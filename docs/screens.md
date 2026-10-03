# Every screen in the console

The console modules are described below. Screenshots from the previous interface have been removed; marked placeholders will be replaced with new light and dark captures.

## Product demo

The current edited demo shows the OSS Launch Planner: a task using a Notion brief and GitHub research, an interactive artifact and a sharing link. Waiting time has been removed; the report contains snapshot data.

<video src="https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953" controls muted playsinline style="width:100%"></video>

## Where you land

### Dashboard

Arrangeable widgets, the whole deployment first and then this organization. Runs, spend, service health and answer quality; each card is gated on the permission its own data needs, so a card whose primary read you cannot make is a card you are not offered.

> **Screenshot pending — Dashboard.**

### Chat, mid-run

The agent thinking, then the shell commands it actually ran in the sandbox, each one expandable. Transparency is the product here: what a tool did is on screen, not in a log somebody else can read.

> **Screenshot pending — Chat, mid-run.**

## Building an agent

### Agents

The catalog. Every agent carries the version that is live, who may reach it, and whether a draft is waiting. An agent is configuration, not code - which is why this list is editable by whoever knows the answer.

> **Screenshot pending — Agents.**

### Agent templates

Templates by industry, over the catalog. Installing one creates a draft you finish and publish; nothing runs until you do.

> **Screenshot pending — Agent templates.**

### Skills

Know-how written once and shared by every agent bound to it - how refunds are handled, what the house style is. Edit it here and each agent bound to it is current on its next run.

> **Screenshot pending — Skills.**

### Skill gallery

Skills by industry. Installing copies one into your organization, where you can edit it - a copy, so upstream cannot change what your agents say.

> **Screenshot pending — Skill gallery.**

### One skill

Open for editing, with its category. The name the model refers to is fixed at creation and cannot change; everything else here can.

> **Screenshot pending — One skill.**

### Context

Standing context every agent can draw on - a glossary, a policy, a brand voice. Injected into the prompt or read on demand, and current the moment you edit it.

> **Screenshot pending — Context.**

## Inside one agent

The Builder, tab by tab. New screenshots are pending for the current interface.

### Build

Instructions, model and endpoint. The behaviour lives here rather than in code, in Markdown the model reads for structure - and the header carries `published` beside `Draft differs from v40`, which is the whole point: editing does not ship.

> **Screenshot pending — Build.**

### Toolbox

Every capability as a switch - knowledge search, a browser, Python in a sandbox, charts, delegation - and the per-tool approval gate beside each. Configuration reaches only what code registered.

> **Screenshot pending — Toolbox.**

### MCP servers

Which connections this agent may reach, and which of their tools. The organization's list still bounds it; an agent can narrow inside that and cannot reach past it.

> **Screenshot pending — MCP servers.**

### Limits

One monthly cap and a step ceiling. The cap is checked before each model request, and the step limit catches the other runaway - a tool loop that is cheap per call and never finishes.

> **Screenshot pending — Limits.**

### Availability

Where this agent answers: the dashboard and the API always, plus any chat bot bound here. An agent is mentionable by `@handle` only on the bots it is bound to.

> **Screenshot pending — Availability.**

### Routines, on the agent

What it does with nobody typing, on this same tab - a schedule that can be paused, or an event trigger.

> **Screenshot pending — Routines, on the agent.**

### History

Every version this agent has had. The one that was live in March is still readable, which is what makes a rollback a choice rather than an archaeology project.

> **Screenshot pending — History.**

### Visual map

The same agent as a graph: what reaches it, and what it reaches for. A dashed box is something nothing is attached to - a budget with no ceiling of its own reads as a gap rather than as a default.

> **Screenshot pending — Visual map.**
## Knowledge

### Knowledge bases

Collections. Group related documents into one, then choose in chat which collections an agent may search.

> **Screenshot pending — Knowledge bases.**

### A collection

Its documents, their chunk counts, and anything that failed to ingest with the reason. Chunk boundaries are what a search matches against, so a document re-uploaded after a settings change is re-chunked.

> **Screenshot pending — A collection.**

### Parsing, per upload

The choice nobody else exposes: **PyMuPDF**, **LiteParse** or **LlamaParse**, the chunking strategy, chunk size and overlap, OCR and its language. Set on the collection and overridable on the next file you add - because a scanned rate card and a Markdown runbook do not want the same parser, and the wrong one is the difference between an answer and a refusal.

> **Screenshot pending — Parsing, per upload.**

## What happened, and what is waiting

### Runs

Every run this organization made, with its status, surface, model, person and cost. A run is the process: it starts, it can be stopped, and it leaves a record.

> **Screenshot pending — Runs.**

### One run, opened

Tokens in and out, cost to four decimal places, how long it took, and the timeline of every turn and tool call. The chat it happened in is one click away.

> **Screenshot pending — One run, opened.**

### Approvals

Everything waiting on a person, with what the agent intends to do. An approval is decided exactly once - a second decision on a settled one is refused, which is the detail that makes the gate worth having.

> **Screenshot pending — Approvals.**

### Spend

What was actually spent, by period. A budget is checked *before* the model request rather than tallied afterwards, so a run that breaches one stops mid-answer and still records its cost.

> **Screenshot pending — Spend.**

### Routines

What agents do with nobody typing - on a schedule, or when an event arrives. Those runs are budgeted, approved and audited like any other.

> **Screenshot pending — Routines.**

### A new event trigger

Naming the event that starts a run, over the routines list.

> **Screenshot pending — A new event trigger.**

## The organization

### Organizations

Switch between them, manage members, and create new ones. Authority inside an organization is a membership row plus the permission catalog - there is no role column on a user.

> **Screenshot pending — Organizations.**

### Vault

Every key this organization has stored, sealed per tenant. Replaceable, never readable again; and rotating one is invisible to a published agent, which references the secret rather than its value.

> **Screenshot pending — Vault.**

### MCP servers

Connect any MCP server by URL and its tools become switches in the Builder. Connect it for the organization and every agent may use it; connect it for yourself and it stays in your own chat.

> **Screenshot pending — MCP servers.**

### Channels

The chat platforms this organization answers on - Slack, Telegram, Mattermost. A bot serves every agent bound to it, and the binding is made on that agent's Availability tab.

> **Screenshot pending — Channels.**

### Sandboxes

Where this organization's agents run shell commands and keep files. An agent names a connection by id, so moving to another host is one edit here rather than a republish of every agent.

> **Screenshot pending — Sandboxes.**

### Workspaces

The files agents are keeping for you. A workspace is scratch space - it is deleted with the conversation it belongs to, and is not a place to store anything durable.

> **Screenshot pending — Workspaces.**

## Deployment administration

### Users

Everybody who can sign in to this deployment, and the app-admin flag that is separate from any organization role.

> **Screenshot pending — Users.**

### All organizations

Every tenant on this deployment, with its owner, members and agents.

> **Screenshot pending — All organizations.**

### System

Database, Redis, the vector store and model access - the same checks `agenticos cmd doctor` runs, on a page.

> **Screenshot pending — System.**

### Deployment

This deployment's own identity and policy: sign-up, invitations, notices, and what a first-time visitor meets.

> **Screenshot pending — Deployment.**

## What is not here yet

New screenshots of the current interface are pending, including the Builder, sign-in and onboarding.

## Recap

The current video is available above. Screenshot placeholders identify the views still to capture; use matching light and dark frames when adding them.
