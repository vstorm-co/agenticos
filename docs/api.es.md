---
source_sha: "ba34a88c524a"
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
| **JWT** | `Authorization: Bearer <access token>` | Una persona, o algo que actúa como tal. De vida corta, se renueva con un refresh token |
| **API key** | `X-API-Key: <key>` | De servicio a servicio. Sin ningún usuario detrás |
| **Cookie de sesión** | la pone la consola | Solo el navegador — el token es HttpOnly y nunca llega a JavaScript |

Las claves se comparan con `secrets.compare_digest`, nunca con `==`, y una clave
se guarda igual que [cualquier otra credencial](secrets.md).

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

**`X-Organization-Id` viaja en todas las peticiones**, y no es un adorno
opcional: decide en qué inquilino actúa la llamada.

Un llamante que pertenece a tres organizaciones es un principal distinto en cada
una, con un rol distinto y grants distintos. Si omites la cabecera, la petición no
tiene inquilino en el que actuar; si envías la equivocada, obtienes un rechazo
idéntico a que el recurso no exista — deliberadamente, para que los ids no se
puedan sondear.

## Ejecutar un agent { #running-an-agent }

```bash
curl -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "How do I rotate a provider key?"}'
```

La respuesta trae el id del run, la salida y el estado. Conviene conocer dos
campos opcionales del cuerpo: `conversation_id` continúa un hilo existente, y
`environment_id` elige [qué entorno](environments.md) responde.

!!! info "Un llamante de la API no puede esquivar el governance"

    Este endpoint pasa por el mismo runner que la consola, Slack y el widget. El
    run queda registrado, el budget se comprueba antes de la petición al modelo,
    la puerta de aprobación se aplica, y el coste acaba en el mismo dashboard.

    Ese es el sentido de tener un único runner, y por eso no existe una "vía
    rápida" que se lo salte.

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
## Los servicios de ML { #the-ml-services }

Cuatro servicios de la plataforma responden por su cuenta, sin conversación y sin
un agent detrás: análisis de documentos, OCR, transcripción de voz y detección de
datos personales. Los controla `ml:invoke`, no `agents:run`, y
[Los servicios de ML](ml-services.md) es su referencia.

```bash
curl -X POST "$BASE/api/v1/ml/privacy/pii" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"text": "write to ada@example.com"}'
```

## Streaming { #streaming }

Dos endpoints WebSocket, para dos públicos.

- **`/api/v1/ws/agent`** — el autenticado, el que usa la consola. Un frame que
  lleva `agent_id` ejecuta ese agent publicado; un frame sin él llega al
  asistente general.
- **`/api/v1/embed/{public_key}/ws`** — el público, detrás de un
  [embed](channels.md), para un visitante que no tiene cuenta.

Los dos emiten tokens según llegan (un agent con guardrail de salida transmite paso
a paso, consulta [Guardrails](reference/capabilities.md#guardrails)) y los dos
producen un run corriente, con la misma contabilidad que todo lo demás.

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
miembro. El socket del embed se cierra con `4029` al pasar un rate limit y con
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
| `ready` | `call_id`, `run_id`, `conversation_id`, `transport`, `input_sample_rate`, `output_sample_rate`, `cap_seconds`, `minutes_left`, `resume_token` | La llamada está establecida. `resume_token` se envía solo aquí, solo a quien llama; una reconexión lo devuelve |
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
`ready` no incluye `run_id`, `minutes_left` llega como `null`, y `cap_seconds`
es el límite propio de la llamada - la llamada más larga de la organización, la
del agent o lo que queda de una llamada que se reanuda - en lugar de uno que
revele los minutos de la organización. El servidor sigue terminando la llamada
en el límite real. Los frames de herramientas siguen los interruptores
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
`voice_off`, `no_agent`, `forbidden`, `not_configured`, `bad_offer`,
`data_channel`, `resume_refused`, `minutes_exhausted`, `call_limit`,
`not_priced`, `budget`, `busy` o `line_busy`, con un `message` que se puede
mostrar. Un inicio que falla por cualquier otro motivo responde con `ended` y
`error`. Un visitante rechazado como `not_configured`, `not_priced`,
`minutes_exhausted` o `budget` recibe el mismo motivo con el mensaje "Calls are
not available right now.", porque el mensaje completo está escrito para el
operador del agent. Una llamada a una conversación archivada se rechaza como
`forbidden`, igual que un mensaje escrito en ella.

Una llamada que se llegó a mantener termina con `user`, `time_limit`, `budget`,
`minutes`, `disconnected`, `revoked`, `shutdown` o `error`. Termina con
`minutes` cuando los minutos del mes fijaron su límite, y con `time_limit`
cuando lo fijó el ajuste de la llamada más larga. La llamada de un visitante termina con
`revoked` cuando su embed se pausa, se le desactivan las llamadas o se apunta a
otro agent. Ningún frame lleva nunca una credencial del provider.

La acompañan cuatro rutas HTTP:

| Ruta | Control | Responde |
|---|---|---|
| `GET /api/v1/agents/{agent_id}/voice?surface=web` | `agents:run` sobre ese agent, grant incluido; `404` en caso contrario | Si una llamada empezaría, por qué no, el transporte, la llamada más larga y los minutos restantes. `surface=embed` pregunta por un widget o una página alojada |
| `GET /api/v1/providers/realtime-models` | `agents:view` | El catálogo en tiempo real del que elige la sección Voice |
| `GET /api/v1/voice/usage?start=…&end=…` | `runs:view` | Segundos de llamada y llamadas de las llamadas iniciadas en `start` o después y antes de `end`, por agent (las llamadas de un agent eliminado como una sola fila sin id ni nombre), y los segundos de este mes frente a los minutos mensuales de la organización. Un `end` que no sea posterior a `start` se rechaza con `422` |
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

**Todavía no hay una promesa de compatibilidad publicada, ni una librería
cliente.** La API es pública desde el primer commit y el contrato de versionado
es trabajo de la
[hoja de ruta](https://github.com/vstorm-co/agenticos/blob/main/docs/ROADMAP.md)
(R10).

En la práctica las formas han sido estables y el prefijo `/api/v1` significa que
un cambio incompatible aterrizaría al lado del actual y no encima de él — pero
hasta que eso esté por escrito, trátala como lo que es: una API contra la que
deberías fijar las pruebas de tu integración.

El único formato que *sí* lleva una promesa es el
[spec del agent](reference/spec.md), que está versionado y solo avanza.

## Recapitulación { #recap }

- **`/docs`** en el despliegue es la referencia generada; está desactivada en
  producción por diseño.
- Tres formas de entrar: **JWT, `X-API-Key` o la cookie de la consola**.
- **`X-Organization-Id` decide el inquilino** en todas las peticiones, y la
  equivocada parece un recurso inexistente.
- Ejecutar un agent por HTTP usa el **mismo runner** — budget, aprobación y
  auditoría se aplican igual.
- **Todavía no hay promesa de compatibilidad ni SDK** (R10); el spec del agent es
  el único formato versionado.
