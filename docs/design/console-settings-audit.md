# Settings and administration UX audit

Date: 2026-11-21. Scope: the settings, administration, organization and guided
onboarding routes in PR #3160. This is a source and interaction-test audit;
browser screenshots and live light/dark checks are recorded separately by the
main frontend review. A source review does not establish that every native
application integration works on a device.

## Decisions and implemented corrections

- Keep common appearance choices immediately visible: Theme, Style and Motion.
  Voice glow and workflow-step styling belong under **Interface details**.
  The disclosure preserves controls and their state; reduced motion remains
  reachable without expanding it.
- `/orgs` now reads the actual membership query's loading/error state. A failed
  read shows Retry, not an empty-workspace invitation or a stale success count.
  It no longer forces a second invalidation on every URL change.
- Deployment section changes update `?section=`. A new section link on the same
  mounted page selects that section without dropping unsaved field values.
- Name the deployment navigation for its contents: **Announcements & maintenance**
  contains the maintenance screen; **Updates & diagnostics** contains releases and
  diagnostics. The two were previously both described as maintenance.
- The directory mapping list offers Retry after a failed read, while keeping its
  existing permission gates, mutation confirmations and role-assignment rules.
- Onboarding links point to the actual destinations. Maintenance goes to
  `/admin/settings?section=notices`, and workspace voice configuration goes to
  `/orgs/{id}/members?tab=voice`. Branding and mobile push retain their correct
  deployment sections.
- The announcement in onboarding is edited directly inside its live preview,
  with a real associated label. There is one editable value rather than a second
  text copy beside it. Preview changes do not save until Continue.
- Optional organization settings use consistent closed summaries with an icon,
  purpose and chevron, then links to governance, assistant and voice settings.
  A budget-only operator is not offered the organization-profile editor.
- Onboarding illustrations use the console's surface, text, border and accent
  tokens in both themes. Pulsing workspace outlines were removed. Navigation
  keeps one header geometry and reserved content space; short entry motion is
  enabled only when both the app and system allow it.

## Route inventory and disposition

| Route | Source inspection and resulting decision |
| --- | --- |
| `/settings` | Retain redirect to profile; no duplicate overview page. |
| `/settings/profile` | Retain unified identity save and separate personal-account connections; simplify optional appearance controls in `AppearanceSettings`. |
| `/settings/account` | Retain password validation, current/new-password autocomplete, session controls and explicit destructive confirmations. No automatic security changes. |
| `/settings/notifications` | Retain named event controls, channel filtering and paging. Mandatory transactional emails remain explanations rather than misleading switches. |
| `/settings/sign-ins` | Retain personal, tenant-scoped kept sign-ins and deployment-availability gating for starting a browser. Do not expose cookie contents. |
| `/settings/memory` | Retain Memories/Notes separation and personal ownership. Agent choices remain permission-filtered. |
| `/settings/slash-commands` | Retain searchable, paged command management, explicit failed-read handling and existing create/edit dialogs. |
| `/settings/api-keys` | Retain the consolidated MCP/API access surface and addressable inner view. Key and scope read failures retain retry; keys are not fabricated from an empty response. |
| `/settings/api-keys/reference` | Retain the separate API reference destination rather than expanding the reference into the access form. |
| `/settings/mcp` | Retain compatibility entry into MCP access; empty connected-client state explains what connecting enables. |
| `/settings/mobile` | Retain separate pairing, phone settings and setup surfaces; device pairing is not performed by this audit. |
| `/settings/assistant` | Retain redirect to account preferences so old links still work. |
| `/settings/blobby` | Retain desktop-only controls and named appearance/behavior sections; native execution requires the desktop app. |
| `/settings/desktop` | Retain one browser fallback via `DesktopTab`, with readiness, notification, device, window and pinned preferences inside the native surface. |
| `/settings/shortcuts` | Retain keyboard recording, explicit Save/Clear and collision feedback. Native global-shortcut registration is outside browser verification. |
| `/admin` | Retain redirect to users rather than duplicate dashboard statistics and navigation. |
| `/admin/users` | Retain server search/sort/pagination and details drawer; destructive/impersonation controls keep their existing confirmation boundaries. |
| `/admin/organizations` | Retain server-side search, kind filter, sort and paging; collection failures are distinct from an empty result. |
| `/admin/organizations/{id}` | Retain metadata-only tenant detail and distinct 404/error presentation. This route does not grant membership or access to tenant resources. |
| `/admin/system` | Retain service summary and per-service status, with optional refresh paused in background tabs. |
| `/admin/background-jobs` | Retain status/pool filters, circuit-breaker guidance and explicit Retry for overview failure. |
| `/admin/settings` | Fix addressable sections and names; preserve mounted drafts, one PATCH for edited fields and separate immediate credential/image saves. |
| `/orgs` | Replace local pseudo-loading and unconditional refresh with query-owned pending/error/retry states. |
| `/orgs/{id}/members` | Preserve tenant adoption and Members/Governance/Assistant ownership; detailed Assistant/builder refinement is coordinated in the main frontend task. |
| `/orgs/{id}/groups` | Retain readable member groups and permission-gated create/edit/delete/member management; empty guidance belongs to `GroupList`. |
| `/orgs/{id}/directory` | Add failed-list Retry. Keep membership/role gates and existing no-access/loading distinctions. |
| `/orgs/{id}/roles` | Retain searchable keyboard-reachable permission matrix, scoped permission labels and catalog-failure state. |
| `/orgs/{id}/retention` | Retain permission loading/refusal/failure distinctions, policy Retry and explicit save confirmation. |
| First-run console tour and explicit Help flows | Verified that `useOnboardingTour` does not auto-open for new accounts or loading permissions. The organization-switcher spotlight is available only in an explicitly requested tour; interactive coaching mounts only for an explicit flow or its one-use OAuth resume. Regression tests cover unobstructed first use and explicit replay. |
| `/onboarding` and resumable step URLs | Apply the preview, artwork, motion, grouping and link corrections above without changing policy defaults or automatically saving decisions. |

## Verification

Targeted Testing Library/Vitest checks cover the changed controls and data paths:

- Appearance: advanced controls start closed, Theme/Style/Motion remain visible,
  opening details exposes the same effective stored choices, and reduced motion
  disables glow without erasing its saved preference.
- Organizations: a failed read is not presented as empty and Retry reaches the
  query; unresolved memberships retain loading geometry.
- Deployment navigation: valid/invalid initial links, changing a section and
  following a changed deep link without remounting.
- Directory: failed mapping read, successful retry, existing permission refusal,
  create/delete and role-assignment regression tests.
- Onboarding: a single editor inside the preview, tone changes, no save before
  Continue, clear/preserve/failure cases, corrected links, closed optional groups,
  permission-aware destinations, hidden steps and resumed state.

The main task runs combined lint, type checks, translation guards and CI for the
final PR SHA. Do not interpret these source dispositions as a completed visual
inspection of every route or a test of native desktop/mobile integrations.

## Authentication, public links and native route audit

The following route entry points and their composed surfaces were also reviewed
in source. Their disposition is complete for this source audit; native device
execution and visual browser checks are separate verification layers.

| Route | Source inspection and resulting decision |
| --- | --- |
| `/` and localized roots | Retain the locale-preserving sign-in redirect; do not add a marketing screen inside a deployment. |
| `/login` | Retain shared `AuthHeading`, static brand mark, named email/password fields, invalid-email feedback, directory sign-in and OAuth destinations. |
| `/register` | Retain sign-up policy and invitation-aware registration; presentation follows the same heading and form shell. |
| `/forgot-password` | Retain anti-enumeration response and explicit retry; long email confirmation text follows the shared form layout. |
| `/reset-password` | Use the same `AuthHeading` for the missing/expired-link state and keep a real link to password recovery. Token metadata retains no-referrer. |
| `/magic-link-sent` | Align its heading with account recovery; long email addresses can wrap instead of widening the form. |
| `/auth/callback` | Retain one-use OAuth exchange, session adoption/cache clearing, safe return destinations and cancellation ownership. No automatic extra retry of the exchange. |
| `/auth/magic-link` | Align heading, status announcements and reserved status geometry. The password-reset destination is now labelled **Reset password**, rather than falsely promising a new magic link. |
| `/auth/email-change` | Align status geometry and typography, allow long errors to wrap and preserve the unauthenticated confirmation contract. This page does not sign anybody in. |
| `/auth/pair` | Keep identity preview and explicit session-adoption consent. Failed links now offer a way back to sign-in. The loading button retains its label width; labels and actions wrap on narrow screens. |
| `/profile` | Retain the compatibility redirect to `/settings/profile`; there is no duplicate profile editor. |
| `/invitations/{token}` | Retain explicit acceptance, query invalidation and active-organization adoption; signed-out staging is owned by AuthGuard. |
| `/invitations/pending` | Retain the same acceptance card with the staged httpOnly invitation handle. No token is copied into a visible field. |
| `/link/{token}` | Retain account/platform/server identification before explicit confirmation, error and connected states, and the link to personal connected accounts. |
| `/apps/{id}` | Retain authenticated, version-addressable full-window artifact viewing, validated return destination and server-provided edit authority. Public viewing remains a separate surface. |
| `/oauth/consent` | Distinguish expired/missing request (404) from failed reads (including 403, 429 and 5xx). Failed reads offer Retry and no Allow control. An incomplete link no longer sends a request for an empty ID. Global deployment authority remains a separate unchecked opt-in. |
| `/a/{publicKey}` | Retain public no-session fetch, 404-versus-failure distinction, password gate and signed sandboxed content frame. Long titles wrap and the theme action stays reachable. |
| `/e/{publicKey}` | Retain branded anonymous chat, visitor-owned media links and operator-filtered frames. Long titles and attachment names no longer widen the page. The shared turn renderer keeps diagnostics collapsed until requested. |
| `/f/{token}` | Retain public-only form submission, field validation, distinct refusal states and no private administration links. Long submission confirmations wrap. |
| `/shared/{token}` | Add noindex/nofollow and no-referrer metadata: previously this secret route inherited the root's indexable metadata. Preserve inert remote Markdown images, public rebuilt visuals, plain-text user messages and no private console controls. |
| `/legal/terms` | Remove forced light mode from `LegalPage`; retain operator-branded legal content and sibling links. Heading and prose reflow in the selected console theme. |
| `/legal/privacy` | Same theme/reading-shell correction; no change to legal commitments or dates. |
| `/legal/cookies` | Same theme/reading-shell correction; do not introduce consent for nonexistent public-surface tracking. |
| `/desktop/blobby` | Retain desktop-only transparent-window gating, signed-out dozing state and reduced-motion handling rather than placing an unusable sign-in form in a tiny window. |
| `/desktop/quick-ask` | Retain account/tenant-scoped tabs, bounded searchable history, explicit failed-history retry, Escape handling and draft retention across inactive tabs. |
| `/desktop/readiness` | Retain browser fallback, readiness/capability checks and explicit failure feedback; finish navigation follows successful native setup. |
| `/desktop/welcome` | Align heading typography and wrap shortcut rows; preserve native-only gating and the existing sign-in return destination. |
| `/onboarding/{legacy-step…}` | Retain redirect to the current onboarding entry so existing history links do not become 404s. |

`DesktopSetting` now allows labels and controls to wrap as a unit on narrow native
windows. This affects native settings consistently without changing any persisted
preference or native command. Legal bodies remain English/Polish as before; this
UI audit does not claim new German/Turkish legal translations.

Additional regression checks cover failed consent reads versus expiry, incomplete
consent links, pairing recovery, accurate magic-link recovery labels, secret-share
metadata and hosted turn disclosures. Existing public-form, public-artifact,
shared-transcript, cookie-banner and native/browser-gating tests remain in the
verification batches.

## Public chat transport boundaries

Hosted pages reuse `TurnParts`, including initially collapsed work, raw diagnostic
results and inline generated media. Regression checks cover a generated image
remaining visible exactly once after opening its raw result, and a public file
card never inferring private workspace Open/Download authority. Hosted media
continues to use the embed key and signed file token, not the console endpoint.

The hosted page and injected widget currently have **no interactive question
protocol**. `EmbedSession.handle` accepts only `message`; `visible_frames` does
not include `ask_user` or `ask_user_answered`. Neither client renders a question
dock, so there is no dock to migrate into the transcript. Introducing question
answering would require an explicit visitor-scoped admission, correlated answer
and acknowledgement contract; reusing an authenticated member's answer endpoint
would be incorrect. No such authority is added by this presentation change.

Hosted reconnect history currently contains only `role`, `text` and `at`. Live
steps are rendered consistently with the console when the operator permits their
frames, but replay cannot reconstruct reasoning, raw tool results or produced
output cards from that text-only contract. The injected widget uses its own
small script and receives no tool-step/detail frames under its current visibility
policy. Full live/history parity on these public transports therefore requires
a separate, operator-filtered history contract; it is not claimed here.

## Unfinished setup reminder

The desktop sidebar and phone navigation reuse membership-scoped `useStart` state
for a compact Finish setup card. Dismissing uses the existing server-owned
24-hour snooze and leaves a quiet return link; loading, failure, wrong-organization
and confirmed-completion states do not show an incomplete claim. The collapsed
rail and dismissal controls retain named, touch-sized targets. No local completion
or dismissal flag is introduced.

A separate persisted navigation-only UI store remembers only a known
step and optional known question under `/onboarding`, scoped by account and exact
organization. The entry observer strips unrelated query values; the store and
consumer validate the navigation again. Server-confirmed completion clears the
hint. Reloads restore only sanitized navigation; another device safely begins at
the default entry. This is not backend resume state. Existing organization-logo previews no longer draw a square
background, border or shadow around their circular avatar. The standalone header retains its existing language control.

Inbox now shares row grid, spacing, mark size, title/metadata/detail typography
and responsive action alignment between open items and Done. The same page frame
is retained when filtering. Approval forms inherit the common outer inset while
keeping their fields, read-only/decision gates and contextual sizing. Done keeps
decision badges and restore behavior, with readable source/time on phones.
Scoped Inbox/approval tests pass without changing acceptance or filtering contracts.

## Dashboard request/cache inspection

The same usage query key/window is shared by MeHeader, summary and matching
widgets, so multiple consumers do not imply duplicate HTTP requests. The page
starts onboarding and Briefing reads before mounting the opening cards; those
read the same cached queries. Permission/layout gating before the widget grid
is retained deliberately, rather than requesting widgets the caller may not see.

One confirmed unnecessary read was removed: layout presets were fetched on every
view even though their controls exist only under organization arrangement. The
hook now accepts `enabled`; the page enables it for the requested organization
view. Actual request assertions cover zero preset reads on Me/Group/Deployment
and one on Organization, plus existing save/remove behavior. This saves one
cold request on those views; no first-paint speedup or timing benchmark is claimed.

Dashboard aggregates retain the existing 30-minute RAM freshness. A normal-browser
reload does not restore that query cache; run events do not invalidate usage
aggregates on each completion. No polling, server TTL or arbitrary freshness
change was introduced. Backend aggregate work and the static widget import graph
remain separate performance questions requiring profiling before a refactor.

## Workflow surfaces

Workflow templates now reuse the agent library's compact category selector,
bounded detail canvas and template-row composition. Table-backed templates keep
their existing provision permission gate and show the refusal reason beside the
choice; local graph examples and Await a reply retain their existing contracts.

Workflow Logs uses the same flex/fill list frame and bottom pagination placement
as Run History; filters remain server-owned and invalid run IDs remain visible
field refusals. The workflow route and its own portal dialogs opt into stable
text-field hover fill. The override matches only standard filled inputs/areas;
TemplateBox keeps its transparent syntax backdrop. Focus and invalid borders
remain shared, and fields elsewhere do not receive this override.

Inline editor, step-test, chat-trigger and form-preview starts use their visible
run/answer surface as start feedback and omit the redundant start-success toast.
Admission failures remain visible; history admission retains its route feedback.
No run admission, polling, permissions, schema, choice or published-version
contract changes. Shared navigation progress is owned by the console router
adapter rather than patched separately inside each workflow table.
