---
title: "Compare AgenticOS"
seo_title: "AgenticOS comparisons: sovereign agentic AI layer"
description: "Compare AgenticOS with Claude, ChatGPT, Copilot Studio, Dify, n8n, Kortix, LobeHub, Onyx, Open WebUI, Langdock, Dust, deepset and agents in Slack."
---

# Compare AgenticOS

Most products in this space are one of five things: an assistant app, an agent builder, a teammate service, a delivered enterprise platform or a coding agent. AgenticOS is a sovereign layer for a company's agents that you run yourself. The usual starting point is the same everywhere: people use their own AI accounts, so know-how, memory and spend sit outside the company, and IT wants one governed place instead. These guides show where each option fits and what AgenticOS adds.

Maintained by the AgenticOS team. Vendor sources checked 21 October 2026 for the original guides (OpenAI Frontier's on 14 October), 2 November for Muse, Claude Duet, Grok Bot and OpenBot, and 26 November 2026 for the guides added then: open-source platforms, European vendors, agents in Slack, the DIY stack and licence terms. Review by 27 February 2027, or sooner when a vendor changes the offering a guide describes. Each guide names its sources. No competitor account was exercised for these guides.

AgenticOS feature statements refreshed on 27 November 2026 against v1.95.0 in every guide. Older vendor source-check dates are unchanged; that refresh is not a fresh vendor pricing audit.

## Pick the guide for your decision

| You are weighing | Products | Guide |
| --- | --- | --- |
| A company chat assistant, or agents your organization owns | Claude Team and Enterprise, ChatGPT Business and Enterprise | [Claude](claude-apps.md) · [ChatGPT](chatgpt.md) |
| A builder inside a vendor's cloud suite | Microsoft Copilot Studio, Google Gemini Enterprise | [Copilot Studio](copilot-studio.md) · [Gemini Enterprise](gemini-enterprise.md) |
| A self-hosted builder or automation tool | Dify, n8n | [Dify](dify.md) · [n8n](n8n.md) |
| An open-source platform for company agents | Kortix CompanyOS, LobeHub, Agno AgentOS, OpenAgents, OpenHuman | [Kortix](kortix.md) · [LobeHub](lobehub.md) · [Agno](agno.md) · [OpenAgents](openagents.md) · [OpenHuman](openhuman.md) |
| A self-hosted company chat or search | Open WebUI, LibreChat, Onyx | [Open WebUI and LibreChat](open-webui-librechat.md) · [Onyx](onyx.md) |
| Assembling it from open-source parts | Open WebUI, LiteLLM, Langfuse, n8n, Keycloak | [DIY stack](diy-stack.md) · [Licence terms](licence-terms.md) |
| A European AI platform | Langdock, Dust, Mistral, deepset | [Langdock](langdock.md) · [Dust](dust.md) · [Mistral](mistral.md) · [deepset](deepset.md) |
| An agent inside Slack | Claude Tag, Slackbot | [Agents in Slack](slack-agents.md) |
| An always-on AI teammate with its own computer | OpenAI dots, Grok Bot, Viktor, Sauna | [dots](openai-dots.md) · [Grok Bot](grok-bot.md) · [Viktor](viktor.md) · [Sauna](sauna.md) |
| A vendor's platform or control plane for company agents | OpenAI Frontier, Microsoft Agent 365 | [Frontier](openai-frontier.md) · [Agent 365](microsoft-agent-365.md) |
| A hosted agent runtime for developers | Claude Managed Agents | [Managed Agents](claude-managed-agents.md) |
| An open-source personal agent | OpenClaw, NVIDIA NemoClaw | [OpenClaw](openclaw.md) |
| A delivered enterprise platform | Wonderful | [Wonderful](wonderful.md) |
| A coding agent, or a layer for everyone else | Claude Code, OpenAI Codex, OpenCode | [Claude Code](claude-code.md) · [Codex](codex.md) · [OpenCode](opencode.md) |

## The field at a glance

| Product | What it is | Where it runs | Source | Models |
| --- | --- | --- | --- | --- |
| **AgenticOS** | A sovereign layer for company agents, built in a browser | Your infrastructure | Apache-2.0 | 28 providers, including local ones |
| Claude Team / Enterprise | Anthropic's assistant workspace | Anthropic's cloud | Proprietary | Claude only |
| ChatGPT Business / Enterprise | OpenAI's assistant workspace, with workspace agents | OpenAI's cloud | Proprietary | OpenAI only |
| Copilot Studio | A low-code agent builder on Power Platform | Microsoft's cloud | Proprietary | OpenAI and Anthropic models, plus Azure Foundry |
| Gemini Enterprise | Google's employee agent platform and search | Google Cloud | Proprietary | Gemini in the app |
| Dify | A visual LLM app and workflow builder | Self-hosted or Dify Cloud | Modified Apache 2.0 with conditions | Many, including Ollama |
| n8n | Workflow automation with AI agent nodes | Self-hosted or n8n Cloud | Sustainable Use License | Many, including Ollama |
| Kortix CompanyOS | A company as a git repository of agents, skills and connectors | Kortix cloud, or self-hosted with sessions in Kortix's cloud | Elastic License 2.0 | Any |
| LobeHub | An AI workspace whose agents join team chats | LobeHub cloud or self-hosted | LobeHub Community License | 90+ providers |
| Agno AgentOS | A Python framework and runtime with a hosted control plane | Runtime self-hosted; control plane as SaaS | Apache-2.0 runtime; closed control plane | Any |
| OpenAgents | A shared workspace for people and agents from many runtimes | Hosted or self-hosted | Apache-2.0 | The connected agents' own |
| OpenHuman | A personal agent harness and desktop app | Desktop, terminal or server | GPL-3.0 | 26 providers and local models |
| Open WebUI | A self-hosted AI chat interface | Self-hosted | BSD-3 with a branding clause | OpenAI-compatible and Ollama |
| LibreChat | A self-hosted chat with agents and MCP | Self-hosted | MIT; admin panel AGPL-3.0 | All major providers |
| Onyx | Company search and chat with agents | Self-hosted or Onyx cloud | MIT with `ee` directories | Any |
| Langdock | A per-seat AI workspace with agents and workflows | SaaS on Azure in the EU | Proprietary | Multi-model, EU-hosted |
| Dust | A hosted workspace for company agents | Dust's cloud, US or EU region | Proprietary | Several providers |
| Mistral AI Studio | Models, assistant and agent platform from one vendor | Cloud, serverless or self-hosted | Proprietary platform | Mainly Mistral |
| deepset Haystack Enterprise Platform | A sovereign platform for Haystack agents and pipelines | Cloud, self-hosted, air-gapped, STACKIT | Proprietary; Haystack Apache-2.0 | Any |
| Claude Tag / Slackbot | Vendor agents inside Slack | Anthropic's or Salesforce's cloud | Proprietary | Claude only / Salesforce's choice |
| Viktor | One AI teammate per Slack or Teams workspace | Viktor's cloud | Proprietary | OpenAI, Anthropic, Google, xAI |
| Sauna | A proactive AI assistant per person, with memory | Sauna's cloud | Proprietary | Its own Lite model, or all models from the Basic plan |
| OpenAI dots | Always-on agents in ChatGPT, each with a cloud computer | OpenAI's cloud | Proprietary | OpenAI only |
| Grok Bot | Named teammates on a shared cloud computer | xAI's cloud | Proprietary | Grok only |
| OpenAI Frontier | A platform to manage enterprise AI coworkers | Locally, your cloud or OpenAI's | Proprietary | OpenAI |
| Microsoft Agent 365 | A control plane over agents across Microsoft 365 | Microsoft's cloud | Proprietary | Through the agents it governs |
| Claude Managed Agents | A hosted agent runtime for developers | Anthropic's cloud | Proprietary | Claude only |
| OpenClaw / NemoClaw | An open-source personal agent; NVIDIA's enterprise distribution | Your machine or server | Open source | Many |
| Wonderful | An enterprise AI platform with deployment teams | SaaS, single-tenant, your cloud or on-premises | Proprietary | Model-agnostic, routed per task |
| Claude Code | A coding agent for developers | Developer machines, Anthropic cloud | Proprietary | Claude only |
| OpenAI Codex | A coding agent for developers | Developer machines, OpenAI cloud | CLI Apache-2.0, cloud proprietary | OpenAI; the CLI also takes others |
| OpenCode | An open-source coding agent | Developer machines | MIT | 75+ providers |

Each cell is taken from the vendor's own pages; the guides link them. "Proprietary" describes the licence, not the quality.

## How much stays yours

Sovereignty here means four things you decide: where the product runs, which models it may use, what the licence lets you do with it, and whether the controls an IT and security review asks for come without a paid tier. Each cell is taken from the guides above or the vendor pages they link.

| Product | Where it runs | Models you may use | What the licence lets you do | Sign-in, audit and spend controls |
| --- | --- | --- | --- | --- |
| **AgenticOS** | Your infrastructure; a fresh install sends no prompts or documents anywhere, and diagnostics are on by default and can be switched off | Any of 28 providers, or local models only | Apache-2.0: read it, change it, brand it as your own and run it for others; the default PDF parser is AGPL-3.0, so a modified image you serve to others owes them its source ([details](../licenses.md#the-agpl-component)) | Sign-in: OIDC SSO, LDAP and Kerberos · Audit: tamper-evident log · Spend: budgets per agent and per organization · all in every deployment |
| Claude Team / Enterprise | Anthropic's cloud | Claude only | Proprietary | Sign-in: SSO on Team and Enterprise · Audit: Enterprise, 180 days of events · Spend: organization and user caps |
| ChatGPT Business / Enterprise | OpenAI's cloud; storage residency in ten regions on Enterprise | OpenAI only | Proprietary | Sign-in: SAML SSO on Business; SCIM and role-based access controls on Enterprise · Audit: Compliance API on Enterprise and Edu · Spend: credit pools and overage limits |
| Copilot Studio | Microsoft's cloud, in Power Platform environments | GPT models by default, Claude models, Azure Foundry models billed separately | Proprietary | Sign-in: Entra ID · Audit: Purview · Spend: monthly limits per agent |
| Gemini Enterprise | Google Cloud, in global, US, EU and some national regions | Gemini; other models only in custom agents on Agent Platform | Proprietary | Sign-in: Google Cloud IAM · Audit: Google Cloud audit logs · Spend: monthly limits on the billing account |
| Dify | Self-hosted or Dify Cloud | Many, including Ollama | Apache 2.0 with conditions: a multi-tenant service needs written permission, and the logo may not be changed | Sign-in: email; SSO on Enterprise · Audit: Enterprise · Spend: provider billing or Cloud message credits |
| Kortix CompanyOS | Kortix cloud, or self-hosted with agent sessions in Kortix's cloud sandboxes | Any, with your own keys | Elastic License 2.0: no hosted service for others, no circumventing the licence key | Sign-in: SAML and SCIM with an Enterprise key · Audit: reading it needs Enterprise · Spend: budget per workspace |
| LobeHub | LobeHub cloud or self-hosted | 90+ providers | LobeHub Community License: commercial use without modifying the code; derivatives need a commercial licence | Sign-in: SAML on Enterprise · Audit: Business plan · Spend: credit pool |
| Onyx | Self-hosted, including air-gapped, or Onyx cloud | Any | MIT core; `ee` directories need a seat licence in production | Sign-in: SCIM on Enterprise · Audit: OCSF stream · Spend: per workspace on Business, per user and group on Enterprise |
| Open WebUI | Self-hosted, including air-gapped | OpenAI-compatible and Ollama | BSD-3 with a branding clause above 50 users in 30 days | Sign-in: OIDC, LDAP and SCIM · Audit: not stated · Spend: not stated |
| LibreChat | Self-hosted | All major providers | MIT; admin panel with custom roles AGPL-3.0 | Sign-in: OIDC, SAML, LDAP · Audit: permission changes · Spend: token balance per user |
| Langdock | SaaS on Azure in the EU; single-tenant and on-premises for large contracts | Multi-model, EU-hosted, your own keys | Proprietary | Sign-in: SAML and SCIM on every plan · Audit: API, 90 days · Spend: limits per workspace, person, group, agent and workflow |
| Dust | Dust's cloud, US or EU region; no self-hosting | Several providers | Proprietary | Sign-in: not checked for this guide · Audit: tamper-evident on Enterprise · Spend: credits per person, group and API key |
| deepset Haystack Enterprise Platform | Cloud, self-hosted, air-gapped or STACKIT | Any | Proprietary platform; Haystack framework Apache-2.0 | Access control and observability; details through sales |
| n8n | Self-hosted or n8n Cloud in Frankfurt | Many, including Ollama | Sustainable Use License: internal business, non-commercial or personal use; paid features need a licence key that contacts n8n's licence server daily | Sign-in: SSO on paid plans · Audit: log streaming on Enterprise · Spend: execution quotas per plan |
| Viktor | Viktor's cloud, US-hosted by default | OpenAI, Anthropic, Google and xAI models, or your own OpenRouter key | Proprietary | Sign-in: SAML SSO · Audit: audit logs on Enterprise · Spend: credit pool with a monthly top-up cap, per-user caps on Enterprise |
| Sauna | Sauna's cloud; US infrastructure for US customers | Its own Lite model, or all models from the Basic plan | Proprietary | Sign-in: email or Google · Audit: not stated · Spend: credits per plan |
| OpenAI dots | OpenAI's cloud; the Pro plan was not offered in the EEA, Switzerland or the UK at launch | OpenAI only | Proprietary | Sign-in: ChatGPT accounts · Audit: not stated for dots · Spend: included in the plan |
| Grok Bot | xAI cloud | Grok Bot service | Proprietary | Enterprise: audit logs, OpenTelemetry export, MCP allowlist, SCIM; see [current scope](grok-bot.md) |
| OpenAI Frontier | Locally, your cloud or OpenAI's | OpenAI | Proprietary | Sign-in, audit and spend: not stated publicly; per-agent permissions and dashboards announced |
| Microsoft Agent 365 | Microsoft's cloud | Through the agents it governs | Proprietary | Sign-in: Entra ID · Audit: Purview · Spend: Microsoft 365 licensing |
| Claude Managed Agents | Anthropic's cloud | Claude only | Proprietary | Sign-in: Anthropic API keys · Audit: not stated · Spend: tokens plus a session-hour fee, organisation limits |
| OpenClaw / NemoClaw | Your machine or server | Many | Open source; NemoClaw is NVIDIA's distribution | Sign-in, audit and access control: minimal in OpenClaw; added by NemoClaw |
| Wonderful | Multi-tenant SaaS, single-tenant, your cloud, or air-gapped on-premises | Routed per task by the platform | Proprietary; agents and configuration export through its UI or API | Sign-in: not stated on its pages · Audit: audit logs in its AI Gateway · Spend: budget caps per team |

Dify, n8n, Onyx, Open WebUI, LibreChat and deepset also run on your own servers, and Wonderful offers air-gapped on-premises deployment. LibreChat also keeps all four answers with you; AgenticOS adds a budget per agent checked before each model request, approvals decided by other people and many organizations in one deployment.

Running AgenticOS yourself does not make every model, parser or tool local. Each outside service is one you add; see [what leaves by default](../data-protection.md#nothing-leaves-by-default).

## Spend limits are common; where they apply is not

Spend limits alone no longer set a product apart. Claude Tag limits spend per organization and Slack channel, Notion per member, Hermes Business per team member, Amazon Quick per user, LiteLLM per key, team and tag, Kortix per workspace, Onyx per workspace or user, Dust per person and group, and Langdock even per agent, in its paid SaaS.

What AgenticOS combines is a [budget per agent](../governance.md#budgets), checked [before each model request](../governance.md#enforcement-is-before-the-request) whichever provider and channel the request comes from, with [delegated work](../governance.md#delegation-spends-the-parents-budget) charged to the delegating agent, in the free open-source product on your own servers, and recorded in the same audit log as [approvals](../governance.md#approvals).

## Open source, with conditions

Most open-source rivals attach conditions: modified Apache (Dify, FastGPT), the Sustainable Use License (n8n), the Elastic License 2.0 (Kortix since February 2026), custom licences (LobeHub, Open WebUI) or enterprise directories (Onyx, LiteLLM, Langfuse). AgenticOS is Apache-2.0 with nothing held back. [Licence terms compared](licence-terms.md) quotes the clauses.

## What AgenticOS brings to every comparison

These run through every guide, so they are stated once here.

- **The deployment is yours.** It runs on your hardware with your own Postgres and storage, and a fresh install sends no prompts or documents anywhere; deployment diagnostics are on by default and can be switched off. A fully local setup is possible, with local chat models, local embeddings and local parsing. See [what leaves by default](../data-protection.md#nothing-leaves-by-default).
- **Any model, switched in one place.** [28 providers](../models.md#providers) sit behind a [model profile](../models.md#a-model-profile) with [fallbacks](../models.md#fallbacks). Change the profile and every agent using it moves, without a republish.
- **An agent is a versioned document.** Publishing freezes a [version](../concepts.md#version), [environments](../environments.md#what-an-environment-is) point at versions, and the spec [exports as YAML](../features.md#exportable-into-your-own-repository) into your own git repository.
- **Governance is in the open-source product.** [Budgets](../governance.md#enforcement-is-before-the-request) are checked before each model request. [Approvals](../governance.md#approvals) park a run until someone decides. The [audit log](../governance.md#audit) is tamper-evident. None of it waits for an enterprise tier.
- **Many teams, one deployment.** Organizations are tenants, isolated in the schema. The [permission model](../permissions.md#the-built-in-roles) has six roles and per-resource grants. [OIDC single sign-on, LDAP and Kerberos](../directory.md#signing-in-with-a-directory-account) map directory groups to roles.
- **One agent, every surface.** The same published agent answers in web chat, a widget, a hosted page, the HTTP API, a WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, email and iMessage, takes [telephone calls](../voice.md#telephone-calls), and other agents reach it over [A2A](../channels.md#a2a). See [surfaces](../channels.md).
- **Desktop and phone apps.** The [desktop app](../desktop.md) adds quick ask, work in an approved folder on your computer and local coding agents such as Claude Code and Codex. The [phone app](../mobile.md) shows pending approvals on a widget and takes shares from other apps.
- **Tested before it ships.** [Eval runs](../evals.md) score a version against a versioned dataset and a baseline, [suites](../evals.md#suites) can gate promotion, and the [authoring assistant](../authoring.md) proposes changes from evidence.
- **People and agents in one place.** A [project](../projects.md) gives a team and its agents shared files, instructions and chats, and the [coding agent](../reference/capabilities.md#coding-agent) hands software work to Claude Code or Codex in a sandbox. [AgenticOS is an MCP server](../mcp.md#agenticos-as-an-mcp-server) too, so those tools can list and run the company's agents.
- **Extensible in code.** A [capability](../howto/add-capability.md) is typed Python, and [any MCP server](../mcp.md) connects by URL. Configuration can only reach what code registered.
- **No seat fee.** You pay your model providers directly and run the infrastructure. Vstorm offers implementation help as a separate agreement; see [operation and implementation](../rollout.md).

## What AgenticOS does not do yet

A comparison that hides its own gaps is an advertisement. Check these against your requirements before a pilot.

- Roles are the six built-in ones; custom roles are not available yet.
- Sign-in has no SAML or SCIM yet; SAML works through an identity broker such as Keycloak. See [what directory sign-in does not do yet](../directory.md#what-this-does-not-do-yet).
- There is no trace dashboard and no reranker. Run history, cost and eval results exist, and traces export to Logfire. See [where it is not finished](index.md#where-this-one-is-not-finished).
- There is no WhatsApp channel. Telephone calls need your own Twilio number.
- There is no marketplace of community plugins or nodes, and fewer ready-made connectors than the largest suites.
- There are no security certifications for a managed service: you certify your own deployment, and the [security page](../security.md) maps its controls.
- AgenticOS now includes a visual workflow canvas with typed steps, branches and loops. Compare the required node types and integrations, rather than assuming either canvas covers the same jobs.
- An MCP binding set to `writes` trusts the server's own read-only marks, so a tool it mislabels as read-only runs unasked; `all` holds every call. See [what MCP does not get you](../mcp.md#what-mcp-does-not-get-you).
- OpenShift is not validated. A maintained [Kubernetes Helm chart](../kubernetes.md) deploys the API, worker and console with external data services; Docker Compose remains the single-host path.
- You operate it, or you agree the operation with Vstorm or another partner.

## A shared trial

Use the [first document agent](../howto/first-document-agent.md) fixture in both products. Ask the supported question and the missing-policy question. Change the request owner, reprocess the source and repeat. Keep the actual responses and configuration, including failures.

Record the product version or service plan, model, source processing, identity, tool access, approval configuration, channel, cost and operating owner. Start with retrieval only. If a tool action matters, agree a harmless test action and its expected approval before adding it.

## What the evidence means

A vendor description establishes a documented option, not its quality on your workload. No competitor account was exercised for these guides. Untested behavior stays unknown rather than becoming a missing-feature mark. Prices and plan contents change often, so confirm them on the linked page before you quote them.

For a published trial, report the exact inputs, actual outputs, failed attempts and configuration. Separate model usage from infrastructure, implementation and ongoing operation. Check [licences](../licenses.md), provider terms and the edition you would deploy.

## Frequently asked questions

### Is AgenticOS open source?

Yes. AgenticOS is licensed under Apache-2.0 and runs on your own infrastructure with Docker Compose. Some bundled components carry their own licences, listed on the [licences](../licenses.md) page.

### Is AgenticOS a self-hosted alternative to ChatGPT Enterprise or Claude Enterprise?

For agents your organization owns, yes. It runs agents on any of 28 model providers, OpenAI and Anthropic included, with budgets, approvals and audit logs in every deployment. It is not a personal assistant for every employee; see the [ChatGPT](chatgpt.md) and [Claude](claude-apps.md) guides.

### How much does AgenticOS cost?

There is no licence or seat fee. You pay your model providers at their own rates and run the infrastructure: [4 vCPU and 8 GB of RAM](../deploy.md) runs it. Implementation help from Vstorm is agreed separately.

### Which comparison should I read first?

Start from the kind of product you are weighing: an assistant app, a builder in a cloud suite, a self-hosted builder, a teammate service, a delivered platform or a coding agent. The [table at the top](#pick-the-guide-for-your-decision) points to each guide.

### Is AgenticOS the same as Agno AgentOS or other "agent OS" products?

No. In 2026 "agent OS" and "agentic OS" are used by many vendors, including Agno, Kortix, aiXplain and others. AgenticOS is the Apache-2.0 platform maintained by Vstorm at github.com/vstorm-co/agenticos. See [AgenticOS vs Agno AgentOS](agno.md).

### Which open-source platforms are closest to AgenticOS?

Kortix CompanyOS and LobeHub describe the same idea of agents working in a company's channels, Onyx, Open WebUI and LibreChat are the self-hosted chats IT often deploys first, and OpenAgents coordinates agents from many runtimes. The [table at the top](#pick-the-guide-for-your-decision) links a guide for each.

## Other starting points

A library such as [Pydantic AI](https://ai.pydantic.dev/) fits an agent embedded in your own application; AgenticOS runs on it and adds the application for configuring and operating agents. [OpenClaw](https://github.com/openclaw/openclaw) documents personal and shared-team deployments. [Lindy](https://www.lindy.ai/) offers a teammate service. These are further candidates, not products ruled out here.

Start with the [document task](../howto/first-document-agent.md), then review [operation and implementation](../rollout.md). The AgenticOS maintainers own these guides.

[Muse](muse.md) · [Claude Duet](claude-duet.md) — Sources checked 2 November 2026; AgenticOS baseline v1.35.0.

[AgenticOS vs OpenBot](openbot.md)
