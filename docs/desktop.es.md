---
source_sha: "e2a19cf6c8da"
---

# La app de escritorio { #the-desktop-app }

El inicio de sesión OAuth nativo utiliza PKCE S256. La aplicación conserva un verificador privado; el callback solo contiene su desafío público. El verificador se envía en el cuerpo de la solicitud de intercambio, nunca en una URL. Cerrar sesión elimina las vistas previas nativas de las notificaciones del teléfono.

Al desconectar, cerrar sesión o cambiar de servidor se eliminan los permisos de carpetas, servicios locales, todo el equipo y pantalla. La vinculación muestra la cuenta antes de consumir el código de un solo uso. Los permisos compartidos de carpetas para rutinas sobreviven al vencimiento de la sesión y a una nueva vinculación con la misma cuenta y servidor verificados. Permanecen inactivos hasta verificar otra vez esa identidad; la desconexión explícita, cerrar sesión o cambiar de servidor o cuenta los elimina.

Un delegado publicado que necesite este equipo puede pedir permiso en el mismo chat, aunque el agente principal se ejecute en la nube. El consentimiento pertenece al agente principal que inicia la ejecución. Los delegados de programación locales piden acceso completo; los delegados anidados usan ese espacio aprobado del dispositivo sin compartirlo con otros delegados en la nube. Cancelar un comando o superar su tiempo límite también termina sus procesos secundarios.

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

Al volver de Ajustes del Sistema se actualiza el estado aunque la vista web siga visible. Si la grabación de pantalla está activada pero el acceso sigue denegado, cierra y vuelve a abrir la copia en ejecución y actualiza el estado. Los permisos pueden diferir entre una versión instalada y una copia de prueba con firma ad hoc.

Las tareas ACP locales terminan tras 16.384 eventos entrantes u 8 MiB acumulados de actualizaciones serializadas, incluida la reproducción de la sesión. El error es explícito y se cierra el adaptador.

Un pin del certificado del editor registrado exige el material de firma correspondiente: si falta MACOS_SELF_SIGNED_P12, la versión falla. La firma ad hoc solo se permite en distribuciones sin pin.

## Instalar la aplicación { #installing-the-app }

Descarga el paquete para tu ordenador desde la [versión en GitHub](https://github.com/vstorm-co/agenticos/releases/latest). Instalar una versión no requiere Rust ni herramientas de desarrollo.

- **macOS:** elige Apple silicon o Intel, abre el `.dmg` y arrastra AgenticOS a **Applications** siguiendo la flecha. Inícialo desde Applications y expulsa la imagen de disco.
- **macOS sin la advertencia:** `curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/install_macos.sh | bash` descarga la versión, comprueba su SHA-256 con el publicado junto a ella, copia la aplicación a Applications y quita la marca de descarga de esa sola aplicación. `brew install --cask vstorm-co/agenticos/agenticos` hace lo mismo mediante [el tap del proyecto](https://github.com/vstorm-co/homebrew-agenticos). Las versiones no están notarizadas por Apple, así que un `.dmg` descargado en el navegador sigue pidiendo **Abrir igualmente**. Cuando el proyecto fije el certificado con el que firma sus versiones (`scripts/macos_signing_identity.txt`), el script también rechazará una aplicación firmada con cualquier otro.
- **Windows:** abre el instalador `setup.exe`. Utiliza el idioma del sistema e instala para tu usuario sin permisos de administrador. Abre AgenticOS desde el menú Inicio. También hay un paquete `.msi` para instalaciones administradas.
- **Linux:** abre `.deb` o `.rpm` en el instalador de software de tu distribución. Para una instalación portátil, permite ejecutar el `.AppImage` en sus propiedades y ábrelo.

El primer inicio te guía para conectarte a un servidor o crear una instancia local. Solo las instancias locales necesitan Docker; el asistente lo detecta y ofrece descargarlo si falta. La instalación no concede acceso a la pantalla ni al micrófono.

[Por qué macOS muestra esta advertencia](howto/macos-warning.md).

### Widgets de escritorio en macOS { #desktop-widgets-on-macos }

En macOS 14 o posterior, inicia una vez la aplicación instalada, haz clic derecho en el escritorio, elige **Editar widgets** y busca **AgenticOS**. El pequeño abre Quick Ask; el mediano también Chat, Inbox y Activity. Siguen la apariencia del sistema y solo contienen accesos directos, sin datos de la cuenta. Un clic nunca inicia una grabación ni una llamada.

La CI de versiones crea paquetes nativos para Mac (Apple silicon e Intel), Windows y Linux. Los paquetes macOS usan el certificado autofirmado estable configurado, o firma ad-hoc solo en una distribución sin pin. Estas compilaciones no están notarizadas por Apple. Copia la aplicación a Applications e intenta abrirla. Si macOS la bloquea porque no puede verificar al desarrollador, selecciona **Ajustes del Sistema → Privacidad y seguridad → Abrir igualmente** y confirma. Los ordenadores administrados pueden impedir esta excepción. Consulta las [instrucciones de Apple](https://support.apple.com/es-es/102445). Las actualizaciones descargadas siguen requiriendo una firma válida con la clave de actualización de la versión.

Tras una actualización con firma ad-hoc, macOS puede volver a solicitar acceso al micrófono, grabación de pantalla, accesibilidad o llavero. Si se pierde el emparejamiento del dispositivo, vuelve a conectarlo. Las firmas de actualización verifican el paquete, pero no proporcionan una identidad de firma estable de Apple.

Cuando el workflow de versiones tiene un certificado autofirmado estable (`scripts/create_macos_signing_cert.sh` crea uno), macOS conserva los permisos de grabación de pantalla y micrófono entre actualizaciones, porque están ligados a la identidad de firma. Créalo una vez y no lo sustituyas nunca: un certificado nuevo vuelve a preguntar a todos. Autofirmar no elimina la advertencia de Gatekeeper; solo lo hacen la firma Developer ID y la notarización.

## Paquete nativo de Arch Linux { #native-arch-linux-package }

Descarga `agenticos-VERSION-1-x86_64.pkg.tar.zst` de la versión de GitHub e instálalo con `sudo pacman -U ./agenticos-VERSION-1-x86_64.pkg.tar.zst`. Sustituye `VERSION` por el número de versión. Pacman resuelve las dependencias del sistema declaradas, incluido WebKitGTK 4.1. El paquete no incluye su propio WebKitGTK ni la biblioteca cliente de Wayland.

Antes de instalar, descarga también `SHA256SUMS.arch` y compruébalo con `sha256sum -c SHA256SUMS.arch`. Estos paquetes no están firmados por el llavero de Arch Linux.

Para actualizar, descarga el paquete más reciente y vuelve a ejecutar `pacman -U`. Elimínalo con `sudo pacman -R agenticos`; los ajustes personales permanecen en tu directorio de usuario. **Check for Updates…** explica esta política del gestor de paquetes en lugar de descargar un AppImage. No hay un repositorio automático de pacman ni una publicación oficial en AUR.

La receta mantenida está en `packaging/arch/PKGBUILD.in`. `scripts/build_arch_package.sh OUTPUT_DIRECTORY` genera una receta con versión y un archivo con suma de comprobación desde el commit actual de Git y ejecuta makepkg como usuario normal. Compila en un entorno Arch x86_64 actualizado con las dependencias indicadas en la receta. El workflow de publicación repite la compilación para cada versión de la plataforma; las dependencias de la distribución continua se resuelven al compilar.

El trabajo CI nativo de Arch instala el paquete, actualiza su revisión, comprueba la propiedad y eliminación de archivos y ejecuta la prueba aislada de renderizado WebKit del programa instalado bajo Xvfb/X11 y Weston/Wayland sin pantalla. El artefacto `arch-native` registra rutas de bibliotecas, versiones de paquetes y logs de renderizado. Estas pruebas con renderizado por software no demuestran compatibilidad con todas las GPU físicas, versiones de Mesa, compositores ni instalaciones de CachyOS.

## Ejecutarla { #running-it }

El asistente empieza con el idioma y la elección entre espacio local y
servidor de la organización. Grabación de pantalla, accesibilidad y micrófono
son funciones opcionales disponibles en App readiness o al utilizarlas;
no son un requisito para elegir la conexión.

Al conectar la aplicación de escritorio, puedes pegar el enlace original de invitación en lugar de solo la dirección del servidor. La aplicación se conecta al servidor del enlace y abre la invitación, conservando el destino durante el inicio de sesión. No acepta la invitación automáticamente ni guarda su token en los ajustes nativos. La revisión opcional de conexión espera a que termine la invitación.

El inicio nativo y la consola admiten inglés, polaco, alemán y turco. La elección
se pasa a la consola; el idioma guardado en una cuenta existente sigue teniendo
prioridad. La instalación local pide un nombre de espacio; un nombre de organización
separado es una opción avanzada. Tras revisar la conexión, **Get started** abre
el inicio común de tareas. Un espacio local puede enviar contenido a un proveedor
de IA remoto; instalar localmente no implica IA sin conexión.

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

Elige **Set up this computer** para preparar el entorno local. AgenticOS descarga
Docker Desktop 4.97.0 para tu procesador y verifica su suma SHA-256 fijada. macOS
comprueba el instalador con Gatekeeper, verifica la identidad de firma de Docker
Inc y solicita autorización del sistema.
Windows ejecuta el instalador firmado y prepara las funciones WSL que falten con
autorización del sistema. Si Windows solicita reiniciarse, vuelve a abrir AgenticOS
para continuar. Ubuntu, Debian y Fedora en x86-64 usan el instalador de paquetes
del sistema. Completa los términos propios de Docker al iniciarlo por primera
vez.

En Linux, la configuración añade la fuente de paquetes firmada de Docker si
falta y solicita autorización de administrador para los paquetes y el acceso a KVM.
Reinicia cuando se solicite. Una comprobación de estado nunca instala software por
sí sola.

Antes de instalar, AgenticOS comprueba que haya 4 GB de almacenamiento libre. El
entorno local también requiere al menos 3 GB de memoria visibles para su motor.
Son comprobaciones de inicio, no garantías de capacidad para cualquier tarea. Las
descargas de imágenes muestran progreso y tienen un límite de 30 minutos.
**Retry** continúa la misma instancia conservando sus claves. El uso normal de
la app no requiere Git, Python, uv ni Node.js en el equipo.

Las instancias nuevas fijan la versión de plataforma incluida con la app.
Actualizar la app de escritorio no cambia automáticamente una instancia en uso.
**Update local workspace** descarga las imágenes correspondientes, pausa las escrituras y guarda
una copia de la base de datos, los archivos multimedia y las claves de despliegue
en el directorio privado `backups/` antes de actualizar. Si falla la copia, se
bloquea la actualización. Las copias contienen datos personales y requieren
protección. Se notifican los errores de migración; no se revierte automáticamente
el esquema de la base de datos.

Al abrir AgenticOS se inicia automáticamente el espacio local administrado y
guardado si está detenido, incluido el entorno instalado en sistemas compatibles. No se inician
servidores externos ni entornos de desarrollo no administrados. La app transmite
a los procesos secundarios los directorios de la CLI y de los asistentes de
credenciales de Docker, incluso al abrirla desde Finder; no necesitas editar la
configuración de credenciales de Docker ni el perfil de tu shell.

Las imágenes públicas del producto usan una configuración privada y anónima del
registro para evitar avisos de los asistentes de credenciales y del llavero. Tu
configuración de Docker existente no cambia. La instalación local rechaza los
contextos que apuntan a un motor remoto.

Elige **New instance**, asígnale un nombre e introduce la organización y su
propietario. La aplicación asigna puertos loopback libres y crea un proyecto Compose
separado con base de datos, volumen de archivos, red, directorio de trabajo y claves
propias. Las cookies de sesión tienen un espacio de nombres por instancia, por lo
que cambiar no sustituye el inicio de sesión de otra instalación. Las imágenes del
frontend deben admitirlo; se rechazan las antiguas antes de crear al propietario
o abrir una sesión.

La pantalla local muestra las instancias guardadas, sus direcciones y estado.
**Start and connect** inicia la elegida; **Finish setup** reintenta una instalación
interrumpida conservando archivos y claves. Start y Stop del menú actúan sobre la instancia administrada conectada. **Update local workspace…** abre la lista de instancias locales. Conectarse a un entorno de desarrollo
iniciado externamente no lo convierte en una instancia administrada.

Una instancia local ejecuta la API, el worker, la consola, la base de datos y
Redis, sin servicio de sandbox, servicio de navegador ni almacén de objetos. Los
agentes reciben el espacio de trabajo solo de archivos. En **Chat controls → Tools & files**,
elige **Work on → This computer** para carpetas y **Browser → Local browser**
para navegar. **Computer use** concede pantalla, ratón y teclado por separado.

Los metadatos están en `local-instances.json` en el directorio de configuración;
los archivos nuevos en `local-stacks/<id>/` en el directorio de datos. Las
instalaciones `local-stack/` existentes conservan su proyecto Compose y sus datos.
Las contraseñas y claves de proveedores se pasan al bootstrap sin guardarlas en
estos archivos ni en argumentos de Docker. Las claves del despliegue permanecen
en su `.env` privado; las de proveedores se guardan en la bóveda del servidor.
El asistente nativo usa un foco de teclado neutro y no enfoca automáticamente
los botones de selección.

La aplicación de escritorio y el espacio de trabajo se actualizan por separado.
En el menú principal de macOS, elige **AgenticOS → Update local workspace…**; en
Windows y Linux, usa el menú de la bandeja. La acción también aparece junto a cada
instancia instalada en **Change server… → On this computer**. La lista muestra la
versión de la aplicación, la versión configurada del espacio y la versión de destino
incluida con la aplicación.

En un espacio antiguo sin versión fija, esta figura
como desconocida; el actualizador la comprueba antes de cambiar nada. No se permite volver a una versión anterior. Si el espacio ya está actualizado, **Reapply workspace update** permite recuperarlo tras un reinicio o una migración interrumpidos.

Elige **Update local workspace** y confirma el aviso nativo de copia de seguridad
y reinicio. La lista muestra la descarga de imágenes, la copia y el reinicio, y
luego permite volver a conectarse. Si falla, muestra el error y permite reintentar;
cancelar deja el espacio sin cambios. **Check for Updates…** solo actualiza la
aplicación de escritorio e indica la acción separada del espacio, incluso cuando
la aplicación está al día. Esta ruta funciona también con una consola anterior.

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
**Ajustes → App de escritorio → Este ordenador → Vincular este
ordenador** ofrece la misma acción. La app obtiene una sesión propia para este
ordenador y guarda su refresh token en el llavero del sistema. Mantiene una
conexión WebSocket saliente al device hub del servidor (`/api/v1/ws/device`);
nada escucha en el ordenador. **Desvincular** termina esa sesión; antes pregunta y
enumera lo que borra.

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
todo el ordenador. Las lecturas y escrituras directas de archivos locales tienen un límite de
10 MiB para que las transferencias grandes no desconecten el dispositivo. Las
escrituras mayores se rechazan antes de codificar o enviar los datos del archivo.

Windows ofrece solo lectura y acceso completo. Linux ofrece escribir en la carpeta
solo cuando está instalado `bwrap` con soporte para `--bind-fd`. La app mantiene abierto un descriptor de directorio sin seguir enlaces hasta el inicio del sandbox. Renombrar la carpeta o sustituirla por un enlace simbólico no puede cambiar el directorio aprobado. En Linux, las variables de entorno de la tarea se aplican dentro del sandbox, no a su proceso de lanzamiento; sus valores se pasan mediante un descriptor privado.

La ruta raíz de una carpeta de rutina no puede contener enlaces simbólicos ni junctions. Selecciona la carpeta real en el selector; la admisión en segundo plano nunca resuelve enlaces en la ruta raíz.

**Decide el ordenador, no el servidor.** Las carpetas elegidas, con sus modos, se
guardan en los ajustes de la app, y cada operación nombra una carpeta y un modo que
la app compara con ellos: una carpeta que nunca elegiste, un modo más amplio que
el permitido o una ruta que sale de la carpeta se rechazan en el ordenador, pida
lo que pida el servidor. La elección se recuerda por conversación. Los chats nuevos heredan la última
carpeta y las herramientas de esta cuenta y organización; los ajustes del proyecto
tienen prioridad. El consentimiento para todo el ordenador dado en un chat nunca se
hereda; el dado a un agente vale para ese agente (ver **Todo el equipo**).

**Solo tus propios runs.** Un chat llega a tu ordenador solo cuando es tuyo -
nunca una clave de API, un visitante del widget o el chat de otra persona - y un
[trigger](triggers.md) solo cuando actúa como su creador, que le asigna una carpeta
de su ordenador en el campo **Trabajar en** del trigger.

**En el chat interactivo: cuando el ordenador no está.** Un run que pidió este ordenador y encuentra la app
sin conectar la espera hasta diez minutos, y el chat lo dice. Una operación que
encuentra la app desconectada a mitad del run - tapa cerrada, red cambiada -
espera hasta cinco minutos a que vuelva en la misma sesión y luego sigue. Mientras
una operación de un run está en curso, la bandeja dice que un agent trabaja en este
ordenador.

El servidor comprueba la sesión antes de reenviar cada operación local. Las sesiones revocadas o caducadas rechazan trabajo nuevo; el heartbeat también cierra conexiones inactivas. Las operaciones en curso se cancelan al cerrar el socket del escritorio.

En el Builder, **Sandbox → Computer** guarda `backend: local` sin rutas ni
consentimiento nativo. Cada persona autoriza su propio destino en el chat de
escritorio. Ese agente no tiene espacio en la nube, así que **Work on** no le
ofrece la nube.

Puedes escribirle
antes de conceder nada: responde lo que no necesita archivos y solo cuando una
petición necesita tus archivos pregunta dónde puede trabajar - **Todo el equipo** o
una carpeta. La ejecución espera tu elección y luego el chat continúa solo con los
archivos. La respuesta se recuerda para ese agente en este equipo, de modo que sus
chats posteriores empiezan allí sin preguntar. En la consola web, donde no hay
equipo que conceder, dice que no puede acceder a tus archivos. Al crear un proyecto, **Project sandbox → Computer · your files** abre
el selector de carpeta personal; los demás miembros conservan el espacio compartido.

**Todo el equipo.** El chat de escritorio ofrece **Todo el equipo** sin
selector de carpetas. Una advertencia nativa autoriza el acceso: para un agente con
espacio **Computer**, la advertencia nombra al agente y el consentimiento vale para
él en cada conversación; si no, vale para esta conversación.
las herramientas de archivos pueden usar rutas absolutas accesibles para tu cuenta
y los comandos se ejecutan como tú, sin confirmaciones nativas individuales. Siguen
vigentes los permisos del sistema y las reglas de aprobación del agente.
**Revocar acceso a todo el equipo** o elegir **Nube** bloquea nuevas operaciones;
los comandos en curso no se interrumpen. El consentimiento sobrevive a reinicios,
se limita a este servidor y al agente o la conversación, y un borrador vincula el
consentimiento de una conversación en su primera operación. Un chat nuevo con otro
agente necesita su propio consentimiento. Este modo no recorre el
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
  en la ventana, porque algunos flujos OAuth - conectar una cuenta para un terminal -
  tienen que volver al mismo webview para que su cookie llegue. El título de la
  ventana nombra cualquier otro host que muestre. Conectar un servidor MCP no es uno
  de ellos: su consentimiento se abre en tu propio navegador, donde están tus
  sesiones y passkeys, porque el callback se autentica solo con su `state`. Termina
  allí y vuelve; el servidor aparece en la app cuando queda autorizado.

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

## Coding agents en este equipo { #coding-agents-on-this-computer }

**Settings → Desktop app → Coding agents on this computer** muestra versiones y
estado de sesión. **Set up** prepara Node.js 24.19.0 privado y los adaptadores
fijados mediante un archivo de bloqueo, con comprobaciones de integridad. No
necesitas instalar herramientas de desarrollo por separado. **Sign in** inicia el
flujo OAuth propio del agente en el navegador; AgenticOS no lee ni copia
credenciales. **Refresh status** comprueba la sesión de forma explícita. Volver
a la app no consulta repetidamente el almacén de credenciales; el inicio de sesión
y la preparación correctos actualizan el estado automáticamente.

En la aplicación de escritorio, elige **Controles del chat → Herramientas y archivos → Agente de programación** y selecciona **Claude Code** o **Codex**, aunque la capacidad publicada esté desactivada o ausente. La aplicación prepara las herramientas de archivos locales y abre el selector nativo de carpetas, salvo que la carpeta actual ya tenga acceso completo. Cancelar conserva los ajustes anteriores. **Usar configuración del agente** restaura la configuración publicada.

La selección pertenece a este chat. Se mantienen las reglas de solo lectura y aprobación; la autorización nativa de inicio puede recordarse para este agente y carpeta. Cambiar a la nube elimina la selección local de esta conversación. Los controles del chat se despliegan sobre el campo de mensajes. Sus pestañas son **Model**, **Herramientas y archivos** (Coding agent, Work on, Browser, Computer use y skills) y **Preferencias** (aprobaciones y notificaciones).

Configura la capability **Coding agent** como **On this computer**, elige una
carpeta en **Work on** y concédele acceso completo. La autorización nativa se
recuerda para ese agente, carpeta, versión del adaptador y conexión. Eliminar o
volver a seleccionar la carpeta borra la autorización y detiene sus agentes;
cambiar de cuenta o servidor también borra las autorizaciones. El adaptador se
ejecuta con tu cuenta del sistema: la carpeta indica el directorio de trabajo,
no una sandbox del sistema. El acceso a todo el equipo también inicia un coding
agent, en tu carpeta personal o una carpeta dentro de ella.
Siguen vigentes las aprobaciones de tareas y los permisos del sistema.

La aprobación de la capability se aplica una vez por tarea. `edit` permite las operaciones solicitadas y `read_only` rechaza cambios. Claude desactiva la omisión de permisos en modo lectura y ofrece solo herramientas de lectura. Codex selecciona su sandbox nativa de solo lectura. Los agentes locales usan su propia configuración de modelo. El uso de suscripción no tiene precio registrado; el coste mostrado del run es un mínimo.

Las tareas posteriores reanudan la sesión con nombre (`main` cuando una tarea no indica ninguna) para la conversación, agente, harness, carpeta, cuenta y política de acceso; varias sesiones se ejecutan a la vez, hasta ocho en un ordenador, cada una en la carpeta del chat o en una carpeta dentro de ella. `fresh_session` comienza de nuevo explícitamente. Los identificadores quedan en los ajustes del escritorio, fuera del repositorio, y se borran al desvincular o cambiar de cuenta. Si no se puede cargar una sesión guardada, la tarea falla explícitamente; inicia una nueva cuando corresponda. La desconexión detiene el proceso, pero permite reanudar el historial guardado del harness.

Una corrección enviada durante la tarea local interrumpe el turno ACP actual. Tras confirmar el adaptador la parada, la misma sesión continúa con la corrección. La transcripción registra la corrección aplicada. Un mensaje que llega tras finalizar queda disponible para el agente principal.

Tras elegir el agente de programación y una carpeta autorizada, **Modelo de programación** y **Nivel de razonamiento** muestran las opciones del agente instalado. Se guardan para esta conversación y se aplican antes de una tarea nueva o reanudada. Deja los campos vacíos para conservar los ajustes del agente. Cambiar de agente elimina las opciones incompatibles. Actualiza la lista explícitamente después de cambiar el inicio de sesión o la configuración; otra ventana no vuelve a comprobar la cuenta. Una opción eliminada o no compatible se muestra y se rechaza, sin sustituirla silenciosamente. Consultar las opciones no inicia una respuesta del modelo ni concede permisos de herramientas.

## Tus skills e instrucciones { #your-own-skills-and-instructions }

**Chat controls → Work on → My skills and instructions** elige las fuentes de una conversación: `~/.agents/skills`, `~/.claude/skills` y `~/.codex/skills`. Cada chat nuevo las tiene desactivadas. Los archivos se leen en su ubicación, sin copiar ni sincronizar credenciales o configuración.

Entre las fuentes activadas, los nombres coincidentes se resuelven por `.agents`, después `.claude` y luego `.codex`. Los contadores respetan la selección actual. El escritorio deduplica los enlaces a la misma carpeta de skill. Las instrucciones globales usan el archivo activado más reciente entre `~/.codex/AGENTS.md`, `~/.claude/AGENTS.md` y `~/.claude/CLAUDE.md`, incluidos enlaces simbólicos a Markdown.

Después se leen `AGENTS.md` y `CLAUDE.md` de la carpeta aprobada. Antes de trabajar en una subcarpeta, el agente puede usar `load_local_instructions` para leer la jerarquía desde la raíz aprobada hasta ella. Los archivos específicos siguen a los de sus padres. El lector no sale de la carpeta aprobada ni sigue enlaces simbólicos del proyecto. Las instrucciones no amplían los permisos del run.

El texto de skills e instrucciones cargado pasa por tu servidor al modelo configurado del agente. El selector controla ese contexto de AgenticOS; los coding agents locales conservan su propia configuración y búsqueda de instrucciones.

## Diagnóstico { #diagnostics }

**Help → Export Diagnostics…** escribe un archivo JSON en el lugar que elijas, para adjuntarlo a un informe de error. Contiene la versión, el sistema operativo, lo que macOS ha permitido, si Claude Code y Codex están instalados y con sesión iniciada, la dirección del servidor (solo esquema, host y puerto) y los últimos fallos. No contiene credenciales, tokens, conversaciones ni rutas dentro de tu carpeta personal, y no se envía nada a ninguna parte. Un fallo se escribe en `crash.log` en la carpeta de datos de la aplicación en el momento en que ocurre.

Si la aplicación de escritorio 1.38.1 permanece en **Linked — reconnecting…**
y los chats locales muestran **Waiting for your computer**, busca `rustls` /
`crypto/mod.rs` entre las ubicaciones de los fallos en el diagnóstico exportado.
Este error de inicio de TLS está corregido en una versión de escritorio posterior.
Instálala y vuelve a abrir la aplicación; actualizar solo el servidor no sustituye
al cliente de escritorio. Esta corrección no requiere restablecer el emparejamiento
ni los permisos de las carpetas.

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

La CI de instaladores y las compilaciones de versiones para Linux también inspeccionan el AppImage extraído y rechazan la biblioteca cliente de Wayland incluida (`libwayland-client.so*`), que puede entrar en conflicto con el controlador Mesa del sistema y provocar un fallo de WebKitGTK. La validación se ejecuta antes de subir los instaladores y las firmas de actualización. Esta comprobación de bibliotecas no confirma la compatibilidad de renderizado con todos los compositores Wayland o GPU.

Al ejecutar manualmente un tag antiguo sin `scripts/build_linux_desktop_release.sh`, el trabajo de Linux compila directamente con Tauri y registra una advertencia de que la validación de AppImage previa a la subida no está disponible. Los tags que contienen el wrapper conservan esa validación; un fallo de compilación o validación sigue impidiendo la publicación del manifiesto de actualización.

El workflow **Apps** de GitHub Actions comprueba los crates nativos en macOS,
Windows y Linux y construye APK de depuración Android y la aplicación del
simulador iOS. Las comprobaciones completas se ejecutan en CI; `make desktop-check`
sigue disponible para cambios locales concretos. **App release** adjunta
instaladores, archivos de actualización firmados, un APK y un cask Homebrew a una
versión estable ya publicada `v1.MINOR.PATCH` cuyo commit pertenece a `main`.
No crea una versión de la plataforma. El cask también se publica en el tap Homebrew si se configura una clave de despliegue o un token. **Check for Updates…** requiere un
build con la clave pública y verifica la firma antes de instalar.

Los builds de versiones de escritorio se ejecutan en paralelo. Cada uno sube
sus paquetes firmados; un job final valida los cuatro targets nativos y publica
`latest.json`. CI nativo guarda los resultados de compilación por sistema operativo,
arquitectura, compilador, target y perfil de build. Las versiones solo restauran
las dependencias descargadas del caché compartido. Un build fallido impide publicar
el manifiesto de actualización.

La publicación móvil está desactivada actualmente. La variable del repositorio
`AGENTICOS_MOBILE_RELEASES_ENABLED=true` habilita las versiones firmadas de Android;
iOS requiere además la opción de TestFlight indicada abajo. Las compilaciones
habituales de CI siguen activas. Hasta habilitar la distribución, consulta la
[instalación móvil por tu cuenta](mobile.md#availability-and-self-installation).

Configura el entorno GitHub `apps-release` antes de publicar:

- Firma estable macOS: secretos `MACOS_SELF_SIGNED_P12`, `MACOS_SELF_SIGNED_P12_PASSWORD` y variable `MACOS_SELF_SIGNED_IDENTITY`. Publica la huella pública en `scripts/macos_signing_identity.txt`.
- Homebrew: secreto `HOMEBREW_TAP_DEPLOY_KEY`, una clave de despliegue con escritura limitada al repositorio del tap. `HOMEBREW_TAP_TOKEN` sigue siendo una alternativa. Los archivos temporales se borran también si falla la publicación.
- Variable `AGENTICOS_UPDATER_PUBLIC_KEY`; secretos `TAURI_SIGNING_PRIVATE_KEY`
  y `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` (pareja de claves persistente).
- Firma opcional macOS Developer ID: establece la variable del repositorio `AGENTICOS_MACOS_SIGNING_ENABLED=true` y configura las siguientes credenciales de Apple. Si faltan datos, la compilación falla sin recurrir a firma ad-hoc. Sin la variable o con false, se usa el certificado autofirmado estable configurado, o firma ad-hoc solo en una distribución sin pin. Ninguno tiene notarización; se ignoran las credenciales de Apple.
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

## Rutinas locales { #local-routines }

El rechazo de un equipo sustituto no demuestra que el equipo autorizado haya perdido su permiso: puede estar desconectado. El propietario recibe un aviso sin duplicados para reconectarlo o revisar el acceso; la rutina y sus eventos siguen esperando. Un rechazo de la sesión activa originalmente seleccionada sigue deteniendo la rutina para revisión.

En Linux la app comprueba que bubblewrap anuncie `--bind-fd` antes de ofrecer escritura en carpetas o iniciar un comando aislado. Rechaza versiones ausentes, incompatibles o que no respondan; actualiza bubblewrap para habilitar este modo.

El JSON de permisos de rutinas se verifica con su huella SHA-256 actual en el llavero del sistema operativo. Editarlo o restaurar una copia anterior a una revocación no concede acceso. Un llavero no disponible o una discrepancia bloquea las rutinas. **Actualización:** los permisos antiguos no tienen huella y necesitan nueva aprobación: desconecta explícitamente el equipo, vuelve a vincularlo y revisa sus rutinas. El mismo reinicio recupera una escritura interrumpida; la app nunca confía automáticamente en un archivo sin verificar.

Crea una rutina local con **Ejecutar como yo**, elige una carpeta y selecciona por separado lectura, escritura y ejecución de comandos. Los comandos requieren escritura. Al guardar se crea primero una rutina pausada. La primera vez, la aplicación de escritorio pregunta una vez, de forma nativa, si **todas tus rutinas** de esta organización pueden trabajar en esa carpeta y sus subcarpetas con esas operaciones; elige tu carpeta personal para todo el ordenador.

Cada rutina posterior en esa carpeta se guarda sin preguntar, y el permiso se mantiene tras actualizar la aplicación y volver a iniciar sesión. Cancelar mantiene la misma rutina pausada; reintentar completa su configuración sin duplicarla. Un permiso general de carpeta del chat no autoriza una rutina.

**Ajustes → Escritorio → Permisos de rutinas** muestra los permisos de la cuenta y organización actuales en este ordenador. Revocar uno detiene operaciones posteriores. Cambiar de servidor o de cuenta elimina estos permisos; un permiso para una sola rutina, concedido por una aplicación anterior, también termina con su sesión. Cambiar de carpeta o ampliar operaciones requiere nueva confirmación nativa. Quedan fuera navegador, pantalla, modelos locales, servicios MCP locales y acceso a todo el ordenador. El agente publicado ya debe tener Sandbox habilitado; un destino local no habilita capacidades.

Si el ordenador concreto autorizado está desconectado antes de ejecutar, una activación duradera espera en PostgreSQL. La fila de la rutina muestra cuántas esperan. Las activaciones programadas y manuales se agrupan mientras esperan; los eventos entrantes distintos conservan su contexto e ID de activación. El worker existente comprueba la reconexión cada minuto. Las comprobaciones de disponibilidad no llaman al modelo ni consumen intentos de inicio fallidos. La admisión se confirma con la ejecución antes de la primera llamada al modelo. Una activación iniciada no se repite automáticamente tras una caída del worker; una operación de archivo o comando incierta no genera otra ejecución.

Pausar, cambiar la tarea o el permiso local, eliminar la rutina o alcanzar su fin cancela el trabajo pendiente anterior en lugar de redirigirlo a otra carpeta. Una sesión de dispositivo revocada requiere revisión. Tres trabajos muertos o perdidos antes de la admisión detienen la rutina y crean un incidente para su propietario. El contexto del evento fallido sigue disponible en su exportación de datos. Los contextos iniciados y cancelados se borran de inmediato. Los metadatos terminados y contextos fallidos siguen la retención del historial de ejecuciones de la organización; el trabajo desconectado activo permanece hasta su admisión, cancelación o eliminación.

Actualiza API, workers y escritorio juntos y drena los workers antiguos antes de habilitar el contrato. Las aplicaciones antiguas no confirman permisos de rutinas; las rutinas locales existentes requieren revisión explícita. La migración `0272_routine_device_waits.py` añade esperas sin cambiar la identidad de la rutina. Antes de revertirla, pausa las rutinas locales y drena sus trabajos: la reversión elimina el contexto pendiente y no lo ejecuta. Las ejecuciones locales antiguas suspendidas sin instantánea del destino necesitan una ejecución nueva.

La elección de acceso local pertenece al agente seleccionado, no a un valor global heredado por otros agentes. Revocar una carpeta también elimina las elecciones guardadas y los consentimientos de programación de sus subcarpetas. Las aplicaciones de escritorio antiguas conservan el consentimiento para todo el equipo solo en una conversación; actualiza la aplicación para reutilizarlo en las conversaciones del mismo agente.

La corrección `[session:api] Usa las cifras de la UE` llega a la sesión `api`. Con una sola sesión activa, también recibe las correcciones sin destinatario; con varias, estas quedan para el agente principal para no modificar otra tarea. El agente principal registra la corrección una vez cuando continúa.

 Las tareas de programación en sandbox del mismo conjunto de herramientas se ejecutan en secuencia para evitar que se superpongan sus instantáneas de archivos; las sesiones locales independientes siguen en paralelo.

Los programas ACP instalados se pueden registrar en **Agentes ACP externos**. [Agente ACP externo](reference/capabilities.md#external-acp) explica el registro, los permisos, la identidad de sesión y los límites de facturación.

## Codex como entorno principal de conversación { #codex-conversation }

En el chat Desktop, elige una carpeta autorizada con **Acceso completo** y **Entorno de conversación → Codex · este ordenador**. Codex genera la respuesta; ningún modelo alojado delega el prompt. Inicia sesión mediante los controles nativos de cuentas de programación. El CLI controla cuenta, modelo y cargos; no se importa OAuth de la bóveda ni una clave de perfil cloud. Un ID nativo exacto opcional debe confirmarse antes del prompt. El perfil normal sirve como atribución, no como segundo proveedor de inferencia.

El acceso a herramientas es de solo lectura por defecto. Se rechazan escrituras y comandos nativos; las herramientas de plataforma necesitan clasificación de solo lectura. Editar conserva permisos, aprobaciones y presupuestos del agente. El CLI conserva los permisos del usuario local, sin aislamiento del sistema operativo. Actividad y respuesta en streaming aparecen en el chat; las llamadas reenviadas respetan el límite de pasos/herramientas. Solicitudes internas, tokens y cargos de suscripción/API quedan desconocidos y sin valorar.

Las respuestas finalizadas guardan un comprobante de sesión nativa. Turnos posteriores y reinicios deben comprobar sesión e historial visible antes de enviar contexto nuevo. Cambiar entorno, modelo o política selecciona otro ámbito. **Restablecer sesión nativa** conserva el chat y crea contexto nativo nuevo. La falta de comprobante nunca reanuda ni reenvía automáticamente. Tras Stop, desconexión o entrega incierta, revisa los efectos antes de continuar; no hay reintentos ni reversión automáticos.

Solo se admite el chat web de texto privado y no compartido del miembro iniciador. Desactiva salida estructurada, prompts multimodales, sobrescrituras de modelo, Code Mode, revisores y compactación de plataforma; el CLI gestiona su contexto. La inferencia auxiliar necesita un proveedor compatible separado, no acceso recursivo a la sesión principal. API, voz, programación y otros usuarios no pueden usar la cuenta Desktop. Los perfiles de modelo Codex y las tareas delegadas siguen separados. Inicio de sesión, derechos, efectos de herramientas, cuotas y reanudación requieren aceptación con cuenta real.

## Reenviar herramientas de plataforma { #runtime-platform-tools }

**External ACP agent → Forward platform tools** está desactivado de forma predeterminada. Permite al programa registrado llamar a herramientas ya admitidas en esta ejecución de AgenticOS. Requiere una conversación privada, no compartida, del miembro y su ordenador autorizado. Desktop solicita un consentimiento nativo separado; autorizar una carpeta no activa el puente. Las descripciones de proveedores siguientes se refieren a la configuración predeterminada salvo que se active esta opción.

Un endpoint MCP de bucle local, propiedad del proceso, envía solicitudes mediante el gestor de herramientas preparado de Pydantic AI. Pi usa una extensión de la aplicación; Muse, la configuración MCP de sesión de su SDK. Se mantienen validación, permisos de recursos, presupuestos, aprobaciones y revisión de resultados. Se excluyen herramientas de delegación a runtimes y las llamadas se ejecutan de forma secuencial. Sin descubrir el catálogo limitado se rechaza el prompt ACP. El programa no recibe un token de acceso a la plataforma.

Las acciones que requieren aprobación muestran sus argumentos completos en el chat. La decisión se confirma antes de ejecutar y se comprueban otra vez los permisos al recibir la respuesta. La falta de permisos, tarjetas demasiado grandes, rechazo, caducidad o desconexión no inventan consentimiento ni aparcan el RPC activo. Cancelación, entrega incierta y resultados demasiado grandes o incompatibles son errores explícitos; nunca se repiten acciones automáticamente. Las credenciales MCP locales terminan con el proceso. Las herramientas nativas conservan sus permisos y facturación propios.

## Antigravity mediante ACP { #antigravity-acp }

Instala la CLI de Antigravity de Google. En **External ACP agents**, elige una de
las dos plantillas e introduce la ruta absoluta que devuelve `which agy`. Ambas
permiten solo el argumento `acp` y ninguna copia archivos de tokens.

| Plantilla | Inicio de sesión | Facturación |
| --- | --- | --- |
| **Antigravity** | Inicio de sesión personal de Google (`oauth-personal`). Ejecuta antes `agy acp --login`. Se eliminan las claves de Gemini API heredadas y los selectores de API/Vertex. | Tu plan de Google AI |
| **Antigravity · clave de Gemini API** | `gemini-api-key`, con una clave de Gemini elegida de la bóveda para la ejecución (propósito Google Gemini o Custom) o, si no, la `GEMINI_API_KEY` heredada por Desktop. Una clave de la bóveda requiere tu propio acceso de lectura y solo llega a tu chat privado en tu propio ordenador. Sin clave, el inicio se rechaza; nunca se usa en su lugar el inicio de sesión de Google guardado. | Precios y condiciones de Gemini API |

La primera plantilla conlleva un riesgo para tu cuenta de Google. La sección 6 de
las [condiciones adicionales de Antigravity](https://antigravity.google/terms)
restringe el inicio de sesión de consumidor mediante herramientas de terceros, y un
responsable de Google [indicó en el gestor de incidencias de la CLI](https://github.com/google-antigravity/antigravity-cli/issues/1493)
que no puede servir de backend a un agente de terceros, con medidas contra abusos y
suspensión de la cuenta como consecuencia. Otros clientes, como T3 Code, ofrecen el
mismo inicio de sesión. La consola te pide aceptar este riesgo antes de registrar
la plantilla; la decisión y sus consecuencias son tuyas. La plantilla con clave de
Gemini API lo evita.

Activa **External ACP agent** en el Builder con el ID registrado. Desktop exige el
método de autenticación ACP de la plantilla antes de iniciar una sesión, incluso
cuando la vinculación usa la configuración del programa. Un inicio de sesión
rechazado o no compatible falla sin probar otra cuenta ni otro modo de facturación.

Pide al agente que use `inspect_acp_agent` para leer los modelos y niveles de
razonamiento de la sesión actual. El catálogo no envía ningún prompt y no se
comparte entre cuentas. Que falte el selector no es lo mismo que una lista vacía.
Establece **External model ID** en un ID devuelto exacto para elegir un modelo; si
lo dejas vacío, se mantiene la configuración de la CLI. Una configuración de modelo
no compatible falla de forma explícita.

Esto ejecuta tareas delegadas con las herramientas nativas de Antigravity. Es
independiente de los perfiles de modelo de Gemini API y no reenvía herramientas de
la plataforma AgenticOS de forma predeterminada. El uso no tiene precio en
AgenticOS. Google restringe algunos modelos de terceros a clientes concretos;
AgenticOS se identifica como AgenticOS y no promete acceso más allá de su propio
catálogo anunciado.

### Agentes registrados como entorno de conversación { #external-runtime }

Antigravity con una clave Gemini de Vault usa el campo opcional de ID de modelo nativo, en lugar de consultar el catálogo con la clave heredada por Desktop. Déjelo vacío para conservar la selección de la CLI; un ID explícito se comprueba en la sesión activa antes de enviar el prompt.

Cualquier agente registrado en **External ACP agents** también puede responder la
conversación, en lugar del perfil de modelo del agente, con el [mismo
contrato](#codex-conversation) que Codex y Claude Agent: Antigravity en ambos modos,
Cursor, Cline, Grok, Kimi, Qwen, Devin, Mistral Vibe, OpenCode y Go, Hermes, Muse y
programas ACP propios. Las plantillas de Pi usan RPC en lugar de ACP y solo aceptan
tareas delegadas.

Elige **Este ordenador** con acceso completo y después **Entorno de conversación →
Agente externo · este ordenador**; con varios registros, elige el registro. Desktop
lee los modelos de ese registro con su propio inicio de sesión y sin turno de
modelo, y los muestra en **Modelo**; **Predeterminado del agente** mantiene la
selección de la CLI. Mistral Vibe, Kimi, Qwen, Devin, Hermes y Muse eligen su modelo
en su propia configuración, así que no se lee ninguna lista. Una lectura fallida
muestra el rechazo de la CLI y **Volver a leer los modelos**. Un modelo de la lista
no prueba derechos ni cuota restante.

El entorno está disponible salvo que el operador establezca
`EXTERNAL_NATIVE_CONVERSATION_ENABLED=false`. Las CLI registradas no prometen
confinamiento de solo lectura, así que el entorno siempre se ejecuta con su propio
acceso a herramientas, y las herramientas de la plataforma AgenticOS mantienen la
política de aprobación del agente. Hermes recibe el mismo directorio privado por
conversación que en las tareas delegadas. Un registro que no habla ACP se rechaza
antes de enviar ningún prompt, y cambiar el registro o el modelo inicia una sesión
nativa nueva. Con un inicio de sesión personal de Antigravity, el selector recuerda
el riesgo de la cuenta aceptado al registrarlo.

El inicio de sesión con una cuenta real, los derechos, la cuota, la revocación y la
reanudación tras un reinicio siguen requiriendo pruebas de aceptación. Consulta la
[guía oficial de ACP](https://antigravity.google/docs/ide/extensions/acp) para ver
los métodos de autenticación admitidos y las restricciones de clientes.

## OpenCode y Go mediante ACP { #opencode-acp }

Instala OpenCode, ejecuta `opencode auth login` en una terminal y registra la ruta
absoluta del ejecutable con la plantilla **OpenCode** en **Agentes ACP externos**.
La plantilla inicia `opencode acp`. Las credenciales, los endpoints propios y la
configuración del proyecto permanecen en OpenCode; AgenticOS no copia claves ni
reescribe ajustes. La integración delega tareas nativas, no reenvía herramientas
de AgenticOS ni sustituye el runtime principal de la conversación.

`inspect_acp_agent` devuelve una instantánea de los modelos configurados en la
sesión. Espera brevemente actualizaciones tardías del catálogo ACP;
`refresh_pending` indica que no llegaron modelos durante ese intervalo. Repite
la consulta después de configurar el CLI. El catálogo no confirma derechos de
acceso ni cuota restante. Usa un ID exacto del resultado en **ID del modelo
externo** o conserva el modelo predeterminado del CLI.

Para **OpenCode Go**, conecta la clave Go con `/connect` dentro de OpenCode y
selecciona **OpenCode Go**. Registra la plantilla independiente **OpenCode Go** y
elige un modelo `opencode-go/…`. Se exige ese espacio de nombres antes de la
selección y en los ajustes confirmados de la sesión. Una selección ausente o
distinta falla antes del prompt de inferencia. El catálogo de esta inscripción
filtra otros providers. Un rechazo no cambia automáticamente el provider principal.

Go está destinado a tareas de programación. La restricción afecta al modelo
principal; los modelos auxiliares de OpenCode y **Extra Usage** de Go pueden
generar cargos adicionales. AgenticOS registra el gasto externo sin valorar.
El inicio de sesión, la cuota Go, la revocación y la reanudación tras reiniciar
requieren pruebas con una cuenta real. Consulta la
[guía ACP](https://opencode.ai/docs/cli/acp/) y la
[configuración Go](https://opencode.ai/docs/console/go/).

## Cursor mediante ACP { #cursor-acp }

Instala Cursor CLI, ejecuta `agent login` y comprueba `agent status`. Registra la
ruta absoluta del ejecutable con la plantilla **Cursor**. Inicia `agent acp`,
exige el método anunciado `cursor_login` y elimina los valores heredados
`CURSOR_API_KEY` y `CURSOR_AUTH_TOKEN`. Cursor conserva el inicio de sesión;
AgenticOS no lee archivos de tokens, no cambia ajustes ni instala el CLI. La
plantilla admite la cuenta CLI, no el registro de una clave API. La plantilla separada **Clave API de Cursor** se describe [abajo](#native-account-controls-and-launch-models).

`inspect_acp_agent` lee los modelos de la sesión; **ID del modelo externo** acepta
un ID exacto del resultado. La ausencia de selector no confirma derechos de
acceso. El uso se registra sin valorar; la cuenta Cursor determina los cargos por
suscripción, bajo demanda y otros. Ejecuta `agent logout` y elimina o vuelve a
registrar la entrada Desktop para detener sesiones y borrar continuaciones.
Registra de nuevo después de cambiar de cuenta; cambiar las credenciales del CLI
no revoca por sí solo un proceso activo.

Las preguntas nativas y los planes completos aparecen en el chat en vivo. Solo se
devuelve tu respuesta explícita. Consulta [preguntas del runtime](#runtime-questions). Los permisos ACP estándar siguen la política de delegación
existente. La integración exige acceso local completo y no reenvía herramientas
de AgenticOS. El inicio de sesión, los modelos, el rechazo por cuota y la
reanudación tras reiniciar siguen pendientes de pruebas reales. Consulta
[Cursor ACP](https://cursor.com/docs/cli/acp) y la
[autenticación CLI](https://cursor.com/docs/cli/reference/authentication).

## Cline mediante ACP { #cline-acp }

Instala Cline CLI con soporte ACP directo y registra su ruta absoluta mediante
**Cline** o **Clave API Cline**. Ambas plantillas ejecutan `cline --acp` sin
aprobación automática, fijan `CLINE_PROVIDER=cline` y usan la gestión existente de
procesos y sesiones. No conectan con un hub compartido en segundo plano.

Para **Cline**, ejecuta antes `cline auth`. El proceso elimina `CLINE_API_KEY`
heredado y autentica la cuenta con el método anunciado `cline`. Para **Clave API
Cline**, inicia Desktop con `CLINE_API_KEY` en su entorno. No se aceptan claves en
el spec, los argumentos de registro ni los mensajes del servidor. Una clave
ausente o vacía impide iniciar la sesión. El CLI recibe esa clave; AgenticOS no
recurre al inicio de sesión guardado. La integración no persiste credenciales.

`inspect_acp_agent` consulta el catálogo sin inferencia. Introduce un ID exacto en
**ID del modelo externo** o conserva la selección del CLI. Los créditos, ofertas
gratuitas y cargos dependen de Cline; no se promete ningún modelo gratuito ni
derecho de suscripción. El uso sigue sin valorar. Elimina o registra de nuevo la
entrada después de cambiar credenciales para detener procesos y borrar
continuaciones. Se exige acceso local completo; no se reenvían herramientas de
la plataforma.

El acceso por cuenta o clave, el rechazo por créditos agotados, los modelos y
la reanudación tras reiniciar requieren pruebas reales. Consulta
[Cline ACP](https://github.com/cline/cline/blob/main/docs/usage/acp.mdx).

## Mistral Vibe mediante ACP { #mistral-vibe-acp }

Instala Mistral Vibe, completa `vibe --setup` y registra la ruta absoluta de
`vibe-acp` sin argumentos mediante **Mistral Vibe**. La plantilla exige ACP
`browser-auth`, desactiva la telemetría de este proceso y activa el catálogo
experimental de modelos. Vibe conserva configuración y credenciales. El acceso
por navegador puede crear o reutilizar una clave API; no confirma derechos de
suscripción Le Chat.

`inspect_acp_agent` espera brevemente actualizaciones del catálogo e incluye
`credentials` saneadas: `kind=api_key`, origen (`os_keyring`, `cli_file` o
`environment`) y disponibilidad de cierre de sesión según Vibe. Los informes de
tareas incluyen los mismos datos. No se copian identidad de cuenta, clave,
dominio ni errores de configuración. Un contrato desconocido o credenciales no
disponibles impiden la inferencia. El estado indica almacenamiento, no créditos
restantes ni plan.

La cuenta controla cargos API y de suscripción; el uso externo queda sin valorar.
Eliminar una inscripción no revoca una clave heredada del CLI. Usa los controles
de cuenta y configuración de Vibe y después elimina o registra de nuevo la
entrada Desktop para detener procesos y borrar continuaciones. Se admite acceso
local por navegador, no acceso delegado en hosts remotos. Se exige acceso local
completo; reenviar herramientas es una [opción explícita](#runtime-platform-tools).
Inicio de sesión, límites, cierre y reanudación requieren pruebas reales. Consulta
[configuración ACP de Vibe](https://docs.mistral.ai/vibe/code/use-vibe-in-other-ides).

Mistral Vibe informa `configuration_policy=launch`: elige un ID de modelo externo anunciado. Desktop establece `VIBE_ACTIVE_MODEL` solo en ese proceso, sin invocar la operación que guarda el modelo predeterminado de Vibe.

## Grok Build mediante ACP { #grok-acp }

Instala Grok Build, completa `grok login` (o `grok login --device-auth`) y registra la ruta absoluta de `grok` con la plantilla **Grok**. Ejecuta `--no-auto-update agent stdio`, elimina `XAI_API_KEY` y `GROK_CODE_XAI_API_KEY` heredadas y establece `GROK_DISABLE_API_KEY_AUTH=true` solo para ese proceso hijo.

AgenticOS exige el método anunciado `cached_token`, rechaza un runtime que siga anunciando `xai.api_key` y solicita autenticación sin interacción. No importa archivos de tokens ni cambia a una clave u otro inicio de sesión. Consulta los modelos mediante `inspect_acp_agent`; cuenta, gateway y plan determinan disponibilidad y cargos. La plantilla no promete Build en todos los planes Grok. Las preguntas al usuario aparecen en el chat en vivo; una respuesta final vacía es un fallo explícito.

La plantilla separada **Clave API de Grok** aísla la clave de las cuentas guardadas; consulta los [controles nativos](#native-account-controls-and-launch-models).

## Kimi Code mediante ACP { #kimi-acp }

Instala Kimi Code CLI, completa `kimi login` y registra la ruta absoluta de `kimi` con **Kimi Code**. La plantilla ejecuta `acp` y exige el método anunciado `login`. Comprueba la autenticación del CLI; AgenticOS no abre un terminal de acceso ni importa tokens. Credenciales ausentes o caducadas detienen la tarea sin probar otro método.

Elige un ID exacto de Kimi desde `inspect_acp_agent`. El host verifica el código y cambia solo la configuración en memoria; Kimi conserva credenciales, renovación y facturación. Las preguntas siguen apareciendo en el chat.

Registra de nuevo tras cambiar de cuenta. Permisos, cuotas, reconexión, cancelación y modelos con cuenta real siguen como criterios de aceptación. Es ejecución local delegada sin herramientas de plataforma AgenticOS de forma predeterminada. Consulta [Kimi ACP](https://www.kimi.com/code/docs/en/kimi-code-cli/reference/kimi-acp).

## Suscripción Qwen mediante ACP { #qwen-subscription-acp }

Instala Qwen Code CLI actualizado, ejecuta `qwen` y elige **Qwen Account with Subscription** mediante `/auth`. Registra la ruta absoluta de `qwen` con **Qwen subscription**. El proceso hijo ejecuta `--acp --auth-type=qwen-subscription` y elimina `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` y `DASHSCOPE_API_KEY` heredadas. Las versiones incompatibles deben actualizarse; no se cambia a una clave API.

La plantilla no llama a ACP `authenticate`, que puede cambiar el método de acceso guardado. Qwen usa su propio acceso de suscripción. Un ID opcional anunciado se pasa mediante `--model` al iniciar y debe confirmarse antes de inferir.

Qwen Plus/Pro es distinto de claves API Alibaba Model Studio y endpoints Coding/Token Plan. No se ofrece la antigua cuota OAuth gratuita retirada. Planes, cuotas, caducidad, revocación, cancelación, reconexión y modelos requieren aceptación con cuenta real. Registra de nuevo tras cambiar de cuenta. Reenviar herramientas es una [opción explícita](#runtime-platform-tools). Consulta [autenticación Qwen](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/).

## Devin CLI mediante ACP { #devin-acp }

Instala Devin CLI, completa `devin auth login` y comprueba `devin auth status`. Registra la ruta absoluta de `devin` con **Devin**. La plantilla ejecuta `--permission-mode normal acp`, exige el método anunciado `devin-browser` y rechaza flags adicionales de nube u omisión de permisos. Las credenciales quedan en el CLI; AgenticOS no las importa.

Esto delega al CLI local, no a la API de tareas Devin Cloud. Un modelo opcional anunciado se pasa mediante `--model` al iniciar y debe confirmarse antes de inferir. Las políticas de cuenta determinan acceso y facturación.

Registra de nuevo tras cambiar de cuenta. Inicio de sesión, caducidad, revocación, cuotas, modelos, reanudación, cancelación y cambio de cuenta requieren aceptación real. La interfaz nativa de preguntas sigue sin verificar. Reenviar herramientas es una [opción explícita](#runtime-platform-tools). Consulta [Devin ACP](https://docs.devin.ai/cli/acp/zed) y [comandos](https://docs.devin.ai/cli/reference/commands).

## Pi mediante RPC nativo { #pi-rpc }

Registra **Pi** en Ajustes → Aplicación Desktop con la ruta absoluta de `pi`. La plantilla inicia exactamente `--mode rpc` con los proveedores, modelos, cuentas y extensiones propios de Pi. Inicia sesión y elige el modelo en Pi primero; deja External model ID vacío. La ejecución delegada requiere una carpeta con acceso completo aprobado expresamente. No hay aislamiento del sistema operativo. Las herramientas de plataforma están desactivadas de forma predeterminada; esta plantilla nunca exporta claves de la bóveda. Las herramientas y extensiones de Pi conservan sus permisos. La facturación de suscripción o API depende de la cuenta elegida; el coste permanece desconocido.

Usa `inspect_acp_agent` para descubrir identificadores de modelo con su proveedor en el catálogo de Pi configurado. El nombre de la herramienta se conserva por compatibilidad; el transporte es Pi RPC, no ACP. El catálogo no demuestra autenticación, derechos del plan ni crédito. Las tareas con nombre guardan el archivo nativo de sesión en el ámbito existente de organización, persona, chat, carpeta y versión de registro. Registra de nuevo tras cambiar de cuenta. Una reanudación fallida se rechaza en lugar de iniciar otra sesión silenciosamente.

La finalización espera a `agent_settled`, incluidos los reintentos y la compactación automáticos posteriores a `agent_end`. Un prompt fallido, cancelado, en cola o procesado por una extensión nunca se informa como completado. Stop vacía la cola, cancela el turno activo y cierra el árbol de procesos propio. Los diálogos de extensiones compatibles aparecen como tarjeta de chat; no se inventan respuestas humanas. Streaming, reanudación tras reinicio, cuotas, cancelación y compatibilidad de extensiones con una cuenta real siguen siendo pruebas de aceptación. Consulta [Pi RPC](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md).

## Muse mediante el SDK oficial { #muse-sdk }

Elige **Muse** o **Muse API key** en Ajustes → Aplicación Desktop con la ruta absoluta a la CLI Muse **1.4.23**. AgenticOS incluye el `@muse-code/sdk` compatible con licencia MIT en su entorno Node administrado. El SDK gestiona negociación MSP, reconstrucción de eventos, repetición y resultados de turnos; un adaptador conecta con el transporte de tareas existente. Inicia su propio proceso `muse serve` en primer plano. No se conecta a un demonio ni trata una cuenta Meta como un token genérico de modelo.

Configura la cuenta primero en `muse`. Muse prioriza claves del entorno, luego claves guardadas y finalmente el inicio de sesión del navegador. La inspección muestra la fuente efectiva de clave API u OAuth sin copiar tokens ni etiquetas de cuenta al informe. El modo de clave requiere `META_API_KEY` en Desktop y confirmación de esa fuente; una clave guardada o sesión del navegador no puede sustituirla silenciosamente. El acceso del navegador no demuestra derechos ni facturación. Las cuentas Meta administradas pueden requerir claves API. El coste permanece desconocido.

Las tareas requieren consentimiento expreso para una carpeta con acceso completo. Muse conserva sus herramientas y extensiones; no se transfieren herramientas de la plataforma de forma predeterminada ni se ofrece ejecución sin herramientas. `inspect_acp_agent` consulta el catálogo actual con identificadores de proveedor; los cambios requieren coincidencia y confirmación del servidor. Las sesiones duraderas usan el historial de reanudación existente. La falta de persistencia o versiones SDK/CLI incompatibles provocan rechazo. Cancelar alcanza el turno SDK y cierra el árbol de procesos propio. Los resultados fallidos o desconocidos nunca se convierten en éxito. Derechos, cuotas, reanudación, Stop y compatibilidad de extensiones siguen siendo pruebas con cuentas reales. Consulta [Muse SDK](https://github.com/meta-models/muse-code-sdk) y [autenticación](https://www.musemuse.dev/docs/muse-code/auth).

## Preguntas del runtime { #runtime-questions }

Las preguntas y planes completos de Cursor, preguntas de Grok, preguntas de Kimi mediante permisos, diálogos select/confirm/input/editor de Pi y entradas del SDK Muse aparecen en la tarjeta de chat existente. Se conservan límites de selección, identidad de opciones y vistas previas nativas. El editor de Pi conserva sangría, saltos de línea y un reemplazo vacío explícito. Las contraseñas se introducen en el inicio de sesión del proveedor.

Las respuestas requieren la conexión activa y autorizada de la persona que inició la tarea y la identidad de la pregunta actual. Stop, desconexión, caducidad nativa o finalización cierra la tarjeta; una respuesta tardía no puede contestar otra pregunta. Sin una interfaz activa, las solicitudes se cancelan explícitamente. Estos diálogos no conceden permisos de herramientas ni debilitan la política de delegación. Preguntas y respuestas aceptadas se guardan en la cronología existente.

### Gestionar la cuenta Muse en Desktop { #muse-account }

Cada registro Muse ofrece **Comprobar cuenta**, **Iniciar sesión en Muse** y **Cerrar sesión en Muse**. El acceso por dispositivo utiliza el SDK fijado y el flujo propio de Muse. Confirma el diálogo nativo, abre la dirección HTTPS mostrada e introduce el código. Mantén Ajustes abierto hasta finalizar. Cancelar, cerrar el control, cambiar registro o servidor, o diez minutos sin completar termina el proceso de acceso propio. Etiquetas de cuenta, claves y códigos no se envían al backend ni al modelo.

El acceso requiere una cuenta Muse desconectada sin clave API prioritaria. La plantilla con clave de entorno ofrece estado y cierre de sesión sin acceso por navegador. Cerrar sesión elimina la cuenta o clave guardada de Muse; una `META_API_KEY` heredada sigue activa y se indica así. Cambiar de cuenta detiene todas las tareas Muse y borra sus continuaciones porque la CLI local comparte credenciales. Nuevas tareas esperan a que termine la gestión de cuenta. Derechos del plan y acceso real por dispositivo siguen siendo pruebas de aceptación.

## Pi con una clave API elegida de la bóveda { #pi-vault-key }

Registra **Pi · Inception**, **Pi · DeepSeek** o **Pi · OpenRouter** con la ruta absoluta a Pi CLI **1.5.2**. En External ACP agent elige el mismo **proveedor con clave de bóveda**, su clave API y una **External model ID** exacta con prefijo del proveedor, por ejemplo `deepseek/<model-id>`. Estos modos de clave API son distintos de las cuentas guardadas de Pi y de los proveedores directos de Pydantic AI.

Solo el ordenador privado de la persona que inicia la tarea, aprobado con acceso completo, puede recibir la clave. Poder ejecutar el agente no basta: se comprueban membresía actual y visibilidad independiente de esa clave antes de cada inicio o inspección. Ejecuciones anónimas, de sala compartida o por suplantación no pueden exportarla. El registro nativo debe confirmar el mismo proveedor antes de enviar un prompt. Rotar la clave cambia el ámbito de continuación.

Pi usa configuración privada temporal sin cuentas guardadas, extensiones descubiertas, habilidades, plantillas de prompts ni servidores MCP. Una extensión sin clave escrita recibe la clave en el entorno del proceso hijo, elimina variables iniciales y sobrescribe la autenticación, incluidos ambos encabezados de OpenRouter. La clave nunca entra en argumentos, archivos generados, parámetros de herramientas del modelo ni informes. Las herramientas nativas conservan acceso local completo; no hay sandbox del sistema. Los fragmentos de texto esperan a poder redactar la respuesta completa; la actividad de herramientas sigue visible.

Los identificadores, límites de contexto/salida y precios de chat Inception provienen de su catálogo autenticado actual. DeepSeek y OpenRouter usan catálogo y transporte de la versión fijada de Pi. Cambiar modelo requiere confirmación nativa exacta. La inspección devuelve hasta 128 opciones, mantiene primero el modelo actual e indica truncamiento. Un catálogo no prueba derechos ni crédito. Los cargos siguen sin precio calculado en AgenticOS. Claves inválidas, falta de crédito y modelos desconocidos no cambian a otra cuenta o facturación.

Los archivos privados de sesión se limitan a persona, agente, chat, carpeta, registro y revisión de clave. La configuración temporal se elimina con el proceso propio. Elimina o registra de nuevo la entrada para revocar continuaciones. Pruebas con claves reales cubren streaming, 401/402, cuotas, reinicio/reanudación y Stop. Reenviar herramientas es una [opción explícita](#runtime-platform-tools). Consulta [extensiones de proveedor Pi](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/custom-provider.md) y [modelos Inception](https://www.inceptionlabs.ai/models).

Codex y Claude Agent están disponibles salvo que el operador establezca `CODEX_NATIVE_CONVERSATION_ENABLED=false` o `CLAUDE_NATIVE_CONVERSATION_ENABLED=false`. Cada persona usa su propia cuenta de la CLI y responde de sus condiciones. OpenAI no permite la autenticación de App Server en servicios comerciales o alojados sin aprobación, y Anthropic exige aprobación previa para ofrecer el inicio de sesión de claude.ai o los límites de consumo en un producto SDK de terceros; el selector indica que el proveedor puede limitar o suspender una cuenta. Los interruptores no acreditan derechos ni aprobación.

Cambiar el inicio de sesión desde Desktop detiene los procesos activos de ese entorno y borra sus continuaciones guardadas; restablece la sesión nativa antes de continuar. Los cambios manuales de cuenta fuera de Desktop también requieren un restablecimiento explícito.

Claude Agent utiliza el adaptador ACP fijado de Claude Code como entorno principal de conversación, con el mismo contrato de sesión privada, streaming, política de herramientas y recuperación que Codex. El binario del proveedor y sus métodos de autenticación no se modifican. La interfaz usa el nombre permitido «Claude Agent».

## Hermes en un proceso propio {#hermes-runtime}

Registre el **ejecutable de Python** del entorno preparado de Hermes, con la plantilla Hermes y sin argumentos. Esta integración utiliza la revisión `91cb42b51bddc6841c4e50183c41c96d59e48516`. Prepare ese checkout según las instrucciones de dependencias del proyecto y seleccione su entorno Python. Desktop verifica tres archivos del adaptador antes de ejecutar inferencia. Otras revisiones se rechazan hasta revisar su compatibilidad.

Desktop ejecuta `HermesACPAgent(session_manager=SessionManager())` en su propio proceso. El comando habitual `hermes acp` selecciona el visor del gateway compartido. El gestor explícito mantiene esta integración en primer plano: Stop cierra su árbol de procesos y nunca usa ni detiene un gateway personal. El descubrimiento de modelos, varios turnos, streaming, permisos nativos y herramientas opcionales de la plataforma utilizan la interfaz ACP existente.

Cada conversación privada del miembro iniciador recibe un directorio Hermes separado, vinculado también al agente, carpeta, conexión y revisión del registro. Se rechazan ejecuciones compartidas o suplantadas. El primer inicio muestra el directorio exacto y las instrucciones locales. Establezca `HERMES_HOME` en ese directorio y ejecute Python con `-m hermes_cli.main --profile default setup`; para Nous Portal use `-m hermes_cli.main --profile default auth add nous --type oauth`. Configure allí el modelo y proveedor. No se importan directorios existentes, memoria, habilidades ni archivos de tokens.

Hermes gestiona credenciales, renovación, facturación API/suscripción y herramientas nativas. El inicio de sesión y el catálogo no acreditan derechos del plan. El uso no tiene precio calculado. Detenga la ejecución antes de cambiar de cuenta y registre de nuevo para invalidar continuaciones y elegir un perfil nuevo. Eliminar un registro no borra archivos del proveedor; retire ese directorio por separado cuando ya no necesite la cuenta. Las herramientas nativas conservan el acceso local completo aprobado explícitamente. Las pruebas de cuenta se documentan por separado en el PR.

## Controles nativos de cuenta y modelos al iniciar { #native-account-controls-and-launch-models }

En **Ajustes → Aplicación Desktop**, los registros de Cursor, Grok, Kimi, Devin y Vibe ofrecen estado, inicio de sesión, reconexión, cierre de sesión y cancelación. La reconexión cierra primero la sesión. Una confirmación nativa identifica el programa antes de modificarlo; se detienen todos los registros de ese CLI, se borran continuaciones y permisos recordados y los nuevos inicios esperan al cierre del proceso. El proveedor conserva el acceso; códigos y credenciales no llegan al backend. Vibe identifica las claves heredadas del entorno y no las elimina.

**Clave API de Cursor** requiere `CURSOR_API_KEY` en el entorno de Desktop y elimina `CURSOR_AUTH_TOKEN`. **Clave API de Grok** requiere `XAI_API_KEY`, usa un `GROK_HOME` privado sin copiar cuentas ni ajustes y autentica solo como `xai.api_key`. Los datos de sesión conservan su ámbito entre reinicios; el archivo `auth.json` del CLI se elimina al terminar y antes de reutilizarlo tras una caída. La ausencia de clave o un rechazo nunca seleccionan una cuenta guardada. El catálogo usa la misma credencial aislada.

La elección de modelos de Vibe, Kimi, Qwen y Devin se aplica al proceso iniciado (`configuration_policy=launch`), nunca a los valores predeterminados del usuario. El runtime debe confirmar el modelo antes de recibir un prompt; se rechazan discrepancias y cambios separados del nivel de razonamiento. Un ID vacío conserva el valor del CLI. Kimi requiere una instalación Python de la revisión `9ab1286b8fe4e6bcd116949a27ce5e0ac3389c82`; registra su launcher `kimi` cuyo shebang apunta al Python de ese entorno. El host verifica huellas del código antes de cargarlo. Un CLI binario o incompatible rechaza cambios de modelo.

Actualiza API y Desktop juntos. Estos controles y pruebas de protocolo no verifican el plan, la cuota ni la facturación de cuentas reales; esa aceptación queda aplazada.
