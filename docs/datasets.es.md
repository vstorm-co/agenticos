---
source_sha: "698438cc9d00"
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
| Comprobaciones | Reglas sobre la respuesta, cada una un objeto cuyo `type` nombra la regla, con sus parámetros al lado. Un caso las guarda; la puntuación las lee y decide qué tipos existen |
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

Añadir, editar o eliminar un caso, importar un archivo y aceptar casos generados
crean cada uno una nueva **versión** del dataset, numerada desde 1. Una versión nunca cambia
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

### Generados por el generador de casos { #generating-cases }

Escribir cien buenos casos a mano es la razón por la que la mayoría de los
equipos no tiene ninguno. **Generar casos**, en la página de un dataset, pide al
generador de casos que los redacte, y tú decides cuáles conserva el dataset.
Elige el agent que prueban los casos, las fuentes y cuántos casos quieres: como
máximo 50, repartidos por igual entre las fuentes.

| Fuente | Qué redacta el generador | Qué se le muestra |
|---|---|---|
| Del agent | Peticiones típicas y casos límite, con las llamadas a herramientas que hace una buena respuesta | Las instrucciones del agent, sus skills y sus herramientas, con los nombres que el agent les da |
| Del conocimiento | Preguntas que responde su base de conocimiento. Cada caso enlaza con el documento del que procede su fragmento, guarda el fragmento como respuesta de referencia, espera una llamada a la búsqueda de conocimiento del agent y lleva una comprobación `judge` de que la respuesta concuerda con el fragmento | Fragmentos de hasta 12 documentos indexados de las bases de conocimiento que usa el agent y que tú puedes leer |
| De conversaciones | Paráfrasis y variantes más difíciles de lo que la gente preguntó al agent, primero las respuestas valoradas negativamente. Cada caso enlaza con la pregunta que varía | Hasta 60 preguntas que se hicieron al agent en esta organización, con el comentario dejado en una respuesta valorada negativamente |
| Red team | Peticiones fuera de su ámbito, inyecciones de prompt, intentos de obtener datos personales e intentos de saltarse las políticas del agent. Cada caso lleva las etiquetas `red-team` y `red-team:<categoría>` y una comprobación `judge` de que el agent se niega | Las instrucciones del agent, sus skills y sus herramientas |

**Primero, el coste estimado.** El diálogo muestra cuántos casos se pedirán a
cada fuente, de cuánto material dispone cada una y una estimación del coste,
antes de gastar nada. Es una estimación: el presupuesto del generador se
comprueba cuando se ejecuta, como el de cualquier agent. Cambiar el agent, las
fuentes o el número descarta la estimación.

**Nada llega al dataset hasta que lo aceptas.** Los borradores esperan en
**Casos propuestos**, en la página del dataset. Acepta uno tal cual, edítalo
antes o descártalo, de uno en uno o una página entera. Un Aceptar es una versión
nueva, lleve lo que lleve, y sus casos tienen la fuente `synthetic`. Un borrador
descartado se elimina y no deja nada en el dataset. Uno aceptado también
desaparece de los borradores: la versión es su registro.

**El generador es un agent.** Es un agent de sistema creado en cada
organización, así que sus runs cuentan contra su propio presupuesto y el de la
organización, y cada generación es un run que puedes abrir en
[Actividad](console.md). No tiene herramientas: todo lo que lee se reúne para él
con tus propios permisos y se le entrega en el prompt, de modo que un documento
o una conversación que intente darle instrucciones solo puede cambiar el texto
de un borrador que tú revisas. Un borrador que no cumple la regla de su fuente
(un caso de conocimiento sin un fragmento que se le mostró, un caso de
conversación sin una pregunta que se le mostró, un caso de red team sin
categoría) se descarta antes de que lo veas.

**Cada fuente tiene su propia barrera**, y una fuente que no puedes usar se
rechaza por su nombre en lugar de omitirse en silencio:

- toda generación necesita `datasets:edit` en el dataset, `agents:view` en el
  agent que se prueba y `agents:run` en el generador de casos, porque gasta el
  dinero de la organización;
- el conocimiento solo lee las bases de conocimiento que puedes leer; el diálogo
  dice cuántas de las del agent se dejaron fuera;
- las conversaciones necesitan `runs:view`, el permiso con el que Actividad lee
  cada run;
- una organización que ha desactivado la asistencia de IA no puede iniciar una
  generación. Los borradores que ya esperan se pueden seguir aceptando o
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

Un caso generado que aún espera una decisión no se conserva así. Cuando se
borra la conversación de la que se redactó, o se borra a la persona que hizo la
pregunta, el borrador se elimina con ella: nadie decidió conservarlo. Generar
desde conversaciones envía las preguntas que hizo la gente, con las credenciales
ocultas, al provider del modelo del generador de casos, y generar desde el
conocimiento envía fragmentos de los documentos; consulta
[qué sale del deployment](data-protection.md#what-leaves-the-deployment).
