# The capability catalog

Everything an agent can *do* comes from one of two places: a capability
registered in this deployment's code, or an [MCP server](../mcp.md) somebody
connected. This page is the first list.

A capability is the unit worth switching on or off — one line in the Builder, one
entry in the spec. It is deliberately not "a tool": knowledge search is a single
decision for the person configuring an agent, and whether it exposes one function
today and three next month is not their problem. Capabilities also cover things
that are not tools at all, which is why `thinking` and `clock` are here with no
tools listed.

!!! note "The API is authoritative, this page is a snapshot"

    `GET /api/v1/agents/capabilities` serves the registry as it is in the running
    deployment, including anything added since this page was written. The Builder
    renders its picker and its configuration forms from that response. If the two
    disagree, the API is right.

## What ships

| id | Name | Category | Tools | Scope | Key |
|---|---|---|---|---|---|
| `knowledge` | Knowledge search | knowledge | `search_documents` | `knowledge:read` | — |
| `skills` | Skills | knowledge | `list_skills`, `load_skill`, `read_skill_resource` | `knowledge:read` | — |
| `web_research` | Web search | research | `web_search` | `web:read` | for paid services |
| `code_execution` | Run Python | analysis | `run_python` | `code:execute` | — |
| `charts` | Charts | analysis | `create_chart` | — | — |
| `thinking` | Thinking | reasoning | none, by design | — | — |
| `clock` | Date and time | utility | none, by design | — | — |

Two of those have no tools on purpose. `thinking` changes how the model runs
rather than what it can reach, and `clock` puts the date in the instructions —
neither leaves anything for a person to approve, so neither declares a tool. A
capability with genuinely no tools says so with `tools=()` rather than omitting
the argument; see [Add a capability](../howto/add-capability.md).

## Knowledge search

`search_documents` — *Search the organization's documents for passages relevant to
a question.*

Searches the collections the agent's spec binds and cites what it used. The model
asks *what* to search, never *where*: collections are resolved from the spec
before the run and handed to the capability, so an agent cannot reach a collection
nobody connected to it.

| Config | Default | Range |
|---|---|---|
| `default_top_k` | 5 | 1–50 |

`default_top_k` applies only when the model does not ask for a number itself.

Bound with no collections, this capability contributes **nothing** — it is not
attached at all. A search tool that always returns empty is worse than no search
tool, because the model keeps trying it and reasons from the silence.

## Skills

`list_skills`, `load_skill`, `read_skill_resource`

Written know-how the agent loads only when it decides it is relevant, one skill at
a time — the alternative being an instructions field that grows until every run
pays for every procedure. See [Skills](../skills.md) for what a skill is and how
one gets into an organization.

These three tools come from `pydantic-ai-skills`, so their names and wording are
somebody else's to change. A drift test compares what the registry declares
against the tools the model is actually offered, which is what reports the day
that happens.

## Web search

`web_search` — *Search the public web for current information.*

| Config | Default | Values |
|---|---|---|
| `method` | `duckduckgo` | `duckduckgo`, `native`, `tavily`, `brave`, `exa` |
| `max_results` | 5 | 1–10, ignored by `native` |

- **`duckduckgo`** — free, no account, results rendered as clickable sources.
- **`native`** — the model provider searches with its own index and returns its
  own citations. Only on models that support it.
- **`tavily`** — results summarised for a model to read.
- **`brave`** — an index of its own.
- **`exa`** — search by meaning rather than by keyword.

The three paid methods need an API key from the organization's
[secrets](../secrets.md), named by the binding's `secret_id`. The requirement is
conditional rather than flat: a flat one would either lock the free default behind
an account, or let a Tavily agent publish with nothing to authenticate with and
fail on its first search.

## Run Python

`run_python` — *Run a small Python program to compute something.*

A restricted sandbox with no network and no filesystem, which is why time and
memory are the only limits worth setting.

| Config | Default | Range |
|---|---|---|
| `timeout_secs` | 10 | > 0, ≤ 120 |
| `max_memory_mb` | 256 | 16–4096 |

Capped rather than open-ended, and per agent rather than per deployment: an author
raising a limit for one data-heavy agent should not need an operator or a
redeploy.

## Charts

`create_chart` — *Draw a chart of numbers you already have, so the user can see
them.*

Renders numbers the model already has. It does not fetch, compute or aggregate —
pair it with `code_execution` or `knowledge` for that. No configuration.

## Thinking

No tools. Asks the model to reason before it answers: slower and dearer, better on
work that needs several steps held in mind at once.

| Config | Default | Values |
|---|---|---|
| `effort` | unset | `minimal`, `low`, `medium`, `high`, `xhigh` |

Unset means the provider's own default effort. A level a provider does not have
maps to its closest one, so a spec stays portable across a model swap.

## Date and time

No tools. Puts the current date and time into the agent's instructions, so it
stops assuming one — the failure this fixes is an agent confidently reasoning
about "this quarter" from its training cutoff.

| Config | Default | |
|---|---|---|
| `timezone` | `UTC` | any IANA name, e.g. `Europe/Warsaw` |

## What a binding may change

The catalog is the deployment's answer to "what exists". A spec's
`capabilities[]` entry is one agent's answer to "how do I use it", and it may
change four things:

| Field | Effect |
|---|---|
| `config` | Validated against that capability's schema **at publish**, not at run time |
| `approval` | `default` \| `required` \| `never` for every tool the capability contributes |
| `tool_approval` | The same, per tool, overriding `approval` |
| `tool_overrides` | The `name` and `description` the model sees, per tool |
| `secret_id` | Which organization secret satisfies a declared key requirement |
| `enabled` | Off without losing the configuration |

Approval is why a capability declares its tools at all. "May this agent write
files" and "may it read them" are two decisions even though one capability answers
both, so enabling stays per capability while approving happens per tool. `default`
follows the capability's own `side_effecting` flag.

`tool_overrides` exists because a tool's description is the highest-leverage
prompt in the product — it is what the model reads before deciding to call —
and its name steers just as hard: `search_refund_policy` is not
`search_documents`. An agent that needs different behaviour from the same tool
usually needs these reworded, not a second capability written.

Both are keyed on the tool's **stable id**, never on the name the model sees. That
is what keeps an approval gate attached to a renamed tool; keying it on the
visible name would mean a rename silently removes the gate and a side-effecting
call goes unattended with nothing reporting it. An id no such capability exposes
is refused at publish, and so is a name no model could call.

## Scopes

A capability may declare scopes the organization must have granted, checked when
the agent is assembled:

| Scope | Declared by |
|---|---|
| `knowledge:read` | `knowledge`, `skills` |
| `web:read` | `web_research` |
| `code:execute` | `code_execution` |

All three are granted by default today (`DEFAULT_GRANTED_SCOPES` in
`app/services/agent_registry.py`). Per-organization scope management is
[roadmap](../ROADMAP.md) work; the check is live and honest in the meantime rather
than disabled and forgotten.

## Adding to this list

Capabilities are code — nothing an operator types brings a new one into being,
which is what makes the set of things an agent can do reviewable. See
[Add a capability](../howto/add-capability.md) for a new one, or
[Add a tool to a capability](../howto/add-capability.md#adding-a-tool-to-an-existing-capability)
when the capability already exists.

For tools nobody here has to write, see [MCP](../mcp.md).
