---
source_sha: "3a50fc3a822d"
---

# Protección de datos { #data-protection }

Dónde residen los datos personales en un deployment, qué sale de él y bajo qué
configuración, qué controles existen en el código con una prueba detrás y cuáles
siguen siendo incidencias abiertas. Escrito para quien responde a una revisión
de protección de datos de un deployment — un delegado de protección de datos, un
responsable de seguridad, un operador — y honesto sobre la diferencia entre lo
que el software puede hacer y lo que un deployment ha decidido de verdad.

!!! warning "Una página no es cumplimiento"

    Nada de lo que hay aquí es prueba de que un deployment cumpla el RGPD. La
    base de código se puede desplegar dentro de un entorno conforme; que uno
    *lo sea* depende de los providers configurados, de la retención decidida, de
    los acuerdos firmados y del operador que lo lleva. Cada una de esas
    condiciones aparece abajo como algo que hay que obtener y verificar, nunca
    como algo que se da por supuesto.

## Por defecto no sale nada { #nothing-leaves-by-default }

Un deployment recién instalado lo guarda todo en su propio PostgreSQL y en su
propio disco, y no envía nada a ninguna parte. Cada salto al exterior es una
fila o un ajuste que alguien añade después: un perfil de modelo que nombra un
provider, una colección que elige un parser, un método de búsqueda en un spec,
un token de Logfire, un host de mem0, un servidor MCP, un bot de canal. Quita la
fila y el salto desaparece.

Así que un deployment que no quiere **ninguna tercera parte en la cadena** se
configura así y el software coopera:

| Asunto | La respuesta local |
|---|---|
| El modelo de chat | Un perfil `ollama` o `litellm` — sin clave, apuntando a un endpoint que alojas tú. Cualquiera de los 27 providers con `base_url` admite también una pasarela tuya |
| Parseo de documentos | `pymupdf`, el valor por defecto, se ejecuta en el worker. El OCR de LiteParse también, o en un servidor de OCR que registres como servicio local. LlamaParse es una elección por colección que necesita una clave del vault; sin ella no se parsea nada fuera |
| Embeddings | Un Ollama que alojas tú, registrado como servicio local en Knowledge → Integrations y elegido por colección como provider `ollama`. Sin clave, y el único provider que puede usar una colección app-scoped |
| Trazas | Deja `LOGFIRE_TOKEN` sin definir y no vincules ningún token `observability` a un spec ni a un entorno. Los runs siguen registrando localmente un id de traza |
| Búsqueda, navegación, memoria, herramientas | No vincules ningún secreto `search`, ninguna capability `web_fetch`, `browser_use` ni `memory_mem0`, ninguna conexión MCP |
| Correo | Tu propio relay SMTP |
| Voz e imágenes | Perfiles en un provider que alojes tú, o ningún perfil de ese tipo |

Los embeddings incluidos: el catálogo nombra OpenRouter y OpenAI, a los que una
colección llega con una clave del vault, y `ollama`, al que una colección llega a
través de un servicio local — una fila que nombra un servidor que opera la
organización o el deployment. Una colección en `ollama` no envía sus chunks ni
sus consultas a ningún host que no sea ese, y no le paga a nadie. Un deployment
que deba mantener los documentos en su propio hardware crea allí todas sus
colecciones.

## Quién es responsable de qué { #who-is-responsible-for-what }

| Parte | Rol | Qué significa aquí |
|---|---|---|
| La organización que lo despliega (una ciudad, una empresa) | **Responsable del tratamiento** | Decide finalidades, retención, a qué providers puede llegar un agent, y firma los acuerdos con ellos |
| Vstorm, como autor del software | **Ninguno de los dos**, en un deployment autoalojado | El código se ejecuta en tu infraestructura y nada llama a casa. Vstorm nunca ve tus datos |
| Vstorm, si opera el deployment por ti | **Encargado del tratamiento** | Un contrato de encargo de tratamiento es un contrato entre nosotros, no un ajuste. Tiene que existir antes de publicar el primer agent |
| Un provider de modelos, embeddings, parseo, búsqueda u observabilidad | **Subencargado**, elegido por configuración | La plataforma registra *qué* provider y *qué* endpoint usa cada agent. Su ubicación, su retención y sus condiciones de entrenamiento son suyas, y se verifican en cada deployment |

La plataforma no entrena ni afina nada. Envía prompts, documentos y resultados
de herramientas a los providers que configura un deployment y guarda lo que
vuelve. Que un provider use el tráfico de la API para entrenar es una propiedad
de la cuenta y de las condiciones del provider, y la lista de comprobación del
final pide la declaración en lugar de darla por supuesta.

## Dónde residen los datos personales { #where-personal-data-lives }

Todo lo de abajo está en el PostgreSQL del propio deployment, en su propio disco
o en un servicio que el deployment eligió. Toda tabla que pertenece a una
organización lleva un `organization_id`; una fila hija — un mensaje, un adjunto,
una valoración — queda acotada a través de la conversación o el usuario del que
cuelga, y leerla pasa por la comprobación del padre.

### La base de datos { #the-database }

| Almacén | Guarda | Datos personales que contiene | Finalidad |
|---|---|---|---|
| `users`, `sessions`, `organization_members` | Cuentas e inicios de sesión | Correo, nombre, avatar, contraseña con hash o el id de la cuenta de Google, hash del refresh token, dirección IP y user agent por sesión | Autenticación y autorización |
| `conversations`, `messages`, `tool_calls` | Todos los chats en todas las superficies | El texto que la gente escribió, las respuestas y el razonamiento del modelo, argumentos y resultados de herramientas, un resumen continuo de los hilos largos | La función central del producto; el historial al que vuelve la persona |
| `chat_files` | Adjuntos de un mensaje | Nombre de archivo, tipo, tamaño, el texto extraído (`parsed_content`) y la ruta de los bytes en disco | Responder sobre un archivo |
| `context_files` | Conocimiento permanente que un builder escribió para los agents | Lo que el autor pusiera ahí — y llega al prompt literalmente. Consulta [Archivos de contexto](context.md) | Instrucciones y hechos que un agent debe saber siempre |
| `agent_memory_files` | Notas que un agent escribió sobre una persona o un chat de grupo | Lo que el agent decidiera que valía la pena recordar, con clave `person:<user_id>` o una sala de chat | Continuidad entre conversaciones |
| `rag_documents`, `knowledge_bases` y una tabla vectorial por colección | Documentos subidos y sincronizados, sus chunks y sus embeddings | El texto del documento y sus vectores, la ruta original del archivo en el origen | Recuperación |
| `agent_runs`, `tool_approvals`, `run_manifests` | Lo que costó y lo que hizo cada run | El prompt de sistema y la última petición entregada al modelo, argumentos de herramientas a la espera de aprobación, la persona que decide y su nota | Budgets, aprobaciones, historial de runs |
| `agent_triggers` | Runs programados y disparados por eventos | El prompt y la configuración y el filtro del origen de eventos | Ejecutar un agent sin una persona |
| `app_admin_audit_logs` | Quién cambió accesos o gastó dinero — el rastro de la organización y el del administrador del deployment comparten tabla | Actor, suplantador, dirección IP, la acción y un mapa `details`. El mapa nombra sobre todo campos, pero algunas entradas guardan valores: el correo de la cuenta suplantada, el correo de una cuenta que un administrador borró, una nota de publicación | Rendición de cuentas. Consulta [Gobernanza](governance.md#audit) |
| `embed_visitors`, `channel_identities`, `channel_sessions` | Desconocidos en una página alojada y personas en Slack, Telegram o Mattermost | Una clave de visitante aleatoria; un id de usuario de la plataforma, nombre de usuario y nombre visible; el id del chat | Retomar el hilo correcto |
| `message_ratings` | Pulgares y comentarios sobre las respuestas | Quien valora y su comentario | Revisión de calidad |
| `agent_workspaces`, `sandbox_operations` | Archivos sobre los que trabajó un agent y el registro de lo que ejecutó | Para el backend `state`, los propios archivos, en JSON; para un contenedor, el id de sesión y cada comando, destino y resumen del resultado | La sandbox. Consulta [La sandbox](sandbox.md#what-was-done-in-one-and-where-that-record-lives) |
| `organization_secrets`, `model_profiles`, `mcp_connections`, `channel_bots` | Credenciales y hacia dónde apuntan | Solo el cifrado sellado, con una pista; el provider, el modelo y la `base_url` en claro | Llegar a los providers. Consulta [Secretos](secrets.md) |

`messages.search_vector` es un índice de texto completo sobre el mismo
contenido, y `conversations.summary_messages` es una compresión de él escrita
por el modelo. Ambos son copias del chat y se van con él.

### Fuera de la base de datos { #outside-the-database }

| Almacén | Guarda | Se borra cuando |
|---|---|---|
| `MEDIA_DIR` en el host de la API (volumen `media_data`) | Adjuntos de chat bajo `<user_id>/`, avatares, logos de embeds, imágenes generadas bajo `generated_<org>/` y una copia temporal de cada documento bajo `_rag_tmp` mientras se parsea | Se borra un documento desde el producto. **Nada en el producto elimina los bytes de un adjunto de chat** — ni borrar su conversación, ni borrar a su propietario. Consulta [Qué alcanza el borrado](#what-deletion-reaches) |
| `SANDBOXD_WORKSPACE_ROOT` en el host de la sandbox | Los archivos de cada workspace respaldado por contenedor | Se borra la conversación, o `SANDBOXD_WORKSPACE_TTL` los barre; sin definir, se conservan indefinidamente. Consulta [Cuánto sobrevive cada cosa](sandbox.md#how-long-anything-survives) |
| Redis | Cubos de rate limit con clave en quien llama — en una superficie pública eso es la **dirección IP en claro**, dentro de la clave, durante el TTL de la ventana; claves de deduplicación de triggers y canales; estado del intercambio OAuth; invitaciones en espera | Al expirar; nada de esto sobrevive a sus minutos |
| Prefect | Historial y logs de los flow-runs | Los parámetros son ids y rutas, con una excepción: el **`event_context` de un run disparado por un evento** — el remitente, el asunto y el cuerpo de un mensaje de Gmail, una incidencia de GitHub, un payload de webhook — viaja como parámetro del flow y se queda en el historial. Los logs del worker pasan por el mismo filtro de redacción que los de la API |
| Logfire, si está configurado | Trazas de cada run | La retención del provider. Hoy una traza lleva el prompt completo, la salida y los argumentos de las herramientas — consulta [Trazas](#traces) |
| Tu relay SMTP | Invitaciones, enlaces mágicos, peticiones de aprobación, alertas de budget, informes de uso | Lo que el relay conserve. El correo de aprobación nombra el agent, la herramienta y un enlace, no los argumentos de la herramienta |
| Copias de seguridad | Un `pg_dump` es la base de datos entera; el volumen de medios son los archivos | Tu caducidad de copias. El borrado nunca alcanza una copia ya tomada — consulta [Copias de seguridad](deploy.md#backups) |

## Qué sale del deployment { #what-leaves-the-deployment }

No sale nada mientras una fila o un ajuste no nombre un destino. Esta es la
lista completa de destinos, con la configuración que decide cada uno.

| Destino | Qué se envía | Lo decide | Ubicación y condiciones |
|---|---|---|---|
| El modelo de chat | La conversación hasta ese punto, los adjuntos pegados o descritos, los chunks recuperados, los resultados de herramientas | Un [perfil de modelo](models.md#a-model-profile): `provider`, `model`, `base_url` y una clave sellada. Veintisiete providers; `ollama` y `litellm` no llevan clave y se alcanzan en un endpoint que alojas tú, y `openai`, `anthropic`, `google`, `huggingface` y otros aceptan una `base_url`, así que un endpoint en la UE o una pasarela es un campo, no una bifurcación | La del provider. Verifícalo por perfil |
| El modelo de embeddings | Cada chunk de cada documento de una colección, y cada consulta de recuperación | Por colección, y solo ahí: `embedding_provider` (`openrouter`, `openai` u `ollama`, del catálogo) y, para los dos primeros, la clave del vault `embedding_secret_id` que paga. No hay clave de embeddings a nivel de deployment; una colección con clave que no nombre ninguna rechaza indexar y buscar. `ollama` no lleva clave y se alcanza en el servicio local que nombra la colección (`embedding_endpoint_id`), un host que operas tú | La del provider, o tu propio host. [Una elección permanente](choosing-models.md#embeddings-are-a-separate-permanent-choice) |
| LlamaCloud | El documento entero | Una colección cuyo `pdf_parser` sea `llamaparse`; tiene que nombrar una clave del vault (`llamaparse_secret_id`), no hay clave de deployment. El `pymupdf` por defecto parsea en el worker | La de LlamaCloud, si se usa |
| Un servidor de OCR | Páginas renderizadas de un documento | Una colección cuyo `pdf_parser` sea `liteparse` **y** cuyo `ocr_endpoint_id` nombre un servicio local; sin él, el OCR se ejecuta en el worker | Tu propio host — un servicio local está por construcción en la red del deployment |
| Un modelo de descripción de imágenes | Las imágenes dentro de los documentos | El `image_description_model` de una colección | La de ese provider de modelos |
| Investigación web | La consulta de búsqueda que compuso el agent | `web_research.method` en el spec: `duckduckgo` (sin clave), `tavily`, `brave` o `exa` (un secreto `search` cada uno), o `native`, donde busca el provider del modelo de chat | La del proveedor de búsqueda, o la del provider del modelo |
| Web fetch y uso del navegador | La URL; para el uso del navegador, la tarea entera | La capability en el spec; el uso del navegador necesita además un endpoint CDP que nombres tú | El sitio consultado; el host del navegador |
| La sandbox, hacia fuera | **Cualquier cosa del workspace, a cualquier host** — la runtime `workbench` tiene red, shell y `curl` | La capability `sandbox` y una runtime con `needs_network`; la aprobación de comandos controla qué se ejecuta, no adónde se conecta | Adonde fuera el comando. El control de salida es el firewall del host de la sandbox, no un ajuste de aquí |
| Un servidor MCP | Argumentos y resultados de herramientas | `mcp_connections.url`, por organización o por persona | La del operador del servidor |
| mem0 | Los recuerdos escritos para una persona o un chat | La `base_url` de la capability `memory_mem0`, que tiene que estar en `MEM0_ALLOWED_HOSTS` | La del host de mem0 que permitas |
| Logfire | Spans de cada petición y cada run | `LOGFIRE_TOKEN` a nivel de deployment; un token `observability` en un spec, o `logfire_token_secret_id` en un entorno, redirige esos runs a otro proyecto. `LOGFIRE_BASE_URL` elige el deployment de EE. UU. o el de la UE. Sin definir en ninguna parte, no se envía nada | La de Pydantic, EE. UU. o UE |
| Voz a texto, generación de imágenes | La nota de voz; el prompt | Un perfil para `groq`, `mistral` u `openai`; un perfil para `google` u `openai` | La del provider |
| Slack, Telegram, Mattermost | Las respuestas del agent | Una fila `channel_bots` con su token en el vault | El proveedor de mensajería ya tiene el chat |
| Inicio de sesión con Google | Nada hacia fuera; Google devuelve el correo, el nombre, la foto y el id de la cuenta | `GOOGLE_CLIENT_ID` | La de Google |
| Tu relay SMTP | El correo de arriba | `SMTP_HOST`, `SMTP_TLS` | La tuya |

Los conectores de sincronización van al revés: un origen de Google Drive o S3
trae documentos **hacia dentro**, autenticado por un secreto `connector`, y a
partir de ahí los documentos son la copia del deployment y siguen las reglas de
arriba. Quién acaba pudiendo leer lo que un origen ha ingerido es
[una decisión que toma la fila del origen](file-processing.md#who-ends-up-able-to-read-what-a-source-ingested).

## Controles, y dónde se prueba cada uno { #controls-and-where-each-is-proved }

Cada fila nombra el mecanismo en el código y la prueba o la página que lo fija,
o la incidencia que lo hará. Una fila cuya última columna es una incidencia es
una laguna, y así queda dicho.

| Control | Mecanismo | Probado por |
|---|---|---|
| Aislamiento entre tenants | `organization_id` en toda tabla que pertenece a una organización, resuelto desde `X-Organization-Id` a una membresía en cada petición; las filas hijas solo se alcanzan a través de la comprobación de su padre | `tests/integration/test_conversation_tenant_isolation.py` y sus hermanos; [Permisos](permissions.md) |
| Acceso a una fila | Tres capas: administrador del deployment, rol en la organización, grant por recurso a través de `resolve_access`. Un control que quien llama no puede usar no se renderiza | Pruebas de rechazo en `tests/api/`; [Permisos](permissions.md#how-the-layers-combine) |
| Leer el chat de otra persona | El propietario, una compartición explícita o el app admin del deployment — nunca un rol de la organización. Las conversaciones tienen su propia comprobación, `ConversationService._may_read`, en vez de la fórmula de grants | `admin_conversations.py` exige `is_app_admin`; `tests/integration/test_conversation_tenant_isolation.py` |
| Credenciales en reposo | Cifrado de sobre por organización, claves maestras versionadas, rotación con ejecución en seco | [Secretos](secrets.md#what-never-happens), cuatro garantías fijadas por pruebas |
| Contenido en reposo | **La aplicación no lo cifra.** Los datos de Postgres, `media_data` y la raíz de workspaces de la sandbox dependen del cifrado de disco o de volumen que aportes tú | Control del operador. Un backend S3 con cifrado del lado del servidor para archivos es [#1423](https://github.com/vstorm-co/agenticos/issues/1423) |
| En tránsito, entrante | HTTPS en tu proxy; `Strict-Transport-Security` cuando `ENVIRONMENT=production`; cookies de sesión `httpOnly`, y `secure` según el esquema de la petición al iniciar sesión y al refrescar. La ruta de cambio de contraseña pone `secure` solo en una build de producción | [Despliegue](deploy.md#choose-a-reverse-proxy); `frontend/src/app/api/auth/login/route.ts` |
| En tránsito, hacia los almacenes | `POSTGRES_SSLMODE` y `REDIS_SSL`; `agenticos cmd doctor` informa de si la conexión que estableció iba cifrada | [Conexiones cifradas](configuration.md#encrypted-connections-tls); `tests/integration/test_store_tls.py` |
| En tránsito, hacia los providers | HTTPS a todo endpoint catalogado. Una `base_url` propia se rechaza sin host o con credenciales dentro, pero **`http://` se acepta**, para un Ollama o una pasarela en la propia red del deployment; un perfil en HTTP plano que apunte fuera de esa red envía los prompts y la clave en claro. El punto 4 de la lista de comprobación enumera todos esos perfiles | `refused_field("base_url", ...)` en el servicio de perfiles de modelo; el esquema es control del operador |
| Secretos en respuestas, logs, auditoría, exportaciones | Ningún endpoint devuelve un texto en claro; `SecretStr` en todas partes; los specs referencian secretos por id | [Secretos](secrets.md#what-never-happens) |
| Datos personales en los logs | `app/core/logging.py` redacta direcciones de correo, JWT, claves de API, tokens bearer y pares `password=` de cada registro de log, tanto en la API como en el worker | `tests/test_logging.py`; el worker lo instala en `prefect_app.py` (#440) |
| Datos personales que llegan al modelo | La capability `guardrails` redacta IBAN, números de tarjeta, números de seguridad social estadounidenses y direcciones de correo de los prompts, las respuestas y los resultados de herramientas cuando está configurada | [Capabilities](reference/capabilities.md); sus pruebas bajo `tests/` |
| Datos personales en una columna de fallo | `rag_documents.error_message` y similares registran la etapa y la clase, nunca el texto del cliente | `app/services/rag/failures.py` (#423) |
| Rendición de cuentas | Las entradas de auditoría comparten la transacción que actúa y fallan en cerrado; la suplantación nombra a ambas personas; las exportaciones masivas quedan registradas | [Gobernanza](governance.md#audit) |
| Exportación de auditoría y prueba de no manipulación | Todavía ninguna | [#1422](https://github.com/vstorm-co/agenticos/issues/1422) |
| Trazas | Hoy contenido completo, y sin interruptor | [#1413](https://github.com/vstorm-co/agenticos/issues/1413) añade `full`, `redacted`, `none` por agent |
| Retención programada | Solo se barren las filas de `sandbox_operations`, a los 30 días. El barrido de runs abandonados los finaliza; no borra nada | [#1420](https://github.com/vstorm-co/agenticos/issues/1420) |
| Supresión de una persona | El borrado de la cuenta concilia lo que lo bloquearía; la supresión de la memoria es una llamada aparte y llega hasta mem0 | [Qué alcanza el borrado](#what-deletion-reaches); [#1421](https://github.com/vstorm-co/agenticos/issues/1421) para lo que deja |
| Acceso a los propios datos | No hay endpoint de exportación; no hay vista de la propia memoria | [#1421](https://github.com/vstorm-co/agenticos/issues/1421), [#1594](https://github.com/vstorm-co/agenticos/issues/1594) |
| Identidad corporativa | Inicio de sesión con Google y contraseñas; todavía sin OIDC | [#1419](https://github.com/vstorm-co/agenticos/issues/1419) |
| La matriz de controles que lee una revisión de seguridad | Esta página y [Ponerlo en marcha](rollout.md#what-your-security-review-will-ask) | [#1412](https://github.com/vstorm-co/agenticos/issues/1412) añade el mapeo a HIPAA y SOC 2 |
| Superficies públicas | La clave de visitante de una página alojada es aleatoria, nunca derivada de la persona; la admisión y las subidas se limitan por dirección, y la dirección vive en una clave de Redis durante la ventana y en ningún otro sitio | [Canales](channels.md#a-hosted-page) |
| Avisos legales | Las URL de Términos y Privacidad propias del deployment sustituyen a las páginas incorporadas | [El deployment](deployment.md#identity) |

### Trazas { #traces }

`instrument_pydantic_ai()` se ejecuta con el valor por defecto de la biblioteca,
así que un span contiene el mensaje del usuario, la respuesta del modelo y cada
argumento y resultado de herramienta. Con `LOGFIRE_TOKEN` sin definir, sin token
`observability` en ningún spec y sin `logfire_token_secret_id` en ningún
entorno, no se envía nada y el id de la traza se sigue registrando localmente.
Un deployment que necesite trazas antes de que aterrice
[#1413](https://github.com/vstorm-co/agenticos/issues/1413) tiene una sola
opción: un proyecto de Logfire cuyas condiciones y región haya aceptado,
sabiendo que el contenido va con los tiempos.

### Qué alcanza el borrado { #what-deletion-reaches }

Borrar es lo que hace el producto hoy cuando alguien lo pide; la retención
programada es [#1420](https://github.com/vstorm-co/agenticos/issues/1420).

| Acción | Elimina | Deja |
|---|---|---|
| `DELETE /conversations/{id}` (el propietario) | La conversación, sus mensajes, llamadas a herramientas, valoraciones, comparticiones y filas `chat_files`, en cascada; un workspace en contenedor se purga a través de `purge_for_conversation` | **Los bytes de los adjuntos bajo `MEDIA_DIR`.** Ninguna ruta borra un archivo de chat; el único camino de código que desenlaza uno descarta la subida huérfana de un bot de canal. Las filas de runs y los manifiestos que nombraban la conversación conservan su copia del prompt. Se sigue en [#1421](https://github.com/vstorm-co/agenticos/issues/1421) |
| `DELETE /memory/person/{user_id}` (la persona, o `members:manage`) | Cada fila de `agent_memory_files` con clave en la persona a lo largo de todos los agents de la organización, y lo mismo en cada almacén mem0 vinculado | Las notas con clave en un chat de grupo en el que la persona habló |
| `DELETE /users/{id}` | La cuenta, sus sesiones, su organización personal y sus colecciones personales con sus tablas vectoriales y archivos, por desmontaje explícito; conversaciones y archivos de chat en cascada | **La memoria de la persona** — `owner_key` es una cadena, no una clave ajena, así que las entradas de `agent_memory_files` y de mem0 sobreviven salvo que antes se haya ejecutado `DELETE /memory/person`. Las entradas de auditoría que nombran el id del actor y, en algunas acciones, el correo; los mensajes en conversaciones compartidas; los bytes de adjuntos de arriba. El inventario de cada uno es el entregable de [#1421](https://github.com/vstorm-co/agenticos/issues/1421) |
| Borrar un documento o una colección | Las filas, la tabla vectorial y el archivo almacenado, mediante un flow duradero tras el commit | Nada, una vez que el flow ha corrido; los recuentos de `sync_logs` permanecen |
| Borrar una organización | Todo lo acotado a ella, con el mismo desmontaje diferido | Las colecciones personales que solo llevaban el id |

Ninguno de estos alcanza una copia de seguridad. Una restauración devuelve lo
que se había borrado, así que la caducidad de las copias forma parte de la
política de retención y se escribe junto a ella.

## Qué tiene que decidir y obtener un deployment { #what-a-deployment-has-to-decide-and-obtain }

El software no puede aportar ninguna de estas cosas. Cada una es una prueba que
pedirá la revisión, distinta de la capacidad técnica que la hace posible.

- **Un contrato de encargo con cada subencargado configurado** — cada provider
  que nombre una fila de `model_profiles` o de `organization_secrets`, el
  provider de embeddings, LlamaCloud si lo usa alguna colección, el proveedor de
  búsqueda que nombre el `method` de un agent, el host de mem0, Logfire, el
  relay SMTP y Google si el inicio de sesión está habilitado.
- **Una declaración de ubicación de datos por provider**, cotejada con la
  `base_url` que cada perfil usa realmente. Un provider con endpoint en la UE
  solo está en la UE si el perfil lo dice.
- **Una exclusión de entrenamiento por provider**: el ajuste de cuenta o la
  cláusula contractual por la que los datos de la API no se usan para entrenar.
  La posición de la propia plataforma es una frase — no entrena nada — y el
  resto es cosa suya.
- **Un contrato de encargo con Vstorm**, solo si Vstorm opera el deployment.
- **Un calendario de retención** para conversaciones, archivos, memoria,
  documentos, runs y auditoría, y junto a él la caducidad de las copias de
  seguridad. Hasta que
  [#1420](https://github.com/vstorm-co/agenticos/issues/1420) imponga uno, la
  retención es un borrado manual.
- **Cifrado de disco o de volumen** en el host de la base de datos, el volumen
  de medios y el host de la sandbox, ya que la aplicación no cifra el contenido
  por sí misma — y una regla de salida en el host de la sandbox si los agents
  pueden ejecutar comandos.
- **Las páginas legales** a las que enlaza el deployment, y quién responde a una
  solicitud de acceso o supresión mientras
  [#1421](https://github.com/vstorm-co/agenticos/issues/1421) siga abierta.

## Verificar un deployment { #verifying-one-deployment }

Comprobaciones reproducibles, desde el host, contra el deployment en marcha.
Cada una imprime hechos que la revisión puede adjuntar; ninguna imprime una
credencial ni los datos de una persona. Ejecuta los comandos desde `backend/`, o
a través de `docker compose exec api`.

```bash
# 1. ¿Puede arrancar, y van cifradas las conexiones a los almacenes?
#    `postgres` informa del estado TLS de la conexión que el propio doctor hizo.
uv run agenticos cmd doctor

# 2. Toda credencial sellada sigue abriéndose con las claves maestras
#    configuradas.
uv run agenticos cmd vault-rotate --dry-run

# 3. Los ajustes que deciden qué sale. Vacío es la respuesta silenciosa.
env | grep -E '^(ENVIRONMENT|LOGFIRE_TOKEN|LOGFIRE_BASE_URL|MEM0_ALLOWED_HOSTS|POSTGRES_SSLMODE|REDIS_SSL|SMTP_TLS|LOG_PROVIDER_WRITE_TO_DISK|RATE_LIMIT_TRUST_FORWARDED_FOR)=' \
  | sed -E 's/(KEY|TOKEN)=.+/\1=<set>/'
```

`LOG_PROVIDER_WRITE_TO_DISK` tiene que ser `false` fuera de desarrollo: el
provider de correo que registra en log escribe cuerpos de mensaje enteros en
disco cuando está activo.

```sql
-- 4. Todos los providers y endpoints que un agent puede alcanzar, sin las
--    claves.
SELECT o.name AS organization, p.label, p.provider, p.model, p.base_url
FROM model_profiles p JOIN organizations o ON o.id = p.organization_id
ORDER BY 1, 2;

-- Perfiles que hablan HTTP plano. Cada uno debe apuntar a la propia red del
-- deployment; cualquier otra cosa envía los prompts y la clave en claro.
SELECT label, provider, base_url FROM model_profiles WHERE base_url LIKE 'http://%';

SELECT o.name AS organization, s.purpose, s.kind, s.name
FROM organization_secrets s JOIN organizations o ON o.id = s.organization_id
ORDER BY 1, 2;

-- Colecciones: quién genera sus embeddings y cuáles parsean fuera.
SELECT name, embedding_provider, embedding_model,
       ingestion_config ->> 'pdf_parser' AS pdf_parser,
       ingestion_config ->> 'llamaparse_secret_id' IS NOT NULL AS llamaparse_key,
       embedding_endpoint_id, ingestion_config ->> 'ocr_endpoint_id' AS ocr_endpoint_id
FROM knowledge_bases ORDER BY 1;

-- Los servidores de tu propia red a los que se pueden apuntar las colecciones.
-- Toda dirección de aquí debería ser una que operes tú.
SELECT o.name AS organization, s.kind, s.provider, s.name, s.base_url, s.is_active
FROM local_services s LEFT JOIN organizations o ON o.id = s.organization_id
ORDER BY 1 NULLS FIRST, 2, 4;

SELECT scope, name, url, auth_type FROM mcp_connections WHERE is_enabled ORDER BY 1, 2;
SELECT name, connector_type, collection_name FROM sync_sources WHERE is_active ORDER BY 2, 1;

-- 5. Runs trazados a un proyecto propio: un token en el spec publicado, o en un
--    entorno.
SELECT a.slug, v.version, 'spec' AS via
FROM agent_versions v JOIN agents a ON a.id = v.agent_id
WHERE v.spec -> 'observability' ->> 'token_secret_id' IS NOT NULL
UNION ALL
SELECT a.slug, NULL, 'environment ' || e.name
FROM agent_environments e JOIN agents a ON a.id = e.agent_id
WHERE e.logfire_token_secret_id IS NOT NULL;

-- 6. A qué tendría que llegar la retención. Ajusta la antigüedad al calendario
--    decidido.
SELECT 'conversations' AS store, count(*) FROM conversations WHERE created_at < now() - interval '365 days'
UNION ALL SELECT 'agent_runs', count(*) FROM agent_runs WHERE created_at < now() - interval '365 days'
UNION ALL SELECT 'audit', count(*) FROM app_admin_audit_logs WHERE created_at < now() - interval '365 days'
UNION ALL SELECT 'agent_memory_files', count(*) FROM agent_memory_files
UNION ALL SELECT 'chat_files', count(*) FROM chat_files;
```

```bash
# 7. Bytes de adjuntos cuyas filas ya no están. Una fila chat_files desaparece
#    en cascada con su mensaje mientras el archivo se queda, así que la
#    diferencia crece con cada conversación borrada (ver "Qué alcanza el
#    borrado"). Las imágenes generadas y el directorio temporal de parseo no
#    tienen fila por diseño y quedan excluidos. A través del contenedor de la
#    base de datos: la API conoce su cadena de conexión solo como un ajuste
#    calculado, no como una variable que pudiera leer un shell.
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT storage_path FROM chat_files
  UNION SELECT storage_path FROM rag_documents WHERE storage_path IS NOT NULL" \
  | sort > /tmp/referenced.txt
(cd "${MEDIA_DIR:-./media}" && find . -type f -not -path './generated_*' -not -path './_rag_tmp/*' \
  | sed 's|^\./||' | sort) > /tmp/on_disk.txt
comm -23 /tmp/on_disk.txt /tmp/referenced.txt | wc -l      # archivos que nada referencia
```

Los avatares y los logos de embeds también están en disco y se referencian desde
`users.avatar_url` y `agent_embeds.logo_path`; añade esas columnas a la consulta
si el recuento de arriba no es cero y quieres la lista exacta.

Adjunta la salida de los puntos 1 a 6 a la revisión junto con los acuerdos de la
sección anterior. El punto 7 es un recuento que vigilar hasta que
[#1421](https://github.com/vstorm-co/agenticos/issues/1421) elimine los bytes
con la conversación.

## Condiciones abiertas para una primera puesta en marcha { #open-conditions-for-a-first-rollout }

Escritas para el deployment para el que se redactó esta página, y ciertas de
cualquier deployment hasta que cada una se cierre.

**En el código, con seguimiento:**

- Las trazas llevan contenido completo — [#1413](https://github.com/vstorm-co/agenticos/issues/1413).
- No hay retención programada — [#1420](https://github.com/vstorm-co/agenticos/issues/1420).
- Los bytes de los adjuntos y la memoria de una persona sobreviven al borrado de
  su propietario; no hay exportación de datos personales; el inventario de
  supresión — [#1421](https://github.com/vstorm-co/agenticos/issues/1421).
- No hay exportación de auditoría ni prueba de no manipulación — [#1422](https://github.com/vstorm-co/agenticos/issues/1422).
- Archivos solo en disco local, cifrados por el volumen o nada — [#1423](https://github.com/vstorm-co/agenticos/issues/1423).
- No hay vista de autoservicio de la propia memoria — [#1594](https://github.com/vstorm-co/agenticos/issues/1594).
- No hay inicio de sesión OIDC — [#1419](https://github.com/vstorm-co/agenticos/issues/1419).
- La matriz de controles de HIPAA y SOC 2 — [#1412](https://github.com/vstorm-co/agenticos/issues/1412).

**En el deployment, decidido por su operador:** los acuerdos, las ubicaciones,
las exclusiones de entrenamiento, el calendario de retención, la caducidad de
las copias, el cifrado de disco, la salida de la sandbox y las páginas legales
de la sección anterior.

Una revisión que encuentre cada fila de arriba cerrada o aceptada por escrito
tiene lo que esta página puede darle. El resto es del deployment.
