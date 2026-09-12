# CLAUDE.md — AgenticOS

Project-wide decisions and pointers to task-specific guidance. Read relevant rules,
skills and documentation as needed. Keep detailed procedures and incident history
outside this file. Current user instructions and higher-priority session rules
take precedence.

## What this is

A self-hosted, open-source, multi-tenant platform for a company's AI agents.

**An agent is a versioned spec.** Users configure instructions, models, capabilities
and budgets in the UI, publish a version and can export it as YAML. The same agent
runs through web chat, the HTTP API and channel integrations. Change an individual
agent through its spec; change Python when implementing platform behaviour or
capabilities. Tools reach models through the capability registry.

**Stack:** FastAPI, Pydantic v2, Pydantic AI, PostgreSQL with pgvector, Redis,
Prefect, Next.js, React, bun, next-intl and MkDocs Material. Use versions from the
repository manifests and lockfiles; Python is pinned in `backend/.python-version`.

The repository originated from the Full-Stack AI Agent Template. Platform and
template-inherited subsystems have different coverage gates, described below.

## Quality and scope

- Type owned boundaries and nontrivial helpers. Do not use `Any` or suppressions to
  hide errors. Necessary suppressions need a specific explanation; route return
  annotations below are an explicit project convention.
- Use domain exceptions with `message` and `details`. Do not swallow exceptions
  or mask bugs with fallbacks.
- Keep changes scoped. Avoid speculative abstractions, unused code and unrelated
  cleanup. Comments explain non-obvious constraints; API contracts belong in
  docstrings. See `.claude/rules/code-style.md`.
- Test new behaviour and add regression tests for bugs. Documentation-only changes
  need documentation checks, not artificial application tests.
- Integrate new user-facing features with the existing product: onboarding for new
  pages and creation flows, and dashboard widgets for activity or state that belongs
  at a glance. Follow `.claude/rules/frontend.md` for registries, permissions,
  translations and anchors.

## Hard boundaries

- Routes call services; services coordinate repositories. Routes must not import or
  call repositories directly.
- Repositories use `db.flush()` and `db.refresh()`, never `db.commit()`. Use
  `DBSession`: its `scope="function"` commits after the route returns and before
  the response is written. A bare `Depends(get_db_session)` has different timing.
  The agent run paths in `AgentRunnerService._run` and `ChatAgentRunner.run`
  explicitly commit before the model call and in terminal cleanup. See
  `docs/architecture.md#the-requests-transaction`.
- Dispatch background work needing rows written by the request with
  `spawn_after_commit`, so its own session can see those rows. See
  `docs/architecture.md#dispatching-background-work-from-a-request`.
- Collection routes use `require(...)` gates. Per-resource routes for agents, skills
  and collections delegate to a service using `resolve_access`; a role gate must
  not reject access allowed by a resource grant. Follow `permissions-rbac`.
- Route handlers return `-> Any` and declare `response_model` for serialization.
  Keep service and repository return types precise.
- Store credentials through `app/core/vault.py`. Connector sources reference vault
  secret IDs; do not put credentials in a connector's `CONFIG_MODEL` or introduce
  deployment-wide Fernet keys, `CHANNEL_ENCRYPTION_KEY` or `app/core/crypto.py`.
- Organization authority comes from membership and the permission catalog. Do not
  restore `UserRole`, `User.has_role()`, `RoleChecker`, `CurrentAdmin`,
  `CurrentSuperuser` or the old `users.role` column.
- Use `datetime.now(UTC)` and `secrets.compare_digest()` for API key comparisons.
- Migration numbering restarted after a baseline squash. Verify references against
  `backend/alembic/versions/` and cite full filenames; use git history for removed
  revisions rather than assuming an old number still identifies the same migration.

## Read the matching rule before writing code

Read the relevant files under `.claude/rules/`; their frontmatter defines the file
scope. Load only the rules that apply to the change.

| Editing | Read |
|---|---|
| Any `backend/app/**` Python | `architecture.md` — Routes → Services → Repositories, DI, thin vs. thick domains |
| `schemas/`, `db/models/` | `schemas-models.md` — `*Create`/`*Update`/`*Read`/`*List`, SQLAlchemy |
| `api/` | `api-conventions.md` — REST structure, status codes, pagination, auth aliases |
| `core/`, `services/` | `exceptions-security.md` — domain exceptions, JWT, the permission model |
| Any Python | `code-style.md` — formatting, naming, imports, type hints |
| `tests/` | `testing.md` — the layers, anyio, fixtures, the 100% gate |
| `frontend/` | `frontend.md` — App Router, data layer, stores, i18n, permissions |

## Read the matching skill before starting a task

Skills live in `.claude/skills/<name>/SKILL.md`. Read the skills matching the task;
`.claude/README.md` explains the layout.

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
make check                                        # aggregate pre-PR checks; excludes e2e
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

## Verification

During implementation, run tests covering the change. Run frontend commands from
`frontend/`, backend commands from `backend/` and make targets from the root.

Before pushing, run `make lint` and the coverage gate for the side changed:
`make test` and/or `make test-frontend-cov`. A passing run without coverage does
not verify that gate. Before a PR, run `make check`. Report failures and unavailable
checks. See `.claude/rules/testing.md` for scoped commands.

Inspect CI for the current commit. A later push can cancel an earlier run, and
path-filtered jobs may be skipped. Consult `docs/branching.md` and workflow files
for CI behaviour rather than assuming local commands and CI are identical.

## Environment

- Use the repository's pgvector-enabled PostgreSQL image; stock PostgreSQL lacks
  the vector extension required by RAG. Check the image if ingestion fails in a
  fresh environment.
- Match `backend/.python-version` when creating or syncing the backend environment.
  Check the interpreter actually used by `uv run` before relying on test results.

## Testing

Read `docs/testing.md`, `.claude/rules/testing.md` and the relevant testing skill
for fixtures and patterns.

- The platform layer has a 100% coverage gate. Exact modules are configured in
  `backend/pyproject.toml`; template-inherited subsystems are additionally reported
  by `make coverage-all` without that gate.
- When adding a platform module, keep `[tool.coverage.run] include` and the matching
  `[[tool.ty.overrides]] include` aligned, including order.
  `backend/tests/test_coverage_gate.py` checks this contract.
- Async tests use anyio: `pytestmark = pytest.mark.anyio`.
- Cover refusal and failure paths: tenant isolation, scopes and grants, budgets
  checked before model calls and recorded on failure, invalid specs rejected at
  publish, and secrets excluded from responses, logs and audit entries. Also cover
  channel sender identity, parser/routing compatibility and existing stored JSONB
  when tightening validation. The testing skills contain worked examples.

## Documentation

Update existing documentation in the same change when described behaviour changes.
Refactors with unchanged behaviour and test-only changes do not require unrelated
prose edits. Update rules and skills when referenced paths or contracts change.
API reference changes belong in the generating docstrings.

Read the `project-docs` skill for site structure, writing conventions, generated
pages and build checks. Add new pages to `mkdocs.yml`, relevant cross-links and
the topic map below. `scripts/docs_drift.py` contains the code-to-page trigger map;
its Stop hook is a reminder, not a completeness check or a gate.

| Topic | Page |
|---|---|
| Spec, version, exposure, run | `docs/concepts.md` |
| The three permission layers, scopes, grants | `docs/permissions.md` |
| Budgets, approvals, alerts, audit | `docs/governance.md` |
| What ships as a capability, its tools and config | `docs/reference/capabilities.md` |
| The agent spec, field by field | `docs/reference/spec.md` |
| MCP connections, the server catalog, OAuth | `docs/mcp.md` |
| Providers, model profiles, fallbacks, cost | `docs/models.md` |
| Which model to pick, open weights vs closed | `docs/choosing-models.md` |
| Adoption, roles, cost, the security review | `docs/rollout.md` |
| The vault, secret kinds, what never leaks | `docs/secrets.md` |
| Skills — format, library, skills vs knowledge | `docs/skills.md` |
| Context files — standing knowledge bound to agents | `docs/context.md` |
| Named environments, promotion, per-environment tracing | `docs/environments.md` |
| Surfaces: widget, WebSocket, Slack, Telegram | `docs/channels.md` |
| The desktop app: a Tauri shell around a deployment's console | `docs/desktop.md` |
| Upload, parsing, ingestion | `docs/file-processing.md` |
| The console: dashboard widgets, chat, slash commands, the map | `docs/console.md` |
| Every module, screenshotted in both themes | `docs/screens.md` |
| The sandbox: sessions, runtimes, isolation, lifetimes | `docs/sandbox.md` |
| Routes → services → repositories | `docs/architecture.md` |
| The Next.js console, for a contributor | `docs/frontend.md` |
| Authenticating and calling the HTTP API | `docs/api.md` |
| Adding a feature end to end | `docs/adding_features.md` |
| Test layers and what belongs in each | `docs/testing.md` |
| The automated pull request reviewer | `docs/code-review.md` |
| Branches, rulesets and what protects `main` | `docs/branching.md` |
| Recurring patterns | `docs/patterns.md` |
| Getting it onto a host: sizing, TLS, the approved deploy | `docs/deploy.md` |
| The deployment's identity, sign-up policy, notices | `docs/deployment.md` |
| Settings and the production checklist | `docs/configuration.md` |
| What the platform does, on one page | `docs/features.md` |
| The Learn track's own landing | `docs/learn/index.md` |
| Help, contributing, extending the platform | `docs/resources/index.md` |
| Why it exists, and what it is not | `docs/about/index.md` |
| The six decisions that shape the codebase | `docs/about/design.md` (repo only) |
| Delivery state and what is left | `docs/ROADMAP.md` (repo only) |
| Every notable change | `docs/release-notes.md` (reads `CHANGELOG.md`) |

## Git

- Never commit on `main`. Use a feature or fix branch, one PR per coherent change,
  squashed on merge.
- On a branch, commit and push each finished, verified piece without being asked.
  This is the project's exception to the global commit-on-request preference;
  explicit session instructions still take precedence.
- No AI attribution in commits or PR descriptions: no `Co-Authored-By: Claude`,
  `Generated with Claude Code` or equivalent footer.
- Stage only intended changes and review the staged diff. Exclude secrets, unrelated
  work and tool caches.
- Use Conventional Commits: `type(scope): summary`, imperative, lower case after the
  colon, no trailing period, at most 72 characters. Types: `feat`, `fix`,
  `refactor`, `perf`, `test`, `docs`, `ci`, `build`, `chore`. Scope names the
  subsystem; omit it for repository-wide changes. Use `!` and a
  `BREAKING CHANGE:` footer for breaking changes.
- Add a body when the reason, verification or tradeoffs are not clear from the
  subject; wrap it at 72 characters. Put issue references in footers (`Closes`,
  `Refs`, `Part-of`); use `Closes` only when the issue is fully resolved.
- PR descriptions explain the problem, resulting behaviour, verification and
  material limitations. Review the diff and surrounding code before declaring work
  finished. `.claude/commands/review.md` defines the local review standard.
  `docs/code-review.md` and `.github/workflows/ai-review.yml` describe automated
  review. A failed reviewer is not a clean review; assess findings against the code
  and explain rejected ones.
- Fix confirmed in-scope defects; record out-of-scope defects without expanding the
  change. Before filing or triaging issues, read
  `.claude/references/issue-triage.md` for the repository's board conventions.
