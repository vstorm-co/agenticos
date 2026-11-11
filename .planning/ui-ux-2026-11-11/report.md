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

Not exercised end to end: real model responses, approval/run/evaluation outcome
combinations, authenticated external integrations, OAuth consent providers, knowledge
parsing with an embedding provider, token-bound public viewers/forms/invitations,
and native desktop/mobile shells. Those views remain in the source inventory; this
report does not claim that every possible state of every component was tested.

Optional avatar 404s and default-layout 404s were distinguished from failures of
primary page data. Public GitHub release checks returned 503 after repeated local
navigation; those optional network checks were not treated as broken resource lists.
An automated contrast finding during MCP card fade-in was rechecked with motion
settled rather than changing otherwise readable colors.
