# The `@register` contract

Source of truth: `backend/app/agents/capabilities/_registry.py`. Its module
docstring carries the reasoning; this is the operational summary.

## Arguments

| Argument | Notes |
|---|---|
| `id` | In every published spec and in clients' git repos. **Never change it.** |
| `name` | What the Builder's picker shows |
| `category` | Groups the picker: `knowledge`, `research`, `analysis`, `reasoning`, `utility` |
| `description` | What a *person* reads when choosing. Not the model-facing text |
| `tools` | **No default.** A tuple of `CapabilityToolInfo`; `()` for none |
| `config_schema` | A Pydantic model. Validated at publish; generates the Builder form |
| `side_effecting` | `True` routes every tool through the approval gate by default |
| `scopes` | Refused at build time if the org has not granted them |
| `secret` | A `SecretRequirement` — a *kind*, never an instance |
| `provider_executed` | Which tools the model provider runs itself, under which config. Approval on one is refused at publish |

`tools` having no default is deliberate: omitting it is a `TypeError` rather than a
capability whose tools cannot be gated.

Each `CapabilityToolInfo` carries `id` (stable, what approval and overrides key on),
optional `name` (defaults to `id`), and `description` — which should be the tool's
own docstring summary. The person choosing what needs approval and the model
choosing when to act should read the same text, not two paraphrases that drift.

## The builder function

```python
def _build(ctx: CapabilityBuildContext) -> Weather | None:
    config = ctx.config if isinstance(ctx.config, WeatherConfig) else WeatherConfig()
    return Weather(units=config.units)
```

`isinstance` narrowing rather than a cast is how every builtin does it: `ctx.config`
is typed as the base model because the registry does not know which schema this
capability declared, and a binding with no config at all gets its defaults instead
of a crash.

### `ctx` fields

- **`binding`** — the spec's entry: config, overrides, `secret_id`, `enabled`.
- **`config`** — already validated. Read its fields without re-checking.
- **`resources`** — what was resolved from the database for this run: collection
  names, skills. A capability never queries for them itself. The model asks *what*
  to search, never *where*.
- **`secret`** — the unsealed credential, present exactly when the capability
  declared one. A field of its own rather than an entry in `resources` because a
  resource may be logged and a secret may not.

### Returning `None`

Means "contributes nothing to *this* agent" — the capability is not attached at all.
`knowledge` does this when no collections are bound: a search tool that always
returns empty is worse than none, because the model keeps trying it and reasons from
the silence.

### Returning something we did not write

The signature is `CapabilityBuildContext -> AbstractCapability[Any] | None`, so
anything Pydantic AI ships is a valid return. `thinking/` registers
`pydantic_ai.capabilities.Thinking` and has no `_capability.py` at all. Wrapping one
of theirs to make it "ours" only adds a second place for the same value to be set.

The registry stamps the returned instance with the registry id — which is what the
approval gate matches on — so a foreign capability arrives with the same identity as
a local one.

## Scopes

Declared as strings, checked against what the organization granted when the agent is
assembled. Currently granted by default:
`knowledge:read`, `web:read`, `code:execute` (`DEFAULT_GRANTED_SCOPES` in
`app/services/agent_registry.py`). Per-organization scope management is roadmap work;
the check is live in the meantime.

## Conditional secrets

```python
secret=SecretRequirement(
    kind=SecretKind.API_KEY,
    description="The API key for the chosen search service",
    required_when=...,   # data, not a predicate
)
```

`required_when` narrows the requirement to the configurations that actually
authenticate. Without it, a capability offering both a keyless provider and a paid
one has to choose which of the two to break — `web_research` is the worked example
(`duckduckgo` needs nothing, `tavily` needs a key).

It is data rather than a callable because the Builder has to ask for a key at
exactly the moments the server will demand one, and only a value can cross the wire.

`needs_secret(config)` is the one answer, consulted by publish validation *and* by
the build, so the two cannot disagree — which would mean an agent that publishes and
then refuses to run, or worse, the reverse.

## Duplicate ids

A second registration under an existing id raises `RuntimeError` at import. Letting
the second win would make an agent's behaviour depend on import order — a bug that
only appears in production.
