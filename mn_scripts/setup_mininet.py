#!/usr/bin/env python3
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel

def setup():
    setLogLevel('info')

    # Create a Mininet network
    net = Mininet()

    # Add a remote Ryu controller
    ryu_controller = RemoteController('ryu', ip='ryu', port=6633)
    net.addController(ryu_controller)

    # Add switches and hosts
    s1 = net.addSwitch('s1')

    h1 = net.addHost('h1')
    h2 = net.addHost('h2')
    print("here")

    # Link hosts to the switch
    net.addLink(h1, s1)
    net.addLink(h2, s1)

    # Start the network
    net.start()

    # Test connectivity
    net.pingAll()

    # Drop to CLI
    CLI(net)

    # Stop the network
    net.stop()

if __name__ == '__main__':
    setup()
