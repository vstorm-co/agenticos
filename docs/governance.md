# Governance

Budgets, approvals, alerts and the audit trail. The four things that make an
agent platform something you can put a credit card behind.

All of them apply identically on every surface, because every surface goes through
one runner.

## Budgets

Two levels, and they are not variations on one number.

| Level | Set in | Meters | Raised by |
|---|---|---|---|
| **Agent monthly** | the agent's spec | that agent's own runs | whoever may edit the agent |
| **Organization monthly** | organization settings | every run *and* ingestion in the organization | whoever holds `budgets:manage` |

### Why they cannot be collapsed

They used to be, with `min()`, and the result was wrong. An agent's cap measured
against the organization's total is exhausted by its neighbours' runs, which is
precisely what makes it not a cap. An organization's cap measured against one
agent's spend would never bind.

So each cap meters its own quantity, and the lookup travels with the limit. A $5
agent under a $50 ceiling now binds when *it* has spent $5, and the refusal names
the cap that actually bound rather than inferring it from which of two numbers was
smaller.

An agent still cannot loosen the organization's ceiling: the organization's entry
is present at its own number whatever the spec asks for, and an agent's spend is
part of the organization's - so a $100 agent under a $10 organization is stopped
at $10.

### Enforcement is before the request

Checked *before* each model request, not after. Checking afterwards means the
request that broke the budget was already paid for, and a loop can overshoot by
one expensive call every time.

!!! important "A failed run still records what it spent"

    A budget that ignores failures is not a budget. Accounting happens in a
    `finally` block on every surface, and the commit is explicit rather than left
    to the session context - which rolls back on any exception and is never
    reached at all on cancellation.

### Step limits

The other kind of runaway is a tool loop: cheap per call, and it never finishes. A
budget only bills for that. `max_steps` caps how many model requests one run may
make and is what actually stops it.

### Reporting

A run that could not be priced - a model `genai-prices` does not know - is
recorded at zero with a warning and the total is flagged as a **floor** rather
than guessed at. The UI shows that as a `+` next to the figure.

## Approvals

A tool that acts on the outside world parks the run and waits for a person.

Resolution is most-specific-first:

1. the tool's own override, if it has one
2. the capability's `approval` mode (`required` | `never` | `default`)
3. what `side_effecting` decides, for `default`

The Builder states the outcome in words rather than describing the rule, because a
rule the reader has to run in their head is a setting nobody dares touch.

Three properties worth knowing:

- **A parked run is resumable.** Its message history is stored, so the decision is
  applied to the conversation it belongs to rather than starting again.
- **A decided approval cannot be decided twice.** The second decision is refused.
- **`required` works on any capability**, not only side-effecting ones. "This only
  reads, but in my organization somebody approves it anyway" is a real decision
  and is expressible.

!!! warning "MCP tools are outside the approval gate"

    An approval set on a capability does not cover them. Anything an agent's bound
    MCP servers can do, that agent can do without asking. Which of a server's
    tools are exposed is set on the connection, so every agent bound to it gets
    the same ones.

## Alerts

Every alert here is about a run nobody is looking at. A chat run that stops on its
budget says so on screen; the same run started by a Slack mention, a schedule or
an API call stops silently, and the first anyone hears of it is somebody asking
why the agent went quiet.

### Configured on the agent

Who hears about an agent is part of the agent's spec, under **Limits → Alerts**.
A deployment-wide audience made the noisy agent and the one nobody may miss the
same setting, so the only way to quieten the first was to go deaf to the second.

| Alert | Fires when | Default audience |
|---|---|---|
| **Budget** | this agent reached its own monthly cap | the admins and the agent's owner |
| **Approvals** | a tool call parked | whoever started the run, plus the admins |
| **Usage** | weekly and monthly, what this agent spent | off |

An audience is a list of roles, not addresses:

| Audience | Resolves to |
|---|---|
| `admins` | the organization's owners and admins, **plus the deployment's app admins** |
| `owner` | the agent's owner |
| `initiator` | whoever started the run; nobody, for a run a schedule began |
| `chosen` | exactly the members named alongside it |

Roles rather than addresses because a spec is exported to a client's repository
and outlives the people in it: `admins` still means the right people after a
reorganisation, and it means them in whichever organization the spec is imported
into. A named member who has left contributes nothing rather than raising - an
approval queue must not go silent because one id no longer resolves.

### Two rules that are not negotiable

**A per-person opt-out only ever subtracts.** Each recipient's own switches at
**Settings → Notifications** are applied last. An agent can decide the admins
should hear about it; an admin can still decide they do not want budget mail.
Nothing an agent's author writes conscripts somebody into an inbox.

**The organization's cap ignores the spec entirely.** That limit stops every agent
in the organization and an agent's author cannot raise it, so its alert goes to
the administrators whatever any agent asks for. An agent cannot silence a limit it
does not control.

### Silence is meaningful

An organization that ran nothing gets no report. A weekly "0 runs, $0.00" is the
report people filter into a folder, and then the one that mattered goes there too.

Sending never blocks and never raises into the caller: a run that has already
ended must not fail again because SMTP was down.

## Audit

Actions that change access or spend money are recorded with an actor, and the
actor column is `NOT NULL` - which is why a context with no subject raises rather
than letting the absence travel.

`audit:read` gates reading it. An app admin's bypass is exactly what the trail
exists to hold to account.

## What none of this covers

Worth stating, because a governance page implies otherwise:

- **No rate limiting per agent.** There is deployment-level rate limiting on the
  API, not a per-agent request budget.
- **No content filtering.** What an agent says is what the model said.
- **No egress control on MCP.** A bound server is reached over the network from
  the worker; restricting where that can go is deployment configuration, not a
  setting here.

## Reference

- [Concepts](concepts.md) - spec, version, exposure, run.
- [Permissions](permissions.md) - who may set any of this.
- [Configuration](configuration.md) - the deployment-level settings.
