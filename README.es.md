<!-- source_sha: 74a30d94e71c -->

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

Dale a un agente el briefing, el conocimiento y las herramientas. Deja que investigue, prepare informes y cree resultados que tu equipo pueda utilizar. Mantén las instrucciones, los permisos y el historial de ejecuciones en un solo lugar; elige modelos locales o en la nube.

<p align="center"><strong>5700+ integraciones mediante MCP · Agentes y conocimiento compartidos · Observabilidad integrada · Alojamiento propio</strong></p>

## Mira cómo funciona

**De un briefing en Notion y una investigación en GitHub a una página interactiva para tomar decisiones.**

<video src="https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953" controls muted playsinline width="100%" poster="docs/assets/screens/oss-launch-planner-poster.webp">
  <img src="docs/assets/screens/oss-launch-planner-poster.webp" alt="Vstorm OSS Launch Planner: selección de audiencia, recomendación de proyecto y enlaces a fuentes" width="100%">
</video>

[Ver el vídeo](https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953) · [Ver una captura](docs/assets/screens/oss-launch-planner-poster.webp)

*Demostración editada con los tiempos de espera eliminados. Las cifras de los repositorios corresponden
al momento de la grabación; el artefacto no obtiene datos en vivo. Las conexiones y capacidades se configuraron para esta demo.*

## 💬 Lleva los agentes a donde tu equipo ya trabaja

Usa tu agente publicado en **Slack, Mattermost o Telegram**. Tus compañeros pueden pedir ayuda desde las herramientas que ya utilizan, con las instrucciones, el conocimiento y las herramientas configurados para el agente.

**Un agente, varias formas de acceder:** mensajería del equipo, chat de AgenticOS, widget web, página alojada o tu propia aplicación mediante la API. Configura el canal, gestiona la versión publicada del agente desde un solo lugar y consulta sus ejecuciones en Activity.

[Conecta Slack, Mattermost y otros canales](docs/channels.es.md).

## Explora la capa de agentes

<table>
<tr>
<td width="45%" valign="middle">

### 📄 Guarda los resultados fuera del chat

Los **Artifacts** son páginas creadas por un agente: informes, comparaciones interactivas o pequeños paneles.
Ábrelos desde la biblioteca, consulta sus versiones y decide quién puede acceder. Actualizar el mismo
artefacto conserva el enlace a su página actual; una conversación puede enlazar a una versión concreta.

Un artefacto muestra los datos con los que se publicó. Una nueva ejecución del agente puede actualizarlos.
[Crea y comparte artefactos](docs/artifacts.es.md).

</td>
<td width="55%">

<!-- MEDIA: artifacts | light -->

<a href="docs/assets/screens/light/artifacts.webp">
  <img src="docs/assets/screens/light/artifacts.webp" alt="Biblioteca de artefactos con informes guardados y versiones." width="100%">
</a>

</td>
</tr>
<tr>
<td colspan="2" valign="top">

### 🔌 5700+ integraciones mediante MCP

Conecta agentes con las herramientas que tu empresa ya utiliza: **GitHub, Notion, HubSpot, Linear y n8n**.
**MCP** (Model Context Protocol) es el estándar que permite a los agentes utilizar herramientas y fuentes de datos externas.

Busca entre **más de 5700 entradas de servidores MCP** en el catálogo o añade un servidor compatible por URL.
Conecta los servicios que necesitas y elige las herramientas de cada agente. La configuración, las credenciales
y las acciones disponibles dependen del servidor. [Conecta tus herramientas](docs/mcp.es.md).



<!-- MEDIA: mcp-catalog | light -->

<a href="docs/assets/screens/light/mcp-catalog.webp">
  <img src="docs/assets/screens/light/mcp-catalog.webp" alt="Catálogo MCP con GitHub, Notion, Slack y otros servicios y su estado de conexión." width="100%">
</a>

</td>
</tr>
<tr>
<td width="45%" valign="middle">

### 📚 Dale documentos donde buscar

Las **Knowledge bases** organizan documentos en colecciones que asignas a los agentes. El agente busca
fragmentos relevantes en esas fuentes al responder. Esto suele llamarse **RAG**, o generación aumentada
por recuperación. [Añade y procesa documentos](docs/file-processing.es.md).

</td>
<td width="55%">

<!-- MEDIA: knowledge-bases | light -->

<a href="docs/assets/screens/light/knowledge-bases.webp">
  <img src="docs/assets/screens/light/knowledge-bases.webp" alt="Bases de conocimiento con colecciones personales y de la organización." width="100%">
</a>

</td>
</tr>
<tr>
<td width="45%" valign="middle">

### 📊 Observabilidad integrada: ejecuciones y costes a la vista

**Activity** reúne el historial de ejecuciones, las aprobaciones y los gastos. Un **run** es una ejecución de un agente:
consulta su estado, modelo, tokens, duración y coste registrado. Filtra por agente, persona o versión,
compara resultados entre versiones y exporta los datos a CSV.

Localiza ejecuciones lentas o fallidas y ábrelas para revisar la conversación y las llamadas a herramientas.
[Explora Activity y el control de costes](docs/governance.es.md).

</td>
<td width="55%">

<!-- MEDIA: activity | light; filtered run history and version comparison -->

<a href="docs/assets/screens/light/activity.webp">
  <img src="docs/assets/screens/light/activity.webp" alt="Activity con comparación de versiones e historial filtrado: estado, tokens, duración y coste registrado." width="100%">
</a>

</td>
</tr>
<tr>
<td width="45%" valign="middle">

### 🛡️ Aprobación humana

Puedes exigir aprobación humana para las acciones de herramientas compatibles. La solicitud permite
revisar la operación propuesta antes de decidir si debe continuar. El acceso a agentes y recursos
se controla mediante [roles y permisos](docs/permissions.es.md).

</td>
<td width="55%">

<!-- MEDIA: approval | light -->

<a href="docs/assets/screens/light/approval.webp">
  <img src="docs/assets/screens/light/approval.webp" alt="Acción de herramienta pendiente con argumentos y controles de aprobación." width="100%">
</a>

</td>
</tr>
<tr>
<td width="45%" valign="middle">

### 🤖 Configura un agente

En **Agents**, crea un asistente para una tarea, elige su modelo, escribe instrucciones y activa sus herramientas.
Publica una versión cuando esté lista para usarse. Puedes consultar versiones anteriores y revertir un cambio.
[Crea un agente](docs/first-agent.es.md).

</td>
<td width="55%">

<!-- MEDIA: agent-builder | light -->

<a href="docs/assets/screens/light/agent-builder.webp">
  <img src="docs/assets/screens/light/agent-builder.webp" alt="Configuración del agente con instrucciones, modelo seleccionado y versión publicada actual." width="100%">
</a>

</td>
</tr>
<tr>
<td width="45%" valign="middle">

### 🧩 Enseña un procedimiento reutilizable

Los **Skills** son procedimientos escritos que un agente puede cargar cuando resultan pertinentes: cómo
revisar una propuesta, conciliar un informe o aplicar vuestro estilo de redacción. Escribe el procedimiento
una vez y asígnalo a los agentes que lo necesiten. [Más sobre skills](docs/skills.es.md).

</td>
<td width="55%">

<!-- MEDIA: skills | light -->

<a href="docs/assets/screens/light/skill-detail.webp">
  <img src="docs/assets/screens/light/skill-detail.webp" alt="El procedimiento artifact-pages con instrucciones y plantillas de páginas." width="100%">
</a>

</td>
</tr>
<tr>
<td width="45%" valign="middle">

### 🧠 Contexto compartido

**Context** contiene información estable, como nombres de productos, un glosario o pautas de comunicación.
Úsalo para hechos y reglas compartidos entre tareas; elige si el agente los recibe automáticamente
o los lee cuando los necesita. [Más sobre contexto](docs/context.es.md).

</td>
<td width="55%">

<!-- MEDIA: context | light -->

<a href="docs/assets/screens/light/context-detail.webp">
  <img src="docs/assets/screens/light/context-detail.webp" alt="Vista previa del glosario en modo linked para leerlo cuando sea necesario." width="100%">
</a>

</td>
</tr>
<tr>
<td width="45%" valign="middle">

### ⏱️ Programa el trabajo recurrente

Las **Routines** ejecutan un agente según una programación o en respuesta a un evento configurado.
Úsalas para resúmenes semanales o informes periódicos. Las ejecuciones utilizan el acceso y los controles
configurados y dejan un registro. [Configura una rutina](docs/triggers.es.md).

</td>
<td width="55%">

<!-- MEDIA: routines | light; existing weekly schedule configuration -->

<a href="docs/assets/screens/light/routines.webp">
  <img src="docs/assets/screens/light/routines.webp" alt="Editor de horarios con repetición semanal los lunes a las 06:00 UTC y vista previa del mensaje para el agente." width="100%">
</a>

</td>
</tr>
</table>

<details>
<summary>Más vistas y detalles de ejecución</summary>

<a href="docs/assets/screens/light/skills.webp">
  <img src="docs/assets/screens/light/skills.webp" alt="Biblioteca de Skills con procedimientos reutilizables." width="100%">
</a>

<a href="docs/assets/screens/light/context.webp">
  <img src="docs/assets/screens/light/context.webp" alt="Biblioteca Context con archivos de glosario compartidos." width="100%">
</a>

<!-- MEDIA: knowledge-collection | light; supplementary view -->

<a href="docs/assets/screens/light/knowledge-collection.webp">
  <img src="docs/assets/screens/light/knowledge-collection.webp" alt="La colección vstorm con el documento adding_features.md procesado correctamente." width="100%">
</a>

<a href="docs/assets/screens/light/artifact-detail.webp">
  <img src="docs/assets/screens/light/artifact-detail.webp" alt="OSS Launch Planner de la demo con selección de audiencia y recomendación." width="100%">
</a>

### Consulta las acciones y los costes

Un **run** es una ejecución de un agente. **Activity / Runs** muestra su estado y el consumo registrado;
abre una ejecución para revisar la conversación y las llamadas a herramientas. Los controles de presupuesto
usan el gasto registrado antes de las solicitudes al modelo; las solicitudes en curso o ejecuciones simultáneas
pueden superar el límite. [Presupuestos e historial de auditoría](docs/governance.es.md).

<!-- MEDIA: run-detail | capture light with expanded sidebar; same run as the demo -->
> **Captura pendiente — Detalle de ejecución:** estado, duración, coste registrado y llamadas a herramientas de la tarea mostrada.

</details>

## Convierte el trabajo individual con IA en una capacidad del equipo

Para un informe periódico, el equipo puede repartirse el trabajo:

1. **Una persona experta define el método:** mantiene las instrucciones, los skills y las fuentes de conocimiento.
2. **La persona que configura el agente lo pone a disposición del equipo:** conecta las herramientas, publica una versión y concede acceso a sus compañeros.
3. **Los compañeros utilizan los resultados:** ejecutan el agente, revisan su respuesta y comparten un artefacto con los ajustes de acceso adecuados.

La organización conserva el agente y el conocimiento reutilizable. El equipo trabaja desde el navegador;
los desarrolladores pueden conectar sistemas internos. [Configura el acceso del equipo](docs/permissions.es.md).

## Inicio rápido

Instala primero Docker con Compose. En macOS o Linux, ejecuta el comando siguiente; en Windows, utiliza
WSL2 con la integración de WSL2 de Docker Desktop. El instalador te guía para configurar el acceso al
modelo, tu cuenta y la organización, y prepara el despliegue con un agente de ejemplo.

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

Abre la consola en **http://localhost:3000** e inicia sesión con las credenciales que configuraste.

### Prueba tu primera tarea

En **Chat**, selecciona **Getting Started** y pega este briefing ficticio. El acceso al modelo debe
estar configurado; este ejercicio no necesita conexión con Notion ni GitHub.

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

<details>
<summary>Adónde van tus datos</summary>

| Componente | Qué decides |
|---|---|
| Aplicación y almacenamiento | Operas la aplicación, la base de datos y el almacenamiento de archivos configurado; eliges dónde se ejecutan y cómo se hacen las copias de seguridad |
| Modelos de lenguaje | Un proveedor alojado recibe el contexto enviado para la inferencia; elige un endpoint local si ese procesamiento debe permanecer en tu infraestructura |
| Procesamiento y búsqueda de documentos | Revisa los parsers y proveedores de embeddings por separado: un modelo de chat local no hace locales un parser en la nube ni los embeddings remotos |
| Herramientas y canales | Las integraciones habilitadas intercambian los datos necesarios para sus llamadas; los canales conectados reciben las respuestas enviadas a través de ellos |
| Observabilidad | El tracing opcional puede exportar datos de ejecución; revisa tanto los ajustes del despliegue como los de cada agente |

[Revisa los límites de los datos](docs/security.es.md#what-leaves-the-deployment) ·
[Elige el procesamiento de documentos](docs/file-processing.es.md).

</details>

## ¿Encaja AgenticOS con tu empresa?

Elige AgenticOS si tu empresa necesita agentes, conocimiento y automatización compartidos con control
sobre el código, los modelos y el despliegue. Tu equipo opera la instalación; Vstorm puede ayudar con
la implementación y el soporte. Si solo necesitas una biblioteca de agentes en una aplicación existente,
empieza con un framework. Si buscas un servicio totalmente gestionado, compara también quién se ocupa de operarlo.

Compara el enfoque con [Dify](docs/about/dify.es.md), [Viktor](docs/about/viktor.es.md) y
[Wonderful](docs/about/wonderful.es.md), o utiliza la [guía de comparación](docs/about/comparison.es.md)
para elegir según la tarea, la propiedad y los controles necesarios.

<details>
<summary>Preguntas sobre la capa de agentes</summary>

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

</details>

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

## ¿Necesitas ayuda para llevar agentes a producción?

Vstorm puede ayudarte a desplegar AgenticOS en la infraestructura del cliente, redactar documentación, definir procesos y desarrollar componentes a medida. El mantenimiento y el soporte se acuerdan para cada proyecto.

Creado con esmero por [**Vstorm**](https://vstorm.co) · [oss.vstorm.co](https://oss.vstorm.co)
