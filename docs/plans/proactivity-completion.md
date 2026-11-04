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
| Outcomes | Runtime/source/delivery incidents, resumed terminal callbacks, ordering/retry guards and automatic recovery; monthly budget-pause notices and automatic case recovery; shared finding/Inbox/chat settlement, explicit restore without resending, acknowledged findings excluded from briefings; live per-routine e-mail/push limits inherited from personal preferences, quiet monitoring versus requested no-change reports, retry-safe report activations | Automatic-stop escalation policy and remaining channel integration (private Slack/Telegram/Mattermost/Teams/SMS/iMessage notification routes implemented; external continuation remains) |
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


## iMessage / BlueBubbles — implemented

The Mac bridge now implements the existing channel contract: text, files,
optional Private API tapbacks, separate private/group context, linked primary
conversation continuity, numbered approvals and explicit private notification
routes. The console can configure its endpoint/password and register its webhook;
unsaved credentials block registration. Migration `0274_imessage_notifications.py`
expands exposure and notification channel checks without enabling any opt-in.

The bounded webhook authenticates a separate vault-sealed Basic credential before
reading its body and dispatches through the ordinary channel handlers after
commit. Incoming self echoes, system events and tapbacks cannot start a turn.
Bridge HTTP requests and downloads have a 30-second total deadline, bounded bodies,
no redirects and credential-free client-visible URLs; only the wire transport
adds the bridge's mandatory query password. Unknown send outcomes remain failures,
not automatic retries. Provider acceptance is distinct from recipient acknowledgement.

Verification includes 108 focused receiver/notification/coverage checks and a
154-test regression batch covering the bridge contract, shared history, source
attribution and routine channel selectors. The new receiver service and route
have 100% statement/branch coverage. Console configuration/notification tests,
backend lint, migration down/up/model-drift checks and four-language docs are
checked locally. No live Apple account was contacted; a real company Mac remains
an operator acceptance check.

Primary protocol evidence was read from BlueBubblesApp/bluebubbles-server on
2026-11-03: API v1 message/webhook validators, routers and serializers, query-only
auth middleware, webhook dispatch and URL guard. The API currently supports no
custom webhook headers. Register the callback URL with Basic Auth userinfo so
Axios sends an Authorization header rather than putting its callback credential
in the request URI; `webhook_secret` stays separately vault-sealed. BlueBubbles
allows userinfo in webhook URLs. Preserve callback ownership when deleting hooks.

Reuse the existing Teams-style ephemeral credential envelope pattern to carry
bridge endpoint, bot UUID and callback secret beside the decrypted API password;
this avoids global mutable endpoint state or widening every adapter signature.
No new dependency or provider upgrade is authorized. Basic text/attachments use
AppleScript with a fresh tempGuid; tapbacks require the optional Private API and
must never decide an approval. Numbered prompts use existing shared sms_prompts
under the imessage namespace. Group membership needs live bridge confirmation.
Inbound self echoes, receipts, reactions and ambiguous/malformed chat scopes must
not become ordinary agent turns. Files are fetched only from the configured
bridge by bounded, encoded attachment GUID; do not follow arbitrary media URLs.

Still required: workflow/table presets and durable matching
reply/deadline follow-through; broader stop/escalation policies; decision episodes
with the actual open Improve PR #2172; Twilio PSTN/contact/quiet-hours/budget/call
cards; remaining routine-wide source ceilings. Continue in PR #2606, no CI polling.


## Automatic pause and escalation — implemented

Migration `0275_routine_health.py` adds owner-configurable execution failure limits
and bounded activation observations. Root terminal callbacks, stale-run reaping
and validated watch/source outcomes feed the same policy; parked work and
delivery failures are excluded. Parent locks plus immutable activation keys keep
duplicates and out-of-order completion from inflating the streak. Explicit resume
or a policy change starts a fresh epoch. Pausing updates the existing owner
incident and the shared notification paths; acknowledgement is not recovery.
The console exposes limits and automatic-pause state. Observation metadata is
owner-scoped, included in bounded export and removed by parent/owner cascade.
Local checks passed: 111 policy/incident/export tests, 136 notification escalation
and routing tests, 49 runner/create/read checks, 15 explicit resume checks and 29
console tests. The three new health modules have 100% statement/branch coverage.
Postgres checks cover concurrent workers, out-of-order completion, bounded
retention, export, cascades and explicit-null configuration. Automatic pause
supersedes the earlier Inbox notice for the same case and uses only the current
pause's opt-in deliveries; acknowledgment suppresses escalation without resetting
execution health. Safe Slack refusal waits can be cancelled without violating the
retry-state check. Migration down/up/check has no model drift. Backend lint,
frontend typing/i18n/ESLint and strict documentation build passed.

Other remaining feature blocks listed above still require implementation.

## Durable mail reply expectations — implemented

`flow.await_reply` uses existing workflow dispatch timers. Account and consent
generation, exact provider thread/sender, optional RFC anchor and original deadline
persist across wakes. Authenticated replies before the deadline win; unreadable,
oversized or revoked mailboxes cannot produce a no-reply verdict. The run page
shows state and permits authorized pause/correction without changing the mailbox.
Existing cancellation, duplicate dispatch protection and storage quotas apply.
Project/table and follow-up creation presets remain required in this block.

## Workflow notification channels — implemented

`notification.send` now selects in-app, email, push, Slack, Telegram, Mattermost,
Teams, SMS and iMessage through the same notification center as routines. The
workflow chooses channel ceilings, never another person's opt-in or destination.
Current membership/workflow access, preferences, private route consent and delivery
checks remain required; six real-database refusal tests verify that selecting a
private channel alone queues no delivery. Existing graph configurations still load.

## Await-reply creation preset — implemented

The workflow template library creates a private validated five-step graph against
an explicitly selected existing mailbox. The Run form collects thread, sender and
ISO timestamps; the two exclusive branches either finish with the verified reply
or create one review/follow-up reminder. No table, model, outbound mail or new
provider authorization is provisioned. Project task-table/routine presets remain
required. Full-graph validation also corrected the await node's branching kind and
introduced a validated adapter for text inputs from the form.

## Routine source ceilings — implementation resumed

Migration 0276 is now wired into creation, source review, metadata admission,
provider polling, canonical queue jobs, offline intents, root assembly, tool
checks and parked-run restoration. Reviews retain exact account generations,
normalized MCP aliases, cached tool ceilings, pinned delegate sources and remote
A2A endpoint/card/credential bindings. Model/instruction-only publication may
follow; new source authority requires the console owner's explicit review.
Legacy routines receive no migration opt-in. Re-review invalidates old jobs and
runs instead of lending them later authority. Mailbox places are filtered by the
account/review admitted before provider reads. Unknown/unavailable sources cause
an explicit refusal and the existing attention case, without fabricating a check.

The consent dialog contains the source/account inventory and separately retains
standing action exceptions. Added an optional owner-control onboarding stop.
Owner export includes bounded review metadata; account erasure clears retained
routine/run authority JSON before SET NULL can orphan the actor identity.

Validation: the routine/privacy batch passed 438 checks and exposed one new
mailbox fixture with a missing non-null schedule discriminator; that fixture was
corrected. A subsequent 105-check batch passed assembly,
portal-poll, native wait and source regressions. Final source/route/coverage gate
batch: 49 passing checks, with both new backend modules at 100% statements and
branches. All 261 focused console/onboarding checks pass. Backend lint,
TypeScript, scoped ESLint/i18n, migration downgrade/upgrade/model-drift checks
pass. Live provider accounts are not used.

Still required in this original PR: project task-table/routine creation preset,
automatic follow-up drafting, scoped decision episodes/actual Improve handoff,
Twilio PSTN/contact/quiet-hour/rate/budget/call-card implementation. After all
implementation blocks, request five sequential `@codex review` rounds through PR
comments and address confirmed findings. The maintainer explicitly resumed work
and continues to request one agent, feature delivery and no CI polling.


### Project tracking preset

Implemented explicit source review and publication, a private agent copy, task table with four saved views, fixed project binding and idempotent setup. Project access and workspace identity are checked before tools; queued outcome notices recheck project visibility. Setup is available on the project page and through onboarding. Automatic email follow-up drafting, structured decision episodes/Improve and PSTN remain in progress.
