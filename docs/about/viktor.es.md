---
source_sha: "bf18f8d902e6"
title: "AgenticOS vs Viktor"
seo_title: "AgenticOS vs Viktor: alternativa autoalojada a un colega IA"
description: "Viktor: un colega de IA por workspace de Slack o Teams. Compáralo con AgenticOS: muchos agents gobernados, cualquier modelo y budgets por agent en tu servidor."
---

# AgenticOS vs Viktor { #agenticos-vs-viktor }

Viktor vende un compañero de equipo de IA por cada workspace de Slack o Microsoft Teams, ejecutado en su nube y facturado en créditos. AgenticOS te da tantos agents como necesites, cada uno con sus propias instrucciones, modelo, herramientas, conocimiento, budget y reglas de acceso, en una infraestructura que tú controlas.

Si quieres un colega útil en el chat esta misma tarde, Viktor se prueba rápido. Si quieres decidir qué puede hacer cada agent, cuánto cuesta y dónde viven los datos, AgenticOS te da ese control.

Mantenido por el equipo de AgenticOS. Fuentes revisadas el 21 de octubre de 2026. Versión de referencia de AgenticOS: v1.9.1. Alcance de Viktor: sus páginas públicas de producto, precios, seguridad y empresa, y su changelog; no una cuenta probada ni un contrato negociado.

## De un vistazo { #at-a-glance }

| Área | Viktor | AgenticOS |
| --- | --- | --- |
| Qué obtienes | Un "empleado de IA" compartido por workspace | Cualquier número de agents, cada uno un spec versionado |
| Dónde se ejecuta | La nube de Viktor, alojada en EE. UU. por defecto | Tu infraestructura, con Docker Compose |
| Código fuente | Propietario | Apache-2.0 |
| Modelos | Modelos de OpenAI, Anthropic, Google y xAI en un selector; tu propia clave de OpenRouter | 28 providers, incluidos Ollama y LiteLLM en tu propio hardware |
| Conocimiento | Memoria del workspace y herramientas conectadas | Colecciones de documentos en tu Postgres, con cinco conectores de sincronización |
| Superficies | Slack, Teams, Discord, su propia bandeja de correo, web, apps de escritorio y móviles, API | Chat web, widget, página alojada, API HTTP, WebSocket, Slack, Telegram, Mattermost |
| Acceso | A nivel de workspace; sus páginas difieren sobre el acceso basado en roles | Seis roles, 33 permisos y grants por recurso, por organización |
| Control del gasto | El fondo de créditos con un tope mensual de recargas automáticas; límites por usuario en Enterprise | Un budget mensual por agent y por organización, comprobado antes de cada petición al modelo |
| Precios | Free con hasta $100 en créditos; Team a $100 al mes por 40.000 créditos compartidos; Enterprise a medida | Sin cuota de licencia; pagas a los providers de modelos y la infraestructura |
| Evidencia de cumplimiento | SOC 2 Type 1; Type II e ISO 27001 en curso | Tus controles en tu infraestructura; consulta [seguridad](../security.md) |

## Dónde llega más lejos AgenticOS { #where-agenticos-goes-further }

### Muchos agents, cada uno con su tarea { #many-agents-each-with-a-job }

Viktor es un único compañero de equipo que comparte todo el workspace. En AgenticOS cada agent se construye para su propia tarea, como un agent de políticas de RR. HH., un asistente de ventas o un agent de triaje de soporte. Cada uno tiene sus propias instrucciones, [capabilities](../reference/capabilities.md), colecciones de conocimiento y budget.

El spec de un agent se [versiona al publicar](../concepts.md#version) y [se exporta como YAML](../features.md#exportable-into-your-own-repository) a tu repositorio git. Los [entornos](../environments.md#what-an-environment-is) con nombre te permiten probar una versión en staging antes de que producción responda con ella.

### Acceso decidido por agent y por persona { #access-decided-per-agent-and-per-person }

Las preguntas frecuentes de la página principal de Viktor, revisadas el 21 de octubre de 2026, dicen que todos los miembros de un plan comparten una instancia y un contexto de Viktor, y que una herramienta conectada se puede compartir con todo el equipo o, en workspaces de Slack, mantener privada. Su página para empresas menciona el acceso basado en roles. Pregunta cuál se aplica a tu contrato.

En AgenticOS, el acceso procede del [catálogo de permisos](../permissions.md#the-built-in-roles), y los [grants](../permissions.md#layer-3-visibility-and-grants) comparten un agent, un skill o una colección con una persona o un grupo. Un binding MCP puede usar [la cuenta propia de cada persona](../mcp.md#whose-account-a-binding-speaks-through) en lugar de un inicio de sesión compartido. Un usuario de Slack vinculado ejecuta los runs [como sí mismo](../channels.md#slack).

### Un budget por agent, no solo un fondo de créditos { #a-budget-per-agent-not-only-a-credit-pool }

Viktor factura un fondo de créditos del workspace, y afirma que los créditos corresponden a lo que cobran los providers de modelos. AgenticOS no tiene créditos. Cada agent tiene un [budget mensual](../governance.md#budgets) que se comprueba [antes de cada petición al modelo](../governance.md#enforcement-is-before-the-request). Un run fallido también registra su gasto, y una [alerta](../governance.md#alerts) avisa a las personas que elijas cuando un agent alcanza su límite.

### Tus datos se quedan donde los pones { #your-data-stays-where-you-put-it }

Viktor está alojado en EE. UU. Sus páginas difieren sobre la residencia en la UE y la retención configurable, así que confirma ambas cosas por escrito. AgenticOS almacena conversaciones, documentos y vectores en [tu propio Postgres](../data-protection.md#where-personal-data-lives). Tú fijas la [retención por clase](../governance.md#retention). Con un modelo local, nada necesita salir de tu red.

### Conocimiento que puedes inspeccionar { #knowledge-you-can-inspect }

Viktor aprende de las conversaciones y de las herramientas conectadas. AgenticOS añade colecciones de documentos gestionadas: eliges el [parser](../file-processing.md#parser-selection-rag) y el [chunking](../file-processing.md#chunking-configuration) por colección. Puedes sincronizar desde Google Drive, S3, SharePoint u OneDrive, un sitio web o un repositorio git. Una sincronización [elimina los documentos](../howto/configure-sync-sources.md#what-a-sync-removes) que la fuente ya no incluye.

## Cuándo basta con Viktor { #when-viktor-is-enough }

- Quieres un asistente en Slack o Teams sin infraestructura que operar.
- Su catálogo de más de 9.800 herramientas y su sandbox de código cubren tus tareas.
- La facturación por créditos y el alojamiento en EE. UU. cumplen tus requisitos.
- Necesitas Microsoft Teams, voz o una bandeja de correo hoy. AgenticOS todavía no tiene canal de conversación para Teams, voz ni correo electrónico.

## Prueba una pregunta del manual { #try-one-handbook-question }

Usa el [ejemplo documental común](../howto/first-document-agent.md). Compara el acceso a la fuente, la respuesta real, una pregunta sobre una política ausente y una actualización de la fuente. Comprueba qué identidad puede recuperar la fuente y cómo se retira el acceso cuando alguien se marcha.

Después ejecuta en cada producto un segundo agent para otro equipo. Comprueba si puede ver las integraciones y la memoria del primer equipo. Ese segundo agent es donde más difieren un compañero de equipo de workspace y una plataforma de agents. Registra el resultado con el [método de comparación](comparison.md#a-shared-trial).

## Preguntas frecuentes { #frequently-asked-questions }

### ¿AgenticOS es una alternativa a Viktor? { #is-agenticos-an-alternative-to-viktor }

Sí, si quieres algo más que un asistente compartido. AgenticOS ejecuta muchos agents, cada uno con sus propias instrucciones, acceso, conocimiento y budget, en tu propia infraestructura. Viktor se pone en marcha más rápido en Slack o Teams y se ejecuta en su propia nube.

### ¿AgenticOS puede responder en Slack como Viktor? { #can-agenticos-answer-in-slack-like-viktor }

Sí. Un agent publicado responde en Slack, y un usuario vinculado ejecuta los runs como sí mismo. AgenticOS también responde en Telegram, Mattermost, un widget para sitios web, una página alojada y la API HTTP. Todavía no tiene canal para Microsoft Teams.

### ¿Cómo se comparan los precios? { #how-does-pricing-compare }

Viktor vende créditos por workspace: Team cuesta $100 al mes por 40.000, compartidos en todo el workspace. AgenticOS no tiene cuota de licencia: pagas directamente a los providers de modelos, y cada agent tiene su propio budget mensual.

### ¿Dónde se almacenan los datos? { #where-is-the-data-stored }

Viktor dice que está alojado en EE. UU. por defecto; una de sus páginas ofrece residencia en la UE en contratos Enterprise y otra la sitúa en su hoja de ruta. AgenticOS almacena las conversaciones, los documentos y los vectores en tu propio Postgres, allí donde lo despliegues.

## Comparativas relacionadas { #related-comparisons }

[AgenticOS vs Claude](claude-apps.md) · [AgenticOS vs ChatGPT](chatgpt.md) · [AgenticOS vs Wonderful](wonderful.md) · [Todas las comparativas](comparison.md)

## Fuentes { #sources }

- [Página de producto y preguntas frecuentes de Viktor](https://viktor.com/): posicionamiento, instancia compartida del workspace, integraciones compartidas con el equipo o privadas, acceso a nivel de workspace.
- [Precios](https://viktor.com/pricing): planes de créditos Free, Team y Enterprise, límites de gasto, sin cuota por usuario.
- [Seguridad](https://viktor.com/security): alojamiento en EE. UU. por defecto, SOC 2 Type 1, ISO 27001 en curso, SSO SAML.
- [Empresa](https://www.viktor.com/enterprise): identidad heredada de Slack o Teams, residencia en la UE y retención en la hoja de ruta.
- [Changelog](https://www.viktor.com/changelog): claves de OpenRouter, modelos en el selector, Discord y correo electrónico.
