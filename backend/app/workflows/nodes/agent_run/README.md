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

Set `structured_output_schema` to a JSON Schema, and the agent's final text must
be a JSON object that satisfies it. It is checked before the next step runs. A
mismatch fails the step with `STRUCTURED_OUTPUT_MISMATCH`, naming the path and
the rule broken but not the answer. Nothing downstream, such as a table write,
sees an answer of the wrong shape. Tell the agent in its instructions or the
prompt to answer in JSON.

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
