<div align="center">

<h1><img src="../docs/assets/amigo-walk.svg" alt="Amigo, the AgenticOS pet" width="64" valign="middle"> AgenticOS</h1>

<p>
  <strong>Sovereign Agentic AI Layer</strong><br>
  <b>AI agents your whole team can use and improve.</b><br>
  Open source. Build shared agents in your browser, on infrastructure you control.
</p>

<p>
  <a href="#quick-start">Quick start</a> &middot;
  <a href="#build-share-and-operate">Product tour</a> &middot;
  <a href="#what-ships-today">What ships</a> &middot;
  <a href="#where-it-stops-today">Limits</a> &middot;
  <a href="https://vstorm-co.github.io/agenticos/">Documentation</a>
</p>

<p>
  <a href="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml"><img src="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://github.com/vstorm-co/agenticos/releases"><img src="https://img.shields.io/github/v/release/vstorm-co/agenticos?label=release&color=blue" alt="Release"></a>
  <a href="../LICENSE"><img src="https://img.shields.io/badge/licence-Apache--2.0-blue" alt="Apache-2.0"></a>
  <a href="https://ai.pydantic.dev"><img src="https://img.shields.io/badge/Powered%20by-Pydantic%20AI-E92063?logo=pydantic&logoColor=white" alt="Built with Pydantic AI"></a>
</p>

</div>

AgenticOS is a self-hosted workspace where AI agents work with files, run code and use your company's tools and knowledge. Build and publish agents in the browser, share them with colleagues, and manage their access, cost and results in one place.

<img src="assets/builder-annotated.webp" alt="The agent builder with four numbered areas: name and status, tabs, instructions and model." width="100%">

## At a glance

| | |
|---|---|
| **26** built-in capabilities | knowledge search, web, Python, files and shell, charts, artifacts, delegation, guardrails… |
| **8** places an agent answers | web chat, website widget, hosted page, API, WebSocket, Slack, Mattermost, Telegram |
| **27** model providers | hosted, your cloud contract (Azure, Bedrock, Vertex) or local (Ollama, vLLM) |
| **5** document sync sources | Google Drive, S3/MinIO, websites, Git, SharePoint and OneDrive |
| **6** built-in roles | Owner, Admin, Builder, Operator, Member, Viewer, plus groups and grants |
| **29** tutorials | each with a sample input and a check you can run |

## Quick start

Start with Docker Compose and access to a model provider. On macOS or Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

On Windows, run it inside WSL2 with Docker Desktop's WSL2 integration. The installer asks for a model provider and key, your login and an organization name, then starts a deployment with a working agent. Open **http://localhost:3000**.

A host with **4 vCPU and 8 GB of RAM** runs it. [Inspect the installer first](../scripts/quickstart.sh), or follow the [installation guide](https://vstorm-co.github.io/agenticos/install/).

**Your first agent:** the [document-assistant walkthrough](https://vstorm-co.github.io/agenticos/howto/first-document-agent/) uploads a handbook, asks questions and checks the answers against cited sources.

## Build, share and operate

### Work with files and code

Ask an agent to analyse a spreadsheet, draw a chart or work on a repository. In a container sandbox it reads and edits files, runs shell commands and executes Python.

<img src="../docs/assets/screens/light/chat.png" alt="A sales CSV analysed in chat, with a regional revenue chart and the agent's findings." width="100%">

### Teach agents how your team works

**Skills** are procedures written once. **Context** is standing knowledge such as a glossary or a policy. **Knowledge bases** make your documents searchable, with citations.

<img src="assets/rag-pipeline.webp" alt="From a file to a cited answer: sources, read, split, embed, answer." width="100%">

### Publish results as pages

Agents publish reports and dashboards as **artifacts** with stable links, version history and controlled access.

<img src="../docs/assets/screens/light/artifact-detail.png" alt="Meridian sales dashboard built by an agent, labelled as demo data." width="100%">

### Track runs, costs and approvals

<img src="assets/dashboard-annotated.webp" alt="The dashboard with six numbered sections: time range, at a glance, runs over time, outcomes, run sources and adoption." width="100%">

Budgets are checked before each model request. Sensitive tools wait for a person's approval. Every run is recorded with its agent version, tools, tokens and cost.

### Organize teams

<img src="assets/organisation-model.webp" alt="Three layers: deployment, organisation and groups with six roles; resources with visibility and grants." width="100%">

Sign in with email and password, Google, OIDC single sign-on (Entra ID, Okta, Keycloak and others), LDAP or Kerberos.

## What ships today

<img src="assets/capabilities.webp" alt="26 built-in capabilities in six groups." width="100%">

<img src="assets/eight-surfaces.webp" alt="Eight places one agent can answer." width="100%">

## Where it stops today

<img src="assets/limits.webp" alt="Eight limits: source permissions, Microsoft 365 triggers, visual workflow builder, MFA/SAML/SCIM, search quality tools, scale-out, budgets under load and results." width="100%">

## For developers and operators

Built with FastAPI, Pydantic AI, PostgreSQL with pgvector, Redis, Prefect and Next.js. Engineers add capabilities in typed Python; teams switch them on in the console.

[Architecture](https://vstorm-co.github.io/agenticos/architecture/) · [Capabilities](https://vstorm-co.github.io/agenticos/reference/capabilities/) · [API](https://vstorm-co.github.io/agenticos/api/) · [Security](https://vstorm-co.github.io/agenticos/security/) · [Contributing](https://vstorm-co.github.io/agenticos/help/)

## License

[Apache License 2.0](../LICENSE). See [NOTICE](../NOTICE) and [third-party notices](../THIRD_PARTY_NOTICES.md).

## Need help putting agents into production?

Vstorm deploys AgenticOS in client infrastructure, writes the documentation, defines the processes and builds custom capabilities. Maintenance and support are agreed per engagement.

Built with care by [**Vstorm**](https://vstorm.co) · [Vstorm on GitHub](https://github.com/vstorm-co)
