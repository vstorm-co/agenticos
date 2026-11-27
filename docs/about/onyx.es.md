---
title: "AgenticOS vs Onyx"
seo_title: "AgenticOS vs Onyx: buscador corporativo o agents de empresa"
description: "Compara Onyx y AgenticOS: búsqueda y chat corporativos frente a agents gobernados, la licencia ee, límites de gasto, aprobaciones, canales y precios."
source_sha: "e335c0e76f47"
---

# AgenticOS vs Onyx { #agenticos-vs-onyx }

Onyx es una plataforma de IA de código abierto construida en torno a la búsqueda corporativa: chat con cualquier modelo sobre más de 40 conectores, con agents, MCP y bots en Slack y Discord. AgenticOS parte del agent: cada uno tiene propietario, versiones, budget y aprobaciones, y responde en muchos canales. Si todo el trabajo es recuperar información de muchas fuentes SaaS, Onyx es fuerte. Si los agents actúan en nombre de la empresa, la gobernanza es distinta.

Mantenido por el equipo de AgenticOS. Fuentes revisadas el 26 de noviembre de 2026. Versión de referencia de AgenticOS: v1.95.0. Alcance de Onyx: su repositorio, sus archivos de licencia, su documentación y su página de precios; no un despliegue probado.

## De un vistazo { #at-a-glance }

| Área | Onyx | AgenticOS |
| --- | --- | --- |
| Qué es | Chat y búsqueda corporativa sobre las fuentes de la empresa, con agents | Agents de empresa versionados, workflows, apps y tablas, creados en el navegador |
| Licencia | MIT, con directorios `ee` bajo la Onyx Enterprise License | Apache-2.0; consulta las [licencias de los componentes incluidos](../licenses.md) |
| Dónde se ejecuta | Autoalojado, también aislado de la red, o nube de Onyx | Tu infraestructura |
| Conocimiento | Más de 40 conectores, buena recuperación | [Bases de conocimiento](../file-processing.md) con control del parser y conectores sincronizados; aún sin reranker |
| Control del gasto | Límites de gasto por workspace en Business, por usuario y grupo en Enterprise | Un budget mensual por agent y por organización, comprobado antes de cada petición al modelo |
| Aprobaciones | Las confirma el usuario, en su función Craft | Aprobación por capability, herramienta y conexión MCP, decidida por las personas que elijas |
| Roles y acceso | Roles personalizados y SCIM en Enterprise | Seis roles y concesiones por recurso; SSO con OIDC, LDAP y Kerberos |
| Tenants | Una organización por instalación autoalojada | Muchas organizaciones en un despliegue |
| Canales | Web, bots de Slack y Discord, widget, app de escritorio, extensión de Chrome | Chat web, widget, página alojada, API HTTP, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, correo electrónico, iMessage, llamadas telefónicas; apps de escritorio y de teléfono |
| Precios | Community gratis; Business 20 USD por usuario al mes; Enterprise a medida | Sin coste de licencia; el uso de modelos a las tarifas de tu provider |

## Dónde llega más lejos AgenticOS { #where-agenticos-goes-further }

### Un agent es un objeto con propietario { #an-agent-is-an-object-with-an-owner }

En AgenticOS un agent es un [spec versionado](../concepts.md#version): instrucciones, modelo, capabilities y budget, publicado como una versión que los [entornos](../environments.md#what-an-environment-is) promocionan y que se exporta como YAML. Un responsable de negocio lo cambia en el [Builder](../features.md#exportable-into-your-own-repository), y cada cambio se puede leer después.

### Gobernanza en el producto de código abierto { #governance-in-the-open-source-product }

El uso en producción de los directorios `ee` de Onyx requiere una licencia por número de puestos, y los límites de gasto por usuario y grupo, SCIM y los roles personalizados son funciones Enterprise. AgenticOS incluye [budgets](../governance.md#enforcement-is-before-the-request), [aprobaciones](../governance.md#approvals), el [registro de auditoría con detección de manipulaciones](../governance.md#audit) y el [inicio de sesión con directorio](../directory.md#signing-in-with-a-directory-account) en todos los despliegues, sin coste por puesto.

### Aprobación por alguien distinto del usuario { #approval-by-someone-other-than-the-user }

Una llamada a herramienta en AgenticOS puede esperar a una persona que elijas, [avisada](../governance.md#alerts) en la consola, en un canal o en la [app de teléfono](../mobile.md). Onyx describe la confirmación por el usuario en su función Craft.

### Canales más allá del chat { #channels-beyond-chat }

El mismo agent publicado responde en [Microsoft Teams](../channels.md#microsoft-teams), por [correo electrónico](../channels.md#email), [SMS](../channels.md#sms), [llamadas telefónicas](../voice.md#telephone-calls) y en una [página alojada](../channels.md#a-hosted-page), y otros agents lo alcanzan por [A2A](../channels.md#a2a).

## Cuándo encaja mejor Onyx { #when-onyx-is-the-better-fit }

- La búsqueda en muchas fuentes SaaS es el trabajo principal y sus conectores cubren tus sistemas.
- La calidad de recuperación en esas fuentes te importa más que gobernar lo que hacen los agents.
- Te basta una organización por instalación y el precio por puesto te encaja.

## Compara un cambio, no solo una respuesta { #compare-a-change-not-only-an-answer }

Conecta la misma fuente en ambos productos y haz las preguntas del [primer agent de documentos](../howto/first-document-agent.md). Después da a un agent una herramienta que cambie algo inofensivo, exige la aprobación de una segunda persona y limita su budget a unos céntimos. Anota lo que cada producto permite, rechaza y registra, con el [método de comparación](comparison.md#a-shared-trial).

## Preguntas frecuentes { #frequently-asked-questions }

### ¿Es Onyx de código abierto? { #is-onyx-open-source }

Casi todo es MIT. El código de sus directorios `ee` está bajo la Onyx Enterprise License, que requiere una licencia por puestos para usarlo en producción. AgenticOS no tiene directorio enterprise: su propio código es Apache-2.0, y los componentes incluidos mantienen sus licencias, como el parser de PDF por defecto, AGPL-3.0 ([detalles](../licenses.md#the-agpl-component)).

### ¿Sustituye AgenticOS a un buscador corporativo? { #does-agenticos-replace-enterprise-search }

Responde desde bases de conocimiento con conectores sincronizados y control del parser, pero se centra en agents que actúan. Si buscar en decenas de herramientas SaaS es la necesidad principal, compara primero la cobertura de conectores.

### ¿Pueden ambos funcionar aislados de la red? { #can-both-run-air-gapped }

Sí. Onyx documenta el despliegue aislado de la red, y AgenticOS funciona con modelos locales, embeddings locales y procesamiento local de documentos en tu propio hardware.

## Comparativas relacionadas { #related-comparisons }

[AgenticOS vs Open WebUI y LibreChat](open-webui-librechat.md) · [AgenticOS vs un stack DIY](diy-stack.md) · [AgenticOS vs Dify](dify.md) · [Todas las comparativas](comparison.md)

## Fuentes { #sources }

- [Repositorio de Onyx](https://github.com/onyx-dot-app/onyx): funciones, conectores, opciones de despliegue y la división de licencias citada.
- [Precios de Onyx](https://onyx.app/pricing): planes Community, Business y Enterprise.
- [Límites de gasto](https://docs.onyx.app/admins/advanced_configs/spending_limits): límites por workspace, usuario y grupo.
