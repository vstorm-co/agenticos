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

**Python is pinned to 3.12 by `backend/.python-version`**, matching
`requires-python`, `backend/Dockerfile` and every CI job. That pin exists because it
did not: the venv resolved to 3.14, `tests/test_coverage_gate.py` reached for
`Path.full_match` (added in **3.13**), and the test guarding the coverage gate passed
locally while raising `AttributeError` in CI. **If `uv run` reports anything other
than 3.12, delete `backend/.venv` and re-run `uv sync`** — anything verified on a
newer interpreter has not been verified on the one that ships.

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

### Finishing an implementation means updating the page (required)

**A change that alters behaviour a page describes is not finished until that page is
updated, in the same change. Do not wait to be asked.** One copy only stays true if
it moves with the code; otherwise the page keeps describing what the code used to do
and the disagreement is found months later by somebody acting on the stale half.

Trigger map — what changed → which page:

| Changed | Update |
|---|---|
| `app/agents/spec.py` | `docs/reference/spec.md` (via the docstrings) |
| `app/agents/capabilities/**` | `docs/reference/capabilities.md` |
| `app/agents/mcp*.py`, `app/services/mcp_*.py`, `catalog/mcp_servers.json` | `docs/mcp.md` |
| `app/agents/model_resolver.py`, `app/services/model_profile.py`, `model_catalog.py` | `docs/models.md` |
| `app/core/vault.py`, `secret_kinds.py`, `app/services/organization_secret.py` | `docs/secrets.md` |
| `app/core/permissions.py`, `app/services/access.py` | `docs/permissions.md` + `docs/reference/permissions.md` |
| `app/services/skills.py`, `skill_library.py`, `catalog/skills/**` | `docs/skills.md` |
| `app/services/spend.py`, `approvals.py`, `notifications.py` | `docs/governance.md` |
| `app/services/channels/**`, `agent_exposure.py`, `agent_embed.py` | `docs/channels.md` |
| `app/services/rag/**`, `file_upload.py`, `ingestion_config.py` | `docs/file-processing.md` |
| `app/core/config.py` | `docs/configuration.md` |
| `app/commands/**`, a new `make` target | `docs/commands.md` |
| A new route, service or layering change | `docs/architecture.md` |
| `.github/workflows/ai-review.yml`, `.github/codex/**` | `docs/code-review.md` |
| `.github/workflows/branch-policy.yml`, the branch rulesets | `docs/branching.md` |
| A capability, permission or setting that changes the first-run path | `docs/first-agent.md`, `docs/install.md` |

**When updating a page:** keep its altitude — `docs/reference/*` is generated from
docstrings, so fix the **docstring** there rather than adding prose. Keep the
concept pages behaviour-level, not line-by-line. If a change makes a page's
structure wrong (a stage removed, a new subsystem), restructure the page rather than
patching around it. Adding a page means adding it to `nav` in `mkdocs.yml` and to
the table below.

`.claude/skills/*` and `.claude/rules/*` are subject to the same rule: they name
files, flags and commands, so a rename or removal makes them confidently wrong.
`assistant.py`, `CHANNEL_ENCRYPTION_KEY`, `UserRole` and `search_knowledge_base` all
survived there long after leaving the code.

A **Stop hook** runs `scripts/docs_drift.py` and names the pages owed when a change
touched the map above and nothing under `docs/` moved. It is a reminder, not a gate —
a refactor with no behaviour change and a test-only change legitimately owe nothing;
say so and move on. Run it yourself any time with
`python3 scripts/docs_drift.py`.

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
| The automated pull request reviewer | `docs/code-review.md` |
| Branches, rulesets and how a release reaches `main` | `docs/branching.md` |
| Recurring patterns | `docs/patterns.md` |
| Settings and the production checklist | `docs/configuration.md` |

Two things about the reference pages. They are generated from docstrings by
mkdocstrings, so the reasoning belongs in the docstring rather than in a second prose
copy. And the collector is static: `app/services/`, `app/api/` and `app/worker/` have no
`__init__.py`, so it cannot traverse into them and `::: app.services.foo` **fails the
build** — reference those from prose with a source link until those packages are made
explicit.

## Git

- **Never commit on `main`.** Branch first (`feat/…`, `fix/…`), then open a pull
  request. A pre-commit hook refuses `main` locally and a ruleset refuses it at
  push time; `docs/branching.md` has the whole picture.
- **One branch, one pull request, squashed on merge.** `main` is the only long-lived
  branch, so the squashed commit is what survives - which is why the subject line
  and body below are worth the minute they cost.
- **Commit only when asked.**
- **No AI attribution** — no `Co-Authored-By: Claude`, no "Generated with" trailer.
  Write commits and PR descriptions as Kacper authored them.
- **`make check` before opening a PR.** It is what CI runs; a red PR costs a review
  cycle.
- No secrets in commits. Never stage `.env`, a key, or a credential.

### The subject line

`type(scope): summary` — Conventional Commits. Imperative, lower case after the
colon, no trailing period, **72 characters or fewer**. A `commit-msg` hook enforces
the shape.

```
fix(vault): stop passing a role column that no longer exists
test(mcp): assert the fixture exists rather than that it is on screen
ci(e2e): give bootstrap a key so the seed publishes an agent
feat(capabilities): add a clock so the agent stops assuming the date
```

| Type | For |
|---|---|
| `feat` | New behaviour somebody can use |
| `fix` | A defect. Ships with a regression test |
| `refactor` | Same behaviour, different shape |
| `perf` | Faster, same behaviour |
| `test` | Tests only |
| `docs` | `docs/`, `README`, `CLAUDE.md`, `.claude/` |
| `ci` | `.github/`, pre-commit, the Makefile's check targets |
| `build` | Dependencies, lockfiles, Dockerfiles, compose files |
| `chore` | Anything left, and a release commit |

**Scope is the subsystem, not the path.** Prefer the vocabulary the docs use:
`agents`, `capabilities`, `spec`, `permissions`, `vault`, `mcp`, `models`, `rag`,
`skills`, `channels`, `api`, `budgets`, `approvals`, `builder`, `chat`, `e2e`,
`docs`, `deps`, `compose`. Omit it when a change is genuinely repo-wide
(`chore: cut 0.0.1`). One scope — if two are honest, that is usually two commits.

A breaking change takes `!` (`feat(spec)!: …`) and a `BREAKING CHANGE:` footer
saying what a stored spec or a client's YAML has to do about it.

### The body

The subject says what; the body says **why, and what it cost**. This is the part
that survives — a decision explained only in review is a decision nobody finds.
Worth writing down:

- the failure the change prevents, concretely ("every path that created a user
  raised `TypeError`"), not "improve reliability";
- how it was verified, and how far that verification actually reaches — an upgrade
  that passes because a fixture short-circuited is worth saying so;
- what was found and deliberately *not* fixed, so the next reader knows it was seen.

Wrap at 72. Bullets are fine. Correct an earlier commit's claim plainly if it turned
out wrong; a wrong message is worse than a missing one.

### Issues and pull requests

Reference in the **footer**, never the subject — the subject has to read on its own
in `git log --oneline`.

```
Closes #142            the issue is done
Refs #142              related, still open
Part-of #142           one commit of several on one issue
Reverts 0f94fa4        with the reason it was reverted in the body
```

`Closes` only when the change genuinely finishes it. A PR body opens with what
changed and why, then how it was verified — and says plainly what is still red.
