# memory_files

Gives an agent notes of its own across conversations, kept as named files and
indexed by one it maintains itself.

`MEMORY.md` is the whole idea. It is an ordinary note — the agent writes and edits
it with the same tools as any other — and it is **spliced into the agent's
instructions every request**, the way a bound context file is. It lists what the
agent has saved, a line each, so the agent meets its own index before it decides
anything and opens a listed note with `read_memory` when the line says it is worth
reading. That is deliberately the shape Claude Code uses.

Where `context` is a library a *person* authors and binds to many agents
(read-only to the model), memory is the agent's own: nobody else writes here at
all. That is the line between the two features rather than a limitation, and it is
why there is no authoring surface, no listing and no `origin` column.

## Why it is not `context`, and not a knowledge base

`context` is standing knowledge someone curates; a knowledge base is a corpus you
retrieve from. Memory is neither: it is what *this agent* chose to keep, written
by a tool call mid-run. That single fact — agent-authored content replayed into a
later run, and here into the *instructions* — is also the whole of its risk, so
the design is built around it rather than around the happy path.

## One store per conversation, and it is not the model's to choose

`owner_key` says whose a note is: `person:<user_id>` for one human being,
`room:<platform>:<chat_id>` for one group chat. There is no third value — the
organisation-wide store went, because it was a second mechanism for what `context`
already does and the console was its only author (#1470).

**Whose the note is, is not the same question as who may read it back.** The row
answers the first; the *run* answers the second, as a `RunAudience` derived
server-side in `app.agents.audience` — at most one person and at most one room.
Collapsing the two into one column is the defect this design exists to prevent: a
note taken alone with somebody was readable in a group channel, because "this
person's store" and "somewhere only this person is listening" had been made the
same value (#788).

The rule that follows is one sentence: **a run touches exactly one store, the
conversation's own.** In a group chat that is the room's, and everyone in the chat
reads it; one to one it is that person's, and nobody else ever does; on a public
widget or an embed there is nobody to attribute anything to, so there is no store
and the tools say so.

That is deliberately not "read a union, write the narrowest". The union is what
the old shape had, along with a `scope` argument the model chose — and a model
that chose `personal` in a channel wrote a private note out of a public
conversation. There is nothing to choose now: no tool takes a store, and
`app.agents.memory_scope` resolves the one this run has.

The person is resolved **account-first**, which is what makes web chat, the HTTP
API and a linked chat account one store rather than three. A hosted or embedded
visitor has no person at all — `user_id` there is the *publisher* standing in — so
the run has no store and a write is refused rather than attributed to the owner.

## What may be injected, and what may only be fetched

The tools answer with tool *results*, which a model weighs. `MEMORY.md` becomes
the model's *instructions*, which it obeys. So the injected set is narrower:
`may_inject_memory` is where the rule lives, and an index reaches the prompt only
where its content could have steered nobody but its reader.

| Audience | Reads | Injected |
|---|---|---|
| One to one | that person's notes | yes |
| A group chat | the chat's notes | never — reachable with `read_memory` |
| Anonymous | nothing | nothing to inject |

The room row is the reason this is a rule rather than "inject whatever the run can
read": a room's store is self-scoped to nobody, so one colleague's crafted
sentence would arrive as another colleague's instructions in the same channel —
a prompt-injection channel between colleagues rather than a shared memory.

An index over ~6,000 characters is dropped rather than truncated. It is an
ordinary note, so its body is unbounded; injecting it whole would let one
`write_memory` push the preamble out of the window, and half an index — ending
mid-line, mid-filename — is worse than none.

## Config

One field — `allow_personal`, off to drop the per-person store for compliance or
privacy; the notes kept in group chats stay. This capability used to be one
binding with six fields, two of which chose between products that are now two
capabilities (#1470).

## Erasing it

Nothing browses these notes. What there is, is deletion, and it comes in two
shapes because they answer different questions:

- **Forgetting one person** spans every agent in the organization, because "forget
  everything you know about me" is a fact about a person rather than about one
  agent they happened to talk to. A person may always erase themselves; erasing
  somebody else is `members:manage`.
- **Clearing one agent** removes every note that agent holds, in every store —
  a store nobody can clear is a liability (#788). It is gated per row through
  `resolve_access`, so a grant on that agent widens it.

Both live in `app.services.memory.facade`, and the first reaches mem0 as well
where an agent binds it: a clear that reported success while mem0 still remembered
would be a partial wipe wearing a success.

## What is not wired yet

- **Root agent only.** A delegate does not inherit the run's audience
  (`clone_for_subagent` drops it), so a delegation reaches no store at all.
- **A private run does not read the rooms its person belongs to.** Proving that
  entitlement means asking the platform for the membership of every room on every
  request, which a standing instruction block cannot afford. A deliberate limit,
  not an oversight.

## The operational footgun

**An index the agent forgets to update is an index that lies.** `MEMORY.md` is
maintained by the agent as an ordinary write, so a note saved without a line added
to it is a note the agent will not know to look for. `list_memory` is the ground
truth and exists for exactly this; the tool descriptions tell the model to keep the
index current after every save and delete.

## Session model

The agent's runtime reads and writes never use the session the run is on: each
opens its own short-lived session (`app.services.memory._native`), for the reason
the budget baseline does — a session held across a model call is an
idle-in-transaction, and autoflush would turn a later read into a flush of a
half-written row (#12). A consequence worth stating: a note written in a run that
later fails still persists, which is what a memory should do.
