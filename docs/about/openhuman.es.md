---
title: "AgenticOS vs OpenHuman"
seo_title: "AgenticOS vs OpenHuman: harness personal o plataforma"
description: "Compara OpenHuman y AgenticOS: un harness de agents personal y rápido con GPL-3.0 frente a una plataforma Apache-2.0 con budgets, roles y auditoría."
source_sha: "bc81d3a12c59"
---

# AgenticOS vs OpenHuman { #agenticos-vs-openhuman }

OpenHuman, de Tiny Humans, se presenta como el harness de agents de código abierto más rápido y barato: una app de escritorio y una biblioteca en Rust y Tauri con memoria, voz, control del navegador y del escritorio, grafos de workflow duraderos con aprobaciones, 14 canales y 26 providers más modelos locales. Publica cifras de benchmark para respaldarlo. AgenticOS está pensado para una organización y no para una persona: muchos agents con propietarios, roles, budgets y un registro de auditoría.

Mantenido por el equipo de AgenticOS. Fuentes revisadas el 26 de noviembre de 2026. Versión de referencia de AgenticOS: v1.95.0. Alcance de OpenHuman: el repositorio `tinyhumansai/openhuman`, su README y el repositorio de benchmarks publicado; no una instalación probada. OpenHuman se describe como beta temprana.

## De un vistazo { #at-a-glance }

| Área | OpenHuman | AgenticOS |
| --- | --- | --- |
| Qué es | Un harness de agents personal y para desarrolladores, app de escritorio y biblioteca en Rust | Una plataforma donde un equipo de negocio crea, publica y gobierna los agents de la empresa |
| Licencia | GPL-3.0 | Apache-2.0; consulta las [licencias de los componentes incluidos](../licenses.md) |
| Dónde se ejecuta | Escritorio, terminal o servidor sin interfaz | Tu infraestructura; las apps de [escritorio](../desktop.md) y de [teléfono](../mobile.md) se conectan a ella |
| Modelos | 26 providers con tus propias claves, más Ollama, LM Studio y MLX, con enrutamiento | 28 providers, incluidos locales, con [fallbacks](../models.md#fallbacks) |
| Control del gasto | Se registra el coste de cada llamada | Un budget mensual por agent y por organización, aplicado antes de cada petición al modelo |
| Aprobaciones | Las confirma el usuario, dentro de los grafos de workflow | Aprobación por capability, herramienta y conexión MCP, decidida por las personas que elijas |
| Organización | Una persona; no describe tenants, roles ni SSO | Muchas organizaciones, seis roles, concesiones por recurso, SSO con OIDC, LDAP y Kerberos |
| Auditoría | Registros de runs reproducibles | Registro de auditoría con detección de manipulaciones, exportable en CSV y JSONL |
| Creación de agents | Configuración y código | Un [Builder](../features.md) en el navegador para equipos de negocio, versiones y entornos |
| Workflows | Grafos duraderos con aprobaciones | Un lienzo visual de [workflows](../workflows.md) con pasos tipados, ramas, bucles y aprobaciones |

## Dónde llega más lejos AgenticOS { #where-agenticos-goes-further }

### Pensado para una organización, no para una persona { #built-for-an-organization-not-one-person }

OpenHuman funciona como el harness de una persona. AgenticOS identifica a las personas con [el directorio de la empresa](../directory.md#signing-in-with-a-directory-account), les da [roles y concesiones por recurso](../permissions.md#layer-3-visibility-and-grants) y aísla [organizaciones](../concepts.md#organizations) en un despliegue. Un agent pertenece a la empresa, no a quien lo instaló.

### Muchos agents acotados en lugar de uno que lo hace todo { #many-narrow-agents-instead-of-one-that-does-everything }

En AgenticOS cada agent tiene un propósito, sus propias instrucciones, capabilities y [budget](../governance.md#budgets), y una [versión](../concepts.md#version) publicada. Ves qué agent se ejecutó, cuánto costó y qué cambió, y puedes sustituir uno sin tocar los demás.

### Un budget que detiene, no solo un contador { #a-budget-that-stops-not-only-a-counter }

OpenHuman informa del coste de cada llamada. AgenticOS rechaza la siguiente petición al modelo cuando se alcanza el budget de un agent o el límite de la organización, y el [trabajo delegado](../governance.md#delegation-spends-the-parents-budget) gasta del budget del agent padre.

### Una licencia sobre la que construir un producto { #a-licence-you-can-build-a-product-on }

La GPL-3.0 exige que las obras derivadas que se distribuyan se publiquen con la misma licencia. Apache-2.0 no tiene esa condición, así que AgenticOS puede integrarse en un producto cerrado u ofrecerse como servicio.

## Cuándo encaja mejor OpenHuman { #when-openhuman-is-the-better-fit }

- Una persona o un desarrollador quiere el harness local más rápido, con control del escritorio y muchas integraciones a través de Composio.
- La eficiencia pura en un servidor pequeño importa más que los roles, los budgets y la auditoría.
- La GPL-3.0 encaja con cómo vas a distribuir tus cambios.

## Compara un cambio, no solo una respuesta { #compare-a-change-not-only-an-answer }

Los benchmarks miden un harness con tareas de programación. Para el uso en una empresa, mide otra cosa: añade una segunda persona con otro rol, da a un agent un budget de unos céntimos y supéralo, y exige que otra persona apruebe una llamada a herramienta. Anota lo que cada producto permite, rechaza y registra, con el [método de comparación](comparison.md#a-shared-trial).

## Preguntas frecuentes { #frequently-asked-questions }

### ¿Es OpenHuman una alternativa a AgenticOS? { #is-openhuman-an-alternative-to-agenticos }

Para los agents de una persona, puede serlo. Para una empresa, AgenticOS añade lo que OpenHuman no describe: tenants, roles, inicio de sesión con directorio, un budget aplicado antes de cada petición al modelo, aprobaciones por otra persona y un registro de auditoría de toda la organización.

### ¿Puede AgenticOS ejecutar también modelos locales? { #can-agenticos-run-local-models-too }

Sí. AgenticOS funciona con modelos de chat locales, embeddings locales y procesamiento local de documentos, y la app de escritorio puede usar modelos y servidores MCP locales en tu ordenador.

## Comparativas relacionadas { #related-comparisons }

[AgenticOS vs OpenAgents](openagents.md) · [AgenticOS vs OpenClaw](openclaw.md) · [Todas las comparativas](comparison.md)

## Fuentes { #sources }

- [`tinyhumansai/openhuman`](https://github.com/tinyhumansai/openhuman): funciones, canales, providers, licencia y estado de la versión.
- [Benchmarks de OpenHuman](https://github.com/tinyhumansai/openhuman-benchmarks): la comparación de harnesses publicada.
