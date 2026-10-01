<!-- source_sha: 571c0eb5fe9a -->

<div align="center">

<img src="docs/assets/amigo-walk.svg" alt="Amigo, la mascota de AgenticOS" width="144">

<h1>AgenticOS</h1>

<p>
  <b>La capa de agentes de código abierto para tu empresa.</b><br>
  Agentes de IA, conocimiento y automatización compartidos — en infraestructura que tú controlas.
</p>

<p>
  <a href="#mira-cómo-funciona">Ver la demo</a> &middot;
  <a href="#inicio-rápido">Inicio rápido</a> &middot;
  <a href="#explora-la-capa-de-agentes">Explora la capa de agentes</a> &middot;
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

AgenticOS es una capa de agentes de IA de código abierto y autoalojada para equipos. Crea agentes en el
navegador, conéctalos con documentos y herramientas de la empresa y compártelos con quienes los necesitan.
Los agentes pueden investigar, analizar archivos, crear informes y ejecutar tareas de varios pasos.
Tu organización controla su acceso, la elección de modelos y el despliegue.

Cuando los agentes forman parte del trabajo diario, el equipo necesita saber cuáles usar, a qué pueden
acceder y cuánto cuesta su trabajo. AgenticOS reúne agentes, instrucciones reutilizables, conocimiento,
automatización e historial de ejecución en un solo lugar.

**Apache-2.0 · Autoalojado · Modelos en la nube o locales · Agentes y conocimiento compartidos**

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

## Convierte el trabajo individual con IA en una capacidad del equipo

Ventas puede mantener un agente de investigación, operaciones programar un informe semanal y los expertos
actualizar el conocimiento que utilizan los agentes. El equipo trabaja en el navegador; los desarrolladores
amplían las herramientas y conectan los sistemas internos. La organización conserva los agentes
y los procedimientos reutilizables.

| Qué necesita tu equipo | Cómo ayuda AgenticOS |
|---|---|
| Formas de trabajar consistentes | **Skills** guarda procedimientos reutilizables; **Context**, hechos, terminología y pautas compartidas |
| Respuestas basadas en documentos de la empresa | Las **bases de conocimiento** contienen colecciones consultables; la generación aumentada por recuperación (**RAG**) encuentra los fragmentos relevantes |
| Acciones en las aplicaciones existentes | **MCP** (Model Context Protocol) conecta agentes con herramientas y fuentes de datos compatibles, como Notion y GitHub |
| Resultados útiles para otros compañeros | Los **Artifacts** son páginas guardadas, como informes y paneles interactivos, con versiones y ajustes de acceso |
| Trabajo recurrente | **Routines** ejecuta agentes según un horario o un evento configurado y conserva un registro de ejecución |
| Acceso adecuado para cada persona | Las organizaciones, los roles y los permisos por recurso controlan quién puede usar y gestionar los agentes y el conocimiento compartidos |

Usa los agentes publicados en el chat web o en canales compatibles como Slack, Telegram y Mattermost,
o mediante la API, una página alojada o un widget web. [Explora los canales](docs/channels.es.md).

## Controla tu despliegue, modelos y acceso

**Ejecuta en tu infraestructura.** AgenticOS es software Apache-2.0 que puedes inspeccionar, modificar
y operar. Elige proveedores en la nube o modelos locales mediante Ollama y endpoints compatibles como
vLLM. Las capacidades y los requisitos de hardware dependen del modelo elegido.
[Configuración de modelos](docs/models.es.md).

**Decide qué puede hacer un agente.** Configura permisos por recurso, guarda credenciales en la bóveda
y exige aprobación humana para las acciones de herramientas compatibles.
[Controles de acceso](docs/permissions.es.md) · [Secretos](docs/secrets.es.md).

**Revisa el trabajo y el gasto.** Un run es una ejecución de un agente. Inspecciona las llamadas a
herramientas, el consumo registrado y los registros de auditoría de acciones administrativas. Los presupuestos
comprueban el gasto registrado antes de las solicitudes al modelo; las solicitudes en curso o simultáneas
pueden superar un límite. [Control de ejecuciones y costes](docs/governance.es.md).

El [autoalojamiento](docs/rollout.es.md) deja en manos de tu equipo el despliegue, las actualizaciones y las copias de seguridad.
Los modelos externos, parsers, embeddings, herramientas y trazas pueden enviar datos fuera de tu
infraestructura. Configura cada componente según tus requisitos de datos.
[Seguridad y flujos de datos](docs/security.es.md).

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

## Explora la capa de agentes

### Configura un agente

En **Agents**, crea un asistente para una tarea, elige su modelo, escribe instrucciones y activa sus herramientas.
Publica una versión cuando esté lista para usarse. Puedes consultar versiones anteriores y revertir un cambio.
[Crea un agente](docs/first-agent.es.md).

<!-- MEDIA: agent-builder | light + dark; same agent as the demo -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/agent-builder.webp">
  <img src="docs/assets/screens/light/agent-builder.webp" alt="Configuración del agente con instrucciones, modelo seleccionado y versión publicada con cambios en el borrador." width="100%">
</picture>

<details>
<summary>Abre el recorrido: configuración, conocimiento compartido, integraciones y automatización</summary>

### Enseña un procedimiento reutilizable

Los **Skills** son procedimientos escritos que un agente puede cargar cuando resultan pertinentes: cómo
revisar una propuesta, conciliar un informe o aplicar vuestro estilo de redacción. Escribe el procedimiento
una vez y asígnalo a los agentes que lo necesiten. [Más sobre skills](docs/skills.es.md).

<!-- MEDIA: skills | light + dark; library and artifact-pages procedure -->

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/skills.webp">
  <img src="docs/assets/screens/light/skills.webp" alt="Biblioteca de Skills con procedimientos reutilizables." width="100%">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/skill-detail.webp">
  <img src="docs/assets/screens/light/skill-detail.webp" alt="El procedimiento artifact-pages con instrucciones y plantillas de páginas." width="100%">
</picture>

**Context** contiene información estable, como nombres de productos, un glosario o pautas de comunicación.
Úsalo para hechos y reglas compartidos entre tareas; elige si el agente los recibe automáticamente
o los lee cuando los necesita. [Más sobre contexto](docs/context.es.md).

<!-- MEDIA: context | light + dark; library and glossary content -->

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/context.webp">
  <img src="docs/assets/screens/light/context.webp" alt="Biblioteca Context con archivos de glosario compartidos." width="100%">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/context-detail.webp">
  <img src="docs/assets/screens/light/context-detail.webp" alt="Vista previa del glosario en modo linked para leerlo cuando sea necesario." width="100%">
</picture>

### Dale documentos donde buscar

Las **Knowledge bases** organizan documentos en colecciones que asignas a los agentes. El agente busca
fragmentos relevantes en esas fuentes al responder. Esto suele llamarse **RAG**, o generación aumentada
por recuperación. [Añade y procesa documentos](docs/file-processing.es.md).

<!-- MEDIA: knowledge-bases | light + dark -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/knowledge-bases.webp">
  <img src="docs/assets/screens/light/knowledge-bases.webp" alt="Bases de conocimiento con colecciones personales y de la organización." width="100%">
</picture>

Abre una colección para consultar sus documentos y el estado de procesamiento. Elige cómo se leen
los documentos compatibles, incluido el reconocimiento de texto en documentos escaneados (OCR).

<!-- MEDIA: knowledge-collection | light + dark -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/knowledge-collection.webp">
  <img src="docs/assets/screens/light/knowledge-collection.webp" alt="La colección vstorm con el documento adding_features.md procesado correctamente." width="100%">
</picture>

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

</details>

## ¿Encaja AgenticOS con tu empresa?

Elige AgenticOS si tu empresa necesita agentes, conocimiento y automatización compartidos con control
sobre el código, los modelos y el despliegue. Tu equipo opera la instalación; Vstorm puede ayudar con
la implementación y el soporte. Si solo necesitas una biblioteca de agentes en una aplicación existente,
empieza con un framework. Si buscas un servicio totalmente gestionado, compara también quién se ocupa de operarlo.

Compara el enfoque con [Dify](docs/about/dify.es.md), [Viktor](docs/about/viktor.es.md) y
[Wonderful](docs/about/wonderful.es.md), o utiliza la [guía de comparación](docs/about/comparison.es.md)
para elegir según la tarea, la propiedad y los controles necesarios.

## Preguntas sobre la capa de agentes

### ¿Es AgenticOS un AI agent harness?

AgenticOS combina un AI agent harness con una interfaz para equipos: ejecución de modelos, herramientas,
skills, contexto y controles configurables desde el navegador. Los desarrolladores añaden capacidades
mediante código; los equipos las configuran y utilizan. La [arquitectura](docs/architecture.es.md)
describe cómo se ejecutan los agentes.

### ¿Puedo crear un agente al estilo de Claude Code para tareas empresariales?

Puedes configurar un agente para trabajar en varios pasos con archivos, herramientas y tareas delegadas. Las acciones disponibles dependen de las capacidades activadas y del soporte del
modelo. AgenticOS es un proyecto independiente con su propio entorno de ejecución y elección de modelos.
Consulta la [comparación con Claude Code](docs/about/claude-code.es.md).

### ¿Qué pueden compartir los compañeros?

Los equipos pueden compartir agentes, skills, contexto, colecciones de conocimiento y artifacts según
los permisos por recurso. Un agente compartido puede atender a distintas personas; un artifact compartido
ofrece un resultado accesible fuera del chat.

## Para desarrolladores y operadores

AgenticOS utiliza FastAPI, Pydantic AI, PostgreSQL con pgvector, Redis, Prefect y Next.js.
La configuración del agente selecciona capacidades registradas en el entorno de ejecución; los desarrolladores las amplían mediante código.

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
