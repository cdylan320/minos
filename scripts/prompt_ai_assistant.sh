#!/usr/bin/env bash
# First-run prompt for the Minos Miner AI Assistant.
#
# This is intentionally tiny and safe to call from install.sh, start-miner.sh,
# or a MinosVM first-login script. It checks setup state only to decide whether
# to launch scripts/setup_ai_assistant.sh.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ASSISTANT_SCRIPT="$ROOT_DIR/scripts/setup_ai_assistant.sh"
DITTO_SCRIPT="$ROOT_DIR/scripts/setup_ditto_agent.sh"
MARKER_FILE="$ROOT_DIR/.minos_ai_assistant_prompted"

MODE="prompt"
DEFAULT_ANSWER="y"
ONCE=false
ROLE="miner"
RUNTIME_ONLY=false

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

print_box() {
  local title="$1"
  local body="$2"
  local width="${3:-72}"
  local title_text=" $title "
  local inner_width=$((width - 4))
  local line wrapped

  if [[ "$USE_TTY_UI" != "true" ]]; then
    printf '\n%s\n' "$title"
    printf '%s\n' "$body"
    return
  fi

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
}

section() {
  printf '\n%s◆%s %s%s%s\n' "$CYAN" "$NC" "$BOLD" "$1" "$NC"
}

ok() { printf '  %s✓%s %s\n' "$GREEN" "$NC" "$1"; }
warn() { printf '  %s⚠%s %s\n' "$YELLOW" "$NC" "$1"; }
hint() { printf '  %s%s%s\n' "$DIM" "$1" "$NC"; }

setup_terminal_ui

usage() {
  cat <<'EOF'
Usage: bash scripts/prompt_ai_assistant.sh [OPTIONS]

Options:
  --prompt           Show the assistant setup menu (default).
  --print            Only print the setup commands.
  --once             Do not prompt again if the user already answered once.
  --default <y|n>    Default menu behavior: y selects OpenClaw, n selects skip.
                     Default: y.
  --role <name>      Context label for output. Default: miner.
  --runtime-only     Offer only OpenClaw, Hermes, or skip. Ditto is assumed
                     already configured by the environment.
  --help, -h         Show this help.

This prompt launches scripts/setup_ai_assistant.sh with the selected path.
OpenClaw is the default runtime path. Hermes and Ditto-only @minos setup are optional.
If Ditto graph retrieval cannot be verified, setup can save a private fallback
copy from the public Minos docs outside MinosVM.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prompt) MODE="prompt"; shift ;;
    --print) MODE="print"; shift ;;
    --once) ONCE=true; shift ;;
    --default) DEFAULT_ANSWER="${2:-y}"; shift 2 ;;
    --role) ROLE="${2:-miner}"; shift 2 ;;
    --runtime-only) RUNTIME_ONLY=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ "$DEFAULT_ANSWER" != "y" && "$DEFAULT_ANSWER" != "n" ]]; then
  echo "Invalid --default value: $DEFAULT_ANSWER" >&2
  exit 1
fi

if [[ "$ROLE" == "minosvm" || "${MINOSVM_AI_RUNTIMES_PREINSTALLED:-}" == "true" ]]; then
  RUNTIME_ONLY=true
  export MINOS_DITTO_SEED_FALLBACK="${MINOS_DITTO_SEED_FALLBACK:-never}"
fi

has_miner_env() {
  [[ -f "$ROOT_DIR/.env" ]] && grep -q '^MINER_TEMPLATE=' "$ROOT_DIR/.env"
}

is_demo_env() {
  local env_demo
  env_demo="${MINER_DEMO:-}"
  if [[ -f "$ROOT_DIR/.env" ]]; then
    env_demo="$(grep -E '^MINER_DEMO=' "$ROOT_DIR/.env" 2>/dev/null | tail -1 | cut -d= -f2- || true)"
  fi
  env_demo="${env_demo%%#*}"
  env_demo="$(printf '%s' "$env_demo" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')"
  env_demo="${env_demo//\"/}"
  env_demo="${env_demo//\'/}"
  [[ "$env_demo" =~ ^(1|true|yes|on)$ ]]
}

default_setup_choice() {
  if [[ "$DEFAULT_ANSWER" == "y" ]]; then
    printf '1\n'
  elif [[ "$RUNTIME_ONLY" == "true" ]]; then
    printf '3\n'
  else
    printf '4\n'
  fi
}

SETUP_CHOICE=""

ask_setup_choice() {
  local default="$1"
  local answer
  while true; do
    if [[ "$RUNTIME_ONLY" == "true" ]]; then
      read -r -p "Choose assistant runtime (1/2/3) [$default]: " answer
    else
      read -r -p "Choose assistant setup (1/2/3/4) [$default]: " answer
    fi
    answer="${answer:-$default}"
    if [[ "$RUNTIME_ONLY" == "true" ]]; then
      case "$answer" in
        1|2)
          SETUP_CHOICE="$answer"
          return 0
          ;;
        3)
          SETUP_CHOICE="4"
          return 0
          ;;
        *)
          echo "Please choose 1, 2, or 3."
          ;;
      esac
    else
      case "$answer" in
        1|2|3|4)
          SETUP_CHOICE="$answer"
          return 0
          ;;
        *)
          echo "Please choose 1, 2, 3, or 4."
          ;;
      esac
    fi
  done
}

run_setup_choice() {
  local choice="$1"
  local ditto_flag="--with-ditto"

  if [[ "$RUNTIME_ONLY" == "true" && -f "$ROOT_DIR/.minosvm-ditto-default-ready" ]]; then
    ditto_flag="--skip-ditto"
  fi

  case "$choice" in
    1)
      MINOS_AI_ASSISTANT_EMBEDDED=true bash "$ASSISTANT_SCRIPT" "$ditto_flag" --openclaw
      ;;
    2)
      MINOS_AI_ASSISTANT_EMBEDDED=true bash "$ASSISTANT_SCRIPT" "$ditto_flag" --hermes
      ;;
    3)
      MINOS_AI_ASSISTANT_EMBEDDED=true bash "$ASSISTANT_SCRIPT" --ditto-only
      ;;
    *)
      return 2
      ;;
  esac
}

setup_choice_label() {
  case "$1" in
    1) printf '@minos graph + Minos MCP + OpenClaw runtime' ;;
    2) printf '@minos graph + Minos MCP + Hermes runtime' ;;
    3) printf '@minos graph in Ditto only' ;;
    *) printf 'skip' ;;
  esac
}

print_intro() {
  if [[ "$RUNTIME_ONLY" == "true" ]]; then
    print_box "Minos Miner AI Assistant" "Ready-to-use Minos mining help, powered by the public @minos knowledge graph and Minos MCP live data.
Ditto is already part of the MinosVM baseline. Choose whether to enable a local runtime with Minos MCP.
No Minos secrets, configs, logs, wallet files, or model API keys are uploaded." 76
    section "Choose runtime"
    printf '  %s1%s) OpenClaw runtime %s(recommended)%s\n' "$BOLD" "$NC" "$DIM" "$NC"
    printf '  %s2%s) Hermes runtime\n' "$BOLD" "$NC"
    printf '  %s3%s) Skip for now\n' "$BOLD" "$NC"
    printf '\n'
    hint "Runtime setup uses the public @minos graph for memory and https://mcp.theminos.ai for live data."
    return
  fi

  print_box "Minos Miner AI Assistant" "Ready-to-use Minos mining help, powered by the public @minos knowledge graph and Minos MCP live data.
If graph retrieval cannot be verified, setup can save a private fallback copy from public Minos docs outside MinosVM.
No Minos secrets, configs, logs, wallet files, or model API keys are uploaded." 76
  section "Choose setup path"
  printf '  %s1%s) Ditto + Minos MCP + OpenClaw runtime %s(recommended)%s\n' "$BOLD" "$NC" "$DIM" "$NC"
  printf '  %s2%s) Ditto + Minos MCP + Hermes runtime\n' "$BOLD" "$NC"
  printf '  %s3%s) Ditto @minos graph only\n' "$BOLD" "$NC"
  printf '  %s4%s) Skip for now\n' "$BOLD" "$NC"
  printf '\n'
  hint "After runtime install, Minos checks provider auth and launches the selected runtime's setup if needed."
}

print_later_commands() {
  echo ""
  section "Run later"
  hint "bash start-miner.sh --setup-ai-assistant"
  if [[ "$RUNTIME_ONLY" != "true" ]]; then
    hint "bash start-miner.sh --setup-ditto"
  fi
}

if [[ "$ROLE" == "miner" ]] && ! has_miner_env; then
  exit 0
fi

if [[ "$ROLE" == "miner" ]] && is_demo_env; then
  exit 0
fi

if [[ "$ONCE" == "true" && -f "$MARKER_FILE" ]]; then
  exit 0
fi

if [[ ! -f "$ASSISTANT_SCRIPT" || ! -f "$DITTO_SCRIPT" ]]; then
  echo "Minos Miner AI Assistant scripts are missing. Re-run bash install.sh or update the repo." >&2
  exit 0
fi

if [[ "$MODE" == "print" ]]; then
  print_intro
  print_later_commands
  exit 0
fi

print_intro

if [[ ! -t 0 || ! -t 1 ]]; then
  print_later_commands
  exit 0
fi

ask_setup_choice "$(default_setup_choice)"

if [[ "$SETUP_CHOICE" == "4" ]]; then
  ok "Skipped. Your miner can run without the assistant."
  print_later_commands
  date -u +"skipped_at_utc=%Y-%m-%dT%H:%M:%SZ" > "$MARKER_FILE"
  exit 0
fi

echo ""
ok "Selected: $(setup_choice_label "$SETUP_CHOICE")"

if run_setup_choice "$SETUP_CHOICE"; then
  echo ""
  status="configured"
  if [[ -f "$ROOT_DIR/.minos_ai_assistant_incomplete" ]]; then
    warn "Minos Miner AI Assistant setup is incomplete; retry Ditto @minos setup before relying on Ditto memory."
    hint "bash scripts/setup_ditto_agent.sh --yes"
    status="incomplete"
  else
    ok "Minos Miner AI Assistant setup complete."
  fi
  date -u +"${status}_at_utc=%Y-%m-%dT%H:%M:%SZ" > "$MARKER_FILE"
else
  echo ""
  warn "AI assistant setup did not complete."
  hint "Retry: bash scripts/setup_ai_assistant.sh"
  exit 1
fi
