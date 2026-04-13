#!/usr/bin/env python3
"""
Link Failure Detection and Recovery - Ryu SDN Controller
=========================================================
Course   : UE24CS252B – Computer Networks
Problem  : Orange Problem #14 – Link Failure Detection and Recovery

Topology (hardcoded):
    h1 --- s1 ---[PRIMARY]--- s2 --- h2
            \                 /
             ------ s3 ------

Port assignments (set by topology.py addLink order):
    s1 (DPID 1): port 1 = h1 | port 2 = s2 (PRIMARY) | port 3 = s3 (BACKUP)
    s2 (DPID 2): port 1 = h2 | port 2 = s1 (PRIMARY) | port 3 = s3 (BACKUP)
    s3 (DPID 3): port 1 = s1               | port 2 = s2

Controller logic:
    1. Install primary-path flow rules on s1 & s2 once all switches connect.
    2. Listen for OFPT_PORT_STATUS messages; when the primary link (s1:port2 or
       s2:port2) goes down, delete stale flows and install backup-path rules
       across s1, s3, and s2.
    3. When the primary link comes back, flush all flows and restore primary rules.
"""

import logging
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (CONFIG_DISPATCHER,
                                    MAIN_DISPATCHER,
                                    set_ev_cls)
from ryu.ofproto import ofproto_v1_3

logger = logging.getLogger('LinkFailureCtrl')
logger.setLevel(logging.DEBUG)


class LinkFailureController(app_manager.RyuApp):
    """Ryu application that detects link failures and reroutes traffic."""

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    # ── topology constants ──────────────────────────────────────────────────
    # DPID → {role: port_no}
    PORTS = {
        1: {'host': 1, 'primary': 2, 'backup': 3},   # s1
        2: {'host': 1, 'primary': 2, 'backup': 3},   # s2
        3: {'to_s1': 1, 'to_s2': 2},                  # s3
    }
    PRIMARY_PORT = 2   # the inter-switch port that forms the direct s1-s2 link

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.datapaths      = {}   # dpid → datapath object
        self.primary_active = False
        self.flows_installed = False

    # ── switch handshake ────────────────────────────────────────────────────

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        self.datapaths[dp.id] = dp
        logger.info(f"[+] Switch s{dp.id} connected (DPID={dp.id})")

        # Always install table-miss so unmatched packets reach the controller
        self._install_table_miss(dp)

        # Install primary flows as soon as all three switches are up
        if len(self.datapaths) == 3 and not self.flows_installed:
            self.flows_installed = True
            self._install_primary_path()

    # ── port-status events (link up / down) ─────────────────────────────────

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def port_status_handler(self, ev):
        msg      = ev.msg
        dp       = msg.datapath
        ofproto  = dp.ofproto
        port     = msg.desc

        reason_str = {
            ofproto.OFPPR_ADD:    'ADD',
            ofproto.OFPPR_DELETE: 'DELETE',
            ofproto.OFPPR_MODIFY: 'MODIFY',
        }.get(msg.reason, 'UNKNOWN')

        link_down = bool(port.state & ofproto.OFPPS_LINK_DOWN)

        logger.info(
            f"[PORT-STATUS] s{dp.id} port {port.port_no} | "
            f"reason={reason_str} | link_down={link_down}"
        )

        # We only care about the PRIMARY link ports (port 2 on s1 and s2)
        is_primary_port = (dp.id in (1, 2) and port.port_no == self.PRIMARY_PORT)

        if not is_primary_port:
            return

        if link_down or msg.reason == ofproto.OFPPR_DELETE:
            if self.primary_active:
                logger.warning(
                    f"[!!!] PRIMARY LINK DOWN  →  s{dp.id} port {port.port_no}"
                )
                self._install_backup_path()

        else:   # link is up / restored
            if not self.primary_active:
                logger.info(
                    f"[***] PRIMARY LINK RESTORED → s{dp.id} port {port.port_no}"
                )
                self._restore_primary_path()

    # ── packet-in handler (safety net for unmatched packets) ────────────────

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg      = ev.msg
        dp       = msg.datapath
        ofproto  = dp.ofproto
        parser   = dp.ofproto_parser
        in_port  = msg.match['in_port']

        logger.debug(f"[PKT-IN] s{dp.id} in_port={in_port} (no flow match → flood)")

        actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        data    = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(
            datapath  = dp,
            buffer_id = msg.buffer_id,
            in_port   = in_port,
            actions   = actions,
            data      = data,
        )
        dp.send_msg(out)

    # ── internal helpers ─────────────────────────────────────────────────────

    def _add_flow(self, dp, priority, match, actions,
                  idle_timeout=0, hard_timeout=0):
        """Helper: push a single flow-mod to the switch."""
        ofproto = dp.ofproto
        parser  = dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod  = parser.OFPFlowMod(
            datapath      = dp,
            priority      = priority,
            match         = match,
            instructions  = inst,
            idle_timeout  = idle_timeout,
            hard_timeout  = hard_timeout,
        )
        dp.send_msg(mod)
        logger.debug(
            f"  [FLOW] s{dp.id} priority={priority} "
            f"in_port={match.get('in_port','*')} → "
            f"out_port={actions[0].port}"
        )

    def _delete_all_flows(self, dp):
        """Delete every flow (including table-miss) from a switch."""
        ofproto = dp.ofproto
        parser  = dp.ofproto_parser
        match   = parser.OFPMatch()
        mod     = parser.OFPFlowMod(
            datapath  = dp,
            command   = ofproto.OFPFC_DELETE,
            out_port  = ofproto.OFPP_ANY,
            out_group = ofproto.OFPG_ANY,
            match     = match,
        )
        dp.send_msg(mod)

    def _install_table_miss(self, dp):
        """Install priority-0 catch-all that sends packets to the controller."""
        ofproto = dp.ofproto
        parser  = dp.ofproto_parser
        match   = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self._add_flow(dp, 0, match, actions)

    def _install_primary_path(self):
        """
        Primary path – direct s1 ↔ s2 link (port 2 on both switches).

        s1: port1(h1) ↔ port2(s2)
        s2: port1(h2) ↔ port2(s1)
        """
        logger.info("=" * 60)
        logger.info("INSTALLING PRIMARY PATH  →  h1 ↔ s1 ↔ s2 ↔ h2")
        logger.info("=" * 60)

        dp1 = self.datapaths.get(1)
        dp2 = self.datapaths.get(2)
        if not (dp1 and dp2):
            logger.error("Cannot install primary path: switches not ready")
            return

        p1, p2 = dp1.ofproto_parser, dp2.ofproto_parser

        # s1 rules
        self._add_flow(dp1, 10, p1.OFPMatch(in_port=1), [p1.OFPActionOutput(2)])
        self._add_flow(dp1, 10, p1.OFPMatch(in_port=2), [p1.OFPActionOutput(1)])

        # s2 rules
        self._add_flow(dp2, 10, p2.OFPMatch(in_port=1), [p2.OFPActionOutput(2)])
        self._add_flow(dp2, 10, p2.OFPMatch(in_port=2), [p2.OFPActionOutput(1)])

        self.primary_active = True
        logger.info("[OK] Primary path installed")

    def _install_backup_path(self):
        """
        Backup path – reroute via s3.

        s1: port1(h1) ↔ port3(s3)
        s3: port1(s1) ↔ port2(s2)
        s2: port3(s3) ↔ port1(h2)
        """
        logger.warning("=" * 60)
        logger.warning("LINK FAILURE → SWITCHING TO BACKUP PATH")
        logger.warning("Route: h1 ↔ s1 ↔ s3 ↔ s2 ↔ h2")
        logger.warning("=" * 60)

        dp1 = self.datapaths.get(1)
        dp2 = self.datapaths.get(2)
        dp3 = self.datapaths.get(3)
        if not all([dp1, dp2, dp3]):
            logger.error("Cannot install backup path: switches not ready")
            return

        # Flush stale primary flows on s1 and s2 (keep table-miss)
        for dp in (dp1, dp2):
            self._delete_all_flows(dp)
            self._install_table_miss(dp)

        p1, p2, p3 = (dp1.ofproto_parser,
                      dp2.ofproto_parser,
                      dp3.ofproto_parser)

        # s1 – forward h1 ↔ s3
        self._add_flow(dp1, 10, p1.OFPMatch(in_port=1), [p1.OFPActionOutput(3)])
        self._add_flow(dp1, 10, p1.OFPMatch(in_port=3), [p1.OFPActionOutput(1)])

        # s3 – forward s1 ↔ s2
        self._add_flow(dp3, 10, p3.OFPMatch(in_port=1), [p3.OFPActionOutput(2)])
        self._add_flow(dp3, 10, p3.OFPMatch(in_port=2), [p3.OFPActionOutput(1)])

        # s2 – forward s3 ↔ h2
        self._add_flow(dp2, 10, p2.OFPMatch(in_port=3), [p2.OFPActionOutput(1)])
        self._add_flow(dp2, 10, p2.OFPMatch(in_port=1), [p2.OFPActionOutput(3)])

        self.primary_active = False
        logger.warning("[OK] Backup path installed – connectivity restored")

    def _restore_primary_path(self):
        """
        Called when the primary link comes back up.
        Flush all flow tables (backup rules + table-miss) then reinstall primary.
        """
        logger.info("=" * 60)
        logger.info("PRIMARY LINK RESTORED → Reverting to primary path")
        logger.info("=" * 60)

        for dp in self.datapaths.values():
            self._delete_all_flows(dp)
            self._install_table_miss(dp)

        self._install_primary_path()
