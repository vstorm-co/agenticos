---
source_sha: "2cdd1d63b902"
---

# La app del móvil { #the-phone-app }

La consola funciona en el navegador de un móvil y se puede añadir a la pantalla de
inicio como app. La app de AgenticOS para iOS y Android añade lo que solo una app
puede hacer: la pantalla de bloqueo, la Dynamic Island, widgets, la hoja de
Compartir, push con la app cerrada y un bloqueo propio. Como la
[app de escritorio](desktop.md), es un shell alrededor de la consola del propio
despliegue, así que el inicio de sesión, los permisos y las comprobaciones de
tenant son los de la consola.

> **Captura pendiente — la app del móvil, una live activity y los widgets.**

Es una app de [Tauri](https://tauri.app) en `mobile/`, con las mitades nativas -
Swift para iOS, Kotlin para Android - en `mobile/src-tauri/`.

## Iniciar sesión { #signing-in }

**Ajustes → App móvil** en la consola muestra un código QR; al escanearlo con la
app, esta inicia sesión como tú. Un código sirve una vez, durante un minuto, y la
sesión del móvil se abre solo al escanearlo, con el nombre del propio móvil.
También funciona escribir la dirección del servidor e iniciar sesión. La sesión
sobrevive a los reinicios, y la app se bloquea tras Face ID, Touch ID o la huella
después de cinco minutos fuera.

**Sesiones activas**, en Ajustes → Perfil, lista cada dispositivo con sesión
iniciada: «AgenticOS for iOS 0.2.0» para la app, el navegador en otro caso, y
cuáles reciben push. Revocar una allí cierra la sesión de esa app al instante.

## Push { #push }

| Dónde | A través de | Se activa en |
|---|---|---|
| iPhone | El servicio push de Apple, con la clave APNs propia de la organización (Admin → Ajustes) | Ajustes de la app → Notificaciones |
| Android | ntfy (ntfy.sh o un servidor propio de la empresa), no Google | Ajustes de la app → Notificaciones, con la app ntfy instalada |
| Un navegador, o la consola añadida a la pantalla de inicio | Web Push, con la clave propia del despliegue | Ajustes → Notificaciones |

Las notificaciones de cada evento - correo, push - se eligen por evento en Ajustes
→ Notificaciones. Una notificación abre su página a través del bloqueo de la app.

El push registrado por un inicio de sesión se detiene cuando la sesión se revoca o caduca. Un token vinculado solo recibe mensajes si su sesión pertenece al mismo usuario. Las suscripciones antiguas sin sesión registrada conservan su permiso; elimínalas y regístralas de nuevo para vincularlas al dispositivo actual.

## Fuera de la app { #outside-the-app }

Las **live activities** - la pantalla de bloqueo y la Dynamic Island en iOS, una
notificación permanente en Android - muestran lo que está en marcha para ti:

- tus runs en curso, con un reloj;
- una aprobación que te espera, con Reject y Approve;
- una pregunta cuya respuesta espera un agent, que abre su conversación;
- una llamada de voz en curso, con su reloj, que avisa cuando el agent pregunta
  algo.

Una decisión tomada desde la pantalla de bloqueo espera a Face ID o a la huella y
luego va por la misma petición que los botones de la cola.

**Widgets.** El widget de resumen cuenta las aprobaciones que te esperan y tus runs
en curso, con la hora del recuento, y la parte del budget mensual de la
organización que queda cuando tiene un límite. El widget de agents fijados abre un
chat nuevo con un agent que fijaste en su página; en Android, fijarlo también pone
un acceso directo en el launcher con la cara del agent. Las cifras son de la
consola y se renuevan cada vez que las lee.

**Atajos.** El menú de pulsación larga del icono, Atajos y Siri, el botón de
Acción y el Centro de control en iOS, y un mosaico de Ajustes rápidos en Android
inician una llamada de voz, un dictado, un chat nuevo o las aprobaciones.

**Compartir con AgenticOS.** La hoja de Compartir de cualquier app ofrece
AgenticOS: texto, enlaces, fotos y archivos (hasta 20 MB cada uno) llegan a un
mensaje nuevo. Con la app bloqueada no se adjunta nada.

## Dentro de la app { #in-the-app }

- **Un chat como una app de mensajería.** El `+` del campo de mensaje abre Cámara,
  Fotos y Archivos, luego la entrada de voz y los comandos, la llamada, el modelo y
  las aprobaciones. Al abrir el chat se ofrece una foto hecha hace un momento; solo
  llegan al mensaje las fotos que tocas.
- **Gestos.** Desliza una aprobación pendiente a la derecha para aprobarla o a la
  izquierda para rechazarla, y tira de una página hacia abajo para volver a leerla,
  con una vibración cuando soltar va a actuar.
- **Las páginas se mueven como las del móvil.** Una página abierta entra desde el
  borde final y una a la que se vuelve, desde el inicial. Reducir el movimiento lo
  desactiva.

## Sin red { #without-a-network }

La app del móvil, la app de escritorio y la consola añadida a la pantalla de inicio
guardan una copia en el dispositivo durante siete días: la lista de conversaciones,
las veinte conversaciones abiertas por última vez con sus archivos más nuevos, la
cola de aprobaciones y el gasto, los fallos y las conversaciones por retomar del
dashboard. La copia está sellada con una clave que ningún script puede leer y se
borra al cerrar sesión o al cambiar de organización; una pestaña normal del
navegador no guarda nada.

Sin red, la consola muestra esa copia bajo un aviso que dice cuándo se guardó. Un
mensaje escrito sin conexión espera sobre el campo de mensaje, sobrevive a cerrar
la app y se envía cuando vuelve la conexión; uno que el servidor rechaza vuelve
marcado «No enviado» con el motivo.

## Instalar la consola en su lugar { #installing-the-console-instead }

En un navegador que puede instalarla, una franja bajo la cabecera de la consola lo
ofrece: ventana propia, push y un icono en la pantalla de inicio, sin los extras
nativos de arriba. En un iPhone explica cómo - Compartir y luego Añadir a pantalla
de inicio. Si se descarta una vez, no vuelve en ese navegador.

## Gestión de dispositivos { #device-management }

Una organización puede fijar el servidor al que se conecta la app, bloquearlo para
que nadie apunte la app a otro sitio y forzar el bloqueo biométrico activado o
desactivado - las claves `serverUrl`, `serverLocked` y `biometricLock` (`person` |
`on` | `off`) en las configuraciones gestionadas de Android y la configuración de
app gestionada de iOS (AppConfig). Una política que no se puede leer se ignora en
lugar de dejar a alguien fuera.

## Dónde está en el árbol { #where-it-sits-in-the-tree }

- `mobile/src-tauri/src/` - los plugins de Rust que llama la consola: live
  activities (`live.rs`), widgets (`widget.rs`), fijados, compartir, push y
  configuración gestionada.
- `mobile/src-tauri/ios/Sources/AgenticOSNative/` - los plugins de iOS y los tipos
  que la extensión de widgets comparte con la app.
- `mobile/src-tauri/gen/apple/Widgets/` - los widgets, los controles y la live
  activity.
- `mobile/src-tauri/gen/android/` - el proyecto de Android: los plugins, los
  widgets y sus diseños.
- `frontend/src/components/mobile/` - la mitad de la consola: lo que está en
  marcha, las cifras del widget, las acciones que devuelve la app.

## Resumen { #recap }

- **La consola se queda en el servidor.** La app la abre y añade las superficies
  propias del móvil.
- **En vivo fuera de la app**: runs, aprobaciones, preguntas y llamadas en la
  pantalla de bloqueo; cifras, budget y agents fijados en los widgets.
- **Push sin Google** en Android, con la clave propia de la organización en el
  iPhone.
- **Una copia en el dispositivo**, sellada, para cuando no hay red.
