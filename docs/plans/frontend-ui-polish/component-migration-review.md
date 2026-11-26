# Component migration verification

Date: 2026-11-19. Scope: PR #3160, the accepted Minimal presentation promoted across the application.

## Implemented ownership

| Family                  | Shared owner and adaptation                                                                                                                                                                                                                                                                |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Fields and actions      | `control-styles.ts`, Button/IconButton, Input/Textarea/NativeSelect/Select; quiet 1px resting edges, explicit focus/invalid states, independent touch targets.                                                                                                                             |
| Floating panels         | `FLOATING_PANEL`, `.panel`, shared elevation and timing tokens; Popover, Select, DropdownMenu and ContextMenu inherit the same surface. The chat-route portal override and unused glass surface were removed.                                                                              |
| Menu and command rows   | `MENU_ROW`, `MENU_LABEL`, `MENU_SEPARATOR`, existing focus contracts; all nine cmdk picker modules, slash/mention palettes, profile choices and conversation search.                                                                                                                       |
| Exclusive choices       | ChoiceGroup moved from settings to `ui/`; conversation filters reuse its keyboard behavior. Dashboard segments share its geometry; real page tabs and tab panels retain their own semantics.                                                                                               |
| Settings disclosures    | MoreOptions and SettingsSection reuse DisclosureContent. Drafts remain mounted, closed sections remain inert, focus returns to their trigger. Native validation can reveal and focus a hidden required field. ServiceCard shares this validation path.                                     |
| Native disclosures      | 61 details instances across 50 existing files use NativeDisclosure, forwarding the actual native element/ref/events. Intrinsic-size animation is feature-detected; unsupported browsers retain instantaneous native opening. No extra arrow-key handlers or exclusive grouping were added. |
| Cards, states and files | Existing Card/ListCard/DataTable state contracts retained; settings/service title rhythm aligned, empty/error actions aligned, file gallery/compact modes retained with shared independent icon actions.                                                                                   |
| Specialized surfaces    | Canvas toolbar/minimap elevation aligns with shared tokens; canvas controls keep gesture/coordinate behavior and gain coarse-pointer targets. Native range/color/choice controls keep their native semantics and share focus styling.                                                      |

## Route integration review

All 101 page entry points and their ancestor layouts were traced through local import/export paths. Named imports through the UI barrel resolve to the relevant exports. This is source integration coverage, not proof that every branch of every route was rendered. Other domain barrels and conditional imports can make reachability an upper bound. Public branded forms, hosted/desktop/phone surfaces, artwork, native media/QR backgrounds and legal typography keep their intentional layouts. Redirect pages have no controls to migrate.

Runtime coverage is listed separately; a dash means it was not exercised in Playwright. Dynamic resource IDs and destructive/provider-backed flows were not invented to fill the table.

| Page module                                                   | Source integration                       | Runtime sample           |
| ------------------------------------------------------------- | ---------------------------------------- | ------------------------ |
| `[locale]/(auth)/forgot-password/page.tsx`                    | Shared presentation path checked         | —                        |
| `[locale]/(auth)/login/page.tsx`                              | Shared presentation path checked         | —                        |
| `[locale]/(auth)/magic-link-sent/page.tsx`                    | Text/native links; themed shell retained | —                        |
| `[locale]/(auth)/register/page.tsx`                           | Shared presentation path checked         | —                        |
| `[locale]/(auth)/reset-password/page.tsx`                     | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/admin/background-jobs/page.tsx`         | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/admin/organizations/[id]/page.tsx`      | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/admin/organizations/page.tsx`           | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/admin/page.tsx`                         | Redirect preserved                       | —                        |
| `[locale]/(dashboard)/admin/settings/page.tsx`                | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/admin/system/page.tsx`                  | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/admin/users/page.tsx`                   | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/agents/[id]/evals/[runId]/page.tsx`     | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/agents/[id]/improve/[session]/page.tsx` | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/agents/[id]/page.tsx`                   | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/agents/page.tsx`                        | Shared presentation path checked         | DOM/keyboard             |
| `[locale]/(dashboard)/apps/page.tsx`                          | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/browse/[runId]/[callId]/page.tsx`       | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/channels/page.tsx`                      | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/chat/page.tsx`                          | Shared presentation path checked         | DOM/keyboard             |
| `[locale]/(dashboard)/context/page.tsx`                       | Shared presentation path checked         | DOM/keyboard             |
| `[locale]/(dashboard)/dashboard/page.tsx`                     | Shared presentation path checked         | DOM/keyboard             |
| `[locale]/(dashboard)/datasets/[id]/page.tsx`                 | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/datasets/page.tsx`                      | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/dev/components/page.tsx`                | Shared presentation path checked         | DOM/keyboard             |
| `[locale]/(dashboard)/documents/[id]/page.tsx`                | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/documents/page.tsx`                     | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/evals/page.tsx`                         | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/groups/[id]/page.tsx`                   | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/groups/page.tsx`                        | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/inbox/page.tsx`                         | Shared presentation path checked         | DOM/keyboard             |
| `[locale]/(dashboard)/invitations/[token]/page.tsx`           | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/invitations/pending/page.tsx`           | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/kb/[id]/page.tsx`                       | Redirect preserved                       | —                        |
| `[locale]/(dashboard)/kb/page.tsx`                            | Redirect preserved                       | —                        |
| `[locale]/(dashboard)/link/[token]/page.tsx`                  | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/mcp-servers/page.tsx`                   | Shared presentation path checked         | DOM/keyboard             |
| `[locale]/(dashboard)/orgs/[id]/directory/page.tsx`           | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/orgs/[id]/groups/page.tsx`              | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/orgs/[id]/members/page.tsx`             | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/orgs/[id]/retention/page.tsx`           | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/orgs/[id]/roles/page.tsx`               | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/orgs/page.tsx`                          | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/profile/page.tsx`                       | Redirect preserved                       | —                        |
| `[locale]/(dashboard)/projects/[id]/page.tsx`                 | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/projects/page.tsx`                      | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/rag/[id]/page.tsx`                      | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/rag/page.tsx`                           | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/remote-agents/page.tsx`                 | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/routines/page.tsx`                      | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/runs/page.tsx`                          | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/sandboxes/page.tsx`                     | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/settings/account/page.tsx`              | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/settings/api-keys/page.tsx`             | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/settings/api-keys/reference/page.tsx`   | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/settings/assistant/page.tsx`            | Redirect preserved                       | —                        |
| `[locale]/(dashboard)/settings/blobby/page.tsx`               | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/settings/desktop/page.tsx`              | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/settings/mcp/page.tsx`                  | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/settings/memory/page.tsx`               | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/settings/mobile/page.tsx`               | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/settings/notifications/page.tsx`        | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/settings/page.tsx`                      | Redirect preserved                       | DOM; redirect to profile |
| `[locale]/(dashboard)/settings/profile/page.tsx`              | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/settings/shortcuts/page.tsx`            | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/settings/sign-ins/page.tsx`             | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/settings/slash-commands/page.tsx`       | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/skills/[id]/improve/[session]/page.tsx` | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/skills/[id]/page.tsx`                   | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/skills/page.tsx`                        | Shared presentation path checked         | DOM/keyboard             |
| `[locale]/(dashboard)/tables/[id]/page.tsx`                   | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/tables/page.tsx`                        | Shared presentation path checked         | DOM/keyboard             |
| `[locale]/(dashboard)/vault/page.tsx`                         | Shared presentation path checked         | DOM/keyboard             |
| `[locale]/(dashboard)/work/page.tsx`                          | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/workflows/[id]/form-preview/page.tsx`   | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/workflows/[id]/logs/page.tsx`           | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/workflows/[id]/page.tsx`                | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/workflows/[id]/runs/[runId]/page.tsx`   | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/workflows/[id]/runs/page.tsx`           | Shared presentation path checked         | —                        |
| `[locale]/(dashboard)/workflows/page.tsx`                     | Shared presentation path checked         | DOM/keyboard             |
| `[locale]/(dashboard)/workflows/runs/page.tsx`                | Shared presentation path checked         | —                        |
| `[locale]/(viewer)/apps/[id]/page.tsx`                        | Shared presentation path checked         | —                        |
| `[locale]/(viewer)/oauth/consent/page.tsx`                    | Shared presentation path checked         | —                        |
| `[locale]/a/[publicKey]/page.tsx`                             | Shared presentation path checked         | —                        |
| `[locale]/auth/callback/page.tsx`                             | Shared presentation path checked         | —                        |
| `[locale]/auth/email-change/page.tsx`                         | Shared presentation path checked         | —                        |
| `[locale]/auth/magic-link/page.tsx`                           | Shared presentation path checked         | —                        |
| `[locale]/auth/pair/page.tsx`                                 | Shared presentation path checked         | —                        |
| `[locale]/desktop/blobby/page.tsx`                            | Shared presentation path checked         | —                        |
| `[locale]/desktop/quick-ask/page.tsx`                         | Shared presentation path checked         | —                        |
| `[locale]/desktop/readiness/page.tsx`                         | Shared presentation path checked         | —                        |
| `[locale]/desktop/welcome/page.tsx`                           | Shared presentation path checked         | —                        |
| `[locale]/e/[publicKey]/page.tsx`                             | Shared presentation path checked         | —                        |
| `[locale]/f/[token]/page.tsx`                                 | Shared presentation path checked         | —                        |
| `[locale]/legal/cookies/page.tsx`                             | Text/native links; themed shell retained | —                        |
| `[locale]/legal/privacy/page.tsx`                             | Text/native links; themed shell retained | —                        |
| `[locale]/legal/terms/page.tsx`                               | Text/native links; themed shell retained | —                        |
| `[locale]/onboarding/[...step]/page.tsx`                      | Redirect preserved                       | —                        |
| `[locale]/onboarding/page.tsx`                                | Shared presentation path checked         | —                        |
| `[locale]/page.tsx`                                           | Redirect preserved                       | —                        |
| `[locale]/shared/[token]/page.tsx`                            | Shared presentation path checked         | —                        |

## Explicit exceptions

- Provider/MCP/connector marks with baked artwork keep their light logo tiles. Media players use black backing; QR codes and isolated published artifacts keep their own document background. These colors carry content requirements rather than a competing console theme.
- Code editors keep mirrored text/selection layers, native textareas and scroll synchronization. Their containing fields, toolbar buttons and menus inherit shared styles.
- Workflow canvas nodes/handles, drag/drop, chart drawing, voice visualization and image/brand illustrations keep their geometry and rendering. Only their controls and surrounding surfaces migrate.
- Native hidden file inputs, transparent radio-card inputs and inline rename/command editors are not converted into full-size forms. They preserve their owning control and focus contract.
- Settings, table filters and public forms retain field-specific data and authorization logic. No provider selection, credential binding, model configuration, database or permission boundary was changed by this migration.

## Evidence

- Focused component tests cover native/controlled disclosure behavior, preserved drafts, hidden-field validation, filter radio keyboard selection, all shared menu contracts, model/profile/account controls, file actions, tables and specialized chat/editor behavior. Exact batches are in `verification.md`.
- The first Playwright pass completed 15 cases without client exceptions: shared fields and menus at 1440/390px in light/dark, main-chat filters and new-chat disabled controls, plus Dashboard, Agents, Workflows, Skills, Context, Tables, Inbox, Settings, Vault and MCP servers. Catalog route samples had no document horizontal overflow.
- A final eight-case Playwright pass verified native disclosure keyboard/draft retention, settled light/dark fields and menu focus at both widths, main-chat filters, Settings and coarse-pointer fields/disclosures at 44px or larger. No client exceptions were observed. These checks captured no screenshots and used no Computer Use/Browser Use.
- Local broad suites were not run; full CI/coverage/e2e belong to GitHub Actions. New-SHA results must be checked after the push.
