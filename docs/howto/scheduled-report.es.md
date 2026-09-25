---
source_sha: "c64d022dd8b0"
title: "Programa un informe semanal"
description: "Dale a un agent una tarea de informe autocontenida, ejecútala bajo demanda, publica el resultado como artefacto y ponla en una programación semanal."
---

# Programa un informe semanal { #schedule-a-weekly-report }

Crea un agent que escriba un informe breve a partir de los datos de su tarea y lo publique como [artefacto](../artifacts.md) bajo un enlace estable. Después ponlo en una programación semanal. El fixture incluye una fila que no se puede usar, para que puedas comprobar que el agent la señala en lugar de ocultarla. Es un procedimiento que ejecutar, con un run registrado como referencia.

La página separa dos preguntas. ¿Sale bien el informe? Compruébalo con **Run now**. ¿Lo entrega la programación? Solo un disparo programado responde a eso.

## Construye el agent { #build-the-agent }

Usa una [instalación en marcha](../install.md) con un perfil de modelo. No hacen falta ni sandbox ni modelo de embeddings.

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
2. En **Toolbox**, activa **Charts** y **Artifacts**.
3. Define un budget y un límite de pasos para la prueba. Los runs registrados usaron 15 pasos y costaron unos 0,05 USD cada uno.
4. Pon las instrucciones de abajo y pulsa **Publish**.

```text
You write short reports from data given in the task.
Use only the rows in the task. Report totals per category and name any row you could not use.
Label the report as synthetic when the task says the data is synthetic.
Publish the finished report with publish_artifact under the name weekly-report.
```

El nombre del artefacto es su identidad. Cada run de este agent que publica `weekly-report` actualiza el mismo artefacto, así que el enlace que compartes no cambia. Un run añade una versión solo cuando la página cambió. Un contenido idéntico responde `unchanged` y conserva la última versión.

## Crea la programación { #create-the-schedule }

Abre **Routines → New schedule**, o la pestaña **Availability** del agent, y elige el agent. Pon los datos en el mensaje, para que un run posterior no dependa de un archivo que alguien subió a un chat anterior:

```text
Create a report for the synthetic period Demo Week.
Use only these CSV rows:
category,amount
Supplies,20
Supplies,30
Travel,15
Travel,abc
Report totals by category in a fictional demo currency and draw a bar chart.
Label the report synthetic and name any row you could not use.
```

Para la cadencia, elige **At a set time**, después **Days of the week**, marca **Mon** y pon **Time (UTC)** a las 09:00. La expresión cron equivalente es `0 9 * * 1`. El programador trabaja en UTC, así que convierte desde tu hora local. Guarda y comprueba la hora del próximo disparo que muestra la programación.

La programación se ejecuta como el miembro que la creó, con el acceso de ese miembro, y sus runs se cargan al budget del agent como cualquier otro. [Conceptos](../concepts.md#trigger) explica por qué.

## Ejecútalo ahora { #run-it-now }

Pulsa **Run now** en la programación. Hace un disparo adicional y deja sin cambios la cadencia semanal. La petición vuelve en cuanto el worker acepta el disparo. El run aparece entonces en la conversación propia de la programación, en **Routines** en la barra lateral del chat.

| Comprobación | Referencia |
| --- | --- |
| Totales | Supplies 50, Travel 15 |
| La fila `Travel,abc` | Señalada como inutilizable, y no contada |
| Etiqueta | El informe dice que los datos son sintéticos |
| Artefacto | **Artifacts** muestra `weekly-report`, privado para ti |
| El run en Activity | Superficie `schedule`, estado completado |
| Run now por segunda vez | El mismo artefacto y enlace: una versión nueva si la página cambió, o `unchanged` si el contenido es idéntico |

Abre la página del artefacto y lee allí el informe, no solo la respuesta del chat. La página es lo que abrirá la gente. Sigue siendo privada hasta que la compartas o crees un enlace público.

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter. La programación indicó como próximo disparo el lunes 28 de septiembre, a las 09:00 UTC. Run now se aceptó con `202`, y el run terminó en la superficie `schedule` unos 30 segundos después, por 0,044 USD.

    El agent llamó a `publish_artifact` con el nombre `weekly-report` y obtuvo la versión 1, privada. Después llamó a `create_chart`. El artefacto mostraba Supplies 50 y Travel 15, una etiqueta de datos sintéticos y "Rows excluded (could not be used): Travel, abc". Un segundo Run now añadió la versión 2 al mismo artefacto y enlace.

    El gráfico apareció en la conversación del run, no en el artefacto. La página del artefacto no tiene acceso a la red, y el agent escribió el informe sin un gráfico incrustado.

## Lo que la programación no decide por ti { #what-the-schedule-does-not-decide-for-you }

- **De dónde vienen los datos.** Este fixture está fijado en el mensaje. Un informe real necesita una fuente a la que el agent pueda llegar en cada run, como una [colección de knowledge](set-up-knowledge-base.md), una [conexión MCP](../mcp.md) o un workspace de sandbox. Una programación no puede adivinar qué archivo recién subido sustituye al de la semana pasada.
- **El periodo del informe.** Indícalo en el mensaje o haz que el agent lea la fecha. Un archivo llamado "weekly" no le dice al modelo qué fechas incluir.
- **Quién lo lee.** Un artefacto nuevo es privado para la persona para la que se hizo el run. Compártelo, o crea un enlace público, en la página del artefacto. [Artefactos](../artifacts.md) cubre la visibilidad y los grants.
- **Las aprobaciones.** Ninguna de las herramientas usadas aquí necesita una. Si añades una herramienta que sí la necesita, un run programado queda aparcado hasta que alguien decida, así que nombra a quién vigila la [cola de aprobaciones](../governance.md#approvals).

## Observa un disparo real { #watch-a-real-fire }

Run now prueba la tarea, no la programación. Después del primer lunes a las 09:00 UTC, comprueba que apareció por sí solo un run nuevo en Activity, que el artefacto ganó una versión y que las personas que deben leerlo pueden abrirlo. La tarjeta **Routines** del dashboard muestra el último resultado de cada rutina, así que una programación que empieza a fallar se ve.

Una programación cuyo creador ya no puede ejecutar el agent se desactiva sola y registra el motivo. Consulta [los conceptos](../concepts.md#it-runs-as-a-person).

## Cuando algo sale mal { #when-it-goes-wrong }

- **Run now no hace nada.** La programación está en pausa, o el worker de segundo plano no está en marcha. El worker ejecuta cada disparo programado y cada Run now.
- **El informe no tiene artefacto.** Comprueba que **Artifacts** está activado y que las instrucciones nombran `weekly-report`. Las llamadas a herramientas del run en Activity muestran si se llamó a `publish_artifact` y qué devolvió.
- **Cada run crea un artefacto nuevo.** El nombre cambió entre runs. Mantenlo fijo en las instrucciones.
- **Un total es incorrecto o la fila mala desapareció.** Ajusta las instrucciones antes de programar nada. Una programación repite un error cada semana.

## Registra la prueba { #record-the-trial }

Conserva el mensaje, la versión del agent, el perfil de modelo, la expresión cron, cada run en Activity y cada versión del artefacto. Registra qué disparos fueron Run now y cuáles fueron programados. Una persona comprueba los totales, decide quién puede leer el artefacto y vigila el primer disparo real.
