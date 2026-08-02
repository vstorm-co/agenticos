# Changelog

Notable changes to AgenticOS. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Two things are versioned separately from this file and worth knowing about:

- **`SPEC_VERSION`** — the agent spec format, currently **7**. A published agent
  and a client's exported YAML both carry it, so it only ever moves forward with a
  migration that keeps old documents loading. See
  [the spec reference](docs/reference/spec.md).
- **The migration chain** — `backend/alembic/versions/`, squashed to a single
  `0001_baseline` for this first version. Revision ids named below (`0038`,
  `0059`, `0066`) are history: they describe when something changed, not a file
  that still exists. Schema changes are listed here by what they do.

## [Unreleased]

Nothing yet.

## [0.0.2] — 2026-08-02

A dependency patch, and the first release cut through the path 0.0.1 built.

### Changed

- `tavily-python` 0.7.26 → 0.7.27, which is what the `web_research` capability
  searches with.

## [0.0.1] — 2026-08-02

First tagged version. The platform is usable end to end — build an agent in the
UI, publish it, run it from chat, an HTTP API, Slack or an embedded widget, with
budgets and approvals applying identically to all of them — and the interfaces
below should be treated as unstable until 0.1.0.

### Added

**The agent model.** An agent is data, not code: instructions, a model profile, a
set of capabilities and a budget, versioned on publish and exportable as YAML into
a client's own git repository. Spec, version, exposure and run are the four nouns
everything else is built from.

**Capabilities** — seven, registered in code and composed by configuration:
knowledge search, skills, web search (DuckDuckGo, native, Tavily, Brave, Exa),
sandboxed Python, charts, reasoning effort, and a clock. Per-tool approval and
per-agent tool renaming key on a stable tool id, so a rename cannot detach an
approval gate.

**MCP** — any Model Context Protocol server by URL, over streamable HTTP or SSE,
with 58 common servers in the picker and full OAuth 2.1 (discovery, dynamic client
registration, PKCE, refresh). Connections are personal or organization-wide; only
the latter can be bound by a published agent.

**Models** — 27 providers, per-organization credentials, fallback on outage, and
self-hosted Ollama or a LiteLLM proxy. Model ids stay free text, with live and
curated pickers, because a provider ships something the morning after any list is
warmed.

**Knowledge and skills** — collections with pgvector retrieval over uploaded
documents, Google Drive and S3; and skills, which are written know-how the agent
loads only when it decides one is relevant.

**Governance** — monthly budgets checked *before* each model request and recorded
even when a run fails, human approval for side-effecting tools, per-agent alerts
with an audience, and an audit trail.

**Permissions** — three layers: the deployment superadmin, an organization role
composed from a permission catalog, and per-row visibility plus grants. Effective
access is `max(role scope, grant)`, so sharing one resource never means promoting
somebody.

**The vault** — envelope encryption for every credential at rest, sealed to the
organization or member that owns it, so a ciphertext moved between tenants cannot
be decrypted. There is deliberately no second mechanism.

**Surfaces** — web chat, HTTP API, Slack, Telegram, Mattermost and embeddable
widgets, all behind one runner.

**Multi-tenancy** — organization isolation enforced by database constraints rather
than by service code alone.

**Dependency freshness as a policy.** FastAPI, Pydantic AI, Logfire and
genai-prices are uncapped and meant to track their newest release — genai-prices
especially, since it *is* the price snapshot budgets are computed from.
`make deps-upgrade` bumps them, a scheduled `framework-freshness` workflow tries
the newest on a Monday and opens an issue when it breaks, and Dependabot opens the
PR. Majors are not held back: delaying one does not avoid the upgrade, it only
makes the eventual jump wider.

**Pre-commit**, covering both halves of the repo: the standard hygiene hooks,
`codespell`, `yamlfmt`, `zizmor` over the workflows, and ruff / ty / prettier /
eslint / tsc. `pre-commit` had been a dependency and `make install` had been
running `pre-commit install` for a while, but there was no config file, so the
installed hook did nothing.

### Fixed

- **Every path that created a user was broken.** The user repository still passed
  `role=` to the model after the column was dropped in `0066`, and SQLAlchemy
  raises on an unmapped keyword — so registration, Google OAuth,
  `agenticos user create` and `agenticos cmd bootstrap` all failed. Bootstrap is
  the command the install instructions open with.
- **`agenticos cmd seed --clear` deleted nothing**, for the same reason: it
  filtered on the dropped `role` column. It now keys on `is_app_admin`.
- **The chat WebSocket 500'd on handshake in local development.**
  `docker-compose.dev.yml` claimed in its header to be identical to
  `docker-compose.yml`, had drifted, and had lost `--ws websockets-sansio` —
  and it was the file `make dev` used.
- **Production ran without a route to the internet.** The only network was marked
  `internal: true`, which blocks egress, so no agent could reach a model provider.
  Split into an internal `data` network for Postgres and Redis and an `edge`
  network for the app.
- **Production ran no background work at all** — no Prefect server or runner, so
  document ingestion and collection syncs never happened and an upload stayed
  unsearchable forever.
- **The test guarding the coverage gate could not run on the interpreter that
  ships.** It used `Path.full_match`, added in Python 3.13, while CI installs
  3.12. `backend/.python-version` now pins 3.12 so local matches.
- **The security CI job never audited anything** — it errored installing
  `pip-audit` outside a virtualenv, with two more argument errors queued behind
  that.
- **Icons and diagrams in the documentation rendered as their own source**, for
  want of `pymdownx.emoji` and a mermaid custom fence.
- **FastAPI 0.141 stopped flattening included routers into `app.routes`**, so
  every route sweep in `tests/api/test_platform_routes.py` silently ran over zero
  routes. Rewritten on the public `iter_route_contexts`. Found by upgrading rather
  than by a Dependabot PR, which is the argument for the freshness workflow.
- **`Agent.updated_at` was typed `string | undefined`** while the API sends
  `null`, which made the honest test for "never edited" a type error.
- **The workflows ran with a broader token than they need** and left the checkout
  credential on disk. Every action is now pinned to a commit SHA,
  `persist-credentials: false` everywhere, `contents: read` by default, and Pages
  write scoped to the one job that deploys.
- **`backend/.pre-commit-config.yaml`** shadowed the repository root and carried a
  `ty` hook that failed on an argument the pinned `ty` does not accept.

### Security

- **A conversation was readable and writable across tenants.** `GET
  /conversations/{id}/messages` returned a full transcript — tool calls and
  their arguments included — for a conversation in another organization, and
  `POST` to the same path appended a turn to it, `role: "assistant"` included,
  which rendered to its owner as the agent's own words. `organization_id` is now
  a required argument on every conversation read and write; a caller that
  genuinely reads across tenants passes an explicit sentinel.
- **The avatar proxy forwarded a path traversal to the backend.** It is the one
  route handler served without a session, so an anonymous caller could drive
  arbitrary `GET`s against the internal API and read the response.
- **A channel bot missing one configuration value stalled the whole API.** The
  Slack and Mattermost supervisors retried a start that returns without
  awaiting, which never yields — so the event loop starved and every request,
  health check included, stopped being answered.
- **Icons are resolved from the directory listing**, not by joining a request
  parameter onto a path, and a symlink out of that directory is refused.

### Added — the toolchain that keeps it honest

- **An automated pull request reviewer** that reads this repository's own rules
  from the base branch rather than a generic checklist. See
  [Code review](docs/code-review.md).
- **`main` is protected by a ruleset** with no bypass actors: pull request
  required, CI green, squash only, no force push. See
  [Branches](docs/branching.md).
- **A weekly freshness job** that upgrades the entire lockfile, transitive
  packages included, runs the suite against it and opens an issue when the
  newest release breaks us.

### Changed

- **One compose file per environment**, with a matching frontend file beside it:
  `docker-compose.yml` (local), `docker-compose-dev.yml` (dev server),
  `docker-compose-prod.yml` (production), each with a `.frontend.yml` sibling.
  `make stage` is kept as an alias for the new `make dev-server`.
- **One long-lived branch.** Work reaches `main` by pull request from a
  short-lived branch, squashed on merge. A `dev` branch existed briefly and was
  removed; see [Branches](docs/branching.md). CI's lint job matches `make lint`,
  and the integration suite refuses to skip when `CI` is set: an unreachable
  database there means the service container failed, and skipping two hundred
  tests to report green is worse than failing.
- **Pydantic AI 2.x** is the agent runtime, and the frontend is on **Next 16**.
- **The documentation is the single copy of how the system works**, with a
  trigger map from code path to page in `CLAUDE.md` and a `Stop` hook
  (`scripts/docs_drift.py`) that names the pages a change owes.

### Removed

- `users.role`, `UserRole`, `User.has_role()`, `RoleChecker`, `CurrentAdmin` and
  `CurrentSuperuser` (`0066`). Authority inside an organization is a membership
  row plus the permission catalog.
- `CHANNEL_ENCRYPTION_KEY` and the deployment-wide Fernet keys (`0038`).
  Everything seals through the vault, bound to an owner.
- `app/agents/assistant.py` and `app/agents/prompts.py`. There is no single agent
  object and no system prompt in code; an agent is assembled per run from the
  capabilities its spec names.
- Conversation-level knowledge-base ids (`0059`). An agent's spec is the only
  thing that decides what it may search.
- `ENV_VARS.md`, superseded by [Configuration](docs/configuration.md).
- `.fastapi-fullstack.json` and the `make upgrade*` template-merge targets. This
  codebase has diverged from the generator past the point where a 3-way merge
  helps.

[Unreleased]: https://github.com/vstorm-co/agenticos/compare/v0.0.2...HEAD
[0.0.2]: https://github.com/vstorm-co/agenticos/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/vstorm-co/agenticos/releases/tag/v0.0.1
