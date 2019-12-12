from cassandra.cluster import Cluster
import json

class PlayerSessionService(object):

    YEAR_IN_SECONDS = 31556952 # time to live (TTL)

    def __init__(self, keyspace, cluster_address=None):
        """ Initializes a service that consumes player sessions from a Cassandra cluster.
            Arguments:
                keyspace (string) : sets the default the keyspace for all queries
                cluster_address=None : an array of IP addresses to cluster nodes
        """

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
        """

        # verify batch size
        if len(sessions) == 0 or len(sessions) > 10:
            raise AttributeError("Batch size is 0 or greater than 10: size %d" % (len(sessions)))

        # convert json encoding to python
        for session in sessions:
            decoded = json.loads(session)

            # verify json object schema and integrity
            event_type = "end"
            keys = decoded.keys()
            if len(keys) > 5 or len(keys) == 0:
                raise AttributeError("JSON object has incompatible schema")
            for key in keys:
                if key is "event" and decoded[key] is "start":
                    event_type = "start"
                if key not in ['event', 'country', 'player_id', 'session_id', 'ts']:
                    raise AttributeError("JSON object has incompatible key: %s" % (key))
            
            # Insert into incomplete table
            cql_request = ""
            
            # Start event
            if event_type == "start":
                cql_request = """
                    INSERT INTO %s (player_id, session_id, country, start_time) 
                    VALUES ('%s', %s, %s, '%s')
                    IF NOT EXISTS
                    USING TTL %d;
                    """ % (self.incomplete,
                    decoded['player_id'],
                    decoded['session_id'],
                    decoded['country'],
                    decoded['start_time'].replace('T', " ")[:-3], # format timestamp
                    PlayerSessionService.YEAR_IN_SECONDS)

            # End event
            else:
                cql_request = """
                    INSERT INTO %s (player_id, session_id, end_time) 
                    VALUES ('%s', %s, '%s')
                    IF NOT EXISTS
                    USING TTL %d;
                    """ % (self.incomplete,
                    decoded['player_id'],
                    decoded['session_id'],
                    decoded['end_time'].replace('T', " ")[:-3], # format timestamp
                    PlayerSessionService.YEAR_IN_SECONDS)

            # insert the entry
            self.session.execute_async(cql_request) # asynchronous

    def fetch(self, player_id):
        """ Returns the last 20 completed sessions for the given player
        """


        pass
            


if __name__ == "__main__":
    print("Performs basic test")

    # instantiate a service object
    pss = PlayerSessionService('tutorialspoint')

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
                "life":3
            }
        """
        my_events = [e1, e2]
        pss.receive_events(my_events)

    test_receive()