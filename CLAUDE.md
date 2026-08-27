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
  `make lint` runs `vulture` as a gate on what it is sure of, and `deptry` on the
  manifest so a dependency nothing imports fails the same way; `make dead-code` is the
  deeper, human-read scan for unused functions (`docs/branching.md`, `code-style.md`).
- **Comments are scarce; the default is none.** Reasoning lives in docstrings (the
  reference docs are generated from them). The bar for a `#`/`//` comment is one
  question — *would a competent reader make a mistake without it?* If not, delete it. No
  restating what the code says, no section labels (`# the owner's side`), no narrating an
  optimisation a reader already sees (`# one query rather than an EXISTS per row`), no
  ASCII banners (a guard rejects those). Keep only a footgun, a non-obvious constraint or
  an invariant — one sentence, ideally with an issue number. See `code-style.md`.
- **Scoped diffs.** Fix what was asked. Propose follow-ups instead of taking them.
- **Tests are part of the change.** New behaviour ships with a test; a bug ships with a
  regression test that fails without the fix.
- **A user-facing feature ships its seams, not just its surface.** If it produces
  activity or state somebody would want at a glance, it ships a **dashboard widget**
  (registry entry, component, backend id parity). If it adds something somebody
  creates or configures, it ships an **onboarding touch** — a tour stop, and a coach
  flow when it is a create flow. This is not polish: four W3 features landed on
  branches that could not see each other and #594 is the bill, three of the four
  reading as bolted-on because the branch that owned each seam shipped before its
  neighbour. The mechanics are in `.claude/rules/frontend.md` and
  "A new surface owes the walkthrough a stop" below.

## Hard boundaries

Easy to violate, cross-cutting, and each one has been violated here at least once.

- Repositories use `db.flush()` + `db.refresh()`, **never** `db.commit()` — the request's
  session commits once, after the route returns and **before the response is written**.
  That ordering is `scope="function"` on the `DBSession` alias and nothing else; a bare
  `Depends(get_db_session)` puts the commit after the answer has gone out, which is #353.
  The one sanctioned exception is the agent run path: `AgentRunnerService._run` and
  `ChatAgentRunner.run` commit before the model call and again in the terminal
  `finally` (#12, #3). `docs/architecture.md#the-requests-transaction` has the order,
  its three consequences, and the run path's two commits.
- **Background work that reads a row this request wrote is handed over with
  `spawn_after_commit`, never `spawn`.** `spawn` creates the task at once and the loop
  starts it before the commit, so the flow opens its own session and cannot see the row
  it was given the id of — an upload answered `processing` that stays that way (#417).
  `docs/architecture.md#dispatching-background-work-from-a-request` has both.
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
  mechanism**, and adding one is the defect two migrations removed - the second
  of them `0042_sync_source_secret_id`, which took `app/core/crypto.py` off RAG
  connector credentials. They had been sealed with one deployment-wide Fernet key,
  which made this sentence untrue for one table until #937 deleted it. The first
  predates the squash, so it is in git history rather than in a file.
- `datetime.now(UTC)`, never `datetime.utcnow()`.
- `secrets.compare_digest()` for API key comparison, never `==`.
- **Do not reintroduce what was deliberately removed:** `UserRole`, `User.has_role()`,
  `RoleChecker`, `CurrentAdmin`, `CurrentSuperuser` (the `users.role` column went
  with them — authority inside an organization is a membership row plus the
  permission catalog), or `CHANNEL_ENCRYPTION_KEY` and the deployment-wide Fernet
  keys, or `app/core/crypto.py` and a `secret: true` field in a connector's
  `CONFIG_SCHEMA` (`0042_sync_source_secret_id` - a connector credential is a vault
  secret the source references by id).

  **The first two have no revision of their own any more.** 65 were collapsed into
  `0001_baseline` on 2026-07-31 and the numbering restarted, so `0038` and `0066`
  name a *different* migration today or none at all — which is worse than a
  dangling reference, because it resolves. The baseline carries the schema those
  revisions arrived at and none of their data migrations; to read one, use git
  history before that date. Cite a revision by its full file name, and only for
  one that is still in `backend/alembic/versions/`.

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
make check                                        # every CI job but e2e — before every PR
```

`make help` lists the rest. Day to day:

| | |
|---|---|
| `make lint` / `make format` | ruff + ty + vulture + deptry + eslint + prettier + tsc + the guard scripts + codespell |
| `make lint-backend` / `make lint-frontend` | one half of it — CI runs them in two jobs |
| `make dead-code` | vulture + knip, unused functions — a report to read, not a gate |
| `make test-fast` | no coverage — the write-run-write loop |
| `make test` | backend + the 100% gate on the platform layer |
| `make test-integration` | only the tests needing a real database |
| `make test-frontend` / `make test-frontend-cov` | vitest / vitest with the gate CI applies |
| `make test-e2e` | Playwright — needs a backend and its seed |
| `make test-migrations` | the whole chain forwards and back |
| `make db-check` | `alembic check` — a model change with no migration fails here (in `make check`) |
| `make db-migrate` / `make db-upgrade` | autogenerate / apply |
| `make docs` / `make docs-build` | serve on :8001 (`DOCS_PORT=` to move it) / `--strict` |
| `uv run agenticos cmd doctor` | can this deployment actually run an agent? |
| `uv run agenticos cmd --help` | every custom command, including all `rag-*` |

## The loop

**Write, run the tests you just wrote, commit, push, and let CI be the wide net.**
After an edit, run only the tests that cover the change; the full suites are the
pre-push gate, not the write-run loop. Running everything after every edit is the
slowest way to learn the same thing: one frontend spec answers in about two seconds
against seventy for the suite, one backend file in a few seconds — nearly all of it
importing the app, since pytest itself clocks the run at a fraction of that — against
ninety-odd for `make test`. CI's jobs run in parallel and answer in about twelve
minutes, the backend `test` job the long pole and the one #520 is cutting — from a
pushed branch, while you carry on working.

Two things about that answer, both since #317. **Pushing again cancels the run in
flight**, so the answer you were waiting on disappears rather than arriving about a
commit you have already replaced — which is the point, but it means a push is also a
decision to stop caring about the previous one. And **CI runs fewer jobs than
`make check` does**: `test`, `test-frontend` and `e2e` skip when the changed paths
cannot affect them, so a backend-only branch gets no frontend answer at all, and a
`skipped` required check is a pass rather than a problem.
`docs/branching.md` has the rule.

```bash
cd frontend && bunx vitest run src/components/chat/usage-strip.test.tsx
cd backend  && uv run pytest tests/test_sandbox_workspace.py -q
cd backend  && uv run pytest tests/api/test_workspace_routes.py -k bytes -x
```

Once before the push — not after every edit — run `make lint` and the coverage gate for
the half you touched: `make test` or `make test-frontend-cov`. **`bun run test:run` does
not measure coverage**, so a frontend suite where every test passes still fails the job;
that is how `test-frontend` went red on `feat/sandbox` after a green local run. Before
the pull request, `make check` — every CI job except `e2e`, about five minutes, and
`backend/tests/test_ci_parity.py` is what keeps that claim true rather than aspirational
(#143 found four divergences at once). Then read
the answer rather than guessing at it: `gh pr checks <n>`, and
`gh run view --job <id> --log-failed` for whatever is red. `.claude/rules/testing.md` has
the scoped commands and the traps; the pull request reviewer is under Git below, and it is
for a branch you believe is finished.

Two habits that cost time here, both cheap to keep:

- **Edit files with the editor.** A `python3 - <<'PY'` heredoc that rewrites source is not
  reviewable and not atomic — one in this session aborted on its twelfth replacement
  having applied eleven, leaving a half-migrated tree that took two more runs to notice.
  A genuine sweep over dozens of files is the exception: write the script under the
  session scratchpad, collect every edit before writing any, and say what it did.
- **Stage the paths you changed.** `git add -A` staged a stray `node_modules/.vite`
  cache — created by running `bunx vitest` from the repository root instead of
  `frontend/`, which also reports 164 phantom failures because the config is not there.

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
| `app/agents/mcp*.py`, `app/services/mcp_*.py`, `app/core/catalog/mcp_servers.json` | `docs/mcp.md` |
| `app/agents/model_resolver.py`, `app/services/model_profile.py`, `app/services/model_catalog.py` | `docs/models.md` |
| `app/core/vault.py`, `secret_kinds.py`, `app/services/organization_secret.py` | `docs/secrets.md` |
| `app/core/permissions.py`, `app/services/access.py` | `docs/permissions.md` + `docs/reference/permissions.md` |
| `app/services/skills.py`, `skill_library.py`, `app/core/catalog/skills/**` | `docs/skills.md` |
| `app/services/spend.py`, `approvals.py`, `notifications.py` | `docs/governance.md` |
| `app/services/channels/**`, `agent_exposure.py`, `agent_embed.py` | `docs/channels.md` |
| `app/services/rag/**`, `file_upload.py`, `ingestion_config.py` | `docs/file-processing.md` |
| `app/services/sandbox_*.py`, `app/agents/capabilities/sandbox/**`, `app/core/catalog/sandbox_runtimes.json` | `docs/sandbox.md` |
| `app/services/deployment_settings.py`, `signup_policy.py`, `invitation_admission.py`, `app/core/maintenance.py`, `otel_compat.py`, `app/api/exception_handlers.py` | `docs/deployment.md` |
| `app/core/config.py` | `docs/configuration.md` |
| `app/commands/**`, a new `make` target | `docs/commands.md` |
| A new route, service or layering change | `docs/architecture.md` |
| `.github/workflows/ai-review.yml`, `.github/codex/**` | `docs/code-review.md` |
| `.pre-commit-config.yaml`, `.github/dependabot.yml`, the branch rulesets | `docs/branching.md` |
| A capability, permission or setting that changes the first-run path | `docs/first-agent.md`, `docs/install.md` |
| A new dashboard page, tab or create control | `frontend/src/lib/onboarding/{tour,flows}.ts` — see below |

### A new surface owes the walkthrough a stop (required)

The product teaches itself: `frontend/src/lib/onboarding/tour.ts` is the passive
walk a walked page's "?" replays, and `flows.ts` is the guided creation the walk
offers at its end. Both are **registries**, so a page, tab, section or control
added anywhere else is simply absent from them — nothing fails, nothing warns,
and the feature ships invisible to everyone who learns the product through the
tour. That is the whole failure mode: it is silent.

The one place it is now audible: a page with no stop in `tour.ts` renders **no
"?" at all** (`pageHasSteps`), rather than one that opens a walk with nothing in
it and closes again. So a new page whose header carries no help button has not
been added to the registry.

So a change that adds a surface adds its stop in the same change.

| Added | Owed |
|---|---|
| A dashboard page, or a tab/section within one | A `TourStep` in `tour.ts`, and `data-tour` on the control it names |
| A page that can *create* something | A `CreationFlow` in `flows.ts`, plus its `flowForPage` entry |
| A detail view with no route of its own | A pseudo-page id and its resolver in `components/onboarding/detail-targets.ts` |
| A step, of either kind | `steps.<id>.title` / `.body` in `messages/en.json` — a missing key renders the key |

Three things that decide whether a stop actually works, each of which has been
got wrong here:

- **Gate it on the permission its control carries.** An ungated step describes a
  control the server hid, and the walk then waits four seconds for an element
  that will never mount.
- **`optional: true` for a control that renders only when data exists** — an
  "add integration" button behind a non-empty catalog. Without it an empty
  organization gets a caption pinned to nothing.
- **Point at something bounded.** `data-tour` on a card whose body is a full
  catalog spotlights the entire viewport, which highlights nothing; anchor the
  describing step on the header and leave the card's own anchor for the guided
  flow, which needs the list reachable.

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
| The sandbox: sessions, runtimes, isolation, lifetimes | `docs/sandbox.md` |
| Routes → services → repositories | `docs/architecture.md` |
| Adding a feature end to end | `docs/adding_features.md` |
| Test layers and what belongs in each | `docs/testing.md` |
| The automated pull request reviewer | `docs/code-review.md` |
| Branches, rulesets and what protects `main` | `docs/branching.md` |
| Recurring patterns | `docs/patterns.md` |
| The deployment's identity, sign-up policy, notices | `docs/deployment.md` |
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
- **On a branch, commit and push each finished piece without being asked.** That is
  what makes the loop above work: the piece is verified by its own tests, the commit
  body records why, and CI checks the whole of it while the next piece is being
  written. Small commits, each one a thing that stands on its own - not one commit at
  the end of a session. **On `main`, nothing is ever committed** (see above), and a
  half-finished piece waits rather than landing.
- **No AI attribution** — no `Co-Authored-By: Claude`, no "Generated with" trailer.
  Write commits and PR descriptions as Kacper authored them.
- **`make check` before opening a PR.** It is what CI runs; a red PR costs a review
  cycle. Between commits on an open branch the scoped runs plus the pushed jobs are
  enough - see The loop.
- No secrets in commits. Never stage `.env`, a key, or a credential. **Stage paths,
  not `-A`**, and read `git status` before committing: caches and generated files end
  up in a diff exactly this way.

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

### Review your own diff — the automated reviewer is off (#311)

**`ai-review` no longer runs on a pull request, and the label does nothing.**
Every run since 2026-08-05 evening failed inside Codex, concluded `success`, and
posted a sentence that read like a verdict on the diff — eleven pull requests
merged that way. Until #311 is fixed, the only review before a merge is a human
one, so the sweep that used to follow the reviewer's findings is now the whole
job rather than the second half of it: read the surrounding files, sweep the
siblings of anything you changed, review your own diff as a maintainer would.
Subagents are good at this — give one the diff and a category to hunt in. The
local `/review` command in `.claude/commands/review.md` checks the same standard.

When it comes back, it answers "is this branch finished", so **ask it when you
believe the branch is finished**: label, fix everything it found plus whatever
reviewing your own work turned up, label again, until it comes back clean. Never
once per commit and never one finding per run — the work between the labels is
where most of the defects are actually found, and a reviewer that answers the
same diff seven times has been asked the same question seven times. If it is
wrong — and it is, sometimes; it does not always know what a file's surrounding
code already does — say so in the commit body or the pull request, with the
reason, rather than churning the code to silence it.

`github-code-quality[bot]` opens threads on the same ruleset and cannot be
filtered. Three of its findings are **already adjudicated** in
`docs/code-review.md` — a bare `await <task>`, `...` as a `Protocol` body, and a
`pytest.fail` fall-through. Resolve those with a pointer to that section; do not
write a fresh essay per thread, and do not rewrite the cancellation idiom to
satisfy a query that does not model `await`.

### A bug you find is a bug you file

**Every defect found along the way gets a GitHub issue** — `gh issue create`,
straight away, whoever or whatever found it: the reviewer, a subagent, you
reading a neighbouring file, a test that failed for the wrong reason.

- **In scope for what you are doing?** Fix it in the same change, and the issue
  is unnecessary — the commit body carries the story.
- **Out of scope?** File it and keep going. Do not fold an unrelated fix into a
  branch about something else, and do not drop it either. Mentioning a bug in a
  pull request comment is not recording it: the comment is closed with the pull
  request and the bug outlives both.

An issue says what breaks, the sequence that triggers it, the `file:line`, and
how you would know it was fixed. Say plainly whether the current branch caused
it or merely found it — "pre-existing, found reviewing #105" is information the
next reader needs. `#106` is the shape to copy.

### File it triaged, not bare

**An issue with no labels, no type, no project and no milestone is an issue
somebody else has to triage by hand, and until they do it is invisible to every
view the board is read through.** So set all five at creation. Guessing wrong is
cheap and fixable; leaving them empty is what actually costs, because nothing
surfaces the gap.

```bash
gh issue create --repo vstorm-co/agenticos \
  --title "…" --body-file draft.md \
  --label bug,severity:medium,effort:s \
  --project VstormOS \
  --milestone "W1 · Aug 3–7"
```

| | What to set, and how to choose |
|---|---|
| **Labels** | One kind (`bug`, `enhancement`, `documentation`, `dependencies`, `ci`, `meta`), plus `severity:*` on a bug, `effort:*` always, plus `frontend` / `security` where they apply. `gh label list` is the list; do not invent one. |
| **Type** | `Bug`, `Feature` or `Task`. Needs GraphQL — see below. |
| **Project** | `VstormOS` for anything in this repo. (`Vstorm OSS` is the cross-repo board; do not use it for issues here.) |
| **Milestone** | The current week, unless the work genuinely belongs later. `gh api repos/vstorm-co/agenticos/milestones --jq '.[].title'` — never hardcode a week from an example, including this one. |
| **Status** | The project's own field, defaulting to `Backlog`. Leave it there: `In progress` is a claim about somebody's day, not about the issue. |

`gh` has **no `--type` flag** on `create` or `edit` (checked on 2.83.2), so the
type is a second call. The ids are stable, and the REST ones are the wrong ones —
GraphQL needs the global node id:

```bash
node=$(gh api repos/vstorm-co/agenticos/issues/N --jq .node_id)
gh api graphql -f query='mutation($i:ID!,$t:ID!){
  updateIssueIssueType(input:{issueId:$i,issueTypeId:$t}){issue{number issueType{name}}}}' \
  -f i="$node" -f t="IT_kwDOBMvQGs4A22d_"   # Bug
```

`Task = IT_kwDOBMvQGs4A22d7` · `Bug = IT_kwDOBMvQGs4A22d_` ·
`Feature = IT_kwDOBMvQGs4A22eD`. Re-derive with
`gh api graphql -f query='{organization(login:"vstorm-co"){issueTypes(first:10){nodes{id name}}}}'`
if a mutation answers `NOT_FOUND`.

**Inherit from the issue you are working on.** Filing a defect found while
working #40 is not filing into a vacuum: unless there is a reason to differ, take
its milestone, its project and its `priority:*`, and reference it in the body —
`Found reviewing #40` — so the two read as one thread of work rather than two
unrelated rows a week apart. If the new issue *blocks* the one you are on, say so
in both directions, because a blocker nobody can see from the blocked issue is a
blocker that gets discovered by being hit.

### And it says where it sits — [#168](https://github.com/vstorm-co/agenticos/issues/168)

**#168 is the issue map**: what the clusters are, which chains block which, and
what has no scope yet. Read it before filing and **name at least one existing
issue in the body** — the cluster it belongs to, or the issue it most nearly
duplicates. "Checked, nothing related" is a fine answer; silence is not, because
an unlinked issue is one that gets worked twice or not at all.

That is not hypothetical. Before the map: 17 open issues referenced nothing and
were referenced by nothing; #13 and #30 were one bug filed twice, the second
saying "the same URL normalisation as the avatar-proxy issue" without the
number; #7 and #18 were one failure in two middlewares; #139 called itself the
hub for "several page-level complaints" and named none of them; and five issues
had **empty bodies**, which no amount of linking fixes.

Filing changes the map, so **update #168 in the same breath** — add the number
to its cluster, and to the spine if it blocks something. The graph is cheap to
re-derive when in doubt:

```bash
gh issue list --state open --limit 300 --json number,title,body   # then grep '#[0-9]'
```

**Pass `--limit`.** It defaults to 30 and caps at 100 — under a hundred open
issues that silently drops the lowest numbers, which is how #2 through #7 once
read as closed and a blocker chain read as already done.

An issue that closes a whole cluster says so (`Closes #147, #148`). One that
only takes a checkbox out of a bag issue like #33 ticks the box there instead —
that is how a batch issue stays honest about what is left.
