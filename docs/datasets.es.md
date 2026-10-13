---
source_sha: "c41b7914ae35"
title: "Datasets"
description: "Los datasets guardan las preguntas con las que se prueba un agent: casos versionados escritos a mano, importados de CSV o JSONL o tomados de una respuesta valorada."
---

# Datasets { #datasets }

Un **dataset** guarda las preguntas con las que se prueba un agent. Sin uno,
cada comprobación de si un cambio mejoró al agent consiste en que alguien prueba
unos cuantos prompts a mano e intenta recordar cómo era la última respuesta.

Cada pregunta es un **caso**: el mensaje que responde el agent y cómo es una
buena respuesta. Los casos vienen de tres sitios: escritos en la consola,
importados de un archivo o tomados de una conversación real en la que alguien
valoró la respuesta con un pulgar abajo. Este último suele ser el más útil,
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
| Comprobaciones | Reglas sobre la respuesta, cada una un objeto cuyo `type` nombra la regla, con sus parámetros al lado. [La puntuación](#checks) enumera los tipos, y un caso con un tipo que no conoce se rechaza |
| Etiquetas | Rótulos para agrupar resultados, como `billing` o `refusal` |
| Nota | Por qué existe el caso: qué salió mal o qué protege |
| Origen | `manual`, `import`, `conversation` o `synthetic`: lo fija la plataforma, no se escribe |

Un caso tiene que decir contra qué se compara su respuesta: una respuesta de
referencia, un contraejemplo, una llamada a herramienta esperada o una
comprobación, al menos una de las cuatro. Un caso con solo una entrada no podría
fallar nunca, así que se rechaza: el formulario no lo guarda, la API responde 422
señalando `reference_answer` y una importación nombra la fila.

Un caso tomado de una conversación también guarda un enlace al run, a la
conversación y al mensaje de los que procede. La pregunta y la respuesta se
copian en el caso, así que el caso sigue completo después de que la retención
elimine el propio run.

Los adjuntos no forman parte de un caso en esta versión. Un caso es texto.

## Cada cambio es una versión nueva { #versions }

Añadir, editar o eliminar un caso, e importar un archivo, crean cada uno una
nueva **versión** del dataset, numerada desde 1. Una versión nunca cambia
después de crearse. Un caso editado se guarda como una revisión nueva, y la
versión anterior a la edición sigue conteniendo la antigua.

Esto importa al comparar resultados. Dos runs de eval sobre la misma versión
vieron las mismas preguntas, así que una diferencia en sus resultados viene del
agent y no de la prueba. La página del dataset muestra por defecto la versión
más reciente; elige una anterior en la lista de versiones. Una versión anterior
es de solo lectura.

Renombrar un dataset o cambiar su descripción no crea una versión, porque
ninguna de las dos cosas cambia un caso.

## Añadir casos { #adding-cases }

### En la consola { #in-the-console }

Abre **Datasets**, crea un dataset y elige **Añadir caso**. Escribe la entrada
y al menos una de las cuatro expectativas de arriba. La conversación, las llamadas a herramientas esperadas
y las comprobaciones se escriben como listas JSON: el mismo texto con el que las
guarda una exportación CSV.

### Desde un archivo { #import-and-export }

**Importar** lee un archivo `.csv` o `.jsonl` y añade todos sus casos como una
única versión nueva. La importación es todo o nada: si una fila no es válida, no
se añade ninguna, y el rechazo nombra cada fila no válida para que puedas
corregir el archivo y volver a intentarlo. Un archivo tiene como máximo 10 MB, y
un dataset guarda como máximo 10.000 casos.

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

Cada respuesta del agent en el chat y cada turno del agent en **Actividad**
tiene un control **Añadir al dataset**. Elige un dataset y el caso se crea a
partir de ese turno:

- la pregunta se convierte en la entrada, y los turnos anteriores en la
  conversación antes de la entrada;
- la respuesta se convierte en el contraejemplo. Si nadie la valoró con un
  pulgar abajo, se ofrece en su lugar como respuesta de referencia, y puedes
  elegir cualquiera de las dos;
- el comentario más reciente dejado con un pulgar abajo se convierte en la
  nota.

El control lo ven los miembros que pueden editar un dataset. El mensaje debe
pertenecer a tu organización y debes poder leerlo: o tienes `runs:view`, que lee
cada run de la organización como hace Actividad, o puedes abrir la conversación.
Un mensaje de otra organización se rechaza como si no existiera.

## Las credenciales se ocultan { #credentials }

El texto de los casos se copia de conversaciones y de archivos que la gente
sube, y después se exporta y se entrega a modelos. Antes de guardar un caso, la
plataforma sustituye cualquier clave de API o token que reconoce por un
marcador como `[redacted:github_token]`. Esto se aplica a cada campo que lee un
modelo o que lleva una exportación, incluidos los argumentos de una llamada a
herramienta esperada, y a cada forma de añadir un caso. La entrada de auditoría
del cambio registra cuántos valores se ocultaron, nunca los valores.

## Puntuación { #scoring }

Un dataset indica cómo se puntúan sus casos en su pestaña **Scoring**. Cuatro
evaluadores pueden aplicarse a un caso, y cada uno se activa o desactiva y se
marca como obligatorio o no:

| Evaluador | Qué compara | Coste |
|---|---|---|
| Comprobaciones | La respuesta con las reglas del caso, y con reglas por defecto que el dataset da a cada caso | Nada |
| Llamadas a herramientas | Las herramientas que llamó el agent con las llamadas esperadas del caso | Nada |
| Juez | La respuesta con una rúbrica de criterios con nombre, calificada por el juez de evals | Un run del juez |
| Respuesta de referencia | La respuesta con la respuesta de referencia del caso, calificada por el juez de evals | El mismo run del juez |

Cada evaluador devuelve aprobado o suspendido, una puntuación de 0 a 1 y un
motivo. Un caso **aprueba** cuando aprueba cada evaluador obligatorio. Cuando un
evaluador obligatorio no pudo ejecutarse (el juez estaba desactivado, su budget
se había agotado), el caso queda **sin puntuar**, no aprobado: un resultado que
nadie comprobó no cuenta como aprobado.

La configuración no se versiona con los casos, porque cómo califica un equipo no
es lo que pregunta. Cada puntuación guarda una copia de la configuración con la
que se calculó, así que una puntuación anterior sigue diciendo cómo se obtuvo
después de que cambie la configuración.

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
no distinguen mayúsculas de minúsculas salvo que `case_sensitive` sea true. Un
patrón se comprueba al escribir el caso, y una regla lee como máximo los
primeros 100.000 caracteres de una respuesta, así que un patrón no puede volver
lenta la puntuación.

Una comprobación `judge` es un criterio solo para un caso, calificado en el
mismo run del juez que la rúbrica del dataset. Úsala para lo que una regla no
puede expresar, como "se niega y no revela la dirección del cliente".

### Llamadas a herramientas { #trajectory }

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

El juez es el **Eval judge**, un agent que la plataforma añade a cada
organización (consulta [Agents del sistema](concepts.md#system-agents)). Se
ejecuta como la persona que pidió la puntuación: se comprueba su acceso a él, se
comprueba contra su propio budget y el de la organización antes de llamar al
modelo, y su run aparece en Activity bajo la superficie `eval`. Sus
instrucciones se pueden editar como las de cualquier agent, y un dataset puede
indicar otro modelo para él.

Cada criterio se califica de 1 al máximo de la escala y aprueba en la nota de
aprobado o por encima. Cuando el juez no puede calificar, sus criterios se
registran como omitidos o como errores, con un motivo que nombra la causa: la
asistencia de IA está desactivada, el juez no tiene una versión publicada, está
archivado, la persona no puede ejecutarlo o su budget se ha agotado. Los
evaluadores basados en reglas siguen puntuando.

### Revisión y veredictos { #review }

Un dataset puede enviar resultados a una **cola de revisión**: ninguno hasta que
alguien envíe uno, cada resultado que no aprobó, o cada resultado. La pestaña
Scores muestra los resultados de un dataset, y la tarjeta del dashboard
**Awaiting review** muestra la cola de todos los datasets que puedes ver.

El veredicto de una persona se guarda junto a los resultados de los evaluadores
y decide el resultado final. Nunca cambia lo que dijo el juez: las
calificaciones y los motivos del juez se quedan en la puntuación después de que
se anule. Un veredicto se puede retirar, y la puntuación vuelve entonces a
esperar revisión.

### Puntuar un run { #scoring-a-run }

En **Activity**, abre un run y elige **Score against a case**. Elige el dataset
y el caso, y la respuesta y las llamadas a herramientas del run se puntúan con
cada evaluador que configura el dataset. Un run sin transcripción no tiene
respuesta que puntuar.

| Para | Necesitas |
|---|---|
| Cambiar cómo se puntúa un dataset | `datasets:edit` sobre él |
| Puntuar un run contra él | `datasets:run` sobre él, y `runs:view` |
| Leer sus puntuaciones | `datasets:view` sobre él |
| Registrar o retirar un veredicto | `datasets:edit` sobre él |

Un motivo que escribió el juez pasa por la misma ocultación de credenciales que
un caso antes de guardarse.

## Acceso { #access }

Un dataset es un recurso compartido con un propietario, una visibilidad y
grants, como un [skill](skills.md) o un [archivo de contexto](context.md). Un
dataset nuevo es privado para quien lo creó hasta que se comparte desde su
página. El catálogo tiene tres permisos para datasets:

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

## Datos personales { #personal-data }

Un caso tomado de una conversación es una copia de lo que escribió una persona y
de lo que respondió el agent. Cuando se borra la conversación, o se borra a la
persona que la escribió, el caso se queda y se elimina todo vínculo con ella: el
run, la conversación y el mensaje de los que procede, y quién lo añadió si era
la persona borrada. Lo que queda es el texto, que puede seguir conteniendo datos
personales que alguien escribió y que solo desaparece al eliminar el caso.
Consulta [Protección de datos](data-protection.md#what-deletion-reaches).

Una puntuación se conserva de la misma forma. Cuando se elimina el run que
puntuó, la puntuación se queda sin el vínculo con él, y cuando se borra a la
persona que la pidió o la decidió, su nombre se quita de ella. El motivo de un
juez puede citar la respuesta que calificó.
