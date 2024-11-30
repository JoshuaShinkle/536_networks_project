from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_0
from ryu.lib.packet import packet, ethernet, ipv4, arp
from ryu.lib.packet import ether_types
from ryu.topology.api import get_switch, get_link
from ryu.topology import event
import networkx as nx

class RENETController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_0.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(RENETController, self).__init__(*args, **kwargs)
        self.net = nx.DiGraph()  # Network topology graph
        self.mac_to_port = {}   # MAC address to switch port mapping
        self.mst = nx.Graph()   # Minimum Spanning Tree (MST) for broadcasts

    def add_flow(self, datapath, match, actions):
        """Add a flow to the switch."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        flow_mod = parser.OFPFlowMod(
            datapath=datapath,
            match=match,
            cookie=0,
            command=ofproto.OFPFC_ADD,
            idle_timeout=0,
            hard_timeout=0,
            priority=ofproto.OFP_DEFAULT_PRIORITY,
            flags=ofproto.OFPFF_SEND_FLOW_REM,
            actions=actions,
        )
        datapath.send_msg(flow_mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        """Handle incoming packets."""
        msg = ev.msg
        datapath = msg.datapath
        in_port = msg.in_port
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)

        # Ignore LLDP packets
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src
        dpid = datapath.id

        self.logger.info("Packet-In: datapath=%s in_port=%s src=%s dst=%s",
                         dpid, in_port, src, dst)


        # Learn the source MAC address to avoid flooding next time
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        # Check if the destination MAC is known
        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            path = self.find_best_path(src, dst)
            if path:
                self.logger.info("Path found: %s", path)
                self.install_path(path, pkt, datapath)
                return
            else:
                self.logger.info("Flooding for unknown destination: %s", dst)
                out_port = datapath.ofproto.OFPP_FLOOD

        actions = [datapath.ofproto_parser.OFPActionOutput(out_port)]
        match = datapath.ofproto_parser.OFPMatch(
            in_port=in_port,
            dl_src=src,
            dl_dst=dst
        )
        print(f'Packet-In: {dpid} {in_port} {src} {dst}')
        self.add_flow(datapath, match, actions)
        self.send_packet(datapath, msg.buffer_id, in_port, actions, msg.data)

    def send_packet(self, datapath, buffer_id, in_port, actions, data=None):
        """Send a packet to the switch."""
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

    def find_best_path(self, src, dst):
        """Find the best path between two nodes."""
        if src not in self.net or dst not in self.net:
            self.logger.warning("Source or destination not in topology: src=%s, dst=%s", src, dst)
            return None

        try:
            k_paths = list(nx.shortest_simple_paths(self.net, source=src, target=dst))[:5]
            self.logger.info("K-shortest paths for %s -> %s: %s", src, dst, k_paths)

            best_path = None
            for path in k_paths:
                bottleneck_bw = min(self.net[path[i]][path[i + 1]]['bw'] for i in range(len(path) - 1))
                best_path = path
                break  # Select the first available path for OpenFlow 1.0 simplicity
            return best_path
        except nx.NetworkXNoPath:
            self.logger.warning("No path found for %s -> %s", src, dst)
            return None

    def install_path(self, path, pkt, datapath):
        """Install the flow rules for the given path."""
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        src_ip = pkt.get_protocol(ipv4.ipv4).src
        dst_ip = pkt.get_protocol(ipv4.ipv4).dst

        for i in range(len(path) - 1):
            src_dpid = path[i]
            dst_dpid = path[i + 1]
            out_port = self.net[src_dpid][dst_dpid]['port']

            match = parser.OFPMatch(dl_src=src_ip, dl_dst=dst_ip)
            actions = [parser.OFPActionOutput(out_port)]
            self.add_flow(datapath, match, actions)

    @set_ev_cls(event.EventSwitchEnter)
    def _switch_enter_handler(self, ev):
        self.logger.info("Switch entered: %s", ev.switch.dp.id)
        self.update_topology()

    @set_ev_cls(event.EventLinkAdd)
    def _link_add_handler(self, ev):
        self.logger.info("Link added: %s -> %s", ev.link.src, ev.link.dst)
        self.update_topology()

    def update_topology(self):
        """Update the topology graph."""
        self.net.clear()
        switches = get_switch(self, None)
        links = get_link(self, None)

        for switch in switches:
            self.net.add_node(switch.dp.id)

        for link in links:
            self.net.add_edge(link.src.dpid, link.dst.dpid,
                              port=link.src.port_no, bw=100)  # Assume default bandwidth
            self.net.add_edge(link.dst.dpid, link.src.dpid,
                              port=link.dst.port_no, bw=100)
        
        self.mst = nx.minimum_spanning_tree(self.net.to_undirected())

        self.logger.info("Topology updated: %s", self.net.edges(data=True))
        self.logger.info("Updated MST: %s", self.mst.edges(data=True))
