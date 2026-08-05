# Commands Reference

This project provides commands via two interfaces: **Make** targets for common
workflows and a **project CLI** for fine-grained control.

## Make Commands

Run these from the project root directory.

### Quick Start

| Command | Description |
|---------|-------------|
| `make quickstart` | Install deps, start Docker, run migrations, create admin user |
| `make install` | Install backend dependencies with uv + pre-commit hooks |

### Development

| Command | Description |
|---------|-------------|
| `make run` | Start development server with hot reload |
| `make run-prod` | Start production server (0.0.0.0:8000) |
| `make routes` | Show all registered API routes |
| `make test` | Backend suite plus the 100% gate on the platform layer |
| `make test-cov` | Run tests with coverage report (HTML + terminal) |
| `make format` | Auto-format code — ruff on the backend, prettier on the frontend |
| `make lint` | Every static check: ruff, ruff format, ty, eslint, prettier, tsc, the backtick and i18n guards, and codespell over the whole tree |
| `make lint-backend` / `make lint-frontend` | One half of the above. CI runs them in two different jobs, so either can be run on its own |
| `make lint-spelling` | codespell over every tracked file. The pre-commit hook reads only the files a commit touches, so a misspelling that lands with its file waits there to refuse somebody else's unrelated commit |
| `make build-frontend` | `next build`. Type-checks the route tree and fails on a server component that cannot render — which neither tsc nor vitest sees |
| `make audit` | Audit the locked dependency set for known vulnerabilities (needs the network) |
| `make clean` | Remove cache files (__pycache__, .pytest_cache, etc.) |

### Before a pull request

`make check` is every CI job except one, and the equality is deliberate rather
than approximate: `.github/workflows/ci.yml` calls these same Make targets rather
than repeating their commands, and `backend/tests/test_ci_parity.py` fails if a
gating job grows a step `check` does not run — or the reverse.

```bash
make check   # lint, test, test-frontend-cov, build-frontend, docs-build, audit
```

About five minutes, serial, on a warm cache. What it deliberately leaves out:

| Not in `check` | Why, and what to run instead |
|---|---|
| `e2e` | Needs a migrated database, a seeded organization and a running backend: `make dev && make platform-bootstrap && make test-e2e` |
| The image build and Trivy scan | CI runs those only on a push to `main` |
| `make test-migrations` | CI cycles the chain against a throwaway `test_db`. On a laptop `alembic downgrade base` points at whatever `backend/.env` says, which is usually the database with your own work in it |

One gap no command can close: CI's `test` job has a Postgres beside it, so
`tests/integration/` runs there, and locally it skips itself when nothing answers
on 5432. `make check` says so at the end when that happens — `make docker-db`
first if the change is anywhere near the database.
| `make sandbox-token` | Generate the sandbox service's own `SANDBOXD_TOKEN` into `backend/.env`, once. `make dev` runs it for you; it never regenerates, because a new token orphans every workspace the service is holding. The connection form offers to store the same value in the vault, so it does not have to be pasted anywhere |


### Database

| Command | Description |
|---------|-------------|
| `make db-init` | Start PostgreSQL + create initial migration + apply |
| `make db-migrate` | Create new migration (prompts for message) |
| `make db-upgrade` | Apply pending migrations |
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
`users.role` column was dropped in migration `0066`. The only privilege this group
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

uv run agenticos cmd channel-list-bots
uv run agenticos cmd channel-list-bots --platform telegram

# Send a test message through it
uv run agenticos cmd channel-test-message --bot-id <uuid> --chat-id <chat> --text "ping"

# Webhook delivery, or delete the webhook to fall back to polling
uv run agenticos cmd channel-webhook-register --bot-id <uuid>
uv run agenticos cmd channel-webhook-delete --bot-id <uuid>
```

Access modes are `open`, `whitelist`, `jwt_linked` and `group_only`. A mention runs
as the *sender*, never as the bot, and an unlinked identity is refused rather than
run with no role — see [Channels](channels.md#what-every-channel-shares).

### RAG Commands

All RAG commands are custom commands invoked via `cmd`:

#### Document Ingestion

```bash
# Ingest a single file
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

# Add a new sync source
uv run agenticos cmd rag-source-add \
    --name "My Drive" \
    --type gdrive \
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
