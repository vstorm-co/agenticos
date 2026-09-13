---
source_sha: 1fd2c8097097
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
