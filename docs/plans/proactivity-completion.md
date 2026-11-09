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
- [x] Address the existing Codex review findings. On renewed request, complete
  five sequential `@codex review` rounds on the original PR (all five reviewed; final corrections verified below).

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
The SMS webhook also bounds reads before signature work. The maintainer initially
deferred additional reviews for manual acceptance, then explicitly requested five
new sequential rounds on 2026-11-04. The earlier review above is historical and
does not count toward those five.

Existing earlier review findings also receive bounded streamed e-mail admission
and queue-level serialization for budgeted routine fires and memory extraction.
Focused verification: 148 checks including real queue concurrency contracts.


### Renewed five-round review

| Round | Request comment | Reviewed head | Result / correction |
| --- | --- | --- | --- |
| 1 | 6637015225 | `2cd0a5990` | Six code/security findings; fixed in `8eaf63042` |
| 2 | 6637730841 | `8eaf63042` | Interactive telephone admission; fixed in `37bdd4728` |
| 3 | 6637978995 | `37bdd4728` | Seven code/security findings; fixed in `5686388b1` |
| 4 | 6638576699 | `5686388b1` | Five code/security findings; fixed in `1cb94cdff` |
| 5 | 6639173680 | `1cb94cdff` | Three code/security findings: durable reaping, dial cancellation, SMS credential rotation; corrected in the final follow-up |

Confirmed findings receive regression coverage and an individual reply before
resolving their PR conversation. Round four verification includes 141 real-database
tests for routine authority, action consent, personal export and telephony;
164 focused email, account-deletion, organization and export-route tests;
and 61 final consent/lock-order checks. Backend lint, type checks and the strict
four-language documentation build pass. These are scoped local checks, not a
claim that every CI or live carrier acceptance check has run.

Upgrade the API and workers together after draining old workers. Apply migrations
through `0285_member_proactivity.py`; it adds the member concurrency limit shared
by watches and nightly jobs. Legacy mem0 bindings must be inventoried and their
remote data explicitly erased before `0248_drop_mem0_bindings.py` can proceed;
the migration refuses to discard retained cleanup mappings.

The local acceptance environment uses the populated `agenticos_growth_demo_pr2606`
clone, leaving the original database intact. Automatic watches remain disabled;
telephone and BlueBubbles live-provider acceptance remains with the maintainer.
The agent/team todo-table concept remains a design discussion, not another task
engine implemented in this change.


Round five produced two code findings and one security finding, all confirmed.
Cleanup now commits the ending state and releases row locks before provider IO,
then reloads the receipt without overwriting a terminal signed callback. A dial
accepted after cancellation immediately finishes its retained stop intent. SMS
credential replacement uses the same organization fence and unfinished-call
check as deletion, before locking the bot row. The instruction fingerprint also
includes skill-resource identity so deletion/recreation cannot restore an old
exception. Final focused verification includes 25 telephone integration tests,
47 action-consent regressions and 121 transport/channel tests. Real provider
acceptance remains manual. Five requests completed; review is evidence against
known defects, not a guarantee that no further defect exists.


## Subsequent starter work-tool defaults — 2026-11-04

AgenticOS, Architect and newly created console agents now include command
monitors, durable background topics, temporary background tools, five-result
conversation search and portable local BM25 tool search. Both starters include
research/explore/review specialists, dynamic specialist creation and auto
sync/async mode. Computer use, browser and coding tools are AgenticOS-only
starter defaults and use an explicitly approved paired desktop; other agents
can still opt into them. Existing models and custom prompt/tool choices remain
protected during shipped refreshes. The local demo's custom starters were
explicitly enriched through the ordinary draft/publish API for acceptance.

AgenticOS receives the actual published Architect pin. Untouched pins refresh
with it, while a removed or customized pin stays protected. Optional
`allow_any_agent` discovery is off by default, scoped to the initiating member's
runnable published agents, and excluded from anonymous/unattended expansion.
Catalog versions survive an approval park; live membership/run permission is
checked before delegating. Explicit reviewed pins retain their existing contract.

The coding-account/profile and shared-project proposal is in
`docs/design/coding-accounts.md`; those new profile connections and private cloud
task environments are not implemented. Existing local desktop authentication
and tool-selected credentials remain the execution paths. Personal account
isolation must precede lifting the shared-sandbox subscription refusal.

Focused verification includes PostgreSQL starter install/refresh, grant/tenant
isolation and new-agent defaults, delegation execution/resume/refusal, bounded
history access, local coding validation and 100% line/branch coverage for the new
BM25 ranker. On this Python 3.15 environment, coverage needs the existing settings
module imported before starting pytest's tracer; untraced focused tests run
normally. This increment follows the five earlier cloud-review rounds; those
reviews do not constitute a review of this later feature increment.

Frontend implementation belongs to the parallel frontend task. This increment
only authored the capability-config translation entries before that handoff;
no later frontend source or layout changes belong to this backend increment.
