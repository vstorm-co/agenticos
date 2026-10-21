---
source_sha: "3394e53d70df"
---

# Artefactos { #artifacts }

Un **artefacto** es una página que un agent ha publicado: un informe, un pequeño
dashboard, un resumen de una página que alguien abre en el navegador. Tiene un
enlace que no cambia cuando el agent vuelve a publicarla, así que «cada lunes,
publica las cifras de la semana en esta página» es un solo enlace que la gente
guarda en favoritos, en lugar de uno nuevo cada semana.

Un artefacto no es un archivo. Un gráfico, un PDF generado y un archivo del
workspace ya tienen su sitio en el chat y en el [workspace](sandbox.md). Un
artefacto es lo que se *sirve*: tiene un propietario, una visibilidad y grants
como un agent o un skill, y se le puede dar un enlace público para alguien sin
cuenta.

## Publicar uno { #publishing-one }

Activa la capability **Artifacts** para el agent. Añade cuatro herramientas:
`publish_artifact`, que el modelo llama cuando el resultado es algo que una
persona debería abrir en lugar de leerlo una vez en el chat; `read_artifact`,
que vuelve a leer una página publicada; `list_artifacts`, que nombra las páginas
que un run puede abrir; y `preview_artifact`, que dibuja una página y dice qué
falla en ella.

La página sale de uno de tres sitios:

- **Un archivo del workspace del agent**, terminado en `.html` o `.md`. Es el
  caso habitual para un agent con la capability [Archivos y shell](reference/capabilities.md#files-shell):
  escribe `report.html`, ejecuta lo que haga falta para construirlo y después
  publica el archivo. Los bytes se leen a través del propio backend de workspace
  del run, así que funciona con todos los backends de sandbox.
- **La página pasada en línea**, para un agent sin workspace o una página corta.
- **Cambios en la página ya publicada** con ese nombre: consulta más abajo.

El chat muestra una tarjeta para la página publicada. La tarjeta enlaza a la
versión que publicó *este* run, así que leer la conversación más tarde sigue
mostrando lo que se publicó en ella, no lo que la página muestra hoy.

### Cambiar parte de una página { #changing-part-of-a-page }

Cambiar una palabra no debería costar la página entera otra vez. El agent llama a
`read_artifact` con el nombre de la página, que devuelve la versión actual tal
como se escribió, y después a `publish_artifact` con el mismo nombre y `edits`:
reemplazos exactos, aplicados en orden. Cada uno debe coincidir con exactamente un
sitio de la página; uno que no coincide con ninguno o con varios vuelve al modelo
para que lo corrija. El resultado es una versión nueva como cualquier otra.

Los cambios llevan la versión sobre la que se hicieron. Si otro run publicó entre
medias, no se escribe nada y se le dice al modelo que vuelva a leer la página, así
que una copia editada de una página antigua nunca sustituye a una más nueva. Leer
sigue la misma regla que abrir la página en la consola: la persona por la que
actúa el run tiene que poder abrirla. Una página de más de 100.000 caracteres
vuelve cortada, y lo dice; un cambio puede seguir nombrando texto más allá del
corte.

### Volver a encontrar una página { #finding-a-page-again }

Cada mensaje es un run nuevo, y un run solo ve los turnos anteriores como texto,
así que el modelo no conserva los nombres con los que publicó. `list_artifacts`
enumera las páginas del agent en el entorno del run, de la más reciente a la más
antigua y como máximo 50: cada una con su nombre, título, versión actual,
formato, bindings en vivo, visibilidad, si tiene un enlace público activo, cuándo
se publicó, su enlace en la consola y `may_edit`, que indica si publicar con ese
nombre desde este run actualiza la página en lugar de ser rechazado. El modelo lo
consulta antes de elegir un nombre nuevo.

La lista se lee como la persona por la que actúa el run, con la regla de la
consola: sus propias páginas, las de la organización y las compartidas con ella,
o todas las páginas para un rol que ve todas. En un chat de grupo, el canal solo
ve las páginas de toda la organización: nunca las páginas privadas o de equipo de
quien habla, ni una página compartida solo con esa persona. Una superficie sin
nadie con sesión iniciada, como un widget público, no enumera nada.

## Datos en vivo { #live-data }

Una página puede mostrar registros de [Virtual Tables](virtual-tables.md) que se
mantienen al día, en lugar de la copia con la que se publicó. El agent pasa
`bindings` a `publish_artifact`: cada binding es un nombre, una [vista guardada](virtual-tables.md#saved-views)
y las columnas que la página lee de ella. `list_views` da al agent el id y las
columnas de cada vista. La página llama a `agenticos.onData(render)`, y
`render(data)` se ejecuta con los primeros datos y de nuevo en cada refresco.
`agenticos.data` es una Promise de los primeros datos.

```js
agenticos.onData((data) => {
  // data.tickets = { status, records, fields, count, truncated, limit, filters_dropped }
});
```

Cada binding llega como `status` (`ok` o `unavailable`), `records`
(`{id, <field>: value}`), `fields` (etiqueta, tipo, opciones y estado de cada uno),
`count`, `truncated`, `limit` y `filters_dropped`, que vale true cuando un filtro
de la vista apuntaba a una columna que ya no existe, de modo que los registros
abarcan más de lo que la vista pretendía.

Una página que no recibe respuesta en 10
segundos ve todos sus bindings `unavailable`; un listener añadido después de eso
pregunta una vez más.

Un binding es `unavailable` cuando este lector no puede leer su vista
o la vista ya no existe. Un campo cuya columna se eliminó se sirve con su nombre de
campo como campo `text` con valor `null` y estado `missing`; una columna archivada
da `null` con estado `archived`.

Los registros se leen **cuando alguien mira la página, con el acceso de ese
lector**, y nunca se guardan en ella. Dos personas que abren la misma página pueden
ver filas distintas. El resultado de la publicación enumera cada campo como
`Label (type)`, para que el agent compruebe que vinculó la columna que pretendía;
un binding que se arrastra sin cambios dice `kept`.

Una vista privada solo sirve a su propietario. Vincular una no impide publicar la
página, y el `warning` del resultado recibe una línea que dice que solo esa
persona ve sus registros hasta que la vista se comparta, y el agent se lo
comunica. Si un compañero los verá se decide donde se comparte la página:
consulta [Quién ve los registros de una página en vivo](#who-sees-a-live-pages-records).

La versión 3 del [kit de páginas](#the-library-set) dibuja un binding por el
agent: `AO.records("#tickets", data.tickets)` dentro de `agenticos.onData`
muestra los registros como una tabla con una cabecera formada por las etiquetas
de los campos, los números y las fechas alineados a la derecha, las opciones como
insignias y cada valor escrito como texto. Antes de los datos muestra una línea
de carga, y un binding `unavailable` o vacío, una lista cortada y un filtro
descartado reciben cada uno su propio mensaje. En la versión 3, `AO.onData` es la
misma llamada que `agenticos.onData`. Una página vinculada cuyo script nunca pide
sus datos se publica igualmente, con un [aviso](#the-page-contract-and-the-publish-warnings).

El nombre de un binding son letras minúsculas, dígitos y `_`. Un campo puede
llamarse como está rotulada su columna: palabras de letras en mayúsculas o
minúsculas, dígitos y `_`, separadas por un solo espacio, como `Status` o
`Created At`. Ambos tienen hasta 64 caracteres, y `__proto__`, `constructor` y
`prototype` están reservados para ambos (`id` también, para un campo). Una página
tiene como máximo 5 bindings, y un binding como máximo 50 campos.

### Lo que ve el lector { #what-the-viewer-sees }

Una página con bindings muestra una insignia **Live** en su tarjeta, en el widget
de artefactos del dashboard y en el visor. En el visor, su punto palpita mientras
llegan los datos y se vuelve ámbar cuando algunas fuentes no están disponibles para
este lector. Un lector que no puede leer ninguna no ve insignia alguna, y tampoco
la muestra una versión anterior.

El visor tiene **Refresh**, que vuelve a leer los datos y actualiza en el sitio una
página que usa `agenticos.onData`, con la hora de la última lectura en el tooltip
del botón. Junto a él hay un menú para refrescar automáticamente: Off, cada minuto, cada 5 o
15 minutos, o cada hora. Cada lector elige el suyo, y la elección se recuerda por
página en ese navegador.

El refresco automático no hace nada mientras la pestaña está oculta, y lee una vez
cuando la pestaña vuelve si se perdió un ciclo. Se detiene cuando los datos se
rechazan (la página ya no existe para este lector) y cuando no se puede leer
ninguna fuente de la página, hasta que el lector pulsa Refresh y una lectura
responde. Un fallo que no dice nada de la página, como un error del servidor, lo
mantiene consultando. Una respuesta de ocupado (429) se reintenta dos veces, con un
segundo entre medias, antes de decir al lector "Busy, try again in a moment."

Bajo la barra aparece una línea solo cuando algo requiere atención. Una página
rechazada dice "This page's live data is not available to you." Un lector cuyas
fuentes no se pueden leer ve cuántas ("2 of 3 sources unavailable to you"). Un
editor, es decir, cualquiera que pueda editar la página, ve además el motivo de
cada fuente (por ejemplo, que su vista guardada ya no existe, que su tabla está
archivada, que al agent no se le concedió la tabla o que no puedes leer su vista
guardada) con un enlace **Open the table** a la vista vinculada.

Cuando un agent publica una versión nueva mientras alguien tiene abierta la actual,
la siguiente lectura (un refresco, manual o automático) lleva al lector a la versión
nueva: la página se vuelve a cargar desde esa versión, con sus propios datos. Un
lector que eligió una versión en el menú de versiones se queda en ella.

En una versión anterior no se leen datos en vivo. El visor dice "Live data only on
the current version." con **Open current** y, para un editor, **Restore** para esa
versión. Restaurar una versión cuyas fuentes en vivo no están disponibles dice
cuáles.

### Límites { #limits }

Toda respuesta está acotada, así que una sola página no puede tumbar el despliegue:

| Límite | Valor |
|---|---|
| Bindings por página | 5 |
| Registros por binding | 1.000 |
| Datos ya formados por página | 4 MiB, repartidos equitativamente entre los bindings |
| Una consulta | como máximo 2 s |
| Una página | plazo de 5 s |
| Cargas de datos | 30 por minuto por lector, una en curso por lector y un tope por proceso |

Un binding cortado dice `truncated: true`, con `limit` a `records` o `bytes` y
`count` como el número de registros servidos. `bytes` cubre también una lectura
cuyo coste medido se agotó antes de que los datos formados llenaran la parte que le
corresponde de la página.

El plazo se cumple sin cancelar ninguna consulta: cada consulta dura como máximo lo
menor entre 2 s y lo que queda de los 5 s, y ninguna consulta empieza una vez
agotados los 5 s, así que una página responde en unos 5 s. Pasado un límite de
peticiones la ruta responde 429; la consola reintenta dos veces una respuesta de
ocupado. Con Redis caído, el suelo del límite de peticiones y el límite de cargas
en curso cuentan por worker de la API, y el tope por proceso sigue acotando cada
worker.

### Quién puede publicar una página vinculada { #who-may-publish-a-bound-page }

Una página se vincula a una tabla solo si el spec del agent que la publica concede
lectura sobre ella, y eso se comprueba al publicar la página o al restaurar una
versión. Revocar el grant más tarde no detiene las páginas ya publicadas, y cada
lector sigue leyendo solo lo que su propio acceso le permite.

Una página vinculada solo puede volver a publicarla un run que actúe en nombre de un
miembro: el miembro con sesión iniciada (chat web, API HTTP), un remitente de canal
vinculado o el creador de una programación. Un visitante de un widget, un embed o
una página alojada, un remitente de canal no vinculado y la entrega de un trigger de
eventos de un agent (GitHub, correo, relé de webhooks) no cuentan, ni tampoco un run
de workflow admitido por una puerta pública ni nada en la cadena de ese run.

## Un nombre, un enlace { #one-name-one-link }

La identidad de un artefacto es su **nombre dentro del agent**: `weekly-report`,
`churn-dashboard`. Publicar con el mismo nombre actualiza el mismo artefacto,
desde cualquier superficie: el chat, la API, un [trigger](triggers.md) o un
workflow. Un nombre nuevo crea una página nueva. El nombre admite letras
minúsculas, dígitos y guiones, hasta 64 caracteres.

El nombre también vale **dentro del entorno** desde el que respondió el run. Un
run en un [entorno](environments.md) con nombre — `staging`, `dev` — publica una
página propia junto a la del entorno por defecto, así que probar una versión nueva
de un agent no puede volver a publicar la página que los lectores de producción
tienen en favoritos. El entorno se lee del propio run, nunca del modelo, y la
lista y la página lo nombran.

El nombre lo comparten todos los que ejecutan el agent, pero la página no. Un run
vuelve a publicar un artefacto existente solo cuando la persona por la que actúa
es su propietaria o tiene `artifacts:edit` sobre él, por el rol o por un grant
`edit`: la misma regla que para gestionarlo en la consola. Al run de cualquier
otra persona se le dice que el nombre está ocupado y publica con otro, así que un
compañero que pida al mismo agent compartido un `weekly-report` no puede
sustituir la página que hay detrás de tu enlace.

Cada publicación es una **versión** nueva. No se sobrescribe nada, así que la
lista de versiones en la página del artefacto es su historial. Dos cosas mantienen
ese historial acotado:

- Publicar exactamente los bytes que ya contiene la versión actual no añade
  ninguna versión. El resultado dice `unchanged`, y una programación que no
  encontró nada nuevo deja el historial en paz. Aun así cuenta como publicación,
  así que el reloj de la retención vuelve a empezar.
- Solo se conservan las versiones más recientes, `ARTIFACT_MAX_VERSIONS` de
  ellas (20 por defecto). Una versión antigua se elimina cuando llega una nueva,
  salvo aquella a la que está fijado el enlace público. Una conversación que
  enlaza a una versión eliminada dice que esa versión ya no se conserva y ofrece
  la última.

**Restore this version** recupera una versión conservada. Un miembro que puede
editar la página abre la versión y la restaura; eso añade una versión nueva con
los bytes de la antigua, así que el historial conserva lo que pasó y la
restauración se puede deshacer de la misma manera. No se almacena nada nuevo.
Queda registrado en el registro de auditoría. La versión nueva dice de dónde
viene: la lista de versiones la muestra como `v4 · restored from v2`, y la API da
su número en `restored_from`, que una publicación deja vacío.

## Formatos admitidos { #supported-formats }

| Formato | Qué se guarda | Qué se sirve |
|---|---|---|
| HTML (`.html`, `.htm`, o `format: html`) | El documento tal como lo escribió el agent | El mismo documento, detrás de un script corto de la plataforma (consulta [Cómo se aísla la página](#how-the-page-is-isolated)) |
| Markdown (`.md`, `.markdown`, o `format: markdown`) | El código fuente Markdown | El código fuente renderizado en una página sencilla, tablas incluidas. El HTML en bruto que contenga se escapa |

Una versión es un único documento autocontenido de como máximo
`ARTIFACT_MAX_BYTES` (5 MiB por defecto). No hay paquetes de varios archivos:
incrusta tu propio script, tus estilos y las imágenes (como URI `data:`) en el
único archivo.

!!! warning "La página no tiene red"

    Los scripts se ejecutan, así que un gráfico dibujado por una librería
    funciona. Pero la página no puede cargar nada de ningún sitio ni enviar nada a
    ninguna parte: un script de una CDN, una fuente web desde una URL y una
    llamada a una API fallan todos. Las excepciones son el conjunto de bibliotecas
    de abajo, que el propio despliegue sirve, y los [datos en vivo](#live-data) que
    la consola entrega a una página que declaró bindings. La herramienta se lo dice
    al modelo. Es deliberado, y [Cómo se aísla la página](#how-the-page-is-isolated)
    explica por qué.

### El conjunto de bibliotecas { #the-library-set }

El despliegue sirve unos pocos archivos junto a cada página, para que el modelo
deje de pegar una librería de gráficos entera en cada una. Una página los carga
con una dirección relativa y sigue funcionando si el despliegue mueve más tarde su
contenido a otro origen:

| Dirección en la página | Qué es |
|---|---|
| `lib/chart-4.5.1.umd.min.js` | Chart.js 4.5.1, como `window.Chart` |
| `lib/d3-7.9.0.min.js` | d3 7.9.0, como `window.d3` |
| `lib/lucide-1.46.0.min.js` | Iconos de Lucide 1.46.0, como `window.lucide` - el mismo conjunto que usa la consola |
| `lib/agenticos-3.css` | El kit de páginas: el aspecto de la consola para páginas, claro y oscuro, y los componentes `ao-` con los que se construye una página |
| `lib/agenticos-3.js` | `window.AO`: Chart.js con el estilo de la consola, formato de números en el idioma de la página, iconos, pestañas, `AO.onData` y `AO.records` |
| `lib/agenticos-2.css`, `lib/agenticos-2.js` | La versión anterior del kit, conservada para las páginas publicadas con ella |
| `lib/agenticos-1.css` | La primera versión del aspecto, conservada para las páginas publicadas con ella |

Cada nombre lleva su versión y se guarda en caché un año. Una actualización añade
un archivo nuevo junto al antiguo, así que una página publicada con una versión
sigue recibiendo esa, y un archivo ya distribuido nunca se modifica. No se
descarga nada de fuera del despliegue, así que uno sin acceso a internet funciona
igual. Los archivos están en `backend/app/core/catalog/artifact_lib/`.

La versión 3 conserva todas las clases y llamadas de la versión 2, y perdona el
marcado que un modelo escribe con descuido: un título, un subtítulo y una línea
de metadatos puestos directamente en la cabecera se apilan en vez de repartirse
a lo ancho, una tabla sin `<thead>` recibe igualmente su fila de cabecera, y un
mensaje escrito en el contenedor de una tabla recibe relleno.

Añade líneas de carga y de nota, una línea de leyenda, un punto en vivo, listas,
una barra de herramientas con campos, y el icono y las acciones de la cabecera.
Los iconos que un script añade tras cargar la página, como los registros de una
página en vivo, también se dibujan.

El [skill](skills.md) incluido **`artifact-pages`** enseña a un agent a usarlos:
el esqueleto obligatorio, todas las clases del kit, tres plantillas (un
dashboard, un informe y una tabla en vivo dibujada con `AO.records`), el estilo
de la casa, iconos en lugar de emoji y cómo cambiar una página con
`read_artifact`. Una organización nueva lo recibe con los demás skills incluidos,
una existente con `seed-skills`, y la pestaña **Page style** de la capability
Artifacts en el Builder lo ofrece. Edita el skill para describir tu propia marca,
y el agent la sigue.

### El contrato de página y los avisos de publicación { #the-page-contract-and-the-publish-warnings }

El agent no puede ver la página que publica, así que la plataforma le dice cómo
debe ser una página y qué parece estar mal en la que envió.

La capability Artifacts da a cada agent que la tiene un breve **contrato de
página** en sus instrucciones, esté vinculado el skill o no: el esqueleto
(doctype, viewport, `lang`, la hoja de estilos y el script del kit en orden,
`main.ao-page` y la cabecera), una lista cerrada de las clases más usadas del
kit, iconos de Lucide en lugar de emoji, y `AO.records` para los datos
vinculados.

Cuando el run del agent ofrece el skill `artifact-pages` y no lo ha cargado, su
primera página HTML completa se devuelve una vez con la petición de cargar el
skill y reconstruirla. Eso ocurre una vez por run; cada mensaje nuevo es un run
nuevo, así que puede volver a ocurrir en un turno posterior. Un cambio nunca se
devuelve.

Después se comprueba la página HTML publicada, y el resultado lleva un `warning`
con una línea por cada problema encontrado. La página se publica en cualquier
caso. Las comprobaciones:

- falta `<!doctype html>` como primera línea, o falta la meta de viewport;
- una clase `ao-`, en el marcado o nombrada en un script, que no define la
  versión del kit que carga la página ni tampoco su propio `<style>`;
- una tabla sin `<thead>`, o sin la clase `ao-table`;
- iconos `data-lucide` sin `lib/lucide-1.46.0.min.js`;
- `AO.onData` o `AO.records` en una página que no carga `lib/agenticos-3.js`;
- una página vinculada cuyo script nunca llama a `agenticos.onData` ni lee
  `agenticos.data`, así que no muestra ningún registro.

### Ver la página: la vista previa { #seeing-the-page-preview }

`preview_artifact` dibuja la versión actual de una página como la vería quien la
abre, a 1280 píxeles de ancho, y entrega al modelo una imagen y un informe
escrito. El informe da los datos de cada binding (registros, cortado, o
`unavailable` y por qué), si la página pidió sus datos, los errores no capturados
con su línea, los errores y avisos de la consola, lo que rechazó la política de
seguridad de la página, las peticiones rechazadas, los diálogos y los avisos de
publicación de arriba. La imagen mide como máximo 2400 píxeles de alto; una
página más larga dice cuánto mide. Si sigue ejecutándose a los 15 segundos, se
notifica así, sin imagen.

Los datos se leen como la persona por la que actúa el run, exactamente como la
consola los leería para ella. En un chat de grupo solo se puede previsualizar una
página de toda la organización, las mismas páginas que la lista muestra allí, y
se dibuja sin datos. Una superficie sin nadie con sesión iniciada no previsualiza
nada. Nada de lo que pide la página llega a la red: la API responde a cada
petición con la página, el [conjunto de bibliotecas](#the-library-set) o un
rechazo.

La imagen necesita un navegador que ejecute el operador, indicado por
[`ARTIFACT_RENDER_CDP_URL`](configuration.md#published-artifacts), y el extra
`browser` del backend. Ese ajuste es solo del operador: está separado de los
hosts que puede manejar un agent que navega, y ningún agent puede apuntar un
navegador hacia él. Sin alguno de los dos, la herramienta sigue devolviendo el
informe, sin la imagen, y dice que el despliegue no tiene renderizador. Desactiva
**Preview screenshot** en los ajustes de la capability para un modelo que no
puede leer imágenes; el informe sigue llegando. `agenticos cmd doctor` dice si el
renderizador responde.

## Quién puede abrirlo { #who-can-open-it }

Un artefacto nuevo es **privado** para la persona en nombre de la cual actuó el
run que lo publicó: la persona del chat, o el creador de un trigger. Una página
privada también es visible para los roles Owner, Admin, Builder y Operator.

Su enlace - al que apuntan la tarjeta del chat y la respuesta del agente - abre
la propia página (desde la tarjeta del chat, en una pestaña nueva), a toda la
ventana, bajo una única barra con el título, la versión y **Share**. El enlace
por sí solo no deja entrar a nadie: solo se abre para un miembro con sesión
iniciada al que las reglas de abajo ya dejan entrar.
Nombra la organización en la que está el artefacto (`?org=`), así que un miembro
de varias llega a la correcta.

En **Share**, cualquiera que pueda gestionarlo puede compartirlo de tres maneras:

| Alcance | Cómo | Quién |
|---|---|---|
| Personas concretas | Un grant, con `read` o `edit` | Esos miembros, en esta organización |
| La organización | Visibilidad fijada a toda la organización | Todo miembro cuyo rol alcance los artefactos compartidos |
| Cualquiera con el enlace | **Create a public link** | Cualquiera que tenga la dirección, sin cuenta |

Compartir y la visibilidad usan el mismo panel y las mismas reglas que los agents
y los skills; consulta [Permisos](permissions.md). Gestionar un artefacto
(compartirlo, su enlace público y sus ajustes, restaurar una versión, borrarlo)
requiere `artifacts:edit` sobre ese artefacto, desde el rol o desde un grant
`edit`. Abrirlo requiere `artifacts:view`.

El agent no puede ampliar quién lee una página. Publica; una persona decide quién
la ve. Por eso la capability no pide aprobación por defecto: una primera
publicación es privada, y lo que muestra una página vinculada lo decide en el
momento de verla el propio acceso de cada lector. Un autor que quiera que una
persona apruebe cada nueva publicación de una página ya compartida, o de una página
vinculada, fija `tool_approval` en `publish_artifact` en el spec. Una página
vinculada solo puede volver a publicarla un run que actúe en nombre de un miembro
(consulta [Datos en vivo](#live-data)).

### Quién ve los registros de una página en vivo { #who-sees-a-live-pages-records }

Compartir una [página en vivo](#live-data) deja que una persona la abra, pero los
registros de cada binding se leen con su propio acceso. Para verlos necesita
además acceso de lectura a la tabla del binding, y una vista compartida o propia.
Por eso una página vinculada a una vista privada solo muestra sus registros al
propietario de la vista; el resultado de la publicación se lo dice al agent, para
que lo transmita.

### El enlace público { #the-public-link }

Un enlace público es `/a/<key>` en la propia dirección de la consola, con una
clave aleatoria de 192 bits: la misma regla que sigue la clave de la página de
chat alojada. No dice nada de quién la publicó ni de a qué organización pertenece.

**Replace the link** emite una clave nueva, y la antigua deja de abrir nada al
instante. **Turn off** lo elimina. Ambas acciones quedan registradas en el
registro de auditoría. Una página que alguien ya tiene abierta se sigue mostrando
hasta que caduca su dirección de contenido firmada, como máximo
`ARTIFACT_VIEW_TTL_SECONDS` (cinco minutos por defecto).

Un miembro revocado está en la misma situación: pierde el artefacto en su
siguiente petición, y una página que ya tenía abierta se mantiene como mucho
durante esa misma ventana.

Bajo el enlace, **Share** guarda sus ajustes. Se mantienen cuando se sustituye el
enlace, y un enlace que se apaga y se vuelve a encender los conserva:

| Ajuste | Qué hace |
|---|---|
| **Stops opening after** | Una fecha a partir de la cual el enlace no abre nada, como si estuviera apagado |
| **Shows** | La versión más reciente, o una versión conservada fijada para que una publicación nueva no cambie lo que ya vieron quienes tienen el enlace. Una versión fijada nunca se elimina |
| **Password** | Se pide antes de abrir la página. El enlace no dice nada — ni el título, ni cuándo se publicó — hasta que es correcta. Se guarda como hash y no vuelve a mostrarse; cada intento cuenta contra el límite de peticiones del enlace |
| **Sites that may embed it** | Consulta más abajo |

La tarjeta también dice cuántas veces se abrió el enlace y cuándo fue la última.
Cuenta aperturas, no personas: no se guarda nada sobre el visitante. Cada cambio en
los ajustes queda auditado, con los nombres de los ajustes cambiados y nunca con
una contraseña.

### Incrustarlo en otro sitio { #embedding-it-on-another-site }

Una página pública se puede colocar en una página de la intranet, en un wiki o en
el sitio de un cliente con un `<iframe>`. Enumera los sitios en **Sites that may
embed it** — solo esquema y host, `https://intranet.example.com`, o
`https://*.example.com` para los subdominios de un sitio — y copia el **Embed
code** que Share muestra entonces.

El código incrusta `/api/v1/artifact-embed/<key>` desde el origen del contenido:
un documento pequeño del propio despliegue, que a su vez incrusta la página en el
mismo sandbox que en todas partes. Su política solo deja incrustarlo a los sitios
enumerados, y la política de la propia página solo deja incrustarla a ese
documento y a la consola. Sin ningún sitio enumerado, nadie puede. Una página tras
una contraseña no se puede incrustar — la incrustación dice entonces que se abra en
su propia página —, y nadie inicia sesión dentro de un frame en el sitio de otro.

## Cómo se aísla la página { #how-the-page-is-isolated }

Un artefacto es HTML con script dentro, escrito por un modelo que puede haber
leído algo hostil. Se sirve de forma que nada de lo que haga pueda alcanzar la
consola ni a la persona que lo mira:

- Los bytes salen de una ruta aparte, `/api/v1/artifact-content/<token>`, que
  no lee ninguna cookie ni ninguna sesión. El token está firmado, nombra una sola
  versión y caduca en minutos. Solo se emite después de que un grant o un enlace
  público haya admitido a quien llama.
- Cada respuesta de contenido lleva `Content-Security-Policy: sandbox
  allow-scripts allow-modals`, sin `allow-same-origin`. La página se ejecuta en
  un origen opaco, así que no puede leer las cookies, el almacenamiento ni la
  página de la consola, y una petición que hiciera no llevaría nada del lector.
  Eso se mantiene incluso cuando alguien abre la dirección de contenido por sí
  sola.
- La misma política fija `default-src 'none'` y `connect-src 'none'`. El único
  origen remoto que nombra es la ruta propia del conjunto de bibliotecas en el
  origen del contenido, para scripts, estilos y fuentes. `frame-ancestors` nombra
  solo la consola — y, para una página con enlace público y sitios que la
  incrustan, el documento de incrustación y esos sitios. El frame de la consola
  lleva la misma lista `sandbox` como segundo cerrojo.
- No hay `allow-popups`. `connect-src` no rige la navegación, así que un enlace
  que abriera una ventana nueva sería una forma de enviar lo que muestra la página
  a una dirección elegida por ella. En su lugar, cada página servida recibe
  primero un script corto de la plataforma: un clic en un enlace a otro sitio se
  convierte en un mensaje al padre del frame. La consola y la página pública
  muestran la dirección completa y la abren en una pestaña nueva solo cuando la
  persona acepta; el documento de incrustación hace lo mismo en una barra bajo la
  página. La página podría enviar ese mensaje por sí misma, así que es una
  petición y nunca un permiso: la persona que lee la dirección es lo que se
  interpone entre una página manipulada por prompt injection y la dirección a la
  que enviaría sus cifras.
- Los datos en vivo llegan por `postMessage` desde la consola, que los obtiene
  como el lector. La ruta de contenido nunca lleva registros. La petición de la
  página lleva un nonce que permite a la consola emparejar cada respuesta con la
  carga de página correcta; eso es **correlación, no control de acceso**. El
  acceso es la propia sesión del lector en la ruta de datos, así que una página
  solo recibe lo que el lector puede leer.
- Una dirección firmada carga su página unas pocas veces por minuto como mucho,
  contadas por dirección antes de leer nada. La consola y la página pública
  emiten una dirección nueva cada vez que dibujan el frame, y emitirla a través
  de un enlace público ya está limitado por enlace.

La lista **Artifacts** dibuja la página actual de cada tarjeta como una
miniatura en vivo, por el mismo tipo de frame, con script y nada más: sin
diálogos, sin ventanas emergentes, sin formularios. Con script, para que un
dashboard cuyos gráficos dibuja una librería no sea un lienzo vacío en su
tarjeta. La miniatura es inerte — sin eventos de puntero, fuera del orden de
tabulación, oculta a las tecnologías de asistencia — y solo existe mientras su
tarjeta está cerca de la vista, así que una lista larga ejecuta las pocas que se
ven y detiene una página que quedó fuera de la pantalla.

Además, un despliegue puede servir el contenido desde un **dominio registrable
aparte** fijando `ARTIFACT_ORIGIN`, por ejemplo
`https://agenticos-content.example.net`, enrutado a la misma API. La página queda
entonces en otro sitio por completo. El origen opaco ya la aísla, así que esto es
un endurecimiento que puede pedir una revisión de seguridad, no un requisito.
Fija la variable para el backend y para el frontend, que añade la ruta de
contenido de ese origen a su `frame-src`. Consulta [Configuración](configuration.md#published-artifacts).

## Archivar una página { #archiving-a-page }

Archivar retira una página a todo el mundo sin perderla. Alguien que puede
editar la página elige **Archive** en el menú **More actions** que hay sobre
ella, y un diálogo explica lo que eso hace antes de que cambie nada. Se conservan
la página, sus versiones, sus grants y su nombre. Nada la sirve hasta que se
restaura, desde la misma página. Archivar queda auditado como
`artifact.archived`, y restaurar como `artifact.unarchived`.

Mientras una página está archivada, cada vía que la mostraría responde como si
no existiera:

- **La consola.** Se rechazan su vista y sus datos en vivo, y también una
  dirección firmada emitida antes de archivarla. A un lector que abre su enlace
  se le dice que no está disponible. Quien puede editarla ve cuándo se archivó,
  con **Restore** y **Delete**.
- **Las listas.** La lista Artifacts y el widget del dashboard la omiten. Elige
  **Archived included** en la lista para verla, marcada como **Archived**.
- **El enlace público y el embed.** Ninguno de los dos abre nada.
- **El agent.** `publish_artifact` rechaza el nombre con un mensaje que menciona
  el archivado, así que un run no puede crear una segunda página con él.
  `read_artifact`, `preview_artifact` y `list_artifacts` tratan la página como
  inexistente. Un run que no puede editar la página solo oye que el nombre no es
  suyo para cambiarlo.

Archivar desactiva el enlace público, auditado como
`artifact.public_link_disabled`, y restaurar no lo vuelve a activar. Una
dirección enviada antes del archivado sigue muerta hasta que alguien crea una
nueva desde **Share**. Para eso se conservan la caducidad del enlace, la versión
fijada, la contraseña y los sitios que pueden incrustarlo.

Por la API, `POST /api/v1/artifacts/{id}/archive` archiva una página, y
archivarla de nuevo no cambia nada. `POST /api/v1/artifacts/{id}/unarchive` la
restaura, y responde `400` para una página que no está archivada. Ambas piden el
derecho a editar esa página, grant incluido. `GET /api/v1/artifacts` enumera las
páginas archivadas solo con `include_archived=true`, y `archived_at` en cada
página dice cuándo se archivó.

## Retención y borrado { #retention-and-deletion }

Los artefactos son una [clase de retención](governance.md#the-classes) propia,
medida desde la **última publicación**: un informe que se vuelve a publicar cada
semana está vivo por antigua que sea su primera versión. Como toda clase, conserva
los artefactos para siempre hasta que una organización o el despliegue fijen un
periodo.

Borrar un artefacto, a mano o por retención, elimina todas sus versiones, sus
bytes almacenados, sus grants y su enlace público. Una página archivada envejece
y se borra como cualquier otra. Borrar el agent no borra sus
artefactos: siguen legibles y simplemente no tienen quien los publique. Borrar un
entorno con nombre hace lo mismo con las páginas publicadas desde él, así que
nunca caen sobre la página del entorno por defecto con el mismo nombre. Borrar la
organización los elimina. Los artefactos de una persona borrada se quedan y
pierden su propietario, igual que sus agents y skills.

Los bytes viven en el [almacenamiento de archivos](configuration.md#uploaded-files-at-rest)
del despliegue, bajo `artifacts/<organization>/<artifact>/`.

## Limitaciones { #limitations }

- **Un único documento autocontenido por versión.** Sin paquetes, y sin red desde
  dentro de la página más allá del conjunto de bibliotecas servido y de los
  [datos en vivo](#live-data) que le entrega la consola.
- **Los datos en vivo están acotados.** Cinco bindings, 1.000 registros cada uno y
  unos 5 s por carga; consulta los [límites](#limits). Los datos que no están
  vinculados son la página tal como se publicó, y cambian cuando el agent vuelve a
  publicar.
- **Nada en la página actúa.** Un formulario o un botón no tiene adónde enviar lo
  que recoge.
- **Una página abierta sobrevive a una revocación durante la vida de una
  dirección firmada**, cinco minutos por defecto.
- **Un enlace dentro de una página pregunta primero.** Se abre en una pestaña
  nueva cuando una persona acepta; la propia página no puede abrir una ventana ni
  navegar la consola.
- **Una incrustación necesita el enlace público y ninguna contraseña.** Los
  miembros no pueden iniciar sesión dentro del frame de otro sitio.
- **Las versiones eliminadas desaparecen.** Una conversación que enlaza a una
  versión más antigua que la ventana conservada solo puede ofrecer la última.
- **Sin renderizador, el agent no ve su página.** Los avisos de publicación leen
  el marcado y no pueden saber qué aspecto tiene. Con uno, la imagen es la de un
  Chromium headless: las fuentes y los tamaños pueden diferir un poco del
  navegador de un lector.

## Resumen { #recap }

- Una capability, cuatro herramientas: `publish_artifact`, desde un archivo del
  workspace, en línea o como cambios; `read_artifact` para volver a leer una
  página; `list_artifacts` para encontrar una; y `preview_artifact` para verla
  dibujada, con sus errores.
- El agent, el entorno y el nombre son la identidad; volver a publicar conserva el
  enlace y añade una versión, y cualquier versión conservada se puede restaurar.
- Privado por defecto; compartido por una persona mediante grants, la
  organización o un enlace público. El enlace público puede caducar, fijar una
  versión, pedir una contraseña e incrustarse en los sitios enumerados.
- Una página puede vincularse a vistas guardadas de tablas y mostrar datos en vivo,
  leídos en el momento de verla con el propio acceso del lector y nunca guardados
  en la página.
- Un breve contrato de página en las instrucciones de cada agent con Artifacts,
  y avisos en el resultado de la publicación sobre lo que parece estar mal en el
  marcado.
- Servido desde una ruta sin cookies, en un origen opaco sin red salvo el propio
  conjunto de bibliotecas del despliegue, con enlaces que preguntan antes de
  abrirse, y opcionalmente desde un dominio propio.
- Archivar conserva una página y no sirve nada de ella, con el enlace público
  desactivado, hasta que alguien que puede editarla la restaura.
- Una clase de retención propia, medida desde la última publicación.
