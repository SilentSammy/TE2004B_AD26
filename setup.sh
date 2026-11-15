#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
yes=false
[[ ${1:-} == --yes ]] && yes=true
git submodule update --init --recursive
if "$yes"; then
  bash aruco_gps/setup.sh --yes
else
  bash aruco_gps/setup.sh
fi
