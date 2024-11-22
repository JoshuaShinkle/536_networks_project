from mininet.net import Mininet
from mininet.topo import Topo
from mininet.node import RemoteController
from mininet.link import TCLink  # For bandwidth-limited links
from mininet.log import setLogLevel, info
from mininet.cli import CLI
from time import sleep

# Defining constants for links easily changeable or customizable to each link
eth_bandwidth = 10
sat_bandwidth = 10

class RenetTopo(Topo):
    def build(self):
        # # Host List
        # host1 = self.addHost('h1')
        # host2 = self.addHost('h2')
        # host3 = self.addHost('h3')
        # host4 = self.addHost('h4')

        # # Switch List
        # switch1 = self.addSwitch("s1")
        # switch2 = self.addSwitch("s2")
        # switch3 = self.addSwitch("s3")
        # switch4 = self.addSwitch("s4")

        # # Link List
        # # Host Links
        # self.addLink(host1, switch1, bw=eth_bandwidth)
        # self.addLink(host2, switch1, bw=eth_bandwidth)
        # self.addLink(host3, switch3, bw=eth_bandwidth)
        # self.addLink(host4, switch2, bw=eth_bandwidth)

        # # Switch Links
        # # s1
        # self.addLink(switch1, switch2, bw=eth_bandwidth)
        # self.addLink(switch1, switch4, bw=eth_bandwidth)
        # self.addLink(switch1, switch3, bw=sat_bandwidth)  # Throttled link

        # # s2
        # self.addLink(switch2, switch4, bw=eth_bandwidth)
        # self.addLink(switch2, switch3, bw=eth_bandwidth)

        # # s3
        # self.addLink(switch3, switch4, bw=eth_bandwidth)
        host1 = self.addHost('h1')
        host2 = self.addHost('h2')
        s1 = self.addSwitch("s1")
        self.addLink(host1, s1, bw=eth_bandwidth)
        self.addLink(host2, s1, bw=eth_bandwidth)


if __name__ == '__main__':
    setLogLevel('info')  # Set Mininet log level to info

    # Ryu Controller IP and Port
    RYU_IP = "ryu_controller"  # Docker container name or actual IP
    RYU_PORT = 6633

    # Create the network
    info('*** Creating network topology\n')
    topo = RenetTopo()

    # Initialize Mininet
    net = Mininet(topo=topo, controller=None, link=TCLink)

    # Add the Ryu controller
    info('*** Adding Ryu controller\n')
    ryu_controller = net.addController('c0', controller=RemoteController, ip=RYU_IP, port=RYU_PORT)

    # Start the network
    info('*** Starting network\n')
    net.start()

    h1 = net['h1']
    h2 = net['h2']
    s1 = net['s1']

    link = net.linksBetween(h1, s1)[0]

    print("*** Running bandwidth test before changing link speed")
    h1.cmd('iperf -s &')  # Start iperf server on h1
    sleep(1)  # Allow server to start
    print(h2.cmd('iperf -c 10.0.0.1 -t 5'))  # Run iperf client on h2

    print("*** Changing bandwidth dynamically to 2 Mbps")
    link.intf1.config(bw=2)
    link.intf2.config(bw=2)
    sleep(1)

    print("*** Running bandwidth test after changing link speed")
    print(h2.cmd('iperf -c 10.0.0.1 -t 5'))  # Run iperf client again on h2

    # Test connectivity
    # info('*** Testing network connectivity\n')
    # net.pingAll()

    # Launch CLI
    info('*** Running CLI\n')
    CLI(net)

    # Stop the network
    info('*** Stopping network\n')
    net.stop()
