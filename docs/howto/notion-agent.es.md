---
source_sha: "d73b776f3671"
title: "Busca y actualiza Notion desde un agent"
description: "Conecta Notion como servidor MCP, deja que un agent responda a partir de una página que encuentra por sí mismo y exige la revisión de una persona antes de que añada nada."
---

# Busca y actualiza Notion desde un agent { #search-and-update-notion-from-an-agent }

Conecta Notion mediante [MCP](../mcp.md) para que un agent pueda buscar en un workspace, responder con lo que encuentra y añadir notas de reunión a una página, con una persona que decide, cada vez, si la escritura se produce de verdad. Esta página describe ambos flujos y las decisiones exactas de conexión de las que dependen. No se puede ejecutar aquí: este entorno no tiene ninguna cuenta de Notion que conectar, así que abajo no hay run registrado.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo.
- **`connections:manage`** para añadir Notion para toda la organización, o nada más que una cuenta de miembro normal para conectarlo solo para ti, en **MCP servers → You**.
- Un workspace de Notion en el que puedas autorizar una app OAuth.

## Conecta Notion { #connect-notion }

Notion está en el catálogo con **oauth**, en `https://mcp.notion.com/mcp` (consulta [el catálogo](../mcp.md#communication-support-knowledge)). Antes de que un agent lo toque, importan dos decisiones:

**Organización o personal.** Añadirlo en **MCP servers → Organization** (`connections:manage`) hace que una sola conexión de Notion responda por cada agent vinculado a ella, en cada superficie, con un nombre y una identidad compartidos en el propio registro de auditoría de Notion. Añadirlo en su lugar en **MCP servers → You** significa que cada persona conecta su propio acceso al workspace, y una vinculación a *la propia cuenta de cada persona* (`account: personal` en la spec) hace que el agent hable con Notion como quien pregunta: el registro de Notion dice quién hizo qué, pero un compañero que no ha conectado su propio Notion recibe un mensaje pidiéndole que lo haga, no una respuesta sacada del de otra persona. Consulta [a través de qué cuenta habla una vinculación](../mcp.md#whose-account-a-binding-speaks-through).

**Un nombre y un prefijo de herramientas.** Conectar un segundo workspace de Notion obliga a un segundo nombre: el prefijo `notion` está ocupado, así que el segundo pasa a ser `notion-2`, y el modelo lee el prefijo que nombra su vinculación. Consulta [dos nombres, y responden a preguntas distintas](../mcp.md#two-names-and-they-answer-different-questions).

Para un equipo pequeño que usa un único workspace compartido, la cuenta de la organización es el comienzo más sencillo; cambia a la propia cuenta de cada persona cuando distintas personas solo deban llegar a lo que ve su propio inicio de sesión de Notion.

## Construye el agent { #build-the-agent }

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
2. En **Toolbox**, añade el servidor de Notion en **MCP servers**, vinculado a la cuenta de la organización (o a la de cada persona). Deja sus herramientas sin restringir en una primera prueba, o limita `allowed_tools` en la vinculación a una herramienta de búsqueda y lectura si este agent no debe escribir nunca.
3. Escribe las instrucciones de abajo y luego pulsa **Publish**.

```text
You answer questions from this organization's Notion workspace.
Search before you answer, and open the page you found before quoting it.
Cite the page's title in your answer, and say plainly if nothing in Notion answers the question.
When asked to add meeting notes to a page, find the exact page first, show the person what you are about to append, and only write it once they confirm.
```

El modelo llega a las herramientas de Notion con el prefijo de la conexión: `notion_search` y lo demás que encontrara la última comprobación, con el mismo prefijo. Qué herramientas existen se decide al comprobar la conexión, no escribiéndolas a mano en la spec; consulta [qué herramientas, y quién decide](../mcp.md#which-tools-and-who-decides).

## Flujo: encuentra una página y responde a partir de ella { #workflow-find-a-page-and-answer-from-it }

Haz una pregunta que el workspace debería poder responder, en una conversación nueva:

```text
Who owns the Q3 onboarding checklist, and where does it live?
```

El modelo llama a una herramienta de búsqueda, abre la página que parece correcta y responde con el título de la página como cita. Si nada coincide, las instrucciones de arriba le piden que lo diga en lugar de adivinar; comprueba esa negativa igual que comprobarías una respuesta correcta en la prueba de un agent con búsqueda en el conocimiento.

## Flujo: añade notas de reunión, con una persona que decide { #workflow-append-meeting-notes-with-a-person-deciding }

Este es el flujo en el que conviene ser exacto, porque **las herramientas MCP no tienen aprobación propia por herramienta**; el Builder lo dice directamente: *"MCP tools are outside the approval gate entirely: an approval set on a capability does not cover them, so anything these servers can do, this agent can do without asking."* Una herramienta de escritura que puedes nombrar en la spec, como `execute` o `send_email`, tiene un interruptor `required`/`never`/`default`; una herramienta de escritura de Notion descubierta al conectar nunca lo recibe, porque nada la declaró en el código. Consulta [lo que MCP no te da](../mcp.md#what-mcp-does-not-get-you).

La compuerta que sí llega hasta ella es la de la propia conversación. Antes de pedir al agent que escriba, quien habla con él abre **Chat controls → Approval mode** y elige **Ask about everything**, un ajuste de sesión que "reaches further than the spec's gate on purpose, to the tools no capability owns" (consulta [cuánto quiere que le pregunten a una conversación](../governance.md#how-much-one-conversation-wants-to-be-asked)). Con eso activado:

```text
Append these notes to the Q3 onboarding checklist page: attendees Ana and Marek, decided to move the kickoff to Monday, action item for Marek to update the calendar invite.
```

La herramienta de escritura se aparca ahora igual que `execute` en [la prueba del gráfico CSV](csv-chart.md#run-it): el chat muestra **Tool approval required** con la página y el contenido exactos que el modelo va a enviar, y una persona lo lee antes de elegir **Approve**. Si omites **Ask about everything**, la misma escritura se ejecuta de inmediato, sin nada que revisar, así que un agent vinculado a una conexión de Notion con escritura solo está tan revisado como el modo que eligió en ese turno la persona que habla con él.

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| Una pregunta que Notion responde | Cita el título de la página, y la respuesta coincide con lo que dice la página |
| Una pregunta que nada del workspace responde | Lo dice, en lugar de inventarse una página plausible |
| Añadir notas con **Ask about everything** desactivado | Se ejecuta de inmediato: confirma que es lo que quieres antes de que ocurra |
| Añadir notas con **Ask about everything** activado | Se aparca como **Tool approval required**, mostrando la página y el texto exactos |
| Rechazar la escritura aparcada | La página no cambia, y el agent puede transmitir la negativa en lugar de fallar |
| Alguien sin conexión personal de Notion, en una vinculación a cuentas personales | Se le pide que conecte una, en lugar de responderle desde el workspace de otra persona |

## Cuando algo sale mal { #when-it-goes-wrong }

- **El agent no tiene ninguna herramienta de Notion.** La conexión nunca se comprobó con éxito: abre **MCP servers**, ejecuta la comprobación y confirma que muestra una lista de herramientas antes de vincularla a un agent.
- **Se ejecuta una escritura sin que nadie la revise.** Comprueba el **Approval mode** de la propia conversación: `required` en una capability no llega a una herramienta MCP, así que una conexión con escritura necesita la sesión en **Ask about everything** cada vez que la revisión importe.
- **Dos conexiones de Notion chocan bajo un mismo nombre.** Renombra una; consulta [las colisiones de nombres](../mcp.md#name-collisions) para ver qué hace un run cuando no puede distinguirlas.
- **Un compañero recibe "connect your account" en lugar de una respuesta.** Es lo esperado en una vinculación a cuentas personales hasta que conecte su propio Notion en **MCP servers → You**.

## Registra la prueba { #record-the-trial }

Guarda la pregunta y su cita, el alcance de la conexión (organización o personal) y a qué workspace de Notion apunta, y cada escritura aprobada o rechazada con la página a la que iba dirigida. Una persona sigue decidiendo quién puede vincular a un agent una conexión de Notion con escritura, y revisa cada adición que ese modo no aparcó para revisión por su cuenta.

## Siguientes pasos { #next-steps }

Para la misma pregunta de revisión frente a un tracker de proyectos en lugar de un documento, consulta [convierte los elementos de acción de una reunión en tareas con aprobación](meeting-to-tasks.md). Para limitar lo que puede hacer la conexión de Notion de toda una organización antes de que ningún agent la vincule, consulta [qué herramientas, y quién decide](../mcp.md#which-tools-and-who-decides).
