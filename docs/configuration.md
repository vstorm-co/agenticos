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

`SECRET_KEY` ships as a published string, and an empty `VAULT_MASTER_KEY` falls
back to it so a fresh checkout runs at all. Both are fine on a laptop and are the
whole security of a deployment anywhere else — and setting `VAULT_MASTER_KEY`
explicitly is also what lets stored secrets survive a `SECRET_KEY` rotation.

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
| `MAX_UPLOAD_SIZE_MB` | `50` | Knowledge-base document cap. Chat and embed uploads are bounded by the hardcoded `MAX_UPLOAD_SIZE` (10 MiB in `file_storage.py`), not by this |
| `EMBED_MAX_UPLOAD_SIZE_MB` | `5` | What a **stranger** may upload to a hosted page. A ceiling on top of the chat path's `MAX_UPLOAD_SIZE`, never a way past it |

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
| `VAULT_MASTER_KEY` | (empty, falls back to `SECRET_KEY`) | Master key for the secret vault. Set it explicitly in production so stored secrets survive a `SECRET_KEY` rotation. Generate with: `openssl rand -hex 32` |

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
| `GOOGLE_CLIENT_ID` | (empty) | Google OAuth2 client ID |
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
sync source carries its own `service_account_json` and runs on that or does not
run: a deployment-wide key standing in for a missing field meant a tenant's
`folder_id` chose what was listed under the operator's service account.

The file is a service account's key: [Cloud console](https://console.cloud.google.com/iam-admin/serviceaccounts)
→ create a service account → Keys → Add key → JSON. Then **share the Drive
folder with the service account's own email address** - it is a principal like
any other, and a folder nobody shared with it lists as empty rather than as
refused.

### S3/MinIO Sync

| Variable | Default | Description |
|----------|---------|-------------|
| `S3_RAG_ENDPOINT` | (none) | S3/MinIO endpoint URL |
| `S3_RAG_ACCESS_KEY` | (empty) | Access key |
| `S3_RAG_SECRET_KEY` | (empty) | Secret key |
| `S3_RAG_BUCKET` | `agenticos-rag` | Bucket name |
| `S3_RAG_REGION` | `us-east-1` | AWS region |

## Agent workspaces

The `state` workspace needs nothing here. It is stored in this database, works on
every deployment, and is what an agent gets by default — so the settings below
are only for a container-backed one.

| Variable | Default | Notes |
|---|---|---|
| `SANDBOX_STATE_MAX_BYTES` | 4 MiB | Per workspace. Past it a write is refused with a message the model reads |
| `SANDBOX_INLINE_IMAGE_MAX_BYTES` | 5 MiB | Above this an attached image is written to the workspace and not also sent inline |

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
**Open** goes to that workspace's own page: folders walked one at a time, a search
box over the whole tree rather than the folder on screen, tiles for the files, and
every file downloadable. A second view on the listing flattens every file the reader
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

**What is running is read from the service too.** The Sandboxes screen lists this
organization's open sandboxes on its default host — runtime, what shares each one,
idle time, and memory against its own ceiling when asked — plus the activity log
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

Applied to the surfaces a stranger can reach, and only those: the public run
API and the admission step of the widget and the hosted page. The console's own
routes are behind a session and are not metered — whether the whole API should
carry a ceiling is a separate decision, not this one.

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_RUN_PER_MINUTE` | `30` | `POST /api/v1/agents/{id}/run`, per caller |
| `RATE_LIMIT_EMBED_PER_MINUTE` | `20` | Widget admission and a hosted page's socket, per address |
| `RATE_LIMIT_HOSTED_PAGE_PER_MINUTE` | `240` | A hosted page's config, **per page** — see below |
| `RATE_LIMIT_EMBED_UPLOAD_PER_MINUTE` | `5` | Files a visitor may store on a hosted page. Counted **per address and per visitor key**, and both have to allow it — the key is minted by the browser, so counting only that bounds nothing |
| `RATE_LIMIT_TRUST_FORWARDED_FOR` | `false` | Whether `X-Forwarded-For` names the caller |

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
makes from *outside* the worker, so one number covers both. Set it to `0` while
debugging: a breakpoint blocks the event loop and nothing can tell that from a
deadlock, so a worker sitting on one is otherwise killed under you.

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

Before deploying to production, ensure these variables are properly set:
1. `SECRET_KEY` -- Generate a unique 64-character hex key: `openssl rand -hex 32`
2. `API_KEY` -- Generate a unique key: `openssl rand -hex 32`
3. `ENVIRONMENT` -- Set to `production`
4. `DEBUG` -- Set to `false`
5. `POSTGRES_PASSWORD` -- Use a strong, unique password
6. `CORS_ORIGINS` -- List only your actual frontend domain(s)
7. `REDIS_PASSWORD` -- Set a strong password
8. `OPENROUTER_API_KEY` -- Your production API key
