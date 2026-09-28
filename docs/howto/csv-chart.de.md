---
source_sha: "1176d12d1a25"
title: "Eine CSV in ein prüfbares Diagramm umwandeln"
description: "Hängen Sie eine kleine synthetische Verkaufsdatei an, lassen Sie den Agent sie in einer Sandbox berechnen und plotten, und gleichen Sie jede Zahl mit den Quellzeilen ab."
---

# Eine CSV in ein prüfbares Diagramm umwandeln { #turn-a-csv-into-a-chart-you-can-check }

Geben Sie einem Agent eine kleine Verkaufsdatei und bitten Sie um Monatssummen, ein Diagramm und das Skript, das beides erzeugt hat. Die Testdatei ist klein genug, um sie von Hand zu addieren, sodass sich jede Zahl, die der Agent meldet, mit den Quellzeilen abgleichen lässt. Dies ist eine Anleitung zum Durchführen, mit einem festgehaltenen Run als Referenz. Sie misst nicht die Genauigkeit auf Ihren eigenen Daten.

## Die Eingabe vorbereiten { #prepare-the-input }

Verwenden Sie eine [laufende Installation](../install.md) mit einem Modellprofil. Speichern Sie dies als `sales.csv`:

```csv
month,product,revenue_eur
2026-01,A,120
2026-01,B,80
2026-02,A,150
2026-02,B,100
2026-03,A,90
2026-03,B,110
```

Die Zahlen sind erfunden. Die Referenzsummen sind 200 EUR für Januar, 250 für Februar und 200 für März, 650 insgesamt, aus sechs Datenzeilen.

## Die Sandbox prüfen { #check-the-sandbox }

Der Agent liest die Datei und führt sein Skript in einem Container aus. Dafür braucht es den Sandbox-Dienst und eine registrierte Verbindung:

- `make dev` und das Docker-Compose-Profil `sandbox` starten den Dienst. Siehe [Installation](../install.md).
- **Sandboxes → Add connection** registriert ihn für die Organisation. Die Verbindung bietet die Runtime `workbench`, die `pandas` und `matplotlib` enthält. Siehe [die Sandbox](../sandbox.md#which-environments-an-agent-may-ask-for).
- `agenticos cmd doctor` meldet, ob jede registrierte Verbindung mit einer Runtime antwortet.

Die erste Session baut das Image `workbench`, etwa 2 GB. Rechnen Sie auf einem frischen Host mit ein bis zwei Minuten für die erste Runde.

## Den Agent bauen { #build-the-agent }

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
2. Aktivieren Sie unter **Toolbox** die Capability **Files & shell**. Wählen Sie **Container**, nicht **Files**: Der Files-Workspace hat keine Shell, daher kann der Agent kein Skript ausführen. Wählen Sie die Verbindung und die Runtime `workbench`, und behalten Sie den Konversations-Scope bei.
3. Aktivieren Sie **Charts**. Die Capability zeichnet Zahlen, die der Agent bereits hat, sodass das Diagramm zeigt, was das Skript berechnet hat.
4. Setzen Sie ein Budget und ein Schrittlimit für den Versuch. Der festgehaltene Run brauchte 25 Schritte und kostete etwa 0,11 USD.
5. Setzen Sie die folgenden Instruktionen und klicken Sie dann auf **Publish**.

```text
You analyse CSV files the user attaches.
Read the file from the workspace before calculating anything.
Show the totals as a table and state the number of rows you read.
Draw charts with create_chart from numbers you computed.
Save any code and output files in the workspace and give their paths.
Do not fetch data from the internet.
```

## Ausführen { #run-it }

Öffnen Sie einen neuen Chat mit dem Agent, hängen Sie `sales.csv` an und senden Sie:

```text
Sum revenue_eur by month. Return the totals as a table, draw a bar chart of them, and save the calculation script and a PNG of the chart in the workspace.
```

Der Anhang wird im Workspace unter `uploads/` abgelegt, und die Nachricht sagt dem Agent, wo. [Dateiverarbeitung](../file-processing.md) beschreibt das Routing.

Wenn der Agent sein Skript ausführen will, zeigt der Chat **Tool approval required**. Einen Shell-Befehl auszuführen ist ein Seiteneffekt, daher genehmigt ihn standardmäßig eine Person. Lesen Sie den Befehl und klicken Sie dann auf **Approve**. Der Run läuft dort weiter, wo er angehalten hat. Um das für einen vertrauenswürdigen Test-Agent zu überspringen, ändern Sie die Genehmigungseinstellung von `execute` im Builder. Siehe [Genehmigungen](../governance.md#approvals).

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Monatssummen in der Antwort, in der Skriptausgabe und im Diagramm | 200, 250 und 200 EUR, in Monatsreihenfolge |
| Gesamtsumme | 650 EUR |
| Gelesene Zeilen | 6 |
| Diagramm | Die Balken beginnen bei null, die Achse nennt die Einheit |
| Workspace | Das Skript und das PNG existieren und lassen sich öffnen |
| Dieselbe Nachricht ohne angehängte Datei | Der Agent sagt, dass die Datei fehlt, und erfindet keine Daten |

Vergleichen Sie jede Zahl mit den Quellzeilen, nicht mit der Zusammenfassung in der Antwort selbst. Öffnen Sie dann den Workspace über das Dateipanel des Chats. Öffnen Sie das PNG selbst und lesen Sie das Skript. Ein Pfad in einer Antwort beweist nicht, dass die Datei existiert.

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter. Der Agent rief `read_file` auf dem Upload auf, `write_file` für `analysis/revenue_by_month.py`, dann `execute`, das zur Genehmigung angehalten wurde. Nach der Genehmigung gab das Skript die drei Summen, `Total rows read : 6` und `Grand total (€) : 650` aus. `create_chart` zeichnete 200, 250 und 200. Der Workspace enthielt das Skript und ein PNG mit 1050×600. Kosten: 0,115 USD.

    Die abschließende Antwort nannte die Summen als Fließtext und listete die gespeicherten Dateien auf, wiederholte aber weder die Tabelle noch die Zeilenzahl. Diese standen in der Ausgabe des Skripts. Ohne Datei listete der Agent einen leeren Workspace auf und bat um die CSV.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Der Agent sagt, er habe keine Shell.** Die Capability verwendet **Files** statt **Container**.
- **Die erste Runde wartet lange.** Das Image `workbench` wird gebaut. Spätere Sessions verwenden es wieder.
- **Der Run hält an, nachdem der Agent sein Skript geschrieben hat.** Er wartet auf die Genehmigung von `execute`. Öffnen Sie den Chat oder den Tab **Approvals** in **Activity**.
- **Ein Verbindungsfehler nennt die Sandbox.** Führen Sie `agenticos cmd doctor` aus und prüfen Sie dann die Verbindung unter **Sandboxes**.
- **Eine Summe ist falsch.** Lesen Sie das Skript, bevor Sie den Prompt ändern. Ein Rechenfehler und eine fehlende Runtime sind verschiedene Probleme, und die Tool-Ergebnisse in Activity zeigen, welches aufgetreten ist.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie die genaue CSV, den Prompt, die Agent-Version, das Modellprofil, den Run in Activity, das Skript und das PNG auf. Bewahren Sie auch fehlgeschlagene Runs auf. Wenn Sie das Ergebnis veröffentlichen, sagen Sie, dass die Daten synthetisch sind, und zeigen Sie genug von der Tabelle, um das Diagramm zu prüfen.

Eine Person genehmigt den Befehl, vergleicht die Summen mit der Quelle und öffnet die Dateien. Der Agent ersetzt diese Prüfung nicht. Er gibt Ihnen alles, was Sie brauchen, um sie schnell durchzuführen.

Wenn das funktioniert, fügen Sie jeweils eine Schwierigkeit hinzu: einen fehlenden Wert, einen wiederholten Monat oder eine zweite Währung. Jede zeigt, wie der Agent mit Daten umgeht, die nicht glatt aufgehen. Um den Bericht nach Zeitplan zu wiederholen, machen Sie mit [einen Wochenbericht planen](scheduled-report.md) weiter.
