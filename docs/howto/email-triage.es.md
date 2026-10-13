---
source_sha: "94fe4ff073a5"
title: "Clasifica tu bandeja de entrada y redacta respuestas"
description: "Conecta un buzón como trigger de eventos consultado periódicamente y haz que un agent redacte respuestas o extraiga tareas, sin enviar nunca nada."
---

# Clasifica tu bandeja de entrada y redacta respuestas { #triage-your-inbox-and-draft-replies }

Conecta un buzón de Gmail como [trigger de eventos](../triggers.md#gmail-1-minute-and-no-secret-anywhere) y haz que un agent lea cada mensaje nuevo y produzca un borrador de respuesta o una lista de tareas. Es un procedimiento para ejecutar, no el informe de un despliegue medido: necesita una cuenta real de Gmail y un cliente OAuth de Google que el despliegue no tiene configurado aquí, así que nada de esta página se ha disparado contra un buzón real.

## Lo que el agent puede y no puede hacer con el correo { #what-the-agent-can-and-cannot-do-with-mail }

Lee esto antes de conectar nada, porque decide si la página de abajo compensa el consentimiento de OAuth.

**Puede leer.** El trigger de Gmail consulta el buzón conectado una vez por minuto y entrega al agent el asunto, el remitente y el cuerpo de un mensaje nuevo. El despliegue solo pide a Google el alcance `gmail.readonly`: en la pantalla de consentimiento no se solicita nada más, así que no existe un permiso más amplio en el que apoyarse por accidente.

**No puede enviar, ni crear un borrador real en Gmail.** No hay ninguna herramienta, ni aquí ni en el catálogo MCP, que llame a la API de envío o de borradores de Gmail. Lo que las plantillas de abajo llaman "borrador" es el texto de respuesta del agent, escrito en el run que se disparó: queda en **Activity**, en la conversación de ese run, como un mensaje que una persona tiene que leer y pegar ella misma en un correo saliente. Nunca se envía nada en tu nombre ni se escribe nada de vuelta en el buzón.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo.
- Un cliente OAuth de Google que haya registrado el operador del despliegue (`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`, con la API de Gmail activada). Es un requisito del *despliegue*, no algo que cada organización configure por su cuenta. Sin él, la tarjeta de conexión de Gmail lo indica en lugar de mostrar un botón que solo podría fallar.
- El permiso `mcp:manage`, para conectar el buzón.

## Construye el agent { #build-the-agent }

1. Abre **Routines → New event trigger → Gmail → Connect account**. El consentimiento autoriza acceso de solo lectura al buzón; conectarlo no dispara nada ni pierde nada, porque la posición del buzón se toma en el momento en que termina el consentimiento.
2. Elige qué lo dispara: cualquier mensaje nuevo, solo la bandeja de entrada o los marcados como importantes. Acota más con **Subject contains**, **Sender contains** o una etiqueta de Gmail: los tres son filtros opcionales de subcadena, y uno sin definir significa que dispara cada mensaje dentro del alcance.
3. Parte de una plantilla en lugar de un prompt en blanco. `GET /trigger-templates` lista dos para esta fuente:

   | Plantilla | Qué hace |
   | --- | --- |
   | **Draft a reply to the email** | Resume en una línea lo que necesita el remitente y luego redacta una respuesta para revisar |
   | **Turn the email into action items** | Extrae cada tarea, su responsable y cualquier fecha límite |

4. Crea un agent para que lo dispare este trigger, con un perfil de modelo, y publícalo. Ninguna de las dos plantillas necesita sandbox, colección de conocimiento ni otra capability.
5. Vincula el trigger al agent publicado y actívalo.

El prompt de la plantilla de borrador de respuesta, literal:

```text
An email just arrived - its subject, sender and body are in this message.
Summarise in one line what the sender needs, then draft a reply I can review and
send. Match the sender's tone, answer every question they asked, and keep it
brief.
```

## Qué significa "Ejecútalo" aquí { #what-run-it-means-here }

No hay ninguna entrega firmada que enviar a mano: Gmail se consulta, no empuja, así que no hay ni URL ni secreto. Hay dos formas de ver trabajar al agent antes de que llegue un mensaje real:

- **Run now**, en el trigger, dispara el **prompt base del agent sin contexto de entrega**: sin mensaje, sin remitente, sin nada a lo que responder. Demuestra que el agent, su budget y su estado de publicación están en orden, pero no pone a prueba la clasificación: en ese run no hay correo sobre el que actúen las instrucciones de la plantilla.
- **Un mensaje real que llega al buzón conectado** es la única forma de ver un borrador de verdad. El heartbeat lee lo que ha llegado desde su última comprobación, una vez por minuto, hasta 25 mensajes por ciclo, así que la latencia máxima es de un minuto y una ráfaga de una lista de correo no se convierte en cientos de runs.

## Comprueba el resultado { #check-the-result }

Cuando un mensaje real haya disparado el trigger, las comprobaciones generales son:

| Comprobación | Referencia |
| --- | --- |
| Un mensaje que coincide con el filtro | Dispara una vez, y la conversación del run contiene un borrador de respuesta o una lista de tareas, nunca un correo enviado |
| Un mensaje que **no** coincide con asunto/remitente/etiqueta | No dispara en absoluto |
| Un correo sin pregunta ni tarea clara | La plantilla de tareas dice claramente que no hay trabajo que hacer, en lugar de inventarse uno |
| El estado propio de la conexión de Gmail | Se muestra en el trigger; una consulta fallida se notifica ahí, no solo en un log del contenedor |
| Correo anterior a la conexión del buzón | Nunca dispara: el cursor empieza en el momento en que terminó el consentimiento |

## Cuando algo sale mal { #when-it-goes-wrong }

- **No se dispara nada.** Comprueba primero el estado de la conexión de Gmail: una consulta rota se notifica en el trigger. Luego revisa el filtro: un **Subject contains** o **Sender contains** vacío coincide con todo, así que un filtro estrecho que parece correcto sobre el papel puede excluir igualmente el mensaje que enviaste de prueba.
- **Esperas una respuesta enviada y recibes un mensaje de chat.** Así está diseñado, no es un fallo; consulta *Lo que el agent puede y no puede hacer con el correo* arriba. Copia el borrador a tu cliente de correo a mano.
- **Un atraso perdido tras una caída.** Google conserva alrededor de una semana de historial; un cursor más antiguo se resincroniza al momento actual en lugar de reproducir todo lo acumulado, así que un buzón caído más de una semana tiene un hueco que nada rellena.
- **`Run now` parece haber funcionado pero no devolvió nada útil.** Ejecutó el agent sin ningún mensaje adjunto: es lo esperado y no sirve para probar la clasificación. Espera a una entrega real o envíate un correo de prueba que coincida.

## Registra la prueba { #record-the-trial }

Cuando puedas ejecutar esto contra un buzón real: guarda el filtro que configuraste, la plantilla o el prompt usado, unos cuantos runs disparados con sus borradores y quién lee esos borradores antes de que se envíe nada. Una persona envía cada respuesta y registra cada tarea; este agent solo prepara el texto.

## Siguientes pasos { #next-steps }

Para una clasificación impulsada por tu propia app en lugar de un buzón, consulta [clasifica las solicitudes de soporte entrantes desde tu propia app](support-ticket-triage.md), que usa un webhook firmado que controlas de principio a fin y se puede verificar sin una cuenta externa.
