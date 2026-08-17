# Add a capability

A **capability** is the unit an agent is assembled from. It is what the Builder
shows as a switch and what a spec names by id.

It is deliberately not "a tool". A tool is an implementation detail — "knowledge
search" is one decision for the person configuring an agent, and whether it
exposes one function today and three tomorrow is not their problem. A capability
also covers things that are not tools at all: a budget guard, an approval gate,
a compaction strategy. One concept covers the whole assembly instead of two that
overlap awkwardly.

Code defines what exists; configuration only composes it. Nothing an operator
types can bring a new capability into being, which is what makes the set of
things an agent can do reviewable.

## The shape

One folder per capability under `backend/app/agents/capabilities/`:

```
weather/
  __init__.py       registration — the id, the name the picker shows, the builder
  _capability.py    the AbstractCapability subclass
  _toolset.py       the tools, and the text the model reads before calling them
  README.md         why this exists and what it deliberately does not do
```

This layout is not a suggestion — `tests/test_capability_layout.py` enforces it.
Every package has a `_capability.py`, every package offering tools of its own
has a `_toolset.py`, and `@register` appears in `__init__.py` and nowhere else
(a registration in a submodule only fires if something imports that module,
which is how a capability vanishes from the Builder with every test still
green). A capability with no tools — `clock`, `thinking` — is listed in that
test with the reason why, rather than carrying an empty module.

The tools live apart from the capability class because a tool's **name and
description are prompt**: the model reads them before deciding to call, and an
agent author may rewrite both per agent. Buried in a `get_toolset` closure they
are findable only by whoever wrote the class.

Read `clock/` for the smallest complete example and `knowledge/` for one with a
config schema, resources and a scope.

## 1. The capability

`_capability.py` — a dataclass extending `AbstractCapability`, building its
toolset lazily:

```python
"""Current weather for a place."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset


def _build_toolset(units: str) -> FunctionToolset[Any]:
    async def current_weather(city: str) -> dict[str, str]:
        """Get the current weather for a city.

        Use this when an answer depends on today's conditions rather than a
        seasonal average.
        """
        ...

    toolset: FunctionToolset[Any] = FunctionToolset()
    toolset.add_function(current_weather, takes_ctx=False)
    return toolset


@dataclass
class Weather(AbstractCapability[AgentDepsT]):
    """Gives an agent current conditions instead of a guess."""

    units: str = "metric"
    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        if self._toolset is None:
            self._toolset = _build_toolset(self.units)
        return self._toolset
```

The tool's docstring is the prompt. It is what the model reads when deciding
whether to call it, so it says *when to use this*, not what the function does —
see `~/.claude/standards/prompting.md`.

## 2. Register it

`__init__.py`:

```python
"""Weather capability — current conditions."""

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.weather._capability import Weather

__all__ = ["Weather"]


class WeatherConfig(BaseModel):
    units: str = Field(default="metric", pattern="^(metric|imperial)$")


@register(
    id="weather",
    name="Weather",
    category="data",
    description="Read current conditions for a place instead of assuming them.",
    tools=(
        CapabilityToolInfo(
            id="current_weather",
            description="Get the current weather for a city.",
        ),
    ),
    config_schema=WeatherConfig,
    scopes=("weather:read",),
)
def _build(ctx: CapabilityBuildContext) -> Weather | None:
    """Build the capability from its validated config."""
    config = ctx.config if isinstance(ctx.config, WeatherConfig) else WeatherConfig()
    return Weather(units=config.units)
```

- **`id`** goes into every published spec and is the one thing that must never
  change. Rename freely; re-id never.
- **`tools`** has no default, on purpose. It is what the Builder offers per-tool
  approval for and what the approval gate matches on, so a capability that declares
  nothing is a capability whose tools cannot be gated — and the dangerous half of
  that failure is silent: an author adds a second, side-effecting tool, forgets to
  declare it, and it runs unattended forever. Omitting the argument is a
  `TypeError`; a capability with genuinely no tools says `tools=()`. Each entry's
  `id` is what a spec's `tool_approval` and `tool_overrides` key on, and its
  `description` should be the tool's own docstring summary — the person choosing
  what needs approval and the model choosing when to act should read the same text,
  not two paraphrases that drift.
- **`config_schema`** generates the Builder's form and is validated at publish,
  so a bad value fails while somebody is looking at a form rather than mid-run.
- **`scopes`** are refused at build time when the organization has not granted
  them.
- **`side_effecting=True`** routes the capability's tools through the approval
  gate.
- **Returning `None`** means "contributes nothing to *this* agent" and the
  capability is not attached at all. `knowledge` does this when no collections
  are bound: a search tool that always returns empty is worse than none, because
  the model keeps trying it.
- **`ctx.resources`** carries what was resolved from the database for this run —
  collection names, skills. A capability never queries for them itself; the
  model asks *what* to search, never *where*.

**The builder may return a capability we did not write.** Its signature is
`CapabilityBuildContext -> AbstractCapability[Any] | None`, so anything Pydantic
AI ships is a valid return — `thinking/` registers `pydantic_ai.capabilities.Thinking`
and has no `_capability.py` at all. Wrapping one of theirs to make it "ours" only
adds a second place for the same value to be set. The registry stamps the
returned instance with the registry id, which is what the approval gate matches
on, so a foreign capability arrives with the same identity as a local one.

The `isinstance` narrowing rather than a cast is how every builtin does it:
`ctx.config` is typed as the base model because the registry does not know which
schema this capability declared, and a capability bound with no config at all
gets its defaults instead of a crash.

Then add the module to `load_builtins()` in `_registry.py`. A module nobody
imports does not exist as far as the Builder is concerned, which is the intended
coupling — registration is an import, not a scan.

## 3. Write the README

Every capability folder has one. Say why it exists, what it deliberately does
not do, and any decision a future reader would otherwise undo. This is where the
reasoning lives, not in the commit message.

## 4. Test it

`app/agents/**` is held to **100% coverage and it is enforced in CI** — a new
capability with an untested branch fails the build. See `## Testing` in
`CLAUDE.md`, and `tests/test_capability_registry.py` for the style.

Worth covering specifically:

- the config schema refusing a bad value, since that is the publish-time gate
- the builder returning `None` when it should contribute nothing
- the scope refusal, if the capability declares one
- the tool itself, including what it does when the thing it calls is unavailable

## Where it shows up

Nothing else needs changing. `GET /api/v1/agents/capabilities` serves the
registry, the Builder's picker renders from it, and `schema-form.tsx` generates
the configuration form from `config_json_schema()`. A capability added here is
in the product on the next restart.

Two things the generated form reads that are worth knowing while writing the
schema:

- **A field's default is drawn as its value**, not as placeholder grey. Nothing
  is stored until somebody edits it, so the field keeps tracking a default that
  later changes in code — but what a person sees is what will happen if they
  leave it alone. Give every optional field a sensible default and the form is
  filled in on arrival.
- **A `Literal` renders its raw values** unless the schema says otherwise, and
  raw values are spec format: `clear_tool_results` in a dropdown is a choice
  somebody makes by guessing. Say what each one does with
  `json_schema_extra={"x-enum-labels": {value: "what it does"}}` on the field —
  an extension keyword, because JSON Schema has none, kept beside the definition
  for the same reason `description` is.
- **A string is a one-line box** unless the schema says otherwise, and a prompt in
  one is a field nobody can read what they are editing in.
  `json_schema_extra={"x-multiline": True}` gets it the Markdown editor the
  agent's own instructions get — source or preview, and a refusal wired to the
  field. Same extension shape, same reason.

## Adding a tool to an existing capability

Usually the right move when the new behaviour belongs to a decision somebody has
already made — a second way to read the knowledge base is still "knowledge search".
Three steps, and the second is the one that gets forgotten:

1. **Write the function** in `_toolset.py` and add it to the toolset. Its docstring
   is the prompt; say *when to reach for this*, not what the function does.
2. **Declare it** in the `tools=` tuple in `__init__.py`. A tool the registry does
   not know about cannot be approved, cannot be renamed per agent, and does not
   appear in the Builder — it simply runs.
3. **Check the drift test.** `tests/test_capability_registry.py` builds every
   registered capability and compares the declared list against the tools the model
   is actually offered. It is what catches step 2 being skipped, and what reports
   the day an upstream package renames one of the tools we re-export — the `skills`
   capability's three come from `pydantic-ai-skills`, so their names are somebody
   else's to change.

If the new tool has side effects and the existing ones do not, that is a signal the
capability is now two decisions wearing one name. Prefer a second capability;
`side_effecting` is per capability, and per-tool `approval` in a spec is a way for
an *agent author* to be stricter than the default, not a substitute for declaring
the truth.

## Adding a tool nobody here has to write

If the tool is a call to a third-party API that already publishes an MCP server,
consider whether it belongs in code at all. A capability is right for something the
platform must guarantee; a server the vendor maintains is right for the rest. See
[MCP](../mcp.md) and
[Add a server to the MCP catalog](add-mcp-server.md).
