# Proactivity, memory and channels completion

Continues original PR #2606 for #2575, #2090, #2082, #2077 and #2236.
No merge or deployment is part of this implementation authorization.

## Implementation state — 2026-11-04

- [x] Repair claim scope/erasure/sharing, effective dates, SMS prompt allocation,
  bounded attachments and existing private-channel continuity.
- [x] Run watches through the selected published agent, immutable pins and
  reviewed source ceilings; retain authorization through delegation and resume.
- [x] Manage routines/watches from chat and console with source conversation,
  end time, budgets, outcome cards and explicit delivery failures.
- [x] Persist unattended action authority and native device/folder/operation
  grants; recheck revocation and queue durable offline admission.
- [x] Persist exact authenticated mail reply/deadline expectations in the existing
  workflow engine, with pause/correction/cancellation and duplicate protection.
- [x] Provide an await-reply preset and optional model-budgeted follow-up draft
  after a verified deadline. Save the draft for review without sending email.
- [x] Provide a project tracking preset: reviewed published sources, private agent,
  task table, saved views, project-bound routine and idempotent setup.
- [x] Stop repeated execution failures automatically and escalate through shared
  outcomes and currently authorized notification preferences/routes.
- [x] Support in-app, email, push, Slack, Telegram, Mattermost, Teams, SMS and
  iMessage notifications; use existing transports and current private-route consent.
- [x] Implement the BlueBubbles iMessage bridge, attachments, numbered approvals,
  separate private/group context, bounded webhooks and operator instructions.
- [x] Store bounded decision episodes in the existing scoped memory ledger,
  append corrections/outcomes and export explicitly reviewed Improve JSONL cases.
- [x] Implement Twilio inbound/outbound voice, spoken reports, verified contact
  opt-ins, quiet hours, rate/concurrency/cost ceilings, transfer allowlists,
  private transcripts, source-chat cards and dashboard receipts.
- [x] Restrict automatic calls to selected agents, important-case criteria and
  immediate or delayed unacknowledged-case delivery; cancel on shared settlement
  and retain event deduplication after short-lived receipt expiry.
- [x] Address the existing Codex review findings. Further rounds are deferred
  at the maintainer’s request so manual local acceptance can start.

## Authority and durable effects

Routes delegate to services; repositories flush rather than commit. Existing
Postgres jobs and workflow execution own durable work. Source policies capture
account authorization generations, normalized MCP aliases/tool ceilings, bound
knowledge/context, pinned delegates, external A2A and telephone route generations.
Old policies require explicit review. Revocation blocks queued, resumed and active
work instead of borrowing a later grant. Native consent additionally binds the
paired account/session, routine, canonical folder and finite operation set.

Existing notifications distinguish quiet monitoring, requested reports and failures.
Slack confirmed HTTP 429 refusals permit bounded delayed retries; unknown chat
submissions never automatically resend. iMessage credentials and webhook secrets
remain vault-backed. Shared outcomes retain acknowledgement and recovery semantics.

Telephone intent admission, submission and cleanup commit before external effects.
Idempotency and ambiguous-acceptance states prevent automatic redial after timeout.
Signed callbacks and single-use media claims bind the original route/account.
Inbound caller ID grants no member authority. Routine-origin calls may speak
reports, but cannot open an interactive session with broader source access.
Transfer consent, remaining duration and current contact authority are rechecked.
Prepared reports do not claim that a person heard them. Phone estimates reserve
rounded minutes and possible transfer legs separately from AI model budgets.

## Dependencies and acceptance limits

PR #2172 remains a prerequisite for the Improve dataset UI/optimizer. The reviewed
JSONL handoff matches its actual `DatasetCaseContent` and `dataset_files.parse`
contract at `cae0914f75c5a2b1106da178ae46f8e2062cdf94`. This PR does not duplicate
its optimizer or automatically publish generalized rules. Await-reply drafts are
workflow results; they do not create provider-side Gmail/Outlook drafts.

Provider tests use deterministic fakes. Real Twilio numbers/audio/voicemail,
transfers and billing, and a live Apple/BlueBubbles account, remain operator
acceptance checks. The maintainer explicitly accepts doing live Twilio validation
later. Telephone receipt history is bounded to 30 days; text conversations retain
the platform’s ordinary retention policy. Personal export/erasure includes new
consents, receipts, source reviews, health observations and decision episodes.

## Verification record

Each vertical increment has focused backend/frontend tests, typing/lint, translated
documentation and migration round-trip/model-drift checks. Earlier source/native/
health/iMessage increments achieved focused 100% module coverage. This is not a
claim that the complete PR coverage gate has run locally. Full suites and CI
polling are deliberately omitted in favor of focused verification and delivery.

Migrations: `0271_notification_routes.py` through `0279_telephony.py` (verify exact
intermediate filenames in `backend/alembic/versions/`; the migration chain is
canonical). Telephone verification includes real Postgres admission/idempotency,
revocation, unknown provider acceptance, signed callbacks, anonymous inbound media,
late receipt binding, transfers, cleanup, source fencing and personal export.


## Review rounds

Round 1 requested at `c9eb68afa` (comment 6631817110). Code review completed
with four confirmed findings; security review completed with one confirmed
A2A credential-fencing finding. Corrections retain telephone cleanup receipts
after agent deletion, reconcile signed terminal cost callbacks, count complete
claim export rows and deduplicate numbered SMS/iMessage presses. Vault credential
generations now invalidate reviewed remote-agent accounts on replacement.
The SMS webhook also bounds reads before signature work. Further rounds are deferred at the maintainer’s explicit request. Start the
local application and provide hands-on acceptance instructions instead.

Existing earlier review findings also receive bounded streamed e-mail admission
and queue-level serialization for budgeted routine fires and memory extraction.
Focused verification: 148 checks including real queue concurrency contracts.
