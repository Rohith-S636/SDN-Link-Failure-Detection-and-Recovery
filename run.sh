#!/usr/bin/env bash
# ============================================================
# run.sh – Start Ryu controller then Mininet topology
# ============================================================
# Usage:
#   chmod +x run.sh
#   ./run.sh            # interactive Mininet CLI
#   ./run.sh --test     # automated test scenarios

set -euo pipefail

CONTROLLER="controller/link_failure_controller.py"
TOPOLOGY="topology/topology.py"
TEST_SCRIPT="tests/test_scenarios.py"

# ── check dependencies ───────────────────────────────────────
command -v ryu-manager  >/dev/null 2>&1 || { echo "[ERROR] ryu-manager not found. Install: pip install ryu"; exit 1; }
command -v mn           >/dev/null 2>&1 || { echo "[ERROR] Mininet not found. Install: sudo apt install mininet -y"; exit 1; }

# ── clean up any stale Mininet state ─────────────────────────
echo "[*] Cleaning up old Mininet state …"
sudo mn -c 2>/dev/null || true

# ── start Ryu controller in background ───────────────────────
echo "[*] Starting Ryu controller …"
ryu-manager "$CONTROLLER" --verbose 2>&1 | tee /tmp/ryu_controller.log &
RYU_PID=$!
echo "[*] Ryu PID = $RYU_PID (logs → /tmp/ryu_controller.log)"

# Give Ryu time to bind port 6653
sleep 3

if ! kill -0 "$RYU_PID" 2>/dev/null; then
    echo "[ERROR] Ryu controller failed to start. Check /tmp/ryu_controller.log"
    exit 1
fi

echo "[*] Ryu is running on port 6653"

# ── launch Mininet ────────────────────────────────────────────
if [[ "${1:-}" == "--test" ]]; then
    echo "[*] Running automated test scenarios …"
    sudo python3 "$TEST_SCRIPT"
else
    echo "[*] Starting Mininet topology (interactive CLI) …"
    sudo python3 "$TOPOLOGY"
fi

# ── teardown ─────────────────────────────────────────────────
echo "[*] Stopping Ryu controller (PID $RYU_PID) …"
kill "$RYU_PID" 2>/dev/null || true

echo "[*] Final Mininet cleanup …"
sudo mn -c 2>/dev/null || true

echo "[*] Done."
