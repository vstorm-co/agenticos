# Notification center — plan first (#1598)

A bell, an inbox and email delivery for events nobody is watching: approvals,
budget and security events, run completion and failure, ingestion, and
configuration changes. An app admin can also send an audited system
announcement. This plan follows the design-first practice this repository
already uses for a large change (see #1111): a written plan before code, so
the shape is agreed once instead of argued over in review comments.

The one-sentence design: **every event resolves to a durable per-recipient row
a person can read and mark read, each side channel off that row is a claimed,
retried delivery rather than a fire-and-forget send, what a row shows is
re-checked against the reader's current permission rather than frozen at
write time, and only a deployment app admin can address an audience wider
than one organization.**

## 0. What already exists

`NotificationService` (`backend/app/services/notifications.py`) is
email-only. It has four methods: `budget_exceeded`, `approval_requested` and
`agent_usage_report` are per-agent-lifecycle, and `usage_report` is the
organization-wide periodic digest. Each resolves an audience and calls
`EmailService.send`. `budget_exceeded` and `approval_requested` run inside
`AgentRunnerService.finish` (`backend/app/services/agent_runner.py:3401`,
`_notify`), which is called **before** the terminal `db.commit()` at line
4118, not after it — `finish` only flushes. `usage_report` and
`agent_usage_report` instead run from a Prefect flow
(`backend/app/worker/tasks/report_tasks.py`) against its own already-committed
session. A separate, mandatory email already exists outside this service
entirely: `EmailKey.IMPERSONATION_NOTICE` is sent straight through
`EmailService` from `services/impersonation.py`, gated on the deployment's
`notify_impersonated_users` setting rather than any per-user preference —
the existing precedent for a notice nobody can opt out of. There is no
in-app notification or inbox anywhere in the codebase.

**Audience resolution exists, but returns addresses already filtered by
preference — not identities.** `backend/app/repositories/member.py`'s
`list_emails_by_role`, `list_emails_for_members` and `list_app_admin_emails`
all `select(User.email)`, and all apply the `preference` column in the query
itself when one is given. `NotificationService._administrators`, `_deciders`
and `_audience` compose those into the role-based audiences an `AlertSpec`
names (`backend/app/agents/spec.py`, `AlertAudience`: `ADMINS`, `OWNER`,
`INITIATOR`, `CHOSEN`). None of the three returns a user id, and all three
already drop anyone who opted out of that one email kind. An in-app row
needs `recipient_user_id`, and Decision 4 needs in-app to survive an email
opt-out — so this plan cannot call these functions unchanged for the new
write path. See Decision 1.

**Preferences are three fixed boolean columns.** `User` carries
`notify_budget_alerts`, `notify_approval_requests`, `notify_usage_reports`
(`backend/app/db/models/user.py`), one per agent-alert kind, email only. There
is no per-channel toggle and no room for a new event kind without a new
column each time.

**`AlertSpec`/`NotificationSpec` are per-agent, by design.** They live in the
agent's own spec because the three alerts they cover — budget, approvals,
usage — are about that agent, and an exported spec must mean the same thing
in a different organization. Security events, ingestion and configuration
changes are not about one agent. This plan does not extend `NotificationSpec`
to cover them. See Decision 1.

**No security-event or configuration-change notification exists**, but the
audit trail already records the moments that matter. `record_audit`
(`backend/app/core/audit.py`) is called from `services/impersonation.py`,
`services/organization_secret.py`, `services/sandbox_connection.py`,
`services/deployment_settings.py`, `api/routes/v1/admin_users.py` and a dozen
more — every one of them a privileged or access-changing action. This plan
treats those call sites as the trigger points, rather than inventing a
separate detector. Some of them carry no `organization_id` at all —
`deployment.settings_updated` and both impersonation actions pass none, since
they are deployment-wide, and the column is nullable. See Decision 2.

**Ingestion completes through more than one worker-task path, but they share
one service boundary.** An upload completes through
`rag_tasks.py::ingest_document_flow` → `_run_ingestion`, which calls
`RAGDocumentService.complete_ingestion`/`fail_ingestion` **directly** — not
`_settle_document_row`, contrary to what an earlier draft of this plan
claimed. A local-directory or connector-source sync instead goes through
`_settle_document_row`, which calls the same two `RAGDocumentService`
methods on a per-file basis. `services/sync_source.py` is a different
layer — `SyncSourceService` manages sync *sources* (create/update/delete/
trigger), not per-document completion. A trigger point wired to
`_settle_document_row` alone — this plan's own earlier draft — misses every
upload. The shared boundary both paths actually call through is
`RAGDocumentService.complete_ingestion`/`fail_ingestion`, in
`services/rag_document.py`. That boundary alone still misses a failure with
no document row to attach to — a connector auth/network failure, or the
pre-download `BudgetExceeded` check in `_run_source_sync` — which instead
reaches `RAGSyncService.complete_sync` or `SyncSourceService
.update_after_sync`. See Decision 1.

**Permissions have three layers**, and only the first reaches across
organizations. `users.is_app_admin` (`CurrentAppAdmin` in
`backend/app/api/deps.py`) is a deployment-wide bypass with no membership
row. Every entry in `Perm` (`backend/app/core/permissions.py`) is resolved
against one organization through `AuthContext.permissions`, so no role, no
matter how senior, reaches a second organization through the permission
catalog. This is the mechanism the issue's "an organization admin must not
gain deployment-wide broadcast rights" rests on: the composer gates on
`CurrentAppAdmin`, never on a `Perm`.

**Background delivery has two existing shapes, and neither is a queue with a
claim.** In-process fire-and-forget: `app.core.background.spawn` /
`spawn_after_commit`. `NotificationService._send` uses plain `spawn`, called
from inside `finish` before its terminal commit (see above) — so today's
email already fires for a transaction that has not yet committed, and
`_deliver` discards the `SendResult` it gets back without checking
`.accepted`, so a provider rejection is logged and otherwise invisible.
Durable, retried work: a thin `@flow` calling a plain async function,
deployed on an `IntervalSchedule`. The only flow with explicit bounded
retries today is `teardown_tasks.py::external_state_cleanup_flow`
(`retries=3, retry_delay_seconds=30`), and it retries the whole flow, not
individual rows. The precedent for **claiming individual rows** so two
concurrent workers cannot both process one is
`repositories/agent_trigger.py::claim_due`: `SELECT ... FOR UPDATE SKIP
LOCKED`, plus a lease column (`fire_in_flight_since`, released after
`FIRE_LEASE`) so a worker that dies mid-row does not hold it forever. This is
the template for Decision 3's delivery sweep, not `approval_tasks.py`, which
only flips a status and claims nothing.

Deduplication's one existing shape is a Redis claim keyed on a caller-supplied
id (`backend/app/services/trigger_dedupe.py`): `SET NX` with a 15-minute TTL,
**fails open** when Redis is unreachable or unconfigured, and is never
released on failure — its own docstring says a duplicate costs money but a
drop is worse, which is the right trade for an inbound webhook and the wrong
one for a database write this plan controls. See Decision 3.

**Nothing exists for issue #1420** (retention). A search of `backend/app`
finds only narrow, unrelated retention constants on other features. This plan
does not depend on #1420 landing first. See Decision 8.

**No bell, inbox or cross-process push exists on the frontend.** The nearest
precedent is `frontend/src/components/branding/announcement-banner.tsx`: one
static, deployment-wide message, not per-user, not audited, not queued — the
opposite shape from an audited composer with explicit recipients. The only
WebSocket endpoints in the product are scoped to one agent run each
(`api/routes/v1/agent.py`, `api/routes/v1/embed.py`). No existing
channel pushes an event to whichever browser tab a given user happens to
have open.

## Decision 1 — one event catalog, code-defined, not agent-spec-owned

`NotificationEventType` (`StrEnum`) names every event this feature covers.
The mapping from event to producer, occurrence identity, default audience,
the permission its content is gated on, its channels and whether it is
mandatory is a table in code, not a form an admin fills in — the issue asks
for an "extensible event catalog and recipient rules", and extensible here
means a developer adds a row when a new event ships, the same way
`AlertAudience` values are fixed and reviewed, not user-invented. A
per-organization routing UI is real scope the issue does not ask for and
this plan does not add it.

| Event | Producer | Occurrence id (Decision 3's dedup key) | Default audience | Content gated on (Decision 7) | Mandatory |
|---|---|---|---|---|---|
| `budget_exceeded` | `AgentRunnerService.finish` | the run id | `AlertSpec` (unchanged) | — | no |
| `approval_requested` | `AgentRunnerService.finish` | the approval id | `AlertSpec` (unchanged) | current `approvals:decide` | no |
| `run_completed` | `AgentRunnerService.finish`, unattended surfaces only (not `WEB`) — the gap `docs/governance.md`'s Alerts section already names | the run id | `initiator` | — | no |
| `run_failed` | same as above | the run id | `initiator` | — | no |
| `ingestion_completed` / `ingestion_failed` | `RAGDocumentService.complete_ingestion`/`fail_ingestion` for a per-document outcome, or `RAGSyncService.complete_sync`/`SyncSourceService.update_after_sync` for a whole-attempt failure with no document row yet (a connector auth/network failure, or the pre-download `BudgetExceeded` check in `_run_source_sync`) | `(document id, ingestion attempt)` for the per-document case, `(sync log id \| source id, attempt started-at)` for the whole-attempt case — see Decision 2 | whoever started the sync or upload | current `collections:view` on the target collection | no |
| `usage_report` / `agent_usage_report` | `worker/tasks/report_tasks.py` | `(organization id \| agent id, period, window start)` | `AlertSpec`/`_administrators` (unchanged) | — | no |
| `security_event` | the `record_audit` call sites in section 0 | the `AppAdminAuditLog` id | `org_admins` when the entry carries an `organization_id` (`organization_secret.py`, `sandbox_connection.py`), otherwise deployment app admins (`impersonation.py`) | current owner/admin role in the row's organization, or current `is_app_admin` for an app-admin-audience row | yes |
| `configuration_changed` | same, for `deployment.settings_updated` | the `AppAdminAuditLog` id | deployment app admins (no organization — see Decision 2) | current `is_app_admin` | yes |
| `announcement` | the composer (Decision 5) | the announcement id | explicit, chosen by the sender | — | no |

`run_completed` is deliberately scoped to the surfaces nobody is watching —
the same distinction `NotificationService`'s own docstring already draws
("a chat run ... says so on screen; the same run started by a Slack mention,
a schedule or an API call stops silently"). A `WEB` chat run never produces
one. An inbox entry for every successful chat turn would be noise nobody
reads twice. `security_event` and `configuration_changed` are marked
mandatory as an extension of the same rule the deployment already applies to
the impersonation notice and to the organization's own budget cap
(`docs/governance.md`, "the organization's cap ignores the spec entirely") —
see Decision 4.

**Two failure classes need covering, not one.** A per-document failure
(a bad PDF, an embedding credential problem on one file) has a
`rag_documents` row to hang the event on. A whole-attempt failure does not:
`_run_source_sync`'s pre-download `assert_organization_within_budget` check
can raise before a single `_open_document_row` call, and a connector
auth/network failure can fail the same way — both land in
`SyncSourceService.update_after_sync(source_id, status="error", ...)`, never
in `RAGDocumentService.fail_ingestion`, because no document row exists yet
for either. `sync_collection_flow`'s own top-level failure is the same
shape, one level down, through `RAGSyncService.complete_sync`. A trigger
point wired only to `RAGDocumentService.fail_ingestion` — this plan's own
earlier draft — reports every failed file and stays silent about a sync
that failed to find any.

**The occurrence id for a per-document event is the document id plus the
attempt, captured when the attempt starts — not read back from a mutable
counter when it ends.** `RAGDocumentService.retry_ingestion(doc_id)` parses
the same document again under the same id — it is a resubmission, not a new
document — so a second failure would carry the same
`(recipient_user_id, event_type, doc_id)` as the first and the unique
constraint would silently drop the new notification, exactly when a person
most wants to hear that the retry failed too. `RAGDocument` gains a small
`ingestion_attempt` counter, bumped by `retry_ingestion` at dispatch time.
The counter alone is not enough, though: if `complete_ingestion`/
`fail_ingestion` read `doc.ingestion_attempt` at *settlement* time rather
than carrying it from dispatch, a slow attempt that finishes after a later
retry has already bumped the counter would settle under the newer attempt's
number — attributing attempt 2's stale result to attempt 3's occurrence id,
the same "who still holds the claim" problem Decision 3 already solves for
`notification_deliveries`, one layer up. So the attempt number is a
parameter threaded through the call, not a column read back: `retry_ingestion`
passes its freshly bumped value into `ingest_document_flow`, which carries
it through `_run_ingestion` to `complete_ingestion`/`fail_ingestion`, and
those methods write only when the passed `attempt` still equals the row's
current `ingestion_attempt` — a stale settlement is a no-op (logged), the
same as a delivery settling against a claim it no longer holds. The
occurrence id `(doc_id, ingestion_attempt)` is then always built from the
attempt the notification write is actually about, never from whatever the
column happens to say by the time the write runs.

**"Content gated on" is re-checked at both read and send time, for every
row that has one — not only `approval_requested`.** Decision 7 states the
general rule. The table above is what a developer adding an event consults
to fill it in. A row with no gate (`budget_exceeded`, `run_completed`,
`run_failed`, the report events, `announcement`) needs no recheck beyond the
tenant/membership check every row gets.

**The two report events carry no gate and no fresh-render step, because
their content is a window aggregate, not a permission-dependent fact.**
Decision 3 explains why re-deriving content at send time is right for
`approval_requested` and wrong for these two.

`AlertSpec`/`NotificationSpec` stay exactly as they are, unmodified, still
gating `budget_exceeded` and `approval_requested`'s audience and their email.
Those two events now also write to the new tables below, from the same
trigger point, migrated onto one delivery path rather than a second one
layered beside it — see Decision 3, which spells out why "also write" cannot
mean "also call `_send`".

*Rejected: extending `NotificationSpec` with the new event types.* An agent's
spec cannot reasonably declare who hears about a vault secret rotation or a
deployment-wide config change — those are not the agent's business, and
putting them in an exported, per-agent file would mean two unrelated
organizations' security teams reading the same YAML field name.

## Decision 2 — a notification is a row per recipient, separate from audit

New table `notifications`: `id`, `organization_id` (**nullable** — see
below), `recipient_user_id` (FK `users.id`, `ON DELETE CASCADE`: a hard-deleted
user's inbox goes with them, the same as their other owned rows),
`event_type` (`NotificationEventType`), `occurrence_id` (a string — the id
from Decision 1's table, composite ids joined with `:`, e.g.
`f"{doc_id}:{attempt}"` for ingestion or `f"{subject_id}:{period}:{window_start}"`
for a report), `summary` (plain text, pre-rendered at write time — never a
raw comment or secret value), `context_url` (nullable, built the way
`NotificationService._link` already builds one, with `?org=<id>` so the
reader lands in the right tenant), `render_context` (nullable JSONB — the
typed template variables an event's specific `EmailKey` needs, captured at
write time, see Decision 3), `in_app_visible` (boolean, the recipient's
in-app preference for this `(event_type, channel=IN_APP)` at write time —
see Decision 4), `read_at` (nullable), `created_at`. A unique constraint on
`(recipient_user_id, event_type, occurrence_id)` is Decision 3's dedup
guarantee, enforced by Postgres inside the same transaction rather than a
separate cache. Two indexes carry the two read patterns:
`(recipient_user_id, created_at DESC) WHERE in_app_visible` for the
paginated inbox, and a partial index
`(recipient_user_id) WHERE in_app_visible AND read_at IS NULL` for the
unread count.

`organization_id` is nullable because not every event has one.
`configuration_changed` fires from `deployment.settings_updated`, which
`record_audit` already writes with no `organization_id` — the setting is
deployment-wide, and its only audience is app admins, who hold no membership
row in any organization (section 0). A null-organization notification is
addressed to nobody's tenant context: `GET /notifications` always scopes by
`recipient_user_id`, and additionally excludes rows whose `organization_id`
disagrees with the caller's active organization only when that column is
set. A null-organization row reaches its recipient regardless of which
organization they currently have selected, the same way an app admin's
authority already is not organization-scoped (Decision 7).

One row per recipient, not one event row with a join table, because unread
count and read state are per person and the inbox reads by recipient every
time. Storing a pre-rendered summary, not a template key plus raw context,
keeps a later change to an event's wording from rewriting history, and keeps
a comment or file name that later turns out unsafe to display out of the row
in the first place — the summary is built once, at write time, by the code
that already knows what is and is not safe to show. An announcement's body
is not squeezed into this column: Decision 5 gives it its own table, and
`notifications.announcement_id` (nullable FK) is how one send's rows point
back to it.

**`summary`/`context_url` are what the inbox shows. They are not enough to
re-render `EmailKey.BUDGET_EXCEEDED`, `APPROVAL_REQUESTED`/`APPROVAL_PENDING`
or `USAGE_REPORT`, which is the gap an earlier draft of this plan asserted
shut without the field to back it.** Those templates need typed variables —
`agent_name`, `reason`, `total`, `runs`, `dashboard_url` and the like — that
two free-text columns cannot carry. `render_context` holds exactly those
variables, captured once by the same code that already builds them today
(`NotificationService.budget_exceeded`/`approval_requested`/
`agent_usage_report`/`usage_report`), so the send-time renderer (Decision 3)
has the real inputs those templates were always built for, not a
paraphrase.

**The row always exists. Whether it is shown is a separate, stored bit.**
Decision 4 lets a person turn in-app off for an event type while leaving
email on — but `notification_deliveries` (Decision 3) is a child of
`notifications`, so an email-only preference cannot mean "write no
`notifications` row" without leaving the email delivery with nothing to
attach to. The write helper always creates the `notifications` row (it is
also the dedup anchor, regardless of which channels end up active) and
computes `in_app_visible` once, from the same preference lookup Decision 4
already does for the in-app channel. The inbox listing, the unread count and
mark-all-read all filter on `in_app_visible`, so an email-only row exists,
dedupes and delivers exactly like any other, and is simply never returned by
any of the three read paths. `notification_deliveries` for the `EMAIL`
channel is unaffected by this column — it is created or not from the
*email* preference alone, exactly as already designed.

This is a new table, not a new use of `AppAdminAuditLog`. The audit log is
immutable evidence with no per-reader state. A notification is read, marked
read, and eventually purged. Different lifecycle, different table. Mixing
them would make the audit trail mutable or the inbox permanent, and neither
is acceptable.

The write happens in the same transaction as the triggering action, through
the ordinary repository/service pattern (`db.flush()`, the request's own
`DBSession` commits it). The row existing is the in-app delivery — nothing
further has to succeed for a person to see it in their inbox. Only the
side channels (email, and any future channel) are the part that can fail
independently, which is what makes Decision 3 necessary.

**A failure inside this write must not poison the caller's transaction.**
`AgentRunnerService.finish` calls its notification path inside a `try`/`except`
specifically so a notification failure cannot replace the run's own outcome
(section 0) — but that guard only catches the Python exception. A `flush()`
that raises (a constraint violation, a lost connection) leaves the shared
SQLAlchemy session needing rollback, and the outer `except` cannot undo
that: `finish`'s own terminal `db.commit()`, reached afterward, then fails
too, and the run it just finalized rolls back with it — exactly the failure
the guard exists to prevent, just one layer further out than the guard
reaches. The write helper therefore runs its insert inside a **savepoint**
(`async with db.begin_nested()`) when called from a context that cannot
afford the outer transaction poisoned — `finish` is exactly such a context.
A failure inside the savepoint rolls back to it, and the caller's
transaction proceeds and commits normally. **The savepoint's reach is
narrower than "any failure is now safe", and this plan states that plainly
rather than implying otherwise**: a `ROLLBACK TO SAVEPOINT` needs the
underlying connection and outer transaction still alive to roll back *to* —
a recoverable statement error (the constraint case, a data error) is exactly
what it isolates. A lost connection or a dead transaction takes the whole
request down regardless, savepoint or not, the same as it would for any
other write in `finish`. And because the savepoint's whole point is that
nothing gets persisted on this path, **the failure cannot be surfaced
through `notification_deliveries`** — there is no row, in either table, for
that query to return. It is instead a structured log line
(`logger.error("notification_write_failed", extra={"event_type": ...,
"occurrence_id": ...})`) at the point of rollback — an observable path
distinct from, not folded into, the failed-deliveries view Decision 3
defines for rows that *did* get written and then failed to send. Separately,
the dedup insert itself uses `INSERT ... ON CONFLICT
(recipient_user_id, event_type, occurrence_id) DO NOTHING` rather than a
plain insert relying on the unique constraint to raise — the duplicate case
this plan expects to happen routinely (a retried budget check, a redelivered
webhook) is then an ordinary no-op, not an exception the savepoint has to
absorb on every retry.

**Resolving who the row is for happens by identity, not by borrowing the
email helpers.** Section 0 already rules out `_administrators`/`_deciders`/
`_audience` for this: they return addresses pre-filtered by an email
preference, and this write must happen once per resolved *person*,
independent of any channel's preference. New repository functions —
`list_member_ids_by_role`, `list_app_admin_ids` — mirror the existing
`list_emails_by_role`/`list_app_admin_emails` shape but `select(User.id)`
and take no `preference` argument, since channel preference is applied per
channel afterward (Decision 4), not baked into who gets a row at all. The
existing email-address functions are unchanged and keep serving the
email-channel step described in Decision 3.

## Decision 3 — one delivery path, a claimed queue, and re-validation at send time

A new table `notification_deliveries`: `id`, `notification_id`, `channel`
(`NotificationChannel`: `EMAIL` today), `status`
(`pending`/`sent`/`failed`/`skipped`), `attempts`, `last_error`,
`claimed_at`/`claimed_until` (the lease). One row per channel a recipient is
due to receive the notification on, created in the same transaction as the
`notifications` row.

**Every email this plan concerns itself with goes through this table —
including the four existing agent-lifecycle emails.** Section 0 already
shows why "also write to the new tables, alongside the existing send" is the
wrong shape: `budget_exceeded` and `approval_requested` fire `_send`/`spawn`
*before* `finish`'s terminal commit, so a `notification_deliveries` row
created in the same transaction and queued through `spawn_after_commit`
would resolve to a second, independent send of the same fact on a different
schedule with a different failure mode — the exact duplicate-mail risk this
review caught. `NotificationService.budget_exceeded` and
`approval_requested` stop calling `_send` directly. They still resolve the
audience and build the `AlertSpec`-shaped list exactly as today. The
difference is that resolving an audience now ends in a
`notifications`/`notification_deliveries` write, not a spawned coroutine.
`agent_usage_report` and `usage_report` migrate the same way, from their
Prefect-flow context. `IMPERSONATION_NOTICE` stays outside this pipeline —
it is not preference-gated and has no inbox row to anchor a channel
preference to, and folding it in is not needed for anything this plan asks
for.

**Sending is a claim, not a poll — and the claim itself, not the outcome, is
what consumes the retry bound.** The sweep flow,
`notification_delivery_sweep`
(`backend/app/worker/tasks/notification_tasks.py`), takes rows the way
`repositories/agent_trigger.py::claim_due` already does: `SELECT ... WHERE
status IN ('pending', 'failed') AND attempts < max AND (claimed_until IS
NULL OR claimed_until <= now()) ... FOR UPDATE SKIP LOCKED`. The claiming
update stamps `claimed_at`/`claimed_until` **and increments `attempts` right
there**, not later when an outcome is recorded — the original shape of this
decision incremented on failure only, which meant a worker that sent the
email and then died before writing `sent` left the row looking exactly like
a fresh `pending` row once its lease expired, retryable forever without ever
tripping the bound. Incrementing at claim time means every claim — sent,
failed, or the worker never came back — counts toward the same limit.

**Counting the claim is not, by itself, a terminal state — the row still
needs one written for it.** A worker that dies on the row's *last* allowed
attempt leaves `attempts = max`, `status` still whatever it was
(`pending`/`failed`) and an expiring lease, with no outcome recorded. The
claim query's own `attempts < max` then excludes it from every future
claim, and it never reaches `sent`/`failed`/`skipped` — invisible to the
sweep and, because its `status` may never have become `failed`, invisible
to the failed-deliveries view too. `notification_delivery_sweep` therefore
runs a second, plain step after claiming — no claim needed, since these
rows are already unclaimable — reaping any row where
`attempts >= max AND claimed_until < now() AND status NOT IN ('sent',
'failed', 'skipped')`, and writing it `failed` with
`last_error = "exhausted without a recorded outcome"`. This is the same
shape as the existing `stale_run_sweep`/`RunReaperService.reap_stale`
precedent (`docs/governance.md`, "A run whose process died") — settling
what a dead worker left open, not retrying it.

**Settling a row requires still holding its claim.** The update that marks a
row `sent`/`failed`/`skipped` is conditioned on
`WHERE id = :id AND claimed_at = :claimed_at` — the exact claim token this
worker was issued. A worker whose lease expired and was reclaimed by another
sweep run therefore cannot overwrite the second worker's outcome with its
own late one. Its `UPDATE` matches zero rows and it discards the result.

**The lease alone is not a bound on how long a send can run — nothing in
`EmailService.send` or its providers defines one today**, and an earlier
draft of this decision claimed otherwise. `claimed_until` (proposed: two
minutes) only decides when *another* worker may retry. It does nothing to
stop the *original* worker sitting inside a hung `send()` indefinitely,
which could still complete and write `sent` after a second worker has
already resent — a wider duplicate window than the provider-crash case
below already accepts. The write helper therefore wraps the call itself,
`asyncio.wait_for(EmailService.send(...), timeout=SEND_TIMEOUT)`, with
`SEND_TIMEOUT` (proposed: thirty seconds) set well under `claimed_until`'s
lease — a hung call is cancelled by this plan's own code, marked `failed`
with `last_error = "send timed out"`, well before the lease would let
another worker reclaim the row at all.

**Provider acceptance followed by a crash is not solved by any of the
above, and this plan says so rather than implying otherwise.** If the
provider accepts the message and the worker dies before writing `sent`, the
lease eventually expires and a second worker resends — a genuine duplicate
delivery, not a bug in the claim mechanism, a gap in what a claim can
guarantee without the provider's own help. Where the configured
`EmailProvider` supports a client-supplied idempotency key, the delivery
row's id is passed as one, and a resend the provider recognizes as already
accepted is suppressed on its side. `SmtpEmailProvider`/`LogProvider`
(`services/email/providers/`) do not support one today, and for a deployment
on either, this plan accepts at-least-once, not exactly-once, delivery as a
known, bounded limitation — the same trade `trigger_dedupe.py`'s own
docstring already argues for: a rare duplicate costs less than a routinely
dropped notification.

Two concurrent sweeps, or a sweep overlapping a crashed one, take disjoint
rows the same way two concurrent trigger heartbeats already do — this is the
concurrency and crash-recovery contract the review asked for, and it is an
existing pattern in this codebase, not new infrastructure.

**A row's outcome is `SendResult.accepted`, not the absence of an
exception.** `EmailService.send` already returns `SendResult(accepted=False,
error=...)` on a provider rejection without raising —
`NotificationService._deliver` discards that result today (section 0). The
sweep inspects it. `accepted=True` marks the row `sent`. `accepted=False` or
a raised exception marks it `failed` — `attempts` is already incremented,
from the claim above, so a row that keeps failing still exhausts into a
terminal `failed` at the same bound a row that keeps disappearing without a
recorded outcome does. A recipient who has lost access since the row was
queued (Decision 7) marks it `skipped` instead — a fact worth telling an
app admin apart from a provider failure, not silently absent.

**A terminally `failed` row is visible, not only queryable.** Recording
`status`/`last_error`/`attempts` on the row is not, by itself, the
"delivery/failure visibility" the issue asks for — nothing reads that column
back today, which is the same silent-failure shape as the status quo this
plan set out to fix. A new `CurrentAppAdmin`-gated route,
`GET /admin/notifications/deliveries?status=failed`, lists terminally failed
rows deployment-wide (event type, recipient, attempts, `last_error`,
`notification_id` to trace back to its event) — one small, generic view
rather than a bespoke one per event type, and app-admin-gated because a
permanent mail failure is an operational concern, not a tenant one. This
covers a row that was written and then failed to send. It does not cover
Decision 2's savepoint case — a write that never happened has no row for
this view to return, which is why that case gets its own structured log
line rather than a claim on covering it here too.

**What re-derives at send time is the *gate*, never the whole rendering —
the content itself always comes from what was written.** The delivery row
names the event and the notification it belongs to. It carries no
`EmailKey` of its own. The renderer reads the notification's `render_context`
(Decision 2) for the typed variables and picks an `EmailKey` per Decision
1's table: `budget_exceeded` → `EmailKey.BUDGET_EXCEEDED`,
`agent_usage_report`/`usage_report` → `EmailKey.USAGE_REPORT`, both off
their frozen `render_context` unchanged since write time — which is what
makes the report case correct rather than merely convenient: a window
aggregate ("this week's spend") computed once when the report is generated
must not be recomputed if a delayed retry pushes the send past that
original window, or the email would silently describe a different period
than the one the recipient was told they were reading. `approval_requested`
is the one case with something to re-derive: the *choice* between
`EmailKey.APPROVAL_REQUESTED` and `APPROVAL_PENDING` depends on the
recipient's *current* `approvals:decide` (Decision 7), recomputed fresh
when the sweep claims the row — but the surrounding `render_context` (the
tool names, the queue link) is still the frozen data from write time, only
the key selection is live. `ingestion_*`, `security_event` and
`configuration_changed` have a content gate (Decision 1) that governs
whether the row is sent or `skipped` (Decision 7), not which template
renders — their `render_context` needs no re-derivation once the gate has
passed. Every event type without a specific `EmailKey` renders through one
shared `EmailKey.NOTIFICATION` template off `summary`/`context_url`, since a
bespoke template per new event type is not scope
this plan takes on.

**Deduplication is the database, not Redis.** The
`(recipient_user_id, event_type, occurrence_id)` unique constraint from
Decision 2 is the guarantee: a retried budget check, a re-delivered
ingestion callback or a duplicated audit write attempts the same insert
twice and the second one is a no-op, inside the same transaction as
whatever triggered it, with no separate cache to fall out of sync with the
database and no TTL to expire before the retry it was meant to catch.
`trigger_dedupe.py`'s Redis claim is right for its own job — an inbound
webhook arriving from outside any transaction — but it fails open, expires
after fifteen minutes and is never released on a failed hand-off, all of
which section 0 already shows are wrong properties for a write this plan
fully controls.

*Rejected: keep delivery as plain `spawn`, no retry table.* That is the
status quo, and the issue is explicit that email must survive a transient
outage without the originating action failing — which needs somewhere to
record that a send is still owed.

*Rejected: a Redis claim keyed on `(organization_id, event_type, target_id)`.*
The original draft of this decision proposed exactly that and does not
survive its own reasoning: a claim taken before a transaction that later
rolls back leaves a real retry suppressed for fifteen minutes, and a claim
that expires before a legitimately slow retry lets the duplicate through —
the DB constraint has neither failure mode.

## Decision 4 — preferences cover both channels, with a named mandatory set

The issue asks for "per-user/per-event channel preferences for in-app and
email ... explicitly define any mandatory system notice policy instead of
silently bypassing preferences." The original draft of this decision made
in-app unconditional and unconfigurable, which is exactly the silent bypass
the issue warns against. Both channels are preferences. `mandatory` (Decision
1's table: `security_event`, `configuration_changed`) is the named
exception, on **both** channels — the same shape the deployment already
applies to `IMPERSONATION_NOTICE` (section 0: gated on a deployment setting,
not a user preference) and to the organization's own budget cap
(`docs/governance.md`: "the organization's cap ignores the spec entirely").
A mandatory event's write path does not consult `notification_preferences`
at all, for either channel.

The three existing boolean columns on `User` stay exactly as they are and
stay authoritative for exactly what they already gate: the **email** channel
of `budget_exceeded`, `approval_requested` and `agent_usage_report`/
`usage_report`. A new table, `notification_preferences`: `user_id`,
`event_type`, `channel`, `enabled` (default `true`), covers every other
`(event_type, channel)` pair — every event type's in-app channel, and every
non-legacy event type's email channel. The two never overlap, by
construction, so there is exactly one authoritative lookup per pair rather
than two that could disagree: legacy email reads the column, everything
else reads the table, and a mandatory event type reads neither.

*Rejected: one row per (user, event_type) with no channel dimension.* The
issue explicitly asks for "per-user/per-event channel preferences ... with a
delivery-channel abstraction for future channels", which the channel column
gives for free — a later channel is a new enum value and no migration to the
preference model itself.

*Rejected (the original draft): in-app always on, no preference offered.*
The quote opening this decision is what the issue actually asks for. Making
in-app unconditional was a product opinion this plan asserted without naming
it as a decision, and it contradicts the "no requirement demands this"
standard Decision 6 holds itself to elsewhere in this same document.

## Decision 5 — the announcement composer is app-admin-only, and reuses the pipeline

A new table, `announcements`: `id`, `actor_user_id`, `body`, `audience_description`
(the human-readable scope the sender picked, e.g. "all organizations" or
"Acme, Globex — owners and admins"), `created_at`. A new route, gated on
`CurrentAppAdmin` alone — never on a `Perm`, since every `Perm` is
organization-scoped and none of them can express "every organization" — lets
an app admin write a body, pick an explicit audience (one organization, a
list of organizations, or every organization, optionally narrowed to a role
within each), pick channels, and send. Sending writes one `announcements`
row, then one `notifications` row per resolved recipient with
`event_type=announcement` and `announcement_id` pointing at it, through the
exact same write path and delivery pipeline as every other event — an
announcement is not a second mechanism, it is one more producer into the one
that already exists. The `announcement_id` is what lets a sender (or a
`runs:view`-equivalent audit view — access to this is an open question)
reconstruct exactly which rows and which delivery statuses belong to one
send, rather than only the aggregate `record_audit` entry below.

The send is audited through `record_audit` (actor, the `announcement_id`,
the audience description, recipient count — never the full recipient list,
which is already reconstructable by joining `notifications` on
`announcement_id`), matching every other privileged action in
`backend/app/services/`.

An organization admin gets nothing new here. `agents:edit`, `org:settings`
and the rest stay exactly what they are. There is no `notifications:manage`
permission, because the one action that would need it — composing a
broadcast — is deliberately not something any organization-scoped role can
reach, per the issue's own boundary.

## Decision 6 — no new realtime transport in v1

The bell shows an unread count and a paginated inbox. The acceptance criteria
in the issue ask that this survive a reload and that email follow
preferences — neither asks for the count to update without one. Building a
cross-process push channel (a new Redis pub/sub plus a new WebSocket surface
that is not scoped to one run, unlike either existing WS endpoint) is real,
separate infrastructure work with its own failure modes, and the issue does
not require it.

V1 ships a short-interval poll of the unread count from the console shell,
the same shape existing client-side polling already uses elsewhere in the
frontend. A push-based bell is recorded as an open question below rather
than designed here — the `notifications` table shape does not
foreclose it: a later phase can add a publish call beside the existing
`db.flush()` without touching the schema.

*Rejected: building the WebSocket channel now.* It would be the single
largest new piece of infrastructure in this plan for a requirement the issue
does not state, at the direct cost of the "minimize the amount of changes"
instruction this plan is written under.

## Decision 7 — cross-tenant safety, and permission re-checked at read and at send

Reading the inbox is `GET /notifications`, scoped to the caller's own rows —
`recipient_user_id = caller`, additionally filtered to rows whose
`organization_id` matches the caller's active organization or is null
(Decision 2), the same way every other listing already is. A `notification`
row belonging to another organization answers 404, the same rule every
resource in this codebase already follows. There is no new mechanism to
build here, only the existing scoping applied to a new table.

The issue asks for more than tenant scoping, though: "resolve permissions at
delivery/read time so links and content cannot expose another tenant's
resources... role membership changes ... must be handled." Two distinct
things follow from that, and the original draft of this decision only
covered the first:

- **A removal from the organization is a plain consequence of the tenant
  check above** — a person no longer a member has nothing to scope the read
  to, the same as any other resource. Decision 3's send-time claim covers
  the email side: a pending delivery to somebody no longer a member is
  marked `skipped`, not sent, because the row is claimed and rendered at
  send time, not at write time. The same check covers the deployment-wide
  audience: `security_event`/`configuration_changed` recipients are app
  admins with no membership row to lose (Decision 2), so the send-time
  re-check there is `is_app_admin`, not organization membership — a
  recipient whose app-admin status is revoked before the sweep claims their
  row is `skipped` on exactly the same basis.
- **A role change, short of removal, can change what a still-current member
  is allowed to see about an event they were correctly addressed on — and
  this applies to every gated event type in Decision 1's table, not only
  `approval_requested`.** The first draft of this decision worked the
  approval case as its only example and left the others (`security_event`'s
  `org_admins` audience, `configuration_changed`'s app admins,
  `ingestion_*`'s `collections:view`) implicitly ungated, which is exactly
  what let a demoted organization admin go on reading security notices and
  a revoked app admin go on reading global ones. The rule is table-driven,
  not case-by-case: **`GET /notifications` re-checks the reader's *current*
  standing on whatever Decision 1 names in "Content gated on" for that row's
  `event_type`, before the row is returned.** Two shapes, not one:
  - **Degrade, for `approval_requested`.** `NotificationService
    .approval_requested` already recomputes who currently holds
    `approvals:decide` and sends one of two emails depending on the answer —
    this plan extends that, not invents it. A reader who still holds it sees
    the queue link. A reader who no longer does sees the same no-link
    variant the email already sends a non-decider, because there is
    something true and useful to say either way ("a call is parked" is
    informative regardless of who may act on it).
  - **Exclude, for `security_event`, `configuration_changed` and
    `ingestion_*`.** There is no equivalent partial truth for "you are no
    longer an admin" or "you can no longer see this collection" — the row is
    simply not returned to a reader who does not currently hold the named
    gate, the same way a cross-tenant row is not returned. A demoted
    organization admin stops seeing that organization's `security_event`
    rows. A revoked app admin stops seeing `configuration_changed` rows and
    the `org_admins`-less half of `security_event`, even for rows addressed
    to them while they still held the status. This is the read-time half of
    what the first bullet above already does at send time for the same two
    event types.

A notification already written is never rewritten by either check — it
recorded a true fact about who was addressed when the event fired, and a
later role or app-admin-status change changes what is *rendered* or
*returned* from it, not the row itself.

## Decision 8 — retention, ahead of #1420

Issue #1420 does not exist in the codebase yet, so this plan cannot integrate
with a mechanism it may design differently than expected. Instead,
`notifications` and `notification_deliveries` get their own bounded default —
a daily Prefect flow, modeled on the existing `sandbox_log_sweep`, hard-deleting
read notifications past a fixed window (proposed: 90 days) and all
notifications past a longer outer bound regardless of read state (proposed:
one year) — written as one named class of data, so when #1420 ships its
per-organization settings, adopting `notifications` as one more row in that
table is a follow-up, not a redesign.

`announcements` is deliberately not part of this sweep. Purging the
per-recipient `notifications` rows a broadcast fanned out to is exactly what
the window above is for, but the `announcements` row itself — the message an
app admin actually sent, and what `record_audit`'s `announcement_id`
(Decision 5) points at — survives past that window, so "what did an app
admin send, and when" stays answerable from the audit trail after ordinary
retention has cleared the individual deliveries.

## Work breakdown

1. **Schema** — `notifications` (nullable `organization_id`, `occurrence_id`,
   `render_context` JSONB, `in_app_visible`, `announcement_id`, the unique
   constraint and the two indexes from Decision 2), `notification_deliveries`
   (`claimed_at`/`claimed_until`, `status` including `skipped`),
   `notification_preferences`, `announcements`, `rag_documents
   .ingestion_attempt` (new column, an integer counter `retry_ingestion`
   bumps — Decision 1), migration (next number after `0077`). Tests:
   cross-tenant read refused, a recipient reads only their own rows, a
   null-organization row is visible regardless of the caller's active
   organization, the unique constraint rejects a duplicate
   `(recipient_user_id, event_type, occurrence_id)` insert, a second failed
   `retry_ingestion` on the same document produces a distinct
   `occurrence_id` from the first.
2. **Identity-first resolution and the write path** — `NotificationEventType`,
   `NotificationChannel`, Decision 1's code-defined event table,
   `list_member_ids_by_role`/`list_app_admin_ids` (new, `select(User.id)`,
   no preference filter), and the write helper that turns a resolved set of
   recipient ids into `notifications`/`notification_deliveries` rows inside
   the caller's transaction — `INSERT ... ON CONFLICT DO NOTHING` on the
   dedup constraint, wrapped in `db.begin_nested()` when called from a
   context that cannot afford its own transaction poisoned (Decision 2),
   computing `in_app_visible` and consulting Decision 4's
   one-authoritative-lookup preference rule per channel, and skipping the
   **preference lookup** entirely for a mandatory event type (both channels
   always on — the row is still written. Nothing about "mandatory" ever
   means "unwritten"). Tests: one event produces one row per resolved
   recipient, a duplicated trigger produces one row via the unique
   constraint rather than two (and raises nothing), an in-app row is written
   even when the recipient has emailed off, a mandatory event type's row is
   written regardless of any preference, all four `(in_app, email)`
   preference combinations produce the schema-level state Decision 2/item 6
   describe, and — the regression Decision 2's savepoint fix targets — a
   forced write failure inside the helper does not roll back the caller's
   own transaction, instead producing the structured log line Decision 2
   specifies.
3. **Migrate the four existing agent-lifecycle emails onto this path** —
   `budget_exceeded`, `approval_requested`, `agent_usage_report` and
   `usage_report` stop calling `_send`/`spawn` directly and instead end in a
   `notifications`/`notification_deliveries` write carrying the typed
   variables their existing `EmailKey` template needs in `render_context`
   (Decision 2) — same trigger point, same `AlertSpec`/`_administrators`
   -resolved audience, with the report events' occurrence id carrying
   `(subject id, period, window start)` (Decision 1). Tests: no duplicate
   email is sent for one event (the regression this review caught), the
   existing `EmailKey`s render from `render_context` with output unchanged
   from today's, the approval split is still made — now at send time
   (item 4), reading `render_context` for everything but the key choice —
   and a report resent after a delay renders the same numbers it was
   generated with, not the window at send time.
4. **Delivery sweep and failure visibility** — `notification_delivery_sweep`
   flow, modeled on `repositories/agent_trigger.py::claim_due` (`FOR UPDATE
   SKIP LOCKED`, incrementing `attempts` in the same claiming update rather
   than on outcome), the settle step's ownership check
   (`WHERE id = :id AND claimed_at = :claimed_at`), the exhausted-and-abandoned
   reaper step (`attempts >= max AND claimed_until < now() AND status NOT IN
   ('sent', 'failed', 'skipped')` → `failed`, modeled on
   `RunReaperService.reap_stale`), an explicit `SEND_TIMEOUT` around
   `EmailService.send` well under the lease, the per-event-type render
   dispatch from Decision 3 (re-deriving the gate/key choice only for
   `approval_requested` — everyone else renders `render_context` as written),
   `SendResult.accepted` deciding `sent` vs `failed`, a provider idempotency
   key passed where the configured `EmailProvider` supports one, and the
   `CurrentAppAdmin`-gated `GET /admin/notifications/deliveries?status=failed`
   view. Tests: two concurrent sweep runs never both send the same row, a
   worker that claims a row and never returns still exhausts the retry bound,
   a row exhausted on its last claim with no recorded outcome is reaped to
   `failed` and appears in the failed-deliveries view (the regression this
   review's lease-and-reaper finding targets), a settle attempt against an
   already-reclaimed row's stale `claimed_at` updates nothing, a hung
   `send()` is cancelled at `SEND_TIMEOUT` and marked `failed` rather than
   holding its claim to the lease's edge, a failed send retries up to the
   bound and then stops, a recipient who lost access since the row was
   queued is marked `skipped` and not sent, sending never raises into the
   triggering request, an organization admin is refused the failed-deliveries
   view, and a terminally failed row appears in it with its `last_error`.
5. **New trigger points** — `run_completed`/`run_failed` for unattended
   surfaces only (excluding `WEB`). Ingestion wired at three points —
   `RAGDocumentService.complete_ingestion`/`fail_ingestion` for a
   per-document outcome (the shared boundary both the upload path
   (`rag_tasks.py::_run_ingestion`) and the sync paths
   (`_settle_document_row`) call through), plus `RAGSyncService.complete_sync`
   and `SyncSourceService.update_after_sync` for a whole-attempt failure
   with no document row — `ingest_document_flow` and `retry_ingestion`
   threading the dispatch-time `ingestion_attempt` through to settlement and
   rejecting a stale one (Decision 1). `security_event`/
   `configuration_changed` wired at the existing `record_audit` call sites
   named in section 0. Tests: each trigger point produces the expected
   audience, a `WEB` run never produces a `run_completed` row, a connector
   auth failure and a pre-download `BudgetExceeded` each produce a
   notification with no document row involved, an ingestion failure for one
   organization never reaches another, an upload's per-document failure is
   covered alongside a sync's (through the one hook, not two), a second
   failure on a retried document produces a second notification rather than
   being suppressed by the first's `occurrence_id`, and an attempt that
   settles after a newer retry has already been dispatched is rejected as
   stale rather than mislabeled under the newer attempt's number.
6. **Preferences API and page** — extend
   `frontend/.../settings/notifications/page.tsx` with the new event
   types and channel toggles for the non-legacy `(event_type, channel)`
   pairs, and `GET`/`PATCH` on `notification_preferences`. Tests: turning
   email off for one event type leaves in-app untouched, an unset preference
   defaults to on, a mandatory event type's toggle is absent or disabled in
   the UI and refused if called directly, and the inbox listing, unread
   count and mark-all-read all agree on `in_app_visible` across the four
   `(in-app on/off, email on/off)` combinations — an email-only row never
   appears in any of the three, an in-app-only row appears in all three with
   no delivery row to show for it.
7. **Announcement composer** — the `CurrentAppAdmin`-gated route,
   `announcements` row, per-recipient `notifications` fan-out, audit entry.
   Tests: an organization admin is refused, an app admin's send reaches
   exactly the selected audience and nobody outside it, the audit entry
   never carries the full recipient list, and every recipient row for one
   send resolves back to it through `announcement_id`.
8. **Retention sweep** — the daily flow, frozen-time tested.
9. **Frontend inbox and dashboard integration** — bell with unread count
   (polled), paginated list, mark-read/mark-all-read, empty state, i18n
   keys, a `tour.ts` stop gated on the bell always being present, and a
   dashboard widget surfacing recent/unread notifications at a glance —
   `.claude/rules/frontend.md`'s own rule for activity or state that belongs
   there, which the first draft of this plan did not account for. Tests:
   read state persists across reload, pagination, the empty state.
10. **Docs** — `docs/governance.md`'s Alerts section gains the in-app half
    (today it documents email only), `docs/permissions.md` if the composer's
    gate needs a line, and `docs/console.md` for the bell and the dashboard
    widget.

## Out of scope, deliberately

- Any realtime push transport (Decision 6) — open question 1 below.
- A per-organization routing UI for the event catalog (Decision 1) —
  audiences stay code-defined in phase 1.
- Folding `IMPERSONATION_NOTICE` into this pipeline (section 0, Decision 3)
  — it already has its own mandatory, non-preference-gated delivery, and
  nothing in the issue asks it to grow an inbox row.
- Outgoing webhooks to external systems, per the issue's own text — this
  covers notifications to people.
- Synthetic or scored evaluation of anything — not applicable here, noted
  only for consistency with this repository's other design-first plans.
- A new `notifications:manage` permission — the composer's gate is
  `CurrentAppAdmin`, and nothing else in this plan needs a permission that
  does not already exist.

## Open questions — for review, none blocking

1. **Should v1 include any realtime push**, or is polling acceptable through
   the first release and revisited only if it proves too slow in practice?
2. **Retention windows** (90 days read, one year outer bound) are placeholders
   in Decision 8 — whose call is the actual number?
3. **Does `usage_report` need an in-app row at all?** It is a periodic
   digest already delivered by email. An inbox entry for it may be noise
   rather than signal.
4. **How many organizations can one announcement address before the
   recipient-resolution query itself needs paging or a background job
   rather than a synchronous route handler?** Decision 3's sweep-only
   delivery already removes the sharper half of this — sending fans out
   through the bounded, leased sweep (Decision 3), never as one burst of
   in-process tasks per send — so what is left is the synchronous insert of
   one `notifications`/`notification_deliveries` pair per recipient before
   the route can return. This plan leaves that as a bulk insert in the
   request rather than a background job deliberately: a few thousand rows is
   a sub-second write, an app admin's own action is not latency-sensitive
   the way a user-facing request is, and an admin can already page by
   organization by sending more than one announcement. A background job adds
   a job table, a progress surface and a partial-failure story for a
   scale this plan has no evidence it needs yet — worth revisiting once a
   real deployment's organization count says otherwise, not designed
   speculatively here.
5. **Security event granularity** — section 0 proposes reusing existing
   `record_audit` call sites as the trigger points rather than a new
   detector. Is that coverage sufficient, or does the issue expect events
   `record_audit` does not yet cover?

## Resolved in review

Four automated review passes (Codex) against this plan. Outcomes below.
`Resolved in review` still applies to a human reviewer's own decisions on
top of these.

**Fixed, first pass** (commit `ecc82358`): permission not re-checked at
read/send time, the Redis-claim dedup, no concurrency/crash-recovery
contract for the sweep, two incompatible delivery paths for the legacy
emails, `_audience()`'s address-only shape reused unchanged, in-app wrongly
made unconditional, no scope for deployment-wide events, the ingestion and
run-completion gaps in the catalog, missing FKs/indexes, no announcement
identifier, and the missing dashboard-widget integration. Decisions 1–8 and
the work breakdown above reflect all of them.

**Fixed, second pass** (this commit): a notification write's failure could
poison and roll back the transaction that triggered it (`AgentRunnerService
.finish`'s own guard did not reach far enough) — Decision 2 now specifies a
savepoint and an `ON CONFLICT DO NOTHING` dedup insert. A terminally failed
delivery was recorded but never surfaced — Decision 3 now specifies an
app-admin-gated failed-deliveries view. An announcement's message could
outlive its audit linkage's usefulness after retention purged its recipient
rows — Decision 8 now states `announcements` is exempt from the sweep. The
send-time membership re-check (Decision 7) did not name its analogue for the
app-admin audience — added.

**Deliberately not fixed, second pass**: the synchronous route for an
`every organization` announcement doing its recipient-resolution insert
in-request. Open question 4 explains why a background job is not designed
here yet — the sharper half of the original concern (unbounded in-process
delivery tasks) is already gone now that delivery is sweep-only, and the
remaining half (a bulk insert before the route returns) is judged low-risk
at the scale this plan has evidence for. Revisit if a real deployment's
organization count says otherwise.

**Fixed, third pass** (this commit): two P1s and four P2s, verified against
`feat/1598-notification-center` at `ce3e809b` before fixing. **Read-time
authorization was incomplete** — Decision 7's re-check only worked the
`approval_requested` case. A demoted organization admin or a revoked app
admin could still read previously delivered `security_event`/
`configuration_changed` rows. Decision 1's table now names a content gate
for every event that needs one, and Decision 7 states the general,
table-driven rule with its two shapes (degrade for approvals, exclude for
admin-only content). **The claimed-delivery guarantee had two real gaps** —
`attempts` incremented on a recorded outcome, not on the claim itself, so a
worker that died between sending and recording could retry forever without
exhausting the bound, and nothing stopped a reclaimed row's original,
late-returning worker from overwriting a second worker's outcome. Decision
3 now increments `attempts` at claim time and conditions the settling
`UPDATE` on still holding the claim, and states plainly that provider
acceptance followed by a crash is a known at-least-once limitation absent a
provider-side idempotency key. **The ingestion producer this plan named was
wrong** — uploads call `RAGDocumentService.complete_ingestion`/
`fail_ingestion` directly, not `_settle_document_row`, which only sync paths
call. Both sections 0 and 1 and work item 5 now name the shared service
boundary instead. **The occurrence id for ingestion collided across
retries** — `retry_ingestion` reuses the document id, so a second failure
shared its predecessor's dedup key and was silently suppressed.
`RAGDocument` gains an `ingestion_attempt` counter, folded into the
occurrence id. **The two report events had no catalog entry**, despite
Decision 3 already migrating them, and re-deriving their content at send
time (right for a permission-gated event) would have silently changed what
window a delayed report described. Decision 1 now catalogs them with a
period-scoped occurrence id, and the render-dispatch rule in Decision 3 is
scoped to gated events only. **Email-only preferences had no schema
representation** — `notification_deliveries` is a child of `notifications`,
so an in-app-off, email-on combination needed a row that would also,
incidentally, show up in the inbox. `notifications.in_app_visible` closes
that, checked by listing, unread count and mark-all-read alike. **The
failed-deliveries view could not show a rolled-back write**, and the text
claiming otherwise is now corrected — a savepoint rollback leaves no row in
either table, so it gets a structured log line instead, and the savepoint's
own reach is narrowed to recoverable statement errors, not a lost
connection. **One direct contradiction** — work item 2 said "skip the
write" for a mandatory event while its own test required the row to exist.
Corrected to "skip the preference lookup", which is what Decision 4 always
meant.

**Fixed, fourth pass** (this commit): five P2s, verified against
`feat/1598-notification-center` at `274a602f` before fixing. **Frozen
summaries could not reproduce the legacy email templates this plan claimed
to preserve unchanged** — `summary`/`context_url` are free text, not the
typed variables `EmailKey.BUDGET_EXCEEDED`/`APPROVAL_REQUESTED`/
`USAGE_REPORT` need. `notifications.render_context` (JSONB) now carries
them, captured at write time by the same code that builds them today.
**A worker that crashed on a row's last allowed claim left it permanently
stuck** — unclaimable (`attempts` at the bound) and not visibly failed
(`status` never written). The sweep now runs a second, claim-free reaping
step for exactly that state, modeled on the existing
`RunReaperService.reap_stale`. **The lease was assumed to bound the send
itself, and nothing in `EmailService.send` or its providers does** — an
explicit `SEND_TIMEOUT`, well under the lease, now wraps the call. **The
ingestion catalog still missed a whole class of failure** — a connector
auth/network failure or a pre-download `BudgetExceeded` check fails before
any document row exists, so `RAGDocumentService.fail_ingestion` never
fires. `RAGSyncService.complete_sync` and `SyncSourceService
.update_after_sync` are now named as the producers for that case. **The
mutable `ingestion_attempt` counter had the same "which claim do you still
hold" race Decision 3 had just fixed for delivery settlement** — a slow
attempt settling after a newer retry bumped the counter would misattribute
its outcome to the newer attempt's number. The attempt is now captured at
dispatch and threaded through to settlement, which rejects a stale one.
