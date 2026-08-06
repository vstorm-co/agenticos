# Install

Four commands to a running agent, on macOS, Linux or WSL2. Every step below is
idempotent - re-run any of them whenever you are not sure it worked.

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| **Docker** | Desktop / Engine 24+ | <https://docs.docker.com/get-docker/> |
| **Make** | GNU Make 3.81+ | Preinstalled on macOS and Linux. On Windows use WSL2. |
| **uv** | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **bun** | 1.x | `curl -fsSL https://bun.sh/install \| bash` |

!!! warning "Windows"

    The Makefile and shell helpers assume bash. Use **WSL2** or **Git Bash**.
    The Docker workflow is identical once you are in one.

## Step by step

### 1. Clone it

```bash
git clone https://github.com/vstorm-co/agenticos && cd agenticos
```

**There is no `.env` to write first.** Every variable in `docker-compose.yml`
carries a default, deliberately, so the stack starts on a clean checkout. One
value is generated rather than defaulted: `make dev` runs `make sandbox-token`
first, which appends a fresh `SANDBOXD_TOKEN` to `backend/.env` if there is not
one there already. The sandbox service refuses to start without it - it can run
commands on this host, so an empty default would be a shared secret of `""`.
Generated once and left alone afterwards; regenerating it would orphan every
workspace the service is holding.

If you want to change anything - a provider key on the host, a different
database name - copy `backend/.env.example` to `backend/.env` and edit it. The
generated token is appended to whatever is there.

### 2. Start the backend stack

```bash
make dev
```

Builds the backend image, starts **Postgres (pgvector), Redis, the API, the
Prefect server and runner, and the sandbox service**, waits for the database to
accept connections, and applies pending migrations. Migrations are a no-op when
already at head, so this is the command to re-run after any code or config
change.

### 3. Start the frontend

```bash
make dev-frontend      # or: cd frontend && bun dev
```

**A separate command, and not an oversight.** `make dev` uses
`docker-compose.yml` only; the Next.js container lives in
`docker-compose.frontend.yml` so that working on the API does not rebuild a
frontend image, and so a developer running `bun dev` on the host is not fighting
a container for port 3000.

### 4. Create an organization, an owner, a model and an agent

```bash
make platform-bootstrap BOOTSTRAP_API_KEY=sk-...
```

This is the one that turns an empty database into something you can use. An empty
AgenticOS is a chicken-and-egg problem - an agent needs a model, a model needs a
key, a key needs an organization - and this walks that chain once:

| It creates | |
|---|---|
| An organization | `Acme`, or `--org` |
| An owner | `admin@example.com` / `admin123`, or `--email` / `--password` |
| A vault entry | Your provider key, sealed for that organization |
| A model profile | `gpt-4.1`, `claude-sonnet-4-6`, `gemini-2.5-pro` or `openai/gpt-4.1`, whichever provider the key is for |
| An agent | `@getting-started`, published if there is a key |

Then open <http://localhost:3000>, sign in as `admin@example.com` / `admin123`,
and open **Agents → Getting Started → Test**.

!!! tip "No provider key yet?"

    Leave `BOOTSTRAP_API_KEY` out. Everything is still created, and the demo
    agent is saved as a **draft** rather than published - because an agent with
    no model cannot answer, and publishing one that fails on its first message is
    worse than not publishing it. Add a key under **Settings → AI providers**,
    then publish.

!!! note "`make seed` is a different thing"

    It creates `admin@example.com` as a deployment superadmin and nothing else -
    no organization, no model, no agent. `make platform-bootstrap` creates that
    user too, so on a fresh install you want bootstrap. `make dev` prints a
    suggestion to run `seed`; it is the older path and still valid if all you
    want is an admin login.

### 5. Check it can actually run an agent

```bash
cd backend && uv run agenticos cmd doctor
```

Asks the questions a first message would: is the database reachable and at head,
does the vault decrypt, is there a model profile with a key behind it, and does
every registered sandbox connection answer with a runtime. Each line says which
part is missing rather than that something failed.

## When it does not come up

| What you see | Why |
|---|---|
| Ingestion 500s with `extension "vector" is not available` | Stock Postgres instead of `pgvector/pgvector:pg16`. See below |
| `uv run` reports Python 3.13 or 3.14 | `backend/.venv` resolved past the pin. Delete it and re-run `uv sync` |
| The frontend loads but every request fails | Step 3 without step 2, or the API is still applying migrations. `make dev-logs` |
| `agenticos_sandboxd` exits immediately | No `SANDBOXD_TOKEN` in `backend/.env`. `make sandbox-token`, then `make dev` |
| Files says `This host's files could not be read` and names `workspace_root` | A sandbox service started before it had one. Recreate it - `docker compose -f docker-compose.yml --profile sandbox up -d sandboxd` - and `docker rm` the leftover `sandboxd-*` containers: a persisted container is reattached with the mounts it was created with, so an old session keeps writing where nothing can read it |
| A port is already taken (3000, 5432, 6379, 8000, 4200) | Something else is on it. `make dev-down`, stop the other process, start again |
| Anything stranger | `make docker-clean` wipes containers, networks **and volumes** - all local data - then `make dev` from scratch |

## The database must be pgvector

Not stock Postgres. The retrieval store issues
`CREATE EXTENSION IF NOT EXISTS vector` the first time a collection is written
to, and stock Postgres answers `extension "vector" is not available` - a 500
before any row is committed.

Every compose file in this repository pins `pgvector/pgvector:pg16`. If document
ingestion 500s on a fresh environment, check the image first.

## Day to day

```bash
make dev           # start or restart (idempotent)
make dev-down      # stop everything
make dev-logs      # tail logs
make dev-rebuild   # force-rebuild the backend image after a pyproject change
make dev-frontend  # start the Next.js container on its own
```

Where things are:

| | |
|---|---|
| Frontend | <http://localhost:3000> |
| API | <http://localhost:8000> |
| OpenAPI docs | <http://localhost:8000/docs> |
| Django-style admin | <http://localhost:8000/admin> |
| Prefect UI | <http://localhost:4200> |
| Postgres | `localhost:5432` (`agenticos` / `agenticos`) |
| Redis | `localhost:6379` |

The sandbox service is deliberately **not** published. It holds the Docker
socket, which is an unauthenticated API for root on the host, so it is reachable
only from inside the compose network - the API proxies what a browser needs to
see of it.

## Running the backend on the host

Useful for breakpoints and IDE debugging - the services stay in Docker, the API
does not.

```bash
make install                                    # uv sync + pre-commit
docker compose -f docker-compose.yml up -d db redis
make db-upgrade                                 # apply migrations
make run                                        # uvicorn --reload, supervised
```

!!! note "The reloader is supervised"

    `--reload` runs under `backend/cli/reload_supervisor.py` rather than
    uvicorn's reloader alone. Uvicorn's watches files and nothing else, so a
    worker the kernel kills — an out-of-memory kill being the realistic way — is
    neither reaped nor replaced: the reloader keeps watching while no port is
    listening, and inside a container that means PID 1 is still alive,
    `docker ps` still says `Up`, and the restart policy has nothing to act on.
    A worker killed by a signal is now replaced within about five seconds. One
    that exited on its own still waits for the edit that fixes it.

    This is the reload path only. `make dev-server` runs a single unsupervised
    uvicorn, so a kill takes PID 1 with it and `restart: unless-stopped`
    restarts the container; `make prod` runs `--workers 4`, where uvicorn's own
    `Multiprocess` supervisor already replaces a dead worker twice a second.

!!! note "Python is pinned to 3.12"

    `backend/.python-version` pins it, matching `requires-python`,
    `backend/Dockerfile` and every CI job. If `uv run python -V` reports anything
    else, delete `backend/.venv` and re-run `uv sync` — a newer interpreter has
    reachable APIs that the one which ships does not.

## Environments

Three, one compose file each, with a matching frontend file beside it.

| Target | Compose files | Use |
|---|---|---|
| `make dev` | `docker-compose.yml`<br>`docker-compose.frontend.yml` | Local. Hot reload, bind-mounted source, Postgres and Redis published to the host |
| `make dev-server` | `docker-compose-dev.yml`<br>`docker-compose-dev.frontend.yml` | A deployed dev environment. Built images, no bind mounts, no database port, verbose logging |
| `make prod` | `docker-compose-prod.yml`<br>`docker-compose-prod.frontend.yml` | Production. Resource limits, internal data network, 4 workers |

Each has matching `-down`, `-logs` and `-frontend` siblings. `make stage` is kept
as an alias for `make dev-server`, which is what it used to be.

Both deployed environments want a reverse proxy in front of them;
`nginx/nginx.conf` is the template and resolves `backend:8000` and
`frontend:3000` as network aliases.

!!! warning "`NEXT_PUBLIC_*` are build arguments"

    Next inlines them into the browser bundle, so the dev-server and production
    frontend files require `PUBLIC_API_URL`, `PUBLIC_WS_URL` and
    `PUBLIC_SITE_URL` at **build** time and refuse to start without them.
    Changing one means rebuilding the image, not restarting it — otherwise
    server-side rendering keeps working while every call from the browser goes to
    whatever hostname was baked in.

See [Configuration](configuration.md) for every setting, and
[Deploying](deploy.md) for production.

## Next

- [Your first agent](first-agent.md) - from a key to a metered, published agent.
- [Concepts](concepts.md) - what a spec, a version and an exposure are.
