---
source_sha: "10772d5fcdb4"
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
`environment_id` elige [qué entorno](environments.md) responde. Un agent con un
[formato de respuesta](concepts.md#spec) responde con un objeto: está en
`structured`, ya validado contra el `output_schema` del agent, y `output` muestra
el mismo objeto como un bloque JSON.

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

## Ejecutar un workflow { #running-a-workflow }

```bash
curl -X POST "$BASE/api/v1/workflow-runs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"workflow_id": "'"$WORKFLOW_ID"'", "input": {"question": "How long do refunds take?"}, "deadline_seconds": 3600}'
```

Esto inicia un run de la versión publicada del workflow y responde `201` de
inmediato; los nodos se ejecutan en segundo plano. `"mode": "test"` ejecuta en
su lugar el borrador actual, desde cualquier trigger, y exige `workflows:edit`.
`deadline_seconds` (hasta
treinta días) fija un plazo que se comprueba cada vez que un nodo va a
despacharse: el primer nodo pendiente tras cumplirse hace fallar el run con
`DEADLINE_EXCEEDED`, mientras que un nodo ya en ejecución, o un run que espera
una aprobación, no se interrumpe por ello. La ruta tiene un límite por llamante como
la de runs de agents, y responde `429` con `Retry-After` al superarlo.

`input` es lo que el trigger [`core.input`](reference/workflow-nodes.md#core-input)
del grafo pasa adelante, como mucho `WORKFLOW_RUN_MAX_INPUT_BYTES` en JSON (`413`
si lo supera). Aquí solo se inicia una versión que empieza por ese trigger o sin
ninguno: cualquier otra responde `409 WORKFLOW_TRIGGER_MISMATCH`, porque la inicia un
webhook, una programación, un mensaje del chat o un registro de tabla.

`GET /api/v1/workflow-runs/{id}` devuelve el estado del run, `spent_cost`,
`error` y, cuando su nodo [`core.output`](reference/workflow-nodes.md#core-output) ya se ha ejecutado, su `output`, y `POST /api/v1/workflow-runs/{id}/cancel` lo detiene. `GET
/api/v1/workflow-runs/{id}/events?after=<cursor>` devuelve el flujo de eventos
del run del más antiguo al más reciente, con un `next_cursor` que se devuelve
como `after`: se mantiene igual mientras no exista nada más nuevo, así que
consultar con él sigue un run en curso. Quién puede hacer cada cosa está en
[Permisos](permissions.md#workflow-runs).

`GET /api/v1/workflow-runs/{id}/nodes` enumera cada paso que dio el run,
iteraciones de bucle incluidas, cada uno con su `scope_path`, estado, intentos,
coste y el error tipado con el que falló por última vez, y `GET
/api/v1/workflow-runs/{id}/graph` devuelve el grafo que ejecuta el run: el de su
versión o la instantánea del draft de un run de prueba.

### Seguir un run por un WebSocket { #following-a-run-over-a-websocket }

`/api/v1/ws/workflow-runs?organization_id=<org>` se autentica como el socket del
chat, con el token de acceso como subprotocolo `access_token.<token>`. Envía
`{"type": "start", "workflow_id": ..., "input": {...}}` para iniciar un run, o
`{"type": "attach", "run_id": ..., "after": <cursor>}` para seguir uno. El servidor
envía `{"type": "run", "run": {...}}` cuando empieza a seguirlo y otra vez cuando el
run termina, y `{"type": "event", "event": {...}, "cursor": ...}` por cada evento
intermedio. Un frame rechazado recibe `{"type": "error", "code": ..., "message":
...}`, y una sesión revocada cierra el socket con `4001`. Un socket sigue un run; un
frame nuevo sustituye el run que seguía. Un frame `start` gasta la misma cuota por
minuto que `POST /workflow-runs`, y pasada esta recibe `RATE_LIMIT_EXCEEDED`.

### Webhooks y programaciones { #workflow-webhooks-and-schedules }

Un workflow cuyo nodo trigger es un webhook o una programación recibe su exposure al
publicarse esa versión, y la respuesta de la publicación la lleva como `exposure`. El
secreto de firma de un webhook está en el `webhook_secret` de la publicación que lo
enciende por primera vez, y en ningún otro sitio. `GET /api/v1/workflows/{id}/exposure`
la vuelve a leer, o devuelve `null` para un workflow que empieza de otra forma. `PATCH
.../exposures/{exposure_id}` con `{"is_active": false}` la pausa, y `POST
.../exposures/{exposure_id}/rotate-secret` sustituye el secreto de un webhook y
devuelve el nuevo una vez. Ambos requieren `workflows:edit` y `workflows:run` sobre el
workflow. La `webhook_url` de un webhook es la dirección a la que entrega el remitente:

```bash
BODY='{"lead": 42}'
SIGNATURE="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | cut -d' ' -f2)"
curl -X POST "$WEBHOOK_URL" \
  -H "X-Signature-256: $SIGNATURE" \
  -H "X-Delivery-Id: lead-42" \
  -H "Content-Type: application/json" \
  -d "$BODY"
```

Responde `202` con `{"run_id": ..., "duplicate": false}` en cuanto el run queda
admitido, sin esperar nunca al run en sí. Un id de entrega ya admitido responde
`"duplicate": true` con el id del primer run. Una firma que no se verifica es un
`403`, una entrega sin id o con un cuerpo que no es un objeto JSON un `400`, y un
webhook pausado o desconocido un `404`.

## Trabajar con tablas { #working-with-tables }

Los `values` de un registro van por id de columna; `GET /api/v1/tables/{id}` lista las
columnas. Toda escritura acepta un `Idempotency-Key`: un reintento con la misma clave y
el mismo cuerpo responde con el resultado de la primera escritura e
`Idempotent-Replayed: true` en lugar de escribir otra vez, y la misma clave con otro
cuerpo es `422`.

```bash
curl -X POST "$BASE/api/v1/tables/$TABLE_ID/records" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Idempotency-Key: lead-ada-2026-09-29" \
  -H "Content-Type: application/json" \
  -d '{"external_id": "ada@example.com", "values": {"'"$EMAIL_COLUMN"'": "ada@example.com"}}'
```

`PATCH .../records/{record_id}` cambia algunas celdas y necesita la `expected_revision`
que leíste por última vez; una desfasada es `409 REVISION_CONFLICT`. `PUT
.../records/by-external-id/{external_id}` crea el registro o lo actualiza, con
`expected_revision` obligatoria cuando ya existe. `POST .../records/query` filtra y
ordena página a página.

Un workflow cuyo nodo trigger es **New table record** se ejecuta, una vez publicado,
por cada registro que se añade a su tabla. `GET .../triggers` enumera los workflows
que empiezan por una tabla, `PATCH .../triggers/{trigger_id}` con `{"is_active": false}`
pausa uno, y `GET .../triggers/{trigger_id}/admissions` lista lo que decidió sobre
cada registro. Consulta [Triggers](virtual-tables.md#triggers).

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

Los dos emiten tokens según llegan y los dos producen un run corriente, con la
misma contabilidad que todo lo demás.

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
