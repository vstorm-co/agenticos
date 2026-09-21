# Workflow Builder SDK evaluation

Decision record for #1781, part of #56. Timeboxed prototype of `@workflowbuilder/sdk`
2.3.0 in the AgenticOS frontend.

## Decision

**Do not adopt the SDK. Build the workflow editor on `@xyflow/react` directly.**

On this record's own numbers the threshold is met: 2 patches against a bound of 5
(see [Patches](#patches)), and the prototype's adapters fit the 2-day bound. The
rejection is a judgement that rests on three findings the count does not capture:

- Its stylesheet was not contained in the prototype. It restyles the whole document,
  survives client-side navigation and could not be fixed with tokens. Containing it
  needs a forked stylesheet build, or an iframe, which would require relaxing the
  console's framing headers. Both were evaluated as far as the notes below say; neither
  is shown to be impossible.
- Every integration point that touches process-wide state needed a guard of ours
  (autosave timers, save status, registries). One of them, left unguarded, wrote one
  workflow's nodes into another workflow's document.
- Half of what the editor needs is not in the package (undo/redo, copy/paste, nested
  scopes, a list-of-rows control), so that code is ours under either engine. The
  parts the SDK does provide are the canvas chrome and simple property fields, and
  the property forms that mattered were custom controls anyway.

One optional trigger for a later look: the reviewed upstream commit is already ahead
of 2.3.0 and swaps its UI dependency (`@synergycodes/overflow-ui` for
`@workflowbuilder/ui`), which may change both the package weight and the stylesheet.
The issue says not to extend the experiment automatically, so nothing here schedules
that. See [Not evaluated](#not-evaluated-and-caveats).

## Threshold, set before the lab was built

Issue #1781 says only that the adaptations must be "bounded". The figures below, **at
most 5 patches to the SDK and about 2 days of adapter work**, were set at the start of
this evaluation, before any code was written, and were not changed afterwards. They
are not in the issue text. Nothing better grounded turned up, so they stand.

- A **patch** is a change to the SDK's own source or built output that has to be
  carried across upgrades.
- **Adapter work** is our code around its public API.

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
  new document, and the new nodes render.
- **A pending autosave outlives its editor.** The SDK's autosave timer is not
  cancelled on unmount, and the save reads the global store when it fires. Reproduced
  by editing a node, then switching workflow inside the 400 ms debounce. With a
  callback that has no guard, **`acme/wf-a` was overwritten with `wf-b`'s nodes**
  (`persisted acme/wf-a r2: b-start b-end`). The guarded callback refused it
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
| `body{overflow:hidden}` | `body` rule | No: a second global override was added |
| `.font-mono` renders in the body font | unlayered `*` beats our layered utility | No, and not patched |
| `<html data-theme>` set, `wb-theme` written to localStorage | SDK theme code | No |

These persist after navigating from the lab to `/agents`, in the dev server and in a
production build. Containing them would need the stylesheet rebuilt with a prefix
and the SDK's portals (modals, snackbar, select popups, which render into `body`)
pointed at our scope, or an iframe. Neither was attempted: the first is a fork, and
the second would need the console's framing headers relaxed for one route, which was
not done. So this is not shown to be impossible, only not achieved in the prototype.
Recorded as **not tamed: failed**, under the half-day rule set at the start of this
evaluation (it is not in the issue text).

## Patches

Needed to meet the bar, none applied:

1. Contain the stylesheet (build-time scope or prefix, and portal targets).
2. Give the icon-only buttons accessible names.

Avoided by the adapter, upstream fixes wanted: the `didSave` truthiness, the autosave
timer that survives unmount, the append-only renderer registry, the "Saved data has
been restored" snackbar on every mount, and commit-on-blur text controls.

Count: **2 of the 5 allowed.**

## Adapter work

Measured with `wc -l`: 1,548 lines of adapter source, 1,046 lines of lab UI, mocks
and fixtures (`baseline-flow`, `editor-host`, `fixtures`, `mock-workflow-api`, `perf`,
`sdk-theme.css`, `workflow-sdk-lab` and the route's `page.tsx`), and 752 lines across
the 7 test files.

The algorithms carry over to React Flow directly, not the files verbatim:

- `typed-graph.ts` is a stand-in for the generated API types.
- `clipboard.ts` hard-codes the stand-in's binding fields, and its default branches
  would silently treat a new node kind as having no bindings.
- `save-handler.ts` imports its error classes from the mock server and `fromSdkScope`
  from `sdk-adapter.ts`.

These modules move once the real editor exists, and were not refactored for that.
The algorithms in question total about 480 lines: `typed-graph.ts` 127,
`clipboard.ts` 143, `history.ts` 110 and the guarded save in `save-handler.ts` 98,
which excludes the lab-only `createNaiveSave`.

| Module | Lines | Survives without the SDK |
|---|---|---|
| `typed-graph.ts`, `clipboard.ts`, `history.ts` | 380 | The algorithms, not the files |
| `save-handler.ts` | 111 | The guards and 409 mapping, yes |
| `sdk-adapter.ts` | 244 | Partly: the strict parse, not the SDK node shape |
| `editor-controller.tsx` | 244 | Partly: history and clipboard wiring |
| `pydantic-schema.ts` | 192 | Only if property forms stay schema-driven |
| `renderers.tsx`, `nodes.ts` | 377 | Controls yes, palette definitions no |

This is a measure of size, not of days. The prototype reached every case in the
issue, so the adapters fit the 2-day bound at prototype quality. Work the SDK would
still need is unbounded or unestimated: stylesheet containment, accessibility
patches, whether its English and Polish chrome follows the console's language switch,
and real API and permission wiring. That is a judgement about risk, not a measured
overrun of the bound.

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
extra chunks are its icon set, loaded on demand. The 132 extra packages include
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
- The vendor sells an Enterprise Edition. Nothing in the npm package requires it.

Removing the dependencies removes those entries and regenerates
`THIRD_PARTY_NOTICES.md` (`make licenses`).

## Not evaluated, and caveats

- **Version drift.** The issue names commit `b926e94`, which is ahead of the `v2.3.0`
  tag by four commits touching `packages/sdk` (a Temporal plugin, a required start
  node, and the `@workflowbuilder/ui` migration). Behaviour here was measured on the
  published 2.3.0 build, and the source was read at the `v2.3.0` tag. The migration
  may change the stylesheet and the dependency tree.
- Two editors mounted at once inline. Upstream says one; the lab only detects it.
- The iframe, beyond the policy refusal.
- Whether the SDK's chrome follows the console's language switch. It ships English
  and Polish, which matches the console's two locales today; a third locale would
  need its own SDK translations.
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
