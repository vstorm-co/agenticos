#!/usr/bin/env bash
#
# AgenticOS quickstart: from nothing to an agent you can talk to.
#
#   curl -fsSL https://agenticos.sh | bash          # or the raw URL below
#   ./scripts/quickstart.sh                         # from a clone
#   ./scripts/quickstart.sh --check                 # only say what is missing
#   ./scripts/quickstart.sh --dry-run               # print the plan, run nothing
#   ./scripts/quickstart.sh --yes --provider openai --api-key sk-...
#
# Written for bash 3.2, because that is what ships with macOS: no associative
# arrays, no `${var,,}`, no `mapfile`. Prompts read from /dev/tty rather than
# stdin, because stdin is this script when the thing is piped from curl.
#
# What it needs is smaller than the README used to claim: Docker, git, make and
# python3. `uv` and `bun` are for developing AgenticOS, not for running it - the
# stack and the frontend are both containers.

set -euo pipefail

REPO_URL="https://github.com/vstorm-co/agenticos.git"
REPO_DIR_DEFAULT="agenticos"

# --- how this run was asked for -----------------------------------------------

ASSUME_YES=0
DRY_RUN=0
CHECK_ONLY=0
PROVIDER=""
API_KEY=""
ADMIN_EMAIL=""
ADMIN_PASSWORD=""
ORG_NAME=""
WANT_FRONTEND=""
WANT_MCP=""

BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; RESET=""
if [ -t 1 ] && [ "${NO_COLOR:-}" = "" ]; then
  BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m'); RED=$(printf '\033[31m')
  GREEN=$(printf '\033[32m'); YELLOW=$(printf '\033[33m'); BLUE=$(printf '\033[34m')
  RESET=$(printf '\033[0m')
fi

say()   { printf '%s\n' "$*"; }
step()  { printf '\n%s▶ %s%s\n' "$BOLD" "$*" "$RESET"; }
ok()    { printf '  %s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
warn()  { printf '  %s!%s %s\n' "$YELLOW" "$RESET" "$*"; }
fail()  { printf '  %s✗%s %s\n' "$RED" "$RESET" "$*"; }
note()  { printf '  %s%s%s\n' "$DIM" "$*" "$RESET"; }

die() { printf '\n%sStopped:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
AgenticOS quickstart

  --check              Report what is missing and stop.
  --dry-run            Print every command this would run, run none of them.
  --yes                Never prompt; use flags and defaults.
  --provider NAME      openai | anthropic | google | openrouter | none
  --api-key KEY        Provider key. Omit with --provider none to add it later.
  --email ADDRESS      Owner login (default admin@example.com)
  --password SECRET    Owner password (default admin123)
  --org NAME           Organization name (default Acme)
  --frontend / --no-frontend    Start the web console container (default: yes)
  --mcp / --no-mcp     Mirror the public MCP registry, 5,703 servers (default: yes)
  --dir PATH           Where to clone (default ./agenticos)
  -h, --help           This.
EOF
}

REPO_DIR="$REPO_DIR_DEFAULT"
while [ $# -gt 0 ]; do
  case "$1" in
    --check) CHECK_ONLY=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --provider) PROVIDER="${2:-}"; shift ;;
    --api-key) API_KEY="${2:-}"; shift ;;
    --email) ADMIN_EMAIL="${2:-}"; shift ;;
    --password) ADMIN_PASSWORD="${2:-}"; shift ;;
    --org) ORG_NAME="${2:-}"; shift ;;
    --frontend) WANT_FRONTEND=yes ;;
    --no-frontend) WANT_FRONTEND=no ;;
    --mcp) WANT_MCP=yes ;;
    --no-mcp) WANT_MCP=no ;;
    --dir) REPO_DIR="${2:-}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
  shift
done

run() {
  if [ "$DRY_RUN" = "1" ]; then
    printf '  %s$ %s%s\n' "$DIM" "$*" "$RESET"
    return 0
  fi
  "$@"
}

# `run` cannot carry a pipeline or a redirect, so anything shaped like that goes
# through here instead and is printed verbatim under --dry-run.
run_sh() {
  if [ "$DRY_RUN" = "1" ]; then
    printf '  %s$ %s%s\n' "$DIM" "$1" "$RESET"
    return 0
  fi
  sh -c "$1"
}

# --- which machine is this ----------------------------------------------------

detect_platform() {
  case "$(uname -s)" in
    Darwin) PLATFORM="macos" ;;
    Linux)
      if grep -qi microsoft /proc/version 2>/dev/null; then
        PLATFORM="wsl"
      else
        PLATFORM="linux"
      fi
      ;;
    MINGW*|MSYS*|CYGWIN*) PLATFORM="windows-shell" ;;
    *) PLATFORM="unknown" ;;
  esac
}

# What to type on this platform to get a missing thing. One place, so the advice
# cannot drift from the check that produced it.
hint_for() {
  case "$1:$PLATFORM" in
    docker:macos)  say "    brew install --cask docker   ${DIM}(or Docker Desktop / OrbStack)${RESET}" ;;
    docker:linux)  say "    curl -fsSL https://get.docker.com | sh" ;;
    docker:wsl)    say "    Install Docker Desktop on Windows and enable WSL2 integration" ;;
    make:macos)    say "    xcode-select --install" ;;
    make:linux)    say "    sudo apt install make    ${DIM}# or dnf/pacman${RESET}" ;;
    make:wsl)      say "    sudo apt install make" ;;
    git:macos)     say "    xcode-select --install" ;;
    git:linux)     say "    sudo apt install git" ;;
    git:wsl)       say "    sudo apt install git" ;;
    python3:macos) say "    brew install python3" ;;
    python3:*)     say "    sudo apt install python3" ;;
    *)             say "    install $1 and run this again" ;;
  esac
}

MISSING=0
need() {
  if command -v "$1" >/dev/null 2>&1; then
    ok "$1"
  else
    fail "$1 is missing"
    hint_for "$1"
    MISSING=$((MISSING + 1))
  fi
}

check_prerequisites() {
  step "Checking this machine"
  case "$PLATFORM" in
    macos) note "macOS" ;;
    linux) note "Linux" ;;
    wsl)   note "Windows, inside WSL2 — the supported way to run this on Windows" ;;
    windows-shell)
      fail "This is Git Bash or MSYS, not WSL2."
      note "AgenticOS runs on Windows through WSL2. Open PowerShell as administrator:"
      say  "    wsl --install"
      note "then run this script again from inside the Ubuntu shell it gives you."
      exit 1
      ;;
    *) warn "Unrecognised platform $(uname -s) — carrying on, but untested" ;;
  esac

  need git
  need make
  need python3
  need docker

  if command -v docker >/dev/null 2>&1; then
    if docker compose version >/dev/null 2>&1; then
      ok "docker compose"
    else
      fail "docker compose is missing (the v2 plugin, not docker-compose)"
      note "Docker Desktop and OrbStack both ship it; on Linux: sudo apt install docker-compose-plugin"
      MISSING=$((MISSING + 1))
    fi
    if docker info >/dev/null 2>&1; then
      ok "the Docker daemon is running"
    else
      fail "Docker is installed but not running"
      note "Start Docker Desktop (or 'sudo systemctl start docker') and run this again."
      MISSING=$((MISSING + 1))
    fi
  fi

  note "uv and bun are not needed — the stack and the console are containers."

  if [ "$MISSING" -gt 0 ]; then
    die "$MISSING thing(s) missing. Install them and run this again."
  fi
}

# --- the questions ------------------------------------------------------------

# ask <variable> <prompt> <default>
#
# The locals are prefixed because bash locals are *dynamically* scoped: a caller
# that also had `__answer` would have had this function's `eval` write into its
# own copy instead, which is how --yes silently skipped the frontend and the
# registry sync.
ask() {
  local _qs_var="$1" _qs_prompt="$2" _qs_default="$3" _qs_reply=""
  if [ "$ASSUME_YES" = "1" ]; then
    eval "$_qs_var=\"\$_qs_default\""
    return 0
  fi
  printf '  %s %s[%s]%s ' "$_qs_prompt" "$DIM" "$_qs_default" "$RESET" > /dev/tty
  IFS= read -r _qs_reply < /dev/tty || _qs_reply=""
  [ -n "$_qs_reply" ] || _qs_reply="$_qs_default"
  eval "$_qs_var=\"\$_qs_reply\""
}

ask_secret() {
  local _qs_var="$1" _qs_prompt="$2" _qs_reply=""
  if [ "$ASSUME_YES" = "1" ]; then
    eval "$_qs_var=\"\""
    return 0
  fi
  printf '  %s ' "$_qs_prompt" > /dev/tty
  stty -echo < /dev/tty 2>/dev/null || true
  IFS= read -r _qs_reply < /dev/tty || _qs_reply=""
  stty echo < /dev/tty 2>/dev/null || true
  printf '\n' > /dev/tty
  eval "$_qs_var=\"\$_qs_reply\""
}

ask_yes_no() {
  local _yn_var="$1" _yn_prompt="$2" _yn_default="$3" _yn_reply=""
  ask _yn_reply "$_yn_prompt (y/n)" "$_yn_default"
  case "$_yn_reply" in
    y|Y|yes|YES) eval "$_yn_var=yes" ;;
    *) eval "$_yn_var=no" ;;
  esac
}

wizard() {
  step "Setting it up"
  note "Enter accepts the value in brackets."

  if [ -z "$PROVIDER" ] && [ "$ASSUME_YES" = "1" ]; then
    PROVIDER="openai"
  fi

  if [ -z "$PROVIDER" ]; then
    say ""
    say "  Which model should the first agent use?"
    say "    1) OpenAI          ${DIM}gpt-4.1${RESET}"
    say "    2) Anthropic       ${DIM}claude-sonnet-4-6${RESET}"
    say "    3) Google          ${DIM}gemini-2.5-pro${RESET}"
    say "    4) OpenRouter      ${DIM}one key, many models${RESET}"
    say "    5) Decide later    ${DIM}everything is created; add a key in the console${RESET}"
    say ""
    local choice=""
    ask choice "  Pick one" "1"
    case "$choice" in
      1) PROVIDER="openai" ;;
      2) PROVIDER="anthropic" ;;
      3) PROVIDER="google" ;;
      4) PROVIDER="openrouter" ;;
      *) PROVIDER="none" ;;
    esac
  fi

  if [ "$PROVIDER" != "none" ] && [ -z "$API_KEY" ]; then
    say ""
    note "The key is stored encrypted in your own database and never printed back."
    ask_secret API_KEY "  Paste your $PROVIDER API key (Enter to skip):"
  fi

  say ""
  [ -n "$ADMIN_EMAIL" ]    || ask ADMIN_EMAIL    "  Your login email" "admin@example.com"
  [ -n "$ADMIN_PASSWORD" ] || ask ADMIN_PASSWORD "  A password" "admin123"
  [ -n "$ORG_NAME" ]       || ask ORG_NAME       "  Organization name" "Acme"

  say ""
  [ -n "$WANT_FRONTEND" ] || ask_yes_no WANT_FRONTEND "  Start the web console too?" "y"
  [ -n "$WANT_MCP" ]      || ask_yes_no WANT_MCP      "  Mirror the public MCP registry (5,703 servers, ~20s)?" "y"
}

# --- doing it -----------------------------------------------------------------

in_repo() { [ -f Makefile ] && [ -d backend ] && [ -f docker-compose.yml ]; }

obtain_repo() {
  if in_repo; then
    ok "already in an AgenticOS clone"
    return 0
  fi
  step "Getting the code"
  if [ -d "$REPO_DIR" ]; then
    note "$REPO_DIR exists — using it"
  else
    run git clone --depth 1 "$REPO_URL" "$REPO_DIR"
  fi
  if [ "$DRY_RUN" != "1" ]; then
    cd "$REPO_DIR"
    in_repo || die "$REPO_DIR does not look like an AgenticOS clone"
  fi
  ok "code in $(pwd)"
}

start_stack() {
  step "Starting Postgres, Redis, the API, the worker and the sandbox"
  note "First run builds an image, so this is the slow part — a few minutes."
  run make dev
}

bootstrap_platform() {
  step "Creating your organization, your login, a model and a first agent"
  local args="--email $ADMIN_EMAIL --password $ADMIN_PASSWORD --org \"$ORG_NAME\""
  if [ "$PROVIDER" != "none" ]; then
    args="$args --provider $PROVIDER"
  fi
  if [ -n "$API_KEY" ]; then
    # Through the environment, not the command line: an argument is visible in
    # `ps` to every other user on the machine.
    run_sh "docker compose -f docker-compose.yml exec -T -e BOOTSTRAP_API_KEY='$API_KEY' app agenticos cmd bootstrap $args"
  else
    run_sh "docker compose -f docker-compose.yml exec -T app agenticos cmd bootstrap $args"
  fi
}

sync_mcp() {
  [ "$WANT_MCP" = "yes" ] || return 0
  step "Mirroring the public MCP registry"
  note "5,703 servers, searchable by name in the console. Offline snapshot; --fetch refreshes it later."
  run_sh "docker compose -f docker-compose.yml exec -T app agenticos cmd mcp-registry-sync"
}

start_frontend() {
  [ "$WANT_FRONTEND" = "yes" ] || return 0
  step "Starting the web console"
  run make dev-frontend
}

summary() {
  local where="http://localhost:3000"
  [ "$WANT_FRONTEND" = "yes" ] || where="http://localhost:8000/docs"
  cat <<EOF

${GREEN}${BOLD}Ready.${RESET}

  Console    ${BLUE}${where}${RESET}
  Sign in    ${ADMIN_EMAIL} / ${ADMIN_PASSWORD}
  API        http://localhost:8000${DIM}  (docs at /docs)${RESET}

${BOLD}What to try first${RESET}
  1. Open the chat and ask the agent something.
  2. Knowledge bases → new collection → drop a PDF in → ask about it.
  3. MCP servers → search for a tool your company already uses.

${BOLD}Day to day${RESET}
  make dev-logs        follow the logs
  make dev-down        stop everything, keep the data
  make doctor          can this deployment actually run an agent?

EOF
  if [ "$PROVIDER" = "none" ] || [ -z "$API_KEY" ]; then
    warn "No provider key was given, so the agent cannot answer yet."
    note "Add one in the console: Vault → add a key, then Agents → your agent → Model."
  fi
}

main() {
  say ""
  say "${BOLD}AgenticOS${RESET} — the operating system for your company's AI agents"
  note "Self-hosted, Apache-2.0. This runs entirely on this machine."

  detect_platform
  check_prerequisites
  [ "$CHECK_ONLY" = "1" ] && { say ""; ok "Everything this needs is here."; exit 0; }

  obtain_repo
  wizard
  start_stack
  bootstrap_platform
  sync_mcp
  start_frontend
  summary
}

main "$@"
