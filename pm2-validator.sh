#!/usr/bin/env bash
# Start or restart the validator under PM2 (wraps start-validator.sh).
set -euo pipefail
cd "$(dirname "$0")"

CONFIG="$(pwd)/ecosystem.validator.config.js"
if [[ ! -f "$CONFIG" ]]; then
  echo "Missing $CONFIG" >&2
  exit 1
fi

if ! command -v pm2 &>/dev/null; then
  echo "PM2 not found. Re-run: bash install.sh" >&2
  echo "The installer repairs Node/npm, installs PM2, and reports any PATH fix needed." >&2
  echo "Manual fallback: npm install -g pm2" >&2
  exit 1
fi

if pm2 describe minos-validator &>/dev/null; then
  exec pm2 restart minos-validator --update-env
else
  exec pm2 start "$CONFIG"
fi
