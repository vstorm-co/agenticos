# About AgenticOS

AgenticOS is the operating system for a company's AI agents: self-hosted, open
source, multi-tenant.

It exists because of one observation. Most agent frameworks give you a library —
you write Python, you deploy it, and every change to an agent's behaviour is a
pull request, a review and a release. That is exactly right for a product feature
and exactly wrong for the forty small agents a company actually wants, because
the person who knows what the agent should say is not the person with commit
access.

So here, **an agent is a file**. In an operating system a program is a file:
something you can read, copy, version and commit. An agent is the same —
instructions, a model, a set of capabilities, a budget — built in a UI, published
as a version, and exportable as YAML into your own git repository.

## What makes something an operating system for agents

The word gets used loosely in this category, which is a fair complaint. It is
worth stating what it has to mean, because an operating system is not a mood: it
is seven jobs, and a product either does them or it does not.

Use this as a test. Run it on AgenticOS, and run it on anything you are
comparing it against.

| An operating system… | …and for agents that is |
|---|---|
| **Runs and isolates processes** | A run is the process. It starts, it can be stopped, it is isolated from other tenants, and it leaves a record of what it did |
| **Enforces resource limits** — quota, cgroups | A budget, checked *before* the work is allowed rather than tallied afterwards, on a unit somebody is accountable for |
| **Controls access** — users, permissions, `sudo` | Permissions checked at the call site, not role names; and an escalation path for anything that acts on the outside world |
| **Reaches hardware through drivers** | One interface to many model providers and many tool servers, so swapping either does not rewrite the thing using it |
| **Keeps a filesystem** | Somewhere durable for the organization's own knowledge, with the access rules attached to it |
| **Gives many interfaces one shell** | The same agent answering on every surface through one execution path, rather than each surface assembling its own |
| **Writes an audit log** | Who ran what, when, what it cost, who approved it — written whether or not the run succeeded |

### How AgenticOS answers each one

| | |
|---|---|
| Processes | Runs are first-class: history, cost, status, and tenant isolation enforced by database constraints rather than by service code |
| Resource limits | [Monthly budgets](../governance.md) per agent, checked before each model request. A run that fails still records what it spent, because a budget that ignores failures is not a budget |
| Access control | A [permission catalog](../permissions.md) in code, roles composed from it, per-resource grants that widen and never narrow. `approval: required` is the `sudo` — the run parks and waits for a person |
| Drivers | [27 model providers](../models.md) behind a model profile, and [any MCP server by URL](../mcp.md). Change the profile and every agent using it moves, without one being republished |
| Filesystem | [Collections, skills and context](../file-processing.md) in your own Postgres, embeddings keyed per organization |
| Shell | One runner behind [web chat, the API, Slack, Telegram, a widget, a hosted page and a schedule](../channels.md) |
| Audit log | Every run, every approval decision, every secret rotation — with values, never rows, and never a plaintext key |

!!! info "Why the test is written to be applied to us too"

    A checklist that only ever produces one answer is marketing. This one is
    genuinely usable against any product in the category, and it is how we would
    like to be judged — including on the row below, where the answer is not yet
    good enough.

### Where this one is not finished

Monitoring is the weakest of the seven. Every run records a
`logfire_trace_id` and nothing yet reads it, so what you get today is run
history, cost and status rather than a trend you can act on. It is on
[the roadmap](../ROADMAP.md) as R11.

Two more gaps worth knowing before you compare: there is no SAML or SCIM yet —
sign-in is JWT, API keys, Google OAuth and magic links — and there is no
evaluation harness, so testing an agent before publishing it is something you
do by hand.

## Who it is for

A company that wants more than three agents, and wants them governed.

- **The person who builds the agent** does not write Python. They write
  instructions, switch on capabilities, point at a knowledge collection and set a
  budget.
- **The person accountable for the bill** gets budgets that stop a run, approvals
  on anything side-effecting, and an audit trail.
- **The engineer** gets a spec that exports as YAML into their own git
  repository, an HTTP API, and a platform they can read the source of.

## What it deliberately is not

**It is not an agent framework.** [Pydantic AI](https://ai.pydantic.dev) is the
runtime underneath, and if what you want is to write an agent in Python, use it
directly — you will be happier.

**It is not a hosted service.** Nothing phones home. Model prices come from a
snapshot bundled with the release, and the only outbound requests are the ones
your agents make. An operating system installs on your own machine; nobody rents
a kernel per seat.

**It is not a place to write integrations.** An integration with a SaaS product
is an [MCP connection](../mcp.md), not a Python module somebody in this
repository maintains against that product's API. That is why the capability
catalog is short and stays short.

## The part that is actually the product

Most of the value here is in what the platform **refuses**: a cross-tenant read,
an ungranted scope, a budget breach, a second decision on a decided approval, a
spec that fails validation at publish.

The happy path — a model call with some tools attached — is the easy half, and a
dozen libraries do it well. The refusals are the half that decides whether you
can hand an agent to somebody who is not you.

## When to use something else

Four of the seven jobs are things a library will never do for you, and three of
them are things a hosted platform will do without giving you the machine. Neither
is a criticism; they are different products.

[Which one to pick, and when →](comparison.md)

## Where it came from

Generated from the
[Full-Stack AI Agent Template](https://github.com/vstorm-co/full-stack-ai-agent-template),
which is why "the platform layer" and "template-inherited" are distinctions that
show up in the contributor docs. The platform layer — everything AgenticOS adds
on top — is held at 100% test coverage in CI. The inherited subsystems are
reported but do not gate the build, because holding code we did not design to the
same bar buys a coverage number rather than confidence.

The decisions behind the shape of it are on the next page.

## Who builds it

[Vstorm](https://vstorm.co), and whoever sends a pull request.

## Recap

- An **agent is a file**: readable, copyable, versioned, committable.
- "Operating system" is a **specification here, not a label** — seven jobs, each
  with a mechanism behind it.
- The test is meant to be **applied to other products too**, and to this one:
  monitoring is the row where the honest answer is "not yet".
- The product is mostly the **refusals**, not the happy path.
- It runs on **your machine**, because that is what an operating system does.

[The design →](design.md) · [The roadmap →](../ROADMAP.md)
