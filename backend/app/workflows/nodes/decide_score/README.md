# decide.score

Asks TypeSafe's Jev where a text sits on a rubric: `levels` says what each
level means, from 0 upwards, and every level needs saying. The `score` is the
nearest level and `position` is where between levels the text sat. It leaves by
`out`, or by `unsure` below `min_confidence`.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `text` is bound |
| `out` | output | `ScoreOutput` | the confident score |
| `unsure` | output | `ScoreOutput` | a score below the floor |

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
