<!-- source_sha: 96cce7bd5751 -->

<div align="center">

<img src="docs/assets/amigo-walk.svg" alt="Amigo, la mascota de AgenticOS" width="144">

<h1>AgenticOS</h1>

<p>
  <b>Crea agentes de IA que trabajen con los documentos y herramientas de tu equipo.</b><br>
  Configúralos en el navegador, aprovecha sus resultados y consulta sus acciones y costes.
</p>

<p>
  <a href="#mira-cómo-funciona">Ver la demo</a> &middot;
  <a href="#inicio-rápido">Inicio rápido</a> &middot;
  <a href="#explora-la-plataforma">Explorar la plataforma</a> &middot;
  <a href="docs/index.es.md">Documentación</a>
</p>

<p>
  <a href="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml"><img src="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://github.com/vstorm-co/agenticos/releases"><img src="https://img.shields.io/github/v/release/vstorm-co/agenticos?label=release&color=blue" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-Apache--2.0-blue" alt="Apache-2.0"></a>
  <a href="https://ai.pydantic.dev"><img src="https://img.shields.io/badge/Powered%20by-Pydantic%20AI-E92063?logo=pydantic&logoColor=white" alt="Pydantic AI"></a>
</p>

<p>
  <a href="README.md">English</a> &middot;
  <a href="README.pl.md">Polski</a> &middot;
  <a href="README.de.md">Deutsch</a> &middot;
  <b>Español</b>
</p>

</div>

AgenticOS es un espacio de trabajo de código abierto y autoalojado para crear y utilizar agentes de IA.
Un agente es un asistente de IA al que asignas una tarea, instrucciones y acceso a documentos y herramientas concretos.
Puede investigar un tema, analizar un archivo, preparar un informe o ejecutar una acción en una aplicación conectada.
Tú eliges las capacidades y el acceso disponibles para cada agente.

Los equipos configuran agentes y procedimientos reutilizables desde la interfaz. Los desarrolladores
amplían la plataforma y la integran con sus aplicaciones. Los operadores gestionan el acceso, el despliegue y el uso en un solo lugar.

## Mira cómo funciona

**De un briefing en Notion y una investigación en GitHub a una página interactiva para tomar decisiones.**
La demo utiliza el agente **Claude Code like** para preparar una comparación de proyectos de código abierto.
Después se cambia de audiencia en la página resultante y se crea un enlace para compartirla.
El informe es un **artefacto**: un resultado que puedes abrir y utilizar fuera de la conversación.

<video src="https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953" controls muted playsinline width="100%" poster="docs/assets/screens/oss-launch-planner-poster.webp">
  <img src="docs/assets/screens/oss-launch-planner-poster.webp" alt="Vstorm OSS Launch Planner: selección de audiencia, recomendación de proyecto y enlaces a fuentes" width="100%">
</video>

[Ver el vídeo](https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953) · [Ver una captura](docs/assets/screens/oss-launch-planner-poster.webp)

*Demostración editada con los tiempos de espera eliminados. Las cifras de los repositorios corresponden
al momento de la grabación; el artefacto no obtiene datos en vivo. Las conexiones y capacidades se configuraron para esta demo.*

## Empieza con una tarea

| Tu tarea | Qué le das al agente | Qué puedes pedir |
|---|---|---|
| Investigar para tomar una decisión | Un briefing y acceso a las aplicaciones pertinentes | Una comparación con fuentes, recomendaciones y preguntas abiertas |
| Analizar una hoja de cálculo | Un CSV y una pregunta | Cálculos, gráficos y un resultado descargable |
| Responder con conocimiento de la empresa | Manuales, políticas o documentos de producto | Una respuesta con referencias que puedas comprobar |
| Preparar un informe periódico | Instrucciones, fuentes y una programación | Un informe nuevo o un artefacto actualizado después de cada ejecución |

Son puntos de partida: activa las herramientas necesarias y verifica el resultado de tu tarea.
[Crea tu primer agente de documentos](docs/howto/first-document-agent.es.md) o [consulta más casos de uso](docs/use-cases.es.md).

## Inicio rápido

Instala primero Docker con Compose. En macOS o Linux, ejecuta el comando siguiente; en Windows, utiliza
WSL2 con la integración de WSL2 de Docker Desktop. El instalador te guía para configurar el acceso al
modelo, tu cuenta y la organización, y prepara el despliegue con un agente de ejemplo.

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

Abre la consola en **http://localhost:3000**, inicia sesión con las credenciales que configuraste y prueba
el agente de ejemplo. Después, añade un documento o conecta una herramienta para tu propia tarea.

<details>
<summary>Revisa el instalador o elige otro método de despliegue</summary>

Lee el [instalador](scripts/quickstart.sh) antes de ejecutarlo. Para comprobar los requisitos sin instalar:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- --check
```

La [guía de instalación](docs/install.es.md) explica la configuración manual con Docker Compose, las versiones fijas y la resolución de problemas.
Para desarrollar a partir del código fuente, consulta [Contribuir](CONTRIBUTING.es.md).

</details>

Tú operas el despliegue. Los modelos, el procesamiento de documentos y las herramientas conectadas pueden
utilizar servicios externos según la configuración. Consulta las [responsabilidades de operación](docs/rollout.es.md) y los [flujos de datos](docs/security.es.md).

## Explora la plataforma

El chat es donde encargas el trabajo. El resto del espacio reúne las instrucciones, el conocimiento,
las conexiones, los resultados y los controles que permiten repetirlo.

### Configura un agente

En **Agents**, crea un asistente para una tarea, elige su modelo, escribe instrucciones y activa sus herramientas.
Publica una versión cuando esté lista para usarse. Puedes consultar versiones anteriores y revertir un cambio.
[Crea un agente](docs/first-agent.es.md).

<!-- MEDIA: agent-builder | light + dark; same agent as the demo -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/agent-builder.webp">
  <img src="docs/assets/screens/light/agent-builder.webp" alt="Configuración del agente con instrucciones, modelo seleccionado y versión publicada con cambios en el borrador." width="100%">
</picture>

### Enseña un procedimiento reutilizable

Los **Skills** son procedimientos escritos que un agente puede cargar cuando resultan pertinentes: cómo
revisar una propuesta, conciliar un informe o aplicar vuestro estilo de redacción. Escribe el procedimiento
una vez y asígnalo a los agentes que lo necesiten. [Más sobre skills](docs/skills.es.md).

<!-- MEDIA: skills | capture light + dark -->
> **Captura pendiente — Skills:** la biblioteca y un procedimiento abierto con pasos legibles.

**Context** contiene información estable, como nombres de productos, un glosario o pautas de comunicación.
Úsalo para hechos y reglas compartidos entre tareas; elige si el agente los recibe automáticamente
o los lee cuando los necesita. [Más sobre contexto](docs/context.es.md).

<!-- MEDIA: context | capture light + dark -->
> **Captura pendiente — Context:** un archivo de contexto de la empresa abierto con su contenido y opciones de asignación.

### Dale documentos donde buscar

Las **Knowledge bases** organizan documentos en colecciones que asignas a los agentes. El agente busca
fragmentos relevantes en esas fuentes al responder. Esto suele llamarse **RAG**, o generación aumentada
por recuperación. [Añade y procesa documentos](docs/file-processing.es.md).

<!-- MEDIA: knowledge-bases | capture light + dark -->
> **Captura pendiente — Bases de conocimiento:** colecciones con nombres que muestran cómo se organiza el conocimiento del equipo.

Abre una colección para consultar sus documentos y el estado de procesamiento. Elige cómo se leen
los documentos compatibles, incluido el reconocimiento de texto en documentos escaneados (OCR).

<!-- MEDIA: knowledge-collection | capture light + dark -->
> **Captura pendiente — Detalle de colección:** nombres de documentos, estado de procesamiento y una vista previa legible o un resultado de búsqueda.

### Conecta las aplicaciones con las que trabajas

**MCP**, Model Context Protocol, es un estándar para conectar agentes de IA con herramientas y fuentes de datos.
La página **MCP servers** permite configurar conexiones compatibles, como las herramientas de Notion y GitHub
utilizadas en la demo. Las acciones disponibles dependen del servidor, las credenciales y las herramientas
activadas para el agente. [Conecta una aplicación](docs/mcp.es.md).

<!-- MEDIA: mcp-connections | capture light + dark -->
> **Captura pendiente — Conexiones con aplicaciones:** servidores de Notion y GitHub conectados y herramientas seleccionadas, con las credenciales ocultas.

### Guarda los resultados fuera del chat

Los **Artifacts** son páginas creadas por un agente: informes, comparaciones interactivas o pequeños paneles.
Ábrelos desde la biblioteca, consulta sus versiones y decide quién puede acceder. Actualizar el mismo
artefacto conserva el enlace a su página actual; una conversación puede enlazar a una versión concreta.

Un artefacto muestra los datos con los que se publicó. Una nueva ejecución del agente puede actualizarlos.
[Crea y comparte artefactos](docs/artifacts.es.md).

<!-- MEDIA: artifacts | capture light + dark; use the OSS Launch Planner from the video -->
> **Captura pendiente — Artifacts:** la biblioteca y el OSS Launch Planner abierto con su selector de audiencia y recomendación.

### Consulta las acciones y los costes

Un **run** es una ejecución de un agente. **Activity / Runs** muestra su estado y el consumo registrado;
abre una ejecución para revisar la conversación y las llamadas a herramientas. Los controles de presupuesto
usan el gasto registrado antes de las solicitudes al modelo; las solicitudes en curso o ejecuciones simultáneas
pueden superar el límite. [Presupuestos e historial de auditoría](docs/governance.es.md).

<!-- MEDIA: run-detail | capture light + dark; same run as the demo -->
> **Captura pendiente — Detalle de ejecución:** estado, duración, coste registrado y llamadas a herramientas de la tarea mostrada.

Puedes exigir aprobación humana para las acciones de herramientas compatibles. La solicitud permite
revisar la operación propuesta antes de decidir si debe continuar. El acceso a agentes y recursos
se controla mediante [roles y permisos](docs/permissions.es.md).

<!-- MEDIA: approval | capture light + dark; real pending operation -->
> **Captura pendiente — Aprobación:** una acción real que espera una decisión, con la operación y los controles de aprobación visibles.

### Programa el trabajo recurrente

Las **Routines** ejecutan un agente según una programación o en respuesta a un evento configurado.
Úsalas para resúmenes semanales o informes periódicos. Las ejecuciones utilizan el acceso y los controles
configurados y dejan un registro. [Configura una rutina](docs/triggers.es.md).

<!-- MEDIA: routines | capture light + dark; show an actual scheduled execution -->
> **Captura pendiente — Routines:** programación de un informe, última ejecución programada completada y enlace al resultado.

## Trabaja con tu equipo

Utiliza la consola web, ofrece un agente mediante la API o configura un canal compatible como Slack,
Telegram, Mattermost, una página alojada o un widget para tu sitio web. [Elige un canal](docs/channels.es.md).
La [aplicación de escritorio](docs/desktop.es.md) opcional abre la consola en su propia ventana, con una
mascota de escritorio y un atajo para enviar una captura a un chat nuevo.

Las organizaciones, los permisos sobre recursos, la bóveda de credenciales y los paneles de uso ayudan
a los operadores a gestionar el despliegue. [Planifica la puesta en marcha](docs/rollout.es.md).

## ¿Encaja AgenticOS con tu equipo?

AgenticOS está diseñado para equipos que quieren configurar y utilizar agentes desde el navegador y
operar su propio despliegue. Los ingenieros pueden añadir capacidades e integraciones; los responsables
de las tareas pueden mantener instrucciones, documentos y procedimientos desde la interfaz.

Si buscas un servicio gestionado, considera el trabajo de operar una plataforma autoalojada. Si solo
necesitas una biblioteca de agentes dentro de una aplicación existente, evalúa directamente un framework.
Compara las opciones por tarea, modelo de despliegue y controles necesarios en la [guía de comparación de plataformas](docs/about/comparison.es.md).

## Para desarrolladores y operadores

La plataforma utiliza FastAPI, Pydantic AI, PostgreSQL con pgvector, Redis, Prefect y Next.js.
La configuración del agente selecciona capacidades registradas en la plataforma; los desarrolladores las amplían mediante código.

| Empieza aquí | Qué incluye |
|---|---|
| [Arquitectura](docs/architecture.es.md) | Servicios, almacenamiento y ejecución |
| [Capacidades](docs/reference/capabilities.es.md) | Herramientas disponibles y configuración |
| [API](docs/api.es.md) | Integración con tus aplicaciones |
| [Modelos](docs/models.es.md) | Proveedores de modelos y perfiles |
| [Seguridad](docs/security.es.md) | Flujos de datos y límites del despliegue |
| [Pruebas](docs/testing.es.md) | Conjuntos de pruebas y alcance de la cobertura |

Las contribuciones son bienvenidas. Lee [Contribuir](CONTRIBUTING.es.md) para conocer la configuración y las comprobaciones necesarias,
y consulta la [hoja de ruta](docs/ROADMAP.md) para ver el trabajo previsto.

## Licencia y soporte

[Apache License 2.0](LICENSE). Consulta [NOTICE](NOTICE) y los [avisos de terceros](THIRD_PARTY_NOTICES.md)
para conocer las atribuciones y los componentes incluidos.

[Vstorm](https://vstorm.co/) mantiene AgenticOS y puede ayudarte con el despliegue, las integraciones y el desarrollo a medida.
El soporte y el mantenimiento se acuerdan para cada proyecto.
