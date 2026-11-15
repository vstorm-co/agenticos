# Explicit row Read and Write access

Status: claimed implementation draft. Owner: shermzy.
Requested on 15 November 2026 (Asia/Singapore). Base: t3 at 080c1294.

## Contract

Add real per-record Read/Write sharing and policy semantics. Write includes Read plus ordinary-field updates; deletion, access management and table schema remain separately authorized.

Read and Write compose with the organization and table-read boundaries.
Reuse the existing resource-grant persistence for user/group row shares with
expiry and revocation. Public row-grant levels are Read and Write; do not expose
an administrative Edit grant through this interface.

Keep stored view_column_id/edit_column_id policy compatibility. The Read result
includes the Write field, explicit row Read/Write grants and any configured
project-membership read rule. Use consistent SQL and individual-row evaluation,
including projected linked reads. A malformed policy never widens access.

Creation remains separately authorized. A row writer cannot modify table schema,
table sharing, row policy, protected membership fields or the security parent.
Use per-record server-derived access, can_delete and can_manage_access in the UI.

## Acceptance checks

- A Read grantee can inspect/list/export only allowed rows, but cannot mutate them.
- A Write grantee without table-administration permission can update the granted row only.
- User/group grants, expiry, revocation, tenant boundaries and API-key ceilings apply consistently.
- Permission-driving fields require access-management authority.
- Grid, detail, list and board consume per-record permissions; direct grants expose Read or Write only.

## Dependency and ownership

Depends on the permission-hardening PR in this series. Account for shared
permission files touched by MCP PR #97 and the upstream sync in #82.
Coordinate through this PR before overlapping implementation. This initial
commit records the implementation contract; application changes follow after
all draft PRs have been opened and claimed.
