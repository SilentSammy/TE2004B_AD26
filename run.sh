#!/bin/bash
# Activates the venv and runs main.py. Usage: ./run.sh [extra args passed to main.py]
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate
python main.py --broadcast 10.42.0.255 "$@"
