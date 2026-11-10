# Deploy on Kubernetes

`charts/agenticos` installs the API, worker and console from released images.
It requires external PostgreSQL with pgvector, Redis/Valkey and an existing S3
bucket. It does not install databases or provision their backups. The chart's
`appVersion` is the default image version; pin another release with `image.tag`,
or use `image.backendDigest` and `image.frontendDigest` for immutable images.

Backend images older than 1.63.0 expect shared ingestion scratch files and are
not supported by this chart.


## Compatibility and limits

The reproducible test uses kind 0.33.0, Kubernetes 1.37.0 and Helm 4.3.1. It checks
restricted Pod Security admission, read-only root filesystems, arbitrary numeric
UIDs, migrations, sign-in, a published agent response, S3 upload, ingestion and a
durable background run. The model is a deterministic protocol fixture; the test
makes no claim about a paid provider's availability or answer quality.

**OpenShift remains unvalidated.** `values-openshift.yaml` removes fixed UIDs and
`fsGroup` so `restricted-v2` can assign the namespace's ranges. Test it on your
actual OpenShift version before adopting it. Kubernetes admission with an
arbitrary UID does not validate SCC admission, SELinux, Routes or storage drivers.
Do not grant `anyuid`, privileged SCCs or node socket access to make it start.

The base chart has no sandbox daemon, Docker socket, browser service or artifact
renderer. Container execution, computer/browser use and rendering that require
those services remain unavailable until you configure an appropriate external
service. For sandbox connections use the product's [sandbox configuration](sandbox.md)
and vault; do not mount a node's `/var/run/docker.sock` into application pods.

## Prepare external services

Create the `agenticos` database and user on a pgvector-enabled PostgreSQL server.
Allow the migration identity to create the vector extension, or have the database
administrator install it first. Give the application access to its own database,
Redis database and bucket. See [external services and connection counts](scaling.md).

Create the bucket before bootstrapping: starter agent avatars also use file
storage. Set bucket encryption according to your provider. `sse-s3` is the default;
`storage.encryption: sse-kms` also needs `storage.kmsKeyId`. A test MinIO without KMS
uses `none`; that is not an instruction to disable encryption in production.

Use your secret manager to create a Secret in the application's namespace **before
Helm runs**. It must contain independent `SECRET_KEY`, `API_KEY`,
`VAULT_MASTER_KEY` values generated with `openssl rand -hex 32`, and
`POSTGRES_PASSWORD`. Preserve these keys across upgrades. The vault key is needed
to decrypt stored tenant credentials; changing it is a [key rotation](secrets.md),
not a reinstall. Add `REDIS_PASSWORD` when required and the paired
`FILE_STORAGE_S3_ACCESS_KEY` / `FILE_STORAGE_S3_SECRET_KEY` for static S3 credentials.
Omit both S3 keys when using your provider's workload identity credential chain.

The chart references an existing service account with API token automount disabled.
For workload identity, supply its name with `serviceAccountName` and configure the
provider's projected identity token/annotations on that account. Migration hooks
use it too. Model provider keys remain organization secrets in the product vault.

For `postgres.sslMode: verify-full` (the default) or `verify-ca`, create the
`trust.existingSecret` Secret with a `postgres-ca.crt` key containing the database
CA certificate. The chart mounts it read-only in the migration, API and worker
and sets `PGSSLROOTCERT`. `trust.postgresCaKey` selects another filename. For a
private Redis CA, also include a combined public/private CA bundle and name its
key with `trust.sslCaKey`; this sets `SSL_CERT_FILE`. Keep public roots in that
bundle if model providers use public certificates. Other SDK CA settings, such as
`AWS_CA_BUNDLE`, can reference the same mount through `extraEnv`.

## Install

Use the chart from the repository tag for the release you deploy. Create an
operator-owned `cluster-values.yaml` containing configuration, not credentials:

```yaml
existingSecret: agenticos-runtime
public:
  siteUrl: https://app.example.com
  apiUrl: https://api.example.com
  websocketUrl: wss://api.example.com
postgres:
  host: postgres.internal
  database: agenticos
  user: agenticos
  sslMode: verify-full
trust:
  existingSecret: agenticos-trust
  postgresCaKey: postgres-ca.crt
redis:
  host: valkey.internal
  ssl: true
storage:
  bucket: agenticos-files
  region: eu-central-1
  # endpoint: https://s3.example.com
  # pathStyle: true
image:
  tag: "1.63.0"
trustedProxy:
  enabled: true
  namespaceLabels:
    kubernetes.io/metadata.name: ingress-system
  podLabels:
    app.kubernetes.io/name: your-ingress-controller
ingress:
  enabled: true
  className: your-ingress-class
  siteHost: app.example.com
  apiHost: api.example.com
  tls:
    - secretName: agenticos-tls
      hosts: [app.example.com, api.example.com]
```

```bash
helm lint charts/agenticos --strict -f cluster-values.yaml
helm upgrade --install agenticos charts/agenticos \
  --namespace agenticos --create-namespace -f cluster-values.yaml \
  --wait --timeout 15m
kubectl -n agenticos exec deployment/agenticos-agenticos-api -- agenticos cmd bootstrap
```

Read [Install](install.md) for bootstrap credentials and provider setup. If the
namespace does not exist yet, create it before creating the runtime Secret. Set
`imagePullSecrets` for registries requiring authentication. Do not use `kubectl
apply` on rendered chart output: it bypasses Helm's migration ordering.

Use two public hostnames, as in [the Compose deployment](deploy.md#why-two-hostnames).
The ingress controller must support WebSocket upgrades, sufficiently long idle
and request timeouts, and the upload sizes you allow. Configure those with your
controller's own annotations; the chart preserves `ingress.annotations`.
Terminate TLS with your existing certificate Secret or certificate controller.
OpenShift operators can leave ingress disabled and provide their own two Routes.

Restrict network traffic with your cluster's policies: the console reaches the API;
API and worker reach Postgres, Redis, S3 and explicitly configured providers or
external services. Do not expose database or worker ports publicly.

Public ingress requires `trustedProxy.enabled: true` and nonempty namespace/pod
label selectors for the ingress controller. Replace the example selectors with
your actual protected controller namespace and pods. This enables
`RATE_LIMIT_TRUST_FORWARDED_FOR` together with NetworkPolicies: only that controller
may enter the console; the API also accepts the release's console pods. Use a CNI
that enforces NetworkPolicy, and do not expose either service directly. Keep those
namespaces protected from untrusted pod creation. Without policy enforcement,
do not enable trusted forwarding.

Configure exactly one trusted proxy to append the real client to `X-Forwarded-For`.
The limiter reads its rightmost address, and the console preserves that header
when proxying auth. If a CDN/load balancer adds another hop, normalize the verified
client address at your edge. The ClusterIP smoke does not validate your chosen
ingress controller or CNI; verify their isolation and forwarding before exposing
production traffic. External Routes/proxies need the same trusted-proxy settings.

## Health, storage and capacity

The API probes `/api/v1/health/live` for startup/liveness and
`/api/v1/health/ready` for database/Redis readiness. Worker probes check its database
heartbeat file; console startup/readiness use `/login`, while liveness checks its
listening socket. A slow provider does not fail process liveness. Each workload
has 60 seconds to stop; the worker stops claiming jobs and drains/requeues work.

Resources are configured separately under `api.resources`, `worker.resources`,
`frontend.resources` and `migration.resources`. Size the worker for all configured
ingest children: their memory allowance is additional to its parent process.
Tune `extraEnv.WORKER_INGEST_CHILDREN` and `extraEnv.WORKER_INGEST_MEMORY_MB` together with the pod
limit. Scale with `api.replicas`, `worker.replicas` and `frontend.replicas`; account
for every process's database pool before adding replicas.

Files persist in S3; the worker downloads each ingest into its own temporary
copy. No shared filesystem or RWX claim is required. Cache/staging directories
are bounded `emptyDir` volumes. Losing them is expected; they are not backups.
A killed ingest process can leave a temporary file until its pod is replaced;
ordinary completion, parser failures and cancellation remove the worker copy.
Local-directory sync sources must be reachable from the executing worker; this
chart does not mount operator directories into pods.

## Upgrade and rollback

Back up Postgres, S3 and runtime keys before upgrading. Review release notes and
migration compatibility with both the old and new application. A pre-install or
pre-upgrade Job runs `agenticos db upgrade`; its failure prevents Helm from
changing the deployments. Failed Jobs remain for diagnosis:

```bash
kubectl -n agenticos logs job/agenticos-agenticos-migrate
helm history agenticos -n agenticos
```

Capture logs before retrying: the next hook deletes the previous hook Job. Do not
run simultaneous upgrades of one release, use `--no-hooks`, or manually start new
pods after a failed migration. A partially applied migration still needs operator
assessment; Helm cannot reverse database side effects.

Rolling upgrades require schema and queued-job compatibility while old processes
remain live. For an incompatible change, stop incoming traffic, drain active work,
scale all three deployments to zero, back up, and then upgrade in a maintenance
window. Verify readiness and a real agent run before reopening traffic.

For the first upgrade to 1.63.0 on an existing S3 deployment, drain ingestion and
replace workers before upgrading the API, or use a maintenance window. New API
processes no longer write the shared scratch copies expected by old workers.
Local file storage keeps its shared-directory contract.

`helm rollback agenticos REVISION -n agenticos --wait --timeout 15m` restores an
older application only when its migration hook accepts the current database.
It does **not** downgrade the database. If the old image does not recognize a new
revision, its pre-rollback hook refuses the rollback before replacing pods.
Restore a matching database backup and compatible objects/keys as a deliberate
recovery operation when release notes require it. `helm uninstall` removes the
application; external databases, bucket and runtime Secret remain operator-owned.

## Reproduce the test

Install Docker, kubectl 1.37.0, kind 0.33.0, Helm 4.3.1 and Python with PyYAML. From the
repository root, run `python3 scripts/kubernetes/test_chart.py`, then
`scripts/kubernetes/run-smoke.sh`. The latter creates and deletes its own kind
cluster, uses a separate kubeconfig, and refuses to replace an existing cluster.
It never uses your current Kubernetes context. It needs ports 18000/13000 free.

Before the first application release containing this change, build the source
backend and set `SMOKE_BACKEND_IMAGE=agenticos-smoke-backend:ci` and
`SMOKE_FRONTEND_TAG=1.62.8`, as the Kubernetes workflow does. The script also tests a
failed migration, successful upgrade, same-schema rollback and an arbitrary UID
rollout. Its fixture databases and S3 bucket are disposable, single-node test
services, not production database manifests. CI records tool versions and image
IDs in the run log. `SMOKE_KEEP_CLUSTER=true` retains a failed test cluster for
inspection; remove it explicitly afterwards with `kind delete cluster --name
agenticos-smoke`.
