---
source_sha: "926f21066868"
title: "Investiga una pregunta con subagents y publica un informe"
description: "Divide una pregunta en subpreguntas independientes, delega cada una en un especialista de un solo uso y publica una comparación con fuentes como artefacto."
---

# Investiga una pregunta con subagents y publica un informe { #research-a-question-with-subagents-and-publish-a-report }

Construye un agent que divide una pregunta en partes independientes, entrega cada parte a su propio especialista y escribe un informe con lo que vuelve. El ejemplo es una comparación de tres licencias de código abierto: un tema estable y público en el que cada afirmación puede comprobarse con el propio texto de la licencia. Es un procedimiento para ejecutar, con un run registrado como referencia.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo.
- Búsqueda web: el método por defecto es DuckDuckGo y no necesita cuenta ni clave.
- Sin sandbox, sin colección de conocimiento y sin conexión MCP.

## Prepara la entrada { #prepare-the-input }

La pregunta se divide en tres subpreguntas independientes, una por licencia. Pregunta:

```text
Compare the MIT licence, the Apache License 2.0 and the GPLv3 on one question:
when you distribute software that includes code under that licence, what are
you obligated to do - include the licence text, state changes you made, or
disclose or release your own source code?
```

La respuesta de referencia, para comprobar a mano el informe del agent:

| Licencia | Incluir el texto de la licencia | Indicar los cambios | Publicar tu código fuente |
| --- | --- | --- | --- |
| MIT | Sí | No | No |
| Apache-2.0 | Sí, más el archivo `NOTICE` | Sí, por archivo | No |
| GPLv3 | Sí | Sí, por archivo | Sí, de toda la obra combinada, al distribuir |

La obligación de publicar el código de la GPLv3 la activa la distribución, no la modificación: una organización que solo ejecuta internamente una copia modificada no debe nada a nadie.

## Construye el agent { #build-the-agent }

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
2. En **Toolbox**, activa **Delegation**. Activa `allow_dynamic`, el ajuste que permite al modelo inventar un especialista de un solo uso para una subpregunta para la que nadie escribió uno de antemano. Pon el modo en **Async**, para que las tres subpreguntas se ejecuten a la vez y no una tras otra, y deja el límite de ramificación en 3.
3. Todavía en Delegation, activa **Share Web search with delegates** y **Share Web fetch with delegates**. Un especialista inventado por el modelo no recibe capabilities propias [por diseño](../reference/capabilities.md#delegation): solo le llega lo que el padre comparte explícitamente, así que sin este paso cada especialista inventado podría delegar pero no buscar.
4. Activa **Web search** (método DuckDuckGo) y **Read web pages** en el propio padre: compartir solo hace llegar a un delegado aquello a lo que el padre está vinculado.
5. Activa **Planning** y **Artifacts**.
6. Fija un budget y un límite de pasos para la prueba. El run registrado usó 40 pasos y costó unos 0,43 USD.
7. Escribe las instrucciones de abajo y luego pulsa **Publish**.

```text
You research a question that splits into independent sub-questions.
Write a plan naming each sub-question as its own step.
For each sub-question, call delegate to create a one-off specialist with
mode="async": give it a narrow instruction (research exactly this one
sub-question, using web search and web fetch, and answer with a short sourced
summary), a clear name, and no capabilities argument.
After firing all the sub-questions, call wait_tasks for all of them before
writing anything.
Every claim in your final report must carry the source URL it came from.
State plainly where the sources disagree or where you could not find an answer.
Publish the finished report with publish_artifact under the name
licence-comparison.
Do not answer from your own training knowledge without a source URL next to it.
```

## Ejecútalo { #run-it }

Abre un chat nuevo con el agent y envía la pregunta de *Prepara la entrada*.

El modelo llama a `delegate` tres veces, una por licencia: cada llamada es su propia delegación, no una sola llamada que hace las tres. **Delegate tiene efectos secundarios**, así que las tres quedan aparcadas para aprobación a la vez, porque un paso del modelo puede aparcar varias llamadas juntas. Lee los tres especialistas propuestos y pulsa **Approve**. El run se reanuda, lanza los tres especialistas en segundo plano y llama a `wait_tasks` para recogerlos antes de escribir el informe.

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| Número de delegaciones | Tres, una por licencia, cada una en su propia fila de Activity bajo el run padre |
| Obligación de MIT | Incluir el texto de la licencia y el aviso de copyright; nada más |
| Obligación de Apache-2.0 | Texto de la licencia, archivo `NOTICE` y un aviso de cambios por archivo |
| Obligación de GPLv3 | Texto de la licencia, cambios por archivo y el código fuente completo al distribuir |
| Cada afirmación | Lleva la URL de su fuente al lado, no reunidas en una lista al final |
| Discrepancia o laguna | El informe lo dice explícitamente o afirma que no hubo ninguna |
| Artefacto | **Artifacts** muestra `licence-comparison`, privado para ti |
| Una pregunta de dos partes con una sola fuente real (p. ej. sobre una licencia que no existe) | El informe dice que no pudo confirmar esa parte en lugar de inventarse una respuesta |

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter. El agent escribió un plan de cuatro pasos y luego llamó tres veces a `delegate` en un mismo turno: `mit-licence-research`, `apache2-licence-research`, `gplv3-licence-research`, todas asíncronas. Las tres quedaron aparcadas para aprobación en un solo paso; tras aprobarlas, el run llamó a `wait_tasks` y obtuvo `3/3 finished`. El informe coincidió exactamente con la tabla de referencia, citó las páginas de OSI, Apache.org, GNU.org y las FAQ de la FSF, y terminó con "No source disagreements found" nombrando las fuentes coincidentes. Publicó `licence-comparison` como artefacto HTML. Coste total: 0,43 USD, incluidas las tres delegaciones. Un especialista dinámico no tiene su propia fila en `agent_runs`, porque no es un agent publicado.

## Cuando algo sale mal { #when-it-goes-wrong }

- **Una delegación se rechaza directamente en lugar de quedar aparcada.** Delegation está desactivado, o `allow_dynamic` está desactivado y el modelo intentó `delegate` o `create_agent` de todos modos; sin ninguno de los dos, a una delegación solo se le ofrece `task`.
- **Un especialista dice que no tiene herramienta de búsqueda.** No se configuró `share_with_delegates`, o nombra una capability a la que el propio padre no está vinculado. La publicación rechaza el segundo caso, así que suele ser el primero.
- **Las tres subpreguntas se ejecutan una tras otra, no juntas.** El modo es `sync`, o el modelo eligió `mode="sync"` en sus propias llamadas a `delegate` pese a las instrucciones.
- **Solo aparece una delegación que lo cubre todo.** El modelo trató la pregunta de tres partes como una sola tarea en lugar de dividirla. Endurece las instrucciones para que nombren delegar cada parte por separado, no solo investigarla.
- **El run se detiene con "reached the fan-out ceiling".** Se lanzaron más delegaciones que `max_fanout` en un turno; tres subpreguntas caben en el valor por defecto de 3, pero una cuarta no.

## Registra la prueba { #record-the-trial }

Guarda la pregunta, el plan que escribió el agent, el nombre y el resultado de cada delegación, las fuentes citadas, el artefacto y su versión, y el coste de Activity. Una persona sigue leyendo el artefacto frente a los datos de referencia antes de fiarse de él, decide quién puede leerlo y juzga si la sección "could not confirm" es honesta o esconde una búsqueda que debió repetirse.

## Siguientes pasos { #next-steps }

Cuando esto funcione con un tema de respuesta conocida, apunta el agent a una pregunta sin referencia fija y apóyate en la instrucción "state where sources disagree" en lugar de en una tabla que ya conoces. Para mantener el informe al día, continúa con [programa un informe semanal](scheduled-report.md).
