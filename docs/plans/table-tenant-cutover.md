# Tables tenant isolation cutover

Engineering runbook for PR #102, following #103, #99, #100 and #101.
The release keeps logical user tables in the deployment's PostgreSQL database.
Table creation changes metadata and records; it does not provision another
database or run user-defined DDL.

Use this runbook with [the relationship cutover](table-relations-cutover.md).
The combined release requires a write barrier for the relationship backfill
and a coordinated restart for tenant enforcement. Development and CI use
disposable databases. Deployment approval, production credentials and a
production migration are separate operator actions.

## What is enforced

The application still decides table access and row Read/Write permissions.
Row Write includes Read and ordinary cell/link updates; it does not grant
create, delete, sharing, schema administration or changes to fields that control
access. Link changes require source Write and destination Read. PostgreSQL RLS
adds an organization boundary if application code omits an organization filter.

A trusted server `AuthContext` sets transaction-local
`t3os.organization_id`. An active runtime transaction accepts one organization.
The context is established before the first table operation or savepoint and
ends with commit or rollback. Missing context exposes no Tables rows. Request
bodies and arbitrary organization headers do not supply this context directly.

The complete policy inventory has 15 objects:

| Objects | Tenant check |
| --- | --- |
| `virtual_tables`, `virtual_table_records`, `virtual_table_record_history`, `virtual_table_receipts`, `virtual_table_outbox`, `virtual_table_media`, `table_views`, `virtual_table_relations`, `virtual_table_record_links`, `virtual_table_link_evidence` | The row's organization matches the trusted transaction context. |
| `virtual_table_triggers`, `table_trigger_admissions` | The row's organization matches, and referenced Tables parents belong to that organization. A retained admission may have a null outbox reference. |
| `virtual_table_schema_versions`, `virtual_table_trigger_revisions` | The parent table or trigger belongs to the current organization. |
| `resource_grants` | The organization boundary applies to `table` and `table_record` grants. Other resource families retain their existing application authorization. |

Every object receives the restrictive `t3os_tables_tenant_guard` and
permissive `t3os_tables_tenant_access` policies, with both read and write checks.
Activation enables and forces RLS on the entire inventory in one transaction.
The explicit maintenance role membership is the only policy exception.

This context guards against accidental missing predicates. It is not a
boundary against arbitrary SQL execution or a compromised application process.
Runtime code can set its trusted context, and the separate maintenance
credential is privileged. Policy fingerprints detect drift; they are not
signatures against a database owner who can replace both a policy and its stamp.

## Credentials and privileges

Use three distinct credentials for the same deployment database:

| Credential | Configuration | Purpose |
| --- | --- | --- |
| Runtime | Existing `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_SSLMODE` settings | API, agent, workflow and worker operations under a bound organization. |
| Migration owner | `POSTGRES_MIGRATION_URL` | Alembic and the explicit preflight/activation command. It must own, or inherit ownership of, the complete protected object set. |
| Maintenance | `POSTGRES_MAINTENANCE_URL` | Authorized whole-account export/deletion and other explicitly scoped global maintenance transactions. |

The two URL settings are secret values. Supply them through the deployment's
secret manager, not a committed environment file, command history or PR.
Use PostgreSQL URLs with URL-encoded credentials. Alembic normalizes the
migration URL to the installed psycopg2 driver; the operator command selects
asyncpg when checking its connections. A standard `postgresql://` provider URL
or an explicit PostgreSQL driver URL is accepted. TLS parameters are translated
for the selected driver; configure TLS consistently for all three connections.

Runtime and maintenance logins must not be superusers, have `BYPASSRLS` or
`CREATEROLE`, own protected tables, or be able to assume a privileged or owner
role. Both the login identity (`session_user`) and active identity
(`current_user`) are checked, including indirect membership. `NOINHERIT`
alone does not remove a role's ability to assume another role.

Both service logins need `SELECT`, `INSERT`, `UPDATE` and `DELETE` on the
protected objects and the usual privileges needed by the rest of the application.
Neither may have effective `TRUNCATE` on protected objects, including through
`PUBLIC` or another role. Do not use `GRANT ALL ON TABLES` for these logins.

The fixed group `t3os_tables_maintenance` must be `NOLOGIN`, nonprivileged
and not an owner. Only the maintenance login joins it. The runtime login must
have no membership path into it. Role creation and grants are operator-owned;
neither the migration nor the activation command provisions credentials.

For a fresh pair of service roles, an operator can adapt this example after
connecting to the intended database as its owner. Replace the deployment role
names, retain the existing migration owner, and set login secrets separately:

```sql
CREATE ROLE t3os_tables_maintenance
    NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
CREATE ROLE deployment_runtime
    LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
CREATE ROLE deployment_maintenance
    LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
GRANT t3os_tables_maintenance TO deployment_maintenance;

GRANT USAGE ON SCHEMA public TO deployment_runtime, deployment_maintenance;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
    TO deployment_runtime, deployment_maintenance;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public
    TO deployment_runtime, deployment_maintenance;
```

If the fixed group already exists, inspect it instead of recreating it. Preserve
the same narrow table and sequence grants in the actual migration owner's
default privileges so future migrations do not silently leave the runtime
without access. Use deployment-specific login credentials and database access;
do not reuse a service login across unrelated deployments.

The existing RAG/vector store creates collection tables at runtime. Its runtime
role also needs `CREATE` on that deployment's vector-table schema, and ownership
of its runtime vector objects for their lifecycle operations. Inventory existing
objects when changing credentials; a DML grant alone does not transfer ownership.
Identify them using the registered model metadata and the runtime-vector rules,
not just a `rag_` prefix: `rag_documents` is an application model. Preserve
protected Tables object ownership under the migration owner. The Tables role
preflight intentionally permits ownership of unrelated runtime vector objects.

## Rehearsal and data prerequisites

Record the release commit, migration head, PostgreSQL major, credential role
names, backup reference and linked CI run before scheduling the cutover.
Require the exact release's migration cycle, model parity, permission regressions
and coverage gates to pass. The expected dependency chain is
`0332_merge_t3_pools_v1761`, published `0333_room_threads` (#90),
`0327_virtual_table_relations` (#101), then `0328_tables_tenant_rls` (#102),
with one Alembic head. The unreleased policy revision was renumbered during
recovery; its original source remains in history. Track the combined release
and current verification in #111.

On a disposable restored copy, run the full migration chain and inspect the
relationship evidence and storage projection described in the companion
runbook. Retained JSON, history, definitions, edges and quarantine evidence all
need headroom. A small fabricated-data rehearsal establishes correctness of its
fixtures, not production timing, database disk capacity or lock duration.

The tenant migration adds a nullable generated Tables-user subject to
`resource_grants`. Its composite foreign key requires the user to be a member
of that organization and cascades Tables grants when membership ends. Group
grants and other resource families are unaffected. This keeps multi-organization
LDAP/OIDC membership cleanup atomic in its original authentication transaction.

Legacy Tables user grants without their organization membership stop the
migration with an actionable count before the constraint is added. Legacy
cross-organization trigger/admission parent references stop migration or
activation. Investigate and repair these records through an approved data
repair; the rollout does not silently delete, reassign or hide them.

Before resuming traffic, rehearse with actual non-owner login connections.
A superuser followed by `SET ROLE` is insufficient: the login could restore its
privileged identity, and the preflight deliberately refuses it.

## Apply and activate

Run the commands from the release's `backend` directory or its equivalent
installed container environment. Use its locked dependencies and configured
secret values. The commands below contain no credentials.

1. Drain every API process, agent writer, import, workflow worker, trigger
   consumer and maintenance job. Wait for in-flight transactions to finish.
   Prevent old processes from restarting during the cutover.
2. Confirm the production backup and the rehearsed restore path. Apply the full
   migration chain under the separate migration credential. Policies are
   installed disabled; this migration alone does not activate RLS.

   ```sh
   uv run --frozen alembic upgrade head
   ```

3. Grant the narrow runtime and maintenance privileges on newly created objects.
   Configure all replacement API and worker processes with the runtime
   credential. Keep the migration credential limited to the operator job.
4. Verify the actual migration head and credential/policy checks:

```sh
uv run --frozen alembic current
uv run --frozen alembic heads
uv run --frozen alembic check
uv run --frozen agenticos cmd tables-rls preflight
```

The preflight verifies all objects, policies and effective role privileges.
A transaction-local advisory-lock challenge proves that the three separate
connections reach the same database, even when their hostnames differ.
Read-only preflight makes no enforcement change. A failed check must be resolved
before activation.

5. With services still drained, activate the complete policy family:

```sh
uv run --frozen agenticos cmd tables-rls activate --services-drained
```

Activation releases maintenance preflight read locks, obtains exclusive locks on
the full object set, recreates the two owned policies from exact definitions,
stamps them, and enables plus forces RLS atomically. It uses bounded connection
and command timeouts, a five-second lock timeout and a 30-second statement
timeout. A refusal or timeout does not leave a partially committed activation.
The command does not drain services for the operator.

6. Start only the new API and worker release. Startup checks reject partial
   enforcement, unsafe runtime credentials and changed policy inventory.
   Verify representative reads, writes, imports, receipts, deltas, backlinks,
   saved views, public page bindings and trigger processing under restricted
   members. Confirm another organization is absent from each surface.
7. Verify authorized account export/deletion on a disposable account and confirm
   its audit and deferred cleanup behavior. Resume normal writers after the
   cutover checks pass and record the deployed commit and activation result.

The maintenance credential is mandatory for the explicit global-operation path
after activation. Authentication occurs on the runtime connection; the actor's
current active/admin state is checked again on the maintenance connection.
The complete action, audit and deferred work use one managed maintenance
transaction. Missing configuration fails closed instead of falling back to a
privileged runtime connection.

## Failure, repair and rollback

A failed activation transaction leaves its prior enforcement state intact.
Keep services drained while diagnosing missing grants, lock contention,
credential mismatch, legacy corruption or policy drift. The preflight reports
configuration problems without printing DSNs or driver error details.

A missing or changed owned policy may be repaired only through the same
services-drained activation command, which recreates its exact SQL before
restamping it. An unknown extra policy stops activation for explicit operator
review. There is no command that approves arbitrary existing policy text by
giving it a new stamp.

Fingerprints include stored expression trees and the PostgreSQL major. A major
upgrade, and a logical restore that changes referenced object identities, can
require exact policy recreation before services start. Rehearse that operation;
copying old comments or accepting a changed fingerprint is not validation.

Any future code-owned policy-definition change must bump `POLICY_VERSION` and
include a migration and cutover plan. Otherwise a structurally valid old stamp
would not tell the new application that its expected policy semantics changed.

Do not disable only part of the inventory or roll back to code that cannot
interpret the stored Read/Write policy contract. In particular, disabling RLS
does not make pre-relationship writers safe: they do not maintain canonical
edges. A successful-cutover rollback needs the same write barrier, a deliberate
compatible application version and a tested database restore or downgrade
procedure. Keep the previous release and backup until verification finishes.

## Implementation references

- [Policy inventory, role checks and activation](../../backend/app/db/table_rls.py)
- [Transaction-local tenant binding](../../backend/app/db/table_tenant.py)
- [Operator command](../../backend/app/commands/tables_rls.py)
- [Managed maintenance connection](../../backend/app/db/session.py)
- [Account authorization boundary](../../backend/app/services/account_maintenance.py)
- [Tables membership constraint](../../backend/app/db/models/resource_grant.py)
- [Runtime vector objects and model exclusions](../../backend/app/db/vector_tables.py)
- [PostgreSQL row security and its scope](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [PostgreSQL role membership and privilege inspection](https://www.postgresql.org/docs/current/functions-info.html)
