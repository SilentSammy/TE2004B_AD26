#!/bin/bash
# Activates the venv and runs main.py. Usage: ./run.sh [extra args passed to main.py]
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate

# Auto-detect the broadcast address from the first non-loopback interface
# that has one, so this doesn't hardcode a subnet that can change.
BROADCAST=$(ip -4 -o addr show | awk '$2 != "lo" && /brd/ { for (i = 1; i <= NF; i++) if ($i == "brd") print $(i + 1) }' | head -n1)

if [ -z "$BROADCAST" ]; then
  echo "Could not auto-detect a broadcast address; pass one manually, e.g. ./run.sh --broadcast 192.168.1.255" >&2
  python main.py "$@"
else
  echo "Using broadcast address: $BROADCAST"
  python main.py --broadcast "$BROADCAST" "$@"
fi
