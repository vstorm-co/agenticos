---
source_sha: "18de9f68880b"
---

# La API HTTP { #the-http-api }

Todo lo que hace la consola, lo hace a través de esta API. No hay una superficie
privada: los mismos endpoints están a tu disposición.

La referencia interactiva se genera a partir del código y la sirve el propio
despliegue en **`/docs`**, con el esquema en
`/api/v1/openapi.json`. Ambas están activas en desarrollo y desactivadas en
producción — lo decide `ENVIRONMENT`, así que un despliegue de producción no
publica su propia lista de rutas.

## Autenticarse { #authenticating }

Tres formas de entrar, para tres llamantes distintos.

| | Cabecera | Para |
|---|---|---|
| **Clave de API de la organización** | `Authorization: Bearer aos_…` | Un script, un cliente HTTP como Postman o un cliente MCP. Actúa como el miembro que la emitió, limitada a los permisos con los que se emitió |
| **JWT** | `Authorization: Bearer <access token>` | Una persona, o algo que actúa en su nombre. De vida corta, renovado con un refresh token |
| **Cookie de sesión** | la pone la consola | Solo el navegador: el token es HttpOnly y nunca llega a JavaScript |

### Claves de API de la organización { #organization-api-keys }

Una clave la emite un miembro, en una organización, desde **Settings → API**
(o con `POST /api/v1/api-keys` desde una sesión iniciada). Lleva la autoridad de
ese miembro, limitada dos veces:

- **A los permisos con los que se emitió.** Elige una plantilla — *Read-only*,
  *Knowledge ingest*, *Full access* — o marca permisos del
  [catálogo](permissions.md). Solo puedes conceder lo que tienes.
- **A lo que el emisor puede hacer ahora.** Cada petición vuelve a leer la
  membresía del emisor, así que degradarlo limita al instante cada una de sus
  claves. Sacarlo de la organización, o que se vaya, revoca todas las claves que
  emitió y todas las apps que conectó - para siempre, así que volver a invitarlo no
  reactiva ninguna. Un
  permiso concedido sobre un recurso amplía lo que una *persona* puede hacer con
  una fila; nunca amplía una clave más allá de sus permisos.

La clave se muestra **una vez**, en la respuesta que la crea. Solo se guarda su
SHA-256, y nunca aparece en una línea de log, una entrada de auditoría ni el
cuerpo de un error. Las listas muestran su prefijo (`aos_1a2b3c4d`), que es
también como una entrada de auditoría nombra la clave que actuó: cada entrada
registrada durante una petición autenticada con clave lleva `via_api_key` en sus
detalles. Una clave puede caducar, y revocarla (`DELETE /api/v1/api-keys/{id}`)
surte efecto en su siguiente petición.

**Una clave no es la persona que la emitió.** Un run que inicia pertenece a quien
la emitió, cuenta en su presupuesto y en su auditoría, pero no alcanza nada
personal suyo: ni la
[memoria](reference/capabilities.md#whose-notes-and-who-may-hear-them), ni la
búsqueda en sus conversaciones anteriores, ni los sitios en los que el navegador
guarda sus inicios de sesión, ni el espacio de trabajo del sandbox ligado al
usuario. Quien tiene la clave es un script, no esa persona, así que el run
responde como en un widget público.

La consulta de conexiones también es pública y de solo lectura:
`GET /sandbox-connections`, `GET /sandbox-connections/runtimes` y
`GET /sandbox-connections/{id}/policy` requieren `connections:view`;
`GET /mcp-connections` requiere `mcp:manage`. Siguen vigentes la organización
y los permisos de la clave. Las escrituras de conexiones y las operaciones
con credenciales siguen requiriendo una sesión.

```bash
curl "$BASE/api/v1/me/permissions" \
  -H "Authorization: Bearer $AGENTICOS_KEY"
```

Conviene conocer dos rechazos:

- **`403` "API keys are not accepted on this endpoint"**: las claves solo se
  aceptan en la API pública: agents, runs y aprobaciones, bases de conocimiento y
  RAG, skills, archivos de contexto, proyectos, aplicaciones, los servicios de ML,
  `/me/permissions` y los miembros, invitaciones, grupos y ajustes de una
  organización. Las rutas propias de la consola, tu cuenta, abandonar o traspasar
  una organización y la gestión de claves en sí siguen siendo solo de sesión, para
  que una clave filtrada no pueda acuñar su sucesora.
- **`401` "Invalid, expired or revoked API key"**: la misma frase en cada caso,
  para que una clave equivocada no aprenda nada sobre qué claves existen.

Cada clave tiene además su propio límite, `RATE_LIMIT_API_KEY_PER_MINUTE`
peticiones por minuto (600 por defecto), y un run o una llamada de ML que haga
cuenta contra esos límites para la clave y no para su emisor. Ambas comprobaciones
ocurren antes de buscar la clave, en una petición y al abrir un WebSocket: una clave
se cuenta por un digest del token entero - nunca por su prefijo, que las listas
muestran - y
una dirección que ya envió `RATE_LIMIT_AUTH_PER_MINUTE` claves inexistentes
recibe `429` sin búsqueda hasta que termine su minuto.

### Sin navegador { #without-a-browser }

Un script puede conseguir su propia clave sin abrir la consola. Inicia sesión con
un cuerpo de formulario (el password grant de OAuth2, así que JSON recibe `422`),
elige la organización, emite la clave con el token de sesión y revócala igual
cuando haya terminado:

```bash
SESSION=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -d "username=$EMAIL" --data-urlencode "password=$PASSWORD" | jq -r .access_token)

ORG_ID=$(curl -s "$BASE/api/v1/orgs" -H "Authorization: Bearer $SESSION" \
  | jq -r '[.items[] | select(.is_personal)][0].id')

curl -s -X POST "$BASE/api/v1/api-keys" \
  -H "Authorization: Bearer $SESSION" -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"name": "nightly import", "scopes": ["collections:view", "collections:edit"]}'
# -> {"id": "...", "key": "aos_...", "prefix": "aos_1a2b3c4d", ...}

curl -s -X DELETE "$BASE/api/v1/api-keys/$KEY_ID" \
  -H "Authorization: Bearer $SESSION" -H "X-Organization-Id: $ORG_ID"
```

`GET /api/v1/api-keys/scopes` lista lo que el miembro con sesión puede
poner en una clave, y los presets sobre ello. Un despliegue que solo inicia
sesión mediante SSO no tiene contraseña que enviar; allí un miembro emite la
clave en la consola.

[`examples/public-api.sh`](examples/public-api.sh) es todo el recorrido en un
script: emite una clave de solo lectura, lista con ella agents y runs, muestra el
`403` de una ruta fuera de los permisos de la clave, ejecuta un agent y lee el
run cuando `AGENT_ID` está definido, y revoca la clave al salir.

```bash
BASE=http://localhost:8000 EMAIL=you@example.com PASSWORD=... bash docs/examples/public-api.sh
```


### Sesiones y revocación { #sessions-and-revocation }

Un access token JWT queda ligado a la sesión que abrió su inicio de sesión — el id
de la sesión viaja dentro del token. Cerrar sesión en todas partes
(`DELETE /sessions`) desactiva esas sesiones, y un token ligado se rechaza en su
siguiente uso en lugar de agotar los pocos minutos que le quedaban. Eso alcanza
también a un WebSocket de chat abierto: el siguiente frame de una sesión revocada
cierra el socket, no solo la siguiente petición HTTP.

Renovar no abre una sesión nueva — el refresh token rota en su sitio y el access
token sigue nombrando la misma — así que una conexión de larga vida no se corta
por una renovación rutinaria.

## La cabecera de organización { #the-organization-header }

**Una clave de API actúa en su propia organización** y no necesita cabecera.
Enviar `X-Organization-Id` con una clave solo se permite si nombra esa misma
organización; nombrar otra responde `400` con
`details.header = "X-Organization-Id"` en lugar de cambiar de inquilino.

**Un token de sesión toma el inquilino de `X-Organization-Id`.** Quien pertenece
a tres organizaciones es un principal distinto en cada una, con otro rol y otros
permisos concedidos, así que envía la cabecera en cada petición. Si falta, la
petición vuelve a la **organización por defecto** del despliegue si el llamante
pertenece a ella, luego a su **organización personal**, luego a la única que
tenga: un script que olvide la cabecera actúa allí, con los agents, permisos y
budget de esa organización, y no recibe ningún error. Quien pertenece a varias y
no tiene ninguna de ellas recibe un `400` con
`details.header = "X-Organization-Id"` en vez de una suposición
([dónde empieza una cuenta nueva](deployment.md#where-a-new-account-starts)).
Envía la equivocada y obtendrás un rechazo idéntico al de un recurso inexistente,
a propósito, para que los ids no se puedan sondear.

## Ejecutar un agent { #running-an-agent }

```bash
curl -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "How do I rotate a provider key?"}'
```

La respuesta trae el id del run, la salida, el estado, los tokens y el coste.
`environment_id` en el cuerpo elige [qué entorno](environments.md) responde.
`"draft": true` ejecuta en su lugar el borrador sin publicar, como el panel de
pruebas del Builder: un run de prueba, para una clave cuyo emisor puede editar el
agent, rechazado con el motivo cuando el borrador no se publicaría, y nunca con
`Prefer: respond-async`.

Una clave también llega a las rutinas de un agent - `GET /api/v1/triggers` y
`GET`, `POST`, `PATCH` y `DELETE` bajo `/api/v1/agents/{agent_id}/triggers`, más
`POST .../{trigger_id}/run` para lanzar una ahora - y a los modelos de la
organización en `GET /api/v1/providers/model-profiles`. Tres rutas actúan sobre
el propio emisor: `GET /api/v1/me/mcp-connections` lista los servicios que conectó
con su propia cuenta, `PUT /api/v1/users/me/locale` le fija el idioma de la consola
en cada dispositivo, y `PATCH /api/v1/users/me/agent-context` guarda su rol
(`job_title`) y en qué trabaja (`about`), lo que se le dice a cada agent. Cada una
necesita una clave emitida para `agents:run`.

`POST /api/v1/agents` crea un agent a partir del spec del cuerpo y deja vacío un
campo vacío. Con `"from_starter": true` rellena lo que el spec omite - las
instrucciones, los skills, las herramientas propias de la plataforma y el
presupuesto - desde el agent inicial AgenticOS, como hace **New agent** en la
consola.

**Un run continúa una conversación.** Una llamada sin `conversation_id` abre una
conversación nueva para quien emitió la clave y devuelve su id como
`conversation_id`; envíalo en la siguiente llamada y el agent lee lo que se dijo
antes - los últimos turnos, o el resumen de los anteriores y lo que vino
después. Un workspace compartido por conversación, el valor por defecto, es el de
esa conversación. Un id desconocido, o la conversación de otra persona, responde
`404`; una conversación propia de quien emitió la clave desde la consola o un canal
responde `400` - una clave que puede ejecutar agents no recibió los chats de esa
persona. Lo mismo con una ejecución aparcada: una clave reanuda o responde solo una
ejecución que inició una clave, y una que inició la persona responde `403`, porque
continuarla actúa en su nombre. La conversación se guarda en la lista de chats de quien emitió la clave con
la etiqueta **API** y queda oculta hasta que las muestre allí con un interruptor.

`GET /api/v1/conversations/{id}/transcript` lee una de las conversaciones de
quien emitió la clave turno a turno, con las herramientas que llamó cada turno y
lo que costó, para una clave con `runs:view`.

!!! info "Un llamante de la API no puede esquivar el governance"

    Este endpoint pasa por el mismo runner que la consola, Slack y el widget. El
    run queda registrado, el budget se comprueba antes de la petición al modelo,
    la puerta de aprobación se aplica, y el coste acaba en el mismo dashboard.

    Ese es el sentido de tener un único runner, y por eso no existe una "vía
    rápida" que se lo salte.

### Sin mantener la conexión { #without-holding-the-connection }

Un run de minutos - una navegación, una cadena larga de herramientas - mantiene
la petición abierta todo el tiempo, y el tiempo límite de lectura de un proxy
puede cortarla mientras el run sigue. Envía `Prefer: respond-async` y la llamada
responde `202` al instante, con una petición de run que consultar:

```bash
curl -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -H "Prefer: respond-async" \
  -H "Idempotency-Key: ticket-4711" \
  -d '{"prompt": "Summarise this quarter for the board"}'
# 202, Location: /api/v1/run-requests/{id}, Preference-Applied: respond-async

curl "$BASE/api/v1/run-requests/$REQUEST_ID" -H "Authorization: Bearer $AGENTICOS_KEY"
```

La petición pasa por `queued`, `running` y después `completed` con `result` -
el mismo cuerpo con el que responde la llamada síncrona - o `failed` con
`error`. Su `conversation_id` se conoce desde la primera respuesta, así que se
puede enviar un mensaje de seguimiento antes de que termine el run. Lo ejecuta
un worker, con el mismo runner, budget y aprobaciones que cualquier otra
superficie.

Lo que se puede comprobar al momento se comprueba al momento: una conversación
o un adjunto desconocidos son un `404` en el `POST`, no un fallo que haya que
esperar. Los permisos de la clave se vuelven a comprobar cuando el run arranca,
así que una clave revocada mientras su run esperaba no lo ejecuta. Solo quien lo
pidió, o una clave suya, puede leer una petición de run; la de otro responde
`404`. Un run asíncrono tiene un intento: un run que falla queda registrado con
lo que gastó y no se reintenta para no gastarlo dos veces.

La ruta lleva un **límite de frecuencia en lugar de una puerta de permisos**. El
permiso se decide dentro del servicio, contra los grants de ese agent concreto —
una puerta de rol en una ruta por recurso [no puede verlos](permissions.md).

`PATCH /api/v1/agents/{id}/metadata` fija las **categories** y los **tags** de un
agent con un cuerpo del estilo `{"categories": [...], "tags": [...]}`, donde una
lista vacía borra esa faceta. Los valores se normalizan — recortados, con los
espacios colapsados, plegados en mayúsculas/minúsculas y sin duplicados — y se
acotan: como mucho 10 categories y 20 tags, cada uno de 32 caracteres como
máximo, y un elemento más largo responde `422`. Igual que la ruta run, no lleva
puerta de rol; decide la comprobación `agents:edit` con conciencia de grants
dentro del servicio, así que un viewer con un grant de edición sobre un agent
puede etiquetarlo.

`GET /api/v1/agents` filtra ese catálogo con los parámetros de consulta
repetibles `category` y `tag`: los valores se combinan con **OR dentro de una
faceta** y **AND entre facetas**, con coincidencia sin distinguir
mayúsculas/minúsculas (un valor de consulta se pliega como uno almacenado, y un
valor en blanco se ignora). El filtro solo estrecha lo que ya podías ver — nunca
cruza una frontera de tenant ni de grant.

La respuesta también trae `categories` y
`tags`: cada etiqueta distinta en los agents que podrías listar, sea cual sea el
filtro y la página — las opciones que ofrece un menú de filtro. Un agent privado que
no puedes ver no aporta ninguna.
## Agents por A2A { #agents-over-a2a }

Un agent que su organización sirve por A2A responde JSON-RPC en
`POST /api/v1/a2a/{agent_id}`, con las mismas claves que `/run`; su agent card está
en `GET /api/v1/a2a/{agent_id}/.well-known/agent-card.json` y no necesita ninguna.
`PUT /api/v1/agents/{id}/a2a` con `{"enabled": true}` lo activa, para quien tenga
`agents:publish` sobre ese agent.

```bash
curl -X POST "$BASE/api/v1/a2a/$AGENT_ID" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "message/send",
       "params": {"message": {"role": "user", "messageId": "m1",
                              "parts": [{"kind": "text", "text": "Review clause 7"}]}}}'
```

La respuesta es una `Task` cuyo id es el del run y cuyo `contextId` continúa la
conversación. `tasks/get` vuelve a leer una. Los [canales](channels.md#a2a) tienen
el resto.

Los agents remotos en los que delega esta organización se registran en
`/api/v1/external-agents`: `GET` los lista (`agents:view`); `POST` con una
`card_url`, un `slug` opcional y un `secret_id` opcional de una clave API lee la card
y lo registra, y `POST /{id}/refresh` la vuelve a leer; `DELETE /{id}` elimina uno
(`agents:edit` para los tres).

## Los servicios de ML { #the-ml-services }

Cuatro servicios de la plataforma responden por su cuenta, sin conversación y sin
un agent detrás: análisis de documentos, OCR, transcripción de voz y detección de
datos personales. Los controla `ml:invoke`, no `agents:run`, y
[Los servicios de ML](ml-services.md) es su referencia.

```bash
curl -X POST "$BASE/api/v1/ml/privacy/pii" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "write to ada@example.com"}'
```

## Ejemplos paso a paso { #worked-examples }

Cada uno funciona con una clave de la organización en `$AGENTICOS_KEY` y el origen
de la API en `$BASE`. Crea la clave en **Settings → API** con los permisos que
nombra el ejemplo; la consola la muestra una vez.

**Sube un documento a una base de conocimiento y búscalo** — una clave con
`collections:view` y `collections:edit` (la plantilla *Knowledge ingest*). La
ingesta corre en segundo plano, así que una búsqueda justo después de subirlo puede
no encontrarlo todavía; `GET /api/v1/kb/$KB_ID/documents` muestra su estado.

```bash
# Find the knowledge base, upload a file into it, and search it.
curl "$BASE/api/v1/kb" -H "Authorization: Bearer $AGENTICOS_KEY"

curl -X POST "$BASE/api/v1/kb/$KB_ID/documents" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -F "file=@policy.pdf"

curl -X POST "$BASE/api/v1/rag/search" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"collection_name\": \"$COLLECTION_NAME\", \"query\": \"refund window\"}"
```

**Ejecuta un agent y consulta lo que costó** — `agents:run` y `runs:view`. La
lectura del run trae su estado, sus tokens y su coste.

```bash
RUN_ID=$(curl -s -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarise this week'"'"'s tickets"}' | jq -r .run_id)

curl "$BASE/api/v1/runs/$RUN_ID" -H "Authorization: Bearer $AGENTICOS_KEY"
```

**Invita a un miembro** — `members:manage`. La invitación se envía por correo; la
respuesta trae su token una vez, por si el correo del invitante no llega.

```bash
curl -X POST "$BASE/api/v1/orgs/$ORG_ID/invitations" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email": "new.hire@example.com", "role": "member"}'
```

**Reintenta lo que chocó con el límite, y nada más.** Un `429` trae `Retry-After`;
cualquier otro rechazo es definitivo para esa petición, y un `401` significa que la
clave ya no existe — revocada, caducada o su emisor eliminado —, así que
reintentarlo solo gasta el límite.

```python
import time

import httpx


def call(client: httpx.Client, method: str, path: str, **kwargs) -> httpx.Response:
    for _ in range(5):
        response = client.request(method, path, **kwargs)
        if response.status_code != 429:
            response.raise_for_status()
            return response
        time.sleep(int(response.headers.get("Retry-After", "60")))
    response.raise_for_status()
    return response


client = httpx.Client(
    base_url="https://agenticos.example.com/api/v1",
    headers={"Authorization": f"Bearer {KEY}"},
)
print(call(client, "GET", "/me/permissions").json())
```

## Streaming { #streaming }

Dos endpoints WebSocket, para dos públicos.

- **`/api/v1/ws/agent`**: el autenticado que usa la consola. Un frame con
  `agent_id` ejecuta ese agent publicado; un frame sin él llega al asistente
  general. El `conversation_id` de un frame continúa esa conversación; `null`
  empieza una nueva, y omitir la clave continúa aquella en la que este socket
  escribió por última vez. Autentícate con el subprotocolo `access_token.<token>`, donde el token
  es un JWT de sesión. Una clave de API de la organización se rechaza aquí: un
  turno en este socket es una persona al teclado, con sus conexiones personales.
  Las integraciones ejecutan agents con `POST /api/v1/agents/{id}/run`.
- **`/api/v1/embed/{public_key}/ws`** — el público, detrás de un
  [embed](channels.md), para un visitante que no tiene cuenta.

Los dos emiten tokens según llegan (un agent con guardrail de salida transmite paso
a paso, consulta [Guardrails](reference/capabilities.md#guardrails)) y los dos
producen un run corriente, con la misma contabilidad que todo lo demás.

Un tercero, **`/api/v1/ws/events`**, solo escucha. Es como una consola abierta
[se mantiene al día con los cambios hechos en otro lugar](console.md#changes-made-elsewhere):
autenticado igual, con la organización en `?organization_id=`, envía un frame JSON
por cada escritura correcta a través de la API pública en esa organización —
`resource`, `id`, `action` (`created`, `updated` o `deleted`), `surface`
(`console`, `api_key`, `mcp` o `assistant`) y quién la hizo — y solo sobre filas
que quien llama puede leer.

## Llamadas de voz { #voice-calls }

Una [llamada de voz](voice.md) tiene un socket propio, porque una llamada no es
un bucle de turnos: **`/api/v1/ws/voice`** para un miembro, y
**`/api/v1/embed/{public_key}/voice/ws`** para un visitante en un widget o una
página alojada ([admisión](channels.md#the-call-socket)). Los dos hablan los
mismos frames, definidos en `backend/app/schemas/voice.py`.

El socket de la consola se autentica igual que `/ws/agent`: el token como una
entrada `access_token.<JWT>` de `Sec-WebSocket-Protocol` (o la cookie del mismo
origen), nunca en la query string, y la organización como `?organization_id=`.
Se cierra con `4001` sin una sesión válida y con `4003` cuando quien llama no es
miembro o se autentica con una clave API de la organización: una llamada es una
persona ante el micrófono, como un turno de chat es una persona ante el teclado.

El socket del embed se cierra con `4029` al pasar un rate limit y con
`4003` ante cualquier rechazo relativo al embed. Cada latido vuelve a comprobar
la sesión, así que una llamada no sobrevive a un cierre de sesión.

**El cliente envía** frames JSON, y a través del relay también audio binario:

| Frame | Campos | Cuándo |
|---|---|---|
| `start` | `agent_id`, `conversation_id`, `sdp_offer` (WebRTC), `resume_of` y `resume_token` (una reconexión), `context` (las variables de un embed) | Primero, en 10 segundos como mucho |
| `approval` | `id`, `decision` (`approve` o `deny`) | Al decidir una aprobación que la llamada está esperando |
| `mute` | `muted` | El relay: el micrófono silenciado |
| `played` | `bytes` | El relay: cuánto audio del agent se ha reproducido |
| `end` | - | Colgar |
| *binario* | PCM de 16 bits a la frecuencia de entrada del modelo | El relay: el audio de quien llama |

**El servidor envía:**

| Frame | Campos | Significa |
|---|---|---|
| `answer` | `sdp` | WebRTC: la respuesta del provider para la conexión peer del navegador |
| `ready` | `call_id`, `run_id`, `conversation_id`, `transport`, `input_sample_rate`, `output_sample_rate`, `cap_seconds`, `resume_token` | La llamada está establecida. `resume_token` se envía solo aquí, solo a quien llama; una reconexión lo devuelve |
| `state` | `state`: `connecting`, `listening`, `user_speaking`, `thinking`, `agent_speaking`, `interrupted`, `tool_running`, `awaiting_approval` | Quién habla, o qué está haciendo el agent |
| `caption` | `role`, `turn_id`, `part`, y uno de `delta` (añadir), `text` (sustituir por el texto revisado hasta ese momento) o `final` | Un subtítulo en vivo |
| `turn_saved` | `message` | Un turno terminado, como el mensaje con el que se guardó; sustituye a los subtítulos que llevan su `turn_id` |
| `tool` | `name`, `status` (`running` o `done`) | Una herramienta que está ejecutando el agent |
| `approval_required` | `id`, `tool`, `args`, `said`, `timeout_seconds` | Una aprobación para la persona de la llamada: los argumentos exactos y lo que se le oyó decir |
| `approval_unavailable` | `tool`, `args` | Una llamada a herramienta que quien llama no puede aprobar por voz |
| `approval_settled` | `id`, `outcome` (`approved`, `denied` o `expired`) | Cómo terminó una aprobación |
| `notice` | `kind`, `message` (opcional) | Algo que decir con palabras: un guardrail que salta, un límite que se alcanza |
| `limit` | `seconds_left` | El tiempo de la llamada casi se ha agotado |
| `clear_playback` | - | El relay: descartar el audio del agent en cola |
| `ended` | `reason`, `message` | La llamada ha terminado |
| *binario* | PCM de 16 bits a la frecuencia de salida del modelo | El relay: el audio del agent |

**A un visitante de un widget o de una página alojada se le dice menos.** Su
`ready` no incluye `run_id`; `cap_seconds` es el límite de la llamada - la
llamada más larga del agent o lo que queda de una llamada que se reanuda. Los
frames de herramientas siguen los interruptores
`show_tool_steps` y `show_tool_results` del embed, como los de una respuesta
escrita. Sin pasos de herramientas no se envía ningún frame `tool` y
`tool_running` llega como `thinking`. Sin resultados de herramientas,
`approval_unavailable` llega con `args` vacíos. El `turn_saved` de un
visitante lleva solo el `id`, `role`, `content`, `interrupted` y `turn_id` del
mensaje, sean cuales sean los interruptores: nunca los ids de su run, de su
agent o de su versión, ni su coste ni sus llamadas a herramientas.

**Una reconexión demuestra que la llamada es suya.** Un `start` con `resume_of`
debe llevar también el `resume_token` del `ready` de esa conexión. Sin él, o
con uno incorrecto, la reconexión se rechaza como `resume_refused` y la llamada
que nombra no se toca. El servidor guarda solo un hash del token. Una llamada
que ya consta de 20 conexiones no se reanuda más: su siguiente reconexión
también se rechaza como `resume_refused`.

Un socket que no envía `start` en 10 segundos recibe `ended` con `no_start`.
Una llamada que no va a empezar responde con `ended` y un `reason` estable:
`no_agent`, `forbidden`, `not_configured`, `bad_offer`, `data_channel`,
`resume_refused`, `call_limit`, `not_priced`, `budget`, `busy` o `line_busy`,
con un `message` que se puede mostrar. `busy` solo llega después de que una
llamada que la misma persona acaba de colgar haya tenido hasta cuatro segundos
para terminar. Un inicio que falla por cualquier otro motivo responde con `ended` y
`error`.

Un visitante rechazado como `not_configured`, `not_priced` o `budget`, o cuya
llamada termina como `budget`, recibe en su lugar `unavailable` con el mensaje "Calls are not available right
now.": el código y el mensaje completo son cosa del operador del agent. Una llamada a una conversación archivada se rechaza como
`forbidden`, igual que un mensaje escrito en ella.

Una llamada que se llegó a mantener termina con `user`, `time_limit`, `budget`,
`disconnected`, `revoked`, `guardrail`, `shutdown` o `error`; con `time_limit`
cuando alcanzó la llamada más larga del agent. La llamada de un visitante termina con
`revoked` cuando su embed se pausa, se le desactivan las llamadas o se apunta a
otro agent. Ningún frame lleva nunca una credencial del provider.

La acompañan cinco rutas HTTP:

| Ruta | Control | Responde |
|---|---|---|
| `GET /api/v1/agents/{agent_id}/voice` | `agents:run` sobre ese agent, grant incluido; `404` en caso contrario | Si una llamada empezaría, por qué no (`no_voice`, `not_offered` o `no_key`), el transporte y la llamada más larga |
| `POST /api/v1/agents/{agent_id}/voice/preview` | `agents:edit` sobre ese agent, grant incluido; `404` en caso contrario | La voz del borrador de la sección Voice diciendo una frase fija, como `audio/wav`. En caché por voz e idioma; `RATE_LIMIT_VOICE_PREVIEW_PER_MINUTE` por persona |
| `GET /api/v1/providers/realtime-models` | `agents:view` | El catálogo en tiempo real del que elige la sección Voice |
| `GET /api/v1/voice/usage?start=…&end=…` | `runs:view` | Segundos de llamada y llamadas de las llamadas iniciadas en `start` o después y antes de `end`, por agent (las llamadas de un agent eliminado como una sola fila sin id ni nombre). Un `end` que no sea posterior a `start` se rechaza con `422` |
| `GET /api/v1/runs?modality=voice` | `runs:view` | Solo llamadas (`text` para solo runs escritos); una llamada que se reconectó es una fila que lleva `voice_chain`, con todas las conexiones sumadas |

Una aprobación que pertenece a una llamada en curso se decide en la llamada:
`POST /api/v1/approvals/{id}` la rechaza con `400`.

## Errores { #errors }

Un único sobre, en todas partes:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Agent not found",
    "details": { "agent_id": "..." }
  }
}
```

`details` lleva valores y no filas, así que nombra el campo que explica un rechazo
y nunca un registro de la base de datos. Cuando un rechazo trata sobre algo que
envió el llamante, `details.fields` es una lista de `{field, message}` — que es lo
que permite a un formulario marcar el campo en lugar de mostrar una frase que
alguien tiene que buscar releyendo la página.

Un `401` lleva `WWW-Authenticate: Bearer`. Una lectura entre inquilinos responde
`404`, no `403`, por el motivo de arriba.

**Un run que empezó y luego falló se nombra a sí mismo.** `POST /agents/{id}/run`
responde `502` con `MODEL_CALL_FAILED` cuando el proveedor del modelo rechazó la
solicitud o no la completó - también cada modelo de una cadena de fallback - y
`500` con `RUN_FAILED` ante cualquier otro fallo una vez empezado el run. Ambas
llevan `details.run_id` y `details.status`, y `details.conversation_id` cuando el
run escribió en una conversación, para que un reintento continúe ese hilo en vez
de abrir otro; y
`message` dice el porqué con las palabras de la plataforma, no con la respuesta
cruda del proveedor. El run queda registrado como fallido con lo que gastó, así
que `GET /api/v1/runs/{run_id}` lo lee; enviar la solicitud de nuevo inicia un
run nuevo.

## Reintentos, idempotencia y revisiones { #retries-idempotency-and-revisions }

v1 no tiene precondiciones de revisión: ni `ETag` ni `If-Match`. Una escritura
se aplica cuando llega, y gana la última. `Idempotency-Key` se respeta en una
ruta, el run asíncrono.

- **`GET`, `PUT` y `DELETE` se pueden repetir sin riesgo.** Leer dos veces lee
  dos veces; borrar lo que ya no está responde `404`, que un reintento puede dar
  por hecho.
- **`PATCH` se puede repetir con el mismo cuerpo**, y solo entonces: dos clientes
  que cambian un campo se sobrescriben en lugar de entrar en conflicto.
- **`POST` no.** Un `POST /agents/{id}/run` repetido inicia un segundo run y se
  factura como tal; una creación repetida hace una segunda fila. Tras un timeout
  o una conexión cortada, mira antes de reintentar:
  `GET /api/v1/runs?agent_id=…&surface=api` lista los runs del más reciente al
  más antiguo, y una lectura de la lista encuentra la fila que el primer intento
  sí creó.
- **Un run asíncrono sí lo es, con un `Idempotency-Key`.** Envía
  `Prefer: respond-async` y una clave que elijas, de 255 caracteres como mucho,
  y un reintento con la misma clave y el mismo cuerpo responde la misma petición
  de run, esté en el estado que esté. La misma clave con otro cuerpo es un `409`,
  nunca un segundo run. Las claves son por organización. Una llamada síncrona con
  esa cabecera se rechaza con un `400` en vez de dejar creer que reintentar es
  seguro.
- **`429` es el único rechazo que se reintenta**, tras el `Retry-After` que
  lleva. Cualquier otro `4xx` es definitivo para esa petición.

## Convenciones { #conventions }

| | |
|---|---|
| Prefijo | `/api/v1` |
| Crear | `POST`, `201` |
| Actualización parcial | `PATCH` |
| Borrar | `DELETE`, `204`, sin cuerpo |
| Paginación | parámetros de consulta `skip` (≥ 0) y `limit` (1–100); las respuestas de lista llevan `items` y `total` |
| Rutas | kebab-case |

## Estabilidad, con franqueza { #stability-honestly }

**La API pública tiene una promesa de compatibilidad escrita; el resto de
`/api/v1` no.** Las rutas que puede llamar una clave de API están en su propio
documento OpenAPI en **`/api/v1/public/openapi.json`**, servido en todos los
entornos. Dentro de v1, un cambio en una de ellas es aditivo — una ruta nueva, un
campo opcional nuevo, un campo de respuesta o un valor de enum nuevos —, y un
cliente debe ignorar los campos de respuesta que no conozca. Quitar o renombrar algo
solo ocurre después de marcarlo como `deprecated` en ese documento durante al menos
90 días y listarlo en las [notas de versión](release-notes.md); un cambio que no se
pueda hacer así va a `/api/v2`, junto a v1.

La consola muestra el mismo documento como una página: **Settings → API → API reference** lista cada endpoint con sus parámetros, cuerpo, respuestas y una llamada `curl` lista para copiar.

El primer cambio de nombre bajo esa regla son las aplicaciones (#2071): lo que eran
artefactos se sirve en `/api/v1/apps` y `/api/v1/public/apps`, y las rutas antiguas
`/api/v1/artifacts` y `/api/v1/public/artifacts` responden igual, marcadas como
`deprecated`, hasta que pasen los 90 días. Los nombres de los permisos
(`artifacts:view`, `artifacts:edit`), los de las herramientas y las direcciones
desde las que se sirve una página publicada conservan su nombre.

Las rutas propias de la consola no tienen esa promesa y cambian con la consola; una
clave no puede llamarlas. Todavía no hay biblioteca cliente.

Lo que la API pública todavía no hace, para que nadie construya un cliente
encima:

- **Virtual Tables** no están en ella; leer y escribir una tabla con una clave es
  [#1795](https://github.com/vstorm-co/agenticos/issues/1795).
- **Sin streaming para una clave.** El socket del chat solo acepta la sesión de
  una persona.
- **Sin claves de idempotencia ni revisiones**, como arriba.

El [spec del agent](reference/spec.md) tiene su propia promesa: está versionado y
solo avanza.

## Recapitulación { #recap }

- **`/docs`** en el despliegue es la referencia generada; está desactivada en
  producción por diseño.
- Tres formas de entrar: **una clave de API de la organización, un JWT o la
  cookie de la consola**.
- Una clave lleva la autoridad de su emisor **limitada a sus permisos y al rol
  actual del emisor**, se muestra una vez y solo funciona en la API pública.
- **Una clave actúa en su propia organización; una sesión lee
  `X-Organization-Id`** y sin ella vuelve a la organización por defecto, la
  personal o la única. La equivocada parece un recurso inexistente.
- Ejecutar un agent por HTTP usa el **mismo runner** — budget, aprobación y
  auditoría se aplican igual.
- Un script consigue su propia clave **sin navegador** — iniciar sesión, emitir,
  revocar — y `examples/public-api.sh` hace todo ese recorrido.
- **Solo vale la pena reintentar un `429`**; un `POST` no es idempotente, así que
  mira antes de repetirlo, salvo un run asíncrono enviado con `Idempotency-Key`.
- **`Prefer: respond-async`** convierte un run en un `202` y una petición de run
  que consultar, así que un run largo no mantiene una conexión abierta.
- **La API pública está en `/api/v1/public/openapi.json`** y dentro de v1 solo
  cambia de forma aditiva, con 90 días de deprecación; todavía no hay SDK.
