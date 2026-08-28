# When to use something else

This page is written to be useful when the answer is not AgenticOS. A comparison
that always concludes the same way is not a comparison, and the categories below
overlap enough that picking wrong costs months.

The short version: a **library** is right for one agent inside a product, a
**hosted platform** is right when you do not want the machine, an **agent
workspace** is right when the user is your own employee, and AgenticOS is right
when agents have to be editable by a non-engineer, governed by somebody
accountable, and running on hardware you control — all three at once.

## The categories

| | What it is | When to use it instead |
|---|---|---|
| [Pydantic AI](https://ai.pydantic.dev) | The agent library AgenticOS runs on | You are building one agent, in Python, as part of a product |
| LangChain, LlamaIndex, elizaOS | Libraries and frameworks for composing model calls | Same — you want code, not a platform, and you are happy owning the deployment |
| [Cloudflare OS](https://github.com/cloudflare/cloudflare-os) | An open-source agent workspace on Cloudflare Workers | Your users are your own employees, you are already on Cloudflare, and you want per-person apps more than a governed agent catalog |
| [Glean](https://www.glean.com) | Hosted enterprise search with agents on top | You want 275+ ACL-aware connectors indexed for you and the data may live in a vendor's cloud |
| Dify, Flowise | Visual agent builders | You want the builder without self-hosted multi-tenancy and per-organization key isolation |
| Hosted enterprise agent platforms | Closed-source platforms sold with a deployment team | You want somebody else accountable for the outcome and the licence cost is not the constraint |
| OpenAI Assistants, Bedrock Agents | Hosted agent runtimes | You are happy on one vendor and do not need the data on your own hardware |

## Open source is not the same as self-hostable

These are two different promises and the difference decides deployments.

**Open source** means you can read the code and fork it. **Self-hostable** means
you can run it to completion on infrastructure you already own, with no
dependency on the vendor's platform.

AgenticOS needs PostgreSQL with pgvector, Redis and Docker. Nothing else, no
account anywhere, and the only outbound requests are the ones your agents make.
That is the whole deployment surface, and it is why it can run inside a hospital
network or an air-gapped environment.

Cloudflare OS is Apache-2.0 and genuinely open, and it is built on Durable
Objects, Dynamic Workers and Cap'n Web. Running it outside Cloudflare means
running `workerd` yourself, and the project's own README lists documentation for
that as not yet written. If the deployment constraint is "this cannot depend on a
specific cloud", that is the thing to check first.

!!! info "Neither position is wrong"

    Building on one platform's primitives is how Cloudflare OS gets per-document
    sandboxing and capability-scoped access that are genuinely hard to reproduce
    on ordinary infrastructure. It is a trade, and which side of it you want
    depends on where the software has to run.

## Cloudflare OS

The closest thing to this project by name, and a different product by shape.

**Cloudflare OS is a workspace.** Each person gets an agent, a runtime to write
and run code in, and personal apps they can build and share. The security model
is excellent: agents start with access to nothing, credentials never reach the
agent, and every resource an agent reads is recorded and checked against whoever
later opens the result.

**AgenticOS is a catalog.** You publish agents, and they answer people who are
often not employees — a customer in a widget, a user in Slack, a system behind an
API key. The unit is a published, versioned agent with a budget and an audience,
not a person's workspace.

Pick Cloudflare OS if the agent's user is your own staff and you are on
Cloudflare. Pick AgenticOS if the agent has to face outward, be governed per
agent, and run where you say.

## Glean

Glean is enterprise search first, with agents built on the index. Its strength is
the part AgenticOS does not attempt: connectors to 275+ systems that carry each
document's own access rules into the index, so an answer can never quote
something the asker could not open.

Two things follow. If your problem is *"our knowledge is in forty systems and
search does not work"*, that is what Glean is for and AgenticOS will not match
it — our retrieval is per-collection and does not yet inherit source ACLs.

If your problem is *"we need governed agents and the data cannot leave"*, the
comparison goes the other way: Glean is hosted, priced per seat with an
enterprise minimum, and not something you run yourself.

## Building it yourself

The honest option, and often correct. A library plus a queue plus a database gets
you a working agent quickly, and for one or two agents that is less work than
learning a platform.

The bill arrives at the fifth agent, and it is always the same items: budgets
that stop a run rather than report on it, an approval that cannot be decided
twice, tenant isolation that survives someone forgetting a `WHERE` clause,
per-organization secrets, and one execution path so Slack and the API cannot
disagree about what an agent costs.

If you are going to build those anyway, the seven jobs in
[About](index.md#what-makes-something-an-operating-system-for-agents) are a
reasonable specification to build against — whether or not you use this one.

## Recap

- Use a **library** for one agent inside a product; use this for a catalog of
  them.
- **Open source and self-hostable are different promises** — check which one you
  actually need.
- **Cloudflare OS** is a workspace for employees; this is a catalog of agents
  that face outward.
- **Glean** wins on connectors and ACL-aware search; this wins when the data
  cannot leave your infrastructure.
- **Building it yourself** is right until roughly the fifth agent, and the seven
  jobs are the specification either way.
