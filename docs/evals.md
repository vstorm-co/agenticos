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

An agent with no history on a model is estimated at
`EVAL_FALLBACK_CASE_COST_USD` per case, and the estimate says it is a guess
(`basis: "fallback"`). The baseline's cost is part of the total, unless a
recent matching baseline is reused, in which case it costs nothing and the
estimate names the run it reuses.

### The budget it leaves { #the-budget-it-leaves }

An eval spends from the same monthly budgets as live traffic: the agent's cap
and the organization's. There is no separate eval budget. A large dataset can
therefore leave production without budget for the rest of the month, so the
estimate shows what each cap keeps once the run has spent its total:
`agent_after_usd` and `org_after_usd`.

Starting refuses with `402` before anything is written when the total is more
than either cap has left. Confirmation reruns (below) are not part of that
check, because they only happen to cases that flip; the estimate shows the most
they can add as `rerun_ceiling_usd`. Every case is still checked against both
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

## What each case runs as { #what-each-case-runs-as }

Every case is an ordinary agent run with the surface `eval`. It is checked
against the budgets before each model request, its cost is recorded, and it is
listed in Activity, where the surface filter keeps it apart from production
traffic. It runs as the person who started the eval, with their current role,
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

A run is executed in the background, in a worker flow of its own, so it
survives the API restarting. Cases run a few at a time: at most
`EVAL_RUN_CONCURRENCY` per run, and at most `EVAL_ORG_CONCURRENCY` across all of
an organization's eval runs, so a 500-case dataset cannot take every request a
provider allows the organization.

Cancelling (`POST /api/v1/eval-runs/{id}/cancel`, by whoever started it or
anyone who may edit the agent) stops what has not started: cases already running
finish and are kept, and no other case starts. A running run's worker says it is
alive every `EVAL_HEARTBEAT_SECONDS`; one that has not, and whose cases have not
moved, for `EVAL_ABANDONED_AFTER_MINUTES` is failed by the hourly stale-run
sweep, which also frees its slots. A queued run has no worker yet - it waits for
a runner slot - so the sweep gives up on it only after
`EVAL_QUEUED_ABANDONED_AFTER_HOURS`.

## Results { #results }

Every attempt keeps the answer, the calls it made - each marked executed,
blocked, replayed or divergent - every scorer's verdict and reason, its cost,
its tokens and its latency. The answer and calls are copied onto the result,
because a case run has no conversation to keep a transcript in.

Each arm of the run is summarised on two axes, and per tag:

| Axis | Measures |
|---|---|
| Quality | Pass rate over the decided cases, and how many could not be decided |
| Efficiency | Cost per passed case, tokens per case, and latency at p50 and p95 |

A case whose required scorer could not run is **undecided**, never a pass. A
person's verdict in the [review queue](datasets.md#review) replaces the
scorers' outcome for that case, and the run's numbers follow it.

```text
GET /api/v1/agents/{agent_id}/eval-runs      an agent's runs, newest first
GET /api/v1/eval-runs/{id}                   one run, with each arm's summary
GET /api/v1/eval-runs/{id}/cases             cases and every attempt; ?outcome=, ?tag=, ?arm_id=
GET /api/v1/eval-runs/{id}/comparison        a candidate arm against its baseline
```

## Comparing with a baseline { #comparing-with-a-baseline }

A comparison matches the two sides case by case on the case's stable id, and
reports each case as a **regression** (passed, now fails), **fixed** (failed,
now passes), unchanged, or incomplete. Cases only one side answered are counted
as not compared.

**The default baseline is cheap**: the last completed run of the same dataset
on the version before the candidate - the published version, for a draft.
Both sides are labelled with their date, model and dataset version, because the
two may differ in any of them.

### A baseline in the same run { #a-baseline-in-the-same-run }

When a decision rests on the result - a promotion gate, a proposed change
checked with evals, a model comparison - the baseline runs **in the same run**
(`paired_baseline`, and always for `purpose: "gate"`). Providers drift between
days, and a regression measured against last week's answers may be the
provider's, not the agent's.

A completed baseline arm stands in for running one only when its version,
dataset version, model, scoring and judge all match, and it finished within
`EVAL_BASELINE_CACHE_HOURS`. The run says which run it reused.

### A flip is confirmed before it counts { #a-flip-is-confirmed-before-it-counts }

A case that flipped is rerun `EVAL_RERUNS` times (2 by default) when the first
answers are in. A regression is **confirmed** when every rerun of the candidate
fails again and, for a baseline in the same run, every rerun of the baseline
passes again; otherwise it is reported as **unconfirmed**. A fix is confirmed
the same way. A past baseline cannot be rerun, so only the candidate side
confirms against it.

### Too few flips are not a verdict { #too-few-flips-are-not-a-verdict }

The verdict rests on the confirmed flips only, tested with an exact McNemar
test. When the test cannot tell the two sides apart at `EVAL_SIGNIFICANCE`, the
verdict is `inconclusive` - the difference is within noise, or the sample is
too small - rather than better or worse. There is no minimum number of cases;
a small dataset simply reports inconclusive more often. With no confirmed flip
at all the verdict is `no_difference`.

### A different judge invalidates the comparison { #a-different-judge-invalidates-the-comparison }

Every score records the [judge that graded it](datasets.md#judge): its model,
its version and a fingerprint of the rubric. When the two sides were scored
with different scoring settings, or graded by a different judge, model or
rubric, the comparison is `invalid` and gives no verdict - a flip there says
something about the grading, not about the agent.

### Two axes, quality first { #two-axes-quality-first }

The verdict is about quality. Efficiency is reported beside it, never folded
in: cost per passed case, tokens and latency are each `better`, `worse` or
`unchanged`, where a change within `EVAL_EFFICIENCY_TOLERANCE` is unchanged.

## Comparing models { #comparing-models }

Naming several `model_profile_ids` runs the candidate once per model in the
same run, each as an arm of its own. Each arm reports its pass rate, cost and
latency side by side. With a baseline in the same run, the baseline runs on the
first model named, and every arm is compared with it.

## Settings { #settings }

| Setting | Default | What it decides |
|---|---|---|
| `EVAL_RUN_CONCURRENCY` | `3` | Cases one run executes at once |
| `EVAL_ORG_CONCURRENCY` | `6` | Cases one organization executes at once, across its runs |
| `EVAL_RERUNS` | `2` | Reruns of a flipped case; a run can ask for 0 to 5 |
| `EVAL_BASELINE_CACHE_HOURS` | `24` | How old a matching baseline may be and still be reused |
| `EVAL_SIGNIFICANCE` | `0.05` | The level below which confirmed flips are a verdict |
| `EVAL_EFFICIENCY_TOLERANCE` | `0.05` | A relative change in cost, tokens or latency counted as none |
| `EVAL_FALLBACK_CASE_COST_USD` | `0.05` | The estimate per case on a model with no history |
| `EVAL_ESTIMATE_SAMPLE` | `50` | How many recent runs the estimate averages |
| `EVAL_ABANDONED_AFTER_MINUTES` | `30` | How long a running run may stand still, its worker silent, before the sweep fails it |
| `EVAL_HEARTBEAT_SECONDS` | `60` | How often a working run says it is alive |
| `EVAL_QUEUED_ABANDONED_AFTER_HOURS` | `24` | How long a run may wait for a worker before the sweep fails it |

## Access { #access }

Starting a run needs `datasets:run` on the dataset and `agents:run` on the
agent, each resolved with the resource's grants. Running the draft also needs
`agents:edit` on the agent, because the draft is the editors' work in progress.
The judge, when one scores the dataset, needs what
[scoring](datasets.md#scoring) says.

Reading a run needs `runs:view`, and that the reader can see both the agent and
the dataset - a run over a dataset the reader cannot open is not listed, and
asking for it by id answers `404`, as a run of another organization does.

## What a run keeps { #what-a-run-keeps }

A result holds the agent's answer and the arguments of every call it made, so
it can hold personal data from the case it answered and from the recording it
was answered from. It is deleted with its run, and a run with its agent or its
dataset; deleting the conversation a case was taken from does not delete
results already produced from it. [Data protection](data-protection.md)
lists it with the other stores.
