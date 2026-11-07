# Tool search

Lets the agent find a tool from a large set instead of carrying every tool's
schema in its context. Contributes no tool of its own.

## Why it is a capability

An agent can enable many capabilities and bind an arbitrary number of
[MCP](../../../../../docs/mcp.md) servers. Each exposed tool adds a schema the
model reads on every request. Tool search hides selected tools until the model
discovers the one it needs, natively where the provider supports it and through
a local `search_tools` function elsewhere.

## Why it inherits discovery

`ConfiguredToolSearch` extends `pydantic_ai.capabilities.ToolSearch` to select
eligible function tools and resolved MCP toolsets for deferral. It inherits native
and local discovery from Pydantic AI. Capability lifecycle hooks keep running;
only function tool definitions are marked for deferred loading. The builder maps
our `auto` onto the library's `None`.

## How deferral is selected

`ToolSearch` is inert with nothing marked `defer_loading=True`, and a deferred
tool with no search to find it is a tool the model can never call — so the two are
paired or not at all. The factory applies the configured policy when assembling
the agent. By default it defers MCP tools and keeps capability tools visible,
preserving existing specs. Enable `defer_capabilities` to defer eligible function
tools from enabled capabilities too; disable `defer_mcp_servers` to keep MCP tools
visible. Both switches can be enabled together.

Exclusions keep whole capabilities, whole MCP server namespaces or individual
tools visible from the first request. They do not grant access to an unbound or
disallowed tool. Provider-native built-ins and capability hooks remain active;
skills keep their own `load_capability` discovery. Realtime voice does not use
Tool search deferral.

## Why it contributes no model-facing tool

The `search_tools` function materialises only once `ToolSearch` wraps a toolset
that has deferred tools, which is a property of the assembled agent rather than of
the capability in isolation. Built on its own it resolves to no toolset at all, so
there is nothing to declare, gate or rename — hence `tools=()`.

## Why it needs no metering

The local strategies (`auto`'s keyword fallback, `keywords` and `local_bm25`) run in Python
and spend no tokens; native strategies run inside the provider's own request,
whose usage the budget guard already meters; and the discovery round-trips are
ordinary model requests the same guard wraps. The only shape that would escape the
guard — a custom search callable that itself calls a model or an embedding — is
deliberately not exposed, so the config offers named strategies only.

## Configuration

| Field | Default | What it is |
|---|---|---|
| `strategy` | `auto` | `auto`, `keywords`, `local_bm25`, `bm25`, `regex` |
| `max_results` | 10 | how many matches the local search returns; ignored by native search |
| `defer_capabilities` | `false` | defer eligible function tools from enabled capabilities |
| `defer_mcp_servers` | `true` | defer tools from bound MCP servers |
| `exclude_capabilities` | `[]` | capability IDs whose tools stay visible |
| `exclude_mcp_servers` | `[]` | normalized MCP tool prefixes whose tools stay visible |
| `exclude_tools` | `[]` | final exposed tool names that stay visible, after prefixing and renaming |

For example, `exclude_mcp_servers: [github_work]` keeps the tools of the
`github-work` connection visible. Personal bindings use their actual account
namespace, commonly the catalog key such as `notion`; multiple accounts can have
different namespaces. `exclude_tools: [github_work_search]` keeps only that
exposed tool visible. Exclusions affect visibility only; connection and binding
allowlists still decide which tools the agent can call.

`bm25` and `regex` force an Anthropic-native algorithm and error at request time
on a provider without native tool search. The model is resolved separately from
the spec, so that is a run-time cost the author accepts by naming one; `auto`
never fails this way.

`local_bm25` provides provider-independent lexical ranking over the authorized deferred tool catalog. It tokenizes identifiers (including camel case), descriptions and argument schemas, weights rare terms, normalizes document length and boosts identifiers. It uses no embeddings or extra model request; the existing result limit bounds what enters context. Shipped starters use five results.
