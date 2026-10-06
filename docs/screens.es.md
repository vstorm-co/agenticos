---
source_sha: "1048cece0606"
---

# Todas las pantallas de la consola { #every-screen-in-the-console }

A continuación se describen los módulos de la consola. Se han retirado las capturas de la interfaz anterior; los marcadores se sustituirán por capturas nuevas en los temas claro y oscuro.

## Demo del producto { #product-demo }

La demo editada actual muestra el OSS Launch Planner: una tarea con un briefing de Notion e investigación en GitHub, un artefacto interactivo y un enlace para compartir. Se han eliminado los tiempos de espera; el informe contiene una instantánea de los datos.

<video src="https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953" controls muted playsinline style="width:100%"></video>

## Dónde aterrizas { #where-you-land }

### Dashboard { #dashboard }

Widgets que puedes ordenar, primero todo el despliegue y después esta organización. Runs, gasto, salud de los servicios y calidad de las respuestas; cada tarjeta está protegida por el permiso que necesitan sus propios datos, así que una tarjeta cuya lectura principal no puedes hacer es una tarjeta que no se te ofrece.

> **Captura pendiente — Dashboard.**

### Chat, a mitad de run { #chat-mid-run }

El agent pensando, y después los comandos de shell que realmente ejecutó en la sandbox, cada uno desplegable. Aquí la transparencia es el producto: lo que hizo una herramienta está en pantalla, no en un log que pueda leer otra persona.

> **Captura pendiente — Chat, a mitad de run.**

## Construir un agent { #building-an-agent }

### Agents { #agents }

El catálogo. Cada agent lleva la versión que está en vivo, quién puede alcanzarlo y si hay un borrador esperando. Un agent es configuración, no código — por eso esta lista la puede editar cualquiera que sepa la respuesta.

> **Captura pendiente — Agents.**

### Agent templates { #agent-templates }

Templates por sector, sobre el catálogo. Instalar uno crea un borrador que tú terminas y publicas; hasta que lo haces no se ejecuta nada.

> **Captura pendiente — Agent templates.**

### Skills { #skills }

Conocimiento escrito una vez y compartido por cada agent vinculado a él — cómo se gestionan las devoluciones, cuál es el estilo de la casa. Edítalo aquí y cada agent vinculado a él estará al día en su siguiente run.

> **Captura pendiente — Skills.**

### Skill gallery { #skill-gallery }

Skills por sector. Instalar copia uno en tu organización, donde puedes editarlo — una copia, para que el origen no pueda cambiar lo que dicen tus agents.

> **Captura pendiente — Skill gallery.**

### Un skill { #one-skill }

Abierto para editar, con su categoría. El nombre al que se refiere el modelo queda fijado al crearlo y no puede cambiar; todo lo demás de aquí sí.

> **Captura pendiente — Un skill.**

### Context { #context }

Contexto permanente del que cada agent puede tirar — un glosario, una política, una voz de marca. Inyectado en el prompt o leído bajo demanda, y actualizado en el momento en que lo editas.

> **Captura pendiente — Context.**

## Dentro de un agent { #inside-one-agent }

El Builder, pestaña por pestaña. Las nuevas capturas de la interfaz actual están pendientes.

### Build { #build }

Instrucciones, modelo y endpoint. El comportamiento vive aquí en lugar de en el código, en Markdown que el modelo lee como estructura — y la cabecera lleva `published` junto a `Draft differs from v40`, que es justo el objetivo: editar no despliega.

> **Captura pendiente — Build.**

### Toolbox { #toolbox }

Cada capability como un interruptor — búsqueda en el conocimiento, un navegador, Python en una sandbox, gráficas, delegación — y junto a cada una la puerta de aprobación por herramienta. La configuración solo alcanza lo que el código registró.

> **Captura pendiente — Toolbox.**

### MCP servers { #mcp-servers }

Qué conexiones puede alcanzar este agent, y cuáles de sus herramientas. La lista de la organización lo sigue limitando; un agent puede estrechar dentro de ella y no puede alcanzar más allá.

> **Captura pendiente — MCP servers.**

### Limits { #limits }

Un tope mensual y un techo de pasos. El tope se comprueba antes de cada petición al modelo, y el límite de pasos atrapa el otro desbocamiento — un bucle de herramientas que es barato por llamada y nunca termina.

> **Captura pendiente — Limits.**

### Availability { #availability }

Dónde responde este agent: el dashboard y la API siempre, más cualquier bot de chat vinculado aquí. Un agent se puede mencionar por `@handle` solo en los bots a los que está vinculado.

> **Captura pendiente — Availability.**

### Routines, en el agent { #routines-on-the-agent }

Lo que hace sin que nadie escriba, en esta misma pestaña — un horario que se puede pausar, o un disparador por evento.

> **Captura pendiente — Routines, en el agent.**

### History { #history }

Cada versión que ha tenido este agent. La que estuvo en vivo en marzo sigue siendo legible, y eso es lo que convierte una vuelta atrás en una decisión y no en un proyecto de arqueología.

> **Captura pendiente — History.**

### Visual map { #visual-map }

El mismo agent como grafo: qué lo alcanza y hacia qué alcanza él. Una caja discontinua es algo a lo que no hay nada enganchado — un budget sin tope propio se lee como un hueco y no como un valor por defecto.

> **Captura pendiente — Visual map.**
## Knowledge { #knowledge }

### Knowledge bases { #knowledge-bases }

Collections. Agrupa documentos relacionados en una y después elige en el chat qué collections puede buscar un agent.

> **Captura pendiente — Knowledge bases.**

### Una collection { #a-collection }

Sus documentos, el número de chunks de cada uno y todo lo que falló al ingerirse, con el motivo. Los límites de los chunks son contra lo que compara una búsqueda, así que un documento que se vuelve a subir tras un cambio de ajustes se vuelve a trocear.

> **Captura pendiente — Una collection.**

### Parsing, por subida { #parsing-per-upload }

La elección que nadie más expone: **PyMuPDF**, **LiteParse** o **LlamaParse**, la estrategia de troceado, el tamaño de chunk y el solapamiento, el OCR y su idioma. Se fija en la collection y se puede sobrescribir en el siguiente archivo que añadas — porque una tarifa escaneada y un runbook en Markdown no quieren el mismo parser, y el equivocado es la diferencia entre una respuesta y una negativa.

> **Captura pendiente — Parsing, por subida.**

## Qué ha pasado, y qué está esperando { #what-happened-and-what-is-waiting }

### Runs { #runs }

Cada run que ha hecho esta organización, con su estado, superficie, modelo, persona y coste. Un run es el proceso: arranca, se puede detener y deja un registro.

> **Captura pendiente — Runs.**

### Un run, abierto { #one-run-opened }

Tokens de entrada y de salida, coste con cuatro decimales, cuánto tardó y la línea de tiempo de cada turno y cada llamada a una herramienta. El chat en el que ocurrió está a un clic.

> **Captura pendiente — Un run, abierto.**

### Approvals { #approvals }

Todo lo que espera a una persona, con lo que el agent pretende hacer. Una aprobación se decide exactamente una vez — una segunda decisión sobre una ya zanjada se rechaza, y ese es el detalle que hace que la puerta valga la pena.

> **Captura pendiente — Approvals.**

### Spend { #spend }

Lo que se gastó realmente, por periodo. Un budget se comprueba *antes* de la petición al modelo en lugar de sumarse después, así que un run que rompe uno se detiene a mitad de la respuesta y aun así registra su coste.

> **Captura pendiente — Spend.**

### Routines { #routines }

Lo que hacen los agents sin que nadie escriba — según un horario, o cuando llega un evento. Esos runs llevan budget, aprobación y auditoría como cualquier otro.

> **Captura pendiente — Routines.**

### Un nuevo disparador por evento { #a-new-event-trigger }

Nombrar el evento que arranca un run, sobre la lista de routines.

> **Captura pendiente — Un nuevo disparador por evento.**

## La organización { #the-organization }

### Organizations { #organizations }

Cambia entre ellas, gestiona miembros y crea otras nuevas. La autoridad dentro de una organización es una fila de membresía más el catálogo de permisos — no hay una columna de rol en un usuario.

> **Captura pendiente — Organizations.**

### Vault { #vault }

Cada clave que ha guardado esta organización, sellada por inquilino. Reemplazable, nunca legible otra vez; y rotar una es invisible para un agent publicado, que referencia el secreto y no su valor.

> **Captura pendiente — Vault.**

### MCP servers { #mcp-servers }

Conecta cualquier servidor MCP por URL y sus herramientas se convierten en interruptores en el Builder. Conéctalo para la organización y cualquier agent podrá usarlo; conéctalo para ti y se queda en tu propio chat.

> **Captura pendiente — MCP servers.**

### Channels { #channels }

Las plataformas de chat en las que responde esta organización — Slack, Telegram, Mattermost. Un bot sirve a cada agent vinculado a él, y el vínculo se hace en la pestaña Availability de ese agent.

> **Captura pendiente — Channels.**

### Sandboxes { #sandboxes }

Donde los agents de esta organización ejecutan comandos de shell y guardan archivos. Un agent nombra una conexión por id, así que mudarse a otro host es una edición aquí en lugar de una republicación de cada agent.

> **Captura pendiente — Sandboxes.**

### Workspaces { #workspaces }

Los archivos que los agents guardan para ti. Un workspace es espacio de trabajo temporal — se borra junto con la conversación a la que pertenece, y no es un sitio donde guardar nada duradero.

> **Captura pendiente — Workspaces.**

## Administración del despliegue { #deployment-administration }

### Users { #users }

Todo el que puede iniciar sesión en este despliegue, y el indicador de app-admin, que es independiente de cualquier rol de organización.

> **Captura pendiente — Users.**

### All organizations { #all-organizations }

Cada inquilino de este despliegue, con su owner, sus miembros y sus agents.

> **Captura pendiente — All organizations.**

### System { #system }

Base de datos, Redis, el almacén vectorial y el acceso a los modelos — las mismas comprobaciones que ejecuta `agenticos cmd doctor`, en una página.

> **Captura pendiente — System.**

### Deployment { #deployment }

La identidad y la política propias de este despliegue: registro, invitaciones, avisos y lo que encuentra quien lo visita por primera vez.

> **Captura pendiente — Deployment.**

## Lo que todavía no está aquí { #what-is-not-here-yet }

Están pendientes las nuevas capturas de la interfaz actual, incluidos el Builder, el inicio de sesión y la incorporación.

## Resumen { #recap }

El vídeo actual está disponible arriba. Los marcadores identifican las vistas pendientes de capturar; añade el mismo encuadre en los temas claro y oscuro.
