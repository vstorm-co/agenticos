# Eval tool tuning

Score one tool against eval cases that are already judged, and draft tuning
proposals from the failures. The tuning layer on top of the failure-learning
loop (#32): a tuning run takes the judged results of an eval try and asks
how one tool behaved across them.

## Why it exists

An eval case says what an answer should say; a tuning run says what the
tool did about it. A tool that is never called, a tool that loses to another
tool, a tool that errors on its arguments, and a tool that runs cleanly
while the answer still misses the mark are four different problems, and
each wants a different fix - a routing rule, a parameter constraint, or a
prompt line. Scoring sorts them before anybody writes the fix.

## What it deliberately does not do

- **It does not judge an answer.** The per-case verdict arrives already
  judged, by #32's `judge()` (`app/services/eval_judging.py`). This
  capability consumes `(passed, shown)` pairs; a second judge would drift
  from the first, and the eval gate would stop meaning one thing.
- **It does not run evals.** Running cases through the test-run path is
  #32's try runner. Until #32 merges, the tool takes judged cases as its
  input; when #32 lands, its try results feed this tool.
- **It does not apply a proposal.** Every proposal is a draft with its
  failing cases as evidence, for a human to approve. Applying an
  instruction change goes through #32's proposal apply (eval-gated,
  audited); a skill change through the learned-skill path (#9). There is
  no apply function here, so there is no path that applies one by mistake.
- **It does not store anything of its own.** A tuning run is a plain dict
  on the run manifest (`RunRecorder.eval_tool_tuning_runs`, capped at 10),
  beside the requests it scored. No migration, no new table.

## How it works

One call of `record_eval_tool_tuning` is one tuning run: the tool name,
and every judged case - what its answer was supposed to say, whether the
judge said it passed, what the answer said, and every tool call the case's
run made. The pure module `app/agents/eval_tool_tuning.py` scores the
tool (pass rate, per-case classification, dominant failure class) and
drafts one proposal per failure class. The record lands on the manifest;
the run drawer shows it.
