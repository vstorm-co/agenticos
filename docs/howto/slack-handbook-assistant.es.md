---
source_sha: "fcf4f76f3d2d"
title: "Responde una pregunta sobre el manual en Slack"
description: "Pon el agent con documentos en un canal de prueba de Slack, haz las mismas preguntas y comprueba a quién pertenecía cada run."
---

# Responde una pregunta sobre el manual en Slack { #answer-a-handbook-question-in-slack }

Pon el [agent con documentos](first-document-agent.md) en un canal de prueba de Slack y hazle las preguntas que ya comprobaste en la consola. El resultado que buscas es la misma respuesta comprobada en un hilo de Slack, y un run en Activity registrado en la superficie `slack`. Es un procedimiento que ejecutar, no un informe de un despliegue medido.

## Antes de empezar { #before-you-start }

- **El agent con documentos supera sus tres comprobaciones en la consola.** Mantén fijos su manual, su modelo y su versión publicada mientras añades Slack. Si el modelo, los documentos y el canal cambian a la vez, una respuesta distinta no te dice cuál de los cambios la provocó.
- **Un workspace de Slack en el que puedas instalar apps.** Usa un workspace de prueba o un canal de prueba. El manual es sintético, así que no hay nada privado en juego mientras aprendes el recorrido.
- **El permiso `channels:manage`** para registrar el bot, y `agents:publish` sobre el agent, por tu rol o por un grant, para vincularlo.

Socket Mode es el transporte que se usa abajo. El bot abre la conexión con Slack, así que no hace falta que nada sea accesible desde internet. Eso lo convierte en la elección adecuada en un portátil. [Canales](../channels.md#slack) describe la alternativa de la Events API.

## Crea la app de Slack { #create-the-slack-app }

1. En **api.slack.com/apps → Create New App → From an app manifest**, elige el workspace de prueba y pega el manifiesto de la [sección de Slack de Canales](../channels.md#slack). Cambia `name` y `display_name` por el nombre que deba tener el bot. Revisa los scopes antes de instalar: la [tabla de scopes](../channels.md#scopes-and-events) indica qué llamada necesita cada uno.
2. En **Basic Information → App-Level Tokens → Generate**, añade el scope `connections:write` y copia el token `xapp-`.
3. En **Install App → Install to Workspace → Allow**, instálala y copia el **Bot User OAuth Token** (`xoxb-`).

!!! warning "Deja desactivada la rotación de tokens"

    Con la rotación de tokens activada, el token `xoxb-` caduca y el bot deja de responder. La plataforma guarda un token de bot estático y no lo renueva.

Mantén ambos tokens fuera de capturas de pantalla, grabaciones y solicitudes de ayuda.

## Registra el bot y vincula el agent { #register-the-bot-and-bind-the-agent }

1. En **Channels → Add channel**, elige Slack. Pega el token del bot en **Bot token** y el token `xapp-` en **App-level token**. Ambos quedan sellados en el [vault](../secrets.md) y no se vuelven a mostrar.
2. La nueva fila dice *No agent bound - this bot answers nothing*. Es lo esperado hasta el siguiente paso.
3. Abre el agent con documentos en el Builder, ve a **Availability** y elige el bot en **Where this agent is available**. El agent debe tener una versión publicada.
4. Deja desactivadas las consultas al canal. Una pregunta sobre el manual no necesita que el agent lea el historial del canal ni su lista de miembros, y cada consulta es una [decisión aparte](../reference/capabilities.md#chat-channel-lookup).
5. En Slack, crea un canal de prueba e invita al bot con `/invite @your-bot`.

## Haz las preguntas { #ask-the-questions }

Haz cada pregunta en Slack y compara la respuesta con la fuente.

| Dónde y qué | Comprobación de referencia |
| --- | --- |
| En el canal: `@your-bot Who handles an equipment request?` | Nombra al office manager y dice que usó el manual |
| Respuesta en ese hilo: `Which details should I include?` | Artículo, motivo y lugar de entrega, respondido en el mismo hilo |
| Un mensaje nuevo en el canal: `@your-bot How much can I spend?` | Dice que el manual no indica ninguna asignación |
| Un mensaje en el canal que no menciona al bot | Ninguna respuesta |
| Un mensaje directo al bot, antes de vincular tu cuenta | Te pide que conectes tu cuenta y envía un enlace |

Un hilo es una conversación. La respuesta en el hilo mantiene en contexto la primera respuesta. Un mensaje nuevo en el canal empieza una conversación nueva sin memoria de la anterior. Consulta [una conversación por hilo](../channels.md#one-conversation-per-thread).

La mención debe ser una que Slack haya resuelto, elegida en el autocompletado. Un identificador escrito como texto plano no es una mención, y el bot se queda en silencio.

## Comprueba a quién pertenecía cada run { #check-who-each-run-belonged-to }

Abre **Activity** y busca los runs. Cada uno registra la superficie `slack`, la versión del agent que respondió y la cuenta de Slack que escribió el mensaje. Abre un run y comprueba que llamó a `search_documents` y que el pasaje recuperado es aquel en el que se basa la respuesta.

Un remitente que no ha vinculado una cuenta de Slack a un miembro sigue recibiendo respuesta en un canal. Ese run adopta el rol de la persona que vinculó el agent al bot. Así que cualquiera que pueda escribir en el canal puede gastar el budget de la organización y leer, a través del agent, lo que contienen las colecciones vinculadas.

!!! info "Los miembros del canal son el público del documento"

    El agent busca en las colecciones que vincula su spec, pregunte quien pregunte. Los permisos propios de un usuario de Slack en AgenticOS no lo restringen. Elige el canal y la colección a la vez, y nunca pruebes reglas de acceso con un documento privado.

Para vincular tu propia cuenta, envía un mensaje directo al bot. Te responde con un enlace. Ábrelo en el navegador en el que tienes la sesión iniciada en la consola y confirma **Connect this account**. A partir de entonces tus mensajes se ejecutan como tú, con tus permisos y tu budget. El enlace dura quince minutos y funciona una sola vez. Las cuentas vinculadas aparecen en **Settings → Profile → Chat accounts**.

Para rechazar también en los canales a los remitentes no vinculados, activa `require_link` en la política de acceso del bot. Las reglas y el límite de frecuencia por cuenta están en [la vinculación, y dónde es obligatoria](../channels.md#what-every-channel-shares).

## Cuando no responde { #when-it-does-not-answer }

Recorre el camino en este orden:

1. La fila del bot en **Channels** muestra **Not connected**. La insignia indica el motivo, a menudo un token `xapp-` incorrecto o ausente.
2. La fila sigue diciendo que no hay ningún agent vinculado, o el agent no tiene ninguna versión publicada.
3. Falta un scope o un event. Añadir uno implica reinstalar la app, lo que emite un nuevo token `xoxb-`. Pega el token nuevo en los ajustes del bot, o el bot conserva el acceso que tenía.
4. El bot no está en el canal, o el mensaje no era una mención resuelta.
5. Un mensaje directo desde una cuenta no vinculada se rechaza hasta que la vincules.

Si el bot responde pero la respuesta es incorrecta, el recorrido de Slack funciona. Revisa la recuperación en Activity y los documentos de la colección antes de cambiar nada en Slack. [Canales](../channels.md#slack) enumera qué se notifica y qué no cuando un bot está en silencio.

## Registra la prueba { #record-the-trial }

Conserva juntos estos elementos, para que otra persona pueda repetir la prueba y comparar:

- la versión de AgenticOS, la versión del agent, el perfil de modelo y la colección con el estado de sus documentos;
- el manifiesto de Slack que pegaste, sin tokens, y el transporte;
- cada pregunta, la respuesta tal como se publicó en Slack y el run correspondiente en Activity;
- cada fallo, incluido un bot en silencio, y lo que lo solucionó;
- quién instaló la app, quién vinculó el agent y quién juzgó las respuestas.

Aquí una persona hace tres cosas que ningún ajuste sustituye: instala la app, decide qué canal puede llegar a qué documentos y juzga cada respuesta frente a la fuente. Una captura de la página Channels explica la configuración. Solo el hilo, con la pregunta y la respuesta una junto a otra, muestra el resultado.

## Siguientes pasos { #next-steps }

Antes de sustituir el manual sintético por uno real, decide quién debe poder llegar a ese documento y elige el canal en consecuencia. Nombra quién actualiza el documento, quién cambia el agent y quién hace el seguimiento de las preguntas que el manual no puede responder. [Despliega y opera AgenticOS](../rollout.md) cubre esos roles.
