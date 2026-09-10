#!/usr/bin/env bash
#
# AgenticOS quickstart: from nothing to an agent you can talk to.
#
#   curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
#   ./scripts/quickstart.sh                         # from a clone: builds from source
#   ./scripts/quickstart.sh --check                 # only say what is missing
#   ./scripts/quickstart.sh --dry-run               # print the plan, run nothing
#   ./scripts/quickstart.sh --yes --provider openai --api-key sk-...
#
# It needs Docker and nothing else. Outside a clone it downloads one file -
# `docker-compose.yml`, at the latest release so the file and the `latest`
# images it pulls are the same release - into a directory of its own and pulls
# the published images (`ghcr.io/vstorm-co/agenticos-backend`, `-frontend`);
# inside a clone it uses the clone's compose files, which build the same images
# from the tree. Either way the stack, the migrations and the console are
# containers, so there is no git, make, python, uv or bun to install first
# (#1545).
#
# Written for bash 3.2, because that is what ships with macOS: no associative
# arrays, no `${var,,}`, no `mapfile`. Prompts read from /dev/tty rather than
# stdin, because stdin is this script when the thing is piped from curl.

set -euo pipefail

REPO="vstorm-co/agenticos"
INSTALL_DIR_DEFAULT="agenticos"
# `env_file: { path, required: false }` and `condition: service_completed_successfully`
# in the compose file; older plugins refuse the schema with a message that names
# neither the version nor the fix.
COMPOSE_MIN_MAJOR=2
COMPOSE_MIN_MINOR=24

# --- how this run was asked for -----------------------------------------------

ASSUME_YES=0
DRY_RUN=0
CHECK_ONLY=0
PROVIDER=""
API_KEY=""
ADMIN_EMAIL=""
ADMIN_PASSWORD=""
ORG_NAME=""
WANT_MCP=""
WANT_SANDBOX=""

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
  --mcp / --no-mcp     Mirror the public MCP registry, 5,703 servers (default: yes)
  --sandbox / --no-sandbox
                       Start the sandbox service, which gives agents a container to
                       run code in and holds the Docker socket to do it (default: yes
                       where /var/run/docker.sock exists)
  --dir PATH           Where to put docker-compose.yml and .env when not in a clone
                       (default ./agenticos)
  -h, --help           This.
EOF
}

INSTALL_DIR="$INSTALL_DIR_DEFAULT"
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
    --mcp) WANT_MCP=yes ;;
    --no-mcp) WANT_MCP=no ;;
    --sandbox) WANT_SANDBOX=yes ;;
    --no-sandbox) WANT_SANDBOX=no ;;
    --dir) INSTALL_DIR="${2:-}"; shift ;;
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
    curl:macos)    say "    xcode-select --install" ;;
    curl:*)        say "    sudo apt install curl" ;;
    *)             say "    install $1 and run this again" ;;
  esac
}

MISSING=0

# `docker compose version --short` is `2.29.1` or `v2.29.1` depending on the
# build; anything that does not parse is reported rather than assumed fine.
check_compose_version() {
  local raw major minor
  raw="$(docker compose version --short 2>/dev/null || true)"
  raw="${raw#v}"
  major="${raw%%.*}"
  minor="${raw#*.}"; minor="${minor%%.*}"
  case "$major$minor" in
    *[!0-9]*|"")
      warn "docker compose reports '$raw' - could not read its version; ${COMPOSE_MIN_MAJOR}.${COMPOSE_MIN_MINOR} or later is needed"
      return 0
      ;;
  esac
  if [ "$major" -gt "$COMPOSE_MIN_MAJOR" ] || { [ "$major" -eq "$COMPOSE_MIN_MAJOR" ] && [ "$minor" -ge "$COMPOSE_MIN_MINOR" ]; }; then
    ok "docker compose $raw"
  else
    fail "docker compose $raw is too old - ${COMPOSE_MIN_MAJOR}.${COMPOSE_MIN_MINOR} or later is needed"
    note "The compose file uses env_file options that older plugins refuse. Update Docker Desktop / OrbStack,"
    note "or on Linux install the plugin from Docker's own repository: https://docs.docker.com/compose/install/linux/"
    MISSING=$((MISSING + 1))
  fi
}

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

  need docker
  in_clone || need curl

  if command -v docker >/dev/null 2>&1; then
    if docker compose version >/dev/null 2>&1; then
      check_compose_version
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

  note "Nothing else is needed — the stack, the migrations and the console are containers."

  if [ "$MISSING" -gt 0 ]; then
    die "$MISSING thing(s) missing. Install them and run this again."
  fi
}

# --- the questions ------------------------------------------------------------

# ask <variable> <prompt> <default>
#
# The locals are prefixed because bash locals are *dynamically* scoped: a caller
# that also had `__answer` would have had this function's `eval` write into its
# own copy instead, which is how --yes silently skipped the registry sync.
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
  [ -n "$WANT_MCP" ] || ask_yes_no WANT_MCP "  Mirror the public MCP registry (5,703 servers, ~20s)?" "y"
}

# --- doing it -----------------------------------------------------------------

# A clone has the override file, which is what turns the base file into a source
# build. Checked on the files rather than on `.git`, because a tarball of the
# repository should behave the same way.
in_clone() { [ -f docker-compose.yml ] && [ -f docker-compose.override.yml ] && [ -d backend ]; }

# Where the settings live: `backend/.env` in a clone, where every other document
# in the repository says to look; `.env` beside the compose file otherwise, which
# is also the file Compose reads for `${...}` in it.
ENV_FILE=""
IN_CLONE=0
ENV_FILE_CREATED=0

# Only a compose file that is *ours* is adopted. This runs from wherever the
# reader is, and a developer's current directory often has a `docker-compose.yml`
# of some other project in it - adopting that would `up` a stranger's stack,
# append a token to its `.env`, and `exec` into a service that is not ours. The
# old script died here (`does not look like an AgenticOS clone`); this one moves
# on to `$INSTALL_DIR` instead.
ours() { grep -q 'ghcr.io/vstorm-co/agenticos-' "${1:-.}/docker-compose.yml" 2>/dev/null; }

# The compose file at the latest release, so that the file and the `latest`
# images it pulls by default are the same release - the one on `main` can be
# ahead of the last release by a rename the image does not know yet. The
# GitHub API answers without a token at a rate a person never reaches; when it
# does not answer at all (offline, a proxy), `main` is the fallback and says so.
compose_url() {
  local tag
  tag="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
    | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1)"
  # Progress goes to stderr: stdout is the URL, and this runs inside `$(...)`.
  if [ -z "$tag" ]; then
    warn "could not read the latest release from GitHub - taking docker-compose.yml from main" >&2
    tag="main"
  else
    note "latest release: $tag" >&2
  fi
  printf 'https://raw.githubusercontent.com/%s/%s/docker-compose.yml' "$REPO" "$tag"
}

obtain_compose() {
  if in_clone; then
    IN_CLONE=1
    ENV_FILE="backend/.env"
    ok "in an AgenticOS clone — the images are built from this tree"
    return 0
  fi
  step "Getting docker-compose.yml"
  # A directory this script already set up is used in place - re-running it from
  # there must not nest another install under it.
  if ours; then
    note "docker-compose.yml already here — keeping it"
  else
    if [ -f docker-compose.yml ]; then
      note "the docker-compose.yml here is another project's - installing into $INSTALL_DIR instead"
    fi
    # Decided against `$INSTALL_DIR` by path rather than after a `cd`, so that
    # --dry-run, which never changes directory, still answers for the right one.
    if ours "$INSTALL_DIR"; then
      note "docker-compose.yml already in $INSTALL_DIR — keeping it"
    elif [ -f "$INSTALL_DIR/docker-compose.yml" ]; then
      die "$INSTALL_DIR has a docker-compose.yml that is not AgenticOS's - pick another directory with --dir"
    else
      run mkdir -p "$INSTALL_DIR"
      run curl -fsSL -o "$INSTALL_DIR/docker-compose.yml" "$(compose_url)"
    fi
    if [ "$DRY_RUN" != "1" ]; then
      cd "$INSTALL_DIR"
    fi
  fi
  ENV_FILE=".env"
  ok "compose file in $(pwd)"
  note "The images come from ghcr.io/vstorm-co - pin a release with AGENTICOS_VERSION=x.y.z in .env."
}

# The env file is created by this script when there is none, mode 0600 from the
# first byte: it is about to hold the sandbox token, which is worth the Docker
# socket, and the vault key, which unwraps every provider key an organization
# stores. A file that already exists keeps its mode and its contents - this
# script appends, and only what is missing.
ensure_env_file() {
  if [ -f "$ENV_FILE" ] || [ "$ENV_FILE_CREATED" = "1" ]; then
    return 0
  fi
  ENV_FILE_CREATED=1
  run_sh "(umask 077 && : >> '$ENV_FILE')"
}

# Append `NAME=value` with a comment above it. Real argv into `printf`, so the
# value never passes through `sh -c`; under --dry-run the value is masked, since
# the plan is printed to a terminal and these are secrets.
append_env() {
  local name="$1" value="$2" comment="$3"
  if [ "$DRY_RUN" = "1" ]; then
    printf '  %s$ printf ... %s=<generated> >> %s%s\n' "$DIM" "$name" "$ENV_FILE" "$RESET"
    return 0
  fi
  printf '\n%s\n%s=%s\n' "$comment" "$name" "$value" >> "$ENV_FILE"
}

# 64 hex characters from the kernel, the same shape `scripts/server-init.sh`
# writes with `openssl rand -hex 32` - without assuming openssl is installed.
random_hex() { head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

# The one secret the stack cannot default. The sandbox service can run commands on
# this host, so an empty token would be a shared secret of "" - it refuses to
# start without one. Written once and left alone afterwards: a new token orphans
# every workspace the service is holding. `make sandbox-token` is the same logic
# for a clone, and the file it writes is the file read here.
ensure_sandbox_token() {
  if grep -q '^SANDBOXD_TOKEN=.' "$ENV_FILE" 2>/dev/null; then
    note "SANDBOXD_TOKEN already in $ENV_FILE"
    return 0
  fi
  ensure_env_file
  # Every stage reads its whole input: a `head` at the end of a pipe kills `tr`
  # with SIGPIPE, which `set -o pipefail` turns into this script exiting.
  local token
  token="$(head -c 64 /dev/urandom | base64 | LC_ALL=C tr -dc 'A-Za-z0-9' | cut -c1-43)"
  append_env SANDBOXD_TOKEN "$token" \
    "# Authorises opening a sandbox session, and a session runs commands
# on this host. Treat it like the Docker socket it sits in front of."
  ok "generated SANDBOXD_TOKEN in $ENV_FILE"
}

# The two keys the application would otherwise take from its own defaults: a
# `SECRET_KEY` that is a constant in the repository, and no `VAULT_MASTER_KEY`,
# which makes the vault seal every provider key under that constant. Generated
# only into an env file this run created. An existing file is somebody's
# configuration - and a database may already hold secrets sealed under whatever
# key it names or implies, which a new key would make unreadable - so it is
# left exactly as found.
ensure_secrets() {
  ensure_env_file
  if [ "$ENV_FILE_CREATED" != "1" ]; then
    return 0
  fi
  append_env SECRET_KEY "$(random_hex)" \
    "# Signs sessions. Generated by scripts/quickstart.sh; changing it signs everyone out."
  append_env VAULT_MASTER_KEY "$(random_hex)" \
    "# Seals every credential the vault stores. Generated by scripts/quickstart.sh.
# Back it up with the database: a dump restored beside a different key is unreadable."
  ok "generated SECRET_KEY and VAULT_MASTER_KEY in $ENV_FILE"
}

# Which optional services this run brings up. The sandbox is on wherever the
# Docker socket is, because an agent with a container to work in is most of the
# demo; a host without the socket gets everything else and a note.
PROFILES=""

decide_sandbox() {
  if [ -z "$WANT_SANDBOX" ]; then
    if [ -S /var/run/docker.sock ]; then WANT_SANDBOX=yes; else WANT_SANDBOX=no; fi
  fi
  if [ "$WANT_SANDBOX" != "yes" ]; then
    note "Sandbox off - agents get no container to run code in. --sandbox turns it on."
    return 0
  fi
  if [ ! -S /var/run/docker.sock ]; then
    die "--sandbox needs /var/run/docker.sock on this host, and there is none"
  fi
  PROFILES="--profile sandbox"
  ensure_sandbox_token
  # The group that owns the socket, which the service takes as a supplementary
  # group to reach it. 0 on Docker Desktop, where the socket is proxied.
  DOCKER_GID="$(stat -c '%g' /var/run/docker.sock 2>/dev/null || stat -f '%g' /var/run/docker.sock)"
  export DOCKER_GID
}

start_stack() {
  step "Starting Postgres, Redis, the API, the worker and the console"
  if [ "$IN_CLONE" = "1" ]; then
    note "First run builds the backend and console images from source — a few minutes."
    # `--profile console` beside the sandbox one: in a clone the console sits
    # behind it so `bun dev` on the host keeps :3000; this run wants it started.
    run_sh "docker compose $PROFILES --profile console up -d --build"
  else
    note "First run pulls about 2 GB of images."
    run_sh "docker compose $PROFILES pull --quiet"
    run_sh "docker compose $PROFILES up -d"
  fi
}

# Compose returns once the containers are *started*. The API imports the whole
# application before it answers and, on a fresh volume, waits for the migrations
# first, so the bootstrap below would race it. Its own healthcheck is the answer
# to "is it up", so read that rather than guess at a sleep.
wait_for_api() {
  [ "$DRY_RUN" != "1" ] || return 0
  step "Waiting for the API"
  local attempt status
  for attempt in $(seq 1 90); do
    status=$(docker inspect -f '{{.State.Health.Status}}' agenticos_backend 2>/dev/null || echo starting)
    case "$status" in
      healthy) ok "API answering on http://localhost:8000"; return 0 ;;
      unhealthy)
        docker compose logs --tail 40 migrate app >&2 || true
        die "the API reports unhealthy - the log above says why"
        ;;
    esac
    if [ "$attempt" -eq 90 ]; then
      docker compose logs --tail 40 migrate app >&2 || true
      die "the API is still '$status' after three minutes"
    fi
    printf '.'
    sleep 2
  done
}

bootstrap_platform() {
  step "Creating your organization, your login, a model and a first agent"
  # Real argv, not a string through `sh -c`: a password with a `$`, a space or a
  # quote in it has to reach the container as typed.
  local -a cmd
  cmd=(docker compose exec -T)
  if [ -n "$API_KEY" ]; then
    # Through the environment, not the command line: an argument is visible in
    # `ps` to every other user on the machine.
    cmd+=(-e "BOOTSTRAP_API_KEY=$API_KEY")
  fi
  cmd+=(app agenticos cmd bootstrap --email "$ADMIN_EMAIL" --password "$ADMIN_PASSWORD" --org "$ORG_NAME")
  if [ "$PROVIDER" != "none" ]; then
    cmd+=(--provider "$PROVIDER")
  fi
  run "${cmd[@]}"
}

sync_mcp() {
  [ "$WANT_MCP" = "yes" ] || return 0
  step "Mirroring the public MCP registry"
  note "5,703 servers, searchable by name in the console. Offline snapshot; --fetch refreshes it later."
  run_sh "docker compose exec -T app agenticos cmd mcp-registry-sync"
}

summary() {
  local down="docker compose down" logs="docker compose logs -f"
  if [ "$IN_CLONE" = "1" ]; then
    down="make dev-down"; logs="make dev-logs"
  fi
  cat <<EOF

${GREEN}${BOLD}Ready.${RESET}

  Console    ${BLUE}http://localhost:3000${RESET}
  Sign in    ${ADMIN_EMAIL} / ${ADMIN_PASSWORD}
  API        http://localhost:8000${DIM}  (docs at /docs)${RESET}

${BOLD}What to try first${RESET}
  1. Open the chat and ask the agent something.
  2. Knowledge bases → new collection → drop a PDF in → ask about it.
  3. MCP servers → search for a tool your company already uses.

${BOLD}Day to day${RESET}${DIM}  (from $(pwd))${RESET}
  $logs        follow the logs
  $down        stop everything, keep the data
  docker compose exec app agenticos cmd doctor
                       can this deployment actually run an agent?

EOF
  if [ "$PROVIDER" = "none" ] || [ -z "$API_KEY" ]; then
    warn "No provider key was given, so the agent cannot answer yet."
    note "Add one in the console: Vault → add a key, then Agents → your agent → Model."
  fi
}

main() {
  say ""
  say "${BOLD}AgenticOS${RESET} — build, run and govern your company's AI agents"
  note "Self-hosted, Apache-2.0. This runs entirely on this machine."

  detect_platform
  check_prerequisites
  [ "$CHECK_ONLY" = "1" ] && { say ""; ok "Everything this needs is here."; exit 0; }

  obtain_compose
  ensure_secrets
  decide_sandbox
  wizard
  start_stack
  wait_for_api
  bootstrap_platform
  sync_mcp
  summary
}

main "$@"
