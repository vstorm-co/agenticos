#!/usr/bin/env bash
# Disposable cluster only. Never uses the operator's current kube context.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cluster=${SMOKE_CLUSTER:-agenticos-smoke}
case "$cluster" in agenticos-*) ;; *) echo 'SMOKE_CLUSTER must start with agenticos-' >&2; exit 1 ;; esac
if kind get clusters 2>/dev/null | grep -Fxq "$cluster"; then
  echo "Refusing to replace existing cluster $cluster" >&2
  exit 1
fi
scratch=$(mktemp -d)
export KUBECONFIG="$scratch/kubeconfig"
api_forward=""
site_forward=""
cleanup() {
  if [ -n "$api_forward" ]; then kill "$api_forward" 2>/dev/null || true; fi
  if [ -n "$site_forward" ]; then kill "$site_forward" 2>/dev/null || true; fi
  kubectl -n agenticos-smoke get pods -o wide || true
  kubectl -n agenticos-smoke logs -l app.kubernetes.io/instance=smoke --all-containers --prefix --tail=60 || true
  if [ "${SMOKE_KEEP_CLUSTER:-false}" = true ]; then
    echo "Retained cluster $cluster and kubeconfig $KUBECONFIG"
  else
    kind delete cluster --name "$cluster"
    rm -rf "$scratch"
  fi
}
trap cleanup EXIT
kind create cluster --name "$cluster" --image kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5 --wait 180s
# Imported local images need this policy; a nonempty array also supports Bash 3.
image_options=(--set image.pullPolicy=IfNotPresent)
if [ -n "${SMOKE_BACKEND_IMAGE:-}" ]; then
  kind load docker-image --name "$cluster" "$SMOKE_BACKEND_IMAGE"
  image_options+=(--set "image.backend=${SMOKE_BACKEND_IMAGE%:*}" --set "image.backendTag=${SMOKE_BACKEND_IMAGE##*:}")
fi
if [ -n "${SMOKE_FRONTEND_TAG:-}" ]; then image_options+=(--set "image.frontendTag=$SMOKE_FRONTEND_TAG"); fi
kubectl apply -f "$root/scripts/kubernetes/fixtures.json"
# A real TLS database exercises CA mounts in migrations and both backend roles.
openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 1 \
  -keyout "$scratch/postgres.key" -out "$scratch/postgres.crt" \
  -subj '/CN=postgres.agenticos-smoke-deps.svc.cluster.local' \
  -addext 'subjectAltName=DNS:postgres.agenticos-smoke-deps.svc.cluster.local' \
  -addext 'basicConstraints=critical,CA:TRUE' > "$scratch/certificate.log" 2>&1
kubectl -n agenticos-smoke-deps create secret tls postgres-tls --cert="$scratch/postgres.crt" --key="$scratch/postgres.key"
kubectl -n agenticos-smoke create secret generic agenticos-smoke-ca --from-file="postgres-ca.crt=$scratch/postgres.crt"
kubectl -n agenticos-smoke-deps create configmap model-fixture --from-file="server.py=$root/scripts/kubernetes/model_fixture.py"
for fixture in postgres valkey minio model-fixture; do
  kubectl -n agenticos-smoke-deps rollout status "deployment/$fixture" --timeout=180s
done
python3 - <<'PY' | kubectl -n agenticos-smoke create -f -
import json
import secrets
print(json.dumps({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "agenticos-smoke"},
    "stringData": {"SECRET_KEY": secrets.token_hex(32), "API_KEY": secrets.token_hex(32),
        "VAULT_MASTER_KEY": secrets.token_hex(32), "POSTGRES_PASSWORD": "smoke-password",
        "FILE_STORAGE_S3_ACCESS_KEY": "smoke-access", "FILE_STORAGE_S3_SECRET_KEY": "smoke-secret-password"}}))
PY
# Admission validates the restricted ingress policies without enabling a proxy
# in this ClusterIP fixture; enforcement remains the operator's CNI contract.
helm template smoke "$root/charts/agenticos" -n agenticos-smoke -f "$root/scripts/kubernetes/smoke-values.yaml" "${image_options[@]}" \
  --set trustedProxy.enabled=true --set trustedProxy.namespaceLabels.controller=ingress --set trustedProxy.podLabels.controller=trusted \
  | kubectl -n agenticos-smoke apply --dry-run=server -f -
helm install smoke "$root/charts/agenticos" -n agenticos-smoke -f "$root/scripts/kubernetes/smoke-values.yaml" "${image_options[@]}" --wait --timeout 15m
kubectl -n agenticos-smoke-deps exec deployment/postgres -- psql -U agenticos -d agenticos -Atc \
  "SELECT count(*) > 0 AND bool_and(ssl) FROM pg_stat_ssl JOIN pg_stat_activity USING (pid) WHERE client_addr IS NOT NULL AND usename = 'agenticos'" | grep -qx t
kubectl -n agenticos-smoke exec deployment/smoke-agenticos-worker -- python -c 'from app.core.config import settings; assert settings.WORKER_INGEST_CHILDREN == 1; assert settings.WORKER_INGEST_MEMORY_MB == 512'
kubectl -n agenticos-smoke exec deployment/smoke-agenticos-api -- python -c 'from app.services.file_storage import build_s3_client; build_s3_client().create_bucket(Bucket="uploads")'
kubectl -n agenticos-smoke exec deployment/smoke-agenticos-api -- agenticos cmd bootstrap --email smoke@example.com --password smoke-password-2872 --org 'Kubernetes smoke'
kubectl -n agenticos-smoke port-forward service/smoke-agenticos-api 18000:8000 > "$scratch/api-forward.log" 2>&1 &
api_forward=$!
kubectl -n agenticos-smoke port-forward service/smoke-agenticos-frontend 13000:3000 > "$scratch/site-forward.log" 2>&1 &
site_forward=$!
for attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:18000/api/v1/health/ready >/dev/null && curl -fsS http://127.0.0.1:13000/login >/dev/null; then break; fi
  sleep 1
done
python3 "$root/scripts/kubernetes/smoke_probe.py"
# A failed pre-upgrade migration must leave every deployed pod template intact.
kubectl -n agenticos-smoke get deployments -o json > "$scratch/before.json"
cp -R "$root/charts/agenticos" "$scratch/broken-chart"
python3 - "$scratch/broken-chart/templates/migration.yaml" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
source = path.read_text()
needle = 'command: [agenticos, db, upgrade]'
assert source.count(needle) == 1
path.write_text(source.replace(needle, 'command: [python, -c, "raise SystemExit(42)"]'))
PY
if helm upgrade smoke "$scratch/broken-chart" -n agenticos-smoke -f "$root/scripts/kubernetes/smoke-values.yaml" "${image_options[@]}" --wait --timeout 3m; then
  echo 'A failed migration was accepted' >&2
  exit 1
fi
kubectl -n agenticos-smoke get deployments -o json > "$scratch/after.json"
python3 - "$scratch/before.json" "$scratch/after.json" <<'PY'
import json
import sys
from pathlib import Path
before, after = (json.loads(Path(path).read_text()) for path in sys.argv[1:])
assert {item['metadata']['name']: item['spec'] for item in before['items']} == {item['metadata']['name']: item['spec'] for item in after['items']}
PY
helm upgrade smoke "$root/charts/agenticos" -n agenticos-smoke -f "$root/scripts/kubernetes/smoke-values.yaml" "${image_options[@]}" --wait --timeout 10m
helm rollback smoke 1 -n agenticos-smoke --wait --timeout 10m
# Exercise arbitrary UID + root group under restricted Pod Security admission.
# This is a compatibility check, not validation of an actual OpenShift cluster.
helm upgrade smoke "$root/charts/agenticos" -n agenticos-smoke -f "$root/scripts/kubernetes/smoke-values.yaml" \
  --set api.runAsUser=1000650000 --set worker.runAsUser=1000650000 --set frontend.runAsUser=1000650000 \
  --set podSecurityContext.runAsUser=1000650000 --set podSecurityContext.runAsGroup=0 --set podSecurityContext.fsGroup=1000650000 "${image_options[@]}" --wait --timeout 10m
# Forwarding tracks pods; reconnect after the UID rollout.
kill "$api_forward" "$site_forward"
kubectl -n agenticos-smoke port-forward service/smoke-agenticos-api 18000:8000 > "$scratch/api-forward.log" 2>&1 &
api_forward=$!
kubectl -n agenticos-smoke port-forward service/smoke-agenticos-frontend 13000:3000 > "$scratch/site-forward.log" 2>&1 &
site_forward=$!
for attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:18000/api/v1/health/ready >/dev/null && curl -fsS http://127.0.0.1:13000/login >/dev/null; then break; fi
  sleep 1
done
python3 "$root/scripts/kubernetes/smoke_probe.py"
kubectl version -o yaml
helm version
kubectl -n agenticos-smoke get pods -o jsonpath='{range .items[*]}{.metadata.name}{" "}{range .status.containerStatuses[*]}{.imageID}{"\n"}{end}{end}'
echo 'PASS migration refusal, upgrade, same-schema rollback and arbitrary UID smoke'
