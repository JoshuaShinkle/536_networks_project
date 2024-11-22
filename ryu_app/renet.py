from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, arp
from ryu.lib.packet import ether_types
from ryu.topology.api import get_switch, get_link
from ryu.topology import event
import networkx as nx


class RENETController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(RENETController, self).__init__(*args, **kwargs)
        self.net = nx.DiGraph()  # Network topology graph
        self.mac_to_port = {}   # MAC address to switch port mapping

    def add_flow(self, datapath, match, actions, priority=1):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        instructions = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]

        flow_mod = parser.OFPFlowMod(datapath=datapath,
                                      priority=priority,
                                      match=match,
                                      instructions=instructions)
        datapath.send_msg(flow_mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        print("Packet in")
        msg = ev.msg
        datapath = msg.datapath
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)

        # Ignore LLDP packets
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src
        dpid = datapath.id

        self.logger.info("Packet in: %s -> %s (Switch: %s, Port: %s)", src, dst, dpid, in_port)

        # Learn source MAC address
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        # Check if destination is known
        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            path = self.find_best_path(src, dst)
            if path:
                self.logger.info("Path found: %s", path)
                self.install_path(datapath, path, pkt, in_port)
                return
            else:
                self.logger.info("Flooding for unknown destination: %s", dst)
                out_port = datapath.ofproto.OFPP_FLOOD

        actions = [datapath.ofproto_parser.OFPActionOutput(out_port)]
        match = datapath.ofproto_parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
        self.add_flow(datapath, match, actions)
        self.send_packet(datapath, msg.buffer_id, in_port, actions, msg.data)
        print("Packet in handled")

    def send_packet(self, datapath, buffer_id, in_port, actions, data=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=buffer_id,
                                  in_port=in_port,
                                  actions=actions,
                                  data=data)
        datapath.send_msg(out)

    def find_best_path(self, src, dst):
        try:
            k_paths = list(nx.shortest_simple_paths(self.net, source=src, target=dst, weight='bw'))[:5]
            best_path = None
            best_bandwidth = 0

            for path in k_paths:
                bottleneck_bw = min(self.net[path[i]][path[i + 1]]['bw'] for i in range(len(path) - 1))
                if bottleneck_bw > best_bandwidth:
                    best_bandwidth = bottleneck_bw
                    best_path = path

            return best_path
        except nx.NetworkXNoPath:
            return None

    def install_path(self, datapath, path, pkt, in_port):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        src_ip = pkt.get_protocol(ipv4.ipv4).src
        dst_ip = pkt.get_protocol(ipv4.ipv4).dst

        for i in range(len(path) - 1):
            src_dpid = path[i]
            dst_dpid = path[i + 1]
            out_port = self.net[src_dpid][dst_dpid]['port']

            match = parser.OFPMatch(eth_src=src_ip, eth_dst=dst_ip)
            actions = [parser.OFPActionOutput(out_port)]
            self.add_flow(datapath, match, actions)

    @set_ev_cls(event.EventSwitchEnter)
    def _switch_enter_handler(self, ev):
        self.logger.info("Switch entered: %s", ev.switch.dp.id)
        self.update_topology()

    @set_ev_cls(event.EventSwitchLeave)
    def _switch_leave_handler(self, ev):
        self.logger.info("Switch left: %s", ev.switch.dp.id)
        self.update_topology()

    @set_ev_cls(event.EventLinkAdd)
    def _link_add_handler(self, ev):
        self.logger.info("Link added: %s -> %s", ev.link.src, ev.link.dst)
        self.update_topology()

    @set_ev_cls(event.EventLinkDelete)
    def _link_delete_handler(self, ev):
        self.logger.info("Link deleted: %s -> %s", ev.link.src, ev.link.dst)
        self.update_topology()

    def update_topology(self):
        print("Updating topology")
        self.net.clear()
        switches = get_switch(self, None)
        links = get_link(self, None)

        for switch in switches:
            self.net.add_node(switch.dp.id)

        for link in links:
            self.net.add_edge(link.src.dpid, link.dst.dpid,
                              port=link.src.port_no, bw=100)  # Assume default bandwidth
            self.net.add_edge(link.dst.dpid, link.src.dpid,
                              port=link.dst.port_no, bw=100)  # Assume default bandwidth
        print("Topology updated")
