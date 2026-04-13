#!/usr/bin/env python3
"""
Automated Test Scenarios – Link Failure Detection & Recovery
=============================================================
Runs the four required test scenarios automatically, printing results
and prompting you to take screenshots at key moments.

Pre-requisite:  Ryu controller must already be running.
    ryu-manager controller/link_failure_controller.py

Run:
    sudo python3 tests/test_scenarios.py
"""

import os
import sys
import time

# Resolve project root so imports work regardless of cwd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mininet.net  import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.log  import setLogLevel, info, error

from topology.topology import RedundantTopo


# ── helpers ────────────────────────────────────────────────────────────────

def banner(title: str, char: str = '=', width: int = 60):
    info(f"\n{char * width}\n{title}\n{char * width}\n")


def pause_screenshot(description: str):
    """Pause so the tester can capture a screenshot."""
    info(f"\n📸  SCREENSHOT POINT: {description}\n")
    input("    → Press ENTER when done … ")
    info("\n")


def dump_flows(switch_name: str):
    """Print the flow table for the named OVS switch."""
    info(f"\n[Flow table – {switch_name}]\n")
    os.system(f"sudo ovs-ofctl dump-flows {switch_name} 2>/dev/null")


def dump_all_flows():
    for sw in ('s1', 's2', 's3'):
        dump_flows(sw)


# ── test scenarios ─────────────────────────────────────────────────────────

def scenario1_normal_operation(h1, h2):
    """
    Scenario 1 – Normal Operation via Primary Path
    ------------------------------------------------
    Expected: 0 % packet loss, traffic flows s1 ↔ s2 directly.
    """
    banner("SCENARIO 1 – Normal Operation (Primary Path Active)")

    info("[+] Waiting for controller to program flow rules …\n")
    time.sleep(3)

    info("[+] Pinging h2 from h1 (5 packets) …\n")
    result = h1.cmd('ping -c 5 -i 0.5 10.0.0.2')
    info(result)

    dump_all_flows()
    pause_screenshot(
        "Normal operation – flow tables show primary path (s1 port2 → s2, s2 port2 → s1)"
    )

    passed = '0% packet loss' in result
    info(f"[RESULT] Scenario 1: {'PASS ✓' if passed else 'FAIL ✗'}\n")
    return passed


def scenario2_link_failure(net, h1, h2):
    """
    Scenario 2 – Link Failure & Automatic Failover
    ------------------------------------------------
    Take down the primary s1–s2 link and observe:
      - Transient packet loss during detection
      - Automatic reroute via s3
    """
    banner("SCENARIO 2 – Link Failure → Backup Path Activation")

    # Start background continuous ping so we can see the failover
    info("[+] Starting background ping h1 → h2 …\n")
    h1.cmd('rm -f /tmp/ping_output.txt')
    h1.cmd('ping 10.0.0.2 > /tmp/ping_output.txt 2>&1 &')
    time.sleep(2)

    # Bring primary link down
    info("[+] Taking DOWN the primary link  s1 ↔ s2 …\n")
    net.configLinkStatus('s1', 's2', 'down')
    time.sleep(4)   # allow port-status event + controller reaction

    info("[+] Background ping log (observe brief loss then recovery):\n")
    log = h1.cmd('cat /tmp/ping_output.txt')
    info(log)

    dump_all_flows()
    pause_screenshot(
        "After failover – flow tables updated: s1 port3→s3, s3 forwards, s2 port3→h2"
    )

    # Direct ping to confirm backup path works
    info("[+] Direct ping via backup path (5 packets) …\n")
    result2 = h1.cmd('ping -c 5 -i 0.5 10.0.0.2')
    info(result2)

    pause_screenshot(
        "Ping output after failover – should show 0% packet loss on backup path"
    )

    # Stop background ping
    h1.cmd('kill %ping 2>/dev/null')
    h1.cmd('rm -f /tmp/ping_output.txt')

    passed = '0% packet loss' in result2
    info(f"[RESULT] Scenario 2: {'PASS ✓' if passed else 'FAIL ✗'}\n")
    return passed


def scenario3_link_recovery(net, h1, h2):
    """
    Scenario 3 – Primary Link Restored, Traffic Reverts
    -----------------------------------------------------
    Bring the s1–s2 link back and verify the controller reinstalls
    the primary-path rules.
    """
    banner("SCENARIO 3 – Link Recovery → Primary Path Restored")

    info("[+] Restoring primary link  s1 ↔ s2 …\n")
    net.configLinkStatus('s1', 's2', 'up')
    time.sleep(4)

    info("[+] Pinging h2 from h1 (5 packets) after recovery …\n")
    result = h1.cmd('ping -c 5 -i 0.5 10.0.0.2')
    info(result)

    dump_all_flows()
    pause_screenshot(
        "After recovery – flow tables back to primary: s1 port2→s2, s2 port2→s1"
    )

    passed = '0% packet loss' in result
    info(f"[RESULT] Scenario 3: {'PASS ✓' if passed else 'FAIL ✗'}\n")
    return passed


def scenario4_throughput(h1, h2):
    """
    Scenario 4 – Throughput Measurement with iperf
    -----------------------------------------------
    Measures TCP throughput over the active path.
    Run once on primary and optionally repeat during failure.
    """
    banner("SCENARIO 4 – Throughput Measurement (iperf)")

    info("[+] Starting iperf server on h2 …\n")
    h2.cmd('iperf -s &')
    time.sleep(1)

    info("[+] Running iperf client on h1 (TCP, 10 seconds) …\n")
    result = h1.cmd('iperf -c 10.0.0.2 -t 10')
    info(result)

    pause_screenshot(
        "iperf throughput result – note the bandwidth value"
    )

    h2.cmd('kill %iperf 2>/dev/null')
    info("[RESULT] Scenario 4: iperf completed ✓\n")
    return True


# ── main ───────────────────────────────────────────────────────────────────

def main():
    setLogLevel('info')

    topo = RedundantTopo()
    net  = Mininet(
        topo       = topo,
        controller = RemoteController('c0', ip='127.0.0.1', port=6653),
        switch     = OVSKernelSwitch,
        autoSetMacs= False,
    )

    results = {}

    try:
        net.start()
        info("\n[*] Network started – waiting 3 s for controller handshake …\n")
        time.sleep(3)

        h1 = net.get('h1')
        h2 = net.get('h2')

        results['S1'] = scenario1_normal_operation(h1, h2)
        time.sleep(1)

        results['S2'] = scenario2_link_failure(net, h1, h2)
        time.sleep(1)

        results['S3'] = scenario3_link_recovery(net, h1, h2)
        time.sleep(1)

        results['S4'] = scenario4_throughput(h1, h2)

        # ── summary ────────────────────────────────────────────────────────
        banner("SUMMARY", char='-')
        for k, v in results.items():
            status = 'PASS ✓' if v else 'FAIL ✗'
            info(f"  {k}: {status}\n")

        info("\n[*] Entering interactive CLI (type 'exit' to quit) …\n")
        from mininet.cli import CLI
        CLI(net)

    except KeyboardInterrupt:
        info("\n[!] Interrupted by user\n")
    except Exception as exc:
        error(f"\n[ERROR] {exc}\n")
        raise
    finally:
        net.stop()


if __name__ == '__main__':
    main()
