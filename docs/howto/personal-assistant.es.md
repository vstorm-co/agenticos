---
source_sha: "fc6566006c49"
title: "Construye un asistente personal que te recuerda"
description: "Dale a un agent memoria de tus preferencias, comprueba que una conversación posterior las aplica y confirma después que puede olvidar una cuando se lo pides."
---

# Construye un asistente personal que te recuerda { #build-a-personal-assistant-that-remembers-you }

Construye un asistente que lleva sus propias notas sobre la persona con la que habla, de una conversación a otra, sin nada que conectar y sin cuenta externa. Indica unas cuantas preferencias sintéticas, abre una conversación nueva y comprueba que el asistente las usa; después pídele que olvide una. Es un procedimiento para ejecutar, con un run registrado como referencia.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo.
- Sin sandbox, sin modelo de embeddings y sin conexión MCP: [Memoria](../reference/capabilities.md#memory-files) funciona sin nada vinculado.

## Prepara la entrada { #prepare-the-input }

Son datos inventados sobre una persona ficticia, lo bastante pocos para comprobarlos frente a las respuestas del asistente:

```text
Timezone: Europe/Warsaw
Meeting-free day: Friday
Summary format: short bullet points, not paragraphs
```

## Construye el agent { #build-the-agent }

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
2. En **Toolbox**, activa **Memory**, **Date and time** y **Past conversations**. Añade **Web search** si quieres que el resumen de abajo busque algo; las comprobaciones de esta página no lo necesitan.
3. Fija un budget y un límite de pasos para la prueba. Los runs registrados usaron entre 5 y 15 pasos y costaron entre 0,01 y 0,04 USD cada uno.
4. Escribe las instrucciones de abajo y luego pulsa **Publish**.

```text
You are a personal assistant that remembers what this person tells you about themselves.
When the person states a preference or a standing fact (timezone, working hours, meeting-free days, how they like summaries formatted), save it with write_memory under a short name, then read MEMORY.md and add or update a one-line entry for it with edit_memory (or write_memory if MEMORY.md does not exist yet).
When asked for a plan, a summary or a morning brief, apply every preference currently in your notes: check MEMORY.md, read any note it lists that is relevant, and follow it without being asked again.
When asked to forget something, delete the matching note with delete_memory, remove its line from MEMORY.md with edit_memory, and confirm in one sentence what you forgot.
Never save something the person has not actually told you.
```

`write_memory`, `edit_memory` y `delete_memory` tienen efectos secundarios, así que cada guardado u olvido queda aparcado como **Tool approval required** por defecto, igual que cualquier otra escritura. Apruébalo para continuar.

## Ejecútalo { #run-it }

**Conversación 1**: indica las preferencias.

```text
A few things about me: I'm in the Europe/Warsaw timezone, I keep Fridays meeting-free, and I prefer summaries as short bullet points rather than paragraphs.
```

**Conversación 2**: una conversación nueva con el mismo agent, pidiéndole que use lo que aprendió.

```text
Give me a plan for tomorrow. I have three things to fit in: a client call, writing a proposal, and a team sync.
```

**Conversación 3**: pídele que olvide una de las tres.

```text
Forget my meeting-free Fridays preference.
```

Una programación puede leer las instrucciones de este agent, pero no las notas de su propietario; consulta [lo que una programación no puede leer](#what-a-schedule-cannot-read) antes de conectar un resumen matinal a una.

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| La respuesta de la conversación 1 | Confirma las tres preferencias, después de aprobar tres llamadas a `write_memory` y una que escribe `MEMORY.md` |
| `MEMORY.md` después de la conversación 1 | Lista `timezone`, `meeting_free_days` y `summary_format` |
| El plan de la conversación 2 | Usa Europe/Warsaw, está casi todo en viñetas y no aplica mal la regla del viernes a un día que no es viernes |
| La respuesta de la conversación 3 | Dice en una frase qué olvidó |
| Settings → Memory (o `GET /memory/mine`) después de la conversación 3 | `meeting_free_days` ha desaparecido por completo; las otras dos notas no han cambiado |
| El **Run now** de una programación de resumen matinal, antes de que se le haya dicho nada en el chat | Dice que no hay nada guardado en lugar de adivinar; consulta abajo |

Abre Activity en cada run y revisa las llamadas a herramientas, no solo la respuesta: un `write_memory` que el modelo llamó pero que nadie aprobó nunca ocurrió.

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter. La conversación 1 llamó tres veces a `write_memory` y, una vez aprobado, escribió `MEMORY.md` como `- timezone [preference] — …`, `- meeting_free_days [preference] — …`, `- summary_format [preference] — …`. Coste: 0,039 USD.

    La conversación 2 llamó a `read_memory` sobre las tres notas y a `search_conversations` (que no encontró nada, correctamente, porque aún no se había dicho nada sobre mañana), y después respondió con un horario en viñetas en hora de Europe/Warsaw, señalando que mañana era sábado, así que la regla de días sin reuniones no se aplicaba. Coste: 0,026 USD.

    La conversación 3 llamó a `delete_memory` sobre `meeting_free_days` y, una vez aprobado, a `read_memory` y `edit_memory` sobre `MEMORY.md` para quitar su línea, y respondió "Done — I've forgotten your meeting-free Fridays preference and removed it from my index." Después, `GET /memory/mine` solo listaba `timezone` y `summary_format`. Coste: 0,043 USD.

## Lo que una programación no puede leer { #what-a-schedule-cannot-read }

Un disparo programado o por un trigger de eventos se ejecuta con el rol y los permisos de quien lo creó, pero para la memoria no es la conversación de nadie: `list_memory` en un **Run now** de una programación de resumen matinal respondió "This conversation has no memory. It has no identified person and is not a group chat, so a note would have to land somewhere other people read", la misma negativa que recibe un visitante anónimo del widget, aunque quien creó la programación es un miembro real y conocido.

Si un resumen programado necesita una preferencia, indícala en el propio prompt de la programación, igual que [un informe programado](scheduled-report.md) incluye sus datos en el mensaje en lugar de depender de la memoria o de un archivo que nadie vuelve a aportar.

## Quién puede leer esto { #who-can-read-this }

Nadie lee tus notas por su rol en la organización: ni un Owner, ni un Admin, ni alguien con permiso de edición sobre este agent. Llegas a las tuyas en **Settings → Memory** (`GET /memory/mine`), donde puedes dejar de usar una nota, volver a usarla o eliminarla del todo; "dejar de usar" la mantiene en la página para ti mientras deja de llegar a cualquier modelo.

Solo un administrador del despliegue puede leer las de otra persona, de una en una, y esa lectura queda en el registro de auditoría con quién la hizo, a quién afecta y un motivo, nunca con el contenido. Consulta [de quién son las notas y quién puede oírlas](../reference/capabilities.md#whose-notes-and-who-may-hear-them) y [leerlas y borrarlas](../reference/capabilities.md#reading-it-and-erasing-it).

En un chat de grupo la regla cambia: las notas pertenecen a la sala y todos sus participantes las leen, y nada de lo que se le dijo al asistente a solas se recupera allí. Esta prueba solo usó el chat web uno a uno, donde el almacén es solo tuyo.

## Cuando algo sale mal { #when-it-goes-wrong }

- **Un guardado o un olvido nunca ocurre.** `write_memory`, `edit_memory` y `delete_memory` tienen efectos secundarios y están protegidos por defecto; busca en **Approvals** de Activity una llamada aparcada antes de suponer que el modelo ignoró la indicación.
- **Una conversación posterior no conoce una preferencia guardada.** Revisa el propio `MEMORY.md`: una nota que el agent guardó pero nunca indexó es invisible hasta que el modelo llama a `list_memory`, algo que un modelo más ligero puede no hacer por su cuenta.
- **Un resumen programado adivina en lugar de usar tus notas.** Es lo esperado; consulta [lo que una programación no puede leer](#what-a-schedule-cannot-read) arriba. Pon el dato en el prompt de la programación.
- **Borrar una nota no la quita de todas partes.** `delete_memory` elimina la nota en sí; si la línea de `MEMORY.md` que la nombra no se reescribe también con `edit_memory`, el índice sigue describiendo algo que ya no existe.

## Registra la prueba { #record-the-trial }

Guarda cada conversación, la versión del agent, qué llamadas a `write_memory`/`delete_memory` se aprobaron y `GET /memory/mine` antes y después de la petición de olvido. Una persona sigue aprobando cada guardado y cada borrado, decide si **Allow personal memory** sigue activado para este agent y juzga si un plan refleja de verdad lo que se dijo: el asistente no se comprueba a sí mismo.

## Siguientes pasos { #next-steps }

Para llegar a este asistente desde una programación en lugar del chat web, lee primero [lo que una programación no puede leer](#what-a-schedule-cannot-read) y después [programa un informe semanal](scheduled-report.md) para ver cómo funcionan una cadencia y una conversación de registro de runs. Para que pueda buscar lo que realmente se dijo en conversaciones anteriores, y no solo lo que decidió guardar, consulta [la búsqueda en conversaciones](../reference/capabilities.md#conversation-search).
