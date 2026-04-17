#!/usr/bin/env bash
# ============================================================
# run.sh – Simplified SDN Project Launcher (No Ryu)
# ============================================================
# Usage:
#   chmod +x run.sh
#   ./run.sh            # interactive Mininet CLI
#   ./run.sh --test     # automated test scenarios (if updated)

set -euo pipefail

TOPOLOGY="topology/topology.py"
TEST_SCRIPT="tests/test_scenarios.py"

# ── check dependencies ───────────────────────────────────────
command -v mn >/dev/null 2>&1 || { echo "[ERROR] Mininet not found. Install: sudo apt install mininet -y"; exit 1; }
command -v ovs-ofctl >/dev/null 2>&1 || { echo "[ERROR] ovs-ofctl not found."; exit 1; }

# ── clean up any stale Mininet state ─────────────────────────
echo "[*] Cleaning up old Mininet state …"
sudo mn -c 2>/dev/null || true

# ── launch Mininet ────────────────────────────────────────────
if [[ "${1:-}" == "--test" ]]; then
    echo "[*] Running automated test scenarios …"
    # Note: test_scenarios.py might need update to avoid controller checks
    sudo python3 "$TEST_SCRIPT"
else
    echo "[*] Starting Mininet topology (Integrated Monitor) …"
    sudo python3 "$TOPOLOGY"
fi

# ── teardown ─────────────────────────────────────────────────
echo "[*] Final Mininet cleanup …"
sudo mn -c 2>/dev/null || true

echo "[*] Done."
