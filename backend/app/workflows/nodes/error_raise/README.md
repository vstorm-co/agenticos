# error.raise

Fails the branch it sits on with an error the author defines: a `code`, a
`message`, optional `details` (which may be bound) and whether a retry policy
may try again. Use it when a run should stop for a reason of your own, such as
a record that breaks a business rule, instead of letting a later step fail on
the same data with a message about something else.

The node has no output port. Its failure is handled like any other node's: it
fails the run by default, it leaves through its `error` port when its policy
routes errors, and inside a loop the loop's item-error policy applies.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | none | control flow |

## Effect kind and retries

`effect_kind="pure"`, `retry_guarantee="idempotent"`.
