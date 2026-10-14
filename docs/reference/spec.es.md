---
source_sha: "02ec08e2ff51"
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

## Voz a texto { #speech-to-text }

El proveedor, el modelo, la clave y el idioma con los que se transcriben el
dictado de un agent y las notas de voz de canal que hereda, cuando difieren de
los de la organización. La clave es el id de un secreto del vault, nunca la
clave misma. [Servicios de ML](../ml-services.md#which-engine-a-recording-reaches)
tiene el orden en que se resuelven. Un spec que lleva este bloque no se puede
importar en un despliegue anterior al bloque: su spec rechaza los campos que no
conoce.

::: app.agents.spec.SpeechToTextSpec
