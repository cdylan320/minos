#!/usr/bin/env bash
# Friendly first-run launcher for MinosVM images.
#
# VM builders can call this from MOTD, shell profile, or desktop shortcut.
# It does not auto-start mining without the user's choice.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export MINOS_DITTO_SEED_FALLBACK="${MINOS_DITTO_SEED_FALLBACK:-never}"

RED=""
GREEN=""
YELLOW=""
BLUE=""
CYAN=""
DIM=""
BOLD=""
NC=""
TERM_WIDTH=78
USE_TTY_UI=false

setup_terminal_ui() {
  if command -v tput &>/dev/null; then
    TERM_WIDTH="$(tput cols 2>/dev/null || echo 78)"
    if [[ -z "$TERM_WIDTH" ]] || (( TERM_WIDTH < 60 )); then
      TERM_WIDTH=78
    elif (( TERM_WIDTH > 96 )); then
      TERM_WIDTH=96
    fi
  fi

  if [[ -z "${NO_COLOR:-}" ]] && [[ -t 1 ]] && [[ "${TERM:-}" != "dumb" ]] && command -v tput &>/dev/null; then
    local colors
    colors="$(tput colors 2>/dev/null || echo 0)"
    if [[ "$colors" =~ ^[0-9]+$ ]] && (( colors >= 8 )); then
      RED="$(tput setaf 1)"
      GREEN="$(tput setaf 2)"
      YELLOW="$(tput setaf 3)"
      BLUE="$(tput setaf 4)"
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
  local width="${1:-$TERM_WIDTH}"
  printf '%s\n' "${DIM}$(repeat_char "-" "$width")${NC}"
}

panel() {
  local title="$1"
  local body="$2"
  local width="${3:-76}"
  local title_text=" $title "
  local inner_width=$((width - 4))
  local line wrapped

  if [[ "$USE_TTY_UI" != "true" ]]; then
    printf '\n%s\n' "$title"
    printf '%s\n' "$body"
    return
  fi

  if (( width > TERM_WIDTH )); then
    width="$TERM_WIDTH"
    inner_width=$((width - 4))
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

status_line() {
  local symbol="$1"
  local color="$2"
  shift 2
  printf '  %s%s%s %s\n' "$color" "$symbol" "$NC" "$*"
}

ok() { status_line "✓" "$GREEN" "$1"; }
info() { status_line "•" "$CYAN" "$1"; }
warn() { status_line "⚠" "$YELLOW" "$1"; }
fail() { status_line "✗" "$RED" "$1"; }

is_minosvm() {
  [[ -f /opt/minosvm_venv/bin/activate ]]
}

ditto_claim_url_candidates() {
  local config_dir home_dir
  home_dir="${HOME:-/root}"
  config_dir="${DITTO_CONFIG_DIR:-${XDG_CONFIG_HOME:-$home_dir/.config}/heyditto/cli}"
  printf '%s\n' "${MINOSVM_DITTO_CLAIM_URL_FILE:-$ROOT_DIR/.minosvm-ditto-claim-url}"
  printf '%s/minos-claim-url.txt\n' "$config_dir"
  printf '%s\n' "/root/.config/heyditto/cli/minos-claim-url.txt"
}

print_ditto_claim_url() {
  local candidate claim_url

  while IFS= read -r candidate; do
    [[ -f "$candidate" ]] || continue
    claim_url="$(sed -n '1p' "$candidate" 2>/dev/null || true)"
    [[ -n "$claim_url" ]] || continue
    warn "Ditto agent claim URL:"
    printf '  %s%s%s\n' "$CYAN" "$claim_url" "$NC"
    warn "Open it yourself if the agent is not claimed yet. It is private until claimed."
    return 0
  done < <(ditto_claim_url_candidates)
}

print_ai_status() {
  local ai_marker="${MINOSVM_AI_RUNTIMES_MARKER:-/opt/minosvm-ai-runtimes.json}"
  local ditto_ready="$ROOT_DIR/.minosvm-ditto-default-ready"
  local ditto_attempted="$ROOT_DIR/.minosvm-ditto-default-attempted"

  if [[ -f "$ai_marker" ]]; then
    ok "AI tools installed: Ditto CLI, OpenClaw, and Hermes."
  elif is_minosvm; then
    warn "AI runtime marker not found; OpenClaw/Hermes may not be preinstalled in this image."
  else
    info "AI tools install on demand outside MinosVM."
  fi

  if [[ -f "$ditto_ready" ]]; then
    ok "Ditto @minos knowledge graph is configured."
  elif [[ -f "$ditto_attempted" ]]; then
    warn "Ditto @minos setup was attempted and will be retried if needed."
  elif is_minosvm; then
    info "Ditto @minos setup runs automatically before runtime setup."
  fi

  print_ditto_claim_url || true
}

print_header() {
  panel "MinosVM First Run" "Guided setup for Minos subnet 107 mining.
Start with demo mode if this is your first miner." 76
  if is_minosvm; then
    ok "Runtime detected: /opt/minosvm_venv"
  else
    warn "MinosVM runtime not detected; continuing from this repo clone."
  fi
  print_ai_status
  info "Live mining and AI assistant runtime setup are available when you are ready."
}

print_commands() {
  printf '\n%s◆%s %sUseful commands%s\n' "$CYAN" "$NC" "$BOLD" "$NC"
  rule 76
  printf '  %s%-42s%s %s\n' "$CYAN" "bash start-miner.sh --demo" "$NC" "test pipeline, no wallet/TAO"
  printf '  %s%-42s%s %s\n' "$CYAN" "bash start-miner.sh" "$NC" "live miner setup/start"
  printf '  %s%-42s%s %s\n' "$CYAN" "bash start-validator.sh" "$NC" "validator setup/start"
  printf '  %s%-42s%s %s\n' "$CYAN" "bash pm2-miner.sh" "$NC" "run miner under PM2"
  printf '  %s%-42s%s %s\n' "$CYAN" "bash start-miner.sh --setup-ai-assistant" "$NC" "enable OpenClaw/Hermes assistant runtime"
  printf '  %s%-42s%s %s\n' "$CYAN" "heyditto graphs list" "$NC" "check Ditto @minos subscription"
  printf '  %s%-42s%s %s\n' "$CYAN" "bash scripts/setup_ai_assistant.sh" "$NC" "advanced assistant setup"
  printf '\n'
  warn "Open any Ditto claim URL yourself before sharing screenshots or logs."
  warn "Enter provider keys only inside OpenClaw/Hermes/provider OAuth."
}

print_menu() {
  printf '\n%s◆%s %sWhat do you want to do?%s\n' "$CYAN" "$NC" "$BOLD" "$NC"
  printf '  %s1%s) Run demo miner first\n' "$CYAN" "$NC"
  printf '  %s2%s) Set up/start live miner\n' "$CYAN" "$NC"
  printf '  %s3%s) Enable Minos Miner AI Assistant runtime\n' "$CYAN" "$NC"
  printf '  %s4%s) Start validator\n' "$CYAN" "$NC"
  printf '  %s5%s) Show commands\n' "$CYAN" "$NC"
  printf '  %s6%s) Exit\n' "$CYAN" "$NC"
}

setup_terminal_ui

if [[ ! -t 0 || ! -t 1 ]]; then
  print_header
  print_commands
  exit 0
fi

print_header

while true; do
  print_menu
  read -r -p "Choice (1/2/3/4/5/6) [1]: " choice
  choice="${choice:-1}"

  case "$choice" in
    1)
      exec bash start-miner.sh --demo
      ;;
    2)
      exec bash start-miner.sh
      ;;
    3)
      exec bash scripts/prompt_ai_assistant.sh --prompt --default y --role minosvm --runtime-only
      ;;
    4)
      exec bash start-validator.sh
      ;;
    5)
      print_commands
      ;;
    6)
      print_commands
      exit 0
      ;;
    *)
      fail "Unknown choice."
      ;;
  esac
done
