---
source_sha: "1d2ade73a284"
title: "Resume una transcripción de reunión en decisiones y elementos de acción"
description: "Pega una breve transcripción sintética y comprueba que el agent separa las decisiones de las tareas, nombra un responsable y una fecha para cada una y señala la única tarea que nadie asumió."
---

# Resume una transcripción de reunión en decisiones y elementos de acción { #summarise-a-meeting-transcript-into-decisions-and-action-items }

Construye un agent que convierte una transcripción pegada en tres listas cortas: decisiones, tareas con responsable y fecha límite, y preguntas abiertas. La transcripción de ejemplo tiene una tarea que se menciona pero que nadie acepta de verdad; la comprobación que más importa es si el agent lo dice con honestidad en lugar de asignársela a quien aparece cerca. Es un procedimiento para ejecutar, con un run registrado como referencia.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo.
- Ninguna capability. Este agent lee lo que hay en el mensaje y nada más.

## Prepara la entrada { #prepare-the-input }

Una transcripción breve y sintética, inventada para esta página:

```text
Onboarding revamp sync — 12 March, 10:00–10:35
Jenna: Let's get through this quickly. Marcus, where are we with the signup
API changes?
Marcus: Mostly done. I can have the new field validation live by March 20.
Jenna: Good. Priya, the tooltip designs?
Priya: Almost there. I can deliver the final set by March 18, in time for
Marcus to wire them up.
Jenna: Great. Let's also decide on the survey step. Tomas, you said support
tickets show people dropping off there.
Tomas: Right, about a third of drop-offs happen on the survey screen. My
recommendation is to remove it entirely rather than shorten it.
Jenna: Agreed, let's remove the survey step from onboarding. Marcus, can you
fold that into the same API change?
Marcus: Yes, same PR.
Jenna: Decision made — the survey step is gone. Now, should the new tooltip
flow go to everyone at once, or beta first?
Priya: Beta first. We haven't tested it on mobile yet.
Marcus: Agreed, mobile rendering is still rough.
Jenna: Okay, decision: new tooltip flow ships to beta users first, general
release after that's clean.
Tomas: One more thing — the help center article on "how onboarding works"
is now out of date once the survey step is gone. Somebody should update it
before we ship.
Jenna: Good catch. Let's make sure that happens.
Priya: I can't take that on, I'm full up with the tooltip work through the
20th.
Marcus: Not mine either, that's not engineering's article.
Jenna: Okay, let's flag it and figure out who owns docs later this week.
Tomas: Compiling the onboarding-related support tickets into a report —
I'll do that, but I don't have a firm date yet, depends on how much backlog
I need to dig through.
Jenna: That's fine, just get it to us when it's ready.
Jenna: Last open question — do we sunset the old onboarding flow entirely,
or keep it behind a flag as a fallback for a few weeks?
Marcus: I'd lean toward keeping the flag, in case the new flow breaks
something we didn't catch in beta.
Priya: I don't have a strong opinion either way.
Jenna: Let's leave that open and revisit once beta feedback comes in.
Jenna: Okay, I think that's everything. Thanks all.
```

La referencia: dos decisiones (eliminar el paso de la encuesta; lanzar primero el flujo de tooltips en beta), cuatro tareas con responsable, una tarea (actualizar el artículo del centro de ayuda) que Priya y Marcus rechazan explícitamente, y una pregunta abierta que queda para más adelante.

## Construye el agent { #build-the-agent }

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
2. Deja vacío el Toolbox. Nada de esto necesita una herramienta.
3. Fija un budget y un límite de pasos para la prueba.
4. Escribe las instrucciones de abajo y luego pulsa **Publish**.

```text
You turn a pasted meeting transcript into three sections: Decisions,
Action items, and Open questions.

For each action item, name the owner and the due date exactly as stated. If
a task is mentioned but nobody agreed to own it, list it under Action items
as unassigned and say so - never guess an owner, and never assign it to
someone who explicitly declined it in the transcript.

List a topic under Open questions only if the transcript does not record a
decision on it. Do not invent a decision, an owner, or a date the transcript
does not state.
```

## Ejecútalo { #run-it }

Pega la transcripción directamente en una conversación nueva, tras una instrucción breve:

```text
Summarise this meeting transcript into decisions, action items and open questions.

[paste the transcript]
```

Adjuntarla como archivo de texto funciona igual: un agent sin workspace recibe el texto de una subida pegado en el prompt, igual que al pegarlo. Consulta [el procesamiento de archivos](../file-processing.md#chat-file-uploads).

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| Decisiones | Eliminar el paso de la encuesta; lanzar primero el flujo de tooltips en beta |
| Tareas de Marcus | La validación de campos y la eliminación del paso de la encuesta, para el 20 de marzo |
| Tarea de Priya | Los diseños finales de los tooltips, para el 18 de marzo |
| Tarea de Tomas | Recopilar el informe de tickets de soporte, sin ninguna fecha inventada |
| El artículo del centro de ayuda | Aparece como sin asignar, no se le da a Priya ni a Marcus |
| Preguntas abiertas | Solo la de retirada frente a alternativa, no una decisión repetida como pregunta |

Comprueba primero la tarea sin asignar. Un agent que se la entrega en silencio al nombre que aparece más cerca en la transcripción ha fallado la única comprobación para la que existe esta página, aunque todas las demás líneas sean correctas.

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter. Sin llamadas a herramientas: toda la respuesta salió de una petición al modelo, por 0,0063 USD. Enumeró las dos decisiones, dio a Marcus dos tareas (validación de campos y eliminación del paso de la encuesta, ambas para el 20 de marzo), a Priya los diseños de tooltips para el 18 de marzo y a Tomas el informe con "no firm date — to be delivered when ready". El artículo del centro de ayuda apareció como **"Unassigned (Priya and Marcus both declined; owner to be determined later this week)"** en lugar de asignárselo a cualquiera de ellos. La única pregunta abierta fue la decisión entre retirada y alternativa, marcada como aplazada.

## Cuando algo sale mal { #when-it-goes-wrong }

- **La tarea que nadie asumió se asigna igualmente.** Es el fallo que hay que vigilar. Endurece aún más las instrucciones; nombrar la expresión exacta "declined" o "unassigned" a veces ayuda menos que añadir una segunda transcripción en la que se repita el mismo patrón, para ver si el primer resultado fue suerte.
- **Aparece una fecha límite que nadie dijo.** El modelo rellenó un hueco porque una tarea sin fecha parece incompleta. Comprueba que la última línea de las instrucciones cumple su función y prueba con una transcripción que tenga más de una tarea sin fecha.
- **Una pregunta abierta repite algo ya decidido.** El modelo trató como abierta una decisión tomada bajo presión, al final de la reunión. Señálale la línea exacta en la que se tomó.
- **Las tres secciones se mezclan.** Con una transcripción más larga y desordenada, pide las secciones en un orden fijo y comprueba que cada una contiene solo lo que le corresponde.

## Registra la prueba { #record-the-trial }

Guarda la transcripción, el prompt exacto, la versión del agent, el modelo y la respuesta. Una persona sigue comprobando la tarea sin asignar directamente en la transcripción: es justo el tipo de detalle pequeño y fácil de pasar por alto que se salta una lectura rápida de un resumen largo.

## Siguientes pasos { #next-steps }

Convertir cada tarea en un elemento de seguimiento real, con el responsable avisado, es un paso aparte que cubre [convierte los elementos de acción de una reunión en tareas con aprobación](meeting-to-tasks.md). Esta página se detiene en el resumen que una persona lee y comprueba.
