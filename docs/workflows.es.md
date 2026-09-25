---
source_sha: "d22d5fce4b79"
---

# Workflows { #workflows }

Un **workflow** encadena pasos en una automatización que llevan a cabo tus agents:
leer una [tabla](virtual-tables.md), llamar a un agent, ramificar según el
resultado, iterar sobre una lista. Lo construyes en un lienzo, conectas los pasos
entre sí y lo publicas como una versión inmutable — la misma forma que tiene un
[agent](concepts.md): un draft que editas y una versión publicada que se ejecuta.

Esta página describe el editor visual: la lista, el lienzo y la paleta, cómo se
configura un nodo, el autoguardado y la publicación, y las rutas de teclado por todo
ello. El editor está en **Workflows** en la consola. La página de **lista** de
Workflows tiene un **"?"** que reproduce un recorrido por esa lista; el editor en
sí no tiene recorrido.

## Crear y duplicar un workflow { #creating-and-duplicating-a-workflow }

**New workflow** abre un diálogo que te deja empezar desde un lienzo en blanco o
desde una plantilla. **Blank workflow** es un lienzo vacío para construir desde cero.
Las plantillas son puntos de partida listos — **Starter**, un único paso para
renombrar y conectar, y **Two-step sequence**, dos pasos ya conectados para un flujo
lineal. Elige una con **Use** y aterrizas en el editor.

La lista agrupa cada workflow que puedes ver por estado — **Drafts** que aún estás
construyendo, las versiones **Published** que se ejecutan y los **Archived** — y
**Filter by status** acota a uno. El badge de cada fila muestra **Draft**,
**Published** o **Archived**.

**Duplicate** copia el draft actual de un workflow en uno nuevo llamado *{name}
(copy)*. Un duplicado es un workflow nuevo con su propio draft, nunca una copia de una
versión publicada.

!!! info "Una lista vacía puede ser un filtro, no una organización vacía"

    **No workflows yet** y **Nothing matches** son estados distintos: el primero es
    una organización sin ninguno, el segundo un filtro de estado bajo el que no cae
    ninguna fila. **Clear filter** devuelve la lista completa. Un workflow compartido
    contigo aparece en la misma lista en cuanto tienes `workflows:view`.

## El lienzo y la paleta { #the-canvas-and-the-palette }

El **lienzo** es donde aparecen los pasos y las conexiones de un workflow. Un **nodo**
es un paso; una **arista** es una conexión que lleva la salida de un paso al
siguiente. El lienzo se desplaza y hace zoom, y sus controles están en la esquina —
no hay minimapa.

La paleta **Nodes** al lado enumera los tipos de nodo que tu deployment ha
registrado, agrupados por categoría, cada uno con icono, nombre y descripción.
**Search nodes** filtra la lista. Añades un paso de dos maneras:

- **Arrastra** un nodo desde la paleta al lienzo — la ruta del puntero.
- **Haz clic** en un nodo para añadirlo cerca del centro de la vista — la ruta de
  teclado y táctil, que no necesita arrastrar.

La paleta muestra lo que es válido donde estás. Dentro del cuerpo de un bucle oculta
las clases de nodo que no pueden vivir ahí, así que la lista que ves siempre se puede
añadir en el scope que estás editando.

!!! note "El catálogo de nodos crece con el tiempo"

    La paleta se nutre de los nodos registrados del deployment, no de una lista fija.
    Al principio el catálogo es pequeño; más clases de nodo — llamar a un agent, leer
    y escribir una tabla, ramificar y hacer bucles — llegan a medida que milestones
    posteriores los registran, y aparecen en la paleta en el momento en que lo hacen,
    sin cambio alguno en un workflow que ya construiste.

## Configurar un nodo { #configuring-a-node }

Selecciona un nodo y el panel **Properties** se abre a la derecha. Sus campos caen en
dos secciones. **Configuration** contiene ajustes estáticos — las opciones fijas que
no cambian de un run al siguiente, incluidos los recursos a los que un paso está
fijado. **Inputs** contiene los valores que un paso lee cuando se ejecuta.

Un input se rellena de una de dos maneras, y el conmutador **Bind** junto al campo
alterna entre ellas:

- **Un literal** — escribes el valor directamente en el campo, con el mismo control
  que exige el tipo del campo.
- **Un binding** — lees el valor de la salida de otro paso. **Bind** convierte el
  campo en un selector **Source** cuyas opciones son las salidas previas realmente
  alcanzables aquí y que llevan un tipo compatible, cada una mostrada como *{node} ·
  {port} ({type})*. Un campo sin nada compatible antes dice **No compatible upstream
  outputs**, en vez de ofrecer una elección no válida.

Un input obligatorio sin valor es un problema de validación, señalado en el nodo y no
rellenado con un valor por defecto silencioso. Algunos campos contienen valores
estructurados: una lista de filas a la que añades con **Add row**, reordenas y quitas,
o una elección tipada que intercambia el sub-formulario de debajo. El panel desciende
recursivamente en ellos, en vez de enviarte a una pantalla aparte.

Selecciona más de un nodo y el panel informa de cuántos están seleccionados;
selecciona una arista y muestra el **From** y el **To** de la conexión.

### Selectores de recursos { #resource-pickers }

Un ajuste que fija un recurso abre un selector en vez de un campo de texto libre, para
que un paso nombre algo real que tu organización tiene:

| Selector | Qué fija |
|---|---|
| **Agent** y **Version** | Un agent, y luego una de sus versiones publicadas. Cambiar el agent borra la versión fijada, porque una versión pertenece a un agent |
| **Table** y **Columns** | Una [Virtual Table](virtual-tables.md), y luego las columnas que el paso lee — acotadas al esquema actual de esa tabla |
| **Secret** | Un secreto del [vault](secrets.md), por referencia. Un paso guarda la id del secreto, nunca su valor |

Cada selector desambigua filas con el mismo nombre mediante contexto y marca una
referencia cuyo destino ha desaparecido. Los selectores **Agent** y **Secret**
ofrecen además un enlace para crear uno nuevo — siempre, no solo cuando la lista
está vacía — mientras que el selector **Table** no tiene ninguno. Una tabla cuyo esquema cambió desde que se vinculó lo dice y
ofrece **Rebind to the current schema**, para que un conjunto de columnas obsoleto sea
un aviso visible y no una ruptura silenciosa.

## Conexiones y scope de foreach { #connections-and-foreach-scope }

Dibujas una arista conectando el puerto de salida de un nodo con el puerto de entrada
de otro nodo. El editor rechaza una conexión entre puertos que llevan formas distintas
antes de dibujarla, así que un cable incompatible nunca aterriza en el lienzo.

Un paso `foreach` ejecuta su cuerpo una vez por cada elemento de una lista. El cuerpo
no es un documento aparte — es parte del mismo grafo plano, mostrado por sí solo.
**Open body** en el paso entra en esa vista, y las migas **Workflow scope** muestran
dónde estás, desde **Workflow** en la raíz hasta el bucle que abriste. Cada miga
navega de vuelta hacia fuera. La paleta y las fuentes de binding siguen el scope en el
que estás, así que lo que puedes añadir y de dónde puedes leer son siempre los válidos
en ese nivel.

## Retroalimentación de validación { #validation-feedback }

El editor comprueba el grafo mientras editas y muestra qué está mal donde está mal. Un
nodo seleccionado con un problema lleva un badge que cuenta sus problemas en la
cabecera del panel; un campo con un problema muestra su mensaje inline; y una lista
plegable al pie del panel reúne los problemas, de modo que cada uno enlaza con el nodo
o el campo del que trata.

Los mensajes nombran el fallo concreto: un input obligatorio sin valor, un input
puesto por más de una fuente, una conexión cuyos puertos llevan formas distintas, un
paso que no se puede alcanzar desde el inicio, un bucle de vuelta a un paso anterior,
un valor que lee un paso que no se ha ejecutado en todos los caminos que llegan aquí,
o una conexión que cruza hacia dentro o hacia fuera del cuerpo de un bucle.

!!! info "La comprobación del editor es una vista previa; la publicación es la autoridad"

    La validación en el editor es un espejo rápido de las reglas que el servidor
    impone. Existe para atrapar un problema mientras lo estás mirando, pero nunca es
    la última palabra: publicar vuelve a ejecutar la validación completa en el
    servidor, y un problema que el editor pasó por alto se muestra de la misma manera,
    contra el nodo o el campo al que pertenece.

## Autoguardado y el banner de conflicto de revisión { #autosave-and-the-revision-conflict-banner }

Tu draft se guarda solo. Una breve pausa después de que dejas de editar escribe el
grafo actual, y el estado junto a la cabecera lo refleja — **Unsaved changes**
mientras un guardado está pendiente, **Saving…** mientras se ejecuta, **Saved** una
vez que aterriza, y **Save failed — will retry** si no lo hizo.

Cada guardado se escribe contra la revisión que abriste, así que un draft editado en
dos sitios a la vez no puede sobrescribir en silencio. Cuando eso ocurre, el editor
levanta un banner titulado **This draft changed elsewhere**: *Someone edited this
workflow since you opened it. Overwrite keeps your changes; reload replaces them with
the latest saved draft.* Eliges:

- **Overwrite** — conserva tu versión y escríbela sobre la guardada en otro sitio.
- **Reload** — descarta tus ediciones sin guardar y toma el último draft guardado.

## Publicar una versión y el historial de versiones { #publishing-a-version-and-version-history }

**Publish** congela el draft actual como una versión inmutable que se ejecuta — una
versión nunca se cambia después de crearse. El diálogo de publicación toma una
**Release note** opcional que describe qué cambió. Si el grafo aún tiene problemas, la
publicación se bloquea con **Fix the problems below before publishing**, así que una
versión que no validaría nunca se crea.

Publicar no termina tu edición. El draft sigue existiendo con independencia de
cualquier versión publicada, así que lo sigues editando enseguida, y cada versión
publicada se lista bajo **Version history** con su release note. **View** abre una
versión anterior en solo lectura — una versión publicada es de solo lectura, y para
hacer cambios sigues editando el draft.

## Ejecutar un workflow { #running-a-workflow }

La pestaña **Runs** de un workflow es donde aparecerán sus runs de prueba y de
producción, paso a paso con sus inputs, salidas y costes. El historial de runs llega
en cuanto se lance el runner de workflows; hasta entonces la pestaña muestra que aún
no está disponible, y el editor sirve para construir y publicar.

## Teclado y accesibilidad { #keyboard-and-accessibility }

Cada parte del editor tiene una ruta que no necesita puntero. Hacer clic en un nodo de
la paleta lo añade sin arrastrar, cada control de solo icono lleva una etiqueta
hablada, y el lienzo toma el foco de teclado para que puedas tabular por sus pasos y
conexiones. Una conexión se puede hacer desde el teclado: empieza una en un nodo y
luego termínala en un destino compatible.

Los atajos del lienzo se disparan solo mientras el foco está dentro del editor, así
que nunca roban una tecla a un campo en otra parte de la página:

| Teclas | Hace |
|---|---|
| `Ctrl`/`Cmd` + `Z` | Deshacer |
| `Ctrl`/`Cmd` + `Shift` + `Z`, o `Ctrl`/`Cmd` + `Y` | Rehacer |
| `Ctrl`/`Cmd` + `C` | Copiar la selección |
| `Ctrl`/`Cmd` + `X` | Cortar la selección |
| `Ctrl`/`Cmd` + `V` | Pegar, desplazado para no cubrir el original |
| `Escape` | Cancelar una conexión en curso |

Un pegado obtiene ids nuevas y reasigna los bindings entre los pasos copiados, así que
los pasos pegados leen unos de otros y no de los originales. Cada atajo de edición es
inerte mientras ves una versión publicada, que es de solo lectura; `Escape` sigue
cancelando una conexión perdida.

## Resumen { #recap }

- Un workflow es **un draft que editas y una versión publicada e inmutable que se
  ejecuta** — empieza uno en blanco o desde una plantilla, y **Duplicate** copia un
  draft en un workflow nuevo.
- La **paleta** añade pasos por arrastre o clic; el **lienzo** los conecta y rechaza
  una conexión entre puertos incompatibles.
- Los inputs de un nodo son **un literal o un binding** — **Bind** lee un valor de una
  salida previa alcanzable y de tipo compatible.
- El draft **se guarda solo**, y una edición desde dos sitios levanta un banner con
  **Overwrite** o **Reload**.
- **Publish** se bloquea mientras un problema persiste y vuelve a validar en el
  servidor; las versiones anteriores quedan visibles en solo lectura.
- Cada acción tiene una **ruta de teclado**, y los atajos de edición son inertes en una
  versión publicada de solo lectura.
