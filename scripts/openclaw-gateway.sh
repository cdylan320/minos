#!/usr/bin/env bash
# Run the OpenClaw gateway in foreground mode for PM2 or other supervisors.
#
# OpenClaw's managed gateway service uses systemd-user/launchd where available.
# Miner VMs and containers often do not have a systemd user bus, so Minos runs
# the documented foreground gateway command under PM2 instead.
set -euo pipefail

exec openclaw gateway run \
  --bind "${OPENCLAW_GATEWAY_BIND:-loopback}" \
  --port "${OPENCLAW_GATEWAY_PORT:-18789}" \
  --force \
  --allow-unconfigured
