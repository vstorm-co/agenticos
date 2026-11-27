---
title: "AgenticOS vs Onyx"
seo_title: "AgenticOS vs Onyx: company search or company agents"
description: "Compare Onyx and AgenticOS: enterprise search and chat against governed company agents, the ee licence, spending limits, approvals, channels and pricing."
---

# AgenticOS vs Onyx

Onyx is an open-source AI platform built around company search: chat with any model over 40+ connectors, with agents, MCP and bots in Slack and Discord. AgenticOS starts from the agent: each one has an owner, versions, a budget and approvals, and answers in many channels. If retrieval across many SaaS sources is the whole job, Onyx is strong. If agents act on behalf of the company, the governance differs.

Maintained by the AgenticOS team. Sources checked 26 November 2026. AgenticOS baseline: v1.95.0. Onyx scope: its repository, licence files, documentation and pricing page, not a tested deployment.

## At a glance

| Area | Onyx | AgenticOS |
| --- | --- | --- |
| What it is | Chat and enterprise search over company sources, with agents | Versioned company agents, workflows, apps and tables, built in a browser |
| Licence | MIT, with `ee` directories under the Onyx Enterprise License | Apache-2.0; see [bundled component licences](../licenses.md) |
| Where it runs | Self-hosted, including air-gapped, or Onyx cloud | Your infrastructure |
| Knowledge | 40+ connectors, strong retrieval | [Knowledge bases](../file-processing.md) with parser control and syncing connectors; no reranker yet |
| Spend control | Spending limits per workspace on Business, per user and group on Enterprise | A monthly budget per agent and per organization, checked before each model request |
| Approvals | Confirmed by the user, in its Craft feature | Approval per capability, tool and MCP connection, decided by the people you choose |
| Roles and sign-in | Custom roles and SCIM on Enterprise | Six roles and per-resource grants; OIDC SSO, LDAP and Kerberos |
| Tenancy | One organization per self-hosted install | Many organizations in one deployment |
| Channels | Web, Slack and Discord bots, widget, desktop app, Chrome extension | Web chat, widget, hosted page, HTTP API, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, email, iMessage, telephone calls; desktop and phone apps |
| Pricing | Community free; Business $20 per user a month; Enterprise custom | No licence fee; model usage at your provider's rates |

## Where AgenticOS goes further

### An agent is an object with an owner

In AgenticOS an agent is a [versioned spec](../concepts.md#version): instructions, model, capabilities and budget, published as a version that [environments](../environments.md#what-an-environment-is) promote and that exports as YAML. A business owner changes it in the [Builder](../features.md#exportable-into-your-own-repository) and every change is readable later.

### Governance in the open-source product

Onyx's production use of the `ee` directories needs a licence for the number of seats, and spending limits per user and group, SCIM and custom roles are Enterprise features. AgenticOS ships [budgets](../governance.md#enforcement-is-before-the-request), [approvals](../governance.md#approvals), the [tamper-evident audit log](../governance.md#audit) and [directory sign-in](../directory.md#signing-in-with-a-directory-account) in every deployment, with no seat fee.

### Approval by someone other than the user

An AgenticOS tool call can wait for a person you choose, [alerted](../governance.md#alerts) through the console, a channel or the [phone app](../mobile.md). Onyx describes confirmation by the user in its Craft feature.

### Channels beyond chat

The same published agent answers in [Microsoft Teams](../channels.md#microsoft-teams), [email](../channels.md#email), [SMS](../channels.md#sms), [telephone calls](../voice.md#telephone-calls) and a [hosted page](../channels.md#a-hosted-page), and other agents reach it over [A2A](../channels.md#a2a).

## When Onyx is the better fit

- Search across many SaaS sources is the main job, and its connectors cover your systems.
- Retrieval quality across those sources matters more to you than governing what agents do.
- One organization per install is enough and per-seat pricing suits you.

## Compare a change, not only an answer

Connect the same source in both products and ask the [first document agent](../howto/first-document-agent.md) questions. Then give an agent a tool that changes something harmless, require an approval from a second person, and cap its budget at a few cents. Record what each product allows, refuses and logs, with the [comparison method](comparison.md#a-shared-trial).

## Frequently asked questions

### Is Onyx open source?

Most of it is MIT. Code in its `ee` directories is under the Onyx Enterprise License, which needs a seat licence for production use. AgenticOS is Apache-2.0 throughout.

### Does AgenticOS replace enterprise search?

It answers from knowledge bases with synced connectors and parser control, but its focus is agents that act. If searching across dozens of SaaS tools is the main need, compare connector coverage first.

### Can both run air-gapped?

Yes. Onyx documents air-gapped deployment, and AgenticOS runs with local models, local embeddings and local parsing on your own hardware.

## Related comparisons

[AgenticOS vs Open WebUI and LibreChat](open-webui-librechat.md) · [AgenticOS vs a DIY stack](diy-stack.md) · [AgenticOS vs Dify](dify.md) · [All comparisons](comparison.md)

## Sources

- [Onyx repository](https://github.com/onyx-dot-app/onyx): features, connectors, deployment options and the licence split quoted above.
- [Onyx pricing](https://onyx.app/pricing): Community, Business and Enterprise plans.
- [Spending limits](https://docs.onyx.app/admins/advanced_configs/spending_limits): workspace, user and group limits.
