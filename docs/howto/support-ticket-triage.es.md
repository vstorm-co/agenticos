---
source_sha: "9121fc5ca757"
title: "Clasifica las solicitudes de soporte entrantes desde tu propia app"
description: "Dispara un agent desde tu propio backend con un webhook firmado y haz que clasifique, redacte una respuesta y señale los informes de seguridad."
---

# Clasifica las solicitudes de soporte entrantes desde tu propia app { #triage-incoming-support-requests-from-your-own-app }

Conecta tu propio formulario de soporte o sistema de tickets a un agent con un [trigger de eventos](../triggers.md) de la fuente **API**, la fuente genérica `webhook` que se dispara con cualquier entrega JSON firmada. Tres tickets sintéticos, uno de ellos un informe de seguridad, comprueban que la clasificación, el borrador y la señal de seguridad funcionan antes de apuntar ahí un sistema real. Es un procedimiento para ejecutar, con un run registrado como referencia.

## Qué necesitas { #what-you-need }

Una [instalación en marcha](../install.md) con un perfil de modelo. Sin sandbox, sin modelo de embeddings y sin cuenta externa: la fuente API firma sus propias entregas, así que no hay consola de proveedor que configurar.

## Prepara la entrada { #prepare-the-input }

Tres tickets, tal como los enviaría tu propio backend. El cuerpo JSON completo llega al prompt del agent, así que sirve cualquier forma siempre que escribas las instrucciones en torno a ella:

```json
{"ticket_id":"T-1001","from":"lena@acme-example.com","subject":"Charged twice this month","body":"I was billed 49 USD twice on the 3rd for the same Pro plan invoice. Can you refund the duplicate?"}
{"ticket_id":"T-1002","from":"marek@example.org","subject":"Export button does nothing","body":"Clicking Export CSV on the reports page just spins forever and nothing downloads. Chrome, latest version."}
{"ticket_id":"T-1003","from":"researcher@example.net","subject":"Found an issue with account access","body":"By changing the id in the /api/v1/invoices/{id} URL I was able to view another customer's invoice PDF without being logged in as them. Tested with three different ids, all worked."}
```

Referencia: T-1001 es de facturación, prioridad media. T-1002 es técnico, prioridad media. T-1003 describe un IDOR: debería volver como seguridad, urgente, con una señal explícita.

## Construye el agent { #build-the-agent }

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo. Esta prueba no necesita ninguna capability.
2. Escribe las instrucciones de abajo y luego pulsa **Publish**.

```text
You triage inbound support tickets for a small SaaS product.
Be concise and factual. Never invent facts not in the ticket.
```

3. Abre **Routines → New event trigger**, elige el agent y la fuente **API**. Escribe el prompt propio del trigger, que se envía antes de la entrega cada vez que se dispara:

```text
A support ticket just arrived as JSON below. Classify it by category (billing,
technical, account, security, other) and priority (low, medium, high, urgent).
Draft a reply the support team can send. If the ticket describes a possible
security vulnerability or exposure of somebody else's data, say so explicitly in
a line starting with 'SECURITY:' and set priority to urgent.
```

4. Guarda. Copia la **webhook URL** y el **signing secret** que se muestran una sola vez: la fuente API tiene entrega `manual`, así que nada se registra solo y el secreto lo eliges tú. [Los triggers](../triggers.md#the-mechanism-once) explican qué significa cada uno.

## Ejecútalo { #run-it }

Firma los bytes exactos de cada ticket con el secreto del trigger y envíalos por POST. Consulta [firmar tú mismo una entrega](../triggers.md#signing-a-delivery-yourself) para las dos trampas: no vuelvas a serializar el cuerpo y firma solo los bytes que envías.

```bash
SECRET='your-signing-secret'
URL='http://localhost:8110/api/v1/webhooks/triggers/webhook/<trigger_id>'
BODY='{"ticket_id":"T-1001","from":"lena@acme-example.com","subject":"Charged twice this month","body":"I was billed 49 USD twice on the 3rd for the same Pro plan invoice. Can you refund the duplicate?"}'

SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')"

curl -sS -X POST "$URL" \
  -H 'Content-Type: application/json' \
  -H "X-Signature-256: $SIG" \
  --data-raw "$BODY"
```

Repite con T-1002 y T-1003. Cada entrega aceptada responde `202`: aceptada, no terminada. Lee los runs disparados en **Activity** o en la conversación propia del trigger en **Routines**.

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| T-1001 | Categoría facturación, prioridad media, una respuesta que reconoce el cargo duplicado |
| T-1002 | Categoría técnica, prioridad media, una respuesta que pide detalles para reproducirlo |
| T-1003 | Categoría seguridad, prioridad urgente, una línea que empieza por `SECURITY:` y nombra la exposición |
| La respuesta `202` | Llega al instante; el run en sí termina unos segundos después, de forma asíncrona |
| Una entrega sin firmar del mismo cuerpo | `403`, rechazada antes de que el agent llegue a ejecutarse |
| Una entrega cuyo cuerpo reserializó tu cliente HTTP en lugar de enviarlo tal cual | `403`: la firma ya no coincide con los bytes realmente enviados |

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter. Las tres entregas respondieron `202` y terminaron en unos 6 segundos cada una, registradas con la superficie `schedule`: los disparos de triggers de eventos comparten esa superficie con los programados.

    T-1001: *"Category: Billing, Priority: Medium"*, una respuesta que pide el ID de la factura para tramitar un reembolso. T-1002: *"Category: Technical, Priority: Medium"*, una respuesta que pide la salida de la consola del navegador. T-1003: *"Category: Security, Priority: Urgent"*, seguido de `SECURITY: Reporter claims unauthenticated/unauthorized access to other customers' invoice PDFs via IDOR (Insecure Direct Object Reference) on /api/v1/invoices/{id}. Multiple accounts confirmed affected.` y un borrador de respuesta que pide a quien lo notificó que no siga probando mientras se investiga. Coste conjunto de los tres runs: 0,013 USD.

    También se comprobaron las dos vías de rechazo: el mismo cuerpo enviado sin la cabecera `X-Signature-256` respondió `403`, y un cuerpo firmado como cadena pero enviado después con la recodificación `json=` propia de un cliente (mismo contenido, bytes distintos) también respondió `403 AUTHORIZATION_ERROR: Webhook signature did not verify`, lo que confirma que la firma cubre los bytes exactos que viajan por la conexión y no el contenido lógico del JSON.

## Cuando algo sale mal { #when-it-goes-wrong }

- **Cada entrega vuelve con `403`.** La firma cubre los bytes *exactos* enviados. `echo` añade un salto de línea final que puede coincidir o no con lo firmado; usa `printf '%s'` y `curl --data-raw`, y nunca dejes que un cliente vuelva a codificar un diccionario después de firmar la cadena.
- **`202` pero no aparece ningún run.** Significa aceptado, no terminado: un flow de Prefect lo ejecuta en el worker. Dale unos segundos y revisa Activity filtrando por el agent.
- **La señal de seguridad no se activó.** La señal sale de las instrucciones, no de un clasificador integrado; vuelve a leer el prompt del trigger y precisa qué cuenta como informe de seguridad si se escapa un caso sintético como T-1003.
- **Solo quieres probar el prompt, no la vía de entrega.** Usa primero **Run now** en el trigger: dispara el prompt base del agent sin contexto de entrega, sin firma y sin webhook. No pondrá a prueba la clasificación, porque no hay JSON de ticket que clasificar, pero confirma que el agent, su budget y su estado de publicación funcionan.
- **Zapier o Make en lugar de un script.** Ninguno tiene una acción HMAC integrada; calcula una hora para un paso de código que firme el cuerpo, no cinco minutos de clics. Consulta [los triggers](../triggers.md#zapier-and-make-cannot-do-this-without-a-code-step).

## Registra la prueba { #record-the-trial }

Guarda los tres cuerpos de ticket, el prompt del trigger, el origen del secreto de firma (no su valor), el estado HTTP de cada entrega y el run que produjo cada una en Activity. Una persona sigue leyendo cada borrador antes de enviarlo y decide si el umbral de la señal de seguridad es lo bastante estricto para una bandeja real antes de apuntar un sistema de tickets en producción a este webhook.

## Siguientes pasos { #next-steps }

La misma fuente API sirve para cualquier otra cosa que pueda firmar y enviar JSON: el envío de un formulario, un cambio en un anuncio de un marketplace, una alerta de monitorización. Para un buzón en lugar de los tickets de tu propia app, consulta [clasifica tu bandeja de entrada y redacta respuestas](email-triage.md), que usa la fuente de Gmail en lugar de una entrega firmada.
