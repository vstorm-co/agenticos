---
source_sha: "efcb7fe03f88"
---

# Glosario { #glossary }

Las palabras que usa la consola, qué significa cada una y cómo se llama lo mismo
en la API, en el spec y en el YAML que exporta un agent. La consola, el recorrido,
el Architect y estas páginas usan estos nombres; la API y el spec conservan los
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
| Primeros mensajes | Lo que un chat vacío ofrece a quien abre el agent, cada uno con un clic | `starters` |
| Capability | Algo que un agent puede hacer, activado en el Builder | `capabilities[]` |
| Skill | Saber hacer escrito una vez y leído por cualquier agent que lo necesite | `skill` |
| Context file | Conocimiento fijo que un agent siempre tiene, como un glosario o una política | `context` |
| Knowledge base | Documentos que un agent busca y cita | `collection` |
| Knowledge gap | Un tema de preguntas que una knowledge base no pudo responder, agrupadas por significado; Improve las cuenta como **Missing from the knowledge base** | `knowledge_gap_topic` |
| App | Una página que publica un agent, como un informe o un pequeño panel | `artifact` |
| Architect | El asistente en la esquina de cada página, que puede construir agents contigo | `platform-assistant` |
| System agent | Un agent que ejecuta la propia plataforma, como un juez, el gap drafter o el gap classifier; aparece aparte en **System agents** | `kind` distinto de `agent` |
| Asistente de autoría | Sugiere cambios a un agent, un skill o un archivo de contexto a partir de respuestas valoradas negativamente; una persona decide cada uno | `authoring` |
| Sugerencia | Un cambio propuesto al draft, que se acepta, edita o descarta por separado | `spec_proposal_hunk` |
| Cambio de ajuste | Una sugerencia de cambiar una parte de la configuración de un agent, como su modelo o una capability | hunk `spec_field` |
| Cambio a un archivo de contexto | Un cuerpo nuevo que el asistente propone para un archivo de contexto, aplicado o descartado en la página Context | `context_proposal` |
| AgenticOS | El agent de uso general con el que una organización nueva empieza en Chat, y aquello con lo que empieza un agent nuevo | `general/agenticos` |

## Dónde se ejecuta { #where-it-runs }

| En la consola | Qué es | En la API y el spec |
|---|---|---|
| Chat | La conversación web con un agent | `conversation` |
| Channel | Slack, Telegram o Mattermost, donde las personas hablan con un agent | `channel_bot` |
| Routine | Un agent que se ejecuta solo, con un horario o un evento | `trigger` |
| Suite de evals | Un dataset con el que se mide un agent, ejecutado con un horario, al publicar o promocionar, o tras un cambio | `eval_suite` |
| Run | Una vez que un agent respondió, con su coste y sus pasos | `agent_run` |
| Environment | Una etapa con nombre, como producción, que apunta a una versión | `environment` |
| Guardiana | Una suite de evals que un entorno exige que pase en una versión antes de aceptarla | `guard_suite_ids` |
| Excepción | Una promoción por encima de guardianas que no pasaron, con un motivo | `override_reason` |
| MCP server | Un servidor de herramientas externo al que llaman los agents, conectado una vez | `mcp_connection` |
| Remote agent | El agent de otro proveedor, al que se llega por A2A y en el que delegan los agents | `external_agent` |
| Agent2Agent (A2A) | El protocolo con el que los agents de otros sistemas envían tareas a un agent | `a2a_enabled` |
| Sandbox | Un ordenador aislado donde un agent escribe archivos y ejecuta código | `sandbox` |
| Documents | Los archivos que los agents guardan para una persona, adjuntos o escritos, en sus sandboxes | `workspace` |

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
| AI assistance | El interruptor de la organización para los modelos que califican respuestas, redactan casos, proponen cambios y redactan el conocimiento que falta, Improve incluido; desactivado hasta que alguien lo activa | `ai_assistance_enabled` |

## Cómo se prueba { #how-it-is-tested }

| En la consola | Qué es | En la API y el spec |
|---|---|---|
| Dataset | Casos de prueba versionados con los que se comparan las respuestas de un agent; en Improve, las **Test questions** | `dataset` |
| Case | Una pregunta y aquello con lo que se compara una buena respuesta; en Improve, una pregunta de prueba | `dataset_case` |
| Grading | Cómo se puntúan las respuestas de un dataset: comprobaciones, la respuesta de referencia y un juez | `scoring` |
| Criterion | Una cosa que el juez califica en cada respuesta, en una escala o como sí o no | `criteria[]` |
| Rule | Una comprobación que una respuesta pasa o no sin ningún modelo, como una frase, un patrón o una longitud; aparece en **Checks** | `checks[]` |
| Judge | Un agent que califica respuestas para evals; solo lo ejecuta la plataforma | `kind: judge` |
| Grading model | El modelo con el que califican los jueces nuevos, elegido una vez para la organización | `grading_model_profile_id` |
| Eval | Un agent que responde cada caso de un dataset, puntuado y comparado con una versión anterior | `eval_run` |
| Confirmed regression | Un caso que antes pasaba y vuelve a fallar en cada repetición; Improve dice **Newly broken** | `flip: regression`, `confirmed: true` |
| Confirmed fix | Un caso que antes fallaba y vuelve a pasar en cada repetición; Improve dice **Newly fixed** | `flip: fixed`, `confirmed: true` |
| Unconfirmed | Un caso que cambió una vez, pero no de la misma manera en la repetición, así que no cuenta como ninguna de las dos cosas; Improve lo muestra en **Not confirmed yet** | `confirmed: false` |
| Noise | Respuestas calificadas de otra manera al preguntar de nuevo sin que nada haya cambiado; un resultado que eso podría explicar queda dentro del ruido, y **Ask each question twice** lo mide | `measurement_noise`, `purpose: stability` |
| Review | Puntuaciones que esperan a que una persona las confirme o las cambie | `review_state` |
| Case generator | El agent de sistema que redacta casos a partir de un agent, su conocimiento, chats reales y red teaming | `kind: generator` |
| Proposed case | Un caso redactado que espera en **Generated** hasta que una persona lo acepta o lo descarta | `case_proposal` |
| Red teaming | Casos que comprueban que un agent rechaza lo que debe rechazar | etiqueta `red-team` |

## Cómo se mejora { #how-it-is-improved }

| En la consola | Qué es | En la API y el spec |
|---|---|---|
| Improve | Una sesión que lee qué salió mal con un agent, escribe cambios y los prueba, y espera a una persona entre un paso y otro; nunca publica por sí sola | `improvement` |
| Understand | El primer paso: separa las respuestas con valoraciones en lo que el agent puede corregir y lo que falta en la knowledge base | `stage: analyzing`, `stage: classifying` |
| Changes | El paso en el que el ayudante escribe los cambios de un intento y tú eliges cuáles probar | `stage: proposing`, `stage: filtering` |
| Check | El paso en el que la versión de hoy y la cambiada responden las mismas preguntas y ambas se califican; **Open the full check** abre su eval run | `stage: evaluating`, `stage: judging` |
| Result | Lo que dio la sesión: qué intento mejoró el agent, o que ninguno lo hizo, y qué se puede hacer después | `status: ready`, `status: stopped` |
| Accept | El último paso: **Publish version N** o **Keep as draft**; cualquiera de los dos termina la sesión | `POST /{run_id}/finish` |
| Attempt | Un intento dentro de una sesión: cambios escritos y luego comprobados con preguntas propias; como mucho tres por sesión | `improvement_iteration` |
| Helper that writes the changes | El agent que lee las valoraciones y escribe los cambios de cada intento; el asistente de autoría, salvo que se elija otro | `improver_agent_id` |
| Kept aside | Preguntas de prueba que un intento aparta para que el ayudante no las vea y solo ellas decidan su resultado | `improvement_partition: holdout` |
| Help write the changes | Preguntas de prueba que el ayudante lee mientras escribe los cambios de un intento; nunca deciden su resultado | `improvement_partition: train` |
| Try again | Empieza otro intento desde el resultado, con una **Note for the helper** opcional; escribe cambios nuevos y se detiene en **Changes** | `/{run_id}/continue` con `note` |
| Spending limit | Lo que una sesión puede gastar en total, con el análisis y cada intento incluidos; cada paso se presupuesta antes de empezar | `budget_usd` |
| Automatic check | **Check these questions automatically on every change**: al aceptar, una suite que hace las preguntas de la sesión antes de cada publicación y no admite ninguna regresión confirmada | `automatic_check` |

## Capabilities { #capabilities }

El nombre que muestra el Builder y el id que vincula el spec de un agent. Cada una
se describe en [Capabilities](capabilities.md).

| En la consola | En el spec |
|---|---|
| Apps | `artifacts` |
| Ask the user | `ask_user` |
| Web browser | `browser_use` |
| Chat channel lookup | `channel_tools` |
| Charts | `charts` |
| Date and time | `clock` |
| Calculations | `code_execution` |
| Coding agent | `coding_agent` |
| Long conversations | `compaction` |
| Computer use | `computer_use` |
| Context | `context` |
| Past conversations | `conversation_search` |
| Follow-ups | `follow_ups` |
| Guardrails | `guardrails` |
| Image generation | `image_generation` |
| Knowledge search | `knowledge` |
| Media offload | `media` |
| Memory | `memory_files` |
| Memory (mem0) | `memory_mem0` |
| Planning | `planning` |
| Work while tools run | `background_tools` |
| Sandbox | `sandbox` |
| Skills | `skills` |
| Subagents | `subagents` |
| Instruction reminders | `system_reminders` |
| Text to speech | `text_to_speech` |
| Thinking | `thinking` |
| Tool output limits | `tool_output_limits` |
| Tool search | `tool_search` |
| Video generation | `video_generation` |
| Visuals | `visuals` |
| Read web pages | `web_fetch` |
| Web search | `web_research` |
| Tables | `virtual_tables` |
| Workflows | `workflows` |
