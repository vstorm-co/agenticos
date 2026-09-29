---
source_sha: "7bf230937988"
---

# Workflows { #workflows }

Un **workflow** encadena pasos en una automatización que llevan a cabo tus agents:
leer una [tabla](virtual-tables.md), llamar a un agent, ramificar según el
resultado, iterar sobre una lista. Lo construyes en un lienzo, conectas los pasos
entre sí y lo publicas como una versión inmutable — la misma forma que tiene un
[agent](concepts.md): un draft que editas y una versión publicada que se ejecuta.

Esta página describe el editor visual: la lista, el lienzo y el selector de pasos, cómo se
configura un nodo, el autoguardado y la publicación, y las rutas de teclado por todo
ello. El editor está en **Workflows** en la consola. La página de **lista** de
Workflows tiene un **"?"** que reproduce un recorrido por esa lista; el editor en
sí no tiene recorrido.

## Crear y duplicar un workflow { #creating-and-duplicating-a-workflow }

**New workflow** abre un diálogo que te deja empezar desde un trigger o desde una
plantilla. **How does it start?** ofrece seis triggers - **Manual**, **API request**,
**Chat message**, **Webhook**, **Schedule** y **New table record** -, cada uno un
lienzo por lo demás vacío que empieza por él. Las plantillas son puntos de partida
listos — **Starter**, un único paso para
renombrar y conectar, y **Two-step sequence**, dos pasos ya conectados para un flujo
lineal. Elige una con **Use** y aterrizas en el editor.

La lista muestra cada workflow que puedes ver como una tarjeta: su estado, quién
puede alcanzarlo, si tiene una versión en vivo y cuándo se editó por última vez.
**Filter by status** la acota a los **Drafts** que aún estás construyendo, los
**Published** que se ejecutan o los **Archived**. Desde una tarjeta abres el editor,
los runs del workflow o una copia.

**Duplicate** copia el draft actual de un workflow en uno nuevo llamado *{name}
(copy)*. Un duplicado es un workflow nuevo con su propio draft, nunca una copia de una
versión publicada.

!!! info "Una lista vacía puede ser un filtro, no una organización vacía"

    **No workflows yet** y **Nothing matches** son estados distintos: el primero es
    una organización sin ninguno, el segundo un filtro de estado bajo el que no cae
    ninguna fila. **Clear filter** devuelve la lista completa. Un workflow compartido
    contigo aparece en la misma lista en cuanto tienes `workflows:view`.

## El lienzo y cómo añadir pasos { #the-canvas-and-the-palette }

El **lienzo** es donde aparecen los pasos y las conexiones de un workflow, y tiene
todo el ancho del editor bajo la cabecera. Un **nodo** es un paso; una **arista** es
una conexión que fija el orden: el paso al que apunta se ejecuta después del paso del
que sale.

Cada nodo es una tarjeta con el icono del paso, su nombre y una línea debajo: lo que
está configurado para hacer - una condición, una URL, el número de campos mapeados -
o si no, el grupo al que pertenece, como **Slack** o **Tables**. Un paso con más de una
salida nombra sus puertos: **true** y **false**, **Each item** y **Done**, y un
puerto **Error** rojo en un paso que gestiona sus errores. Un paso que bloquea la
publicación lleva una marca roja. Un trackpad o la rueda del ratón mueve el lienzo, y
un pellizco - o Ctrl o Cmd con la rueda - lo amplía; sus controles están en la esquina.

Los pasos se eligen en el **selector de pasos**. Muestra secciones - **Start**, **AI**,
**Flow**, **Data**, **Apps and the web** - con sus grupos debajo. Un grupo como
**Slack**, **Tables** o **Jev decisions** se abre a sus pasos, y un grupo de un solo
paso es ese paso. **Search steps** encuentra cualquier paso por su nombre, por lo que
hace o por su grupo. Añades un paso de cuatro maneras:

- **+** arriba a la izquierda del lienzo - o **Add step** en el centro de un lienzo
  vacío - abre el selector. El paso va tras el paso seleccionado, o al final del flujo
  a la vista, conectado a él cuando sus puertos encajan. Un paso de inicio va en
  cambio antes del inicio actual y pasa a serlo.
- **+** junto a la salida de un paso abre el selector para el paso que va tras esa
  salida.
- **Clic derecho** en el lienzo: **Add a step here** muestra las mismas secciones y
  grupos, y el paso aparece donde hiciste clic.
- **Arrastra** un paso desde el selector para dejarlo donde lo sueltes, sin conectar.

Un paso nuevo nunca cae encima de otro, queda seleccionado, abre sus ajustes cuando
tiene alguno, y el lienzo se desplaza hasta él cuando queda fuera de la vista. Dentro
del cuerpo de un bucle cada paso nuevo se conecta al cuerpo, así que se queda ahí. El
selector muestra lo que es válido donde estás: **Loop item** y **Loop result** solo
dentro del cuerpo de un bucle, y un bucle mientras los bucles no estén anidados tan
hondo como permite la publicación.

Un clic derecho en un paso ofrece **Open settings**, **Duplicate** y **Delete step**; un
clic derecho en el lienzo ofrece además **Paste**, **Undo**, **Redo** y **Fit to
view**. Con varios pasos seleccionados, una barra abajo los borra juntos.

!!! note "El catálogo de pasos crece con el tiempo"

    El selector se alimenta de los nodos registrados en el despliegue, no de una lista
    fija. Un tipo de nodo registrado más tarde aparece en él en cuanto se registra, sin
    cambiar un workflow que ya construiste.

## Configurar un nodo { #configuring-a-node }

Qué hace cada nodo, con qué se configura y qué significan sus fallos está en la
[referencia de nodos](reference/workflow-nodes.md).

Haz clic en un paso y sus ajustes se abren en un diálogo sobre el lienzo: su nombre,
qué hace y cualquier problema que bloquee la publicación, encima de sus campos. Cada
cambio se guarda en el draft al hacerlo, así que **Done** solo cierra el diálogo y
**Delete step** quita el paso. Los campos se dividen en dos secciones.
**Configuration** guarda los ajustes estáticos — las elecciones fijas que no cambian de
una ejecución a otra, incluidos los recursos a los que está fijado un paso. **Inputs**
guarda los valores que un paso lee al ejecutarse.

Un input se rellena de una de dos maneras, y **Value** y **From a step** junto a su
etiqueta alternan entre ellas:

- **Un valor** — lo escribes directamente en el campo, con el mismo control que pide el
  tipo del campo.
- **From a step** — lees el valor de la salida de otro paso. El campo se convierte en
  un selector **Source** cuyas opciones son las salidas previas realmente alcanzables
  aquí y de tipo compatible — la salida entera de un paso o un campo dentro de ella —,
  cada una mostrada como *{node} · {port} ({type})*, o *{node} · {port} → {field}
  ({type})* para un campo. Un campo sin nada compatible antes dice **No compatible
  upstream outputs** en lugar de ofrecer una elección inválida.

Un input obligatorio sin valor es un problema de validación, señalado en el nodo y no
rellenado con un valor por defecto silencioso. Algunos campos guardan valores
estructurados: una lista de filas a la que **Add row** añade, que reordenas y de la
que quitas, o una elección tipada que cambia el subformulario de debajo. El diálogo
entra en ellos en lugar de mandarte a otra pantalla.

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

### Cuando un paso es lento o falla { #when-a-step-is-slow-or-fails }

Bajo los campos de un paso, **When it is slow or fails** fija su política. **Handle
errors** da al paso un puerto **Error**: un fallo que sus reintentos no resolvieron
sale por él, hacia un paso **Handle error** o lo que conectes, en lugar de hacer
fallar el run. **Tries** es cuántas veces se intenta el paso en total, y **Wait
between tries** y **First wait** fijan la pausa entre intentos. Un paso cuya llamada
no es seguro repetir, como ejecutar un agent, lo dice y nunca se reintenta. **Time
limit** corta una llamada tras esos segundos. Qué hace cada ajuste durante el run
está en la [referencia de nodos](reference/workflow-nodes.md#error-handling).

Un binding a un valor sin forma declarada - el elemento actual de un bucle, el
payload de un trigger - ofrece bajo la fuente un campo **Field inside it**, donde
escribes la ruta dentro de ese valor, como `record_id` o `fields.Email`. El run
comprueba esa ruta cuando el paso se despacha, porque solo el run sabe qué contiene
el valor.

## Conexiones y scope de foreach { #connections-and-foreach-scope }

Dibujas una arista conectando el puerto de salida de un nodo con el puerto de entrada
de otro nodo. El editor rechaza una conexión entre puertos que llevan formas distintas
antes de dibujarla, así que un cable incompatible nunca aterriza en el lienzo.

Una arista fija el orden en que se ejecutan los pasos; no mueve ningún dato. Los valores
que lee un paso son sus **bindings**, descritos en [Configurar un nodo](#configuring-a-node).

Para que un cable no te deje enlazando cada campo a mano, conectar dos puertos que llevan
exactamente la misma forma — la salida de un Echo con la entrada de un Relay, por ejemplo —
también enlaza cada input del destino con el campo del mismo nombre de la fuente. Un campo
que ya habías enlazado se deja como está.

Cuando las formas difieren, o un puerto no lleva
datos, no se enlaza nada y eliges cada fuente tú mismo con **From a step**. Undo (`Ctrl`/`Cmd` + `Z`) deshace la
conexión junto con sus bindings, y borrar una arista más tarde deja sus bindings donde
estaban, así que quítalos o vuelve a enlazarlos en los ajustes del paso.

Para borrar una conexión, selecciónala: haz clic en el cable y se dibuja más grueso y aparece sobre él un botón **Delete connection**. Pulsa el botón o `Backspace` y la conexión desaparece, mientras los dos
pasos se quedan. Las conexiones de una versión publicada no se pueden seleccionar, así
que no se pueden borrar.

Un paso **For each** ejecuta su cuerpo una vez por cada elemento de una lista. El
cuerpo no es un documento aparte - es parte del mismo grafo plano, mostrado por su
cuenta. **Edit loop body** en el paso, que dice cuántos pasos contiene el cuerpo,
entra en esa vista, y las migas **Workflow scope** en la esquina del lienzo muestran
dónde estás, desde **Workflow** hasta el bucle que abriste. Cada miga vuelve hacia
fuera.

Un cuerpo empieza en **Loop item**, al que se conecta el puerto **Each item**
del bucle, y termina en **Loop result**; nada en él vuelve al bucle, que continúa por
**Done** cuando cada elemento ha pasado por el cuerpo. El selector de pasos y las fuentes de binding siguen el scope en el que estás, y un paso del cuerpo puede leer cualquier
cosa que se ejecutara antes del bucle. Qué hace el bucle está en la
[referencia de nodos](reference/workflow-nodes.md#loops).

## Retroalimentación de validación { #validation-feedback }

El editor comprueba el grafo mientras editas y muestra qué está mal donde está mal. Cada paso con un problema lleva una marca roja en el lienzo y un recuento en sus ajustes, y un campo con un problema muestra su mensaje inline. El estado arriba a la derecha del lienzo dice **Ready to publish** o cuenta los problemas y los lista, cada uno bajo el nombre de su paso y su campo; elegir uno abre los ajustes de ese paso.

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
cualquier versión publicada, así que lo sigues editando enseguida. **History** en la
cabecera del editor abre cada versión publicada con su release note. **View** abre
una versión anterior en solo lectura - una versión publicada es de solo lectura, y
para hacer cambios sigues editando el draft.

Para volver a una versión publicada, ábrela con **View** y elige **Restore to
draft**. Tras confirmarlo, el draft toma el grafo de esa versión, y lo que no estaba
publicado en el draft se descarta. La versión en sí no cambia, y no se publica nada
hasta que vuelvas a publicar el draft. Deshacer empieza de nuevo desde el grafo
restaurado. Si alguien cambió el draft desde que lo abriste, la restauración se
rechaza con el mismo banner de conflicto que muestra un guardado, en vez de
descartar su cambio. Restaurar requiere `workflows:edit` sobre el workflow, y un
workflow archivado no se puede restaurar. Cada restauración queda en el
[registro de auditoría](governance.md) como `workflow.version_restored`.

## Ejecutar un workflow { #running-a-workflow }

**Run**, en la cabecera del editor, prueba el draft al momento - `Ctrl`/`Cmd` +
`Enter` también -, pidiendo antes los campos que declara un trigger Manual o API. El
run aparece luego en el lienzo mientras ocurre: cada paso toma su estado, sus
intentos y su error, y una barra abajo dice cómo va el run, con **Open run** para su
página. La siguiente edición lo oculta. **Run** espera mientras un cambio se sigue
guardando, y dice por qué no puede ejecutarse mientras el draft tenga problemas.

**Runs** en la cabecera del editor, y el icono de runs en la tarjeta de un
workflow, abren sus runs, del más reciente al más antiguo, cada uno con su estado, si
ejecutó el draft o la versión publicada, qué lo inició, cuándo, cuánto duró y cuánto
costó. **Start a run** inicia uno a mano: **Test the draft** ejecuta el draft tal
como está, y **Published version** ejecuta la versión en vivo. Su **Input (JSON)** es
lo que el paso **Input** del workflow entrega como `payload`.

Un run se abre con su duración, su coste y cuántos pasos dio, y luego con el error
con el que terminó, si lo hubo. Junto a ellos está el grafo que ejecutó, con cada
paso marcado por lo que el run hizo con él, sus intentos y su error, y los pasos a los
que nunca llegó atenuados. **Open loop body** muestra las iteraciones de un bucle de
la misma manera.

La salida del run y cada paso que dio, iteración a iteración, están
al lado. Un run en curso se actualiza cada par de segundos, y **Cancel run** lo
detiene. Sus **Files** listan lo que guardaron sus pasos - una descarga, una página
renderizada, la salida de un script -, cada uno descargable.

## Iniciar un workflow desde fuera de la consola { #starting-a-workflow-from-outside-the-console }

Un workflow empieza por un **trigger**, el primer nodo de su lienzo. El grupo
**Triggers**, arriba en el selector de pasos, tiene seis: **Manual**, **API request**, **Chat message**,
**Webhook**, **Schedule** y **New table record**. Añadir uno a un workflow que ya
tiene trigger sustituye el anterior en su mismo sitio, y las conexiones y los
bindings que salían del anterior salen del nuevo. **New workflow** empieza un
workflow por el trigger que elijas ahí.

Publicar una versión es lo que enciende su trigger. Un webhook, una programación y un
trigger de tabla ejecutan entonces esa versión como el miembro que la publicó, y la
siguiente publicación los pasa a la nueva versión. Una publicación que empieza por
otro trigger apaga el anterior. **Trigger**, en la cabecera del editor, muestra el
trigger en vivo y su estado, y avisa cuando el draft empieza de otra forma.

Una versión que empieza por **Manual** o **API request**, o sin ningún trigger, la inicia quien
pueda ejecutarla, como sí mismo: **Start a run** en Runs, la
[API HTTP](api.md#running-a-workflow) o un WebSocket. Cada run se comprueba, factura y
audita como uno iniciado aquí. Esas vías no inician ningún otro trigger, y cada otro
trigger tiene la suya. Un run de prueba del draft acepta cualquier trigger, y **Start
a run** lo abre con una entrada con la forma de ese trigger.

**Manual** es el trigger que una persona inicia con **Run**; **API request** es el que llama un sistema, y **Trigger** muestra su endpoint y una petición de ejemplo. Dale a cualquiera de los dos **campos de entrada** y un run pide lo que necesita: **Run** y **Start a run** muestran un formulario con una casilla por campo en lugar
del JSON, con el tipo del campo, y una llamada a la API cuya entrada no encaja se
rechaza con los campos que están mal. Consulta
[core.input](reference/workflow-nodes.md#core-input).

### Desde el chat { #from-the-chat }

El selector del chat de quién responde enumera, debajo de los agentes, los workflows
publicados que empiezan por **Chat message**. Con uno elegido, cada mensaje inicia un
run de él, y el trigger pasa a los pasos siguientes el mensaje como `prompt`, con el
`conversation_id` y el `user_id` de quien lo envió. El hilo muestra una tarjeta con el
estado del run y un enlace a sus pasos, y la respuesta del workflow la sigue cuando el
run termina.

La respuesta se escribe en la conversación cuando el run termina, siga el chat abierto
o no, así que al volver a abrir la conversación se lee de nuevo. Un run escribe en la
conversación desde la que se inició y en ninguna otra parte: llegar a cualquier otra
persona requiere un paso HTTP o de notificación en el grafo.

### Por un WebSocket { #over-a-websocket }

`/api/v1/ws/workflow-runs` inicia un run y transmite sus eventos, o sigue uno que ya
está en marcha. Un cliente que perdió la conexión se reconecta con el cursor del
último evento que vio y retoma exactamente donde lo dejó. Los eventos se escriben
antes de enviarse, así que nada se pierde y nada se ejecuta dos veces. El socket
vuelve a comprobar la sesión y el acceso del miembro antes de cada frame y de cada
lectura del flujo. Los frames están en [La API HTTP](api.md#following-a-run-over-a-websocket).

### Un webhook o una programación { #a-webhook-or-a-schedule }

Un trigger **Webhook** recibe su dirección y su **signing secret** la primera vez que
se publica una versión que lo tiene. La publicación muestra el secreto una vez, y las
publicaciones posteriores del mismo nodo conservan ambos; un nodo de webhook borrado y
añadido de nuevo recibe una dirección nueva.

El remitente firma con el secreto el
cuerpo exacto de la petición, HMAC-SHA256 en `X-Signature-256`, y nombra cada entrega
en `X-Delivery-Id`; las cabeceras propias de GitHub también funcionan. El trigger pasa
el JSON de la entrega como `body`, con su `delivery_id`. Un reintento que repite un id
recibe como respuesta el primer run y no inicia nada, porque el id se guarda junto con
el run que admitió, en una sola transacción.

Un trigger **Schedule** se ejecuta cada cierto tiempo, a diario a una hora fija o
según una expresión cron, todo en UTC y como mucho una vez por minuto. Su **Input** es
aquello con lo que empieza cada run, pasado como `input` junto al `fired_at` del tic.
Un tic que encuentra el último run aún en marcha se omite en lugar de apilar un
segundo run detrás, y un tic que la cuota de admisión rechaza espera al siguiente.

Los dos se ejecutan como el miembro que publicó la versión, y su acceso se comprueba
de nuevo en cada disparo. Un webhook cuyo miembro ya no puede ejecutar el workflow
rechaza sus entregas, y una programación así se desactiva y queda registrada en el
registro de auditoría. **Pause**, en la hoja **Trigger**, detiene cualquiera de los
dos sin publicar, y **New secret** sustituye el secreto de un webhook; el anterior
deja de verificarse al instante.

### Cuando se añade un registro a una tabla { #when-a-table-record-is-added }

Un trigger **New table record** nombra una tabla y filtra cada registro tal como se
añadió: desde la consola, la API, un agent o el paso de tabla de otro workflow. Pasa
el registro: su `record_id`, sus `values` por id de columna, los mismos valores como
`fields` por etiqueta y el `author_id` de quien lo añadió. Publicarlo requiere acceso
de lectura a la tabla, y un registro añadido antes de la publicación nunca lo inicia.
Un run iniciado así lleva la cadena de triggers por la que pasó, así que un workflow
que vuelve a escribir en la tabla cuyo trigger lo inició se bloquea en lugar de entrar
en bucle.

**Triggers**, en la propia tabla, enumera los workflows que empiezan por ella, los
pausa y reanuda, y muestra lo que cada uno decidió sobre cada registro. Consulta
[Virtual Tables](virtual-tables.md#triggers).

## Cuando algo sale mal { #when-something-goes-wrong }

**Lo que promete un run.** El resultado de un paso y el envío de los pasos siguientes se
guardan juntos, así que un worker que se detiene entre pasos no pierde nada: otro retoma
el run donde estaba. Un worker que se detiene dentro de un paso deja un intento cuyo
final nadie vio. Un paso que se puede repetir sin riesgo se vuelve a intentar. Una
escritura en una tabla repite su primera escritura a través de su recibo en lugar de
escribir dos veces, y una notificación se envía una vez. Un paso que puede haber
actuado ya en otro sitio y no promete nada más - ejecutar un agent es uno - nunca se
repite por sí solo: el run se detiene como **Needs attention**, para no pagar un modelo
dos veces ni enviar un mensaje dos veces sin que nadie lo decida.

Nada más ocurre exactamente una vez. Una llamada HTTP, una subida o una escritura de
archivo pueden repetirse tras una detención así, de modo que un sistema receptor que no
debe ver una petición dos veces necesita su propia clave de idempotencia. La promesa de
reintento de cada paso está en la [referencia de nodos](reference/workflow-nodes.md).

| Lo que ves | Por qué | Qué hacer |
|---|---|---|
| **Needs attention** | Se interrumpió un paso que pudo haber actuado | Comprueba si su efecto ocurrió y, si no, cancela el run e inicia uno nuevo. Reanudarlo desde la consola aún no está construido |
| `PRINCIPAL_REVOKED` | El miembro con el que actúa el run perdió el acceso o su cuenta se desactivó | Que un miembro que pueda ejecutar el workflow lo vuelva a publicar, para que su trigger se ejecute como él |
| `WORKFLOW_TRIGGER_MISMATCH` | El run se pidió por una vía que no es su trigger en vivo: a mano o por la API para un workflow que empieza por un webhook, o en el chat para uno que no empieza por un mensaje del chat | Inícialo como dice su trigger, o prueba el draft, que acepta cualquier trigger |
| `INVALID_BINDING` | Un valor no encajaba en el campo al que estaba enlazado | El error del paso nombra el campo; corrige el enlace o el valor anterior |
| `REVISION_CONFLICT` | Alguien cambió un registro después de que el paso lo leyera | Encamina el error del paso con `error.handle` hacia una lectura nueva |
| El historial de un trigger de tabla dice **Blocked** | El run se habría iniciado a sí mismo de nuevo, o su cadena llegó demasiado hondo | Consulta [Triggers](virtual-tables.md#triggers) |
| Un webhook responde `403` | La firma no coincide con el cuerpo, o el miembro con el que se ejecuta ya no puede ejecutar el workflow | Firma exactamente los bytes enviados con el secreto actual, o que un miembro que pueda ejecutarlo lo vuelva a publicar |

## Teclado y accesibilidad { #keyboard-and-accessibility }

Cada parte del editor tiene una ruta que no necesita puntero. El selector de pasos es una lista que recorres con las flechas y de la que eliges con Enter, cada control de solo icono lleva una etiqueta
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

Copiar y pegar tienen tres límites:

- **Un paso con bindings lee de donde leía.** Un paso copiado conserva sus bindings.
  Uno que lee de un paso que no copiaste sigue leyendo del original, pero nada conecta
  el paso pegado con él, así que no valida hasta que los conectes. Selecciona ambos
  pasos para copiar el par, y la copia leerá de su propio paso anterior.
- **Una conexión viaja solo con sus dos pasos.** Seleccionar solo una conexión y copiar
  no hace nada.
- **Los atajos pertenecen al lienzo.** Funcionan mientras el foco está en el lienzo, y
  hacer clic en cualquier parte de él — un paso, el lienzo vacío, una conexión — lo
  mantiene ahí. Con el foco en los ajustes de un paso o en el selector de pasos, las teclas son de
  esos campos, así que haz clic en el lienzo antes de pulsarlas.

## Resumen { #recap }

- Un workflow es **un draft que editas y una versión publicada e inmutable que se
  ejecuta** — empieza uno desde un trigger o una plantilla, y **Duplicate** copia un
  draft en un workflow nuevo.
- El **selector de pasos** añade pasos - desde **+**, la salida de un paso o un clic derecho; el **lienzo** los conecta y rechaza
  una conexión entre puertos incompatibles.
- Una arista fija el **orden** y los bindings llevan los **valores**; conectar puertos
  de la misma forma crea los bindings por ti.
- Los inputs de un nodo son **un valor o un binding** — **From a step** lee un valor de una
  salida previa alcanzable y de tipo compatible.
- El draft **se guarda solo**, y una edición desde dos sitios levanta un banner con
  **Overwrite** o **Reload**.
- **Publish** se bloquea mientras un problema persiste y vuelve a validar en el
  servidor; las versiones anteriores quedan visibles en solo lectura, y **Restore to
  draft** vuelve a convertir una de ellas en el draft.
- Cada acción tiene una **ruta de teclado**, y los atajos de edición son inertes en una
  versión publicada de solo lectura.
- Un workflow empieza por un nodo **trigger** - a mano o por la API, un mensaje del
  chat, un **webhook** firmado, una **programación** o un registro nuevo de tabla -,
  y **publicar** lo enciende, ejecutándose como el miembro que publicó.
- La **política** de un paso fija sus intentos, su límite de tiempo y si sus fallos
  salen por un puerto **Error**; el cuerpo de un paso **For each** se ejecuta de
  **Loop item** a **Loop result** una vez por elemento.
- **Runs** enumera cada run, **Start a run** prueba el draft o ejecuta la versión
  publicada, y un run muestra su grafo paso a paso tal como ocurrió.
