# Workflows + Virtual Tables: milestone acceptance map

Checked on 2026-10-24 against PR #1925 and milestone 16 (56 issues: 55 open, one closed).

This maps the implemented contracts to executable evidence. An existing test is a
verification entry point, not a claim that every test in this table was rerun locally.
GitHub issues remain open until the implementation is merged; this record does not
close issues or authorize a merge.

## Requirement map

| Issue | Implemented behavior | Evidence |
|---|---|---|
| [#56](https://github.com/vstorm-co/agenticos/issues/56) | Milestone journeys and boundaries | [test_workflow_journeys.py](../../backend/tests/integration/test_workflow_journeys.py) |
| [#1781](https://github.com/vstorm-co/agenticos/issues/1781) | React Flow selected; SDK lab excluded | [workflow-builder-sdk-evaluation.md](../../docs/plans/workflow-builder-sdk-evaluation.md) |
| [#1782](https://github.com/vstorm-co/agenticos/issues/1782) | Typed storage, schema versions, revisions | [test_virtual_table_records.py](../../backend/tests/integration/test_virtual_table_records.py) |
| [#1783](https://github.com/vstorm-co/agenticos/issues/1783) | Table, kanban, list and saved views | [test_table_views.py](../../backend/tests/integration/test_table_views.py) |
| [#1784](https://github.com/vstorm-co/agenticos/issues/1784) | One service behind agent tools and typed nodes | [test_virtual_tables_capability.py](../../backend/tests/integration/test_virtual_tables_capability.py) |
| [#1785](https://github.com/vstorm-co/agenticos/issues/1785) | Transactional events, subscriptions, deduplication | [test_table_triggers.py](../../backend/tests/integration/test_table_triggers.py) |
| [#1786](https://github.com/vstorm-co/agenticos/issues/1786) | Registry, graph and binding validation | [test_workflow_graph_validation.py](../../backend/tests/test_workflow_graph_validation.py) |
| [#1787](https://github.com/vstorm-co/agenticos/issues/1787) | Editor, autosave and immutable publication | [use-workflow-autosave.test.ts](../../frontend/src/components/workflows/editor/use-workflow-autosave.test.ts) |
| [#1788](https://github.com/vstorm-co/agenticos/issues/1788) | Durability, approval, budgets and replay | [test_workflow_run_dispatch.py](../../backend/tests/integration/test_workflow_run_dispatch.py) |
| [#1789](https://github.com/vstorm-co/agenticos/issues/1789) | Agent, retrieval, HTTP, notification and output nodes | [test_workflow_journeys.py](../../backend/tests/integration/test_workflow_journeys.py) |
| [#1790](https://github.com/vstorm-co/agenticos/issues/1790) | Error routing and durable iteration scopes | [test_workflow_error_foreach.py](../../backend/tests/integration/test_workflow_error_foreach.py) |
| [#1791](https://github.com/vstorm-co/agenticos/issues/1791) | Authorized files, conversions, image and sandbox bounds | [test_workflow_file_nodes.py](../../backend/tests/integration/test_workflow_file_nodes.py) |
| [#1792](https://github.com/vstorm-co/agenticos/issues/1792) | Shared API-key authentication and channel adapters | [test_workflow_journeys.py](../../backend/tests/integration/test_workflow_journeys.py) |
| [#1793](https://github.com/vstorm-co/agenticos/issues/1793) | Four journeys plus crash/revocation evidence | [test_workflow_journeys.py](../../backend/tests/integration/test_workflow_journeys.py) |
| [#1795](https://github.com/vstorm-co/agenticos/issues/1795) | Real organization-key CRUD, receipts and projection | [test_virtual_table_public_api.py](../../backend/tests/integration/test_virtual_table_public_api.py) |
| [#1800](https://github.com/vstorm-co/agenticos/issues/1800) | Selected extensions: called workflows, switch, forms and channels | [test_workflow_calls.py](../../backend/tests/integration/test_workflow_calls.py) |
| [#1823](https://github.com/vstorm-co/agenticos/issues/1823) | History deltas, receipt/outbox retention and quotas | [test_virtual_table_retention.py](../../backend/tests/integration/test_virtual_table_retention.py) |
| [#1905](https://github.com/vstorm-co/agenticos/issues/1905) | Collision-free workflow creation and duplication | [test_workflow_management.py](../../backend/tests/integration/test_workflow_management.py) |
| [#1907](https://github.com/vstorm-co/agenticos/issues/1907) | Reserved node work per principal/org and separate worker pool | [test_workflow_execution_admission.py](../../backend/tests/test_workflow_execution_admission.py) |
| [#1915](https://github.com/vstorm-co/agenticos/issues/1915) | Revisioned restore; stale responses cannot replace another draft | [use-restore-version.test.ts](../../frontend/src/components/workflows/editor/use-restore-version.test.ts) |
| [#1932](https://github.com/vstorm-co/agenticos/issues/1932) | Manual/API triggers and editor Run | [run-button.test.tsx](../../frontend/src/components/workflows/editor/run-button.test.tsx) |
| [#1933](https://github.com/vstorm-co/agenticos/issues/1933) | Live canvas status and output counts | [live-run.test.tsx](../../frontend/src/components/workflows/canvas/live-run.test.tsx) |
| [#1934](https://github.com/vstorm-co/agenticos/issues/1934) | Input/output JSON, table and schema panes | [step-panes.test.tsx](../../frontend/src/components/workflows/node-editor/step-panes.test.tsx) |
| [#1935](https://github.com/vstorm-co/agenticos/issues/1935) | Test one step without repeating known effects | [step-test-run.test.tsx](../../frontend/src/components/workflows/node-editor/step-test-run.test.tsx) |
| [#1936](https://github.com/vstorm-co/agenticos/issues/1936) | Pinned test outputs excluded from real runs | [test_workflow_pinned_data.py](../../backend/tests/integration/test_workflow_pinned_data.py) |
| [#1937](https://github.com/vstorm-co/agenticos/issues/1937) | Typed drag/drop with keyboard picker | [binding-field-drop.test.tsx](../../frontend/src/components/workflows/property-panel/binding-field-drop.test.tsx) |
| [#1938](https://github.com/vstorm-co/agenticos/issues/1938) | Validated template placeholders | [template-box.test.tsx](../../frontend/src/components/workflows/property-panel/template-box.test.tsx) |
| [#1939](https://github.com/vstorm-co/agenticos/issues/1939) | Named, annotated and disabled steps | [test_workflow_switched_off_steps.py](../../backend/tests/integration/test_workflow_switched_off_steps.py) |
| [#1940](https://github.com/vstorm-co/agenticos/issues/1940) | Canvas notes kept by versions and copy/paste | [workflow-editor-store.test.ts](../../frontend/src/stores/workflow-editor-store.test.ts) |
| [#1941](https://github.com/vstorm-co/agenticos/issues/1941) | Connection insertion, tidy, minimap and shortcuts | [quick-add.test.tsx](../../frontend/src/components/workflows/canvas/quick-add.test.tsx) |
| [#1942](https://github.com/vstorm-co/agenticos/issues/1942) | List search/sort/tags and workflow management | [test_workflow_management.py](../../backend/tests/integration/test_workflow_management.py) |
| [#1943](https://github.com/vstorm-co/agenticos/issues/1943) | Run filters, graph inspection and retry | [test_workflow_run_retry.py](../../backend/tests/integration/test_workflow_run_retry.py) |
| [#1944](https://github.com/vstorm-co/agenticos/issues/1944) | Timezone, deadline, failure workflow and retention settings | [test_workflow_settings.py](../../backend/tests/integration/test_workflow_settings.py) |
| [#1945](https://github.com/vstorm-co/agenticos/issues/1945) | Failure workflow admitted once without recursion | [test_workflow_settings.py](../../backend/tests/integration/test_workflow_settings.py) |
| [#1946](https://github.com/vstorm-co/agenticos/issues/1946) | Pinned called workflows, budgets and depth limits | [test_workflow_calls.py](../../backend/tests/integration/test_workflow_calls.py) |
| [#1947](https://github.com/vstorm-co/agenticos/issues/1947) | Switch, durable wait, resume, filter and merge | [test_workflow_wait_and_switch.py](../../backend/tests/integration/test_workflow_wait_and_switch.py) |
| [#1948](https://github.com/vstorm-co/agenticos/issues/1948) | Typed transformations that compose | [test_workflow_transform_composed.py](../../backend/tests/integration/test_workflow_transform_composed.py) |
| [#1949](https://github.com/vstorm-co/agenticos/issues/1949) | Draft webhook listener and explicit response | [webhook-listener.test.tsx](../../frontend/src/components/workflows/node-editor/webhook-listener.test.tsx) |
| [#1950](https://github.com/vstorm-co/agenticos/issues/1950) | Create a typed vault secret in the picker | [binding-field-dynamic.test.tsx](../../frontend/src/components/workflows/property-panel/binding-field-dynamic.test.tsx) |
| [#1951](https://github.com/vstorm-co/agenticos/issues/1951) | cURL import and bounded authenticated pagination | [test_workflow_http_node.py](../../backend/tests/integration/test_workflow_http_node.py) |
| [#1952](https://github.com/vstorm-co/agenticos/issues/1952) | Themed code editing and isolated test execution | [code-editor.test.tsx](../../frontend/src/components/workflows/property-panel/code-editor.test.tsx) |
| [#1953](https://github.com/vstorm-co/agenticos/issues/1953) | Portable import/export with resource rebinding | [test_workflow_portable_graph.py](../../backend/tests/test_workflow_portable_graph.py) |
| [#1954](https://github.com/vstorm-co/agenticos/issues/1954) | Version-to-version/draft graph diff | [version-compare.test.tsx](../../frontend/src/components/workflows/editor/version-compare.test.tsx) |
| [#1955](https://github.com/vstorm-co/agenticos/issues/1955) | Editor chat tests isolated from conversations | [chat-panel.test.tsx](../../frontend/src/components/workflows/editor/chat-panel.test.tsx) |
| [#1956](https://github.com/vstorm-co/agenticos/issues/1956) | Header trigger activation and pause | [workflow-status.test.tsx](../../frontend/src/components/workflows/editor/workflow-status.test.tsx) |
| [#1957](https://github.com/vstorm-co/agenticos/issues/1957) | Optional settings and validation after interaction | [node-form.test.tsx](../../frontend/src/components/workflows/property-panel/node-form.test.tsx) |
| [#1958](https://github.com/vstorm-co/agenticos/issues/1958) | New-record sheet and bottom grid row | [new-record-row.test.tsx](../../frontend/src/components/tables/new-record-row.test.tsx) |
| [#1959](https://github.com/vstorm-co/agenticos/issues/1959) | Typed inline cells, keyboard navigation and conflicts | [inline-cell.test.tsx](../../frontend/src/components/tables/inline-cell.test.tsx) |
| [#1960](https://github.com/vstorm-co/agenticos/issues/1960) | Confirmed deletion with deferred undo | [table-grid-view.test.tsx](../../frontend/src/components/tables/table-grid-view.test.tsx) |
| [#1961](https://github.com/vstorm-co/agenticos/issues/1961) | CSV preview, mapping, background import and export | [import-csv-dialog.test.tsx](../../frontend/src/components/tables/import-csv-dialog.test.tsx) |
| [#1962](https://github.com/vstorm-co/agenticos/issues/1962) | Saved filters/search and server paging | [record-filters-popover.test.tsx](../../frontend/src/components/tables/record-filters-popover.test.tsx) |
| [#1963](https://github.com/vstorm-co/agenticos/issues/1963) | Column actions and schema dependencies | [column-header-menu.test.tsx](../../frontend/src/components/tables/column-header-menu.test.tsx) |
| [#1964](https://github.com/vstorm-co/agenticos/issues/1964) | Virtualized grid, incremental pages and bounded counts | [table-grid-view.test.tsx](../../frontend/src/components/tables/table-grid-view.test.tsx) |
| [#1974](https://github.com/vstorm-co/agenticos/issues/1974) | Live page queries, owner access recheck, consent and refresh | [test_artifact_bindings.py](../../backend/tests/integration/test_artifact_bindings.py) |
| [#1975](https://github.com/vstorm-co/agenticos/issues/1975) | Off-by-default public live data and audited consent | [test_artifact_public_data.py](../../backend/tests/integration/test_artifact_public_data.py) |
| [#1976](https://github.com/vstorm-co/agenticos/issues/1976) | Member-only actions run as viewer; frame bridge | [test_artifact_action_runs.py](../../backend/tests/integration/test_artifact_action_runs.py) |

## Scope decisions

- #1800 is an optional extension tracker whose body explicitly leaves candidate
  additions unscheduled. Its concrete delivered increments are called workflows
  (#1946), Switch/Wait (#1947), typed form and channel adapters. This does not promise
  arbitrary provider nodes or unrestricted parallel graph execution. New candidates
  still require their own use case, acceptance criteria and estimate, as #1800 asks.
- #1974 evolved from a saved-view reference into a disclosed, versioned page query.
  A view supplies initial filters and sort; explicit fields define its columns.
  Subsequent view edits do not broaden an approved page. The owner’s access and the
  revisions of every reached column are checked on each load. See
  [the current contract](../virtual-tables.md#views-for-pages) and
  [the implementation](../../backend/app/services/artifact_bindings.py).
- Historical planning documents mention Prefect. The implemented durable runner uses
  the shared Postgres job queue and a dedicated workflow worker pool. No second
  orchestration runtime is required.

## Gaps fixed during acceptance

- Organization-key requests were rejected before reaching table and workflow-run
  services because those routers lacked the public API marker. The public OpenAPI
  regression failed before this change. Both routers now use shared key authentication.
- Workers now persist and revalidate the admitting workflow key, intersect current
  scopes with the admitted ceiling, and stop after expiry, revocation or deletion.
  A key-started chain is public-origin and cannot acquire personal authority.
- Record queries now support bounded column projection, including computed results
  whose source columns are omitted. Unknown/archived columns are refused after table
  access checks; projections do not return unselected link labels.
- The API-created lead journey now authenticates with an actual organization key,
  retries the delivery with an idempotency key, and proves a single admitted workflow.
  It no longer overrides request authentication.
- Published docs no longer claim console record creation/deletion, update/delete
  triggers or the API-key principal are missing.

## Recorded code-based journeys

Run the named file against an isolated pgvector test database:

```bash
cd backend
uv run pytest tests/integration/test_workflow_journeys.py -q --no-cov
```

The file executes real publication, dispatch, state persistence and table operations.
Model responses and retrieval are deterministic in-process substitutes; no app server
or external model is started. Its assertions record these outcomes:

| Journey | Verified outcome |
|---|---|
| Chat → retrieval → agent → answer | One final answer in the original conversation |
| Two agents in sequence | Structured extraction passes to the writing agent |
| API-created lead → trigger → agent → update → notification | Duplicate delivery is replayed; one workflow updates the lead to revision 2 |
| Files → foreach → conversion → agent → Python → upsert → report | Uploaded files are processed in order and recorded in the report |
| Crash after table write | The completed write is replayed without another revision |
| Crash during model call | Unknown effects stop for attention instead of repeating the call |
| Access revoked midway | Later work stops; confirmed effects remain recorded |
| Key-started workflow | Current key authority remains narrowed; the result is readable over the public API |
| Key revoked before dispatch | The run fails with PRINCIPAL_REVOKED before a node acts |

## Local verification and limits

- Scoped public API/journey/dispatcher batch: 143 passed before the additional stored
  session-ceiling regression; final verification is recorded in the PR.
- Dispatcher/facade/journey batch: 180 passed before the final added assertions.
- Artifact bindings, public-data consent, declarations and action-run integration:
  145 passed.
- Seven table UI test files covering grid, inline cells, column menus, new rows,
  CSV import, kanban and list views: 85 passed.
- Migration 0217_workflow_api_key_authority: upgrade, downgrade, upgrade and
  `alembic check` on a disposable database; no schema drift.
- No application startup, local full backend/frontend suite, e2e or load test.
- These code-based demonstrations do not establish real-provider latency, sandbox
  host isolation or smooth scrolling at 10,000 rows on a device. Those need deployed
  environment validation; unit/component evidence is not a browser benchmark.
