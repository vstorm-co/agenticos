---
source_sha: "4f6ac46ddef7"
title: "Einen Excel-Bericht und ein Deck aus Daten bauen"
description: "Hängen Sie eine kleine synthetische CSV an und lassen Sie einen Agent in einer Sandbox eine Arbeitsmappe mit Formeln und einem Diagramm sowie ein dreiteiliges Deck erzeugen, dann öffnen Sie beides und prüfen Sie die Zahlen."
---

# Einen Excel-Bericht und ein Deck aus Daten bauen { #build-an-excel-report-and-a-slide-deck-from-data }

Geben Sie einem Agent eine Sandbox und eine kleine Verkaufs-CSV, und lassen Sie ihn eine Arbeitsmappe mit einem formelgesteuerten Zusammenfassungsblatt und einem Diagramm bauen, dann ein dreiteiliges Deck, das dieselben Zahlen abdeckt. Die Testdatei ist klein genug, um sie von Hand zu summieren, sodass Sie jede Zelle mit den Quellzeilen abgleichen können. Dies ist eine Anleitung zum Durchführen, mit einem festgehaltenen Run als Referenz. Wenn Ihnen ein Bericht allein genügt, beginnen Sie stattdessen mit [eine CSV in ein prüfbares Diagramm umwandeln](csv-chart.md) - diese Seite fügt diesem Muster eine vollständige Arbeitsmappe und ein Deck hinzu.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil und einer registrierten [Sandbox-Verbindung](../sandbox.md), deren Standard-Runtime `workbench` ist - sie führt `openpyxl` und `python-pptx` mit, sodass kein Installationsschritt für Pakete nötig ist.
- Die synthetische CSV unten, klein genug, um sie von Hand zu prüfen.

## Die Eingabe vorbereiten { #prepare-the-input }

Speichern Sie dies als `sales.csv`. Vier Quartale, vier Regionen, sechzehn Zeilen.

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

Referenzsummen, von Hand berechnet: North 54.000, South 39.000, East 66.000, West 35.000 nach Region; Q1 44.000, Q2 47.000, Q3 50.000, Q4 53.000 nach Quartal; Gesamtsumme 194.000.

## Den Agent bauen { #build-the-agent }

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
2. Aktivieren Sie unter **Toolbox** **Sandbox**. Wählen Sie **Container**, wählen Sie Ihre Sandbox-Verbindung und die Runtime `workbench`, und behalten Sie den Konversations-Scope bei.
3. Setzen Sie ein Budget für den Versuch, setzen Sie dann die folgenden Instruktionen und **Publish**.

```text
You build spreadsheets and slide decks in your workspace from data the user
attaches.
Read the attached file before calculating anything.
Use openpyxl to build the workbook and python-pptx to build the deck.
Save every output file in the workspace and give its path.
Do not fetch data from the internet.
```

## Ausführen { #run-it }

Öffnen Sie einen neuen Chat mit dem Agent, hängen Sie `sales.csv` an und senden Sie:

```text
Using the attached CSV, build report.xlsx with a summary sheet totalling
revenue by region and by quarter (use SUM formulas over a raw-data sheet, not
hand-typed numbers) plus a bar chart of revenue by region. Then build a
3-slide summary.pptx: a title slide, a slide with the totals table, and a
slide with the chart or its key numbers. Save both files in the workspace.
```

Wenn der Agent sein Skript ausführt, zeigt der Chat **Tool approval required**. Lesen Sie den Befehl, dann **Approve**. Siehe [Genehmigungen](../governance.md#approvals).

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Regionssummen | North 54.000, South 39.000, East 66.000, West 35.000 |
| Quartalssummen | Q1 44.000, Q2 47.000, Q3 50.000, Q4 53.000 |
| Gesamtsumme | 194.000 |
| Das Zusammenfassungsblatt verwendet Formeln | Klicken Sie auf eine Summenzelle und sehen Sie `=SUM(...)`, keine eingetippte Zahl |
| Diagramm | Balken pro Region, Achse mit der Währung beschriftet |
| Deck | Drei Folien: Titel, Summentabelle, Diagramm oder Kennzahlen |
| Zahlen stimmen zwischen Arbeitsmappe und Deck überein | Die Summen des Decks entsprechen denen der Arbeitsmappe, nicht unabhängig gerundet |

Öffnen Sie `report.xlsx` und `summary.pptx` über das Dateipanel des Chats und prüfen Sie sie selbst - ein Pfad in einer Antwort beweist nicht, dass die Datei existiert oder dass ihre Formeln die richtige Zahl berechnen.

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter. Der Agent las die CSV, schrieb ein 460-zeiliges Build-Skript und führte es aus - ein `execute`-Aufruf, genehmigt. Dann machte er drei weitere `execute`-Aufrufe, um das Deck über LibreOffice in PNGs pro Folie umzuwandeln, damit er sein eigenes Werk ansehen konnte, jeder einzeln genehmigt.

    `report.xlsx` enthielt ein Blatt `Raw Data` mit allen 16 Zeilen und ein Blatt `Summary`, dessen jede regionale und quartalsweise Zelle eine lebendige `SUMPRODUCT`-Formel gegen `Raw Data` war, mit `SUM`-Zeilen- und Spaltensummen und einem gruppierten Balkendiagramm - nirgends eine eingetippte Zahl. Diese Formeln gegen die Rohdaten ausgewertet ergeben North 54.000, South 39.000, East 66.000, West 35.000, und 44.000/47.000/50.000/53.000 nach Quartal, insgesamt 194.000 - genau die Referenzsummen.

    `summary.pptx` enthielt drei Folien: eine Titelfolie mit der Gesamtsumme, eine vollständige Region-nach-Quartal-Tabelle, die zellgenau der Arbeitsmappe entsprach, und eine Diagramm-und-Kennzahlen-Folie, die die vier Regionssummen wiederholte. Kosten: 0,37 USD über vier Genehmigungs-Runden.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Der Agent sagt, er habe keine Shell.** Die Capability verwendet **Files** statt **Container** - wechseln Sie zu Container und wählen Sie die Runtime `workbench`.
- **Eine Summe ist eine eingetippte Zahl, keine Formel.** Bitten Sie ihn, das Zusammenfassungsblatt mit `SUM`- oder `SUMPRODUCT`-Formeln neu zu bauen, die auf das Rohdatenblatt verweisen; eine eingetippte Zahl aktualisiert sich nicht, wenn sich eine Zeile ändert.
- **Der Workspace verweigert kurzzeitig jedes Schreiben.** Das ist einmal während der Verifikation passiert, als der zugrunde liegende Sandbox-Host die Berechtigung für den Docker-Socket verloren hatte; jedes `write_file` schlug fehl, und der Agent wich darauf aus, das Skript als Text auszugeben, statt es auszuführen. `agenticos cmd doctor` und der Status der Verbindung unter **Sandboxes** zeigen, ob der Dienst tatsächlich eine Session starten kann.
- **Die Zahlen im Deck stimmen nicht mit der Arbeitsmappe überein.** Der Agent hat die Summen im Deck möglicherweise separat eingetippt; bitten Sie ihn, die Zahlen des Decks aus denselben Werten zu berechnen, die die Formeln der Arbeitsmappe liefern.
- **Der erste Turn ist langsam.** Das Image `workbench` wird gebaut; spätere Sessions verwenden es wieder.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie die CSV, den Prompt, die Agent-Version, den Run in Activity und beide Ausgabedateien auf. Öffnen Sie die Formeln der Arbeitsmappe, nicht nur ihre angezeigten Zahlen, bevor Sie einer Summe vertrauen.

Eine Person prüft, dass die Formeln echte Formeln sind, dass die Achse des Diagramms das bedeutet, was sie sagt, und dass das Deck etwas ist, das sie tatsächlich jemand anderem geben würde. Der Agent gibt Ihnen die Dateien; er ersetzt nicht, sie zu öffnen.

## Nächste Schritte { #next-steps }

Für einen Bericht, der jede Woche statt einmal laufen muss, fahren Sie fort mit [einen Wochenbericht planen](scheduled-report.md), das seine Ausgabe als stabile, teilbare App statt als Workspace-Datei veröffentlicht.
