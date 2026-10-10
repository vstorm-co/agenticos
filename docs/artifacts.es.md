---
source_sha: "f3a9cc7f1767"
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

Activa la capability **Artifacts** para el agent. Añade dos herramientas:
`publish_artifact`, que el modelo llama cuando el resultado es algo que una
persona debería abrir en lugar de leerlo una vez en el chat, y `read_artifact`,
que vuelve a leer una página publicada.

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
Queda registrado en el registro de auditoría.

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
    llamada a una API fallan todos. La única excepción es el conjunto de
    bibliotecas de abajo, que el propio despliegue sirve. La herramienta se lo dice
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
| `lib/agenticos-2.css` | El aspecto de la consola para páginas, claro y oscuro, y los componentes `ao-` con los que se construye una página |
| `lib/agenticos-2.js` | `window.AO`: Chart.js con el estilo de la consola, formato de números en el idioma de la página, iconos, pestañas |
| `lib/agenticos-1.css` | La primera versión del aspecto, conservada para las páginas publicadas con ella |

Cada nombre lleva su versión y se guarda en caché un año. Una actualización añade
un archivo nuevo junto al antiguo, así que una página publicada con una versión
sigue recibiendo esa. No se descarga nada de fuera del despliegue, así que uno sin
acceso a internet funciona igual. Los archivos están en
`backend/app/core/catalog/artifact_lib/`.

El [skill](skills.md) incluido **`artifact-pages`** enseña a un agent a usarlos: dos
plantillas (un dashboard y un informe), el estilo de la casa con sus componentes,
iconos en lugar de emoji y cómo cambiar una
página con `read_artifact`. Una organización nueva lo recibe con los demás skills
incluidos, una existente con `seed-skills`, y la pestaña **Page style** de la
capability Artifacts en el Builder lo ofrece. Edita el skill para describir tu
propia marca, y el agent la sigue.

## Quién puede abrirlo { #who-can-open-it }

Un artefacto nuevo es **privado** para la persona en nombre de la cual actuó el
run que lo publicó: la persona del chat, o el creador de un trigger.

Su enlace - al que apuntan la tarjeta del chat y la respuesta del agente - abre
la propia página, a toda la ventana, bajo una única barra con el título, la
versión y **Share**. El enlace por sí solo no deja entrar a nadie: solo se abre
para un miembro con sesión iniciada al que las reglas de abajo ya dejan entrar.
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
publicación es privada. Un autor que quiera que una persona apruebe cada nueva
publicación de una página ya compartida fija `tool_approval` en
`publish_artifact` en el spec.

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
Fija la variable para el backend y para el frontend, que añade ese origen a su
`frame-src`. Consulta [Configuración](configuration.md#published-artifacts).

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
Artifact updated**.

## Retención y borrado { #retention-and-deletion }

Los artefactos son una [clase de retención](governance.md#the-classes) propia,
medida desde la **última publicación**: un informe que se vuelve a publicar cada
semana está vivo por antigua que sea su primera versión. Como toda clase, conserva
los artefactos para siempre hasta que una organización o el despliegue fijen un
periodo.

Borrar un artefacto, a mano o por retención, elimina todas sus versiones, sus
bytes almacenados, sus grants y su enlace público. Borrar el agent no borra sus
artefactos: siguen legibles y simplemente no tienen quien los publique. Borrar un
entorno con nombre hace lo mismo con las páginas publicadas desde él, así que
nunca caen sobre la página del entorno por defecto con el mismo nombre. Borrar la
organización los elimina. Los artefactos de una persona borrada se quedan y
pierden su propietario, igual que sus agents y skills.

Los bytes viven en el [almacenamiento de archivos](configuration.md#uploaded-files-at-rest)
del despliegue, bajo `artifacts/<organization>/<artifact>/`.

## Limitaciones { #limitations }

- **Un único documento autocontenido por versión.** Sin paquetes, y sin red desde
  dentro de la página más allá del conjunto de bibliotecas servido.
- **Sin datos en vivo.** Un dashboard muestra los datos con los que se publicó. Se
  actualiza cuando el agent vuelve a publicar; una programación es la forma
  habitual.
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

## Resumen { #recap }

- Una capability, dos herramientas: `publish_artifact`, desde un archivo del
  workspace, en línea o como cambios, y `read_artifact` para volver a leer una
  página.
- El agent, el entorno y el nombre son la identidad; volver a publicar conserva el
  enlace y añade una versión, y cualquier versión conservada se puede restaurar.
- Privado por defecto; compartido por una persona mediante grants, la
  organización o un enlace público. El enlace público puede caducar, fijar una
  versión, pedir una contraseña e incrustarse en los sitios enumerados.
- Servido desde una ruta sin cookies, en un origen opaco sin red salvo el propio
  conjunto de bibliotecas del despliegue, con enlaces que preguntan antes de
  abrirse, y opcionalmente desde un dominio propio.
- Una clase de retención propia, medida desde la última publicación.
