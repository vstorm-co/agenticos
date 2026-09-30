---
source_sha: "5a5133da4c49"
---

# Nodos de workflow { #workflow-nodes }

Cada paso que puede contener un workflow: con qué se configura, qué lee, qué
produce y qué significa un fallo. La paleta del editor muestra los mismos nodos
del mismo registro. La documentación de campos de abajo se genera desde el
código, por eso sigue en inglés.

Algunas reglas valen para todos los nodos:

- **Una arista fija el orden y un binding lleva un valor.** Los campos de
  entrada de un nodo se enlazan a salidas anteriores, a un literal o a una
  referencia de archivo o de tabla. Ver
  [Configurar un nodo](../workflows.md#configuring-a-node).
- **Una ruta dentro de un valor de forma libre se comprueba cuando el nodo se
  ejecuta.** La carga de un trigger, un registro mapeado y la respuesta
  estructurada de un agent no tienen forma fija, así que un binding como
  `payload.email` se acepta al publicar y se valida contra su destino cuando el
  nodo se despacha. Un valor que no encaja hace fallar el run con
  `INVALID_BINDING`, y el handler nunca lo ve.
- **Los recursos se comprueban dos veces.** Publicar rechaza una colección, una
  versión de agent, una credencial o un destinatario que el autor del grafo no
  puede alcanzar. Cada run lo vuelve a comprobar con su propio principal, porque
  el acceso puede retirarse entre medias.
- **El tipo de efecto y los reintentos** deciden qué puede hacer el motor tras
  un fallo. Un paso `pure` o `idempotent` se reintenta. Un paso que puede haber
  actuado ya y no da ninguna garantía se detiene para una persona. La
  [política](#error-handling) propia de un nodo fija cuántas veces se reintenta,
  cuánto puede durar una llamada y adónde va un fallo.

## Triggers { #triggers }

Un workflow empieza por un trigger, el nodo en el que empieza su grafo. Publicar una
versión enciende su trigger; consulta
[Iniciar un workflow desde fuera de la consola](../workflows.md#starting-a-workflow-from-outside-the-console).
Cada trigger pasa a los pasos siguientes aquello con lo que su superficie inició el
run, congelado al admitir el run y como mucho `WORKFLOW_RUN_MAX_INPUT_BYTES`. Un run de
prueba iniciado con una entrada de otra forma hace fallar el trigger con
`TRIGGER_INPUT_INVALID`. Un segundo trigger, o un trigger por el que no empieza el
grafo, se rechaza al publicar.

### core.input { #core-input }

**API request.** Se inicia con una petición HTTP o por un WebSocket. Su id sigue siendo `core.input`, así que un grafo escrito antes de que Manual y API se separaran sigue empezando desde la API. Entrega al grafo
la entrada del run como `payload`, lo que haya enviado quien llama, y nombra la
superficie en `triggered_by`.

::: app.workflows.contracts.io.WorkflowInputPayload

Sus **campos de entrada** convierten la entrada en un contrato. Un campo tiene un
nombre, un tipo - texto, número, número entero, sí o no, fecha u opción - y si es
obligatorio. Sin campos, un run acepta cualquier objeto JSON. Con campos, **Start a
run** pide cada uno por su nombre, un run cuya entrada omite uno, envía uno del tipo
equivocado o uno no declarado se rechaza antes de empezar con
`WORKFLOW_RUN_INPUT_INVALID`, y un binding a `payload.<campo>` se comprueba por tipo
al publicar.

::: app.workflows.nodes.core_input._handler.InputField

### trigger.manual { #trigger-manual }

**Manual.** Lo inicia una persona - **Run** en el editor, o **Start a run** en su
página de runs. Entrega al grafo lo mismo que **API request** y acepta los mismos
campos de entrada, que el editor pide antes de empezar el run.

### trigger.chat { #trigger-chat }

**Chat message.** Se inicia con un mensaje en el chat, con este workflow elegido para
responder. El texto de su `core.output` se escribe de vuelta en esa conversación.

::: app.workflows.nodes._triggers.ChatTriggerOutput

### trigger.webhook { #trigger-webhook }

**Webhook.** Se inicia con una entrega firmada a la dirección propia del workflow, que
la primera publicación del nodo crea junto con su secreto de firma.

Antes de publicarlo, **Listen for test event** en el panel Output del disparador
abre una URL de prueba para el borrador durante dos minutos. La única llamada que
se le envía, un objeto JSON, queda fijada como salida del disparador, así que cada
paso posterior se puede probar con una entrega real. La URL de prueba no comprueba
ninguna firma y nunca inicia un run.

::: app.workflows.nodes._triggers.WebhookTriggerOutput

### trigger.schedule { #trigger-schedule }

**Schedule.** Se inicia según un reloj, en la zona horaria del workflow y como mucho una
vez por minuto.

::: app.workflows.nodes._triggers.ScheduleTriggerConfig

::: app.workflows.nodes._triggers.ScheduleTriggerOutput

### trigger.table_record { #trigger-table-record }

**New table record.** Se inicia con un registro añadido a su tabla que cumple cada
filtro tal como se añadió. Publicarlo requiere acceso de lectura a la tabla.

::: app.workflows.nodes._triggers.TableRecordTriggerConfig

::: app.workflows.nodes._triggers.TableRecordTriggerOutput

### trigger.workflow_call { #trigger-workflow-call }

**Called by a workflow.** Lo inicia el paso `workflow.run` de otro workflow, con los
campos que declara - los mismos que **Manual** - y nunca a mano ni por la API. La
entrada de quien llama se comprueba contra ellos antes de que empiece la ejecución.

### trigger.workflow_failed { #trigger-workflow-failed }

**On failure of a workflow.** Se inicia una vez por cada ejecución real fallida de
un workflow cuyos ajustes nombran este como su workflow de errores, como el miembro
que lo eligió. Una ejecución iniciada por este disparador nunca inicia a su vez un
workflow de errores.

::: app.workflows.nodes._triggers.WorkflowFailedTriggerOutput

## core.output { #core-output }

Lo que responde el workflow. Sus campos enlazados pasan a ser el `output` del
run, que devuelve la API y entrega la superficie que lo invoca. Tiene los mismos
campos que la salida de `agent.run`, así que la respuesta de un agent se enlaza
directamente. Una salida sin nada enlazado es una respuesta vacía.

::: app.workflows.contracts.io.WorkflowOutputPayload

## webhook.respond { #webhook-respond }

**Respond to webhook.** Responde a la entrega que inició el run con un estado (de
200 a 599), cabeceras y un `body` JSON vinculado desde un paso anterior. Una
entrega a un grafo con este paso lo espera en lugar de recibir `202`, como mucho
`WORKFLOW_WEBHOOK_RESPONSE_TIMEOUT_SECONDS`. La respuesta es el primer paso respond
que termina, un reintento de la misma entrega la recibe de nuevo y el run sigue
después. Un run que termina sin llegar al paso responde `202` si tuvo éxito y
`500` si no. Las cabeceras que pertenecen a la propia respuesta de la API se
rechazan al publicar: el encuadre, `Content-Type`, `Set-Cookie` y las cabeceras
CORS y de políticas del navegador.

::: app.workflows.nodes.webhook_respond.WebhookRespondConfig

## data.map { #data-map }

Construye un registro pequeño y tipado a partir de salidas anteriores. Cada
mapeo lee un valor con una expresión JMESPath y lo convierte a `string`,
`number`, `integer`, `boolean`, `json`, `file_ref` o `table_ref`. Un valor que no
se puede convertir falla con `MAPPING_COERCION_FAILED` y nombra el campo.

::: app.workflows.nodes.data_map._handler.DataMapConfig

::: app.workflows.nodes.data_map._handler.FieldMapping

## data.filter y data.combine { #data-filter-and-data-combine }

**Filter a list** conserva los elementos de una lista vinculada para los que se
cumple una condición JMESPath sobre `item` e `index`, y dice cuántos descartó.
**Combine lists** hace una lista de `first` y `second`: `append` pone una tras otra,
`by_position` une los objetos de la misma posición, y `by_key` une a cada objeto de
la primera el objeto de la segunda con el mismo `key`. Si ambos tienen un campo,
gana la segunda; unir elemento a elemento necesita objetos y, si no, falla con
`COMBINE_NEEDS_OBJECTS`.

::: app.workflows.nodes.data_filter._handler.DataFilterConfig

::: app.workflows.nodes.data_combine._handler.DataCombineConfig

## Transform { #transform }

Los pasos **Transform** transforman una lista de objetos sin un paso de código. Cada
uno toma `items`, una lista vinculada desde un paso anterior, y la mayoría entrega
`items`, así que se encadenan.

| Paso | Hace |
|---|---|
| `transform.edit_fields` | Fija campos con expresiones JMESPath sobre cada `item`, quita campos o conserva solo los fijados |
| `transform.sort` | Ordena por campos en orden, ascendente o descendente |
| `transform.limit` | Conserva los primeros o los últimos elementos |
| `transform.remove_duplicates` | Conserva el primero de cada grupo de elementos iguales en los campos indicados, o enteros |
| `transform.aggregate` | Reúne los valores de cada campo de todos los elementos en una lista por campo, como `values` |
| `transform.split_out` | Convierte una lista dentro de cada elemento en elementos propios |
| `transform.summarize` | Cuenta, suma, promedia, halla el menor o el mayor, o cuenta valores distintos, por grupo |
| `transform.date_time` | Ahora, o un `value` vinculado desplazado una cantidad, escrito en una zona horaria - la del workflow salvo que el paso indique otra |
| `transform.crypto` | Calcula el hash o codifica en base64 el `text` vinculado, o crea un UUID o hex aleatorio |

Un campo es una ruta con puntos, `customer.email`, y un elemento sin él nunca es un
error. Sort lo pone al final, Remove duplicates trata "falta" como un valor propio,
Aggregate y Summarize lo omiten, Split out conserva el elemento tal cual, y Edit
fields fija `null` donde su expresión no encuentra nada. Crypto no es para secretos:
nada en él usa una clave.

Encadenados, responden preguntas habituales sin un paso de código:

- **Los mejores leads, una vez cada uno** - **Remove duplicates** por `email`,
  **Sort** por `score` descendente, **Limit** a 10, y luego **Edit fields** dejando solo
  `name` y `score`, listos para un mensaje.
- **Totales por región** - **Split out** `lines`, para que cada línea de pedido sea un
  elemento, y luego **Summarize** la `sum` de `amount` agrupada por `region`: un
  elemento por región con `sum_amount`.
- **Una lista de direcciones** - **Aggregate** `email` entrega `values.email`, todas
  las direcciones en una lista, para cualquier ajuste que acepte una lista.

Cada paso lee `items` del anterior. `tests/integration/test_workflow_transform_composed.py`
ejecuta los dos primeros tal cual.

::: app.workflows.nodes.transform._handler.EditFieldsConfig

::: app.workflows.nodes.transform._handler.SummarizeConfig

::: app.workflows.nodes.transform._handler.DateTimeConfig

## logic.if y logic.merge { #logic-if-and-logic-merge }

`logic.if` evalúa una condición JMESPath sobre su `value` enlazado y sigue por el
puerto `true` o `false`. Cada nodo de la rama no tomada queda registrado como
`skipped`. `logic.merge` vuelve a unir las dos ramas. Se ejecuta cuando la rama
tomada llega a él y pasa la salida de esa rama como `value`. Publicar comprueba
que las entradas de un merge salen de un mismo `logic.if` por puertos distintos,
de modo que siempre se ejecuta exactamente una de ellas.

Las expresiones pueden seleccionar, filtrar y comparar, y llamar a un conjunto
fijo de funciones puras: `abs`, `avg`, `ceil`, `contains`, `ends_with`,
`floor`, `join`, `keys`, `length`, `max`, `merge`, `min`, `not_null`,
`reverse`, `sort`, `starts_with`, `sum`, `to_array`, `to_number`, `to_string`,
`type` y `values`. Null, `false` y una cadena, lista u objeto vacíos son falsos,
y todo lo demás es verdadero, incluido `0`. Una expresión que no se puede
analizar, o que llama a otra cosa, no se puede publicar.

::: app.workflows.nodes.logic_if._handler.LogicIfConfig

::: app.workflows.nodes.logic_merge._handler.LogicMergeOutput

## logic.switch { #logic-switch }

**Switch.** Envía la ejecución por la primera de muchas ramas cuya regla se cumple.
Cada regla tiene un nombre, que es el puerto de su rama, y una condición JMESPath
sobre el `value` vinculado, probadas en orden; `otherwise` se lleva la ejecución
cuando ninguna se cumple. Las ramas se reúnen en un `logic.merge`, que las acepta
porque siempre se toma exactamente una. Una regla que falla con sus datos hace fallar
el paso con `CONDITION_FAILED` y nombra la regla.

::: app.workflows.nodes.logic_switch._handler.LogicSwitchConfig

::: app.workflows.nodes.logic_switch._handler.LogicSwitchOutput

## knowledge.search { #knowledge-search }

Busca en colecciones de conocimiento una `query` enlazada y devuelve los
fragmentos como fuentes tipadas, la mejor primero. Un resultado vacío es una
búsqueda correcta. Una colección que ya no existe, o que el principal del run ya
no puede leer, hace fallar el paso con `COLLECTION_NOT_ACCESSIBLE`. El paso nunca
busca en menos colecciones de las que nombra el grafo.

::: app.workflows.nodes.knowledge_search._handler.KnowledgeSearchConfig

::: app.workflows.contracts.io.SourceRef

## Decisiones { #decisions }

Tres pasos hacen a Jev, de TypeSafe, una pregunta tipada sobre un `text` enlazado,
con una clave de API de TypeSafe del vault. Jev no escribe texto: responde la
pregunta con una confianza de 0 a 1, en una sola petición, y solo puede responder
con una de las respuestas que el paso permite. Por debajo del `min_confidence` del
paso, sale por su puerto `unsure`, así que el workflow decide ahí qué hace una
persona o un agent con un caso dudoso.

| Paso | Pregunta | Sale por |
|---|---|---|
| `decide.yes_no` | una pregunta de sí o no | `yes`, `no` o `unsure` |
| `decide.choose` | cuál de hasta 255 opciones encaja | `out` con la `choice`, o `unsure` |
| `decide.score` | dónde queda el texto en una escala de 2 a 10 niveles | `out` con el `score`, o `unsure` |

La clave se comprueba al publicar y se vuelve a leer en cada run. Una clave que ya
no existe o no está compartida hace fallar el paso con `SECRET_NOT_USABLE`, un
modelo que no responde con `DECISION_FAILED`, que se reintenta según la política
del paso, y un despliegue construido sin el extra `browser` con
`DECISION_MODEL_UNAVAILABLE`. Un merge puede volver a unir las ramas de una
decisión, como las de un paso If / else.

::: app.workflows.nodes._decide.DecisionConfig

::: app.workflows.nodes.decide_choose._handler.ChooseConfig
    options:
      show_bases: false

::: app.workflows.nodes.decide_score._handler.ScoreConfig
    options:
      show_bases: false

## Canales { #channels }

Slack, Mattermost y Telegram tienen cada uno su propio grupo de pasos, que actúan
como uno de los bots de la organización en esa plataforma a través del mismo
adaptador por el que van sus respuestas, así que un mensaje que envía un workflow
llega de ese bot, y un paso puede leer lo que el bot puede leer. Una plataforma solo
tiene los pasos que sus bots pueden dar.

| Paso | Slack | Mattermost | Telegram | Pasa adelante |
|---|---|---|---|---|
| **Send a message** (`<platform>.message.send`) | sí | sí | sí | dónde se envió |
| **Read messages** (`<platform>.messages.read`) | sí | sí | - | `messages`, del más antiguo |
| **List members** (`<platform>.members.list`) | sí | sí | administradores | `members`, con sus ids de la plataforma |
| **Find channels** (`<platform>.channels.find`) | sí | sí | - | `channels` |

Un paso solo acepta un bot de su propia plataforma, y un bot habla por toda la
organización, así que actuar como él requiere `channels:manage`: al autor del grafo
para publicar, y al principal del run en cada run. Un bot borrado, apagado o de otra
plataforma hace fallar el paso con `CHANNEL_NOT_USABLE`. Una plataforma que rechaza
una llamada al ejecutarse lo hace fallar con `CHANNEL_UNSUPPORTED`, y una que no
responde, con `CHANNEL_CALL_FAILED`. El envío nunca se repite solo.

::: app.workflows.nodes._channels.ChannelBotConfig

::: app.workflows.nodes.channel_read._handler.ChannelReadConfig
    options:
      show_bases: false

::: app.workflows.nodes.channel_read._handler.ChannelReadOutput

::: app.workflows.nodes.channel_members._handler.ChannelMembersOutput

::: app.workflows.nodes.channel_find._handler.ChannelFindOutput

## agent.run { #agent-run }

Pregunta a un agent publicado, en la versión exacta que fija el paso, a través
del mismo runner que el chat y la API, con el presupuesto, las aprobaciones, los
guardrails y el historial de runs del agent. El run se registra con la superficie
`workflow`. Las `sources` enlazadas se añaden al prompt como contexto numerado.
Una llamada a una herramienta que requiere aprobación detiene el paso, y la
decisión reanuda el mismo run del agent.

Un agent con un formato de respuesta propio pasa su objeto como `structured`.
`structured_output_schema` pide otra forma en su lugar: el agent se ejecuta con
ese esquema, y una respuesta que lo incumple vuelve al modelo para corregirla. El
objeto se comprueba una vez más antes de que se ejecute nada después. Un agent que
nunca produce uno que encaje hace fallar el paso con `AGENT_RUN_FAILED`, y una
respuesta sin objeto donde se pidió uno, con `STRUCTURED_OUTPUT_MISMATCH`.

| Cómo terminó el run del agent | Resultado del paso |
|---|---|
| Completed | Completed |
| Esperando aprobación | Espera y luego reanuda el mismo run |
| Presupuesto superado | `AGENT_BUDGET_EXCEEDED` |
| Bloqueado por un guardrail | `AGENT_GUARDRAIL_BLOCKED` |
| En otro caso | `AGENT_RUN_FAILED` |

Los `attachments` vinculados son imágenes de los archivos del run - una descarga,
una página de PDF renderizada, una foto transformada - que se muestran al agent como
imágenes y no como un enlace que no puede abrir. Solo se muestran PNG, JPEG, WebP y
GIF. Cualquier otro archivo falla con `UNSUPPORTED_ATTACHMENT_TYPE`, así que lee
primero el texto de un documento con `text.extract`.

Nunca se reintenta automáticamente, porque un agent puede haber llamado a
herramientas con efectos secundarios.

::: app.workflows.nodes.agent_run._handler.AgentRunConfig

::: app.workflows.nodes.agent_run._handler.AgentRunOutput

## http.request { #http-request }

Llama a una API HTTP. Cada petición y cada redirección pasa la comprobación SSRF
del despliegue y se envía a la dirección que esa comprobación aprobó. Una
credencial es una [HTTP credential](../secrets.md#kinds) del vault, y solo se
envía a los orígenes que permite el secreto. La respuesta se lee dentro de
`max_response_bytes` y se devuelve sin `Set-Cookie`, sin las cabeceras de
autenticación y sin el token.

La credencial va como token bearer, autenticación Basic, una cabecera con el
nombre que indiques o, con `query`, un parámetro de URL con el nombre que indiques.
**Import cURL** en el editor lee un comando pegado de la documentación de una API en
el método, la URL, las cabeceras y el cuerpo JSON. Una credencial del comando nunca
se queda en el paso: el paso queda configurado para enviarla igual, y el formulario
del vault se abre con ella rellenada.

Un `GET` puede recorrer una lista por páginas con `pagination`: siguiendo una URL
siguiente que nombra la respuesta, devolviendo un cursor o contando un parámetro de
página. Los elementos de `items_path` de cada página se reúnen en `items`, en orden.
La paginación se detiene cuando no hay página siguiente, cuando una página no tiene
elementos o en `max_pages`, con `complete` en falso. Todas las páginas juntas leen
como mucho `max_response_bytes`, y una página siguiente en otro origen no recibe la
credencial.

| Qué pasó | Resultado |
|---|---|
| La URL es privada, loopback, metadata o no es http(s) | `URL_REFUSED`, no se envía nada |
| La URL está fuera de los orígenes de la credencial | `SECRET_ORIGIN_DENIED`, no se envía nada |
| La conexión nunca se abrió | `HTTP_UNREACHABLE`, se reintenta |
| Enviada, sin respuesta, `GET` o cabecera de idempotencia | `HTTP_NO_RESPONSE`, se reintenta |
| Enviada, sin respuesta, cualquier otra escritura | Incierto: el run se detiene para una persona |
| Distinto de 2xx | `HTTP_ERROR_STATUS`, o la respuesta como salida con `on_error_status: complete` |
| Mayor que el límite | `RESPONSE_TOO_LARGE` |
| El `items_path` de una página encuentra algo que no es una lista | `PAGE_ITEMS_NOT_A_LIST` |

::: app.workflows.nodes.http_request._handler.HttpRequestConfig

::: app.workflows.nodes.http_request._handler.HttpAuth

::: app.workflows.nodes.http_request._handler.HttpPagination

::: app.workflows.nodes.http_request._handler.HttpRequestOutput

## notification.send { #notification-send }

Notifica a miembros de la organización en la aplicación, por email o por ambos,
a través del centro de notificaciones. Los destinatarios son miembros indicados
por id. En el momento de ejecutarse, cada uno debe seguir siendo un miembro
activo que puede ver el workflow, y los demás se descartan. Si no queda nadie, el
paso falla con `NO_PERMITTED_RECIPIENTS`. Las preferencias de cada persona para
**Workflow notifications** siguen aplicándose. El paso termina cuando la
notificación queda escrita, y el email se entrega después. Un paso reintentado no
escribe una segunda notificación.

::: app.workflows.nodes.notification_send._handler.NotificationSendConfig

## human.approval { #human-approval }

**Ask for approval** detiene el run hasta que una persona apruebe o rechace lo
que está a punto de hacer, y sigue por `approved` o `rejected`. Quien aprueba lee
el `title` del paso y los `details` vinculados en la pestaña **Approvals** de
Activity o por `GET /api/v1/workflow-approvals`. `approvers` nombra quién puede
decidir, y esas personas reciben un aviso en la aplicación; vacío, puede
cualquiera con `approvals:decide`. Pasado `timeout_hours` la solicitud caduca y el
paso sale por `rejected` con `decision: "expired"`. Cancelar el run cancela lo que
pidió. Cada ejecución del paso pregunta una vez, así que un reintento o una
iteración de un bucle nunca preguntan dos veces lo mismo.

::: app.workflows.nodes.human_approval._handler.HumanApprovalConfig

::: app.workflows.nodes.human_approval._handler.HumanApprovalOutput

## flow.wait { #flow-wait }

**Wait.** Detiene la ejecución en el paso durante `seconds` desde que se alcanza, o
hasta un `until` vinculado, y luego sigue; como mucho treinta días. El paso queda
aparcado en un reloj cuya fila de despacho vence entonces, así que la espera
sobrevive a un reinicio del worker y no ocupa ninguno, y las demás ramas siguen
mientras tanto. Un momento ya pasado sigue enseguida, y el plazo de la ejecución
sigue vigente.

::: app.workflows.nodes.flow_wait._handler.FlowWaitConfig

::: app.workflows.nodes.flow_wait._handler.FlowWaitOutput

## Gestión de errores { #error-handling }

Cada nodo acepta una `policy` opcional junto a su configuración.

| Campo | Por defecto | Efecto |
|---|---|---|
| `timeout_seconds` | ninguno | Una llamada que sigue en marcha pasado ese tiempo se corta. Un paso sin escritura externa, o cuya llamada es idempotente, falla con `NODE_TIMEOUT` y puede reintentarse. Una escritura que puede haber llegado queda incierta y se detiene para una persona |
| `retry.max_attempts` | `WORKFLOW_RETRY_CEILING` | Intentos en total, el primero incluido. Solo se reintenta un fallo que el nodo marca como `retryable`, y publicar rechaza más de un intento para un paso cuya llamada no es seguro repetir |
| `retry.backoff`, `base_delay_seconds`, `max_delay_seconds` | `exponential`, `2`, `60` | La espera entre intentos: fija, o duplicándose hasta el techo |
| `on_error` | `fail_run` | `route` envía un fallo que los reintentos no resolvieron por el puerto `error` del nodo en lugar de hacer fallar el run |

Un nodo cuya política encamina sus errores tiene un puerto de salida `error`
adicional. Lleva el `WorkflowError`: `code`, `message`, `details` y
`retryable`. La salida normal del nodo solo existe en sus otros puertos, así
que publicar rechaza un binding que lee la salida en el camino de error, o el
error en el camino de éxito. El puerto de error tiene que llevar a algún sitio,
y los dos caminos pueden volver a unirse en un `logic.merge`.

`error.handle` recibe ese error en su puerto `in` y sale por la primera rama
cuyos `code` y `retryable` coinciden, o por `default`, que debe estar
conectada. `error.raise` hace fallar su rama con un código, un mensaje y unos
detalles que fija el autor.

Algunos fallos nunca se encaminan. Un acceso revocado, un budget agotado (del
run o de un agent), un run cancelado, un plazo vencido, el límite de nodos por
run y un efecto de resultado desconocido terminan el run se conecte como se
conecte el grafo. Un conflicto de revisión o un error de validación se puede
encaminar, pero nunca se reintenta a ciegas, porque la misma entrada vuelve a
fallar igual.

::: app.workflows.contracts.policy.NodePolicy

::: app.workflows.contracts.policy.RetryPolicy

::: app.workflows.nodes.error_handle._handler.ErrorHandleConfig

::: app.workflows.nodes.error_handle._handler.HandledError

::: app.workflows.nodes.error_raise._handler.ErrorRaiseConfig

## Bucles { #loops }

`control.foreach` ejecuta su cuerpo una vez por cada elemento de una lista
`items` enlazada, un elemento cada vez y en orden. Después continúa por su
puerto `done` con `results` en el orden de entrada, `errors` y `count`. El
cuerpo empieza en `loop.item`, conectado desde el puerto `body` del bucle, que
ofrece `item`, `index` y `count`. Termina en `loop.yield`, cuyo `value` enlazado
es el resultado de la iteración. Ninguna arista vuelve al bucle. Un paso del
cuerpo puede enlazarse a cualquier cosa que se ejecutara antes del bucle, y nada
fuera del cuerpo puede enlazarse a su interior.

La lista se congela cuando arranca el bucle, así que una iteración nunca ve una
fuente que cambió durante el run. Una lista más larga que
`WORKFLOW_FOREACH_MAX_ITEMS`, o más grande que
`WORKFLOW_FOREACH_MAX_MANIFEST_BYTES`, se rechaza en lugar de truncarse. Una
lista vacía da `results: []` sin ejecutar el cuerpo. Los pasos de cada
iteración se ejecutan en su propio ámbito, con sus propios intentos, claves de
idempotencia y costes. La siguiente iteración se programa en la transacción que
termina la anterior, así que un reinicio continúa en el índice correcto y nunca
repite una escritura confirmada. Una aprobación dentro de una iteración reanuda
esa iteración.

Con `item_error_policy: stop`, el valor por defecto, el bucle falla en la
primera iteración fallida y los detalles del error llevan el `scope_path` de esa
iteración. Con `collect`, el resultado del elemento es `null`, el error se añade
a `errors` y el bucle sigue. Los bucles se anidan como mucho
`WORKFLOW_FOREACH_MAX_DEPTH` niveles, y cada ejecución de nodo que crea un run
cuenta para `WORKFLOW_RUN_MAX_NODE_RUNS`. No hay bucle `while` ni map paralelo.

::: app.workflows.nodes.control_foreach._handler.ForeachConfig

::: app.workflows.nodes.control_foreach._handler.ForeachOutput

::: app.workflows.nodes.loop_item._handler.LoopItemOutput

## Virtual Tables { #virtual-tables }

Siete nodos leen y escriben [Virtual Tables](../virtual-tables.md) a través del
mismo servicio que usan la consola, la API y las herramientas de tablas de un agent.
La validación, los conflictos de revisión, las cuotas, el historial, los recibos y
la auditoría son los mismos en cada superficie.

| Nodo | Hace | Efecto |
|---|---|---|
| `table.record.create` | Añade un registro | write |
| `table.record.upsert` | Crea o actualiza el registro con un external id | write |
| `table.record.update` | Cambia algunas celdas de un registro | write |
| `table.record.delete` | Borra un registro y conserva su historial | write |
| `table.record.get` | Busca un registro por id o external id | read |
| `table.record.query` | Lee una página de registros, filtrada y ordenada | read |
| `table.create` | Crea una tabla nueva con un esquema tipado | write |

Cada nodo de registros fija su tabla en la configuración. Al publicar se comprueba
contra el autor del grafo, y en cada run se vuelve a comprobar como el principal del
run. Los valores se enlazan y se indican por id o por etiqueta de columna. Un
registro vuelve con sus valores dos veces: `values` por id de columna, para los
bindings, y `fields` por etiqueta, para leer. Una clave que no nombra ninguna
columna viva falla con `UNKNOWN_COLUMN`.

Una escritura lleva la clave de operación del paso, así que un paso reintentado
repite su primera escritura. Un update, upsert o delete sin revisión enlazada escribe
en la revisión actual del registro, leída bajo el bloqueo del registro, y la repetición
se mantiene aunque la primera escritura ya haya movido esa revisión. Una revisión que se movió es
`REVISION_CONFLICT`, que no se reintenta: la misma revisión volvería a
chocar, así que encamínalo con `error.handle` hacia una lectura nueva. Un registro que falta es `found: false` de
`table.record.get`, no un fallo. `table.record.query` lee como mucho 100 registros
por página e indica `has_more`. Nunca lee por su cuenta una tabla grande entera.

`table.create` es un nodo propio y necesita `tables:create`. Su salida lleva la
tabla nueva como una referencia a la que se puede enlazar el `table` de un nodo
posterior, y el id de cada columna por etiqueta. Una tabla que lee o escribe un
workflow vivo, o una columna que fija, no se puede archivar mientras la versión
actual de ese workflow la use.

Cuatro pasos más leen qué tablas tiene la organización, y no cambian nada.

| Paso | Hace | Sale por |
|---|---|---|
| `table.list` | enumera las tablas que ve el principal, buscadas por nombre | `out`, con `tables` y `total` |
| `table.describe` | lee el nombre y las columnas de una tabla | `out`, con `columns` |
| `table.exists` | si existe una tabla con exactamente este nombre | `yes`, con su id, o `no` |
| `table.record.exists` | si algún registro coincide con los filtros | `yes`, con el id del primero, o `no` |

`table.exists` compara el nombre entero sin distinguir mayúsculas, así que un
workflow puede crear su tabla la primera vez que se ejecuta y reutilizarla
después. Las dos preguntas salen por exactamente un puerto, y un `logic.merge`
puede volver a unir las ramas.

::: app.workflows.nodes.table_list._handler.TableListOutput

::: app.workflows.nodes.table_describe._handler.TableDescribeOutput

::: app.workflows.nodes.table_record_exists._handler.TableRecordExistsConfig

::: app.workflows.nodes._tables.TableRecordOutput

::: app.workflows.nodes.table_record_get._handler.TableRecordLookup

::: app.workflows.nodes.table_record_query._handler.TableRecordQueryConfig

::: app.workflows.nodes.table_create._handler.TableCreateConfig

::: app.workflows.nodes.table_create._handler.TableCreatedOutput

## Archivos { #files }

Un archivo que crea un paso se guarda como archivo de su run y se pasa como `FileRef`:
un id, el tipo que resultaron ser sus bytes y un tamaño. Un paso lee un archivo solo si
lo creó su propio run o el run se inició con él - un `FileRef` vinculado en el grafo,
comprobado al publicar contra un run que el autor puede ver. Cualquier otro archivo,
de otra organización o de otro run, es `FILE_NOT_FOUND`, así que conocer un id no
concede nada. Los archivos de un run se listan y se descargan desde su página.

| Nodo | Hace | Efecto |
|---|---|---|
| `http.download` | Descarga un archivo por HTTP, en streaming, y lo guarda | write |
| `http.upload` | Envía un archivo a un endpoint HTTP, en streaming desde el almacenamiento | write |
| `file.read` | Lee un archivo como texto, un valor JSON o filas CSV | read |
| `file.write` | Guarda texto, un valor JSON o filas como archivo | write |
| `text.extract` | El texto de un archivo TXT, JSON, CSV, PDF con texto o DOCX | read |
| `convert.csv_to_json` | Un archivo CSV como archivo JSON de filas | write |
| `convert.json_to_csv` | Una lista JSON de objetos planos como archivo CSV | write |
| `convert.text_to_file` | Texto como archivo TXT | write |
| `convert.pdf_to_png` | Páginas elegidas de un PDF como imágenes PNG | write |
| `image.transform` | Recorta, redimensiona, gira o convierte una imagen | write |

Una descarga sigue las mismas reglas de SSRF y credenciales que `http.request`, hasta
cinco redirecciones. Su cuerpo se cuenta a medida que llega y se rechaza por encima de
`max_bytes`, y su tipo se detecta por los bytes, así que una cabecera no puede engañar
a `expected_content_types`. `text.extract` no hace OCR: una página escaneada hace
fallar el paso con `TEXT_EXTRACTION_NEEDS_OCR` y nombra las páginas. Un documento
dañado es `DOCUMENT_CORRUPT`, un documento de Word que se descomprime más allá de los
límites de archivo de una subida al chat es `DOCUMENT_TOO_LARGE`, y un PDF protegido
con contraseña `DOCUMENT_ENCRYPTED`.

Una imagen se mide antes de decodificarse. Su ancho por alto, una zona de recorte y un
tamaño solicitado se comprueban cada uno contra `CHAT_IMAGE_MAX_PIXELS`, y el
resultado no lleva ningún metadato del origen. Todo paso que guarda un archivo guarda
uno nuevo en cada intento, así que es `at_least_once`.

::: app.workflows.nodes.http_download._handler.HttpDownloadConfig

::: app.workflows.nodes.http_upload._handler.HttpUploadConfig

::: app.workflows.nodes.file_read._handler.FileReadConfig

::: app.workflows.nodes.text_extract._handler.TextExtractOutput

::: app.workflows.nodes.convert_pdf_to_png._handler.ConvertPdfToPngConfig

::: app.workflows.nodes.image_transform._handler.ImageTransformConfig

## Python { #python }

Dos nodos ejecutan Python, para dos tipos de trabajo.

`code.python.simple` ejecuta un script corto en el sandbox de Monty, que no tiene
sistema de archivos, ni red, y tiene una biblioteca estándar pequeña. El script lee los
valores vinculados como `args`, y su última expresión es el `result` del paso, que debe
ser un valor JSON. Solo calcula, así que es `pure` y requiere `code:execute`.

En el editor, el script de un paso de código se escribe en un editor de código:
Python o JavaScript resaltado en ambos temas, Tab y Shift+Tab para sangrar, Enter
que conserva la sangría, paréntesis y comillas que se cierran al escribirlos, el
paréntesis junto al cursor enmarcado con su pareja, y las
claves del `args` vinculado ofrecidas al escribir `args["` o, en JavaScript,
`args.`. Esc y luego Tab sale del editor. **Test step** ejecuta solo el script con
lo que entregaron los pasos anteriores.

`code.python.sandbox` ejecuta Python completo con paquetes y los archivos del run en
la conexión `sandboxd` de la organización, y requiere `sandbox:execute`. El script
encuentra sus archivos de entrada en `inputs`, escribe archivos en `outputs` y fija
`result`. Es un trabajo duradero: el primer despacho lo inicia en segundo plano, y
cada uno posterior lo comprueba en la misma sesión, así que un worker reiniciado se
reconecta en lugar de volver a iniciarlo. Ninguna credencial de la plataforma llega
nunca al sandbox, y lo que el script alcanza más allá de sus archivos es la propia
configuración del runtime del host - elige un runtime sin red para trabajo que no es
de confianza.

| Qué pasó | Resultado |
|---|---|
| El resultado no es JSON | `PYTHON_OUTPUT_NOT_JSON` |
| El script lanzó una excepción o superó un límite | `PYTHON_ERROR` |
| El trabajo superó `timeout_seconds` | `PYTHON_SANDBOX_TIMEOUT`, la sesión purgada |
| No hay una conexión `sandboxd` utilizable | `SANDBOX_UNAVAILABLE` |
| Escribió más de 20 archivos o 100 MB, o imprimió más de 10 MB | `PYTHON_OUTPUT_TOO_LARGE`, medido en la sandbox antes de traer nada, y la sesión purgada |
| No se pudo alcanzar el host | `SANDBOX_UNREACHABLE`, se reintenta |

::: app.workflows.nodes.code_python_simple._handler.PythonSimpleConfig

::: app.workflows.nodes.code_python_sandbox._handler.PythonSandboxConfig

::: app.workflows.nodes.code_python_sandbox._handler.PythonSandboxOutput

## JavaScript { #javascript }

`code.javascript.sandbox` ejecuta JavaScript en Node como el mismo trabajo
duradero, en la misma conexión `sandboxd`, y necesita `sandbox:execute`. El
script es el cuerpo de una función asíncrona: lee los valores vinculados como
`args`, sus archivos de entrada en `inputs`, escribe archivos en `outputs`, puede
usar `await`, y lo que devuelve con `return` es el `result` del paso - `null`
cuando no devuelve nada. `require` carga los módulos propios de Node y lo que el
runtime tenga instalado. Elige un runtime con Node.

Sus fallos son los del sandbox de Python, con nombre de JavaScript: un error
lanzado es `JAVASCRIPT_ERROR`, un resultado que no es un valor JSON - una
función, un `BigInt` - es `JAVASCRIPT_OUTPUT_NOT_JSON`, y el límite de tiempo y
los límites de salida son `JAVASCRIPT_SANDBOX_TIMEOUT` y
`JAVASCRIPT_OUTPUT_TOO_LARGE`.

::: app.workflows.nodes.code_javascript_sandbox._handler.JavaScriptSandboxConfig

::: app.workflows.nodes.code_javascript_sandbox._handler.JavaScriptSandboxOutput

## workflow.run { #workflow-run }

**Run a workflow.** Ejecuta la versión publicada de otro workflow, una que empieza por
**Called by a workflow**, con el `input` vinculado, como actúa esta ejecución. El paso
espera a que termine la ejecución llamada y entrega su `output`, o falla con
`CALLED_WORKFLOW_FAILED` y el error de esa ejecución; con **Wait for it to finish**
desactivado, entrega enseguida la ejecución iniciada. La ejecución llamada queda
vinculada al paso y a la cadena de esta ejecución. Llamar a un workflow que ya se
ejecuta más arriba en la cadena falla con `WORKFLOW_CALL_LOOP`, y una llamada con más
de cinco niveles con `WORKFLOW_CALL_TOO_DEEP`. Una ejecución de prueba del borrador
llama de verdad al workflow publicado.

::: app.workflows.nodes.workflow_run._handler.WorkflowRunConfig

::: app.workflows.nodes.workflow_run._handler.WorkflowRunOutput

## Añadir un nodo { #adding-a-node }

Un nodo es un paquete bajo `backend/app/workflows/nodes/`: `__init__.py` registra
una `NodeDefinition`, `_handler.py` la implementa y `README.md` explica por qué
existe. `load_builtins` importa el paquete. `tests/test_workflow_node_layout.py`
hace cumplir esa estructura. Un handler devuelve `Completed`, `Waiting`, `Failed`
o `Uncertain` y nunca lanza una excepción. Lee el run para el que se ejecuta
desde `app.services.workflow_execution.context.current()`.

Un nodo tipado declara tres modelos de Pydantic: su configuración, que se fija en el
editor y se congela al publicar; su entrada, cuyos campos rellenan los enlaces; y su
salida, a la que se enlazan los pasos posteriores. `extra="forbid"` en cada uno mantiene
una errata fuera de un grafo publicado. Elige `retry_guarantee` según lo que haría una
repetición de la llamada: `idempotent` cuando el propio handler hace inofensiva una
repetición - una escritura en una tabla pasa `operation_key()` -, `at_least_once` cuando
una repetición es aceptable, y `none` cuando no lo es. Un nodo que lee o escribe un
recurso declara `check_resources`, que la publicación ejecuta contra el autor y cada run
contra su principal.

La consola dibuja un nodo a partir de su definición, con su icono y su tono en
`frontend/src/components/workflows/node-visuals.ts`. Prueba el handler directamente en
sus rechazos, y llévalo una vez por `tests/integration/workflow_run_support.py` para que
su configuración, sus enlaces y su salida queden demostrados en un run real.

::: app.workflows.contracts.definition.NodeDefinition
