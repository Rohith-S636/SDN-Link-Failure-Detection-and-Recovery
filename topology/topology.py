#!/usr/bin/env python3
"""
Link Failure Detection and Recovery - Integrated Monitor (No Ryu Required)
==========================================================================
Course   : UE24CS252B – Computer Networks
Problem  : Orange Problem #14 – Link Failure Detection and Recovery

This script launches the Mininet topology and runs a background thread that 
monitors the primary link and updates OVS flow tables via ovs-ofctl.
"""

import os
import time
import threading
import subprocess
from mininet.topo   import Topo
from mininet.net    import Mininet
from mininet.node   import OVSKernelSwitch, Controller
from mininet.cli    import CLI
from mininet.log    import setLogLevel, info, error

# ── topology constants ──────────────────────────────────────────────────
# Switch │ Port 1 │ Port 2              │ Port 3
# ───────┼────────┼─────────────────────┼───────────────────
# s1     │ h1     │ s2 (PRIMARY)        │ s3 (backup)
# s2     │ h2     │ s1 (PRIMARY)        │ s3 (backup)
# s3     │ s1     │ s2                  │ -

class RedundantTopo(Topo):
    """Triangle topology with direct link (primary) and relay switch (backup)."""
    def build(self):
        h1 = self.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01')
        h2 = self.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:02')

        s1 = self.addSwitch('s1', dpid='0000000000000001')
        s2 = self.addSwitch('s2', dpid='0000000000000002')
        s3 = self.addSwitch('s3', dpid='0000000000000003')

        # Port 1
        self.addLink(h1, s1)
        self.addLink(h2, s2)
        # Port 2
        self.addLink(s1, s2)
        # Port 3
        self.addLink(s1, s3)
        # Port 2 on s3
        self.addLink(s3, s2)

class LinkMonitor(threading.Thread):
    """Background thread to monitor link status and update flows."""
    def __init__(self, net):
        super(LinkMonitor, self).__init__()
        self.net = net
        self.running = True
        self.primary_active = None # Forces initial installation

    def run(self):
        info("[*] Link Monitor Thread Started\n")
        while self.running:
            try:
                # Check status of s1-eth2 (Primary link interface on s1)
                s1 = self.net.get('s1')
                intf = s1.intf('s1-eth2')
                
                # Check if interface is up (Mininet sets link status here)
                is_up = intf.isUp()
                
                if is_up != self.primary_active:
                    if is_up:
                        self.install_primary()
                    else:
                        self.install_backup()
                    self.primary_active = is_up
                
                time.sleep(1)
            except Exception as e:
                error(f"Error in monitor: {e}\n")
                break

    def ovs_cmd(self, sw, cmd):
        """Execute an ovs-ofctl command."""
        full_cmd = f"ovs-ofctl -O OpenFlow13 {cmd} {sw}"
        subprocess.run(full_cmd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def install_primary(self):
        info("\n" + "="*60 + "\n")
        info("INSTALLING PRIMARY PATH  →  h1 ↔ s1 ↔ s2 ↔ h2\n")
        info("="*60 + "\n")
        
        # Flush all
        for sw in ['s1', 's2', 's3']:
            self.ovs_cmd(sw, "del-flows")

        # s1: h1(1) <-> s2(2)
        self.ovs_cmd('s1', "add-flow priority=10,in_port=1,actions=output:2")
        self.ovs_cmd('s1', "add-flow priority=10,in_port=2,actions=output:1")
        
        # s2: h2(1) <-> s1(2)
        self.ovs_cmd('s2', "add-flow priority=10,in_port=1,actions=output:2")
        self.ovs_cmd('s2', "add-flow priority=10,in_port=2,actions=output:1")
        
        info("[OK] Primary path active\n")

    def install_backup(self):
        info("\n" + "!"*60 + "\n")
        info("LINK FAILURE DETECTED → SWITCHING TO BACKUP PATH\n")
        info("Route: h1 ↔ s1 ↔ s3 ↔ s2 ↔ h2\n")
        info("!"*60 + "\n")

        # Flush s1, s2, s3
        for sw in ['s1', 's2', 's3']:
            self.ovs_cmd(sw, "del-flows")

        # s1: h1(1) <-> s3(3)
        self.ovs_cmd('s1', "add-flow priority=10,in_port=1,actions=output:3")
        self.ovs_cmd('s1', "add-flow priority=10,in_port=3,actions=output:1")
        
        # s3: s1(1) <-> s2(2)
        self.ovs_cmd('s3', "add-flow priority=10,in_port=1,actions=output:2")
        self.ovs_cmd('s3', "add-flow priority=10,in_port=2,actions=output:1")
        
        # s2: h2(1) <-> s3(3)
        self.ovs_cmd('s2', "add-flow priority=10,in_port=1,actions=output:3")
        self.ovs_cmd('s2', "add-flow priority=10,in_port=3,actions=output:1")

        info("[OK] Backup path active\n")

    def stop(self):
        self.running = False

def run():
    setLogLevel('info')
    topo = RedundantTopo()
    
    # We use Controller=None because we manage flows manually via ovs-ofctl
    net = Mininet(
        topo=topo,
        switch=OVSKernelSwitch,
        controller=None,
        autoSetMacs=True
    )
    
    net.start()
    
    # Set switches to Secure mode so they don't act as standalone hubs
    for sw in net.switches:
        sw.cmd(f'ovs-vsctl set bridge {sw} fail-mode=secure')

    # Start the integrated monitoring thread
    monitor = LinkMonitor(net)
    monitor.start()

    info("\n" + "─" * 55 + "\n")
    info("Simplified SDN Project (No Ryu Dependencies)\n")
    info("Monitor is running. Test link failure using:\n")
    info("  mininet> link s1 s2 down\n")
    info("  mininet> link s1 s2 up\n")
    info("─" * 55 + "\n\n")

    CLI(net)
    
    monitor.stop()
    monitor.join()
    net.stop()

if __name__ == '__main__':
    run()
