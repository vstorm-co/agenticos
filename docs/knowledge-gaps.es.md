---
source_sha: "2af2a153e11d"
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
persona escribe el contenido que falta en el tema - un modelo puede redactar
un borrador - y lo añade a la base de conocimiento como documento, y antes puede
convertir las preguntas del tema en casos de un [dataset](datasets.md), para
que un eval muestre si el nuevo documento cambió las respuestas.

Los editores eligen **Ayudantes de IA** en la pestaña de lagunas: un
clasificador y redactor publicados propios o los predeterminados de la organización.
Los campos son `gap_classifier_agent_id` y `gap_drafter_agent_id`; null restaura
el valor predeterminado y omitir el campo mantiene la selección. Las llamadas
de pago vuelven a comprobar acceso y tipo; una selección eliminada se rechaza
explícitamente. Las bases compartidas por todo el despliegue usan los valores
de cada organización, porque una configuración global no puede referirse al
ayudante privado de una sola organización.

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
cada respuesta con su pregunta, los comentarios de quien la valoró
negativamente y las instrucciones y los [archivos de contexto](context.md) de la
versión del agent que la dio - los que puede leer la persona que pidió la
revisión -, y decide una de cuatro cosas, con una frase sobre el porqué:

| Veredicto | Cuándo |
|---|---|
| El agent no lo sabía | La respuesta dice, con cualquier palabra o idioma, que el agent no lo sabía o no encontró la información. Una pregunta legítima que el agent rechazó porque no tenía nada sobre ella entra aquí, no entre los rechazos |
| Faltaba información | Un comentario de una valoración negativa dice que faltaba información, estaba desactualizada o incompleta |
| Rechazo justificado | La pregunta pedía lo que las reglas o el propósito del agent no permiten - ignorar sus instrucciones, conceder una excepción o ayudar con algo para lo que no está - y el agent se negó. No es una laguna, y las búsquedas fallidas del run también dejan de contar como lagunas - en esa base de conocimiento y en otra que una búsqueda fallida también cubría, porque un rechazo trata de la petición, no de una base de conocimiento |
| Sin laguna | Todo lo demás: una respuesta correcta, el rechazo de algo que las reglas permiten, un comentario sobre el tono, la longitud o un error. Una respuesta que aplicó mal una política o una regla no es una laguna: la regla estaba, y es un error que corregir - y también lo es una cuyo agent tiene en sus instrucciones o archivos de contexto lo que necesitaba. Un comentario de que la información estaba desactualizada sí es una laguna |

Una respuesta con cualquiera de los dos primeros veredictos se convierte en una
pregunta en los temas de la base de conocimiento, agrupada como una búsqueda
fallida. En el tema dice cuál de los dos es, en lugar de nombrar una búsqueda.

Una respuesta se lee cuando su run, de los últimos 30 días, terminó y buscó en
la base de conocimiento o funcionó con una versión del agent vinculada a ella,
valorado o no: una respuesta en la que el agent no lo sabía a menudo no la
valora nadie. Un run cuya búsqueda ya falló también se lee, para que un rechazo
justificado saque su fallo de las lagunas; si no, sigue contando una vez, como
ese fallo.

Los runs por la API HTTP no guardan respuesta, y los runs de eval, cuyas
preguntas se reproducen o se generan, nunca se leen. Tampoco las pruebas de un borrador en el
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
uno que deniega un presupuesto agotado, y conserva lo que leyó.

Cada base de conocimiento tiene una sola revisión a la vez, como un job en
segundo plano en Admin → Background jobs: un worker que se detiene durante ella
deja el job terminado ahí, nunca perdido sin rastro, y lo que la revisión leyó
queda leído.

Una sesión de mejora - [Mejorar](authoring.md) en segundo plano - lee igual las
malas respuestas que encontró, solo esas y sea cual sea su antigüedad, y
clasifica cada una según sus veredictos: falta conocimiento si a una base de
conocimiento le faltaba contenido, nada que corregir si el agent se negó con
razón, y fallo del agent en los demás casos.

Las que les falta conocimiento
salen de lo que lee el asistente de autoría, y la sesión redacta en su lugar sus
temas, tres como máximo por ronda, aunque haya preguntado poca gente: una persona
revisa cada borrador antes de añadirlo, y un borrador basado en la pregunta de una
sola persona lo indica. Fuera de una sesión, un borrador que nadie pidió sigue
esperando a que pregunten dos personas distintas. Los runs de un eval nunca se leen, así que tampoco ningún
caso reservado.

## Temas { #topics }

Los fallos se agrupan en **temas** según el significado de la consulta. Cada 15
minutos, un proceso en segundo plano toma los fallos nuevos de cada base de
conocimiento, los convierte en embeddings con el modelo propio de esa base de conocimiento
y coloca cada uno en el tema más cercano de esa base de conocimiento, o abre uno
nuevo. Una pasada procesa como mucho 500 fallos por base de conocimiento; el
resto espera a la siguiente. Una base de conocimiento sin fallos nuevos no
cuesta ninguna llamada de embeddings.

Un fallo entra en el tema más cercano solo si se le parece al menos tanto como
`KNOWLEDGE_GAP_TOPIC_SIMILARITY`; si no, abre uno nuevo.

| Ajuste | Por defecto | Qué decide |
|---|---|---|
| `KNOWLEDGE_GAP_TOPIC_SIMILARITY` | `0.55` | La similitud coseno que un fallo necesita con un tema para unirse a él. Lo que puntúan las preguntas sobre un mismo asunto depende del modelo de embeddings: entre 0,5 y 0,7 aproximadamente en los modelos `text-embedding-3` de OpenAI. Súbelo si preguntas sin relación comparten tema, bájalo si un mismo asunto sigue abriendo temas nuevos. El valor por defecto está ajustado a esos modelos; un modelo de embeddings servido tras un endpoint compatible con OpenAI, como bge o e5, puntúa alto incluso preguntas sin relación, así que súbelo ahí |

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

Un tema muestra cuántas veces se preguntó y cuántas personas lo preguntaron,
cuándo fue la última vez, qué agents lo preguntaron y hasta tres de sus
preguntas. Quienes preguntaron por un canal cuentan por su cuenta de chat;
todos los que preguntaron de forma anónima, a través de un widget o sin una
persona detrás del run, cuentan como una. Ábrelo para ver las preguntas más
recientes: qué preguntó la persona, qué buscó el agent, lo cerca que estaba el
fragmento más cercano y el comentario de quien valoró negativamente la
respuesta. Una pregunta leída de una respuesta dice si el agent no lo sabía o si
un lector escribió que faltaba información.

## Qué hacer con una laguna { #acting-on-a-gap }

Un tema abierto tiene un editor: un título y el contenido en Markdown, vacío o
con el borrador del tema. **Añadir al dataset** y **Descartar** están en el
menú **…** de un tema, en su fila y en el propio tema.

| Acción | Qué hace |
|---|---|
| **Añadir a** *base de conocimiento* | Añade el título y el contenido a la base de conocimiento del tema como documento Markdown, por el mismo camino que una subida, y marca el tema como **cubierto** por él. Se deniega mientras quede un dato por completar, o mientras algo pueda identificar a una persona y no lo hayas confirmado (consulta [Datos personales](#personal-data)) |
| **Guardar** | Guarda el título y el contenido en el tema sin añadirlos a ningún sitio |
| **Añadir al dataset** | Convierte las preguntas más recientes del tema (hasta 200) en casos de un dataset que puedes cambiar, como una versión nueva. Cada caso es la pregunta de la persona, con la respuesta del agent como contraejemplo. Una pregunta hecha a través de la HTTP API no guarda respuesta y se omite |
| **Descartar** | Marca un tema como uno que no necesita contenido. Un tema descartado conserva las preguntas que le pertenecen, así que no vuelve como tema nuevo. **Reabrir** lo deshace |

Un tema cubierto dice qué documento lo cubre, conserva las preguntas que le
pertenecen como uno descartado y aparece en **Cubiertos**. Si ese documento se
borra, o su ingesta falla, el tema vuelve a estar abierto; un tema descartado
se reabre antes de escribir contenido para él. **Reabrir** en un tema cubierto deja el
documento en la base de conocimiento. El documento registra el tema desde el
que se añadió y quién lo añadió, y cada adición queda en el registro de
auditoría como `knowledge_gap.content_added`.

También puedes subir un documento por tu cuenta, o añadirlo a una fuente que la
base de conocimiento sincroniza. Después de añadir el contenido, ejecuta un
eval sobre el dataset. Los casos que fallaban porque faltaba el conocimiento
deberían pasar ahora.

## Redactar el contenido que falta { #drafting-the-missing-content }

**Redactar el contenido que falta**, en un tema abierto, pide a un modelo que
escriba el fragmento o la entrada de FAQ que le falta a la base de conocimiento.
Es un run del **Knowledge gap drafter**, un
[agent del sistema](concepts.md#system-agents) que tiene cada organización. Ve
las 20 preguntas más recientes del tema: qué preguntó cada persona, qué buscó y
encontró el agent, qué respuesta recibió la persona y cualquier comentario
dejado con una valoración negativa. Antes se quita lo que identifica a las
personas (consulta [Datos personales](#personal-data)); de lo que encontró la
búsqueda, el propio texto de la base de conocimiento, solo los datos personales,
así que sus cifras se quedan. Lo que encontró es siempre el resultado de la
propia búsqueda en la base de conocimiento, nunca lo que otra herramienta
devolvió para las mismas palabras. También ve los
[archivos de contexto](context.md) que los agents del tema leen en sus
versiones publicadas, los que tú puedes leer, para que el borrador siga las
reglas que los agents ya siguen.

El borrador rellena el editor del tema, con un enlace a su run. Puedes copiarlo
como Markdown, y solo llega a la base de conocimiento cuando alguien lo añade. El redactor no conoce los datos de tu empresa: donde una
respuesta necesita una cifra, una fecha o una regla, escribe
`{{what to fill in}}`, y el editor enumera cada uno hasta que se sustituye.

Cuando un archivo de contexto o un documento ya responde a las preguntas, el
redactor lo dice y el tema nombra esa fuente: descarta el tema en lugar de
añadir contenido. Redactar de nuevo sustituye el borrador. Quien puede editar el drafter encuentra **Edit the drafter's
instructions** en el borrador, y el propio drafter en **System agents**, en la
página Agents.

Un borrador nombra sus fuentes: los documentos de la base de conocimiento en
los que se apoya, los archivos de contexto que sigue y las preguntas del tema
que responde. Cada una se verifica antes de guardar el borrador - un documento
debe pertenecer a la base de conocimiento del tema, una pregunta debe ser del
tema, un archivo de contexto debe ser uno que puedes leer - y la que no pasa se
omite, nunca se muestra, y se cuenta en el borrador. Se guardan como mucho 12
fuentes. Una fuente borrada después deja de mostrarse.

Si cambias un borrador en el editor, pasa a ser tu contenido: su run y sus
fuentes dejan de mostrarse, porque lo que citó el modelo ya no habla por él.

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
| Escribir, guardar o añadir el contenido de un tema | `runs:view` y `collections:edit` en la base de conocimiento, por tu rol o por un grant de edición sobre ella |
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
borrador.

El borrador es el único texto que guarda un tema, escrito por un modelo o por
una persona. Las credenciales que contenga se ocultan antes de guardarlo.
Redactar envía las preguntas, respuestas y comentarios al proveedor del modelo
del redactor, después de quitar lo que identifica a las personas: direcciones
de correo electrónico, números de teléfono, de tarjeta y de cuenta bancaria, y
todo número o código de cuatro o más dígitos, o de tres con una letra, como un
número de pedido. Una cifra como «30 días» o «$500» se queda. Nada de lo que
escribe una persona se modifica. Consulta
[Protección de datos](data-protection.md#where-personal-data-lives).

Borrar a una persona elimina los borradores que un modelo escribió a partir de
sus preguntas. El contenido que una persona escribió o cambió se queda, igual que
un documento añadido a partir de él.

Un documento añadido desde un tema llega a todas las personas a las que
responden los agents de su base de conocimiento, así que antes de añadirlo se
revisa el contenido en busca de datos personales y de cualquier número o
código de ese tipo que repita de las preguntas, respuestas o comentarios del
tema, salvo que un archivo de contexto de los agents del tema también lo
indique. Lo que se encuentra se muestra en el tema, y la adición espera hasta
que lo confirmes.

La entrada de auditoría registra cuánto se marcó y que se
confirmó, no qué. El documento se queda cuando se borra el tema, la persona que
lo añadió o una persona cuya pregunta le dio forma: alguien revisó y confirmó lo
que dice.

Una pregunta leída de una respuesta se guarda igual que una búsqueda: contiene
la pregunta de la persona y se va con su run y su conversación. Revisar
respuestas envía preguntas, respuestas y comentarios de valoraciones negativas
al proveedor del modelo del clasificador.

De cada respuesta leída se recuerda
su veredicto, el run del clasificador y su motivo en una frase, que se va con la
respuesta y se borra cuando se borra a la persona que preguntó. El motivo solo lo
ve quien puede ver el agent que respondió. Puede nombrar las instrucciones del
agent o uno de sus archivos de contexto - por su nombre, nunca por lo que dicen -
incluso a quien no puede leer ese archivo. Una respuesta cuyo run ya no existe no
dice quién preguntó, así que su motivo se queda hasta que se va la conversación de
la respuesta.

## Lo que las lagunas aún no detectan { #limits }

Las respuestas solo se leen cuando alguien las revisa, y solo de los últimos 30
días. Los runs por la API HTTP no guardan respuesta, así que una pregunta hecha
allí se convierte en laguna solo cuando su búsqueda falló. Una respuesta
valorada negativamente sin comentario se lee por lo que dijo el agent, no por la
valoración.

Los nombres no se quitan de lo que lee el redactor ni se marcan en el contenido
que se va a añadir: nada aquí reconoce un nombre. Revisa si un borrador los
contiene antes de añadirlo.
