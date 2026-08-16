# The capability catalog

Everything an agent can *do* comes from one of two places: a capability
registered in this deployment's code, or an [MCP server](../mcp.md) somebody
connected. This page is the first list.

A capability is the unit worth switching on or off — one line in the Builder, one
entry in the spec. It is deliberately not "a tool": knowledge search is a single
decision for the person configuring an agent, and whether it exposes one function
today and three next month is not their problem. Capabilities also cover things
that are not tools at all, which is why `thinking` and `clock` are here with no
tools listed.

!!! note "The API is authoritative, this page is a snapshot"

    `GET /api/v1/agents/capabilities` serves the registry as it is in the running
    deployment, including anything added since this page was written. The Builder
    renders its picker and its configuration forms from that response. If the two
    disagree, the API is right.

## What ships

| id | Name | Category | Tools | Scope | Key |
|---|---|---|---|---|---|
| `knowledge` | Knowledge search | knowledge | `search_documents` | `knowledge:read` | — |
| `skills` | Skills | knowledge | `list_skills`, `load_skill`, `read_skill_resource` | `knowledge:read` | — |
| `context` | Context | knowledge | `list_context`, `read_context` | — | — |
| `web_research` | Web search | research | `web_search` | `web:read` | for paid services |
| `code_execution` | Run Python | analysis | `run_python` | `code:execute` | — |
| `sandbox` | Files & shell | analysis | `ls`, `read_file`, `glob`, `grep`, `write_file`, `edit_file`, `execute` | `sandbox:execute` | for Daytona |
| `charts` | Charts | analysis | `create_chart` | — | — |
| `image_generation` | Image generation | analysis | `generate_image` | — | required |
| `subagents` | Delegation | reasoning | `task`, `check_task`, `wait_tasks`, `list_active_tasks`, `answer_subagent`, `send_message_to_subagent`, `soft_cancel_task`, `hard_cancel_task`, `create_agent`, `delegate` | `agents:delegate` | — |
| `planning` | Planning | reasoning | `write_plan`, `read_plan`, `add_task`, `update_task_status`, `update_task_statuses`, `remove_task`, `add_subtask`, `set_dependency`, `get_available_tasks` | — | — |
| `thinking` | Thinking | reasoning | none, by design | — | — |
| `system_reminders` | System reminders | reasoning | none, by design | — | — |
| `tool_search` | Tool search | utility | none, by design | — | — |
| `clock` | Date and time | utility | none, by design | — | — |
| `guardrails` | Guardrails | utility | none, by design | — | — |
| `compaction` | Context management | utility | none, by design | — | — |
| `channel_tools` | Chat channel lookup | channels | `get_channel_info`, `list_channel_members`, `search_channels`, `read_channel_history` | — | — |

Six of those have no tools on purpose. `thinking` changes how the model runs
rather than what it can reach, `clock` puts the date in the instructions,
`tool_search` contributes its search function only once it wraps a toolset that
has deferred tools — in isolation it declares nothing — `guardrails` inspects and
rewrites the text flowing through a run, `compaction` rewrites the history a
request carries, and `system_reminders` appends steering text to the request tail.
None of the six leaves anything for a person to approve, so none
declares a tool. A capability with genuinely no
tools says so with `tools=()` rather than omitting the argument; see
[Add a capability](../howto/add-capability.md).

**This column is what a capability declares, which is not always what a model is
offered.** Delegation is the one place the two differ: `create_agent` and `delegate`
appear only under `allow_dynamic`, and `answer_subagent` appears to nobody at all —
both explained under [Delegation](#delegation) below.

**One of them is not in the Toolbox at all.** `channel_tools` is chosen per bound
bot under *Where this agent is available*, and publishing refuses a spec that
tries to carry it — see [Chat channel lookup](#chat-channel-lookup).

## Knowledge search

`search_documents` — *Search the organization's documents for passages relevant to
a question.*

Searches the collections the agent's spec binds and cites what it used. The model
asks *what* to search, never *where*: collections are resolved from the spec
before the run and handed to the capability, so an agent cannot reach a collection
nobody connected to it.

| Config | Default | Range |
|---|---|---|
| `default_top_k` | 5 | 1–50 |

`default_top_k` applies only when the model does not ask for a number itself.

Bound with no collections, this capability contributes **nothing** — it is not
attached at all. A search tool that always returns empty is worse than no search
tool, because the model keeps trying it and reasons from the silence.

## Skills

`list_skills`, `load_skill`, `read_skill_resource`

Written know-how the agent loads only when it decides it is relevant, one skill at
a time — the alternative being an instructions field that grows until every run
pays for every procedure. See [Skills](../skills.md) for what a skill is and how
one gets into an organization.

These three tools come from `pydantic-ai-skills`, so their names and wording are
somebody else's to change. A drift test compares what the registry declares
against the tools the model is actually offered, which is what reports the day
that happens.

## Context

`list_context`, `read_context`

An organization's standing context put into the run instead of made to be asked
for — a glossary, a brand voice, an escalation matrix. Each bound file carries a
`mode`: an `inject` file is spliced into the instructions verbatim, so the model
simply knows it; a `link` file is left out of the prompt and reached through
`read_context`, so a large or rarely-needed file costs nothing until the model
decides it is relevant. `list_context` reports what is available without the
bodies. The two tools appear only when a `link`-mode file is bound; an
agent whose files are all `inject` contributes instructions and no tools.

Injected content is framed as reference material — delimited and prefaced with a
line telling the model to treat it as information, not as instructions — because
a file's body is written by a person and reaches the model verbatim. The fence is
best-effort against *accidental* breakout: a body that itself contains a closing
`</context-file>` or `</context-files>` tag, or a name or format holding a `"`,
is neutralised so it cannot spill text back into the trusted instructions. It is
not a security boundary — a `context:edit` holder can still inject deliberately.
Content is text: a document to be searched belongs in a knowledge collection, not
here.

Bound with nothing usable — no files, or only `link` files with the read tool
turned off — this capability contributes **nothing** and is not attached, the
same way `knowledge` bound to no collections is not. Files are managed under
`/api/v1/context` and bound to an agent by id (`AgentSpec.context_ids`).

## Web search

`web_search` — *Search the public web for current information.*

| Config | Default | Values |
|---|---|---|
| `method` | `duckduckgo` | `duckduckgo`, `native`, `tavily`, `brave`, `exa` |
| `max_results` | 5 | 1–10, ignored by `native` |

- **`duckduckgo`** — free, no account, results rendered as clickable sources.
- **`native`** — the model provider searches with its own index and returns its
  own citations. Only on models that support it.
- **`tavily`** — results summarised for a model to read.
- **`brave`** — an index of its own.
- **`exa`** — search by meaning rather than by keyword.

The three paid methods need an API key from the organization's
[secrets](../secrets.md), named by the binding's `secret_id`. The requirement is
conditional rather than flat: a flat one would either lock the free default behind
an account, or let a Tavily agent publish with nothing to authenticate with and
fail on its first search.

## Run Python

`run_python` — *Run a small Python program to compute something.*

A restricted sandbox with no network and no filesystem, which is why time and
memory are the only limits worth setting.

| Config | Default | Range |
|---|---|---|
| `timeout_secs` | 10 | > 0, ≤ 120 |
| `max_memory_mb` | 256 | 16–4096 |

Capped rather than open-ended, and per agent rather than per deployment: an author
raising a limit for one data-heavy agent should not need an operator or a
redeploy.

## Files & shell

`ls`, `read_file`, `glob`, `grep` — *reading.*
`write_file`, `edit_file`, `execute` — *writing and running.*

A workspace that survives between turns. `code_execution` computes and forgets;
this remembers, and on a container-backed backend it has a real shell. An agent
granted both computes with one and keeps its work in the other — which is the
normal pairing on the `state` backend, because that one has no shell at all.

| Config | Default | Values |
|---|---|---|
| `backend` | `state` | `state`, `service` |
| `connection_id` | null | a registered sandbox connection; null takes the organization's default. `service` only |
| `session_scope` | `conversation` | `run`, `conversation`, `channel`, `user`, `agent` |
| `runtime` | null | an alias that connection's service allows; `service` only |
| `include_execute` | `true` | removes the shell entirely when off, rather than gating it |

There is no `docker` or `daytona` backend to choose. *Where* a sandbox runs is a
property of the connection an operator registered — Sandboxes in the app — so
naming the connection is naming the kind. Choosing them separately made it
possible to choose two things that disagree.

**`backend` is infrastructure; `session_scope` is a data-sharing policy.** Getting
the first wrong costs a feature. Getting the second wrong shows one person
another person's files, so it is worth reading twice:

| Scope | Who shares the workspace |
|---|---|
| `run` | Nobody — a fresh one every turn |
| `conversation` | Everyone in that chat. On Slack a thread *is* a chat, so threads do not share |
| `channel` | Every thread in one channel. A direct message has its own chat id, so people still get their own |
| `user` | One person, across every surface they reach this agent on |
| `agent` | **Everyone who talks to this agent**, across the organization |

`conversation` and `channel` exist as separate answers because a chat platform
makes them different things. `SlackAdapter` folds `thread_ts` into the chat id, so
`conversation` on Slack means one workspace per thread — fifty threads in a busy
channel is fifty containers and a `429` for the fifty-first person to reply.

The scope in the spec is the **default**. Each channel the agent is published to
can override it, on the exposure: an agent reached in web chat and on a Slack bot
is one agent in two situations, and one value for both was the wrong shape.
`user` scope is what carries a workspace across surfaces — the same person picking
up in Slack a conversation they started in web chat finds their files there.

`agent` is the one that crosses a boundary between people. The Builder warns at
the field, the file panel labels whose workspace it is rather than calling it "this
conversation's files", and setting it is recorded in the audit log — because a user
who sees a file they did not create should be able to find out why.

**Changing the backend or the connection starts a fresh workspace rather than
reattaching to the old one.** A stored document, a container's volume and a
Daytona sandbox are three different things, and two `sandboxd` installations are
two different things — so each gets its own workspace, and the previous one stays
where it is, still listed and still readable. Moving a live agent is therefore not
a way to carry its files across; the agent finds an empty workspace on the new
host. Since `connection_id: null` means "the organization's default", marking a
different connection as default has the same effect without any spec changing.

A spec chooses a connection and never an image, a mount, a network mode or a
ceiling. Those belong to whoever runs the deployment: a spec is authored in a
browser by anyone holding `edit` on the agent, and one that could name a container
image could name one whose entrypoint mounts the host. `runtime` is an alias, and
the Builder offers only the aliases that connection's service reports — read live,
because a stored copy would offer one the service has since stopped allowing.

What each backend costs to run:

| Backend | Needs | Shell | Where files live |
|---|---|---|---|
| `state` | nothing | no | this database, capped at `SANDBOX_STATE_MAX_BYTES` |
| `service` | a registered connection | yes | a container on that host, or Daytona's cloud on the organization's own account |

An operator can see what is running: Sandboxes lists this organization's open
sandboxes on its default host with their runtimes, idle times and memory, and the
activity log per sandbox. See [Configuration](../configuration.md#agent-workspaces).

Publishing is refused for a `service` workspace when the organization has
registered no connection, when the one it names is gone, or when that connection
has no credential — each by name, because all three are states a deployment
reaches *after* an agent was published and the fix is an operator's rather than the
author's.

**Only `execute` asks.** Side-effecting is declared per tool, and of the seven only
running a command is: a workspace is scratch space deleted with the conversation it
belongs to, so writing a file in it is not the class of act sending an email is —
and an agent that has to ask before every `write_file` cannot do multi-step work at
all, which is how an author ends up turning the gate off entirely and losing the one
that mattered. `execute` runs arbitrary commands on somebody's host.

A binding that wants the stricter behaviour sets it per tool:
`tool_approval: {"write_file": "required"}`. See [Governance](../governance.md) for
how an approval is put to a person.

**Some paths are refused whatever the approval policy says.** Credentials
(`**/.env`, `**/*.pem`, `**/*.key`, `**/credentials*`, `**/.ssh/**`, `**/.aws/**`)
and the system tree (`/etc/**`, `/usr/**`, `/proc/**` and their siblings) cannot be
read, written or edited — the agent gets a readable refusal and can carry on. `grep`
is filtered rather than refused, since a pattern over `/` legitimately covers the
workspace: matches inside an off-limits file are dropped, so a search cannot return
a line from one. Names are not secret, so `ls` and `glob` still show what is there;
only the contents are withheld.

A command that *names* one of those paths is refused too, so `cat /etc/shadow`
does not get round the rule by asking a different tool. That is defence in depth
and not a boundary, and the difference matters: a shell reaches a file in ways
string inspection cannot see, so what actually makes execution safe is the
container's isolation and the operator's network mode. There is no allowlist of
command strings, because one is defeated by `sh -c`.

And none of it is a substitute for the approval gate: refusal here is the code's
flat no, while `execute` asking a person is the decision an operator owns.

Files somebody attaches to a message land in `/uploads` — see
[File processing](../file-processing.md).

**Skills become files too.** An agent with both a workspace and skills gets each
skill as `/skills/<name>/SKILL.md` with its resources beside it, which is what
makes a skill's script runnable at all: it is on disk next to the shell that can
run it. There is deliberately no `run_skill_script` — `execute` already has the
approval gate and the operator's ceilings behind it, and a second execution path
would be a second set of rules to get wrong.

Those files are writable, and what the agent writes does **not** become a skill. A
skill is instructions every agent bound to it follows on every run, so a change is
recorded as a proposal and somebody holding `skills:edit` accepts or discards it —
see [Skills](../skills.md).

## Charts

`create_chart` — *Draw a chart of numbers you already have, so the user can see
them.*

Renders numbers the model already has. It does not fetch, compute or aggregate —
pair it with `code_execution` or `knowledge` for that. No configuration.

The numbers arrive as columns — one `x_values` list for the axis, one `values`
list per series — because a free-form `data` argument is not something a JSON
Schema can describe, and a model given an array of objects with no declared
properties sent back a single empty one. A chart with nothing in it is now
unexpressible rather than merely refused; an axis with no points, a chart with no
series, or a series holding fewer numbers than the axis has points all come back
as a retry naming what is missing. A frame drawn around no data reads as "there
is no trend" rather than as a mistake, and it is persisted and re-rendered on
every replay of the conversation.

## Image generation

`generate_image` — *Generate an image from a written description.*

Draws an image with a dedicated image model — separate from the agent's own — so
it works whatever model the agent runs on. `create_chart` plots numbers; this
draws pictures.

| Config | Default | Values |
|---|---|---|
| `model` | `openai-responses:gpt-5.4` | `openai-responses:gpt-5.4`, `google:gemini-3-pro-image` |
| `quality` | provider default | `low`, `medium`, `high`, `auto` |
| `size` | provider default | `auto`, `1024x1024`, `1024x1536`, `1536x1024`, `512`, `1K`, `2K`, `4K` |
| `background` | provider default | `transparent`, `opaque`, `auto` |
| `output_format` | provider default | `png`, `webp`, `jpeg` |
| `aspect_ratio` | provider default | `16:9`, `1:1`, `9:16`, … |

`model` also decides which provider the API key belongs to. The key is required —
publishing an agent that binds this without one is refused — and comes from the
organization's [secrets](../secrets.md), named by the binding's `secret_id`. Every
other setting is optional; unset, the provider applies its own default, so turning
the capability on is enough to generate.

**It is side-effecting.** Drawing an image spends real money on a provider key and
produces content a person may publish, so every call is a candidate for the
[approval gate](../governance.md) and can be gated per binding.

**Its spend is metered.** The image model is run as a subagent whose usage is
booked to the run's ledger, so image cost counts against a budget the same as a
model request. Image models are often unpriced by the pricing snapshot, in which
case the run records the call at zero and flags its total as partial (`cost_is_partial`)
rather than hiding the spend.

**Where the image goes.** Every generated image is stored **per organization** and
served back by [`GET /api/v1/generated/{filename}`](../architecture.md), scoped to
the caller's own organization — a wider boundary than a chat upload, which is owned
by one user, because there is no record of who produced an image. When the agent
also has a workspace (the `sandbox` capability), the same image is written into it
under `/output`, so a later `execute` step can build with it — assemble a PDF, a
slide, a page. An agent without a workspace still generates and shows images; it
simply has nowhere to build with them.

## Delegation

`task` — *hand a self-contained piece of work to one of this agent's specialists.*
`check_task`, `wait_tasks`, `list_active_tasks` — *following one that is running.*
`send_message_to_subagent`, `soft_cancel_task`, `hard_cancel_task` — *steering or
stopping one.* These six are offered only when a background delegation is reachable
— a `sync`-only agent is handed none of them.
`create_agent`, `delegate` — *a specialist the model writes for itself, when the author allows it.*
`answer_subagent` — *declared, and offered to no model.*

One agent handing part of a job to another, each on its own model with its own
knowledge and its own step limit, addressed by name. There are two shapes of
delegate and the difference decides how it is reviewed, versioned and billed —
[Concepts](../concepts.md#delegate-vs-inline-specialist) is where that is
explained. Which *published* agents this one may delegate to is not in this
config: it is `subagents` at the top level of the spec, where publish validation,
the YAML export and the permission model can all see it.

| Config | Default | Range |
|---|---|---|
| `inline` | none | specialists defined inside this agent |
| `mode` | `sync` | `sync`, `async`, `auto` |
| `allow_questions` | `false` | a sync delegate may ask the parent's person |
| `allow_dynamic` | `false` | |
| `max_depth` | 1 | 1–3 |
| `max_fanout` | 3 | 1–10 |
| `max_result_chars` | 2000 | 200–20000 |
| `share_with_delegates` | none | capability ids this agent is itself bound to, except `subagents` |

**The mode is the author's decision, not the model's.** The library's `task` tool
takes a `mode` argument defaulting to `sync`, so "the model chose to wait" and
"the model said nothing" are the same call — there is no way to honour both a
setting and a choice, and the setting was reviewed. So the argument is replaced on
the way through, and `auto` is how an author deliberately hands the decision over.
`auto` is resolved *before* the delegation starts, because whether a panel stays
open after the parent has answered depends on the answer. A pinned delegate or a
specialist may override the mode for itself: one slow researcher is the case worth
running in the background. The instructions **mark that delegate**, beside its
name — a single sentence stating the configured mode was a promise the overriding
delegate then broke, telling the model to expect an answer and handing it a task
id.

**A `sync`-only agent is offered none of the six task-lifecycle tools.** Each of
`check_task`, `wait_tasks`, `list_active_tasks`, `send_message_to_subagent` and the
two cancels takes or reports on a task id, and a `sync` delegation returns the
answer and nothing else — there is no id to pass. So they are offered only when a
background delegation is reachable: `async` or `auto` mode, a delegate that prefers
either, or permission to invent specialists. `sync` is the default, so this is the
common configuration, and six tool descriptions withheld is six the model no longer
pays for on every turn. `task` stays — a `sync` agent still delegates.

**Fan-out and nesting are ceilings, not errors.** Past `max_fanout` the next
delegation comes back as a tool result the model can act on — wait, or do the work
itself — because a pacing limit should not end a run. `max_depth` counts levels of
delegation **including the configured agent's own**: 1 is this agent delegating and
its delegates not, 2 allows one nested level. At the bound a delegate is built
*without* the delegation capability rather than with one that can only refuse - a
tool that always answers "no delegates available" is a description the model pays
for on every turn and tries anyway. There is deliberately no 0: turning delegation
off is disabling the binding, and a second spelling of the same switch is one that
disagrees with the first.

**And every agent in the tree is held to its own `max_depth`, not the root's.** A
delegate gets the *lower* of what the tree has left and what its own spec allows,
so a root configured for three levels delegating to an agent whose author chose 1
gets one: that delegate delegates and its delegates do not, exactly as its own
reviewers read it. A ceiling a caller could widen would not be one, and the reason
to pin a delegate to a version is that its author's decisions hold when somebody
else calls it.

**A sync delegation can stop to ask a person, and is continued in place.** A gated
tool inside one parks the whole run; approving it resumes that delegate from where
it stopped rather than delegating again, which is what makes the approval apply to
the call the reviewer actually saw. [Governance](../governance.md) has the shape of
the stored state and why re-running would answer differently.

**A background delegation cannot stop to ask a person.** A gated tool inside one
is refused rather than parked, and the refusal tells the model to delegate that
work with `mode="sync"` instead. The reason is not policy but lifetime: the
approval channel closes over the request's database session, and a background
delegation outlives the tool call that started it, so by the time it wanted to ask,
there is nothing left to write the question with. A background delegation that
suspends anyway — a shape the library documents as undeliverable — is recorded
`failed` with that same message, because the alternative is a task that reports
"still running" for as long as the process lives: its spend attributed to nothing,
its fan-out slot never released, and the panel a surface opened never closed.

**A sync delegate may ask the parent's person, when `allow_questions` is set.** Off
by default: a specialist works autonomously and says so if it could not. Set on, a
delegate whose mode is sync is given the library's `ask_parent` tool, and a question
it asks is answered by the run's own `ask_user` channel — the person already holding
the parent's tool call — never by the model. It is the author's decision because the
question wears a name the author published; a specialist the model *invents* never
asks, whatever this says, because instructions a model wrote a moment ago are not the
author's to put to a person. Only sync: a background delegation has handed back a
task id with nobody left to answer, and `auto` may become one. Reaching a pre-built
delegate needed an upstream change —
[subagents-pydantic-ai#76](https://github.com/vstorm-co/subagents-pydantic-ai/pull/76)
honours `can_ask_questions` for a caller-supplied agent, which every delegate here
is — landing the sync half of
[#184](https://github.com/vstorm-co/agenticos/issues/184).

**`answer_subagent` is offered to no model.** It answers a question a *background*
delegate parked on, and no delegate here parks on one: a sync question goes to a
person through `ask_user` and never this tool, and an async delegate is not given
`ask_parent` at all. So the tool's only possible answer is "that delegation is not
waiting for an answer". It stays *declared*, because a tool absent from the
declaration cannot be gated by the approval policy or renamed by a binding and that
half of the failure is silent; it is filtered out of the offered set, because the
other half is a description in every turn's context describing an action that cannot
happen, and tool descriptions are the strongest prompt in this product. The tool
becomes reachable only when the background half of
[#184](https://github.com/vstorm-co/agenticos/issues/184) is answered — where the
parent's own model answers while nothing obliges it to look, the delegate blocking
on a fan-out slot the turn's end cancels.

**`wait_tasks` truncates, and says so.** A completed task's result is cut at
`max_result_chars` with an explicit marker pointing at `check_task`, which always
returns the full text. The marker is the load-bearing half: a silent cut reads as a
short answer, and an orchestrator handed half a report re-delegates work it already
has.

**Switching delegation off is disabling the binding, not lowering a number.** A
disabled binding is not delegation: nothing is built, so nothing reads the pins or
the specialists it carries — and publishing is then refused for an agent that still
names delegates, because a pin nothing will ever call is configuration that reads
as a decision and does nothing.

**Bound with no delegates at all, this capability contributes nothing** — it is
not attached, the same way `knowledge` is not attached with no collections. Ten
tools that can only refuse are ten tools in every turn's context.

**Only the three that act ask for approval:** `send_message_to_subagent`,
`soft_cancel_task` and `hard_cancel_task`. Steering changes what a delegate is
doing mid-run, and either cancel destroys work that was paid for and not
delivered. `task` is deliberately not side-effecting, which reads wrong for a
moment: what a delegate *does* is gated by the delegate's own spec, through the
same approval gate this run uses, so gating the delegation as well would ask
somebody to approve it before the work that might need approving has been
proposed. An author who does want that has one `tool_approval` override.

**A delegate is not lent the parent's capabilities.** It runs on its own spec plus
whatever `share_with_delegates` names, one id at a time — a specialist that
silently gained the parent's credentials would be the quiet route around what the
parent was granted. Publishing refuses a shared id the parent is not itself bound
to, since lending what you do not hold is a line of configuration that reads as a
decision and does nothing. In practice this exists for `sandbox`: sharing it is
how a researcher writes `/workspace/notes.md` and a writer reads it. A delegate
that binds `sandbox` *without* being shared the parent's gets the in-memory
workspace, because only the run opens one.

**`subagents` cannot be shared**, and it is the one id "does the parent hold it"
could never refuse — an agent that shares anything holds it by definition. Shared,
the parent's binding lands on a delegate that binds none, and the runtime then
reads the *parent's* specialists, `allow_dynamic`, `max_fanout`, `max_depth` and
share list as though the delegate's author had chosen them. Publishing refuses it,
and the runtime drops it from the share list as well, so a spec stored before that
rule cannot widen a delegate either. Whether a delegate may delegate at all is its
own spec's answer, and so is how deep it may go — bounded by what the tree above it
has left.

Sharing is also the only route to an [MCP connection](../mcp.md) for an inline
specialist, which cannot bind one at all: a connection is organization-scoped
configuration, and reaching one through a specialist nobody published is the wrong
door. Bind it on the parent and name it here.

**`create_agent` and `delegate` are offered only under `allow_dynamic`.** A tool
absent from a capability's declaration cannot be gated by the approval policy or
renamed by a binding, and the dangerous half of that is silent — so all ten are
declared, and a default configuration offers seven.

What the switch buys is a specialist the model writes itself: instructions and a
model, and nothing else. It is built through the same `build_agent` an inline
specialist comes through, on the run's shared budget guard and its approval
channel, so its requests are priced and counted against the cap somebody set. That
is the entire reason this took a factory rather than a flag: a specialist the
library built for itself would sit outside this deployment's model catalog, its
vault and its budget guard — an unmetered request, possibly to a provider the
organization holds no key for. The factory is what routes it back through this
platform instead. (Before `subagents-pydantic-ai` 0.2.18 the library also carried a
default model string a modelless specialist was compiled from; 0.2.18 removed that
fallback, so a specialist naming no model is now refused rather than built — this
platform refuses it earlier still, in `DelegatingToolset._refuse_dynamic`.)

The model may name only a model the organization has a profile for, and the refusal
names the list. It may not attach capabilities: letting a model grant its own child
a capability is the ungranted-scope failure wearing a new hat. It gets no knowledge,
no delegates of its own, and nothing is persisted across runs — keeping a specialist
means publishing an agent, which is a person's action. `MAX_DYNAMIC_SPECIALISTS`
bounds how many one run may keep.

That a specialist is not persisted is a design, and it has an exit rather than a
dead end: a person can **promote** one to a draft agent. Its definition rides the
opening `SubagentStarted` frame — the one place it is legible after the model wrote
it and before the turn ends — so the chat delegation panel can offer to keep it
while the run is still on screen, and the Builder offers the same on an inline
specialist. Promotion creates a draft owned by whoever promoted it, gated on
`agents:edit`, and stops there: it does not publish, does not pin the new agent as a
delegate, and does not remove the specialist it came from. See
[Concepts](../concepts.md#delegate-vs-inline-specialist) for why the persistence rule
is the reason the exit exists rather than a limitation it works around.

A kept one lasts the whole run it was invented in, an approval park included: the
registration lives in a registry the delegation library builds per *built* agent,
and a run that parks is built again when it is continued, so it was lost across the
park until the registrations were carried in `PausedRunState` and re-registered on
the replay ([#175](https://github.com/vstorm-co/agenticos/issues/175)). It does not
survive into the *next conversation turn*, which is a fresh build with no paused
state — a name created in one reply is unknown in the next, and `create_agent`'s
description tells the model to create it again if `task` says so.

**The delegation library's own unspecialised delegate is not offered at all**, and
there is no setting for it. Before subagents-pydantic-ai 0.2.18 it would have run on
a model this deployment did not configure — compiled from the library's own default
model string, outside the organization's profiles, its vault and the run's budget
guard, exactly like the run-time specialist above before it took a factory. A
catch-all is a legitimate thing to want; write it as an inline specialist, where you
can read what it does and it is priced like everything else. The library's own is
fixed as of 0.2.18 ([#174](https://github.com/vstorm-co/agenticos/issues/174)): with
no default model or factory it now refuses to build the delegate rather than picking
a model.

What the model is told about all of this is written here rather than by the
library: the delegates by name and description, the mode this run will actually
use, and the fan-out ceiling it would otherwise discover by being refused. Two
lists of the same delegates in one system prompt is context paid for twice, and
only one of them can say what the deployment enforces.

For what a delegation costs and which run row records it, see
[Governance](../governance.md#delegation-spends-the-parents-budget). For who may
delegate to what, see [Permissions](../permissions.md#delegation-is-not-a-privilege-boundary).

## Planning

`write_plan` — *lay out or replace the whole checklist.*
`read_plan` — *see the steps and their ids before a granular edit.*
`add_task`, `update_task_status`, `update_task_statuses`, `remove_task` — *change one
step, or a batch, without replacing the plan.*
`add_subtask`, `set_dependency`, `get_available_tasks` — *dependency-aware planning,
offered only under `enable_subtasks`.*

A checklist the model keeps for itself while it works: what is done, what is in
progress, what is left. For multi-step work a model does better when it writes the
steps down first and keeps them in front of itself, so the current plan is surfaced
back every turn as a **cache-safe tail reminder** — appended after a cache breakpoint,
so the stable prompt prefix stays byte-identical and only the mutable plan is re-read
each turn. The plan never lands in the system prompt.

It overlaps with [Delegation](#delegation) the way a plan overlaps with a team:
planning decides *what* the steps are, delegation decides *who* does them. They are
orthogonal — a plan is a toolset plus a reminder, delegation is a toolset plus a run
wrapper — so an agent may bind both, one, or neither.

| Config | Default | Values |
|---|---|---|
| `enable_subtasks` | `false` | adds the three subtask/dependency tools and the `blocked` status |
| `cache_ttl` | `5m` | `5m`, `1h` — how long the prefix before the reminder may cache |

**None of the nine tools acts on the world.** Each mutates a checklist the model
keeps for itself, so there is nothing here for a person to approve and the capability
declares `side_effecting=False`. The three subtask tools are declared even when a flat
checklist does not offer them, because a tool absent from the declaration can be
neither gated by the approval policy nor renamed by a binding.

**The plan survives an approval park.** The checklist is state, and a run that parks
on an approval mid-plan resumes as a fresh run — so the store is owned by the runner,
not the capability: it is seeded from `paused_state` on resume and read back when the
run stops. An agent that does not bind the capability pays nothing — no tools, no
reminder, no stored plan.

**It spends no tokens of its own.** The tools are local checklist edits with no model
or embedding request behind them, so unlike knowledge or delegation there is no
ambient usage to meter. The round trips the model makes to call them are its own, and
the budget guard already counts those.

## Thinking

No tools. Asks the model to reason before it answers: slower and dearer, better on
work that needs several steps held in mind at once.

| Config | Default | Values |
|---|---|---|
| `effort` | unset | `minimal`, `low`, `medium`, `high`, `xhigh` |

Unset means the provider's own default effort. A level a provider does not have
maps to its closest one, so a spec stays portable across a model swap.

## System reminders

No tools. Re-states steering guidance mid-run so a long session stops drifting
from its instructions — the failure this fixes is instruction fade, where after
many tool-use turns a model progressively ignores the guidance it started with. It
is a port of
[`pydantic-ai-harness`](https://github.com/pydantic/pydantic-ai-harness)'s
`SystemReminders`.

There are three reminder kinds, each with its own cadence:

| Kind | Cost | Text it injects |
|---|---|---|
| `reminders[]` | none | A fixed line you write |
| `goal_reanchor` | none | The run's first user request, re-stated as the anchor |
| `llm_reminder` | one model call per fire | A short nudge a model writes from the recent transcript |

Each kind takes `interval` (fire every N model requests), `first_after` (the
request number of the first fire) and `max_fires` (the cap over the conversation);
`cache_ttl` on the capability sets the lifetime of the cache breakpoint. At least
one kind must be set, or the capability contributes nothing and is dropped from the
run — which is what an empty config means.

**The cadence counts across the whole conversation, and it is durable.** A reminder
fires on model-request number N, and that counter is stored on the conversation and
seeded back at the next turn — so a reminder set to fire every ten requests keeps
counting where the last turn left off rather than resetting to zero, and leaving and
reloading a conversation resumes it (#787). Only the counters are stored; the
reminder text is injected per request and never enters the transcript.

**Injection is cache-safe.** A fired reminder is appended to the *tail* of the
request as an ephemeral user prompt behind a cache breakpoint, after core has
persisted the durable history — so it reaches the model but never enters
`message_history`, no stale reminders pile up, and the cached prefix (tools, system,
the real conversation) stays byte-identical turn over turn while only the small
reminder falls outside the cache. Injecting into the system prompt instead would
bust the cached prefix on every fire *and* accumulate stale reminders.

**An LLM reminder is metered and inherits the run's model.** It writes its text
through an agent it builds itself, which no budget guard wraps, so its spend is
booked against the run's ledger the way a summary is, and it runs under the run's
usage limits minus one reserved request so it can never push the run past its own
step limit. It uses the run's own model — the one whose credential the vault
resolved — rather than a name from config, the same decision
[Context management](#context-management) makes about its summariser. On any error,
or when the reserved budget is already spent, it falls back to the goal-reanchor
line, so a failed generation never blocks the run.

## Date and time

No tools. Puts the current date and time into the agent's instructions, so it
stops assuming one — the failure this fixes is an agent confidently reasoning
about "this quarter" from its training cutoff.

| Config | Default | |
|---|---|---|
| `timezone` | `UTC` | any IANA name, e.g. `Europe/Warsaw` |

## Context management

No tools. Trims a long run's message history before each request, so a run that
would have hit the model's limit keeps working instead. The strategies come from
[`pydantic-ai-harness`](https://github.com/pydantic/pydantic-ai-harness).

| Config | Default | |
|---|---|---|
| `strategy` | `summarize` | `summarize`, `tiered`, `clear_tool_results`, `sliding_window` |
| `max_fraction` | `0.9` | 0.05–0.95 of the window, at which compaction starts |
| `keep_messages` | 20 | recent messages that survive a summary or a window |
| `keep_tool_pairs` | 3 | recent tool calls that keep their results |
| `summary_prompt` | the library's own | what the summarising model is told; must contain `{messages}` |
| `context_window` | unset | override the window — what this triggers against *and* what the chat's gauge divides by |
| `fallback_context_window` | 200000 | window to assume when the model's cannot be resolved |

`summarize` is the default because it is the only strategy that keeps what the
older turns *said*. The zero-LLM ones are cheaper because they throw information
away — a sliding window drops the oldest messages outright, clearing a tool result
blanks an answer the agent may still need — and an agent that silently forgets
what it was told mid-run is a worse failure than a summary nobody asked for. It
fires at 0.9 of the window for the same reason: compaction is where a run starts
losing detail, so it is deferred until the window is nearly full.

`tiered` is the frugal choice and one binding away: it clears old tool results
first and pays for a summary only if that was not enough. Summarising turns input
tokens into output tokens, which are billed at a premium and generated serially,
so an agent whose runs are dominated by large tool results is usually better on
`tiered`.

**It reaches one run, not one conversation.** Between turns the history is rebuilt
from the transcript as user and assistant text, so tool calls and their results
are not there to compact and no edit made here survives a turn boundary. The
history worth compacting is the long tool loop inside a single run, where one
directory listing or knowledge search is tens of thousands of tokens.

**The trigger is a fraction because an absolute number is only right for one
model**, and the same agent runs on whatever profile its spec points at. The
window comes from the model profile, which recorded it from the provider's own
listing when somebody added the model — see
[Which models a provider offers](../models.md#the-window-a-model-accepts-is-read-once-and-kept).

Where the profile recorded nothing, the window is resolved from the bundled price
snapshot instead, and two cases resolve wrongly — both in the direction that
breaks a run rather than the one that wastes a summary: a spec with fallbacks
builds a `FallbackModel` whose composite id resolves to nothing, and
`genai-prices` records 1,000,000 for `anthropic:claude-sonnet-4-5` against a real
200,000, where `max_fraction=0.9` puts the trigger at 900,000 and compaction never
fires. `context_window` overrides everything and is the answer to both — a
provider publishes the maximum a model *can* be made to accept, and a beta- or
tier-gated deployment gets less.

**The trigger allows for what every request carries.** It measures the message
parts; a request also carries the instructions and every tool schema. On a real
agent the estimator saw 60 tokens where the provider charged for 3,865 — so the
overhead is measured against each response and the trigger's window is moved down
by it, which is what keeps the gauge and the trigger describing one ceiling rather
than two.

It waits for a response to measure from, so the first request of a run triggers on
the messages alone. And it gives up when the overhead alone is past the trigger:
no summary can get under it, the schemas are not in the history, and a corrected
window would buy a summary on every request for ever.

**When it gives up, it says so.** A `context_window` smaller than the agent's own
overhead is that case, and doing nothing about it is indistinguishable on screen
from a setting that is working — so the chat shows what the overhead is and what
window it was measured against, which is the pair somebody needs to pick a number
that works. Once per run, because it describes a configuration rather than an
event, and it is displaced the moment a summary actually runs.

**A summary says it is happening.** It is a whole model request between two of the
turn's own, where nothing else streams — the chat used to stop dead for the length
of it, which reads as a broken screen and gets the page reloaded, cancelling the
turn. The chat now shows what is being summarised while it happens. Only the
summarising strategy: the others edit a list and return.

**A summary is metered.** The strategy writes it through an agent it builds
itself, which no budget guard wraps, so the capability measures the run's usage
across the hook and books the difference against the run's ledger. It is recorded
rather than prevented: the guard refuses on the *next* request, so a compaction
that crosses a cap stops the run after it, not during it.

**The gauge beside it is not part of this binding.** How full the window was is
reported by every agent, whether or not it compacts — see
[how full the context window is](../governance.md#how-full-the-context-window-is).
The warning matters most to the agent that will *not* compact, which is the one
that reaches the ceiling and gets refused.

## Tool search

No tools of its own. Lets the agent *find* a tool from a large set instead of
carrying every tool's schema in its context on every request. This matters most
for [MCP](../mcp.md): an agent may bind an arbitrary number of servers, and every
tool a server exposes is a schema the model pays for on each turn whether or not
it ever calls it.

| Config | Default | Values |
|---|---|---|
| `strategy` | `auto` | `auto`, `keywords`, `bm25`, `regex` |
| `max_results` | 10 | 1–50, ignored by native search |

- **`auto`** — native tool search where the provider offers it (Anthropic BM25 or
  regex, OpenAI server-side), the local keyword algorithm everywhere else.
- **`keywords`** — always match locally, on any provider.
- **`bm25` / `regex`** — force an Anthropic-native algorithm; a run on a provider
  with no native tool search errors rather than silently substituting another. The
  model is resolved separately from the spec, so this is a run-time cost the author
  accepts by naming one — `auto` never fails this way.

**Enabling it is what defers the MCP toolsets.** The capability and the deferral
are two halves of one decision: the library's `ToolSearch` is inert with nothing
deferred, and a deferred tool with no search to find it is a tool the model can
never call. So binding `tool_search` is what marks the connected servers'
toolsets for deferred loading — the registry's own tools stay visible, being few
and chosen per agent. An agent that does not bind it pays nothing and sees every
tool as before.

**Deferral changes what the model sees, never a tool's identity.** A discovered
MCP tool arrives under its real prefixed name, so the [approval gate](#what-a-binding-may-change)
still pairs on it and a binding's rename still reaches it; `ToolSearch` sits
outermost, reading the names a rename already applied.

**It needs no metering.** The two local strategies run in Python and spend no
tokens; native search runs inside the provider's own request, whose usage the
[budget guard](../governance.md) already meters; and the discovery round-trips are
ordinary model requests the same guard wraps. The one shape that would escape it —
a custom search callable that itself calls a model or an embedding — is
deliberately not exposed.

## Guardrails

No tools. Inspects the text flowing through a run at three edges and either
**redacts** a match or **blocks** the run. The checks are ready-made detectors from
`pydantic-ai-harness`; an agent is data, so the config selects and parameterises
them rather than carrying a Python guard.

| Edge | Reads | Redact | Block |
|---|---|---|---|
| input | the user's prompt | `redact_secrets_in`, `redact_pii_in` | `blocked_keywords_in` |
| output | the agent's answer | `redact_secrets_out`, `redact_pii_out` | `blocked_keywords_out` |
| tool result | what a tool returned, before the model reads it | `redact_secrets_tool`, `redact_pii_tool` | `blocked_keywords_tool` |

| Config | Default | |
|---|---|---|
| `redact_secrets_*` | `false` | scrub API keys, tokens, JWTs and PEM blocks |
| `redact_pii_*` | `false` | scrub email, IBAN (mod-97), card (Luhn) and US SSN |
| `blocked_keywords_*` | `""` | comma- or newline-separated terms; a match ends the run |

Every field defaults off, and a capability enabled with no edge configured attaches
nothing — an agent that does not use it pays nothing.

**Redaction rewrites; a block is a run outcome.** A redactor scrubs the match and
the run finishes — an answer that quoted a key back has still done the work. A
keyword block instead ends the run with status `guardrail_blocked`, its own outcome
beside `budget_exceeded`, because a refusal is the platform working and an operator
filtering for problems should be able to find it rather than have it read like any
completed answer. See [Governance](../governance.md).

**Tool-result screening is the reason this edge matters most.** It is the only guard
on untrusted content entering the loop — a fetched page, a file, an MCP server's
response — where a prompt-injection payload would otherwise reach the model unread.

Two things are deliberately out of scope. **Tool arguments** are a structured
mapping with no text detector, so they are not an edge. And the harness's tool
`approve` verdict is not ported: [approvals](../governance.md) already park a run per
tool for a human decision, and a second, rule-driven path to the same mechanism is
what a single door avoids.

## Chat channel lookup

`get_channel_info` — *Describe the channel this conversation is happening in.*
`list_channel_members` — *List the people in this channel.*
`search_channels` — *Find other channels by name or purpose, without reading them.*
`read_channel_history` — *Read the most recent messages in this channel, newest last.*

The one capability an agent's spec may not bind. It is granted **per binding**,
in the Builder under *Where this agent is available*, because an organization can
bind one agent to two Mattermost servers and three Slack workspaces — and "may it
read what was said in this channel" has a different answer on the internal one and
the customer one. A field on the spec would have one answer for all five, so
publish validation refuses `channel_tools` in a spec and the run assembles the
binding from the row that admitted the message, exactly as it appends that row's
prompt to the instructions.

It is still an ordinary registry capability, which is the point of doing it that
way rather than injecting a toolset: its tools can be gated by `tool_approval` and
renamed by `tool_overrides`, both of which read the spec.

| Config | Default | Range |
|---|---|---|
| `tools` | `[]` | any of the four ids |
| `default_limit` | 20 | 1–200 |

Nothing is granted by default, and what a platform cannot answer is not offered:
Telegram gives a bot no directory of chats to search and no way to read messages
it was not sent. `docs/channels.md` has the per-platform table and the reasoning.

Three properties hold on every platform:

- **The bot's membership is the whole permission boundary.** Every call uses the
  bot's own token, so the agent sees exactly what the bot sees.
- **The model never names a channel.** The tools are bound server-side to the one
  the message arrived in — in a thread, to the channel that holds it.
- **Outside a channel it contributes nothing.** A run from the dashboard, the API
  or a schedule has no directory, so the capability is not attached at all — the
  same reason `knowledge` with no collections is not.

## What a binding may change

The catalog is the deployment's answer to "what exists". A spec's
`capabilities[]` entry is one agent's answer to "how do I use it", and it may
change four things:

| Field | Effect |
|---|---|
| `config` | Validated against that capability's schema **at publish**, not at run time |
| `approval` | `default` \| `required` \| `never` for every tool the capability contributes |
| `tool_approval` | The same, per tool, overriding `approval` |
| `tool_overrides` | The `name` and `description` the model sees, per tool |
| `secret_id` | Which organization secret satisfies a declared key requirement |
| `enabled` | Off without losing the configuration |

Approval is why a capability declares its tools at all. "May this agent write
files" and "may it read them" are two decisions even though one capability answers
both, so enabling stays per capability while approving happens per tool. `default`
follows the capability's own `side_effecting` flag.

`tool_overrides` exists because a tool's description is the highest-leverage
prompt in the product — it is what the model reads before deciding to call —
and its name steers just as hard: `search_refund_policy` is not
`search_documents`. An agent that needs different behaviour from the same tool
usually needs these reworded, not a second capability written.

Both are keyed on the tool's **stable id**, never on the name the model sees. That
is what keeps an approval gate attached to a renamed tool; keying it on the
visible name would mean a rename silently removes the gate and a side-effecting
call goes unattended with nothing reporting it. An id no such capability exposes
is refused at publish, and so is a name no model could call.

## Scopes

A capability may declare scopes the organization must have granted, checked when
the agent is assembled:

| Scope | Declared by |
|---|---|
| `knowledge:read` | `knowledge`, `skills` |
| `web:read` | `web_research` |
| `code:execute` | `code_execution` |
| `sandbox:execute` | `sandbox` |
| `agents:delegate` | `subagents` |

All five are granted by default today (`DEFAULT_GRANTED_SCOPES` in
`app/services/agent_registry.py`). Per-organization scope management is
[roadmap](../ROADMAP.md) work; the check is live and honest in the meantime rather
than disabled and forgotten.

`agents:delegate` is the one worth understanding, because it is *not* the gate on
who may be delegated to — that is `agents:run`, checked on the publisher against
each delegate's row. This scope answers a question no permission can: whether this
**deployment** allows agents to call agents at all. Removing it from that set turns
delegation off everywhere in one edit, which is what an operator who does not want
nested runs or fan-out billing needs, and every spec that delegates then says so at
publish rather than at 3am.

## Adding to this list

Capabilities are code — nothing an operator types brings a new one into being,
which is what makes the set of things an agent can do reviewable. See
[Add a capability](../howto/add-capability.md) for a new one, or
[Add a tool to a capability](../howto/add-capability.md#adding-a-tool-to-an-existing-capability)
when the capability already exists.

For tools nobody here has to write, see [MCP](../mcp.md).
