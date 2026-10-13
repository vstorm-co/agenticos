---
source_sha: "be354afc92ae"
---

# Spec agenta { #the-agent-spec }

Najbardziej nośny typ na całej platformie: Builder go edytuje, baza danych
wersjonuje, factory tworzy z niego instancje, a klienci eksportują go jako YAML
do własnych repozytoriów git.

Generowany ze źródła, bo uzasadnienie mieszka w docstringach — i dlatego
wygenerowana niżej dokumentacja pól pozostaje po angielsku.

::: app.agents.spec.AgentSpec

## Delegowanie { #delegation }

Dwie formy, a [Koncepcje](../concepts.md#delegate-vs-inline-specialist)
wyjaśniają, po którą sięgnąć. `subagents` trzyma pierwszą; druga mieszka w
konfiguracji samej [capability `subagents`](capabilities.md#delegation).

::: app.agents.spec.SubagentRef

::: app.agents.spec.SpecialistSpec

## Budżety { #budgets }

::: app.agents.spec.BudgetSpec

## Alerty { #alerts }

::: app.agents.spec.NotificationSpec

::: app.agents.spec.AlertSpec

::: app.agents.spec.AlertAudience

## Ustawienia modelu { #model-settings }

::: app.agents.spec.ModelSettingsSpec

## Observability { #observability }

::: app.agents.spec.ObservabilitySpec

## Mowa na tekst { #speech-to-text }

Provider, model i język, którymi transkrybowane są dyktowanie do agenta i
dziedziczone notatki głosowe z kanałów, tam gdzie różnią się od tych organizacji.
[Usługi ML](../ml-services.md#which-engine-a-recording-reaches) opisują
kolejność, w jakiej się rozwiązują. Speca z tym blokiem nie da się zaimportować
do wdrożenia starszego niż ten blok: jego spec odrzuca pola, których nie zna.

::: app.agents.spec.SpeechToTextSpec
