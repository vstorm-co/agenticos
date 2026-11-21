# Console monitoring and integrations audit

Repository source review and targeted component/hook checks. This is not a visual
certification; browser evidence belongs to the parent task. Permissions and API
refusals remain authoritative. Existing query hooks, table, dialog and error
primitives were reused rather than adding a parallel state layer.

| Route / surface                | Findings and resulting behavior                                                                                                                                                                               |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/runs` and focused run        | Permission errors are retryable; selecting a row scrolls only the list. Failed, loading and unavailable run detail retain Close; transient errors have Retry. Nested dialog Escape does not close the parent. |
| `/evals`                       | Permission read failure has Retry; empty-state dataset action requires dataset view authority.                                                                                                                |
| `/agents/[id]/evals/[runId]`   | Existing comparison/case tabs, denied states and read Retry retained. Explicit case deep links intentionally scroll to cases.                                                                                 |
| `/mcp-servers`                 | Catalog/personal read Retry; tool picker resets stale search between connections, links to actual server setup, and prevents conflicting changes/dismissal while saving.                                      |
| `/vault`                       | Failed reads retry personal/secrets and organization accounts only when authorized; available sections remain usable. No credential values or storage contract changed.                                       |
| `/sandboxes`                   | Query disabled without read authority; permission failure and refusal distinct. Failed list Retry in both tabs; Edit/Delete hidden from read-only callers.                                                    |
| `/channels`                    | Failed permissions or channel reads retry their actual owning query. Platform-first creation and existing optional controls retained.                                                                         |
| `/remote-agents`               | Read permission gates query; failures have Retry. Registration folds optional handle/auth while revealing field errors. Deletion stays open on failure and prevents duplicate writes.                         |
| `/work`                        | Existing active/history split, encoded conversation links and guarded stop actions retained.                                                                                                                  |
| `/browse/[runId]/[callId]`     | Shared BrowserWindow differentiates forbidden/gone/unavailable/loading. Remote takeover was source reviewed, not exercised here.                                                                              |
| `/apps/[id]`                   | Version pin and return-path parsing retained; ArtifactViewer handles unavailable/requestable/transient states and Retry. Rendering isolation unchanged.                                                       |
| Workflow logs/runs             | Shared filtering, server paging, Retry and optional statistics retained. Run detail now reports failed constituent reads instead of an endless loading skeleton.                                              |
| Agent/skill improvement detail | Stage/review/acceptance guards retained; initial resource read now retryable alongside the existing session read.                                                                                             |

## Contracts retained

- Read denial does not silently become an empty collection or fetch protected data.
- Remote registration keeps essential URL visible and only folds optional handle
  and authentication; configured field errors reveal the corresponding controls.
- MCP search does not silently carry into another connection. Saving prevents
  editing or dismissing the draft until the write settles.
- Retry stays with the failed query; no browser reload, fabricated success or
  automatic permission escalation is introduced.
- EnvironmentsPanel was source reviewed with the builder workstream: release
  authority, version pins, test controls and existing failure recovery retained.

## Evidence and limits

Initial monitoring/integration batch: 123 tests passed in 11 files. The expanded
batch passed 230 tests and exposed three exact-label mistakes in new run-detail
tests, subsequently corrected; the final shared panel/run/MCP batch passed 120
tests in four files. Final route recovery and type/lint checks are recorded in
the parent delivery. No whole-directory suite or E2E was run by this workstream.
Live OAuth, remote homeservers, sandbox hosts and native desktop takeover need
their actual runtime; source and mocked component checks do not prove them.
