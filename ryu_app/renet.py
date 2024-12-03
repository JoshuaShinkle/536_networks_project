import json
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_0
from ryu.topology.api import get_switch, get_link
from ryu.topology import event
from ryu.lib.packet import packet, ethernet, tcp, udp
import networkx as nx
import matplotlib.pyplot as plt
from ryu.app.ofctl.api import get_datapath
from ryu.lib import hub
import time
from ryu.lib import mac


DESIRED_RATE = 1000000  # 1 Mbps

REROUTE_LIMIT = 1000000


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
        self.stats_interval = 5
        self.flow_store = {}  # Store flow metrics
        self.link_store = {}  # Store link metrics
        self.flows_per_link = {}  # Store flows per link

    # @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    # def switch_features_handler(self, ev):
    #     datapath = ev.msg.datapath
    #     self.logger.info(f"Switch connected: {datapath.id}")
    #     self.install_default_flows(datapath)
    #     # self.datapaths[datapath.id] = datapath

    def install_default_flows(self, datapath):
        """
        Install default flows for LLDP packet handling.
        """
        # print("Installing default flows")
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
        # print(ev.__dict__)
        datapath = ev.switch.dp
        # keep track of datapath
        # print(ev.switch.dp)
        # self.datapaths[ev.switch.dp.id] = ev.switch.dp
        hub.spawn(self._send_stats_request, datapath)
        self.update_topology()

    # @set_ev_cls(ofp_event.EventOFPSwitchFeatures, MAIN_DISPATCHER)
    # def _switch_features_handler(self, ev):
    #     """Handles the switch feature reply."""
    #     datapath = ev.msg.datapath
    #     self.datapaths[datapath.id] = datapath

    #     # Send a default flow mod to prevent packet flooding by default
    #     ofproto = datapath.ofproto
    #     parser = datapath.ofproto_parser
    #     match = parser.OFPMatch()
    #     actions = []
    #     # self.add_flow(datapath, 0, match, actions)  # Drop all by default
    #     print(f"Switch {datapath.id} connected.")

    #     hub.spawn(self._send_stats_request, datapath)

    @set_ev_cls(event.EventLinkAdd)
    def link_add_handler(self, ev):
        """
        Update topology when a new link is added.
        """
        src = ev.link.src.dpid
        dst = ev.link.dst.dpid
        self.flows_per_link[f'{src}-{dst}'] = 0
        self.flows_per_link[f'{dst}-{src}'] = 0
        with open('/mn_scripts/link_bandwidths.json', 'r') as f:
            current_link_bandwidths = json.load(f)
            link_key = f"{src}-{dst}"
            link_key2 = f"{dst}-{src}"
            new_link_info = {
                'src_dst': link_key,
                'usage': 0,
                'recieved_bytes': 0,
                'desired_rate': 1000000,  # 1 Mbps
                'update_time': time.time(),
                'active': True,  # Assuming link is active if stats exist
            }
            new_link_info['current_bandwidth'] = current_link_bandwidths.get(link_key, 0)
            self.link_store[link_key] = self.link_store[link_key2] = new_link_info
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

        # self.logger.info("\nUpdated network topology:\nNodes: %s\nEdges: %s\n", self.network_graph.nodes(data=True), self.network_graph.edges(data=False))

        # Compute the Minimum Spanning Tree
        self.mst = nx.minimum_spanning_tree(self.network_graph.to_undirected())
        # self.logger.info("\nUpdated MST:\nEdges: %s\n", self.mst.edges(data=False))

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
        # self.logger.info(f"Flooding {state} on port {port_no} of switch {dpid}.")


    def _send_stats_request(self, datapath):
        """Send a periodic stats request to the controller for flow and link metrics."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        while True:
            # Send Flow Stats Request
            # flow_stats_req = parser.OFPStatsRequest(datapath, flags=0)
            empty_match = parser.OFPMatch()
            flow_stats_req = parser.OFPFlowStatsRequest(datapath, flags=0, match=empty_match, table_id=0, out_port=ofproto.OFPP_NONE)
            datapath.send_msg(flow_stats_req)
            # self.logger.info("Sent flow stats request to datapath %s", datapath.id)

            # Send Port Stats Request
            port_stats_req = parser.OFPPortStatsRequest(datapath, flags=0, port_no=ofproto.OFPP_NONE)
            datapath.send_msg(port_stats_req)
            # self.logger.info("Sent port stats request to datapath %s", datapath.id)

            rerun = False

            for flow_key, flow_info in self.flow_store.items():
                if flow_info['active']:
                    flow_info['active_countdown'] -= 1
                    if flow_info['active_countdown'] == 0 and flow_info['active']:
                        flow_info['active'] = False
                        rerun = True

                        # self.logger.info("Flow %s marked as inactive", flow_key)
            
            if rerun:
                # print("Rerouting flows")
                to_rerun = {}
                for flow_key, flow_info in self.flow_store.items():
                    # print('Rerouting info:', flow_info['current_rate'], DESIRED_RATE)
                    # print(f"Flow info: active={flow_info['active']}, current_rate={flow_info['current_rate']}, recent_rerouting_countdown={flow_info['recent_rerouting_countdown']}")
                    if flow_info['active'] and flow_info['recent_rerouting_countdown'] == 0 and flow_info['current_rate'] < 0.75 * DESIRED_RATE:
                        to_rerun[flow_key] = flow_info['current_rate'] / DESIRED_RATE
                
                sorted_rerun = sorted(to_rerun.items(), key=lambda x: x[1])

                for flow_key, _ in sorted_rerun:
                    if flow_key[0] not in self.network_graph or flow_key[1] not in self.network_graph:
                        continue
                    path, throughput = self.path_selection(flow_key[0], flow_key[1])
                    # print('throughput:', throughput, "current rate:", self.flow_store[flow_key]['current_rate'])
                    if throughput > self.flow_store[flow_key]['current_rate'] * 1.25:
                        self.flow_store[flow_key]['recent_rerouting_countdown'] = 2
                        # decrement the flow count for the old path
                        for i in range(len(self.flow_store[flow_key]['path']) - 2):
                            self.flows_per_link[f'{self.flow_store[flow_key]["path"][i]}-{self.flow_store[flow_key]["path"][i + 1]}'] -= 1
                            self.flows_per_link[f'{self.flow_store[flow_key]["path"][i + 1]}-{self.flow_store[flow_key]["path"][i]}'] -= 1
                        
                        # increment the flow count for the new path
                        for i in range(len(path) - 2):
                            self.flows_per_link[f'{path[i]}-{path[i + 1]}'] += 1
                            self.flows_per_link[f'{path[i + 1]}-{path[i]}'] += 1
                        
                        self.flow_store[flow_key]['path'] = path

                        src, dst, src_port, dst_port = flow_key

                        # print(f"Rerouting flow from {src} to {dst}: {path}")

                        self.install_path_flows(path, src, dst, src_port, dst_port)
                        self.install_path_flows(path[::-1], dst, src, src_port, dst_port)




                


            # Sleep for the interval before sending the next request
            time.sleep(self.stats_interval)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):
        """Handle flow statistics reply from the switch."""
        datapath = ev.msg.datapath
        body = ev.msg.body

        for stat in body:
            # Flow store stores source, destination, current path, rate, and other metrics
            # print("Stat match", stat.match)
            # print("addresses:", mac.haddr_to_str(stat.match.dl_src), mac.haddr_to_str(stat.match.dl_dst))
            flow_key = (mac.haddr_to_str(stat.match.dl_src), mac.haddr_to_str(stat.match.dl_dst), stat.match.tp_src, stat.match.tp_dst)
            prev_flow_info = self.flow_store.get(flow_key, {})
            print("flow_key", flow_key)
            if prev_flow_info == {}:
                prev_flow_info['path'] = []
            
            new_flow_info = {
                'src_dst': flow_key,
                # 'current_path': self.flow_store.get(flow_key, {}).get('current_path', []), # Retrieve the real path from flow store
                # 'current_rate': (stat.byte_count - prev_flow_info['recieved_bytes']) / self.stats_interval,
                'current_rate': stat.byte_count / stat.duration_sec if stat.duration_sec > 0 else 0,
                'desired_rate': DESIRED_RATE,  # 1 Mbps
                'update_time': time.time(),
                'active': True,  # Assuming flow is active if stats exist
                'input_port': stat.match.in_port,
                'active_countdown': 2,
                'recent_rerouting_countdown': 0,
                'path': prev_flow_info['path']
            }
            self.flow_store[flow_key] = new_flow_info
            # self.logger.info("Updated flow stats for %s: %s", flow_key, new_flow_info)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        """Handle port statistics reply from the switch."""
        datapath = ev.msg.datapath
        body = ev.msg.body

        for stat in body:
            # Find the connected switch for the given port
            dpid1 = datapath.id
            port_no = stat.port_no
            # print(f'port number {port_no}')
            dpid2 = None
            for neighbor in self.network_graph.neighbors(dpid1):
                edge_data = self.network_graph.get_edge_data(dpid1, neighbor)
                # print (f'edge data {edge_data}')
                if 'src_port' in edge_data and edge_data['src_port'] == port_no:
                    dpid2 = neighbor
                    break
                elif 'dst_port' in edge_data and edge_data['dst_port'] == port_no:
                    dpid2 = neighbor
                    break

            if dpid2 is None:
                # raise ValueError(f"Neighbor switch not found for port {port_no} on switch {dpid1}")
                continue

            # Link store stores source, destination, current rate, and other metrics
            link_key = f"{dpid1}-{dpid2}"
            prev_link_info = self.link_store.get(link_key, {}).copy()
            print("prev_lin_info", prev_link_info)

            if prev_link_info == {}:
                prev_link_info['recieved_bytes'] = 0
                prev_link_info['current_bandwidth'] = 0

            prev_bandwidth = prev_link_info['current_bandwidth']

            new_link_info = {
                'src_dst': link_key,
                'usage': (stat.rx_bytes - prev_link_info['recieved_bytes']) / self.stats_interval,
                'recieved_bytes': stat.rx_bytes,
                'desired_rate': 1000000,  # 1 Mbps
                'update_time': time.time(),
                'active': True,  # Assuming link is active if stats exist
            }

            # print(new_link_info)
            # print(f"Received bytes on port {port_no} of switch {dpid1}: {stat.rx_bytes}")

            with open('/mn_scripts/link_bandwidths.json', 'r') as f:
                current_link_bandwidths = json.load(f)
                link_key = f"{dpid1}-{dpid2}"
                link_key2 = f"{dpid2}-{dpid1}"
                new_link_info['current_bandwidth'] = current_link_bandwidths.get(link_key, 0)
                print("new_link_info", new_link_info)
                print(f"Link bandwidth: {new_link_info['current_bandwidth']}, previous bandwidth: {prev_bandwidth}")
                if new_link_info['current_bandwidth'] < prev_bandwidth:
                    print(f"Entering thingggggg")
                    # iterate though the flow store and get the ones that are using this link
                    for flow_key, flow_info in self.flow_store.items():
                        if self.edge_in_path(flow_info['path'], dpid1, dpid2):
                            print(f"Rerouting flow {flow_key}")
                            path, throughput = self.path_selection(flow_key[0], flow_key[1])
                            print('throughput:', throughput, "current rate:", flow_info['current_rate'])

                            self.flow_store[flow_key]['recent_rerouting_countdown'] = 2
                            # decrement the flow count for the old path
                            for i in range(len(flow_info['path']) - 2):
                                self.flows_per_link[f'{flow_info["path"][i]}-{flow_info["path"][i + 1]}'] -= 1
                                self.flows_per_link[f'{flow_info["path"][i + 1]}-{flow_info["path"][i]}'] -= 1
                            
                            # increment the flow count for the new path
                            for i in range(len(path) - 2):
                                self.flows_per_link[f'{path[i]}-{path[i + 1]}'] += 1
                                self.flows_per_link[f'{path[i + 1]}-{path[i]}'] += 1
                            
                            self.flow_store[flow_key]['path'] = path

                            src, dst, src_port, dst_port = flow_key

                            print(f"Rerouting flow from {src} to {dst}: {path}")

                            self.install_path_flows(path, src, dst, src_port, dst_port)
                            self.install_path_flows(path[::-1], dst, src, src_port, dst_port)
                            # self.logger.info("Rerouted flow %s to path %s", flow_key, path)
                            break

            self.link_store[link_key] = new_link_info
            self.link_store[link_key2] = new_link_info
            # self.logger.info("Updated port stats for %s: %s", link_key, new_link_info)

    def edge_in_path(self, path, n1, n2):
        """
        Check if an edge is in a given path.
        """
        for i in range(len(path) - 1):
            if path[i] == n1 and path[i + 1] == n2:
                return True
            if path[i] == n2 and path[i + 1] == n1:
                return True
        return False

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
            # src_dpid = self.mac_to_switch[src]['dpid']
            # dst_dpid = self.mac_to_switch[dst]['dpid']
            # path = nx.shortest_path(self.network_graph, src, dst)

            # Extract TCP/UDP ports if available
            tcp_pkt = pkt.get_protocol(tcp.tcp)
            udp_pkt = pkt.get_protocol(udp.udp)
            if tcp_pkt:
                src_port = tcp_pkt.src_port
                dst_port = tcp_pkt.dst_port
            elif udp_pkt:
                src_port = udp_pkt.src_port
                dst_port = udp_pkt.dst_port
            else:
                # Flood the packet to discover the destination
                self.logger.info(f"Flooding packet")
                self.flood_packet_mst(datapath, in_port, msg)
                return
            
            path = self.path_selection(src, dst)[0]

            self.logger.info(f"Path computed from {src} to {dst}: {path}")
            self.install_path_flows(path, src, dst, src_port, dst_port)
            self.install_path_flows(path[::-1], dst, src, src_port, dst_port)
            for i in range(len(path) - 2):
                self.flows_per_link[f'{path[i]}-{path[i + 1]}'] += 1
                self.flows_per_link[f'{path[i + 1]}-{path[i]}'] += 1
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
        


    def path_selection(self, src, dst):
        """
        Compute the optimal path between two switches, considering link capacities and flow requirements.
        """
        # Get K shortest paths
        K = 5  # Number of shortest paths to consider
        paths = list(nx.shortest_simple_paths(self.network_graph, source=src, target=dst))
        paths = paths[:K]  # Limit to K shortest paths


        path_list = {}

        for path in paths:
            # remove the first and last element of the path
            path = path[1:-1]
            # Calculate the minimum bandwidth along this path
            path_throughput = float('inf')
            for i in range(len(path) - 1):
                link = self.link_store[f'{path[i]}-{path[i + 1]}']
                link_capacity = link['current_bandwidth']
                link_usage = link['usage']
                available_bandwidth = link_capacity - link_usage
                fair_share = link_capacity / (self.flows_per_link[f'{path[i]}-{path[i + 1]}'] + 1)
                expected_throughput = max(available_bandwidth, fair_share)
                if expected_throughput < path_throughput:
                    path_throughput = expected_throughput
            path_list[tuple(path)] = path_throughput
        
        path_list = sorted(path_list.items(), key=lambda x: x[1])

        path_result = None
        throughput_result = None

        for path, throughput in path_list:
            if throughput > DESIRED_RATE:
                self.logger.info(f"Selected path from {src} to {dst}: {path}")
                path_result = path
                throughput_result = throughput
                break

        if path_result is None:
            path_result, throughput_result = path_list[-1]
            self.logger.info(f"Selected path from {src} to {dst}: {path_result}") 


        
        return list(path_result) + [dst], throughput_result
    


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


    def install_path_flows(self, path, src, dst, tp_src, tp_dst):
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
                self.add_flow(datapath, src, dst, tp_src, tp_dst, out_port)


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


    def add_flow(self, datapath, src, dst, tp_src, tp_dst, out_port):
        """
        Add a flow rule to the given datapath.
        """
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        match = parser.OFPMatch(dl_src=src, dl_dst=dst, tp_src=tp_src, tp_dst=tp_dst)
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
