---
title: "AgenticOS vs Kortix"
seo_title: "AgenticOS vs Kortix CompanyOS: licencia y autoalojamiento"
description: "Compara Kortix CompanyOS y AgenticOS: Elastic License 2.0 frente a Apache-2.0, dónde se ejecutan las sesiones, budgets, aprobaciones, acceso y canales."
source_sha: "bf622c9110d0"
---

# AgenticOS vs Kortix { #agenticos-vs-kortix }

Kortix CompanyOS y AgenticOS se describen casi con las mismas palabras: un sistema operativo para una empresa que trabaja con agents de IA. La diferencia aparece en dos puntos que una revisión legal o de TI mira primero. Kortix pasó de Apache-2.0 a la Elastic License 2.0 en febrero de 2026, y su edición autoalojada sigue ejecutando las sesiones de los agents en sandboxes en la nube de Kortix. AgenticOS es Apache-2.0 y se ejecuta por completo en tu infraestructura.

Mantenido por el equipo de AgenticOS. Fuentes revisadas el 26 de noviembre de 2026. Versión de referencia de AgenticOS: v1.95.0. Alcance de Kortix: su web, su documentación, su página de precios y el historial del archivo `LICENSE` en `kortix-ai/CompanyOS`; no un workspace probado ni un despliegue autoalojado.

## De un vistazo { #at-a-glance }

| Área | Kortix CompanyOS | AgenticOS |
| --- | --- | --- |
| Qué es | Una empresa como repositorio git: agents, skills, memoria y conectores son archivos | Una consola donde un equipo de negocio crea agents versionados, workflows, apps y tablas |
| Licencia | Elastic License 2.0 desde el 18 de febrero de 2026; Apache-2.0 antes de diciembre de 2025 | Apache-2.0; consulta las [licencias de los componentes incluidos](../licenses.md) |
| Dónde se ejecuta | Nube de Kortix, o web, API y base de datos autoalojadas; las sesiones de los agents siguen en sandboxes en la nube de Kortix | Tu infraestructura, incluida la sandbox; es posible un despliegue aislado de la red |
| Modelos | Cualquiera, con tus propias claves | 28 providers, incluidos locales |
| Control del gasto | Un budget diario, semanal o mensual por workspace, que bloquea o avisa | Un budget mensual por agent y por organización, comprobado antes de cada petición al modelo |
| Aprobaciones | Allow, Ask o Deny por herramienta; decide un responsable del workspace o quien inició la sesión | Aprobación por capability, herramienta y conexión MCP; el run espera a las personas que elijas |
| Acceso y roles | SAML SSO, SCIM, grupos y roles personalizados tras una clave de licencia Enterprise | SSO con OIDC, LDAP y Kerberos, seis roles y concesiones por recurso en todos los despliegues |
| Auditoría | Archivo bloqueado; leerlo requiere Enterprise | Registro de auditoría con detección de manipulaciones, exportable en CSV y JSONL |
| Canales | Slack, Microsoft Teams, Telegram, Discord, correo; voz experimental | Chat web, widget, página alojada, API HTTP, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, correo electrónico, iMessage, llamadas telefónicas |
| Precios | Plan gratuito con 500 créditos; créditos desde 50 USD al mes; clave de licencia Enterprise | Sin coste de licencia; el uso de modelos a las tarifas de tu provider |

## Dónde llega más lejos AgenticOS { #where-agenticos-goes-further }

### Una licencia que te permite alojarlo para otros { #a-licence-that-lets-you-host-it-for-others }

La Elastic License 2.0 es una licencia source-available, no de código abierto. Prohíbe ofrecer el software a terceros como servicio alojado o gestionado, y mover, cambiar o eludir la funcionalidad de la clave de licencia. En Kortix, la clave desbloquea SAML, SCIM, grupos, roles personalizados, la lectura del archivo de auditoría y la marca propia.

La licencia cambió tres veces en menos de un año: Apache-2.0 en abril de 2025, una Kortix Non-Commercial License el 3 de diciembre de 2025, un día después una Kortix Public Source License y la Elastic License 2.0 el 18 de febrero de 2026. AgenticOS es Apache-2.0: puedes ejecutarlo para cada departamento, filial o cliente, modificarlo y ponerle tu propia marca.

### Un autoalojamiento que deja el trabajo en tus servidores { #self-hosting-that-keeps-the-work-on-your-servers }

Kortix documenta que una instalación autoalojada ejecuta la app web, la API y la base de datos, mientras las sesiones de los agents siguen en sandboxes en la nube de Kortix, y que el servidor debe ser accesible desde internet. Por tanto, no hay funcionamiento aislado de la red ni residencia completa de los datos.

En AgenticOS la [sandbox](../sandbox.md) forma parte de tu despliegue, y una instalación nueva no envía prompts ni documentos a ninguna parte. Consulta [qué sale por defecto](../data-protection.md#nothing-leaves-by-default).

### Un budget por agent, no por workspace { #a-budget-per-agent-not-per-workspace }

El budget de Kortix se aplica a todo un workspace. AgenticOS comprueba el [budget mensual](../governance.md#budgets) de cada agent y el límite de la organización [antes de cada petición al modelo](../governance.md#enforcement-is-before-the-request), y el [trabajo delegado](../governance.md#delegation-spends-the-parents-budget) gasta del budget del agent padre. Sabes qué agent gastó qué, y un agent desbocado no agota la asignación de todos.

### Los controles que pide una revisión, sin clave de licencia { #the-controls-a-review-asks-for-without-a-licence-key }

El [SSO con OIDC, LDAP y Kerberos](../directory.md#signing-in-with-a-directory-account), los [seis roles y concesiones por recurso](../permissions.md#layer-3-visibility-and-grants) y el [registro de auditoría con detección de manipulaciones](../governance.md#audit) están en todos los despliegues de AgenticOS. SAML y SCIM aún no están disponibles; SAML funciona a través de un broker como Keycloak.

### Muchas organizaciones en un despliegue { #many-organizations-in-one-deployment }

Las [organizaciones](../concepts.md#organizations) de AgenticOS son tenants aislados en el esquema. Kortix admite varios workspaces por cuenta y no describe el aislamiento entre tenants en tus propios servidores.

## Cuándo encaja mejor Kortix { #when-kortix-is-the-better-fit }

- Quieres una empresa descrita por completo como archivos en un repositorio git y editada con un agent de programación.
- Prefieres un producto gestionado en la nube que arranque en minutos, y la Elastic License 2.0 encaja con tu uso.
- Necesitas SAML o SCIM hoy y vas a comprar la clave de licencia Enterprise. AgenticOS todavía no tiene ninguno de los dos.

## Compara un cambio, no solo una respuesta { #compare-a-change-not-only-an-answer }

Ejecuta el fixture del [primer agent de documentos](../howto/first-document-agent.md) en ambos productos. Después comprueba dónde se ejecuta realmente una sesión observando las conexiones salientes del servidor autoalojado mientras trabaja un agent. Da a un agent un budget de unos céntimos y supéralo. Anota lo que cada producto permite, rechaza y registra, con el [método de comparación](comparison.md#a-shared-trial).

## Preguntas frecuentes { #frequently-asked-questions }

### ¿Es Kortix CompanyOS de código abierto? { #is-kortix-companyos-open-source }

No con una licencia OSI. Su repositorio pasó a la Elastic License 2.0 el 18 de febrero de 2026, que prohíbe ofrecerlo a otros como servicio alojado y eludir su clave de licencia. AgenticOS es Apache-2.0.

### ¿Puede Kortix ejecutarse por completo en mis servidores? { #can-kortix-run-fully-on-my-own-servers }

Según su documentación, una instalación autoalojada ejecuta la app web, la API y la base de datos, pero las sesiones de los agents siguen en sandboxes en la nube de Kortix. AgenticOS ejecuta todas las partes, incluida la sandbox, en tu infraestructura.

### ¿Tiene Kortix budgets y aprobaciones? { #does-kortix-have-budgets-and-approvals }

Sí: un budget por workspace que bloquea o avisa, y Allow, Ask o Deny por herramienta. AgenticOS fija un budget por agent y por organización, comprobado antes de cada petición al modelo, y dirige las aprobaciones a las personas que elijas.

## Comparativas relacionadas { #related-comparisons }

[AgenticOS vs LobeHub](lobehub.md) · [AgenticOS vs Agno AgentOS](agno.md) · [Condiciones de licencia comparadas](licence-terms.md) · [Todas las comparativas](comparison.md)

## Fuentes { #sources }

- [Kortix](https://kortix.com): descripción del producto y planes de precios.
- [Documentación de Kortix](https://kortix.com/docs/guide): autoalojamiento, sandboxes, budgets y aprobaciones.
- [Licencia de `kortix-ai/CompanyOS`](https://github.com/kortix-ai/CompanyOS/blob/main/LICENSE) y su historial: las condiciones de la Elastic License 2.0 citadas y las licencias anteriores.
- [Elastic License 2.0](https://www.elastic.co/licensing/elastic-license): el texto de la licencia.
