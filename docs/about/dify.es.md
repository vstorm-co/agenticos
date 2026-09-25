---
source_sha: "3689d8258a77"
title: "AgenticOS vs Dify"
seo_title: "AgenticOS vs Dify: alternativa Apache-2.0 y multi-tenant"
description: "Compara Dify y AgenticOS, dos plataformas de agents de IA autoalojadas: condiciones de licencia, multi-tenancy, SSO, budgets, aprobaciones, auditoría y precios."
---

# AgenticOS vs Dify { #agenticos-vs-dify }

Ambos productos son autoalojados y ambos hacen recuperación de documentos, así que la diferencia está en otra parte. Dify es un lienzo visual para apps LLM y workflows, con multi-tenancy de varios workspaces, SSO y registros de auditoría en su edición Enterprise. AgenticOS es Apache-2.0 y multi-tenant en el producto de código abierto, con budgets, aprobaciones, inicio de sesión con directorio y un registro de auditoría con detección de manipulaciones incluidos.

Mantenido por el equipo de AgenticOS. Fuentes revisadas el 25 de septiembre de 2026. Versión de referencia de AgenticOS: v0.0.504. Alcance de Dify: el repositorio público en la versión 1.17.1, su licencia, su documentación y su página de precios; no un plan cloud probado ni un despliegue fijado.

## De un vistazo { #at-a-glance }

| Área | Dify Community Edition | AgenticOS |
| --- | --- | --- |
| Cómo construyes | Un lienzo visual de nodos de workflow, chatflow y agent | Instrucciones, un perfil de modelo, capabilities, colecciones y un budget, publicados como una versión |
| Licencia | Dify Open Source License: Apache 2.0 con condiciones añadidas | Apache-2.0; consulta las [licencias de los componentes incluidos](../licenses.md) |
| Multi-tenancy | Un workspace; varios workspaces son Enterprise | Muchas organizaciones en un despliegue |
| Roles | Cuatro roles integrados; los roles personalizados son Enterprise | Seis roles, 27 permisos y grants por recurso para personas y grupos |
| Inicio de sesión | Correo electrónico; SSO es Enterprise | Correo electrónico, Google, SSO OIDC, LDAP y Kerberos, con asignaciones de grupos del directorio |
| Auditoría | Enterprise | Registro de auditoría con detección de manipulaciones, con exportación CSV y JSONL |
| Control del gasto | Facturación del provider, o créditos de mensajes de Cloud | Un budget mensual por agent y por organización, comprobado antes de cada petición al modelo |
| Aprobación humana | Un nodo Human Input en un workflow | Aprobación por capability y por herramienta para las herramientas de capability; el run queda detenido hasta que alguien decide. Las herramientas MCP no se controlan por herramienta |
| Superficies | App web, embed, API, servidor MCP; Slack mediante un plugin | Chat web, widget, página alojada, API HTTP, WebSocket, Slack, Telegram, Mattermost |
| Kubernetes | Helm charts de la comunidad; la alta disponibilidad oficial es Enterprise | Docker Compose en un único host |

## Dónde llega más lejos AgenticOS { #where-agenticos-goes-further }

### Multi-tenant sin licencia comercial { #multi-tenant-without-a-commercial-licence }

La licencia de Dify permite el uso comercial y añade dos condiciones. No puedes operar un entorno multi-tenant sin permiso por escrito, donde un tenant es un workspace. No puedes eliminar ni modificar el logotipo ni la información de copyright de su frontend. Los contribuidores aceptan además que el productor puede cambiar los términos de la licencia.

AgenticOS es Apache-2.0. Las [organizaciones](../concepts.md#organizations) son tenants, aislados en el esquema, y un despliegue puede dar servicio a cada departamento, filial o cliente. Puedes cambiar la consola y ponerle tu propia marca. La configuración de [identidad del despliegue](../deployment.md) cubre el nombre y los avisos.

### Los controles que pide una empresa, en el producto de código abierto { #the-controls-an-enterprise-asks-for-in-the-open-source-product }

La página de precios de Dify indica SSO como exclusivo de Enterprise, y su documentación sitúa los roles personalizados y los múltiples workspaces en Enterprise. AgenticOS incluye el inicio de sesión único y muchas organizaciones en el producto Apache-2.0, junto con:

- [Inicio de sesión único OIDC](../configuration.md#single-sign-on-generic-oidc) con Entra, Okta, Keycloak y otros, [LDAP y Kerberos](../directory.md#signing-in-with-a-directory-account), y [asignaciones de grupos del directorio](../directory.md#directory-group-mappings) a roles.
- [Seis roles y grants por recurso](../permissions.md#layer-3-visibility-and-grants) que amplían el acceso a un agent o una colección.
- Un [registro de auditoría con detección de manipulaciones](../governance.md#audit), escrito en la misma transacción que la acción que registra.
- [Periodos de retención](../governance.md#retention) por clase de datos, y [secretos con cifrado de sobre](../secrets.md#envelope-encryption) sellados por organización.

Los seis roles son fijos. Los roles personalizados, igual que SCIM, todavía no están disponibles.

### Un budget que detiene la siguiente llamada al modelo { #a-budget-that-stops-the-next-model-call }

La documentación de Dify no describe en la Community Edition un límite de gasto aplicado antes de las llamadas al modelo. Con tus propias claves, la facturación va a la cuenta de cada provider.

AgenticOS comprueba el [budget mensual](../governance.md#budgets) de cada agent y el límite de la organización [antes de cada petición al modelo](../governance.md#enforcement-is-before-the-request), y registra también el coste de un run fallido. El [trabajo delegado](../governance.md#delegation-spends-the-parents-budget) consume el budget del agent padre, así que un subagent no puede esquivarlo gastando por su cuenta.

### Aprobación en la herramienta, no solo en el flujo { #approval-on-the-tool-not-only-in-the-flow }

El nodo Human Input de Dify pausa un workflow y envía un formulario, y la solicitud se cierra tras la primera respuesta. En AgenticOS una [aprobación](../governance.md#approvals) se configura por capability y puede sobrescribirse por herramienta. Cubre las herramientas de capability; una herramienta MCP solo se controla cuando una conversación del chat web pide aprobar todo. El run queda detenido, las personas que elijas reciben una [alerta](../governance.md#alerts), y se rechaza una segunda decisión sobre una aprobación ya decidida.

### Un cambio que puede hacer un equipo de negocio { #a-change-a-business-team-can-make }

En Dify cambias un proceso editando el lienzo. En AgenticOS un responsable de negocio edita las instrucciones o activa una capability, y después publica. Cada [versión](../concepts.md#version) sigue siendo legible, los [entornos](../environments.md#the-workflow-it-is-for) promueven una versión probada, y el spec [se exporta como YAML](../features.md#exportable-into-your-own-repository) para revisarlo en una pull request. La configuración solo puede alcanzar lo que registraron los ingenieros, y eso mantiene seguro un builder no-code.

## Cuándo encaja mejor Dify { #when-dify-is-the-better-fit }

- Tu equipo piensa en diagramas de flujo y quiere un lienzo visual de nodos, bucles y ramas. AgenticOS no tiene lienzo de workflows.
- Necesitas los plugins de su marketplace, su búsqueda híbrida con rerank o sus numerosas integraciones de observabilidad. AgenticOS todavía no tiene reranker ni panel de trazas.
- Te basta con un workspace, o te convienen los términos de la edición Enterprise.

## Compara un cambio, no solo una respuesta { #compare-a-change-not-only-an-answer }

Usa el mismo [manual sintético](../howto/first-document-agent.md), las mismas preguntas y las mismas comprobaciones de referencia. Registra en cada lado la versión, el modelo, la configuración de procesamiento de fuentes y la identidad. Después cambia el responsable de la solicitud en la fuente y repite tras el procesamiento.

Añade dos comprobaciones que muestran las diferencias anteriores. Crea un segundo tenant para un segundo equipo, y dale a un agent un budget de unos pocos céntimos; después ejecútalo hasta superar el límite. Registra qué permite, qué rechaza y qué registra cada producto, con el [método de comparación](comparison.md#a-shared-trial).

## Preguntas frecuentes { #frequently-asked-questions }

### ¿AgenticOS es una alternativa de código abierto a Dify? { #is-agenticos-an-open-source-alternative-to-dify }

Sí. Ambos son autoalojados y ambos hacen recuperación de documentos. AgenticOS es Apache-2.0 sin condiciones sobre multi-tenancy ni logotipo, e incluye SSO, roles, budgets, aprobaciones y un registro de auditoría con detección de manipulaciones sin una edición Enterprise.

### ¿Dify puede funcionar como servicio multi-tenant? { #can-dify-run-as-a-multi-tenant-service }

La licencia de Dify exige permiso por escrito para operar un entorno multi-tenant, donde un tenant es un workspace. AgenticOS da servicio a muchas organizaciones desde un solo despliegue bajo Apache-2.0.

### ¿AgenticOS tiene un constructor visual de workflows como Dify? { #does-agenticos-have-a-visual-workflow-builder-like-dify }

No. AgenticOS construye agents a partir de instrucciones, capabilities, conocimiento y un budget, y resuelve el trabajo de varios pasos con delegación, planificación y triggers. Si tu equipo trabaja con un lienzo de nodos, Dify encaja mejor.

### ¿Cuál de los dos cuesta menos de operar? { #which-one-costs-less-to-run }

Dify Community Edition y AgenticOS son gratuitos para autoalojar; pagas los modelos y la infraestructura. El equipo comercial de Dify fija el precio de sus funciones Enterprise. En AgenticOS esos controles ya están en el producto de código abierto.

## Comparativas relacionadas { #related-comparisons }

[AgenticOS vs n8n](n8n.md) · [AgenticOS vs Copilot Studio](copilot-studio.md) · [AgenticOS vs Gemini Enterprise](gemini-enterprise.md) · [Todas las comparativas](comparison.md)

## Fuentes { #sources }

- [Repositorio de Dify](https://github.com/langgenius/dify): ediciones, funciones y la versión 1.17.1.
- [Licencia de Dify](https://github.com/langgenius/dify/blob/main/LICENSE): las condiciones sobre multi-tenancy y logotipo, citadas arriba.
- [Precios](https://dify.ai/pricing): planes de Cloud y las funciones exclusivas de Enterprise.
- [Enterprise](https://dify.ai/enterprise): SSO, SCIM, roles personalizados, registros de auditoría y opciones de despliegue.
- [Miembros del equipo](https://docs.dify.ai/en/self-host/use-dify/workspace/team-members-management) y [workspaces](https://docs.dify.ai/en/self-host/use-dify/workspace/readme): roles e instalaciones de un solo workspace.
- [Nodo Human Input](https://docs.dify.ai/en/self-host/use-dify/nodes/human-input): comportamiento de las aprobaciones en los workflows.
