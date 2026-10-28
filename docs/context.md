# Context files

A **context file** is a piece of standing knowledge written once and attached to
many agents: a glossary, a brand voice, an escalation matrix, the list of
products you actually sell.

If you have written an `AGENTS.md` for a coding agent, this is the same idea with
the same shape — a Markdown file that says how things are done here, kept beside
the work rather than inside one prompt. The difference is who reads it: an
`AGENTS.md` in a repository is read by whatever tool happens to open it, and a
context file here is attached to the agents you choose, versioned with them, and
editable by the person who actually knows the answer.

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

The **Context** page shows the opening of each file on its card. `GET
/api/v1/context` returns it as `excerpt`: a few bounded lines, never the whole
body.

## Two modes, and the difference is cost

Each attached context file has a mode in the agent’s **Context** capability settings. The same shared file can be injected for one agent, linked for another, or switched off for a third.

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

In the Builder, each selected file has **Use in this agent** and a mode selector. These settings belong to the agent draft and take effect when published. The library editor only changes shared content and description; its format follows the filename. Existing agent versions without per-file overrides retain their previous mode and availability.

The capability also controls whether its read tool is available. Turning **off** the read tool
means only injected files reach the model and nothing is read on demand — a
reasonable choice when you want an agent's inputs entirely predictable.

You can also start from the file: **Add to an agent** on its card adds it to the
agent's draft with the Context capability switched on, and the card says which
agents carry it already. A knowledge base has the same action on its own page.

## Changes the assistant proposes

**Improve with the assistant**, in a file's editor, asks the
[authoring assistant](authoring.md#context-files) for a better body, written from
the runs of the agents that read the file. What it proposes is not applied: it
waits above the list on the Context page, with why, the runs it rests on, and
the agents bound to the file.

Applying it is the same as editing the file by hand - live at once for every
agent whose published version reads the file - so **Check with evals** comes
first, on one of those agents. Beside **Apply** the change says what applying
does: each agent and environment it goes live for, the eval suites it queues,
and the guards that check it only at the agent's next promotion. A file
somebody edited after the change was proposed refuses the change; the edit is
never written over.

Asking the assistant again rewrites the waiting change rather than adding a
second one. A decision names the version of the change you read, so of two made
at once only one counts, and a page opened before the rewrite is refused with
"The proposal changed since you opened it" until you review the new version. A
change that says what the file already says is not proposed at all.

Any edit to a file - applied or made by hand - and deleting it queue the eval
suites that run when a dependency changes, for every agent that reads it, and
applying a change tells the owners of those agents.

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
