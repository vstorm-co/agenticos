---
name: platform-tables
description: "Build useful AgenticOS tables with typed columns, rich-text notes, real user/agent references, views, default Kanban and conflict-safe writes. Reuse managed Task boards for TODOs and connect records to workflows and Apps."
category: data
---

# Design around the next decision

Discover existing tables and inspect their columns and current schema version.
Decide which entity one row represents, its stable identity, audience and the
questions people need to answer. Start small: title, controlled state, actual
relations, useful dates and rich-text Notes. Use English status and column names
by default unless the person explicitly requests localization. The content of a
record remains in the language its author chose.

## Choose correct semantics

| Data | Type or mechanism |
| --- | --- |
| A document, detailed note or checklist | `rich_text`, not a one-line text field |
| A responsible person or agent | `user` or `agent`, not their name as free text |
| Which actor has the next action | Controlled select, separate from the responsible person |
| A state | `single_select` with a small, meaningful set of transitions |
| A count, amount or comparison | Numeric type and explicit unit/currency |
| A calendar date versus a scheduled instant | Date versus datetime; state the time zone |
| Related records | The actual relation/link type supported by the schema catalog |
| A source-system object | Stable external ID; not a title used as identity |

Do not duplicate automatic created/updated dates or author in Markdown. Keep
queryable properties in columns, not frontmatter. A rich-text column default
can supply a reusable document template; omitted values use the default while
explicit content wins. Validate one realistic record before bulk writes.

For TODOs use `ensure_task_board` for private, project, group or organization
scope. Do not build a second independent status list. Managed boards own stable
core columns and choices; add optional custom columns without changing their
meaning. Keep both Person and Agent while Next step selects who acts. Start at
launches work or a reminder; Due at is the deadline. Assignment does not grant
access to another person's account. An agent result waits for human review.

## Write and evolve safely

Use the platform table tools for discovery and record operations. For schema
updates send the complete current column list, preserving IDs and using
`expected_version`. Archive retired columns; inspect formula, lookup, workflow
and saved-view dependencies before changing types. Do not throw away a person's
data merely to make a schema validate.

Updates require the record revision actually read. Omitted cells remain; null
clears a nullable field. On conflict reread and reconcile rather than repeating
the stale write. Use upsert with a stable external ID for source deduplication;
this does not make an external send idempotent. Page through `has_more` when an
answer claims completeness.

## Make the table usable

Use Kanban for task state, a grid for comparison/editing, and a list for documents.
Create purposeful saved views rather than cosmetic duplicates: Open tasks,
Agent tasks, Waiting for review. A shared saved view can be set as the table's
default in the toolbar; managed task boards start in Kanban. A URL view override
wins. If no tool to set the default is offered, say that this UI action remains
instead of claiming it happened. A view filters records; it never grants access.

For a live App, bind queries to the table rather than copying records into HTML.
Show empty, unavailable and truncated results honestly, and verify its audience:
published binding data is read with the page owner's access. For table events,
filter state transitions and avoid a workflow that triggers itself on every write.
Return the table link, schema/view decisions and the verified record operations.
