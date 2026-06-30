#!/usr/bin/env bash
# Minos Local Lab - start backend + frontend dev server
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(dirname "${SCRIPT_DIR}")
cd "${PROJECT_DIR}"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# --- Configuration (edit here) ---
EXTERNAL_PORT=5050       # Dashboard port — open http://<your-server-ip>:5050
BACKEND_PORT=8765        # API port (proxied by the dashboard)
LAB_BIND_HOST="0.0.0.0"  # Listen on all interfaces for external access
# Optional: set your public/LAN IP for startup URLs (auto-detected if empty)
LAB_EXTERNAL_HOST=""
# --------------------------------

FRONTEND_PORT="${EXTERNAL_PORT}"

echo -e "${BOLD}Minos Local Lab${NC}"
echo ""

PYTHON="${PROJECT_DIR}/.venv/bin/python"
PIP="${PROJECT_DIR}/.venv/bin/pip"
if [[ ! -x "${PYTHON}" ]]; then
  echo -e "${RED}Missing .venv - run: bash install.sh${NC}"
  exit 1
fi

echo -e "${CYAN}Installing lab backend deps...${NC}"
"${PIP}" install -q -r local_lab/backend/requirements.txt

if ! command -v npm >/dev/null 2>&1; then
  echo -e "${RED}npm not found - install Node.js 18+ for the UI${NC}"
  exit 1
fi

if [[ ! -d local_lab/frontend/node_modules ]]; then
  echo -e "${CYAN}Installing frontend deps...${NC}"
  (cd local_lab/frontend && npm install)
fi

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "${BACKEND_PID}" 2>/dev/null || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]]; then
    kill "${FRONTEND_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

DISPLAY_HOST="${LAB_EXTERNAL_HOST}"
if [[ -z "${DISPLAY_HOST}" ]]; then
  DISPLAY_HOST=$(hostname -I 2>/dev/null | awk '{print $1}')
fi
if [[ -z "${DISPLAY_HOST}" ]]; then
  DISPLAY_HOST="127.0.0.1"
fi

echo -e "${CYAN}Starting backend on ${LAB_BIND_HOST}:${BACKEND_PORT}${NC}"
PYTHONPATH="${PROJECT_DIR}" "${PYTHON}" -m uvicorn local_lab.backend.main:app \
  --host "${LAB_BIND_HOST}" \
  --port "${BACKEND_PORT}" \
  --reload &
BACKEND_PID=$!

sleep 1

echo -e "${CYAN}Starting frontend on ${LAB_BIND_HOST}:${FRONTEND_PORT}${NC}"
(
  cd local_lab/frontend
  LAB_BIND_HOST="${LAB_BIND_HOST}" \
  LAB_BACKEND_PORT="${BACKEND_PORT}" \
  LAB_FRONTEND_PORT="${FRONTEND_PORT}" \
    npm run dev
) &
FRONTEND_PID=$!

echo ""
echo -e "${GREEN}${BOLD}Local Lab is running${NC}"
echo -e "  Dashboard (local):    ${CYAN}http://127.0.0.1:${FRONTEND_PORT}${NC}"
echo -e "  Dashboard (external): ${CYAN}http://${DISPLAY_HOST}:${FRONTEND_PORT}${NC}"
echo -e "  API (local):          ${CYAN}http://127.0.0.1:${BACKEND_PORT}/api/meta${NC}"
echo -e "  API (external):       ${CYAN}http://${DISPLAY_HOST}:${BACKEND_PORT}/api/meta${NC}"
echo -e "  Press Ctrl+C to stop"
echo ""

wait
