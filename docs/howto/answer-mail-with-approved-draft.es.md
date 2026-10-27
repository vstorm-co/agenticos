---
title: "Responde al correo con un borrador aprobado"
description: "Un workflow lee el correo nuevo, redacta una respuesta, pide a una persona que la edite y la apruebe, y luego deja un borrador en el hilo o la envía mediante un servidor MCP de Gmail o Microsoft 365 que ejecutas tú."
source_sha: "fc39b8c85301"
---

# Responde al correo con un borrador aprobado { #answer-mail-with-an-approved-draft }

La [página de clasificación de la bandeja de entrada](email-triage.md) termina con un
texto en un chat. Esta da un paso más: un [workflow](../workflows.md) lee un mensaje
nuevo, redacta una respuesta, se la muestra a una persona que puede editarla y luego
la escribe en el buzón, como borrador en el mismo hilo o como respuesta enviada. Al
buzón se llega mediante un servidor MCP que ejecutas tú.

Es un procedimiento que seguir, no el informe de un despliegue medido. Necesita un
buzón, un registro de aplicación en Google o Microsoft y un servidor que los
mantenedores no ejecutaron para esta página, así que nada de lo que sigue se probó
con un buzón real. Los nombres de herramientas y argumentos se leyeron del código
fuente de los servidores, no de un servidor en marcha.

## Qué necesitas { #what-you-need }

- Uno de los dos servidores, en marcha donde el despliegue pueda alcanzarlo, con una
  dirección terminada en `/mcp`:
  [`taylorwilsdon/google_workspace_mcp`](https://github.com/taylorwilsdon/google_workspace_mcp)
  para Gmail, con `--transport streamable-http`, `MCP_ENABLE_OAUTH21=true` y tu
  propio cliente OAuth de Google, o
  [`softeria/ms-365-mcp-server`](https://github.com/softeria/ms-365-mcp-server) para
  Outlook, con `--http` y una aplicación registrada en Microsoft Entra (añade
  `--org-mode` para llegar a buzones compartidos). El catálogo los lista como
  **Google Workspace (self-hosted)** y **Microsoft 365 (self-hosted)**.
- Un servidor de tu propia red se rechaza hasta que un operador lista su host en
  `OUTBOUND_PRIVATE_ALLOWLIST` o `MCP_ALLOWED_HOSTS`. Consulta [servidores MCP](../mcp.md)
  y [ajustes](../configuration.md#project-settings).
- Una conexión MCP **de la organización** con ese servidor, creada desde esa entrada
  del catálogo por alguien con `mcp:manage`. Cada conexión inicia sesión como una
  cuenta, así que responde desde un buzón. Un workflow aún no puede usar la conexión
  de una persona, por lo que un buzón al que se llega así es una cuenta de servicio
  o un buzón compartido.
- El portal de Gmail o de Outlook conectado, para el trigger. El trigger lee el
  correo solo con acceso de lectura. El permiso de escritura está en la conexión
  MCP, una concesión aparte: conéctala como la cuenta que debe firmar las respuestas.

## Gmail { #gmail }

Construye el workflow en este orden.

1. Trigger **Gmail** ([`trigger.gmail`](../reference/workflow-nodes.md#trigger-gmail)).
   Su salida lleva `thread_id`, `rfc_message_id`, `subject`, `sender` y `text`.
2. Un paso de redacción: [`agent.run`](../reference/workflow-nodes.md#agent-run) con la
   capability de knowledge, o [`knowledge.search`](../reference/workflow-nodes.md#knowledge-search)
   seguido de [`ai.prompt`](../reference/workflow-nodes.md#model-steps). Su texto es
   la respuesta propuesta.
3. [`human.approval`](../reference/workflow-nodes.md#human-approval) con `editable`
   activado y `proposal` enlazado al paso de redacción. Quien aprueba lee el
   resumen del correo en `details`, edita el texto y aprueba.

4. [`mcp.call`](../reference/workflow-nodes.md#mcp-call) en la conexión de Google
   Workspace, herramienta `draft_gmail_message`, con estos argumentos:

   | Argumento | Enlazado a |
   |---|---|
   | `thread_id` | el `thread_id` del trigger |
   | `in_reply_to` | el `rfc_message_id` del trigger |
   | `body` | el `final` del paso de aprobación |

   Omite `references`: el servidor deriva la cadena a partir del mensaje al que se
   responde. Omite también `to` y el servidor responde al remitente de ese mensaje;
   pon `reply_all` en `true` para responder a todos los del hilo. Si omites
   `subject`, el borrador conserva el asunto del hilo. `user_google_email` lo rellena
   el servidor porque se ejecuta con `MCP_ENABLE_OAUTH21=true`.

   Pon **Ask for approval** de este paso en **Never**. Una persona aprobó el texto
   exacto un paso antes y, si no, se le preguntaría una segunda vez.

Para **enviar** en lugar de dejar un borrador, usa `send_gmail_message` con los mismos
argumentos y uno más: enlaza `to` al `sender` del trigger, o pon `reply_all` en
`true`. La herramienta rechaza una llamada que no tenga ninguno (`reply_all` necesita
el `thread_id`), y solo la herramienta de borradores rellena `to` por sí misma. El
servidor no tiene ninguna herramienta que envíe un borrador guardado, así que son dos
opciones separadas, no dos pasos.

!!! warning "Un envío directo no tiene protección"

    `send_gmail_message` no acepta una clave de idempotencia y el servidor lo marca
    como escritura. Si la llamada se hizo y no llegó respuesta, el paso termina como
    **Uncertain** y el run espera a una persona: el correo pudo salir o no. Abre el
    hilo en Gmail y mira antes de volver a ejecutar el paso. Cuando quieras una
    segunda oportunidad de detectar un error, usa `draft_gmail_message` y deja que
    una persona pulse **Enviar** en Gmail: una repetición como mucho deja un segundo
    borrador.

## Microsoft 365 { #microsoft-365 }

1. Trigger **Outlook** ([`trigger.outlook`](../reference/workflow-nodes.md#trigger-outlook)).
   Su salida lleva `message_id` y, para un buzón compartido, `mailbox`.
2. El mismo paso de redacción y el mismo `human.approval` editable que arriba.
3. **Construye el cuerpo de la respuesta.** Un paso **Map fields**
   ([`data.map`](../reference/workflow-nodes.md#data-map)) construye un campo,
   `reply_body`, de tipo `json` a partir del `final` de la aprobación:

   ```text
   {Message: {body: {contentType: 'text', content: source.final}}}
   ```

   con `source` enlazado al paso de aprobación; el resultado es `values.reply_body`.

   La propia indicación del servidor para `create-reply-draft` es pasar el texto como
   `Message.body.contentType` y `Message.body.content`; un cuerpo proporcionado
   reemplaza todo el cuerpo del borrador, así que el historial citado no va incluido.

   Comprueba los nombres de los argumentos en el formulario de la herramienta en el
   editor, después de elegirla y de actualizar sus herramientas: el servidor los
   construye a partir de Microsoft Graph y no se vieron en un servidor en marcha.

4. [`mcp.call`](../reference/workflow-nodes.md#mcp-call) en la conexión de Microsoft
   365, herramienta `create-reply-draft`, con `messageId` enlazado al `message_id` del
   trigger y `body` enlazado a `values.reply_body` del paso anterior. Graph asocia el
   borrador al hilo por sí mismo. Para un buzón compartido que lee el trigger, usa en
   su lugar `create-shared-mailbox-reply-draft`, añadiendo `userId` enlazado al
   `mailbox` del trigger; el servidor debe ejecutarse con `--org-mode`. El servidor
   registra sus parámetros de ruta en camelCase y los exige.

5. *Opcional.* Para enviar el borrador, primero lee su id. El servidor responde con
   JSON dentro de su `text`, no como datos `structured`, así que un paso
   [`code.python.simple`](../reference/workflow-nodes.md#python) lo extrae: enlaza
   `args.text` al `text` del paso que lo crea y ejecuta

   ```python
   import json
   json.loads(args['text'])['id']
   ```

   No ejecutes el servidor con `--toon`: su salida deja de ser JSON. Después llama a
   `send-draft-message` con `messageId` enlazado al `result` de ese paso
   (`send-shared-mailbox-draft` para un buzón compartido, que también toma `userId`
   enlazado al `mailbox` del trigger).

Pon **Ask for approval** de cada paso `mcp.call` en **Never** tras una aprobación
editable. Si no se aprobó nada antes del paso, conserva el valor por defecto,
**Before a tool that can change something**. Esa política pregunta antes de cualquier
herramienta que el servidor no marque como de solo lectura, así que pregunta también
antes de `create-reply-draft` y antes de `draft_gmail_message` de Gmail.

### Qué hace una repetición { #what-a-repeat-does }

Ninguno de los servidores acepta una clave de idempotencia, así que deja vacío
**Idempotency key argument** en estos pasos. Las siguientes fórmulas hacen inocua una
repetición sin ella.

- **Microsoft 365: crea y luego envía por el id del borrador.** Un segundo
  `send-draft-message` del mismo borrador falla, porque un borrador enviado ha dejado
  Borradores; no envía un segundo correo. Un `create-reply-draft` repetido puede dejar
  un borrador sobrante, nunca un segundo correo enviado. Si el paso de envío se corta
  después de la llamada, termina como **Uncertain**: mira en Elementos enviados y
  luego vuelve a ejecutarlo. Volver a ejecutar un envío que sí se hizo falla en lugar
  de enviar otra vez.
- **Gmail: deja un borrador** (recomendado). Una repetición deja como mucho un segundo
  borrador.
- **Gmail: un envío directo** no tiene esa protección; consulta la advertencia de
  arriba.

Un fallo antes de la llamada - servidor caído, conexión rechazada - se reintenta solo.
Tras una llamada sin clave a una herramienta que el servidor no marca como de solo
lectura, el paso nunca se repite por sí mismo. La [referencia de
`mcp.call`](../reference/workflow-nodes.md#mcp-call) tiene la regla.

## Seguridad { #safety }

El correo es entrada de fuera y puede llevar instrucciones dirigidas al modelo; la
documentación del servidor de Google Workspace lo advierte. Mantén el paso de
aprobación entre el paso de redacción y el buzón, y no des al agent que redacta una
herramienta que pueda escribir.

Los adjuntos llegan al workflow como archivos, pero una respuesta escrita así no lleva
ninguno.

## Compruébalo { #check-it }

- Un borrador o una respuesta enviada aparece en el hilo original del buzón; una enviada llega también al remitente.
- `In-Reply-To` del mensaje enviado o guardado como borrador es igual al
  `rfc_message_id` del trigger.
- Edita el texto en la aprobación y comprueba que el texto editado, no la propuesta,
  es el que llega al buzón.
- Rechaza la aprobación y comprueba que no se escribe nada.

## Siguientes pasos desde la misma conexión { #next-steps-from-the-same-connection }

- **Google Calendar:** `query_freebusy`, `get_events`, `manage_event`.
- **Google Drive:** `search_drive_files`, `get_drive_file_content`.
- **Google Sheets:** `append_table_rows`, `read_sheet_values`.
- **Calendario de Microsoft 365:** `list-calendar-events`, `create-calendar-event`.

Existe otra vía hacia Microsoft: el servidor alojado **Microsoft Work IQ** responde
preguntas sobre correo, reuniones, chats y archivos, pero bloquea los cambios hasta
que un administrador del tenant los permita. Consulta [Microsoft 365 y
Outlook](../mcp.md#outlook-setup).
