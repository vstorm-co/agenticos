# Context files

A **context file** is a piece of standing knowledge written once and attached to
many agents: a glossary, a brand voice, an escalation matrix, the list of
products you actually sell.

It is the answer to a problem every company hits at its third agent — the same
three paragraphs pasted into three sets of instructions, and then edited in one
of them.

## Where it sits between skills and knowledge

Three things put text in front of a model, and choosing wrongly is the usual
cause of an agent that either ignores what it was told or reads nothing at all.

| | It holds | The model sees it |
|---|---|---|
| **Context file** | Standing facts, small and stable — a glossary, a tone guide, an org chart | Always, or on demand — you choose |
| **[Skill](skills.md)** | A procedure for one kind of task — how to handle a refund request | When the model decides that task is what is happening |
| **[Knowledge collection](file-processing.md)** | A corpus too large to read — every policy document, every ticket | Only the chunks a search returns |

The rule of thumb: **if it is short and always relevant, it is a context file.
If it is long, it is knowledge. If it is a procedure, it is a skill.**

## Two modes, and the difference is cost

Every context file carries a mode, and it decides how the file reaches the
model.

=== "`inject` — always there"

    The body is spliced into the agent's instructions verbatim. The model
    always knows it, without deciding to look and without a tool call.

    Use it for things the agent must never get wrong: what your products are
    called, who to escalate to, how to refer to the company.

    **It is read on every single turn**, so it is part of the cost of every
    message. Keep injected files short.

=== "`link` — read on demand"

    The body stays out of the prompt and is exposed through a tool. The model
    reads it only when it decides the file is relevant, choosing from the name
    and a one-line description you write.

    Use it for reference that matters sometimes: a rarely-needed policy, a
    regional variation, a long list.

    Costs nothing on turns that do not need it, and nothing at all if the model
    never looks — which is also the risk.

!!! tip "Write the description for a model, not for a person"

    A linked file is chosen from its name and description alone. "Returns
    policy" tells a model less than "when a customer may return an item, the
    time limits, and the three exceptions" — and the difference is whether the
    file is ever opened.

## Attaching them to an agent

Context files are an organization's, not an agent's. You write one, and any
number of agents bind to it.

Switch on the **Context** capability on the agent, then bind the files it should
have. Editing the file afterwards changes what every bound agent knows **on its
next run** — no republishing, on any of them.

That is the whole point, and the thing to be careful about: a change to an
injected file is a change to every agent that carries it. Treat it as the
shared, load-bearing text it is.

The capability has one setting worth knowing. Turning **off** the read tool
means only injected files reach the model and nothing is read on demand — a
reasonable choice when you want an agent's inputs entirely predictable.

## Access

A context file has an owner and a visibility, like any other resource here, and
`context:view` gates reading the catalog. A file somebody has not been granted
is a file they cannot bind, and the [same three layers](permissions.md) decide
that as everywhere else.

Anything genuinely secret does not go in one — a context file is text an agent
reads out loud when asked the right question. Credentials belong in
[the vault](secrets.md).

## Recap

- A context file is **standing knowledge written once, bound to many agents**.
- **`inject`** is always in the prompt and costs on every turn; **`link`** is
  read on demand and costs nothing until it is.
- A linked file is chosen by its **description**, so write that for the model.
- Editing a file updates **every bound agent on its next run**, with nothing
  republished.
- Short and always relevant → context. Long → [knowledge](file-processing.md).
  A procedure → [a skill](skills.md).
