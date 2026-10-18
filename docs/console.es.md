---
source_sha: "27d973f8560b"
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
| **Usage & cost** | Qué agents se usan, gasto, cuándo ocurre el trabajo, de dónde vienen los runs, mezcla de modelos, latencia, calidad de respuesta, quién lo usa |

Quien construye agents ve además **Get started** encima de las bandas hasta
completar cada paso: crear un agent, publicarlo, darle una base de conocimiento,
añadir departamentos, invitar a alguien del equipo y - quien pueda - poner un agent
en una app de chat. Cada paso se marca a partir de lo que existe, se haya hecho
donde se haya hecho; cerrar la tarjeta la oculta en ese navegador.

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

## El asistente { #the-assistant }

Cada página tiene al **Architect** en su esquina inferior derecha: un agent que
toda organización recibe sin instalar nada, compartido con todos los que pueden
ejecutar agents (`agents:run`). Está vinculado al
[servidor MCP de la propia plataforma](mcp.md#agenticos-as-an-mcp-server).
Pregúntale qué agents responden dudas de reembolsos, por qué falló el run de anoche
o qué hay en una base de conocimiento.

Pídele que esboce un agent o invite a un
compañero, y primero te mostrará lo que apruebas: el borrador
de un agent como el propio borrador - dónde se crea, su nombre, qué puede hacer y
sus instrucciones - y todo lo demás como la llamada exacta. Actúa con
tus permisos, así que encuentra y hace lo que tú podrías, y nada más. Su coste
cuenta como el de cualquier agent.

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
notas sobre ti entre conversaciones, te dice cuánto cuestan tus agents y puede
deshacer un borrador de agent que creó por error — nada más. Además de las
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

## Para qué sirve cada área { #what-each-area-is-for }

La barra lateral los agrupa. **Build** reúne Agents, Routines, Apps y Activity;
**Knowledge** reúne Knowledge bases, Documents, Skills y Context. Dos grupos se
pliegan a su título hasta que los abres, porque se configuran una vez y se visitan
poco: **Connections** (MCP servers, Channels, Vault, Sandboxes) y
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

## Idiomas { #languages }

La consola habla inglés, polaco y alemán, en su totalidad salvo las páginas
legales, que siguen en inglés. La primera tarjeta del recorrido ofrece los tres, y
el menú de la cuenta cambia el idioma en cualquier momento; la elección se recuerda
en el navegador. Las palabras del producto - agent, skill, run, budget, MCP y el
resto de la lista de [traducir](howto/translate.md) - siguen en inglés en todos
los idiomas.

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

- El dashboard son **treinta y seis widgets** que ordenas tú, guardados por
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
