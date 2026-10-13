---
source_sha: "6ff659040810"
title: "Despliega y opera AgenticOS"
description: "Asigna responsabilidades, entiende los costes y acuerda ayuda de implementación."
---

# Despliega y opera AgenticOS { #deploy-and-operate-agenticos }

AgenticOS es una aplicación que opera tu organización. Empieza con [una tarea verificable](howto/first-document-agent.md) y decide quién mantiene el despliegue y quién responde por el trabajo del agent.

## Quién mantiene cada parte { #who-maintains-what }

| Área | Responsabilidad |
| --- | --- |
| Hosting y actualizaciones | Desplegar servicios, vigilar capacidad, revisar versiones y planificar actualizaciones |
| Copias y recuperación | Respaldar bases y datos de workspace necesarios, proteger claves y probar restauración |
| Fuentes y comportamiento | Mantener documentos, instrucciones, skills y versiones publicadas |
| Acceso y secretos | Gestionar identidades, permisos, credenciales y rotación |
| Fallos y aprobaciones | Inspeccionar runs, asignar incidentes y decisores autorizados |
| Servicios externos | Revisar modelos, parsers, embeddings, herramientas, sandbox, canales y trazas |

Detalles: [instalación](install.md), [despliegue](deployment.md), [secretos](secrets.md), [permisos](permissions.md) y [seguridad](security.md). Conserva pruebas de restauración y contactos operativos. Publicar un agent no sustituye ese trabajo.

## Costes y opciones de entrega { #costs-and-delivery-options }

Cuenta modelos, infraestructura, servicios externos, implementación y tiempo operativo. El gasto registrado en runs es solo una parte. Revisa [licencias del proyecto y componentes](licenses.md).

Puedes operar AgenticOS por tu cuenta. Vstorm puede ayudar por separado con infraestructura del cliente, documentación, procesos y desarrollo personalizado. El mantenimiento continuo requiere acordar alcance y responsabilidades. Instalar el proyecto no incluye un precio de servicio, soporte ni SLA.

Contacta con [Vstorm](https://vstorm.co/) o Kacper indicando tarea, fuentes, restricciones y responsable operativo. No hacen falta documentos privados para la primera conversación.

<span id="what-your-security-review-will-ask"></span>

## Límites que verificar { #boundaries-to-verify }

Autoalojado no significa offline. Un modelo local cambia una ruta; parsing, embeddings, herramientas, sandboxes alojados, canales y trazas pueden usar servicios externos. Revisa el [flujo de datos](security.md).

Las aprobaciones dependen de capability y configuración. El budget comprueba gasto registrado antes de llamar al modelo y no garantiza ausencia de sobrecoste. Los permisos de colección no prueban herencia de todas las ACL de origen. Prueba identidades y tarea con [governance](governance.md) y [acceso a colecciones](file-processing.md).

## Evalúa el piloto { #evaluate-the-pilot }

Registra proceso actual, preguntas de aceptación, versión de fuente, modelo, herramientas y resultados reales. Incluye lagunas, fallos, revisión y consumo. Cambia un hecho y repite antes de ampliar.

Usa [comparaciones](about/comparison.md) para elegir y [ayuda](help.md) para fallos reproducibles. Un piloto puede justificar ampliar, corregir o detener un caso; no promete un resultado empresarial.
