#!/usr/bin/env bash
# Optional Minos Miner AI Assistant setup.
#
# 1.0.0 scope:
#   1. Set up Ditto CLI auth and subscribe to the public @minos graph.
#   2. Optionally install OpenClaw or Hermes.
#   3. Install the Minos skill/persona files, Ditto skill, and Minos MCP
#      live-data connection into the selected runtime.
#
# This script only installs public Minos onboarding docs plus runtime integration. It
# does not upload Minos .env values, wallet files, miner configs, logs,
# presigned URLs, model API keys, or private validator data.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DITTO_SETUP_SCRIPT="$ROOT_DIR/scripts/setup_ditto_agent.sh"
MINOS_SKILL_SOURCE="$ROOT_DIR/docs/ai-assistant/minos-miner-skill"
OPENCLAW_CONTEXT_SOURCE="$ROOT_DIR/docs/ai-assistant/openclaw-workspace"
OPENCLAW_GATEWAY_SCRIPT="$ROOT_DIR/scripts/openclaw-gateway.sh"
HERMES_SOUL_TEMPLATE="$ROOT_DIR/docs/ai-assistant/hermes/SOUL.minos-miner-template.md"
INCOMPLETE_MARKER="$ROOT_DIR/.minos_ai_assistant_incomplete"
MINOS_MCP_NAME="${MINOS_MCP_NAME:-minos}"
MINOS_MCP_URL="${MINOS_MCP_URL:-https://mcp.theminos.ai}"
MINOS_MCP_TIMEOUT="${MINOS_MCP_TIMEOUT:-120}"
MINOS_MCP_CONNECT_TIMEOUT="${MINOS_MCP_CONNECT_TIMEOUT:-30}"
MINOS_MCP_TOOLS=(
  get_current_round
  get_leaderboard
  list_recent_rounds
  get_miner_history
  get_subnet_overview
)

YES=false
DRY_RUN=false
SETUP_DITTO="ask"
DITTO_SETUP_STATUS="skipped"
RUNTIME="ask"
RUNTIME_EXPLICIT=false
INSTALL_RUNTIME_CONTEXT=true
FORCE_CONTEXT=false
RUN_ONBOARDING=false
RUN_HERMES_SETUP=false
EMBEDDED="${MINOS_AI_ASSISTANT_EMBEDDED:-false}"
DITTO_CLAIM_CREATED_THIS_RUN=false

if [[ -z "${MINOS_DITTO_SEED_FALLBACK:-}" && -f /opt/minosvm_venv/bin/activate ]]; then
  export MINOS_DITTO_SEED_FALLBACK="never"
fi

export HERMES_TUI_BACKGROUND="${HERMES_TUI_BACKGROUND:-#0A0A0A}"

RED=""
GREEN=""
YELLOW=""
CYAN=""
DIM=""
BOLD=""
NC=""
TERM_WIDTH=78
USE_TTY_UI=false

setup_terminal_ui() {
  if command -v tput >/dev/null 2>&1; then
    TERM_WIDTH="$(tput cols 2>/dev/null || echo 78)"
    if [[ -z "$TERM_WIDTH" ]] || (( TERM_WIDTH < 60 )); then
      TERM_WIDTH=78
    elif (( TERM_WIDTH > 88 )); then
      TERM_WIDTH=88
    fi
  fi

  if [[ -z "${NO_COLOR:-}" && -t 1 && "${TERM:-}" != "dumb" ]] && command -v tput >/dev/null 2>&1; then
    local colors
    colors="$(tput colors 2>/dev/null || echo 0)"
    if [[ "$colors" =~ ^[0-9]+$ ]] && (( colors >= 8 )); then
      RED="$(tput setaf 1)"
      GREEN="$(tput setaf 2)"
      YELLOW="$(tput setaf 3)"
      CYAN="$(tput setaf 6)"
      BOLD="$(tput bold)"
      DIM="$(tput dim 2>/dev/null || true)"
      NC="$(tput sgr0)"
      USE_TTY_UI=true
    fi
  fi
}

repeat_char() {
  local char="${1:--}"
  local count="${2:-$TERM_WIDTH}"
  local output=""
  local i

  for ((i = 0; i < count; i++)); do
    output+="$char"
  done
  printf '%s' "$output"
}

rule() {
  printf '%s\n' "${DIM}$(repeat_char "-")${NC}"
}

panel() {
  local title="$1"
  local body="$2"
  local width="${3:-76}"
  local title_text=" $title "
  local inner_width=$((width - 4))
  local line wrapped

  if [[ "$USE_TTY_UI" == "true" ]]; then
    printf '\n%s╭─%s%s%s%s%s╮%s\n' \
      "$CYAN" "$BOLD" "$title_text" "$NC" "$CYAN" \
      "$(repeat_char "─" $((width - 3 - ${#title_text})))" "$NC"
    while IFS= read -r line; do
      if [[ -z "$line" ]]; then
        printf '%s│%s %-*s %s│%s\n' "$CYAN" "$NC" "$inner_width" "" "$CYAN" "$NC"
        continue
      fi
      while IFS= read -r wrapped; do
        printf '%s│%s %-*s %s│%s\n' "$CYAN" "$NC" "$inner_width" "$wrapped" "$CYAN" "$NC"
      done < <(printf '%s\n' "$line" | fold -s -w "$inner_width")
    done <<< "$body"
    printf '%s╰%s╯%s\n' "$CYAN" "$(repeat_char "─" $((width - 2)))" "$NC"
  else
    printf '\n%s\n' "$title"
    printf '%s\n' "$body"
  fi
}

banner() {
  panel "Minos Miner AI Assistant" "Public @minos knowledge graph, Minos MCP live data, and optional OpenClaw/Hermes runtime support."
  printf '  %-14s %s\n' "Ditto" "read-only @minos graph subscription"
  printf '  %-14s %s\n' "Minos MCP" "live/current public subnet data"
  printf '  %-14s %s\n' "Runtime" "optional OpenClaw or Hermes"
  printf '  %-14s %s\n' "Provider" "connect inside the selected runtime"
  printf '\n'
}

section() {
  printf '\n%s◆%s %s%s%s\n' "$CYAN" "$NC" "$BOLD" "$1" "$NC"
}

status_line() {
  local symbol="$1"
  local color="$2"
  shift 2
  printf '  %s%s%s %s\n' "$color" "$symbol" "$NC" "$*"
}

info() { status_line "•" "$CYAN" "$1"; }
ok() { status_line "✓" "$GREEN" "$1"; }
warn() { status_line "⚠" "$YELLOW" "$1"; }
fail() { status_line "✗" "$RED" "$1" >&2; }

command_hint() {
  printf '  %s%s%s\n' "$DIM" "$1" "$NC"
}

ditto_claim_file_path() {
  local config_dir="${DITTO_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/heyditto/cli}"
  printf '%s/minos-claim-url.txt\n' "$config_dir"
}

file_mtime() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    printf '0\n'
    return
  fi

  stat -c %Y "$path" 2>/dev/null || stat -f %m "$path" 2>/dev/null || printf '0\n'
}

read_ditto_claim_url() {
  local claim_file
  claim_file="$(ditto_claim_file_path)"
  [[ -f "$claim_file" ]] || return 1
  sed -n '1p' "$claim_file"
}

mask_secret_value() {
  local value="$1"
  local len="${#value}"
  if (( len <= 20 )); then
    printf '[saved locally]'
  else
    printf '%s...%s' "${value:0:12}" "${value: -8}"
  fi
}

print_log_tail() {
  local log_file="$1"
  if [[ -f "$log_file" ]]; then
    tail -8 "$log_file" | sed 's/^/      /' >&2
  fi
}

run_quiet() {
  local message="$1"
  local log_file="$2"
  shift 2

  : > "$log_file"

  if [[ "$DRY_RUN" == "true" ]]; then
    info "$message"
    command_hint "$*"
    return 0
  fi

  if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    "$@" >"$log_file" 2>&1 &
    local pid=$!
    local frames='|/-\'
    local i=0

    while kill -0 "$pid" 2>/dev/null; do
      printf '\r  %s[%s]%s %s' "$CYAN" "${frames:i++%4:1}" "$NC" "$message"
      sleep 0.12
    done

    if wait "$pid"; then
      printf '\r'
      printf '  %s✓%s %s\n' "$GREEN" "$NC" "$message"
      return 0
    fi

    printf '\r'
    printf '  %s✗%s %s\n' "$RED" "$NC" "$message" >&2
    print_log_tail "$log_file"
    return 1
  fi

  info "$message"
  if "$@" >"$log_file" 2>&1; then
    ok "$message"
    return 0
  fi

  fail "$message"
  print_log_tail "$log_file"
  return 1
}

success_card() {
  local title="$1"
  local body="$2"
  panel "✓ $title" "$body"
}

run_quiet_or_existing() {
  local message="$1"
  local log_file="$2"
  shift 2

  if run_quiet "$message" "$log_file" "$@"; then
    return 0
  fi

  if [[ -f "$log_file" ]] && grep -qiE "already exists|already installed" "$log_file"; then
    ok "$message already exists."
    return 0
  fi

  return 1
}

setup_terminal_ui

usage() {
  cat <<'EOF'
Usage: bash scripts/setup_ai_assistant.sh [OPTIONS]

Options:
  --with-ditto       Subscribe Ditto to the public @minos graph without asking.
  --skip-ditto       Skip Ditto graph setup and only configure the runtime.
  --ditto-only       Subscribe to @minos in Ditto and skip OpenClaw/Hermes setup.
  --openclaw         Configure OpenClaw + Ditto skill + Minos MCP + local Minos files.
  --hermes           Configure Hermes + Ditto skill + Minos MCP + local Minos files.
  --install-runtime  Compatibility flag. Selected runtimes install automatically if missing.
  --skip-runtime-context
                     Do not install Minos local skill/persona files.
  --force-context    Append Minos context blocks even when Minos markers already exist.
  --run-onboarding   After installing OpenClaw, run OpenClaw onboarding.
                     By default Minos skips this to keep onboarding in one flow.
  --run-hermes-setup After installing Hermes, use the Hermes Portal setup path.
                     By default Minos asks which Hermes provider path to use.
  --yes, -y          Skip nonessential confirmations where possible.
  --dry-run          Print what would happen.
  --help, -h         Show this help.

Recommended:
  bash scripts/setup_ai_assistant.sh --with-ditto --openclaw
  bash scripts/setup_ai_assistant.sh --with-ditto --hermes
  bash scripts/setup_ai_assistant.sh --ditto-only
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-ditto) SETUP_DITTO="yes"; shift ;;
    --skip-ditto) SETUP_DITTO="no"; shift ;;
    --ditto-only) SETUP_DITTO="yes"; RUNTIME="none"; RUNTIME_EXPLICIT=true; shift ;;
    --openclaw) RUNTIME="openclaw"; RUNTIME_EXPLICIT=true; shift ;;
    --hermes) RUNTIME="hermes"; RUNTIME_EXPLICIT=true; shift ;;
    --install-runtime) shift ;;
    --skip-runtime-context) INSTALL_RUNTIME_CONTEXT=false; shift ;;
    --force-context) FORCE_CONTEXT=true; shift ;;
    --run-onboarding) RUN_ONBOARDING=true; shift ;;
    --run-hermes-setup) RUN_HERMES_SETUP=true; shift ;;
    --yes|-y) YES=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) fail "Unknown option: $1"; usage; exit 1 ;;
  esac
done

ask_yes_no() {
  local prompt="$1"
  local default="${2:-n}"
  local answer

  if [[ "$YES" == "true" ]]; then
    [[ "$default" == "y" ]]
    return
  fi

  if [[ ! -t 0 || ! -t 1 ]]; then
    [[ "$default" == "y" ]]
    return
  fi

  if [[ "$default" == "y" ]]; then
    read -r -p "$prompt [Y/n]: " answer
    answer="${answer:-y}"
  else
    read -r -p "$prompt [y/N]: " answer
    answer="${answer:-n}"
  fi

  [[ "$answer" =~ ^[Yy] ]]
}

choose_runtime() {
  local answer

  if [[ "$RUNTIME" != "ask" ]]; then
    return
  fi

  if [[ "$YES" == "true" || ! -t 0 || ! -t 1 ]]; then
    if [[ "$RUNTIME_EXPLICIT" == "true" ]]; then
      return
    fi
    RUNTIME="none"
    return
  fi

  section "Optional runtime"
  printf '  1) OpenClaw runtime with Ditto skill + Minos skill/persona files\n'
  printf '  2) Hermes runtime with Ditto skill + Minos skill/persona files\n'
  printf '  3) Ditto @minos graph only\n'
  printf '  4) Skip runtime setup\n'

  while true; do
    read -r -p "Choose runtime path (1/2/3/4) [1]: " answer
    answer="${answer:-1}"
    case "$answer" in
      1) RUNTIME="openclaw"; return ;;
      2) RUNTIME="hermes"; return ;;
      3|4) RUNTIME="none"; return ;;
      *) printf 'Please choose 1, 2, 3, or 4.\n' ;;
    esac
  done
}

npm_global_install_cmd() {
  local package="$1"
  local prefix

  prefix="$(npm config get prefix 2>/dev/null || true)"
  if [[ -n "$prefix" && -w "$prefix" ]]; then
    npm install -g "$package"
  elif command -v sudo >/dev/null 2>&1; then
    sudo npm install -g "$package"
  else
    npm install -g "$package"
  fi
}

node_version_at_least() {
  local required="$1"
  local current
  local major minor patch req_major req_minor req_patch

  command -v node >/dev/null 2>&1 || return 1
  current="$(node -p 'process.versions.node' 2>/dev/null || true)"
  [[ "$current" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || return 1

  IFS=. read -r major minor patch <<< "$current"
  IFS=. read -r req_major req_minor req_patch <<< "$required"

  (( major > req_major )) && return 0
  (( major < req_major )) && return 1
  (( minor > req_minor )) && return 0
  (( minor < req_minor )) && return 1
  (( patch >= req_patch ))
}

node_version_label() {
  if command -v node >/dev/null 2>&1; then
    node -v 2>/dev/null || printf 'unknown'
  else
    printf 'not installed'
  fi
}

run_as_root() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    return 1
  fi
}

install_nodejs_22() {
  if command -v apt-get >/dev/null 2>&1; then
    run_as_root apt-get update -qq
    run_as_root apt-get install -y -qq curl ca-certificates gnupg
    curl -fsSL https://deb.nodesource.com/setup_22.x | run_as_root bash -
    run_as_root apt-get install -y nodejs
  elif command -v dnf >/dev/null 2>&1; then
    curl -fsSL https://rpm.nodesource.com/setup_22.x | run_as_root bash -
    run_as_root dnf install -y nodejs
  elif command -v yum >/dev/null 2>&1; then
    curl -fsSL https://rpm.nodesource.com/setup_22.x | run_as_root bash -
    run_as_root yum install -y nodejs
  elif command -v brew >/dev/null 2>&1; then
    brew install node
  else
    return 1
  fi
}

ensure_node_for_openclaw() {
  local required="22.19.0"

  if node_version_at_least "$required" && command -v npm >/dev/null 2>&1; then
    ok "Node $(node -v) and npm $(npm -v 2>/dev/null || echo '?') satisfy OpenClaw."
    return
  fi

  warn "OpenClaw requires Node >= $required; current Node is $(node_version_label)."

  if [[ "$DRY_RUN" == "true" ]]; then
    info "Would install Node.js 22 before installing OpenClaw."
    command_hint "curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash -"
    command_hint "sudo apt-get install -y nodejs"
    return
  fi

  if ! run_quiet "Installing Node.js 22 for OpenClaw" "/tmp/minos-node22-install.log" install_nodejs_22; then
    fail "Could not install Node.js 22 automatically."
    command_hint "Install Node >= $required, then rerun: bash scripts/setup_ai_assistant.sh --with-ditto --openclaw"
    exit 1
  fi

  hash -r 2>/dev/null || true
  if ! node_version_at_least "$required" || ! command -v npm >/dev/null 2>&1; then
    fail "Node.js 22 install finished, but OpenClaw requirements are still not met."
    command_hint "Current node: $(node_version_label)"
    command_hint "Current npm: $(npm -v 2>/dev/null || echo 'not installed')"
    exit 1
  fi

  ok "Node $(node -v) and npm $(npm -v 2>/dev/null || echo '?') are ready for OpenClaw."
}

setup_ditto() {
  if [[ "$SETUP_DITTO" == "ask" ]]; then
    if ask_yes_no "Subscribe Ditto to the public @minos knowledge graph now?" "y"; then
      SETUP_DITTO="yes"
    else
      SETUP_DITTO="no"
    fi
  fi

  if [[ "$SETUP_DITTO" != "yes" ]]; then
    if [[ "${MINOS_DITTO_ALREADY_READY:-false}" == "true" || -f "$ROOT_DIR/.minosvm-ditto-default-ready" ]]; then
      ok "Using existing Ditto @minos graph setup."
      DITTO_SETUP_STATUS="ok"
    else
      warn "Skipping Ditto @minos graph setup."
      DITTO_SETUP_STATUS="skipped"
    fi
    return
  fi

  if [[ ! -x "$DITTO_SETUP_SCRIPT" && ! -f "$DITTO_SETUP_SCRIPT" ]]; then
    fail "Missing Ditto setup script: $DITTO_SETUP_SCRIPT"
    exit 1
  fi

  section "Step 1: Ditto @minos graph"
  info "Creates or uses local Ditto CLI auth and subscribes read-only to @minos."
  if [[ "${MINOS_DITTO_SEED_FALLBACK:-}" == "never" ]]; then
    info "Public graph only: private fallback memory seeding is disabled."
  else
    info "If graph retrieval cannot be verified, setup can save a private fallback copy from public Minos docs."
  fi
  warn "If a claim URL is saved, open it yourself and do not paste it into public channels or logs."
  if [[ "$DRY_RUN" == "true" ]]; then
    if [[ "${MINOS_DITTO_SEED_FALLBACK:-}" == "never" ]]; then
      command_hint "MINOS_DITTO_SEED_FALLBACK=never bash $DITTO_SETUP_SCRIPT --yes"
    else
      command_hint "bash $DITTO_SETUP_SCRIPT --yes"
    fi
    DITTO_SETUP_STATUS="planned"
    return
  fi

  local claim_file before_mtime after_mtime
  claim_file="$(ditto_claim_file_path)"
  before_mtime="$(file_mtime "$claim_file")"
  if MINOS_DITTO_EMBEDDED=true bash "$DITTO_SETUP_SCRIPT" --yes; then
    DITTO_SETUP_STATUS="ok"
  else
    DITTO_SETUP_STATUS="failed"
    warn "Ditto @minos setup did not complete. Continuing with local Minos runtime files."
    command_hint "Retry later: bash scripts/setup_ditto_agent.sh --yes"
    command_hint "Expected Ditto command: heyditto graphs add @minos"
    return
  fi
  after_mtime="$(file_mtime "$claim_file")"
  if [[ -s "$claim_file" && "$after_mtime" != "$before_mtime" ]]; then
    DITTO_CLAIM_CREATED_THIS_RUN=true
  fi
}

has_ditto_auth() {
  if command -v heyditto >/dev/null 2>&1; then
    heyditto status --output json >/dev/null 2>&1
    return
  fi

  local config_dir="${DITTO_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/heyditto/cli}"
  [[ -f "$config_dir/config.json" || -f "$config_dir/auth.json" ]]
}

ensure_ditto_cli_for_runtime() {
  if command -v heyditto >/dev/null 2>&1; then
    ok "Ditto CLI is available for runtime skills."
    return 0
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    info "Installing Ditto CLI globally for runtime skills"
    command_hint "npm install -g @heyditto/cli@latest"
    return 0
  fi

  if ! command -v npm >/dev/null 2>&1; then
    warn "Node/npm is missing, so the runtime Ditto skill may not be able to read @minos."
    command_hint "Install Node/npm or rerun: bash install.sh"
    return 1
  fi

  run_quiet "Installing Ditto CLI globally for runtime skills" "/tmp/minos-ai-ditto-npm-install.log" npm_global_install_cmd "@heyditto/cli@latest"
  hash -r 2>/dev/null || true

  if command -v heyditto >/dev/null 2>&1; then
    ok "Ditto CLI is available for runtime skills."
    return 0
  fi

  warn "heyditto is not on PATH after install."
  command_hint "npm install -g @heyditto/cli@latest"
  return 1
}

ditto_config_file() {
  local config_dir="${DITTO_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/heyditto/cli}"

  if [[ -f "$config_dir/config.json" ]]; then
    printf '%s\n' "$config_dir/config.json"
  elif [[ -f "$config_dir/auth.json" ]]; then
    printf '%s\n' "$config_dir/auth.json"
  fi
}

read_ditto_api_key() {
  local config_file

  config_file="$(ditto_config_file || true)"
  [[ -n "$config_file" && -f "$config_file" ]] || return 1

  python3 - "$config_file" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    data = json.load(open(path))
except Exception:
    sys.exit(1)

keys = {"apiKey", "api_key", "key", "token", "bearerToken", "accessToken"}

def walk(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, str) and item.strip():
                return item.strip()
        for item in value.values():
            found = walk(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = walk(item)
            if found:
                return found
    return ""

print(walk(data))
PY
}

minos_mcp_include_csv() {
  local IFS=,
  printf '%s' "${MINOS_MCP_TOOLS[*]}"
}

openclaw_minos_mcp_json() {
  python3 - "$MINOS_MCP_URL" "$MINOS_MCP_TIMEOUT" "$MINOS_MCP_CONNECT_TIMEOUT" "${MINOS_MCP_TOOLS[@]}" <<'PY'
import json
import sys

url = sys.argv[1]
tools = sys.argv[4:]

def number(value: str):
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed

print(json.dumps({
    "url": url,
    "transport": "streamable-http",
    "timeout": number(sys.argv[2]),
    "connectTimeout": number(sys.argv[3]),
    "supportsParallelToolCalls": True,
    "toolFilter": {
        "include": tools,
    },
}, separators=(",", ":")))
PY
}

configure_openclaw_minos_mcp() {
  local include_csv
  local config_json

  section "OpenClaw Minos MCP"
  include_csv="$(minos_mcp_include_csv)"

  if [[ "$DRY_RUN" == "true" ]]; then
    info "Would configure OpenClaw Minos MCP for live subnet data."
    command_hint "openclaw mcp set $MINOS_MCP_NAME '{...}'"
    command_hint "openclaw mcp probe $MINOS_MCP_NAME --json"
    command_hint "endpoint: $MINOS_MCP_URL"
    command_hint "tools: $include_csv"
    return
  fi

  if ! command -v openclaw >/dev/null 2>&1; then
    warn "OpenClaw is not on PATH, so Minos MCP could not be configured."
    return
  fi

  config_json="$(openclaw_minos_mcp_json)"
  if ! run_quiet "Configuring OpenClaw Minos MCP" "/tmp/minos-openclaw-mcp-set.log" openclaw mcp set "$MINOS_MCP_NAME" "$config_json"; then
    warn "OpenClaw Minos MCP config did not complete."
    command_hint "Retry later: openclaw mcp set $MINOS_MCP_NAME '<json config>'"
    return
  fi

  if ! run_quiet "Probing OpenClaw Minos MCP" "/tmp/minos-openclaw-mcp-probe.log" openclaw mcp probe "$MINOS_MCP_NAME" --json; then
    warn "OpenClaw Minos MCP was saved, but probe did not complete."
    command_hint "Retry later: openclaw mcp probe $MINOS_MCP_NAME --json"
  fi

  openclaw mcp reload >/dev/null 2>&1 || true
}

configure_hermes_minos_mcp() {
  local hermes_home
  local config_path
  local include_csv

  section "Hermes Minos MCP"
  hermes_home="$(hermes_home_dir)"
  config_path="${HERMES_CONFIG_PATH:-$hermes_home/config.yaml}"
  include_csv="$(minos_mcp_include_csv)"

  if [[ "$DRY_RUN" == "true" ]]; then
    info "Would merge Minos MCP into Hermes config."
    command_hint "$config_path"
    command_hint "endpoint: $MINOS_MCP_URL"
    command_hint "tools: $include_csv"
    command_hint "reload inside Hermes: /reload-mcp"
    return
  fi

  mkdir -p "$(dirname "$config_path")"

  python3 - "$config_path" "$MINOS_MCP_URL" "$MINOS_MCP_TIMEOUT" "$MINOS_MCP_CONNECT_TIMEOUT" "${MINOS_MCP_TOOLS[@]}" <<'PY'
from pathlib import Path
import re
import shutil
import sys
from datetime import datetime, timezone

path = Path(sys.argv[1]).expanduser()
url = sys.argv[2]
timeout = sys.argv[3]
connect_timeout = sys.argv[4]
tools = sys.argv[5:]

server_block = [
    "  minos:",
    f"    url: \"{url}\"",
    "    enabled: true",
    f"    timeout: {timeout}",
    f"    connect_timeout: {connect_timeout}",
    "    supports_parallel_tool_calls: true",
    "    tools:",
    "      include:",
]
server_block.extend(f"        - {tool}" for tool in tools)
server_block.extend([
    "      resources: false",
    "      prompts: false",
])

original = path.read_text() if path.exists() else ""
lines = original.splitlines()

def backup():
    if path.exists() and original.strip():
        suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        shutil.copy2(path, path.with_name(path.name + f".minos-backup-{suffix}"))

def is_top_level(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#") and not line.startswith((" ", "\t"))

def indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))

start = None
for idx, line in enumerate(lines):
    if re.match(r"^mcp_servers\s*:\s*(?:\{\s*\})?\s*$", line):
        start = idx
        break

if start is None:
    if lines and lines[-1].strip():
        lines.append("")
    lines.append("mcp_servers:")
    lines.extend(server_block)
else:
    lines[start] = "mcp_servers:"
    end = len(lines)
    for idx in range(start + 1, len(lines)):
        if is_top_level(lines[idx]):
            end = idx
            break

    existing = None
    for idx in range(start + 1, end):
        if indent(lines[idx]) == 2 and re.match(r"^\s{2}minos\s*:\s*$", lines[idx]):
            existing = idx
            break

    if existing is not None:
        stop = end
        for idx in range(existing + 1, end):
            if lines[idx].strip() and indent(lines[idx]) <= 2:
                stop = idx
                break
        lines = lines[:existing] + lines[stop:]
        end -= (stop - existing)

    lines = lines[:start + 1] + server_block + lines[start + 1:]

new_text = "\n".join(lines).rstrip() + "\n"
if new_text != original:
    backup()
    path.write_text(new_text)
PY

  chmod 600 "$config_path" 2>/dev/null || true
  ok "Hermes Minos MCP config is ready."
  command_hint "$config_path"

  if command -v hermes >/dev/null 2>&1 && hermes mcp --help 2>/dev/null | grep -q "test"; then
    if ! run_quiet "Testing Hermes Minos MCP" "/tmp/minos-hermes-mcp-test.log" hermes mcp test "$MINOS_MCP_NAME"; then
      warn "Hermes Minos MCP config was saved, but the MCP test did not complete."
      command_hint "Retry inside Hermes with: /reload-mcp"
    fi
  else
    command_hint "Reload inside Hermes with: /reload-mcp"
  fi
}

write_env_value() {
  local file="$1"
  local key="$2"
  local value="$3"
  local backup_file="${file}.minos-backup-$(date -u +%Y%m%d%H%M%S)"
  local tmp_file

  if [[ -z "$value" ]]; then
    return
  fi

  info "Writing $key into runtime env"
  command_hint "$file"

  if [[ "$DRY_RUN" == "true" ]]; then
    return
  fi

  mkdir -p "$(dirname "$file")"
  tmp_file="$(mktemp)"

  if [[ -f "$file" ]]; then
    cp "$file" "$backup_file"
    chmod 600 "$backup_file" 2>/dev/null || true
    grep -v -E "^${key}=" "$file" > "$tmp_file" || true
  else
    : > "$tmp_file"
  fi

  printf '%s=%s\n' "$key" "$value" >> "$tmp_file"
  mv "$tmp_file" "$file"
  chmod 600 "$file" 2>/dev/null || true
}

copy_skill_dir() {
  local source_dir="$1"
  local target_dir="$2"
  local label="$3"

  if [[ ! -d "$source_dir" ]]; then
    fail "Missing $label source: $source_dir"
    exit 1
  fi

  if [[ "$EMBEDDED" != "true" ]]; then
    info "Installing $label"
    command_hint "$target_dir"
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    return
  fi

  mkdir -p "$(dirname "$target_dir")"
  rm -rf "$target_dir.tmp"
  cp -R "$source_dir" "$target_dir.tmp"
  rm -rf "$target_dir"
  mv "$target_dir.tmp" "$target_dir"
}

install_context_file() {
  local source_file="$1"
  local target_file="$2"
  local label="$3"
  local template_file="${target_file}.minos-template"
  local backup_file="${target_file}.minos-backup-$(date -u +%Y%m%d%H%M%S)"

  if [[ ! -f "$source_file" ]]; then
    fail "Missing $label source: $source_file"
    exit 1
  fi

  if [[ "$DRY_RUN" == "false" ]]; then
    mkdir -p "$(dirname "$target_file")"
  fi

  if [[ ! -f "$target_file" ]]; then
    if [[ "$EMBEDDED" != "true" ]]; then
      info "Installing $label"
      command_hint "$target_file"
    fi
    [[ "$DRY_RUN" == "true" ]] || cp "$source_file" "$target_file"
    return
  fi

  if grep -q "MINOS-MINER-" "$target_file" 2>/dev/null && [[ "$FORCE_CONTEXT" != "true" ]]; then
    if [[ "$EMBEDDED" != "true" ]]; then
      ok "$label already has Minos context."
      command_hint "$target_file"
    fi
    return
  fi

  warn "$label already exists; saving a backup before adding Minos context."
  command_hint "backup:   $backup_file"
  command_hint "template: $template_file"

  if [[ "$DRY_RUN" == "false" ]]; then
    cp "$target_file" "$backup_file"
    cp "$source_file" "$template_file"
    {
      printf '\n\n'
      cat "$source_file"
    } >> "$target_file"
  fi
}

openclaw_workspace_dir() {
  if [[ -n "${OPENCLAW_WORKSPACE:-}" ]]; then
    printf '%s\n' "$OPENCLAW_WORKSPACE"
  elif [[ -n "${OPENCLAW_PROFILE:-}" && "${OPENCLAW_PROFILE:-}" != "default" ]]; then
    printf '%s\n' "$HOME/.openclaw/workspace-$OPENCLAW_PROFILE"
  else
    printf '%s\n' "$HOME/.openclaw/workspace"
  fi
}

openclaw_state_dir() {
  printf '%s\n' "${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
}

hermes_home_dir() {
  printf '%s\n' "${HERMES_HOME:-$HOME/.hermes}"
}

install_openclaw_minos_context() {
  local workspace

  [[ "$INSTALL_RUNTIME_CONTEXT" == "true" ]] || return
  workspace="$(openclaw_workspace_dir)"

  section "OpenClaw local knowledge"
  [[ "$EMBEDDED" == "true" ]] && info "Installing Minos skill/persona files for OpenClaw."
  copy_skill_dir "$MINOS_SKILL_SOURCE" "$workspace/skills/minos-miner" "OpenClaw minos-miner skill"
  install_context_file "$OPENCLAW_CONTEXT_SOURCE/AGENTS.md" "$workspace/AGENTS.md" "OpenClaw AGENTS.md"
  install_context_file "$OPENCLAW_CONTEXT_SOURCE/SOUL.md" "$workspace/SOUL.md" "OpenClaw SOUL.md"
  install_context_file "$OPENCLAW_CONTEXT_SOURCE/TOOLS.md" "$workspace/TOOLS.md" "OpenClaw TOOLS.md"
  [[ "$EMBEDDED" == "true" ]] && ok "OpenClaw Minos local knowledge installed."
  return 0
}

install_hermes_minos_context() {
  local hermes_home

  [[ "$INSTALL_RUNTIME_CONTEXT" == "true" ]] || return
  hermes_home="$(hermes_home_dir)"

  section "Hermes local knowledge"
  [[ "$EMBEDDED" == "true" ]] && info "Installing Minos skill/persona files for Hermes."
  copy_skill_dir "$MINOS_SKILL_SOURCE" "$hermes_home/skills/minos-miner" "Hermes minos-miner skill"
  install_context_file "$HERMES_SOUL_TEMPLATE" "$hermes_home/SOUL.md" "Hermes SOUL.md"

  if [[ "$EMBEDDED" != "true" ]]; then
    info "Installing Hermes Minos SOUL template"
    command_hint "$hermes_home/SOUL.minos-miner-template.md"
  fi
  if [[ "$DRY_RUN" == "false" ]]; then
    mkdir -p "$hermes_home"
    cp "$HERMES_SOUL_TEMPLATE" "$hermes_home/SOUL.minos-miner-template.md"
  fi
  [[ "$EMBEDDED" == "true" ]] && ok "Hermes Minos local knowledge installed."
  return 0
}

configure_hermes_tui_background() {
  local hermes_home
  local env_file

  hermes_home="$(hermes_home_dir)"
  env_file="$hermes_home/.env"

  write_env_value "$env_file" "HERMES_TUI_BACKGROUND" "$HERMES_TUI_BACKGROUND"

  for profile_file in "$HOME/.bashrc" "$HOME/.zshrc"; do
    [[ -f "$profile_file" ]] || continue
    if grep -q "MINOS-HERMES-TUI-START" "$profile_file" 2>/dev/null; then
      continue
    fi
    info "Adding Hermes TUI terminal setting"
    command_hint "$profile_file"
    if [[ "$DRY_RUN" == "false" ]]; then
      {
        printf '\n# MINOS-HERMES-TUI-START\n'
        printf 'export HERMES_TUI_BACKGROUND="${HERMES_TUI_BACKGROUND:-#0A0A0A}"\n'
        printf '# MINOS-HERMES-TUI-END\n'
      } >> "$profile_file"
    fi
  done
}

install_openclaw_ditto_auth() {
  local api_key
  local state_dir

  if [[ "$DRY_RUN" == "true" ]]; then
    info "Would write Ditto auth into OpenClaw runtime env when Ditto auth exists."
    command_hint "$(openclaw_state_dir)/.env"
    return
  fi

  api_key="$(read_ditto_api_key 2>/dev/null || true)"
  if [[ -z "$api_key" ]]; then
    warn "Could not find a Ditto API key for OpenClaw."
    command_hint "Run: bash scripts/setup_ditto_agent.sh"
    return
  fi

  state_dir="$(openclaw_state_dir)"
  write_env_value "$state_dir/.env" "DITTO_API_KEY" "$api_key"
}

install_openclaw_ditto_skill() {
  local workspace

  workspace="$(openclaw_workspace_dir)"
  if [[ -d "$workspace/skills/ditto" ]]; then
    ok "OpenClaw Ditto skill already installed."
    return
  fi

  run_quiet_or_existing "Installing OpenClaw Ditto skill" "/tmp/minos-openclaw-ditto-skill.log" openclaw skills install ditto
}

ensure_openclaw_gateway_config() {
  local config_path

  if [[ "$DRY_RUN" == "true" ]]; then
    info "Would configure OpenClaw gateway for local loopback access."
    command_hint "~/.openclaw/openclaw.json"
    return
  fi

  config_path="$(openclaw config file 2>/dev/null || printf '%s/.openclaw/openclaw.json' "$HOME")"
  mkdir -p "$(dirname "$config_path")"

  python3 - "$config_path" <<'PY'
import json
import secrets
import sys
from pathlib import Path

path = Path(sys.argv[1]).expanduser()
try:
    data = json.loads(path.read_text()) if path.exists() else {}
except Exception:
    data = {}

gateway = data.setdefault("gateway", {})
gateway["mode"] = "local"
gateway["bind"] = "loopback"
gateway["port"] = int(gateway.get("port") or 18789)

auth = gateway.setdefault("auth", {})
auth["mode"] = auth.get("mode") or "token"
if auth["mode"] == "token" and not auth.get("token"):
    auth["token"] = secrets.token_hex(32)

path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
PY
  chmod 600 "$config_path" 2>/dev/null || true
  ok "OpenClaw gateway config is ready."
}

wait_for_openclaw_gateway() {
  local attempt

  for attempt in {1..20}; do
    if openclaw gateway health >/tmp/minos-openclaw-gateway-health.log 2>&1; then
      ok "OpenClaw gateway is running on 127.0.0.1:18789."
      return 0
    fi
    sleep 1
  done

  warn "OpenClaw gateway did not report healthy yet."
  command_hint "pm2 logs openclaw-gateway --lines 80"
  command_hint "openclaw gateway status"
  return 1
}

start_openclaw_gateway_pm2() {
  if [[ "$DRY_RUN" == "true" ]]; then
    info "Would run OpenClaw gateway under PM2 for container/headless VMs."
    command_hint "pm2 start $OPENCLAW_GATEWAY_SCRIPT --name openclaw-gateway --interpreter bash"
    return
  fi

  if ! command -v pm2 >/dev/null 2>&1; then
    warn "PM2 is not available; leaving OpenClaw gateway stopped."
    command_hint "Foreground fallback: bash scripts/openclaw-gateway.sh"
    return
  fi

  if [[ ! -x "$OPENCLAW_GATEWAY_SCRIPT" ]]; then
    chmod +x "$OPENCLAW_GATEWAY_SCRIPT" 2>/dev/null || true
  fi

  pm2 delete openclaw-gateway >/dev/null 2>&1 || true
  run_quiet "Starting OpenClaw gateway under PM2" "/tmp/minos-openclaw-gateway-pm2.log" pm2 start "$OPENCLAW_GATEWAY_SCRIPT" --name openclaw-gateway --interpreter bash

  pm2 save >/dev/null 2>&1 || true
  wait_for_openclaw_gateway || true
}

install_hermes_ditto_auth() {
  local api_key
  local hermes_home

  if [[ "$DRY_RUN" == "true" ]]; then
    info "Would write Ditto auth into Hermes runtime env when Ditto auth exists."
    command_hint "$(hermes_home_dir)/.env"
    return
  fi

  api_key="$(read_ditto_api_key 2>/dev/null || true)"
  if [[ -z "$api_key" ]]; then
    warn "Could not find a Ditto API key for Hermes."
    command_hint "Run: bash scripts/setup_ditto_agent.sh"
    return
  fi

  hermes_home="$(hermes_home_dir)"
  write_env_value "$hermes_home/.env" "DITTO_API_KEY" "$api_key"
}

ensure_openclaw() {
  if command -v openclaw >/dev/null 2>&1; then
    ok "OpenClaw is installed."
    return
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    info "Installing OpenClaw globally"
    command_hint "npm install -g openclaw@latest"
    return
  fi

  if ! command -v npm >/dev/null 2>&1; then
    fail "Node/npm is required to install OpenClaw automatically."
    command_hint "Install Node/npm or rerun: bash install.sh"
    exit 1
  fi

  run_quiet "Installing OpenClaw globally" "/tmp/minos-openclaw-npm-install.log" npm_global_install_cmd "openclaw@latest"
  hash -r 2>/dev/null || true
}

ensure_hermes() {
  if command -v hermes >/dev/null 2>&1; then
    ok "Hermes is installed."
    return
  fi

  warn "Installing Hermes from the official installer in noninteractive mode."
  command_hint "curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --skip-setup"

  if [[ "$DRY_RUN" == "true" ]]; then
    return
  fi

  if ! command -v curl >/dev/null 2>&1; then
    fail "curl is required to install Hermes automatically."
    exit 1
  fi

  run_quiet "Installing Hermes" "/tmp/minos-hermes-install.log" bash -c "curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --skip-setup"
  hash -r 2>/dev/null || true
}

openclaw_status_text() {
  openclaw models status 2>/dev/null || true
}

openclaw_default_model() {
  local status

  status="$(openclaw_status_text)"
  awk -F: '/^Default[[:space:]]*:/ {gsub(/^[ \t]+|[ \t]+$/, "", $2); print $2; exit}' <<< "$status"
}

openclaw_provider_usable() {
  local status

  status="$(openclaw_status_text)"
  grep -q "status=usable" <<< "$status" && ! grep -q "Missing auth" <<< "$status"
}

setup_openclaw_provider() {
  local answer
  local default_model

  section "OpenClaw model provider"
  info "OpenClaw needs a model provider for reasoning. Ditto supplies memory, not the model."
  warn "Enter provider credentials only inside OpenClaw/provider OAuth flows."

  if [[ "$DRY_RUN" == "true" ]]; then
    info "Would check OpenClaw provider auth and prompt if no usable provider is configured."
    command_hint "openclaw models status"
    command_hint "openclaw models auth login --provider openai --set-default"
    command_hint "openclaw models auth login --provider anthropic --set-default"
    command_hint "openclaw models auth login --provider openrouter --set-default"
    return
  fi

  if openclaw_provider_usable; then
    default_model="$(openclaw_default_model)"
    ok "OpenClaw provider already appears usable."
    [[ -n "$default_model" ]] && command_hint "Default model: $default_model"
    command_hint "Change later: openclaw models auth add"
    return
  fi

  warn "No usable OpenClaw provider detected yet."

  if [[ "$YES" == "true" || ! -t 0 || ! -t 1 ]]; then
    command_hint "Configure later with one of:"
    command_hint "openclaw models auth login --provider openai --set-default"
    command_hint "openclaw models auth login --provider anthropic --set-default"
    command_hint "openclaw models auth login --provider openrouter --set-default"
    command_hint "openclaw models auth add"
    return
  fi

  printf '  %s1%s) OpenAI / Codex account %s(recommended)%s\n' "$BOLD" "$NC" "$DIM" "$NC"
  printf '  %s2%s) Claude / Anthropic account\n' "$BOLD" "$NC"
  printf '  %s3%s) OpenRouter account\n' "$BOLD" "$NC"
  printf '  %s4%s) OpenClaw guided provider setup\n' "$BOLD" "$NC"
  printf '  %s5%s) Skip provider setup for now\n' "$BOLD" "$NC"

  while true; do
    read -r -p "Choose OpenClaw provider path (1/2/3/4/5) [1]: " answer
    answer="${answer:-1}"
    case "$answer" in
      1)
        run_optional_interactive_cmd "OpenAI/Codex provider setup" openclaw models auth login --provider openai --set-default || true
        break
        ;;
      2)
        run_optional_interactive_cmd "Claude/Anthropic provider setup" openclaw models auth login --provider anthropic --set-default || true
        break
        ;;
      3)
        run_optional_interactive_cmd "OpenRouter provider setup" openclaw models auth login --provider openrouter --set-default || true
        break
        ;;
      4)
        run_optional_interactive_cmd "OpenClaw guided provider setup" openclaw models auth add || true
        break
        ;;
      5)
        warn "Skipped OpenClaw provider setup."
        break
        ;;
      *)
        printf 'Please choose 1, 2, 3, 4, or 5.\n'
        ;;
    esac
  done

  if openclaw_provider_usable; then
    default_model="$(openclaw_default_model)"
    ok "OpenClaw provider is ready."
    [[ -n "$default_model" ]] && command_hint "Default model: $default_model"
  else
    warn "OpenClaw still does not report a usable provider."
    command_hint "Check: openclaw models status"
  fi
}

setup_hermes_provider() {
  local answer

  section "Hermes model provider"
  info "Hermes needs a model provider for reasoning. Ditto supplies memory, not the model."
  warn "Enter provider credentials only inside Hermes/provider OAuth flows."

  if [[ "$DRY_RUN" == "true" ]]; then
    info "Would offer Hermes Portal, full Hermes setup, or skip."
    command_hint "hermes setup --portal"
    command_hint "hermes setup"
    return
  fi

  if [[ "$RUN_HERMES_SETUP" == "true" ]]; then
    run_optional_interactive_cmd "Hermes Portal setup" hermes setup --portal || true
    return
  fi

  if [[ "$YES" == "true" || ! -t 0 || ! -t 1 ]]; then
    command_hint "Configure later with one of:"
    command_hint "hermes setup --portal"
    command_hint "hermes setup"
    return
  fi

  printf '  %s1%s) Hermes / Nous Portal setup %s(recommended)%s\n' "$BOLD" "$NC" "$DIM" "$NC"
  printf '  %s2%s) Full Hermes provider setup\n' "$BOLD" "$NC"
  printf '  %s3%s) Skip provider setup for now\n' "$BOLD" "$NC"

  while true; do
    read -r -p "Choose Hermes provider path (1/2/3) [1]: " answer
    answer="${answer:-1}"
    case "$answer" in
      1)
        run_optional_interactive_cmd "Hermes Portal setup" hermes setup --portal || true
        break
        ;;
      2)
        run_optional_interactive_cmd "Hermes provider setup" hermes setup || true
        break
        ;;
      3)
        warn "Skipped Hermes provider setup."
        break
        ;;
      *)
        printf 'Please choose 1, 2, or 3.\n'
        ;;
    esac
  done
}

setup_openclaw() {
  section "OpenClaw runtime"
  ensure_node_for_openclaw
  ensure_openclaw
  [[ "$DRY_RUN" == "true" ]] || command -v openclaw >/dev/null 2>&1 || {
    fail "OpenClaw install completed, but openclaw is not on PATH."
    exit 1
  }

  install_openclaw_minos_context
  ensure_ditto_cli_for_runtime || true
  install_openclaw_ditto_auth
  install_openclaw_ditto_skill
  configure_openclaw_minos_mcp
  ensure_openclaw_gateway_config
  start_openclaw_gateway_pm2

  if [[ "$RUN_ONBOARDING" == "true" ]]; then
    run_cmd openclaw onboard --install-daemon
  else
    ok "Skipped OpenClaw onboarding to keep setup inside the Minos flow."
  fi

  setup_openclaw_provider
}

setup_hermes() {
  section "Hermes runtime"
  ensure_hermes
  [[ "$DRY_RUN" == "true" ]] || command -v hermes >/dev/null 2>&1 || {
    fail "Hermes install completed, but hermes is not on PATH."
    exit 1
  }

  install_hermes_minos_context
  ensure_ditto_cli_for_runtime || true
  configure_hermes_tui_background
  install_hermes_ditto_auth
  run_quiet_or_existing "Adding Hermes Ditto skill tap" "/tmp/minos-hermes-ditto-tap.log" hermes skills tap add ditto-assistant/ditto-hermes
  run_quiet_or_existing "Installing Hermes Ditto skill" "/tmp/minos-hermes-ditto-skill.log" hermes skills install ditto-assistant/ditto-hermes/ditto
  configure_hermes_minos_mcp

  setup_hermes_provider
}

run_cmd() {
  command_hint "$*"
  if [[ "$DRY_RUN" == "false" ]]; then
    "$@"
  fi
}

run_optional_interactive_cmd() {
  local label="$1"
  shift

  command_hint "$*"
  if [[ "$DRY_RUN" == "true" ]]; then
    return 0
  fi

  if "$@"; then
    ok "$label complete."
    return 0
  fi

  warn "$label did not finish. Runtime install is still complete; configure the provider later."
  return 1
}

print_ditto_claim_panel() {
  local claim_url claim_file

  [[ "$SETUP_DITTO" == "yes" ]] || return 0
  [[ "$DRY_RUN" == "false" ]] || return 0
  [[ "$DITTO_CLAIM_CREATED_THIS_RUN" == "true" ]] || return 0

  claim_url="$(read_ditto_claim_url || true)"
  [[ -n "$claim_url" ]] || return 0
  claim_file="$(ditto_claim_file_path)"

  panel "Claim your Ditto agent" "Open this private URL yourself now to claim your Minos Miner AI Assistant:

$claim_url

The same URL is saved locally with private file permissions:
$claim_file

Show it locally with:
  sed -n '1p' \"$claim_file\"

This URL is sensitive until claimed. Do not paste it into public channels, screenshots, or logs."
}

print_runtime_provider_panel() {
  case "$RUNTIME" in
    openclaw)
      if [[ "$DRY_RUN" == "true" ]]; then
        panel "Connect OpenClaw to an AI provider" "After a real OpenClaw setup, OpenClaw will have the Minos skill/persona files, Ditto skill, and Minos MCP live-data connection configured. Connect a model provider before chatting with the agent.

Use one of these after setup:
  openclaw models auth login --provider openai --set-default
  openclaw models auth login --provider anthropic --set-default
  openclaw models auth login --provider openrouter --set-default

Then start OpenClaw:
  bash scripts/openclaw-tui.sh"
      else
        panel "Connect OpenClaw to an AI provider" "OpenClaw has the Minos skill/persona files, Ditto skill, and Minos MCP live-data connection configured. If you have not connected a model provider yet, do that before chatting with the agent.

Use one of these after setup:
  openclaw models auth login --provider openai --set-default
  openclaw models auth login --provider anthropic --set-default
  openclaw models auth login --provider openrouter --set-default

Then start OpenClaw:
  bash scripts/openclaw-tui.sh"
      fi
      ;;
    hermes)
      if [[ "$DRY_RUN" == "true" ]]; then
        panel "Connect Hermes to an AI provider" "After a real Hermes setup, Hermes will have the Minos skill/persona files, Ditto skill, and Minos MCP live-data connection configured. Connect a model provider before chatting with the agent.

Use one of these after setup:
  hermes setup --portal
  hermes setup

Then start Hermes:
  hermes --tui --skills minos-miner
  hermes chat --cli --skills minos-miner"
      else
        panel "Connect Hermes to an AI provider" "Hermes has the Minos skill/persona files, Ditto skill, and Minos MCP live-data connection configured. If you have not connected a model provider yet, do that before chatting with the agent.

Use one of these after setup:
  hermes setup --portal
  hermes setup

Then start Hermes:
  hermes --tui --skills minos-miner
  hermes chat --cli --skills minos-miner"
      fi
      ;;
  esac
}

print_next_steps() {
  section "Next steps"
  print_ditto_claim_panel
  print_runtime_provider_panel

  case "$DITTO_SETUP_STATUS" in
    ok)
      command_hint "Check Ditto graph subscription: heyditto graphs list"
      command_hint "Ask Ditto: PM2 says my Minos miner is online but I have 0 weight. What should I check?"
      ;;
    planned)
      command_hint "Real setup will verify Ditto graph subscription with: heyditto graphs list"
      command_hint "Real setup will test search with: heyditto search \"Minos PM2 online but 0 weight\""
      ;;
    failed)
      command_hint "Retry Ditto @minos setup: bash scripts/setup_ditto_agent.sh --yes"
      ;;
  esac

  case "$RUNTIME" in
    openclaw)
      command_hint "Check OpenClaw provider status: openclaw models status"
      command_hint "Check Minos MCP tools: openclaw mcp probe minos --json"
      command_hint "OpenClaw gateway status: openclaw gateway status"
      command_hint "OpenClaw gateway logs: pm2 logs openclaw-gateway --lines 80"
      command_hint "If Ditto is unavailable inside OpenClaw, rerun: bash scripts/setup_ai_assistant.sh --with-ditto --openclaw"
      ;;
    hermes)
      command_hint "Reload Hermes MCP after config changes: /reload-mcp"
      command_hint "Check Hermes Minos MCP: hermes mcp test minos"
      command_hint "If Ditto is unavailable inside Hermes, rerun: bash scripts/setup_ai_assistant.sh --with-ditto --hermes"
      ;;
    *)
      command_hint "Add a runtime later: bash scripts/setup_ai_assistant.sh --with-ditto --openclaw"
      command_hint "Or: bash scripts/setup_ai_assistant.sh --with-ditto --hermes"
      ;;
  esac
}

main() {
  if [[ "$EMBEDDED" != "true" ]]; then
    banner
    info "1.0.0 focuses on @minos memory, Minos MCP live data, and OpenClaw/Hermes support."
    info "Provider credentials stay inside the selected runtime or provider OAuth flow."
  fi

  setup_ditto

  if [[ "$SETUP_DITTO" == "yes" && "$DRY_RUN" == "false" && "$DITTO_SETUP_STATUS" == "ok" && ! has_ditto_auth ]]; then
    warn "Ditto setup did not leave CLI auth visible. Runtime skills may need Ditto login later."
    command_hint "bash scripts/setup_ditto_agent.sh"
  fi

  choose_runtime

  case "$RUNTIME" in
    none) ok "No runtime selected." ;;
    openclaw) setup_openclaw ;;
    hermes) setup_hermes ;;
    *) fail "Unknown runtime: $RUNTIME"; exit 1 ;;
  esac

  if [[ "$DRY_RUN" == "true" ]]; then
    success_card "AI assistant dry run complete" "No changes were made. Review the planned steps and next-step guidance below."
  elif [[ "$DITTO_SETUP_STATUS" == "failed" ]]; then
    date -u +"ditto_incomplete_at_utc=%Y-%m-%dT%H:%M:%SZ" > "$INCOMPLETE_MARKER"
    panel "AI assistant setup incomplete" "Runtime setup continued, but Ditto @minos graph setup did not complete. Review the retry step below before relying on Ditto memory."
  else
    rm -f "$INCOMPLETE_MARKER"
    success_card "AI assistant setup complete" "Requested Minos AI assistant setup steps finished. Review the next steps below."
  fi
  print_next_steps
}

main
