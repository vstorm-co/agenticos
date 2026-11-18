# Tool map

Every tool on the `agenticos` server by domain, with the permission it needs. Call each as `agenticos:<tool>`. Compare the **Needs** column with the permissions `agenticos:whoami` returned before starting a task.

The connected server is the authority: if a tool here is missing from the connection, the deployment is older or the connection was narrowed; if the connection has a tool not listed here, use it by its own description.

## Contents

- Identity and people
- Agents
- Capabilities, models, MCP servers and sandboxes
- Runs, conversations and spend
- Routines and watches
- Tasks and Inbox
- Knowledge and context
- Skills
- Agent Improve sessions
- Workflows
- Virtual Tables
- Projects and Apps
- Size limits

## Identity and people

| Tool | Needs | Changes something |
|---|---|---|
| `whoami` | nothing | no |
| `list_members` | `members:view` | no |
| `invite_member` | `members:manage` and `roles:manage`; a role above the caller's is refused | yes, sends an email |
| `set_my_language`, `set_my_profile` | the caller's own account | yes |

## Agents

| Tool | Needs | Changes something |
|---|---|---|
| `list_agents`, `get_agent` | `agents:view` | no |
| `create_agent_draft`, `update_agent_draft` | `agents:edit` | yes, the draft only |
| `test_agent_draft`, `answer_agent_questions` | `agents:edit` | yes, a recorded and budgeted test run |
| `publish_agent` | `agents:publish` on that agent | yes, live on every surface |
| `discard_agent_draft` | `agents:edit`, on an unpublished draft the caller created | yes, deletes it |
| `run_agent` | `agents:run` | yes, a recorded and budgeted run |

## Capabilities, models, MCP servers and sandboxes

| Tool | Needs | Changes something |
|---|---|---|
| `list_capabilities`, `get_capability`, `list_models`, `search_mcp_servers` | `agents:view` | no |
| `list_org_connections` | `mcp:manage` | no |
| `list_mcp_connection_tools`, `get_mcp_connection_tool` | `mcp:manage` for organization connections; the caller's own for personal ones | no |
| `list_my_connections` | the caller's own | no |
| `test_my_connection` | the caller's own; a key also needs `agents:run` | yes, refreshes recorded status and tools |
| `list_sandbox_connections`, `list_sandbox_runtimes`, `get_sandbox_policy` | `connections:view` | no |

## Runs, conversations and spend

| Tool | Needs | Changes something |
|---|---|---|
| `list_runs`, `get_run`, `read_run_transcript`, `read_run_tool_call`, `get_spend` | `runs:view` | no |
| `list_conversations`, `read_conversation`, `read_conversation_tool_call` | `runs:view`; the caller's own chats only | no |
| `create_conversation` | `agents:run` | yes |
| `get_eval_run` | `runs:view` | no |

`read_run_transcript` reads any run the caller's `runs:view` covers, including channel and colleagues' runs. `read_conversation` never reaches another member's chat. Both omit turns a guardrail refused.

## Routines and watches

| Tool | Needs | Changes something |
|---|---|---|
| `list_routines` | `agents:view` | no |
| `create_routine`, `run_routine_now` | `agents:run` on the agent | yes |
| `update_routine`, `delete_routine` | the routine's creator, or `agents:edit` on its agent | yes |
| `list_watches` | the caller's own | no |
| `create_watch`, `update_watch`, `delete_watch` | the person themselves, with the `personal:consent` scope; `agents:run` on the chosen agent | yes |
| `update_proactivity_settings` | `org:settings` and `budgets:manage` | yes, organization-wide |

## Tasks and Inbox

| Tool | Needs | Changes something |
|---|---|---|
| `list_task_boards`, `list_tasks`, `get_task` | `tables:view` | no |
| `ensure_task_board` | `tables:create` on first use | yes, when the board is missing |
| `create_task`, `update_task` | `tables:edit` on the scope | yes |
| `list_inbox_cases`, `settle_inbox_case` | the person's own chat or console session; refused for an external MCP client | no / yes |

## Knowledge and context

| Tool | Needs | Changes something |
|---|---|---|
| `list_knowledge_bases`, `search_knowledge` | `collections:view` | no |
| `list_embedding_models` | nothing | no |
| `create_knowledge_base`, `add_document` | `collections:edit` | yes |
| `estimate_knowledge_draft` | `runs:view` and edit access to the topic's knowledge base | no |
| `draft_knowledge_topic` | the same, plus a model and budget | yes, spends |
| `list_context_files`, `get_context_file` | `context:view` | no |
| `create_context_file`, `update_context_file` | `context:edit` | yes |

## Skills

| Tool | Needs | Changes something |
|---|---|---|
| `list_skills`, `get_skill`, `list_skill_versions`, `get_skill_version`, `list_skills_behind_main` | `skills:view` | no |
| `create_skill`, `update_skill`, `add_skill_resource` | `skills:edit` | yes |
| `list_skill_improvements`, `get_skill_improvement`, `get_skill_check` | `skills:view` and `runs:view` | no |
| `estimate_skill_improvement`, `estimate_next_skill_improvement_step`, `estimate_skill_update_check`, `estimate_skill_catch_up` | `skills:edit` and `runs:view` | no |
| `start_skill_improvement`, `run_next_skill_improvement_step`, `retry_skill_improvement_step`, `start_skill_update_check`, `start_skill_catch_up` | `skills:edit` and `runs:view` | yes, spends |
| `accept_skill_improvement`, `end_skill_improvement` | `skills:edit`; pinning worse agents also `agents:publish` on each | yes |
| `change_skill_version`, `return_skill_fork_to_main` | `agents:edit` on each agent; going live also `agents:publish` | yes |

## Agent Improve sessions

These refuse an organization API key; they need an OAuth connection.

| Tool | Needs | Changes something |
|---|---|---|
| `list_datasets` | `datasets:view` | no |
| `list_improvements`, `get_improvement` | read access to the agent; `runs:view` for knowledge topics and for listing without an agent | no |
| `estimate_improvement`, `estimate_next_improvement_step`, `estimate_improve_again` | `agents:edit` and `runs:view`; the first also `datasets:run` | no |
| `start_improvement`, `run_next_improvement_step`, `improve_again` | `agents:edit` and `runs:view`; starting also `datasets:run` | yes, spends |
| `use_attempt`, `end_improvement` | `agents:edit` and `runs:view` | yes |
| `accept_improvement` | `agents:edit` and `runs:view`; `publish: true` also `agents:publish` | yes |

## Workflows

| Tool | Needs | Changes something |
|---|---|---|
| `list_workflow_definitions`, `get_workflow_definition`, `list_workflow_nodes`, `get_workflow_node`, `get_workflow_input_schema`, `check_workflow_draft` | `workflows:view` | no |
| `get_workflow_execution`, `get_workflow_execution_steps` | `workflows:view` | no |
| `create_workflow_draft`, `prepare_workflow_draft` | `workflows:create`; table permissions when a table is included | yes |
| `update_workflow_draft` | `workflows:edit` | yes |
| `test_workflow_draft` | edit and run access | yes, real external effects |
| `publish_workflow` | `workflows:edit`; a member session for unattended triggers | yes, activates triggers |
| `run_workflow` | `workflows:run` | yes |

## Virtual Tables

| Tool | Needs | Changes something |
|---|---|---|
| `list_virtual_tables`, `get_virtual_table`, `query_virtual_table`, `get_virtual_table_record`, `virtual_table_record_exists`, `list_virtual_table_views` | `tables:view` | no |
| `create_virtual_table` | `tables:create` | yes |
| `update_virtual_table_schema`, `add_virtual_table_record`, `update_virtual_table_record`, `upsert_virtual_table_record`, `delete_virtual_table_record` | edit access to the table | yes |

## Projects and Apps

| Tool | Needs | Changes something |
|---|---|---|
| `list_projects` | `projects:view` | no |
| `get_project` | access to that project | no |
| `create_project` | `projects:edit` | yes |
| `create_app_public_link` | edit access to the App, and the user's explicit confirmation that its content may be read outside the organization | yes, public |

`create_project` creates the project only: not its files, an agent or a schedule. `create_app_public_link` needs a real `artifact_id` from an App an agent published; never guess one.

## Size limits

Discovery responses are refused in full, never truncated, when they exceed their budget.

| Response | Limit | Then |
|---|---|---|
| Listings and transcript windows | 64 KiB | narrow `q`, lower `limit`, or lower `content_chars` / `chars` |
| `get_workflow_input_schema` | 32 KiB | read the contract through the HTTP API outside the model context |
| One transcript message | `content_chars` up to 8000 | repeat with `skip` set to its `message_index`, `limit: 1` and `content_offset` set to `next_offset` |
