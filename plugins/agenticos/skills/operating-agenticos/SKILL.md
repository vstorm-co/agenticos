---
name: operating-agenticos
description: Operates an AgenticOS organization through its platform MCP server - builds, tests and publishes agents, diagnoses failed runs and spend, fills and searches knowledge bases, sets up routines, watches, workflows, Virtual Tables and tasks, and runs Improve sessions on agents and skills. Use when the user mentions AgenticOS or its agents, runs, routines, workflows, knowledge bases, skills, context files or tables, when AgenticOS MCP tools such as whoami, list_agents, create_agent_draft or run_workflow are connected and the task touches them, or when the user asks what the AgenticOS MCP can do.
---

# Operating AgenticOS over MCP

The AgenticOS MCP server (`/mcp` on a deployment) acts as the member who connected it, inside one organization, with that member's permissions. Every tool is a call to the public API: refused, rate limited and audited like the same HTTP request.

## Tool names

This skill writes tools as `agenticos:<tool>`. The server name is whatever the connection was called, so match on the tool name: `agenticos:whoami` may appear as `mcp__agenticos__whoami` or `mcp__claude_ai_<connector>__whoami`. If no such tools are connected, stop and point the user at [README.md](../../README.md) for setup.

## Start here

1. Call `agenticos:whoami` once per session. It returns the organization ID, the role and the permission list: check a request against them before starting it. It does not say how the connection signed in or which OAuth scopes it holds; those limits show only as a refusal.
2. Find the resource with its `list_*` tool, then read it with its `get_*` tool. Listings return summaries only.
3. Treat each tool's own description and schema as the contract. This skill supplies the map, the order of operations and the judgment; it does not restate parameters.

## Rules that hold for every task

- **Discover, never invent.** IDs, capability IDs, workflow node IDs, ports, model profile IDs and column IDs come from tool results. A table's `values` are keyed by column UUID, not label; `single_select` values are option UUIDs.
- **Read before writing.** Several fields replace a whole list or text (`instructions`, `mcp_servers`, `skill_ids`, `collection_ids`, `context_ids`, `starters`, a capability's `config`, a table's column list). Read the current value and send the edited whole.
- **Carry revisions.** Workflow drafts, table schemas, records and tasks take `expected_revision` or `expected_version`. On a conflict, reread and reconcile; never overwrite.
- **Follow pagination.** Continue while `next_skip` is set, `has_more` is true, or fewer items than `total` have been read (some listings return only `items` and `total`; page those with `skip`). One page is not the whole set.
- **An `error` envelope is a refusal, not a result.** It carries `status`, `code`, `message` and `details`. Fix the input or report the missing permission. Do not retry a failed write unchanged and do not route around a permission refusal. A call that times out or loses its connection has an unknown outcome: the server may still be working. Look for the result (`agenticos:list_runs`, the relevant `list_*`) before sending it again.
- **Say what will change before a write.** Writes land in a live organization. Publishing, inviting, starting runs and creating automations are the user's decisions: name the effect, then call.
- **"Waits for approval"** in a tool description is about agents inside AgenticOS. From an MCP client, this client's own permission prompt is the approval, so the statement to the user before the call is what makes it informed.
- **Quote the price before spending.** Improve sessions, skill checks and knowledge drafts each have an `estimate_*` tool. Run it and tell the user the price and the limit. Then give the spending step what its schema asks for: session steps take `budget_usd` (the session's limit), the estimate's `total_usd` as `estimate_usd`, and its `candidate_hash`; a skill update check takes neither, and a catch-up takes only `budget_usd`.
- **Read back consequential writes** before claiming success: `agenticos:get_agent` after a publish, `agenticos:get_workflow_execution_steps` after a workflow test, `agenticos:list_routines` after creating a routine.
- **Draft, test, then publish.** A draft changes nothing live. Testing still makes real model calls and, for workflows, real external calls.

## What the connection cannot do

Do not promise these; send the user to the console instead.

- Create, read or rotate credentials. Model keys, embedding keys and MCP tokens are set in the console.
- Delete agents, workflows, tables, knowledge bases, skills or documents. The only deletions are an unpublished agent draft the caller created, a routine, a watch and a table record.
- Upload binary documents. `agenticos:add_document` takes text content (`.md`, `.txt`).
- Read the Inbox from an external MCP client. `agenticos:list_inbox_cases` and `agenticos:settle_inbox_case` need the person's own chat or console session.
- Grant desktop folders, browsers or local models. The person selects those in the Desktop app.
- Discover channel bots or chat IDs. A workflow's Slack, Telegram or Mattermost step needs a `bot_id` and a channel ID that no tool lists: the user picks the bot in the workflow editor or supplies both.
- Approve personal routines or watches unless the connection was authorized with the `personal:consent` scope.
- Run Improve and eval tools through an organization API key. They need a connection signed in with OAuth. A harmless probe is `agenticos:list_improvements`: an API key is refused there.
- Create datasets (test question sets) or automatic checks. Improve needs one that `agenticos:list_datasets` already shows; the user makes it in the console.
- List vault secrets or embedding endpoints. The user supplies the ID. A model profile's `secret_id` from `agenticos:list_models` is a chat key and is not an embedding key.

## Choosing the mechanism

| The user wants | Use |
|---|---|
| Judgment over varying input | an agent |
| A recurring report or periodic job | a routine on an agent |
| Read-only monitoring of a personal account for changes | a watch |
| A deterministic, typed pipeline with triggers | a workflow |
| Structured records an automation reads and writes | a Virtual Table |
| A one-off commitment or reminder | a task on a managed task board |
| Documents an agent searches and cites | a knowledge base |
| Short standing facts for every run (glossary, policy) | a context file |
| A reusable procedure an agent loads on demand | a skill |

Use the fewest mechanisms that meet the goal, and reuse an existing resource before creating another.

## Core workflows

### Diagnose a failed run

1. `agenticos:list_runs`, newest first. For "my last run", look at the newest run before filtering: it may not be the failed one, and `awaiting_answer` is a run paused on a question, not a failure. Then filter with `status: "failed"`, `agent_id`, `surface` or `started_from`. Each item already carries its `error`.
2. `agenticos:read_run_transcript` for the turns, then `agenticos:read_run_tool_call` for one call's arguments or result. A transcript holding only the user's message means the run recorded no assistant turn: say that the detail is in the server log, and reason from the error and the token counts.
3. `agenticos:get_run` gives `prev_run_id`. Compare the failed run with the last one that completed: its `agent_version_id`, and the agent's `current_version_id` and `updated_at` from `agenticos:get_agent`. `updated_at` also moves on draft edits, so it is a weak signal of when a publish happened. A failure that starts right after a publish points at that version; a failure on an older version does not prove the published one fails.

Reading the error: `ToolLoopStopped` is the loop guard ending a run that repeated the same tool calls, usually with input tokens far above output tokens. Budget, guardrail and usage-limit stops are named the same way in `error`. Mark anything not in the record as an inference.

### Build and publish an agent

1. `agenticos:list_models` for a `model_profile_id`. `agenticos:list_capabilities`, then `agenticos:get_capability` for each one to be configured.
2. `agenticos:create_agent_draft`.
3. `agenticos:test_agent_draft`. A refusal names what blocks publishing. `status: awaiting_answer` means the agent asked a question: continue with `agenticos:answer_agent_questions` using the user's real answer.
4. Fix with `agenticos:update_agent_draft` and test again until the answers are right.
5. `agenticos:publish_agent` only when the user asks for it.

Full detail, bindings and Improve: [reference/agents.md](reference/agents.md).

### Report spend

`agenticos:get_spend` returns month to date and per-agent cost. When `partial_run_count` is above zero or a run has `cost_is_partial: true`, some runs used a model with no price: report the figure as a lower bound and give token counts.

## Reference files

Read the one that matches the task.

- **Use cases to offer, each with its tool chain and what it needs**: [reference/use-cases.md](reference/use-cases.md). Read it when the user asks what is possible or wants ideas, and pick by the permissions `agenticos:whoami` returned and what the organization already has.
- **Every tool by domain, with the permission it needs**: [reference/tool-map.md](reference/tool-map.md)
- **Agents: capabilities, MCP bindings, sandboxes, testing, publishing, Improve**: [reference/agents.md](reference/agents.md)
- **Routines, watches and tasks**: [reference/automation.md](reference/automation.md)
- **Workflows and Virtual Tables**: [reference/workflows-and-tables.md](reference/workflows-and-tables.md)
- **Knowledge bases, context files and skills**: [reference/knowledge-and-skills.md](reference/knowledge-and-skills.md)

## Reporting back

End with the resource and its ID, what was checked, whether it is a draft or published, what is now active unattended, and anything still waiting on the user in the console.
