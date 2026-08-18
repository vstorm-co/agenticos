# Approval

`ApprovalGate` wraps tool execution and refuses to let a gated tool run until a
human has answered. Which tools are gated is resolved once, from the spec, when
the agent is assembled.

Not registered in the capability registry. Like the budget guard, every agent
gets one - an agent whose approval gate is optional is an agent somebody can
configure into sending email unattended.

## Where the pieces live

| File | What |
|---|---|
| `app/agents/approval.py` | `ApprovalRequest`, the three decisions, `refusal()` |
| `_policy.py` | `tool_needs_approval()` - the rule, and the only copy of it; and what the rule cannot enforce |
| `_capability.py` | `ApprovalGate` - the only thing that enforces them |

The decision types sit a layer *below* this capability, not inside it. They are
the contract between four parties - the gate asks, a surface carries the
question to a person, the approvals service records the answer, and `AgentDeps`
holds the callback that joins them - and only one of those four is this
capability.

They used to live in `_capability.py`, which made `app/agents/deps.py` depend on
a capability that imports `deps` straight back. That cycle was survivable only
because the annotation hid behind `TYPE_CHECKING` and a lazily-evaluated PEP 695
alias, with a comment apologising for the arrangement. Moving the types below
both removes the cycle instead of working around it - and the first attempt,
splitting them into a sibling module *inside* the package, did not: importing
the submodule still initialises the package, whose `__init__` pulls in the gate.
Module layout has to follow the direction of dependency, not the shape of the
folder.

## Why it wraps execution instead of living in the tool

Enforcement a tool has to remember to call is enforcement the next tool forgets.
Wrapping means a tool is gated because the spec says so, not because its author
thought about approval.

## What is gated, and by what rule

It gates by **the name the model called**, decided by the tool's **stable id**.
Those two differ the moment a binding renames a tool, and `_policy.py` is the
only place allowed to translate between them - see "Renamed tools" below.

Gating used to be per capability id, on the argument
that "this agent may send email" is the decision a person actually makes. That
argument only holds for a capability with one tool. A `filesystem` capability
wants `write_file` gated and `read_file` not; an `email` capability wants
`send_email` gated and `draft_email` not. Per capability there is no way to say
that - you approve all of it or none of it, and a queue that asks about reads is
a queue people learn to click through, which is how the write gets approved too.

So a capability declares its `tools` in the registry (a stable id plus the
docstring summary the model reads), the Builder shows them, and the spec answers
per id. Enabling is still per capability; only approval got finer.

The rule, in `_policy.py`, takes the most specific statement available:

| Precedence | Source | Means |
|---|---|---|
| 1 | `tool_approval[tool_id]` | this agent, this tool |
| 2 | the binding's `approval` | this agent, every tool of this capability |
| 3 | the capability's `side_effecting` | what the code that wrote the tool says |

`'default'` at level 1 or 2 is a deferral, not an answer. A spec with neither
key therefore behaves exactly as it did before per-tool approval existed, which
is what keeps an agent published against `spec_version: 2` gating the same tools
today.

A `tool_approval` key naming a tool the capability does not declare is refused
at publish (`AgentRegistryService.validate_spec`). It has to be: a typo there
produces no error at run time, just a tool that quietly never asks.

Tools no capability owns (an MCP server's) are left alone even if one shares a
name with a gated tool: their approval belongs to the connection, and answering
for them here would be a guess.

### A tool this deployment does not execute cannot be gated

The gate wraps *execution*, so a tool the model provider runs on its own side -
a native fetch, a native search - never reaches it, and a binding that gates one
gets a gate that never fires with nothing reporting it. A capability declares
those configurations as `provider_executed` in its `register(...)`, and
`_policy.py` answers with both halves: `ungateable_tool_problems` is what publish
validation appends to its list, and `refuse_ungateable_approvals` is what
`build_agent` calls before assembling anything.

The second exists because the first is not enough. A frozen `AgentVersion` is
never re-validated - a run reads its stored spec and builds it - so a publish-only
refusal closes the defect for new agents and leaves every agent already published
with it fetching and searching unapproved (#871). Refused at assembly rather than
downgraded: swapping the binding to a method this deployment runs would answer a
question that belongs to the author, and dropping the gate is the bug. The price
is that such an agent stops running on upgrade, and it is the right price - the
approval its operator asked for was never being asked for.

### Declared tools, and the drift that threatens them

The declaration is a second copy of something the code already knows, so it can
go stale - and stale in the direction that matters, a new side-effecting tool
nobody declared and therefore nobody can gate. Deriving the list instead would
mean building every capability to read the catalog, and two of them build to
nothing without database rows (`knowledge` without a collection, `skills`
without skills), so deriving would mean fabricating rows on a catalog request.

The declaration stays, and `tests/test_capability_registry.py` holds it honest:
it builds every registered capability, gives the two that need resources some,
and asserts the declared ids are exactly the tools the model is offered - then
does it again through a binding that renames all of them, so a tool nobody
declared still cannot hide behind the rename.

## Renamed tools

A binding may rename a tool and reword its description (`tool_overrides` on the
spec, applied by `ToolOverrides` in `capabilities/_overrides.py`). Approval is
keyed on the tool's stable id, so the operator's decision survives the rename -
but the gate matches `tool_def.name`, which after a rename is not that id.

`approval_required_tools` therefore **decides by id and answers with the
effective name**, via `CapabilityDef.effective_tools`. Returning `tool.name`
from the static declaration instead would leave the gate watching for a tool the
model never calls, while the renamed one - the side-effecting tool somebody
deliberately gated - ran unapproved with nothing reporting it. That is the
failure this arrangement exists to prevent, and
`tests/test_tool_overrides.py::TestARenamedToolIsStillGated` drives it through a
real agent.

`knowledge` used to have its own `config.tool_name`, which approval could not
see through, so a renamed search tool could not be gated at all. That field is
gone and the general mechanism replaces it; a version-3 spec that used it is
migrated on load.

A rename is refused at publish if it names a tool the capability does not have,
if the new name is not something a model can emit, or if it would leave two
tools sharing a name.

## The three outcomes

| Decision | What the gate does |
|---|---|
| `ApprovalGranted(tool_args)` | Executes **the approved arguments**, not the ones the model just produced |
| `ApprovalRejected(note)` | Returns a refusal as the tool's result - the model responds, the run lives |
| `ApprovalPending()` | Raises `ApprovalRequired`, ending the run with the call parked |

No callback at all (`AgentDeps.request_approval is None`) is a refusal too. An
agent running where nobody can be asked - a schedule, a webhook - must not
decide on its own that unattended is fine.

## Parking and resuming

`ApprovalRequired` is Pydantic AI's signal for a human-in-the-loop call: the run
ends with a `DeferredToolRequests` output instead of an answer, and
`AgentRunnerService` records the run as `awaiting_approval` with the message
history in `agent_runs.paused_state`. Holding the coroutine open instead would
mean a database connection and a task per pending decision, for however long a
person takes to look.

On resume the runner replays those messages with
`ToolApproved(override_args=<stored args>)` for every decided call - including
rejected ones. That looks odd for a rejection and is deliberate: `ToolApproved`
means "let this call reach the tool pipeline", and the gate is the single place
allowed to decide whether a side effect happens. Splitting that authority
between the library and the gate would give refusals two sources of truth.

The decision is consumed once. If the model calls the same tool again later in
the resumed run, it parks again - a second act needs a second approval.

**A gated tool inside a delegate parks the whole run, and the parked state is a
tree.** The delegate reaches this run's channel - a specialist that needs a person
needs the person already waiting - so the row is written here, by the delegate's own
gate, naming the delegate's tool. But the *parent* suspends on its `task` call, so
what the run has to store is one level per agent: each one's messages and each one's
parked calls. `ToolApproved` on a `task` call means "reach the delegation tool
again", and the delegation capability answers it by continuing the suspended delegate
rather than starting a new one - so the decision applies to the call a person was
shown. `subagent_name` on the row is who was asking;
`app/agents/capabilities/subagents/README.md` has the rest.
