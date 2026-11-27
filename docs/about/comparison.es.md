---
source_sha: "5881de747c1a"
title: "Compara AgenticOS"
seo_title: "Comparativas de AgenticOS: capa soberana de agents de IA"
description: "Compara AgenticOS con Claude, ChatGPT, Copilot Studio, Dify, n8n, Kortix, LobeHub, Onyx, Open WebUI, Langdock, Dust, deepset y los agents en Slack."
---

# Compara AgenticOS { #compare-agenticos }

La mayoría de los productos de este ámbito son una de cinco cosas: una app de asistente, un builder de agents, un servicio de compañero de equipo, una plataforma empresarial entregada o un agent de programación. AgenticOS es una capa soberana para los agents de una empresa que operas tú mismo. El punto de partida suele ser el mismo: las personas usan sus propias cuentas de IA, así que el conocimiento, la memoria y el gasto quedan fuera de la empresa, y TI quiere en su lugar un único sitio gobernado. Estas guías muestran dónde encaja cada opción y qué añade AgenticOS.

Mantenido por el equipo de AgenticOS. Fuentes de los proveedores revisadas el 21 de octubre de 2026 para las guías originales (las de OpenAI Frontier el 14 de octubre), el 2 de noviembre para Muse, Claude Duet, Grok Bot y OpenBot, y el 26 de noviembre de 2026 para las guías añadidas entonces: plataformas de código abierto, proveedores europeos, agents en Slack, el stack DIY y las condiciones de licencia. Revisar antes del 27 de febrero de 2027, o antes si un proveedor cambia la oferta que describe una guía. Cada guía indica sus fuentes. Para estas guías no se ha utilizado ninguna cuenta de un competidor.

Las funciones de AgenticOS se actualizaron el 27 de noviembre de 2026 con v1.95.0 en todas las guías. Las fechas anteriores de revisión de los proveedores no cambian; esta actualización no es una nueva auditoría de precios.

## Elige la guía para tu decisión { #pick-the-guide-for-your-decision }

| Estás valorando | Productos | Guía |
| --- | --- | --- |
| Un asistente de chat para la empresa, o agents propiedad de tu organización | Claude Team y Enterprise, ChatGPT Business y Enterprise | [Claude](claude-apps.md) · [ChatGPT](chatgpt.md) |
| Un builder dentro de la suite en la nube de un proveedor | Microsoft Copilot Studio, Google Gemini Enterprise | [Copilot Studio](copilot-studio.md) · [Gemini Enterprise](gemini-enterprise.md) |
| Un builder o una herramienta de automatización autoalojados | Dify, n8n | [Dify](dify.md) · [n8n](n8n.md) |
| Una plataforma de código abierto para los agents de la empresa | Kortix CompanyOS, LobeHub, Agno AgentOS, OpenAgents, OpenHuman | [Kortix](kortix.md) · [LobeHub](lobehub.md) · [Agno](agno.md) · [OpenAgents](openagents.md) · [OpenHuman](openhuman.md) |
| Un chat o un buscador corporativo autoalojado | Open WebUI, LibreChat, Onyx | [Open WebUI y LibreChat](open-webui-librechat.md) · [Onyx](onyx.md) |
| Montarlo con piezas de código abierto | Open WebUI, LiteLLM, Langfuse, n8n, Keycloak | [Stack DIY](diy-stack.md) · [Condiciones de licencia](licence-terms.md) |
| Una plataforma de IA europea | Langdock, Dust, Mistral, deepset | [Langdock](langdock.md) · [Dust](dust.md) · [Mistral](mistral.md) · [deepset](deepset.md) |
| Un agent dentro de Slack | Claude Tag, Slackbot | [Agents en Slack](slack-agents.md) |
| Un compañero de IA siempre activo con su propio ordenador | OpenAI dots, Grok Bot, Viktor, Sauna | [dots](openai-dots.md) · [Grok Bot](grok-bot.md) · [Viktor](viktor.md) · [Sauna](sauna.md) |
| La plataforma o el plano de control de un proveedor para los agents de una empresa | OpenAI Frontier, Microsoft Agent 365 | [Frontier](openai-frontier.md) · [Agent 365](microsoft-agent-365.md) |
| Un entorno alojado de agents para desarrolladores | Claude Managed Agents | [Managed Agents](claude-managed-agents.md) |
| Un agent personal de código abierto | OpenClaw, NVIDIA NemoClaw | [OpenClaw](openclaw.md) |
| Una plataforma empresarial entregada | Wonderful | [Wonderful](wonderful.md) |
| Un agent de programación, o una capa para todos los demás | Claude Code, OpenAI Codex, OpenCode | [Claude Code](claude-code.md) · [Codex](codex.md) · [OpenCode](opencode.md) |

## El panorama de un vistazo { #the-field-at-a-glance }

| Producto | Qué es | Dónde se ejecuta | Código fuente | Modelos |
| --- | --- | --- | --- | --- |
| **AgenticOS** | Una capa soberana para los agents de la empresa, construida en un navegador | Tu infraestructura | Apache-2.0 | 28 providers, incluidos los locales |
| Claude Team / Enterprise | El workspace de asistente de Anthropic | La nube de Anthropic | Propietario | Solo Claude |
| ChatGPT Business / Enterprise | El workspace de asistente de OpenAI, con agents de workspace | La nube de OpenAI | Propietario | Solo OpenAI |
| Copilot Studio | Un builder de agents low-code sobre Power Platform | La nube de Microsoft | Propietario | Modelos de OpenAI y Anthropic, además de Azure Foundry |
| Gemini Enterprise | La plataforma de agents y búsqueda para empleados de Google | Google Cloud | Propietario | Gemini en la app |
| Dify | Un builder visual de apps LLM y workflows | Autoalojado o Dify Cloud | Apache 2.0 modificada con condiciones | Muchos, incluido Ollama |
| n8n | Automatización de workflows con nodos de agent de IA | Autoalojado o n8n Cloud | Sustainable Use License | Muchos, incluido Ollama |
| Kortix CompanyOS | Una empresa como repositorio git de agents, skills y conectores | Nube de Kortix, o autoalojado con sesiones en la nube de Kortix | Elastic License 2.0 | Cualquiera |
| LobeHub | Un workspace de IA cuyos agents se unen a los chats del equipo | Nube de LobeHub o autoalojado | LobeHub Community License | Más de 90 providers |
| Agno AgentOS | Un framework y runtime en Python con un plano de control alojado | Runtime autoalojado; plano de control como SaaS | Runtime Apache-2.0; plano de control cerrado | Cualquiera |
| OpenAgents | Un workspace compartido para personas y agents de muchos runtimes | Alojado o autoalojado | Apache-2.0 | Los de los agents conectados |
| OpenHuman | Un harness de agents personal y una app de escritorio | Escritorio, terminal o servidor | GPL-3.0 | 26 providers y modelos locales |
| Open WebUI | Una interfaz de chat de IA autoalojada | Autoalojado | BSD-3 con cláusula de marca | Compatibles con OpenAI y Ollama |
| LibreChat | Un chat autoalojado con agents y MCP | Autoalojado | MIT; panel de administración AGPL-3.0 | Todos los providers principales |
| Onyx | Búsqueda y chat corporativos con agents | Autoalojado o nube de Onyx | MIT con directorios `ee` | Cualquiera |
| Langdock | Un workspace de IA por puesto con agents y workflows | SaaS en Azure en la UE | Propietaria | Varios modelos alojados en la UE |
| Dust | Un workspace alojado para los agents de la empresa | Nube de Dust, región de EE. UU. o de la UE | Propietaria | Varios providers |
| Mistral AI Studio | Modelos, asistente y plataforma de agents de un mismo proveedor | Nube, serverless o autoalojado | Plataforma propietaria | Sobre todo Mistral |
| deepset Haystack Enterprise Platform | Una plataforma soberana para agents y pipelines de Haystack | Nube, autoalojado, aislado de la red, STACKIT | Propietaria; Haystack Apache-2.0 | Cualquiera |
| Claude Tag / Slackbot | Agents de proveedores dentro de Slack | Nube de Anthropic o de Salesforce | Propietaria | Solo Claude / a elección de Salesforce |
| Viktor | Un compañero de equipo de IA por cada workspace de Slack o Teams | La nube de Viktor | Propietario | OpenAI, Anthropic, Google, xAI |
| Sauna | Un asistente de IA proactivo por persona, con memoria | La nube de Sauna | Propietario | Su propio modelo Lite, o todos los modelos desde el plan Basic |
| OpenAI dots | Agents siempre activos en ChatGPT, cada uno con un ordenador en la nube | La nube de OpenAI | Propietario | Solo OpenAI |
| Grok Bot | Compañeros con nombre en un ordenador compartido en la nube | La nube de xAI | Propietario | Solo Grok |
| OpenAI Frontier | Una plataforma para gestionar compañeros de IA de empresa | En local, tu nube o la de OpenAI | Propietario | OpenAI |
| Microsoft Agent 365 | Un plano de control sobre los agents de Microsoft 365 | La nube de Microsoft | Propietario | A través de los agents que gobierna |
| Claude Managed Agents | Un entorno alojado de agents para desarrolladores | La nube de Anthropic | Propietario | Solo Claude |
| OpenClaw / NemoClaw | Un agent personal de código abierto; la distribución empresarial de NVIDIA | Tu equipo o servidor | Código abierto | Muchos |
| Wonderful | Una plataforma empresarial de IA con equipos de despliegue | SaaS, single-tenant, tu nube u on-premises | Propietario | Independiente del modelo, enrutado por tarea |
| Claude Code | Un agent de programación para desarrolladores | Máquinas de los desarrolladores, nube de Anthropic | Propietario | Solo Claude |
| OpenAI Codex | Un agent de programación para desarrolladores | Máquinas de los desarrolladores, nube de OpenAI | CLI Apache-2.0, nube propietaria | OpenAI; la CLI admite también otros |
| OpenCode | Un agent de programación de código abierto | Máquinas de los desarrolladores | MIT | Más de 75 providers |

Cada celda procede de las propias páginas del proveedor; las guías las enlazan. "Propietario" describe la licencia, no la calidad.

## Cuánto queda en tus manos { #how-much-stays-yours }

Aquí la soberanía significa cuatro cosas que decides tú: dónde se ejecuta el producto, qué modelos puede usar, qué te permite hacer la licencia y si los controles que pide una revisión de TI y seguridad están disponibles sin un plan de pago. Cada celda procede de las guías de arriba o de las páginas del proveedor que enlazan.

| Producto | Dónde se ejecuta | Qué modelos puedes usar | Qué te permite la licencia | Inicio de sesión, auditoría y control del gasto |
| --- | --- | --- | --- | --- |
| **AgenticOS** | Tu infraestructura; una instalación nueva no envía prompts ni documentos a ninguna parte, y el diagnóstico está activado por defecto y se puede desactivar | Cualquiera de los 28 providers, o solo modelos locales | Apache-2.0: leerlo, modificarlo, ponerle tu marca y operarlo para otros; el parser de PDF por defecto es AGPL-3.0, así que una imagen modificada que sirvas a otros les debe su código fuente ([detalles](../licenses.md#the-agpl-component)) | Inicio de sesión: SSO OIDC, LDAP y Kerberos · Auditoría: registro con detección de manipulaciones · Gasto: budgets por agent y por organización · todo en cada despliegue |
| Claude Team / Enterprise | La nube de Anthropic | Solo Claude | Propietaria | Inicio de sesión: SSO en Team y Enterprise · Auditoría: Enterprise, 180 días de eventos · Gasto: límites por organización y por usuario |
| ChatGPT Business / Enterprise | La nube de OpenAI; en Enterprise, residencia del almacenamiento en diez regiones | Solo OpenAI | Propietaria | Inicio de sesión: SSO SAML en Business; SCIM y control de acceso basado en roles en Enterprise · Auditoría: Compliance API en Enterprise y Edu · Gasto: bolsas de créditos y límites de exceso |
| Copilot Studio | La nube de Microsoft, en entornos de Power Platform | Modelos GPT por defecto, modelos Claude, modelos de Azure Foundry facturados aparte | Propietaria | Inicio de sesión: Entra ID · Auditoría: Purview · Gasto: límites mensuales por agent |
| Gemini Enterprise | Google Cloud, en las regiones global, US, EU y algunas nacionales | Gemini; otros modelos solo en agents personalizados de Agent Platform | Propietaria | Inicio de sesión: Google Cloud IAM · Auditoría: registros de auditoría de Google Cloud · Gasto: límites mensuales en la cuenta de facturación |
| Dify | Autoalojado o Dify Cloud | Muchos, incluido Ollama | Apache 2.0 con condiciones: un servicio multiinquilino necesita permiso por escrito y el logotipo no se puede cambiar | Inicio de sesión: email; SSO en Enterprise · Auditoría: Enterprise · Gasto: facturación del provider o créditos de mensajes en Cloud |
| Kortix CompanyOS | Nube de Kortix, o autoalojado con las sesiones de los agents en sandboxes en la nube de Kortix | Cualquiera, con tus propias claves | Elastic License 2.0: sin servicio alojado para terceros y sin eludir la clave de licencia | Inicio de sesión: SAML y SCIM con clave Enterprise · Auditoría: leerla requiere Enterprise · Gasto: budget por workspace |
| LobeHub | Nube de LobeHub o autoalojado | Más de 90 providers | LobeHub Community License: uso comercial sin modificar el código; las obras derivadas requieren licencia comercial | Inicio de sesión: SAML en Enterprise · Auditoría: plan Business · Gasto: bolsa de créditos |
| Onyx | Autoalojado, también aislado de la red, o nube de Onyx | Cualquiera | Núcleo MIT; los directorios `ee` requieren en producción una licencia por puestos | Inicio de sesión: SCIM en Enterprise · Auditoría: flujo OCSF · Gasto: por workspace en Business, por persona y grupo en Enterprise |
| Open WebUI | Autoalojado, también aislado de la red | Compatibles con OpenAI y Ollama | BSD-3 con cláusula de marca por encima de 50 usuarios en 30 días | Inicio de sesión: OIDC, LDAP y SCIM · Auditoría: no indicada · Gasto: no indicado |
| LibreChat | Autoalojado | Todos los providers principales | MIT; panel de administración con roles personalizados en AGPL-3.0 | Inicio de sesión: OIDC, SAML, LDAP · Auditoría: cambios de permisos · Gasto: saldo de tokens por persona |
| Langdock | SaaS en Azure en la UE; single-tenant y on-premises en contratos grandes | Varios modelos alojados en la UE, claves propias | Propietaria | Inicio de sesión: SAML y SCIM en todos los planes · Auditoría: API, 90 días · Gasto: límites por workspace, persona, grupo, agent y workflow |
| Dust | Nube de Dust, región de EE. UU. o de la UE; sin autoalojamiento | Varios providers | Propietaria | Inicio de sesión: no revisado para esta guía · Auditoría: con detección de manipulaciones en Enterprise · Gasto: créditos por persona, grupo y clave de API |
| deepset Haystack Enterprise Platform | Nube, autoalojado, aislado de la red o STACKIT | Cualquiera | Plataforma propietaria; framework Haystack Apache-2.0 | Control de acceso y observabilidad; detalles a través de ventas |
| n8n | Autoalojado o n8n Cloud en Fráncfort | Muchos, incluido Ollama | Sustainable Use License: uso empresarial interno, no comercial o personal; las funciones de pago necesitan una clave de licencia que contacta a diario con el servidor de licencias de n8n | Inicio de sesión: SSO en planes de pago · Auditoría: streaming de logs en Enterprise · Gasto: cuotas de ejecuciones por plan |
| Viktor | La nube de Viktor, alojada en EE. UU. por defecto | Modelos de OpenAI, Anthropic, Google y xAI, o tu propia clave de OpenRouter | Propietaria | Inicio de sesión: SSO SAML · Auditoría: registros de auditoría en Enterprise · Gasto: bolsa de créditos con un tope mensual de recargas, límites por usuario en Enterprise |
| Sauna | La nube de Sauna; infraestructura en EE. UU. para clientes de EE. UU. | Su propio modelo Lite, o todos los modelos desde el plan Basic | Propietaria | Inicio de sesión: correo electrónico o Google · Auditoría: no indicada · Gasto: créditos por plan |
| OpenAI dots | La nube de OpenAI; el plan Pro no se ofreció al lanzamiento en el EEE, Suiza ni Reino Unido | Solo OpenAI | Propietaria | Inicio de sesión: cuentas de ChatGPT · Auditoría: no indicada para dots · Gasto: incluido en el plan |
| Grok Bot | Nube de xAI | Servicio Grok Bot | Propietario | Enterprise: logs, exportación OpenTelemetry, lista permitida MCP y SCIM; [alcance actual](grok-bot.md) |
| OpenAI Frontier | En local, tu nube o la de OpenAI | OpenAI | Propietaria | Inicio de sesión, auditoría y gasto: no indicados públicamente; anunciados permisos por agent y paneles |
| Microsoft Agent 365 | La nube de Microsoft | A través de los agents que gobierna | Propietaria | Inicio de sesión: Entra ID · Auditoría: Purview · Gasto: licencias de Microsoft 365 |
| Claude Managed Agents | La nube de Anthropic | Solo Claude | Propietaria | Inicio de sesión: claves de API de Anthropic · Auditoría: no indicada · Gasto: tokens más una tarifa por hora de sesión, límites de la organización |
| OpenClaw / NemoClaw | Tu equipo o servidor | Muchos | Código abierto; NemoClaw es la distribución de NVIDIA | Inicio de sesión, auditoría y control de acceso: mínimos en OpenClaw; añadidos por NemoClaw |
| Wonderful | SaaS multiinquilino, single-tenant, tu nube o on-premises aislado de la red | Enrutados por tarea por la plataforma | Propietaria; los agents y la configuración se exportan desde su UI o su API | Inicio de sesión: no indicado en sus páginas · Auditoría: registros de auditoría en su AI Gateway · Gasto: topes de presupuesto por equipo |

Dify, n8n, Onyx, Open WebUI, LibreChat y deepset también funcionan en tus propios servidores, y Wonderful ofrece un despliegue on-premises aislado de la red. Entre los productos de esta tabla, AgenticOS es el único en el que las cuatro respuestas quedan en tus manos.

Operar AgenticOS tú mismo no hace locales todos los modelos, parsers y herramientas. Cada servicio externo lo añades tú; consulta [por defecto no sale nada](../data-protection.md#nothing-leaves-by-default).

## Los límites de gasto son habituales; dónde se aplican, no { #spend-limits-are-common-where-they-apply-is-not }

Los límites de gasto por sí solos ya no distinguen a un producto. Claude Tag limita el gasto por organización y canal de Slack, Notion por miembro, Hermes Business por miembro del equipo, Amazon Quick por usuario, LiteLLM por clave, equipo y etiqueta, Kortix por workspace, Onyx por workspace o persona, Dust por persona y grupo, y Langdock incluso por agent, en su SaaS de pago.

AgenticOS combina un [budget por agent](../governance.md#budgets), comprobado [antes de cada petición al modelo](../governance.md#enforcement-is-before-the-request) sea cual sea el provider y el canal de la petición, con el [trabajo delegado](../governance.md#delegation-spends-the-parents-budget) cargado al agent que lo delegó, en el producto de código abierto gratuito en tus propios servidores, y registrado en el mismo registro de auditoría que las [aprobaciones](../governance.md#approvals).

## Código abierto, con condiciones { #open-source-with-conditions }

La mayoría de los rivales de código abierto añaden condiciones: Apache modificada (Dify, FastGPT), la Sustainable Use License (n8n), la Elastic License 2.0 (Kortix desde febrero de 2026), licencias propias (LobeHub, Open WebUI) o directorios enterprise (Onyx, LiteLLM, Langfuse). AgenticOS es Apache-2.0 y no reserva nada para una edición de pago. [Las condiciones de licencia comparadas](licence-terms.md) citan las cláusulas.

## Lo que AgenticOS aporta a cada comparación { #what-agenticos-brings-to-every-comparison }

Estos puntos recorren todas las guías, así que se exponen una sola vez aquí.

- **El despliegue es tuyo.** Se ejecuta en tu hardware con tu propio Postgres y tu propio almacenamiento, y una instalación nueva no envía prompts ni documentos a ninguna parte; el diagnóstico del deployment está activado por defecto y se puede desactivar. Es posible una configuración totalmente local, con modelos de chat locales, embeddings locales y procesamiento local de documentos. Consulta [qué sale por defecto](../data-protection.md#nothing-leaves-by-default).
- **Cualquier modelo, cambiado en un solo lugar.** [28 providers](../models.md#providers) se sitúan detrás de un [perfil de modelo](../models.md#a-model-profile) con [fallbacks](../models.md#fallbacks). Cambia el perfil y todos los agents que lo usan se mueven, sin volver a publicar.
- **Un agent es un documento versionado.** Publicar congela una [versión](../concepts.md#version), los [entornos](../environments.md#what-an-environment-is) apuntan a versiones, y el spec [se exporta como YAML](../features.md#exportable-into-your-own-repository) a tu propio repositorio git.
- **La gobernanza está en el producto de código abierto.** Los [budgets](../governance.md#enforcement-is-before-the-request) se comprueban antes de cada petición al modelo. Las [aprobaciones](../governance.md#approvals) detienen un run hasta que alguien decide. El [registro de auditoría](../governance.md#audit) detecta manipulaciones. Nada de esto espera a un plan empresarial.
- **Muchos equipos, un despliegue.** Las organizaciones son tenants, aislados en el esquema. El [modelo de permisos](../permissions.md#the-built-in-roles) tiene seis roles y grants por recurso. [El inicio de sesión único OIDC, LDAP y Kerberos](../directory.md#signing-in-with-a-directory-account) asignan grupos del directorio a roles.
- **Un agent, todas las superficies.** El mismo agent publicado responde en el chat web, un widget, una página alojada, la API HTTP, un WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, correo electrónico e iMessage, atiende [llamadas telefónicas](../voice.md#telephone-calls), y otros agents lo alcanzan por [A2A](../channels.md#a2a). Consulta [superficies](../channels.md).
- **Apps de escritorio y de teléfono.** La [app de escritorio](../desktop.md) añade la pregunta rápida, el trabajo en una carpeta aprobada de tu ordenador y agents de programación locales como Claude Code y Codex. La [app de teléfono](../mobile.md) muestra las aprobaciones pendientes en un widget y recibe contenido compartido desde otras apps.
- **Probado antes de publicarse.** Los [eval runs](../evals.md) puntúan una versión contra un dataset versionado y una baseline, las [suites](../evals.md#suites) pueden bloquear la promoción y el [asistente de autoría](../authoring.md) propone cambios a partir de evidencias.
- **Personas y agents en un mismo lugar.** Un [proyecto](../projects.md) da a un equipo y a sus agents archivos, instrucciones y chats compartidos, y el [coding agent](../reference/capabilities.md#coding-agent) pasa el trabajo de software a Claude Code o Codex en un sandbox. [AgenticOS también es un servidor MCP](../mcp.md#agenticos-as-an-mcp-server), así que esas herramientas pueden listar y ejecutar los agents de la empresa.
- **Extensible en código.** Una [capability](../howto/add-capability.md) es Python tipado, y [cualquier servidor MCP](../mcp.md) se conecta por URL. La configuración solo puede alcanzar lo que el código ha registrado.
- **Sin cuota por usuario.** Pagas directamente a tus providers de modelos y operas la infraestructura. Vstorm ofrece ayuda de implementación mediante un acuerdo aparte; consulta [operación e implementación](../rollout.md).

## Lo que AgenticOS todavía no hace { #what-agenticos-does-not-do-yet }

Una comparación que oculta sus propias carencias es un anuncio. Contrasta estos puntos con tus requisitos antes de un piloto.

- Los roles son los seis integrados; los roles personalizados todavía no están disponibles.
- El inicio de sesión todavía no tiene SAML ni SCIM; SAML funciona a través de un broker de identidad como Keycloak. Consulta [lo que el inicio de sesión con directorio todavía no hace](../directory.md#what-this-does-not-do-yet).
- No hay panel de trazas ni reranker. Existen el historial de runs, los costes y los resultados de los evals, y las trazas se exportan a Logfire. Consulta [dónde no está terminado](index.md#where-this-one-is-not-finished).
- No hay canal de WhatsApp. Las llamadas telefónicas requieren tu propio número de Twilio.
- No hay marketplace de plugins o nodos de la comunidad, y hay menos conectores listos que en las suites más grandes.
- No hay certificaciones de seguridad para un servicio gestionado: certificas tu propio despliegue, y la [página de seguridad](../security.md) relaciona sus controles.
- AgenticOS incluye un editor visual de workflows con pasos tipados. El trabajo de varios pasos usa delegación, planificación y disparadores.
- Una vinculación MCP configurada en `writes` confía en las marcas de solo lectura del propio servidor, así que una herramienta que marca mal como de solo lectura se ejecuta sin preguntar; `all` retiene cada llamada. Consulta [lo que MCP no te da](../mcp.md#what-mcp-does-not-get-you).
- OpenShift no está validado. Un [chart Helm de Kubernetes](../kubernetes.md) mantenido despliega API, worker y consola con servicios de datos externos; Docker Compose sigue siendo la vía para un solo host.
- Lo operas tú, o acuerdas la operación con Vstorm u otro partner.

## Una prueba común { #a-shared-trial }

Usa el ejemplo del [primer agent documental](../howto/first-document-agent.md) en ambos productos. Haz la pregunta con respuesta en la documentación y la pregunta sobre la política ausente. Cambia el responsable de la solicitud, vuelve a procesar la fuente y repite. Conserva las respuestas y la configuración reales, incluidos los fallos.

Registra la versión del producto o el plan de servicio, el modelo, el procesamiento de fuentes, la identidad, el acceso a herramientas, la configuración de aprobaciones, el canal, el coste y el responsable de la operación. Empieza solo con recuperación de información. Si importa una acción de herramienta, acuerda una acción de prueba inocua y su aprobación esperada antes de añadirla.

## Qué demuestra la evidencia { #what-the-evidence-means }

La descripción de un proveedor acredita una opción documentada, no su calidad en tu carga de trabajo. Para estas guías no se ha utilizado ninguna cuenta de un competidor. El comportamiento no probado queda como desconocido en lugar de convertirse en una marca de función ausente. Los precios y el contenido de los planes cambian a menudo, así que confírmalos en la página enlazada antes de citarlos.

Para una prueba publicada, informa de las entradas exactas, los resultados reales, los intentos fallidos y la configuración. Separa el consumo de modelos de la infraestructura, la implementación y la operación continua. Revisa las [licencias](../licenses.md), las condiciones de los providers y la edición que desplegarías.

## Preguntas frecuentes { #frequently-asked-questions }

### ¿AgenticOS es de código abierto? { #is-agenticos-open-source }

Sí. AgenticOS tiene licencia Apache-2.0 y se ejecuta en tu propia infraestructura con Docker Compose. Algunos componentes incluidos tienen sus propias licencias, que se enumeran en la página de [licencias](../licenses.md).

### ¿AgenticOS es una alternativa autoalojada a ChatGPT Enterprise o Claude Enterprise? { #is-agenticos-a-self-hosted-alternative-to-chatgpt-enterprise-or-claude-enterprise }

Para los agents que son propiedad de tu organización, sí. Ejecuta agents con cualquiera de los 28 providers de modelos, OpenAI y Anthropic incluidos, con budgets, aprobaciones y registros de auditoría en todos los despliegues. No es un asistente personal para cada empleado; consulta las guías de [ChatGPT](chatgpt.md) y [Claude](claude-apps.md).

### ¿Cuánto cuesta AgenticOS? { #how-much-does-agenticos-cost }

No hay cuota de licencia ni por puesto. Pagas a tus providers de modelos según sus propias tarifas y operas la infraestructura: bastan [4 vCPU y 8 GB de RAM](../deploy.md) para ejecutarlo. La ayuda de implementación de Vstorm se acuerda por separado.

### ¿Qué comparativa debería leer primero? { #which-comparison-should-i-read-first }

Empieza por el tipo de producto que estás valorando: una app de asistente, un builder dentro de una suite en la nube, un builder autoalojado, un servicio de compañero de equipo, una plataforma entregada o un agent de programación. La [tabla del principio](#pick-the-guide-for-your-decision) enlaza cada guía.

### ¿Es AgenticOS lo mismo que Agno AgentOS u otros productos «agent OS»? { #is-agenticos-the-same-as-agno-agentos-or-other-agent-os-products }

No. En 2026 muchos proveedores usan «agent OS» y «agentic OS», entre ellos Agno, Kortix y aiXplain. AgenticOS es la plataforma Apache-2.0 que mantiene Vstorm en github.com/vstorm-co/agenticos. Consulta [AgenticOS vs Agno AgentOS](agno.md).

### ¿Qué plataformas de código abierto están más cerca de AgenticOS? { #which-open-source-platforms-are-closest-to-agenticos }

Kortix CompanyOS y LobeHub describen la misma idea de agents que trabajan en los canales de una empresa; Onyx, Open WebUI y LibreChat son los chats autoalojados que TI suele desplegar primero; y OpenAgents coordina agents de muchos runtimes. La [tabla del principio](#pick-the-guide-for-your-decision) enlaza una guía para cada uno.

## Otros puntos de partida { #other-starting-points }

Una biblioteca como [Pydantic AI](https://ai.pydantic.dev/) encaja con un agent integrado en tu propia aplicación; AgenticOS se ejecuta sobre ella y añade la aplicación para configurar y operar agents. [OpenClaw](https://github.com/openclaw/openclaw) documenta despliegues personales y de equipos compartidos. [Lindy](https://www.lindy.ai/) ofrece un servicio de compañero de equipo. Son candidatos adicionales, no productos descartados aquí.

Empieza con la [tarea documental](../howto/first-document-agent.md) y después revisa [operación e implementación](../rollout.md). Los maintainers de AgenticOS son los responsables de estas guías.

[Muse](muse.md) · [Claude Duet](claude-duet.md) — Fuentes revisadas el 2 de noviembre de 2026; AgenticOS v1.35.0.

[AgenticOS vs OpenBot](openbot.md)
