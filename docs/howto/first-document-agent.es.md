---
source_sha: "90d62e9ab4aa"
title: "Crea tu primer agent con documentos"
description: "Crea un asistente que responda preguntas sobre solicitudes de equipos. Este ejemplo sintético contiene un hecho comprobable y una laguna deliberada. Es un procedimiento, no un informe de resultados medidos."
---

# Crea tu primer agent con documentos { #build-your-first-document-agent }

Crea un asistente que responda preguntas sobre solicitudes de equipos. Este ejemplo sintético contiene un hecho comprobable y una laguna deliberada. Es un procedimiento, no un informe de resultados medidos.

## Prepara la fuente { #prepare-the-source }

Necesitas una [instalación en marcha](../install.md) y un modelo. [Tu primer agent](../first-agent.md) explica credenciales y configuración. El coste depende del proveedor y los ajustes.

Guarda como `equipment-handbook.md`:

```text
Equipment requests go to the office manager.
Include the item, reason and delivery location.
```

Son políticas inventadas. No indican un límite de gasto.

## Construye y publica { #build-and-publish }

1. En **Knowledge → Collections**, abre el formulario de creación y despliega **Embeddings**. Selecciona un proveedor/modelo de embeddings compatible y su credencial del almacén o endpoint local. Crea la colección y sube el archivo. Un modelo de chat por sí solo no basta. Espera al procesamiento y comprueba el estado.
2. Crea un agent en **Agents → New agent** y selecciona el perfil de modelo.
3. En **Toolbox**, activa knowledge, vincula solo la colección de prueba y usa estas instrucciones.
4. Configura budget y límite de pasos adecuados y pulsa **Publish** para publicar la versión de prueba.

```text
Answer equipment-policy questions from the bound handbook.
Cite the document you used.
If it does not contain the answer, say what is missing.
Do not invent policies or submit equipment requests.
```

## Comprueba el resultado { #check-the-result }

| Pregunta | Criterio |
| --- | --- |
| Who handles an equipment request? | Office manager, respaldado por la fuente |
| Which details should I include? | Item, reason y delivery location |
| How much can I spend? | Indica que la fuente no contiene el límite |

Pregunta en una conversación nueva. Inspecciona respuesta y material recuperado en [Activity](../governance.md). Conserva también respuestas incorrectas o incompletas. Si la recuperación está vacía, revisa colección, permisos y procesamiento antes del prompt.

Cambia el responsable del archivo de prueba a facilities team. En la [lista de documentos de la colección](../file-processing.md), elimina el documento original y espera a que termine antes de subir el archivo editado. Subir de nuevo el mismo nombre de archivo no sustituye por sí solo los vectores antiguos. Espera al procesamiento y repite en otra conversación. Comprueba que no se sigue recuperando material obsoleto.

## Comparte el siguiente paso { #share-the-next-step }

Tras verificar el resultado, elige [Slack u otro punto de acceso](../channels.md). La Hosted Page es pública mediante enlace: usa datos públicos o sintéticos. El canal no determina los permisos documentales.

Asigna un [responsable operativo](../rollout.md) antes del piloto. Si falla un paso, incluye versión, configuración y reproducción sin datos privados en una [solicitud de ayuda](../help.md).
