#!/usr/bin/env bash
# Daily job-hunt run. Safe for cron / Windows Task Scheduler: loads Node (nvm) itself and logs to brain/data/logs.
cd "$(dirname "$0")/.." || exit 1
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" >/dev/null 2>&1 && nvm use 22 >/dev/null 2>&1
mkdir -p brain/data/logs
echo "=== $(date '+%Y-%m-%d %H:%M:%S') run_daily.sh ===" >> brain/data/logs/cron.log
./venv/bin/python hire.py daily >> brain/data/logs/cron.log 2>&1
code=$?
echo "=== exit $code ===" >> brain/data/logs/cron.log
exit $code
