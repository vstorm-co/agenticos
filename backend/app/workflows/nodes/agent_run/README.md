# agent.run

Asks a published agent a question and hands its answer to the next step. The
step pins an agent **and** one of its published versions, and it runs that
version whatever is published later. There is no "latest" option, so a workflow
reviewed against version 4 keeps running version 4 until someone edits the step.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `prompt` and `sources` are bound |
| `out` | output | `AgentRunOutput` | `text`, `sources`, `artifacts`, `structured`, `agent_run_id` |

`sources` takes passages from `knowledge.search`. They are appended to the
prompt as numbered context the agent cites inline, and passed on unchanged so
`core.output` can return them to the caller.

## It is the agent, as it always runs

The run goes through the same runner as chat and the API. The agent's budget,
approvals, guardrails, tools and run history all apply. The run is recorded
with the surface `workflow` and acts as the workflow run's principal, who must
still be allowed to run the agent. Publishing refuses an agent version the
graph's author cannot run.

## Approvals

When the agent stops on an approval-gated tool, the step waits (the run shows
`waiting_approval`). After the decision in the approvals queue, the step
continues **the same** agent run, so the decision applies to the call that was
shown. The prompt is never sent to a fresh run.

## Structured answers

An agent with an **Answer format** of its own hands its object on as
`structured`. Set `structured_output_schema` to ask for another shape: the
agent runs with that JSON Schema in place of its own, the model answers with an
object of it, and an answer that breaks it is sent back to be fixed. The object
is checked once more before the next step runs, naming the path and the rule
broken but never the answer. An agent that never fits fails the step with
`AGENT_RUN_FAILED`; an answer with no object where one was asked for fails it
with `STRUCTURED_OUTPUT_MISMATCH`. Nothing downstream, such as a table write,
sees an answer of the wrong shape.

## Failures

| Agent run ended | Step |
|---|---|
| Completed | `Completed` |
| Awaiting approval | Waits, then resumes the same run |
| Budget exceeded | `AGENT_BUDGET_EXCEEDED` |
| Guardrail blocked | `AGENT_GUARDRAIL_BLOCKED` |
| Anything else | `AGENT_RUN_FAILED` |

## Effect kind and retries

`effect_kind="write"`, `retry_guarantee="none"`. An agent may have called tools
with side effects, so a failed or interrupted run is never retried
automatically. Cost is reported to the workflow run, and for a resumed run only
what the continuation added.
