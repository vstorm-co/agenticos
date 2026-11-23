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
| `publish_agent` | `agents:publish` on that agent | yes, publishes a version; environment pointers decide who serves it |
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
| `publish_inbox_finding` | a live routine or monitor run credential; only its own owner, no arbitrary recipient | yes; automatically available with no general platform scopes when unbound |
| `list_inbox_items` | the signed-in person in an unshared private chat or console session; refused for an external MCP client | no, at most 30 summaries; use `item_id` for one card |
| `list_inbox_cases`, `settle_inbox_case` | the person's own chat or console session; refused for an external MCP client | no / yes |
| `list_inbox_items` | the person's own chat or console session | no |

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

## Progressive disclosure (MCP contract 2)

Search before listing, start with `limit: 10`, and follow `next_skip`. Discovery
returns identity and state, not resource bodies. Use `detailed: true` only when
needed, or the named detail tools below. A summary is never a complete editable
workflow graph or authoring schema. Read the full graph before replacing it;
preserve bindings and use the current revision for writes.

Every successful tool result is bounded to 16 KiB. Oversized reads return a
`continuation` for `read_platform_details`: first inspect JSON pointers, then read
only the chosen pointer in `mode: content`. Continue `next_offset`/`next_skip`;
pass `value_hash` as `expected_hash` to avoid mixing revisions. JSON fragments
must be assembled before parsing. Handles last five minutes, belong to the exact
credential and original authorized read, and cannot select another tool or its
arguments. Every fragment rechecks API access. After expiry or a changed result,
execute and authorize the original read again. An unavailable original tool cannot
be invoked through this reader.

Large writes return identity/status receipts, never a false size failure after a
successful mutation. Do not repeat a write for its body: use its named read tool
with the required read permission. Request completion does not prove that an
asynchronous run, ingestion or deployment succeeded. Validation errors are bounded
and remain explicit refusals. Transcript windows still support up to 8000 chars;
new body windows support up to 2000 chars.

| Tool | Needs | Changes something |
|---|---|---|
| `read_platform_details` | continuation from an already authorized oversized read; original API access rechecked | no |
| `get_authoring_schema` | authenticated caller; contracts contain no resource content | no |
| `read_context_file_content` | read access to the context file | no |
| `read_skill_content`, `get_skill_resource`, `list_skill_agents`, `list_skill_forks`, `list_skill_resources` | read access to the skill; hidden agent identities remain hidden | no |
| `get_dataset_case`, `read_dataset_case_field` | read access to the selected dataset/version | no |
| `get_model_profile`, `get_model_provider` | the corresponding model/provider read permission | no |
| `get_embedding_endpoint` | `connections:view` | no |
| `get_agent_environment`, `get_eval_suite` | read access to the agent | no |
| `get_knowledge_source`, `get_knowledge_connector` | knowledge/source discovery access | no |
| `get_routine`, `get_watch` | the same resource access as their listings | no |
| `list_workflow_definition_nodes`, `get_workflow_definition_node` | read access to the workflow | no |
| `get_workflow_execution_step` | read access to the run; actual node-run ID, including loop instance | no |
| `prepare_solution` | `agents:edit`; reserves a principal-scoped review for 24 hours | yes, temporary review only |
| `get_solution_installation` | `agents:edit`; only the caller's receipt in this organization | no |
| `get_my_preferences` | the caller's own account, `agents:run` for keys | no |
| `set_my_preferences` | the caller's own account, `agents:run` for keys | yes, theme/style/language only |
| `get_my_console_experience` | active personal membership, `agents:run` for keys | no, reads presentation availability, defaults and effective preferences |
| `set_my_console_experience` | active personal membership, `agents:run` for keys | yes, own chat-home and setup-reminder overrides only; omitted fields stay, null inherits |

Use `get_authoring_schema` for solution, agent, workflow or workflow-preparation
contracts rather than loading those schemas into every tool definition. The API
still validates the complete typed payload. For a large solution, review with
`prepare_solution`, then call `install_solution` with `plan_id`, `installation_key`
and `expected_manifest_hash` rather than resending the manifest. An expired review
can be prepared again; the durable installation receipt still prevents duplicate
resources. For tables, select only required `columns` in `query_virtual_table`.

## Dependency setup and release lifecycle

These require MCP contract 1, discovered with `get_platform_context`. Availability
is distinct from the caller's scopes. OAuth reaches assistant-only routes; an
ordinary organization API key is refused on those routes.

| Tool | Needs | Changes something |
|---|---|---|
| `get_platform_context`, `get_setup_link` | authenticated caller | no |
| `list_secret_references` | `secrets:view`; metadata only | no |
| `list_model_providers` | `agents:view` | no |
| `create_model_profile`, `update_model_profile` | `connections:manage` and access to referenced keys | yes |
| `list_embedding_endpoints` | `connections:view` | no |
| `create_embedding_endpoint` | `connections:manage`; organization-owned only | yes |
| `get_knowledge_base`, `list_knowledge_documents`, `get_knowledge_ingestion` | read access to the base | no |
| `list_knowledge_connectors`, `list_knowledge_sources`, `list_knowledge_sync_logs` | read access to the base and source | no |
| `create_knowledge_source`, `sync_knowledge_source` | edit access to the base and referenced key | yes |
| `create_dataset` | `datasets:edit` | yes |
| `get_dataset`, `list_dataset_cases` | read access to the dataset | no |
| `add_dataset_case` | edit access to the dataset | yes, a dataset version |
| `estimate_eval_run` | agent and dataset access | no |
| `start_eval_run` | agent access and dataset run access | yes, budgeted background work |
| `list_agent_versions`, `get_agent_version` | read access to the agent | no |
| `list_agent_environments`, `get_promotion_gate` | read access to the agent | no |
| `create_agent_environment`, `update_agent_environment` | publish access; stronger checks for guards and overrides | yes |
| `run_promotion_gate` | publication/run authority and guarding suite admission | yes, may spend |
| `list_eval_suites`, `estimate_eval_suite` | agent and dataset access | no |
| `create_eval_suite`, `update_eval_suite` | agent/dataset access and standing personal authority | yes |
| `plan_solution` | `agents:view`; validates caller-supplied content only | no |
| `install_solution` | `agents:edit` and every permission in the plan | yes, private drafts atomically |

## Administration

| Tool | Needs | Changes something |
|---|---|---|
| `list_administration_actions` | authenticated caller; metadata discovery only | no |
| `get_administration_schema` | authenticated caller; selected action contract only | no |
| `read_administration` | selected action's organization permissions, or explicit external OAuth `deployment:admin` plus live app-admin flag | no |
| `change_organization` | selected action's organization permissions; connected tenant only | yes; internal agents always ask |
| `change_deployment` | explicit external OAuth `deployment:admin` plus live app-admin flag | yes; unavailable to internal agents |

Search actions by task or field, inspect the exact body/path schema, read current
configuration and send only intended changes. Never treat role ownership as an
OAuth grant. Reauthorize an existing external connection with the separate,
initially unchecked deployment-administration consent option. Built-in agents,
routines and ordinary keys cannot acquire global authority. Secret entry and
binary uploads return secure console links. Assistant configuration reads do not
install anything; installation/refresh is a write that can publish ready defaults.
Read update status after preparation/application; a receipt is not completion.
