---
title: "Condiciones de licencia comparadas"
seo_title: "Condiciones de licencia: plataformas de agents de IA"
description: "¿Qué plataformas de agents de IA son de código abierto sin condiciones? Compara Apache-2.0 con Apache modificada, Elastic License 2.0, Sustainable Use y ee."
source_sha: "733a5072cfd8"
---

# Condiciones de licencia comparadas { #licence-terms-compared }

«Código abierto» en la página de un producto suele significar código público con condiciones. Para una empresa que quiere modificar el software, o para un integrador que quiere alojar una instancia para varios clientes, esas condiciones deciden qué está permitido. Esta página ordena las plataformas de estas comparativas según lo que permite su licencia, con la cláusula relevante citada o resumida del archivo de licencia.

Mantenido por el equipo de AgenticOS. Archivos de licencia revisados el 26 de noviembre de 2026 en el repositorio principal de cada proyecto. Es un resumen orientativo, no asesoramiento jurídico; lee la propia licencia antes de depender de ella.

## Las clases de un vistazo { #the-classes-at-a-glance }

| Clase | Qué permite | Proyectos |
| --- | --- | --- |
| Licencia OSI permisiva, sin nada reservado | Usar, modificar, poner tu marca y alojar para otros | **AgenticOS** (Apache-2.0), framework Agno, Sim, OpenAgents, RAGFlow, LangBot (Apache-2.0); núcleo de LibreChat, AnythingLLM, Langflow, Hermes Agent, OpenClaw (MIT) |
| Copyleft | Usar y modificar; los cambios distribuidos, y con AGPL también el uso en red, deben compartirse con la misma licencia | OpenHuman, MaxKB (GPL-3.0); Khoj, Cherry Studio, Nextcloud (AGPL-3.0); el panel de administración de LibreChat (AGPL-3.0) |
| Open core con directorio enterprise | El núcleo es permisivo; las funciones de los directorios `ee` o `enterprise` requieren licencia comercial | Onyx, LiteLLM, Langfuse, Activepieces, Chatwoot, Mastra, Windmill |
| Apache 2.0 modificada | Apache 2.0 más condiciones sobre el uso multi-tenant o la marca | Dify, FastGPT |
| Source-available | Código público con condiciones que prohíben el uso competidor o alojado | Kortix CompanyOS (Elastic License 2.0), n8n (Sustainable Use License), AutoGPT Platform (Polyform Shield), Arize Phoenix (Elastic License 2.0) |
| Licencia propia con condiciones | Código público con condiciones comerciales o de marca añadidas | LobeHub (LobeHub Community License), Open WebUI (BSD-3 con cláusula de marca), NocoBase (su propio contrato de licencia) |

Entre las plataformas de código abierto para agents de empresa y los builders autoalojados, una licencia sin condiciones y sin directorio enterprise es minoría.

## Las cláusulas que importan { #the-clauses-that-matter }

### Kortix CompanyOS: Elastic License 2.0 { #kortix-companyos-elastic-license-20 }

No puedes ofrecer el software a terceros como servicio alojado o gestionado, ni mover, cambiar, desactivar o eludir la funcionalidad de su clave de licencia. El repositorio fue Apache-2.0 hasta diciembre de 2025 y pasó a la Elastic License 2.0 el 18 de febrero de 2026. Consulta [AgenticOS vs Kortix](kortix.md).

### Dify: Apache 2.0 con condiciones { #dify-apache-20-with-conditions }

Operar un entorno multi-tenant, donde un tenant es un workspace, requiere permiso por escrito, y no se pueden quitar ni cambiar el logotipo ni la información de copyright del frontend. Consulta [AgenticOS vs Dify](dify.md).

### n8n: Sustainable Use License { #n8n-sustainable-use-license }

El uso se limita a fines empresariales internos, no comerciales o personales. Las funciones de pago están en archivos `.ee.` y necesitan una clave de licencia. Consulta [AgenticOS vs n8n](n8n.md).

### LobeHub: LobeHub Community License { #lobehub-lobehub-community-license }

El uso comercial está permitido como servicio de frontend y backend sin modificar el código fuente. Desarrollar y distribuir una obra derivada requiere una licencia comercial, y los contribuidores aceptan que el productor pueda endurecer las condiciones. Consulta [AgenticOS vs LobeHub](lobehub.md).

### Open WebUI: BSD-3 con cláusula de marca { #open-webui-bsd-3-with-a-branding-clause }

Cambiar o eliminar su marca solo se permite en despliegues con un máximo de 50 usuarios en un periodo de 30 días; por encima, hace falta una licencia enterprise. Consulta [AgenticOS vs Open WebUI y LibreChat](open-webui-librechat.md).

### Onyx, LiteLLM, Langfuse: directorios enterprise { #onyx-litellm-langfuse-enterprise-directories }

El núcleo es MIT. El código de los directorios `ee` o `enterprise` está bajo una licencia comercial; en Onyx, su uso en producción requiere una licencia por número de puestos. Ahí suelen estar el inicio de sesión único, SCIM, los roles personalizados y las funciones de auditoría. Consulta [AgenticOS vs Onyx](onyx.md) y [AgenticOS vs un stack DIY](diy-stack.md).

### AutoGPT Platform: Polyform Shield { #autogpt-platform-polyform-shield }

El directorio `autogpt_platform` está bajo la licencia Polyform Shield, que prohíbe usarlo para competir con el licenciante; el resto del repositorio es MIT.

## AgenticOS { #agenticos }

AgenticOS es Apache-2.0, sin directorio enterprise y sin funciones reservadas para una edición de pago. Puedes modificarlo, ponerle tu marca y ejecutarlo para otras organizaciones desde un despliegue. Algunos componentes incluidos tienen sus propias licencias: el parser de PDF por defecto es AGPL-3.0, así que una imagen modificada que ofrezcas a otros te obliga a darles su código fuente. La [página de licencias](../licenses.md) enumera cada componente y [el componente AGPL](../licenses.md#the-agpl-component) explica la excepción.

## Preguntas frecuentes { #frequently-asked-questions }

### ¿Qué plataformas de agents de IA son totalmente de código abierto? { #which-ai-agent-platforms-are-fully-open-source }

De las comparadas aquí, AgenticOS, el framework Agno, Sim, OpenAgents, el núcleo de LibreChat, AnythingLLM y Langflow usan licencias OSI sin directorio enterprise. Dify, n8n, Kortix, LobeHub y Open WebUI añaden condiciones.

### ¿Puede un integrador alojar AgenticOS para varios clientes? { #can-an-integrator-host-agenticos-for-several-clients }

Sí. Apache-2.0 lo permite, y las organizaciones de un despliegue son tenants aislados. Las licencias de Dify y FastGPT exigen permiso para el uso multi-tenant, y la Elastic License 2.0 prohíbe ofrecer Kortix como servicio alojado.

### ¿Sustituye esta página a una revisión legal? { #does-this-page-replace-a-legal-review }

No. Las licencias cambian, como la de Kortix tres veces en un año. Lee el archivo de licencia de la versión que despliegues.

## Comparativas relacionadas { #related-comparisons }

[Todas las comparativas](comparison.md) · [Licencias de los componentes de AgenticOS](../licenses.md)

## Fuentes { #sources }

- [Licencia de Kortix](https://github.com/kortix-ai/CompanyOS/blob/main/LICENSE) · [Licencia de Dify](https://github.com/langgenius/dify/blob/main/LICENSE) · [Licencia de n8n](https://github.com/n8n-io/n8n/blob/master/LICENSE.md)
- [Licencia de LobeHub](https://github.com/lobehub/lobehub/blob/main/LICENSE) · [Licencia de Open WebUI](https://docs.openwebui.com/license) · [Licencia de Onyx](https://github.com/onyx-dot-app/onyx/blob/main/LICENSE)
- [Licencia de Langfuse](https://github.com/langfuse/langfuse/blob/main/LICENSE) · [LiteLLM enterprise](https://docs.litellm.ai/docs/enterprise) · [Licencia de AutoGPT](https://github.com/Significant-Gravitas/AutoGPT/blob/master/LICENSE)
