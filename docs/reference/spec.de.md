---
source_sha: "be354afc92ae"
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

## Spracherkennung { #speech-to-text }

Der Anbieter, das Modell und die Sprache, mit denen das Diktieren an einen Agent
und die von ihm geerbten Sprachnachrichten aus Kanälen transkribiert werden, wo
sie von denen der Organisation abweichen.
[ML-Dienste](../ml-services.md#which-engine-a-recording-reaches) nennt die
Reihenfolge, in der sie sich auflösen. Ein Spec, der diesen Block trägt, lässt
sich nicht in ein Deployment importieren, das älter ist als der Block: dessen
Spec lehnt Felder ab, die er nicht kennt.

::: app.agents.spec.SpeechToTextSpec
