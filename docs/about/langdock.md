---
title: "AgenticOS vs Langdock"
seo_title: "AgenticOS vs Langdock: EU SaaS seats or self-hosted agents"
description: "Compare Langdock and AgenticOS: a German per-seat AI platform against Apache-2.0 agents on your servers. Agent limits, SSO, approvals, hosting and cost."
---

# AgenticOS vs Langdock

Langdock is a German enterprise AI platform with chat, agents, workflows and apps, hosted on Azure in the EU. It is the most complete governance offering among European SaaS products: SAML and SCIM on every plan, up to five custom roles, monthly limits per agent that block or switch to a fallback model, approvals in workflows, agent evaluations and an MCP server. AgenticOS covers much of the same governance as open source on your own servers, without a seat fee, and still lacks SAML, SCIM and custom roles.

Maintained by the AgenticOS team. Sources checked 26 November 2026. AgenticOS baseline: v1.95.0. Langdock scope: its pricing page and administrator documentation, not a tested workspace.

## At a glance

| Area | Langdock | AgenticOS |
| --- | --- | --- |
| What it is | A per-seat AI workspace with chat, agents, workflows and apps | A platform for company agents, workflows, apps and tables that you run |
| Licence | Proprietary | Apache-2.0; see [bundled component licences](../licenses.md) |
| Where it runs | SaaS on Azure in the EU; single-tenant and on-premises for large contracts | Your infrastructure, any cloud or on-premises |
| Models | Multi-model, EU-hosted, or your own keys | 28 providers, including local ones |
| Spend control | Monthly limits per workspace, person, group, agent and workflow, blocking or switching to a fallback model | A monthly budget per agent and per organization, checked before each model request |
| Approvals | In workflows, routed to named recipients | Approval per capability, tool and MCP connection, routed to the people you choose |
| Sign-in and roles | SAML and SCIM on every plan; up to five custom roles | OIDC SSO, LDAP and Kerberos; six built-in roles and per-resource grants; no SAML, SCIM or custom roles yet |
| Evaluations | Agent evaluations | [Eval runs](../evals.md) and suites against versioned datasets |
| Audit | Audit API, 90 days | Tamper-evident audit log with retention you set |
| Channels | Web, Slack, Microsoft Teams, Office, desktop and phone apps | Web chat, widget, hosted page, HTTP API, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, email, iMessage, telephone calls; desktop and phone apps |
| Pricing | Core €23.20, Work €31.20, Max €99 per user a month billed annually; workflows €449 per workspace a month | No licence or seat fee; model usage at your provider's rates |

## Where AgenticOS goes further

### No seat fee

Langdock charges per user. For 200 people, its published plans come to roughly €56,000 to €238,000 a year before workflow add-ons. AgenticOS has no licence or seat fee: you pay model providers at their rates and run the infrastructure, yourself or with Vstorm. Compare the two on your own usage, since per-seat plans include model usage within limits and AgenticOS does not.

### Your servers, from the first user

Langdock's dedicated and on-premises options are offered only for large contracts. AgenticOS runs on [your infrastructure](../deploy.md) from the start, with local models, local embeddings and local parsing if you need them. See [what leaves by default](../data-protection.md#nothing-leaves-by-default).

### Open code you can change

AgenticOS is Apache-2.0. You can read every control a review asks about, change the console and brand it, and run it for several companies from one deployment with [organizations](../concepts.md#organizations) as tenants.

### More channels

The same published agent also answers in Telegram, Mattermost, Discord, Matrix, [SMS](../channels.md#sms), [email](../channels.md#email), iMessage and [telephone calls](../voice.md#telephone-calls), and on a public [website widget](../channels.md#the-website-widget) or [hosted page](../channels.md#a-hosted-page).

## When Langdock is the better fit

- You need SAML, SCIM or custom roles today. AgenticOS has none of them yet; SAML works only through a broker such as Keycloak.
- You want a managed EU service with ISO 27001 and SOC 2 Type II reports, and no servers to run.
- Your teams want a chat assistant for every employee as much as company agents.

## Compare a change, not only an answer

Run the same agent in both products with a monthly limit of a few cents and check what happens at the limit. Route a tool call to a second person for approval. Then price a year for your headcount: Langdock seats against AgenticOS infrastructure and model usage. Record the results with the [comparison method](comparison.md#a-shared-trial).

## Frequently asked questions

### Is AgenticOS a European alternative to Langdock?

It is an open-source alternative you host wherever you choose, including in the EU or on-premises. Vstorm, which maintains it, is a Polish company. Langdock is a German SaaS product.

### Does Langdock have budgets per agent?

Yes. Langdock sets monthly limits per workspace, person, group, agent and workflow, and can block or switch to a fallback model at the limit. AgenticOS sets a budget per agent and per organization, checked before each model request, in the open-source product.

### What does AgenticOS lack compared with Langdock?

SAML and SCIM, custom roles and security certifications for a managed service. You certify your own AgenticOS deployment; the [security page](../security.md) maps its controls for a review.

## Related comparisons

[AgenticOS vs Dust](dust.md) · [AgenticOS vs deepset](deepset.md) · [AgenticOS vs Mistral](mistral.md) · [All comparisons](comparison.md)

## Sources

- [Langdock pricing](https://langdock.com/pricing): plans, prices and workflow add-on.
- [Agent limits](https://docs.langdock.com/en/admin/manage-agents/agent-limits): limits per agent and what happens at the limit.
- [Langdock documentation](https://docs.langdock.com): SSO, SCIM, roles, approvals, evaluations, MCP and integrations.
