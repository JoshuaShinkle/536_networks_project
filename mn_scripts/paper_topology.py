try:
    from mininet.topo import Topo

except:
    Exception(ImportError)

# Defining constants for links easily changable or customizable to each link
eth_bandwidth = 10
sat_bandwidth = 10

class RenetTopo ( Topo ):
    def build (self):

        # Host List
        host1 = self.addHost('h1')
        host2 = self.addHost('h2')
        host3 = self.addHost('h3')
        host4 = self.addHost('h4')

        # Switch List
        switch1 = self.addSwitch("s1")
        switch2 = self.addSwitch("s2")
        switch3 = self.addSwitch("s3")
        switch4 = self.addSwitch("s4")

        #Link List
        #Host Links
        self.addLink(host1, switch1, bw=eth_bandwidth)
        self.addLink(host2, switch1, bw=eth_bandwidth)
        self.addLink(host3, switch3, bw=eth_bandwidth)
        self.addLink(host4, switch2, bw=eth_bandwidth)
        #Switch Links
        #s1
        self.addLink(switch1, switch2, bw=eth_bandwidth)
        self.addLink(switch1, switch4, bw=eth_bandwidth)
        self.addLink(switch1, switch3, bw=sat_bandwidth)   # This is the one that is throttled
        #s2
        self.addLink(switch2, switch4, bw=eth_bandwidth)
        self.addLink(switch2, switch3, bw=eth_bandwidth)
        #s3
        self.addLink(switch3, switch4, bw=eth_bandwidth)
        
topos = { 'mytopo' : (lambda: RenetTopo() ) }