#!/usr/bin/env bash
#
# Deploy one commit onto a server that already runs this stack.
#
#   ssh <host> 'bash -s -- <sha>' < scripts/deploy.sh
#
# Piped over stdin rather than run from the server's checkout: the checkout there
# is only the build context, and the procedure travels with whoever is running
# it. Deliberately **not** taken from the commit being deployed - a rollback to a
# commit older than this file would then have no script to run, which is the one
# moment it is needed most.
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
    FRONTEND=(-f docker-compose-prod.frontend.yml -f docker-compose-prod.frontend.traefik.yml)
    ;;
  nginx|"")
    BACKEND=(-f docker-compose-prod.yml)
    FRONTEND=(-f docker-compose-prod.frontend.yml)
    ;;
  *)
    echo "PROXY=$PROXY in $COMPOSE_ENV is not one of: traefik, nginx" >&2
    exit 1
    ;;
esac

say "Fetching $SHA"
git fetch --prune --quiet origin
git checkout --quiet --detach "$SHA"
git --no-pager log --oneline -1

compose() { docker compose --env-file "$COMPOSE_ENV" "$@"; }

# The API first, and its migrations before the frontend: a frontend serving a
# schema the backend has not migrated to yet is the window this ordering closes.
say "Building and starting the API"
compose "${BACKEND[@]}" up -d --build

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
