# AgenticOS plugin for Claude

A Claude plugin with one skill, `operating-agenticos`, that teaches Claude to operate an AgenticOS organization through the deployment's own MCP server.

The MCP server already describes each tool. The skill adds what the tool list does not: which mechanism fits a request, the order of operations, the rules that keep writes safe, what the connection cannot do, and a catalogue of use cases to offer.

## What you can ask for

- "Why did my last run fail?" and "What did our agents cost this month?"
- "Build me an agent that answers from our handbook, test it, and publish it when I say so."
- "Every weekday at 9, have the ops agent summarise yesterday's failed runs."
- "When a form comes in, classify it and file it in a table."
- "Load this repository's `docs/` folder into a knowledge base."
- "Which agents are still on an old version of the refund skill?"

The full list, with the tool chain behind each one, is in [`skills/operating-agenticos/reference/use-cases.md`](skills/operating-agenticos/reference/use-cases.md).

## Requirements

The plugin does not bundle a connection, because the address is your own deployment. Connect the AgenticOS MCP server first:

```bash
claude mcp add --transport http agenticos https://<your-deployment>/mcp
```

Claude Code opens the console's consent page, where you choose the organization and what the connection may do. The console lists the exact command for every client under **Settings → MCP clients**. A claude.ai connector pointing at the same URL works too; the skill matches tools by name, whatever the server is called.

Two choices at sign-in decide what the skill can do:

- Sign in with OAuth, not an organization API key, if you want Improve and eval sessions.
- Select `personal:consent` under **Custom** if you want Claude to create personal routines and watches.

## Install

From a checkout of this repository:

```bash
claude plugin marketplace add /path/to/agenticos
claude plugin install agenticos@agenticos
```

Or from GitHub:

```bash
claude plugin marketplace add vstorm-co/agenticos
claude plugin install agenticos@agenticos
```

To try it without installing, start Claude Code with `claude --plugin-dir plugins/agenticos`.

## Layout

```
plugins/agenticos/
├── .claude-plugin/plugin.json
├── skills/operating-agenticos/
│   ├── SKILL.md                         overview, rules, core workflows
│   └── reference/
│       ├── use-cases.md                 what to offer, and how each was confirmed
│       ├── tool-map.md                  every tool, by domain, with its permission
│       ├── agents.md                    build, bind, test, publish, Improve
│       ├── automation.md                routines, watches, tasks
│       ├── workflows-and-tables.md      graphs, testing, records
│       └── knowledge-and-skills.md      knowledge bases, context files, skills
└── evaluations/                         scenarios for checking the skill
```

## How the use cases were confirmed

Each use case names how far its tool chain was exercised against a running deployment (AgenticOS 1.82.2, signed in as an organization owner):

- **live**: the whole chain ran. This covers diagnosing a failed run, spend, the organization snapshot, querying a table, checking a workflow draft, and creating, editing, testing and discarding an agent draft.
- **reads live**: every discovery step ran; the writes were checked against the tool schemas and `backend/app/services/platform_mcp/`, and not executed, because MCP cannot undo them (a table, a knowledge base, a workflow and a skill cannot be deleted over MCP) or the test organization lacked the precondition (a dataset, a personal connection, an embedding key).
- **contract**: checked against the schemas and source only.

## Maintaining the skill

The MCP tool descriptions are the contract; the skill deliberately does not restate parameters. Update it when a tool is added, removed or renamed, when a permission changes, or when the server gains or loses an ability listed under "What the connection cannot do".

`evaluations/` holds scenarios in the format the [skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) describe. Run them against a test organization with and without the plugin when changing the skill.
