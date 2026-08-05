# subagents — delegation

One agent handing part of a job to another. The tools, the task lifecycle and the
background execution come from
[`subagents-pydantic-ai`](https://github.com/vstorm-co/subagents-pydantic-ai);
what lives here is who an agent may delegate to, under which ceilings, and what
every delegation is recorded as having cost.

## Why an adapter rather than registering the library's capability

`thinking` registers Pydantic AI's own class and has no `_capability.py` at all,
so wrapping somebody else's capability needs a reason. There are three.

The **reference docs are generated from the docstrings in this repository**, and
"what may this agent do" is the question a client asks first. A capability
documented only upstream is one nobody here can answer it for.

**`get_instructions` has to describe our delegates.** The library lists the
configs it was handed. What an author actually published is a pinned agent
version or an inline specialist, with a description written for the parent's
model — plus the mode this deployment will force and the fan-out it will refuse.
Two lists that mostly agree are worse than one, because the disagreement is
silent.

And **an adapter is what stops a library release from changing what an agent
can do.** `SubAgentCapability` is a dataclass of twenty fields with defaults, one
of them `include_general_purpose=True` — which this platform inverts. Registered
directly, a field added upstream would arrive switched on in every published
agent with nothing here saying so.

## What this decides, and the library does not

**The mode is the spec's.** The library's `task` tool takes a `mode` argument
defaulting to `"sync"`, so "the model chose sync" and "the model said nothing"
are the same call — there is no way to honour both an author's setting and a
model's choice. The author's was reviewed, so it wins, and the argument is
replaced on the way through. An author who wants the model to decide sets `auto`,
which is resolved here rather than inside the library: `SubagentStarted.mode` has
to be concrete *before* the delegation runs, because it is what tells a surface
whether to keep a panel open after the parent has answered.

A delegate may pin a mode of its own (`ResolvedSubagent.preferred_mode`), and then
*that* delegation runs its way rather than the agent's. Which means the
instructions cannot state one mode and stop: an agent configured `sync` with one
delegate pinned `async` told its model "each delegation blocks until the specialist
answers" and then handed that delegate back a task id. So a delegate that overrides
is marked in the list `get_instructions` renders, and the ceiling note says the
exceptions are there — what the model reads has to be what will happen.

**Fan-out is bounded.** A run may launch background delegations and carry on, so
without a ceiling it can keep launching them. The refusal is a tool result the
model can act on — wait, or do the work itself — never an exception, because a
pacing limit should not end a run.

**Every delegation is recorded.** A delegate spends against the *parent's* ledger
by construction, which is what makes the parent's budget see a delegation before
the next request. One ledger, and every entry in it stamped with the delegation
that booked it — so what one delegation cost is the sum of its own entries, exact
in both modes and at every depth. It used to be the *growth* of the shared total
across the delegation, which absorbed whatever the parent spent before a background
one was polled and counted a delegate's delegates inside its own share
(agenticos#180); `DelegationOutcome` has the numbers.

A delegation that **parked** is more than one such share, because its turns ran
against different ledgers in different processes and a resumed turn's is a fresh
object. So the park keeps a running total and `_spent` adds this turn's share to it;
one row is written, by the turn where the delegation ends. Left out, the row held
what the delegate spent after the last resume — the small half, on the ordinary shape
of doing the work and then asking permission to act on it — and nothing anywhere
disagreed, because the money was in the parent's row all along.

`has_unpriced_models` is carried the same way and OR'd across the segments, because
`cost_is_partial` is per share now rather than per run: a delegate that made an
unpriced request *before* the approval and resumed onto a priced model would
otherwise have its row claim an exact cost for money nobody priced.

**A delegate that stopped for a person keeps its place.** See below; it is the one
decision here that is a correctness fix rather than a policy.

## Nesting: `max_depth` counts the configured agent's own level

`max_depth=1` — the default — is "this agent delegates, its delegates do not". So
the budget handed down the tree is `max_depth - 1`, and the subtraction is the whole
of the setting's meaning rather than an off-by-one: it used to be passed straight
through, which made the documented behaviour of `1` what `0` did and shipped a
default that allowed one nested level nobody had asked for. `0` is no longer
expressible: it would be a *second* off switch, and the first one — disabling the
binding — is the one publish validation already understands.

At the bound a delegate is built *without* the capability rather than with one that
can only refuse, because that tool's description is context the model pays for on
every turn and the first thing it does with one is try it.

`SubagentRuntime.depth` is told to each level by the runner rather than computed
from `max_depth - depth_remaining`. Those two numbers come from *different* specs —
the ceiling is the delegating agent's own setting, the remainder is what the tree
has left — so any delegate configuring a different ceiling reported the wrong depth,
and a surface nested its panel under the wrong parent.

**And the parent is told too, for the same reason.** Depth alone says which *level* a
delegation is on, not which delegation it belongs to, so a surface with only the
depth has to guess — "the most recent still-running delegation one level up", which
is wrong the moment two are running, which is the ordinary fan-out: a researcher's
helper drawn inside the writer's panel, and the researcher showing no children. The
journal already reads the enclosing delegation at `begin` for the parked tree, so
`SubagentStarted` carries the same `parent_task_id` — `None` for a delegation the
run's own agent started.

## A gated tool inside a delegate, and how the run is continued

This is the supported shape, and making it work is more than passing the signal
through. A delegate whose tool needs a person reaches the *run's own* approval
channel — that is what makes it usable at all, since the delegation holds the
parent's tool call and there is somebody already waiting. So the row is written by
the **delegate's** gate and names the delegate's tool and arguments: the queue is
honest, and `subagent_name` on the row is what says who is calling it.

But the parent suspends on its own `task` call. `DeferredToolRequests.approvals`
therefore holds the *delegation*, not the delegate's tool, and replaying the parent
with the granted approval presented an id the run never asks about — which Pydantic
AI refuses outright. The obvious repair, delegating again, is worse than the
refusal: the delegate starts from nothing, the model need not call the same tool the
second time round, and **what a reviewer approved is not what executes**. Nothing
raises.

So a parked run is a tree, and three pieces carry it:

- **`DelegationJournal.park`** writes the delegate's conversation, the `task` call
  that identifies the delegation, the delegation's parent and what it has spent so
  far into `DelegationStash`. Called from `_toolset.py`, where the suspension propagates
  past — the only point at which the delegation record, the library's task handle
  and the parent's tool call id all exist at once. The library keeps the history on
  that handle and deliberately does *not* save it as a chat trace, because a trace
  resumed from a point whose deferred results were never supplied would replay the
  suspension forever.
- **`_LazyAgent._continuing`** puts it back: on the replay the same `task` call
  arrives, `journal.resuming()` finds the place, and the delegate runs with its own
  `message_history` and the verdicts on the calls it parked as
  `deferred_tool_results` — which is exactly how a top-level parked run is
  continued, one level further in. Both entry points, because the library uses
  `iter` when retries are on and `run` when they are off.
- **`AgentRunnerService`** owns the storage and the splitting. The tree goes into
  `agent_runs.paused_state`, and each level gets only *its own* parked calls:
  Pydantic AI refuses a resume whose results name a call the replayed response does
  not contain, so one flat set for the whole tree fails the continuation.

Everything in the stash is plain data, and that is a constraint rather than a
preference: it outlives the tool call it was made in and is written to a JSONB
column, while `request_approval` closes over a service holding the request's
`AsyncSession`. Messages and ids, never a live object.

Two things degrade rather than failing. A frame whose `messages` are empty — the
library's history is best-effort telemetry — re-runs the delegation instead of
continuing it, but the `task` call is still answered, because a parked call left
without a result makes the whole run unresumable. Its **spend is still carried**,
which is why the two are separate fields on the stash rather than one: how to
continue is best-effort, what it already cost is not, and a delegation re-run from
the start has still spent it. And a suspension arriving without
a task id keeps nothing at all: the library assigns one before it runs anything, so
no delegate can have suspended, and a frame invented there would claim the run's own
parked calls as a delegate's.

## What it deliberately does not do

**Resolve its own delegates.** A delegate is rows: an agent, a pinned version, its
collections, skills and secrets, each of which has to pass `resolve_access`
first. The runner walks that tree while it still holds a session and an auth
context, and hands the result over as `SUBAGENT_RUNTIME_RESOURCE` — the same shape
and the same reason as the workspace backend. A capability that queried for its
own delegates would need a session per delegation, on an `AsyncSession` that is
not concurrency-safe.

**Let the library build a specialist a model invents.** See below; it is what
`allow_dynamic` turns on, and the one place the library's own default is not
merely inverted but replaced.

**Build a delegate that is never used.** Each `SubAgentConfig` carries a
`_LazyAgent` rather than an agent, because the library compiles every config when
its toolset is constructed — before any delegation has happened. Building one
resolves a model profile, assembles capabilities and instruments the agent; a
delegate the model never calls should cost none of that.

## The deps a delegation actually runs with

`_LazyAgent` has a second job, and it is not optional. **The library decides what
deps a delegation runs with, and they are not the ones the delegate was built
with:** it calls `clone_for_subagent` on the *parent's* deps and hands the result
to the child's run, so the `AgentDeps` the runner built for the delegate is
discarded before its first request. Almost everything on that clone is right and
deliberately so — the organization and user a delegation acts for, the parent's
`agent_id` and `run_id` (they key the shared workspace, which is how a researcher
and a writer see the same files), the parent's `ask_user` and `subagent_events`.

Two fields are decided here instead.

**The collections are the delegate's own.** `clone_for_subagent` drops them on
purpose: inheriting the parent's would hand a specialist a collection nobody
granted it. So the two halves are complementary — the parent's are dropped, and
the delegate's own are put back from `ResolvedSubagent.collection_names`, field by
field onto the clone, on both `run` and `iter`. Without it the failure is silent
(agenticos#166): a delegate bound to a collection resolves it, is handed deps
without it, and answers "No active knowledge bases selected" to every search — a
specialist that publishes cleanly, looks correctly configured, and cannot read the
one thing it exists to read.

**A background delegation gets no approval channel.** `request_approval` closes
over `ApprovalService`, which holds the request's `AsyncSession` — shared by the
whole run and not concurrency-safe — and a background delegation outlives the tool
call that started it. Asking is therefore a database write from a task the parent
is still sharing its session with, for a decision that cannot be delivered anyway:
the tool call returned a task id long ago, so there is no caller left to hand a
parked call back to. The channel is handed down as `None`, which is the case the
gate is already written for — it refuses the call, tells the model a person could
not be asked, and the delegation goes on to answer or to say it could not. A sync
delegation keeps the channel, because there a parked call genuinely does park the
parent run; that is the supported shape, and `mode="sync"` is what the library's
own message tells a model to re-delegate with.

**Let a delegate ask the parent a question.** The library's `ask_parent` tool is
injected only into agents it built itself, and every delegate here arrives
pre-built — so `task` passes `inject_ask_parent=False` for a pinned delegate and an
inline specialist alike, and `_autonomously` closes the two dynamic entry points as
well. A specialist works autonomously and says so if it could not; a specialist that
needs a person reaches one through its own capabilities, on the parent's channels,
which `AgentDeps.clone_for_subagent` passes down.

So **`answer_subagent` is declared and offered to nobody** — `UNREACHABLE_TOOLS`,
applied as a filter in `get_toolset`. It replies to a question that cannot be asked,
and the library adds it to its toolset unconditionally, so the offered set is the
only place the decision can be made. Declared still, because a tool absent from
`tools=` can be neither gated by the approval policy nor renamed by a binding, and
that half is silent; filtered, because the other half is a description in every
turn's context inviting a call whose only answer is "that delegation is not waiting
for an answer". Opening the path is a feature rather than a repair, and which
channel answers depends on the mode: a `sync` question is answered by a *person*,
through `ask_user`, and never through this tool — so it becomes reachable only for a
background delegation, whose question the parent's own model answers while nothing
obliges it to look. agenticos#184 is the sync half, worth doing on its own terms, and
it would not make this tool reachable.

## Background delegation, and what it costs

`mode` decides whether a delegation blocks the parent's tool call (`sync`, the
default), runs in an `asyncio.Task` the parent collects later (`async`), or is
decided per task from what the model said about it (`auto`, resolved here rather
than in the library — see above). A background delegation is collected with the
lifecycle tools the library provides: `check_task` for one, `wait_tasks` for
several, `list_active_tasks` for what is still going,
`send_message_to_subagent` to steer one mid-run, and the two cancels. Every one of
them is scoped to the run that started the task — a task id is short and appears
in tool output, so an unscoped lookup would let one run read and kill another's
work.

These six are **offered only when a background delegation is reachable**, the same
`get_toolset` filter that withholds `answer_subagent` — `BACKGROUND_LIFECYCLE_TOOLS`
and `_can_delegate_in_background`. Each takes or reports on a task id, and a `sync`
delegation returns the answer and a `chat_trace_id` and nothing else, so a
`sync`-only agent is handed none of them and `task` alone. Reachable means the
configured mode is `async` or `auto`, a pinned delegate prefers either, or the agent
may invent specialists — `sync` being the default is what makes withholding them the
common case rather than a corner. The predicate errs toward offering: removing a
tool an agent needs mid-turn is worse than offering one it will not use.

Three things about it are not obvious.

**`wait_tasks` truncates.** A completed task's result is cut to
`max_result_chars` with a marker saying the cut is ours, that the stored answer is
whole, and which tool returns it in full. That marker is load-bearing: a silent cut
read to an orchestrator like a specialist that had stopped mid-sentence, so it
re-delegated work it had already been handed half of
(`subagents-pydantic-ai#55`).

**A background delegation cannot park on an approval** — see the deps section
above. If one suspends anyway (a tool that defers its own call, without going
through the gate), the library reports `DEFERRED` on the handle with a message
naming the rule, and this platform records that as `failed`. Reading it as "still
going" is what `_RESOLVED` alone did, and it failed three ways at once: the spend
was attributed to nothing, the fan-out slot was never released, and the panel a
surface had opened never closed.

**Cancellation is half the library's, and the other half is here.**
`SubAgentCapability.wrap_run` cancels every *task* the run started and waits up to
`cancel_grace_seconds` for each to unwind. Two things that leaves:

A **sync** delegation — the default mode — has no task, only a handle, so nothing
in that sweep touches it; and `asyncio.CancelledError` is a `BaseException`, so the
library's `_run_sync`, whose every `except` names an `Exception` subclass, does not
touch the handle either. A `stop` arriving mid-delegation therefore left the handle
`RUNNING`, `_terminal_status` answered "not over", and the delegation was filed as
still going and never recorded — the spend attributed to nothing, the fan-out slot
never released, the panel never closed. So `Delegation.wrap_run` finishes everything
still in flight as cancelled *before* settling, which covers every mode and, because
each level wraps its own run, every nesting level. A delegation parked on an approval
is untouched by that sweep: `DEFERRED` is already terminal and `TaskHandle.finish`
keeps the first terminal status.

And the grace period **expires** — it does not guarantee the delegate stopped. A
delegate whose cleanup outlasts it is still executing after the row is written:
writing into a workspace `finish` closed, appending to a ledger whose `cost_usd` was
already persisted. Nothing here can stop it, so it is logged
(`delegation_outlived_the_run`) rather than claimed not to happen. The library's
default grace period is kept: nothing in this deployment shields a delegate's
cleanup, so a setting of our own would be a knob nothing turns.

The cancel that matters arrives from outside — `AgentSession` cancels `_turn_task`
for a `stop` frame and for `shutdown` — so it is asserted through that teardown
rather than in isolation, in
`tests/test_agent_session.py::TestStoppingATurnMidDelegation`, in both modes.

## A specialist the model invents: `allow_dynamic`

Off by default, and switched on it adds the two entry points that were declared
and not offered for two phases: `delegate` creates a specialist and runs it in
one call, `create_agent` keeps one and `task` reaches it by name. What held them back was never plumbing, and it is what the whole of this
section is about.

**The library builds a dynamic specialist itself, from `default_model`.** That is
an agent on a model string of its own choosing — outside this deployment's model
catalog, outside the vault, and outside the budget guard. An unmetered model
request on a provider the organization may hold no key for is the one thing this
platform exists to refuse, so the fix is not a flag but a
`default_agent_factory`: every specialist a model invents is built by
`build_agent` with the run's `shared_budget`, the same door an inline specialist
and a pinned delegate come through. Its spend therefore lands on the run's shared
ledger and the parent's cap sees it *before the parent's next request*, which is
the property `tests/test_dynamic_specialists.py` exists to pin — reverting the
factory fails it, in both halves.

**`allowed_models` is the organization's own profiles, by label.** Free text
would be a model naming `openai:gpt-4.1` in an organization holding no OpenAI
key: a run that dies at its first request with a provider error, named by a model
that had no way to know. The runner is the half that can see the profiles, so it
resolves them — a query and a vault unseal each, paid once per run and only by an
agent whose author asked for this — and hands them over as
`SubagentRuntime.dynamic`. The label is the handle because it is what the Builder
shows an author and what an organization's models are unique by.

The list is never empty in a run, and that answers a rule nobody has to write:
the delegating agent's own profile resolved before any of this, so the catalog
holds at least it. Publish validation already refuses a spec with no
`model_profile_id`, and one whose profile is gone — so "an organization with no
usable model publishes `allow_dynamic`" is not a state a run reaches, and a second
publish rule for it would be unreachable code. A profile that no longer resolves
is left off the list with a warning rather than failing the run, for the reason
`resolve` already applies to a fallback chain.

**There is no default model, so naming none is refused.** The library would fall
back on `SubAgentCapability.default_model`, so the omission is refused in
`_toolset.py` and the model is pointed at the list in its instructions. Setting
`default_model` to an unusable value instead would raise from inside the library
where a refusal that names the allowed models is something the model can act on.

**A specialist is instructions and a model, and nothing else.** No capabilities,
no knowledge, no skills, no MCP connections, no workspace, no delegates. Two
consequences are worth stating because both are load-bearing. A specialist a
model wrote cannot reach a credential the organization granted the agent that
invented it — which is the tempting route precisely because nobody thinks of it as
an agent. And it cannot delegate a level further, structurally rather than by a
ceiling it could talk past: a dynamic specialist is a level like any other, and at
`max_depth` the whole capability is removed, which removes these two tools with
it.

`capabilities_map` is therefore empty, and a model asking for a capability is
refused rather than quietly ignored. **It stays empty until somebody builds the
parent-intersected, author-chosen, publish-checked allowlist** — populating it
from anything less is the ungranted-scope failure wearing a new hat, and half of
it would be worse than none.

**Creating one needs approval, by default.** This is the one place delegation and
*dynamic* delegation part company. `task` is not side-effecting because what a
delegate does is gated by the delegate's own reviewed spec; there is no reviewed
spec here, so the specialist itself is the thing worth a person's eye. An author
who wants an agent to run unattended clears it with `tool_approval`.

**Nothing is persisted, and a kept one lasts less long than "the run".** The
registry `create_agent` writes into belongs to the *built agent*, and a run that
parks on an approval is built again when it is continued — so a specialist
created before the park is unknown after it, while the transcript still carries
the library's "created successfully". `create_agent`'s description says so and
`task` answers "unknown subagent", which makes it recoverable rather than
surprising; making the tool mean what its name says is agenticos#175. Keeping one
properly means publishing an agent, which is a person's action.

`MAX_DYNAMIC_SPECIALISTS` bounds how many one run may **keep**, which is the
registry's ceiling and nothing else: a `delegate` call registers nothing, so
one-shot specialists are bounded by `max_fanout` on how many run at once and by
the agent's own `max_steps` on how many calls a turn can make.

**Both entry points are routed through `_toolset.py`**, which is what puts a
one-shot delegation under the same mode, fan-out ceiling and recording as a
`task` call. `delegate` spells its arguments differently, so `_ENTRY_POINTS` is a
table rather than a comparison against one name — a delegation this module does
not see is one that escapes every decision it makes.

Wiring both removed `UNWIRED_TOOLS` from `tests/test_capability_registry.py`, and
before it a `CapabilityDef.drift_config` field that named a configuration nothing
read. What stands in their place is a resource fixture wide enough — one resolved
delegate *and* a `DynamicSpecialists` — that no capability has an excuse for not
building.

An exception table is back, and it is a narrower claim than either of those:
`DECLARED_AND_NOT_OFFERED` names `answer_subagent`, subtracted from the expectation
rather than exempting the capability, so everything else about `subagents` is still
compared in both directions. That "nothing left to be told about" only held while a
declared tool was declared and *unwired*; a declared tool that is declared and
deliberately *unoffered* is a state the check has to know about, or it reads the
filter as drift.

## The general-purpose delegate is not offered

`build_delegation` passes `include_general_purpose=False` unconditionally, against
the library's own default of `True`. That is a fact about somebody else's default,
stated in one place — not a setting, and never one an author could reach.

The library compiles this delegate at construction from `default_model`, a model
string of its own choosing: no profile of this organization's resolves it, no
credential of this organization's is unsealed for it, and the run's `BudgetGuard`
never wraps it. So a deployment holding no such key fails the build outright, and
one with that key in its process environment runs a tenant's work on a
deployment-wide credential — unpriced, unmetered, and against the one rule
`model_resolver.py` states outright. A switch whose two outcomes are a crash and a
credential leak is a trap, and a warning beside it is not a guard.

There was briefly an `include_general_purpose` field on `SubagentsConfig`,
defaulting off with that warning written next to it. It was removed rather than
deprecated because this capability had not yet merged: no published spec carried
the field, so nothing needed coercing or migrating. It was not replaced with a
publish-time refusal either — a control that always fails publish costs an author a
round trip to learn it does nothing.

An author who wants a catch-all writes an inline specialist, which runs on one of
this organization's model profiles through `build_agent` like every other delegate,
and whose instructions somebody can read. Making the library's own work means
resolving it here the same way: agenticos#174, still open, and an upstream defect
regardless of what this deployment configures.

## Reading the code

| File | |
|---|---|
| `__init__.py` | `SubagentsConfig` — the Builder form — and the one `@register` |
| `_capability.py` | The tool declarations, the adapter, how a delegate becomes a `SubAgentConfig`, and the factory a dynamic specialist is built by |
| `_toolset.py` | The calls that delegate: mode, fan-out, settling the outcome, and what an invented specialist is refused |
| `_journal.py` | What a run has delegated: in flight, what it cost, which stream is whose |
| `_events.py` | A delegate's stream events, as frames a surface can render |
