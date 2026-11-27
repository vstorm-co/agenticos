---
title: "AgenticOS vs Open WebUI y LibreChat"
seo_title: "AgenticOS vs Open WebUI y LibreChat: chat o agents"
description: "Compara Open WebUI, LibreChat y AgenticOS: un chat corporativo autoalojado frente a una plataforma de agents gobernados, licencias, budgets y canales."
source_sha: "041b493e450a"
---

# AgenticOS vs Open WebUI y LibreChat { #agenticos-vs-open-webui-and-librechat }

Open WebUI y LibreChat son las interfaces de chat autoalojadas que los equipos de TI suelen desplegar primero, para que los empleados dejen de pegar datos de la empresa en cuentas personales de IA. Ambas son maduras, se conectan a muchos modelos y añaden herramientas, conocimiento y agents. AgenticOS responde a otra pregunta: no «qué ventana de chat damos a la gente», sino «qué agents posee la empresa, quién responde de ellos y cuánto pueden gastar».

Mantenido por el equipo de AgenticOS. Fuentes revisadas el 26 de noviembre de 2026. Versión de referencia de AgenticOS: v1.95.0. Alcance: los repositorios públicos, los archivos de licencia y la documentación de Open WebUI y LibreChat; no despliegues probados.

## De un vistazo { #at-a-glance }

| Área | Open WebUI | LibreChat | AgenticOS |
| --- | --- | --- | --- |
| Qué es | Una interfaz de IA autoalojada con RBAC, grupos, herramientas y RAG | Un «clon mejorado de ChatGPT» con agents, MCP y skills | Una plataforma para agents de empresa versionados, workflows, apps y tablas |
| Licencia | BSD-3 con cláusula de marca: cambiar la marca se permite hasta 50 usuarios en 30 días; por encima, requiere licencia enterprise | MIT; su panel de administración (roles personalizados, grupos) es AGPL-3.0 | Apache-2.0; consulta las [licencias de los componentes incluidos](../licenses.md) |
| Propietario | Open WebUI Inc. | ClickHouse, desde noviembre de 2025 | Vstorm |
| Acceso | OIDC, LDAP y SCIM incluidos | OIDC, SAML y LDAP | SSO con OIDC, LDAP y Kerberos; aún sin SAML ni SCIM |
| Control del gasto | No descrito | Un saldo de tokens por usuario | Un budget mensual por agent y por organización, comprobado antes de cada petición al modelo |
| Aprobaciones | No descritas | Las confirma el usuario | Aprobación por capability, herramienta y conexión MCP, decidida por las personas que elijas |
| Ciclo de vida del agent | Modelos y presets | Agents con listas de control de acceso | Versiones publicadas, entornos, eval runs y exportación a YAML |
| Canales | Solo web; sin bots en mensajería externa | Web; Slack en beta | Chat web, widget, página alojada, API HTTP, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, correo electrónico, iMessage, llamadas telefónicas |
| Tenants | Una organización | Aislamiento entre tenants mediante un proxy | Muchas organizaciones en un despliegue |

## Dónde llega más lejos AgenticOS { #where-agenticos-goes-further }

### Una ventana de chat no es un agent que posea la empresa { #a-chat-window-is-not-an-agent-the-company-owns }

Ambas interfaces permiten elegir un modelo o un preset y hablar con él. En AgenticOS un agent tiene propietario, una [versión publicada](../concepts.md#version), [entornos](../environments.md#what-an-environment-is), [eval runs](../evals.md) contra un dataset versionado y un spec que se [exporta a YAML](../features.md#exportable-into-your-own-repository). Cuando el agent cambia, sabes quién lo cambió, puedes probarlo antes de publicarlo y volver atrás.

### Gasto y aprobaciones por agent { #spend-and-approvals-per-agent }

Un [budget](../governance.md#budgets) de AgenticOS detiene la siguiente petición al modelo de un agent cuando se alcanza su límite o el de la organización; LibreChat cuenta un saldo por usuario, y Open WebUI no describe un límite de gasto. Una llamada a herramienta puede esperar la [aprobación](../governance.md#approvals) de alguien distinto de quien conversa, y cada decisión queda en el [registro de auditoría con detección de manipulaciones](../governance.md#audit).

### El mismo agent donde la gente ya trabaja { #the-same-agent-where-people-already-work }

Un agent publicado de AgenticOS responde en [Slack](../channels.md#slack), [Microsoft Teams](../channels.md#microsoft-teams), por [correo electrónico](../channels.md#email), en un [widget web](../channels.md#the-website-widget) y por la [API HTTP](../channels.md#the-public-api), no solo en su propia interfaz web. Las apps de [escritorio](../desktop.md) y de [teléfono](../mobile.md) añaden la pregunta rápida y las aprobaciones sobre la marcha.

### Condiciones de licencia sin cláusulas de marca { #licence-terms-without-branding-conditions }

La licencia de Open WebUI prohíbe cambiar su marca por encima de 50 usuarios en 30 días sin licencia enterprise. El núcleo de LibreChat es MIT, pero el panel de administración con roles personalizados y grupos es AGPL-3.0. AgenticOS es Apache-2.0. Consulta las [condiciones de licencia comparadas](licence-terms.md).

## Cuándo encaja mejor Open WebUI o LibreChat { #when-open-webui-or-librechat-is-the-better-fit }

- Necesitas un chat corporativo con elección de modelo para cada empleado, y los agents con propietario y budget todavía no son el objetivo.
- Necesitas SAML o SCIM hoy. Open WebUI incluye SCIM y LibreChat incluye SAML; AgenticOS aún no tiene ninguno.
- Tus usuarios ejecutan modelos locales con Ollama y valoran la gran comunidad de estas interfaces.

También pueden convivir: mantén una interfaz de chat para el día a día y ejecuta los agents de la empresa en AgenticOS, accesible por la [API HTTP](../channels.md#the-public-api) y como [servidor MCP](../mcp.md#agenticos-as-an-mcp-server).

## Compara un cambio, no solo una respuesta { #compare-a-change-not-only-an-answer }

Elige una tarea que cambie algo, como abrir un ticket. Configúrala en ambos productos, dásela a dos equipos, exige la aprobación de una segunda persona y limita su gasto. Después cambia las instrucciones y comprueba quién puede ver qué cambió y cuándo. Anota los resultados con el [método de comparación](comparison.md#a-shared-trial).

## Preguntas frecuentes { #frequently-asked-questions }

### ¿Es AgenticOS un ChatGPT autoalojado como Open WebUI? { #is-agenticos-a-self-hosted-chatgpt-like-open-webui }

Incluye chat web, pero está construido en torno a los agents de la empresa: cada uno con propietario, versiones, budget, aprobaciones y canales. Open WebUI y LibreChat están construidos en torno a la propia interfaz de chat.

### ¿Puedo mantener Open WebUI y añadir AgenticOS? { #can-i-keep-open-webui-and-add-agenticos }

Sí. Muchos equipos mantienen una interfaz de chat y ejecutan agents gobernados a su lado. Los agents de AgenticOS responden por la API HTTP, Slack, Teams y las demás superficies, y AgenticOS también es un servidor MCP.

### ¿Qué licencia es más permisiva? { #which-licence-is-more-permissive }

El código propio de AgenticOS es Apache-2.0, sin directorio enterprise ni cláusula de marca; los componentes incluidos mantienen sus licencias, y el parser de PDF por defecto es AGPL-3.0 ([detalles](../licenses.md#the-agpl-component)). El núcleo de LibreChat es MIT con un panel de administración AGPL-3.0. La licencia BSD-3 de Open WebUI añade una cláusula de marca por encima de 50 usuarios.

## Comparativas relacionadas { #related-comparisons }

[AgenticOS vs un stack DIY](diy-stack.md) · [AgenticOS vs Onyx](onyx.md) · [AgenticOS vs LobeHub](lobehub.md) · [Todas las comparativas](comparison.md)

## Fuentes { #sources }

- [Repositorio de Open WebUI](https://github.com/open-webui/open-webui) y [licencia](https://docs.openwebui.com/license): funciones, opciones de acceso y la cláusula de marca.
- [Repositorio de LibreChat](https://github.com/LibreChat-AI/LibreChat): agents, MCP, opciones de acceso y el panel de administración AGPL-3.0.
- [Configuración de saldo de LibreChat](https://www.librechat.ai/docs/configuration/librechat_yaml/object_structure/balance): saldo de tokens por usuario.
- [ClickHouse adquiere LibreChat](https://clickhouse.com/blog/clickhouse-acquires-librechat): propietario desde noviembre de 2025.
