---
source_sha: "ee9dcf4d5cd6"
---

# Glosario { #glossary }

Las palabras que usa la consola, qué significa cada una y cómo se llama lo mismo
en la API, en el spec y en el YAML que exporta un agent. La consola, el recorrido,
el AI Architect y estas páginas usan estos nombres; la API y el spec conservan los
suyos, para que un script escrito contra ellos no se rompa con un cambio de nombre.
La consola no tiene versión en español, así que sus nombres aparecen aquí en inglés,
tal como se ven en pantalla.

## Lo que construyes { #what-you-build }

| En la consola | Qué es | En la API y el spec |
|---|---|---|
| Agent | Un asistente con sus propias instrucciones, modelo, conocimiento y herramientas | `agent` |
| Draft | Los cambios sin publicar de un agent; fuera del Builder nadie los ve | `draft_spec` |
| Publish | Congelar el borrador como una versión numerada que ejecutan todas las superficies | `POST /agents/{id}/publish` |
| Version | Un estado publicado de un agent, guardado y comparable | `agent_version` |
| Test panel | El chat junto al Builder que responde como el borrador o como cualquier versión | `is_test` en sus runs |
| Instructions | Lo que se le dice al agent antes de cada conversación | `instructions` |
| Variables | `{{name}}` en las instrucciones, que se rellena al empezar un run | `variables` |
| Capability | Algo que un agent puede hacer, activado en el Builder | `capabilities[]` |
| Skill | Saber hacer escrito una vez y leído por cualquier agent que lo necesite | `skill` |
| Context file | Conocimiento fijo que un agent siempre tiene, como un glosario o una política | `context` |
| Knowledge base | Documentos que un agent busca y cita | `collection` |
| App | Una página que publica un agent, como un informe o un pequeño panel | `artifact` |
| AI Architect | El asistente en la esquina de cada página, que puede construir agents contigo | `platform-assistant` |

## Dónde se ejecuta { #where-it-runs }

| En la consola | Qué es | En la API y el spec |
|---|---|---|
| Chat | La conversación web con un agent | `conversation` |
| Channel | Slack, Telegram o Mattermost, donde las personas hablan con un agent | `channel_bot` |
| Routine | Un agent que se ejecuta solo, con un horario o un evento | `trigger` |
| Run | Una vez que un agent respondió, con su coste y sus pasos | `agent_run` |
| Environment | Una etapa con nombre, como producción, que apunta a una versión | `environment` |
| MCP server | Un servidor de herramientas externo al que llaman los agents, conectado una vez | `mcp_connection` |
| Sandbox | Un ordenador aislado donde un agent escribe archivos y ejecuta código | `sandbox` |
| Agent files | Los archivos que los agents guardan en sus sandboxes | `workspace` |

## Quién decide { #who-decides }

| En la consola | Qué es | En la API y el spec |
|---|---|---|
| Organization | La empresa o el equipo al que pertenece todo | `organization` |
| Group | Un departamento o equipo con el que se comparten agents, skills y conocimiento | `group` |
| Lead | Un miembro del grupo que decide quién más está en él | `is_lead` |
| Approval | Una llamada a herramienta que espera a que una persona la permita | `approval` |
| Budget | Un límite de gasto que detiene los runs al alcanzarse | `budget` |
| Guardrails | Comprobaciones que redactan o bloquean lo que pasa por un run | `guardrails` |
| Vault | Donde se guardan claves y tokens, sellados y nunca más mostrados | `secret` |

## Capabilities { #capabilities }

El nombre que muestra el Builder y el id que vincula el spec de un agent. Cada una
se describe en [Capabilities](capabilities.md).

| En la consola | En el spec |
|---|---|
| Apps | `artifacts` |
| Ask the user | `ask_user` |
| Web browser (step by step) | `browser_choice` |
| Web browser | `browser_use` |
| Chat channel lookup | `channel_tools` |
| Charts | `charts` |
| Date and time | `clock` |
| Calculations | `code_execution` |
| Long conversations | `compaction` |
| Context | `context` |
| Past conversations | `conversation_search` |
| Guardrails | `guardrails` |
| Image generation | `image_generation` |
| Knowledge search | `knowledge` |
| Media offload | `media` |
| Memory | `memory_files` |
| Memory (mem0) | `memory_mem0` |
| Planning | `planning` |
| Sandbox | `sandbox` |
| Skills | `skills` |
| Delegation | `subagents` |
| Instruction reminders | `system_reminders` |
| Thinking | `thinking` |
| Tool output limits | `tool_output_limits` |
| Tool search | `tool_search` |
| Read web pages | `web_fetch` |
| Web search | `web_research` |
