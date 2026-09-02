# memory

Gives an agent a store of its own across conversations, in two shapes: named
**files** it writes and reads back by name, and short **facts** it remembers and
recalls by meaning (semantic search over pgvector). Where `context` is a library
a *person* authors and binds to many agents (read-only to the model), memory is
the agent's own — agent-written, addressed by the agent and a memory tier
(shared, or one end-user's), and inspected, seeded or cleared by operators
through `/api/v1/memory`.

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

**Two tiers, and the model picks the tier but never the person.** Every memory
agent has a `shared` store (one per organization+agent, cross-user by design) and,
when a run has an identified person, that person's private store. Reads union the
two; writes carry a `scope` — `personal` or `shared` — the model chooses from
context, defaulting to `personal` when unsure. Only the *tier* is the model's: the
per-end-user key is derived server-side, never named by the model, so a write can
only ever reach the current person's own store, never another's. A run with no way
to identify the person (a hosted/widget visitor, an anonymous surface) simply loses
the personal tier — it reads shared alone, and a `personal` write is **refused**
rather than silently written to shared, which would leak one person's note to
everyone. The derivation lives in `derive_end_user_scope_key` and is wired in the
factory; it reads the request identity and no permission.

Two config switches refine the tiers. **`allow_personal`** off makes an agent
shared-only — no per-end-user store at all, for compliance or privacy — by forcing
the personal key to `None`, so the graceful-degradation path (shared reads, refused
personal writes) does the work. **`allow_agent_shared_writes`** off keeps the shared
store operator-curated: the agent reads it but a `shared` write is refused, because
an agent write is user-influenceable and a curated company memory must not be. Both
default on, the plain two-tier model; both off leaves a read-only, operator-curated
memory.

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
  (`clone_for_subagent` is untouched), so the personal tier is unavailable inside a
  delegation — a delegate reads and writes shared alone. The shared store a delegate
  reaches is the parent agent's, because a delegate shares the parent's `agent_id`
  by design.

## Session model

The agent's runtime reads and writes never use the session the run is on: each
opens its own short-lived session (`app.services.memory._native`), for the
reason the budget baseline does — a session held across a model call is an
idle-in-transaction, and autoflush would turn a later read into a flush of a
half-written row (#12). A consequence worth stating: a memory written in a run
that later fails still persists, which is what a memory should do.
