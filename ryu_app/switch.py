import time
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_0
from ryu.lib.packet import packet, ethernet
from ryu.lib.packet import ether_types
from ryu.lib import hub

class SimpleSwitch(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_0.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(SimpleSwitch, self).__init__(*args, **kwargs)
        self.datapaths = {}
        self.mac_to_port = {}  # MAC address to port mapping
        self.flow_store = {}  # Store for flow statistics
        self.link_store = {}  # Store for link statistics
        self.stats_interval = 10  # Stats request interval in seconds

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, MAIN_DISPATCHER)
    def _switch_features_handler(self, ev):
        """Handles the switch feature reply."""
        datapath = ev.msg.datapath
        self.datapaths[datapath.id] = datapath

        # Send a default flow mod to prevent packet flooding by default
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        actions = []
        self.add_flow(datapath, 0, match, actions)  # Drop all by default

        # Start periodic stats request in a separate greenlet
        hub.spawn(self._send_stats_request, datapath)

    def add_flow(self, datapath, priority, match, actions):
        """Add a flow entry."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        flow_mod = parser.OFPFlowMod(
            datapath=datapath,
            match=match,
            cookie=0,
            command=ofproto.OFPFC_ADD,
            idle_timeout=0,
            hard_timeout=0,
            priority=priority,
            flags=ofproto.OFPFF_SEND_FLOW_REM,
            actions=actions
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

        # Ignore LLDP packets (used for topology discovery)
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src

        self.logger.info("Packet-In: datapath=%s in_port=%s src=%s dst=%s",
                         datapath.id, in_port, src, dst)

        # Learn the source MAC address to avoid flooding next time
        self.learn_source_mac(datapath, src, in_port)

        # If the destination MAC is known, forward the packet
        if self.mac_to_port(datapath, dst):
            out_port = self.mac_to_port(datapath, dst)
        else:
            out_port = datapath.ofproto.OFPP_FLOOD  # Flood if destination is unknown

        if flow_key not in self.flow_store:
            self.flow_store[flow_key] = {
                'src_dst': flow_key,
                'current_path': [],  # Start with an empty path
                'current_rate': 0,
                'desired_rate': 0,
                'update_time': time.time(),
                'active': True
            }
        flow_info = self.flow_store[flow_key]
        # Append the switch and port as part of the current path (trace the actual path)
        flow_info['current_path'].append((datapath.id, in_port))  # Append switch id and in_port
        actions = [datapath.ofproto_parser.OFPActionOutput(out_port)]
        match = datapath.ofproto_parser.OFPMatch(in_port=in_port, dl_src=src, dl_dst=dst)
        self.add_flow(datapath, 1, match, actions)  # Install flow to avoid flooding next time

        self.send_packet_out(datapath, msg.buffer_id, in_port, actions, msg.data)

    def learn_source_mac(self, datapath, src, in_port):
        """Learn the source MAC address."""
        if datapath.id not in self.mac_to_port:
            self.mac_to_port[datapath.id] = {}
        self.mac_to_port[datapath.id][src] = in_port

    def mac_to_port(self, datapath, mac):
        """Look up the port associated with a MAC address."""
        if datapath.id in self.mac_to_port and mac in self.mac_to_port[datapath.id]:
            return self.mac_to_port[datapath.id][mac]
        return None

    def send_packet_out(self, datapath, buffer_id, in_port, actions, data=None):
        """Send the packet out of the switch."""
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

    def _send_stats_request(self, datapath):
        """Send a periodic stats request to the controller for flow and link metrics."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        while True:
            # Send Flow Stats Request
            flow_stats_req = parser.OFPStatsRequest(datapath, ofproto.OFPMP_FLOW_STATS)
            datapath.send_msg(flow_stats_req)
            self.logger.info("Sent flow stats request to datapath %s", datapath.id)

            # Send Port Stats Request (for link stats)
            port_stats_req = parser.OFPStatsRequest(datapath, ofproto.OFPMP_PORT_STATS)
            datapath.send_msg(port_stats_req)
            self.logger.info("Sent port stats request to datapath %s", datapath.id)

            # Sleep for the interval before sending the next request
            time.sleep(self.stats_interval)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):
        """Handle flow statistics reply from the switch."""
        datapath = ev.msg.datapath
        body = ev.msg.body

        for stat in body:
            # Assuming flow store stores source, destination, current path, rate, and other metrics
            flow_key = (stat.match['dl_src'], stat.match['dl_dst'])
            flow_info = {
                'src_dst': flow_key,
                'current_path': self.flow_store.get(flow_key, {}).get('current_path', []), # Retrieve the real path from flow store
                'current_rate': stat.byte_count,
                'desired_rate': stat.packet_count,  # Placeholder; you'll need a way to calculate desired rate
                'update_time': time.time(),
                'active': True  # Assuming flow is active if stats exist
            }
            self.flow_store[flow_key] = flow_info
            self.logger.info("Updated flow stats for %s: %s", flow_key, flow_info)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        """Handle port statistics reply from the switch."""
        datapath = ev.msg.datapath
        body = ev.msg.body

        for stat in body:
            # Link store stores throughput, delay, bandwidth, etc., per link
            link_key = (stat.port_no)
            link_info = {
                'current_throughput': stat.rx_bytes,
                'instantaneous_traffic_rate': stat.rx_dropped,  # Replace with traffic rate calculation
                'base_delay': 0,  # Replace with actual base delay
                'current_delay': 0,  # Replace with current delay calculation
                'base_bw': 1000,  # Example base bandwidth
                'current_bw': stat.rx_bytes,  # Example current bandwidth
                'last_updated': time.time()  # Timestamp of last update
            }
            self.link_store[link_key] = link_info
            self.logger.info("Updated link stats for port %s: %s", stat.port_no, link_info)
