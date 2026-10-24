---
source_sha: "ae0585c30a8a"
---

# Aplicaciones { #artifacts }

Una **aplicación** es una página que un agent ha publicado: un informe, un pequeño
dashboard, un resumen de una página que alguien abre en el navegador. Tiene un
enlace que no cambia cuando el agent vuelve a publicarla, así que «cada lunes,
publica las cifras de la semana en esta página» es un solo enlace que la gente
guarda en favoritos, en lugar de uno nuevo cada semana.

Una aplicación no es un archivo. Un gráfico, un PDF generado y un archivo del
workspace ya tienen su sitio en el chat y en el [workspace](sandbox.md). Una
aplicación es lo que se *sirve*: tiene un propietario, una visibilidad y grants
como un agent o un skill, y se le puede dar un enlace público para alguien sin
cuenta.

## Publicar una { #publishing-one }

Activa la capability **Apps** para el agent. Añade cinco herramientas:
`publish_artifact`, que el modelo llama cuando el resultado es algo que una
persona debería abrir en lugar de leerlo una vez en el chat; `read_artifact`,
que vuelve a leer una página publicada; `list_artifacts`, que nombra las páginas
que un run puede abrir; y `preview_artifact`, que dibuja una página y dice qué
falla en ella.

La página sale de uno de tres sitios:

- **Un archivo del workspace del agent**, terminado en `.html` o `.md`. Es el
  caso habitual para un agent con la capability [Sandbox](reference/capabilities.md#files-shell):
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
`bindings` a `publish_artifact`: cada binding es un nombre y una **page query** — una
tabla, los campos que la página lee de ella y, opcionalmente, filtros, un orden y un
límite. La página llama a `agenticos.onData(render)`, y `render(data)` se ejecuta con los
primeros datos y de nuevo en cada refresco. `agenticos.data` es una Promise de los
primeros datos.

```js
agenticos.onData((data) => {
  // data.tickets = { status, records, fields, count, truncated, limit }
});
```

Cada binding llega como `status` (`ok` o `unavailable`), `records`
(`{id, <field>: value}`), `fields` (etiqueta, tipo, opciones y estado de cada uno),
`count`, `truncated` y `limit`. Una página que no recibe respuesta en 10 segundos ve
todos sus bindings `unavailable`; un listener añadido después de eso pregunta una vez más.

**Todos los que abren una página en vivo leen los mismos registros**, sea cual sea su
propio acceso a las tablas. La query se lee con el acceso del [propietario](#who-owns-a-page)
de la página, y solo cuando el propietario ha aceptado compartirla
([consentimiento](#consent-the-owner-decides-who-reads-the-data)). Así, una página es para
datos que pueden ver todos los que puedan abrirla. Los registros se leen cuando alguien mira
la página y nunca se guardan en ella.

### Lo que congela un binding { #what-a-binding-freezes }

Una page query no es un enlace a una vista guardada. El agent nombra una `table`, o una
[vista guardada](virtual-tables.md#saved-views) por id o nombre exacto, y la plataforma
**copia** los filtros y el orden de la vista a la página al publicar. Editar o borrar la
vista después no cambia nada en la página.

| En el binding | Significado |
|---|---|
| `table` o `view` | La tabla que leer, o una vista cuyos filtros y orden se copian. No ambas |
| `fields` | Cada nombre que lee la página, asignado a una columna por id o etiqueta |
| `filters` | `{column, op, value}`, todos deben cumplirse; se suman a los filtros de la vista |
| `sort` | `{by, direction}`; sustituye el orden de la vista |
| `limit` | Como máximo 1.000, que es también el valor por defecto; sustituye el de la vista |

Los `visible_columns` y `group_by` de una vista se ignoran: los `fields` del binding deciden
las columnas. Un filtro puede nombrar una columna que la página no lee, y se avisa al
propietario de cuál. Una page query no tiene búsqueda de texto libre, así que una vista con
búsqueda **no se puede vincular**; la publicación se rechaza y la nombra. Una vista cuyo
filtro nombra una columna que ya no existe se rechaza igual.

Se permiten fórmulas, lookups, rollups y etiquetas de enlace. Leen más que la columna que
nombra la página, así que la query registra todo lo que alcanza: las columnas de entrada de una
fórmula, el enlace y el destino de un lookup o rollup, cada tabla vinculada y la columna por la
que cada tabla vinculada etiqueta sus registros. El spec del agent debe conceder lectura sobre
la tabla, y la persona detrás del run debe leer cada tabla que alcanza la query, porque nadie
puede vincular lo que no puede leer.

El resultado de la publicación describe cada query en palabras — su tabla, filtros, orden,
límite y cada campo con lo que lee (`Status (single_select)`, `Pay band: formula over Salary,
Level`). Es el texto que acepta el propietario, así que el agent comprueba que es lo que
pretendía. Un binding que se arrastra sin cambios dice `kept`.

El nombre de un binding son letras minúsculas, dígitos y `_`. Un campo puede
llamarse como está rotulada su columna: palabras de letras en mayúsculas o
minúsculas, dígitos y `_`, separadas por un solo espacio, como `Status` o
`Created At`. Ambos tienen hasta 64 caracteres, y `__proto__`, `constructor` y
`prototype` están reservados para ambos (`id` también, para un campo). Una página
tiene como máximo 5 bindings, y un binding como máximo 50 campos.

La versión 3 del [kit de páginas](#the-library-set) dibuja un binding por el
agent: `AO.records("#tickets", data.tickets)` dentro de `agenticos.onData`
muestra los registros como una tabla con una cabecera formada por las etiquetas
de los campos, los números y las fechas alineados a la derecha, las opciones como
insignias y cada valor escrito como texto. Antes de los datos muestra una línea
de carga, y un binding `unavailable` o vacío y una lista cortada reciben cada uno
su propio mensaje. En la versión 3, `AO.onData` es la misma llamada que
`agenticos.onData`. Una página vinculada cuyo script nunca pide sus datos se
publica igualmente, con un [aviso](#the-page-contract-and-the-publish-warnings).

### Quién ve qué { #who-sees-what }

Qué versión se sirve a un lector, y si se leen sus datos para él, depende de quién es.

| Lector | Se le sirve | Sus datos |
|---|---|---|
| El propietario de la página | La última versión | Siempre |
| Owner, Admin, Builder y Operator, aunque solo puedan ver | La última versión | Siempre, para los roles que leen todas las tablas (`tables:view` con alcance ALL) |
| Cualquier otro que pueda editar la página | La última versión, para que el agent de un editor siga editando lo vigente | Mientras se mantenga el consentimiento del propietario a esa versión |
| Todos los demás que pueden abrirla (la **audiencia**) | La versión más reciente que alguna vez tuvo consentimiento, o que no lee datos | Mientras se mantenga el consentimiento del propietario a ella |

A la audiencia nunca se le sirve una versión que nadie aceptó compartir. Cuando el
consentimiento a los datos ya no se mantiene — un editor lo retiró, o cambió el
propietario —, la audiencia sigue recibiendo esa **página completa**, y cada binding llega
`unavailable` con el motivo `awaiting_consent`; la página dice «The data appears once
the page's owner confirms it.» Cuando ninguna versión tiene consentimiento ni está libre de
datos, la audiencia ve «This page isn't available yet» y nada más.

Un binding también es `unavailable` cuando lo que lee cambió desde que se publicó la página.
El motivo solo se le dice a quien puede editar la página; un lector ve cuántas fuentes no
están disponibles.

| Motivo | Qué ocurrió |
|---|---|
| `creator_gone` | El propietario de la página ya no es un miembro activo |
| `creator_lost_access` | El propietario ya no puede leer una tabla que alcanza la query |
| `source_changed` | Cambió el significado de una columna (su tipo, una fórmula, el destino de un enlace o lookup, un agregado, una opción archivada o restaurada), se archivó una columna o tabla, o una tabla vinculada ahora etiqueta sus registros por otra columna. Se nombra la etiqueta actual de la columna |
| `awaiting_consent` | El propietario no ha confirmado compartir los datos de esta versión, o se retiró |

Que un binding pase a `unavailable` deja funcionando a los demás. A la página nunca se le
bloquea un cambio de tabla: nada impide cambiar una columna, y el binding deja de servir hasta
que el agent vuelve a publicar la página, lo que resuelve la query contra la tabla tal como
está ahora. Renombrar una columna no cambia un binding; la página sigue leyéndola por el
nombre que le dio el agent. Añadir una opción a un select, o renombrar una, tampoco.

### Consentimiento: el propietario decide quién lee los datos { #consent-the-owner-decides-who-reads-the-data }

Los datos de una página se leen con el acceso de su propietario, así que el propietario decide
quién más los lee, por versión. Esa decisión es el **consentimiento**: el propietario revisa
las page queries en palabras — la tabla, filtros, orden, límite y campos de cada query, cada
tabla vinculada que alcanza y quién la leerá — y confirma.

La revisión nombra quién verá la página: los roles que ven todas las páginas (Owner, Admin,
Builder y Operator), la visibilidad de la página, las personas con las que se comparte y los
grupos, incluidos los futuros miembros. El propietario solo puede
confirmar lo que él mismo lee.

Los datos de una versión están en uno de estos estados:

| Estado | Significado |
|---|---|
| `not_needed` | La versión no tiene bindings |
| `pending` | Nadie la ha confirmado. La audiencia conserva la versión que tenía |
| `consented` | El propietario la confirmó, o se consintió automáticamente |
| `declined` | Se rechazó una solicitud para confirmarla |
| `withdrawn` | Un consentimiento que ya no se mantiene: un editor lo retiró, o su propietario ya no es el de la página |

Una versión nueva se consiente **automáticamente** cuando sus page queries — y todo lo que
alcanzan — son las que el propietario ya había consentido. Si no, queda `pending`: eso incluye
la primera versión vinculada, salvo que el propietario tenga activado el
[consentimiento automático](#auto-consent).

El propietario, y solo él como él mismo, confirma en el visor. Mientras la última versión
espera, la franja bajo el título de la página lo dice, con **Confirm data**: abre lo que la
versión comparte y con quién, y la confirmación lleva una huella de exactamente lo que se
mostró. Si la página se volvió a publicar entretanto, o sus queries cambiaron, la confirmación
se rechaza y el propietario vuelve a mirar. Confirmar también comprueba que el propietario
sigue pudiendo leer cada tabla que alcanza la query.

Un Owner o Admin puede confirmar por el propietario. Se audita como consentido por él en nombre
del propietario, y el acceso del propietario sigue respaldando los datos. Quien tenga un grant
`edit` no puede: un grant para editar la página no da autoridad sobre los datos de quién lee.

**Retirarlo** quita el consentimiento. Cualquiera que pueda editar la página, como él mismo,
usa **Stop sharing data** en el menú del visor. Todos los consentimientos dados hasta ahora
quedan anulados, no solo el último, y el consentimiento automático se desactiva. Cada grant
`edit_data` de la página baja también a `edit`, de modo que la siguiente republicación de un
editor de datos espera al propietario en lugar de deshacer la retirada. La audiencia conserva
la página y pierde sus datos hasta que el propietario vuelva a confirmar. Retirar solo
estrecha quién lee, por lo que todo editor puede hacerlo.

Cuando el propietario deja la organización, sus consentimientos caducan con su membresía. Un
propietario al que se elimina y se vuelve a invitar empieza de cero. Un propietario al que se
desactiva y se reactiva recupera sus consentimientos: reactivar es un acto de toda la cuenta,
en cada organización a la que pertenece.

#### Volver a publicar { #republishing }

Cuando un editor que no es el propietario publica una versión que lee datos distintos, la
versión queda `pending` y la plataforma presenta una **solicitud de versión** para el
propietario — consulta [Solicitudes de compartir](#share-requests). Hasta que el propietario
decide, la audiencia sigue viendo la versión anterior. El resultado de la publicación dice
«The audience still sees v2 until Alex confirms this version's data in the console.» (con el
nombre del propietario, o «the page's owner»).

Un run sin persona detrás solo puede volver a publicar una página vinculada sin cambios — los
mismos bytes y las mismas queries, lo que no necesita persona ni consentimiento. No puede
cambiar el código que recibe los registros del propietario. La publicación de un editor se
rechaza cuando el propietario de la página no puede leer una tabla que alcanza la query.

#### Consentimiento automático { #auto-consent }

El propietario puede activar **Share new versions automatically** para una página. Está
desactivado por defecto y solo el propietario, como él mismo, lo activa, nunca un agent.
Primero pregunta: «Any data change your runs make to this page, including new tables and
columns, reaches everyone who can open it without asking you. This includes API runs.» La entrada de
auditoría registra el texto confirmado.

Cubre solo las republicaciones del propio propietario. La republicación de un editor sigue
esperando. Los consentimientos automáticos se registran como automáticos, y cuando uno alcanza
más que la versión servida antes, la franja del propietario lo lista: «v4 was shared
automatically and shows more data: +Deals, +Salary». El propietario, o un Owner o Admin, lo
desactiva, y retirar la página o entregarla a otra persona también lo desactiva.

Nunca cubre un run que empezó mientras un administrador suplantaba al propietario, por
tarde que publique: un run en segundo plano, un paso de workflow o un run reanudado tras
una aprobación lo lleva consigo, y lo mismo vale para el grant de editor de datos
(abajo). Republicar las queries que el propietario ya confirmó sigue contando como
consentido.

#### Editores de datos { #data-editors }

El diálogo de compartir tiene un nivel de grant por encima de `edit`: **Can edit, including
data** (`edit_data`), solo para páginas. Es un consentimiento permanente a las
republicaciones de esa persona, incluido un cambio de query. Solo el propietario, o un Owner o
Admin, como ellos mismos, lo concede, tras una ventana: «Alex can change the data everyone sees
on this page, including new tables and columns, without asking you. This also covers their API
runs.» Para un grupo, la ventana dice «Anyone in Sales, now or later, can change ...».
El grant se audita con el texto confirmado.

Una republicación de alguien con `edit_data` se consiente automáticamente, registrada como
hecha mediante su grant. Aun así tiene que leer cada tabla que alcanza la query, y el
propietario también. El alcance de rol de Owner o Admin nunca lo implica. Cualquiera que pueda
editar la página lo baja o lo quita, y un cambio de propietario baja cada grant `edit_data` a
`edit`.

### Quién es el propietario de una página { #who-owns-a-page }

El propietario de una página es la persona en cuyo nombre actuó el primer run que publicó. Nunca
cambia por sí solo y es el único propietario de datos de la página: la persona cuyo acceso lee
los datos y cuyo consentimiento los comparte. Si se elimina al propietario, la página se queda
sin él. Nadie puede reclamar una página.

El propietario la entrega a otro miembro activo de la organización con **Change owner** en el
menú del visor, y un Owner o Admin puede reasignar cualquier página, incluida una cuyo
propietario ya no está. Cada uno lo hace como él mismo, no suplantando a nadie. Un grant para
editar la página no lo permite. No hay una herramienta de agent para ello.

El cambio es inmediato, sin paso de aceptación. Los datos de la página dejan de llegar a la
audiencia hasta que el nuevo propietario los confirme, todos los consentimientos dados quedan
anulados para siempre (de modo que devolver la página nunca revive uno antiguo), el
consentimiento automático se desactiva, toda solicitud pendiente se anula, cada grant
`edit_data` baja a `edit`, y se notifica al propietario anterior y al nuevo, salvo a quien hizo
el cambio. Se audita como `artifact.owner_changed`.

Dar a una página sin propietario la visibilidad `private` cuenta como tomarla, y solo está
abierto a un Owner o Admin. Pasa por las mismas reglas.

### Solicitudes de compartir { #share-requests }

Ampliar quién puede abrir una página que lee datos — una visibilidad más amplia, o un grant
nuevo o un nivel más alto — es decisión del propietario, o de un Owner o Admin por el
propietario. Estrechar está abierto a todo editor. Una página que no lee datos conserva las
reglas de compartir ordinarias.

Cualquier otro que pueda editar la página e intente ampliarla no recibe una negativa. La
plataforma presenta una solicitud. Hay tres tipos:

| Tipo | La hace | Pide |
|---|---|---|
| `audience` | Un editor, en el diálogo de compartir o mediante el `share_artifact` de su agent | Ampliar quién abre la página |
| `access` | Un miembro de la organización de la página que abre su enlace sin acceso | Abrir la página, con una nota opcional |
| `version` | La publicación de otro editor cuya versión lee datos distintos | Confirmar esa versión |

Un miembro puede tener una solicitud `audience` y una `access` pendientes por página, y una
página tiene una solicitud `version` pendiente; una más reciente sustituye a la anterior. Las
solicitudes están limitadas, por defecto, a diez por hora por persona y
organización ([`RATE_LIMIT_ARTIFACT_SHARE_REQUESTS_PER_HOUR`](configuration.md)). Una
solicitud `version` también cuenta contra el cupo de quien publica: superado, una
republicación sigue sustituyendo a la solicitud pendiente, pero no se vuelve a notificar al
propietario.

Decide el propietario de la página. Cuando ya no tiene
propietario, los Owners y Admins pueden rechazar; para aprobar, primero entregan la página a un
miembro (**Change owner**), que confirma los datos. Una solicitud queda anulada sin decisión
cuando cambian las queries de la página, cambia el propietario o se archiva la página.

Se notifica al propietario en la consola y por correo, según lo configurado en **Settings →
Notifications** («Page requests»). La notificación nombra la página y al solicitante,
nunca sus datos.

Se responden en una sección **Requests** del diálogo de compartir, y un botón **Requests** en la
franja del visor muestra cuántas esperan. Aprobar una solicitud `audience` o `access` aplica la
visibilidad y los grants que pedía, cada uno solo donde aún amplía. **Nunca consiente los
datos**: cuando la versión que se sirve a la audiencia no tiene un consentimiento vigente,
aprobar se rechaza con «Confirm the page's data before sharing it», y el propietario confirma
primero los datos y luego aprueba. Rechazar no comparte nada.

Una solicitud `audience` o `access` hecha bajo una
membresía que ya terminó (se quitó al miembro y se le volvió a invitar) no se puede aprobar;
recházala.

La lista de solicitudes (`GET /api/v1/artifacts/{id}/share-requests`) contiene siempre todas las
pendientes. Con `include_decided=true` añade las decididas y las anuladas, que se conservan, de
la más reciente a la más antigua y por páginas con `skip` y `limit` (50 por defecto, 100 como
máximo); `total` cuenta todas, y el diálogo Share avisa cuando solo muestra las decididas más
recientes.

Al solicitante no se le avisa de la decisión: que la página se abra o no es la respuesta. Una
página que no lee datos admite una solicitud `access` simple, que puede aprobar cualquier
editor.

#### Solicitar acceso { #requesting-access }

Un miembro de la organización que abre el enlace de una página que no puede abrir ve «You don't
have access to this page», un campo de nota y **Request access**. No se revela nada más: ni
título, ni propietario, ni agent. Un visitante sin sesión o alguien de otra organización recibe
el not-found habitual.

#### Revisar una versión cambiada { #reviewing-a-changed-version }

Una solicitud `version` abre la página para el propietario en la versión pendiente, con sus
datos reales. La franja dice quién cambió los datos que muestra la versión, con **Review data change**. El
panel compara las page queries de la versión con la que ve ahora la audiencia, binding por
binding y en palabras: campos, filtros, orden, límite y tablas vinculadas añadidos, quitados o
cambiados, cada uno marcado **Shows more**, **Shows less** o sin cambio, los bindings nuevos
con su divulgación completa y los que no cambian plegados.

Un interruptor, **What others see**, muestra la página tal como la tiene la audiencia. El
panel nombra quién publicó la versión y cuándo, y enlaza a la conversación cuando el propietario
puede abrirla. **Approve** confirma la versión. **Decline** mantiene a la audiencia en la
versión anterior y marca la versión `declined` en su historial; una republicación posterior
vuelve a preguntar. En la lista de Requests una solicitud de versión ofrece **Review data
change**, no Approve: se confirma desde la revisión.

### Compartir una página desde un agent { #sharing-a-page-from-an-agent }

`share_artifact(name, visibility?, people?)` permite a un agent pedir que se comparta una
página: `visibility` es `team` u `org`, `people` son miembros por nombre completo o correo y
grupos por nombre, cada uno pedido con nivel de vista. **Nunca comparte nada**. Presenta una
solicitud `audience` para la persona a la que sirve el run — también el run del propio
propietario — y responde «Waiting for Alex to approve in the page's Share dialog». La
aprobación es una persona en la consola, con sesión iniciada como ella misma, nunca una llamada
a una herramienta.

Un nombre que no coincide con nadie, o con varias personas, se devuelve como informe, nunca se
adivina. No pide nada público: el enlace público solo se crea en la consola. Un run sin persona
detrás, como un visitante de un widget, no puede pedirlo.

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

Bajo la barra aparece una línea solo cuando algo requiere atención: una versión que espera
confirmación, una solicitud que revisar o fuentes que no se pueden leer. Una página
rechazada dice "This page's live data is not available to you." Un lector cuyas
fuentes no se pueden leer ve cuántas ("2 of 3 sources unavailable to you"). Un editor
ve además el motivo de cada fuente, con un enlace **Open the table** a la tabla vinculada.

Cuando un agent publica una versión nueva mientras alguien tiene abierta la actual,
la siguiente lectura (un refresco, manual o automático) lleva al lector a la versión
que ahora se le sirve: la página se vuelve a cargar, con sus propios datos. Un
lector que eligió una versión en el menú de versiones se queda en ella.

En una versión anterior no se leen datos en vivo. El visor dice "Live data only on
the current version." con **Open current** y, para un editor, **Restore** para esa
versión. Una restauración resuelve las page queries de la versión contra las tablas tal
como están ahora, así que es una query nueva cuando una tabla ha cambiado, y espera el
consentimiento como cualquier otra republicación.

### Cómo llegan los datos a la página { #how-the-data-reaches-the-page }

Cuando la consola abre una página pide una dirección firmada que lleva quién es el lector. La
ruta de contenido lee cada binding **una vez, al cargar**, y escribe el resultado en el script
de plataforma de la página, de modo que la primera llamada a `onData` ya tiene sus datos y no
sigue ningún viaje de ida y vuelta. Un [enlace público o un embed](#live-data-on-a-public-link) se
escribe del mismo modo, con requisitos más estrictos. No se inyecta nada para una miniatura, una
tarjeta ni una versión del historial.

El refresco y el refresco automático siguen usando la ruta de datos y un `postMessage` de la
consola, que ahora responde las mismas filas de page query a todos los que se sirve esa versión.
La ruta nunca se almacena en caché, la dirección es de vida corta y el contenido de un registro
se mantiene fuera de los logs. Un binding que no se puede leer a tiempo o que falla en la base
de datos se inyecta `unavailable` y la página se dibuja igualmente.

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
| Lecturas solo de los motivos (`rows=false`, la franja del editor) | Los mismos límites, contados aparte de las cargas de datos |
| Solicitudes de compartir | 10 por hora por persona y organización (audience, access y version) |

Un binding cortado dice `truncated: true`, con `limit` a `records` o `bytes` y
`count` como el número de registros servidos. `bytes` cubre también una lectura
cuyo coste medido se agotó antes de que los datos formados llenaran la parte que le
corresponde de la página.

El plazo se comprueba antes de cada consulta, sin cancelar ninguna: cada consulta dura como
máximo lo menor entre 2 s y lo que queda de los 5 s, y ninguna consulta empieza una vez
agotados los 5 s, así que una página responde en unos 5 s y el tiempo real puede llegar a unos
7 s.

Las cargas inyectadas cuentan para los 30 por minuto, igual que los refrescos. Pasado un
límite de peticiones la ruta de datos responde 429, la consola reintenta dos veces una
respuesta de ocupado, y una página servida con sus datos recibe bindings `busy`. Con Redis
caído, el suelo del límite de peticiones y el límite de cargas en curso cuentan por worker de
la API, y el tope por proceso sigue acotando cada worker.

### Quién puede publicar una página vinculada { #who-may-publish-a-bound-page }

Una página se vincula a una tabla solo si el spec del agent que la publica concede
lectura sobre ella, y la persona detrás del run lee cada tabla que alcanza la query,
y eso se comprueba al publicar la página o al restaurar una versión. Revocar cualquiera de
las dos más tarde no detiene las páginas ya publicadas; el acceso del propietario se vuelve a
comprobar en cada carga.

Una página vinculada solo puede **cambiarla** un run que actúe en nombre de miembro (una republicación sin cambios, con los mismos bytes y queries, no necesita
persona): el miembro con sesión iniciada (chat web, API HTTP), un remitente de canal
vinculado o el creador de una programación. Un visitante de un widget, un embed o
una página alojada, un remitente de canal no vinculado y la entrega de un trigger de
eventos de un agent (GitHub, correo, relé de webhooks) no cuentan, ni tampoco un run
de workflow admitido por una puerta pública ni nada en la cadena de ese run.

## Acciones { #actions }

Una página puede iniciar un [workflow](workflows.md), pero solo cuando una persona está de acuerdo.
La página no actúa: pide, la consola le muestra a la persona qué ocurriría, y el run es suyo.
Así una página se convierte en una pequeña app - un formulario que presenta una solicitud, un
botón que aprueba una factura - sin que la página tenga ningún poder propio.

### Declarar acciones { #declaring-actions }

El agent declara los workflows que una página puede iniciar cuando publica, con el argumento
`actions` de `publish_artifact`: hasta cinco entradas, cada una con un workflow (su id o nombre
exacto) y una **label**, la palabra con la que la página lo nombra.

```json
{"actions": [{"workflow": "Approve invoice", "label": "Approve"}]}
```

Un workflow puede ser una acción solo si se cumple todo esto:

- el agent que publica lo tiene en la [capability Workflows](reference/capabilities.md#workflows),
  de modo que lo que una página puede iniciar forma parte de lo que revisó el autor del agent;
- está activo (publicado, no archivado) y arranca desde un trigger **Manual** o **API**;
- la persona detrás del run puede verlo y ejecutarlo. Uno que no puede se responde como si
  no estuviera vinculado, así que un rechazo nunca nombra un workflow que la persona no ve.

La label es texto plano de como máximo 60 caracteres, sin caracteres de control ni invisibles;
si queda vacía, pasa a ser el nombre del workflow. Omitir `actions` conserva las de la versión
actual, y `[]` las quita. El resultado de la publicación lista cada acción declarada con palabras,
o dice `kept`. Una página Markdown no puede tener acciones. Un run sin nadie detrás no puede
añadirlas ni cambiarlas, y solo puede volver a publicar sin cambios una página que ya las tiene.
Restaurar una versión anterior vuelve a comprobar sus acciones contra el agent tal como está
ahora, y se rechaza si alguna ya no se sostiene.

Las acciones se guardan con la versión, así que una versión nueva sustituye la lista entera y una
anterior conserva la suya. Desvincular después un workflow del agent no edita una versión
publicada; el estado propio del workflow y el acceso de cada lector se comprueban cada vez que se
abre la página y de nuevo cuando se inicia un run.

### Quién ve qué acciones { #who-sees-which-actions }

Cuando la consola abre una página, lista las acciones que declara la **versión servida** y que
este lector puede ejecutar ahora: cada una con el nombre real del workflow, la label de la página
y los campos que pide su trigger. Una que el lector no puede ejecutar se omite. La franja del
visor muestra **This page can run: ...**, con los nombres de los workflows, cada uno un enlace a los
runs de ese workflow. Sin ninguna, no se muestra nada.

Una página no recibe acciones, y su llamada `run` se rechaza de inmediato, cuando se muestra:

- en un enlace público, en un embed, en una vista previa o en la miniatura de una tarjeta;
- como una versión anterior del historial, o una que no es la versión que se sirve a este lector
  (una audiencia aún espera el consentimiento para la más nueva);
- a un miembro que no puede ejecutar ninguno de sus workflows, o a una sesión suplantada.

La ruta de inicio rechaza todo lo mismo, así que una página que se saltara la consola no
ganaría nada.

### Ejecutar una desde la página { #running-one-from-the-page }

En la página, `agenticos.run(action, input)` - `AO.run` en el [kit de páginas](#the-library-set) -
le pide a la consola que inicie una acción. `action` es un id de workflow, la label de la página
o el nombre del workflow. La consola busca primero el id exacto, luego la label, luego el nombre,
sin distinguir mayúsculas. Un nivel que encaja con dos acciones no encuentra nada y no pasa al
siguiente. `input` es un objeto con exactamente los valores que declara el trigger del workflow.
La llamada devuelve una Promise del run terminado, y `onRun` (`AO.onRun`) oye cada cambio por el
camino:

```js
AO.run("Approve", { invoice: "INV-204" }).then(
  (run) => show(run.status, run.output_text),
  (error) => show("not run", error.message),
);
```

La consola no inicia nada hasta que la persona ha aceptado. Cada run, por muchos que hayan
precedido, abre un diálogo de confirmación:

- su título es el **nombre propio del workflow**, y la label de la página aparece solo como cita;
- muestra cada valor que envía la página, completo y como texto, con los caracteres que no
  dibujan nada o que reordenan el texto escritos (`\u{202E}`);
- **Run** está desactivado durante medio segundo y nunca recibe el foco, así que un clic que ya
  venía de camino no acepta; Cancel tiene el foco;
- hay una sola pregunta abierta a la vez, entre diálogos de run y de enlace, y una petición que
  llega mientras tanto se rechaza como `busy`;
- tras **tres rechazos** en una apertura de la página (recargar el frame conserva la cuenta) la
  consola deja de preguntar y rechaza más peticiones hasta que se vuelve a abrir la página.

Una petición se rechaza sin diálogo cuando es demasiado pronto (el frame no ha cargado), nombra
una acción que la página no declara, no encaja con los campos del workflow, o viene de algo que no
es el propio frame de la página bajo el nonce que la consola generó para esa carga. Un mensaje de
otro frame, o de una página obsoleta, se descarta sin respuesta.

La promesa se rechaza con un `Error` cuyo `message` es un código corto, para que la página
redacte su propio texto:

| Código | Cuándo |
|---|---|
| `cancelled` | La persona rechazó |
| `busy` | Había otra pregunta abierta |
| `too_many_cancels` | Tres rechazos; no se vuelve a preguntar a la página hasta que se reabra |
| `not_ready` | La página pidió antes de que su frame hubiera cargado |
| `unknown_action` | Ninguna acción declarada que el lector pueda ejecutar encaja |
| `invalid_input` | Falta un valor, es desconocido o de tipo erróneo; `error.problems` lista `{field, kind}` solo cuando el problema lo encontró la consola, y no está si respondió el servidor con 422 |
| `rate_limited` | Demasiados runs de esta persona, o la cuota de admisión del llamante o de la organización |
| `not_found`, `unavailable` | La acción ya no existe, ya no se puede iniciar a mano o está archivada, o la página no puede ejecutar acciones aquí en absoluto (un enlace público, un embed, una vista previa, el historial, un lector sin ninguna acción ejecutable) |
| `failed` | No se pudo iniciar o seguir el run |
| `page_changed` | La página se reemplazó mientras la pregunta estaba abierta |

### Qué es el run { #what-the-run-is }

El run es del **lector**: empieza con sus permisos y cuenta contra su budget, como si hubiera
ejecutado el workflow desde la consola. Su trigger es **App** (`app`), y registra la página y la
versión que miraba la persona. La página no confiere nada; el run se rechaza cuando la persona no
habría podido iniciarlo ella misma. Un run que espera una aprobación o que alguien lo mire se
queda en el [historial de runs](workflows.md#running-a-workflow) del workflow, y el visor muestra
una línea con **Open run**.

A la página nunca se le entrega el run entero. Lee una proyección: el estado, el texto de la
respuesta, la respuesta estructurada sin referencias a archivos, la primera línea de un error
(como máximo 200 caracteres) y, mientras el run espera a alguien, la ruta hasta él en la consola.
Solo puede leerlo la persona que inició el run, y solo a través de la página que lo inició.

La consola lee el run con un retardo creciente y envía cada cambio a la página. Un run que espera
a alguien se lee durante diez minutos con la pestaña visible. Pasado ese tiempo la promesa de la
página se resuelve con el último estado, `paused: true` y sin `finished`, y la página no oye nada
más; la línea del visor es el camino hasta el run. A una página que se recarga o se cierra no se le
dice nada.

### Límites y auditoría { #limits-and-audit }

| Límite | Valor |
|---|---|
| Acciones por página | 5 |
| Label | 60 caracteres |
| Runs iniciados desde una página | 10 por minuto por persona y página (`RATE_LIMIT_ARTIFACT_ACTIONS_PER_MINUTE`) |
| Rechazos antes de que la consola deje de preguntar | 3 por apertura de la página (recargar el frame conserva la cuenta) |
| Trabajo pendiente | la cuota de admisión propia de los runs de workflow, que también responde `rate_limited` |

Pasado un límite, la persona ve un mensaje y la página recibe `rate_limited`. Cada inicio se
audita como `artifact.action_started` con la página, la versión, el workflow y el run - nunca la
entrada, que es de la persona y está en el propio run. Consulta [gobernanza](governance.md#audit) y
[la página de seguridad](security.md#a-page-that-starts-workflows).

## Un nombre, un enlace { #one-name-one-link }

La identidad de una aplicación es su **nombre dentro del agent**: `weekly-report`,
`churn-dashboard`. Publicar con el mismo nombre actualiza la misma aplicación,
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
vuelve a publicar una aplicación existente solo cuando la persona por la que actúa
es su propietaria o tiene `artifacts:edit` sobre ella, por el rol o por un grant
`edit`: la misma regla que para gestionarla en la consola. Al run de cualquier
otra persona se le dice que el nombre está ocupado y publica con otro, así que un
compañero que pida al mismo agent compartido un `weekly-report` no puede
sustituir la página que hay detrás de tu enlace.

Cada publicación es una **versión** nueva. No se sobrescribe nada, así que la
lista de versiones en la página de la aplicación es su historial. Dos cosas mantienen
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
| `lib/agenticos-3.js` | `window.AO`: Chart.js con el estilo de la consola, formato de números en el idioma de la página, iconos, pestañas, `AO.onData`, `AO.records`, y `AO.run` y `AO.onRun` para las [acciones](#actions) |
| `lib/agenticos-2.css`, `lib/agenticos-2.js` | La versión anterior del kit, conservada para las páginas publicadas con ella |
| `lib/agenticos-1.css` | La primera versión del aspecto, conservada para las páginas publicadas con ella |
| `lib/three-0.186.0/three.module.js` | three.js 0.186.0 como módulo ES, con `addons/controls/OrbitControls.js` al lado - asigne `three` y `three/addons/` con un import map |
| `lib/mermaid-12.1.0.min.js` | Mermaid 12.1.0, como `window.mermaid` |
| `lib/leaflet-1.9.4/leaflet.js`, `leaflet.css` | Leaflet 1.9.4, como `window.L` - dibuja sobre las [teselas de mapa](#visuals) del despliegue, cuando las tiene |
| `lib/agenticos-map-2.js` | `window.AOMap.itinerary`: chinchetas numeradas mostradas en orden y que caen una a una cuando se pide, un mapa 16:9 del ancho de la página, una línea entre ellas y tarjetas para las paradas - sobre teselas de mapa, o sin ellas como un contorno de las paradas. `lib/agenticos-map-1.js`, que deja caer las chinchetas al cargar y tiene una sola altura, se sigue sirviendo a las páginas que lo nombran |
| `lib/agenticos-map-1.js` | `window.AOMap.itinerary`: chinchetas numeradas que caen en orden, una línea entre ellas, pausa y repetición, y tarjetas para las paradas - sobre teselas de mapa, o sin ellas como un contorno de las paradas |

Cada nombre lleva su versión y se guarda en caché un año. Una actualización añade
un archivo nuevo junto al antiguo, así que una página publicada con una versión
sigue recibiendo esa, y un archivo ya distribuido nunca se modifica. No se
descarga nada de fuera del despliegue, así que uno sin acceso a internet funciona
igual. Los archivos están en `backend/app/core/catalog/artifact_lib/`.

Los archivos responden `Access-Control-Allow-Origin: *`, porque un script de módulo se
descarga en modo CORS y una página en un origen opaco envía `Origin: null` - sin ello
three.js no se importaría.

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
Apps en el Builder lo ofrece. Edita el skill para describir tu propia marca,
y el agent la sigue.

### El contrato de página y los avisos de publicación { #the-page-contract-and-the-publish-warnings }

El agent no puede ver la página que publica, así que la plataforma le dice cómo
debe ser una página y qué parece estar mal en la que envió.

La capability Apps da a cada agent que la tiene un breve **contrato de
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
- `AO.onData`, `AO.records`, `AO.run` o `AO.onRun` en una página que no carga `lib/agenticos-3.js`;
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
consola los leería para ella, y cuentan contra su cupo de lecturas de datos. En un chat
de grupo solo se puede previsualizar una página de toda la organización, las mismas
páginas que la lista muestra allí, y se dibuja sin datos. También se dibuja sin datos
la página que previsualiza un run del que nadie responde: uno que un tercero inició por
un webhook, un formulario, un mensaje de canal, un correo o un evento de repositorio,
sea cual sea la identidad con la que se ejecute. Una superficie sin nadie con sesión
iniciada no previsualiza nada.

Nada de lo que pide la página llega a la red: la API responde a cada
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

## Visuals { #visuals }

Un [visual](reference/capabilities.md#visuals) es una aplicación que aún no se ha
guardado: un dibujo que un agente escribe en la conversación con `draw`, mostrado bajo
su mensaje mientras se escribe. Es el mismo tipo de documento - un visual `html` es una
página, y uno `svg` o `mermaid` se convierte en una página que lo contiene - y se dibuja
con el mismo aislamiento.

**El marco.** `/api/v1/artifact-content/visual-frame` es una página fija en el origen
de contenido, servida con la misma política que recibe la página de cada aplicación. No
contiene ningún dibujo: la consola se lo envía mientras llega, así que nada tiene que
guardarse antes de mostrarse, y el aislamiento viene de la cabecera de la respuesta y no
de una etiqueta meta en `srcdoc`. Mientras llega, el marco transforma el marcado en su
sitio, sin scripts ni atributos `on*`; al completarse escribe el documento entero para
que sus scripts se ejecuten, exactamente como en la página guardada. El marco informa de
su tamaño, sus errores y un latido; un dibujo que deja de latir se cierra en lugar de
bloquear la pestaña.

**En el chat.** Un dibujo está en la propia conversación, sin tarjeta alrededor,
desde el borde izquierdo del texto del mensaje: un SVG se ajusta por su `viewBox` y
se reduce por encima de 560 píxeles, una página se compone al ancho de la columna y
se reduce por encima de 900. Una línea discreta debajo lo nombra y dice si todavía
se está dibujando; *Mostrar código*, *Descargar* (`.svg`, `.html` o la fuente
Mermaid), *Copiar como imagen* para un SVG, *Guardar en Apps* y *Pantalla
completa* aparecen en esa línea cuando el puntero está sobre el dibujo, y siempre
en una pantalla táctil. Mientras se transmite, el dibujo conserva la altura que
declaró su llamada, sobre un tono suave, para que la conversación no se mueva bajo
el lector. La pantalla completa lo muestra a su propio tamaño; en un teléfono, un
toque abre la vista previa a pantalla completa. El zoom está en la esquina
inferior derecha del dibujo mientras el puntero está encima: un SVG se dibuja más
grande, una página se escala, y el marco se desplaza cuando el dibujo lo supera.
Un error que el dibujo informa llega con *Arreglarlo*, que se lo pide al agent.

**Mensajes de seguimiento.** Un control de un dibujo puede devolver la elección de
la persona a la conversación - *Planificar esta parada*, *Usar estas cifras* -
llamando a `agenticos.followUp(text)`. El dibujo solo lo pide. La consola muestra
el texto exacto bajo el dibujo con *Enviar*, *Editar* y *Descartar*, y se convierte
en el mensaje de la persona solo cuando hace clic en *Enviar*, un clic que el
dibujo no puede hacer por ella. Una petición sin interacción del usuario detrás -
al cargar, con un temporizador - se descarta, igual que una de más de 2.000
caracteres, y mientras una espera, otra no puede sustituirla. Los seguimientos solo
se ofrecen en el chat: `agenticos.canFollowUp()` es falso en un hilo compartido, en
el widget y en una app, donde `followUp` no hace nada y devuelve `false`, así que un
dibujo guardado sigue funcionando.

**Mapas.** Con [`VISUAL_MAP_TILES`](configuration.md#published-artifacts)
definido, un dibujo o una app pueden dibujar sobre teselas de mapa reales: el
despliegue trae cada tesela de ese servidor y la sirve desde su propia ruta de
teselas, `agenticos.map` dice dónde, y el kit de mapas dibuja sobre ella un
itinerario con el crédito del servidor debajo. Sin él, la misma llamada dibuja un
contorno de las paradas - chinchetas y la línea entre ellas, sin calles - y lo mismo
hace un mapa cuyas teselas no cargan. El agent lo dice en su respuesta: que no hay
un servidor de mapas conectado y que un administrador activa los mapas reales con
este ajuste. La imagen de un mapa en una app de chat se
dibuja terminada, con todas las chinchetas en su sitio.

**Elegir la forma.** El skill `visual-design` le dice al agent cuándo un dibujo es
siquiera la respuesta correcta: texto para un dato o un consejo, una tabla Markdown
para valores exactos, `create_chart` para cifras que ver - así «ahora en gráfico»
convierte una tabla en un gráfico nativo - y un dibujo para explicar cómo se mueve
algo, hacer una herramienta para el momento o seguir lugares en un mapa. Sus
plantillas son un diagrama, una explicación con controles deslizantes, un avión 3D
con cabeceo, alabeo y guiñada, una calculadora y un itinerario. Un chat vacío con
un agent que dibuja se abre con un iniciador para cada uno. Activar Visuals en el
Builder vincula también Charts.

**Descargarlo.** Un archivo abierto desde el disco no tiene marco alrededor, así que
la descarga lleva lo que imponía el marco. Un SVG conserva el dibujo y pierde lo que
podría ejecutarse o salir fuera: scripts, manejadores, documentos incrustados y
cualquier referencia fuera del archivo. Una página se abre con la política del marco
por delante de todo lo que escribió, y carga sus bibliotecas desde el origen de
artefactos de este despliegue.

**Guardarlo como aplicación.** *Guardar en Aplicaciones* toma un título y un nombre,
ambos rellenados, y publica el visual como versión de una aplicación bajo el agente
cuyo turno lo dibujó, en el entorno en el que corrió ese turno, propiedad de quien lo guarda y privada hasta que la comparta. El
servidor reconstruye el visual a partir de la transcripción - con las revisiones
aplicadas - en lugar de tomar bytes del navegador, así que la aplicación es exactamente
lo que dibujó el agente. Guardarlo con un nombre que la persona ya tiene añade una
versión a esa aplicación - así una revisión de un dibujo guardado actualiza la página con
la que se compartió. Guardar requiere `artifacts:edit`.

**Desde un delegado.** Un dibujo se queda en el run que lo hizo, así que un agente
que trabaja como delegado de otro agente no dibuja: `draw` se lo dice, y describe la
imagen en su resultado para que el agente para el que trabaja la dibuje en la
conversación.

## Quién puede abrirla { #who-can-open-it }

Un artefacto nuevo es **privado** para la persona en nombre de la cual actuó el
run que lo publicó: la persona del chat, o el creador de un trigger. Una página
privada también es visible para los roles Owner, Admin, Builder y Operator: su
`artifacts:view` tiene alcance `ALL`, así que abren todas las páginas de la organización
sea cual sea su visibilidad y sus grants (consulta los [alcances](permissions.md#scope)). Un
Member o Viewer solo abre lo que se comparte con él. Esos cuatro roles forman siempre parte de
la audiencia de una página, y toda divulgación los nombra.

Su enlace - al que apuntan la tarjeta del chat y la respuesta del agente - abre
la propia página (desde la tarjeta del chat, en una pestaña nueva), a toda la
ventana, bajo una única barra con el título, la versión y **Share**. El enlace
por sí solo no deja entrar a nadie: solo se abre para un miembro con sesión
iniciada al que las reglas de abajo ya dejan entrar.
Nombra la organización en la que está el artefacto (`?org=`), así que un miembro
de varias llega a la correcta.

En **Share**, cualquiera que pueda gestionarla puede compartirla de tres maneras:

| Alcance | Cómo | Quién |
|---|---|---|
| Personas concretas | Un grant, con `read`, `edit` o, para una página, `edit_data` («Can edit, including data») | Esos miembros, en esta organización |
| La organización | Visibilidad fijada a toda la organización | Todo miembro cuyo rol alcance los artefactos compartidos |
| Cualquiera con el enlace | **Create a public link** | Cualquiera que tenga la dirección, sin cuenta |

Compartir y la visibilidad usan el mismo panel y las mismas reglas que los agents
y los skills; consulta [Permisos](permissions.md). Gestionar una aplicación
(compartirla, su enlace público y sus ajustes, restaurar una versión, borrarla)
requiere `artifacts:edit` sobre esa aplicación, desde el rol o desde un grant
`edit`. Abrirla requiere `artifacts:view`.

El agent no puede ampliar quién lee una página. Publica, y `share_artifact` solo presenta una
solicitud; una persona decide quién la ve. Por eso la capability no pide aprobación por defecto:
una primera publicación es privada, y lo que muestra una página vinculada lo condiciona el
[consentimiento](#consent-the-owner-decides-who-reads-the-data) de su propietario. Un autor que
quiera que una persona apruebe cada nueva publicación de una página ya compartida, o de una
página vinculada, fija `tool_approval` en `publish_artifact` en el spec. Una página vinculada
solo puede volver a publicarla un run que actúe en nombre de un miembro (consulta
[Datos en vivo](#live-data)).

### Compartir una página en vivo { #sharing-a-live-page }

Abrir una [página en vivo](#live-data) muestra sus datos a cualquiera a quien se sirva, leídos
con el acceso del propietario y no con el suyo, así que ampliar quién puede abrirla es decisión
del propietario. El propietario, o un Owner o Admin por él, la amplía directamente en el diálogo
de compartir una vez confirmados los datos; el intento de cualquier otro editor se convierte en
una [solicitud](#share-requests). Estrechar está abierto a todo editor.

### El enlace público { #the-public-link }

Un enlace público es `/a/<key>` en la propia dirección de la consola, con una
clave aleatoria de 192 bits: la misma regla que sigue la clave de la página de
chat alojada. No dice nada de quién la publicó ni de a qué organización pertenece.

**Replace the link** emite una clave nueva, y la antigua deja de abrir nada al
instante. **Turn off** lo elimina. Ambas acciones quedan registradas en el
registro de auditoría. Una página que alguien ya tiene abierta sigue mostrando lo que
tiene, pero al recargarla, o al abrir de nuevo su dirección de contenido, responde 404
de inmediato: la dirección nombra la clave del enlace, y la ruta comprueba esa clave en
cada carga. La vida de la propia dirección, `ARTIFACT_VIEW_TTL_SECONDS` (cinco minutos
por defecto), es solo el límite exterior.

Un miembro revocado está en la misma situación que antes: pierde la aplicación en su
siguiente petición, y una página que ya tenía abierta se mantiene como mucho
durante esa misma ventana.

Bajo el enlace, **Share** guarda sus ajustes. Se mantienen cuando se sustituye el
enlace, y un enlace que se apaga y se vuelve a encender los conserva:

| Ajuste | Qué hace |
|---|---|
| **Stops opening after** | Una fecha a partir de la cual el enlace no abre nada, como si estuviera apagado |
| **Shows** | La versión más reciente, o una versión conservada fijada para que una publicación nueva no cambie lo que ya vieron quienes tienen el enlace. Una versión fijada nunca se elimina |
| **Password** | Se pide antes de abrir la página. El enlace no dice nada — ni el título, ni cuándo se publicó — hasta que es correcta. Se guarda como hash y no vuelve a mostrarse; cada intento cuenta contra el límite de peticiones del enlace. Cambiarla o quitarla pone fin a las direcciones abiertas con la antigua: no llevan datos |
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

Un embed lleva los datos de una página en las mismas condiciones que su enlace; consulta
[Datos en vivo en un enlace público](#live-data-on-a-public-link). Añadir un sitio amplía
quién lee esos datos, así que borra el consentimiento de datos.

### Datos en vivo en un enlace público { #live-data-on-a-public-link }

La caducidad del enlace público también rechaza tokens de contenido público emitidos previamente, antes de cargar el documento. Un token emitido justo antes del corte no prolonga el enlace durante su propia vigencia. Los tokens de miembros siguen sujetos a su acceso y caducidad.

Una [página vinculada](#live-data) muestra sus registros en su enlace público y en sus embeds
solo cuando se han tomado dos decisiones distintas, y una tercera comprobación se cumple en cada
carga. Sin ellas, la página pública se muestra tal como se publicó, con todos los bindings
`unavailable`.

1. **La organización lo permite.** Un Owner o Admin activa **Public pages with
   live data** en los ajustes de la organización. Está desactivado por defecto, avisa antes de
   activarse y debe cambiarse con la sesión iniciada como uno mismo, nunca en nombre de
   otra persona. Es un interruptor de emergencia, no un reinicio: al desactivarlo se ocultan
   los datos de todas las páginas públicas y embeds en la siguiente carga y se deja intacto
   el consentimiento de cada página, de modo que al volver a activarlo se restauran las
   páginas cuyo consentimiento sigue vigente.
2. **El propietario de la página lo confirma para el enlace.** En los ajustes del enlace,
   dentro de **Share**, **Confirm data** abre una pantalla con lo que muestra el consentimiento
   de los miembros - las page queries de la versión servida en palabras, cada tabla vinculada
   a la que llegan - y quién puede leerlos: cualquiera con el enlace, sin cuenta y sin iniciar
   sesión, si una contraseña lo protege, cuándo caduca y cada sitio que lo incrusta. El
   propietario, o un Owner o Admin en su nombre, lo confirma con la sesión iniciada como
   uno mismo; un grant `edit` no basta. Exige que el enlace esté activado, que el interruptor
   de la organización esté activado y el
   [consentimiento](#consent-the-owner-decides-who-reads-the-data) de los miembros para esa
   versión. Cualquier editor puede retirarlo, con la sesión iniciada como uno mismo; un Owner
   o Admin no puede hacerlo suplantando a uno.
3. **Todas las comprobaciones se cumplen en cada carga.** Consulta
   [qué recibe un visitante anónimo](#what-an-anonymous-visitor-gets).

La confirmación es para la versión que sirve el enlace - la fijada, o si no la que se sirve
a la audiencia de la página - y queda ligada a dos digests: la huella de sus page queries y un
digest de a quién llega el enlace (los sitios que lo incrustan, si hay una contraseña, si el
enlace está activado). Se rechaza con un conflicto si cualquiera de los dos cambió después de
dibujarse la pantalla. Se registra bajo la membresía del propietario y se audita por nombres
de tablas y columnas, nunca por fila.

#### Qué la anula y qué no { #what-voids-it-and-what-does-not }

Todo lo que amplía la audiencia o cambia de quién son los datos borra el consentimiento, auditado
como `artifact.public_data_voided` con el motivo. Volver a activarlo exige una nueva
confirmación.

| Anula el consentimiento | No lo afecta |
|---|---|
| Desactivar el enlace o archivar la página | Sustituir la clave del enlace: cambia la dirección, no los datos |
| Quitar la contraseña | Cambiar la contraseña, la caducidad del enlace o la versión fijada |
| Añadir un sitio que incrusta | Quitar un sitio que incrusta |
| Entregar la página a otro propietario | Que el interruptor de la organización se desactive |
| Retirar el consentimiento de los miembros para los datos | |

Una versión fijada distinta, o una nueva publicación que cambie las page queries, no anula el
consentimiento pero hace que deje de valer: la huella de la versión servida ya no coincide, así
que la página pública no muestra datos hasta que alguien vuelva a confirmar. Un enlace caducado
tampoco sirve nada.

El propietario y los demás editores ven el motivo en la franja sobre la página: el interruptor
está desactivado, el enlace no sirve ninguna versión, las queries cambiaron, el propietario se
fue o cambió, falta el consentimiento de los miembros o el enlace caducó.

#### Qué recibe un visitante anónimo { #what-an-anonymous-visitor-gets }

A un visitante no se le dice nada sobre el motivo. Antes de leer nada, cada carga comprueba que
el enlace aún tiene la clave para la que se emitió la dirección, que no ha caducado, que el
estado de la contraseña es el que tenía la dirección al abrirse, que la versión sigue siendo la
que sirve el enlace, que el interruptor de la organización está activado y que se cumplen el
consentimiento de datos de la página y el de los miembros. Si algo falla, la página se muestra
con todos los bindings `unavailable` y sin motivo.

Después se comprueba cada binding por separado: el propietario debe seguir siendo un miembro
activo que lee la tabla, y la tabla no debe haberse desviado de la query. Un binding que falla
ahí queda `unavailable`; los demás se cargan igualmente.

Los registros se escriben en la página al cargar y son los de esa carga. La página pública y el
embed no tienen Refresh ni ruta de datos, y la página no puede pedir más; el visitante recarga
para ver un cambio. Una clave rotada o eliminada da un 404, no una página sin datos, y una
contraseña cambiada o eliminada da a una dirección antigua una página sin datos.

#### La caché y el tope { #the-cache-and-the-cap }

Una carga anónima cuesta lecturas de tablas, así que las lecturas se comparten. Los registros de
un binding se guardan 30 segundos en la memoria del proceso de la API, con la versión, el
binding, la huella de las queries y la membresía del propietario como clave - **nunca en Redis**,
porque son registros. Todas las comprobaciones anteriores se ejecutan antes de consultar la
caché, así que una organización con el interruptor desactivado, una clave rotada o un
consentimiento retirado surten efecto al instante, sea lo que sea lo que se haya guardado. Una
lectura fallida o `unavailable` nunca se guarda.

La memoria está acotada: `ARTIFACT_PUBLIC_DATA_CACHE_BYTES` (32 MiB por defecto) y 64 lecturas
por proceso, descartando primero las menos usadas recientemente, y una lectura mayor que el
presupuesto no se guarda. Aparte, cada página puede leer de sus tablas
`RATE_LIMIT_ARTIFACT_PUBLIC_DATA_PER_MINUTE` veces por minuto (60) entre todos sus visitantes.
Una carga que tiene que leer de las tablas cuenta una vez, así que una página muy visitada queda
acotada por el tope y no por su audiencia. Pasado el tope, o mientras el proceso ya sirve tantas
cargas de datos como puede, un binding que necesita una lectura vuelve `unavailable` para ese
visitante.

## Cómo se aísla la página { #how-the-page-is-isolated }

Una aplicación es HTML con script dentro, escrita por un modelo que puede haber
leído algo hostil. Se sirve de forma que nada de lo que haga pueda alcanzar la
consola ni a la persona que la mira:

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
  origen del contenido, para scripts, estilos y fuentes. En un despliegue que define `VISUAL_MAP_TILES`, se suman las imágenes de su propia ruta de teselas, `/api/v1/artifact-content/tiles/{z}/{x}/{y}`. Esa ruta toma tres números, cada uno comprobado contra el zoom en el que puede existir, y trae la tesela ella misma, así que una página nunca conoce la dirección ni la clave del servidor de teselas y no puede enviarle nada que haya elegido. `frame-ancestors` nombra
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
  que enviaría sus cifras. Un [mensaje de seguimiento](#visuals) es el mismo tipo de petición: la consola muestra el texto y lo envía una persona.
- Los datos en vivo llegan a la página de un miembro de dos maneras, ambas decididas por lector
  en el servidor. Al cargar, la ruta de contenido escribe los registros de cada binding en el
  script de plataforma de la página para el miembro que nombra la dirección firmada; un refresco
  llega por `postMessage` desde la consola, que lo obtiene de la ruta de datos con la propia
  sesión del lector. La petición de la página lleva un nonce que permite a la consola emparejar
  cada respuesta con la carga de página correcta; eso es **correlación, no control de
  acceso**. Un enlace público o un embed recibe sus datos solo al cargar, escritos por el
  servidor, y nunca los pide: no tiene ruta de datos ni refresco. Consulta
  [datos en vivo en un enlace público](#live-data-on-a-public-link) y
  [la página de seguridad](security.md#a-pages-data-and-its-address).
- Una página puede pedir que se inicie un [workflow](#actions) a través del mismo puente, con
  `agenticos.run`, y solo lo ofrece el visor de página de la consola: la dirección lleva el
  derecho a pedir, y un enlace público, un embed, una vista previa y una miniatura rechazan la
  llamada de inmediato. La petición vuelve a ser **solo una petición**. La consola la acepta de su
  propio frame bajo el nonce de esa carga, la empareja con una acción que el servidor listó para
  este lector y la versión servida, y le pregunta a la persona en un diálogo antes de que empiece
  nada. El run es entonces suyo, así que una página manipulada por prompt injection puede hacer que
  la persona lea una pregunta, nunca responderla por ella.
- Una dirección firmada carga su página unas pocas veces por minuto como mucho,
  contadas por dirección antes de leer nada. La consola y la página pública
  emiten una dirección nueva cada vez que dibujan el frame, y emitirla a través
  de un enlace público ya está limitado por enlace.

La lista **Apps** dibuja la página actual de cada tarjeta como una
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
- **Las listas.** La lista Apps y el widget del dashboard la omiten. Elige
  **Archived included** en la lista para verla, marcada como **Archived**. Solo la ven
  quienes pueden editarla.
- **El enlace público y el embed.** Ninguno de los dos abre nada.
- **El agent.** `publish_artifact` rechaza el nombre con un mensaje que menciona
  el archivado, así que un run no puede crear una segunda página con él.
  `read_artifact`, `preview_artifact` y `list_artifacts` tratan la página como
  inexistente. Un run que no puede editar la página solo oye que el nombre no es
  suyo para cambiarlo.

Archivar desactiva el enlace público, auditado como
`artifact.public_link_disabled`, y borra su
[consentimiento de datos](#what-voids-it-and-what-does-not). Restaurar no vuelve a activar
ninguno de los dos. Una dirección enviada antes del archivado sigue muerta hasta que alguien
crea una nueva desde **Share**. Para eso se conservan la caducidad del enlace, la versión
fijada, la contraseña y los sitios que pueden incrustarlo.

Por la API, `POST /api/v1/artifacts/{id}/archive` archiva una página, y
archivarla de nuevo no cambia nada. `POST /api/v1/artifacts/{id}/unarchive` la
restaura, y responde `400` para una página que no está archivada. Ambas piden el
derecho a editar esa página, grant incluido. `GET /api/v1/artifacts` enumera las
páginas archivadas, a quienes pueden editarlas, solo con `include_archived=true`, y
`archived_at` en cada página dice cuándo se archivó.

## Seguir una página { #following-a-page }

**Seguir**, en la barra de una página, deja un aviso en tu bandeja cada vez que
la página recibe una versión nueva: un agente la volvió a publicar con otro
contenido, o alguien restauró una versión anterior. Una republicación que no
cambia nada no avisa a nadie, así que una programación que no encontró nada
nuevo no hace ruido. La persona cuyo run o restauración creó la versión no recibe
aviso de su propio cambio.

Seguir no da acceso. Cualquiera que pueda abrir la página puede seguirla, y quien
pierde el acceso deja de recibir avisos sin tener que dejar de seguirla. La
bandeja vuelve a comprobar el acceso al leerse, de modo que un aviso sobre una
página que ya no puedes abrir desaparece con ese acceso. El aviso también puede
llegar por correo; cada canal se desactiva en **Settings → Notifications →
App updated**.

## Retención y borrado { #retention-and-deletion }

Las aplicaciones son una [clase de retención](governance.md#the-classes) propia,
medida desde la **última publicación**: un informe que se vuelve a publicar cada
semana está vivo por antigua que sea su primera versión. Como toda clase, conserva
las aplicaciones para siempre hasta que una organización o el despliegue fijen un
periodo.

Borrar una aplicación, a mano o por retención, elimina todas sus versiones, sus
bytes almacenados, sus grants y su enlace público. Una página archivada envejece
y se borra como cualquier otra. Borrar el agent no borra sus
aplicaciones: siguen legibles y simplemente no tienen quien las publique. Borrar un
entorno con nombre hace lo mismo con las páginas publicadas desde él, así que
nunca caen sobre la página del entorno por defecto con el mismo nombre. Borrar la
organización las elimina. Las aplicaciones de una persona borrada se quedan y
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
- **Todos leen la vista del propietario de los datos.** Una page query se lee con el
  acceso del propietario, así que una página es para datos que pueden ver todos los que puedan
  abrirla. Una page query no tiene búsqueda de texto libre, ni filtro por lector como «me» o
  «today», ni límite de fila o de columna más allá de la propia query.
- **Un enlace público o un embed recibe datos solo tras dos confirmaciones.** La organización
  tiene que permitirlo y el propietario de la página tiene que confirmarlo para el enlace; hasta
  entonces una página vinculada muestra «unavailable» ahí. Lo que muestra es el estado de la
  carga, sin refresco, con hasta 30 segundos de antigüedad, y leído con el acceso del propietario
  para personas a las que el propietario no conoce. Un despliegue que no pueda aceptarlo deja el
  interruptor desactivado. Consulta [datos en vivo en un enlace público](#live-data-on-a-public-link).
- **Una página actúa solo mediante sus acciones declaradas.** Un formulario o un botón no
  tiene adónde enviar lo que recoge, salvo para iniciar uno de los hasta cinco workflows que su
  publicador declaró, que la persona confirma cada vez y que se ejecutan como ella. No puede
  llamar a una API, escribir un registro ni enviar un mensaje por sí misma, y solo recibe de vuelta
  el estado y la respuesta de un run. Consulta [acciones](#actions).
- **Una página abierta sobrevive a un grant revocado durante la vida de una
  dirección firmada**, cinco minutos por defecto. Desactivar un enlace público o sustituir su
  clave lo termina en la siguiente carga.
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
- **Un visual solo se dibuja en el chat web y en un hilo compartido.** Una app de
  chat recibe una imagen de él donde `VISUAL_RENDER_CDP_URL` nombra un navegador, y
  su título en otro caso; el widget y una incrustación en otro sitio muestran su
  título.
- **Un hilo compartido muestra sus doce visuals más recientes**, y no más de 16 MB
  entre todos. Cualquiera con el enlace puede abrirlo tantas veces como quiera, así
  que una vista está acotada; un turno más allá de cualquiera de los dos límites
  conserva su texto y no muestra el dibujo.

## Resumen { #recap }

- Una capability, cinco herramientas: `publish_artifact`, desde un archivo del
  workspace, en línea o como cambios; `read_artifact` para volver a leer una
  página; `list_artifacts` para encontrar una; `preview_artifact` para verla
  dibujada, con sus errores; y `share_artifact` para pedir que se comparta una página.
- El agent, el entorno y el nombre son la identidad; volver a publicar conserva el
  enlace y añade una versión, y cualquier versión conservada se puede restaurar.
- Privado por defecto; compartido por una persona mediante grants, la
  organización o un enlace público. El enlace público puede caducar, fijar una
  versión, pedir una contraseña e incrustarse en los sitios enumerados.
- Una página puede vincularse a una page query — una tabla, filtros, un orden, un límite y
  campos — y mostrar datos en vivo, leídos en el momento de verla con el acceso de su
  propietario, solo cuando el propietario ha confirmado compartirlos, y nunca guardados en la
  página. Cualquiera con edit puede retirar ese consentimiento; ampliar quién puede abrir una
  página vinculada es del propietario, o una solicitud. Un enlace público o un embed muestra
  los datos solo cuando un Owner o Admin lo ha permitido para la organización y el propietario
  lo ha confirmado para el enlace, y borrar la audiencia del enlace borra esa confirmación.
- Una página puede declarar hasta cinco workflows que un agent ha vinculado; sus botones piden a
  la consola que inicie uno con `AO.run`, y el lector confirma cada run en un diálogo que nombra
  el workflow real y muestra cada valor. El run es del lector, con el trigger `app`, y la página
  solo lee de vuelta su estado y su respuesta.
- El propietario puede entregar una página a otro miembro, que debe volver a confirmar sus datos.
- Un breve contrato de página en las instrucciones de cada agent con Artifacts,
  y avisos en el resultado de la publicación sobre lo que parece estar mal en el
  marcado.
- Servido desde una ruta sin cookies, en un origen opaco sin red salvo el propio
  conjunto de bibliotecas del despliegue, con enlaces que preguntan antes de
  abrirse, y opcionalmente desde un dominio propio.
- Archivar conserva una página y no sirve nada de ella, con el enlace público
  desactivado, hasta que alguien que puede editarla la restaura.
- Una clase de retención propia, medida desde la última publicación.
