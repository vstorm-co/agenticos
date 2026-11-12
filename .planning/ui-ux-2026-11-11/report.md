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
151 focused unit/integration tests in ten files and three browser journeys passed.
Scoped ESLint, TypeScript, translations and the strict four-language documentation
build pass. The production import map has been refreshed.

| Evidence | Before | After |
| --- | --- | --- |
| Organization identity form, touch phone | [PNG](comparisons/org-profile-mobile-before.png) | [PNG](comparisons/org-profile-mobile-after.png) |
| Spending cap after editing | [PNG](comparisons/org-budget-mobile-before.png) | [PNG](comparisons/org-budget-mobile-after.png) |
| Organization members and actions | [PNG](comparisons/org-members-mobile-before.png) | [PNG](comparisons/org-members-mobile-after.png) |
| KB document actions | [PNG](comparisons/kb-documents-mobile-before.png) | [PNG](comparisons/kb-documents-mobile-after.png) |
| KB settings dismissed while saving | [PNG](comparisons/kb-save-pending-mobile-before.png) | [PNG](comparisons/kb-save-pending-mobile-after.png) |


The final pending-write check also found editable fields inside Create KB and the
embedding-provider dialog. Both bodies now use disabled, named fieldsets until
the request settles, preventing a later reset from erasing text typed during the
write. Two additional regression tests cover refusal and restoration of editing.
The interrupted dev environment was restored from its own persisted database and
cache containers; a corrupt Next dev manifest was moved aside and regenerated.

Two additional organization-role browser checks pass after updating stale E2E
selectors for the permission row headers, aligning the denied-scope marker with
the rendered `-`, and asserting both member and viewer scopes. Historical CI
run 43111576233 also found stale generated Architect guide copies; regeneration
and `gen_architect_guide.py --check` now pass. That older run's frontend coverage
and unrelated workflow-run failures do not constitute verification of the new
head; full CI remains pending.

## Human-entered technical names — 2026-11-12

Reproduced the reported skill-creation failure on a touch phone: `Strategic
Diagnostic` produced a server validation error. The console now formats a name
on blur and again at submission, preserving the text and caret while typing.
Capitals become lowercase, separators become single hyphens, and Latin accents
(including Polish ł) are simplified. No fallback name or silent truncation is
introduced. The server's canonical validation and capability-name checks remain.

The same behavior covers editable authoring skill proposals, environment creation
and rename, MCP prefixes in both connection entry points, and custom slash
commands. Identifier keyboards disable autocorrection, capitalization and spell
checking. Skill and MCP helper text is connected to its field. Authoring names
no longer start red or become red during ordinary typing. Existing unchanged
MCP prefixes and command names retain their stored identity on unrelated saves.

210 scoped tests in eight files pass. Two touch Chromium journeys verify real
skill creation and reload, a normalized-name collision retaining the draft,
correction and retry, and command creation followed by reload. Both remove their
own fixtures. The original UI's refused skill creation was reproduced before
editing and captured at the same phone width. ESLint/TypeScript and documentation
checks run with the change; full CI remains separate evidence.

| Evidence | Before | After |
| --- | --- | --- |
| Skill creation accepts a human title | [PNG](comparisons/skill-name-mobile-before.png) | [PNG](comparisons/skill-name-mobile-after.png) |
| Custom command name | — | [PNG](comparisons/command-name-mobile-after.png) |

## Commands and MCP configuration journeys — 2026-11-12

At 320 px, custom command edit/delete buttons measured 28×28 px; the command name
was squeezed between them and its switch, while New command extended beyond its
section. Commands now adapt to their container: the heading/action wraps, names
can use the row's width, and controls get a separate row with 44×44 touch targets.
Action names identify the command. Built-in and custom toggles remain disabled
until their writes settle, and custom edits/removal cannot race that toggle.

Command editing now uses a native form and a bounded scrolling body with a fixed
footer. A 320×568 viewport retains its Save button inside the visible viewport.
Closing a changed draft uses the console's Save/Discard/Stay guard; a refused save
keeps the editor and values. Pending saves disable the named fieldset, Cancel and
Close, and prevent Escape/backdrop dismissal. Removal uses an application
confirmation: Cancel sends no DELETE, refusal keeps it open, and retry can finish.
Command confirmations, action names and mutation feedback use all four UI locales.
The shared unsaved-changes prompt also visibly disables Close while saving.

MCP connection fields were editable while a connection write was pending. The
shared dialog now freezes its native fieldset and dismissal, including both
connection entry points. Separately, the server list closed the OAuth draft
*before* starting consent; an actual controlled 403 reproduced a vanished form.
The draft now stays open while OAuth start is pending and remains editable after
refusal. It closes only after the start produced a consent destination.

143 scoped tests in five files pass. Three touch Chromium journeys cover command
creation/reload, Stay, refused pending save, guarded retry/save, persisted toggle,
canceled/refused/successful removal; MCP creation/refusal/retry and stored label
edit/re-entry; and refused OAuth start followed by a redirect retry. MCP transport
probes are controlled refusals, and the OAuth destination is a local stand-in:
configuration persists in the actual backend, but no live provider grant is made.
Strict documentation builds in all four published languages pass. Full CI remains
separate evidence. The route/component import map is refreshed.

| Evidence | Before | After |
| --- | --- | --- |
| Custom command actions at 320 px | [PNG](comparisons/command-actions-mobile-before.png) | [PNG](comparisons/command-actions-mobile-after.png) |
| Command fields during save | [PNG](comparisons/command-pending-mobile-before.png) | [PNG](comparisons/command-pending-mobile-after.png) |
| MCP connection fields during save | [PNG](comparisons/mcp-pending-mobile-before.png) | [PNG](comparisons/mcp-pending-mobile-after.png) |
| Refused OAuth start retains its draft | [PNG](comparisons/mcp-oauth-refusal-mobile-before.png) | [PNG](comparisons/mcp-oauth-refusal-mobile-after.png) |
| Command removal confirmation | — | [PNG](comparisons/command-delete-mobile-after.png) |

## Mobile creation and dataset authoring — 2026-11-12

Controlled pending creates reproduced editable fields and Escape dismissal in
New project, New context file and New dataset. All three now use named native
fieldsets and block closing while the write settles; context source editing is
also read-only. Refusal restores editing with the submitted values. Closing a
changed creation form now asks Save/Discard/Stay; explicit discard resets its
state instead of leaving the abandoned values in the next opening. Project field
refusals clear when that field is edited.

Context creation formerly placed the source below the description and three
large audience cards on phones. Optional metadata is now collapsed there, with
Details showing the effective audience even when closed. The source is visible
immediately. A description refusal expands its hidden field; helper/error notes
are linked to the controls. Desktop fields remain expanded.

A drop containing multiple context files is special: closing offers Stay or
Discard, while Create advances the queue. Saving just the first file from a
close prompt would otherwise abandon the remaining files as navigation proceeded.
The browser journey verifies both files and their distinct bodies in order.

Dataset details and case editing also allowed changes and closing during a save.
Both now freeze fields and dismissal. The case form/JSON switch is blocked too,
including while checking for a duplicate question. Dataset details use a scrolling
body and fixed footer; the 320×568 check keeps Save inside the viewport.

100 focused tests in five files pass. Four touch Chromium flows verify:

- Project creation with Stay, delayed refusal and retry, file upload and reload,
  followed by reading the saved instructions.
- Context creation with collapsed metadata, source preservation after a refused
  write, then a saved edit and another opening.
- Dataset creation/refusal/retry, settings refusal and persisted percentage,
  case refusal/retry and persisted question, and a real CSV download whose bytes
  contain the saved question and answer.
- Two dropped context files, Stay without losing the queue, creation in order,
  and both files listed after reload.

Each journey removes its own fixtures. No paid model or evaluation run is needed.
Strict docs build in all four published languages passes; full CI remains
separate evidence. The route/component import map is refreshed.

| Evidence | Before | After |
| --- | --- | --- |
| New project during save | [PNG](comparisons/project-create-mobile-before.png) | [PNG](comparisons/project-create-mobile-after.png) |
| Context creation: source and pending state | [PNG](comparisons/context-create-mobile-before.png) | [PNG](comparisons/context-create-mobile-after.png) |
| New dataset during save | [PNG](comparisons/dataset-create-mobile-before.png) | [PNG](comparisons/dataset-create-mobile-after.png) |
| Dataset details during save | [PNG](comparisons/dataset-edit-mobile-before.png) | [PNG](comparisons/dataset-edit-mobile-after.png) |
| Dataset case during save | [PNG](comparisons/dataset-case-mobile-before.png) | [PNG](comparisons/dataset-case-mobile-after.png) |


## Mobile channels and vault — 2026-11-12

Browser reproduction confirmed that Cancel in channel registration, vault creation
and key rotation bypassed the reset used by Escape. Reopening restored a cancelled
credential; rotation could carry it into another attempt. All close routes now
clear these ephemeral values when no write is pending. Credentials are never
stored in a persistent draft.

Channel registration now uses a compact eight-option selector below the desktop
breakpoint; the desktop keeps its platform cards. Channel and vault fields and
close controls freeze during writes, including ChatGPT sign-in/reconnection.
A refusal restores editing with the same draft. Channel editing and key rotation
use the shared scrolling body and fixed footer rather than independent vh limits.

58 focused tests in six component files pass. Two touch Chromium journeys at
320×740 and 320×568 verify cancellation/re-entry, held 403 responses and retries,
real channel registration and editing, real vault creation and rotation, reloads
and the unchanged secret ID. Read responses expose the hint, not the fake token.
The channel fixture is Slack in webhook mode, so no external stream opens. The
vault uses dummy API keys and makes no provider call. Every journey deletes its
own fixtures. Two leftovers from an initial test-helper failure were also removed.
TypeScript and focused ESLint pass. Full CI remains separate evidence.

| Evidence | Before | After |
| --- | --- | --- |
| Platform selection at 320 px | [PNG](comparisons/channel-platform-mobile-before.png) | [PNG](comparisons/channel-platform-mobile-after.png) |
| Cancelled channel reopened | [PNG](comparisons/channel-cancel-mobile-before.png) | [PNG](comparisons/channel-cancel-mobile-after.png) |
| Cancelled vault creation reopened | [PNG](comparisons/vault-cancel-mobile-before.png) | [PNG](comparisons/vault-cancel-mobile-after.png) |
| Cancelled key rotation reopened at 320×568 | [PNG](comparisons/vault-rotate-mobile-before.png) | [PNG](comparisons/vault-rotate-mobile-after.png) |

Routine creation/editing was inspected in source, but its pending-state findings
still need a browser reproduction and a separate verified correction.


## Production feedback: context, availability and app sharing — 2026-11-12

Context settings no longer stretches a two-column gallery to its longest file
or selected file's controls. Single-column rows clamp descriptions for scanning,
wrap long names, and keep per-agent mode and enabled state together. The toolbar
shows the file count. Redundant introductory copy and duplicate capability IDs
are omitted. Inject-only context is explained with a shorter neutral information
note; a disabled capability with bound files retains its warning.

Availability uses the shared brand mark for each bot's platform, with its name
and platform on separate lines. The row wraps on phones instead of truncating the
identity against the environment and action buttons.

App sharing leads with its page link and people/access controls. Public-link
expiry, pinning, embedding, iframe code and password controls sit in a native
`details` disclosure. Active restrictions remain visible as badges. Closing the
disclosure preserves drafts; a pending write freezes its fields and prevents
collapse. Refusals leave the open draft intact. Pending access/version requests
stay first, including when opened from their badge or a notification; an empty
request section moves below the ordinary sharing controls. Public-data consent
controls and permission gates remain in their existing paths.

408 focused tests in eight files pass, including retaining password drafts,
pending disclosure behavior, existing consent/refusal cases and request ordering.
One touch Chromium journey publishes a demo app through the real agent/tool path
using the local stub model, persists a context-file override and reloads it, then
creates a public link, changes expiry/version/embed sites, holds and refuses a
save before retrying, sets a password, reopens the app and turns the link off.
TypeScript, scoped ESLint and the strict four-language docs build pass. Full CI
remains separate evidence.

The screenshots use four real demo context files and an app published by a local
stub run. Only the Mattermost exposure read is a controlled browser fixture: no
external Mattermost server was connected. Desktop screenshots are 1440×1000;
phone screenshots are 390×844. Initial test fixtures left by an outdated button
label assertion were explicitly removed, as were the review's demo records.

| Evidence | Before | After |
| --- | --- | --- |
| Context settings, desktop | [PNG](comparisons/context-settings-desktop-before.png) | [PNG](comparisons/context-settings-desktop-after.png) |
| Context settings, phone | [PNG](comparisons/context-settings-phone-before.png) | [PNG](comparisons/context-settings-phone-after.png) |
| Availability, desktop | [PNG](comparisons/availability-desktop-before.png) | [PNG](comparisons/availability-desktop-after.png) |
| Availability, phone | [PNG](comparisons/availability-phone-before.png) | [PNG](comparisons/availability-phone-after.png) |
| App sharing, desktop | [PNG](comparisons/app-share-desktop-before.png) | [PNG](comparisons/app-share-desktop-after.png) |
| App sharing, phone | [PNG](comparisons/app-share-phone-before.png) | [PNG](comparisons/app-share-phone-after.png) |


## Routines and monitoring forms — 2026-11-12

A held refusal reproduced editable schedule fields during an update. The edit
form also scrolled its header and Save action away. Schedule/event editing now
uses a fixed header, scrolling body and fixed action footer. Fields, the prompt
editor, Cancel, Close, Escape and Run now freeze during writes; a refusal unlocks
the same draft for retry. The prompt's disabled state reaches its expanded view.

The common routine frame distinguishes disabled preparation from a pending write:
preparing local consent must not lock dismissal. Pending schedule, event, portal
and watch writes disable Close. Watch and portal roots guard closing too. The
wizard footer exposes `backDisabled` for non-cancellable writes; other callers
retain cancellation. Navigation has 44px touch targets and consistent phone
padding. The current step has a separate phone caption instead of a truncated
label. Advanced options use a leading chevron and compact phone spacing.

Long routine names wrap on phones. An unmatched search shows a centered empty
state, guidance and reset action. Read errors offer Retry for both tasks and
watches, preserving the combined list's completeness contract.

75 focused tests in nine files pass. Two touch Chromium journeys at 320×568 verify:

- A paused schedule: search/reset, held 403, blocked fields/dismissal and visible
  Save, retry, persisted name/message after reload and confirmed UI deletion.
- A new API event: catalog entry, source/configure/message steps, Back with
  retained values, held refusal/retry, real creation, webhook instructions,
  return to the list and reload. The stored row has no run; reads do not expose
  the dummy signing secret.

The screenshot fixture is another paused schedule, removed after capture. No
routine runs manually and no webhook delivery is triggered. Portal and watch
pending/refusal behavior is covered by focused integration tests; an external
account was not connected. TypeScript and focused ESLint pass. Full CI remains
separate evidence.

| Evidence | Before | After |
| --- | --- | --- |
| Routine list, 320×740 touch | [PNG](comparisons/routines-list-phone-before.png) | [PNG](comparisons/routines-list-phone-after.png) |
| No search matches, 320×740 touch | [PNG](comparisons/routines-empty-phone-before.png) | [PNG](comparisons/routines-empty-phone-after.png) |
| Editing during save, 320×568 | [PNG](comparisons/routine-edit-phone-before.png) | [PNG](comparisons/routine-edit-phone-after.png) |
| Editing during save, 1440×1000 | [PNG](comparisons/routine-edit-desktop-before.png) | [PNG](comparisons/routine-edit-desktop-after.png) |
| Creating during save, 320×568 | [PNG](comparisons/routine-create-phone-before.png) | [PNG](comparisons/routine-create-phone-after.png) |


## Department browsing and setup — 2026-11-12

The department catalog uses responsive cards with full names, descriptions and
member counts that remain visible on phones. Search matches names and descriptions,
with a clear/reset empty state. Both group catalogs offer retry on read failures.
The detail page distinguishes a failed read from a missing group, places shared
resources before usage panels and gives resource categories readable headings,
counts and wrapping names. Secondary actions fold on phones.

Setup combines a live icon preview with a 44px icon grid and a collapsed optional
budget. A scrolling body keeps the action footer visible even at 320×568. Named
fieldsets lock fields during writes. Membership rows wrap identity separately from
actions; a complete membership shows a short notice. Failed adds retain the chosen
person until success. Sharing keeps names readable and stacks the grant selector
and submit action at full width on phones; all read/use/edit levels remain available. Pending
member and share changes block dismissal and competing controls. Failed group
deletion retains the confirmation for retry instead of closing it.

43 targeted tests across four files pass. Two Chromium journeys pass at desktop
1440×1000 and touch phone 320×740 (editing also at 320×568). Each creates a group,
sets identity and budget, searches it, adds a member and lead, shares a private
context file at read level, edits metadata, reloads persisted data and deletes
the group. Held 403 responses verify locked fields/dismissal and retained choices
through retries for creation, membership, sharing and deletion. The phone journey
measures grant-selector and submit-button widths to catch a narrow, right-aligned
footer. Fixtures are
removed in each journey. TypeScript and focused ESLint pass. Strict MkDocs builds
all four locales; translation, paragraph and generated-guide checks pass. Full
CI and the complete cross-browser suite remain separate evidence.

Seven before/after pairs are actual browser captures at equal viewport sizes.
The baseline temporarily uses the previous committed UI, then restores the exact
working source. Four demo groups, two context files and one published demo agent
are removed after capture. No new model run or external integration is triggered;
the usage panels include the seeded members' historical runs. Existing users,
profiles and unrelated resources are retained.

| Evidence | Before | After |
| --- | --- | --- |
| Department catalog, desktop 1440×1000 | [PNG](comparisons/departments-list-desktop-before.png) | [PNG](comparisons/departments-list-desktop-after.png) |
| Department catalog, phone 390×844 | [PNG](comparisons/departments-list-phone-before.png) | [PNG](comparisons/departments-list-phone-after.png) |
| Department resources, desktop 1440×1000 | [PNG](comparisons/department-detail-desktop-before.png) | [PNG](comparisons/department-detail-desktop-after.png) |
| Department resources, phone 390×844 | [PNG](comparisons/department-detail-phone-before.png) | [PNG](comparisons/department-detail-phone-after.png) |
| Department setup, touch phone 320×740 | [PNG](comparisons/department-create-phone-before.png) | [PNG](comparisons/department-create-phone-after.png) |
| Group members, touch phone 320×740 | [PNG](comparisons/department-members-phone-before.png) | [PNG](comparisons/department-members-phone-after.png) |
| Sharing resources, touch phone 320×740 | [PNG](comparisons/department-resources-phone-before.png) | [PNG](comparisons/department-resources-phone-after.png) |


## API key setup and credential lifecycle — 2026-11-12

The API settings page puts credentials before the connection guide. Active keys
appear first. Desktop rows wrap long names; phone cards retain the full name,
status, scope count, issuer (where authorized), expiry and last use. Search
matches names, prefixes and issuers, with pagination and unmatched-search reset.

Creation submits by keyboard as well as by its action button; Enter in the
permission filter does not issue a credential. It has a scrolling body and fixed
footer, compact preset permission details
and a searchable Custom picker. Touch checkbox labels are at least 44px high.
Filtering does not clear selections or widen scopes. Pending creation blocks
fields, selects, checkboxes and dismissal; refusal retains the exact draft. Close
clears both local reveal state and mutation result. A failed scope-catalog read
offers Retry instead of silently removing creation. Refused revocation remains
open for retry without an unhandled mutation rejection.

The shared picker also serves MCP OAuth consent, whose organization and scope
controls now freeze during approval or denial. A focused component test checks
that state and retained choices; no external MCP client was authorized. Secret
and code copy controls use the existing clipboard hook, report denied copies
and allow retry without discarding the value or claiming success.

31 focused tests in seven files pass. The pending/refusal regression fails on the
previous create dialog with an enabled Name field, then passes after restoration.
Two Chromium journeys at 1440×1000 and touch 320×568 pass: copy the displayed API
base URL, create with searched Custom permissions and expiry, hold a 403 and
retry, copy the actual one-time value to the browser clipboard, and use it for a
real allowed agent read and a denied knowledge read. Cancelled revocation leaves
it active; refused revocation retains the dialog; retry makes subsequent bearer
reads return 401. Re-entry clears the creation form and reload preserves Revoked.
The create action stays within the short viewport and the page does not overflow.

TypeScript, focused ESLint and i18n checks pass. Strict MkDocs builds all four
locales; translations, paragraphs and the generated Architect guide are current.
Full CI, coverage and cross-browser results remain separate evidence. The local
frontend now advertises the API and WebSocket on its actual port, 8100, through
runtime environment variables; no deployment defaults are changed.

Six equal-viewport pairs use three real demo records, including a revoked key.
They show no complete credentials. The previous committed UI is captured with
the same records and runtime, then the working files are restored byte for byte.
Flow credentials are revoked in test cleanup. The demo credentials are revoked
and only this pass's known fixture IDs are deleted from the local database after
capture, since the product intentionally retains revoked history. No paid model
call or external integration is triggered.

| Evidence | Before | After |
| --- | --- | --- |
| API key settings, desktop 1440×1000 | [PNG](comparisons/api-keys-desktop-before.png) | [PNG](comparisons/api-keys-desktop-after.png) |
| API key settings, touch phone 320×740 | [PNG](comparisons/api-keys-phone-before.png) | [PNG](comparisons/api-keys-phone-after.png) |
| Create key, desktop 1440×1000 | [PNG](comparisons/api-key-create-desktop-before.png) | [PNG](comparisons/api-key-create-desktop-after.png) |
| Create key, touch phone 320×740 | [PNG](comparisons/api-key-create-phone-before.png) | [PNG](comparisons/api-key-create-phone-after.png) |
| Custom permissions, desktop 1440×1000 | [PNG](comparisons/api-key-custom-desktop-before.png) | [PNG](comparisons/api-key-custom-desktop-after.png) |
| Custom permissions, touch phone 320×740 | [PNG](comparisons/api-key-custom-phone-before.png) | [PNG](comparisons/api-key-custom-phone-after.png) |


## Profile and notification journeys — 2026-11-12

Profile combines portrait and identity in one card, folds fallback colours and
places Save below the fields. Native forms support Enter; named fieldsets freeze
identity, portrait, colour and agent-context controls during conflicting writes.
Refused saves retain drafts and allow retry. Working days have 44px touch targets,
with equal-width, labelled start/end fields at 320px. Native avatar-colour radios
support arrow keys and retain native appearance in forced colours.

Event preferences have translated search, six-event pagination, compact channel
cards and a branded chat-platform selector. Paging scrolls the new first result
into view. Loading shows skeletons rather than guessed enabled switches; failed
reads offer Retry. Connected/selected destinations lead their section, with unused
platforms folded away. Linked chat accounts show platform logos and wrapping
identities, hosts and agent names; a failed read no longer looks like an empty
account list.

75 focused tests across nine files and two full Chromium journeys pass at
1440×1000 and touch 320×740. Journeys cover held refusals, pending locks, retries,
keyboard submit, profile/context changes, event/channel changes, navigation,
re-entry and reload. Regression checks fail on the previous context form and
linked-account error handling. The paging assertion also fails before its fix:
the next page's first result has viewport ratio zero. Final checks pass frontend
lint (including TypeScript, i18n and dependency checks), strict multilingual MkDocs,
translation freshness, paragraph checks and generated Architect-guide drift.
Full CI, coverage and cross-browser suites have not run locally.

The original profile and all 276 stored notification values are restored and
verified after the journeys and captures. Browser portrait coverage exercises a
refused upload; successful upload/retry is covered with a component mock rather
than replacing the existing portrait. Chat-account screenshot pairs use one
controlled read fixture to show a long Mattermost identity; no external account
is connected or disconnected. Context screenshots use unsaved demonstration
text. No email, phone, push delivery or model call is triggered.

Twelve equal-viewport pairs capture the previous committed UI with the same local
runtime and records, followed by the working UI. Production files are restored
byte for byte after baseline capture. The source map now covers 99 routes,
1194 component modules and 57 families.

| Evidence | Before | After |
| --- | --- | --- |
| Profile identity, desktop 1440×1000 | [PNG](comparisons/profile-desktop-before.png) | [PNG](comparisons/profile-desktop-after.png) |
| Profile identity, phone 320×740 | [PNG](comparisons/profile-phone-before.png) | [PNG](comparisons/profile-phone-after.png) |
| Personal agent context and working hours, desktop 1440×1000 | [PNG](comparisons/profile-context-desktop-before.png) | [PNG](comparisons/profile-context-desktop-after.png) |
| Personal agent context and working hours, phone 320×740 | [PNG](comparisons/profile-context-phone-before.png) | [PNG](comparisons/profile-context-phone-after.png) |
| Linked chat accounts, desktop 1440×1000 | [PNG](comparisons/profile-chat-accounts-desktop-before.png) | [PNG](comparisons/profile-chat-accounts-desktop-after.png) |
| Linked chat accounts, phone 320×740 | [PNG](comparisons/profile-chat-accounts-phone-before.png) | [PNG](comparisons/profile-chat-accounts-phone-after.png) |
| Notification settings overview, desktop 1440×1000 | [PNG](comparisons/notifications-desktop-before.png) | [PNG](comparisons/notifications-desktop-after.png) |
| Notification settings overview, phone 320×740 | [PNG](comparisons/notifications-phone-before.png) | [PNG](comparisons/notifications-phone-after.png) |
| Searchable event preferences, desktop 1440×1000 | [PNG](comparisons/notification-preferences-desktop-before.png) | [PNG](comparisons/notification-preferences-desktop-after.png) |
| Searchable event preferences, phone 320×740 | [PNG](comparisons/notification-preferences-phone-before.png) | [PNG](comparisons/notification-preferences-phone-after.png) |
| Private chat destinations, desktop 1440×1000 | [PNG](comparisons/notification-routes-desktop-before.png) | [PNG](comparisons/notification-routes-desktop-after.png) |
| Private chat destinations, phone 320×740 | [PNG](comparisons/notification-routes-phone-before.png) | [PNG](comparisons/notification-routes-phone-after.png) |


## First-message composer and dashboard table marks — 2026-11-12

Dashboard table rows reuse the catalog's product mark in a muted tile. Each row
keeps its accessible name, full link target and a minimum 44px height. The SVG is
decorative. Desktop and phone captures use the same existing demo records.

The first chat turn used to gain an ID before the refreshed list held its row.
The access lookup then replaced the composer with Checking conversation access.
The socket now adopts a newly created conversation and its creation fact in one
store update. Selecting another thread or resetting the tenant/session clears
that fact. An existing thread is never adopted as newly created; shared/view-only
and unknown-thread access checks still apply. A regression fails on the previous
implementation with the visible checking notice, and passes after the change.

Six focused files cover the chat hook, container, scoped stores, session reset
and table widget. Chromium desktop/phone checks use a controlled socket creation
frame and a held metadata read: the same editor node remains attached and visible.
These isolate the transition without creating a real conversation or model run.
The baseline captures show the original access notice under the same conditions.

| Evidence | Before | After |
| --- | --- | --- |
| Dashboard tables, desktop | [PNG](comparisons/table-widget-desktop-before.png) | [PNG](comparisons/table-widget-desktop-after.png) |
| Dashboard tables, phone | [PNG](comparisons/table-widget-phone-before.png) | [PNG](comparisons/table-widget-phone-after.png) |
| First-message composer, desktop | [PNG](comparisons/composer-flash-desktop-before.png) | [PNG](comparisons/composer-flash-desktop-after.png) |
| First-message composer, phone | [PNG](comparisons/composer-flash-phone-before.png) | [PNG](comparisons/composer-flash-phone-after.png) |


## Catalogs, knowledge editors and stable Briefing loading — 12 November 2026

Tables and workflows now share a neutral mark in catalogs, detail headers and
Dashboard rows. Their header picker saves one of 14 validated icons, including
reset to the default. The nullable metadata columns are introduced by
`0321_resource_icons.py`; choosing an icon changes neither table schema version
nor workflow draft revision. Existing resource grants and task-board management
restrictions remain enforced.

Agents exposes its primary status filter directly; secondary facets keep their
disclosure. The shared workspace fullscreen action is phone-only and restores
page scrolling and navigation when resized to desktop. Skills opens its existing
instructions/files editor as the catalog default, with an explicit full Content
view action and an unsaved-change guard. The Version tree and unused comparison
assets are removed; History retains its saved-version diffs. Context and skill
improvement use matching sections, a compact model selector and an actionable
no-feedback state instead of unusable start controls. Dataset catalogs and empty
Cases use neutral marks and compact actions while retaining permissions.

Briefing no longer alternates guessed widget skeletons. The optional opening row
coordinates onboarding and suggestion reads in a stable 224px area, independently
of other widgets. A controlled dismissed-onboarding read reproduced the previous
496px-to-224px contraction. Failed reads do not restart on every child observer
mount; an explicit retry remains available.

Verification: 100 focused tests across eight editor/icon/fullscreen files
(including the two additional compact selector cases), 66 dashboard/dataset/filter
tests and 72 header/table tests pass. Backend validation, schema/service and
coverage-contract tests pass (112 tests), as do frontend/backend lint, scoped ty,
Alembic drift and strict multilingual documentation. Migration up/down/up was
checked on connection-local temporary tables without downgrading user data.
Chromium exercised actual icon save/reload/catalog persistence for both resources
at 1440px desktop and touch 320px phone widths, plus Skills modal-to-Content
navigation and phone fullscreen-to-desktop cleanup. Original icons were restored.
Dark/light mark contrast measured 6.43:1 and 5.21:1 respectively.

Screenshot comparisons use equal 1440x1000 or 390x844 viewports. Briefing captures
hold read-only onboarding/suggestion fixtures; no onboarding state is persisted.
No model improvement, external notification or account operation is started.
Full CI, coverage and cross-browser suites have not run locally. The refreshed
source map covers 101 routes, 1248 component modules and 58 families.

| Evidence | Before | After |
| --- | --- | --- |
| catalog-agents-desktop | [PNG](comparisons/catalog-agents-desktop-before.png) | [PNG](comparisons/catalog-agents-desktop-after.png) |
| catalog-agents-phone | [PNG](comparisons/catalog-agents-phone-before.png) | [PNG](comparisons/catalog-agents-phone-after.png) |
| catalog-workflows-desktop | [PNG](comparisons/catalog-workflows-desktop-before.png) | [PNG](comparisons/catalog-workflows-desktop-after.png) |
| catalog-workflows-phone | [PNG](comparisons/catalog-workflows-phone-before.png) | [PNG](comparisons/catalog-workflows-phone-after.png) |
| catalog-tables-desktop | [PNG](comparisons/catalog-tables-desktop-before.png) | [PNG](comparisons/catalog-tables-desktop-after.png) |
| catalog-tables-phone | [PNG](comparisons/catalog-tables-phone-before.png) | [PNG](comparisons/catalog-tables-phone-after.png) |
| catalog-skills-desktop | [PNG](comparisons/catalog-skills-desktop-before.png) | [PNG](comparisons/catalog-skills-desktop-after.png) |
| catalog-skills-phone | [PNG](comparisons/catalog-skills-phone-before.png) | [PNG](comparisons/catalog-skills-phone-after.png) |
| datasets-catalog-desktop | [PNG](comparisons/datasets-catalog-desktop-before.png) | [PNG](comparisons/datasets-catalog-desktop-after.png) |
| datasets-catalog-phone | [PNG](comparisons/datasets-catalog-phone-before.png) | [PNG](comparisons/datasets-catalog-phone-after.png) |
| datasets-empty-desktop | [PNG](comparisons/datasets-empty-desktop-before.png) | [PNG](comparisons/datasets-empty-desktop-after.png) |
| datasets-empty-phone | [PNG](comparisons/datasets-empty-phone-before.png) | [PNG](comparisons/datasets-empty-phone-after.png) |
| skill-improve-desktop | [PNG](comparisons/skill-improve-desktop-before.png) | [PNG](comparisons/skill-improve-desktop-after.png) |
| skill-improve-phone | [PNG](comparisons/skill-improve-phone-before.png) | [PNG](comparisons/skill-improve-phone-after.png) |
| context-improve-desktop | [PNG](comparisons/context-improve-desktop-before.png) | [PNG](comparisons/context-improve-desktop-after.png) |
| context-improve-phone | [PNG](comparisons/context-improve-phone-before.png) | [PNG](comparisons/context-improve-phone-after.png) |
| briefing-loading-desktop | [PNG](comparisons/briefing-loading-desktop-before.png) | [PNG](comparisons/briefing-loading-desktop-after.png) |

Additional dark-theme checks: [Workflows](comparisons/workflows-dark-after.png), [Datasets](comparisons/datasets-dark-after.png).


## Loading geometry audit and event service picker — 12 November 2026

The production-source census covers 1371 TSX files and records 482 loading or
pulsing presentation sites across 244 files in [loading-inventory.md](loading-inventory.md)
and [loading-inventory.json](loading-inventory.json). This includes local
placeholders, step-specific onboarding, frame-constrained widgets/charts, real
form loading, table cells, catalog grids and modal bodies. Some pulsing indicators
represent live activity rather than a read. A source census does not mean every
permission, data size or browser combination has been visually verified.

Confirmed mismatches and fixes:

- Skills initially used a 512x387 dialog before becoming a 1280x968 editor on
  desktop. Its chunk/data loading dialogs now use the editor's actual canvas,
  title, metadata, file tree, pane and footer slots. Catalog title/access metadata
  is reused while the body loads; lazy loading remains, and its fallback closes.
- Context's loading body invented three columns and a second large metadata row.
  It now mirrors Description and its helper text, the pane toolbar and footer.
  Both editor skeletons follow the real mobile metadata/file disclosures and
  the context footer's two-row wrapping. Fork text uses the same workbench shape.
- Dataset detail had an unrelated bordered panel, followed by cards while its
  Cases table loaded. Metadata loading now retains header/breadcrumbs, workspace
  tabs and the case surface. Row loading uses CasesTable/DataTable itself, so
  column names, widths and responsive hiding match. The generic text-file pane
  also retains its toolbar and shows content lines rather than a loading sentence.
- Seven primary catalogs and project Apps now share explicit document/resource/
  project slots and the actual 768/1280px grid breakpoints. Skills and Context
  retain the desktop document preview area while hiding it on phones. Shared
  Skeleton bounds cannot exceed their container width.
- Generic skeleton-panel is removed: it invented nested forms across unrelated
  views. Data-dependent improvement, review, settings, exposure and detail reads
  reserve a neutral pending region until their structure is known. Known tables,
  lists, charts, widget frames and onboarding step-specific layouts remain shaped
  for their own content. The Activity permission read no longer guesses a table
  before the permitted tabs are known. Judge datasets loads as its row list.
- The event-trigger modal uses short branded service disclosures in two desktop
  columns and one phone column. Descriptions, presets and connection prerequisites
  remain available after expansion; connection grants and actions are unchanged.
  Search/category filtering and the compact API trigger remain available. The
  full portal catalog retains its expanded cards.

Verification: 147 focused tests across ten files plus 117 consumer tests across
seven additional files pass. Regression coverage exercises pending-to-editor
geometry tokens and dismissal, dataset metadata-to-page and table row loading,
responsive table column continuity, file loading accessibility and disclosure
behavior. Frontend lint includes ESLint, formatting, TypeScript, i18n and dependency
checks. Whole coverage/CI/cross-browser suites are left to CI rather than run on
this laptop.

Chromium held and released real API reads at desktop 1440x1000 and touch phone
390x844. For Skills and Context, every measured outer dialog and inner editor-pane
coordinate/dimension is identical before and after the read (not just within a
rounded visual tolerance). Dataset metadata and row reads resolve into the real
page. Event selection covers expansion, keyboard collapse, search and dismissal.
Twenty-one catalog reads cover all seven catalogs at 1440, 800 and 390px: each
renders the same 3/2/1 columns as its loaded grid, without horizontal overflow.
No dataset, skill, credential, external integration or model state is written.

Ten equal-viewport before/after pairs are below; the archive additionally contains
ready-state references for all four editor transitions and fourteen catalog
loading captures. Baselines are captured against the previous commit and source
files are restored byte for byte. The route graph now covers 101 routes and 1252
component modules in 58 families.

| Evidence | Before | After |
| --- | --- | --- |
| modal-loading-skills-desktop | [PNG](comparisons/modal-loading-skills-desktop-before.png) | [PNG](comparisons/modal-loading-skills-desktop-after.png) |
| modal-loading-skills-phone | [PNG](comparisons/modal-loading-skills-phone-before.png) | [PNG](comparisons/modal-loading-skills-phone-after.png) |
| modal-loading-context-desktop | [PNG](comparisons/modal-loading-context-desktop-before.png) | [PNG](comparisons/modal-loading-context-desktop-after.png) |
| modal-loading-context-phone | [PNG](comparisons/modal-loading-context-phone-before.png) | [PNG](comparisons/modal-loading-context-phone-after.png) |
| dataset-loading-metadata-desktop | [PNG](comparisons/dataset-loading-metadata-desktop-before.png) | [PNG](comparisons/dataset-loading-metadata-desktop-after.png) |
| dataset-loading-metadata-phone | [PNG](comparisons/dataset-loading-metadata-phone-before.png) | [PNG](comparisons/dataset-loading-metadata-phone-after.png) |
| dataset-loading-cases-desktop | [PNG](comparisons/dataset-loading-cases-desktop-before.png) | [PNG](comparisons/dataset-loading-cases-desktop-after.png) |
| dataset-loading-cases-phone | [PNG](comparisons/dataset-loading-cases-phone-before.png) | [PNG](comparisons/dataset-loading-cases-phone-after.png) |
| event-picker-desktop | [PNG](comparisons/event-picker-desktop-before.png) | [PNG](comparisons/event-picker-desktop-after.png) |
| event-picker-phone | [PNG](comparisons/event-picker-phone-before.png) | [PNG](comparisons/event-picker-phone-after.png) |

Ready editor references: [skills desktop](comparisons/modal-ready-skills-desktop-after.png), [skills phone](comparisons/modal-ready-skills-phone-after.png), [context desktop](comparisons/modal-ready-context-desktop-after.png), [context phone](comparisons/modal-ready-context-phone-after.png).

Catalog loading captures: [apps desktop](comparisons/loading-catalog-apps-desktop.png), [apps phone](comparisons/loading-catalog-apps-phone.png), [skills desktop](comparisons/loading-catalog-skills-desktop.png), [skills phone](comparisons/loading-catalog-skills-phone.png), [context desktop](comparisons/loading-catalog-context-desktop.png), [context phone](comparisons/loading-catalog-context-phone.png), [datasets desktop](comparisons/loading-catalog-datasets-desktop.png), [datasets phone](comparisons/loading-catalog-datasets-phone.png), [projects desktop](comparisons/loading-catalog-projects-desktop.png), [projects phone](comparisons/loading-catalog-projects-phone.png), [tables desktop](comparisons/loading-catalog-tables-desktop.png), [tables phone](comparisons/loading-catalog-tables-phone.png), [workflows desktop](comparisons/loading-catalog-workflows-desktop.png), [workflows phone](comparisons/loading-catalog-workflows-phone.png).

Seven additional permission/fork/reader tests bring this batch to 271 passing tests. Focused V8 coverage for `files/editor-loading.tsx` is 100% statements, branches, functions and lines; the whole frontend coverage suite has not run locally.


## Unified Vault, usable sharing scroll and a persistent Skill modal — 12 November 2026

Vault now uses one typed table for keys, personal accounts and organization
accounts. The separate account cards, premature empty-account states and key
count strip are removed. Add key and owner-specific Connect account controls live
in the page header. Existing per-key edit grants and organization account view/
management gates remain intact; personal actions remain scoped to the member.
Accounts keep their own reconnect/disconnect actions, with disconnect confirmation.
Unknown account creator/usage metadata is marked unavailable rather than invented.
Google accounts use the Google brand glyph, not the Gemini model-provider mark.
All initial reads use the same table columns and responsive visibility as loaded
rows, and one failed feed does not hide other available entries.

The project-sharing defect reproduced with a portaled member/group picker:
wheel delta 900 left its list at scrollTop zero. Giving the nested popover its
own modal scroll-lock scope lets that same gesture reach 900px on desktop and
phone contexts. Its search header stays fixed while one bounded list scrolls;
the limit follows Radix's available collision height. At a 480px-high viewport,
the list stays within the window and remains searchable/selectable. A separate
35-grant fixture verifies the sharing dialog itself scrolls without moving the
page. The shared fix applies to all resource-sharing pickers. Project visibility
copy now says project rather than falling through to secret in all four console
languages.

Matching skeleton bounds alone did not prevent the Skill flash: the initial and
loaded windows were different DOM nodes, repeating their entry animation and
focus initialization. A lightweight SkillEditorFrame now stays mounted across
metadata and lazy editor-module reads. The heavy body remains code-split; the
frame, overlay and focus scope do not get replaced. Browser checks retain the
same dialog node before/after the read at 1440x1000 and touch 390x844, with identical
inner-pane bounds. Normal-motion checks register exactly one dialog entry
animation in both sizes. Full view moves beside Share in the footer; its loading
slot matches and its unsaved-change guard still offers Stay and Discard before
navigating to Content. A source review of multi-return dialog components found
intentional read/edit, check and completion switches, rather than another initial
skeleton-to-editor root replacement.

Validation: 148 focused tests pass across ten files. The unified Vault table
meets its migrated coverage gate: 100% statements/functions/lines and 98.63%
branches; the shared editor loading component has 100% coverage in all four
metrics. Frontend lint, TypeScript, i18n/dependency checks, translation freshness,
Architect-guide synchronization and strict multilingual MkDocs pass. Full CI,
whole-frontend coverage and cross-browser suites have not run locally.

The browser journeys cover mixed account scopes, a cancelled disconnect, short
viewport picker wheel/search/selection, outer dialog scrolling, and Skill loading
through guarded full-view navigation. Long member/grant lists and the two account
rows are controlled read-only fixtures. The mixed Vault references limit displayed
keys to three for composition; ordinary before/after Vault pairs use the real key
listing. No credential, account, project, skill or resource grant is mutated.

The updated graph covers 101 routes and 1251 component modules in 58 families.
The loading census now records 477 presentation sites across 242 files (1370 TSX
sources), after retiring the obsolete account cards and standalone Skill loader.

| Evidence | Before | After |
| --- | --- | --- |
| vault-unified-desktop | [PNG](comparisons/vault-unified-desktop-before.png) | [PNG](comparisons/vault-unified-desktop-after.png) |
| vault-unified-phone | [PNG](comparisons/vault-unified-phone-before.png) | [PNG](comparisons/vault-unified-phone-after.png) |
| project-share-scroll-desktop | [PNG](comparisons/project-share-scroll-desktop-before.png) | [PNG](comparisons/project-share-scroll-desktop-after.png) |
| project-share-scroll-phone | [PNG](comparisons/project-share-scroll-phone-before.png) | [PNG](comparisons/project-share-scroll-phone-after.png) |
| skill-dialog-desktop | [PNG](comparisons/skill-dialog-desktop-before.png) | [PNG](comparisons/skill-dialog-desktop-after.png) |
| skill-dialog-phone | [PNG](comparisons/skill-dialog-phone-before.png) | [PNG](comparisons/skill-dialog-phone-after.png) |
| skill-dialog-loading-desktop | [PNG](comparisons/skill-dialog-loading-desktop-before.png) | [PNG](comparisons/skill-dialog-loading-desktop-after.png) |
| skill-dialog-loading-phone | [PNG](comparisons/skill-dialog-loading-phone-before.png) | [PNG](comparisons/skill-dialog-loading-phone-after.png) |

Mixed account references: [desktop](comparisons/vault-mixed-desktop-after.png), [phone](comparisons/vault-mixed-phone-after.png).
