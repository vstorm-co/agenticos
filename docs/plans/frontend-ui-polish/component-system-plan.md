# Console component consistency plan

Date: 2026-11-19. PR: [#3160](https://github.com/vstorm-co/agenticos/pull/3160).
Status: code inventory and initial inspection complete; application-wide migration not started.

## Outcome

Make the entire application use the accepted Minimal chat's quiet surfaces, restrained borders, compact controls and predictable interactions. Preserve the current typography, neutral palette, light/dark themes and product identity. Consistency means the same control behaves and looks the same in equivalent contexts; a data grid, a voice call and a long settings form still need different layouts.

The [inventory](component-inventory.md) covers all current component directories, all 69 shared UI modules and 101 App Router page modules. Inspection concentrated on shared primitives and representative chat, dashboard, settings, model, table, navigation and editor compositions. This is a code audit, not a visual certification of every route. No screenshots, Computer Use or Browser Use were run.

The current request is to review and plan first. The waves below are pending implementation. The preceding chat refinements remain part of this PR and do not establish that the rest of the application has migrated.

## What the code shows

Counts below include named imports through the UI barrel, not just direct module imports. They count distinct importing files, not visible controls.

| Shared family                 | Importing files | Consequence                                                                               |
| ----------------------------- | --------------: | ----------------------------------------------------------------------------------------- |
| Button                        |             557 | Button surface, density and focus changes have the widest reach.                          |
| Label / Input / Select        | 201 / 185 / 173 | A shared field contract can remove much of the inconsistent form styling.                 |
| Dialog                        |             148 | Change its presentation in one place; preserve dismissal, onboarding and focus contracts. |
| FormField                     |              82 | Already available; reuse its labels, descriptions and validation wiring.                  |
| ListCard / Switch             |         74 / 74 | Catalog framing and toggle rows can share a consistent rhythm.                            |
| DropdownMenu / Popover / Tabs |    51 / 35 / 27 | Shared wrappers exist, but local compositions and chat-only CSS still diverge.            |

There are also 414 native button occurrences in 255 source files and 66 native details occurrences in 53 files. Some are legitimate semantic controls or special interactions. Inspect each candidate; do not replace native markup mechanically or delete modules based on an import count.

### Confirmed presentation inconsistencies and migration targets

| Evidence in the current tree                                                                                                        | Why it differs                                                                                                                                                                                   | Planned change                                                                                                                                                                          |
| ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `frontend/src/components/chat/conversation-filters.tsx:131`                                                                         | `space-y-5 p-4`, bespoke underlined Active/Archived buttons at line 133 and default-size selects at lines 162/192 build the oversized panel in the user's screenshot.                            | First migration example: compact filter panel, consistent field spacing and a compact exclusive-choice control; preserve server-side filtering, archived agents and API-thread switch.  |
| `frontend/src/components/ui/control-styles.ts:11`                                                                                   | `FORM_CONTROL` gives all fields a 2px border. Outline buttons also use 2px; floating panels use 1px. This makes fields visually heavier than the accepted chat.                                  | Define shared resting field/action edges and distinct focus/invalid states; compare both themes before changing defaults.                                                               |
| `frontend/src/components/ui/list-filters.tsx:40` and `control-styles.ts:18`                                                         | ListFilters duplicates filter styling with `rounded-lg border`, while FILTER_CONTROL uses `rounded-xl` and different spacing.                                                                    | One toolbar-control density and state contract, reused by disclosure and select triggers.                                                                                               |
| `frontend/src/components/ui/popover.tsx:24`, `dropdown-menu.tsx:132`, `select.tsx:92`                                               | Each wrapper repeats a floating-surface recipe; their insets and row geometry differ.                                                                                                            | Shared surface and menu-row style ownership, with explicit panel/menu content padding. Keep Radix semantics.                                                                            |
| `frontend/src/components/chat/chat-layout.css:135`                                                                                  | Main-chat presence changes portalled `.panel` surfaces through `body:has(...)`; other routes keep the old wrapper style. It can also affect unrelated portals on the chat route.                 | Promote accepted surface values to shared owners, migrate callers, then remove the route-presence override. Keep composer-specific layout local.                                        |
| `frontend/src/components/settings/settings-section.tsx:146` and `:183` versus `settings/service-card.tsx:64` and `:107`             | SettingsSection uses larger headings and immediate `hidden`; ServiceCard has smaller headings and DisclosureContent. Service descriptions reserve `min-h-10` at lines 87/96 even for short copy. | Consistent settings heading/disclosure rhythm, with service cards and simple sections as explicit compositions. Avoid a blank description row where unnecessary.                        |
| `frontend/src/components/ui/tabs.tsx:83` and `chat/conversation-filters.tsx:133`                                                    | Shared Radix tabs exist, but the conversation filter implements an independent exclusive-choice strip.                                                                                           | Use a shared compact choice pattern for filters; keep actual tab semantics for tab panels. Do not make every toggle a tab.                                                              |
| `frontend/src/components/agents/model-combobox.tsx:116` and `:191`, `agents/model-profile-picker.tsx`, `chat/chat-model-picker.tsx` | Catalog selection, saved profile editing and chat overrides have different responsibilities; the visible rows and trigger summaries are composed separately.                                     | Share model/provider identity, row layout, checkmark, truncation and loading/error presentation; retain profile creation, permissions and personal-connection logic at existing owners. |
| `frontend/src/components/tables/record-filters-popover.tsx:151`                                                                     | A condition editor uses a responsive grid and nested field editors, unlike a simple list filter.                                                                                                 | Reuse filter panel framing and field density without flattening its typed column/operator/value logic.                                                                                  |
| `frontend/src/components/files/file-card.tsx:84` and `:94`                                                                          | Gallery and compact file rows already have separate presentations.                                                                                                                               | Keep both intentional modes; align border, action target, metadata and focus tokens instead of forcing one shape.                                                                       |

These are presentation findings, not claims that all the components are functionally broken. Existing good contracts include FormField error wiring, touch targets, Radix focus handling, shared table loading/error/empty props, model logos and permission-aware selectors. Preserve them.

## Shared presentation contract

Implement in existing owners before adding wrappers. Introduce a new composite only after migrating two real callers with the same structure.

| Area           | Target contract                                                                                                                                                                                                                                                                    |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Surfaces       | Existing page/card/popover colors; one quiet edge and elevation recipe for floating panels. Cards remain flat. No route-dependent recoloring, new glass theme or global `!important` patch.                                                                                        |
| Density        | Explicit form and compact-toolbar modes. Start from current 40px form and 36px toolbar controls; menus approximately 36–40px on fine pointers. Preserve at least 44px coarse-pointer targets. Do not shrink every input to fit a popover.                                          |
| Type           | Existing family; 14px body/control labels, 13px compact metadata where appropriate. No blanket reduction to the chat's smallest labels. Long translated text wraps or truncates with accessible full meaning.                                                                      |
| Fields         | Input, Textarea, SelectTrigger, NativeSelect, search and model-combobox triggers share resting, hover, open, focus, disabled and invalid states. Error state is not color alone.                                                                                                   |
| Menus          | Consistent icon column, text/description hierarchy, right-side selection indicator and separators. Distinguish menus from forms in popovers; retain search and keyboard semantics.                                                                                                 |
| Settings       | Consistent icon/title/summary/action alignment; title disclosure and switch are separate controls. Disabled, missing configuration and permission refusal are different states.                                                                                                    |
| Navigation     | Page tabs, compact filter choices and wizard steps are distinct patterns sharing type, focus and motion. URL/query-driven tabs preserve state and history.                                                                                                                         |
| Motion         | Shared duration/easing tokens, 0.97-scale/opacity entrances, state-driven chevrons and subtle press feedback. Popup anchors and form fields stay still. No `transition: all`, replay of whole screens on streaming updates or lost release velocity in existing drag interactions. |
| Reduced motion | Respect OS preference and the existing application preference. Functional state remains visible without animation. Preserve theme-switch transition suppression.                                                                                                                   |
| Feedback       | Skeletons hold useful geometry; loading, empty, filtered-empty, denied and failed states stay distinct. Pending actions do not resize.                                                                                                                                             |

## Migration waves

### 1. Shared controls and the reported filter panel

- [ ] Consolidate field, action and floating-surface values in `control-styles.ts`, shared UI wrappers and existing global tokens.
- [ ] Align Button/IconButton, Input/Textarea/NativeSelect/Select, Switch/Checkbox and search controls; keep existing props and focus contracts.
- [ ] Align Popover/DropdownMenu/ContextMenu/Tooltip surface and row styling. Keep forms, command lists and menus semantically distinct.
- [ ] Migrate ConversationFilters first, followed by ListFilters and dashboard period/section controls. Keep filters in the same row as tabs where the page already uses that pattern.
- [ ] Promote reusable Minimal surface styling out of `chat-layout.css`; remove the corresponding body/portal override only after callers inherit the shared style.
- [ ] Verify narrow filter panels, long agent/model names, keyboard opening/Escape/focus return and both themes. Keep current filter behavior unchanged.

Deliverable: the screenshot's panel and equivalent shared controls look coherent both inside and outside `/chat`.

### 2. Repeated compositions

- [ ] Field groups and compact filter panels: FormField, ListFilters, ListCardControlsRow, sort/search/period controls and condition-editor framing.
- [ ] Model/provider choices: ModelCombobox, ModelProfilePicker, ChatModelPicker, eval model pickers, service defaults and voice selectors. Use shared identity/row presentation, not one universal business component.
- [ ] Cards and settings: Card, ListCard, SettingsSection, SectionCard, ServiceCard and capability configuration headers; standardize rhythm without adding cards around every section.
- [ ] Dialog/ConfirmDialog/AlertDialog/Sheet headers, content and footer spacing. Preserve unsaved/pending writes, non-dismissible operations, onboarding exceptions and nested OAuth dialogs.
- [ ] Tabs, wizard steps and disclosures: migrate custom copies; use DisclosureContent where persistent form state is required. Do not unmount unsaved fields just to animate them.
- [ ] Shared empty/error/loading, status badges, toast and skeleton styles.

Deliverable: repeated patterns have one owner and real callers no longer carry duplicate presentation recipes.

### 3. Route and feature migration

Use the inventory's complete directory and route checklists. Mark each route only after checking its actual component path; a shared import alone is not proof of completion.

| Feature group               | Component directories included                                                   | Inspect/migrate                                                                                                                                                                                  |
| --------------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Shell and onboarding        | layout, branding, theme, language-switcher, onboarding, public-config, legal     | Navigation, workspace/account menus, search, header/actions, onboarding overlays and theme transitions. Preserve branding choices.                                                               |
| Chat and assistant surfaces | chat, assistant, inbox, voice, phone, desktop, mobile, hosted                    | Conversation filters, commands/mentions, transcript steps/tools/drafts/approvals, inbox rows, files/usage, recording/call states and responsive shell. Embedded chat isolation remains explicit. |
| Agent authoring             | agents, authoring, improvement, skill-improvement, remote-agents                 | Builder sections, capability cards, tool/config fields, published/dirty/disabled states, permission and model selectors.                                                                         |
| Workflows and automation    | workflows, triggers, watches, tasks                                              | Editor toolbars, palette, property fields, run/debug panels, schedule pickers and task rows. Canvas interaction remains specialized.                                                             |
| Knowledge and memory        | rag, kb, context, memory, skills, knowledge-gaps, projects                       | Library lists, searches, editors, source pickers, ingestion states, project controls and memory filters.                                                                                         |
| Data and evaluations        | tables, datasets, evals, runs, charts                                            | Tables/grid cells, column menus, bulk actions, pagination, review dialogs, filters, run details and chart controls.                                                                              |
| Workspace administration    | settings, orgs, groups, teams, admin, sharing, vault, mcp, channels, oauth, auth | Members/roles, invitations, grants, keys/accounts, connection dialogs, AI services, channel configuration and sign-in forms.                                                                     |
| Files and applications      | files, artifacts, sandboxes, browser, live-updates                               | Upload/drop, file row/gallery/viewer/editor, artifact/version menus, sandbox/session and browser controls.                                                                                       |
| Cross-cutting support       | ui, states, icons, illustrations, shared                                         | Token ownership, state presentation, MCP/provider/model identities and reusable marks.                                                                                                           |

Do not apply console-density changes blindly to public forms, embedded widgets, phone controls or the development playground. They belong to the review, but adaptation must preserve their surface-specific usability. Capability artwork and brand illustrations retain their identity; their surrounding controls inherit the shared system.

### 4. Specialized interactions and cleanup

- [ ] Editor/canvas drag, selection, docking, resizing and keyboard bindings: reuse surfaces and controls, preserve coordinate and gesture behavior.
- [ ] Streaming steps, long/virtualized lists, live counters and voice state: prevent remount/entrance animations on each update.
- [ ] Audit the inventory's native button/input/details candidates. Reuse shared presentation where appropriate; retain native semantics and specialized handlers where necessary.
- [ ] Remove superseded local classes and duplicate composition code only after all consumers migrate. Verify usage beyond direct imports before deleting any module.
- [ ] Review new presentation abstractions against actual callers; remove variants/props introduced without a real use.

## Verification and completion criteria

For each wave:

1. Run relevant existing component tests and add regression tests for changed behavior (focus, open/close, selection, disabled state, form persistence and keyboard access). Avoid tests that only copy class strings.
2. Check representative light/dark surfaces at narrow and desktop widths, enlarged/translated text, OS/application reduced motion and coarse-pointer targets. Do not claim contrast or geometry is verified from source alone.
3. Use focused Playwright DOM/keyboard checks if browser execution is needed; do not open Computer Use/Browser Use or take screenshots. The user reviews visual results on `http://localhost:3018`.
4. Run formatting, lint, type and translation checks appropriate to the diff; CI owns full coverage, integration and e2e suites. Do not run whole suites locally.
5. Preserve data hooks, server queries, authorization gates, dirty state, focus restoration, URL state and pending-write protections. No database/model/provider changes are part of this UI migration.
6. Update the route checklist and PR verification record with changed files, checks and unresolved exceptions. A green old SHA does not prove a new SHA passed CI.

Completion means equivalent controls share presentation throughout the route checklist, legitimate specialized variants are explicit, and remaining exceptions have a concrete reason. It does not mean every screen is forced into the chat composer's shape.

## Guidance used

- [Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md): interaction semantics, focus, motion, layout and state checks.
- Modern Web Guidance `accessibility` and `forms` guides, retrieved 2026-11-19: persistent labels, descriptions, keyboard/focus behavior and pointer target sizing. Their recommendations inform this migration; existing Radix and project contracts remain in place.
- Existing repository frontend rules and the current Minimal implementation. No additional UI library or dependency upgrade is planned.
