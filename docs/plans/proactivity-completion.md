# Proactivity, memory and channels completion

Requested 2026-11-02. Continues PR #2606 against the contracts in #2575,
#2090 and #2082. This is an implementation checklist, not a statement that
unchecked behavior ships.

## Acceptance and delivery order

- [ ] Repair SMS prompt allocation, claim erasure/sharing/authorization,
  effective-date mutation guards and existing private-channel continuity.
- [ ] Execute watches through their selected agent, with published-version
  following/pinning and bounded approved sources.
- [ ] Create and manage watches/recurring work through the same chat/UI flow;
  retain source conversation, end time and existing routine identities.
- [ ] Persist action-specific unattended authority and device-specific grants;
  recheck permissions/revocation and expose offline waiting.
- [ ] Connect workflows/tables to durable awaited-event/deadline follow-through;
  cover restart, cancellation, matching replies and duplicate effects.
- [ ] Apply shared outcomes and notification preferences/overrides to routines;
  distinguish quiet monitoring, requested reports and explicit failures.
- [ ] Extend scope-bound memory capture and decision episodes; connect evidence
  to the existing Improve flow without publishing generalized rules automatically.
- [ ] Add Twilio inbound/outbound voice using the existing realtime path,
  authorized contact policies, scheduled reports, limits and conversation cards.
- [ ] Complete channel attachments/approvals and operator migration guidance.
- [ ] Validate focused tests, local lint, migration contracts and CI on the
  resulting SHA; update documentation and translations with behavior changes.

## Boundaries

Routes delegate to services and repositories. Existing Postgres jobs/workflow
execution own durability; tables and narrative memory never become job queues.
Provider transport remains in channel adapters. Models do not grant authority.
No merge or production deployment is part of this implementation authorization.

## Dependencies and verification

PR #2172 is still open at task start. Build against its actual Improve contract
before integrating evidence; do not introduce a parallel optimizer. Desktop/mobile
and workflow prerequisite deployment is not established merely by issue closure.
Provider tests use deterministic fakes unless a dedicated test account is available.

## Implemented increments

| Area | Implemented | Still required |
|---|---|---|
| Review defects | Claim scope/erasure guards, effective dates, atomic numbered replies, one-time verified private-thread backfill; bounded inbound/outbound MMS, media-only messages, explicit file/chart delivery with expiring copies; operator upgrade/rollback guidance | Wider channel approval coverage |
| Selected agent | Selected-agent watches through the shared runner, immutable pins/environments, approved account/tool/knowledge/context ceilings, in-flight revocation, authorization-generation fencing across OAuth re-consent and explicit source re-review for old policies | Routine-wide approved source ceilings beyond read-only watches |
| Chat management | Trusted private-chat provenance, routine/watch source delivery, live destination authorization, durable source-chat delivery after approval/question resume, explicit unavailable-delivery status and management cards, shared global/agent watch forms, MCP end/budget controls and end-time form control | Complete responsibility flow and remaining external-channel continuation |
| Standing authority | Version/intent-bound capability and account-specific MCP action consent, per-call audit, default action approvals including local writes and delegation; admitted MCP accounts and aliases retained across resume/delegation; immutable-pin consent and live routine/actor/run-grant checks before root, delegate and resumed tools; persistent native routine/device/folder/operation grants and durable offline admission | Bounded source authority beyond read-only watches |
| Follow-through | Existing workflow engine retained as the durability owner; independent minute-based end cleanup, including paused routines/watches and long cadences | Event/deadline presets, matching replies, restart/cancellation/idempotency acceptance |
| Outcomes | Runtime/source/delivery incidents, resumed terminal callbacks, ordering/retry guards and automatic recovery; monthly budget-pause notices and automatic case recovery; shared finding/Inbox/chat settlement, explicit restore without resending, acknowledged findings excluded from briefings; live per-routine e-mail/push limits inherited from personal preferences, quiet monitoring versus requested no-change reports, retry-safe report activations | Automatic-stop escalation policy and remaining channel integration (private Slack/Telegram/Mattermost/Teams/SMS notification routes now implemented; iMessage and external continuation remain) |
| Memory | Admitted audience retained in jobs, scoped channel/routine capture, erasure serialization, no false starter-version attribution | Decision episodes and Improve evidence integration with #2172 |
| Voice | Existing realtime path retained | Twilio inbound/outbound PSTN, transfer/contact policies, limits and source-chat cards |

Completed increments are not acceptance of the whole area. The PR closing references name its intended full scope. Do not merge while these gaps remain.

## Current continuation — 2026-11-03

The user requested all six remaining feature blocks and notification delivery through every supported channel. Explicit per-organization private Slack/Telegram/Mattermost/Teams/SMS routes now use existing transports and the shared notification queue, current preferences/outcomes/access checks, immutable route/account/bot grants and one durable attempt for unconfirmed chat submissions. Confirmed Slack HTTP 429 refusals now permit bounded delayed retries. E-mail/push retain existing setup and retry semantics. Other unchecked acceptance work above remains required in PR #2606.

## Native routine grants and durable offline admission — implemented

Native consent now binds server origin, paired owner/session, organization,
routine, canonical folder and read/write/execute operations. General chat folder
grants never authorize a routine; execute requires write. Account changes clear
grants, and desktop settings list and revoke them. The form creates paused,
confirms the actual UUID natively, attaches its grant and activates; cancellation
and HTTP failures retry the same prepared row. Organization/account changes or
unmounting cannot activate a setup after its native dialog returns.

Public device identity comes from the paired server's access JWT (refresh tokens
have no session ID), in separate keychain metadata fingerprint-bound to the raw
refresh credential. Native operations require an explicit work context and check
the exact current grant on every operation. Old clients/workers fail closed.
Published Sandbox authority is retained rather than auto-enabled. Folder grants
exclude full-computer, browser, screen, local model and MCP-service authority.

Migration `0272_routine_device_waits.py` adds canonical pre-model activations.
Distinct incoming events keep their body and activation ID; scheduled/manual
waits coalesce. The existing minute sweep and Postgres queue wake the same
activation, with active job deduplication and parent-first locking. Admission is
marked after final workspace readiness and commits with the run before the model.
An offline race rolls back its empty uncommitted run. Started work is never
replayed as another run. Task/grant/owner/pause/end changes cancel and redact old
waits; an old refusal cannot disable a newly repaired routine. Three dead/missing
pre-admission dispatches stop the routine and retain the failed event for review.

Run policy captures the native-target hash for resume and delegation. Local
workspace identity is restored from the original routine owner, never the
approver. Live routine checks re-read target authority and device revocation.
The routine list and dashboard show pending counts and refresh local routine
state. Owner export includes bounded wait data; finished rows follow run-history
retention, while active offline work remains pending. User/org/routine erasure
cascades. Desktop and data-protection documentation is updated in four languages.

Verification includes real Postgres queue/offline/reconnect/cancel/failure-bound
and rollback-race cases, live/delegated authority revocation, two-phase console
creation, cross-organization/unmount refusal, native persistence and finite IPC
allowlists, migration downgrade/upgrade and model-drift checks. The four new
backend modules and new native bridge/hook have 100% statement/branch coverage
in focused runs. Full suites and CI polling are deliberately not run locally.

After this vertical feature, continue all remaining blocks, including workflow
reply/deadline follow-through, stop escalation, decision episodes with the actual
Improve PR #2172 contract, Twilio PSTN voice, iMessage and Slack notification
acceptance. Slack notifications now use bounded plain-text blocks and a canonical shared-case
link, with documented private destination policy in four languages. The SDK makes
one explicit submission. A confirmed HTTP 429 refusal permits up to five total
claims after Retry-After; each claim clears retry authority before I/O and each
deferral retires the old handoff token. Timeout/crash/unknown outcomes remain
terminal. Existing send-time resource/outcome/preferences/route checks apply on
every retry. Migration `0273_notification_safe_retries.py` defaults old rows closed.
iMessage and the other outstanding integration blocks remain required.
