# CLAUDE.md — AgenticOS

Always-loaded brief. Everything else is loaded on demand: `.claude/rules/*` by the
files you edit, `.claude/skills/*` by the task you are doing, `docs/*` when you need to
know how something works. **This file is deliberately short — if a section here grows
past a screen, it belongs in one of those three.**

## What this is

The operating system for a company's AI agents. Self-hosted, open source, multi-tenant.

**An agent here is data, not code.** Instructions, a model, a set of capabilities, a
budget. Somebody builds it in a UI, publishes a version, and it runs the same way
everywhere — web chat, HTTP API, Slack, Telegram, an embedded widget.

That one sentence is the whole design, and nearly every wrong assumption about this
codebase comes from missing it:

- There is **no** `@agent.tool`, no `RunContext[Deps]`, no `app/agents/assistant.py`.
  Every tool reaches a model through the capability registry.
- Agent behaviour is **not** changed by editing Python. It is changed by editing a
  spec, which is versioned on publish and exportable as YAML into a client's own git
  repository.
- The platform's value is mostly in what it **refuses**: a cross-tenant read, an
  ungranted scope, a budget breach, a second decision on a decided approval. Code that
  only handles the happy path is not finished.

**Stack:** FastAPI + Pydantic v2 · PostgreSQL (asyncpg, pgvector) · Redis ·
[Pydantic AI](https://ai.pydantic.dev) for the agent runtime · Prefect for background
work · Next.js 15 + React 19 (bun, `next-intl`) · MkDocs Material.

Generated from the [Full-Stack AI Agent Template](https://github.com/vstorm-co/full-stack-ai-agent-template),
which is why "the platform layer" and "template-inherited" are distinctions that matter
below.

## The quality bar

Top-tier open source. "Works" is not the bar; "a maintainer would merge this without
changes" is. Concretely, in this repo:

- **Full typing, no escapes.** No `Any` as a shortcut, no `# type: ignore` or
  `ty: ignore` without a comment saying what holds it true.
- **Errors are explicit.** Domain exceptions with `message` and `details`. Never swallow
  an exception, never add a fallback that papers over a bug.
- **No dead weight.** No speculative abstraction, unused parameter, commented-out code
  or "just in case" branch. If a branch cannot be reached, delete it; if it can, test it.
- **Reasoning lives in docstrings.** The reference docs are generated from them, so a
  decision explained in a commit message is a decision nobody will find.
- **Scoped diffs.** Fix what was asked. Propose follow-ups instead of taking them.
- **Tests are part of the change.** New behaviour ships with a test; a bug ships with a
  regression test that fails without the fix.

## Hard boundaries

Easy to violate, cross-cutting, and each one has been violated here at least once.

- Repositories use `db.flush()` + `db.refresh()`, **never** `db.commit()` — the session
  auto-commits via `get_db_session`.
- Routes call services only — **never** import or call a repository directly.
- **`require(...)` gates belong on collection routes, not per-resource ones.** Listing,
  creating and reading catalogs carry a permission gate; anything acting on *one* agent,
  skill or collection must not. A role gate cannot see the grants on a row, so it
  refuses a Viewer holding an explicit `edit` grant before `resolve_access` ever widens
  their access — which contradicts "a grant widens what a role allows; it never narrows
  it". Per-resource routes hand the decision to a service that calls `resolve_access`.
  `tests/api/test_platform_routes.py` enforces both halves.
- Route handlers return `-> Any`; `response_model` does the serialization (avoids double
  Pydantic validation).
- Every secret at rest goes through `app/core/vault.py`. **There is no second
  mechanism**, and adding one is the defect migration `0038` removed.
- `datetime.now(UTC)`, never `datetime.utcnow()`.
- `secrets.compare_digest()` for API key comparison, never `==`.
- **Do not reintroduce what was deliberately removed:** `UserRole`, `User.has_role()`,
  `RoleChecker`, `CurrentAdmin`, `CurrentSuperuser` (dropped in `0066` — authority
  inside an organization is a membership row plus the permission catalog), or
  `CHANNEL_ENCRYPTION_KEY` and the deployment-wide Fernet keys (dropped in `0038`).

## Read the matching rule before writing code

`.claude/rules/*` is path-scoped, each file declaring the `globs` it applies to. This is
mandatory, not aspirational — when your instinct and the rule disagree, the rule wins.

| Editing | Read |
|---|---|
| Any `backend/app/**` Python | `architecture.md` — Routes → Services → Repositories, DI, thin vs. thick domains |
| `schemas/`, `db/models/` | `schemas-models.md` — `*Create`/`*Update`/`*Read`/`*List`, SQLAlchemy |
| `api/` | `api-conventions.md` — REST structure, status codes, pagination, auth aliases |
| `core/`, `services/` | `exceptions-security.md` — domain exceptions, JWT, the permission model |
| Any Python | `code-style.md` — formatting, naming, imports, type hints |
| `tests/` | `testing.md` — the layers, anyio, fixtures, the 100% gate |
| `frontend/` | `frontend.md` — App Router, data layer, stores, i18n, permissions |

## Invoke the matching skill before starting a task

`.claude/skills/*` is task-scoped. Each routes to the relevant `docs/` page and adds
what a page does not carry: which shape the work should take, and which failures are
silent. `.claude/README.md` lists all thirteen and explains the layout.

| Doing | Skill |
|---|---|
| Giving an agent a new tool, or a capability | `agent-capability` |
| Changing `AgentSpec`, `SPEC_VERSION` or publish validation | `agent-spec` |
| Anything authorization | `permissions-rbac` |
| Anything with a credential at rest | `vault-secrets` |
| MCP servers, or an integration with a SaaS product | `mcp-connections` |
| Ingestion, retrieval, connectors, parsers | `rag-knowledge` |
| Telegram / Slack / Mattermost | `channel-bot` |
| Prefect flows, or work that outlives a request | `background-task` |
| A schema change or a backfill | `alembic-migration` |
| Backend tests, or a failing coverage gate | `backend-tests` |
| A Playwright spec | `e2e-tests` |
| A page, store, hook or permission-gated control | `frontend-feature` |
| The docs site | `project-docs` |

## Commands

```bash
make dev                                          # postgres, redis, api, worker, frontend
make platform-bootstrap BOOTSTRAP_API_KEY=sk-...  # an org, an owner, a model, an agent
make check                                        # what CI runs — before every PR
```

`make help` lists the rest. Day to day:

| | |
|---|---|
| `make lint` / `make format` | ruff + ty, backend and frontend |
| `make test-fast` | no coverage — the write-run-write loop |
| `make test` | backend + the 100% gate on the platform layer |
| `make test-integration` | only the tests needing a real database |
| `make test-frontend` / `make test-e2e` | vitest / Playwright |
| `make test-migrations` | the whole chain forwards and back |
| `make db-migrate` / `make db-upgrade` | autogenerate / apply |
| `make docs` / `make docs-build` | serve on :8001 (`DOCS_PORT=` to move it) / `--strict` |
| `uv run agenticos cmd doctor` | can this deployment actually run an agent? |
| `uv run agenticos cmd --help` | every custom command, including all `rag-*` |

## Environment gotchas

**The database must be `pgvector/pgvector:pg16`, not stock Postgres.** The RAG store
issues `CREATE EXTENSION IF NOT EXISTS vector` the first time a collection is written
to, and stock Postgres answers `extension "vector" is not available` — a 500 before any
row is committed. Every compose file and both CI jobs pin the pgvector image; they used
to pin `postgres:16-alpine`, which is why no ingestion path had ever been exercised
locally or in CI and an E2E upload spec sat skipped. **If document ingestion 500s on a
fresh environment, check the image first.**

**Local development runs Python 3.14; `backend/Dockerfile`, `pyproject.toml` and every
CI job target 3.12.** Something verified locally has been verified on a newer
interpreter than the one that ships.

## Testing — what a first reader must know

Layers, fixtures and patterns are in `docs/testing.md`, `.claude/rules/testing.md` and
the `backend-tests` / `e2e-tests` skills. Four things belong here because they change
what you do before you write a line:

**The platform layer is at 100% and CI fails below it.** Everything AgenticOS adds on
top of the template: `app/agents/**`, the permission catalog, the vault, the secret
kinds, the catalogs, and the services and repositories built on them. Template-inherited
subsystems (the RAG pipeline, connectors, channel adapters, worker tasks) are reported by
`make coverage-all` but do not gate the build — holding code we did not design to the
same bar would buy a coverage number rather than confidence.

**Adding a module to the platform layer means editing two lists**, both in
`backend/pyproject.toml`: `[tool.coverage.run] include` and `[[tool.ty.overrides]]
include`, verbatim and in the same order. A module held to 100% coverage is held to the
type checker too. `tests/test_coverage_gate.py` fails if they drift, and
`references/coverage-gate.md` in the `backend-tests` skill explains why the config uses
`include` rather than `source`.

**Async tests use anyio** — `pytestmark = pytest.mark.anyio`. `@pytest.mark.asyncio`
does not work here.

**Cover the refusal.** Tenant isolation (including when the caller owns the row) ·
permission scopes and grants · a budget checked *before* the model request and recorded
even when the run fails · a spec refused at publish, never at run time · no plaintext
secret in any response, log or audit entry · a channel mention running as the sender ·
what a parser claims it reads versus what the pipeline routes · narrowing a rule on a
field already stored as JSONB. The `backend-tests` skill has the worked examples and the
history behind each.

## Documentation

`docs/` is both the published site and the repository's own engineering notes — **one
copy, on purpose.** A second copy written for a different reader is a copy that
disagrees. So: when behaviour changes, change the page; do not write a second
explanation next to it.

| Topic | Page |
|---|---|
| Spec, version, exposure, run | `docs/concepts.md` |
| The three permission layers, scopes, grants | `docs/permissions.md` |
| Budgets, approvals, alerts, audit | `docs/governance.md` |
| What ships as a capability, its tools and config | `docs/reference/capabilities.md` |
| The agent spec, field by field | `docs/reference/spec.md` |
| MCP connections, the server catalog, OAuth | `docs/mcp.md` |
| Providers, model profiles, fallbacks, cost | `docs/models.md` |
| The vault, secret kinds, what never leaks | `docs/secrets.md` |
| Skills — format, library, skills vs knowledge | `docs/skills.md` |
| Surfaces: widget, WebSocket, Slack, Telegram | `docs/channels.md` |
| Upload, parsing, ingestion | `docs/file-processing.md` |
| Routes → services → repositories | `docs/architecture.md` |
| Adding a feature end to end | `docs/adding_features.md` |
| Test layers and what belongs in each | `docs/testing.md` |
| Recurring patterns | `docs/patterns.md` |
| Settings and the production checklist | `docs/configuration.md` |

Two things about the reference pages. They are generated from docstrings by
mkdocstrings, so the reasoning belongs in the docstring rather than in a second prose
copy. And the collector is static: `app/services/`, `app/api/` and `app/worker/` have no
`__init__.py`, so it cannot traverse into them and `::: app.services.foo` **fails the
build** — reference those from prose with a source link until those packages are made
explicit.

## Git

- **Never commit on `main`.** Branch first (`feat/…`, `fix/…`).
- **Commit only when asked**, then keep the message scoped and in the imperative.
- **No AI attribution** — no `Co-Authored-By: Claude`, no "Generated with" trailer.
  Write commits and PR descriptions as Kacper authored them.
- **`make check` before opening a PR.** It is what CI runs; a red PR costs a review
  cycle.
- No secrets in commits. Never stage `.env`, a key, or a credential.
