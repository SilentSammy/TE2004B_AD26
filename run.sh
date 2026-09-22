#!/bin/bash
# Activates the venv and runs main.py. Usage: ./run.sh [extra args passed to main.py]
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate

# Prefer an interface actively running as a Wi-Fi access point (e.g. a
# hotspot hosted on this machine), since that's the network devices like
# the Pico W actually join. NetworkManager creates a separate virtual
# interface (commonly ap0) for this when the radio is also a client
# elsewhere, so the "first interface with an IP" heuristic can pick the
# wrong one on a machine connected to two networks at once.
AP_IFACE=$(iw dev 2>/dev/null | awk '/Interface/{iface=$2} /type AP/{print iface; exit}')
if [ -n "$AP_IFACE" ]; then
  BROADCAST=$(ip -4 -o addr show dev "$AP_IFACE" | awk '/brd/ { for (i = 1; i <= NF; i++) if ($i == "brd") print $(i + 1) }')
fi

# Fall back to the first non-loopback interface with a broadcast address,
# for machines that are only a client (not hosting a hotspot themselves).
if [ -z "$BROADCAST" ]; then
  BROADCAST=$(ip -4 -o addr show | awk '$2 != "lo" && /brd/ { for (i = 1; i <= NF; i++) if ($i == "brd") print $(i + 1) }' | head -n1)
fi

if [ -z "$BROADCAST" ]; then
  echo "Could not auto-detect a broadcast address; pass one manually, e.g. ./run.sh --broadcast 192.168.1.255" >&2
  python main.py "$@"
else
  echo "Using broadcast address: $BROADCAST"
  python main.py --broadcast "$BROADCAST" "$@"
fi
