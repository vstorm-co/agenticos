---
source_sha: "607db26c1ad1"
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

Una clave la emite un miembro, en una organización, desde **Settings → API keys**
(o con `POST /api/v1/api-keys` desde una sesión iniciada). Lleva la autoridad de
ese miembro, limitada dos veces:

- **A los permisos con los que se emitió.** Elige una plantilla — *Read-only*,
  *Knowledge ingest*, *Full access* — o marca permisos del
  [catálogo](permissions.md). Solo puedes conceder lo que tienes.
- **A lo que el emisor puede hacer ahora.** Cada petición vuelve a leer la
  membresía del emisor, así que degradarlo limita al instante cada una de sus
  claves, y sacarlo de la organización detiene todas las claves que emitió. Un
  permiso concedido sobre un recurso amplía lo que una *persona* puede hacer con
  una fila; nunca amplía una clave más allá de sus permisos.

La clave se muestra **una vez**, en la respuesta que la crea. Solo se guarda su
SHA-256, y nunca aparece en una línea de log, una entrada de auditoría ni el
cuerpo de un error. Las listas muestran su prefijo (`aos_1a2b3c4d`), que es
también como una entrada de auditoría nombra la clave que actuó: cada entrada
registrada durante una petición autenticada con clave lleva `via_api_key` en sus
detalles. Una clave puede caducar, y revocarla (`DELETE /api/v1/api-keys/{id}`)
surte efecto en su siguiente petición.

```bash
curl "$BASE/api/v1/me/permissions" \
  -H "Authorization: Bearer $AGENTICOS_KEY"
```

Conviene conocer dos rechazos:

- **`403` "API keys are not accepted on this endpoint"**: las claves solo se
  aceptan en la API pública: agents, runs y aprobaciones, bases de conocimiento y
  RAG, skills, archivos de contexto, artefactos, los servicios de ML,
  `/me/permissions` y los miembros, invitaciones, grupos y ajustes de una
  organización. Las rutas propias de la consola, tu cuenta, abandonar o traspasar
  una organización y la gestión de claves en sí siguen siendo solo de sesión, para
  que una clave filtrada no pueda acuñar su sucesora.
- **`401` "Invalid, expired or revoked API key"**: la misma frase en cada caso,
  para que una clave equivocada no aprenda nada sobre qué claves existen.

Cada clave tiene además su propio límite, `RATE_LIMIT_API_KEY_PER_MINUTE`
peticiones por minuto (600 por defecto), y un run o una llamada de ML que haga
cuenta contra esos límites para la clave y no para su emisor.

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
petición vuelve a la **organización personal** del llamante: un script que la
olvide actúa allí, con los agents, permisos y budget de esa organización, y no
recibe ningún error. Envía la equivocada y obtendrás un rechazo idéntico al de un
recurso inexistente, a propósito, para que los ids no se puedan sondear.

## Ejecutar un agent { #running-an-agent }

```bash
curl -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $AGENTICOS_KEY" \
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
  -H "Authorization: Bearer $AGENTICOS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "write to ada@example.com"}'
```

## Ejemplos paso a paso { #worked-examples }

Cada uno funciona con una clave de la organización en `$AGENTICOS_KEY` y el origen
de la API en `$BASE`. Crea la clave en **Settings → API keys** con los permisos que
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
  general. Autentícate con el subprotocolo `access_token.<token>`, donde el token
  es un JWT de sesión o una clave de API de la organización; el socket de una
  clave actúa en la organización de la clave, ejecuta cada turno dentro de los
  permisos de la clave y se cierra en el siguiente frame tras revocarla.
- **`/api/v1/embed/{public_key}/ws`** — el público, detrás de un
  [embed](channels.md), para un visitante que no tiene cuenta.

Los dos emiten tokens según llegan (un agent con guardrail de salida transmite paso
a paso, consulta [Guardrails](reference/capabilities.md#guardrails)) y los dos
producen un run corriente, con la misma contabilidad que todo lo demás.

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

**La API pública tiene una promesa de compatibilidad escrita; el resto de
`/api/v1` no.** Las rutas que puede llamar una clave de API están en su propio
documento OpenAPI en **`/api/v1/public/openapi.json`**, servido en todos los
entornos. Dentro de v1, un cambio en una de ellas es aditivo — una ruta nueva, un
campo opcional nuevo, un campo de respuesta o un valor de enum nuevos —, y un
cliente debe ignorar los campos de respuesta que no conozca. Quitar o renombrar algo
solo ocurre después de marcarlo como `deprecated` en ese documento durante al menos
90 días y listarlo en las [notas de versión](release-notes.md); un cambio que no se
pueda hacer así va a `/api/v2`, junto a v1.

Las rutas propias de la consola no tienen esa promesa y cambian con la consola; una
clave no puede llamarlas. Todavía no hay biblioteca cliente.

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
  `X-Organization-Id`** y sin ella vuelve a la organización personal. La
  equivocada parece un recurso inexistente.
- Ejecutar un agent por HTTP usa el **mismo runner** — budget, aprobación y
  auditoría se aplican igual.
- **La API pública está en `/api/v1/public/openapi.json`** y dentro de v1 solo
  cambia de forma aditiva, con 90 días de deprecación; todavía no hay SDK.
