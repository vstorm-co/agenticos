---
source_sha: "9350ca23bd90"
---

# La app de escritorio { #the-desktop-app }

AgenticOS funciona en el navegador, y así lo usa la mayoría. La app de escritorio
es para quien quiere más en su propio ordenador: la consola en una ventana propia,
una pregunta rápida desde cualquier sitio, Blobby en el escritorio y - lo que un
navegador no puede hacer - los agents de uno trabajando en una carpeta de este
ordenador y en su pantalla. La plataforma en sí no la necesita.

> **Captura pendiente — la app de escritorio, Blobby y la pregunta rápida.**

La aplicación de la ventana es la misma consola Next.js que el servidor ya sirve,
cargada desde el servidor, así que tiene el mismo inicio de sesión, los mismos
permisos y las mismas comprobaciones de tenant que una pestaña del navegador. Es
un shell de [Tauri](https://tauri.app) en `desktop/`.

!!! note "Es un shell, no un build del frontend"

    `frontend/` es una aplicación Next.js con una mitad de servidor - route
    handlers que reenvían al backend, las cookies de sesión que fijan, un
    middleware que elige el idioma y páginas renderizadas en el servidor. Nada de
    eso funciona dentro de un binario de escritorio, así que el shell no lo
    intenta: abre la URL del despliegue como lo haría un navegador. Lo que se
    instala es el despliegue; la app es la forma de abrirlo.

Sin una preferencia guardada, la aplicación de escritorio usa el tema **Sistema**
y el estilo **Glass**. Una elección explícita guardada tiene prioridad.

En **Chat controls → Computer use**, selecciona **Local computer** para dar a esta conversación herramientas de capturas de pantalla, ratón y teclado, aunque el agente no tenga la capacidad Computer use. La elección es independiente de Browser y Work on: no concede acceso a carpetas ni comandos y no modifica el agente publicado. La persona debe tener conectado su propio dispositivo emparejado; siguen siendo necesarios el consentimiento nativo para la pantalla y los permisos del sistema operativo.

## Instalar la aplicación { #installing-the-app }

Descarga el paquete para tu ordenador desde la [versión en GitHub](https://github.com/vstorm-co/agenticos/releases/latest). Instalar una versión no requiere Rust ni herramientas de desarrollo.

- **macOS:** elige Apple silicon o Intel, abre el `.dmg` y arrastra AgenticOS a **Applications** siguiendo la flecha. Inícialo desde Applications y expulsa la imagen de disco.
- **Windows:** abre el instalador `setup.exe`. Utiliza el idioma del sistema e instala para tu usuario sin permisos de administrador. Abre AgenticOS desde el menú Inicio. También hay un paquete `.msi` para instalaciones administradas.
- **Linux:** abre `.deb` o `.rpm` en el instalador de software de tu distribución. Para una instalación portátil, permite ejecutar el `.AppImage` en sus propiedades y ábrelo.

El primer inicio te guía para conectarte a un servidor o crear una instancia local. Solo las instancias locales necesitan Docker; el asistente lo detecta y ofrece descargarlo si falta. La instalación no concede acceso a la pantalla ni al micrófono.

### Widgets de escritorio en macOS { #desktop-widgets-on-macos }

En macOS 14 o posterior, inicia una vez la aplicación instalada, haz clic derecho en el escritorio, elige **Editar widgets** y busca **AgenticOS**. El pequeño abre Quick Ask; el mediano también Chat, Inbox y Activity. Siguen la apariencia del sistema y solo contienen accesos directos, sin datos de la cuenta. Un clic nunca inicia una grabación ni una llamada.

La CI de versiones crea paquetes nativos para Mac (Apple silicon e Intel), Windows y Linux. Los paquetes públicos de macOS requieren credenciales de firma Developer ID y notarización en el entorno de publicación. Una compilación local de desarrollo con firma ad-hoc no es una versión pública notarizada.

## Ejecutarla { #running-it }

Antes de elegir una instalación local o conectar con un servidor, el asistente inicial
ofrece permisos opcionales de grabación de pantalla y accesibilidad en macOS. Cada botón
abre los ajustes del sistema correspondientes; la configuración no captura la pantalla
ni controla el equipo. Se puede continuar sin ambos permisos. Al volver de Ajustes se
actualiza su estado; macOS puede requerir reiniciar la aplicación. El acceso al
micrófono y las carpetas se solicita al usar esas funciones.

Hacen falta Rust de [rustup](https://rustup.rs) y el webview de la plataforma -
WebKit en macOS, WebView2 en Windows, WebKitGTK en Linux; la
[página de requisitos](https://v2.tauri.app/start/prerequisites/) de Tauri tiene la
lista por plataforma. La CLI de Tauri está fijada en `desktop/package.json`, y
`make install` la descarga con todo lo demás.

```bash
make desktop-dev     # opens the shell
make desktop-build   # a .app / .dmg, .msi or .deb/.AppImage for this machine
make desktop-check   # rustfmt, clippy with warnings denied, and the tests
```

La primera vez, la app pregunta dónde está AgenticOS:

- **En este ordenador.** La app comprueba Docker, prepara las imágenes publicadas
  con la consola y la API solo en loopback, crea tu organización y su propietario,
  y desde entonces arranca, para y actualiza ese stack desde la barra de menús.
- **En el servidor de tu organización.** Escribe su dirección; un host a secas
  (`agenticos.acme.com`) se abre por HTTPS. Inicias sesión en tu propio navegador
  (ver [Iniciar sesión](#signing-in)).

!!! warning "`http://` sin cifrar solo para esta máquina"

    `localhost`, `127.0.0.1` y `::1` pueden alcanzarse sin cifrar; cualquier otro
    host se rechaza hasta que sea `https://`. La consola envía la contraseña y
    recibe el token por esa conexión, y una red local es justo donde otro puede
    leerlo.

También se rechaza una dirección donde no responde nada: el shell abre una
conexión TCP antes de dirigir el webview a ningún sitio, porque WebKit pinta una
conexión rechazada como una ventana blanca vacía.

Los ajustes están en `server.json`, en el directorio de configuración de la app -
`~/Library/Application Support/co.vstorm.agenticos/` en macOS,
`%APPDATA%\\co.vstorm.agenticos\\` en Windows, `~/.config/co.vstorm.agenticos/` en
Linux. Un archivo que ya no se puede leer se aparta como `server.json.invalid` y
se escribe uno nuevo. El servidor se cambia en **Ajustes…** (`⌘,`), desde el menú
de la bandeja o arrancando con `--server <address>`.

**Cambiar servidor…** está en el menú desplegable de la cuenta, al pie de la
barra lateral. Pulsa el nombre de la cuenta o el avatar en la barra contraída
y selecciona la opción para abrir el formulario de conexión. Sigue disponible
cuando blobby está oculto.

### Docker y varias instancias locales { #docker-and-multiple-local-instances }

Crear una instancia abre un paso propio con campos agrupados de espacio,
propietario y proveedor. **Cancel** vuelve a la lista de instancias. Blobby se
oculta durante la configuración y regresa con la consola según su preferencia
de visibilidad guardada.

En macOS, **Download Docker Desktop** descarga el instalador oficial para Apple
silicon o Intel, muestra el progreso y abre la imagen de disco. Termina la
instalación en la ventana del sistema y elige **Open Docker Desktop** y **Check
again**. La aplicación también detecta la CLI de Docker instalada para el usuario.
Otros sistemas abren la página de descarga de Docker. Una comprobación de estado
por sí sola no inicia la instalación.

Elige **New instance**, asígnale un nombre e introduce la organización y su
propietario. La aplicación asigna puertos loopback libres y crea un proyecto Compose
separado con base de datos, volumen de archivos, red, directorio de trabajo y claves
propias. Las cookies de sesión tienen un espacio de nombres por instancia, por lo
que cambiar no sustituye el inicio de sesión de otra instalación. Las imágenes del
frontend deben admitirlo; se rechazan las antiguas antes de crear al propietario
o abrir una sesión.

La pantalla local muestra las instancias guardadas, sus direcciones y estado.
**Start and connect** inicia la elegida; **Finish setup** reintenta una instalación
interrumpida conservando archivos y claves. Start, Stop y Update del menú actúan
sobre la instancia administrada conectada. Conectarse a un entorno de desarrollo
iniciado externamente no lo convierte en una instancia administrada.

Los metadatos están en `local-instances.json` en el directorio de configuración;
los archivos nuevos en `local-stacks/<id>/` en el directorio de datos. Las
instalaciones `local-stack/` existentes conservan su proyecto Compose y sus datos.
Las contraseñas y claves de proveedores se pasan al bootstrap sin guardarlas en
estos archivos ni en argumentos de Docker. Las claves del despliegue permanecen
en su `.env` privado; las de proveedores se guardan en la bóveda del servidor.
El asistente nativo usa un foco de teclado neutro y no enfoca automáticamente
los botones de selección.

## Configuración de conexión y estado de la aplicación { #connection-setup-and-app-readiness }

El menú de usuario también abre directamente el **Estado de la aplicación**, incluso desde los ajustes de escritorio. La lista sustituye al contador flotante y no tapa los controles de la página.

La revisión de conexión está centrada sobre el material de cristal nativo, incluso
si la consola tiene guardado un estilo opaco. Las filas permanecen visibles durante
la comprobación. Conectar y Continuar muestran progreso inmediato; el panel se precarga
durante la configuración. La animación de entrada respeta la reducción de movimiento.

Al conectar con un servidor se abre el estado de la aplicación, también para cuentas
existentes. Comprueba el inicio de sesión, la conexión del ordenador, un agente
publicado disponible, el modelo del asistente, los atajos y los permisos de macOS.
Solo **Activar** solicita un permiso. Puedes continuar con pasos opcionales pendientes
y volver desde **Ajustes → Aplicación de escritorio** o **Activity & Access**.
La consola recuerda la revisión aplazada por cuenta, organización y servidor;
una nueva conexión explícita propone otra revisión. Los errores de comprobación
siguen visibles y permiten reintentar. Volver de los ajustes del sistema actualiza
el estado de los permisos.

Los fallos de captura y control de pantalla indican Grabación de pantalla o
Accesibilidad; los errores de micrófono en Quick Ask enlazan al mismo panel.
Tras conceder Grabación de pantalla, la reparación permite abrir de nuevo el selector
interactivo de región. macOS puede exigir reiniciar la aplicación.

**Ajustes → Aplicación de escritorio → Notificaciones** controla ejecuciones terminadas,
errores, aprobaciones, preguntas y otras novedades. Las vistas previas se ocultan
por defecto; una aprobación privada abre la solicitud en la aplicación en lugar de
permitir aprobarla sin leerla. Los ajustes del chat permiten silenciar una conversación.
La notificación se suprime mientras esa conversación tiene el foco en la consola
o Quick Ask. Los permisos del sistema y el modo de concentración de macOS siguen
controlando la entrega.

**Activity & Access** muestra el trabajo activo y las solicitudes pendientes.
Abre una entrada para continuar en la consola; **Stop** está disponible cuando
esta aplicación mantiene la conexión original de la conversación. Otras ejecuciones
del servidor siguen accesibles mediante **Open**. El menú también revoca permisos
individuales de carpetas o del ordenador completo y devuelve el control de la pantalla.

La cabecera ofrece **Nuevo chat** (`⌘N` o `Ctrl+N`), continuar en la consola
y cerrar. Un nuevo chat borra la selección de conversación y el contexto del borrador;
el editor permanece bajo el historial con un botón de envío visible.

Quick Ask admite `@mention` con los mismos recursos que el editor del chat.
Las flechas y Enter o Tab seleccionan; Escape cierra primero las sugerencias.
Eliminar una mención quita su vínculo al recurso del siguiente mensaje.

## Una aplicación, no una pestaña { #an-application-not-a-tab }

En macOS la barra lateral de la consola lleva los botones de la ventana y la
arrastra, la ventana recuerda su tamaño y posición, y cerrarla deja la app en la
barra de menús. La barra de menús tiene File, Edit, View, Go (`⌘1`-`⌘5`, `⌘[` y
`⌘]`) y Window; un menú de bandeja hace lo mismo en Windows y Linux. Las
notificaciones nativas llevan Approve y Reject para una aprobación pendiente, y el
Dock o la barra de tareas muestra cuántas esperan. **Ajustes → App de escritorio**
abre la app al iniciar sesión, la mantiene con la ventana cerrada y activa o
desactiva el contador.

Encima del contenido hay una fila reservada para arrastrar la ventana, fuera del
área desplazable. Las acciones de página y los botones de cierre siguen siendo
pulsables. El botón web de Architect queda en el borde derecho de la consola y
se despliega al pasar el puntero, dejando la esquina para las acciones y Blobby.

El chat ocupa el área de contenido desde arriba, sin fila de arrastre ni margen de
página. La cabecera de la lista de chats permite arrastrar la ventana; sus botones
siguen funcionando.

**Apariencia** en el menú de cuenta ofrece el modo claro/oscuro y Standard, Glass,
Graphite, Midnight y Paper con vistas previas. La fila indica el estilo actual.
Son las mismas opciones de **Ajustes → Perfil → Apariencia**; cambiar el estilo
conserva el modo de color y la selección se mantiene al reiniciar la app.

**Agents fijados**: la página de un agent ofrece Fijar en el Dock (en la barra de
tareas en otros sistemas). Un agent fijado está en el menú del Dock y en el de la
bandeja, a un clic de un chat nuevo con él. Un archivo soltado sobre el icono del
Dock o sobre Blobby empieza un chat con ese archivo adjunto.

## Blobby { #blobby }

Una criatura al estilo de los avatares de los agents que vive en el escritorio
mientras la consola está abierta, minimizada o cerrada: uno de un reparto de seis,
la cara de uno de tus agents o una cara propia. Avisa cuando hay una aprobación
pendiente, algo nuevo en tu bandeja de entrada o tus runs en curso, y lo abre con
un clic. Arrástralo a cualquier sitio; pellízcalo, desplázate sobre él con `⌘`
pulsado o usa el control deslizante de Ajustes para cambiar su tamaño. Su propia
pestaña en Ajustes elige el personaje, cuánto habla y si muestra actividad.

Su ventana es transparente, lo que en macOS necesita `macOSPrivateApi` en
`tauri.conf.json` - y eso descarta la Mac App Store, adonde una consola
autoalojada no iba a ir de todos modos.

## Pregunta rápida y voz { #quick-ask-and-voice }

**Abrir AgenticOS** (`⌘⇧O` en macOS, `Ctrl+Shift+O` en los demás sistemas) trae
la consola al frente desde cualquier app. Cambia o borra la combinación en
**Ajustes → Atajos**. La barra de menús y los menús de la bandeja y de Blobby
muestran los atajos activos para abrir AgenticOS, Pregunta rápida y Captura a un
chat nuevo. Se actualizan al cambiar una combinación. El menú no anuncia atajos
que no se hayan podido registrar.

**Pregunta rápida** (`⌥Space`, configurable) abre un panel flotante para preguntar
a cualquier agent desde cualquier sitio, sin traer la consola al frente. En macOS
puede llevarse lo que estabas mirando: el texto seleccionado en otra app, el
portapapeles o los archivos seleccionados en el Finder - cada uno mostrado antes de
enviarlo y solo si has permitido a AgenticOS leer la selección.

Mantén `⌥⇧Space` para dictar en la pregunta rápida; una llamada de voz con el
agent por defecto tiene su propio atajo. **Ajustes → Atajos** los reasigna todos:
una combinación necesita al menos un modificador, una que ya tiene otra app se
rechaza conservando la anterior, y **Borrar** la desactiva.

**Captura a un chat nuevo** (`⌘⇧A`) muestra la mira del sistema; la zona que
eliges llega a un chat nuevo, ya adjunta. La primera pulsación pide a macOS
Grabación de pantalla, que funciona tras reiniciar.

Quick Ask conserva toda la conversación: tus preguntas, respuestas anteriores y
actividad y resultados de herramientas usan la vista de mensajes de la consola.
Las aprobaciones, preguntas del agente y solicitudes de conexión se resuelven en
el panel. El texto en espera sin conexión sigue visible y el botón de parada
detiene la ejecución. Los adjuntos y fuentes citadas se abren en el panel; al
desplazarte hacia arriba se pausa el seguimiento automático hasta volver al final.

Selecciona archivos con el clip, pega una imagen del portapapeles o arrastra
archivos a Quick Ask. Los adjuntos aparecen antes de enviar y pueden quitarse por
separado. Se aplica el mismo límite de subida que en el chat. El envío y la creación
de una conversación esperan a que terminen las subidas; un fallo conserva el
borrador del mensaje. Puedes enviar un archivo sin añadir texto.

El botón de fijar mantiene Quick Ask visible sobre otras aplicaciones al hacer
clic fuera de la ventana. Desfíjalo para volver a ocultarlo cuando pierda el foco.
El botón de cerrar, Escape en el campo del mensaje y el atajo de Quick Ask siguen
ocultando el panel fijado. La fijación dura durante la sesión actual de escritorio,
incluso si se recarga la página.

## Trabajar en este ordenador { #work-on-this-computer }

Las operaciones locales usan un descriptor abierto del directorio autorizado. Sustituir un directorio o archivo por un enlace simbólico no puede redirigir una escritura fuera de él. El directorio autorizado y sus directorios superiores se abren sin seguir enlaces simbólicos; las vistas previas y listas usan el mismo límite.

Lo único que un navegador no puede hacer: un chat de escritorio puede
trabajar en una carpeta del ordenador donde corre la app, en vez de en la nube.
Las herramientas de archivos y shell del agent - listar, leer, escribir, editar,
ejecutar - llegan a esa carpeta a través de la app.

**Vincula el ordenador una vez.** En los ajustes del chat, elige
**Trabajar en → Este ordenador** para vincularlo directamente. Confirma en el
diálogo nativo y luego elige una carpeta y su modo de acceso en el mismo panel.
**Ajustes → App de escritorio → Este ordenador → Dejar que los agents trabajen
aquí** ofrece la misma acción. La app obtiene una sesión propia para este
ordenador y guarda su refresh token en el llavero del sistema. Mantiene una
conexión WebSocket saliente al device hub del servidor (`/api/v1/ws/device`);
nada escucha en el ordenador. **Desvincular** termina esa sesión.

**Elígelo por chat.** En la app de escritorio los ajustes del chat ofrecen
**Trabajar en (Work on): Nube / Este ordenador**. Elegir este ordenador pide una
carpeta en el selector nativo y hasta dónde puede llegar el agent en ella:

Este ordenador solo queda seleccionado después de aprobar una carpeta. El
selector de acceso muestra el modo aprobado para esa carpeta; cambiarlo vuelve
a abrir el selector nativo de carpetas para confirmar el nuevo permiso. Cancelar
conserva la elección anterior. La carpeta y el modo se mantienen al cerrar los
ajustes y cuando un chat nuevo recibe su ID.

| Modo                   | Qué puede hacer el agent                                         | Cómo se le sujeta                                                                                                                    |
| ---------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Solo lectura           | Leer archivos; no se escribe nada y no se ejecuta ningún comando | La app rechaza escrituras y comandos                                                                                                 |
| Escribir en la carpeta | Leer, escribir dentro de la carpeta, ejecutar comandos           | Los comandos se ejecutan bajo Seatbelt en macOS y bubblewrap en Linux, con escritura solo en la carpeta y los directorios temporales |
| Acceso completo        | Los comandos se ejecutan como tú, sin aislamiento                | Cada comando se muestra antes en un diálogo nativo para permitirlo                                                                   |

Los comandos pueden leer la carpeta autorizada y los archivos de ejecución del
sistema, pero no otros archivos personales ni credenciales heredadas de la
aplicación. Las herramientas que los necesiten requieren permiso separado para
todo el ordenador. Las lecturas directas de archivos locales tienen un límite de
10 MiB para que un resultado grande no desconecte el dispositivo.

Windows ofrece solo lectura y acceso completo. Linux ofrece escribir en la carpeta
solo cuando `bwrap` está instalado.

**Decide el ordenador, no el servidor.** Las carpetas elegidas, con sus modos, se
guardan en los ajustes de la app, y cada operación nombra una carpeta y un modo que
la app compara con ellos: una carpeta que nunca elegiste, un modo más amplio que
el permitido o una ruta que sale de la carpeta se rechazan en el ordenador, pida
lo que pida el servidor. La elección se recuerda por conversación. Los chats nuevos heredan la última
carpeta y las herramientas de esta cuenta y organización; los ajustes del proyecto
tienen prioridad. El consentimiento para todo el ordenador nunca se hereda.

**Solo tus propios runs.** Un chat llega a tu ordenador solo cuando es tuyo -
nunca una clave de API, un visitante del widget o el chat de otra persona - y un
[trigger](triggers.md) solo cuando actúa como su creador, que le asigna una carpeta
de su ordenador en el campo **Trabajar en** del trigger.

**Cuando el ordenador no está.** Un run que pidió este ordenador y encuentra la app
sin conectar la espera hasta diez minutos, y el chat lo dice. Una operación que
encuentra la app desconectada a mitad del run - tapa cerrada, red cambiada -
espera hasta cinco minutos a que vuelva en la misma sesión y luego sigue. Mientras
una operación de un run está en curso, la bandeja dice que un agent trabaja en este
ordenador.

El servidor comprueba la sesión antes de reenviar cada operación local. Las sesiones revocadas o caducadas rechazan trabajo nuevo; el heartbeat también cierra conexiones inactivas. Las operaciones en curso se cancelan al cerrar el socket del escritorio.

En el Builder, **Sandbox → Computer** guarda `backend: local` sin rutas ni
consentimiento nativo. Cada persona autoriza su propio destino en el chat de
escritorio. Sin selección, la ejecución la solicita en lugar de abrir una sandbox
en la nube. Al crear un proyecto, **Project sandbox → Computer · your files** abre
el selector de carpeta personal; los demás miembros conservan el espacio compartido.

**Todo el equipo.** El chat de escritorio ofrece **Todo el equipo** sin
selector de carpetas. Una advertencia nativa autoriza el acceso para esta conversación:
las herramientas de archivos pueden usar rutas absolutas accesibles para tu cuenta
y los comandos se ejecutan como tú, sin confirmaciones nativas individuales. Siguen
vigentes los permisos del sistema y las reglas de aprobación del agente.
**Revocar acceso a todo el equipo** o elegir **Nube** bloquea nuevas operaciones;
los comandos en curso no se interrumpen. El consentimiento sobrevive a reinicios,
se limita a este servidor y conversación, y un borrador se vincula en su primera
operación. Un chat nuevo necesita su propio consentimiento. Este modo no recorre el
directorio personal ni recoge archivos automáticamente como adjuntos.

Las herramientas locales de navegador y archivos están disponibles en el chat de
escritorio aunque el agente no tenga Browser o Sandbox. La elección añade la
capacidad solo a esa ejecución, mantiene las restricciones de dominios y reglas de
aprobación, y no modifica el agente publicado. Las instantáneas internas de adjuntos
usan listados de archivos en lugar de comandos de shell.

## La pantalla { #the-screen }

[Computer use](reference/capabilities.md) puede manejar la pantalla de este
ordenador. En un chat que trabaja en este ordenador, su escritorio `auto` - el de
por defecto - es esta pantalla; `local` no pide otra cosa.

- **Pregunta primero.** La primera captura de una sesión pregunta, en un diálogo
  nativo, si el agent puede ver y controlar esta pantalla durante una hora.
- **Enmarcada mientras actúa.** Un contorno enmarca la pantalla mientras el agent
  la tiene.
- **Se detiene al instante.** `⌘⌥Esc` (`Ctrl+Alt+Esc` en otros sistemas) recupera
  la pantalla; la siguiente acción se rechaza hasta que lo vuelvas a permitir.
- **El sistema también pregunta.** macOS necesita AgenticOS en Privacidad y
  seguridad, tanto en Grabación de pantalla como en Accesibilidad; un rechazo los
  nombra.

Cada escritorio en el que trabaja un run, este incluido, se muestra en vivo en el
chat y en la vista en vivo del run, donde **Tomar el control** te lo pasa entre los
pasos del agent y **Devolver** se lo devuelve. La vista en vivo de la pantalla de
este ordenador es solo tuya, quien sea que pueda ver runs.

## Iniciar sesión { #signing-in }

La ventana principal de escritorio reserva la franja de arrastre por separado de un margen superior de contenido compacto de 16px. En macOS los controles de ventana tienen una fila reservada de 32px, alineando la marca lateral y el encabezado sin el espacio superior adicional del diseño del navegador.

La consola, Blobby y Quick Ask comparten un perfil WebView persistente con nombre; las
pestañas privadas del agent permanecen aisladas. El cambio desde un perfil anterior
puede requerir iniciar sesión una vez. En Glass, la zona de arrastre usa el fondo del
contenido. El dashboard suaviza la navegación por teclado y los pasos discretos de la
rueda, conservando el desplazamiento fino nativo del trackpad; el movimiento reducido
desactiva el suavizado.

La consola conserva la sesión en cookies HttpOnly persistentes, incluida una cookie de
actualización que se renueva al usar la sesión. Al abrir de nuevo la aplicación se
restaura la sesión mientras siga siendo válida. Los fallos temporales del servidor y los
límites de peticiones conservan la cuenta de escritorio; la sesión se comprueba de nuevo
al recuperar la conexión o activar la ventana. Un token rechazado o revocado sigue
requiriendo iniciar sesión. Si no hay una cuenta local, un servidor no disponible
muestra una opción de reintento en lugar del formulario de acceso.

La única navegación que la ventana de la consola rechaza. Todo lo demás se carga en
la ventana; un clic en **Continue with Google** se abre en tu propio navegador, y
el resultado vuelve a la app (#1532).

Lo que ocurre, en orden:

1. El `/api/oauth/<provider>/login` de la consola se ejecuta **en la ventana**,
   donde puede leer la cookie httpOnly con una invitación preparada y adjuntarla.
2. La ventana ve entonces una navegación al `/api/v1/oauth/<provider>/login` del
   _despliegue_, la pasa al navegador del sistema con `client=desktop` y un
   `desktop_nonce` recién generado y no la sigue.
3. Inicias sesión allí, en un navegador de verdad con tus contraseñas, tus
   extensiones y el segundo factor que uses.
4. El callback del despliegue ve que este intento era de escritorio - anotado en
   la sesión al _principio_ bajo el `state` OAuth de ese intento, nunca leído del
   retorno - y redirige a `agenticos://auth/callback?code=…` con un código de un
   solo uso que caduca en un minuto, más el nonce que recibió.
5. El sistema operativo entrega ese enlace a la app. El shell envía la ventana de
   la consola a `<your server>/auth/callback?code=…`, que canjea el código por el
   par de tokens de servidor a servidor; se fijan las cookies de la propia ventana.

**Cualquier proceso de tu máquina puede lanzar un deep link**, así que lo que uno
puede hacer aquí es estrecho: enviar la consola a una ruta, en el servidor que
_tú_ configuraste, con un código canjeable exactamente una vez - y solo uno con el
nonce que esta app generó para este intento. En Windows y Linux un bloqueo de
instancia única pasa los argumentos de un segundo arranque al primero. El
despliegue tiene que coincidir en el esquema - `DESKTOP_DEEP_LINK_SCHEME`,
`agenticos` salvo que alguien lo cambiara - y en su propia dirección pública.

## Lo que no hace a propósito { #what-it-deliberately-does-not-do }

- **Sin guardia de navegación.** Un enlace que sale del origen del servidor se abre
  en la ventana, porque un flujo OAuth - conectar un servidor MCP - tiene que volver
  al mismo webview para que su cookie llegue. El título de la ventana nombra
  cualquier otro host que muestre.

- **Sin acceso permanente.** Vincular el ordenador no concede nada por sí solo: un
  run llega solo a las carpetas que elegiste, en los modos que elegiste, y a la
  pantalla solo después de que lo permitas.

## Dónde está en el árbol { #where-it-sits-in-the-tree }

- `desktop/ui/` - las páginas del primer arranque y el contorno de la pantalla,
  archivos estáticos.
- `desktop/core/` - las partes en las que ambos lados tienen que coincidir, sin el
  runtime: los mensajes del dispositivo, los endpoints y el back-off, probados por
  separado.
- `desktop/src-tauri/` - el shell: ventanas, menús, Blobby, pregunta rápida, el
  vínculo del dispositivo (`device.rs`), el ejecutor local (`local_work.rs`) y la
  pantalla (`screen.rs`).
- `backend/app/services/device_hub/` - la mitad del servidor: presencia en Redis,
  para que cualquier host de API o worker llegue a un ordenador, y
  `DeviceWorkspace`, el workspace de la sandbox que ejecuta la app.

## Navegador, modelos y MCP locales { #local-browser-models-and-mcp }

Tras emparejar la aplicación, selecciona **Navegador → Navegador local** para
sobrescribir la configuración del agente en esta conversación. La elección es
independiente de **Work on**: no requiere carpeta ni capacidad Sandbox y mantiene
el sandbox del agente en la nube. Los modelos locales y servicios MCP siguen
necesitando una carpeta autorizada o acceso a todo el equipo; la ejecución recibe su propia capacidad Sandbox. La aplicación del teléfono no
invoca comandos de escritorio.

Añade servicios en **Settings → Desktop app → Local services**. Un diálogo nativo
confirma cada permiso. Los modelos usan un endpoint HTTP de Ollama o compatible
con OpenAI (por ejemplo `http://127.0.0.1:11434/v1`) y el ID de un modelo instalado.
MCP requiere un servidor Streamable HTTP en ejecución
(por ejemplo `http://127.0.0.1:8000/mcp`).

Solo se aceptan direcciones loopback, sin
redirecciones ni credenciales en la URL. El escritorio guarda la dirección; la API
transmite un ID opaco del permiso. Las solicitudes y respuestas tienen un límite
de 8 MiB y un plazo de dos minutos. MCP debe aceptar solicitudes sin token y
terminar las respuestas HTTP; no se admiten suscripciones SSE independientes ni
el inicio de procesos stdio. Eliminar un permiso bloquea llamadas posteriores.
El perfil de la organización se conserva para la atribución sin abrir sus credenciales de nube.
La inferencia local no recurre a la nube; las capacidades con modelos separados
mantienen su configuración.

**Local browser** muestra una página nativa en el panel del navegador de la
consola tras el consentimiento en el equipo emparejado. Los clics, el scroll y la
escritura ocurren localmente, sin transmitir capturas. La sesión privada no
importa pestañas ni contraseñas personales. El texto de la página sigue llegando
al modelo del agente. La interacción manual toma el control; **Return to agent**
lo devuelve al agente.

En un chat ancho, el navegador se abre junto a la conversación, tanto local como
remoto. Arrastra el separador o usa sus teclas de flecha para ajustar el ancho.
Maximizar abre la pantalla completa y la acción de volver junto al chat restaura
el panel. Las áreas de chat estrechas y los teléfonos usan la pantalla completa
automáticamente.

La pestaña nativa pertenece al equipo, organización, persona, agente y conversación.
Permanece abierta entre runs; `browser_read` la reanuda. Solo un run puede usarla
a la vez. El run renueva su lease automáticamente; si su backend se detiene,
la lease vuelve a estar disponible tras dos minutos. **Close tab** la elimina; cerrar el panel solo la oculta. Desconectar el
equipo emparejado cierra todas sus pestañas. Se conservan hasta ocho; las inactivas
durante dos horas pueden eliminarse al abrir otra.

El consentimiento del navegador nativo cubre las pestañas de esta conversación durante la conexión actual del dispositivo. Las pestañas nuevas o reabiertas por el agente no vuelven a pedir permiso con la misma política de dominios. Cerrar tú mismo la última pestaña revoca el consentimiento; ocultar el panel no. Desconectar el dispositivo lo elimina. Otra persona, agente, conversación o política de dominios requiere su propio consentimiento.

Computer use y el navegador muestran tarjetas de entorno con descripciones breves. Las nuevas vinculaciones de Computer use eligen explícitamente Docker / Sandbox. Automático ya no se ofrece; las configuraciones anteriores siguen siendo legibles y no cambian hasta que la persona elija un entorno. Docker Compose incluye sandboxd y el runtime desktop. Un operador puede registrar otro host con URL y clave en Conexiones → Sandboxes y elegirlo junto con el runtime desktop en la configuración Sandbox del agente.

Para elegir compatibilidad con Chromium, desactiva **Use the native local browser**
en la capacidad del navegador. Las tareas con vision o cambios de idioma o zona
horaria también usan una ventana
Chromium aislada. Esa ruta requiere Chrome, Chromium, Edge o Brave y cierra su
perfil temporal al terminar el run. Las acciones DOM nativas usan scripts, que
algunas páginas distinguen de la entrada CDP de confianza. Las páginas no reciben
permisos de consola ni archivos; solo pueden notificar una toma de control.
`connection: local` sigue requiriendo la selección del navegador local.

## Instaladores y actualizaciones { #installers-and-updates }

El workflow Apps también genera instaladores de desarrollo y comprueba la instalación sin automatizar la interfaz: copia de la app Mac desde el DMG, instalación y desinstalación silenciosas en Windows, instalación y eliminación de Debian y extracción del AppImage portátil. Verifica el widget integrado de macOS y las firmas, el aislamiento de la sesión persistente y el rechazo de descargas de actualización modificadas. Usa compilaciones ad-hoc o sin firma y no acredita notarización pública ni aprobación de tiendas.

El workflow **Apps** de GitHub Actions comprueba los crates nativos en macOS,
Windows y Linux y construye APK de depuración Android y la aplicación del
simulador iOS. Las comprobaciones completas se ejecutan en CI; `make desktop-check`
sigue disponible para cambios locales concretos. **App release** adjunta
instaladores, archivos de actualización firmados, un APK y un cask Homebrew a una
versión estable ya publicada `v1.MINOR.PATCH` cuyo commit pertenece a `main`.
No crea una versión de la plataforma. El cask es un archivo descargable; publicar
un tap Homebrew es una operación separada. **Check for Updates…** requiere un
build con la clave pública y verifica la firma antes de instalar.

La publicación móvil está desactivada actualmente. La variable del repositorio
`AGENTICOS_MOBILE_RELEASES_ENABLED=true` habilita las versiones firmadas de Android;
iOS requiere además la opción de TestFlight indicada abajo. Las compilaciones
habituales de CI siguen activas. Hasta habilitar la distribución, consulta la
[instalación móvil por tu cuenta](mobile.md#availability-and-self-installation).

Configura el entorno GitHub `apps-release` antes de publicar:

- Variable `AGENTICOS_UPDATER_PUBLIC_KEY`; secretos `TAURI_SIGNING_PRIVATE_KEY`
  y `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` (pareja de claves persistente).
- macOS: `APPLE_CERTIFICATE` (P12 en base64), `APPLE_CERTIFICATE_PASSWORD`,
  `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD` (contraseña de aplicación)
  y `APPLE_TEAM_ID` para firma Developer ID y notarización.
- Authenticode Windows opcional: `WINDOWS_CERTIFICATE_BASE64` (PFX) y
  `WINDOWS_CERTIFICATE_PASSWORD`. Sin ellos, el instalador queda sin firmar.
- Android: `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`,
  `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`. Conserva el keystore para actualizar.
- TestFlight: variable del repositorio `AGENTICOS_TESTFLIGHT_ENABLED=true`; secretos
  `IOS_CERTIFICATE_BASE64`, `IOS_CERTIFICATE_PASSWORD`, `IOS_PROFILES_BASE64_JSON`
  (array JSON de perfiles base64 para aplicación, widgets y extensión de compartir),
  `APP_STORE_CONNECT_KEY_P8`, `APP_STORE_CONNECT_KEY_ID`,
  `APP_STORE_CONNECT_ISSUER_ID`, `APPLE_TEAM_ID`. Crea primero los identificadores,
  el App Group compartido y la aplicación en App Store Connect. Push sigue
  requiriendo las credenciales APNs existentes del despliegue.

Las credenciales de tienda permanecen en CI; los jobs borran archivos temporales
de firma. TestFlight está desactivado hasta habilitarlo explícitamente. La
aprobación de tienda, provisioning y entrega firmada a dispositivos requieren
cuentas del operador; no pueden verificarse con un build local sin firma.

## Resumen { #recap }

- **La consola se queda en el servidor.** El shell la abre; no se empaqueta nada.
- **Nativa donde importa.** Menús, notificaciones, agents fijados, Blobby,
  pregunta rápida y voz desde cualquier sitio.
- **Tus agents pueden trabajar en este ordenador** - en carpetas que eliges, en
  modos que eliges, aislados por el sistema operativo y solo para tus propios runs.
- **Y en su pantalla** - preguntando primero, enmarcados mientras actúan y
  detenidos con un atajo.

Quick Ask admite hasta ocho pestañas independientes por ventana. Cada una conserva su borrador, adjuntos, agente y respuestas en curso. Conversaciones recientes abre una lista con búsqueda y reutiliza una pestaña ya abierta; los chats guardados recuperan mensajes e historial anterior. Las pestañas inactivas no capturan archivos, atajos de dictado ni el foco. Conversaciones recientes muestra avatares de agentes en una sección desplegable que ocupa solo el espacio necesario. Nuevo chat es la única acción para abrir una pestaña nueva. La barra lateral del navegador ofrece la descarga de escritorio; cerrar el aviso lo silencia durante 14 días para esa cuenta en ese navegador.

Quick Ask tiene un botón de micrófono para iniciar el dictado con un clic, además del atajo de mantener pulsado. Las llamadas usan los mismos controles que el chat, con el transporte configurado del agente seleccionado, subtítulos, aprobaciones y preguntas. Los turnos hablados se guardan en la conversación. El envío de texto y el dictado esperan durante una llamada. Cambiar de pestaña o agente finaliza la llamada y libera el micrófono.
