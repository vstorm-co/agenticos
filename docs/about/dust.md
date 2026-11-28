---
title: "AgenticOS vs Dust"
seo_title: "AgenticOS vs Dust: hosted agents or agents on your servers"
description: "Compare Dust and AgenticOS: a French SaaS for company agents against an Apache-2.0 platform you host. Hosting, spend limits, audit, channels and pricing."
---

# AgenticOS vs Dust

Dust calls itself a multiplayer operating system for enterprise AI: agents that work on company data, with MCP as client and server and agents in Slack, Microsoft Teams, email and Zendesk. It is a hosted service in a US or EU region, with single-tenant hosting on Enterprise. AgenticOS offers agents for the same buyer on infrastructure you run, under Apache-2.0, without a seat fee.

Maintained by the AgenticOS team. Sources checked 26 November 2026. AgenticOS baseline: v1.95.0. Dust scope: its website, pricing page, administrator documentation and press coverage of its May 2026 funding, not a tested workspace.

## At a glance

| Area | Dust | AgenticOS |
| --- | --- | --- |
| What it is | A hosted workspace for company agents on company data | A platform for company agents, workflows, apps and tables that you run |
| Licence | Proprietary | Apache-2.0; see [bundled component licences](../licenses.md) |
| Where it runs | Dust's cloud, US or EU region; single-tenant on Enterprise; no self-hosting | Your infrastructure, any cloud or on-premises |
| Models | Several providers | 28 providers, including local ones |
| Spend control | Credit limits per person, group and API key, checked before each message | A monthly budget per agent and per organization, checked before each model request |
| Audit | Tamper-evident audit on Enterprise | Tamper-evident audit log in every deployment |
| MCP | Client and server | Client and [server](../mcp.md#agenticos-as-an-mcp-server) |
| Channels | Web, Slack, Microsoft Teams, email, Zendesk | Web chat, widget, hosted page, HTTP API, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, email, iMessage, telephone calls |
| Pricing | Pro €24, Max €120 per user a month billed annually; Enterprise custom | No licence or seat fee; model usage at your provider's rates |

## Where AgenticOS goes further

### Hosting you choose

Dust runs only in its own cloud. AgenticOS runs [where you deploy it](../deploy.md), including on-premises and air-gapped, with local models if your data may not leave. See [what leaves by default](../data-protection.md#nothing-leaves-by-default).

### Limits on the agent, not only on the person

Dust limits credits per person, group and API key. AgenticOS also limits each agent: a [monthly budget](../governance.md#budgets) checked [before each model request](../governance.md#enforcement-is-before-the-request), so an agent that loops or is used heavily stops at its own cap without blocking anyone else.

### Governance in the open-source product

The [tamper-evident audit log](../governance.md#audit), [approvals](../governance.md#approvals), [directory sign-in](../directory.md#signing-in-with-a-directory-account) and [many organizations](../concepts.md#organizations) are in every AgenticOS deployment, not reserved for an enterprise contract.

### No seat fee

Dust charges per user. AgenticOS charges nothing per user; you pay model providers and run the infrastructure, yourself or with Vstorm.

## When Dust is the better fit

- You want a managed service that starts in minutes and you have no team to run servers.
- Its connectors and its Zendesk integration cover your systems.
- SAML and SCIM are a requirement; AgenticOS has neither yet.

## Compare a change, not only an answer

Build the same agent on the same documents in both products. Cap the agent's spend at a few cents and check what happens at the cap. Then ask your security team which of the two can keep all prompts and documents inside your network. Record the results with the [comparison method](comparison.md#a-shared-trial).

## Frequently asked questions

### Can Dust be self-hosted?

Not according to its public pages: it runs in Dust's cloud, in a US or EU region, with single-tenant hosting on Enterprise. AgenticOS is self-hosted by design.

### Does Dust have spend limits?

Yes, credit limits per person, group and API key, checked before each message. AgenticOS adds a budget per agent and per organization, checked before each model request.

## Related comparisons

[AgenticOS vs Langdock](langdock.md) · [AgenticOS vs deepset](deepset.md) · [Agents in Slack](slack-agents.md) · [All comparisons](comparison.md)

## Sources

- [Dust](https://dust.tt) and [pricing](https://dust.tt/pricing): product description, hosting regions and plans.
- [Credit management](https://docs.dust.tt/docs/user-documentation/admins/usage-seats-and-credits/credit-management): credit limits per person, group and API key.
- [Dust raises $40M Series B](https://tech.eu/2026/05/18/dust-raises-40m-series-b-to-build-the-multiplayer-operating-system-for-enterprise-ai/): the "multiplayer operating system" description.
