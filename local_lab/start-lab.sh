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

BACKEND_PORT="${LAB_BACKEND_PORT:-8765}"
FRONTEND_PORT="${LAB_FRONTEND_PORT:-5173}"

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

echo -e "${CYAN}Starting backend on http://127.0.0.1:${BACKEND_PORT}${NC}"
PYTHONPATH="${PROJECT_DIR}" "${PYTHON}" -m uvicorn local_lab.backend.main:app \
  --host 127.0.0.1 \
  --port "${BACKEND_PORT}" \
  --reload &
BACKEND_PID=$!

sleep 1

echo -e "${CYAN}Starting frontend on http://127.0.0.1:${FRONTEND_PORT}${NC}"
(
  cd local_lab/frontend
  npm run dev -- --host 127.0.0.1 --port "${FRONTEND_PORT}"
) &
FRONTEND_PID=$!

echo ""
echo -e "${GREEN}${BOLD}Local Lab is running${NC}"
echo -e "  Dashboard: ${CYAN}http://127.0.0.1:${FRONTEND_PORT}${NC}"
echo -e "  API:       ${CYAN}http://127.0.0.1:${BACKEND_PORT}/api/meta${NC}"
echo -e "  Press Ctrl+C to stop"
echo ""

wait
