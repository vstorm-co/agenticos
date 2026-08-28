# Commands Reference

This project provides commands via two interfaces: **Make** targets for common
workflows and a **project CLI** for fine-grained control.

## Make Commands

Run these from the project root directory.

### Quick Start

| Command | Description |
|---------|-------------|
| `make quickstart` | Start Docker, run migrations, create admin user. Does **not** install dependencies — `make install` first |
| `make install` | The whole setup path: `backend/.env` from the example if there is none, backend dependencies with uv, `frontend/node_modules` with bun, and the pre-commit hooks. All of it, because `make check` needs all of it — `db-check` reads the env file, and eslint, prettier, tsc, vitest and next live only in `node_modules`. Both are per-checkout, so this is owed on every clone; an existing `.env` is never overwritten |

### Development

| Command | Description |
|---------|-------------|
| `make run` | Start development server with hot reload |
| `make run-prod` | Start production server (0.0.0.0:8000) |
| `make routes` | Show all registered API routes |
| `make test` | Backend suite plus the 100% gate on the platform layer. Runs across worker processes (`-n auto --maxprocesses 4`); `pytest-cov` combines their data, so the gate is unchanged |
| `make test-cov` | Run tests with coverage report (HTML + terminal). Runs across worker processes like `make test` |
| `make format` | Auto-format code — ruff on the backend, prettier on the frontend |
| `make lint` | Every static check: ruff, ruff format, ty, vulture, deptry, eslint, prettier, tsc, the guard scripts (backtick, i18n, routes, banner comments), knip's dependency check, and codespell over the whole tree |
| `make lint-backend` / `make lint-frontend` | One half of the above. CI runs them in two different jobs, so either can be run on its own |
| `make dead-code` | Unused functions and methods — vulture at a lower confidence than the `lint` gate, plus knip's full report on the frontend. A report to read, not a gate: on a registry-driven codebase it comes with false positives (a CLI command, a capability hook), so read each before deleting. The same role `dependency-freshness` plays for dependencies. Its one unambiguous half — a package in `package.json` that nothing imports — gates in `lint-frontend` instead (`bun run lint:deps`), because a dependency that survived being unused for months is what motivated it |
| `make lint-spelling` | codespell over every tracked file. The pre-commit hook reads only the files a commit touches, so a misspelling that lands with its file waits there to refuse somebody else's unrelated commit |
| `make lint-precommit` | yamlfmt, zizmor and the `pre-commit-hooks` basics over every tracked file. Same reason as `lint-spelling` — those hooks are per-file, so a `rev:` bump that brings a new rule breaks the tree with nothing noticing. `SKIP` drops the hooks `lint-backend`/`lint-frontend`/`lint-spelling` already gate, so it neither doubles their time nor lets a fixer rewrite a file mid-check |
| `make build-frontend` | `next build`. Type-checks the route tree and fails on a server component that cannot render — which neither tsc nor vitest sees |
| `make audit` | Audit the locked dependency set for known vulnerabilities. Needs the network — one request per locked distribution — so its last line says which of four states it ended in rather than leaving a red run ambiguous. See below |
| `make sandbox-token` | Generate the sandbox service's own `SANDBOXD_TOKEN` into `backend/.env`, once. `make dev` runs it for you; it never regenerates, because a new token orphans every workspace the service is holding. The connection form offers to store the same value in the vault, so it does not have to be pasted anywhere |
| `make clean` | Remove cache files (__pycache__, .pytest_cache, etc.) |

### Before a pull request

!!! success "`make check` is every CI job except `e2e`"

    The equality is maintained rather than asserted, and
    `backend/tests/test_ci_parity.py` is what keeps it true. It has drifted four
    times.

`.github/workflows/ci.yml` calls these same Make targets rather than repeating
their commands, so a gating job that grows a step `check` does not run fails the
parity test — as does the reverse.

```bash
make check   # lint, test, db-check, test-frontend-cov, build-frontend, docs-build, audit
```

About five minutes, serial, on a warm cache. What it deliberately leaves out:

| Not in `check` | Why, and what to run instead |
|---|---|
| `e2e` | Needs a migrated database, a seeded organization and a running backend: `make dev && make platform-bootstrap && make test-e2e` |
| The image build and Trivy scan | CI runs those only on a push to `main` |
| `make test-migrations` | CI cycles the chain against a throwaway `test_db`. On a laptop `alembic downgrade base` points at whatever `backend/.env` says, which is usually the database with your own work in it — `uv run pytest tests/test_migrations.py` asks the same question against a database of its own, and `make test` already runs it |

!!! warning "One gap no command can close"

    CI's `test` job has a Postgres beside it, so `tests/integration/` runs there;
    locally it skips itself when nothing answers on 5432. `make check` says so at
    the end when that happens — run `make docker-db` first if the change is
    anywhere near the database.

### What a red `make audit` means

`make audit` exports what the lockfile resolves to — which is what a deployment
installs — and hands it to `pip-audit`, which asks the vulnerability feed about
each of the 254 locked distributions in turn. `pip-audit` on its own cannot say
which of two very different things went wrong: it exits 1 whether it found an
advisory or died on a `ReadTimeout` reaching for one, and `Security Scan` is a
required check, so one slow answer out of 254 blocks a merge while reading
exactly like a real finding until somebody opens the log
([#855](https://github.com/vstorm-co/agenticos/issues/855)).

`scripts/audit_dependencies.py` stands between the two and **ends every run on
one line**:

```
AUDIT: CLEAN — no known advisories against 254 locked dependencies
AUDIT: VULNERABLE — 6 known advisories in 1 of 254 locked dependencies
AUDIT: NETWORK — unreachable (ReadTimeout) after 3 attempts; no audit was performed
AUDIT: FAILED — pip-audit reached no verdict in 3 attempts and did not say why; no audit was performed
```

| State | Means | What to do |
|---|---|---|
| `CLEAN` | Every locked dependency was audited, none has a known advisory | Nothing |
| `VULNERABLE` | A locked dependency has a known advisory. Ids, fixed versions and CVE aliases are printed above the verdict | Upgrade it |
| `NETWORK` | No audit happened, and the cause was recognisably the network | Re-run |
| `FAILED` | No audit happened, and the cause was not recognised. pip-audit's own output is on stderr | Read that output |

**A line, not an exit code, because make cannot carry one.** GNU Make turns any
failed recipe into its own exit 2, so `make audit` returns 2 for both `VULNERABLE`
and `NETWORK` and there is no target shape that changes that. Anything reading the
result through this interface — the `Security Scan` job included — reads the line:
`make audit | tail -1`, or `make audit 2>&1 | grep '^AUDIT:'`. Inside a GitHub job
the same line is appended to `$GITHUB_STEP_SUMMARY`, so the run's summary page says
which state it was without anyone opening the log.

Invoked directly, `scripts/audit_dependencies.py` does carry it: `0` for `CLEAN`,
`1` for `VULNERABLE`, `75` (`EX_TEMPFAIL`) for `NETWORK` and `FAILED` alike — an
audit that did not happen is never reported green, because an unaudited dependency
set called clean is the same defect facing the other way.

**Every incomplete run is retried, whatever it said.** `AUDIT_ATTEMPTS` (default
3) with a 5s/10s backoff, and `AUDIT_TIMEOUT` (default 30s) as the per-request
socket timeout, raised from pip-audit's own 15. Matching a phrase in the output
decides only whether the verdict reads `NETWORK` or `FAILED` — never whether to
try again. The two mistakes are not symmetric: re-running a deterministic failure
costs seconds and the same answer, while not re-running a transient one is the
false red on a required check that this exists to prevent. So a failure phrased in
words the list does not hold still gets its retries; it just gets a vaguer name.
Two vocabularies are in that list, because two programs reach for the network —
`uv`, fetching `pip-audit` itself on a cold tool cache, and then `pip-audit`,
fetching the advisories.

### Database

| Command | Description |
|---------|-------------|
| `make db-init` | Start PostgreSQL + create initial migration + apply |
| `make db-migrate` | Create new migration (prompts for message) |
| `make db-upgrade` | Apply pending migrations |
| `make db-check` | `alembic check` — fail if a model change has no migration. Non-destructive (it never downgrades), so unlike `test-migrations` it runs inside `make check`; needs a database at head, and skips rather than fails when none answers on 5432. The vector store's per-collection `rag_<collection>` tables are excluded from the comparison, since nothing models or migrates them — `rag_documents`, which is a model table, is not |
| `make db-downgrade` | Rollback last migration |
| `make db-current` | Show current migration revision |
| `make db-history` | Show full migration history |

### Users

| Command | Description |
|---------|-------------|
| `make create-admin` | Create admin user (interactive) |
| `make user-create` | Create new user (interactive) |
| `make user-list` | List all users |

### Prefect

Prefect runs as two containers in the dev stack — they start automatically with `make dev`:

- **`prefect-server`** — orchestration API + web UI at <http://localhost:4200>
- **`prefect-runner`** — registers the scheduled deployments and polls for work

The runner is `python -m app.worker.prefect_app`; flows live in `app/worker/tasks/`.
Open the UI to watch flow runs, inspect logs, and trigger deployments manually.
Self-hosted by default — set `PREFECT_API_KEY` (and a Cloud `PREFECT_API_URL`) to use Prefect Cloud instead.

### Docker (Development)

| Command | Description |
|---------|-------------|
| `make docker-up` | Start all backend services |
| `make docker-down` | Stop all services |
| `make docker-logs` | Follow backend logs |
| `make docker-build` | Build backend images |
| `make docker-shell` | Open shell in app container |
| `make docker-frontend` | Start frontend (separate compose) |
| `make docker-frontend-down` | Stop frontend |
| `make docker-frontend-logs` | Follow frontend logs |
| `make docker-frontend-build` | Build frontend image |
| `make docker-db` | Start only PostgreSQL |
| `make docker-db-stop` | Stop PostgreSQL |
| `make docker-redis` | Start only Redis |
| `make docker-redis-stop` | Stop Redis |

### Docker (Production with Traefik)

| Command | Description |
|---------|-------------|
| `make docker-prod` | Start production stack |
| `make docker-prod-down` | Stop production stack |
| `make docker-prod-logs` | Follow production logs |
| `make docker-prod-build` | Build production images |

### Vercel (Frontend Deployment)

| Command | Description |
|---------|-------------|
| `make vercel-deploy` | Deploy frontend to Vercel |

---

## Project CLI

All project CLI commands are invoked via:

```bash
cd backend
uv run agenticos <group> <command> [options]
```

### Server Commands

```bash
uv run agenticos server run              # Start dev server
uv run agenticos server run --reload     # With hot reload
uv run agenticos server run --port 9000  # Custom port
uv run agenticos server routes           # Show all registered routes
```

`--reload` runs uvicorn's reloader under a supervisor of our own
(`backend/cli/reload_supervisor.py`), because uvicorn's is a file watcher and
nothing more: when the kernel kills the worker — an out-of-memory kill is the
realistic way — it neither reaps it nor replaces it, so the reloader carries on
watching while no port is listening. Under the supervisor a worker killed by a
signal is replaced within about five seconds, and one that exited on its own
still waits for the edit that fixes it, which is what `--reload` is for.

It also replaces a worker that is **wedged** — alive, but with an event loop
that has stopped turning, which has no exit code and so looks healthy to every
other recovery path. The worker reports its loop through uvicorn's
`callback_notify` hook once a second, and a worker silent for fifteen seconds
across two consecutive polls is killed and replaced — about twenty-five seconds
from deadlock to serving again. Two polls rather than one because `docker pause`
and a laptop waking from sleep stop the supervisor as well as the worker, and the
first poll afterwards reads a stale beat that says nothing.
That is liveness and not readiness on purpose: the beat is a timer callback, not
a request, so a slow database cannot make a healthy server look wedged.

| | |
|---|---|
| `EVENT_LOOP_WEDGED_AFTER` | Seconds of silence before a worker is replaced. Default `15`; `0` or below switches the check off |

Switch it off while debugging. A breakpoint blocks the event loop and no probe
can tell that from a deadlock, so a worker sitting on one is replaced under you.

The same variable is read by the worker itself, which watches its own event loop
and kills its own process — that is what covers the dev and production stacks,
where there is no supervisor reading a beat from outside. One number, so
switching the check off for a breakpoint switches off both judges.
[Configuration](configuration.md#a-worker-whose-event-loop-has-stopped-turning)
has the whole picture.

`server run` also selects the `websockets-sansio` implementation in both modes.
uvicorn's `auto` picks the legacy one, which fails the handshake against
websockets >=14 with an HTTP 500 — and the dashboard chat is a WebSocket.


### Database Commands

```bash
uv run agenticos db init                  # Run all migrations
uv run agenticos db migrate -m "message"  # Create new migration
uv run agenticos db upgrade               # Apply pending migrations
uv run agenticos db upgrade --revision e3f  # Upgrade to specific revision
uv run agenticos db downgrade             # Rollback last migration
uv run agenticos db downgrade --revision base  # Rollback to start
uv run agenticos db current               # Show current revision
uv run agenticos db history               # Show migration history
```

### User Commands

```bash
# Create user (interactive prompts for email/password)
uv run agenticos user create

# Create user non-interactively
uv run agenticos user create --email user@example.com --password secret

# Also grant app-admin, which administers the whole deployment
uv run agenticos user create --email admin@example.com --password secret --superuser

# The same thing, as a shortcut
uv run agenticos user create-admin --email admin@example.com --password secret

# List all users
uv run agenticos user list
```

**There is no `--role` and no `set-role`.** A user's authority inside an
organization is a membership row plus the [permission
catalog](reference/permissions.md), granted from Users & Roles in the UI — the
`users.role` column was dropped before the migration chain was squashed. The only privilege this group
can hand out is the global one, and `--superuser` is it. To grant or revoke it
later:

```bash
uv run agenticos cmd create-app-admin user@example.com
uv run agenticos cmd create-app-admin user@example.com --revoke
```

### Custom Commands

Custom commands are auto-discovered from `app/commands/`. Run them via:

```bash
uv run agenticos cmd <command-name> [options]
```

`uv run agenticos cmd --help` lists everything the running deployment has.

### Setup and Diagnostics

```bash
# An organization, an owner, a model profile and a published agent. Idempotent.
uv run agenticos cmd bootstrap \
    --email owner@example.com --password secret \
    --org "Acme" --provider anthropic --api-key sk-ant-...

# Without a key the agent is created but cannot run
uv run agenticos cmd bootstrap --org "Acme"

# Can this deployment actually run an agent? Database, vault, a usable model,
# and every registered sandbox connection - probed one by one, credential
# included, because `/healthz` is unauthenticated and answers for a service
# holding the wrong token.
uv run agenticos cmd doctor

# Find published agents that lend a skill their publisher could not reach. The
# publish-time check on skill_ids only guards new publishes; this is the offline
# half, naming versions frozen before it that still hand a private skill to a run.
# It sweeps every version a run can load, not only the current one: each named
# environment's pinned version, each version a non-terminal run (running, or parked
# awaiting approval) still reloads, and each delegate a spec pins - the last only as
# deep as max_depth lets a run reach, so a grandchild past the ceiling is not flagged.
# Report-only - a spec is exported into a client's own git, so unbinding is a person's
# call. Exits non-zero when it finds one, so a cron can gate on it.
uv run agenticos cmd audit-skill-bindings

# Re-wrap every stored secret under the current master key - the staged rotation
# docs/secrets.md describes. Configure the old and new key side by side in
# VAULT_MASTER_KEYS first; --dry-run fully unseals every stored envelope without
# writing, so failures surface before anything moves. Exits non-zero when any row
# could not move, so a script cannot drop the old key on a partial rotation.
uv run agenticos cmd vault-rotate --dry-run
uv run agenticos cmd vault-rotate

# Install the bundled skills (refund-policy, code-review, incident-report)
uv run agenticos cmd seed-skills
uv run agenticos cmd seed-skills --org <org-id> --dry-run

# Sample data for development
uv run agenticos cmd seed --count 10 --clear
```

`make platform-bootstrap BOOTSTRAP_API_KEY=sk-...` wraps `bootstrap` with the
migrations it needs. Run `doctor` first when something works locally and not on a
fresh environment — it is faster than reading logs.

### Channel Bots

See [Channels](channels.md) for what each platform supports.

```bash
# Register a bot
uv run agenticos cmd channel-add-bot \
    --platform telegram --name "Support" --token <token> --mode jwt_linked

# Mattermost is self-hosted, so its bot carries its own server's address.
# --webhook-secret is the token Mattermost shows when the outgoing webhook is
# created; omit it to use the event stream and expose nothing.
uv run agenticos cmd channel-add-bot \
    --platform mattermost --name "Support" --token <token> \
    --api-base-url https://mattermost.acme.internal \
    --webhook-secret <token-from-mattermost>

uv run agenticos cmd channel-list-bots
uv run agenticos cmd channel-list-bots --platform telegram

# Send a test message through it - the cheapest proof the token and the
# address are right. --chat-id is a Telegram chat id or a Mattermost channel id.
uv run agenticos cmd channel-test-message --bot-id <uuid> --chat-id <chat> --text "ping"

# Webhook delivery, or delete the webhook to fall back to polling. Telegram is
# the only platform with an API for this; for Slack and Mattermost the command
# prints the URL to paste into their own settings.
uv run agenticos cmd channel-webhook-register --bot-id <uuid>
uv run agenticos cmd channel-webhook-delete --bot-id <uuid>
```

Registering a bot from the CLI is the only way on a deployment with no browser
pointed at it, which is what a Mattermost server behind a VPN usually is.

Access modes are `open`, `whitelist`, `jwt_linked` and `group_only`. A mention runs
as the *sender*, never as the bot, and an unlinked identity is refused rather than
run with no role — see [Channels](channels.md#what-every-channel-shares).

### RAG Commands

All RAG commands are custom commands invoked via `cmd`:

#### Document Ingestion

The default collection is `default`. A name whose vector table the models already
declare — `documents`, which prefixed is the ingestion tracking table — is refused
with a 400 rather than aliased onto it; see
[File processing](file-processing.md#vector-storage).

```bash
# Ingest a single file into the default collection
uv run agenticos cmd rag-ingest ./docs/guide.pdf

# Ingest a directory
uv run agenticos cmd rag-ingest ./docs/

# Ingest recursively into a specific collection
uv run agenticos cmd rag-ingest ./docs/ --collection knowledge --recursive

# Ingest with sync mode
uv run agenticos cmd rag-ingest ./docs/ --sync-mode new_only
uv run agenticos cmd rag-ingest ./docs/ --sync-mode update_only

# Skip replacing existing documents
uv run agenticos cmd rag-ingest ./docs/ --no-replace
```

#### Search

```bash
# Search the default collection
uv run agenticos cmd rag-search "what is fastapi"

# Search a specific collection
uv run agenticos cmd rag-search "deployment guide" --collection docs

# Get more results
uv run agenticos cmd rag-search "deployment" --top-k 10
```

#### Collection Management

```bash
# List all collections with stats
uv run agenticos cmd rag-collections

# Show overall RAG system statistics
uv run agenticos cmd rag-stats

# Drop a collection (with confirmation)
uv run agenticos cmd rag-drop my_collection

# Drop without confirmation
uv run agenticos cmd rag-drop my_collection --yes
```

#### Google Drive Sync

```bash
# Sync from Google Drive root
uv run agenticos cmd rag-sync-gdrive --collection docs

# Sync from a specific folder
uv run agenticos cmd rag-sync-gdrive --collection docs --folder-id abc123
```

#### S3/MinIO Sync

```bash
# Sync from S3 bucket root
uv run agenticos cmd rag-sync-s3 --collection docs

# Sync from a specific prefix (folder)
uv run agenticos cmd rag-sync-s3 --collection docs --prefix documents/

# Sync from a specific bucket
uv run agenticos cmd rag-sync-s3 --collection docs --bucket my-bucket
```


#### Sync Source Management

```bash
# List configured sync sources
uv run agenticos cmd rag-sources

# Add a new sync source. `--org` is required and the collection has to be one
# that organization already holds: a sync *writes into* the collection it names,
# so a source pointing at a name nobody owns fails later in a worker, and one
# pointing at another tenant's is an injection rather than a read.
uv run agenticos cmd rag-source-add \
    --name "My Drive" \
    --type gdrive \
    --org 0c8f2b1e-... \
    --collection docs \
    --config '{"folder_id": "abc123"}' \
    --sync-mode new_only \
    --schedule 60

# Remove a sync source
uv run agenticos cmd rag-source-remove <source-id>
uv run agenticos cmd rag-source-remove <source-id> --yes  # Skip confirmation

# Trigger sync for a specific source
uv run agenticos cmd rag-source-sync <source-id>

# Trigger sync for all active sources
uv run agenticos cmd rag-source-sync --all
```

`rag-source-sync` **waits for the syncs it starts**, up to an hour, and says so
while it does. The sync itself runs in a background task, and the command's
process ends when its coroutine returns — so a command that only triggered and
exited was cancelling the work it had just reported as started. Over the API
that task belongs to a long-lived worker and nothing has to wait for it.

## Adding Custom Commands

Commands are auto-discovered from `app/commands/`. Create a new file:

```python
# app/commands/my_command.py
import click
from app.commands import command, success, error

@command("my-command", help="Description of what this does")
@click.option("--name", "-n", required=True, help="Name parameter")
def my_command(name: str):
    """Your command logic here."""
    success(f"Done: {name}")
```

Run it:

```bash
uv run agenticos cmd my-command --name test
```

For more details, see `docs/adding_features.md`.
