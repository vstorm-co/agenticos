# Agents

An agent is a versioned spec. A draft is edited freely; the published version keeps answering on every surface until the next publish. Tools are written `agenticos:<tool>`; match on the tool name whatever the server is called.

## Contents

- Design before drafting
- Draft
- Capabilities
- MCP server bindings
- Sandboxes
- Test
- Publish
- Run a published agent
- Improve sessions

## Design before drafting

Settle the deliverable, who uses it, its authoritative sources, which effects it may cause and what shows the job is done. Check `agenticos:list_agents` for an agent that already owns the job.

Write instructions as a working contract: role, source precedence, decision policy, failure handling and completion criteria. Keep stable facts in a context file, reusable methods in a skill and documents in a knowledge base.

## Draft

1. `agenticos:list_models` returns the model profiles. A draft needs a `model_profile_id` before it can be tested. A profile with `missing_key: true` cannot run.
2. `agenticos:create_agent_draft` with `name`, `instructions` and the bindings. `ask_user` and `drafts` are always included.
3. `agenticos:get_agent` returns `draft_spec`, `draft_revision` and the published `current_version_id`. Published `starters` are top-level; a draft's are in `draft_spec.starters`.

`agenticos:get_agent` does not return the published spec, and its summary fields (`published_capabilities`, `published_model`, `channels`) can be empty where `agenticos:list_agents` fills them. A publish ships every pending draft edit, not only the one just made: before editing a published agent, tell the user the draft may already differ from what is live.

`agenticos:update_agent_draft` changes only what is passed, with these whole-value replacements:

| Field | Behaviour |
|---|---|
| `instructions` | Replaces the whole prompt. Read it, edit it, send it all. |
| `add_capabilities` | A string leaves existing settings alone. An object upserts its fields; a supplied `config` replaces the whole config. |
| `remove_capabilities` | Switches the named capabilities off. |
| `mcp_servers` | Replaces the whole binding list. `[]` disconnects all. |
| `skill_ids`, `collection_ids`, `context_ids`, `starters` | Each replaces its whole list. |

`agenticos:discard_agent_draft` deletes a draft the caller created that was never published. It is the undo for a mistake, not a way to retire an agent.

## Capabilities

`agenticos:list_capabilities` returns summaries; search with `q` and follow `next_skip`. Before configuring one, read `agenticos:get_capability` for its `config_schema`, tools and `requires_secret`.

- A capability with `requires_secret` needs a `secret_id` that exists in the organization's vault. The user creates the secret in the console.
- `approval` gates every tool of the capability; `tool_approval` overrides it per tool ID.
- `tool_overrides` renames or redescribes one tool for this agent. The description the model reads steers it more than the instructions do.

Start with the capabilities the job requires. Each extra tool costs context on every run.

## MCP server bindings

`mcp_servers` takes three kinds of entry, told apart by `account`.

| `account` | Identified by | Whose credentials | Found with |
|---|---|---|---|
| `organization` | `connection_id` | The organization's, on every surface | `agenticos:list_org_connections` |
| `personal` | `catalog_key` | Each person's own, resolved when they talk to the agent | `agenticos:search_mcp_servers` |
| `platform` | nothing else | Whoever the agent runs for, on this same MCP server | built in |

- Never put a personal connection ID in a spec. Personal bindings name the catalog key.
- Personal and platform bindings are absent where nobody is asking: an API key, a public widget, a schedule acting for nobody.
- Narrow with `allowed_tools`. Inspect names with `agenticos:list_mcp_connection_tools` and one contract with `agenticos:get_mcp_connection_tool`. Both read the last recorded catalog, not live health.
- Set `approval: "writes"` or `"all"` for servers the organization does not control. `writes` trusts the server's own read-only hints.
- A service with no connection yet is connected by a person in the console at `/mcp-servers?connect=<key>`.

## Sandboxes

For an agent that runs code:

1. `agenticos:list_sandbox_connections` for active hosts.
2. `agenticos:get_sandbox_policy` for the runtimes and limits that host allows. `agenticos:list_sandbox_runtimes` is the static catalog.
3. Bind `{id: "sandbox", config: {backend: "service", include_execute: true, connection_id: "<id>"}}`.

A `state` backend stores files only and cannot execute commands.

## Test

`agenticos:test_agent_draft` sends one message to the unpublished draft. The run is budgeted, recorded and marked as a test.

- A refusal names what would block publishing: no model, a capability missing its key.
- `status: "awaiting_answer"` with `questions` means the agent asked the person something. Call `agenticos:answer_agent_questions` with that `run_id`, keyed by `tool_call_id`, using the user's real answers or explicit test fixtures. Never invent a person's reply.
- Pass `conversation_id` to continue the same test thread.

Test an ordinary request, a request the sources cannot answer, a refused access and a document that tries to give instructions. A test may call real services through the agent's tools; keep its effects within what the user authorized.

## Publish

`agenticos:publish_agent` runs the console's publish checks and makes the draft live on every surface at once. A refusal says what to fix. Pass a `note` saying why the version exists. Publish only when the user asked; then read the agent back and report the new `current_version_id`.

## Run a published agent

`agenticos:run_agent` asks a published agent and waits for the answer. The result carries `run_id` and cost. Pass `conversation_id` to continue a thread. A run may pause on a question exactly as a test does.

## Improve sessions

An Improve session measures an agent on a dataset of test questions, proposes changes, tests them and waits for a decision. It changes nothing in the agent until accepted. These tools need an OAuth connection, and an agent has one open session at a time.

Copy this checklist and track progress:

```
Improve progress:
- [ ] 1. list_datasets: pick a dataset with can_run true (none: stop, the user creates one in the console)
- [ ] 2. estimate_improvement: tell the user total_usd, per_round_usd and limit_usd
- [ ] 3. start_improvement with the agreed budget_usd
- [ ] 4. get_improvement: reply from summary, offer its next_actions
- [ ] 5. estimate_next_improvement_step, then run_next_improvement_step
- [ ] 6. Repeat 4 and 5 until the session reaches its result
- [ ] 7. accept_improvement (draft or publish) or end_improvement
```

- Start a session, run a step, try again and accept only when the user asked for that step.
- Build each reply from the session's `summary` and keep every fact in it, warnings above all. Offer exactly its `next_actions`.
- The step that spends takes `budget_usd` (the session's limit), the estimate's `total_usd` as `estimate_usd`, and its `candidate_hash`. A session that changed since the estimate is refused: estimate again.
- Compare attempts by their `change` on held-out questions, not by pass rates in `details`. When `measurement_noise.noisy` is true, the test cannot tell better from worse; say so.
- `agenticos:use_attempt` picks a finished attempt; `agenticos:estimate_improve_again` and `agenticos:improve_again` start another, with the user's `note`.
- `agenticos:accept_improvement` with `publish: false` unless the user asked to publish. Link the user to the session's `link` for the full wizard.
