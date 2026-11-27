---
title: "AgenticOS vs Open WebUI and LibreChat"
seo_title: "AgenticOS vs Open WebUI and LibreChat: chat UI or agents"
description: "Compare Open WebUI, LibreChat and AgenticOS: a self-hosted company chat against a platform for governed agents, licences, budgets, approvals and channels."
---

# AgenticOS vs Open WebUI and LibreChat

Open WebUI and LibreChat are the self-hosted chat interfaces IT teams usually deploy first, so employees stop pasting company data into personal AI accounts. Both are mature, connect to many models and add tools, knowledge and agents. AgenticOS answers a different question: not "which chat window do we give people", but "which agents does the company own, who is responsible for them and what may they spend".

Maintained by the AgenticOS team. Sources checked 26 November 2026. AgenticOS baseline: v1.95.0. Scope: the public repositories, licence files and documentation of Open WebUI and LibreChat, not tested deployments.

## At a glance

| Area | Open WebUI | LibreChat | AgenticOS |
| --- | --- | --- | --- |
| What it is | A self-hosted AI interface with RBAC, groups, tools and RAG | An "enhanced ChatGPT clone" with agents, MCP and skills | A platform for versioned company agents, workflows, apps and tables |
| Licence | BSD-3 with a branding clause: changing the branding is allowed up to 50 users in 30 days, then needs an enterprise licence | MIT; its admin panel (custom roles, groups) is AGPL-3.0 | Apache-2.0; see [bundled component licences](../licenses.md) |
| Owner | Open WebUI Inc. | ClickHouse, since November 2025 | Vstorm |
| Sign-in | OIDC, LDAP and SCIM included | OIDC, SAML and LDAP | OIDC SSO, LDAP and Kerberos; no SAML or SCIM yet |
| Spend control | Not described | A token balance per user | A monthly budget per agent and per organization, checked before each model request |
| Approvals | Not described | Confirmed by the user | Approval per capability, tool and MCP connection, decided by the people you choose |
| Agent lifecycle | Models and presets | Agents with access control lists | Published versions, environments, eval runs and YAML export |
| Channels | Web only; no bots in outside messaging tools | Web; Slack in beta | Web chat, widget, hosted page, HTTP API, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, email, iMessage, telephone calls |
| Tenancy | One organization | Tenant isolation through a proxy setup | Many organizations in one deployment |

## Where AgenticOS goes further

### A chat window is not an agent the company owns

Both chat interfaces let a person pick a model or a preset and talk to it. In AgenticOS an agent has an owner, a [published version](../concepts.md#version), [environments](../environments.md#what-an-environment-is), [eval runs](../evals.md) against a versioned dataset and a spec that [exports as YAML](../features.md#exportable-into-your-own-repository). When the agent changes, you can say who changed it, test it before publishing and roll back.

### Spend and approvals per agent

An AgenticOS [budget](../governance.md#budgets) stops an agent's next model request when its cap or the organization's is reached; LibreChat counts a balance per user, and Open WebUI does not describe a spend cap. A tool call can wait for an [approval](../governance.md#approvals) by someone other than the person chatting, and every decision is in the [tamper-evident audit log](../governance.md#audit).

### The same agent where people already work

A published AgenticOS agent answers in [Slack](../channels.md#slack), [Microsoft Teams](../channels.md#microsoft-teams), [email](../channels.md#email), a [website widget](../channels.md#the-website-widget) and over the [HTTP API](../channels.md#the-public-api), not only in its own web interface. The [desktop](../desktop.md) and [phone](../mobile.md) apps add quick ask and approvals on the go.

### Licence terms without branding conditions

Open WebUI's licence forbids changing its branding above 50 users in a 30-day period without an enterprise licence. LibreChat's core is MIT, but the admin panel that holds custom roles and groups is AGPL-3.0. AgenticOS is Apache-2.0. See [licence terms compared](licence-terms.md).

## When Open WebUI or LibreChat is the better fit

- You need a company chat with model choice for every employee, and agents with owners and budgets are not the goal yet.
- You need SAML or SCIM today. Open WebUI includes SCIM and LibreChat includes SAML; AgenticOS has neither yet.
- Your users run local models through Ollama and value the large community around these interfaces.

The two can also coexist: keep a chat interface for everyday use and run company agents in AgenticOS, reachable through its [HTTP API](../channels.md#the-public-api) and as an [MCP server](../mcp.md#agenticos-as-an-mcp-server).

## Compare a change, not only an answer

Pick one task that changes something, such as filing a ticket. Configure it in both products, give it to two teams, require a second person's approval and cap its spend. Then change the instructions and check who can see what changed and when. Record the results with the [comparison method](comparison.md#a-shared-trial).

## Frequently asked questions

### Is AgenticOS a self-hosted ChatGPT like Open WebUI?

It includes web chat, but it is built around company agents: each with an owner, versions, a budget, approvals and channels. Open WebUI and LibreChat are built around the chat interface itself.

### Can I keep Open WebUI and add AgenticOS?

Yes. Many teams keep a chat interface and run governed agents beside it. AgenticOS agents answer through the HTTP API, Slack, Teams and the other surfaces, and AgenticOS is also an MCP server.

### Which licence is more permissive?

AgenticOS is Apache-2.0 throughout. LibreChat's core is MIT with an AGPL-3.0 admin panel. Open WebUI's BSD-3 licence adds a branding clause above 50 users.

## Related comparisons

[AgenticOS vs a DIY stack](diy-stack.md) · [AgenticOS vs Onyx](onyx.md) · [AgenticOS vs LobeHub](lobehub.md) · [All comparisons](comparison.md)

## Sources

- [Open WebUI repository](https://github.com/open-webui/open-webui) and [licence](https://docs.openwebui.com/license): features, sign-in options and the branding clause.
- [LibreChat repository](https://github.com/LibreChat-AI/LibreChat): agents, MCP, sign-in options and the AGPL-3.0 admin panel.
- [LibreChat balance settings](https://www.librechat.ai/docs/configuration/librechat_yaml/object_structure/balance): token balance per user.
- [ClickHouse acquires LibreChat](https://clickhouse.com/blog/clickhouse-acquires-librechat): ownership since November 2025.
