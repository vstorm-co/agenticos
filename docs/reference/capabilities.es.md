---
source_sha: "144975623fb4"
---

# El catálogo de capabilities { #the-capability-catalog }

Todo lo que un agent puede _hacer_ viene de uno de dos sitios: una capability
registrada en el código de este despliegue, o un [servidor MCP](../mcp.md) que
alguien conectó. Esta página es la primera lista.

Una capability es la unidad que merece la pena encender o apagar: una línea en el
Builder, una entrada en el spec. Deliberadamente no es «una herramienta»: la
búsqueda de conocimiento es una única decisión para quien configura un agent, y si
hoy expone una función y el mes que viene tres no es problema suyo. Las
capabilities cubren además cosas que no son herramientas en absoluto, y por eso
`thinking` y `clock` están aquí sin herramientas listadas.

!!! note "La API es la autoridad; esta página es una instantánea"

    `GET /api/v1/agents/capabilities` sirve el registro tal y como está en el
    despliegue en marcha, incluido todo lo añadido desde que se escribió esta
    página. El Builder dibuja su selector y sus formularios de configuración a
    partir de esa respuesta. Si ambos se contradicen, la API tiene razón.

El Builder nombra cada capability en el idioma de la consola y la explica con
palabras sencillas: qué le permite hacer al agent, dos o tres ejemplos de uso, qué
necesita y qué no hace nunca. La consola no tiene traducción al español, así que
allí se ven los nombres en inglés que da la tabla de la versión inglesa. Cinco
capabilities que solo ajustan cómo se lleva un run - conversaciones largas,
imágenes fuera del historial, recordatorio de instrucciones, límites de resultados
de herramientas y búsqueda de herramientas - quedan plegadas bajo **Advanced**
hasta que alguien abre el grupo, busca o activa una de ellas.

En los ajustes de una capability, los límites, la vida de la caché, los prompts y
el resto del ajuste fino quedan plegados en **Ajustes avanzados**, que se abren
solos donde alguno se haya establecido.

Las capabilities que tiene el agente inicial - la plantilla **AgenticOS**, que una
organización nueva recibe en su primer arranque - llevan la insignia
**Recommended**, y un agente creado con **New agent** empieza con exactamente esas
activadas, configuradas como las configura la plantilla, junto con sus
instrucciones, skills, herramientas de la plataforma y presupuesto. Su autor
desactiva lo que el agente no deba hacer.

Acabe con las capabilities que acabe, cada run recibe en sus instrucciones, bajo
**Your setup**, cuáles tiene y cuáles no - así describe solo lo que puede hacer y
dice qué habría que activar para el resto. A un agent con skills se le dice al
final, bajo **Your skills**, que abra con `read_skill` el skill en el que cae
una pregunta; pedir un skill con la tarjeta recibe eso como respuesta.

Cuando una petición necesita una que el agent no tiene, muestra en el chat una
tarjeta con ella y su motivo. Quien puede editar el agent la activa desde la
tarjeta, vinculada como la vincula el agent inicial y comprobada como comprueba
una publicación. Se publica en el acto solo si el borrador no tenía nada sin
publicar y esa persona puede publicar; si no, espera en el borrador al Builder.
Cualquier otra persona se lo pide desde la tarjeta al propietario del agent, que
recibe una notificación que abre el Toolbox del agent.

Dos de ellas dependen de lo que ejecuta el despliegue. El espacio de trabajo es un
contenedor en el servicio de sandbox del propio despliegue, que el bootstrap y la
primera publicación registran como predeterminado de la organización; sin él solo
guarda archivos. El navegador web apunta al servicio de navegador del despliegue
(`BROWSER_SIGN_IN_CDP_URL`) y se omite donde no lo hay.

## Errores de herramientas y recuperación { #tool-errors-and-recovery }

En los runs de texto, los fallos de validación, las herramientas no disponibles y
los fallos de ejecución inesperados devuelven un objeto `error` con `id`, `code`,
`tool`, `execution`, `message`, `issues` y `recovery`. Los problemas
de validación indican `field`, el código de validación `code` y `expected_type`, con
un mensaje de corrección o un ejemplo. Un ID de workflow debe ser un UUID devuelto
por la búsqueda de workflows; un array de nombres de campos se envía como
`["name", "primary_ip"]`, no como una cadena separada por comas.

`execution` vale `not_started` cuando la validación o el registro rechazan la llamada
antes de ejecutarla, `started` cuando se ha confirmado el inicio y `unknown` cuando
un error deja el resultado incierto. Un timeout posterior a la llamada no demuestra
que la acción haya fallado. Comprueba su estado antes de volver a intentarla.

| Código de error | Recuperación |
| --- | --- |
| `invalid_arguments` | `correct_arguments`: corrige el campo indicado antes de volver a intentarlo. |
| `tool_unavailable` | `rediscover_tools`: busca las herramientas y vías de invocación disponibles en este contexto. |
| `permission_denied` | `stop`: explica el rechazo. |
| `transient_failure` | `retry` si se conoce el resultado y es seguro hacer otro intento; si no, `inspect_execution_status`. |
| `execution_unknown` | `inspect_execution_status`: determina primero el resultado de la acción existente. |

La búsqueda no permite invocar directamente todos los nombres de herramientas que
devuelve. Un error de registro indica que la herramienta no está disponible en el
contexto actual de invocación; no demuestra que falten permisos del usuario. El
entorno de ejecución proporciona una vía de invocación admitida solo cuando puede
determinarla. Las instrucciones de recuperación piden al agente que siga esa vía,
corrija argumentos concretos y se ciña a la tarea: un fallo al buscar un workflow
no justifica buscar en el sistema de archivos.

El mismo error estructurado llega al modelo y al historial guardado cuando se
reanuda una llamada aprobada. Las excepciones inesperadas muestran una explicación
breve y el tipo de excepción cuando es seguro; los mensajes externos no confiables
y las trazas internas quedan en los logs del servidor. Usa el `id` del error para
encontrar la entrada detallada correspondiente.

Cuando `run_code` informa de un fallo de una herramienta anidada, `cause_tool` y
`cause_execution` identifican esa llamada e indican si comenzó. El ID del error y
los problemas de los campos se conservan al cruzar el límite del sandbox. Un
resultado externo desconocido exige comprobar las acciones anteriores antes de
volver a ejecutar el script.

Los campos obligatorios que faltan se indican por separado. Las restricciones de
valor muestran las opciones permitidas, los límites numéricos, la cantidad de
elementos o la longitud exigida. La validación de argumentos MCP utiliza el esquema
publicado sin obtener referencias externas. Las comprobaciones se ejecutan en
procesos aislados con concurrencia limitada y un plazo. Los esquemas inválidos,
irresolubles o recursivos y las comprobaciones que exceden el plazo devuelven
`tool_unavailable` antes de invocar la herramienta.

Los errores del compilador conservan un diagnóstico seguro y la posición en el
código cuando está disponible, incluido el identificador de los nombres sin
resolver. El diagnóstico omite el código fuente sin procesar, las trazas internas
y los mensajes arbitrarios de las excepciones.

La limpieza de resultados de herramientas conserva los errores estructurados
controlados, incluso si el número configurado de resultados retenidos es cero.
Los resúmenes y las ventanas deslizantes aún pueden reducir intercambios anteriores.

El agotamiento del presupuesto, los bloqueos de guardrails, las paradas de bucles y
los límites de uso del modelo siguen terminando la ejecución y conservan su
contabilidad. El modo de código mantiene esas paradas al cruzar el límite del sandbox.

## Qué se entrega { #what-ships }

| id | Nombre | Categoría | Herramientas | Scope | Clave | Voz |
| --- | --- | --- | --- | --- | --- | --- |
| `knowledge` | Búsqueda de conocimiento | knowledge | `search_documents` | `knowledge:read` | — | tal cual |
| `skills` | Skills | knowledge | `read_skill_resource` | `knowledge:read` | — | adaptada |
| `context` | Contexto | knowledge | `list_context`, `read_context` | — | — | tal cual |
| `memory_files` | Memoria | knowledge | `list_memory`, `read_memory`, `write_memory`, `edit_memory`, `delete_memory`, `remember`, `recall`, `correct_memory`, `share_memory` | — | — | tal cual |
| `conversation_search` | Conversaciones anteriores | knowledge | `search_conversations`, `read_conversation` | `conversations:read` | — | tal cual |
| `workflows` | Workflows | automation | `list_workflows`, `run_workflow`, `get_workflow_run` | `workflows:run` | — | tal cual |
| `web_research` | Búsqueda web | research | `web_search` | `web:read` | para servicios de pago | tal cual |
| `web_fetch` | Leer páginas web | research | `web_fetch` | `web:fetch` | — | tal cual |
| `browser_use` | Navegador web | research | `browse_web`, `browser_open`, `browser_new_tab`, `browser_tabs`, `browser_switch_tab`, `browser_close_tab`, `browser_read`, `browser_click`, `browser_type`, `browser_select`, `browser_scroll`, `browser_back` | `web:browse` | mediante el extra `browser` | delegada |
| `computer_use` | Computer use | research | `computer_screenshot`, `computer_act`, `computer_apps`, `computer_save_screenshot` | `computer:use` | para un daemon | delegada |
| `code_execution` | Cálculos | analysis | `run_python` | `code:execute` | — | tal cual |
| `sandbox` | Sandbox | analysis | `ls`, `read_file`, `glob`, `grep`, `write_file`, `edit_file`, `execute` | `sandbox:execute` | para Daytona | delegada |
| `mirage` | Terminal virtual | analysis | `mirage_ls`, `mirage_read_file`, `mirage_glob`, `mirage_grep`, `mirage_write_file`, `mirage_edit_file`, `mirage_execute` | — | por carpeta, con el extra `mirage` | delegada |
| `charts` | Gráficos | analysis | `create_chart` | — | — | tal cual |
| `visuals` | Visuals | analysis | `draw`, `revise_visual`, `read_visual` | — | — | tal cual |
| `image_generation` | Generación de imágenes | analysis | `generate_image` | — | obligatoria | tal cual |
| `text_to_speech` | Texto a voz | analysis | `generate_speech` | — | obligatoria | tal cual |
| `video_generation` | Generación de vídeo | analysis | `generate_video` | — | obligatoria | delegada |
| `coding_agent` | Coding agent | analysis | `run_coding_agent` | `sandbox:execute` | obligatoria | delegada |
| `harness` | Harness | analysis | `harness_start`, `harness_prompt`, `harness_stop`, `harness_sessions` | `sandbox:execute` | obligatoria | delegada |
| `monitor` | Watch a command | analysis | `start_monitor`, `list_monitors`, `stop_monitor` | `sandbox:execute` | — | delegada |
| `council` | Consejo | analysis | `run_council_review` | `agents:delegate` | — | delegada |
| `babysit_pr` | Babysit PR | analysis | `babysit_pr_check`, `babysit_pr_rate_limit`, `babysit_pr_stop` | — | — | delegada |
| `sol_loop` | Sol-loop | analysis | `run_sol_loop_review` | `agents:delegate` | — | delegada |
| `eval_tool_tuning` | Ajuste de herramientas con evals | analysis | `record_eval_tool_tuning` | — | — | tal cual |
| `burst` | Burst | analysis | `run_burst` | `agents:delegate` | — | delegada |
| `proof_scenario` | Escenario de prueba | analysis | `proof_scenario_record`, `proof_scenario_verdict` | — | — | delegada |
| `subagents` | Subagents | reasoning | `task`, `check_task`, `wait_tasks`, `list_active_tasks`, `answer_subagent`, `send_message_to_subagent`, `soft_cancel_task`, `hard_cancel_task`, `create_agent`, `delegate` | `agents:delegate` | — | delegada |
| `background_tasks` | Temas en segundo plano | reasoning | `start_background_task`, `list_background_tasks`, `stop_background_task` | — | — | delegado |
| `agent_messages` | Mensajes de agentes | reasoning | `agent_send_message`, `agent_read_messages`, `agent_list_threads`, `agent_react` | `agents:message` | — | sin cambios |
| `planning` | Planificación | reasoning | `write_plan`, `read_plan`, `add_task`, `update_task_status`, `update_task_statuses`, `remove_task`, `add_subtask`, `set_dependency`, `get_available_tasks` | — | — | tal cual |
| `thinking` | Razonamiento | reasoning | ninguna, a propósito | — | — | mapeada |
| `system_reminders` | Recordatorio de instrucciones | reasoning | ninguna, a propósito | — | — | sin efecto |
| `tool_search` | Búsqueda de herramientas | utility | ninguna, a propósito | — | — | descartada |
| `clock` | Fecha y hora | utility | ninguna, a propósito | — | — | tal cual |
| `guardrails` | Reglas de protección | utility | ninguna, a propósito | — | — | en las transcripciones |
| `compaction` | Conversaciones largas | utility | ninguna, a propósito | — | — | sin efecto |
| `media` | Imágenes fuera del historial | utility | ninguna, a propósito | — | — | sin efecto |
| `tool_output_limits` | Límites de resultados de herramientas | utility | `read_tool_result` | — | — | tal cual |
| `artifacts` | Aplicaciones | utility | `publish_artifact`, `read_artifact`, `list_artifacts`, `preview_artifact`, `share_artifact` | — | — | tal cual |
| `channel_tools` | Información del canal de chat | channels | `get_channel_info`, `list_channel_members`, `search_channels`, `read_channel_history`, `send_channel_file` | — | — | no disponible |
| `phone_calls` | [Llamadas telefónicas](../voice.md#telephone-calls) | channels | `get_phone_contact_policy`, `call_me`, `list_phone_transfer_contacts`, `transfer_phone_call`, `end_phone_call` | `endpoint_id` | — | — |
| `ask_user` | Preguntar al usuario | utility | `ask_user_question` | — | — | en pantalla |
| `secret_request` | Solicitar un secreto | utility | `request_secret` | — | — | en pantalla |
| `drafts` | Borradores | utility | `write_draft` | — | — | no disponible |
| `follow_ups` | Follow-ups | utility | `suggest_next_steps`, `propose_setup` | — | — | no disponible |

Siete de ellas no tienen herramientas a propósito. `thinking` cambia cómo trabaja
el modelo, no qué puede alcanzar, `clock` pone la fecha en las instrucciones,
`tool_search` aporta su función de búsqueda solo cuando envuelve un toolset con
herramientas diferidas — por sí sola no declara nada —, `guardrails` inspecciona y
reescribe el texto que circula por un run, `compaction` reescribe el historial que
lleva una petición, `media` reescribe cómo se _almacena_ un historial compactado, y
`system_reminders` añade texto de guía al final de la petición.

Ninguna de las siete deja nada que aprobar a una persona, así que ninguna
declara una herramienta. Una capability sin herramientas de verdad lo dice con
`tools=()` en lugar de omitir el argumento; consulta
[Añadir una capability](../howto/add-capability.md).

**Esta columna es lo que una capability declara, que no siempre es lo que se le
ofrece a un modelo.** La delegación es el único sitio donde ambas difieren:
`create_agent` y `delegate` aparecen solo bajo `allow_dynamic`, y
`answer_subagent` no aparece para nadie — las dos cosas se explican en
[Delegación](#delegation) más abajo.

**La columna Voz es lo que hace una capability en una [llamada de voz](../voice.md#what-a-call-can-use).**
_Tal cual_ funciona sin cambios. Los skills de una capability _adaptada_ se
cargan como instrucciones bajo demanda, sin su herramienta de lectura. La
búsqueda de herramientas _descartada_ da a la llamada sus herramientas MCP
directamente, porque las herramientas de una llamada quedan fijas cuando se
conecta. El razonamiento _mapeado_ se convierte en el propio ajuste de
razonamiento del modelo en tiempo real. _Delegada_ se ejecuta en el
modelo de texto propio del agent, al que la llamada pasa una tarea
([Pasar trabajo](../voice.md#handing-work-off)); la tarjeta Voice del Builder
las enumera para un agent que las tiene, igual que trabajar mientras corren
herramientas, que solo manda al fondo una herramienta delegada. _En pantalla_
hace sus preguntas en la tarjeta de la vista de la llamada en `/chat`. La
consulta del canal de chat _no está disponible_, porque una llamada nunca se
hace en un canal, y tampoco Follow-ups, cuyos botones una llamada no tiene dónde
mostrar. _Sin efecto_ marca tres que
actúan sobre las peticiones al modelo de un run de texto y sobre su historial
almacenado, que una llamada no envía.

Los guardrails revisan las transcripciones de la llamada. El resultado de una
herramienta se revisa, y se bloquea, antes de que el agent lo lea; la
comprobación antes de que una herramienta se ejecute es la aprobación, para las
herramientas que la necesitan. Los guardrails no revisan los argumentos de una
herramienta. La API del catálogo lleva cómo participa cada capability
en una llamada en el campo `voice`: `live` en el propio modelo de la llamada,
`hand_off` o `never`.

**Una de ellas no está en el Toolbox en absoluto.** `channel_tools` se elige por
bot vinculado en _Where this agent is available_, y la publicación rechaza un spec
que intente llevarla — consulta
[Consulta del canal de chat](#chat-channel-lookup).

## Qué ejecuta un eval { #what-an-eval-runs }

Un eval ejecuta el agent de verdad, así que ejecuta una herramienta solo cuando
no cambia nada fuera del run, o llega a una conexión de prueba del
[entorno](../environments.md#in-an-eval). Cada capability declara cuáles de sus
herramientas solo leen — `read_only`, junto a `side_effecting` — y una
herramienta que no declara nada escribe. Estas son las herramientas que escriben,
y que un eval retiene y registra:

| id | Herramientas que escriben |
| --- | --- |
| `artifacts` | `publish_artifact` |
| `ask_user` | `ask_user_question` |
| `browser_use` | `browse_web`, `browser_open`, `browser_read`, `browser_click`, `browser_type`, `browser_select`, `browser_scroll`, `browser_back` |
| `coding_agent` | `run_coding_agent` |
| `image_generation` | `generate_image` |
| `memory_files` | `write_memory`, `edit_memory`, `delete_memory` |
| `memory_mem0` | `remember` |
| `sandbox` | `write_file`, `edit_file`, `execute` |
| `visuals` | `draw`, `revise_visual`, `read_visual` |

Todas las demás herramientas de arriba solo leen. Delegar cuenta como leer: las
herramientas propias de un delegado se rigen por sus propias declaraciones.
`side_effecting` y `read_only` responden a preguntas distintas: la primera es
sobre qué pregunta la aprobación por defecto, la segunda qué puede ejecutar un
eval, y una herramienta sin declarar queda sin aprobación con la primera y
bloqueada con la segunda.

Un entorno puede sustituir la clave del vault de una capability por una de
prueba, pero una clave sustituida no hace segura una escritura por sí sola: la
clave de `browser_use` es para el navegador alojado o su proxy, mientras que su
`cdp_url` sigue nombrando el navegador que hace clic. Una capability declara
`test_key_isolates` solo cuando la clave por sí sola elige adónde van sus
escrituras, y nunca con una URL, un host o un endpoint en su configuración.
Ninguna capability incluida lo declara, así que en un eval cada escritura de
arriba se registra, no se ejecuta, tenga la clave que tenga.

## Búsqueda de conocimiento { #knowledge-search }

`search_documents` — _Busca en los documentos de la organización los pasajes
relevantes para una pregunta._

Busca en las colecciones que vincula el spec del agent y cita lo que ha usado. El
modelo pide _qué_ buscar, nunca _dónde_: las colecciones se resuelven desde el spec
antes del run y se entregan a la capability, así que un agent no puede alcanzar una
colección que nadie le conectó.

Cada resultado nombra su documento y dónde está la coincidencia en él. Un PDF, una
presentación o un archivo de procesador de textos como `.doc`, `.odt` o `.rtf` da la
página. Un archivo Markdown, una hoja de cálculo, una página web o una imagen no
tiene una página que un lector pueda abrir. Da solo el nombre del documento, igual
que los archivos de texto y `.docx`. Los chunks no conservan límites de sección
fiables, por lo que una línea que empieza por una almohadilla no se interpreta
como encabezado: puede ser un comentario de un bloque de código que empezó en el
chunk anterior.

Lo decide el tipo del documento al mostrar el resultado, así que una colección
ingerida antes no necesita volver a ingerirse.

| Configuración | Valor por defecto | Rango |
| --- | --- | --- |
| `default_top_k` | 5 | 1–50 |
| `self_query_enabled` | `false` | activado / desactivado |
| `query_analysis_mode` | `off` | `off`, `multi_query`, `hyde` |
| `query_analysis_max_variants` | 3 | 1–5 |
| `parent_context` | `off` | `off`, `window`, `parent` |

`default_top_k` se aplica solo cuando el modelo no pide un número por su cuenta.

`parent_context` activa la recuperación small-to-big. La coincidencia y el ranking
siempre operan sobre los fragmentos pequeños y precisos; esta opción solo decide
cuánto contexto circundante se _devuelve_ con cada coincidencia, ensamblado en la
ruta de retorno:

| Modo | Lo que recibe el modelo |
| --- | --- |
| `off` | Solo el fragmento coincidente — el valor por defecto, sin cambios |
| `window` | El fragmento coincidente con el fragmento anterior y el siguiente del mismo documento |
| `parent` | El fragmento coincidente con tanto de su documento alrededor como quepa, el texto más cercano primero |

El fragmento coincidente nunca se acorta. Solo el texto añadido a su alrededor
cuenta contra dos límites fijos - 8.000 caracteres por resultado y 24.000 por
búsqueda -, así que activar el modo nunca le muestra al modelo menos que `off`.
Un pasaje sigue siendo continuo: crece hacia fuera desde la coincidencia y se
detiene en el primer fragmento que no cabe o que ya se devolvió con un resultado
anterior, de modo que nunca se une texto que no era contiguo en el documento.

Los fragmentos se leen por su posición alrededor de la coincidencia, nunca el
documento entero, y la expansión permanece dentro del propio ámbito de inquilino y
colección de quien llama. Nunca cambia qué fragmentos coincidieron, sus
puntuaciones ni sus citas; una cita dice `with surrounding text` cuando el pasaje
va más allá del fragmento que nombra.

`self_query_enabled` activa la self-query, desactivada por defecto. Cuando una
búsqueda se ejecuta sin ningún filtro que el propio modelo haya indicado, un LLM
lee la pregunta — «PDF del mes pasado sobre onboarding» — y deriva los filtros de
negocio que implica: un origen, un tipo de documento, una unidad organizativa, un
rango de fechas. Los filtros explícitos del propio modelo siempre ganan; la
self-query solo rellena el hueco. Cuando se aplican filtros inferidos, el
resultado empieza con una línea que los nombra, y el modelo puede repetir la
búsqueda sin ellos pasando `infer_filters=false`.

El objeto inferido es el mismo filtro validado que aporta quien llama, así que no
lleva ningún campo de tenant ni de autorización y no puede ampliar el acceso:
solo puede acotar dentro del propio tenant y las colecciones del agente. Una
unidad organizativa se conserva solo si las colecciones vinculadas la contienen
de verdad, leídas en el mismo ámbito que la búsqueda; unas colecciones que suman
más de 200 unidades no ofrecen ninguna para la inferencia. Nunca se infiere un id
de documento. Una inferencia vacía o fallida busca sin filtro dentro de ese
ámbito aún aplicado.

**Coste:** cada búsqueda que el modelo ejecuta sin filtros propios hace una
petición adicional al modelo para la inferencia (dos si su salida necesita
corrección). Se ejecuta en el propio modelo del agente, se imputa a la ejecución
como cualquier otra petición y se rechaza antes de enviarse cuando el
presupuesto ya está agotado. Se traza como las propias peticiones del agente, así
que un agente configurado para no registrar contenido también deja aquí la
pregunta fuera de sus trazas.

Vinculada sin colecciones, esta capability no aporta **nada**: no se adjunta en
absoluto. Una herramienta de búsqueda que siempre devuelve vacío es peor que no
tener ninguna, porque el modelo sigue intentándolo y razona a partir del silencio.

### Análisis y expansión de la consulta { #query-analysis-and-expansion }

Las preguntas cortas, poco especificadas o con vocabulario que no coincide
recuperan de menos. Desactivado por defecto, `query_analysis_mode` expande
opcionalmente la consulta _antes_ de la recuperación:

| Modo | Qué hace | Coste |
| --- | --- | --- |
| `off` | Busca la consulta tal como está escrita | ninguno |
| `multi_query` | El modelo del run escribe hasta `query_analysis_max_variants` reformulaciones; el original y las variantes se buscan por separado y sus resultados se fusionan | una llamada al modelo, más una recuperación por consulta |
| `hyde` | El modelo del run escribe una breve respuesta hipotética, y la recuperación se ejecuta contra _su_ embedding | una llamada al modelo |

`multi_query` y `hyde` añaden cada uno una llamada al modelo antes de la
búsqueda, así que cambian latencia y un poco de gasto por recuperación en
preguntas difusas. `multi_query` además recupera una vez por consulta, una tras
otra, y cada recuperación genera el embedding de su propia consulta —las
variantes no se agrupan en una sola llamada de embedding—, así que mantén
`query_analysis_max_variants` bajo para acotar la ramificación.

Ambos modos usan el propio modelo del agente —no hay un modelo aparte que
configurar— y su coste se mide contra el presupuesto del run como cualquier otra
llamada al modelo. Un presupuesto agotado omite la expansión sin llamar al
modelo, y lo mismo ocurre con un modelo que falla o no puede responder a una
petición simple: la búsqueda se ejecuta entonces con la consulta tal como está
escrita en lugar de fallar.

La expansión amplía la _recuperación_, nunca el _acceso_. Cada consulta que
produce se busca bajo el mismo ámbito de inquilino y los mismos filtros de negocio
que el original, así que una consulta expandida nunca puede alcanzar un documento
de otra organización o fuera de ámbito. Se combina con el reordenamiento: la
expansión amplía el conjunto de candidatos y los resultados se fusionan, y un
reranker reordenaría lo que devolvió la fusión. Con `parent_context` activado, el
texto circundante se añade una sola vez, a los resultados fusionados, así que sus
límites cubren toda la búsqueda y no cada consulta por separado.

## Skills { #skills }

`read_skill_resource`

Conocimiento escrito que el agent carga solo cuando decide que es relevante, un
skill cada vez — la alternativa sería un campo de instrucciones que crece hasta que
cada run paga por cada procedimiento. Consulta [Skills](../skills.md) para saber
qué es un skill y cómo llega a una organización.

**Cada skill vinculado sigue siendo una capability diferida nativa.** El modelo
ve un catálogo de skills disponibles y abre el contenido con `read_skill`. El
adaptador de la plataforma conserva el estado de carga nativo, las aprobaciones
y la reproducción de conversaciones, incluidas las antiguas. Las políticas de
aprobación mantienen la clave estable `load_capability`; los overrides habituales
no renombran este cargador del framework. `read_skill_resource` lee archivos
auxiliares y aparece solo si un skill vinculado incluye alguno. Un test de deriva
compara la herramienta de archivos de la biblioteca con el registro.

`run_skill_script` está apagada en lugar de expuesta: los archivos de un skill
llegan a un run bajo `/workspace/skills/`, donde los ejecuta el propio `execute`
del [sandbox](../sandbox.md) bajo los topes del operador, y una segunda vía de
ejecución sería un segundo juego de reglas que equivocar.

## Contexto { #context }

`list_context`, `read_context`

El contexto permanente de una organización, puesto en el run en lugar de pedirlo:
un glosario, un tono de marca, una matriz de escalado. Cada archivo vinculado
lleva un `mode`: un archivo `inject` se inserta literalmente en las instrucciones,
y el modelo simplemente lo conoce; un archivo `link` queda fuera del prompt y se
alcanza con `read_context`, así que un archivo grande o que casi nunca hace falta
no cuesta nada hasta que el modelo decide que es relevante. `list_context` informa
de lo que hay disponible sin los cuerpos. Las dos herramientas aparecen solo con
un archivo `link` vinculado; un agent cuyos archivos son todos `inject` aporta
instrucciones y ninguna herramienta.

El contenido inyectado se enmarca como material de referencia: delimitado y
precedido de una línea que le dice al modelo que lo trate como información y no
como instrucciones, porque el cuerpo lo escribe una persona y llega literalmente
al modelo. La delimitación es un mejor esfuerzo contra la fuga _accidental_: un
cuerpo que contenga una etiqueta de cierre `</context-file>` o `</context-files>`,
o un nombre o formato con una `"`, se neutraliza para que no derrame texto en las
instrucciones de confianza. No es una frontera de seguridad: quien tenga
`context:edit` sigue pudiendo inyectar a propósito. El contenido es texto: un
documento que haya que buscar va en una colección de conocimiento, no aquí.

Vinculada sin nada aprovechable — ningún archivo, o solo archivos `link` con la
herramienta de lectura apagada —, esta capability no aporta **nada** y no se
adjunta, igual que `knowledge` vinculada sin colecciones tampoco se adjunta. Los
archivos se gestionan bajo `/api/v1/context` y se vinculan a un agent por id
(`AgentSpec.context_ids`).

## Memoria { #memory-files }

`list_memory`, `read_memory`, `write_memory`, `edit_memory`, `delete_memory`

Notas que un agent guarda por su cuenta entre conversaciones, indexadas por otra
que él mismo mantiene. Donde `context` es una biblioteca que una persona escribe y
vincula a muchos agents, la memoria es del propio agent: escribe con herramientas
en mitad del run, y aquí no escribe nadie más. No se vincula por id: activar la
capability le da al agent sus notas.

**`MEMORY.md` es el índice, y se le muestra al agent en cada petición.** Es una
nota corriente que el agent escribe y edita con las mismas herramientas que
cualquier otra, y la capability la inserta en las instrucciones igual que se
inserta un archivo de contexto vinculado. Así el agent se encuentra con lo que ha
guardado antes de decidir nada, y abre una nota listada con `read_memory` cuando
la línea dice que merece la pena leerla, en vez de tener que decidirse a llamar a
una herramienta de listado que un modelo más ligero rara vez llama.

### De quién son las notas, y quién puede oírlas { #whose-notes-and-who-may-hear-them }

Una nota pertenece a una sola persona o a un solo chat de grupo, y **un run toca
exactamente un almacén: el de la propia conversación.** Cuál es se deriva en el
servidor a partir de quién va a oír la respuesta, nunca del modelo, así que ninguna
herramienta recibe un ámbito y no hay nada que el agent pueda confundir.

- Uno a uno (chat web, un mensaje directo): las notas son de esa persona y nadie
  más las lee jamás. La misma persona alcanza un único almacén desde ambas vías: una cuenta de chat vinculada se resuelve a su cuenta y no a
  la superficie por la que llegó.
- En un chat de grupo las notas son del chat, y todos los del chat las leen. Las
  notas propias de quien habla **no** son alcanzables ahí: algo anotado a solas
  con alguien no se lee en voz alta donde lo ve un canal entero.
- En un widget público o en un embed no hay a quién atribuir nada, así que no hay
  almacén, y las herramientas lo dicen en vez de guardar en algún sitio. Un run
  iniciado con una [clave API](../api.md#organization-api-keys) tampoco lo tiene:
  la clave actúa por quien la emitió, pero quien la tiene no es esa persona.
- En un chat que leen otras personas, el de un proyecto o uno compartido con
  alguien para editar, no hay almacén personal. El agent no muestra, no recupera
  ni guarda allí lo que sabe de la persona; sigue leyendo los claims del
  proyecto y de la organización. Compartir un chat para editar, o moverlo a un
  proyecto, muestra su historial, incluidas las respuestas escritas mientras era
  privado; desde ese momento, las respuestas siguientes no usan memoria
  personal. Un chat compartido solo para ver muestra todas las respuestas,
  también las posteriores escritas con memoria personal.
- En una programación o en un trigger de evento tampoco hay almacén, aunque el
  run se ejecuta como el creador del trigger. El creador presta al run su
  autoridad, no su identidad, así que nadie escucha y las herramientas se
  niegan. Pon un dato que necesite un run programado en el prompt del trigger o
  en un archivo de contexto vinculado. Consulta
  [Trigger](../concepts.md#it-is-not-that-persons-conversation), o deja que el trigger
  [se ejecute como su creador](../concepts.md#unless-its-creator-lets-it-run-as-them):
  un horario lee y escribe entonces el almacén del creador, y un evento solo lo lee.

No hay un almacén para toda la organización. Existió uno y se retiró: era un
segundo mecanismo para lo que ya hacen los [archivos de contexto](../context.md)
— conocimiento permanente que una persona escribe y vincula a agents — y un solo
trabajo con dos mecanismos es la forma en que los dos acaban contradiciéndose. La
memoria es lo que aprendió el _agent_; lo que escribe una persona va en el
contexto.

Un interruptor, **Allow personal memory**, elimina por completo el almacén por
persona, por motivos de cumplimiento o de privacidad; las notas guardadas en chats
de grupo se quedan.

### Hechos, preferencias y decisiones { #memory-claims }

Además de notas, un agent puede registrar **claims**: un hecho, preferencia o
decisión duradero en una frase sencilla, con su procedencia (#2090). Las notas no
cambian; un claim hace que una frase se pueda comprobar: su fuente, desde cuándo
vale y qué sustituyó. Cuatro herramientas: `remember`, `recall`, `correct_memory`
y `share_memory`.

Dónde vive un claim es una regla de acceso, nunca una etiqueta que elija el
modelo:

| Scope | De quién | Quién lo lee |
| --- | --- | --- |
| Perfil de la persona | Una persona de esta organización; puede usarlo cualquier agent que actúe por ella | Esa persona, a solas con cualquier agent |
| Persona y agent | La relación de un agent con una persona: detalle del caso, el valor por defecto | Esa persona, con ese agent |
| Chat de grupo | Un chat | Solo ese chat |
| Proyecto | Un proyecto | Las conversaciones de ese proyecto |
| Organización | Todos aquí | Las conversaciones privadas de esta organización |

Una escritura automática se queda en el scope de la conversación de la que vino, y
un chat de grupo nunca escribe un perfil. Solo `share_memory` amplía un claim, y
solo por orden de una persona que pueda: `projects:edit` en el proyecto, o
`context:edit` para toda la organización. Siempre espera a que una persona apruebe exactamente ese claim y esa audiencia, sean cuales sean los ajustes de aprobación del agent, así que un texto leído por el agent no puede convencerlo de compartir.

Tampoco lo responden **Approve everything** ni un **Permitir siempre** recordado, y su tarjeta no ofrece ninguna de las dos opciones. La tarjeta muestra el hecho y su audiencia; en la cola de aprobaciones el hecho solo lo ve quien puede ver el run del que viene.

La copia nombra el claim del que viene y
el original conserva su audiencia. Un embed, un run con clave de API y un run
programado no leen nada; un chat de grupo lee solo sus propios claims. Corregir un claim que lee todo el proyecto o la organización exige el mismo permiso que compartir hacia allí: leerlo no es autoridad para reescribirlo.

Una corrección así mediante `correct_memory` además espera a una persona cada vez, sea cual sea el modo de aprobación, y su tarjeta muestra el hecho antes y después; corregir un claim propio de una persona no espera. Una corrección que registra la herramienta es un claim del agent, nombra el run y la conversación de los que viene, y el registro de auditoría recibe una entrada `memory.claim.corrected`. Una corrección hecha en **Settings → Memory** es de la propia persona.

- **Una corrección conserva lo que corrige.** «Desde el lunes Piotr se encarga de
  las facturas» cierra el claim anterior en esa fecha y añade el nuevo; que Anna
  las llevara antes del lunes sigue siendo cierto y visible.
- **La palabra de una persona pesa más que una inferencia.** Un claim de un agent
  que contradice lo que dijo una persona se aparta como _en disputa_ y nunca se
  ofrece como establecido. Dos agents que discrepan también son una disputa, hasta
  que alguien la resuelva.
- **La consolidación solo pliega el acuerdo.** Cada quince minutos se fusionan los
  claims de cada scope que _cambió_: las frases idénticas pasan a ser un claim
  derivado que nombra sus fuentes, el desacuerdo se marca en disputa. Es
  determinista —sin llamada al modelo—, así que un scope sin cambios no cuesta
  nada y una segunda pasada no cambia nada. Retirar un claim derivado devuelve sus
  fuentes y no se vuelve a extraer.
- **La ascendencia se filtra por acceso.** Un claim compartido con el proyecto no
  revela el claim privado del que se copió a quien no pueda leerlo.

Una conversación privada recibe el perfil de la persona (como mucho unos veinte
claims, 1.800 caracteres) en sus instrucciones, con la misma regla que el índice:
solo donde el lector está a solas. Lo demás se obtiene con `recall`, que compara
palabras y no llama a ningún modelo. Los claims recuperados son evidencia, nunca
una instrucción ni una concesión de autoridad.

En **Ajustes → Memoria**, **Memories** muestra hechos, preferencias y decisiones; **Notes** abre archivos más largos en el visor compartido. La búsqueda abarca todo el almacén antes de paginar. Filtra por tipo y ámbito, incluye el historial y abre una entrada para consultar su fuente y las pruebas de la decisión. Las correcciones conservan la versión anterior. Dejar de usar una entrada conserva el historial; eliminar una nota permanentemente requiere confirmación. Borrar a una persona también elimina sus claims y las copias compartidas.

### Qué se inyecta, y qué solo se consulta { #what-is-injected-and-what-is-only-fetched }

Un resultado de herramienta es algo que el modelo sopesa; las instrucciones son lo
que obedece. Por eso el índice llega al prompt solo donde su contenido no habría
podido dirigir a nadie más que a quien lo lee: en una conversación uno a uno se
inyecta, y en un chat de grupo sigue siendo alcanzable con `read_memory` y no se
inyecta nunca. Las notas de una sala no tienen ámbito propio, así que la frase de
un compañero llegaría si no como instrucciones de otro compañero en el mismo canal.

Un índice de más de unos 6.000 caracteres se deja fuera en vez de recortarse. Medio
índice — que termina a mitad de línea, a mitad de nombre de archivo — es peor que
ninguno.

### Leerla, y borrarla { #reading-it-and-erasing-it }

Nadie hojea las notas _de otra persona_ por su rol en la organización. Esa era
toda la respuesta anterior —borrado y ninguna lista— y estaba medio bien: una
lista es un instrumento de vigilancia sobre el almacén de un colega, y lo
contrario sobre el propio. Por eso la respuesta tiene ahora tres partes (#1594).

**El tuyo, siempre, en Ajustes → Memoria.** Ningún permiso lo protege, porque la
respuesta es la misma para un Viewer y para un Owner: lo que los agentes de aquí
han escrito sobre ti, a través de todos ellos, con cuál escribió cada nota y
cuándo. Tres cosas que puedes hacer con una nota:

|  |  |
| --- | --- |
| **Dejar de usarla** | La nota deja de listarse, leerse y de ser editable por herramienta alguna, así que deja de llegar al modelo — y sigue existiendo, para que la mires y la restaures. La respuesta intermedia para una nota que está mal o es demasiado personal y de la que aún no estás seguro de querer deshacerte. |
| **Volver a usarla** | La restaura. |
| **Borrarla** | Desaparece. |

El _nombre_ de una nota suspendida sigue ocupado, así que un agente que lo
escriba otra vez revive la fila con contenido nuevo. Eso no deshace la
suspensión: lo que suspendiste queda sobrescrito, y la fila guarda algo que el
agente ha aprendido desde entonces. La alternativa —un nombre permanentemente
inservible— es un almacén que se niega a funcionar y nunca dice por qué.

**El índice va detrás.** `MEMORY.md` se inserta en las instrucciones de cada
petición, así que una nota que detuviste cuya línea del índice sigue
describiéndola es una nota que sigue llegando al modelo. Suspender o borrar una
nota elimina, por tanto, las líneas del índice que la **nombran**. Una línea que
la describe sin nombrarla sobrevive —el recorte es por líneas y se apoya en el
nombre, que es lo que el índice es— y restaurar una nota no vuelve a poner la
línea: el índice lo escribe el agente, y este no es el sitio para redactar en su
voz.

**El de otra persona, solo una administradora del despliegue.**
`GET /memory/person/{id}`, nombrando el tenant, y rechazado a todos los demás: ni
a un Owner, ni a un Admin, ni a quien tenga un grant de edición sobre el agente
que escribió la nota. El razonamiento es el de arriba: un rol de organización no
es la parte a la que llega una solicitud de acceso del interesado, y la
administradora del propio despliegue, que ya administra cuentas entre tenants,
sí lo es. La lectura queda en el rastro de auditoría con el actor, el tenant, el
sujeto y un motivo, y **sin contenido**: una entrada que guardara lo que miró
sería una segunda copia de lo que se protege.

**El borrado**, sin cambios. Una persona limpia desde su propio perfil todo lo
que un agente recuerda sobre ella, y una administradora con `members:manage`
puede hacerlo por otra; ambos borran las notas de aquí y los claims registrados, con las copias compartidas a partir de ellos.

## Temas en segundo plano { #background-tasks }

Trabajo explícito en un tema nuevo que dura más que la respuesta de origen. El agente original resume el resultado con el historial actual, sin herramientas. [Temas en segundo plano](../console.es.md#background-topics) explica límites, aprobaciones, detención e interrupciones. Es independiente de `background_tools` y los subagentes asíncronos temporales de una ejecución.

## Mensajes de agentes { #agent-messages }

Mensajes directos entre dos agents, en un hilo que muestra la consola. Hay un
hilo por pareja de agents dentro de una organización; el mensaje se guarda,
nunca se entrega como un run. Enviar requiere `agents:run` sobre ambos agents;
leer, sobre al menos uno, y ambos deben estar publicados. Consulta [Mensajes de
agentes](../agent-messages.md) para respuestas, reacciones, archivos y límites.
Es la forma abierta de delegación: una delegación oculta el intercambio dentro
del padre, mientras que cualquiera que pueda ejecutar uno de los agents puede
leer el hilo.

## Conversaciones anteriores { #conversation-search }

`search_conversations`, `read_conversation`

Encuentra una conversación pasada por lo que se **dijo** en ella, y la abre
entera. La memoria solo puede recordar lo que algún turno anterior consideró digno
de anotar; todo lo demás se dijo, se guardó y, hasta que esto existió, era
inalcanzable — de modo que «qué decidimos sobre los precios del Q3» se respondía
con «no tengo constancia de eso» en un producto que guardaba el intercambio entero.

`search_conversations` devuelve los hilos que mejor encajan, cada uno con su
título, cuándo estuvo activo por última vez, cuántos turnos coincidieron y el
pasaje más fuerte con las palabras coincidentes en negrita. `read_conversation`
abre uno como Markdown, dividido en `USER:` y `AI:` en el orden en que se
escribieron los turnos, nombrando a quien habló cuando una sala tiene varias
personas. Un hilo largo llega de ventana en ventana y la respuesta dice cómo pedir
la siguiente.

### De quién son las conversaciones { #whose-conversations }

Las de una sola persona: aquella a la que el run está respondiendo. Tres vías de
entrada, las mismas tres que permite la consola: las conversaciones de su
propiedad, las compartidas con ella y los hilos de canal en los que participó _y
de los que sigue siendo miembro_, confirmado contra la plataforma de chat. El
registro de runs de un trigger queda deliberadamente fuera: es la transcripción de
runs hechos bajo la autoridad de otra persona, y un agent que busca en nombre de
alguien no tiene ningún permiso suyo con el que comprobarlo.

**Y solo donde esa persona es la única que escucha.** En un chat de grupo ambas
herramientas se niegan, diciendo por qué: el corpus es personal, así que responder
a partir de él en un canal leería las conversaciones privadas de una persona ante
todos los de la sala. Es la línea que traza el índice de memoria, una capa más
afuera.

Una programación o un trigger de evento no responde a nadie, así que ambas
herramientas se niegan también ahí, por la misma razón que los
[archivos de memoria](#whose-notes-and-who-may-hear-them) - y siguen negándose en un
trigger que [se ejecuta como su
creador](../concepts.md#unless-its-creator-lets-it-run-as-them), que abre la memoria
y las conexiones personales, pero nunca las conversaciones de una persona.

### Cómo busca { #how-it-matches }

Búsqueda de texto completo de PostgreSQL: un `tsvector` que la base de datos
mantiene sobre cada mensaje, un índice GIN, `websearch_to_tsquery` para la consulta
y `ts_rank_cd` para el orden. Funcionan las `"frases exactas"` entre comillas, `or`
y un `-` inicial para excluir una palabra. No `ILIKE`, que coincide dentro de las
palabras y no sabe ordenar; ni embeddings, que es lo que ya es la
[búsqueda de conocimiento](#knowledge-search) y responde a otra pregunta.

Las palabras coinciden enteras y sin distinguir mayúsculas, pero **sin lematizar**:
`meeting` no encuentra `meetings`. La configuración está fijada en la base de datos
y `english` lematizaría un idioma mientras destroza todos los demás — PostgreSQL no
trae diccionario polaco alguno —, así que la uniformidad entre idiomas se paga con
las formas de las palabras. La descripción de la herramienta lo indica, para que un
modelo que no encuentre nada pruebe otra forma de la palabra en vez de concluir que
no se dijo nada.

Un operador que no quiera en absoluto que los agents lean conversaciones retira el
scope `conversations:read`, lo que lo apaga en todo el despliegue. No hay ningún
ajuste que amplíe el corpus.

## Búsqueda web { #web-search }

`web_search` — _Busca información actual en la web pública._

| Configuración | Valor por defecto | Valores |
| --- | --- | --- |
| `method` | `duckduckgo` | `duckduckgo`, `native`, `tavily`, `brave`, `exa`, `keenable` |
| `max_results` | 5 | 1–10, ignorado por `native` |

La consola nombra cada método en lugar de imprimir el valor que almacena, y dibuja
la marca del propio servicio al lado: el campo lleva `x-enum-labels`, que es lo que
el formulario generado lee como etiqueta. Sin ellas el selector ofrecía
`duckduckgo` y `exa` con las mayúsculas con las que se almacenan, lo que se lee
como una clave de configuración que reconocer y no como un producto que elegir.

- **`duckduckgo`** — gratis, sin cuenta, resultados presentados como fuentes
  pulsables.
- **`native`** — el provider del modelo busca con su propio índice y devuelve sus
  propias citas. Solo en modelos que lo admiten.
- **`tavily`** — resultados resumidos para que los lea un modelo.
- **`brave`** — un índice propio.
- **`exa`** — búsqueda por significado en vez de por palabra clave.
- **`keenable`** — sin cuenta; una clave de API opcional de los secretos de la organización activa el endpoint con clave.

Los tres métodos de pago necesitan una clave de API de los
[secretos](../secrets.md) de la organización, nombrada por el `secret_id` de la
vinculación. El requisito es condicional y no fijo: uno fijo, o bien encerraría el
método gratuito por defecto tras una cuenta, o bien dejaría que un agent con Tavily
se publicara sin nada con lo que autenticarse y fallara en su primera búsqueda.

La aprobación y `native` no combinan, por la razón que da
[Lectura de páginas web](#web-fetch) más abajo: la puerta de
[aprobación](../governance.md) envuelve la _ejecución de la herramienta_, y una
búsqueda nativa la ejecuta el provider del modelo, así que una vinculación que
exige aprobación para `web_search` y pone `method` en `native` se rechaza al
publicar, en lugar de recibir una puerta que nunca se dispara. Elige un método que
ejecute este propio despliegue, o retira el requisito de aprobación.

Una búsqueda encuentra una página; no la lee. Leerla es
[Lectura de páginas web](#web-fetch), más abajo, y es una capability aparte con un
scope aparte.

## Leer páginas web { #web-fetch }

`web_fetch` — _Lee la página completa de una URL, como Markdown._

| Configuración | Valor por defecto | Valores |
| --- | --- | --- |
| `method` | `local` | `local`, `native`, `auto` |
| `max_content_chars` | 50000 | 1000–200000, ignorado por `native` |
| `allowed_domains` | — | nombres de host desnudos que el agent puede leer; null significa cualquiera |
| `blocked_domains` | — | nombres de host desnudos que nunca puede leer |

- **`local`** — este despliegue descarga la página. Es el valor por defecto, porque
  es el único método que se comporta igual en todos los modelos.
- **`native`** — la descarga el provider del modelo, con su propia salida de red y
  sus propias citas. Solo en modelos que lo admiten; Pydantic AI lanza un error en
  el resto.
- **`auto`** — nativo donde el modelo lo tiene, `local` en todo lo demás. Solo se
  ofrece uno de los dos, así que un run no puede elegir entre ellos por llamada.

La descarga en sí es el `web_fetch_tool` de Pydantic AI sobre su `safe_download`
protegido contra SSRF, y esa es la razón de que no sea código nuestro.

En qué se convierte una respuesta se decide aquí:

- Una página (HTML, Markdown, JSON, texto plano) vuelve como Markdown.
- Una imagen vuelve como imagen, para un modelo que lee imágenes.
- Un PDF o un documento de oficina vuelve como su **texto extraído**, leído por el mismo
  parser por el que pasa un adjunto del chat y recortado en `max_content_chars` como una
  página. La biblioteca devolvería los bytes en bruto para que el modelo los leyera de
  forma nativa. Un modelo servido tras un endpoint compatible con OpenAI que no puede
  hacerlo rechaza la petición entera (`Unsupported chat content part type: 'file'`), y
  el agent vuelve a descargar el mismo documento. Solo se extrae el texto hasta
  `max_content_chars`, y un PDF se lee como máximo hasta 2.000 páginas: uno más largo
  termina con una nota que nombra la página en la que se detuvo, y cuando las páginas
  leídas no tenían texto, solo vuelve esa nota.
- Un binario sin texto legible (un PDF escaneado, un archivo comprimido) llega al modelo
  como un error reintentable que nombra lo que llegó.

La URL viene del **modelo** y se resuelve desde dentro del contenedor, así que
validarla de antemano — como hace `app.core.sanitize.validate_webhook_url` con un
callback que alguien nos entregó — no basta por sí solo. `httpx` resuelve el nombre
de host una segunda vez y sigue las redirecciones sin volver a preguntar, así que
un nombre que hace un momento respondía públicamente puede responder ahora
`169.254.169.254`, y una URL pública puede redirigir a una de esas.

`safe_download` fija en la petición la dirección que resolvió y revalida cada salto,
incluidos los filtros de dominio. Además acota el cuerpo mientras se transmite, y
rechaza las codificaciones de compresión que no pueden acotarse así.

Las direcciones privadas, de bucle local, de enlace local y de metadatos de nube se
rechazan, y el rechazo llega al modelo como un error reintentable y no como una
página vacía: un rechazo con forma de resultado es uno que el modelo esquiva al
responder sin decir que tuvo que hacerlo. A la biblioteca se le puede indicar que
permita direcciones locales; aquí nada expone eso.

Cualquiera de los dos fallos, como cualquier otro (un 403, un tiempo de espera
agotado), es un reintento solo mientras a la herramienta le quede un intento.
Pydantic AI cuenta los reintentos por herramienta y no por URL, así que el segundo
sitio que rechazara al agente terminaría todo el run; en el último intento el
mismo mensaje vuelve en su lugar como resultado de la herramienta, y el modelo
pasa a otra fuente o responde sin ella.

!!! warning "Los filtros de dominio no son la frontera de seguridad — `safe_download` sí"

    Coinciden con el nombre de host exactamente, sin comodines y sin subdominios
    implícitos, así que responden a *qué sitios puede leer este agent* y no a *puede
    este agent alcanzar nuestra red*.

Una entrada que nunca podría coincidir se rechaza al publicar: un comodín, un
esquema, una ruta, un puerto o una **lista de permitidos** vacía. Cada una dejaría
si no una lista de denegados que calladamente no deniega, o una lista de permitidos
que calladamente lo deniega todo.

Una _lista de denegados_ vacía no deniega nada, que es lo que ya significa dejarla
sin poner, así que se lee como no puesta en vez de rechazarse: un spec importado
que escribe «ningún host denegado» como `[]` está diciendo algo cierto.

Una entrada que _sí_ puede coincidir se almacena con la única grafía por la que se
preguntaría al DNS: en minúsculas, sin la etiqueta raíz final y codificada en IDNA.
Un nombre tiene más de una grafía, y una coincidencia exacta contra una sola de
ellas es un filtro con un agujero: `https://exämple.com/` llega a la comparación tal
y como se escribió, así que una lista de denegados con solo `xn--exmple-cua.com` lo
dejaría pasar mientras `getaddrinfo` resuelve las dos igual. Al filtro se le
entregan en tiempo de construcción todas las grafías equivalentes; el spec almacena
una.

!!! warning "La aprobación y `native` no combinan"

    La puerta de [aprobación](../governance.md) envuelve la *ejecución de la
    herramienta*, que es el único sitio donde una llamada puede retenerse, así que
    una descarga que el provider del modelo ejecuta por su lado no llega nunca a
    ella.

Una vinculación que exige aprobación para `web_fetch` y pone `method` en `native`
— o en `auto`, donde cuál de los dos se ejecuta es una propiedad del perfil del
modelo y cambia sin republicar — se **rechaza al publicar**, en lugar de recibir
una puerta que calladamente no se dispara nunca.

Pon `method` en `local`, o retira el requisito de aprobación. Los dos son agents
legítimos, y cuál se quiere no es una decisión que tomar en nombre del autor.

Una versión publicada antes de que existiera ese rechazo se rechaza de nuevo cuando
se ensambla, porque nada revalida una versión congelada. Así que un agent así deja
de funcionar hasta que se edite, en vez de seguir descargando sin aprobación.

Una página llega como Markdown, truncada en `max_content_chars`; un PDF o una
imagen llegan como contenido binario que el modelo lee de forma nativa. Nada la
resume: qué hacer con una página corresponde a las instrucciones del agent.

## Navegador web { #browser-automation }

`browse_web` — _Hace una tarea en un navegador web real, paso a paso._

Una tarea y una URL de inicio. Abre la página en un Chromium que usted opera y repite
tres cosas: lee la página en una tabla numerada de los elementos sobre los que una
persona podría actuar, pide al modelo del run un paso y lo ejecuta. Un paso juzga si la
acción anterior funcionó, guarda una memoria breve para el resto de la tarea, dice para
qué es la siguiente acción y nombra una sola acción: hacer clic, escribir, elegir,
desplazarse, abrir una URL, volver, esperar, terminar con una respuesta, pedir a una
persona o avisar de que la página lo bloquea.

Úselo cuando una página haya que _manejarla_ — un formulario, un filtro, un inicio de
sesión con datos que tiene, una búsqueda cuyos resultados piden un clic, un recorrido
por varias páginas. Para una página que solo hay que leer, la
[descarga de páginas](#web-fetch) es más rápida y no tiene efectos secundarios.

**O el agent lo maneja él mismo.** `browser_open`, `browser_read`, `browser_click`,
`browser_type`, `browser_select`, `browser_scroll` y `browser_back` son la misma pestaña
en manos del propio agent: una acción por llamada, elegida por el modelo del run en su
propio turno, y cada una responde con la página después de la acción - su dirección, los
elementos numerados y su texto. Sin una segunda petición por paso, y el agent dice en el
chat lo que hace entre acciones. El navegador se abre automáticamente en un panel lateral a toda altura junto al chat. Una persona puede tomar el control entre acciones. Medido con Claude a través de OpenRouter: un paso de
`browse_web` dura 3,5-5 s, casi todo la petición al modelo del propio paso; una tarea de
dos clics que el agent manejó él mismo tardó 13 s, y con `browse_web` unos 20. Las
herramientas convienen para una tarea corta o una que alguien quiere ver, `browse_web`
para una tarea larga entregada entera.

Antes de cada petición al modelo, los resultados anteriores de herramientas directas
pierden solo sus tablas obsoletas de elementos numerados. Se conservan la tabla más
reciente, el texto de los artículos y los resultados de acciones; la conversación
guardada mantiene los resultados completos. La navegación DOM usa la vista previa
independiente y captura una imagen final tras detenerla. Vision sigue esperando la
imagen para el modelo. La disponibilidad depende del contenido visible y no de cambios
ajenos en segundo plano; un documento vacío recibe un reintento acotado de lectura.

**Varias pestañas y reanudación.** `browser_new_tab(url)` abre una página aparte,
`browser_tabs` lista identificadores, `browser_switch_tab(tab_id)` selecciona y lee una
página y `browser_close_tab(tab_id)` la cierra. Hay hasta ocho pestañas por ejecución.
`browser_open` navega en la pestaña seleccionada. En conversaciones privadas,
`browser_read` restaura durante una hora un estado cifrado: URL, cookies y local storage.
Las páginas remotas se cierran al terminar. Reanudar carga páginas y números de elementos
nuevos; no conserva formularios sin guardar, memoria JavaScript ni historial. Los navegadores
alojados no reciben estos estados. Las tarjetas con iconos aparecen primero en la
configuración; los usuarios de escritorio pueden cambiar la conexión por conversación.

**Una acción nombra una fila, nunca un selector.** Cada elemento sobre el que el modelo
puede actuar es una fila de una tabla construida en el servidor a partir del DOM vivo,
así que una página no puede ofrecer una acción describiéndola. Eso no es lo mismo que
seguro: «Eliminar cuenta» es una acción que una página ofrece de verdad, por eso la
capability es **`side_effecting`** y `browse_web` puede quedar tras una
[aprobación](../governance.md).

**Por defecto no espera aprobación**, como toda herramienta. Una aprobación de una navegación llega antes
de cargar la primera página, sobre una tarea en lenguaje natural, y pide consentir
acciones que nadie puede ver todavía. En su lugar está la observación: la consola dibuja
la navegación mientras ocurre, cada paso dice qué pulsó y para qué, y `allowed_domains`
limita adónde puede ir. Quien quiera la puerta pone `tool_approval` en el binding.

**Un límite de pasos es una pausa, no un final.** La pestaña sigue abierta el resto del
turno. Una navegación que llega a `max_steps` lo dice junto con lo que aprendió, y el
agente continúa llamando de nuevo a `browse_web` sin `start_url` — en la misma página,
con la sesión iniciada y la misma memoria. Una llamada con `start_url` empieza una tarea
nueva en la misma pestaña. Cuatro resultados, todos normales: terminada, bloqueada por la
página, en pausa en el límite de pasos y el navegador no responde. El último es una
respuesta, no un run fallido: el agente sabe que el navegador no responde y lo dice,
junto con quién puede arreglarlo.

**Una persona puede tomar el control del navegador.** Cada navegación de un run tiene
una vista en directo en la consola, en `/browse/{run_id}/{call_id}`: la página tal como
está ahora y los pasos hasta el momento. La tarjeta del chat enlaza a ella, y en Slack,
Telegram y Mattermost el paso publica el enlace. La persona para la que actúa el run, o
quien puede editar el agente, puede tomar el control: el agente se detiene tras su paso
actual y la página es suya — clic, escribir, desplazarse — hasta que la devuelva, y el
agente sigue desde la página tal como la dejó. Los miembros que pueden ver runs pueden
mirar, pero no manejar. Lo que alguien escribe llega a la página y no se guarda en
ningún sitio; el historial del run solo registra que alguien tomó el control.

**La página toma el tamaño de la ventana que la muestra.** Mientras alguien que puede
manejar la navegación la tiene abierta, el navegador maqueta la página para esa ventana
entre pasos - el diseño propio del sitio para ese ancho, con la densidad de esa
pantalla -, así que la vista en directo es el sitio y no una pantalla de portátil
encogida en una columna. El modelo ve entonces la misma página a ese tamaño.

**Una tarea ya hecha va más rápido la segunda vez, para la misma persona.** Cuando
termina una navegación que actúa por una persona - su propio chat, su mensaje directo,
su propia programación - los pasos que la llevaron allí se guardan solo para ella: la
dirección y la etiqueta de cada cosa que pulsó, nunca lo que escribió (la grabación se
detiene en el primer campo que rellena). La próxima vez que pida la misma tarea desde
el mismo `start_url`, esos pasos se dan sin el modelo mientras la página los siga
ofreciendo, y el modelo toma el relevo en la primera diferencia. Una repetición que no
termina se descarta. Nadie más en la organización los lee, y Redis los guarda dos
semanas desde la última vez que se hizo la tarea.

**Cuando solo una persona puede pasar de una página** — un inicio de sesión sin datos,
un captcha, una decisión que le corresponde a otro —, el modelo pide una persona en
lugar de rendirse. La tarjeta y el hilo del canal dicen que el agente necesita a una
persona, y para qué. La
navegación espera hasta diez minutos a que alguien tome el control y termina bloqueada
si nadie llega; una persona tiene el navegador como mucho quince minutos. La vista en
directo se guarda en Redis, así que lo necesita, y dura una hora desde la última acción
de la navegación.

Mientras controla el navegador, puede editar la dirección y usar Atrás, Adelante
y Recargar. La navegación respeta los dominios permitidos del agente; la vista
muestra las direcciones rechazadas. Las pantallas de computer use no ofrecen
navegación del navegador.

Las herramientas directas mantienen la vista en directo entre llamadas hasta el
final del run. Las imágenes se detienen al desconectarse el último espectador
y se reanudan cuando vuelve; las consultas ligeras mantienen la dirección y el
título actualizados entre acciones. La escritura no espera una captura después de cada carácter. Las
acciones esperan una estabilidad del DOM limitada en el tiempo; la navegación
explícita sigue el documento nuevo incluso si la URL no cambia.

Las pestañas remotas de Chromium siguen cerrándose al terminar el run; las nativas
locales permanecen abiertas para su conversación — véase
[Navegador local](../desktop.md#local-browser-models-and-mcp).
La vista conserva solo el último fotograma pendiente y desconecta al receptor
que no acepta datos durante dos segundos. Las imágenes viajan una vez por el
socket de vista en directo, sin duplicarlas en el stream del chat.

| Configuración | Por defecto | Valores |
| --- | --- | --- |
| `cdp_url` | vacío | un endpoint DevTools de Chromium; obligatorio, y su host tiene que estar en `BROWSER_CDP_ALLOWED_HOSTS` |
| `allowed_domains` | null | hosts en los que puede estar el navegador; se admiten patrones como `*.example.com`; null es sin restricción en la web. Toda petición que apunte dentro de la red del despliegue (una dirección privada, de loopback, link-local o de metadatos, también tras una redirección) se rechaza salvo que su host esté aquí - añade una herramienta interna para navegarla (y, tras `BROWSER_EGRESS_PROXY`, también a las excepciones del proxy) |
| `max_steps` | 50 | 1–200; pasos por llamada, cada uno una petición al modelo |
| `vision` | `false` | envía también al modelo la captura de cada paso; el modelo tiene que leer imágenes |
| `prefer_native_browser` | `true` | pestaña nativa integrada para DOM local; desactivar para compatibilidad Chromium. Vision y cambios de idioma/zona horaria usan Chromium; no afecta a conexiones remotas |
| `candidate_cap` | 60 | 2–200; cuántos elementos se pueden ofrecer en un paso |
| `preview` | `true` | envía la vista del navegador al chat mientras navega |
| `preview_width` | 1024 | 320–1920; el ancho de la vista y, por tanto, de los fotogramas |
| `step_model_profile_id` | vacío | un perfil de modelo al que `browse_web` pregunta en cada paso en lugar del modelo del agent - un modelo más barato abarata un browse largo, y solo lo acelera donde su proveedor responde rápido (Claude Haiku por OpenRouter tardó por paso lo mismo que Sonnet); vacío usa el modelo del agent, que sus propias herramientas de navegador usan siempre |
| `connection` | `built_in` | `built_in`, `proxy`, `hosted` o `local`: cómo sale el navegador a la red |
| `proxy_url` | vacío | con `proxy`: `http://`, `https://` o `socks5://` con host y puerto; el secreto del binding, si lo hay, es su `username:password` |
| `hosted_url` | vacío | con `hosted`: la dirección CDP `wss://` del servicio; el secreto del binding es su clave y es obligatorio |
| `hosted_key_param` | `apiKey` | cómo llama el navegador alojado a su clave en la query de la dirección |
| `timezone` | vacío | una zona horaria IANA que declara el navegador - ajústala a la región del proxy |
| `locale` | vacío | una etiqueta de idioma como `pl-PL`, enviada como `Accept-Language` y `navigator.language` |

Para `local`, selecciona navegación local en **Work on** de la [aplicación de escritorio](../desktop.es.md#local-browser-models-and-mcp) emparejada. No requiere un endpoint CDP del servidor. Un perfil temporal visible de Chromium utiliza la red del equipo, incluidos servicios LAN tras consentimiento nativo; sigue aplicándose la lista de dominios de página. Los bindings proxy y hosted se rechazan en lugar de ignorarse. Se admiten ajustes de zona horaria e idioma. La configuración siguiente del navegador del despliegue corresponde a los otros modos.

**El navegador lo opera usted, y el operador dice cuál.** No hay Chromium en la imagen
de la API: `cdp_url` apunta a un servicio de navegador que un operador ejecuta y aísla.
Los ficheros de compose traen uno tras el perfil `browser` — `docker compose --profile
browser up -d browser`, accesible como `http://browser:9222`. El host tiene que estar en
[`BROWSER_CDP_ALLOWED_HOSTS`](../configuration.md), y una lista vacía — la de por defecto
— rechaza la automatización del navegador por completo. El host de
[`ARTIFACT_RENDER_CDP_URL`](../configuration.md#published-artifacts) se rechaza
aunque la lista lo nombre: ese navegador dibuja las páginas de las personas para
`preview_artifact` y nunca es de un autor. Se verifica **al publicar**, cuando se
guarda el spec, y no en cada run.

El navegador de compose está en una red de Docker propia, a la que solo se unen la
API y el worker para llegar a él: una página que abre, o a la que lo redirigen, no
alcanza la base de datos, Redis ni MinIO. Sigue alcanzando lo que permita
la red del host, como la dirección de metadatos de una nube, así que bloquéala en el
host donde importe.

**Un agent elige cómo sus browses salen a la red** (#2130), en los ajustes del propio
navegador, con el mismo `edit` sobre el agent que el resto. `connection` es
`built_in` - el navegador que nombra `cdp_url`, desde la dirección propia del
despliegue -, `proxy` o `hosted`, y `timezone` y `locale` dicen qué zona horaria e
idioma declara el navegador, sea cual sea el modo.

Un proxy (`proxy_url`) envía el tráfico de ese navegador por una dirección `http://`,
`https://` o `socks5://` - residencial o regional - y se autentica con el secreto del
binding como `username:password` cuando lo tiene.

Un proxy `http://` o
`socks5://` llega al navegador en la dirección que se comprobó, así que un nombre
que cambie entre la comprobación y la conexión no lo dirige al interior de la red;
un proxy `https://` conserva su nombre, para el que se emitió su certificado.

Un navegador alojado (`hosted_url`)
se conecta en cambio por `wss://` a un servicio de navegador - Browserbase, Steel o
uno propio - con el secreto del binding como clave, añadida a la query de la
dirección bajo `hosted_key_param` (`apiKey` por defecto).

Un navegador alojado nunca
empieza con los inicios de sesión guardados de una persona: su dirección la elige
el autor del agent, no un operador. Allí también cada recorrido recibe un contexto
de navegador propio, y un servicio que lo rechaza queda rechazado: su perfil
predeterminado no se da por privado, y lo que un recorrido escriba ahí - cookies,
local storage - le sobreviviría.

Una dirección dentro de la red del despliegue se rechaza al publicar y otra vez al
empezar un browse, salvo que el operador haya puesto el host en
`BROWSER_CDP_ALLOWED_HOSTS`. Chromium no puede autenticarse en un proxy SOCKS, así que
uno con contraseña tiene que ser HTTP. Un sitio que pide una contraseña nunca recibe
la del proxy. El navegador de inicio de sesión siempre usa el del propio despliegue.

**El navegador de compose se ve como uno de escritorio.** Es un Chromium completo con
ventana en una pantalla virtual (`docker/browser`), con las fuentes de un escritorio y
sin los flags que le dicen a una página que está siendo dirigida - el headless shell
al que sustituye decía `HeadlessChrome` en su user agent, y los sitios que rechazan bots
lo rechazaban al verlo. La capability también quita lo que una página aún podría leer
por CDP: nunca activa el dominio `Runtime`, y sustituye `Headless` en el user agent,
`navigator.webdriver` y un renderer WebGL `SwiftShader` donde un navegador los muestra,
así que un headless shell que un operador conserve también parece de escritorio.

Comprobado con la detección de bots de BrowserScan (_Normal_ en cada punto) y la tabla
de Sannysoft (todo superado). `BROWSER_TZ` y `BROWSER_LANG` en el entorno fijan dónde
y en qué idioma dice estar; por defecto `UTC` y `en-US`. Una comprobación de bots no
son unas condiciones de uso: lo que un sitio permite automatizar lo lee el operador
antes de dirigir agentes a él.

Es una lista de permitidos y no la comprobación SSRF por la que pasan otras URL del
inquilino, porque `cdp_url` vive en un spec que escribe cualquiera con `edit`, y la
protección SSRF falla aquí en ambos sentidos: rechaza el servicio aislado de su propia
red y acepta un depurador expuesto a internet. Chromium solo responde a DevTools por una
dirección IP, así que un endpoint `http` o `ws` dado por nombre se resuelve una vez y se
alcanza por su dirección; un endpoint TLS conserva su nombre para el certificado.

**Cada navegación tiene su propio contexto de navegador**, que se descarta al terminar el
run. En un navegador compartido por muchos, el contexto por defecto guardaría una cookie
que puso el agente de una persona, y el siguiente llegaría con su sesión iniciada.

**Cada paso va al propio modelo del agente.** La URL de la página, su título, las
etiquetas de los elementos y hasta 4.000 caracteres de su texto visible, más una captura
con `vision` activado — al mismo proveedor que la conversación y a ningún otro. Un valor
que escribe el agente no se repite: el historial anota que se rellenó un campo, no con
qué. Cada paso se comprueba contra el presupuesto del run antes de enviarse, así que un
presupuesto agotado detiene la navegación en vez de pagar el paso siguiente.

**`cdp-use` llega con el extra `browser`**, que una instalación por defecto no trae.
Quien quiera la capability instala `agenticos[browser]`; un agente en un despliegue sin
él falla esa herramienta de forma visible, con la línea de instalación.

Los specs anteriores a la versión 13 que vinculaban el navegador paso a paso
(`browser_choice`) se cargan como esta capability; la aprobación y el cambio de nombre de
`browse_page` pasan a `browse_web`, y se descartan los ajustes del modelo de decisión y
la clave de TypeSafe.

## Computer use { #computer-use }

`computer_screenshot` — _Take a screenshot of the desktop._

`computer_act` — _Act on the desktop: click, type, press keys, scroll, drag, open an app or wait._

`computer_apps` — _List the applications installed on the desktop, to open one with `launch`._

`computer_save_screenshot` — _Save a screenshot of the desktop for the user: shown in the chat and kept._

El agent maneja un escritorio entero, así que puede usar cualquier aplicación,
no solo una página web. Mira una captura de pantalla y envía unas pocas acciones
de ratón y teclado en los píxeles de esa captura. Cada respuesta de
`computer_act` incluye una captura nueva. Las pantallas más grandes se reducen a
`screen_width`x`screen_height` antes de que las vea el modelo, y cada punto se
traduce de vuelta a las coordenadas del propio escritorio, incluidos los puntos
de un Mac con pantalla Retina.

**La aprobación es para actuar, y hay que activarla.** Como cualquier tool,
ninguna de las dos espera aprobación hasta que el dueño del agent la pide.
`computer_screenshot` no cambia nada. Con `tool_approval: {computer_act:
required}`, cada lote de acciones espera aprobación frente a una captura que han
visto tanto el modelo como quien aprueba. Un punto fuera de esa captura se
rechaza antes de que se ejecute nada. Un lote aprobado se ejecuta en un run
propio, que primero mide la pantalla y solo actúa si sigue teniendo la forma que
tenía en la captura sobre la que se eligió el lote. Una resolución o una
proporción distintas no hacen nada y muestran al modelo la pantalla nueva.
`max_actions` es del run, por muchas veces que espere aprobación. La aprobación
cubre las acciones, no los píxeles bajo ellas: una ventana puede cambiar entre
la captura y el clic mientras la pantalla conserva su tamaño, así que deniega
un lote dirigido a una ventana en la que no confíes que siga igual.

| `desktop` | El escritorio | Necesita |
| --- | --- | --- |
| `sandbox` | Un escritorio Linux (XFCE y Firefox) dentro de la propia [sandbox](#files-shell) del agent, la misma máquina en la que trabajan su shell y sus tools de archivos | La capability [Sandbox](#files-shell) sobre una conexión de sandbox, con el runtime `desktop` |
| `daemon` | Un `computerd` que ejecuta el operador: su propio escritorio Linux (X11), la propia pantalla de un Mac (`uv run deploy/computer/computerd.py`) o un escritorio en un contenedor (`deploy/computer/Dockerfile`) | `daemon_url` en `COMPUTER_DAEMON_ALLOWED_HOSTS`, y el token del daemon como secreto de la vinculación |
| `e2b` | Un escritorio E2B propio del run, de la plantilla `desktop` de E2B, terminado cuando el run lo suelta | La clave de E2B de la organización como secreto del binding |
| `local` | La propia pantalla de la persona, en un chat que trabaja en su ordenador a través de la [app de escritorio](../desktop.md#the-screen) | Nada: la app pregunta a la persona antes de la primera captura |
| `auto` | La pantalla de la persona cuando el chat trabaja en su ordenador; si no, un escritorio E2B cuando el binding nombra una clave; si no, la sandbox | Lo que necesite el escritorio en el que acabe |

Un escritorio en la sandbox no necesita nada propio: ni dirección, ni token, ni
proveedor. Vive y se comparte exactamente como la sandbox, por conversación o
por agent según el `session_scope` de la capability Sandbox, y un archivo que el
agent escribe con sus tools de archivos es un archivo que puede abrir en la
pantalla.

Publicar rechaza un escritorio `sandbox` en un agent sin conexión de sandbox, y
en un especialista inline sin una propia ni una que comparta su padre. También
rechaza uno cuya sandbox no esté en el runtime `desktop`, leído como lo lee una
ejecución: el `runtime` de la capability Sandbox o, si no, el predeterminado de
la conexión. Una sandbox que no nombra ninguno también se rechaza, porque el
predeterminado que se distribuye es `workbench`, que no tiene pantalla. Una
conexión de Daytona se rechaza porque ejecuta su propia imagen.

**Abrir una aplicación.** `computer_apps` enumera las aplicaciones que muestra
el menú del escritorio, cada una con su nombre en el idioma del escritorio y su
id, el nombre de archivo de la entrada del menú. Una acción `launch` abre una de
ellas por cualquiera de los dos, en lugar de buscar su icono. La coincidencia es
exacta, sin distinguir mayúsculas: un nombre que comparten dos entradas, como un
Firefox del sistema y uno de Flatpak, se rechaza con sus ids, y un nombre
desconocido, con la indicación de llamar a `computer_apps`. `launch` acepta
solo un nombre, nunca una ruta ni argumentos: sin barras ni caracteres de
control, y empieza por una letra o un dígito.

Se lee cada directorio de la ruta de búsqueda del menú (`$XDG_DATA_HOME` y
`$XDG_DATA_DIRS`, así que también `/usr/local/share` y las exportaciones de
Flatpak) con sus subdirectorios: `kde/konsole.desktop` tiene el id
`kde-konsole`. Se omite lo que el menú no mostraría: entradas ocultas, que no
son aplicaciones, de otro escritorio que XFCE o con un `TryExec` no instalado.
La entrada se abre con `exo-open`, y la acción vuelve en cuanto aparece una
ventana nueva o se mueve el foco. Si nada de eso ocurre en diez segundos, el
lanzamiento falla y el resto de su lote no se ejecuta, así que no se escribe
nada en la ventana que tenía el foco antes.

Solo los escritorios Linux abren aplicaciones: el de un sandbox, un escritorio
de E2B y el contenedor de computerd, donde la aplicación se ejecuta como `desk`,
no como la cuenta que guarda el token. Un computerd en un Mac o en el propio
escritorio Linux de un operador, y el ordenador de la propia persona, al que se
llega por la app de escritorio, rechazan `launch` y `computer_apps`. A través de
la app de escritorio, al modelo se le indica que use el lanzador de ese
ordenador; a través de un daemon, que puede ser de un tipo o del otro, que llame
primero a `computer_apps` y use el lanzador del ordenador si se rechaza.

La tool `execute` no hace falta, y dejarla fuera mantiene las acciones del
escritorio detrás de `computer_act` y de su aprobación: con `execute`, el agent
puede ejecutar `xdotool` desde la shell.

Un daemon es un escritorio: cada run que apunta a él comparte la máquina y todo
lo que tenga la sesión iniciada en ella. Dale una máquina o una cuenta propias,
no la sesión de trabajo de alguien. El agent puede leer todo lo que pueda leer la
cuenta con la que se ejecuta el daemon, su token incluido; por eso el contenedor
de `deploy/computer/` ejecuta el daemon con una cuenta propia.

**El token de un daemon es de la organización.** El `COMPUTERD_TOKEN` con el que
se arrancó el daemon se guarda en el [vault](../secrets.md) de la organización
como clave de API y lo nombra el `secret_id` de la vinculación, y publicar
rechaza un daemon sin él. `COMPUTER_DAEMON_ALLOWED_HOSTS` es la lista del
despliegue de los sitios a los que un run puede enviar ese token. Se comprueba al
publicar y de nuevo cada vez que un run abre el daemon, así que quitar un host de
ella detiene a los agents ya publicados. Cualquier organización puede nombrar un
host permitido, así que es el token, y no la lista, lo que mantiene a una
organización fuera del escritorio de otra: da a cada escritorio su propio token.
`daemon_url` es solo la dirección del daemon, y se rechaza una con query,
fragmento o credenciales.

| Ajuste | Por defecto | Rango |
| --- | --- | --- |
| `desktop` | `auto` | `auto`, `sandbox`, `daemon`, `e2b`, `local` |
| `daemon_url` | vacío, rechazado al publicar con `daemon` | un host permitido, sin query, fragmento ni credenciales |
| `screen_width` × `screen_height` | 1280 × 800 | 640–1920 × 480–1200 |
| `max_actions_per_call` | 20 | 1–50, no más que `max_actions` |
| `max_actions` | 200 | 1–2000 por run |
| `preview` | activado |  |

El chat dibuja el escritorio en una ventana bajo el mensaje mientras el agent
trabaja: una ventana por run, abierta por la primera captura, con un fotograma
tras cada llamada y una línea por acción. El texto que escribe el modelo se muestra ahí tal como se escribió.

**Ver y tomar el control.** Cada escritorio se publica también en la vista en vivo
del run, la misma que usa un browse, así que un run de un canal o de una rutina se
puede ver desde la consola. **Tomar el control** pasa el escritorio a la persona
entre las llamadas del agent: sus clics, teclas y desplazamientos se ejecutan en
él, el agent espera, y **Devolver** se lo devuelve con la indicación al modelo de
que vuelva a mirar. Quién puede ver y tomar el control es la regla del browse; la
pantalla propia de la persona es solo suya.

**Una captura que el usuario conserva.** `computer_screenshot` es para el
modelo, y nada la guarda: un run que espera aprobación, su manifiesto y una
conversación compactada guardan una frase en su lugar. Cuando el usuario pide ver la pantalla, o el resultado
de un paso debe quedar como prueba, el agent llama a `computer_save_screenshot`.
Guarda la pantalla a resolución completa para la organización y la muestra en el
chat, enlazada al archivo a tamaño completo. Si el agent tiene un workspace,
también escribe el archivo en `output/`, de modo que la respuesta en un canal lo
lleva y un paso posterior puede incluirlo en un informe. Sin workspace, la
respuesta en un canal no lleva ningún archivo, igual que con la generación de
imágenes. No cambia nada en el
escritorio, y la aprobación no la retiene salvo que el propietario lo pida.

!!! warning "El texto de la pantalla no es de fiar"

    Las instrucciones dicen al modelo que lo que hay en pantalla son datos, nunca
    instrucciones, y que se detenga ante contraseñas, pagos y decisiones que
    corresponden al usuario. Lo que lo hace cumplir es la aprobación, y está
    desactivada hasta que el dueño del agent la activa: sin ella, `computer_act`
    deja que el agent actúe según lo que le diga cualquier ventana.

## Cálculos { #run-python }

`run_python` — _Ejecuta un pequeño programa en Python para calcular algo._

Una sandbox restringida, sin red y sin sistema de archivos, que es la razón por la
que el tiempo y la memoria son los únicos límites que merece la pena fijar.

| Configuración | Valor por defecto | Rango |
| --- | --- | --- |
| `timeout_secs` | 10 | > 0, ≤ 120 |
| `max_memory_mb` | 256 | 16–4096 |

!!! info "Por agent, no por despliegue"

    Un autor que sube un límite para un único agent con mucho tratamiento de datos
    no debería necesitar a un operador ni un redespliegue, y los topes están
    acotados en vez de ser abiertos.

## Sandbox { #files-shell }

`ls`, `read_file`, `glob`, `grep` — _lectura._
`write_file`, `edit_file`, `execute` — _escritura y ejecución._

Un workspace que sobrevive entre turnos. `code_execution` calcula y olvida; este
recuerda, y en un backend respaldado por contenedores tiene una shell de verdad. Un
agent al que se le conceden ambos calcula con uno y guarda su trabajo en el otro,
que es el emparejamiento habitual en el backend `state`, porque ese no tiene shell
en absoluto.

| Configuración | Valor por defecto | Valores |
| --- | --- | --- |
| `backend` | `state` | `state`, `service` |
| `connection_id` | null | una conexión de sandbox registrada; null toma la predeterminada de la organización. Solo `service` |
| `session_scope` | `conversation` | `run`, `conversation`, `channel`, `user`, `agent` |
| `runtime` | null | un alias que permita el servicio de esa conexión; solo `service` |
| `include_execute` | `true` | apagado, quita la shell por completo en lugar de ponerle una puerta |

No hay un backend `docker` ni `daytona` que elegir. _Dónde_ se ejecuta una sandbox
es una propiedad de la conexión que registró un operador — Sandboxes en la
aplicación —, así que nombrar la conexión es nombrar el tipo. Elegirlos por
separado hacía posible elegir dos cosas que se contradicen.

Un despliegue que ejecuta su propio servicio de sandbox - `sandboxd` arrancado
desde el archivo compose de este proyecto, con el token que generó
`make sandbox-token` - no necesita registrar nada. La primera vez que una
organización sin conexión predeterminada lista sus sandboxes o ejecuta un agente
que necesita una, la plataforma registra _This deployment's sandbox_ como
predeterminada, en nombre del propietario de la organización, con el token en su
bóveda y una entrada de auditoría como cualquier otra conexión. Del mismo modo,
el Architect recibe archivos y código cuando se instala en un despliegue así.

**`backend` es infraestructura; `session_scope` es una política de compartición de
datos.** Equivocarse en lo primero cuesta una funcionalidad. Equivocarse en lo
segundo le enseña a una persona los archivos de otra, así que merece la pena leerlo
dos veces:

| Ámbito | Quién comparte el workspace |
| --- | --- |
| `run` | Nadie: uno nuevo en cada turno |
| `conversation` | Todos los de ese chat. En Slack un hilo _es_ un chat, así que los hilos no comparten |
| `channel` | Todos los hilos de un canal. Un mensaje directo tiene su propio id de chat, así que cada persona sigue teniendo el suyo |
| `user` | Una persona, en todas las superficies desde las que alcanza este agent |
| `agent` | **Todos los que hablan con este agent**, en toda la organización |

`conversation` y `channel` existen como respuestas separadas porque una plataforma
de chat las convierte en cosas distintas. `SlackAdapter` incorpora `thread_ts` al id
del chat, así que `conversation` en Slack significa un workspace por hilo: cincuenta
hilos en un canal concurrido son cincuenta contenedores y un `429` para la persona
número cincuenta y uno que responda.

El ámbito del spec es el **valor por defecto**. Cada canal en el que se publica el
agent puede sobrescribirlo, en la exposición: un agent al que se llega por el chat
web y por un bot de Slack es un agent en dos situaciones, y un solo valor para
ambas era la forma equivocada. El ámbito `user` es el que lleva un workspace de una
superficie a otra: la misma persona que retoma en Slack una conversación que empezó
en el chat web encuentra ahí sus archivos.

`agent` es el que cruza una frontera entre personas. El Builder avisa en el campo,
el panel de archivos etiqueta de quién es el workspace en lugar de llamarlo «los
archivos de esta conversación», y fijarlo queda registrado en el log de auditoría,
porque un usuario que ve un archivo que no creó debería poder averiguar por qué.

**Cambiar el backend, la conexión o el runtime arranca un workspace nuevo en vez
de reengancharse al antiguo.** Un documento almacenado, el volumen de un contenedor
y una sandbox de Daytona son tres cosas distintas, y dos instalaciones de `sandboxd`
son dos cosas distintas, así que cada una tiene su propio workspace y el anterior se
queda donde está, aún listado y aún legible. El runtime de un contenedor se elige al
crearlo, así que un workspace movido a otro runtime seguiría, si no, en la imagen
antigua. No nombrar ningún runtime y nombrar `workbench`, el predeterminado que se
distribuye, son el mismo workspace. Mover un agent en marcha no es, por
tanto, una manera de llevarse sus archivos; el agent encuentra un workspace vacío en
el nuevo host. Dado que `connection_id: null` significa «la predeterminada de la
organización», marcar otra conexión como predeterminada tiene el mismo efecto sin
que cambie ningún spec.

Un spec elige una conexión y nunca una imagen, un montaje, un modo de red ni un
tope. Eso corresponde a quien opera el despliegue: un spec lo escribe en un
navegador cualquiera que tenga `edit` sobre el agent, y uno que pudiera nombrar una
imagen de contenedor podría nombrar una cuyo entrypoint monte el host. `runtime` es
un alias, y el Builder ofrece solo los alias que informa el servicio de esa
conexión, leídos en vivo, porque una copia almacenada ofrecería uno que el servicio
ya ha dejado de permitir.

Lo que cuesta ejecutar cada backend:

| Backend | Necesita | Shell | Dónde viven los archivos |
| --- | --- | --- | --- |
| `state` | nada | no | esta base de datos, con tope en `SANDBOX_STATE_MAX_BYTES` |
| `service` | una conexión registrada | sí | un contenedor en ese host, o la nube de Daytona en la cuenta propia de la organización |

Un operador puede ver qué hay en marcha: Sandboxes lista las sandboxes abiertas de
esta organización en su host predeterminado con sus runtimes, sus tiempos de
inactividad y su memoria, y el registro de actividad por sandbox. Consulta
[Configuración](../configuration.md#agent-workspaces).

La publicación se rechaza para un workspace `service` cuando la organización no ha
registrado ninguna conexión, cuando la que nombra ya no existe o cuando esa conexión
no tiene credencial; cada caso por su nombre, porque los tres son estados a los que
un despliegue llega _después_ de que se publicara un agent y el arreglo es de un
operador y no del autor.

**Solo `execute` se declara con efectos secundarios**, y nada pregunta hasta que un
autor lo pone tras una puerta. De las siete, solo ejecutar un comando actúa sobre el
mundo: un workspace es espacio de borrador que se
borra con la conversación a la que pertenece, así que escribir un archivo en él no
es de la misma clase de acto que enviar un correo — y un agent que tiene que
preguntar antes de cada `write_file` no puede hacer trabajo de varios pasos en
absoluto, que es como un autor acaba apagando la puerta del todo y perdiendo la que
importaba. `execute` ejecuta comandos arbitrarios en el host de alguien, así que es la que merece una puerta.

Una vinculación que quiera el comportamiento más estricto lo fija por herramienta:
`tool_approval: {"write_file": "required"}`. Consulta
[Gobernanza](../governance.md) para ver cómo se le plantea una aprobación a una
persona, y para las dos cosas que una _sesión de chat_ puede decir por encima del
spec: eximir toda llamada con puerta en esta conversación, o preguntar por cada
herramienta que tenga el agent, incluidas las herramientas MCP que la puerta guiada
por el spec deja deliberadamente en paz (agenticos#925).

**Algunas rutas se rechazan diga lo que diga la política de aprobación.** Las
credenciales (`**/.env`, `**/*.pem`, `**/*.key`, `**/credentials*`, `**/.ssh/**`,
`**/.aws/**`) y el árbol del sistema (`/etc/**`, `/usr/**`, `/proc/**` y sus
hermanos) no pueden leerse, escribirse ni editarse; el agent recibe un rechazo
legible y puede seguir. A `grep` se le filtra en lugar de rechazarlo, ya que un
patrón sobre `/` cubre legítimamente el workspace: las coincidencias dentro de un
archivo vedado se descartan, así que una búsqueda no puede devolver una línea de
uno. Los nombres no son secretos, así que `ls` y `glob` siguen mostrando lo que hay;
solo se retiene el contenido.

Un comando que _nombre_ una de esas rutas también se rechaza, así que
`cat /etc/shadow` no se salta la regla preguntándole a otra herramienta. Eso es
defensa en profundidad y no una frontera, y la diferencia importa: una shell alcanza
un archivo por caminos que la inspección de cadenas no puede ver, así que lo que de
verdad hace segura la ejecución es el aislamiento del contenedor y el modo de red
del operador. No hay lista de permitidos de cadenas de comandos, porque una así se
derrota con `sh -c`.

Y nada de esto sustituye a la puerta de aprobación: el rechazo de aquí es el no
rotundo del código, mientras que `execute` preguntándole a una persona es la
decisión que posee un operador.

Los archivos que alguien adjunta a un mensaje aterrizan en `/uploads`; consulta
[Tratamiento de archivos](../file-processing.md).

**Los skills también se vuelven archivos.** Un agent que tenga a la vez un workspace
y skills recibe cada skill como `/workspace/skills/<name>/SKILL.md` con sus recursos al lado,
que es lo que hace ejecutable el script de un skill: está en disco junto a la shell
que puede ejecutarlo. Deliberadamente no hay `run_skill_script`: `execute` ya tiene
detrás la puerta de aprobación y los topes del operador, y una segunda vía de
ejecución sería un segundo conjunto de reglas en el que equivocarse.

Esos archivos son escribibles, y lo que el agent escribe **no** se convierte en un
skill. Un skill son instrucciones que sigue en cada run todo agent vinculado a él,
así que un cambio se registra como una propuesta y alguien con `skills:edit` la
acepta o la descarta; consulta [Skills](../skills.md).

## Mirage (terminal virtual) { #mirage }

Las siete herramientas de `sandbox`, con el prefijo `mirage_`, sobre los servicios
que monta un autor: un Google Drive, un repositorio de GitHub, Notion, una base de
datos Postgres, un servidor SSH, un buzón de correo.
[Mirage](https://github.com/strukto-ai/mirage) (Apache-2.0) monta cada servicio como
una carpeta y ejecuta la shell sobre ella a través de la propia API del servicio,
así que el agent responde «¿qué contratos mencionan a Acme?» con un `grep` sobre una
carpeta de Drive. No arranca ningún contenedor. Un agent puede tener esta
capability y una sandbox a la vez: las herramientas del terminal siempre llegan al
terminal, y `execute` sigue llegando a la sandbox.

| Configuración | Por defecto | Valores |
| --- | --- | --- |
| `mounts` | obligatorio | De una a diez carpetas, cada una descrita abajo |
| `allowed_commands` | comandos virtuales salvo `curl`/`wget` | Nombres de comandos que la shell puede ejecutar, como `ls`, `cat`, `grep` |
| `hidden_paths` | ninguno | Rutas absolutas que el agent no ve en absoluto, como `/drive/HR/` |

**Una carpeta es una ruta, un servicio y una forma de iniciar sesión.** La ruta es
un nombre en minúsculas entre barras (`/drive/`). El servicio es uno de los
backends que el deployment puede montar, con sus propias opciones: un
repositorio, un id de carpeta, un host. Una carpeta es de solo lectura salvo que
el autor permita escribir. Una carpeta con escritura pide a una persona que
apruebe cada escritura salvo que el autor lo desactive. El Builder lista todos los
servicios que trae Mirage y da el motivo de cada uno que este deployment no puede
montar.

**Cómo inicia sesión una carpeta depende del servicio:**

| Credencial | Servicios | Qué guarda el spec |
| --- | --- | --- |
| Claves del vault | GitHub, Notion, Linear, Slack, Postgres, SSH, correo IMAP y el resto | Un secreto `api_key` por cada campo de credencial (`token`, `dsn`, `password`) |
| Una app de Entra | OneDrive, SharePoint | Un secreto `entra_app`, como el que el run inicia sesión para obtener un token de Microsoft Graph |
| Una cuenta de Google | Drive, Docs, Sheets, Slides, Gmail, Calendar | Una de las [cuentas conectadas](../secrets.md#connected-accounts) de la organización, o las propias de cada persona |
| Ninguna | Espacio temporal (`ram`) | Nada |

**Las cuentas propias de cada persona se buscan cuando esa persona habla con el
agent.** Quien tiene dos cuentas de Google recibe dos carpetas bajo el punto de
montaje, cada una con el nombre de su dirección. Quien no tiene ninguna, como una
clave de API o una programación, no recibe carpeta, y el agent lo sabe. Una cuenta
de la organización responde por todos los que hablan con el agent.

**Un spec nunca guarda una credencial, un endpoint sustituido ni una ruta en el
host de la API.** La publicación rechaza un secreto que quien publica no puede
prestar, un secreto del tipo equivocado y una cuenta que la organización no tiene.
Un host que escribe el autor tiene que estar en
[`MIRAGE_ALLOWED_HOSTS`](../configuration.md), como un servidor SSH o el host de un
DSN. La publicación comprueba el host escrito, y el run comprueba los hosts
guardados dentro de los secretos.

**La aprobación es por carpeta, no por herramienta.** `mirage_execute ls` y
`mirage_execute rm /drive/q3.pdf` son la misma herramienta, así que aprobar la
herramienta preguntaría por las dos. En su lugar, una llamada que escribiría en una
carpeta marcada «Aprobar cada escritura» pasa por la
[aprobación](../governance.md) antes de ejecutarse. Para `mirage_write_file` y
`mirage_edit_file` decide el `path` de la llamada. Para `mirage_execute`, Mirage
ensaya antes la línea de comandos, así que una redirección, `cp`, `tee` y `rm` se
detectan. Una escritura que ningún ensayo previó, como `echo x > $TARGET`, se
rechaza salvo que la llamada se haya aprobado.

**Límites y continuación tras la aprobación.** Mirage 0.0.8 limita la caché de
archivos a 16 MiB y la memoria del workspace a 16 MiB. Cada comando devuelve
como máximo 64 KiB por flujo de salida; después se detiene la lectura y se indica
que el resultado está incompleto. Las carpetas RAM se conservan en los metadatos
de mensajes del run pausado y se restauran tras aprobarlo, también en los
delegados. No se incluyen credenciales ni cachés de servicios externos. La
carpeta de cada cuenta personal incluye su ID estable para evitar que direcciones
de correo similares sobrescriban otras cuentas.

**Es una instalación opcional.** Instala el extra `mirage` (`EXTRAS="--extra mirage"`). Mirage 0.0.8 ya no requiere el antiguo paso de compilación del analizador de shell. Sin el extra, el Builder indica que falta el terminal y rechaza un spec que lo vincule. La familia S3 sigue sin estar disponible porque su SDK asíncrono entra en conflicto con las dependencias AWS actuales; el Builder explica el motivo. Todos los hosts configurables, incluidos los valores predeterminados de los backends, deben estar permitidos en `MIRAGE_ALLOWED_HOSTS`.

**Box y LanceDB.** Box utiliza una cuenta de servicio mediante Client Credentials: proporciona `client_id`, `enterprise_id` y un secreto API key del vault (propósito `custom`) para `client_secret`. No admite tokens de desarrollo ni refresh tokens OAuth rotatorios. LanceDB solo funciona como Cloud/Enterprise: requiere `uri: db://database-name`, un endpoint HTTPS `host_override` permitido en `MIRAGE_ALLOWED_HOSTS` y un secreto API key (`custom`) para `api_key`. Rechaza rutas locales, URI de almacenamiento de objetos y `storage_options`. El extra incluye LanceDB y PyArrow, lo que aumenta el tamaño de la imagen.

Qdrant y Langfuse están disponibles con el extra. Qdrant permite listar y leer
archivos y usar grep de texto; la búsqueda semántica con modelos no está habilitada.
El consentimiento debe terminar en el mismo navegador y con la misma cuenta
iniciadora de AgenticOS.

Los secretos del vault deben corresponder al propósito del backend; `custom` permite una integración propia de forma explícita. OneDrive y SharePoint aceptan una aplicación Entra con propósito `sharepoint`, y los servicios de Hugging Face aceptan `huggingface`. La publicación y la ejecución aplican la misma regla. Cada host de una lista de servidores PostgreSQL debe figurar en la lista permitida del despliegue. MongoDB y GridFS requieren un único host `mongodb://`: la plataforma fuerza `directConnection=true` y rechaza el descubrimiento SRV. Los remitentes de canales sin cuenta vinculada necesitan aprobación para cada herramienta Mirage, incluso las lecturas; al vincular la cuenta se aplica la política habitual de carpetas del autor.

Los montajes PostgreSQL requieren una contraseña no vacía en el DSN de la bóveda; no se admiten contraseñas vacías ni autenticación sin contraseña. No recurren a `PGPASSWORD` ni a `.pgpass`. Se rechazan los parámetros DSN que apuntan a archivos de credenciales o TLS del host (`passfile`, `servicefile`, `sslkey`, `sslcert`, `sslrootcert`, `sslcrl`).

SSH usa un nombre de usuario explícito y una contraseña del vault. Proporciona el `host_key` público de confianza del servidor; el adaptador fija esa clave y desactiva la configuración SSH local, las claves privadas locales y el agente SSH. No se permite la autenticación automática con credenciales del entorno.

## Gráficos { #charts }

`create_chart` — _Dibuja un gráfico con números que ya tienes, para que el usuario
pueda verlos._

Representa números que el modelo ya tiene. No descarga, ni calcula, ni agrega: para
eso, combínalo con `code_execution` o `knowledge`. Sin configuración.

Los números llegan como **columnas** — una lista `x_values` para el eje y una lista
`values` por serie — porque un argumento `data` de forma libre no es algo que un
JSON Schema pueda describir, y un modelo al que se le dio un array de objetos sin
propiedades declaradas devolvió uno solo y vacío.

Un gráfico sin nada dentro ahora es inexpresable en vez de meramente rechazado. Un
eje sin puntos, un gráfico sin series o una serie con menos números que puntos tiene
el eje: los tres vuelven como un reintento que nombra lo que falta.

Un marco dibujado alrededor de ningún dato se lee como «no hay tendencia» y no como
un error, y además se persiste y se vuelve a dibujar en cada repetición de la
conversación.

## Generación de imágenes { #image-generation }

`generate_image` — _Genera una imagen a partir de una descripción escrita._

Dibuja una imagen con un modelo de imagen dedicado — distinto del propio del agent —
de modo que funciona sea cual sea el modelo con el que corra el agent. `create_chart`
representa números; esta dibuja ilustraciones.

| Configuración | Valor por defecto | Valores |
| --- | --- | --- |
| `provider` | `openai` | Los providers cuya clase de modelo respeta la herramienta de imagen _y_ acepta una clave de API: dos a día de hoy |
| `model` | `gpt-image-2` | Los modelos de ese provider, desde `app/core/catalog/image_models.json` |
| `quality` | el del provider | `low`, `medium`, `high`, `auto` |
| `size` | el del provider | `auto`, `1024x1024`, `1024x1536`, `1536x1024`, `512`, `1K`, `2K`, `4K` |
| `background` | el del provider | `transparent`, `opaque`, `auto` |
| `output_format` | el del provider | `png`, `webp`, `jpeg` |
| `aspect_ratio` | el del provider | `16:9`, `1:1`, `9:16`, … |

**Qué providers saben dibujar lo responde el SDK, no una lista.**
`Model.supported_native_tools()` es un classmethod de todas las clases de modelo que
trae Pydantic AI, así que la plataforma se lo pregunta: `OpenAIResponsesModel`,
`GoogleModel` y `GoogleModel` a través de Vertex respetan `ImageGenerationTool`,
nadie más lo hace, y una actualización que enseñe a un cuarto no necesita código
aquí. Los modelos de imagen de Together y de Fireworks existen y fallarían en su
primera llamada con «not supported by this model», que es por lo que no se ofrecen.

**Poder dibujar y poder configurarse son dos preguntas**, y Vertex AI es donde se
separan. La capability sella una única clave de API y construye con ella todos los
providers, mientras que Vertex quiere una cuenta de servicio, así que una entrada
para Vertex sería una opción del selector para la que nadie puede aportar una
credencial, y se descarta junto a las que no saben dibujar. Ofrecerla significa
enseñarle a la capability formas de credencial específicas de cada provider, lo cual
es un cambio de la capability y no del catálogo.

**Qué modelos ofrece cada provider son datos**, en
`app/core/catalog/image_models.json`: un id, un nombre y una frase que dice cuándo
recurrir a él. Ningún endpoint de listado responde a esta pregunta — `/v1/models`
devuelve modelos de chat —, así que un modelo publicado esta mañana es una entrada de
catálogo y no una release. Una entrada de provider que el SDK no sepa manejar, o
cuya credencial esta capability no pueda construir, se descarta al leer el archivo:
la salvaguarda contra que el archivo críe algo indibujable o inconfigurable.

Los dos providers nombran el modelo de imagen en sitios distintos, y el catálogo
también lo recoge. En **Google** el modelo elegido _es_ el modelo de imagen. En
**OpenAI** la herramienta la llama un modelo Responses y dibuja con el elegido, así
que la entrada nombra a ese llamante y la elección viaja como el `model` de la
propia herramienta. Ninguna de las dos es una pregunta que se le haga al autor.

**Un spec publicado antes de que existiera el par sigue funcionando.** Esto era antes
una única cadena enumerada que llevaba el prefijo del SDK
(`openai-responses:gpt-5.4`), y un spec almacenado todavía la guarda. Leído contra
los dos campos eso es un modelo desconocido, así que la configuración normaliza la
forma antigua a la entrada: el prefijo nombra al provider, y un nombre que es el
_llamante_ en vez de un modelo que dibuja se resuelve al primer modelo de imagen de
ese provider. Solo cuando no se almacenó ningún `provider`: una vinculación que
nombre uno está declarando las dos mitades.

`model` decide además a qué provider pertenece la clave de API. La clave es
obligatoria — publicar un agent que vincule esto sin una se rechaza — y viene de los
[secretos](../secrets.md) de la organización, nombrada por el `secret_id` de la
vinculación. Todos los demás ajustes son opcionales; sin poner, el provider aplica
el suyo por defecto, así que encender la capability basta para generar.

**Tiene efectos secundarios.** Dibujar una imagen gasta dinero real de una clave de
provider y produce contenido que una persona puede publicar, así que cada llamada es
candidata a la [puerta de aprobación](../governance.md) y puede ponerse tras una
puerta por vinculación.

**Su gasto se contabiliza.** El modelo de imagen se ejecuta como un subagente cuyo
uso se anota en el libro del run, así que el coste de imagen cuenta contra un budget
igual que una petición al modelo. Los modelos de imagen a menudo no tienen precio en
la instantánea de precios, en cuyo caso el run registra la llamada a cero y marca su
total como parcial (`cost_is_partial`) en vez de ocultar el gasto.

**Adónde va la imagen.** Cada imagen generada se guarda **por organización** y se
sirve de vuelta con [`GET /api/v1/generated/{filename}`](../architecture.md),
acotada a la organización propia de quien llama: una frontera más amplia que la de
un archivo subido a un chat, que pertenece a un solo usuario. Se registra con la
conversación en la que se hizo y se borra con ella, cuenta contra la cuota de medios
generados de la organización y se borra tras el periodo de retención
([configuración](../configuration.md#generated-media)). Pasada la cuota, la
herramienta lo responde antes de gastar nada. Cuando el agent tiene además un workspace
(la capability `sandbox`), la misma imagen se escribe en él bajo `/output`, para que
un paso `execute` posterior pueda construir con ella: montar un PDF, una diapositiva,
una página. Un agent sin workspace sigue generando y mostrando imágenes; simplemente
no tiene dónde construir con ellas.

## Texto a voz { #text-to-speech }

`generate_speech` — _Lee un texto en voz alta como clip de audio._

Lee un texto en voz alta con el provider de voz que elige el autor y se comporta
como la generación de imágenes: el clip se guarda, aparece en la conversación como
reproductor y se escribe en `output/` cuando hay un workspace abierto (#2259).

| Configuración | Por defecto | Valores |
| --- | --- | --- |
| `provider` | `openai` | `openai`, `elevenlabs`, `google` |
| `model` | `gpt-4o-mini-tts` | Los modelos de ese provider, de `app/core/catalog/text_to_speech_models.json` |
| `voice` | la primera del modelo | La voz por defecto del agente; puede cambiarla en cada clip dentro de `voices`. Una voz del catálogo para OpenAI y Gemini; un id de tu propia biblioteca de voces para ElevenLabs |
| `voices` | ninguna: cualquier voz del modelo | Hasta 20 voces a las que el agente puede cambiar en cada clip, cada una con un `id` y, para una voz de la cuenta, una `note` de hasta 120 caracteres que dice quién es. Vacía permite todas las voces del modelo; en ElevenLabs, cualquier id de voz de la cuenta |
| `output_format` | el primero del provider | `mp3`, `wav` (Gemini solo devuelve `wav`) |
| `max_characters` | `5000` | 1–10 000; el máximo de texto que puede decir una llamada |

**Providers, modelos, voces y precios son datos**, en el fichero del catálogo. Un
provider es un [propósito de secreto](../secrets.md) con una clave de API simple -
ElevenLabs no ejecuta modelos de chat, así que es un servicio en el vault y no un
provider de modelos - y una entrada sin propósito, o cuya forma de API no tiene
cliente, se descarta. Los antiguos `tts-1` y `tts-1-hd` de OpenAI hablan con nueve
de sus trece voces, por eso las voces se listan por modelo.

**Las voces de ElevenLabs pertenecen a la cuenta.** Sus voces por defecto
compartidas caducan el 31-12-2026, así que el catálogo no lista ninguna y un
binding nombra una de las voces propias de la cuenta por su id; publicar sin ella
se rechaza.

**La voz es un valor por defecto; las voces permitidas son el límite.** `voice`
es la voz con la que habla el agente mientras no pida otra, y `voices` enumera
las únicas demás a las que puede cambiar, para un diálogo o para un narrador y
un personaje. Vacía, se permite cualquier voz del modelo; en ElevenLabs,
cualquier id de voz de la cuenta, clonadas incluidas, y el Builder lo advierte.
Las voces llegan al modelo como un `enum` en el parámetro `voice` de la
herramienta, con la habitual como valor por defecto y la descripción de cada una
del catálogo o, para una voz de la cuenta, la nota del autor. Una voz de cuenta
abierta es texto libre cuyo formato se comprueba. Una voz de la lista que el
modelo no tiene se rechaza al publicar, y una fuera de la lista se devuelve al
modelo en la llamada.

**El selector de claves muestra las claves del provider elegido.** El secreto es
obligatorio para todos los providers y se declara obligatorio _cuando_ `provider`
es uno de ellos, lo que le dice al Builder que el provider es el propósito de la
clave.

**Un texto largo es un solo clip.** Un texto que supera el límite por petición del
modelo se corta en un párrafo, una frase o una palabra y se dice en orden. Los
trozos MP3 se unen uno tras otro; el WAV se pide a cada provider como PCM de
24 kHz y se envuelve en una sola cabecera. `instructions` - tono, ritmo, acento -
llegan a los modelos que las leen (`gpt-4o-mini-tts` de OpenAI, Gemini) y se
omiten en los demás.

**Al budget se le pregunta con el precio del clip.** La voz se vende por carácter,
así que el catálogo guarda un precio fechado por millón de caracteres y el coste
se conoce antes de la llamada. Se rechaza un clip que llevaría el run más allá de
un límite; después se registra el coste y, si falla a medias, también los trozos
ya dichos. Los modelos que facturan por tokens se comprueban con un precio por
carácter de habla típica. Gemini, que devuelve su audio como PCM sin procesar, se
contabiliza después a partir del audio que devolvió cada trozo - tokens de texto de
entrada y 25 tokens de audio por segundo de salida -, así que una locución lenta
cuesta lo que el provider factura por ella. Un precio fechado entra en vigor ese día: así queda registrada la
duplicación de precios de Gemini el 01-01-2027.

**Se registra mientras se dice, un clip cada vez.** Cada trozo de un texto largo
se registra cuando llega su audio, así que un fallo o un run cancelado a medias
sigue registrando los trozos que volvieron. La comprobación del budget no reserva
nada, así que la herramienta hace una llamada cada vez. `instructions` tiene un
límite de 1000 caracteres, va al provider con cada trozo y no se tarifica.

**Tiene efectos secundarios**, por las mismas razones que la generación de
imágenes: gasta dinero y produce una grabación que alguien puede publicar.

**Los fallos van a quien puede arreglarlos.** El texto vacío, el que supera
`max_characters` o el que rechaza el provider vuelve al modelo, igual que un
provider que limita el tráfico o no responde. Una clave rechazada, una voz
desconocida y un budget agotado se responden como resultado, porque solo el autor
o el operador pueden arreglarlos; una voz elegida por el modelo que el provider no
conoce vuelve al modelo. Solo se registra el código de error del provider; su
texto de error nunca llega a los registros ni al modelo.

## Generación de vídeo { #video-generation }

`generate_video` — _Crea un vídeo corto a partir de una descripción escrita._

Crea un clip corto con el provider de vídeo que elige el autor y se comporta como
la generación de imágenes: el clip se guarda, aparece en la conversación como
reproductor y se escribe en `output/` cuando hay un workspace abierto (#2260).
Puede empezar desde una imagen: el `filename` que devolvió `generate_image` en el
mismo run o una ruta del workspace, donde una imagen generada también queda en
`output/`, reconocida por sus bytes y no por su nombre. Un nombre de fichero por sí
solo nunca llega a los ficheros generados de la organización: el run tiene que
haber hecho la imagen.

| Configuración | Por defecto | Valores |
| --- | --- | --- |
| `provider` | `google` | `google`, `byteplus`, `xai`, `alibaba` |
| `model` | `gemini-omni-1.1-flash` | Los modelos de ese provider, de `app/core/catalog/video_models.json` |
| `resolution` | la primera del modelo | La de por defecto; el agente puede pedir otra en cada clip, hasta `max_resolution` |
| `max_resolution` | ninguna: cualquiera que renderice el modelo | La más alta que el agente puede pedir; al menos `resolution` |
| `aspect_ratio` | la primera del modelo | La de por defecto; el agente puede pedir cualquier proporción que renderice el modelo |
| `seconds` | 5, o la más cercana del modelo | Dentro del rango del modelo; se rechaza para Gemini Omni, que decide su duración |
| `max_seconds` | el clip más largo del modelo | El clip más largo que puede pedir el agente; se rechaza para Gemini Omni |
| `audio` | la del provider | Por defecto activado o no; el agente puede pedir cualquiera de los dos en cada clip. Se rechaza cuando el sonido del modelo es fijo |
| `alibaba_workspace` | ninguno: el endpoint compartido de DashScope | Solo Alibaba: el id del workspace de Model Studio, una etiqueta de host; Wan se llama entonces en `https://{workspace}.{region}.maas.aliyuncs.com/api/v1` |
| `alibaba_region` | `ap-southeast-1` | Solo Alibaba: `ap-southeast-1`, `us-east-1`, `eu-central-1`, `ap-northeast-1`, `cn-beijing`, `cn-hongkong` |
| `timeout_seconds` | `600` | 60–1800 |

**Lo que puede hacer cada modelo son datos.** El catálogo indica el rango de
duración de cada modelo, sus proporciones, sus resoluciones, si sus clips llevan
sonido y si puede empezar desde una imagen, y el Builder solo ofrece eso. BytePlus
es un [propósito de secreto](../secrets.md) en el vault; Google, xAI y Alibaba
Cloud ya son providers de modelos. Falta OpenAI: su API de vídeo se cerró el
24-09-2026.

**Los ajustes son valores por defecto; la resolución más alta es el límite.** La
resolución, la proporción, la duración y el sonido de un binding son los del
clip, salvo que el agente pida otros en la llamada. La duración se detiene en
`max_seconds`, la proporción en las que renderiza el modelo y la resolución en
`max_resolution`: vacía, el agente puede pedir cualquier resolución del modelo,
y el Builder lo advierte, porque la resolución es lo que cuesta un segundo. El
presupuesto se consulta con el precio de la resolución elegida. La proporción y
la resolución llegan al modelo como un `enum` con la habitual por defecto, y el
sonido solo se ofrece donde el modelo lo hace opcional.

**Un clip es un trabajo que se espera como una imagen.** Gemini responde en la
propia petición; BytePlus, xAI y Alibaba aceptan un trabajo que se consulta. En
ambos casos la llamada espera uno o varios minutos, como mucho `timeout_seconds`.
Un trabajo que lo supera se cancela donde el provider lo permite - en BytePlus,
mientras sigue en cola - y la llamada recibe una respuesta en vez de reintentarse,
porque xAI y Alibaba no documentan la cancelación y pueden terminar y facturar el
trabajo. El clip se descarga antes de que caduque la dirección del provider, y la
clave nunca va a un host de almacenamiento.

**Al budget se le pregunta con el precio del clip.** Todos los providers facturan
por segundo con una tarifa que fija la resolución, así que el catálogo guarda un
precio fechado por segundo y resolución. Se rechaza un clip que llevaría el run
más allá de un límite; después se registra la duración que informa el provider.
Gemini Omni decide su duración y no la informa, así que allí el clip se tarifica y
se registra con la duración máxima del modelo.

**Tiene efectos secundarios**, por las mismas razones que la generación de
imágenes, y más: un clip es la llamada individual más cara que hace un agente.

**Los fallos van a quien puede arreglarlos.** Un prompt vacío, una duración o
proporción que el modelo no hace y una imagen que no se puede leer vuelven al
modelo con una indicación, igual que un provider que limita o está caído. Una
clave rechazada, un presupuesto agotado, un prompt que la política de contenido
del provider rechazó y un trabajo que pasa el límite de tiempo se responden como
resultado: una indicación de reintento ante un rechazo invitaría a sortearlo. Un
trabajo que pasa el límite de tiempo, o que se cancela con la ejecución, se
contabiliza con su estimación en cuanto su solicitud pudo llegar al provider,
porque el provider aún puede
terminarlo y cobrarlo. Un clip hecho que no se pudo descargar también se
contabiliza, y se responde como resultado en lugar de devolverse al modelo: un
segundo intento se cobraría de nuevo.

## Coding agent { #coding-agent }

**Cuentas personales en la nube.** En **Settings → Profile → Coding accounts**, conecta una clave de Anthropic/token de configuración de Claude, una clave de OpenAI o un nuevo inicio de sesión de ChatGPT y habilita su uso explícitamente en esta organización. Elige **Private cloud task with my account** en Coding agent. Solo las tareas autenticadas que inicies en el chat web/API pueden usarla; no horarios, canales, claves API ni suplantación. Otros miembros no pueden tomar prestada tu cuenta.

Un contenedor independiente recibe una copia limitada del código (500 archivos, 1 MiB por archivo, 16 MiB en total; sin enlaces simbólicos ni carpetas de plataforma o caché). El informe final identifica cuenta y snapshot, con diff y ZIP en el chat. Los archivos de origen no cambian automáticamente. Revocar el acceso a la cuenta cancela el trabajo. También puedes revocar el permiso externo de ChatGPT en sus ajustes. Las credenciales organizativas existentes y los inicios de sesión CLI locales siguen separados. Actualiza API y workers juntos después de `0290_personal_coding_accounts.py`.

El modo personal en la nube solo acepta workspaces de origen privados. Rechaza proyectos, workspaces de agente/canal, chats grupales y conversaciones compartidas para editar antes de cargar credenciales o copiar archivos. Un contenedor privado de destino no convierte en fiable el código controlado por colaboradores. Usa el modo de programación configurado por la organización para proyectos compartidos. La redacción del resultado no protege credenciales frente al código ejecutable.

`run_coding_agent` — _Hand a software task to the coding agent, which works on it in the sandbox until done._

Entrega el trabajo de software a **Claude Code** o **Codex**, que se ejecutan en la
propia [sandbox](../sandbox.md) del agent. Un agent corriente con shell puede editar
código; un harness de programación lo hace mejor, y así es como un agent llega a uno.
El harness es un agent aparte: el agent le entrega una tarea entera, el harness
trabaja hasta terminarla y el chat lo muestra trabajando. Otro agent llega a un
coding agent mediante la [delegación](#delegation) de siempre, como a cualquier
especialista.

| Configuración | Predeterminado | Valores |
| --- | --- | --- |
| `harness` | `claude_code` | `claude_code` (una clave API de Anthropic o un token de suscripción de Claude), `codex` (una clave API de OpenAI o un inicio de sesión de ChatGPT) |
| `access` | `edit` | `edit` cambia archivos y ejecuta comandos; `read_only` lee el código y responde (Claude Code o Codex en este ordenador) |
| `model` | el del harness | Claude Opus, Sonnet o Haiku 5.5 para Claude Code; GPT-5.6 Sol, Terra, Luna o GPT-5.3 Codex para Codex |
| `base_url` | Anthropic directamente | Solo Claude Code: una pasarela que habla la API de Anthropic, como `https://openrouter.ai/api`, cuya clave guarda entonces el vault. Se descarta al elegir Codex |
| `timeout_minutes` | 15 | 1–60, por tarea |
| `runs_on` | `sandbox` | `sandbox` ejecuta la tarea en el sandbox del agente con una clave; `this_computer` la ejecuta en la carpeta que una persona eligió en su propio ordenador en la aplicación de escritorio, con la sesión que el agente ya tiene, sin clave |

**Una herramienta, y el binding decide lo que puede hacer.** Con `edit` el harness
edita cualquier archivo y ejecuta cualquier comando en la sandbox, con sus propias
preguntas desactivadas (`--dangerously-skip-permissions`, `--dangerously-bypass-approvals-and-sandbox`):
nadie está ante su terminal, y el límite es el contenedor para el que ambas opciones
están documentadas. Con `read_only`, Claude Code se ejecuta en modo plan, sin
ninguna herramienta que escriba - ni las de edición ni la shell - y lee con Read, Grep
y Glob; sabe que no se puede aprobar nada más. Ni siquiera comandos que leen: ninguna
lista de prefijos de comandos hace de una shell algo de solo lectura, porque
`git log --output=<archivo>` encaja con `git log` igual que cualquier lectura. Codex dentro de un contenedor no tiene `read_only`: su modo de solo lectura es una
sandbox propia, que no arranca dentro del contenedor del agent, y la publicación
rechaza la combinación. Que una persona diga sí antes de cada tarea es la
**Aprobación humana** de la capability, puesta en **Preguntar siempre**. El Builder elige este modo para bindings nuevos;
los existentes conservan su política. No hay pestaña de
herramientas: la única herramienta es la capability.

**Sesiones con nombre.** Cada tarea indica una `session` - `main` cuando no indica ninguna. El mismo nombre continúa el trabajo anterior de esa sesión en la conversación; un nombre nuevo abre otra, y las sesiones independientes se ejecutan en paralelo cuando el agente llama a la herramienta varias veces a la vez. `fresh_session` reinicia una sesión. En este ordenador una sesión también puede elegir su `harness` - Claude Code o Codex, con la sesión iniciada en ese ordenador - y una `folder` dentro de la carpeta del chat, de modo que dos proyectos, o ambos harnesses, trabajan a la vez. En una sandbox o en una tarea privada en la nube el harness del binding es el único, porque la clave o la cuenta le pertenecen.

**En este ordenador.** Configura `runs_on` como `this_computer` para usar el harness instalado mediante [Agent Client Protocol](https://agentclientprotocol.com). El escritorio inicia un adaptador con versión fijada mediante `npx`; el servidor habla ACP. Elige una carpeta con acceso completo en **Work on** y confirma cada inicio de forma nativa. La carpeta es un directorio de trabajo, no una sandbox del sistema. El harness usa su propia sesión; la clave de vault es opcional. Los permisos siguen `access`; la aprobación se aplica una vez por tarea. Claude read-only desactiva bypass y herramientas de escritura; Codex local selecciona su modo de lectura nativo.

Las siguientes tareas cargan la misma sesión de conversación; `fresh_session` inicia otra explícitamente. Las correcciones interrumpen el turno ACP y continúan la sesión tras confirmar la parada. Los identificadores quedan fuera del repositorio y se borran al desvincular. Las tareas de suscripción sin precio, incluidas las iniciadas que fallan, hacen del coste del run un mínimo. Consulta [la aplicación de escritorio](../desktop.md#coding-agents-on-this-computer).

**La persona lo ve trabajar.** El harness se arranca en segundo plano en la sandbox
(`claude -p --output-format stream-json` o `codex exec --json`), y su archivo de
eventos se lee cada segundo y medio. Cada paso llega al chat mientras ocurre, en un
panel propio bajo la marca de Claude Code o Codex, como los de una delegación: el
archivo que lee, la edición, el comando que ejecuta, lo que dice entre medias. Al
terminar, el resultado de la llamada contiene la respuesta, cada paso y los archivos
que cambió. Una tarea que pasa de `timeout_minutes`, y una que la persona detiene,
ve detenido todo su grupo de procesos. En segundo plano significa también que una
tarea no se corta en el límite del servicio de sandbox para un comando.

**Lo que cambió, como diff.** Con `edit` en una conversación, el workspace se
captura antes de la tarea y otra vez después, en un almacén git propio de la tarea
bajo `/tmp` - nunca en el repositorio que alguien clonó, cuyo índice e historial
quedan intactos. El panel enumera entonces los archivos que la tarea añadió,
cambió, eliminó o renombró, y después los fragmentos de cada archivo, con
**Copiar parche**; una tarea que no cambió nada lo dice. Una tarea fallida o que
agotó su tiempo también conserva su diff. Quedan fuera las carpetas propias de la
plataforma `.agenticos/`, `skills/` y `tool_output/`, las carpetas de herramientas
como `.git`, `.venv` y `node_modules`, y los archivos de más de 1 MiB, salvo los que
eran más pequeños al empezar la tarea. El parche se guarda hasta 256 KiB y 500 archivos, y se marca donde se cortó.

**Quién lee el diff.** Se guarda con la conversación y se lee con el mismo acceso
que su transcripción, así que lo ve quien pueda leer el chat; borrar el chat lo
borra. En una sandbox que comparten varios chats, una tarea que se ejecuta a la vez
que otra ve también los cambios de esa en su diff. Una tarea en este ordenador no registra diff.

**Revertir esta tarea.** Las tareas nuevas pueden restaurar archivos regulares
solo si su snapshot completo se capturó en un workspace aislado de conversación.
Los snapshots con ámbito de proyecto, agente, canal o usuario siguen siendo de
solo lectura, porque pueden incluir trabajo de otra conversación. Necesitas
acceso de edición actual y ningún run debe estar escribiendo en el workspace.
El contenido y modo ejecutable de cada archivo deben coincidir con el estado
final de la tarea. Un conflicto rechaza toda la reversión e indica los archivos.
Los demás archivos, el índice de Git y su historial permanecen sin cambios.

La acción encola un trabajo duradero y reserva el workspace. El panel muestra el
progreso y los rechazos confirmados. Un resultado desconocido conserva la reserva;
**Reintentar reversión** comprueba antes de escribir si los archivos ya se
restauraron. Así, un fallo o una respuesta perdida no aplica la reversión dos
veces. El worker vuelve a comprobar el acceso y registra el éxito en la auditoría.

La reversión restaura solo archivos; conserva la conversación y el informe.
Requiere Git y Python 3 y rechaza snapshots truncados, redactados, antiguos de
solo visualización, archivos enlazados y archivos actuales de más de 2 MiB. No
sustituye un workspace eliminado o trasladado.

**Número de archivos cambiados.** El panel y el pie del mensaje usan el conjunto
de cambios guardado, incluidas las ediciones del shell y el número de archivos
omitidos por el límite. Solo una tarea sin conjunto de cambios usa la lista del
harness; los informes nuevos expresan esas rutas respecto al workspace.

**Las tareas de una conversación continúan una sesión.** El id de sesión del harness
se guarda en la sandbox junto al trabajo, en `.agenticos/coding-agent/`, uno por
conversación, así que la segunda tarea de un chat sabe lo que leyó la primera - y un
chat nunca continúa la de otro en una sandbox que comparten varias: la de un proyecto o
una asignada a una persona o a un agent. El modelo pasa `fresh_session`
para empezar de cero, y una sesión que la sandbox ya no tiene empieza de cero sola,
una vez.

**Lo que necesita.** La capability `sandbox` en el backend `service` con los
comandos de shell activados — publicar rechaza cualquier otra cosa — y un runtime con
el harness instalado: el runtime `workbench` fija Claude Code 2.1.288 y Codex
0.160.0. La credencial viene del vault mediante el `secret_id` del binding y llega al
comando por su entorno, nunca en su línea de comandos. En un [proyecto](../projects.md)
que guarda sus archivos sin contenedor no hay shell, así que el coding agent se deja
fuera de los runs ahí y el agent sabe por qué.

**Una clave o una suscripción.** Claude Code toma una clave API de Anthropic, o el
token que `claude setup-token` imprime para una suscripción Claude Pro o Max, guardado
como clave — se distingue por su prefijo `sk-ant-oat` y solo inicia sesión en
Anthropic, no en una pasarela. Codex toma una clave API de OpenAI, o un inicio de
sesión de ChatGPT hecho con **Sign in with ChatGPT**, el mismo que usa un
[perfil de modelo](../models.md). Para una tarea, el inicio de sesión se escribe en un
`auth.json` en un directorio de Codex propio de esa tarea (`CODEX_HOME`), fuera
del workspace, y se elimina después - dos tareas que se ejecutan a la vez nunca
comparten uno, y las sesiones que Codex reanuda se guardan por conversación a su
lado. Los tokens que Codex renovó se sellan de nuevo
sobre el mismo secreto. Todo lo que Codex ejecuta puede leer ese archivo, así que el
inicio de sesión solo se entrega a una persona que puede verlo en el vault - ejecutar
el agent nunca es un camino a la suscripción de otro -, y solo en un sandbox que no
comparten tareas de otras personas: en el contenedor de un proyecto, en uno a nivel de
agent o en un chat compartido con alguien para editar, la tarea de otra persona se ejecuta como el mismo usuario y podría leerlo.
Una clave API es distinta:
es del agent, como el token de un bot en Slack, así que cada run la usa, sea quien
sea quien preguntó - y todo lo que ejecuta una tarea puede leerla. Vincula una
clave que puedan compartir todos los que pueden ejecutar el agent. Trabajar con una suscripción
personal está sujeto a las condiciones de Anthropic y OpenAI para esos planes, que
pueden no permitirlo en un despliegue compartido.

**La clave encaja con el harness.** El selector ofrece a Claude Code solo claves
guardadas para Anthropic, y a Codex solo claves de OpenAI e inicios de sesión de
ChatGPT. Una clave guardada como `custom` encaja con los dos, igual que la clave
ya vinculada. Publicar rechaza una clave guardada para otro proveedor y nombra los
que acepta el harness: una clave de OpenAI vinculada a Claude Code se publicaría y
luego fallaría en cada tarea. Con `base_url` definido, la clave es de la
pasarela - OpenRouter, LiteLLM u otra -, así que Claude Code acepta ahí cualquier
clave.

**Delegar en un coding agent.** Un delegado que enlaza `sandbox` por sí mismo se
ejecuta en un workspace nuevo en memoria, sin shell, así que un coding agent al que se
llega por delegación no tiene dónde ejecutar su harness. Da al agent que delega la
capability `sandbox` en una conexión de sandbox y añade `sandbox` a _Capabilities delegates inherit_ en la
delegación: el coding agent trabaja entonces en el contenedor
del padre, y los archivos que escribe son los que ve el padre.

**Su gasto se mide.** Ambos harness informan de sus tokens por modelo, que se
anotan en el registro del run como cualquier petición al modelo, y el budget se
comprueba antes de cada tarea. Codex no nombra ningún modelo en sus eventos, así que
sin `model` su uso se anota sin precio y el coste del run se marca como parcial.
Igual se anota una tarea que termina antes de que su harness diga cuánto gastó:
fallida, agotado su tiempo o detenida.

## Harness { #harness }

`harness_start` — *Abre una sesión de harness con nombre con un primer prompt, y la mantiene abierta.*
`harness_prompt` — *Envía un prompt de seguimiento a una sesión de harness con nombre.*
`harness_stop` — *Cierra una sesión de harness con nombre.*
`harness_sessions` — *Lista las sesiones de harness que esta conversación tiene abiertas.*

Un agente respaldado por una sesión de **Claude Code**, **Codex**, **OpenCode**,
**Gemini CLI** o **Pi** en su propio [sandbox](../sandbox.md), mantenida abierta
a lo largo de los turnos: el agente inicia una sesión
por línea de trabajo y le envía prompts a medida que avanza el trabajo, en lugar de entregar una
tarea a un harness e informar. La sesión es del CLI: recuerda lo que sus prompts anteriores leyeron y cambiaron, y una persona ve en el chat cómo
trabaja cada prompt. Otro agente llega a un agente respaldado por harness mediante
[delegación](#delegation) ordinaria, como a cualquier especialista.

| Configuración | Por defecto | Valores |
|---|---|---|
| `harness` | `claude_code` | `claude_code` (una clave API de Anthropic o un token de suscripción de Claude), `codex` (una clave API de OpenAI), `opencode` (la clave del modelo elegido), `gemini` (una clave API de Gemini), `pi` (la clave del modelo elegido) |
| `access` | `read_only` | `read_only` lee el código y responde; `edit` cambia archivos y ejecuta comandos |
| `model` | el modelo por defecto del harness | Claude Opus, Sonnet o Haiku 5.5 para Claude Code; GPT-5.6 Sol, Terra, Luna o GPT-5.3 Codex para Codex; `provider/model` para OpenCode y Pi (hay que elegir un modelo para determinar el proveedor de la clave); Gemini CLI conserva el valor predeterminado del harness (`auto`) |
| `base_url` | Anthropic directamente | Solo Claude Code: un gateway que habla la API de Anthropic, como `https://openrouter.ai/api`, cuya clave guarda entonces el vault. Se descarta cuando se elige Codex |
| `timeout_minutes` | 30 | 1–60, para un prompt. La sesión se mantiene abierta |

**Cuatro herramientas, y el binding decide lo que pueden hacer.** Con `edit`, el harness edita
cualquier archivo y ejecuta cualquier comando en el sandbox, con sus propios prompts
desactivados (`--dangerously-skip-permissions`, `--dangerously-bypass-approvals-and-sandbox`):
nadie se sienta en su terminal, y el contenedor es el límite para el que ambos flags están
documentados. Con `read_only`, Claude Code corre en modo plan sin ninguna herramienta
que escriba —sin sus herramientas de edición ni la shell— y lee con Read, Grep y Glob;
se le dice que nada más puede aprobarse. Codex en un contenedor no tiene `read_only`: su modo de solo lectura es
un sandbox propio, que no puede arrancar dentro del contenedor del agente, y la publicación
rechaza la combinación.

Con `read_only`, OpenCode usa su agente de planificación, que deniega las
ediciones; Gemini CLI usa su modo de aprobación de planes. Pi ejecuta solo sus
herramientas de lectura (`read,grep,find,ls`), porque nunca pide aprobación.
Que una persona diga que sí antes de cada prompt es la
**Aprobación humana** de la capability —como cada gate, está apagada
hasta que alguien la enciende. No hay pestaña de Herramientas: las cuatro herramientas son la capability.

**Sesiones con nombre.** Cada prompt nombra una `session` —`main` cuando no nombra ninguna. El mismo nombre continúa el trabajo anterior de esa sesión en la conversación; un nombre nuevo abre otra. `harness_start` sobre un nombre ya abierto la reinicia, y `harness_stop` la cierra, así que un prompt posterior con ese nombre abre una nueva. Los prompts de un toolset corren uno a la vez, así que dos prompts a la misma sesión no pueden entrelazarse. Una sesión de harness nunca es reanudada por el coding agent, y una tarea del coding agent nunca continúa una sesión de harness: sus archivos de sesión viven separados, `.agenticos/harness/` y `.agenticos/coding-agent/`.

**Las sesiones de una conversación continúan a través de los prompts.** El id de sesión del harness se guarda
en el sandbox junto al trabajo, en `.agenticos/harness/`, uno por
conversación y nombre de sesión, así que el segundo prompt de un chat sabe lo que leyó el primero —y un
chat nunca continúa la sesión de otro en un sandbox compartido por varios, en un proyecto o en un ámbito
de una persona o un agente. Una sesión que el sandbox ya no guarda empieza de nuevo por sí sola, una vez.

**La persona ve cómo trabaja.** Un prompt corre como una tarea del coding agent: el harness se inicia separado en el sandbox,
`claude -p --output-format stream-json`, `codex exec --json`, `opencode run --format json`,
`gemini -p --output-format stream-json` o `pi --mode json`, y su archivo de eventos
se lee cada segundo y medio. Cada paso llega al chat cuando ocurre, en un
panel propio bajo la marca del harness, como los pasos de una delegación:
el archivo que lee, la edición, el comando que ejecuta, lo que dice entre ellos. Cuando
termina, el resultado de la llamada contiene la respuesta, cada paso y los archivos que
cambió. Un prompt pasado `timeout_minutes`, y uno que la persona detiene, termina con todo
su grupo de procesos detenido.

**Lo que necesita.** La capability `sandbox` en el backend `service` con los comandos de shell
activados —la publicación rechaza cualquier otra cosa— y un runtime con el harness
instalado: el runtime `workbench` fija Claude Code 2.1.288 y Codex 0.160.0.
No se ha establecido si incluye OpenCode, Gemini CLI o Pi; un harness que no
esté instalado informa del fallo en lugar de afirmar lo contrario. La
credencial viene del vault a través del `secret_id` del binding y llega al
comando por su entorno, nunca en su línea de comandos. En un [proyecto](../projects.md)
que guarda sus archivos sin contenedor no hay shell, así que el harness queda
fuera de los runs allí y al agente se le dice por qué.

**Una clave, no un inicio de sesión.** Claude Code acepta una clave API de Anthropic, o el token
que imprime `claude setup-token` para una suscripción Claude Pro o Max, guardado como clave —
se distingue por su prefijo `sk-ant-oat`, y solo inicia sesión en Anthropic, no
en un gateway. Codex acepta una clave API de OpenAI. OpenCode y Pi aceptan la
clave del modelo elegido, por lo que el binding debe seleccionar un modelo;
Gemini CLI siempre acepta una clave API de Gemini.

Un inicio de sesión con ChatGPT aún no se acepta aquí: el flujo de inicio de
sesión del coding agent —un home aislado, una comprobación de visibilidad y
rotación de tokens leída de vuelta desde el sandbox— no está conectado en esta
capability, así que el selector solo ofrece claves API.

Una clave API es del agente, como el token de un bot en Slack, así que
cada run la usa, pregunte quien pregunte —y cualquier cosa que ejecute un prompt puede leerla. Vincula
una clave que puedan compartir todos los que puedan ejecutar el agente.
Usar una suscripción personal está sujeto a los términos de Anthropic para
esos planes, que pueden no permitirlo en un deployment compartido.

**La clave encaja con el harness.** El selector ofrece a Claude Code solo claves guardadas para
Anthropic, y a Codex solo claves de OpenAI. OpenCode y Pi ofrecen solo la clave
del proveedor del modelo, y Gemini CLI solo claves de Gemini. Una clave guardada
para `custom` encaja con cualquier harness, igual que la clave ya vinculada.
La publicación rechaza una clave
guardada para otro proveedor y nombra las que acepta el harness: una clave de OpenAI
vinculada a Claude Code se publicaría y luego fallaría en cada prompt. Con `base_url`
fijado, la clave es la del gateway —OpenRouter, LiteLLM u otro— así que Claude Code
acepta entonces cualquier clave.

**Su gasto se mide.** Los harness informan de sus tokens por modelo, que se
apuntan en el ledger del run como cualquier petición de modelo, y el presupuesto se comprueba antes
de cada prompt. Codex no nombra ningún modelo en sus eventos, así que sin `model` fijado su uso se
apunta sin precio y el coste del run se marca parcial. Un prompt que termina antes de que su
harness informe de lo que gastó —fallido, agotado o detenido— se apunta igual.

## Watch a command { #monitor }

`start_monitor`, `list_monitors`, `stop_monitor` — _Vigila un comando de larga duración y entérate de su salida a medida que aparece._

Permite que un agente inicie un comando que se ejecuta durante mucho tiempo - un watcher de pruebas, un tail de logs, una compilación, un sondeo de CI o de despliegue - y se entere de su salida sin consultarla. El comando se ejecuta desacoplado en el espacio de trabajo de la ejecución, con su salida en un archivo allí.

Antes de cada petición al modelo se leen las líneas nuevas, se filtran con las palabras opcionales `match` (separadas por `|`, sin distinguir mayúsculas; texto simple, no una expresión regular) y se ponen al final de la petición como una nota efímera, como un recordatorio de dirección, de modo que nada se escribe en el historial de la conversación. Una vigilancia que termina se notifica con su código de salida.

| Herramienta | Qué hace |
| --- | --- |
| `start_monitor` | Inicia `command` con `label` y `match` opcionales; como máximo cuatro a la vez |
| `list_monitors` | Lista las vigilancias con su estado, código de salida, cuántas líneas coincidieron y las últimas diez |
| `stop_monitor` | Detiene una vigilancia y los procesos que inició |

**Una vigilancia vive lo que la ejecución.** Cada vigilancia se detiene al terminar el turno, así que un comando nunca sobrevive al turno que lo pidió. Necesita un shell persistente del sandbox. El shell de escritorio termina sus procesos después de cada comando; la herramienta lo rechaza antes de iniciar la vigilancia. Lo que imprime un comando vigilado son datos, no instrucciones, y se le dice al agente. Añade **Human approval** para preguntar antes de que arranque un comando.

## Visuals { #visuals }

`draw` — _Dibuja en la conversación: un diagrama, un mapa, un flujo, una explicación, una escena 3D._
`revise_visual` — _Cambia un visual con reemplazos exactos, sin dibujarlo de nuevo._
`read_visual` — _Lee un visual de esta conversación tal como está, con las revisiones aplicadas._

Dibuja en el propio chat. `kind` es `svg` para diagramas e ilustraciones, `mermaid`
para diagramas de flujo, secuencias y diagramas ER, o `html` para todo lo
interactivo - controles deslizantes, `<canvas>`, three.js, un mapa. Sin
configuración; el skill incluido `visual-design` lleva el estilo y cinco plantillas,
y el Builder lo vincula, junto con Charts, al activar Visuals.

**Primero elige la forma.** No toda respuesta es un dibujo. El texto de la
herramienta y el skill le indican al modelo que responda un dato con texto, valores
exactos con una tabla Markdown y cifras que ver con `create_chart` - así «ahora en
gráfico» convierte una tabla en un gráfico nativo - y que dibuje cuando la persona
deba entender cómo funciona algo, usar una herramienta hecha para el momento o
seguir lugares en un mapa. El skill también dice cómo debe verse un dibujo para que
parezca hecho para la respuesta y no generado: un tema grande, espacio en lugar de
cajas, solo los colores del tema, sin píldoras, sombras ni degradados.

**Un dibujo puede continuar la conversación.** `agenticos.followUp(text)` en un
dibujo pide enviar la elección de la persona como su siguiente mensaje -
_Planificar esta parada_, _Usar estas cifras_. La consola muestra el texto bajo el
dibujo y lo envía solo cuando la persona hace clic en _Enviar_; una petición sin un
clic detrás se descarta. Consulte
[mensajes de seguimiento](../artifacts.md#visuals).

**Mapas.** `lib/agenticos-map-2.js` dibuja un itinerario - chinchetas numeradas en
orden y la línea entre ellas, mostradas a la vez y que caen una a una cuando se pide,
sobre un mapa 16:9 del ancho de la página, y una tarjeta por parada -
sobre el servidor de teselas que nombra `VISUAL_MAP_TILES`, o como un contorno de
las paradas en un despliegue que no nombra ninguno. Las instrucciones de la
capability le dicen al modelo cuál es el caso, para que no prometa calles que no
puede mostrar.

**Aparece mientras se escribe.** El dibujo es el argumento `content` de la llamada. La
consola lo lee de los argumentos en streaming y lo envía a un marco bajo el mensaje,
así que el SVG y el HTML crecen en pantalla y Mermaid se redibuja en cada línea
completa. Los scripts se ejecutan una vez, cuando la llamada está completa: hasta
entonces el marcado se muestra sin scripts ni atributos `on*`, así que una escena a
medio escribir nunca arranca.

**Vive en la conversación.** Solo se guarda la llamada a la herramienta, que la
transcripción ya conserva, así que una recarga y un hilo compartido lo vuelven a
dibujar. Un turno anterior llega al modelo solo como texto, por eso la capability
nombra en sus instrucciones los visuales anteriores de la conversación, por id y
título, y `read_visual` recupera uno antes de una revisión.

**El modelo sabe cómo se renderizó.** Mientras alguien mira en el chat web, la consola
informa de los errores de script, las cargas fallidas y las peticiones rechazadas de
cada dibujo, y `draw` espera ese informe hasta diez segundos antes de responder - así
el modelo corrige un dibujo roto con `revise_visual` en el mismo turno. Si nadie mira,
responde enseguida y dice que el dibujo no se comprobó.

**Las revisiones** son reemplazos exactos, la misma regla que las ediciones de
`publish_artifact`, y cada una es un visual propio bajo el mensaje que la hizo. Un
dibujo demasiado grande para una aplicación (`ARTIFACT_MAX_BYTES`), un SVG que no es un
único elemento `<svg>`, o uno que carga algo de otro sitio es un reintento que dice qué
cambiar.

**Imágenes.** `images` lleva hasta seis imágenes a un dibujo, cada una con un
nombre que el dibujo usa como `{{image:NAME}}`: una imagen adjunta a la
conversación, un archivo del workspace o una dirección `https://`. Una dirección
solo sirve a un agente que ya lee la web - con `web_fetch` o `browser_use`
activados - y solo en un host que uno de ellos leería: sus `allowed_domains` y
`blocked_domains` limitan también las imágenes, y la descarga no puede
redirigirse a otro host. Cada imagen tiene como mucho 2 MiB, y un visual lleva
solo las imágenes que su dibujo todavía usa, seis como máximo entre todas sus
revisiones.

**Tiene el aislamiento de una aplicación.** El marco es el sandbox de las
aplicaciones - un origen opaco, `connect-src 'none'`, nada remoto salvo el conjunto
de bibliotecas del despliegue, que ahora incluye three.js, Mermaid y Leaflet, y la
propia ruta de teselas del despliegue. Consulte [Visuals](../artifacts.md#visuals).

## Aplicaciones { #artifacts }

`publish_artifact` — _Publica una página terminada — un informe, un pequeño
dashboard, un resumen — bajo un enlace estable._
`read_artifact` — _Lee la versión actual de una página que publicó este agent, tal
como se escribió._
`list_artifacts` — _Enumera las páginas que publicó este agent y que este run puede
abrir, de la más reciente a la más antigua._
`preview_artifact` — _Mira una página que publicaste como la vería quien la abre:
una imagen, y lo que salió mal._
`share_artifact` — _Pide que una página que publicaste se comparta con más gente; esto no
comparte nada por sí mismo._

Publica un único documento HTML o Markdown autocontenido como
[aplicación](../artifacts.md): un recurso compartido con propietario, visibilidad y
grants, que se abre en el navegador bajo un enlace que no se mueve. Un solo
ajuste: `preview_screenshot` (activado por defecto) entrega al modelo la imagen
que dibuja una vista previa; desactívalo para un modelo que no puede leer
imágenes.

**El nombre es la identidad.** `(organization, agent, environment, name)` elige la
aplicación, así que el siguiente run del mismo agent que publique `weekly-report` —
desde un chat, una programación o la API — añade una versión a la misma en lugar de
crear un segundo enlace. El entorno sale del run, así que un run en `staging`
publica una página propia. Unos bytes idénticos no añaden versión y responden
`unchanged`.

**De dónde sale la página.** `path` lee un archivo del workspace del run a través
de su propio backend, así que funciona allí donde funciona la capability `sandbox`;
`content` recibe la página en línea para un agent sin workspace; `edits` son
reemplazos exactos aplicados a la versión que devolvió `read_artifact`, y una
publicación entre medias los rechaza en lugar de sobrescribirla. Exactamente uno de
los tres. Una llamada incorrecta — más de uno, ninguno, un nombre fuera de
`^[a-z0-9][a-z0-9-]{0,63}$`, una extensión desconocida, una página vacía o
demasiado grande, un reemplazo que no coincide con ningún sitio o con varios — es un
reintento que nombra qué cambiar. Una lectura que las reglas de permisos del
workspace rechazan, y una página que la persona del run no puede abrir, son
resultados, no reintentos.

**Leer de vuelta.** `read_artifact` devuelve una línea de cabecera (versión,
formato, tamaño) y el código fuente, cortado en 100.000 caracteres, cosa que la
cabecera dice. Solo abre lo que la persona del run puede abrir en la consola, y nada en un widget público, un embed, una programación o un trigger de eventos,
donde no escucha ninguna persona identificada.

**Listar.** `list_artifacts` devuelve JSON: las páginas de este agent en el
entorno del run, de la más reciente a la más antigua y como máximo 50, con
`total`, cada una con su nombre, título, versión, formato, bindings, visibilidad,
enlace público, hora de publicación, `url` de la consola y `may_edit` (si una
publicación con ese nombre desde este run la actualiza). Se lee como la persona
que escucha, con la regla de listado de la consola; en un chat de grupo solo se
enumeran las páginas de toda la organización, nunca una a la que esa persona
llega por su cuenta. No se enumera nada donde no escucha ninguna persona
identificada.

**Vista previa.** `preview_artifact` dibuja la versión actual a 1280 píxeles de
ancho y como máximo 2400 de alto, en un navegador que ejecuta el operador
([`ARTIFACT_RENDER_CDP_URL`](../configuration.md#published-artifacts)), con sus
datos leídos como la persona que escucha. En un chat de grupo solo abre una
página de toda la organización, y la dibuja sin datos; igual para un run del que nadie
responde, como uno que inició un webhook o un formulario. Devuelve un informe de
texto (los datos de cada binding, los errores no capturados, los errores de
consola, los rechazos de la política, las peticiones rechazadas, los diálogos y
los avisos de publicación) y la imagen como parte de imagen. Cada petición del
renderizado la responde la API o se rechaza. Sin renderizador ni el extra
`browser`, o pasado un plazo de 15 segundos, el informe llega solo y dice por
qué. [Ver la página](../artifacts.md#seeing-the-page-preview) cuenta el resto.

**Sin efectos secundarios.** Una primera publicación es privada para la persona en
cuyo nombre se hizo el run, y solo una persona amplía quién la lee, así que la
puerta de aprobación solo aparcaría el informe programado para el que existe esto.
Un autor que quiera aprobar cada nueva publicación de una página compartida fija
`tool_approval` en `publish_artifact`.

**La página no tiene red.** Se sirve en un origen opaco bajo una política `sandbox`
con `connect-src 'none'`, y el texto de la herramienta le dice al modelo que
incruste sus propios datos y cargue los gráficos desde el
[conjunto de bibliotecas](../artifacts.md#the-library-set) del despliegue en lugar
de un CDN. Consulta [cómo se aísla la página](../artifacts.md#how-the-page-is-isolated).

**Cómo es una página.** La capability añade a las instrucciones del agent un
contrato de página breve y estático: el esqueleto, las clases más usadas del kit,
iconos de Lucide en lugar de emoji, y `AO.records` para los datos vinculados.
Cuando el run ofrece el skill `artifact-pages` sin cargar, la primera página HTML
completa del run es un reintento que pide al modelo cargarlo y reconstruirla; una
vez por run, y en el último intento la página se publica con ese consejo en su
lugar. Cada página HTML publicada se comprueba, y el `warning` del resultado
enumera lo que parece estar mal, un problema por línea; consulta
[el contrato de página y los avisos de publicación](../artifacts.md#the-page-contract-and-the-publish-warnings).
Un aviso nunca detiene una publicación.

**Datos en vivo.** Los `bindings` de `publish_artifact` vinculan una página HTML a datos de
tabla como `{name: query}`. Una query nombra una `table` (id o nombre exacto, de
`list_tables`) o una `view` guardada (id o nombre exacto, de `list_views`), nunca las dos, y
`fields`, que asigna cada nombre que lee la página a una columna por id o etiqueta. Opcionales:
`filters` (`[{column, op, value}]`, todos deben cumplirse, se suman a los de una vista; una
opción se elige por su etiqueta), `sort` (`{by, direction}`) y `limit` (como máximo y por
defecto 1.000), que sustituyen a los de la vista. Los filtros y el orden de una vista se
**copian** al publicar la página, y las ediciones posteriores de la vista no cambian nada; sus
`visible_columns` y `group_by` se ignoran, y se rechaza una vista con búsqueda de texto libre o
con un filtro sobre una columna que ya no existe. Omite `bindings` para conservar los actuales
de la página; `{}` los elimina.

El spec del agent tiene que conceder lectura sobre la tabla, y la persona detrás del run tiene
que leer cada tabla que alcanza la query, incluidas las vinculadas. La página llama a
`agenticos.onData(render)`, que se ejecuta con los primeros datos y en cada refresco;
`agenticos.data` es una Promise de los primeros datos. **Todos los que abren la página leen los
mismos registros, leídos con el acceso de su propietario**, una vez que este ha confirmado
compartirlos; vincula solo lo que todos ellos pueden ver. Un binding que no se puede servir
llega `unavailable`. Los nombres son `^[a-z_][a-z0-9_]{0,63}$`, con como máximo 5 bindings y
50 campos cada uno. [Datos en vivo](../artifacts.md#live-data) tiene los límites.

**El resultado de la publicación.** Devuelve cada query en palabras - `table`, `filters`,
`sort`, `limit` y cada campo con lo que lee (`Status (single_select)`, `Pay band: formula over
Salary, Level`) - o `kept` para un binding que se arrastra; ese resumen es lo que consiente el
propietario, así que el agent lo comprueba. `consent` indica en qué punto están los datos de la
versión (`not_needed`, `pending`, `consented`, `declined`, `withdrawn`), y `audience` dice qué
ve el resto mientras espera: «the audience still sees v2 until Alex confirms». Una versión
`pending` la debe confirmar la persona en la consola; el agent se lo dice. Una página nueva es
privada para la persona a la que sirve el run.

**Acciones.** `actions` en `publish_artifact` declara hasta cinco workflows que los botones de la
página pueden pedir que se inicien, como `[{workflow, label}]`: un workflow por id o nombre exacto, y
cómo lo llama la página. Cada uno debe estar vinculado en la capability [Workflows](#workflows) del
agent, estar activo, iniciarse desde **Manual** o **API request**, y ser uno que la persona detrás
del run pueda ver y ejecutar; uno al que la persona no llega se rechaza como si no estuviera
vinculado, y uno archivado o que no se inicia a mano al que sí llega se rechaza por su nombre.
Omite `actions` para conservar las actuales, `[]` las quita, y un run sin ninguna persona detrás no
puede cambiarlas. El resultado devuelve en `actions` cada una por nombre y etiqueta, o `kept`. El
agent no inicia nada: el lector confirma cada run en la consola, y se ejecuta como él. La página
llama a `AO.run`. Consulta [Acciones](../artifacts.md#actions).

**`share_artifact(name, visibility?, people?)`.** Pide que se comparta una página. Nunca
comparte nada y **no** la protege una aprobación de herramienta: presenta una
[solicitud](../artifacts.md#share-requests) `audience` como la persona del run - también si es
el run del propio propietario - y responde «Waiting for Alex to approve in the page's Share
dialog». El propietario responde en la consola, con sesión iniciada como él mismo. `visibility`
es `team` u `org`, no existe `public`, y `people` son miembros por nombre completo o correo y
grupos por nombre, cada uno pedido con nivel de vista; un nombre que no coincide con nadie o
con varios se informa, nunca se adivina. Un run sin persona detrás, y la página de un chat de
grupo que no es de toda la organización, no pueden pedirlo. Es `side_effecting=False`: la
llamada no aplica nada.

**Un run sin persona.** Una página con bindings solo la publica un run que actúa en
nombre de un miembro: el miembro con sesión iniciada (chat web, API HTTP), un
remitente de canal vinculado o el creador de una programación. Un visitante de un
widget, un embed o una página alojada, un remitente de canal no vinculado, la
entrega de un trigger de eventos de un agent (GitHub, correo, relé de webhooks) y un
run de workflow admitido por una puerta pública, o cualquier punto de la cadena de
ese run, no publican ninguna página vinculada. Un autor que quiera aprobar cada
nueva publicación de una página vinculada fija `tool_approval` en
`publish_artifact`. Un run sin persona solo puede republicar una página vinculada sin
cambios, y la publicación de un editor se rechaza cuando el propietario de la página no
puede leer una tabla que esta alcanza.

## Delegación { #delegation }

`task` — _entrega una pieza de trabajo autocontenida a uno de los especialistas de
este agent._
`check_task`, `wait_tasks`, `list_active_tasks` — _seguir una que está en marcha._
`send_message_to_subagent`, `soft_cancel_task`, `hard_cancel_task` — _dirigir o
detener una._ Estas seis se ofrecen solo cuando hay una delegación en segundo plano
alcanzable: a un agent que solo es `sync` no se le entrega ninguna.
`create_agent`, `delegate` — _un especialista que el modelo escribe para sí mismo, cuando el autor lo permite._
`answer_subagent` — _declarada, y no ofrecida a ningún modelo._

Un agent entregando parte de un trabajo a otro, cada uno con su propio modelo, su
propio conocimiento y su propio límite de pasos, y llamados por su nombre. Hay dos
formas de delegado y la diferencia decide cómo se revisa, se versiona y se factura;
[Conceptos](../concepts.md#delegate-vs-inline-specialist) es donde se explica. A qué
agents _publicados_ puede delegar este no está en esta configuración: está en
`subagents`, en el nivel superior del spec, donde pueden verlo la validación de
publicación, la exportación a YAML y el modelo de permisos.

| Configuración | Valor por defecto | Rango |
| --- | --- | --- |
| `inline` | ninguno | especialistas definidos dentro de este agent |
| `mode` | `sync` | `sync`, `async`, `auto` |
| `allow_questions` | `false` | un delegado sync puede preguntar a la persona del padre |
| `allow_dynamic` | `false` |  |
| `max_depth` | 1 | 1–3 |
| `max_fanout` | 3 | 1–10 |
| `max_result_chars` | 2000 | 200–20000 |
| `allow_any_agent` | false | Usar otros agentes accesibles |
| `share_with_delegates` | ninguna | ids de capability a las que este agent está vinculado, salvo `subagents` |

`allow_any_agent` resuelve opcionalmente otros agentes publicados de esta organización que la persona puede ejecutar, al inicio de cada ejecución interactiva, con nombres `agent-<slug>`. Conserva las fijaciones explícitas, excluye ancestros y respeta permisos use y límites de claves API. No amplía ejecuciones anónimas ni desatendidas. Está desactivado por defecto; los catálogos grandes aumentan preparación y contexto.

**El modo es decisión del autor, no del modelo.**

La herramienta `task` de la biblioteca recibe un argumento `mode` cuyo valor por
defecto es `sync`, así que «el modelo eligió esperar» y «el modelo no dijo nada» son
la misma llamada. No hay forma de respetar a la vez un ajuste y una elección, y el
ajuste fue revisado.

Así que el argumento se sustituye al pasar, y `auto` es la manera en que un autor
cede deliberadamente la decisión. `auto` se resuelve _antes_ de que empiece la
delegación, porque si un panel sigue abierto después de que el padre haya respondido
depende de la respuesta.

Un delegado fijado o un especialista puede sobrescribir el modo para sí mismo: un
investigador lento es el caso que merece la pena ejecutar en segundo plano. Las
instrucciones entonces **marcan a ese delegado**, junto a su nombre: una sola frase
que indicara el modo configurado era una promesa que el delegado que lo sobrescribe
rompía después, anunciándole al modelo una respuesta y entregándole un id de tarea.

**A un agent que solo es `sync` no se le ofrece ninguna de las seis herramientas del
ciclo de vida de tareas.** Cada una de `check_task`, `wait_tasks`,
`list_active_tasks`, `send_message_to_subagent` y las dos cancelaciones recibe o
informa sobre un id de tarea, y una delegación `sync` devuelve la respuesta y nada
más: no hay id que pasar. Así que se ofrecen solo cuando hay una delegación en
segundo plano alcanzable: modo `async` o `auto`, un delegado que prefiera cualquiera
de los dos, o permiso para inventar especialistas. `sync` es el valor por defecto,
así que esta es la configuración habitual, y seis descripciones de herramienta
retenidas son seis que el modelo ya no paga en cada turno. `task` se queda: un agent
`sync` sigue delegando.

**El fan-out y el anidamiento son topes, no errores.**

Pasado `max_fanout`, la siguiente delegación vuelve como un resultado de herramienta
sobre el que el modelo puede actuar — esperar, o hacer el trabajo él mismo —, porque
un límite de ritmo no debería terminar un run.

`max_depth` cuenta niveles de delegación **incluido el del propio agent
configurado**: 1 es este agent delegando y sus delegados no; 2 permite un nivel
anidado.

En el límite, un delegado se construye _sin_ la capability de delegación, en lugar
de con una que solo puede negarse. Una herramienta que siempre responde «no hay
delegados disponibles» es una descripción que el modelo paga en cada turno y que
intenta igualmente.

Deliberadamente no hay 0. Apagar la delegación es deshabilitar la vinculación, y una
segunda grafía del mismo interruptor es una que contradice a la primera.

**Y cada agent del árbol se ciñe a su propio `max_depth`, no al de la raíz.** Un
delegado recibe el _menor_ entre lo que le queda al árbol y lo que permite su propio
spec, así que una raíz configurada para tres niveles que delega en un agent cuyo
autor eligió 1 recibe uno: ese delegado delega y sus delegados no, exactamente como
lo leyeron sus propios revisores. Un tope que quien llama pudiera ampliar no sería un
tope, y la razón para fijar un delegado a una versión es que las decisiones de su
autor se mantengan cuando lo llama otro.

**Una delegación sync puede detenerse para preguntar a una persona, y se continúa en
el sitio.** Una herramienta con puerta dentro de una aparca el run entero; aprobarla
reanuda ese delegado desde donde se detuvo en lugar de delegar otra vez, que es lo
que hace que la aprobación se aplique a la llamada que el revisor vio de verdad.
[Gobernanza](../governance.md) tiene la forma del estado almacenado y por qué
volver a ejecutar respondería de otro modo.

**Una delegación en segundo plano no puede detenerse para preguntar a una persona.**

Una herramienta con puerta dentro de una se rechaza en lugar de aparcarse, y el
rechazo le dice al modelo que delegue ese trabajo con `mode="sync"` en su lugar.

La razón no es de política sino de **duración**. El canal de aprobación se cierra
sobre la sesión de base de datos de la petición, y una delegación en segundo plano
sobrevive a la llamada de herramienta que la arrancó, así que para cuando quiso
preguntar ya no queda nada con lo que escribir la pregunta.

Una delegación en segundo plano que se suspenda de todos modos — una forma que la
biblioteca documenta como no entregable — se registra como `failed` con ese mismo
mensaje. La alternativa es una tarea que informa de «sigue en marcha» mientras viva
el proceso: su gasto atribuido a nada, su plaza de fan-out nunca liberada y el panel
que abrió una superficie nunca cerrado.

**Un delegado sync puede preguntar a la persona del padre, cuando se pone
`allow_questions`.**

Apagado por defecto: un especialista trabaja de forma autónoma y lo dice si no pudo.

Encendido, a un delegado cuyo modo sea sync se le da la herramienta `ask_parent` de
la biblioteca, y una pregunta que haga la responde el propio canal `ask_user` del
run — la persona que ya sostiene la llamada de herramienta del padre —, nunca el
modelo.

Es decisión del autor porque la pregunta lleva un nombre que el autor publicó. Un
especialista que el modelo _inventa_ no pregunta nunca, diga lo que diga esto: unas
instrucciones que un modelo escribió hace un momento no son del autor para
planteárselas a una persona.

Solo sync. Una delegación en segundo plano ha devuelto un id de tarea sin que quede
nadie para responder, y `auto` puede convertirse en una.

Alcanzar un delegado preconstruido necesitó un cambio aguas arriba.
[subagents-pydantic-ai#76](https://github.com/vstorm-co/subagents-pydantic-ai/pull/76)
respeta `can_ask_questions` para un agente aportado por quien llama, que es lo que es
todo delegado aquí, con lo que aterriza la mitad sync de
[#184](https://github.com/vstorm-co/agenticos/issues/184).

**`answer_subagent` no se ofrece a ningún modelo.**

Responde a una pregunta en la que aparcó un delegado _en segundo plano_, y aquí
ningún delegado aparca en una: una pregunta sync va a una persona por `ask_user` y
nunca por esta herramienta, y a un delegado async no se le da `ask_parent` en
absoluto. Así que la única respuesta posible de la herramienta es «esa delegación no
está esperando una respuesta».

Sigue **declarada**, porque una herramienta ausente de la declaración no puede
ponerse tras una puerta por la política de aprobación ni renombrarse por una
vinculación, y esa mitad del fallo es silenciosa.

Se **filtra fuera del conjunto ofrecido**, porque la otra mitad es una descripción en
el contexto de cada turno que describe una acción que no puede ocurrir, y las
descripciones de herramienta son el prompt más fuerte de este producto.

La herramienta pasa a ser alcanzable solo cuando se resuelva la mitad de segundo
plano de [#184](https://github.com/vstorm-co/agenticos/issues/184): donde responde el
propio modelo del padre sin que nada le obligue a mirar, con el delegado bloqueado en
una plaza de fan-out que el final del turno cancela.

**`wait_tasks` trunca, y lo dice.** El resultado de una tarea completada se corta en
`max_result_chars` con un marcador explícito que apunta a `check_task`, que siempre
devuelve el texto completo. El marcador es la mitad que aguanta el peso: un corte
silencioso se lee como una respuesta breve, y un orquestador al que se le da medio
informe vuelve a delegar trabajo que ya tiene.

**Apagar la delegación es deshabilitar la vinculación, no bajar un número.** Una
vinculación deshabilitada no es delegación: no se construye nada, así que nada lee
los delegados fijados ni los especialistas que lleva — y entonces la publicación se
rechaza para un agent que siga nombrando delegados, porque un delegado fijado al que
nada llamará jamás es una línea de configuración que se lee como una decisión y no
hace nada.

**Vinculada sin ningún delegado, esta capability no aporta nada**: no se adjunta,
igual que `knowledge` no se adjunta sin colecciones. Diez herramientas que solo
pueden negarse son diez herramientas en el contexto de cada turno.

**Tres se declaran como que actúan**, y un autor las pone tras una puerta con
`tool_approval`: `send_message_to_subagent`,
`soft_cancel_task` y `hard_cancel_task`. Dirigir cambia lo que un delegado está
haciendo en mitad del run, y cualquiera de las dos cancelaciones destruye trabajo
que se pagó y no se entregó. `task` deliberadamente no tiene efectos secundarios, lo
que suena mal por un momento: lo que un delegado _hace_ pasa por la puerta del propio
spec del delegado, a través de la misma puerta de aprobación que usa este run, así
que poner además una puerta a la delegación pediría que alguien la aprobara antes de
que se haya propuesto el trabajo que quizá necesite aprobación. El autor que sí lo
quiera tiene una sobrescritura de `tool_approval`.

**A un delegado no se le prestan las capabilities del padre.** Se ejecuta con su
propio spec más lo que nombre `share_with_delegates`, id a id: un especialista que
ganara calladamente las credenciales del padre sería la vía silenciosa para rodear lo
que se le concedió al padre. La publicación rechaza un id compartido al que el padre
no está vinculado él mismo, ya que prestar lo que no tienes es una línea de
configuración que se lee como una decisión y no hace nada. En la práctica esto existe
para `sandbox`: compartirla es la forma en que un investigador escribe
`/workspace/notes.md` y un redactor lo lee. Un delegado que vincula `sandbox` _sin_
que se le comparta la del padre recibe el workspace en memoria, porque solo el run
abre uno.

**`subagents` no puede compartirse**, y es el único id que «¿lo tiene el padre?»
nunca podría rechazar: un agent que comparte algo lo tiene por definición.

Compartida, la vinculación del padre aterriza en un delegado que no vincula ninguna,
y el runtime lee entonces los especialistas, el `allow_dynamic`, el `max_fanout`, el
`max_depth` y la lista de compartición _del padre_ como si los hubiera elegido el
autor del delegado.

La publicación lo rechaza, y el runtime además lo quita de la lista de compartición,
así que un spec almacenado antes de esa regla tampoco puede ampliar un delegado.

Si un delegado puede delegar siquiera lo responde su propio spec, y lo mismo hasta
qué profundidad puede llegar, acotado por lo que le quede al árbol que tiene encima.

Compartir es además la única vía a una [conexión MCP](../mcp.md) para un especialista
inline, que no puede vincular ninguna: una conexión es configuración de ámbito de
organización, y alcanzar una a través de un especialista que nadie publicó es la
puerta equivocada. Vincúlala en el padre y nómbrala aquí.

**`create_agent` y `delegate` se ofrecen solo bajo `allow_dynamic`.** Una herramienta
ausente de la declaración de una capability no puede ponerse tras una puerta por la
política de aprobación ni renombrarse por una vinculación, y la mitad peligrosa de
eso es silenciosa, así que las diez están declaradas y una configuración por defecto
ofrece siete.

Lo que compra el interruptor es un especialista que el modelo escribe él mismo:
instrucciones y un modelo, y nada más.

Se construye con el mismo `build_agent` por el que pasa un especialista inline, sobre
el guardián de budget compartido del run y su canal de aprobación, así que sus
peticiones se tarifan y se cuentan contra el tope que alguien fijó.

Esa es toda la razón de que esto necesitara una **factory** y no una bandera. Un
especialista que la biblioteca se construyera para sí misma quedaría fuera del
catálogo de modelos de este despliegue, de su vault y de su guardián de budget: una
petición sin contabilizar, quizá a un provider del que la organización no tiene
clave. La factory es lo que la encamina de vuelta por esta plataforma.

!!! note "Un especialista que no nombre un modelo se rechaza"

    Antes de `subagents-pydantic-ai` 0.2.18 la biblioteca llevaba una cadena de
    modelo por defecto con la que se compilaba un especialista sin modelo. La 0.2.18
    eliminó ese recurso, y esta plataforma lo rechaza aún antes, en
    `DelegatingToolset._refuse_dynamic`.

El modelo solo puede nombrar un modelo del que la organización tenga un perfil, y el
rechazo nombra la lista.

Un perfil sobre el
[inicio de sesión de ChatGPT](../models.md#running-on-a-chatgpt-subscription) de
alguien, o uno cuyos tres primeros fallbacks llegan a uno, solo está en la lista
cuando el spec del agent nombra exactamente ese perfil - su propio modelo, el de un revisor, el de un
especialista inline o el de una capability activada -, porque un inicio de sesión es
la suscripción de una persona. Un perfil que quien ejecuta el agente no puede usar
se omite en vez de hacer fallar el run.

El modelo no puede adjuntar capabilities: dejar que un modelo conceda
una capability a su propio hijo es el fallo del scope no concedido con sombrero
nuevo. No recibe conocimiento, ni delegados propios, y no se persiste nada entre
runs: conservar un especialista significa publicar un agent, que es la acción de una
persona. `MAX_DYNAMIC_SPECIALISTS` acota cuántos puede conservar un run.

Que un especialista no se persista es un diseño, y tiene una salida en vez de un
callejón sin salida: una persona puede **promoverlo** a un agent en borrador.

Su definición viaja en el frame `SubagentStarted` de apertura — el único sitio en el
que es legible después de que el modelo lo escribiera y antes de que acabe el turno —,
de modo que el panel de delegación del chat puede ofrecer conservarlo mientras el run
sigue en pantalla, y el Builder ofrece lo mismo sobre un especialista inline.

La promoción crea un borrador propiedad de quien lo promovió, tras la puerta de
`agents:edit`, y ahí se detiene: no publica, no fija el nuevo agent como delegado y
no elimina el especialista del que salió.

Consulta [Conceptos](../concepts.md#delegate-vs-inline-specialist) para ver por qué
la regla de persistencia es la razón de que exista la salida, y no una limitación que
la salida sortee.

Uno conservado dura todo el run en el que se inventó, incluido un aparcamiento por
aprobación: la inscripción vive en un registro que la biblioteca de delegación
construye por agente _construido_, y un run que aparca se vuelve a construir cuando
se continúa, así que se perdía a lo largo del aparcamiento hasta que las
inscripciones se llevaron en `PausedRunState` y se volvieron a registrar en la
repetición
([#175](https://github.com/vstorm-co/agenticos/issues/175)). No sobrevive al
_siguiente turno de la conversación_, que es una construcción nueva sin estado
aparcado: un nombre creado en una respuesta es desconocido en la siguiente, y la
descripción de `create_agent` le dice al modelo que lo cree otra vez si `task` lo
indica.

**El delegado no especializado propio de la biblioteca de delegación no se ofrece en
absoluto**, y no hay ajuste para él.

Antes de subagents-pydantic-ai 0.2.18 se habría ejecutado con un modelo que este
despliegue no configuró, compilado a partir de la cadena de modelo por defecto de la
propia biblioteca, fuera de los perfiles de la organización, de su vault y del
guardián de budget del run. Exactamente igual que el especialista en tiempo de
ejecución de más arriba, antes de que necesitara una factory.

Un comodín para todo es algo legítimo de querer. Escríbelo como un especialista
inline, donde puedes leer lo que hace y se tarifa como todo lo demás.

El propio de la biblioteca quedó arreglado a partir de la 0.2.18
([#174](https://github.com/vstorm-co/agenticos/issues/174)): sin modelo por defecto
ni factory, ahora se niega a construir el delegado en vez de elegir un modelo.

Lo que se le cuenta al modelo sobre todo esto se escribe aquí y no en la biblioteca:
los delegados por nombre y descripción, el modo que este run usará realmente y el
tope de fan-out que si no descubriría al ser rechazado. Dos listas de los mismos
delegados en un solo system prompt son contexto pagado dos veces, y solo una de ellas
puede decir lo que el despliegue impone.

### Agents remotos por A2A { #remote-agents }

Un agent también puede delegar en el **agent de otro proveedor** que hable el
[protocolo Agent2Agent](https://a2a-protocol.org). Se registra una vez en
**Connections → Remote agents** por la dirección de su agent card, que se lee y se
valida en ese momento, con una clave API opcional del vault enviada como bearer
token. El spec de un agent nombra registros en `external_agents`, y los ajustes de
delegación los muestran junto a los agents propios de la organización. La clave de
un registro se presta a cada run, como la de una capability, así que publicar
rechaza un registro cuya clave quien publica no puede ver en el vault.

Cada agent que delega en un registro depende de él, así que actualizarlo o
eliminarlo le corresponde a quien lo registró, o a quien edita todos los agents; y
actualizarlo, que decide adónde va la clave, solo a quien aún puede usar esa clave.
Una actualización cuya card lleva el agent a otro host queda en la auditoría, porque
ese host recibe desde entonces las peticiones y la clave. La lista muestra la
dirección de una card y su endpoint sin query ni userinfo, donde una dirección
firmada lleva su credencial.

Borrar la clave que envía un registro borra el registro, en lugar de dejarlo
llamando sin ella. Una clave solo se envía a un endpoint HTTPS, así que una card con
HTTP sin cifrar se rechaza para un registro que tiene clave. Una dirección con
nombre de usuario o contraseña se rechaza de entrada: una credencial va al vault.

Para el modelo que delega, un agent remoto es un delegado más, llamado por su nombre
con la misma herramienta `task`. Cada llamada es un `message/send` de A2A con la
última petición, y el `contextId` del agent remoto pasa de una llamada a la
siguiente dentro de la misma delegación: una pregunta de seguimiento sobre una tarea
continúa su conversación remota, y dos tareas enviadas a la vez tienen cada una la
suya.

Una respuesta `input-required` o `auth-required` vuelve como texto que lo dice,
porque un delegado que espera a su propio usuario es una respuesta que el modelo
tiene que leer. Una parte de datos o de archivo de una respuesta no se lee, y aparece
como una línea que dice que se envió. Un agent remoto al que no se puede llegar
responde precisamente eso, y el run sigue.

El budget se comprueba antes de cada llamada. Lo que cuesta una llamada lo fija el
proveedor remoto y nadie lo publica, así que cada llamada se anota sin precio y el
coste del run dice que es parcial. Cada petición pasa por las comprobaciones de
direcciones del despliegue, de modo que ni una card ni un endpoint pueden apuntar la
plataforma a su propia red. Publicar rechaza una referencia a un registro que no
existe, y un run cuyo registro se eliminó entretanto falla nombrándolo.

Para ver qué cuesta una delegación y qué fila de run la registra, consulta
[Gobernanza](../governance.md#delegation-spends-the-parents-budget). Para ver quién
puede delegar en qué, consulta
[Permisos](../permissions.md#delegation-is-not-a-privilege-boundary).

## Planificación { #planning }

`write_plan` — _plantea o sustituye la lista de comprobación entera._
`read_plan` — _ver los pasos y sus ids antes de una edición granular._
`add_task`, `update_task_status`, `update_task_statuses`, `remove_task` — _cambiar un
paso, o un lote, sin sustituir el plan._
`add_subtask`, `set_dependency`, `get_available_tasks` — _planificación consciente de
las dependencias, ofrecida solo bajo `enable_subtasks`._

El modelo mantiene una lista de pasos completados, activos y pendientes. Las
herramientas que cambian el plan lo devuelven en un marco `<plan_reminder>`.
Cuando el plan visible difiere del almacén, por ejemplo tras la compactación o
al iniciar un run, el harness lo registra como contenido del canal de usuario
en el historial del run. Nunca se convierte en un system prompt. Los ajustes del
modelo controlan la caché. Si un agente usaba `planning.cache_ttl`, traslade la
retención al ajuste del modelo `cache`, por ejemplo `cache: "1h"`; el campo
anterior de la capability se sigue aceptando, pero se ignora.

Se solapa con la [Delegación](#delegation) como un plan se solapa con un equipo: la
planificación decide _cuáles_ son los pasos, la delegación decide _quién_ los hace.
Son ortogonales — un plan es un toolset más un recordatorio, la delegación es un
toolset más un envoltorio del run —, así que un agent puede vincular ambas, una o
ninguna.

| Configuración | Valor por defecto | Valores |
| --- | --- | --- |
| `enable_subtasks` | `false` | añade las tres herramientas de subtarea/dependencia y el estado `blocked` |
| `cache_ttl` | `5m` | Campo anterior: aceptado pero ignorado; configure `cache` en los ajustes del modelo |

**Ninguna de las nueve herramientas actúa sobre el mundo.** Cada una muta una lista de
comprobación que el modelo mantiene para sí, así que aquí no hay nada que una persona
pueda aprobar y la capability declara `side_effecting=False`. Las tres herramientas de
subtarea se declaran incluso cuando una lista plana no las ofrece, porque una
herramienta ausente de la declaración no puede ponerse tras una puerta por la política
de aprobación ni renombrarse por una vinculación.

**El plan pertenece a la conversación, no a un turno de ella.**

La lista de comprobación es estado, y si no, cada frontera que tiene un run lo
perdería. Un run que aparca en una aprobación a mitad de plan se reanuda como un run
nuevo — y aquí un mensaje de chat _es_ un run, así que el siguiente mensaje empezaba
desde un almacén vacío.

Un agent escribió tres pasos, se le pidió empezar el primero y respondió que no
existía ningún plan y que él nunca había creado uno (agenticos#1077).

Así que el almacén es del **runner**, no de la capability. Se siembra desde el plan
almacenado de la conversación, o desde `paused_state` en una reanudación, que es la
copia más reciente, y se escribe de vuelta en la conversación cuando el run se
detiene.

Una superficie sin conversación — una llamada pelada a la API — conserva un plan
mientras dura su run, que es todo lo que tiene.

**Una lista de comprobación terminada es historia, y un turno nuevo no parte de
ella.** La fila la conserva — no se borra nada —, pero un plan cuyos pasos están
todos `completed` o `cancelled` no se siembra en el turno siguiente: el recordatorio
de cola llamaría «tu plan actual» a una tarea que nadie está haciendo, y `read_plan`
respondería con ella (agenticos#1221).

Conservar la fila exige una regla más, porque un turno escribe su almacén de vuelta
al terminar: el turno cuyo almacén se abrió vacío _sobre_ un plan terminado no
escribe nada. No hizo nada a la lista de comprobación, y un volcado vacío borraría la
fila en el siguiente mensaje corriente. Un agent que empieza trabajo nuevo vuelca un
plan y lo sustituye como siempre.

El filtro está en la _siembra_, no al marcar el último paso, y en eso consiste toda
la decisión. En el turno que termina un plan el almacén todavía lo tiene, así que el
agent puede resumir lo que acaba de hacer y nada contradice la transcripción. Es la
siguiente pregunta la que empieza limpia, y la lista marcada sigue en los mensajes de
encima, donde se lee como lo hecho y no como lo que se está haciendo. Un paso
`blocked` es trabajo pendiente, así que un plan que tenga uno sí se siembra: algo
tiene que desbloquearlo. Una reanudación se siembra desde `paused_state` y queda
intacta: está a mitad de plan por construcción.

**Un run que termina sin acabar deja su paso.** Un run que falló, se detuvo o
superó el presupuesto ya no trabaja en nada, así que el plan que escribe de vuelta
no tiene ningún paso `in_progress`: ese paso vuelve a `pending`, pendiente pero sin
nadie haciéndolo. Conservado tal cual, el recordatorio del siguiente turno le decía
a un run nuevo que ya lo estaba haciendo (agenticos#2149). Un turno que termina a
mitad de plan a propósito —con una pregunta a la persona— y un run aparcado
conservan su paso en curso.

Un agent que no vincula la capability no paga nada: ni herramientas, ni recordatorio,
ni nada almacenado, porque una lista de comprobación vacía contra una columna que es
null no es un cambio que escribir.

**No gasta tokens propios.** Las herramientas son ediciones locales de una lista de
comprobación sin ninguna petición a un modelo o a un embedding detrás, así que, a
diferencia del conocimiento o la delegación, no hay uso ambiental que contabilizar.
Las idas y vueltas que hace el modelo para llamarlas son suyas, y el guardián de
budget ya las cuenta.

## Trabajar mientras corren las herramientas { #background-tools }

Sin herramientas propias. Con ella activada, una herramienta lenta que otra
capability marca - hoy `browse_web` del [navegador web](#browser-automation) -
recibe la opción `run_in_background`, y el modelo decide en cada llamada: espera
una navegación sin cuya respuesta no puede decir nada; deja corriendo otra que
puede rodear mientras responde al resto de la petición, y su resultado llega como
mensaje cuando está listo. Construida sobre `BackgroundTools` de
pydantic-ai-harness.

- **Revisado igual.** Un resultado en segundo plano pasa por las reglas de
  resultados de herramientas del agente - [guardrails](#guardrails),
  [límites de salida de herramientas](#tool-output-limits) - igual que uno en
  primer plano; la biblioteca sola lo entregaría saltándoselas.
- **Primero la aprobación.** Una herramienta que espera a una persona se detiene
  para su aprobación antes de que nada corra en segundo plano.
- **El presupuesto y la vida del run.** Lo que gasta una herramienta en segundo
  plano es del run, y detener el run la detiene. Un run que se pausa - una
  aprobación, una pregunta - cancela las herramientas en segundo plano que siguen
  en marcha, y sus resultados no llegan tras reanudar.

## Razonamiento { #thinking }

Sin herramientas. Le pide al modelo que razone antes de responder: más lento y más
caro, mejor en trabajo que exige tener varios pasos en la cabeza a la vez.

| Configuración | Valor por defecto | Valores |
| --- | --- | --- |
| `effort` | sin poner | `minimal`, `low`, `medium`, `high`, `xhigh`, `max` |

Sin poner significa el esfuerzo por defecto del propio provider. Un nivel que un
provider no tenga se asigna al más cercano que tenga, de modo que un spec sigue
siendo portable al cambiar de modelo.

## Recordatorio de instrucciones { #system-reminders }

Sin herramientas. Reitera las pautas de guía en mitad del run para que una sesión
larga deje de alejarse de sus instrucciones; el fallo que arregla es el desvanecido
de las instrucciones, en el que, tras muchos turnos de uso de herramientas, un modelo
va ignorando progresivamente las pautas con las que empezó. Es un port de
`SystemReminders` de
[`pydantic-ai-harness`](https://github.com/pydantic/pydantic-ai-harness).

Hay tres clases de recordatorio, cada una con su propia cadencia:

| Clase | Coste | Texto que inyecta |
| --- | --- | --- |
| `reminders[]` | ninguno | Una línea fija que escribes tú |
| `goal_reanchor` | ninguno | Una referencia a la primera petición del usuario en el run, sin repetir su texto |
| `llm_reminder` | una llamada al modelo por disparo | Un empujón corto que un modelo escribe a partir de la transcripción reciente |

Cada clase recibe `interval` (dispara cada N peticiones al modelo), `first_after` (el
número de petición del primer disparo) y `max_fires` (el tope a lo largo de la
conversación); `cache_ttl` en la capability fija la vida del punto de corte de caché.
Hay que poner al menos una clase, o la capability no aporta nada y se descarta del
run, que es lo que significa una configuración vacía.

**La cadencia cuenta a lo largo de toda la conversación, y es duradera.** Un
recordatorio se dispara en la petición al modelo número N, y ese contador se guarda
en la conversación y se vuelve a sembrar en el turno siguiente, así que un
recordatorio puesto para dispararse cada diez peticiones sigue contando donde lo dejó
el último turno en lugar de reiniciarse a cero, y salir de una conversación y
recargarla lo reanuda (#787). Solo se guardan los contadores; el texto del
recordatorio se inyecta por petición y no entra nunca en la transcripción.

**La inyección es segura para la caché.** Un recordatorio disparado se añade a la
_cola_ de la petición como un prompt de usuario efímero detrás de un punto de corte
de caché, después de que el núcleo haya persistido el historial duradero, así que
llega al modelo pero no entra nunca en `message_history`, no se acumulan
recordatorios rancios, y el prefijo cacheado (herramientas, sistema, la conversación
real) sigue idéntico byte a byte turno tras turno mientras solo el pequeño
recordatorio cae fuera de la caché. Inyectarlo en el system prompt en su lugar
reventaría el prefijo cacheado en cada disparo _y_ acumularía recordatorios rancios.

**Un recordatorio por LLM se contabiliza y hereda el modelo del run.**

Escribe su texto mediante un agente que construye él mismo, al que no envuelve ningún
guardián de budget, así que su gasto se anota en el libro del run igual que el de un
resumen, y se ejecuta bajo los límites de uso del run menos una petición reservada,
de modo que nunca puede empujar al run más allá de su propio límite de pasos.

Usa el modelo propio del run — aquel cuya credencial resolvió el vault — en vez de un
nombre de la configuración, la misma decisión que toma la
[Gestión del contexto](#context-management) sobre su resumidor.

Ante cualquier error, o cuando el budget reservado ya está gastado, recurre a la
línea de reanclaje del objetivo. Una generación fallida nunca bloquea el run.

## Tablas { #tables }

Las operaciones de tablas son herramientas de **AgenticOS MCP**, no una capacidad separada. Conecte el MCP de la plataforma en los servicios del agente y busque sus herramientas de tablas. Las lecturas usan los permisos actuales del miembro; las escrituras siguen la política de aprobación MCP.

La versión 14 de la especificación elimina las conexiones `virtual_tables` guardadas al cargarlas. Los permisos existentes de las aplicaciones publicadas pasan a `table_bindings`; este campo no expone herramientas. Los permisos desactivados siguen desactivados. Las conexiones MCP, herramientas permitidas y aprobaciones no se amplían automáticamente. Un agente antiguo sin MCP de la plataforma necesita conectarlo explícitamente antes de operar con tablas.

## Workflows { #workflows }

El descubrimiento con `list_workflows` se limita a 32 KiB de JSON codificado,
incluidos los contratos de entrada. Las respuestas mayores devuelven un rechazo
en lugar de una lista parcial. Elige menos workflows o contratos más pequeños
para el vínculo, o consulta el endpoint HTTP del esquema fuera del contexto del agente.

Permite al agente iniciar los [workflows](../workflows.md) publicados que nombra su
binding, y leer cómo fueron. El panel del Builder lista los workflows de la
organización, una fila por cada uno, y una fila marcada es uno que el agente puede
iniciar. Un borrador, o un workflow que arranca desde un webhook, una programación, un
mensaje del chat o una tabla, se muestra pero no se puede marcar: un agente solo inicia
lo que arranca a mano, por la API o por la llamada de otro workflow. **Wait for a run**
limita cuánto espera una llamada: 60 segundos salvo que se indique, entre 5 y 300.

`list_workflows` nombra los que el agente puede iniciar con los campos de entrada que
declara cada uno. `run_workflow` inicia uno con esos campos y espera su respuesta, y
`get_workflow_run` lee una ejecución que seguía en curso cuando terminó la espera. Cada
inicio es la misma petición que hace la API, hecha como el miembro por quien actúa la
ejecución, reconstruido desde su membresía en cada llamada: rigen su acceso, la entrada
declarada, los presupuestos y las cuotas de admisión, y la ejecución dice que la inició
**An agent**.

Un workflow fuera del binding se rechaza antes de que nada arranque. `run_workflow` tiene
efectos secundarios, así que una política de aprobación puede retenerlo mientras las
lecturas corren libres. Un agente que se ejecuta como paso de un workflow no inicia nada
por esta vía: un paso **Run a workflow** llama a otro workflow y conserva los límites de
bucle y de profundidad de la cadena. Por eso el diálogo del agente del propio paso no
ofrece esta capability. Una ejecución sin un miembro detrás (un visitante de un
widget, un embed o una página alojada, un remitente de canal no vinculado, la entrega
de un trigger de eventos de un agente) no inicia ninguno.

## Fecha y hora { #date-and-time }

Sin herramientas. Pone la fecha y la hora actuales en las instrucciones del agent,
para que deje de suponerlas; el fallo que arregla es un agent razonando con
seguridad sobre «este trimestre» a partir de su fecha de corte de entrenamiento.

| Configuración | Valor por defecto |  |
| --- | --- | --- |
| `timezone` | `UTC` | cualquier nombre IANA, p. ej. `Europe/Warsaw` |

## Conversaciones largas { #context-management }

Sin herramientas. Recorta el historial de mensajes de un run largo antes de cada
petición, para que un run que habría alcanzado el límite del modelo siga funcionando.
Las estrategias vienen de
[`pydantic-ai-harness`](https://github.com/pydantic/pydantic-ai-harness).

| Configuración | Valor por defecto |  |
| --- | --- | --- |
| `strategy` | `summarize` | `summarize`, `tiered`, `clear_tool_results`, `sliding_window` |
| `max_fraction` | `0.9` | 0,05–0,95 de la ventana, punto en el que empieza la compactación |
| `keep_messages` | 20 | mensajes recientes que sobreviven a un resumen o a una ventana |
| `keep_tool_pairs` | 3 | llamadas de herramienta recientes que conservan su resultado |
| `summary_prompt` | el propio de la biblioteca | qué se le dice al modelo que resume; tiene que contener `{messages}` |
| `context_window` | sin poner | sobrescribe la ventana: contra qué se dispara esto _y_ entre qué divide el indicador del chat |
| `fallback_context_window` | 200000 | ventana que suponer cuando no se puede resolver la del modelo |

`summarize` es el valor por defecto porque es la única estrategia que conserva lo que
_dijeron_ los turnos antiguos. Las que no usan LLM son más baratas porque tiran
información — una ventana deslizante descarta sin más los mensajes más antiguos,
limpiar el resultado de una herramienta borra una respuesta que el agent quizá aún
necesite — y un agent que olvida calladamente lo que le dijeron en mitad del run es
un fallo peor que un resumen que nadie pidió. Se dispara al 0,9 de la ventana por la
misma razón: la compactación es donde un run empieza a perder detalle, así que se
pospone hasta que la ventana está casi llena.

`tiered` es la opción frugal y está a una vinculación de distancia: primero limpia
los resultados de herramienta antiguos y solo paga un resumen si eso no bastó.
Resumir convierte tokens de entrada en tokens de salida, que se facturan más caros y
se generan en serie, así que a un agent cuyos runs están dominados por resultados de
herramienta grandes le suele ir mejor con `tiered`.

**Alcanza un run, no una conversación.** Entre turnos el historial se reconstruye
desde la transcripción como texto de usuario y de asistente, así que las llamadas de
herramienta y sus resultados no están ahí para compactarse y ninguna edición hecha
aquí sobrevive a la frontera de un turno. El historial que merece la pena compactar
es el largo bucle de herramientas dentro de un solo run, donde un listado de
directorio o una búsqueda de conocimiento son decenas de miles de tokens.

**El disparador es una fracción porque un número absoluto solo es correcto para un
modelo**, y el mismo agent se ejecuta con el perfil al que apunte su spec. La ventana
viene del perfil del modelo, que la anotó del listado del propio provider cuando
alguien añadió el modelo; consulta
[Qué modelos ofrece un provider](../models.md#the-window-a-model-accepts-is-read-once-and-kept).

Donde el perfil no anotó nada, la ventana se resuelve en cambio desde la instantánea
de precios incluida, y dos casos se resuelven mal, ambos en la dirección que rompe un
run y no en la que desperdicia un resumen: un spec con fallbacks construye un
`FallbackModel` cuyo id compuesto no resuelve a nada, y `genai-prices` anota 1.000.000
para `anthropic:claude-sonnet-4-5` frente a los 200.000 reales, con lo que
`max_fraction=0.9` pone el disparador en 900.000 y la compactación no se dispara
jamás. `context_window` lo sobrescribe todo y es la respuesta a ambos: un provider
publica el máximo que un modelo _puede_ llegar a aceptar, y un despliegue limitado por
beta o por nivel recibe menos.

**El disparador tiene en cuenta lo que lleva cada petición.** Mide las partes del
mensaje; una petición lleva además las instrucciones y el esquema de cada herramienta.
En un agent real el estimador vio 60 tokens donde el provider cobró por 3.865, así que
el sobrecoste se mide contra cada respuesta y la ventana del disparador se baja en esa
cantidad, que es lo que mantiene al indicador y al disparador describiendo un solo
techo en vez de dos.

Espera a tener una respuesta desde la que medir, así que la primera petición de un run
se dispara solo con los mensajes. Y se rinde cuando el sobrecoste por sí solo pasa del
disparador: ningún resumen puede bajar de ahí, los esquemas no están en el historial,
y una ventana corregida compraría un resumen en cada petición para siempre.

**Cuando se rinde, lo dice.** Un `context_window` menor que el propio sobrecoste del
agent es ese caso, y no hacer nada al respecto es indistinguible en pantalla de un
ajuste que funciona, así que el chat muestra cuál es el sobrecoste y contra qué
ventana se midió, que es el par que alguien necesita para elegir un número que
funcione. Una vez por run, porque describe una configuración y no un evento, y queda
desplazado en cuanto se ejecuta un resumen de verdad.

**Un resumen dice que está ocurriendo.** Es una petición al modelo entera entre dos de
las del propio turno, en la que no se transmite nada más: el chat se quedaba parado
en seco durante todo ese rato, lo que se lee como una pantalla rota y hace que se
recargue la página, cancelando el turno. Ahora el chat muestra qué se está resumiendo
mientras ocurre. Solo la estrategia que resume: las demás editan una lista y
devuelven.

**Un resumen se contabiliza.** La estrategia lo escribe mediante un agente que
construye ella misma, al que no envuelve ningún guardián de budget, así que la
capability mide el uso del run a lo largo del hook y anota la diferencia en el libro
del run. Se registra en vez de impedirse: el guardián se niega en la _siguiente_
petición, así que una compactación que cruza un tope detiene el run después de ella,
no durante.

**El indicador que hay al lado no forma parte de esta vinculación.** Lo llena que
estaba la ventana lo informa cada agent, compacte o no; consulta
[lo lleno que está el context window](../governance.md#how-full-the-context-window-is).
El aviso importa sobre todo al agent que _no_ va a compactar, que es el que llega al
techo y recibe un rechazo.

## Imágenes fuera del historial { #media-offload }

Ninguna herramienta. Escribe las partes grandes de una conversación compactada en
el almacenamiento y deja en el historial guardado una referencia
`media+sha256://…`. Los almacenes direccionados por contenido y los recorridos
vienen de
[`pydantic-ai-harness`](https://github.com/pydantic/pydantic-ai-harness).

| Configuración | Por defecto |  |
| --- | --- | --- |
| `threshold_bytes` | 32768 | 1 KiB–10 MiB; las partes de ese tamaño o mayores se guardan fuera del historial |

**Hay un sitio donde los medios se acumulan de verdad, y es este.** Un adjunto
llega al modelo una vez, en el turno en que se adjuntó: el historial ordinario se
reconstruye a partir del _texto_ de la transcripción, así que una imagen no se
reenvía. La excepción es una conversación [compactada](#context-management) —
entonces el volcado que hace la propia biblioteca de los mensajes del run se
guarda entero y se reproduce exactamente como el modelo lo vio por última vez,
base64 incluido, hasta que el siguiente resumen lo sustituye. Ese blob son filas
en Postgres y bytes en el cable, en cada turno intermedio.

**Dónde van los bytes, y cuánto viven.** Al propio almacenamiento de ficheros del
despliegue, en `media/<organización>/<conversación>/<digest>`. La organización es
el aislamiento: una URI de medios es un hash de contenido, así que dos inquilinos
con la misma imagen calculan la misma URI, y la organización viene del run y no de
la URI. La conversación es el ciclo de vida — un hash de contenido no registra
quién lo sigue referenciando, así que el prefijo del hilo se va con el hilo y el
del inquilino con el inquilino. El almacén no emite ninguna URL pública; una URL
que puede descargar un proveedor de modelos la puede descargar cualquiera.

**Descargar es opcional; restaurar no.** Vincular la capability es la decisión de
descargar. La reinserción ocurre para toda conversación, siga vinculada o no:
una conversación cuyo agent se desvinculó después sigue teniendo marcadores en su
historial, y un marcador que nadie reinserta es una imagen entregada al modelo en
un idioma que no lee.

**Ambas direcciones fallan con suavidad.** Perder un resumen por el que se pagó a
un modelo, porque el almacén tuvo un tropiezo, es peor que un historial más grande
de lo necesario. El fallo se registra y el historial se usa tal cual.

No reduce lo que se le _envía_ al modelo: las partes se reinsertan antes de que
salga la petición, y eso es lo que mantiene correcto el run. Reescribirlas a una
URL que el modelo descargue por su cuenta es otra función y necesitaría la URL
pública que este almacén deliberadamente no emite.

## Límites de resultados de herramientas { #tool-output-limits }

Una herramienta, `read_tool_result`. Donde `compaction` recorta el historial _dentro_
de la ventana entre peticiones, esta impide de entrada que un retorno de herramienta
desmedido llegue ahí. Un `ToolReturnPart` se persiste, así que un grep sobre un
repositorio grande o una respuesta de API verbosa se reenvía entero en cada petición
posterior del run; `code_execution` ya recorta en 8.000 caracteres exactamente por
eso, que es el valor por defecto correcto y el techo equivocado: la parte que
importaba desaparece de la vista del modelo sin nada sobre lo que actuar. Esta reduce
un retorno una vez, cuando se produce, y deja que persista la forma reducida. La
reducción en sí es el `ToolOutputLimits` de
[`pydantic-ai-harness`](https://github.com/pydantic/pydantic-ai-harness).

| Configuración | Valor por defecto |  |
| --- | --- | --- |
| `action` | `spill` | `spill`, `truncate`, `summarize` |
| `threshold` | 60000 | tamaño a partir del cual se reduce un retorno; 15000 cuando `over_tokens` está activado |
| `over_tokens` | `false` | mide el umbral en tokens estimados, no en caracteres |
| `max_chars` | 20000 | caracteres que se conservan cuando se trunca un retorno, o cuando un volcado recae en un truncado; sin fijar, nunca más que el umbral |
| `truncation_strategy` | `head_tail` | `head`, `tail`, `head_tail`: qué extremo o extremos conservar |
| `strip_ansi` | `false` | quita los códigos de color del terminal antes de medir y reducir |
| `summary_prompt` | el propio de la biblioteca | qué se le dice al modelo que resume; tiene que contener `{tool_name}` y `{output}` |

`spill` es el valor por defecto y el único sin pérdida: el retorno completo se escribe
en el backend del agent y se sustituye por un handle, una vista previa y un esbozo de
su forma, y el modelo lee porciones de él bajo demanda mediante
`read_tool_result(handle, offset, limit, from_end, pattern)`, el mismo patrón de
paginación que le da `read_file` sobre el workspace. `truncate` es el recorte barato y
con pérdida, con un marcador que dice qué se cortó; `summarize` sustituye el retorno
por un resumen hecho por un LLM y es el caro.

**Un volcado va al propio backend del agent.**

Un agent que vincula `sandbox` ya tiene un sistema de archivos — `state`, un
contenedor de Docker, Daytona — que el runner abrió para el run y asoció a la
organización. El volcado vive ahí, bajo un prefijo `tool_output/`, así que comparte la
vida de ese workspace y el agent puede incluso alcanzarlo con sus propios `read_file`
y `grep`.

En el ámbito de sesión `run`, el que viene por defecto, esa vida _es_ el run, que es
lo que pide el requisito de «no debe sobrevivir al run».

Un volcado es un artefacto de dentro del run y tampoco sobrevive nunca al run en un
workspace de ámbito más largo (`conversation`, `user`, `agent`):

- a un workspace `state` se le quita el prefijo reservado al volcar, así que los
  volcados acumulados ya no pueden empujarlo hacia su tope de bytes y hacer que
  rechace las escrituras del propio agent;
- a un workspace de _contenedor_ se le borran de su sistema de archivos los volcados
  del run cuando el workspace se cierra, por los handles exactos que el run registró y
  nunca barriendo el prefijo, de modo que dos runs concurrentes que compartan un
  workspace no pueden llevarse los volcados del otro en pleno vuelo
  ([#803](https://github.com/vstorm-co/agenticos/issues/803)).

Un agent sin backend recibe uno en memoria construido para el run y descartado con él,
así que el volcado no se escribe nunca en disco compartido.

Un volcado que el backend rechace — un workspace `state` que ya esté en su tope de
bytes — recae en un truncado en vez de desaparecer en silencio. Y lo mismo un
`summarize` cuya llamada al modelo falle: `summarize` → `spill` → `truncate`.

**Un resumen se factura al run.** Igual que el de `compaction`, la llamada que resume
pasa por un `Agent` que el harness construye él mismo, fuera del guardián de budget,
así que sus tokens se anotan en el libro del run por la misma vía de uso ambiental;
consulta [cómo se cuenta el coste de un run](../governance.md). `spill` y `truncate`
no llaman a ningún modelo y no cuestan nada.

El harness compone reducciones a partir de una lista ordenada de _bandas_ de tamaño;
aquí un autor elige una `action` en un `threshold`, porque el formulario del Builder
no puede dibujar una lista anidada, la misma razón por la que `compaction` elige una
estrategia en vez de componer niveles.

## Búsqueda de herramientas { #tool-search }

Sin herramientas propias. Permite al agent _encontrar_ una herramienta dentro de un
conjunto grande en lugar de llevar en su contexto el esquema de cada herramienta en
cada petición. Esto importa sobre todo para [MCP](../mcp.md): un agent puede vincular
un número arbitrario de servidores, y cada herramienta que expone un servidor es un
esquema que el modelo paga en cada turno, la llame alguna vez o no.

| Configuración | Valor por defecto | Valores |
| --- | --- | --- |
| `strategy` | `auto` | `auto`, `keywords`, `local_bm25`, `bm25`, `regex` |
| `max_results` | 10 | 1–50, ignorado por la búsqueda nativa |
| `defer_capabilities` | `false` | diferir herramientas de función aptas de las capabilities habilitadas |
| `defer_mcp_servers` | `true` | diferir herramientas de los servidores MCP vinculados |
| `exclude_capabilities` | `[]` | identificadores de capabilities cuyas herramientas siguen visibles |
| `exclude_mcp_servers` | `[]` | prefijos normalizados de herramientas MCP cuyas herramientas siguen visibles |
| `exclude_tools` | `[]` | nombres expuestos de herramientas que siguen visibles, tras añadir el prefijo y renombrar |

**`local_bm25`** ordena localmente identificadores, descripciones y esquemas de argumentos en cualquier proveedor. Usa rareza de términos y normalización de longitud, favorece identificadores y devuelve solo herramientas autorizadas coincidentes. No llama a modelos ni embeddings. Sigue aplicándose el límite de resultados.

- **`auto`** — búsqueda nativa de herramientas donde el provider la ofrece (BM25 o
  regex de Anthropic, del lado del servidor en OpenAI), y el algoritmo local de
  palabras clave en todo lo demás.
- **`keywords`** — busca siempre en local, con cualquier provider.
- **`bm25` / `regex`** — fuerza un algoritmo nativo de Anthropic; un run con un
  provider sin búsqueda nativa de herramientas da error en lugar de sustituirlo
  calladamente por otro. El modelo se resuelve aparte del spec, así que este es un
  coste en tiempo de ejecución que el autor acepta al nombrar uno; `auto` no falla
  nunca así.

**Elige qué grupos de herramientas diferir.** Los valores predeterminados
conservan el comportamiento de los specs existentes: las herramientas MCP se
difieren y las de capabilities siguen visibles. Activa `defer_capabilities` para
diferir también las herramientas de función aptas de las capabilities
habilitadas. Desactiva `defer_mcp_servers` para diferir solo las herramientas de
capabilities, o activa ambos grupos juntos. Un agent sin búsqueda de herramientas
ve sus herramientas como antes.

**Las exclusiones mantienen herramientas visibles desde la primera petición.**
Indica identificadores de capabilities en `exclude_capabilities`, espacios de
nombres completos de herramientas MCP en `exclude_mcp_servers`, o nombres finales
expuestos en `exclude_tools`. Una conexión llamada `github-work` usa el espacio
de nombres `github_work`; una vinculación personal usa el espacio de nombres real
de la cuenta, normalmente la clave del catálogo, como `notion`. Varias cuentas
personales pueden tener espacios de nombres distintos. Para una herramienta MCP
individual, incluye su prefijo, como `github_work_search`, y usa el nombre que
aplique el renombrado de la vinculación. Las exclusiones afectan a la visibilidad;
las listas permitidas de conexión y vinculación siguen controlando el acceso.

Las herramientas nativas del provider y los hooks de capabilities siguen activos.
Los skills conservan su propio descubrimiento mediante `read_skill`. La voz
en tiempo real no usa el diferido de la búsqueda de herramientas. Si todas las
herramientas siguen visibles, la búsqueda no tiene un catálogo diferido que descubrir.

**El Builder avisa cuando merece la pena.** En cuanto las vinculaciones MCP de un
agent suman más de 30 herramientas - según la lista permitida de cada vinculación o,
si no la tiene, según lo que su servidor listó en la última comprobación -, la
pestaña MCP muestra un aviso con una estimación aproximada de tokens y un botón
que activa la búsqueda de herramientas MCP. Añade la búsqueda de herramientas o
activa el diferido MCP en la configuración existente, conservando las exclusiones
y los ajustes de capabilities. Nunca activa el diferido por sí solo: cambia lo
que ve el modelo, así que la decisión es de quien edita.

**El diferido cambia lo que ve el modelo, nunca la identidad de una herramienta.** Una
herramienta MCP descubierta llega con su nombre real con prefijo, así que la
[puerta de aprobación](#what-a-binding-may-change) sigue emparejándose con ella y el
renombrado de una vinculación sigue alcanzándola; `ToolSearch` se sitúa en la capa más
externa, leyendo los nombres que un renombrado ya aplicó.

**No necesita contabilización.** Las estrategias locales se ejecutan en Python y
no gastan tokens; la búsqueda nativa se ejecuta dentro de la propia petición del
provider, cuyo uso ya contabiliza el [guardián de budget](../governance.md); y las
idas y vueltas del descubrimiento son peticiones corrientes al modelo que envuelve ese
mismo guardián. La única forma que se le escaparía — un callable de búsqueda a medida
que llamara él mismo a un modelo o a un embedding — deliberadamente no se expone.

## Reglas de protección { #guardrails }

Sin herramientas. Inspecciona el texto que circula por un run en cuatro bordes y o bien
**censura** una coincidencia o bien **bloquea** el run. Las comprobaciones son
detectores ya hechos de `pydantic-ai-harness`, más un detector de números de
teléfono que el harness no incluye; un agent son datos, así que la configuración
los selecciona y los parametriza en lugar de llevar una guarda en Python.

| Borde | Lee | Censura | Bloqueo |
| --- | --- | --- | --- |
| entrada | el prompt del usuario | `redact_secrets_in`, `redact_pii_in` | `blocked_keywords_in` |
| salida | la respuesta del agent y el texto que muestran sus borradores, dibujos, gráficos, páginas y preguntas | `redact_secrets_out`, `redact_pii_out` | `blocked_keywords_out` |
| resultado de herramienta | lo que devolvió una herramienta, antes de que lo lea el modelo | `redact_secrets_tool`, `redact_pii_tool` | `blocked_keywords_tool` |
| argumentos de herramienta | lo que el agent pasa a una herramienta, antes de que se ejecute | `redact_secrets_args`, `redact_pii_args` | `blocked_keywords_args` |

| Configuración | Valor por defecto |  |
| --- | --- | --- |
| `redact_secrets_*` | `false` | limpia claves de API, tokens, JWT y bloques PEM |
| `redact_pii_*` | `false` | limpia correos, números de teléfono (válidos en su plan de numeración), IBAN (mod-97), tarjetas (Luhn) y el SSN de EE. UU. |
| `blocked_keywords_*` | `""` | términos separados por comas o saltos de línea; una coincidencia termina el run |
| `phone_regions` | `"US, GB, DE, PL"` | códigos ISO 3166, separados por comas o saltos de línea, cuyos formatos nacionales de teléfono lee la censura de PII, como mucho 16 |

Todos los campos de borde vienen apagados por defecto, y una capability activada
sin ningún borde configurado no adjunta nada: un agent que no la usa no paga nada.

**Un número de teléfono solo se censura cuando es un número real.** El detector es
el de libphonenumber, con su nivel `STRICT_GROUPING`: un candidato se acepta solo
cuando encaja en el plan de numeración de su país y sus separadores caen donde ese
país agrupa los dígitos, así que una fecha, un importe o un número de pedido que
una regla por cantidad de dígitos tomaría pasan sin cambios. Un número escrito con `+` indica su propio país y se censura sea cual sea
el contenido de `phone_regions`. Un número nacional, como `415-555-0132`, se lee
frente a cada país de la lista, y cada país añadido amplía lo que puede ser una
simple secuencia de dígitos: `123456789` es un fijo polaco válido, así que con `PL`
en la lista también se censura un número de pedido de nueve dígitos. La agrupación
funciona en ambos sentidos: un código postal ZIP+4 de EE. UU. que empieza por `0`,
como `02134-1234`, está agrupado como un prefijo alemán con su número, así que con
`DE` en la lista se censura. Incluye los
países a los que atiende el agent. Un código desconocido (lo habitual es `UK` en
lugar de `GB`), o una lista de más de 16, se rechaza al publicar. Con hasta cuatro
países, un texto de más de 200.000 caracteres o con más de 10.000 dígitos no se lee.
Cada país por encima de cuatro es otra pasada sobre el texto, así que ambos límites
bajan en proporción, a 50.000 caracteres y 2.500 dígitos con dieciséis. Un texto por
encima del límite termina el run con `guardrail_blocked`, porque pasarlo sin leer
pasaría también cada número que contiene.

**La censura reescribe; un bloqueo es un desenlace del run.** Un censor limpia la
coincidencia y el run termina: una respuesta que devolvía una clave citada ha hecho el
trabajo igualmente. Un bloqueo por palabra clave, en cambio, termina el run con estado
`guardrail_blocked`, un desenlace propio junto a `budget_exceeded`, porque un rechazo
es la plataforma funcionando y un operador que filtre buscando problemas debería poder
encontrarlo en lugar de que se lea como cualquier respuesta completada. Consulta
[Gobernanza](../governance.md).

**El mensaje de un turno bloqueado no se vuelve a leer.** Cada comprobación lee solo
lo nuevo de su propio turno, así que el historial de un turno posterior no reproduce
el mensaje de un run `guardrail_blocked`, sea cual sea la comprobación que lo detuvo.
En su lugar, el modelo lee una nota breve de que un guardrail detuvo ese turno, sin
el texto del mensaje ni lo que añadieron los archivos enviados con él. La
conversación sigue mostrando a la persona lo que escribió. El rechazo de un paso
de agent en un workflow también marca el mensaje exacto del chat de origen. La
búsqueda en conversaciones anteriores (`conversation_search`) omite los mensajes
rechazados en coincidencias, fragmentos y lecturas de transcripciones. Estas
herramientas no reciben el título de una conversación con un turno rechazado,
incluso si el título ya estaba guardado.

Los reintentos y los workflows llamados conservan este vínculo del rechazo con
su origen. No heredan un destino de respuesta ni acceso al workspace del chat original.
Si un turno recién rechazado ya estaba compactado, se descarta el resumen guardado
que lo incluye para reconstruir el historial posterior con la nota de rechazo.
Las menciones de conversaciones usan la misma lista filtrada para que sus etiquetas
no repitan a un modelo el texto de un turno rechazado.

Una compactación ya iniciada no puede devolver a la caché un turno rechazado
después. La actualización reconstruye una vez los resúmenes guardados; los
mensajes originales se conservan.

Cada ejecución comprueba su historial antes de cada petición al modelo, también después de llamadas a herramientas. Los pasos de agente, modelo y decisión de un workflow también comprueban la fuente de chat compartida antes de empezar; los pasos en cola no pueden reutilizar una fuente rechazada o eliminada. Los resúmenes de voz y las nuevas sesiones realtime usan la misma comprobación de revisión.

Los harnesses de código comprueban el mismo contexto antes de iniciarse y antes de cada prompt ACP, también después de una corrección de la tarea.

Si se rechaza un turno anterior mientras un run espera aprobación o una respuesta,
el run se detiene antes de volver a ejecutar herramientas o llamar a un modelo.
Inicia un turno nuevo para continuar con el historial actual y filtrado.

**Una comprobación de salida filtra la respuesta antes de que nadie la vea.** Todas
las superficies transmiten en streaming: el chat web y el widget incrustado envían la
respuesta mientras se escribe, y un bot de canal edita su respuesta según llega el
texto. Cuando hay configurada cualquier comprobación de salida, cada fragmento de
texto y de razonamiento se retiene hasta que está completo, se comprueba con los
mismos detectores y solo entonces se envía. Una clave partida en dos trozos se detecta igualmente. Una
partida en dos partes, como el texto antes de una llamada a herramienta y el texto
después, o el razonamiento y luego la respuesta, termina el run antes de enviar su
segunda mitad, porque la primera ya está en pantalla. También el texto que el modelo escribe antes de llamar a una herramienta,
que no forma parte de la respuesta final pero aun así se muestra y se guarda. El coste
es que la respuesta de un agent así llega paso a paso en lugar de palabra a palabra.
Un agent sin comprobación de salida transmite como antes. Un bloqueo por palabra clave
en la respuesta termina el run antes de que se muestre o se guarde nada del texto
bloqueado. El razonamiento no es la respuesta, así que una palabra clave bloqueada
en él no termina el run: ese paso de razonamiento muestra
`[reasoning withheld by the output guardrail]` en su lugar.

**Los argumentos de herramienta son un borde propio.** Cada texto que el agent pasa
a una herramienta se revisa cuando llega la respuesta del modelo, antes de que la
herramienta se ejecute. El valor redactado es lo que recibe la herramienta, lo que
guarda la transcripción y lo que muestra el stream, y una palabra bloqueada termina
el run antes de llamar a ninguna herramienta. Va aparte de la revisión de salida
porque redactar un argumento cambia lo que hace la herramienta: un correo sale con
un marcador donde estaba la clave. Mientras está activo, los argumentos de una
llamada se retienen hasta que la llamada está completa, como la respuesta. La
excepción es lo que una llamada muestra a la persona - un [borrador](#drafts), un dibujo,
un gráfico, una página o una pregunta: el borde de salida revisa su texto como revisa la
respuesta, tenga o no activo este borde. En un dibujo o una página es el texto,
los atributos legibles (`alt`, `title`, `aria-label`, `aria-description`, `label`,
`placeholder`, `value`, `href`, `src`, salvo una imagen incrustada o un URI `data:` en base64) y las
cadenas de un script; las etiquetas, los comentarios, los estilos y el código no se
cambian. Un dibujo o una página aparece cuando la llamada está completa, no mientras se
escribe.

**Un delegado transmite bajo la revisión de salida del run que delega.** El texto y
el razonamiento que un delegado escribe en el panel de delegación pasan la misma
revisión que la respuesta del run, en cada nivel de delegación. Una palabra
bloqueada termina esa delegación antes de mostrar nada de ella, y el agent que
delegó recibe que ha fallado.

El filtro del stream hereda los límites de tamaño del detector de teléfonos, así que
una parte de la respuesta demasiado larga para él termina el run igual que lo haría
la respuesta final. Como el filtro se engancha al flujo de eventos del run, las
peticiones al modelo de un agent con guardrail se transmiten en streaming incluso a
través de la API HTTP, así que su modelo debe admitir streaming.

**El borde de entrada cambia lo que lee el modelo, no la transcripción.** Un prompt
censurado llega al modelo limpio, pero la conversación guarda el mensaje tal como lo
escribió la persona, datos personales incluidos. Quien pueda leer la conversación
puede leer ese mensaje.

**El borde de entrada revisa un adjunto antes de escribirlo.** Un archivo adjunto
llega al prompt como su nombre, su ruta y sus primeras 20 líneas (como máximo 2.000
caracteres), y el borde de entrada las lee junto con el mensaje de la persona. En un
agent con workspace ese texto se revisa antes de copiar el archivo a `uploads/`, así
que un turno que el borde bloquea no escribe nada, y un turno posterior en un
workspace con alcance `conversation`, `user` o `agent` no tiene ningún archivo
rechazado que abrir. El borde solo lee esas primeras líneas, así que un término
bloqueado más abajo en el archivo no se detecta aquí; para eso está la revisión de
los resultados de las herramientas. Una imagen enviada en línea no es texto, así que
el borde no la lee: en un prompt con una imagen el borde revisa solo las palabras,
nunca los bytes de la imagen, y una censura reescribe esas palabras y conserva la
imagen. Un prompt construido en código también puede
llevar un archivo de texto, que se revisa como el texto UTF-8 que recibe el
modelo; un archivo que declara otro juego de caracteres o que no es válido en el
que declara bloquea el turno. Un prompt así también puede llevar un enlace, que también se
revisa: una censura no se puede escribir en un enlace sin romperlo, así que una
coincidencia en él bloquea. Como los bytes ya no deciden, la revisión previa a
la escritura prevé un turno con imagen igual que cualquier otro.

**El filtrado de los resultados de herramienta es la razón de que este borde sea el que
más importa.** Es la única guarda sobre el contenido no confiable que entra en el
bucle — una página descargada, un archivo, la respuesta de un servidor MCP — donde si
no una carga de inyección de prompt llegaría al modelo sin leerse.

Una cosa queda deliberadamente fuera de alcance: el
veredicto `approve` de herramienta del harness no se ha portado: las
[aprobaciones](../governance.md) ya aparcan un run por herramienta para una decisión
humana, y una segunda vía, guiada por reglas, al mismo mecanismo es justo lo que evita
una única puerta.

## Información del canal de chat { #chat-channel-lookup }

`get_channel_info` — _Describe el canal en el que está ocurriendo esta conversación._
`list_channel_members` — _Lista las personas de este canal._
`search_channels` — _Encuentra otros canales por nombre o por propósito, sin leerlos._
`read_channel_history` — _Lee los mensajes más recientes de este canal, el más nuevo al final._
`send_channel_file` — _Enviar un fichero solicitado del workspace._

Para conectar la cuenta, envíe al bot un mensaje directo con solo `link`, sin barra. Abra el enlace privado tras iniciar sesión en AgenticOS y vuelva al canal. Si los ficheros anteriores del hilo requieren conexión, el bot lo explica sin descargarlos y vuelve a intentarlo tras conectar. Las imágenes del canal usan el doble de resolución CSS; los diagramas Mermaid horizontales muy anchos reciben una disposición vertical solo en el PNG.

La única capability que el spec de un agent no puede vincular. Se concede **por
vinculación**, en el Builder bajo _Where this agent is available_, porque una
organización puede vincular un agent a dos servidores de Mattermost y tres
workspaces de Slack — y «¿puede leer lo que se dijo en este canal?» tiene una
respuesta distinta en el interno y en el del cliente. Un campo del spec tendría una
sola respuesta para los cinco, así que la validación de publicación rechaza
`channel_tools` en un spec y el run ensambla la vinculación desde la fila que
admitió el mensaje, igual que añade el prompt de esa fila a las instrucciones.

Sigue siendo una capability corriente del registro, que es el motivo de hacerlo así en
vez de inyectar un toolset: a sus herramientas se les puede poner una puerta con
`tool_approval` y renombrarlas con `tool_overrides`, y ambas cosas leen el spec.

| Configuración | Valor por defecto | Rango |
| --- | --- | --- |
| `tools` | `[]` | cualquiera de los cuatro ids |
| `default_limit` | 20 | 1–200 |

No se concede nada por defecto, y lo que una plataforma no puede responder no se
ofrece: Telegram no le da a un bot ningún directorio de chats en el que buscar ni
manera alguna de leer mensajes que no se le enviaron. `docs/channels.md` tiene la
tabla por plataforma y el razonamiento.

Tres propiedades se cumplen en todas las plataformas:

- **La pertenencia del bot es toda la frontera de permisos.** Cada llamada usa el
  token del propio bot, así que el agent ve exactamente lo que ve el bot.
- **El modelo no nombra nunca un canal.** Las herramientas se atan en el servidor a
  aquel en el que llegó el mensaje; en un hilo, al canal que lo contiene.
- **Fuera de un canal no aporta nada.** Un run desde el panel, la API o una
  programación no tiene directorio, así que la capability no se adjunta en absoluto,
  por la misma razón por la que `knowledge` sin colecciones tampoco.

## Preguntar al usuario { #ask-the-user }

Cuando un agent necesita una decisión que solo la persona puede tomar, pregunta en
lugar de adivinar: `ask_user_question` acepta de una a diez preguntas de opción
múltiple, cada una con un encabezado corto, de dos a seis opciones con lo que
significa cada una y si se pueden elegir varias. La consola las muestra como una
tarjeta, una pregunta a la vez, con espacio para una respuesta escrita y un resumen
antes de enviar; el agent recibe lo elegido por encabezado, o se le dice que la
persona no quiso responder, y sigue.

La herramienta y su esquema vienen de `AskUser` de pydantic-ai-harness. Está activa
por defecto en cada agent nuevo y en cada plantilla, y el autor puede desactivarla.
Un run independiente de agent sin canal de preguntas — desde una programación,
un webhook o la API — recibe que la persona no quiso responder.

En el chat de la consola, el run guarda sus preguntas y se pausa antes de mostrar
la tarjeta — **Waiting for an answer** en el historial de runs. Cambiar de chat,
recargar la página o abrir la conversación en otro dispositivo restaura la
tarjeta sin responder. La consola envía las respuestas por su conexión activa
del chat, para que un delegado pueda hacer preguntas de seguimiento durante la
continuación. Una tarjeta sin conexión espera a que se restablezca.

Solo la persona a quien se preguntó puede responder. Los clientes de la API
pueden usar `POST /runs/{run_id}/answers`; `GET /runs/{run_id}/questions` vuelve
a leer la tarjeta. Pasado un día (`QUESTION_EXPIRY_HOURS`, 24) el run termina como
cancelado y el paso registra que la persona no respondió a tiempo.

Dentro de un paso de agent de un workflow, la misma herramienta guarda la conversación y pausa el workflow con **Esperando al usuario**. Responde en la vista del run del workflow o en el chat de origen. La respuesta se guarda y el worker del workflow reanuda el mismo run del agent, conservando su presupuesto y los resultados anteriores de las herramientas. Los clientes de workflow leen `GET /workflow-runs/{run_id}/questions` y envían `POST /workflow-runs/{run_id}/nodes/{node_run_id}/answers` con el objeto habitual `responses`. Cada entrada indica el `workflow_run_id` propietario; usa ese identificador al responder a una pregunta de un workflow llamado de forma síncrona.

Las tarjetas de preguntas aparecen solo mientras conservas permiso para ejecutar el workflow propietario. Un permiso **use** sobre ese workflow también permite responder; otra persona con acceso de lectura no puede responder en tu nombre.

## Borradores { #drafts }

`write_draft` — _Show a draft the person will send or paste somewhere else, as a card
they copy from._

Cuando alguien pide un correo, una respuesta en Slack, una publicación o la
descripción de una incidencia, el agent pone el texto en una tarjeta propia en lugar
de mezclarlo con la respuesta, así que no hay que seleccionar nada a mano ni
limpiarlo donde se pega.

La tarjeta tiene un título y un tipo (Email, Slack message,
Post). Un texto con partes que se pegan en sitios distintos - el asunto y el cuerpo
de un correo - tiene un segmento por parte, y cada segmento tiene su propio icono de
copiar en la esquina. Un segmento muestra su nombre solo donde sirve para distinguir
las partes, y una pequeña pista de tipo en la esquina inferior: `text` por defecto,
`markdown` cuando la persona lo pidió, o un lenguaje para un fragmento que el texto
lleva consigo.

Copiar pone **texto plano** en el portapapeles: exactamente el texto del segmento,
sin su nombre y sin líneas en blanco al principio ni al final. Nunca HTML ni texto
enriquecido, así que se pega con la fuente y los colores del destino. Un campo se
muestra tal como se escribió y `<b>` nunca se interpreta. Una parte `markdown` tiene un
botón Preview que la muestra renderizada: los enlaces funcionan y las imágenes
aparecen como enlaces, sin cargarse; Source vuelve al texto. Copiar siempre da la fuente.

Cuando la persona debe aportar un dato que el agente no conoce, este escribe un
marcador breve entre corchetes, como `[Tu nombre]` o `[fecha]`, en lugar de
inventarlo. La tarjeta muestra en rojo todo texto entre corchetes que contenga una
letra, salvo enlaces, notas al pie, líneas citadas y código, para que nada se envíe
sin rellenar, salvo en la vista previa de una parte markdown. Copiar conserva los
corchetes.

De dos a cinco variantes del mismo borrador («dame dos versiones») van en una sola
llamada como **variantes** y se muestran como pestañas con un nombre de una o dos
palabras («Corta», «Con detalles»). Los límites: un título de hasta 120 caracteres,
hasta 10 campos por variante, hasta 20.000 caracteres por campo y ningún campo, título o tipo vacío.
Una llamada que rompe un límite se rechaza con un mensaje que dice qué corregir, así
que el modelo reintenta y nunca se dibuja una tarjeta vacía.

El [borde de salida](#guardrails) de un agent revisa un borrador como revisa su respuesta:
un secreto o dato personal que redacta queda redactado también en la tarjeta, y una
palabra bloqueada detiene el run. Los borradores guardados antes de que el agent
tuviera la protección no se reescriben.

La tarjeta se reconstruye a partir de los argumentos de la llamada guardada, así que
al reabrir una conversación se ve la misma tarjeta. Una conversación compartida por
enlace también lleva sus borradores (hasta los 50 más recientes y 500.000 caracteres de
texto entre todos, porque cualquiera con el enlace puede cargarla). Una llamada
rechazada, o cuyos argumentos ya no se pueden leer, no muestra tarjeta.

Se ofrece **solo en el chat web**, porque es la única superficie que dibuja la
tarjeta. Las apps de escritorio y de teléfono cargan la misma consola, así que
también la tienen, incluida la consulta rápida. En cualquier otra superficie -
páginas alojadas y el widget incrustado, canales de chat, la API, programaciones,
workflows, topics en segundo plano, voz - y para un subagente, cuya salida va al modelo padre y no a la persona, el agent
no ve la herramienta y escribe el texto en su respuesta como hasta ahora.

Está activada por defecto en cada agent nuevo, cada plantilla y los agents que crea
el Architect, y un autor puede desactivarla. Los agents existentes no cambian hasta
que su autor la active y publique una versión nueva.

!!! note "Límite: una herramienta renombrada"
La consola encuentra la tarjeta por el nombre de la herramienta, igual que con
`draw` y `create_chart`. Un binding que renombra `write_draft` pierde la
tarjeta: la llamada se muestra como un paso corriente. Seguimiento en
[#2740](https://github.com/vstorm-co/agenticos/issues/2740).

## Follow-ups { #follow-ups }

Los botones funcionan en el chat de la consola y los canales de mensajería
indicados. Los widgets públicos, las páginas alojadas y los sockets embed
no procesan tarjetas de sugerencias, por lo que no inician una ejecución de
seguimiento de pago. Antes de generar y entregar, los canales vuelven a comprobar
la identidad registrada del remitente, la vinculación del bot, la política de
acceso actual y la pertenencia a la sala. Un remitente admitido sin cuenta
vinculada sigue siendo distinto del publicador usado para contabilizar costes.

Los botones de siguientes pasos los genera exclusivamente un modelo separado,
elegido en **Modelo para siguientes pasos** (`model_profile_id`). Sin selección,
las sugerencias están desactivadas. Después de actualizar, selecciona un perfil
en Follow-ups para seguir usando los botones. El modelo principal nunca recibe
`suggest_next_steps` ni espera las sugerencias para terminar su respuesta o
aceptar el siguiente mensaje.

Después de confirmar la transacción de la respuesta, una tarea opcional en segundo
plano lee la pregunta de ese run y la respuesta guardada. Devuelve hasta tres pasos
breves en el idioma de la persona, o ninguno. La consola recibe después un evento
que identifica la conversación y la respuesta exactas; un turno posterior queda
intacto. Los botones guardados se conservan al volver a abrir la conversación.
Slack, Teams, Telegram y Mattermost inician este trabajo después de publicar la
respuesta principal y envían los botones por separado.

El modelo auxiliar no tiene herramientas ni instrucciones del agente principal.
Su propio run comprueba los presupuestos del agente, departamento y organización,
hereda la privacidad del tracing y registra su coste por separado, también tras
un error. El coste de la respuesta principal no cambia. Cada proceso permite
cuatro tareas simultáneas; las demás se omiten. El trabajo del modelo está limitado
a 15 segundos, como máximo dos peticiones y 512 tokens de salida. No hay reintentos
automáticos. Las sugerencias pueden perderse al cerrar el proceso o la conexión;
nunca sustituyen la respuesta por un error.

Activity identifica el run auxiliar como **Siguientes pasos**. Conserva los
permisos de lectura de la conversación original y cuenta en su coste total, sin
marcarla como ocupada ni sustituir su último run principal.

`suggest_next_steps` conserva la identidad registrada de los botones para el
historial y los ajustes existentes del spec; el modelo principal no puede invocarlo.

`propose_setup` propone hasta tres cosas que configurar, dibujadas como tarjetas
bajo la respuesta: un agent propio de la persona, una rutina o un servicio que
conectar. Una tarjeta actúa con un clic - una rutina abre el diálogo de rutinas
relleno, en el agent que la propuso; un agent es una pregunta al Architect.

Una conexión que nombra su servidor por clave del catálogo es la tarjeta de ese
servicio - su logo y su botón Conectar, que lleva directo al inicio de sesión del
proveedor y de vuelta a la conversación - y una sin clave abre la página de
servidores MCP en su botón de añadir. El agent AgenticOS termina con ellas su
entrevista de bienvenida, y ofrece una tarjeta de conexión siempre que una
petición necesita un servicio que la persona no ha conectado. Las tarjetas son de la
consola; una app de chat no las dibuja.

Está activa en el agent inicial y en el Architect, y un autor puede desactivarla.
Una llamada de voz la deja fuera.

Una propuesta de tipo `watch` abre el formulario de observación personal con el título y la tarea completados. La persona elige una cuenta conectada y revisa la frecuencia y las fuentes aprobadas del agente. Proponer una observación no la crea ni la activa.

## Qué puede cambiar una vinculación { #what-a-binding-may-change }

El catálogo es la respuesta del despliegue a «qué existe». La entrada
`capabilities[]` de un spec es la respuesta de un agent a «cómo la uso», y puede
cambiar cuatro cosas:

| Campo | Efecto |
| --- | --- |
| `config` | Validado contra el esquema de esa capability **al publicar**, no en tiempo de ejecución |
| `approval` | `default` \ | `required` \ | `never` para cada herramienta que aporte la capability |
| `tool_approval` | Lo mismo, por herramienta, sobrescribiendo `approval` |
| `tool_overrides` | El `name` y la `description` que ve el modelo, por herramienta |
| `secret_id` | Qué secreto de la organización satisface un requisito de clave declarado |
| `enabled` | Apagada sin perder la configuración |

La aprobación es la razón de que una capability declare sus herramientas siquiera.
«¿Puede este agent escribir archivos?» y «¿puede leerlos?» son dos decisiones aunque
una sola capability responda a ambas, así que activar sigue siendo por capability
mientras que aprobar ocurre por herramienta. `default` no pregunta
a nadie; `side_effecting` solo le dice al Builder qué herramientas actúan sobre el
mundo.

!!! tip "La descripción de una herramienta es el prompt con más palanca del producto"

    Es lo que lee el modelo antes de decidirse a llamar, y su nombre dirige con la
    misma fuerza: `search_refund_policy` no es `search_documents`. Un agent que
    necesita un comportamiento distinto de la misma herramienta suele necesitar que
    se reescriban estos textos, no que se escriba una segunda capability.

!!! danger "Referenciado por el id estable de la herramienta, nunca por el nombre que ve el modelo"

    Eso es lo que mantiene una puerta de aprobación pegada a una herramienta
    renombrada. Referenciarla por el nombre visible significaría que un renombrado
    quita la puerta calladamente, y una llamada con efectos secundarios queda entonces
    desatendida sin que nada lo informe. Un id que ninguna capability así expone

se rechaza al publicar, y también un nombre que ningún modelo podría llamar, o uno que ya tiene otra herramienta del agent: la de otra capability, o una que la propia plataforma añade, como `request_capability`.

## Scopes { #scopes }

Una capability puede declarar scopes que la organización tiene que haber concedido,
comprobados cuando se ensambla el agent:

| Scope | Declarado por |
| --- | --- |
| `knowledge:read` | `knowledge`, `skills` |
| `conversations:read` | `conversation_search` |
| `web:read` | `web_research` |
| `web:fetch` | `web_fetch` |
| `web:browse` | `browser_use` |
| `code:execute` | `code_execution` |
| `sandbox:execute` | `sandbox` |
| `agents:delegate` | `subagents` |
| `tables:read` | Cada [nodo de workflow para tablas](workflow-nodes.md#virtual-tables) |
| `tables:write` | los nodos de workflow para tablas que escriben |
| `workflows:run` | `workflows` |
| `computer:use` | `computer_use` |

!!! note "Los doce se conceden hoy por defecto"

    `DEFAULT_GRANTED_SCOPES` en `app/services/agent_registry.py`. La gestión de
    scopes por organización es trabajo de la
    [hoja de ruta](https://github.com/vstorm-co/agenticos/blob/main/docs/ROADMAP.md);
    mientras tanto la comprobación está viva y es honesta, en lugar de estar
    deshabilitada y olvidada.

!!! warning "`agents:delegate` no es la puerta sobre _a quién_ se puede delegar"

    Esa es `agents:run`, comprobada sobre quien publica contra la fila de cada
    delegado. Este scope responde a una pregunta que ningún permiso puede responder:
    si este **despliegue** permite siquiera que los agents llamen a agents. Quítalo
    de ese conjunto y la delegación queda apagada en todas partes con una sola
    edición.

Un operador que no quiera runs anidados ni facturación por fan-out lo quita, y cada
spec que delegue lo dice entonces al publicar y no a las tres de la mañana.
`conversations:read` es la misma clase de palanca para la búsqueda de conversaciones:
una sola edición impide que cualquier agent lea conversaciones pasadas, para un
despliegue que considere una transcripción demasiado sensible como para ser
buscable, por muy acotado que esté el corpus.

## Qué le dice una herramienta al modelo { #what-a-tool-tells-the-model }

La definición de una herramienta es un prompt. El modelo elige una herramienta, y
rellena sus argumentos, sin nada más que el texto adjunto a ella, así que cada
herramienta de aquí lleva cuatro cosas, y la cuarta es la que suele omitirse:

1. **Qué hace**, en una frase. Es además lo que el Builder muestra junto a la casilla
   de aprobación, así que se escribe una vez y lo leen los dos.
2. **Cuándo usarla, y cuándo usar otra cosa.** `create_chart` dice que es para
   números que ya tienes y `generate_image` para algo que hay que dibujar; `glob`
   dice que busca de forma recursiva donde `ls` no lo hace.
3. **Qué significa cada argumento**, incluidos su valor por defecto y su tope.
4. **Qué vuelve**: la forma de la respuesta, qué aspecto tiene un fallo y dónde el
   resultado es una porción truncada en vez del conjunto entero. Un modelo que no
   sabe que `grep` responde en tres formas distintas según `output_mode`, o que
   `glob` se detiene a las 100 rutas, razona a partir de una porción como si fuera
   todo.

Las cuatro llegan al modelo con una sola forma, y es la propia de pydantic-ai: la
prosa dentro de `<summary>`, la descripción del retorno dentro de `<returns>`.

Una herramienta escrita aquí lo obtiene gratis: el framework la construye a partir de
la sección `Returns:` del docstring.

Una herramienta que viene de una biblioteca se registra con una descripción explícita,
lo que le quita ese camino. Así que su texto pasa por `ToolText`, en
`app/agents/capabilities/_tool_text.py`, que dibuja lo que habría dibujado el
framework.

Dos convenciones en una misma lista de herramientas es una cosa más que el modelo
tiene que reconciliar, y `tests/test_tool_text_shape.py` es lo que mantiene que haya
una: fija `ToolText` contra una herramienta que pydantic-ai construye por su cuenta, y
comprueba que las herramientas de cada capability llevan una forma de retorno.

Eso cubre también las herramientas que este despliegue no escribió: a `planning` y a
la delegación se les entrega el texto de este repositorio, `web_fetch` y
`search_tools` se vuelven a describir donde se construyen, y `read_tool_result` y
`read_skill_resource` se vuelven a describir en el sitio, sobre el toolset de la
biblioteca. Una mereció la molestia más allá de la coherencia: la frase de la
biblioteca para `read_tool_result` no decía nada de con qué responde un handle, lo
único que necesita un modelo que sostiene uno.

Una herramienta de una biblioteca para la que este repositorio no tiene texto conserva
el de la biblioteca, que es el valor por defecto correcto: `run_skill_script` se
excluye en vez de describirse, y si algún día llega, llega diciendo lo que escribiera
su autor.

### Un error, un resultado y un rechazo { #a-mistake-a-result-and-a-refusal }

Cómo informa una herramienta de un problema decide qué hace el modelo a continuación,
y los tres no son intercambiables.

| El fallo | Qué hace la herramienta | Por qué |
| --- | --- | --- |
| Los propios argumentos del modelo: una serie de un gráfico con el número equivocado de valores, un archivo de contexto que no existe, un `NameError` en el Python que escribió | Petición de reintento | Volver a llamar de otra manera es un arreglo plausible, y el mensaje dice qué aspecto tiene una llamada correcta |
| Un fallo transitorio de lo que hay detrás de la herramienta: un provider de búsqueda caído, una base de conocimiento que agota el tiempo | Petición de reintento | Un error con forma de resultado se lee como «no se encontró nada», y el modelo responde entonces de memoria, con seguridad, sin decir que tuvo que hacerlo |
| Un resultado que simplemente son malas noticias: un comando que salió con código distinto de cero, una búsqueda sin aciertos, un canal que este bot no puede ver | Se devuelve como texto | Es la respuesta. El modelo razona sobre ella y sigue |
| Un rechazo: una regla de permisos, una capability que el despliegue no ofrece | Se devuelve como texto | Una petición de reintento invita al modelo a buscar la manera de rodearlo |

Los reintentos están presupuestados: una llamada de herramienta tiene un intento para
corregirse, y un reintento lanzado _más allá_ de ese presupuesto termina el run entero
en vez de la llamada. Así que el último intento devuelve su mensaje en lugar de
lanzar: dirigido mientras hay presupuesto para ello, y nunca peor que la respuesta que
habría dado de todas formas. El único helper que decide esto es
`app/agents/capabilities/_failures.py`; `pydantic-ai-backend` mantiene la misma regla
para las herramientas del workspace.

## Añadir a esta lista { #adding-to-this-list }

Las capabilities son código: nada de lo que teclee un operador trae una nueva a la
existencia, que es lo que hace revisable el conjunto de cosas que un agent puede
hacer. Consulta [Añadir una capability](../howto/add-capability.md) para una nueva, o
[Añadir una herramienta a una capability](../howto/add-capability.md#adding-a-tool-to-an-existing-capability)
cuando la capability ya existe.

Para herramientas que nadie de aquí tiene que escribir, consulta [MCP](../mcp.md).

### Episodios de decisiones e Improve { #decision-episodes-and-improve }

Una decisión puede guardar pruebas estructuradas: situación, elección, alternativas, resultado esperado, resultado observado y corrección. El agente usa `remember` con `kind: decision` y `episode`; el mantenimiento de memoria puede capturar la misma información de una conversación admitida. Los resultados desconocidos quedan vacíos. El episodio permanece en el ámbito de la relación persona-agente o de la sala de origen. Compartir sigue requiriendo aprobación explícita de la audiencia.

En **Ajustes → Memoria**, lee las pruebas y registra un resultado observado mediante una corrección. La corrección añade un registro; el episodio anterior y su procedencia permanecen en el historial. La consolidación determinista no convierte episodios en reglas generales. El borrado elimina su contenido junto con los registros; la exportación de datos personales lo incluye.

**Preparar caso Improve** abre una entrada y una respuesta esperada editables. Revisa el texto, elimina lo que deba permanecer privado y aprueba expresamente la descarga de un registro JSONL. Los campos `input`, `reference_answer`, `tags` y `note` corresponden al importador de [Improve PR #2172](https://github.com/vstorm-co/agenticos/pull/2172). Importa el archivo en un conjunto Improve cuando esa función esté instalada, evalúalo y acepta/publica los cambios allí. Esta exportación no crea un conjunto, no ejecuta un optimizador ni publica instrucciones automáticamente.

La elección de acceso local pertenece al agente seleccionado, no a un valor global heredado por otros agentes. Revocar una carpeta también elimina las elecciones guardadas y los consentimientos de programación de sus subcarpetas. Las aplicaciones de escritorio antiguas conservan el consentimiento para todo el equipo solo en una conversación; actualiza la aplicación para reutilizarlo en las conversaciones del mismo agente.

La corrección `[session:api] Usa las cifras de la UE` llega a la sesión `api`. Con una sola sesión activa, también recibe las correcciones sin destinatario; con varias, estas quedan para el agente principal para no modificar otra tarea. El agente principal registra la corrección una vez cuando continúa.

Las tareas de programación en sandbox del mismo conjunto de herramientas se ejecutan en secuencia para evitar que se superpongan sus instantáneas de archivos; las sesiones locales independientes siguen en paralelo.
