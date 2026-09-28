---
source_sha: "2db3d6fc670a"
title: "Construye un wiki de LLM que el agent mantiene"
description: "Dale a un agent un workspace que sobrevive entre conversaciones y un archivo de esquema, y deja que convierta notas en bruto en un pequeño wiki de Markdown enlazado."
---

# Construye un wiki de LLM que el agent mantiene { #build-an-llm-wiki-the-agent-maintains }

Andrej Karpathy describió este patrón en abril de 2026: guarda las fuentes en bruto intactas en un lugar, haz que un agent las compile en un pequeño wiki de Markdown enlazado en otro, y escribe el esquema para que cualquier sesión posterior pueda contrastarse con él en lugar de volver a adivinar la estructura. Esta página lo construye sobre un workspace que sobrevive a una sola conversación, con dos fuentes sintéticas incorporadas con una sesión de diferencia.

Es un procedimiento para ejecutar, con un run registrado como referencia: las dos conversaciones de incorporación de abajo se ejecutaron completas; a la pregunta y al paso de lint no se llegó en ese run, y están marcados como tales.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo y una [conexión de sandbox](../sandbox.md) registrada que ofrezca el runtime `workbench`.
- Ninguna otra capability. El wiki vive entero en el workspace del agent.

## Prepara la entrada { #prepare-the-input }

Dos notas cortas que parecen no tener relación pero comparten un dato, para que el wiki tenga un motivo para enlazarlas.

Fuente uno, pegada en la primera conversación:

```text
Meeting notes, 3 March. The team adopts a weekly on-call rotation starting
Monday. Alice is on-call first, then Bob, then Carol, rotating every Monday
at 9am. Escalation rule: if the on-call person does not respond within 15
minutes, page the backup, who is always the previous week's on-call person.
```

Fuente dos, pegada en una segunda conversación aparte:

```text
Incident report, 11 March. A database outage occurred on Tuesday. Alice was
on-call and responded within 5 minutes; the backup escalation was not
needed. Root cause: a migration script left a lock unreleased. Fix: the
migration now acquires the lock with a timeout.
```

El dato de referencia que una página del wiki tiene que llevar a través de ambas notas: Alice estaba de guardia durante la caída por la rotación fijada el 3 de marzo, y la regla de sustitución de esa misma rotación no se activó.

## Construye el agent { #build-the-agent }

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
2. En **Toolbox**, activa **Files & shell**. Elige **Container**, selecciona tu conexión de sandbox y el runtime `workbench`.
3. Pon el **alcance de sesión en `user`**, no en el valor por defecto `conversation`. Un workspace con alcance de conversación empieza vacío en el siguiente chat, que es justo el fallo de "el wiki lo olvida todo" que comprueba esta página; uno con alcance de agent lo comparten todos los de la organización que hablan con este agent, que es el modelo equivocado para el wiki de una persona. `user` mantiene un workspace para la persona en cada conversación y superficie por la que llega al agent, y para nadie más. Consulta [Files & shell](../reference/capabilities.md#files-shell) para ver qué comparte cada alcance.
4. Fija un budget y un límite de pasos para la prueba.
5. Escribe las instrucciones de abajo y luego pulsa **Publish**.

```text
You maintain a small personal LLM wiki in your workspace: raw sources
compiled into a cross-linked Markdown wiki, following this schema.

Layout:
raw/<slug>.md - one file per ingested source, saved verbatim, append-only.
Never edit a raw file once written.
wiki/index.md - one line per wiki page, each a Markdown link to it.
wiki/<topic>.md - one page per topic, written in your own words from the raw
sources. Link related pages with a relative Markdown link.
schema.md - this layout, written once on your first turn if it does not
exist, so any later session can check itself against it.

When asked to ingest a source: read schema.md first, writing it if it is
missing; list wiki/ so you know what exists; save the source verbatim to
raw/<slug>.md; update an existing wiki page if the source is about it, or
create a new one only for a genuinely new topic; cross-link pages that refer
to each other; update wiki/index.md; report which files you touched.

When asked a question, read the relevant wiki page(s) - not the raw sources,
unless a page is missing something the question needs - and answer citing
the page you used by name.

When asked to lint the wiki: list every file, read wiki/index.md and every
page it links to, then report broken links, orphan pages nothing links to,
and any two pages that state different facts about the same thing. Do not
fix anything unless asked; only report.
```

El esquema va aquí en las instrucciones porque es corto. Un esquema que pase de uno o dos párrafos encaja mejor en un [archivo de contexto](../context.md) en modo `link`, leído una vez y compartido por cada agent que mantenga un wiki así, en lugar de pegarlo en las instrucciones de cada uno.

## Ejecútalo { #run-it }

En una primera conversación nueva:

```text
Ingest this source: [paste source one]
```

Empieza una **segunda conversación nueva** con el mismo agent (no una respuesta en la primera) y pídele que incorpore la segunda fuente y luego haz la pregunta:

```text
Ingest this source: [paste source two]
```

```text
Who was on-call during the outage, and what is the backup escalation rule?
```

En un tercer turno, o en una tercera conversación, pide la comprobación en torno a la que está construido el patrón:

```text
Lint the wiki.
```

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| `schema.md` después de la primera conversación | Existe y coincide con la estructura de las instrucciones |
| El workspace al empezar la segunda conversación | Ya contiene `schema.md`, `raw/` y `wiki/` de la primera; no se vuelve a crear nada |
| Páginas del wiki después de ambas fuentes | Mencionan a Alice, el orden de la rotación y la caída; los dos temas se enlazan entre sí en lugar de quedar como dos páginas sin conexión |
| Respuesta a la pregunta | Nombra a Alice, cita las páginas del wiki e indica que la regla de sustitución no se activó |
| Informe de lint | Nombra con verdad cualquier enlace roto o página huérfana, incluido "none found", en lugar de un genérico "looks good" |
| Una tercera conversación con una pregunta, sin incorporar nada nuevo | Lee el wiki existente y responde igualmente, porque el workspace es de la persona, no de la conversación |

Lee los archivos reales en el panel de archivos de la conversación, no solo la respuesta. Un modelo que describe haber actualizado un enlace y uno que de verdad lo escribió parecen iguales en prosa.

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter, runtime `workbench`, `session_scope: user`. La primera conversación no encontró `schema.md` ni `wiki/`, escribió ambos según la estructura de las instrucciones, guardó la nota de guardias en `raw/meeting-notes-2024-03-03.md` y creó `wiki/on-call-rotation.md` y `wiki/index.md`. No hubo ninguna llamada a `execute`, así que no hizo falta aprobar nada. Coste: 0,1022 USD.

    Una segunda conversación aparte con el mismo agent empezó leyendo `schema.md` y listando `wiki/`, y encontró ambos ya allí: el workspace se había conservado. Guardó el informe del incidente en `raw/incident-report-11-march.md`, creó `wiki/database-incidents.md` con Alice, la respuesta en 5 minutos y la causa raíz, luego usó `edit_file` en `wiki/on-call-rotation.md` para añadir una sección "Incidents" enlazando la página nueva, y actualizó `wiki/index.md` para que listara ambas páginas: un enlace auténtico en los dos sentidos, no dos páginas una al lado de la otra. Coste: 0,1250 USD.

    Una caída de infraestructura ajena al agent y a la sandbox detuvo la prueba aquí. La pregunta ("Who was on-call during the outage...") y el paso de lint no se ejecutaron, así que las filas correspondientes de la tabla de arriba son la referencia esperada, no un resultado observado. Lo confirmado es la parte que esta página existe para comprobar: el workspace sobrevivió a una conversación totalmente aparte y los dos temas se enlazaron entre sí en lugar de duplicar contenido.

## Cuando algo sale mal { #when-it-goes-wrong }

- **La segunda conversación empieza con un workspace vacío.** El alcance es `conversation`, o `agent` se vincula a una conexión por defecto distinta de la del primer run, o la conexión o el backend cambiaron entre ambas; cualquiera de esos casos inicia un workspace nuevo en lugar de volver a conectar el anterior.
- **Dos páginas se repiten en lugar de enlazarse.** El modelo no leyó `wiki/index.md` antes de escribir. Endurece las instrucciones para exigir listar el wiki primero, cada vez.
- **El informe de lint siempre dice que todo está bien.** Pídele que revise un wiki que sabes que tiene un problema (renombra antes un archivo enlazado) para comprobar que el informe lee los archivos en lugar de suponer.
- **`schema.md` se reescribe en cada conversación.** Las instrucciones dicen que lo escriba solo si falta; si el modelo lo sigue reescribiendo, dile explícitamente que lea antes de escribir nada.
- **Un compañero puede ver notas que creías privadas.** Revisa el alcance de sesión. `agent` comparte un workspace con todos los que hablan con este agent, y por eso mismo el Builder avisa en ese campo.

## Registra la prueba { #record-the-trial }

Guarda las dos fuentes en bruto, los prompts exactos, la versión del agent y la lista de archivos del workspace después de cada conversación, no solo las respuestas. Una persona sigue juzgando si un enlace es realmente útil o solo existe, y si el informe de lint detectó algo real.

## ¿Wiki o búsqueda en el conocimiento? { #wiki-or-knowledge-search }

Responden a necesidades distintas. [La búsqueda en el conocimiento](../reference/capabilities.md#knowledge-search) recupera fragmentos de documentos que nadie reescribe (un contrato firmado, un PDF de políticas) y cita el fragmento de origen. Este patrón es para material que empieza desordenado y pequeño y merece el tiempo de un agent para *compilarlo*: notas, transcripciones, borradores a medio terminar que ganan al convertirse en unas pocas páginas mantenidas en lugar de un montón creciente de archivos de origen. Cuando el propio wiki compilado se hace demasiado grande para inyectarlo o leerlo entero, el siguiente paso natural es buscar en él como en cualquier otra colección, en lugar de mantenerlo como un archivo del workspace.

## Siguientes pasos { #next-steps }

Prueba a incorporar a propósito una fuente que contradiga a otra anterior, y comprueba que el paso de lint nombra ambas páginas en lugar de elegir un lado en silencio. Para un wiki que varias personas deban poder leer y ampliar, compara el alcance de sesión `agent` con dar a cada colaborador su propio agent vinculado a un [archivo de contexto](../context.md) compartido.
