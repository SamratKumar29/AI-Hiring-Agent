#!/usr/bin/env bash
# One-command start of the web interface: loads Node (nvm) if present, starts Streamlit and opens the browser.
cd "$(dirname "$0")" || exit 1
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" >/dev/null 2>&1 && nvm use 22 >/dev/null 2>&1
exec ./venv/bin/python hire.py ui "$@"
