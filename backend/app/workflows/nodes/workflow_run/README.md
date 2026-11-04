# workflow.run

**Run a workflow**: run another workflow as a step. The step starts the chosen
workflow's published version - one that starts from **Called by a workflow** -
with the bound `input`, as this run acts, and waits for it to end. It then hands
on the run's `output`, or fails with `CALLED_WORKFLOW_FAILED` and the called run's
error. With **Wait for it to finish** off, it hands on the started run at once and
the called run goes on by itself.

## Why it waits the way it does

A step parked on another run is woken by that run's end, in the same transaction,
so the wake cannot be lost; a run that ended before the step parked is noticed
when it parks. The called run is found by the step's own run, so a retried
dispatch finds the run it started rather than starting a second.

## Limits

A call into a workflow already running further up the chain is refused with
`WORKFLOW_CALL_LOOP`, and a chain deeper than five calls with
`WORKFLOW_CALL_TOO_DEEP`. An input the called workflow's fields refuse fails the
step with the reason, before anything runs.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | `WorkflowRunInput` | `input`, what the called workflow starts with |
| `out` | output | `WorkflowRunOutput` | `run_id`, `status`, and the run's `output` once it has one |
