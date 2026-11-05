---
name: platform-agents
description: "Build or repair an AgenticOS agent: choose capabilities and MCP tools, write its prompt, bind skills and knowledge, test failure cases and publish a verified version. Use for agent setup and configuration, not a one-off specialist."
category: engineering
---

# Build an agent around an observable job

Start with the outcome, its audience, the source of truth and the actions allowed.
Inspect the existing agent, available models, capabilities, skills and connections
before creating anything. Platform MCP tools may have an `agenticos_` prefix;
discover the current names with tool search. Read `list_capabilities` configuration
schemas rather than guessing an identifier or copying another provider's settings.

## Choose only what the job needs

| Need | Choose | Check |
| --- | --- | --- |
| Company records and platform setup | Platform MCP binding | The caller's access and write approvals still apply |
| Clarify a consequential choice | `ask_user` | Prefer its question tool to a list of questions in prose |
| A reusable procedure | `skills` and the relevant skill IDs | Skills describe work; they do not grant tools |
| Standing background information | Context files | Small, current and appropriate for every reader of this agent |
| Search a document corpus | Knowledge collections | Retrieval and citations; test absent evidence |
| Cross-chat preferences and decisions | `memory_files` | Private scope, stable subjects, corrections with history |
| Current external facts | Web research and fetch | Open primary sources; account access needs its connection |
| Calculations and files | Sandbox | Files-only is not a shell; inspect the actual execution policy |
| Durable records and commitments | Platform Tables and Task tools | Typed state, scope, revisions and explicit next actor |
| A visual or reusable page | `visuals`, `charts`, `artifacts` | Load the matching design skill and preview the result |
| Broad investigation or review | `subagents` | Bound brief and actual tools; default dynamic specialists have none |
| Work while the person keeps chatting | `background_tasks` | A persistent topic differs from a background tool in this run |
| Substantial coding | Coding agent, if configured | Desktop pairing or sandbox credentials; never assume access |

Keep service-specific actions on their actual connection. An AgenticOS MCP binding
does not automatically connect mail, a CRM or a filesystem. Use catalog connection
cards for missing services, without requesting secrets in chat. Discover before
adding separate Workflows or Tables capabilities that duplicate platform tools.

## Write the instructions as a working contract

Describe the role, deliverable, source precedence, workflow, permitted actions,
failure handling and completion evidence. Put the core job first. Explain how to
handle missing data, refused access, stale revisions and uncertainty. Specify
language and output only where they matter. Avoid contradictory instructions,
unconditional permission questions and claims of access the runtime may lack.

For example: “Prepare supplier follow-up drafts from the project table and the
connected mailbox. Read the latest thread before drafting. Save the draft in the
working chat, keep its task waiting for review, and send only when the person
requests it and the send tool succeeds.” This defines a verifiable outcome.

## Build, test, publish

Use `create_agent_draft` or read and update the existing draft. Supplied skill,
knowledge and MCP lists replace their whole list: preserve entries still needed.
Use IDs returned by discovery, never plausible UUIDs. A capability configuration
replacement must retain the settings that still apply. Bound delegates and local
resources require their actual published versions and permissions.

Test the draft on an ordinary request, missing evidence, an unavailable tool and
a document containing instructions to leak data. Test only authorized effects;
a draft test can call real services and spend model budget. Inspect its answer,
tool results and run. Repair the draft and retest the failed case. Publication is
separate: use `publish_agent` when authorized or link its Builder for the person's
Publish action. Report the agent/version, what passed and what remains blocked.
