---
source_sha: e5e660ee22ce
---

# El despliegue en sí { #the-deployment-itself }

La mayor parte de este producto trata sobre agents. Esta página trata sobre
aquello dentro de lo que se ejecutan.

**Una instalación, con un nombre, una marca, una regla sobre quién puede unirse y
un interruptor que la cierra.** Todo ello vive en una única fila de la base de
datos y se edita desde `/admin/settings` por quien tenga `is_app_admin`: sin
redespliegue, sin variable de entorno, sin reconstrucción.

!!! info "Por qué esa autoridad y no un permiso"

    Un permiso está acotado a una organización. Esta fila no está en ninguna.

    Es la misma autoridad que ya administra usuarios y tenants en toda la
    instalación.

## Identidad { #identity }

| Campo | Dónde aparece |
|---|---|
| Name | La barra lateral, la cabecera de inicio de sesión, la pestaña del navegador, la tarjeta OpenGraph y cada correo que envía este despliegue |
| Tagline | Junto al nombre en el título de la pestaña y en un enlace compartido |
| Description | La descripción de la página y las vistas previas de enlaces |
| Logo | Dondequiera que aparezca el nombre: el enlace de marca, la cabecera de inicio de sesión, las páginas legales |
| Favicon | La pestaña del navegador |
| Footer text | Debajo del formulario de inicio de sesión |
| Terms URL, Privacy URL | Cada enlace que si no ofrecería las páginas `/legal/*` integradas |

!!! note "Una columna nula significa *lo integrado*, no *vacío*"

    Un operador que borra un campo pide que vuelva el valor por defecto, no una
    cabecera de inicio de sesión sin nombre. La API responde *overrides* y cada
    renderizador resuelve un nulo contra su propio valor integrado.

Un operador que nunca ha abierto la página no tiene fila alguna. La consola
resuelve un nulo contra `APP_NAME` y `SITE` en `frontend/src/lib/`; el backend lo
resuelve contra `settings.PROJECT_NAME` para el correo que envía él mismo.

Dos constantes para un mismo nombre de producto pueden divergir, así que
`backend/tests/test_deployment_settings.py` las fija iguales. Lee el
`constants.ts` del frontend y lo compara con el valor por defecto de clase de
`Settings.PROJECT_NAME`: el mismo trato que `TestFrontendToolCatalog` hace con el
catálogo de tools.

### Las dos imágenes { #the-two-images }

Se suben mediante `POST /api/v1/admin/settings/{logo,favicon}` y se guardan como
cualquier otra imagen de esta plataforma: los bytes van al almacenamiento de
archivos configurado y la clave va a una columna. **La clave nunca se toma del
cuerpo de una petición** —quien pudiera nombrarla podría apuntar el logo público
de este despliegue a lo que sea que guarde el backend de almacenamiento— y el
nombre de archivo almacenado se acuña a partir del tipo de contenido validado y
no del nombre de la subida, porque estos archivos se sirven desde el mismo origen
en el que corren las páginas de la app y ahí `logo.html` es un script.

JPEG, PNG, WebP y GIF, hasta 2MB, que es la única definición de «una imagen que
esta plataforma acepta».

!!! danger "SVG está deliberadamente ausente"

    Es un documento que puede llevar script, y estos archivos se sirven desde el
    mismo origen en el que corren las páginas de la app. ICO no aporta nada que
    un favicon PNG no dé.

La respuesta de branding lleva una **versión**, no una URL. La dirección es
constante (`GET /api/v1/branding/{logo,favicon}`) y los bytes se sirven como
`immutable` durante un año, así que lo que un cliente necesita de la fila es si
existe una imagen y cuándo cambió por última vez; el `?v=` construido a partir de
eso es la única razón por la que aparece un reemplazo. Una URL sería además algo
que cada cliente tendría que reescribir, porque en cualquier despliegue real la
API no está en el mismo origen que las páginas.

## Cabeceras de seguridad { #security-headers }

Cada página de la consola lleva una Content-Security-Policy y las cabeceras de
endurecimiento habituales, definidas en `frontend/src/lib/csp.ts` y
`frontend/src/lib/security-headers.ts`, ambas verificadas por tests. La política
es `default-src 'self'` con un `connect-src` que nombra exactamente este origen,
`PUBLIC_API_URL` y `PUBLIC_WS_URL`, un `img-src` que permite `data:` para los
glifos de marca y los avatares, `frame-src 'self' blob:` para las vistas previas
de documentos, `object-src 'none'`, `base-uri 'self'` y `frame-ancestors 'none'`.

La política se estampa por petición desde el middleware del frontend, porque las
dos URLs públicas se leen del entorno del servidor en tiempo de ejecución y una
cabecera fijada en el build solo podría nombrar `localhost`. Las demás cabeceras
son constantes y las fija la configuración de Next. Cambia las URLs públicas y la
política las sigue en la siguiente petición; no se reconstruye nada.

Junto a ella están `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin` y una `Permissions-Policy` que
deniega la cámara y la geolocalización y permite el micrófono solo en este
origen, para el dictado por voz del chat.

!!! warning "Un proxy inverso no debe añadir sus propias copias de estas"

    Nginx, Traefik o un ALB delante de la app las pasan sin cambios en lugar de
    fijar las suyas. Dos cabeceras `Content-Security-Policy` en una misma
    respuesta las combina el navegador en su intersección, así que un proxy que
    añade una segunda —incluso una más laxa— solo endurece la política hasta
    convertirla en algo que bloquea un panel que nadie quería bloquear; y con un
    segundo `X-Frame-Options` el navegador se queda con cualquiera de los dos
    valores. El `nginx/nginx.conf` incluido fija únicamente
    `Strict-Transport-Security`, que pertenece a lo que termine TLS; una
    configuración de proxy ya existente que añada las demás debería quitarlas.

## Quién puede registrarse { #who-may-register }

`signup_mode`, aplicado en `app/services/signup_policy.py` —el único lugar— y
controla **ambos** caminos que acuñan una cuenta.

| Modo | Efecto |
|---|---|
| `open` | Cualquiera puede registrarse. El valor por defecto, y lo que era todo despliegue antes de esta funcionalidad. |
| `invite_only` | Solo una dirección que alguna organización haya invitado de verdad. |
| `closed` | Nadie se registra, por ninguna vía: una invitación no lo anula. |

En los tres, un `allowed_email_domains` no vacío restringe quién puede
registrarse siquiera. **Una invitación anula esa lista**: alguien con
`members:invite` nombró la dirección a propósito, y una lista de dominios es
política del despliegue frente a desconocidos, no un veto sobre un acto
deliberado. A `closed` no lo anula nada, porque un «cerrado» que deja pasar
algunos registros no está cerrado.

**`closed` significa cerrado, y no hay ningún camino en el que un administrador
cree una cuenta.** Deliberadamente: una cuenta necesita una contraseña elegida
por su dueño, así que añadir a alguien significa abrirle el registro *a esa
persona*, que es para lo que está `invite_only`. Un modo que permitiera a un
administrador acuñar cuentas sería un tercer camino que acuña una, y los dos que
ya existen son toda la razón por la que `signup_policy` es un módulo y no una
comprobación dentro de `register`. Así que un despliegue que tiene que admitir a
una persona más cambia a `invite_only` y la invita.

Tres cosas más sobre esto que es fácil equivocar, y que se equivocaron:

**El primer usuario siempre se admite.** Una instalación recién hecha no tiene
cuentas, así que su administrador todavía no existe; un despliegue cerrado que
además rechaza a la persona que lo abriría es uno en el que nadie puede entrar,
sin consola desde la que arreglarlo. `register` ya promueve esa primera cuenta a
`is_app_admin`, y la política se remite al mismo hecho.

**`invite_only` existe porque cerrar el registro rompería si no las
invitaciones.** `InvitationService.accept` exige un usuario ya autenticado, así
que una persona invitada tiene que registrarse primero. La política pregunta a
`invitation_repo.first_pending_admitting`, que es cross-tenant por construcción:
el registro ocurre antes de que se elija una organización. Lo que mantiene eso
seguro es adónde va la respuesta: la política la convierte en un rechazo
booleano, así que un desconocido que sondee el formulario de registro aprende que
alguien invitó a esa dirección y nunca qué organización lo hizo.

**Cómo se reconoce una invitación depende de si el registro lleva su token**, y
las dos respuestas cubren formas distintas:

| Llega con | Reconocida por | Qué formas admite |
|---|---|---|
| Un token (resuelto desde la invitación preparada, nunca en el cuerpo del registro) | `invitation_admission.admits` | Cualquier invitación viva que admita la dirección, incluido un enlace que no restringe **ninguna** dirección, que es la forma que nada más puede ver |
| Sin token | `invitation_repo.first_pending_admitting` | Una invitación por correo para esa dirección, o un enlace acotado a su dominio |

El token es la única prueba disponible para un enlace compartible que no lleva ni
dirección ni dominio. Una consulta sobre la dirección enviada no puede
reconocerlo, así que honrarlo *sin* prueba de posesión convertiría un único
enlace abierto en cualquier parte del despliegue en registro abierto para todo
internet. Tener el token es esa prueba.

Un token que no nombra nada vivo cae a la pregunta por la dirección en lugar de
rechazar: un enlace caducado guardado en marcadores no debería convertir un
registro que por lo demás estaría permitido en un error sobre algo que la persona
no puede arreglar.

**Registrarse con un token no acepta la invitación.** Admite la cuenta y nada
más; unirse a la organización sigue siendo `InvitationService.accept`, que el
cliente llama cuando ya tiene sesión. Un token en el cuerpo de un registro no
autenticado que además concediera membresía sería una concesión de membresía en
una ruta pública.

La consola nunca lleva el token a través del rodeo por el inicio de sesión. Un
invitado sin cuenta abre `/invitations/<token>`; `AuthGuard` canjea el token en
el servidor por un identificador opaco que guarda en una cookie `httpOnly` que el
navegador no puede leer, y lo envía a
`/login?returnTo=/invitations/pending?flow=…`: un destino sin credencial, así que
el token no está ni en el `returnTo`, ni en el historial del navegador, ni en el
almacenamiento de sesión. Si el canje falla —servidor inalcanzable, un rate
limit—, el guard se queda en el enlace de invitación y ofrece reintentar en lugar
de marcharse sin nada preparado, porque el enlace es la única credencial del
invitado.

El `flow` es un id aleatorio que el canje acuña por cada preparación, y la cookie
lleva su nombre. No es una credencial: sin la cookie no nombra nada. Está ahí
porque un único nombre fijo de cookie es una sola ranura: dos enlaces de
invitación abiertos en paralelo sin sesión se pisaban el uno al otro, y las dos
pestañas pendientes canjeaban luego el segundo. Ahora cada pestaña canjea
exactamente la cookie que nombra su propio flow.

«Create an account» continúa desde ese destino sin credencial, y el proxy de
registro reenvía como cabecera el handle preparado del flow nombrado, así que la
admisión del registro sigue teniendo el token que necesita sin que este pise
nunca una URL ni el cuerpo. Tras iniciar sesión, la página pendiente canjea el
handle y acepta: la misma forma que el intercambio del código OAuth, un sustituto
opaco, de un solo uso y caducable, para que la credencial nunca viaje por URL.
La cookie se borra tras ejecutarse el canje; un 401, un 429 o un fallo del
servidor la dejan, porque el handle puede seguir sin gastar y un reintento lo
necesita.

**Un enlace con `max_uses` limita cuentas, no solo adhesiones.**

`used_count` cuenta aceptaciones, y aceptar necesita una sesión, así que un techo
leído solo de ahí no limitaba nada de lo que hacía un registro. Un enlace de un
solo uso publicado en un canal admitía tantas cuentas como alguien quisiera
crear, en el despliegue que acababa de cerrar el registro.

Así que un uso se **reserva** primero para la dirección que se registra:
`reserved_emails` en la fila, y `used_count + reserved_emails` es lo que
significa «gastado». La reserva es un único `UPDATE` condicional, porque dos
registros compitiendo por el último uso leerían si no el mismo recuento.

Aceptar saca la dirección de la lista mientras incrementa el recuento, lo que lo
conserva: quien se registró con un enlace de un solo uso todavía puede unirse.

Una reserva que nadie acepta sigue gastada (`max_uses` es a cuántas personas
admite un enlace, y una cuenta creada con él fue admitida) y muere con la
invitación.

**Iniciar sesión con un provider también lleva la invitación, como su handle.**
El login del provider empieza en el mismo origen, en
`/api/oauth/<provider>/login`, para que el handle `httpOnly` preparado pueda
adjuntarse al salto cross-origin que el navegador hace a continuación:
`/oauth/google/login?invitation_handle=…`, que el backend resuelve al token que
guarda en la sesión durante todo el viaje de ida y vuelta. El token nunca está en
esa URL. Sin esto, `invite_only` rechazaba el botón de Google precisamente para
los enlaces que necesitan un token —uno que no restringe ni dirección ni
dominio— mientras el formulario de contraseña de al lado aceptaba a la misma
persona.

**Iniciar sesión con un provider también es un registro.**
`get_or_create_oauth_user` es el segundo camino que crea una cuenta, y nada en un
callback de Google parece un registro, así que un despliegue con `closed` y un
botón de Google estaba de par en par hasta que se controlaron los dos. A quien
*ya* tiene una cuenta no se le vuelve a controlar: cerrar el registro cierra el
registro, y dejar fuera a un miembro de un despliegue al que pertenece no es lo
que dice el ajuste.

El formulario de registro lee la política del endpoint público de branding y
enuncia la regla **antes** de que nadie escriba nada. Un formulario que acepta
una dirección y luego informa de que «ese dominio de correo no puede registrarse»
es un formulario que miente; quien lo visita no tiene forma de saber que la regla
existe y lee el rechazo como que el producto está roto. Por eso también se
publican los dominios permitidos: no son un secreto, y el despliegue está en el
host de la propia empresa.

## Encontrar un tenant entre todos ellos { #finding-one-tenant-among-all-of-them }

`GET /admin/organizations` es la única superficie que responde a *qué tenants
existen*, y es solo para el app admin por la razón que la hace útil: es
cross-tenant por construcción. Responde con una página de organizaciones, cada
una con su número de miembros y de agents y su owner más antiguo: a quién
preguntar por ella. Todos los campos de owner son nulos a la vez en una
organización cuyo último owner se marchó, un estado que solo el administrador del
despliegue puede arreglar y que por tanto hay que mostrarle.

| Parámetro | |
|---|---|
| `search` | Nombre, slug o la dirección del owner. El término es texto, no un patrón: `100%` encuentra al tenant que se llama así en lugar de a todos |
| `sort_by` | `name`, `slug`, `members`, `agents`, `created_at`. Cualquier otra cosa es un 422 |
| `sort_dir` | `asc` / `desc`, con los más nuevos primero por defecto |
| `kind` | `personal`, `team` o `all`. A cada cuenta se le da una organización personal al registrarse, así que en la mayoría de despliegues son casi toda la lista |
| `skip`, `limit` | Una página del servidor, hasta 100 |

**Todo ello ocurre en SQL, antes de `OFFSET`/`LIMIT`**, y `total` cuenta aquello
a lo que se acotó, no el despliegue entero. Esa es la diferencia entre ordenar y
aparentarlo: una página ordenada después de llegar afirma un orden sobre toda la
colección que cincuenta filas no pueden dar, y por eso la lista de tenants del
administrador no llevaba ningún control mientras la ruta no respondía a ninguno
(#921). El orden desempata por el id, así que paginar una columna donde las filas
comparten valor lista cada una de ellas una sola vez.

Una columna fuera del conjunto se rechaza por su nombre en lugar de compararse
contra nada, por las dos razones por las que `GET /runs` rechaza una: una página
vacía se lee como *este despliegue no tiene tenants*, y un `ORDER BY` ensamblado
a partir de una query string es una superficie de inyección.

## Un app admin no puede dejar al despliegue sin acceso desde la consola { #an-app-admin-cannot-lock-the-deployment-out-through-the-console }

!!! warning "El bloqueo autoinfligido que esto evita"

    En la instalación de un solo administrador que produce
    `make platform-bootstrap`, un clic despistado en tu propia fila terminaba con
    la administración hasta que alguien llegara a un terminal. La recuperación es
    `agenticos cmd create-app-admin <email>` desde una shell: el correo es un
    argumento obligatorio.

`is_active` se aplica en la siguiente petición y `is_app_admin` es lo que leen las
páginas de administración, así que un app admin actuando sobre **su propia** fila
desde `/admin/users` podía cerrarse la sesión, perder `/admin` o borrar la
cuenta. `UserService.admin_update` y `admin_delete` rechazan la autosuspensión y
el autoborrado, y el panel no ofrece Suspend, Demote ni Impersonate en tu propia
fila (Delete se queda, visible y rechazado, porque «por qué no puedo borrarme»
tiene una respuesta que vale la pena enseñar). La API también rechaza actuar como
uno mismo: nadie actuando como nadie no es una impersonación.

El despliegue no puede quedarse sin ningún app admin a través de la API: el único
privilegio global se concede solo por CLI (`agenticos cmd create-app-admin`) y no
hay petición que lo quite, así que el conjunto de app admins solo mengua por
borrado, y borrar al *último* es borrarte a ti, lo cual se rechaza. Quitar a un
administrador que se marcha de verdad es la acción de otro administrador, que es
también lo que mantiene legible el rastro de auditoría. La recuperación, si
alguna vez hace falta, sigue siendo `create-app-admin` desde una shell en el
despliegue.

Ese argumento va sobre el *conjunto*, y durante un tiempo el código iba sobre una
fila.

Dos administradores borrándose el uno al otro no estaban borrándose a sí mismos.
Bloquearon filas objetivo distintas, nunca compitieron y ambos hicieron commit:
cero app admins, recuperable solo escribiendo en la base de datos (#1208).

Así que el borrado de un administrador toma `SELECT ... FOR UPDATE` sobre el
conjunto de app admins, ordenado por id, antes de decidir. La segunda petición
espera, vuelve a leer el conjunto una vez que la primera ha hecho commit, y se
rechaza por vaciarlo.

Ordenado, porque dos peticiones tomando las mismas filas en distinto orden son un
deadlock y no una cola. Y tomado en cada borrado de usuario y no solo en el de un
administrador: borrar a un usuario es la acción de un administrador, no una ruta
caliente, y un orden total vale más que la contención que cuesta.

## Actuar como otra cuenta { #acting-as-another-account }

**Impersonate** en `/admin/users` empieza a actuar como esa persona desde tu
propio navegador. No se copia nada a ninguna parte: la consola cambia la cookie
de acceso de la sesión por una que nombra al objetivo, cada página se renderiza
como esa persona la vería, y una franja en la parte superior dice de quién es
esta cuenta y quién está actuando de verdad, con el único botón que lo termina.

Una impersonación es una **sesión**, no una credencial suelta. El token nombra una
fila en `sessions` con `impersonator_user_id` puesto, y la API lo rechaza en
cuanto esa fila se termina o ha caducado, o el administrador que hay detrás ya no
es un app admin activo; así que se detiene cuando pulsas **End impersonation**,
cuando la persona cierra sesión en todas partes o cambia su contraseña, cuando se
cumple la hora, o cuando el administrador es suspendido, degradado o borrado, lo
que ocurra primero. No se puede refrescar: la ventana es la del propio access
token, y la hora es el techo, no un arrendamiento renovable.

!!! note "Una conversación de chat abierta termina con ella"

    Una conversación de chat corre sobre un WebSocket que se autentica una vez,
    en el handshake. Ahora vuelve a ejecutar esa comprobación en cada mensaje,
    así que terminar una impersonación —o suspender la cuenta— cierra también un
    chat abierto, en lugar de solo rechazar la siguiente petición HTTP mientras
    el socket sigue respondiendo.

!!! note "La lista de dispositivos de la persona no la muestra"

    Una impersonación es una fila bajo su id que tiene un administrador, no un
    dispositivo desde el que ella inició sesión, así que no está en su lista de
    dispositivos, ni en el recuento de sesiones abiertas del panel, ni en su
    «última vez visto». Si se le dice o no es el ajuste de más abajo, y una fila
    en esa lista lo decidiría por ella.

**Si se avisa a la persona es una política, fijada en esta fila.**
`notify_impersonated_users` está desactivado por defecto; activado, se envía un
correo a la persona una vez, al empezar la impersonación, nombrando al
administrador. El rastro de auditoría registra la impersonación en cualquier caso
—tanto el inicio como el fin, con la sesión a la que pertenecen—, que es lo que
describe [Gobernanza](governance.md#audit).

## Avisos, y cerrar el despliegue { #notices-and-closing-the-deployment }

**El anuncio** es una frase con uno de tres estilos, mostrada encima de cada
página a los usuarios con sesión hasta que la descartan. Es el único campo de esta
fila que *no* está en el endpoint público: un anuncio es un operador hablando con
la gente que usa el despliegue —una ventana de actualización, a quién escribir—,
así que tiene su propia ruta, `GET /api/v1/branding/notice`, detrás de una
sesión.

El descarte se indexa por el **mensaje mismo**, en el almacenamiento del propio
navegador. Una bandera haría invisible el siguiente anuncio para todos los que
descartaron el anterior; la marca de tiempo de la fila de ajustes desharía el
descarte de un aviso cada vez que se renombrara el despliegue. Lo que cambió es
el texto, así que el texto es la clave. Un almacenamiento que se niega a leerse o
escribirse —un modo privado, un webview embebido— significa «nada descartado» y
no una excepción: lanzada durante el render tiraría el dashboard para todo
usuario con sesión, y la franja se sigue cerrando mientras la página esté
abierta.

**El modo de mantenimiento mantiene cerrada la API**, no solo la consola.
`app/core/maintenance.py` es un middleware ASGI puro por encima de las rutas, así
que una página que alguien ya tuviera abierta deja de funcionar, que es toda la
diferencia entre un modo de mantenimiento y una franja. Su lista de permitidos es
corta y se prueba entrada por entrada:

- `/health*` — una sonda de disponibilidad que falla durante una ventana es un
  orquestador reiniciando el contenedor en el que el operador está trabajando.
- `/api/v1/branding` — la página cerrada tiene que poder decir cómo se llama este
  despliegue y por qué está cerrado.
- `/api/v1/auth/*` — un administrador tiene que poder iniciar sesión **mientras**
  la ventana está abierta.
- `/api/v1/admin/*` — y llegar entonces al interruptor.
- La documentación y el esquema OpenAPI, que no sirven datos.

Todo lo demás es un 503 con `Retry-After`. No lee ninguna sesión —eso significaría
verificar un token por encima del grafo de dependencias—, así que ampliar la ruta
a `/api/v1/admin/*` no amplía la autoridad: `CurrentAppAdmin` rechaza allí a quien
no sea administrador exactamente igual que siempre.

**Falla abriendo.** Una puerta que no puede leer su propio interruptor —un
parpadeo de Redis, una migración que no se ha ejecutado— deja pasar el tráfico,
porque la alternativa convierte un hipo de infraestructura en una caída total que
nadie programó.

El veredicto se cachea en el Redis que todo worker ya comparte: escrito **después
del commit**, para que el interruptor sea inmediato y la caché nunca pueda
anunciar un estado que la base de datos revirtió; publicado de forma anticipada,
una petición que luego fallaba dejaba una ventana desactivada reabriendo el
despliegue durante hasta el TTL. Lleva además un TTL de 30 segundos, así que una
escritura que nunca llegó a Redis se cura sola en lugar de dejar el despliegue
abierto durante una ventana que alguien programó.

**Y una página ya abierta se entera.** El contexto de branding lo resuelve una
sola vez el layout raíz del servidor y no cambia en toda la vida de una página,
así que una ventana abierta después dejaba cada pestaña abierta en un dashboard
cuyas peticiones habían empezado todas a responder 503, sin nada en pantalla que
dijera por qué; y cerrarla dejaba una pestaña en la pantalla de mantenimiento
hasta que alguien recargaba. `GET /api/v1/branding/notice` lleva el veredicto de
mantenimiento junto al anuncio y se consulta una vez por minuto, que es una
petición para las dos respuestas en lugar de dos que pueden discrepar sobre una
misma fila.

En la consola, el administrador ve una franja en lugar de la página cerrada. Es
la única persona que puede terminar la ventana, y un modo de mantenimiento que
además esconde el interruptor es una caída.

## Cuánto puede ocupar una sola cuenta { #how-much-one-account-may-take-up }

Dos techos, ambos en la misma fila y ambos **nulos por defecto, y nulo significa
sin límite en lugar de «sin configurar»**. Un despliegue autoalojado para una
sola empresa no quiere ninguno; un despliegue abierto a registros quiere los dos,
porque si no una cuenta puede acuñar tenants sin límite.

| Ajuste | Cuenta | No cuenta |
|---|---|---|
| Organizations per account | Las organizaciones que una cuenta **posee**, la personal incluida | Aquellas a las que otro la invitó |
| Agents per organization | Los agents que tiene la organización | Los agents archivados |

**Cada transición hacia el estado contado se comprueba, no solo una creación.** Un
techo aplicado solo a filas nuevas es uno que se esquiva de lado: una organización
en su límite de agents archiva uno, crea un reemplazo y restaura el que archivó, y
a una cuenta en su límite de organizaciones se le entrega la de otro mediante
`transfer_ownership`. Así que `unarchive` y `transfer_ownership` hacen la misma
pregunta que `create`.

**Y el recuento se toma bajo un lock.** Leer `count(...) >= limit` y luego
escribir son dos sentencias, así que dos peticiones pasan ambas el recuento y
ambas insertan: el techo superado de forma determinista, con dos clics. Ninguna
restricción puede expresar «como mucho N filas así», por lo que `app/db/locks.py`
toma un advisory lock con alcance de transacción sobre el *sujeto* del techo: dos
peticiones sobre una misma cuenta hacen cola, peticiones sobre cuentas distintas
no se encuentran nunca, y el lock lo libera el commit o el rollback. Solo donde
hay un límite fijado, así que un despliegue sin topes no paga nada.

Ambas exclusiones son el punto del diseño y no un detalle de él. Que te inviten a
diez organizaciones es decisión de otro, y un techo que una persona no puede
controlar es un techo que le impide crear las suyas. Y archivar es como se retira
un agent: un techo que un agent retirado siguiera ocupando dejaría como única
vuelta por debajo de él un borrado, que se lleva por delante el historial de
versiones y la atribución de los runs.

El rechazo nombra el techo y el recuento contra el que se midió
(`{"limit": 5, "held": 5}`), así que «por qué no puedo» lo responde la respuesta y
no la memoria de un administrador. Se lanza en el servicio que crea la cosa, no en
la ruta, porque la ruta no es la única entrada.

El schema rechaza el cero: una cuenta que no puede poseer ninguna organización es
una cuenta que no se puede crear, ya que el registro da a cada una su propia
organización personal.

## La fila { #the-row }

Una sola fila para toda la instalación, custodiada por la base de datos y no por
una convención que nadie ve: `singleton` es único y está restringido a verdadero,
así que una segunda identidad es un `IntegrityError` en lugar de un despliegue que
calladamente tiene dos y sirve aquella que una consulta ordenó primero. La
escritura es un único `INSERT ... ON CONFLICT DO UPDATE`, porque un
leer-luego-insertar compite consigo mismo en cuanto dos administradores guardan
desde dos pestañas.

**No se siembra nada.** Sin fila significa todos los valores por defecto, que es
exactamente el estado de un despliegue que nadie ha configurado; e importa porque
el endpoint público de branding no está autenticado y se alcanza en cada carga de
página en frío, así que una lectura que creara la fila permitiría a un desconocido
provocar un `INSERT`.

Cada escritura se audita en `app_admin_audit_logs`, nombrando los **campos** y
nunca sus valores: un anuncio y una lista de dominios son ambos texto del
operador, y una fila de auditoría sobrevive al cuerpo de la petición del que vino.

## Un rechazo de este despliegue siempre tiene el mismo aspecto { #a-refusal-from-this-deployment-always-looks-the-same }

Vale la pena decirlo aquí porque cerrar un despliegue es la funcionalidad con más
probabilidades de producir uno que una persona no haya visto nunca.
`app/api/exception_handlers.py` pone **cada** rechazo en
`{"error": {"code", "message", "details"}}`:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Agent not found",
    "details": { "agent_id": "…" }
  }
}
```

Eso cubre las excepciones de dominio, la validación de schema y, desde #917,
también `HTTPException`, lo que cubre un 405, una ruta sin coincidencia y las
veintidós rutas que lanzan una directamente. Dos formas en el cable significan que
cada llamante o maneja las dos o maneja mal una en silencio.

Una petición con el método equivocado respondía antes **500** en lugar de 405, en
todas las rutas. La instrumentación de FastAPI de OpenTelemetry deriva el nombre
de un span recorriendo `app.routes`, y su rama `Match.PARTIAL` —que es exactamente
«la ruta coincide y el método no»— lee `.path` sin protección; FastAPI 0.141 pone
objetos `_IncludedRouter` en esa lista y no lo tienen. `app/core/otel_compat.py`
proporciona, para esa rama, el mismo valor de reserva que upstream ya usa en la
rama que sí protegió. Sigue sin arreglarse en upstream a fecha de 0.65b0, y
`tests/test_otel_route_details.py` falla cuando se arregle, que es cuando el
módulo desaparece.

## Resumen { #recap }

- La identidad del despliegue es **una fila**, editada desde `/admin/settings`, y
  una columna nula significa *lo integrado* y no *vacío*.
- `signup_mode` se aplica en **un solo lugar** y controla ambos caminos que acuñan
  una cuenta. Una invitación anula una lista de dominios; nada anula `closed`.
- Un app admin **no puede dejarse a sí mismo sin acceso** desde la consola.
- **La impersonación es una sesión**: iniciada desde la consola sin ningún token
  en el portapapeles, nombrada en una franja, terminada por el administrador, por
  la persona al cerrar sesión en todas partes, o por la hora. Si se avisa a la
  persona es `notify_impersonated_users`, desactivado por defecto.
- Cada rechazo de este despliegue tiene el mismo aspecto, sea cual sea la capa que
  lo produjo.
