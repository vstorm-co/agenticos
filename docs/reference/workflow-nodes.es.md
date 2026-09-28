---
source_sha: "b554c0542c76"
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
  actuado ya y no da ninguna garantía se detiene para una persona.

## core.input { #core-input }

Donde empieza un workflow. Entrega al grafo la entrada del run como `payload`,
lo que haya aportado la superficie que lo invoca, y nombra esa superficie en
`triggered_by`. La entrada se congela al admitir el run y ocupa como mucho
`WORKFLOW_RUN_MAX_INPUT_BYTES`.

::: app.workflows.contracts.io.WorkflowInputPayload

## core.output { #core-output }

Lo que responde el workflow. Sus campos enlazados pasan a ser el `output` del
run, que devuelve la API y entrega la superficie que lo invoca. Tiene los mismos
campos que la salida de `agent.run`, así que la respuesta de un agent se enlaza
directamente. Una salida sin nada enlazado es una respuesta vacía.

::: app.workflows.contracts.io.WorkflowOutputPayload

## data.map { #data-map }

Construye un registro pequeño y tipado a partir de salidas anteriores. Cada
mapeo lee un valor con una expresión JMESPath y lo convierte a `string`,
`number`, `integer`, `boolean`, `json`, `file_ref` o `table_ref`. Un valor que no
se puede convertir falla con `MAPPING_COERCION_FAILED` y nombra el campo.

::: app.workflows.nodes.data_map._handler.DataMapConfig

::: app.workflows.nodes.data_map._handler.FieldMapping

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

## knowledge.search { #knowledge-search }

Busca en colecciones de conocimiento una `query` enlazada y devuelve los
fragmentos como fuentes tipadas, la mejor primero. Un resultado vacío es una
búsqueda correcta. Una colección que ya no existe, o que el principal del run ya
no puede leer, hace fallar el paso con `COLLECTION_NOT_ACCESSIBLE`. El paso nunca
busca en menos colecciones de las que nombra el grafo.

::: app.workflows.nodes.knowledge_search._handler.KnowledgeSearchConfig

::: app.workflows.contracts.io.SourceRef

## agent.run { #agent-run }

Pregunta a un agent publicado, en la versión exacta que fija el paso, a través
del mismo runner que el chat y la API, con el presupuesto, las aprobaciones, los
guardrails y el historial de runs del agent. El run se registra con la superficie
`workflow`. Las `sources` enlazadas se añaden al prompt como contexto numerado.
Una llamada a una herramienta que requiere aprobación detiene el paso, y la
decisión reanuda el mismo run del agent.

Con `structured_output_schema`, la respuesta debe ser un objeto JSON que cumpla
el esquema antes de que se ejecute nada después. Si no, el paso falla con
`STRUCTURED_OUTPUT_MISMATCH`.

| Cómo terminó el run del agent | Resultado del paso |
|---|---|
| Completed | Completed |
| Esperando aprobación | Espera y luego reanuda el mismo run |
| Presupuesto superado | `AGENT_BUDGET_EXCEEDED` |
| Bloqueado por un guardrail | `AGENT_GUARDRAIL_BLOCKED` |
| En otro caso | `AGENT_RUN_FAILED` |

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

| Qué pasó | Resultado |
|---|---|
| La URL es privada, loopback, metadata o no es http(s) | `URL_REFUSED`, no se envía nada |
| La URL está fuera de los orígenes de la credencial | `SECRET_ORIGIN_DENIED`, no se envía nada |
| La conexión nunca se abrió | `HTTP_UNREACHABLE`, se reintenta |
| Enviada, sin respuesta, `GET` o cabecera de idempotencia | `HTTP_NO_RESPONSE`, se reintenta |
| Enviada, sin respuesta, cualquier otra escritura | Incierto: el run se detiene para una persona |
| Distinto de 2xx | `HTTP_ERROR_STATUS`, o la respuesta como salida con `on_error_status: complete` |
| Mayor que el límite | `RESPONSE_TOO_LARGE` |

::: app.workflows.nodes.http_request._handler.HttpRequestConfig

::: app.workflows.nodes.http_request._handler.HttpAuth

::: app.workflows.nodes.http_request._handler.HttpResponseOutput

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
en la revisión actual del registro. Una revisión que se movió es
`REVISION_CONFLICT`, que se reintenta. Un registro que falta es `found: false` de
`table.record.get`, no un fallo. `table.record.query` lee como mucho 100 registros
por página e indica `has_more`. Nunca lee por su cuenta una tabla grande entera.

`table.create` es un nodo propio y necesita `tables:create`. Su salida lleva la
tabla nueva como una referencia a la que se puede enlazar el `table` de un nodo
posterior, y el id de cada columna por etiqueta. Una tabla que lee o escribe un
workflow vivo, o una columna que fija, no se puede archivar mientras la versión
actual de ese workflow la use.

::: app.workflows.nodes._tables.TableRecordOutput

::: app.workflows.nodes.table_record_get._handler.TableRecordLookup

::: app.workflows.nodes.table_record_query._handler.TableRecordQueryConfig

::: app.workflows.nodes.table_create._handler.TableCreateConfig

::: app.workflows.nodes.table_create._handler.TableCreatedOutput

## Añadir un nodo { #adding-a-node }

Un nodo es un paquete bajo `backend/app/workflows/nodes/`: `__init__.py` registra
una `NodeDefinition`, `_handler.py` la implementa y `README.md` explica por qué
existe. `load_builtins` importa el paquete. `tests/test_workflow_node_layout.py`
hace cumplir esa estructura. Un handler devuelve `Completed`, `Waiting`, `Failed`
o `Uncertain` y nunca lanza una excepción. Lee el run para el que se ejecuta
desde `app.services.workflow_execution.context.current()`.

::: app.workflows.contracts.definition.NodeDefinition
