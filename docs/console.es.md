---
source_sha: "ff771900ffbf"
---

# La consola { #the-console }

La consola es la aplicación web desde la que se configura todo lo demás de este
sitio. Esta página es el mapa: para qué sirve cada área, y qué página la explica
como es debido.

Si buscas una pantalla concreta, el camino más rápido es el **"?"** de la
cabecera de cada página — reproduce el recorrido guiado de esa página, y una
página cuya cabecera no lleva "?" no tiene recorrido que reproducir.

## El dashboard { #the-dashboard }

La página de inicio es una **cuadrícula de widgets que tú ordenas**, y es la
respuesta a "qué está pasando" sin abrir cinco páginas.

Existen treinta y ocho tarjetas. No las verás todas: **cada tarjeta está
protegida por el permiso que necesitan sus datos**, así que un widget que no
puedes leer nunca se monta y sus consultas nunca se lanzan — excepto tus
propias notificaciones, más abajo, que solo necesitan que hayas iniciado
sesión. Una banda vacía desaparece junto con su título en lugar de quedarse ahí
vacía.

Llegan agrupadas en bandas:

| Banda | Responde a |
|---|---|
| *(sin título, arriba del todo)* | El resumen del que el resto de la página es el detalle |
| **Deployment** | Solo para un [administrador del despliegue](permissions.md) — totales de la plataforma, salud, inquilinos más activos, valoraciones |
| **Attention** | Lo que está esperando: [aprobaciones](governance.md#approvals), fallos recientes, margen de budget, salud de MCP, conocimiento obsoleto, tus [notificaciones](#the-bell) más recientes |
| **Usage** | Runs, resultados, superficies, latencia, gasto, [minutos de voz](#voice-calls), mezcla de modelos, comparación de versiones |
| **People** | Miembros, usuarios activos, valoraciones, quién hace qué |
| **Sandboxes** | [Capacidad, sesiones en curso, política](sandbox.md) |
| **Workspace** | Lo tuyo: tus agents, tus conversaciones, tu actividad, lo que han compartido contigo |

### Reordenarlo { #rearranging-it }

Arrastra una tarjeta, cambia su tamaño, oculta otra. La disposición es **tuya** —
ligada a ti y a la organización en la que estás, no a la organización — así que
cambiarla no cambia la página de nadie más.

Guarda una disposición como **preset** con nombre para tener más de una e ir
alternando. Un nombre repetido se rechaza en lugar de sobrescribir en silencio la
instantánea que querías conservar.

!!! info "La comprobación de permisos corre la última, sobre lo que le llegue"

    Una disposición guardada puede reordenar y ocultar, pero no puede revelar. El
    filtrado por permisos corre después de resolver la disposición, venga esta de
    la de serie o de una que tú guardaste.

## La campana { #the-bell }

Junto al buscador, en la barra lateral: un contador en marcha de lo que aún no
has leído, y un clic abre la lista misma. A diferencia del widget de arriba,
abrirla trae la página completa que estás mirando, no una vista previa de
cinco tarjetas — **Load more** sigue paginando hacia atrás por la organización
en la que estás ahora, más lo dirigido al deployment entero, hasta llegar a lo
que ya ha caducado.

Cambia de organización y la campana es la de esa: una
notificación de la organización que dejaste no ha desaparecido, está detrás del
selector. El administrador del deployment es la única excepción — su campana no
la estrecha la organización en la que esté actuando, porque una audiencia
«admins» lo alcanza sin una membresía por la que acotar.

Una fila con un destino es un enlace; una sin él — el anuncio propio de un
admin, la mayoría de las veces — solo se puede marcar como leída. Marcar una
como leída, o todas a la vez, actualiza el contador al instante; nada aquí
espera a que se recargue la página. **Mark all read** barre por lotes hasta
cinco mil filas no leídas y luego vuelve a pedir el contador — así que con un
atraso mayor la insignia sigue mostrando lo que queda por leer y un clic más
termina el resto, en lugar de anunciar una bandeja que solo trabajó en parte.

Cada clic avanza siempre, incluso cuando todo el lote eran filas que quien lee
ya no puede ver. Nunca las marca: la comprobación es sobre los permisos
*actuales*, así que a quien estuviera degradado una semana y luego restituido le
aparecerían ya leídos los avisos de seguridad de esa semana. En su lugar, un
barrido truncado dice dónde se paró y el siguiente clic arranca desde ahí.

Tanto el contador como el barrido dicen cuándo se han parado en ese límite y no
al final de la bandeja — `approximate` en `GET /notifications/unread-count` y
`remaining` en `POST /notifications/mark-all-read` —, porque si no un contador
justo en el límite y un contador real del mismo tamaño son el mismo número.

Leída no es lo mismo que fuera, y se ofrecen las dos cosas. Pasar el cursor por
una fila revela una cruz que la saca de la lista; **Clear** en la cabecera saca
todo lo que está listado ahora mismo, leído y no leído por igual. Limpiar algo
no leído lo marca además como leído, porque una fila que nada en pantalla puede
alcanzar no debe seguir contando para la insignia. Como «Mark all read», una
limpieza está acotada — mil filas — y un atraso más largo pide un segundo clic.

Lo que una fila limpiada *no* hace es volver. La notificación se conserva y deja
de listarse, en lugar de borrarse, y eso es lo que lo hace cierto: la bandeja
reconoce una repetición por el hecho que describe, así que una fila borrada
sería una que la siguiente comprobación de budget o el siguiente reintento
volverían a escribir. Descartar un aviso del que ya te has ocupado es, por
tanto, definitivo — para esa ocurrencia; uno *nuevo*, sobre un hecho nuevo,
sigue llegando. Las filas también caen solas: noventa días después de
escribirse si fueron leídas, y un año pase lo que pase.

Qué llega aquí y qué se puede desactivar le toca explicarlo a
[Governance](governance.md#alerts) — esta página es solo los dos sitios donde
lo lees: la campana para lo que acaba de pasar, la tarjeta del dashboard para
un puñado de las más recientes, la próxima vez que abras la página.

## Chat { #chat }

Donde hablas con un agent publicado. El selector elige qué agent responde, y el
run se comporta exactamente igual que en Slack o detrás de la API — mismo budget,
misma puerta de aprobación, mismo rastro de auditoría, porque
[todas las superficies pasan por un único runner](channels.md).

Tres cosas del compositor que conviene saber.

**Tus propias cuentas.** Un agent ligado a
[la cuenta de cada persona](mcp.md#whose-account-a-binding-speaks-through) en un
servicio le habla como tú. Los controles del chat enumeran qué servicios del
agent necesitan una cuenta tuya y si cada uno está listo, con un botón de conexión
que abre el consentimiento del provider en una pestaña nueva. Si preguntas antes
de conectar, no aparece nada hasta que el agent necesita de verdad el servicio:
entonces la respuesta se detiene en una tarjeta con ese botón y, en cuanto la
cuenta está conectada, la misma respuesta sigue con él. **Skip** deja que siga
sin él.

**Los adjuntos** se parsean y se entregan solo a esa conversación; no se añaden a
una [colección de conocimiento](file-processing.md). Consulta
[Procesamiento de archivos](file-processing.md#chat-file-uploads).

**Los comandos de barra** se expanden a un prompt antes de enviar el mensaje. Los
de serie vienen con el producto; puedes escribir los tuyos en
**Settings → Slash commands**, y ocultar cualquiera de los de serie que no uses.
Son tuyos, no de la organización.

**Ver un recorrido.** Un agent con
[automatización del navegador](reference/capabilities.md#browser-automation-choose)
abre un panel junto a la transcripción cuando empieza a recorrer una página: la vista
de la página según avanza, la página en la que está y cada paso con la probabilidad
con la que el motor lo eligió. Ese número es la razón de que exista el panel en lugar
de un indicador de carga: un recorrido que actuó sobre una elección de 0,31 merece
una mirada. Se queda cuando el recorrido termina, porque *bloqueado por la página* es
una respuesta sobre la página. Ciérralo y seguirá cerrado para ese recorrido.

### Dictado { #dictation }

El micrófono del compositor convierte la voz en texto en el cuadro y nunca lo
envía: lo que dices aparece donde estaba el cursor cuando pulsaste el micrófono,
listo para editar, y no va a ninguna parte hasta que pulsas Enviar. Cómo se
transcribe lo elige la organización, en [la tarjeta Voice](#the-voice-card):

- **Off** — sin micrófono.
- **Browser** — el reconocimiento de voz del propio navegador, así que el audio va
  al fabricante del navegador (Google, Apple). Firefox no lo tiene: su
  micrófono lo indica al pulsarlo.
- **Server** — el navegador graba, y este despliegue envía la grabación al
  proveedor de speech-to-text de la organización, o al
  [del propio agent](#an-agents-own-engine) cuando este nombra uno. Funciona en
  cualquier navegador que pueda grabar. El endpoint, sus límites y lo que queda
  registrado están en [Dictado en el chat](ml-services.md#dictation-in-chat).

Con **Server**, pulsar el micrófono sustituye los controles por una barra de
grabación: Cancelar, el nivel, un temporizador y Detener. **Enter** detiene y
transcribe, **Escape** cancela, y nada de lo que se escriba o pulse mientras una
grabación está en curso o transcribiéndose se envía. La grabación se detiene sola
al llegar al dictado más largo de la organización y se transcribe, y un micrófono
desconectado a mitad la termina igual en vez de descartarla. Si la subida tarda
más de un segundo, la barra muestra cuánto se ha subido ya; después muestra
**Transcribing** hasta que llega el texto.

Todo lo que el dictado tiene que decir aparece en una franja unida bajo el
compositor: la petición de permiso, un micrófono bloqueado o ausente, los últimos
30 segundos, cinco segundos sin sonido, una grabación de menos de un segundo (no
se envía), una grabación que se detuvo en el límite, cuántas palabras se
insertaron y cada fallo. El recuento de palabras desaparece a los pocos segundos
o con tu siguiente tecla. Una grabación que no se pudo transcribir se conserva
hasta que pulsas **Retry** o **Discard**.

Si la organización eligió Server pero
nada se resuelve para el agent que elegiste —ningún proveedor en el agent ni en
la organización, o ninguna clave elegida para él—, o no hay ningún agent elegido, el
micrófono aparece tachado y dice por qué; quien tiene `org:settings` recibe un
enlace a la tarjeta Voice, y quien puede editar agents, un enlace a la tarjeta Voice
de ese agent.

El brillo debajo del compositor mientras hablas sigue a **Voice glow** en
**Settings → Profile → Appearance**, junto al tema y a **Motion**: **Vivid**,
**Subtle** (por defecto) u **Off**. Se recuerda por navegador. **Motion** decide
cuánto se mueve toda la consola: **System** (por defecto) sigue el ajuste de
movimiento reducido del sistema operativo, **Reduce** reduce el movimiento sin
él y **Full** lo mantiene diga lo que diga el sistema operativo. Mientras el
movimiento está reducido no hay brillo alguno, la franja aparece sin deslizarse
y el nivel es un indicador de cinco pasos.

### La tarjeta Voice { #the-voice-card }

En la página **Members** de la organización, para quien tiene `org:settings`.
**Speech to text** elige el motor —Off, Browser o Server, cada uno diciendo a
dónde va el audio— y, para Server, la grabación más larga, de 10 segundos a 10
minutos. **Default provider**, debajo, es el proveedor y el modelo del catálogo
de speech-to-text y un idioma (detección automática, o un idioma fijo, que es más
preciso). Se muestra sea cual sea el motor, porque es también a donde envían sus
mensajes de voz los [bots de canal](channels.md#what-every-channel-shares)
configurados para heredar; **None** lo vacía.

**Key**, junto al proveedor, es la clave del vault con la que se envía la
configuración por defecto. Lista las claves de API cuyo propósito es ese
proveedor y que ve toda la organización: la plataforma gasta esta clave en el
dictado de cada miembro y en cada bot que hereda, así que la clave privada de un
miembro no se ofrece y se rechaza si se envía. Con exactamente una clave que
encaje se elige por ti, y se guarda por su id en cualquier caso; nada elige una
clave en tiempo de ejecución. Un proveedor sin clave aparece marcado **no hay
clave para este proveedor**, y el selector enlaza al vault para añadir una.
Cuando Server está guardado pero no puede funcionar —el modelo se retiró del
catálogo, o la clave se borró o se hizo privada—, la tarjeta lo dice y pide
**elegir una clave** cuando eso es lo que falta, porque entonces todos los
miembros ven un micrófono tachado.

Server sin proveedor predeterminado es una configuración, no un fallo: la tarjeta indica que solo dictan los agents con su propio proveedor.
**Voice conversations**, debajo, guarda los ajustes de llamada de la organización - ver [Llamadas de voz](#voice-calls).

Para quien además tiene `runs:view`, la tarjeta empieza con una línea sobre lo que
la organización transcribió en los últimos 30 días — «42 min · 118 grabaciones
(30 sin duración)» — sumando el dictado, los mensajes de voz de los canales y la
API. **Show breakdown** lo desglosa por agent y por bot de canal. Los minutos
cuentan solo las grabaciones cuya duración se informó, así que la línea dice
cuántas no la tienen; queda oculta mientras no se haya transcrito nada. Las
cifras salen de [`GET /ml/calls/summary`](ml-services.md#what-is-recorded).

### El motor propio de un agent { #an-agents-own-engine }

La pestaña **Build** de un agent tiene una tarjeta **Voice** después de sus
ajustes de modelo, para un agent que deba transcribir de forma distinta a su
organización. **Inherit** conserva el proveedor, el modelo y la clave de la
organización y muestra cuáles son; **Choose** elige un par del catálogo y la
clave con la que se envía —una clave de API de ese proveedor que puedas ver,
porque publicar la presta a todos los que pueden ejecutar el agent—.

Nunca es la
clave de la organización: un agent con par propio nombra su propia clave. El
idioma se elige aparte: heredar el de la organización, o fijar uno —así un agent
en polaco puede conservar el proveedor y la clave de la organización—.

Lo que elige forma parte del spec: se guarda con el borrador, entra en vigor cuando se
publica el agent, y se aplica al [dictado](#dictation) dirigido a este
agent y a los mensajes de voz que heredan sus bots de canal.
[El orden](ml-services.md#which-engine-a-recording-reaches) cuenta el resto.

La tarjeta avisa cuando la anulación cambia menos de lo que parece: con el motor
de la organización en Off o Browser solo alcanza a los mensajes de voz de los
canales, y sin proveedor en la organización es aquello con lo que funciona el
dictado a este agent.

### Llamadas de voz { #voice-calls }

Una [llamada de voz](voice.md) es una conversación hablada con un agent
publicado: tú hablas, él responde en voz alta y puedes interrumpirlo. Tres
lugares de la consola la configuran.

- **La tarjeta Voice de la organización**, bajo **Voice conversations**: **Allow
  voice conversations** (apagado por defecto), **Offer calls in chat**, **Longest
  call (minutes)**, de 1 a 50, y **Monthly call minutes**, o sin límite mensual
  para confiar solo en los budgets. Los tres primeros necesitan `org:settings`;
  los minutos necesitan `budgets:manage` y son de solo lectura para cualquier
  otro. Quien tiene `runs:view` ve además cuántos de los minutos de este mes han
  usado las llamadas.
- **La tarjeta Voice del agent**, bajo **Voice conversations**: **Take voice
  calls**, y después el provider y el modelo de la llamada (en Azure, el nombre
  del deployment y su modelo base), la clave, la voz, el idioma hablado (o
  **Follow the caller**), la llamada más larga y una nota de voz. La tarjeta
  enumera lo que el agent no puede usar en las llamadas, dice que las
  salvaguardas no pueden filtrar las palabras habladas antes de que se oigan, y
  que las llamadas se registran como texto sin conservar el audio. Entra en
  vigor cuando se publica el agent.
- **El interruptor Voice calls de un embed**, en los formularios del widget y de
  la página alojada - ver
  [Canales](channels.md#voice-calls-on-a-widget-or-a-hosted-page).

Antes de ofrecer una llamada, la consola pregunta si este agent puede atenderla
(`GET /agents/{id}/voice`), para que nadie conceda el micrófono solo para que se
lo rechacen. La respuesta nombra lo que falta: llamadas apagadas en la
organización o en el chat, ninguna voz configurada en el agent, el modelo ya no
ofrecido, ninguna clave, o ningún minuto restante este mes.

Una llamada pasa por estados que la consola nombra: conectando, escuchando,
hablas tú, pensando, habla el agent, interrumpido, trabajando con una
herramienta, esperando tu aprobación, una aprobación que no puedes dar, casi sin
tiempo, y terminada - por ti, por un límite, por una conexión caída o por un
fallo. Los subtítulos aparecen palabra a palabra en una región en vivo que un
lector de pantalla anuncia, y cada turno terminado sustituye su subtítulo por el
mensaje guardado en la conversación, así que después la llamada está en tu
historial y puedes seguir escribiendo.

**Las aprobaciones** se deciden en la llamada: una tarjeta muestra la
herramienta, sus argumentos exactos y lo que se te oyó decir, con 60 segundos
para decidir. Sin `approvals:decide` se te dice que la herramienta necesita una
aprobación que no puedes dar por voz. **Los límites** se dicen en voz alta: un
minuto antes de que acabe la llamada más larga se te avisa, y cuando se agotan
el tiempo, el budget o los minutos del mes, el agent dice una frase y la llamada
termina. Hablar es manos libres por defecto; **push-to-talk** (mantén pulsado el
botón o Espacio) es una opción que recuerda tu navegador, junto a silenciar y
**End call**.

!!! note "La vista de llamada todavía se está diseñando"

    Todo lo anterior está construido salvo la propia vista de llamada y su botón
    en el composer del chat, cuya disposición aún se está decidiendo. Hasta que
    llegue, ninguna página ofrece una llamada.

En **Activity**, una llamada es una fila con una insignia de micrófono, y el
filtro de tipo (**Text** o **Voice calls**) la reduce a llamadas; una llamada que
se reconectó sigue siendo una fila, con el tiempo y el coste de cada conexión
sumados. La tarjeta **Voice minutes** del dashboard, en la banda Usage para
quien tiene `runs:view`, muestra los minutos de llamada y las llamadas del
periodo, los tres agents principales y los minutos de este mes frente al límite
de la organización.

## Para qué sirve cada área { #what-each-area-is-for }

| Área | Contiene | Lee |
|---|---|---|
| **Agents** | El catálogo, el Builder, las versiones, el uso compartido, las pruebas, la actividad | [Tu primer agent](first-agent.md) |
| **Chat** | Hablar con un agent publicado | [Superficies](channels.md) |
| **Knowledge** | Colecciones, documentos, fuentes de sincronización, ajustes de ingesta | [Procesamiento de archivos](file-processing.md) |
| **Skills** | Procedimientos escritos que un agent carga cuando hacen falta | [Skills](skills.md) |
| **Context** | Conocimiento permanente ligado a muchos agents | [Archivos de contexto](context.md) |
| **Routines** | Horarios y disparadores por evento | [Disparadores](triggers.md) |
| **Runs** | Qué se ejecutó, cuánto costó, qué tocó, si falló | [Governance](governance.md#audit) |
| **Sandboxes / Workspaces** | Sesiones aisladas de archivos y shell en las que trabajó un agent | [La sandbox](sandbox.md) |
| **MCP servers** | Conexiones a herramientas externas, personales y de toda la organización | [MCP](mcp.md) |
| **Channels** | Bots de Slack, Telegram y Mattermost, widgets, páginas alojadas | [Superficies](channels.md) |
| **Vault** | Credenciales, selladas por organización | [Secretos](secrets.md) |
| **Organizations** | Miembros, roles, invitaciones | [Permisos](permissions.md) |
| **Settings** | Providers, valores de ingesta por defecto, notificaciones, tu propio perfil | [Configuración](configuration.md) |
| **Admin** | El despliegue en sí: usuarios, inquilinos, sistema, ajustes del despliegue | [El despliegue](deployment.md) |

El catálogo de **Agents** se puede filtrar por **category** y **tag** — las
etiquetas editables y locales a la organización que se muestran en la tarjeta de
cada agent. Cada filtro es un menú de las etiquetas de los agents que puedes ver;
marca varias para ampliarlo. Las categories y los tags de un agent los mantienes desde su página
de detalle, junto a los controles del avatar, y el cambio surte efecto al
momento, sin publicar una nueva versión.

## Cuando una página parece vacía { #when-a-page-looks-empty }

**Un estado vacío y una petición fallida se ven igual.** Todas las páginas de aquí
se abren en varias consultas y muestran "todavía nada" cuando una de ellas falla.

Así que antes de concluir que una colección está vacía o que un agent no tiene
runs, mira la pestaña de red. Esta es, con diferencia, la forma más habitual de
que un problema real se lea como algo tranquilo.

## Recapitulación { #recap }

- El dashboard son **treinta y ocho widgets** que ordenas tú, guardados por
  persona y por organización — todos menos tus propias notificaciones
  protegidos por el permiso que necesitan sus datos.
- Una disposición guardada **puede ocultar y reordenar, pero nunca revelar** — la
  comprobación de permisos corre la última.
- **La campana** es un contador de no leídas en marcha con la lista completa a
  un clic, sin importar en qué página estés.
- **Chat, Slack y la API son el mismo runner**, así que lo que ves en la consola
  es lo que recibe un cliente.
- **Los comandos de barra son tuyos**, incluidos los de serie, y puedes ocultar
  los que no uses.
- Una página que muestra "todavía nada" puede ser **una petición fallida**, no un
  recurso vacío.
