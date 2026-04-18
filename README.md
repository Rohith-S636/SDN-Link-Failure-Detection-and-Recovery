# SDN Link Failure Detection and Recovery

**Course:** UE24CS252B – Computer Networks  
**Framework:** Mininet + Ryu OpenFlow Controller (OpenFlow 1.3)

---

## Problem Statement

Design and implement an SDN-based solution that **automatically detects link failures and dynamically reroutes traffic** to restore connectivity with minimal disruption.

| Requirement | Implementation |
|---|---|
| Detect link failure | `OFPT_PORT_STATUS` events from OVS |
| Update routing dynamically | Delete stale flows; push new `OFPFlowMod` messages |
| Restore connectivity | Backup path via relay switch s3 |
| Restore primary path | Port-UP event triggers reversion to direct link |

---

## Network Topology

```
h1 (10.0.0.1) ─── s1 ──[PRIMARY  s1:port2 ↔ s2:port2]── s2 ─── h2 (10.0.0.2)
                    │                                      │
                    └─[BACKUP s1:port3]── s3 ──[s2:port3]─┘
```

| Switch | Port 1 | Port 2 | Port 3 |
|--------|--------|--------|--------|
| s1 (DPID 1) | h1 | s2 ← **PRIMARY** | s3 ← backup |
| s2 (DPID 2) | h2 | s1 ← **PRIMARY** | s3 ← backup |
| s3 (DPID 3) | s1 | s2 | – |

### Justification of Topology

This triangle/redundant topology was chosen because it provides the simplest scenario to demonstrate failover. It provides a direct, optimal primary route alongside an alternative backup route, avoiding unnecessary complexity while perfectly showcasing link failure detection and traffic rerouting natively via Ryu controller logic.

---

## Repository Structure

```
sdn-link-failure-recovery/
├── controller/
│   └── link_failure_controller.py   # Ryu SDN controller
├── topology/
│   └── topology.py                  # Mininet topology definition
├── tests/
│   └── test_scenarios.py            # Automated test runner
├── screenshots/                     # Proof-of-execution images (see below)
├── run.sh                           # One-command launcher
└── README.md
```

---

## SDN Controller Logic

The controller (`link_failure_controller.py`) implements:

1. **`switch_features_handler`** – Registers each switch; installs primary-path flow rules as soon as all three switches connect.
2. **`port_status_handler`** – Listens for `OFPT_PORT_STATUS` messages. When port 2 of s1 or s2 goes **down**, it flushes the primary-path flows and installs backup-path flows across s1 → s3 → s2. When port 2 comes **back up**, it flushes backup flows and reinstalls the primary path.
3. **`packet_in_handler`** – Safety net that floods unmatched packets so ARP/discovery still works during transitions.

### Flow Rule Design

| State | Switch | Match | Action |
|-------|--------|-------|--------|
| Primary | s1 | `in_port=1` | `output:2` |
| Primary | s1 | `in_port=2` | `output:1` |
| Primary | s2 | `in_port=1` | `output:2` |
| Primary | s2 | `in_port=2` | `output:1` |
| Backup | s1 | `in_port=1` | `output:3` |
| Backup | s1 | `in_port=3` | `output:1` |
| Backup | s3 | `in_port=1` | `output:2` |
| Backup | s3 | `in_port=2` | `output:1` |
| Backup | s2 | `in_port=3` | `output:1` |
| Backup | s2 | `in_port=1` | `output:3` |

---

## Prerequisites

- Oracle VM / VirtualBox running **Ubuntu 20.04 or 22.04**
- Mininet installed (`sudo apt install mininet -y`)
- Open vSwitch (`sudo apt install openvswitch-switch -y`)
- Python 3.8+
- Ryu SDN framework (`pip install ryu`)
- iperf (`sudo apt install iperf -y`)
- Wireshark (optional, `sudo apt install wireshark -y`)

---

## Setup & Execution Steps

### Step 1 – Install dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install mininet openvswitch-switch iperf wireshark -y
pip install ryu
```

### Step 2 – Clone this repository

```bash
git clone https://github.com/<YOUR-USERNAME>/sdn-link-failure-recovery.git
cd sdn-link-failure-recovery
chmod +x run.sh
```

### Step 3 – Option A: One-command launch (interactive)

```bash
./run.sh
```

### Step 3 – Option B: One-command launch (automated tests)

```bash
./run.sh --test
```

### Step 3 – Option C: Manual two-terminal launch

**Terminal 1 – Ryu controller:**
```bash
ryu-manager controller/link_failure_controller.py --verbose
```

**Terminal 2 – Mininet topology:**
```bash
sudo mn -c   # clean previous state
sudo python3 topology/topology.py
```

---

## Test Scenarios

### Scenario 1 – Normal Operation (Primary Path)

```bash
# Inside Mininet CLI
mininet> pingall
mininet> h1 ping -c 10 h2
mininet> sh ovs-ofctl dump-flows s1
mininet> sh ovs-ofctl dump-flows s2
```

**Expected:** 0 % packet loss; `s1 port2 → s2` and `s2 port2 → s1` rules visible in flow tables.

---

### Scenario 2 – Link Failure (Allowed → Blocked / Rerouted)

```bash
# Start continuous ping
mininet> h1 ping h2 &

# Simulate primary link failure
mininet> link s1 s2 down

# Wait ~4 seconds, observe brief loss then recovery
# Check updated flow tables
mininet> sh ovs-ofctl dump-flows s1
mininet> sh ovs-ofctl dump-flows s2
mininet> sh ovs-ofctl dump-flows s3

# Ping should resume via backup path
mininet> h1 ping -c 10 h2
```

**Expected:** Brief packet loss during detection; then 0 % loss via backup path (s1 → s3 → s2).

---

### Scenario 3 – Link Recovery (Restore Primary)

```bash
mininet> link s1 s2 up
# Wait ~4 seconds
mininet> sh ovs-ofctl dump-flows s1
mininet> sh ovs-ofctl dump-flows s2
mininet> h1 ping -c 10 h2
```

**Expected:** 0 % packet loss; flow tables revert to primary-path rules.

---

### Scenario 4 – Throughput Measurement (iperf)

```bash
# Primary path throughput
mininet> h2 iperf -s &
mininet> h1 iperf -c h2 -t 10

# Backup path throughput (after bringing s1-s2 down)
mininet> link s1 s2 down
mininet> h1 iperf -c h2 -t 10
mininet> link s1 s2 up
```

---

### Wireshark Capture (optional but recommended)

```bash
# In Mininet CLI – capture on primary link interface
mininet> sh tcpdump -i s1-eth2 -w /tmp/primary_link.pcap &

# After failover – capture on backup link
mininet> sh tcpdump -i s1-eth3 -w /tmp/backup_link.pcap &
```

---

## Expected Output

### Controller log during failover

```
[+] Switch s1 connected (DPID=1)
[+] Switch s2 connected (DPID=2)
[+] Switch s3 connected (DPID=3)
============================================================
INSTALLING PRIMARY PATH  →  h1 ↔ s1 ↔ s2 ↔ h2
============================================================
[OK] Primary path installed

[PORT-STATUS] s1 port 2 | reason=MODIFY | link_down=True
[!!!] PRIMARY LINK DOWN  →  s1 port 2
============================================================
LINK FAILURE → SWITCHING TO BACKUP PATH
Route: h1 ↔ s1 ↔ s3 ↔ s2 ↔ h2
============================================================
[OK] Backup path installed – connectivity restored

[PORT-STATUS] s1 port 2 | reason=MODIFY | link_down=False
[***] PRIMARY LINK RESTORED → s1 port 2
============================================================
PRIMARY LINK RESTORED → Reverting to primary path
============================================================
[OK] Primary path installed
```

### Ping output during failover

```
64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=1.23 ms
64 bytes from 10.0.0.2: icmp_seq=2 ttl=64 time=0.98 ms
Request timeout for icmp_seq 3
Request timeout for icmp_seq 4
64 bytes from 10.0.0.2: icmp_seq=5 ttl=64 time=2.34 ms   ← backup path active
64 bytes from 10.0.0.2: icmp_seq=6 ttl=64 time=1.10 ms
```

---

## Performance Observation & Analysis

- **Latency (ping):** When a link failure occurs, the continuous ping experiences a slight momentary spike in latency or a few dropped packets (shown as `Request timeout`). This delay represents the time it takes for the switch to generate the `OFPT_PORT_STATUS` message, for the controller to switch states, and to push the new flow rules. After the transition, ping latency over the backup path typically shows a slight increase due to the extra hop (via s3).
- **Throughput (iperf):** The `iperf` tests demonstrate maximum available throughput on the direct primary link. Peak throughput on the backup route may be marginally lower due to the intermediate switch's forwarding overhead.
- **Flow Table Dynamics:** The controller uses a fast proactive approach, pushing flows fully for the new topology, and flushing stale states, ensuring instant routing recovery while relying only on a fallback `packet_in` handler as a safety net.

---

## Screenshots

> All screenshots are in the [`screenshots/`](./screenshots/) directory.

| # | Filename | Description |
|---|----------|-------------|
| 1 | `01_topology_start.png` | Mininet topology launched, all nodes listed |
| 2 | `02_controller_primary_path.png` | Ryu log showing primary path installed |
| 3 | `03_pingall_primary.png` | `pingall` output – 0 % packet loss on primary |
| 4 | `04_flow_table_primary_s1.png` | `ovs-ofctl dump-flows s1` – primary rules |
| 5 | `05_flow_table_primary_s2.png` | `ovs-ofctl dump-flows s2` – primary rules |
| 6 | `06_link_down_command.png` | `link s1 s2 down` command executed in CLI |
| 7 | `07_controller_failover.png` | Ryu log showing backup path installed |
| 8 | `08_ping_during_failover.png` | Ping output showing brief loss then recovery |
| 9 | `09_flow_table_backup_s1.png` | `ovs-ofctl dump-flows s1` – backup rules (port 3) |
| 10 | `10_flow_table_backup_s2.png` | `ovs-ofctl dump-flows s2` – backup rules (port 3) |
| 11 | `11_flow_table_backup_s3.png` | `ovs-ofctl dump-flows s3` – s3 now forwarding |
| 12 | `12_ping_backup_path.png` | Direct ping – 0 % packet loss via backup |
| 13 | `13_link_up_recovery.png` | `link s1 s2 up` + controller log reverting to primary |
| 14 | `14_ping_after_recovery.png` | Ping after recovery – 0 % packet loss |
| 15 | `15_iperf_primary.png` | iperf throughput on primary path |
| 16 | `16_iperf_backup.png` | iperf throughput on backup path (comparison) |
| 17 | `17_wireshark_failover.png` | Wireshark showing traffic shift from s1-eth2 → s1-eth3 |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ryu-manager: command not found` | `pip install ryu` or `pip3 install ryu` |
| `mn: command not found` | `sudo apt install mininet -y` |
| Controller not receiving events | Ensure OVS uses OpenFlow 1.3: `sudo ovs-vsctl set bridge s1 protocols=OpenFlow13` |
| Port 6653 already in use | `sudo fuser -k 6653/tcp` |
| Flows not appearing | Run `sudo mn -c` to reset, then restart both terminals |
| Backup path not activating | Check Ryu logs; confirm `OFPPS_LINK_DOWN` in port-status event |
| `ImportError: No module named ryu` | Use same Python as Mininet: `sudo pip3 install ryu` |

---
