# trigger.manual

The manual trigger: a run a person starts by clicking **Run** in the editor or
**Start a run** on the workflow's runs page. It hands the graph the run's input
as `payload` and names the surface in `triggered_by`, exactly as `core.input`
(**API request**) does, and takes the same typed input fields - the editor asks
for them in a form before the run starts.

## Why it is its own trigger

What a builder means by "run it" and "call it" differ even when the run is the
same: a Manual workflow's editor offers **Run** and asks for its fields; an API
workflow's settings show the endpoint and a sample request. Both are started
through the same door, so a Manual workflow can still be started over the API by
anyone who may run it, and both are refused through any other.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `out` | output | `WorkflowInputPayload` | `payload`, typed by the declared fields; `triggered_by` |
