---
source_sha: "82fcf03671a3"
---

# El catálogo de capabilities { #the-capability-catalog }

Todo lo que un agent puede *hacer* viene de uno de dos sitios: una capability
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

## Qué se entrega { #what-ships }

| id | Nombre | Categoría | Herramientas | Scope | Clave |
|---|---|---|---|---|---|
| `knowledge` | Búsqueda de conocimiento | knowledge | `search_documents` | `knowledge:read` | — |
| `skills` | Skills | knowledge | `list_skills`, `load_skill`, `read_skill_resource` | `knowledge:read` | — |
| `context` | Contexto | knowledge | `list_context`, `read_context` | — | — |
| `memory_files` | Archivos de memoria | knowledge | `list_memory`, `read_memory`, `write_memory`, `edit_memory`, `delete_memory` | — | — |
| `memory_mem0` | Memoria (mem0) | knowledge | `remember`, `recall` | — | obligatoria |
| `conversation_search` | Búsqueda de conversaciones | knowledge | `search_conversations`, `read_conversation` | `conversations:read` | — |
| `web_research` | Búsqueda web | research | `web_search` | `web:read` | para servicios de pago |
| `web_fetch` | Lectura de páginas web | research | `web_fetch` | `web:fetch` | — |
| `browser_use` | Automatización del navegador | research | `browse_web` | `web:browse` | mediante el extra `browser-use` |
| `code_execution` | Ejecutar Python | analysis | `run_python` | `code:execute` | — |
| `sandbox` | Archivos y shell | analysis | `ls`, `read_file`, `glob`, `grep`, `write_file`, `edit_file`, `execute` | `sandbox:execute` | para Daytona |
| `charts` | Gráficos | analysis | `create_chart` | — | — |
| `image_generation` | Generación de imágenes | analysis | `generate_image` | — | obligatoria |
| `subagents` | Delegación | reasoning | `task`, `check_task`, `wait_tasks`, `list_active_tasks`, `answer_subagent`, `send_message_to_subagent`, `soft_cancel_task`, `hard_cancel_task`, `create_agent`, `delegate` | `agents:delegate` | — |
| `planning` | Planificación | reasoning | `write_plan`, `read_plan`, `add_task`, `update_task_status`, `update_task_statuses`, `remove_task`, `add_subtask`, `set_dependency`, `get_available_tasks` | — | — |
| `thinking` | Razonamiento | reasoning | ninguna, a propósito | — | — |
| `system_reminders` | Recordatorios del sistema | reasoning | ninguna, a propósito | — | — |
| `tool_search` | Búsqueda de herramientas | utility | ninguna, a propósito | — | — |
| `clock` | Fecha y hora | utility | ninguna, a propósito | — | — |
| `guardrails` | Guardrails | utility | ninguna, a propósito | — | — |
| `compaction` | Gestión del contexto | utility | ninguna, a propósito | — | — |
| `tool_output_limits` | Límites de salida de herramientas | utility | `read_tool_result` | — | — |
| `channel_tools` | Consulta del canal de chat | channels | `get_channel_info`, `list_channel_members`, `search_channels`, `read_channel_history` | — | — |

Seis de ellas no tienen herramientas a propósito. `thinking` cambia cómo trabaja
el modelo, no qué puede alcanzar, `clock` pone la fecha en las instrucciones,
`tool_search` aporta su función de búsqueda solo cuando envuelve un toolset con
herramientas diferidas — por sí sola no declara nada —, `guardrails` inspecciona y
reescribe el texto que circula por un run, `compaction` reescribe el historial que
lleva una petición, y `system_reminders` añade texto de guía al final de la
petición. Ninguna de las seis deja nada que aprobar a una persona, así que ninguna
declara una herramienta. Una capability sin herramientas de verdad lo dice con
`tools=()` en lugar de omitir el argumento; consulta
[Añadir una capability](../howto/add-capability.md).

**Esta columna es lo que una capability declara, que no siempre es lo que se le
ofrece a un modelo.** La delegación es el único sitio donde ambas difieren:
`create_agent` y `delegate` aparecen solo bajo `allow_dynamic`, y
`answer_subagent` no aparece para nadie — las dos cosas se explican en
[Delegación](#delegation) más abajo.

**Una de ellas no está en el Toolbox en absoluto.** `channel_tools` se elige por
bot vinculado en *Where this agent is available*, y la publicación rechaza un spec
que intente llevarla — consulta
[Consulta del canal de chat](#chat-channel-lookup).

## Búsqueda de conocimiento { #knowledge-search }

`search_documents` — *Busca en los documentos de la organización los pasajes
relevantes para una pregunta.*

Busca en las colecciones que vincula el spec del agent y cita lo que ha usado. El
modelo pide *qué* buscar, nunca *dónde*: las colecciones se resuelven desde el spec
antes del run y se entregan a la capability, así que un agent no puede alcanzar una
colección que nadie le conectó.

| Configuración | Valor por defecto | Rango |
|---|---|---|
| `default_top_k` | 5 | 1–50 |

`default_top_k` se aplica solo cuando el modelo no pide un número por su cuenta.

Vinculada sin colecciones, esta capability no aporta **nada**: no se adjunta en
absoluto. Una herramienta de búsqueda que siempre devuelve vacío es peor que no
tener ninguna, porque el modelo sigue intentándolo y razona a partir del silencio.

## Skills { #skills }

`list_skills`, `load_skill`, `read_skill_resource`

Conocimiento escrito que el agent carga solo cuando decide que es relevante, un
skill cada vez — la alternativa sería un campo de instrucciones que crece hasta que
cada run paga por cada procedimiento. Consulta [Skills](../skills.md) para saber
qué es un skill y cómo llega a una organización.

Estas tres herramientas vienen de `pydantic-ai-skills`, así que sus nombres y su
redacción los cambia otra persona. Un test de deriva compara lo que declara el
registro con las herramientas que realmente se le ofrecen al modelo, y eso es lo
que avisa el día que ocurra.

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
al modelo. La delimitación es un mejor esfuerzo contra la fuga *accidental*: un
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

## Archivos de memoria { #memory-files }

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

- Uno a uno (chat web, la API HTTP, un mensaje directo): las notas son de esa
  persona y nadie más las lee jamás. La misma persona alcanza un único almacén
  desde las tres vías: una cuenta de chat vinculada se resuelve a su cuenta y no a
  la superficie por la que llegó.
- En un chat de grupo las notas son del chat, y todos los del chat las leen. Las
  notas propias de quien habla **no** son alcanzables ahí: algo anotado a solas
  con alguien no se lee en voz alta donde lo ve un canal entero.
- En un widget público o en un embed no hay a quién atribuir nada, así que no hay
  almacén, y las herramientas lo dicen en vez de guardar en algún sitio.

No hay un almacén para toda la organización. Existió uno y se retiró: era un
segundo mecanismo para lo que ya hacen los [archivos de contexto](../context.md)
— conocimiento permanente que una persona escribe y vincula a agents — y un solo
trabajo con dos mecanismos es la forma en que los dos acaban contradiciéndose. La
memoria es lo que aprendió el *agent*; lo que escribe una persona va en el
contexto.

Un interruptor, **Allow personal memory**, elimina por completo el almacén por
persona, por motivos de cumplimiento o de privacidad; las notas guardadas en chats
de grupo se quedan.

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

### Borrarla { #erasing-it }

Nada permite hojear las notas de alguien en la consola: un operador leyendo lo que
un agent escribió sobre un compañero es el fallo que este diseño rechaza, y no hay
pantalla para ello. Lo que sí hay es el borrado. Una persona borra desde su propio
perfil todo lo que un agent recuerda sobre ella, y un administrador que tenga
`members:manage` puede hacerlo por otra persona; ambos eliminan las filas de aquí
**y** las memorias correspondientes en mem0 de cada agent que la vincule. Borrar
por completo la memoria de un agent está en su toolbox, junto a la capability.

## Memoria (mem0) { #memory-mem0 }

`remember`, `recall`

Memoria semántica guardada en un servicio [mem0](https://mem0.ai) — en la nube, o
autoalojado mediante `base_url` — en lugar de en este despliegue. `remember` guarda
una frase corta y autocontenida; `recall` encuentra las que tratan de una pregunta
por significado y no por nombre. Necesita una clave de API del vault de la
organización.

A qué memorias puede llegar un run obedece exactamente la regla anterior, porque a
mem0 se le entrega el ámbito entero como su `user_id`: `{org}:{agent}:{owner}`. Una
sola cuenta de mem0 no puede, por tanto, mezclar las memorias de dos
organizaciones, de dos agents ni de dos personas.

Dos diferencias que conviene conocer antes de elegirla. **Aquí no se guarda nada**,
así que borrar la memoria de una persona llega a mem0 por su propia API en lugar de
por una fila que eliminemos. Y **mem0 factura su propio embedding por fuera**, así
que el libro de gasto del despliegue no lo ve y un tope de budget no lo acota.

Un `base_url` autoalojado tiene que ser https y estar en `MEM0_ALLOWED_HOSTS`. Una
lista de permitidos vacía rechaza de plano el mem0 autoalojado, y es deliberado: la
clave viaja en una cabecera `Authorization`, así que quien construya un agent y
pueda vincular una clave compartida sin poder leerla no debe poder apuntarla a un
servidor propio.

## Búsqueda de conversaciones { #conversation-search }

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
propiedad, las compartidas con ella y los hilos de canal en los que participó *y
de los que sigue siendo miembro*, confirmado contra la plataforma de chat. El
registro de runs de un trigger queda deliberadamente fuera: es la transcripción de
runs hechos bajo la autoridad de otra persona, y un agent que busca en nombre de
alguien no tiene ningún permiso suyo con el que comprobarlo.

**Y solo donde esa persona es la única que escucha.** En un chat de grupo ambas
herramientas se niegan, diciendo por qué: el corpus es personal, así que responder
a partir de él en un canal leería las conversaciones privadas de una persona ante
todos los de la sala. Es la línea que traza el índice de memoria, una capa más
afuera.

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

`web_search` — *Busca información actual en la web pública.*

| Configuración | Valor por defecto | Valores |
|---|---|---|
| `method` | `duckduckgo` | `duckduckgo`, `native`, `tavily`, `brave`, `exa` |
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

Los tres métodos de pago necesitan una clave de API de los
[secretos](../secrets.md) de la organización, nombrada por el `secret_id` de la
vinculación. El requisito es condicional y no fijo: uno fijo, o bien encerraría el
método gratuito por defecto tras una cuenta, o bien dejaría que un agent con Tavily
se publicara sin nada con lo que autenticarse y fallara en su primera búsqueda.

La aprobación y `native` no combinan, por la razón que da
[Lectura de páginas web](#web-fetch) más abajo: la puerta de
[aprobación](../governance.md) envuelve la *ejecución de la herramienta*, y una
búsqueda nativa la ejecuta el provider del modelo, así que una vinculación que
exige aprobación para `web_search` y pone `method` en `native` se rechaza al
publicar, en lugar de recibir una puerta que nunca se dispara. Elige un método que
ejecute este propio despliegue, o retira el requisito de aprobación.

Una búsqueda encuentra una página; no la lee. Leerla es
[Lectura de páginas web](#web-fetch), más abajo, y es una capability aparte con un
scope aparte.

## Lectura de páginas web { #web-fetch }

`web_fetch` — *Lee la página completa de una URL, como Markdown.*

| Configuración | Valor por defecto | Valores |
|---|---|---|
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

!!! warning "Los filtros de dominio no son la frontera de seguridad — `safe_download` sí"

    Coinciden con el nombre de host exactamente, sin comodines y sin subdominios
    implícitos, así que responden a *qué sitios puede leer este agent* y no a *puede
    este agent alcanzar nuestra red*.

Una entrada que nunca podría coincidir se rechaza al publicar: un comodín, un
esquema, una ruta, un puerto o una **lista de permitidos** vacía. Cada una dejaría
si no una lista de denegados que calladamente no deniega, o una lista de permitidos
que calladamente lo deniega todo.

Una *lista de denegados* vacía no deniega nada, que es lo que ya significa dejarla
sin poner, así que se lee como no puesta en vez de rechazarse: un spec importado
que escribe «ningún host denegado» como `[]` está diciendo algo cierto.

Una entrada que *sí* puede coincidir se almacena con la única grafía por la que se
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

## Automatización del navegador { #browser-automation }

`browse_web` — *Delega una tarea web abierta en un agente de navegador autónomo.*

Un objetivo en lenguaje natural, entregado a un agente
[browser-use](https://github.com/browser-use/browser-use) que maneja un Chromium
real — navegando, leyendo, pulsando, extrayendo — y devuelve un resultado en texto.
Recurre a ella cuando la maquetación de la página es desconocida o la tarea exige
criterio, no para un flujo guionizado que resolvería una petición directa.

Es la mayor superficie de ataque que abre una capability: un navegador sigue lo que
le dice una página, la página no es de confianza, y por eso `browse_web` convierte
el contenido web en una herramienta con efectos secundarios. Es **`side_effecting`
y puede ponerse tras una puerta** por ese motivo: ponla tras la
[aprobación](../governance.md) y la página inyectada llega a una persona, no a una
acción.

| Configuración | Valor por defecto | Valores |
|---|---|---|
| `mode` | `playwright` | `playwright`, `remote` |
| `cdp_url` | null | un endpoint de Chromium DevTools; obligatorio en (y válido solo en) `remote` |
| `allowed_domains` | null | dominios que el agent puede alcanzar; se admiten globs como `*.example.com`; null es sin restricción |
| `max_steps` | 25 | 1–100; cada paso es una petición al modelo |
| `use_vision` | `true` | envía capturas de la página al modelo del agente de navegador |
| `headless` | `true` | ejecuta sin ventana un navegador lanzado localmente (solo `playwright`) |

**`mode` elige dónde se ejecuta el navegador.** `playwright` lanza un Chromium sin
interfaz junto al agent; `remote` se conecta por CDP a un navegador que un operador
ejecuta en otro sitio. Un despliegue autoalojado apunta `remote` a un servicio de
navegador endurecido y aislado en lugar de darle al contenedor de la aplicación un
proceso de navegador. Un `cdp_url` de `remote` es una URL a la que este despliegue
se conecta desde el servidor, así que se comprueba contra SSRF: una dirección de
bucle local, privada, reservada o de metadatos se rechaza **al publicar**, cuando se
guarda el spec, y no en cada run (la comprobación resuelve DNS, que no debe bloquear
el bucle de eventos sobre el que se ensambla el run).

**El gasto de modelo del agente de navegador se contabiliza.** El subagente se
ejecuta con el modelo del run anfitrión — aquel cuya credencial se resolvió desde el
vault — y cada uno de sus pasos es una petición al modelo, anotada contra el budget
del run a través del mismo libro de uso ambiental que usa un resumen de compactación.
No es el modelo alojado propio de browser-use, y no es gasto que el guardián del
budget no pueda ver.

**`browser-use` es un extra opcional.** Arrastra un árbol pesado (Chromium vía
Playwright) y fija dependencias una versión menor por debajo del resto de la
plataforma, así que no se instala por defecto. El operador que quiera la capability
instala `agenticos[browser-use]` y proporciona un Chromium; un agent vinculado cuyo
despliegue no lo tenga falla ruidosamente en esa única herramienta, con la línea de
instalación.

## Ejecutar Python { #run-python }

`run_python` — *Ejecuta un pequeño programa en Python para calcular algo.*

Una sandbox restringida, sin red y sin sistema de archivos, que es la razón por la
que el tiempo y la memoria son los únicos límites que merece la pena fijar.

| Configuración | Valor por defecto | Rango |
|---|---|---|
| `timeout_secs` | 10 | > 0, ≤ 120 |
| `max_memory_mb` | 256 | 16–4096 |

!!! info "Por agent, no por despliegue"

    Un autor que sube un límite para un único agent con mucho tratamiento de datos
    no debería necesitar a un operador ni un redespliegue, y los topes están
    acotados en vez de ser abiertos.

## Archivos y shell { #files-shell }

`ls`, `read_file`, `glob`, `grep` — *lectura.*
`write_file`, `edit_file`, `execute` — *escritura y ejecución.*

Un workspace que sobrevive entre turnos. `code_execution` calcula y olvida; este
recuerda, y en un backend respaldado por contenedores tiene una shell de verdad. Un
agent al que se le conceden ambos calcula con uno y guarda su trabajo en el otro,
que es el emparejamiento habitual en el backend `state`, porque ese no tiene shell
en absoluto.

| Configuración | Valor por defecto | Valores |
|---|---|---|
| `backend` | `state` | `state`, `service` |
| `connection_id` | null | una conexión de sandbox registrada; null toma la predeterminada de la organización. Solo `service` |
| `session_scope` | `conversation` | `run`, `conversation`, `channel`, `user`, `agent` |
| `runtime` | null | un alias que permita el servicio de esa conexión; solo `service` |
| `include_execute` | `true` | apagado, quita la shell por completo en lugar de ponerle una puerta |

No hay un backend `docker` ni `daytona` que elegir. *Dónde* se ejecuta una sandbox
es una propiedad de la conexión que registró un operador — Sandboxes en la
aplicación —, así que nombrar la conexión es nombrar el tipo. Elegirlos por
separado hacía posible elegir dos cosas que se contradicen.

**`backend` es infraestructura; `session_scope` es una política de compartición de
datos.** Equivocarse en lo primero cuesta una funcionalidad. Equivocarse en lo
segundo le enseña a una persona los archivos de otra, así que merece la pena leerlo
dos veces:

| Ámbito | Quién comparte el workspace |
|---|---|
| `run` | Nadie: uno nuevo en cada turno |
| `conversation` | Todos los de ese chat. En Slack un hilo *es* un chat, así que los hilos no comparten |
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

**Cambiar el backend o la conexión arranca un workspace nuevo en vez de
reengancharse al antiguo.** Un documento almacenado, el volumen de un contenedor y
una sandbox de Daytona son tres cosas distintas, y dos instalaciones de `sandboxd`
son dos cosas distintas, así que cada una tiene su propio workspace y el anterior se
queda donde está, aún listado y aún legible. Mover un agent en marcha no es, por
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
|---|---|---|---|
| `state` | nada | no | esta base de datos, con tope en `SANDBOX_STATE_MAX_BYTES` |
| `service` | una conexión registrada | sí | un contenedor en ese host, o la nube de Daytona en la cuenta propia de la organización |

Un operador puede ver qué hay en marcha: Sandboxes lista las sandboxes abiertas de
esta organización en su host predeterminado con sus runtimes, sus tiempos de
inactividad y su memoria, y el registro de actividad por sandbox. Consulta
[Configuración](../configuration.md#agent-workspaces).

La publicación se rechaza para un workspace `service` cuando la organización no ha
registrado ninguna conexión, cuando la que nombra ya no existe o cuando esa conexión
no tiene credencial; cada caso por su nombre, porque los tres son estados a los que
un despliegue llega *después* de que se publicara un agent y el arreglo es de un
operador y no del autor.

**Solo `execute` pregunta.** El efecto secundario se declara por herramienta, y de
las siete solo lo es ejecutar un comando: un workspace es espacio de borrador que se
borra con la conversación a la que pertenece, así que escribir un archivo en él no
es de la misma clase de acto que enviar un correo — y un agent que tiene que
preguntar antes de cada `write_file` no puede hacer trabajo de varios pasos en
absoluto, que es como un autor acaba apagando la puerta del todo y perdiendo la que
importaba. `execute` ejecuta comandos arbitrarios en el host de alguien.

Una vinculación que quiera el comportamiento más estricto lo fija por herramienta:
`tool_approval: {"write_file": "required"}`. Consulta
[Gobernanza](../governance.md) para ver cómo se le plantea una aprobación a una
persona, y para las dos cosas que una *sesión de chat* puede decir por encima del
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

Un comando que *nombre* una de esas rutas también se rechaza, así que
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
y skills recibe cada skill como `/skills/<name>/SKILL.md` con sus recursos al lado,
que es lo que hace ejecutable el script de un skill: está en disco junto a la shell
que puede ejecutarlo. Deliberadamente no hay `run_skill_script`: `execute` ya tiene
detrás la puerta de aprobación y los topes del operador, y una segunda vía de
ejecución sería un segundo conjunto de reglas en el que equivocarse.

Esos archivos son escribibles, y lo que el agent escribe **no** se convierte en un
skill. Un skill son instrucciones que sigue en cada run todo agent vinculado a él,
así que un cambio se registra como una propuesta y alguien con `skills:edit` la
acepta o la descarta; consulta [Skills](../skills.md).

## Gráficos { #charts }

`create_chart` — *Dibuja un gráfico con números que ya tienes, para que el usuario
pueda verlos.*

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

`generate_image` — *Genera una imagen a partir de una descripción escrita.*

Dibuja una imagen con un modelo de imagen dedicado — distinto del propio del agent —
de modo que funciona sea cual sea el modelo con el que corra el agent. `create_chart`
representa números; esta dibuja ilustraciones.

| Configuración | Valor por defecto | Valores |
|---|---|---|
| `provider` | `openai` | Los providers cuya clase de modelo respeta la herramienta de imagen *y* acepta una clave de API: dos a día de hoy |
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
también lo recoge. En **Google** el modelo elegido *es* el modelo de imagen. En
**OpenAI** la herramienta la llama un modelo Responses y dibuja con el elegido, así
que la entrada nombra a ese llamante y la elección viaja como el `model` de la
propia herramienta. Ninguna de las dos es una pregunta que se le haga al autor.

**Un spec publicado antes de que existiera el par sigue funcionando.** Esto era antes
una única cadena enumerada que llevaba el prefijo del SDK
(`openai-responses:gpt-5.4`), y un spec almacenado todavía la guarda. Leído contra
los dos campos eso es un modelo desconocido, así que la configuración normaliza la
forma antigua a la entrada: el prefijo nombra al provider, y un nombre que es el
*llamante* en vez de un modelo que dibuja se resuelve al primer modelo de imagen de
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
un archivo subido a un chat, que pertenece a un solo usuario, porque no hay
constancia de quién produjo una imagen. Cuando el agent tiene además un workspace
(la capability `sandbox`), la misma imagen se escribe en él bajo `/output`, para que
un paso `execute` posterior pueda construir con ella: montar un PDF, una diapositiva,
una página. Un agent sin workspace sigue generando y mostrando imágenes; simplemente
no tiene dónde construir con ellas.

## Delegación { #delegation }

`task` — *entrega una pieza de trabajo autocontenida a uno de los especialistas de
este agent.*
`check_task`, `wait_tasks`, `list_active_tasks` — *seguir una que está en marcha.*
`send_message_to_subagent`, `soft_cancel_task`, `hard_cancel_task` — *dirigir o
detener una.* Estas seis se ofrecen solo cuando hay una delegación en segundo plano
alcanzable: a un agent que solo es `sync` no se le entrega ninguna.
`create_agent`, `delegate` — *un especialista que el modelo escribe para sí mismo, cuando el autor lo permite.*
`answer_subagent` — *declarada, y no ofrecida a ningún modelo.*

Un agent entregando parte de un trabajo a otro, cada uno con su propio modelo, su
propio conocimiento y su propio límite de pasos, y llamados por su nombre. Hay dos
formas de delegado y la diferencia decide cómo se revisa, se versiona y se factura;
[Conceptos](../concepts.md#delegate-vs-inline-specialist) es donde se explica. A qué
agents *publicados* puede delegar este no está en esta configuración: está en
`subagents`, en el nivel superior del spec, donde pueden verlo la validación de
publicación, la exportación a YAML y el modelo de permisos.

| Configuración | Valor por defecto | Rango |
|---|---|---|
| `inline` | ninguno | especialistas definidos dentro de este agent |
| `mode` | `sync` | `sync`, `async`, `auto` |
| `allow_questions` | `false` | un delegado sync puede preguntar a la persona del padre |
| `allow_dynamic` | `false` | |
| `max_depth` | 1 | 1–3 |
| `max_fanout` | 3 | 1–10 |
| `max_result_chars` | 2000 | 200–20000 |
| `share_with_delegates` | ninguna | ids de capability a las que este agent está vinculado, salvo `subagents` |

**El modo es decisión del autor, no del modelo.**

La herramienta `task` de la biblioteca recibe un argumento `mode` cuyo valor por
defecto es `sync`, así que «el modelo eligió esperar» y «el modelo no dijo nada» son
la misma llamada. No hay forma de respetar a la vez un ajuste y una elección, y el
ajuste fue revisado.

Así que el argumento se sustituye al pasar, y `auto` es la manera en que un autor
cede deliberadamente la decisión. `auto` se resuelve *antes* de que empiece la
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

En el límite, un delegado se construye *sin* la capability de delegación, en lugar
de con una que solo puede negarse. Una herramienta que siempre responde «no hay
delegados disponibles» es una descripción que el modelo paga en cada turno y que
intenta igualmente.

Deliberadamente no hay 0. Apagar la delegación es deshabilitar la vinculación, y una
segunda grafía del mismo interruptor es una que contradice a la primera.

**Y cada agent del árbol se ciñe a su propio `max_depth`, no al de la raíz.** Un
delegado recibe el *menor* entre lo que le queda al árbol y lo que permite su propio
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
especialista que el modelo *inventa* no pregunta nunca, diga lo que diga esto: unas
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

Responde a una pregunta en la que aparcó un delegado *en segundo plano*, y aquí
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

**Solo las tres que actúan piden aprobación:** `send_message_to_subagent`,
`soft_cancel_task` y `hard_cancel_task`. Dirigir cambia lo que un delegado está
haciendo en mitad del run, y cualquiera de las dos cancelaciones destruye trabajo
que se pagó y no se entregó. `task` deliberadamente no tiene efectos secundarios, lo
que suena mal por un momento: lo que un delegado *hace* pasa por la puerta del propio
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
`/workspace/notes.md` y un redactor lo lee. Un delegado que vincula `sandbox` *sin*
que se le comparta la del padre recibe el workspace en memoria, porque solo el run
abre uno.

**`subagents` no puede compartirse**, y es el único id que «¿lo tiene el padre?»
nunca podría rechazar: un agent que comparte algo lo tiene por definición.

Compartida, la vinculación del padre aterriza en un delegado que no vincula ninguna,
y el runtime lee entonces los especialistas, el `allow_dynamic`, el `max_fanout`, el
`max_depth` y la lista de compartición *del padre* como si los hubiera elegido el
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
rechazo nombra la lista. No puede adjuntar capabilities: dejar que un modelo conceda
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
construye por agente *construido*, y un run que aparca se vuelve a construir cuando
se continúa, así que se perdía a lo largo del aparcamiento hasta que las
inscripciones se llevaron en `PausedRunState` y se volvieron a registrar en la
repetición
([#175](https://github.com/vstorm-co/agenticos/issues/175)). No sobrevive al
*siguiente turno de la conversación*, que es una construcción nueva sin estado
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

Para ver qué cuesta una delegación y qué fila de run la registra, consulta
[Gobernanza](../governance.md#delegation-spends-the-parents-budget). Para ver quién
puede delegar en qué, consulta
[Permisos](../permissions.md#delegation-is-not-a-privilege-boundary).

## Planificación { #planning }

`write_plan` — *plantea o sustituye la lista de comprobación entera.*
`read_plan` — *ver los pasos y sus ids antes de una edición granular.*
`add_task`, `update_task_status`, `update_task_statuses`, `remove_task` — *cambiar un
paso, o un lote, sin sustituir el plan.*
`add_subtask`, `set_dependency`, `get_available_tasks` — *planificación consciente de
las dependencias, ofrecida solo bajo `enable_subtasks`.*

Una lista de comprobación que el modelo mantiene para sí mientras trabaja: qué está
hecho, qué está en marcha, qué queda. En trabajo de varios pasos un modelo lo hace
mejor cuando primero anota los pasos y los mantiene delante, así que el plan actual
se le devuelve cada turno como un **recordatorio de cola seguro para la caché**:
añadido después de un punto de corte de caché, de modo que el prefijo estable del
prompt sigue siendo idéntico byte a byte y solo el plan mutable se vuelve a leer cada
turno. El plan no aterriza nunca en el system prompt.

Se solapa con la [Delegación](#delegation) como un plan se solapa con un equipo: la
planificación decide *cuáles* son los pasos, la delegación decide *quién* los hace.
Son ortogonales — un plan es un toolset más un recordatorio, la delegación es un
toolset más un envoltorio del run —, así que un agent puede vincular ambas, una o
ninguna.

| Configuración | Valor por defecto | Valores |
|---|---|---|
| `enable_subtasks` | `false` | añade las tres herramientas de subtarea/dependencia y el estado `blocked` |
| `cache_ttl` | `5m` | `5m`, `1h`: cuánto puede cachearse el prefijo anterior al recordatorio |

**Ninguna de las nueve herramientas actúa sobre el mundo.** Cada una muta una lista de
comprobación que el modelo mantiene para sí, así que aquí no hay nada que una persona
pueda aprobar y la capability declara `side_effecting=False`. Las tres herramientas de
subtarea se declaran incluso cuando una lista plana no las ofrece, porque una
herramienta ausente de la declaración no puede ponerse tras una puerta por la política
de aprobación ni renombrarse por una vinculación.

**El plan pertenece a la conversación, no a un turno de ella.**

La lista de comprobación es estado, y si no, cada frontera que tiene un run lo
perdería. Un run que aparca en una aprobación a mitad de plan se reanuda como un run
nuevo — y aquí un mensaje de chat *es* un run, así que el siguiente mensaje empezaba
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
al terminar: el turno cuyo almacén se abrió vacío *sobre* un plan terminado no
escribe nada. No hizo nada a la lista de comprobación, y un volcado vacío borraría la
fila en el siguiente mensaje corriente. Un agent que empieza trabajo nuevo vuelca un
plan y lo sustituye como siempre.

El filtro está en la *siembra*, no al marcar el último paso, y en eso consiste toda
la decisión. En el turno que termina un plan el almacén todavía lo tiene, así que el
agent puede resumir lo que acaba de hacer y nada contradice la transcripción. Es la
siguiente pregunta la que empieza limpia, y la lista marcada sigue en los mensajes de
encima, donde se lee como lo hecho y no como lo que se está haciendo. Un paso
`blocked` es trabajo pendiente, así que un plan que tenga uno sí se siembra: algo
tiene que desbloquearlo. Una reanudación se siembra desde `paused_state` y queda
intacta: está a mitad de plan por construcción.

Un agent que no vincula la capability no paga nada: ni herramientas, ni recordatorio,
ni nada almacenado, porque una lista de comprobación vacía contra una columna que es
null no es un cambio que escribir.

**No gasta tokens propios.** Las herramientas son ediciones locales de una lista de
comprobación sin ninguna petición a un modelo o a un embedding detrás, así que, a
diferencia del conocimiento o la delegación, no hay uso ambiental que contabilizar.
Las idas y vueltas que hace el modelo para llamarlas son suyas, y el guardián de
budget ya las cuenta.

## Razonamiento { #thinking }

Sin herramientas. Le pide al modelo que razone antes de responder: más lento y más
caro, mejor en trabajo que exige tener varios pasos en la cabeza a la vez.

| Configuración | Valor por defecto | Valores |
|---|---|---|
| `effort` | sin poner | `minimal`, `low`, `medium`, `high`, `xhigh` |

Sin poner significa el esfuerzo por defecto del propio provider. Un nivel que un
provider no tenga se asigna al más cercano que tenga, de modo que un spec sigue
siendo portable al cambiar de modelo.

## Recordatorios del sistema { #system-reminders }

Sin herramientas. Reitera las pautas de guía en mitad del run para que una sesión
larga deje de alejarse de sus instrucciones; el fallo que arregla es el desvanecido
de las instrucciones, en el que, tras muchos turnos de uso de herramientas, un modelo
va ignorando progresivamente las pautas con las que empezó. Es un port de
`SystemReminders` de
[`pydantic-ai-harness`](https://github.com/pydantic/pydantic-ai-harness).

Hay tres clases de recordatorio, cada una con su propia cadencia:

| Clase | Coste | Texto que inyecta |
|---|---|---|
| `reminders[]` | ninguno | Una línea fija que escribes tú |
| `goal_reanchor` | ninguno | La primera petición del usuario en el run, reformulada como ancla |
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
*cola* de la petición como un prompt de usuario efímero detrás de un punto de corte
de caché, después de que el núcleo haya persistido el historial duradero, así que
llega al modelo pero no entra nunca en `message_history`, no se acumulan
recordatorios rancios, y el prefijo cacheado (herramientas, sistema, la conversación
real) sigue idéntico byte a byte turno tras turno mientras solo el pequeño
recordatorio cae fuera de la caché. Inyectarlo en el system prompt en su lugar
reventaría el prefijo cacheado en cada disparo *y* acumularía recordatorios rancios.

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

## Fecha y hora { #date-and-time }

Sin herramientas. Pone la fecha y la hora actuales en las instrucciones del agent,
para que deje de suponerlas; el fallo que arregla es un agent razonando con
seguridad sobre «este trimestre» a partir de su fecha de corte de entrenamiento.

| Configuración | Valor por defecto | |
|---|---|---|
| `timezone` | `UTC` | cualquier nombre IANA, p. ej. `Europe/Warsaw` |

## Gestión del contexto { #context-management }

Sin herramientas. Recorta el historial de mensajes de un run largo antes de cada
petición, para que un run que habría alcanzado el límite del modelo siga funcionando.
Las estrategias vienen de
[`pydantic-ai-harness`](https://github.com/pydantic/pydantic-ai-harness).

| Configuración | Valor por defecto | |
|---|---|---|
| `strategy` | `summarize` | `summarize`, `tiered`, `clear_tool_results`, `sliding_window` |
| `max_fraction` | `0.9` | 0,05–0,95 de la ventana, punto en el que empieza la compactación |
| `keep_messages` | 20 | mensajes recientes que sobreviven a un resumen o a una ventana |
| `keep_tool_pairs` | 3 | llamadas de herramienta recientes que conservan su resultado |
| `summary_prompt` | el propio de la biblioteca | qué se le dice al modelo que resume; tiene que contener `{messages}` |
| `context_window` | sin poner | sobrescribe la ventana: contra qué se dispara esto *y* entre qué divide el indicador del chat |
| `fallback_context_window` | 200000 | ventana que suponer cuando no se puede resolver la del modelo |

`summarize` es el valor por defecto porque es la única estrategia que conserva lo que
*dijeron* los turnos antiguos. Las que no usan LLM son más baratas porque tiran
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
publica el máximo que un modelo *puede* llegar a aceptar, y un despliegue limitado por
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
del run. Se registra en vez de impedirse: el guardián se niega en la *siguiente*
petición, así que una compactación que cruza un tope detiene el run después de ella,
no durante.

**El indicador que hay al lado no forma parte de esta vinculación.** Lo llena que
estaba la ventana lo informa cada agent, compacte o no; consulta
[lo lleno que está el context window](../governance.md#how-full-the-context-window-is).
El aviso importa sobre todo al agent que *no* va a compactar, que es el que llega al
techo y recibe un rechazo.

## Límites de salida de herramientas { #tool-output-limits }

Una herramienta, `read_tool_result`. Donde `compaction` recorta el historial *dentro*
de la ventana entre peticiones, esta impide de entrada que un retorno de herramienta
desmedido llegue ahí. Un `ToolReturnPart` se persiste, así que un grep sobre un
repositorio grande o una respuesta de API verbosa se reenvía entero en cada petición
posterior del run; `code_execution` ya recorta en 8.000 caracteres exactamente por
eso, que es el valor por defecto correcto y el techo equivocado: la parte que
importaba desaparece de la vista del modelo sin nada sobre lo que actuar. Esta reduce
un retorno una vez, cuando se produce, y deja que persista la forma reducida. La
reducción en sí es el `ToolOutputLimits` de
[`pydantic-ai-harness`](https://github.com/pydantic/pydantic-ai-harness).

| Configuración | Valor por defecto | |
|---|---|---|
| `action` | `spill` | `spill`, `truncate`, `summarize` |
| `threshold` | 10000 | tamaño a partir del cual se reduce un retorno |
| `over_tokens` | `false` | mide el umbral en tokens estimados, no en caracteres |
| `max_chars` | 4000 | caracteres que se conservan cuando se trunca un retorno, o cuando un volcado recae en un truncado |
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

En el ámbito de sesión `run`, el que viene por defecto, esa vida *es* el run, que es
lo que pide el requisito de «no debe sobrevivir al run».

Un volcado es un artefacto de dentro del run y tampoco sobrevive nunca al run en un
workspace de ámbito más largo (`conversation`, `user`, `agent`):

- a un workspace `state` se le quita el prefijo reservado al volcar, así que los
  volcados acumulados ya no pueden empujarlo hacia su tope de bytes y hacer que
  rechace las escrituras del propio agent;
- a un workspace de *contenedor* se le borran de su sistema de archivos los volcados
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

El harness compone reducciones a partir de una lista ordenada de *bandas* de tamaño;
aquí un autor elige una `action` en un `threshold`, porque el formulario del Builder
no puede dibujar una lista anidada, la misma razón por la que `compaction` elige una
estrategia en vez de componer niveles.

## Búsqueda de herramientas { #tool-search }

Sin herramientas propias. Permite al agent *encontrar* una herramienta dentro de un
conjunto grande en lugar de llevar en su contexto el esquema de cada herramienta en
cada petición. Esto importa sobre todo para [MCP](../mcp.md): un agent puede vincular
un número arbitrario de servidores, y cada herramienta que expone un servidor es un
esquema que el modelo paga en cada turno, la llame alguna vez o no.

| Configuración | Valor por defecto | Valores |
|---|---|---|
| `strategy` | `auto` | `auto`, `keywords`, `bm25`, `regex` |
| `max_results` | 10 | 1–50, ignorado por la búsqueda nativa |

- **`auto`** — búsqueda nativa de herramientas donde el provider la ofrece (BM25 o
  regex de Anthropic, del lado del servidor en OpenAI), y el algoritmo local de
  palabras clave en todo lo demás.
- **`keywords`** — busca siempre en local, con cualquier provider.
- **`bm25` / `regex`** — fuerza un algoritmo nativo de Anthropic; un run con un
  provider sin búsqueda nativa de herramientas da error en lugar de sustituirlo
  calladamente por otro. El modelo se resuelve aparte del spec, así que este es un
  coste en tiempo de ejecución que el autor acepta al nombrar uno; `auto` no falla
  nunca así.

**Activarla es lo que difiere los toolsets MCP.** La capability y el diferido son las
dos mitades de una sola decisión: el `ToolSearch` de la biblioteca es inerte si no hay
nada diferido, y una herramienta diferida sin una búsqueda que la encuentre es una
herramienta que el modelo no puede llamar nunca. Así que vincular `tool_search` es lo
que marca los toolsets de los servidores conectados para carga diferida; las
herramientas propias del registro siguen visibles, por ser pocas y elegidas por agent.
Un agent que no la vincule no paga nada y ve todas las herramientas como antes.

**El diferido cambia lo que ve el modelo, nunca la identidad de una herramienta.** Una
herramienta MCP descubierta llega con su nombre real con prefijo, así que la
[puerta de aprobación](#what-a-binding-may-change) sigue emparejándose con ella y el
renombrado de una vinculación sigue alcanzándola; `ToolSearch` se sitúa en la capa más
externa, leyendo los nombres que un renombrado ya aplicó.

**No necesita contabilización.** Las dos estrategias locales se ejecutan en Python y
no gastan tokens; la búsqueda nativa se ejecuta dentro de la propia petición del
provider, cuyo uso ya contabiliza el [guardián de budget](../governance.md); y las
idas y vueltas del descubrimiento son peticiones corrientes al modelo que envuelve ese
mismo guardián. La única forma que se le escaparía — un callable de búsqueda a medida
que llamara él mismo a un modelo o a un embedding — deliberadamente no se expone.

## Guardrails { #guardrails }

Sin herramientas. Inspecciona el texto que circula por un run en tres bordes y o bien
**censura** una coincidencia o bien **bloquea** el run. Las comprobaciones son
detectores ya hechos de `pydantic-ai-harness`; un agent son datos, así que la
configuración los selecciona y los parametriza en lugar de llevar una guarda en
Python.

| Borde | Lee | Censura | Bloqueo |
|---|---|---|---|
| entrada | el prompt del usuario | `redact_secrets_in`, `redact_pii_in` | `blocked_keywords_in` |
| salida | la respuesta del agent | `redact_secrets_out`, `redact_pii_out` | `blocked_keywords_out` |
| resultado de herramienta | lo que devolvió una herramienta, antes de que lo lea el modelo | `redact_secrets_tool`, `redact_pii_tool` | `blocked_keywords_tool` |

| Configuración | Valor por defecto | |
|---|---|---|
| `redact_secrets_*` | `false` | limpia claves de API, tokens, JWT y bloques PEM |
| `redact_pii_*` | `false` | limpia correos, IBAN (mod-97), tarjetas (Luhn) y el SSN de EE. UU. |
| `blocked_keywords_*` | `""` | términos separados por comas o saltos de línea; una coincidencia termina el run |

Todos los campos vienen apagados por defecto, y una capability activada sin ningún
borde configurado no adjunta nada: un agent que no la usa no paga nada.

**La censura reescribe; un bloqueo es un desenlace del run.** Un censor limpia la
coincidencia y el run termina: una respuesta que devolvía una clave citada ha hecho el
trabajo igualmente. Un bloqueo por palabra clave, en cambio, termina el run con estado
`guardrail_blocked`, un desenlace propio junto a `budget_exceeded`, porque un rechazo
es la plataforma funcionando y un operador que filtre buscando problemas debería poder
encontrarlo en lugar de que se lea como cualquier respuesta completada. Consulta
[Gobernanza](../governance.md).

**El filtrado de los resultados de herramienta es la razón de que este borde sea el que
más importa.** Es la única guarda sobre el contenido no confiable que entra en el
bucle — una página descargada, un archivo, la respuesta de un servidor MCP — donde si
no una carga de inyección de prompt llegaría al modelo sin leerse.

Dos cosas quedan deliberadamente fuera de alcance. Los **argumentos de herramienta**
son un mapeo estructurado sin detector de texto, así que no son un borde. Y el
veredicto `approve` de herramienta del harness no se ha portado: las
[aprobaciones](../governance.md) ya aparcan un run por herramienta para una decisión
humana, y una segunda vía, guiada por reglas, al mismo mecanismo es justo lo que evita
una única puerta.

## Consulta del canal de chat { #chat-channel-lookup }

`get_channel_info` — *Describe el canal en el que está ocurriendo esta conversación.*
`list_channel_members` — *Lista las personas de este canal.*
`search_channels` — *Encuentra otros canales por nombre o por propósito, sin leerlos.*
`read_channel_history` — *Lee los mensajes más recientes de este canal, el más nuevo al final.*

La única capability que el spec de un agent no puede vincular. Se concede **por
vinculación**, en el Builder bajo *Where this agent is available*, porque una
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
|---|---|---|
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

## Qué puede cambiar una vinculación { #what-a-binding-may-change }

El catálogo es la respuesta del despliegue a «qué existe». La entrada
`capabilities[]` de un spec es la respuesta de un agent a «cómo la uso», y puede
cambiar cuatro cosas:

| Campo | Efecto |
|---|---|
| `config` | Validado contra el esquema de esa capability **al publicar**, no en tiempo de ejecución |
| `approval` | `default` \| `required` \| `never` para cada herramienta que aporte la capability |
| `tool_approval` | Lo mismo, por herramienta, sobrescribiendo `approval` |
| `tool_overrides` | El `name` y la `description` que ve el modelo, por herramienta |
| `secret_id` | Qué secreto de la organización satisface un requisito de clave declarado |
| `enabled` | Apagada sin perder la configuración |

La aprobación es la razón de que una capability declare sus herramientas siquiera.
«¿Puede este agent escribir archivos?» y «¿puede leerlos?» son dos decisiones aunque
una sola capability responda a ambas, así que activar sigue siendo por capability
mientras que aprobar ocurre por herramienta. `default` sigue la propia bandera
`side_effecting` de la capability.

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
se rechaza al publicar, y también un nombre que ningún modelo podría llamar.

## Scopes { #scopes }

Una capability puede declarar scopes que la organización tiene que haber concedido,
comprobados cuando se ensambla el agent:

| Scope | Declarado por |
|---|---|
| `knowledge:read` | `knowledge`, `skills` |
| `conversations:read` | `conversation_search` |
| `web:read` | `web_research` |
| `web:fetch` | `web_fetch` |
| `web:browse` | `browser_use` |
| `code:execute` | `code_execution` |
| `sandbox:execute` | `sandbox` |
| `agents:delegate` | `subagents` |

!!! note "Los ocho se conceden hoy por defecto"

    `DEFAULT_GRANTED_SCOPES` en `app/services/agent_registry.py`. La gestión de
    scopes por organización es trabajo de la
    [hoja de ruta](https://github.com/vstorm-co/agenticos/blob/main/docs/ROADMAP.md);
    mientras tanto la comprobación está viva y es honesta, en lugar de estar
    deshabilitada y olvidada.

!!! warning "`agents:delegate` no es la puerta sobre *a quién* se puede delegar"

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
`search_tools` se vuelven a describir donde se construyen, y `read_tool_result` y las
tres de `skills` se vuelven a describir en el sitio, sobre el toolset de la
biblioteca. Dos merecieron la molestia más allá de la coherencia: la frase de la
biblioteca para `read_tool_result` no decía nada de con qué responde un handle, lo
único que necesita un modelo que sostiene uno, y `list_skills` documentaba el retorno
de Python (un diccionario) en lugar del texto que se entrega al modelo.

Una herramienta de una biblioteca para la que este repositorio no tiene texto conserva
el de la biblioteca, que es el valor por defecto correcto: `run_skill_script` se
excluye en vez de describirse, y si algún día llega, llega diciendo lo que escribiera
su autor.

### Un error, un resultado y un rechazo { #a-mistake-a-result-and-a-refusal }

Cómo informa una herramienta de un problema decide qué hace el modelo a continuación,
y los tres no son intercambiables.

| El fallo | Qué hace la herramienta | Por qué |
|---|---|---|
| Los propios argumentos del modelo: una serie de un gráfico con el número equivocado de valores, un archivo de contexto que no existe, un `NameError` en el Python que escribió | Petición de reintento | Volver a llamar de otra manera es un arreglo plausible, y el mensaje dice qué aspecto tiene una llamada correcta |
| Un fallo transitorio de lo que hay detrás de la herramienta: un provider de búsqueda caído, una base de conocimiento que agota el tiempo | Petición de reintento | Un error con forma de resultado se lee como «no se encontró nada», y el modelo responde entonces de memoria, con seguridad, sin decir que tuvo que hacerlo |
| Un resultado que simplemente son malas noticias: un comando que salió con código distinto de cero, una búsqueda sin aciertos, un canal que este bot no puede ver | Se devuelve como texto | Es la respuesta. El modelo razona sobre ella y sigue |
| Un rechazo: una regla de permisos, una capability que el despliegue no ofrece | Se devuelve como texto | Una petición de reintento invita al modelo a buscar la manera de rodearlo |

Los reintentos están presupuestados: una llamada de herramienta tiene un intento para
corregirse, y un reintento lanzado *más allá* de ese presupuesto termina el run entero
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
