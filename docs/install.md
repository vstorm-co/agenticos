# Install

Three commands to a running agent, on macOS, Linux or WSL2.

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

## The short way

```bash
git clone https://github.com/vstorm-co/agenticos && cd agenticos
make dev
make platform-bootstrap BOOTSTRAP_API_KEY=sk-...
```

Then open <http://localhost:3000> and sign in as `admin@example.com` /
`admin123`.

`make dev` builds the backend image, starts Postgres, Redis, the API, the worker
and the frontend, waits for the database to accept connections and applies
pending migrations. It is idempotent - re-run it after any code or config change.

`make platform-bootstrap` creates an organization, an owner, a model profile and
a working agent called `@getting-started`. Also idempotent: re-run it whenever
you are not sure it worked.

!!! tip "No provider key yet?"

    Leave `BOOTSTRAP_API_KEY` out. Everything is still created, and the demo
    agent is saved as a **draft** rather than published - because an agent with
    no model cannot answer, and publishing one that fails on its first message is
    worse than not publishing it. Add a key under **Settings → AI providers**,
    then publish.

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

## Running the backend on the host

Useful for breakpoints and IDE debugging - the services stay in Docker, the API
does not.

```bash
make install                                            # uv sync + pre-commit
docker compose -f docker-compose.dev.yml up -d db redis
make db-upgrade                                         # apply migrations
make run                                                # uvicorn --reload
```

!!! note "Interpreter versions differ"

    Local development runs Python 3.14 while `backend/Dockerfile`,
    `pyproject.toml` and CI all target 3.12. Something verified locally has been
    verified on a newer interpreter than the one that ships.

## Environments

| Target | Compose file | Use |
|---|---|---|
| `make dev` | `docker-compose.dev.yml` | Local development, hot reload, bind-mounted source |
| `make stage` | `docker-compose.yml` | Production-like build with no bind mounts, on localhost |
| `make prod` | `docker-compose.prod.yml` | Production. Needs `backend/.env` and an external Nginx using `nginx/nginx.conf`. |

Each has matching `-down`, `-logs` and `-rebuild` siblings.

See [Configuration](configuration.md) for every setting, and
[Deploying](deploy.md) for production.

## Next

- [Your first agent](first-agent.md) - from a key to a metered, published agent.
- [Concepts](concepts.md) - what a spec, a version and an exposure are.
