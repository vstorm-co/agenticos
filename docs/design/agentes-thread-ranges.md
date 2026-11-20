# Agentes-style thread ranges

## Status and dependency

Draft PR 190 implements the context-range follow-up to draft PR 181. The branch
contains the multiplayer recovery through
`b348ae7fb4b93c1467ff8e6b90d8da7636f682d0`. Validation results belong in the PR:
implementation in a draft branch does not establish a merge, deployment or live
provider acceptance.

The comparison is pinned to Agentes Chat
[`05468176f2af476513bea2bb1138d95d244d148b`](https://github.com/agentes-chat/agentes-chat/tree/05468176f2af476513bea2bb1138d95d244d148b).
Its [thread engine](https://github.com/agentes-chat/agentes-chat/blob/05468176f2af476513bea2bb1138d95d244d148b/packages/engine/src/threads.ts)
creates a new marker, limits a range to 500 messages, supports atomic replacement
of moved context, checks source visibility and refuses physical cross-room moves.
This implementation replaces the earlier same-room-only, return-before-edit
proposal.

## Range and placement

Select two saved top-level user or assistant messages in one source conversation.
Normalize either endpoint order by `Message.ordinal`; timestamps can tie.
Remove explicit exclusions, reject exclusions outside the interval, and require
1–500 included messages. The persisted snapshot records exact IDs rather than
re-resolving the interval on each read. Another range's root is not selectable,
and messages with nested replies cannot be moved.

Creating a range inserts a new human-authored root marker in the destination.
Same-room titles default to an excerpt; cross-room titles default to **Shared
context** so a marker does not copy private source text. Creation bypasses post
dispatch: it does not request an agent, create a queue item or notify mentions.

Context and placement are separate. New ranges start as references. Within the
same conversation, move changes only selected messages' thread root. IDs,
ordinals, authors, timestamps, quotes, files, reactions and run records remain
stable. Return restores only the exact moved IDs; actual replies stay attached.

An edit of moved context returns the old selection, validates its replacement,
then moves the replacement in one transaction. Any stale revision, missing row
or invalid nested relationship rolls back the entire operation. Archived
threads are read-only. Cross-room context remains a reference: its messages
never leave the source conversation.

## Current audience proof

Both conversations must belong to the same organization. The actor must have
current read access to both and current write/manage authority in the destination.
Project grants and private/public room membership use the canonical conversation
permission service. Enumerate active organization members using their current
role and application-admin status, then prove every destination reader may read
the source. Preserve any API-key scope while refreshing the actor.

Private and project sources also require a compatible agent audience. Public
standalone sources are available to the active organization audience. A
destination with a bearer sharing link is refused because its anonymous readers
cannot be enumerated. A public link to the source does not grant named-user
access for this proof.

The actual responder must remain on every private or project source's agent
roster throughout the inherited source graph. This also applies to main-room
answers that quote earlier derived content, not only replies inside the selected
thread. Adding a bot to an intermediate room grants no access to its private
sources.

Repeat the proof for context reads, editable candidate reads, history creation
and every initial or resumed model request. Background results returning to a
thread take the same path. Changed membership or grants therefore stop further
use of imported context. A final check under the conversation locks precedes
publication of a model result. Failed authorization preserves run usage and
failure state without saving the derived answer.

The destination inherits the read restrictions of every linked source, including
transitive references. Canonical conversation reads, files, pins, notifications,
search snippets and paged lists enforce that closure. A named destination share
does not grant source access. Bearer sharing and forks containing an imported
marker are refused because they would detach the answer from its source policy.
An iterative, bounded walk handles cycles and fails closed on an incomplete or
oversized source graph.

Rooms with imported context emit only identifiers and safe lifecycle status in
live model events. They do not stream answer text, tool payloads or questions to
cached listeners. After a successful commit, the client rereads the saved answer
through the current room policy, scoped to its account, organization and selected
conversation or thread.

## Storage and accepted requests

`RoomThread` stores source conversation, boundary IDs and ordinals, excluded IDs,
the exact included ID snapshot, moved state and a monotonically increasing
context revision. A durable `context_used` flag records a saved reply even if
that reply is later deleted. Once a request or reply has used external context,
its source cannot be replaced and its root marker cannot be deleted; editing
the selected range within the same source remains supported. This retains the
source restriction on derived answers or quotes elsewhere in the room.
Ordinary reply threads keep null bounds, empty arrays and
revision zero. Tenant/source and boundary foreign keys protect the persisted
references. A moved range must have the same source and destination.

`RoomSubmission.thread_root_message_id` is a physical acceptance-time column.
The migration backfills it from each existing prompt's current root. New root
and child requests capture it explicitly. Fingerprints, queued history, resumed
authority and answer placement use this accepted scope; the message's current
root remains display placement.

Selected model context includes the complete snapshot in ordinal order, followed
by the marker and the bounded actual-reply window. The ordinary 60-row window
does not silently trim an explicit 500-row selection. Refusal filtering and
attachments retain their existing handling. Automatic quotes cannot bring
excluded source messages back into the selected history.

## Atomic writes and history fences

Lock source and destination conversations in stable UUID order, then recheck
authority and activity. Range creation, editing, moving and returning require
both conversations to be idle. Active room submissions include queued, running,
awaiting-approval and awaiting-answer states. Also check nonterminal runs,
including children, live foreground claims, and background tasks whose source
or destination is either room, including pending result delivery.

A topology edit increments `Conversation.transcript_revision` and clears the
saved summary. The model-history fence combines that revision with the existing
refusal revision. Summary writes and each provider call reject an older fence.
Changes to a referenced source also invalidate destination history; refusal
changes cannot leave a previously built external context valid.

Every model request checks that the complete saved ID set still exists.
Deleting a middle message cannot silently shrink a selection. The same check
applies when loading context for display. An incomplete snapshot returns its saved
metadata with `stale: true` and no partial context body, so an authorized manager
can open the editor and select replacement context. Move and return stay disabled
until the snapshot is repaired; model history continues to refuse it.

## API and interface

| Operation | Route |
|---|---|
| Create range thread | `POST /conversations/{id}/room-threads` |
| Replace context | `PATCH /conversations/{id}/room-threads/{root}/context` |
| Move saved context | `POST /conversations/{id}/room-threads/{root}/context/move` |
| Return moved context | `POST /conversations/{id}/room-threads/{root}/context/return` |
| Read editable candidates | `GET /conversations/{id}/room-threads/{root}/context/candidates` |

Updates and moves carry `expected_context_revision`. An update's optional
`move` field preserves current placement when omitted, returns on false and
moves on true. Thread responses keep `context_messages` separate from actual
reply `items`; metadata names the source, bounds, exclusions, snapshot, count,
moved state, revision and whether the snapshot needs repair.

Main transcript pages return ordinal-positioned moved-range stubs. Even when
every older message is moved, the oldest surviving page retains the stub.
The UI offers source selection, accessible boundary controls, exclusions, and
direct editing of moved context. A cross-room reference exposes its source link
and editing, without physical move/return controls.

Context rows are excluded from reply counts, unread counts, automatic following,
reply notifications and read-through cursors. The root author and actual human
repliers still follow by default. Account, organization and conversation changes
clear stale selection; mutation refreshes remove returned stubs.

## Migration and validation

Revision `0352_room_thread_context` follows `0351_room_thread_state`.
Add nullable context fields and backfill accepted request scope before enabling
the new behavior. The downgrade refuses to discard used context, moved ranges
or accepted/display scope divergence. Release the additive schema before API,
worker and frontend code that uses it.

Focused acceptance covers ordinal bounds, exclusions, invalid and 501-message
ranges, 500-message history, quoted exclusions, exact moves/returns, atomic
replacement, nested-thread refusal, stale revisions, permissions and idle gates.
Real PostgreSQL checks cover constraints, backfill, guarded rollback, transcript
counts, history fences and schema drift. Frontend checks cover controls, source
selection, context/reply separation, stubs, conflict errors and tenant changes.

Full CI and Quick check remain manual-only. No deployment, live paid model call,
or multi-browser acceptance is implied by local focused tests. Hosted execution
and mention-first defaults remain the established T3OS policy. Model-based
automatic routing is tracked separately in [the shared-chat comparison](agentes-chat-parity.md).
