---
source_sha: "abc239ffbca4"
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

Activa la capability **Artifacts** para el agent. Añade una herramienta,
`publish_artifact`, y el modelo la llama cuando el resultado es algo que una
persona debería abrir, en lugar de leerlo una vez en el chat.

La página sale de uno de dos sitios:

- **Un archivo del workspace del agent**, terminado en `.html` o `.md`. Es el
  caso habitual para un agent con la capability [Archivos y shell](reference/capabilities.md#files-shell):
  escribe `report.html`, ejecuta lo que haga falta para construirlo y después
  publica el archivo. Los bytes se leen a través del propio backend de workspace
  del run, así que funciona con todos los backends de sandbox.
- **La página pasada en línea**, para un agent sin workspace o una página corta.

El chat muestra una tarjeta para la página publicada. La tarjeta enlaza a la
versión que publicó *este* run, así que leer la conversación más tarde sigue
mostrando lo que se publicó en ella, no lo que la página muestra hoy.

## Un nombre, un enlace { #one-name-one-link }

La identidad de un artefacto es su **nombre dentro del agent**: `weekly-report`,
`churn-dashboard`. Publicar con el mismo nombre actualiza el mismo artefacto,
desde cualquier superficie: el chat, la API, un [trigger](triggers.md) o un
workflow. Un nombre nuevo crea una página nueva. El nombre admite letras
minúsculas, dígitos y guiones, hasta 64 caracteres.

Cada publicación es una **versión** nueva. No se sobrescribe nada, así que la
lista de versiones en la página del artefacto es su historial. Dos cosas mantienen
ese historial acotado:

- Publicar exactamente los bytes que ya contiene la versión actual no añade
  ninguna versión. El resultado dice `unchanged`, y una programación que no
  encontró nada nuevo deja el historial en paz.
- Solo se conservan las versiones más recientes, `ARTIFACT_MAX_VERSIONS` de
  ellas (20 por defecto). Una versión antigua se elimina cuando llega una nueva.
  Una conversación que enlaza a una versión eliminada dice que esa versión ya no
  se conserva y ofrece la última.

## Formatos admitidos { #supported-formats }

| Formato | Qué se guarda | Qué se sirve |
|---|---|---|
| HTML (`.html`, `.htm`, o `format: html`) | El documento tal como lo escribió el agent | El mismo documento |
| Markdown (`.md`, `.markdown`, o `format: markdown`) | El código fuente Markdown | El código fuente renderizado en una página sencilla, tablas incluidas. El HTML en bruto que contenga se escapa |

Una versión es un único documento autocontenido de como máximo
`ARTIFACT_MAX_BYTES` (5 MiB por defecto). No hay paquetes de varios archivos:
incrusta la hoja de estilos, el script y las imágenes (como URI `data:`) en el
único archivo.

!!! warning "La página no tiene red"

    Los scripts se ejecutan, así que un gráfico dibujado por una librería
    incrustada funciona. Pero la página no puede cargar nada de ningún sitio ni
    enviar nada a ninguna parte: un script de una CDN, una fuente web desde una
    URL y una llamada a una API fallan todos. La herramienta se lo dice al
    modelo. Es deliberado, y la siguiente sección explica por qué.

## Quién puede abrirlo { #who-can-open-it }

Un artefacto nuevo es **privado** para la persona en nombre de la cual actuó el
run que lo publicó: la persona del chat, o el creador de un trigger. Desde su
página en **Artifacts**, cualquiera que pueda gestionarlo puede compartirlo de
tres maneras:

| Alcance | Cómo | Quién |
|---|---|---|
| Personas concretas | Un grant, con `read` o `edit` | Esos miembros, en esta organización |
| La organización | Visibilidad fijada a toda la organización | Todo miembro cuyo rol alcance los artefactos compartidos |
| Cualquiera con el enlace | **Create a public link** | Cualquiera que tenga la dirección, sin cuenta |

Compartir y la visibilidad usan el mismo panel y las mismas reglas que los agents
y los skills; consulta [Permisos](permissions.md). Gestionar un artefacto
(compartirlo, su enlace público, borrarlo) requiere `artifacts:edit` sobre ese
artefacto, desde el rol o desde un grant `edit`. Abrirlo requiere
`artifacts:view`.

El agent no puede ampliar quién lee una página. Publica; una persona decide quién
la ve. Por eso la capability no pide aprobación por defecto: una primera
publicación es privada. Un autor que quiera que una persona apruebe cada nueva
publicación de una página ya compartida fija `tool_approval` en
`publish_artifact` en el spec.

### El enlace público { #the-public-link }

Un enlace público es `/a/<key>` en la propia dirección de la consola, con una
clave aleatoria de 192 bits: la misma regla que sigue la clave de la página de
chat alojada. Siempre muestra la última versión y no dice nada de quién la
publicó ni de a qué organización pertenece.

**Replace the link** emite una clave nueva, y la antigua deja de abrir nada al
instante. **Turn off** lo elimina. Ambas acciones quedan registradas en el
registro de auditoría. Una página que alguien ya tiene abierta se sigue mostrando
hasta que caduca su dirección de contenido firmada, como máximo
`ARTIFACT_VIEW_TTL_SECONDS` (cinco minutos por defecto).

Un miembro revocado está en la misma situación: pierde el artefacto en su
siguiente petición, y una página que ya tenía abierta se mantiene como mucho
durante esa misma ventana.

## Cómo se aísla la página { #how-the-page-is-isolated }

Un artefacto es HTML con script dentro, escrito por un modelo que puede haber
leído algo hostil. Se sirve de forma que nada de lo que haga pueda alcanzar la
consola ni a la persona que lo mira:

- Los bytes salen de una ruta aparte, `/api/v1/artifact-content/<token>`, que
  no lee ninguna cookie ni ninguna sesión. El token está firmado, nombra una sola
  versión y caduca en minutos. Solo se emite después de que un grant o un enlace
  público haya admitido a quien llama.
- Cada respuesta de contenido lleva `Content-Security-Policy: sandbox
  allow-scripts allow-popups allow-popups-to-escape-sandbox allow-modals`,
  sin `allow-same-origin`. La página se ejecuta en un origen opaco, así que no
  puede leer las cookies, el almacenamiento ni la página de la consola, y una
  petición que hiciera no llevaría nada del lector. Eso se mantiene incluso
  cuando alguien abre la dirección de contenido por sí sola.
- La misma política fija `default-src 'none'` y `connect-src 'none'` sin ningún
  origen remoto, y `frame-ancestors` nombra solo la consola. El frame de la
  consola lleva la misma lista `sandbox` como segundo cerrojo.

Además, un despliegue puede servir el contenido desde un **dominio registrable
aparte** fijando `ARTIFACT_ORIGIN`, por ejemplo
`https://agenticos-content.example.net`, enrutado a la misma API. La página queda
entonces en otro sitio por completo. El origen opaco ya la aísla, así que esto es
un endurecimiento que puede pedir una revisión de seguridad, no un requisito.
Fija la variable para el backend y para el frontend, que añade ese origen a su
`frame-src`. Consulta [Configuración](configuration.md#published-artifacts).

## Retención y borrado { #retention-and-deletion }

Los artefactos son una [clase de retención](governance.md#the-classes) propia,
medida desde la **última publicación**: un informe que se vuelve a publicar cada
semana está vivo por antigua que sea su primera versión. Como toda clase, conserva
los artefactos para siempre hasta que una organización o el despliegue fijen un
periodo.

Borrar un artefacto, a mano o por retención, elimina todas sus versiones, sus
bytes almacenados, sus grants y su enlace público. Borrar el agent no borra sus
artefactos: siguen legibles y simplemente no tienen quien los publique. Borrar la
organización los elimina. Los artefactos de una persona borrada se quedan y
pierden su propietario, igual que sus agents y skills.

Los bytes viven en el [almacenamiento de archivos](configuration.md#uploaded-files-at-rest)
del despliegue, bajo `artifacts/<organization>/<artifact>/`.

## Limitaciones { #limitations }

- **Un único documento autocontenido por versión.** Sin paquetes, y sin red desde
  dentro de la página.
- **Sin datos en vivo.** Un dashboard muestra los datos con los que se publicó. Se
  actualiza cuando el agent vuelve a publicar; una programación es la forma
  habitual.
- **El agent no puede volver a leer sus artefactos.** Un informe se reconstruye a
  partir de sus datos, no se edita desde la última versión.
- **Una página abierta sobrevive a una revocación durante la vida de una
  dirección firmada**, cinco minutos por defecto.
- **Las versiones eliminadas desaparecen.** Una conversación que enlaza a una
  versión más antigua que la ventana conservada solo puede ofrecer la última.

## Resumen { #recap }

- Una capability, una herramienta: `publish_artifact`, desde un archivo del
  workspace o en línea.
- El agent y el nombre son la identidad; volver a publicar conserva el enlace y
  añade una versión.
- Privado por defecto; compartido por una persona mediante grants, la
  organización o un enlace público.
- Servido desde una ruta sin cookies, en un origen opaco sin red, y
  opcionalmente desde un dominio propio.
- Una clase de retención propia, medida desde la última publicación.
