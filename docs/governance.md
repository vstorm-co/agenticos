# Governance

Budgets, approvals, alerts and the audit trail. The four things that make an
agent platform something you can put a credit card behind.

All of them apply identically on every surface, because every surface goes through
one runner.

The newest of those surfaces is a **trigger**: an agent running itself on a schedule
or on an incoming event - a GitHub issue, an inbound email (see
[Concepts](concepts.md#trigger)). It changes none of what follows - it spends against
the same two caps, parks on the same approval gate (routed to its creator, the member
it runs as, and the administrators), and is recorded in the same audit trail. The one
thing "unattended" adds is what happens to a *refusal*: a fired run the budget stops
ends `budget_exceeded` and waits for the trigger's next fire rather than being retried,
and a fired run the creator may no longer make - they left the organization, or lost
their grant on the agent - disables the trigger and writes an audit entry saying why.
A fired run that fails on the model itself - a provider outage, a revoked key - is the
same: recorded `failed` and left for the next fire rather than failing the heartbeat
into retrying the same wall, with the trigger's `last_run_id` left pointing at it so its
history stays honest. A refusal a heartbeat retried every minute would be a bill, or an
alert, that never stops. What is *not* swallowed is a failure that never became a
record: if the run reached a terminal state but the write recording it did not commit -
a transcript or conversation-state write that raised after the answer was in hand - the
fire fails the flow rather than reporting success, so the half-written run rolls back
instead of being committed as complete with nothing behind it. An event trigger adds one more refusal at its edge: a webhook
whose signature does not verify against the trigger's own secret is a 403 that never
reaches the runner at all.

## Budgets

Two levels, and they are not variations on one number.

| Level | Set in | Meters | Raised by |
|---|---|---|---|
| **Agent monthly** | the agent's spec | that agent's own runs | whoever may edit the agent |
| **Organization monthly** | organization settings | every run *and* ingestion in the organization | whoever holds `budgets:manage` |

A **new organization starts with the organization ceiling already set** — the
deployment's `DEFAULT_ORG_MONTHLY_BUDGET_USD` ([configuration](configuration.md),
$100 out of the box) — so a fresh tenant is not one runaway agent away from a
surprise bill. It is an ordinary cap from that point on: editable on the org's
row, and enforced exactly like a hand-set one. A deployment that would rather
start uncapped leaves that setting empty; either way an existing organization's
cap is never changed for it.

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

Both caps are readable where their spend is: the organization's on its own row
(`GET /orgs/{org_id}`), and each agent's as `budget_monthly_usd` on the agent
listing - the *published* version's number, since that is the one the runner
enforces, not whatever the draft currently promises. The dashboard's headroom
card joins these against `GET /spend`, so a cap can be seen approaching before
`budget_exceeded` starts appearing in run history.

### Enforcement is before the request

Checked *before* each model request, not after. Checking afterwards means the
request that broke the budget was already paid for, and a loop can overshoot by
one expensive call every time.

!!! important "A failed run still records what it spent"

    A budget that ignores failures is not a budget. Accounting happens in a
    `finally` block on every surface, and the commit is explicit rather than left
    to the session context - which rolls back on any exception and is never
    reached at all on cancellation.

The guard is a hard stop for a run that *sees* the spend, and a run's own cost
only lands on its row when it finishes. So the baseline a run reads is the sum of
runs that have already finished, and concurrent runs are invisible to one
another: fifty runs starting together against an organization one call short of
its cap each read the same under-cap baseline and each proceed, overshooting by
up to their combined cost. This is a property of an aggregate with no single row
to lock - unlike the per-run and per-loop overshoot above, which the
before-the-request check does bound - and it is why the cap is a ceiling on
committed spend rather than a gate that serialises simultaneous runs. A
deployment that needs a strict cap runs its agents through one queue rather than
in parallel.

### A run costs more than its model requests

A knowledge search embeds the question before it can search it, and that embedding
is billed to the run that asked for it. The embedding service is process-global -
it serves every run and every ingestion job at once - so it books against whichever
run is *currently metered* rather than taking a budget as an argument.

Which makes the meter something a surface can forget, and forgetting it is silent:
no exception and no warning, just a run that reports less than it spent and an
organization's month that never sees it. So the meter belongs to the prepared run
rather than to the surface. Opening one is not a step a new surface has to know
about, because there is no way to execute a prepared agent without it.

[Context management](reference/capabilities.md#context-management) is the other
one. Its summarizing strategy writes the summary through an agent it builds
itself, so that request passes no budget guard; the capability books what it cost
against the same meter. Being *outside* the guard has one consequence worth
knowing: the spend is recorded rather than refused, so a compaction that crosses a
cap stops the run on the request after it.

### A cost that could not be measured says so

`genai-prices` does not know every model. When a run reaches one it has no entry
for, that request is booked at zero and the run is marked `cost_is_partial` — the
total is short by exactly what those requests cost, and the honest reading of it
is a **floor**.

That flag now travels the whole way down. It is on the run row, on the message
row a turn writes, and on the total a conversation reports; every surface that
draws money draws `≥` in front of it rather than a figure that reads as exact.
Null on a message written before the column existed means *not recorded*, which
is not the same claim as "exact" — a client marks only what it knows.

**Every surface records it now, and each turn records its own share.** A message
written by a channel, the API or the widget carried no cost at all until
recently, so a Slack thread could not be totalled. The number written is the
*difference* from what that run's earlier turns already claim, not the run row's
figure: a run row is cumulative, and a run that parked and was resumed writes two
assistant turns — stamping both with the row would count the parked half twice.
The messages of a run therefore sum to exactly what the run says it spent.

**A turn the run was stopped part-way through says so.** A cancelled run leaves
whatever the agent had written when the socket closed or `stop` was pressed, and
that reads exactly like a finished answer — so a reader takes a truncated one as
everything the agent had to say, and the money it spent looks like it bought that.
The transcript carries the run's status per turn, and the chat marks it.

### How full the context window is

The third ceiling, and the one nobody sees coming. A budget refuses with a
message somebody can act on. A workspace refuses a write. A **context window** is
refused by the provider, mid-answer, and the run simply fails.

Every agent therefore carries a gauge — not only one with
[context management](reference/capabilities.md#context-management) bound, because
the warning matters most to the agent that will *not* compact. It reports how
many tokens the last request of a turn carried, *after* any compaction: the
reading falls when compaction works, because it measures what went out rather
than what the conversation holds.

The number is the provider's own `input_tokens`, not an estimate of the history.
A character count cannot see the tool definitions, and those are billed on every
request — thousands of tokens on an agent with knowledge, a sandbox and
delegation, which is a third of the real figure missing at exactly the moment the
figure matters.

**The count is stored on the turn; the share is not.** How much history there is
survives a model change; what fraction of a window that is does not, and the chat
lets somebody switch model between turns. A 500,000-token history is half of a
1M-context model and 390% of a 128K one — and the second is a request the
provider refuses outright. A share frozen with the reading would still read
"50%". So the denominator is resolved where the selection is known, from the
model profile's own recorded window and the pricing registry behind it; where
neither can say, no share is drawn at all, because a percentage against an
assumed window is a guess presented as a measurement.

That switch is also what compaction is for. Its trigger is a **fraction resolved
per request** against the model the request is going to, so a history that sat
comfortably in the old window is compacted on the very next turn under the new
one — before the request leaves, not after the provider has refused it. An agent
with no compaction bound has the gauge instead, and nothing else.

**The trigger measures what the provider measured.** It anchors on the most recent
answer carrying provider usage — that request's `input_tokens` counted the
instructions, every tool schema and every prior message — and estimates only what
came after it. This is why a replayed conversation carries what each answer cost:
without an anchor the trigger counts characters, and a real agent here read 9
tokens where the provider had charged for 3,859. The gauge said 77%; the trigger
saw nothing to do.

**A summary is kept.** Compaction rewrites the messages of one run; the thread
between turns is rebuilt from the transcript, so a summary used to be thrown away
at the turn boundary and the next turn bought another one over a history one turn
longer — two consecutive turns of a real conversation here each paid for a summary
of the same five messages, and the second announced itself as summarising nine. So
the compacted history is written to the conversation, along with how far it
reaches, and the next turn starts from it and replays only what has been said
since. Reopening the thread finds the same thing the model does.

Only a summary is kept. Dropping the oldest messages and clearing tool results
cost nothing to redo, and writing them down would make permanent a loss that is
currently reconsidered against the window on every turn.

One setting cannot work, and says so instead of running. When the instructions and
tool schemas alone are past the trigger, no summary can get under it — they are
not in the history to summarise. Every request would then buy a summary that
changes nothing. Compaction is skipped, the chat says why, and the fix is an
author's: a larger window, or a higher fraction.

That refusal rests on a number a *response* produces, so a turn cannot measure
its own before it has to decide — and a chat turn is usually one request. The
conversation carries the last reading, and a run starts from it. The first turn
of a thread therefore has nothing to go on and compacts as configured; from the
second, the refusal is available. Only the strategies that buy something are
refused: dropping the oldest messages and clearing tool results call no model, so
they run whatever the window is.

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

A failed child row is also held to the parent's rule about what `error` may say.
What raises under a delegate is a model client whose message can carry the failing
request URL — key included, on a custom endpoint — so the row and the delegation's
closing frame store the same controlled sentence the parent's row does, and the
provider's own text goes to the server log. A delegate stopped by its usage limit
or by a budget ceiling keeps the limit's message whole: that is a ceiling doing
its job, not a failure to diagnose.

The rule reaches the *parent's* transcript too. When an agent delegates in the
background it polls `check_task` and `wait_tasks` for the outcome, and what those
answer becomes a tool-call row in the conversation — stored whole, because a tool
return is the tool's own answer rather than something this platform composed. So
they name the exception's class rather than repeating the provider's message,
which is `subagents-pydantic-ai` 0.2.20 and the reason the floor is there.

**The dashboard's windowed figure carries it too.** `GET /stats/usage` answers a
`cost` block for whatever period the filter chose, and that block is runs *plus*
ingestion *plus* retrieval — the same arithmetic the monthly cap is measured with
— with `model_usd`, `ingestion_usd` and `retrieval_usd` beside it so a reader can
see where the money went without subtracting. It reported the model half alone
until 0.0.152, which put two different definitions of cost on one card: the
headline moved with the period filter and counted runs, while the month-to-date
line under it counted the whole bill, and nothing said they were answering
different questions. On a deployment that indexes documents they simply
disagreed.

`retrieval_usd` is what a metered `POST /rag/search` spent on embeddings and
reranking. It shares the `ingestion_spend` table with indexing — both are RAG
spend on no agent run — but a `source` column keeps them apart, so a search is
reported as search rather than inflating the indexing subtotal. Both count
toward the monthly cap all the same.

At `scope=own` the ingestion and retrieval halves are zero rather than a share: a
document is indexed by a worker and a colleague's search records no user of this
window, so charging one person's window for a collection somebody else synced or
searched would be inventing their spend.

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
| `GET /runs/<id>/transcript` | That run's turns, in order - what a run detail view renders as steps. Authorized, not owned (below) |

**Reading a run is authorized, not owned.** A colleague holding `runs:view` reads
a run somebody else started - authority over a run is the organization's, because
a run is what the organization is billed and held accountable for, not the private
property of whoever pressed go. So the decision lives in the service rather than in
a route gate: it resolves the run against the caller's organization first, then
checks `runs:view`. A run in another tenant reads as *absent* - the same 404 an id
that never existed answers with, down to its body - so the response cannot be used
to discover that a run exists. A run that ran with no conversation (an API call
that passed no `conversation_id`) has no transcript to read, and says so with a
null `conversation_id` rather than an empty list that would read as "it did
nothing". None of this widens `GET /conversations/{id}/messages`, which stays
scoped to the owner: a run's transcript being readable by a colleague must not make
the private thread it sits in readable too.

**Each turn the transcript serves carries the ratings people left on it** — the
reading caller's own thumb, the organization's likes and dislikes, and the most
recent down rating's comment. A plain message row holds none of these, so they are
read from `message_ratings` in one batch and attached to the turns; a turn nobody
rated carries them empty and reads exactly as a plain message does. This is what
lets the run detail view show the answers that were rated down and the words left
with them — the conversations behind the dashboard's quality number (#209) — read
where the run is read, rather than only in the app-admin ratings export. The comment
shown is a down rating's, never an up rating's, and the most recent when a turn drew
more than one objection.

### What the dashboard's aggregates show

`GET /stats/usage` takes the same two sides, and the same default. The composed
response is the organization's question, so every block in it counts top-level
rows only: the period cost and its split by provider (the double bill above),
but also the run total, the day series, the outcomes split, the surfaces, the
latency percentiles, the active-people count and the per-person table. Beyond
cost, a delegated row *copies* its parent's `user_id` and `surface`, so counting
it would additionally invent a second person and a second arrival on a channel
somebody used once.

Two aggregates take the other side, and both are asked about one agent:

| Ask | Child rows |
|---|---|
| `by_agent` — the adoption card | **included.** Excluded, an agent that runs four hundred times a day as somebody's delegate has no row, and the card names every published agent without one as forgotten and offers to archive it. Its bars can therefore exceed the run total beside them; nothing sums them |
| `?group_by=version` — the version-compare card | **included.** A specialist that only ever executes as a delegate would otherwise have nothing to compare across its versions |

The invariant that survives either way: the outcomes donut's segments still sum
to `total_runs`, and its `awaiting_approval` segment still counts the same
parked runs as the approvals card, because those three come from the same side
of the switch.

The one query with no delegation filter at all is the count of the caller's
runs parked on a decision. A parked child is a stuck parent, and that card
answers "why is my agent not finishing"; today it changes nothing, because a
delegation is written to the database already finished and so never parks.

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

`partial_run_count` says how much of any of it is a fact: how many **top-level
runs** in the window could not be fully priced, so the cost is a floor by exactly
that many. *"3 of 40 runs could not be priced"* is something a reader can act on;
a figure wearing a plus sign is not.

A run counts when any model in its tree had no price, **its delegates' included** —
the tree shares one spend ledger, so an unpriced delegate makes the parent's row a
floor as well. That is what lets one figure govern all three breakdowns: By
provider and By key sum every row's own spend, delegated rows included, and a floor
in either of them is marked by a count that never looked at the row causing it. It
**measures** By agent, which counts the same top-level rows, and only **marks** the
other two — it counts trees, so one parent with three unpriced delegates reads `1`
while three figures below it are a floor.

A tree that **straddles the start of the window** — the delegate's row inside it,
its parent's row before it — is counted through the delegate: the parent row that
would otherwise carry the mark is outside every aggregate on the page, while the
delegate's own spend is inside both splits. It lands on the agent the delegate ran
as, once per straddling tree however many delegations crossed the edge, and only
when the delegate's own requests went unpriced — a priced delegation under an
unpriced out-of-window parent raises no caveat, because the window's own money is
exact ([#620](https://github.com/vstorm-co/agenticos/issues/620)).

A row is **one per agent**, with `agent_name` on it. It used to be one per agent
*and model*, carrying only `model_label` — so the tab listed model names where a
reader expects an agent, and split one agent across two rows for having answered on
two models. The per-model shape survives where it is the question being asked: the
usage email still groups that way.

**Who spent it is a fourth breakdown**, beneath By provider, By key and By agent —
the one that answers with people rather than vendors or agents. It reads the same
`group_by=user` rows the dashboard's adoption table does — top-level runs only,
busiest first — so a delegate's cost lands once, inside the run that started it, and
it covers the window the rest of the tab shows rather than a rolling default of its
own. Naming the organization's people is the same call the dashboard card makes, so
it takes the same gate: `runs:view`, held by builder and operator as well as the two
stewards, and it says so in its own copy. A caller without `runs:view` does not see
it — the card is absent, and its question is never asked, rather than a request that
comes back refused.

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
| `model_label` | The model **as the run recorded it**, matched exactly. Not resolved through the model catalog: the column is what answered, and a profile it came from may since have been renamed or deleted. The dashboard's model card counts these same strings, so "the runs behind this bar" is one set on both screens |
| `started_from`, `started_to` | Inclusive both ends, because a range picker hands over whole days |
| `environment_id` | Runs on the version that environment pins. **Never a delegated run:** a delegate's version comes from a pin, so the column is deliberately never written on one, and narrowing to `production` drops every delegation. A surface that includes delegations has to say so |
| `exposure_id` | Runs admitted through one binding. Null for the dashboard and the API |
| `agent_version_id` | Runs that executed one frozen spec — the version strip's "show me the rows behind this number" |
| `took_over_ms` | Only runs slower than this. A run that has not finished has no duration and is excluded, not counted as zero |
| `rated` | `down` or `up` — runs where somebody rated a message the run produced |
| `order_by`, `descending` | `started_at` (the default, newest first), `duration`, `cost` or `tokens` |

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
wrong this week*. `order_by` takes one of four orders rather than a column name,
for the same reason plus one more: an `ORDER BY` assembled from a query string is
an injection surface.

**Every one of these travels in the URL**, which is what makes a dashboard card
able to hand over to its own rows: `/runs?surface=mattermost&period=30d` opens
Activity with the facet already set and the count matching the card that linked
it. They were local state until #768, so the p95 figure was the only number on
the dashboard that could reach the runs behind it and three cards carried no link
at all — there was nothing honest to point them at.

**Duration is computed in SQL, over the whole narrowed set.** That is what gets
from *"p95 is 14.8s"* on the dashboard to **those runs** — sorting one page of
twenty-five sorts the wrong set, because the slowest run of a month is not in
whichever rows a newest-first page happened to return. `cost` and `tokens` are
the same arrangement for money and context weight. A run with no `ended_at`
sorts **last in both directions under all three**: it has no duration, it is not
the fastest run either, and its cost and token figures are written only when it
finishes — sorted as stored, a run still going would read as the cheapest and
lightest in the organization. How long a *still-running* run has been going is a
different question and none of these orders answers it.

Activity surfaces that duration three ways, and all three lead to the same query.
The **Took** column header is a sort control — like the Started header beside it,
and like every sortable header in the product — so a click reorders history by
`duration` rather than by the twenty-five rows on screen. A **"slow runs"** canned view is that sort plus a `took_over_ms` threshold
(30s) as one click, and **"all runs"** drops both, back to newest-first — within
whatever window is in view, since the window is a separate axis the p95 link and
the date range set. And the
dashboard's **p95 figure links here**, sorted by duration over the same window: it
carries `?sort=duration` with the period's `started_from`/`started_to`, so the
number and the runs behind it are one click apart — the rule the rest of these two
pages already follow, and the one dimension where they did not (#210).

**`rated=down` is the highest-signal queue here** — the answers real people said
were wrong, in their own words. A rating hangs off a message, so this join runs
through `messages.run_id`: two runs in one conversation keep their own ratings,
which is why that column exists rather than a time window over the thread. It is
an `EXISTS`, so a run three people disliked is one row and not three; and a run
one person liked while another disliked matches **both** `up` and `down`, because
both are true of it. Reducing that to one verdict per run would invent a consensus
the rows do not record.

The same fact rides the row without the filter: `AgentRunRead.down_rated` is
`true` when anybody rated an answer the run produced below zero, computed for a
page in one query rather than an `EXISTS` per row, and it is what run history
draws a 👎 on. Bounded to the caller's organization like every read here — a
neighbour's run, rated down, is never marked for another tenant. The **comment**
that thumb was left with is read in the run detail (`?run=<id>`), not on the row:
it is user-written text about one conversation, and putting it behind the detail
is the deliberate line between a marker anybody with `runs:view` sees and the
words that explain it. That is the join `rated=down` was built for — the dashboard
says quality fell four points, and this is where the conversations that did it are
read.

The trend the dashboard reads is `GET /api/v1/ratings/summary` (a headline split
plus a per-day series): `scope=org` under `runs:view`, `scope=own` for a member's
own conversations, the same scope rule and window vocabulary as `GET /stats/usage`
(see [Permissions](permissions.md)). Counts only — the comments stay behind the
run detail above.

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

### Exporting to CSV

Everything the three tabs show can be taken off the screen as CSV: the rows
somebody reconciles against an invoice, hands to a finance team, or attaches to an
audit. A page that can answer the question on screen and not off it sends people to
the database.

| Ask | Answer |
|---|---|
| `GET /runs/export` | Run history, the same filters as `GET /runs` and the same top-level-only default. `runs:view` |
| `GET /approvals/export` | The approvals record, the same filters as `GET /approvals`. `approvals:decide` |
| `GET /spend/export` | The per-agent spend breakdown, the same window as `GET /spend`. `runs:view` |

The spend export carries only the window figures — `cost_usd`, `run_count` and
`partial_run_count`. The Spend tab's `month_to_date_usd` and `monthly_cap_usd` are
left off it: they read the calendar month while `cost_usd` reads the export's
window, and two dollar columns on two time bases in one downloaded file get summed
across by a reader who cannot see the difference. A downloaded file carries one
time base, the window it was asked for.

An export is a bulk read, not a button, and it answers six questions the list
routes do not have to:

- **Tenancy.** Each export carries the gate of the tab it comes from, and every
  read is scoped to the caller's organization - a neighbour's rows never reach it,
  including a row the caller owns in an organization that is not the one they are
  asking from. The two on `runs:view` also apply a **`Scope.OWN` floor in the
  query**: a caller whose `runs:view` reaches less than the whole organization
  exports only their own rows, `WHERE user_id = <them>`, and a `user_id` they pass
  is overwritten with their own rather than widening it. No built-in role holds
  `runs:view` below `all` yet; the floor is in place for when the member/viewer
  scope decision lands.
- **Size.** An export has no ceiling by nature, so it is given one by design. The
  **date range is mandatory** - a request without both ends is refused - and the
  match is **capped at 10,000 rows**, above which the request is refused with a
  message naming the count and telling the caller to narrow the range. Never a
  silent truncation: a trimmed CSV is worse than a refused one, because a
  spreadsheet sums whatever arrives. The cap is what lets the body be built in one
  pass and the audit entry committed before the response leaves, rather than
  streamed down a held connection.
- **Partial cost.** `cost_is_partial` is its own column on the runs export and
  `partial_run_count` its own column on the spend export, so a floor survives a
  spreadsheet sum. A run whose only model was unpriced exports its real `cost_usd`
  of `0` beside `cost_is_partial=true` - never a bare `0` a reader takes for free.
- **Delegated runs.** The runs export defaults to top-level rows only, exactly as
  the list does, so summing `cost_usd` gives the bill and not double it. The stance
  is in the file, not only here: every row carries a `parent_run_id` column, blank
  for a run somebody started and set for a delegation, so a reader who opts into
  `include_delegations` can see which rows would double-count if summed whole.
- **PII.** Each export ships exactly the identity its tab already shows. The runs
  table shows a `user_id` and no name, so the runs export ships the id alone - a
  CSV of who-ran-what with names resolved is the per-person table decision 3 of the
  activity design refused, arriving as a download. The approvals queue already
  resolves the triggering and deciding emails on screen, so the approvals export
  keeps them.
- **Audit.** Every export writes one `audit_log` entry - a privileged bulk read,
  cheap to record now and impossible to reconstruct later. It names the window, the
  filters that were applied and the row count, never the request body.

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
- **A parked run survives a reload saying so.** The transcript stores the call the
  run stopped on as `awaiting_approval` rather than `running`, so reopening the
  conversation still shows the step waiting — and `GET /runs/{id}/parked` answers
  with the pending calls (the approval to decide, the tool, its arguments), which
  is how the chat rebuilds the approval panel the live
  `tool_approval_required` frame gave to whoever was watching. It answers empty
  for a run that is not parked, and it is gated on `approvals:decide` like the
  queue, because its rows are offered to be decided
  ([#601](https://github.com/vstorm-co/agenticos/issues/601)). The step does not
  read as waiting for ever: a resume settles it with what the call returned, an
  expiry settles it with the timeout notice.
- **A continuation says what it did.** `POST /runs/{id}/resume` answers with the
  tool calls the continuation made, in order, each with what came back — and the
  transcript records them whether or not it reached an answer. Both halves used to
  be missing, and one approval could hide an unbounded amount of work: the agent
  ran inside the resume request rather than on the socket the conversation
  streams, so nothing announced its calls, and the transcript write was skipped
  for a segment with no answer. A run that read a file, then asked to run a second
  command, showed nothing between the two approvals and recorded nothing either.
- **And what the approved call itself returned lands on the step that was
  approved.** It arrives separately from the continuation's own calls (`settled`,
  not `steps`), because it was made by the execution that parked: the resume
  produces its return without the call it belongs to, so it closes a row already
  written rather than opening a new one. Recording it as a step would put the same
  command in the turn twice; not recording it at all — which is what happened
  until it did — made the one call somebody deliberately reviewed the one call with
  no output anywhere.
- **It stays resumable if continuing it fails.** A run is continued on the version
  it parked on, and that version's spec may have stopped building since - a secret
  a binding names deleted, a model profile removed, a capability dropped in a
  deploy, an MCP connection unshared. The spec is assembled before the run leaves
  the approval queue, so a refusal there refuses the *attempt*: the decision
  stands and resuming works again once the spec does.
- **A decided approval cannot be decided twice.** The second decision is refused —
  including a decision arriving a second after the expiry sweep took the call.
- **A parked call is denied by timeout once it passes `APPROVAL_EXPIRY_HOURS`**, and
  the run behind it is settled rather than left parked for ever. The status is
  `expired` with a null `decided_by_user_id`, which is what tells an expiry from a
  rejection in the accountability trail. The Activity page still surfaces the **age**
  of the oldest wait, because a queue under its expiry window is the one somebody can
  still act on.
- **`required` works on any capability**, not only side-effecting ones. "This only
  reads, but in my organization somebody approves it anyway" is a real decision
  and is expressible.
- **Except on a tool the model provider runs, where it is refused at publish.**
  The gate wraps *tool execution*, which is the only place a call can be held, so
  a native fetch or a native search — executed on the provider's side — never
  reaches it, and gating one would leave the queue empty while the agent acted
  unapproved. Which configurations hand which tools over is declared by the
  capability itself (`provider_executed` in its `register(...)`), so the refusal
  covers every capability that grows a provider-executed method rather than the
  ones a validator happened to know about
  ([#857](https://github.com/vstorm-co/agenticos/issues/857)). Choose a method
  this deployment runs itself, or drop the approval requirement; both are
  legitimate agents, and which one is wanted is not a decision to make on the
  author's behalf.
- **And a version published before that refusal existed does not run.** Nothing
  re-validates a frozen version — a run loads its stored spec and assembles it —
  so the same check runs again when the agent is built, and refuses rather than
  quietly swapping the method to make the gate work. The cost is real and
  deliberate: an agent that has been running like this stops, with a message
  saying what to change. What stops is an agent whose operator asked for an
  approval nobody was ever being asked for.
- **One model step can park several calls.** A model that answers with two
  side-effecting calls at once - "email the customer and the account manager" -
  parks both, each its own approval row decided on its own. The rows are written
  when the run parks rather than as each call is gated, because the calls run
  concurrently and the run's database session is not concurrency-safe
  ([#169](https://github.com/vstorm-co/agenticos/issues/169)).

### A decision nobody makes

An approval waits on a person, and some of them wait for ever: the reviewer left,
the tool was asked for on a Friday, nobody knew it was theirs to decide. Nothing in
a request path can end one — the whole premise is that no request is coming — so an
hourly sweep denies by timeout anything still pending past `APPROVAL_EXPIRY_HOURS`
(three days by default, which spans a weekend).

**It is the run that matters, not the row.** An approval left pending keeps its run
in `awaiting_approval` indefinitely: work that is neither finished nor going to be,
sitting in run history and in the oldest-waiting age on the dashboard. So the sweep
follows each expired call down to the run behind it and ends it, `cancelled` —
nobody came back, and what it spent before it parked stands.

Three things it deliberately does not do:

- **It does not continue the run.** A *rejected* call is settled by resuming: the
  denial is replayed and the agent carries on to an answer. That is a model request
  against the organization's own keys, and making one on a schedule, for a run
  nobody is waiting on, is not a cost to incur unasked.
- **It does not end a run with a call still inside its window.** A run parks on all
  of its outstanding calls at once, so it is ended only when none of them is pending.
- **It does not name a decider.** `decided_by_user_id` stays null and so does the
  audit entry's actor, because that is the fact being recorded. Null there means the
  platform on a schedule, and nothing else can produce one.

This is the only read in the codebase that crosses every organization, for the
reason a schedule has no tenant to be scoped to. Every write it makes is still in
the row's own organization.

### A run whose process died

The other state nothing in-process will ever resolve. A run's row is committed
`running` before its model is called ([#12][12-issue]), so a worker killed
mid-run — OOM, a deploy that does not drain — leaves a durable row with nothing
left to finish it: in Activity for ever, and blocking any schedule whose
trigger it was the linked run of. An hourly sweep ends anything still `running`
past `STALE_RUN_REAPED_AFTER_HOURS` (six hours by default; zero switches it
off), as `failed` — nobody stopped this run, the infrastructure did, and an
operator filtering run history for problems is exactly who should see it. The
error on the row is the sweep's own sentence; the process that knew more died.

A run's age here is its **last transition**, not its first start: a resume
keeps the original `started_at` — the run spans both segments — so a run
approved days after it parked ages from the moment its replay began, not from
a start that would have it reaped mid-replay. The ceiling does not have to be
exact either way, because a live run the sweep flips anyway flips itself back:
its own terminal write lands later and wins. What a
reaped run cannot recover is its spend — the ledger died with the process — so
the row keeps the zeros it was opened with rather than being given a number
somebody would reconcile against a bill. And nobody is mailed: the failure
notification rides `finish`, which has the agent and its spec in hand; a sweep
has neither.

[12-issue]: https://github.com/vstorm-co/agenticos/issues/12

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

Actions that change access or spend money are recorded with an actor, and a
context with no subject raises rather than letting the absence travel - so an
entry naming nobody means exactly two things, and the `action` says which: the
approval expiry sweep, and an operator command at the deployment's shell.
Binding a credential to a collection is one of those actions: `sync_source`
entries record creating, cloning, repointing and deleting a source, because the
row decides who ends up able to read what it ingests
([File processing](file-processing.md#who-ends-up-able-to-read-what-a-source-ingested)).
A privileged bulk read is recorded too: each CSV
export writes a `runs.export`, `approvals.export` or `spend.export` entry naming
the window and the row count, because who took the whole table off the screen is a
question that is cheap to answer now and impossible to reconstruct later.

The write shares the acting request's transaction, so it fails closed: an entry
that cannot be recorded rolls back the action it describes rather than letting a
privileged mutation land unaudited.

`audit:read` gates reading it. An app admin's bypass is exactly what the trail
exists to hold to account.

An **impersonated** action names both. When an app admin acts as another account,
the access token carries the administrator as an `act` claim; every entry that
request records keeps `actor_user_id` as the account being acted as and adds
`impersonator_user_id` — the administrator behind it. So "who read this customer's
conversation" resolves to a person even when the action was recorded as the
customer's own. It is null on an ordinary request, where nobody is acting as
anybody else, and nothing is backfilled: whether a past action was impersonated
cannot be known after the fact, and inventing an answer would be a false
accusation rather than a missing one.

## What none of this covers

Worth stating, because a governance page implies otherwise:

- **No rate limiting per agent.** The limits that exist sit on the public
  surfaces — the embed widget meters messages per visitor, a channel bot meters
  each sender ([Channels](channels.md)) — not on the deployment: there is no
  per-agent request budget, and the console's own routes are not metered.
- **No content filtering.** What an agent says is what the model said.
- **No egress control on MCP.** A bound server is reached over the network from
  the worker; restricting where that can go is deployment configuration, not a
  setting here.

## Reference

- [Concepts](concepts.md) - spec, version, exposure, run.
- [Permissions](permissions.md) - who may set any of this.
- [Configuration](configuration.md) - the deployment-level settings.
