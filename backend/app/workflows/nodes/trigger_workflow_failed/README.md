# trigger.workflow_failed

**On failure of a workflow**: the trigger of an error workflow. A workflow whose
settings name a published workflow starting from this trigger starts it once for
each of its runs that ends failed - a real run, not a test of the draft. The run
hands on what failed: the run's id, its workflow's id and name, the step that
failed by id and name, and the error it ended with.

## Why it is its own trigger

A failure has to reach somebody even when no step routes its errors. Making it a
workflow of its own, rather than a notification setting, lets the response be
whatever the team needs: a message to a channel, a ticket, a row in a table, an
agent asked what went wrong.

## What it never does

A run this trigger started never starts an error workflow when it fails, so an
error workflow that fails cannot start itself, or another, in a loop. The error
workflow runs as the member who chose it in the settings, who must still be able
to run it when the failure comes; otherwise nothing starts.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `out` | output | `WorkflowFailedTriggerOutput` | `run_id`, `workflow_id`, `workflow_name`, `step_id`, `step_name`, `error` |
