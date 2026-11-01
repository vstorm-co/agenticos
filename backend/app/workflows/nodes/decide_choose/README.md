# decide.choose

Asks TypeSafe's Jev which of the step's `options` fits a text - a category, a
queue, an intent. The answer is always one of the options, never an invented
one. It leaves by `out` with the `choice`, its `confidence` and the chance Jev
gave each option in `probabilities`, or by `unsure` below `min_confidence`.
Route on `choice` with an If / else step after it.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `text` is bound |
| `out` | output | `ChooseOutput` | the confident pick |
| `unsure` | output | `ChooseOutput` | a pick below the floor |

## The key

A TypeSafe **API key** from the vault, stored under the TypeSafe service - the
one the browser capability uses too. It is checked at publish against the
graph's author and read again on every run against the run's principal, so a
key deleted or unshared since publishing stops the step with
`SECRET_NOT_USABLE`. A deployment built without the `browser` extra, which
carries the TypeSafe SDK, fails the step with `DECISION_MODEL_UNAVAILABLE`.

## Failures

| Code | Meaning |
|---|---|
| `DECISION_FAILED` | Jev did not answer; retried as the step's policy says |
| `SECRET_NOT_USABLE` | The key is gone, not TypeSafe's, or no longer shared |
| `DECISION_MODEL_UNAVAILABLE` | The deployment has no TypeSafe SDK |
