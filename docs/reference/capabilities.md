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
| `sandbox` | Files & shell | analysis | `ls`, `read_file`, `glob`, `grep`, `write_file`, `edit_file`, `execute` | `sandbox:execute` | for Daytona |
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

## Files & shell

`ls`, `read_file`, `glob`, `grep` — *reading.*
`write_file`, `edit_file`, `execute` — *writing and running.*

A workspace that survives between turns. `code_execution` computes and forgets;
this remembers, and on a container-backed backend it has a real shell. An agent
granted both computes with one and keeps its work in the other — which is the
normal pairing on the `state` backend, because that one has no shell at all.

| Config | Default | Values |
|---|---|---|
| `backend` | `state` | `state`, `service` |
| `connection_id` | null | a registered sandbox connection; null takes the organization's default. `service` only |
| `session_scope` | `conversation` | `run`, `conversation`, `channel`, `user`, `agent` |
| `runtime` | null | an alias that connection's service allows; `service` only |
| `include_execute` | `true` | removes the shell entirely when off, rather than gating it |

There is no `docker` or `daytona` backend to choose. *Where* a sandbox runs is a
property of the connection an operator registered — Sandboxes in the app — so
naming the connection is naming the kind. Choosing them separately made it
possible to choose two things that disagree.

**`backend` is infrastructure; `session_scope` is a data-sharing policy.** Getting
the first wrong costs a feature. Getting the second wrong shows one person
another person's files, so it is worth reading twice:

| Scope | Who shares the workspace |
|---|---|
| `run` | Nobody — a fresh one every turn |
| `conversation` | Everyone in that chat. On Slack a thread *is* a chat, so threads do not share |
| `channel` | Every thread in one channel. A direct message has its own chat id, so people still get their own |
| `user` | One person, across every surface they reach this agent on |
| `agent` | **Everyone who talks to this agent**, across the organization |

`conversation` and `channel` exist as separate answers because a chat platform
makes them different things. `SlackAdapter` folds `thread_ts` into the chat id, so
`conversation` on Slack means one workspace per thread — fifty threads in a busy
channel is fifty containers and a `429` for the fifty-first person to reply.

The scope in the spec is the **default**. Each channel the agent is published to
can override it, on the exposure: an agent reached in web chat and on a Slack bot
is one agent in two situations, and one value for both was the wrong shape.
`user` scope is what carries a workspace across surfaces — the same person picking
up in Slack a conversation they started in web chat finds their files there.

`agent` is the one that crosses a boundary between people. The Builder warns at
the field, the file panel labels whose workspace it is rather than calling it "this
conversation's files", and setting it is recorded in the audit log — because a user
who sees a file they did not create should be able to find out why.

A spec chooses a connection and never an image, a mount, a network mode or a
ceiling. Those belong to whoever runs the deployment: a spec is authored in a
browser by anyone holding `edit` on the agent, and one that could name a container
image could name one whose entrypoint mounts the host. `runtime` is an alias, and
the Builder offers only the aliases that connection's service reports — read live,
because a stored copy would offer one the service has since stopped allowing.

What each backend costs to run:

| Backend | Needs | Shell | Where files live |
|---|---|---|---|
| `state` | nothing | no | this database, capped at `SANDBOX_STATE_MAX_BYTES` |
| `service` | a registered connection | yes | a container on that host, or Daytona's cloud on the organization's own account |

An operator can see what is running: Sandboxes lists this organization's open
sandboxes on its default host with their runtimes, idle times and memory, and the
activity log per sandbox. See [Configuration](../configuration.md#agent-workspaces).

Publishing is refused for a `service` workspace when the organization has
registered no connection, when the one it names is gone, or when that connection
has no credential — each by name, because all three are states a deployment
reaches *after* an agent was published and the fix is an operator's rather than the
author's.

**Only `execute` asks.** Side-effecting is declared per tool, and of the seven only
running a command is: a workspace is scratch space deleted with the conversation it
belongs to, so writing a file in it is not the class of act sending an email is —
and an agent that has to ask before every `write_file` cannot do multi-step work at
all, which is how an author ends up turning the gate off entirely and losing the one
that mattered. `execute` runs arbitrary commands on somebody's host.

A binding that wants the stricter behaviour sets it per tool:
`tool_approval: {"write_file": "required"}`. See [Governance](../governance.md) for
how an approval is put to a person.

**Some paths are refused whatever the approval policy says.** Credentials
(`**/.env`, `**/*.pem`, `**/*.key`, `**/credentials*`, `**/.ssh/**`, `**/.aws/**`)
and the system tree (`/etc/**`, `/usr/**`, `/proc/**` and their siblings) cannot be
read, written or edited — the agent gets a readable refusal and can carry on. `grep`
is filtered rather than refused, since a pattern over `/` legitimately covers the
workspace: matches inside an off-limits file are dropped, so a search cannot return
a line from one. Names are not secret, so `ls` and `glob` still show what is there;
only the contents are withheld.

Two things this is *not*. It is not a filter on commands — `execute` runs a shell,
an allowlist of command strings is defeated by `sh -c`, and what makes execution
safe is the container's isolation and the operator's network mode, not a pattern.
And it is not a substitute for the approval gate: refusal here is the code's flat
no, while `execute` asking a person is the decision an operator owns.

Files somebody attaches to a message land in `/uploads` — see
[File processing](../file-processing.md).

**Skills become files too.** An agent with both a workspace and skills gets each
skill as `/skills/<name>/SKILL.md` with its resources beside it, which is what
makes a skill's script runnable at all: it is on disk next to the shell that can
run it. There is deliberately no `run_skill_script` — `execute` already has the
approval gate and the operator's ceilings behind it, and a second execution path
would be a second set of rules to get wrong.

Those files are writable, and what the agent writes does **not** become a skill. A
skill is instructions every agent bound to it follows on every run, so a change is
recorded as a proposal and somebody holding `skills:edit` accepts or discards it —
see [Skills](../skills.md).

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
| `sandbox:execute` | `sandbox` |

All four are granted by default today (`DEFAULT_GRANTED_SCOPES` in
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
