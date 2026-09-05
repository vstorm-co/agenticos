# memory

Gives an agent a store of its own across conversations, in two shapes: named
**files** it writes and reads back by name, and short **facts** it remembers and
recalls by meaning (semantic search over pgvector). Where `context` is a library
a *person* authors and binds to many agents (read-only to the model), memory is
the agent's own — agent-written, addressed by the agent and an *owner* (the
organization, a group chat, or one person), and inspected, seeded or cleared by
operators through `/api/v1/memory`.

## Why it is not `context`, and not a knowledge base

`context` is standing knowledge someone curates; a knowledge base is a corpus
you retrieve from. Memory is neither: it is what *this agent* chose to remember,
written by a tool call mid-run. That single fact — agent-authored content
replayed into a later run — is also the whole of its risk, so the design is
built around it rather than around the happy path.

## The two things that are load-bearing, not metadata

**`origin` is a trust tier.** Every row is `operator` (written by a person
through the management API) or `agent` (written by a tool mid-run). Only
`operator` content will ever be injectable into instructions; agent-authored
content is reachable only as a tool *result*. A poisoned agent write is
therefore at worst untrusted data a later run reads, never a prompt it obeys —
and the runtime `edit`/`delete` tools refuse to touch an `operator` row
(`protected`), so an agent cannot launder its own content into the trusted tier.
The one path from `agent` to `operator` is a deliberate operator action
("promote"), never a side effect of editing.

**Whose memory a row is, and who may hear it, are two questions.** The row
answers the first: `owner_key` is `NULL` for the organization's store,
`person:<id>` for one human being, `room:<platform>:<chat>` for one group chat.
The *run* answers the second, as a `MemoryAudience` derived server-side in
`app.agents.memory_scope` — at most one person and at most one room.

Collapsing the two into one column is the defect this design exists to prevent:
a note taken alone with somebody was readable in a group channel, because "this
person's store" and "somewhere only this person is listening" had been made the
same value (#788).

Two rules follow, and every refusal in the toolset is one of them.

**Reading**: a row is readable only when everyone who hears the run was already
entitled to it. The organization's store everywhere; a room's only in that room;
a person's only where that person is the sole listener — so a direct message and
web chat read the same store, and a group channel reads neither person's.

**Writing**: writing *narrower* than the audience is always safe (the audience
already heard it, and fewer people read it back); writing *wider* is the only
dangerous direction and the only one behind a lever. So the default scope is the
audience's own store, which can leak nothing by construction, and the model is
told to omit `scope` rather than to reason about who is listening. It picks a
*store*, never a key: the keys come from the audience, so a write can only ever
reach this person's store, this room's, or the organization's.

The person is resolved account-first, which is what makes web chat and a linked
chat account one store rather than two. An unlinked chat account keys on the
identity instead. A hosted or embedded visitor has no person at all — `user_id`
there is the *publisher* standing in — so the run reads the organization store
alone and a `personal` write is **refused** rather than attributed to the owner.

Two config switches. **`allow_personal`** off drops the per-person store
entirely, for compliance or privacy; room and organization memory stay.
**`allow_agent_shared_writes`** off keeps the organization store
operator-curated: the agent reads it but a `shared` write is refused, because an
agent write is user-influenceable and a curated company memory must not be.

One completeness limit, not a correctness one: the runtime read cap (the index's
200, recall's `limit`) spans every readable store at once, with no dedup between
them, so a very large person store can crowd organization rows out of a single
read and the reverse. It bounds what one read returns, never what a run may reach.

One deliberate limit: a private run does **not** read the rooms its person
belongs to. Proving that entitlement means asking the platform for the membership
of every room on every request, which a standing brief cannot afford.

## Shapes and backends

Two shapes, each behind its own flag — **files** (`enable_files`) and **facts**
(`enable_facts`) — for seven tools: five file tools
(`list`/`read`/`write`/`edit`/`delete`) and two fact tools
(`remember`/`recall`). Facts embed on the deployment's embedding model and live
either in this deployment's own pgvector (`backend=native`, the default) or in a
mem0 service (`backend=mem0`, which needs an API key); files are always native,
because mem0 has no named-file concept.

## What is not wired yet

- **No prompt injection.** `operator`-authored files are the trusted, injectable
  tier by design, but the `get_instructions` resolution that would splice them
  into the prompt is not shipped — so there is no `injection` config field yet.
  `promote` still earns its keep: it moves a reviewed `agent` row into the
  trusted tier the console shows, the gate that feature will read.
- **Root agent only.** A delegate does not inherit the run's audience
  (`clone_for_subagent` drops it), so neither the person store nor the room is
  reachable inside a delegation — a delegate reads and writes the organization's
  store alone. That store is the *parent* agent's, because a delegate shares the
  parent's `agent_id` by design.

## Two operational footguns

- **A person store seeded from the console reaches an *unlinked* chat account
  only by its own key.** A member's key is `person:<user_id>`, and that is the
  store they reach from web chat, the API and any chat account linked to them.
  A chat account nobody has linked keys on `person:chan:<identity_id>` instead,
  so a note seeded under the member key does not come back in that chat until
  the account is linked. It is never cross-user — just a read-back gap, and
  linking closes it (see `derive_audience`).

- **Do not change `EMBEDDING_MODEL` while an agent has stored facts.** Facts embed
  on the deployment model into a fixed-width `vector(N)` column, so a model of a
  different dimension makes `remember` and `recall` fail on a dimension mismatch.
  Clear the facts first, or keep the model. Unlike the RAG store, memory does not
  yet record the embedding width per agent to guard this automatically - that guard
  is a tracked follow-up.

## Session model

The agent's runtime reads and writes never use the session the run is on: each
opens its own short-lived session (`app.services.memory._native`), for the
reason the budget baseline does — a session held across a model call is an
idle-in-transaction, and autoflush would turn a later read into a flush of a
half-written row (#12). A consequence worth stating: a memory written in a run
that later fails still persists, which is what a memory should do.
