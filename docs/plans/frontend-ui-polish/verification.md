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

The selected 22 capabilities are now explicit in the shipped AgenticOS template.
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
- Assistant eval scoring and execution were checked with TestModel. An explicit
  optional AgentDojo environment passed four offline tests, including its actual
  runtime and upstream utility scorer. No paid quality benchmark was run.

The populated preview uses a copy of the existing local database. Its historical
migration branch differs from the current repository, so additive compatibility
changes were applied only to that disposable copy, retaining its data and legacy
columns. This preview is not evidence of an upgrade from that old branch; the
canonical migration round-trip above uses the separate current-schema QA database.
The preview's API does not run a worker or submit scheduled/model work.
