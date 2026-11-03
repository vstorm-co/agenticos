# Background topics

An explicit delegation opens a fresh conversation in the source project and
queues one attempt through the platform's PostgreSQL job queue. The source
conversation remains available for other questions. A terminal task queues a
separate result turn using the source agent's pinned version and current history.

This is distinct from `background_tools` and the subagents capability's async
mode, whose work belongs to one run and ends with it. It is not a watch, routine,
memory write or proactive decision. The agent may delegate requested work without requiring the person to say “background”; it may not invent new work.

The same agent or a published delegate from `AgentSpec.subagents` may work on a
topic. Its pinned version, budgets and ordinary approvals remain in force.
Delegation is bounded to four active topics per person and one level: neither a
background task nor its result turn may start another. A local target includes
the resolved device id and retains its existing native grants; coding requires an approved folder. Whole-computer
consent is never inherited by a new topic.

Completion is durable and claimed once. It waits for foreground turns, rechecks
membership and access to both conversations, and treats the result as untrusted
data, with no tools in the summary turn. The source model profile and reasoning settings are retained, including local inference. Interrupted model/tool executions are not automatically replayed, since
they may already have edited files or changed an external service. The task
record, both transcripts and ordinary run spend remain inspectable.

Cancellation is monitored by the runner on both initial and resumed segments.
A failed result turn is shown as interrupted; it is never claimed as delivered
or replayed automatically.
