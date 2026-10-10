# Glossary

The words the console uses, what each one means, and the name the same thing
has in the API, the spec and the YAML an agent exports. The console, the
onboarding tour, the AI Architect and these pages use these names; the API and
the spec keep their own, so a script written against them never breaks over a
rename.

## What you build

| In the console | What it is | In the API and spec |
|---|---|---|
| Agent | An assistant with its own instructions, model, knowledge and tools | `agent` |
| Draft | An agent's unpublished changes; nothing outside the Builder sees them | `draft_spec` |
| Publish | Freeze the draft as a numbered version that every surface runs | `POST /agents/{id}/publish` |
| Version | One published state of an agent, kept and comparable | `agent_version` |
| Test panel | The chat beside the Builder that answers as the draft or any version | `is_test` on its runs |
| Instructions | What the agent is told before every conversation | `instructions` |
| Variables | `{{name}}` in the instructions, filled in when a run starts | `variables` |
| Capability | Something an agent may do, switched on in the Builder | `capabilities[]` |
| Skill | Know-how written once and read by any agent that needs it | `skill` |
| Context file | Standing knowledge an agent always has, such as a glossary or a policy | `context` |
| Knowledge base | Documents an agent searches and cites | `collection` |
| App | A page an agent publishes, such as a report or a small dashboard | `artifact` |
| AI Architect | The assistant in the corner of every page, which can build agents with you | `platform-assistant` |

## Where it runs

| In the console | What it is | In the API and spec |
|---|---|---|
| Chat | The web conversation with an agent | `conversation` |
| Channel | Slack, Telegram or Mattermost, where people reach an agent | `channel_bot` |
| Routine | An agent running on its own, on a schedule or an event | `trigger` |
| Run | One time an agent answered, with its cost and steps | `agent_run` |
| Environment | A named stage, such as production, pointing at one version | `environment` |
| MCP server | An external tool server agents call, connected once | `mcp_connection` |
| Sandbox | An isolated computer where an agent writes files and runs code | `sandbox` |
| Agent files | The files agents keep in their sandboxes | `workspace` |

## Who decides

| In the console | What it is | In the API and spec |
|---|---|---|
| Organization | The company or team everything belongs to | `organization` |
| Group | A department or team that agents, skills and knowledge are shared with | `group` |
| Lead | A group member who manages who else is in it | `is_lead` |
| Approval | A tool call waiting for a person to allow it | `approval` |
| Budget | A spending limit that stops runs when it is reached | `budget` |
| Guardrails | Checks that redact or block what flows through a run | `guardrails` |
| Vault | Where keys and tokens are stored, sealed and never shown again | `secret` |

## Capabilities

The name the Builder shows, and the id an agent's spec binds. Each is described
in [Capabilities](capabilities.md).

| In the console | In the spec |
|---|---|
| Apps | `artifacts` |
| Ask the user | `ask_user` |
| Web browser (step by step) | `browser_choice` |
| Web browser | `browser_use` |
| Chat channel lookup | `channel_tools` |
| Charts | `charts` |
| Date and time | `clock` |
| Calculations | `code_execution` |
| Long conversations | `compaction` |
| Context | `context` |
| Past conversations | `conversation_search` |
| Guardrails | `guardrails` |
| Image generation | `image_generation` |
| Knowledge search | `knowledge` |
| Media offload | `media` |
| Memory | `memory_files` |
| Memory (mem0) | `memory_mem0` |
| Planning | `planning` |
| Sandbox | `sandbox` |
| Skills | `skills` |
| Delegation | `subagents` |
| Instruction reminders | `system_reminders` |
| Thinking | `thinking` |
| Tool output limits | `tool_output_limits` |
| Tool search | `tool_search` |
| Read web pages | `web_fetch` |
| Web search | `web_research` |
