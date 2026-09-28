---
source_sha: "37a9ef11651d"
title: "Crea tu primer agent con documentos"
description: "Dale a un agent un manual pequeño, haz una pregunta y comprueba la respuesta frente a la fuente."
---

# Crea tu primer agent con documentos { #build-your-first-document-agent }

Crea un asistente que responda preguntas sobre la política de equipos a partir de un documento. Este fixture sintético te da un hecho que comprobar y una laguna de información deliberada. Es un procedimiento que ejecutar, con un run registrado como referencia.

## Prepara la fuente { #prepare-the-source }

Usa una [instalación en marcha](../install.md) y un modelo configurado. Sigue [tu primer agent](../first-agent.md) para la credencial del proveedor y la configuración del modelo. El coste depende del proveedor y la configuración elegidos.

Guarda este texto como `equipment-handbook.md`:

```text
Equipment requests go to the office manager.
Include the item, reason and delivery location.
```

Son hechos de política inventados. No se indica ningún límite de gasto.

## Construye y publica { #build-and-publish }

1. En **Knowledge → Collections**, abre el diálogo de creación y despliega **Embeddings**. Selecciona un proveedor/modelo de embeddings compatible y su credencial del vault o endpoint local, después crea la colección y sube el archivo. Un modelo de chat por sí solo no basta. Espera al procesamiento y comprueba el estado del documento.
2. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
3. En **Toolbox**, activa knowledge y vincula solo la colección de prueba. Pon las instrucciones de abajo.
4. Define un budget y un límite de pasos adecuados a la prueba y pulsa **Publish** para publicar la versión que vas a probar.

```text
Answer equipment-policy questions from the bound handbook.
Cite the document you used.
If it does not contain the answer, say what is missing.
Do not invent policies or submit equipment requests.
```

## Comprueba el resultado { #check-the-result }

| Pregunta | Comprobación de referencia |
| --- | --- |
| Who handles an equipment request? | Nombra al office manager, respaldado por la fuente |
| Which details should I include? | Item, reason y delivery location |
| How much can I spend? | Dice que la fuente no indica ninguna asignación |

Pregunta en una conversación de prueba nueva. Inspecciona la respuesta y el material recuperado en [Activity](../governance.md). Conserva también las respuestas incorrectas o incompletas, no solo las correctas. Si la recuperación está vacía, revisa la vinculación de la colección, los permisos y el procesamiento antes de cambiar el prompt.

Cambia el responsable a facilities team en el archivo de prueba. En la [lista de documentos de la colección](../file-processing.md), elimina el documento de prueba original y espera a que la eliminación termine antes de subir el archivo editado. Subir de nuevo el mismo nombre de archivo por sí solo no sustituye los vectores antiguos. Espera al procesamiento y repite en una conversación nueva. Comprueba que no se sigue recuperando material obsoleto.

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter, búsqueda en knowledge vinculada a la única colección. "Who handles an equipment request?" llamó a `search_documents` una vez y respondió "equipment requests go to the office manager," con los tres detalles, citando `equipment-handbook.md`. "How much can I spend?" llamó a `search_documents` dos veces y respondió que el manual "does not contain any information about spending limits or purchase approval thresholds." Coste de las tres preguntas y un reintento más abajo: 0,043 USD.

    "Which details should I include?" devolvió primero una pregunta aclaratoria ("could you clarify what you're referring to?") en lugar de buscar — preguntada sola en una conversación nueva, la frase no lleva el tema de la solicitud de equipos. Un segundo intento de la misma pregunta llamó a `search_documents` y respondió correctamente. Formúlala nombrando el tema si quieres que la búsqueda se dispare a la primera.

    Tras eliminar el documento original, confirmar que la lista quedó vacía y subir el archivo editado, la misma primera pregunta en una conversación nueva respondió "equipment requests go to the facilities team" sin mencionar al office manager. Coste total de los cinco turnos: 0,055 USD.

## Comparte el siguiente paso { #share-the-next-step }

Una vez comprobado el resultado, lleva el agent [a Slack](slack-handbook-assistant.md) o elige [otro punto de acceso](../channels.md). La Hosted Page es pública mediante enlace: usa ahí material público o sintético. La elección de canal no establece las reglas de acceso a los documentos.

Antes de un piloto con el equipo, asigna el [responsable operativo](../rollout.md). Si un paso falla, incluye la versión, la configuración y una reproducción censurada en una [solicitud de ayuda](../help.md).
