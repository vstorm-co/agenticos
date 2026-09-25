# Workflows: visual editor, configuration, testing and publication

Design for #1787, part of #56 (Workflows + Virtual Tables, W8–W12). Depends on
#1781 (decided: build on `@xyflow/react`, not `@workflowbuilder/sdk`) and #1786
(planning only — [1786-node-contracts.md](1786-node-contracts.md) is the
authoritative shape this document is written against; its parent
[shared contracts](56-shared-contracts.md) page is the summary). See the
[implementation plan](56-workflows-tables-implementation-plan.md) for status
and build order.

Written 2026-09-22 against #1786's *planned* models, not yet code — confirm
`NodeDefinition`, `WorkflowGraph`, `Binding` and the nine validation rules
still hold before implementing.

## What #1787 is not

No execution: test runs need #1788's durable run state and are designed only
as far as the frozen-snapshot contract, flagged below. No node library beyond
the catalog #1786 ships (`debug.echo` only at first); #1789–#1792 populate it.
No nested canvas for `foreach`: #1781's lab proved a scope switch with a
breadcrumb, carried forward rather than reopened.

## Page and route structure

```
src/app/[locale]/(dashboard)/workflows/
  page.tsx                    # list: draft / published / archived, create, duplicate, templates
  [id]/page.tsx                # the editor — canvas + palette + property panel
  [id]/runs/page.tsx            # run history (needs #1788; list only)
  [id]/runs/[runId]/page.tsx    # per-step inputs/outputs/costs (needs #1788, see Test runs)
```

Mirrors `agents/`, `agents/[id]/`, `runs/`: `Workflow` is draft/published/
archived like `Agent`, so the list reuses that tab and empty-state shape.
`src/hooks/use-workflows.ts` over `src/lib/workflows-api.ts`, query keys in
`query-keys.ts`. The editor loads the workflow (`WorkflowRead`, carrying
`draft_graph`/`draft_revision`) and the node catalog
(`GET /api/v1/workflows/node-catalog`) into TanStack Query, and hands both to
a workflow-scoped Zustand store (`workflow-editor-store.ts`) owning
everything ephemeral: selection, clipboard, undo/redo stack, scope path,
dirty flag, conflict-banner state. Server data never lives in the store.

"Duplicate" copies the current draft graph into a new `Workflow` (never a
`WorkflowVersion`). "Create" offers a blank canvas or a template (static JSON
in the frontend for v1). **The editor tree is keyed on `workflowId` and fully
remounted on switch** — `@xyflow/react`'s `<ReactFlowProvider>` is
per-instance, not a module-level singleton the way `@workflowbuilder/sdk`'s
store was, so the class of bug #1781's lab reproduced (one workflow's
autosave overwriting another's) is structurally harder to hit. The autosave
dispatcher still carries its own generation guard (below) regardless, since
that failure was in the lab's own timer code, not only the SDK's.

## Canvas shell, on `@xyflow/react`

Confirmed: `@xyflow/react` is not yet in `frontend/package.json` on `main` — a
new direct dependency, MIT, bringing `@xyflow/system` and the `d3-*` packages
(ISC). Update `THIRD_PARTY_NOTICES.md` in the same change (`make licenses`).

`src/components/workflows/canvas/`:

- `workflow-canvas.tsx` — `<ReactFlow>` in `<ReactFlowProvider>`, `<Controls>`,
  `<Background>`, no `<MiniMap>` in v1. Read-only mode (a published
  `WorkflowVersion`) reuses it with `nodesDraggable={false}` and no handles —
  the posture `agent-map.tsx` already uses for a different, hand-built canvas.
- `nodes/` — one component per `NodeDefinition.kind`. `Port.kind: Literal
  ["input", "output"]` (round 3 of this review: a third, still-stale copy
  of this resolved question, after the two already fixed in this document
  in rounds 1 and 2) decides handle placement directly; the canvas never
  infers direction from a port id convention. An error port gets a visually
  distinct handle regardless. `isValidConnection` mirrors rule 3
  (type-compatibility) client-side, refusing an incompatible drag before it
  draws.
- `edges/` — typed edges: normal data, error, and `logic.if`/`logic.merge`
  branch labels.
- Agent-map is hand-rolled, read-only SVG pan/zoom with no drag/connect
  model — no `@xyflow/react` precedent to reuse, as #1781's estimate assumes.
- **Accessibility from the first commit.** #1781's lab found 8 of 10 SDK
  controls had no accessible name and no confirmed keyboard-only connect
  path. Every icon-only control gets a translated `aria-label`; palette
  click-to-add is the accessible add path; a keyboard "connect mode" (pick a
  source port, then a compatible target) is budgeted rather than assumed.

## Palette

`src/components/workflows/palette/node-palette.tsx`, backed by the
`NodeCatalog` query, grouped by category, icon + name + description.

- **Drag or click to add** — drag for pointer users, click-to-add (near
  viewport center or the selected node) as the keyboard/touch path.
- **Scope filtering** reads the store's scope path. What is valid inside a
  `foreach` body is whatever #1786's nested-scope-boundary rule allows
  structurally, not a second frontend denylist; the palette additionally
  hides boundary-shaped node kinds inside a body and blocks a second
  `control.foreach` once the fan-out limit is hit.
- Search over name/description/category (`useListControls`, as
  `collection-picker.tsx` uses).

## Property panel: the form renderer

The hardest new UI primitive in the milestone — #1781's cost table puts
binding-aware fields at 5/8/14 days, its largest line, and names the #1786
catalog contract as deciding "how property forms and bindings work."
`1786-node-contracts.md` fixes the shape this designs against:

- `NodeInstance.config: dict[str, Any]` holds only `config_schema`-typed,
  literal, static settings — including resource pins (`table_id`,
  `agent_id`/`version_id`), picked through a resource picker, never bound.
- **A field's runtime value never lives in `config`.** It is a `Binding
  {target_node_id, target_field, source}` in the graph's flat `bindings`
  list, where `source` is `NodeOutputRef {node_id, port}`, `TableIORef`,
  `FileRef` or `LiteralValue {value}`. Every `input_schema` field works this
  way — `LiteralValue` for "type a value," the rest for "read it from
  somewhere else." A `config_schema` field opts in via `x-bindable: true`
  (the slot `schema-form.tsx` already reads `x-multiline`/`x-suggestions`
  from) for a setting that legitimately varies per loop item.

### Extending `schema-form.tsx`, not replacing it

`schema-form.tsx` (523 lines) stays the base for scalar leaves —
string/number/boolean/enum/suggested, with its masking/placeholder/`x-*`
conventions unchanged. It has no array beyond a list of strings, no nested
object, no `$ref`, no union, no notion of a bound value. The new
`property-panel/node-form.tsx`:

1. **Resolves `$ref` against `$defs`** before rendering — the primitive
   missing to render anything beyond a flat bag.
2. **Renders a nested object as a fieldset**, recursing into the same
   renderer rather than a parallel one or a modal.
3. **Renders an array of objects as repeatable rows** — add/remove/reorder
   over the recursive renderer per item. #1781's lab hand-wrote exactly this
   once for `table_write.mappings` ("the SDK has no control for a list of
   rows"); here it is the renderer's general case, not a one-off.
4. **Renders a discriminated union** (Pydantic v2's `oneOf` with a `const`
   discriminator per branch, the shape #1786's own `NodeResult` uses) as a
   `Select` over branch values plus the matching sub-form, swapped wholesale
   on change.
5. **Wraps every binding-aware leaf** (every `input_schema` leaf, every
   `x-bindable` `config_schema` leaf) in `BindingField`.

### `BindingField`: literal or reference

`target_field` is a plain string in #1786's `Binding` model. For a leaf
nested in an array-of-rows or object (`mappings[0].value`), this document
recommends a JSON-Pointer-style path (`mappings/0/value`) as the convention —
a wire contract the frontend and the validator both need to agree on,
flagged below.

`BindingField` wraps whichever control the leaf's schema calls for (a
`schema-form.tsx` scalar, or a resource picker for a `TableIORef`/`FileRef`
leaf) and reads/writes the `bindings` list by `(target_node_id,
target_field)`, never `config`:

- **Literal mode** — a `LiteralValue` entry; the ordinary control edits
  `.value`, so a scalar leaf gets exactly `schema-form.tsx`'s existing input,
  wrapped rather than reimplemented.
- **Binding mode** — a toggle (translated `aria-label`, never free text —
  #1786 forbids client-supplied expressions) switches to a `Select` picker.
  Candidates are every upstream `(node, port)` reachable on every path that
  reaches this node — rule 4's dominator check — filtered by schema
  compatibility — rule 3 — both mirrored client-side. Choosing one writes
  `NodeOutputRef {node_id, port}`; candidates group by source node (icon +
  name) and show declared type, the density `collection-picker.tsx` already
  uses to disambiguate same-named rows.
- Toggling replaces `Binding.source` wholesale (`SchemaField`'s existing
  convention: discard a stale shape rather than merge it).
- An `input_schema` leaf with no `Binding` targeting it is a validation
  problem (required input unfilled), not a silent default.
- **Dynamic choices** (table → columns): the column picker's list is a query
  keyed on the sibling `table_id` field's *current* value — the same
  `x-suggestions`-against-a-list mechanism, fed a live list instead of static.

### Panel shell

Docked right-hand panel: header (name/kind/category — `NodeInstance` has no
per-instance label in #1786's model, so the header shows the catalog name,
disambiguated by a short id suffix until #1786 adds one), the form, empty
and multi-select states (bulk delete only in v1). A narrower edge panel
reuses the same renderer over an edge's own schema fragment (a `logic.if`
condition, an error-edge retry override).

**Validation display**: a warning badge + count on a node with any
client-side problem, a per-field message in `schema-form.tsx`'s `error` slot,
and a collapsible problems list in the footer linking to each offending
node/field — the same "field-scoped problems, collected together" shape
#1786's `GraphValidationError` uses server-side.

## Resource pickers

`src/components/workflows/pickers/`, following `collection-picker.tsx`'s
shape (disambiguating context, an orphaned-reference state, a create-new
escape hatch):

- **Agent + version** — two-step; changing the agent clears the pinned
  version, per #1781's lab finding. A workflow always pins a specific
  version.
- **Collection** — `collection-picker.tsx` reused as-is.
- **Table + column** — new; no tables-list endpoint exists on `main` yet.
  Built against `TableIORef` (`table_id`, `column_ids`, `schema_version`)
  once #1784 ships listing routes: table picker with row/column counts,
  column picker scoped to the table's *current* schema. A binding whose
  `schema_version` no longer matches gets the orphaned treatment plus a
  field-scoped "table schema changed since this was bound" banner — #1784
  revalidates at execution time regardless.
- **Secret** — the existing vault secret-selection pattern (kind/metadata
  only, never a value) for a config field needing a credential reference; a
  vault secret id in `config`, never a value.

### Client-side validation against #1786's eight rules

Each `validate.py` rule (exactly-one-input, reachable-outputs, type-
compatibility, branch-local data availability, exclusive-merge, nested-scope
boundaries, no cycles, no parallel fan-out) gets a pure TypeScript mirror,
run on every edit against the store's in-memory graph. Not polish: the
binding picker's candidates *are* rule 4, and a refused canvas connection
*is* rule 3. The mirror is deliberately non-authoritative — publish always
re-validates server-side, and drift degrades to a worse editing experience,
never a correctness bug, since nothing client-side executes. A fixture-graph
drift test (both implementations, same inputs) belongs in this issue's tests.

## Nested `foreach` editing: a view filter, not a nested document

`WorkflowGraph` is **flat** — `nodes`, `edges`, `bindings` are single lists;
nesting is `ScopeBoundary {scope_node_id, body_node_ids, entry_port,
exit_port}` entries, not a recursive subgraph (#1781's lab stand-in used a
nested `body: WorkflowGraph`; #1786's real model does not). The editor should
use this, not reproduce the lab's recursion:

- The store holds `scopePath: string[]` (foreach ids root-to-current). The
  visible set for a scope is the flat lists intersected with the relevant
  `ScopeBoundary.body_node_ids` — root scope is every node in no boundary.
- Breadcrumb, palette scope-filtering and binding-picker reachability all key
  off this filtered view — the same proven UX #1781's lab validated two
  levels deep, computed over one document instead of a nested body.
- Autosave, undo/redo and publish need **no scope-aware branching** — a scope
  switch is a display change only, simpler than the lab needed since there
  is no separate body graph to splice back.
- **Resolved by #1786** (round 1 of this review: this section was still
  calling it an open question after #1786 had already answered it):
  `body_node_ids` is server-derived from edge topology, never
  client-authored. Dropping a node inside a `foreach`'s scoped view is
  still a local store update for the editor's own purposes — it draws
  edges and positions like any other node placement — but the client never
  writes `body_node_ids` itself, and a draft save that implied a different
  membership than what the server recomputes from the graph's actual edges
  has that implication silently overwritten, not honored.

## Autosave, `expected_revision`, and the conflict banner

Builds on `Workflow.draft_revision` and `PATCH /api/v1/workflows/{id}/draft`
(`WorkflowDraftUpdate {graph, expected_revision}`) — the one part of this
document with a working, tested reference implementation to port:

- A ~400 ms-after-quiet debounce (ours, not inherited) calls the draft route
  with the current graph and the last-known `expected_revision`.
- **Guarded save**, porting `createGuardedSave`'s shape: refused client-side
  if the originating editor instance is no longer current (a generation
  counter bumped on remount) or the in-memory workflow id no longer matches
  the request being built. Kept even though the keyed-remount design makes
  the lab's exact reproduction harder — it also guards a slow request
  completing after a same-workflow navigation away.
- A `409` (`RevisionConflictError`, #1782's existing shape) surfaces the
  conflict banner — "This draft changed elsewhere," **Overwrite** (resend
  with the server's `current_revision`) or **Reload** — exactly what #1781's
  lab proved for both a stale revision and a forced conflict.
- **No cross-workflow/cross-organization leak** (an explicit acceptance
  criterion): the draft cache key includes `workflowId` and
  `organizationId` (already implicit via `apiClient`'s header); the editor
  store is destroyed, not reset, on unmount.

## Publish as an immutable version

`POST /api/v1/workflows/{id}/publish`, also `expected_revision`-gated, runs
`validate_graph()` server-side and creates a `WorkflowVersion` never updated
after insert. The editor runs the client-side validation mirror first and
blocks submission while any problem is outstanding; a server refusal (a rule
the mirror missed, a resource that went away) reuses the panel's field/edge-
scoped error display. "Restore to draft" needs no special mode — the draft
already exists independently of any published version, so editing after
publish is just continuing to edit it, with a version-history list (each
entry viewable read-only) alongside.

## Test runs — designed, not buildable until #1788 exists

Frozen snapshot, mock vs. real, per-step inputs/outputs/costs from persisted
events all name #1788's own `WorkflowRun`/`NodeRun`/event contracts, which do
not exist at planning tier. Design to build once #1788 lands:

- **Frozen snapshot** — "Run test" snapshots the current draft graph into
  `WorkflowRun.draft_graph_snapshot` (round 3 of this review: an earlier
  draft said "not published" with no durable place for that to mean
  anything; #1788 now has one — a `WorkflowRun` with `workflow_version_id
  IS NULL` and this column set instead, its own `mode: test`), so edits
  during a long test cannot change what is executing underneath.
- **Mock vs. real, chosen before the run starts** — an explicit toggle, never
  an inferred default. "Mock" returns synthetic output for `read`/`write`
  effect-kind nodes; "Real" is budget- and approval-gated like production,
  clearly labelled. What is mockable is #1788/#1789's contract; #1787 only
  presents the choice.
- **Inspector** (`[id]/runs/[runId]/page.tsx`) — read-only canvas, nodes
  colored by `NodeRun` status, per-node click opening persisted input/
  output/cost from #1788's cursor-based event stream.
- Recommendation: treat `[id]/runs/**` as **out of #1787's delivered scope**,
  landing once #1788 merges — the one acceptance-criteria half this document
  explicitly defers rather than silently drops.

## Undo/redo and copy/paste

Ports #1781's lab algorithms as algorithms (~490 lines including stand-in
types), with one real change the flat, binding-list shape both requires and
simplifies:

- **`history.ts`** ports close to unchanged — a bounded snapshot stack plus a
  debounced `Recorder` coalescing a drag into one undo step.
- **Copy/paste re-derives `clipboard.ts` rather than porting it.** The lab's
  version hard-codes binding fields per node kind, and its default branch
  "would silently treat a new node kind as having no bindings" — a real risk
  against a config shape where a binding could be embedded anywhere. #1786's
  model has no such shape: bindings are one flat list keyed by
  `(target_node_id, target_field)`/`NodeOutputRef.node_id`, uniform across
  every node kind. Remapping a selection is therefore: assign new ids to
  every copied node/edge/scope-boundary; for each `Binding`, remap
  `target_node_id`, and remap `NodeOutputRef.node_id` the same way when it
  names a copied node (left alone otherwise, matching the lab's finding);
  keep a `ScopeBoundary` only when fully contained in the selection. This
  never inspects a node's `config`, so the lab's per-kind failure mode does
  not reproduce — a new node kind from #1789–#1792 needs no clipboard change.
- **Clipboard scope**: the Ctrl+C/X/V handler is scoped to the canvas, and
  the clipboard is keyed per organization and workflow, not a module
  variable surviving remounts — the lab's finding, carried forward.
- `save-handler.ts`'s guard logic ports as described under Autosave.

## i18n and accessibility

- Every string in the palette, panel, pickers, conflict banner and publish
  flow goes through `next-intl`; `make lint`'s guard applies to
  `src/components/workflows/**` exactly as elsewhere. No English/Polish-only
  chrome — one of the findings against the SDK, only a win here if the fresh
  build actually follows the console's language switch.
- **Every icon-only control has a translated `aria-label`** — direct fix for
  #1781's "8 of 10 interactive controls... had no accessible name."
- **A keyboard path to every canvas action** — tab order over nodes/edges,
  Enter opens the property panel, click-to-add substitutes for drag, an
  explicit keyboard connect-mode is budgeted rather than assumed to exist.

## Work breakdown

Same shape as #1781's estimate. The top block reuses #1781's own figures for
the canvas/palette/panel core unchanged; the bottom block is this issue's
remaining scope, new judgment at the same granularity, not measured.

| Area | Item | Best | Likely | Worst | Source |
|---|---|---:|---:|---:|---|
| Canvas chrome | Shell, controls, background, read-only mode | 2 | 3 | 5 | #1781 |
| Canvas chrome | Node/edge rendering, ports, connection rules | 3 | 4.5 | 7 | #1781 |
| Canvas chrome | Theming, dark mode | 1 | 2 | 3.5 | #1781 |
| Canvas chrome | Accessibility: focus, keyboard connect, names | 1.5 | 2.5 | 4 | #1781 |
| Canvas chrome | Test harness (jsdom mocks, e2e drag/connect) | 2 | 3.5 | 6 | #1781 |
| Palette | Library, drag/click add, keyboard, scope filtering | 3 | 4 | 6 | #1781 |
| Property panel | Shell: panel, edge panel, empty/multi-select | 2 | 3 | 5 | #1781 |
| Property panel | Form renderer base: rows, nested, `$ref`, unions | 3 | 5 | 9 | #1781 |
| Property panel | Binding-aware fields, typed binding picker | 5 | 8 | 14 | #1781 |
| Property panel | Dynamic choices (table → columns) | 2 | 3 | 5 | #1781 |
| Property panel | Resource pickers: agent+version, collection, table+column, secret | 3 | 5 | 8 | #1781 |
| Property panel | Validation display: badges, field errors, problems list | 3 | 4 | 7 | #1781 |
| **Subtotal (#1781's estimate)** | | **30.5** | **47.5** | **79.5** | |
| List page | Draft/published/archived, create, duplicate, templates | 2 | 3 | 5 | New |
| Foreach editing | Scope-as-view-filter, breadcrumb, scoped filtering | 1.5 | 3 | 5 | New |
| Autosave | Debounced save, guarded dispatch, conflict banner, isolation | 2 | 3 | 5 | New |
| Publish | Client gating, server-error surfacing, version history/read-only | 2 | 3 | 5 | New |
| Client validation mirror | TS port of the 8 rules + drift test | 3 | 5 | 8 | New |
| Undo/redo & clipboard | `history.ts` port; flat-binding-aware `clipboard.ts` | 1.5 | 3 | 5 | New |
| i18n | New namespace, `en`/`pl`/`de` for a large surface | 2 | 3 | 5 | New |
| Tests | Unit + integration beyond the canvas harness; coverage gate | 3 | 5 | 8 | New |
| Docs | New console page, onboarding tour + dashboard widget stops | 1.5 | 2.5 | 4 | New |
| **Subtotal (new to #1787)** | | **18.5** | **30.5** | **50** | |
| **Total** | | **49** | **78** | **129.5** | |

At five days a week, roughly 10/16/26 working weeks against a five-week
window shared with #1786/#1789/#1790 under one owner — the same flag #1781's
record and the implementation plan already raise, restated with this issue's
full total rather than #1781's canvas-only subtotal. Test-run inspection
(#1788-gated) is excluded since it is not buildable yet; add it once #1788's
contracts exist.

## Open questions for #1786

Two of this section's original four items are resolved, not open (round 2
of this review: this list still stated them as open after they were
answered earlier in this same document — `Port.kind` and `ScopeBoundary`
authorship, both per #1786's contract). What remains:

- **`target_field` path syntax** for a binding-aware leaf nested inside an
  array-of-rows or object — this document proposes JSON-Pointer-style
  `a/0/b`; needs confirmation before the form renderer and validator commit.
- **A per-instance node label** — `NodeInstance` has none; the canvas shows
  the catalog's static name, which will not scale to two `debug.echo` nodes
  doing different things.

The table/column picker is buildable **now**, not gated on #1784: it reads
#1782's own already-real `GET /api/v1/tables` and `GET
/api/v1/tables/{id}` (round 2 of this review: an earlier draft named
#1784's list/describe *tools and nodes* as the dependency, but those wrap
the same service for agents and workflow runs — they add no HTTP route the
picker needs, and #1782's routes exist today).
