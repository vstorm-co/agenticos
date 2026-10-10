# The agent spec

The most load-bearing type in the platform: the Builder edits it, the database
versions it, the factory instantiates it, and clients export it to their own git
repositories as YAML.

Generated from the source, because the reasoning lives in the docstrings.

::: app.agents.spec.AgentSpec

## Variables

`{{name}}` in `instructions` is filled in when each run starts: a system variable
the platform knows (the date and time, who is signed in, the organization, the
agent, the channel) or one of the agent's own `variables`. `time_zone` decides
which clock `{{current_time}}` reads. Publishing refuses a name that is neither.

::: app.agents.spec.PromptVariableSpec

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
