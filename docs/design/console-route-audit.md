# Console route audit — 2026-11-21

This is the implementation ledger for the console simplification work in PR #3160.
Source review means the route composition, its primary child forms, state branches
and configuration entry points were traced. It is not a claim that every dynamic
provider-specific field or every permission combination has been exercised in a browser.
Light/dark and touch-width verification must be recorded separately by the root task.

## Decisions and confirmed corrections

- Keep primary writing surfaces and consequential choices visible; fold secondary
  configuration with a readable summary. Native disclosures retain mounted editors.
- Keep distinct loading, empty, filtered-empty, permission and failure states. A failed
  read must never masquerade as an empty catalog; offer recovery at the point of failure.
- Builder summaries do not change the agent spec or publish defaults. Voice setup
  deep links still reveal the correct section. Organization service switches stay
  separate from disclosure buttons and maintain their existing authority checks.
- Project creation starts with name, workspace and audience. Optional instructions,
  default agent and description remain available and open automatically for a field refusal.
- Empty hints explain actual tasks and the next step. Avoid decorative fake data
  and examples that look like buttons but perform no action.

## Route ledger

The inventory includes every `page.tsx` under `frontend/src/app/[locale]`, including
redirects, authentication, public viewers, desktop surfaces and development previews.
Rows marked pending or delegated are not completed reviews.

| Route | Source status | Findings / action |
| --- | --- | --- |
| `/forgot-password` | source reviewed / retained | Retain anti-enumeration response and explicit retry; long email confirmation text follows the shared form layout. |
| `/login` | source reviewed / retained | Retain shared `AuthHeading`, static brand mark, named email/password fields, invalid-email feedback, directory sign-in and OAuth destinations. |
| `/magic-link-sent` | source reviewed / changed | Align its heading with account recovery; long email addresses can wrap instead of widening the form. |
| `/register` | source reviewed / retained | Retain sign-up policy and invitation-aware registration; presentation follows the same heading and form shell. |
| `/reset-password` | source reviewed / changed | Use the same `AuthHeading` for the missing/expired-link state and keep a real link to password recovery. Token metadata retains no-referrer. |
| `/admin/background-jobs` | source reviewed / retained | Retain status/pool filters, circuit-breaker guidance and explicit Retry for overview failure. |
| `/admin/organizations/[id]` | source reviewed / retained | Retain metadata-only tenant detail and distinct 404/error presentation. This route does not grant membership or access to tenant resources. |
| `/admin/organizations` | source reviewed / retained | Retain server-side search, kind filter, sort and paging; collection failures are distinct from an empty result. |
| `/admin` | source reviewed / retained | Retain redirect to users rather than duplicate dashboard statistics and navigation. |
| `/admin/settings` | source reviewed / changed | Fix addressable sections and names; preserve mounted drafts, one PATCH for edited fields and separate immediate credential/image saves. |
| `/admin/system` | source reviewed / retained | Retain service summary and per-service status, with optional refresh paused in background tabs. |
| `/admin/users` | source reviewed / retained | Retain server search/sort/pagination and details drawer; destructive/impersonation controls keep their existing confirmation boundaries. |
| `/agents/[id]/evals/[runId]` | source reviewed / retained | EvalRunView separates denied access, failed reads with Retry, live status and comparison/cases tabs; existing guarded navigation retained. |
| `/agents/[id]/improve/[session]` | reviewed / changed | ImprovementPage keeps stage navigation, budget/acceptance guards and retryable session reads; added Retry for the initial agent read. |
| `/agents/[id]` | reviewed / changed | Instructions and model remain first; Variables, Voice, Starters, reviewers, alerts and tracing use collapsed summaries. Voice deep links reveal their tab. Inline instructions height follows the viewport with fullscreen retained. Existing models keep Provider/Model visible and fold connection details, automatically revealing missing setup/refusals. Builder tabs, save/publish permissions and test panel retained. |
| `/agents` | reviewed / changed | Read errors now have Retry; cached rows survive refresh failure. Empty state gives concrete first-agent examples. |
| `/apps` | reviewed | Gallery already distinguishes access/error/empty and explains Apps capability, report/dashboard examples and private sharing; archived apps remain discoverable. |
| `/browse/[runId]/[callId]` | source reviewed / retained | Shared BrowserWindow distinguishes loading, unavailable, forbidden and gone states. Remote browser/native takeover was inspected in source; no runtime takeover or visual pass was performed by this workstream. |
| `/channels` | source reviewed / changed + targeted tests | Permission/list failure retries its owning query; platform-first creation and optional controls retained. Component integration checks; actual channel delivery and provider setup remain runtime checks. |
| `/chat` | source reviewed / changed + browser checks | Shared live/history projection, collapsed raw diagnostics, single produced outputs, acknowledged inline questions, viewport owner, unified panels and the selected default Workspace sidebar and two opt-in alternatives. Real local conversations and shared controls inspected in both themes; responsive/event-trace regressions run in CI. |
| `/context` | reviewed / changed | List and editor failures, drop parsing, queued drafts and unsaved guards inspected. Empty hint explains standing context vs on-demand reference. |
| `/dashboard` | reviewed | Role-aware views, URL period/group/section filters, sanitized saved layouts and edit/reset/preset failures traced. MeOpening reserves its loading row; checklist and summary widgets retain recovery. Existing dashboard integration checks exercised; no redundant configuration refactor. |
| `/datasets/[id]` | reviewed / changed | Cases/results/settings and historical URL aliases retained. Version paging and unsaved-copy restoration inspected. Cold metadata failures now offer a query-owned Retry; cases retain their own recovery action. |
| `/datasets` | reviewed / changed | List query error and access states remain separate; empty hint explains examples → evals → version/model comparison. Creation already folds optional description. |
| `/dev/agent-designs` | reviewed | Development-only, production notFound. URL variants sanitize to profile/directory/compact; directory/builder toggles preserve variant and controls only edit local sample state, explicitly labelled unsaved. |
| `/dev/components` | reviewed | Development-only gallery rejects production via notFound. Local primitive controls, confirms, palette, ServiceCard and agent-step examples inspected; no backend mutations. Shared primitive changes flow into this gallery. |
| `/documents/[id]` | reviewed | WorkspaceExplorer receives folder identity and shared file presentation; layout height chain retained. Pane standardization is owned by chat_panels_ui. |
| `/documents` | reviewed / changed | WorkspaceBrowser file grouping/search/open flow inspected. File listing failure now uses standard error + Retry rather than isolated red text. |
| `/evals` | source reviewed / changed + targeted tests | Permission-read failure has Retry; empty-state dataset CTA requires dataset view authority. Component integration checks cover refusal and recovery; browser/theme validation is separate. |
| `/groups/[id]` | reviewed / changed | Resources grouped by kind precede budgets/quality. Metadata/resource query recovery and member/lead authority traced. Shared skill opens its actual detail; shareable catalog failure now retries in-place without closing or dropping selection. |
| `/groups` | reviewed / changed | Department gallery uses query Retry, permission-gated manage actions and separate templates/form/member dialogs. Batch template creation now blocks dismissal, cancellation and selection changes during its write. |
| `/inbox` | reviewed / changed | All/urgent/watches/suggestions/Done URL filters, approval deep links and restore flow traced. Filter control switches to Select on phones. Open and Done failed reads now explain the actual reason beside their existing Retry. |
| `/invitations/[token]` | source reviewed / retained | Retain explicit acceptance, query invalidation and active-organization adoption; signed-out staging is owned by AuthGuard. |
| `/invitations/pending` | source reviewed / retained | Retain the same acceptance card with the staged httpOnly invitation handle. No token is copied into a visible field. |
| `/kb/[id]` | reviewed redirect | Compatibility redirect to /rag/[id]; no independent screen. |
| `/kb` | reviewed redirect | Compatibility redirect to /rag; no independent screen. |
| `/link/[token]` | source reviewed / retained | Retain account/platform/server identification before explicit confirmation, error and connected states, and the link to personal connected accounts. |
| `/mcp-servers` | source reviewed / changed + targeted tests | Catalog/personal Retry, connection-specific tool search reset, actual setup link and pending draft locks. Targeted hook/picker tests; live OAuth and remote server probing require their runtime. |
| `/orgs/[id]/directory` | source reviewed / changed | Add failed-list Retry. Keep membership/role gates and existing no-access/loading distinctions. |
| `/orgs/[id]/groups` | source reviewed / retained | Retain readable member groups and permission-gated create/edit/delete/member management; empty guidance belongs to `GroupList`. |
| `/orgs/[id]/members` | reviewed / changed | AI Architect exposes its Builder link beside the switch with no empty disclosure. Background-role errors now have a reason and query-owned Retry. Assistant/conversation controls precede background models; noninteractive section headings keep each service switch/disclosure independent. Role and organization gates retained. |
| `/orgs/[id]/retention` | source reviewed / retained | Retain permission loading/refusal/failure distinctions, policy Retry and explicit save confirmation. |
| `/orgs/[id]/roles` | source reviewed / retained | Retain searchable keyboard-reachable permission matrix, scoped permission labels and catalog-failure state. |
| `/orgs` | reviewed / changed | Membership search, query recovery and workspace switching retained. Only the active workspace exposes AI/services and governance shortcuts, derived from current-tenant permissions; no permission is assumed for other organizations. |
| `/profile` | source reviewed / retained | Retain the compatibility redirect to `/settings/profile`; there is no duplicate profile editor. |
| `/projects/[id]` | reviewed | Files, Chats, Apps and Instructions are independently addressable. Unsaved instruction guard and workspace-move gate retained. Child editor and file operations retain existing tests; browser comparison remains required. |
| `/projects` | reviewed / changed | List distinguishes errors/empty/search; empty hint names realistic projects. Create dialog keeps workspace and audience visible, folds optional instructions/defaults and reveals field refusals. |
| `/rag/[id]` | reviewed / changed | Documents, ingestion, sync and gaps stay addressable. Cold read failure now uses standard error + Retry; warm failure preserves prior data and notice. Connector/refusal states retained. |
| `/rag` | reviewed / changed | Knowledge list/search/source tabs and creation entry inspected. Empty hint explains documents → attach to agent → search. |
| `/remote-agents` | source reviewed / changed + targeted tests | Read authority gates query and Retry. Optional registration authentication/handle reveal field errors; failed deletion remains open and blocks duplicates while pending. Mocked hook/dialog/page checks, not live remote-agent certification. |
| `/routines` | reviewed / changed | Schedule/event/watch creation remains gated. RoutinesList has distinct read error/search/empty states; empty hint explains the three entry points. |
| `/runs` | source reviewed / changed + targeted tests | Permission-read Retry and query-disabled denial retained. Row selection scrolls only its list; unavailable/loading/failed focused detail keeps Close, transient failures have Retry, nested Escape respects child dialogs. Mocked component/hook checks; live backend/browser behavior is separate. |
| `/sandboxes` | source reviewed / changed + targeted tests | Read denial disables query; permission failure differs from refusal. Both list tabs have Retry and read-only users have no Edit/Delete. Page/hook checks; actual sandbox hosts and native files require runtime validation. |
| `/settings/account` | source reviewed / retained | Retain password validation, current/new-password autocomplete, session controls and explicit destructive confirmations. No automatic security changes. |
| `/settings/api-keys` | source reviewed / retained | Retain the consolidated MCP/API access surface and addressable inner view. Key and scope read failures retain retry; keys are not fabricated from an empty response. |
| `/settings/api-keys/reference` | source reviewed / retained | Retain the separate API reference destination rather than expanding the reference into the access form. |
| `/settings/assistant` | source reviewed / retained | Retain redirect to account preferences so old links still work. |
| `/settings/blobby` | source reviewed / retained | Retain desktop-only controls and named appearance/behavior sections; native execution requires the desktop app. |
| `/settings/desktop` | source reviewed / retained | Retain one browser fallback via `DesktopTab`, with readiness, notification, device, window and pinned preferences inside the native surface. |
| `/settings/mcp` | source reviewed / retained | Retain compatibility entry into MCP access; empty connected-client state explains what connecting enables. |
| `/settings/memory` | source reviewed / retained | Retain Memories/Notes separation and personal ownership. Agent choices remain permission-filtered. |
| `/settings/mobile` | source reviewed / retained | Retain separate pairing, phone settings and setup surfaces; device pairing is not performed by this audit. |
| `/settings/notifications` | source reviewed / retained | Retain named event controls, channel filtering and paging. Mandatory transactional emails remain explanations rather than misleading switches. |
| `/settings` | source reviewed / retained | Retain redirect to profile; no duplicate overview page. |
| `/settings/profile` | source reviewed / changed | Retain unified identity save and separate personal-account connections; simplify optional appearance controls in `AppearanceSettings`. |
| `/settings/shortcuts` | source reviewed / retained | Retain keyboard recording, explicit Save/Clear and collision feedback. Native global-shortcut registration is outside browser verification. |
| `/settings/sign-ins` | source reviewed / retained | Retain personal, tenant-scoped kept sign-ins and deployment-availability gating for starting a browser. Do not expose cookie contents. |
| `/settings/slash-commands` | source reviewed / retained | Retain searchable, paged command management, explicit failed-read handling and existing create/edit dialogs. |
| `/skills/[id]/improve/[session]` | reviewed / changed | SkillImprovementPage keeps line/merge context and staged review; added Retry for the initial skill read. |
| `/skills/[id]` | reviewed / changed | SkillDetails separates bindings, content and history; metadata/forks/versions failures now retry each owned query. Permission refusal stays distinct. |
| `/skills` | reviewed / changed | Categories/search/group filters, data errors and resource creation inspected. Empty hint names reusable checklist/report/procedure examples. |
| `/tables/[id]` | reviewed / changed | Saved views, grid/list/kanban, schema and record failure paths inspected. Cold metadata failure now shows its reason and Retry; record queries already have retry. Large Add record forms keep required, document and prefilled values visible and fold optional properties without dropping edits. |
| `/tables` | reviewed / changed | Archive/filter/error/create/CSV paths inspected. Column types and defaults remain explicit; empty hint names contacts, requests and project records. |
| `/vault` | source reviewed / changed + targeted tests | Retry refreshes personal/secrets and organization accounts only when authorized; available sections remain usable. Integration mocks check authority; real provider authorization and secret storage runtime were not exercised here. |
| `/work` | source reviewed / retained | Existing active/history split, encoded conversation links and pending-guarded Stop retained. Source interaction review only; no claim of exercising live background-task cancellation in a browser. |
| `/workflows/[id]/form-preview` | source reviewed / changed | Saved-draft preview retains exact entry, edit authority, test execution and run link. Add query-owned Retry on read failure; missing form remains distinct. Targeted regression; no public draft exposure. |
| `/workflows/[id]/logs` | source reviewed / retained | WorkflowLogs uses bounded server filters, pagination, request-field errors and read Retry; linked run details retained. |
| `/workflows/[id]` | reviewed / changed | Canvas, triggers and settings remain separate. Cold metadata/catalog failure has explicit recovery; cached canvas stays mounted during a refresh failure. Blank rename gets an inline explanation instead of silently failing to autosave. WorkflowSettingsForm already folds execution/history/limits. |
| `/workflows/[id]/runs/[runId]` | reviewed / changed | Fixed permanent loading on failed run/steps/files/graph/workflow/catalog reads with explicit error and query-owner Retry. Existing read-only canvas, output/files tabs and guarded cancel/retry/resolve retained. |
| `/workflows/[id]/runs` | source reviewed / retained | RunHistory has filters, pagination and Retry; optional statistics already folded. StartRunDialog preserves live-contract loading/refusal and test/live permissions. |
| `/workflows` | reviewed / changed | Gallery loading/error/filtered-empty states and templates inspected. Cards keep identity, description, access, publication and management/history actions; runtime, node counts and tags remain in the existing editor/history and filters instead of every card. Removed the gallery-only node-catalog read. New form already folds description/tags and makes trigger/audience choices explicit. |
| `/workflows/runs` | source reviewed / retained | Shared RunHistory provides cross-workflow filters, pagination, failed-read Retry and workflow-specific row links. |
| `/apps/[id]` | source reviewed / retained | ArtifactViewer separates unavailable, requestable access and transient failure with Retry; version pin, return route, isolated artifact rendering and request drawer retained. |
| `/oauth/consent` | source reviewed / changed | Distinguish expired/missing request (404) from failed reads (including 403, 429 and 5xx). Failed reads offer Retry and no Allow control. An incomplete link no longer sends a request for an empty ID. Global deployment authority remains a separate unchecked opt-in. |
| `/a/[publicKey]` | source reviewed / changed | Retain public no-session fetch, 404-versus-failure distinction, password gate and signed sandboxed content frame. Long titles wrap and the theme action stays reachable. |
| `/auth/callback` | source reviewed / retained | Retain one-use OAuth exchange, session adoption/cache clearing, safe return destinations and cancellation ownership. No automatic extra retry of the exchange. |
| `/auth/email-change` | source reviewed / changed | Align status geometry and typography, allow long errors to wrap and preserve the unauthenticated confirmation contract. This page does not sign anybody in. |
| `/auth/magic-link` | source reviewed / changed | Align heading, status announcements and reserved status geometry. The password-reset destination is now labelled **Reset password**, rather than falsely promising a new magic link. |
| `/auth/pair` | source reviewed / changed | Keep identity preview and explicit session-adoption consent. Failed links now offer a way back to sign-in. The loading button retains its label width; labels and actions wrap on narrow screens. |
| `/desktop/blobby` | source reviewed / retained | Retain desktop-only transparent-window gating, signed-out dozing state and reduced-motion handling rather than placing an unusable sign-in form in a tiny window. |
| `/desktop/quick-ask` | source reviewed / retained | Retain account/tenant-scoped tabs, bounded searchable history, explicit failed-history retry, Escape handling and draft retention across inactive tabs. |
| `/desktop/readiness` | source reviewed / retained | Retain browser fallback, readiness/capability checks and explicit failure feedback; finish navigation follows successful native setup. |
| `/desktop/welcome` | source reviewed / changed | Align heading typography and wrap shortcut rows; preserve native-only gating and the existing sign-in return destination. |
| `/e/[publicKey]` | source reviewed / changed | Retain branded anonymous chat, visitor-owned media links and operator-filtered frames. Long titles and attachment names no longer widen the page. The shared turn renderer keeps diagnostics collapsed until requested. |
| `/f/[token]` | source reviewed / changed | Retain public-only form submission, field validation, distinct refusal states and no private administration links. Long submission confirmations wrap. |
| `/legal/cookies` | source reviewed / changed | Same theme/reading-shell correction; do not introduce consent for nonexistent public-surface tracking. |
| `/legal/privacy` | source reviewed / changed | Same theme/reading-shell correction; no change to legal commitments or dates. |
| `/legal/terms` | source reviewed / changed | Remove forced light mode from `LegalPage`; retain operator-branded legal content and sibling links. Heading and prose reflow in the selected console theme. |
| `/onboarding/[...step]` | source reviewed / retained | Retain compatibility redirect into the current start hub; historical step links do not become 404s. |
| `/onboarding` | source reviewed / changed | All guided steps reviewed: inline announcement editor, closed optional configuration, correct permission-aware settings links, restrained token-based artwork and opt-in short motion. Removed pulsing organization choices; console tour remains explicit only. |
| `/` | source reviewed / retained | Retain the locale-preserving sign-in redirect; no deployment marketing screen added. |
| `/shared/[token]` | source reviewed / changed | Add noindex/nofollow and no-referrer metadata: previously this secret route inherited the root's indexable metadata. Preserve inert remote Markdown images, public rebuilt visuals, plain-text user messages and no private console controls. |

## Verification for builder and resource corrections

Targeted component and integration tests cover native-section defaults and retained
editing, voice deep links, organization role gates, cold/warm agent-read failure,
project optional setup and field-refusal reveal, KB recovery, table metadata recovery
Documents recovery, dataset and skill recovery, workflow/catalog recovery, empty-name validation and optional record-field retention. Final command outcomes and browser screenshots belong in
the root task delivery; no whole-directory suite or E2E run was performed locally.

## Nested forms and configuration review

- Shared ChipsInput uses one field surface with a transparent inline input; Unicode limits, suggestions, commit/remove controls remain and IME Enter cannot prematurely commit a candidate.
- NewAgentDialog already folds optional description/category/tags; name, audience and
  handle remain primary. CapabilityWorkbench separates capability navigation from
  focused settings and resources. SchemaForm already groups `x-advanced` fields and
  reveals configured/invalid advanced values; no arbitrary generated fields were hidden.
- Image/video/TTS provider selectors and their generated parameter forms were traced.
  The empty allowed-voice warning stays visible because it explains that any account
  voice could otherwise be used. Provider-specific visual checks remain part of the
  root browser verification rather than an inferred pass from the common renderer.
- EnvironmentsPanel already separates follow-latest from version pins, requires
  release authority for promotion and includes failed-read recovery. Its independent
  guard/test controls were retained; monitoring workstream inspected the same contract.
- Table record sheets commit a focused editor on close through their write queue;
  conflicts keep pending edits for retry. Large new-record forms now fold only optional
  fields; required, document and initially populated values stay visible.
- Dataset case/scoring tabs, skill binding/version flows, context creation/upload,
  project instructions and workspace choice were traced. Existing permission refusals,
  unsaved changes and validation remain authoritative.

## Verification limits

- Browser evidence is owned by the root task. Source review and component integration
  checks do not certify every live provider, every grant combination or every width.
- Desktop-only filesystem authorization and phone-specific paths require their
  actual runtime. Browser-only screenshots cannot certify those interactions.

## Settings, onboarding and public-surface verification

The source dispositions above incorporate the settings/onboarding workstream's
route and composed-component review. Targeted tests cover appearance disclosure,
addressable deployment sections, query-owned organization loading/retry and
creation refresh, directory mapping retry, guided-step editing/navigation,
explicit-only tours, consent refusal versus expiry, pairing recovery, auth
recovery destinations, secret-share metadata and hosted raw diagnostic/media
rendering. Scoped batches passed: onboarding 79 tests, settings 45, auth/public
48, tour/flow 24 and hosted 106. These are separate scoped runs, not a combined
coverage or end-to-end claim.

Hosted live steps use the shared collapsed turn renderer and public media tokens;
public produced files cannot infer private workspace Open/Download authority.
Hosted/widget transports currently have no interactive ask-user/answer-ack
protocol, and hosted reconnect history contains only role/text/time. This review
does not claim full public live/history work-step parity or add authenticated
member authority to anonymous visitors.

Root browser evidence must separately record light/dark, width, focus and motion
checks. Native desktop/filesystem/global-shortcut and phone pairing execution
remain runtime verification limits; their source-reviewed rows are not manual
QA certifications. Full details and the public transport boundary are retained in
[the settings audit](console-settings-audit.md).
