---
source_sha: "f70dbf41fb0d"
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

## Ejecutarla { #running-it }

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

**Cambiar servidor…** también es un botón fijo sobre tu cuenta en la barra
lateral de la consola. Abre directamente el formulario de conexión; la barra
lateral contraída muestra su icono de servidor. Puedes cambiar la dirección sin
usar blobby.

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

## Trabajar en este ordenador { #work-on-this-computer }

Lo único que un navegador no puede hacer: un chat cuyo agent tiene sandbox puede
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

| Modo | Qué puede hacer el agent | Cómo se le sujeta |
|---|---|---|
| Solo lectura | Leer archivos; no se escribe nada y no se ejecuta ningún comando | La app rechaza escrituras y comandos |
| Escribir en la carpeta | Leer, escribir dentro de la carpeta, ejecutar comandos | Los comandos se ejecutan bajo Seatbelt en macOS y bubblewrap en Linux, con escritura solo en la carpeta y los directorios temporales |
| Acceso completo | Los comandos se ejecutan como tú, sin aislamiento | Cada comando se muestra antes en un diálogo nativo para permitirlo |

Windows ofrece solo lectura y acceso completo. Linux ofrece escribir en la carpeta
solo cuando `bwrap` está instalado.

**Decide el ordenador, no el servidor.** Las carpetas elegidas, con sus modos, se
guardan en los ajustes de la app, y cada operación nombra una carpeta y un modo que
la app compara con ellos: una carpeta que nunca elegiste, un modo más amplio que
el permitido o una ruta que sale de la carpeta se rechazan en el ordenador, pida
lo que pida el servidor. La elección se recuerda por conversación, y un chat nuevo
empieza en la nube.

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

La única navegación que la ventana de la consola rechaza. Todo lo demás se carga en
la ventana; un clic en **Continue with Google** se abre en tu propio navegador, y
el resultado vuelve a la app (#1532).

Lo que ocurre, en orden:

1. El `/api/oauth/<provider>/login` de la consola se ejecuta **en la ventana**,
   donde puede leer la cookie httpOnly con una invitación preparada y adjuntarla.
2. La ventana ve entonces una navegación al `/api/v1/oauth/<provider>/login` del
   *despliegue*, la pasa al navegador del sistema con `client=desktop` y un
   `desktop_nonce` recién generado y no la sigue.
3. Inicias sesión allí, en un navegador de verdad con tus contraseñas, tus
   extensiones y el segundo factor que uses.
4. El callback del despliegue ve que este intento era de escritorio - anotado en
   la sesión al *principio* bajo el `state` OAuth de ese intento, nunca leído del
   retorno - y redirige a `agenticos://auth/callback?code=…` con un código de un
   solo uso que caduca en un minuto, más el nonce que recibió.
5. El sistema operativo entrega ese enlace a la app. El shell envía la ventana de
   la consola a `<your server>/auth/callback?code=…`, que canjea el código por el
   par de tokens de servidor a servidor; se fijan las cookies de la propia ventana.

**Cualquier proceso de tu máquina puede lanzar un deep link**, así que lo que uno
puede hacer aquí es estrecho: enviar la consola a una ruta, en el servidor que
*tú* configuraste, con un código canjeable exactamente una vez - y solo uno con el
nonce que esta app generó para este intento. En Windows y Linux un bloqueo de
instancia única pasa los argumentos de un segundo arranque al primero. El
despliegue tiene que coincidir en el esquema - `DESKTOP_DEEP_LINK_SCHEME`,
`agenticos` salvo que alguien lo cambiara - y en su propia dirección pública.

## Lo que no hace a propósito { #what-it-deliberately-does-not-do }

- **Sin guardia de navegación.** Un enlace que sale del origen del servidor se abre
  en la ventana, porque un flujo OAuth - conectar un servidor MCP - tiene que volver
  al mismo webview para que su cookie llegue. El título de la ventana nombra
  cualquier otro host que muestre.
- **Sin run local sin sandbox.** Trabajar en este ordenador cambia dónde se ejecutan
  las herramientas de la sandbox de un agent; un agent sin sandbox no tiene esas
  herramientas que mover.
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
necesitando una carpeta autorizada y un sandbox. La aplicación del teléfono no
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

Para elegir compatibilidad con Chromium, desactiva **Use the native local browser**
en la capacidad del navegador. Las tareas con vision o cambios de idioma o zona
horaria también usan una ventana
Chromium aislada. Esa ruta requiere Chrome, Chromium, Edge o Brave y cierra su
perfil temporal al terminar el run. Las acciones DOM nativas usan scripts, que
algunas páginas distinguen de la entrada CDP de confianza. Las páginas no reciben
permisos de consola ni archivos; solo pueden notificar una toma de control.
`connection: local` sigue requiriendo la selección del navegador local.

## Instaladores y actualizaciones { #installers-and-updates }

El workflow **Apps** de GitHub Actions comprueba los crates nativos en macOS,
Windows y Linux y construye APK de depuración Android y la aplicación del
simulador iOS. Las comprobaciones completas se ejecutan en CI; `make desktop-check`
sigue disponible para cambios locales concretos. **App release** adjunta
instaladores, archivos de actualización firmados, un APK y un cask Homebrew a una
versión estable ya publicada `v1.MINOR.PATCH` cuyo commit pertenece a `main`.
No crea una versión de la plataforma. El cask es un archivo descargable; publicar
un tap Homebrew es una operación separada. **Check for Updates…** requiere un
build con la clave pública y verifica la firma antes de instalar.

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
