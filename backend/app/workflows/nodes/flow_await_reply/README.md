# flow.await_reply

A durable, body-free expectation for an authenticated mail reply. The existing
workflow dispatch outbox owns polling and deadlines; there is no new queue,
mail watcher or model loop. See [the node reference](../../../../../docs/reference/workflow-nodes.md#flow-await-reply).

The step pins the explicitly selected organization mailbox and its authorization
generation on first execution. Criteria and pause state live in the quota-accounted
`NodeRun.resume_payload`. The normal run retention and erasure remove them.
Public resume-link calls cannot change this private state. The run principal or
an editor can correct a parked step; an in-flight check cannot be changed.

`reply` and `deadline` are exclusive routes. The latter requires a successful
bounded provider read. HTTP failures, revoked consent, unsafe pagination and
oversized threads fail explicitly. A verified reply received before the deadline
wins even if the worker wakes late. No body, attachment or arbitrary provider URL
is persisted or followed. RFC reply headers are additional filters, never authority.

Providers: [Gmail threads.get](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.threads/get)
and [Microsoft Graph messages](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0).
