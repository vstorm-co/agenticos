<div align="center">

# AgenticOS

**The operating system for your company's AI agents.**
Self-hosted, open source, and yours.

[![CI](https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/platform%20layer-100%25-brightgreen)](docs/testing.md)
[![Docs](https://img.shields.io/badge/docs-mkdocs-blue)](docs/index.md)
[![Licence](https://img.shields.io/badge/licence-Apache--2.0-blue)](LICENSE)

[![Python](https://img.shields.io/badge/python-3.12-3776ab?logo=python&logoColor=white)](backend/pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-Pydantic%20v2-009688?logo=fastapi&logoColor=white)](backend/pyproject.toml)
[![Pydantic AI](https://img.shields.io/badge/runtime-Pydantic%20AI-e520a0)](https://ai.pydantic.dev)
[![Next.js](https://img.shields.io/badge/Next.js-15-000000?logo=nextdotjs&logoColor=white)](frontend/package.json)
[![Postgres](https://img.shields.io/badge/Postgres-pgvector-4169e1?logo=postgresql&logoColor=white)](docker-compose.yml)
[![Conventional Commits](https://img.shields.io/badge/commits-conventional-fe5196?logo=conventionalcommits&logoColor=white)](docs/branching.md)

[Documentation](docs/index.md) ·
[Install](docs/install.md) ·
[Your first agent](docs/first-agent.md) ·
[Concepts](docs/concepts.md) ·
[Integrations](docs/mcp.md) ·
[Changelog](CHANGELOG.md) ·
[Roadmap](docs/ROADMAP.md)

</div>

---

**An agent here is data, not code.** Instructions, a model, a set of
capabilities, a budget. You build it in a UI, publish a version, and it runs the
same way everywhere: web chat, HTTP API, Slack, Telegram. Budgets, approvals and
audit apply identically to all of them, because every surface goes through one
runner.

```yaml
# What an agent actually is - exportable, reviewable, committable to your repo.
name: Support Copilot
instructions: |
  Answer from the product wiki and cite the document you used.
  If the wiki does not cover it, say so rather than guessing.
model_profile_id: 8f1c...
capabilities:
  - id: knowledge
    config: { default_top_k: 8 }
  - id: web_research
    approval: required
collection_ids: [b2a9...]
budget:
  monthly_usd: 50
```

## Get to a running agent

Four commands, about five minutes. Needs Docker, GNU Make, [uv](https://astral.sh/uv)
and [bun](https://bun.sh); on Windows, WSL2. There is no `.env` to write first -
every compose variable has a default, and the one secret that cannot have one
(`SANDBOXD_TOKEN`) is generated into `backend/.env` for you.

```bash
git clone https://github.com/vstorm-co/agenticos && cd agenticos
make dev                                          # postgres (pgvector), redis, api, prefect, sandbox
make dev-frontend                                 # the Next.js container — a separate compose file
make platform-bootstrap BOOTSTRAP_API_KEY=sk-...  # an org, an owner, a key, a model, a published agent
open http://localhost:3000                        # sign in as admin@example.com / admin123
```

Then open **Agents → Getting Started → Test** and ask it something.

`make platform-bootstrap` is the step that matters, because an empty install is a
chicken-and-egg problem: an agent needs a model, a model needs a key, a key needs
an organization. It walks that chain once. Leave `BOOTSTRAP_API_KEY` out and
everything is still created - the agent is saved as a draft rather than published,
because an agent with no model cannot answer. Add a key under **Settings → AI
providers**, then publish.

Every command here is idempotent; re-run any of them whenever you are not sure
they worked.

| | |
|---|---|
| Frontend | <http://localhost:3000> |
| API · OpenAPI | <http://localhost:8000> · `/docs` |
| Prefect | <http://localhost:4200> |

If something does not come up, `uv run agenticos cmd doctor` (from `backend/`)
checks the database, the vault, whether there is a model an agent could actually
run on and whether every sandbox connection answers - and says which one is
missing. [Install](docs/install.md) has the step-by-step version of all of this,
the prerequisites table, the host-Python workflow and a table of what each
failure means.

## Why

Most agent frameworks give you a library. You write Python, you deploy it, and
every change to an agent's behaviour is a pull request, a review and a release.
That is the right shape for a product feature and the wrong shape for the forty
small agents a company actually wants - because the person who knows what the
agent should say is not the person with commit access.

AgenticOS moves the agent out of the code and puts governance around it instead.

| | |
|---|---|
| **Agents** | Built in a UI, versioned on publish, exportable as YAML into your own git repository |
| **[Capabilities](docs/reference/capabilities.md)** | Knowledge search, web research, charts, sandboxed Python, reasoning effort - switched on per agent, never edited as code in a browser |
| **[Integrations](docs/mcp.md)** | Any MCP server by URL, with 58 in the picker - GitHub, Linear, Notion, Slack, Stripe, Postgres, Sentry. No connector to write |
| **[Models](docs/models.md)** | 27 providers, a key per organization, fallback on outage, or self-hosted Ollama and LiteLLM |
| **Knowledge** | Collections with RAG over documents, Google Drive and S3 |
| **[Skills](docs/skills.md)** | Written know-how the agent loads only when it decides it is relevant |
| **[Governance](docs/governance.md)** | Monthly budgets that stop a run, human approval for anything side-effecting, an audit trail, per-agent alerts |
| **[Surfaces](docs/channels.md)** | Web chat, HTTP API, Slack, Telegram, Mattermost, embeddable widgets - one runner behind all of them |
| **[Access](docs/permissions.md)** | Permission catalog in code, roles composed from it, per-resource sharing |
| **Multi-tenant** | Organization isolation enforced by database constraints, not only by service code |

[Secrets](docs/secrets.md) are sealed per organization: a key copied from one
tenant's database row cannot be decrypted for another, and no API response ever
returns one.

## Stack

| Component | Technology |
|---|---|
| Backend | FastAPI + Pydantic v2 |
| Database | PostgreSQL (async via asyncpg) + pgvector |
| Agent runtime | [Pydantic AI](https://ai.pydantic.dev) |
| Tool protocol | [MCP](https://modelcontextprotocol.io) over streamable HTTP and SSE |
| Auth | JWT + refresh tokens, API keys, Google OAuth, magic links |
| Cache | Redis |
| Background work | Prefect |
| Frontend | Next.js 15 + React 19 + Tailwind v4 |

Nothing phones home. Model prices come from a bundled
[`genai-prices`](https://github.com/pydantic/genai-prices) snapshot, and the only
outbound calls are the ones your agents make.

## Documentation

The docs are built with MkDocs and live in [`docs/`](docs/).

```bash
make docs         # serve on http://localhost:8001, live reload
make docs-build   # build with --strict, which is what CI runs
```

| | |
|---|---|
| [Concepts](docs/concepts.md) | Spec, version, exposure, run - the four nouns everything is built from |
| [Permissions](docs/permissions.md) | The three layers, scopes, and how a grant widens access without promoting anybody |
| [Governance](docs/governance.md) | Budgets, approvals, alerts, audit |
| [Capabilities](docs/reference/capabilities.md) | Every capability that ships, its tools, config and scope |
| [MCP](docs/mcp.md) | Connections, the server catalog, OAuth, what is *not* gated |
| [Models](docs/models.md) | Providers, model profiles, fallbacks, how a run is costed |
| [Secrets](docs/secrets.md) | The vault, secret kinds, and what never leaves it |
| [Skills](docs/skills.md) | The format, the bundled library, skills versus knowledge |
| [Channels](docs/channels.md) | Slack, Telegram, Mattermost, the widget, the raw WebSocket |
| [The agent spec](docs/reference/spec.md) | Field by field, generated from the source |
| [Configuration](docs/configuration.md) | Every setting, and the production checklist |
| [Architecture](docs/architecture.md) | Routes → services → repositories, and why |

## Development

```bash
make check          # what CI runs: lint, types, backend tests, frontend tests
make test           # backend + the 100% coverage gate on the platform layer
make test-fast      # no coverage, for the write-run-write loop
make test-frontend  # vitest
make test-e2e       # playwright, against a running stack
make test-migrations  # apply and roll back the whole chain
make format         # ruff
make help           # everything else
```

The **platform layer** - everything AgenticOS adds on top of the generated
template - is held at 100% coverage and CI fails below it. The exact list is
`[tool.coverage.run] include` in `backend/pyproject.toml`, mirrored in
`[[tool.ty.overrides]]` because a module held to 100% coverage is held to the type
checker too. Template-inherited subsystems are reported by `make coverage-all` but
do not gate the build; see [Testing](docs/testing.md) for why, and for what belongs
in each test layer.

> [!IMPORTANT]
> The database must be `pgvector/pgvector:pg16`, not stock Postgres. The
> retrieval store issues `CREATE EXTENSION IF NOT EXISTS vector` the first time a
> collection is written to, and stock Postgres answers
> `extension "vector" is not available` - a 500 before any row is committed. If
> document ingestion fails on a fresh environment, check the image first.

## Contributing

Read [Architecture](docs/architecture.md) and [Patterns](docs/patterns.md)
first - the layering is enforced by tests, not by convention. Then
[Adding a feature](docs/adding_features.md).

New behaviour ships with tests; a bug ships with a regression test. Run
`make check` before opening a pull request - it is exactly what CI runs.

Three things that trip up a first change here:

- **An agent is data.** There is no `@agent.tool` and no agent module to decorate;
  a new tool reaches a model through the capability registry. See
  [Add a capability](docs/howto/add-capability.md).
- **`require(...)` gates go on collection routes only.** A permission gate on a
  per-resource route cannot see that row's grants, so it refuses a Viewer who was
  explicitly given access. Per-resource routes hand the decision to a service that
  calls `resolve_access`. See [Permissions](docs/permissions.md).
- **If the tool you need already exists as an MCP server, write no code.** Point at
  it and its tools appear in the Builder. See [MCP](docs/mcp.md).

If you work on this with an AI agent, [`.claude/`](.claude/README.md) holds the
repository's own rules and task skills - the same conventions, written for a machine.

## Licence

Apache License 2.0 - see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

Apache-2.0 rather than MIT because AgenticOS is meant to be deployed inside other
companies: the explicit patent grant is the part their legal review asks about,
and MIT is silent on it.

---

*Built from the [Full-Stack AI Agent Template](https://github.com/vstorm-co/full-stack-ai-agent-template).*
