# Frontend component inventory

Snapshot: 2026-11-19, branch `codex/chat-inbox-ui-polish`. See [the migration plan](component-system-plan.md).

## Method and limits

Static enumeration of `.ts`/`.tsx` files under `frontend/src`, excluding `.test.`, `.spec.` and `.stories.`. Counts include helpers and barrel modules, not only React components. CSS and assets are outside these module counts. Imports include direct `@/components/ui/<module>` imports and named imports through `@/components/ui`, resolved against its current export barrel. Counts are distinct importing files, not rendered instances; relative imports, lazy imports and other re-export chains are not resolved. Zero is not evidence that a module is unused. Native JSX is a migration search index, not an accessibility defect count.

- Source modules: 2320.
- Shared UI modules: 69 (including `index.ts`).
- App Router `page.tsx` modules: 101.

## Shared modules

| Module                                                                                               | Importing source files |
| ---------------------------------------------------------------------------------------------------- | ---------------------: |
| [`alert-dialog`](../../../frontend/src/components/ui/alert-dialog.tsx)                               |                      6 |
| [`alert`](../../../frontend/src/components/ui/alert.tsx)                                             |                     24 |
| [`animated-counter`](../../../frontend/src/components/ui/animated-counter.tsx)                       |                      1 |
| [`animated-number`](../../../frontend/src/components/ui/animated-number.tsx)                         |                      4 |
| [`avatar-color-picker`](../../../frontend/src/components/ui/avatar-color-picker.tsx)                 |                      5 |
| [`avatar-face`](../../../frontend/src/components/ui/avatar-face.tsx)                                 |                     10 |
| [`avatar`](../../../frontend/src/components/ui/avatar.tsx)                                           |                      2 |
| [`badge`](../../../frontend/src/components/ui/badge.tsx)                                             |                    152 |
| [`beam`](../../../frontend/src/components/ui/beam.tsx)                                               |                      0 |
| [`bell-glyph`](../../../frontend/src/components/ui/bell-glyph.tsx)                                   |                      1 |
| [`button`](../../../frontend/src/components/ui/button.tsx)                                           |                    557 |
| [`card`](../../../frontend/src/components/ui/card.tsx)                                               |                     62 |
| [`checkbox`](../../../frontend/src/components/ui/checkbox.tsx)                                       |                     64 |
| [`code-area`](../../../frontend/src/components/ui/code-area.tsx)                                     |                     10 |
| [`confirm-dialog`](../../../frontend/src/components/ui/confirm-dialog.tsx)                           |                     61 |
| [`console-toaster`](../../../frontend/src/components/ui/console-toaster.tsx)                         |                      1 |
| [`context-help`](../../../frontend/src/components/ui/context-help.tsx)                               |                     19 |
| [`context-menu`](../../../frontend/src/components/ui/context-menu.tsx)                               |                      2 |
| [`control-styles`](../../../frontend/src/components/ui/control-styles.ts)                            |                     12 |
| [`data-table`](../../../frontend/src/components/ui/data-table.tsx)                                   |                     28 |
| [`date-range-picker`](../../../frontend/src/components/ui/date-range-picker.tsx)                     |                      1 |
| [`dialog`](../../../frontend/src/components/ui/dialog.tsx)                                           |                    148 |
| [`disclosure-content`](../../../frontend/src/components/ui/disclosure-content.tsx)                   |                      3 |
| [`doc-peek`](../../../frontend/src/components/ui/doc-peek.tsx)                                       |                      6 |
| [`dropdown-menu`](../../../frontend/src/components/ui/dropdown-menu.tsx)                             |                     51 |
| [`entity-avatar`](../../../frontend/src/components/ui/entity-avatar.tsx)                             |                     24 |
| [`figure-spark`](../../../frontend/src/components/ui/figure-spark.tsx)                               |                      0 |
| [`figure`](../../../frontend/src/components/ui/figure.tsx)                                           |                     23 |
| [`form-field`](../../../frontend/src/components/ui/form-field.tsx)                                   |                     82 |
| [`generated-image`](../../../frontend/src/components/ui/generated-image.tsx)                         |                      0 |
| [`icon-button`](../../../frontend/src/components/ui/icon-button.tsx)                                 |                     18 |
| [`index`](../../../frontend/src/components/ui/index.ts)                                              |                      0 |
| [`input`](../../../frontend/src/components/ui/input.tsx)                                             |                    185 |
| [`json-view`](../../../frontend/src/components/ui/json-view.tsx)                                     |                      5 |
| [`label`](../../../frontend/src/components/ui/label.tsx)                                             |                    201 |
| [`line-diff`](../../../frontend/src/components/ui/line-diff.tsx)                                     |                      3 |
| [`list-card`](../../../frontend/src/components/ui/list-card.tsx)                                     |                     74 |
| [`list-controls`](../../../frontend/src/components/ui/list-controls.tsx)                             |                     64 |
| [`list-filters`](../../../frontend/src/components/ui/list-filters.tsx)                               |                     10 |
| [`markdown-editor`](../../../frontend/src/components/ui/markdown-editor.tsx)                         |                     21 |
| [`markdown-mode-toggle`](../../../frontend/src/components/ui/markdown-mode-toggle.tsx)               |                      3 |
| [`more-options`](../../../frontend/src/components/ui/more-options.tsx)                               |                     24 |
| [`native-select`](../../../frontend/src/components/ui/native-select.tsx)                             |                     10 |
| [`optional-setting`](../../../frontend/src/components/ui/optional-setting.tsx)                       |                      2 |
| [`pagination-bar`](../../../frontend/src/components/ui/pagination-bar.tsx)                           |                     13 |
| [`popover`](../../../frontend/src/components/ui/popover.tsx)                                         |                     35 |
| [`preview-skeleton`](../../../frontend/src/components/ui/preview-skeleton.tsx)                       |                      3 |
| [`progress`](../../../frontend/src/components/ui/progress.tsx)                                       |                      3 |
| [`question-prompt`](../../../frontend/src/components/ui/question-prompt.tsx)                         |                      4 |
| [`question-slide`](../../../frontend/src/components/ui/question-slide.tsx)                           |                      0 |
| [`resource-icon`](../../../frontend/src/components/ui/resource-icon.tsx)                             |                      5 |
| [`scroll-fade`](../../../frontend/src/components/ui/scroll-fade.ts)                                  |                      5 |
| [`section-heading`](../../../frontend/src/components/ui/section-heading.tsx)                         |                      5 |
| [`select`](../../../frontend/src/components/ui/select.tsx)                                           |                    173 |
| [`separator`](../../../frontend/src/components/ui/separator.tsx)                                     |                      1 |
| [`sheet`](../../../frontend/src/components/ui/sheet.tsx)                                             |                     16 |
| [`skeleton`](../../../frontend/src/components/ui/skeleton.tsx)                                       |                     78 |
| [`sort-button`](../../../frontend/src/components/ui/sort-button.tsx)                                 |                      1 |
| [`spinner`](../../../frontend/src/components/ui/spinner.tsx)                                         |                     24 |
| [`swipe-to-decide`](../../../frontend/src/components/ui/swipe-to-decide.tsx)                         |                      2 |
| [`switch`](../../../frontend/src/components/ui/switch.tsx)                                           |                     74 |
| [`tabs`](../../../frontend/src/components/ui/tabs.tsx)                                               |                     27 |
| [`text-peek`](../../../frontend/src/components/ui/text-peek.tsx)                                     |                      5 |
| [`textarea`](../../../frontend/src/components/ui/textarea.tsx)                                       |                     68 |
| [`thinking-orb`](../../../frontend/src/components/ui/thinking-orb.tsx)                               |                      4 |
| [`tooltip`](../../../frontend/src/components/ui/tooltip.tsx)                                         |                     14 |
| [`voice-glow`](../../../frontend/src/components/ui/voice-glow.tsx)                                   |                      2 |
| [`wizard-steps`](../../../frontend/src/components/ui/wizard-steps.tsx)                               |                      6 |
| [`workspace-fullscreen-button`](../../../frontend/src/components/ui/workspace-fullscreen-button.tsx) |                     11 |

## Component directories

Every directory belongs to a migration wave; helper modules remain unchanged unless their presentation contract changes. Counts include nested source modules.

| Directory or root file  | Source modules |
| ----------------------- | -------------: |
| `chat`                  |            149 |
| `workflows`             |            147 |
| `agents`                |            112 |
| `dashboard`             |            104 |
| `ui`                    |             69 |
| `datasets`              |             66 |
| `tables`                |             47 |
| `onboarding`            |             45 |
| `evals`                 |             40 |
| `triggers`              |             37 |
| `improvement`           |             36 |
| `layout`                |             34 |
| `skills`                |             34 |
| `settings`              |             33 |
| `artifacts`             |             29 |
| `desktop`               |             28 |
| `runs`                  |             26 |
| `authoring`             |             25 |
| `sandboxes`             |             21 |
| `skill-improvement`     |             21 |
| `rag`                   |             20 |
| `orgs`                  |             17 |
| `teams`                 |             17 |
| `projects`              |             16 |
| `knowledge-gaps`        |             15 |
| `kb`                    |             15 |
| `admin`                 |             15 |
| `memory`                |             13 |
| `channels`              |             13 |
| `voice`                 |             12 |
| `sharing`               |             11 |
| `files`                 |             11 |
| `mcp`                   |             10 |
| `mobile`                |             10 |
| `assistant`             |              9 |
| `auth`                  |              9 |
| `vault`                 |              9 |
| `states`                |              8 |
| `icons`                 |              7 |
| `groups`                |              6 |
| `theme`                 |              6 |
| `phone`                 |              6 |
| `legal`                 |              6 |
| `branding`              |              5 |
| `context`               |              5 |
| `watches`               |              4 |
| `inbox`                 |              3 |
| `illustrations`         |              3 |
| `tasks`                 |              2 |
| `remote-agents`         |              2 |
| `charts`                |              2 |
| `browser`               |              2 |
| `live-updates`          |              2 |
| `language-switcher.tsx` |              1 |
| `public-config`         |              1 |
| `oauth`                 |              1 |
| `hosted`                |              1 |
| `shared`                |              1 |

## Native JSX candidates

| Tag        | Files | Occurrences |
| ---------- | ----: | ----------: |
| `button`   |   255 |         414 |
| `input`    |    43 |          48 |
| `select`   |     2 |           3 |
| `textarea` |     5 |           5 |
| `details`  |    53 |          66 |

## Route checklist

These are routes to check after the component migration, not a claim that each screen has already been visually reviewed. Authentication, public/hosted and development routes have distinct interaction constraints. No browser automation or screenshots were used for this inventory.

- [ ] `[locale]/(auth)/forgot-password/page.tsx`
- [ ] `[locale]/(auth)/login/page.tsx`
- [ ] `[locale]/(auth)/magic-link-sent/page.tsx`
- [ ] `[locale]/(auth)/register/page.tsx`
- [ ] `[locale]/(auth)/reset-password/page.tsx`
- [ ] `[locale]/(dashboard)/admin/background-jobs/page.tsx`
- [ ] `[locale]/(dashboard)/admin/organizations/[id]/page.tsx`
- [ ] `[locale]/(dashboard)/admin/organizations/page.tsx`
- [ ] `[locale]/(dashboard)/admin/page.tsx`
- [ ] `[locale]/(dashboard)/admin/settings/page.tsx`
- [ ] `[locale]/(dashboard)/admin/system/page.tsx`
- [ ] `[locale]/(dashboard)/admin/users/page.tsx`
- [ ] `[locale]/(dashboard)/agents/[id]/evals/[runId]/page.tsx`
- [ ] `[locale]/(dashboard)/agents/[id]/improve/[session]/page.tsx`
- [ ] `[locale]/(dashboard)/agents/[id]/page.tsx`
- [ ] `[locale]/(dashboard)/agents/page.tsx`
- [ ] `[locale]/(dashboard)/apps/page.tsx`
- [ ] `[locale]/(dashboard)/browse/[runId]/[callId]/page.tsx`
- [ ] `[locale]/(dashboard)/channels/page.tsx`
- [ ] `[locale]/(dashboard)/chat/page.tsx`
- [ ] `[locale]/(dashboard)/context/page.tsx`
- [ ] `[locale]/(dashboard)/dashboard/page.tsx`
- [ ] `[locale]/(dashboard)/datasets/[id]/page.tsx`
- [ ] `[locale]/(dashboard)/datasets/page.tsx`
- [ ] `[locale]/(dashboard)/dev/components/page.tsx`
- [ ] `[locale]/(dashboard)/documents/[id]/page.tsx`
- [ ] `[locale]/(dashboard)/documents/page.tsx`
- [ ] `[locale]/(dashboard)/evals/page.tsx`
- [ ] `[locale]/(dashboard)/groups/[id]/page.tsx`
- [ ] `[locale]/(dashboard)/groups/page.tsx`
- [ ] `[locale]/(dashboard)/inbox/page.tsx`
- [ ] `[locale]/(dashboard)/invitations/[token]/page.tsx`
- [ ] `[locale]/(dashboard)/invitations/pending/page.tsx`
- [ ] `[locale]/(dashboard)/kb/[id]/page.tsx`
- [ ] `[locale]/(dashboard)/kb/page.tsx`
- [ ] `[locale]/(dashboard)/link/[token]/page.tsx`
- [ ] `[locale]/(dashboard)/mcp-servers/page.tsx`
- [ ] `[locale]/(dashboard)/orgs/[id]/directory/page.tsx`
- [ ] `[locale]/(dashboard)/orgs/[id]/groups/page.tsx`
- [ ] `[locale]/(dashboard)/orgs/[id]/members/page.tsx`
- [ ] `[locale]/(dashboard)/orgs/[id]/retention/page.tsx`
- [ ] `[locale]/(dashboard)/orgs/[id]/roles/page.tsx`
- [ ] `[locale]/(dashboard)/orgs/page.tsx`
- [ ] `[locale]/(dashboard)/profile/page.tsx`
- [ ] `[locale]/(dashboard)/projects/[id]/page.tsx`
- [ ] `[locale]/(dashboard)/projects/page.tsx`
- [ ] `[locale]/(dashboard)/rag/[id]/page.tsx`
- [ ] `[locale]/(dashboard)/rag/page.tsx`
- [ ] `[locale]/(dashboard)/remote-agents/page.tsx`
- [ ] `[locale]/(dashboard)/routines/page.tsx`
- [ ] `[locale]/(dashboard)/runs/page.tsx`
- [ ] `[locale]/(dashboard)/sandboxes/page.tsx`
- [ ] `[locale]/(dashboard)/settings/account/page.tsx`
- [ ] `[locale]/(dashboard)/settings/api-keys/page.tsx`
- [ ] `[locale]/(dashboard)/settings/api-keys/reference/page.tsx`
- [ ] `[locale]/(dashboard)/settings/assistant/page.tsx`
- [ ] `[locale]/(dashboard)/settings/blobby/page.tsx`
- [ ] `[locale]/(dashboard)/settings/desktop/page.tsx`
- [ ] `[locale]/(dashboard)/settings/mcp/page.tsx`
- [ ] `[locale]/(dashboard)/settings/memory/page.tsx`
- [ ] `[locale]/(dashboard)/settings/mobile/page.tsx`
- [ ] `[locale]/(dashboard)/settings/notifications/page.tsx`
- [ ] `[locale]/(dashboard)/settings/page.tsx`
- [ ] `[locale]/(dashboard)/settings/profile/page.tsx`
- [ ] `[locale]/(dashboard)/settings/shortcuts/page.tsx`
- [ ] `[locale]/(dashboard)/settings/sign-ins/page.tsx`
- [ ] `[locale]/(dashboard)/settings/slash-commands/page.tsx`
- [ ] `[locale]/(dashboard)/skills/[id]/improve/[session]/page.tsx`
- [ ] `[locale]/(dashboard)/skills/[id]/page.tsx`
- [ ] `[locale]/(dashboard)/skills/page.tsx`
- [ ] `[locale]/(dashboard)/tables/[id]/page.tsx`
- [ ] `[locale]/(dashboard)/tables/page.tsx`
- [ ] `[locale]/(dashboard)/vault/page.tsx`
- [ ] `[locale]/(dashboard)/work/page.tsx`
- [ ] `[locale]/(dashboard)/workflows/[id]/form-preview/page.tsx`
- [ ] `[locale]/(dashboard)/workflows/[id]/logs/page.tsx`
- [ ] `[locale]/(dashboard)/workflows/[id]/page.tsx`
- [ ] `[locale]/(dashboard)/workflows/[id]/runs/[runId]/page.tsx`
- [ ] `[locale]/(dashboard)/workflows/[id]/runs/page.tsx`
- [ ] `[locale]/(dashboard)/workflows/page.tsx`
- [ ] `[locale]/(dashboard)/workflows/runs/page.tsx`
- [ ] `[locale]/(viewer)/apps/[id]/page.tsx`
- [ ] `[locale]/(viewer)/oauth/consent/page.tsx`
- [ ] `[locale]/a/[publicKey]/page.tsx`
- [ ] `[locale]/auth/callback/page.tsx`
- [ ] `[locale]/auth/email-change/page.tsx`
- [ ] `[locale]/auth/magic-link/page.tsx`
- [ ] `[locale]/auth/pair/page.tsx`
- [ ] `[locale]/desktop/blobby/page.tsx`
- [ ] `[locale]/desktop/quick-ask/page.tsx`
- [ ] `[locale]/desktop/readiness/page.tsx`
- [ ] `[locale]/desktop/welcome/page.tsx`
- [ ] `[locale]/e/[publicKey]/page.tsx`
- [ ] `[locale]/f/[token]/page.tsx`
- [ ] `[locale]/legal/cookies/page.tsx`
- [ ] `[locale]/legal/privacy/page.tsx`
- [ ] `[locale]/legal/terms/page.tsx`
- [ ] `[locale]/onboarding/[...step]/page.tsx`
- [ ] `[locale]/onboarding/page.tsx`
- [ ] `[locale]/page.tsx`
- [ ] `[locale]/shared/[token]/page.tsx`
