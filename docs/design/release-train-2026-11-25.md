# Release train: portability and console controls

Maintainer request, 2026-11-25. One eventual release, with reviewable dependent
PRs. No merge, release or production deploy is authorized at this stage. The
last branch in the stack must contain every preceding change for local testing.

## Work already in progress

PR #3299 (`codex/project-integrations-fixes`) is the base. Finish selectable
export/import and project behavior, desktop and mobile screenshots, and full
CI. Its current draft checks do not establish a full green CI run.

The durability work is implemented in `f16e4b1c8`: ZIP storage, transfer
journals, worker fencing, expiring uploads and reviewed application. Knowledge-base content,
workflow bundles and manually published delegate-version bindings are still
unfinished. The project file/execution architecture document records target
behavior separately from implementation.

## Additional reviewed changes

| Pull request | Requested change | Head inspected | State |
| --- | --- | --- | --- |
| #3388 | Clear phone/desktop safe areas in full-screen panels | `61de64d09563882c1931a1dbf60c5275251eb6e5` | Integrated as `0ea65872d`; 26 scoped tests pass; fixed i18n gate |
| #3383 | Reconcile a saved answer and live replay after socket loss; fixes #3382 | `21ed8d62e1c202e79718d98bc94e47472c4c4a0f` | Integrated as `1e0ae3cbc`; regression fixed; 458 hook/store tests pass |
| #3304 | Admit conversation-ID corrections to active async API runs, with a queued fallback | `1ace55d3da15cf8a2a6bcf412cd563d42140b8ff` | Integrated as `6fea54932`; 814 scoped backend tests pass; no new confirmed finding |

Recheck each head and existing findings before integration. Review is local;
posting comments to contributors has not been requested.

## New implementation scope

- #3300: per-role organization console presentation, personal overrides,
  approved MCP/Skill catalogs, product notices, dashboard defaults and preview
  as role. Presentation never grants access to a resource or changes RBAC.
- #3302: organization controls visibility of costs across chat, shared chat
  and delegation. Redact forbidden costs at the server boundary. Personal
  preference may hide an otherwise permitted cost, never reveal an
  organization-forbidden one. Continue recording all spend.
- #3303: configured sign-in methods only; optional deployment-level password
  disablement, consistent register/reset behavior and a documented operator
  recovery path.
- #3382: covered by the reviewed #3383 implementation, with any additional
  regressions found during review included in the same change.

## Acceptance evidence

Each dependent PR needs its own scoped tests and an accurate description. The
aggregate checkout needs real desktop/mobile UI checks and full CI for its exact
head. Do not close issues for partial implementations or describe skipped draft
checks as passing gates. Final merge and one version cut require a later request.

## Confirmed review findings

- #3388: five template-literal `className` expressions fail the repository's
  hardcoded-copy gate. Use the existing `cn` helper; do not suppress the gate.
  The safe-area source guard also reuses the existing source-files utility.
- #3383: an already saved question segment in run A can satisfy the run check
  when detached run B finishes during A's dropped continuation. Reproduced on
  the inspected head: the interruption notice clears prematurely. Snapshot
  saved segment IDs at socket loss and require a new segment of run A.
  Regression evidence: `does not mistake a saved question segment for its
  dropped continuation` fails before this correction.

Source #3388 and #3383 workflows require contributor approval; those statuses
are not evidence of passed CI. #3304 has successful CI and CodeQL at the
inspected head; the integrated train still needs its own checks.

## Integrated API steering verification

The #3304 patch applies on the #3299 queue changes without removing the generic
`lock_attempt` fence. Focused tests pass: 173 steering, transcript, channel and
route tests; 617 runner tests; and 24 real-Postgres request/delivery tests.
The delivery tests use `FunctionModel`, not paid provider calls. They cover a
correction arriving from an independent transaction, idempotent redelivery,
consumption before a later model step, and the final-step queued fallback.
Docs translation fingerprints and the bundled Architect guide match.

Steering remains opt-in. It requires an existing API conversation and the exact
agent, environment, person and credential of a live attempt. A changed grant,
revoked key, replaced version or expired lease leaves the correction queued for
normal admission. A consumed request is a terminal receipt pointing at the
original run; it does not produce a second answer. Operators must update API
replicas and workers before clients send the new flag.

## Provider-only sign-in (#3303)

Implemented on `codex/sign-in-method-policy`, based on #3431's integration
branch. Deployment administrators can disable local account admission after a
provider is configured. The six local login/registration/recovery/email-token
routes refuse admission at the server, including previously issued reset and
email tokens. Existing sessions and directory authentication retain their own
contracts. Public branding publishes configured provider names without secrets;
the console retains an explicit display filter and defaults to all supported
configured methods. Unconfigured Google is absent, not disabled.

The saved switch and the operator's temporary environment override are distinct.
The administrator sees both; public pages see the effective policy. A missing
provider refuses disabling local admission, and the console also checks the
visible filter. The recovery flag never creates an account or grants a role.

Verification: 190 focused backend tests (including PostgreSQL persistence), 92
UI tests plus the added staged-invitation check, and 100% scoped statement and
branch coverage for the provider registry and deployment-settings service. The
new provider-only UI has 100% statement, branch, function and line coverage.
Types, lint and strict four-language docs checks pass. Migration
`0368_password_sign_in_policy.py` upgrades, downgrades and upgrades cleanly;
Alembic reports no drift. Actual local console testing saved the switch and
checked login, registration, recovery and an old reset link before restoring
local login. Preview SSO is a local dummy provider, not a tested live IdP.

Desktop/mobile captures are available locally. The aggregate CI gate and the
remaining #3300/#3302 and #3299 work are still pending; no release is cut.
