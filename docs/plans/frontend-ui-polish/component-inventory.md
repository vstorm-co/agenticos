# Frontend component inventory

Baseline snapshot before migration: 2026-11-19, branch `codex/chat-inbox-ui-polish`. See [the migration plan](component-system-plan.md).

## Method and limits

Current migration evidence is in [component-migration-review.md](component-migration-review.md). ChoiceGroup and NativeDisclosure now live in `ui/`; baseline counts below are retained for comparison.

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

Checked boxes now record source integration review, not a claim that each screen has been visually reviewed. Runtime samples are recorded separately in the migration review. Authentication, public/hosted and development routes have distinct interaction constraints. No browser automation or screenshots were used for this inventory.

- [x] `[locale]/(auth)/forgot-password/page.tsx`
- [x] `[locale]/(auth)/login/page.tsx`
- [x] `[locale]/(auth)/magic-link-sent/page.tsx`
- [x] `[locale]/(auth)/register/page.tsx`
- [x] `[locale]/(auth)/reset-password/page.tsx`
- [x] `[locale]/(dashboard)/admin/background-jobs/page.tsx`
- [x] `[locale]/(dashboard)/admin/organizations/[id]/page.tsx`
- [x] `[locale]/(dashboard)/admin/organizations/page.tsx`
- [x] `[locale]/(dashboard)/admin/page.tsx`
- [x] `[locale]/(dashboard)/admin/settings/page.tsx`
- [x] `[locale]/(dashboard)/admin/system/page.tsx`
- [x] `[locale]/(dashboard)/admin/users/page.tsx`
- [x] `[locale]/(dashboard)/agents/[id]/evals/[runId]/page.tsx`
- [x] `[locale]/(dashboard)/agents/[id]/improve/[session]/page.tsx`
- [x] `[locale]/(dashboard)/agents/[id]/page.tsx`
- [x] `[locale]/(dashboard)/agents/page.tsx`
- [x] `[locale]/(dashboard)/apps/page.tsx`
- [x] `[locale]/(dashboard)/browse/[runId]/[callId]/page.tsx`
- [x] `[locale]/(dashboard)/channels/page.tsx`
- [x] `[locale]/(dashboard)/chat/page.tsx`
- [x] `[locale]/(dashboard)/context/page.tsx`
- [x] `[locale]/(dashboard)/dashboard/page.tsx`
- [x] `[locale]/(dashboard)/datasets/[id]/page.tsx`
- [x] `[locale]/(dashboard)/datasets/page.tsx`
- [x] `[locale]/(dashboard)/dev/components/page.tsx`
- [x] `[locale]/(dashboard)/documents/[id]/page.tsx`
- [x] `[locale]/(dashboard)/documents/page.tsx`
- [x] `[locale]/(dashboard)/evals/page.tsx`
- [x] `[locale]/(dashboard)/groups/[id]/page.tsx`
- [x] `[locale]/(dashboard)/groups/page.tsx`
- [x] `[locale]/(dashboard)/inbox/page.tsx`
- [x] `[locale]/(dashboard)/invitations/[token]/page.tsx`
- [x] `[locale]/(dashboard)/invitations/pending/page.tsx`
- [x] `[locale]/(dashboard)/kb/[id]/page.tsx`
- [x] `[locale]/(dashboard)/kb/page.tsx`
- [x] `[locale]/(dashboard)/link/[token]/page.tsx`
- [x] `[locale]/(dashboard)/mcp-servers/page.tsx`
- [x] `[locale]/(dashboard)/orgs/[id]/directory/page.tsx`
- [x] `[locale]/(dashboard)/orgs/[id]/groups/page.tsx`
- [x] `[locale]/(dashboard)/orgs/[id]/members/page.tsx`
- [x] `[locale]/(dashboard)/orgs/[id]/retention/page.tsx`
- [x] `[locale]/(dashboard)/orgs/[id]/roles/page.tsx`
- [x] `[locale]/(dashboard)/orgs/page.tsx`
- [x] `[locale]/(dashboard)/profile/page.tsx`
- [x] `[locale]/(dashboard)/projects/[id]/page.tsx`
- [x] `[locale]/(dashboard)/projects/page.tsx`
- [x] `[locale]/(dashboard)/rag/[id]/page.tsx`
- [x] `[locale]/(dashboard)/rag/page.tsx`
- [x] `[locale]/(dashboard)/remote-agents/page.tsx`
- [x] `[locale]/(dashboard)/routines/page.tsx`
- [x] `[locale]/(dashboard)/runs/page.tsx`
- [x] `[locale]/(dashboard)/sandboxes/page.tsx`
- [x] `[locale]/(dashboard)/settings/account/page.tsx`
- [x] `[locale]/(dashboard)/settings/api-keys/page.tsx`
- [x] `[locale]/(dashboard)/settings/api-keys/reference/page.tsx`
- [x] `[locale]/(dashboard)/settings/assistant/page.tsx`
- [x] `[locale]/(dashboard)/settings/blobby/page.tsx`
- [x] `[locale]/(dashboard)/settings/desktop/page.tsx`
- [x] `[locale]/(dashboard)/settings/mcp/page.tsx`
- [x] `[locale]/(dashboard)/settings/memory/page.tsx`
- [x] `[locale]/(dashboard)/settings/mobile/page.tsx`
- [x] `[locale]/(dashboard)/settings/notifications/page.tsx`
- [x] `[locale]/(dashboard)/settings/page.tsx`
- [x] `[locale]/(dashboard)/settings/profile/page.tsx`
- [x] `[locale]/(dashboard)/settings/shortcuts/page.tsx`
- [x] `[locale]/(dashboard)/settings/sign-ins/page.tsx`
- [x] `[locale]/(dashboard)/settings/slash-commands/page.tsx`
- [x] `[locale]/(dashboard)/skills/[id]/improve/[session]/page.tsx`
- [x] `[locale]/(dashboard)/skills/[id]/page.tsx`
- [x] `[locale]/(dashboard)/skills/page.tsx`
- [x] `[locale]/(dashboard)/tables/[id]/page.tsx`
- [x] `[locale]/(dashboard)/tables/page.tsx`
- [x] `[locale]/(dashboard)/vault/page.tsx`
- [x] `[locale]/(dashboard)/work/page.tsx`
- [x] `[locale]/(dashboard)/workflows/[id]/form-preview/page.tsx`
- [x] `[locale]/(dashboard)/workflows/[id]/logs/page.tsx`
- [x] `[locale]/(dashboard)/workflows/[id]/page.tsx`
- [x] `[locale]/(dashboard)/workflows/[id]/runs/[runId]/page.tsx`
- [x] `[locale]/(dashboard)/workflows/[id]/runs/page.tsx`
- [x] `[locale]/(dashboard)/workflows/page.tsx`
- [x] `[locale]/(dashboard)/workflows/runs/page.tsx`
- [x] `[locale]/(viewer)/apps/[id]/page.tsx`
- [x] `[locale]/(viewer)/oauth/consent/page.tsx`
- [x] `[locale]/a/[publicKey]/page.tsx`
- [x] `[locale]/auth/callback/page.tsx`
- [x] `[locale]/auth/email-change/page.tsx`
- [x] `[locale]/auth/magic-link/page.tsx`
- [x] `[locale]/auth/pair/page.tsx`
- [x] `[locale]/desktop/blobby/page.tsx`
- [x] `[locale]/desktop/quick-ask/page.tsx`
- [x] `[locale]/desktop/readiness/page.tsx`
- [x] `[locale]/desktop/welcome/page.tsx`
- [x] `[locale]/e/[publicKey]/page.tsx`
- [x] `[locale]/f/[token]/page.tsx`
- [x] `[locale]/legal/cookies/page.tsx`
- [x] `[locale]/legal/privacy/page.tsx`
- [x] `[locale]/legal/terms/page.tsx`
- [x] `[locale]/onboarding/[...step]/page.tsx`
- [x] `[locale]/onboarding/page.tsx`
- [x] `[locale]/page.tsx`
- [x] `[locale]/shared/[token]/page.tsx`
