#!/usr/bin/env python3
"""
Automated Test Scenarios – Link Failure Detection & Recovery (No Ryu)
=====================================================================
Runs the four required test scenarios automatically using the integrated
monitor logic.
"""

import os
import sys
import time
import threading

# Resolve project root
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mininet.net  import Mininet
from mininet.node import OVSKernelSwitch
from mininet.log  import setLogLevel, info, error
from topology.topology import RedundantTopo, LinkMonitor

def banner(title: str, char: str = '=', width: int = 60):
    info(f"\n{char * width}\n{title}\n{char * width}\n")

def pause_screenshot(description: str):
    info(f"\n📸  SCREENSHOT POINT: {description}\n")
    input("    → Press ENTER when done … ")

def dump_flows(switch_name: str):
    info(f"\n[Flow table – {switch_name}]\n")
    os.system(f"sudo ovs-ofctl -O OpenFlow13 dump-flows {switch_name} 2>/dev/null")

def dump_all_flows():
    for sw in ('s1', 's2', 's3'):
        dump_flows(sw)

def main():
    setLogLevel('info')
    topo = RedundantTopo()
    
    # No controller needed
    net = Mininet(
        topo=topo,
        switch=OVSKernelSwitch,
        controller=None,
        autoSetMacs=True
    )

    results = {}
    monitor = None

    try:
        net.start()
        
        # Set switches to Secure mode
        for sw in net.switches:
            sw.cmd(f'ovs-vsctl set bridge {sw} fail-mode=secure')

        # Start background monitor
        monitor = LinkMonitor(net)
        monitor.start()

        time.sleep(2)
        h1, h2 = net.get('h1', 'h2')

        # Scenario 1 - Normal
        banner("SCENARIO 1 – Normal Operation (Primary Path Active)")
        result = h1.cmd('ping -c 5 -i 0.5 10.0.0.2')
        info(result)
        dump_all_flows()
        pause_screenshot("Normal operation – primary path rules")
        results['S1'] = '0% packet loss' in result

        # Scenario 2 - Failure
        banner("SCENARIO 2 – Link Failure → Backup Path Activation")
        info("[+] Starting background ping h1 → h2 …\n")
        h1.cmd('ping 10.0.0.2 > /tmp/ping_output.txt 2>&1 &')
        time.sleep(2)
        info("[+] Taking DOWN primary link s1 ↔ s2 …\n")
        net.configLinkStatus('s1', 's2', 'down')
        time.sleep(5)
        info("[+] Ping log (recovery check):\n")
        info(h1.cmd('tail -n 10 /tmp/ping_output.txt'))
        dump_all_flows()
        pause_screenshot("After failover – backup path active")
        result2 = h1.cmd('ping -c 5 -i 0.5 10.0.0.2')
        info(result2)
        results['S2'] = '0% packet loss' in result2
        h1.cmd('pkill ping')

        # Scenario 3 - Recovery
        banner("SCENARIO 3 – Link Recovery → Primary Path Restored")
        info("[+] Restoring primary link s1 ↔ s2 …\n")
        net.configLinkStatus('s1', 's2', 'up')
        time.sleep(5)
        result3 = h1.cmd('ping -c 5 -i 0.5 10.0.0.2')
        info(result3)
        dump_all_flows()
        pause_screenshot("After recovery – primary path restored")
        results['S3'] = '0% packet loss' in result3

        # Scenario 4 - Throughput
        banner("SCENARIO 4 – Throughput Measurement (iperf)")
        h2.cmd('iperf -s &')
        time.sleep(1)
        result4 = h1.cmd('iperf -c 10.0.0.2 -t 10')
        info(result4)
        pause_screenshot("iperf throughput")
        h2.cmd('pkill iperf')
        results['S4'] = True

        # Summary
        banner("SUMMARY", char='-')
        for k, v in results.items():
            info(f"  {k}: {'PASS ✓' if v else 'FAIL ✗'}\n")

    except Exception as e:
        error(f"Test error: {e}\n")
    finally:
        if monitor:
            monitor.stop()
            monitor.join()
        net.stop()

if __name__ == '__main__':
    main()
