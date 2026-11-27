---
title: "AgenticOS vs LobeHub"
seo_title: "AgenticOS vs LobeHub: agents on your team, self-hosted"
description: "Compare LobeHub and AgenticOS: the LobeHub Community License against Apache-2.0, team channels, budgets, approvals, audit, roles and multi-tenancy."
---

# AgenticOS vs LobeHub

LobeHub calls its product "super-agents on your team": agents added to the chat tools a team already uses, with a workspace, 90+ model providers, MCP, memory and a skill market. AgenticOS makes the same promise of agents in the team's channels. The differences are the licence, the governance around each agent and how many organizations one deployment can serve.

Maintained by the AgenticOS team. Sources checked 26 November 2026. AgenticOS baseline: v1.95.0. LobeHub scope: its website, pricing page, documentation and the `LICENSE` file in `lobehub/lobehub`, not a tested workspace or self-hosted deployment.

## At a glance

| Area | LobeHub | AgenticOS |
| --- | --- | --- |
| What it is | An AI workspace with agents that join team chats | A console where a business team builds versioned agents, workflows, apps and tables |
| Licence | LobeHub Community License: Apache 2.0 with added commercial conditions | Apache-2.0; see [bundled component licences](../licenses.md) |
| Where it runs | LobeHub cloud, or self-hosted with Docker | Your infrastructure |
| Models | 90+ providers | 28 providers, including local ones |
| Channels | Discord, Slack, Telegram, LINE, WeChat, Feishu, DingTalk and others; WhatsApp and iMessage announced; no Microsoft Teams | Web chat, widget, hosted page, HTTP API, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, email, iMessage, telephone calls |
| Spend control | A credit pool with usage tracking | A monthly budget per agent and per organization, checked before each model request |
| Approvals | Confirmed by the person using the agent | Approval per capability, tool and MCP connection, decided by the people you choose |
| Roles and audit | Roles and audit on the Business workspace plan; SAML on Enterprise | Six roles, per-resource grants, OIDC SSO, LDAP, Kerberos and a tamper-evident audit log in every deployment |
| AgenticOS as an MCP server | MCP client; its own MCP server announced | MCP client and [MCP server](../mcp.md#agenticos-as-an-mcp-server) |
| Pricing | Personal plans $20, $100 and $200 a month; workspace plans from $19.90 a month | No licence fee; model usage at your provider's rates |

## Where AgenticOS goes further

### A licence without commercial conditions

The LobeHub Community License is based on Apache 2.0 with added conditions. LobeHub may be used commercially as a frontend and backend service **without modifying the source code**. Developing and distributing a derivative work needs a commercial licence from the producer, and contributors agree that the producer can make the terms stricter. Business features are not part of the open-source build.

AgenticOS is Apache-2.0. You may change it, brand it as your own and run it for others. See [licence terms compared](licence-terms.md).

### Governance on every agent

An AgenticOS agent has an owner, published [versions](../concepts.md#version), a [budget](../governance.md#budgets) checked before each model request and [approvals](../governance.md#approvals) routed to someone other than the person chatting. A second decision on a decided approval is refused, and every action lands in the [audit log](../governance.md#audit). In LobeHub, spend is tracked against a credit pool and a tool call is confirmed by its user.

### Microsoft Teams, phone and email

A published AgenticOS agent answers in [Microsoft Teams](../channels.md#microsoft-teams), over [email](../channels.md#email), [SMS](../channels.md#sms) and [telephone calls](../voice.md#telephone-calls), and in the same Slack, Telegram and Discord channels LobeHub covers. LobeHub lists no Teams channel.

### Many organizations in one deployment

AgenticOS [organizations](../concepts.md#organizations) are tenants isolated in the schema, so one deployment serves several companies or departments. LobeHub does not describe multi-tenant isolation for a self-hosted install.

## When LobeHub is the better fit

- You want a polished consumer-grade chat experience and a large skill market for a small team.
- Your teams work in LINE, WeChat, Feishu or DingTalk, which AgenticOS does not cover.
- You will use it unmodified, or the commercial licence suits you.

## Compare a change, not only an answer

Add one agent to the same Slack channel in both products. Ask it to run a tool that needs approval, then decide the approval as someone other than the person who asked. Give the agent a budget of a few cents and run it past the cap. Record what each product allows, refuses and logs, with the [comparison method](comparison.md#a-shared-trial).

## Frequently asked questions

### Is LobeHub open source?

Its code is public under the LobeHub Community License, which adds conditions to Apache 2.0: commercial use is allowed without modifying the code, and distributing a derivative work needs a commercial licence. AgenticOS is plain Apache-2.0.

### Can AgenticOS agents join team chats like LobeHub agents?

Yes. A published agent answers in Slack, Microsoft Teams, Telegram, Mattermost, Discord and Matrix, and can also follow a channel passively. A linked user's requests run as that person.

### Which one controls cost better?

LobeHub tracks usage against a credit pool. AgenticOS stops an agent's next model request when its budget or the organization's cap is reached, and records the cost of a failed run too.

## Related comparisons

[AgenticOS vs Kortix](kortix.md) · [AgenticOS vs Open WebUI and LibreChat](open-webui-librechat.md) · [Agents in Slack](slack-agents.md) · [All comparisons](comparison.md)

## Sources

- [LobeHub](https://lobehub.com): product description, channels and pricing.
- [`lobehub/lobehub` licence](https://github.com/lobehub/lobehub/blob/main/LICENSE): the LobeHub Community License conditions quoted above.
- [LobeHub repository](https://github.com/lobehub/lobehub): providers, MCP support and the self-hosted build.
