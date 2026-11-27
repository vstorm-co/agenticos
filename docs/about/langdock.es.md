---
title: "AgenticOS vs Langdock"
seo_title: "AgenticOS vs Langdock: SaaS por puesto o tus servidores"
description: "Compara Langdock y AgenticOS: una plataforma de IA alemana por puesto frente a agents Apache-2.0 en tus servidores. Límites, SSO, aprobaciones y coste."
source_sha: "b9b5fcbeb158"
---

# AgenticOS vs Langdock { #agenticos-vs-langdock }

Langdock es una plataforma alemana de IA para empresas con chat, agents, workflows y apps, alojada en Azure en la UE. Es la oferta de gobernanza más completa entre los productos SaaS europeos: SAML y SCIM en todos los planes, hasta cinco roles personalizados, límites mensuales por agent que bloquean o cambian a un modelo de respaldo, aprobaciones en workflows, evaluaciones de agents y un servidor MCP. AgenticOS cubre buena parte de esa misma gobernanza como código abierto en tus propios servidores, sin coste por puesto, y aún no tiene SAML, SCIM ni roles personalizados.

Mantenido por el equipo de AgenticOS. Fuentes revisadas el 26 de noviembre de 2026. Versión de referencia de AgenticOS: v1.95.0. Alcance de Langdock: su página de precios y su documentación para administradores; no un workspace probado.

## De un vistazo { #at-a-glance }

| Área | Langdock | AgenticOS |
| --- | --- | --- |
| Qué es | Un workspace de IA por puesto con chat, agents, workflows y apps | Una plataforma para los agents de la empresa, workflows, apps y tablas que operas tú |
| Licencia | Propietaria | Apache-2.0; consulta las [licencias de los componentes incluidos](../licenses.md) |
| Dónde se ejecuta | SaaS en Azure en la UE; single-tenant y on-premises en contratos grandes | Tu infraestructura, cualquier nube u on-premises |
| Modelos | Varios modelos, alojados en la UE, o tus propias claves | 28 providers, incluidos locales |
| Control del gasto | Límites mensuales por workspace, persona, grupo, agent y workflow, que bloquean o cambian a un modelo de respaldo | Un budget mensual por agent y por organización, comprobado antes de cada petición al modelo |
| Aprobaciones | En workflows, dirigidas a destinatarios concretos | Aprobación por capability, herramienta y conexión MCP, dirigida a las personas que elijas |
| Acceso y roles | SAML y SCIM en todos los planes; hasta cinco roles personalizados | SSO con OIDC, LDAP y Kerberos; seis roles integrados y concesiones por recurso; aún sin SAML, SCIM ni roles personalizados |
| Evaluaciones | Evaluaciones de agents | [Eval runs](../evals.md) y suites sobre datasets versionados |
| Auditoría | API de auditoría, 90 días | Registro de auditoría con detección de manipulaciones y la retención que fijes |
| Canales | Web, Slack, Microsoft Teams, Office, apps de escritorio y de teléfono | Chat web, widget, página alojada, API HTTP, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, correo electrónico, iMessage, llamadas telefónicas; apps de escritorio y de teléfono |
| Precios | Core 23,20 €, Work 31,20 €, Max 99 € por usuario al mes con pago anual; workflows 449 € por workspace al mes | Sin coste de licencia ni por puesto; el uso de modelos a las tarifas de tu provider |

## Dónde llega más lejos AgenticOS { #where-agenticos-goes-further }

### Sin coste por puesto { #no-seat-fee }

Langdock cobra por usuario. Para 200 personas, sus planes publicados suman aproximadamente entre 56.000 € y 238.000 € al año, sin contar los complementos de workflows. AgenticOS no tiene coste de licencia ni por puesto: pagas a los providers de modelos a sus tarifas y operas la infraestructura, tú o con Vstorm. Compáralos con tu propio uso, ya que los planes por puesto incluyen el uso de modelos dentro de unos límites y AgenticOS no.

### Tus servidores desde el primer usuario { #your-servers-from-the-first-user }

Las opciones dedicadas y on-premises de Langdock solo se ofrecen en contratos grandes. AgenticOS se ejecuta en [tu infraestructura](../deploy.md) desde el principio, con modelos, embeddings y procesamiento de documentos locales si los necesitas. Consulta [qué sale por defecto](../data-protection.md#nothing-leaves-by-default).

### Código abierto que puedes cambiar { #open-code-you-can-change }

AgenticOS es Apache-2.0. Puedes leer cada control que pide una revisión, cambiar la consola y ponerle tu marca, y atender a varias empresas desde un despliegue, con las [organizaciones](../concepts.md#organizations) como tenants.

### Más canales { #more-channels }

El mismo agent publicado responde también en Telegram, Mattermost, Discord, Matrix, por [SMS](../channels.md#sms), [correo electrónico](../channels.md#email), iMessage y [llamadas telefónicas](../voice.md#telephone-calls), y en un [widget web](../channels.md#the-website-widget) público o una [página alojada](../channels.md#a-hosted-page).

## Cuándo encaja mejor Langdock { #when-langdock-is-the-better-fit }

- Necesitas SAML, SCIM o roles personalizados hoy. AgenticOS aún no tiene ninguno; SAML solo funciona a través de un broker como Keycloak.
- Quieres un servicio gestionado en la UE con informes ISO 27001 y SOC 2 Type II, sin servidores que operar.
- Tus equipos quieren un asistente de chat para cada empleado tanto como agents de empresa.

## Compara un cambio, no solo una respuesta { #compare-a-change-not-only-an-answer }

Ejecuta el mismo agent en ambos productos con un límite mensual de unos céntimos y comprueba qué pasa al llegar al límite. Dirige una llamada a herramienta a una segunda persona para que la apruebe. Después calcula un año para tu plantilla: puestos de Langdock frente a infraestructura y uso de modelos en AgenticOS. Anota los resultados con el [método de comparación](comparison.md#a-shared-trial).

## Preguntas frecuentes { #frequently-asked-questions }

### ¿Es AgenticOS una alternativa europea a Langdock? { #is-agenticos-a-european-alternative-to-langdock }

Es una alternativa de código abierto que alojas donde quieras, incluida la UE u on-premises. Vstorm, que lo mantiene, es una empresa polaca. Langdock es un producto SaaS alemán.

### ¿Tiene Langdock budgets por agent? { #does-langdock-have-budgets-per-agent }

Sí. Langdock fija límites mensuales por workspace, persona, grupo, agent y workflow, y al llegar al límite puede bloquear o cambiar a un modelo de respaldo. AgenticOS fija un budget por agent y por organización, comprobado antes de cada petición al modelo, en el producto de código abierto.

### ¿Qué le falta a AgenticOS frente a Langdock? { #what-does-agenticos-lack-compared-with-langdock }

SAML y SCIM, roles personalizados y certificaciones de seguridad para un servicio gestionado. Tu propio despliegue de AgenticOS lo certificas tú; la [página de seguridad](../security.md) relaciona sus controles para una revisión.

## Comparativas relacionadas { #related-comparisons }

[AgenticOS vs Dust](dust.md) · [AgenticOS vs deepset](deepset.md) · [AgenticOS vs Mistral](mistral.md) · [Todas las comparativas](comparison.md)

## Fuentes { #sources }

- [Precios de Langdock](https://langdock.com/pricing): planes, precios y complemento de workflows.
- [Límites de agents](https://docs.langdock.com/en/admin/manage-agents/agent-limits): límites por agent y qué ocurre al llegar a ellos.
- [Documentación de Langdock](https://docs.langdock.com): SSO, SCIM, roles, aprobaciones, evaluaciones, MCP e integraciones.
