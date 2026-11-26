# AgenticOS plugin for Claude

A Claude plugin for the path from an upstream checkout or fork to a verified deployment, configured organization, tested agent release and reusable solution. The operating skill uses the deployment's own MCP server; installation and host maintenance use an authorized terminal or CI executor.

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
│       ├── use-cases.md                 what to offer, and what each needs
│       ├── tool-map.md                  every tool, by domain, with its permission
│       ├── agents.md                    build, bind, test, publish, Improve
│       ├── automation.md                routines, watches, tasks
│       ├── workflows-and-tables.md      graphs, testing, records
│       └── knowledge-and-skills.md      knowledge bases, context files, skills
└── evaluations/                         scenarios for checking the skill
```

## How the skill was checked

The tool chains in the use-case catalogue were run against a live deployment (AgenticOS 1.82.2, signed in with OAuth as an organization owner):

- diagnosing a failed run, the spend report and the organization snapshot
- drafting, testing, publishing and running an agent, including one that answered from a bound skill
- creating, retiming and deleting a routine
- building a workflow with its table in one call, testing it, publishing it and starting it with `run_workflow`, with the filed record read back each time
- table upserts, updates, typed queries and deletes, and the task chain with an idempotent retry
- creating and editing a skill and a context file

Four fresh Claude sessions then used the skill on the scenarios in `evaluations/` and on requests the test organization could not serve (an Improve session with no dataset, a watch with no connection, a knowledge base with no embedding key), read-only, building the arguments of every write and checking them against the live schemas. What they could not find in the skill was added to it.

## Maintaining the skill

The MCP tool descriptions are the contract; the skill deliberately does not restate parameters. Update it when a tool is added, removed or renamed, when a permission changes, or when the server gains or loses an ability listed under "What the connection cannot do".

`evaluations/` holds scenarios in the format the [skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) describe. Run them against a test organization with and without the plugin when changing the skill.

## Lifecycle skills and reusable solutions

- `getting-started-agenticos`: choose the adoption path and connect the intended organization.
- `developing-agenticos`: maintain a fork, publish its images and update from upstream.
- `deploying-agenticos`: install, verify, update and recover a deployment.
- `operating-agenticos`: work with resources and investigate recorded runs.
- `releasing-agenticos-resources`: datasets, evals, staging, promotion and rollback.
- `building-agenticos-solutions`: adapt a bundle or build the user's own case from discovered platform features.

The baseline was tested with server 1.82.2. Lifecycle tools use MCP contract 1;
read `get_platform_context` rather than assuming a server version has a feature.
See [compatibility.json](compatibility.json). New assistant-only operations need
OAuth with the corresponding scopes; ordinary organization API keys retain their
existing public API boundary.

[Support](solutions/support.json), [repository work](solutions/repository.json) and
[onboarding](solutions/onboarding.json) are draft-only example bundles. Review and
plan the exact manifest, then install using its hash and a caller-scoped installation
key. Installation is atomic and retries replay the receipt. It never publishes,
runs, schedules or indexes; external model and embedding dependencies remain
explicit. Read back and test resources before release. Credentials are entered in
the console, never in a bundle or conversation.
