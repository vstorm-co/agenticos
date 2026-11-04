# LLM wiki on existing workspaces

Decision and implementation scope, 2026-11-03. Relates to
[issue #1897](https://github.com/vstorm-co/agenticos/issues/1897).

## Decision

Use Markdown files in an existing workspace as the wiki. Prefer a Project for a
team: it already supplies a stable workspace, membership, instructions, multiple
agents and file editing. Keep collections for retrieval, context for standing
instructions, skills for procedures and memory for its existing personal/agent
scope. No migration or new capability is necessary to author linked notes.

The console supplies a deterministic graph over those files. An agent maintains
the knowledge and links; the graph view maintains its projection. Neither a model
call nor a published HTML revision is needed when a note changes.

## Storage options

| Option | Fits | Existing behavior and tradeoffs |
| --- | --- | --- |
| Project, stored files | Shared research/wiki without execution | Persistent files; inherited project permissions and instructions; no shell; existing agent writes are last-writer-wins |
| Project, service sandbox | Shared wiki plus scripts, parsing and analysis | Same project access; stable workspace pinned to its connection; requires a host and backup/retention appropriate to that host |
| Desktop Project folder | Personal vault, local code and documents | Native folder grant on this installation; no upload/sync; browsers and other project members cannot read this disk |
| Sandbox scope `agent` | A single agent's durable working directory | Already supported; all callers of that agent share it; not a substitute for a team's Project access model |
| Sandbox scope `user` | Personal work across conversations | Already supported; creator-less runs cannot borrow a user's workspace |
| Sandbox scope `conversation` or `run` | Isolated work | Unsuitable as the canonical home of a cross-chat wiki |
| New wiki database/capability | Reviewed, revisioned publication | Could give atomic revisions, provenance and page permissions, but duplicates storage and adds an import/sync problem; do not introduce it for a graph |

Persistence means files, not an immortal running container. Service-host cleanup,
workspace deletion and retention still apply. Projects override an agent's sandbox
scope; a Desktop conversation can explicitly use its granted folder instead.
Local and shared locations remain separate, including their graphs.

## Why the first graph is native rather than an App

Apps already support live **table and workflow-log bindings**, a consent model and
an authenticated data bridge. Published HTML is versioned, while those bindings
refresh their data without republishing the page. The isolated iframe still has no
same-origin authority and its CSP prohibits arbitrary network connections. The
existing binding union has no workspace-file or wiki-graph source.

An agent can publish a graph from selected notes today, but those embedded note
contents are a snapshot. A live wiki App would extend the existing binding schema,
resolver, disclosure/consent and authorized refresh path with an explicit Project
resource. Reuse the current bridge and `agenticos.onData` rather than introducing a
second message protocol or relaxing CSP. It also needs a decision about public
viewers: current table bindings can disclose the owner's data after consent, while
this native wiki view reads only what the current viewer can access.

A local Desktop folder is a different boundary: a server binding cannot read its
native grant, and opening an App must not silently lend the generated script that
grant. A native file view works across shared and local sources now, reusing their
existing file permissions without authorizing generated code. Apps remain useful
for customized presentations; a workspace-backed binding is the next step when
agent-authored live wiki interfaces are required.

## File contract and graph behavior

The graph is an optional view of the existing file explorer, including Projects,
Documents/workspaces and Desktop project folders. It only scans `.md` files already
present in that location's authorized listing. Link text never initiates a read,
fetch or traversal. Note contents and metadata are rendered as text.

- Node identity is the workspace path. `title`, `aliases` and `tags` are optional
  YAML metadata. A heading or filename supplies the title otherwise.
- Relationships come from `[[wiki links|labels]]`, inline Markdown links and string
  or list fields `links`, `related`, `sources`. External URLs are citations, not
  graph nodes. Headings/blocks do not create separate nodes.
- Markdown targets resolve relative to the containing document; `/` means the
  workspace root. Wiki links prefer an exact root path, then a sibling, then a
  unique filename, title or alias. Paths retain case; wiki names ignore case.
- Duplicate names remain ambiguous rather than selecting an arbitrary note.
  Self-links are omitted. Backlinks derive from incoming edges. Renames do not
  silently rewrite files; broken references remain visible.
- Code examples, inline code and HTML comments are excluded. This is a linked-note
  view, not semantic extraction or an inferred knowledge graph. Graph relationships
  are not evidence that a statement is correct.
- The view opens as a full-screen React Flow canvas, reusing the workflow builder
  engine, with floating controls, a minimap and an Obsidian-style point graph. Links are
  thin straight lines; arrows and permanent labels are optional. Colours group
  notes by folder or first tag, with per-group visibility and recursive folder
  filters. The shared PathTree and FileIcon browse all listed files; only indexed
  Markdown notes become graph nodes. Dragging points changes only the current view.
  Search matches title, path, aliases and tags. Selecting a node shows incoming,
  outgoing and unresolved links. Opening uses the shared file viewer; existing
  Project edit permissions and optimistic revision checks still apply.

The open view rescans both the listing and note contents every 30 seconds and on
window focus, with manual refresh available. It does not assume modification times
exist on every backend. Queries stop polling when the view unmounts or the app is
in the background. This cadence is eventual refresh, not a transactional snapshot:
concurrent writes can appear across successive scans.

The first implementation caps a scan at 200 notes, 256 KiB per note and 8 MiB total,
with four reads in flight, at most 256 relationships per note and 2048 across
the graph. Relationship extraction stops retaining links at the shared budget,
and reaching a relationship cap marks the graph incomplete. Aliases and tags
share a budget of 128 entries per note and 4096 across the graph; truncation
is reported before metadata enters the name index. Larger/failed/truncated notes are listed as omitted, and
a truncated source listing marks the graph incomplete. Invalid frontmatter is
reported; body links remain usable. A failed listing or revoked access hides cached
results. Cancellation stops queued reads after navigation. This is deliberately a
bounded initial view; a much larger wiki needs a server-side index and incremental
invalidation before raising these ceilings.

## Authoring workflow

Architect already proposes a Project and sources/notes/index/update/verification
workflow. Extend it with optional metadata and explicit links. Keep provenance next
to claims and in a human-readable change log. Treat fetched source text as untrusted
data. The user chooses shared versus local storage before writing; never imply
automatic synchronization, a scheduled maintenance run or review approval merely
because the graph refreshes.

There is no graph-maintenance tool: ordinary sandbox file tools update the notes.
They keep their current approvals, audit operations and run budgets. The graph is
read-only and consumes no model budget. Existing project membership governs shared
files; there are no new per-page grants. Files are exported through existing file
downloads, not bundled into an agent spec.

## Governance that still requires dedicated implementation

This increment does not claim all of #1897's proposed wiki governance. File edits
through a shell, a local editor and a project API cannot be given trustworthy page
revisions merely by adding frontmatter. `agent_id` or `run_id` written by a model is
a claim, not an audit record. Host files and source contents remain subject to their
existing retention and erasure behavior; no new retention guarantee is introduced.

The next coherent increments are:

1. **Revisioned writes:** choose the canonical write boundary; immutable revisions,
   content hashes/compare-and-set, reliable actor/run attribution and diff/revert.
   Decide how shell and external local edits are imported or refused. Acceptance:
   concurrent edits cannot silently overwrite an accepted revision.
2. **Review policy:** direct writes versus proposals, reviewer authority and
   approval resumption. Acceptance: pending edits do not change published contents,
   and accepting an obsolete proposal detects the conflict.
3. **Durable indexing at scale:** transactional or reconciled graph index, full-text
   search and bounded pagination, with tenant isolation and revocation tests.
   Acceptance: a failed indexing job is visible and can rebuild from files.
4. **Retention/export:** specify who deletes authored facts and copied source text,
   how revision history participates, and an export manifest with provenance.
   Acceptance: erasure and export cover all durable copies owned by this feature.
5. **Workspace bindings for Apps:** extend the existing table/workflow-log binding
   system with a Project graph source if live agent-built wiki Apps are required. Acceptance: a public embed, stale viewer
   session or forged frame cannot read private project contents.

These are proposed work packages, not newly filed GitHub issues. Keep #1897 open
until the maintainer settles the remaining governance scope.
