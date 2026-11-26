# Chat panels and controls audit

Date: 2026-11-21. Scope: the console chat and its composed controls. This is a
source and targeted-test audit. It does **not** certify visual inspection of every
component, browser/provider operation, or every application page. Browser proof
is recorded separately by the parent task.

## Implemented interaction contract

- Files, Sources and Browser share the dock frame, explicit expansion and close.
  Browser retains 35–65% keyboard/pointer bounds and a 55% starting width.
  Files and Sources start at a preferred 400px, resize from 360px to 420px and are capped
  at 38% of the docked chat. On constrained desktop layouts, opening Files or Sources
  temporarily folds the conversation list; closing restores the previous choice,
  while a manual expansion overrides folding for that panel session.
  A narrow main console uses a full-screen panel; an embedded conversation keeps
  its panel inside that conversation. The two layout container names are explicit
  because metadata panels are siblings of the browser container.
- Shared metadata headers contain a normal-weight title, contextual actions,
  expansion and close in that order. They retain the owner label of shared files.
- Escape closes the current metadata panel, except when a nested dialog/menu
  owns the event. Closing returns focus without scrolling only when it was still
  in that panel, or was removed with it. A reader who moved elsewhere keeps focus.
- Metadata panels no longer animate transcript width on opening. This avoids
  continuous text reflow while the surface opens. Resizing remains deliberate.
- Approval mode is 23rem wide and uses compact explanatory rows. Chat controls
  is 25rem wide with a compact header, stable tabs and a bounded scrolling body.
  Existing organization ceilings and permission checks remain in place.
- The usage/context popover has an explicit title and bounded scroll area.
  The project picker distinguishes an empty usable collection, an empty search
  and a failed read with retry. Its management link names the actual destination.
- Slash and mention navigation scroll their own lists rather than invoking
  scrollIntoView on ancestors. Browser tab focus also uses preventScroll.
- Browser comment capture failures show an error while retaining the note for
  retry. Enter during IME composition does not submit that note or forward an
  Enter to a held remote screen. This does not add a full remote IME input method.
- Plans stay collapsed by default. Historical plan rows do not replay entry
  effects, and settled check transitions are immediate. Blocked state uses the
  semantic warning text color rather than a fixed amber shade.

## Source review decisions

| Surface                         | Result / reason                                                                                                                                                                                                    |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| File preview and cited original | Keep the shared FileViewer dialog. A document preview is a reading workbench, while the file/source rail is navigation. Combining both into a tiny rail would reduce usable reading width.                         |
| Browser and computer screen     | Keep takeover/ownership controls and the live viewport contract. A common surrounding dock does not remove explicit control or native-desktop restrictions. Real browser/computer takeover was not exercised here. |
| Browser tabs/navigation         | Keep named buttons, URL validation, bounded tab-strip scrolling, and separate active ownership. Added preventScroll focus; invalid URL feedback remains explicit.                                                  |
| Remote screen typing            | Preserve permission checks. IME Enter is now ignored during composition; full remote composition input needs a dedicated editable input contract and remains outside this polish.                                  |
| Delegation sheet                | Keep its accessible modal sheet and per-delegate identity rather than treating a separate conversation as a file list. Needs visual review with simultaneous delegates.                                            |
| Workflow run card               | Keep name, current status, pending questions, error, and actual workflow-run detail link. It is a meaningful in-conversation result, not a duplicate diagnostic preview.                                           |
| Outcomes                        | Keep explicit failed-read retry and concrete actions. Context URLs are server-produced; no claim was made that arbitrary URLs were manually opened.                                                                |
| Plan strip/checklist            | Compact collapsed progress is appropriate; hidden details remain reachable. Settled rows no longer replay animations.                                                                                              |
| Account/model/local access      | Keep explicit consent and existing permission boundaries. Dialogs already describe concrete access rather than silently changing agent capabilities.                                                               |
| Composer plus menu              | Already compact and on demand; changed only focus to prevent ancestor scrolling.                                                                                                                                   |
| Visual/chart/app cards          | Meaningful user outputs may remain between messages. The parent task owns eliminating their duplicate visual rendering inside raw tool diagnostics.                                                                |

## Complete component inventory

Review levels are intentionally distinct: **changed + tested** describes this
subtask; **source reviewed** means the main source contract was read and retained;
**coordinated with parent** means another owner is changing it. Remaining rows
record the source interaction contract inspected and the reason it was retained.
This review covers state, actions, disclosures and links; it does not certify
every provider payload or native runtime.
No visual approval is implied by any row.

| Component                                                                                                     | Kind            | Review level                                                                                                                                          |
| ------------------------------------------------------------------------------------------------------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| [agent-draft-proposal.tsx](../../frontend/src/components/chat/agent-draft-proposal.tsx)                       | view/control    | Draft approval names destination organization and capabilities; long instructions fold without hiding the decision.                                   |
| [agent-picker.tsx](../../frontend/src/components/chat/agent-picker.tsx)                                       | view/control    | Published/setup-runnable options, explicit default and workflow permission gate retained; own bounded list and keyboard navigation.                   |
| [agent-step.module.css](../../frontend/src/components/chat/agent-step.module.css)                             | style           | Rail is decorative, token-colored and pointer-inert; no independent layout animation.                                                                 |
| [agent-step.tsx](../../frontend/src/components/chat/agent-step.tsx)                                           | view/control    | Disclosure exposes aria-expanded/controls, keeps parked/error status and reduced-motion running indicator.                                            |
| [attachment-card.tsx](../../frontend/src/components/chat/attachment-card.tsx)                                 | view/control    | Shared compact FileCard, render-safe image types and named removal action retained.                                                                   |
| [attachment-row.tsx](../../frontend/src/components/chat/attachment-row.tsx)                                   | view/control    | Bounded horizontal tray with overflow arrows, count announcement and cleaned ResizeObserver.                                                          |
| [background-tasks.tsx](../../frontend/src/components/chat/background-tasks.tsx)                               | view/control    | Bounded list links encoded conversation ids; Stop only for active tasks and disabled during stop.                                                     |
| [browser-card.tsx](../../frontend/src/components/chat/browser-card.tsx)                                       | view/control    | Live preview releases its socket when expanded; compact history visits and once-per-session auto-open retained.                                       |
| [browser-comment.tsx](../../frontend/src/components/chat/browser-comment.tsx)                                 | view/control    | Changed + targeted tests                                                                                                                              |
| [browser-navigation.tsx](../../frontend/src/components/chat/browser-navigation.tsx)                           | view/control    | Source reviewed; retained contract                                                                                                                    |
| [browser-panel-frame.tsx](../../frontend/src/components/chat/browser-panel-frame.tsx)                         | view/control    | Changed + targeted tests                                                                                                                              |
| [browser-panel.tsx](../../frontend/src/components/chat/browser-panel.tsx)                                     | view/control    | Source reviewed; retained contract                                                                                                                    |
| [browser-speech-failure.ts](../../frontend/src/components/chat/browser-speech-failure.ts)                     | contract/helper | Recognition errors map to actionable states; deliberate cancellation stays silent.                                                                    |
| [browser-tabs.tsx](../../frontend/src/components/chat/browser-tabs.tsx)                                       | view/control    | Changed + targeted tests                                                                                                                              |
| [browser-view.tsx](../../frontend/src/components/chat/browser-view.tsx)                                       | view/control    | Operation labels and live/latest emphasis retained; unknown operations use a generic icon.                                                            |
| [browser-visit.tsx](../../frontend/src/components/chat/browser-visit.tsx)                                     | view/control    | Compact card distinguishes panel reopen from external visit; link isolation retained.                                                                 |
| [browser-window.tsx](../../frontend/src/components/chat/browser-window.tsx)                                   | view/control    | Source reviewed; retained contract                                                                                                                    |
| [chart-message.impl.tsx](../../frontend/src/components/chat/chart-message.impl.tsx)                           | view/control    | Memoized responsive chart reserves 300px and shares semantic axis/grid tokens; legend and axis labels remain separate.                                |
| [chart-message.tsx](../../frontend/src/components/chat/chart-message.tsx)                                     | view/control    | Chart payload parsing and deferred implementation retained; duplicate diagnostic rendering handled by parent.                                         |
| [chat-approval-selector.tsx](../../frontend/src/components/chat/chat-approval-selector.tsx)                   | view/control    | Changed + targeted tests                                                                                                                              |
| [chat-composer-menu.tsx](../../frontend/src/components/chat/chat-composer-menu.tsx)                           | view/control    | Changed + targeted tests                                                                                                                              |
| [chat-container.tsx](../../frontend/src/components/chat/chat-container.tsx)                                   | view/control    | Coordinated with parent                                                                                                                               |
| [chat-controls.tsx](../../frontend/src/components/chat/chat-controls.tsx)                                     | view/control    | Changed + targeted tests                                                                                                                              |
| [chat-empty-state.tsx](../../frontend/src/components/chat/chat-empty-state.tsx)                               | view/control    | Coordinated with parent                                                                                                                               |
| [chat-home-inbox.tsx](../../frontend/src/components/chat/chat-home-inbox.tsx)                                 | view/control    | Coordinated with parent                                                                                                                               |
| [chat-input.tsx](../../frontend/src/components/chat/chat-input.tsx)                                           | view/control    | Parent source reviewed/changed: composer layout, smooth welcome suggestions and viewport stability.                                                   |
| [chat-layout.css](../../frontend/src/components/chat/chat-layout.css)                                         | style           | Parent source reviewed/changed: composer layout, smooth welcome suggestions and viewport stability.                                                   |
| [chat-layout.tsx](../../frontend/src/components/chat/chat-layout.tsx)                                         | view/control    | Parent source reviewed/changed: composer layout, smooth welcome suggestions and viewport stability.                                                   |
| [chat-model-library.tsx](../../frontend/src/components/chat/chat-model-library.tsx)                           | view/control    | Provider-first navigation, searchable bounded catalog and saved/key tabs retained; optional credential setup stays contextual.                        |
| [chat-model-picker.tsx](../../frontend/src/components/chat/chat-model-picker.tsx)                             | view/control    | Read-only model summary survives manage denial; creating/reusing profiles checks keys, availability and shows failed-read Retry.                      |
| [chat-room-bar.tsx](../../frontend/src/components/chat/chat-room-bar.tsx)                                     | view/control    | Presence is omitted when alone, capped at four faces and sharing remains owner-gated.                                                                 |
| [chat-side-panel.tsx](../../frontend/src/components/chat/chat-side-panel.tsx)                                 | view/control    | Changed + targeted tests                                                                                                                              |
| [chat-welcome.tsx](../../frontend/src/components/chat/chat-welcome.tsx)                                       | view/control    | Parent source reviewed/changed: composer layout, smooth welcome suggestions and viewport stability.                                                   |
| [collapsible-block.tsx](../../frontend/src/components/chat/collapsible-block.tsx)                             | view/control    | Explicit starting open state respects user toggles between streaming frames; Copy remains reachable.                                                  |
| [compaction-notice.tsx](../../frontend/src/components/chat/compaction-notice.tsx)                             | view/control    | Transient status stays outside persisted transcript; impossible overhead explains the unavailable operation.                                          |
| [composer-action.css](../../frontend/src/components/chat/composer-action.css)                                 | style           | Opacity/transform transitions preserve geometry and both system/application reduced-motion disable them.                                              |
| [composer-editor.tsx](../../frontend/src/components/chat/composer-editor.tsx)                                 | view/control    | Coordinated with parent                                                                                                                               |
| [composer-hints.tsx](../../frontend/src/components/chat/composer-hints.tsx)                                   | view/control    | Coordinated with parent                                                                                                                               |
| [composer-sheet.tsx](../../frontend/src/components/chat/composer-sheet.tsx)                                   | view/control    | Source reviewed; retained contract                                                                                                                    |
| [composer-status.tsx](../../frontend/src/components/chat/composer-status.tsx)                                 | view/control    | Connection status is screen-reader-only to avoid duplicating composer reconnect feedback.                                                             |
| [connect-account-prompt.tsx](../../frontend/src/components/chat/connect-account-prompt.tsx)                   | view/control    | Source reviewed; retained contract                                                                                                                    |
| [connect-services-card.tsx](../../frontend/src/components/chat/connect-services-card.tsx)                     | view/control    | Source reviewed; retained contract                                                                                                                    |
| [conversation-access-notice.tsx](../../frontend/src/components/chat/conversation-access-notice.tsx)           | view/control    | Checking, failed and view-only states are distinct; only failed reads offer Retry.                                                                    |
| [conversation-filters.tsx](../../frontend/src/components/chat/conversation-filters.tsx)                       | view/control    | Sort/archive/API and agent filters remain on demand with labelled controls and active-filter indicator.                                               |
| [conversation-search-dialog.tsx](../../frontend/src/components/chat/conversation-search-dialog.tsx)           | view/control    | Debounced server search has Retry, empty/searching states and keyboard command list; closes after selection.                                          |
| [conversation-sidebar.tsx](../../frontend/src/components/chat/conversation-sidebar.tsx)                       | view/control    | Coordinated with parent                                                                                                                               |
| [copy-button.tsx](../../frontend/src/components/chat/copy-button.tsx)                                         | view/control    | Shared clipboard hook reports completion; title and accessible name track copied state.                                                               |
| [delegate-face.tsx](../../frontend/src/components/chat/delegate-face.tsx)                                     | view/control    | Native harness and platform-agent identities remain distinct; decorative avatar does not own actions.                                                 |
| [delegation-chat.tsx](../../frontend/src/components/chat/delegation-chat.tsx)                                 | view/control    | Compact exchange previews open the shared delegation sheet; nesting is capped rather than indefinitely indenting.                                     |
| [delegation-panel.tsx](../../frontend/src/components/chat/delegation-panel.tsx)                               | view/control    | Source reviewed; retained contract                                                                                                                    |
| [delegation-sheet.tsx](../../frontend/src/components/chat/delegation-sheet.tsx)                               | view/control    | Source reviewed; retained contract                                                                                                                    |
| [dictation-bar.tsx](../../frontend/src/components/chat/dictation-bar.tsx)                                     | view/control    | Stop/Cancel stay accessible through transcription; reduced-motion waveform and timer announcement contracts retained.                                 |
| [dictation-strip.tsx](../../frontend/src/components/chat/dictation-strip.tsx)                                 | view/control    | One bounded hint region separates alerts from polite announcements; actionable microphone/transcription states retained.                              |
| [draft-card.tsx](../../frontend/src/components/chat/draft-card.tsx)                                           | view/control    | Source reviewed; retained contract                                                                                                                    |
| [draft-segment.tsx](../../frontend/src/components/chat/draft-segment.tsx)                                     | view/control    | Source/preview toggle and copy remain explicit; placeholder highlighting does not interpret draft source as HTML.                                     |
| [file-preview-dialog.tsx](../../frontend/src/components/chat/file-preview-dialog.tsx)                         | view/control    | Source reviewed; retained contract                                                                                                                    |
| [forked-from.tsx](../../frontend/src/components/chat/forked-from.tsx)                                         | view/control    | Named origin opens the actual source conversation via caller-owned navigation.                                                                        |
| [index.ts](../../frontend/src/components/chat/index.ts)                                                       | contract/helper | Exports only; no additional UI or state contract.                                                                                                     |
| [interrupted-notice.tsx](../../frontend/src/components/chat/interrupted-notice.tsx)                           | view/control    | Lost/interrupted/detached states keep explicit recheck or ask-again actions rather than fabricating completion.                                       |
| [kept-image.tsx](../../frontend/src/components/chat/kept-image.tsx)                                           | view/control    | Offline blob fallback is attempted once and blob URLs are revoked on cleanup; primary file URL retained.                                              |
| [link-favicon.tsx](../../frontend/src/components/chat/link-favicon.tsx)                                       | view/control    | Only HTTP(S) origins request lazy local favicon proxy; failures fall back to Globe.                                                                   |
| [live-viewport.tsx](../../frontend/src/components/chat/live-viewport.tsx)                                     | view/control    | Changed + targeted tests                                                                                                                              |
| [local-access-dialog.tsx](../../frontend/src/components/chat/local-access-dialog.tsx)                         | view/control    | Source reviewed; retained contract                                                                                                                    |
| [local-agent-chip.tsx](../../frontend/src/components/chat/local-agent-chip.tsx)                               | view/control    | Desktop-only status distinguishes missing folder/full access from readiness and names the effective harness.                                          |
| [local-coding-control.tsx](../../frontend/src/components/chat/local-coding-control.tsx)                       | view/control    | Native link/folder selection precedes store changes; pending disables selection and actual desktop settings link retained.                            |
| [local-coding-settings.tsx](../../frontend/src/components/chat/local-coding-settings.tsx)                     | view/control    | Model/effort preserve unavailable saved choices and failed local settings have explicit Refresh.                                                      |
| [local-skills-control.tsx](../../frontend/src/components/chat/local-skills-control.tsx)                       | view/control    | Optional native disclosure preserves source ordering/shadow counts; linking must succeed before enabling sources.                                     |
| [main-chat-context.ts](../../frontend/src/components/chat/main-chat-context.ts)                               | contract/helper | Embedded scope overrides main-chat context; no additional visual state.                                                                               |
| [markdown-content.impl.tsx](../../frontend/src/components/chat/markdown-content.impl.tsx)                     | view/control    | Stable memoized renderer prevents streamed remounts; citations, inert review images, table/quote and external link contracts retained.                |
| [markdown-content.tsx](../../frontend/src/components/chat/markdown-content.tsx)                               | view/control    | Deferred renderer keeps readable plain-text fallback while loading.                                                                                   |
| [markdown-quote.tsx](../../frontend/src/components/chat/markdown-quote.tsx)                                   | view/control    | Copy exports whole quote text/HTML with a named control, separate from quote content.                                                                 |
| [markdown-table.tsx](../../frontend/src/components/chat/markdown-table.tsx)                                   | view/control    | Horizontal overflow stays within table and named Copy exports text/HTML.                                                                              |
| [mention-chip.tsx](../../frontend/src/components/chat/mention-chip.tsx)                                       | view/control    | Typed entity marks and plain-text rich segments retained; external link chips isolate new tabs.                                                       |
| [mention-palette.tsx](../../frontend/src/components/chat/mention-palette.tsx)                                 | view/control    | Changed + targeted tests                                                                                                                              |
| [message-cost.tsx](../../frontend/src/components/chat/message-cost.tsx)                                       | view/control    | Rounded compact costs preserve exact/cache/partial details on demand.                                                                                 |
| [message-item.tsx](../../frontend/src/components/chat/message-item.tsx)                                       | view/control    | Coordinated with parent                                                                                                                               |
| [message-list.tsx](../../frontend/src/components/chat/message-list.tsx)                                       | view/control    | Coordinated with parent                                                                                                                               |
| [message-sources.tsx](../../frontend/src/components/chat/message-sources.tsx)                                 | view/control    | Deduplicated document count and capped varied marks open the common Sources panel.                                                                    |
| [model-provider-credential.tsx](../../frontend/src/components/chat/model-provider-credential.tsx)             | view/control    | Provider-specific inline or structured secret flow retained; structured creation requires secret edit.                                                |
| [model-setup-card.module.css](../../frontend/src/components/chat/model-setup-card.module.css)                 | style           | Setup illustration retains deliberate accent; content and notices use console tokens with narrow container rules.                                     |
| [model-setup-card.tsx](../../frontend/src/components/chat/model-setup-card.tsx)                               | view/control    | Source reviewed; retained contract                                                                                                                    |
| [model-setup-reply.tsx](../../frontend/src/components/chat/model-setup-reply.tsx)                             | view/control    | Reduced motion shows full text immediately; setup CTA appears after its explanatory reply.                                                            |
| [native-browser.tsx](../../frontend/src/components/chat/native-browser.tsx)                                   | view/control    | Source reviewed; retained contract                                                                                                                    |
| [next-steps.tsx](../../frontend/src/components/chat/next-steps.tsx)                                           | view/control    | Source reviewed; retained contract                                                                                                                    |
| [outcome-cards.tsx](../../frontend/src/components/chat/outcome-cards.tsx)                                     | view/control    | Source reviewed; retained contract                                                                                                                    |
| [pending-messages.tsx](../../frontend/src/components/chat/pending-messages.tsx)                               | view/control    | Coordinated with parent                                                                                                                               |
| [person-face.tsx](../../frontend/src/components/chat/person-face.tsx)                                         | view/control    | Shared EntityAvatar controls fallback and decorative identity semantics.                                                                              |
| [personal-model-connection.tsx](../../frontend/src/components/chat/personal-model-connection.tsx)             | view/control    | Changed + regression test: failed status read now has Retry; private password form and pinned destination retained.                                   |
| [phone-chat-bar.tsx](../../frontend/src/components/chat/phone-chat-bar.tsx)                                   | view/control    | Named touch-sized actions open menu/history/new chat; unread mark remains decorative.                                                                 |
| [plan-checklist.tsx](../../frontend/src/components/chat/plan-checklist.tsx)                                   | view/control    | Changed + targeted tests                                                                                                                              |
| [plan-strip.tsx](../../frontend/src/components/chat/plan-strip.tsx)                                           | view/control    | Changed + targeted tests                                                                                                                              |
| [project-chip.tsx](../../frontend/src/components/chat/project-chip.tsx)                                       | view/control    | Source reviewed; retained contract                                                                                                                    |
| [question-interaction.ts](../../frontend/src/components/chat/question-interaction.ts)                         | contract/helper | Coordinated with parent                                                                                                                               |
| [question-turn-card.tsx](../../frontend/src/components/chat/question-turn-card.tsx)                           | view/control    | Coordinated with parent                                                                                                                               |
| [rating-buttons.tsx](../../frontend/src/components/chat/rating-buttons.tsx)                                   | view/control    | Pending disables duplicate votes; dislike feedback and optional dataset action stay on demand; failure preserves draft.                               |
| [remembered-approvals.tsx](../../frontend/src/components/chat/remembered-approvals.tsx)                       | view/control    | Failed read has Retry; revoke is pending-guarded and preserves failure feedback.                                                                      |
| [reply-quote.tsx](../../frontend/src/components/chat/reply-quote.tsx)                                         | view/control    | Explicit user jump uses reduced-motion-aware scroll; composing quote exposes named cancel.                                                            |
| [sandbox-preparing-notice.tsx](../../frontend/src/components/chat/sandbox-preparing-notice.tsx)               | view/control    | Live status distinguishes computer preparation from cloud sandbox without persisting a fake message.                                                  |
| [setup-proposals.tsx](../../frontend/src/components/chat/setup-proposals.tsx)                                 | view/control    | Source reviewed; retained contract                                                                                                                    |
| [share-dialog.tsx](../../frontend/src/components/chat/share-dialog.tsx)                                       | view/control    | Source reviewed; retained contract                                                                                                                    |
| [shared-visuals.tsx](../../frontend/src/components/chat/shared-visuals.tsx)                                   | view/control    | Shared drawing records adapt into the same TurnVisuals renderer rather than a separate viewer.                                                        |
| [skill-shortcut.tsx](../../frontend/src/components/chat/skill-shortcut.tsx)                                   | view/control    | Only ready/usable assistant and skill editors see contextual draft creation; answer payload is bounded.                                               |
| [slash-command-palette.tsx](../../frontend/src/components/chat/slash-command-palette.tsx)                     | view/control    | Changed + targeted tests                                                                                                                              |
| [slash-commands.ts](../../frontend/src/components/chat/slash-commands.ts)                                     | contract/helper | Enabled custom/builtin commands preserve aliases and prefix-first search; send/client actions remain distinct.                                        |
| [source-mark.tsx](../../frontend/src/components/chat/source-mark.tsx)                                         | view/control    | Decorative source identity reuses file/favicon fallback and shared background/border tokens.                                                          |
| [sources-panel.tsx](../../frontend/src/components/chat/sources-panel.tsx)                                     | view/control    | Changed + targeted tests                                                                                                                              |
| [suggestion-actions.tsx](../../frontend/src/components/chat/suggestion-actions.tsx)                           | view/control    | Failed actions surface toast; routine suggestions are accepted only after creation succeeds.                                                          |
| [suggestion-cards.tsx](../../frontend/src/components/chat/suggestion-cards.tsx)                               | view/control    | Only the highest-priority suggestion is primary; remaining count links to Inbox and dismiss remains named.                                            |
| [tool-approval-dialog.tsx](../../frontend/src/components/chat/tool-approval-dialog.tsx)                       | view/control    | Permission and always-asks hidden-content rules remain authoritative; details fold and remember choices stay explicit.                                |
| [tool-call-card.tsx](../../frontend/src/components/chat/tool-call-card.tsx)                                   | view/control    | Coordinated with parent                                                                                                                               |
| [tool-group.tsx](../../frontend/src/components/chat/tool-group.tsx)                                           | view/control    | Grouped activity is collapsed by native disclosure and exposes pending approval/answer/error status.                                                  |
| [tool-results/artifact.tsx](../../frontend/src/components/chat/tool-results/artifact.tsx)                     | result renderer | Version-pinned app links retain conversation return path and new-tab isolation.                                                                       |
| [tool-results/asked.tsx](../../frontend/src/components/chat/tool-results/asked.tsx)                           | result renderer | Coordinated with parent                                                                                                                               |
| [tool-results/catalogs.tsx](../../frontend/src/components/chat/tool-results/catalogs.tsx)                     | result renderer | Compact named context/skill entries have explicit empty states; diagnostic rendering is parent-owned.                                                 |
| [tool-results/coding-agent.tsx](../../frontend/src/components/chat/tool-results/coding-agent.tsx)             | result renderer | Answer is primary and trace initially folded; recorded change/file origin retained. Owned report fields validated; legacy kind-less reports retained. |
| [tool-results/coding-changes.tsx](../../frontend/src/components/chat/tool-results/coding-changes.tsx)         | result renderer | Capped patches disclose omitted/binary data and keep copy/revert controls.                                                                            |
| [tool-results/coding-task-revert.tsx](../../frontend/src/components/chat/tool-results/coding-task-revert.tsx) | result renderer | Recorded conversation origin gates undo; conflict/unknown/pending outcomes stay explicit in confirmation.                                             |
| `tool-results/delegation.tsx` (removed)                                                                       | result renderer | Removed unused legacy renderer after raw diagnostics replaced its only rendering path; turn-level delegation outputs remain separate.                 |
| [tool-results/desktop-screenshot.tsx](../../frontend/src/components/chat/tool-results/desktop-screenshot.tsx) | result renderer | Parent reviewed/changed media-surface parser; missing stored file is explicit.                                                                        |
| [tool-results/generated-image.tsx](../../frontend/src/components/chat/tool-results/generated-image.tsx)       | result renderer | Parent reviewed/changed media-surface parser; missing stored image is explicit.                                                                       |
| [tool-results/generated-speech.tsx](../../frontend/src/components/chat/tool-results/generated-speech.tsx)     | result renderer | Parent reviewed/changed media-surface parser; native controls and missing audio state retained.                                                       |
| [tool-results/generated-video.tsx](../../frontend/src/components/chat/tool-results/generated-video.tsx)       | result renderer | Parent reviewed/changed media-surface parser; native controls and missing video state retained.                                                       |
| [tool-results/generic.tsx](../../frontend/src/components/chat/tool-results/generic.tsx)                       | result renderer | Arguments and result remain copyable plain diagnostics, without duplicate interactive visualization.                                                  |
| [tool-results/memory.tsx](../../frontend/src/components/chat/tool-results/memory.tsx)                         | result renderer | Manage points to actual memory settings; unknown results fall back to generic text.                                                                   |
| [tool-results/plan.tsx](../../frontend/src/components/chat/tool-results/plan.tsx)                             | result renderer | Shared checklist handles recognized data; waiting/failure fallback stays explicit.                                                                    |
| [tool-results/platform-objects.tsx](../../frontend/src/components/chat/tool-results/platform-objects.tsx)     | result renderer | Only completed supported writes create actual-resource links; errors excluded and references deduplicated.                                            |
| [tool-results/rag.tsx](../../frontend/src/components/chat/tool-results/rag.tsx)                               | result renderer | Chunks group by source with clamped previews and one expanded passage; no-result state explicit.                                                      |
| [tool-results/routine.tsx](../../frontend/src/components/chat/tool-results/routine.tsx)                       | result renderer | Validated references re-read current routine; loading/error/Retry/unavailable states distinct.                                                        |
| [tool-results/run-python.tsx](../../frontend/src/components/chat/tool-results/run-python.tsx)                 | result renderer | Code/output use copyable collapsible blocks; execution failure stays visible.                                                                         |
| [tool-results/skills.tsx](../../frontend/src/components/chat/tool-results/skills.tsx)                         | result renderer | Refused or malformed skill loads keep readable failure instead of disappearing.                                                                       |
| [tool-results/table-call-answer.tsx](../../frontend/src/components/chat/tool-results/table-call-answer.tsx)   | result renderer | Result previews cap ten rows and disclose more; columns reflect query intent.                                                                         |
| [tool-results/table-call-data.ts](../../frontend/src/components/chat/tool-results/table-call-data.ts)         | result renderer | Cell previews cap 280 characters and table reads require session media surface.                                                                       |
| [tool-results/table-call-query.tsx](../../frontend/src/components/chat/tool-results/table-call-query.tsx)     | result renderer | Translated query operators and schema labels retained; unknown identifiers remain visible.                                                            |
| [tool-results/table-call.tsx](../../frontend/src/components/chat/tool-results/table-call.tsx)                 | result renderer | Actual table link and schema labels retained; failed/unrecognized output falls back to generic text.                                                  |
| [tool-results/watch.tsx](../../frontend/src/components/chat/tool-results/watch.tsx)                           | result renderer | Completed validated write references deduplicate into watch cards.                                                                                    |
| [tool-results/web-search.tsx](../../frontend/src/components/chat/tool-results/web-search.tsx)                 | result renderer | Compact external hits clamp snippets; no-result state explicit and detailed scores optional.                                                          |
| [tool-results/workspace.tsx](../../frontend/src/components/chat/tool-results/workspace.tsx)                   | result renderer | Shared FileViewer/access preserves recorded origin; listing preview capped at 50 rows.                                                                |
| [turn-action.ts](../../frontend/src/components/chat/turn-action.ts)                                           | contract/helper | Shared quiet action sizing retained; labels belong to each consuming action.                                                                          |
| [turn-delegations.tsx](../../frontend/src/components/chat/turn-delegations.tsx)                               | view/control    | One team byline opens common exchange sheet; background task status and coding harness identity remain distinct.                                      |
| [turn-extras.tsx](../../frontend/src/components/chat/turn-extras.tsx)                                         | view/control    | Settled turns expose concise project/memory links; capability writes preserve server grant refusal and request-owner fallback.                        |
| [turn-files.tsx](../../frontend/src/components/chat/turn-files.tsx)                                           | view/control    | Settled output chips deduplicate paths, refuse outside-root local paths and open shared FileViewer.                                                   |
| [turn-parts.tsx](../../frontend/src/components/chat/turn-parts.tsx)                                           | view/control    | Coordinated with parent                                                                                                                               |
| [turn-rail.tsx](../../frontend/src/components/chat/turn-rail.tsx)                                             | view/control    | Long-transcript-only navigation observes message ids and disconnects cleanly; scrolling occurs only on explicit user navigation.                      |
| [turn-shortcuts.tsx](../../frontend/src/components/chat/turn-shortcuts.tsx)                                   | view/control    | Routine/agent creation actions require matching permissions and usable assistant.                                                                     |
| [typing-indicator.tsx](../../frontend/src/components/chat/typing-indicator.tsx)                               | view/control    | Polite presence announcement caps visible faces; decorative animation does not duplicate names.                                                       |
| [usage-meter.tsx](../../frontend/src/components/chat/usage-meter.tsx)                                         | view/control    | Changed + targeted tests                                                                                                                              |
| [viewport-visual-frame.tsx](../../frontend/src/components/chat/viewport-visual-frame.tsx)                     | view/control    | Offscreen settled visuals reserve measured height; Intersection/Resize observers clean up.                                                            |
| [visual-actions.ts](../../frontend/src/components/chat/visual-actions.ts)                                     | contract/helper | Downloads seal HTML/CSP and strip active/external SVG content; image conversion revokes blob URL on success/failure.                                  |
| [visual-frame.tsx](../../frontend/src/components/chat/visual-frame.tsx)                                       | view/control    | Own-frame messages only, bounded size growth and stall cleanup retained; loading reserves declared height.                                            |
| [visual-panel.tsx](../../frontend/src/components/chat/visual-panel.tsx)                                       | view/control    | Source reviewed; retained contract                                                                                                                    |
| [visual-save-dialog.tsx](../../frontend/src/components/chat/visual-save-dialog.tsx)                           | view/control    | Changed + regression test: pending save locks fields/dismissal and guards duplicate submissions; field errors remain local.                           |
| [visual-zoom.tsx](../../frontend/src/components/chat/visual-zoom.tsx)                                         | view/control    | Named zoom/reset controls enforce fixed steps and disable endpoint actions.                                                                           |
| [work-fold.tsx](../../frontend/src/components/chat/work-fold.tsx)                                             | view/control    | Coordinated with parent                                                                                                                               |
| [work-on.tsx](../../frontend/src/components/chat/work-on.tsx)                                                 | view/control    | Desktop-only native consent flow precedes target changes; folder/whole-computer controls retain explicit access modes.                                |
| [workflow-run-card.tsx](../../frontend/src/components/chat/workflow-run-card.tsx)                             | view/control    | Source reviewed; retained contract                                                                                                                    |
| [workspace-files.tsx](../../frontend/src/components/chat/workspace-files.tsx)                                 | view/control    | Changed + targeted tests                                                                                                                              |
| [you-face.tsx](../../frontend/src/components/chat/you-face.tsx)                                               | view/control    | Shared EntityAvatar uses current authenticated user and cache-busted avatar version.                                                                  |
| [your-connections.tsx](../../frontend/src/components/chat/your-connections.tsx)                               | view/control    | Published spec determines personal accounts; OAuth return preserves chat and missing catalog points to actual MCP page.                               |

Additional inspected dependencies: `components/projects/project-picker-dialog.tsx`
(changed and tested), `components/files/file-viewer.tsx` and
`components/kb/source-viewer.tsx` (nested-dialog boundary inspected).

## Verification and remaining work

The scoped coverage batch passed 332 tests across 16 files: 100% lines, statements
and functions across the 13 explicitly selected modules (97.7% branches). Later
Files recovery/header checks passed 76 tests across four files. The final stale
file/source selection and run/MCP picker regression batch passed 120 tests across
four files. These batches are scoped evidence, not a full frontend coverage gate.
Final integration and browser results are reported by the parent task.

Browser checks outside this source-audit evidence: light/dark metadata panels; narrow and wide chat;
resizer keyboard/pointer; nested file preview Escape; focus after close; approval
and Chat controls geometry; project picker empty/search/error states; history
versus live plans; native desktop/browser takeover where the runtime is available.
A complete console-wide visual pass remains tracked by the parent task.

## File recovery and responsive follow-up

Files now present a short human failure message, explicit Retry and the complete
technical cause behind a closed native disclosure. The actual `/sandboxes` setup
link is shown only for cloud files and connection managers. Expand is hidden when
a narrow/contained panel already fills its conversation; Close stays available.
Navigating between conversations resets the file selection before commit. Closing
Sources clears its nested original-document selection, so reopening never revives
a stale source preview. Regression tests cover both transitions.

## Follow-up interaction review

The remaining chat inventory was inspected by interaction boundary: menus, forms,
status regions, copy/export helpers, media frames, native access controls and
settled-turn summaries. Initial private model connection failures now have Retry.
Visual publishing locks the draft and dismissal during its write and refuses
duplicate form submission while pending (18 targeted tests across both files).

The coding-agent report boundary now validates owned fields with the existing Zod
dependency: malformed steps, filenames, harness and answer fall back to raw text.
Legacy reports without kind remain supported; nullable backend metadata normalizes
to absent, so a null change-set id does not initiate a resource read. Native
microphone, filesystem consent and remote browser control still require their
actual runtime for visual verification.

## Sources layout and embedded chat follow-up

Files and Sources now use a preferred width of 400px, adjustable from 360px to 420px and
capped at 38% of a docked conversation. Browser retains its wider content-oriented profile. On a constrained desktop chat row, Sources temporarily
folds the conversation list; closing the panel restores the prior explicit choice.
Expanding the list manually overrides that automatic folding for the current
panel session. Resize observation responds to available chat width, without
writing an automatic change into saved user preferences. Highlighted citations
scroll their own Sources list instead of calling ancestor-scrolling
`scrollIntoView`. Scoped tests cover preferred width, pointer and keyboard resize,
container resize, restoration, explicit overrides and ancestor-scroll refusal.
Browser verification of reading-position stability belongs to the parent pass.

| Surface                             | Source and interaction review                                                                                                                       | Change or retained contract                                                                                                                                                                                                                                                 | Verification                                                                                |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Architect assistant window          | Shared ChatContainer, history, screenshot attachment, new conversation, tips and close                                                              | Header controls use 44px targets with visible keyboard focus; all actions retained. Its shared composer and turn pipeline already inherit console changes.                                                                                                                  | Assistant widget scoped suite; no child browser pass                                        |
| Agent builder test chat             | Shared ChatContainer under testing context; pinned greeting, starter questions, agent/conversation reset and externally requested prompts           | Retained: shared composer and turn rendering preserve feature parity without exposing a separate conflicting control layout.                                                                                                                                                | Source interaction review; existing shared tests                                            |
| Hosted public page `/e/[publicKey]` | Separate admitted public socket, attachments, reconnect, browser/server dictation, public voice and shared TurnParts                                | Multiline composer with bounded height and separate controls row. Enter sends; Shift+Enter adds a line; IME confirmation does not send. Public transport and admission remain unchanged.                                                                                    | Hosted suite, including keyboard/IME regressions                                            |
| Public channel widget `WIDGET_JS`   | Scoped stylesheet, safe Markdown DOM, caller-side token, limited public frame vocabulary, sources gate, dictation, voice, Escape and reduced motion | Multiline textarea grows within 160px, then scrolls internally. Plain Enter submits; Shift+Enter and IME keep composing. Rejected/disconnected sends retain the draft. Widget remains its own restricted public renderer; it does not promise private console tool history. | Widget Python suite, real Node syntax/keyboard-handler execution, security-marker inventory |

These are source and automated interaction checks. They do not establish visual
approval in both themes, native microphone availability or a live public-channel
end-to-end result; those require the parent browser/CI pass.

## Public reading position and composer recovery

Hosted and widget transcript following now pauses while a reader is above the
bottom. Streaming deltas and content resize respect that state. Returning to the
bottom or explicitly submitting a new message resumes following; reconnect and
history replay do not force the reader away. Hosted tests deliver real public
frames and exercise both scroll and ResizeObserver callbacks. The widget tests
execute its actual scroll, pin and submit handlers in Node.

The home Inbox preview has one actionable row per item, without dates or a second
chat icon. It places an editable question into the composer through the existing
incoming-message contract; it does not submit that question. Open inbox remains a
separate link. Scoped hover treatment respects reduced motion.

The rich composer serializes canonical message text for copy and cut, preserving
URL and mention chips through a plain-text round trip. Paste and cut replace the
selected range rather than inserting only at its end. Conversation rename uses a
visible Title label, selects the current title and disables an unchanged save.

## Sharing modal consistency

The artifact share dialog is the reference shell: `DIALOG_FORM` with
`DIALOG_SCROLL`, a named header and vertically ordered access sections. The chat
share dialog now uses the same quiet section structure rather than an extra large
nested general-access card. Its controls and the shared resource-sharing controls
use 40px heights, with 44px targets on coarse-pointer devices. Link fields and copy
buttons follow that same scale. Selecting a recipient or access level is disabled
while the current share is saving; targeted tests preserve that pending-state
contract.

| Entry point                      | Composition checked                                                                      | Decision                                                                                               |
| -------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Chat ShareDialog                 | Member picker, view/edit grants, view-only public token, grant changes, revoke and retry | Updated layout and control scale; public-token permission remains view-only.                           |
| ArtifactShareDialog              | Page URL, public link, requests, data consent, embed settings and common SharingPanel    | Reference shell retained; common control polish applies without changing consent or public link rules. |
| DatasetShareDialog               | Named header, description, common SharingPanel                                           | Existing reference-size scrollable shell retained; common controls apply.                              |
| ShareResourceButton              | Project, skill, Context and knowledge-base sharing                                       | Existing common shell retained; common controls apply.                                                 |
| Agent/table sharing dialogs      | Existing named dialog shells and common SharingPanel                                     | Existing reference-size scrollable shells retained; common controls apply.                             |
| Vault and MCP connection sharing | Common SharingPanel inside their existing management dialogs                             | Common controls apply; existing management permissions remain authoritative.                           |

The scoped chat/common-sharing batch passed 106 tests across four files, including
pending recipient/access selection, read-only grants, levels, public links and
consent paths. This is automated/source evidence; visual parity with the reference
in light/dark themes remains part of the parent browser pass.

## Shared surfaces recovery review

A failed shared-resource access read previously stayed on the loading skeleton
because the hook discarded its query error. `useSharing` now exposes error/refetch;
SharingPanel presents the actual refusal and Retry. A network/service refresh
failure keeps cached access rows visible alongside its warning; authentication,
permission and not-found refusals hide cached grants and editing controls. This applies to every resource-sharing
entry point listed above, without treating a 403 as an empty access list.

The command palette now reports unavailable entity reads with a generic localized
notice and retries only the failed, currently permitted queries. Backend exception
text is not copied into that notice. Agent and knowledge-base names are also gated
at rendering time: disabling a query alone did not hide previously cached names
after permission withdrawal. Regression tests cover successful recovery without
refetching healthy scopes and removal of cached names after a permission change.

The file viewer attachment strip now reveals the selected item by changing only
its own horizontal scroll position. Tests cover overflow on either edge, an
already-visible item, retained button focus and absence of ancestor
`scrollIntoView` calls. Reduced motion selects immediate scrolling.

Additional retained boundaries: Quick Ask already tracks an explicit reader pause
and resets it on the visitor's own send; it was not replaced with public-chat
following. The notification bell already distinguishes a failed read from an empty
inbox and refreshes when reopened. No native desktop or live-notification runtime
claim follows from these source checks.

## Phone composer layout

At phone widths, the main console composer now has two stable control rows:
attach, current agent, Files, settings, approval and usage on the first; model and
Send/Stop on the second. Every control retains a 44px target. The model spans five
of the six columns instead of sharing the narrow remainder after three icons;
its former 5rem trigger and 2.75rem label caps were removed. At the narrowest
supported layout the agent may show its avatar/chevron summary, while its full
accessible current-agent label remains available. The model keeps substantially
more room for its actual name.

The grid occupies at least 264px and uses the same placement while the field is
focused, blurred or processing. These overrides are limited to the main-chat
phone stylesheet; desktop layout and embedded/public composers are unchanged.
The phone/input unit batch passed 72 tests. Actual 390px geometry and theme proof
remain the parent browser check, rather than a claim derived from jsdom layout.

## Inbox and table-board follow-up

Inbox rows, the dashboard briefing, chat home preview and suggestion cards now use
one `SuggestionPriority` warning badge with the same localized Urgent label. Source
marks share a neutral muted surface; detailed and dense rows keep their intentional
differences in size and metadata. Long titles can wrap beside attention/status
badges, and action targets grow to 44px for coarse-pointer devices. Chat preview
rows still compose an editable question rather than sending it.

Kanban lanes stretch across the board's available height; their content areas can
grow even when they contain only an empty placeholder. The pointer drag preview
now renders the real title and the same visible-property renderer as a card,
including select chips. It uses the source card's measured width/minimum height
and original pointer grab offset. It is inert and has no duplicate interactive
controls or motion layout id. Hidden columns stay absent, and Escape cancels the
preview without writing. The focused Inbox/briefing/chat/Kanban batch passed 115
tests across seven files, including pointer geometry, fields, hidden-column
exclusion, empty-lane structure and consistent attention styling. Pixel height
verification remains the parent browser pass.

## Maintenance notice data freshness

DeploymentGate now passes the current authenticated maintenance message into
MaintenanceScreen instead of showing the initial branding-context text forever.
An unanswered poll preserves the initial public fallback; an explicit null message
clears the previous custom text and uses the localized default. Anonymous visitors
retain the public branding fallback, including when authenticated notice data was
already cached. Existing notice styles and administrator bypass remain intact.
The branding integration batch passed 22 tests, including actual query refetches
that change and clear the message without reopening the tab.
