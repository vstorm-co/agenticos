---
name: agenticos-guide
description: Answer questions about AgenticOS itself - what a feature is called, how it works, how to connect it to Claude Code or another tool, the API - from the product's own documentation, not from a web search.
category: documentation
---

# AgenticOS, from its own documentation

A question about the platform you run in - a feature, a setting, an integration, the API, "can I use it from X" - is answered from AgenticOS's documentation. Do not search the web for it: results about other products with similar names are wrong for this one, and the answer is already written down.

## Where the answer is

Read the file first when one is listed; it is the documentation page itself, bundled with this skill. Otherwise fetch the page from the documentation site with `web_fetch`.

| Question                                                                                       | Read                                                          |
| ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| What a word in the console means, and its name in the API and spec                             | `docs/reference-glossary.md`                                  |
| What the platform can do, on one page                                                          | `docs/features.md`                                            |
| Agents, versions, specs, runs, capabilities - how the pieces fit                               | `docs/concepts.md`                                            |
| Connecting a tool through MCP; the server catalog; OAuth sign-in                               | `docs/mcp.md`                                                 |
| Using AgenticOS from Claude Code, Codex, Cursor or Claude Desktop (AgenticOS as an MCP server) | `docs/mcp.md`, section "AgenticOS as an MCP server"           |
| Calling the HTTP API, API keys, streaming, errors                                              | `docs/api.md`                                                 |
| Ongoing work, shared files across chats, creating a project, an LLM wiki                       | `docs/projects.md`                                            |
| Roles, scopes, sharing an agent                                                                | https://vstorm-co.github.io/agenticos/permissions/            |
| Budgets, approvals, alerts, the audit log                                                      | https://vstorm-co.github.io/agenticos/governance/             |
| Slack, Telegram, Mattermost, the website widget                                                | https://vstorm-co.github.io/agenticos/channels/               |
| Models, providers, fallbacks, cost                                                             | https://vstorm-co.github.io/agenticos/models/                 |
| Skills and how they differ from knowledge                                                      | https://vstorm-co.github.io/agenticos/skills/                 |
| Knowledge bases: uploading, parsing, retrieval                                                 | https://vstorm-co.github.io/agenticos/file-processing/        |
| Every capability and its settings                                                              | https://vstorm-co.github.io/agenticos/reference/capabilities/ |
| Credentials and the vault                                                                      | https://vstorm-co.github.io/agenticos/secrets/                |
| Desktop app, local folders, local browser/models/MCP, permissions and local instances          | `docs/desktop.md`                                             |
| Mobile app, connecting, sharing, notifications and device limitations                          | `docs/mobile.md`                                              |
| The sandbox: server versus local execution, files and browsers                                 | `docs/sandbox.md`                                             |
| Published pages and public links                                                               | https://vstorm-co.github.io/agenticos/artifacts/              |
| Groups and departments                                                                         | https://vstorm-co.github.io/agenticos/departments/            |
| Installing and deploying                                                                       | https://vstorm-co.github.io/agenticos/deploy/                 |

## How to answer

- Answer in the person's words, then the steps - the exact command, menu path or setting - quoted from the page rather than paraphrased.
- Where the page names a place in the console ("Settings → MCP clients"), send the person there: it shows values for their own deployment, such as its address, which the documentation can only write as a placeholder.
- Look at the person's own organization with your tools when the answer depends on it - whether a connection exists, what a key may do - instead of describing the general case.
- When neither the files nor the site answer the question, say so and say what you did find; do not fill the gap from another product's documentation.

For workflow construction, execution, triggers and API integration, read `docs/workflows.md`. For typed records, table schemas and Markdown notes, read `docs/virtual-tables.md`. Load workflow-builder and virtual-tables for the building procedure.
