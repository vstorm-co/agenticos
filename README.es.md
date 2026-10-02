<!-- source_sha: 47c6c2527a65 -->

<div align="center">

<h1><img src="docs/assets/amigo-walk.svg" alt="Amigo, la mascota de AgenticOS" width="64" valign="middle"> AgenticOS</h1>

<p>
  <b>Pon la IA a trabajar en tu empresa.</b><br>
  La capa de agentes de código abierto para compartir agentes, conocimiento y automatización — en infraestructura que tú controlas.
</p>

<p>
  <a href="#mira-cómo-funciona">Ver la demo</a> &middot;
  <a href="#inicio-rápido">Inicio rápido</a> &middot;
  <a href="#explora-la-capa-de-agentes">Explora la capa de agentes</a> &middot;
  <a href="#por-qué-un-sistema-operativo">Por qué un OS</a> &middot;
  <a href="docs/index.es.md">Documentación</a>
</p>

<p>
  <a href="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml"><img src="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://github.com/vstorm-co/agenticos/releases"><img src="https://img.shields.io/github/v/release/vstorm-co/agenticos?label=release&color=blue" alt="Versión"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-Apache--2.0-blue" alt="Apache-2.0"></a>
  <a href="https://ai.pydantic.dev"><img src="https://img.shields.io/badge/Powered%20by-Pydantic%20AI-E92063?logo=pydantic&logoColor=white" alt="Construido con Pydantic AI"></a>
</p>

<p>
  <a href="README.md">English</a> &middot;
  <a href="README.pl.md">Polski</a> &middot;
  <a href="README.de.md">Deutsch</a> &middot;
  <b>Español</b>
</p>

</div>

Dale a un agente el briefing, el conocimiento y las herramientas. Deja que investigue, prepare informes y cree resultados que tu equipo pueda usar. Las instrucciones, el acceso y el historial de ejecuciones quedan en un solo lugar; eliges modelos en la nube o locales.

<h3 align="center">🔌 5700+ integraciones mediante MCP &nbsp;·&nbsp; 🤝 Agentes y conocimiento compartidos<br>
📊 Observabilidad integrada &nbsp;·&nbsp; 🏠 Autoalojado</h3>

## Mira cómo funciona

**De un briefing en Notion y una investigación en GitHub a una página interactiva para decidir.**

<video src="https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512" controls playsinline width="100%" poster="docs/assets/screens/oss-launch-planner-poster.webp">
  <img src="docs/assets/screens/oss-launch-planner-poster.webp" alt="Vstorm OSS Launch Planner: selección de audiencia, recomendación de proyecto y enlaces a las fuentes" width="100%">
</video>

<details>
<summary>¿No se carga el vídeo? Abre la vista previa animada</summary>

<a href="https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512">
  <img src="docs/assets/screens/oss-launch-planner-preview.gif" alt="Vstorm OSS Launch Planner: selección de audiencia, recomendación de proyecto y enlaces a las fuentes" width="100%">
</a>

*Vista previa animada a velocidad 2×. Haz clic para ver el vídeo de 37 segundos con sonido a velocidad normal.*

</details>

[Ver el vídeo abreviado (37 segundos)](https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512) · [Ver una captura](docs/assets/screens/oss-launch-planner-poster.webp)

## Inicio rápido

Solo necesitas Docker con Compose. En macOS o Linux, ejecuta:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

En Windows, ejecuta el mismo comando dentro de WSL2 con la integración de WSL2 de Docker Desktop activada.
El instalador pregunta por el proveedor de modelos y su clave, tu usuario y el nombre de la organización, descarga
las imágenes publicadas y arranca un despliegue con un agente que ya funciona.

Abre **http://localhost:3000** e inicia sesión con el usuario que elegiste. Con los valores por defecto es
`admin@example.com` / `admin123`.

### Prueba tu primera tarea

En **Chat**, selecciona **Getting Started** y pega este briefing ficticio. No necesita conexión con
Notion ni GitHub.

```text
Responde en español. Convierte este briefing en una lista de tareas para el lanzamiento. Usa solo los hechos indicados.
Para cada tarea, muestra la persona responsable, la fecha límite y la información que falta.
No inventes fechas ni responsabilidades.

Briefing:
- El webinar para clientes será el 15 de octubre.
- Maya se encarga de la página de destino; debe estar lista el 8 de octubre.
- Leo se encarga de la demo, pero aún no se ha fijado su fecha de revisión.
- Hay que enviar las invitaciones antes del 10 de octubre; no hay una persona asignada.
```

**Comprueba el resultado:** la página de destino debería indicar a Maya y el 8 de octubre; la demo,
la falta de fecha de revisión; y las invitaciones, la falta de responsable. Después, prueba tu propio briefing o
[configura un agente con herramientas y conocimiento de la empresa](docs/first-agent.es.md).

<details>
<summary>Revisa el instalador o elige otro método de despliegue</summary>

Lee el [instalador](scripts/quickstart.sh) antes de ejecutarlo. Para comprobar los requisitos sin instalar:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- --check
```

La [guía de instalación](docs/install.es.md) explica la configuración manual con Docker Compose, las versiones fijas y la resolución de problemas.
Para desarrollar a partir del código fuente, consulta [Contribuir](CONTRIBUTING.es.md).

</details>

## 💬 Lleva los agentes a donde tu equipo ya trabaja

<p align="center">
  <a href="docs/channels.es.md"><img src="docs/assets/channels/slack.svg" alt="Slack" width="176" height="64"></a>
  <a href="docs/channels.es.md"><img src="docs/assets/channels/mattermost.svg" alt="Mattermost" width="176" height="64"></a>
  <a href="docs/channels.es.md"><img src="docs/assets/channels/telegram.svg" alt="Telegram" width="176" height="64"></a>
</p>

Usa tu agente publicado en **Slack, Mattermost o Telegram**. Tus compañeros piden ayuda en las herramientas que ya usan, y el agente responde con sus instrucciones, su conocimiento y sus herramientas. Una `@mention` se ejecuta como la persona que la envió, no como el bot.

**Un agente, varias formas de llegar a él:** mensajería del equipo, el chat web de AgenticOS, un widget en tu web, una página alojada o tu propia aplicación a través de la API. Configura el canal una vez; gestiona la versión publicada del agente desde un único lugar y revisa sus ejecuciones en Activity.

[Conecta Slack, Mattermost y otros canales](docs/channels.es.md).

## Explora la capa de agentes

<table>
<tr>
<td colspan="2" valign="top">

### 📄 Guarda los resultados fuera del chat

Los **Artifacts** son páginas que crea un agente: informes, comparativas interactivas o pequeños paneles.
Ábrelos desde la biblioteca, consulta sus versiones y decide quién puede acceder. Actualizar el mismo artifact
conserva su enlace; una conversación puede enlazar a una versión concreta. [Crea y comparte artifacts](docs/artifacts.es.md).

<a href="docs/assets/screens/light/artifacts.webp">
  <img src="docs/assets/screens/light/artifacts.webp" alt="Biblioteca de artifacts con informes guardados y versiones." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🤖 Configura un agente

En **Agents**, crea un asistente para una tarea, elige su modelo, escribe las instrucciones y activa sus herramientas.
Publica una versión cuando esté listo. Cada versión anterior sigue disponible, y volver a ella es un clic.
[Crea un agente](docs/first-agent.es.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/agent-builder.webp">
  <img src="docs/assets/screens/light/agent-builder.webp" alt="Editor de agentes con instrucciones, modelo seleccionado y versión publicada actual." width="100%">
</a>

</td>
</tr>
<tr>
<td colspan="2" valign="top">

### 🔌 5700+ integraciones mediante MCP

Conecta los agentes a las herramientas que tu empresa ya usa: **GitHub, Notion, HubSpot, Linear y n8n**.
**MCP** (Model Context Protocol) es el estándar que permite a los agentes llamar a herramientas y fuentes de datos externas.

Busca entre **más de 5700 servidores MCP** en el catálogo o añade un servidor compatible por URL.
Conecta los servicios que necesites y elige qué herramientas puede usar cada agente. [Conecta tus herramientas](docs/mcp.es.md).

<a href="docs/assets/screens/light/mcp-catalog.webp">
  <img src="docs/assets/screens/light/mcp-catalog.webp" alt="Catálogo MCP con GitHub, Notion, Slack y otros servicios, con su estado de conexión." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🧩 Enseña un procedimiento reutilizable

Los **Skills** son procedimientos escritos que un agente carga cuando son relevantes: cómo revisar una propuesta,
cuadrar un informe o seguir tu estilo de redacción. Escribe un procedimiento una vez y asígnalo a los agentes
que lo necesiten. Edítalo y la siguiente respuesta ya lo usa, sin publicar una versión. [Más sobre skills](docs/skills.es.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/skill-detail.webp">
  <img src="docs/assets/screens/light/skill-detail.webp" alt="El procedimiento artifact-pages con instrucciones y plantillas de página." width="100%">
</a>

</td>
</tr>
<tr>
<td colspan="2" valign="top">

### 📚 Dale documentos donde buscar

Las **Knowledge bases** organizan los documentos en colecciones que asignas a los agentes. El agente busca en esas
fuentes los pasajes relevantes para responder. Esto se suele llamar **RAG**, generación aumentada por recuperación.
Eliges el lector de PDF, la división en fragmentos y el OCR para cada colección. [Añade y procesa documentos](docs/file-processing.es.md).

<a href="docs/assets/screens/light/knowledge-bases.webp">
  <img src="docs/assets/screens/light/knowledge-bases.webp" alt="Knowledge bases con colecciones personales y de la organización." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🧠 Contexto compartido

**Context** guarda información estable como nombres de productos, un glosario o pautas de comunicación.
Úsalo para hechos y reglas comunes a varias tareas; decide si el agente los recibe automáticamente
o los lee cuando los necesita. [Más sobre el contexto](docs/context.es.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/context-detail.webp">
  <img src="docs/assets/screens/light/context-detail.webp" alt="Glosario en vista previa, en modo enlazado para leerlo cuando se necesite." width="100%">
</a>

</td>
</tr>
<tr>
<td colspan="2" valign="top">

### 📊 Observabilidad integrada: ejecuciones y costes a la vista

**Activity** reúne el historial de ejecuciones, las aprobaciones y el gasto. Cada ejecución registra su estado,
modelo, tokens, duración y coste. Filtra por agente, persona o versión, compara versiones y exporta los
registros a CSV. Abre una ejecución para ver la conversación y cada llamada a herramientas.
[Explora Activity y el control de costes](docs/governance.es.md).

<a href="docs/assets/screens/light/activity.webp">
  <img src="docs/assets/screens/light/activity.webp" alt="Activity con comparación de versiones del agente e historial filtrado de ejecuciones: estado, tokens, duración y coste registrado." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🛡️ Aprobación humana

Todo lo que envía, archiva o cambia algo puede esperar a una persona. La solicitud de aprobación muestra
la operación prevista y sus argumentos, y la acción solo se ejecuta cuando alguien la aprueba.
El acceso a agentes y recursos se controla mediante [roles y permisos](docs/permissions.es.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/approval.webp">
  <img src="docs/assets/screens/light/approval.webp" alt="Una acción de herramienta pendiente con sus argumentos y los controles de aprobación." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### ⏱️ Programa el trabajo recurrente

Las **Routines** ejecutan un agente según un calendario o en respuesta a un evento: el resumen del lunes,
el informe periódico. Una ejecución de una rutina tiene los mismos límites y el mismo registro que cualquier petición de una persona.
[Configura una rutina](docs/triggers.es.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/routines.webp">
  <img src="docs/assets/screens/light/routines.webp" alt="Editor de calendario con repetición semanal los lunes a las 06:00 UTC y el mensaje para el agente en vista previa." width="100%">
</a>

</td>
</tr>
</table>

<details>
<summary>Más vistas</summary>

<a href="docs/assets/screens/light/skills.webp">
  <img src="docs/assets/screens/light/skills.webp" alt="Biblioteca de skills con procedimientos reutilizables." width="100%">
</a>

<a href="docs/assets/screens/light/context.webp">
  <img src="docs/assets/screens/light/context.webp" alt="Biblioteca de contexto con archivos de glosario compartidos." width="100%">
</a>

<a href="docs/assets/screens/light/knowledge-collection.webp">
  <img src="docs/assets/screens/light/knowledge-collection.webp" alt="La colección vstorm con adding_features.md procesado correctamente." width="100%">
</a>

<a href="docs/assets/screens/light/artifact-detail.webp">
  <img src="docs/assets/screens/light/artifact-detail.webp" alt="OSS Launch Planner de la demo con selección de audiencia y recomendación." width="100%">
</a>

</details>

## Por qué un sistema operativo

El nombre es una afirmación, así que aquí están los criterios. Un sistema operativo hace siete trabajos; cada fila
es un mecanismo que puedes leer en el código.

| Un sistema operativo… | AgenticOS |
|---|---|
| **Ejecuta y aísla procesos** | Ejecuta agentes, aísla a cada organización en el esquema y guarda cada ejecución con su coste |
| **Impone límites de recursos** | Presupuestos mensuales por agente, comprobados *antes* de cada petición al modelo |
| **Controla el acceso** | Un [catálogo de permisos](docs/permissions.es.md) en el código, roles compuestos a partir de él, permisos por recurso; una aprobación es el `sudo` |
| **Llega al hardware mediante controladores** | [27 proveedores de modelos](docs/models.es.md) y [servidores MCP](docs/mcp.es.md) tras una sola interfaz |
| **Mantiene un sistema de archivos** | [Colecciones, skills y contexto](docs/file-processing.es.md) en tu propio Postgres |
| **Da a muchas interfaces un solo shell** | Un único runner tras el chat web, la API, Slack, Telegram, Mattermost, un widget, una página alojada y un calendario |
| **Escribe un registro de auditoría** | Quién ejecutó qué, cuándo, cuánto costó y quién lo aprobó, incluso cuando la ejecución falló |

Aplica los mismos siete a cualquier otro producto de la categoría, nosotros incluidos:
[qué hace que algo sea un sistema operativo para agentes](docs/about/index.es.md).

## Por qué existe

La mayoría de los frameworks de agentes te dan una biblioteca. Escribes Python, lo despliegas, y cada cambio en el
comportamiento de un agente es un pull request, una revisión y una versión nueva. Es la forma correcta para una
funcionalidad de producto y la equivocada para los cuarenta pequeños agentes que una empresa realmente quiere — porque
quien sabe lo que el agente debe decir no es quien tiene permiso de commit.

**El código define, la configuración compone.** Un equipo de negocio monta agentes en el navegador y nunca abre
Python; los ingenieros amplían lo que se puede montar, y la configuración solo alcanza lo que el código registró.
El techo es el registro de capacidades, no un archivo de configuración.

## Convierte el trabajo individual con IA en una capacidad del equipo

Para un informe recurrente, el equipo puede repartirse el trabajo:

1. **Una persona experta define el método:** mantiene las instrucciones, los skills y el conocimiento de origen.
2. **Quien configura pone el agente a disposición:** configura sus herramientas, publica una versión y da acceso a los compañeros.
3. **Los compañeros usan los resultados:** ejecutan el agente, revisan su respuesta y comparten un artifact con quien lo necesita.

La organización conserva el agente y el conocimiento reutilizable. El equipo trabaja en el navegador;
los ingenieros pueden conectar sistemas internos. [Configura el acceso del equipo](docs/permissions.es.md).

## Controla tu despliegue, modelos y acceso

**Ejecútalo en tu infraestructura.** AgenticOS es software Apache-2.0 que puedes revisar, modificar y operar.
Elige proveedores de modelos alojados o modelos locales mediante Ollama y endpoints compatibles como vLLM.
[Configuración de modelos](docs/models.es.md).

**Decide qué puede hacer un agente.** Configura permisos sobre los recursos, guarda las credenciales en la bóveda cifrada
y pon la aprobación de una persona delante de las herramientas que actúan fuera. [Control de acceso](docs/permissions.es.md) · [Secretos](docs/secrets.es.md).

**Ve el trabajo y el gasto.** Cada ejecución conserva sus llamadas a herramientas y su coste, y cada presupuesto se comprueba
antes de llamar al modelo. [Control de ejecución y costes](docs/governance.es.md).

[Desplegar y operar](docs/rollout.es.md) · [Seguridad y flujos de datos](docs/security.es.md)

## ¿Encaja AgenticOS con tu empresa?

Elige AgenticOS cuando tu empresa quiera agentes compartidos, conocimiento reutilizable y automatización con control
sobre el código fuente, los modelos y el despliegue. Si solo necesitas una biblioteca de agentes dentro de una
aplicación existente, empieza por un framework.

Cada comparativa cita las páginas del propio proveedor, muestra dónde AgenticOS va más allá y nombra lo que todavía no hace.

- **Apps de asistente:** [Claude](docs/about/claude-apps.es.md) · [ChatGPT](docs/about/chatgpt.es.md). Licencias para empleados, o agentes que pertenecen a tu organización sobre cualquier modelo.
- **Constructores en suites cloud:** [Copilot Studio](docs/about/copilot-studio.es.md) · [Gemini Enterprise](docs/about/gemini-enterprise.es.md). La nube y la tarifa de un proveedor, o tu infraestructura y los precios de tu proveedor de modelos.
- **Constructores autoalojados:** [Dify](docs/about/dify.es.md) · [n8n](docs/about/n8n.es.md). Condiciones de licencia y planes enterprise, o Apache-2.0 con la gobernanza incluida.
- **Servicio de compañero IA:** [Viktor](docs/about/viktor.es.md). Un empleado de IA compartido, o muchos agentes con su propio acceso y presupuesto.
- **Capa de agentes entregada:** [Wonderful](docs/about/wonderful.es.md). Un sistema que entrega un proveedor, o uno que es tuyo desde el primer día.
- **Agentes de programación:** [Claude Code](docs/about/claude-code.es.md) · [Codex](docs/about/codex.es.md) · [OpenCode](docs/about/opencode.es.md). Hechos para desarrolladores; AgenticOS es para todos los demás, y los desarrolladores lo amplían.

[Todas las comparativas, y las carencias](docs/about/comparison.es.md).

<details>
<summary>Preguntas sobre la capa de agentes</summary>

### ¿Es AgenticOS un AI agent harness?

Sí, con una interfaz para el equipo. El harness es el bucle que ejecuta un modelo con herramientas: búsqueda en tus
documentos, búsqueda web y un navegador real, Python en un sandbox con archivos y shell, gráficos, imágenes, delegación
en subagentes, una lista de tareas y la compactación de conversaciones largas. Cada una es una capacidad que activas por
agente en el navegador, junto a skills, contexto, servidores MCP, presupuestos y aprobaciones. Los desarrolladores añaden
capacidades nuevas en Python tipado. Consulta la [referencia de capacidades](docs/reference/capabilities.es.md).

### ¿Puedo crear un agente al estilo de Claude Code para tareas empresariales?

Sí. Dale a un agente un sandbox con archivos y shell, búsqueda web, un navegador, delegación y una lista de tareas, y
asígnale los skills y el contexto que necesite. Planifica trabajo en varios pasos, lee antes de actuar, edita archivos,
ejecuta comandos, delega partes en especialistas y comprueba el resultado. Responde en el chat web, en Slack o a través
de la API, con el modelo que elijas y con aprobación delante de todo lo que actúa fuera. Consulta la
[comparativa con Claude Code](docs/about/claude-code.es.md).

### ¿Qué pueden compartir los compañeros?

Los equipos pueden compartir agentes, skills, contexto, colecciones de conocimiento y artifacts según los permisos sobre
los recursos. Un agente compartido puede atender a distintas personas; un artifact compartido da a los compañeros un
resultado que pueden abrir fuera del chat.

</details>

## En el escritorio, si quieres

La consola es una aplicación web y basta con un navegador. La [aplicación de escritorio](docs/desktop.es.md) opcional
es la misma consola en su propia ventana, con una mascota en el escritorio y un atajo global (`⌘⇧A`) que captura
cualquier zona de la pantalla directamente en un chat nuevo.

## Para desarrolladores y operadores

Construido con FastAPI, Pydantic AI, PostgreSQL con pgvector, Redis, Prefect y Next.js.
La configuración del agente selecciona capacidades registradas en el runtime; los desarrolladores las amplían en código.

| Empieza aquí | Qué cubre |
|---|---|
| [Arquitectura](docs/architecture.es.md) | Servicios, almacenamiento y ejecución |
| [Capacidades](docs/reference/capabilities.es.md) | Herramientas disponibles y configuración |
| [API](docs/api.es.md) | Integración con tus aplicaciones |
| [Modelos](docs/models.es.md) | Proveedores de modelos y perfiles |
| [Seguridad](docs/security.es.md) | Flujos de datos y límites del despliegue |
| [Pruebas](docs/testing.es.md) | Conjuntos de pruebas y alcance de la cobertura |

`make check` antes de un pull request: todos los trabajos de CI salvo e2e. Un comportamiento nuevo llega con una prueba;
una corrección, con una prueba de regresión. El núcleo se mantiene al 100 % de cobertura y CI falla por debajo.

Tres cosas con las que tropieza un primer cambio: una herramienta es código y un agente no (no existe `@agent.tool` —
una capacidad se registra y entonces es un interruptor en el Builder de todos); las comprobaciones `require(...)` van solo
en las rutas de colección; y si la herramienta ya existe como servidor MCP, no escribas ninguna.
[Contribuir](CONTRIBUTING.es.md) explica el resto, [`.claude/`](.claude/README.md) recoge las mismas convenciones escritas
para una máquina, la [hoja de ruta](docs/ROADMAP.md) muestra el trabajo previsto y las tareas para empezar están
[etiquetadas aquí](https://github.com/vstorm-co/agenticos/labels/good%20first%20issue).

<details>
<summary><b>El resto del ecosistema Vstorm OSS</b></summary>

Todo lo siguiente funciona sobre [Pydantic AI](https://ai.pydantic.dev).

| Proyecto | Qué es | |
|---|---|---|
| **[full-stack-ai-agent-template](https://github.com/vstorm-co/full-stack-ai-agent-template)** | El generador del que nació AgenticOS — FastAPI + Next.js, RAG, streaming, autenticación, más de 20 integraciones | [![Stars](https://img.shields.io/github/stars/vstorm-co/full-stack-ai-agent-template?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/full-stack-ai-agent-template) |
| **[pydantic-deepagents](https://github.com/vstorm-co/pydantic-deepagents)** | Un Claude Code de código abierto y autoalojado — un asistente de terminal y el framework que lo sostiene | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-deepagents?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-deepagents) |
| **[pydantic-ai-shields](https://github.com/vstorm-co/pydantic-ai-shields)** | Guardrails — seguimiento de costes, detección de prompt injection, filtrado de PII, ocultación de secretos | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-shields?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-shields) |
| **[subagents-pydantic-ai](https://github.com/vstorm-co/subagents-pydantic-ai)** | Delegación anidada en subagentes, ejecución en paralelo, cancelación de tareas | [![Stars](https://img.shields.io/github/stars/vstorm-co/subagents-pydantic-ai?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/subagents-pydantic-ai) |
| **[pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend)** | Almacenamiento de archivos y sandboxes aislados en Docker, con un sistema de permisos | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-backend?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-backend) |
| **[pydantic-ai-todo](https://github.com/vstorm-co/pydantic-ai-todo)** | Planificación jerárquica de tareas con almacenamiento en PostgreSQL y un sistema de eventos | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-todo?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-todo) |
| **[production-stack-skills](https://github.com/vstorm-co/production-stack-skills)** | Paquete de skills que convierte un agente de programación en un ingeniero sénior de producción | [![Stars](https://img.shields.io/github/stars/vstorm-co/production-stack-skills?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/production-stack-skills) |
| **[content-skills](https://github.com/vstorm-co/content-skills)** | Paquete de skills de contenidos para agentes de programación — fiel a la marca, con filtro anti-slop incluido | [![Stars](https://img.shields.io/github/stars/vstorm-co/content-skills?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/content-skills) |

Encuéntralos todos en **[oss.vstorm.co](https://oss.vstorm.co)**.

</details>

## Licencia

[Apache License 2.0](LICENSE). Consulta [NOTICE](NOTICE) y los [avisos de terceros](THIRD_PARTY_NOTICES.md)
para las atribuciones y los componentes incluidos.

## ¿Necesitas ayuda para llevar agentes a producción?

Vstorm despliega AgenticOS en la infraestructura del cliente, escribe la documentación, define los procesos
y construye capacidades a medida. El mantenimiento y el soporte se acuerdan en cada proyecto.

Construido con esmero por [**Vstorm**](https://vstorm.co) · [oss.vstorm.co](https://oss.vstorm.co)
