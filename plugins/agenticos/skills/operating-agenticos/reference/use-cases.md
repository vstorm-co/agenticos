# Use cases

Ideas to offer, each with the tool chain that delivers it. Tool names are written bare here; each is `agenticos:<tool>` on the connected AgenticOS server.

Offer a handful, not the list. Pick by what the user is doing; for a cold "what can I do?", pick by the permissions `whoami` returned and what the organization already has (`list_agents`, `list_routines`, `list_knowledge_bases`), and lead with the coding-session ideas when the user is in a repository.

The **Needs** column names what must already exist. Check it with the chain's first read step before promising the rest.

## Contents

- From a coding session
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

## Observe and diagnose

| Use case | A prompt that starts it | Tool chain | Needs |
|---|---|---|---|
| Explain a failed run | "Why did my last run fail?" | `list_runs` (`status: "failed"`) → `read_run_transcript` → `read_run_tool_call` → `get_run` → `get_agent` | a failed run |
| Triage one channel or period | "What failed on Telegram since yesterday?" | `list_runs` with `surface`, `status`, `started_from` | |
| Spend report | "What did our agents cost this month?" | `get_spend`, then `list_runs` per agent for the expensive ones | |
| Organization snapshot | "Give me a status of this AgenticOS org" | `whoami` → `list_agents` → `list_routines` → `list_workflow_definitions` → `list_improvements` → `list_skills_behind_main` | |
| Review a draft before publishing | "What is in this agent's draft?" | `get_agent` for `draft_spec`; the published side shows only as `current_version_id` (summary fields such as `published_capabilities` come from `list_agents`), so say when a full diff needs the console's version history | |
| Reread a past chat | "What did Architect tell me about budgets?" | `list_conversations` (`search`) → `read_conversation` → `read_conversation_tool_call` | |

## Build agents

| Use case | A prompt that starts it | Tool chain | Needs |
|---|---|---|---|
| Draft, test and publish an agent | "Build me an agent that triages support email" | `list_models` → `list_capabilities` → `get_capability` → `create_agent_draft` → `test_agent_draft` → `update_agent_draft` → `publish_agent` | a model profile with a key |
| Regression prompts before a publish | "Run these five questions against the draft" | `test_agent_draft` per prompt, `conversation_id` for follow-up turns | |
| Agent that answers from documents | "An agent that answers from our handbook" | `list_knowledge_bases` → `get_capability` (`knowledge`) → `create_agent_draft` with `collection_ids` | a knowledge base |
| Agent that follows a procedure | "Make the agent use our refund skill" | `list_skills` → `update_agent_draft` with the `skills` capability and `skill_ids` → `test_agent_draft` → `publish_agent` | a skill |
| Give an agent a SaaS tool | "Let the agent read our GitHub issues" | `search_mcp_servers` → `list_org_connections` → `list_mcp_connection_tools` → `update_agent_draft` with `mcp_servers` | an organization connection, made in the console |
| Coding agent with a shell | "An agent that can run Python on our data" | `list_sandbox_connections` → `get_sandbox_policy` → `create_agent_draft` with the `sandbox` capability | an active sandbox host |
| Agent that operates the platform | "An agent that tells people why runs failed" | `create_agent_draft` with `mcp_servers: [{account: "platform", approval: "writes"}]`, narrowed by `allowed_tools` | |
| Ask a published agent from the terminal | "Ask the research agent to summarise this" | `list_agents` → `run_agent` | a published agent |

## Knowledge and standing context

| Use case | A prompt that starts it | Tool chain | Needs |
|---|---|---|---|
| Seed a knowledge base from a repository's docs | "Load our `docs/` folder so agents can answer from it" | `list_embedding_models` → `list_knowledge_bases` → `create_knowledge_base` → `add_document` per file → `search_knowledge` | an embedding key, or a keyless provider's endpoint |
| Check what an agent would retrieve | "Does the handbook collection cover parental leave?" | `list_knowledge_bases` → `search_knowledge` | a knowledge base |
| Publish a glossary or policy to agents | "Make every agent use our product names" | `list_context_files` → `create_context_file` → `update_agent_draft` with `context_ids` → `publish_agent` | |
| Save a procedure that worked | "Make a skill of what we just did" | `list_skills` → `create_skill` → `add_skill_resource` → `update_agent_draft` with `skill_ids` | |
| Draft a document for a question knowledge could not answer | "Write up what's missing on refunds" | `get_improvement` (knowledge topics) → `estimate_knowledge_draft` → `draft_knowledge_topic` | an Improve session with knowledge topics |

## Automate

| Use case | A prompt that starts it | Tool chain | Needs |
|---|---|---|---|
| Scheduled report | "Every weekday at 9, summarise yesterday's failed runs" | `list_agents` → `list_routines` → `create_routine` → `run_routine_now` → `list_routines` | a published agent; the `personal:consent` scope when the routine acts as its creator |
| Pause or retime a routine | "Pause the weekly digest until January" | `list_routines` → `update_routine` | a routine |
| Watch a personal account | "Tell me when a customer replies about the contract" | `list_my_connections` → `list_agents` → `create_watch` | a personal connection and the `personal:consent` scope |
| Build a workflow with its table | "When a form comes in, classify it and file it in a table" | `list_workflow_definitions` → `list_workflow_nodes` → `get_workflow_node` → `prepare_workflow_draft` → `check_workflow_draft` → `test_workflow_draft` → `get_workflow_execution_steps` → `publish_workflow` | a model profile for `ai.*` steps |
| Wrap an HTTP API that has no MCP server | "Call our billing API when an invoice record changes" | `get_workflow_node` (`http.request`, `trigger.table_record`) → `prepare_workflow_draft` | a vault secret, set in the console |
| Start a published workflow from the terminal | "Run the onboarding workflow for this customer" | `get_workflow_input_schema` → `run_workflow` → `get_workflow_execution` → `get_workflow_execution_steps` | a published workflow with a Manual or API entry |

## Records and tasks

| Use case | A prompt that starts it | Tool chain | Needs |
|---|---|---|---|
| Keep an operational table in sync | "Mirror our open incidents into a table" | `list_virtual_tables` → `create_virtual_table` → `get_virtual_table` → `upsert_virtual_table_record` keyed by `external_id` | |
| Query records | "Which leads have no owner?" | `list_virtual_tables` → `get_virtual_table` → `query_virtual_table` with typed `filters` | a table |
| Durable follow-ups | "Remind me Friday to check the migration" | `list_task_boards` → `ensure_task_board` → `create_task` → `update_task` | |
| Hand a task to an agent | "Have the research agent draft this by Monday" | `create_task` with `assignee_agent_id`, `next_actor: "agent"`, `start_at` | a published agent |

## Improve quality

These need a connection signed in with OAuth, and every step that spends is priced first.

| Use case | A prompt that starts it | Tool chain | Needs |
|---|---|---|---|
| Improve an agent against test questions | "Make the support agent better on our test set" | `list_datasets` → `estimate_improvement` → `start_improvement` → `get_improvement` → `estimate_next_improvement_step` → `run_next_improvement_step` → `accept_improvement` | a dataset with `can_run` true |
| Check where improving stands | "How is the Improve session going?" | `list_improvements` → `get_improvement` | |
| Improve a shared skill safely | "Fix the refund skill without breaking other agents" | `get_skill` → `estimate_skill_improvement` → `start_skill_improvement` → `get_skill_improvement` → `accept_skill_improvement` | rated or failed runs that used the skill |
| Catch pinned agents up | "Which agents are on an old skill version?" | `list_skills_behind_main` → `estimate_skill_update_check` → `start_skill_update_check` → `get_skill_check` → `change_skill_version` | an agent pinned behind main |

## People and setup

| Use case | A prompt that starts it | Tool chain | Needs |
|---|---|---|---|
| Onboard a teammate | "Invite Ana as a builder" | `list_members` → `invite_member` | |
| A home for ongoing work | "Set up a project for the Q3 audit" | `list_projects` → `create_project` → `get_project` | |
| Tell agents who the user is | "I'm head of sales, remember that" | `set_my_profile` | |
| Check a connected service | "Is my Notion connection still working?" | `list_my_connections` → `test_my_connection` | a personal connection |

## Requests to decline

Say plainly that the MCP connection does not do these and that the console does. Give a console path only when a tool result supplied it.

| Request | Why |
|---|---|
| "Add our OpenAI key" or "rotate the token" | Credentials are never exposed over MCP. |
| "Delete that agent, workflow, table or knowledge base" | Only an unpublished draft the caller created, a routine, a watch and a table record can be deleted. |
| "Upload this PDF to the knowledge base" | `add_document` takes text. Convert to Markdown first, or upload in the console. |
| "Clear my Inbox" | Inbox tools refuse an external MCP client with `AUTHORIZATION_ERROR`. |
| "Let the agent use my local folder" | Native access is granted in the Desktop app. |
