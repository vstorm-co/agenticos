# Agentes-style thread ranges: follow-up design

## Status and dependency

This is a follow-up specification only; range context, segment moves, and returns are not implemented or validated. Draft PR 181 is the prerequisite for its room, thread, queue, permission, and realtime foundations. The implementation inspected for this design was commit `6d41fe7946e5d22d0b27a2e64f6c35807523b9d0`; source links below are pinned to that inspected baseline and do not assert that it remains PR 181’s latest head. PR 181 is not described as merged or deployed.

The pinned comparison is Agentes Chat at [`05468176f2af476513bea2bb1138d95d244d148b`](https://github.com/agentes-chat/agentes-chat/tree/05468176f2af476513bea2bb1138d95d244d148b). Its engine creates a new top-level range marker, caps selection at 500, separates context editing from moving, refuses moves with nested replies, and returns only moved IDs. Sources: [`threads.ts` marker](https://github.com/agentes-chat/agentes-chat/blob/05468176f2af476513bea2bb1138d95d244d148b/packages/engine/src/threads.ts#L43-L50), [range validation](https://github.com/agentes-chat/agentes-chat/blob/05468176f2af476513bea2bb1138d95d244d148b/packages/engine/src/threads.ts#L290-L358), [move/return](https://github.com/agentes-chat/agentes-chat/blob/05468176f2af476513bea2bb1138d95d244d148b/packages/engine/src/threads.ts#L645-L733).

## Version-one behavior

In version one, members select boundaries from top-level user or assistant messages in one conversation. Either endpoint order is accepted; normalize the pair by `Message.ordinal`, the stable transcript order, because `created_at` can tie for rows saved in one transaction. System messages, deleted rows, and existing subthread replies are not selectable or counted. Both boundary IDs must resolve to live top-level rows in that conversation.

Include eligible top-level messages between the normalized boundaries, minus explicit exclusions. Deduplicate exclusions and reject any outside the interval. Reject stale boundaries, zero included messages, and more than 500. Return normalized boundaries, exclusions, included IDs, and count; store the exact included IDs as the context snapshot so later overlapping moves cannot redefine the selection.

Creating a range thread inserts a new user-authored root marker at the current end of the room and saves its `RoomThread` context row atomically. Never reuse a selected message as root. An optional title defaults to a short one-line excerpt from the first included message. Bypass room post submission and dispatch: this action posts no prompt, mention, or agent request.

Context and placement are separate. A new range thread starts context-only. An explicit move changes only selected messages’ `thread_root_message_id`, preserving IDs, ordinals, authors, timestamps, quotes, files, reactions, and run records. Reject the entire move with a conflict if any selected message already has replies; the current thread model cannot represent nesting safely. Execute the update against the exact validated ID set and compare returned IDs with that set. If any row changed or disappeared, roll back the whole transaction and return a conflict; never commit a partial move. Apply the same all-or-nothing rule when returning IDs.

Return only snapshotted IDs still attached to the target root; never promote real replies or unrelated rows between range bounds. Retain the range as thread context. Version one requires members to return context before editing its boundaries or exclusions. This is a deliberate workflow difference from upstream, which can return and move a replacement range during one update. While moved, disable the edit control and explain that the member must return the messages first. Archived threads remain read-only.

## Storage, accepted requests, and model history

Extend `RoomThread` with nullable first and last ordinals, excluded message IDs, the resolved context message ID snapshot, a moved flag, and a monotonic context revision. The row is already scoped by organization, conversation, and root in [room_thread.py](https://github.com/t3grp/agenticos/blob/6d41fe7946e5d22d0b27a2e64f6c35807523b9d0/backend/app/db/models/room_thread.py#L23-L65). Keep message IDs as client handles and ordinals as range order. Do not add a source-conversation field in version one. A root message’s content can hold its visible title; no separate title column is required.

Replace `RoomSubmission.thread_root_message_id`’s computed `column_property` with a nullable physical column set when the post is accepted. Backfill existing rows from their associated message’s current thread root.

The current model says accepted scope is immutable, but derives it from mutable `Message.thread_root_message_id`; `authority()` uses it to reconstruct the accepted fingerprint, and history uses it to classify completed preceding runs. Keep persisted submission root as acceptance-time scope and message root as current display placement. See [room_submission.py](https://github.com/t3grp/agenticos/blob/6d41fe7946e5d22d0b27a2e64f6c35807523b9d0/backend/app/db/models/room_submission.py#L128-L138), [authority](https://github.com/t3grp/agenticos/blob/6d41fe7946e5d22d0b27a2e64f6c35807523b9d0/backend/app/services/room_submission.py#L462-L554), and [queued history](https://github.com/t3grp/agenticos/blob/6d41fe7946e5d22d0b27a2e64f6c35807523b9d0/backend/app/repositories/conversation.py#L2155-L2244).

Thread model history must include every saved context ID in ordinal order. The ordinary room window is 60 rows, but it must not silently trim a valid 1–500 range. Preserve root/replies, attachments, refusal handling, queue boundary, and exclusions for later asks and sibling threads. If model token limits prevent carrying the selection, reduce it through an explicit path or fail clearly; never imply an arbitrary subset is the saved range.

## Authorization and idle gate

Reuse `RoomThreadService` management rules: the thread starter or a room manager must have current write access. Recheck membership, project grants, room state, and authority after taking `LockScope.CONVERSATION_TURN`. Range creation, edit, move, and return are room writes, even when they do not create an agent request. Use one transaction for validation and message relationship changes so partial moves cannot be observed.

Require the whole conversation to be idle before changing context. Reject with a conflict while any `RoomSubmission` is queued, running, awaiting approval, or awaiting an answer; include a live foreground turn claim and nonterminal runs or tasks that can resume. Room queue statuses are defined in [room_submission.py](https://github.com/t3grp/agenticos/blob/6d41fe7946e5d22d0b27a2e64f6c35807523b9d0/backend/app/repositories/room_submission.py#L13-L25), and the active count is conversation-wide at [lines 129–140](https://github.com/t3grp/agenticos/blob/6d41fe7946e5d22d0b27a2e64f6c35807523b9d0/backend/app/repositories/room_submission.py#L129-L140). A room-wide gate is intentional: selected top-level messages may be context for another queued request. Check after locking and cover parked work as well as queued work.

The persisted submission scope plus idle gate freezes the range that an accepted request can observe before the worker builds history. It also prevents moving the triggering message while `authority()` or resumed work still depends on its original scope. If a later release allows editing during active work, it must add immutable per-submission context-ID snapshots and use those snapshots for every initial and resumed model request.

## API and user interface

Add create-from-range, context-update, move, and return routes beside existing room-thread actions. Creation accepts boundary IDs, exclusions, and optional title; responses return normalized metadata and the marker root. Thread reads separate `context_messages` from actual reply `items`; moved context references the original rows. Top-level transcript pages also return stubs for moved ranges overlapping the page, since source rows no longer appear there.

The timeline provides accessible start/end controls and per-message exclude/include toggles for eligible top-level rows. The panel shows context separately from replies, with move and return actions. After a move, show a compact title/count stub at the source position, linking to the marker. Distinguish invalid ranges, denied access, archived threads, nested replies, and room-busy conflicts.

Frontend integration belongs in `chat-container.tsx` for selection and stubs, `room-thread-panel.tsx` for context and actions, `room-api.ts` for calls, and room/conversation types for metadata. Publish one identifier-only thread change after commit; refresh transcript and thread detail under existing account/tenant guards. Never send message bodies or exclusions over realtime events.

Moved context is not a real reply. Exclude its IDs from unread counts, follow-by-human-replier defaults, reply notifications, and the panel’s visible read-through cursor. Only root author and actual human repliers follow by default; explicit follow or mute is unchanged. Keep read ordinals monotonic and never advance a cursor merely because older context is visible.

A move or return invalidates the thread summary, counters, transcript stubs, and thread detail after commit. It also changes what saved model history means. On range edits, increment `RoomThread.context_revision` and invalidate any root-specific history projection. On move/return, increment the conversation’s transcript-topology revision, clear its affected saved model-history summary, and fence pending compaction results against captured topology and context revisions before save. A compaction started before the change must not publish a summary built from the old selection or placement.

## Cross-room parity requirement

Cross-room context is explicitly deferred from version one. Later parity requires a source conversation identifier plus a current-audience visibility proof: every person who can read the destination must also be able to read the source. The proof must account for organization-wide public rooms, project access and grants, private-room membership, and resource grants. Recheck it whenever context is read and before every initial or resumed model request; a changed audience or revoked grant must prevent disclosure.

An initial cross-room increment may allow only same-organization public sources after proving that every destination reader is an active organization member. Project and private sources remain denied until the service can evaluate their actual reader sets. The Agentes roster-subset check cannot be copied as-is because T3OS’s project and private conversation audiences come from current permission APIs, not solely a participant roster. Report cross-room parity as outstanding until those checks exist.

## Migration, acceptance, and rollout

Add a revision after `0349_room_thread_state`. Keep context columns nullable so existing threads remain ordinary reply threads. Backfill the new `RoomSubmission.thread_root_message_id` from each associated message without changing message scope. Add constraints and indexes only after the backfill is verified. The downgrade must refuse to erase nonempty range or moved-context evidence; it may drop the additive schema only when no rows use the feature. Exercise forward and guarded rollback migrations against disposable PostgreSQL before proposing merge.

Focused backend acceptance tests cover ordinal bounds, exclusions, invalid and zero/501 ranges, snapshot stability, no-queue root creation, history beyond 60 through 500, attachments/refusals, and queue boundaries. Verify identity/order preservation, atomic nested-reply refusal, exact return IDs, and that active/parked work, claims, and nonterminal tasks block writes. Test auth rechecks, submission-scope backfill, counters, and invalidation. Frontend tests cover keyboard selection, stubs, context/reply separation, busy errors, and tenant scoping.

The acceptance sequence is migration rehearsal, focused backend and frontend suites, then a coordinated release of additive schema, compatible API/worker changes, and matching frontend. Deploy the nullable schema before code that uses it; existing threads and clients must work during rollout. Verify history construction, compaction fencing, authorization, and move/return error rates after release. If rollback is needed, revert code while retaining schema/data the guarded downgrade refuses to erase. No validation or deployment is claimed here.

Hosted-agent execution and mention-first routing are existing T3OS policies. This feature does not introduce local-device execution or change the explicit mention default. Model-based automatic reply routing remains a separate, opt-in follow-up; see [agentes-chat-parity.md](agentes-chat-parity.md).
