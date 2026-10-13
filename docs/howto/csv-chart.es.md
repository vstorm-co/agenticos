---
source_sha: "1176d12d1a25"
title: "Convierte un CSV en un gráfico que puedas comprobar"
description: "Adjunta un pequeño archivo sintético de ventas, deja que el agent lo calcule y lo represente en una sandbox, y cuadra cada número con las filas de origen."
---

# Convierte un CSV en un gráfico que puedas comprobar { #turn-a-csv-into-a-chart-you-can-check }

Dale a un agent un pequeño archivo de ventas y pídele los totales mensuales, un gráfico y el script que los produjo. El fixture es lo bastante pequeño para sumarlo a mano, así que cada número que dé el agent se puede comprobar frente a las filas de origen. Es un procedimiento que ejecutar, con un run registrado como referencia. No mide la precisión con tus propios datos.

## Prepara la entrada { #prepare-the-input }

Usa una [instalación en marcha](../install.md) con un perfil de modelo. Guarda esto como `sales.csv`:

```csv
month,product,revenue_eur
2026-01,A,120
2026-01,B,80
2026-02,A,150
2026-02,B,100
2026-03,A,90
2026-03,B,110
```

Las cifras son inventadas. Los totales de referencia son 200 EUR para enero, 250 para febrero y 200 para marzo, 650 en total, a partir de seis filas de datos.

## Comprueba la sandbox { #check-the-sandbox }

El agent lee el archivo y ejecuta su script en un contenedor. Para eso hacen falta el servicio de sandbox y una conexión registrada:

- `make dev` y el perfil `sandbox` de Docker Compose arrancan el servicio. Consulta [la instalación](../install.md).
- **Sandboxes → Add connection** la registra para la organización. La conexión ofrece el runtime `workbench`, que incluye `pandas` y `matplotlib`. Consulta [la sandbox](../sandbox.md#which-environments-an-agent-may-ask-for).
- `agenticos cmd doctor` indica si cada conexión registrada responde con un runtime.

La primera sesión construye la imagen `workbench`, de unos 2 GB. Cuenta con un minuto o dos para el primer turno en un host nuevo.

## Construye el agent { #build-the-agent }

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
2. En **Toolbox**, activa **Files & shell**. Elige **Container**, no **Files**: el workspace de Files no tiene shell, así que el agent no puede ejecutar un script. Selecciona la conexión y el runtime `workbench`, y mantén el ámbito de conversación.
3. Activa **Charts**. Dibuja números que el agent ya tiene, así que el gráfico muestra lo que calculó el script.
4. Define un budget y un límite de pasos para la prueba. El run registrado usó 25 pasos y costó unos 0,11 USD.
5. Pon las instrucciones de abajo y pulsa **Publish**.

```text
You analyse CSV files the user attaches.
Read the file from the workspace before calculating anything.
Show the totals as a table and state the number of rows you read.
Draw charts with create_chart from numbers you computed.
Save any code and output files in the workspace and give their paths.
Do not fetch data from the internet.
```

## Ejecútalo { #run-it }

Abre un chat nuevo con el agent, adjunta `sales.csv` y envía:

```text
Sum revenue_eur by month. Return the totals as a table, draw a bar chart of them, and save the calculation script and a PNG of the chart in the workspace.
```

El adjunto se escribe en el workspace, dentro de `uploads/`, y el mensaje le dice al agent dónde. [Procesamiento de archivos](../file-processing.md) describe el enrutamiento.

Cuando el agent quiere ejecutar su script, el chat muestra **Tool approval required**. Ejecutar un comando de shell es un efecto secundario, así que por defecto lo aprueba una persona. Lee el comando y pulsa **Approve**. El run continúa desde donde se detuvo. Para saltarte este paso con un agent de prueba de confianza, cambia el ajuste de aprobación de `execute` en el Builder. Consulta [las aprobaciones](../governance.md#approvals).

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| Totales mensuales en la respuesta, en la salida del script y en el gráfico | 200, 250 y 200 EUR, en orden de mes |
| Total general | 650 EUR |
| Filas leídas | 6 |
| Gráfico | Las barras empiezan en cero y el eje indica la unidad |
| Workspace | El script y el PNG existen y se abren |
| El mismo mensaje sin archivo adjunto | El agent dice que falta el archivo y no inventa datos |

Compara cada número con las filas de origen, no con el resumen de la propia respuesta. Después abre el workspace desde el panel de archivos del chat. Abre el propio PNG y lee el script. Una ruta en una respuesta no prueba que el archivo exista.

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter. El agent llamó a `read_file` sobre el adjunto, a `write_file` para `analysis/revenue_by_month.py` y después a `execute`, que quedó aparcado a la espera de aprobación. Tras la aprobación, el script imprimió los tres totales, `Total rows read : 6` y `Grand total (€) : 650`. `create_chart` dibujó 200, 250 y 200. El workspace contenía el script y un PNG de 1050×600. Coste: 0,115 USD.

    La respuesta final dio los totales en prosa y enumeró los archivos guardados, pero no repitió la tabla ni el número de filas. Esos datos estaban en la salida del script. Sin archivo, el agent listó un workspace vacío y pidió el CSV.

## Cuando algo sale mal { #when-it-goes-wrong }

- **El agent dice que no tiene shell.** La capability usa **Files** en lugar de **Container**.
- **El primer turno tarda mucho.** Se está construyendo la imagen `workbench`. Las sesiones posteriores la reutilizan.
- **El run se detiene después de que el agent escribe su script.** Está esperando la aprobación de `execute`. Abre el chat, o la pestaña **Approvals** en **Activity**.
- **Un error de conexión menciona la sandbox.** Ejecuta `agenticos cmd doctor` y después revisa la conexión en **Sandboxes**.
- **Un total es incorrecto.** Lee el script antes de cambiar el prompt. Un error de cálculo y un runtime ausente son problemas distintos, y los resultados de las herramientas en Activity muestran cuál ocurrió.

## Registra la prueba { #record-the-trial }

Conserva el CSV exacto, el prompt, la versión del agent, el perfil de modelo, el run en Activity, el script y el PNG. Conserva también los runs fallidos. Si publicas el resultado, di que los datos son sintéticos y muestra lo suficiente de la tabla para comprobar el gráfico.

Una persona aprueba el comando, compara los totales con la fuente y abre los archivos. El agent no sustituye esa comprobación. Te da todo lo que necesitas para hacerla rápido.

Cuando esto funcione, añade una dificultad cada vez: un valor que falta, un mes repetido o una segunda moneda. Cada una muestra cómo trata el agent unos datos que no cuadran limpiamente. Para repetir el informe según una programación, continúa con [programa un informe semanal](scheduled-report.md).
