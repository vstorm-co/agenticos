# Personal cloud coding sessions

The maintainer chose named, resumable Claude Code and Codex sessions in the same
agent. Different accounts run concurrently; work sharing an account waits for its
exclusive credential lease. Existing sandbox-key and desktop modes keep their
execution and authorization policies.

Use the existing user-scoped service workspaces, with a server-derived namespace
for account generation, conversation, agent and session name. Record the coding
account association and initial source revision on the workspace row. Native CLI
history and files remain in that private container; each task injects only the
initiating person's current account. Never put account credentials in a spec or
session marker. The normal provider idle expiry still applies; missing remote
state must be reported rather than called a successful continuation.

Personal workspaces are excluded from a conversation's ordinary source workspace
and are readable through workspace APIs only by their coding-account owner.
Conversation deletion, account revocation/disconnect, membership removal and user
or organization deletion must queue remote cleanup before cascades remove refs.
Use the existing durable sandbox-destroy mechanism. Recheck current membership,
conversation trust and account generation after waiting and before publication.

Continue native session history by the existing `session` argument, keeping each
name's files separate. `fresh_session` resets CLI conversation history and keeps
that workspace's files. A new name starts from the current source copy. Pin model
and effort to the harness they belong to. Preserve read-only restrictions and
never fall back to an organization key when a personal account is unavailable.

Bound detached coding processes on the host as well as in the caller, so a lost
worker cannot outlive its credential lease. Test timeout/cancellation, same-account
serialization, cross-harness overlap, session continuation and isolation, cleanup,
transaction rollback and tenant/owner refusal against the appropriate layers.
