---
source_sha: "12c6776e073b"
---

# Todas las pantallas de la consola { #every-screen-in-the-console }

Capturas actuales de Northwind Labs realizadas el 2 de noviembre de 2026 con AgenticOS 1.35.3. Empresas, ventas, entregas y equipos son ficticios. Los Visuals preparados están identificados; no implican conexión con CRM, ERP ni máquinas. Las capturas conservan la ventana completa de la aplicación.

## Dónde aterrizas { #where-you-land }

### Dashboard { #dashboard }

Tu propia vista, la de la organización que se ordena, la de un grupo y - para un administrador del despliegue - la de todo el despliegue, elegidas arriba. Runs, gasto, salud de los servicios y calidad de las respuestas; cada tarjeta está protegida por el permiso que necesitan sus propios datos, así que una tarjeta cuya lectura principal no puedes hacer es una tarjeta que no se te ofrece.

![Dashboard](assets/screens/light/dashboard.webp?v=20261102-industrial#only-light)
![Dashboard](assets/screens/dark/dashboard.webp?v=20261102-industrial#only-dark)

### Chat { #chat }

Una revisión comercial preparada con Revenue Pulse en el renderer de Visuals. Ingresos, objetivos y aportación del equipo cambian con los filtros de región y período. La conversación y los datos son ejemplos preparados, no evidencia de generación del dashboard por un modelo.

![Chat](assets/screens/light/chat.webp?v=20261102-industrial#only-light)
![Chat](assets/screens/dark/chat.webp?v=20261102-industrial#only-dark)

## Construir un agent { #building-an-agent }

### Agents { #agents }

El catálogo. Cada agent lleva la versión que está en vivo, quién puede alcanzarlo y si hay un borrador esperando. Un agent es configuración, no código — por eso esta lista la puede editar cualquiera que sepa la respuesta.

![Agents](assets/screens/light/agents.webp?v=20261102-industrial#only-light)
![Agents](assets/screens/dark/agents.webp?v=20261102-industrial#only-dark)

### Agent templates { #agent-templates }

Templates por sector, sobre el catálogo. Instalar uno crea un borrador que tú terminas y publicas; hasta que lo haces no se ejecuta nada.

![Agent templates](assets/screens/light/agent-templates.webp?v=20261102-industrial#only-light)
![Agent templates](assets/screens/dark/agent-templates.webp?v=20261102-industrial#only-dark)

### Skills { #skills }

Conocimiento escrito una vez y compartido por cada agent vinculado a él — cómo se gestionan las devoluciones, cuál es el estilo de la casa. Edítalo aquí y cada agent vinculado a él estará al día en su siguiente run.

![Skills](assets/screens/light/skills.webp?v=20261102-industrial#only-light)
![Skills](assets/screens/dark/skills.webp?v=20261102-industrial#only-dark)

### Skill gallery { #skill-gallery }

Skills por sector. Instalar copia uno en tu organización, donde puedes editarlo — una copia, para que el origen no pueda cambiar lo que dicen tus agents.

![Skill gallery](assets/screens/light/skill-gallery.webp?v=20261102-industrial#only-light)
![Skill gallery](assets/screens/dark/skill-gallery.webp?v=20261102-industrial#only-dark)

### Un skill { #one-skill }

Abierto para editar, con su categoría. El nombre al que se refiere el modelo queda fijado al crearlo y no puede cambiar; todo lo demás de aquí sí.

![Un skill](assets/screens/light/skill-detail.webp?v=20261102-industrial#only-light)
![Un skill](assets/screens/dark/skill-detail.webp?v=20261102-industrial#only-dark)

### Context { #context }

Contexto permanente del que cada agent puede tirar — un glosario, una política, una voz de marca. Inyectado en el prompt o leído bajo demanda, y actualizado en el momento en que lo editas.

![Context](assets/screens/light/context.webp?v=20261102-industrial#only-light)
![Context](assets/screens/dark/context.webp?v=20261102-industrial#only-dark)

## Dentro de un agent { #inside-one-agent }

El Builder, pestaña por pestaña.

### Build { #build }

Instrucciones, modelo y endpoint. El comportamiento vive aquí en lugar de en el código, en Markdown que el modelo lee como estructura — y la cabecera lleva `published` junto a `Draft differs from agent v40`, que es justo el objetivo: editar no despliega.

![Build](assets/screens/light/agent-builder.webp?v=20261102-industrial#only-light)
![Build](assets/screens/dark/agent-builder.webp?v=20261102-industrial#only-dark)

### Toolbox { #toolbox }

Cada capability como un interruptor — búsqueda en el conocimiento, un navegador, Python en una sandbox, gráficas, delegación — y junto a cada una la puerta de aprobación por herramienta. La configuración solo alcanza lo que el código registró.

![Toolbox](assets/screens/light/agent-toolbox.webp?v=20261102-industrial#only-light)
![Toolbox](assets/screens/dark/agent-toolbox.webp?v=20261102-industrial#only-dark)

### MCP servers { #mcp-servers }

Qué conexiones puede alcanzar este agent, y cuáles de sus herramientas. La lista de la organización lo sigue limitando; un agent puede estrechar dentro de ella y no puede alcanzar más allá.

![MCP servers](assets/screens/light/agent-mcp.webp?v=20261102-industrial#only-light)
![MCP servers](assets/screens/dark/agent-mcp.webp?v=20261102-industrial#only-dark)

### Limits { #limits }

Un tope mensual y un techo de pasos. El tope se comprueba antes de cada petición al modelo, y el límite de pasos atrapa el otro desbocamiento — un bucle de herramientas que es barato por llamada y nunca termina.

![Limits](assets/screens/light/agent-limits.webp?v=20261102-industrial#only-light)
![Limits](assets/screens/dark/agent-limits.webp?v=20261102-industrial#only-dark)

### Availability { #availability }

Dónde responde este agent: el dashboard y la API siempre, más cualquier bot de chat vinculado aquí. Un agent se puede mencionar por `@handle` solo en los bots a los que está vinculado.

![Availability](assets/screens/light/agent-availability.webp?v=20261102-industrial#only-light)
![Availability](assets/screens/dark/agent-availability.webp?v=20261102-industrial#only-dark)

### Routines, en el agent { #routines-on-the-agent }

Lo que hace sin que nadie escriba, en esta misma pestaña — un horario que se puede pausar, o un disparador por evento.

![Routines, en el agent](assets/screens/light/agent-routines.webp?v=20261102-industrial#only-light)
![Routines, en el agent](assets/screens/dark/agent-routines.webp?v=20261102-industrial#only-dark)

### History { #history }

Cada versión que ha tenido este agent. La que estuvo en vivo en marzo sigue siendo legible, y eso es lo que convierte una vuelta atrás en una decisión y no en un proyecto de arqueología.

![History](assets/screens/light/agent-history.webp?v=20261102-industrial#only-light)
![History](assets/screens/dark/agent-history.webp?v=20261102-industrial#only-dark)

### Visual map { #visual-map }

El mismo agent como grafo: qué lo alcanza y hacia qué alcanza él. Una caja discontinua es algo a lo que no hay nada enganchado — un budget sin tope propio se lee como un hueco y no como un valor por defecto.

![Visual map](assets/screens/light/agent-map.webp?v=20261102-industrial#only-light)
![Visual map](assets/screens/dark/agent-map.webp?v=20261102-industrial#only-dark)

## Workflows y tablas { #workflows-and-tables }

### Workflows { #workflows }

El catálogo de automatizaciones, una tarjeta por cada una: su estado, quién puede alcanzarla, si tiene una versión en vivo y cuándo se editó por última vez, con sus runs, el editor y una copia a un clic.

![Workflows](assets/screens/light/workflows.webp?v=20261102-industrial#only-light)
![Workflows](assets/screens/dark/workflows.webp?v=20261102-industrial#only-dark)

### El editor de workflows { #the-workflow-editor }

El lienzo tiene todo el ancho: el grafo como tarjetas que dicen para qué está configurado cada paso o a qué grupo pertenece, los ajustes de un paso en un diálogo sobre él, y cada paso por añadir a un clic - o un clic derecho - de distancia. Un bucle muestra cuántos pasos contiene su cuerpo.

![Workflow editor](assets/screens/light/workflow-editor.webp?v=20261102-industrial#only-light)
![Workflow editor](assets/screens/dark/workflow-editor.webp?v=20261102-industrial#only-dark)

### El cuerpo de un bucle { #a-loops-body }

Dentro del bucle: la empresa actual, el mapeo que forma su registro y el paso que recoge el resultado. Este ejemplo local procesa tres nombres de empresas ficticias sin credenciales externas.

![Workflow loop body](assets/screens/light/workflow-loop-body.webp?v=20261102-industrial#only-light)
![Workflow loop body](assets/screens/dark/workflow-loop-body.webp?v=20261102-industrial#only-dark)

### Runs { #runs }

Cada run de un workflow, del más reciente al más antiguo: si ejecutó el draft o la versión publicada, qué lo inició, cuándo, cuánto duró y cuánto costó. **Start a run** prueba el draft con un input propio.

![Workflow runs](assets/screens/light/workflow-runs.webp?v=20261102-industrial#only-light)
![Workflow runs](assets/screens/dark/workflow-runs.webp?v=20261102-industrial#only-dark)

### Un run { #a-run }

Un run tal como ocurrió: el grafo que ejecutó, con cada paso marcado por lo que hizo, la salida con la que respondió y cada paso que dio, iteración a iteración.

![Workflow run](assets/screens/light/workflow-run.webp?v=20261102-industrial#only-light)
![Workflow run](assets/screens/dark/workflow-run.webp?v=20261102-industrial#only-dark)

### Tablas { #tables }

Pipeline comercial ficticio en Kanban: una oportunidad por tarjeta, agrupada por etapa. Agentes y workflows trabajan con los mismos registros tipados; el tablero es la captura principal.

![Tables](assets/screens/light/table-kanban.webp?v=20261102-industrial#only-light)
![Tables](assets/screens/dark/table-kanban.webp?v=20261102-industrial#only-dark)

## Knowledge { #knowledge }

### Knowledge bases { #knowledge-bases }

Collections. Agrupa documentos relacionados en una y después elige en el chat qué collections puede buscar un agent.

![Knowledge bases](assets/screens/light/knowledge-bases.webp?v=20261102-industrial#only-light)
![Knowledge bases](assets/screens/dark/knowledge-bases.webp?v=20261102-industrial#only-dark)

### Una collection { #a-collection }

Sus documentos, el número de chunks de cada uno y todo lo que falló al ingerirse, con el motivo. Los límites de los chunks son contra lo que compara una búsqueda, así que un documento que se vuelve a subir tras un cambio de ajustes se vuelve a trocear.

![Una collection](assets/screens/light/knowledge-collection.webp?v=20261102-industrial#only-light)
![Una collection](assets/screens/dark/knowledge-collection.webp?v=20261102-industrial#only-dark)

### Parsing, por subida { #parsing-per-upload }

La elección que nadie más expone: **PyMuPDF**, **LiteParse** o **LlamaParse**, la estrategia de troceado, el tamaño de chunk y el solapamiento, el OCR y su idioma. Se fija en la collection y se puede sobrescribir en el siguiente archivo que añadas — porque una tarifa escaneada y un runbook en Markdown no quieren el mismo parser, y el equivocado es la diferencia entre una respuesta y una negativa.

![Parsing, por subida](assets/screens/light/kb-parse-options.webp?v=20261102-industrial#only-light)
![Parsing, por subida](assets/screens/dark/kb-parse-options.webp?v=20261102-industrial#only-dark)

## Probar y mejorar un agente { #testing-and-improving-an-agent }

Estas pantallas vienen de una segunda organización de demo, Demo, y de su agente Refund desk: preguntas de la tienda Acme sobre reembolsos y envíos, calificadas con checks y un juez. Las preguntas son inventadas; las respuestas, las calificaciones y las sesiones de Improve son runs reales.

### Datasets { #datasets }

Las preguntas de prueba con las que se comprueban tus agentes. Cada cambio en los casos de un dataset crea una versión nueva, así que dos eval runs se comparan sobre las mismas preguntas o no se comparan.

![Datasets](assets/screens/light/datasets.webp#only-light)
![Datasets](assets/screens/dark/datasets.webp#only-dark)

### Los casos de un dataset { #a-datasets-cases }

Cada pregunta con su origen, cuántos checks lleva y si Improve la usa para escribir los cambios o la aparta para comprobar el resultado.

![Los casos de un dataset](assets/screens/light/dataset-cases.webp#only-light)
![Los casos de un dataset](assets/screens/dark/dataset-cases.webp#only-dark)

### Grading { #grading }

Lo que hace que una respuesta pase: los checks que recibe cada caso, qué juez la califica, con qué criterios y desde qué puntuación. Los checks no cuestan nada; cada calificación del juez es un run en un modelo.

![Grading](assets/screens/light/dataset-grading.webp#only-light)
![Grading](assets/screens/dark/dataset-grading.webp#only-dark)

### Los evals de un dataset { #a-datasets-evals }

Cada run contra este dataset como una línea de tasa de aprobados por agente; el color de cada punto dice si arregló o rompió casos, y debajo están los runs.

![Los evals de un dataset](assets/screens/light/dataset-evals.webp#only-light)
![Los evals de un dataset](assets/screens/dark/dataset-evals.webp#only-dark)

### Un eval run { #one-eval-run }

Primero el veredicto, en una frase; después la tasa de aprobados antes y después, lo que costó frente a su estimación y los casos que cambiaron. Una respuesta que salió distinta al preguntarla otra vez no cuenta como cambio.

![Un eval run](assets/screens/light/eval-run.webp#only-light)
![Un eval run](assets/screens/dark/eval-run.webp#only-dark)

### Los evals de un agente { #an-agents-evals }

La misma tendencia desde el lado del agente: cada dataset contra el que se ejecutó, una línea por dataset, con Run evals al lado.

![Los evals de un agente](assets/screens/light/agent-evals.webp#only-light)
![Los evals de un agente](assets/screens/dark/agent-evals.webp#only-dark)

### Improve { #improve }

Donde empieza una mejora: las respuestas valoradas negativamente, las respuestas de prueba que fallan, cómo se reparten las preguntas de prueba entre escribir los cambios y comprobarlos, y lo que cuesta el primer paso. Cada paso siguiente se presupuesta antes de pulsarlo.

![Improve](assets/screens/light/improve-start.webp#only-light)
![Improve](assets/screens/dark/improve-start.webp#only-dark)

### Improve · Understand { #improve-understand }

Qué salió mal, separado en lo que el agente puede corregir y lo que le falta a la base de conocimiento, una tarjeta por pregunta con las calificaciones en palabras. La sesión se detiene aquí para que lo mires.

![Improve · Understand](assets/screens/light/improve-understand.webp#only-light)
![Improve · Understand](assets/screens/dark/improve-understand.webp#only-dark)

### Improve · Changes { #improve-changes }

Los cambios que escribió el asistente, como un diff del propio texto del agente, con el porqué y en qué se basan. Puedes reformular uno antes de que se compruebe; la comprobación mide tu redacción.

![Improve · Changes](assets/screens/light/improve-changes.webp#only-light)
![Improve · Changes](assets/screens/dark/improve-changes.webp#only-dark)

### Improve · Result { #improve-result }

A qué llegó la sesión: cada intento con cuántas de las preguntas apartadas arregló y rompió, lo que costó y cuál conservar. Nada pasa a producción hasta que una persona lo acepta.

![Improve · Result](assets/screens/light/improve-result.webp#only-light)
![Improve · Result](assets/screens/dark/improve-result.webp#only-dark)

### Knowledge gaps { #knowledge-gaps }

Preguntas para las que un agente buscó en sus bases de conocimiento y no encontró nada relevante, agrupadas por tema. Nada se añade solo a una base de conocimiento; una persona redacta el documento y lo añade.

![Knowledge gaps](assets/screens/light/knowledge-gaps.webp#only-light)
![Knowledge gaps](assets/screens/dark/knowledge-gaps.webp#only-dark)


## Qué ha pasado, y qué está esperando { #what-happened-and-what-is-waiting }

### Runs { #runs }

Cada run que ha hecho esta organización, con su estado, superficie, modelo, persona y coste. Un run es el proceso: arranca, se puede detener y deja un registro.

![Runs](assets/screens/light/activity.webp?v=20261102-industrial#only-light)
![Runs](assets/screens/dark/activity.webp?v=20261102-industrial#only-dark)

### Un run, abierto { #one-run-opened }

Tokens de entrada y de salida, coste con cuatro decimales, cuánto tardó y la línea de tiempo de cada turno y cada llamada a una herramienta. El chat en el que ocurrió está a un clic.

![Un run, abierto](assets/screens/light/run-detail.webp?v=20261102-industrial#only-light)
![Un run, abierto](assets/screens/dark/run-detail.webp?v=20261102-industrial#only-dark)

### Approvals { #approvals }

Todo lo que espera a una persona, con lo que el agent pretende hacer. Una aprobación se decide exactamente una vez — una segunda decisión sobre una ya zanjada se rechaza, y ese es el detalle que hace que la puerta valga la pena.

![Approvals](assets/screens/light/approvals.webp?v=20261102-industrial#only-light)
![Approvals](assets/screens/dark/approvals.webp?v=20261102-industrial#only-dark)

### Spend { #spend }

Lo que se gastó realmente, por periodo. Un budget se comprueba _antes_ de la petición al modelo en lugar de sumarse después, así que un run que rompe uno se detiene a mitad de la respuesta y aun así registra su coste.

![Spend](assets/screens/light/spend.webp?v=20261102-industrial#only-light)
![Spend](assets/screens/dark/spend.webp?v=20261102-industrial#only-dark)

### Routines { #routines }

Lo que hacen los agents sin que nadie escriba — según un horario, o cuando llega un evento. Esos runs llevan budget, aprobación y auditoría como cualquier otro.

![Routines](assets/screens/light/routines.webp?v=20261102-industrial#only-light)
![Routines](assets/screens/dark/routines.webp?v=20261102-industrial#only-dark)

### Un nuevo disparador por evento { #a-new-event-trigger }

Nombrar el evento que arranca un run, sobre la lista de routines.

![Un nuevo disparador por evento](assets/screens/light/routine-event-trigger.webp?v=20261102-industrial#only-light)
![Un nuevo disparador por evento](assets/screens/dark/routine-event-trigger.webp?v=20261102-industrial#only-dark)

### Apps { #apps }

Páginas que publicaron los agents: informes, pequeños dashboards, resúmenes. Cada una conserva su enlace cuando el agent la vuelve a publicar, y sus versiones anteriores siguen siendo legibles.

![Apps](assets/screens/light/apps.webp?v=20261102-industrial#only-light)
![Apps](assets/screens/dark/apps.webp?v=20261102-industrial#only-dark)

### Una app { #one-app }

Northline combina un mapa europeo de proveedores, excepciones de entrega y ventanas de montaje. Permite simular un retraso, filtrar envíos y revisar dependencias. Es una App local preparada, sin conexión a ERP ni transportistas.

![Northline](assets/screens/light/app-manufacturing.webp?v=20261102-industrial#only-light)
![Northline](assets/screens/dark/app-manufacturing.webp?v=20261102-industrial#only-dark)

### Motor Atlas { #motor }

Vista conceptual de un motor descompuesto con componentes seleccionables, control de separación, lista de materiales ficticia y telemetría de ejemplo. Es una explicación interactiva, no un plano CAD, diagnóstico ni instrucción de mantenimiento.

![Motor Atlas](assets/screens/light/app-motor.webp?v=20261102-industrial#only-light)
![Motor Atlas](assets/screens/dark/app-motor.webp?v=20261102-industrial#only-dark)

### Revenue Pulse { #revenue }

Revisión comercial interactiva con ingresos frente al objetivo, pipeline, aportación del equipo y próximas oportunidades. Los totales se calculan con registros ficticios; los filtros funcionan localmente.

![Revenue Pulse](assets/screens/light/app-revenue.webp?v=20261102-industrial#only-light)
![Revenue Pulse](assets/screens/dark/app-revenue.webp?v=20261102-industrial#only-dark)

### Visuals { #visuals-in-the-conversation }

El Visual de Revenue Pulse preparado en el renderer real del chat. Puede guardarse como App; la captura no representa una nueva ejecución del modelo ni acceso a un CRM conectado.

![Visuals](assets/screens/light/chat-hero.webp?v=20261102-industrial#only-light)
![Visuals](assets/screens/dark/chat-hero.webp?v=20261102-industrial#only-dark)

## La organización { #the-organization }

### Organizations { #organizations }

Cambia entre ellas, gestiona miembros y crea otras nuevas. La autoridad dentro de una organización es una fila de membresía más el catálogo de permisos — no hay una columna de rol en un usuario.

![Organizations](assets/screens/light/organizations.webp?v=20261102-industrial#only-light)
![Organizations](assets/screens/dark/organizations.webp?v=20261102-industrial#only-dark)

### Members { #members }

Las personas de una organización y sus roles, con el límite mensual que comparten todos sus agents y si una conversación puede omitir sus approvals.

![Members](assets/screens/light/members.webp?v=20261102-industrial#only-light)
![Members](assets/screens/dark/members.webp?v=20261102-industrial#only-dark)

### Roles { #roles }

Lo que puede hacer cada rol, como la matriz que define el código. Compartir un recurso concreto puede ampliar el acceso más allá del rol; nunca lo reduce.

![Roles](assets/screens/light/roles.webp?v=20261102-industrial#only-light)
![Roles](assets/screens/dark/roles.webp?v=20261102-industrial#only-dark)

### Groups { #groups }

Departamentos y equipos. Comparte un agent, una base de conocimiento, un skill o un archivo de contexto con un grupo y todos sus miembros podrán usarlo; quien esté fuera, no.

![Groups](assets/screens/light/groups.webp?v=20261102-industrial#only-light)
![Groups](assets/screens/dark/groups.webp?v=20261102-industrial#only-dark)

### Vault { #vault }

Cada clave que ha guardado esta organización, sellada por inquilino. Reemplazable, nunca legible otra vez; y rotar una es invisible para un agent publicado, que referencia el secreto y no su valor.

![Vault](assets/screens/light/vault.webp?v=20261102-industrial#only-light)
![Vault](assets/screens/dark/vault.webp?v=20261102-industrial#only-dark)

### MCP servers { #mcp-servers }

Conecta cualquier servidor MCP por URL y sus herramientas se convierten en interruptores en el Builder. Conéctalo para la organización y cualquier agent podrá usarlo; conéctalo para ti y se queda en tu propio chat.

![MCP servers](assets/screens/light/mcp-servers.webp?v=20261102-industrial#only-light)
![MCP servers](assets/screens/dark/mcp-servers.webp?v=20261102-industrial#only-dark)

### Channels { #channels }

Las plataformas de chat en las que responde esta organización — Slack, Teams, Telegram, Mattermost. Un bot sirve a cada agent vinculado a él, y el vínculo se hace en la pestaña Availability de ese agent.

![Channels](assets/screens/light/channels.webp?v=20261102-industrial#only-light)
![Channels](assets/screens/dark/channels.webp?v=20261102-industrial#only-dark)

### Sandboxes { #sandboxes }

Donde los agents de esta organización ejecutan comandos de shell y guardan archivos. Un agent nombra una conexión por id, así que mudarse a otro host es una edición aquí en lugar de una republicación de cada agent.

![Sandboxes](assets/screens/light/sandboxes.webp?v=20261102-industrial#only-light)
![Sandboxes](assets/screens/dark/sandboxes.webp?v=20261102-industrial#only-dark)

### Documents { #documents }

Los archivos que los agents guardan para ti. Un workspace es espacio de trabajo temporal — se borra junto con la conversación a la que pertenece, y no es un sitio donde guardar nada duradero.

![Documents](assets/screens/light/documents.webp?v=20261102-industrial#only-light)
![Documents](assets/screens/dark/documents.webp?v=20261102-industrial#only-dark)

### Tus ajustes { #your-settings }

Tu perfil y tu cuenta, los slash commands, la memoria, los inicios de sesión que el agent del navegador guarda para ti, las notificaciones, las claves de API, los clientes MCP y el Architect: una pestaña para cada uno.

![Tus ajustes](assets/screens/light/settings.webp?v=20261102-industrial#only-light)
![Tus ajustes](assets/screens/dark/settings.webp?v=20261102-industrial#only-dark)

## Administración del despliegue { #deployment-administration }

### Users { #users }

Todo el que puede iniciar sesión en este despliegue, y el indicador de app-admin, que es independiente de cualquier rol de organización.

![Users](assets/screens/light/admin-users.webp?v=20261102-industrial#only-light)
![Users](assets/screens/dark/admin-users.webp?v=20261102-industrial#only-dark)

### All organizations { #all-organizations }

Cada inquilino de este despliegue, con su owner, sus miembros y sus agents.

![All organizations](assets/screens/light/admin-organizations.webp?v=20261102-industrial#only-light)
![All organizations](assets/screens/dark/admin-organizations.webp?v=20261102-industrial#only-dark)

### System { #system }

Base de datos, Redis, el almacén vectorial, el acceso a los modelos y los trabajos programados — las mismas comprobaciones que ejecuta `agenticos cmd doctor`, en una página.

![System](assets/screens/light/admin-system.webp?v=20261102-industrial#only-light)
![System](assets/screens/dark/admin-system.webp?v=20261102-industrial#only-dark)

### Deployment { #deployment }

La identidad y la política propias de este despliegue: registro, invitaciones, avisos y lo que encuentra quien lo visita por primera vez.

![Deployment](assets/screens/light/admin-deployment.webp?v=20261102-industrial#only-light)
![Deployment](assets/screens/dark/admin-deployment.webp?v=20261102-industrial#only-dark)

## Lo que todavía no está aquí { #what-is-not-here-yet }

Aún no hay capturas del inicio de sesión, la incorporación inicial ni el recorrido dentro del producto.

## Resumen { #recap }

Cada pantalla aparece en ambos temas, desde una única organización de demostración. `docs/assets/screens/capture.mjs` las vuelve a capturar todas contra cualquier despliegue en marcha, así que una pantalla que cambia es una nueva ejecución y no una imagen hecha a mano.
