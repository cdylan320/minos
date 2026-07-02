#!/usr/bin/env bash
# Start or restart the miner under PM2 (wraps start-miner.sh).
#
# Usage:
#   bash pm2-miner.sh          # live mode (uses .env wallet)
#   bash pm2-miner.sh --demo   # demo sandbox (no wallet, ephemeral keypair)
#
# --demo here just exports MINER_DEMO=true before PM2 takes over; the
# Python miner reads the env var at startup. To make demo mode persist
# across restarts add MINER_DEMO=true to your .env instead.
set -euo pipefail
cd "$(dirname "$0")"

DEMO=false

usage() {
  cat <<'EOF'
Usage: bash pm2-miner.sh [OPTIONS]

Options:
  --demo       Run the miner under PM2 in demo mode.
  --help, -h   Show this help.

Examples:
  bash pm2-miner.sh
  bash pm2-miner.sh --demo
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --demo)
      DEMO=true
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

CONFIG="$(pwd)/ecosystem.miner.config.js"
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

if [[ "$DEMO" == "true" ]]; then
  echo "Launching minos-miner under PM2 in DEMO mode (MINER_DEMO=true)"
  export MINER_DEMO=true
fi

if pm2 describe minos-miner &>/dev/null; then
  exec pm2 restart minos-miner --update-env
else
  exec pm2 start "$CONFIG"
fi
