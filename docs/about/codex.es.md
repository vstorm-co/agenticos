---
source_sha: "b7ac54815ce6"
title: "AgenticOS vs OpenAI Codex"
description: "Codex es el agent de programación de OpenAI. AgenticOS ejecuta agents gobernados para toda la empresa, y Codex puede ayudar a ampliarlo."
---

# AgenticOS vs OpenAI Codex { #agenticos-vs-openai-codex }

OpenAI Codex es un agent de ingeniería de software. Abarca una CLI de código abierto, una extensión para el IDE, la app de escritorio de ChatGPT, tareas en la nube y la revisión de pull requests en GitHub. Está pensado para desarrolladores que cambian código. AgenticOS está pensado para los agents que usa toda una organización: los configuran los equipos de negocio en un navegador, se gobiernan en el servidor y se publican en superficies de chat, web y API.

Los dos comparten parte del terreno: una licencia Apache-2.0 para las partes abiertas, MCP, ejecución en sandbox y aprobación antes de las acciones arriesgadas. Lo aplican a usuarios distintos.

Mantenido por el equipo de AgenticOS. Fuentes revisadas el 25 de septiembre de 2026. Versión de referencia de AgenticOS: v0.0.504. Alcance de Codex: la documentación de Codex de OpenAI en learn.chatgpt.com, su página de precios y el repositorio `openai/codex`, no un despliegue empresarial probado.

## De un vistazo { #at-a-glance }

| Área | OpenAI Codex | AgenticOS |
| --- | --- | --- |
| Para quién es | Ingenieros de software | Equipos de negocio que configuran agents, y los ingenieros que los amplían |
| Sobre qué trabaja | Un repositorio de código y una shell | Documentos, herramientas y sistemas de la empresa |
| Dónde se ejecuta | Máquinas de los desarrolladores; tareas en la nube en contenedores gestionados por OpenAI | Tu infraestructura, como servicio compartido |
| Código | CLI Apache-2.0; nube, revisión y app de ChatGPT propietarias | Apache-2.0 |
| Modelos | OpenAI con inicio de sesión de ChatGPT; la CLI también admite Ollama, LM Studio, Bedrock y providers personalizados | 27 providers, definidos por perfil de modelo |
| Usuarios finales | El desarrollador | Empleados, clientes y sistemas, en ocho superficies |
| Aprobaciones | Modos de sandbox y políticas de aprobación en el puesto del desarrollador | Una persona con `approvals:decide`, desde una cola compartida |
| Control del gasto | Límites del plan por ventana de cinco horas y créditos compartidos con ChatGPT Work | Un budget mensual por agent y por organización |
| Precio | Incluido en los planes de ChatGPT; OpenAI estima entre $100 y $200 por desarrollador al mes en créditos | Sin cuota de licencia; uso del modelo e infraestructura |

## Dónde AgenticOS va más allá { #where-agenticos-goes-further }

### Agents para personas fuera de ingeniería { #agents-for-people-outside-engineering }

Las funciones en la nube de Codex requieren un plan de ChatGPT, y sus usuarios son desarrolladores. Para los agents de empresa, OpenAI remite en su lugar a los workspace agents de ChatGPT; consulta [AgenticOS vs ChatGPT](chatgpt.md). AgenticOS da a un equipo de negocio el camino completo: instrucciones, [capabilities](../reference/capabilities.md), conocimiento, un budget, una [versión publicada](../concepts.md#version) y [ocho superficies](../channels.md).

### Reglas que valen para todos a la vez { #rules-that-hold-for-everyone-at-once }

Codex aplica las políticas de sandbox y de aprobación en la máquina de cada desarrollador, con un `requirements.toml` gestionado para flotas. AgenticOS las aplica una sola vez, en el servidor. Los [permisos](../permissions.md), los [budgets](../governance.md#enforcement-is-before-the-request), las [aprobaciones](../governance.md#approvals) y el [registro de auditoría](../governance.md#audit) se aplican a cada run, sea cual sea la superficie que lo inició.

### Cualquier modelo, con todas las funciones { #any-model-with-every-feature }

La CLI de Codex puede usar otros providers, pero sus tareas en la nube, la revisión de código y Slack requieren un inicio de sesión de ChatGPT y modelos de OpenAI. En AgenticOS cada provider llega a la misma plataforma: [27 providers](../models.md#providers), [fallbacks](../models.md#fallbacks) y el coste registrado en cada run de cada agent.

### La ejecución de código como capability gobernada { #code-execution-as-a-governed-capability }

Codex ejecuta comandos en una sandbox del sistema operativo en la máquina del desarrollador o en un contenedor en la nube. AgenticOS da a los agents [Run Python](../reference/capabilities.md#run-python), un intérprete Monty sin red ni sistema de archivos, y un workspace de [Files & shell](../reference/capabilities.md#files-shell) en [contenedores hermanos](../sandbox.md#isolation-plainly). Ambos se activan por agent, con límites y un ajuste de aprobación.

## Cuándo Codex es la herramienta adecuada { #when-codex-is-the-right-tool }

- El trabajo es software: tareas paralelas en la nube, revisiones de pull requests y trabajo con la CLI en un repositorio.
- Quieres una CLI de programación de código abierto con sandbox impuesta por el sistema operativo y la red desactivada por defecto.
- Tus desarrolladores ya tienen puestos de ChatGPT.

## Úsalos juntos { #use-them-together }

Un ingeniero puede usar Codex para escribir, probar y revisar una nueva [capability](../howto/add-capability.md): Python tipado con tests, en un repositorio cuyas reglas para contribuir están escritas. Una vez fusionada, está disponible para todos los que construyen agents en la organización. El spec de un agent [se exporta como YAML](../features.md#exportable-into-your-own-repository), así que Codex también puede revisar un cambio de un agent en una pull request.

## Pruébalo con una tarea { #try-it-on-one-task }

Plantea a ambos la pregunta del [manual compartido](../howto/first-document-agent.md). Después pasa la respuesta a un compañero que no programa y comprueba qué necesita en cada uno antes de poder hacer su propia pregunta. Registra el resultado con el [método de comparación](comparison.md#a-shared-trial).

## Fuentes { #sources }

- [Repositorio de Codex](https://github.com/openai/codex): la CLI con licencia Apache-2.0.
- [Precios de Codex](https://learn.chatgpt.com/docs/pricing): planes, ventanas de uso, créditos y funciones por plan.
- [Aprobaciones y seguridad](https://learn.chatgpt.com/docs/agent-approvals-security): modos de sandbox y políticas de aprobación.
- [Configuración avanzada](https://learn.chatgpt.com/docs/config-file/config-advanced): providers de modelos personalizados y locales.
- [Configuración gestionada para empresas](https://learn.chatgpt.com/codex/enterprise/managed-configuration): `requirements.toml`.
- [Tarifas de ChatGPT](https://help.openai.com/en/articles/11481834-chatgpt-rate-card-business-enterpriseedu-credit-based-pricing): la estimación por desarrollador.
