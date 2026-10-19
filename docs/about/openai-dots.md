---
title: "AgenticOS vs OpenAI dots"
seo_title: "AgenticOS vs OpenAI dots: a self-hosted alternative"
description: "OpenAI dots are always-on agents inside ChatGPT, each with a cloud computer. Compare them with AgenticOS: your servers, any model, rules enforced in code."
---

# AgenticOS vs OpenAI dots

OpenAI dots are always-on agents inside ChatGPT. Each dot has its own cloud computer and browser, works through thousands of connected apps, and answers in ChatGPT, Slack and Microsoft Teams. AgenticOS gives you the same kind of teammate - an agent with tools, a browser, a sandbox and a schedule - running on infrastructure you control, with any model and with limits the platform enforces rather than asks for.

If your company already lives in ChatGPT and your plan and region include dots, they are the fastest way to try an AI teammate. If you need the agents, the data and the rules to stay yours, AgenticOS is built for that.

Maintained by the AgenticOS team. Sources checked 14 October 2026. AgenticOS baseline: v0.0.535. dots scope: OpenAI's announcement of 29 September 2026, its help-centre FAQ and press coverage, not a tested account.

## At a glance

| Area | OpenAI dots | AgenticOS |
| --- | --- | --- |
| What you get | Always-on agents inside ChatGPT, each with a cloud computer | Any number of agents, each a versioned spec |
| Where it runs | OpenAI's cloud | Your infrastructure, with Docker Compose |
| Source | Proprietary | Apache-2.0 |
| Models | OpenAI only | 28 providers, including local models |
| Tools | 4,000+ connected apps, a browser and a computer per dot | 4,700+ MCP servers in the gallery, a browser, a code sandbox, your own capabilities |
| Surfaces | ChatGPT, Slack, Microsoft Teams; SMS announced | Web chat, widget, hosted page, HTTP API, WebSocket, Slack, Telegram, Mattermost |
| Rules | Custom rules to allow, block or require approval; a model reviews risky actions | Approvals checked by the platform before a tool runs; per-tool allow-lists |
| Spend control | Included in the plan | A monthly budget per agent and per organization, checked before each model request |
| Availability | Pro and Business Premium plans; Pro not offered in the EEA, Switzerland or the UK at launch | Wherever you deploy it |

## Where AgenticOS goes further

### Rules the platform enforces

OpenAI describes custom rules as guidance a dot follows, with a model reviewing risky actions. In AgenticOS an [approval](../governance.md#approvals) is checked by the platform before the tool runs, whatever the model decides, and an MCP binding can [allow only the tools you pick](../mcp.md#which-tools-and-who-decides). A [budget](../governance.md#enforcement-is-before-the-request) stops a run before the model request that would pass it.

### Your servers, your region

dots run in OpenAI's cloud, and at launch the Pro plan was not offered in the EEA, Switzerland or the UK. AgenticOS runs [where you deploy it](../deploy.md), stores conversations and documents in [your own Postgres](../data-protection.md#where-personal-data-lives), and can run with a [local model](../models.md#providers) so nothing leaves your network.

### Any model, not one vendor's

A dot thinks with OpenAI's models. An AgenticOS agent uses a [model profile](../models.md#a-model-profile) over 28 providers, with fallbacks, so one agent can run on Claude, another on a local model, and a change of provider is one setting.

### A record you can audit

Each run in AgenticOS is in [Activity](../governance.md#audit) with its steps, cost and outcome, and the audit log is tamper-evident. Sign-in is your [OIDC, LDAP or Kerberos](../directory.md#signing-in-with-a-directory-account) directory.

## When dots are enough

- Your company already works in ChatGPT, and your plan and region include dots.
- OpenAI's models, its cloud and its connected apps meet your requirements.
- You want an assistant that watches your apps and suggests work with no infrastructure to run. AgenticOS covers scheduled and event-driven work with [routines](../features.md#triggers-so-an-agent-runs-without-you), which someone sets up.

## Frequently asked questions

### Is AgenticOS an alternative to OpenAI dots?

Yes, if you want always-on agents you host yourself. AgenticOS agents have tools, a browser, a code sandbox and routines, run on your infrastructure with any model, and answer in web chat, Slack, Telegram, Mattermost and the API.

### Can AgenticOS work while nobody is chatting?

Yes. A routine starts an agent on a schedule or on an event such as a GitHub issue, an email or a signed webhook, and its runs are budgeted and recorded like any other.

### Where do dots run, and where does AgenticOS run?

dots run in OpenAI's cloud. AgenticOS runs on your own servers or cloud account, and stores its data in your own Postgres.

## Related comparisons

[AgenticOS vs ChatGPT](chatgpt.md) · [AgenticOS vs Grok Bot](grok-bot.md) · [AgenticOS vs Viktor](viktor.md) · [All comparisons](comparison.md)

## Sources

- [The Next Web: OpenAI launches dots](https://thenextweb.com/news/openai-dots-always-on-ai-agents-cloud-computers-devday): always-on agents, a cloud computer per dot, apps, Slack and Teams, plans.
- [OpenAI Help: dots privacy, security and safety FAQ](https://help.openai.com/mr-in/articles/20001529-dots-privacy-security-and-safety-faqs): custom rules, review of risky actions, what stays with the user.
