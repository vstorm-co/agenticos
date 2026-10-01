<div align="center">

<img src="docs/assets/amigo-walk.svg" alt="Amigo, the AgenticOS pet" width="144">

<h1>AgenticOS</h1>

<p>
  <b>Build AI agents that work with your team's documents and tools.</b><br>
  Configure them in your browser, get useful results, and keep track of their actions and costs.
</p>

<p>
  <a href="#see-it-in-action">Watch the demo</a> &middot;
  <a href="#quick-start">Quick start</a> &middot;
  <a href="#inside-the-platform">Explore the platform</a> &middot;
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

AgenticOS is an open-source, self-hosted workspace for creating and using AI agents.
An agent is an AI assistant you give a task, instructions, and access to selected documents and tools.
It can research a question, analyse a file, prepare a report, or perform a connected action.
You choose the capabilities and access available to each agent.

Teams configure agents and reusable procedures through the interface. Developers extend the platform
and integrate it with their applications. Operators manage access, deployment and usage in one place.

## See it in action

**From a Notion brief and GitHub research to an interactive decision page.**
The demo uses the **Claude Code like** agent to prepare an OSS project comparison, switch between
audiences in the resulting page, and create a sharing link. The report is an **artifact**:
a result you can open and use outside the conversation.

<video src="https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953" controls muted playsinline width="100%" poster="docs/assets/screens/oss-launch-planner-poster.webp">
  <img src="docs/assets/screens/oss-launch-planner-poster.webp" alt="Vstorm OSS Launch Planner: audience selection, project recommendation and source links" width="100%">
</video>

[Watch the video](https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953) · [View a screenshot](docs/assets/screens/oss-launch-planner-poster.webp)

*Edited demonstration with waiting time removed. Repository figures reflect the recording's snapshot;
the artifact does not fetch live data. Connections and capabilities are configured for this demo.*

## Start with a task

| Your task | What you give the agent | What you can ask for |
|---|---|---|
| Research a decision | A brief and access to relevant applications | A comparison with sources, recommendations and open questions |
| Analyse a spreadsheet | A CSV and a question | Calculations, charts and a downloadable result |
| Answer from company knowledge | Handbooks, policies or product documents | An answer with references you can check |
| Prepare a recurring report | Instructions, sources and a schedule | A new report or an updated artifact after each run |

These are starting points; enable the necessary tools and verify the result for your task.
[Build your first document agent](docs/howto/first-document-agent.md) or [explore more use cases](docs/use-cases.md).

## Quick start

Install Docker with Compose first. On macOS or Linux, run the command below; on Windows, use WSL2
with Docker Desktop's WSL2 integration. The installer guides you through model access, your login
and organization, then sets up the deployment with a starter agent.

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

Open the console at **http://localhost:3000**, sign in with the credentials you configured, and try
the starter agent. Next, add a document or connect a tool for your own task.

<details>
<summary>Inspect the installer or deploy another way</summary>

Read the [installer](scripts/quickstart.sh) before running it. To check prerequisites without installing:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- --check
```

For manual Docker Compose setup, pinned versions and troubleshooting, follow the [installation guide](docs/install.md).
For development from source, see [Contributing](CONTRIBUTING.md).

</details>

You operate the deployment. Models, document processing and connected tools may use external services,
depending on your configuration. See [deployment responsibilities](docs/rollout.md) and [data flows](docs/security.md).

## Inside the platform

Chat is where you ask for work. The rest of the workspace holds the instructions, knowledge,
connections, results and controls that make that work repeatable.

### Configure an agent

In **Agents**, create an assistant for a task, choose its model, write instructions and enable its tools.
Publish a version when it is ready for use. You can inspect earlier versions and roll back a change.
[Build an agent](docs/first-agent.md).

<!-- MEDIA: agent-builder | light + dark; same agent as the demo -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/agent-builder.webp">
  <img src="docs/assets/screens/light/agent-builder.webp" alt="Agent builder with instructions, selected model and published version alongside draft changes." width="100%">
</picture>

### Teach a reusable procedure

**Skills** are written procedures an agent can load when relevant: how to review a proposal,
reconcile a report or follow your writing style. Write a procedure once and attach it to the agents
that need it. [Learn about skills](docs/skills.md).

<!-- MEDIA: skills | capture light + dark -->
> **Screenshot placeholder — Skills:** the library and an open procedure with readable steps.

**Context** holds standing information such as product names, a glossary or communication guidelines.
Use it for facts and rules shared across tasks; choose whether the agent receives it automatically
or reads it on demand. [Learn about context](docs/context.md).

<!-- MEDIA: context | capture light + dark -->
> **Screenshot placeholder — Context:** a company context file open with its content and attachment settings.

### Give it documents to search

**Knowledge bases** organize documents into collections you attach to agents. The agent searches these
sources for relevant passages when answering. This is often called **RAG**, or retrieval-augmented generation.
[Add and process documents](docs/file-processing.md).

<!-- MEDIA: knowledge-bases | capture light + dark -->
> **Screenshot placeholder — Knowledge bases:** named collections showing how the team's knowledge is organized.

Open a collection to inspect its documents and processing status. Choose how supported documents are read,
including text recognition for scans (OCR).

<!-- MEDIA: knowledge-collection | capture light + dark -->
> **Screenshot placeholder — Collection detail:** document names, processing status and a readable document preview or search result.

### Connect the applications you work in

**MCP**, the Model Context Protocol, is a standard for connecting AI agents to tools and data sources.
The **MCP servers** page lets you configure compatible connections, such as the Notion and GitHub tools
used in the demo. Available actions depend on the server, credentials and tools enabled for the agent.
[Connect an application](docs/mcp.md).

<!-- MEDIA: mcp-connections | capture light + dark -->
> **Screenshot placeholder — Application connections:** connected Notion and GitHub servers and selected tools, with credentials hidden.

### Keep results outside the chat

**Artifacts** are pages an agent creates: reports, interactive comparisons or small dashboards.
Open them from the library, inspect versions and choose who can access them. Updating the same artifact
keeps its current-page link; a conversation can link to a particular version.

An artifact displays the data it was published with. A new agent run can update it.
[Create and share artifacts](docs/artifacts.md).

<!-- MEDIA: artifacts | capture light + dark; use the OSS Launch Planner from the video -->
> **Screenshot placeholder — Artifacts:** the library and the OSS Launch Planner open with its audience selector and recommendation.

### Inspect actions and costs

A **run** is one execution of an agent. **Activity / Runs** shows its status and recorded usage;
open a run to inspect the conversation and tool calls. Budget checks use recorded spend before model
requests; requests already in progress or concurrent runs can exceed a cap. [Budgets and audit history](docs/governance.md).

<!-- MEDIA: run-detail | capture light + dark; same run as the demo -->
> **Screenshot placeholder — Run detail:** status, duration, recorded cost and tool calls for the demonstrated task.

You can require human approval for supported tool actions. The approval request lets a person review
the proposed operation before deciding whether it should proceed. Access to agents and resources is
controlled through [roles and permissions](docs/permissions.md).

<!-- MEDIA: approval | capture light + dark; real pending operation -->
> **Screenshot placeholder — Approval:** a real action waiting for a decision, with the operation and approval controls visible.

### Schedule repeat work

**Routines** run an agent on a schedule or in response to a configured event. Use them for a weekly
brief or a recurring report. Runs use the configured access and controls and leave an execution record.
[Set up a routine](docs/triggers.md).

<!-- MEDIA: routines | capture light + dark; show an actual scheduled execution -->
> **Screenshot placeholder — Routines:** a report's schedule, last completed scheduled run and link to its result.

## Use it with your team

Use the web console, expose an agent through the API, or configure a supported channel such as Slack,
Telegram, Mattermost, a hosted page or a website widget. [Choose a channel](docs/channels.md).
The optional [desktop app](docs/desktop.md) brings the console into its own window, with a desktop pet
and a shortcut for sending a screenshot into a new chat.

Organizations, resource permissions, the credentials vault and usage dashboards help operators
manage the deployment. [Plan a rollout](docs/rollout.md).

## Is AgenticOS a fit?

AgenticOS is designed for teams that want to configure and use agents through a browser while
operating their own deployment. Engineers can add capabilities and integrations; task owners can
maintain instructions, documents and procedures through the interface.

If you want a managed service, account for the work of operating a self-hosted platform. If you only
need an agent library inside an existing application, evaluate a framework directly. Compare options
by the task, deployment model and controls you need in the [platform comparison guide](docs/about/comparison.md).

## For developers and operators

Built with FastAPI, Pydantic AI, PostgreSQL with pgvector, Redis, Prefect and Next.js.
Agent configuration selects capabilities registered by the platform; developers extend those capabilities in code.

| Start here | What it covers |
|---|---|
| [Architecture](docs/architecture.md) | Services, storage and execution |
| [Capabilities](docs/reference/capabilities.md) | Available tools and configuration |
| [API](docs/api.md) | Integration with your applications |
| [Models](docs/models.md) | Model providers and profiles |
| [Security](docs/security.md) | Data flows and deployment boundaries |
| [Testing](docs/testing.md) | Test suites and coverage scope |

Contributions are welcome. Read [Contributing](CONTRIBUTING.md) for setup and required checks,
and see the [roadmap](docs/ROADMAP.md) for planned work.

## License and support

[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) and [third-party notices](THIRD_PARTY_NOTICES.md)
for attribution and bundled components.

[Vstorm](https://vstorm.co/) maintains AgenticOS and can help with deployment, integrations and custom development.
Support and maintenance are agreed for each project.
