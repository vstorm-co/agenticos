# memory_mem0

Semantic memory for an agent, kept in a [mem0](https://mem0.ai) service rather
than in this deployment. `remember` keeps a short self-contained sentence;
`recall` finds the ones a question is about by meaning rather than by name.

The counterpart to `memory_files`: that one is what the agent writes down and
looks up by name, this one is what it half-remembers. They are separate
capabilities because they are separate products — an agent binds either, both, or
neither — and folding them into one binding with a mode flag is what produced the
six-field config both of them replace (#1470).

Nothing is stored in this deployment's database, so clearing one agent's notes
does not reach these — mem0 has its own store and its own delete. Erasing a
*person* does reach them: `forget_person` calls mem0's `delete_users` for that
person's namespace under every agent that binds this capability, because a wipe
that reported success while mem0 still remembered would be worse than an error.

## Isolation is the namespace, and only the namespace

mem0's `user_id` is handed the whole scope: `{org}:{agent}:{owner}`. One mem0
account therefore cannot mix two organizations', two agents', or two owners'
memories. It is built from the run's `RunAudience` (`app.agents.audience`,
resolved to a store by `app.agents.memory_scope`), never from the model, so which
memories a run can reach obeys exactly the rule the file store obeys: one store
per conversation — a person's where that person is the sole listener, a room's
inside that room, and none at all for an anonymous visitor. There is no shared
namespace to fall back to, which is why `namespace()` requires its owner rather
than defaulting one.

That is also why the tests assert on the namespace rather than on our call to the
SDK: a test that checked we called `add` would prove nothing about whether one
tenant can read another's.

## Why the SDK, and the three guards it needs

`mem0ai`'s own client is what talks to mem0 — their API is theirs to change, and a
hand-rolled client pinned to `v1` is drift we would eat ourselves. What it is not
is safe to construct on an event loop. Each of these was checked against **2.0.20**
and each is a guard in `_client.py`:

- **`AsyncMemoryClient.__init__` makes a blocking network call.** It runs
  `_validate_api_key()`, which issues a synchronous `requests.get` against
  `/v1/ping/` — on the loop, from the *async* client. So the client is built once
  per credential in a worker thread and cached, which turns an unbounded per-call
  stall into a one-off cost off the loop.
- **Telemetry is opt-out and fires from that constructor.** `MEM0_TELEMETRY` is set
  before `mem0` is imported, rather than left to a default that one missed
  environment variable re-arms.
- **The SDK does not vet a self-hosted host.** `base_url` comes from an agent spec,
  so a builder who may bind (but not read) a shared key could otherwise point it at
  their own server and capture the key from the `Authorization` header. A
  self-hosted URL must be https and on `MEM0_ALLOWED_HOSTS`; an empty allowlist
  refuses self-hosted mem0 outright, and the managed cloud needs no entry.

One more thing worth knowing before upgrading: **`mem0/client/main.py` imports
`requests` and does not declare it**. It resolves today only because something else
in the tree pulls it in, so `requests` is declared in this project's own manifest
with that reason recorded beside it.

## Cost

mem0 bills its own embedding out of band, so the deployment's spend ledger does
not see it. That is a real difference from every other capability that embeds:
there is nothing to meter here, and a budget cap does not bound it. Say so to
anyone comparing the two memory capabilities on cost.

## What is not here

- **No operator console.** Listing and seeding memories is mem0's own surface;
  there is none here for `memory_files` either, and for the same reason.
- **No wholesale clear for one agent.** mem0 addresses memories per person, so
  there is no way to empty `{org}:{agent}:*` in one call — which is why the
  console's clear action says plainly that it does not reach mem0.
- **Root agent only**, for the same reason `memory_files` is: a delegate does not
  inherit the run's audience, so it reaches no namespace at all.
