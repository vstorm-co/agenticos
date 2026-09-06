#!/usr/bin/env bash
#
# Prepare a fresh host to run this stack, once.
#
#   sudo -u "$USER" bash scripts/server-init.sh
#
# It writes `backend/.env` from `backend/.env.example`, generating every secret
# the production checklist demands and asking for the four facts it cannot
# invent: the two hostnames, an address for Let's Encrypt, and the embedding key.
#
# **Why a script rather than a page of instructions.** The checklist in
# `docs/configuration.md` is nine settings whose defaults are wrong in
# production, and a deployment that gets one of them wrong is not obviously
# broken - it runs, and its vault is sealed under a key published in an example
# file. Generating them is the one part of a deployment where a human adds no
# value and a typo costs everything.
#
# It refuses to overwrite an existing `backend/.env`. Rotating a key that already
# seals stored credentials is `agenticos cmd vault-rotate`, not a new file: see
# `docs/secrets.md#operations`.
#
# Nothing here needs root. It does not install Docker, open ports or touch
# systemd - `docs/deploy.md` says what to do about those, because on a managed
# host they are usually already done and doing them twice is how a firewall ends
# up with a rule nobody remembers adding.
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE="backend/.env"
EXAMPLE="backend/.env.example"

die() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
say() { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }
ask() {
  local prompt="$1" default="${2:-}" answer
  if [ -n "$default" ]; then
    read -rp "  $prompt [$default]: " answer
    printf '%s' "${answer:-$default}"
  else
    while :; do
      read -rp "  $prompt: " answer
      [ -n "$answer" ] && break
      echo "    (required)" >&2
    done
    printf '%s' "$answer"
  fi
}

command -v docker >/dev/null || die "docker is not installed - see docs/deploy.md"
docker compose version >/dev/null 2>&1 || die "the docker compose plugin is missing"
command -v openssl >/dev/null || die "openssl is not installed"
test -f "$EXAMPLE" || die "run this from a checkout: $EXAMPLE is missing"
test -e "$ENV_FILE" && die "$ENV_FILE already exists - move it aside first, or edit it by hand"

say "Where this deployment answers"
SITE_DOMAIN=$(ask "Site hostname" "")
API_DOMAIN=$(ask "API hostname" "")
ACME_EMAIL=$(ask "Address for Let's Encrypt expiry notices" "")

say "The one key the deployment itself needs"
echo "  Every collection embeds through OpenRouter. Chat models are not set here -"
echo "  each organization stores its own provider keys in the vault."
OPENROUTER_API_KEY=$(ask "OPENROUTER_API_KEY" "")

say "Reverse proxy"
echo "  traefik - the containers carry labels an existing Traefik discovers."
echo "  nginx   - both ports on the loopback, and a proxy on the host reaches them."
while :; do
  PROXY=$(ask "Proxy" "traefik")
  case "$PROXY" in traefik|nginx) break ;; *) echo "    (traefik or nginx)" >&2 ;; esac
done

say "Sizing"
echo "  Each uvicorn worker is a separate process holding about 460 MiB. Two suits"
echo "  a team; four suits a deployment with real traffic."
UVICORN_WORKERS=$(ask "Workers" "2")

say "Generating secrets"
gen() { openssl rand -hex 32; }
SECRET_KEY=$(gen)
API_KEY=$(gen)
VAULT_MASTER_KEY=$(gen)
POSTGRES_PASSWORD=$(gen)
REDIS_PASSWORD=$(gen)
echo "  SECRET_KEY, API_KEY, VAULT_MASTER_KEY, POSTGRES_PASSWORD, REDIS_PASSWORD"

# Written with python rather than sed: several of these are hex, but a generated
# password reaching a `sed` replacement is one `&` away from being silently
# mangled, and a corrupted VAULT_MASTER_KEY is a vault nobody can open.
say "Writing $ENV_FILE"
SITE_DOMAIN="$SITE_DOMAIN" API_DOMAIN="$API_DOMAIN" ACME_EMAIL="$ACME_EMAIL" PROXY="$PROXY" \
OPENROUTER_API_KEY="$OPENROUTER_API_KEY" UVICORN_WORKERS="$UVICORN_WORKERS" \
SECRET_KEY="$SECRET_KEY" API_KEY="$API_KEY" VAULT_MASTER_KEY="$VAULT_MASTER_KEY" \
POSTGRES_PASSWORD="$POSTGRES_PASSWORD" REDIS_PASSWORD="$REDIS_PASSWORD" \
python3 - "$EXAMPLE" "$ENV_FILE" <<'PY'
import os
import sys

source, target = sys.argv[1], sys.argv[2]
site, api = os.environ["SITE_DOMAIN"], os.environ["API_DOMAIN"]

settings = {
    "ENVIRONMENT": "production",
    "DEBUG": "false",
    "SECRET_KEY": os.environ["SECRET_KEY"],
    "API_KEY": os.environ["API_KEY"],
    "VAULT_MASTER_KEY": os.environ["VAULT_MASTER_KEY"],
    "POSTGRES_PASSWORD": os.environ["POSTGRES_PASSWORD"],
    "REDIS_PASSWORD": os.environ["REDIS_PASSWORD"],
    "OPENROUTER_API_KEY": os.environ["OPENROUTER_API_KEY"],
    "FRONTEND_URL": f"https://{site}",
    "PUBLIC_BASE_URL": f"https://{api}",
    "PUBLIC_SITE_URL": f"https://{site}",
    "PUBLIC_API_URL": f"https://{api}",
    "PUBLIC_WS_URL": f"wss://{api}",
    # Only the site's own origin. A browser calls the API directly for the
    # WebSocket and for a few reads, and anything wider here is an origin
    # somebody else controls being allowed to make credentialed calls.
    "CORS_ORIGINS": f'["https://{site}"]',
    "SITE_DOMAIN": site,
    "API_DOMAIN": api,
    "ACME_EMAIL": os.environ["ACME_EMAIL"],
    "UVICORN_WORKERS": os.environ["UVICORN_WORKERS"],
    # Read by `scripts/deploy.sh` so a later deploy uses the proxy this host was
    # set up with, rather than whichever one the script happened to hard-code.
    "PROXY": os.environ["PROXY"],
    # Sent to Logfire verbatim, so without it every production trace arrives
    # labelled `development` and is filtered out of the view somebody built to
    # watch production.
    "LOGFIRE_ENVIRONMENT": "production",
    # Behind a proxy the caller's address arrives in a header, and without this
    # every login attempt is counted against the proxy's own address - so a
    # handful of failures locks the whole deployment out (0.0.368).
    "RATE_LIMIT_TRUST_FORWARDED_FOR": "true",
}

written = set()
out = []
for line in open(source):
    stripped = line.lstrip("# ").rstrip("\n")
    key = stripped.split("=", 1)[0] if "=" in stripped else ""
    if key in settings and key not in written:
        out.append(f"{key}={settings[key]}\n")
        written.add(key)
    else:
        out.append(line)

missing = [f"{k}={v}\n" for k, v in settings.items() if k not in written]
if missing:
    out.append("\n# Set by scripts/server-init.sh; absent from .env.example.\n")
    out.extend(missing)

# `os.open` with the mode, rather than `open()` then `chmod`: under the usual
# 022 umask the second leaves the file world-readable for as long as it takes to
# write five secrets into it, which on a shared host is long enough. `O_EXCL`
# also makes the "already exists" check above race-free.
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as handle:
    handle.writelines(out)
PY

say "Done"
cat <<EOF
  $ENV_FILE is written and readable only by you. It holds the key that unwraps
  every credential this deployment stores; back it up somewhere a lost disk
  cannot take with it.

  Two things it does not know about, both optional and both in that file:

    SMTP_*             invitations and password resets are emailed
    LOGFIRE_TOKEN      traces of every agent run

  Next: docs/deploy.md, from "Point the names at the host".
EOF
