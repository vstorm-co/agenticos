---
name: virtual-tables
description: Design and use AgenticOS typed tables for an automation's records, state, notes and reporting.
category: data
---

# Structured records for an automation

Use a Virtual Table for contacts, requests, jobs, statuses, tracking and typed
records that people or workflows must read and update. Use a knowledge base for
retrieval from long reference documents, a context file for standing instructions,
and a project for ongoing work with files. Never store credentials in a table.

Use these tools through the AgenticOS platform MCP server (`account: platform`),
with an allowlist for the operations the agent needs. Writes remain approval-gated
and the requesting member's table access still applies. Keep legacy `virtual_tables`
capability grants intact unless the person explicitly chooses to change access.

## Reuse and design

Search `list_virtual_tables`; inspect a match with `get_virtual_table`. Reuse its
stable column IDs and current schema version. Design a small schema around the
queries and next action: a short name, a status, dates, identifiers, required
values and useful defaults. Use numeric/date types for comparisons, select types
for a controlled status, links for actual record relationships and `rich_text`
for Markdown notes, including optional YAML frontmatter. Frontmatter stays part
of the document; it does not create queryable table columns. The console edits
custom properties above the body; created/updated dates and author come from the
record itself, so never fabricate them in Markdown. For a reusable document
template, set the rich-text column’s `default`. Omit that cell on creation to
apply the template; explicit content, including an empty string, takes priority.
Changing the default affects new records only. Select defaults in a schema may
name live option labels or IDs; stored defaults use IDs. Options accept `color`
as gray, blue, green, yellow, purple or red; null chooses the automatic palette.
The console always shows immutable record dates and actors. These remain in the
API record envelope, not writable cell values.

`create_virtual_table` creates a private table through approval. For a schema
change, submit the complete existing column list through
`update_virtual_table_schema`, preserving IDs, against `expected_version`.
Archive obsolete columns rather than dropping them. The service reports
incompatible values and dependencies; do not mask those refusals.

## Records and workflow bindings

Read the table schema before writing. `query_virtual_table` accepts filters,
search and sort, returns `items` and `has_more`, and needs paging for a complete
answer. Text search includes the source of Markdown notes. A saved view narrows a
table; it never grants access to its records.

`add_virtual_table_record` returns a record and its revision.
`update_virtual_table_record` requires the revision actually read. Omitted cells
stay; null clears a nullable cell. On a conflict, reread and reconcile with the
person's edits. Use an external ID to identify a source-system record; it does
not by itself make every external side effect idempotent. Use
`upsert_virtual_table_record` with the read revision for an existing record;
`get_virtual_table_record`, `virtual_table_record_exists` and
`list_virtual_table_views` support discovery. Delete only through
`delete_virtual_table_record` with the revision actually read. Source identities
are authoritative record metadata; never imitate a person by writing their name
into Markdown.

For an automation, inspect `table.record.create`, `table.record.update` and the
query steps in the workflow catalog. Pin the real table ID and schema version;
bind input values to actual column IDs or labels. A table-record trigger can
start work after an add, change or deletion. Avoid feedback loops when that
workflow writes the same table; filter on meaningful status transitions.
Verify the actual created or changed record, not only the workflow's run state.
