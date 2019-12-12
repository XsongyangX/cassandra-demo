from cassandra.cluster import Cluster
import json

class PlayerSessionService(object):

    YEAR_IN_SECONDS = 31556952

    def __init__(self, keyspace, cluster_address=None):
        """ Initializes a service that consumes player sessions from a Cassandra cluster.
            Arguments:
                keyspace (string) : sets the default the keyspace for all queries
                cluster_address=None : an array of IP addresses to cluster nodes
        """

        if cluster_address is not None:
            self.cluster = Cluster(cluster_address)
        else:
            self.cluster = Cluster()
        
        # Use the keyspace
        self.session = self.cluster.connect()
        self.session.execute("""
            CREATE KEYSPACE IF NOT EXISTS %s
            WITH replication = {'class' : 'SimpleStrategy', 'replication_factor' : 3};
            """ % (keyspace))
        self.session.execute("USE %s;" % (keyspace))
        
        # Initialize a table called <keyspace>_table
        self.table = keyspace + "_table"
        self.session.execute("DROP TABLE %s;" % (self.table))
        self.session.execute("""
            CREATE TABLE IF NOT EXISTS %s (
                event text,
                country text,
                player_id text,
                session_id uuid,
                ts text,
                PRIMARY KEY (player_id)
            );
            """ % (self.table))
    
    def receive_events(self, sessions):
        """ Receives a batch of events in encoded json objects to insert into the database
            A batch has size of maximum 10 and minimum 1
        """

        # verify batch size
        if len(sessions) == 0 or len(sessions) > 10:
            raise AttributeError("Batch size is 0 or greater than 10")

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
            
            
            cql_request = ""
            
            # if country is a key in an end event, the country field is thought as null
            if event_type is "end":
                cql_request = """
                INSERT INTO %s (
                    event, player_id, session_id, ts
                ) 
                VALUES(
                    '%s', '%s', %s, '%s'
                )
                USING TTL %d;
                """ % (self.table,
                decoded['event'], # no country
                decoded['player_id'], # as string
                decoded['session_id'],
                decoded['ts'],
                PlayerSessionService.YEAR_IN_SECONDS) # data expires after one year
            
            # start request
            else:
                cql_request = """
                INSERT INTO %s (
                    event, country, player_id, session_id, ts
                ) 
                VALUES(
                    '%s', '%s', '%s', %s, '%s'
                )
                USING TTL %d;
                """ % (self.table,
                decoded['event'], decoded['country'],
                decoded['player_id'], # as string
                decoded['session_id'],
                decoded['ts'],
                PlayerSessionService.YEAR_IN_SECONDS) # data expires after one year
                
            # insert the entry
            self.session.execute(cql_request)
            


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