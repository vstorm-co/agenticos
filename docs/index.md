# AgenticOS

<p style="font-size: 1.15rem; color: var(--md-default-fg-color--light);">
The operating system for your company's AI agents. Self-hosted, open source, and
yours.
</p>

---

**An agent here is data, not code.** Instructions, a model, a set of
capabilities, a budget. You build it in a UI, publish a version, and it runs the
same way everywhere: web chat, HTTP API, Slack, Telegram.

That sentence is the whole design. Everything below follows from it.

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

## Why this exists

Most agent frameworks give you a library. You write Python, you deploy it, and
every change to an agent's behaviour is a pull request, a review and a release.
That is the right shape for a product feature and the wrong shape for the forty
small agents a company actually wants, because the person who knows what the
agent should say is not the person with commit access.

AgenticOS moves the agent out of the code and puts governance around it instead:

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

## What you get

| | |
|---|---|
| **Agents** | Built in a UI, versioned on publish, exportable as YAML into your own git repository |
| **[Capabilities](reference/capabilities.md)** | Knowledge search, web research, charts, code execution, reasoning effort - switched on per agent, never edited as code in a browser |
| **[Integrations](mcp.md)** | Any MCP server by URL, with 58 common ones in the picker - GitHub, Linear, Notion, Slack, Stripe, Postgres |
| **[Models](models.md)** | 27 providers, per-organization keys, fallbacks, and self-hosted Ollama or a LiteLLM proxy |
| **Knowledge** | Collections with RAG over documents, Google Drive and S3 |
| **[Skills](skills.md)** | Written know-how the agent loads only when it decides it is relevant |
| **[Governance](governance.md)** | Monthly budgets, human approval, an audit trail, per-agent alerts |
| **[Surfaces](channels.md)** | Web chat, HTTP API, Slack, Telegram, embeddable widgets - one runner behind all of them |
| **Multi-tenant** | Organization isolation enforced by constraints, not by convention |

[Secrets](secrets.md) are sealed per organization: a key copied from one tenant's
database row cannot be decrypted for another, and no API response ever returns one.

## Get started

<div class="grid cards" markdown>

- :material-download:{ .lg .middle } **[Install](install.md)**

    Docker, or the services by hand. About five minutes to a running stack.

- :material-rocket-launch:{ .lg .middle } **[Your first agent](first-agent.md)**

    From a provider key to an agent that answers, then to one that is published
    and metered.

- :material-lightbulb:{ .lg .middle } **[Concepts](concepts.md)**

    Spec, version, exposure, run. The four nouns everything else is built from.

- :material-book-open-variant:{ .lg .middle } **[Reference](configuration.md)**

    Settings, CLI commands, the agent spec, the permission catalog.

</div>

!!! tip "Three commands"

    ```bash
    make dev                                          # postgres, redis, api, worker, frontend
    make platform-bootstrap BOOTSTRAP_API_KEY=sk-...  # an org, an owner, a model, an agent
    open http://localhost:3000                        # admin@example.com / admin123
    ```

## Stack

FastAPI and Pydantic v2 on PostgreSQL, [Pydantic AI](https://ai.pydantic.dev)
for the agent runtime, pgvector for retrieval, Prefect for background work, and
Next.js 15 for the UI. Nothing here phones home: model prices come from a
bundled snapshot, and the only outbound calls are the ones your agents make.

## Licence

Open source. See [`LICENSE`](https://github.com/vstorm-co/agenticos/blob/main/LICENSE).
