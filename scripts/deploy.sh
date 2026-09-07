#!/usr/bin/env bash
#
# Deploy one commit onto a server that already runs this stack.
#
#   remote=$(ssh <host> 'mktemp -t agenticos-deploy.XXXXXX')
#   ssh <host> "cat > $remote" < scripts/deploy.sh
#   ssh <host> "trap 'rm -f $remote' EXIT; bash $remote <sha>"
#
# Copied to the server rather than run from its checkout: the checkout there is
# only the build context, and the procedure travels with whoever is running it.
# Deliberately **not** taken from the commit being deployed - a rollback to a
# commit older than this file would then have no script to run, which is the one
# moment it is needed most.
#
# Copied and *then* run, rather than piped into `bash -s`, and that is not a
# style preference. Under `bash -s` the script is its own standard input, so the
# first command that reads stdin consumes the rest of it: `docker compose exec`
# forwards stdin to the container even with `-T`, so the migration swallowed
# everything below it, bash reached EOF, and the script exited 0 having never
# built the frontend or waited for anything (#1488).
#
# It takes a **commit**, not a branch. Two pushes can land while an approval is
# pending, and `git pull` on the server would then deploy whichever one won the
# race rather than the one somebody approved.
#
# To roll back, run it again with the previous sha. There is nothing else to
# undo: the images are rebuilt from the tree, and a migration that has run stays
# run - which is why a rollback across one is a decision rather than a command.
#
# Not zero-downtime. Compose recreates the containers it rebuilt, so the API and
# the site are unavailable for the few seconds that takes. Worth knowing before
# scheduling a deploy in the middle of somebody's conversation; not worth a blue
# environment for a deployment this size.
set -euo pipefail

SHA="${1:?usage: deploy.sh <commit-sha>}"
APP_DIR="${APP_DIR:-/opt/agenticos}"
COMPOSE_ENV="${APP_DIR}/backend/.env"
# The frontend is a project of its own, or compose - which names a project after
# the directory - reports the backend's containers as orphans of the frontend
# stack, and suggests the flag that would remove them. Matches the Makefile.
FRONTEND_PROJECT="agenticos-frontend"

say() { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }

cd "$APP_DIR"
test -f "$COMPOSE_ENV" || { echo "missing $COMPOSE_ENV" >&2; exit 1; }

# Which reverse proxy this host was set up with, read from the host rather than
# assumed. Hard-coding the Traefik overlays meant an Nginx host was silently
# converted on its next deploy - and since the overlay declares
# `traefik_webgateway` external, on a host that never created it compose fails
# outright, which is the better of the two outcomes.
PROXY="$(sed -n 's/^PROXY=//p' "$COMPOSE_ENV" | tail -1)"
case "${PROXY:-nginx}" in
  traefik)
    BACKEND=(-f docker-compose-prod.yml -f docker-compose-prod.traefik.yml)
    FRONTEND=(-p "$FRONTEND_PROJECT" -f docker-compose-prod.frontend.yml -f docker-compose-prod.frontend.traefik.yml)
    ;;
  nginx|"")
    BACKEND=(-f docker-compose-prod.yml)
    FRONTEND=(-p "$FRONTEND_PROJECT" -f docker-compose-prod.frontend.yml)
    ;;
  *)
    echo "PROXY=$PROXY in $COMPOSE_ENV is not one of: traefik, nginx" >&2
    exit 1
    ;;
esac

# The sandbox service is behind a compose profile, so it is opt-in - and a
# profile compose is not told about is a service compose treats as nothing to do
# with this project. It does not merely leave it alone: `up -d` on the same
# project without the profile stops it. So a host that started the sandbox by
# hand had it taken away by its next deploy, silently, and an agent's code
# execution stopped working for reasons nowhere near the deploy that
# caused it (#1506).
#
# Read from the host, the same way `PROXY` is: `SANDBOXD_TOKEN` is what the
# service refuses to start without, so its presence in `backend/.env` is this
# host saying it runs one.
PROFILES=()
if grep -qE '^SANDBOXD_TOKEN=.' "$COMPOSE_ENV"; then
  PROFILES=(--profile sandbox)
fi

say "Fetching $SHA"
git fetch --prune --quiet origin
git checkout --quiet --detach "$SHA"
git --no-pager log --oneline -1

# `< /dev/null` on every compose call, so this stays correct even when somebody
# pipes the script into `bash -s` anyway: nothing in here has any business
# reading standard input, and one that does silently truncates the deploy (#1488).
compose() { docker compose --env-file "$COMPOSE_ENV" "$@" < /dev/null; }

# The API first, and its migrations before the frontend: a frontend serving a
# schema the backend has not migrated to yet is the window this ordering closes.
say "Building and starting the API"
compose "${BACKEND[@]}" "${PROFILES[@]+"${PROFILES[@]}"}" up -d --build

say "Migrating"
compose "${BACKEND[@]}" exec -T app agenticos db upgrade

say "Building and starting the frontend"
compose "${FRONTEND[@]}" up -d --build

# A deploy that finished is not a deploy that works. Compose returns as soon as
# the containers are started, so without this a broken build is discovered by
# whoever opens the site next.
say "Waiting for health"
for name in agenticos_backend agenticos_frontend; do
  for attempt in $(seq 1 60); do
    status=$(docker inspect -f '{{.State.Health.Status}}' "$name" 2>/dev/null || echo missing)
    case "$status" in
      healthy) echo "  $name: healthy"; break ;;
      unhealthy) echo "  $name: unhealthy" >&2; docker logs --tail 50 "$name" >&2; exit 1 ;;
    esac
    if [ "$attempt" -eq 60 ]; then
      echo "  $name: still $status after 120s" >&2
      docker logs --tail 50 "$name" >&2
      exit 1
    fi
    sleep 2
  done
done

# Only the layers nothing references. `image prune -a` would take the base images
# every build starts from, and turn a two-minute deploy into a ten-minute one.
say "Reclaiming space"
docker image prune -f >/dev/null
df -h / | tail -1

say "Deployed $(git rev-parse --short HEAD)"
