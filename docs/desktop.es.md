---
source_sha: "2a08473da582"
---

# La aplicación de escritorio { #the-desktop-app }

AgenticOS se ejecuta en un navegador, y así es como lo usa la mayoría. La
aplicación de escritorio es un añadido para quien la quiera en el dock: la consola
en una ventana propia, más una mascota y un atajo de captura de pantalla. Nada de
la plataforma la necesita.

<figure markdown>
  ![Amigo, la mascota de escritorio, diciendo: No more caramba.](assets/desktop_no_more_caramba_pet.png){ width="270" }
  <figcaption>Amigo, una de las cinco mascotas. No more caramba in your AI.</figcaption>
</figure>

La aplicación que hay dentro de la ventana es la misma consola Next.js que el
servidor ya sirve, cargada desde el servidor, así que lleva el mismo inicio de
sesión, los mismos permisos y las mismas comprobaciones de inquilino que llevaría
una pestaña del navegador.

Es un envoltorio [Tauri](https://tauri.app) en `desktop/`, y guarda exactamente un
ajuste: la dirección del servidor. El primer arranque la pide, "Shell → Change
server…" la vuelve a pedir, y todo lo que hay en medio es la consola.

!!! note "Es un envoltorio, no un build del frontend"

    `frontend/` es una aplicación Next.js con una mitad de servidor — noventa y
    tantos route handlers que hacen de proxy hacia el backend, cookies de sesión
    que ellos fijan, middleware que elige la locale y páginas renderizadas en el
    servidor. Nada de eso corre dentro de un binario de escritorio, así que el
    envoltorio ni lo intenta: abre la URL del deployment igual que lo haría un
    navegador. Un deployment es lo que instalas; la app es cómo lo abres.

## Ejecutarla { #running-it }

Rust desde [rustup](https://rustup.rs) y el webview de la plataforma — WebKit en
macOS, WebView2 en Windows, WebKitGTK en Linux — son los requisitos previos; la
[página de requisitos](https://v2.tauri.app/start/prerequisites/) del propio Tauri
tiene la lista por plataforma. La CLI de Tauri está fijada en
`desktop/package.json`, y `make install` la descarga con todo lo demás.

```bash
make desktop-dev     # opens the shell; type the address of a console
make desktop-build   # a .app / .dmg, .msi or .deb/.AppImage for this machine
make desktop-check   # rustfmt, clippy with warnings denied, and the tests
```

La primera vez, la ventana muestra un formulario que pregunta dónde está el
servidor, relleno con `http://localhost:3000` — un stack de `make dev`. Un host a
secas (`agenticos.acme.com`) se abre por HTTPS. Todo lo que no sea una dirección
web se rechaza en el formulario.

!!! warning "El `http://` a secas es solo para esta máquina"

    A `localhost`, `127.0.0.1` y `::1` se puede llegar en claro; cualquier otro
    host se rechaza hasta que sea `https://`. La consola envía la contraseña y
    recibe de vuelta el token por esa conexión, y una LAN es exactamente el sitio
    donde otro puede leerlo.

Una dirección en la que no responde nada también se rechaza: el envoltorio abre
una conexión TCP antes de apuntar el webview a ninguna parte, porque WebKit pinta
una conexión rechazada como una ventana en blanco. La misma sonda corre en cada
arranque, así que un stack caído te devuelve al formulario con el motivo en lugar
de dejarte ante una ventana vacía.

La respuesta se guarda como `server.json` en el directorio de configuración que la
plataforma tiene para la app — `~/Library/Application Support/co.vstorm.agenticos/`
en macOS, `%APPDATA%\\co.vstorm.agenticos\\` en Windows,
`~/.config/co.vstorm.agenticos/` en Linux — y se vuelve a leer en cada arranque.

Un archivo que ya no se puede parsear — una errata al editarlo a mano — se aparta
como `server.json.invalid` en el siguiente arranque, y el formulario de conexión
guarda uno nuevo.

Una dirección equivocada se corrige de cuatro maneras, la que quede más a mano:
**Settings…** (`⌘,`, también en el icono de la bandeja y en el menú contextual de
la mascota, así que se alcanza incluso cuando la ventana muestra el sitio
equivocado), **Shell → Change server…**, editando ese archivo, o arrancando con
`--server http://localhost:3000` desde un terminal, que además la guarda.

## La mascota { #the-pet }

Una pequeña criatura de pixel art en una ventana propia, transparente y siempre
encima: se queda en el escritorio mientras la consola está abierta, minimizada o
cerrada, igual que las mascotas de Codex. Arrástrala a donde quieras; haz clic y
saluda; haz doble clic y da un brinco y trae la consola al frente, reabriéndola si
habías cerrado la ventana. Si la dejas en paz, está a su aire, mira alrededor,
pasea un trecho por la pantalla y da la vuelta al llegar al borde, y de vez en
cuando echa una cabezada.

Pasa el cursor por encima y aparece un botón **+ New chat** sobre su cabeza; pone
la consola en una conversación nueva y abre la ventana si estaba cerrada. Haz clic
y dice algo, en un bocadillo, con voz propia. Acaríciala — el cursor adelante y
atrás sobre ella unas cuantas veces — y cierra los ojos y sube un corazón.
Mientras está ahí parada, sus ojos siguen al cursor. Al caer la noche echa una
cabezada donde habría paseado. Soltada tras un arrastre, aterriza con un pequeño
brinco.

Haz clic derecho en la mascota para su menú: un chat nuevo, la consola, qué
mascota es y si se muestra. El mismo menú está en el icono de la bandeja (el extra
de la barra de menús en macOS) y bajo **Pet** en la barra de menús, y los tres son
un único conjunto de entradas, así que una marca cambiada en uno queda cambiada en
los otros.

**Show pet** (Cmd/Ctrl+Shift+P) la esconde y la trae de vuelta; el mismo menú
elige qué mascota es — Orbit, una redonda con antena; Boxy, un terminal con patas;
Ghost, que flota; Sprout, una semilla con una hoja; Amigo, con sombrero y bigote,
para no more caramba in your AI. Dónde se quedó, si se muestra y qué mascota es se
guardan junto a la dirección del servidor, así que en el siguiente arranque la
mascota está donde la pusiste. Con el ajuste de reducción de movimiento del
sistema operativo se queda quieta, y se sigue pudiendo arrastrar.

El dibujo se compone al vuelo en `desktop/ui/pet-sprites.js`: cada mascota es un
cuerpo y una descripción de dónde van ojos, pies y brazo, y cada animación son
unas líneas de posiciones compartidas por las cinco, no un sprite sheet por
mascota. Lo que dice cada una está en `pet-lines.js`; el comportamiento, y cada
regla sobre cuándo cuenta una caricia o adónde miran los ojos, está en
`pet-engine.js`, puro y con tests. Su ventana propia es lo que la hace mascota y
no widget, y lo que cuesta: `macOSPrivateApi` en `tauri.conf.json`, porque una
ventana transparente en macOS lo exige, lo que descarta la Mac App Store — no era
sitio para una consola autoalojada.

!!! note "Todavía no sabe qué están haciendo los agents"

    La mascota de Codex lleva un bocadillo que dice que hay un run en curso o una
    aprobación esperando. La nuestra aún no puede: la consola es una página remota
    sin IPC hacia el envoltorio, y dárselo significa una capability con URLs
    `remote` más un hook en el frontend que informe de la actividad. Eso es lo que
    viene después; la mascota de aquí es compañía, no un piloto de estado.

## Captura de pantalla a un chat nuevo { #screenshot-to-a-new-chat }

Pulsa el atajo — `⌘⇧A` por defecto, estés donde estés — y aparece la cruceta de
Cmd+Shift+4. Elige una región y la consola viene al frente en un chat nuevo con la
imagen ya adjunta, lista para la pregunta. Escape cancela. La misma acción está en
el menú de la mascota y en el icono de la bandeja.

**Settings…** (`⌘,`, bajo Shell, en el icono de la bandeja y en el menú contextual
de la mascota) lo reasigna: haz clic en el campo, mantén los modificadores y pulsa
una tecla. Una combinación necesita al menos un modificador — un atajo global
sobre una letra a secas se tragaría lo que escribes en cualquier aplicación — y
una que ya tenga otra aplicación se rechaza conservando la asignación anterior.
**Clear** lo apaga. Las asignaciones se guardan junto a la dirección del servidor.
Una asignación que no se pudo tomar al arrancar, porque otra aplicación llegó
antes, se nombra en esa misma página para sustituirla, en vez de que se quede ahí
aparentando estar asignada.

!!! note "Dos modificadores por sí solos no pueden ser un atajo"

    Command izquierda más Command derecha es un acorde, no una tecla: el registro
    de hotkeys del sistema operativo, que es lo que usa el envoltorio, necesita en
    la combinación una tecla que no sea modificador. Detectar un acorde de solo
    modificadores significa un event tap de accesibilidad que vigila cada
    pulsación, y pedirle a cada usuario que lo conceda. No en esta versión.

La primera pulsación pregunta a macOS si AgenticOS puede grabar la pantalla.
Mientras no pueda, no se captura nada — la herramienta del propio sistema termina
en silencio sin cruceta —, así que el envoltorio comprueba primero, abre System
Settings → Privacy & Security → Screen Recording, y la mascota dice "Allow screen
recording, then restart me." El permiso va a la aplicación *responsable*: el
bundle de AgenticOS una vez empaquetado, pero bajo `make desktop-dev` el terminal
desde el que se lanzó el binario, o el IDE que lo alberga — que es el que hay que
marcar en esa lista. Un permiso surte efecto tras reiniciar.

La imagen llega al compositor igual que un archivo elegido: el envoltorio ejecuta
un script en la página de la consola que entrega el PNG al campo de archivo del
compositor, así que la subida, el límite de tamaño y la vista previa son los de la
propia consola. Solo se entrega a la página de chat en el origin del servidor
configurado — nunca a otro sitio al que la ventana haya podido ir a parar — y solo
dentro de los dos minutos siguientes a la pulsación; una captura que no llegó a
ninguna parte se descarta. En Windows y Linux todavía no hay captura cableada.

## Lo que a propósito no hace { #what-it-deliberately-does-not-do }

- **Nada de ejecución local.** El envoltorio no tiene acceso a la máquina más allá
  de un único archivo JSON. Un agent que ejecuta comandos en el portátil desde el
  que se abre es otra funcionalidad con otro modelo de permisos — un tercer tipo
  de conexión de sandbox junto a Docker y Daytona, ligado a la máquina de una
  persona en lugar de a la organización — y no es esta.
- **Nada de modo sin conexión.** Con el servidor inalcanzable, la ventana muestra
  la página de error del propio webview; "Shell → Reload" reintenta.
- **Nada de guardia de navegación.** Un enlace que sale del origin del servidor se
  abre dentro de la ventana en lugar de en el navegador del sistema, porque un
  flujo OAuth — iniciar sesión, conectar un servidor MCP — sale del origin y tiene
  que volver al mismo webview para que su cookie aterrice. Mientras la ventana
  muestra cualquier otro sitio, su título nombra ese host — la única pieza de la
  interfaz del navegador que una página no puede dibujar, ya que no hay barra de
  direcciones — y `⌘,` o "Shell → Change server…" es el camino de vuelta si una
  página no tiene enlace a casa. Llevar esos flujos al navegador del sistema es
  [#1532](https://github.com/vstorm-co/agenticos/issues/1532).
- **El inicio de sesión se queda en la ventana, y la ventana dice que es Safari.**
  El user agent desnudo de WebKit es lo que Google rechaza como navegador
  incrustado (`disallowed_useragent`); la ventana de la consola lleva los tokens
  de versión de Safari sobre el mismo motor, así que el inicio de sesión con
  Google funciona. El traspaso que Google prefiere — el navegador del sistema y un
  deep link de vuelta — necesita un intercambio de un solo uso que el backend
  todavía no tiene, y es
  [#1532](https://github.com/vstorm-co/agenticos/issues/1532).

## Dónde queda en el árbol { #where-it-sits-in-the-tree }

`desktop/ui/` es el formulario de conexión y la mascota, archivos estáticos sin
paso de build; `bun test` ejecuta ahí los tests de sprites y de comportamiento de
la mascota. `desktop/src-tauri/` es la parte de Rust: los comandos que llaman las
dos páginas, las dos ventanas y el menú. `desktop-check` no forma parte de
`make lint` ni de `make check`: CI todavía no tiene un toolchain de Rust, y
`tests/test_ci_parity.py` rechazaría un `check` que ejecutase un paso que CI no
ejecuta. Ejecútalo antes de pushear un cambio bajo `desktop/`.

## Resumen { #recap }

- **La consola se queda en el servidor.** El envoltorio la abre; no se empaqueta
  nada.
- **Un archivo de ajustes.** La dirección del servidor, preguntada una vez, y
  dónde se dejó la mascota, ambas cambiables desde el menú.
- **Una captura está a un atajo de distancia.** `⌘⇧A`, una región, un chat nuevo
  con ella adjunta; se reasigna en Settings (`⌘,`).
- **Nada local todavía.** La ejecución local es un tipo de conexión de sandbox por
  diseñar, no un interruptor de este envoltorio.
