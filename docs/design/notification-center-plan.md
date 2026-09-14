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

**Ingestion completes through two separate producers.** A connector sync
completes in `services/sync_source.py`. An uploaded document completes
through the worker flow, `worker/tasks/rag_tasks.py::ingest_document_flow`
and its `_settle_document_row`. A trigger point wired to only one of them
misses the other.

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

| Event | Producer | Occurrence id (Decision 3's dedup key) | Default audience | Content gated on | Mandatory |
|---|---|---|---|---|---|
| `budget_exceeded` | `AgentRunnerService.finish` | the run id | `AlertSpec` (unchanged) | — | no |
| `approval_requested` | `AgentRunnerService.finish` | the approval id | `AlertSpec` (unchanged) | `approvals:decide`, re-checked at read/send time (Decision 7) | no |
| `run_completed` | `AgentRunnerService.finish`, unattended surfaces only (not `WEB`) — the gap `docs/governance.md`'s Alerts section already names | the run id | `initiator` | — | no |
| `run_failed` | same as above | the run id | `initiator` | — | no |
| `ingestion_completed` / `ingestion_failed` | `services/sync_source.py` **and** `rag_tasks.py::_settle_document_row` | the sync attempt id / the document id | whoever started the sync or upload | `collections:view` on the target collection | no |
| `security_event` | the `record_audit` call sites in section 0 | the `AppAdminAuditLog` id | `org_admins` when the entry carries an `organization_id` (`organization_secret.py`, `sandbox_connection.py`), otherwise deployment app admins (`impersonation.py`) | — | yes |
| `configuration_changed` | same, for `deployment.settings_updated` | the `AppAdminAuditLog` id | deployment app admins (no organization — see Decision 2) | — | yes |
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
`event_type` (`NotificationEventType`), `occurrence_id` (the id from
Decision 1's table — an approval, a run, an audit-log row, a document),
`summary` (plain text, pre-rendered at write time — never a raw comment or
secret value), `context_url` (nullable, built the way
`NotificationService._link` already builds one, with `?org=<id>` so the
reader lands in the right tenant), `read_at` (nullable), `created_at`. A
unique constraint on `(recipient_user_id, event_type, occurrence_id)` is
Decision 3's dedup guarantee, enforced by Postgres inside the same
transaction rather than a separate cache. Two indexes carry the two read
patterns: `(recipient_user_id, created_at DESC)` for the paginated inbox, and
a partial index `(recipient_user_id) WHERE read_at IS NULL` for the unread
count.

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
including the three existing agent-lifecycle emails.** Section 0 already
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

**Sending is a claim, not a poll.** The sweep flow,
`notification_delivery_sweep`
(`backend/app/worker/tasks/notification_tasks.py`), takes rows the way
`repositories/agent_trigger.py::claim_due` already does: `SELECT ... WHERE
status IN ('pending', 'failed') AND attempts < max AND (claimed_until IS
NULL OR claimed_until <= now()) ... FOR UPDATE SKIP LOCKED`, stamping
`claimed_at`/`claimed_until` before releasing the row back to `pending` (on
failure, with `attempts` incremented) or `sent`. Two concurrent sweeps, or a
sweep overlapping a crashed one, take disjoint rows the same way two
concurrent trigger heartbeats already do — this is the concurrency and
crash-recovery contract the review asked for, and it is an existing pattern
in this codebase, not new infrastructure.

**A row's outcome is `SendResult.accepted`, not the absence of an
exception.** `EmailService.send` already returns `SendResult(accepted=False,
error=...)` on a provider rejection without raising —
`NotificationService._deliver` discards that result today (section 0). The
sweep inspects it. `accepted=True` marks the row `sent`. `accepted=False` or
a raised exception marks it `failed` and bumps `attempts`, exhausting into a
terminal `failed` past the bound. A recipient who has lost access since the
row was queued (Decision 7) marks it `skipped` instead — a fact worth
telling an app admin apart from a provider failure, not silently absent.

**Rendering is dispatched by `event_type` at send time, not frozen at write
time.** The delivery row names the event and the notification it belongs
to. It does not carry an `EmailKey` or a rendering context. A small
per-event-type renderer — one function per row of Decision 1's table —
re-derives what to send when the sweep claims the row: for
`approval_requested` this recomputes the recipient's current
`approvals:decide` status and picks `APPROVAL_REQUESTED` or
`APPROVAL_PENDING` accordingly, exactly the split
`NotificationService.approval_requested` already makes, but freshly, so a
role change between queuing and sending is reflected rather than baked in
(Decision 7). `budget_exceeded` and `agent_usage_report` keep their existing
`EmailKey`s and context shape unchanged. Every other event type in Decision
1's table renders through one shared `EmailKey.NOTIFICATION` template off the
notification's own `summary`/`context_url`, since a bespoke template per new
event type is not scope this plan takes on.

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
  send time, not at write time.
- **A role change, short of removal, can change what a still-current member
  is allowed to see about an event they were correctly addressed on.** This
  is not new to this plan — `NotificationService.approval_requested` already
  recomputes who currently holds `approvals:decide` and sends one of two
  emails depending on the answer. Decision 1's table names, per event type,
  which permission (if any) content is gated on. Decision 3 re-derives it at
  send time for email. The inbox does the same at read time: serializing a
  `notification` row for `approval_requested` checks the reader's *current*
  `approvals:decide` before including the queue link, falling back to the
  no-link variant exactly as the email does, rather than trusting whatever
  was true when the row was written.

A notification already written is never rewritten by either check — it
recorded a true fact about who was addressed when the event fired, and a
later role change changes what is *rendered* from it, not the row itself.

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

## Work breakdown

1. **Schema** — `notifications` (nullable `organization_id`, `occurrence_id`,
   `announcement_id`, the unique constraint and the two indexes from
   Decision 2), `notification_deliveries` (`claimed_at`/`claimed_until`,
   `status` including `skipped`), `notification_preferences`,
   `announcements`, migration (next number after `0077`). Tests: cross-tenant
   read refused, a recipient reads only their own rows, a null-organization
   row is visible regardless of the caller's active organization, the unique
   constraint rejects a duplicate `(recipient_user_id, event_type,
   occurrence_id)` insert.
2. **Identity-first resolution and the write path** — `NotificationEventType`,
   `NotificationChannel`, Decision 1's code-defined event table,
   `list_member_ids_by_role`/`list_app_admin_ids` (new, `select(User.id)`,
   no preference filter), and the write helper that turns a resolved set of
   recipient ids into `notifications`/`notification_deliveries` rows inside
   the caller's transaction, consulting Decision 4's one-authoritative-lookup
   preference rule per channel and skipping the write entirely for a
   mandatory event type. Tests: one event produces one row per resolved
   recipient, a duplicated trigger produces one row via the unique
   constraint rather than two, an in-app row is written even when the
   recipient has emailed off, a mandatory event type's row is written
   regardless of any preference.
3. **Migrate the three existing agent-lifecycle emails onto this path** —
   `budget_exceeded`, `approval_requested` and `agent_usage_report` stop
   calling `_send`/`spawn` directly and instead end in a
   `notifications`/`notification_deliveries` write, same trigger point, same
   `AlertSpec`-resolved audience. Tests: no duplicate email is sent for one
   event (the regression this review caught), the existing `EmailKey`s and
   template context are unchanged, and the approval split is still made —
   now at send time (item 4) rather than at write time.
4. **Delivery sweep** — `notification_delivery_sweep` flow, modeled on
   `repositories/agent_trigger.py::claim_due` (`FOR UPDATE SKIP LOCKED` plus
   a lease), the per-event-type render dispatch from Decision 3, and
   `SendResult.accepted` deciding `sent` vs `failed`. Tests: two concurrent
   sweep runs never both send the same row, a crashed claim's lease expires
   and the row is retried, a failed send retries up to the bound and then
   stops, a recipient who lost access since the row was queued is marked
   `skipped` and not sent, and sending never raises into the triggering
   request.
5. **New trigger points** — `run_completed`/`run_failed` for unattended
   surfaces only (excluding `WEB`), ingestion completion/failure wired at
   **both** `services/sync_source.py` and
   `worker/tasks/rag_tasks.py::_settle_document_row`, and
   `security_event`/`configuration_changed` wired at the existing
   `record_audit` call sites named in section 0. Tests: each trigger point
   produces the expected audience, a `WEB` run never produces a
   `run_completed` row, an ingestion failure for one organization never
   reaches another, and an upload's ingestion failure is covered alongside a
   sync's.
6. **Preferences API and page** — extend
   `frontend/.../settings/notifications/page.tsx` with the new event
   types and channel toggles for the non-legacy `(event_type, channel)`
   pairs, and `GET`/`PATCH` on `notification_preferences`. Tests: turning
   email off for one event type leaves in-app untouched, an unset preference
   defaults to on, a mandatory event type's toggle is absent or disabled in
   the UI and refused if called directly.
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
   rather than a synchronous route handler?**
5. **Security event granularity** — section 0 proposes reusing existing
   `record_audit` call sites as the trigger points rather than a new
   detector. Is that coverage sufficient, or does the issue expect events
   `record_audit` does not yet cover?
6. **Who can inspect a delivery failure beyond `last_error` on the row?**
   Decision 5 gives an announcement's sender a way to reconstruct its
   deliveries through `announcement_id`. Nothing in this plan yet gives an
   app admin a general view over `notification_deliveries.status`/
   `last_error` for non-announcement events — worth a small admin view, or
   is a database query sufficient for how rarely this is expected to matter?

## Resolved in review

*(to be filled in during review. This section records the outcomes so the
document stands as the final design rather than a set of proposals.)*
