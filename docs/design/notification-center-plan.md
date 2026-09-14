# Notification center — plan first (#1598)

A bell, an inbox and email delivery for events nobody is watching: approvals,
budget and security events, run completion and failure, ingestion, and
configuration changes. An app admin can also send an audited system
announcement. This plan follows the design-first practice this repository
already uses for a large change (see #1111): a written plan before code, so
the shape is agreed once instead of argued over in review comments.

The one-sentence design: **the platform keeps writing every event through the
audience-resolution code it already has, but the resolved recipients now get a
durable per-user row they can read, mark read, and later stop receiving
through their own preferences — email stays exactly what it is today, a
best-effort side channel off the same row, and only a deployment app admin can
address an audience wider than one organization.**

## 0. What already exists

`NotificationService` (`backend/app/services/notifications.py`) is
email-only. It has three methods, one per agent-lifecycle event:
`budget_exceeded`, `approval_requested`, `usage_report`. Each resolves an
audience and calls `EmailService.send`. There is no in-app notification or
inbox anywhere in the codebase.

**Audience resolution already exists and is reusable as-is.**
`backend/app/repositories/member.py` answers "which addresses" for a role
list, for named members, or for deployment app admins.
`NotificationService._administrators`, `_deciders` and `_audience` compose
those into the role-based audiences an `AlertSpec` names
(`backend/app/agents/spec.py`, `AlertAudience`: `ADMINS`, `OWNER`,
`INITIATOR`, `CHOSEN`). This plan keeps that layer and does not replace it.

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
separate detector.

**Permissions have three layers**, and only the first reaches across
organizations. `users.is_app_admin` (`CurrentAppAdmin` in
`backend/app/api/deps.py`) is a deployment-wide bypass with no membership
row. Every entry in `Perm` (`backend/app/core/permissions.py`) is resolved
against one organization through `AuthContext.permissions`, so no role, no
matter how senior, reaches a second organization through the permission
catalog. This is the mechanism the issue's "an organization admin must not
gain deployment-wide broadcast rights" rests on: the composer gates on
`CurrentAppAdmin`, never on a `Perm`.

**Background delivery has two existing shapes to reuse.** In-process
fire-and-forget: `app.core.background.spawn` /`spawn_after_commit`
(`NotificationService._send` uses `spawn`, since it runs after a run's
transaction already committed). Durable, retried work: a thin `@flow` calling
a plain async function, deployed on an `IntervalSchedule` — the cleanest
template is `backend/app/worker/tasks/approval_tasks.py`. The only flow with
explicit bounded retries today is `teardown_tasks.py::external_state_cleanup_flow`
(`retries=3, retry_delay_seconds=30`). Deduplication has one existing shape,
a Redis claim keyed on a caller-supplied id (`backend/app/services/trigger_dedupe.py`).

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

`NotificationEventType` (`StrEnum`) names every event this feature covers:
`approval_requested`, `budget_exceeded`, `run_failed`, `ingestion_completed`,
`ingestion_failed`, `security_event`, `configuration_changed`, and
`announcement` for the app-admin composer. Each maps, in code, to a default
audience built from the same `AlertAudience`-shaped roles the agent spec
already uses (admins, initiator, chosen), plus one new case: `org_admins`
without app admins, for events about the organization itself rather than one
run.

The mapping is code, not a form an admin fills in. The issue asks for an
"extensible event catalog and recipient rules", and extensible here means a
developer adds a row when a new event ships — the same way `AlertAudience`
values are fixed and reviewed, not user-invented. A per-organization routing
UI is real scope the issue does not ask for and this plan does not add it.

`AlertSpec`/`NotificationSpec` stay exactly as they are, unmodified, still
gating the three agent-lifecycle emails. `budget_exceeded` and
`approval_requested` now also write to the new catalog below, using the same
trigger point and the same resolved audience — one call to
`NotificationService`, two effects (an email it already sends, and a new
in-app row). No behavior an existing test asserts on changes.

*Rejected: extending `NotificationSpec` with the new event types.* An agent's
spec cannot reasonably declare who hears about a vault secret rotation or a
deployment-wide config change — those are not the agent's business, and
putting them in an exported, per-agent file would mean two unrelated
organizations' security teams reading the same YAML field name.

## Decision 2 — a notification is a row per recipient, separate from audit

New table `notifications`: `id`, `organization_id`, `recipient_user_id`,
`event_type` (`NotificationEventType`), `summary` (plain text, pre-rendered
at write time — never a raw comment or secret value), `context_url`
(nullable, built the way `NotificationService._link` already builds one, with
`?org=<id>` so the reader lands in the right tenant), `read_at` (nullable),
`created_at`.

One row per recipient, not one event row with a join table, because unread
count and read state are per person and the inbox reads by recipient every
time. Storing a pre-rendered summary, not a template key plus raw context,
keeps a later change to an event's wording from rewriting history, and keeps
a comment or file name that later turns out unsafe to display out of the row
in the first place — the summary is built once, at write time, by the code
that already knows what is and is not safe to show.

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

## Decision 3 — email and future channels are a queued side effect, not the write itself

A new table `notification_deliveries`: `id`, `notification_id`, `channel`
(`NotificationChannel`: `EMAIL` today), `status`
(`pending`/`sent`/`failed`), `attempts`, `last_error`. One row per channel a
recipient is due to receive the notification on, created in the same
transaction as the `notifications` row.

After commit, `spawn_after_commit` queues delivery for each pending row —
same mechanism `NotificationService` already depends on for post-commit work.
A new Prefect flow, `notification_delivery_sweep`
(`backend/app/worker/tasks/notification_tasks.py`, modeled on
`external_state_cleanup_flow`'s bounded retry shape), runs on a short
interval and retries any `pending`/`failed` row under a max attempt count,
marking it `failed` for good past that count. This closes a real gap: today's
`NotificationService._deliver` logs a failure and moves on, so a mail server
outage silently drops the alert with nothing left to retry. The issue asks
for exactly this — "bounded retries", "delivery/failure visibility" — and it
does not exist today.

Deduplication reuses the Redis-claim shape from
`backend/app/services/trigger_dedupe.py`, keyed on
`(organization_id, event_type, target_id)` at the point a notification would
be created — a retried budget check or a re-delivered webhook must produce
one row, not two, the same "at-least-once with the duplicate suppressed"
property the trigger pipeline already relies on.

Email delivery itself still goes through `EmailService`/`EmailKey`
(`backend/app/services/email/`). Rather than one `EmailKey` per event type —
which would grow without bound as the catalog grows — a single
`EmailKey.NOTIFICATION` template renders the event's summary and link
generically, and the three existing alert-specific keys
(`BUDGET_EXCEEDED`, `APPROVAL_REQUESTED`, `APPROVAL_PENDING`) are left
untouched, since their wording earns the extra template (the approval split
in `NotificationService.approval_requested`, for one, is deliberate and
documented in `docs/governance.md`).

*Rejected: keep delivery as plain `spawn`, no retry table.* That is the
status quo, and the issue is explicit that email must survive a transient
outage without the originating action failing — which needs somewhere to
record that a send is still owed.

## Decision 4 — preferences: keep the three columns, add one table for the rest

The three existing boolean columns on `User` are untouched. They already
gate the three agent-lifecycle emails through `NotificationPreference`, and
rewriting them into the new shape would touch tested code for no behavior
change.

A new table, `notification_preferences`: `user_id`, `event_type`, `channel`,
`enabled` (default `true`). Read at the point a `notifications` /
`notification_deliveries` pair would be created for a recipient: in-app is
never suppressed by a preference — an event that names somebody as a
recipient always reaches their inbox, because "opted out of the bell
entirely" is not a preference this plan offers — only the email row is
skipped when the recipient has turned that channel off for that event type.
This mirrors the existing rule stated in `docs/governance.md`'s Alerts
section: a per-person opt-out only ever subtracts, and it is applied last,
after the audience is resolved.

*Rejected: one row per (user, event_type) with no channel dimension.* The
issue explicitly asks for "per-user/per-event channel preferences ... with a
delivery-channel abstraction for future channels", which the channel column
gives for free — a later channel is a new enum value and no migration to the
preference model itself.

## Decision 5 — the announcement composer is app-admin-only, and reuses the pipeline

A new route, gated on `CurrentAppAdmin` alone — never on a `Perm`, since
every `Perm` is organization-scoped and none of them can express "every
organization" — lets an app admin write a summary, pick an explicit audience
(one organization, a list of organizations, or every organization, optionally
narrowed to a role within each), pick channels, and send. Sending creates one
`notifications` row per resolved recipient with `event_type=announcement`,
through the exact same write path and delivery pipeline as every other
event — an announcement is not a second mechanism, it is one more producer
into the one that already exists.

The send is audited through `record_audit` (actor, the chosen audience
description, recipient count — never the full recipient list, which is
already reconstructable from the `notifications` rows themselves), matching
every other privileged action in `backend/app/services/`.

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
frontend. A push-based bell is recorded as an open question (Decision 8's
list) rather than designed here — the `notifications` table shape does not
foreclose it: a later phase can add a publish call beside the existing
`db.flush()` without touching the schema.

*Rejected: building the WebSocket channel now.* It would be the single
largest new piece of infrastructure in this plan for a requirement the issue
does not state, at the direct cost of the "minimize the amount of changes"
instruction this plan is written under.

## Decision 7 — cross-tenant and membership safety

Reading the inbox is `GET /notifications`, scoped to the caller's own rows —
`recipient_user_id = caller`, filtered further by the currently-active
organization the same way every other listing already is. A `notification`
row belonging to another organization answers 404, the same rule every
resource in this codebase already follows. There is no new mechanism to
build here, only the existing scoping applied to a new table.

A role change or a removal from the organization does not rewrite history: a
notification already written stays exactly what it says, because it recorded
a true fact about who was addressed when the event fired. A person removed
from the organization entirely loses read access to that organization's rows
going forward, through the same tenant check as everything else — not a
special case, an ordinary consequence of no longer being a member.

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

1. **Schema** — `notifications`, `notification_deliveries`,
   `notification_preferences` migration (next number after `0077`).
   Tests: cross-tenant read refused, a recipient reads only their own rows,
   default preferences leave in-app on and email on for every existing event
   type.
2. **Event catalog and write path** — `NotificationEventType`,
   `NotificationChannel`, the code-defined default-audience mapping, and the
   write helper that turns a resolved audience into
   `notifications`/`notification_deliveries` rows inside the caller's
   transaction. Tests: one event produces one row per resolved recipient, a
   duplicated trigger (the dedup key) produces one row, not two, and an
   in-app row is written even when the recipient has emailed off.
3. **Wire the three existing agent events** — `budget_exceeded` and
   `approval_requested` (and `usage_report`, if in-app is wanted for it)
   call the write helper alongside their existing email send, same trigger
   point, same audience. Tests: existing email behavior is unchanged, and the
   in-app row's audience matches the email's.
4. **Delivery sweep** — `notification_delivery_sweep` flow, bounded retry,
   `EmailKey.NOTIFICATION` template. Tests: a failed send retries up to the
   bound and then stops, a successful send is not retried, and sending never
   raises into the triggering request.
5. **New trigger points** — run failure (a scheduled/triggered run's
   initiator, closing the gap `docs/governance.md` already names for a run
   nobody is watching), ingestion completion/failure
   (`services/sync_source.py`), and security/configuration events wired at
   the existing `record_audit` call sites named in section 0. Tests: each
   trigger point produces the expected audience, and an ingestion failure for
   one organization never reaches another.
6. **Preferences API and page** — extend
   `frontend/.../settings/notifications/page.tsx` with the new event
   types and channel toggles, and `GET`/`PATCH` on
   `notification_preferences`. Tests: turning email off for one event type
   leaves in-app untouched, and an unset preference defaults to on.
7. **Announcement composer** — the `CurrentAppAdmin`-gated route, audience
   selection, audit entry. Tests: an organization admin is refused, an app
   admin's send reaches exactly the selected audience and nobody outside it,
   and the audit entry never carries the full recipient list.
8. **Retention sweep** — the daily flow, frozen-time tested.
9. **Frontend inbox** — bell with unread count (polled), paginated list,
   mark-read/mark-all-read, empty state, i18n keys, a `tour.ts` stop gated on
   the bell always being present. Tests: read state persists across reload,
   pagination, the empty state.
10. **Docs** — `docs/governance.md`'s Alerts section gains the in-app half
    (today it documents email only), `docs/permissions.md` if the composer's
    gate needs a line, and `docs/console.md` for the bell.

## Out of scope, deliberately

- Any realtime push transport (Decision 6) — open question 1 below.
- A per-organization routing UI for the event catalog (Decision 1) —
  audiences stay code-defined in phase 1.
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

## Resolved in review

*(to be filled in during review. This section records the outcomes so the
document stands as the final design rather than a set of proposals.)*
