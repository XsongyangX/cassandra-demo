from cassandra.cluster import Cluster

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
        

if __name__ == "__main__":
    print("Performs basic test")

    pss = PlayerSessionService('tutorialspoint')

    # pss.session.execute("USE tutorialspoint;")

    pss.session.execute("SELECT * FROM system_schema.keyspaces;")

    