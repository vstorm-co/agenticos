# Tables (`virtual_tables`)

Lets an agent read and write Virtual Tables: list the tables it may use,
describe their columns, find, list and read records, and create, upsert,
update and delete them. With `allow_create` it may also create a new table.

## Which tables, and what it may do there

The binding's config holds the grants: `tables: [{table_id, operations}]`, with
`operations` drawn from `read`, `create`, `update` and `delete`. The grants are
part of the published spec, which the model cannot change. A tool call that
names another table, or an operation the grant does not include, is refused
before anything is read. An upsert needs both `create` and `update`, because it
creates the record when no record holds the key.

The grant narrows and never widens. Every call also runs the table service's own
access check as the member the run acts for, rebuilt from their current
membership on each call. A table unshared, a role narrowed or a membership
removed stops the next call, even in a run that waited hours on an approval.

## Creating a table is its own switch

`create_table` exists only when the binding sets `allow_create`, and the member
still needs `tables:create` when it runs. Record tools never create tables. A
table the agent creates is usable for the rest of that run. The binding's config
is not changed, so the next run starts from the published grants.

## Same behaviour as every other surface

Every tool calls `VirtualTableService`, the class the console, the API and
workflow nodes call. Validation, revision conflicts, quotas, history, receipts
and audit are the same everywhere. A write's operation key is derived from the
run and the tool call, so a retried call replays its first answer and two
different calls never collide.

## Approval

The five write tools are side-effecting per tool, so an approval policy gates
them and not the reads.

## What it deliberately does not do

It does not change a table's schema, rename or archive a table, or share one.
Those are administrative actions for the console.
