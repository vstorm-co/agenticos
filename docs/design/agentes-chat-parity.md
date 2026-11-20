# Agentes-style shared chat

This change brings human and agent conversations onto the same room model. A
person can add colleagues to an existing agent conversation, add agents to a
human discussion, and address either with `@`. Converting a conversation keeps
its identity and saved history.

## Reference

The comparison uses [Agentes Chat](https://agentes.chat), pinned to
[`05468176f2af476513bea2bb1138d95d244d148b`](https://github.com/agentes-chat/agentes-chat/tree/05468176f2af476513bea2bb1138d95d244d148b).
The implementation follows behavior and uses T3OS's existing permission, queue,
notification, attachment and transcript services.

| Behavior | Reference source | T3OS implementation |
|---|---|---|
| Public/private rooms and explicit human/agent membership | [`channels.ts`](https://github.com/agentes-chat/agentes-chat/blob/05468176f2af476513bea2bb1138d95d244d148b/packages/engine/src/channels.ts) | `RoomParticipantService`, room directory and participant controls |
| Identity-based mentions and selected bot responders | [`messages.ts`](https://github.com/agentes-chat/agentes-chat/blob/05468176f2af476513bea2bb1138d95d244d148b/packages/engine/src/messages.ts), [`dispatch.ts`](https://github.com/agentes-chat/agentes-chat/blob/05468176f2af476513bea2bb1138d95d244d148b/packages/engine/src/dispatch.ts) | `RoomMessageCreate.mentions`, canonical saved recipients and one queued request per selected agent |
| Human mentions notify without adding members | [`notification-producers.ts`](https://github.com/agentes-chat/agentes-chat/blob/05468176f2af476513bea2bb1138d95d244d148b/packages/engine/src/notification-producers.ts) | `room_mention`, current conversation access checked again when read |
| Thread follow, unread state and lifecycle | [`threads.ts`](https://github.com/agentes-chat/agentes-chat/blob/05468176f2af476513bea2bb1138d95d244d148b/packages/engine/src/threads.ts) | Room thread state, explicit follow/mute and a cursor through the last viewed reply |
| Emoji reactions and attachment sharing | [`chat.ts`](https://github.com/agentes-chat/agentes-chat/blob/05468176f2af476513bea2bb1138d95d244d148b/apps/server/src/routes/app/chat.ts) | Human emoji aggregates, existing upload cards and attachment routing in room posts |

Agentes fixes a direct message at two participants. In-place conversion to a
larger room is intentional here: the requested workflow lets a person add any
eligible agent or colleague to the conversation they already have.

## Membership and authority

`Conversation.room_visibility` is null for existing personal conversations, or
`private`/`public` for explicit standalone rooms. Public means visible to active
members of the organization. Joining is an explicit action before posting.
Private room membership grants conversation access; it grants no access to a
different organization, a project or an agent's private configuration.

The owner or an existing editor manages people, removals and automatic reply
settings. A joined member can add an agent they may run. Mention candidates carry
separate `is_member`, `can_add` and `can_mention` decisions. An outsider is added
through an explicit action before it can be mentioned; text never grants access.
The owner cannot be removed from the roster.

Project rooms retain the project's permission boundary. Their human audience is
derived from current project access, including grants, rather than a second
roster that could accidentally widen it. Adding an agent does not share the
project with another person. Human access is managed through project sharing.

Converting a personal conversation seeds its owner and historical agent
responders once. Later changes do not re-add a removed historical agent. The
confirmation explains that new participants can read the existing history.
Conversion must wait for private work already in progress to finish or be
cancelled, so a running private context cannot become a live shared answer.

## Posts and replies

The composer stores mentions as `{kind, id}` references independently of their
labels. Duplicate names remain distinct. Editing away a selected mention removes
its recipient; typing a matching name without selecting a candidate does not
silently invoke it.

A post can contain up to ten explicit recipients and ten uploaded files. The
server validates every selected recipient and runnable agent before saving the
post. One human message owns the files, quote and canonical mention names. Each
requested agent gets its own durable request, pinned to the published version
accepted at submission. The primary request retains the original message's run
link; later responders use the same source without replacing that link.

All room and subthread requests share the existing ordered queue. An answer sees
earlier conversation context and completed replies before its queue position,
including an earlier responder to the same post. It does not read later human
questions or unrelated thread replies. Admission, resumed work and subsequent
model requests recheck the original requester's current authority.

The idempotency fingerprint includes text, quote, thread, selected identities,
files and responder intent. An uncertain retry uses that frozen payload and
returns the same original requests. It never resolves a different set of agents
or sends another mention alert. A worker with an uncertain external outcome is
not automatically restarted.

## Optional automatic replies

New agents are mention-only by default. A manager may opt a room agent into
automatic replies. This differs from Agentes's default and matches the requested
explicit-mention workflow.

T3OS uses a bounded deterministic selector for those opted-in agents. Simple
acknowledgements select none; a named candidate is preferred; a broad request can
select at most four; otherwise the first eligible configured agent is selected.
Explicit human or agent mentions are not expanded. The selected responders are
frozen with the accepted post. This is not Agentes's model-based routing policy.

`Ask lead` remains a separate explicit planning action. Human mentions may
accompany it. Agent mentions and `Ask lead` cannot be combined, and the composer
explains that conflict without deleting the selected recipients.

## Files and shared context

Room uploads use the existing file service, type/size limits and download access
checks. Attachment-only posts are valid. Every file must be the sender's own
unclaimed upload; linking the files, saving the post and queueing replies happen
in one transaction. A retry reads those already-linked files instead of claiming
them again.

Each responder routes the files through its own existing `AttachmentRouter`,
including its workspace and input screening. `saved_prompt_id` keeps the runner
from recording a second human turn. The first responder owns the shared history
projection; later responders cannot replace it with a less restrictive copy.
A guardrail refusal from any responder also fences the shared source from later
history. A missing or moved attachment invalidates pending authority checks.

Standalone rooms use a room memory key and shared workspace protection. Room
admission excludes personal memory and signed-in browsing even if a caller uses
an older chat entry point. Paused room work is resumed under the original
requester's current room and agent permissions.

## Reactions and thread state

Reactions are one signed-in person's emoji on a saved human or assistant message.
Ensure-on and ensure-off requests are idempotent. There can be at most twenty
distinct emoji on one message; another person can join an existing emoji at that
limit. Responses aggregate count and the current viewer's own selection, without
returning an actor directory.

A thread can be open, closed or archived. A new reply reopens a closed thread.
An archived thread does not accept replies; unarchiving restores the state it had
before archiving. The starter and human repliers follow by default. An explicit
mute overrides that default, while a direct mention still sends its own alert.
Reply notifications exclude the author and people already mentioned in that reply.

Reading the room does not mark all its subthreads read. A thread cursor advances
through a validated visible message ID. Replies arriving after that position stay
unread. Root message summaries show thread state, following and unread count
alongside the existing reply count and last activity time.

## Realtime and migrations

Existing room message and run streams remain the delivery paths. Membership,
reaction and thread changes publish identifiers only after commit. Readers then
fetch the authorized durable rows. Membership invalidation first clears the
socket's cached access decision; a removed private member stops following before
another room event is relayed. Polling remains a recovery path.

The migration chain continues from `0347_network_connections` through
`0348_room_participants`, `0349_room_mention_requests`,
`0350_room_message_reactions` and `0351_room_thread_state`. Legacy room requests
remain primary requests with explicit dispatch. Downgrades refuse to erase used
feature evidence. Schema changes are exercised against disposable PostgreSQL;
production migration and deployment are separate operations.

## Deliberate limits and validation

The room worker executes published cloud-compatible agents. Desktop and personal
sandbox execution still depend on a person's connected device and are not
silently moved into a server job. Automatic selection is bounded rules rather
than an additional paid routing model. Existing quotes, pins, search, thread
navigation and presence are reused.

This comparison does not cover Agentes's wiki, business applications or plugin
ecosystem. Advanced thread context ranges and moving conversation segments are
distinct from the existing reply threads and are not claimed by this change.

Validation is recorded in the PR with the exact focused suites and migration
rehearsals. Local tests do not establish deployed, multi-browser acceptance or a
live provider run.
