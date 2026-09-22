# #1789 — Workflows: agent, retrieval, data, condition, HTTP and output nodes

Design for [issue #1789](https://github.com/vstorm-co/agenticos/issues/1789),
child of [#56](https://github.com/vstorm-co/agenticos/issues/56). Depends on
[#1786](1786-node-contracts.md) (`NodeDefinition`, `register()`, graph
validation) and [#1788](1788-durable-execution.md) (the state machine that
interprets `NodeResult`) — both designed, neither built. Every node below is a
`NodeDefinition` in #1786's shape, registered the way `debug.echo` is; every
handler returns the `Completed`/`Waiting`/`Failed`/`Uncertain` union #1788's
dispatcher already knows how to advance. Nothing here adds a second approval
queue, a second budget ledger or a second SSRF check — each node is a thin
adapter onto a service this codebase already trusts.

## Reused vs. new

Reused untouched: `AgentRunnerService`'s lifecycle, `ApprovalGate`,
`BudgetGuard`; `RetrievalService.retrieve`/`retrieve_multi`;
`PinnedAsyncClient`/`resolve_pinned_url`; `app.core.vault`;
`NotificationCenterService.write()`; `member_repo.list_member_ids_for`/
`resolve_access`. New: a pinned-version entry point for `agent.run`; a typed
`SourceRef` wrapping retrieval results; `http.request`'s config and
redaction; one code-defined `NotificationEventType` member.

## Module layout

```
app/workflows/nodes/
  core_input/  core_output/    agent_run/      knowledge_search/
  data_map/    logic_if/  logic_merge/         http_request/  notification_send/
app/workflows/nodes/_expr.py     # the shared JMESPath evaluator (data.map, logic.if)
app/workflows/contracts/io.py    # + WorkflowInputPayload, WorkflowOutputPayload, SourceRef
```

Each package is `{__init__, _handler, README}`, mirroring `debug_echo/`, so
`test_workflow_node_layout.py` needs no per-node exception.

## The expression language: JMESPath, not eval

#1786 is explicit: no `eval`/`exec` of client-supplied code or JS expressions,
ever. `data.map` and `logic.if` both need to pick a value out of a typed
input and coerce or compare it, so both use **JMESPath** — the declarative,
side-effect-free JSON query language AWS CLI's `--query` and Ansible's
`json_query` use — evaluated over the node's input serialized via
`model_dump(mode="json")`. It has no assignment, no loops, no user-defined
functions; `_expr.py` further restricts its builtin set to a read-only subset
(`contains`, `length`, `to_string`, `to_number`, `type`, `merge`,
comparisons), rejecting anything else at config-validation time — a real
query language with no code-execution surface. A malformed expression is a
`config_schema` failure at publish time (#1786 Pass 0), never a runtime one.

## Node reference

| id | kind | effect_kind | retry_guarantee | Waiting | Uncertain |
|---|---|---|---|---|---|
| `core.input` | action | pure | idempotent | never | never |
| `core.output` | action | pure | idempotent | never | never |
| `agent.run` | action | write | none | approval, via the pinned agent run | never (reconciler-synthesized only) |
| `knowledge.search` | action | read | idempotent | never | never |
| `data.map` | action | pure | idempotent | never | never |
| `logic.if` | control | pure | idempotent | never | never |
| `logic.merge` | control | pure | idempotent | never | never |
| `http.request` | action | write | method-dependent | never | on an ambiguous send |
| `notification.send` | action | write | idempotent | never | never |

### `core.input` / `core.output` — the graph boundary

Shared-contracts decision 5 left these names for #1789. They are markers, not
typed-contract negotiators: `core.input` is the node `entry_node_id` names,
`core.output` is a reachable sink (rule 2). Neither has a per-instance
configured shape — `NodeDefinition.output_schema` cannot vary per instance —
so a workflow needing a typed field out of the trigger payload uses
`data.map` to extract and coerce it.

```python
class WorkflowInputPayload(BaseModel):
    payload: dict[str, Any]     # whatever the trigger adapter supplied (#1785/#1792)
    triggered_by: str           # "api"|"websocket"|"webhook"|"chat"|"schedule"|"table_created"

class WorkflowOutputPayload(BaseModel):
    text: str | None = None
    sources: tuple[SourceRef, ...] = ()
    artifacts: tuple[FileRef, ...] = ()
    structured: dict[str, Any] | None = None
```

`core.input`: `input_schema=None`, `output_schema=WorkflowInputPayload`.
`core.output`: `input_schema=WorkflowOutputPayload`, `output_schema=None` —
deliberately the same shape `agent.run` outputs, so the common case (an
agent feeding straight into the workflow's output) type-checks under #1786
rule 3 with no `data.map` in between. Handlers are identity: `core.input`
returns `Completed` built by #1788's run-start code from the trigger;
`core.output` returns `Completed(output=None)` after recording its input as
the run's final answer.

### `agent.run` — a pinned published version, never floating

```python
class AgentRunConfig(BaseModel):
    agent_id: UUID
    agent_version_id: UUID          # no "current"/"latest" option exists to select
    structured_output_schema: dict[str, Any] | None = None   # JSON Schema, validated post-hoc

class AgentRunInput(BaseModel):
    prompt: str
    attachments: tuple[FileRef, ...] = ()

class AgentRunOutput(BaseModel):
    text: str
    sources: tuple[SourceRef, ...] = ()
    artifacts: tuple[FileRef, ...] = ()
    structured: dict[str, Any] | None = None
```

`AgentRunConfig` has no field that can express "whatever is published now" —
floating is structurally unreachable, not a runtime check. `prepare()`
cannot be reused directly: it resolves the version through
`AgentRegistryService.get_runnable_spec`, which answers an `environment_id`
pin or falls back to `Agent.current_version_id` — floating by design,
correct for chat, wrong for a published workflow. Delegation already needs
the same pin (`SubagentRef.agent_version_id`) and does not use `prepare()`
either: it loads `agent_repo.get_version(db, ref.agent_version_id,
organization_id=...)` directly and refuses if the version is missing,
belongs to another agent, or the delegate is archived. `agent.run` follows
that path — a small `AgentRunnerService.prepare_pinned(ctx, agent_id,
agent_version_id, ...)` mirroring it, or the same checks open-coded — never
`prepare()`'s environment resolution. `AgentRunInput.prompt` is handed to
`PreparedRun.execute(user_prompt=...)` exactly as a chat turn's text is;
`attachments` route through the existing `AttachmentRouter`/`ChatFile`
machinery into `UserContent`.

**Approval surfaces as this node's own `Waiting`** — the whole of what the
issue's "human.approval integration" means; see the call below. When the
pinned run parks on `ApprovalGate` (`RunStatus = AWAITING_APPROVAL`), the
handler returns `Waiting(reason="approval", resume_token=<NodeRun.id>)` and
`NodeRun.waiting_agent_run_id` is set to that `agent_runs.id`, per #1788.
Resume calls `AgentRunnerService.resume(ctx, run_id=waiting_agent_run_id)` —
never `prepare_pinned` again, which would re-send the original prompt to a
fresh run. A rejected approval resumes the agent as today, surfacing as an
ordinary `Completed` or a node-declared `Failed`.

**Failed**: the version/agent checks fail before any model call, so nothing
is spent; a `BudgetExceeded` mid-run maps to `Failed(code="agent_budget_exceeded")`;
a set `structured_output_schema` the agent's final text does not parse and
validate against (a post-hoc check — `AgentSpec` has no native
structured-output field, and adding one is out of scope) returns
`Failed(code="structured_output_mismatch")` **before** any downstream node
dispatches — #1788's transactional outbox already guarantees no state where
a `Failed` result exists but a downstream dispatch does too, so this node
only has to *return* `Failed`. `retry_guarantee="none"`: a conversation that
may already have called side-effecting tools is never safe to blindly
re-run; a crash mid-run is the child `agent_runs` row `run_reaper.py`
reconciles, and #1788's reconciler marks the orphaned `NodeAttempt`
`uncertain` rather than retrying, per its stated rule for `none` nodes.

### `human.approval` — not a node kind of its own

**The call: realized only indirectly, through `agent.run`'s
`Waiting(reason="approval")`. Not registered as a separate `NodeDefinition`.**

Every piece of approval machinery — `ApprovalGate`, `agent_runs.paused_state`,
`ApprovalService.decide`, the audit trail — is built exclusively around a
tool call inside a running agent, and #1788 is explicit that it adds "no
second approval queue." A standalone node would need its own queue, decide
endpoint and audit entries — the duplication #1788's design table already
rejects for budgets, restated here for approvals. "Ask a human before doing
X" is already expressible: give the pinned agent an approval-gated tool and
reach it through `agent.run`. The issue's phrase, "human.approval
**integration**", reads as wiring the existing flow into workflows, not a
new node kind. A generic pre-dispatch gate on an arbitrary node (pause
before `http.request`, independent of any agent) is a different, real
feature, explicitly out of scope here.

### `knowledge.search` — typed source references, empty is valid

```python
class KnowledgeSearchConfig(BaseModel):
    collection_ids: tuple[UUID, ...]   # resolved via resolve_access(Perm.KNOWLEDGE_VIEW) at bind time
    top_k: int = Field(default=5, ge=1, le=50)

class KnowledgeSearchInput(BaseModel):
    query: str

class SourceRef(BaseModel):
    document_id: UUID
    filename: str
    collection: str
    page: int | None = None
    chunk: int | None = None
    score: float
    content: str

class KnowledgeSearchOutput(BaseModel):
    sources: tuple[SourceRef, ...]
```

The handler calls `RetrievalService.retrieve`/`retrieve_multi` directly —
the same calls `search_knowledge_base` makes — skipping `_format_results`,
which exists only to build a string a model reads inline with citation
markers; each `RetrievalResult` becomes one `SourceRef`. An empty result
list is `Completed(output=KnowledgeSearchOutput(sources=()))`, never an
error — the issue's own requirement. Failures map through
`ExternalServiceError`'s existing redaction (`details={"collections",
"operation"}`, never upstream exception text) into
`Failed(code="knowledge_search_failed")`.

### `data.map` — typed binding conversion, no eval

```python
class FieldMapping(BaseModel):
    target_field: str
    source_path: str      # a JMESPath expression over the bound input
    coerce_to: Literal["string", "number", "boolean", "json", "file_ref", "table_ref"]
    default: Any | None = None

class DataMapConfig(BaseModel):
    mappings: tuple[FieldMapping, ...]
```

`input_schema=None` (the config plus whatever's bound decides the shape);
`output_schema` is a dict of typed values built from one JMESPath evaluation
and one coercion per field. A coercion failure returns
`Failed(code="mapping_coercion_failed", details={"target_field"})`.
`effect_kind="pure"`, `retry_guarantee="idempotent"` — deterministic, safe to
recompute without limit.

### `logic.if` / `logic.merge` — runtime evaluation of a validated shape

#1786 already validates these structurally (rule 5: a `logic.merge`'s
predecessors must be dominated by one `logic.if`'s two branch ports). Which
branch a given *run* takes is this node's handler, not #1786's.

```python
class LogicIfConfig(BaseModel):
    condition: str    # a JMESPath expression evaluated for truthiness against the input

class LogicIfOutput(BaseModel):
    branch: Literal["true", "false"]
    value: dict[str, Any]   # the bound input, passed through unchanged
```

`logic.if` has two output ports, `true`/`false`; its handler is
`Completed(output=LogicIfOutput(...))`. #1788's dispatcher reads
`output.branch` to decide which branch gets outbox rows; the untaken
branch's nodes are marked `skipped` exactly as #1788 already defines skip —
structural, at dispatch time, no new run-status concept. `logic.merge` takes
no config: exactly one dominating branch ever ran, so the handler passes
that one predecessor's output through unchanged,
`Completed(output=<that output>)`. Both `effect_kind="pure"`,
`retry_guarantee="idempotent"`.

### `http.request` — the reused SSRF pin, vault auth, node-scoped error policy

```python
class HttpAuthConfig(BaseModel):
    kind: Literal["bearer", "basic", "header", "none"]
    secret_id: UUID | None = None     # a vault secret id, like an MCP connection's
    header_name: str | None = None    # only for kind="header"

class HttpRequestConfig(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    url: str                          # may itself be a bound value, resolved before validation
    headers: dict[str, str] = {}
    auth: HttpAuthConfig = HttpAuthConfig(kind="none")
    body_mapping: tuple[FieldMapping, ...] = ()   # data.map's own shape, reused here
    timeout_seconds: int = Field(default=15, le=30)
    max_response_bytes: int = Field(default=1_000_000, le=10_000_000)
    idempotency_key_header: str | None = None     # e.g. "Idempotency-Key", if the target supports one
    on_error_status: Literal["complete_with_error_body", "fail"] = "fail"

class HttpResponseOutput(BaseModel):
    status_code: int
    headers: dict[str, str]     # Authorization, Set-Cookie, the auth header stripped
    body: dict[str, Any] | str
    truncated: bool
```

The handler dials through `PinnedAsyncClient` unchanged — no second SSRF
check, no reimplemented redirect walk. `auth` resolves through
`vault.unseal(ciphertext, scope=VaultScope.organization(ctx.organization_id))`,
never a value in `config_schema` itself. `timeout_seconds`/`max_response_bytes`
are bounded above by the node's own schema, not by policy read at run time; a
streamed body hitting the cap is `Failed(code="response_too_large")`, never a
silent partial-success truncation. Outgoing `headers` strip `Authorization`,
`Set-Cookie` and whichever header `auth` populated, so a `WorkflowError.details`
or stored `NodeAttempt.result` never carries the secret back out.

**Node-scoped error policy only.** `on_error_status` decides this node's own
outcome for a non-2xx response: `"complete_with_error_body"` returns
`Completed` so a downstream `logic.if` can branch on `status_code`; `"fail"`
(default) returns `Failed(code="http_error_status", details={"status_code"})`.
**#1790**, not yet designed, owns retry ceilings, backoff and error-routing —
this stays one node-local switch between "treat a bad status as data" and
"treat it as a failure," nothing about retrying it.

**The one `Uncertain` trigger** reuses a distinction `PinnedTransport`
already codes: `_UNREACHED = (ConnectError, ConnectTimeout)` — a failure
before any byte left the process, safely `Failed` (and, for an idempotent
method, safely retried). A `ReadTimeout`/`RemoteProtocolError` *after* the
body was sent, for a non-idempotent method with no `idempotency_key_header`
set, returns `Uncertain(detail="request sent; no response received")` — the
handler cannot tell whether the far side acted, and #1788's reconciler
decides whether a fresh attempt is safe. `retry_guarantee`: `GET` →
`"idempotent"`; a write method with `idempotency_key_header` set (from the
`NodeAttempt`'s own stable key, per #1788) → `"idempotent"`; otherwise
`"at_least_once"`.

### `notification.send` — acceptance is not delivery

```python
class RecipientRef(BaseModel):
    member_id: UUID

class NotificationSendConfig(BaseModel):
    recipients: tuple[RecipientRef, ...]
    subject: str
    body_mapping: tuple[FieldMapping, ...]   # interpolated values, not a template language
    channel: Literal["in_app", "email"] = "in_app"

class NotificationSendOutput(BaseModel):
    notified_member_ids: tuple[UUID, ...]
    notification_ids: tuple[UUID, ...]
```

Recipients are member ids resolved and permission-checked, never free-text
addresses — `resolve_access`/`member_repo.list_member_ids_for` filters to
members the workflow's audience may reach, the way `NotificationService.
_audience_ids` resolves an agent's alert audience; an unresolved recipient
is dropped silently, exactly as `_audience_ids` drops one, and if every
recipient drops the node is `Failed(code="no_permitted_recipients")`. The
vocabulary this writes into is code-defined (`NotificationEventType`), so
this node needs one new member, `WORKFLOW_NOTIFICATION` (a migration
touching the CHECK constraint, plus a `notification_catalog.py` entry) —
audience comes from the node's own `recipients`, already checked, not a
per-agent alert setting.

**The sharp edge in reuse**: every existing `write()` caller passes
`use_savepoint=True`, because for `AgentRunnerService` a notification
failing must never poison the transaction that just recorded the run's own
outcome — the failure is absorbed and logged. Here the notification *is*
the entire effect, so it calls `write(..., use_savepoint=False)`: a write
failure must surface as this node's own `Failed`, not be silently swallowed
the way a run's terminal write deliberately swallows it.

`Completed` means the row was written, not that anyone saw it or mail went
out — `notification_delivery_sweep`, a separate retried process, sends
email and can fail independently; the issue's "acceptance is not proof of
delivery" is exactly this split, already built for agent alerts.
`retry_guarantee="idempotent"`: this node passes the `NodeAttempt`'s own
stable idempotency key as `occurrence_id`, so a retried attempt after a
crash lands on the notification center's existing per-recipient uniqueness
constraint and writes nothing twice.

## Test plan

**Contract tests, one file per node package**, mirroring
`test_debug_echo_registered`: the node resolves through
`all_node_definitions()`/`get(id, version)` after `load_builtins()`; its
three schemas round-trip; a handler call with a mocked reused service
returns the right `NodeResult` variant for every documented trigger — what
AC4 checks structurally.

**Integration tests against the real reused services**:

| Node | Integration test |
|---|---|
| `knowledge.search` | A seeded pgvector collection returns correct `SourceRef`s; an unpermitted `collection_id` is refused at bind time |
| `agent.run` | An approval-gated tool parks (`Waiting`); the dispatcher resumes the *same* `agent_runs` row — #1788's approval test, replayed here |
| `http.request` | A private-IP target is refused before connecting; an over-size response fails without buffering it whole; a redacted response never carries `Authorization` |
| `notification.send` | An unpermitted `member_id` is dropped; two attempts sharing one idempotency key write one row |
| `logic.if`/`logic.merge` | A full if/else→merge graph runs end to end with typed data on both branches (AC1) |
| `data.map` | A disallowed JMESPath function is refused at config-validation time |

**Regression tests named directly off AC2/AC3**: unsafe HTTP targets, secret
leakage in any response or error detail, an invalid branch reaching both
`logic.merge` inputs at once, and an unauthorized notification recipient —
each its own test, not a shared catch-all. Structured-output mismatch is
verified by asserting no `DispatchOutbox` row exists for any node downstream
of a failed `agent.run` instance — the direct test of that AC's wording.

## Commit order

1. `contracts/io.py` additions (`WorkflowInputPayload`, `WorkflowOutputPayload`,
   `SourceRef`, `FieldMapping`) + serialization tests — every node imports one.
2. `nodes/_expr.py` — the JMESPath evaluator and function allowlist, with
   tests for every accepted/rejected function and a malformed-expression refusal.
3. `core.input`/`core.output` — no external service, provable in isolation.
4. `logic.if`/`logic.merge` — exercises #1786's rule 5 end to end with a real handler.
5. `data.map` — depends only on step 2.
6. `knowledge.search` — first node touching a real reused service; its
   pgvector integration suite lands with it.
7. `http.request` — `PinnedAsyncClient` wrapper, vault auth, redaction; SSRF
   and secret-leak regression tests land with it, not after.
8. `notification.send` — the `NotificationEventType.WORKFLOW_NOTIFICATION`
   migration and catalog entry, then the node; dedup test against the real
   unique constraint.
9. `agent.run` last — the pinned-version entry point on `AgentRunnerService`
   (or its open-coded equivalent), the structured-output check, and the
   approval `Waiting`/resume integration test against #1788's dispatcher.
10. Docs: whatever workflow-node catalog page exists by the time this lands
    (#1786 created none — its own design page names the node-catalog route
    as its only doc surface); otherwise each node's `README.md`, mirroring
    `nodes/debug_echo/README.md`, is this issue's documentation surface.
