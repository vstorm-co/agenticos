---
title: "AgenticOS vs LobeHub"
seo_title: "AgenticOS vs LobeHub: agents en tu equipo, autoalojados"
description: "Compara LobeHub y AgenticOS: LobeHub Community License frente a Apache-2.0, canales del equipo, budgets, aprobaciones, auditoría, roles y multi-tenancy."
source_sha: "277af3a6a45c"
---

# AgenticOS vs LobeHub { #agenticos-vs-lobehub }

LobeHub llama a su producto «superagents en tu equipo»: agents que se añaden a las herramientas de chat que el equipo ya usa, con un workspace, más de 90 providers, MCP, memoria y un mercado de skills. AgenticOS hace la misma promesa de agents en los canales del equipo. Las diferencias están en la licencia, en la gobernanza de cada agent y en cuántas organizaciones puede atender un despliegue.

Mantenido por el equipo de AgenticOS. Fuentes revisadas el 26 de noviembre de 2026. Versión de referencia de AgenticOS: v1.95.0. Alcance de LobeHub: su web, su página de precios, su documentación y el archivo `LICENSE` en `lobehub/lobehub`; no un workspace probado ni un despliegue autoalojado.

## De un vistazo { #at-a-glance }

| Área | LobeHub | AgenticOS |
| --- | --- | --- |
| Qué es | Un workspace de IA con agents que se unen a los chats del equipo | Una consola donde un equipo de negocio crea agents versionados, workflows, apps y tablas |
| Licencia | LobeHub Community License: Apache 2.0 con condiciones comerciales añadidas | Apache-2.0; consulta las [licencias de los componentes incluidos](../licenses.md) |
| Dónde se ejecuta | Nube de LobeHub o autoalojado con Docker | Tu infraestructura |
| Modelos | Más de 90 providers | 28 providers, incluidos locales |
| Canales | Discord, Slack, Telegram, LINE, WeChat, Feishu, DingTalk y otros; WhatsApp e iMessage anunciados; sin Microsoft Teams | Chat web, widget, página alojada, API HTTP, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, correo electrónico, iMessage, llamadas telefónicas |
| Control del gasto | Una bolsa de créditos con seguimiento del uso | Un budget mensual por agent y por organización, comprobado antes de cada petición al modelo |
| Aprobaciones | Las confirma la persona que usa el agent | Aprobación por capability, herramienta y conexión MCP, decidida por las personas que elijas |
| Roles y auditoría | Roles y auditoría en el plan de workspace Business; SAML en Enterprise | Seis roles, concesiones por recurso, SSO con OIDC, LDAP, Kerberos y un registro de auditoría con detección de manipulaciones en todos los despliegues |
| AgenticOS como servidor MCP | Cliente MCP; su propio servidor MCP anunciado | Cliente MCP y [servidor MCP](../mcp.md#agenticos-as-an-mcp-server) |
| Precios | Planes personales de 20, 100 y 200 USD al mes; planes de workspace desde 19,90 USD al mes | Sin coste de licencia; el uso de modelos a las tarifas de tu provider |

## Dónde llega más lejos AgenticOS { #where-agenticos-goes-further }

### Una licencia sin condiciones comerciales { #a-licence-without-commercial-conditions }

La LobeHub Community License se basa en Apache 2.0 con condiciones añadidas. LobeHub puede usarse comercialmente como servicio de frontend y backend **sin modificar el código fuente**. Desarrollar y distribuir una obra derivada requiere una licencia comercial del productor, y los contribuidores aceptan que el productor pueda endurecer las condiciones. Las funciones de negocio no forman parte del build de código abierto.

AgenticOS es Apache-2.0. Puedes modificarlo, ponerle tu marca y ejecutarlo para otros. Consulta las [condiciones de licencia comparadas](licence-terms.md).

### Gobernanza en cada agent { #governance-on-every-agent }

Un agent de AgenticOS tiene un propietario, [versiones](../concepts.md#version) publicadas, un [budget](../governance.md#budgets) comprobado antes de cada petición al modelo y [aprobaciones](../governance.md#approvals) dirigidas a alguien distinto de quien conversa. Una segunda decisión sobre una aprobación ya decidida se rechaza, y cada acción queda en el [registro de auditoría](../governance.md#audit). En LobeHub el gasto se sigue contra una bolsa de créditos y una llamada a herramienta la confirma su usuario.

### Microsoft Teams, teléfono y correo { #microsoft-teams-phone-and-email }

Un agent publicado de AgenticOS responde en [Microsoft Teams](../channels.md#microsoft-teams), por [correo electrónico](../channels.md#email), [SMS](../channels.md#sms) y [llamadas telefónicas](../voice.md#telephone-calls), y en los mismos canales de Slack, Telegram y Discord que cubre LobeHub. LobeHub no incluye un canal de Teams.

### Muchas organizaciones en un despliegue { #many-organizations-in-one-deployment }

Las [organizaciones](../concepts.md#organizations) de AgenticOS son tenants aislados en el esquema, así que un despliegue atiende a varias empresas o departamentos. LobeHub no describe aislamiento entre tenants para una instalación autoalojada.

## Cuándo encaja mejor LobeHub { #when-lobehub-is-the-better-fit }

- Quieres una experiencia de chat pulida, de nivel consumidor, y un gran mercado de skills para un equipo pequeño.
- Tus equipos trabajan en LINE, WeChat, Feishu o DingTalk, que AgenticOS no cubre.
- Lo usarás sin modificar, o la licencia comercial te encaja.

## Compara un cambio, no solo una respuesta { #compare-a-change-not-only-an-answer }

Añade un agent al mismo canal de Slack en ambos productos. Pídele una herramienta que requiera aprobación y decide la aprobación como alguien distinto de quien preguntó. Da al agent un budget de unos céntimos y supéralo. Anota lo que cada producto permite, rechaza y registra, con el [método de comparación](comparison.md#a-shared-trial).

## Preguntas frecuentes { #frequently-asked-questions }

### ¿Es LobeHub de código abierto? { #is-lobehub-open-source }

Su código es público con la LobeHub Community License, que añade condiciones a Apache 2.0: el uso comercial está permitido sin modificar el código, y distribuir una obra derivada requiere una licencia comercial. AgenticOS es Apache-2.0 sin más.

### ¿Pueden los agents de AgenticOS unirse a los chats del equipo como los de LobeHub? { #can-agenticos-agents-join-team-chats-like-lobehub-agents }

Sí. Un agent publicado responde en Slack, Microsoft Teams, Telegram, Mattermost, Discord y Matrix, y también puede seguir un canal de forma pasiva. Las peticiones de un usuario vinculado se ejecutan como esa persona.

### ¿Cuál controla mejor el coste? { #which-one-controls-cost-better }

LobeHub sigue el uso contra una bolsa de créditos. AgenticOS detiene la siguiente petición al modelo de un agent cuando alcanza su budget o el límite de la organización, y registra también el coste de un run fallido.

## Comparativas relacionadas { #related-comparisons }

[AgenticOS vs Kortix](kortix.md) · [AgenticOS vs Open WebUI y LibreChat](open-webui-librechat.md) · [Agents en Slack](slack-agents.md) · [Todas las comparativas](comparison.md)

## Fuentes { #sources }

- [LobeHub](https://lobehub.com): descripción del producto, canales y precios.
- [Licencia de `lobehub/lobehub`](https://github.com/lobehub/lobehub/blob/main/LICENSE): las condiciones de la LobeHub Community License citadas.
- [Repositorio de LobeHub](https://github.com/lobehub/lobehub): providers, compatibilidad con MCP y el build autoalojado.
