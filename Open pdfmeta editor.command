#!/bin/bash
# Double-click this file to open the pdfmeta metadata editor in your browser.
# The first run sets things up automatically; later runs open instantly.

cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install it from https://www.python.org/downloads/ and try again."
  echo "Press Return to close."; read -r; exit 1
fi

if ! python3 -c "import pdfmeta, flask" >/dev/null 2>&1; then
  echo "Setting up the editor (first run only)…"
  python3 -m pip install -e ".[gui]" || {
    echo "Setup failed. Please make sure Python 3 and pip are installed."
    echo "Press Return to close."; read -r; exit 1
  }
fi

echo "Opening the editor in your browser…"
echo "Keep this window open while you work. Close it (or press Ctrl+C) to stop."
python3 -m pdfmeta gui
