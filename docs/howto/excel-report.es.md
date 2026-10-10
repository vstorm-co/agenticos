---
source_sha: "46ef69419b31"
title: "Construye un informe de Excel y una presentación a partir de datos"
description: "Adjunta un pequeño CSV sintético y haz que un agent en una sandbox produzca un libro con fórmulas y un gráfico, más una presentación de tres diapositivas; después abre ambos y comprueba los números."
---

# Construye un informe de Excel y una presentación a partir de datos { #build-an-excel-report-and-a-slide-deck-from-data }

Dale a un agent una sandbox y un pequeño CSV de ventas, y haz que construya un libro con una hoja de resumen basada en fórmulas y un gráfico, y luego una presentación de tres diapositivas con los mismos números. El ejemplo es lo bastante pequeño para sumarlo a mano, así que puedes comprobar cada celda frente a las filas de origen. Es un procedimiento para ejecutar, con un run registrado como referencia. Si solo necesitas un informe, empieza por [convierte un CSV en un gráfico que puedas comprobar](csv-chart.md); esta página añade un libro completo y una presentación sobre ese patrón.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo y una [conexión de sandbox](../sandbox.md) registrada cuyo runtime por defecto sea `workbench`, que incluye `openpyxl` y `python-pptx`, así que no hace falta instalar ningún paquete.
- El CSV sintético de abajo, lo bastante pequeño para comprobarlo a mano.

## Prepara la entrada { #prepare-the-input }

Guarda esto como `sales.csv`. Cuatro trimestres, cuatro regiones, dieciséis filas.

```csv
quarter,region,revenue_usd,units
Q1,North,12000,300
Q1,South,9000,250
Q1,East,15000,320
Q1,West,8000,200
Q2,North,13000,310
Q2,South,9500,260
Q2,East,16000,330
Q2,West,8500,210
Q3,North,14000,320
Q3,South,10000,270
Q3,East,17000,340
Q3,West,9000,220
Q4,North,15000,330
Q4,South,10500,280
Q4,East,18000,350
Q4,West,9500,230
```

Totales de referencia, calculados a mano: por región North 54.000, South 39.000, East 66.000, West 35.000; por trimestre Q1 44.000, Q2 47.000, Q3 50.000, Q4 53.000; total general 194.000.

## Construye el agent { #build-the-agent }

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
2. En **Toolbox**, activa **Sandbox**. Elige **Container**, selecciona tu conexión de sandbox y el runtime `workbench`, y mantén el alcance de conversación.
3. Fija un budget para la prueba, escribe las instrucciones de abajo y pulsa **Publish**.

```text
You build spreadsheets and slide decks in your workspace from data the user
attaches.
Read the attached file before calculating anything.
Use openpyxl to build the workbook and python-pptx to build the deck.
Save every output file in the workspace and give its path.
Do not fetch data from the internet.
```

## Ejecútalo { #run-it }

Abre un chat nuevo con el agent, adjunta `sales.csv` y envía:

```text
Using the attached CSV, build report.xlsx with a summary sheet totalling
revenue by region and by quarter (use SUM formulas over a raw-data sheet, not
hand-typed numbers) plus a bar chart of revenue by region. Then build a
3-slide summary.pptx: a title slide, a slide with the totals table, and a
slide with the chart or its key numbers. Save both files in the workspace.
```

Cuando el agent ejecuta su script, el chat muestra **Tool approval required**. Lee el comando y pulsa **Approve**. Consulta [las aprobaciones](../governance.md#approvals).

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| Totales por región | North 54.000, South 39.000, East 66.000, West 35.000 |
| Totales por trimestre | Q1 44.000, Q2 47.000, Q3 50.000, Q4 53.000 |
| Total general | 194.000 |
| La hoja de resumen usa fórmulas | Pulsa una celda de total y ves `=SUM(...)`, no un número escrito |
| Gráfico | Barras por región, eje etiquetado con la moneda |
| Presentación | Tres diapositivas: título, tabla de totales, gráfico o cifras clave |
| Los números coinciden entre el libro y la presentación | Los totales de la presentación son iguales a los del libro, no redondeados por separado |

Abre `report.xlsx` y `summary.pptx` desde el panel de archivos del chat y compruébalos tú mismo: una ruta en una respuesta no demuestra que el archivo exista ni que sus fórmulas calculen el número correcto.

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter. El agent leyó el CSV, escribió un script de construcción de 460 líneas y lo ejecutó: una llamada a `execute`, aprobada. Después hizo tres llamadas más a `execute` para convertir la presentación con LibreOffice en PNG por diapositiva y así revisar su propio trabajo, cada una aprobada por turno.

    `report.xlsx` contenía una hoja `Raw Data` con las 16 filas y una hoja `Summary` en la que cada celda regional y trimestral era una fórmula `SUMPRODUCT` activa sobre `Raw Data`, con totales de fila y columna mediante `SUM` y un gráfico de barras agrupadas, sin ningún número escrito a mano. Evaluar esas fórmulas con los datos de origen da North 54.000, South 39.000, East 66.000, West 35.000, y 44.000/47.000/50.000/53.000 por trimestre, 194.000 en total: exactamente los totales de referencia.

    `summary.pptx` tenía tres diapositivas: una de título con el total general, una tabla completa de regiones por trimestre que coincidía con el libro celda a celda, y una de gráfico y KPI que repetía los cuatro totales por región. Coste: 0,37 USD en cuatro rondas de aprobación.

## Cuando algo sale mal { #when-it-goes-wrong }

- **El agent dice que no tiene shell.** La capability usa **Files** en lugar de **Container**. Cambia a Container y elige el runtime `workbench`.
- **Un total es un número escrito, no una fórmula.** Pídele que reconstruya la hoja de resumen con fórmulas `SUM` o `SUMPRODUCT` que referencien la hoja de datos; un número escrito a mano no se actualiza si cambia una fila.
- **El workspace rechaza por un momento cada escritura.** Pasó una vez durante la verificación, cuando el host de la sandbox perdió el permiso sobre el socket de Docker: cada `write_file` falló y el agent recurrió a mostrar el script como texto en lugar de ejecutarlo. `agenticos cmd doctor` y el estado de la conexión en **Sandboxes** muestran si el servicio puede iniciar realmente una sesión.
- **Los números de la presentación no coinciden con el libro.** Puede que el agent escribiera a mano los totales de la presentación por separado; pídele que calcule los números de la presentación a partir de los mismos valores que producen las fórmulas del libro.
- **El primer turno es lento.** Se está construyendo la imagen `workbench`; las sesiones posteriores la reutilizan.

## Registra la prueba { #record-the-trial }

Guarda el CSV, el prompt, la versión del agent, el run en Activity y los dos archivos de salida. Abre las fórmulas del libro, no solo los números que muestra, antes de fiarte de un total.

Una persona comprueba que las fórmulas son fórmulas de verdad, que el eje del gráfico significa lo que dice y que la presentación es algo que realmente entregaría a otra persona. El agent te da los archivos; no sustituye abrirlos.

## Siguientes pasos { #next-steps }

Para un informe que tiene que ejecutarse cada semana y no una sola vez, continúa con [programa un informe semanal](scheduled-report.md), que publica su resultado como un artefacto estable y compartible en lugar de un archivo del workspace.
