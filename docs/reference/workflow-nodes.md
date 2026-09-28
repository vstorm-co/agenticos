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
  and gives no guarantee stops for a person instead.

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

## Adding a node { #adding-a-node }

A node is a package under `backend/app/workflows/nodes/`: `__init__.py`
registers a `NodeDefinition`, `_handler.py` implements it, and `README.md`
explains why it exists. `load_builtins` imports the package.
`tests/test_workflow_node_layout.py` enforces the layout. A handler returns
`Completed`, `Waiting`, `Failed` or `Uncertain` and never raises. It reads the
run it executes for from `app.services.workflow_execution.context.current()`.

::: app.workflows.contracts.definition.NodeDefinition
