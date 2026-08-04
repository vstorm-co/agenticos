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

**Fan-out is bounded.** A run may launch background delegations and carry on, so
without a ceiling it can keep launching them. The refusal is a tool result the
model can act on — wait, or do the work itself — never an exception, because a
pacing limit should not end a run.

**Every delegation is recorded.** A delegate spends against the *parent's* ledger
by construction, which is what makes the parent's budget see a delegation before
the next request. So the only honest description of what one delegation cost is
what the shared total grew by while it ran. That is exact for a sync delegation,
which holds the run loop, and overlapping for concurrent ones — stated in
`DelegationOutcome` rather than hidden.

## What it deliberately does not do

**Resolve its own delegates.** A delegate is rows: an agent, a pinned version, its
collections, skills and secrets, each of which has to pass `resolve_access`
first. The runner walks that tree while it still holds a session and an auth
context, and hands the result over as `SUBAGENT_RUNTIME_RESOURCE` — the same shape
and the same reason as the workspace backend. A capability that queried for its
own delegates would need a session per delegation, on an `AsyncSession` that is
not concurrency-safe.

**Offer the dynamic entry points.** `create_agent` and `delegate` are declared —
a tool absent from `tools=` cannot be gated or renamed — but not wired, and
`allow_dynamic` therefore changes nothing yet. That is not an oversight waiting
on plumbing: the library builds a dynamic specialist itself, from its own default
model string, which means an agent outside this deployment's model catalog, its
vault and, most importantly, its budget guard. An unmetered model request is
precisely what this platform exists to refuse. Wiring them means giving the
library a factory that goes through `build_agent`, and routing both tools through
`_toolset.py` so they cannot escape the mode, fan-out and recording decisions
above.

Declared-and-not-offered is the one thing the shared drift check has to be told
about, and it is told in one place: `UNWIRED_TOOLS` in
`tests/test_capability_registry.py`, which names these two ids and points back
here. It replaced a `CapabilityDef.drift_config` field that named a configuration
instead — a field nothing read, and one that would have failed had anything read
it, since no configuration makes these two appear.

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
pre-built. A specialist works autonomously and says so if it could not; a
specialist that needs a person reaches one through its own capabilities, on the
parent's channels, which `AgentDeps.clone_for_subagent` passes down.

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

**Cancellation is the library's, verified under ours.** `SubAgentCapability.wrap_run`
cancels every task the run started and waits up to `cancel_grace_seconds` for each
to unwind; this capability's `wrap_run` then settles whatever those cancellations
produced, which is why a stopped turn still records what its delegate spent. The
cancel that matters here arrives from outside — `AgentSession` cancels `_turn_task`
for a `stop` frame and for `shutdown` — so it is asserted through that teardown
rather than in isolation, in
`tests/test_agent_session.py::TestStoppingATurnMidDelegation`. The library's
default grace period is kept: nothing in this deployment shields a delegate's
cleanup, so a cancelled delegation unwinds immediately and a setting of our own
would be a knob nothing turns.

## The general-purpose delegate

`include_general_purpose` defaults `False`, against the library's own default, and
the reason is worth keeping: its general-purpose subagent is a copy of the parent
with no instructions of its own, built on the library's default model string. An
agent whose behaviour nobody specified is the thing this product exists to
prevent, and one on a model this deployment did not configure is not priced,
metered or credentialed like everything else here. It stays configurable because
an author may genuinely want a catch-all; it stays off by default because nobody
should arrive at one by accident.

## Reading the code

| File | |
|---|---|
| `__init__.py` | `SubagentsConfig` — the Builder form — and the one `@register` |
| `_capability.py` | The tool declarations, the adapter, and how a delegate becomes a `SubAgentConfig` |
| `_toolset.py` | The `task` call: mode, fan-out, and settling the outcome |
| `_journal.py` | What a run has delegated: in flight, what it cost, which stream is whose |
| `_events.py` | A delegate's stream events, as frames a surface can render |
