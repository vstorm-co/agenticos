---
source_sha: "063feb1082a0"
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
Person, die Organisation, der Agent, der Kanal), oder mit einer der eigenen
`variables` des Agents. `time_zone` bestimmt, welche Uhr `{{current_time}}` liest.
Die Veröffentlichung lehnt einen Namen ab, der keines von beiden ist.

::: app.agents.spec.PromptVariableSpec

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
