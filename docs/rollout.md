# Rolling it out

This page is for whoever is accountable for the decision rather than the
install: what changes in a company that runs this, who does what, what it costs,
and the three ways it usually goes wrong.

Nothing here needs a terminal. [Install](install.md) is the other half.

## What it replaces

Not a person. **A backlog.**

Every company has a queue of small automations that never get built: the reply
that answers the same customer question, the weekly summary somebody assembles by
hand, the form filled from an email, the internal question answered by
interrupting the one person who knows.

Each is too small to justify a project and there are forty of them. They stay
undone because the only way to build one has been a developer, a repository and
a release — and a developer's time is better spent on the product.

AgenticOS makes each of those a document somebody writes, rather than software
somebody ships.

## Who does what

Three roles, and the split matters more than the tool does.

| | Who this is | What they own |
|---|---|---|
| **The builder** | The person who knows the answer — support lead, ops manager, analyst | Writes the agent's instructions, chooses what it may do, points it at the right documents, tests it, publishes it |
| **The owner** | Whoever is accountable for the spend and the behaviour | Sets budgets, decides which actions need human approval, reads the audit trail |
| **The engineer** | One person, part-time, after the first week | Runs the install, connects the systems, adds a capability if something genuinely new is needed |

The point of the split is that the builder is not blocked on the engineer. If
every change to what an agent says has to go through the person with commit
access, you have bought a slower version of what you had.

!!! info "The engineer's load drops after setup"

    Connecting a system is [an MCP server by URL](mcp.md), not a connector
    somebody writes. Changing behaviour is an edit and a publish, not a release.
    Most weeks the engineering cost is zero.

## A realistic first ninety days

| | | What "done" looks like |
|---|---|---|
| **Week 1** | Install, connect one model provider, invite three people | One agent answers a real question from a real document |
| **Weeks 2–4** | One agent, one team, one repeated task. Budget set low on purpose | The team uses it without being asked to |
| **Weeks 5–8** | Put it where the work already happens — [Slack, a widget, email-driven routines](channels.md) | Somebody outside the pilot team uses it without training |
| **Weeks 9–12** | Second and third agent, built by a different person | A non-engineer has published an agent end to end |

The milestone that matters is the last one. **One agent proves the technology;
the second agent, built by somebody else, proves the model.** If every agent
still comes from the same person, you have a tool, not a platform.

## What it costs

Three lines, and only one of them is a surprise.

- **Infrastructure.** Postgres, Redis and a container host. A small VM runs a
  pilot; this is the cheapest line and stays that way.
- **Model usage.** Metered per run, per agent, and visible before the invoice.
  This is the line to watch, and the one [budgets](governance.md#budgets) exist
  to cap — checked *before* each model request, so an over-budget agent stops
  rather than overspends.
- **People.** An engineer for setup, then part-time. A builder per team, as part
  of their existing job rather than a new one.

There is no per-seat licence, because there is no licence: it is Apache-2.0 and
you are running it. That changes the shape of the decision — adding the
eleventh agent and the hundredth user costs nothing but the tokens they use.

!!! tip "Set the first budget lower than you think"

    A budget that stops a run is a much better teacher than an invoice. Start at
    a number that will be hit, watch where it goes, then raise it deliberately.
    [Choosing a model](choosing-models.md) covers what actually drives the bill.

## What your security review will ask

The questions come in a predictable order, and the answers are the reason this
architecture was chosen.

| They ask | The answer |
|---|---|
| Where does our data go? | Your Postgres, on your infrastructure. Nothing phones home. The only outbound calls are to model providers you configured — and [none at all](choosing-models.md#closed-models-or-open-weights) if you run the model yourself |
| Who can see what? | [Three layers](permissions.md): a deployment admin, an organization role, and per-resource grants. A control somebody may not use is not rendered, not rendered and then refused |
| What stops an agent doing damage? | Nothing side-effecting runs without [approval](governance.md#approvals) when you require it, and an approval is decided exactly once |
| Can we prove what happened? | Every run, every approval, every secret rotation is in the [audit trail](governance.md#audit) — including runs that failed |
| Where are the credentials? | [One vault](secrets.md), sealed per organization. No API response, log line or audit entry ever carries a plaintext key |
| Can we read the code? | Yes. That is usually the end of the conversation |

## Three ways this goes wrong

Each has been seen; each is avoidable.

**One person builds every agent.** The platform becomes that person's queue and
you are back where you started. Fix: make the second agent somebody else's, and
sit with them while they build it.

**The first agent is too ambitious.** An agent that touches four systems and
makes decisions fails in a way nobody can debug, and the failure is remembered
as "AI does not work here". Fix: the first agent answers questions from
documents. It is boring, it works, and it earns the second one.

**Nobody set a budget or an approval.** The run that surprises somebody is the
one that had no cap and no gate, and it costs more trust than money. Fix: set
both on day one, on every agent, before anyone else has access.

## What to measure

Resist counting conversations. Measure the four things that decide whether this
was worth doing:

| | Why it is the right number |
|---|---|
| **Questions answered without a person** | The actual output. Everything else is a proxy for it |
| **Cost per resolved task** | Falls as you tune retrieval and move down a model tier — and it is visible per run, not per month |
| **How many people have published an agent** | The adoption number that predicts whether this survives its champion |
| **Approvals waiting** | A queue that grows means the gate is on the wrong action, or the agent is not trusted yet. Both are worth knowing early |

## Recap

- It replaces **a backlog of small automations**, not a person.
- The split that makes it work: **the builder is not blocked on the engineer.**
- The milestone that matters is the **second agent, built by somebody else.**
- **No per-seat licence** — the eleventh agent costs only the tokens it uses.
- Set a **budget and an approval on day one**, on every agent, before anyone
  else has access.

[Install it →](install.md) · [Build the first agent →](first-agent.md) ·
[What it refuses →](about/index.md)
