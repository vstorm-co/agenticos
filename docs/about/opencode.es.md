---
source_sha: "d0e31f6b27f0"
title: "AgenticOS vs OpenCode"
description: "OpenCode es un agent de programación de código abierto para un desarrollador. AgenticOS es una plataforma de código abierto para los agents de una empresa."
---

# AgenticOS vs OpenCode { #agenticos-vs-opencode }

OpenCode es un agent de programación de código abierto con licencia MIT. Se ejecuta en una terminal, una app de escritorio o un IDE y se conecta a más de 75 providers de modelos. Es una opción sólida para un desarrollador que quiere su propio agent en su propio repositorio. AgenticOS también es de código abierto, y está construido para otro trabajo: muchos agents, muchos usuarios, un único despliegue gobernado.

Mantenido por el equipo de AgenticOS. Fuentes revisadas el 25 de septiembre de 2026. Versión de referencia de AgenticOS: v0.0.504. Alcance de OpenCode: su documentación en opencode.ai y el repositorio `anomalyco/opencode` en v1.18.32, no un despliegue empresarial probado.

## De un vistazo { #at-a-glance }

| Área | OpenCode | AgenticOS |
| --- | --- | --- |
| Para quién es | Un desarrollador, en un repositorio | Una organización: equipos de negocio, usuarios finales e ingenieros |
| Dónde se ejecuta | La máquina del desarrollador; `opencode serve` para un servidor HTTP local | Un servicio compartido en tu infraestructura |
| Código | MIT | Apache-2.0 |
| Modelos | Más de 75 providers a través de Models.dev, incluidos locales | 27 providers, incluidos locales |
| Usuarios y acceso | Un usuario; los equipos de Zen tienen Admin y Member | Organizaciones, seis roles, 27 permisos, concesiones por recurso |
| Aprobaciones | `allow`, `ask` o `deny` por herramienta, respondidos desde el teclado | Una persona con `approvals:decide`, desde una cola compartida |
| Control del gasto | Límites mensuales en su gateway Zen | Un budget por agent y por organización, comprobado antes de cada petición al modelo |
| Auditoría | No documentada | Registro de auditoría con evidencia de manipulación |
| Compartir | Enlaces públicos en `opncd.ai` hasta que se dejan de compartir | Concesiones, páginas alojadas y artefactos con propietario y visibilidad |
| Precio | Gratis; opcionalmente Zen de pago por uso y Go a $10 al mes; Enterprise por puesto | Sin cuota de licencia; uso del modelo e infraestructura |

## Dónde AgenticOS va más allá { #where-agenticos-goes-further }

### Hecho para muchas personas, no para una { #built-for-many-people-not-one }

OpenCode guarda las claves de los providers en un archivo en la máquina del desarrollador y no tiene modelo de usuarios ni de roles en la herramienta de código abierto. AgenticOS tiene [organizaciones](../concepts.md#organizations), [roles y concesiones](../permissions.md#layer-3-visibility-and-grants) e [inicio de sesión con el directorio](../directory.md#signing-in-with-a-directory-account). Las claves están en un [vault sellado por organización](../secrets.md#envelope-encryption) y ningún endpoint las devuelve nunca.

### Agents que atienden a usuarios finales { #agents-that-serve-end-users }

Las superficies de OpenCode son para el desarrollador: TUI, escritorio, IDE y un servidor local. Un agent de AgenticOS responde a personas que nunca instalan nada, a través de un [widget](../channels.md#the-website-widget), una [página alojada](../channels.md#a-hosted-page), [Slack, Telegram o Mattermost](../channels.md#slack), o la [API HTTP](../channels.md#the-public-api).

### Gobernanza registrada en el servidor { #governance-recorded-on-the-server }

Los permisos de OpenCode protegen la máquina del desarrollador. AgenticOS registra cada run con su versión, superficie, coste y estado en el [historial de runs](../governance.md#what-run-history-shows). Los [budgets](../governance.md#enforcement-is-before-the-request) detienen a un agent antes de la siguiente petición al modelo, y el [registro de auditoría](../governance.md#audit) registra quién cambió qué.

### Conocimiento más allá del repositorio { #knowledge-beyond-the-repository }

OpenCode lee el repositorio y lo que devuelvan los servidores MCP. AgenticOS guarda los documentos de la empresa en [colecciones](../file-processing.md#rag-document-ingestion), con parsing por colección y sincronización desde Drive, S3, SharePoint, sitios web y git.

## Cuándo OpenCode es la herramienta adecuada { #when-opencode-is-the-right-tool }

- Un desarrollador quiere un agent de programación de código abierto con libre elección de provider.
- El trabajo está en un repositorio, y decide la persona que está al teclado.
- Quieres que el agent se ejecute por completo en la propia máquina del desarrollador.

## Úsalos juntos { #use-them-together }

Un desarrollador puede usar OpenCode con cualquier modelo para escribir una nueva [capability](../howto/add-capability.md) para AgenticOS. Una vez fusionada, los equipos de negocio la activan en sus agents.

## Pruébalo con una tarea { #try-it-on-one-task }

Responde en ambos a la pregunta del [manual compartido](../howto/first-document-agent.md). Después pasa el resultado a cinco compañeros y comprueba quién puede hacer una pregunta de seguimiento, cuánto cuesta y qué registro queda. Registra el resultado con el [método de comparación](comparison.md#a-shared-trial).

## Fuentes { #sources }

- [OpenCode](https://opencode.ai): posicionamiento y superficies.
- [Repositorio](https://github.com/anomalyco/opencode): la licencia MIT y las versiones publicadas.
- [Providers](https://opencode.ai/docs/providers/): más de 75 providers y modelos locales.
- [Permisos](https://opencode.ai/docs/permissions/): `allow`, `ask` y `deny`.
- [Compartir](https://opencode.ai/docs/share/): enlaces públicos para compartir.
- [Zen](https://opencode.ai/docs/zen/), [Go](https://opencode.ai/docs/go/) y [Enterprise](https://opencode.ai/docs/enterprise/): opciones de pago y límites.
