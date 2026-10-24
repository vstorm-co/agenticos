---
title: "Eval runs"
description: "An eval run answers every case of a dataset with an agent version or its draft, scores each answer, and compares the result with a baseline."
---

# Eval runs

An **eval run** has an agent answer every case of a [dataset](datasets.md)
version, scores each answer the way the dataset's
[scoring](datasets.md#scoring) says, and keeps what happened. It answers the
question a person editing an agent actually has: did this change make the agent
better, worse, or neither - and what did it cost.

A run is made of four choices: the **agent** and what of it runs (a published
version, or the draft as it stands), the **dataset version**, the
**environment** whose test connections the cases use, and optionally **several
models** side by side. It can also run a **baseline** - an earlier version - in
the same run, so the two meet the same provider on the same day.

## In the console { #in-the-console }

An agent's **Evals** tab opens on a line chart of its pass rate run by run,
oldest on the left, a line per dataset, each with its own dash. A point is red
where the run broke cases, green where it fixed them, amber where it did both,
and hollow for a draft; hovering it says what ran, against what and when, and
clicking it opens the run.

The axis names each point by what ran and when - the time for a run today, the
date before. Past 12 runs a range appears under the chart, starting on the last
12; drag its handles, or move them with the arrow keys, to see more or fewer.

Below it are its runs, grouped by dataset, each naming what was tested against
what, its verdict (Breaks 2, Worse overall · 4 broke, First result, Pending) and
each model's pass rate, with the first answers' rate on hover.

**Run evals** opens the start dialog on the obvious answer: the draft against
the live version when the draft differs from it, the live version alone when it
does not, and the draft alone for an agent nobody published. The dataset the
agent was last measured on - or the only one there is - is already chosen; the
environment, recordings and reruns are under **Advanced**. The cost is worked
out as the fields settle and says what grades the answers and what the agent's
and the organization's budgets keep after it; the run starts only from the
button that names the amount. **Draft differs from vN** on the agent's page -
vN is the latest published version, and when production's guards hold it on an
older one a second badge says which, such as "production on v1 (waiting for
evals)" - carries a **Test draft** button that opens the same dialog. The publish
dialog says what the draft's last run found - a
[check of the assistant's suggestions](authoring.md#check-with-evals) counts once
they are accepted - or that it was not tested since it last changed, or that the
test it had is out of date, without holding the publish back.

A run's page opens on its verdict in a few sentences - the cases the candidate
breaks or fixes every time it is asked, one quoted with how many tries repeated
it, whether it is better or worse overall when the confirmed changes can tell,
and the pass rate before and after - with what to do next:
see what changed between the two versions (History opens on that comparison,
against the spec the run tested rather than the draft as it is now), show the
cases that broke, go back to Build, or publish the draft.

Publish is the main action only when no regression was confirmed and none of the
candidate's cases was left unanswered or ungraded, and a run of a draft that
changed since offers **Test again** instead. While the run answers it says how
many first answers are in and the comparison waits for both sides. Answers the
judge failed to grade say why and count as neither passed nor failed, and
**Grade again** in the header grades them again without asking the agent, for
whoever may run the dataset.

Below the verdict are the sides next to each other, how the two compare, and the
cases - each row with a pass or fail dot per side, filtered by outcome or tag,
each opening onto what the case expects and every side's answers, calls and
scorer reasons. Picking a tag reads the sides, the changes and the cases under
it; the verdict stays over every case.

Once its reruns are in, a run sends to the dataset's
[review queue](datasets.md#review) what it can stand behind - each regression
it confirmed and each answer its judge failed to grade, one per case and agent -
and says how many (`routed_to_review`). A
[check of the assistant's proposal](authoring.md#check-with-evals) sends nothing
by itself, since nothing was accepted.

A judge that was skipped sends nothing: its answers wait on the run's page for
**Grade again**. When sending is refused, the
run still completes and its page says why (`routing_error`). **Send failed to review** sends the rest of one
side's failed answers, for whoever may edit the dataset, and a case whose grade
a person overturned is marked as corrected.

Either way an answer takes the place of an older one of its case and agent still
waiting, which leaves the queue undecided - a run says how many as
`routed_replacing` - and an answer older than the one waiting is not sent.
Another agent's answer to the case waits beside it.

A dataset's own **Evals** tab lists every agent measured on it, each with its
trend and runs, and its header's **Run evals** opens the start dialog on the
dataset, asking which agent to test.

The dashboard's **Eval runs** card lists the organization's latest runs with
their agent and verdict. An eval's cases and the judge's grading are kept out
of every other dashboard figure, and Activity hides them unless its surface
filter asks for every surface or for evals alone. Activity's list shows what
every run was asked - its first user turn, or the eval case's question, and for
the judge's run what it graded - so a run can be found again to become a case.
An eval case there opens its eval run on that case, and a case's **See what the
model saw** opens what its model was given.

The card's **See all** opens **Eval runs**, at `/evals`: every eval run you may
see, across agents, newest first, a page at a time. With none yet, it says what
an eval is and where to start one.

## Starting a run { #starting-a-run }

Starting is two calls, so nothing is spent before somebody has seen what it
will cost.

```text
POST /api/v1/agents/{agent_id}/eval-runs/estimate   the estimate, nothing written
POST /api/v1/agents/{agent_id}/eval-runs            the same body; starts the run
```

The body names the dataset (`dataset_id`, `dataset_version`), the candidate
(`candidate: "version"` with an optional `version`, or `candidate: "draft"`),
the `environment_id`, the `model_profile_ids` to compare, and
`paired_baseline`. The estimate is the agent's average cost per run on each
model, over its recent completed runs, times the number of cases, plus a judge
call per case when a judge scores the dataset and AI assistance is on.

AI assistance is off for an organization until someone with `org:settings`
turns it on. While it is off the judge does not run: a case is decided by its
checks and its expected tool calls, the judge's criteria are recorded as
skipped, and the estimate counts no judge.

An agent with no history on a model is estimated as a typical case -
`EVAL_FALLBACK_INPUT_TOKENS` in, `EVAL_FALLBACK_OUTPUT_TOKENS` out - at the
model's own price, or at `EVAL_FALLBACK_CASE_COST_USD` for a model nothing
prices, and the estimate says it is a rough guess (`basis: "fallback"`). A judge
with no history is priced the same way, on the model its published spec names;
the estimate warns when that is the model being tested, and a run's page when
it was. The baseline's cost is part of the total,
unless a recent matching baseline is reused, in which case its first answers
cost nothing and the estimate names the run they come from.

### The budget it leaves { #the-budget-it-leaves }

An eval spends from the same monthly budgets as live traffic: the agent's cap
and the organization's. There is no separate eval budget. A large dataset can
therefore leave production without budget for the rest of the month, so the
estimate shows what each cap keeps once the run has spent its total:
`agent_after_usd` and `org_after_usd`.

Starting refuses with `402` before anything is written when the total is more
than either cap has left. Confirmation reruns (below) are not part of that
check, because they only happen to cases that flip; the estimate shows the most
they can add - every case flipping, rerun on every side, a reused baseline
included - as `rerun_ceiling_usd`, which the run keeps so a run that spent
past its estimate says why. Every case is still checked against both
caps before each model request, as any run is, and a case that runs into a cap
stops the whole eval run as `budget_exceeded`.

### What is refused { #what-is-refused }

A run that could not tell anybody anything is refused before it is estimated:

- a dataset version with no cases;
- scoring with no required scorer that can decide any case of the version -
  no check to apply, no expected tool call, and no judge. When the judge is the
  only scorer and AI assistance is off, the refusal says so: the judge needs AI
  assistance, which is off for this organization, so turn it on in the
  organization's settings or add a check;
- an agent that was never published, asked for a version - run its draft
  instead;
- a baseline for a first version, which has nothing before it.

A version where only some cases have nothing to grade them still runs, and the
estimate counts them first (`ungraded_cases`): the start dialog, a check of
suggestions and a suite's dialog say "1 case has nothing to grade it. The
result will be inconclusive."

### Checking suggestions { #checking-suggestions }

The [authoring assistant](authoring.md#check-with-evals) starts eval runs to check
what it suggests: the draft with the waiting suggestions applied, beside the
published version. Such a run leaves out the cases taken from the conversations
the suggestions came from and says how many, so a smaller sample than the dataset
explains itself.

## What each case runs as { #what-each-case-runs-as }

Every case is an ordinary agent run with the surface `eval`. It is checked
against the budgets before each model request and its cost is recorded. It is
kept out of the dashboard's usage figures, which count production alone and
report the eval traffic's cost beside it (`cost.eval_usd`), and run history
leaves it out when asked to (`?exclude_surface=eval`). Its single-run read
names the eval run and case it answered (`eval_case`), for a reader who may see
the dataset. It runs as the person who started the eval, with their current role,
and does not read or write their personal memory.

Each case runs **isolated**, as [Environments](environments.md) describes: a
tool with a test connection on the run's environment runs against it, a tool
known to only read runs on the normal connection, and anything that writes without
a test connection is not executed - the call and its arguments are kept as an
intended call, which the trajectory scorer still judges.

A case taken from a conversation can be answered **from the recording** of the
run it came from (`from_recordings`): a call that matches the recording gets the
recorded result, and one that does not is held and marked divergent. A case
without a usable recording runs isolated without one.

### A draft is never counted as a version { #a-draft-is-never-counted-as-a-version }

A draft runs through the same path, with two differences. It is validated
against the starter's own access first - everything a publish would check -
because a draft was never validated when it was saved. And its runs are
attributed to no version: they do not appear in a version's usage, and a
version's numbers never include answers its draft gave.

The draft is copied when the run starts, so every case answers the same
content even if somebody keeps editing.

## Running and cancelling { #running-and-cancelling }

A run is executed in the background, as a job of its own in the worker, so it
survives the API restarting. Cases run a few at a time: at most
`EVAL_RUN_CONCURRENCY` per run, and at most `EVAL_ORG_CONCURRENCY` across all of
an organization's eval runs, so a 500-case dataset cannot take every request a
provider allows the organization.

Cancelling (`POST /api/v1/eval-runs/{id}/cancel`, by whoever started it or
anyone who may edit the agent) stops what has not started: cases already running
finish and are kept, and no other case starts. Cancelling a run's job in
**Admin** → **Background jobs** before a worker took it cancels the run the
same way, within seconds.

A run its worker cannot finish - the database lost mid-run, say - ends `failed`
at once, as an agent run does: its running cases fail, the rest are skipped, and
its page says it stopped on an error and should be run again. It is not resumed.
A run whose job ran out of time, or whose worker shut down under it, ends
`failed` at once the same way.

A worker can also die without a word. A running run's worker says it is alive
every `EVAL_HEARTBEAT_SECONDS`; one that has not, and whose cases have not
moved, for `EVAL_ABANDONED_AFTER_MINUTES` is failed by a sweep the worker runs
every minute, which also frees its slots. A worker whose heartbeats fail that
long - on a host too loaded to reach its database - is failed the same way while
it still works, and its run has to be started again.

A queued run has no worker to say it is alive yet. It may wait for a free
worker, or behind a paused kind of job, for as long as its job is queued; the
sweep fails it once no job is left to run it. A case a dead worker left running
under a run that has already ended is failed after the same
`EVAL_ABANDONED_AFTER_MINUTES`. A running case counts against
`EVAL_ORG_CONCURRENCY` until it ends, also after its run was cancelled.

While a run is queued or running, the environment it names and the model profile
any of its sides runs on cannot be removed: its remaining cases would answer
against production's connections, or on another model than the cases before
them.

## Results { #results }

Every attempt keeps the answer, the calls it made - each marked executed,
blocked, replayed or divergent - every scorer's verdict and reason, its cost,
its tokens and its latency. The answer and calls are copied onto the result,
because a case run has no conversation to keep a transcript in.

Each arm of the run is summarised on two axes, and per tag:

| Axis | Measures |
|---|---|
| Quality | Pass rate over the decided cases, each as most of its tries came out; the first answers' rate beside it; how many were left undecided, and why |
| Efficiency | Cost per passed case, tokens per case, and latency at p50 and p95 |

Every attempt comes out one of four ways (`state` on the attempt):

- **passed** or **failed** on its grade;
- **failed** too when the agent's run failed - a tool that raised, its step
  limit, a loop, a guardrail, a request the provider refused - which fails a
  suite outright, even when the case's reruns pass;
- **incomplete** when the provider failed after its retries (an error 5xx, 408
  or 429, or no answer at all), a scorer raised, the run was cancelled or ran
  out of budget, or its tries tied;
- **ungraded** when nothing grades the answer - no required scorer applies, or
  only the judge could and AI assistance is off.

Neither of the last two is ever a pass; the summary counts them apart
(`incomplete`, `ungraded`).

A run's header says "Pass rate 67% · 1 of 3 cases undecided" and calls the
result inconclusive until every case is decided. A provider that rejects the
credentials is named as such, and a side whose every answer failed with one
error says so instead of a verdict. A case the agent crashed on where the
baseline passed is a regression like any other, shown with its error.

An answer the judge failed on or skipped is **not graded**: the run lists those scores as
`ungraded_score_ids`, and grading them again
(`POST /api/v1/datasets/{id}/scores/rescore`) reads the answer kept on the
attempt rather than asking the agent. A person's verdict in the
[review queue](datasets.md#review) replaces the scorers' outcome for that case,
and the run's numbers follow it.

A finished run keeps its first candidate's verdict, counts and pass rates as
`outcome`, so a listing reads them without comparing every run again. It is
compared again when a person has decided one of the scores it rests on since,
or one was graded again.

```text
GET /api/v1/agents/{agent_id}/eval-runs      an agent's runs, newest first; ?draft=current
GET /api/v1/datasets/{dataset_id}/eval-runs  a dataset's runs over the agents the reader may see
GET /api/v1/eval-runs/{id}                   one run, with each arm's summary and its outcome
GET /api/v1/eval-runs/{id}/cases             cases, what each expects, and every attempt;
                                             ?outcome=, ?tag=, ?arm_id=, ?case_id=
GET /api/v1/eval-runs/{id}/comparison        a candidate arm against its baseline
GET /api/v1/eval-runs/{id}/arms/{arm}/spec   the spec one side ran; needs agents:edit
```

`?draft=current` keeps the runs that tested the draft as it stands now - the
same spec, whatever order its keys were stored in, a check of suggestions since
accepted among them - which is what the publish dialog reads. `?draft=earlier`
keeps the runs that tested another draft since the latest version was published -
a check only once one of its suggestions was accepted: the test the draft has
moved away from. A check measured against the draft itself counts in neither.

## Comparing with a baseline { #comparing-with-a-baseline }

A comparison matches the two sides case by case on the case's stable id, and
reports each case as a **regression** (passed, now fails), **fixed** (failed,
now passes), unchanged, or incomplete. Cases only one side answered are counted
as not compared.

**The default baseline is cheap**: the last completed run of the same dataset
on the version before the candidate - the published version, for a draft.
Both sides are labelled with their date, model and dataset version, because the
two may differ in any of them.

A run may instead name an **earlier run** of the same agent and dataset as its
baseline (`baseline_run_id`), one that completed. Its flips are then rerun
and confirmed against that run - which is how an [eval suite](#suites) checking the same version
every day sees it drift.

### A baseline in the same run { #a-baseline-in-the-same-run }

When a decision rests on the result - a promotion gate, a proposed change
checked with evals, a model comparison - the baseline runs **in the same run**
(`paired_baseline`, and always for `purpose: "gate"`). Providers drift between
days, and a regression measured against last week's answers may be the
provider's, not the agent's.

A completed baseline arm stands in for running one only when its version,
dataset version, model, scoring and judge all match, it ran in the same
environment with the same `from_recordings` and `live_reads`, and it finished within
`EVAL_BASELINE_CACHE_HOURS`. The run says which run it reused. Only its first
answers are reused: a case that flips is asked of it again in this run.

### A flip is confirmed before it counts { #a-flip-is-confirmed-before-it-counts }

A case that flipped is rerun `EVAL_RERUNS` times (2 by default) when the first
answers are in. A regression is **confirmed** when every rerun of the candidate
fails again and, for a baseline in the same run, every rerun of the baseline
passes again; otherwise it is reported as **unconfirmed**. A fix is confirmed
the same way. A baseline in the same run - one that answered here, or one whose
first answers were reused - is rerun beside the candidate, so both sides confirm
a flip the same day. A baseline from an earlier run, compared with when nothing
ran beside the candidate, cannot be rerun, so only the candidate side confirms
against it.

Reruns raise the bar rather than lower it: a flip confirms only when it holds on
every rerun, so more reruns confirm fewer flips. A small or cheap model that
answers a case differently from one try to the next leaves its flips
unconfirmed, and the verdict reads `no_difference` even when the pass rate
moved - that means the model is unsteady on those cases, not that nothing
changed. What helps is more cases in the dataset, a steadier model or a lower
`temperature` in its [model settings](models.md#model-settings), and reading the
unconfirmed cases in the table.

A run's page says so when nothing held but three or more cases changed once, or
the two pass rates are 20 points apart or more.

### What the verdict says { #what-the-verdict-says }

The verdict rests on the confirmed flips only. One confirmed regression makes
the candidate `worse` - a case it breaks every time is reason enough not to
publish - confirmed fixes alone make it `better`, both make it `mixed`, and no
confirmed flip at all is `no_difference`. Each flip names the case's question.

Separately, an exact McNemar test over the confirmed flips gives `overall`:
`worse` or `better` when it tells the two sides apart at `EVAL_SIGNIFICANCE`,
and null when the flips are too few, as they are on most small datasets.

The pass rate counts each case by the majority of its decided tries - its first
answer alone when it was not rerun, and a person's verdict on that answer over
both - so it agrees with the confirmed flips. The first answers' own rate is
kept beside it as `first_pass_rate`.

### A different judge invalidates the comparison { #a-different-judge-invalidates-the-comparison }

Every score records the [judge that graded it](datasets.md#judge): its model,
its version, a fingerprint of the rubric and the version of the judge's own
prompt. When the two sides were scored with different scoring settings, or
graded by a different judge, model, rubric or prompt, the comparison is
`invalid` and gives no verdict - a flip there says something about the grading,
not about the agent. A baseline graded under an earlier judge prompt says so,
and is not reused as a cached baseline.

A run whose judge changed while its cases were graded is `invalid` too: a case
whose tries carry two judges' grades settles by whichever graded more of them.

### Two axes, quality first { #two-axes-quality-first }

The verdict is about quality. Efficiency is reported beside it, never folded
in: cost per passed case, tokens and latency are each `better`, `worse` or
`unchanged`, where a change within `EVAL_EFFICIENCY_TOLERANCE` is unchanged.

## Comparing models { #comparing-models }

Naming several `model_profile_ids` runs the candidate once per model in the
same run, each as an arm of its own. Each arm reports its pass rate, cost and
latency side by side. With a baseline in the same run, the baseline runs on the
first model named, and every arm is compared with it.

## Suites { #suites }

A **suite** is an eval run nobody has to remember to start. It names the
agent, the dataset, the environment whose version it checks and a threshold
every result must meet, and it runs on its own. The **Suites** card sits under
the runs on an agent's Evals tab: each suite's dataset, when it runs, its
threshold and how it last came out. Opening one lists every result, why it fell
short, the cases that broke and a link to the eval run behind it; that run's
page names the suite that started it.

### When a suite runs { #when-a-suite-runs }

Any combination of:

- **On a schedule** - a cron expression read on the wall clock of a time zone,
  so `0 6 * * *` in `Europe/Warsaw` is six in Warsaw either side of a clock
  change. It checks the version its environment serves - the production version
  checked daily catches a provider's model drifting and a knowledge base
  changing underneath it. A fire missed while the worker was down runs once.
- **On publish** - every new version, with the version before it run beside it
  in the same eval run.
- **On promotion** - a version promoted onto the suite's environment (the
  default one when it names none), measured against the version it replaced.
- **When a dependency changes** - a skill or a context file the checked version
  binds is edited, or a document in a knowledge base it searches is added,
  reingested or deleted. Specialists the version defines count as the version. A burst of
  changes is one run, due `EVAL_SUITE_DEPENDENCY_DEBOUNCE_SECONDS` after the
  first. A model profile cannot change in place - pointing an agent at another
  one is a publish - and a provider changing the model behind it is what the
  schedule catches.
- **Run now** - by hand, as whoever presses it.

A suite waiting to check a version absorbs the next trigger for the same
version, so a publish followed by the promotion of that version is one run. A
suite runs one eval run at a time; a change that arrives while it runs waits
for the next one. A paused suite does not run, by any trigger or by hand.

A suite that **guards an environment** also runs before a promotion onto it -
on the version about to be promoted, beside the one the environment serves -
and the promotion waits for it to pass; see
[Guarding a promotion with evals](environments.md#guarding-a-promotion-with-evals).
Its results read *Before promotion* (`gate`). A suite that guards an
environment is pinned to the dataset version and the scoring it had when it
became a guard, so editing the dataset does not change what it checks until the
pin is moved. It cannot be deleted until it is taken off there.

### What a result must meet { #what-a-result-must-meet }

A result **fails** when more cases break reproducibly against the baseline
than the suite allows - none by default, so one confirmed regression fails it -
or when the settled pass rate, each case counted by the majority of its
attempts, falls below the suite's minimum. The McNemar direction is shown
beside the result and never decides it. Two optional ceilings check
efficiency: the rise in cost per passed case and in p95 latency against the
baseline; left empty, they check nothing.

A result whose comparison is [invalid](#a-different-judge-invalidates-the-comparison),
or with any case left incomplete or ungraded, is **inconclusive** - never
passed - unless something failed outright: a confirmed regression, or a
minimum the pass rate misses even were every undecided case to pass. It names
the cases left undecided.

A case the agent crashed on is not undecided: it failed, and like a confirmed
regression it fails the result outright, with or without a minimum or a
baseline - fourteen crashes and one pass also read a pass rate of about 7%.

Republishing the judge changes how answers are graded, so the next result of
every suite it grades for is inconclusive once, and its owner is told. A pass
rate below the minimum fails a result whatever its comparison: the minimum
needs no baseline. A result whose eval run was cancelled is inconclusive too,
and says so; one whose run failed is an error.

A result **did not run** when it would cost more than a budget has left or more than the suite's own ceiling, when only
the judge could grade it and AI assistance is off, or when there is no
published version to check.

Scheduled and dependency runs are compared with
the suite's last passing run of the same version - the last state known to be
good, so a case that broke stays broken until it is fixed - and so measure
drift; a publish or a promotion runs its baseline in the same run. After a
result that could not be compared with that run, the next one has no baseline:
it is held to its own numbers and, passing, becomes the run the ones after it
are compared with.

A [check of the authoring assistant's suggestions](authoring.md#check-with-evals)
run on a suite is held to the same threshold, but it is not a result of the
suite: it is in none of its history and notifies nobody.

### Who it runs as, and who is told { #who-it-runs-as-and-who-is-told }

A suite runs as whoever last saved it - its **owner** - with that person's
authority as it is when the run starts. Nobody watches a scheduled run start,
so saving a suite is agreeing to its spend, and the form prices one run and a
month of the schedule first. Somebody else who changes the suite takes it
over. A suite whose owner leaves the organization, or can no longer run it,
pauses with the reason and says so - as does one whose environment is removed,
paused already or not, rather than quietly checking another version. It resumes
once somebody chooses an environment for it again.

The owner is told when a result fails, is inconclusive or does not run - once
per run of such results on a version, naming the cases that broke or went
ungraded - in the notification
center and by email where they have it on. Slack is not a notification
channel yet.

## Settings { #settings }

| Setting | Default | What it decides |
|---|---|---|
| `EVAL_RUN_CONCURRENCY` | `3` | Cases one run executes at once |
| `EVAL_ORG_CONCURRENCY` | `6` | Cases one organization executes at once, across its runs |
| `EVAL_RERUNS` | `2` | Reruns of a flipped case; a run can ask for 0 to 5 |
| `EVAL_BASELINE_CACHE_HOURS` | `24` | How old a matching baseline may be and still be reused |
| `EVAL_SIGNIFICANCE` | `0.05` | The level below which confirmed flips are a verdict |
| `EVAL_EFFICIENCY_TOLERANCE` | `0.05` | A relative change in cost, tokens or latency counted as none |
| `EVAL_FALLBACK_INPUT_TOKENS` | `2000` | The input tokens a case is priced at on a model with no history |
| `EVAL_FALLBACK_OUTPUT_TOKENS` | `400` | The output tokens a case is priced at on a model with no history |
| `EVAL_FALLBACK_CASE_COST_USD` | `0.05` | The estimate per case on a model with no history and no known price |
| `EVAL_ESTIMATE_SAMPLE` | `50` | How many recent runs the estimate averages |
| `EVAL_ABANDONED_AFTER_MINUTES` | `10` | How long a running run may stand still, its worker silent, before the sweep fails it |
| `EVAL_HEARTBEAT_SECONDS` | `60` | How often a working run says it is alive |
| `EVAL_SUITE_DEPENDENCY_DEBOUNCE_SECONDS` | `600` | How long a suite waits after a skill, context file or knowledge base changed, so a burst of changes is one run |

## Access { #access }

Starting a run needs `datasets:run` on the dataset and `agents:run` on the
agent, each resolved with the resource's grants. Running the draft also needs
`agents:edit` on the agent, because the draft is the editors' work in progress.
The judge, when one scores the dataset, needs what
[scoring](datasets.md#scoring) says.

Reading a run needs `runs:view`, and that the reader can see both the agent and
the dataset - a run over a dataset the reader cannot open is not listed, and
asking for it by id answers `404`, as a run of another organization does. A
dataset's runs also need `datasets:view` on it, and list only the agents the
reader may see.

Setting up, changing, pausing or running a suite needs `agents:edit` and
`agents:run` on the agent, `datasets:run` on the dataset and `runs:view`, and a
person signed in as
themselves: a suite spends as whoever saves it, so neither an API key nor an
administrator acting as somebody can. Reading an agent's suites needs
`runs:view` and the agent; the questions of the cases a result names are shown
only to a reader who may open the dataset.

## What a run keeps { #what-a-run-keeps }

A result holds the agent's answer and the arguments of every call it made, so
it can hold personal data from the case it answered and from the recording it
was answered from. It is deleted with its run, and a run with its agent or its
dataset; deleting the conversation a case was taken from does not delete
results already produced from it. [Data protection](data-protection.md)
lists it with the other stores.
