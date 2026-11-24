# Tables tenant isolation: implementation checkpoint

PR #102 is claimed by shermzy for the tables-20261115 series and remains a draft.

## Implemented foundation

`backend/app/db/table_tenant.py` binds the authenticated organization with
PostgreSQL `set_config(..., true)`. The setting lasts only for the current outer
transaction. A second tenant cannot replace it during that transaction. Commit
and rollback let the same pooled session bind a new tenant. A first binding
inside a savepoint is refused so a savepoint rollback cannot erase the database
setting while leaving an apparently valid Python binding.

The policy predicate denies reads when context is absent and is intended for
both `USING` and `WITH CHECK`. The runtime-role check rejects `SUPERUSER` and
`BYPASSRLS`; migrations must use separate credentials. Integration tests exercise
actual PostgreSQL with a disposable role and table, including owner enforcement
under `FORCE ROW LEVEL SECURITY`, tenant reassignment, and pooled reuse.

## Enforcement is not activated yet

This checkpoint does not install or enable RLS on production Tables objects and
does not claim that all service entry points are wired. That cutover stays gated
on the following work:

1. Finish and integrate #103, #99, #100 and #101, including normalized relations.
2. Bind trusted context at every API, agent, workflow, scheduled job and background
   worker entry point before touching a protected table. Do not derive it from an
   unchecked header or accept a client-supplied context setting.
3. Inventory every Tables object: metadata, schema versions, records, row grants,
   views, media, history, receipts, outbox, triggers, definitions, edges and evidence.
   Child rows without an organization column need a verified parent predicate or
   a backfilled tenant column with a composite foreign key.
4. Make cross-tenant maintenance explicit. No application-set bypass flag and no
   silent fallback to privileged credentials. Runtime credentials should not own
   tables; enforce `ENABLE` plus `FORCE` and check actual policy coverage.
5. Add and rehearse the Alembic migration on the true integrated head, round-trip
   it, and run missing-context, wrong-tenant, savepoint, pool-reuse and worker tests
   before activating enforcement.

Tenant RLS is a backstop against a missing organization predicate. The service
still enforces table visibility, row Read/Write, protected access fields and link
destination permissions. Direct untrusted SQL access is outside this contract:
an application connection can set a custom PostgreSQL setting and must stay
behind trusted server code.
