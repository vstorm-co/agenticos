---
source_sha: "daee0cd1b399"
title: "Responde preguntas en una biblioteca de documentos con citas"
description: "Pon cuatro pequeños documentos de políticas sintéticos en una colección y comprueba que el agent encuentra el correcto, combina dos de ellos y admite lo que ninguno cubre."
---

# Responde preguntas en una biblioteca de documentos con citas { #answer-questions-across-a-document-library-with-citations }

Construye un agent que responde a partir de una pequeña biblioteca de políticas de RR. HH. en lugar de un solo archivo. El ejemplo tiene cuatro documentos cortos en una colección: una pregunta se responde con un solo documento, otra necesita combinar dos y otra no está cubierta en absoluto. Comprobar una respuesta basada en varios documentos significa leer los dos fragmentos de origen, no solo la respuesta. Es un procedimiento para ejecutar, con un run registrado como referencia.

Para un solo documento sin colección que gestionar, empieza mejor por [tu primer agent con documentos](first-document-agent.md). Esta página es el paso siguiente: varios documentos y una respuesta que tiene que citar el correcto.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo.
- Un proveedor de embeddings y una clave para él en el vault: el run registrado usó `text-embedding-3-small` de OpenRouter. [Configura una base de conocimiento](set-up-knowledge-base.md) cubre el diálogo de creación completo.
- Sin sandbox y sin ninguna otra capability.

## Prepara la entrada { #prepare-the-input }

Cuatro archivos Markdown cortos, subidos por separado. El ejemplo es inventado, y dos políticas comparten a propósito una cifra para que una pregunta necesite ambas.

`expense-policy.md`:

```text
Employees may claim reimbursement for client meals up to 40 EUR per person.
Travel booked more than 14 days in advance must use economy class for flights
under 6 hours. Mileage for a personal car used on company business is
reimbursed at 0.35 EUR per kilometre. Receipts are required for any claim over
15 EUR. Claims must be submitted within 30 days of the expense.
```

`remote-work-policy.md`:

```text
Employees may work remotely up to 3 days per week without prior approval.
A fully remote arrangement needs sign-off from the department head and HR.
Remote employees must be reachable during core hours, 10:00 to 16:00 in their
local time zone. Equipment for a home office is reimbursed once per employee,
up to 400 EUR, on the same 15 EUR receipt threshold as the expense policy.
```

`onboarding-checklist.md`:

```text
A new employee's manager requests a laptop and accounts in the first week.
IT provisions access within 2 business days of the request. The employee
completes the compliance training module within 30 days of their start date.
The 400 EUR home-office equipment allowance from the remote work policy is
requested through the same IT ticket as the laptop.
```

`travel-booking-guide.md`:

```text
Book flights and hotels through the corporate travel portal. Economy class is
the default for flights under 6 hours, matching the expense policy's advance-
booking rule. Hotel stays are capped at 180 EUR per night in tier-1 cities and
120 EUR elsewhere. A trip that combines client meetings and a conference needs
the sponsoring manager's approval before booking.
```

Los datos de referencia: una comida con un cliente tiene un límite de 40 EUR (solo la política de gastos). La asignación para la oficina en casa es de 400 EUR y se pide mediante el mismo ticket de TI que el portátil: una cifra de la política de teletrabajo y un paso de la lista de incorporación. Nada de esto indica un plazo de preaviso por dimisión.

## Construye el agent { #build-the-agent }

1. En **Knowledge → New**, pon nombre a la colección, despliega **Embeddings** y elige el proveedor y el modelo que atiende tu clave; el run registrado usó OpenRouter y `text-embedding-3-small`. Esta elección queda fija en cuanto existe la colección.
2. Crea la colección y sube los cuatro archivos. Espera a que cada uno llegue a `done` antes de seguir.
3. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
4. En **Toolbox**, activa **Knowledge search** y vincula la colección que acabas de llenar. Deja `default_top_k` en su valor por defecto; cuatro documentos cortos no necesitan más.
5. Escribe las instrucciones de abajo y luego pulsa **Publish**.

```text
Answer questions from the bound HR policy collection.
Cite the document you used for each fact.
If the answer draws on more than one document, name each one.
If the collection does not cover the question, say so rather than guessing.
```

!!! info "Dos ajustes que conviene conocer antes de ampliar esto"

    `self_query_enabled` (desactivado por defecto) hace que el modelo infiera filtros como una fuente, un tipo de documento o un intervalo de fechas a partir de una pregunta como "políticas actualizadas el último trimestre": útil cuando los documentos llevan esos metadatos, e innecesario para cuatro archivos sin ninguno. `parent_context` (desactivado por defecto) devuelve el texto que rodea a un fragmento coincidente en lugar del fragmento solo, lo que ayuda cuando una respuesta queda en el borde de uno. Ninguno de los dos pasa por encima de los filtros explícitos del propio modelo, y ninguno amplía las colecciones ni la organización a las que puede llegar un agent. Consulta [la referencia de la capability](../reference/capabilities.md#knowledge-search).

## Ejecútalo { #run-it }

Haz cada pregunta en una conversación nueva, para que una respuesta anterior no se filtre en la siguiente.

```text
How much can I claim for a client meal?
```

```text
I am fully remote. How much is the home-office equipment allowance, and how do I request it?
```

```text
What is the notice period if I want to resign?
```

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| Respuesta sobre la comida con cliente | 40 EUR, citando `expense-policy.md` |
| Respuesta sobre la oficina en casa | 400 EUR, citando `remote-work-policy.md`, con el paso de solicitud citado a `onboarding-checklist.md` |
| Pregunta sobre la dimisión | Indica que la colección no lo cubre y no se inventa una cifra |
| Fragmentos recuperados en Activity | La mejor coincidencia del run de la comida es `expense-policy.md`; las del run de la oficina en casa incluyen ambos documentos de origen |
| Una pregunta sobre las reservas de viaje de la semana pasada | Se responde a partir de `travel-booking-guide.md`, sin mezclarla con los otros tres |

Lee los fragmentos recuperados en Activity, no solo la respuesta. Una cita que nombra el archivo correcto con la cifra equivocada, o la cifra correcta de un archivo equivocado, parecen correctas en el chat.

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter, `default_top_k` en 5. La pregunta sobre la comida con cliente llamó una vez a `search_documents` y respondió "up to €40 per person", citando `expense-policy.md`, por 0,0133 USD. La pregunta sobre la oficina en casa recuperó tres documentos y respondió "up to €400", citando `remote-work-policy.md` para la cifra y `onboarding-checklist.md` para "the same IT ticket used to request your laptop", por 0,0181 USD. La pregunta sobre la dimisión recuperó los tres documentos menos relevantes, no encontró nada en ellos y respondió "does not appear to contain a document covering resignation notice periods", por 0,0135 USD.

    El primer intento con este agent no vinculó ninguna colección en la spec (un error en la preparación de la prueba, no del producto) y el modelo respondió a partir de su propio entrenamiento en lugar de admitir que no tenía nada vinculado. Nunca se llamó a `search_documents`. Vincular la colección y volver a publicar lo arregló; la diferencia entre "no hubo llamada a la herramienta" y "la herramienta se ejecutó y no encontró nada" es lo primero que hay que comprobar cuando una respuesta suena segura pero falta la fuente.

## Cuando algo sale mal { #when-it-goes-wrong }

- **El agent responde con soltura y sin cita.** Comprueba en Activity si se llegó a llamar a `search_documents`. Una capability de conocimiento sin colección vinculada no aporta nada, en silencio, en lugar de ofrecer una herramienta que siempre falla.
- **Falta un documento en una respuesta que debería usarlo.** Comprueba el estado del documento en la colección. Un documento en `processing` o fallido es invisible para la búsqueda, por muy claro que lo lea una persona.
- **La pregunta sobre la dimisión recibe una respuesta segura pero errónea.** La última línea de las instrucciones, "say so rather than guessing", es lo que convierte el silencio en una negativa. Pruébalo a propósito, como hace aquí la tercera pregunta.
- **Dos documentos que deberían combinarse solo responden desde uno.** Sube `default_top_k`, o comprueba si la formulación de la pregunta favorece el vocabulario de un documento frente al del otro.
- **Una carpeta sincronizada debería alimentar esta colección en lugar de subidas manuales.** Consulta [configura fuentes de sincronización](configure-sync-sources.md): la misma colección puede mezclar subidas y una sincronización programada.

## Registra la prueba { #record-the-trial }

Guarda los cuatro archivos, las preguntas, la versión del agent, los perfiles de modelo y de embeddings y los fragmentos recuperados en Activity de cada run, no solo las respuestas. Una persona sigue juzgando si una cita respalda de verdad lo que dijo el agent, y si "no cubierto" fue la decisión correcta y no una salida fácil.

## Siguientes pasos { #next-steps }

Cuando la recuperación funcione entre documentos, pon el agent delante de la gente: [Slack](slack-handbook-assistant.md) es el mismo patrón con un canal delante. Para un corpus demasiado grande para subirlo a mano, usa [configura fuentes de sincronización](configure-sync-sources.md).
