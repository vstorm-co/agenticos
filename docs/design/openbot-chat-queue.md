# Durable personal chat queue

This change completes the queued-message actions in personal chat: waiting for a
full turn, sending plain-text guidance into the active turn, and moving a queued
message into an independent background task. A server receipt owns the choice.
The browser keeps unresolved messages visible while it learns the outcome.

The public instructions remain in [Console](../console.md). This document records
the execution and recovery boundaries for contributors. It does not describe a
deployment or claim full OpenBot parity.

## Admission and frozen context

Receipt admission requires a signed-in member acting in their own personal
conversation. Organization, owner, conversation and published agent are bound on
the server. Room, project, channel, draft and impersonated execution are outside
this path.

The receipt freezes the message text, ordered attachment IDs, mentioned skill
IDs, quoted-message reference and excerpt, supported page context and supported
local execution target. Acceptance validates those references and reserves the
attachments. Execution rechecks current authority; a saved snapshot is not an
access grant.

Receipt admission currently refuses per-message model or approval overrides and
local project targets that cannot be represented exactly. Testing and draft
surfaces keep their existing queue path. An accepted receipt does not inherit
later changes to the live composer's model, approval or testing controls.

A client-generated queue UUID makes acceptance idempotent within the owning
conversation. Repeating the same request returns the same receipt. Reusing the
UUID with a different payload is refused. Attachment reservation participates in
the transaction, so a racing message cannot attach a reserved upload elsewhere.

Pending and unresolved steering receipts both count toward the queue limit.
Owner recovery pages through unresolved receipts; an in-flight claim must not
disappear simply because it no longer has the `pending` state.

## One receipt, one disposition

| Receipt state | Meaning | Permitted next action |
|---|---|---|
| `pending` | Accepted, with no execution owner yet | Full turn, eligible steer, task transfer or cancellation |
| `steering` | Claimed by a particular live agent run | Confirm consumption, or release only with positive proof that no inbox consumed it |
| `steered` | Consumed by the claimed run before its provider request | Read the existing outcome |
| `sent` | Claimed by the ordinary full-turn run | Read the existing outcome |
| `task` | Transferred to one independent task | Open the returned task conversation |
| `cancelled` | Cancelled before execution ownership | Read the existing outcome |

These transitions use the conversation-turn lock and the receipt lock in one
transaction. Ordinary send, steering, task transfer and cancellation do not own
separate copies of the queued message. Losing the race returns the stored
disposition rather than starting another execution.

A terminal receipt identifies ownership of the execution, not successful model
completion. Provider failures still belong to the admitted run or task. Recovery
must not start another paid operation because an acknowledgment was lost.

## Send now remains steering

Send now uses the existing steer frame and reaches the next eligible step of the
active run. It accepts only plain text with the same active agent. Files,
mentions, quoted replies, page context and local context remain full messages or
task candidates; silently stripping those fields would change the user's input.

The frame carries the receipt ID. The server resolves the owner, conversation and
actual active run, then claims `pending → steering` against that run. A replay for
the same receipt and run is idempotent. The server does not accept a client-chosen
run as authority and does not append the same receipt twice to the live inbox.

Steering may be forwarded to a child coding-session inbox. Receipt consumption
therefore needs a marker shared by the parent and its children. Each inbox still
maintains its own application and history cursor: child consumption must prevent
an unsafe release without hiding guidance from the parent's normal transcript.

The durable `steered` transition happens before the provider request that
consumes the guidance. Receipt IDs travel with claimed, applied and unapplied
frames. The client reconciles by identity even if an applied frame arrives before
the claimed acknowledgment.

The only automatic return to `pending` is proven non-consumption by the exact
live inbox and run that claimed it. A process crash, lost acknowledgment or
uncertain consumption keeps the receipt unresolved and blocked. Timeout alone
does not prove that a model never received the text.

Run retention may clear the receipt's run reference, but it does not clear the
`steering` state or delete the receipt. Such an outcome remains visible and
blocked. A missing run reference never authorizes another run to consume it.

## Run as task

Transfer creates an ordinary private task conversation and enqueues its work in
the same database transaction as the receipt transition. The task references its
receipt as provenance instead of fabricating a source run or tool call. Retries
return the same task and its actual conversation ID.

The task executes concurrently with the original chat, using the frozen payload
and normal permissions, approvals and budgets. Supported local-device work keeps
its specific device target and rechecks availability and authority. A
whole-computer grant or routine standing consent cannot be transferred.

The result stays in the task conversation. Queue-created tasks do not manufacture
a source tool result or schedule the existing return-result path that requires a
real originating agent run.

## Client recovery

The UI retains a row while accepting, transferring or steering. Confirmed
terminal outcomes remove it; a refused operation preserves the message and its
context. Transport failure causes receipt reconciliation, not blind execution
replay.

Recovery and asynchronous completions are fenced by the active account,
organization, conversation and selection generation. Returning from A to B to A
must not make the first visit's delayed completion current again. Task navigation
uses the task's returned conversation ID, not the receipt's source conversation.

The receipt-enabled path refuses automatic drain when the receipt is absent or
unconfirmed. Falling back to the old local queue in that situation would bypass
the server claim. Restored attachment IDs remain visible as attachments even when
the browser has no cached preview card.

## Database and rollout

The new revision is `0357_accepted_queued_messages.py`, following
`0356_trigger_webhook_receipts.py`. Existing deployed revisions keep their IDs
and parents. API, worker and console code must be released with the matching
schema.

The schema adds the receipt journal and nullable provenance on ordinary messages,
runs, uploads and conversation tasks. Existing tasks retain their real source
run and tool call. Queue-created tasks use receipt provenance, with a database
constraint requiring exactly one provenance form.

The three existing-table unique indexes build concurrently. Adding nullable
columns and attaching constraints still need brief catalog locks, with a
five-second lock-wait limit. Foreign keys and checks are added without scanning
old rows under those locks, then validated in separate statements. Rehearse the
index work and lock windows on a production-sized copy before release.

An interrupted upgrade may leave nullable columns and standalone indexes. Retry
verifies their definitions, reuses exact valid indexes, rebuilds exact invalid
standalone indexes and refuses conflicting objects or another active build. If
constraint validation was interrupted, retry verifies the committed schema before
resuming validation. Do not activate the new application until the revision
completes. Downgrade refuses any retained receipt under a table lock.

A private conversation cannot convert into a room while it has an unresolved
queue receipt. The conversion guard uses the same conversation lock so admission
and conversion cannot race to widen a frozen personal message's audience.

## Verification boundaries

Focused PostgreSQL tests must prove concurrent claims, attachment reservation,
owner and tenant isolation, revoked authority, task provenance, and upgrade and
downgrade behavior. Steering tests must cover duplicate frames, child consumption,
late guidance, lost acknowledgments and safe non-consumption release.

Focused client tests must cover receipt recovery, stale completions, both action
buttons, lost transfer responses, missing receipts and retained context. The
existing ordinary queue, steering and task paths remain regression targets.

Full coverage suites, compiler checks, production builds, live-provider execution,
release migration rehearsal and deployed acceptance are separate evidence. A
draft feature PR does not establish those outcomes.
