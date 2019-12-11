from cassandra.cluster import Cluster

class PlayerSessionService(object):

    def __init__(self, cluster_address=None, keyspace=None):
        """ Initializes a service that consumes player sessions from a Cassandra cluster.
            Arguments:
                cluster_address=None : an array of IP addresses to cluster nodes
                keyspace=None : sets the default the keyspace for all queries
        """

        if cluster_address is not None:
            self.cluster = Cluster(cluster_address)
        else:
            self.cluster = Cluster()
        
        if keyspace is not None:
            self.session = self.cluster.connect(keyspace)
        else:
            self.session = self.cluster.connect()

if __name__ == "__main__":
    print("Performs basic test")

    pss = PlayerSessionService()