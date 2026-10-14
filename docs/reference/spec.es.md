---
source_sha: "fe0087d9fc16"
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

## Voz { #voice }

Cómo atiende el agent una [llamada de voz](../voice.md): el modelo realtime, la
clave del vault, la voz y los límites propios de la llamada. Es opcional, y un
bloque con todo vacío se lee como si no hubiera bloque, así que los specs
escritos antes de él cargan sin cambios y `SPEC_VERSION` no se movió. Como el
bloque de voz a texto, un spec que lo lleva no se puede importar en un
despliegue anterior al bloque.

| Campo | Qué contiene |
|---|---|
| `provider` | Un provider del catálogo realtime: `openai`, `azure`, `google` o `xai` |
| `model` | Un modelo realtime de ese provider. Para Azure, déjalo vacío y usa los dos campos de abajo |
| `deployment` | Solo Azure: el nombre del deployment al que van las llamadas |
| `base_model` | Solo Azure: el modelo del catálogo que ejecuta ese deployment, que decide sus voces y su precio |
| `secret_id` | La clave del vault con la que se sostienen las llamadas: un id, nunca la clave |
| `voice` | Una de las voces del modelo; vacío usa la voz por defecto del modelo |
| `language` | Un código ISO-639-1 en el que habla el agent; vacío sigue a quien llama |
| `max_call_seconds` | La llamada más larga, de 60 a 3000, y como mucho la llamada más larga de la organización |
| `voice_note` | Hasta 1000 caracteres que se añaden a las instrucciones del agent solo en las llamadas |

Toda regla que abarca varios campos se comprueba al publicar la versión, no al
guardar el borrador, porque el Builder autoguarda entre elegir un provider y
elegir su modelo. La publicación se rechaza, nombrando la sección de voz,
cuando:

- falta el provider, o el catálogo de este despliegue no tiene ese provider;
- falta el modelo o no es un modelo realtime que el catálogo ofrezca para ese
  provider (para Azure, el modelo base), o una sección de Azure no nombra ningún
  deployment;
- la voz no es una de las voces del modelo;
- no se ha elegido ninguna clave, o la clave no pasa la comprobación común: su
  propósito no es el provider, su tipo no es el del provider (`api_key`, o
  `azure_openai` para Azure), pertenece a otra organización o quien publica no
  puede verla;
- el idioma no es un código que las llamadas acepten;
- la llamada más larga supera la llamada más larga de la organización.

Las capabilities que una llamada no puede ejecutar no bloquean la publicación;
se dejan fuera de las llamadas y el Builder las enumera.

::: app.agents.spec.VoiceSpec
