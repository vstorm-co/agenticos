# Glossary

The words the console uses, what each one means, and the name the same thing
has in the API, the spec and the YAML an agent exports. The console, the
onboarding tour, the Architect and these pages use these names; the API and
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
| First messages | What an empty chat offers whoever opens the agent, one click each | `starters` |
| Capability | Something an agent may do, switched on in the Builder | `capabilities[]` |
| Skill | Know-how written once and read by any agent that needs it | `skill` |
| Skill version | One saved state of a skill, never changed afterwards; **Restore** brings an earlier one back as a new version | `skill_version` |
| Main | A skill's main line; an agent on main reads its newest version | `state: main` |
| Pinned | An agent that stays on one main version of a skill until somebody moves it | `state: pinned` |
| Fork | A named line of a skill, started from a main version, with versions of its own for some agents | `skill_fork`, `state: fork` |
| Behind main | How many main versions a pinned agent or a fork has not taken | `behind_main` |
| Catch up | Bring a pinned agent or a fork onto main's newest version; only on request, and checked first | `/skills/behind-main` |
| Context file | Standing knowledge an agent always has, such as a glossary or a policy | `context` |
| Knowledge base | Documents an agent searches and cites | `collection` |
| Knowledge gap | A topic of questions a knowledge base could not answer, grouped by meaning; Improve counts them as **Missing from the knowledge base** | `knowledge_gap_topic` |
| App | A page an agent publishes, such as a report or a small dashboard | `artifact` |
| Architect | The assistant in the corner of every page, which can build agents with you | `platform-assistant` |
| System agent | An agent the platform runs itself, such as a judge, the gap drafter or the gap classifier; listed apart under **System agents** | `kind` other than `agent` |
| Authoring assistant | Suggests changes to an agent, a skill or a context file from rated-down answers; a person decides each | `authoring` |
| Suggestion | One proposed change to a draft, accepted, edited or dismissed on its own | `spec_proposal_hunk` |
| Setting change | A suggestion to change one part of an agent's configuration, such as its model or a capability | `spec_field` hunk |
| Context file change | A new body the assistant proposed for a context file, applied or discarded on the Context page | `context_proposal` |
| AgenticOS | The general-purpose agent a new organization opens with in Chat, and what a new agent starts as | `general/agenticos` |

## Where it runs

| In the console | What it is | In the API and spec |
|---|---|---|
| Chat | The web conversation with an agent | `conversation` |
| Channel | Slack, Telegram, Mattermost or Discord, where people reach an agent | `channel_bot` |
| Routine | An agent running on its own, on a schedule or an event | `trigger` |
| Eval suite | A dataset an agent is held to, run on a schedule, on publish or promotion, or after a change | `eval_suite` |
| Run | One time an agent answered, with its cost and steps | `agent_run` |
| Environment | A named stage, such as production, pointing at one version | `environment` |
| Guard | An eval suite an environment requires to pass on a version before it takes it | `guard_suite_ids` |
| Override | A promotion made past guards that had not passed, with a reason | `override_reason` |
| MCP server | An external tool server agents call, connected once | `mcp_connection` |
| Remote agent | Another vendor's agent, reached over A2A, that agents delegate to | `external_agent` |
| Agent2Agent (A2A) | The protocol other systems' agents use to send an agent tasks | `a2a_enabled` |
| Sandbox | An isolated computer where an agent writes files and runs code | `sandbox` |
| Documents | The files agents keep for a person, attached or written, in their sandboxes | `workspace` |

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
| Evaluation helpers | Code-defined grading, generation and improvement pipelines configured on a dataset | `scoring.judge`, `helper_settings` |

## How it is tested

| In the console | What it is | In the API and spec |
|---|---|---|
| Dataset | Versioned test cases an agent's answers are checked against; in Improve, the **Test questions** | `dataset` |
| Case | One question, and what a good answer is tested against; in Improve, a test question | `dataset_case` |
| Grading | How a dataset's answers are scored: checks, the reference answer and a judge | `scoring` |
| Criterion | One thing the judge grades every answer on, on a scale or as yes or no | `criteria[]` |
| Rule | A check an answer passes or fails with no model, such as a phrase, a pattern or a length; listed under **Checks** | `checks[]` |
| Judge | An agent that grades answers for evals; only the platform runs it | `kind: judge` |
| Grading model | The model new judges grade on, chosen once for the organization | `grading_model_profile_id` |
| Eval | An agent answering every case of a dataset, scored and compared with a version before it | `eval_run` |
| Confirmed regression | A case that passed before and fails again on every rerun; Improve says **Newly broken** | `flip: regression`, `confirmed: true` |
| Confirmed fix | A case that failed before and passes again on every rerun; Improve says **Newly fixed** | `flip: fixed`, `confirmed: true` |
| Unconfirmed | A case that changed once but not the same way on a rerun, so it counts as neither; Improve shows it under **Not confirmed yet** | `confirmed: false` |
| Noise | Answers graded differently when asked again with nothing changed; a result it could explain is within noise, and **Ask each question twice** measures it | `measurement_noise`, `purpose: stability` |
| Review | Scores waiting for a person to confirm or overrule them | `review_state` |
| Case generator | The system agent that drafts cases from an agent, its knowledge, real chats and red teaming | `kind: generator` |
| Proposed case | A drafted case waiting under **Generated** until a person accepts or dismisses it | `case_proposal` |
| Red teaming | Cases checking that an agent refuses what it must | `red-team` tag |

## How it is improved

| In the console | What it is | In the API and spec |
|---|---|---|
| Improve | A session that reads what went wrong with an agent, writes changes and tests them, waiting for a person between steps; it never publishes by itself | `improvement` |
| Understand | The first step: sorts the answers with feedback into what the agent can fix and what is missing from the knowledge base | `stage: analyzing`, `stage: classifying` |
| Changes | The step where the helper writes an attempt's changes and you choose which to test | `stage: proposing`, `stage: filtering` |
| Check | The step where today's version and the changed one answer the same questions and both are graded; **Open the full check** opens its eval run | `stage: evaluating`, `stage: judging` |
| Result | What the session came to: which attempt made the agent better, or that none did, and what can be done next | `status: ready`, `status: stopped` |
| Accept | The last step: **Publish version N** or **Keep as draft**, either of which ends the session | `POST /{run_id}/finish` |
| Attempt | One try within a session: changes written, then checked on questions of its own; at most three a session | `improvement_iteration` |
| Helper that writes the changes | The agent that reads the feedback and writes each attempt's changes; the authoring assistant unless another is chosen | `improver_agent_id` |
| Kept aside | Test questions an attempt keeps from the helper, so that only they decide its result | `improvement_partition: holdout` |
| Help write the changes | Test questions the helper reads while it writes an attempt's changes; they never decide its result | `improvement_partition: train` |
| Try again | Starts another attempt from the result, with an optional **Note for the helper**; it writes new changes and stops at **Changes** | `/{run_id}/continue` with `note` |
| Spending limit | What one session may spend in all, analysis and every attempt included; each step is priced before it starts | `budget_usd` |
| Automatic check | **Check these questions automatically on every change**: on accepting, a suite that asks the session's questions before each publish and allows no confirmed regression | `automatic_check` |
| Improve a skill | A session that improves one line of a skill, main or a fork, and checks the change on every agent of that line | `/skills/{id}/improvements` |
| Skill check | A skill change run on every agent of its line; better when no agent has a confirmed regression and at least one is better | `skill_check` |
| Unknown | An agent a skill check could not run, named with the reason; the person acknowledges it before applying | `state: unknown` |

## Capabilities

The name the Builder shows, and the id an agent's spec binds. Each is described
in [Capabilities](capabilities.md).

| In the console | In the spec |
|---|---|
| Apps | `artifacts` |
| Ask the user | `ask_user` |
| Request a secret | `secret_request` |
| Drafts | `drafts` |
| Web browser | `browser_use` |
| Chat channel lookup | `channel_tools` |
| Telephone calls | `phone_calls` |
| Charts | `charts` |
| Date and time | `clock` |
| Calculations | `code_execution` |
| Coding agent | `coding_agent` |
| Long conversations | `compaction` |
| Computer use | `computer_use` |
| Council | `council` |
| Context | `context` |
| Past conversations | `conversation_search` |
| Follow-ups | `follow_ups` |
| Guardrails | `guardrails` |
| Harness | `harness` |
| Image generation | `image_generation` |
| Knowledge search | `knowledge` |
| Media offload | `media` |
| Memory | `memory_files` |
| Mirage (virtual terminal) | `mirage` |
| Planning | `planning` |
| Work while tools run | `background_tools` |
| Background topics | `background_tasks` |
| Agent messages | `agent_messages` |
| Watch a command | `monitor` |
| Babysit PR | `babysit_pr` |
| Proof scenario | `proof_scenario` |
| Sandbox | `sandbox` |
| Skills | `skills` |
| Sol-loop | `sol_loop` |
| Eval tool tuning | `eval_tool_tuning` |
| Burst | `burst` |
| Subagents | `subagents` |
| Instruction reminders | `system_reminders` |
| Text to speech | `text_to_speech` |
| Thinking | `thinking` |
| Tool output limits | `tool_output_limits` |
| Tool search | `tool_search` |
| Video generation | `video_generation` |
| Visuals | `visuals` |
| Read web pages | `web_fetch` |
| Web search | `web_research` |
| Tables | AgenticOS MCP: `list_virtual_tables`, `query_virtual_table` |
| Workflows | `workflows` |
