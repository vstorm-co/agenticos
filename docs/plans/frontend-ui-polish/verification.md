# Console interaction polish — verification

Date: 2026-11-18. Base implementation: 1.82.2.

## Scope

This change applies shared interaction rules throughout the existing console,
then fixes concrete exceptions in chat, Inbox, authentication, organization
services, setup wizards, dashboard tips and mobile gestures. It retains the
console's neutral palette, typography, permissions and existing save behavior.
Default AgenticOS instructions and capabilities are a separate final phase;
this patch does not change them or cut a release.

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
  system cancellation and respect reduced motion. Pull resistance increases
  beyond the refresh threshold; pending refreshes cannot be duplicated.
- Swipe decisions read the live motion value rather than a possibly stale React
  render. A new disabled or rejection-only restriction is checked again on release.
- Inbox previews retain the action/subject/requester hierarchy. Redacted calls
  never expose context or arguments. Bounded serialized search requests may
  supply a readable subject; opaque UUIDs and arbitrary JSON do not become titles.
- Draft previews retain inert images and never evaluate raw HTML. Copy keeps the
  original source. Version selection stays accessible when revisions disappear.
- Only credential refusals mark the password invalid and trigger a shake. Inline
  errors remain available with reduced motion, input is preserved, and provider
  outages are not presented as incorrect passwords.

## Local checks

- 293 tests across 27 explicitly selected unit/integration files passed. No full
  application test suite was run locally.
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
