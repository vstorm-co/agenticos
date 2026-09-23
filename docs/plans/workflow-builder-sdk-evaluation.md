# Workflow Builder SDK evaluation

Decision record for #1781, part of #56. Timeboxed prototype of `@workflowbuilder/sdk`
2.3.0 in the AgenticOS frontend.

## Decision

**Do not adopt the SDK. Build the workflow editor on `@xyflow/react` directly.**

The patch count is 2 against a bound of 5 (see [Patches](#patches)), but that holds
only if stylesheet containment is counted as one patch. The record itself says
containment is a fork (a prefixed stylesheet build plus retargeting the SDK's
portals) that nobody estimated. The issue's condition is that the adaptations be
bounded, and for containment that is **not demonstrated**. That is the reason for the
rejection. It is a judgement about an unestimated item, not a measured overrun. Days
of adapter work were not tracked, so the 2-day half of the threshold is a qualitative
judgement too: the prototype reached every case in the issue, and nothing here records
how long that took.

Three findings support it:

- Its stylesheet was not contained in the prototype. It restyles the whole document,
  survives client-side navigation and could not be fixed with tokens. Ways to contain
  it are a forked stylesheet build, an iframe (which would require relaxing the
  console's framing headers), or a cheap layer-order pre-declaration ahead of
  Tailwind's layers. The iframe was tested only as far as the CSP refusal, the fork
  was not attempted, and the layer-order option was not tried; none is shown to be
  impossible. If layer order works, the stylesheet finding shrinks to the
  `<html data-theme>` and `wb-theme` side effects, and the decision would rest on the
  next two findings and on the containment estimate that is still missing.
- Left unguarded, the SDK's autosave timer outlives its editor and wrote one workflow's
  nodes into another workflow's document. Remounting the editor to switch workflow or
  organization worked. The other global state (registries, save status, Strict Mode)
  caused no failure in the lab, though registry growth was read in the source only.
- Half of what the editor needs is not in the package (undo/redo, copy/paste, nested
  scopes, a list-of-rows control), so that code is ours under either engine. The
  parts the SDK does provide are the canvas chrome, the palette and the property
  panel. Building those on React Flow directly is estimated below at about 30, 48 and
  80 engineer-days (best, likely, worst), of which about 18, 28 and 46 come from not
  using the SDK's shell. That is a judgement, not a measurement. It does not settle
  the choice by itself: against the SDK route the net difference is small and its sign
  is uncertain (see [Cost of building on React Flow](#cost-of-building-on-react-flow)).

The workflow milestone's 1-2 working day estimate for this evaluation is unchanged:
nothing here cuts it, as acceptance criterion 3 of #1781 requires.

One optional trigger for a later look: the reviewed upstream commit is already ahead
of 2.3.0 and swaps its UI dependency (`@synergycodes/overflow-ui` for
`@workflowbuilder/ui`), which may change both the package weight and the stylesheet.
The issue says not to extend the experiment automatically, so nothing here schedules
that. See [Not evaluated](#not-evaluated-and-caveats).

## Recommendation and next steps

**Keep the decision: do not adopt the SDK, and build the editor on `@xyflow/react`.**
Confidence is medium. The record rests on a judgement about an unestimated item, and
the estimate below is judgement too.

Why the recommendation holds:

- The SDK contributes the canvas chrome, the palette and simple property fields. The
  rest of the editor is ours under either engine, and the property forms that mattered
  were our own controls. The lab needed about 1,500 lines of adapters around it.
- It carries guards and dependencies the console would live with: a module-level store
  that allows one editor, an autosave that outlives its editor, a second UI kit next
  to Radix, 123 SDK-only packages, English and Polish chrome only, and controls
  without accessible names.
- The day count does not favour it. Choosing React Flow adds about 10 days on a paired
  basis, roughly 12% of the total, and the range straddles zero. Costs the count does
  not capture, such as upstream churn and a beta UI kit, tilt it towards React Flow.

What would change it:

- **The layer-order test.** The one cheap untried experiment, well under a day. If it
  works, the stylesheet finding shrinks to the `data-theme` and `wb-theme` side
  effects. The global-state, missing-feature and dependency findings would remain, so
  it is unlikely to reverse the decision alone. The issue forbids extending the
  timebox automatically, so it needs an explicit go-ahead.
- **A much larger SDK saving.** About 30 days or more would reverse it. Nothing here
  suggests that.

Next steps:

1. Before this PR merges, remove the lab, its two dependencies, their licence entries
   and the changelog entry. Keep the lab reachable, for example by tagging the last
   commit that contains it. What survives is this record.
2. Carry over the algorithms only when #1787 starts: the typed graph, history,
   clipboard and save contract, about 490 lines including stand-in types. They move as
   algorithms, not as files.
3. Flag the schedule. The three editor areas are about ten weeks at the likely figure
   against a five-week window, and the same owner holds #1786, #1789 and #1790.
   Issue #56 already calls for a re-estimate.
4. Settle the #1786 catalog contract early. It is the largest uncertainty, about 8
   days, and it decides how property forms and bindings work.
5. Optionally re-check the SDK at its next release. Upstream is already replacing its
   UI dependency.

Caveats: the estimate and its SDK-side offsets are judgement, the performance figures
are single runs, and some browser claims were not independently re-verified. See
[Not evaluated](#not-evaluated-and-caveats).

## Threshold, set before the lab was built

Issue #1781 says only that the adaptations must be "bounded". The figures below, **at
most 5 patches to the SDK and about 2 days of adapter work**, were set at the start of
this evaluation, before any code was written, and were not changed afterwards. They
are not in the issue text. Nothing better grounded turned up, so they stand.

- A **patch** is a change to the SDK's own source or built output that has to be
  carried across upgrades.
- **Adapter work** is our code around its public API.
- The **half-day rule**: if the SDK's styles are not tamed in the first half day, that
  is recorded as a failure. It was also set at the start of this evaluation and is not
  in the issue text.

## What was built

A development-only lab at `/dev/workflow-sdk`, in
`frontend/src/components/dev/workflow-sdk/`. It is not linked from the navigation, it
renders the not-found page in production builds (checked against `next start`; the
HTTP status is 200 because the response streams under the dashboard layout), and it
is outside the onboarding and dashboard registries on purpose.

| Piece | File | Real or mock |
|---|---|---|
| SDK 2.3.0 mounted in the dashboard layout | `editor-host.tsx` | Real |
| Typed graph: start, agent, table write, foreach with a nested body, end | `typed-graph.ts` | Stand-in for the model #1782 will define |
| Typed graph to SDK document and back | `sdk-adapter.ts` | Real adapter, tested |
| Agent and version picker, on `useAgents` and `useAllAgentVersions` | `renderers.tsx` | Real hooks and endpoint paths; the browser runs answered from stubbed HTTP, because no backend was started |
| Table picker, key column, column mappings | `renderers.tsx`, `fixtures.ts` | Mock: `GET /tables` does not exist |
| Pydantic JSON Schema to SDK node schema | `pydantic-schema.ts`, `fixtures.ts` | Real adapter over a hand-written fixture in the shape Pydantic v2 emits |
| Workflow server with `expected_revision` and HTTP 409 | `mock-workflow-api.ts` | Mock: there is no workflow API yet |
| Save callback, guarded and naive | `save-handler.ts` | Real adapter, tested |
| Undo/redo | `history.ts`, `editor-controller.tsx` | Ours, tested |
| Copy/paste with id and binding remapping | `clipboard.ts`, `editor-controller.tsx` | Ours, tested |
| Bare React Flow baseline | `baseline-flow.tsx` | Real |

The SDK's undo/redo and copy/paste are not in the npm package. The demo app's
versions of both are labelled as Overflow premium features, so they were not treated
as available and not copied. Both were written against the SDK's public store API.

## Results by case

Browser runs were Chromium, headless, driving the dev server unless noted, with the
console's `/api/*` answered by stubs. "Unit" means a vitest spec exists.

| Case | Result | Notes |
|---|---|---|
| Agent and version picker | Works | Radix selects open above the SDK's overlays and take our tokens. Changing the agent clears the pinned version. Requests: `GET /agents`, `GET /agents/{id}/versions?skip=0&limit=100` |
| Virtual Table write config | Works, with custom controls | The SDK has no control for a list of rows, so `mappings` needed a renderer. Table and key column are dynamic, which a static `options` list cannot express |
| Nested foreach | Works as a scope switch, not a nested canvas | The SDK has no parent/child nodes. A foreach's body never enters the SDK; it stays in the typed graph and is re-attached by node id. Two levels deep edited and saved |
| Round trip to the typed graph | Identical at every scope (unit and browser) | Fields the SDK cannot hold (`body`, the `on_conflict` dict) are re-attached from the original; a pasted node carries them in |
| Singleton, Strict Mode, navigation | Works only with guards | See below |
| Save callback bug | Reproduced, avoided in the adapter | See below |
| `expected_revision` and 409 | Works | A stale revision and a forced 409 both surface as a conflict banner with Overwrite and Reload |
| Undo/redo | Works, ours | Rename, delete (through the SDK's confirm dialog), drag and paste all undo. Buttons and Ctrl/Cmd+Z, Shift+Z, Y. Not fired while typing in an input |
| Copy/paste | Works, ours | Every node at every depth gets a new id; bindings that named a copied node are rewritten; bindings to nodes not copied are left. Unit-tested and checked in the browser on a foreach with two nested levels |
| Pydantic schema adaptation | 5 of 7 properties map | See below |
| Keyboard | Partial | See below |
| Bundle and graph performance | See [Measurements](#measurements) | |

### Singleton state

The SDK's store is a module-level global, and its plugin and JsonForms registries
are too. One editor per document is upstream's stated contract.

- **Strict Mode** (on in `next dev`): mount, cleanup and mount again left one active
  editor. No violation was detected.
- **Switching workflow or organization** remounts the editor. The store resets to the
  new document, and the new nodes render. This was exercised through the lab's own
  two-button selector, not the console's real organization switcher.
- **A pending autosave outlives its editor.** The SDK's autosave timer is not
  cancelled on unmount, and the save reads the global store when it fires. The
  autosave (`o4` in `dist/index-CEBfv0NZ.js`) fires only when more than 10 seconds have
  passed since the last load or successful save, and it is debounced by 400 ms. It
  skips `nodeDragStart` and `nodeDragChange` changes, but not `nodeDragStop`.
  Reproduced by waiting past 10 seconds, editing a node, then switching workflow
  inside the 400 ms debounce. With a callback that has no guard, **`acme/wf-a` was
  overwritten with `wf-b`'s nodes**; the lab logged `persisted acme/wf-a r2:
  b-start=B start b-end=B end`. The guarded callback refused it
  (`the editor that scheduled this save is gone`), and also refuses a payload whose
  `name` is not the editor's own.
- **Registries grow.** `registerCustomRenderers` appends on every `<Root>` mount,
  without deduplication. Confirmed in the source, not measured: it is harmless for
  correctness and grows by one copy per mount. Mounting one editor per page and
  keeping `jsonForm` a module constant is the mitigation.
- **Swapping documents needs a remount.** Under `<Root>` with the `props` strategy,
  the SDK copies `name`, `nodes`, `edges` and `layoutDirection` into state on its
  first render (`bB` in `dist/index-CEBfv0NZ.js`), so later prop changes are ignored.
  Only the `localStorage` and `api` strategies call `setState`. Checked in the dist
  source only, not in the browser. The lab keys the editor on the document.
- Text controls commit on blur, not on input. An edit not yet blurred is not in the
  store, so it is lost to the `beforeunload` autosave.

**Iframe outcome, recorded separately.** An iframe would isolate the singleton and the
stylesheet at once, since each frame has its own module registry and document.
Framing a console route is refused by the console's own headers: measured as
`Framing '…' violates the following Content Security Policy directive:
"frame-ancestors 'none'"`, and `X-Frame-Options: DENY` stands behind it. Only
`/api/files/*` and `/api/generated/*` are frameable. Verifying the iframe would mean
weakening those headers, which was not done. It would also need a message bridge for
the graph, saves, theme, session and permissions. Not evaluated beyond the refusal. A
separate browser window isolates the same way and needs no header change, at a cost
in usability.

### Save callback

`DidSaveStatus` is `'error' | 'success' | 'alreadyStarted'`, and the SDK's
`RuntimeIntegrationWrapper` reads a `props` callback's answer with `if (didSave)`.
All three are non-empty strings. The SDK documents this: its `index.d.ts` says
"Today's runtime treats every non-empty resolution as ..." the save finishing. So it
is documented behaviour, not hidden, and it is unchanged at commit `b926e94`
(checked in the source). For a manual save:

| Callback answers | Server did | The SDK showed |
|---|---|---|
| resolves `'alreadyStarted'` | 409 | "Saving diagram successfully" |
| resolves `'error'` | 500 | "Saving diagram successfully" |
| throws | 409 or 500 | "An error occurred while saving diagram" |

The table holds for manual saves only: for an autosave (`isAutoSave`) the SDK shows
no snackbar in any of the three rows. The SDK also coalesces concurrent saves itself,
answering `'alreadyStarted'` while one is in flight, so the adapter needs no in-flight
lock of its own.

The adapter avoids the problem without a patch: `createGuardedSave` resolves
`'success'` only after the server committed and throws in every other case. The
conflict banner is ours, because the SDK's error snackbar cannot say why. An upstream
one-line fix (`didSave === 'success'`) would remove the need.

### Pydantic schema

The fixture has seven properties. Adapted: `$ref` to an enum becomes `options`;
`anyOf [X, null]` unwraps; `integer` becomes `number` with its bounds; a list of
models becomes an array of objects; `required` and defaults carry over.

- Dropped, and reported by the adapter rather than silently: a `dict[str, str]`
  (`on_conflict`) and a `list[str]` (`tags`). The SDK accepts arrays of objects only.
- Not expressible: a `required` field inside an array item (the SDK's array schema
  has no `required`), so an empty `column` reaches the adapter and is refused in
  `fromSdkScope`. Dynamic choices such as the list of tables never come from Pydantic.
- The SDK also writes its own validation results (`errors`, `customErrors`) into
  `properties`; the adapter strips them.

### Keyboard

- Tab order reaches the top bar, the edges and the nodes. A focused node opens its
  properties on Enter and moves with the arrow keys. Escape closes the delete dialog
  and returns focus to the node.
- The SDK's select-all and zoom shortcuts fire only when focus is inside the
  diagram. Zoom was confirmed with a node focused. Select-all did not select in the
  run, and was not investigated.
- 8 of the 10 interactive controls in the editor had no accessible name (icon-only
  buttons).

### Styling

`sdk-theme.css` maps the SDK's accent ramp, font and background onto our tokens in
39 lines, and the editor follows the console's light and dark class. That part is
bounded and looks right in both themes.

What tokens cannot reach is the SDK stylesheet's own global rules, measured against
`/agents` loaded fresh:

| After the SDK loads | Cause | Reachable by a token |
|---|---|---|
| Whole page in Poppins | `*{font-family}` | Yes (mapped) |
| `body` background changed | `body{background-color}` | Yes (mapped) |
| `body{overflow:hidden}` | `body` rule in the SDK's `@layer reset` | No: a second global override was added |
| `.font-mono` renders in the body font | The SDK's `*{font-family}` sits in its `@layer reset`. Its stylesheet loads after ours, so its layers are ordered after our `@layer utilities` and win | No token; not patched. A layer-order pre-declaration was not tried |
| `<html data-theme>` set, `wb-theme` written to localStorage | SDK theme code | No |

These persist after navigating from the lab to `/agents`, in the dev server and in a
production build. The stylesheet begins `@layer reset,ext-lib,ui;`, and its `*` and
`body` rules sit inside those layers; only the `:root` and `html[data-theme]`
custom-property blocks are unlayered. Layer order follows first appearance, and ours
(`@layer utilities` in `globals.css`) comes first, so the SDK's layers outrank it.
Declaring the order ahead of Tailwind's layers (for example
`@layer reset, ext-lib, ui, theme, base, components, utilities;`) is a possible cheap
containment for the font and `body` rules. It was not tried, because the issue says
not to extend the experiment, and it would not address the `<html data-theme>` and
`wb-theme` localStorage side effects.

The heavier routes are a stylesheet rebuilt with a prefix and the SDK's portals
(modals, snackbar, select popups, which render into `body`) pointed at our scope, or
an iframe. The fork was not attempted, and the iframe stopped at the console's
framing refusal, since relaxing those headers for one route was not done. So this is
not shown to be impossible, only not achieved in the prototype.
Recorded as **not tamed: failed**, under the half-day rule set at the start of this
evaluation (it is not in the issue text).

## Patches

Needed to meet the 5-patch bound, none applied:

1. Contain the stylesheet (build-time scope or prefix, and portal targets). Counted
   as one patch, though it is a fork nobody estimated.
2. Give the icon-only buttons accessible names.

Avoided by the adapter, upstream fixes wanted: the `didSave` truthiness, the autosave
timer that survives unmount, and the append-only renderer registry (mitigated by
mounting one editor with a module-constant `jsonForm`).

Not avoided, residual: the "Saved data has been restored" snackbar on every mount (no
lab code suppresses it) and commit-on-blur text controls (an unblurred edit is lost to
the `beforeunload` autosave).

Count: **2 of the 5 allowed**, with the containment caveat above.

## Adapter work

Measured with `wc -l`: 1,554 lines of adapter source, 1,046 lines of lab UI, mocks
and fixtures (`baseline-flow`, `editor-host`, `fixtures`, `mock-workflow-api`, `perf`,
`sdk-theme.css`, `workflow-sdk-lab` and the route's `page.tsx`), and 777 lines across
the 7 test files.

The algorithms carry over to React Flow directly, not the files verbatim:

- `typed-graph.ts` is a stand-in for the generated API types.
- `clipboard.ts` hard-codes the stand-in's binding fields, and its default branches
  would silently treat a new node kind as having no bindings.
- `save-handler.ts` imports its error classes from the mock server and `fromSdkScope`
  from `sdk-adapter.ts`.

These modules move once the real editor exists, and were not refactored for that.
The algorithms in question total about 490 lines including the stand-in types:
`typed-graph.ts` 127 (63 of them the stand-in types and 64 the helpers), `clipboard.ts`
143, `history.ts` 122 and the guarded save in `save-handler.ts` 98, which excludes the
lab-only `createNaiveSave`. Without the stand-in types it is about 427 lines.

| Module | Lines | Survives without the SDK |
|---|---|---|
| `typed-graph.ts`, `clipboard.ts`, `history.ts` | 392 (329 without the stand-in types) | The algorithms, not the files |
| `save-handler.ts` | 111 | The guards and 409 mapping, yes |
| `sdk-adapter.ts` | 244 | Partly: the strict parse, not the SDK node shape |
| `editor-controller.tsx` | 238 | Partly: history and clipboard wiring |
| `pydantic-schema.ts` | 192 | Only if property forms stay schema-driven |
| `renderers.tsx`, `nodes.ts` | 377 | Controls yes, palette definitions no |

This is a measure of size, not of days. Days were not tracked: the prototype reached
every case in the issue, and this record does not say how long that took, so the
2-day half of the threshold rests on judgement. Work the SDK would
still need is unbounded or unestimated: stylesheet containment, accessibility
patches, whether its English and Polish chrome follows the console's language switch,
and real API and permission wiring. That is a judgement about risk, not a measured
overrun of the bound.

## Cost of building on React Flow

This answers what the Decision left open: what the canvas chrome, the palette and the
property panel would cost on `@xyflow/react` instead of the SDK. **It is a judgement,
not a measurement.** Days were not tracked in the lab, so the figures are ranges for
one experienced engineer who knows the repository. They are implementation only: the
one test row included is the canvas test harness. They are a planning input for #1787
and do not change this evaluation's own 1-2 day estimate.

### Estimate, in engineer-days

| Area | Item | Best | Likely | Worst | Needed with the SDK too |
|---|---|---:|---:|---:|---|
| Canvas chrome | Shell and chrome: provider, controls, minimap, toolbar, read-only | 2 | 3 | 5 | No |
| Canvas chrome | Node rendering, ports, edges, connection rules | 3 | 4.5 | 7 | No |
| Canvas chrome | Theming and dark mode | 1 | 2 | 3.5 | No |
| Canvas chrome | Canvas accessibility: focus, a keyboard way to connect, names | 1.5 | 2.5 | 4 | No |
| Canvas chrome | Canvas test harness (jsdom mocks, drag and connect in e2e) | 2 | 3.5 | 6 | No |
| Palette | Node library, drag and click to add, keyboard, scope filtering | 3 | 4 | 6 | No |
| Property panel | Shell: docked panel, header, edge panel, empty and multi-select states | 2 | 3 | 5 | No |
| Property panel | Form renderer base: arrays of rows, nested objects, `$ref`, unions | 3 | 5 | 9 | No |
| Property panel | Binding-aware fields and the typed binding picker | 5 | 8 | 14 | Yes |
| Property panel | Dynamic choices, such as a table and then its columns | 2 | 3 | 5 | Yes |
| Property panel | Resource pickers: agent and version, collection, table and column, secret | 3 | 5 | 8 | Yes |
| Property panel | Validation display: node badges, field errors, problems list | 3 | 4 | 7 | Yes |
| | **Total** | **30.5** | **47.5** | **79.5** | |
| | of which specific to not using the SDK's shell | 17.5 | 27.5 | 45.5 | |
| | of which content needed with either engine | 13 | 20 | 34 | |

At five days a week that is roughly 6, 10 and 16 working weeks. The worst cases rarely
coincide, so read the top of the range as a bound, not a forecast.

Not in the table, although #1787 needs them under either engine: nested foreach scope
editing, error ports and retry settings, autosave and the conflict banner, undo/redo
and copy/paste, translations, accessibility of forms and pickers, unit and end-to-end
tests, documentation, and the pages around the editor (list, publish, test runs,
trigger and channel settings). Together they add about 24, 38 and 59 days.

### What the estimate rests on

- **What the SDK provided in the lab.** A top bar, a canvas with controls and
  background, a node library and templates, and a properties panel driven by JSON
  Forms. It has no minimap, and no undo/redo, copy/paste, nested scopes or list-of-rows
  control. The lab already replaced its pickers and the rows control with our own.
- **What React Flow 12.11.6 provides.** Controls, MiniMap, Background, NodeToolbar,
  EdgeToolbar, NodeResizer, handles, `isValidConnection`, selection and key-code props.
  Node and edge components, the palette, the panel, the forms and the validation
  display are ours. The component props read show no keyboard-only way to create an
  edge; that was not run to confirm.
- **What the repository provides.** 54 files in `components/ui`, plus `cmdk` and
  `sonner`. `schema-form.tsx` (523 lines) builds a form from a Pydantic schema, but
  its one array kind is a list of strings, so arrays of rows, nested objects, `$ref`,
  unions, dynamic choices and bindings are new. Pickers exist for agents
  (`agent-picker.tsx`, 218 lines), collections (190) and secrets (243), and the lab has
  an agent and version picker. There is no table or column picker, because the tables
  list endpoint is not in the API yet. There is no react-hook-form, zod, d3 or dagre.
  `agent-map` is a hand-built pan and zoom view, not built on `@xyflow/react`, so the
  repository has no canvas precedent to reuse.
- **Obligations that add work.** Every string goes through next-intl, permission-gated
  controls are not rendered, the listed directories carry a 100% line-coverage gate,
  and a new page owes an onboarding stop.

### Against the SDK route

Building on React Flow avoids some cost the SDK route would carry: a production adapter
over the SDK document and JSON Forms (the lab's is about 1,000 lines), stylesheet
containment, accessibility patches, and German chrome next to the console's
language switch. Rough offsets are 6 to 14 days for the adapter, 1 to 12 for
containment, 1.5 to 4 for the patches and 1 to 3 for German, about 10, 17 and 30 days
in all. **These offsets are judgement and were not measured.**

Paired best with best, likely with likely and worst with worst, choosing React Flow
adds about 7, 10 and 16 days, roughly 12% of the total. Mixed at the extremes the range
runs from about -13 to +36 days, so the sign is not settled. Containment is the swing:
it costs about a day if the layer-order pre-declaration works and up to about 12 for a
fork. That is why the untried layer-order test still matters more to the choice than
this estimate does.

### What would move the numbers

- **The catalog contract from #1786.** Whether it carries ports, output schemas, which
  fields hold bindings, interface hints and structured validation paths could move the
  total by about 8 days. If the frontend has to work out which bindings are available
  across branches, merges and error scopes, the binding row goes to its worst case.
- **The tables API.** Without it the table pickers stay mocked, and a mock does not
  meet the acceptance criteria.
- **The keyboard alternative for connecting nodes.** The design is open, about 3 days.
- **Whether backend catalog copy comes with translations.** About 2 days.
- **Design and review iteration.** Not included, and probably the largest hidden
  factor. There are no mockups: the demos are illustrative only.
- **Scope.** Scope switching for foreach is assumed, not a visual subflow. Auto-layout,
  import and export, and templates are excluded. The new code is assumed to live in its
  own directory under the coverage gate.

### Planning consequence

The planning window for #56 runs from 2026-09-21 to 2026-10-23, about five weeks. The
three areas alone are about ten weeks at the likely figure, and the owner also holds
#1786, #1789 and #1790. Issue #56 already says to re-estimate after the SDK and
execution design checks, and this is an input to that. It is not a reason to reopen
the SDK question.

## Measurements

Bundle, from `next build` of this branch against `main`:

| | `main` | With the SDK |
|---|---|---|
| `.next/static` | 4.8 MB, 102 chunks | 13.4 MB, 1,638 chunks |
| JS loaded by `/agents` | 1,626 KB | 1,630 KB |
| Lab route, SDK JS | | 1.7 MB raw, 489 KB gzip (2 chunks) |
| Lab route, SDK CSS | | 385 KB raw, 178 KB gzip |
| Frontend image, npm distributions | 281 | 413 (+132) |

The SDK stays in its own dynamic import, so no other route pays for it. The 1,500
extra chunks are its icon set, loaded on demand. Of the 132 extra distributions, 9 are
needed by the recommended `@xyflow/react` path anyway (`@xyflow/react`,
`@xyflow/system`, `classcat`, `d3-dispatch`, `d3-drag`, `d3-selection`,
`d3-transition`, `d3-zoom` and a second `zustand` copy that `@xyflow/react` brings), so
**123 are SDK-only** (`THIRD_PARTY_NOTICES.md` lists them). The 132 include
Material UI, Emotion and Mantine, beside our Radix, and a beta UI kit
(`@synergycodes/overflow-ui@1.0.0-beta.27`).

Graph performance, production build served with `next start`, headless Chromium on
arm64 macOS, one run each. The graph is a chain of agent and table nodes, each with a
binding. "Settled" is click to all nodes present plus two frames. Blocking is the sum
of long-task time over 50 ms. The bare-flow rows include first load of their chunk,
so read them at 1,000 nodes.

| Nodes | Engine | Settled | Blocking | JS heap | Pan frame p95 |
|---:|---|---:|---:|---:|---:|
| 50 | SDK | 62 ms | 0 ms | 26 MB | 9 ms |
| 200 | SDK | 136 ms | 24 ms | 37 MB | 9 ms |
| 1,000 | SDK | 485 ms | 340 ms | 86 MB | 16 ms |
| 1,000 | Bare React Flow | 298 ms | 62 ms | 60 MB | 9 ms |

At 1,000 nodes the SDK costs about 190 ms more to settle, 280 ms more blocking, 26 MB
more heap and a slower pan than React Flow alone. The dev server showed the same
shape at roughly twice the numbers. Neither engine was tuned.

## Licensing obligations

- `@workflowbuilder/sdk` is Apache-2.0. The package ships its `LICENSE`, which the
  image's collector copies. `@synergycodes/overflow-ui` is MIT.
- `@fontsource/poppins` (OFL-1.1) is pulled in by the SDK. It is recorded in
  `licenses/policy.toml` as accepted: keep the notices with every copy, do not sell
  the font alone. This change adds the row to `docs/licenses.md`.
- `use-composed-ref` (MIT) has no licence file and names no author. Recorded as a
  notice attributed to Mateusz Burzynski (Andarist). That name is inferred from the
  npm maintainer's email address and the repository's ownership; the package itself
  names nobody.
- `@xyflow/react` 12.11.6, the engine this record recommends, is a new direct
  dependency on this branch and is MIT (read from the installed package). It brings
  `@xyflow/system` (MIT) and the `d3-*` packages (ISC) into the notices.
- The vendor sells an Enterprise Edition. Nothing in the npm package requires it.

If the editor is built on `@xyflow/react`, the `@xyflow/*` and `d3-*` entries stay.
Only the SDK-only distributions go away with the SDK, along with the Poppins and
`use-composed-ref` entries; regenerate `THIRD_PARTY_NOTICES.md` (`make licenses`).

## Not evaluated, and caveats

- **The cost figures.** The estimate above is judgement, and its SDK-side offsets (adapter,
  containment, accessibility patches, German chrome) were not measured.
- **Version drift.** The issue names commit `b926e94`. Its history has diverged from
  the `v2.3.0` tag (`gh api` compare: 20 commits ahead, 6 behind), and `b926e94`
  already carries the 2.3.0 release commit and `version: 2.3.0`. Four of the commits
  in `v2.3.0..b926e94` touch `packages/sdk` (a Temporal plugin, a required start node,
  and the `@workflowbuilder/ui` migration). Behaviour here was measured on the
  published 2.3.0 build, and the source was read at the `v2.3.0` tag. The migration
  may change the stylesheet and the dependency tree.
- Two editors mounted at once inline. Upstream says one; the lab only detects it.
- The console's real organization switcher. Workflow and organization switching was
  exercised only through the lab's own selector.
- A layer-order pre-declaration ahead of Tailwind's layers as stylesheet containment.
  It is untried, and would not address `<html data-theme>` or `wb-theme`.
- The iframe, beyond the policy refusal.
- Whether the SDK's chrome follows the console's language switch. It ships English
  and Polish, and the console now serves English, Polish and German, so German
  would need its own SDK translations.
- Select-all (Ctrl+A) in the SDK.
- Single runs on one machine; the numbers show shape, not a benchmark.
- No backend was started. The agent picker was checked against stubbed responses on
  the real endpoint paths.
- The SDK logs a React `ownerState` prop warning in development, which Next shows as
  an issue badge.

## What carries over

- The algorithms in `typed-graph.ts`, `clipboard.ts` and `history.ts`, ported rather
  than copied: see [Adapter work](#adapter-work) for what each hard-codes.
- Clipboard scope. The lab's window-level Ctrl+C, X and V handler blocks native copy
  everywhere outside inputs, so a port must scope it to the diagram. The lab's
  clipboard is a module variable that survives remounts, so a port must key it per
  organization and workflow, or it would carry one organization's agent and version
  ids into another's workflow.
- The save contract: send `expected_revision`, refuse a save whose editor is gone or
  whose payload names another workflow, and treat a 409 as a conflict the user
  resolves.
- Nested foreach as a scope switch with a breadcrumb.
- Strict parsing from the editor's document into the typed graph, and re-attaching
  what the editor cannot hold.
- The Radix controls in `renderers.tsx`, which are ours.

## Reproduce

```bash
cd frontend && bun run dev          # the lab is at /dev/workflow-sdk, behind sign-in
bunx vitest run src/components/dev  # the adapters
```

The route needs an authenticated session. The browser runs used a Playwright context
answering `/api/auth/me`, `/api/agents` and `/api/agents/{id}/versions` with stubs.
The performance figures need a production build with the `notFound()` guard in
`dev/workflow-sdk/page.tsx` removed locally; do not commit that.
