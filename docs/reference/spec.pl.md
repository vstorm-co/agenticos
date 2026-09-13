---
source_sha: 74ed632657e1
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
