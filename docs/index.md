<div class="agenticos-hero" markdown>

![AgenticOS](assets/mark.svg){ .agenticos-hero__mark }

<p class="agenticos-hero__name">AgenticOS</p>

<p class="agenticos-hero__tagline">
The operating system for your company's AI agents. Processes, permissions,
resource limits, drivers and an audit log. Self-hosted, open source, and yours.
</p>

<p class="agenticos-hero__badges">
<a href="https://github.com/vstorm-co/agenticos/actions"><img src="https://img.shields.io/github/actions/workflow/status/vstorm-co/agenticos/ci.yml?branch=main&label=tests" alt="Tests"></a>
<a href="https://github.com/vstorm-co/agenticos/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="Licence"></a>
<a href="https://github.com/vstorm-co/agenticos"><img src="https://img.shields.io/github/stars/vstorm-co/agenticos?style=flat" alt="Stars"></a>
<img src="https://img.shields.io/badge/python-3.12-blue" alt="Python 3.12">
</p>

<p class="agenticos-hero__links" markdown>
**Documentation**: <a href="https://vstorm-co.github.io/agenticos/">vstorm-co.github.io/agenticos</a><br>
**Source Code**: <a href="https://github.com/vstorm-co/agenticos">github.com/vstorm-co/agenticos</a>
</p>

</div>

---

AgenticOS is a self-hosted, multi-tenant platform for building, governing and
running a company's AI agents.

The key point is this:

!!! quote "Code defines, configuration composes"

    A business team composes agents in a browser — instructions, a model, a set
    of capabilities, a budget — and the result runs the same way everywhere:
    web chat, HTTP API, Slack, Telegram, an embedded widget.

    Engineers extend what there is to compose, in typed Python. Configuration
    can only ever reach what code registered, which is what makes a no-code
    Builder safe to hand to somebody who is not an engineer.

Everything else on this site follows from that one sentence. The ceiling is not
a config file — it is whatever your engineers put in the registry, and the
source is yours.

## Start where you are

<div class="grid cards" markdown>

- :material-rocket-launch:{ .lg .middle } **I want to try it**

    [Install](install.md) takes four commands, then
    [your first agent](first-agent.md) is a working one in about ten minutes.

- :material-account-tie:{ .lg .middle } **I am deciding whether we adopt it**

    [Rolling it out](rollout.md) — who does what, what it costs, and the
    questions your security review will ask. No terminal on it.

- :material-code-braces:{ .lg .middle } **I want to integrate with it**

    [The HTTP API](api.md) for calling it, [MCP](mcp.md) for giving agents your
    tools, and [the console's code](frontend.md) if you are changing the UI.

- :material-cog:{ .lg .middle } **I already run it and something is wrong**

    [The console](console.md) maps every screen, and each page's *Recap* is the
    short version. [Configuration](configuration.md) is every setting.

</div>

## Why it is called an operating system

Because the word is doing work. An operating system runs and isolates processes,
enforces resource limits, controls access, reaches hardware through drivers,
keeps a filesystem, gives many interfaces one shell, and writes an audit log.

AgenticOS does each of those for agents: runs, budgets checked before the model
request, a permission catalog with approvals as its `sudo`, MCP and model
profiles as its drivers, collections in your own Postgres, one runner behind
every surface, and an audit trail written even when a run fails.

[The seven, one by one, with what to check in any other product →](about/index.md#what-makes-something-an-operating-system-for-agents)

## Why it exists

Most agent frameworks give you a library. You write Python, you deploy it, and
every change to an agent's behaviour is a pull request, a review and a release.

That is the right shape for a product feature. It is the wrong shape for the
forty small agents a company actually wants, because **the person who knows what
the agent should say is not the person with commit access.**

So AgenticOS moves the agent out of the code, and puts governance around it
instead.

<div class="grid cards" markdown>

- :material-shield-check:{ .lg .middle } **Budgets that stop a run**

    Checked *before* each model request, not after. A run that fails still
    records what it spent, because a budget that ignores failures is not a
    budget.

- :material-hand-back-right:{ .lg .middle } **Approval for anything side-effecting**

    A tool that acts on the outside world parks the run and waits for a person.
    Set per capability, overridable per tool.

- :material-account-key:{ .lg .middle } **Permissions in code, roles composed from them**

    Call sites check permissions, never role names. A grant widens what one
    person may do with one row; it never narrows it.

- :material-database-lock:{ .lg .middle } **Tenant isolation in the schema**

    Not only in the service layer. A ciphertext from one organization cannot be
    decrypted for another.

</div>

## Requirements

Docker and Docker Compose. That is the whole list — Postgres (with pgvector),
Redis, the API, the worker and the console all come up together.

Running the services by hand instead? Python 3.12, Node with
[bun](https://bun.sh), PostgreSQL 16 with
[pgvector](https://github.com/pgvector/pgvector), and Redis.

## Installation

```bash
git clone https://github.com/vstorm-co/agenticos.git
cd agenticos
make dev
```

That brings up Postgres, Redis, the API, the worker and the frontend.

Then create an organization, an owner, a model and a first agent:

```bash
make platform-bootstrap BOOTSTRAP_API_KEY=sk-...
```

And open the console:

```bash
open http://localhost:3000
```

Sign in with `admin@example.com` / `admin123`.

!!! tip

    Not sure the deployment can actually run an agent? Ask it.

    ```bash
    uv run agenticos cmd doctor
    ```

## What an agent is made of

Six decisions, and none of them is code. Somebody who knows what the agent
should say makes all six in a browser; publishing freezes the combination as a
version, and that version is what answers.

| | What it decides |
|---|---|
| **Instructions** | What the agent does, in plain language — and what it should refuse to do |
| **A model profile** | Which model answers, with which parameters, and what it falls back to during an outage |
| **Capabilities** | What it may do at all: search your knowledge, read a page, run Python, draw a chart |
| **Knowledge** | Which collections it may search, and nothing outside them |
| **Approval** | Which of those actions wait for a person before they touch the outside world |
| **A budget** | What it may spend in a month, checked *before* each request rather than counted after |

Change any of them and nothing ships until you publish. The version that was
live stays readable, so *what did this agent look like in March* has an answer.

=== "What somebody edits"

    ![The agent builder — instructions, model, capabilities and limits, with the published version pinned](assets/builder.png)

=== "What it becomes"

    A frozen version, and a file you can export into your own git repository,
    review in a pull request and restore from:

    ```yaml
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

## Check it

Publish it and it runs the same way in every surface: the console's chat, a
hosted page, an embedded widget, the HTTP API, Slack, Telegram, Mattermost.

```bash
curl -X POST http://localhost:8000/api/v1/agents/$AGENT_ID/run \
    -H "Authorization: Bearer $TOKEN" \
    -H "X-Organization-Id: $ORG_ID" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "How do I rotate a provider key?"}'
```

One runner behind all of them, so an answer does not depend on where the question
came from.

## What you get

| | |
|---|---|
| **Agents** | Built in a UI, versioned on publish, exportable as YAML into your own git repository |
| **[Capabilities](reference/capabilities.md)** | Knowledge search, web research, charts, code execution, a sandbox, delegation — switched on per agent, never edited as code in a browser |
| **[Integrations](mcp.md)** | Any MCP server by URL, with 59 common ones in the picker — GitHub, Linear, Notion, Slack, Stripe, Postgres |
| **[Models](models.md)** | 27 providers, per-organization keys, fallbacks, and self-hosted Ollama or a LiteLLM proxy |
| **[Knowledge](file-processing.md)** | Collections with RAG over documents, Google Drive and S3 |
| **[Skills](skills.md)** | Written know-how the agent loads only when it decides it is relevant |
| **[Governance](governance.md)** | Monthly budgets, human approval, an audit trail, per-agent alerts |
| **[Surfaces](channels.md)** | Web chat, HTTP API, Slack, Telegram, embeddable widgets — one runner behind all of them |
| **[Secrets](secrets.md)** | Sealed per organization. No response, log line or audit entry ever carries a plaintext key |

[The full list of features →](features.md)

## Recap

- An agent is **a file**, not a module. Instructions, a model, capabilities, a
  budget.
- It is **published as a version**, and that version is what runs.
- It is **exportable as YAML** into your repository, reviewable in a pull
  request.
- It is **governed**: budgets that stop a run, approvals that wait for a person,
  permissions checked at every call site.
- It is **yours**: your Postgres, your hardware, nothing phoning home.

## Next

<div class="grid cards" markdown>

- :material-school:{ .lg .middle } **[Learn](learn/index.md)**

    The recommended way through, in order: install, first agent, concepts, then
    the pieces.

- :material-star-four-points:{ .lg .middle } **[Features](features.md)**

    Everything the platform does, on one page.

- :material-book-open-variant:{ .lg .middle } **[Reference](configuration.md)**

    Settings, CLI commands, the agent spec, the capability and permission
    catalogs.

- :material-account-group:{ .lg .middle } **[Rolling it out](rollout.md)**

    For whoever owns the decision rather than the install: who does what, what
    it costs, and what your security review will ask.

- :material-information-outline:{ .lg .middle } **[About](about/index.md)**

    Why it exists, what it deliberately is not, and the six decisions that shape
    it.

</div>

## Stack

FastAPI and Pydantic v2 on PostgreSQL, [Pydantic AI](https://ai.pydantic.dev) for
the agent runtime, pgvector for retrieval, Prefect for background work, and
Next.js 15 for the console.

Nothing here phones home: model prices come from a bundled snapshot, and the only
outbound calls are the ones your agents make.

## Licence

Apache 2.0. See
[`LICENSE`](https://github.com/vstorm-co/agenticos/blob/main/LICENSE).
