# Console acceptance follow-up

Reviewed against `9d82c11bc4` (AgenticOS 1.94.0). The source PR descriptions
record work-in-progress state; a `Refs` footer alone is not evidence of missing
behavior. This pass checked their linked issue requirements against released
code before adding follow-up work.

| Source PR | Issue | Acceptance assessment |
| --- | --- | --- |
| #3454, #3449 | #3300 | Per-role navigation, discovery ceilings, optional notices and role dashboard defaults are implemented. The preview covered navigation alone; the follow-up below completes the combined presentation preview. |
| #3437 | #3302 | Deployment/organization ceilings and personal narrowing cover saved and paged transcripts, continuations, shared/live completion and delegation metadata. Accounting remains unchanged. |
| #3432 | #3303 | Only configured providers are advertised. Local admission is refused at login, registration, reset and email-token endpoints, including existing tokens. The documented environment override preserves operator recovery. |
| #3431 | #3382 | The saved answer replaces a dropped local bubble; replay removes the old bubble. Continuation recovery requires a new saved segment of the interrupted run. |

## Completed preview requirement

Organization AI & services role settings retain their inline navigation preview
and add **Open console preview**. The shared dialog groups navigation,
permission-filtered dashboard placeholders, catalog restrictions and optional
product-prompt visibility. It loads no member content or widget queries.

Navigation reflects its current draft; the remaining panels reflect saved role
defaults. Personal overrides and administrator-only dashboard privileges are
excluded. Deployment and role catalog limits intersect; catalog managers bypass
only the role limit, matching discovery behavior. An allow-list count is an
upper bound before live connected/installed availability and resource permissions,
not an invented catalog total. Empty defaults remain empty.

The preview shares the dashboard's layout resolution and widget permission
registry. It preserves the deployment/organization notice ceiling. The dialog
uses the existing focus trap, Escape handling and trigger focus restoration,
and adapts its layout to the preview container.

## Evidence

- 280 focused backend acceptance tests passed across console catalog/presentation,
  chat-cost policy/HTTP and configured sign-in methods. These are existing tests,
  not a claim that every backend suite was rerun.
- Focused preview regressions cover permission ceilings, catalog intersections,
  manager behavior, inherited and empty dashboard layouts, no private requests,
  and Escape/focus restoration.
- New preview production modules reach 100% statements, branches, functions and
  lines in their focused coverage run (35 statements, 39 branches).
- Other existing recovery regressions remain in `chat-store.test.ts` and
  `use-chat.test.tsx`; the aggregate release's CI remains the final gate.
