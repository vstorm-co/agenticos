---
title: Proyectos
seo_title: Proyectos - archivos e instrucciones compartidos
description: Un proyecto da al trabajo en curso un contenedor de archivos y unas instrucciones que comparte cada chat iniciado en él, responda el agent que responda.
source_sha: "506e3fa30055"
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

La capability **Projects** busca proyectos accesibles, selecciona un ID devuelto y
lee o escribe sus archivos. AgenticOS y Architect la incluyen. En una conversación
privada vinculada de Mattermost o Slack puedes pedir usar el proyecto XYZ: el agente
lo busca y selecciona mediante herramientas; el nombre no concede acceso. Los
remitentes no vinculados y salas con audiencia no verificada no reciben contexto
privado. Seleccionar no inicia por sí solo un entorno de pago.

La selección dura una ejecución, incluidas continuaciones tras aprobaciones y
preguntas. El siguiente mensaje en un chat normal o canal privado comienza sin
proyecto; un chat de proyecto empieza con el suyo. El historial queda en su
conversación. No se copian ni montan archivos. Cada operación comprueba membresía,
scopes, acceso y generación del workspace actuales. Las rutinas conservan las fuentes
revisadas; las evaluaciones aisladas no seleccionan proyectos activos.

## Lo que recibe un agent en un proyecto { #what-an-agent-gets-in-a-project }

Los archivos del proyecto y la ejecución de comandos están separados:

| Selección | Valor predeterminado y efecto |
|---|---|
| Contexto del proyecto | Archivos e instrucciones de referencia; se mantienen las reglas del agente y la plataforma |
| **Trabajar en → Proyecto** | Por defecto en chats del proyecto; usa su contenedor ejecutable si las herramientas shell de Sandbox están activadas |
| **Trabajar en → Agente** | Por defecto fuera del proyecto; usa el ejecutor configurado sin montar archivos del proyecto |
| Solo almacenar archivos | Funcionan las herramientas de texto; el proyecto no ejecuta comandos |
| Carpeta de trabajo local | Mantiene el ejecutor local elegido por la persona; el contexto del proyecto no lo sustituye |

**Trabajar en** aparece en ajustes del chat web y desktop si el agente puede ejecutar
comandos. Ejecutar en un proyecto requiere uno adjunto o seleccionado antes del
mensaje. La elección explícita se conserva por cuenta, organización y chat, sin
heredarse a chats nuevos. La solicitud explícita fija el ejecutor durante toda la
ejecución; el agente no puede cambiarlo. Sin esa selección puede usar
`select_execution_target`; `select_project_context` y el antiguo `select_project_workspace` solo cambian
archivos. El resultado muestra ambas elecciones y su disponibilidad.

Los chats del proyecto dan acceso real a archivos sin Sandbox. No activan un Sandbox
desactivado ni conceden herramientas shell ausentes. Siguen las aprobaciones de cada
herramienta. Tras observar contexto privado se rechaza un ejecutor de agente/canal
compartido con una audiencia más amplia; limpiar la selección no lo evita. Usa un
ejecutor aislado de conversación o el del proyecto.

Las herramientas de texto listan hasta 100 entradas y leen o escriben UTF-8 de hasta
256 KB. Rechazan rutas reservadas, enlaces fuera del proyecto, binarios y tamaños
desconocidos. No ejecutan OCR. Escribir después de leer rechaza un archivo modificado
en paralelo. El proyecto mantiene su conexión sandbox hasta que un editor lo traslada
explícitamente.

Tras continuar una aprobación o pregunta hay que volver a leer cada archivo
existente del proyecto antes de reemplazarlo o borrarlo. El agente de código requiere
el mismo workspace para archivos y comandos; los espacios separados se rechazan.

El trabajo delegado recibe un snapshot fijo del proyecto, generación y ejecutor.
El primer delegado que comparte workspace bloquea estas opciones hasta terminar la
ejecución, incluidas aprobaciones y preguntas; cambiarlas requiere un turno nuevo.
Los hijos no reciben el puerto mutable de selección y conservan su propia protección
contra conflictos de lectura. El root controla la limpieza y el registro de orígenes.
Tras la limpieza se rechazan nuevas operaciones de archivos y comandos. Las operaciones
remotas ya admitidas conservan los plazos de cancelación y vida útil del proveedor;
la limpieza no garantiza que hayan terminado.

Al crear un proyecto, **Sandbox del proyecto** permite elegir una conexión
registrada, la selección automática o **Solo almacenar archivos**. La selección
automática conserva la conexión elegida al crear el proyecto; si no hay ninguna,
almacena archivos. Elegir una conexión requiere `connections:view` y una conexión
activa de tu organización. Los ajustes muestran su nombre y entorno de ejecución.
Los chats del proyecto usan sus archivos y, por defecto, su ejecutor si hay herramientas de comandos activadas.
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
Los archivos almacenados no tienen shell; contexto y ejecución siguen separados
como se describe arriba.

## Archivos { #files }

En **Archivos** del chat elige el origen cuando hay archivos del proyecto y un
workspace independiente del agente. Cada uno usa sus propios endpoints autorizados;
una ruta idéntica nunca recurre al otro origen. Por defecto se usa el proyecto de
la conversación o el workspace disponible del agente. Ejecuciones completadas,
fallidas y canceladas registran referencias sin copiar contenido. Revocar acceso
elimina un origen. Los archivos con scope run son temporales y desaparecen al limpiar;
elige un scope persistente para trabajo posterior. No se inventan orígenes para
ejecuciones históricas sin referencias.

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

Suelta archivos externos sobre una carpeta para cargarlos allí, o en otro lugar de la pestaña Archivos para añadirlos a la raíz del proyecto. Una pausa sobre una carpeta cerrada la abre. La indicación permanece en el área de archivos, las acciones mantienen su espacio y las carpetas no muestran contadores. Las colas largas muestran las tres primeras entradas y el número pendiente. Los iconos distinguen código, JSON, marcado, documentos, hojas de cálculo y multimedia en proyectos, adjuntos del chat, RAG y archivos de skills.

La consola de escritorio envía los archivos arrastrados a los mismos destinos que la
aplicación web. Al soltarlos sobre un archivo se usa su carpeta; el espacio vacío de
cualquiera de los dos paneles usa la raíz del proyecto. Blobby y el Dock conservan su
función de adjuntar al chat.

## Vista de grafo { #graph-view }

En el explorador de archivos, elige **Graph view** para explorar notas Markdown
enlazadas. La misma vista funciona con archivos compartidos del proyecto,
workspaces del sandbox y una carpeta Desktop autorizada. Cada ubicación conserva
su propio grafo; las notas locales no se suben al servidor.

El grafo se abre a pantalla completa con puntos de colores, enlaces finos y etiquetas
al ampliar o seleccionar una nota. Las flechas de dirección y etiquetas permanentes
son opcionales. La búsqueda, archivos, detalles y zoom están en paneles flotantes.
Los grupos colorean las notas por carpeta de forma predeterminada o por su primera
etiqueta. Puedes ocultar grupos, filtrar una carpeta con sus subcarpetas y restablecer
los filtros. El explorador usa el mismo árbol de carpetas e iconos que otros espacios.

Solo las notas Markdown indexadas son nodos; los demás archivos se abren en el visor
compartido. Arrastrar puntos solo organiza la vista, sin modificar archivos ni enlaces.
El control de pantalla completa o Escape restaura la vista incrustada; la flecha
atrás vuelve a los archivos.

Conecta notas con `[[notes/topic|etiqueta]]`, enlaces Markdown en línea como
`[Tema](topic.md)` o relaciones en el frontmatter:

```yaml
---
title: Memoria del agent
aliases: [Memory]
tags: [agents, research]
related: ["[[notes/retrieval]]"]
sources: [sources/report.md]
---
```

`links`, `related` y `sources` aceptan un texto o una lista de textos. Las URL
externas siguen siendo citas. Los wikilinks resuelven rutas exactas o nombres de
archivo, títulos o alias únicos; los nombres duplicados quedan sin resolver. Los
enlaces Markdown son relativos a su nota. Se ignoran ejemplos de código y
comentarios HTML.

Busca por título, ruta, alias o tag. Selecciona un nodo para ver sus enlaces,
enlaces entrantes y referencias sin resolver; **Open note** abre la nota. Los
archivos compartidos conservan **Edit file** y sus permisos existentes. Usa los
controles de zoom y arrastra el fondo vacío para desplazarte; la lista de notas
también funciona con teclado.

La vista relee los archivos cada 30 segundos mientras está abierta, al volver a
la ventana o con **Refresh**. Los agentes actualizan notas y enlaces sin generar
HTML. Las Apps ya actualizan bindings de tablas y logs de workflows, pero no
tienen un binding de archivos del workspace; este grafo lee las notas directamente.
Actualizar el grafo no inicia un agent para verificar hechos o fuentes.

Un escaneo incluye hasta 200 archivos Markdown, 256 KiB por archivo y 8 MiB en
total, dentro de los límites de la lista de origen. Se permiten hasta 256
relaciones por nota y 2048 en todo el grafo; alcanzar un límite también marca
el grafo como incompleto. Los alias y las etiquetas comparten un límite de
128 entradas por nota y 4096 en todo el grafo. La vista identifica archivos
omitidos o ilegibles, YAML inválido y listas incompletas. Una referencia ausente
puede indicar una nota omitida. La actualización es periódica; las ediciones
simultáneas pueden aparecer en escaneos diferentes.

## Carpetas locales en la aplicación de escritorio { #local-folders-in-the-desktop-app }

La pestaña **Archivos** separa **Archivos compartidos del proyecto** de **Este equipo**. Una carpeta autorizada al crear el proyecto se abre automáticamente en esa instalación; sin conexión se muestran primero los archivos compartidos. Elige Este equipo para conectar una carpeta. Los ajustes de carpeta permiten cambiarla o desconectarla; ruta y modo de acceso siguen visibles sin repetir el formulario.

Los archivos compartidos son copias subidas para personas con acceso al proyecto. Para compartir un archivo local, elige esa fuente y sube una copia. Los lugares no se sincronizan: editar localmente no actualiza la copia subida, y compartir el proyecto no concede acceso al disco. El espacio de trabajo compartido en Instrucciones solo cambia el almacenamiento del servidor; no conecta ni desconecta carpetas personales.

El selector nativo confirma el acceso, inicialmente de solo lectura. La conexión pertenece a la cuenta y organización actuales en este equipo. Desconectarla conserva permisos de otros chats. La vista muestra hasta 500 entradas, omite carpetas generadas como `.git` y `node_modules` y presenta errores de lectura sin cambiar silenciosamente a la nube.

Los nuevos chats del proyecto en escritorio heredan la carpeta y el acceso
aprobado. Las instrucciones del proyecto siguen vigentes; las herramientas del
sandbox trabajan localmente en lugar del contenedor compartido. Cambia
**Trabajar en** para un chat concreto; las conversaciones existentes conservan
su configuración. El acceso directo de carpeta junto al cuadro de mensaje abre
estas opciones. Un equipo desconectado o un permiso revocado no cambia la ejecución
a la nube. Los teléfonos y navegadores siguen usando los archivos compartidos y
no obtienen acceso remoto al equipo. Las respuestas y resultados de herramientas
guardados en el chat del proyecto siguen siendo visibles para sus lectores;
considera su audiencia antes de hablar de archivos privados.

## Compartir y permisos { #sharing-and-permissions }

Un proyecto es privado para quien lo creó hasta que lo comparte, con el mismo
diálogo **Compartir** que usa un agent o un skill: personas,
[departamentos](departments.md) o toda la organización, cada uno con un nivel.

| Nivel de permiso | Permiso         | Lo que permite                                                             |
| ---------------- | --------------- | -------------------------------------------------------------------------- |
| `read`           | `projects:view` | Ver el proyecto, sus archivos y sus instrucciones                          |
| `use`            | `projects:use`  | Chatear; añadir, editar, renombrar, mover y eliminar archivos              |
| `edit`           | `projects:edit` | Cambiar sus instrucciones y su agent predeterminado, compartirlo, borrarlo |

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

- **Proyectos** en la barra lateral muestra los tres usados más recientemente,
  encima del enlace a todos. Un icono indica los proyectos con una respuesta de chat que todavía no has leído.
- La lista de chats agrupa cada chat de los proyectos que puedes ver - los tuyos y
  los de tus compañeros - bajo el nombre del proyecto, encima de los chats que no
  están en ningún proyecto.
- La tarjeta **Proyectos** del dashboard muestra una fila de ellos, con los chats
  en cada uno.
- `GET /api/v1/projects` y sus subrutas forman parte de la API pública, así que un
  script puede crear un proyecto y llenarlo de archivos. Consulta [la API](api.md).


## Mantener un proyecto al día { #keep-a-project-on-track }

En la página del proyecto, elige **Mantener el proyecto al día**. Selecciona un agente publicado que puedas editar, revisa sus recursos y cuentas conectadas, nombra el nuevo agente y la tabla de tareas, elige la frecuencia y confirma expresamente la publicación y el inicio. Se crean una copia privada del agente, una tabla de tareas (privada salvo que elijas la organización), vistas guardadas de todas las tareas, tablero, tareas abiertas y bloqueos, y una rutina fijada a la nueva versión. El agente original no cambia.

La rutina actúa como tú dentro del proyecto y publica informes en su conversación. Lee las tareas, verifica avances con las fuentes aprobadas, actualiza próximos pasos y señala bloqueos y plazos. Enviar mensajes externos sigue requiriendo la autorización habitual. Las fuentes nuevas, un nuevo consentimiento de cuenta o la sustitución del espacio de trabajo requieren otra revisión de fuentes. Perder acceso al proyecto detiene las herramientas siguientes; las notificaciones pendientes vuelven a comprobar el acceso actual del destinatario. Un intento idéntico reutiliza los recursos existentes. Gestiona la frecuencia y las fuentes en Rutinas y abre la tabla desde el proyecto.

Una conversación programada sin propietario dentro de un proyecto puede ser renombrada, archivada o eliminada por quien tenga permiso para editar ese proyecto. Los chats iniciados por otra persona siguen bajo la gestión de esa persona.


Eliminar un proyecto también borra sus entradas de memoria y copias compartidas derivadas e intenta retirar los webhooks registrados antes de eliminar sus rutinas en cascada. Un proveedor no disponible se registra y no bloquea la eliminación.


## Recursos vinculados { #linked-resources }

La pestaña **Recursos** agrupa agentes, workflows, aplicaciones y tablas existentes sin copiarlos. Elige **Añadir recursos existentes**, selecciona uno o varios elementos y, si quieres, marca un workflow vinculado como principal. Un recurso puede pertenecer a varios proyectos. Busca en la lista por nombre o descripción; los catálogos de agentes y workflows también ofrecen un filtro de proyecto. Los nombres de proyectos se encuentran en la paleta de comandos.

Los vínculos no conceden acceso: cada recurso conserva sus propios permisos, versiones y horarios. Quitar un vínculo o eliminar un proyecto mantiene intacto el recurso original. Eliminar un recurso elimina sus vínculos. Marcar un workflow principal no lo ejecuta.

Un proyecto abre **Chats** por defecto; un enlace a una pestaña concreta sigue abriendo esa pestaña. Usa el signo más junto a un proyecto reciente en la barra lateral del chat para iniciar allí un nuevo chat. Los proyectos de solo lectura no ofrecen esta acción.
