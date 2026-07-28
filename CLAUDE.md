# CLAUDE.md

## Project Overview

**agenticos** - FastAPI application generated with [Full-Stack AI Agent Template](https://github.com/vstorm-co/full-stack-ai-agent-template).

**Stack:** FastAPI + Pydantic v2, PostgreSQL (async via asyncpg)
, JWT + API Key auth, Redis, PydanticAI, RAG (pgvector), Next.js 15 (i18n)

## Commands

```bash
# Backend
cd backend
uv run uvicorn app.main:app --reload --port 8000
uv run pytest
uv run pytest tests/test_file.py::test_name -v
uv run ruff check . --fix && uv run ruff format .
uv run ty check

# Database migrations
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "Description"

# Frontend
cd frontend
bun dev
bun test
bun run lint

# Docker
docker compose up -d

# RAG
uv run agenticos rag-collections
uv run agenticos rag-ingest /path/to/file.pdf --collection docs
uv run agenticos rag-search "query" --collection docs
uv run agenticos rag-sync-gdrive --collection docs
uv run agenticos rag-sync-s3 --collection docs

# Sync Sources
uv run agenticos cmd rag-sources
uv run agenticos cmd rag-source-add
uv run agenticos cmd rag-source-sync
```

## Testing

### The commands

```bash
make platform-bootstrap  # fresh install -> a running agent (idempotent)
make test              # backend + the 100% coverage gate on the platform layer
make test-fast         # no coverage, for the write-run-write loop
make test-integration  # only the tests that need a real database
make test-cov          # HTML report at backend/htmlcov/index.html
make coverage-all      # including template-inherited code (informational)
make test-frontend     # vitest: unit + integration
make test-e2e          # playwright
make test-migrations   # apply and roll back the whole chain against Postgres
make check             # what CI runs — do this before opening a PR
```

**The database must be `pgvector/pgvector:pg16`, not stock Postgres.** The RAG
store issues `CREATE EXTENSION IF NOT EXISTS vector` the first time a collection
is written to, and stock Postgres answers `extension "vector" is not available`
— a 500 before any row is committed. Every compose file and both CI jobs pin the
pgvector image; they used to pin `postgres:16-alpine`, which is why no ingestion
path had ever been exercised locally or in CI and an E2E upload spec sat skipped.
If document ingestion 500s on a fresh environment, check the image first.

Note that local development runs Python 3.14 while `backend/Dockerfile`,
`pyproject.toml` and CI all target 3.12. Something verified locally has been
verified on a newer interpreter than the one that ships.

### What is held to 100%, and why not everything

The **platform layer** — everything AgenticOS adds on top of the generated
template — is at 100% and CI fails below it. That is `app/agents/`, the
permission catalog, the vault, and the services built on them. The exact list
lives in `[tool.coverage.run]` in `backend/pyproject.toml`; adding a module to
the platform layer means adding it there.

Two things about that config are worth knowing before you edit it. `source`
entries are module names or directories — a file path is silently ignored with a
`module-not-imported` warning, so a whole file can drop out of the gate without
the build noticing. And where a directory mixes our code with the generator's
(`app/commands`), the generator's files are listed in `omit` individually rather
than the directory being excluded wholesale.

Template-inherited subsystems (the RAG pipeline, connectors, channel adapters,
worker tasks) are reported by `make coverage-all` but do not gate the build.
Holding code we did not design to the same bar would mean writing mock-heavy
tests over its internals, which buys a coverage number rather than confidence.
When we take ownership of one of those subsystems, it moves into the gated list.

### The layers, and what belongs in each

**Unit** (`backend/tests/test_*.py`) — one module, dependencies mocked at the
repository boundary. Most tests live here. Mock repositories, never the service
under test.

**Integration** (`backend/tests/integration/`) — a real database, real
migrations, real transactions. This is where multi-tenant isolation, check
constraints and cascade behaviour get verified; a mock cannot tell you that a
`CHECK` actually rejects a row.

**API** (`backend/tests/api/`) — through the FastAPI app with dependency
overrides. Verifies that a route is wired to the right permission and returns
the right status, not that the service logic is correct.

**Frontend unit** (`frontend/src/**/*.test.ts[x]`) — vitest. Stores, hooks and
pure functions.

**Frontend integration** (`frontend/src/**/*.integration.test.tsx`) — Testing
Library against a mocked API. Verifies that a permission actually hides a
button and that a form submits what it claims to.

**E2E** (`frontend/e2e/`) — Playwright against a running stack. Reserved for
journeys that cross the whole system: sign in, build an agent, publish it, run
it, approve a tool call.

Playwright starts the frontend; the backend, its migrations and
`agenticos cmd bootstrap` are the precondition (`make test-e2e` checks for one
and says so). Bootstrap is the fixture the suite asserts against — an owner, an
organization, a model profile and the published agent `@getting-started` —
and `e2e/seed.setup.ts` adds through the UI what bootstrap deliberately does
not: a skill, a knowledge base, a draft agent, a stored key and a second member.

**An E2E test must assert on something the seed put there.** Every page in this
product renders its empty state when a query fails, so "No skills yet" and "the
skills request answered 502" are the same screen: a spec that asserts a heading
and a button passes against a backend that was never started, which is exactly
how this suite spent months testing the login page. Where a resource genuinely
has no seeded row — Activity, which needs a real provider key to have a run —
assert the response instead. The `test` in `e2e/fixtures.ts` fails any test
whose page took a 5xx from `/api/*`; it is a net, not a substitute for
asserting on data. Prove a new spec can fail by pointing `BACKEND_URL` at a
dead port before you trust it.

### How to write one that is worth keeping

A test earns its place by failing when the behaviour changes. In practice:

- **Name the behaviour, not the function.** `test_a_failed_run_still_records_its_cost`
  says what breaks if it regresses; `test_finish` does not.
- **Assert the consequence.** Not "the repository was called" but "the cost
  written was $2.00".
- **The docstring says why it matters**, when that is not obvious from the name.
  A future reader deciding whether to delete a failing test needs that sentence.
- **Cover the refusal, not just the success.** Most of the platform's value is
  in what it refuses: a cross-tenant read, an ungranted scope, a second decision
  on a decided approval.
- **No test for a mock.** If removing the implementation still passes, delete it.

### Things worth testing here specifically

This platform has a few invariants that are easy to break and expensive to get
wrong. When touching these areas, test them directly:

- **Tenant isolation.** Every org-scoped resource must be unreachable from
  another organization — including when the caller owns the row.
- **Permission scopes.** `own`, `shared`, `all` behave differently per role, and
  a resource grant widens access for one row without promoting the member.
- **Budget enforcement.** The check happens *before* a model request; a run that
  fails still records what it spent.
- **Spec validation.** A spec that references something missing is refused at
  publish, never at run time.
- **Secrets.** No API response, log line or audit entry may contain a plaintext
  key. The vault's tenant binding must reject a ciphertext from another org.
- **Channel mentions.** `@slug` resolves only inside the bot's organization and
  runs as the *sender*, never as the bot. An unlinked identity is refused, not
  run with no role.
- **What a parser claims it reads.** `GET /rag/supported-formats` and the upload
  validator answer from `PARSER_FORMATS`; `DocumentProcessor.process_file` is
  what actually routes. When those two disagree the upload is *accepted* — file
  stored, document row committed, task dispatched — and dies in a worker, so the
  document sits in the listing with no explanation. `tests/test_supported_formats.py`
  pins each parser's set against what the pipeline can route, in both
  directions. Widen a format set and that test is what tells you the parser was
  never taught to read it.
- **Tightening a constraint on a field already stored as JSON.** `IngestionConfig`
  lives in a JSONB column, so a narrower rule does not only reject new input —
  it makes existing rows unreadable, and a Pydantic model that refuses to
  validate one field of one row takes down the whole listing endpoint with a
  500. Adding a field is safe (missing keys take their default); narrowing an
  existing one needs a data migration in the same change. `0046_ocr_tesseract`
  is the worked example: `ocr_language` went from anything 2–16 characters to
  Tesseract's `^[a-z]{3}(\+[a-z]{3})*$`, and every row written before it held
  `"en"`.
- **A document that parses to nothing.** Silently indexing an empty result is
  indistinguishable, afterwards, from a document that ingested fine and simply
  never matches. Markdown reconstruction returns an empty fenced block rather
  than whitespace for an unreadable scan, so `.strip()` is not the check.

`app/services/rag/*` is template-inherited and outside the coverage gate, which
is exactly why the invariants above are pinned by explicit tests rather than left
to a percentage: three format lists disagreed there for months without anything
failing.


## Hard Boundaries

Non-obvious rules that are easy to violate and cross-cutting enough to state up front:

- Repositories use `db.flush()` + `db.refresh()`, **never** `db.commit()` — the session auto-commits via `get_db_session`.
- Routes call services only — **never** import or call repositories directly.
- **`require(...)` gates belong on collection routes, not per-resource ones.** Listing, creating and reading catalogs carry a role gate; anything acting on *one* agent, skill or collection must not. A role gate cannot see the grants on a row, so it refuses a Viewer holding an explicit `edit` grant before `resolve_access` ever widens their access — which contradicts "a grant widens what a role allows; it never narrows it". Per-resource routes hand the decision to a service that calls `resolve_access`. `tests/api/test_platform_routes.py` enforces both halves.
- Route handlers return `-> Any`; serialization is handled by `response_model` (avoids double Pydantic validation).
- `datetime.now(UTC)`, never `datetime.utcnow()`.
- `secrets.compare_digest()` for API key comparison, never `==`.

## Detailed Conventions

Path-scoped guidance lives in `.claude/rules/*` and loads automatically when you edit matching files — it is intentionally NOT repeated here:

- `architecture.md` — Routes → Services → Repositories, dependency injection, thin vs. thick domains
- `schemas-models.md` — Pydantic v2 schemas (`*Create`/`*Update`/`*Read`/`*List`), SQLAlchemy models
- `api-conventions.md` — REST structure, status codes, response format, pagination, auth
- `exceptions-security.md` — domain exceptions (`NotFoundError`, etc.), JWT, RBAC
- `code-style.md` — formatting, naming, imports, type hints
- `testing.md` — test structure, fixtures, async patterns
- `frontend.md` — Next.js 15 conventions

Longer-form docs: `docs/architecture.md`, `docs/adding_features.md`, `docs/testing.md`, `docs/patterns.md`.
