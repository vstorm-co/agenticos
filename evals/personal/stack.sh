#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
if [ ! -f evals/personal/.env ]; then
  printf '%s\n' 'Create evals/personal/.env from .env.example first.' >&2
  exit 1
fi
exec docker compose --project-name agenticos-personal-eval \
  --env-file evals/personal/.env -f docker-compose.yml -f evals/personal/compose.yml \
  --profile sandbox --profile artifact-render "$@"
