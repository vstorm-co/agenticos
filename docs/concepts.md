# Concepts

Five nouns. Everything in the product is built from them, and most confusion
about it comes from conflating two.

```mermaid
graph LR
    S[Spec] -->|publish freezes| V[Version]
    V -->|an exposure admits a caller| E[Exposure]
    V -->|a trigger fires on a schedule or an event| T[Trigger]
    E -->|one execution| R[Run]
    T -->|one execution| R
    R -->|records| C[cost, tokens, version]
```

## Spec

**The agent, as data.** Instructions, a model profile, capability bindings,
collection and skill references, a budget, and who to tell when something
happens. Defined in
[`app/agents/spec.py`](reference/spec.md) and validated by Pydantic.

Two rules the spec keeps, and they are what make it useful:

**References, never values.** A spec names a model profile, a collection, a tool
id. It never embeds a model string, a connection string or a secret. That is what
makes it safe to commit to a client's repository, and what lets an organization
rotate a key without touching a single agent.

**Additive evolution.** New fields get defaults, so an agent published today
still loads after an upgrade. Removing or renaming a field is a migration, not an
edit.

An agent has exactly one *draft* spec, which the Builder edits and saves
continuously.

## Version

**A frozen spec.** Publishing copies the draft into a version and points the
agent at it. Runs record which version executed.

This is why "what did this agent do last Tuesday" stays answerable after a dozen
edits, and it is why a rollback publishes a *new* version copied from the old one
rather than deleting history - the timeline shows that a rollback happened
instead of pretending the bad version never existed.

**Environments** are named pointers at versions. Publishing moves only the
default; every other environment stays pinned until a version is promoted onto
it. A channel bot bound to an environment serves its version.

## Exposure

**Where an agent is reachable, and by whom.** Web chat, an HTTP API key, a public
link, a Slack or Telegram bot, an embedded widget.

The important property: *every surface goes through one runner*. Budgets,
approvals, the audit trail and the permission checks are identical whether a run
came from the chat window or a Slack mention, because there is exactly one code
path that executes an agent.

Channel mentions have one rule worth stating on its own. `@slug` resolves only
inside the bot's own organization, and the run executes as the **sender**, never
as the bot. An unlinked chat identity is refused rather than run with no role -
because a run nobody can be held to is worse than a run that did not happen.

## Trigger

**When an agent runs with nobody at the keyboard.** A schedule - every *N* minutes -
that fires the agent on its own. Like an exposure, a trigger is operational state
beside the agent, not part of the spec: you add, pause and remove one without minting
a version, and it is not exported in a client's YAML because it carries things a spec
cannot - a subject, and when it last fired.

The channel-mention rule above applies here, for the same reason: a triggered run
executes **as the member who created the trigger**, re-resolved every fire, never as
an invented service user. When that member can no longer run the agent - they left the
organization, or their grant on it was revoked - the trigger disables itself and
records why, rather than retrying a refusal for ever.

Everything else is deliberately identical to any other run, because it goes through
the same runner: the budget is enforced the same way, an approval parks it the same
way, the audit trail names it the same way. It is stamped the `schedule` surface, so
"how is this agent used" can tell an unattended run from a person's; each fire is its
own run in Activity; and its answers accumulate in one run-log conversation the trigger
opens once - eagerly, the moment the trigger is created, so it is a clickable item
before it has ever fired.

A trigger fires one of two ways. A **schedule** fires on the clock: an **interval**
("every N seconds", a minute at the finest, since a heartbeat claims the due ones once
a minute) or a **cron** expression evaluated in UTC - `0 9 * * *` for 09:00 each day,
or any crontab - the service computing the next fire for each the same way, and a run
that outlives its own interval finishing before the next fire rather than piling up on
itself. An **event** fires on an arrival: a GitHub issue, an inbound email, a LinkedIn
post, or the catch-all generic webhook - anything that can POST signed JSON, so a
Zapier or Make step or a small script covers whatever else a user wants to fire on. It
is delivered as a signed webhook the platform verifies against a per-trigger secret
[sealed in the vault](secrets.md) and matched against an optional per-source filter
before the agent runs with the payload appended to its prompt. An event has no next
fire - nothing is due until a delivery lands - so the heartbeat never sees it. Adding a
source is a value in one enum and a branch in one module; it changes nothing on the row.

Any trigger can also be **run now**: one extra fire on demand that leaves its cadence
untouched. And every schedule and event in an organization is listed together across
its agents, each filtered to the ones the caller may run - the same per-resource
`agents:run` that gates creating one.

## Run

**One execution.** It has a subject, a version, a surface, a status, token counts
and a cost.

A run that fails still records what it spent. A run that stops on its budget is
recorded as `budget_exceeded` rather than `failed`, so an operator filtering for
problems does not wade through the platform working correctly. A run somebody
stopped - the composer's stop button, a socket that went away, a delegation
cancelled from above - is `cancelled` for the same reason, on every surface and
not only the streaming one. A run that parks on an approval is
`awaiting_approval` and is resumable - its message history is
stored so the decision can be applied to the conversation it belongs to. A run that
parks *inside a delegation* stores one level per agent, each with its own
conversation, so approving continues the delegate that stopped rather than starting
its work again.

A run can also contain another run. When an agent delegates to a published agent,
that delegation gets an `agent_runs` row of its own carrying `parent_run_id` - so
"what did the researcher cost this month" has an answer - while both share one
spend ledger. There is no `delegated` status, because how a run *ended* and how it
*started* are two questions and `parent_run_id` answers the second.

### A run and its transcript

A run says what it cost; `messages.run_id` says what it *did*. Every turn a run
produced carries the run's id, so "the steps of this run" is one query rather
than a guess - which is what a drill-down from run history reads.

The link is a column rather than a time window on purpose. Two runs started in
one conversation interleave, so windowing messages between `started_at` and
`ended_at` returns the first run's turns *and* the second's, and a run with no
`ended_at` - cancelled, or still going - returns nothing at all. Both are wrong
in a way the reader cannot see.

The prompt is written before the run row exists, because a build that refuses -
a deleted secret, a model profile removed in a deploy - must not lose what
somebody typed; it is linked as soon as there is a run to link it to. Deleting a
run nulls the column instead of deleting the turns: the words were still said,
and the conversation is where somebody reads them.

Linking a turn is not the same as writing one, and what each surface actually
writes is a separate question - one this column cannot answer, since it links
rows that already exist. The non-streaming surfaces are written by the runner
rather than by themselves, which is what made them uniform; the exceptions and
what they leave out are listed under
[Surfaces](channels.md#what-each-surface-records).

Run history filters on exactly this: `GET /runs` takes a comma-separated list of
statuses (`?status=failed,budget_exceeded`), because the operator's question is
a set of outcomes, not one status at a time. An unknown status is refused rather
than silently matching nothing - an empty page must mean "no such runs".

---

## Three more, because they are easy to confuse

### Capability vs tool

A **capability** is a unit somebody grants: `knowledge`, `web_research`,
`code_execution`. It may contribute several **tools**, and it carries the
configuration and the approval policy.

Approval resolves most-specific-first: the tool's own override, then the
capability's mode, then whether the capability is `side_effecting`. The Builder
states the outcome in words rather than describing the rule, because a rule the
reader has to run in their head is a setting nobody dares touch.

See the [capability catalog](reference/capabilities.md) for what ships, and
[Adding a capability](howto/add-capability.md) for a new one. Tools that arrive
from an [MCP server](mcp.md) are the exception to all of the above: they are
discovered at run time, so nothing declared them and nothing gates them.

### Collection vs skill

A **collection** is documents, chunked and embedded, and it is *searched*. The
model chooses what to look for; it can never widen where it looks.

A **skill** is a folder of Markdown - a `SKILL.md` and whatever files go with it
- and it is *read*. Its description is the only part the model sees before
deciding whether to open it, which is why a skill's description should say *when
it applies* rather than what is inside it.

The practical difference: retrieval costs an embedding call per search and returns
fragments. A skill costs nothing until it is opened and then returns the whole
document.

See [Skills](skills.md) for the format and the comparison in full.

### Delegate vs inline specialist

An agent can hand part of a job to another agent. There are two ways to say who
that other agent is, they look alike in the Builder's own vocabulary, and almost
everything that matters about delegation follows from which one you picked.

A **delegate** is another published agent in the organization, referenced by
`agent_id` *and* `agent_version_id` - pinned. It is addressed by its slug, the
same handle a channel mention resolves.

An **inline specialist** is defined inside the parent's own spec: a name, a
description the parent's model reads before delegating, instructions, and - because
a summariser that cannot read the collection is useless - its own model, its own
capabilities, its own collections and skills, and its own step limit.

Which makes a specialist an agent in every way except one, and it is worth being
precise about which. Four things make something an agent here:

| | A published delegate | An inline specialist |
|---|---|---|
| **Versioned** | yes - pinned, and a pin only moves when somebody moves it | **no** |
| **Permission-checked at publish** | yes - `agents:run` on that row | yes - the same scope, secret, collection and skill checks the parent's own bindings get |
| **Its own capabilities** | yes - its published spec's | yes - its own, plus what the parent shares |
| **Metered and capped** | yes | yes - by the run's caps, which is [what binds inside any delegation](governance.md#delegation-spends-the-parents-budget) |

**The missing one is the version**, and everything a specialist cannot do follows
from it: nothing else can reference it, editing the parent changes it, it gets no
run row of its own, and it cannot delegate further. A published delegate is
reviewable and exportable; a specialist is a paragraph in somebody else's spec.

So a specialist is for the work that should not require publishing an agent -
"summarise this in three bullets" - and a delegate is for a capability the
organization owns and reuses.

A third kind sits below the inline one: a **dynamic specialist**, invented by the
model at run time under [`allow_dynamic`](reference/capabilities.md#delegation). It
is a specialist that is not even written down in a parent's spec - persisted
nowhere, because keeping one would mean publishing an agent, and publishing is a
person's action. That rule is a design, not a limitation, and the thing that makes
it one is the exit: a person can **promote** a specialist to a draft agent. It
works on an inline specialist in the Builder, and on a dynamic one from the chat
delegation panel while the run that created it is still on screen - the only window
a dynamic specialist's definition is legible, since it rides the delegation's
opening frame and nothing stores it after the turn. Promotion creates an ordinary
draft from the specialist's instructions, model, capabilities, collections and
skills, owned by whoever promoted it and subject to the usual `agents:edit` check.
It stops there: it does not publish, does not pin the new agent as a delegate of its
parent, and does not remove the specialist it came from - each of those is the next
decision, with the normal validation in front of it. Without this exit the only way
to keep a good specialist was to copy its instructions out of a chat log, which
produces an agent whose provenance nobody can see - exactly the untracked-agent
outcome the persistence rule exists to prevent.

!!! important "One notion of 'agent', used recursively"

    The risk this shape exists to contain is a *second*, parallel notion of agent
    - one that publish validation does not walk and the permission model cannot
    see. A specialist would have been the obvious place for it: it does not look
    like an agent, which is exactly why it is the tempting place to reach a
    collection nobody shared or a capability nobody granted.

    It is contained by refusing to write a second format. A specialist is a typed
    *subset* of the spec, using the same capability bindings, checked by the same
    recursive publish pass, and assembled by the same builder. One spec type, one
    validator, one builder, one Builder component - each used recursively. If any
    of those grows a second copy for specialists, the copy is the bug.

**A pin fails loudly rather than drifting.** A delegate whose pinned version no
longer exists fails the run and names the delegate; there is deliberately no fall
back to its current version, because the reason to pin is that nothing changes
without a decision and a silent upgrade is worse than a refusal - nobody finds
out. The cost of that is paid in the Builder, which compares each pin against what
the delegate publishes now and offers to move it.

See the [`subagents` capability](reference/capabilities.md#delegation) for the
ceilings and the tools, and [Permissions](permissions.md#delegation-is-not-a-privilege-boundary)
for who may delegate to what.

---

## Model profiles

A **model profile** is a named model backed by a stored key: `openai default`,
`OpenRouter prod`. Agents point at profiles, never at model strings.

That indirection is the point. Rotating a key, or moving every agent from one
model to another, is an edit to one profile rather than to forty specs. A profile
with no credential behind it is marked `no key` everywhere it appears, because
that is the one fact deciding whether the agent can run at all.

Prices come from
[`genai-prices`](https://github.com/pydantic/genai-prices), which Pydantic
maintains, rather than from a table in this repository - a hand-kept table cannot
express tiered pricing and goes stale silently. A model the package does not know
is recorded at zero with a warning, and the run's total is flagged as a floor
rather than guessed at.

See [Models and providers](models.md) for the twenty-seven providers, the
credential each one wants, and how fallbacks behave.

## Organizations

Every resource is filed under an organization. Isolation is enforced by the
schema - `NOT NULL` columns, check constraints, unique constraints scoped per
tenant - rather than only by the service layer, so a missed `WHERE` clause is a
constraint violation instead of a data leak.

The vault goes further: a secret's ciphertext is bound to the organization that
stored it, so a row copied between tenants cannot be decrypted.

## Next

- [Permissions](permissions.md) - roles, scopes and grants.
- [Governance](governance.md) - budgets, approvals, alerts, audit.
- [Capabilities](reference/capabilities.md) - what an agent can be given.
- [MCP](mcp.md) - the tools nobody here has to write.
- [Models](models.md) - providers, profiles, fallbacks, cost.
- [Secrets](secrets.md) - the vault, and why a ciphertext cannot move tenants.
- [Architecture](architecture.md) - how the code is laid out.
