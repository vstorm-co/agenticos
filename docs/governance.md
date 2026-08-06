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

### Delegation spends the parent's budget

A run can contain another agent's whole conversation - see
[delegate vs inline specialist](concepts.md#delegate-vs-inline-specialist). One run
has **one spend ledger**, and every delegate records into it. That is what makes
the parent's cap see a delegation's spend before its next model request, at
precisely the moment delegation multiplies what a turn can cost. Each entry is
stamped with the delegation that booked it, which is how one ledger still answers
"what did *this* delegate cost" - see below.

It follows that **the caps that bind inside a delegation are the parent's**. A
delegate's own `budget.monthly_usd` is not enforced mid-parent-run: two guards
metering one ledger would double-count every request, and the ceiling that matters
is the one on the run somebody started. The delegate's own cap still governs runs
*of the delegate itself*.

Each delegate prices its own requests, though, because a guard prices what it
records: a delegate on Anthropic metered through a guard built for OpenAI would be
priced against the wrong catalog - silently, and usually as unpriced.

Three further ceilings exist because a budget is a poor way to stop a fan-out - it
only notices after the money is gone. `max_depth` bounds nesting, `max_fanout`
bounds how many delegations run at once, and each delegate's own `max_steps` bounds
its loop. See the
[`subagents` capability](reference/capabilities.md#delegation).

Two of those three are the delegate's own, which is the line the budget does not
cross: `max_steps` is read off the delegate's spec, and its `max_depth` caps how
deep *it* may go however much room its caller had left. A cap on spend is a cap on
the run somebody started; a cap on nesting is a decision the delegate's author made
and its reviewers read, so a caller cannot widen it.

### What a delegated run is recorded as

A delegation to a **published** agent gets an `agent_runs` row of its own, carrying
`parent_run_id` and the delegation's task id. An **inline specialist** gets none: it
has no agent to attribute one to, so its cost is the *run's* and the tool call in
the transcript is the record.

Which run's, though, is the question [#228](https://github.com/vstorm-co/agenticos/issues/228)
answered. A specialist directly under the run's own agent bills to the top-level
row, which is the whole ledger anyway. A specialist under a **published delegate**
bills to *that delegate's* row, not the top-level one - so the delegate's month
includes what its specialist spent, which is the only place it could honestly land.
Each ledger entry therefore carries two attributions: the delegation that made it,
for the panel, and the nearest agent-row it bills to, for the month. The two are
equal for every request a published delegate makes on its own account and diverge
only under an inline specialist - whose panel keeps its own share while its spend
reaches its ancestor's row.

!!! important "The parent's row is the authority; a child's row is its share of it"

    A delegate spends into the shared ledger, and **every entry in that ledger
    carries the delegation that made it**. A delegation's cost is the sum of its own
    entries - the requests its own agent issued, priced once, by the same lookup the
    run's total uses. It is exact in both modes and at every depth, and it does not
    depend on when the delegation happened to be settled.

    It used to depend on exactly that, and it was two defects. The number was the
    *growth* of the shared total across the delegation, so a background delegation -
    settled when it is next polled, which may be after the parent has answered -
    absorbed everything the parent spent in between: a delegate that spent $0.01 was
    recorded at $0.51 if the parent then spent $0.50. And a delegate that delegates
    further had its own delegates' spend inside its window, which their rows record
    again, so its monthly total counted its grandchildren.

    Splitting it with a ledger *per agent* is still the design to avoid - that is
    what stops the parent's cap binding at all. One ledger, attributed, keeps both
    properties: the parent's cap sees every request before the next one, and each
    delegated row says what that one agent spent, its own inline specialists
    included and its published delegates excluded.

    The parent's row remains the authority for the run. Its `cost_usd` is the whole
    ledger, delegates included, which is what the organization is billed; the child
    rows divide that same money by agent and never add to it. `cost_is_partial` is
    per row too: a parent on a model `genai-prices` does not know makes the parent's
    total a floor, and says nothing about a delegate that ran on a priced one.

    A delegated row's `started_at` and `ended_at` are the delegation's **own** span,
    read off the task handle the library stamps when the delegate starts and when it
    ends - not the moment the row was settled. Off the settlement, a background
    delegation read as a zero-duration run at the wrong time, ordered after work that
    finished before it; two that genuinely overlapped were recorded at the same
    instant with nothing to say they had. A terminal handle with an end but no start -
    a delegate cancelled or failed before it began executing - records a zero-length
    span at that end, never a null; and where the library refuses before a handle
    exists at all - an unknown `chat_trace_id` - no delegated row is written. A
    delegation that parked on an approval spans every turn it ran in: its earliest
    start is carried across the park the way its cost is (below), so the row begins
    when the delegate first began and ends when it finally did - not at the resume
    that settled it. The two are not summed the way the cost is; the honest answer
    is the first segment's start and the last segment's end.

**A delegation that parked on an approval is more than one share.** Its turns ran
in different processes against different ledgers, and a resumed turn's ledger is a
fresh object holding nothing from before the park - so what the child row records is
every segment added together: the parked state keeps what the delegation had cost
when it stopped, and the turn that finishes it adds its own share. One row is
written, once, by the turn where the delegation ends - a delegate that parked twice
leaves three segments and one row.

`cost_is_partial` is carried the same way, and for a reason the money does not
share: it is per row now rather than per run, so a delegate that made an unpriced
request *before* the approval and resumed onto a priced model would otherwise have
its row claim an exact cost. The flag is true if it was true of any segment.

That is worth stating because the failure it replaces was invisible. The row used to
hold only what the delegate spent *after* the last resume, which on the ordinary
shape - do the work, then ask permission to act on the result - is the small half.
Nothing failed to add up, because the money was in the parent's row all along; what
was wrong was every number that answers "what did this delegate cost".

The child row is what makes two different questions answerable, and they want
opposite arithmetic:

| The question | Child rows |
|---|---|
| **What does the organization owe?** | **excluded** - the parent's row already contains these tokens, so counting both bills the organization twice for one request |
| **What did *this agent* cost this month?** | **included** - a delegate's rows are the only place its own spend is recorded, and each one holds that agent's own requests and its inline specialists' ([#228](https://github.com/vstorm-co/agenticos/issues/228)) but not its published delegates', which have rows of their own |

The second is what makes "the researcher cost $40 this month" answerable, and it is
what a per-agent usage report or a budget alert on that agent fires on. The
organization's monthly number also carries ingestion spend, which the per-agent
number does not: indexing a shared knowledge base is nobody's agent's spend.

**Every query has to say which of the two it is answering**, and the first column
is the default. The month-to-date figure and the per-agent breakdown behind it
exclude child rows, so they add up to the total printed above them — and the
organization's usage email reports that same total rather than a sum of one of
them. Only a question asked *about one agent* includes them. Three of these five
queries shipped without the distinction and each reported $1.40 for $1.00 of work;
if a new one is added, the default is the safe one.

#### The two vendor questions need a third answer

**By provider** and **by key** cannot use either column, and getting that wrong is
invisible on screen. Excluding child rows totals correctly and then attributes the
delegate's money to the *parent's* vendor, because that is the provider on the row
being summed: an orchestrator on OpenAI delegating $0.40 of work to an agent on
Anthropic reported `openai $1.00` and no Anthropic row at all. Including them
reported `openai $1.00` + `anthropic $0.40` — more than the bill.

So these two sum each run's **own** spend: its cost with its direct delegations'
costs subtracted. `openai $0.60` + `anthropic $0.40`, which is both the right
attribution and the right total. It nests — a delegate that delegated further has
its grandchildren taken out by it, once — and summed over every row it still comes
to the bill, because each child's cost is added by its own row and removed by its
parent's. A key works the same way, and matters more: a key is what somebody
rotates when a bill looks wrong.

### What run history shows

**`GET /runs` lists top-level runs only, and its `total` counts those.** The same
default as the organization's monthly sum, and for the same reason: interleaved,
the two kinds of row cannot be read down one cost column. A fan-out of three
delegations is one run costing $1.00 on the page and $1.00 on the bill; listed
together it was four rows reading $1.00 + $0.40 + $0.40 + $0.40 next to a
month-to-date figure of $1.00, and both halves were right about a different
question.

The list takes the same two-sided arithmetic as the sums above, for the same
reason — so a surface narrowed to one agent shows what *that agent* did, delegate
work included:

| Ask | Answer |
|---|---|
| `GET /runs` | Runs somebody started. `parent_run_id IS NULL` |
| `GET /runs?agent_id=<id>&include_delegations=true` | One agent's own history. What the Builder's Recent runs panel and Activity's `?agent=` ask, because a delegate's rows are the only record of what it itself did |
| `GET /runs?parent_run_id=<id>` | What that run delegated — the query `agent_runs_parent_run_id_idx` exists for. Takes precedence over `include_delegations` |
| `GET /runs/<id>` | One run, delegated or not. Where a link from a transcript lands |

The last two are `?run=<id>` on the Activity page: one run, the delegations under
it each badged with the task id its `subagent_*` frames carried, and a link up to
the run a delegation was charged to. A delegation panel in a chat links there with
the `run_id` its terminal frame carries — which is why the frame carries one.
Nesting delegated rows inside the top-level table is deliberately *not* done here;
a table primitive shared by the whole product is
[proposed separately](https://github.com/vstorm-co/agenticos/issues/139), and
nesting belongs in that rather than in one bespoke run table.

### What the cost screen shows

`GET /spend` takes its window two ways, because the page asks for both kinds:
`days` for the *last N days* presets, and `from`/`to` for *this month*, *last
month* and a calendar range. `from` wins when both arrive — an explicit range is a
more specific request than a default nobody changed — and `period_days` comes back
null in that case rather than repeating a number the range contradicts.

**Every panel on the screen reads the same window.** The per-agent rows, By
provider and By key all take the resolved `since`/`until` rather than a day count
of their own, so two figures beside each other cannot end up describing different
runs. That is the same defect #198 names one panel further up.

**Month-to-date ignores the window entirely**, and so does every per-agent cap
measured against it. A monthly ceiling compared with a rolling seven days reads as
20% used on the day the cap was actually reached.

Each per-agent row carries **two cost figures under two different names**, which is
this page's rule throughout:

| | |
|---|---|
| `cost_usd` | Its share of the window, **top-level runs only**, so the column sums to the total above it |
| `month_to_date_usd` | Its **own** calendar month, delegated rows **included** — the spend its `monthly_cap_usd` is a cap on. It does not sum to the organization's month and is not drawn as if it did |

`partial_run_count` says how much of any of it is a fact: how many runs in the
window had a model with no price, so the cost is a floor by exactly that many.
*"3 of 40 runs could not be priced"* is something a reader can act on; a figure
wearing a plus sign is not.

A row is **one per agent**, with `agent_name` on it. It used to be one per agent
*and model*, carrying only `model_label` — so the tab listed model names where a
reader expects an agent, and split one agent across two rows for having answered on
two models. The per-model shape survives where it is the question being asked: the
usage email still groups that way.

### Narrowing the approvals queue

`GET /approvals` serves two views of the same rows. Pending only by default, which
is the queue somebody acts on; `?status=approved&status=rejected` is the record of
what was decided, and it carries the decider's name and note because a bare UUID is
not an accountability trail. There are deliberately no controls on a decided row.

| Parameter | |
|---|---|
| `status` | Repeats. Absent means pending — the queue |
| `triggered_by_user_id` | Whose runs parked the call. Read off `agent_runs`: an approval belongs to a run and a run belongs to a person |
| `created_from`, `created_to` | When the call was parked, inclusive both ends |
| `oldest_first` | Defaults to true, and the default is load-bearing — see above: nothing ages a call out, so newest-first would bury the row that most needs seeing |

Each row names three things that live in other tables — the agent, the person whose
run parked the call, and the person who decided. The agent and the run are inner
joins because both foreign keys cascade, so an approval cannot outlive either; the
two people are outer joins, because a decision has to survive its decider's account
being deleted and a widget's visitor is anonymous to begin with.

### Narrowing run history

| Parameter | |
|---|---|
| `status` | Repeats. `?status=failed&status=budget_exceeded` is the show-me-the-problems query, and the two are separate statuses precisely so that asking for one is not asking for the other |
| `surface` | Where the run came from |
| `user_id` | Who the run ran **as**, which is not always who asked — a widget's runs carry the widget owner's identity, because the visitor is anonymous |
| `started_from`, `started_to` | Inclusive both ends, because a range picker hands over whole days |
| `environment_id` | Runs on the version that environment pins. **Never a delegated run:** a delegate's version comes from a pin, so the column is deliberately never written on one, and narrowing to `production` drops every delegation. A surface that includes delegations has to say so |
| `exposure_id` | Runs admitted through one binding. Null for the dashboard, the playground and the API |
| `agent_version_id` | Runs that executed one frozen spec — the version strip's "show me the rows behind this number" |
| `took_over_ms` | Only runs slower than this. A run that has not finished has no duration and is excluded, not counted as zero |
| `rated` | `down` or `up` — runs where somebody rated a message the run produced |
| `order_by`, `descending` | `started_at` (the default, newest first) or `duration` |

**Every filter narrows the count as well as the page**, so `total` always
describes the rows under it. The list and the count are two queries, and a filter
reaching only one of them reads as a paging bug rather than as a missing clause.

`started_from` is also what makes that count reconcilable with the money beside
it. Unwindowed it reads *all time* while a spend figure reads one calendar month,
so an organization three years old showed "8,412 runs" next to "$31.20" and the
obvious reading of the pair was wrong by three years. A figure and a spend figure
on one screen share one window, or they say which window each is.

A value outside its type is refused with a 422 rather than matched against
nothing: `status` and `surface` are string columns, so `?status=complete` would
otherwise answer with an empty page — and an empty page reads as *nothing went
wrong this week*. `order_by` takes one of two orders rather than a column name,
for the same reason plus one more: an `ORDER BY` assembled from a query string is
an injection surface.

**Duration is computed in SQL, over the whole narrowed set.** That is what gets
from *"p95 is 14.8s"* on the dashboard to **those runs** — sorting one page of
twenty-five sorts the wrong set, because the slowest run of a month is not in
whichever rows a newest-first page happened to return. A run with no `ended_at`
sorts **last in both directions**: it has no duration, and it is not the fastest
run either. How long a *still-running* run has been going is a different question
and this column deliberately does not answer it.

**`rated=down` is the highest-signal queue here** — the answers real people said
were wrong, in their own words. A rating hangs off a message, so this join runs
through `messages.run_id`: two runs in one conversation keep their own ratings,
which is why that column exists rather than a time window over the thread. It is
an `EXISTS`, so a run three people disliked is one row and not three; and a run
one person liked while another disliked matches **both** `up` and `down`, because
both are true of it. Reducing that to one verdict per run would invent a consensus
the rows do not record.

Activity's three figures above the tabs stay the organization's, including the run
count, even when the table below is narrowed to one agent. A per-agent count beside
the organization's month would be two questions under one label — and the per-agent
count is the one that includes delegations.

**An orphaned delegation is reported without its handle.** `parent_run_id` is
`ON DELETE SET NULL`, so deleting the parent leaves a row that correctly starts
counting toward the bill - but a foreign key can only null its own column, and the
stored `subagent_task_id` then names a transcript that went with the parent.
`AgentRunRead` withholds it whenever `parent_run_id` is null, so no surface offers
a delegation handle that reaches nothing.

### A pinned delegate does not move on its own

A delegate is pinned to a version, so its author shipping a fix changes nothing for
its callers until somebody republishes the parent against the new pin. That is the
same guarantee publishing gives everywhere else here, and it cuts both ways: a bug
fixed in a delegate is a bug still live in every parent that has not moved.

The Builder is where that is surfaced - it compares each pin against what the
delegate publishes now and offers to move it - because staleness nothing surfaces is
a bug frozen in place. A pin whose version no longer exists **fails the run** and
names the delegate; never a quiet fall back to the current version.

**Archiving a delegate stops it answering, including as somebody's delegate.** A
pin to an already archived agent is refused at publish, and an agent archived after
it was pinned fails its caller's run by name - otherwise taking an agent out of
service would leave it running indefinitely in the one place nobody looks, and the
author who retired it would never be told.

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

Four properties worth knowing:

- **A parked run is resumable.** Its message history is stored, so the decision is
  applied to the conversation it belongs to rather than starting again.
- **It stays resumable if continuing it fails.** A run is continued on the version
  it parked on, and that version's spec may have stopped building since - a secret
  a binding names deleted, a model profile removed, a capability dropped in a
  deploy, an MCP connection unshared. The spec is assembled before the run leaves
  the approval queue, so a refusal there refuses the *attempt*: the decision
  stands and resuming works again once the spec does.
- **A decided approval cannot be decided twice.** The second decision is refused.
- **Nothing expires a parked call, and the queue says so rather than pretending.**
  There are three states — `pending`, `approved`, `rejected` — and there was a fourth,
  `expired`, which nothing ever assigned: a schema promising a ceiling the product did
  not have. It is gone. Expiry is a designed feature rather than a missing line, because
  what should happen to the parked *run* when its approval lapses — fail it, cancel it,
  ask again — is a decision nobody has made, and inventing one to retire an enum value
  would be the worse mistake. So the queue surfaces the **age** of the oldest wait
  instead, and a call waiting past a day is drawn as the problem it is.
- **`required` works on any capability**, not only side-effecting ones. "This only
  reads, but in my organization somebody approves it anyway" is a real decision
  and is expressible.
- **One model step can park several calls.** A model that answers with two
  side-effecting calls at once - "email the customer and the account manager" -
  parks both, each its own approval row decided on its own. The rows are written
  when the run parks rather than as each call is gated, because the calls run
  concurrently and the run's database session is not concurrency-safe
  ([#169](https://github.com/vstorm-co/agenticos/issues/169)).

### An approval inside a delegation

A delegate's tools are gated by the delegate's own spec, and it reaches the same
queue the parent's caller is already waiting on - a specialist that needs a person
needs the person who is standing there. The entry names the **delegate's** tool and
the arguments it proposed, because the delegate's own gate is what wrote it, **and
which delegate is calling it**. Without that last part the queue says `send_email`
without saying whether the agent somebody is talking to or a specialist called
`researcher` is sending it, which is a queue people approve blind - and in a
delegation the thing being approved is often more consequential than the agent the
reviewer thinks they are dealing with.

Deleting that delegate does not erase the record of what it was authorised to do:
the row keeps the delegate's name and drops only the link to its now-gone agent.
This holds even when the delete lands while the run is still parked, before the
approval row has been written - the deferred write ([#169](https://github.com/vstorm-co/agenticos/issues/169))
resolves the delegates still present and writes a null id for one that vanished,
exactly what deleting it after the row existed would have done.

What the parent's run does is park, rather than be handed something that looks like
a finished delegation. That is worth stating because it used to be otherwise: every
agent built here declares an output type that lets a run end with its parked calls
as *output* instead of raising, and the delegation library used to serialise that
object and hand the parent's model `{"calls": [], "approvals": [...]}` as the
specialist's report, task marked completed. It was the default path rather than an
edge case, and it is fixed in the pinned version.

Approving it **continues the delegate**, rather than delegating again. The parked
state is a tree - one level per agent, each with its own conversation and its own
parked calls - so granting the approval resumes the suspended delegate from where it
stopped, with the verdict attached to the call the reviewer actually saw. The
parent's `task` call is replayed, and the delegation finds the place it left. A
specialist inside a delegate behaves the same way, one level further down.

That matters because the alternative is not a slower resume, it is a different
answer. Re-running the delegation would start the delegate's conversation from
nothing and let its model call a different tool the second time round, so what a
reviewer approved would not be what executed.

What the delegate had already spent travels with its place, so the row written when
the delegation finally ends covers all of it - see
[what a delegated run is recorded as](#what-a-delegated-run-is-recorded-as). Both
halves of the tree are kept per delegation rather than per run, which is what lets a
specialist three levels down park and still be accounted to its own agent. The spend
is kept even when the delegate's *place* could not be - the library's message history
is best-effort telemetry, and a delegation re-run from the start has still spent what
it spent.

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

The figure in that report is the organization's spend over the window - the same
arithmetic the cap is enforced with, ingestion included and delegated runs counted
once. A report whose total disagrees with the limit the platform enforces is worse
than no report, because both numbers look authoritative.

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
