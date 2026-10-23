---
source_sha: "4b8832761f4a"
---

# Todas las pantallas de la consola { #every-screen-in-the-console }

Cada módulo de la consola, descrito y con su captura. Las imágenes siguen el tema en el que lees el sitio: cámbialo en la cabecera y cambian con él. Muestran una organización de demostración, Northwind Labs, cuya empresa, documentos y cifras son inventados; las conversaciones y la app publicada son runs reales de sus agents.

## Demo del producto { #product-demo }

La demo editada actual muestra el OSS Launch Planner: una tarea con un briefing de Notion e investigación en GitHub, una aplicación interactiva y un enlace para compartir. Se han eliminado los tiempos de espera; el informe contiene una instantánea de los datos.

<video src="https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953" controls muted playsinline style="width:100%"></video>

## Dónde aterrizas { #where-you-land }

### Dashboard { #dashboard }

Tu propia vista, la de la organización que se ordena, la de un grupo y - para un administrador del despliegue - la de todo el despliegue, elegidas arriba. Runs, gasto, salud de los servicios y calidad de las respuestas; cada tarjeta está protegida por el permiso que necesitan sus propios datos, así que una tarjeta cuya lectura principal no puedes hacer es una tarjeta que no se te ofrece.

![Dashboard](assets/screens/light/dashboard.webp#only-light)
![Dashboard](assets/screens/dark/dashboard.webp#only-dark)

### Chat { #chat }

Entra una hoja de cálculo, sale una página publicada. El agent leyó el CSV con Python, calculó las cifras, publicó un dashboard de ingresos como app y dijo qué cifras comprobó y cuáles estimó. Cada paso está en pantalla y se puede desplegar: lo que hizo una herramienta está en la conversación, no en un log que lee otra persona.

![Chat](assets/screens/light/chat.webp#only-light)
![Chat](assets/screens/dark/chat.webp#only-dark)

### Una llamada de voz { #a-voice-call }

El composer convertido en barra de llamada: lo que está haciendo la llamada, su tiempo frente al límite, una forma de onda de las dos voces, silenciar, push-to-talk y End. La conversación sigue por encima: subtítulos dentro del mensaje que se está diciendo, las herramientas que se ejecutan y una tarjeta de aprobación con los argumentos exactos y lo que se te oyó decir.

> **Captura pendiente — Una llamada de voz.**

## Construir un agent { #building-an-agent }

### Agents { #agents }

El catálogo. Cada agent lleva la versión que está en vivo, quién puede alcanzarlo y si hay un borrador esperando. Un agent es configuración, no código — por eso esta lista la puede editar cualquiera que sepa la respuesta.

![Agents](assets/screens/light/agents.webp#only-light)
![Agents](assets/screens/dark/agents.webp#only-dark)

### Agent templates { #agent-templates }

Templates por sector, sobre el catálogo. Instalar uno crea un borrador que tú terminas y publicas; hasta que lo haces no se ejecuta nada.

![Agent templates](assets/screens/light/agent-templates.webp#only-light)
![Agent templates](assets/screens/dark/agent-templates.webp#only-dark)

### Skills { #skills }

Conocimiento escrito una vez y compartido por cada agent vinculado a él — cómo se gestionan las devoluciones, cuál es el estilo de la casa. Edítalo aquí y cada agent vinculado a él estará al día en su siguiente run.

![Skills](assets/screens/light/skills.webp#only-light)
![Skills](assets/screens/dark/skills.webp#only-dark)

### Skill gallery { #skill-gallery }

Skills por sector. Instalar copia uno en tu organización, donde puedes editarlo — una copia, para que el origen no pueda cambiar lo que dicen tus agents.

![Skill gallery](assets/screens/light/skill-gallery.webp#only-light)
![Skill gallery](assets/screens/dark/skill-gallery.webp#only-dark)

### Un skill { #one-skill }

Abierto para editar, con su categoría. El nombre al que se refiere el modelo queda fijado al crearlo y no puede cambiar; todo lo demás de aquí sí.

![Un skill](assets/screens/light/skill-detail.webp#only-light)
![Un skill](assets/screens/dark/skill-detail.webp#only-dark)

### Context { #context }

Contexto permanente del que cada agent puede tirar — un glosario, una política, una voz de marca. Inyectado en el prompt o leído bajo demanda, y actualizado en el momento en que lo editas.

![Context](assets/screens/light/context.webp#only-light)
![Context](assets/screens/dark/context.webp#only-dark)

## Dentro de un agent { #inside-one-agent }

El Builder, pestaña por pestaña.

### Build { #build }

Instrucciones, modelo y endpoint. El comportamiento vive aquí en lugar de en el código, en Markdown que el modelo lee como estructura — y la cabecera lleva `published` junto a `Draft differs from v40`, que es justo el objetivo: editar no despliega.

![Build](assets/screens/light/agent-builder.webp#only-light)
![Build](assets/screens/dark/agent-builder.webp#only-dark)

### Toolbox { #toolbox }

Cada capability como un interruptor — búsqueda en el conocimiento, un navegador, Python en una sandbox, gráficas, delegación — y junto a cada una la puerta de aprobación por herramienta. La configuración solo alcanza lo que el código registró.

![Toolbox](assets/screens/light/agent-toolbox.webp#only-light)
![Toolbox](assets/screens/dark/agent-toolbox.webp#only-dark)

### MCP servers { #mcp-servers }

Qué conexiones puede alcanzar este agent, y cuáles de sus herramientas. La lista de la organización lo sigue limitando; un agent puede estrechar dentro de ella y no puede alcanzar más allá.

![MCP servers](assets/screens/light/agent-mcp.webp#only-light)
![MCP servers](assets/screens/dark/agent-mcp.webp#only-dark)

### Limits { #limits }

Un tope mensual y un techo de pasos. El tope se comprueba antes de cada petición al modelo, y el límite de pasos atrapa el otro desbocamiento — un bucle de herramientas que es barato por llamada y nunca termina.

![Limits](assets/screens/light/agent-limits.webp#only-light)
![Limits](assets/screens/dark/agent-limits.webp#only-dark)

### Availability { #availability }

Dónde responde este agent: el dashboard y la API siempre, más cualquier bot de chat vinculado aquí. Un agent se puede mencionar por `@handle` solo en los bots a los que está vinculado.

![Availability](assets/screens/light/agent-availability.webp#only-light)
![Availability](assets/screens/dark/agent-availability.webp#only-dark)

### Routines, en el agent { #routines-on-the-agent }

Lo que hace sin que nadie escriba, en esta misma pestaña — un horario que se puede pausar, o un disparador por evento.

![Routines, en el agent](assets/screens/light/agent-routines.webp#only-light)
![Routines, en el agent](assets/screens/dark/agent-routines.webp#only-dark)

### History { #history }

Cada versión que ha tenido este agent. La que estuvo en vivo en marzo sigue siendo legible, y eso es lo que convierte una vuelta atrás en una decisión y no en un proyecto de arqueología.

![History](assets/screens/light/agent-history.webp#only-light)
![History](assets/screens/dark/agent-history.webp#only-dark)

### Visual map { #visual-map }

El mismo agent como grafo: qué lo alcanza y hacia qué alcanza él. Una caja discontinua es algo a lo que no hay nada enganchado — un budget sin tope propio se lee como un hueco y no como un valor por defecto.

![Visual map](assets/screens/light/agent-map.webp#only-light)
![Visual map](assets/screens/dark/agent-map.webp#only-dark)

## Knowledge { #knowledge }

### Knowledge bases { #knowledge-bases }

Collections. Agrupa documentos relacionados en una y después elige en el chat qué collections puede buscar un agent.

![Knowledge bases](assets/screens/light/knowledge-bases.webp#only-light)
![Knowledge bases](assets/screens/dark/knowledge-bases.webp#only-dark)

### Una collection { #a-collection }

Sus documentos, el número de chunks de cada uno y todo lo que falló al ingerirse, con el motivo. Los límites de los chunks son contra lo que compara una búsqueda, así que un documento que se vuelve a subir tras un cambio de ajustes se vuelve a trocear.

![Una collection](assets/screens/light/knowledge-collection.webp#only-light)
![Una collection](assets/screens/dark/knowledge-collection.webp#only-dark)

### Parsing, por subida { #parsing-per-upload }

La elección que nadie más expone: **PyMuPDF**, **LiteParse** o **LlamaParse**, la estrategia de troceado, el tamaño de chunk y el solapamiento, el OCR y su idioma. Se fija en la collection y se puede sobrescribir en el siguiente archivo que añadas — porque una tarifa escaneada y un runbook en Markdown no quieren el mismo parser, y el equivocado es la diferencia entre una respuesta y una negativa.

![Parsing, por subida](assets/screens/light/kb-parse-options.webp#only-light)
![Parsing, por subida](assets/screens/dark/kb-parse-options.webp#only-dark)

## Qué ha pasado, y qué está esperando { #what-happened-and-what-is-waiting }

### Runs { #runs }

Cada run que ha hecho esta organización, con su estado, superficie, modelo, persona y coste. Un run es el proceso: arranca, se puede detener y deja un registro.

![Runs](assets/screens/light/activity.webp#only-light)
![Runs](assets/screens/dark/activity.webp#only-dark)

### Un run, abierto { #one-run-opened }

Tokens de entrada y de salida, coste con cuatro decimales, cuánto tardó y la línea de tiempo de cada turno y cada llamada a una herramienta. El chat en el que ocurrió está a un clic.

![Un run, abierto](assets/screens/light/run-detail.webp#only-light)
![Un run, abierto](assets/screens/dark/run-detail.webp#only-dark)

### Approvals { #approvals }

Todo lo que espera a una persona, con lo que el agent pretende hacer. Una aprobación se decide exactamente una vez — una segunda decisión sobre una ya zanjada se rechaza, y ese es el detalle que hace que la puerta valga la pena.

![Approvals](assets/screens/light/approvals.webp#only-light)
![Approvals](assets/screens/dark/approvals.webp#only-dark)

### Spend { #spend }

Lo que se gastó realmente, por periodo. Un budget se comprueba *antes* de la petición al modelo en lugar de sumarse después, así que un run que rompe uno se detiene a mitad de la respuesta y aun así registra su coste.

![Spend](assets/screens/light/spend.webp#only-light)
![Spend](assets/screens/dark/spend.webp#only-dark)

### Routines { #routines }

Lo que hacen los agents sin que nadie escriba — según un horario, o cuando llega un evento. Esos runs llevan budget, aprobación y auditoría como cualquier otro.

![Routines](assets/screens/light/routines.webp#only-light)
![Routines](assets/screens/dark/routines.webp#only-dark)

### Un nuevo disparador por evento { #a-new-event-trigger }

Nombrar el evento que arranca un run, sobre la lista de routines.

![Un nuevo disparador por evento](assets/screens/light/routine-event-trigger.webp#only-light)
![Un nuevo disparador por evento](assets/screens/dark/routine-event-trigger.webp#only-dark)

### Apps { #apps }

Páginas que publicaron los agents: informes, pequeños dashboards, resúmenes. Cada una conserva su enlace cuando el agent la vuelve a publicar, y sus versiones anteriores siguen siendo legibles.

![Apps](assets/screens/light/apps.webp#only-light)
![Apps](assets/screens/dark/apps.webp#only-dark)

### Una app { #one-app }

El dashboard de ingresos del chat de arriba, abierto. Es privado hasta que alguien lo comparte, y un enlace público es una decisión aparte que se puede retirar.

![Una app](assets/screens/light/app-detail.webp#only-light)
![Una app](assets/screens/dark/app-detail.webp#only-dark)

## La organización { #the-organization }

### Organizations { #organizations }

Cambia entre ellas, gestiona miembros y crea otras nuevas. La autoridad dentro de una organización es una fila de membresía más el catálogo de permisos — no hay una columna de rol en un usuario.

![Organizations](assets/screens/light/organizations.webp#only-light)
![Organizations](assets/screens/dark/organizations.webp#only-dark)

### Members { #members }

Las personas de una organización y sus roles, con el límite mensual que comparten todos sus agents y si una conversación puede omitir sus approvals.

![Members](assets/screens/light/members.webp#only-light)
![Members](assets/screens/dark/members.webp#only-dark)

### Roles { #roles }

Lo que puede hacer cada rol, como la matriz que define el código. Compartir un recurso concreto puede ampliar el acceso más allá del rol; nunca lo reduce.

![Roles](assets/screens/light/roles.webp#only-light)
![Roles](assets/screens/dark/roles.webp#only-dark)

### Groups { #groups }

Departamentos y equipos. Comparte un agent, una base de conocimiento, un skill o un archivo de contexto con un grupo y todos sus miembros podrán usarlo; quien esté fuera, no.

![Groups](assets/screens/light/groups.webp#only-light)
![Groups](assets/screens/dark/groups.webp#only-dark)

### Vault { #vault }

Cada clave que ha guardado esta organización, sellada por inquilino. Reemplazable, nunca legible otra vez; y rotar una es invisible para un agent publicado, que referencia el secreto y no su valor.

![Vault](assets/screens/light/vault.webp#only-light)
![Vault](assets/screens/dark/vault.webp#only-dark)

### MCP servers { #mcp-servers }

Conecta cualquier servidor MCP por URL y sus herramientas se convierten en interruptores en el Builder. Conéctalo para la organización y cualquier agent podrá usarlo; conéctalo para ti y se queda en tu propio chat.

![MCP servers](assets/screens/light/mcp-servers.webp#only-light)
![MCP servers](assets/screens/dark/mcp-servers.webp#only-dark)

### Channels { #channels }

Las plataformas de chat en las que responde esta organización — Slack, Teams, Telegram, Mattermost. Un bot sirve a cada agent vinculado a él, y el vínculo se hace en la pestaña Availability de ese agent.

![Channels](assets/screens/light/channels.webp#only-light)
![Channels](assets/screens/dark/channels.webp#only-dark)

### Sandboxes { #sandboxes }

Donde los agents de esta organización ejecutan comandos de shell y guardan archivos. Un agent nombra una conexión por id, así que mudarse a otro host es una edición aquí en lugar de una republicación de cada agent.

![Sandboxes](assets/screens/light/sandboxes.webp#only-light)
![Sandboxes](assets/screens/dark/sandboxes.webp#only-dark)

### Documents { #documents }

Los archivos que los agents guardan para ti. Un workspace es espacio de trabajo temporal — se borra junto con la conversación a la que pertenece, y no es un sitio donde guardar nada duradero.

![Documents](assets/screens/light/documents.webp#only-light)
![Documents](assets/screens/dark/documents.webp#only-dark)

### Tus ajustes { #your-settings }

Tu perfil y tu cuenta, los slash commands, la memoria, los inicios de sesión que el agent del navegador guarda para ti, las notificaciones, las claves de API, los clientes MCP y el Architect: una pestaña para cada uno.

![Tus ajustes](assets/screens/light/settings.webp#only-light)
![Tus ajustes](assets/screens/dark/settings.webp#only-dark)

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

Base de datos, Redis, el almacén vectorial, el acceso a los modelos y los trabajos programados — las mismas comprobaciones que ejecuta `agenticos cmd doctor`, en una página.

![System](assets/screens/light/admin-system.webp#only-light)
![System](assets/screens/dark/admin-system.webp#only-dark)

### Deployment { #deployment }

La identidad y la política propias de este despliegue: registro, invitaciones, avisos y lo que encuentra quien lo visita por primera vez.

![Deployment](assets/screens/light/admin-deployment.webp#only-light)
![Deployment](assets/screens/dark/admin-deployment.webp#only-dark)

## Lo que todavía no está aquí { #what-is-not-here-yet }

Aún no hay capturas del inicio de sesión, la incorporación inicial ni el recorrido dentro del producto.

## Resumen { #recap }

Cada pantalla aparece en ambos temas, desde una única organización de demostración. `docs/assets/screens/capture.mjs` las vuelve a capturar todas contra cualquier despliegue en marcha, así que una pantalla que cambia es una nueva ejecución y no una imagen hecha a mano.
