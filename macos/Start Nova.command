#!/bin/bash
# Double-click to start Nova (after macos/setup.sh). Closing Nova's window quits it.
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  echo "Run macos/setup.sh first."
  read -r -p "Press Return to close."
  exit 1
fi
exec .venv/bin/python dashboard.py "$@"
