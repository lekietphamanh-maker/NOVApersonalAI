#!/bin/bash
# Nova on a Mac, run from this folder: puts Nova's Python packages in .venv (nothing outside this folder), then
# tells you what's left. Run it again after updating Nova.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="$(command -v python3.14 || true)"
if [ -z "$PYTHON" ]; then
  echo "Nova needs Python 3.14: install it from python.org/downloads (the macOS installer), then run this again."
  exit 1
fi
"$PYTHON" -c "import tkinter" 2>/dev/null || { echo "This Python has no Tk: use the python.org installer (Homebrew: brew install python-tk@3.14)."; exit 1; }

"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
chmod +x "macos/Start Nova.command"

echo
echo "Nova is set up."
command -v ollama >/dev/null || echo "• Install Ollama from ollama.com/download (drag it to Applications, open it once)."
[ -d "/Applications/Google Chrome.app" ] || [ -d "/Applications/Microsoft Edge.app" ] || [ -d "/Applications/Brave Browser.app" ] \
  || echo "• Optional: Google Chrome gives Nova its own window (otherwise it opens in your browser)."
echo "• Start Nova: double-click macos/Start Nova.command."
echo "• The first time, allow Input Monitoring (hold Control+Option to talk) and the microphone when macOS asks."
