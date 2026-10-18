#!/usr/bin/env bash
# Run one variant through one scenario on a fresh compose project.
#
#   ./run.sh <variant> <scenario> [driver args...]
#
# Variants: pgqueue pgqueue-fair celery-prefork celery-threads taskiq dramatiq saq
#           procrastinate hatchet hatchet-fair prefect-serve prefect-serve-20
#           prefect-serve-pg prefect-tasks
# Scenarios: workflow mix tenants
#
# Every run starts from nothing (`down -v`), so no backend inherits another's queue,
# and first measures cold start: the time from starting the workers to the first
# job finishing.
set -euo pipefail
cd "$(dirname "$0")"

VARIANT=$1
SCENARIO=$2
shift 2
LABEL="${VARIANT}-${SCENARIO}"
export BENCH_RUN_LABEL="$LABEL"
export BENCH_FAIR=0

case "$VARIANT" in
  pgqueue)          PROFILE=pgqueue;        BACKEND=pgqueue ;;
  pgqueue-fair)     PROFILE=pgqueue;        BACKEND=pgqueue; BENCH_FAIR=1 ;;
  celery-prefork)   PROFILE=celery-prefork; BACKEND=celery ;;
  celery-threads)   PROFILE=celery-threads; BACKEND=celery ;;
  taskiq)           PROFILE=taskiq;         BACKEND=taskiq ;;
  dramatiq)         PROFILE=dramatiq;       BACKEND=dramatiq ;;
  saq)              PROFILE=saq;            BACKEND=saq ;;
  procrastinate)    PROFILE=procrastinate;  BACKEND=procrastinate ;;
  hatchet)          PROFILE=hatchet;        BACKEND=hatchet ;;
  hatchet-fair)     PROFILE=hatchet;        BACKEND=hatchet; BENCH_FAIR=1 ;;
  prefect-serve)    PROFILE=prefect-serve;  BACKEND=prefect-serve ;;
  prefect-serve-20) PROFILE=prefect-serve;  BACKEND=prefect-serve; export BENCH_PREFECT_LIMIT=20 ;;
  prefect-serve-pg) PROFILE=prefect-serve;  BACKEND=prefect-serve
                    export PREFECT_DB_URL=postgresql+asyncpg://bench:bench@postgres:5432/prefect ;;
  prefect-tasks)    PROFILE=prefect-tasks;  BACKEND=prefect-tasks ;;
  *) echo "unknown variant $VARIANT" >&2; exit 2 ;;
esac
export BENCH_FAIR

PROFILES=(--profile "$PROFILE")
case "$PROFILE" in prefect-serve|prefect-tasks) PROFILES+=(--profile prefect) ;; esac

compose() { docker compose "${PROFILES[@]}" "$@"; }
drive() { docker compose --profile driver run --rm -T driver python -m bench.driver --backend "$BACKEND" --variant "$VARIANT" "$@"; }

compose down -v --remove-orphans >/dev/null 2>&1 || true
# Infrastructure first, and healthy, so cold start measures the workers alone.
compose up -d --wait postgres redis >/dev/null
case "$PROFILE" in
  prefect-serve|prefect-tasks) compose up -d --wait prefect-server >/dev/null ;;
  hatchet)
    compose up -d hatchet >/dev/null
    for _ in $(seq 1 90); do
      if docker compose --profile hatchet exec -T hatchet /hatchet-admin token create \
          --config /config --tenant-id 707d0855-80ab-4e1f-a156-f1c4546cbf52 >/tmp/tqbench-token 2>/dev/null; then
        break
      fi
      sleep 2
    done
    HATCHET_CLIENT_TOKEN=$(tail -1 /tmp/tqbench-token)
    export HATCHET_CLIENT_TOKEN
    ;;
esac

# The driver creates the schemas the workers expect before any worker starts.
drive --scenario setup --label "$LABEL-setup"

WORKERS=$(docker compose "${PROFILES[@]}" config --services | grep '^w-' | tr '\n' ' ')
compose up -d $WORKERS >/dev/null
drive --scenario probe --label "$LABEL-probe" --timeout 600
drive --scenario "$SCENARIO" --label "$LABEL" "$@"

compose logs --no-color > "results/$LABEL.log" 2>&1 || true
compose down -v --remove-orphans >/dev/null 2>&1 || true
