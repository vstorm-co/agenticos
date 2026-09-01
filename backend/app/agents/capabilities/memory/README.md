# memory

Gives an agent a store of its own across conversations, in two shapes: named
**files** it writes and reads back by name, and short **facts** it remembers and
recalls by meaning (semantic search over pgvector). Where `context` is a library
a *person* authors and binds to many agents (read-only to the model), memory is
the agent's own — agent-written, addressed by the agent plus an end-user
partition, and inspected, seeded or cleared by operators through `/api/v1/memory`.

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

**`partition` decides who shares a memory.** `shared` is one store per
(organization, agent) — cross-user by design, for a single trusted audience.
`per_user` is a private store per end-user, and the per-end-user key is derived
server-side, never chosen by the model. A `per_user` run with no way to identify
the person (a hosted/widget visitor, an anonymous surface) **refuses** rather
than falling back to a shared store — collapsing a private partition onto a
shared one is the cross-user leak the capability exists to prevent. The
derivation lives in `derive_end_user_scope_key` and is wired in the factory; it
reads the request identity and no permission.

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
- **Root agent only.** A delegate does not derive its own end-user key
  (`clone_for_subagent` is untouched), so `per_user` memory refuses inside a
  delegation. Shared memory a delegate reaches is the parent agent's, because a
  delegate shares the parent's `agent_id` by design.

## Session model

The agent's runtime reads and writes never use the session the run is on: each
opens its own short-lived session (`app.services.memory._native`), for the
reason the budget baseline does — a session held across a model call is an
idle-in-transaction, and autoflush would turn a later read into a flush of a
half-written row (#12). A consequence worth stating: a memory written in a run
that later fails still persists, which is what a memory should do.
