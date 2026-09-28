# Workflow nodes { #workflow-nodes }

Every step a workflow can contain, with what it is configured with, what it
reads, what it produces and what a failure means. The palette in the editor
lists the same nodes from the same registry. The field documentation below is
generated from the source.

A few rules hold for every node:

- **An edge sets order, and a binding carries a value.** A node's input fields
  are bound to earlier outputs, to a literal, or to a file or table reference.
  See [Configuring a node](../workflows.md#configuring-a-node).
- **A path into a free-form value is checked when the node runs.** A trigger's
  payload, a mapped record and an agent's structured answer have no fixed
  shape, so a binding such as `payload.email` is accepted at publish time and
  validated against its target when the node is dispatched. A value that does
  not fit fails the run with `INVALID_BINDING`, and the handler never sees it.
- **Resources are checked twice.** Publishing refuses a collection, agent
  version, credential or recipient that the graph's author cannot reach. Each
  run checks it again against the run's own principal, because access can be
  withdrawn in between.
- **Effect kind and retries** decide what the engine may do after a failure. A
  `pure` or `idempotent` step is retried. A step that may already have acted
  and gives no guarantee stops for a person instead. A node's own
  [policy](#error-handling) sets how often it is retried, how long a call may
  take and where a failure goes.

## core.input { #core-input }

Where a workflow starts. It hands the graph the run's input as `payload`,
whatever the invoking surface supplied, and names the surface in
`triggered_by`. The input is frozen when the run is admitted, and is at most
`WORKFLOW_RUN_MAX_INPUT_BYTES`.

::: app.workflows.contracts.io.WorkflowInputPayload

## core.output { #core-output }

What the workflow answers. Its bound fields become the run's `output`, which
the API returns and the invoking surface delivers. It has the same fields as
`agent.run`'s output, so an agent's answer binds straight across. An output
with nothing bound is an empty answer.

::: app.workflows.contracts.io.WorkflowOutputPayload

## data.map { #data-map }

Builds a small typed record from earlier outputs. Each mapping reads one value
with a JMESPath expression and converts it to `string`, `number`, `integer`,
`boolean`, `json`, `file_ref` or `table_ref`. A value that cannot be converted
fails with `MAPPING_COERCION_FAILED` and names the field.

::: app.workflows.nodes.data_map._handler.DataMapConfig

::: app.workflows.nodes.data_map._handler.FieldMapping

## logic.if and logic.merge { #logic-if-and-logic-merge }

`logic.if` evaluates a JMESPath condition over its bound `value` and continues
down the `true` or the `false` port. Every node on the untaken branch is
recorded as `skipped`. `logic.merge` rejoins the two branches. It runs once the
taken branch reaches it and passes that branch's output on as `value`.
Publishing checks that a merge's inputs leave one `logic.if` through different
ports, so exactly one of them ever runs.

Expressions can select, filter and compare, and call a fixed set of pure
functions: `abs`, `avg`, `ceil`, `contains`, `ends_with`, `floor`, `join`,
`keys`, `length`, `max`, `merge`, `min`, `not_null`, `reverse`, `sort`,
`starts_with`, `sum`, `to_array`, `to_number`, `to_string`, `type` and
`values`. Null, `false`, and an empty string, list or object are false, and
everything else is true, including `0`. An expression that does not parse, or
calls anything else, cannot be published.

::: app.workflows.nodes.logic_if._handler.LogicIfConfig

::: app.workflows.nodes.logic_merge._handler.LogicMergeOutput

## knowledge.search { #knowledge-search }

Searches knowledge collections for a bound `query` and returns the passages as
typed sources, best first. An empty result is a successful search. A
collection that is gone, or no longer readable by the run's principal, fails
the step with `COLLECTION_NOT_ACCESSIBLE`. The step never searches fewer
collections than the graph names.

::: app.workflows.nodes.knowledge_search._handler.KnowledgeSearchConfig

::: app.workflows.contracts.io.SourceRef

## agent.run { #agent-run }

Asks a published agent, at the exact version the step pins, through the same
runner as chat and the API, with the agent's budget, approvals, guardrails and
run history. The run is recorded with the surface `workflow`. Bound `sources`
are appended to the prompt as numbered context. An approval-gated tool call
parks the step, and the decision resumes the same agent run.

With `structured_output_schema`, the answer must be a JSON object that
satisfies the schema before anything downstream runs. Otherwise the step fails
with `STRUCTURED_OUTPUT_MISMATCH`.

| Agent run ended | Step result |
|---|---|
| Completed | Completed |
| Awaiting approval | Waits, then resumes the same run |
| Budget exceeded | `AGENT_BUDGET_EXCEEDED` |
| Guardrail blocked | `AGENT_GUARDRAIL_BLOCKED` |
| Otherwise | `AGENT_RUN_FAILED` |

It is never retried automatically, because an agent may have called tools with
side effects.

::: app.workflows.nodes.agent_run._handler.AgentRunConfig

::: app.workflows.nodes.agent_run._handler.AgentRunOutput

## http.request { #http-request }

Calls an HTTP API. Every request and every redirect passes the deployment's
SSRF check and is sent to the address that check approved. A credential is an
[HTTP credential](../secrets.md#kinds) from the vault, and it is
sent only to the origins the secret allows. The response is read under
`max_response_bytes` and handed back without `Set-Cookie`, the authentication
headers or the token.

| What happened | Result |
|---|---|
| The URL is private, loopback, metadata or not http(s) | `URL_REFUSED`, nothing sent |
| The URL is outside the credential's origins | `SECRET_ORIGIN_DENIED`, nothing sent |
| The connection never opened | `HTTP_UNREACHABLE`, retried |
| Sent, no answer, `GET` or an idempotency header | `HTTP_NO_RESPONSE`, retried |
| Sent, no answer, any other write | Uncertain: the run stops for a person |
| Non-2xx | `HTTP_ERROR_STATUS`, or the response as output with `on_error_status: complete` |
| Larger than the limit | `RESPONSE_TOO_LARGE` |

::: app.workflows.nodes.http_request._handler.HttpRequestConfig

::: app.workflows.nodes.http_request._handler.HttpAuth

::: app.workflows.nodes.http_request._handler.HttpResponseOutput

## notification.send { #notification-send }

Notifies members of the organization in the app, by email, or both, through
the notification center. Recipients are members named by id. At run time each
one must still be an active member who can see the workflow, and anyone else is
dropped. If nobody is left, the step fails with `NO_PERMITTED_RECIPIENTS`. Each
person's preferences for **Workflow notifications** still apply. The step
completes when the notification is written, and email is delivered afterwards.
A retried step writes no second notification.

::: app.workflows.nodes.notification_send._handler.NotificationSendConfig

## Error handling { #error-handling }

Every node takes an optional `policy` beside its config.

| Field | Default | Effect |
|---|---|---|
| `timeout_seconds` | none | A call still running after this long is cut off. A step with no external write, or one whose call is idempotent, fails with `NODE_TIMEOUT` and may be retried. A write that may have landed becomes uncertain and stops for a person |
| `retry.max_attempts` | `WORKFLOW_RETRY_CEILING` | Tries in total, the first included. Only a failure the node marks retryable is tried again, and publishing refuses more than one try for a step whose call is not safe to repeat |
| `retry.backoff`, `base_delay_seconds`, `max_delay_seconds` | `exponential`, `2`, `60` | The wait between tries: fixed, or doubling up to the ceiling |
| `on_error` | `fail_run` | `route` sends a failure that retries did not settle out of the node's `error` port instead of failing the run |

A node whose policy routes its errors has an extra `error` output port. It
carries the `WorkflowError`: `code`, `message`, `details` and `retryable`. The
node's normal output exists only on its other ports, so publishing refuses a
binding that reads the output on the error path, or the error on the success
path. The error port has to lead somewhere, and the two paths may rejoin at a
`logic.merge`.

`error.handle` takes that error on its `in` port and leaves by the first branch
whose `code` and `retryable` both match, or by `default`, which must be
connected. `error.raise` fails its branch with a code, a message and details
that the author sets.

Some failures are never routed. Revoked access, a spent budget (the run's or an
agent's), a cancelled run, a passed deadline, the per-run node ceiling and an
effect of unknown outcome end the run however the graph is wired. A revision
conflict or a validation error can be routed but is never retried blindly,
because the same input fails the same way again.

::: app.workflows.contracts.policy.NodePolicy

::: app.workflows.contracts.policy.RetryPolicy

::: app.workflows.nodes.error_handle._handler.ErrorHandleConfig

::: app.workflows.nodes.error_handle._handler.HandledError

::: app.workflows.nodes.error_raise._handler.ErrorRaiseConfig

## Loops { #loops }

`control.foreach` runs its body once for every element of a bound `items` list,
one element at a time and in order. It then continues through its `done` port
with `results` in input order, `errors` and `count`. The body starts at
`loop.item`, wired from the loop's `body` port, which provides `item`, `index`
and `count`. It ends at `loop.yield`, whose bound `value` is the iteration's
result. No edge leads back to the loop. A step in the body may bind to anything
that ran before the loop, and nothing outside the body may bind into it.

The list is frozen when the loop starts, so an iteration never sees a source
that changed during the run. A list longer than `WORKFLOW_FOREACH_MAX_ITEMS`, or
larger than `WORKFLOW_FOREACH_MAX_MANIFEST_BYTES`, is refused rather than
truncated. An empty list gives `results: []` without running the body. Each
iteration's steps run in their own scope, with their own attempts, idempotency
keys and costs. The next iteration is scheduled in the transaction that ends the
previous one, so a restart resumes at the right index and never repeats a
confirmed write. An approval inside an iteration resumes that iteration.

With `item_error_policy: stop`, the default, the loop fails at the first failed
iteration and the error's details carry that iteration's `scope_path`. With
`collect`, the item's result is `null`, the error is added to `errors` and the
loop carries on. Loops nest at most `WORKFLOW_FOREACH_MAX_DEPTH` deep, and
every node run a run creates counts against `WORKFLOW_RUN_MAX_NODE_RUNS`. There
is no `while` loop and no parallel map.

::: app.workflows.nodes.control_foreach._handler.ForeachConfig

::: app.workflows.nodes.control_foreach._handler.ForeachOutput

::: app.workflows.nodes.loop_item._handler.LoopItemOutput

## Virtual Tables { #virtual-tables }

Seven nodes read and write [Virtual Tables](../virtual-tables.md) through the same
service the console, the API and an agent's table tools use. Validation, revision
conflicts, quotas, history, receipts and audit are the same on every surface.

| Node | Does | Effect |
|---|---|---|
| `table.record.create` | Adds a record | write |
| `table.record.upsert` | Creates or updates the record with an external id | write |
| `table.record.update` | Changes some of a record's cells | write |
| `table.record.delete` | Deletes a record, keeping its history | write |
| `table.record.get` | Finds one record by id or external id | read |
| `table.record.query` | Reads one page of records, filtered and sorted | read |
| `table.create` | Creates a new table with a typed schema | write |

Each record node pins its table in its config, checked at publish against the
graph's author, and checked again as the run's principal on every run. Values are
bound and keyed by column id or by column label. A record comes back with its values
twice: `values` by column id, for bindings, and `fields` by label, to read. A key
that names no live column fails with `UNKNOWN_COLUMN`.

A write carries the step's operation key, so a retried step replays its first write.
An update, upsert or delete with no revision bound writes at the record's current
revision. A revision that moved is `REVISION_CONFLICT`, which is not retried: the same revision would
conflict again, so route it to a fresh read with `error.handle`. A missing
record is `found: false` from `table.record.get`, not a failure. `table.record.query`
reads at most 100 records a page and says `has_more`. It never reads a whole large
table on its own.

`table.create` is its own node and needs `tables:create`. Its output carries the
new table as a reference a later node's `table` can be bound to, and each column's
id by label. A table that a live workflow reads or writes, or a column it pins,
cannot be archived while that workflow's current version uses it.

::: app.workflows.nodes._tables.TableRecordOutput

::: app.workflows.nodes.table_record_get._handler.TableRecordLookup

::: app.workflows.nodes.table_record_query._handler.TableRecordQueryConfig

::: app.workflows.nodes.table_create._handler.TableCreateConfig

::: app.workflows.nodes.table_create._handler.TableCreatedOutput

## Adding a node { #adding-a-node }

A node is a package under `backend/app/workflows/nodes/`: `__init__.py`
registers a `NodeDefinition`, `_handler.py` implements it, and `README.md`
explains why it exists. `load_builtins` imports the package.
`tests/test_workflow_node_layout.py` enforces the layout. A handler returns
`Completed`, `Waiting`, `Failed` or `Uncertain` and never raises. It reads the
run it executes for from `app.services.workflow_execution.context.current()`.

::: app.workflows.contracts.definition.NodeDefinition
