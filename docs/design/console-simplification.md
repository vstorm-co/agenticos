# Console simplification

Working design contract, 2026-11-21. This is an implementation record, not a
claim that every console route has been redesigned.

## Outcome

Make the next action obvious without reducing the platform's capabilities.
Start with shared foundations and chat, then the agent builder, authentication
and onboarding, and finally the remaining screen families.

## Evidence and reference boundaries

The review used the supplied mobile assistant and OpenBot screenshots, the
logged-in Mistral Vibe and Studio interfaces in both themes, and the public
OpenBot and Orca source. Existing local data was cloned for testing: 31 agents,
442 conversations, 71 skills, five workflows and four model profiles. The
original databases are not the preview's write target.

References inform composition and interaction. Their fonts, illustrations,
copy and product-specific behavior are not assets to import into AgenticOS.

| Reference                      | Observed pattern                                                                                                   | Application here                                                                                  |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| Mistral Vibe, light and dark   | Empty composer keeps a stable shortcut hint on focus; suggestions disappear on input                               | Keep `/` and `@` guidance until actual input; remove rotating examples                            |
| Mistral Studio, API keys       | One page title and primary action; table skeleton becomes an explicit empty state; plan restrictions have a reason | Distinguish loading, empty, unavailable and forbidden states; explain blocked actions             |
| Mistral Studio, managed agents | Small preview badge; focused empty state with one primary action and secondary documentation                       | Avoid repeating explanatory introductions and competing creation actions                          |
| Mistral Studio, OCR            | One upload target, constraints beside it, optional examples, restrained color                                      | Group related choices and use progressive disclosure instead of simultaneous panels               |
| OpenBot                        | Compact navigation rail and conversation list; identity color separated from neutral chrome                        | Preserve conversation identity and make context panels optional, without losing navigation labels |
| Orca bot settings              | Grouped rows show current values before opening a detail page                                                      | Let builder summaries explain the saved configuration; preserve deep links and unsaved edits      |
| Supplied mobile assistant      | Whitespace, one dominant action, short text, color for identity                                                    | Reduce decoration and repeated copy; retain large touch targets and readable composer text        |

Mistral Studio's desktop sidebar measures about 260 CSS pixels, with 14px
regular labels and 32px rows. Its dark main surface is approximately `#17171b`.
Vibe's light canvas is approximately `#f8f8f4`, with white composer and dark
`#201f1c` text. These are observations at the inspected viewport, not pixel
specifications to copy. AgenticOS retains its own vendored Inter and tokens.

Source references:

- [Mistral Vibe](https://chat.mistral.ai/work)
- [Mistral Studio](https://console.mistral.ai/home)
- [OpenBot source](https://github.com/nightly-labs/openbot), especially brand
  tokens and conversation components
- [Orca source](https://github.com/stablyai/orca), especially `BotSettingsRows`
  and bot settings sections

## Shared foundations

- Neutral canvas, sidebar, card and floating surface have distinct roles.
  Dark mode needs actual depth; a uniform medium gray loses this hierarchy.
- Primary actions keep strong neutral contrast. Blue identifies links,
  selection and keyboard focus; green identifies enabled switches and success;
  amber signals attention; red identifies destructive actions and errors.
- Color supplements labels, icons and control state. It never supplies the
  only explanation, including for users with color-vision differences.
- Body and navigation use Inter. Most navigation labels use regular weight;
  active destinations use medium weight. Page and section headings have a
  consistent hierarchy rather than making every label bold.
- Keep existing Lucide icons, provider marks and colored entity avatars. Avoid
  adding decorative icons beside every sentence or replacing recognition with
  an unlabeled icon-only interface.
- Preserve system/light/dark preference, section-pinned themes and custom looks.
  Verify OS-selected and explicitly selected dark palettes stay equivalent.
- Normal text must reach 4.5:1, large text and meaningful graphics 3:1. Check
  actual rendered control, hover and focus colors, not only token definitions.
- Keep keyboard navigation, translated text, zoom, reduced motion, empty states
  and errors part of the screen review. Dense desktop rows must grow with text;
  coarse pointers retain larger hit targets.

## Findings in the running console

### Data availability before visual evaluation

The preview initially showed no organizations or agents despite a populated
backend. An authenticated HTTP probe with `Accept-Encoding: gzip` needed two
successive decompressions to produce JSON, while the response advertised one.
The API proxy compressed a decoded body and Next.js compressed it again.
Removing compression from the route handler fixes the transport; the HTTP
server remains responsible for compression. A fresh probe must yield valid JSON
after one decoding. Never redesign this failure as a legitimate empty state.

A first cold builder read also loaded Python dependencies long enough to trip
the local event-loop watchdog. The preview uses a 60-second threshold while
investigating; the production default is unchanged. This needs separate backend
investigation, rather than a frontend fallback that hides the failure.

### Chat

- Global navigation and conversation history consume two substantial columns.
  Keep both discoverable, but let history be contextual and collapsible.
- Rotating composer examples compete with typing and disappear merely on focus.
  Replace them with stable shortcut guidance, retaining the textbox's accessible
  name independently of the hint.
- Suggested prompts belong below the composer and should disappear on input,
  including externally inserted drafts. Clearing restores them; blur does not. Their reserved layout space remains,
  so neither transition moves the composer.
- A populated daily briefing can push the composer and starter prompts below
  the fold. Keep the briefing useful, but subordinate it to starting a chat. The compact
  preview now shows two entries and links to the full Inbox.
- Preserve agent/model choice, attachments, permissions and conversation context.
  A clean composer must not remove these functions or bury them unpredictably.
- Test mention and slash menus, IME confirmation, paste, dictation, attachments,
  mobile Enter, disabled/offline states and pending approvals.

### Agent builder

The inspected local agent is AgenticOS Preview. Its build screen contains a
long instructions editor, variables, model configuration, voice and first
messages. The broader builder also exposes tools, MCP, limits, availability,
evaluations, knowledge gaps and version history.

- Instructions and testing remain immediately usable.
- Show current model, credential mode and meaningful enabled state before users
  expand configuration. Use human-readable model names; keep identifiers for
  search and diagnostics.
- Group related advanced options; avoid a series of indistinguishable cards
  that require opening each to learn what is configured.
- Retain read-only access, permission-gated writes, draft autosave, published
  version boundaries, direct links and error focus. Collapsing a section must
  not discard an editor's state.
- Keep metadata under Details. Do not add another permanent navigation column
  to an already dense builder.
- At narrow widths, make every tab discoverable; do not silently clip history
  and other trailing destinations.

### Authentication and onboarding

The sign-in screen combines a large display headline, repeated greeting and
supporting presentation. Simplify the form's hierarchy and retain credential
labels, password-manager support, errors and enterprise sign-in paths.

The first authenticated visit opens a substantial What's new dialog. Deployment
upgrade instructions are important for administrators, but should be separated
from the short product summary through explicit disclosure. Onboarding should
lead to the person's first useful task without competing with release notes.

## Verification recorded so far

In the populated desktop preview, the composer's top coordinate was identical
before typing, while suggestions were hidden, and after clearing. Hidden prompts
retain their layout space and fade over the shared panel duration. They are inert; they are unavailable to keyboard and
assistive-technology navigation. Initial desktop focus prevents automatic scroll.

Default-theme contrast calculations for the actual token values:

| Pair                         | Light   | Dark    |
| ---------------------------- | ------- | ------- |
| Main text / canvas           | 14.93:1 | 15.44:1 |
| Secondary text / card        | 6.03:1  | 7.55:1  |
| Blue link / canvas           | 6.37:1  | 6.69:1  |
| Focus ring / card            | 3.66:1  | 4.44:1  |
| Enabled switch / card        | 4.08:1  | 7.37:1  |
| Switch thumb / enabled track | 3.91:1  | 8.81:1  |

These establish the default palette's listed pairs, not every contextual alpha
composition or custom look. The browser viewport override did not change the
actual 1280×720 viewport, so mobile visual verification remains pending; existing
phone E2E coverage now also checks that typing does not move the composer.

## Delivery checklist

- [x] Connect the isolated preview to populated local data.
- [x] Compare Mistral's composer behavior and Studio surfaces in both themes.
- [x] Inspect OpenBot and Orca layout source and record the synthesis.
- [x] Reproduce and fix double API compression; verify through the HTTP server.
- [x] Verify shared tokens and primitives in both themes.
- [x] Verify real desktop chat interactions and replay in both themes.
- [ ] Complete responsive chat and resource geometry checks in final-head CI.
- [x] Complete builder summaries and progressive configuration disclosure.
- [x] Simplify authentication, onboarding and first-session interruptions.
- [x] Apply shared patterns to resource lists, details and settings; audit every route.
- [ ] Finish accessibility checks and final-commit CI before merge/release.

## Live conversation and replay audit (2026-11-21)

Tested the maintainer's local conversation `c1412941-f1c3-48cd-a04b-cda772282f21`
in the embedded Codex browser. Submitted a clearly marked fictional UI test,
completed a two-question batch (list, short), and reloaded the saved conversation.
A requested profile write was rejected; the test did not approve a resource or
routine creation. These measurements are desktop observations, not mobile proof.

### Measured layout changes

| Transition                       | Dock height | Transcript scrollTop | Composer editor top |
| -------------------------------- | ----------- | -------------------- | ------------------- |
| Existing single question visible | 425.75 px   | 233 px               | 588 px              |
| That question submitted          | 144 px      | 93.5 px              | 588 px              |
| New two-question test sent       | 144 px      | 589.5 px             | 588 px              |
| Question 1 appeared              | 366.75 px   | 763 px               | 588 px              |
| Question 2 appeared              | 366.75 px   | 763 px               | 588 px              |
| Answer review appeared           | 338 px      | 734 px               | 588 px              |
| Answers submitted                | 144 px      | 624 px               | 588 px              |

The composer itself stayed put in this run. The visible transcript moved: the
absolute dock contains the question card, its ResizeObserver rewrites transcript
bottom padding, and a layout effect pins the scroller to its bottom. Content
following independently writes scrollTop when the transcript resizes. Sent-turn
anchoring adds another viewport policy, while QuestionSlide calls focus without
preventScroll. Focus is a contributing risk in the code, not independently isolated
as the cause of every measured movement.

### Current data paths

- `use-chat.ts` consumes streamed `part_start`, `tool_call`, `tool_result`,
  `ask_user`, parked questions, continuation markers and completion events.
- Main-agent parked questions are restored by run ID, answered through
  `answer_run`, and correlated to tool-call IDs. Delegate questions also have a
  live callback path; those protocols must retain their distinct ownership.
- `chat-store.ts` retains both the timeline `parts` and the `toolCalls` collection.
  Their update helpers must keep IDs, terminal states and results aligned.
- Persisted `Message.parts` records order and references `tool_calls`; replay joins
  them by tool-call ID in `conversation-to-chat.ts`. Older messages have a fallback.
- `TurnParts` splits work around visible prose; each work group can own a WorkFold.
  WorkFold defaults to open while live, so long-running tool output grows the page.
  Finished history collapses it. The same turn changes geometry on settlement.
- Two completed calls in the inspected conversation asked the same Week question
  with different tool-call IDs. This is real repeated agent work, not evidence
  that the renderer received one call twice. Do not deduplicate by question text.
- Replay retained both test questions and the selected answers correctly. Reading
  them required opening the work group and then its tool row.

### Proposed interaction contract

| State                 | Default presentation                                                        | Viewport behavior                                                 |
| --------------------- | --------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| Running               | One compact progress row, latest action and action count; details collapsed | Follow only when the reader is already following                  |
| Waiting for an answer | One actionable question card in transcript flow                             | Keep the composer and the reader's visible anchor stable          |
| Submitting answers    | Keep the same card with disabled controls and submitting status             | Do not remove the card before acknowledgement                     |
| Answer acknowledged   | Convert that card into a concise question/answer receipt                    | Preserve identity and place; expand details on request            |
| Waiting for approval  | Separate decision card identifying the concrete effect                      | Required decisions remain visible regardless of work disclosure   |
| Finished / reopened   | Answer and meaningful outputs first; work collapsed                         | No replay animations, fake spinners or forced focus               |
| Failed submission     | Keep answers, show the failure and a retry action                           | No blank state or automatic resubmission after unknown acceptance |

Recommended implementation order:

1. Move actionable questions out of the variable-height absolute composer dock.
   Use one card component for waiting, submitting and answered states, and clamp
   its internal content on short screens. Preserve keyboard navigation and a
   visible route to pending decisions while reading earlier messages.
2. Give one hook ownership of viewport policy: following, reading history, and
   anchoring an explicitly sent message. Preserve the visible message anchor on
   layout changes; use preventScroll for intentional focus. Animate opacity of
   local surfaces rather than the height of the entire transcript.
3. Default routine tool details to collapsed in live and replay views. Surface the
   latest action without auto-expanding each step. Keep errors, decisions and
   actual outputs reachable outside routine diagnostic details.
4. Build a typed turn projection shared by live events and persisted replay.
   Normalize boundaries to run ID, message ID and tool-call ID; preserve existing
   correlation, tenant checks and cancellation. Extract transitions from the large
   hook incrementally rather than replacing the transport in one rewrite.
5. Add deterministic event-trace tests for parallel questions, delayed results,
   repeated frames, resume acknowledgement, disconnect after submission, history
   reload and older timelines. Distinct calls survive even when their text matches.
   Browser tests should assert a visible message's position through question
   appearance, review and acknowledgement, including a reader scrolled upward.

The interaction contract is now implemented in the same PR. `turn-timeline.ts`
projects both streamed and persisted parts, preserving distinct invocation IDs and
monotonic terminal states. `use-chat-viewport.ts` owns following, sent-turn anchors,
reading anchors and explicit question reveal. Inline questions retain their controls
until the correlated server acknowledgement, then become compact answer receipts.
Diagnostic disclosures render raw arguments and results; produced charts, files,
media and coding change reports appear once in the conversation.

The deterministic tests cover repeated/late frames, concurrent questions, interrupted
answer submission, IME entry, persisted timelines and layout-clamp/focus scrolling.
The browser trace in dark mode retained card top 95.375px, composer top 567px and
scrollTop 2528.5 through both question steps, review, submission and acknowledgement.
A subsequent light-mode trace retained card top 95.125px through both questions, review, submission and the 139px answer receipt. The theme class was checked before the test; reloading retained the receipt and collapsed work.
A four-case Playwright regression covers light/dark at 1280px and 390px with real
persisted messages and a controlled model socket; its CI result is still pending.

Additional workstreams have their own source-review ledgers:
[chat panels](console-chat-panels-audit.md),
[resources and route inventory](console-route-audit.md), and
[settings and onboarding](console-settings-audit.md).

The maintainer selected **Workspace — projects** as the default conversation-list layout. Missing or unknown `sidebar` values use that layout; `compact` and `comfortable` remain explicit comparison options.

## Follow-up review from the maintainer's populated account

The next pass covers issues observed on 2026-11-21 after the initial delivery.
Completion means source review, implementation and scoped checks, not merely listing the route. Checked items below do not claim final-head browser or CI verification.

- [x] Insert Inbox suggestions as editable composer text; remove dates and redundant chat actions.
- [x] Recheck Build section grouping, card height and spacing without changing the other agent tabs.
- [x] Align workflow runs/logs and template libraries; keep one run-start confirmation and quiet field hover.
- [x] Review Projects, Knowledge, Tables and Dataset cards; neutralize Dataset decoration and stabilize its settings footer.
- [x] Fill primary table views and retain visible pagination, including one-page results; preserve server/cursor boundaries.
- [x] Recheck the mobile composer, URL-chip clipboard, Files panel, rename and sharing dialogs.
- [x] Resolve app-viewer help counts before the first caption and keep help in the persistent viewer header.
- [x] Remove workspace-card shortcuts and static settings-section entry animations.
- [x] Cover imperative navigation with the shared progress bar and animate tab selection using measured geometry.
- [x] Fill and center the quiet Group dashboard, then review the remaining route/component inventory.
- [ ] Verify the final head in both themes, responsive journeys and CI; do not equate an earlier run with the final head.

The local administrator's onboarding completion and Personal membership snooze were
reset at their explicit request. Organization and agent configuration were retained.
