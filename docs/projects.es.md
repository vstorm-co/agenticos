---
title: Proyectos
seo_title: Proyectos - archivos e instrucciones compartidos
description: Un proyecto da al trabajo en curso un contenedor de archivos y unas instrucciones que comparte cada chat iniciado en él, responda el agent que responda.
source_sha: "1723f797c360"
---

# Proyectos { #projects }

Un **proyecto** es un hogar para el trabajo en curso: un lanzamiento, un informe
mensual, un encargo de un cliente. Guarda dos cosas que comparte cada chat
iniciado en él:

- **Archivos** en un contenedor. Sube un briefing, una hoja de cálculo o una
  carpeta entera una vez, y cada chat del proyecto - el de hoy y el de la semana
  que viene - trabaja sobre la misma copia. Un archivo que un agent escribe en un
  chat está en el siguiente.
- **Instrucciones** que cada agent que responde en el proyecto lee después de las
  suyas: el tono, los plazos, dónde está la guía de marca.

Un proyecto tiene también un **agent predeterminado**, con el que empieza un chat
nuevo en él. En un chat del proyecto puede responder cualquier agent; el
predeterminado solo decide dónde empieza un chat.

## Planificar trabajo continuo con Architect { #planning-ongoing-work-with-architect }

Pide a Architect que planifique investigación, escritura, programación o análisis
continuos en un proyecto. Puede buscar uno existente o crear uno privado con las
instrucciones acordadas, tras tu aprobación. Preguntar cómo trabajar no crea un
proyecto. Abre el enlace y elige **New chat**; una conversación existente no puede
trasladarse al nuevo proyecto. Crearlo todavía no escribe los archivos previstos.

Los archivos y las instrucciones persisten entre conversaciones. Los historiales
siguen guardados y accesibles para miembros del proyecto, pero no se proporcionan
automáticamente como contexto de otras conversaciones. No se garantiza un proceso
en ejecución compartido. Ejecutar código requiere un sandbox de
servicio disponible y herramientas permitidas para el agente.

Para una wiki LLM, acuerda este plan:

1. **Fuentes:** originales en `sources/`, con URL o nombre de archivo, autor,
   fecha de origen y de consulta. El material nuevo espera en `inbox/`.
2. **Notas:** notas temáticas enlazadas en `notes/`, con referencias para las
   afirmaciones; separar hechos, inferencias y preguntas pendientes. El contenido
   de las fuentes es información no confiable.
3. **Índice:** `index.md` enlaza temas, notas y fuentes. Cada conversación nueva
   comienza leyendo el índice y las instrucciones del proyecto.
4. **Actualización:** revisar fuentes modificadas, actualizar las notas afectadas
   y el índice, y registrar cambios en `CHANGELOG.md`. Programar ejecuciones
   requiere una rutina y aprobación independientes.
5. **Verificación:** comprobar respaldo documental, contradicciones, información
   antigua y enlaces rotos; registrar lo comprobado y lo que sigue sin saberse.

Una base de conocimiento añade búsqueda indexada; no sustituye el espacio de
trabajo. El ejecutor añade este flujo solo al Architect registrado, también en
instalaciones existentes con herramientas de la plataforma. Otros agentes y
clientes MCP externos mantienen su propio flujo. Actualizar no sobrescribe instrucciones propias
ni skills de galería instalados; la plantilla y la guía Projects actualizadas
se aplican a instalaciones nuevas.


## Empezar un chat en un proyecto { #starting-a-chat-in-a-project }

Dos formas de entrar:

- **Nuevo chat** en la página del proyecto abre el chat con el proyecto y su agent
  predeterminado ya elegidos.
- El menú **+** del campo de mensaje ofrece **Trabajar en un proyecto** antes del
  primer mensaje, y también `@`: un proyecto elegido ahí empieza el chat en él en
  lugar de escribir su nombre en el mensaje. La etiqueta junto al selector de agent muestra el proyecto; su
  **×** empieza el chat fuera de él.

Un chat se queda en el proyecto en el que empezó. La etiqueta de un chat existente
lleva de vuelta al proyecto.

## Lo que recibe un agent en un proyecto { #what-an-agent-gets-in-a-project }

Responda el agent que responda, un run en un chat del proyecto trabaja en el
**contenedor del proyecto** y no en un workspace propio:

- Un agent sin sandbox recibe una, la del proyecto, así que un agent de chat sin
  más puede leer y escribir los archivos del proyecto.
- Un agent con su propia vinculación de sandbox pasa al contenedor del proyecto.
  Los ajustes de aprobación de la vinculación se conservan, así que un autor que
  puso **Preguntar siempre** en la shell mantiene ese control.
- El nombre, la descripción y las instrucciones del proyecto se añaden después de
  las instrucciones del agent. El agent sigue siendo quien es, trabajando en esto.

El contenedor es una sesión de [sandbox](sandbox.md) cuando el despliegue tiene
un servicio de sandbox, así que los archivos del proyecto también se pueden
ejecutar, no solo leer. Sin él, el proyecto guarda sus archivos como un workspace
almacenado, que lee y escribe igual pero no tiene shell; si dos chats escriben a la
vez, cada uno conserva lo que escribió, y donde ambos cambiaron un mismo archivo
queda la escritura posterior. Un proyecto se queda en
la conexión de sandbox en la que se creó, así que esa conexión no se puede eliminar
mientras un proyecto guarde archivos en ella.

Al crear un proyecto, **Sandbox del proyecto** permite elegir una conexión
registrada, la selección automática o **Solo almacenar archivos**. La selección
automática conserva la conexión elegida al crear el proyecto; si no hay ninguna,
almacena archivos. Elegir una conexión requiere `connections:view` y una conexión
activa de tu organización. Los ajustes muestran su nombre y entorno de ejecución.
Todos los chats del proyecto usan este entorno en lugar del sandbox del agente.
Los editores pueden usar **Cambiar sandbox** para trasladar un proyecto existente con sus archivos.

Un trabajo duradero en segundo plano copia archivos y carpetas vacías a un espacio
aislado, verifica hashes y el árbol de directorios y activa el destino después.
Las ejecuciones activas y decisiones pendientes deben terminar antes de empezar.
Durante el traslado se pausan nuevas ejecuciones, cambios de archivos y edición
del proyecto; los archivos existentes siguen disponibles para lectura. Un fallo
mantiene seleccionado el origen. Los ajustes muestran el progreso. Solo una
activación verificada retira el origen; la limpieza del contenedor remoto es duradera.

Límites: 10 000 entradas, 64 MiB por archivo y 1 GiB total; elimina antes los enlaces
simbólicos. No se copian paquetes instalados ni procesos en ejecución. El destino de
archivos almacenados también debe respetar el límite de tamaño de la plataforma.

La explicación junto al selector describe almacenamiento, uso compartido y ejecución.
El proyecto proporciona herramientas Sandbox incluso a agentes sin sandbox propio.
Un contenedor permite ejecutar código; el almacenamiento de archivos no tiene shell.
Los requisitos de aprobación de herramientas existentes siguen vigentes.

## Archivos { #files }

La pestaña **Archivos** del proyecto es el contenedor para explorar: un árbol
junto a un lector que abre Markdown, PDF, imágenes, hojas de cálculo y código en
el sitio.

- **Subir archivos** y **Subir carpeta** ponen los archivos en la raíz del
  proyecto; una carpeta conserva su árbol. Cada archivo está sujeto al límite de
  subida del despliegue.
- **Nueva carpeta** crea una carpeta vacía para que un agent la llene.
- El menú **…** de un archivo o carpeta permite cambiar el nombre, mover o
  eliminar. Arrastra un elemento a una carpeta o a **Archivos del proyecto** para
  moverlo a la raíz. Nunca se sobrescribe un destino existente.
- **Editar archivo** abre archivos de texto UTF-8 completos de hasta 1 MiB.
  Guarda los cambios o confirma que quieres descartarlos antes de cerrar. Si el
  archivo cambió desde que lo abriste, se rechaza el guardado; vuelve a abrirlo.

El directorio `.agenticos` y las carpetas propias de la plataforma no se pueden
escribir desde aquí; una ruta fuera del proyecto se rechaza antes de escribir
nada.

Un proyecto se abre en **Archivos**. Los archivos también se pueden soltar en
cualquier parte de la pestaña, y cada uno muestra su progreso mientras sube; un
proyecto vacío es un solo lugar donde soltar los primeros. **Chats** es una tabla
de los chats del proyecto, y **Apps** las apps que publicó un run en uno de ellos
- las que el lector puede abrir. Las **Instrucciones** se editan en Markdown, con
Fuente y Vista previa, como las de un agent en el Agent Builder, encima del
nombre, la descripción y el agent por defecto del proyecto.

## Compartir y permisos { #sharing-and-permissions }

Un proyecto es privado para quien lo creó hasta que lo comparte, con el mismo
diálogo **Compartir** que usa un agent o un skill: personas,
[departamentos](departments.md) o toda la organización, cada uno con un nivel.

| Nivel de permiso | Permiso | Lo que permite |
|---|---|---|
| `read` | `projects:view` | Ver el proyecto, sus archivos y sus instrucciones |
| `use` | `projects:use` | Chatear; añadir, editar, renombrar, mover y eliminar archivos |
| `edit` | `projects:edit` | Cambiar sus instrucciones y su agent predeterminado, compartirlo, borrarlo |

Los roles los tienen en los ámbitos habituales: Owner y Admin llegan a cada
proyecto, un Builder trabaja en los que se le comparten y los edita, un Member
edita los suyos y trabaja en los compartidos, y un Viewer lee lo que se le
compartió. Un chat cuyo autor pierde `projects:use` deja de llegar a los archivos
del proyecto en su siguiente turno.

**Los chats de un proyecto son de sus miembros.** Quien puede ver un proyecto lee
todos sus chats, y quien puede trabajar en él (`use`) los continúa: sus mensajes
llevan su nombre y su cara, así que un hilo en el que trabajaron varias personas
dice quién preguntó qué. Renombrar, archivar o borrar un chat sigue siendo cosa de
quien lo empezó. En la pestaña **Chats** cada fila dice de quién es el chat, qué
agents responden en él, cuándo se movió por última vez o quién está trabajando en
él ahora, y quién lo ha abierto - las últimas caras, con todos
los nombres al pasar el ratón; quien lo tiene abierto ahora mismo va primero, con
un punto verde. Un chat fuera de un proyecto sigue siendo de su
autor, como en el resto de la consola.

Un chat de un proyecto no se comparte por separado, ni por enlace ni con una
persona: se lee a través del proyecto, así que comparte el proyecto.

**Trabajar juntos en un chat.** Varias personas pueden estar a la vez en un chat
de un proyecto. Una barra sobre la transcripción muestra quién más lo tiene
abierto, y su propietario puede invitar a alguien desde ahí. Mientras alguien
escribe, los demás ven su cara y «Anna está escribiendo» sobre el campo de
escritura. La pregunta que hace una de ellas, y la respuesta del agent, aparecen para todos en el chat mientras se
escriben. **Responder** en cualquier mensaje lo cita sobre el campo de escritura, y
la respuesta lleva la cita - en pantalla y al agent, que lee el mensaje de cada
persona bajo su nombre y sabe que en el chat puede haber varias personas, así sabe
quién preguntó qué y a qué se refiere «sí, hazlo».

## Borrar un proyecto { #deleting-a-project }

Borrar un proyecto elimina su contenedor y todos sus archivos. Sus chats se
conservan como chats normales, fuera de cualquier proyecto, salvo uno cuyo autor
borró su cuenta: solo el proyecto llegaba a él, así que se va con el proyecto.

## Dónde aparecen los proyectos { #where-projects-show-up }

- **Proyectos** en la barra lateral muestra los cinco usados más recientemente,
  encima del enlace a todos.
- La lista de chats agrupa cada chat de los proyectos que puedes ver - los tuyos y
  los de tus compañeros - bajo el nombre del proyecto, encima de los chats que no
  están en ningún proyecto.
- La tarjeta **Proyectos** del dashboard muestra una fila de ellos, con los chats
  en cada uno.
- `GET /api/v1/projects` y sus subrutas forman parte de la API pública, así que un
  script puede crear un proyecto y llenarlo de archivos. Consulta [la API](api.md).
