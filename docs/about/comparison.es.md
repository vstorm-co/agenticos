---
source_sha: "eeabd2250add"
title: "Compara AgenticOS"
seo_title: "Comparativas de AgenticOS: plataforma de agents autoalojada"
description: "Compara AgenticOS, plataforma de agents de IA open source y autoalojada, con Claude, ChatGPT, Copilot Studio, Gemini Enterprise, Dify, n8n y agents de código."
---

# Compara AgenticOS { #compare-agenticos }

La mayoría de los productos de este ámbito son una de cinco cosas: una app de asistente, un builder de agents, un servicio de compañero de equipo, una plataforma empresarial entregada o un agent de programación. AgenticOS es una plataforma para los agents de una empresa que operas tú mismo. Estas guías muestran dónde encaja cada opción y qué añade AgenticOS.

Mantenido por el equipo de AgenticOS. Fuentes revisadas el 25 de septiembre de 2026. Versión de referencia de AgenticOS: v0.0.504. Revisar antes del 25 de octubre de 2026, o antes si un proveedor cambia la oferta que describe una guía. Cada guía indica sus fuentes. Para estas guías no se ha utilizado ninguna cuenta de un competidor.

## Elige la guía para tu decisión { #pick-the-guide-for-your-decision }

| Estás valorando | Productos | Guía |
| --- | --- | --- |
| Un asistente de chat para la empresa, o agents propiedad de tu organización | Claude Team y Enterprise, ChatGPT Business y Enterprise | [Claude](claude-apps.md) · [ChatGPT](chatgpt.md) |
| Un builder dentro de la suite en la nube de un proveedor | Microsoft Copilot Studio, Google Gemini Enterprise | [Copilot Studio](copilot-studio.md) · [Gemini Enterprise](gemini-enterprise.md) |
| Un builder o una herramienta de automatización autoalojados | Dify, n8n | [Dify](dify.md) · [n8n](n8n.md) |
| Un servicio de compañero de equipo en Slack o Teams | Viktor | [Viktor](viktor.md) |
| Una plataforma empresarial entregada | Wonderful | [Wonderful](wonderful.md) |
| Un agent de programación, o una plataforma para todos los demás | Claude Code, OpenAI Codex, OpenCode | [Claude Code](claude-code.md) · [Codex](codex.md) · [OpenCode](opencode.md) |

## El panorama de un vistazo { #the-field-at-a-glance }

| Producto | Qué es | Dónde se ejecuta | Código fuente | Modelos |
| --- | --- | --- | --- | --- |
| **AgenticOS** | Una plataforma para los agents de la empresa, construida en un navegador | Tu infraestructura | Apache-2.0 | 27 providers, incluidos los locales |
| Claude Team / Enterprise | El workspace de asistente de Anthropic | La nube de Anthropic | Propietario | Solo Claude |
| ChatGPT Business / Enterprise | El workspace de asistente de OpenAI, con agents de workspace | La nube de OpenAI | Propietario | Solo OpenAI |
| Copilot Studio | Un builder de agents low-code sobre Power Platform | La nube de Microsoft | Propietario | Modelos de OpenAI y Anthropic, además de Azure Foundry |
| Gemini Enterprise | La plataforma de agents y búsqueda para empleados de Google | Google Cloud | Propietario | Gemini en la app |
| Dify | Un builder visual de apps LLM y workflows | Autoalojado o Dify Cloud | Apache 2.0 modificada con condiciones | Muchos, incluido Ollama |
| n8n | Automatización de workflows con nodos de agent de IA | Autoalojado o n8n Cloud | Sustainable Use License | Muchos, incluido Ollama |
| Viktor | Un compañero de equipo de IA por cada workspace de Slack o Teams | La nube de Viktor | Propietario | OpenAI, Anthropic, Google, Kimi |
| Wonderful | Una plataforma empresarial de IA con equipos de despliegue | SaaS, single-tenant, tu nube u on-premises | Propietario | Independiente del modelo, enrutado por tarea |
| Claude Code | Un agent de programación para desarrolladores | Máquinas de los desarrolladores, nube de Anthropic | Propietario | Solo Claude |
| OpenAI Codex | Un agent de programación para desarrolladores | Máquinas de los desarrolladores, nube de OpenAI | CLI Apache-2.0, nube propietaria | OpenAI; la CLI admite también otros |
| OpenCode | Un agent de programación de código abierto | Máquinas de los desarrolladores | MIT | Más de 75 providers |

Cada celda procede de las propias páginas del proveedor; las guías las enlazan. "Propietario" describe la licencia, no la calidad.

## Lo que AgenticOS aporta a cada comparación { #what-agenticos-brings-to-every-comparison }

Estos puntos recorren todas las guías, así que se exponen una sola vez aquí.

- **El despliegue es tuyo.** Se ejecuta en tu hardware con tu propio Postgres y tu propio almacenamiento, y una instalación nueva no envía nada a ninguna parte. Es posible una configuración totalmente local, con modelos de chat locales, embeddings locales y procesamiento local de documentos. Consulta [nada sale por defecto](../data-protection.md#nothing-leaves-by-default).
- **Cualquier modelo, cambiado en un solo lugar.** [27 providers](../models.md#providers) se sitúan detrás de un [perfil de modelo](../models.md#a-model-profile) con [fallbacks](../models.md#fallbacks). Cambia el perfil y todos los agents que lo usan se mueven, sin volver a publicar.
- **Un agent es un documento versionado.** Publicar congela una [versión](../concepts.md#version), los [entornos](../environments.md#what-an-environment-is) apuntan a versiones, y el spec [se exporta como YAML](../features.md#exportable-into-your-own-repository) a tu propio repositorio git.
- **La gobernanza está en el producto de código abierto.** Los [budgets](../governance.md#enforcement-is-before-the-request) se comprueban antes de cada petición al modelo. Las [aprobaciones](../governance.md#approvals) detienen un run hasta que alguien decide. El [registro de auditoría](../governance.md#audit) detecta manipulaciones. Nada de esto espera a un plan empresarial.
- **Muchos equipos, un despliegue.** Las organizaciones son tenants, aislados en el esquema. El [modelo de permisos](../permissions.md#the-built-in-roles) tiene seis roles y grants por recurso. [El inicio de sesión único OIDC, LDAP y Kerberos](../directory.md#signing-in-with-a-directory-account) asignan grupos del directorio a roles.
- **Un agent, todas las superficies.** El mismo agent publicado responde en el chat web, un widget, una página alojada, la API HTTP, un WebSocket, Slack, Telegram y Mattermost. Consulta [superficies](../channels.md).
- **Extensible en código.** Una [capability](../howto/add-capability.md) es Python tipado, y [cualquier servidor MCP](../mcp.md) se conecta por URL. La configuración solo puede alcanzar lo que el código ha registrado.
- **Sin cuota por usuario.** Pagas directamente a tus providers de modelos y operas la infraestructura. Vstorm ofrece ayuda de implementación mediante un acuerdo aparte; consulta [operación e implementación](../rollout.md).

## Lo que AgenticOS todavía no hace { #what-agenticos-does-not-do-yet }

Una comparación que oculta sus propias carencias es un anuncio. Contrasta estos puntos con tus requisitos antes de un piloto.

- Los roles son los seis integrados; los roles personalizados todavía no están disponibles.
- El inicio de sesión todavía no tiene SAML ni SCIM; SAML funciona a través de un broker de identidad como Keycloak. Consulta [lo que el inicio de sesión con directorio todavía no hace](../directory.md#what-this-does-not-do-yet).
- No hay un entorno de evaluación ni un panel de trazas. Existen las valoraciones y el historial de runs. Consulta [dónde no está terminado](index.md#where-this-one-is-not-finished).
- No hay canal de conversación para Microsoft Teams, WhatsApp, voz ni correo electrónico.
- No hay un lienzo visual de workflows. El trabajo de varios pasos usa delegación, planificación y disparadores.
- La configuración de aprobaciones alcanza a las herramientas de las capabilities. Las herramientas MCP se controlan por conversación, no por herramienta. Consulta [lo que MCP no te da](../mcp.md#what-mcp-does-not-get-you).
- El despliegue es Docker Compose en un único host. No hay manifiestos de Kubernetes.
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

Para los agents que son propiedad de tu organización, sí. Ejecuta agents con cualquiera de los 27 providers de modelos, OpenAI y Anthropic incluidos, con budgets, aprobaciones y registros de auditoría en todos los despliegues. No es un asistente personal para cada empleado; consulta las guías de [ChatGPT](chatgpt.md) y [Claude](claude-apps.md).

### ¿Cuánto cuesta AgenticOS? { #how-much-does-agenticos-cost }

No hay cuota de licencia ni por puesto. Pagas a tus providers de modelos según sus propias tarifas y operas la infraestructura: bastan [4 vCPU y 8 GB de RAM](../deploy.md) para ejecutarlo. La ayuda de implementación de Vstorm se acuerda por separado.

### ¿Qué comparativa debería leer primero? { #which-comparison-should-i-read-first }

Empieza por el tipo de producto que estás valorando: una app de asistente, un builder dentro de una suite en la nube, un builder autoalojado, un servicio de compañero de equipo, una plataforma entregada o un agent de programación. La [tabla del principio](#pick-the-guide-for-your-decision) enlaza cada guía.

## Otros puntos de partida { #other-starting-points }

Una biblioteca como [Pydantic AI](https://ai.pydantic.dev/) encaja con un agent integrado en tu propia aplicación; AgenticOS se ejecuta sobre ella y añade la aplicación para configurar y operar agents. [OpenClaw](https://github.com/openclaw/openclaw) documenta despliegues personales y de equipos compartidos. [Lindy](https://www.lindy.ai/) ofrece un servicio de compañero de equipo. Son candidatos adicionales, no productos descartados aquí.

Empieza con la [tarea documental](../howto/first-document-agent.md) y después revisa [operación e implementación](../rollout.md). Los maintainers de AgenticOS son los responsables de estas guías.
