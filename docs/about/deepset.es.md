---
title: "AgenticOS vs deepset"
seo_title: "AgenticOS vs deepset Haystack Enterprise Platform"
description: "Compara Haystack Enterprise Platform de deepset con AgenticOS: pipelines de IA soberana con referencias en el sector público frente a una plataforma abierta."
source_sha: "330dd816d6ea"
---

# AgenticOS vs deepset { #agenticos-vs-deepset }

Haystack Enterprise Platform de deepset, antes deepset AI Platform, se presenta como «la plataforma para la IA soberana». Crea, ejecuta y gobierna agents y pipelines sobre el framework de código abierto Haystack, en la nube, autoalojada o aislada de la red, y desde octubre de 2026 también en STACKIT. Impulsa AI@EC, la plataforma de IA de la Comisión Europea. AgenticOS es la alternativa de código abierto en la que toda la aplicación, y no solo el framework, es Apache-2.0, y en la que los agents llegan a los empleados en sus propios canales.

Mantenido por el equipo de AgenticOS. Fuentes revisadas el 26 de noviembre de 2026. Versión de referencia de AgenticOS: v1.95.0. Alcance de deepset: su página de producto, el caso de estudio de la Comisión Europea y los anuncios de socios; no un despliegue probado. Los precios no están publicados.

## De un vistazo { #at-a-glance }

| Área | deepset Haystack Enterprise Platform | AgenticOS |
| --- | --- | --- |
| Qué es | Una plataforma para crear, ejecutar y gobernar agents y pipelines de Haystack | Una plataforma para los agents de la empresa, workflows, apps y tablas |
| Licencia | Plataforma propietaria; framework Haystack Apache-2.0 | Apache-2.0 para toda la aplicación; consulta las [licencias de los componentes incluidos](../licenses.md) |
| Dónde se ejecuta | Nube, autoalojada o aislada de la red; en STACKIT desde el 15 de octubre de 2026 | Tu infraestructura, también aislada de la red |
| Modelos | Cualquiera | 28 providers, incluidos locales |
| Creación | Builder visual de pipelines para desarrolladores y equipos de IA | Un Builder para equipos de negocio; un lienzo visual de [workflows](../workflows.md); capabilities en Python |
| Evaluaciones | Sí | [Eval runs](../evals.md) y suites sobre datasets versionados |
| Gobernanza | Control de acceso y observabilidad | Budgets por agent comprobados antes de cada petición al modelo, aprobaciones, auditoría con detección de manipulaciones, seis roles y concesiones |
| Tenants | No descritos | Muchas organizaciones en un despliegue |
| Canales | Aplicaciones y API construidas sobre la plataforma | Chat web, widget, página alojada, API HTTP, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, correo electrónico, iMessage, llamadas telefónicas; apps de escritorio y de teléfono |
| Referencias | Comisión Europea (AI@EC); socios Celonis, HPE, NTT DATA, Materna | Fase más temprana: aún sin una referencia comparable en el sector público |
| Precios | A través de ventas | Sin coste de licencia; el uso de modelos a las tarifas de tu provider |

## Dónde llega más lejos AgenticOS { #where-agenticos-goes-further }

### Código abierto hasta arriba { #open-source-all-the-way-up }

Haystack es abierto, pero la plataforma construida sobre él es propietaria. AgenticOS publica toda la aplicación con Apache-2.0: la consola, la gobernanza, los canales y los workers. Un organismo público o un integrador puede auditar cada control y seguir ejecutando el código si termina la relación con el proveedor.

### Agents en los canales que usan los empleados { #agents-in-the-channels-employees-use }

deepset entrega pipelines y aplicaciones. Un agent publicado de AgenticOS responde en [Slack](../channels.md#slack), [Microsoft Teams](../channels.md#microsoft-teams), por [correo electrónico](../channels.md#email), [SMS](../channels.md#sms), [llamadas telefónicas](../voice.md#telephone-calls) y en un [widget web](../channels.md#the-website-widget), con apps de [escritorio](../desktop.md) y de [teléfono](../mobile.md) para las aprobaciones.

### Budgets y aprobaciones en cada agent { #budgets-and-approvals-on-every-agent }

AgenticOS detiene la siguiente petición al modelo de un agent en su [budget](../governance.md#enforcement-is-before-the-request), detiene una llamada a herramienta hasta que la persona adecuada la [aprueba](../governance.md#approvals) y registra ambas cosas en el [registro de auditoría](../governance.md#audit).

### Sin proceso de venta para empezar { #no-sales-process-to-start }

Puedes instalar AgenticOS hoy desde su repositorio y hacer un piloto en tu propio hardware. deepset se vende a través de su equipo comercial y sus socios.

## Cuándo encaja mejor deepset { #when-deepset-is-the-better-fit }

- Necesitas un proveedor con referencias en el sector público, como la Comisión Europea, o una presencia lista en STACKIT.
- Tu equipo crea pipelines de recuperación en Haystack y quiere una plataforma gestionada a su alrededor.
- Necesitas hoy una red de socios para proyectos de defensa o aislados de la red.

## Preguntas frecuentes { #frequently-asked-questions }

### ¿Es AgenticOS una plataforma de IA soberana como deepset? { #is-agenticos-a-sovereign-ai-platform-like-deepset }

Ambos se ejecutan en tu infraestructura, también aislados de la red, con cualquier modelo. En AgenticOS toda la aplicación es Apache-2.0; en deepset el framework Haystack es abierto y la plataforma es propietaria.

### ¿Puede AgenticOS ejecutarse en STACKIT u otra nube europea? { #can-agenticos-run-on-stackit-or-another-european-cloud }

AgenticOS funciona con Docker Compose o con su [Helm chart](../kubernetes.md) en cualquier infraestructura que ofrezca los recursos de la [guía de despliegue](../deploy.md). Valida el proveedor concreto antes de depender de él; el equipo de AgenticOS todavía no ha documentado un despliegue en STACKIT.

## Comparativas relacionadas { #related-comparisons }

[AgenticOS vs Mistral](mistral.md) · [AgenticOS vs Langdock](langdock.md) · [AgenticOS vs Dust](dust.md) · [Todas las comparativas](comparison.md)

## Fuentes { #sources }

- [Haystack Enterprise Platform](https://deepset.ai/products-and-services/deepset-ai-platform): descripción del producto y opciones de despliegue.
- [Comisión Europea y deepset](https://deepset.ai/case-studies/european-commission-x-deepset-building-europes-sovereign-ai-platform): el caso de estudio de AI@EC.
- [Celonis y deepset](https://www.celonis.com/news/press/made-in-germany-celonis-and-deepset-build-sovereign-ai-platform-for-mission-critical-operations): la alianza para una plataforma soberana.
- [Noticias de deepset](https://deepset.ai/news): disponibilidad en STACKIT desde el 15 de octubre de 2026 y las alianzas con HPE, NTT DATA y Materna.
- [Introducing Haystack Enterprise Platform](https://www.deepset.ai/blog/introducing-haystack-enterprise-platform): el cambio de nombre desde deepset AI Platform.
- [Haystack](https://github.com/deepset-ai/haystack): el framework Apache-2.0.
