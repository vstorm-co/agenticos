<div align="center">

<h1><img src="docs/assets/amigo-walk.svg" alt="Amigo, the AgenticOS pet" width="64" valign="middle"> AgenticOS</h1>

<p>
  <strong>Sovereign Agentic AI Layer</strong><br>
  <b>AI agents your whole team can use and improve.</b><br>
  Open source. Build shared agents in your browser, on infrastructure you control.
</p>

<p>
  <a href="#quick-start">Quick start</a> &middot;
  <a href="#build-share-and-operate">Build, share and operate</a> &middot;
  <a href="#is-agenticos-the-right-fit">Is it a fit?</a> &middot;
  <a href="https://vstorm-co.github.io/agenticos/">Documentation</a>
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

AgenticOS is a self-hosted workspace for building and running shared AI agents. Give agents files, company knowledge and tools to work with. Let them run code, produce documents and publish results, then make the agents available to your team. Engineers extend its capabilities; domain experts maintain its instructions and knowledge.

<a href="docs/assets/screens/light/agent-builder.png">
  <img src="docs/assets/screens/light/agent-builder.png" alt="Agent builder showing instructions, model selection and a published version." width="100%">
</a>

## What you can do

| For your team | What AgenticOS provides |
|---|---|
| Build agents | Browser builder, model choice, tools and published versions |
| Get work done | Chat, file handling, code execution in sandboxes and connected apps |
| Reuse knowledge | Shared skills, context, searchable documents and sync sources |
| Deliver results | Downloadable files and shareable, versioned artifacts |
| Operate agents | Customizable dashboards, run history, approvals, budgets and routines |
| Organize access | Organizations, roles, department groups and company sign-in |

## Quick start

All it needs is Docker with Compose. On macOS or Linux, run:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

On Windows, run the same command inside WSL2 with Docker Desktop's WSL2 integration switched on.
The installer asks for a model provider and key, your login and an organization name, pulls the
published images and starts a deployment with a working agent in it.

Open **http://localhost:3000** and sign in with the login you chose during installation.

**Your first agent:** follow the [document-assistant walkthrough](https://vstorm-co.github.io/agenticos/howto/first-document-agent/) to upload a handbook, ask questions and check answers against cited sources and test an updated document. Document search requires an embedding model. For other tasks, see [Build an agent](https://vstorm-co.github.io/agenticos/first-agent/).

<details>
<summary>Inspect the installer or deploy another way</summary>

Read the [installer](scripts/quickstart.sh) before running it. To check prerequisites without installing:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- --check
```

For manual Docker Compose setup, pinned versions and troubleshooting, follow the [installation guide](https://vstorm-co.github.io/agenticos/install/).
For development from source, see [Contributing](https://vstorm-co.github.io/agenticos/help/).

</details>

## Build, share and operate

### Give agents files, tools and a sandbox

Ask an agent to analyze a spreadsheet, produce a chart, prepare a document or work on a repository. With a container-backed sandbox configured and command execution enabled, it can **read and edit files, run shell commands, and execute Python or JavaScript**. The bundled workbench includes data, charting and document tools, including LibreOffice.

If you use [Claude Code](https://code.claude.com/docs/en/overview) or [Codex](https://developers.openai.com/codex/cli/), the file-and-command workflow will feel familiar. AgenticOS brings that kind of work into a shared, self-hosted workspace with company knowledge, reusable agents and organization access controls. What an agent can accomplish depends on its model, enabled tools and instructions.

<a href="docs/assets/screens/light/chat.png">
  <img src="docs/assets/screens/light/chat.png" alt="Existing conversation analyzing a sales CSV, with a regional revenue chart and the agent's findings." width="100%">
</a>

The conversation above shows a CSV analysis and a chart from an existing run. Open tool calls to inspect the commands behind an answer, and use the file panel to reach its inputs and outputs.

Run container sandboxes on your own infrastructure or configure a supported remote backend. Choose the workspace lifetime and execution limits for the job. [Sandbox configuration](https://vstorm-co.github.io/agenticos/sandbox/).

<details>
<summary>See sandbox connections</summary>

<img src="docs/assets/screens/light/sandboxes.png" alt="Sandbox connections with local container hosts, vault-backed credentials and runtime selection." width="100%">

</details>

### Build an agent your colleagues can reuse

Choose its model, instructions and tools in the browser. Publish a version for colleagues to use; inspect earlier versions and roll back when needed. Keep specialized agents for research, reporting, coding or operations in one catalog.

<details>
<summary>See the agent catalog</summary>

<img src="docs/assets/screens/light/agents.png" alt="Agent catalog with published agents, their descriptions and version status." width="100%">

</details>

Colleagues can use a published agent in **web chat, Slack, Mattermost or Telegram** when those channels are configured. Developers can call it through the API. [Build an agent](https://vstorm-co.github.io/agenticos/first-agent/) · [Connect a channel](https://vstorm-co.github.io/agenticos/channels/).

### Give agents your team's knowledge and ways of working

- **Skills** hold reusable procedures: how to review code, write a report or research a market. Maintain them once and reuse them across agents.
- **Context** holds standing knowledge such as a glossary, policy or brand voice. Include it in the prompt or let the agent read it on demand.
- **Knowledge bases (RAG)** make uploaded documents searchable. Inspect processing status and chunks, choose parsing options, or configure sync sources such as Google Drive and S3.

<a href="docs/assets/screens/light/skills.png">
  <img src="docs/assets/screens/light/skills.png" alt="Skills library filtered to Design, Engineering, Finance and Research." width="100%">
</a>

[Skills](https://vstorm-co.github.io/agenticos/skills/) · [Context](https://vstorm-co.github.io/agenticos/context/) · [Document processing](https://vstorm-co.github.io/agenticos/file-processing/) · [Sync sources](https://vstorm-co.github.io/agenticos/howto/configure-sync-sources/).

<details>
<summary>See the open glossary and a knowledge collection</summary>

<img src="docs/assets/screens/light/context-detail.png" alt="Glossary open in Preview, enabled and configured for on-demand reading." width="100%">

<img src="docs/assets/screens/light/knowledge-collection.png" alt="The vstorm knowledge collection with an indexed document, parser and processing status." width="100%">

</details>

### Turn results into pages people can use

Agents can publish reports, interactive comparisons and small dashboards as **artifacts**. Choose who can open them; updates keep the same link and earlier versions remain readable. The example below is the OSS Launch Planner, built from a Notion brief and GitHub research.

<a href="docs/assets/screens/light/artifact-detail.png">
  <img src="docs/assets/screens/light/artifact-detail.png" alt="OSS Launch Planner artifact with audience selection, project recommendations and source links." width="100%">
</a>

[Share an artifact](https://vstorm-co.github.io/agenticos/artifacts/).

<details>
<summary>See the artifacts library</summary>

<img src="docs/assets/screens/light/artifacts.png" alt="Artifacts library with page previews, versions and sharing visibility." width="100%">

</details>

### See what is running, what it costs and what needs attention

Customize the **dashboard** around your work: arrange and resize widgets, color sections and save layouts. Track usage, outcomes, recorded spend, approvals and sandbox capacity. Permissions determine which data a person can see.

<a href="docs/assets/screens/light/dashboard.png">
  <img src="docs/assets/screens/light/dashboard.png" alt="Customized dashboard with usage totals, recorded spend, run trends and outcomes." width="100%">
</a>

**Activity** lets you inspect runs and tool calls, compare agent versions and export records. Configure approval policies for supported tools, then use **routines** to repeat work on schedules or events. Some costs depend on provider usage and pricing data; external services can bill separately.

[Run history, budgets and approvals](https://vstorm-co.github.io/agenticos/governance/) · [Routines](https://vstorm-co.github.io/agenticos/triggers/).

<details>
<summary>See Activity and approval controls</summary>

<img src="docs/assets/screens/light/activity.png" alt="Activity showing recorded runs, statuses, model usage and costs." width="100%">

Approval coverage depends on the tool and execution mode. In web chat, **Ask about everything** also gates MCP tool calls handled by the runner. [Approval modes and limits](https://vstorm-co.github.io/agenticos/governance/#how-much-one-conversation-wants-to-be-asked).

</details>

### Organize access around your company

**Roles define what people may do. Groups define who you share with.** Use roles such as Builder, Operator, Member and Viewer, then create departments or working groups such as **Operations, Engineering, Finance and Research**. Share an agent, skill, collection, context file or artifact with a group in one step. Group grants add access alongside a person's role and individual grants.

<a href="docs/assets/screens/light/groups.png">
  <img src="docs/assets/screens/light/groups.png" alt="Organization groups for Engineering, Finance, Operations and Research, with descriptions and membership controls." width="100%">
</a>

Bring existing company accounts through **OIDC single sign-on, LDAP directory login or Kerberos integrated Windows sign-in**, with the appropriate deployment configuration. **Directory mappings** connect external directory groups to an organization role and optional AgenticOS group; membership is reconciled at sign-in.

[Roles and resource permissions](https://vstorm-co.github.io/agenticos/permissions/) · [Groups, LDAP, Kerberos and directory mappings](https://vstorm-co.github.io/agenticos/directory/).

<details>
<summary>See organization members and the role matrix</summary>

<img src="docs/assets/screens/light/members.png" alt="Organization members with assigned roles and membership management controls." width="100%">

<img src="docs/assets/screens/light/roles.png" alt="Permission matrix comparing Owner, Admin, Builder, Operator, Member and Viewer roles." width="100%">

</details>

## Recorded integration example

This demo shows a Notion brief becoming a sourced, interactive page after GitHub research. It uses Vstorm's own open-source projects as sample material: the useful sequence is **brief → research → shared result**. It is a product demonstration, not a customer outcome study.

<video src="https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512" controls playsinline width="100%" poster="docs/assets/screens/oss-launch-planner-poster.webp">
  <img src="docs/assets/screens/oss-launch-planner-poster.webp" alt="Vstorm OSS Launch Planner: audience selection, project recommendation and source links" width="100%">
</video>

[Watch the shortened video (37 seconds)](https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512) · [View a screenshot](docs/assets/screens/oss-launch-planner-poster.webp)

## Connect the apps your team already uses

<img src="docs/assets/integrations/apps-glass.svg" alt="Sixteen app logos on dark glass tiles: Google Drive, Gmail, Outlook, Notion, GitHub, Slack, Telegram, Figma, Linear, Airtable, Dropbox, Mattermost, HubSpot, Stripe, Shopify, Supabase." width="1140">

Connect tools through **MCP**, alongside built-in sync sources and chat channels. The catalog includes curated connections and **5,700+ MCP server listings** mirrored from a registry. Listings are publisher-provided metadata; each connection needs its own setup and access review.

[Google Drive™ sync](https://vstorm-co.github.io/agenticos/howto/configure-sync-sources/) · [Gmail triggers](https://vstorm-co.github.io/agenticos/triggers/) · [MCP tools: Notion, GitHub, Linear and more](https://vstorm-co.github.io/agenticos/mcp/) · [Chat channels: Slack, Mattermost, Telegram](https://vstorm-co.github.io/agenticos/channels/).

[Outlook email and calendar](https://vstorm-co.github.io/agenticos/mcp/) connect through a third-party MCP service with its own account and permissions.

Some connections use third-party MCP services and require separate setup, accounts and permissions.

## Is AgenticOS the right fit?

Choose it when a team has repeated document or tool-based work, subject experts who can maintain the instructions, and someone responsible for operating a self-hosted deployment.

Evaluate it with one of your own tasks. [Compare approaches](https://vstorm-co.github.io/agenticos/about/comparison/) · [Plan a rollout](https://vstorm-co.github.io/agenticos/rollout/).

## Own your deployment, models and access

**Sovereign means control over deployment, model providers, data flows and agent access.** AgenticOS is Apache-2.0 software you can inspect, modify and operate. Choose hosted providers or local models through Ollama and compatible endpoints such as vLLM. [Configure models](https://vstorm-co.github.io/agenticos/models/).

Self-hosting the console does not make every model, parser or tool local. Review the destinations you configure and the data they receive. Assign resource permissions, store credentials in the encrypted vault and test the approval policy for the tools you enable.

[Security and data flows](https://vstorm-co.github.io/agenticos/security/) · [Access controls](https://vstorm-co.github.io/agenticos/permissions/) · [Secrets](https://vstorm-co.github.io/agenticos/secrets/) · [Execution and cost controls](https://vstorm-co.github.io/agenticos/governance/).

## For developers and operators

Built with FastAPI, Pydantic AI, PostgreSQL with pgvector, Redis, Prefect and Next.js. Engineers add capabilities in typed Python; teams compose agents from the registered capabilities in the console.

[Architecture](https://vstorm-co.github.io/agenticos/architecture/) · [Capabilities](https://vstorm-co.github.io/agenticos/reference/capabilities/) · [API](https://vstorm-co.github.io/agenticos/api/) · [Contributing](https://vstorm-co.github.io/agenticos/help/).

The [operating-system analogy](https://vstorm-co.github.io/agenticos/about/) explains the architecture. The optional [desktop app](https://vstorm-co.github.io/agenticos/desktop/) adds a dedicated window, a pet and a macOS screenshot shortcut. Explore [Vstorm's open-source projects](https://github.com/vstorm-co) for the libraries and tools around AgenticOS.

## License

[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) and [third-party notices](THIRD_PARTY_NOTICES.md)
for attribution and bundled components.

## Need help putting agents into production?

Vstorm deploys AgenticOS in client infrastructure, writes the documentation, defines the processes
and builds custom capabilities. Maintenance and support are agreed per engagement.

Built with care by [**Vstorm**](https://vstorm.co) · [Vstorm on GitHub](https://github.com/vstorm-co)
