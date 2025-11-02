#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r backend/requirements.txt

export FLASK_APP=backend.app
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-5173}"

python - <<'PY' &
import os
import time
import webbrowser

time.sleep(2)
url = f"http://{os.environ.get('HOST', '127.0.0.1')}:{os.environ.get('PORT', '5173')}"
for browser_name in ("google-chrome", "chromium", "chrome", "chromium-browser"):
    try:
        webbrowser.get(browser_name).open(url, new=2)
        break
    except webbrowser.Error:
        continue
else:
    webbrowser.open(url, new=2)
PY

flask run --host="$HOST" --port="$PORT"
