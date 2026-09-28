# error.handle

Routes a failure. Connect a node's `error` port (available once that node's
policy sets `on_error: route`) to this node's `in` port. The failure leaves by
the first branch whose conditions both match: `code` equal to the error's code,
and `retryable` equal to whether it was retryable. A condition left unset
matches anything. A failure no branch matches leaves by `default`, and a graph
whose `default` port is not connected cannot be published.

```json
{"branches": [{"name": "not_found", "code": "NOT_FOUND"},
              {"name": "transient", "retryable": true}]}
```

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | `WorkflowError` | the failure being handled |
| `default` | output | `HandledError` | the error, `branch: "default"` |
| one per branch | output | `HandledError` | the error, `branch: <name>` |

Downstream nodes bind to the error's `code`, `message`, `details` and
`retryable`. They never see the failed node's normal output, which does not
exist on this path.

## What cannot be handled

A principal who lost access to the workflow or to what a step uses, a spent
budget, a cancelled run and an effect of unknown outcome are never routed.
They end the run however the graph is wired.

## Effect kind and retries

`effect_kind="pure"`, `retry_guarantee="idempotent"`.
