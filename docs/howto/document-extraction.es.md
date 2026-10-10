---
source_sha: "d1faa4de619f"
title: "Extrae datos de facturas a una hoja de cálculo"
description: "Adjunta tres facturas PDF sintéticas, haz que un agent las lea en una sandbox y escriba un CSV con columnas fijas, y comprueba que la factura con un campo que falta queda señalada en lugar de rellenada."
---

# Extrae datos de facturas a una hoja de cálculo { #extract-invoice-data-into-a-spreadsheet }

Construye un agent que lee un lote de facturas y escribe un CSV con las mismas columnas en cada fila. El ejemplo son tres pequeñas facturas sintéticas, una de ellas sin fecha, así que la comprobación que importa es si el agent informa del hueco en lugar de inventarse una fecha plausible. Es un procedimiento para ejecutar, con un run registrado como referencia.

## Qué necesitas { #what-you-need }

- Una [instalación en marcha](../install.md) con un perfil de modelo y una [conexión de sandbox](../sandbox.md) registrada que ofrezca el runtime `workbench`, que incluye `liteparse` (`lit`) y `pdftotext` para leer PDF y un entorno de Python para escribir el CSV.
- Sin conocimiento y sin gráficos.

## Prepara la entrada { #prepare-the-input }

Tres facturas cortas, generadas como PDF para que el ejemplo se parezca a una subida real. Guarda este script como `make_invoices.py` en un directorio de trabajo:

```python
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

def draw_invoice(path, number, date, vendor, lines, tax_rate, include_date=True):
    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    y = height - 30 * mm
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y, "INVOICE")
    y -= 10 * mm
    c.setFont("Helvetica", 11)
    c.drawString(20 * mm, y, f"Invoice number: {number}")
    y -= 6 * mm
    if include_date:
        c.drawString(20 * mm, y, f"Date: {date}")
        y -= 6 * mm
    c.drawString(20 * mm, y, f"Vendor: {vendor}")
    y -= 6 * mm
    c.drawString(20 * mm, y, "Bill to: Meridian Analytics BV")
    y -= 12 * mm

    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, "Description")
    c.drawString(130 * mm, y, "Qty")
    c.drawString(150 * mm, y, "Amount")
    y -= 6 * mm
    c.setFont("Helvetica", 11)
    subtotal = 0.0
    for desc, qty, amount in lines:
        c.drawString(20 * mm, y, desc)
        c.drawString(130 * mm, y, str(qty))
        c.drawString(150 * mm, y, f"{amount:.2f}")
        subtotal += amount
        y -= 6 * mm
    y -= 4 * mm

    tax = round(subtotal * tax_rate, 2)
    total = round(subtotal + tax, 2)
    c.drawString(120 * mm, y, "Subtotal:")
    c.drawString(150 * mm, y, f"{subtotal:.2f} EUR")
    y -= 6 * mm
    c.drawString(120 * mm, y, f"Tax ({int(tax_rate*100)}%):")
    c.drawString(150 * mm, y, f"{tax:.2f} EUR")
    y -= 6 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(120 * mm, y, "Total:")
    c.drawString(150 * mm, y, f"{total:.2f} EUR")
    c.showPage()
    c.save()
    return subtotal, tax, total

s1 = draw_invoice("INV-1001.pdf", "INV-1001", "2027-01-15", "Nordic Office Supplies",
                   [("Desk chairs, ergonomic", 3, 420.00), ("Standing desks", 2, 260.00)], 0.21)
print("INV-1001", s1)

s2 = draw_invoice("INV-1002.pdf", "INV-1002", "2027-01-22", "Blue Ridge Logistics",
                   [("Freight, Rotterdam-Warsaw", 1, 780.00), ("Customs handling", 1, 195.00)], 0.21)
print("INV-1002", s2)

s3 = draw_invoice("INV-1003.pdf", "INV-1003", None, "Summit Cleaning Services",
                   [("Monthly office cleaning, January", 1, 227.27)], 0.21, include_date=False)
print("INV-1003", s3)
```

Después ejecútalo allí. Escribe `INV-1001.pdf`, `INV-1002.pdf` e `INV-1003.pdf` a su lado:

```bash
uv run --with reportlab python make_invoices.py
```

`make_invoices.py` dibuja cada una con `reportlab`: un número de factura, un proveedor, una tabla de conceptos, un subtotal, un 21 % de impuesto y un total. `INV-1001` e `INV-1002` están completas; `INV-1003` no tiene línea de fecha, a propósito.

Los valores de referencia con los que comprobar la extracción:

| Factura | Fecha | Proveedor | Subtotal | Impuesto | Total |
| --- | --- | --- | --- | --- | --- |
| INV-1001 | 2027-01-15 | Nordic Office Supplies | 680.00 | 142.80 | 822.80 |
| INV-1002 | 2027-01-22 | Blue Ridge Logistics | 975.00 | 204.75 | 1179.75 |
| INV-1003 | *(falta)* | Summit Cleaning Services | 227.27 | 47.73 | 275.00 |

Cada total es el subtotal más un 21 % de impuesto, así que un total erróneo se puede comprobar a mano.

## Construye el agent { #build-the-agent }

1. Crea un agent en **Agents → New agent** y selecciona tu perfil de modelo.
2. En **Toolbox**, activa **Sandbox**. Elige **Container**, selecciona tu conexión de sandbox y el runtime `workbench`.
3. Fija un budget y un límite de pasos: leer tres PDF cortos y escribir un CSV son unas pocas llamadas a herramientas.
4. Escribe las instrucciones de abajo y luego pulsa **Publish**.

```text
You extract structured data from attached invoices.
Read each invoice from the workspace before extracting anything - use lit
or pdftotext to get its text; do not guess from the filename.
Write invoices.csv in the workspace with exactly these columns: invoice_number,
date, vendor, subtotal, tax, total, currency.
If a field is not present on an invoice, leave that cell empty and name the
invoice and the missing field in your reply. Never invent a value that is
not on the document.
Check that subtotal plus tax equals total for each invoice, and say so if one
does not.
```

## Ejecútalo { #run-it }

Adjunta `INV-1001.pdf`, `INV-1002.pdf` e `INV-1003.pdf` a una conversación nueva y envía:

```text
Extract the invoice data from these three files into invoices.csv, with one row per invoice.
```

Leer el texto de un PDF en el runtime `workbench` ejecuta `lit` o `pdftotext` mediante `execute`, que pide aprobación igual que un comando de shell en [Convierte un CSV en un gráfico que puedas comprobar](csv-chart.md#run-it). Lee el comando y pulsa **Approve**; escribir el CSV no necesita aprobación. El agent puede quedar aparcado en `execute` más de una vez en el mismo turno: una forma posible es un primer intento que escribe la salida de `lit` en un archivo fuera del workspace y un segundo que la imprime directamente en la salida del comando. Consulta el run registrado de abajo.

## Comprueba el resultado { #check-the-result }

| Comprobación | Referencia |
| --- | --- |
| Filas de `invoices.csv` | Tres, una por factura, con las mismas siete columnas en el mismo orden |
| INV-1001 e INV-1002 | Cada campo coincide exactamente con la tabla de referencia |
| La celda de fecha de INV-1003 | Vacía, no una fecha supuesta o inventada |
| La respuesta | Nombra `INV-1003` y "date" como ausentes, en lugar de limitarse a dejar la celda en blanco |
| Totales | En cada fila, el subtotal más el impuesto es igual al total; el agent lo dice si lo comprobó y alguno no cuadra |
| Un cuarto archivo que no es una factura | El agent dice que no pudo extraer campos de factura de él, en lugar de inventarse una fila |

Abre `invoices.csv` desde el workspace y compruébalo directamente: una respuesta que da los números correctos en prosa mientras el archivo contiene otra cosa es un hueco que solo muestra el propio archivo.

!!! example "Registrado en v0.0.504, 25 de septiembre de 2026"

    Modelo: Claude Sonnet 4.6 a través de OpenRouter, runtime `workbench`. La primera llamada a `execute` del agent ejecutó `lit parse <file> -o /tmp/inv*.md` para los tres PDF y luego intentó `read_file` sobre `/tmp/inv1001.md` y los otros dos. Los tres fallaron, porque `/tmp` está fuera del workspace al que llega `read_file`, aunque `execute` sí puede escribir allí. El agent se recuperó solo: una segunda llamada a `execute` volvió a ejecutar `lit parse` para los tres archivos sin `-o`, imprimiendo directamente en la salida del comando, que después leyó del resultado de la herramienta. Las dos llamadas a `execute` necesitaron aprobaciones separadas en el mismo turno.

    `invoices.csv` salió con las tres filas y las columnas de referencia, todos los campos de INV-1001 e INV-1002 coincidiendo exactamente con los PDF de origen y la celda `date` de INV-1003 vacía. La respuesta nombró "`INV-1003` — `date`" como el campo que faltaba. Antes de terminar, el agent comprobó la aritmética por su cuenta con un `execute` puntual: `python3 -c "..."` releyó el CSV y comparó subtotal más impuesto con el total, e informó de que las tres filas cuadraban. Coste total del run: 0,1302 USD, con 37.246 tokens de entrada y 1.233 de salida.

## Cuando algo sale mal { #when-it-goes-wrong }

- **El agent se inventa una fecha para INV-1003.** Las instrucciones dicen que deje la celda vacía y nombre el hueco; si aun así la rellena, añade "do not infer a date from context" y vuelve a probar con el mismo archivo.
- **El run se detiene después de leer los archivos.** Está aparcado en la aprobación de `execute` para `lit` o `pdftotext`. Abre el chat o **Approvals** en **Activity**. Puede aparcarse dos veces en el mismo turno; consulta el run registrado arriba.
- **`read_file` falla en una ruta que `lit` acaba de escribir.** `execute` puede escribir en cualquier parte del contenedor, incluso fuera de `/workspace`, pero `read_file` está limitado al workspace. Haz que el agent imprima el resultado directamente en la salida del comando, o que escriba el archivo `-o` de `lit` dentro del workspace y no en `/tmp`.
- **Un total difiere en el importe del impuesto.** Comprueba si el agent leyó el total impreso en la factura o lo recalculó. Un ejemplo tan pequeño nunca debería necesitar recalcular nada, y una discrepancia suele indicar un concepto mal leído.
- **El CSV tiene columnas distintas cada vez.** Las instrucciones las nombran con exactitud; si el modelo sigue cambiando el orden o añadiendo una columna, pásalas como una línea de cabecera literal en lugar de en prosa.
- **Un PDF con una página escaneada se lee vacío.** `lit` solo aplica OCR a una página sin capa de texto, y un escaneo cuesta varios segundos por página. Consulta [qué hay en el runtime y qué no, a propósito](../sandbox.md#what-is-in-it-and-what-is-deliberately-not) antes de apuntar este agent a facturas escaneadas en lugar de generadas.

## Registra la prueba { #record-the-trial }

Guarda los tres PDF de origen, el prompt exacto, la versión del agent, las llamadas a `execute` aprobadas en Activity y el `invoices.csv` resultante, no solo la respuesta del chat. Una persona sigue comprobando el aviso del campo que falta frente al PDF de origen y decide qué hacer con el hueco: el trabajo del agent es sacarlo a la luz, no resolverlo.

## Siguientes pasos { #next-steps }

Cuando esto funcione con un lote de tres, añade una cuarta factura en otra moneda o con otro diseño, una dificultad cada vez, como sugiere [Convierte un CSV en un gráfico que puedas comprobar](csv-chart.md) para su propio ejemplo.
