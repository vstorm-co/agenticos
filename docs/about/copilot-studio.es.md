---
source_sha: "6daf4c941912"
title: "AgenticOS vs Copilot Studio"
seo_title: "AgenticOS vs Copilot Studio: alternativa autoalojada"
description: "Compara Microsoft Copilot Studio con AgenticOS: sin Copilot Credits, cualquier provider de modelos, tu infraestructura, budgets por agent y auditoría abierta."
---

# AgenticOS vs Copilot Studio { #agenticos-vs-copilot-studio }

Microsoft Copilot Studio construye agents dentro de Power Platform. Tiene los conectores de Power Platform, publicación en Teams y Microsoft 365, y gobernanza con Purview y Entra, todo en la nube de Microsoft y facturado en Copilot Credits. AgenticOS construye agents en tu propia infraestructura, con cualquier provider de modelos, y no cobra ninguna cuota propia: pagas al provider por el modelo.

Si tu empresa vive en Microsoft 365, Copilot Studio es un candidato natural. AgenticOS es el candidato cuando quieres ser dueño de la plataforma, mantener los datos donde elijas y evitar un contador por función.

Mantenido por el equipo de AgenticOS. Fuentes revisadas el 25 de septiembre de 2026. Versión de referencia de AgenticOS: v0.0.504. Alcance de Copilot Studio: la página de precios de Microsoft, la API de precios minoristas de Azure y Microsoft Learn, no un tenant probado.

## De un vistazo { #at-a-glance }

| Área | Copilot Studio | AgenticOS |
| --- | --- | --- |
| Dónde se ejecuta | La nube de Microsoft, en entornos de Power Platform | Tu infraestructura |
| Código | Propietario | Apache-2.0 |
| Modelos | Modelos GPT por defecto, modelos Claude con disponibilidad general, modelos de Azure Foundry facturados aparte | 27 providers, incluidos locales |
| Facturación | $200 al mes por 25 000 Copilot Credits, o $0,01 por crédito en pago por uso | Sin cuota de licencia; uso del modelo a las tarifas de tu provider |
| Cómo se cuenta el uso | Créditos por función: una respuesta generativa son 2, una acción de agent 5, el grounding en el grafo del tenant 10 | Tokens del modelo, con el precio de cada provider |
| Aplicación del gasto | Límites mensuales por agent; los agents se desactivan al 125 % de la capacidad prepagada | Un budget por agent y por organización, comprobado antes de cada petición al modelo |
| Superficies | Teams, Microsoft 365, SharePoint, web, WhatsApp, voz, y Slack o Telegram a través de Azure Bot Service | Chat web, widget, página alojada, API HTTP, WebSocket, Slack, Telegram, Mattermost |
| Identidad | Microsoft Entra ID | SSO OIDC, Entra incluido, LDAP y Kerberos |
| Gobernanza | Políticas de datos de Power Platform, auditoría de Purview, Entra Agent ID | Catálogo de permisos, concesiones, aprobaciones y un registro de auditoría con detección de manipulaciones |

## Dónde AgenticOS va más allá { #where-agenticos-goes-further }

### Una factura que puedes prever a partir del precio del modelo { #a-bill-you-can-predict-from-the-model-price }

Copilot Studio mide cada función en créditos, añade una tarifa premium para los modelos de razonamiento y factura su harness más reciente de GitHub Copilot desde el momento en que empiezas a construir. AgenticOS registra el coste propio del modelo en [cada run](../governance.md#what-run-history-shows) a partir de una instantánea de precios incluida. El [budget](../governance.md#budgets) de un agent se comprueba [antes de cada petición al modelo](../governance.md#enforcement-is-before-the-request), en lugar de desactivar el agent cuando se agota la capacidad.

### Cualquier nube, o ninguna { #any-cloud-or-none }

Copilot Studio se ejecuta en la nube de Microsoft. Microsoft advierte que los modelos de Anthropic quedan fuera del EU Data Boundary y están desactivados por defecto en la UE, la AELC y el Reino Unido. AgenticOS se ejecuta allí donde lo despliegues. Puedes elegir un provider en la región que necesites, o [ejecutar el modelo tú mismo](../models.md#self-hosted) para que los prompts nunca salgan de tu red.

### Todos los providers de modelos, en primera clase { #every-model-provider-first-class }

El harness estándar de Copilot Studio ofrece modelos GPT y Claude, con Azure Foundry para traer tu propio modelo, facturado aparte. AgenticOS trata igual a [27 providers](../models.md#providers). Comparten un mismo formato de [perfil de modelo](../models.md#a-model-profile), los mismos [fallbacks](../models.md#fallbacks) y el mismo registro de costes.

### Abierto donde le importa a un auditor { #open-where-it-matters-to-an-auditor }

La gobernanza de Copilot Studio es sólida dentro del ecosistema de Microsoft. AgenticOS te permite leer los propios controles: el [catálogo de permisos](../permissions.md), el [vault](../secrets.md#envelope-encryption), la [cadena de hashes de auditoría](../governance.md#audit) y los [tests de rechazo](../security.md#the-refusals-as-a-set) en CI. El spec [se exporta como YAML](../features.md#exportable-into-your-own-repository), así que irte significa conservar tus agents, no reconstruirlos.

### Identidad de Microsoft sin alojamiento de Microsoft { #microsoft-identity-without-microsoft-hosting }

AgenticOS inicia la sesión de las personas con Entra ID a través de [OIDC](../configuration.md#single-sign-on-generic-oidc), asigna los [grupos del directorio](../directory.md#the-groups-claim-over-oidc) a roles y lee archivos de [SharePoint y OneDrive](../howto/configure-sync-sources.md#sharepoint-and-onedrive-setup). Mantienes Microsoft como fuente de identidad y de documentos, y ejecutas los agents tú mismo.

## Cuándo Copilot Studio encaja mejor { #when-copilot-studio-is-the-better-fit }

- Tus agents pertenecen a Teams y Microsoft 365 Copilot, y tus usuarios ya tienen licencias de Microsoft 365 Copilot.
- Necesitas conectores de Power Platform, agent flows, voz o WhatsApp. AgenticOS no tiene canal de Teams, de voz ni de WhatsApp.
- Purview, Sentinel y las políticas de datos de Power Platform son la forma en que tu organización gobierna todo lo demás.

## Pruébalo con una tarea { #try-it-on-one-task }

Construye el [agent documental compartido](../howto/first-document-agent.md) en ambos, con modelos comparables. Lanza cien preguntas y compara la factura: créditos en un lado, coste del modelo en el otro. Después comprueba qué ocurre cuando se alcanza el límite. Registra el resultado con el [método de comparación](comparison.md#a-shared-trial).

## Preguntas frecuentes { #frequently-asked-questions }

### ¿AgenticOS es una alternativa a Microsoft Copilot Studio? { #is-agenticos-an-alternative-to-microsoft-copilot-studio }

Sí, si quieres ser dueño de la plataforma. AgenticOS se ejecuta en tu infraestructura con cualquier provider de modelos y sin contador de créditos. Copilot Studio encaja mejor cuando los agents viven en Teams y Microsoft 365.

### ¿AgenticOS funciona con Microsoft Entra ID y SharePoint? { #does-agenticos-work-with-microsoft-entra-id-and-sharepoint }

Sí. Las personas inician sesión con Entra ID mediante OIDC, los grupos del directorio se asignan a roles y las colecciones sincronizan archivos desde SharePoint y OneDrive.

### ¿Cuánto cuesta Copilot Studio en comparación con AgenticOS? { #how-much-does-copilot-studio-cost-compared-with-agenticos }

Copilot Studio vende 25 000 Copilot Credits por $200 al mes, o $0,01 por crédito en pago por uso. AgenticOS no tiene cuota propia; pagas a tu provider de modelos por los tokens que usa un agent.

### ¿AgenticOS puede publicar agents en Microsoft Teams? { #can-agenticos-publish-agents-to-microsoft-teams }

Todavía no. Publica en el chat web, un widget, una página alojada, la API HTTP, un WebSocket, Slack, Telegram y Mattermost.

## Comparativas relacionadas { #related-comparisons }

[AgenticOS vs Gemini Enterprise](gemini-enterprise.md) · [AgenticOS vs ChatGPT](chatgpt.md) · [AgenticOS vs n8n](n8n.md) · [Todas las comparativas](comparison.md)

## Fuentes { #sources }

- [Precios de Copilot Studio](https://www.microsoft.com/en-us/microsoft-365-copilot/pricing/copilot-studio): el paquete de créditos y el pago por uso.
- [Precios minoristas de Azure](https://prices.azure.com/api/retail/prices?$filter=contains(productName,'Copilot%20Studio')): $0,01 por crédito.
- [Tarifas y gestión de la facturación](https://learn.microsoft.com/en-us/microsoft-copilot-studio/requirements-messages-management): créditos por función, límites por agent y la aplicación al 125 %.
- [Harnesses](https://learn.microsoft.com/en-us/microsoft-copilot-studio/harnesses-overview) y [facturación de los harnesses](https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/billing-credit-overview): facturación desde el momento de construir.
- [Seleccionar un modelo](https://learn.microsoft.com/en-us/microsoft-copilot-studio/authoring-select-agent-model): modelos disponibles.
- [Anthropic como subencargado](https://learn.microsoft.com/en-us/microsoft-365/copilot/connect-to-ai-subprocessor): la exclusión del EU Data Boundary.
- [Canales de publicación](https://learn.microsoft.com/en-us/microsoft-copilot-studio/publication-fundamentals-publish-channels): superficies y autenticación.
