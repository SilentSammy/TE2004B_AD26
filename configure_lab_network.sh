#!/usr/bin/env bash
# Verify/restore the lab hotspot while leaving internet selection to the GUI.
# Prefer the RTL8822BU TP-Link for AP duty and keep the built-in radio as uplink.
set -euo pipefail

JSON_OUTPUT=false
PAUSE=true
for arg in "$@"; do
  case "$arg" in
    --json) JSON_OUTPUT=true; PAUSE=false ;;
    --no-pause) PAUSE=false ;;
    --help|-h)
      printf 'Usage: bash configure_lab_network.sh [--json | --no-pause]\n'
      printf 'One check/repair pass; manual terminal runs pause before exiting.\n'
      printf -- '--json: result on stdout, progress on stderr, no pause; exit 0 on success.\n'
      exit 0 ;;
    *) printf 'Unknown option: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

# Reserve stdout for the caller's result. Commands and progress go to stderr.
exec 3>&1
exec 1>&2
ERROR_MESSAGE=
AP_IFACE= AP_ADDRESS= BROADCAST= HOTSPOT_SSID= INTERNET_IFACE=

finish() {
  local status=$?
  trap - EXIT
  if [ "$status" -ne 0 ] && [ -z "$ERROR_MESSAGE" ]; then
    ERROR_MESSAGE="Network check failed (exit status $status)."
    printf '%s\n' "$ERROR_MESSAGE" >&2
  fi
  if "$JSON_OUTPUT"; then
    python3 - "$status" "$ERROR_MESSAGE" "$AP_IFACE" "$AP_ADDRESS" \
      "$BROADCAST" "$HOTSPOT_SSID" "$INTERNET_IFACE" >&3 <<'PY'
import json
import sys

status, error, interface, address, broadcast, ssid, internet_interface = sys.argv[1:]
print(json.dumps({
    "success": status == "0",
    "error": error or None,
    "hotspot_interface": interface or None,
    "hotspot_ip": address.split("/")[0] or None,
    "hotspot_cidr": address or None,
    "broadcast": broadcast or None,
    "hotspot_ssid": ssid or None,
    "internet_interface": internet_interface or None,
}))
PY
  fi
  if "$PAUSE" && [ -t 0 ] && [ -t 2 ]; then
    read -r -p "Press Enter to close..." _ || true
  fi
  exit "$status"
}
trap finish EXIT

AP_CONFIG=/etc/create_ap.conf
AP_SERVICE=create_ap.service

fail() {
  ERROR_MESSAGE=$*
  printf 'Network setup failed: %s\n' "$ERROR_MESSAGE" >&2
  exit 1
}
as_root() {
  if [ "$EUID" -eq 0 ]; then
    "$@"
  else
    if [ -t 0 ]; then
      sudo -- "$@"
    else
      sudo -n -- "$@"
    fi
  fi
}

for command in python3 systemctl ip iw awk grep sed sleep timeout readlink basename; do
  command -v "$command" >/dev/null || fail "Required command is missing: $command"
done
[ "$EUID" -eq 0 ] || command -v sudo >/dev/null || fail "sudo is required for repairs."
[ -r "$AP_CONFIG" ] || fail "Cannot read $AP_CONFIG; this script requires the lab's existing create_ap configuration."

# Read values as data rather than executing the root-owned configuration.
config_value() {
  awk -v key="$1" 'index($0, key "=") == 1 {
    value = substr($0, length(key) + 2)
    sub(/\r$/, "", value)
    if (value ~ /^".*"$/ || value ~ /^\047.*\047$/) value = substr(value, 2, length(value) - 2)
    print value
    exit
  }' "$AP_CONFIG"
}

TP_LINK_IFACE=wlxec750cbd6bcd
RALINK_IFACE=wlxd85d4c8af3fa
BUILTIN_IFACE=wlp1s0
INTERNET_IFACE=$BUILTIN_IFACE

interface_exists() {
  ip link show dev "$1" >/dev/null 2>&1
}

supports_ap() {
  local phy
  phy=$(iw dev "$1" info 2>/dev/null | awk '$1 == "wiphy" {print "phy" $2; exit}')
  [ -n "$phy" ] && iw phy "$phy" info 2>/dev/null | grep -qE '^[[:space:]]+\* AP$'
}

# Do not connect or disconnect the internet radio here. Users retain control of
# that connection in the desktop GUI; we only reserve it as the NAT uplink.
interface_exists "$INTERNET_IFACE" ||
  fail "Built-in internet adapter $INTERNET_IFACE is missing."

if interface_exists "$TP_LINK_IFACE" && supports_ap "$TP_LINK_IFACE"; then
  WIFI_IFACE=$TP_LINK_IFACE
  WIFI_DRIVER=$(basename "$(readlink -f "/sys/class/net/$WIFI_IFACE/device/driver" 2>/dev/null || true)")
  [ "$WIFI_DRIVER" = "rtl88x2bu" ] ||
    fail "TP-Link is present but uses '$WIFI_DRIVER', not the required rtl88x2bu driver."
  NO_VIRT=1
  IEEE80211N=1
elif interface_exists "$RALINK_IFACE" && supports_ap "$RALINK_IFACE"; then
  echo "TP-Link unavailable; falling back to the older Ralink hotspot adapter."
  WIFI_IFACE=$RALINK_IFACE
  NO_VIRT=1
  IEEE80211N=0
elif interface_exists "$BUILTIN_IFACE" && supports_ap "$BUILTIN_IFACE" &&
     ! iw dev "$BUILTIN_IFACE" link 2>/dev/null | grep -q '^Connected to '; then
  echo "External hotspot adapters unavailable; falling back to the idle built-in adapter."
  WIFI_IFACE=$BUILTIN_IFACE
  NO_VIRT=0
  IEEE80211N=1
else
  fail "No usable external hotspot adapter was found; refusing to disconnect the built-in internet link."
fi

set_config_value() {
  local key=$1 value=$2
  if [ "$(config_value "$key")" != "$value" ]; then
    as_root sed -i "s|^${key}=.*|${key}=${value}|" "$AP_CONFIG"
    CONFIG_CHANGED=true
  fi
}

CONFIG_CHANGED=false
set_config_value WIFI_IFACE "$WIFI_IFACE"
set_config_value INTERNET_IFACE "$INTERNET_IFACE"
set_config_value NO_VIRT "$NO_VIRT"
set_config_value IEEE80211N "$IEEE80211N"

HOTSPOT_SSID=$(config_value SSID)
GATEWAY=$(config_value GATEWAY)
[ -n "$HOTSPOT_SSID" ] && [ -n "$GATEWAY" ] ||
  fail "Missing SSID or GATEWAY in $AP_CONFIG."

# Discover the actual AP on the configured radio, including virtual interfaces
# such as ap0. Do not mistake another adapter's hotspot for this one.
find_ap() {
  local phy iface
  phy=$(iw dev "$WIFI_IFACE" info 2>/dev/null | awk '$1 == "wiphy" {print "phy#" $2}')
  [ -n "$phy" ] || return 1
  while read -r iface; do
    if [ "$(iw dev "$iface" info 2>/dev/null | awk '$1 == "ssid" {sub(/^[[:space:]]*ssid /, ""); print; exit}')" = "$HOTSPOT_SSID" ]; then
      printf '%s\n' "$iface"
      return 0
    fi
  done < <(iw dev | awk -v phy="$phy" '
    /^phy#/ {on_radio = ($1 == phy)}
    on_radio && $1 == "Interface" {iface = $2}
    on_radio && $1 == "type" && $2 == "AP" {print iface}')
  return 1
}

hotspot_ready() {
  systemctl is-active --quiet "$AP_SERVICE" || return 1
  AP_IFACE=$(find_ap) || return 1
  AP_ADDRESS=$(ip -4 -o address show dev "$AP_IFACE" | awk -v gateway="$GATEWAY" '
    {split($4, parts, "/"); if (parts[1] == gateway) print $4}')
  BROADCAST=$(ip -4 -o address show dev "$AP_IFACE" | awk '
    {for (i = 1; i < NF; i++) if ($i == "brd") {print $(i + 1); exit}}')
  [ -n "$AP_ADDRESS" ] && [ -n "$BROADCAST" ]
}

wait_for_hotspot() {
  local attempt
  for ((attempt = 0; attempt < 20; attempt++)); do
    hotspot_ready && return 0
    sleep 1
  done
  return 1
}

echo "Checking hotspot $HOTSPOT_SSID..."
if ! systemctl is-enabled --quiet "$AP_SERVICE"; then
  as_root timeout 45s systemctl enable "$AP_SERVICE" || fail "Could not enable hotspot startup at boot."
fi
if ! systemctl is-active --quiet "$AP_SERVICE"; then
  as_root timeout 45s systemctl start "$AP_SERVICE" || fail "Could not start $AP_SERVICE."
fi
if "$CONFIG_CHANGED"; then
  echo "Hotspot adapter selection changed; restarting $AP_SERVICE..."
  as_root timeout 45s systemctl restart "$AP_SERVICE" || fail "Could not restart $AP_SERVICE."
fi
if ! hotspot_ready; then
  if ! wait_for_hotspot; then
    echo "Hotspot is unhealthy; restarting $AP_SERVICE..."
    as_root timeout 45s systemctl restart "$AP_SERVICE" || fail "Could not restart $AP_SERVICE."
    wait_for_hotspot || fail "Hotspot did not become ready. Inspect: journalctl -u $AP_SERVICE -b"
  fi
fi

echo "Lab hotspot ready."
printf '  Hotspot: %s on %s (%s)\n' "$HOTSPOT_SSID" "$AP_IFACE" "$AP_ADDRESS"
printf '  Telemetry broadcast: %s\n' "$BROADCAST"
