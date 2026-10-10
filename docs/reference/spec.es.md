---
source_sha: "b5383e1a56be"
---

# El spec del agent { #the-agent-spec }

El tipo que más peso soporta de toda la plataforma: el Builder lo edita, la base
de datos lo versiona, la factory lo instancia y los clientes lo exportan como
YAML a sus propios repositorios de git.

Se genera a partir del código fuente, porque el razonamiento vive en los
docstrings — y por eso la documentación de campos generada más abajo se queda en
inglés.

::: app.agents.spec.AgentSpec

## Variables { #variables }

`{{nombre}}` en `instructions` se rellena al empezar cada run: con una variable del
sistema que la plataforma conoce (la fecha y la hora, quién ha iniciado sesión y sus
[grupos](../departments.md), la organización, el agent, el canal) o con una de las `variables` propias del agent.
`time_zone` decide qué reloj lee `{{current_time}}`. Publicar rechaza un nombre que
no sea ninguna de las dos cosas.

::: app.agents.spec.PromptVariableSpec

## Delegación { #delegation }

Dos formas, y [Conceptos](../concepts.md#delegate-vs-inline-specialist) explica a
cuál recurrir. `subagents` contiene la primera; la segunda vive en la
configuración de la [capability `subagents`](capabilities.md#delegation).

::: app.agents.spec.SubagentRef

::: app.agents.spec.SpecialistSpec

## Budgets { #budgets }

::: app.agents.spec.BudgetSpec

## Avisos { #alerts }

::: app.agents.spec.NotificationSpec

::: app.agents.spec.AlertSpec

::: app.agents.spec.AlertAudience

## Ajustes del modelo { #model-settings }

::: app.agents.spec.ModelSettingsSpec

## Observabilidad { #observability }

::: app.agents.spec.ObservabilitySpec
