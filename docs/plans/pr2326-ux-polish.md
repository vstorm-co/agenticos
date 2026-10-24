# PR 2326: console interaction and visual polish

## Direction study

Compared three compositions using the console's actual Button, Input, FormField,
Card, Tabs, DataTable, Dialog and Sheet components in a disposable local preview.
Sample agent names and counts were review fixtures, not deployment data.

| Direction | Assessment | Decision |
| --- | --- | --- |
| Dense, 12px panel spacing | Lists fit, but fields and adjacent actions crowd each other | Reject as the global default |
| Spacious, 32px panel spacing | Clear separation, but form actions move below the initial desktop viewport | Reject as the global default |
| Adaptive, 16px phone / 24px desktop spacing | Keeps a clear list/form hierarchy and readable controls | Implement within the existing neutral design system |

The selected direction was inspected in light and dark at a desktop viewport.
This is a component study, not a claim of a manual review of all product screens.
A 390px embedded preview could not be inspected with the available browser
surface; physical iOS/Android keyboard and safe-area behavior remains unverified.
The disposable route and server were removed. No preview data ships in the app.

## Shared surface coverage

The dashboard contains 59 page entry points. Changes belong at the shared layers
so that the same controls behave consistently across those views and native shells.

| Surface family | Applied work |
| --- | --- |
| Navigation and settings/admin tabs | Labelled search above destinations, visible desktop shortcut, taller rows, contained horizontal tab scrolling, visible keyboard focus; search navigation closes the phone drawer |
| Agent/catalog/knowledge/project lists and run/admin tables | Quiet sentence-case headings, aligned tabular numbers, keyboard activation of clickable rows, clearable search with Escape behavior, touch-sized pager/filter controls |
| Settings, Builder and creation/edit forms | Consistent solid fields, larger touch targets, readable help/error text, preserved external help IDs, error announcements |
| Dialogs, viewers and side panels | Shared visible-height budget, phone gutters, larger dismiss controls, Radix focus containment and scroll locking, restored opener focus, nested-menu Escape behavior |
| Dashboard and glanceable metrics | Widget container queries instead of viewport-only columns, reduced phone padding, readable labels, bounded body scrolling |
| Chat and native phone transitions | Shorter streaming/card/page entrances, opacity-only word arrival, less travel between native pages, larger attachment-sheet dismiss target |
| Notifications, toasts and empty/error states | Screen-height bounds, larger dismiss/load targets, wrapped summaries, theme-aware toast surfaces, smaller phone empty-state spacing and consistent retry buttons |

## Verification

Focused behavior tests cover focus trapping/restoration, nested menus, search
clearing inside actual dialogs and sheets, preserving input descriptions, table
keyboard activation, and drawer closure after command-palette navigation.
TypeScript, ESLint, translation and formatting checks run before push. Full suites
and coverage gates run only in GitHub Actions.
