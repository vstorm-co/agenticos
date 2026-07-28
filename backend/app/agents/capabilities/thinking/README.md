# Thinking

Lets the model reason before it answers. Contributes no tools.

## Why it is a capability and not a model setting

Reasoning is the setting people most want per agent — a triage bot answering in
Slack wants none of it, an agent drafting a migration plan wants all of it — and
the platform already has one place where "what this agent does" is composed: the
capability picker. Putting it there costs no new concept, arrives with a
generated config form, and is enabled and disabled the same way everything else
is.

It is deliberately *not* also a field on `model_settings`. Two controls writing
one provider parameter disagree eventually, and the disagreement is silent:
whichever one the merge happens to apply last wins, and the Builder shows both
as if both mattered. `model_settings` names the parameters it forwards; the
`thinking` key is not among them, and a spec written before this capability
existed has it folded into a binding on load (see `SPEC_VERSION` 6 in
`app/agents/spec.py`).

## Why it wraps nothing

The builder returns `pydantic_ai.capabilities.Thinking` directly. It sets the
unified `thinking` setting in `ModelSettings`, which works across providers —
provider-specific settings (`anthropic_thinking`, `openai_reasoning_effort`)
take precedence where both are set, and nothing here sets those. A capability of
ours around it would be a second place for the same value to be written.

`register`'s builder signature already allows this: it returns
`AbstractCapability[Any] | None`, not one of ours.

## Configuration

| Field | Default | What it is |
|---|---|---|
| `effort` | unset | `minimal`, `low`, `medium`, `high` or `xhigh` |

Unset means the provider's own default effort, which is what `Thinking(effort=True)`
asks for. A level a provider does not implement maps to its nearest one —
`xhigh` becomes `high`, `minimal` becomes `low` — so an agent stays portable
across a model swap.

## What this deliberately does not do

**It does not offer "off".** `ThinkingLevel` includes `False`, which means
"disable thinking, and be ignored on a model that always thinks". Not binding
the capability says the same thing to every model that can be told either way,
and the picker already reads as an on/off switch — a capability whose config can
turn itself off is two switches for one decision.

**It does not expose provider-specific reasoning.** `anthropic_thinking` and
`openai_reasoning_effort` are richer, and a spec that names one stops being
portable across the model profile it happens to run on. The unified setting is
the whole point.

**It does not reason about cost.** A thinking model bills for tokens the user
never sees. The budget capability is what stops that, and it applies whether or
not this is on.
