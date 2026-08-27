# Configuration Reference

All configuration is managed via environment variables, loaded from
`backend/.env` using [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

Settings are defined in `app/core/config.py` and accessed via the global
`settings` object:

```python
from app.core.config import settings

print(settings.EMBEDDING_MODEL)
print(settings.DEBUG)
```

## Getting Started

`make install` creates `backend/.env` from `backend/.env.example` when there is
none, and never touches it again — so on a fresh checkout there is nothing to
copy, and on an existing one nothing to lose.

Before anything reaches a network anybody else is on, set the values the example
ships as placeholders:

```bash
openssl rand -hex 32   # SECRET_KEY — signs every access token
openssl rand -hex 32   # VAULT_MASTER_KEY — unwraps every credential stored at rest
```

!!! danger "`SECRET_KEY` ships as a published string"

    An empty `VAULT_MASTER_KEY` falls back to it so a fresh checkout runs at all.
    Both are fine on a laptop and are the whole security of a deployment anywhere
    else. Setting `VAULT_MASTER_KEY` explicitly is also what lets stored secrets
    survive a `SECRET_KEY` rotation.

The config refuses an unset `VAULT_MASTER_KEY` outside `local`/`development`.

## Project Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `PROJECT_NAME` | `agenticos` | Display name for the project |
| `API_V1_STR` | `/api/v1` | API version prefix |
| `DEBUG` | `false` | Enable debug mode (verbose errors, auto-reload) |
| `ENVIRONMENT` | `local` | One of: `development`, `local`, `staging`, `production` |
| `TIMEZONE` | `UTC` | IANA timezone (e.g. `UTC`, `Europe/Warsaw`, `America/New_York`) |
| `MODELS_CACHE_DIR` | `./models_cache` | Directory for cached ML models |
| `MEDIA_DIR` | `./media` | Directory for uploaded files |
| `MAX_UPLOAD_SIZE_MB` | `50` | Knowledge-base document cap, and the number the whole-request ceiling below is derived from. A document at this size is chunked and embedded, not held in one piece |
| `CHAT_MAX_UPLOAD_SIZE_MB` | `10` | What may be attached in chat. Its own setting rather than the one above, because an attachment to an agent with no workspace is pasted whole into the prompt — so the two surfaces fail differently at the same size. Was a hardcoded 10 MiB no operator could raise ([#498](https://github.com/vstorm-co/agenticos/issues/498)); set the frontend's `NEXT_PUBLIC_CHAT_MAX_UPLOAD_SIZE_MB` to match, or the composer refuses a file the server would take |
| `EMBED_MAX_UPLOAD_SIZE_MB` | `5` | What a **stranger** may upload to a hosted page. A ceiling on top of `CHAT_MAX_UPLOAD_SIZE_MB`, never a way past it |
| `FILE_IO_MAX_WORKERS` | `8` | Size of the dedicated thread pool that runs blocking file work — parsing an upload and reading or writing its bytes. Kept off `asyncio`'s shared default executor, which also runs `bcrypt` and pinned-host DNS, so a burst of uploads cannot leave sign-in and outbound requests queued behind them ([#1108](https://github.com/vstorm-co/agenticos/issues/1108)). Raise it on a host that parses many uploads at once. Must be a positive integer — a `0` or negative value is refused at startup |
| `DEFAULT_ORG_MONTHLY_BUDGET_USD` | `100` | The monthly spend ceiling a **new** organization starts with, in USD, so it is not one runaway agent away from a surprise bill. Applies at creation only; existing organizations are untouched and any organization can be cleared back to no cap afterwards. Must be positive; leave **empty** to start organizations uncapped (the older opt-in posture) |

### The size of a request, as opposed to the size of a file

Every limit above is measured on bytes that have already arrived. FastAPI parses a
multipart body to resolve the `UploadFile` parameter *before* the handler runs, so
by the time one of those caps is compared against `len(data)` the body has been
spooled to a temporary file and read into memory. Behind a session that is not much
of a risk; on `POST /api/v1/embed/{key}/files`, which a stranger holding a link may
reach, it is.

So a request declaring a `Content-Length` larger than `MAX_UPLOAD_SIZE_MB` plus a
5 MiB allowance for the multipart envelope is answered **413** before its body is
read. There is no setting: it follows `MAX_UPLOAD_SIZE_MB`, because a second number
to keep in step with the first is a number that ends up below it.

**It is the cheap half of the answer, not the whole one.** `Content-Length` is set
by the caller, and a chunked request declares none at all — those are let through
and bounded by the per-route caps, which measure real bytes. A deployment that wants
the guarantee rather than the courtesy sets `client_max_body_size` (nginx) or the
equivalent on whatever terminates its connections; the compose files run uvicorn
with no such limit of its own.

## Authentication

### JWT

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | (insecure default) | JWT signing key. **Must** be changed in production. Generate with: `openssl rand -hex 32` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_MINUTES` | `10080` | Refresh token lifetime (7 days) |
| `ALGORITHM` | `HS256` | JWT signing algorithm |

Production validation: `SECRET_KEY` must be at least 32 characters and cannot
use the default value in `ENVIRONMENT=production`.

### Secret vault

Every credential the platform stores at rest — provider keys, channel bot
tokens, MCP credentials and organization secrets — is sealed by
`app/core/vault.py`, whose envelope is derived from the master key **and the
owner** (an organization, or the member a personal connection belongs to). A
ciphertext is therefore useless outside the tenant it was sealed for.

| Variable | Default | Description |
|----------|---------|-------------|
| `VAULT_MASTER_KEY` | (empty, falls back to `SECRET_KEY`) | Master key for the secret vault — shorthand for version 1 of `VAULT_MASTER_KEYS`. Required outside `local`/`development` (unless the map below is set), so a staging vault cannot boot sealed under the published `SECRET_KEY` default. Generate with: `openssl rand -hex 32` |
| `VAULT_MASTER_KEYS` | `{}` | Every master key still in use, by version, as JSON — `{"1": "<old>", "2": "<new>"}`. The highest version seals new secrets; older ones keep existing rows readable until `agenticos cmd vault-rotate` re-wraps them. When set it is the whole truth: `VAULT_MASTER_KEY` must then be empty. See [Secrets](secrets.md#operations) |

### API Key

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | `change-me-in-production` | Shared API key for programmatic access |
| `API_KEY_HEADER` | `X-API-Key` | HTTP header name for API key |

Production validation: `API_KEY` cannot use the default value in
`ENVIRONMENT=production`.

### OAuth2 (Google)

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_CLIENT_ID` | (empty) | Google OAuth2 client ID — sign-in, **and** the Gmail trigger's consent |
| `GOOGLE_CLIENT_SECRET` | (empty) | Google OAuth2 client secret |
| `GOOGLE_REDIRECT_URI` | `http://localhost:8000/api/v1/oauth/google/callback` | OAuth2 callback URL |
| `FRONTEND_URL` | `http://localhost:3000` | Frontend URL for OAuth2 redirects |

Getting the pair: [Google Cloud console](https://console.cloud.google.com/) →
APIs & Services → Credentials → Create OAuth client ID → **Web application**.

The authorized redirect URI is the **backend's** callback, not the frontend's -
`http://localhost:8000/api/v1/oauth/google/callback` by default, and whatever
`GOOGLE_REDIRECT_URI` says in a deployment. Google exchanges the code with the
API, which then sends the browser on to `FRONTEND_URL`. Registering the
frontend URL instead is the mistake worth naming: the consent screen works, and
the callback 404s.

The browser is sent on with a single-use, one-minute code, never the session
tokens themselves: a token in a redirect URL reaches the address bar, the
frontend server's access log, and the `Referer` of the next same-origin request,
and the refresh token is good for a week. The frontend swaps the code for the
token pair server to server at `POST /api/v1/oauth/exchange`, which redeems it
exactly once.


## Database (PostgreSQL)

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_HOST` | `localhost` | PostgreSQL host |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_USER` | `postgres` | PostgreSQL user |
| `POSTGRES_PASSWORD` | (empty) | PostgreSQL password |
| `POSTGRES_DB` | `agenticos` | Database name |
| `DB_POOL_SIZE` | `5` | Connection pool size |
| `DB_MAX_OVERFLOW` | `10` | Max overflow connections |
| `DB_POOL_TIMEOUT` | `30` | Pool timeout in seconds |

Computed properties:
- `DATABASE_URL` -- async connection string (`postgresql+asyncpg://...`)
- `DATABASE_URL_SYNC` -- sync connection string for Alembic

## Redis

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `localhost` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_PASSWORD` | (none) | Redis password (optional) |
| `REDIS_DB` | `0` | Redis database number |

## Background work (Prefect)

| Variable | Default | Description |
|----------|---------|-------------|
| `PREFECT_API_URL` | `http://localhost:4200/api` | The self-hosted server, or a Prefect Cloud workspace URL |
| `PREFECT_API_KEY` | (none) | Prefect Cloud only |
| `PREFECT_RUNNER_LIMIT` | `5` | How many flow runs execute at once; the rest queue |
| `PREFECT_RUNNER_SERVER_HOST` | `127.0.0.1` in compose | Interface the runner serves its own health endpoint on |
| `PREFECT_RUNNER_SERVER_PORT` | `8080` | Port for the same |

`PREFECT_RUNNER_LIMIT` is a memory ceiling, not a throughput dial. Each run is a
separate process that imports the whole application — roughly 120 MB — and the
number that matters is not the steady state but the restart: the runner comes up,
finds every run that was scheduled while it was down, and starts as many as the
limit allows. Uncapped, three days of downtime was 71 processes and 6 GiB. Raise
it if ingestion queues behind syncs on a machine with memory to spare; lower it on
a small host.

The two `PREFECT_RUNNER_SERVER_*` variables are Prefect's, and the compose files
pin them so the runner's container has a health status that means something. The
runner starts Prefect's runner webserver, whose `GET /health` answers 503 once it
has missed two polls of the Prefect API — so a process that is alive but no longer
picking up work reads `unhealthy` rather than fine. It is bound to the loopback
because the same webserver also exposes `POST /shutdown`; the probe runs inside
the container, and nothing outside it can reach either. Moving the port means
moving the probe in the compose files with it.

There is no `HEALTHCHECK` in `backend/Dockerfile`. The image is started as two
different processes — the API and this runner — and a probe for one is a
permanent false alarm on the other, so each service definition carries its own.

### Approval expiry

| Variable | Default | Description |
|----------|---------|-------------|
| `APPROVAL_EXPIRY_HOURS` | `72` | How long a parked tool call waits before the hourly sweep denies it by timeout |

Three days because it has to span a weekend: the approval that arrives on Friday
afternoon is the one nobody decides, and expiring it on Saturday would be expiring
it for having been asked at the wrong hour. Shorten it where a queue is watched
during the working day and a stale ask is worse than a slow one; lengthen it where
approvals are a weekly ritual. Expiring a call also **ends its run** — see
[Governance](governance.md#a-decision-nobody-makes) for what that settles and what
it deliberately leaves alone.

### Stale-run reaping

| Variable | Default | Description |
|----------|---------|-------------|
| `STALE_RUN_REAPED_AFTER_HOURS` | `6` | How long a run may sit `running` before the hourly sweep decides its process died and ends it as `failed`. Zero or below switches the sweep off |

A run's row is committed before its model is called, so a worker killed mid-run
leaves it `running` with nothing left to finish it. The ceiling does not have to
be exact — a live run the sweep flips anyway is flipped back by its own terminal
write — so set it well past your longest legitimate run and no closer. See
[Governance](governance.md#a-run-whose-process-died).

## AI Models — configured in the app, not here

Chat models are not environment variables. Each organization stores its own
provider keys in the vault (Settings → Models), and every agent's spec names
the model profile it runs on. `AI_MODEL`, `AI_TEMPERATURE`,
`AI_THINKING_ENABLED`, `AI_THINKING_EFFORT`, `AI_AVAILABLE_MODELS`,
`AI_FRAMEWORK` and `LLM_PROVIDER` were removed along with the template's
general assistant; setting them now does nothing.

The one model credential that stays in the environment is the embeddings key —
see RAG below.

## Observability (Logfire)

| Variable | Default | Description |
|----------|---------|-------------|
| `LOGFIRE_TOKEN` | (none) | Pydantic Logfire token. Get one at https://logfire.pydantic.dev |
| `LOGFIRE_SERVICE_NAME` | `agenticos` | Service name in Logfire dashboard |
| `LOGFIRE_ENVIRONMENT` | `development` | Environment tag |
| `LOGFIRE_ORGANIZATION` | (none) | Organization slug, for building a link **into** a stored trace. The token is a *write* credential and carries neither slug |
| `LOGFIRE_PROJECT` | (none) | Project slug, alongside the organization. With either unset a run's `logfire_trace_id` is still recorded and no link is offered |
| `LOGFIRE_BASE_URL` | `https://logfire-us.pydantic.dev` | Which Logfire deployment those slugs belong to. `logfire-eu` is a different host, and a link built for the wrong one 404s |

## Web Search

| Variable | Default | Description |
|----------|---------|-------------|

## RAG (Retrieval Augmented Generation)

### Vector Database

pgvector uses the existing PostgreSQL connection. No additional configuration
is needed.

### Embeddings

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | (empty) | The fallback embeddings credential, for collections that chose no vault key of their own — and the one a degraded choice falls back to. Not "every collection embeds on it": see [File processing](file-processing.md#embeddings-the-model-and-whose-key-pays) |
| `EMBEDDING_MODEL` | `text-embedding-3-large` | What a **new** collection is built with. The width is recorded on the row and never changes afterwards, so changing this does not invalidate existing collections — they keep embedding with the model they were created with |

### Document Parsing — configured per collection, not here

Parser, OCR, chunk size, chunk overlap, chunking strategy and the
image-description model are **not** environment variables. They are stored on
each knowledge base (`knowledge_bases.ingestion_config`) and edited on `/rag`,
and any one of them can additionally be overridden for a single upload.

The reason is that one installation-wide value made the same form produce
different collections on two deployments, with nothing in the product showing
which — and a scanned contract archive and a folder of Markdown notes want
different answers on the same deployment. `PDF_PARSER`, `CHAT_PDF_PARSER`,
`LLAMAPARSE_TIER`, `LITEPARSE_OCR_LANGUAGE`, `LITEPARSE_TIMEOUT_SECONDS`,
`RAG_ENABLE_OCR`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP` and
`RAG_CHUNKING_STRATEGY` were removed; setting them now does nothing.

What stays here is what a tenant must not choose:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLAMAPARSE_API_KEY` | (empty) | Fallback LlamaParse key for collections that chose no vault key of their own |
| `LITEPARSE_OCR_SERVER_URL` | (empty) | HTTP OCR server; an address on the deployment's own network |

Chat attachments are read with PyMuPDF and are not configurable: an attachment
belongs to no collection, so there is no stored configuration to read.

### Google Drive Sync

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_DRIVE_CREDENTIALS_FILE` | `credentials/google-drive-sa.json` | Path to Google service account credentials, for `rag-sync-gdrive` only |

**This is the CLI's credential, not a fallback for a sync source.** A `gdrive`
sync source names a `gcp_service_account` secret in its organization's vault and
runs on that or does not run: a deployment-wide key standing in for a missing one
meant a tenant's `folder_id` chose what was listed under the operator's service
account. The source's credential is not a setting and not a config field — see
[Secrets and the vault](secrets.md).

The file is a service account's key: [Cloud console](https://console.cloud.google.com/iam-admin/serviceaccounts)
→ create a service account → Keys → Add key → JSON. Then **share the Drive
folder with the service account's own email address** - it is a principal like
any other, and a folder nobody shared with it lists as empty rather than as
refused.

### S3/MinIO Sync

| Variable | Default | Description |
|----------|---------|-------------|
| `S3_RAG_ENDPOINT` | (none) | S3/MinIO endpoint URL. A sync source may override it |
| `S3_RAG_ACCESS_KEY` | (empty) | Access key, for the `rag-sync-s3` CLI command only |
| `S3_RAG_SECRET_KEY` | (empty) | Secret key, same |
| `S3_RAG_BUCKET` | `agenticos-rag` | Bucket name |
| `S3_RAG_REGION` | `us-east-1` | AWS region. A credential's own region wins where it has one |

**The key pair here is the CLI's, not a sync source's.** An `s3` sync source names
an `aws_credentials` secret in its organization's vault, the same way a `gdrive` one
names a service account. The endpoint and region still fall back to these settings
because neither names a principal — they say where the store is, not who is asking.

## Agent workspaces

The `state` workspace needs nothing here. It is stored in this database, works on
every deployment, and is what an agent gets by default — so the settings below
are only for a container-backed one.

| Variable | Default | Notes |
|---|---|---|
| `SANDBOX_STATE_MAX_BYTES` | 4 MiB | Per **stored** workspace. Past it a write is refused with a message the model reads |
| `SANDBOX_INLINE_IMAGE_MAX_BYTES` | 5 MiB | Above this an attached image is written to the workspace and not also sent inline |

**The percentage in the chat is two different ceilings, and it says which.** A
stored workspace fills up against `SANDBOX_STATE_MAX_BYTES` above — bytes, and
running out *refuses a write*. A container reports resident **memory** against the
ceiling its host set for that runtime, which is `1g` unless the allowlist says
otherwise, and running out of that is an OOM kill rather than a refusal. So the
strip says `workspace 12% full` for the first and `sandbox memory 12% full` for the
second; reporting either as the other would name a limit that does not apply.

**Where sandboxes run is not a setting.** It is a row per organization — Sandboxes
in the app, `sandbox_connections` in the database — with the service token in the
vault. Two reasons, and neither is expressible in an environment variable: a
deployment can hold more than one host, and one address per deployment gave every
organization the same one; and the token authorises opening a session, which runs
commands on the host holding the Docker socket, so it belongs where every other
credential at rest lives.

An operator registers a connection with a name, an address, and a key from the
vault. An agent names one by id, exactly as it names a model profile, or names
none and takes the organization's default — so moving to another host is one edit
rather than a republish of every agent.

**The service token is worth what the Docker socket is worth.** The service holds
that socket, the socket is an unauthenticated API for root on the host, and the
token is what opens a session on it. Never in a browser, never in a log, never
committed — which is why the operator screen shows only that a credential is
attached, and why `GET /policy` is proxied through this API rather than fetched by
the browser. The service's own dashboard (`SANDBOXD_UI_ENABLED`) is off in every
shipped compose file for the same reason: it asks a human to paste this value into
a browser.

`SANDBOXD_TOKEN` in `backend/.env` is the *service's* own — what the daemon in the
compose file will accept. `make sandbox-token` generates it, and the connection
form stores the same value in the vault for you: the API reads this setting for
exactly one purpose, offering it to the vault, and asking somebody to copy a secret
out of a file their own stack is already reading is friction with nothing behind
it. It is never used to reach a host — resolving a connection unseals the vault
entry that connection names, and that stays the only path — so a deployment that
leaves it unset loses one button and nothing else, and pastes the token instead.

The same form asks whether a service is already answering, rather than making an
operator know that a `make dev` sandbox service lives at `http://sandboxd:8080`.
That address is not configuration and deliberately so — it is a row, because a
deployment can hold several hosts — so the API probes the unauthenticated
`/healthz` at the address this project's compose file uses and prefills what
answered. Nothing is decided by asking: no service means an empty field, and a
connection already pointing there is named so nobody registers one host twice.

**The address is fetched by this API, so it is validated as one.** Registering or
probing a connection makes the API container issue an authenticated `GET` and hands
the JSON body back, which is a request-forgery primitive if the address is taken on
trust. So `base_url` refuses anything that is not `http(s)` with a host, and refuses
link-local addresses and the instance-metadata hostnames outright —
`169.254.169.254` and `metadata.google.internal` are never a sandbox service.

Private addresses stay allowed, and have to: `http://sandboxd:8080` inside compose
and `http://localhost:8080` for a developer running the API on their host are both
private, so a private-range denylist would refuse the deployment this page
describes. That means the validator narrows the hole rather than closing it — a
hostname that resolves to something internal still resolves. **The boundary that
actually holds is `connections:manage` plus egress policy on the API container**:
whoever may register a host is trusted with one, and a deployment on a network
holding unauthenticated internal APIs should say so at the network rather than here.

### Which environments an agent may ask for

One runtime ships — `workbench` (1.93 GB): Python 3.12, Node 24, LibreOffice, and
the libraries an agent needs to read, write, convert and plot the files a
conversation is about, including liteparse with OCR. It is defined in
`backend/app/core/catalog/sandbox_runtimes.json`. Adding one is an edit there and
`make sandbox-runtimes`, which writes `SANDBOXD_RUNTIMES` into all three compose
files; that variable is the only channel the service accepts runtimes on, and
`PUT /policy` deliberately refuses the membership of the list.

`sandbox.md#which-environments-an-agent-may-ask-for` has the field-by-field
format, the three traps (the first entry is the default, `network_mode` is not
inherited, a build is paid for at start-up by `prewarm`) and why the generated
copy in the compose files cannot drift from the catalogue.

### The service's own settings

Every field of the service's configuration is `SANDBOXD_` plus its name, so this is
a subset rather than a vocabulary. These are the ones the shipped compose files set
or that decide whether files survive:

| Variable | Shipped | What it decides |
|---|---|---|
| `SANDBOXD_WORKSPACE_ROOT` | a host path | Where each session's work directory lives, bind-mounted from the *host*. **Unset, files exist only inside a running container** — an idle reaping discards them and the next request opens an empty workspace, with nothing in a log. It is also what makes browsing possible: reading a workspace never starts a container |
| `SANDBOXD_SANDBOX_UID` | `10001` | The unprivileged user a sandbox runs as, instead of root — a container escape starts from whoever the container runs as, and every file an agent writes is owned by this uid on the host. **Has to be the service's own uid**: opening a session `chown`s the workspace to this user, which an unprivileged service can only do for itself. Applies to a runtime the deployment *builds*, since a ready-made image has no such account and an agent inside one could install nothing |
| `SANDBOXD_CONTAINER_TTL` | 86400s | How long a *stopped* persisted container is kept. Reclaims what a session installed — the build, the wheels, `node_modules` — and leaves the workspace untouched, because the files are the work. Unset, they are kept for ever |
| `SANDBOXD_PERSIST_CONTAINERS` | `true` | A closed session's container is kept rather than removed, so the next session on that workspace starts without a build. Costs a stopped container per workspace; `SANDBOXD_CONTAINER_TTL` bounds it |
| `SANDBOXD_MAX_SESSIONS_PER_TENANT` | `5` | One organization cannot take the pool. `SANDBOXD_MAX_SESSIONS` (20) is the pool |
| `SANDBOXD_NETWORK_MODE` | `none` | The default network for a sandbox. `none` is no network at all; a runtime may name `bridge` for itself |
| `SANDBOXD_UI_ENABLED` | `0` | The service's own dashboard. Off because it asks a human to paste a root-equivalent token into a browser |
| `SANDBOXD_IDLE_TIMEOUT` | 1800s | How long an idle session lives before it is closed and reaped |
| `SANDBOXD_MEM_LIMIT` | `1g` | The default memory ceiling, and therefore the number the chat's `sandbox memory` percentage is a share of |

### Running the service on another host

Nothing about a connection assumes a local address — it is a row holding a URL and
a vault credential, and the form probes whatever it is given. A host somewhere else
needs three things and no code:

1. **The Docker socket**, because the service starts containers. That is root on
   that machine, which is why the token below is worth what it is.
2. **`SANDBOXD_WORKSPACE_ROOT` on real disk, mounted at the same path on both
   sides.** The service creates the directory and then asks the *daemon* to
   bind-mount it, and the daemon resolves the path on the host — so a named volume,
   or a path existing only inside the service's container, is refused with `mounts
   denied`.
3. **TLS and a token nobody shares.** Inside compose the address is
   `http://sandboxd:8080` on a private network; across the internet it is a service
   that will run commands for whoever holds the token, so it belongs behind HTTPS
   with its own value.

Then register it in Sandboxes like any other, and point an agent at it by name. The
compose service is one deployment of the same image.

### When a session is open

The **Running** tab lists the sessions the service holds, refetched every ten
seconds, and a session is one workspace on one host. Three states, and only the
first two appear:

- **running** — the container exists and is resident. Opened by an agent's first
  tool call in a conversation, not when the conversation starts.
- **hibernated** — the row exists and the container does not. A session idle past
  `SANDBOXD_EVICT_IDLE_AFTER` is hibernated to free a slot, and its next request
  wakes it. This needs `WORKSPACE_ROOT`, or waking one would open an empty
  workspace, and the service refuses the combination rather than doing that.
- **gone** — past `SANDBOXD_IDLE_TIMEOUT` the session is closed and reaped. With
  `PERSIST_CONTAINERS` the container survives that, so the next session on the same
  workspace starts without a build.

So an empty Running tab means no agent has used a shell recently, not that nothing
is configured — and a workspace with files in it and no session is the normal
resting state.

The service runs behind the `sandbox` compose profile, which is on by default in
local dev and off elsewhere until an operator opts in — mounting the Docker socket
on a shared host is a deliberate act. `COMPOSE_DEV_PROFILES` in the Makefile is
the one place to change that. `uv run agenticos cmd doctor` probes every registered
connection: whether it answers, whether it accepts its credential, and whether it
allows any runtime at all. No connection registered is a warning, not a failure —
the `state` workspace needs none.

**Browsing what the agents kept.** Workspaces is its own screen — not part of
Sandboxes, which is about *hosts*. Each row names the agent, the conversation the
files belong to (or how many chats reach them, for a workspace no single
conversation owns), who can see them, how big it is and when it was last used.
**Open** goes to that workspace's own page, in the shape the skills editor uses:
the tree on the left — folders walked one at a time, a search box over the whole
tree rather than the folder on screen — and the file itself rendered beside it, so
reading three files is three clicks and the list never closes. Downloading is on
the row rather than beside the reader, because selecting a file reads it and a
large archive is one somebody wants a copy of without paying for that. A second view on the listing flattens every file the reader
can see into one grid — the "who is holding a copy of that CSV" question the
per-workspace page cannot answer.

**Clicking a file opens it in a viewer, and it is the same viewer in the chat panel.**
An image is a picture, a PDF is the browser's own PDF view, markdown offers *Preview*
and *Source* — both are the file, and a `#` that silently became large type is how
somebody fails to notice their agent is writing markdown into something nothing reads
as markdown — and anything else is its text. Download is always there, including for
what cannot be shown at all. One component, because "open this file" meaning two
different things on two screens is how the second one ends up missing a case.

Bytes come from `GET /sandbox-workspaces/{id}/raw?path=…`, or from `GET
/conversations/{id}/workspace/raw?path=…` for the panel beside a chat. Two routes
rather than one because they authorise different callers — the conversation route is
reached by fetching the conversation, so somebody a chat was *shared with* keeps
access — and one module deciding what may be displayed, so the answer cannot differ
by surface. Almost everything is served as an attachment; **raster images and PDFs**
are served for display, a raster because it cannot execute and a PDF because the
browser renders it in its own viewer, which never gets the page's DOM. **SVG and HTML
are downloadable and never displayable** — an SVG served inline from this origin is
stored cross-site scripting written by whatever the agent decided to save, and "the
agent wrote it" is not a trust boundary. Everything else is typed
`application/octet-stream` with `X-Content-Type-Options: nosniff`, so a browser
cannot decide such a body is HTML after all. The filename travels as `filename*`
only, because a workspace path can hold any UTF-8 and the bare form has no way to
say so.

Only a **stored** workspace can serve arbitrary bytes. A container-backed one is read
through the workspace archive, whose only reader is textual, so a text file is served
by encoding it and anything else is refused rather than quietly mangled — the browser
offers the download beside the refusal so the answer is never a dead end.

Files are read only when a workspace is opened, or when the flat view is switched
on: a deployment can hold one per warm conversation, so reading each to render the
table would be a request per row for a page nobody has asked a question of yet. The
flat view is bounded for the same reason, and says so — how many workspaces it read,
how many it could not, and whether more exist. A shorter list is otherwise
indistinguishable from fewer files.

**Who sees which workspace is decided per reader, in the query.** A caller holding
`connections:manage` sees the organization's — the honest bar for a listing that
crosses chats that are not theirs. Everybody else sees the workspaces they are part
of: their own `user`-scoped files, the workspaces of their own conversations, and
the shared workspace of an agent they have talked to. "Have talked to" rather than
"could open", deliberately: `agent` scope shares one workspace across an agent's
users and the chat panel already shows those files to anybody in a conversation
with it, so being *able* to open the agent is a wider claim than this listing makes.

`channel` scope is visible to an operator only, which is correct rather than an
oversight — it is keyed on a Slack or Telegram chat, so the people sharing it are
identified by that platform and not by a row in `users`.

A workspace fetched by id applies the same three predicates and answers **not
found** rather than forbidden when they fail: an id must not be usable to discover
which workspaces exist in a colleague's conversation. Nothing here crosses an
organization — an app admin browsing another tenant's files would be the one read
this platform refuses, so they switch organization like anybody else.

**A container-backed workspace is read off the host volume, which needs one.** The
sandbox service serves those files from `SANDBOXD_WORKSPACE_ROOT`, and that is what
lets a conversation from last month list its files after its session was reaped —
no container is started to answer. A service configured *without* one keeps nothing
on disk, so its files exist only while a sandbox is running and cannot be read
without starting one: the Files panel could then only say so, for a file the agent
had demonstrably just written.

Every compose file therefore sets one, overridable with `SANDBOX_WORKSPACE_ROOT` (an
environment variable where compose interpolates it — the project root, not
`backend/.env`, except on the `dev` and `prod` targets which pass that file
explicitly) — one host path,
bind-mounted at the same location on both sides, because the service creates the
directory and then asks the *daemon* to mount it and the daemon resolves the path on
the host. A named volume, or any path existing only inside the service's container,
is refused with "mounts denied". Local dev defaults to
`/tmp/agenticos-sandbox-workspaces`, which Docker Desktop shares and anybody can
write to, so a laptop needs no setup; the server files default to
`/var/lib/agenticos/sandbox-workspaces`, which has to exist and be writable by uid
10001 (`install -d -o 10001` once) and belongs on storage somebody backs up. A
reboot sweeps `/tmp`, which is the one reason not to point a real deployment there.

That is reported rather than raised. Every listing carries `unreadable_reason`, and
a client shows it as an explanation instead of an error, because neither cause is a
fault: a service keeping nothing on disk is a configuration with a one-line fix the
message names, and a host that is down will be up later. Raising made it a 500,
which a browser could only render as "something went wrong" — beside an empty list,
which reads as "there are no files". Two wrong answers at once. Reading *one file*
from such a host is refused with the same sentence rather than reported as "no such
file", which would say the file is missing when it is not.

**What is running is read from the service too.** The Sandboxes screen keeps it on
its own tab, apart from the connections table, and lists this organization's open
sandboxes on the host it names — the default connection until the operator picks
another — sortable by idle time and memory: runtime, what shares each one, idle
time, and memory against its own ceiling when asked — plus the activity log
per sandbox: which paths were read, which commands ran, and how each went. Neither
file contents nor command output is recorded by the service, which is what keeps
an audit trail from becoming a way to read another agent's work. The dashboard
answers the same three questions in its own section, for a caller holding
`connections:manage`; memory is behind a switch there for the same reason it is on
the screen, because the service samples each sandbox individually for it.

**All three ceilings now divide.** The session listing is filtered to the caller's
organization but carries `SANDBOXD_MAX_SESSIONS` and `SANDBOXD_MAX_OPEN_SESSIONS`
through from the service untouched, so those two count every tenant on the host while
the rows count one - `len(sessions)` divides only against `SANDBOXD_MAX_SESSIONS_PER_TENANT`.
The response carries two host-wide numerators for the other pair, taken from the
unfiltered list before the filter narrows it: `host_session_count`, the resident
sandboxes the service marks `state == "running"`, against `limit`; and
`host_open_count`, every session that exists resident or hibernated, against
`open_limit`. Now the capacity card can say why a session was refused while this
organization is short of its own ceiling: the host itself is full of somebody else's
work. That the two are host-wide is a deliberate, narrow disclosure - two aggregate
integers naming nothing, a long way from the session rows the filter withholds, and
the listing is gated on `connections:view`, the authority to watch a host rather than
any member's. They are `None` on a Daytona connection, which enforces no ceilings of
ours to divide.

That listing is **filtered, not forwarded**. One `sandboxd` answers for every
organization that registered a connection at its address, so passing its response
through would show one tenant another tenant's containers. Sessions are matched on
the `tenant` label this platform sets when it opens one, and named from
`agent_workspaces` rather than by decoding the session id — the id encodes the
scope key, and parsing it back would make that format a schema.

**What the service allows is read from the service.** The runtime allowlist and the
ceiling behind each alias (`SANDBOXD_RUNTIMES`, `SANDBOXD_MEM_LIMIT`,
`SANDBOXD_NETWORK_MODE`, `SANDBOXD_MAX_SESSIONS_PER_TENANT` and the rest) are its
own boot configuration, and there is deliberately no endpoint to write them: a
browser that could reconfigure the process holding the Docker socket would own the
host. The Sandboxes screen and the dashboard's runtimes card both *read* them so
what is in force is visible, and the Builder offers an agent only the aliases the
service will actually accept.

Neither view asks a Daytona connection any of this. It publishes no allowlist of its
own and holds none of our sessions to enumerate — what it permits is a setting on
that account, and what runs there is visible in its own dashboard.

## Messaging Channels

| Variable | Default | Description |
|----------|---------|-------------|

Bot credentials are not configured here: each bot is registered in the app
with its token sealed in the vault, and a Slack bot additionally carries its
own app's signing secret and `xapp-` token (`SLACK_BOT_TOKEN`,
`SLACK_SIGNING_SECRET` and `SLACK_APP_TOKEN` were removed - each bot is its
own Slack app now). Telegram webhook
URLs are built from `PUBLIC_BASE_URL` (`TELEGRAM_WEBHOOK_BASE_URL` was
removed), model profiles may point at local endpoints such as Ollama without
any flag (`ALLOW_INTERNAL_MODEL_ENDPOINTS` was removed), and the `run_python`
sandbox limits are per-agent capability configuration
(`CODE_EXECUTION_TIMEOUT_SECS` / `CODE_EXECUTION_MAX_MEMORY_MB` were removed).

## CORS

| Variable | Default | Description |
|----------|---------|-------------|
| `CORS_ORIGINS` | `["http://localhost:3000","http://localhost:8080"]` | Allowed origins (JSON array) |
| `CORS_ALLOW_CREDENTIALS` | `true` | Allow credentials (cookies) |
| `CORS_ALLOW_METHODS` | `["*"]` | Allowed HTTP methods |
| `CORS_ALLOW_HEADERS` | `["*"]` | Allowed HTTP headers |

Production validation: `CORS_ORIGINS` cannot contain `"*"` in
`ENVIRONMENT=production`.

## Rate Limiting

Applied to the surfaces a stranger can reach, and only those: the public run API,
the widget's script, its config, either surface's socket handshake, a hosted
page's config and logo, and a visitor's upload. The console's own routes are
behind a session and are not metered — whether the whole API should carry a
ceiling is a separate decision, not this one.

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_RUN_PER_MINUTE` | `30` | `POST /api/v1/agents/{id}/run`, per caller |
| `RATE_LIMIT_AUTH_PER_MINUTE` | `10` | Every `auth.py` route — login, register, refresh, the reset/magic-link request and verify routes. Counted **per IP and, where the body carries one, per submitted address**. See below |
| `RATE_LIMIT_EMBED_PER_MINUTE` | `20` | Per address, and **two separate counters of this size**: one for `widget.js`, one for admission — the widget's `/config` plus either surface's socket handshake. See below |
| `RATE_LIMIT_HOSTED_PAGE_PER_MINUTE` | `240` | A hosted page's config, **per page** — and its logo, on a counter of its own. See below |
| `RATE_LIMIT_EMBED_UPLOAD_PER_MINUTE` | `5` | Files a visitor may store on a hosted page. Counted **per address and per visitor key**, and both have to allow it — the key is minted by the browser, so counting only that bounds nothing |
| `RATE_LIMIT_TRUST_FORWARDED_FOR` | `false` | Whether `X-Forwarded-For` names the caller |

**What a refused caller gets** is this API's own error envelope with
`code: "RATE_LIMIT_EXCEEDED"`, the interval in
`error.details.retry_after_seconds`, and the same interval in the `Retry-After`
header — which is the one a fetch wrapper or a CDN actually backs off on. The
socket handshake is the exception, because a WebSocket has no status to answer
with: it closes with `4029` (see [channels](channels.md#the-raw-websocket)).

**Two counters, not one, and the reason is arithmetic.** Loading a page with a
widget on it costs three requests to this API: the script, the config, and the
socket. Counted together, `20` bought about seven page loads for a cold browser
rather than twenty admissions, and a limit wrong by a factor of three is worse
than no limit because it reads as the number you set. So `widget.js` has its own
bucket — it is cacheable, and a refusal there breaks the widget outright instead
of delaying one message. The config and the handshake stay together, because
together they *are* one admission: a browser that read a config and opened no
socket did not get in.

The counts live in the deployment's Redis, so they hold across workers —
production runs four, and a count kept per process would let through four times
what it says. If Redis cannot be reached the limit is not applied and a warning
is logged: refusing a visitor their answer because a cache blipped is the worse
failure of the two.

What a visitor may *say* once admitted is a different number, set per widget in
the Builder (`rate_limit_per_minute`) and counted per visitor. These two are the
ceiling on getting in.

### `RATE_LIMIT_HOSTED_PAGE_PER_MINUTE`, and why it is not per address

A hosted page's config is fetched **server-side**, by the frontend, so the page
paints branded on the first frame. That means the address on the request is the
frontend container's and not the visitor's — so counting it put every hosted page
load in the deployment in a single bucket, and the visitor who tripped it was
served a 404 with nothing saying why. `RATE_LIMIT_TRUST_FORWARDED_FOR` cannot
help: a server-side `fetch` sends no such header for anyone to trust.

So this one is counted per public key. It bounds a single page rather than
rationing a visitor, which is why the default is wide — **it is not what limits
spend.** Spend starts at the socket the page opens next, which the browser makes,
which is counted per address under `RATE_LIMIT_EMBED_PER_MINUTE`. And guessing a
key is not a strategy against 192 bits of `secrets.token_urlsafe`.

### `RATE_LIMIT_AUTH_PER_MINUTE`, and why the auth surface has its own

Every route in `auth.py` carries this limit, counted **per IP** and — where the
body carries an address (login, register, the reset and magic-link requests) —
**per submitted address too**, both against this allowance. The two stop
different attacks: the IP bounds a flood from one source, the address bounds a
brute force against one account.

It is separate from, and lower than, the run allowance because the cost of a
single attempt is what it defends. `verify_password` is bcrypt, ~170ms with no
suspension point, so an unmetered `/login` flood for any address that has an
account saturates a worker's event loop with no credentials at all. Two more
things close the rest of that surface, and need no configuration: bcrypt runs in
a thread so it never blocks the loop, and an address with no account is verified
against a dummy hash rather than skipped, so a known and an unknown address take
the same time to refuse and the timing no longer says which addresses exist.

### `RATE_LIMIT_TRUST_FORWARDED_FOR`, and why it is off

Per-address limits count `request.client.host`. **Behind a proxy or a CDN that
is the proxy's address, not the visitor's** — every visitor shares one bucket, so
a busy site behind Cloudflare exhausts the widget's twenty admissions a minute
for everybody at once. Turning this on reads the **rightmost** `X-Forwarded-For`
hop instead — the address the trusted proxy itself appended.

It is off by default because the header is set by whoever is calling: trusted
unconditionally, a per-address limit becomes a per-header limit that anybody
bypasses by varying one string. The rightmost hop is read rather than the
leftmost for the same reason — `X-Forwarded-For` is a list the client starts and
each proxy appends to, so the head is what the client typed and only the tail is
what a proxy you control wrote. **Turn it on only when a single proxy you control
is the only thing that can reach the API** — if the container's port is published
as well, a caller can set the header themselves and the limit stops meaning
anything; and with two proxies in front, collapse the header to one hop at your
edge, because only the last hop is trustworthy.

## A worker whose event loop has stopped turning

| Variable | Default | Description |
|----------|---------|-------------|
| `EVENT_LOOP_WEDGED_AFTER` | `15` | Seconds the event loop may stop turning before the worker is killed and replaced. `0` or below switches the check off |

A worker that is *alive but not answering* — deadlocked on a lock, spinning in a
synchronous call, blocked on a socket that never answers — has no exit code, so
every recovery path in every stack used to read it as healthy while requests
timed out. The container goes `unhealthy`, and a status is not a mechanism.

So the worker judges its own event loop. A timer callback stamps the loop once a
second; a thread reads the stamp, and if the loop has not turned for
`EVENT_LOOP_WEDGED_AFTER` across two consecutive checks it ends the process —
`SIGKILL`, or `os._exit(137)` where the worker is PID 1, because the kernel
delivers no signal to a namespace's init that init has no handler for. Either
way `docker inspect` reports `137`, and "wedged", which nothing handled, becomes
"gone", which every stack already handles:

| Stack | What replaces the worker |
|---|---|
| `docker-compose.yml` | the reload supervisor, on its next poll |
| `docker-compose-dev.yml` | PID 1 is the server, so the container exits and `restart: unless-stopped` acts |
| `docker-compose-prod.yml` | uvicorn's `Multiprocess`, within about half a second; the other three workers keep serving |

Two properties are the reason for the design, and both are worth knowing before
changing the number:

- **It measures liveness, not readiness.** The stamp is a timer callback, not a
  request, so a slow database or a model provider that takes twenty seconds is
  not a wedge — the loop is turning, it is waiting. An HTTP probe would have
  been fewer moving parts and would restart-loop a healthy server against a
  broken dependency.
- **Two checks, not one.** `docker pause`, a frozen cgroup and a laptop waking
  from sleep stop the watchdog as thoroughly as the loop, so the first check
  after one reads a stale stamp that says nothing.

The local stack's reload supervisor reads the same variable for the judgement it
makes from *outside* the worker, so one number covers both.

!!! tip "Set it to `0` while debugging"

    A breakpoint blocks the event loop and nothing can tell that from a deadlock,
    so a worker sitting on one is otherwise killed under you.

It cannot see a process that is not running at all — `kill -STOP`, a frozen
cgroup — because a watchdog inside a stopped process is stopped too. That case
is the one the supervisors already cover: the reload supervisor's beat goes
stale and production's pipe ping goes unanswered.

## Docker / Production

| Variable | Default | Description |
|----------|---------|-------------|
| `DOMAIN` | `example.com` | Production domain (for Traefik) |
| `ACME_EMAIL` | `admin@example.com` | Let's Encrypt email for SSL certs |
| `REDIS_PASSWORD` | `change-me-in-production` | Redis password for production |

## Production Checklist

!!! danger "Every one of these ships with a default that is wrong in production"

    A deployment reachable from anywhere else has all nine set deliberately.

- [ ] `SECRET_KEY` — a unique 64-character hex key: `openssl rand -hex 32`
- [ ] `API_KEY` — a unique key: `openssl rand -hex 32`
- [ ] `VAULT_MASTER_KEY` — a unique key: `openssl rand -hex 32`. The config
      refuses an empty one outside `local`/`development`
- [ ] `ENVIRONMENT` — `production`
- [ ] `DEBUG` — `false`
- [ ] `POSTGRES_PASSWORD` — a strong, unique password
- [ ] `REDIS_PASSWORD` — a strong password
- [ ] `CORS_ORIGINS` — only your actual frontend domain(s)
- [ ] `OPENROUTER_API_KEY` — your production API key
