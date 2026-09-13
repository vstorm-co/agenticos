---
source_sha: 74ed632657e1
---

# Der Agent-Spec { #the-agent-spec }

Der tragendste Typ der Plattform: der Builder bearbeitet ihn, die Datenbank
versioniert ihn, die Factory instanziiert ihn, und Kunden exportieren ihn als
YAML in ihre eigenen Git-Repositories.

Aus der Quelle generiert, weil die Begründung in den Docstrings steht — und
deshalb bleibt die generierte Felddokumentation unten englisch.

::: app.agents.spec.AgentSpec

## Delegation { #delegation }

Zwei Formen, und [Konzepte](../concepts.md#delegate-vs-inline-specialist)
erklärt, zu welcher man greift. `subagents` hält die erste; die zweite steht in
der Konfiguration der [Capability `subagents`](capabilities.md#delegation)
selbst.

::: app.agents.spec.SubagentRef

::: app.agents.spec.SpecialistSpec

## Budgets { #budgets }

::: app.agents.spec.BudgetSpec

## Benachrichtigungen { #alerts }

::: app.agents.spec.NotificationSpec

::: app.agents.spec.AlertSpec

::: app.agents.spec.AlertAudience

## Modelleinstellungen { #model-settings }

::: app.agents.spec.ModelSettingsSpec

## Observability { #observability }

::: app.agents.spec.ObservabilitySpec
