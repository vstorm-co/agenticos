---
source_sha: "e3d2d8bbc68f"
title: "Lagunas de conocimiento"
description: "Las lagunas de conocimiento muestran las preguntas para las que un agent no encontró nada relevante en su base de conocimiento, o respondió sin saber, agrupadas por tema, para saber qué documento falta."
---

# Lagunas de conocimiento { #knowledge-gaps }

Muchas respuestas malas no son un problema de las instrucciones del agent. La
base de conocimiento no contiene la respuesta, y ningún cambio en el prompt lo
arregla. Las **lagunas de conocimiento** muestran esas preguntas: aquellas para
las que un agent buscó en su [base de conocimiento](file-processing.md) y no
encontró nada relevante, o respondió sin saber, agrupadas por tema, con cuántas veces se hizo cada una
y qué agents la hicieron.

Una laguna dice qué falta. Nunca añade nada a una base de conocimiento por sí misma. Una
persona escribe o encuentra el documento que falta - un modelo puede redactar
un borrador - y lo añade, y antes puede
convertir las preguntas del tema en casos de un [dataset](datasets.md), para
que un eval muestre si el nuevo documento cambió las respuestas.

## Cómo una pregunta se convierte en laguna { #how-a-question-becomes-a-gap }

Cada vez que un agent busca en su base de conocimiento durante un run, la
plataforma registra la búsqueda: la consulta que envió el agent, las bases de conocimiento
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

Solo se registran las búsquedas que un agent hace mientras ejecuta un run, y
solo para preguntas que hicieron personas: una búsqueda a través de
`/rag/search` de la HTTP API, una vista previa en la página de la base de conocimiento y
una búsqueda de un run de eval y una de la prueba de un borrador en el builder no
se registran. Se guardan los primeros 1.000
caracteres de una consulta.

## Respuestas y comentarios { #answers-and-comments }

Una búsqueda puede encontrar un fragmento y el agent aun así no saber la
respuesta, y un lector puede valorar negativamente una respuesta porque faltaba
algo. La búsqueda sola no ve ninguna de las dos cosas. **Revisar N respuestas**,
en la pestaña Lagunas de conocimiento de la base de conocimiento, pide a un
modelo que lea sus respuestas recientes en busca de ellas. Se ofrece mientras la
[asistencia de IA](governance.md#ai-assistance) está activada, y cuenta las
respuestas aún sin leer. Mientras el interruptor está apagado, la pestaña dice
cuántas respuestas esperan, con un enlace al interruptor para quien puede
cambiarlo.

El modelo es el **Knowledge gap classifier**, un
[agent del sistema](concepts.md#system-agents) que tiene cada organización. Lee
cada respuesta con su pregunta y los comentarios de quien la valoró
negativamente, y decide una de tres cosas:

| Veredicto | Cuándo |
|---|---|
| El agent no lo sabía | La respuesta dice, con cualquier palabra o idioma, que el agent no lo sabía o no encontró la información |
| Faltaba información | Un comentario de una valoración negativa dice que faltaba información, estaba desactualizada o incompleta |
| Sin laguna | Todo lo demás: una respuesta correcta, el rechazo de una pregunta para la que el agent no está, un comentario sobre el tono, la longitud o un error |

Una respuesta con cualquiera de los dos primeros veredictos se convierte en una
pregunta en los temas de la base de conocimiento, agrupada como una búsqueda
fallida. En el tema dice cuál de los dos es, en lugar de nombrar una búsqueda.

Una respuesta se lee cuando su run, de los últimos 30 días, terminó y buscó en
la base de conocimiento y encontró algo, o fue valorado negativamente con un
comentario y funciona con una versión del agent vinculada a la base de
conocimiento. Un run cuya búsqueda ya falló cuenta una vez, como ese fallo. Los
runs por la API HTTP no guardan respuesta, y los runs de eval, cuyas preguntas se
reproducen o se generan, nunca se leen. Tampoco las pruebas de un borrador en el
builder, los runs delegados ni los runs cuyo autor ya no tiene cuenta.

Una revisión pertenece a una base de conocimiento: lo que encuentra es una
laguna solo de esa base. Una respuesta cuyo run buscó en dos bases de
conocimiento se vuelve a leer cuando se revisa la otra.

Una revisión lee hasta 100 respuestas, 20 por run del clasificador. Cada run se
comprueba contra el presupuesto del clasificador y el de la organización antes
de llamar al modelo, y aparece en Actividad bajo la persona que lo pidió: elige
**Todas las superficies, evals incluidas** para verlo.

Cada respuesta leída se recuerda, sea cual sea el veredicto, así que ninguna se paga dos veces. Una leída
como sin laguna se vuelve a leer solo tras una nueva valoración negativa con
comentario. Una revisión se detiene en un run que termina sin respuesta, como
uno que deniega un presupuesto agotado, y conserva lo que leyó. Cada base de
conocimiento tiene una sola revisión a la vez.

## Temas { #topics }

Los fallos se agrupan en **temas** según el significado de la consulta. Cada 15
minutos, un proceso en segundo plano toma los fallos nuevos de cada base de
conocimiento, los convierte en embeddings con el modelo propio de esa base de conocimiento
y coloca cada uno en el tema más cercano de esa base de conocimiento, o abre uno
nuevo. Una pasada procesa como mucho 500 fallos por base de conocimiento; el
resto espera a la siguiente. Una base de conocimiento sin fallos nuevos no
cuesta ninguna llamada de embeddings.

- Una búsqueda en dos bases de conocimiento se convierte en una pregunta en un tema de
  cada una.
- Una base de conocimiento que pasa a otro modelo de embeddings empieza temas nuevos,
  porque los vectores de dos modelos no se pueden comparar.
- Un tema conserva su identidad cuando se le añaden preguntas, así que una
  decisión que tomaste sobre él sigue valiendo.

**Agrupar ahora**, en la pestaña de lagunas de conocimiento de la base de conocimiento,
ejecuta la pasada de esa base de conocimiento de inmediato, en lugar de esperar
al calendario. Hasta que una pregunta se coloca en un tema, la pestaña la cuenta
como aún sin agrupar.

## Leer las lagunas { #reading-gaps }

Las lagunas aparecen en tres lugares:

- la pestaña **Lagunas de conocimiento** de una base de conocimiento: todos
  sus temas;
- la pestaña **Lagunas de conocimiento** de un agent: solo las preguntas que
  hizo ese agent, en las bases de conocimiento que puedes leer;
- el widget **Lagunas de conocimiento**, que se añade desde **Customize**: los
  temas más preguntados de toda la organización y cuántos temas tiene cada base
  de conocimiento.

Un tema pertenece a su base de conocimiento, así que quién lo lee depende de
quién lee esa base de conocimiento. No hay un filtro aparte por departamento:
un departamento ve las lagunas de las bases de conocimiento compartidas con
él.

Un tema muestra cuántas veces se preguntó, cuándo fue la última vez, qué agents
lo preguntaron y hasta tres de sus preguntas. Ábrelo para ver las preguntas más
recientes: qué preguntó la persona, qué buscó el agent, lo cerca que estaba el
fragmento más cercano y el comentario de quien valoró negativamente la
respuesta. Una pregunta leída de una respuesta dice si el agent no lo sabía o si
un lector escribió que faltaba información.

## Qué hacer con una laguna { #acting-on-a-gap }

**Añadir al dataset** y **Descartar** están en el menú **…** de un tema, en su
fila y en el propio tema.

| Acción | Qué hace |
|---|---|
| Añadir el documento que falta | Súbelo a la base de conocimiento, o a una fuente que la base de conocimiento sincroniza. No se añade nada por ti |
| **Añadir al dataset** | Convierte las preguntas más recientes del tema (hasta 200) en casos de un dataset que puedes cambiar, como una versión nueva. Cada caso es la pregunta de la persona, con la respuesta del agent como contraejemplo. Una pregunta hecha a través de la HTTP API no guarda respuesta y se omite |
| **Descartar** | Marca un tema como uno que no necesita contenido. Un tema descartado conserva las preguntas que le pertenecen, así que no vuelve como tema nuevo. **Reabrir** lo deshace |

Después de añadir el documento, ejecuta un eval sobre el dataset. Los casos que
fallaban porque faltaba el conocimiento deberían pasar ahora.

## Redactar el contenido que falta { #drafting-the-missing-content }

**Redactar el contenido que falta**, en un tema abierto, pide a un modelo que
escriba el fragmento o la entrada de FAQ que le falta a la base de conocimiento.
Es un run del **Knowledge gap drafter**, un
[agent del sistema](concepts.md#system-agents) que tiene cada organización. Ve
las 20 preguntas más recientes del tema: qué preguntó cada persona, qué buscó y
encontró el agent, qué respuesta recibió la persona y cualquier comentario
dejado con una valoración negativa.

El borrador se guarda en el tema, marcado como borrador, con un enlace a su
run. Puedes copiarlo o descargarlo como Markdown. Nunca se añade a la
base de conocimiento. El redactor no conoce los datos de tu
empresa: donde una respuesta necesita una cifra, una fecha o una regla, escribe
entre corchetes un marcador para que lo completes. Redactar de nuevo sustituye
el borrador. Quien puede editar el drafter encuentra **Edit the drafter's
instructions** en el borrador, y el propio drafter en **System agents**, en la
página Agents.

Un borrador nombra sus fuentes: los documentos de la base de conocimiento en
los que se apoya y las preguntas del tema que responde. Cada una se verifica
antes de guardar el borrador - un documento debe pertenecer a la base de
conocimiento del tema, una pregunta debe ser del tema - y la que no pasa se
omite, nunca se muestra, y se cuenta en el borrador. Se guardan como mucho 12
fuentes. Una fuente borrada después deja de mostrarse.

Un borrador es un run de modelo como cualquier otro. Se deniega mientras la
organización tiene la [asistencia de IA](governance.md#ai-assistance)
desactivada, y lo está hasta que alguien con `org:settings` la activa; hasta
entonces el tema lo dice, con un enlace al interruptor para quien puede
cambiarlo. Se comprueban el presupuesto del redactor y el de la organización
antes de llamar al modelo, y su coste aparece en Activity. Agrupar preguntas en
temas no pide a ningún modelo que escriba nada, así que funciona sea cual sea
el interruptor.

## Acceso { #access }

Un tema está hecho de preguntas de personas, así que leer las lagunas requiere
`runs:view`, el permiso que lee cada run de la organización en Activity. Un
miembro sin él no ve la pestaña ni el widget, y la API se lo deniega.

| Para | Necesitas |
|---|---|
| Leer las lagunas de una base de conocimiento | `runs:view` y `collections:view` en esa base de conocimiento |
| Leer las lagunas de un agent | `runs:view` y `agents:view` en el agent; se omiten los temas de bases de conocimiento que no puedes leer |
| Descartar, reabrir o reagrupar | `runs:view` y `collections:edit` en la base de conocimiento, por tu rol o por un grant de edición sobre ella |
| Añadir un tema a un dataset | `runs:view` y `datasets:edit` en el dataset |
| Redactar el contenido que falta | `runs:view`, `collections:edit` en la base de conocimiento y `agents:run` en el Knowledge gap drafter |
| Revisar respuestas | `runs:view`, `collections:edit` en la base de conocimiento y `agents:run` en el Knowledge gap classifier |

Una revisión de respuestas se ejecuta después con tu rol, así que solo se inicia
en persona: no a través de una clave de API ni mientras un administrador te
suplanta.

Una base de conocimiento, un agent, un tema o un dataset al que no tienes acceso responde
«no encontrado», igual que uno de otra organización. Consulta
[Permisos](permissions.md).

## Datos personales { #personal-data }

Una búsqueda registrada es contenido de usuario: el agent la formuló a partir de
lo que alguien preguntó. Se borra con el run en el que se hizo y con la
conversación de la que procede. Borrar a una persona borra las búsquedas hechas
al responderle, también las de runs sin conversación. Su exportación las
incluye.

Se guarda cada búsqueda, acierto o fallo, para que un umbral cambiado se aplique
también a las búsquedas ya hechas. Ninguna sobrevive a su run: la clase de runs
de la [retención](governance.md#retention) las borra con él.

Un tema no copia preguntas. Su nombre, sus ejemplos y su recuento se leen de
las búsquedas que aún contiene, así que cuando esas búsquedas se borran al tema
no le queda nada y la siguiente pasada de agrupación lo elimina junto con su
borrador. El borrador es el único texto que guarda un tema: lo escribe un
modelo a partir de las preguntas, así que puede repetir algo que alguien
escribió. Las credenciales que repita se ocultan antes de guardarlo. Redactar
envía las preguntas, respuestas y comentarios al proveedor del modelo del
redactor. Consulta
[Protección de datos](data-protection.md#where-personal-data-lives).

Una pregunta leída de una respuesta se guarda igual que una búsqueda: contiene
la pregunta de la persona y se va con su run y su conversación. Revisar
respuestas envía preguntas, respuestas y comentarios de valoraciones negativas
al proveedor del modelo del clasificador. De cada respuesta leída solo se
recuerda su veredicto y el run del clasificador, sin texto.

## Lo que las lagunas aún no detectan { #limits }

Las respuestas solo se leen cuando alguien las revisa, y solo de los últimos 30
días. Los runs por la API HTTP no guardan respuesta, así que una pregunta hecha
allí se convierte en laguna solo cuando su búsqueda falló. Una respuesta
valorada negativamente sin comentario se lee por lo que dijo el agent, no por la
valoración.
