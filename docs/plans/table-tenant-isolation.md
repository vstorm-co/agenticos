# enforce database tenant isolation

Status: claimed implementation draft. Owner: shermzy.
Requested on 15 November 2026 (Asia/Singapore). Base: t3 at 080c1294.

## Contract

Add PostgreSQL tenant-isolation safeguards for table data and relationships using authenticated transaction context and a runtime role that cannot bypass the intended policies.

## Acceptance checks

- Inventory request, tool, workflow, import/export and maintenance paths before enforcement.
- Missing identity/context denies access and pooled connections do not inherit another request's context.
- Test USING and WITH CHECK behavior with the real non-owner runtime role, including cross-tenant updates.
- Keep dynamic row Read/Write rules and field projection in the shared service; tenant RLS does not replace them.
- Document migration/role requirements and safe operational recovery; do not change production configuration in this PR.

## Dependencies and ownership

Depends on #99, #101.
Preserve the agreed row Read/Write contract: Write includes Read and updates to
ordinary fields, while deletion, sharing and schema administration stay separate.
Coordinate through this PR before overlapping implementation. This initial
commit records the implementation contract; application changes follow after
all draft PRs have been opened and claimed.

## Validation and rollout

Use focused deterministic tests and the exact revision's CI. Database constraint
and migration behavior requires disposable PostgreSQL integration tests. Preserve
existing data, revisions, history, idempotency and tenant checks. No production
configuration, migration, merge or deployment is authorized by this plan alone.
