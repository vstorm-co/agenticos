# Features

AgenticOS gives you the following.

## Code defines, configuration composes

That one sentence is the whole design, and it describes two halves that are
deliberately not the same job.

**A business team composes agents in a browser.** Instructions, a model, a set
of capabilities, a budget — no Python, no pull request, no release. The spec is
a document, so it versions on publish and exports as YAML into your own git
repository.

A browser is all the console needs. The [desktop app](desktop.md) wraps the same
console for whoever wants it on the dock - with a pet and a screenshot shortcut -
and is an add-on, not a second way of running the platform.

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
| A tool nobody has written | [Add a capability](https://vstorm-co.github.io/agenticos/howto/add-capability/) — typed Python, and it appears in the Builder |
| A different ingestion, channel or connector | [Extend the platform](https://vstorm-co.github.io/agenticos/resources/#extending-the-platform); the same pattern each time |
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
    [The seven, and how to test any other product against them →](https://vstorm-co.github.io/agenticos/about/#what-makes-something-an-operating-system-for-agents)

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
| **Answer from what your company knows** — your documents, your written procedures, whatever was attached to this conversation, and the services you mount as folders, such as a Drive or a repository | Knowledge search · Skills · Context · Virtual terminal |
| **Remember, and look it up** — keep notes across conversations, recall a fact by meaning, or find what was actually said in a past conversation and read it back | Memory · Past conversations |
| **Go and find out** — search the web, read one page properly, or drive a real browser through a site that needs clicking | Web search · Read web pages · Web browser |
| **Do the work, not describe it** — run Python over a file, keep a workspace with a shell, draw a chart, generate an image, read a text aloud or make a short clip | Calculations · Sandbox · Charts · Image generation · Text to speech · Video generation |
| **Handle work too big for one answer** — delegate to specialists, keep a task list, think longer before replying, carry a long conversation without losing the start of it | Delegation · Planning · Thinking · Long conversations |
| **Stay inside the lines** — redact or block what must not pass, cap what one tool may return, know what today's date is | Guardrails · Tool output limits · Date and time |

Each one carries its own settings, its own permission scope and — where it acts
on the outside world — its own approval setting. Switching one on is a decision
somebody makes about *this* agent, not a change to the platform.

[Every capability, its tools and its config →](https://vstorm-co.github.io/agenticos/reference/capabilities/)

## Any model, from 28 providers

OpenAI, Anthropic, Google, Groq, Mistral, Bedrock, Vertex, an Ollama on your own
hardware, a LiteLLM proxy in front of all of it.

A **model profile** names the model, its parameters and its fallbacks; agents
point at the profile. Change the profile and every agent using it moves —
without a single spec being republished.

Keys are per organization, sealed in the vault, and never returned by any
endpoint.

[Models and providers →](https://vstorm-co.github.io/agenticos/models/)

## Any MCP server, by URL

Connect a server and its tools appear in the Toolbox, namespaced so two servers
offering `search` do not collide.

**4,700+ servers are in the gallery** - the count the MCP servers page shows.
The common ones - GitHub, Linear, Notion, Slack, Stripe, Postgres - arrive with
their OAuth flows already wired, because somebody here connected each of them
and checked it. The rest are mirrored from the public MCP registry and
searchable by name: nobody here reviewed those, the list says which kind a row
is, and a listing a check found dead, broken or duplicated is left out.

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

[File processing →](https://vstorm-co.github.io/agenticos/file-processing/) · [Skills →](skills.md)

## One agent, every surface

Publish once. The same runner answers on all of these:

- **Web chat** in the console
- **A hosted page** you can send somebody a link to
- **An embeddable widget** for your own site
- **The HTTP API**, and a raw WebSocket for streaming
- **Slack**, **Telegram**, **Mattermost** and **Discord**, where an `@mention` runs as the
  person who sent it — not as the bot

Speech to text runs on the organization's own provider on these too: dictation
in web chat, on a hosted page and in the widget, and voice notes transcribed
in Slack, Telegram, Mattermost and Discord.

**Voice calls** let a person talk to a published agent and interrupt it, in web
chat, on a hosted page or in the widget. The agent keeps its tools, knowledge,
approvals and budgets, every turn is saved as text in the conversation, and no
audio is stored. Calls are off until an organization turns them on, and carry
their own time and monthly-minute limits. OpenAI's realtime models are tested
live; Azure OpenAI, Gemini Live and xAI are not verified live yet.

[Surfaces →](https://vstorm-co.github.io/agenticos/channels/) · [Voice conversations →](https://vstorm-co.github.io/agenticos/voice/)

## Budgets that actually stop a run

Checked **before** each model request, not tallied afterwards.

A run that fails still records what it spent, because a budget that only counts
successes is not a budget. Alerts fire at thresholds you set, per agent.

## Approval where you want a person

Choose which tools wait for a person before they run: per capability, overridden
per tool, and per MCP server. Nothing waits until you ask, so a run in a channel
or on a schedule is never parked on a gate nobody chose.

An approval is decided once. A second decision on a decided approval is refused —
which sounds obvious until you have seen the race that makes it necessary.

[Governance →](https://vstorm-co.github.io/agenticos/governance/)

## Permissions in code, roles composed from them

Call sites check permissions, never role names. A role is a set of permissions
from a catalog, and a **grant** widens what one person may do with one row.

A grant never narrows. A Viewer holding an explicit `edit` grant on one agent can
edit that agent — and nothing else.

[Permissions →](https://vstorm-co.github.io/agenticos/permissions/)

## Secrets sealed per organization

Provider keys, bot tokens, MCP credentials — one mechanism, `app/core/vault.py`,
and deliberately no second one.

A ciphertext copied out of one tenant's database row cannot be decrypted for
another. No response, log line or audit entry ever carries a plaintext key.

[Secrets and the vault →](https://vstorm-co.github.io/agenticos/secrets/)

## Multi-tenant, in the schema

Organization isolation is constraints and keys, not convention. The interesting
tests in this repository are the ones that check a *refusal*: a cross-tenant
read, an ungranted scope, a budget breach, a second decision on a decided
approval.

## Workflows, when a job is more than one step

Some work is a sequence, not a single answer: read a record, call an agent,
branch on what it says, loop over a list. You build that on a canvas — drag the
steps in, wire one step's output into the next, and publish it as an immutable
version, the same draft-then-publish shape an agent has.

Each step's inputs are a value you type or a value read from an earlier step, and
the editor only offers a source that is actually reachable and carries the right
type. The draft saves itself as you edit, and publishing re-checks the whole
graph before it freezes a version.

[Workflows →](workflows.md) · [Virtual Tables →](virtual-tables.md)

## Triggers, so an agent runs without you

Schedule a run, or fire one on an event. The same spec, the same budget, the same
audit trail — just nobody typing.

[Triggers →](https://vstorm-co.github.io/agenticos/triggers/)

## Self-hosted, and clear about what leaves { #self-hosted-and-quiet }

Docker Compose, your Postgres, your Redis, your hardware.

Your prompts, conversations and documents stay in your own deployment, in its
database and storage. They go nowhere unless you add something that names a
destination: a model profile, an embedding or parsing provider for a collection,
an MCP server or a channel. Model prices come from a snapshot bundled with the
release.

One report is on by default: [deployment diagnostics](https://vstorm-co.github.io/agenticos/configuration/#diagnostics).
Once an hour the worker sends the version, database and worker health, coarse
usage counts and counts of failed runs, jobs and ingestions by closed category.
Signed-in browsers and the desktop and mobile apps send a pseudonymous activity
signal straight to the collector. No prompts, conversations, file names, account
names, email addresses, provider keys or exception messages are sent. Set
`DIAGNOSTICS_ENABLED=false` to turn it off, or point `DIAGNOSTICS_COLLECTOR_URL`
at a collector you run.

## Open source

Apache 2.0, auditable, and forkable. The spec format is versioned, so a document
you export today still loads tomorrow.

[Install it →](https://vstorm-co.github.io/agenticos/install/) · [Build your first agent →](https://vstorm-co.github.io/agenticos/first-agent/)
