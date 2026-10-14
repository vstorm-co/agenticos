# The agent spec

The most load-bearing type in the platform: the Builder edits it, the database
versions it, the factory instantiates it, and clients export it to their own git
repositories as YAML.

Generated from the source, because the reasoning lives in the docstrings.

::: app.agents.spec.AgentSpec

## Delegation

Two shapes, and [Concepts](../concepts.md#delegate-vs-inline-specialist) explains
which to reach for. `subagents` holds the first; the second lives in the
[`subagents` capability's](capabilities.md#delegation) own config.

::: app.agents.spec.SubagentRef

::: app.agents.spec.SpecialistSpec

## Budgets

::: app.agents.spec.BudgetSpec

## Alerts

::: app.agents.spec.NotificationSpec

::: app.agents.spec.AlertSpec

::: app.agents.spec.AlertAudience

## Model settings

::: app.agents.spec.ModelSettingsSpec

## Observability

::: app.agents.spec.ObservabilitySpec

## Speech to text

The provider, model, key and language an agent's dictation and inherited channel
voice notes are transcribed with, where they differ from the organization's. The
key is a vault secret id, never the key itself.
[ML services](../ml-services.md#which-engine-a-recording-reaches) has the order
they resolve in. A spec that carries this block cannot be imported into a
deployment older than the block: its spec refuses fields it does not know.

::: app.agents.spec.SpeechToTextSpec
