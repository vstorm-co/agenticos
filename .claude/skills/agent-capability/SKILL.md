---
name: agent-capability
description: Add or change what an agent can do — a new tool the model can call, a new capability (knowledge, web search, charts, a guardrail, a compaction strategy), a tool rename, or a per-tool approval gate. Use whenever the ask is "give the agent a new tool/function/action", "add a capability", "let the agent do X". There is no @agent.tool and no assistant module in this project; every tool arrives through the capability registry.
---

# Capabilities — the only way a tool reaches a model

**Read `docs/howto/add-capability.md` first.** It is the walkthrough and it is
current. This file is the decision layer around it: what shape the work should
take, and the traps that are silent.

An agent here is *data*. There is no module with an `Agent` object to decorate —
`@agent.tool`, `RunContext[Deps]` and `app/agents/assistant.py` do not exist. An
agent is assembled per run from the capabilities its spec names, so a new tool is
always part of a capability.

## Pick the shape first

| The ask | Do this |
|---|---|
| A tool that belongs to a decision somebody already makes | Add it to that capability's `_toolset.py` **and** its `tools=` tuple |
| A genuinely new switch an agent author would want | New capability package |
| Behaviour change, not a tool (reasoning, a guard, injected context) | New capability with `tools=()` — see `clock/`, `thinking/` |
| A third-party SaaS that already publishes an MCP server | **No code.** See the `mcp-connections` skill and `docs/mcp.md` |
| Same tool, different wording for one agent | Not code either — `tool_overrides` in that agent's spec |

That last row catches a lot of requests. A tool's name and description *are*
prompt, and an agent needing different behaviour from the same tool usually needs
them reworded per agent, not a second tool written.

## Layout, which a test enforces

```
backend/app/agents/capabilities/<name>/
  __init__.py       @register(...) — and nowhere else
  _capability.py    the AbstractCapability subclass
  _toolset.py       the tools, and the text the model reads
  README.md         why this exists and what it deliberately does not do
```

`tests/test_capability_layout.py` enforces all four. `@register` in a submodule
only fires if something imports that module, which is how a capability vanishes
from the Builder with every test still green.

Read `clock/` for the smallest complete example, `knowledge/` for one with a config
schema, resources and a scope, `web_research/` for a conditional secret
requirement.

## The three things that fail silently

**1. A tool missing from `tools=`.** It still runs. It just cannot be approved,
cannot be renamed per agent, and does not appear in the Builder. The dangerous
half is that an author adds a *side-effecting* tool, forgets to declare it, and it
runs unattended forever. `tests/test_capability_registry.py` is the drift test that
catches this — it builds every registered capability and compares the declared list
against the tools the model is actually offered.

**2. A module missing from `load_builtins()`.** The capability does not exist as far
as the Builder is concerned. Registration is an import, not a scan.

**3. A changed `id`.** Ids are in every published spec and in clients' git
repositories. Rename the class freely; never re-id.

## Then

- Add the module to `load_builtins()` in `_registry.py`.
- Write the `README.md`. Reasoning goes there, not in the commit message.
- Test it — `app/agents/**` is at **100% and CI fails below it**. See the
  `backend-tests` skill.
- If the capability needs a credential, declare it as a `SecretRequirement` *kind*,
  never an instance. See the `vault-secrets` skill.
- Update `docs/reference/capabilities.md` — it is the human-readable catalog and it
  is a snapshot of the registry.

## Depth

- `references/registry-contract.md` — every `@register` argument, `ctx.resources`,
  returning `None`, scopes, conditional secrets, returning a capability we did not
  write.
- `references/approval-and-overrides.md` — how `side_effecting`, `approval`,
  `tool_approval` and `tool_overrides` resolve, and why everything keys on the
  stable tool id.
- `docs/reference/capabilities.md` — what ships today.
