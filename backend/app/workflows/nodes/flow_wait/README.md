# flow.wait

**Wait**: hold the run at this step for a number of seconds after it is reached,
or until a time bound to `until`, then go on. The moment is fixed when the step is
first reached, and the step is parked on a timer whose dispatch row comes due
then: the wait survives a worker restart and holds no worker while it lasts. Other
branches of the run go on meanwhile, and a moment already past goes on at once.

## Why it is durable rather than a sleep

A sleep inside a step would hold a worker for as long as the wait, and a restart
would lose it. Parking the step the way a retry's backoff parks one keeps the
wait in the database, where nothing is lost and nothing is held.

## Limits

A wait lasts at most thirty days. The run's own deadline still applies: a wait
that outlasts it ends the run with `DEADLINE_EXCEEDED`.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | - | the `until` binding |
| `out` | output | `FlowWaitOutput` | `waited_until` |
