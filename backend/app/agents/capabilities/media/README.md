# Media offload

Keeps a compacted conversation's pictures out of the database and off the wire.
Contributes no tools: it rewrites what is *stored*, not what the model can do,
so there is nothing here for a model to call or a person to approve.

The content-addressed stores and the walkers come from
[`pydantic-ai-harness`](https://github.com/pydantic/pydantic-ai-harness), whose
own README says plainly that they are building blocks and not a capability. What
this package adds is the two things a multi-tenant platform has to: where the
bytes go, and when the walk runs.

## The one place media actually piles up

An attachment reaches the model **once**, on the turn it was attached.
`AttachmentRouter` inlines a small image as `BinaryContent` and writes a larger
one to the workspace with a path reference; the next turn's history is rebuilt
from the transcript's *text* (`build_message_history`), so the picture is not
re-sent. There is nothing to offload there.

The exception is a conversation that has been **compacted**. Then the library's
own dump of `all_messages()` is stored in `conversations.summary_messages` and
replayed exactly as the model last saw it — base64 and all — until the next
summary replaces it. That blob is rows in Postgres and bytes on the wire, every
turn in between, and it is what this capability is for. `PausedRunState.messages`
has the same shape for a run parked on an approval.

## Where the bytes go, and how long they live

`OrganizationMediaStore` is a `MediaStore` over `BaseFileStorage`, so offloaded
media lands wherever uploads land rather than in a second place with its own
backup story. The path is `media/<organization>/<conversation>/<digest>`, and
each of those three parts earns its place.

**The organization is the isolation.** A media URI is a content hash, so two
tenants whose runs contain the same picture compute the same URI. The
organization comes from the run — through `resources`, never from configuration
and never from the URI — so a hash is only ever resolved inside the tenant that
wrote it.

**The conversation is the lifetime**, and this is the part that is easy to get
wrong. A content-addressed object records nothing about who still references it:
replacing a summary, deleting a thread or deleting a tenant would otherwise leave
the bytes behind for ever, which is the exact failure a feature about not
accumulating bytes must not have. Under a thread's own prefix the answer is
structural — `ConversationService.delete_conversation` removes the prefix,
`OrganizationService.purge` removes the tenant's — at the cost of storing the
same picture twice if it appears in two threads. For the same reason a run with
**no** conversation offloads nothing: there would be nothing to delete it with.

A summary replaced by a later one leaves its objects under the thread's prefix
until the thread goes. That is bounded rather than immediate, and it is the
honest description: tracking per-summary references would be a table, and the
bytes are already the thing this capability took out of the row.

`public_url` answers `None` deliberately. The harness's forthcoming externalizer
uses one to hand a *model* a URL it fetches itself; these bytes are a tenant's,
behind this deployment's authentication, and a URL a model provider can fetch is
a URL anybody can.

## Offloading is optional, restoring is not

Binding the capability is the decision to offload — on every surface: both
`ChatAgentRunner.run` and `AgentRunnerService._run` offload through the same
helper, so the API, a channel mention, an embed and a trigger get what the
WebSocket chat gets. Restoring is unconditional, in
`ConversationService.model_history`: a conversation whose agent was unbound
afterwards still has markers in its stored history, and a marker nobody
re-inlines is a picture the model is handed in a language it does not read. The
walk over a history carrying none is a tree traversal that changes nothing.

Both directions fail soft. The alternative to a smaller history is the history,
and losing a summary — which a model was paid to produce — because a store hiccuped
is the worse outcome. A failure is logged and the history is used as it stands.

## What it does not do

**It does not reduce what the model is sent.** The markers are re-inlined before
the request goes out, because that is what keeps the run correct. Rewriting
`BinaryContent` to a URL the model fetches itself is the harness's own #254 and
would need a URL this store deliberately does not issue.

**It does not touch an attachment's own storage.** `ChatFile` rows and their
bytes are the upload path's, with their own lifecycle; this only ever writes the
copies that were about to be stored inside a history blob.

**It does not meter vision tokens separately.** An inlined image's input tokens
are part of the main model request and reach the ledger through it, the way every
other input token does.
