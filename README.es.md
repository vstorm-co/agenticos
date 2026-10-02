<!-- source_sha: f4a951bb9509 -->

<div align="center">

<h1><img src="docs/assets/amigo-walk.svg" alt="Amigo, la mascota de AgenticOS" width="64" valign="middle"> AgenticOS</h1>

<p>
  <strong>Sovereign Agentic AI Layer</strong><br>
  <b>Agentes de IA que todo tu equipo puede usar y mejorar.</b><br>
  Código abierto. Crea agentes compartidos en el navegador, en infraestructura que tú controlas.
</p>

<p>
  <a href="#inicio-rápido">Inicio rápido</a> &middot;
  <a href="#crea-comparte-y-opera">Crea, comparte y opera</a> &middot;
  <a href="#encaja-agenticos-con-tu-equipo">¿Encaja con nosotros?</a> &middot;
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

AgenticOS es un espacio de trabajo autoalojado para crear y ejecutar agentes de IA compartidos. Asigna una tarea a un agente, conecta documentos y herramientas de la empresa y publícalo para tu equipo. Los ingenieros amplían sus capacidades; los expertos del área mantienen sus instrucciones y conocimientos.

<a href="docs/assets/screens/light/agent-builder.webp">
  <img src="docs/assets/screens/light/agent-builder.webp" alt="Builder del agente con instrucciones, selección de modelo y una versión publicada." width="100%">
</a>

## Dale a tu equipo una forma compartida de trabajar

Un asistente para consultas sobre solicitudes de equipamiento necesita a alguien que conozca la política, a alguien que configure el agente y a compañeros que lo usen. AgenticOS conecta su trabajo:

1. **Un experto mantiene el método:** redacta instrucciones, procedimientos reutilizables y documentos fuente.
2. **Un builder publica el agente:** elige el modelo y las herramientas, establece límites y concede acceso.
3. **Los compañeros lo usan y lo comprueban:** hacen preguntas, revisan fuentes y comparten resultados. Los operadores inspeccionan las ejecuciones en Activity.

Las instrucciones y el conocimiento se actualizan en la consola. Las nuevas capacidades se añaden en Python. [Cómo crear un agente](docs/first-agent.es.md) · [Acceso del equipo](docs/permissions.es.md).

## Inicio rápido

Solo necesitas Docker con Compose. En macOS o Linux, ejecuta:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

En Windows, ejecuta el mismo comando dentro de WSL2 con la integración de WSL2 de Docker Desktop activada.
El instalador pregunta por el proveedor de modelos y su clave, tu usuario y el nombre de la organización, descarga
las imágenes publicadas y arranca un despliegue con un agente que ya funciona.

Abre **http://localhost:3000** e inicia sesión con el usuario que elegiste durante la instalación.

### Crea un asistente a partir de un documento

Empieza con la [guía de solicitudes de equipamiento](docs/howto/first-document-agent.es.md). Incluye un breve manual ficticio, los pasos de configuración y una prueba documentada con sus limitaciones. Para buscar en documentos necesitas un modelo de embeddings además del modelo de chat.

<details>
<summary>Sigue el ejercicio del asistente de documentos</summary>

1. Guarda las dos líneas siguientes como `equipment-handbook.md` y sube el archivo a una colección de conocimiento. Configura los embeddings y espera a que termine el procesamiento.
2. Crea un agente, selecciona su modelo y activa la búsqueda de conocimiento para esa colección. Indícale que cite el manual y señale cuándo falta una respuesta. Publica el agente.
3. Haz las preguntas siguientes en conversaciones nuevas y revisa el material recuperado y la ejecución en **Activity**.

```text
Equipment requests go to the office manager.
Include the item, reason and delivery location.
```

| Pregunta | Comprueba con la fuente |
|---|---|
| ¿Quién gestiona las solicitudes de equipamiento? | El responsable de oficina, con una cita del manual |
| ¿Qué datos debe incluir una solicitud de equipamiento? | Artículo, motivo y lugar de entrega |
| ¿Cuánto puedo gastar? | El documento no indica un límite de gasto |

Después, sigue la guía para sustituir el documento por una política actualizada y prueba una conversación nueva. Cuando las respuestas sean correctas, concede a un compañero acceso al agente y a los recursos necesarios y pídele que lo pruebe desde su propia cuenta. [Configura el acceso](docs/permissions.es.md) antes de utilizar documentos privados.

La guía documenta una prueba en **v0.0.504, el 25 de septiembre de 2026**, incluido un reintento y la respuesta tras actualizar el documento. Es un ejemplo que puedes reproducir; contrasta las respuestas de tu propio modelo con la fuente.

</details>

<details>
<summary>¿Solo quieres comprobar la instalación? Prueba una tarea sin configurar documentos</summary>

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
la falta de fecha de revisión; y las invitaciones, la falta de responsable. Luego abre **Activity**: la ejecución
ya está ahí, con su modelo, tokens, duración y coste. Después, prueba tu propio briefing o
[configura un agente con herramientas y conocimiento de la empresa](docs/first-agent.es.md).

</details>

<details>
<summary>Revisa el instalador o elige otro método de despliegue</summary>

Lee el [instalador](scripts/quickstart.sh) antes de ejecutarlo. Para comprobar los requisitos sin instalar:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- --check
```

La [guía de instalación](docs/install.es.md) explica la configuración manual con Docker Compose, las versiones fijas y la resolución de problemas.
Para desarrollar a partir del código fuente, consulta [Contribuir](CONTRIBUTING.es.md).

</details>

## Crea, comparte y opera

### Configura la forma de trabajar

Elige el modelo, las instrucciones y las herramientas en el navegador. Publica una versión para tus compañeros; las versiones anteriores siguen disponibles para revisarlas y restaurarlas.

Las [bases de conocimiento](docs/file-processing.es.md) proporcionan documentos para buscar. Los [skills](docs/skills.es.md) contienen procedimientos reutilizables; el [contexto](docs/context.es.md) guarda hechos y directrices compartidos. Actualiza estos recursos a medida que cambia el trabajo.

Conecta herramientas como **GitHub, Notion, HubSpot o Linear** mediante [MCP](docs/mcp.es.md). El catálogo combina conexiones seleccionadas con **más de 5700 entradas de servidores MCP** copiadas de un registro. Las entradas del registro son metadatos de sus editores, no integraciones probadas. Cada conexión requiere su propia configuración y revisión de acceso.

### Da acceso al agente y a sus resultados

Los compañeros pueden usar un agente publicado en el chat web o mediante canales configurados de **Slack, Mattermost y Telegram**. Los desarrolladores pueden invocarlo a través de la API. [Conecta un canal](docs/channels.es.md).

Los agentes pueden publicar informes, comparaciones interactivas y pequeños paneles como **artefactos**. Elige quién puede abrirlos; las actualizaciones del mismo artefacto conservan su enlace y las versiones anteriores siguen siendo legibles. [Comparte un artefacto](docs/artifacts.es.md).

<a href="docs/assets/screens/light/artifacts.webp">
  <img src="docs/assets/screens/light/artifacts.webp" alt="Biblioteca de artefactos con informes, ajustes de acceso y versiones." width="100%">
</a>

### Inspecciona ejecuciones y repite el trabajo útil

**Activity** reúne el historial de ejecuciones, las aprobaciones y el gasto registrado. Inspecciona llamadas a herramientas, compara versiones de agentes y exporta registros. Algunos costes dependen de los datos de uso y precios del proveedor; los servicios externos pueden facturar por separado. [Límites del registro de costes](docs/governance.es.md).

<a href="docs/assets/screens/light/activity.webp">
  <img src="docs/assets/screens/light/activity.webp" alt="Activity con comparaciones de versiones e historial de ejecuciones, incluida una aprobación pendiente." width="100%">
</a>

Configura los requisitos de aprobación para las herramientas de capabilities compatibles. En el chat web, **Ask about everything** también controla las llamadas a herramientas MCP que ejecuta el runner. La cobertura de aprobación depende de la herramienta y del modo de ejecución; activar una conexión por sí solo no exige aprobación. [Modos y límites de aprobación](docs/governance.es.md#how-much-one-conversation-wants-to-be-asked).

Cuando una tarea esté lista para repetirse, usa [rutinas](docs/triggers.es.md) para ejecutar un agente por horario o evento. Prueba sus herramientas, límites y política de aprobación antes de dejarlo sin supervisión.

## Ejemplo de integración grabado

Esta demo muestra cómo un brief de Notion se convierte en una página interactiva con fuentes después de investigar en GitHub. Utiliza proyectos de código abierto de Vstorm como material de ejemplo: la secuencia útil es **brief → investigación → resultado compartido**. Es una demostración del producto, no un estudio de resultados de un cliente.

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

## Conecta las aplicaciones que tu equipo ya usa

Pon documentos, mensajes y herramientas de trabajo a disposición de tus agentes. Selecciona una aplicación para abrir las instrucciones de conexión.

<p align="center">
  <a href="docs/howto/configure-sync-sources.es.md"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/integrations/drive-dark.svg">
    <img src="docs/assets/integrations/drive.svg" alt="Google Drive™" width="168" height="96">
  </picture></a>
  <a href="docs/triggers.es.md"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/integrations/gmail-dark.svg">
    <img src="docs/assets/integrations/gmail.svg" alt="Gmail" width="168" height="96">
  </picture></a>
  <a href="docs/mcp.es.md#outlook-setup"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/integrations/outlook-dark.svg">
    <img src="docs/assets/integrations/outlook.svg" alt="Microsoft Outlook" width="168" height="96">
  </picture></a>
</p>

**Archivos y correo.** Sincroniza documentos de Google Drive™ con colecciones de conocimiento o inicia agentes al recibir mensajes en Gmail. El correo y el calendario de Microsoft Outlook usan [servidores MCP de terceros](docs/mcp.es.md#outlook-setup), con una cuenta del proveedor y permisos independientes.

<p align="center">
  <a href="docs/mcp.es.md"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/integrations/notion-dark.svg">
    <img src="docs/assets/integrations/notion.svg" alt="Notion" width="168" height="96">
  </picture></a>
  <a href="docs/mcp.es.md"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/integrations/github-dark.svg">
    <img src="docs/assets/integrations/github.svg" alt="GitHub" width="168" height="96">
  </picture></a>
  <a href="docs/mcp.es.md"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/integrations/linear-dark.svg">
    <img src="docs/assets/integrations/linear.svg" alt="Linear" width="168" height="96">
  </picture></a>
</p>

**Herramientas del equipo.** Conecta páginas de Notion, repositorios de GitHub e incidencias de Linear mediante sus servidores MCP. Elige qué herramientas puede usar cada agente.

<p align="center">
  <a href="docs/channels.es.md"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/channels/slack-dark.svg">
    <img src="docs/assets/channels/slack.svg" alt="Slack" width="168" height="96">
  </picture></a>
  <a href="docs/channels.es.md"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/channels/mattermost-dark.svg">
    <img src="docs/assets/channels/mattermost.svg" alt="Mattermost" width="168" height="96">
  </picture></a>
  <a href="docs/channels.es.md"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/channels/telegram-dark.svg">
    <img src="docs/assets/channels/telegram.svg" alt="Telegram" width="168" height="96">
  </picture></a>
</p>

**Conversaciones.** Tras configurar el canal, los compañeros pueden usar un agente publicado en Slack, Mattermost o Telegram.

<sub>Google Drive es una marca de Google LLC. Los nombres y logotipos indican opciones de conexión, no asociaciones comerciales. [Fuentes de los logotipos](docs/assets/integrations/ATTRIBUTION.txt).</sub>

## ¿Encaja AgenticOS con tu equipo?

Elígelo cuando el equipo tenga tareas recurrentes basadas en documentos o herramientas, expertos que puedan mantener las instrucciones y alguien responsable de operar un despliegue autoalojado.

| Tu punto de partida | Qué evaluar |
|---|---|
| Quieres que los compañeros usen y mantengan agentes compartidos | Prueba el builder, el conocimiento y la publicación de AgenticOS. Si basta con una interfaz de chat compartida, evalúa también [Open WebUI](https://github.com/open-webui/open-webui). |
| Tu necesidad principal es diseñar workflows o aplicaciones de IA | Compara el proceso de creación con [Dify](docs/about/dify.es.md) y [n8n](docs/about/n8n.es.md), usando una tarea real. |
| Creas agentes como parte de un producto de software | Empieza con un SDK o un entorno de ejecución como [Pydantic AI](https://ai.pydantic.dev) o [Agno](https://github.com/agno-agi/agno); decide si también necesitas la consola de equipo de AgenticOS. |

El autoalojamiento implica responsabilizarse de actualizaciones, copias de seguridad, credenciales y facturas de proveedores. Si nadie asumirá ese trabajo, acuerda el despliegue y el soporte antes de un piloto. [Guía de despliegue](docs/rollout.es.md) · [Comparaciones detalladas y carencias](docs/about/comparison.es.md).

## Controla tu despliegue, modelos y acceso

**Sovereign significa controlar el despliegue, los proveedores de modelos, los flujos de datos y el acceso a los agentes.** AgenticOS es software Apache-2.0 que puedes inspeccionar, modificar y operar. Elige proveedores alojados o modelos locales mediante Ollama y endpoints compatibles como vLLM. [Configura los modelos](docs/models.es.md).

Autoalojar la consola no hace que todos los modelos, parsers o herramientas sean locales. Revisa los servicios configurados y los datos que reciben. Asigna permisos sobre recursos, guarda credenciales en la bóveda cifrada y prueba la política de aprobación de las herramientas que actives.

[Seguridad y flujos de datos](docs/security.es.md) · [Control de acceso](docs/permissions.es.md) · [Secretos](docs/secrets.es.md) · [Control de ejecución y costes](docs/governance.es.md).

## Para desarrolladores y operadores

Creado con FastAPI, Pydantic AI, PostgreSQL con pgvector, Redis, Prefect y Next.js. Los ingenieros añaden capabilities en Python tipado; los equipos componen agentes con las capabilities registradas en la consola.

[Arquitectura](docs/architecture.es.md) · [Capabilities](docs/reference/capabilities.es.md) · [API](docs/api.es.md) · [Contribuir](CONTRIBUTING.es.md) · [Hoja de ruta](docs/ROADMAP.md).

La [analogía del sistema operativo](docs/about/index.es.md) explica la arquitectura. La [aplicación de escritorio](docs/desktop.es.md) opcional añade una ventana propia, una mascota y un atajo de captura de pantalla en macOS. Explora los [proyectos de código abierto de Vstorm](https://github.com/vstorm-co) para encontrar las bibliotecas y herramientas que rodean a AgenticOS.

## Licencia

[Apache License 2.0](LICENSE). Consulta [NOTICE](NOTICE) y los [avisos de terceros](THIRD_PARTY_NOTICES.md)
para las atribuciones y los componentes incluidos.

## ¿Necesitas ayuda para llevar agentes a producción?

Vstorm despliega AgenticOS en la infraestructura del cliente, escribe la documentación, define los procesos
y construye capacidades a medida. El mantenimiento y el soporte se acuerdan en cada proyecto.

Construido con esmero por [**Vstorm**](https://vstorm.co) · [Vstorm on GitHub](https://github.com/vstorm-co)
