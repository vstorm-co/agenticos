---
title: "AgenticOS vs Kortix"
seo_title: "AgenticOS vs Kortix CompanyOS: licence and self-hosting"
description: "Compare Kortix CompanyOS and AgenticOS: Elastic License 2.0 against Apache-2.0, where agent sessions run, budgets, approvals, sign-in and channels."
---

# AgenticOS vs Kortix

Kortix CompanyOS and AgenticOS describe themselves in almost the same words: an operating system for a company that works with AI agents. The difference shows up in two places a legal or IT review checks first. Kortix moved from Apache-2.0 to the Elastic License 2.0 in February 2026, and its self-hosted edition still runs agent sessions in Kortix's cloud sandboxes. AgenticOS is Apache-2.0 and runs entirely on your infrastructure.

Maintained by the AgenticOS team. Sources checked 26 November 2026. AgenticOS baseline: v1.95.0. Kortix scope: its website, documentation, pricing page and the history of the `LICENSE` file in `kortix-ai/CompanyOS`, not a tested workspace or self-hosted deployment.

## At a glance

| Area | Kortix CompanyOS | AgenticOS |
| --- | --- | --- |
| What it is | A company as a git repository: agents, skills, memory and connectors are files | A console where a business team builds versioned agents, workflows, apps and tables |
| Licence | Elastic License 2.0 since 18 February 2026; Apache-2.0 before December 2025 | Apache-2.0; see [bundled component licences](../licenses.md) |
| Where it runs | Kortix cloud, or self-hosted web, API and database; agent sessions still run in Kortix cloud sandboxes | Your infrastructure, including the sandbox; air-gapped setups are possible |
| Models | Any, with your own keys | 28 providers, including local ones |
| Spend control | A daily, weekly or monthly budget per workspace, blocking or warning | A monthly budget per agent and per organization, checked before each model request |
| Approvals | Allow, Ask or Deny per tool; a workspace manager or the session's starter decides | Approval per capability, tool and MCP connection; the run parks for the people you choose |
| Sign-in and roles | SAML SSO, SCIM, groups and custom roles behind an Enterprise licence key | OIDC SSO, LDAP and Kerberos, six roles and per-resource grants in every deployment |
| Audit | Locked archive; reading it needs Enterprise | Tamper-evident audit log with CSV and JSONL export |
| Channels | Slack, Microsoft Teams, Telegram, Discord, email; voice experimental | Web chat, widget, hosted page, HTTP API, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, email, iMessage, telephone calls |
| Pricing | Free tier with 500 credits; credits from $50 a month; Enterprise licence key | No licence fee; model usage at your provider's rates |

## Where AgenticOS goes further

### A licence that lets you host it for others

The Elastic License 2.0 is a source-available licence, not an open-source one. It forbids providing the software to third parties as a hosted or managed service, and forbids moving, changing or circumventing its licence-key functionality. In Kortix, the licence key unlocks SAML, SCIM, groups, custom roles, reading the audit archive and branding.

The licence changed three times in under a year: Apache-2.0 in April 2025, a Kortix Non-Commercial License on 3 December 2025, a Kortix Public Source License a day later, and the Elastic License 2.0 on 18 February 2026. AgenticOS is Apache-2.0: you may run it for every department, subsidiary or client, change it and brand it as your own.

### Self-hosting that keeps the work on your servers

Kortix documents that a self-hosted install runs the web app, the API and the database, while agent sessions keep running in Kortix's cloud sandboxes, and that the server must be reachable from the internet. Air-gapped operation and full data residency are therefore not available.

In AgenticOS the [sandbox](../sandbox.md) is part of your deployment, and a fresh install sends no prompts or documents anywhere. See [what leaves by default](../data-protection.md#nothing-leaves-by-default).

### A budget per agent, not per workspace

Kortix's budget applies to a whole workspace. AgenticOS checks each agent's [monthly budget](../governance.md#budgets) and the organization's cap [before each model request](../governance.md#enforcement-is-before-the-request), and [delegated work](../governance.md#delegation-spends-the-parents-budget) spends the parent agent's budget. You know which agent spent what, and one runaway agent cannot exhaust everyone's allowance.

### The controls a review asks for, without a licence key

[OIDC single sign-on, LDAP and Kerberos](../directory.md#signing-in-with-a-directory-account), [six roles and per-resource grants](../permissions.md#layer-3-visibility-and-grants) and the [tamper-evident audit log](../governance.md#audit) are in every AgenticOS deployment. SAML and SCIM are not available yet; SAML works through a broker such as Keycloak.

### Many organizations in one deployment

AgenticOS [organizations](../concepts.md#organizations) are tenants isolated in the schema. Kortix supports several workspaces per account, and does not describe tenant isolation on its own servers.

## When Kortix is the better fit

- You want a company described entirely as files in one git repository and edited with a coding agent.
- You prefer a managed cloud product that starts in minutes, and the Elastic License 2.0 suits how you will use it.
- You need SAML or SCIM today and are ready to buy the Enterprise licence key. AgenticOS has neither yet.

## Compare a change, not only an answer

Run the [first document agent](../howto/first-document-agent.md) fixture in both products. Then check where a session actually runs by watching outbound connections from the self-hosted server while an agent works. Give an agent a budget of a few cents and run it past the cap. Record what each product allows, refuses and logs, with the [comparison method](comparison.md#a-shared-trial).

## Frequently asked questions

### Is Kortix CompanyOS open source?

Not under an OSI licence. Its repository moved to the Elastic License 2.0 on 18 February 2026, which forbids offering it to others as a hosted service and circumventing its licence key. AgenticOS is Apache-2.0.

### Can Kortix run fully on my own servers?

According to its documentation, a self-hosted install runs the web app, API and database, but agent sessions still run in Kortix's cloud sandboxes. AgenticOS runs every part, including the sandbox, on your infrastructure.

### Does Kortix have budgets and approvals?

Yes: a budget per workspace that blocks or warns, and Allow, Ask or Deny per tool. AgenticOS sets a budget per agent and per organization, checked before each model request, and routes approvals to the people you choose.

## Related comparisons

[AgenticOS vs LobeHub](lobehub.md) · [AgenticOS vs Agno AgentOS](agno.md) · [Licence terms compared](licence-terms.md) · [All comparisons](comparison.md)

## Sources

- [Kortix](https://kortix.com): product description and pricing tiers.
- [Kortix documentation](https://kortix.com/docs/guide): self-hosting, sandboxes, budgets and approvals.
- [`kortix-ai/CompanyOS` licence](https://github.com/kortix-ai/CompanyOS/blob/main/LICENSE) and its file history: the Elastic License 2.0 terms quoted above and the earlier licences.
- [Elastic License 2.0](https://www.elastic.co/licensing/elastic-license): the licence text.
