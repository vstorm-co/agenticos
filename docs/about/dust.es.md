---
title: "AgenticOS vs Dust"
seo_title: "AgenticOS vs Dust: agents alojados o en tus servidores"
description: "Compara Dust y AgenticOS: un SaaS francés para agents de empresa frente a una plataforma Apache-2.0 que alojas tú. Alojamiento, límites, auditoría y precios."
source_sha: "be4cedd13c05"
---

# AgenticOS vs Dust { #agenticos-vs-dust }

Dust se define como un sistema operativo multijugador para la IA en la empresa: agents que trabajan con los datos de la empresa, con MCP como cliente y servidor, y agents en Slack, Microsoft Teams, correo electrónico y Zendesk. Es un servicio alojado en una región de EE. UU. o de la UE, con alojamiento single-tenant en Enterprise. AgenticOS ofrece agents para el mismo comprador en una infraestructura que operas tú, con Apache-2.0 y sin coste por puesto.

Mantenido por el equipo de AgenticOS. Fuentes revisadas el 26 de noviembre de 2026. Versión de referencia de AgenticOS: v1.95.0. Alcance de Dust: su web, su página de precios, su documentación para administradores y la cobertura de prensa de su financiación de mayo de 2026; no un workspace probado.

## De un vistazo { #at-a-glance }

| Área | Dust | AgenticOS |
| --- | --- | --- |
| Qué es | Un workspace alojado para agents de empresa sobre los datos de la empresa | Una plataforma para los agents de la empresa, workflows, apps y tablas que operas tú |
| Licencia | Propietaria | Apache-2.0; consulta las [licencias de los componentes incluidos](../licenses.md) |
| Dónde se ejecuta | Nube de Dust, región de EE. UU. o de la UE; single-tenant en Enterprise; sin autoalojamiento | Tu infraestructura, cualquier nube u on-premises |
| Modelos | Varios providers | 28 providers, incluidos locales |
| Control del gasto | Límites de créditos por persona, grupo y clave de API, comprobados antes de cada mensaje | Un budget mensual por agent y por organización, comprobado antes de cada petición al modelo |
| Auditoría | Con detección de manipulaciones en Enterprise | Registro de auditoría con detección de manipulaciones en todos los despliegues |
| MCP | Cliente y servidor | Cliente y [servidor](../mcp.md#agenticos-as-an-mcp-server) |
| Canales | Web, Slack, Microsoft Teams, correo electrónico, Zendesk | Chat web, widget, página alojada, API HTTP, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, correo electrónico, iMessage, llamadas telefónicas |
| Precios | Pro 24 €, Max 120 € por usuario al mes con pago anual; Enterprise a medida | Sin coste de licencia ni por puesto; el uso de modelos a las tarifas de tu provider |

## Dónde llega más lejos AgenticOS { #where-agenticos-goes-further }

### El alojamiento que elijas { #hosting-you-choose }

Dust solo funciona en su propia nube. AgenticOS se ejecuta [donde lo despliegues](../deploy.md), también on-premises y aislado de la red, con modelos locales si tus datos no pueden salir. Consulta [qué sale por defecto](../data-protection.md#nothing-leaves-by-default).

### Límites en el agent, no solo en la persona { #limits-on-the-agent-not-only-on-the-person }

Dust limita los créditos por persona, grupo y clave de API. AgenticOS limita además cada agent: un [budget mensual](../governance.md#budgets) comprobado [antes de cada petición al modelo](../governance.md#enforcement-is-before-the-request), de modo que un agent que entra en bucle o se usa mucho se detiene en su propio límite sin bloquear a nadie más.

### Gobernanza en el producto de código abierto { #governance-in-the-open-source-product }

El [registro de auditoría con detección de manipulaciones](../governance.md#audit), las [aprobaciones](../governance.md#approvals), el [inicio de sesión con directorio](../directory.md#signing-in-with-a-directory-account) y las [muchas organizaciones](../concepts.md#organizations) están en todos los despliegues de AgenticOS, no reservados a un contrato enterprise.

### Sin coste por puesto { #no-seat-fee }

Dust cobra por usuario. AgenticOS no cobra nada por usuario; pagas a los providers de modelos y operas la infraestructura, tú o con Vstorm.

## Cuándo encaja mejor Dust { #when-dust-is-the-better-fit }

- Quieres un servicio gestionado que arranque en minutos y no tienes un equipo para operar servidores.
- Sus conectores y su integración con Zendesk cubren tus sistemas.
- SAML y SCIM son un requisito; AgenticOS aún no tiene ninguno.

## Compara un cambio, no solo una respuesta { #compare-a-change-not-only-an-answer }

Crea el mismo agent sobre los mismos documentos en ambos productos. Limita el gasto del agent a unos céntimos y comprueba qué pasa al llegar al límite. Después pregunta a tu equipo de seguridad cuál de los dos puede mantener todos los prompts y documentos dentro de tu red. Anota los resultados con el [método de comparación](comparison.md#a-shared-trial).

## Preguntas frecuentes { #frequently-asked-questions }

### ¿Se puede autoalojar Dust? { #can-dust-be-self-hosted }

No según sus páginas públicas: funciona en la nube de Dust, en una región de EE. UU. o de la UE, con alojamiento single-tenant en Enterprise. AgenticOS es autoalojado por diseño.

### ¿Tiene Dust límites de gasto? { #does-dust-have-spend-limits }

Sí, límites de créditos por persona, grupo y clave de API, comprobados antes de cada mensaje. AgenticOS añade un budget por agent y por organización, comprobado antes de cada petición al modelo.

## Comparativas relacionadas { #related-comparisons }

[AgenticOS vs Langdock](langdock.md) · [AgenticOS vs deepset](deepset.md) · [Agents en Slack](slack-agents.md) · [Todas las comparativas](comparison.md)

## Fuentes { #sources }

- [Dust](https://dust.tt) y [precios](https://dust.tt/pricing): descripción del producto, regiones de alojamiento y planes.
- [Gestión de créditos](https://docs.dust.tt/docs/user-documentation/admins/usage-seats-and-credits/credit-management): límites de créditos por persona, grupo y clave de API.
- [Dust levanta 40 M USD en su serie B](https://tech.eu/2026/05/18/dust-raises-40m-series-b-to-build-the-multiplayer-operating-system-for-enterprise-ai/): la descripción como «sistema operativo multijugador».
