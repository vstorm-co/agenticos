# AgenticOS UI/UX audit — 11 November 2026

Implemented in `codex/ui-ux-polish`, in the isolated `agenticos-ui-ux` worktree,
from `origin/main` at `9b2711c87`. The existing console design and dependencies
are retained. This is an engineering audit of the console, not a new visual identity.

## Map and evidence

- [Route and component inventory](inventory.md): all 99 page-route templates,
  1192 component modules and 57 component families.
- [Import graph](inventory.json): 2170 local TypeScript modules. Numeric references
  index `modules[]`; page/layout entry points and component families identify where
  to start following imports. Type imports and barrel re-exports make reachability
  broader than rendering. Dynamic imports are not resolved.
- Browser inspection requested 54 static URLs and 15 concrete detail URLs. The latter
  include two agent builders, project/dataset/table/workflow detail, organization
  settings, role matrix, groups, directory, retention, platform organization detail
  and workflow run/log/form-preview pages. Slow first compilations were rechecked;
  loading captures were not accepted as evidence of a settled screen.
- Eight creation dialogs were inspected on desktop and at 320 × 640. Escape closes
  them; long forms scroll inside their dialog. The Routines entry opens a menu and
  was not counted as an inspected dialog.
- Creating a dataset, project, workflow and table through the UI returned 201 for
  each, and their detail pages were inspected against those real rows.
- A final matrix covers 24 core destinations on a 320 × 640 touch viewport in light
  mode and 1440 × 1000 in dark mode: 48 settled observations, without page overflow.
  Automated axe checks are evidence about these states, not a complete accessibility
  conformance assessment. Theme contrast checks additionally cover the MCP catalog
  in all five looks and both color schemes, with reduced motion to avoid measuring
  intermediate fade-in colors.

## Confirmed problems and fixes

| Problem | Result | Main implementation |
| --- | --- | --- |
| Most console tabs reused the deployment's generic title | Titles use the current visible page/section and deployment name; they follow loading, navigation and renames, including late Next.js metadata | `frontend/src/hooks/use-console-title.ts` |
| Personal and organization connected-account requests returned frontend 404s | GET and DELETE reach the existing backend through the shared authenticated, organization-aware proxy; OAuth start keeps its dedicated handler | `frontend/src/app/api/{me/,}connected-accounts/[[...path]]/route.ts` |
| Empty toolbars were only visually hidden | Native `hidden` removes their controls from keyboard navigation and the accessibility tree | `frontend/src/components/ui/list-card.tsx` |
| The empty dataset catalog repeated its zero count | It uses the shared empty-toolbar behavior | `frontend/src/app/[locale]/(dashboard)/datasets/page.tsx` |
| A lone Briefing kept the setup card's 496 px height | Without a rendered checklist it is 224 px; the paired layout still matches the checklist | `frontend/src/components/dashboard/me-opening.tsx` |
| Box-shadow focus disappeared in Windows High Contrast | A system-color outline remains visible, verified with keyboard focus in forced colors | `frontend/src/app/globals.css` |
| Horizontally scrolled strips did not hint at earlier content | Both edges indicate overflow; selected tabs remain outside the fade, and newly added/resized children update the hints | `frontend/src/components/ui/scroll-fade.ts`, `tabs.tsx` |
| Builder loading content measured 556 px inside a 390 px viewport | Loading actions wrap and the skeleton tab strip clips locally; measured content width is now 390 px | `frontend/src/app/[locale]/(dashboard)/agents/[id]/page.tsx` |
| Setup markers added non-tab buttons inside the organization tablist | Tab markers are decorative; their explanations remain attached to their tabs via `aria-describedby`. Standalone indicators retain their keyboard/touch popovers | `frontend/src/components/settings/setup-indicator.tsx` |
| The permission matrix could not be scrolled with keyboard focus | A named focusable scroll region supports native arrow-key scrolling; column and row headers expose scope | `frontend/src/app/[locale]/(dashboard)/orgs/[id]/roles/page.tsx` |
| A small sidebar shortcut missed the text contrast threshold | Its foreground token gives the shortcut more contrast on its tinted background | `frontend/src/components/layout/sidebar-search.tsx` |

The console title synchronization is limited to the mounted authenticated viewport.
It derives names from existing translated UI rather than maintaining another route
label catalog. It observes heading/navigation changes and title-only metadata changes;
ordinary streamed content does not rewrite the title. The observer disconnects when
the viewport or destination changes, and an equality guard prevents a write loop.

## Before and after

| State | Before | After |
| --- | --- | --- |
| Standalone dashboard Briefing | [PNG](comparisons/dashboard-before.png) | [PNG](comparisons/dashboard-after.png) |
| Builder loading on a phone | [PNG](comparisons/builder-before.png) | [PNG](comparisons/builder-after.png) |
| Keyboard focus in forced colors | [PNG](comparisons/focus-before.png) | [PNG](comparisons/focus-after.png) |
| Empty dataset catalog | [PNG](comparisons/datasets-before.png) | [PNG](comparisons/datasets-after.png) |

The full local gallery is served at `http://127.0.0.1:3101`. Its screenshots and
intermediate diagnostics are local, ignored artifacts; the curated pairs above are
kept with this report. Intermediate frames in the gallery include loading states
and must not be interpreted as settled-screen verification.

## Verification

- 119 scoped Vitest tests in 13 files passed, plus the three SidebarSearch tests.
- The new console title hook has 100% statement, branch, function and line coverage
  in a focused coverage run.
- Three Chromium regression tests passed: forced-colors keyboard focus, phone-sized
  Builder loading, and browser titles across navigation/reload.
- The data-dependent browser test was also run with `BACKEND_URL` pointing at a dead
  port. It failed rather than passing against an empty/authentication-error screen;
  the real backend was then restored and all three tests passed again.
- Organization tab semantics and permission-matrix keyboard scrolling were rechecked
  in the browser: axe reported no violations, and ArrowRight moved the focused matrix
  horizontally by 40 px.
- Documentation drift was checked using the repository's pinned Python 3.15; no
  described documentation page was owed. The system Python is too old for that script.
- `make lint-frontend` passed: ESLint, formatting, TypeScript, i18n and dependency
  checks. The final MCP catalog contrast check passed in all ten look/scheme
  combinations, with an authenticated catalog visible in each. Full application
  suites/build/coverage remain CI work.

## Runtime and limits

The running frontend is `http://127.0.0.1:3100`, with its own backend on 8100, pgvector
PostgreSQL on 55492 and cache on 56392. Test data belongs to this isolated database;
the original checkout and the existing services on 3000/3001/8000 were not changed.
The test owner is the repository's bootstrap account. No real model/provider key was
configured or charged. The local backend's event-loop watchdog is disabled for this
inspection process, not in product configuration.

Not exercised end to end: real provider responses, approval/evaluation outcome
combinations, authenticated external integrations, OAuth consent providers, knowledge
parsing with an embedding provider, public forms/invitations and other token-bound viewers,
and native desktop/mobile shells. Those views remain in the source inventory; this
report does not claim that every possible state of every component was tested.

Optional avatar 404s and default-layout 404s were distinguished from failures of
primary page data. Public GitHub release checks returned 503 after repeated local
navigation; those optional network checks were not treated as broken resource lists.
An automated contrast finding during MCP card fade-in was rechecked with motion
settled rather than changing otherwise readable colors.


## Follow-up: complete user journeys

The second pass follows persisted resources across screens and reloads instead of
counting visited destinations. The same worktree and PR contain these fixes:

| Confirmed defect | Result |
| --- | --- |
| Switching project tabs silently discarded edited instructions, name, description or default agent | The existing unsaved-changes guard offers Stay, Discard and Save; a refused save leaves the form and tab intact |
| Escape, Cancel and the close button dropped Context edits | Closing asks first; failed saves preserve the edited content |
| Skill body/metadata edits and resource-file switches had no leave protection | Workbench close and resource switches use the same guard. Resources save before the body so a resource refusal cannot close the workbench |
| Save file cleared its draft before the write answered | The draft clears only after success. Failed saves/removals keep the open file; typing added during an in-flight resource save remains unsaved |
| The workflow test-run bar was 378 px wide at a 320 px viewport, placing its start at x = −29 px | Live and stale run bars wrap within the canvas. The live bar measures 262 px, starts at x = 29 px, and keeps Open run and Hide the run reachable |

| Journey | Persisted result verified |
| --- | --- |
| Vault → Builder → model → capability → publish → chat → hosted page → Activity → dataset | Instructions reach the local model stub; both authenticated chat and an unauthenticated hosted visitor receive its token. Activity records the model and cost; the curated dataset case contains the answer |
| Create project → choose default agent → New chat → answer → reload → project Chats → reopen | The selected agent answers, the conversation remains in its project and the stored answer is shown again |
| Create project → Instructions → Stay → refused save → successful save → Files/upload → reload → discard | Saved settings and uploaded file survive reload at 1440 and 390 px; failed writes and tab switches preserve pending edits |
| Create Context → edit → Escape/Stay → Cancel/Discard → refused save → save → reopen | The original survives discard, the pending edit survives refusal, and the accepted text survives reload |
| Create Skill with a file → edit body and resource → refused save/close → switch with save → reopen | Both records survive reload. Saving a resource first prevents a body save from closing the editor after the resource was refused |
| Create workflow → add Output → configure → publish → reload → Test draft → Open run → Output → reload | The real worker completes both steps; the run stores the configured text and the output is readable on the run page. Its controls fit a 320 px touch viewport |

The workflow uses test mode and no external integration actions. Model responses
come from the repository's OpenAI-compatible local stub, not a paid provider. The
backend's local FRONTEND_URL was corrected to port 3100 and its isolated worker
was started; these are ignored local environment settings, not product changes.

| Follow-up evidence | Before | After |
| --- | --- | --- |
| Project instructions lost across tabs | [PNG](comparisons/project-unsaved-before.png) | [PNG](comparisons/project-unsaved-after.png) |
| Context edit lost on Escape | [PNG](comparisons/context-unsaved-before.png) | [PNG](comparisons/context-unsaved-after.png) |
| Skill resource after a refused write | [PNG](comparisons/skill-save-before.png) | [PNG](comparisons/skill-save-after.png) |
| Workflow run controls at 320 px | [PNG](comparisons/workflow-run-before.png) | [PNG](comparisons/workflow-run-after.png) |

Verification for this pass:

- 134 scoped Vitest tests across Projects, Context, Skills and workflow run controls.
- Nine targeted Chromium tests, including all six journeys above and the three
  first-pass accessibility regressions. No full application suite was run locally.
- Regression controls: the project journey fails on the original implementation
  at the missing leave confirmation; the resource test fails on the original
  implementation because the pending text is cleared before the write answers.
- Frontend lint, formatting, TypeScript, i18n and dependency checks; strict MkDocs
  build in all four locales. Console/workflow documentation and translations
  describe the changed editing and mobile run behavior.

The route/component inventory remains the full source map, not a claim that all
states, roles and external integrations have been exercised. Full CI is still
separate evidence tied to its own commit SHA.


## Follow-up: tables, knowledge bases and organization settings

Three further full-stack flows use the same isolated worktree and database:

- CSV table creation/import, duplicate mapping rejection, corrected import on a
  390 px viewport, Table/List views, reload and archival. Duplicate Name/name or
  external-id mappings previously overwrote the first value in a successful
  import. Both collisions are now marked, described and blocked until corrected.
- Register a local embedding endpoint, create an Ollama-backed KB, upload text,
  parse/chunk/embed/index through the actual worker, reload, search the selected
  KB, recover from a refused search, and open the original text on a phone.
  A controlled delayed real search reproduced old results under a newly typed
  question. Editing the question or scope now cancels and invalidates the request;
  late responses cannot overwrite a newer result. The client forwards AbortSignal.
- Create an isolated organization, select it, rename it, exercise Stay and a
  refused Save, save and re-enter; edit its spending cap and voice recording limit,
  save both before leaving and verify them after returning. Organization tabs keep
  their forms mounted, so tab changes do not get unnecessary confirmations.
  Identity, budget and voice drafts now use the existing navigation guard.

The embedding fixture creates deterministic lexical vectors through the same
OpenAI-compatible protocol as the registered local provider. It verifies ingestion,
storage, retrieval plumbing and source identity, not semantic embedding quality.
No paid key, external OAuth consent or real teammate invitation is used.

| Evidence | Before | After |
| --- | --- | --- |
| Duplicate CSV target | [PNG](comparisons/table-csv-before.png) | [PNG](comparisons/table-csv-after.png) |
| Organization draft lost on navigation | [PNG](comparisons/org-edit-before.png) | [PNG](comparisons/org-edit-after.png) |
| KB result from an outdated question | [PNG](comparisons/kb-search-before.png) | [PNG](comparisons/kb-search-after.png) |

Scoped checks cover the importer, record detail/conflict behavior, RAG client and
search, organization members/permission controls, spending cap and voice settings.
The three new Chromium journeys assert actual persisted data across reloads; the
KB journey uses the repository model fixture's new embedding route. Console and
Virtual Tables documentation explain the behavior in all four languages.

This pass passed 139 targeted Vitest tests in seven files and three new Chromium
journeys. The table journey additionally edits a stored record and adds one manually
before reloading and archiving. ESLint, formatting, TypeScript, i18n and dependency
checks are applied, with strict four-language documentation and translation checks.
The import graph has been regenerated after the new hook dependencies.


The agent regression also reproduced a hosted-chat startup race: Send was enabled
while the socket was still CONNECTING, and the first click was silently ignored.
Readiness now belongs to the public key and conversation session; sending stays
disabled until that socket opens, while the draft remains editable. A controlled
five-second handshake verified disabled → enabled with the draft preserved, and the
complete agent/hosted/project journey passed again after the fix. All 97 hosted-chat
unit tests passed, bringing this pass to 236 targeted tests in eight files and four
Chromium journeys (three new data/settings journeys plus the agent regression).

| Hosted connection evidence | Before | After |
| --- | --- | --- |
| First question during connection setup | [PNG](comparisons/hosted-ready-before.png) | [PNG](comparisons/hosted-ready-after.png) |

The hosted Before image is the actual failed journey. The After image captures the
same public page with a controlled slow transport, before its real socket opens.


## Composer geometry and populated phone panels

The public-chat send button was visibly offset: its center sat 2 px above the
input on desktop and 4 px above it on touch phones. The composer now centers its
children, removes the extra bottom padding from the action wrapper, and gives Send
a square 40 px base size (44 px with the existing touch target rule). The agent
journey checks the input, button and icon centers and the circular button's aspect
ratio on desktop and a separate anonymous touch-phone context.

A further 320 px touch pass opened table columns, populated filters, view settings
and KB parse options. A populated filter squeezed even Name and contains into
ellipses. Phone conditions now stack full-width controls with removal in the
condition header. The popover constrains its scrolling body to the available
height while keeping its header and footer available. Desktop conditions retain
the existing horizontal layout. The table journey checks usable control widths,
filters actual persisted rows and clears the condition to restore them.

| Evidence | Before | After |
| --- | --- | --- |
| Public composer, desktop | [PNG](comparisons/composer-desktop-before.png) | [PNG](comparisons/composer-desktop-after.png) |
| Public composer, touch phone | [PNG](comparisons/composer-phone-before.png) | [PNG](comparisons/composer-phone-after.png) |
| Populated table filter, 320 px touch phone | [PNG](comparisons/table-filter-phone-before.png) | [PNG](comparisons/table-filter-phone-after.png) |

Validation: 97 hosted-chat and 17 filter unit tests passed, as did the complete
agent/hosted/project journey (plus its 15 authentication/seed prerequisites) and
the expanded CSV/table/filter journey. Targeted ESLint, TypeScript and formatting
checks passed. The table test explicitly blurs the buffered cell operand before
closing its popover; Escape alone unmounts that editor without committing it.
No full local suite was run.


## Consistent mobile control rows

The touch pass exposed a 32 px saved-view shell around a 44 px trigger, a squeezed
format icon and truncated All records label. The format picker and saved-view
picker now align, share their available width and preserve the default names at
320 px. Filter, Sort and View settings occupy a deliberate three-column row;
Set as default belongs inside View settings. Auxiliary hidden-column and Kanban
grouping controls follow that row. A saved view's management actions move into
its phone menu, with the existing owner/manage/delete gates unchanged.

Compact ListFilters triggers show their icon and active count on phones, retaining
their accessible name, expanded state and 44 px touch target. ListCard lets its
single control group fill the mobile width instead of leaving an empty gap.
These shared controls cover Agents, Skills, Context, Workflows, Tables and other
catalogs using ListFilters; the desktop filter labels remain visible.

Actual touch screenshots were reviewed at 320 and 390 px for table detail,
Agents, Skills and Context. The browser checks cover five populated/API-verified
catalogs, opening and closing their filters, plus table creation, control geometry,
format switching, persisted default selection and renaming through the phone menu.
Fifty focused unit tests cover the shared list controls, views, presentation
settings and the phone menu's owner/permission gates. Two Chromium journeys pass;
TypeScript, ESLint and four-language documentation checks are also applied.

| Evidence | Before | After |
| --- | --- | --- |
| Table control rows, 320 px touch | [PNG](comparisons/mobile-table-toolbar-before.png) | [PNG](comparisons/mobile-table-toolbar-after.png) |
| Catalog search and filters, 390 px touch | [PNG](comparisons/mobile-catalog-toolbar-before.png) | [PNG](comparisons/mobile-catalog-toolbar-after.png) |


## Mobile knowledge and organization journeys — 2026-11-12

The organization profile's avatar action overflowed at 320 px while the name
input shrank around Save. The identity form now responds to its container, and
its phone fields/actions stack. The spending cap's wrapped Save no longer keeps
the desktop label-offset margin, and its label uses the shared translation.

Knowledge-base document actions and member-management actions sat beyond the
phone's right edge. Both use the shared table's opt-in narrow-container layout:
labeled cells, full-width identity, and status/role beside visible actions.
Explicit table/row/cell roles preserve semantics when CSS changes their display;
desktop presentation remains tabular. A refused document download is now reported
rather than silently ignored. Member removal asks before sending DELETE; a refused
removal keeps both the member and the confirmation visible.

A controlled delayed settings request on the actual page reproduced a KB dialog disappearing on Escape
before the request settled. Create KB, parsing and embedding-provider dialogs now
block dismissal during their write and disable Cancel/Close. The shared confirmation
also keeps pending operations visible. Refusal restores dismissal and preserves
the form values. Existing Radix dialog primitives and focus behavior are retained.

Retention had no navigation guard or reported write failure, and its button bypassed
HTML number constraints. It now submits as a form, checks native validity for both
ordinary and guarded saves, reports a refusal and preserves the draft. Explicitly
cleared periods still mean null; untouched empty periods remain absent.

The new touch Chromium journeys cover:

- Create a KB against the local embedding fixture; refuse a delayed parsing save
  after trying Escape; retry and re-read the stored configuration; upload, index
  and reload a document; preview it; refuse/retry download and compare the actual
  downloaded bytes; search, refuse/retry and open the original source.
- Create and select an isolated organization through the phone UI; edit its name,
  exercise Stay and a refused Save, then persist it; save spending and voice limits
  before leaving and re-read them; exercise retention Stay/refusal/save/re-entry;
  inspect an invitation draft and cancel it; return to Personal and delete the fixture.
- At 320/390 px, verify member action bounds and touch targets, open/cancel forgetting
  memory, cancel removal before DELETE, and keep a refused removal open. The seeded
  colleague is not actually removed.

The KB journey runs at 320×740 and opens the source again at 390×844. No paid model,
real invitation email, external directory or production account is exercised.
149 focused unit/integration tests in ten files and three browser journeys passed.
Scoped ESLint, TypeScript, translations and the strict four-language documentation
build pass. The production import map has been refreshed.

| Evidence | Before | After |
| --- | --- | --- |
| Organization identity form, touch phone | [PNG](comparisons/org-profile-mobile-before.png) | [PNG](comparisons/org-profile-mobile-after.png) |
| Spending cap after editing | [PNG](comparisons/org-budget-mobile-before.png) | [PNG](comparisons/org-budget-mobile-after.png) |
| Organization members and actions | [PNG](comparisons/org-members-mobile-before.png) | [PNG](comparisons/org-members-mobile-after.png) |
| KB document actions | [PNG](comparisons/kb-documents-mobile-before.png) | [PNG](comparisons/kb-documents-mobile-after.png) |
| KB settings dismissed while saving | [PNG](comparisons/kb-save-pending-mobile-before.png) | [PNG](comparisons/kb-save-pending-mobile-after.png) |
