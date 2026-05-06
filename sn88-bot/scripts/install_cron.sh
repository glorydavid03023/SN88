#!/usr/bin/env bash
set -euo pipefail

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$BOT_DIR/.venv/bin/python"
LOG_DIR="$BOT_DIR/logs"
mkdir -p "$LOG_DIR"

if [ ! -x "$PYTHON" ]; then
  echo "Missing venv python: $PYTHON"
  echo "Run: cd $BOT_DIR && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

CRON_LINE="50 23 * * * cd $BOT_DIR && $PYTHON -m bot.run_daily >> $LOG_DIR/cron.log 2>&1"

# Avoid duplicate line.
( crontab -l 2>/dev/null | grep -vF "$PYTHON -m bot.run_daily" || true; echo "CRON_TZ=UTC"; echo "$CRON_LINE" ) | crontab -

echo "Installed cron:"
echo "CRON_TZ=UTC"
echo "$CRON_LINE"
echo "This runs every day at 23:50 UTC."
