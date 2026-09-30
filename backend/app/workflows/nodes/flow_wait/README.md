# flow.wait

**Wait**: hold the run at this step for a number of seconds after it is reached,
until a time bound to `until`, or until the run's resume link is called, then go
on. The moment is fixed when the step is
first reached, and the step is parked on a timer whose dispatch row comes due
then: the wait survives a worker restart and holds no worker while it lasts. Other
branches of the run go on meanwhile, and a moment already past goes on at once.

## Why it is durable rather than a sleep

A sleep inside a step would hold a worker for as long as the wait, and a restart
would lose it. Parking the step the way a retry's backoff parks one keeps the
wait in the database, where nothing is lost and nothing is held.

## Waiting for a call

With `until_called`, the step parks the same way, its time the longest it waits
(thirty days when `seconds` is unset). A call to the run's resume link - the
address a `flow.resume_link` step hands on - stores its JSON body on the step and
brings the step's dispatch row forward; woken, the step hands the body on as
`body` with `called` true. Its time running out first, it goes on with `called`
false. The call is answered by `app.services.workflow_execution.resume`, which
stores a body only on a step that is waiting and has none, so a second call finds
nothing to resume.

## Limits

A wait lasts at most thirty days. The run's own deadline still applies: a wait
that outlasts it ends the run with `DEADLINE_EXCEEDED`.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | - | the `until` binding |
| `out` | output | `FlowWaitOutput` | `waited_until`, and `called` and `body` for a call |
