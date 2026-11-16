# Room lead routing and task handoffs

**Status: proposal only.** This document adds no agent routing, task table,
conversation fork, thread, attachment feature or automatic dispatch.

Baseline: T3OS `080c12941ed06cce2e92b6b03910e94ace36469e`, inspected on
14 November 2026. Product benchmark:
[OpenBot v0.71.0](https://github.com/nightly-labs/openbot/releases/tag/v0.71.0).
The feature gap is room-level lead routing and visible handoffs, not the absence
of durable tasks or human review.

This continues [Agent and team tasks](agent-tasks.md), an older proposal. The
current code already implements much of that proposal. Preserve the older text
as history and use the verified baseline below for implementation.

## Existing systems and the remaining gap

| Verified existing source | Current behavior to preserve |
|---|---|
| `backend/app/services/room_submission.py`, `db/models/room_submission.py`, `schemas/room_submission.py` | Durable human posts, explicitly selected agent/version, ordered requests, idempotent submission and requester authority checks. |
| `backend/app/services/chat_room.py` and `worker/tasks/room_tasks.py` | Room events and queued execution. A socket is not the source of truth. |
| `backend/app/services/tasks.py` and `schemas/task.py` | Canonical task boards in Virtual Tables, human and agent assignees, optimistic revisions and explicit next actor. |
| `backend/app/services/task_execution.py` | Deferred execution, review handoff and refusal of an executing agent closing its own task. Completed runs become `waiting_for_user`; failures become `blocked`. |
| `backend/app/services/project_tracking.py` | Reviewed project tracking linked to an existing shared task board and routine. |
| `backend/app/services/conversation_tasks.py` | Private background topic delegation and return, with its own source-conversation authority restrictions. Do not remove those restrictions for room routing. |
| `frontend/src/components/chat/team-room-responder.tsx`, `team-room-queue.tsx` | Explicit responder choice and visible pending requests. |
| `frontend/src/components/tasks/tasks-panel.tsx` | Existing task display and edit surface to reuse. |

Add an optional named lead agent to a project room. A person can explicitly ask
the lead to answer or propose a handoff. Accepted handoffs create or reference
existing project tasks, with visible ownership and status in the room.

A normal human message stays a human message. Choosing a lead does not invoke
an agent on every post, authorize all specialists or cause agents to respond
to each other's summaries indefinitely.

## Dependency on active subthreads work

Implementation depends on the accepted result of
`feat/multiplayer-subthreads-20261114`, currently an active work branch.
Rebase against its final reviewed commit before wiring room cards to threads.
Do not assume the branch is merged or deployed.

That work owns subthread identity, parent-message relationships, room membership
inheritance and thread navigation. This proposal references its stable thread
identifier only after its contract is accepted. It does not create another
thread table, fork route, reply protocol or attachment implementation.

The current `reply_to_message_id` in room posts is not treated here as proof
that the new subthread contract is complete.

## User flow

1. A member with project edit authority chooses a published lead agent and an
   allowed specialist list for the room. The server verifies those resources.
2. A participant chooses **Ask lead** on a message. The resulting submission
   names the requester and pinned lead version, as current room requests do.
3. The lead answers directly or proposes one or more task cards: title, expected
   result, specialist, accountable person, due time and review recipient.
4. The requester reviews the proposal. The first release requires human
   acceptance before creating tasks or starting specialists.
5. Each accepted item links to one task on the existing project board. The room
   shows its current canonical status and next actor.
6. The existing task execution path runs accepted work. Completion becomes
   **Waiting for review**, not **Done**.
7. The authorized reviewer accepts, requests changes or cancels through the
   existing task/outcome flow. The room card reflects the resulting state.

The lead cannot assign a person who lacks the required board access or spend a
specialist the requester cannot run. Being configured as a possible room lead
does not give every room participant that lead's private privileges.

## Proposed policy and proposal data

A room routing policy contains `organization_id`, `conversation_id`,
`lead_agent_id`, `lead_version_id`, permitted specialist ids/versions,
`enabled`, `max_items` and `revision`. The default is disabled.
Start with at most three proposed handoffs per explicit request.

A routing proposal records source room/subthread, source submission and message,
requester, frozen policy revision, lead run, item descriptions, proposal hash and
decision. It contains no credentials or private conversation transcript.
A proposal's text is untrusted model output until validated and reviewed.

Proposed item example:

```json
{
  "proposal_item_id": "<stable proposal item>",
  "title": "Reconcile the reviewed invoice batch",
  "expected_result": "A reconciliation file with the mismatches identified",
  "agent_id": "<authorized published specialist>",
  "agent_version_id": "<pinned version>",
  "accountable_user_id": "<eligible project member>",
  "due_at": "2026-11-16T09:00:00+08:00",
  "existing_task_id": null
}
```

A new `room_task_links` record stores only linkage and dispatch provenance:
organization, room/thread, source submission, proposal item, canonical task id,
accepted revision, requester and idempotency key. Task title, assignees, due time
and status stay in the existing task row, not a second mutable task store.

The expected result belongs in the task description initially. If a later typed
result/evidence field is added, extend the canonical task schema once and update
all task surfaces; do not hide a competing value in room metadata.

## APIs and dispatch contract

| Proposed route | Contract |
|---|---|
| `GET/PUT /v1/conversations/{id}/lead-policy` | Read eligible policy metadata or update it with expected revision. Resolve current project/room authority in the service. |
| Existing room-message creation | Support an explicit 'ask lead' intent resolved server-side to the policy's pinned agent/version. An omitted agent/intent still creates a human-only post. |
| `GET /v1/conversations/{id}/routing-proposals/{proposal_id}` | Authorized room members see a sanitized proposal; hidden resources are not enumerated. |
| `POST /v1/conversations/{id}/routing-proposals/{proposal_id}/accept` | Accept selected items with expected proposal revision and an idempotency key. Revalidate requester, policy and each resource. |
| `POST /v1/conversations/{id}/routing-proposals/{proposal_id}/discard` | Final decision with no task creation or dispatch. |
| `GET /v1/conversations/{id}/task-links` | Return room-safe cards derived from authorized canonical task rows. |

Acceptance runs in the request transaction. It uses `TaskService.create` with a
stable external id derived from the room proposal item, or verifies an explicitly
selected existing task. The task revision and link are committed before the
existing durable worker is allowed to execute. Use the existing background queue,
not socket events, to schedule work.

For existing tasks, the requester must already have edit authority and supply
the expected revision. Acceptance never silently overwrites another person's
assignment, changes a task's project or duplicates a task owned by an external
tracker. An external tracker link remains a link; its original tracker retains
authority unless the operator explicitly chooses local ownership.

The first release dispatches through the existing task lifecycle. It does not
force shared-room input through the private `ConversationTaskService.start`
path, whose owner-only source constraint is intentional. Future room-native
background topics need a separately reviewed adapter that preserves requester
identity and room audience; removing the private check is not that adapter.

## Status and review behavior

Use the canonical statuses unchanged:

| Canonical task state | Room card behavior |
|---|---|
| `planned` | Assigned and waiting for the scheduled start or next actor. |
| `in_progress` | Show linked execution and authorized next actor. |
| `waiting_for_user` | Show review needed and the authorized reviewer. Do not imply completed business work. |
| `blocked` | Show a bounded blocker and the next permitted action. |
| `done` | Reflect the accepted canonical task state and accessible evidence link. |
| `cancelled` | Show cancellation; never retry merely because the room reconnects. |

The lead may summarize visible state. It cannot set `done` because an execution
returned a successful status, accept its own result, create recursive handoff
trees or start new work from a delivered result. A manual reassignment increments
the task revision and makes stale proposed updates conflict.

Room cards do not reveal private working chats or Inbox cases. The current
`TaskService.get` intentionally limits those links. A result becomes visible in
the room only through a deliberate authorized summary/evidence attachment that
the room audience may access. Do not copy a private result body to make a card
look complete.

## Security and concurrency

Resolve room/project membership, task-board access and runnable agent versions
again at acceptance and execution. Use the original requester's current
authority, not the lead's author, project owner or worker's service account.
Revocation before execution blocks admission. Revocation during execution follows
existing cancellation and result-export checks.

Per-resource endpoints call services using `resolve_access`; a role-name check
must not erase a valid grant. Every id is organization-scoped and foreign-room
or foreign-thread ids are refused without disclosing their existence.

The source client message id, proposal item id and stable task external id form
the deduplication chain. Concurrent acceptance can produce one task and one
dispatch per item. An uncertain response is reconciled by that identity before
retry. Concurrent policy, assignment or task edits return `409` rather than
choosing whichever write finishes last.

No email, external chat message or third-party tracker write is sent just because
the lead assigned a task. External actions keep their ordinary explicit authority
and approval flow.

## Implementation and acceptance

| Slice | Result | Required evidence |
|---|---|---|
| 1. Lead policy | Optional pinned lead and explicit Ask lead intent | Human-only posts remain inert; inaccessible or unpublished agents are refused; policy edits conflict correctly. |
| 2. Routing proposal | Validated proposal cards with human accept/discard | Model text cannot create tasks; item count bounded; recipient/agent authority verified; unrelated private metadata withheld. |
| 3. Task linkage | Canonical task creation/reference and one durable dispatch | Repeated/concurrent acceptance creates one task; queue restart cannot duplicate work; stale task revision is refused. |
| 4. Room status | Cards reflect canonical lifecycle and reviewed outcome | Agent cannot close its task; private working chats/results stay private; reviewer decision appears without polling-induced writes. |
| 5. Subthread integration | Cards and return summaries use accepted thread identity | Membership changes, account switches and foreign thread ids cannot cross audiences; no duplicate thread/fork/attachment code. |

Use synthetic projects, two authorized members, one outsider and two
organizations. Exercise human-only discussion, Ask lead, acceptance, task
execution, waiting-for-review, authorized completion, cancellation and
revocation. Include lost-response replay and two concurrent acceptors.

Do not provision a new task table for every agent or silently install a project
tracking routine. Existing task boards and reviewed tracking remain the only
sources of those resources.

## Rollout and rollback

Enable lead policies per room after the subthreads dependency and normal release
gates pass. Start with manual acceptance only. Any future automatic handoff mode
requires an explicit room policy with budget, eligible agents and dispatch bounds.

Disabling lead routing stops new proposals and acceptance; it does not cancel or
delete already accepted tasks. Existing tasks continue through their canonical
lifecycle. Room cards remain readable where authorized, and a link can be
removed without deleting the underlying responsibility.

No migration number is reserved here. Published documentation, onboarding,
translations and dashboard/room activity integration belong to the implementation
PR, not this proposal-only repository note.
