#!/usr/bin/env bash
# Run platform checks against disposable services owned by this invocation.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
for tool in docker uv bun make python3; do
  command -v "$tool" >/dev/null || { echo "Missing CI tool: $tool" >&2; exit 2; }
done
[[ ! -e backend/.env ]] || { echo 'CI refuses an existing backend/.env' >&2; exit 2; }

run_id="$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
network="${CI_DOCKER_NETWORK:-t3os-ci-$run_id}"
db_name="t3os-ci-db-$run_id"
minio_name="t3os-ci-store-$run_id"
db_id=''
minio_id=''
network_id=''
created_env=false
check_log="$(mktemp)"
cleanup() {
  local status=$?
  if [[ -n "$db_id" ]]; then docker rm -f "$db_id" >/dev/null 2>&1 || true; fi
  if [[ -n "$minio_id" ]]; then docker rm -f "$minio_id" >/dev/null 2>&1 || true; fi
  if [[ -n "$network_id" ]]; then docker network rm "$network_id" >/dev/null 2>&1 || true; fi
  if [[ "$created_env" == true ]]; then rm -f backend/.env; fi
  rm -f "$check_log"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cp backend/.env.example backend/.env
created_env=true

export CI=true DIAGNOSTICS_ENABLED=false NEXT_TELEMETRY_DISABLED=1
export NODE_OPTIONS=--max-old-space-size=4096
uv sync --frozen --directory backend --dev --group docs
(cd frontend && bun install --frozen-lockfile)
if [[ -n "${CI_DOCKER_NETWORK:-}" ]]; then
  docker network inspect "$network" >/dev/null
else
  network_id="$(docker network create "$network")"
fi

db_args=(--network "$network" --name "$db_name")
minio_args=(--network "$network" --name "$minio_name")
if [[ -z "${CI_DOCKER_NETWORK:-}" ]]; then
  db_args+=(-p 127.0.0.1::5432)
  minio_args+=(-p 127.0.0.1::9000)
fi
db_id="$(docker run -d "${db_args[@]}" --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=agenticos_ci \
  pgvector/pgvector:pg16 postgres -c fsync=off -c synchronous_commit=off -c full_page_writes=off)"

# Read the repository's reviewed object-store image pin; no second version list.
minio_image="$(uv run --no-sync --directory backend python -c \
  'import pathlib,yaml; print(yaml.safe_load(pathlib.Path("../docker-compose.yml").read_text())["services"]["minio"]["image"])')"
minio_id="$(docker run -d "${minio_args[@]}" --tmpfs /data \
  -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin \
  "$minio_image" server /data --console-address :9001)"

export POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres POSTGRES_DB=agenticos_ci TEST_DB=external
export FILE_STORAGE_S3_ACCESS_KEY=minioadmin FILE_STORAGE_S3_SECRET_KEY=minioadmin
if [[ -n "${CI_DOCKER_NETWORK:-}" ]]; then
  export POSTGRES_HOST="$db_name" POSTGRES_PORT=5432
  export FILE_STORAGE_S3_ENDPOINT="http://$minio_name:9000"
else
  export POSTGRES_HOST=127.0.0.1
  POSTGRES_PORT="$(docker port "$db_id" 5432/tcp)"
  export POSTGRES_PORT="${POSTGRES_PORT##*:}"
  minio_port="$(docker port "$minio_id" 9000/tcp)"
  export FILE_STORAGE_S3_ENDPOINT="http://127.0.0.1:${minio_port##*:}"
fi
export CHECK_DB_HOST="$POSTGRES_HOST" CHECK_DB_PORT="$POSTGRES_PORT" POSTGRES_CONTAINER="$db_id"

python3 - <<'PY'
import os
import socket
import time
import urllib.error
import urllib.request

for attempt in range(60):
    try:
        with socket.create_connection((os.environ["POSTGRES_HOST"], int(os.environ["POSTGRES_PORT"])), 2):
            pass
        with urllib.request.urlopen(os.environ["FILE_STORAGE_S3_ENDPOINT"] + "/minio/health/ready", timeout=2) as response:
            if response.status != 200:
                raise OSError("Object store not ready")
        break
    except (OSError, urllib.error.URLError):
        if attempt == 59:
            raise SystemExit("Disposable CI services did not become ready")
        time.sleep(2)
PY
make ci-test-db-configure
make test-migrations
# Run the schema check explicitly as well as through make check's availability gate.
uv run --no-sync --directory backend alembic check
make check 2>&1 | tee "$check_log"
if grep -Eq 'integration skipped itself|alembic check.*was skipped' "$check_log"; then
  echo 'Required database validation was skipped' >&2
  exit 1
fi
uv run --no-sync --directory backend pytest tests/test_email_templates.py tests/test_workflow_email_send.py -q
if [[ -f emails/build.py ]]; then
  python3 emails/build.py --check
fi
