#!/bin/bash
# Activates the venv and runs main.py. Usage: ./run.sh [extra args passed to main.py]
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate || exit 1

# An explicit setup (or a help request) skips the interactive menu.
SELECT_SETUP=true
for arg in "$@"; do
  case "$arg" in
    --setup|--setup=*|--help|-h) SELECT_SETUP=false ;;
  esac
done

if "$SELECT_SETUP"; then
  # Query the actual setups so names and print dimensions stay in sync.
  SETUP_DATA=$(python - <<'PY'
from vision_setup import DEFAULT_SETUP, VISION_SETUPS

for name, setup in VISION_SETUPS.items():
    width, height = setup.board.get_print_dimensions()
    default = "default" if setup is DEFAULT_SETUP else ""
    print(f"{name}\t{width * 100:g} x {height * 100:g} cm\t{default}")
PY
  ) || exit 1

  SETUP_NAMES=()
  DEFAULT_CHOICE=1
  echo "Select a vision setup (print width x height):"
  while IFS=$'\t' read -r setup_name dimensions default; do
    [ -n "$setup_name" ] || continue
    SETUP_NAMES+=("$setup_name")
    index=${#SETUP_NAMES[@]}
    if [ "$default" = "default" ]; then
      DEFAULT_CHOICE=$index
      printf '  %d) %s - %s (default)\n' "$index" "$setup_name" "$dimensions"
    else
      printf '  %d) %s - %s\n' "$index" "$setup_name" "$dimensions"
    fi
  done <<< "$SETUP_DATA"

  if [ "${#SETUP_NAMES[@]}" -eq 0 ]; then
    echo "No vision setups are available." >&2
    exit 1
  fi
  while true; do
    read -r -p "Setup [$DEFAULT_CHOICE]: " choice || choice=$DEFAULT_CHOICE
    choice=${choice:-$DEFAULT_CHOICE}
    # Compare as strings to avoid interpreting user input as shell arithmetic.
    SELECTED_SETUP=
    for index in "${!SETUP_NAMES[@]}"; do
      if [ "$choice" = "$((index + 1))" ]; then
        SELECTED_SETUP=${SETUP_NAMES[$index]}
        break
      fi
    done
    [ -n "$SELECTED_SETUP" ] && break
    echo "Enter an option number from 1 to ${#SETUP_NAMES[@]}."
  done
  echo "Using vision setup: $SELECTED_SETUP"
  set -- --setup "$SELECTED_SETUP" "$@"
fi

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
