# About AgenticOS

AgenticOS is the operating system for a company's AI agents: self-hosted, open
source, multi-tenant.

It exists because of one observation. Most agent frameworks give you a library —
you write Python, you deploy it, and every change to an agent's behaviour is a
pull request, a review and a release. That is exactly right for a product feature
and exactly wrong for the forty small agents a company actually wants, because
the person who knows what the agent should say is not the person with commit
access.

So here, **an agent is data**. Instructions, a model, a set of capabilities, a
budget. Somebody builds it in a UI, publishes a version, and it runs the same way
everywhere.

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
your agents make.

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

## Alternatives

| | What it is | When to use it instead |
|---|---|---|
| [Pydantic AI](https://ai.pydantic.dev) | The agent library AgenticOS runs on | You are building one agent, in Python, as part of a product |
| LangChain / LlamaIndex | Libraries for composing model calls | Same — you want code, not a platform |
| Dify, Flowise | Visual agent builders | You want the builder without self-hosted multi-tenancy and per-organization key isolation |
| OpenAI Assistants, Bedrock Agents | Hosted agent runtimes | You are happy on one vendor and do not need the data on your own hardware |

AgenticOS is the one to pick when the agent must be **editable by a non-engineer,
governed by somebody accountable, and running on hardware you control** — all
three at once.

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

[The roadmap →](../ROADMAP.md) · [The design →](design.md)
