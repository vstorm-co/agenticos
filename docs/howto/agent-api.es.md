---
source_sha: "dbf40f028eaa"
title: "Llama a un agent desde tu propia aplicación"
description: "Autentícate, envía la cabecera de organización y ejecuta un agent publicado por HTTP; después lee el mismo sobre de error, budget y límite de frecuencia que recibe cualquier otra superficie."
---

# Llama a un agent desde tu propia aplicación { #call-an-agent-from-your-own-application }

Llama a un agent publicado igual que lo hacen la consola, Slack y cualquier otra superficie: con un `POST` autenticado que pasa por el mismo runner, la misma comprobación de budget y la misma compuerta de aprobación. Esta página recorre la [API HTTP](../api.md) con un agent pequeño y muestra respuestas reales y recortadas. Es un procedimiento para ejecutar, con un run registrado como referencia.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo y una cuenta de miembro con la que iniciar sesión.
- Un agent publicado sin ninguna capability que necesite una cuenta que no tengas. El run registrado de abajo usa uno sin capabilities, así que nada depende de una sandbox, una colección o una conexión MCP.

## Construye el agent { #build-the-agent }

Crea un agent en **Agents → New agent**, selecciona tu perfil de modelo, deja vacío el Toolbox, fija un budget y un límite de pasos pequeños y escribe unas instrucciones cortas:

```text
You are a small support assistant reachable over the HTTP API.
Answer briefly, in two or three sentences.
If asked something you cannot know, say so plainly rather than guessing.
```

Pulsa **Publish** y copia su id de la URL o de `GET /agents`.

## Autentícate y ejecútalo { #authenticate-and-run-it }

Inicia sesión para obtener un token de acceso y llama al endpoint de run con él y con la cabecera de organización:

```bash
TOKEN=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -d "username=$EMAIL&password=$PASSWORD" | jq -r .access_token)

curl -s -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "In one sentence, what is a model profile?"}'
```

```python
import httpx

login = httpx.post(f"{BASE}/api/v1/auth/login",
                    data={"username": EMAIL, "password": PASSWORD})
token = login.json()["access_token"]

resp = httpx.post(
    f"{BASE}/api/v1/agents/{AGENT_ID}/run",
    headers={"Authorization": f"Bearer {token}", "X-Organization-Id": ORG_ID},
    json={"prompt": "In one sentence, what is a model profile?"},
)
resp.raise_for_status()
print(resp.json()["output"])
```

`X-Organization-Id` decide en qué organización se ejecuta la llamada; consulta [la cabecera de organización](../api.md#the-organization-header). Una cabecera `X-API-Key` funciona igual para un servicio sin una persona detrás. Las dos llamadas de arriba usan el JWT de un miembro.

## O transmítelo en streaming { #stream-it-instead }

`ws://…/api/v1/ws/agent` es el mismo socket autenticado que usa el chat de la consola, con el token en el subprotocolo (`access_token.<JWT>` y `chat`) en lugar de en una cabecera, porque un `WebSocket` de navegador no puede fijarla. Un frame lleva `message`, `agent_id` y un `conversation_id` opcional. El socket responde con eventos `text_delta` mientras el modelo escribe, `tool_call` y `tool_result` en cada paso, `tool_approval_required` si algo queda aparcado y `complete` con el uso del run al final. Consulta [streaming](../api.md#streaming).

## Gestiona errores, budgets y límites de frecuencia { #handle-errors-budgets-and-rate-limits }

Cada rechazo vuelve en el mismo sobre, `error.code`, `error.message` y `error.details`:

```json
{"error": {"code": "VALIDATION_ERROR", "message": "prompt: Field required",
  "details": {"fields": [{"field": "prompt", "message": "Field required"}]}}}
```

Un run que este endpoint acepta sigue pasando por la gobernanza: el [budget](../governance.md#budgets) se comprueba antes de la petición al modelo y el run falla en lugar de gastar de más, y una herramienta protegida [queda aparcada para aprobación](../governance.md#approvals) exactamente igual que en el chat. Quien llama por API no puede saltarse ninguno de los dos. La ruta lleva un límite de frecuencia en lugar de una compuerta de permisos, contado por llamante: 30 runs por minuto por defecto (`RATE_LIMIT_RUN_PER_MINUTE`), rechazados con un mensaje para esperar en lugar de ponerse en cola.

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| Un run normal | `status: "completed"`, una cadena en `output`, `cost_usd` y recuentos de tokens |
| Sin cabecera `Authorization` | `401`, `www-authenticate: Bearer` |
| Un `X-Organization-Id` incorrecto | `404`, `NOT_FOUND`, con la misma forma que un agent que no existe |
| Un `agent_id` desconocido | `404`, con `agent_id` en `details` |
| Un cuerpo sin `prompt` | `422` (`VALIDATION_ERROR`), `details.fields` nombra el campo |
| Dos organizaciones, un llamante | El run solo ve la organización indicada en la cabecera de esa llamada |

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter, agent `uc-api-demo`. `POST /run` con un prompt real respondió `{"status": "completed", "cost_usd": "0.000582", "output": "A model profile is a structured description of an AI model's key characteristics, capabilities, limitations, and intended use cases."}`.

    Omitir `X-Organization-Id` **no** rechazó la llamada: la API recurrió a la organización personal del miembro con sesión iniciada y ejecutó el run allí, en lugar de responder "no tenant to act in". Un id de organización inventado volvió como `404` con `"Organization not found or access denied"`. Omitir `Authorization` volvió como `401` con `www-authenticate: Bearer`. Un cuerpo vacío volvió como `422` con `details.fields: [{"field": "prompt", "message": "Field required"}]`, exactamente como el sobre de arriba.

## Cuando algo sale mal { #when-it-goes-wrong }

- **`404` con un id de agent que sabes que existe.** Comprueba primero la cabecera de organización. Una lectura entre organizaciones responde `404` a propósito, igual que un agent que falta.
- **`429` en mitad de una prueba de integración.** El límite de frecuencia de la ruta de run es por llamante, no por agent. Espera en lugar de reintentar de inmediato.
- **Un run responde pero nunca llega a una herramienta que activaste.** Busca en Activity una aprobación aparcada. La ruta HTTP aparca exactamente igual que el chat, y `POST /run` no se reanuda solo.
- **El coste que ves no coincide con el panel de tu proveedor.** `cost_is_partial` en la respuesta indica si el número es un mínimo y no la cifra final; `true` significa que parte del run no pudo tener precio.

## Registra la prueba { #record-the-trial }

Guarda la petición y la respuesta de cada comprobación, la versión del agent y el perfil de modelo. Una persona sigue decidiendo qué capability puede tener un agent de servidor a servidor, si necesita su propia clave de API en lugar de una compartida y qué budget lo limita. El endpoint aplica esas decisiones, no las toma.

## Siguientes pasos { #next-steps }

Para un token que nadie tenga que renovar, usa una clave de API en lugar de iniciar sesión por JWT; [la autenticación](../api.md#authenticating) cubre ambas. Para ver cómo quedan las llamadas a herramientas y el coste de un run en el producto, consulta [la gobernanza](../governance.md#budgets).
