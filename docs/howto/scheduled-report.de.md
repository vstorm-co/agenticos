---
source_sha: "4137cd31f700"
title: "Einen Wochenbericht planen"
description: "Geben Sie einem Agent eine in sich geschlossene Berichtsaufgabe, führen Sie sie bei Bedarf aus, veröffentlichen Sie das Ergebnis als Artefakt und legen Sie einen wöchentlichen Zeitplan fest."
---

# Einen Wochenbericht planen { #schedule-a-weekly-report }

Bauen Sie einen Agent, der aus den Daten in seiner Aufgabe einen kurzen Bericht schreibt und ihn als [Artefakt](../artifacts.md) unter einem stabilen Link veröffentlicht. Legen Sie dann einen wöchentlichen Zeitplan fest. Die Testdaten enthalten eine Zeile, die sich nicht verwenden lässt, sodass Sie prüfen können, dass der Agent sie meldet, statt sie zu verbergen. Dies ist eine Anleitung zum Durchführen, mit einem festgehaltenen Run als Referenz.

Die Seite trennt zwei Fragen. Kommt der Bericht richtig heraus? Das testen Sie mit **Run now**. Liefert der Zeitplan ihn aus? Das beantwortet nur eine geplante Auslösung.

## Den Agent bauen { #build-the-agent }

Verwenden Sie eine [laufende Installation](../install.md) mit einem Modellprofil. Weder eine Sandbox noch ein Embedding-Modell ist nötig.

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
2. Aktivieren Sie unter **Toolbox** die Capabilities **Charts** und **Artifacts**.
3. Setzen Sie ein Budget und ein Schrittlimit für den Versuch. Die festgehaltenen Runs brauchten 15 Schritte und kosteten jeweils etwa 0,05 USD.
4. Setzen Sie die folgenden Instruktionen und klicken Sie dann auf **Publish**.

```text
You write short reports from data given in the task.
Use only the rows in the task. Report totals per category and name any row you could not use.
Label the report as synthetic when the task says the data is synthetic.
Publish the finished report with publish_artifact under the name weekly-report.
```

Der Name des Artefakts ist seine Identität. Jeder Run dieses Agents, der `weekly-report` veröffentlicht, fügt demselben Artefakt eine Version hinzu, sodass der Link, den Sie teilen, gleich bleibt.

## Den Zeitplan erstellen { #create-the-schedule }

Öffnen Sie **Routines → New schedule** oder den Tab **Availability** des Agents und wählen Sie den Agent. Schreiben Sie die Daten in die Nachricht, damit ein späterer Run nicht von einer Datei abhängt, die jemand in einen früheren Chat hochgeladen hat:

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

Wählen Sie für den Rhythmus **At a set time**, dann **Days of the week**, haken Sie **Mon** an und setzen Sie **Time (UTC)** auf 09:00. Der entsprechende Cron-Ausdruck ist `0 9 * * 1`. Der Scheduler arbeitet in UTC, rechnen Sie also von Ihrer Ortszeit um. Speichern Sie und prüfen Sie dann die nächste Auslösezeit, die der Zeitplan anzeigt.

Der Zeitplan läuft als das Mitglied, das ihn erstellt hat, mit dessen Zugriff, und seine Runs werden wie alle anderen dem Budget des Agents belastet. [Konzepte](../concepts.md#trigger) erklärt, warum.

## Jetzt ausführen { #run-it-now }

Drücken Sie **Run now** auf dem Zeitplan. Das löst ihn einmal zusätzlich aus und lässt den wöchentlichen Rhythmus unverändert. Die Anfrage kehrt zurück, sobald der Worker die Auslösung annimmt. Der Run erscheint dann in der eigenen Konversation des Zeitplans, unter **Routines** in der Chat-Seitenleiste.

| Prüfung | Referenz |
| --- | --- |
| Summen | Supplies 50, Travel 15 |
| Die Zeile `Travel,abc` | Als unbrauchbar genannt und nicht mitgezählt |
| Kennzeichnung | Der Bericht sagt, dass die Daten synthetisch sind |
| Artefakt | **Artifacts** listet `weekly-report`, privat für Sie |
| Der Run in Activity | Oberfläche `schedule`, Status completed |
| Run now ein zweites Mal | Eine neue Version desselben Artefakts, unter demselben Link |

Öffnen Sie die Seite des Artefakts und lesen Sie den Bericht dort, nicht nur die Chat-Antwort. Diese Seite ist das, was andere öffnen werden. Sie bleibt privat, bis Sie sie teilen oder einen öffentlichen Link erstellen.

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter. Der Zeitplan meldete als nächste Auslösung Montag, 28. September, 09:00 UTC. Run now wurde mit `202` angenommen, und der Run wurde etwa 30 Sekunden später auf der Oberfläche `schedule` abgeschlossen, für 0,044 USD.

    Der Agent rief `publish_artifact` mit dem Namen `weekly-report` auf und erhielt Version 1, privat. Dann rief er `create_chart` auf. Das Artefakt zeigte Supplies 50 und Travel 15, eine Kennzeichnung als synthetische Daten und "Rows excluded (could not be used): Travel, abc". Ein zweites Run now fügte demselben Artefakt und Link Version 2 hinzu.

    Das Diagramm erschien in der Konversation des Runs, nicht im Artefakt. Die Artefakt-Seite hat keinen Netzwerkzugriff, und der Agent schrieb den Bericht ohne eingebettetes Diagramm.

## Was der Zeitplan nicht für Sie entscheidet { #what-the-schedule-does-not-decide-for-you }

- **Woher die Daten kommen.** Diese Testdaten stehen fest in der Nachricht. Ein echter Bericht braucht eine Quelle, die der Agent bei jedem Run erreicht, etwa eine [Knowledge-Sammlung](set-up-knowledge-base.md), eine [MCP-Verbindung](../mcp.md) oder einen Sandbox-Workspace. Ein Zeitplan kann nicht erraten, welche neu hochgeladene Datei die der letzten Woche ersetzt.
- **Der Berichtszeitraum.** Nennen Sie ihn in der Nachricht oder lassen Sie den Agent das Datum lesen. Eine Datei namens "weekly" sagt dem Modell nicht, welche Daten es einbeziehen soll.
- **Wer ihn liest.** Ein neues Artefakt ist privat für die Person, für die der Run lief. Teilen Sie es oder erstellen Sie einen öffentlichen Link auf der Seite des Artefakts. [Artefakte](../artifacts.md) behandelt Sichtbarkeit und Grants.
- **Genehmigungen.** Keines der hier verwendeten Tools braucht eine. Fügen Sie ein Tool hinzu, das eine braucht, hält ein geplanter Run an, bis jemand entscheidet. Benennen Sie also, wer die [Genehmigungswarteschlange](../governance.md#approvals) beobachtet.

## Eine echte Auslösung beobachten { #watch-a-real-fire }

Run now beweist die Aufgabe, nicht den Zeitplan. Prüfen Sie nach dem ersten Montag um 09:00 UTC, dass in Activity von selbst ein neuer Run erschienen ist, dass das Artefakt eine Version hinzubekommen hat und dass die Personen, die es lesen sollen, es öffnen können. Die Dashboard-Karte **Routines** zeigt das letzte Ergebnis jeder Routine, sodass ein Zeitplan, der zu scheitern beginnt, sichtbar wird.

Ein Zeitplan, dessen Ersteller den Agent nicht mehr ausführen kann, deaktiviert sich selbst und hält fest, warum. Siehe [Konzepte](../concepts.md#it-runs-as-a-person).

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Bei Run now passiert nichts.** Der Zeitplan ist pausiert, oder der Hintergrund-Worker läuft nicht. Der Worker führt jede geplante und jede Run-now-Auslösung aus.
- **Der Bericht hat kein Artefakt.** Prüfen Sie, dass **Artifacts** aktiviert ist und dass die Instruktionen `weekly-report` nennen. Die Tool-Aufrufe des Runs in Activity zeigen, ob `publish_artifact` aufgerufen wurde und was es zurückgegeben hat.
- **Jeder Run erzeugt ein neues Artefakt.** Der Name hat sich zwischen den Runs geändert. Halten Sie ihn in den Instruktionen fest.
- **Eine Summe ist falsch oder die fehlerhafte Zeile ist verschwunden.** Schärfen Sie die Instruktionen nach, bevor Sie etwas planen. Ein Zeitplan wiederholt einen Fehler jede Woche.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie die Nachricht, die Agent-Version, das Modellprofil, den Cron-Ausdruck, jeden Run in Activity und jede Artefakt-Version auf. Halten Sie fest, welche Auslösungen Run now waren und welche geplant. Eine Person prüft die Summen, entscheidet, wer das Artefakt lesen darf, und beobachtet die erste echte Auslösung.
