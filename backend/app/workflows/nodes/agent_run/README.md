# agent.run

Asks a published agent a question and hands its answer to the next step. The
step pins an agent **and** one of its published versions, and it runs that
version whatever is published later. There is no "latest" option, so a workflow
reviewed against version 4 keeps running version 4 until someone edits the step.

## An agent configured in the step

`inline` holds a whole agent spec in place of `agent`, and exactly one of the two
is set. The agent it describes is the workflow's: `app/services/workflow_agents.py`
creates it on the step's first run (`agents.workflow_id`, `workflow_node_id`),
reuses the newest version while the spec is unchanged, and publishes a new one -
after `validate_spec`, for the run's principal - when it changed. It is kept out of
the catalog and the agent ceiling, and `AgentRegistryService.get` reaches it
through the workflow: viewing and running map to `workflows:view` and
`workflows:run`, and any change is refused, because the step owns the spec.

`max_cost_usd` is a ceiling on one execution, a `BudgetScope.RUN` limit metered on
the run's own ledger and carried across approval and question waits.

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

## Questions

An agent with the `ask_user` capability can call the existing Ask Question tool.
Its step parks with `waiting_reason="question"` and the workflow reports
`waiting_for_user`. The person the workflow runs as sees the question in the
run details or its chat card. Public-origin runs have no person to ask.

Submitting an answer saves its tool result and queues the same step in one
transaction. Dispatch rechecks the workflow's permissions, deadline and budget,
then resumes the same agent conversation. The agent can ask again before
returning its final output. Duplicate identical answers queue one continuation;
answers naming a previous question cannot answer a later one.

The owning step is linked before the first model call. If the process dies
after the child parks but before the step settles, reconciliation restores
that wait and records only cost not already booked. A lost wake is recovered
from saved answers. Other interrupted effects retain `needs_attention` rather
than being replayed. Cancelling the workflow closes parked questions, and an
expired question wakes the step to collect the child's failure.

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
| Awaiting answer | Waits for its person, then resumes the same run |
| Budget exceeded | `AGENT_BUDGET_EXCEEDED` |
| Guardrail blocked | `AGENT_GUARDRAIL_BLOCKED` |
| Anything else | `AGENT_RUN_FAILED` |

## Effect kind and retries

`effect_kind="write"`, `retry_guarantee="none"`. An agent may have called tools
with side effects, so a failed or interrupted run is never retried
automatically. Cost is reported to the workflow run, and for a resumed run only
what the continuation added.
