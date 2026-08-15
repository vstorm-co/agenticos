# Tool search

Lets the agent find a tool from a large set instead of carrying every tool's
schema in its context. Contributes no tool of its own.

## Why it is a capability

An agent may bind an arbitrary number of [MCP](../../../../../docs/mcp.md) servers,
and every tool a server exposes is a schema the model reads on every request
whether or not it ever calls it. Tool search moves that cost off the hot path: the
tools are hidden until the model discovers the one it needs, natively where the
provider supports it and through a local `search_tools` function elsewhere.

## Why it wraps nothing

The builder returns `pydantic_ai.capabilities.ToolSearch` directly. A capability
of ours around it would be a second place for the same behaviour to live. The one
piece of logic is mapping our `auto` — always present so the Builder's picker has
something to show — onto the library's `None`.

## Why enabling it defers the MCP toolsets

`ToolSearch` is inert with nothing marked `defer_loading=True`, and a deferred
tool with no search to find it is a tool the model can never call — so the two are
paired or not at all. `factory._defer_for_tool_search` is that pairing: when the
capability is bound, the connected servers' toolsets are marked for deferred
loading; when it is not, they are left alone and the agent pays nothing. The
registry's own tools stay visible, being few and chosen per agent.

## Why it contributes no model-facing tool

The `search_tools` function materialises only once `ToolSearch` wraps a toolset
that has deferred tools, which is a property of the assembled agent rather than of
the capability in isolation. Built on its own it resolves to no toolset at all, so
there is nothing to declare, gate or rename — hence `tools=()`.

## Why it needs no metering

The two local strategies (`auto`'s keyword fallback and `keywords`) run in Python
and spend no tokens; native strategies run inside the provider's own request,
whose usage the budget guard already meters; and the discovery round-trips are
ordinary model requests the same guard wraps. The only shape that would escape the
guard — a custom search callable that itself calls a model or an embedding — is
deliberately not exposed, so the config offers named strategies only.

## Configuration

| Field | Default | What it is |
|---|---|---|
| `strategy` | `auto` | `auto`, `keywords`, `bm25`, `regex` |
| `max_results` | 10 | how many matches the local search returns; ignored by native search |

`bm25` and `regex` force an Anthropic-native algorithm and error at request time
on a provider without native tool search. The model is resolved separately from
the spec, so that is a run-time cost the author accepts by naming one; `auto`
never fails this way.
