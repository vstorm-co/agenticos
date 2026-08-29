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
| LangGraph, LangChain, LlamaIndex, elizaOS | Libraries and frameworks for composing model calls | Same — you want code, not a platform, and you are happy owning the deployment |
| [Cloudflare OS](https://github.com/cloudflare/cloudflare-os) | An open-source agent workspace on Cloudflare Workers | Your users are your own employees, you are already on Cloudflare, and you want per-person apps more than a governed agent catalog |
| [Glean](https://www.glean.com) | Hosted enterprise search with agents on top | You want 275+ ACL-aware connectors indexed for you and the data may live in a vendor's cloud |
| Dify, Flowise | Visual agent builders, self-hostable | You want the builder and a workflow canvas, and the governance model matters less to you than how fast somebody can assemble a flow |
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

## A library, and building the rest yourself

LangGraph, LangChain, LlamaIndex, Pydantic AI. The most common right answer,
and the one this project is least in competition with: AgenticOS **runs on**
Pydantic AI, so a library is the layer underneath rather than the alternative
to it.

A library plus a queue plus a database gets you a working agent quickly, and
for one or two agents that is less work than learning a platform.

Use the library directly when:

- **The agent is the product.** Its behaviour is a feature you ship, versioned
  with your code, reviewed in your pull requests. A UI that lets somebody else
  change it is not a benefit here — it is a way for your product to change
  without a release.
- **You need the loop.** Custom control flow, a graph with cycles, a retry
  policy nobody else's abstraction expresses. A platform gives you a
  well-defined runner; that is exactly what you are trying not to have.
- **There is no non-engineer in the story.** If every change was always going to
  be written by an engineer anyway, the indirection buys you nothing.
- **There is one agent.** Or two. The economics below only turn at a handful.

What you take on instead is the
[seven jobs](index.md#what-makes-something-an-operating-system-for-agents), one
at a time and usually in this order, each after it has already hurt once:

| You will end up writing | Because |
|---|---|
| A budget that stops a run | Counting spend after the fact is not a budget, and the first surprise invoice teaches this |
| An approval that is decided once | The second decision on a decided approval is a race, and it is not theoretical |
| Tenant isolation | The first time a `WHERE organization_id` is forgotten, it is a data incident rather than a bug |
| A per-tenant secret store | One deployment-wide key means one leak is every customer's leak |
| One execution path across surfaces | Otherwise Slack and your API disagree about what an agent cost |
| An audit trail that records failures | A ledger that only logs successes answers the wrong question during an incident |

None of that is hard. All of it is work you are not doing on your product, and
it is the whole of what this platform is.

!!! info "The line is somewhere around the fifth agent"

    Or earlier, at the first person who needs to change what an agent says and
    does not have commit access. Before that, a library and a queue is less work
    and you should use one.

And if you are going to build those six rows anyway, the
[seven jobs](index.md#what-makes-something-an-operating-system-for-agents) are a
reasonable specification to build against — whether or not you use this one.

## Recap

- Use a **library** for one agent inside a product; use this for a catalog of
  them — the line is around the fifth agent, or the first non-engineer builder.
- **Open source and self-hostable are different promises** — check which one you
  actually need.
- **Cloudflare OS** is a workspace for employees; this is a catalog of agents
  that face outward.
- **Glean** wins on connectors and ACL-aware search; this wins when the data
  cannot leave your infrastructure.
- **Building it yourself** is right until roughly the fifth agent, and the seven
  jobs are the specification either way.
