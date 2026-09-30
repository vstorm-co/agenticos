# trigger.workflow_call

**Called by a workflow**: the trigger of a workflow other workflows run as a step.
Another workflow's **Run a workflow** step (`workflow.run`) starts its published
version with the input the step bound, as the caller's run acts, and waits for it
to end - or does not, when the step is set to go on without waiting. The run is
linked to the step that called it, and to the calling run's chain.

## Why it is its own trigger

Logic several workflows share - enrich a lead, file a ticket - belongs in one
place rather than copied into each. A workflow that starts only this way cannot be
started by hand or over the API by mistake, and its declared fields are the
contract every caller is checked against before the run starts.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `out` | output | `WorkflowInputPayload` | `payload`, typed by the declared fields; `triggered_by` |
