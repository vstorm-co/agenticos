# Use cases

Ideas to offer, each with the tool chain that delivers it. Tool names are written bare here; each is `agenticos:<tool>` on the connected AgenticOS server.

Offer a handful, not the list. Pick by what the user is doing; for a cold "what can I do?", pick by the permissions `whoami` returned and what the organization already has (`list_agents`, `list_routines`, `list_knowledge_bases`), and lead with the coding-session ideas below when the user is in a repository.

## Contents

- From a coding session
- How each use case was confirmed
- Observe and diagnose
- Build agents
- Knowledge and standing context
- Automate
- Records and tasks
- Improve quality
- People and setup
- Requests to decline

## From a coding session

Combinations that only make sense with a repository and a terminal at hand. Each uses chains from the tables below.

- After a deploy, list failed runs since the deploy time and group them by `error`.
- Pair `get_spend` with per-run token counts to find the agent burning context.
- Run a fixed set of regression prompts against an agent draft before publishing it.
- Load the repository's Markdown docs into a knowledge base so agents answer from them.
- Record each release or CI result as a table row keyed by commit SHA, for an agent or workflow to react to.
- Turn TODOs found in a review into tasks with `external_id` set, so a rerun creates no duplicates.
- Keep an agent's instructions in the repository and push edits to its draft, testing before each publish.

## How each use case was confirmed

The **Confirmed** column says how far each chain was exercised against a running deployment.

| Value | Meaning |
|---|---|
| live | The whole chain ran and returned the expected result. |
| reads live | Every discovery and read step ran. The write steps were not executed: their exact arguments were built from those reads and checked against the live tool schemas and the server source, because their effect cannot be undone over MCP or needs data the test organization lacked. |
| contract | Checked against the tool schemas and the server source only. The precondition is named. |

A use case that is not `live` is still valid; start it with its read steps, which show at once whether the organization has what it needs.

## Observe and diagnose

| Use case | A prompt that starts it | Tool chain | Confirmed |
|---|---|---|---|
| Explain a failed run | "Why did my last run fail?" | `list_runs` (`status: "failed"`) → `read_run_transcript` → `read_run_tool_call` → `get_run` → `get_agent` | live, except `read_run_tool_call`: the failed run found had recorded no tool call |
| Triage one channel or period | "What failed on Telegram since yesterday?" | `list_runs` with `surface`, `status`, `started_from` | live |
| Spend report | "What did our agents cost this month?" | `get_spend`, then `list_runs` per agent for the expensive ones | live |
| Organization snapshot | "Give me a status of this AgenticOS org" | `whoami` → `list_agents` → `list_routines` → `list_workflow_definitions` → `list_improvements` → `list_skills_behind_main` | live |
| Review a draft before publishing | "What is in this agent's draft?" | `get_agent` for `draft_spec`; the published side shows only as `current_version_id` (take summary fields such as `published_capabilities` from `list_agents`, which populates them), so say when a full diff needs the console's version history | live |
| Reread a past chat | "What did Architect tell me about budgets?" | `list_conversations` (`search`) → `read_conversation` → `read_conversation_tool_call` | reads live |

## Build agents

| Use case | A prompt that starts it | Tool chain | Confirmed |
|---|---|---|---|
| Draft, test and discard or publish an agent | "Build me an agent that triages support email" | `list_models` → `list_capabilities` → `get_capability` → `create_agent_draft` → `test_agent_draft` → `update_agent_draft` → `publish_agent` | live through test and discard; `publish_agent` by contract |
| Regression prompts before a publish | "Run these five questions against the draft" | `test_agent_draft` per prompt, `conversation_id` for follow-up turns | live |
| Agent that answers from documents | "An agent that answers from our handbook" | `list_knowledge_bases` → `get_capability` (`knowledge`) → `create_agent_draft` with `collection_ids` | reads live; needs a knowledge base |
| Give an agent a SaaS tool | "Let the agent read our GitHub issues" | `search_mcp_servers` → `list_org_connections` → `list_mcp_connection_tools` → `update_agent_draft` with `mcp_servers` | `search_mcp_servers` live; binding needs a connection made in the console |
| Coding agent with a shell | "An agent that can run Python on our data" | `list_sandbox_connections` → `get_sandbox_policy` → `create_agent_draft` with the `sandbox` capability | reads live |
| Agent that operates the platform | "An agent that tells people why runs failed" | `create_agent_draft` with `mcp_servers: [{account: "platform", approval: "writes"}]`, narrowed by `allowed_tools` | contract |
| Ask a published agent from the terminal | "Ask the research agent to summarise this" | `list_agents` → `run_agent` | live |

## Knowledge and standing context

| Use case | A prompt that starts it | Tool chain | Confirmed |
|---|---|---|---|
| Seed a knowledge base from a repository's docs | "Load our `docs/` folder so agents can answer from it" | `list_embedding_models` → `list_knowledge_bases` → `create_knowledge_base` → `add_document` per file → `search_knowledge` | reads live; creating needs an embedding key or a keyless provider |
| Check what an agent would retrieve | "Does the handbook collection cover parental leave?" | `list_knowledge_bases` → `search_knowledge` | reads live; needs a knowledge base |
| Publish a glossary or policy to agents | "Make every agent use our product names" | `list_context_files` → `create_context_file` → `update_agent_draft` with `context_ids` → `publish_agent` | live through create, update and binding to a draft; `publish_agent` by contract |
| Save a procedure that worked | "Make a skill of what we just did" | `list_skills` → `create_skill` → `add_skill_resource` → `update_agent_draft` with `skill_ids` | live through create, resource, update and binding to a draft |
| Draft a document for a question knowledge could not answer | "Write up what's missing on refunds" | `get_improvement` (knowledge topics) → `estimate_knowledge_draft` → `draft_knowledge_topic` | contract; needs an Improve session with topics |

## Automate

| Use case | A prompt that starts it | Tool chain | Confirmed |
|---|---|---|---|
| Scheduled report | "Every weekday at 9, summarise yesterday's failed runs" | `list_agents` → `list_routines` → `create_routine` → `run_routine_now` → `list_routines` | live for create, update and delete; `run_routine_now` by contract, because the test routine was saved paused (see the routine notes in automation.md) |
| Pause or retime a routine | "Pause the weekly digest until January" | `list_routines` → `update_routine` | live |
| Watch a personal account | "Tell me when a customer replies about the contract" | `list_my_connections` → `list_agents` → `create_watch` | reads live; needs a personal connection and the `personal:consent` scope |
| Build a workflow with its table | "When a form comes in, classify it and file it in a table" | `list_workflow_definitions` → `list_workflow_nodes` → `get_workflow_node` → `prepare_workflow_draft` → `check_workflow_draft` → `test_workflow_draft` → `get_workflow_execution_steps` → `publish_workflow` | live through test: the draft and table were created in one call, the test run classified a message and the record was read back; `publish_workflow` by contract |
| Wrap an HTTP API that has no MCP server | "Call our billing API when an invoice record changes" | `get_workflow_node` (`http.request`, `trigger.table_record`) → `prepare_workflow_draft` | reads live; the credential is a vault secret set in the console |
| Start a published workflow from the terminal | "Run the onboarding workflow for this customer" | `get_workflow_input_schema` → `run_workflow` → `get_workflow_execution` → `get_workflow_execution_steps` | contract; needs a published workflow |

## Records and tasks

| Use case | A prompt that starts it | Tool chain | Confirmed |
|---|---|---|---|
| Keep an operational table in sync | "Mirror our open incidents into a table" | `list_virtual_tables` → `create_virtual_table` → `get_virtual_table` → `upsert_virtual_table_record` keyed by `external_id` | live: upsert by `external_id`, update against the revision, query |
| Query records | "Which leads have no owner?" | `list_virtual_tables` → `get_virtual_table` → `query_virtual_table` with typed `filters` | live, including a `single_select` filter by option UUID |
| Durable follow-ups | "Remind me Friday to check the migration" | `list_task_boards` → `ensure_task_board` → `create_task` → `update_task` | live: created, re-created with the same `external_id` (returned the same task), updated against its revision, then removed with `delete_virtual_table_record` |
| Hand a task to an agent | "Have the research agent draft this by Monday" | `create_task` with `assignee_agent_id`, `next_actor: "agent"`, `start_at` | contract |

## Improve quality

These need a connection signed in with OAuth, and every step that spends is priced first.

| Use case | A prompt that starts it | Tool chain | Confirmed |
|---|---|---|---|
| Improve an agent against test questions | "Make the support agent better on our test set" | `list_datasets` → `estimate_improvement` → `start_improvement` → `get_improvement` → `estimate_next_improvement_step` → `run_next_improvement_step` → `accept_improvement` | reads live; needs a dataset |
| Check where improving stands | "How is the Improve session going?" | `list_improvements` → `get_improvement` | live |
| Improve a shared skill safely | "Fix the refund skill without breaking other agents" | `get_skill` → `estimate_skill_improvement` → `start_skill_improvement` → `get_skill_improvement` → `accept_skill_improvement` | `estimate_skill_improvement` live; starting needs runs that used the skill |
| Catch pinned agents up | "Which agents are on an old skill version?" | `list_skills_behind_main` → `estimate_skill_update_check` → `start_skill_update_check` → `get_skill_check` → `change_skill_version` | reads live |

## People and setup

| Use case | A prompt that starts it | Tool chain | Confirmed |
|---|---|---|---|
| Onboard a teammate | "Invite Ana as a builder" | `list_members` → `invite_member` | reads live; sends a real email |
| A home for ongoing work | "Set up a project for the Q3 audit" | `list_projects` → `create_project` → `get_project` | reads live |
| Tell agents who the user is | "I'm head of sales, remember that" | `set_my_profile` | contract |
| Check a connected service | "Is my Notion connection still working?" | `list_my_connections` → `test_my_connection` | reads live; needs a personal connection |

## Requests to decline

Say plainly that the MCP connection does not do these and that the console does. Give a console path only when a tool result supplied it.

| Request | Why |
|---|---|
| "Add our OpenAI key" or "rotate the token" | Credentials are never exposed over MCP. |
| "Delete that agent, workflow, table or knowledge base" | Only an unpublished draft the caller created, a routine, a watch and a table record can be deleted. |
| "Upload this PDF to the knowledge base" | `add_document` takes text. Convert to Markdown first, or upload in the console. |
| "Clear my Inbox" | Inbox tools refuse an external MCP client with `AUTHORIZATION_ERROR`. |
| "Let the agent use my local folder" | Native access is granted in the Desktop app. |
