#!/usr/bin/env bash
# Set up Ditto for a Minos miner by subscribing the current Ditto account or
# Ditto agent to the public @minos knowledge graph.
#
# This script installs/uses the Ditto CLI, creates an agent account when
# needed, subscribes read-only to @minos, and runs soft verification checks. It
# never uploads Minos .env values, wallet files, miner configs, logs, presigned
# URLs, model API keys, or private validator data.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMORY_PACK_DIR="${MINOS_DITTO_MEMORY_PACK_DIR:-$ROOT_DIR/docs/ai-assistant/memory-pack}"
GRAPH_HANDLE="${MINOS_DITTO_GRAPH_HANDLE:-@minos}"
GRAPH_ALIAS="${MINOS_DITTO_GRAPH_ALIAS:-minos}"
AGENT_CALLER="${MINOS_DITTO_AGENT_CALLER:-Minos Miner Mentor}"
MINOSVM_DITTO_READY_MARKER="$ROOT_DIR/.minosvm-ditto-default-ready"
MINOSVM_DITTO_ATTEMPTED_MARKER="$ROOT_DIR/.minosvm-ditto-default-attempted"
if [[ -n "${MINOS_DITTO_SEED_FALLBACK+x}" ]]; then
  SEED_FALLBACK="$MINOS_DITTO_SEED_FALLBACK"
elif [[ -f /opt/minosvm_venv/bin/activate ]]; then
  SEED_FALLBACK="never"
else
  SEED_FALLBACK="auto"
fi
YES=false
DRY_RUN=false
VERIFY_ONLY=false
EMBEDDED="${MINOS_DITTO_EMBEDDED:-false}"
FALLBACK_SEEDED=false

RED=""
GREEN=""
YELLOW=""
CYAN=""
DIM=""
BOLD=""
NC=""
TERM_WIDTH=78
USE_TTY_UI=false

DITTO=()

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

  printf '\n%s+-%s%s%s%s%s+%s\n' \
    "$CYAN" "$BOLD" "$title_text" "$NC" "$CYAN" \
    "$(repeat_char "-" $((width - 3 - ${#title_text})))" "$NC"
  while IFS= read -r line; do
    if [[ -z "$line" ]]; then
      printf '%s|%s %-*s %s|%s\n' "$CYAN" "$NC" "$inner_width" "" "$CYAN" "$NC"
      continue
    fi
    while IFS= read -r wrapped; do
      printf '%s|%s %-*s %s|%s\n' "$CYAN" "$NC" "$inner_width" "$wrapped" "$CYAN" "$NC"
    done < <(printf '%s\n' "$line" | fold -s -w "$inner_width")
  done <<< "$body"
  printf '%s+%s+%s\n' "$CYAN" "$(repeat_char "-" $((width - 2)))" "$NC"
}

section() {
  printf '\n%s%s%s\n' "$BOLD" "$1" "$NC"
  printf '%s\n' "${DIM}$(repeat_char "-")${NC}"
}

status_line() {
  local symbol="$1"
  local color="$2"
  shift 2
  printf '  %s%s%s %s\n' "$color" "$symbol" "$NC" "$*"
}

info() { status_line "*" "$CYAN" "$1"; }
ok() { status_line "OK" "$GREEN" "$1"; }
warn() { status_line "WARN" "$YELLOW" "$1"; }
fail() { status_line "FAIL" "$RED" "$1" >&2; }

command_hint() {
  printf '  %s%s%s\n' "$DIM" "$1" "$NC"
}

is_minosvm() {
  [[ -f /opt/minosvm_venv/bin/activate ]]
}

write_minosvm_marker() {
  local path="$1"
  local status="$2"

  is_minosvm || return 0
  {
    date -u +"${status}_at_utc=%Y-%m-%dT%H:%M:%SZ"
    printf 'graph=%s\n' "$GRAPH_HANDLE"
    printf 'alias=%s\n' "$GRAPH_ALIAS"
  } > "$path"
  chmod 600 "$path" 2>/dev/null || true
}

usage() {
  cat <<'EOF'
Usage: bash scripts/setup_ditto_agent.sh [OPTIONS]

Options:
  --yes, -y              Skip confirmation prompts.
  --graph <handle>       Knowledge graph handle to subscribe to. Default: @minos.
  --alias <name>         Expected local graph alias. Default: minos.
  --agent-caller <name>  Ditto agent caller used when creating auth.
                          Default: Minos Miner Mentor.
  --verify-only          Do not subscribe; only verify current Ditto graph access.
  --seed-fallback        Seed the public memory pack into this account if graph
                         subscription/search cannot be verified.
                         Default: auto; MinosVM default: never.
  --force-seed-fallback  Save a private fallback copy even if graph setup works.
  --no-seed-fallback     Do not save local memory copies if graph setup is missing.
  --dry-run              Print planned actions without contacting Ditto.
  --help, -h             Show this help.

This installs or uses the Ditto CLI, initializes a Ditto agent if no
auth exists, subscribes read-only to the public @minos knowledge graph, and
runs search/list verification for minos-public-knowledge-graph-1.0.0. If graph
subscription or search cannot be verified, it can save a private fallback copy
from the public Minos memory pack. It does not upload miner secrets or logs.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) YES=true; shift ;;
    --graph) GRAPH_HANDLE="${2:-}"; shift 2 ;;
    --alias) GRAPH_ALIAS="${2:-}"; shift 2 ;;
    --agent-caller) AGENT_CALLER="${2:-}"; shift 2 ;;
    --verify-only) VERIFY_ONLY=true; shift ;;
    --seed-fallback) SEED_FALLBACK="auto"; shift ;;
    --force-seed-fallback) SEED_FALLBACK="always"; shift ;;
    --no-seed-fallback) SEED_FALLBACK="never"; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) fail "Unknown option: $1"; usage; exit 1 ;;
  esac
done

if [[ -z "$GRAPH_HANDLE" || "$GRAPH_HANDLE" != @* ]]; then
  fail "Invalid graph handle '$GRAPH_HANDLE'. Expected a handle like @minos."
  exit 1
fi

if [[ -z "$GRAPH_ALIAS" ]]; then
  GRAPH_ALIAS="${GRAPH_HANDLE#@}"
fi

case "$SEED_FALLBACK" in
  auto|always|never) ;;
  true|yes|1) SEED_FALLBACK="auto" ;;
  false|no|0) SEED_FALLBACK="never" ;;
  *)
    fail "Invalid MINOS_DITTO_SEED_FALLBACK='$SEED_FALLBACK'. Use auto, always, or never."
    exit 1
    ;;
esac

setup_terminal_ui

if [[ "$EMBEDDED" != "true" ]]; then
  panel "Minos Ditto Setup" "This will subscribe this Ditto account or agent to the public Minos knowledge graph.

Graph:   $GRAPH_HANDLE
Alias:   $GRAPH_ALIAS
Caller:  $AGENT_CALLER

Nothing from your Minos .env, wallet, configs, logs, provider keys, or private data is uploaded."
fi

if [[ "$YES" != "true" && "$DRY_RUN" != "true" && "$VERIFY_ONLY" != "true" ]]; then
  if [[ ! -t 0 ]]; then
    fail "Confirmation required, but stdin is not interactive."
    command_hint "Rerun with --yes, or use: bash start-miner.sh --setup-ditto"
    exit 1
  fi
  read -r -p "Continue with Ditto @minos setup? [y/N]: " answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) warn "Cancelled."; exit 0 ;;
  esac
fi

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

print_log_tail() {
  local log_file="$1"
  if [[ -f "$log_file" ]]; then
    tail -10 "$log_file" | sed 's/^/      /' >&2
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

  info "$message"
  if "$@" >"$log_file" 2>&1; then
    ok "$message"
    return 0
  fi

  fail "$message"
  print_log_tail "$log_file"
  return 1
}

ensure_ditto_cli() {
  section "Ditto CLI"

  if command -v heyditto >/dev/null 2>&1; then
    DITTO=(heyditto)
    ok "heyditto is available."
    return
  fi

  if [[ "$VERIFY_ONLY" == "true" ]]; then
    if [[ "$DRY_RUN" == "true" ]]; then
      info "Would require an existing heyditto command; verify-only will not install the CLI."
      command_hint "heyditto status --output json"
      DITTO=(heyditto)
      return
    fi
    fail "heyditto is not available; verify-only will not install the CLI."
    command_hint "Run setup later with: bash scripts/setup_ditto_agent.sh --yes"
    exit 1
  fi

  if ! command -v npm >/dev/null 2>&1; then
    fail "Node/npm is required to install the Ditto CLI automatically."
    command_hint "Run: bash install.sh"
    exit 1
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    info "Would install @heyditto/cli globally."
    command_hint "npm install -g @heyditto/cli@latest"
    DITTO=(npx -y @heyditto/cli@latest)
    return
  fi

  run_quiet "Installing Ditto CLI globally" "/tmp/minos-ditto-cli-install.log" npm_global_install_cmd "@heyditto/cli@latest"
  hash -r 2>/dev/null || true

  if command -v heyditto >/dev/null 2>&1; then
    DITTO=(heyditto)
    ok "heyditto is available."
  elif command -v npx >/dev/null 2>&1; then
    warn "heyditto is not on PATH after install; using npx fallback."
    DITTO=(npx -y @heyditto/cli@latest)
  else
    fail "Ditto CLI install finished but neither heyditto nor npx is usable."
    exit 1
  fi
}

claim_file_path() {
  local config_dir="${DITTO_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/heyditto/cli}"
  printf '%s/minos-claim-url.txt\n' "$config_dir"
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

ditto_status_ok() {
  "${DITTO[@]}" status --output json >/tmp/minos-ditto-status.json 2>/tmp/minos-ditto-status.err
}

init_ditto_account() {
  local init_json claim_url claim_file

  section "Ditto account"
  if [[ "$DRY_RUN" == "true" ]]; then
    if [[ "$VERIFY_ONLY" == "true" ]]; then
      info "Would check existing Ditto CLI auth only; verify-only will not create an account."
      command_hint "heyditto status --output json"
      return
    fi
    info "Would check Ditto CLI auth and create an agent account if needed."
    command_hint "heyditto status --output json"
    command_hint "heyditto init --name \"$AGENT_CALLER\" --subscribe \"${GRAPH_HANDLE#@}\" --json"
    return
  fi

  if ditto_status_ok; then
    ok "Ditto CLI auth found."
    return
  fi

  if [[ "$VERIFY_ONLY" == "true" ]]; then
    warn "No Ditto CLI auth found; verify-only will not create an account."
    command_hint "Run setup later with: bash scripts/setup_ditto_agent.sh --yes"
    return 1
  fi

  info "No Ditto CLI auth found. Creating a Minos Ditto agent..."
  if ! init_json="$("${DITTO[@]}" init --name "$AGENT_CALLER" --subscribe "${GRAPH_HANDLE#@}" --json 2>/tmp/minos-ditto-init.err)"; then
    warn "Ditto init with graph pre-subscription failed; trying legacy init flags."
    print_log_tail "/tmp/minos-ditto-init.err"
    if ! init_json="$("${DITTO[@]}" init --agent --agent-caller "$AGENT_CALLER" --json 2>/tmp/minos-ditto-init-legacy.err)"; then
      fail "Could not initialize Ditto auth."
      print_log_tail "/tmp/minos-ditto-init-legacy.err"
      exit 1
    fi
  fi

  claim_url="$(printf '%s' "$init_json" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(data.get("claimURI") or data.get("claimUri") or data.get("claim_uri") or data.get("claimURL") or data.get("claimUrl") or data.get("claim_url") or "")' 2>/dev/null || true)"
  if [[ -n "$claim_url" ]]; then
    claim_file="$(claim_file_path)"
    mkdir -p "$(dirname "$claim_file")"
    printf '%s\n' "$claim_url" > "$claim_file"
    chmod 600 "$claim_file" 2>/dev/null || true
    ok "Ditto agent created."
    panel "Claim Your Ditto Agent" "Open this private URL yourself now to claim the Minos Ditto agent:

$claim_url

The same URL is saved locally with private file permissions:
$claim_file

Show it locally with:
  sed -n '1p' \"$claim_file\"

This URL is sensitive until claimed. Do not paste it into public channels, screenshots, or logs."
  else
    ok "Ditto account initialized."
  fi
}

try_ditto_command() {
  local log_file="$1"
  shift

  : > "$log_file"
  if [[ "$DRY_RUN" == "true" ]]; then
    command_hint "${DITTO[*]} $*"
    return 0
  fi

  if "${DITTO[@]}" "$@" >"$log_file" 2>&1; then
    return 0
  fi

  if grep -qiE "already|exists|subscribed|duplicate" "$log_file" 2>/dev/null; then
    return 0
  fi

  return 1
}

memory_pack_version() {
  local manifest="$MEMORY_PACK_DIR/manifest.yaml"

  if [[ -f "$manifest" ]]; then
    awk -F: '/^version:[[:space:]]*/ {gsub(/^[ \t"]+|[ \t"]+$/, "", $2); print $2; exit}' "$manifest"
  else
    printf 'unknown\n'
  fi
}

fallback_marker_path() {
  local config_dir version

  config_dir="${DITTO_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/heyditto/cli}"
  version="$(memory_pack_version)"
  printf '%s/minos-public-memory-pack-%s-fallback-seeded.txt\n' "$config_dir" "$version"
}

memory_pack_seed_files() {
  local manifest="$MEMORY_PACK_DIR/manifest.yaml"

  if [[ ! -f "$manifest" ]]; then
    return 1
  fi

  python3 - "$manifest" <<'PY'
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
in_seed_order = False
for raw in manifest.read_text().splitlines():
    line = raw.rstrip()
    if line.startswith("graph_seed_order:"):
        in_seed_order = True
        continue
    if not in_seed_order:
        continue
    if line.startswith("  - "):
        print(line[4:].strip())
        continue
    if line and not line.startswith(" "):
        break
PY
}

save_memory_pack_file() {
  local rel_file="$1"
  local file="$MEMORY_PACK_DIR/$rel_file"
  local version source source_context log_file content

  if [[ ! -f "$file" ]]; then
    warn "Skipping missing memory-pack file: $rel_file"
    return 1
  fi

  version="$(memory_pack_version)"
  source="minos-public-memory-pack-${version}-fallback"
  source_context="@minos fallback private cache / $rel_file"
  log_file="/tmp/minos-ditto-fallback-save-${rel_file//[^A-Za-z0-9]/_}.log"
  content="$(printf 'Minos public memory pack fallback file: %s\n\n' "$rel_file"; cat "$file")"

  if [[ "$DRY_RUN" == "true" ]]; then
    command_hint "heyditto save <public $rel_file> --source $source --source-context \"$source_context\""
    return 0
  fi

  if "${DITTO[@]}" save "$content" --source "$source" --source-context "$source_context" --output json >"$log_file" 2>&1; then
    ok "Seeded fallback memory: $rel_file"
    return 0
  fi

  warn "Could not seed fallback memory: $rel_file"
  print_log_tail "$log_file"
  return 1
}

seed_memory_pack_fallback() {
  local reason="$1"
  local marker rel_file failed=false seeded_count=0

  if [[ "$VERIFY_ONLY" == "true" ]]; then
    warn "Verify-only mode; not saving local memory copies."
    return 1
  fi

  if [[ "$SEED_FALLBACK" == "never" ]]; then
    warn "Fallback memory seeding is disabled."
    return 1
  fi

  if [[ ! -d "$MEMORY_PACK_DIR" ]]; then
    warn "No local Minos memory pack found for fallback seeding."
    command_hint "$MEMORY_PACK_DIR"
    return 1
  fi

  marker="$(fallback_marker_path)"
  if [[ -f "$marker" && "$SEED_FALLBACK" != "always" ]]; then
    ok "Private fallback memory pack was already saved."
    command_hint "$marker"
    FALLBACK_SEEDED=true
    return 0
  fi

  section "Private fallback memory setup"
  warn "$reason"
  info "Saving the public Minos memory pack into this Ditto account as a private fallback."
  command_hint "This is a local cache only; the preferred source remains the public $GRAPH_HANDLE graph."

  if [[ "$DRY_RUN" == "true" ]]; then
    memory_pack_seed_files | while IFS= read -r rel_file; do
      [[ -n "$rel_file" ]] && save_memory_pack_file "$rel_file"
    done
    return 0
  fi

  while IFS= read -r rel_file; do
    [[ -n "$rel_file" ]] || continue
    if save_memory_pack_file "$rel_file"; then
      seeded_count=$((seeded_count + 1))
    else
      failed=true
    fi
  done < <(memory_pack_seed_files)

  if (( seeded_count == 0 )); then
    warn "No fallback memory-pack files were seeded."
    return 1
  fi

  mkdir -p "$(dirname "$marker")"
  {
    date -u +"seeded_at_utc=%Y-%m-%dT%H:%M:%SZ"
    printf 'source=%s\n' "$MEMORY_PACK_DIR"
    printf 'version=%s\n' "$(memory_pack_version)"
    printf 'reason=%s\n' "$reason"
    printf 'files_seeded=%s\n' "$seeded_count"
  } > "$marker"
  chmod 600 "$marker" 2>/dev/null || true
  FALLBACK_SEEDED=true

  if [[ "$failed" == "true" ]]; then
    warn "Fallback memory seeding completed with some skipped files."
  else
    ok "Private fallback memory pack saved."
  fi
  command_hint "$marker"
  return 0
}

subscribe_graph() {
  local log_base="/tmp/minos-ditto-graph-subscribe"

  section "Knowledge graph subscription"
  if [[ "$VERIFY_ONLY" == "true" ]]; then
    info "Verify-only mode; not changing graph subscriptions."
    return 0
  fi

  info "Subscribing to $GRAPH_HANDLE as a read-only public knowledge graph."
  if [[ "$DRY_RUN" == "true" ]]; then
    command_hint "heyditto graphs add $GRAPH_HANDLE"
    command_hint "heyditto graphs list"
    return 0
  fi

  if try_ditto_command "${log_base}-graphs-add-json.log" graphs add "$GRAPH_HANDLE" --output json; then
    ok "Subscribed to $GRAPH_HANDLE."
    return 0
  fi
  if try_ditto_command "${log_base}-graphs-add.log" graphs add "$GRAPH_HANDLE"; then
    ok "Subscribed to $GRAPH_HANDLE."
    return 0
  fi
  if try_ditto_command "${log_base}-graphs-subscribe.log" graphs subscribe "$GRAPH_HANDLE"; then
    ok "Subscribed to $GRAPH_HANDLE."
    return 0
  fi
  if try_ditto_command "${log_base}-knowledge-graphs-add.log" knowledge-graphs add "$GRAPH_HANDLE"; then
    ok "Subscribed to $GRAPH_HANDLE."
    return 0
  fi
  if try_ditto_command "${log_base}-subscribe-dash.log" subscribe-knowledge-graph "$GRAPH_HANDLE"; then
    ok "Subscribed to $GRAPH_HANDLE."
    return 0
  fi
  if try_ditto_command "${log_base}-subscribe-underscore.log" subscribe_knowledge_graph "$GRAPH_HANDLE"; then
    ok "Subscribed to $GRAPH_HANDLE."
    return 0
  fi

  fail "Could not subscribe to $GRAPH_HANDLE with this Ditto CLI."
  warn "Graph subscription failed for this CLI/account."
  command_hint "Expected command: heyditto graphs add $GRAPH_HANDLE"
  command_hint "Then verify: heyditto graphs list"
  command_hint "Last error:"
  print_log_tail "${log_base}-graphs-add-json.log"
  return 1
}

verify_graph_list() {
  local log_base="/tmp/minos-ditto-graph-list"
  local log_file spec

  section "Verification"

  if [[ "$DRY_RUN" == "true" ]]; then
    info "Would list subscribed graphs and search Minos topics."
    command_hint "heyditto graphs list"
    command_hint "heyditto search \"Minos PM2 online but 0 weight\""
    return 0
  fi

  for spec in \
    "graphs list --output json" \
    "graphs list" \
    "graph list" \
    "knowledge-graphs list" \
    "list-knowledge-graph-subscriptions" \
    "list_knowledge_graph_subscriptions"
  do
    log_file="${log_base}-${spec//[^A-Za-z0-9]/_}.log"
    # shellcheck disable=SC2206
    args=( $spec )
    if "${DITTO[@]}" "${args[@]}" >"$log_file" 2>&1; then
      if grep -qiE "(@minos|\"minos\"|[^A-Za-z]minos[^A-Za-z])" "$log_file"; then
        ok "Graph list shows $GRAPH_HANDLE or alias '$GRAPH_ALIAS'."
      else
        warn "Graph list command worked, but $GRAPH_HANDLE was not obvious in output."
        command_hint "Check manually: ${DITTO[*]} ${args[*]}"
      fi
      return 0
    fi
  done

  warn "Could not list graph subscriptions with this Ditto CLI."
  command_hint "Expected command: heyditto graphs list"
  return 0
}

verify_search() {
  local query log_file
  local found=false

  if [[ "$DRY_RUN" == "true" ]]; then
    return 0
  fi

  for query in \
    "Minos PM2 online but 0 weight" \
    "Minos demo mode before live tuning" \
    "Minos public endpoint latest finalized leaderboard"
  do
    log_file="/tmp/minos-ditto-search-${query//[^A-Za-z0-9]/_}.log"
    if "${DITTO[@]}" search "$query" --output json >"$log_file" 2>&1 || "${DITTO[@]}" search "$query" >"$log_file" 2>&1; then
      if grep -qiE "subscribed_graph:minos-public-knowledge-graph-1\.0\.0|@minos / Minos SN107 -" "$log_file"; then
        ok "Search returned @minos 1.0.0 results for: $query"
        found=true
        break
      elif grep -qiE "Minos|PM2|demo|leaderboard|weight|score|variant" "$log_file"; then
        warn "Search returned Minos-looking results without clear @minos 1.0.0 source for: $query"
      fi
    fi
  done

  if [[ "$found" != "true" ]]; then
    warn "Plain Ditto search did not clearly return @minos 1.0.0 results yet."
    command_hint "This can be an indexing/CLI limitation; graph subscription may still be present."
    command_hint "Try later: heyditto search \"Minos PM2 online but 0 weight\""
    return 1
  fi

  return 0
}

main() {
  local subscribed=false
  local search_ok=false

  if [[ "$DRY_RUN" != "true" && "$VERIFY_ONLY" != "true" ]]; then
    write_minosvm_marker "$MINOSVM_DITTO_ATTEMPTED_MARKER" "attempted"
  fi

  ensure_ditto_cli
  init_ditto_account

  if subscribe_graph; then
    subscribed=true
  else
    warn "Continuing with private fallback memory setup."
    seed_memory_pack_fallback "Could not subscribe to $GRAPH_HANDLE with this Ditto CLI." || true
  fi

  verify_graph_list || true
  if verify_search; then
    search_ok=true
  elif [[ "$FALLBACK_SEEDED" != "true" ]]; then
    seed_memory_pack_fallback "Plain Ditto search did not clearly retrieve $GRAPH_HANDLE after setup." || true
    verify_search || true
  fi

  if [[ "$SEED_FALLBACK" == "always" && "$FALLBACK_SEEDED" != "true" ]]; then
    seed_memory_pack_fallback "Fallback seeding was explicitly requested." || true
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    if [[ "$VERIFY_ONLY" == "true" ]]; then
      panel "Verify-Only Dry Run Complete" "No changes were made. A real verify-only run will use existing Ditto CLI auth, check graph subscriptions, and run search verification without installing, initializing, or subscribing."
    else
      if [[ "$SEED_FALLBACK" == "never" ]]; then
        panel "Dry Run Complete" "No changes were made. The real setup will install Ditto CLI, initialize auth if needed, subscribe to $GRAPH_HANDLE, and run verification. Private fallback memory setup is disabled."
      else
        panel "Dry Run Complete" "No changes were made. The real setup will install Ditto CLI, initialize auth if needed, subscribe to $GRAPH_HANDLE, run verification, and save a private fallback copy only if needed or explicitly requested."
      fi
    fi
  else
    if [[ "$subscribed" != "true" && "$FALLBACK_SEEDED" != "true" ]]; then
      panel "Ditto @minos Setup Incomplete" "Ditto CLI auth is present, but neither the public graph subscription nor the private fallback memory setup completed.

Retry graph setup:
  heyditto graphs add $GRAPH_HANDLE"
      exit 1
    fi

    if [[ "$subscribed" == "true" && "$search_ok" == "true" ]]; then
      write_minosvm_marker "$MINOSVM_DITTO_READY_MARKER" "ready"
      rm -f "$MINOSVM_DITTO_ATTEMPTED_MARKER" 2>/dev/null || true
      panel "Ditto @minos Setup Complete" "Ditto is configured for Minos public knowledge.

Graph: $GRAPH_HANDLE

Try asking:
  PM2 says my Minos miner is online but I have 0 weight. What should I check?"
    elif [[ "$FALLBACK_SEEDED" == "true" ]]; then
      panel "Ditto Minos Fallback Ready" "Ditto could not prove plain search against the public $GRAPH_HANDLE 1.0.0 graph yet, so the public Minos memory pack was also saved into this Ditto account as a private fallback copy.

Graph: $GRAPH_HANDLE
Fallback: private local Ditto memories

Try asking:
  PM2 says my Minos miner is online but I have 0 weight. What should I check?"
    else
      panel "Ditto @minos Setup Needs Verification" "Ditto graph subscription may be present, but setup could not verify search results from minos-public-knowledge-graph-1.0.0.

Graph: $GRAPH_HANDLE

Retry:
  heyditto graphs add $GRAPH_HANDLE
  heyditto search \"Minos PM2 online but 0 weight\""
      exit 1
    fi
  fi
}

main
