---
source_sha: "ebbdbea67616"
---

# La consola { #the-console }

La consola es la aplicación web desde la que se configura todo lo demás de este
sitio. Esta página es el mapa: para qué sirve cada área, y qué página la explica
como es debido.

Si buscas una pantalla concreta, el camino más rápido es el **"?"** de la
cabecera de cada página — reproduce el recorrido guiado de esa página, y una
página cuya cabecera no lleva "?" no tiene recorrido que reproducir. El chat no
tiene cabecera: sus consejos están en los ajustes del chat, los deslizadores junto
al micrófono.

## El dashboard { #the-dashboard }

La página de inicio es una **cuadrícula de widgets que tú ordenas**, y es la
respuesta a "qué está pasando" sin abrir cinco páginas.

Existen treinta y ocho tarjetas. No las verás todas: **cada tarjeta está
protegida por el permiso que necesitan sus datos**, así que un widget que no
puedes leer nunca se monta y sus consultas nunca se lanzan — excepto tus
propias notificaciones, más abajo, que solo necesitan que hayas iniciado
sesión. Una banda vacía desaparece junto con su título en lugar de quedarse ahí
vacía.

Un selector arriba dice de quién es el dashboard, y ofrece solo las vistas que
puedes abrir. Todos empiezan en **Me**:

| Vista | Responde a |
|---|---|
| **Me** | Un saludo y tu periodo en una frase; tus runs, cuántos terminaron, lo que te espera y lo que costó; después las llamadas que te esperan, tus conversaciones, tus agents y lo que han compartido contigo |
| **Organization** | La página que se ordena, descrita abajo |
| **Group** | Los miembros de un [grupo](departments.md) - sus runs, gasto, modelos, cuándo trabajan y quién lo usa más. El grupo se elige junto al selector. Un grupo cuyos miembros no ejecutaron nada en el periodo lo dice una vez, con un enlace al grupo, en lugar de una página de tarjetas vacías |
| **Deployment** | Solo para un [administrador del despliegue](permissions.md) — totales de la plataforma, salud, inquilinos más activos, valoraciones |

La vista de la organización muestra las tarjetas que responden con datos,
agrupadas en bandas. El resto - integraciones, canales, rutinas, sincronización
de conocimiento, departamentos, miembros, sandboxes - espera en el catálogo, a un
clic bajo **Customize**:

| Banda | Responde a |
|---|---|
| *(sin título, arriba del todo)* | El resumen, los runs en el tiempo y cómo terminaron |
| **Needs attention** | Lo que está esperando: [aprobaciones](governance.md#approvals), fallos recientes, margen de budget, tus [notificaciones](#the-bell) más recientes |
| **Usage & cost** | Qué agents se usan, gasto, [minutos de voz](#voice-calls), cuándo ocurre el trabajo, de dónde vienen los runs, mezcla de modelos, latencia, calidad de respuesta, quién lo usa |

El dashboard se abre con **Get started** hasta completar cada paso: contarles a
los agents sobre ti, empezar una conversación, conectar un servicio con tu
propia cuenta, configurar una rutina y crear un agent - este último es una
pregunta al Architect, que lo crea contigo.

Quien construye agents tiene después los pasos de la organización: publicar un
agent, darle una base de conocimiento, añadir departamentos, invitar a alguien
del equipo y - quien pueda - poner un agent en una app de chat. Cada paso se
marca a partir de lo que existe, se haya hecho donde se haya hecho, no de un
clic en la tarjeta; cerrar la tarjeta la oculta en ese navegador.

Tu propia vista muestra además **Discover AgenticOS**: una tarjeta por cada cosa
fácil de pasar por alto - el servidor MCP propio de este despliegue para Claude
Code, Codex o Cursor, subagents, sandboxes, apps, routines, apps de chat, el
navegador web, bases de conocimiento y skills -, cada una lleva a donde se activa,
y solo las que puedes usar. Cierra una tarjeta o todas; también se guarda en el
navegador.

Los gráficos en el tiempo eligen su propio paso. El tramo desde el primer run del
periodo hasta ahora se dibuja en 48 puntos como mucho, con el paso más fino que
cabe - un minuto, cinco, quince, una hora, tres o seis horas, un día, una
semana -, así que una tarde se lee en minutos y un trimestre en semanas en lugar
de como un pico en el borde derecho.

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

## La bandeja { #the-inbox }

La **bandeja** (Inbox), bajo Chat en la barra lateral, es lo que la plataforma
te trajo por iniciativa propia: lo que tus
[vigilancias](governance.md#proactive-work) encontraron en tus conexiones y lo
que propuso la revisión nocturna. El número a su lado dice cuánto espera. Se lee
como un buzón: una fila por elemento, lo urgente primero, de dónde vino y
cuándo, y las respuestas en la fila.

Filtra por su origen, o abre **Hecho** para ver lo que ya aceptaste o
descartaste y recuperar algo descartado. **What they found** en la tarjeta de
vigilancias de Rutinas la abre filtrada a las vigilancias. Filas más cortas
encabezan tu dashboard como **Briefing**, y el chat vacío con el agente inicial
muestra el primero como tarjeta, con un enlace al resto.

Lo que una vigilancia encuentra y no hace falta avisar al momento espera a tu
mañana: a la hora que mantiene la proactividad de la organización, una
notificación y un mensaje directo de cada uno de sus bots de Slack, Teams y
Mattermost que te conoce enumeran lo nuevo. Cada hallazgo entra en un solo
briefing.

## La campana { #the-bell }

Junto al buscador, en la barra lateral: un contador en marcha de lo que aún no
has leído, y un clic abre la lista misma. A diferencia del widget de arriba,
abrirla trae la página completa que estás mirando, no una vista previa de
cinco tarjetas — **Load more** sigue paginando hacia atrás por la organización
en la que estás ahora, más lo dirigido al deployment entero, hasta llegar a lo
que ya ha caducado.

Cada fila empieza por aquello de lo que trata: la cara del agente, con una
insignia de cómo fue su run, o un icono del tipo de evento — verde para un run
terminado o un servidor MCP que vuelve a funcionar, rojo para un fallo o un
budget agotado, ámbar para una aprobación o un aviso de budget.

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

## El asistente { #the-assistant }

Cada página tiene al **Architect** en su esquina inferior derecha: un agent que
toda organización recibe sin instalar nada, compartido con todos los que pueden
ejecutar agents (`agents:run`). Está vinculado al
[servidor MCP de la propia plataforma](mcp.md#agenticos-as-an-mcp-server).
Pregúntale qué agents responden dudas de reembolsos, por qué falló el run de anoche
o qué hay en una base de conocimiento.

Dile qué debe hacer un agent y lo construye contigo, una pregunta cada vez, cada
una con respuestas propuestas: elige las capabilities, la base de conocimiento y el
modelo, dice por qué en una línea, esboza el agent, lo prueba con tus propias
preguntas como borrador sin publicar, corrige lo que estaba mal y lo publica cuando
lo apruebas. Una rutina la configura igual.

Antes de que cambie nada, te muestra lo que apruebas: el borrador de un agent
como el propio borrador - dónde se crea, su nombre, qué puede hacer y sus
instrucciones - y todo lo demás como la llamada exacta. Actúa con tus permisos,
así que encuentra y hace lo que tú podrías, y nada más. Su coste cuenta como el
de cualquier agent.

Un bocadillo sobre él habla de lo que te espera — aprobaciones, una organización
sin ningún agent — o de la página en la que estás, y de vez en cuando ofrece un
consejo. Haz clic en el bocadillo para preguntarle; × silencia esa página, y la
campana de su ventana apaga los bocadillos. Un bocadillo sin respuesta desaparece
a los pocos segundos. Si nadie lo toca durante menos de un minuto, el botón se
esconde en el borde derecho de la pantalla y deja una franja para sacarlo - con
un punto cuando algo espera - y se queda allí de página en página hasta que se
abre.

En un teléfono no hay bocadillo - taparía la página de la que habla - y el botón
lleva el punto en su lugar. Las aprobaciones que ya mencionó siguen mencionadas
durante el resto de la pestaña, aunque un enlace recargue la consola.

Su ventana es el propio chat de la consola, no una página dentro de la página, y
se abre con cuatro mosaicos, para que el primer mensaje sea un clic; guarda su
propio historial de conversaciones. En un teléfono ocupa toda la pantalla.

Cuando nombra una página, el enlace la abre en la consola detrás de la ventana y
señala el control al que se refiere — el botón que crea un agent, la pestaña de
aprobaciones. La cámara de su cabecera le muestra la página en la que estás: el
navegador pregunta qué pestaña compartir y una imagen se adjunta a tu próximo
mensaje.

Planifica los trabajos largos como una lista que puedes seguir, guarda
notas sobre ti entre conversaciones, te dice cuánto cuestan tus agents y solo
borra un borrador de agent que creó por error y una rutina que le pidas quitar.
Además de las
aprobaciones y de una organización vacía, su bocadillo avisa cuando un run tuyo
acaba de fallar y cuando un formulario lleva un minuto abierto sin terminar.

Mientras la organización no tenga un modelo, no puede responder. Al abrirlo
escribe entonces una breve conversación sobre cómo conectar uno: consigue una clave
de API de un provider, abre el Architect en el Agent Builder, elige el provider en
**Model** y pega la clave, y escoge un modelo. Solo quien puede cambiar los ajustes
de la organización recibe el botón; a los demás se les dice quién puede hacerlo.

El Architect es un agente como cualquier otro, así que su nombre, su modelo, su
conocimiento y el resto de su spec se editan en el Agent Builder - lo hace quien
puede cambiar los ajustes de la organización, porque todos en la organización lo
usan. La página de la organización tiene una tarjeta que lo apaga para todos y
fija su saludo. **Settings → Assistant** guarda solo tus propios consejos.

## Cambios hechos en otro lugar { #changes-made-elsewhere }

Una página abierta se mantiene al día con los cambios hechos en otro lugar: la
consola de un compañero, un script con una [clave de API](api.md), Claude Code a
través del [servidor MCP de la plataforma](mcp.md#agenticos-as-an-mcp-server) o el
Architect. Cada escritura correcta se anuncia a las consolas abiertas de la
organización en cuanto se confirma, también las que solo hace la consola —
compartir, rutinas, bots de canal, comparticiones de grupo, ajustes de
notificaciones—, y una lista o una página de detalle sin nada sin guardar vuelve a
pedir los datos en su sitio.

Un agent creado con una clave aparece en la página Agents sin recargar, y un agent
compartido en una pestaña muestra su nueva audiencia en otra.

También se anuncian los runs, cuando empiezan, se detienen en una aprobación o una
pregunta y terminan: un run que lanza una programación aparece en una página
Activity abierta y cambia de estado allí, sin que haya ninguna petición tuya
detrás.

La excepción es el Builder, porque guarda tu borrador mientras escribes. Cuando el
agent que editas cambia en otro lugar, deja de guardar y obtiene la nueva versión.
Si no hay nada sin guardar, simplemente la adopta; si hay cambios sin guardar, te
dice quién lo cambió y por dónde, y espera a que elijas **Recargar** (su versión)
o **Conservar mis cambios** (la tuya, guardada encima de la suya).

Solo te enteras de lo que podrías leer: un cambio en un agent, un skill, una base
de conocimiento, un archivo de contexto, una página, una clave o un servidor MCP
que no ves nunca llega a tu consola, y una eliminación solo llega a los roles que
ven todas las filas de ese tipo. Los runs llegan a los roles que leen el historial
de runs o deciden aprobaciones, los bots de canal a los roles que los gestionan, y
tus notificaciones solo a ti. Si la conexión se corta, la consola funciona como antes y se reconecta sola.

## Chat { #chat }

Donde hablas con un agent publicado. El selector elige qué agent responde, y el
run se comporta exactamente igual que en Slack o detrás de la API — mismo budget,
misma puerta de aprobación, mismo rastro de auditoría, porque
[todas las superficies pasan por un único runner](channels.md).

**La lista de conversaciones** dice con quién es cada hilo y cuándo se movió por
última vez. Uno cuyo run sigue trabajando muestra un indicador giratorio y cuánto
lleva; uno con una respuesta que no has visto desde la última vez que lo abriste
lleva un punto, que abrirlo borra - solo para ti, porque cada lector de un hilo
compartido lo lee por separado.

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

**`@` señala al agent qué usar.** Escribe `@` y un menú ofrece lo que el agent
puede usar, en este orden: sus servidores MCP, los agents a los que pasa trabajo
(con la capability de delegación activada), sus capabilities - **Sandbox**, **Web
research** -, sus skills y después sus bases de conocimiento y archivos de
contexto. Lo elegido se queda en tu texto como `@Nombre`, marcado con su logo, y
al agent se le indica que lo use - las herramientas de un servidor o de una
capability, la búsqueda de una base de conocimiento, un skill - sin pegar su
contenido. Nombrar un agent le pasa el trabajo; nunca cambia quién responde.
Borra el `@Nombre` y lo elegido desaparece. Un enlace pegado muestra el icono de
su sitio encima del cuadro y en el mensaje enviado. Una mención nunca amplía lo
que el agent puede alcanzar: el servidor comprueba cada una de nuevo como tú,
frente a lo que el agent ya tiene. En el panel de pruebas del Builder el menú lee
el borrador que estás probando. Mientras una conversación está vacía, el cuadro muestra uno
tras otro ejemplos hechos con lo que el agent puede usar - su servidor, una
capability, un delegado, un skill - y `/`; desaparecen en cuanto haces clic en él.
Encima, las tarjetas son los **primeros mensajes** propios del agent, definidos en
el Builder bajo sus instrucciones; un agent sin ellos ofrece los cuatro del chat,
entre ellos uno para preguntar qué puede hacer y otro para configurar una rutina.

**Debajo de una respuesta.** Un agent con
[Follow-ups](reference/capabilities.md#follow-ups) ofrece debajo de su respuesta
más reciente hasta tres pasos siguientes como botones, y un clic envía uno. Una
línea dice qué anotó sobre ti, u olvidó, con **Manage** para
[las notas mismas](reference/capabilities.md#memory-files) - pídele que olvide
algo y lo hará. Cuando una petición necesita una capability que el agent no
tiene, una tarjeta propone activarla o pedírselo a su propietario
([cómo](reference/capabilities.md)).

**Guardar una petición que funcionó.** Pasa el cursor por tu propio mensaje: el
calendario lo convierte en una rutina - el mismo prompt, semanal por defecto, en
el agent que respondió - y el robot le pide al Architect que cree un agent que lo
haga. Pasa el cursor por la respuesta y el marcador le pide al Architect que haga
un [skill](skills.md) de cómo se hizo, para que cualquier agent lo haga igual la
próxima vez; recibe tu petición y la respuesta, y se ofrece a quien puede escribir
skills.

**Enlaces que señalan.** Un enlace de la consola que un agent escribe en su
respuesta - «aquí está el botón que conecta tu Gmail» - abre esa página sin
recargar la consola, y un `?highlight=` en él señala el control que nombra, como
hacen los enlaces del Architect.

**El agent AgenticOS te conoce.** Mientras tu cuenta no dice nada de tu rol ni de
tu trabajo, un saludo empieza una entrevista corta: a qué te dedicas, qué llena tu
semana, con qué herramientas trabajas - una pregunta cada vez, cada una con
respuestas para elegir. Lo que dices se guarda en tu perfil, así que desde
entonces lo sabe cada agent, y la entrevista termina con hasta tres tarjetas que
configurar - una rutina, un servicio que conectar, un agent propio - cada una con
un clic. Sáltate una pregunta, o pide algo real, y hará el trabajo en su lugar.

**Lo que notó durante la noche.** Donde tu organización lo activó, una vez al
día, temprano en tu mañana, la plataforma lee tus conversaciones recientes en una
tarea en segundo plano: una
petición que repites se convierte en una rutina propuesta, lo que un agent supo
de tu rol en un perfil propuesto, y tu chat vacío de AgenticOS recibe primeros
mensajes escritos para tu trabajo. Las propuestas esperan como tarjetas en ese
chat vacío, en tu dashboard y en la campana, y **Ajustes → Asistente** las lista
todas - ahí recuperas una descartada o te excluyes; acepta una y queda configurada, descártala y la misma
propuesta no se vuelve a hacer. Nada se ejecuta cuando no pasó nada nuevo, y lo
que esto puede gastar tiene un [límite por persona](governance.md#proactive-work).
Un enlace de chat con `?agent=<slug>` abre el chat en ese agent.

**El horario laboral** en **Settings → Profile** dice a los agents cuándo
trabajas, para que una rutina que propongan caiga dentro de tu día. Nada espera
por él: es conocimiento para el agent, no un calendario.

Al volver a abrir una conversación, ves los mensajes más recientes. Usa **Load earlier messages** encima del historial para leer turnos más antiguos. Las respuestas en curso y los resultados sin guardar siguen visibles mientras se actualiza el historial guardado.

**Mientras el agent trabaja**, lo que envías espera su respuesta, como en
cualquier chat: queda en una cola encima del cuadro de texto y sale cuando termina
el run. Arrastra un mensaje de la cola, o usa sus flechas, para cambiar el orden.
**Send now** lo envía en cambio a la tarea en curso - el agent lo lee en su
siguiente paso y corrige el rumbo sin empezar de nuevo, y aparece en la
conversación donde llegó. Un mensaje con archivos siempre espera la respuesta.
Slack, Telegram y Mattermost mantienen su propio comportamiento, descrito en
[Canales](channels.md).

**Irte mientras responde.** No tienes que esperar. Cierra la pestaña, sal de la
app o abre otra conversación, y el agente termina la respuesta solo: llega a la
conversación, y la campana - y un correo, si los mantienes para los runs que
terminan o fallan - te avisa de que está ahí, con un enlace a ella. Un turno que
sigue en marcha tras una hora sin nadie mirando se detiene, y se te avisa de eso
([`CHAT_DETACHED_TURN_MINUTES`](configuration.md#a-chat-turn-left-running)). Uno
que espera una aprobación o tu respuesta a una pregunta te avisa por esa vía.
Si vuelves mientras aún responde - a la conversación, desde otra pestaña, tras
recargar -, el chat retoma la respuesta donde está, con todo lo que el agente ha
hecho hasta entonces, y la sigue dibujando a medida que llega.

**En el teléfono** el chat se comporta como una app de mensajería: el campo de
escritura queda sobre el teclado y la conversación en su último mensaje mientras
se abre, Enter empieza una
línea nueva, y adjuntar un archivo o dictar están detrás de un único **+**. Los
campos nunca son tan pequeños como para que iOS haga zoom en ellos.

**Dibujos.** Un agente con [Visuals](reference/capabilities.md#visuals) dibuja bajo
su mensaje - un diagrama, una explicación con controles deslizantes, una escena 3D - y
usted lo ve aparecer mientras se escribe; sus scripts arrancan cuando está completo. El
panel muestra el dibujo entero, ajustado a la conversación, con botones para abrirlo a
pantalla completa, mostrar su código, descargarlo, copiar un SVG como imagen, ampliarlo
y guardarlo como [aplicación](artifacts.md#visuals) con un enlace para
compartir. Cuando un dibujo informa de un error, el agente ya lo sabe; **Corregir**
vuelve a pedírselo. En un teléfono, un toque lo abre a pantalla completa.
La tarjeta **Recent visuals** del panel muestra los últimos dibujados para usted, y
cada uno abre la conversación en la que se dibujó.

**Ver un recorrido.** Cuando un agent con el
[navegador web](reference/capabilities.md#browser-automation) empieza en una página, su
navegador se dibuja en directo bajo el mensaje del agent: una ventana con la dirección y
la página tal como la ve el agent, una línea sobre la página con lo que hace ahora y su
cursor moviéndose hacia lo que pulsa o rellena. La ventana mantiene su forma y crece y
encoge con la conversación; varios recorridos a la vez se colocan uno junto a otro, dos
por fila donde hay sitio. El botón de maximizar abre uno a pantalla completa, y restaurar
lo devuelve bajo el mensaje. La lista completa de pasos, cada uno con su propósito, está
detrás del botón de pasos.

**Tomar el control de un recorrido.** Mientras un recorrido está en curso, **Take over**
en la barra del navegador detiene al agent tras su paso actual y te da la página, en la
misma ventana: clic, escribir, desplazarse, pegar. **Hand it back** y el agent sigue
desde donde lo dejaste. Cuando el agent no puede pasar solo de una página - un inicio de
sesión, un captcha -, el navegador dice *The agent needs you* y para qué.
Quien puede ver runs pero no editar el agent puede mirar, no manejar. La misma ventana
se abre en una página propia desde el enlace de un canal. Consulta el
[navegador web](reference/capabilities.md#browser-automation).

**Señalar en la página.** El botón del bocadillo en la barra del navegador te deja
hacer clic en un punto de la página y escribir una nota sobre él - *este botón, no
aquel*. **Add to message** pone la página en tu mensaje como una imagen con el punto
marcado, con tu nota y la dirección de la página, para enviarlo o seguir escribiendo.
Funciona también en un browse terminado, sobre su última imagen.

**Seguir con la sesión iniciada.** Cuando el browse actúa por ti - tu propio chat, tu
mensaje directo, tu propia programación -, **Devolver** ofrece *Mantener mi sesión en*
el sitio en el que estás. Márcalo después de iniciar sesión y los browses posteriores
que actúen por ti empiezan con la sesión iniciada allí: las cookies y el almacenamiento
del sitio quedan sellados en el vault solo para ti, nunca se muestran y nunca se usan
para un visitante del widget, una sala compartida, una clave de API ni un disparador de
eventos. **Ajustes → Inicios de sesión** lista los sitios que guardaste, y **Olvidar**
hace que el siguiente browse empiece sin sesión. **Iniciar sesión en un sitio** abre ahí
un navegador en cualquier sitio solo para ti, antes de que un agent lo necesite: inicia
sesión, devuélvelo con la casilla marcada y la sesión se guarda igual. Necesita el
navegador de inicio de sesión del despliegue
([`BROWSER_SIGN_IN_CDP_URL`](configuration.md)).

**Detener una ejecución en espera.** El botón **Stop** sigue disponible mientras el
agente espera una respuesta, una aprobación o la conexión de una cuenta. También
funciona al recargar una pregunta o aprobación pendiente. Detenerla cierra las llamadas
pendientes sin reanudar el modelo y conserva el coste registrado. Puedes detener tus
propias ejecuciones; quienes pueden aprobar también pueden detener una ejecución
pendiente de aprobación. Si un error temporal impide detenerla, la tarjeta sigue
disponible para volver a intentarlo.

### Dictado { #dictation }

El micrófono está junto a Enviar en cada agent, y en el menú `+`. Convierte la
voz en texto dentro del cuadro y nunca lo envía: lo que dijiste aparece donde
estaba el cursor cuando pulsaste el micrófono, listo para editar, y no va a
ninguna parte hasta que pulses Enviar. Cómo se transcribe lo decide el agent, en
la pestaña Dictado de [su tarjeta Voice](#an-agents-voice-card):

- **Transcribe with a provider** encendido — el navegador graba y este
  despliegue envía la grabación al provider del agent o al predeterminado de la
  organización. Funciona en cualquier navegador que pueda grabar. El endpoint,
  sus límites y lo que se registra están en
  [Dictado en el chat](ml-services.md#dictation-in-chat).
- Apagado, o sin clave con la que enviarla — el reconocimiento de voz del propio
  navegador, así que el audio va al fabricante del navegador (Google, Apple) y no
  cuesta nada. Firefox no tiene: su micrófono lo dice al pulsarlo. Mientras
  escucha, una nota sobre el compositor dice que el Dictado del agent está
  apagado, y enlaza a su pestaña Dictado para quien puede editar el agent.

Con un provider, al pulsar el micrófono flota sobre el compositor, que no
cambia, una **píldora de grabación**: Cancel, el nivel, un temporizador y Stop.
**Enter** detiene y transcribe, **Escape** cancela, y nada de lo que se escriba
o pulse mientras una grabación está en curso o transcribiéndose se envía. La
grabación se detiene sola en el dictado más largo de la organización y se
transcribe, y un micrófono desconectado a mitad la termina igual, en vez de
descartarla. Si la subida tarda más de un segundo, la píldora muestra cuánto se
ha subido; después dice **Transcribing** hasta que llega el texto. El
reconocimiento del navegador tiene su propia píldora, con **Done dictating**.

Todo lo que el dictado tiene que decir aparece en una franja sobre el
compositor, junto a la píldora: la petición de permiso, un micrófono bloqueado o
ausente, los últimos 30 segundos, cinco segundos sin sonido, una grabación de
menos de un segundo (no se envía), una grabación detenida en el límite y cada
fallo. Cuántas palabras se insertaron se anuncia al lector de pantalla en lugar
de mostrarse, porque las palabras están en el cuadro. Una grabación que no se
pudo transcribir se guarda hasta que pulses **Retry** o **Discard**.

El brillo alrededor del cuadro de una página alojada mientras hablas sigue a **Voice glow** en
**Settings → Profile → Appearance**, junto al tema y a **Motion**: **Vivid**,
**Subtle** (por defecto) u **Off**. Se recuerda por navegador. **Motion** decide
cuánto se mueve toda la consola: **System** (por defecto) sigue el ajuste de
movimiento reducido del sistema operativo, **Reduce** reduce el movimiento sin
él y **Full** lo mantiene diga lo que diga el sistema operativo. Mientras el
movimiento está reducido no hay brillo alguno, la franja aparece sin deslizarse
y el nivel es un indicador de cinco pasos.

### La tarjeta Voice { #the-voice-card }

En la página **Members** de la organización, para alguien con `org:settings`.
Contiene el speech-to-text **predeterminado** que heredan los agents y los bots
de canal, y cuánto puede durar un dictado; si un agent dicta con un provider, o
atiende llamadas, se activa en la propia tarjeta Voice de ese agent. **Max
recording length** va de 10 segundos a 10 minutos. **Default provider** es el
provider y el modelo del catálogo de speech-to-text y un idioma (detección
automática, o un idioma fijo, que es más preciso). También es a donde los
[bots de canal](channels.md#what-every-channel-shares) configurados para heredar
envían sus mensajes de voz; **None** lo borra.

**Key**, junto al provider, es la clave del vault con la que se envía el
predeterminado. Lista las claves de API cuyo propósito es ese provider y que
toda la organización puede ver - la plataforma gasta esta clave en el dictado de
cada miembro y en cada bot que hereda, así que la clave privada de un miembro no
se ofrece y se rechaza si se envía. Con exactamente una clave así, se elige por
ti, y en cualquier caso se guarda por nombre; nada elige una clave en tiempo de
ejecución. Un provider sin clave aparece marcado como **no key for this
provider** y el selector enlaza al vault para añadir una. Cuando el
predeterminado no puede funcionar - el modelo se retiró del catálogo, o la clave
se borró o se hizo privada - la tarjeta lo dice, y pide **choose a key** cuando
es eso lo que falta.

Para alguien que además tiene `runs:view`, la tarjeta empieza con una línea
sobre lo que la organización transcribió en los últimos 30 días — "42 min · 118
recordings (30 without a length)" — entre dictado, mensajes de voz de canales y
la API. **Show breakdown** lo desglosa por agent y por bot de canal. Los minutos
solo cuentan las grabaciones cuya duración se informó, así que la línea dice
cuántas no; está oculta mientras no se ha transcrito nada. Las cifras vienen de
[`GET /ml/calls/summary`](ml-services.md#what-is-recorded).

### La tarjeta Voice de un agent { #an-agents-voice-card }

La pestaña **Build** de un agent tiene una tarjeta **Voice** después de los
ajustes del modelo, con dos pestañas: **Voice calls** y **Dictation**.

**Dictation** contiene **Transcribe with a provider**. Encendido, el micrófono
del chat envía la grabación a un provider: **This agent's own** (el
predeterminado) elige un par del catálogo y la clave con la que enviarlo - una
clave de API de ese provider que puedas ver, porque publicar se la presta a todo
el que pueda ejecutar el agent - y, hasta que elijas una, se usa el
predeterminado de la organización, nombrado. **Organization's** mantiene el
provider, el modelo y la clave de la organización. Apagado, o sin clave con la
que enviarla, transcribe el navegador, lo que no cuesta nada.

El idioma se elige aparte: heredar el de la organización o fijar uno - así un
agent en polaco puede conservar el provider y la clave de la organización. La
tarjeta forma parte de la spec, se guarda con el borrador y está activa en cuanto
se publica el agent, y se aplica al [dictado](#dictation) hacia este agent y a
los mensajes de voz que heredan sus bots de canal.
[El orden](ml-services.md#which-engine-a-recording-reaches) cuenta el resto.

### Llamadas de voz { #voice-calls }

Una [llamada de voz](voice.md) es una conversación hablada con un agent
publicado: hablas, responde en voz alta y puedes interrumpirlo. Las llamadas se
activan en el agent; la organización no tiene ajustes de llamadas.

- **La tarjeta Voice del agent**, en su pestaña **Voice calls**: el provider y
  el modelo de la llamada (para Azure, el nombre del deployment y su modelo
  base), la clave, la voz con un botón de **reproducir** para oírla, el idioma
  hablado (o **Follow the caller**), la **Longest call** (10 minutos si no se
  fija, 50 como máximo) y las **Instructions for calls**. La tarjeta lista lo que
  el agent [pasa a su modelo de texto](voice.md#handing-work-off) en las
  llamadas, dice que los guardrails no pueden filtrar las palabras habladas antes
  de que se oigan y que las llamadas se registran como texto sin guardar audio.
  Entra en vigor cuando se publica el agent.
- **El interruptor Voice calls de un embed**, en los formularios del widget y de
  la página alojada - mira [Canales](channels.md#voice-calls-on-a-widget-or-a-hosted-page).

Antes de ofrecer una llamada, la consola pregunta si este agent puede atenderla
(`GET /agents/{id}/voice`), para que nadie conceda el micrófono solo para ser
rechazado. La respuesta dice qué falta: ninguna voz configurada en el agent, el
modelo ya no se ofrece, o no hay clave.

El **botón de llamada** ocupa en el compositor del chat el lugar de Enviar
mientras el cuadro está vacío - al escribir algo vuelve Enviar -, en cada agent. Cuando este agent no puede atender una llamada aparece tachado, y al
pasar por encima, enfocarlo o pulsarlo dice por qué. Quien puede editar el agent
recibe **Open in the Agent Builder**, que abre su tarjeta Voice en la pestaña de
llamadas; a cualquier otra persona se le dice que pregunte a quien pueda.

Durante una llamada flota una **píldora** sobre el compositor, que se queda como
estaba, borrador y adjuntos incluidos: lo que hace la llamada, su tiempo, una
forma de onda de ambas voces, pulsar para hablar, silenciar y **End call**. Solo
End call termina una llamada; abrir otra conversación o un chat nuevo la cuelga.
Por defecto se habla sin manos; **pulsar para hablar** (mantener el botón o la
barra espaciadora) es una elección que recuerda tu navegador. Con movimiento
reducido, un medidor de nivel escalonado sustituye a la forma de onda.

Una llamada pasa por estados que la píldora nombra: conectando, escuchando,
hablas tú, pensando, habla el agent, interrumpido, trabajando con una
herramienta, esperando tu aprobación, una aprobación que no puedes dar, casi sin
tiempo y terminada - por ti, por un límite, una conexión caída o un fallo.

La llamada ocurre en la conversación: cada turno se dibuja como el mensaje en
que se convertirá, creciendo palabra a palabra mientras se habla, un lector de
pantalla oye cada línea cuando es definitiva, y el mensaje guardado ocupa su
lugar sin que nada se mueva, así que la llamada queda en tu historial y puedes
seguir escribiendo. Mientras el agent piensa o ejecuta una herramienta, la
conversación lo dice donde aparecerá su respuesta.

Las **aprobaciones** se deciden en la llamada: una tarjeta en la conversación
muestra la herramienta, sus argumentos exactos y lo que se te oyó decir, con una
cuenta atrás de 60 segundos. Solo sus botones deciden; decir "sí" no aprueba
nada. Sin `approvals:decide`, la tarjeta dice que la herramienta necesita una
aprobación que no puedes dar por voz y ofrece terminar la llamada y seguir por
texto.

Las **preguntas** que hace el agent aparecen como la tarjeta de pregunta
del chat, también leídas en voz alta: toca una respuesta o simplemente dila. El
trabajo que el agent [pasa a su modelo de texto](voice.md#handing-work-off)
muestra cada paso mientras se ejecuta, y los pasos quedan después en el turno.
Los **límites** se dicen en voz alta: un minuto antes de que acabe la llamada más
larga se te avisa, y cuando se agota el tiempo o el budget el agent dice una
frase y la llamada termina.

Una **franja sobre el compositor** señala lo que te necesita: la petición del
micrófono, una aprobación pendiente (con **Show card**), el último minuto, un
límite que termina la llamada, una reconexión o cómo funciona pulsar para
hablar. Cuando la llamada termina, una tarjeta en la conversación dice cuánto
duró y cuántos turnos se guardaron, o qué límite la terminó, con **Call again**.
Una llamada que no llegó a empezar dice por qué sobre el compositor, con **Try
again**.

En **Activity**, una llamada es una fila con una insignia de micrófono, y el
filtro de tipo (**Text** o **Voice calls**) se limita a las llamadas; una llamada
que se reconectó sigue siendo una fila, con el tiempo y el coste de todas sus
conexiones sumados. La tarjeta de panel **Voice minutes**, en la banda de Uso
para quien tenga `runs:view`, muestra los minutos de llamada y las llamadas del
periodo y los tres agents principales.

## Para qué sirve cada área { #what-each-area-is-for }

La barra lateral los agrupa. **Build** reúne Agents, Routines, Apps y Activity;
**Knowledge** reúne Knowledge bases, Documents, Skills y Context. Dos grupos se
pliegan a su título hasta que los abres, porque se configuran una vez y se visitan
poco: **Connections** (MCP servers, Channels, Remote agents, Vault, Sandboxes) y
**Organization** (Organizations, Groups). Un grupo plegado se abre solo en
cualquier página que le pertenezca, y se queda como lo dejaste.

| Área | Contiene | Lee |
|---|---|---|
| **Agents** | El catálogo, el Builder, las versiones, el uso compartido, las pruebas, la actividad | [Tu primer agent](first-agent.md) |
| **Chat** | Hablar con un agent publicado | [Superficies](channels.md) |
| **Knowledge** | Colecciones, documentos, fuentes de sincronización, ajustes de ingesta | [Procesamiento de archivos](file-processing.md) |
| **Skills** | Procedimientos escritos que un agent carga cuando hacen falta | [Skills](skills.md) |
| **Context** | Conocimiento permanente ligado a muchos agents | [Archivos de contexto](context.md) |
| **Routines** | Horarios y disparadores por evento | [Disparadores](triggers.md) |
| **Runs** | Qué se ejecutó, cuánto costó, qué tocó, si falló | [Governance](governance.md#audit) |
| **Documents** | Todos los archivos que los agents guardan para ti: lo que adjuntaste y lo que escribieron | [La sandbox](sandbox.md#what-the-file-browser-shows-and-what-it-leaves-out) |
| **Sandboxes** | Dónde ejecutan código los agents: hosts, sesiones en curso, política | [La sandbox](sandbox.md) |
| **MCP servers** | Conexiones a herramientas externas, personales y de toda la organización | [MCP](mcp.md) |
| **Channels** | Bots de Slack, Teams, Telegram y Mattermost, widgets, páginas alojadas | [Superficies](channels.md) |
| **Remote agents** | Agents de otros proveedores, registrados por su agent card de A2A, en los que delegan los agents | [Capabilities](reference/capabilities.md#remote-agents) |
| **Vault** | Credenciales, selladas por organización | [Secretos](secrets.md) |
| **Organizations** | Miembros, roles, invitaciones | [Permisos](permissions.md) |
| **Settings** | Providers, valores de ingesta por defecto, notificaciones, tu propio perfil | [Configuración](configuration.md) |
| **Admin** | El despliegue en sí: usuarios, inquilinos, sistema, jobs en segundo plano, ajustes del despliegue | [El despliegue](deployment.md) |

El catálogo de **Agents** se puede filtrar por **category** y **tag** — las
etiquetas editables y locales a la organización que se muestran en la tarjeta de
cada agent. Cada filtro es un menú de las etiquetas de los agents que puedes ver;
marca varias para ampliarlo. Las categories y los tags de un agent los mantienes desde su página
de detalle, junto a los controles del avatar, y el cambio surte efecto al
momento, sin publicar una nueva versión.

## Idiomas { #languages }

La consola habla inglés, polaco y alemán, en su totalidad salvo las páginas
legales, que siguen en inglés. La primera tarjeta del recorrido ofrece los tres, y
el menú de la cuenta cambia el idioma en cualquier momento; la elección se guarda
en tu cuenta, así que la consola se abre en él en cada dispositivo en el que
inicias sesión. También puedes pedírselo a un agent - "cambia a inglés" - y la
página cambia mientras responde, sin recargar. Todos los agents responden en él
salvo que escribas en otro idioma.

Las palabras del producto - agent, skill, run, budget, MCP y el
resto de la lista de [traducir](howto/translate.md) - siguen en inglés en todos
los idiomas.

La misma tarjeta pregunta a qué te dedicas, y **Settings → Profile** guarda el
resto de lo que los agents saben de ti: tu rol, en qué trabajas y tu zona horaria.
Cada agent los lee al empezar un run, así que nunca los repites en un chat; «cada
lunes a las 9» son tus 9. La zona horaria se toma de tu navegador la primera vez
que inicias sesión, hasta que eliges una.

## El siguiente paso { #the-next-step }

Una página vacía porque aún no existe nada ofrece el camino para crear lo
primero: un agent, una rutina, algo compartido con un departamento. Crear un
skill, un archivo de contexto o una base de conocimiento termina con un aviso que
ofrece **Add to an agent** a quien pueda editar agents, para que lo creado llegue
a un agent sin pasar por el Builder.

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
- **Los cambios hechos en otro lugar llegan solos** — por la API, MCP o el
  asistente — y el Builder pregunta antes de reemplazar cambios sin guardar.
- **Los comandos de barra son tuyos**, incluidos los de serie, y puedes ocultar
  los que no uses.
- Una página que muestra "todavía nada" puede ser **una petición fallida**, no un
  recurso vacío.
