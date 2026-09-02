# Choosing a model

[Models](models.md) explains the machinery — what a profile is, how a fallback
fires, how a run is costed. This page answers the question people actually ask
first: **which model should this agent use?**

The short answer is that it is not one decision. It is one decision *per agent*,
and you are meant to change your mind later — that is what a
[model profile](models.md#a-model-profile) is for.

## Three questions decide it

Ask them in this order. The first one that gives a hard answer wins.

| | Ask | If the answer is… |
|---|---|---|
| 1 | **Where may this data go?** | "Nowhere" — you are choosing between models you can run yourself. Stop here; nothing below overrides it |
| 2 | **How hard is the thinking?** | Routine extraction and rewriting is a different budget from multi-step reasoning over a messy corpus |
| 3 | **How often will it run?** | A hundred conversations a month and a hundred thousand are different products, even with the same instructions |

Most agents in a company are question 3 with an easy answer to question 2 — a
support reply, a document summary, a form filled from an email. Those do not
need a frontier model, and paying for one is the most common way an agent
budget disappears.

## What to pick, by what the agent does

| The agent… | Reach for | Why |
|---|---|---|
| Answers from your documents and cites them | A **mid-tier** model with a large context window | Retrieval does the hard part. The model's job is to read what it was handed and not embellish |
| Classifies, extracts, routes, rewrites | The **cheapest** model that passes your own test | The task has a right answer, so quality is measurable and the floor is lower than it feels |
| Plans across many steps and tools | A **frontier** model | Deciding *which* tool to call next is where cheap models fail, and they fail by looping |
| Writes something a customer reads | A **frontier or strong mid-tier** model | Tone and refusal behaviour are where the difference shows up, and both are visible to the person you least want to annoy |
| Handles data that cannot leave the building | An **open-weights** model you host | See below — this is question 1, and it is not a quality trade you get to argue with |

!!! tip "Start one tier up, then come down"

    Build the agent on a strong model until it behaves the way you want, then
    change the profile to a cheaper one and see whether anybody notices. Doing it
    the other way round means debugging your instructions and the model at the
    same time, and you will blame the wrong one.

## Closed models or open weights

Both are first-class here. The 27 providers include the closed frontier labs,
the open-weights hosts, and two keyless entries — [Ollama](models.md) and a
LiteLLM proxy — for models running on hardware you own.

| | Closed models (API) | Open weights (hosted) | Open weights (your hardware) |
|---|---|---|---|
| Examples in the picker | Anthropic, OpenAI, Google, xAI | Groq, Together, Fireworks, Nebius, DeepSeek | Ollama, a LiteLLM proxy |
| Best available quality | Yes, at the frontier | Close, and closing | Bounded by your GPU |
| Data leaves your network | Yes, to that vendor | Yes, to that host | **No** |
| Cost shape | Per token, no floor | Per token, usually cheaper | Fixed — you bought the hardware |
| Who fixes a regression | The vendor, on their schedule | The host | You, and only if you moved |
| Good reason to pick it | The work is genuinely hard | High volume, ordinary work | Data residency, or volume that dwarfs the hardware |

The honest summary: **closed models are still ahead on the hardest reasoning,
and the gap does not matter for most of what a company automates.** An agent
that reads a policy document and answers a question about it is not a frontier
task, and running it on open weights you host is often the better engineering
decision as well as the cheaper one.

!!! warning "Self-hosting a model is a real commitment"

    A GPU that idles is still billed, somebody has to keep the runtime patched,
    and a model you host has no vendor to escalate to. Pick it when data
    residency requires it or when your volume genuinely dwarfs the hardware —
    not to save money on forty conversations a day.

## Putting a gateway in front

Three of the 27 are not model vendors but routers: **OpenRouter**, **Vercel AI
Gateway** and a **LiteLLM proxy** you run. Each gives one key and one endpoint in
front of many models.

That is worth it when you want central spend control across teams outside
AgenticOS too, or when you are still deciding and want to try several models
without a procurement cycle per vendor. It costs you a hop, a second place a
request can fail, and — for a hosted router — a second company seeing the
traffic.

## What actually drives the bill

Not the model name. **The context.**

A run's cost is dominated by how many tokens go *in*, and what goes in is your
instructions, the retrieved documents, the conversation so far, and every tool
result. An agent with a 4,000-word system prompt and eight retrieved chunks per
turn is expensive on any model.

So before changing the model, check three things:

- **`default_top_k` on the knowledge capability.** Eight chunks where three
  would do is the most common quiet overspend.
- **Instructions that repeat themselves.** They are read on every single turn.
- **[Context management](reference/capabilities.md)**, which keeps a long
  conversation inside the window instead of re-sending all of it.

[Budgets](governance.md#budgets) are the backstop, not the plan: a budget stops a
run before the model request, so a misjudged model shows up as an agent that
stopped answering rather than an invoice at the end of the month.

## Changing your mind later

A model profile names the model; agents point at the profile. **Change the
profile and every agent using it moves, without one of them being republished.**

That is the whole reason the indirection exists, and it is what makes the advice
on this page safe to follow: pick something reasonable now, measure what your
own work actually needs, and move.

Fallbacks live on the same profile. Put a second provider behind the first and
an outage becomes a slower answer rather than an incident — worth doing on any
agent a customer can reach.

## Embeddings are a separate, permanent choice

Retrieval uses an embedding model, and it is **fixed when a collection is
created**. Two models of equal width write into different vector spaces, and
search would go on comparing them as though they were the same — so changing it
means re-embedding the collection.

Pick it once, per collection, and see [File processing](file-processing.md)
before you do.

## Recap

- The choice is **per agent**, not per company, and a model profile exists so
  you can change it later without republishing anything.
- **Where the data may go** outranks every other consideration.
- Most agents in a company do **not** need a frontier model; build on one, then
  come down and see whether anybody notices.
- **Context drives the bill**, not the model name — check `default_top_k` and
  your instructions before you change providers.
- The **embedding model is permanent per collection**. Choose that one carefully.

[The mechanics: profiles, providers, fallbacks and cost →](models.md)
