---
source_sha: "926f21066868"
title: "Eine Frage mit Subagents recherchieren und einen Bericht veröffentlichen"
description: "Zerlegen Sie eine Frage in unabhängige Teilfragen, delegieren Sie jede an einen einmaligen Spezialisten und veröffentlichen Sie einen belegten Vergleich als Artefakt."
---

# Eine Frage mit Subagents recherchieren und einen Bericht veröffentlichen { #research-a-question-with-subagents-and-publish-a-report }

Bauen Sie einen Agent, der eine Frage in unabhängige Teile zerlegt, jeden Teil einem eigenen Spezialisten übergibt und aus den Ergebnissen einen Bericht schreibt. Das Beispiel ist ein Vergleich von drei Open-Source-Lizenzen: ein stabiles, öffentliches Thema, bei dem sich jede Behauptung am Lizenztext selbst prüfen lässt. Dies ist eine Anleitung zum Ausführen, mit einem festgehaltenen Run als Referenz.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil.
- Websuche: Die Standardmethode ist DuckDuckGo und braucht weder Konto noch Schlüssel.
- Keine Sandbox, keine Wissenssammlung und keine MCP-Verbindung.

## Die Eingabe vorbereiten { #prepare-the-input }

Die Frage zerfällt in drei unabhängige Teilfragen, eine pro Lizenz. Fragen Sie:

```text
Compare the MIT licence, the Apache License 2.0 and the GPLv3 on one question:
when you distribute software that includes code under that licence, what are
you obligated to do - include the licence text, state changes you made, or
disclose or release your own source code?
```

Die Referenzantwort, damit Sie den Bericht des Agents von Hand prüfen können:

| Lizenz | Lizenztext beilegen | Änderungen angeben | Eigenen Quellcode freigeben |
| --- | --- | --- | --- |
| MIT | Ja | Nein | Nein |
| Apache-2.0 | Ja, plus die Datei `NOTICE` | Ja, pro Datei | Nein |
| GPLv3 | Ja | Ja, pro Datei | Ja, für das gesamte kombinierte Werk, bei Weitergabe |

Die Quellcodepflicht der GPLv3 wird durch Weitergabe ausgelöst, nicht durch Änderung: Eine Organisation, die eine geänderte Kopie nur intern betreibt, schuldet niemandem eine Freigabe.

## Den Agent bauen { #build-the-agent }

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
2. Aktivieren Sie in der **Toolbox** **Delegation**. Schalten Sie `allow_dynamic` ein, die Einstellung, mit der das Modell einen einmaligen Spezialisten für eine Teilfrage erfinden darf, für die niemand vorab einen geschrieben hat. Setzen Sie den Modus auf **Async**, damit die drei Teilfragen gleichzeitig statt nacheinander laufen, und lassen Sie die Fan-out-Obergrenze bei 3.
3. Schalten Sie, weiterhin unter Delegation, **Share Web search with delegates** und **Share Web fetch with delegates** ein. Ein vom Modell erfundener Spezialist bekommt [absichtlich](../reference/capabilities.md#delegation) keine eigenen Capabilities. Nur was der Parent ausdrücklich teilt, erreicht ihn, sodass ohne diesen Schritt jeder erfundene Spezialist zwar delegieren, aber nicht suchen könnte.
4. Aktivieren Sie **Web search** (Methode DuckDuckGo) und **Read web pages** beim Parent selbst. Teilen erreicht einen Delegate nur mit dem, woran der Parent gebunden ist.
5. Aktivieren Sie **Planning** und **Artifacts**.
6. Legen Sie Budget und Schrittlimit für den Versuch fest. Der festgehaltene Run nutzte 40 Schritte und kostete etwa 0,43 USD.
7. Setzen Sie die Instruktionen unten und klicken Sie dann auf **Publish**.

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

## Ausführen { #run-it }

Öffnen Sie einen neuen Chat mit dem Agent und senden Sie die Frage aus *Die Eingabe vorbereiten*.

Das Modell ruft `delegate` dreimal auf, einmal pro Lizenz. Jeder Aufruf ist eine eigene Delegation, nicht ein einzelner Aufruf für alle drei. **Delegate hat Seiteneffekte**, also parken alle drei gemeinsam zur Genehmigung, weil ein Modellschritt mehrere Aufrufe auf einmal parken kann. Lesen Sie die drei vorgeschlagenen Spezialisten und klicken Sie dann auf **Approve**. Der Run setzt fort, startet die drei Spezialisten im Hintergrund und ruft `wait_tasks` auf, um ihre Ergebnisse einzusammeln, bevor er den Bericht schreibt.

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Anzahl der Delegationen | Drei, eine pro Lizenz, jede als eigene Zeile in Activity unter dem Run des Parents |
| Pflicht aus MIT | Lizenztext und Copyright-Hinweis beilegen, sonst nichts |
| Pflicht aus Apache-2.0 | Lizenztext, Datei `NOTICE` und ein Änderungshinweis pro Datei |
| Pflicht aus GPLv3 | Lizenztext, Änderungen pro Datei und der vollständige Quellcode bei Weitergabe |
| Jede Behauptung | Hat eine Quell-URL direkt daneben, nicht in einer Liste am Ende gesammelt |
| Widerspruch oder Lücke | Der Bericht sagt das ausdrücklich oder stellt fest, dass es keine gab |
| Artefakt | **Artifacts** listet `licence-comparison`, privat für Sie |
| Eine zweiteilige Frage mit nur einer echten Quelle (z. B. nach einer Lizenz, die es nicht gibt) | Der Bericht sagt, dass er diesen Teil nicht bestätigen konnte, statt eine Antwort zu erfinden |

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter. Der Agent schrieb einen Plan mit vier Schritten und rief dann in einer Runde dreimal `delegate` auf: `mit-licence-research`, `apache2-licence-research`, `gplv3-licence-research`, alle asynchron. Alle drei parkten in einem Schritt zur Genehmigung. Nach der Genehmigung rief der Run `wait_tasks` auf und bekam `3/3 finished`. Der Bericht stimmte genau mit der Referenztabelle überein, zitierte die Seiten von OSI, Apache.org, GNU.org und die FSF-FAQ und endete mit "No source disagreements found" samt den übereinstimmenden Quellen. Er veröffentlichte `licence-comparison` als HTML-Artefakt. Gesamtkosten: 0,43 USD einschließlich aller drei Delegationen. Für einen dynamischen Spezialisten gibt es keine eigene `agent_runs`-Zeile, da er kein veröffentlichter Agent ist.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Eine Delegation wird sofort abgelehnt statt geparkt.** Delegation ist aus, oder `allow_dynamic` ist aus und das Modell hat trotzdem `delegate` oder `create_agent` versucht. Ohne beides wird einer Delegation nur `task` angeboten.
- **Ein Spezialist meldet, er habe kein Suchwerkzeug.** `share_with_delegates` wurde nicht gesetzt, oder es nennt eine Capability, an die der Parent selbst nicht gebunden ist. Den zweiten Fall lehnt die Veröffentlichung ab, also ist es meist der erste.
- **Die drei Teilfragen laufen nacheinander statt gleichzeitig.** Der Modus ist `sync`, oder das Modell hat entgegen den Instruktionen in seinen eigenen `delegate`-Aufrufen `mode="sync"` gewählt.
- **Es erscheint nur eine Delegation, die alles abdeckt.** Das Modell hat die dreiteilige Frage als eine Aufgabe behandelt, statt sie zu zerlegen. Verschärfen Sie die Instruktionen so, dass sie das getrennte Delegieren jedes Teils nennen, nicht nur dessen Recherche.
- **Der Run stoppt mit "reached the fan-out ceiling".** In einer Runde wurden mehr Delegationen als `max_fanout` gestartet. Drei Teilfragen passen in den Standardwert 3, eine vierte nicht.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie die Frage, den Plan des Agents, Name und Ergebnis jeder Delegation, die zitierten Quellen, das Artefakt mit seiner Version und die Kosten aus Activity auf. Ein Mensch liest das Artefakt weiterhin gegen die Referenzfakten, bevor er ihm vertraut, entscheidet, wer es lesen darf, und beurteilt, ob der Abschnitt "could not confirm" ehrlich ist oder eine Suche verbirgt, die erneut hätte versucht werden sollen.

## Nächste Schritte { #next-steps }

Sobald das bei einem Thema mit bekannter Antwort funktioniert, richten Sie den Agent auf eine Frage ohne feste Referenz und verlassen Sie sich auf die Instruktion "state where sources disagree" statt auf eine Tabelle, die Sie bereits kennen. Um den Bericht aktuell zu halten, machen Sie mit [Einen Wochenbericht planen](scheduled-report.md) weiter.
