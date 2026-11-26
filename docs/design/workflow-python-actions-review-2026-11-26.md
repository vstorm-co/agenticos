# Python action calls: release integration review

Source: PR #3305, commit `0b07ef43a73c6187144c24b093b5c2eed3938fa6`.
Its CI run 45722876258 and CodeQL run 45722876186 succeeded. Those results
belong to the source commit, not to this integration or the release aggregate.

## Execution contract

The `code.python.actions` node runs Monty code with named, versioned bindings to
native workflow actions. Each call becomes a durable child step with its own
scope, arguments digest, permissions, approvals, budget admission and result.
The interpreter checkpoint and queued child are saved in the same transaction.
Code can supply declared input fields and explicitly bindable configuration;
it cannot replace resource pins or credentials at call time. Nested Python action
nodes, graph wiring and trigger/output nodes are excluded.

A retry reuses settled receipts and rechecks current resource access. An external
write with an uncertain outcome is never guessed safe to repeat. Resume links
are regenerated for their run. Parked interpreter checkpoints are bounded,
validated and excluded from public attempt history. Retention keeps the receipt
chain required by active/recent retries. Remote sandbox actions retain the normal
sandbox adapter, current child context and idempotency key; no second execution
transport or provider credential store is introduced.

## Integration corrections

- Resource bundles walk every Python binding through its registered action's
  owned config schema. Arbitrary UUID-shaped user data is untouched. Omitting
  a required dependency removes the whole binding and requires code review.
- Direct table actions now carry separate table and schema-version pins. Both
  remap together to the selected destination table/version. Omitting the table
  removes the structured reference. Column-subset exports fail explicitly rather
  than copying source column identifiers.
- An action scope on a node other than `code.python.actions` cannot dispatch a
  bound action, even if its configuration resembles one.
- Legacy export expectations and onboarding tour expectations include changes
  already present in the integration base; production defaults are unchanged.

## Upgrade and verification

Apply `backend/alembic/versions/0365_attempt_receipt_only.py` before starting the
new worker. Its immutable revision ID is `0365_attempt_receipt_only`; the release
integration rebases its parent to `0370_console_role_presentation`. The aggregate
must join this head with the other feature migrations. Older attempts default to
`receipt_only=false`, preserving conservative unknown-write handling.

Monty remains version 1.6.0 and is now exactly pinned in the manifest/lockfile;
Dependabot must not change it alone because persisted checkpoints require a
compatible interpreter. This is not a dependency upgrade.

Local verification uses isolated PostgreSQL with pgvector and a local MCP HTTP
server. No paid model or production service was called. Focused tests cover
write approvals per iteration, denied/current resource access, fixed binding
configuration, replay versus dispatch, unknown effects, cursor storage/cleanup,
HTTP transport and budget reservations. Fresh migration heads upgrade,
`alembic check`, downgrade to the common base and re-upgrade pass. Full suites,
release-aggregate CI and actual desktop/mobile screenshots remain aggregate
verification, not claimed from source CI.
