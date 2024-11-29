try:
    from mininet.net import Mininet
    from mininet.topo import Topo
    from mininet.node import RemoteController, OVSSwitch
    from mininet.link import TCLink  # For bandwidth-limited links
    from mininet.log import setLogLevel, info
    from mininet.cli import CLI
    import random
    from time import sleep
    import time
    import threading
    import os
except:
    Exception(ImportError)

# Defining constants for links easily changeable or customizable to each link
# For performance purposes keep it between 1 <= bw <= 16
ETH_BANDWIDTH = 16 # Bandwidth of 16 Mbps or 16/8 MBps
SAT_BANDWIDTH = 1 # Bandwidth of 1 Mbps or 1/8 MBps
LINK_CHANGE_INTERVAL = 10 # seconds
PING_INTERVAL = 6 # seconds
PING_TEST_LENGTH = 18 # seconds

# Ryu Controller IP and Port
RYU_IP = "127.0.0.1"  # Docker container name or actual IP
RYU_PORT = 6633

class RenetTopo(Topo):
    def build(self):
        # Hosts
        host1 = self.addHost('h1')
        host2 = self.addHost('h2')
        host3 = self.addHost('h3')
        host4 = self.addHost('h4')

        # Switches
        switch1 = self.addSwitch('s1')
        switch2 = self.addSwitch('s2')
        switch3 = self.addSwitch('s3')
        switch4 = self.addSwitch('s4')

        # Host Links
        self.addLink(host1, switch1, bw=ETH_BANDWIDTH)
        self.addLink(host2, switch1, bw=ETH_BANDWIDTH)
        self.addLink(host3, switch3, bw=ETH_BANDWIDTH)
        self.addLink(host4, switch2, bw=ETH_BANDWIDTH)

        # Switch Links
        self.addLink(switch1, switch2, bw=ETH_BANDWIDTH)
        self.addLink(switch1, switch4, bw=ETH_BANDWIDTH)
        self.addLink(switch1, switch3, bw=SAT_BANDWIDTH)
        self.addLink(switch2, switch4, bw=ETH_BANDWIDTH)
        self.addLink(switch2, switch3, bw=ETH_BANDWIDTH)
        self.addLink(switch3, switch4, bw=ETH_BANDWIDTH)

def change_link_bandwidth(net, node1, node2, new_bw):
    try:
        link = net.linksBetween(net[node1], net[node2])[0]  # Get the link object
        info(f"*** Changing bandwidth between {node1} and {node2} to {new_bw} Mbps\n")
        
        # Link Bandwidth changes both interfaces 
        link.intf1.config(bw=new_bw)
        link.intf2.config(bw=new_bw)
        info(f"*** Bandwidth between {node1} and {node2} updated successfully\n")

    # Index error that results from some miscall of the mininet node networks (no link usually)
    except IndexError:
        info(f"*** Error: No link found between {node1} and {node2}\n")

def simulate_real_links(net, links, min_bw=SAT_BANDWIDTH, max_bw=ETH_BANDWIDTH):
    link = random.choice(links)
    new_bw = random.randint(min_bw, max_bw)
    change_link_bandwidth(net, link[0], link[1], new_bw)
    sleep(LINK_CHANGE_INTERVAL)

def setup_servers(net):
    for h in net.hosts:
        print(f"Starting server at {h.IP()}")
        h.cmd(f"python3 server.py {h.IP()} 10001 &")

    time.sleep(2)

def run_experiment(net):
    hosts = net.hosts
    
    for i, src in enumerate(hosts):
        dst = hosts[(i+1) % len(hosts)]

        print(f"Sending to server {dst.IP()} from client {src.IP()}")
        src.cmd(f"python3 client.py {dst.IP()} 10001 2 &")

    time.sleep(5)

def random_ping_test(net):
    # Get a list of all hosts in the network
    hosts = net.hosts

    # Randomly choose two distinct hosts
    host1, host2 = random.sample(hosts, 2)

    # Ensure the hosts are properly initialized and have IPs
    print(f"*** Checking IPs of {host1.name} and {host2.name}")
    print(f"{host1.name} IP: {host1.IP()}")
    print(f"{host2.name} IP: {host2.IP()}")

    # Make sure the host interfaces are up (some Mininet configurations might cause them to be down)
    host1.cmd('ifconfig', host1.name + '-eth0', 'up')
    host2.cmd('ifconfig', host2.name + '-eth0', 'up')

    # Randomly select the number of pings to send (e.g., between 1 and 10)
    ping_count = random.randint(1, 10)
    print(f"*** Pinging from {host1.name} to {host2.name} with {ping_count} pings")

    # Run the ping command with the random ping count
    result = host1.cmd(f'ping -c {ping_count} {host2.IP()}')

    # Print the result of the ping command
    print(result)

    # Optionally, add a sleep to pause between pings
    sleep(PING_INTERVAL) 

def main():
    try:
        setLogLevel('info')  # Set Mininet log level to info

        # Create the network
        info('*** Creating network topology\n')
        #topo = RenetTopo()

        # Initialize Mininet
        net = Mininet(topo=RenetTopo(), controller=None, switch=OVSSwitch, link=TCLink)

        # Add the Ryu controller
        info('*** Adding Ryu controller\n')
        ryu_controller = net.addController('c0', controller=RemoteController, ip=RYU_IP, port=RYU_PORT)

        # Start the network
        info('*** Starting network\n')
        net.start()

        # Links to dynamically change bandwidth
        links = [
            ('h1', 's1'),
            ('h2', 's1'),
            ('h3', 's3'),
            ('h4', 's2'),
            ('s1', 's2'),
            ('s1', 's4'),
            ('s1', 's3'),
            ('s2', 's4'),
            ('s2', 's3'),
            ('s3', 's4'),
        ]
        # arguements are mininet object, link list, min_bw at least > 0, max_bw, intervals between changing
        #simulate_real_links(net,links,SAT_BANDWIDTH,ETH_BANDWIDTH,LINK_CHANGE_TIME)
        
        # Start a separate thread for continuous link adjustments --Not needed currently
        # info('*** Starting background thread for continuous link adjustments\n')
        # adjustment_thread = threading.Thread(target=simulate_real_links, args=(net, links, SAT_BANDWIDTH, ETH_BANDWIDTH, LINK_CHANGE_INTERVAL), daemon=True)
        # adjustment_thread.start()

        # Launch CLI
        # Note this does not work with link adjustments so do not expect
        # being able to write and read link details via the CLI
        # with lock:
        #     info('*** Running CLI\n')
        #     CLI(net)

        setup_servers(net)

        while True:
            simulate_real_links(net, links, SAT_BANDWIDTH, ETH_BANDWIDTH)
            random_ping_test(net)
            run_experiment(net)

    except KeyboardInterrupt:
        # Handle keyboard interrupt gracefully
        info('*** KeyboardInterrupt received, stopping network\n')

    finally:
        # Ensure the network stops and threads are joined properly
        info('*** Stopping network\n')
        net.stop()

        # Wait for the link adjustment thread to finish gracefully
        #adjustment_thread.join(timeout=5)
        # Allow the background thread to continue running even after stopping the network
        info('*** Extra threads stopped\n')
        

if __name__ == '__main__':
    main()
