from cassandra.cluster import Cluster
import json

class PlayerSessionService(object):

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
        self.session.execute("""
            CREATE TABLE IF NOT EXISTS %s (
                event text,
                country text,
                player_id bigint,
                session_id bigint,
                ts date,
                PRIMARY KEY (player_id)
            );
            """ % (keyspace + "_table"))
    
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
            # if country is a key in an end event, the country field is thought as null
            



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
                "player_id":"10e123",
                "session_id":"10a23",
                "ts":"2016-12-02T12:48:05.520022"
            }
        """
        e2 = """
            {
                "event":"end",
                "player_id":"10e123",
                "session_id":"10a23",
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