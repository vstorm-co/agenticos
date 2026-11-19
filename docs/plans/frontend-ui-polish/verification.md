# Console interaction polish — verification

Date: 2026-11-18. Base implementation: 1.82.2.

## Scope

This change applies shared interaction rules throughout the existing console,
then fixes concrete exceptions in chat, Inbox, authentication, organization
services, setup wizards, dashboard tips and mobile gestures. It retains the
console's neutral palette, typography, permissions and existing save behavior.
The default AgenticOS prompt also clarifies economical delegation, safe recovery
from tool failures, drafts and artifact verification. Capability activation is
awaiting the maintainer’s tool list. This patch does not cut a release.

## Interaction contracts

- Disclosures retain visited content and unsaved input, collapse to zero height,
  become inert and leave the accessibility tree immediately, and return focus
  to their trigger when focused content closes. Service forms still mount
  immediately so collapsed settings retain their existing registration behavior.
- `interpolate-size` is progressive enhancement. CSS Grid supplies the fallback;
  browser checks explicitly exercise both paths. Initial insertion uses
  `@starting-style`; no discrete `display` transition is required.
- The heading contains the disclosure button; a service switch is separate.
  This follows the accordion guide's instruction: “Place the `button` inside
  the heading so the heading keeps its semantics.”
- Expansion transitions from zero to `auto`, rather than between two intrinsic
  keywords: “One end of the transition must be a fixed length or percentage.”
- Entrances use opacity and restrained scale, and moving cursor/progress fills
  use transforms. Intrinsic disclosure height and the sidebar's actual width
  remain deliberate layout transitions.
- Press feedback uses 0.97 scale. Disabled controls retain their refusal behavior.
  Theme changes temporarily suppress descendant transitions and restore them
  synchronously, including rapid repeated theme changes.
- Tooltip groups delay the first hint and skip the delay for adjacent hints.
  Wizards enter from the navigation direction. Reduced motion resolves the
  person's console preference against the operating system's preference.
- Mobile gestures preserve release velocity when returning to rest, cancel on
  system cancellation and respect reduced motion. A preference change cancels an
  armed swipe rather than changing its direction. Pull resistance increases
  beyond the refresh threshold; pending refreshes cannot be duplicated.
- Swipe decisions read the live motion value rather than a possibly stale React
  render. A new disabled or rejection-only restriction is checked again on release.
- Inbox previews retain the action/subject/requester hierarchy. Redacted calls
  never expose context or arguments. Bounded serialized search requests may
  supply a readable subject; opaque UUIDs and arbitrary JSON do not become Inbox
  titles. Decision cards retain opaque targets when a resource name is unavailable.
  Literal commands are never decoded as JSON, and unparsed text stays visible.
- Draft previews retain inert images and never evaluate raw HTML. Copy keeps the
  original source. Version selection stays accessible when revisions disappear.
- Only credential refusals mark the password invalid and trigger a shake. The
  existing authentication error code/status are preserved; a structured reason
  distinguishes invalid local credentials, and directory sign-in uses its
  existing credential-rejection code. Disabled accounts are not field errors. Inline
  errors remain available with reduced motion, input is preserved, and provider
  outages are not presented as incorrect passwords. The email-login proxy preserves
  the domain refusal envelope; real-browser login verified that the reason survives
  both server hops before correcting the password and signing in successfully.

## Local checks

- 537 tests across 32 explicitly selected unit/integration files passed. No full
  application test suite was run locally. Eleven focused backend authentication
  and security-inventory tests also passed. A final auth-specific batch passed
  163 tests across four files, including session-route and LDAP proxy contracts.
- Focused coverage checks for the changed summary helpers, new hooks,
  disclosure primitive and gesture components reached 100% statements,
  functions and lines. Branch coverage exceeded the repository's 97.5% threshold.
- Two Playwright journeys passed against an isolated PostgreSQL/Redis/API stack:
  organization speech settings preserve an unsaved field through keyboard
  collapse/reopen with normal and reduced motion. They do not save settings.
- A real-browser interaction pass in light and dark themes at 390 px verified
  retained drafts, programmatic-close focus return, the CSS Grid fallback,
  normalized cursor coordinates after movement, compact streamed-step folding,
  markdown preview and reduced motion.
- The email-login proxy also reached 100% statement, branch, function and line
  coverage in its session-route tests.
- After switching the preview to the existing local database, eight populated
  views and an existing Northwind Labs chat were checked at both widths, without
  API 5xx responses or document overflow. This uses the existing local API; the
  isolated-stack auth and service-form journeys above exercise the PR backend.
- The dashboard tips pause across overlapping focus, hover and touch; release or
  cancellation does not move a tile while its link still has focus. Fourteen
  focused tests reached 100% statements, branches, functions and lines.
- Forty-four template/default-refresh and security-inventory tests passed after
  the prompt edits. These verify catalog and preservation contracts, not model
  response quality; no paid prompt evaluation was performed.
- Shared primitives are demonstrated in the existing development-only component
  gallery. It stays unavailable in production.

## Read-only route audit

The paths below were visited after the page heading appeared and visible loading
states settled, at 1440 × 1000 and 390 × 1000. The 43-path pass reported no API
5xx responses or document-level horizontal overflow. `/settings` redirects to
`/settings/profile`. These checks cover the isolated workspace's data and empty
states; they do not claim every populated detail state of all 101 route templates.

Ten representative paths were also checked in dark mode at both widths:
Inbox, agents, workflows, routines, runs, skills, tables, knowledge bases,
organizations and profile settings. No overflow or API 5xx was observed there.

- `/admin`
- `/admin/background-jobs`
- `/admin/organizations`
- `/admin/settings`
- `/admin/system`
- `/admin/users`
- `/agents`
- `/apps`
- `/channels`
- `/context`
- `/datasets`
- `/documents`
- `/evals`
- `/groups`
- `/mcp-servers`
- `/orgs`
- `/projects`
- `/rag`
- `/remote-agents`
- `/routines`
- `/runs`
- `/sandboxes`
- `/settings`
- `/settings/account`
- `/settings/api-keys`
- `/settings/api-keys/reference`
- `/settings/assistant`
- `/settings/blobby`
- `/settings/desktop`
- `/settings/mcp`
- `/settings/memory`
- `/settings/mobile`
- `/settings/notifications`
- `/settings/profile`
- `/settings/shortcuts`
- `/settings/sign-ins`
- `/settings/slash-commands`
- `/skills`
- `/tables`
- `/vault`
- `/work`
- `/workflows`
- `/workflows/runs`

## Limits and CI

The browser used locally was Chromium. The fallback was forced and exercised
there; this is not a claim of a native Safari or Firefox run. Backend suites,
the complete frontend coverage report, production build and the remaining E2E
journeys belong to CI for the final commit. No paid model calls or production
configuration changes were needed for this audit.

The design references informed the interaction rules, not a replacement visual
identity. Native scroll-snap strips keep the browser's own inertia and edge
behavior rather than adding a second JavaScript drag implementation.

## Default assistant and personal coding sessions

The selected capabilities, extended with sandbox Computer use, are now explicit in the shipped AgenticOS template.
Personal coding defaults to the initiating person's enabled cloud account without
an organization credential. Both Claude Code and Codex are selectable per task;
model/effort choices stay with their configured coding agent. The starter-agent
creation tests confirm that ordinary new agents continue receiving this template's
instructions. Existing customized agents retain their preservation contract.
Architect's template and shared durable-work skill are unchanged by this stage;
the new session method is an AgenticOS-only skill.

- 151 selected coding/runtime and starter-creation tests passed, followed by a
  364-test catalog/registry/eval batch and a 28-test final refusal/security batch.
  These batches overlap; they are not an aggregate test count.
- 44 real-PostgreSQL personal-account/session integration tests passed. They cover
  retained files/source identity, separate session names, tenant constraints,
  owner-only reads even for another administrator, revocation, failed cleanup and
  disconnect rollback with durable remote-destruction obligations.
- 64 personal coding tests passed under coverage, reaching 100% lines for both
  the personal session factory and account lease. A broader diagnostic report
  also included unrelated services; its total is not the CI platform gate.
- The coding report component reached 100% statements, branches, functions and
  lines, including new/continued session labels and result-archive validation.
- The additive `0342_personal_coding_sessions.py` migration was upgraded,
  downgraded and upgraded again on the isolated PostgreSQL database. Alembic
  reported no remaining model/schema drift there.
- A detached native-process supervisor was exercised with real isolated local
  process groups: normal exit and host-side timeout both stop descendants.
- Two Mattermost worker acknowledgement regressions failed before the fix and
  passed afterward, including stale in-process server/user caches. The related
  89-test channel/security batch passed. No live Mattermost message or reaction
  was sent.

The populated preview uses a copy of the existing local database. Its historical
migration branch differs from the current repository, so additive compatibility
changes were applied only to that disposable copy, retaining its data and legacy
columns. This preview is not evidence of an upgrade from that old branch; the
canonical migration round-trip above uses the separate current-schema QA database.
The preview's API does not run a worker or submit scheduled/model work.

Native-history state is checked independently of container retention: a pruned
CLI conversation that restarts successfully is reported as new, while a real
continuation remains marked continued. Seven focused regressions cover that
state and its propagation into the personal result; the related 154-test coding
batch passed. Four native-state cases reproduced the missing state before the fix.

## Follow-up to the expanded Codex review

All four findings on `ae53c04` were confirmed and addressed with regressions:

- Strict personal Codex read-back rejects missing/malformed auth as well as a
  nonzero command exit. Removal preserves the auth read's failure status; valid
  unchanged credentials remain accepted.
- Agent deletion queues personal-container teardown before workspace metadata
  cascades. Real-PostgreSQL deletion and rollback tests passed for both account
  disconnect and agent removal, including an unavailable provider.
- Container-side Python supervision is opt-in for personal cloud invocations,
  whose bounded source-copy path already requires Python. Organization sandboxes
  retain their shell-only launch contract; custom images need no new runtime.
- Shipped refresh resolves the organization's container availability once and
  passes it consistently through release identity, target defaults and legacy
  recognition. A remote default sandbox keeps coding enabled without a local
  deployment token.

The related seven-file backend batch passed 513 tests. The two real-database
cleanup regressions passed independently. Four static-analysis comments about
Alembic's dynamic revision metadata were explained and resolved as false positives.


## Browser availability, desktop and delegation defaults

The AgenticOS browser uses Built in and 100 steps per browse call. An empty
built-in endpoint resolves the operator's configured browser; if none exists,
publication succeeds and a browser call reports that it is unavailable. A
configured endpoint still requires the host allowlist. FunctionModel regressions
cover no browser use, unconfigured endpoints and refused connections, then
independent tool use and a successful final response without paid calls.

Computer use targets the existing sandbox desktop runtime. That runtime now
retains the workbench CLI and document packages; Compose values are regenerated
from the catalog. Without a container connection, Computer use and personal
cloud coding stay disabled while other tools remain. Ordinary new agents retain
the lighter workbench default. The actual enlarged desktop image has not been
built or exercised as part of these offline checks.

AgenticOS instructions now require an explicit user request for subagents;
dynamic specialists are off. The existing published-agent discovery feature is
enabled for this starter and shown beside Delegates in the Builder. Existing
backend rules preserve tenant/run permissions, pinned versions, ancestor
exclusion, revocation checks and unattended-routine restrictions. The prompt
policy does not claim to enforce user intent with a runtime keyword filter.

Verification for the browser/desktop/delegation follow-up:

- 510 selected browser, route, template and delegate-resolution tests passed;
  415 catalog/registry/browser/security tests and the final 47-test regression
  batch also passed (these counts overlap).
- 80 selected frontend tests passed, followed by the 29-test Delegates file with
  the additional read-only case. Type checking and translation checks passed.
- Backend lint passed. All 14 shipped-agent integration tests passed on isolated
  PostgreSQL, including inherited delegation defaults and preservation of edits.
- The populated preview's AgenticOS was published as version 5. The stored
  version was checked for Built in / 100 browser steps, desktop sandbox,
  Computer use and published-agent discovery; its model, MCP bindings, context
  and pinned delegates were preserved. Browser and sandbox containers are not
  running in this local preview, so no live desktop success is claimed.

## Stationary model picker triggers

Global button press scaling excluded switches and radios but still matched
comboboxes and popup anchors. Exclude those semantics in both the global rule
and shared Button/icon press rules. Existing hover/focus/open states remain.
A real Chromium run on the populated user's Builder reproduced the old
`scale: 0.97`, then verified the fixed field stayed at 637px with unchanged x
position. Enter opened the picker and Escape dismissed it. The 12 model-picker
unit tests passed; a Playwright regression covers model/provider pointer geometry
and keyboard opening without changing the selected model.

## Model makers and tab transitions

Model pickers show the model maker independently of the API transport. Known
namespaces (including OpenRouter's Z.AI, Moonshot and Meta aliases) reuse existing
checked-in brand marks; direct unprefixed models use their maker provider.
Unknown ownership stays neutral rather than borrowing the routing provider's
logo. Marks are decorative and do not change model IDs or catalog search.

Shared tab panels enter with opacity and a 4px vertical transform over 160ms.
Custom draft, authoring, delegation, browser-preview and Quick Ask tabs use the
same treatment. Quick Ask keeps its mounted sessions; live streamed draft updates
do not restart the animation. Native desktop browser surfaces remain untransformed.
Reduced motion leaves the final content visible without animation.

The selected four-file model/tab batch passed 129 tests; the five custom-panel
files passed 51 tests. Frontend type checking passed. On populated Chromium,
the selected model and catalog entries displayed Anthropic's mark through
OpenRouter; Builder panels animated with full motion and stayed static with
reduced motion. Keyboard tab activation still worked. The Playwright regression
checks both preferences and keyboard access.

## Shared picker layout

Picker marks use a shared 24px optical box around 16px checked-in logos. Model
catalog rows start at the logo; the selection check is at the trailing edge,
matching the shared Select. Builder, chat, saved profiles, eval configuration,
organization STT/TTS, channel transcription, voice/media capabilities and coding
settings share maker labels or provider rows. Coding settings preserve arbitrary
model aliases separately from the inheritance option.

The six-file picker batch passed 115 tests; four voice/schema files passed 155,
and the final TTS/coding batch passed 12, including the inheritance regression.
A final four-file batch passed 135 tests (counts overlap). Chromium confirmed
maker marks in selected and catalog rows, the trailing check position and both
motion preferences for tab activation. A captured model menu was inspected at
`/tmp/agenticos-ui-audit/model-picker-polished.png`.

## Stable dashboard scopes

Every dashboard scope shares the greeting/date/primary-action header. Personal
activity queries remain confined to Me. Descriptions reserve two lines; scope
navigation and filters share a row on wide screens and wrap on phones, with
organization-only arrangement controls beside the filters. Empty layouts keep the same header/navigation.
Scope/group changes animate only the content, honoring reduced motion.

All 50 focused dashboard/coding tests passed. Populated Chromium measured the
scope strip at y=152.5px for Me, Organization, Group and Deployment at 1440px,
and y=220px for all four at 390px. Reduced-motion scope content had no animation.
An additional Playwright regression checks wide/narrow geometry, animation
preferences and the shared greeting.


## Compact chat layout review

Development-only `/chat?layout=composer`, `header` and `floating` previews move
model selection into a compact control. Settings retain connections, coding
accounts, notification preferences and remembered approvals without repeating
the approval-mode selector already available through Agent rules. The regular
chat and production build retain their current layout pending selection.

The research compares eight applications using public product documentation;
see [chat layout research](chat-layout-research.md) for sources and tradeoffs.

The focused controls/model-picker batch passed 72 tests, including personal-key
agents, saved model overrides and the production guard. TypeScript passed.
Populated Chromium opened all three desktop variants and their model/settings
popovers, checked the editable composer, compact widths and absence of duplicate
permissions. A 390px floating-layout check found no horizontal overflow or API
5xx. No messages or paid model calls were submitted. The dashboard inline-filter
batch passed 39 tests and browser geometry checks in all four scopes.


## Second chat design review

The maintainer rejected the first placement-only options and requested complete
control compositions. Studio, Canvas, Command and Focus replace those temporary
options, with distinct grid arrangements and palettes. All retain the real file
menu, agent selection, Agent rules, model picker, direct context usage, settings,
dictation and the call/Send position. The normal chat and production remain
unchanged. The preview palette also reaches portal controls and restores on exit;
switching designs preserves conversation query parameters.

The first focused two-file batch passed 73 tests; further regressions cover direct
usage, preserved query parameters and palette cleanup. Chromium checked all nine
visible composer controls in each desktop composition without overlaps, opened
all four model/settings popovers and checked the phone + sheet at 390px. No
horizontal overflow or API 5xx was observed, and no messages or paid calls were
sent. An initial cold-start attempt timed out; the completed browser journey used
the warmed local server. An initial local typecheck was interrupted under workstation load; the final
commit hooks passed TypeScript, ESLint, formatting and copy guards. The final
controls file passed 41 tests, including palette cleanup. Full CI remains a
separate gate for the new commit. These remain review compositions,
with DOM/keyboard order to consolidate after selecting a final arrangement.


## Clean composer reference round

Minimal, Workbench and Compact replace the color experiments, following a live
Firefox review of Mistral Code and the maintainer's Codex screenshots. Existing
light/dark preferences remain intact. More controls sit behind + without removing
call, files, context usage, consent or personal account connections. Dictation
yields priority to Send as a draft appears; Workbench retains a disabled empty
Send. Quick model rows preserve profile suitability and permission gates.

The four-file input/controls/menu batch passed 119 tests. The final focus and
responsive-panel batch passed its two tests. TypeScript passed before the final
responsive adjustment; commit checks must reestablish it. A first mobile browser
check found the side panel clipped, so narrow screens now use a panel above the
trigger. The local preview stack was restarted after the workstation stopped;
browser fixtures use HTTP-only cookies and a real session re-read rather than
pre-marking a cached identity authenticated. No paid model, microphone or call
was submitted during reference inspection or browser checks.

Final browser verification passed all three designs at 1440px and 390px: editable
composers, empty/drafted microphone priority, Send, model selection, nested +
settings, call availability, files, usage and standing consent. All checked
popovers fit the narrow viewport; the desktop controls did not overlap. No page
errors or API 5xx occurred. The menu's responsive/focus regression file passed
three tests after the mobile fix. No messages, microphone capture or calls were
submitted.


## Minimal follow-up and filled conversation list

Four development-only Minimal variants place live consent, context and file
controls above the composer, in a thin top bar, in a persistent corner panel,
or behind a hover/focus handle with optional pinning. Touch exposes the controls
without requiring hover. The design-switching navigation was removed. Portalled
menus and slash/mention palettes share the preview surface and entrance treatment.
File panels overlay without pushing the composer and use transform/opacity motion.

The new-chat Inbox preview reads the same authorized suggestion and approval
queries as Inbox, prioritizes urgent topics, and links to its existing details.
It distinguishes loading, failure and empty states. Six deduplicated preview-only
findings were added for the existing local reviewer across their two memberships;
source keys resolve through the real Slack, Notion and GitHub MCP catalog. No
connection, approval or external action was created. The maintainer chose to keep
the current isolated database after discussing alternative local data sources.

Conversation lists measure available height and progressively open default date
folds. Resize observation is cleaned up; automatic expansion is not persisted.
Explicit project/date folds always win, including when an active thread changes.
A browser check caught that scrollHeight is clamped to the viewport height even
for short content; content geometry now distinguishes that case, and its regression
uses the browser's clamped scrollHeight contract.

Focused verification: 130 composer/controls/Inbox tests, 65 sidebar/measurement
tests, and 44 workspace-file tests passed. TypeScript and targeted ESLint passed;
copy guards and all documentation translation fingerprints passed. Chromium
checked all four variants at 1440px and 390px, including seeded Inbox content and
source marks, commands, model, files, draft behavior, viewport bounds and sidebar
fill. It found and verified the fix for a corner-panel collision with the mobile
New chat button. An earlier attempt was interrupted by the local Next development
server's heap-threshold restart; the completed run used the warmed server. No
messages, microphone capture, approval decisions or calls were submitted. Full CI
must still run on the final pushed SHA.


The maintainer selected Minimal for further iteration and stopped screenshot
capture. Its consent selector moved next to the model as an icon-only shield,
with distinct marks for follow-agent, ask-all and approve-all, and a warning
tone for approve-all. The existing accessible name, native tooltip and policy
gates remain. Four selector tests and targeted ESLint passed. No browser or
screenshot tool was run for this adjustment.


Minimal's follow-up puts Files directly after the agent and Chat controls beside
the shield. Context usage is an icon-only ring immediately before the model;
percentages remain in its details. The model chevron follows the popover state
and respects reduced motion. The focused selector/usage/controls batch passed
85 tests and targeted ESLint. These adjustments used no screenshot capture.


Minimal uses the same card surface for browser dictation, provider dictation and
voice calls, aligned with the composer rather than an inverse floating capsule.
Informational transcription notices keep the composer width and its rounded
border. Recording indicators, mute, push-to-talk, stop, cancel and end callbacks
remain intact; reduced motion is preserved. The five-file voice batch verified
164 tests after correcting the new test's event helper; targeted ESLint passed.
No screenshots, microphone captures or actual calls were made for this change.


## Main chat promotion

The accepted Minimal composition is now the default `/chat` in development and
production. Experimental URLs, variants, the discarded dock, CSS and translations
were removed. MainChatContext distinguishes the page composer from independent
embedded chat scopes; the latter retain their existing controls even when nested
under the main page. No screenshot or native browser tool was used for promotion.

The final five-file composer/context batch passed 119 tests; the separate
container integration file passed 75 tests. The earlier Inbox file passed three
tests. Targeted ESLint and translation fingerprints passed. TypeScript, ESLint, copy guards and the remaining commit checks passed on
`5a3f4b566`.


## Chat refinements and component-system inventory (2026-11-19)

The attachment menu exposes all available actions directly. Chat settings use
compact disclosure sections and account rows; Inbox topics use a unified list
with source identity, relative time, priority and a waiting count. Main-chat
Files and Usage remain visible but disabled before the first message; file
listing hooks also stay inactive. Embedded-chat behavior remains unchanged.

The menu/Inbox/controls/sheet batch passed 55 tests. The account and remembered
approval files passed 8 tests. The final files/usage batch passed 80 tests,
including regressions for disabling, no pre-message file requests and enabling
after history exists. Initial regression testing exposed a premature workspace
request; disabling its cloud/local hook input fixed it. jsdom emitted its existing
canvas/navigation limitations; these were not real microphone or browser runs.

[Component-system plan](component-system-plan.md) and
[static inventory](component-inventory.md) record all shared UI modules,
component directories and page routes, concrete inconsistencies, migration waves
and acceptance checks. The broad migration is planned, not implemented or
visually certified. No screenshots or Computer Use/Browser Use were used.

The final ChatContainer integration file also passed all 75 tests. Local
`/chat` returned HTTP 200 after the changes. Shared-account tests retained their
existing connection and revoke behavior. Full CI for the next SHA remains pending.


## Application-wide component migration (2026-11-19)

Implemented all migration waves in the [component-system plan](component-system-plan.md).
The [migration review](component-migration-review.md) separates source integration
coverage of all 101 page entry points/layouts from runtime samples and records
intentional specialized/brand exceptions. Baseline module counts remain in the
inventory; ChoiceGroup and NativeDisclosure now live in the shared UI layer.

Shared field/action surfaces, floating panels, menu rows, choices and tab triggers
now have common owners. All nine cmdk picker modules reuse row presentation.
The chat-route portal override and unused alternate glass surface are removed.
MoreOptions and SettingsSection retain form values through folding, return focus,
and reveal invalid required fields. All 61 original native details instances in
50 files now use the native-preserving disclosure component. Existing canvas,
streaming, media, credential and permission contracts remain at their owners.

Focused final batches passed: shared controls/files/period (60 tests, nine files),
form disclosures (18 tests, four files), specialized chat/editor controls
(210 tests, seven files), native-disclosure consumers (224 tests, eight files),
and cross-family choices/filters/forms (67 tests, six files). Earlier additional
model/table/account/sheet checks passed 136 tests in seven files. Counts overlap.
The first migration batches caught a missing picker import and obsolete class/
role assertions; corrected behavioral tests passed. Existing jsdom canvas and
navigation warnings were not live provider calls.

The first populated Chromium pass completed 15 cases without client exceptions:
core fields/menus at 1440/390px in light/dark, main-chat filters and disabled
pre-message controls, plus ten catalog/dashboard/settings routes without document
overflow. A final eight-case pass after the native migration verified keyboard
folding and preserved drafts, settled themes, popup focus restoration and coarse-
pointer field/summary targets of at least 44px. The What's new interstitial was
acknowledged only in the disposable test browser's local storage. No screenshots,
Computer Use/Browser Use, microphone capture or paid model runs were used.

Local frontend reloads were restarted after broad HMR invalidation caused login
requests to time out; direct backend login returned 200 and the final browser run
passed. The existing database and app configuration were preserved. Final commit
hooks and new-SHA CI are checked after this note is prepared.


### Composer uploads and gliding selection markers — 2026-11-19

Moved the attachment portal inside the composer. Safe pending images use local
object URLs owned by the upload lifecycle, released on completion, failure or
unmount. The shared compact file card shows a larger thumbnail and one spinner;
the toolbar no longer duplicates upload activity. Attachment count stays available
to assistive technology without extending the tray beyond the composer.

Background-topic read errors use a bounded expandable panel, preserve loaded tasks,
and disable retry during an in-flight fetch. Unsent chats show no task error panel.
Shared tabs, page tabs, dashboard scopes and segmented choices have one moving
selection marker, using scoped CSS anchors with measured geometry for unsupported
browsers. Native selected states and keyboard behavior are retained; resizing,
wrapping and hidden controls update the marker, and reduced motion disables gliding.

The final focused batch passed 131 tests across ten files. ESLint passed for all
changed components; TypeScript and documentation translation checks passed. The
first upload run caught jsdom's object-URL incompatibility; scoped browser API
mocks and explicit failure/unmount cleanup tests now cover that boundary. No full
coverage or e2e suite was run locally.


Restored Minimal's published starter cards above Inbox by removing the rule that
hid the entire hint grid and making quiet descriptions visible. Icon/title/prompt
mapping remains the published agent's configuration. Inbox and approval queries
now explicitly share a 30-second freshness window and 30-minute inactive cache;
refresh errors keep the cached content with a warning. Existing mutation
invalidation and account/organization cache clearing remain unchanged. Focused
starter/Inbox/query tests cover cache reuse, post-decision refresh and error
retention. No data or agent configuration was changed for this restoration.


The populated Chromium DOM pass verified pending local image previews, simulated
upload failures, and attachment containment at 1440px and 390px. Dashboard selection
moved from x=0px/47px width to x=67px/111px width; reduced motion reduced its transition
to the console's near-zero duration, with no client exceptions. No screenshots or
paid model calls were used. Starter/Inbox/cache tests passed 42 cases in five files.

Three model-picker design previews are available only under `/dev/model-picker`
(`variant=list`, `library`, or `command`). They read available workspace models and
support search/local selection, but do not create profiles or change agents/chats.
The production model picker remains unchanged pending the maintainer's selection.
Four preview interaction tests passed, plus two marker lifecycle tests, including
a strip that only mounts after the available dashboard views have loaded.


The three model-picker previews passed populated Chromium DOM checks at 1440px and
390px, including search/local selection and no document overflow. The same browser
pass confirmed the restored starter grid is visible in main chat. No client
exceptions, screenshots or live model calls occurred.


### Selected provider-library design and welcome layout

The maintainer selected variant B. Temporary preview routes/components and their
copy were removed. Main chat now uses the provider library directly: connected
providers sort first, names start with uppercase and every provider uses its shared
brand mark. Models and Saved models are separate accessible tab panels. A row
selection applies through the existing profile creation/reuse/validation path; the
legacy nested picker and apply button are gone from main chat. Embedded pickers
retain their existing presentation and contracts.

Credential creation reuses InlineSecret, ChatGPT sign-in and AddSecretDialog for
structured credentials. No new secret transport, storage or readback was added.
Provider listings refetch after a credential is stored. Nested Vault dialog
interactions keep the parent picker open. Saved profile selection preserves the
exact profile id and its custom endpoint, rather than guessing by model name.

Welcome uses a 960px maximum composer, original animated workspace artwork and
simple starter rows above the composer, with Inbox below. Microphone color and
Send reveal transitions share a 220ms eased timing; reduced-motion overrides remain
in force. Focused model/profile/credential and welcome tests passed (110 cases in
four files, then 78 cases in six files, overlapping). No paid runs were made.


The final populated Chromium pass confirmed the requested home composition:
960px composer at 1800px viewport, prompts above it, Inbox below, visible original
animated artwork, and the 220ms Send reveal. The model library fit both 1800px and
390px views after the floating panel settled, exposed Saved models separately,
had no apply button, and opened inline API-key and structured Vault forms without
closing the model picker. No client errors or credential/profile writes occurred.

Direct selection uses the clicked model ID, never a stale draft. Failed creation
retains the actual current selection. A saved profile retains its exact ID and
endpoint. Credential-read failures block changes and show retry instead of labeling
unknown providers as disconnected or offering a duplicate key. Tests cover these
boundaries. Browser validation waits for responsive floating-position updates;
an initial immediate measurement during viewport resizing was premature.

### Note follow-ups and CI compatibility (2026-11-19)

- 72 focused dashboard/period/improvement tests, 190 picker/sidebar/catalog tests, 87 filters/sidebar tests and 57 editor/Architect/catalog tests passed. Widget subscription: 46 tests passed. TypeScript clean.
- Enabled cmdk rows now retain pointer events when `data-disabled="false"`; Radix disabled attributes still block actions. Headless DOM confirmed `pointer-events: auto` and an actual row click, with no client errors. No screenshots.
- Updated mobile and voice journeys for the chosen compact composer (agent remains in the composer; attachments and call in +). Full CI rerun remains required.
- New-agent Architect action opens the existing widget without prompt submission. Disclosure headers and capability image cards use surface feedback instead of shrinking. Light-mode variables use dark ink on a pale violet background.

### Conversation search and agent layout previews (2026-11-19)

- Add a bounded `/conversations/search` adapter to the existing indexed message search, gated on agent reading. Keep the service’s transcript access checks and plain-text excerpts. Combine title and message results without duplicate threads; keyboard navigation, safe highlighting and retry in the dialog.
- API: 5 tests passed; service/security-marker batch: 16 existing tests passed; existing full-text repository integration: 25 tests passed against an isolated local test database; route inventory passed. Scoped Ruff and ty passed.
- Frontend: 142 hook/catalog tests and 2 search-dialog tests passed. Widget: 47 tests passed, including preserving its unsent draft when opened without a prompt. TSC, ESLint and the copy guard passed.
- Six development-only agent-card/Build previews are available under `/dev/agent-designs`; editable values remain local. No production agent layout is selected yet.
- Headless DOM: all six pages, outline expansion and section navigation worked; local message search returned HTTP 200 with five hits; no client errors or screenshots.

### Full-CI follow-up

- All four component shards passed on `c0d181a5a`; the aggregate exposed three uncovered paths rather than a behavior failure. Add meaningful coverage for opening Architect without a prompt, revealing an invalid collapsed service field and measuring a padded/full chat list. Nine service/list tests passed; the widget regression is included above.
- Update the E2E period preset role. The workspace scroll fixture now includes a first user turn because empty-chat Files controls are intentionally disabled. No model is invoked by that fixture.
- Phone E2E found the agent selector squeezed to 22px wide. Main-chat phone controls now use two short rows; headless touch DOM measured the agent at 220×44px before/after typing, with no horizontal overflow and a working + menu. No screenshots.

### Access review correction

- Tracing search through `readable_by` and `ConversationService._may_read` found an internal workflow transcript could match through project access although ordinary transcript reads refuse it. A real-database regression failed before the correction.
- Exclude `origin=workflow` in the shared search predicate, retaining null origins with `IS DISTINCT FROM`. All 26 search repository integration tests now pass; both listing and single-result reads use the same predicate. No schema change.

### Selected resource cards and Builder sections

- Apply profile cards A through a shared ResourceCard frame to agents, tables, workflows, knowledge bases, projects, datasets, MCP, skills, context, Apps and groups. Keep domain actions, access controls and document previews. Loading skeletons reserve the same layout.
- Apply Builder B: one panel of native collapsible settings. Model starts open; editors stay mounted and Voice deep links reveal their section.
- Scoped suites: 83 card tests, 69 Builder/Voice tests, 164 gallery tests, 66 section/sidebar tests and 60 workspace/save/publish/starter tests passed (overlapping suites). TSC and scoped ESLint passed.
- Reproduce a 2px workspace-file overflow with 120 long filenames in headless Chromium: 286px available / 288px child. The child now fits its parent: 286px / 286px. No screenshots or provider calls.
