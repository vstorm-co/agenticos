# Features

AgenticOS gives you the following.

## An agent is a file

Not a class and not a decorator. In an operating system a program is a file —
something you can read, copy, version and commit — and an agent here is the same
thing: instructions, a model, a set of capabilities, a budget.

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

Everything else on this page follows from that one decision.

!!! info "Why this is called an operating system"

    Because the word is a specification rather than a label: processes,
    resource limits, access control, drivers, a filesystem, one shell for many
    interfaces, and an audit log. Each has a mechanism on this page.
    [The seven, and how to test any other product against them →](about/index.md#what-makes-something-an-operating-system-for-agents)

!!! tip

    The person who knows what the agent should say is rarely the person with
    commit access. When behaviour lives in a file rather than in Python, they do
    not need it.

## Built in a UI, versioned on publish

You build the agent in the browser. When you publish it, the spec is frozen as a
version and that version is what runs — a draft you are still editing never
reaches anybody.

Every published version stays readable, so *what did this agent look like in
March* is a question with an answer.

## Exportable into your own repository

The spec exports as YAML. Commit it, review it in a pull request, diff two
versions, restore one. It is your file, in your git history, in a format that
does not need AgenticOS to read.

Import goes the other way, so a spec written by hand is a first-class agent.

## What an agent can actually do

You decide by switching things on, one at a time, in the Builder. None of it is
a plugin somebody installs, a Python file somebody deploys, or a prompt somebody
hopes the model obeys — an agent cannot reach a capability that is switched off,
whatever its instructions say.

| The agent can… | Switch on |
|---|---|
| **Answer from what your company knows** — your documents, your written procedures, and whatever was attached to this conversation | Knowledge search · Skills · Context |
| **Go and find out** — search the web, read one page properly, or drive a real browser through a site that needs clicking | Web search · Web fetch · Browser automation |
| **Do the work, not describe it** — run Python over a file, keep a workspace with a shell, draw a chart, generate an image | Run Python · Files & shell · Charts · Image generation |
| **Handle work too big for one answer** — delegate to specialists, keep a task list, think longer before replying, carry a long conversation without losing the start of it | Delegation · Planning · Thinking · Context management |
| **Stay inside the lines** — redact or block what must not pass, cap what one tool may return, know what today's date is | Guardrails · Tool output limits · Date and time |

Each one carries its own settings, its own permission scope and — where it acts
on the outside world — its own approval setting. Switching one on is a decision
somebody makes about *this* agent, not a change to the platform.

[Every capability, its tools and its config →](reference/capabilities.md)

## Any model, from 27 providers

OpenAI, Anthropic, Google, Groq, Mistral, Bedrock, Vertex, an Ollama on your own
hardware, a LiteLLM proxy in front of all of it.

A **model profile** names the model, its parameters and its fallbacks; agents
point at the profile. Change the profile and every agent using it moves —
without a single spec being republished.

Keys are per organization, sealed in the vault, and never returned by any
endpoint.

[Models and providers →](models.md)

## Any MCP server, by URL

Connect a server and its tools appear in the Toolbox, namespaced so two servers
offering `search` do not collide. 59 of the common ones — GitHub, Linear, Notion,
Slack, Stripe, Postgres — are in the picker with their OAuth flows already wired.

!!! info

    This is why the capability catalog is short and stays short. An integration
    with a SaaS product is an MCP connection, not a Python module somebody in
    this repository has to maintain against that product's API.

[MCP connections →](mcp.md)

## Knowledge that stays on your hardware

Upload documents, or sync a Google Drive folder or an S3 bucket. AgenticOS parses
them, chunks them, embeds them into pgvector, and keeps them in *your* Postgres.

Embeddings are keyed per organization. A vector written for one tenant cannot be
read by another, and that is enforced by the schema rather than by a `WHERE`
clause somebody has to remember.

[File processing →](file-processing.md) · [Skills →](skills.md)

## One agent, every surface

Publish once. The same runner answers on all of these:

- **Web chat** in the console
- **A hosted page** you can send somebody a link to
- **An embeddable widget** for your own site
- **The HTTP API**, and a raw WebSocket for streaming
- **Slack**, **Telegram** and **Mattermost**, where an `@mention` runs as the
  person who sent it — not as the bot

[Surfaces →](channels.md)

## Budgets that actually stop a run

Checked **before** each model request, not tallied afterwards.

A run that fails still records what it spent, because a budget that only counts
successes is not a budget. Alerts fire at thresholds you set, per agent.

## Approval for anything side-effecting

A tool that changes the outside world parks the run and waits for a person. Set
it per capability, override it per tool.

An approval is decided once. A second decision on a decided approval is refused —
which sounds obvious until you have seen the race that makes it necessary.

[Governance →](governance.md)

## Permissions in code, roles composed from them

Call sites check permissions, never role names. A role is a set of permissions
from a catalog, and a **grant** widens what one person may do with one row.

A grant never narrows. A Viewer holding an explicit `edit` grant on one agent can
edit that agent — and nothing else.

[Permissions →](permissions.md)

## Secrets sealed per organization

Provider keys, bot tokens, MCP credentials — one mechanism, `app/core/vault.py`,
and deliberately no second one.

A ciphertext copied out of one tenant's database row cannot be decrypted for
another. No response, log line or audit entry ever carries a plaintext key.

[Secrets and the vault →](secrets.md)

## Multi-tenant, in the schema

Organization isolation is constraints and keys, not convention. The interesting
tests in this repository are the ones that check a *refusal*: a cross-tenant
read, an ungranted scope, a budget breach, a second decision on a decided
approval.

## Triggers, so an agent runs without you

Schedule a run, or fire one on an event. The same spec, the same budget, the same
audit trail — just nobody typing.

[Triggers →](triggers.md)

## Self-hosted, and quiet

Docker Compose, your Postgres, your Redis, your hardware.

Nothing phones home. Model prices come from a snapshot bundled with the release,
and the only outbound requests are the ones your agents make.

## Open source

Apache 2.0, auditable, and forkable. The spec format is versioned, so a document
you export today still loads tomorrow.

[Install it →](install.md) · [Build your first agent →](first-agent.md)
