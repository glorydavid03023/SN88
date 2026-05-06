#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env. Edit it before using Taostats mode."
fi

echo "Testing CSV mode first..."
python -m bot.run_daily --source csv --dry-run
