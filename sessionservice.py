from cassandra.cluster import Cluster
import json, yaml
import Queue
import time, threading

""" Session service module to interact with Cassandra cluster.

    Only works with Session JSON objects given in the right format.
"""

class Waiter(threading.Thread):
    """ A waiter thread that waits for every async execution to end
           
        The waiter ends when the flag is_shutting_down is True.
    """
    def __init__(self, queue):
        threading.Thread.__init__(self)
        self.is_shutting_down = False
        self.futures = queue

    def run(self):
        """ Waits for every asynchronous execution in FIFO mode
        """
        def handle_error(error):
            print("Async execution error: %s" % str(error))

        # if the flag is false
        while not self.is_shutting_down:

            if not self.futures.empty():
                future = self.futures.get()
                future.add_errback(handle_error) # handle error messages

            else:
                time.sleep(1) # queue is empty

        # if the flag is true, process the rest of the queue
        while not self.futures.empty():
            future = self.futures.get()
            future.add_errback(handle_error)

class PlayerSessionService(object):
    """ A Python class that can instantiate a service that connects to a Cassandra cluster.
        To scale up the load of the application, it is recommended to instantiate as many
        PlayerSessionService as needed and run them in parallel.
    """
    YEAR_IN_SECONDS = 31556952 # time to live (TTL)

    def __init__(self, keyspace, cluster_address=None):
        """ Initializes a service that consumes player sessions from a Cassandra cluster.
            Arguments:
                keyspace (string) : sets the default the keyspace for all queries
                cluster_address=None : an array of IP addresses to cluster nodes
        """

        # For multithreading, a parallel thread will wait for all asynchronous cql requests
        # to end. The parallel thread will end itself when self.shutdown is called.
        self.futures = Queue.Queue()
        self.waiter = Waiter(self.futures)
        self.waiter.start()

        # May need to authenticate
        if cluster_address is not None:
            self.cluster = Cluster(cluster_address)
        else:
            self.cluster = Cluster()
        
        # Use the keyspace
        self.session = self.cluster.connect()
        self.session.execute("""
            CREATE KEYSPACE IF NOT EXISTS %s
            WITH replication = {'class' : 'SimpleStrategy', 'replication_factor' : 1};
            """ % (keyspace))
        self.session.execute("USE %s;" % (keyspace))
        
        # The strategy to avoid sorting after querying is to use two tables.

        # In exchange for higher memory, the query time will be reduced.
        # Cassandra's compaction algorithm is used to clean up the second, temporary table
        # to partially mitigate the memory consumption, assuming a session lasts shorter
        # than the tombstone time period (10 days by default). The drawback can use at most
        # twice as much memory than the amount of received data.

        # Initialize a table called <keyspace>_completed
        # The completed table contains completed sessions ordered by end time for each player
        # This is the only table queried by the API fetch function
        self.completed = keyspace + "_completed"
        self.session.execute("""
            CREATE TABLE IF NOT EXISTS %s(
                session_id uuid,
                player_id ascii,
                country text,
                start_time timestamp,
                end_time timestamp,
                PRIMARY KEY((player_id), end_time)
            )
            WITH CLUSTERING ORDER BY(end_time DESC);
            """ % (self.completed))
        
        # Initialize the secondary, temporary table called <keyspace>_incomplete
        # The incomplete table contains event as they come in from the API receive function
        # If two events are matched, a session is completed and is then inserted into the
        # completed table.
        self.incomplete = keyspace + "_incomplete"
        self.session.execute("""
            CREATE TABLE IF NOT EXISTS %s(
                player_id ascii,
                session_id uuid,
                country text,
                start_time timestamp,
                end_time timestamp,
                PRIMARY KEY(player_id, session_id)
            );
        """ % (self.incomplete))

        
    
    def receive_events(self, sessions):
        """ Receives a batch of events in encoded json objects to insert into the database
            
            A batch has size of maximum 10 and minimum 1
            
            Takes:
                sessions: a json object containing a list of session events
            
            Note: The timestamp must be formatted as a string like "2016-12-02T22:49:05.520022"
        """
        # convert json encoding to python
        sessions = yaml.safe_load(sessions)

        # verify batch size
        if len(sessions) == 0 or len(sessions) > 10:
            raise AttributeError("Batch size is 0 or greater than 10: size %d" % (len(sessions)))

        for decoded in sessions:
            decoded = yaml.safe_load(decoded)
            
            # verify json object schema and integrity
            keys = decoded.keys()
            if len(keys) > 5 or len(keys) == 0:
                raise AttributeError("JSON object has incompatible schema")
            for key in keys:
                if key not in ['event', 'country', 'player_id', 'session_id', 'ts']:
                    raise AttributeError("JSON object has incompatible key: %s" % (key))
            
            # Insert into incomplete table
            cql_insert = ""
            
            # Start event
            if decoded['event'] == 'start':
                cql_insert = """
                    INSERT INTO %s (player_id, session_id, country, start_time) 
                    VALUES ('%s', %s, '%s', '%s')
                    USING TTL %d;
                    """ % (self.incomplete,
                    decoded['player_id'],
                    decoded['session_id'],
                    decoded['country'],
                    decoded['ts'].replace('T', " ")[:-3], # format timestamp
                    PlayerSessionService.YEAR_IN_SECONDS)

            # End event
            else:
                cql_insert = """
                    INSERT INTO %s (player_id, session_id, end_time) 
                    VALUES ('%s', %s, '%s')
                    USING TTL %d;
                    """ % (self.incomplete,
                    decoded['player_id'],
                    decoded['session_id'],
                    decoded['ts'].replace('T', " ")[:-3], # format timestamp
                    PlayerSessionService.YEAR_IN_SECONDS)

            # Execute the insertion request
            self.session.execute(cql_insert)

            # Look if the session is completed
            cql_check_completion = """
                SELECT * FROM %s
                WHERE player_id='%s' AND session_id=%s;
            """ % (self.incomplete, decoded['player_id'], decoded['session_id'])

            rows = self.session.execute(cql_check_completion)
            for row in rows:
                # start time and end time are present
                if row.start_time and row.end_time:
                    
                    # start time is later than end time
                    if not row.start_time < row.end_time:
                        raise AttributeError(
                            "Start timestamp %s is later than end timestamp %s in session_id: %s"
                            % (row.start_time, row.end_time, decoded['session_id']))

                    # insert this session into the completed table
                    self.futures.put(self.session.execute_async("""
                        INSERT INTO %s ( player_id, session_id, country, start_time, end_time)
                        VALUES (
                            '%s', %s, '%s', '%s', '%s'
                        )
                        USING TTL %d;
                        """ % (self.completed,
                        row.player_id,
                        row.session_id,
                        row.country,
                        str(row.start_time)[:-3],
                        str(row.end_time)[:-3],
                        PlayerSessionService.YEAR_IN_SECONDS)))

                    # delete the complete session from the incomplete table
                    cql_delete = "DELETE FROM %s WHERE player_id='%s' AND session_id=%s;"\
                        % (self.incomplete, row.player_id, str(row.session_id))
                    self.futures.put(self.session.execute_async(cql_delete))
                    

    def fetch(self, player_id):
        """ Returns the last 20 completed sessions for the given player

            Takes:
                player_id: a string representing the player
            Return type is a JSON object:
                list of {player_id:'player_id', session_id:'session_id', country:'country',
                start_time:'start timestamp', end_time:'end timestamp'}
        """
        result = self.session.execute("""
            SELECT JSON * FROM %s
            WHERE player_id='%s'
            LIMIT 20;
            """ % (self.completed, player_id))

        return json.dumps(list(result))


    def shutdown(self):
        """ Shuts down the service by waiting for all threads to finish
        """
        self.waiter.is_shutting_down = True
        self.waiter.join()


if __name__ == "__main__":
    print("Performs basic test")

    # instantiate a service object
    pss = PlayerSessionService('test')

    # test the receive function
    def test_receive():
        e1 = """
            {
                "event":"start",
                "country":"CA",
                "player_id":"0a2d12a1a7e145de8bae44c0c6e06629",
                "session_id":"4a0c43c9-c43a-42ff-ba55-67563dfa35d4",
                "ts":"2016-12-02T12:48:05.520022"
            }
        """
        e2 = """
            {
                "event":"end",
                "player_id":"0a2d12a1a7e145de8bae44c0c6e06629",
                "session_id":"4a0c43c9-c43a-42ff-ba55-67563dfa35d4",
                "ts":"2016-12-02T12:49:05.520022"
            }
        """
        e3 = """
            {
                "event":"end",
                "player_id":"testtest",
                "session_id":"7a7c77c7-c43a-42ff-ba55-67563dfa35d4",
                "ts":"2019-12-12T12:12:12.121212"
            }
        """
        e4 = """
            {
                "event":"end",
                "player_id":"0a2d12a1a7e145de8bae44c0c6e06629",
                "session_id":"4f0f43f9-c43a-42ff-ba55-67563dfa35d4",
                "ts":"2018-12-02T12:55:05.520022"
            }
        """
        e5 = """
            {
                "event":"start",
                "country": "US",
                "player_id":"0a2d12a1a7e145de8bae44c0c6e06629",
                "session_id":"4f0f43f9-c43a-42ff-ba55-67563dfa35d4",
                "ts":"2018-12-02T12:49:05.520022"
            }
        """
        my_events = [e1, e2, e3, e4, e5]
        pss.receive_events(json.dumps(my_events))

    test_receive()

    # test the fetch function
    def test_fetch():
        player_id = "0a2d12a1a7e145de8bae44c0c6e06629"

        result = pss.fetch(player_id)

        print(yaml.safe_load(result))
    
    test_fetch()

    pss.shutdown()