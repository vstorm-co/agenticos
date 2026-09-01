# Features

AgenticOS gives you the following.

## Code defines, configuration composes

That one sentence is the whole design, and it describes two halves that are
deliberately not the same job.

**A business team composes agents in a browser.** Instructions, a model, a set
of capabilities, a budget — no Python, no pull request, no release. The spec is
a document, so it versions on publish and exports as YAML into your own git
repository.

**Engineers extend what there is to compose.** A capability is typed, tested
Python in this repository: a tool the model can call, a guardrail, a compaction
strategy, a connector. You add one, and from that moment it is a switch in
everybody's Builder.

The rule between the two halves is the load-bearing part:

!!! quote "Configuration can only ever reach what code registered"

    Which is exactly what makes a no-code Builder safe to hand to somebody who
    is not an engineer. They cannot invent a tool, widen a scope or reach a
    system nobody wired — the worst they can do is assemble things that were
    already approved.

So the ceiling is not a config file. It is whatever your engineers put in the
registry, and the platform is Apache-2.0, so that includes anything you write
for your own use case.

| You want | You do |
|---|---|
| A different answer from an agent | Edit the instructions and publish. Seconds, no engineer |
| A tool for a SaaS product | Point at [an MCP server](mcp.md). Usually no code at all |
| A tool nobody has written | [Add a capability](howto/add-capability.md) — typed Python, and it appears in the Builder |
| A different ingestion, channel or connector | [Extend the platform](resources/index.md#extending-the-platform); the same pattern each time |
| The whole thing shaped to one process | Fork it. It is your deployment and your source |

!!! tip "The split is the point"

    The person who knows what the agent should say is rarely the person with
    commit access — and the person who can write a tool should not be spending
    their week on wording changes. This is the line that lets both of them work
    without waiting for the other.

!!! info "Why this is called an operating system"

    Because the word is a specification rather than a label: processes,
    resource limits, access control, drivers, a filesystem, one shell for many
    interfaces, and an audit log. Each has a mechanism on this page.
    [The seven, and how to test any other product against them →](about/index.md#what-makes-something-an-operating-system-for-agents)

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
offering `search` do not collide. 99 of the common ones — GitHub, Linear, Notion,
Slack, Stripe, Postgres — are in the picker with their OAuth flows already wired.
Beside them sit 5,703 more, mirrored from the public MCP registry and searchable
by name: nobody here reviewed those, and the list says which kind a row is.

!!! info

    This is why the capability catalog is short and stays short. An integration
    with a SaaS product is an MCP connection, not a Python module somebody in
    this repository has to maintain against that product's API.

[MCP connections →](mcp.md)

## Knowledge that stays on your hardware

Upload documents, or sync a Google Drive folder or an S3 bucket. AgenticOS parses
them, chunks them, embeds them into pgvector, and keeps them in *your* Postgres.

**How it reads them is yours to decide**, per collection and overridable per
upload — which is unusual, and it is where retrieval quality is actually won:

| | |
|---|---|
| **PDF parser** | `pymupdf` — local, fast, and the only one that extracts embedded images for description · `liteparse` — local and layout-aware, keeping tables as ASCII grids rather than flattening them · `llamaparse` — a cloud service billed per page that returns markdown |
| **Chunking** | `recursive`, `markdown` or `fixed`, with your own size and overlap |
| **OCR** | On demand or automatic, with a language |
| **Images in documents** | Described by a model profile you choose, with your own prompt |

Embeddings are keyed per organization. A vector written for one tenant cannot be
read by another, and that is enforced by the schema rather than by a `WHERE`
clause somebody has to remember.

The embedding model is fixed when a collection is created, because two models of
equal width write into different spaces that search would go on comparing.

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
