#!/usr/bin/env bash
# Start the shared vision service. Configure the lab network separately.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -f aruco_gps/run.sh ]; then
  echo "The aruco_gps submodule is not initialized. Run bash setup.sh first." >&2
  exit 1
fi
exec bash aruco_gps/run.sh "$@"
