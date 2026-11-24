# Eval tool tuning { #eval-tool-tuning }

Score one tool against eval cases that are already judged, and draft tuning
proposals from the failures. A tuning run takes the judged results of an
eval try - the cases the failure-learning loop (#32) tried - and asks how
one tool behaved across them: was it called, was the right tool picked,
did it error, did the answer still miss the mark.

This is the eval-tool-tuning skill as a capability. The procedure lives in
the `eval-tool-tuning` skill
(`backend/app/core/catalog/skills/eval-tool-tuning/SKILL.md`), which says
when to score a tool; this page says what the capability does with the
answer.

## How a tuning run works

The agent calls `record_eval_tool_tuning` with the tool and the judged
cases - each case with what its answer was supposed to say, whether the
judge said it passed, what the answer said, and every tool call the case's
run made. One call is one tuning run: it scores the tool, classifies each
failure, drafts one proposal per failure class, and records the run on the
manifest.

A failure is one of four classes:

| Class | What it means |
|---|---|
| `not_called` | No tool ran on the case - the tool was never reached |
| `wrong_tool` | Another tool was picked instead |
| `bad_arguments` | The tool was called and errored |
| `wrong_answer` | The tool ran cleanly, but the answer still missed the expectation |

Each class drafts one kind of proposal:

| Failure | Proposal | What it changes |
|---|---|---|
| `not_called`, `wrong_tool` | `tool_choice` | Which tool is picked - a routing rule, or preferring this tool over the one that was picked |
| `bad_arguments` | `tool_parameters` | The tool's arguments - their required fields, ranges, and what counts as valid |
| `wrong_answer` | `prompt_wording` | What the answer must say - a line in the agent's instructions |

One proposal per class, not per case: five cases failing the same way are
one tuning problem, not five. A score with no failures drafts nothing.

## Configuration

| Field | Default | What it is |
|---|---|---|
| `max_tuning_runs` | `3` | How many tuning runs one run may record (1–5) |

The cap is what stops repeated scoring from growing the work: score, show
the drafts, let a human decide. A fresh tuning run after a proposal is
applied is a new run.

## The record

Every tuning run is recorded on the run manifest, and renders in the run
drawer:

```markdown
## Eval tool tuning

Tool: search · 1/2 passed · most common failure: not_called

| Case | Classification |
| --- | --- |
| total | passed |
| missing | not_called |

| Proposal | Kind | Evidence |
| --- | --- | --- |
| Route these requests to search | tool_choice | missing |
```

## What it does not do

- **Judge an answer.** The per-case verdict arrives already judged, by the
  failure-learning loop's `judge()` (`app/services/eval_judging.py`,
  shared with workflow evals). Scoring consumes `(passed, shown)` pairs;
  a second judge would drift from the first, and the eval gate would stop
  meaning one thing.
- **Run evals.** Running cases through the test-run path is the loop's try
  runner (#32). Until #32 merges, the tool takes judged cases as its
  input; when #32 lands, its try results feed this tool.
- **Apply a proposal.** Every proposal is a draft with its failing cases
  as evidence, for a human to approve. Applying an instruction change goes
  through the loop's proposal apply (eval-gated, audited); a skill change
  through the learned-skill path (#9). There is no apply function here.
- **Keep tuning runs anywhere but the manifest.** Runs live in the run
  manifest's JSONB, beside the requests. There is no table to migrate and
  no tuning run to query across runs - the loop's own tables hold the
  cases, once #32 lands.

The capability needs no scope: its tool records onto the run's own
manifest and calls no model, delegates nothing, and touches no service.
