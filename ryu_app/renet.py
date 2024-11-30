from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_0
from ryu.topology.api import get_switch, get_link
from ryu.topology import event
from ryu.lib.packet import packet, ethernet
import networkx as nx
import matplotlib.pyplot as plt
from ryu.app.ofctl.api import get_datapath


class RENETController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_0.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(RENETController, self).__init__(*args, **kwargs)
        self.network_graph = nx.DiGraph()  # Network topology
        self.mst = nx.Graph()  # Minimum Spanning Tree
        self.mac_to_port = {}  # MAC to port mapping on switches
        self.mac_to_switch = {}  # MAC to switch mapping for hosts
        self.blocked_ports = {}
        self.datapaths = {}

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        self.logger.info(f"Switch connected: {datapath.id}")
        self.install_default_flows(datapath)
        # self.datapaths[datapath.id] = datapath

    def install_default_flows(self, datapath):
        """
        Install default flows for LLDP packet handling.
        """
        print("Installing default flows")
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        match = parser.OFPMatch(dl_type=0x88cc)  # LLDP EtherType
        actions = [] # [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, 0)]
        mod = parser.OFPFlowMod(
            datapath=datapath,
            match=match,
            cookie=0,
            command=ofproto.OFPFC_ADD,
            priority=100,
            actions=actions
        )
        datapath.send_msg(mod)

    @set_ev_cls(event.EventSwitchEnter)
    def switch_enter_handler(self, ev):
        """
        Update topology when a new switch enters.
        """
        # keep track of datapath
        # print(ev.switch.dp)
        # self.datapaths[ev.switch.dp.id] = ev.switch.dp
        self.update_topology()

    @set_ev_cls(event.EventLinkAdd)
    def link_add_handler(self, ev):
        """
        Update topology when a new link is added.
        """
        self.update_topology()

    def update_topology(self):
        """
        Build or update the network graph.
        """

        for dpid, ports in self.blocked_ports.items():
            for port_no in ports:
                self.set_port_flooding(dpid, port_no, enable=True)
        self.blocked_ports.clear()
        self.network_graph.clear()

        # Add switches as nodes
        switches = get_switch(self, None)
        for switch in switches:
            dpid = switch.dp.id
            self.datapaths[dpid] = switch.dp
            self.network_graph.add_node(dpid, type='switch')

        # Add links as edges
        links = get_link(self, None)
        for link in links:
            src = link.src.dpid
            dst = link.dst.dpid
            src_port = link.src.port_no
            dst_port = link.dst.port_no

            # Add bidirectional edges with the correct attributes
            self.network_graph.add_edge(src, dst, src_port=src_port, dst_port=dst_port)
            self.network_graph.add_edge(dst, src, src_port=dst_port, dst_port=src_port)

        # Add hosts as nodes (from MAC mapping)
        for mac, switch_info in self.mac_to_switch.items():
            switch_dpid = switch_info['dpid']
            port_no = switch_info['port']
            self.network_graph.add_node(mac, type='host')
            self.network_graph.add_edge(mac, switch_dpid, dst_port=port_no)
            self.network_graph.add_edge(switch_dpid, mac, src_port=port_no)

        self.logger.info("\nUpdated network topology:\nNodes: %s\nEdges: %s\n", self.network_graph.nodes(data=True), self.network_graph.edges(data=False))

        # Compute the Minimum Spanning Tree
        self.mst = nx.minimum_spanning_tree(self.network_graph.to_undirected())
        self.logger.info("\nUpdated MST:\nEdges: %s\n", self.mst.edges(data=False))

        # Block ports not in MST
        for src, dst, edge_data in self.network_graph.edges(data=True):
            if not self.mst.has_edge(src, dst) and self.network_graph.nodes[src]['type'] == 'switch':
                self.set_port_flooding(src, edge_data['src_port'], enable=False)
                self.blocked_ports.setdefault(src, set()).add(edge_data['src_port'])
                # pass



        # draw the network graph
        nx.draw(self.network_graph, with_labels=True, font_weight='bold')
        plt.savefig("network_graph.png")
        plt.close()

        nx.draw(self.mst, with_labels=True, font_weight='bold')
        plt.savefig("mst.png")
        plt.close()

    def set_port_flooding(self, dpid, port_no, enable):
        """
        Enable or disable flooding on a specific port of a switch.
        """
        datapath = self.get_datapath(dpid)
        if not datapath:
            self.logger.warning("Datapath for switch %s not found.", dpid)
            return

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        config = 0
        mask = ofproto.OFPPC_NO_FLOOD

        if not enable:
            config = mask

        mod = parser.OFPPortMod(
            datapath=datapath,
            port_no=port_no,
            hw_addr=datapath.ports[port_no].hw_addr,
            config=config,
            mask=mask
        )
        datapath.send_msg(mod)
        state = "enabled" if enable else "disabled"
        self.logger.info(f"Flooding {state} on port {port_no} of switch {dpid}.")


    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """
        Handle incoming packets and compute paths when necessary.
        """
        msg = ev.msg
        datapath = msg.datapath
        in_port = msg.in_port
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        src = eth.src
        dst = eth.dst
        dpid = datapath.id



        # Ignore LLDP packets
        if eth.ethertype == 0x88cc:# or eth.ethertype == 0x86DD:
            # print("Ignoring LLDP packet")
            return

        print(f"Packet in: {src} -> {dst} on switch {dpid} port {in_port} of type {eth.ethertype}")
        

        # Learn the source host's switch and port
        self.mac_to_switch[src] = {'dpid': dpid, 'port': in_port, 'datapath': datapath}

        

        # Add the source host to the graph if not already present
        if src not in self.network_graph:
            # self.network_graph.add_node(src, type='host')
            # self.network_graph.add_edge(src, dpid, dst_port=in_port)
            # self.network_graph.add_edge(dpid, src, src_port=in_port)
            # self.logger.info(f"Added host {src} connected to switch {dpid} via port {in_port}")
            self.update_topology()
            
        
        # Log the current state of the network graph
        # self.logger.info("Current network graph nodes: %s", self.network_graph.nodes(data=True))
        # self.logger.info("Current network graph edges: %s", self.network_graph.edges(data=True))

        # Check if the destination is known
        if dst in self.mac_to_switch:
            # Compute path and install flow rules
            src_dpid = self.mac_to_switch[src]['dpid']
            dst_dpid = self.mac_to_switch[dst]['dpid']
            path = nx.shortest_path(self.network_graph, src, dst)

            self.logger.info(f"Path computed from {src} to {dst}: {path}")
            self.install_path_flows(path, src, dst)
            self.install_path_flows(path[::-1], dst, src)
            # send packet
            out_port = datapath.ofproto.OFPP_TABLE
            actions = [datapath.ofproto_parser.OFPActionOutput(out_port)]
            self.send_packet(datapath, msg.buffer_id, in_port, actions, msg.data)
            return
        else:
            # Flood the packet to discover the destination
            self.logger.info(f"Flooding packet")
            self.flood_packet_mst(datapath, in_port, msg)
            return


    def flood_packet_mst(self, datapath, in_port, msg):
        """
        Flood the packet along the MST.
        """
        dpid = datapath.id
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        # for neighbor in self.mst.neighbors(dpid):
        #     edge_data = self.network_graph.get_edge_data(dpid, neighbor)
        #     if edge_data['src_port'] != in_port:
        #         # print(f"Flooding packet from {dpid} to {neighbor}")
        #         out_port = edge_data['src_port']
        #         actions = [datapath.ofproto_parser.OFPActionOutput(out_port)]
        #         self.send_packet(datapath, msg.buffer_id, in_port, actions, msg.data)

        # just flood to all neighbors
        actions = [datapath.ofproto_parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        self.send_packet(datapath, msg.buffer_id, in_port, actions, msg.data)


    def install_path_flows(self, path, src, dst):
        """
        Install flow rules for each switch along the path.
        """
        for i in range(len(path) - 1):
            curr_node = path[i]
            next_node = path[i + 1]

            curr_node_type = self.network_graph.nodes[curr_node]['type']
            next_node_type = self.network_graph.nodes[next_node]['type']

            # Find the output port for the current node
            if curr_node_type == 'host':
                # current node is a host, no need to install flow
                continue
            else:
                # next node is a switch or host, so the output port is the one connected to the next switch
                out_port = self.network_graph.edges[curr_node, next_node]['src_port']

            # Install flow rule on the current switch
            datapath = self.get_datapath(curr_node)
            if datapath:
                self.add_flow(datapath, src, dst, out_port)


    def send_packet(self, datapath, buffer_id, in_port, actions, data=None):
        """
        Send a packet to the switch.
        """
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=buffer_id,
            in_port=in_port,
            actions=actions,
            data=data
        )
        datapath.send_msg(out)


    def add_flow(self, datapath, src, dst, out_port):
        """
        Add a flow rule to the given datapath.
        """
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        match = parser.OFPMatch(dl_src=src, dl_dst=dst)
        actions = [parser.OFPActionOutput(out_port)]
        mod = parser.OFPFlowMod(
            datapath=datapath,
            match=match,
            priority=1,
            actions=actions
        )
        datapath.send_msg(mod)
        self.logger.info(f"Flow installed: {datapath.id}, {src} -> {dst} via port {out_port}")

    def get_datapath(self, dpid):
        """
        Retrieve the datapath object for a given DPID.
        """
        if dpid in self.datapaths:
            return self.datapaths[dpid]
        else:
            print(f"Datapath for switch {dpid} not found.")
            print(f"Available datapaths: {self.datapaths}")
            return None
        for dp in self.mac_to_switch.values():
            if dp['dpid'] == dpid:
                return dp['datapath']
        return None
