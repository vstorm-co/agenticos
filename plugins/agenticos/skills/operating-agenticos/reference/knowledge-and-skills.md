# Knowledge bases, context files and skills

Three ways to give agents what they need to know. Tools are written `agenticos:<tool>`; match on the tool name whatever the server is called.

## Contents

- Which one
- Knowledge bases
- Context files
- Skills
- Skill versions and forks
- Improving a skill

## Which one

| Content | Put it in |
|---|---|
| Many documents an agent searches and cites | a knowledge base |
| Short standing facts every run needs: a glossary, a policy, a brand voice | a context file |
| A procedure an agent follows when a task calls for it | a skill |
| A credential | the vault, in the console. Never any of these |

## Knowledge bases

1. `agenticos:list_knowledge_bases` returns each base with its `collection_name` and embedding configuration.
2. `agenticos:search_knowledge` takes the `collection_name`, not the ID.

Creating one needs an embedding provider, because there is no deployment-wide default:

1. `agenticos:list_embedding_models` for providers and models. A `keyless` provider needs an `embedding_endpoint_id`; the others need an `embedding_secret_id`.
2. Copy the configuration from an existing organization knowledge base when there is one. Do not reuse a personal base's secret: it may belong to another organization.
3. `agenticos:create_knowledge_base`. No tool lists vault secrets or embedding endpoints, so with no knowledge base to copy from, stop and ask the user for the ID of an embedding key or endpoint an administrator added in the console. Do not pass a model profile's `secret_id`.

`agenticos:add_document` adds text. The `filename` extension decides the format (`.md`, `.txt`), and indexing runs in the background, so a search straight after may not find it yet. Search again before reporting the document as loaded.

When seeding from a repository, add one document per source file with its path in the filename, so citations point somewhere useful. Tell the user first how many documents will be added: documents cannot be removed over MCP.

Bind a base to an agent with `collection_ids` and the `knowledge` capability.

## Context files

1. `agenticos:list_context_files`, then `agenticos:get_context_file` for the body and mode.
2. `agenticos:create_context_file` with a focused body, an audience and a mode.
3. Bind it with `context_ids` on the agent draft. Saving a file attaches it to nothing.

- `inject` puts the file in every run's prompt: keep it short. `link` makes it readable on demand.
- Naming `group_ids` or `user_ids` makes the file private to them.
- `agenticos:update_context_file` reaches every bound agent on its next run, with no publish. Changing which files an agent binds does need a publish.

## Skills

A skill is instructions for a future agent, not a record of one conversation: when to use it, the steps, what to check and what to hand back.

1. `agenticos:list_skills` (`q` to search) finds an existing one. `agenticos:get_skill` reads its body, files, forks and the version each agent reads.
2. `agenticos:create_skill` with a lowercase hyphenated `name`, a one-line `description` an agent reads before loading it, and the Markdown `content`. The new skill is visible to the whole organization; tell the user.
3. `agenticos:add_skill_resource` attaches a text reference, template or script. Reference its exact name from the body. A script is stored as text; adding it runs nothing.
4. Bind with `skill_ids` on the agent draft, then publish the agent.

`agenticos:update_skill` retains omitted fields and changes the shared copy that every agent on that line reads. Read the skill first, and do not overwrite an organization's own procedure with a generic one. A skill grants no tools and no permissions.

## Skill versions and forks

Every saved change is an immutable version. An agent reads a skill in one of three states:

| State | Meaning |
|---|---|
| `main` | Follows the newest main version |
| `pinned` | Stays on one main version |
| `fork` | Follows a named fork with its own changes |

- `agenticos:list_skill_versions` and `agenticos:get_skill_version` read history.
- `agenticos:list_skills_behind_main` lists pinned agents and forks that main has moved past. Nothing catches up by itself, because each catch-up costs a check.
- `agenticos:change_skill_version` moves one agent, only when the user asked. Read `agenticos:get_skill` first: if the target version was never checked on that agent, say it is unknown and continue only once the user confirms.
- A pinned agent catches up with `agenticos:estimate_skill_update_check` → `agenticos:start_skill_update_check` → `agenticos:get_skill_check` → `agenticos:change_skill_version` to `main` with that `check_id`.
- A fork catches up with `agenticos:estimate_skill_catch_up` → `agenticos:start_skill_catch_up`, or returns with `agenticos:return_skill_fork_to_main` when it has no changes of its own.
- Agents the caller cannot see appear only as `hidden_agents`. Never guess who they are.

## Improving a skill

A skill session proposes changes and checks them on every agent of the line before anything is applied. It needs an OAuth connection and runs only when the user asks.

1. `agenticos:estimate_skill_improvement`. Tell the user `total_usd`, `per_round_usd` and `limit_usd`. An estimate with `reason: "no_evidence"` means there is nothing to improve from: evidence is runs that used the skill and were rated down, failed or were rated up, and an unrated run that succeeded does not count. Say so instead of starting.
2. `agenticos:start_skill_improvement` with the agreed `budget_usd`.
3. `agenticos:get_skill_improvement`. Reply from its `summary`, keeping every fact, a worse agent above all, and end with its `ask` exactly as given.
4. `agenticos:estimate_next_skill_improvement_step`, then `agenticos:run_next_skill_improvement_step` with its `total_usd` and `candidate_hash`. A failed step is rerun with `agenticos:retry_skill_improvement_step`.
5. `agenticos:accept_skill_improvement` with the outcome the user chose from the session's `next_actions`, saying which agents each choice moves. Or `agenticos:end_skill_improvement` to leave the skill unchanged.

Set `acknowledge_unknown` only after the user accepted the agents that could not be checked.
