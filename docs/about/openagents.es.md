---
title: "AgenticOS vs OpenAgents"
seo_title: "AgenticOS vs OpenAgents: crear y gobernar, o colaborar"
description: "Compara OpenAgents y AgenticOS, ambos Apache-2.0: un workspace donde colaboran personas y agents externos frente a una plataforma que crea y gobierna agents."
source_sha: "27048ef8f806"
---

# AgenticOS vs OpenAgents { #agenticos-vs-openagents }

OpenAgents se define como «el sistema operativo de colaboración para personas y agents de IA». Sus workspaces funcionan como un chat de equipo donde personas y agents comparten hilos, un navegador, incidencias y rutinas, y su launcher conecta unos 27 runtimes de agents como Claude Code, Codex, Gemini CLI y Cursor. Ambos productos son Apache-2.0, autoalojados y tienen apps de escritorio y de teléfono. La diferencia: OpenAgents coordina agents creados en otro sitio, mientras AgenticOS crea, ejecuta y gobierna los agents propios de la empresa.

Mantenido por el equipo de AgenticOS. Fuentes revisadas el 26 de noviembre de 2026. Versión de referencia de AgenticOS: v1.95.0. Alcance de OpenAgents: openagents.org y el repositorio `openagents-org/openagents`; no un workspace probado. OpenAgents Inc., en openagents.com, es otra empresa.

## De un vistazo { #at-a-glance }

| Área | OpenAgents | AgenticOS |
| --- | --- | --- |
| Qué es | Un workspace compartido para personas y agents de muchos runtimes | Una plataforma donde un equipo de negocio crea, publica y gobierna los agents de la empresa |
| Licencia | Apache-2.0; launcher MIT | Apache-2.0; consulta las [licencias de los componentes incluidos](../licenses.md) |
| Dónde se ejecuta | Alojado gratis, o autoalojado | Tu infraestructura |
| Agents | Conecta unas 27 CLI de agents de programación y generales con sus propias claves | Crea agents sobre 28 providers; ejecuta Claude Code y Codex en local en la [app de escritorio](../desktop.md#coding-agents-on-this-computer) y mediante el [coding agent](../reference/capabilities.md#coding-agent) |
| Colaboración | Hilos con menciones @agent, navegador compartido, incidencias, rutinas | [Proyectos](../projects.md) con archivos, instrucciones y chats compartidos; rutinas y tareas |
| Aprobaciones | Elegir quién aprueba la acción de un agent | Aprobación por capability, herramienta y conexión MCP, con una [cola de aprobaciones](../governance.md#approvals) |
| Control del gasto | No descrito | Un budget mensual por agent y por organización, comprobado antes de cada petición al modelo |
| Acceso y auditoría | Roles en la versión autoalojada; SSO y auditoría no descritos | SSO con OIDC, LDAP, Kerberos, seis roles y un registro de auditoría con detección de manipulaciones |
| Conocimiento | No descrito | [Bases de conocimiento](../file-processing.md) con procesamiento de documentos y conectores sincronizados |
| Canales | Sus propias apps web, de escritorio y de teléfono | Chat web, widget, página alojada, API HTTP, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, correo electrónico, iMessage, llamadas telefónicas; apps de escritorio y de teléfono |

## Dónde llega más lejos AgenticOS { #where-agenticos-goes-further }

### Agents separados, cada uno con propietario { #separate-agents-each-with-an-owner }

OpenAgents lleva agents existentes a una sala compartida. AgenticOS es el lugar del que salen esos agents: cada uno tiene instrucciones, un perfil de modelo, capabilities, un [budget](../governance.md#budgets) y un propietario, y se publica en [versiones](../concepts.md#version). En lugar de un asistente del que se espera todo, una empresa crea varios agents acotados y puede ver cuál hizo qué.

### La gobernanza que pide una revisión en la empresa { #governance-a-company-review-asks-for }

AgenticOS comprueba el gasto [antes de cada petición al modelo](../governance.md#enforcement-is-before-the-request), escribe cada acción en un [registro de auditoría con detección de manipulaciones](../governance.md#audit), identifica a las personas con [el directorio de la empresa](../directory.md#signing-in-with-a-directory-account) y atiende a [muchas organizaciones](../concepts.md#organizations) desde un despliegue. OpenAgents no describe budgets, auditoría ni SSO.

### Conocimiento, modelos y canales en un solo lugar { #knowledge-models-and-channels-in-one-place }

Los agents de AgenticOS responden desde bases de conocimiento y llegan a las personas en Slack, Microsoft Teams, por correo electrónico, SMS, teléfono y un widget web. Los agents de OpenAgents traen sus propias claves y viven en las apps de OpenAgents.

## Cuándo encaja mejor OpenAgents { #when-openagents-is-the-better-fit }

- Tu gente ya usa muchos agents de programación y quiere una sala compartida para ellos, con navegador compartido.
- Quieres coordinar agents en lugar de crearlos y gobernarlos.
- Necesitas runtimes más allá de los que AgenticOS admite en local.

## Mejor juntos { #better-together }

AgenticOS es un [servidor MCP](../mcp.md#agenticos-as-an-mcp-server) y habla [A2A](../channels.md#a2a), así que un agent gobernado de AgenticOS puede alcanzarse desde herramientas de otro workspace mientras su budget, sus aprobaciones y su auditoría se quedan en AgenticOS. Comprueba qué puede llamar tu configuración de OpenAgents antes de depender de ello.

## Preguntas frecuentes { #frequently-asked-questions }

### ¿Es OpenAgents una alternativa a AgenticOS? { #is-openagents-an-alternative-to-agenticos }

En parte. Ambos son Apache-2.0, autoalojados y tienen apps de escritorio y de teléfono. OpenAgents es una capa de colaboración para agents creados en otro sitio; AgenticOS crea y gobierna los agents, con budgets, aprobaciones, auditoría e inicio de sesión con directorio.

### ¿Puede AgenticOS ejecutar Claude Code o Codex? { #can-agenticos-run-claude-code-or-codex }

Sí. La app de escritorio ejecuta Claude Code, Codex y varios runtimes más en tu ordenador, en una carpeta aprobada, y la capability coding agent entrega el trabajo de software a Claude Code o Codex en una sandbox.

## Comparativas relacionadas { #related-comparisons }

[AgenticOS vs OpenHuman](openhuman.md) · [AgenticOS vs Claude Code](claude-code.md) · [AgenticOS vs Codex](codex.md) · [Todas las comparativas](comparison.md)

## Fuentes { #sources }

- [OpenAgents](https://openagents.org): workspaces, hilos, el navegador compartido, rutinas, aprobaciones y apps.
- [`openagents-org/openagents`](https://github.com/openagents-org/openagents): licencia, el launcher y los runtimes admitidos.
