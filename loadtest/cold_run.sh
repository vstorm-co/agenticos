#!/usr/bin/env bash
# One load run from an empty database: migrate, bootstrap an owner, start the
# stub model, the API and the worker on this host, seed the fixture, run the
# scenario, stop everything. What `.github/workflows/load.yml` runs, and what a
# before-and-after comparison on one machine runs twice.
#
# Needs Postgres (with pgvector) and Redis reachable as `backend/.env` or the
# POSTGRES_* / REDIS_* variables say, and the backend's environment synced.
#
#   LOAD_SCALE=0.5 LOAD_REPORT=/tmp/run.md loadtest/cold_run.sh
#
# LOAD_SCALE multiplies every phase's length (1 is the full six-minute run);
# LOAD_REPORT is where the markdown report goes; LOAD_DATABASE_URL, a
# Postgres DSN, adds connection saturation to it. The exit status is the
# verdict: a threshold that failed or was not measured fails the run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
PYTHON="$BACKEND/.venv/bin/python"
SCALE="${LOAD_SCALE:-1}"
REPORT="${LOAD_REPORT:-$ROOT/loadtest/results/cold-run.md}"
API_PORT="${LOAD_API_PORT:-8000}"
STUB_PORT="${LOAD_STUB_PORT:-4020}"
LOGS="${LOAD_LOGS:-$(mktemp -d)}"
BASE_URL="http://127.0.0.1:$API_PORT"
mkdir -p "$LOGS"
# The scenario offers about 108 runs a minute from one caller, and the public run
# API allows 30: left alone, two thirds of `agent_run` measure the rate limiter,
# whose refusals never enter the latency the threshold reads. The limit is a
# policy, not the capacity this suite exists to find.
export RATE_LIMIT_RUN_PER_MINUTE="${RATE_LIMIT_RUN_PER_MINUTE:-100000}"

cd "$BACKEND"
"$PYTHON" -m alembic upgrade head
"$PYTHON" -m cli.commands cmd bootstrap --org "Load test" >"$LOGS/bootstrap.log" 2>&1

pids=()
stop() {
    # A process tree, not a pid: the Prefect server and the worker start children
    # of their own. Twenty seconds to stop cleanly, then SIGKILL - uvicorn holding
    # a WebSocket open once waited the better part of an hour.
    for pid in "${pids[@]}"; do pkill -TERM -P "$pid" 2>/dev/null || true; kill "$pid" 2>/dev/null || true; done
    for _ in $(seq 1 20); do
        alive=0
        for pid in "${pids[@]}"; do kill -0 "$pid" 2>/dev/null && alive=1; done
        [[ $alive == 0 ]] && break
        sleep 1
    done
    for pid in "${pids[@]}"; do pkill -KILL -P "$pid" 2>/dev/null || true; kill -9 "$pid" 2>/dev/null || true; done
    wait 2>/dev/null || true
}
trap stop EXIT

"$PYTHON" ../loadtest/stub_model.py --port "$STUB_PORT" >"$LOGS/stub.log" 2>&1 &
pids+=($!)
# The uvicorn process itself, not a wrapper, so the run samples the API's CPU and memory.
"$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" >"$LOGS/api.log" 2>&1 &
API_PID=$!
pids+=("$API_PID")
"$PYTHON" -m app.worker >"$LOGS/worker.log" 2>&1 &
pids+=($!)

for _ in $(seq 1 120); do
    if curl -fsS "$BASE_URL/api/v1/health" >/dev/null 2>&1; then break; fi
    sleep 1
done
curl -fsS "$BASE_URL/api/v1/health" >/dev/null

seed_started=$(date +%s)
"$PYTHON" ../loadtest/seed.py --base-url "$BASE_URL" --stub-url "http://127.0.0.1:$STUB_PORT"
# Upload to searchable, for the whole corpus: the seed waits until it is indexed.
echo "seeded in $(($(date +%s) - seed_started))s" >"$LOGS/seed-seconds.txt"
# A Postgres DSN, when given, adds connection saturation to the report.
db_probe=()
if [[ -n "${LOAD_DATABASE_URL:-}" ]]; then db_probe=(--database-url "$LOAD_DATABASE_URL"); fi
"$PYTHON" ../loadtest/run.py \
    --api-pid "$API_PID" \
    ${db_probe[@]+"${db_probe[@]}"} \
    --scale "$SCALE" \
    --topology "one API worker and one background worker on $(uname -sm), Postgres and Redis local, the stub model local" \
    --fail-on-breach \
    >"$REPORT"
