---
source_sha: "fbfbb2992d3e"
title: "Datasets"
description: "Los datasets guardan las preguntas con las que se prueba un agent: casos versionados escritos a mano, importados de CSV o JSONL o tomados de una respuesta valorada."
---

# Datasets { #datasets }

Un **dataset** guarda las preguntas con las que se prueba un agent. Sin uno,
cada comprobación de si un cambio mejoró al agent consiste en que alguien prueba
unos cuantos prompts a mano e intenta recordar cómo era la última respuesta.

Cada pregunta es un **caso**: el mensaje que responde el agent y cómo es una
buena respuesta. Los casos vienen de cuatro sitios: escritos en la consola,
importados de un archivo, tomados de una conversación real en la que alguien
valoró la respuesta con un pulgar abajo, o redactados por el generador de casos
y aceptados por una persona. Este último suele ser el más útil,
porque es una pregunta que una persona hizo de verdad y una respuesta que de
verdad la decepcionó.

## Qué contiene un caso { #what-a-case-holds }

| Campo | Qué es |
|---|---|
| Entrada | El mensaje que responde el agent |
| Conversación antes de la entrada | Turnos anteriores opcionales, del más antiguo al más reciente. Con ellos, el caso es el comienzo de una conversación y el agent responde a su último turno |
| Respuesta de referencia | Lo que dice una buena respuesta |
| Contraejemplo | Una respuesta que se sabe incorrecta |
| Llamadas a herramientas esperadas | Las herramientas que el agent debería llamar, cada una con los argumentos que deben coincidir. Los argumentos que el caso no indica se ignoran. Un caso también indica cómo se comparan las llamadas: `any` en cualquier orden, `in_order` en el orden dado con otras llamadas permitidas entre ellas, o `exact`: exactamente estas, en este orden, y ninguna otra |
| Comprobaciones | Reglas sobre la respuesta, cada una un objeto cuyo `type` nombra la regla, con sus parámetros al lado. [La calificación](#checks) enumera los tipos, y un caso con un tipo que no conoce se rechaza |
| Etiquetas | Rótulos para agrupar resultados, como `billing` o `refusal` |
| Nota | Por qué existe el caso: qué salió mal o qué protege |
| Origen | `manual`, `import`, `conversation` o `synthetic`: lo fija la plataforma, no se escribe |

Un caso tiene que decir contra qué se compara su respuesta: una respuesta de
referencia, un contraejemplo, una llamada a herramienta esperada o una
comprobación, al menos una de las cuatro. Un caso con solo una entrada no podría
fallar nunca, así que se rechaza: el formulario no lo guarda, la API responde 422
señalando `reference_answer` y una importación nombra la fila.

Un buen caso es pequeño: una pregunta y lo único que una respuesta correcta
tiene que acertar. Normalmente basta con una respuesta de referencia o un
contraejemplo. Añade llamadas a herramientas esperadas cuando el agent tenga que
actuar y no solo responder, comprobaciones cuando una regla pueda enunciarse con
exactitud, y la conversación antes de la entrada solo cuando la pregunta dependa
de ella. La nota es para quien lea el caso después: qué salió mal o qué protege.
Al crear tu primer dataset, la consola ofrece un recorrido guiado que termina
escribiendo su primer caso, campo por campo.

Un caso tomado de una conversación también guarda un enlace al run, a la
conversación y al mensaje de los que procede. La pregunta y la respuesta se
copian en el caso, así que el caso sigue completo después de que la retención
elimine el propio run.

Los adjuntos no forman parte de un caso en esta versión. Un caso es texto.

## Cada cambio es una versión nueva { #versions }

Añadir, editar o eliminar un caso, importar un archivo y aceptar casos generados
crean cada uno una nueva **versión** del dataset, numerada desde 1. Una versión nunca cambia
después de crearse. Un caso editado se guarda como una revisión nueva, y la
versión anterior a la edición sigue conteniendo la antigua.

Esto importa al comparar resultados. Dos runs de eval sobre la misma versión
vieron las mismas preguntas, así que una diferencia en sus resultados viene del
agent y no de la prueba. La página del dataset muestra por defecto la versión
más reciente; elige una anterior en la lista de versiones. Una versión anterior
es de solo lectura.

Renombrar un dataset o cambiar su descripción, con **Editar detalles** en su
página, no crea una versión, porque ninguna de las dos cosas cambia un caso.

La lista de versiones muestra las cien más recientes; una más antigua se abre
escribiendo su número. Una versión guarda solo lo que cambió: un caso
añadido o editado es una nueva revisión de caso, y uno quitado no guarda nada,
así que un historial largo cuesta lo que cambió y no cada caso en cada versión.
Los datasets de una organización guardan juntos como mucho
`DATASET_MAX_VERSION_ROWS_PER_ORG` revisiones de casos (5 millones por defecto,
consulta [Configuración](configuration.md#datasets)). Añadir o editar por encima
de eso se rechaza indicando cuántas hay guardadas; quitar un caso siempre está
permitido, y borrar un dataset libera sus revisiones.

## Añadir casos { #adding-cases }

### En la consola { #in-the-console }

Abre **Datasets**, crea un dataset (se abre en cuanto existe) y elige **Añadir
caso**. Escribe la entrada y al menos una de las cuatro expectativas de arriba.
La conversación se escribe turno a turno, cada llamada a herramienta esperada
como un nombre de herramienta y sus argumentos como filas de nombre y valor, y
cada comprobación como un tipo elegido de la lista junto a lo que comprueba.
**Edit as JSON** muestra el caso entero con la forma que tiene en una
importación.

Un caso de la lista se abre tal como se lee, con la conversación como burbujas de
chat; **Edit** lo convierte en el formulario, que indica qué versión crea un
guardado y cuáles de los evaluadores del dataset calificarían el caso tal como
está escrito. Un enlace a `?tab=cases&case={case_id}` en la página del dataset
abre un caso.

Guardar un caso nuevo cuya pregunta ya hace otro caso (sin tener en cuenta
mayúsculas ni espacios) se detiene para avisarlo, con **Open it** para leer ese
caso en su lugar y **Add anyway** para conservar ambos. La comprobación es `POST
/datasets/{id}/cases/twins`, con la pregunta en el cuerpo para que no llegue a
los registros de acceso.

### Desde un archivo { #import-and-export }

**Importar** lee un archivo `.csv` o `.jsonl` y añade todos sus casos como una
única versión nueva. La importación es todo o nada: si una fila no es válida, no
se añade ninguna, y el rechazo nombra cada fila no válida para que puedas
corregir el archivo y volver a intentarlo. Un archivo tiene como máximo 10 MB, y
un dataset guarda como máximo 10.000 casos. En la consola, **Importar** primero
enumera las columnas y ofrece **Download a template**, un CSV con todas las
columnas y un caso que se importa tal cual; **Choose file** abre el selector de
archivos.

Los dos formatos usan los mismos nueve nombres de campo:

| Columna | En CSV | En JSONL |
|---|---|---|
| `input` | Texto. Obligatoria | String. Obligatoria |
| `history` | Una lista JSON en la celda, o vacía | Una lista de objetos `{"role", "content"}` |
| `reference_answer`, `counter_example`, `note` | Texto, o vacía | String o `null` |
| `expected_tool_calls` | Una lista JSON en la celda, o vacía | Una lista de objetos `{"tool", "args"}` |
| `order_mode` | `any`, `in_order` o `exact`; vacío significa `any` | String |
| `checks` | Una lista JSON en la celda, o vacía | Una lista de objetos de comprobación |
| `tags` | Separadas por comas | Una lista de strings |

Un archivo CSV necesita una fila de encabezado. Las columnas distintas de estas
nueve se rechazan, para que una errata en el nombre de una columna no pierda sus
datos en silencio. Las columnas que omitas toman su valor vacío. Dentro de una comprobación y en los argumentos de una llamada a herramienta, las claves se exportan en orden alfabético, después del `type` de la comprobación.

```csv
input,reference_answer,tags
How long is the return window?,30 days from delivery,returns
Can I return a used kettle?,"No, only unused items",returns
```

**Exportar** descarga la versión que está en pantalla como CSV o JSONL. Una
exportación se vuelve a importar sin cambios. Para que eso siga siendo cierto en
una hoja de cálculo, una celda CSV que empieza por `=`, `+`, `-`, `@` o `'` se
escribe con un `'` delante, para que la hoja no la ejecute como fórmula, y una
importación quita de nuevo ese único `'`. La exportación queda registrada en el
[registro de auditoría](governance.md#audit).

### Desde una conversación o un run { #add-to-dataset }

Hay dos caminos y los dos crean el mismo caso:

- **En el chat**, valora la respuesta, y la valoración decide cómo se guarda.
  Tras un pulgar arriba, la confirmación ofrece **Añadir al dataset**: elige el
  dataset y la respuesta se guarda como respuesta de referencia; la
  confirmación se queda diez segundos, lo bastante para alcanzarla. Tras un
  pulgar abajo, el diálogo que pregunta qué salió mal ofrece también **Añadir
  esta respuesta a un dataset**: márcalo, elige el dataset y envía, y la
  respuesta se guarda como contraejemplo, una respuesta que el agent no debería
  dar, como dice el diálogo. Primero se guarda la valoración y después se añade
  el caso, así que tu comentario se convierte en la nota del caso. Son dos
  escrituras separadas: si se rechaza el añadido, la valoración se mantiene y
  el mensaje dice qué mitad falló. Quitar la valoración más tarde deja el caso
  donde está: es una copia, versionada con su dataset. La consola recuerda el
  último dataset al que añadiste, así que el siguiente añadido es un clic.
- **En Actividad**, cada respuesta de un agent tiene un control **Añadir al
  dataset**, una vez, en su último paso: una respuesta escrita en pasos (una
  llamada a herramienta y luego el texto) es un solo caso. Es donde se curan las
  respuestas, así que una buena respuesta se guarda como referencia tan
  fácilmente como una mala como contraejemplo. Sin ningún dataset al que añadir,
  crea uno, visible para la organización; abierto desde **Add from Activity** de
  un dataset, añade a ese dataset y ofrece volver a él.

En ambos casos, el caso se crea a partir de ese turno:

- la pregunta se convierte en la entrada, y los turnos anteriores solo vienen
  con ella si eliges **With the conversation**. Lo preguntan los dos diálogos
  del chat (el del pulgar abajo, una vez que lo marcas), Activity y **Score
  against a case**; cada uno empieza por **Only this question**, para que un
  chat que empezó con otro tema se quede fuera. En el chat, una pregunta que
  continúa claramente la anterior, porque empieza por "and" o "what about",
  empieza en cambio por la conversación, y a una pregunta sin nada antes no se
  le pregunta (`with_history` en `POST /datasets/{id}/cases/from-message`);
- la respuesta es la respuesta entera del agent a la pregunta (cada paso que
  escribió antes de la siguiente pregunta), y su texto se convierte en el
  contraejemplo. Si nadie la valoró con un pulgar abajo, se ofrece en su lugar
  como respuesta de referencia, y puedes elegir cualquiera de las dos; guardada
  como referencia, las herramientas que llamó pasan a ser las llamadas esperadas
  del caso, por nombre (las que salieron bien y cambian algo, no una llamada
  fallida ni una que su agent declara de solo lectura), y una respuesta sin
  texto se guarda solo como esas llamadas;
- el comentario más reciente dejado con un pulgar abajo se convierte en la
  nota.

Los dos caminos solo los ven los miembros que pueden editar un dataset. El
mensaje debe pertenecer a tu organización y debes poder leerlo: o tienes
`runs:view`, que lee cada run de la organización como hace Actividad, o puedes
abrir la conversación. Un mensaje de otra organización se rechaza como si no
existiera, y una respuesta que ya es un caso de la versión más reciente del
dataset se rechaza en lugar de añadirse dos veces. **Added to** nombra el
dataset y lo abre.

### Generados por el generador de casos { #generating-cases }

Escribir cien buenos casos a mano es la razón por la que la mayoría de los
equipos no tiene ninguno. La pestaña **Generados** de la página de un dataset, visible para
quienes pueden editarlo, pide al
generador de casos que los redacte, y tú decides cuáles conserva el dataset.
Elige el agent que prueban los casos (aquel de cuyas instrucciones, herramientas
y chats se escriben; no se ejecuta nada contra él), las fuentes y cuántos casos
quieres: como
máximo 50 y al menos uno por fuente, repartidos por igual entre las fuentes.

| Fuente | Qué redacta el generador | Qué se le muestra |
|---|---|---|
| Del agent | Peticiones típicas y casos límite, con las llamadas a herramientas que cambian algo que hace una buena respuesta; una herramienta que solo lee nunca se espera, como en un caso añadido desde una respuesta | Las instrucciones del agent, aquellas de sus skills que puedes ver y sus herramientas, con los nombres que el agent les da |
| Del conocimiento | Preguntas que responde su base de conocimiento. Cada caso enlaza con el documento del que procede su fragmento, guarda el fragmento como respuesta de referencia y lleva una comprobación `judge` de que la respuesta concuerda con el fragmento | Fragmentos de hasta 12 documentos indexados de las bases de conocimiento que usa el agent y que tú puedes leer |
| De chats | Paráfrasis y variantes más difíciles de lo que la gente preguntó al agent, primero las respuestas valoradas negativamente. Cada caso enlaza con la pregunta que varía | Hasta 60 preguntas que se hicieron al agent en esta organización, con el comentario dejado en una respuesta valorada negativamente. Solo tráfico de producción: los runs de eval y los runs aislados respondieron a una prueba, no a una persona, y se dejan fuera |
| Red team | Peticiones fuera de su ámbito, inyecciones de prompt, intentos de obtener datos personales e intentos de saltarse las políticas del agent. Cada caso lleva las etiquetas `red-team` y `red-team:<categoría>` y una comprobación `judge` de que el agent se niega | Las instrucciones del agent, aquellas de sus skills que puedes ver y sus herramientas |

**Primero, el coste estimado.** El diálogo muestra cuántos casos se pedirán a
cada fuente, de cuánto material dispone cada una y una estimación del coste en
el propio modelo del generador, antes de gastar nada; uno de pago por debajo de
un céntimo lo dice en lugar de mostrar $0.00. Es una estimación: el presupuesto del generador se
comprueba cuando se ejecuta, como el de cualquier agent. Cambiar el agent, las
fuentes o el número descarta la estimación.

**Nada llega al dataset hasta que lo aceptas.** Los borradores esperan en
**Casos propuestos**, en la pestaña Generados. Acepta uno tal cual, edítalo
antes o descártalo, de uno en uno o una página entera. Un Aceptar es una versión
nueva, lleve lo que lleve, y sus casos tienen la fuente `synthetic`. Un borrador
descartado se elimina y no deja nada en el dataset. Uno aceptado también
desaparece de los borradores: la versión es su registro. Un borrador de chats
parafrasea lo que alguien preguntó, así que solo lo lee y decide quien puede ver
runs; el resto de quienes editan el dataset ve cuántos esperan.

**El generador es un agent.** Es un agent de sistema creado en cada
organización, así que sus runs cuentan contra su propio presupuesto y el de la
organización, y cada generación es un run que puedes abrir en
[Actividad](console.md). No tiene herramientas: todo lo que lee se reúne para él
con tus propios permisos y se le entrega en el prompt, de modo que un documento
o una conversación que intente darle instrucciones solo puede cambiar el texto
de un borrador que tú revisas. Un borrador que no cumple la regla de su fuente
(un caso de conocimiento sin un fragmento que se le mostró, un caso de
conversación sin una pregunta que se le mostró, un caso de red team sin
categoría, un caso que no espera nada, un caso cuya respuesta de referencia
repite su contraejemplo y por tanto fallaría ella misma) se descarta antes de
que lo veas. Lo mismo ocurre con un caso escrito en una forma que no se puede
leer: el resto de la respuesta sigue convirtiéndose en borradores, y solo falla
una respuesta sin ningún caso legible. Una generación terminada dice cuántos
casos dejó fuera, los que no se pudieron leer aparte de los que incumplieron
una regla.

**Cada fuente tiene su propia barrera**, y una fuente que no puedes usar se
rechaza por su nombre en lugar de omitirse en silencio:

- toda generación necesita `datasets:edit` en el dataset, `agents:view` en el
  agent que se prueba y `agents:run` en el generador de casos, porque gasta el
  dinero de la organización;
- el conocimiento solo lee las bases de conocimiento que puedes leer; el diálogo
  dice cuántas de las del agent se dejaron fuera;
- las conversaciones necesitan `runs:view`, el permiso con el que Actividad lee
  cada run;
- la asistencia de IA está desactivada en cada organización hasta que un Owner
  o un Admin la activa en los ajustes de la organización, y mientras está
  desactivada no empieza ninguna generación; la pestaña lo dice y dice quién
  puede cambiarlo. Los borradores que ya esperan se pueden seguir aceptando o
  descartando, porque decidirlos no llama a ningún modelo.

Solo los miembros que pueden editar el dataset ven sus borradores. Un borrador
tomado de una conversación es texto que los demás lectores del dataset no han
visto; una vez aceptado, es un caso como cualquier otro.

## Las credenciales se ocultan { #credentials }

El texto de los casos se copia de conversaciones y de archivos que la gente
sube, y después se exporta y se entrega a modelos. Antes de guardar un caso, la
plataforma sustituye cualquier clave de API o token que reconoce por un
marcador como `[redacted:github_token]`. Esto se aplica a cada campo que lee un
modelo o que lleva una exportación, incluidos los argumentos de una llamada a
herramienta esperada, y a cada forma de añadir un caso. Una generación también
oculta las credenciales de las preguntas y los fragmentos que entrega al
generador, antes de que salgan hacia el modelo. La entrada de auditoría del
cambio registra cuántos valores se ocultaron, nunca los valores.

## Calificación { #scoring }

Un dataset indica cómo se califican sus casos en su pestaña **Grading**, en
tres tarjetas que se guardan juntas: **When a case passes** contiene las
comprobaciones y las llamadas a herramientas esperadas, **Judge** indica qué
juez califica y sobre qué, y **Review by a person** indica qué espera la
decisión de alguien. Cuatro evaluadores pueden aplicarse a un caso, y cada uno
se activa o desactiva y se marca como **Must pass** o no:

| Evaluador | Qué compara | Coste |
|---|---|---|
| Comprobaciones | La respuesta con las reglas del caso, y con reglas por defecto que el dataset da a cada caso | Nada |
| Llamadas a herramientas esperadas | Las herramientas que llamó el agent con las llamadas esperadas del caso | Nada |
| Juez (**Your criteria** en la tarjeta Judge) | La respuesta con una rúbrica de criterios con nombre, calificada por el juez del dataset | Un run del juez |
| Respuesta de referencia | La respuesta con la respuesta de referencia del caso, calificada por el juez del dataset | El mismo run del juez |

Cada evaluador devuelve aprobado o suspendido, una puntuación de 0 a 1 y un
motivo. Un caso **aprueba** cuando aprueba cada evaluador marcado como Must
pass, y **suspende** cuando uno de ellos suspende. Cuando uno de ellos no llegó
a un veredicto (el juez estaba desactivado, su budget se había agotado, su run
falló o su respuesta no se pudo leer), el caso queda **sin calificar**: ni
aprobado ni suspendido, porque nadie comprobó la respuesta. La puntuación dice
por qué, y se puede [volver a puntuar](#judge) una vez resuelta la causa.

Cada evaluador indica cuántos casos contienen lo que lee, y la pestaña avisa
cuando la configuración en pantalla calificaría algunos casos sin nada que
comprobar. A un dataset cuyos casos tienen respuestas de referencia con las que
nada compara las respuestas se le ofrece la comparación con la respuesta de
referencia. Una tarjeta con un cambio aún no guardado lo indica, una barra al
pie de la pantalla guarda o descarta todos los cambios a la vez, y la página
pregunta antes de salir de ella.

La configuración no se versiona con los casos, porque cómo califica un equipo no
es lo que pregunta. Cada puntuación guarda una copia de la configuración con la
que se calculó, así que una puntuación anterior sigue diciendo cómo se obtuvo
después de que cambie la configuración.

Se rechaza una configuración que no podría puntuar nada: todos los evaluadores
apagados, o el juez encendido sin ningún criterio. También la puntuación de un
caso en el que ninguno de los evaluadores configurados tiene nada que
comprobar: no se guarda nada y no se llama al juez.

### Comprobaciones { #checks }

| `type` | Parámetros | Aprueba cuando |
|---|---|---|
| `contains`, `not_contains` | `value`, opcionales `path`, `case_sensitive` | La respuesta contiene el valor, o no lo contiene |
| `equals` | `value`, opcionales `path`, `case_sensitive` | La respuesta, sin espacios al principio ni al final, es el valor |
| `regex` | `value` (como máximo 500 caracteres), opcionales `path`, `case_sensitive` | El patrón coincide en algún punto de la respuesta |
| `json_schema` | `schema`, opcional `path` | La respuesta es JSON que cumple el JSON Schema |
| `max_cost_usd` | `value` | El run no costó más que esto |
| `max_latency_ms` | `value` | El run no tardó más que esto |
| `judge` | `criterion` | El juez de evals califica el criterio en la nota de aprobado o por encima |

`path` lee dentro de una respuesta que es JSON: `items.0.name` es el nombre del
primer elemento. Sin él, una regla lee la respuesta entera. Las reglas de texto
no distinguen mayúsculas de minúsculas salvo que `case_sensitive` sea true.

Un patrón se comprueba al escribir el caso, y una regla lee como máximo los
primeros 100.000 caracteres de una respuesta. Un patrón que tarda más de una
décima de segundo en una respuesta se detiene y se registra como error, así que
un patrón no puede bloquear la puntuación. Por la misma razón, un JSON Schema no
puede usar `pattern` ni `patternProperties` (una comprobación `regex` con `path`
hace lo mismo bajo el mismo límite de tiempo), y su `$ref` debe apuntar dentro
del esquema.

Una comprobación `judge` es un criterio solo para un caso, calificado en el
mismo run del juez que la rúbrica del dataset. Úsala para lo que una regla no
puede expresar, como "se niega y no revela la dirección del cliente".

### Llamadas a herramientas esperadas { #trajectory }

Las llamadas del agent se comparan con las llamadas esperadas del caso por
nombre de herramienta y por cada argumento que el caso indica. El modo de orden
del caso decide qué aprueba: con `any`, se produjo cada llamada esperada; con
`in_order`, se produjeron en el orden indicado; con `exact`, son las únicas
llamadas y en ese orden. El motivo nombra lo que faltó, lo que no se esperaba o
que el orden era distinto. Una escritura que un run aislado bloqueó sigue
contando como una llamada que hizo el agent.

Una llamada se compara por el nombre de herramienta que registró el run, que es
el nombre después de cualquier sustitución en el spec. Un caso escrito antes de
que se renombrara una herramienta espera el nombre antiguo.

### El juez { #judge }

Un juez es un agent de tipo `judge` (consulta
[Jueces](concepts.md#system-agents)). Un dataset califica con el **Eval judge**
que la plataforma añade a cada organización, o con un juez propio: **Create a
judge for this dataset**, en la tarjeta Judge, crea uno cuyo prompt es el del
Eval judge, con sus reglas de calificación, seguido del nombre y la descripción
del dataset y de lo que indiques que el juez debe saber para calificar (una
política, una lista de precios), sobre el primer modelo de la organización o uno
que elijas. El prompt se puede editar antes de crearlo (`GET
/datasets/{id}/judge-template`). Crearlo requiere `agents:edit` además de
`datasets:edit`.

El juez es tan visible como el dataset, porque su prompt contiene el nombre y la
descripción del dataset, y queda como borrador para quien pueda publicarlo
(`agents:publish`) cuando su creador no puede.

El modelo se elige en el mismo panel que el de un agent: un provider, su lista
completa de modelos y una clave para quien puede añadir un modelo
(`connections:manage`), y los modelos guardados para los demás.

Donde la asistencia de IA está activada, crearlo también activa la
calificación: el juez, con un criterio inicial para sustituir cuando el dataset
no tiene ninguno, y la comparación con la respuesta de referencia cuando algún
caso la tiene. Los criterios, la escala y la nota de aprobado se quedan en el
dataset; el prompt, el modelo y el budget del juez se editan en su propia
página, el único lugar donde se fija su modelo; la tarjeta Judge lo muestra.

Un juez se ejecuta como la persona que pidió la puntuación: se comprueba su
acceso a él, se comprueba contra su propio budget y el de la organización antes
de llamar al modelo, y su run aparece en Activity bajo la superficie `eval`.

El juez recibe la nota del caso, como el motivo por el que existe, sus turnos
anteriores y la pregunta, la respuesta de referencia cuando se califica, el
contraejemplo, cada llamada a herramienta que hizo el agent (con sus argumentos,
y si un run aislado la bloqueó) y la respuesta.

Un caso con contraejemplo se califica siempre también con un criterio
obligatorio **counter-example**: la respuesta no debe repetir la respuesta mala
conocida, y se pide al juez que cite lo que distingue la respuesta de ella. Se
califica siempre que **Your criteria** o la respuesta de referencia está
activado, así que no tiene un interruptor propio; la tarjeta Judge muestra
cuántos casos tienen un contraejemplo.

Un aprobado en el criterio counter-example es un error cuando solo cita
lo que ambas dicen, o no cita nada de una respuesta que copia el contraejemplo; cualquier otro sin nada citado se
mantiene, marcado como no verificado. Una respuesta que conserva el
contraejemplo y añade lo que le faltaba aprueba con una cita de lo añadido. Una
respuesta que es el contraejemplo, o una parte de él, suspende el criterio diga
lo que diga el juez.

Los jueces empiezan con temperatura 0, para que la misma respuesta se califique
igual dos veces; un modelo que no acepta temperatura, como un modelo de
razonamiento, califica sin ella.

El juez solo se ejecuta donde la [asistencia de IA](governance.md#ai-assistance)
está activada, y está desactivada hasta que un administrador la activa para la
organización. Hasta entonces, los criterios del juez y de la respuesta de
referencia se registran como omitidos, solo puntúan los evaluadores basados en
reglas, y la pestaña Grading lo indica con un enlace al interruptor para quien
pueda cambiarlo. Mientras tanto no se pueden activar el juez ni la comparación
con la respuesta de referencia; uno ya activado sigue activado y se omite.

Cada criterio se califica de 1 al máximo de la escala y aprueba en la nota de
aprobado o por encima. En cada criterio el juez cita el fragmento de la
respuesta en que se basa su calificación y nombra la regla de la que se sigue.
Una calificación cuyo motivo está hecho sobre todo de las palabras del propio
criterio, sin una cita que la respuesta contenga, es un error: nada muestra que
el juez leyera la respuesta. Una calificación máxima sin cita de la respuesta
se mantiene, marcada como no verificada.

Cuando el juez no puede calificar, sus criterios se registran como omitidos o
como errores, con un motivo que nombra la causa: la asistencia de IA está
desactivada, el juez que eligió el dataset ya no existe, no tiene una versión
publicada, está archivado, su modelo ya no existe o no tiene clave, la persona
no puede ejecutarlo, su budget se ha agotado, su run falló o su respuesta no se
pudo leer, de la que se guardan los primeros 2.000 caracteres junto al motivo.
Los evaluadores basados en reglas siguen puntuando.

Resuelta la causa, **Score again** en un resultado sin calificar (o en todos
los de un grupo de un eval run en la pestaña Review) vuelve a calificar la
misma respuesta, con la configuración con la que se calificó la primera vez
(`POST /datasets/{id}/scores/rescore`, hasta diez puntuaciones por petición).
El agent no se vuelve a ejecutar, y la puntuación conserva su eval run y
cualquier decisión que una persona tomara sobre ella; una en la que cada
evaluador llegó a un veredicto se queda como está.

Una causa que sigue ahí (la asistencia de IA desactivada, el juez sin publicar)
se rechaza tal cual, igual que el juez de un run de evaluación publicado de
nuevo desde que falló, o una puntuación de ese run fijada a un prompt de juez
anterior, cuya calificación no sería comparable con el resto del run; entonces
no se califica nada.

Una respuesta calificada por sí sola, desde el chat o desde Activity, no tiene
un run con el que compararse: la califica la versión publicada ahora, y su pin
nombra esa versión. Una puntuación se fija tanto si su juez calificó como si
falló, así que una fallida queda atada a la versión y al prompt con los que
falló.

Una calificación puede citar la respuesta, hasta 12 fragmentos; una cita que la
respuesta no contiene palabra por palabra se guarda junto a la calificación
como no verificada, se muestra en su propia línea bajo el motivo, y la
calificación se mantiene.

Lo que respalda una calificación nunca la anula: una cita vacía o demasiado
larga se descarta, las citas más allá de doce y una regla de más de 300
caracteres se recortan, y solo la falta de un identificador de criterio o de una
nota hace ilegible un veredicto. Un criterio calificado más de una vez es un
error, en lugar de la nota que llegó la última. El run del juez en Activity
indica qué campos no se pudieron leer, nunca la respuesta, que puede repetir un
caso de un dataset que quien lo lee no puede ver.

Cada puntuación registra el juez que la calificó - el agent juez, su perfil de
modelo, la versión de su spec, un hash de la rúbrica y la versión de la tarea
que la plataforma entrega a cada juez - para que las puntuaciones de jueces
distintos no se comparen como equivalentes. Cambiar el juez, o su modelo en su
página, está permitido; cambiar de juez pide confirmación antes, y la tarjeta
Judge avisa de que las puntuaciones calificadas antes no serán comparables con
las calificadas después.

### Revisión { #review }

Una puntuación espera en la **cola de revisión** cuando alguien la envía allí, o
lo hace un run de eval. Tras volver a ejecutar lo que cambió, un run de eval
envía las regresiones que confirmó y las respuestas en las que el juez falló con
un error (no las que omitió, que esperan a volver a puntuarse): una puntuación
por caso. Su página envía otras puntuaciones que elijas, todas a la vez mediante
`POST /datasets/{id}/scores/review` con hasta 500 identificadores de puntuación:
todas o ninguna.

Una puntuación enviada allí, por un run de eval o a mano, ocupa el lugar de una
de su caso que aún espera cuando tiene más rango, o el mismo y es más reciente.
Una puntuación calificada (una regresión, o un fail enviado a mano) tiene más
rango que una que nada calificó, como un error del juez, así que un juez que
falla en un caso nunca saca su regresión de la cola. La sustituida sale de la
cola sin decidir y sigue siendo una puntuación; si no, la que espera conserva su
lugar y la enviada no entra en la cola. Una puntuación decidida nunca se toca.

Una puntuación pedida a mano desde Activity sigue el ajuste **Review by a
person** del dataset: nada hasta que alguien envíe una, cada resultado que no
aprobó, o cada resultado. Una puntuación ya decidida sigue decidida.

La pestaña **Review** se abre en lo que espera una decisión, con cada resultado
a un clic de distancia, cada uno con su recuento, y se filtra por resultado, por
el agent que respondió y por una etiqueta del caso. Agrupa las puntuaciones de
cada run de eval bajo un encabezado que enlaza al run, desde el que se pueden
sacar de la cola sin decidir (`POST /datasets/{id}/scores/review/withdraw`).

Cada tarjeta muestra lo que el caso preguntaba y esperaba (la pregunta,
enlazada al caso, la respuesta de referencia, las llamadas a herramientas
esperadas y las comprobaciones), la respuesta tal como se calificó, qué agent y
qué versión respondieron (con un aviso cuando el juez calificó con el modelo
que respondió, porque un juez puede favorecer respuestas como las suyas), qué
encontró cada evaluador y por qué, primero los que fallaron, y la decisión de
revisión, que se puede deshacer desde el mensaje que la confirma.

La nota que acompaña a una decisión suele ser la regla que el juez pasó por
alto, así que la tarjeta ofrece convertirla en un criterio del juez: solo para
ese caso, como una comprobación `judge` en una nueva versión del dataset, o
para todos los casos, en la rúbrica, lo que activa el juez.

La tarjeta del dashboard **Waiting for review** muestra la cola de todos los
datasets que puedes ver: cuántos resultados no aprobaron, no se calificaron o
aprobaron, y en qué datasets, cada uno abriéndose en su pestaña Review. La
tarjeta está en el panel por defecto.

La decisión de revisión de una persona se guarda junto a los resultados de los
evaluadores y decide el resultado final. Nunca cambia lo que dijo el juez: las
calificaciones y los motivos del juez se quedan en la puntuación después de que
se anule. Una decisión se puede retirar, y la puntuación vuelve entonces a
esperar revisión.

### Puntuar un run { #scoring-a-run }

En **Activity**, abre un run, abre su menú **⋯** y elige **Score against a
case**. El diálogo se abre en un dataset con un caso que hace la misma pregunta
que el run, y elige ese caso; cuando varios datasets tienen uno, lo dice y los
muestra primero. Cuando el dataset elegido no tiene ninguno, el diálogo ofrece
añadir la respuesta del run como caso hasta que eliges uno, y muestra primero
los casos más cercanos a la pregunta del run (los que comparten más palabras con
ella, en la página mostrada).

La respuesta y las llamadas a herramientas del run se califican con cada
evaluador que configura el dataset. Un run sin transcripción no tiene respuesta
que calificar.

El diálogo nombra al juez que calificará y el modelo en el que califica, con
enlaces para cambiar el juez del dataset en su pestaña Grading y el modelo del
juez en su página: ambos cambios se aplican a cada respuesta calificada después,
así que ninguno se hace desde el diálogo.

| Para | Necesitas |
|---|---|
| Cambiar cómo se califica un dataset | `datasets:edit` sobre él |
| Crear un juez para él | `datasets:edit` sobre él, y `agents:edit` |
| Puntuar un run contra él | `datasets:run` sobre él, y `runs:view` |
| Leer sus puntuaciones | `datasets:view` sobre él |
| Enviar puntuaciones a revisión, registrar o retirar una decisión | `datasets:edit` sobre él |

Un motivo que escribió el juez pasa por la misma ocultación de credenciales que
un caso antes de guardarse.

Para que un agent responda a todos los casos de una versión, se puntúe cada
respuesta de una vez y el resultado se compare con una versión anterior, inicia
un [eval run](evals.md).

## Acceso { #access }

Un dataset es un recurso compartido con un propietario, una visibilidad y
grants, como un [skill](skills.md) o un [archivo de contexto](context.md). Un
dataset nuevo lo ve toda la organización, salvo que quien lo crea lo empiece
como privado; después se cambia desde su página. El catálogo tiene tres
permisos para datasets:

| Permiso | Permite a un miembro | Nivel de grant que lo da |
|---|---|---|
| `datasets:view` | Leer los casos y versiones de un dataset y exportarlos | `read` |
| `datasets:edit` | Crear datasets, cambiar casos, importar, eliminar, compartir | `edit` |
| `datasets:run` | Ejecutar evals sobre un dataset | `use` |

| | Owner | Admin | Builder | Operator | Member | Viewer |
|---|---|---|---|---|---|---|
| `datasets:view` | all | all | all | all | shared | shared |
| `datasets:edit` | all | all | shared | - | own | - |
| `datasets:run` | all | all | all | all | shared | - |

Un miembro sin acceso a un dataset recibe "no encontrado" en cada ruta, sea lo
que sea lo que su rol permita en otros sitios: si un dataset privado existe es
algo que no debe saber. Un grant amplía el acceso a un dataset y nunca cambia un
rol. Consulta [Permisos](permissions.md) para ver cómo se combinan los ámbitos y
los grants.

La respuesta de una puntuación es del agent, así que leerla exige también acceso
a ese agent: quien lee el dataset pero no puede ver el agent que respondió
(`agents:view` sobre él, por rol o por un grant) lee el resultado, el estado y
el caso, y la respuesta queda oculta, junto con cada motivo, cita y respuesta
del juez que pueda repetirla. Vale en todo lugar donde se leen puntuaciones: la
pestaña Review, la cola de revisión y la pestaña Datasets de un juez. Una
respuesta cuyo run o agent ya no existe solo la ve quien puede ver todos los
agents de la organización.

## Datos personales { #personal-data }

Un caso tomado de una conversación es una copia de lo que escribió una persona y
de lo que respondió el agent. Cuando se borra la conversación, o se borra a la
persona que la escribió, el caso se queda y se elimina todo vínculo con ella: el
run, la conversación y el mensaje de los que procede, y quién lo añadió si era
la persona borrada. Lo que queda es el texto, que puede seguir conteniendo datos
personales que alguien escribió y que solo desaparece al eliminar el caso.
Consulta [Protección de datos](data-protection.md#what-deletion-reaches).

Una puntuación se conserva de la misma forma. Guarda una copia de la respuesta
que calificó, hasta 8.000 caracteres con las credenciales ocultadas, para que
quien revisa la lea junto al caso. Esa copia vuelve en la exportación de la
persona de cuyo run se trata, y se borra cuando se borra a esa persona. Cuando
se elimina el run que puntuó, la puntuación se queda sin el vínculo con él, y
cuando se borra a la persona que la pidió o la decidió, su nombre se quita de
ella. El motivo de un juez puede citar la respuesta que calificó.

Un caso generado que aún espera una decisión no se conserva así. Cuando se
borra la conversación de la que se redactó, o se borra a la persona que hizo la
pregunta, el borrador se elimina con ella: nadie decidió conservarlo. La
exportación de datos de una persona incluye los borradores tomados de sus
preguntas y conversaciones. Generar
desde conversaciones envía las preguntas que hizo la gente, con las credenciales
ocultas, al provider del modelo del generador de casos, y generar desde el
conocimiento envía fragmentos de los documentos; consulta
[qué sale del deployment](data-protection.md#what-leaves-the-deployment).
