---
source_sha: "d1faa4de619f"
title: "Rechnungsdaten in eine Tabelle extrahieren"
description: "Hängen Sie drei synthetische PDF-Rechnungen an, lassen Sie einen Agent sie in einer Sandbox lesen und eine CSV mit festen Spalten schreiben, und prüfen Sie, dass die Rechnung mit einem fehlenden Feld markiert statt ausgefüllt wird."
---

# Rechnungsdaten in eine Tabelle extrahieren { #extract-invoice-data-into-a-spreadsheet }

Bauen Sie einen Agent, der einen Stapel Rechnungen liest und eine CSV mit denselben Spalten für jede Zeile schreibt. Das Beispiel sind drei kleine synthetische Rechnungen, von denen einer das Datum fehlt. Entscheidend ist also, ob der Agent die Lücke meldet, statt ein plausibel aussehendes Datum zu erfinden. Dies ist eine Anleitung zum Ausführen, mit einem festgehaltenen Run als Referenz.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil und einer registrierten [Sandbox-Verbindung](../sandbox.md) mit der Runtime `workbench`. Sie enthält `liteparse` (`lit`) und `pdftotext` zum Lesen von PDFs sowie eine Python-Umgebung zum Schreiben der CSV.
- Kein Wissen, keine Diagramme.

## Die Eingabe vorbereiten { #prepare-the-input }

Drei kurze Rechnungen, als PDFs erzeugt, damit das Beispiel wie ein echter Upload aussieht. Speichern Sie dieses Skript als `make_invoices.py` in einem Arbeitsverzeichnis:

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

Führen Sie es dann dort aus. Es schreibt `INV-1001.pdf`, `INV-1002.pdf` und `INV-1003.pdf` neben sich:

```bash
uv run --with reportlab python make_invoices.py
```

`make_invoices.py` zeichnet jede Rechnung mit `reportlab`: eine Rechnungsnummer, einen Lieferanten, eine Positionstabelle, eine Zwischensumme, 21 % Steuer und eine Gesamtsumme. `INV-1001` und `INV-1002` sind vollständig, `INV-1003` hat absichtlich gar keine Datumszeile.

Die Referenzwerte, gegen die Sie die Extraktion prüfen:

| Rechnung | Datum | Lieferant | Zwischensumme | Steuer | Gesamt |
| --- | --- | --- | --- | --- | --- |
| INV-1001 | 2027-01-15 | Nordic Office Supplies | 680.00 | 142.80 | 822.80 |
| INV-1002 | 2027-01-22 | Blue Ridge Logistics | 975.00 | 204.75 | 1179.75 |
| INV-1003 | *(fehlt)* | Summit Cleaning Services | 227.27 | 47.73 | 275.00 |

Jede Gesamtsumme ist Zwischensumme plus 21 % Steuer, sodass sich eine falsche Summe von Hand prüfen lässt.

## Den Agent bauen { #build-the-agent }

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
2. Aktivieren Sie in der **Toolbox** **Sandbox**. Wählen Sie **Container**, Ihre Sandbox-Verbindung und die Runtime `workbench`.
3. Legen Sie Budget und Schrittlimit fest. Drei kurze PDFs lesen und eine CSV schreiben sind eine Handvoll Tool-Aufrufe.
4. Setzen Sie die Instruktionen unten und klicken Sie dann auf **Publish**.

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

## Ausführen { #run-it }

Hängen Sie `INV-1001.pdf`, `INV-1002.pdf` und `INV-1003.pdf` an eine neue Konversation an und senden Sie:

```text
Extract the invoice data from these three files into invoices.csv, with one row per invoice.
```

Den Text eines PDFs auf der Runtime `workbench` zu lesen, führt `lit` oder `pdftotext` über `execute` aus, das genauso um Genehmigung bittet wie ein Shell-Befehl in [Eine CSV in ein prüfbares Diagramm umwandeln](csv-chart.md#run-it). Lesen Sie den Befehl und klicken Sie dann auf **Approve**. Das Schreiben der CSV selbst braucht keine Genehmigung. Der Agent kann in derselben Runde mehr als einmal bei `execute` parken. Eine mögliche Form: ein erster Versuch, der die Ausgabe von `lit` in eine Datei außerhalb des Workspaces schreibt, und ein zweiter, der sie direkt in die Ausgabe des Befehls druckt. Siehe den festgehaltenen Run unten.

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Zeilen in `invoices.csv` | Drei, eine pro Rechnung, dieselben sieben Spalten in derselben Reihenfolge |
| INV-1001 und INV-1002 | Jedes Feld stimmt genau mit der Referenztabelle überein |
| Die Datumszelle von INV-1003 | Leer, kein geratenes oder erfundenes Datum |
| Die Antwort | Nennt `INV-1003` und "date" als fehlend, statt nur die Zelle leer zu lassen |
| Summen | Zwischensumme plus Steuer ergibt in jeder Zeile die Gesamtsumme. Der Agent sagt es, wenn er geprüft hat und eine nicht stimmt |
| Eine vierte Datei, die gar keine Rechnung ist | Der Agent sagt, dass er daraus keine Rechnungsfelder extrahieren konnte, statt eine Zeile zu erfinden |

Öffnen Sie `invoices.csv` aus dem Workspace und prüfen Sie die Datei direkt. Eine Antwort, die in Prosa die richtigen Zahlen nennt, während die Datei etwas anderes enthält, ist eine Lücke, die nur die Datei selbst zeigt.

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter, Runtime `workbench`. Der erste `execute`-Aufruf des Agents führte `lit parse <file> -o /tmp/inv*.md` für alle drei PDFs aus und versuchte dann `read_file` auf `/tmp/inv1001.md` und die anderen beiden. Alle drei schlugen fehl, weil `/tmp` außerhalb des Workspaces liegt, den `read_file` erreichen kann, obwohl `execute` selbst dort schreiben kann. Der Agent half sich selbst: Ein zweiter `execute`-Aufruf führte `lit parse` für alle drei Dateien ohne `-o` erneut aus, druckte direkt in die Ausgabe des Befehls und las diese direkt aus dem Tool-Ergebnis. Beide `execute`-Aufrufe brauchten in derselben Runde getrennte Genehmigungen.

    `invoices.csv` enthielt alle drei Zeilen und die Referenzspalten. Jedes Feld von INV-1001 und INV-1002 stimmte genau mit den Quell-PDFs überein, und die Zelle `date` von INV-1003 war leer. Die Antwort nannte "`INV-1003` — `date`" als fehlendes Feld. Vor dem Abschluss prüfte der Agent die Arithmetik selbst mit einem einmaligen `execute`: `python3 -c "..."` las die CSV zurück und verglich Zwischensumme plus Steuer mit der Gesamtsumme. Er meldete alle drei Zeilen als stimmig. Gesamtkosten des Runs: 0,1302 USD bei 37.246 Eingabe- und 1.233 Ausgabe-Tokens.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Der Agent rät ein Datum für INV-1003.** Die Instruktionen sagen, die Zelle leer zu lassen und die Lücke zu nennen. Wenn er trotzdem eines einträgt, ergänzen Sie "do not infer a date from context" und testen Sie erneut mit derselben Datei.
- **Der Run hält nach dem Lesen der Dateien an.** Er wartet auf die `execute`-Genehmigung für `lit` oder `pdftotext`. Öffnen Sie den Chat oder **Approvals** unter **Activity**. Er kann in derselben Runde zweimal parken; siehe den festgehaltenen Run oben.
- **`read_file` schlägt bei einem Pfad fehl, den `lit` gerade geschrieben hat.** `execute` kann überall im Container schreiben, auch außerhalb von `/workspace`, aber `read_file` ist auf den Workspace beschränkt. Lassen Sie den Agent direkt in die Ausgabe des Befehls parsen oder die `-o`-Datei von `lit` im Workspace schreiben, nicht in `/tmp`.
- **Eine Summe weicht um den Steuerbetrag ab.** Prüfen Sie, ob der Agent die auf der Rechnung gedruckte Summe gelesen oder selbst eine berechnet hat. Ein so kleines Beispiel sollte nie eine Neuberechnung brauchen, und eine Abweichung bedeutet meist eine falsch gelesene Position.
- **Die CSV hat jedes Mal andere Spalten.** Die Instruktionen nennen sie genau. Wenn das Modell die Reihenfolge trotzdem ändert oder eine Spalte hinzufügt, geben Sie sie als wörtliche Kopfzeile statt in Prosa an.
- **Ein PDF mit einer gescannten Seite liest sich leer.** `lit` führt OCR nur für eine Seite ohne Textebene aus, und ein Scan kostet mehrere Sekunden pro Seite. Lesen Sie [was in der Runtime ist und was bewusst nicht](../sandbox.md#what-is-in-it-and-what-is-deliberately-not), bevor Sie diesen Agent auf gescannte statt erzeugte Rechnungen ansetzen.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie die drei Quell-PDFs, den genauen Prompt, die Agent-Version, die genehmigten `execute`-Aufrufe aus Activity und die resultierende `invoices.csv` auf, nicht nur die Chat-Antwort. Ein Mensch prüft die Meldung zum fehlenden Feld weiterhin gegen das Quell-PDF und entscheidet, was mit der Lücke geschieht. Aufgabe des Agents ist es, sie sichtbar zu machen, nicht, sie zu schließen.

## Nächste Schritte { #next-steps }

Sobald das bei einem Stapel von drei Rechnungen hält, fügen Sie eine vierte in einer anderen Währung oder mit anderem Layout hinzu, eine Schwierigkeit nach der anderen, so wie es [Eine CSV in ein prüfbares Diagramm umwandeln](csv-chart.md) für sein eigenes Beispiel vorschlägt.
