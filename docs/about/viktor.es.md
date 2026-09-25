---
source_sha: "2ca7dda133d2"
title: "AgenticOS vs Viktor"
description: "Compara un compañero de equipo de IA gestionado por workspace con una plataforma de agents versionados que opera tu equipo."
---

# AgenticOS vs Viktor { #agenticos-vs-viktor }

Viktor vende un compañero de equipo de IA por cada workspace de Slack o Microsoft Teams, ejecutado en su nube y facturado en créditos. AgenticOS te da tantos agents como necesites, cada uno con sus propias instrucciones, modelo, herramientas, conocimiento, budget y reglas de acceso, en una infraestructura que tú controlas.

Si quieres un colega útil en el chat esta misma tarde, Viktor se prueba rápido. Si quieres decidir qué puede hacer cada agent, cuánto cuesta y dónde viven los datos, AgenticOS te da ese control.

Mantenido por el equipo de AgenticOS. Fuentes revisadas el 25 de septiembre de 2026. Versión de referencia de AgenticOS: v0.0.504. Alcance de Viktor: sus páginas públicas de producto, precios, seguridad y empresa, y su changelog; no una cuenta probada ni un contrato negociado.

## De un vistazo { #at-a-glance }

| Área | Viktor | AgenticOS |
| --- | --- | --- |
| Qué obtienes | Un "empleado de IA" compartido por workspace | Cualquier número de agents, cada uno un spec versionado |
| Dónde se ejecuta | La nube de Viktor, alojada en AWS us-east-1 | Tu infraestructura, con Docker Compose |
| Código fuente | Propietario | Apache-2.0 |
| Modelos | Presets de OpenAI, Anthropic, Google y Kimi; tu propia clave de OpenRouter | 27 providers, incluidos Ollama y LiteLLM en tu propio hardware |
| Conocimiento | Memoria del workspace y herramientas conectadas | Colecciones de documentos en tu Postgres, con cinco conectores de sincronización |
| Superficies | Slack, Teams, Discord, su propia bandeja de correo, web, apps de escritorio y móviles, API | Chat web, widget, página alojada, API HTTP, WebSocket, Slack, Telegram, Mattermost |
| Acceso | A nivel de workspace; sus páginas difieren sobre el acceso basado en roles | Seis roles, 27 permisos y grants por recurso, por organización |
| Control del gasto | El fondo de créditos; límites a medida en Enterprise | Un budget mensual por agent y por organización, comprobado antes de cada petición al modelo |
| Precios | Desde $50 al mes por 20.000 créditos, a una tarifa fija de $2,50 por cada 1.000 créditos | Sin cuota de licencia; pagas a los providers de modelos y la infraestructura |
| Evidencia de cumplimiento | SOC 2 Type 1; Type II e ISO 27001 en curso | Tus controles en tu infraestructura; consulta [seguridad](../security.md) |

## Dónde llega más lejos AgenticOS { #where-agenticos-goes-further }

### Muchos agents, cada uno con su tarea { #many-agents-each-with-a-job }

Viktor es un único compañero de equipo que comparte todo el workspace. En AgenticOS cada agent se construye para su propia tarea, como un agent de políticas de RR. HH., un asistente de ventas o un agent de triaje de soporte. Cada uno tiene sus propias instrucciones, [capabilities](../reference/capabilities.md), colecciones de conocimiento y budget.

El spec de un agent se [versiona al publicar](../concepts.md#version) y [se exporta como YAML](../features.md#exportable-into-your-own-repository) a tu repositorio git. Los [entornos](../environments.md#what-an-environment-is) con nombre te permiten probar una versión en staging antes de que producción responda con ella.

### Acceso decidido por agent y por persona { #access-decided-per-agent-and-per-person }

Las preguntas frecuentes de la página principal de Viktor, revisadas el 25 de septiembre de 2026, dicen que un plan comparte una instancia y un contexto de Viktor, y que una integración conectada está disponible para todos los miembros del equipo. Su página para empresas enumera el acceso basado en roles. Pregunta cuál se aplica a tu contrato.

En AgenticOS, el acceso procede del [catálogo de permisos](../permissions.md#the-built-in-roles), y los [grants](../permissions.md#layer-3-visibility-and-grants) comparten un agent, un skill o una colección con una persona o un grupo. Un binding MCP puede usar [la cuenta propia de cada persona](../mcp.md#whose-account-a-binding-speaks-through) en lugar de un inicio de sesión compartido. Un usuario de Slack vinculado ejecuta los runs [como sí mismo](../channels.md#slack).

### Un budget por agent, no solo un fondo de créditos { #a-budget-per-agent-not-only-a-credit-pool }

Viktor factura un fondo de créditos del workspace, y afirma que los créditos corresponden a lo que cobran los providers de modelos. AgenticOS no tiene créditos. Cada agent tiene un [budget mensual](../governance.md#budgets) que se comprueba [antes de cada petición al modelo](../governance.md#enforcement-is-before-the-request). Un run fallido también registra su gasto, y una [alerta](../governance.md#alerts) avisa a las personas que elijas cuando un agent alcanza su límite.

### Tus datos se quedan donde los pones { #your-data-stays-where-you-put-it }

Viktor está alojado en EE. UU. Sus páginas difieren sobre la residencia en la UE y la retención configurable, así que confirma ambas cosas por escrito. AgenticOS almacena conversaciones, documentos y vectores en [tu propio Postgres](../data-protection.md#where-personal-data-lives). Tú fijas la [retención por clase](../governance.md#retention). Con un modelo local, nada necesita salir de tu red.

### Conocimiento que puedes inspeccionar { #knowledge-you-can-inspect }

Viktor aprende de las conversaciones y de las herramientas conectadas. AgenticOS añade colecciones de documentos gestionadas: eliges el [parser](../file-processing.md#parser-selection-rag) y el [chunking](../file-processing.md#chunking-configuration) por colección. Puedes sincronizar desde Google Drive, S3, SharePoint u OneDrive, un sitio web o un repositorio git. Una sincronización [elimina los documentos](../howto/configure-sync-sources.md#what-a-sync-removes) que la fuente ya no incluye.

## Cuándo basta con Viktor { #when-viktor-is-enough }

- Quieres un asistente en Slack o Teams sin infraestructura que operar.
- Su catálogo de más de 3.200 integraciones OAuth y su sandbox de código cubren tus tareas.
- La facturación por créditos y el alojamiento en EE. UU. cumplen tus requisitos.
- Necesitas Microsoft Teams, voz o una bandeja de correo hoy. AgenticOS todavía no tiene canal de conversación para Teams, voz ni correo electrónico.

## Prueba una pregunta del manual { #try-one-handbook-question }

Usa el [ejemplo documental común](../howto/first-document-agent.md). Compara el acceso a la fuente, la respuesta real, una pregunta sobre una política ausente y una actualización de la fuente. Comprueba qué identidad puede recuperar la fuente y cómo se retira el acceso cuando alguien se marcha.

Después ejecuta en cada producto un segundo agent para otro equipo. Comprueba si puede ver las integraciones y la memoria del primer equipo. Ese segundo agent es donde más difieren un compañero de equipo de workspace y una plataforma de agents. Registra el resultado con el [método de comparación](comparison.md#a-shared-trial).

## Fuentes { #sources }

- [Página de producto y preguntas frecuentes de Viktor](https://viktor.com/): posicionamiento, instancia compartida del workspace, integraciones compartidas en todo el equipo, hoja de ruta de RBAC.
- [Precios](https://viktor.com/pricing): planes de créditos, sin cuota por usuario, coste del modelo trasladado.
- [Seguridad](https://viktor.com/security): AWS us-east-1, SOC 2 Type 1, ISO 27001 en curso, aprobaciones, SSO SAML en Enterprise.
- [Empresa](https://www.viktor.com/enterprise.md): identidad nativa del chat, declaraciones sobre residencia en la UE y retención, contratos anuales.
- [Changelog](https://www.viktor.com/changelog.md): claves de OpenRouter, registros de auditoría de Enterprise, Discord y correo electrónico.
