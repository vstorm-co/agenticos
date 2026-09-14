---
source_sha: "52c1284c9aae"
---

# Todas las pantallas de la consola { #every-screen-in-the-console }

Una página, cada módulo, descrito. Las capturas siguen el tema en el que estés
leyendo el sitio — cámbialo con el interruptor de la cabecera y cada imagen de
esta página cambia con él.

Capturadas el 1 de septiembre de 2026 desde un despliegue en marcha: 35
pantallas, 27 de ellas en los dos temas bajo `docs/assets/screens/`, con
nombres idénticos en `light/` y `dark/`. Las ocho pantallas del Builder son
solo oscuras, y lo dicen donde aparecen.

## El chat, en veinte segundos { #the-chat-in-twenty-seconds }

Un CSV soltado en la conversación, una frase de instrucción, y el agent escribe
Python, lo ejecuta en una sandbox y responde con gráficas que dibujó a partir de
los datos. Nada de esto se configuró para este archivo en particular.

<video src="../assets/screens/chat-live-demo.mp4" poster="../assets/screens/chat-live-demo-poster.webp" controls muted loop playsinline style="width:100%"></video>

## Dónde aterrizas { #where-you-land }

### Dashboard { #dashboard }

Widgets que puedes ordenar, primero todo el despliegue y después esta organización. Runs, gasto, salud de los servicios y calidad de las respuestas; cada tarjeta está protegida por el permiso que necesitan sus propios datos, así que una tarjeta cuya lectura principal no puedes hacer es una tarjeta que no se te ofrece.

![Dashboard](assets/screens/light/dashboard.webp#only-light)
![Dashboard](assets/screens/dark/dashboard.webp#only-dark)

### Chat, a mitad de run { #chat-mid-run }

El agent pensando, y después los comandos de shell que realmente ejecutó en la sandbox, cada uno desplegable. Aquí la transparencia es el producto: lo que hizo una herramienta está en pantalla, no en un log que pueda leer otra persona.

![Chat, a mitad de run](assets/screens/light/chat-sandbox-commands.webp#only-light)
![Chat, a mitad de run](assets/screens/dark/chat-sandbox-commands.webp#only-dark)

## Construir un agent { #building-an-agent }

### Agents { #agents }

El catálogo. Cada agent lleva la versión que está en vivo, quién puede alcanzarlo y si hay un borrador esperando. Un agent es configuración, no código — por eso esta lista la puede editar cualquiera que sepa la respuesta.

![Agents](assets/screens/light/agents.webp#only-light)
![Agents](assets/screens/dark/agents.webp#only-dark)

### Agent templates { #agent-templates }

Templates por sector, sobre el catálogo. Instalar uno crea un borrador que tú terminas y publicas; hasta que lo haces no se ejecuta nada.

![Agent templates](assets/screens/light/agents-templates-dialog.webp#only-light)
![Agent templates](assets/screens/dark/agents-templates-dialog.webp#only-dark)

### Skills { #skills }

Conocimiento escrito una vez y compartido por cada agent vinculado a él — cómo se gestionan las devoluciones, cuál es el estilo de la casa. Edítalo aquí y cada agent vinculado a él estará al día en su siguiente run.

![Skills](assets/screens/light/skills.webp#only-light)
![Skills](assets/screens/dark/skills.webp#only-dark)

### Skill gallery { #skill-gallery }

Skills por sector. Instalar copia uno en tu organización, donde puedes editarlo — una copia, para que el origen no pueda cambiar lo que dicen tus agents.

![Skill gallery](assets/screens/light/skills-gallery-dialog.webp#only-light)
![Skill gallery](assets/screens/dark/skills-gallery-dialog.webp#only-dark)

### Un skill { #one-skill }

Abierto para editar, con su categoría. El nombre al que se refiere el modelo queda fijado al crearlo y no puede cambiar; todo lo demás de aquí sí.

![Un skill](assets/screens/light/skill-detail.webp#only-light)
![Un skill](assets/screens/dark/skill-detail.webp#only-dark)

### Context { #context }

Contexto permanente del que cada agent puede tirar — un glosario, una política, una voz de marca. Inyectado en el prompt o leído bajo demanda, y actualizado en el momento en que lo editas.

![Context](assets/screens/light/context.webp#only-light)
![Context](assets/screens/dark/context.webp#only-dark)

## Dentro de un agent { #inside-one-agent }

El Builder, pestaña a pestaña. Estas ocho son **solo oscuras** — la mitad clara
no se ha capturado, así que, a diferencia de las demás pantallas de esta página,
no siguen tu paleta.

### Build { #build }

Instrucciones, modelo y endpoint. El comportamiento vive aquí en lugar de en el código, en Markdown que el modelo lee como estructura — y la cabecera lleva `published` junto a `Draft differs from v40`, que es justo el objetivo: editar no despliega.

![Build](assets/screens/dark/builder-build.webp)

### Toolbox { #toolbox }

Cada capability como un interruptor — búsqueda en el conocimiento, un navegador, Python en una sandbox, gráficas, delegación — y junto a cada una la puerta de aprobación por herramienta. La configuración solo alcanza lo que el código registró.

![Toolbox](assets/screens/dark/builder-toolbox.webp)

### MCP servers { #mcp-servers }

Qué conexiones puede alcanzar este agent, y cuáles de sus herramientas. La lista de la organización lo sigue limitando; un agent puede estrechar dentro de ella y no puede alcanzar más allá.

![MCP servers](assets/screens/dark/builder-mcp-servers.webp)

### Limits { #limits }

Un tope mensual y un techo de pasos. El tope se comprueba antes de cada petición al modelo, y el límite de pasos atrapa el otro desbocamiento — un bucle de herramientas que es barato por llamada y nunca termina.

![Limits](assets/screens/dark/builder-limits.webp)

### Availability { #availability }

Dónde responde este agent: el dashboard y la API siempre, más cualquier bot de chat vinculado aquí. Un agent se puede mencionar por `@handle` solo en los bots a los que está vinculado.

![Availability](assets/screens/dark/builder-availability.webp)

### Routines, en el agent { #routines-on-the-agent }

Lo que hace sin que nadie escriba, en esta misma pestaña — un horario que se puede pausar, o un disparador por evento.

![Routines, en el agent](assets/screens/dark/builder-routines.webp)

### History { #history }

Cada versión que ha tenido este agent. La que estuvo en vivo en marzo sigue siendo legible, y eso es lo que convierte una vuelta atrás en una decisión y no en un proyecto de arqueología.

![History](assets/screens/dark/builder-history.webp)

### Visual map { #visual-map }

El mismo agent como grafo: qué lo alcanza y hacia qué alcanza él. Una caja discontinua es algo a lo que no hay nada enganchado — un budget sin tope propio se lee como un hueco y no como un valor por defecto.

![Visual map](assets/screens/dark/builder-visual-map.webp)
## Knowledge { #knowledge }

### Knowledge bases { #knowledge-bases }

Collections. Agrupa documentos relacionados en una y después elige en el chat qué collections puede buscar un agent.

![Knowledge bases](assets/screens/light/knowledge-bases.webp#only-light)
![Knowledge bases](assets/screens/dark/knowledge-bases.webp#only-dark)

### Una collection { #a-collection }

Sus documentos, el número de chunks de cada uno y todo lo que falló al ingerirse, con el motivo. Los límites de los chunks son contra lo que compara una búsqueda, así que un documento que se vuelve a subir tras un cambio de ajustes se vuelve a trocear.

![Una collection](assets/screens/light/knowledge-base-detail.webp#only-light)
![Una collection](assets/screens/dark/knowledge-base-detail.webp#only-dark)

### Parsing, por subida { #parsing-per-upload }

La elección que nadie más expone: **PyMuPDF**, **LiteParse** o **LlamaParse**, la estrategia de troceado, el tamaño de chunk y el solapamiento, el OCR y su idioma. Se fija en la collection y se puede sobrescribir en el siguiente archivo que añadas — porque una tarifa escaneada y un runbook en Markdown no quieren el mismo parser, y el equivocado es la diferencia entre una respuesta y una negativa.

![Parsing, por subida](assets/screens/light/knowledge-base-upload-parsing-dialog.webp#only-light)
![Parsing, por subida](assets/screens/dark/knowledge-base-upload-parsing-dialog.webp#only-dark)

## Qué ha pasado, y qué está esperando { #what-happened-and-what-is-waiting }

### Runs { #runs }

Cada run que ha hecho esta organización, con su estado, superficie, modelo, persona y coste. Un run es el proceso: arranca, se puede detener y deja un registro.

![Runs](assets/screens/light/activity-runs.webp#only-light)
![Runs](assets/screens/dark/activity-runs.webp#only-dark)

### Un run, abierto { #one-run-opened }

Tokens de entrada y de salida, coste con cuatro decimales, cuánto tardó y la línea de tiempo de cada turno y cada llamada a una herramienta. El chat en el que ocurrió está a un clic.

![Un run, abierto](assets/screens/light/activity-run-detail.webp#only-light)
![Un run, abierto](assets/screens/dark/activity-run-detail.webp#only-dark)

### Approvals { #approvals }

Todo lo que espera a una persona, con lo que el agent pretende hacer. Una aprobación se decide exactamente una vez — una segunda decisión sobre una ya zanjada se rechaza, y ese es el detalle que hace que la puerta valga la pena.

![Approvals](assets/screens/light/activity-approvals.webp#only-light)
![Approvals](assets/screens/dark/activity-approvals.webp#only-dark)

### Spend { #spend }

Lo que se gastó realmente, por periodo. Un budget se comprueba *antes* de la petición al modelo en lugar de sumarse después, así que un run que rompe uno se detiene a mitad de la respuesta y aun así registra su coste.

![Spend](assets/screens/light/activity-spend.webp#only-light)
![Spend](assets/screens/dark/activity-spend.webp#only-dark)

### Routines { #routines }

Lo que hacen los agents sin que nadie escriba — según un horario, o cuando llega un evento. Esos runs llevan budget, aprobación y auditoría como cualquier otro.

![Routines](assets/screens/light/routines.webp#only-light)
![Routines](assets/screens/dark/routines.webp#only-dark)

### Un nuevo disparador por evento { #a-new-event-trigger }

Nombrar el evento que arranca un run, sobre la lista de routines.

![Un nuevo disparador por evento](assets/screens/light/routines-event-trigger-dialog.webp#only-light)
![Un nuevo disparador por evento](assets/screens/dark/routines-event-trigger-dialog.webp#only-dark)

## La organización { #the-organization }

### Organizations { #organizations }

Cambia entre ellas, gestiona miembros y crea otras nuevas. La autoridad dentro de una organización es una fila de membresía más el catálogo de permisos — no hay una columna de rol en un usuario.

![Organizations](assets/screens/light/organizations.webp#only-light)
![Organizations](assets/screens/dark/organizations.webp#only-dark)

### Vault { #vault }

Cada clave que ha guardado esta organización, sellada por inquilino. Reemplazable, nunca legible otra vez; y rotar una es invisible para un agent publicado, que referencia el secreto y no su valor.

![Vault](assets/screens/light/vault.webp#only-light)
![Vault](assets/screens/dark/vault.webp#only-dark)

### MCP servers { #mcp-servers }

Conecta cualquier servidor MCP por URL y sus herramientas se convierten en interruptores en el Builder. Conéctalo para la organización y cualquier agent podrá usarlo; conéctalo para ti y se queda en tu propio chat.

![MCP servers](assets/screens/light/mcp-servers.webp#only-light)
![MCP servers](assets/screens/dark/mcp-servers.webp#only-dark)

### Channels { #channels }

Las plataformas de chat en las que responde esta organización — Slack, Telegram, Mattermost. Un bot sirve a cada agent vinculado a él, y el vínculo se hace en la pestaña Availability de ese agent.

![Channels](assets/screens/light/channels.webp#only-light)
![Channels](assets/screens/dark/channels.webp#only-dark)

### Sandboxes { #sandboxes }

Donde los agents de esta organización ejecutan comandos de shell y guardan archivos. Un agent nombra una conexión por id, así que mudarse a otro host es una edición aquí en lugar de una republicación de cada agent.

![Sandboxes](assets/screens/light/sandboxes.webp#only-light)
![Sandboxes](assets/screens/dark/sandboxes.webp#only-dark)

### Workspaces { #workspaces }

Los archivos que los agents guardan para ti. Un workspace es espacio de trabajo temporal — se borra junto con la conversación a la que pertenece, y no es un sitio donde guardar nada duradero.

![Workspaces](assets/screens/light/workspaces.webp#only-light)
![Workspaces](assets/screens/dark/workspaces.webp#only-dark)

## Administración del despliegue { #deployment-administration }

### Users { #users }

Todo el que puede iniciar sesión en este despliegue, y el indicador de app-admin, que es independiente de cualquier rol de organización.

![Users](assets/screens/light/admin-users.webp#only-light)
![Users](assets/screens/dark/admin-users.webp#only-dark)

### All organizations { #all-organizations }

Cada inquilino de este despliegue, con su owner, sus miembros y sus agents.

![All organizations](assets/screens/light/admin-organizations.webp#only-light)
![All organizations](assets/screens/dark/admin-organizations.webp#only-dark)

### System { #system }

Base de datos, Redis, el almacén vectorial y el acceso a los modelos — las mismas comprobaciones que ejecuta `agenticos cmd doctor`, en una página.

![System](assets/screens/light/admin-system.webp#only-light)
![System](assets/screens/dark/admin-system.webp#only-dark)

### Deployment { #deployment }

La identidad y la política propias de este despliegue: registro, invitaciones, avisos y lo que encuentra quien lo visita por primera vez.

![Deployment](assets/screens/light/admin-deployment.webp#only-light)
![Deployment](assets/screens/dark/admin-deployment.webp#only-dark)

## Lo que todavía no está aquí { #what-is-not-here-yet }

- **La mitad clara del Builder** — las ocho capturas de arriba existen solo en
  oscuro.
- **El inicio de sesión y el onboarding**, que es lo que encuentra realmente
  quien visita esto por primera vez.

## Resumen { #recap }

- 27 módulos tienen los dos temas en `docs/assets/screens/`, con el mismo
  nombre; las ocho pantallas del Builder son solo oscuras.
- En este sitio una imagen se escribe dos veces, con `#only-light` y
  `#only-dark`; Material muestra la que coincide con la paleta del lector.
- En el README el mismo par va en un `<picture>` con
  `media="(prefers-color-scheme: dark)"`, que es como lo hace GitHub.
- Parsing es el ajuste que vale la pena conocer antes de subir nada: el parser y
  el tamaño de chunk deciden si una tabla se puede responder siquiera.
