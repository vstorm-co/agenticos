---
source_sha: "70839ec256fb"
title: "Convierte los elementos de acción de una reunión en tareas con aprobación"
description: "Haz que un agent proponga una tarea en el tracker por cada elemento de acción real de una transcripción, y exige que una persona apruebe cada una antes de crearla."
---

# Convierte los elementos de acción de una reunión en tareas con aprobación { #turn-meeting-action-items-into-tasks-with-approval }

Dale a un agent los elementos de acción de una transcripción de reunión y una [conexión MCP con Linear o Jira](../mcp.md#project-management), y haz que proponga una tarea por elemento en lugar de crear nada sin supervisión. La persona que lee las propuestas las edita o las rechaza antes de que llegue una sola tarea al tracker. Esta página no se puede ejecutar aquí de principio a fin: este entorno no tiene conexión con Linear ni con Jira, así que abajo no hay run registrado.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo.
- **`connections:manage`** para añadir Linear o Jira como conexión MCP de toda la organización, o una cuenta de miembro normal para conectar una para ti en **MCP servers → You**.
- Una transcripción de reunión con la que trabajar. [Resumir una reunión](meeting-summary.md) explica cómo comprobar sus decisiones y elementos de acción antes de que alguno se convierta en tarea.

## Prepara la entrada { #prepare-the-input }

Una pequeña transcripción inventada con un elemento de acción claro, otro sin fecha límite y una preocupación planteada que nadie asume realmente; esta última es el caso límite que conviene comprobar:

```text
Weekly ops sync - 24 September 2026
Attendees: Priya, Tom, Sana

- Priya will update the onboarding doc with the new pricing tiers by Friday.
- Tom will follow up with the vendor about the delayed shipment.
- Sana raised that the support queue is growing, but nobody was assigned to look into it.
```

Referencia: dos elementos de acción reales (Priya, para el viernes; Tom, sin fecha indicada) y una pregunta abierta sin responsable, que no es un elemento de acción.

## Conecta el tracker { #connect-the-tracker }

Linear está en el catálogo con **oauth**, en `https://mcp.linear.app/sse`; Jira y Confluence comparten una entrada, también **oauth**, en `https://mcp.atlassian.com/v1/sse` (consulta [el catálogo](../mcp.md#project-management)). Para un tracker en el que registra todo el equipo, conéctalo en **MCP servers → Organization** para que cada agent vinculado cree las tareas con la misma identidad de integración; vincula en su lugar [la propia cuenta de cada persona](../mcp.md#whose-account-a-binding-speaks-through) solo si tu tracker espera que las tareas se registren a nombre de quien las pidió.

En la conexión, limita `allowed_tools` a la herramienta de crear y comentar que necesita este flujo, si el servidor también ofrece otras que editan o eliminan issues existentes; la vinculación solo puede restringir dentro de lo que ya permite la conexión, nunca recuperar lo que esta excluye.

## Construye el agent { #build-the-agent }

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
2. En **Toolbox**, añade el tracker en **MCP servers**.
3. Escribe las instrucciones de abajo y luego pulsa **Publish**.

```text
You turn meeting notes into tracker tasks.
Propose one task per real action item: a title, the assignee named in the notes, a due date only if one was actually stated, and a one-line description.
Do not invent an assignee, a due date or a priority that the notes do not state.
If something was raised but nobody was assigned to it, say so as an open question rather than proposing a task for it.
Create each proposed task with its own tool call, one at a time, so each can be reviewed on its own.
```

## Ejecútalo { #run-it }

Antes de pedir al agent que cree nada, abre **Chat controls → Approval mode** y elige **Ask about everything**. Esto importa aquí por la misma razón que al [añadir notas a Notion](notion-agent.md#workflow-append-meeting-notes-with-a-person-deciding): la herramienta de creación del tracker se descubre a partir de la conexión MCP en tiempo de ejecución, así que ninguna aprobación por herramienta declarada en la spec llega hasta ella; el modo de aprobación de la propia sesión es la única compuerta por la que pasa una llamada de creación.

```text
Turn the action items in this transcript into tasks:

Weekly ops sync - 24 September 2026
Attendees: Priya, Tom, Sana

- Priya will update the onboarding doc with the new pricing tiers by Friday.
- Tom will follow up with the vendor about the delayed shipment.
- Sana raised that the support queue is growing, but nobody was assigned to look into it.
```

Cada llamada de creación se aparca por separado: un modelo que propone dos tareas en un paso aparca dos filas de aprobación distintas, cada una decidida de forma independiente. Lee el título, el responsable y la fecha exactos de cada una antes de elegir **Approve** o rechazarla; una llamada rechazada vuelve al agent como una negativa con la que puede actuar, no como un fallo.

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| Número de tareas propuestas | Dos, una por elemento de acción real |
| La tarea de Priya | Asignada a Priya, para el viernes |
| La tarea de Tom | Asignada a Tom, sin fecha inventada |
| El punto de Sana | No se propone como tarea; se nombra como pregunta abierta sin responsable |
| Rechazar una tarea propuesta | El tracker no la recibe; la respuesta final del agent dice cuál se omitió |
| Aprobar el resto | El tracker recibe exactamente las tareas aprobadas, nada más |
| La misma transcripción con **Ask about everything** desactivado | Cada tarea propuesta se crea de inmediato, sin nada que revisar antes |
| Una transcripción sin ningún elemento de acción | Dice que no hay nada que convertir en tarea, en lugar de inventarse una |

## Cuando algo sale mal { #when-it-goes-wrong }

- **Se crea una tarea antes de que nadie la revise.** Comprueba primero el **Approval mode** de la conversación: `required` en una capability nunca llega a una herramienta MCP, así que la revisión depende de que la sesión esté en **Ask about everything**, cada vez.
- **El agent se inventa una fecha o un responsable.** Endurece las instrucciones, no la conexión: es un fallo del prompt, y la transcripción ya debería haberle dicho lo que no sabe.
- **Una preocupación planteada se convierte en tarea igualmente.** Comprueba que las instrucciones distinguen "asignado a alguien" de "mencionado"; la pregunta abierta del ejemplo existe justo para detectar esto.
- **Dos agents distintos proponen una tarea para el mismo elemento de acción.** Aquí la fuente de verdad es el propio tracker, no el historial de runs de esta plataforma; busca un duplicado en el tracker antes de suponer que el agent se equivoca.

## Registra la prueba { #record-the-trial }

Guarda la transcripción, cada tarea propuesta, cuáles se aprobaron o rechazaron y el estado posterior del propio tracker: el registro de aprobaciones de AgenticOS guarda lo que se propuso y quién decidió, no si el tracker sigue así más tarde. Una persona sigue leyendo cada propuesta, corrige un responsable equivocado antes de aprobar y no después, y decide quién puede vincular a un agent una conexión de tracker capaz de crear tareas.

## Siguientes pasos { #next-steps }

Para el mismo patrón de aprobar antes de escribir, pero sobre un documento en lugar de un tracker, consulta [busca y actualiza Notion desde un agent](notion-agent.md). Para comprobar las decisiones y elementos de acción de una transcripción antes de convertir alguno en tarea, consulta [resume una transcripción de reunión](meeting-summary.md).
