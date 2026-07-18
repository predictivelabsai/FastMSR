#!/usr/bin/env bash
# Build the animated demo GIF for the README.
#
# This is a thin wrapper around scripts/demo_walkthrough.py, which boots a
# Playwright browser, logs in, clicks through the key module screens, captures
# a frame per screen and stitches them into an animated GIF.
#
#   # against a local dev server (start `python web_app.py` first)
#   DEMO_BASE_URL=http://localhost:5008 bash scripts/build_demo_gif.sh
#
# Output: static/fastmsr-walkthrough.gif  (embedded at the top of the README)
#
# Requires: pip install playwright pillow && python -m playwright install chromium
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python}"
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; fi

exec "$PY" scripts/demo_walkthrough.py
