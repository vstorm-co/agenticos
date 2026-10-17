---
source_sha: "c7ee53ab1f4e"
---

# Der Agent-Spec { #the-agent-spec }

Der tragendste Typ der Plattform: der Builder bearbeitet ihn, die Datenbank
versioniert ihn, die Factory instanziiert ihn, und Kunden exportieren ihn als
YAML in ihre eigenen Git-Repositories.

Aus der Quelle generiert, weil die Begründung in den Docstrings steht — und
deshalb bleibt die generierte Felddokumentation unten englisch.

::: app.agents.spec.AgentSpec

## Variablen { #variables }

`{{name}}` in `instructions` wird zu Beginn jedes Runs ausgefüllt: mit einer
Systemvariable, die die Plattform kennt (Datum und Uhrzeit, die angemeldete
Person und ihre [Gruppen](../departments.md), die Organisation, der Agent, der
Kanal), oder mit einer der eigenen
`variables` des Agents. `time_zone` bestimmt, welche Uhr `{{current_time}}` liest.
Die Veröffentlichung lehnt einen Namen ab, der keines von beiden ist.

::: app.agents.spec.PromptVariableSpec

## Delegation { #delegation }

Zwei Formen, und [Konzepte](../concepts.md#delegate-vs-inline-specialist)
erklärt, zu welcher man greift. `subagents` hält die erste; die zweite steht in
der Konfiguration der [Capability `subagents`](capabilities.md#delegation)
selbst.

::: app.agents.spec.SubagentRef

`external_agents` nennt in der Organisation registrierte Remote Agents über A2A, die die
[Delegation](capabilities.md#remote-agents) neben diesen aufruft.

::: app.agents.spec.ExternalAgentRef

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
