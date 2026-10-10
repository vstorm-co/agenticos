---
title: "Choose a first task"
description: "29 tutorials: documents, support, research, automation, productivity and content, each with a check you can run."
---

# Choose a first task

Start with work whose result someone on the team can judge. Each of the 29 tutorials below gives you a synthetic input, the configuration, the exact prompt, reference checks, the usual failures and what to record. They are starting points with reference runs, not customer case studies or success-rate claims.

The last column says when the maintainers last ran a tutorial on the product. A recorded run covers exactly what the page's example block describes: one configuration, one date and one model. It is not evidence that your configuration passes the same checks. A tutorial that needs a third-party account the maintainers did not connect says *Not yet recorded*.

## Documents and knowledge

| Tutorial | What it does | Last run by the maintainers |
| --- | --- | --- |
| [Build your first document agent](howto/first-document-agent.md) | One document, one agent, answers you can check against it | v0.0.504, 25 September 2026 |
| [Answer questions across a document library with citations](howto/knowledge-base-assistant.md) | Search across a document library and cite the source | v0.0.504, 25 September 2026 |
| [Build an LLM wiki the agent maintains](howto/llm-wiki.md) | An agent that compiles sources into an interlinked markdown wiki | v0.0.504, 25 September 2026 |
| [Review a contract against your checklist](howto/contract-review.md) | A checklist skill applied to an attached agreement | v0.0.504, 25 September 2026 |
| [Extract invoice data into a spreadsheet](howto/document-extraction.md) | Invoice PDFs read in a sandbox and written to a CSV | v0.0.504, 25 September 2026 |
| [Summarise a meeting transcript into decisions and action items](howto/meeting-summary.md) | A transcript turned into decisions, owners and open questions | v0.0.504, 25 September 2026 |

## Customer support and service

| Tutorial | What it does | Last run by the maintainers |
| --- | --- | --- |
| [Put a support assistant on your website](howto/support-widget.md) | A knowledge-backed assistant embedded on a public site | v0.0.504, 25 September 2026 |
| [Answer a handbook question in Slack](howto/slack-handbook-assistant.md) | The document agent answering in a Slack thread | Not yet recorded |
| [Triage incoming support requests from your own app](howto/support-ticket-triage.md) | Tickets from your app classified through a signed webhook | v0.0.504, 25 September 2026 |
| [Triage your inbox and draft replies](howto/email-triage.md) | New mail read by a Gmail trigger and drafted into replies | Not yet recorded |
| [Answer new-hire questions with context files and skills](howto/onboarding-helpdesk.md) | Standing context and procedure skills for new hires | v0.0.504, 25 September 2026 |

## Research and analysis

| Tutorial | What it does | Last run by the maintainers |
| --- | --- | --- |
| [Research a question with subagents and publish a report](howto/deep-research-subagents.md) | Sub-questions delegated in parallel, sourced report published | v0.0.504, 25 September 2026 |
| [Brief yourself on a company before a call](howto/account-research.md) | A dated, sourced one-page brief on an organisation | v0.0.504, 25 September 2026 |
| [Watch web pages for changes on a schedule](howto/competitor-monitoring.md) | Pages fetched on a schedule and compared with the last run | v0.0.504, 25 September 2026 |
| [Answer questions from your database](howto/database-questions.md) | Questions answered through a read-only PostgreSQL connection | Not yet recorded |
| [Turn a CSV into a chart you can check](howto/csv-chart.md) | Totals, a chart and the script, reconciled with the rows | v0.0.504, 25 September 2026 |
| [Build an Excel report and a slide deck from data](howto/excel-report.md) | An Excel workbook and a slide deck built from data | v0.0.504, 25 September 2026 |

## Automation and teams of agents

| Tutorial | What it does | Last run by the maintainers |
| --- | --- | --- |
| [Schedule a weekly report](howto/scheduled-report.md) | A self-contained report republished as an app every week | v0.0.504, 25 September 2026 |
| [Triage new GitHub issues automatically](howto/github-issue-triage.md) | New issues triaged the moment GitHub delivers them | v0.0.504, 25 September 2026 |
| [Turn meeting action items into tasks with approval](howto/meeting-to-tasks.md) | Action items proposed as tracker tasks, each approved first | Not yet recorded |
| [Route requests to a team of specialist agents](howto/specialist-team.md) | A front desk that delegates to specialist agents | v0.0.504, 25 September 2026 |
| [Call an agent from your own application](howto/agent-api.md) | Any published agent called over HTTP from your code | v0.0.504, 25 September 2026 |

## Personal productivity

| Tutorial | What it does | Last run by the maintainers |
| --- | --- | --- |
| [Build a personal assistant that remembers you](howto/personal-assistant.md) | Preferences remembered across conversations, and forgotten on request | v0.0.504, 25 September 2026 |
| [Search and update Notion from an agent](howto/notion-agent.md) | A Notion workspace searched and updated through MCP | Not yet recorded |

## Content and communication

| Tutorial | What it does | Last run by the maintainers |
| --- | --- | --- |
| [Turn one article into social posts in your brand voice](howto/content-repurposing.md) | One article turned into channel posts in a brand voice | v0.0.504, 25 September 2026 |
| [Write product descriptions from a catalogue file](howto/product-descriptions.md) | A catalogue file turned into listings without invented facts | v0.0.504, 25 September 2026 |
| [Translate documents with your terminology](howto/translation-glossary.md) | Translation that follows a terminology skill | v0.0.504, 25 September 2026 |

## Engineering and safety

| Tutorial | What it does | Last run by the maintainers |
| --- | --- | --- |
| [Review a change in a repository](howto/code-review.md) | A diff reviewed in a sandbox with the shipped code-review skill | v0.0.504, 25 September 2026 |
| [Keep personal data out of an agent's prompts and answers](howto/pii-guardrails.md) | Personal data redacted before the model reads it | v0.0.504, 25 September 2026 |

## Before you start

New to the product? [Build your first document agent](howto/first-document-agent.md) first: every other tutorial assumes a running installation and a model profile.

The existing [screens and recordings](screens.md) show product interfaces. They are not evidence of these checks either. Keep your own input, actual output, run and errors together.

Choose one entry point through [channels](channels.md), then assign responsibility for [operation](rollout.md). If you are still selecting a platform, use the [comparisons](about/comparison.md).
