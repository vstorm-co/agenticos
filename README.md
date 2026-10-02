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

AgenticOS is a self-hosted workspace for building and running shared AI agents. Give an agent a task, connect company documents and tools, and publish it for your team. Engineers extend its capabilities; domain experts maintain its instructions and knowledge.

## Give your team a shared way to work

An equipment-policy assistant needs someone who knows the policy, someone who configures the agent and colleagues who can use it. AgenticOS gives each of them a part in the same workflow:

1. **An expert maintains the method:** write instructions, reusable procedures and source documents.
2. **A builder publishes the agent:** choose its model and tools, set limits and grant access.
3. **Colleagues use and check it:** ask questions, review sources and share results. Operators inspect runs in Activity.

Changes to instructions and knowledge happen in the console. New capabilities are added in Python. [How to build an agent](docs/first-agent.md) · [Team access](docs/permissions.md).

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

### Build an assistant from a document

Start with the [equipment-policy walkthrough](docs/howto/first-document-agent.md). It includes a tiny fictional handbook, setup steps and a recorded test with its limitations. You need an embedding model for document search as well as the chat model.

1. Save the two lines below as `equipment-handbook.md` and upload it to a knowledge collection. Configure embeddings and wait for processing.
2. Create an agent, select its model and enable knowledge search for that collection. Instruct it to cite the handbook and say when an answer is missing. Publish the agent.
3. Ask the questions below in fresh conversations, then inspect the retrieved material and run in **Activity**.

```text
Equipment requests go to the office manager.
Include the item, reason and delivery location.
```

| Ask | Check against the source |
|---|---|
| Who handles an equipment request? | The office manager, with a citation to the handbook |
| Which details should an equipment request include? | Item, reason and delivery location |
| How much can I spend? | The spending allowance is not stated |

Then follow the guide to replace the document with an updated policy and test a fresh conversation. Once the answers check out, grant a colleague access to the agent and the required resources, and have them try it from their own account. [Configure access](docs/permissions.md) before using private documents.

The guide records a test on **v0.0.504, 25 September 2026**, including a retry and the answer after a document update. Treat it as a reproducible example; check your own model's answers against the source.

<details>
<summary>Only checking the installation? Try a task without document setup</summary>

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

</details>

<details>
<summary>Inspect the installer or deploy another way</summary>

Read the [installer](scripts/quickstart.sh) before running it. To check prerequisites without installing:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- --check
```

For manual Docker Compose setup, pinned versions and troubleshooting, follow the [installation guide](docs/install.md).
For development from source, see [Contributing](CONTRIBUTING.md).

</details>

## Recorded integration example

This demo shows a Notion brief becoming a sourced, interactive page after GitHub research. It uses Vstorm's own open-source projects as sample material: the useful sequence is **brief → research → shared result**. It is a product demonstration, not a customer outcome study.

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

## Build, share and operate

### Configure the work once

Choose the model, instructions and tools in the browser. Publish a version for colleagues to use; earlier versions remain available for inspection and rollback.

[Knowledge bases](docs/file-processing.md) supply searchable documents. [Skills](docs/skills.md) hold reusable procedures; [context](docs/context.md) holds shared facts and guidelines. Update these resources as the work changes.

<a href="docs/assets/screens/light/agent-builder.webp">
  <img src="docs/assets/screens/light/agent-builder.webp" alt="Agent builder showing instructions, model selection and a published version." width="100%">
</a>

Connect tools such as **GitHub, Notion, HubSpot or Linear** through [MCP](docs/mcp.md). The catalog combines curated connections with **5,700+ MCP server listings** mirrored from a registry. Registry entries are publisher-provided metadata, not tested integrations. Each connection needs its own setup and access review.

### Make the agent and its results available

Colleagues can use a published agent in web chat or through configured **Slack, Mattermost and Telegram** channels. Developers can call it through the API. [Connect a channel](docs/channels.md).

<p align="center">
  <a href="docs/channels.md"><img src="docs/assets/channels/slack.svg" alt="Slack" width="176" height="64"></a>
  <a href="docs/channels.md"><img src="docs/assets/channels/mattermost.svg" alt="Mattermost" width="176" height="64"></a>
  <a href="docs/channels.md"><img src="docs/assets/channels/telegram.svg" alt="Telegram" width="176" height="64"></a>
</p>

Agents can publish reports, interactive comparisons and small dashboards as **artifacts**. Choose who can open them; updates to the same artifact keep its link and earlier versions remain readable. [Share an artifact](docs/artifacts.md).

<a href="docs/assets/screens/light/artifacts.webp">
  <img src="docs/assets/screens/light/artifacts.webp" alt="Artifacts library with saved reports, access settings and versions." width="100%">
</a>

### Inspect runs and repeat useful work

**Activity** brings run history, approvals and recorded spend together. Inspect tool calls, compare agent versions and export records. Some costs depend on provider usage and pricing data; external services can bill separately. [Read the accounting limits](docs/governance.md).

<a href="docs/assets/screens/light/activity.webp">
  <img src="docs/assets/screens/light/activity.webp" alt="Activity with version comparisons and run history, including a pending approval." width="100%">
</a>

Configure approval requirements for supported capability tools. In web chat, **Ask about everything** also gates MCP tool calls handled by the runner. Approval coverage depends on the tool and execution mode; enabling a connection alone does not require approval. [Approval modes and limits](docs/governance.md#how-much-one-conversation-wants-to-be-asked).

When a task is ready to repeat, use [routines](docs/triggers.md) to run an agent on a schedule or an event. Test its tools, limits and approval policy before leaving it unattended.

## Is AgenticOS the right fit?

Choose it when a team has repeated document or tool-based work, subject experts who can maintain the instructions, and someone responsible for operating a self-hosted deployment.

| Your starting point | What to evaluate |
|---|---|
| You want colleagues to use and maintain shared agents | Try AgenticOS's builder, knowledge and publishing workflow. If a shared chat interface is enough, also evaluate [Open WebUI](https://github.com/open-webui/open-webui). |
| You mainly need to design workflows or AI applications | Compare the authoring workflow with [Dify](docs/about/dify.md) and [n8n](docs/about/n8n.md), using one of your real tasks. |
| You are building agents as part of a software product | Start with an SDK or runtime such as [Pydantic AI](https://ai.pydantic.dev) or [Agno](https://github.com/agno-agi/agno); decide whether you also need AgenticOS's team console. |

Self-hosting gives you an operating responsibility: upgrades, backups, credentials and provider bills. If nobody will own that work, settle the deployment and support arrangement before a pilot. [Rollout guide](docs/rollout.md) · [Detailed comparisons and gaps](docs/about/comparison.md).

## Own your deployment, models and access

**Sovereign means control over deployment, model providers, data flows and agent access.** AgenticOS is Apache-2.0 software you can inspect, modify and operate. Choose hosted providers or local models through Ollama and compatible endpoints such as vLLM. [Configure models](docs/models.md).

Self-hosting the console does not make every model, parser or tool local. Review the destinations you configure and the data they receive. Assign resource permissions, store credentials in the encrypted vault and test the approval policy for the tools you enable.

[Security and data flows](docs/security.md) · [Access controls](docs/permissions.md) · [Secrets](docs/secrets.md) · [Execution and cost controls](docs/governance.md).

## For developers and operators

Built with FastAPI, Pydantic AI, PostgreSQL with pgvector, Redis, Prefect and Next.js. Engineers add capabilities in typed Python; teams compose agents from the registered capabilities in the console.

[Architecture](docs/architecture.md) · [Capabilities](docs/reference/capabilities.md) · [API](docs/api.md) · [Contributing](CONTRIBUTING.md) · [Roadmap](docs/ROADMAP.md).

The [operating-system analogy](docs/about/index.md) explains the architecture. The optional [desktop app](docs/desktop.md) adds a dedicated window, a pet and a macOS screenshot shortcut. Explore [Vstorm's open-source projects](https://github.com/vstorm-co) for the libraries and tools around AgenticOS.

## License

[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) and [third-party notices](THIRD_PARTY_NOTICES.md)
for attribution and bundled components.

## Need help putting agents into production?

Vstorm deploys AgenticOS in client infrastructure, writes the documentation, defines the processes
and builds custom capabilities. Maintenance and support are agreed per engagement.

Built with care by [**Vstorm**](https://vstorm.co) · [Vstorm on GitHub](https://github.com/vstorm-co)
