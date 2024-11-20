# asdfdsa



"""
asdf
"""



from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.ofproto import ofproto_v1_0
from ryu.controller import dpset
from ryu.lib import hub


class BandwidthMonitor(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_0.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(BandwidthMonitor, self).__init__(*args, **kwargs)
        self.datapaths = {}
        self.monitor_thread = hub.spawn(self._monitor)
        self.port_stats = {}  # Store port stats for bandwidth calculation

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[datapath.id] = datapath
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                del self.datapaths[datapath.id]

    def _monitor(self):
        while True:
            for dp in self.datapaths.values():
                self._request_stats(dp)
            hub.sleep(1)  # Poll every second

    def _request_stats(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_NONE)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        body = ev.msg.body
        dpid = ev.msg.datapath.id

        self.logger.info("Port stats for switch {0}:".format(dpid))
        for stat in body:
            port_no = stat.port_no
            rx_bytes = stat.rx_bytes
            tx_bytes = stat.tx_bytes

            if (dpid, port_no) not in self.port_stats:
                # Initialize the port stats for first calculation
                self.port_stats[(dpid, port_no)] = (rx_bytes, tx_bytes)
                continue

            prev_rx, prev_tx = self.port_stats[(dpid, port_no)]
            bandwidth_rx = (rx_bytes - prev_rx) * 8  # Convert bytes to bits
            bandwidth_tx = (tx_bytes - prev_tx) * 8

            # Log bandwidth usage in bits per second
            self.logger.info("Port {0}: RX {1} bps, TX {2} bps".format(port_no, bandwidth_rx, bandwidth_tx))

            # Update stats
            self.port_stats[(dpid, port_no)] = (rx_bytes, tx_bytes)

