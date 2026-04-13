#!/usr/bin/env python3
"""
Redundant Network Topology for Link Failure Detection & Recovery
================================================================
Topology diagram:

    h1 (10.0.0.1) ─── s1 ──[PRIMARY port2-port2]── s2 ─── h2 (10.0.0.2)
                        │                             │
                        └───[BACKUP  port3-port1]─── s3 ──[BACKUP port2-port3]─┘

Port-number table (set by addLink insertion order):
    Switch │ Port 1       │ Port 2              │ Port 3
    ───────┼──────────────┼─────────────────────┼───────────────────
    s1     │ h1           │ s2  ← PRIMARY link  │ s3 ← backup link
    s2     │ h2           │ s1  ← PRIMARY link  │ s3 ← backup link
    s3     │ s1 (backup)  │ s2  (backup)        │ –

Usage (two terminals):
    Terminal-1:  ryu-manager controller/link_failure_controller.py
    Terminal-2:  sudo python3 topology/topology.py
"""

from mininet.topo   import Topo
from mininet.net    import Mininet
from mininet.node   import RemoteController, OVSKernelSwitch
from mininet.cli    import CLI
from mininet.log    import setLogLevel, info


class RedundantTopo(Topo):
    """Triangle topology with a direct link (primary) and a relay switch (backup)."""

    def build(self):
        # ── hosts ────────────────────────────────────────────────────────────
        h1 = self.addHost('h1',
                          ip  = '10.0.0.1/24',
                          mac = '00:00:00:00:00:01')
        h2 = self.addHost('h2',
                          ip  = '10.0.0.2/24',
                          mac = '00:00:00:00:00:02')

        # ── switches  (explicit DPIDs so controller mapping is deterministic) ─
        s1 = self.addSwitch('s1', dpid='0000000000000001')
        s2 = self.addSwitch('s2', dpid='0000000000000002')
        s3 = self.addSwitch('s3', dpid='0000000000000003')

        # ── links (ORDER matters – it fixes port numbers) ────────────────────
        # s1 port-1 = h1
        self.addLink(h1, s1)
        # s2 port-1 = h2
        self.addLink(h2, s2)
        # s1 port-2 = s2 port-2  (PRIMARY direct link)
        self.addLink(s1, s2)
        # s1 port-3 = s3 port-1  (backup leg 1)
        self.addLink(s1, s3)
        # s3 port-2 = s2 port-3  (backup leg 2)
        self.addLink(s3, s2)


# Expose for `sudo mn --custom topology.py --topo redundant --controller remote`
topos = {'redundant': RedundantTopo}


def run():
    """Launch the network and open the Mininet CLI."""
    setLogLevel('info')

    topo = RedundantTopo()
    net  = Mininet(
        topo       = topo,
        controller = RemoteController('c0', ip='127.0.0.1', port=6653),
        switch     = OVSKernelSwitch,
        autoSetMacs= False,
    )

    net.start()

    # ── sanity: print the actual port assignments ─────────────────────────
    info("\n" + "─" * 55 + "\n")
    info("Topology started.  Port assignments:\n")
    for sw in ('s1', 's2', 's3'):
        node = net.get(sw)
        info(f"  {sw}: {node.intfList()}\n")
    info("─" * 55 + "\n\n")

    # ── useful quick-reference for the demo ──────────────────────────────
    info("Quick-reference commands inside Mininet CLI:\n")
    info("  pingall                          – test all-pairs connectivity\n")
    info("  h1 ping h2                       – continuous ping\n")
    info("  link s1 s2 down                  – simulate primary link failure\n")
    info("  link s1 s2 up                    – restore primary link\n")
    info("  sh ovs-ofctl dump-flows s1       – show s1 flow table\n")
    info("  sh ovs-ofctl dump-flows s2       – show s2 flow table\n")
    info("  sh ovs-ofctl dump-flows s3       – show s3 flow table\n")
    info("  h2 iperf -s &; h1 iperf -c h2   – throughput test\n\n")

    CLI(net)
    net.stop()


if __name__ == '__main__':
    run()
