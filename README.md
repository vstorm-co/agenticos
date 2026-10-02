<div align="center">

<h1><img src="docs/assets/amigo-walk.svg" alt="Amigo, the AgenticOS pet" width="64" valign="middle"> AgenticOS</h1>

<p>
  <b>Put AI to work across your company.</b><br>
  The open-source agent layer for shared agents, company knowledge and automation — on infrastructure you control.
</p>

<p>
  <a href="#see-it-in-action">Watch the demo</a> &middot;
  <a href="#quick-start">Quick start</a> &middot;
  <a href="#explore-the-agent-layer">Explore the agent layer</a> &middot;
  <a href="#why-an-operating-system">Why an OS</a> &middot;
  <a href="docs/index.md">Documentation</a>
</p>

<p>
  <a href="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml"><img src="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://github.com/vstorm-co/agenticos/releases"><img src="https://img.shields.io/github/v/release/vstorm-co/agenticos?label=release&color=blue" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-Apache--2.0-blue" alt="Apache-2.0"></a>
  <a href="https://ai.pydantic.dev"><img src="https://img.shields.io/badge/Powered%20by-Pydantic%20AI-E92063?logo=pydantic&logoColor=white" alt="Built with Pydantic AI"></a>
</p>

<p>
  <b>English</b> &middot;
  <a href="README.pl.md">Polski</a> &middot;
  <a href="README.de.md">Deutsch</a> &middot;
  <a href="README.es.md">Español</a>
</p>

</div>

Give an agent a brief, your documents and your tools. It researches, writes the report and publishes a page your team can open. Instructions, access and every run stay in one place, on cloud or local models.

<h3 align="center">🔌 5,700+ integrations via MCP &nbsp;·&nbsp; 🤝 Shared agents and knowledge<br>
📊 Built-in observability &nbsp;·&nbsp; 🏠 Self-hosted</h3>

## See it in action

**From a Notion brief and GitHub research to an interactive decision page.**

The agent reads the brief in Notion, researches the candidate repositories on GitHub and publishes an artifact
that recommends one project for each audience, with its sources.

<video src="https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512" controls playsinline width="100%" poster="docs/assets/screens/oss-launch-planner-poster.webp">
  <img src="docs/assets/screens/oss-launch-planner-poster.webp" alt="Vstorm OSS Launch Planner: audience selection, project recommendation and source links" width="100%">
</video>

<details>
<summary>Video not loading? Open the animated preview</summary>

<a href="https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512">
  <img src="docs/assets/screens/oss-launch-planner-preview.gif" alt="Vstorm OSS Launch Planner: audience selection, project recommendation and source links" width="100%">
</a>

*Animated preview at 2× speed. Click to watch the 37-second video with sound at normal speed.*

</details>

[Watch the shortened video (37 seconds)](https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512) · [View a screenshot](docs/assets/screens/oss-launch-planner-poster.webp)

## Quick start

All it needs is Docker with Compose. On macOS or Linux, run:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

On Windows, run the same command inside WSL2 with Docker Desktop's WSL2 integration switched on.
The installer asks for a model provider and key, your login and an organization name, pulls the
published images and starts a deployment with a working agent in it.

Open **http://localhost:3000** and sign in with the login you chose. If you accepted the defaults,
that is `admin@example.com` / `admin123`.

### Try your first task

In **Chat**, select **Getting Started** and paste this fictional brief. It needs nothing connected
to Notion or GitHub.

```text
Turn this brief into a launch checklist. Use only the facts below.
For each task, show the owner, deadline and missing information.
Do not invent dates or responsibilities.

Brief:
- The customer webinar is on 15 October.
- Maya owns the landing page; it must be ready by 8 October.
- Leo owns the demo, but its review date is undecided.
- Someone needs to send invitations by 10 October; no owner is assigned.
```

**Check the result:** the landing page should have Maya and 8 October; the demo should flag
its missing review date; invitations should flag the missing owner. Then open **Activity**: the run is
already there, with its model, tokens, duration and cost. Next, try your own brief or
[configure an agent with tools and company knowledge](docs/first-agent.md).

<details>
<summary>Inspect the installer or deploy another way</summary>

Read the [installer](scripts/quickstart.sh) before running it. To check prerequisites without installing:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- --check
```

For manual Docker Compose setup, pinned versions and troubleshooting, follow the [installation guide](docs/install.md).
For development from source, see [Contributing](CONTRIBUTING.md).

</details>

## 💬 Bring agents to where your team already works

<p align="center">
  <a href="docs/channels.md"><img src="docs/assets/channels/slack.svg" alt="Slack" width="176" height="64"></a>
  <a href="docs/channels.md"><img src="docs/assets/channels/mattermost.svg" alt="Mattermost" width="176" height="64"></a>
  <a href="docs/channels.md"><img src="docs/assets/channels/telegram.svg" alt="Telegram" width="176" height="64"></a>
</p>

Use your published agent in **Slack, Mattermost or Telegram**. Colleagues ask for help in the tools they already use, and the agent answers with its instructions, knowledge and tools. An `@mention` runs as the person who sent it, not as the bot.

The same published agent also answers in web chat, a website widget, a hosted page and your own application through the API, with one set of limits and one run history.

[Connect Slack, Mattermost and other channels](docs/channels.md).

## Explore the agent layer

Everything below lives in the browser console; none of it needs code.

<table>
<tr>
<td colspan="2" valign="top">

### 📄 Keep results outside the chat

**Artifacts** are pages an agent creates: reports, interactive comparisons or small dashboards.
Open them from the library, inspect versions and choose who can access them. Updating the same artifact
keeps its link; a conversation can link to a particular version. [Create and share artifacts](docs/artifacts.md).

<a href="docs/assets/screens/light/artifacts.webp">
  <img src="docs/assets/screens/light/artifacts.webp" alt="Artifacts library with saved reports and versions." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🤖 Configure an agent

In **Agents**, create an assistant for a task, choose its model, write instructions and enable its tools.
Publish a version when it is ready for use. Every earlier version stays readable, and rolling back is a click.
[Build an agent](docs/first-agent.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/agent-builder.webp">
  <img src="docs/assets/screens/light/agent-builder.webp" alt="Agent builder with instructions, selected model and current published version." width="100%">
</a>

</td>
</tr>
<tr>
<td colspan="2" valign="top">

### 🔌 5,700+ integrations through MCP

Connect agents to the tools your company already uses: **GitHub, Notion, HubSpot, Linear and n8n**.
**MCP** (Model Context Protocol) is the standard that lets agents call external tools and data sources.

Search the catalog by name, or add a compatible server by URL.
Connect the services you need and choose which tools each agent can use. [Connect your tools](docs/mcp.md).

<a href="docs/assets/screens/light/mcp-catalog.webp">
  <img src="docs/assets/screens/light/mcp-catalog.webp" alt="MCP catalog showing GitHub, Notion, Slack and other services, with connection status." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🧩 Teach a reusable procedure

**Skills** are written procedures an agent can load when relevant: how to review a proposal,
reconcile a report or follow your writing style. Write a procedure once and attach it to the agents
that need it. Edit it, and the next answer uses it, with no release. [Learn about skills](docs/skills.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/skill-detail.webp">
  <img src="docs/assets/screens/light/skill-detail.webp" alt="The artifact-pages procedure with instructions and page templates." width="100%">
</a>

</td>
</tr>
<tr>
<td colspan="2" valign="top">

### 📚 Give it documents to search

**Knowledge bases** organize documents into collections you attach to agents. The agent searches these
sources for relevant passages when answering. This is often called **RAG**, or retrieval-augmented generation.
Choose the PDF reader, chunking and OCR per collection. [Add and process documents](docs/file-processing.md).

<a href="docs/assets/screens/light/knowledge-bases.webp">
  <img src="docs/assets/screens/light/knowledge-bases.webp" alt="Knowledge bases with personal and organization collections." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🧠 Shared context

**Context** holds standing information such as product names, a glossary or communication guidelines.
Use it for facts and rules shared across tasks; choose whether the agent receives it automatically
or reads it on demand. [Learn about context](docs/context.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/context-detail.webp">
  <img src="docs/assets/screens/light/context-detail.webp" alt="Glossary content in Preview with linked mode for reading on demand." width="100%">
</a>

</td>
</tr>
<tr>
<td colspan="2" valign="top">

### 📊 Built-in observability: see what ran and what it cost

**Activity** brings run history, approvals and spend into one place. Every run records its status,
model, tokens, duration and cost. Filter by agent, person or version, compare versions and export the
records as CSV. Open a run to see its conversation and every tool call.
[Explore Activity and cost controls](docs/governance.md).

<a href="docs/assets/screens/light/activity.webp">
  <img src="docs/assets/screens/light/activity.webp" alt="Activity with agent version comparisons and filtered run history showing status, tokens, duration and recorded cost." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🛡️ Human approval

Anything that sends, files or changes something can wait for a person. The approval request shows
the intended operation and its arguments, and the action runs only once someone approves it.
Access to agents and resources is controlled through [roles and permissions](docs/permissions.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/approval.webp">
  <img src="docs/assets/screens/light/approval.webp" alt="A pending tool action with its arguments and approval controls." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### ⏱️ Schedule repeat work

**Routines** run an agent on a schedule or in response to an event: the Monday brief, the recurring
report. A routine run has the same limits and the same record as anything a person asked for.
[Set up a routine](docs/triggers.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/routines.webp">
  <img src="docs/assets/screens/light/routines.webp" alt="Schedule editor with weekly repetition on Monday at 06:00 UTC and the agent message in Preview." width="100%">
</a>

</td>
</tr>
</table>

<details>
<summary>More views</summary>

<a href="docs/assets/screens/light/skills.webp">
  <img src="docs/assets/screens/light/skills.webp" alt="Skills library with reusable procedures." width="100%">
</a>

<a href="docs/assets/screens/light/context.webp">
  <img src="docs/assets/screens/light/context.webp" alt="Context library with shared glossary files." width="100%">
</a>

<a href="docs/assets/screens/light/knowledge-collection.webp">
  <img src="docs/assets/screens/light/knowledge-collection.webp" alt="The vstorm collection with adding_features.md processed successfully." width="100%">
</a>

<a href="docs/assets/screens/light/artifact-detail.webp">
  <img src="docs/assets/screens/light/artifact-detail.webp" alt="OSS Launch Planner from the demo with audience selection and recommendation." width="100%">
</a>

</details>

## Why an operating system

The name is a claim, so here are the criteria. An operating system does seven jobs; each row is a
mechanism you can read in the source.

| An operating system… | AgenticOS |
|---|---|
| **Runs and isolates processes** | Runs agents, isolates tenants in the schema and keeps every run with what it cost |
| **Enforces resource limits** | Monthly budgets per agent, checked *before* each model request |
| **Controls access** | A [permission catalog](docs/permissions.md) in code, roles composed from it, per-resource grants; an approval is the `sudo` |
| **Reaches hardware through drivers** | [27 model providers](docs/models.md) and [MCP servers](docs/mcp.md) behind one interface |
| **Keeps a filesystem** | [Collections, skills and context](docs/file-processing.md) in your own Postgres |
| **Gives many interfaces one shell** | One runner behind web chat, the API, Slack, Telegram, Mattermost, a widget, a hosted page and a schedule |
| **Writes an audit log** | Who ran what, when, what it cost and who approved it, written even when the run failed |

Apply the same seven to anything else in the category, us included:
[what makes something an operating system for agents](docs/about/index.md).

## Why it exists

Most agent frameworks give you a library. You write Python, you deploy it, and every change to an
agent's behaviour is a pull request, a review and a release. That is the right shape for a product
feature and the wrong shape for the forty small agents a company actually wants — because the person
who knows what the agent should say is not the person with commit access.

**Code defines, configuration composes.** A business team assembles agents in a browser and never
opens Python; engineers extend what there is to assemble, and configuration can only reach what code
registered. The ceiling is the capability registry, not a config file.

## Turn individual AI work into a team capability

For a recurring report, the team can divide the work:

1. **A subject expert defines the method:** maintain the instructions, skills and source knowledge.
2. **A builder makes the agent available:** configure its tools, publish a version and grant colleagues access.
3. **Colleagues use the results:** run the agent, review its output and share an artifact with the people who need it.

The agent and its know-how belong to the organization, not to whoever wrote the first prompt.
[Set up team access](docs/permissions.md).

## Own your deployment, models and access

**Run it on your infrastructure.** AgenticOS is Apache-2.0 software you can inspect, modify and operate.
Choose hosted model providers or local models through Ollama and compatible endpoints such as vLLM.
[Model configuration](docs/models.md).

**Decide what an agent may do.** Configure resource permissions, store credentials in the encrypted vault and
put a person's approval in front of tools that act. [Access controls](docs/permissions.md) · [Secrets](docs/secrets.md).

[Deploy and operate](docs/rollout.md) · [Execution and cost controls](docs/governance.md) · [Security and data flows](docs/security.md)

## Is AgenticOS the right fit?

Choose AgenticOS when your company wants shared agents, reusable knowledge and automation with control
over the source code, models and deployment. If you only need an agent library inside an existing
application, start with a framework.

Each comparison guide cites the vendor's own pages, shows where AgenticOS goes further, and names what it does not do yet.

- **Assistant apps:** [Claude](docs/about/claude-apps.md) · [ChatGPT](docs/about/chatgpt.md). Seats for employees, or agents your organization owns on any model.
- **Cloud-suite builders:** [Copilot Studio](docs/about/copilot-studio.md) · [Gemini Enterprise](docs/about/gemini-enterprise.md). A vendor's cloud and meter, or your infrastructure and your provider's prices.
- **Self-hosted builders:** [Dify](docs/about/dify.md) · [n8n](docs/about/n8n.md). Licence conditions and enterprise tiers, or Apache-2.0 with governance included.
- **Teammate service:** [Viktor](docs/about/viktor.md). One shared AI employee, or many agents with their own access and budgets.
- **Delivered agent layer:** [Wonderful](docs/about/wonderful.md). A system a vendor delivers, or one you own from day one.
- **Coding agents:** [Claude Code](docs/about/claude-code.md) · [Codex](docs/about/codex.md) · [OpenCode](docs/about/opencode.md). Built for developers; AgenticOS is for everyone else, and developers extend it.

[All comparisons, and the gaps](docs/about/comparison.md).

<details>
<summary>Questions about the agent layer</summary>

### Is AgenticOS an AI agent harness?

Yes, with a team interface around it. The harness is the loop that runs a model with tools: retrieval
over your documents, web search and a real browser, Python in a sandbox with files and a shell, charts,
images, delegation to subagents, a task list and conversation compaction. Each is a capability you switch
on per agent in the browser, alongside skills, context, MCP servers, budgets and approvals. Developers add
new capabilities in typed Python. See the [capabilities reference](docs/reference/capabilities.md).

### Can I create a Claude Code-like agent for business tasks?

Yes. Give an agent a sandbox with files and a shell, web search, a browser, delegation and a task list,
then attach the skills and context it needs. It plans multi-step work, reads before it acts, edits files,
runs commands, hands parts to specialists and checks the result. It answers in web chat, Slack or through
the API, on the model you choose, with approval in front of anything that acts. See the
[Claude Code comparison](docs/about/claude-code.md).

### What can colleagues share?

Teams can share agents, skills, context, knowledge collections and artifacts under resource permissions.
A shared agent can serve different people; a shared artifact gives colleagues a result they can open
outside the chat.

</details>

## On the desktop, if you like

The console is a web app, and a browser is all it needs. The optional [desktop app](docs/desktop.md)
is the same console in a window of its own, with a pet on the desktop and a global shortcut (`⌘⇧A`)
that screenshots any region straight into a new chat.

## For developers and operators

Built with FastAPI, Pydantic AI, PostgreSQL with pgvector, Redis, Prefect and Next.js.
Every published agent is also an endpoint, behind the same budget, approvals and run history as the console:

```bash
curl -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarize the open support tickets"}'
```

| Start here | What it covers |
|---|---|
| [Architecture](docs/architecture.md) | Services, storage and execution |
| [Capabilities](docs/reference/capabilities.md) | Available tools and configuration |
| [API](docs/api.md) | Integration with your applications |
| [Models](docs/models.md) | Model providers and profiles |
| [Security](docs/security.md) | Data flows and deployment boundaries |
| [Testing](docs/testing.md) | Test suites and coverage scope |

`make check` before a pull request: every CI job except e2e. New behaviour ships with a test; a bug
ships with a regression test. The core is held at 100% coverage and CI fails below it.

Three things that trip up a first change: a tool is code and an agent is not (there is no
`@agent.tool` — a capability registers, and then it is a switch in everybody's Builder);
`require(...)` gates go on collection routes only; and if the tool already exists as an MCP server,
write none. [Contributing](CONTRIBUTING.md) has the rest, [`.claude/`](.claude/README.md) has the
same conventions written for a machine, the [roadmap](docs/ROADMAP.md) shows planned work, and good
first issues are [labelled here](https://github.com/vstorm-co/agenticos/labels/good%20first%20issue).

<details>
<summary><b>The rest of the Vstorm OSS ecosystem</b></summary>

Everything below runs on [Pydantic AI](https://ai.pydantic.dev).

| Project | What it is | |
|---|---|---|
| **[full-stack-ai-agent-template](https://github.com/vstorm-co/full-stack-ai-agent-template)** | The generator AgenticOS was built from — FastAPI + Next.js, RAG, streaming, auth, 20+ integrations | [![Stars](https://img.shields.io/github/stars/vstorm-co/full-stack-ai-agent-template?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/full-stack-ai-agent-template) |
| **[pydantic-deepagents](https://github.com/vstorm-co/pydantic-deepagents)** | Open-source, self-hosted Claude Code — a terminal assistant and the framework behind it | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-deepagents?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-deepagents) |
| **[pydantic-ai-shields](https://github.com/vstorm-co/pydantic-ai-shields)** | Guardrails — cost tracking, prompt-injection detection, PII filtering, secret redaction | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-shields?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-shields) |
| **[subagents-pydantic-ai](https://github.com/vstorm-co/subagents-pydantic-ai)** | Nested subagent delegation, parallel execution, task cancellation | [![Stars](https://img.shields.io/github/stars/vstorm-co/subagents-pydantic-ai?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/subagents-pydantic-ai) |
| **[pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend)** | File storage and Docker-isolated sandboxes, with a permission system | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-backend?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-backend) |
| **[pydantic-ai-todo](https://github.com/vstorm-co/pydantic-ai-todo)** | Hierarchical task planning with PostgreSQL storage and an event system | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-todo?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-todo) |
| **[production-stack-skills](https://github.com/vstorm-co/production-stack-skills)** | Skill pack that turns a coding agent into a senior production engineer | [![Stars](https://img.shields.io/github/stars/vstorm-co/production-stack-skills?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/production-stack-skills) |
| **[content-skills](https://github.com/vstorm-co/content-skills)** | Content studio skill pack for coding agents — brand-aware, with built-in anti-slop | [![Stars](https://img.shields.io/github/stars/vstorm-co/content-skills?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/content-skills) |

Browse them all at **[oss.vstorm.co](https://oss.vstorm.co)**.

</details>

## License

[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) and [third-party notices](THIRD_PARTY_NOTICES.md)
for attribution and bundled components.

## Need help putting agents into production?

Vstorm deploys AgenticOS in client infrastructure, writes the documentation, defines the processes
and builds custom capabilities. Maintenance and support are agreed per engagement.

Built with care by [**Vstorm**](https://vstorm.co) · [oss.vstorm.co](https://oss.vstorm.co)
