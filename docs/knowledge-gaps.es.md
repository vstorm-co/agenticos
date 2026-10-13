---
source_sha: "2d253005d633"
title: "Lagunas de conocimiento"
description: "Las lagunas de conocimiento muestran las preguntas para las que un agent no encontró nada relevante en su base de conocimiento, agrupadas por tema, para saber qué documento falta."
---

# Lagunas de conocimiento { #knowledge-gaps }

Muchas respuestas malas no son un problema de las instrucciones del agent. La
base de conocimiento no contiene la respuesta, y ningún cambio en el prompt lo
arregla. Las **lagunas de conocimiento** muestran esas preguntas: aquellas para
las que un agent buscó en su [base de conocimiento](file-processing.md) y no
encontró nada relevante, agrupadas por tema, con cuántas veces se hizo cada una
y qué agents la hicieron.

Una laguna dice qué falta. Nunca añade nada a una colección por sí misma. Una
persona escribe o encuentra el documento que falta y lo añade, y antes puede
convertir las preguntas del tema en casos de un [dataset](datasets.md), para
que un eval muestre si el nuevo documento cambió las respuestas.

## Cómo una pregunta se convierte en laguna { #how-a-question-becomes-a-gap }

Cada vez que un agent busca en su base de conocimiento durante un run, la
plataforma registra la búsqueda: la consulta que envió el agent, las colecciones
en las que buscó, cuántos fragmentos devolvió y cuánto se parecía el fragmento
más cercano a la consulta. Una búsqueda es un **fallo** cuando no devolvió nada,
o cuando su fragmento más cercano se parece a la consulta menos que
`KNOWLEDGE_GAP_MIN_SIMILARITY`.

| Ajuste | Por defecto | Qué decide |
|---|---|---|
| `KNOWLEDGE_GAP_MIN_SIMILARITY` | `0.30` | La similitud coseno por debajo de la cual el fragmento más cercano cuenta como «nada relevante». Lo que puntúa una buena coincidencia depende del modelo de embeddings, así que revisa algunas de tus propias búsquedas antes de cambiarlo |

La similitud es la similitud coseno del vector del fragmento con el vector de la
consulta. No es la puntuación de ranking: con búsqueda híbrida o expansión de
consultas, la puntuación de ranking es un rango fusionado y no dice nada sobre
lo cerca que estaba un fragmento.

Se guarda cada búsqueda, no solo los fallos. Cuando cambias el umbral, se aplica
también a las búsquedas ya hechas: las lagunas que lees son siempre las
búsquedas por debajo del ajuste actual.

Solo se registran las búsquedas que un agent hace mientras ejecuta un run. Una
búsqueda a través de `/rag/search` de la HTTP API, o una vista previa en la
página de la colección, no se registra.

## Temas { #topics }

Los fallos se agrupan en **temas** según el significado de la consulta. Cada 15
minutos, un proceso en segundo plano toma los fallos nuevos de cada base de
conocimiento, los convierte en embeddings con el modelo propio de esa colección
y coloca cada uno en el tema más cercano de esa base de conocimiento, o abre uno
nuevo. Una pasada procesa como mucho 500 fallos por base de conocimiento; el
resto espera a la siguiente. Una base de conocimiento sin fallos nuevos no
cuesta ninguna llamada de embeddings.

- Una búsqueda en dos colecciones se convierte en una pregunta en un tema de
  cada una.
- Una colección que pasa a otro modelo de embeddings empieza temas nuevos,
  porque los vectores de dos modelos no se pueden comparar.
- Un tema conserva su identidad cuando se le añaden preguntas, así que una
  decisión que tomaste sobre él sigue valiendo.

**Agrupar ahora**, en la pestaña de lagunas de conocimiento de la colección,
ejecuta la pasada de esa base de conocimiento de inmediato, en lugar de esperar
al calendario. Hasta que una pregunta se coloca en un tema, la pestaña la cuenta
como aún sin agrupar.

## Leer las lagunas { #reading-gaps }

Las lagunas aparecen en tres lugares:

- la pestaña **Lagunas de conocimiento** de una colección: todos los temas de
  esa base de conocimiento;
- la pestaña **Lagunas de conocimiento** de un agent: solo las preguntas que
  hizo ese agent, en las bases de conocimiento que puedes leer;
- el widget **Lagunas de conocimiento** del panel: los temas más preguntados de
  toda la organización.

Un tema muestra cuántas veces se preguntó, cuándo fue la última vez, qué agents
lo preguntaron y hasta tres de sus preguntas. Ábrelo para ver las preguntas más
recientes: qué preguntó la persona, qué buscó el agent, lo cerca que estaba el
fragmento más cercano y el comentario de quien valoró negativamente la
respuesta.

## Qué hacer con una laguna { #acting-on-a-gap }

| Acción | Qué hace |
|---|---|
| Añadir el documento que falta | Súbelo a la colección, o a una fuente que la colección sincroniza. No se añade nada por ti |
| **Añadir al dataset** | Convierte las preguntas más recientes del tema (hasta 200) en casos del dataset que elijas, como una versión nueva. Cada caso es la pregunta de la persona, con la respuesta del agent como contraejemplo. Una pregunta hecha a través de la HTTP API no guarda respuesta y se omite |
| **Descartar** | Marca un tema como uno que no necesita contenido. Un tema descartado conserva las preguntas que le pertenecen, así que no vuelve como tema nuevo. **Reabrir** lo deshace |

Después de añadir el documento, ejecuta un eval sobre el dataset. Los casos que
fallaban porque faltaba el conocimiento deberían pasar ahora.

## Acceso { #access }

Un tema está hecho de preguntas de personas, así que leer las lagunas requiere
`runs:view`, el permiso que lee cada run de la organización en Activity. Un
miembro sin él no ve la pestaña ni el widget, y la API se lo deniega.

| Para | Necesitas |
|---|---|
| Leer las lagunas de una colección | `runs:view` y `collections:view` en esa colección |
| Leer las lagunas de un agent | `runs:view` y `agents:view` en el agent; se omiten los temas de colecciones que no puedes leer |
| Descartar, reabrir o reagrupar | `runs:view` y `collections:edit` en la colección |
| Añadir un tema a un dataset | `runs:view` y `datasets:edit` en el dataset |

Una colección, un agent, un tema o un dataset al que no tienes acceso responde
«no encontrado», igual que uno de otra organización. Consulta
[Permisos](permissions.md).

## Datos personales { #personal-data }

Una búsqueda registrada es contenido de usuario: el agent la formuló a partir de
lo que alguien preguntó. Se borra con el run en el que se hizo y con la
conversación de la que procede. Borrar a una persona borra las búsquedas hechas
al responderle, también las de runs sin conversación. Su exportación las
incluye.

Un tema no copia texto. Su nombre, sus ejemplos y su recuento se leen de las
búsquedas que aún contiene, así que cuando esas búsquedas se borran al tema no
le queda nada y la siguiente pasada de agrupación lo elimina. Consulta
[Protección de datos](data-protection.md#where-personal-data-lives).

## Lo que las lagunas aún no detectan { #limits }

Las lagunas provienen solo de la búsqueda. Una respuesta en la que el agent dijo
que no lo sabía, o una respuesta valorada negativamente con un comentario sobre
información que falta, no se detecta por sí sola. Detectarlas requiere un modelo
y se sigue en [#2135](https://github.com/vstorm-co/agenticos/issues/2135).
Cuando una respuesta valorada negativamente pertenece a un run cuya búsqueda fue
un fallo, su comentario se muestra junto a la pregunta.
