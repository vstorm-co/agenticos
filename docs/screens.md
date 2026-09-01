# Every screen in the console

One page, every module, described. Screenshots follow the theme you are
reading the site in - switch it with the toggle in the header and every image
on this page switches with it.

Captured 2026-09-01 from a running deployment. Both themes of every screen are
in the repository under `docs/assets/screens/`, named identically in
`light/` and `dark/`.

## The chat, in twenty seconds

A CSV dropped into the conversation, one sentence of instruction, and the agent
writes Python, runs it in a sandbox, and answers with charts it drew from the
data. Nothing here was configured for this file in particular.

<video src="../assets/screens/chat-live-demo.mp4" poster="../assets/screens/chat-live-demo-poster.webp" controls muted loop playsinline style="width:100%"></video>

## Where you land

### Dashboard

Arrangeable widgets, the whole deployment first and then this organization. Runs, spend, service health and answer quality; each card is gated on the permission its own data needs, so a card whose primary read you cannot make is a card you are not offered.

![Dashboard](assets/screens/light/dashboard.webp#only-light)
![Dashboard](assets/screens/dark/dashboard.webp#only-dark)

### Chat, mid-run

The agent thinking, then the shell commands it actually ran in the sandbox, each one expandable. Transparency is the product here: what a tool did is on screen, not in a log somebody else can read.

![Chat, mid-run](assets/screens/light/chat-sandbox-commands.webp#only-light)
![Chat, mid-run](assets/screens/dark/chat-sandbox-commands.webp#only-dark)

## Building an agent

### Agents

The catalog. Every agent carries the version that is live, who may reach it, and whether a draft is waiting. An agent is configuration, not code - which is why this list is editable by whoever knows the answer.

![Agents](assets/screens/light/agents.webp#only-light)
![Agents](assets/screens/dark/agents.webp#only-dark)

### Agent templates

Templates by industry, over the catalog. Installing one creates a draft you finish and publish; nothing runs until you do.

![Agent templates](assets/screens/light/agents-templates-dialog.webp#only-light)
![Agent templates](assets/screens/dark/agents-templates-dialog.webp#only-dark)

### Skills

Know-how written once and shared by every agent bound to it - how refunds are handled, what the house style is. Edit it here and each agent bound to it is current on its next run.

![Skills](assets/screens/light/skills.webp#only-light)
![Skills](assets/screens/dark/skills.webp#only-dark)

### Skill gallery

Skills by industry. Installing copies one into your organization, where you can edit it - a copy, so upstream cannot change what your agents say.

![Skill gallery](assets/screens/light/skills-gallery-dialog.webp#only-light)
![Skill gallery](assets/screens/dark/skills-gallery-dialog.webp#only-dark)

### One skill

Open for editing, with its category. The name the model refers to is fixed at creation and cannot change; everything else here can.

![One skill](assets/screens/light/skill-detail.webp#only-light)
![One skill](assets/screens/dark/skill-detail.webp#only-dark)

### Context

Standing context every agent can draw on - a glossary, a policy, a brand voice. Injected into the prompt or read on demand, and current the moment you edit it.

![Context](assets/screens/light/context.webp#only-light)
![Context](assets/screens/dark/context.webp#only-dark)

## Knowledge

### Knowledge bases

Collections. Group related documents into one, then choose in chat which collections an agent may search.

![Knowledge bases](assets/screens/light/knowledge-bases.webp#only-light)
![Knowledge bases](assets/screens/dark/knowledge-bases.webp#only-dark)

### A collection

Its documents, their chunk counts, and anything that failed to ingest with the reason. Chunk boundaries are what a search matches against, so a document re-uploaded after a settings change is re-chunked.

![A collection](assets/screens/light/knowledge-base-detail.webp#only-light)
![A collection](assets/screens/dark/knowledge-base-detail.webp#only-dark)

### Parsing, per upload

The choice nobody else exposes: **PyMuPDF**, **LiteParse** or **LlamaParse**, the chunking strategy, chunk size and overlap, OCR and its language. Set on the collection and overridable on the next file you add - because a scanned rate card and a Markdown runbook do not want the same parser, and the wrong one is the difference between an answer and a refusal.

![Parsing, per upload](assets/screens/light/knowledge-base-upload-parsing-dialog.webp#only-light)
![Parsing, per upload](assets/screens/dark/knowledge-base-upload-parsing-dialog.webp#only-dark)

## What happened, and what is waiting

### Runs

Every run this organization made, with its status, surface, model, person and cost. A run is the process: it starts, it can be stopped, and it leaves a record.

![Runs](assets/screens/light/activity-runs.webp#only-light)
![Runs](assets/screens/dark/activity-runs.webp#only-dark)

### One run, opened

Tokens in and out, cost to four decimal places, how long it took, and the timeline of every turn and tool call. The chat it happened in is one click away.

![One run, opened](assets/screens/light/activity-run-detail.webp#only-light)
![One run, opened](assets/screens/dark/activity-run-detail.webp#only-dark)

### Approvals

Everything waiting on a person, with what the agent intends to do. An approval is decided exactly once - a second decision on a settled one is refused, which is the detail that makes the gate worth having.

![Approvals](assets/screens/light/activity-approvals.webp#only-light)
![Approvals](assets/screens/dark/activity-approvals.webp#only-dark)

### Spend

What was actually spent, by period. A budget is checked *before* the model request rather than tallied afterwards, so a run that breaches one stops mid-answer and still records its cost.

![Spend](assets/screens/light/activity-spend.webp#only-light)
![Spend](assets/screens/dark/activity-spend.webp#only-dark)

### Routines

What agents do with nobody typing - on a schedule, or when an event arrives. Those runs are budgeted, approved and audited like any other.

![Routines](assets/screens/light/routines.webp#only-light)
![Routines](assets/screens/dark/routines.webp#only-dark)

### A new event trigger

Naming the event that starts a run, over the routines list.

![A new event trigger](assets/screens/light/routines-event-trigger-dialog.webp#only-light)
![A new event trigger](assets/screens/dark/routines-event-trigger-dialog.webp#only-dark)

## The organization

### Organizations

Switch between them, manage members, and create new ones. Authority inside an organization is a membership row plus the permission catalog - there is no role column on a user.

![Organizations](assets/screens/light/organizations.webp#only-light)
![Organizations](assets/screens/dark/organizations.webp#only-dark)

### Vault

Every key this organization has stored, sealed per tenant. Replaceable, never readable again; and rotating one is invisible to a published agent, which references the secret rather than its value.

![Vault](assets/screens/light/vault.webp#only-light)
![Vault](assets/screens/dark/vault.webp#only-dark)

### MCP servers

Connect any MCP server by URL and its tools become switches in the Builder. Connect it for the organization and every agent may use it; connect it for yourself and it stays in your own chat.

![MCP servers](assets/screens/light/mcp-servers.webp#only-light)
![MCP servers](assets/screens/dark/mcp-servers.webp#only-dark)

### Channels

The chat platforms this organization answers on - Slack, Telegram, Mattermost. A bot serves every agent bound to it, and the binding is made on that agent's Availability tab.

![Channels](assets/screens/light/channels.webp#only-light)
![Channels](assets/screens/dark/channels.webp#only-dark)

### Sandboxes

Where this organization's agents run shell commands and keep files. An agent names a connection by id, so moving to another host is one edit here rather than a republish of every agent.

![Sandboxes](assets/screens/light/sandboxes.webp#only-light)
![Sandboxes](assets/screens/dark/sandboxes.webp#only-dark)

### Workspaces

The files agents are keeping for you. A workspace is scratch space - it is deleted with the conversation it belongs to, and is not a place to store anything durable.

![Workspaces](assets/screens/light/workspaces.webp#only-light)
![Workspaces](assets/screens/dark/workspaces.webp#only-dark)

## Deployment administration

### Users

Everybody who can sign in to this deployment, and the app-admin flag that is separate from any organization role.

![Users](assets/screens/light/admin-users.webp#only-light)
![Users](assets/screens/dark/admin-users.webp#only-dark)

### All organizations

Every tenant on this deployment, with its owner, members and agents.

![All organizations](assets/screens/light/admin-organizations.webp#only-light)
![All organizations](assets/screens/dark/admin-organizations.webp#only-dark)

### System

Database, Redis, the vector store and model access - the same checks `agenticos cmd doctor` runs, on a page.

![System](assets/screens/light/admin-system.webp#only-light)
![System](assets/screens/dark/admin-system.webp#only-dark)

### Deployment

This deployment's own identity and policy: sign-up, invitations, notices, and what a first-time visitor meets.

![Deployment](assets/screens/light/admin-deployment.webp#only-light)
![Deployment](assets/screens/dark/admin-deployment.webp#only-dark)

## Two screens that are not here yet

- **The Builder itself** - Build, Toolbox, MCP servers, Limits, Availability
  and History on one agent. `docs/first-agent.md` walks through it in prose.
- **Sign-in and onboarding**, which is what a first-time visitor actually meets.

## Recap

- Every module has both themes in `docs/assets/screens/`, under the same name.
- On this site an image is written twice, with `#only-light` and `#only-dark`;
  Material shows the one matching the reader's palette.
- In the README the same pair goes in a `<picture>` with
  `media="(prefers-color-scheme: dark)"`, which is how GitHub does it.
- Parsing is the setting worth knowing about before you upload anything: the
  parser and the chunk size decide whether a table can be answered at all.
