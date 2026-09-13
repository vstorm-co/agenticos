---
source_sha: 74ed632657e1
---

# El spec del agent { #the-agent-spec }

El tipo que más peso soporta de toda la plataforma: el Builder lo edita, la base
de datos lo versiona, la factory lo instancia y los clientes lo exportan como
YAML a sus propios repositorios de git.

Se genera a partir del código fuente, porque el razonamiento vive en los
docstrings — y por eso la documentación de campos generada más abajo se queda en
inglés.

::: app.agents.spec.AgentSpec

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
