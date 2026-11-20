# Deploy on Kubernetes

`charts/agenticos` installs the API, worker and console from released images.
It requires external PostgreSQL with pgvector, Redis/Valkey and an existing S3
bucket. It does not install databases or provision their backups. The chart's
`appVersion` is the default image version; pin another release with `image.tag`,
or use `image.backendDigest` and `image.frontendDigest` for immutable images.

Backend images older than 1.63.0 expect shared ingestion scratch files and are
not supported by this chart.


## Kubernetes and OpenShift

Kubernetes schedules and manages containers. Red Hat OpenShift is a Kubernetes
platform with additional components and policies, including Security Context
Constraints (SCC), SELinux integration and Routes. The same chart is the starting
point for both; a successful Kubernetes test does not validate those OpenShift
components or a cloud provider's identity and storage integration.

| Deployment path | Evidence and remaining checks |
| --- | --- |
| Kubernetes with Helm | Reproducible kind smoke described below; public ingress and NetworkPolicy enforcement still need your cluster's tests |
| OpenShift with Helm | Local OpenShift 5.0.0 passed restricted-v2, Helm lifecycle, HTTPS Routes, WSS and enforcing NetworkPolicies; validate your cluster and storage separately |
| Argo CD on local OpenShift | Argo CD Core 3.6.1 passed full-sync install, migration refusal, configuration upgrade and compatible Git revert on the same database schema |
| Sandbox and OIDC | Optional integrations with separate configuration and acceptance tests below |

## Compatibility and limits

The reproducible test uses kind 0.33.0, Kubernetes 1.37.0 and Helm 4.3.1. It checks
restricted Pod Security admission, read-only root filesystems, arbitrary numeric
UIDs, migrations, sign-in, a published agent response, S3 upload, ingestion and a
durable background run. The model is a deterministic protocol fixture; the test
makes no claim about a paid provider's availability or answer quality.

**OpenShift Local has been tested** with CRC 2.65.0, OpenShift 5.0.0
(Kubernetes 1.36.5), Helm 4.3.1 and application images 1.80.0. API, worker and
console were admitted under `restricted-v2`, with namespace-assigned UIDs,
read-only roots and no `anyuid`, privileged SCC or node socket grants.
`values-openshift.yaml` leaves UID and `fsGroup` assignment to SCC. This evidence
does not cover other OpenShift releases, Azure integration or storage drivers.

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
  tag: "1.80.0"
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

## S3 credentials and bootstrap troubleshooting

S3 is the storage protocol, not a requirement to use AWS. For a compatible service
such as MinIO, set `storage.endpoint`, `storage.bucket`, `storage.region` and the
provider's `storage.pathStyle` and encryption requirements. Azure Blob Storage's
native API is not an S3 endpoint; use an S3-compatible service for this chart.

Put static credentials in the Secret named by `existingSecret`, using the exact
keys `FILE_STORAGE_S3_ACCESS_KEY` and `FILE_STORAGE_S3_SECRET_KEY`. API, worker and
migration pods load that Secret through `envFrom`. Do not put keys under `storage`
or `extraEnv`, in Git, or in a public troubleshooting comment. A workload identity
must provide a credential chain understood by the S3 client; an Azure cluster
identity alone does not supply S3 credentials.

`botocore.exceptions.NoCredentialsError` during `agenticos cmd bootstrap` means
the S3 client could not find credentials while saving a starter avatar. The database
transaction rolls back; the earlier “Created owner” line does not prove it committed.
Correct the Secret, restart API and worker to reload environment variables, wait
for readiness and rerun bootstrap. Check bucket existence, endpoint reachability,
TLS trust and write permissions separately. Never print Secret values to diagnose it.

## OpenShift installation and writable directories

Create the project, runtime Secret and service account first. Keep the release
name `agenticos` for the commands below. Apply the candidate profile before your
cluster-specific values, and keep its UID and group settings unset:

```bash
oc new-project agenticos
helm upgrade --install agenticos charts/agenticos --namespace agenticos \
  -f charts/agenticos/values-openshift.yaml -f cluster-values.yaml \
  --wait --timeout 15m
oc -n agenticos get pods
oc -n agenticos get pods -o 'custom-columns=NAME:.metadata.name,SCC:.metadata.annotations.openshift\.io/scc'
```

Verify the admitted SCC is the intended restricted policy. Do not solve permission
failures by granting `anyuid`, privileged SCCs or a writable root filesystem.
The frontend mounts writable `emptyDir` volumes at `/tmp` and `/app/.next/cache`;
backend writable mounts are declared in `templates/_helpers.tpl`. A reported
`router-cache` error needs the **exact absolute path**, image tag/digest, OpenShift
version, admitted SCC and redacted log. A cache outside these mounts is not covered
by the existing chart. Do not mount over all of `/app/.next`, which hides the built app.

With `ingress.enabled: false`, provide two HTTPS Routes to the chart's API and
frontend Services, both using the named port `http`. Set `public.siteUrl`,
`public.apiUrl` and `public.websocketUrl` to their external addresses. Configure
router timeouts, WebSockets and upload limits, plus the protected router selectors
under `trustedProxy` and an enforcing NetworkPolicy implementation. TLS termination
alone does not establish correct forwarded-client handling.

## Argo CD migration ordering

Argo CD renders Helm templates; it does not run `helm upgrade`. Its
[Helm hook mapping](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/#helm-hooks)
turns this chart's `pre-install` and `pre-upgrade` migration Job into `PreSync`;
`before-hook-creation` permits another attempt on the next sync. Provision the
namespace, Secrets and service account **before** that phase, outside this
Application or in an earlier, completed bootstrap operation.

Use a full Application sync and confirm the migration Job succeeds before any
Deployment changes. Selective sync skips hooks. Adding Argo CD hook annotations
changes Helm-hook handling; do not mix lifecycle schemes without testing the result.
Keep the Application name equal to Helm's release name unless you deliberately
configure Argo CD resource tracking to preserve this chart's instance selectors.

Reverting Git is not a database rollback. Argo CD does not implement Helm's
`pre-rollback` hook; a full sync of the older chart follows its own PreSync path.
Prove failed-migration refusal, a successful upgrade and a compatible revert using
your actual Argo CD version before enabling automatic synchronization. Do not run
Helm and Argo CD as competing owners of the same release.

For OpenShift, load the profile as an Argo CD Helm **value file**:

```yaml
helm:
  releaseName: agenticos
  valueFiles:
    - values-openshift.yaml
```

This is the `spec.source.helm` configuration for source path `charts/agenticos`;
add your nonsecret cluster settings and existing Secret references as above.
Do not rely on inline `valuesObject` nulls to remove default UIDs or `fsGroup`.
In the local test they did not reach Helm as intended; loading the profile file
fixed SCC refusal of UID/group 1000 without broadening permissions.

Local Argo CD Core 3.6.1 passed initial full sync, failed PreSync refusal with unchanged Deployment specs, a console configuration upgrade and a compatible Git revision revert on the same database schema. Its controller had write authority only in the validation namespace and used [`resource.respectRBAC: strict`](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/). It was not granted `anyuid` or privileged SCC use. This does not validate the Red Hat OpenShift GitOps operator or a database downgrade.

## OIDC and sandbox configuration

The local OIDC setup preserves the installed Helm image tags and digests for both backend and console; configuring sign-in does not select another application image.

Configure nonsecret backend OIDC settings under top-level `extraEnv`, put
`OIDC_CLIENT_SECRET` in `existingSecret`, and enable the login button separately:

```yaml
extraEnv:
  OIDC_ISSUER: https://identity.example.com/realms/company
  OIDC_CLIENT_ID: agenticos
  OIDC_REDIRECT_URI: https://api.example.com/api/v1/oauth/oidc/callback
frontend:
  extraEnv:
    OAUTH_PROVIDERS: oidc
    OIDC_DISPLAY_NAME: Company SSO
```

`frontend.extraEnv` is available from chart version `0.1.1`; older charts ignore
it. It contains public console settings, never the client secret. Chart-managed
backend and public URLs take precedence over duplicate frontend environment keys.
Register the exact callback at the identity provider. Verify the button, redirect,
callback, verified email claim, organization access, logout and the deployment's
registration restrictions. See [generic OIDC](configuration.md#single-sign-on-generic-oidc)
for provider-specific claims and settings. A passing password-login smoke does not
test SSO.

For sandbox tools, operate a separate OpenSandbox server and register its URL,
image and vault key under **Settings → Sandboxes → Connections**. The base chart
does not install it. Local OpenShift validation used server/controller/execd/gateway
1.2.1, the Kubernetes BatchSandbox provider and Secure Access. A real tool wrote a
file and the next turn reattached and read it; the connection probe exercised a
POSIX shell. This tests endpoint authentication and the restricted workload,
not gVisor, VM isolation, egress policy, browser use or rendering.

The vendor's 1.2.1 server chart exposes container port 80. For this restricted test,
`configToml` used `server.port = 8080` and
`scripts/kubernetes/opensandbox_ports.py` changed the named HTTP container port to
8080, preserving Service/probe references. Use this executable post-renderer with
Helm 3 (tested 3.22.1); Helm 4 requires a post-renderer plugin. The workload template
mounted private `emptyDir` volumes at `/workspace` and `/tmp` and left UID/group
assignment to SCC. Secure Access used the private gateway and a separate keyring
Secret. These are provider settings, not AgenticOS chart values.

**Cleanup needs the conversation deletion fix in this change.** Released 1.80.0
removed workspace references before queuing remote destruction. The candidate
handler was tested on that image: deleting the conversation removed the provider
sandbox and pod. Do not infer this fix from the image tag alone. OpenSandbox file
browsing/download through the console's workspace archive API is not implemented;
agent file tools are a separate path. See [sandbox configuration](sandbox.md).

Deletion authorizes access, locks the conversation, and checks access again before removing workspace rows. This keeps account deletion and workspace cleanup in the same parent-first lock order. Pending destruction and its post-commit handoff retain their rollback protection.

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

## Local validation and acceptance

You can test both platforms locally, but they need separate clusters. Use kind
for Kubernetes and [OpenShift Local (CRC)](https://crc.dev/docs/getting-started/)
for actual OpenShift. Installing `oc` on a kind cluster does not add SCC or Routes.
CRC supports Apple silicon for its OpenShift preset; its OKD preset does not.
The [current minimum requirements](https://crc.dev/docs/installing/) for OpenShift
are four physical CPU cores, 10.5 GB of free memory and 35 GB of disk, before extra
application capacity. Do not run both clusters together on a constrained laptop.

The Kubernetes smoke creates disposable pgvector, Valkey, MinIO and model-protocol
fixtures; it needs no AWS account or paid model key. Pin the release under test
with `SMOKE_IMAGE_TAG`, which selects both images. `SMOKE_BACKEND_IMAGE` and
`SMOKE_FRONTEND_TAG` override their respective image when testing source builds.

```bash
python3 scripts/kubernetes/test_chart.py
SMOKE_IMAGE_TAG=1.80.0 scripts/kubernetes/run-smoke.sh
```

The automated console check confirms OIDC display configuration only; it does
not contact an identity provider. The model fixture tests the run protocol, not
real model quality. The smoke uses ClusterIP port-forwarding, so it does not
validate public TLS, WebSockets through a router, CNI enforcement or Argo CD.

For OpenShift Local, install CRC from Red Hat, obtain your own pull secret, then
prepare and start the OpenShift preset on the host:

```bash
crc config set preset openshift
crc setup
crc start --cpus 6 --memory 13312 --disk-size 45 \
  --pull-secret-file /path/to/pull-secret
```

`crc setup` configures host networking/virtualization and may require administrator
access. Follow CRC's login instructions with a separate kubeconfig. Verify the
selected cluster before changing it. Prepare reachable external data services,
Secrets and the service account as above, then install with the OpenShift profile.
Do not apply the kind dependency fixtures to OpenShift as a substitute for testing
restricted-compatible dependencies. Stop the local cluster with `crc stop` when done.

Record the image digests, chart revision, cluster and Argo CD versions, admitted
SCC, commands, outcomes and redacted failure logs. Before claiming this deployment
path works, check:

- Migration completes before workloads change; an intentionally failing migration
  prevents a rollout. A compatible upgrade and revert preserve data.
- API, worker and console stay ready under the intended restricted policy;
  frontend navigation and backend uploads produce no read-only filesystem errors.
- Bootstrap, sign-in, an agent response, upload, ingestion and a durable job work.
- Both public HTTPS addresses, WebSockets, upload limits, forwarding and network
  isolation work through the actual ingress or Routes.
- OIDC completes against the chosen identity provider with the required claims
  and registration restrictions; sandbox files survive turns and cleanup succeeds.
- If using Argo CD, repeat install, failed migration, upgrade and revert through
  full syncs, rather than treating a Helm run as GitOps validation.

A local OpenShift pass is evidence for that version and configuration. Azure
identity, Azure networking, storage drivers and the user's Argo CD setup still
need validation in that environment. Report incomplete rows as untested, not passed.

### Measured local OpenShift validation

The base run passed bootstrap, sign-in, deterministic agent execution, S3 upload,
worker ingestion through pgvector and a durable background job. Helm refused a
failed migration without changing Deployment specs; upgrade and compatible
same-schema rollback passed. Verified HTTPS Routes passed console BFF sign-in,
Secure/HttpOnly cookies, server page rendering and authenticated WSS upgrade/ping.
An untrusted namespace could not connect directly to either protected service.
This does not measure real-client forwarding chains or maximum upload sizes.

Keycloak 26.8.2 completed discovery, PKCE, signed-token validation, one-use console
code exchange, organization access and logout/refresh revocation through the TLS
Routes. Unverified email, disallowed domain and invite-only registration were
refused. This is generic OIDC evidence, not a Microsoft Entra or Azure validation.
Server-rendered page checks do not reproduce the reported `router-cache` path or
replace interactive navigation through every screen.

The base run needed **6 CPUs, 13 GiB of VM memory and a 45 GB virtual disk**.
CRC's 10.5 GB minimum left migration pods unschedulable with these fixtures.
Advanced integrations were run in stages: the sandbox SDK requests 2 GiB per
workspace. Plan extra capacity and rolling-update headroom; 13 GiB is evidence
for this base fixture, not a production sizing recommendation.

After CRC starts, use Python with PyYAML, `oc`, `helm` and separate kubeconfig:

```bash
export KUBECONFIG="$HOME/.crc/machines/crc/kubeconfig"
scripts/kubernetes/run-openshift-smoke.sh
python3 scripts/kubernetes/local_integrations.py --kubeconfig "$KUBECONFIG" routes
python3 scripts/kubernetes/local_integrations.py --kubeconfig "$KUBECONFIG" oidc
```

The base runner refuses existing validation namespaces; the integration helper
requires their ownership labels and refuses a non-CRC API. It retains disposable
namespaces and private temporary artifacts for inspection. `sandbox_probe.py`
requires an independently prepared provider stack matching the configuration
above; it is not installed by the base runner. After inspection, remove only the
namespaces and provider resources you created, delete the reported temporary
certificate directory, then stop CRC. Keep your pull secret private.

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
