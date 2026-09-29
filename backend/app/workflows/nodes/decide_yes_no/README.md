# decide.yes_no

Asks TypeSafe's Jev a yes-or-no question about a text and branches on the
answer. The question is `question`; the text is the bound `text`. Jev answers
with a confidence from 0 (a coin flip) to 1, and below `min_confidence` the
step leaves by `unsure` instead of `yes` or `no`.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow; `text` is bound |
| `yes` | output | `YesNoOutput` | the answer was yes, and confident |
| `no` | output | `YesNoOutput` | the answer was no, and confident |
| `unsure` | output | `YesNoOutput` | the confidence was below the floor |

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
