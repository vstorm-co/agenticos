#!/usr/bin/env bash
# Local CRC only. No SCC grants, host sockets or production data services.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
: "${KUBECONFIG:?Set KUBECONFIG to the local CRC kubeconfig}"
if [ "$(oc whoami --show-server)" != 'https://api.crc.testing:6443' ]; then
  echo 'Refusing a cluster other than local CRC api.crc.testing:6443' >&2
  exit 1
fi
for namespace in agenticos-smoke agenticos-smoke-deps; do
  if oc get namespace "$namespace" >/dev/null 2>&1; then
    echo "Refusing existing namespace $namespace" >&2
    exit 1
  fi
done
scratch=$(mktemp -d)
chmod 700 "$scratch"
api_forward=""
site_forward=""
cleanup() {
  if [ -n "$api_forward" ]; then kill "$api_forward" 2>/dev/null || true; fi
  if [ -n "$site_forward" ]; then kill "$site_forward" 2>/dev/null || true; fi
  oc -n agenticos-smoke get pods -o wide || true
  echo "Retained validation namespaces and private artifacts at $scratch"
}
trap cleanup EXIT
oc create namespace agenticos-smoke
oc create namespace agenticos-smoke-deps
oc label namespace agenticos-smoke agenticos-smoke-deps agenticos-validation=true
openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 1 \
  -keyout "$scratch/postgres.key" -out "$scratch/postgres.crt" \
  -subj '/CN=postgres.agenticos-smoke-deps.svc.cluster.local' \
  -addext 'subjectAltName=DNS:postgres.agenticos-smoke-deps.svc.cluster.local' \
  -addext 'basicConstraints=critical,CA:TRUE' > "$scratch/certificate.log" 2>&1
oc -n agenticos-smoke-deps create secret tls postgres-tls --cert="$scratch/postgres.crt" --key="$scratch/postgres.key"
oc -n agenticos-smoke create secret generic agenticos-smoke-ca --from-file="postgres-ca.crt=$scratch/postgres.crt"
oc -n agenticos-smoke-deps create configmap model-fixture --from-file="server.py=$root/scripts/kubernetes/model_fixture.py"
python3 "$root/scripts/kubernetes/openshift_fixtures.py" | oc apply -f -
for fixture in postgres valkey minio model-fixture; do
  oc -n agenticos-smoke-deps rollout status "deployment/$fixture" --timeout=600s
done
python3 - <<'PY' | oc -n agenticos-smoke create -f -
import json
import secrets
print(json.dumps({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "agenticos-smoke"},
    "stringData": {"SECRET_KEY": secrets.token_hex(32), "API_KEY": secrets.token_hex(32),
        "VAULT_MASTER_KEY": secrets.token_hex(32), "POSTGRES_PASSWORD": "smoke-password",
        "FILE_STORAGE_S3_ACCESS_KEY": "smoke-access", "FILE_STORAGE_S3_SECRET_KEY": "smoke-secret-password"}}))
PY
image_tag=${SMOKE_IMAGE_TAG:-1.80.0}
# Keep the migration deadline about database work, not a cold registry download.
for component in backend frontend; do
  python3 - "$component" "$image_tag" <<'PYWARM' | oc -n agenticos-smoke create -f -
import json
import sys
component, tag = sys.argv[1:]
print(json.dumps({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": f"warm-{component}"},
    "spec": {"restartPolicy": "Never", "securityContext": {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
        "containers": [{"name": f"warm-{component}", "image": f"ghcr.io/vstorm-co/agenticos-{component}:{tag}",
            "command": ["sh", "-c", "exit 0"], "securityContext": {"allowPrivilegeEscalation": False,
                "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}}]}}))
PYWARM
  oc -n agenticos-smoke wait --for=jsonpath='{.status.phase}'=Succeeded "pod/warm-$component" --timeout=20m
  oc -n agenticos-smoke delete pod "warm-$component" --wait=true
done
helm upgrade --install smoke "$root/charts/agenticos" -n agenticos-smoke \
  -f "$root/scripts/kubernetes/smoke-values.yaml" -f "$root/charts/agenticos/values-openshift.yaml" \
  --set "image.tag=$image_tag" --wait --timeout 15m
oc -n agenticos-smoke get pods -o json > "$scratch/pods.json"
python3 - "$scratch/pods.json" <<'PY'
import json
from pathlib import Path
import sys
pods=json.loads(Path(sys.argv[1]).read_text())
for pod in pods['items']:
    scc=pod['metadata']['annotations'].get('openshift.io/scc','')
    assert scc.startswith('restricted-'), (pod['metadata']['name'],scc)
    for container in pod['spec']['containers']:
        assert container['securityContext']['runAsUser'] > 0
        assert container['securityContext']['readOnlyRootFilesystem'] is True
    print('PASS restricted SCC admission:',pod['metadata']['name'],scc)
PY
oc -n agenticos-smoke exec deployment/smoke-agenticos-api -- python -c 'from app.services.file_storage import build_s3_client; build_s3_client().create_bucket(Bucket="uploads")'
oc -n agenticos-smoke exec deployment/smoke-agenticos-api -- agenticos cmd bootstrap --email smoke@example.com --password smoke-password-2872 --org 'OpenShift smoke'
oc -n agenticos-smoke port-forward service/smoke-agenticos-api 18000:8000 > "$scratch/api-forward.log" 2>&1 &
api_forward=$!
oc -n agenticos-smoke port-forward service/smoke-agenticos-frontend 13000:3000 > "$scratch/site-forward.log" 2>&1 &
site_forward=$!
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:18000/api/v1/health/ready >/dev/null && curl -fsS http://127.0.0.1:13000/login >/dev/null; then break; fi
  sleep 1
done
python3 "$root/scripts/kubernetes/smoke_probe.py"
oc version
oc -n agenticos-smoke get pods -o jsonpath='{range .items[*]}{.metadata.name}{" "}{range .status.containerStatuses[*]}{.imageID}{"\n"}{end}{end}'
echo 'PASS local OpenShift restricted SCC base deployment'
