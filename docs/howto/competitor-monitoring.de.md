---
source_sha: "a28e7805a24a"
title: "Webseiten nach Zeitplan auf Änderungen prüfen"
description: "Rufen Sie zwei Seiten nach Zeitplan ab, vergleichen Sie jede mit dem zuletzt festgehaltenen Stand, und melden Sie nur, was sich geändert hat."
---

# Webseiten nach Zeitplan auf Änderungen prüfen { #watch-web-pages-for-changes-on-a-schedule }

Bauen Sie einen Agent, der eine kleine Menge von Seiten abruft, eine kurze Zusammenfassung dessen behält, was er zuletzt gesehen hat, und beim nächsten Run sagt, was sich geändert hat - oder dass nichts sich geändert hat. Das Test-Setup beobachtet zwei Seiten, die Sie nicht kontrollieren, die sich aber selten ändern: die GitHub-Releases-Seite eines Projekts und `example.com`. Dies ist eine Anleitung zum Durchführen, mit zwei festgehaltenen Auslösungen als Referenz.

Zwei Auslösungen beweisen zwei verschiedene Dinge. **Run now** beweist, dass die Vergleichslogik funktioniert. Es beweist nicht, dass eine *echte* Änderung je erfasst wird - das zeigt nur eine Auslösung, die eintrifft, nachdem sich die Seite tatsächlich geändert hat, und diese Seite kann eine solche nicht auf Abruf festhalten.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil.
- Keine Knowledge-Sammlung, keine MCP-Verbindung und keine Sandbox-Verbindung: Der Workspace, den dieses Rezept verwendet, braucht nichts davon. Siehe unten.

## Warum nicht Memory-Dateien { #why-not-memory-files }

Die naheliegende Capability für "merke dir, was ich zuletzt gesehen habe" sind [Memory-Dateien](../reference/capabilities.md#memory-files). Sie funktioniert hier nicht, und der Grund ist es wert, ihn zu kennen, bevor Sie bei einem Zeitplan danach greifen.

Eine Trigger-Auslösung läuft für Budgets, Genehmigungen und den Audit-Trail als ihr Ersteller, aber nicht für das Gedächtnis: Das *Publikum* des Runs - wer die Antwort hören wird - ist auf der Oberfläche `schedule` absichtlich leer, sodass ein unbeaufsichtigter Run die persönlichen Notizen des Erstellers weder lesen noch schreiben kann. `write_memory` und `read_memory` antworten beide:

```text
This conversation has no memory. It has no identified person and is not a
group chat, so a note would have to land somewhere other people read. Answer
from what you have rather than saving.
```

Derselbe Agent, dieselbe Frage in einem gewöhnlichen Chat gestellt, speichert die Notiz ohne Probleme - der Speicher existiert dort, weil eine echte Person zuhört. Bei einem Zeitplan hört niemand zu.

## Was Sie stattdessen verwenden { #what-to-use-instead }

Ein [Sandbox](../sandbox.md)-Workspace mit dem Scope **conversation** bleibt über jede Auslösung eines Triggers hinweg erhalten, weil ein Trigger für sein ganzes Leben eine Konversation öffnet und jede Auslösung daran anhängt - die `conversation_id`, an der ein Workspace hängt, hängt nicht davon ab, wer zuhört. Das Backend `state` braucht keine Sandbox-Verbindung: Es ist ein kleiner Speicher in der eigenen Datenbank dieses Deployments, ohne Shell und ohne Container.

## Den Agent bauen { #build-the-agent }

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
2. Aktivieren Sie unter **Toolbox** **Web fetch**. Beschränken Sie `allowed_domains` auf `github.com` und `example.com`, damit der Agent nicht gebeten werden kann, etwas anderes abzurufen.
3. Aktivieren Sie **Files & shell**. Lassen Sie das Backend auf **Files** (das Backend `state` - keine Shell, keine Sandbox-Verbindung) und den Scope auf **This conversation** - die Standardwerte sind genau das, was dieses Rezept braucht.
4. Setzen Sie ein Budget und ein Schrittlimit für den Versuch. Jede festgehaltene Auslösung kostete etwa 0,07-0,14 USD.
5. Setzen Sie die folgenden Instruktionen und klicken Sie dann auf **Publish**.

```text
You watch two pages for changes, once per run:
- https://github.com/vstorm-co/agenticos/releases
- https://example.com/

Each run:

1. Fetch both pages with web_fetch.
2. For the GitHub page, keep only the latest (topmost) release: its tag and
   title. For example.com, keep its heading and first paragraph. Ignore
   everything else on each page - star counts, timestamps, navigation.
3. Look for a file named watch-state.txt in your workspace.
4. If it does not exist, write it now with today's two summaries, one line
   per page, and report that you recorded a baseline - not a change.
5. If it exists, read it and compare each page's new summary to the line
   stored for it. Report, page by page, either the old and new value or
   "no change". Then overwrite watch-state.txt with the new summaries.
Never say a page changed unless the two lines you compared actually differ.
```

## Den Zeitplan erstellen { #create-the-schedule }

Öffnen Sie **Routines → New schedule** oder den Tab **Availability** des Agents, wählen Sie den Agent und setzen Sie einen täglichen Rhythmus. Der Prompt muss nur die Aufgabe nennen:

```text
Run today's page check.
```

## Ausführen { #run-it }

Drücken Sie zweimal, im Abstand weniger Minuten, **Run now** auf dem Zeitplan. Die erste Auslösung findet keine `watch-state.txt` und schreibt einen Basiswert. Die zweite liest ihn zurück und vergleicht.

!!! warning "Eine veröffentlichte Korrektur versetzt einen laufenden Zeitplan nicht automatisch darauf"

    Das Veröffentlichen prägt eine Version, verlegt aber nicht die [Umgebung](../environments.md), aus der ein Zeitplan liest, es sei denn, diese Umgebung hat **tracks latest** eingeschaltet - was `production` standardmäßig nicht hat. Wenn Sie den Agent bearbeiten, nachdem Sie den Trigger erstellt haben, befördern Sie die neue Version in diese Umgebung (**Promote v2 to…**, mit Ihrer Versionsnummer), bevor der nächste **Run now** läuft, sonst führt die Auslösung weiterhin die Version aus, die Sie gerade ersetzt haben.

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Erstes **Run now** | Meldet einen Basiswert, keine Änderung, und für keine Seite wird ein Unterschied gemeldet |
| `watch-state.txt` nach der ersten Auslösung | Existiert, mit einer Zeile pro Seite |
| Zweites **Run now** | Liest dieselbe Datei zurück und meldet für beide Seiten "keine Änderung" |
| Eine Seite, die Sie zwischen zwei Auslösungen bearbeitet haben | Meldet für diese eine Seite den alten und den neuen Wert |
| Die Oberfläche des Runs in Activity | `schedule` für beide Auslösungen, derselbe Trigger, dieselbe Run-Log-Konversation |
| Ein Run, dessen `web_fetch` auf eine dritte Domain zeigt | Abgelehnt - `allowed_domains` enthält sie nicht |

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter. Das erste **Run now** rief `web_fetch` auf beiden Seiten auf, dann `read_file` auf `watch-state.txt`, was fehlschlug, weil die Datei noch nicht existierte, dann `write_file`. Es meldete den neuesten Release der GitHub-Seite als `v0.0.504` sowie Überschrift und Absatz von example.com und sagte, dies sei ein Basiswert. Kosten: 0,13 USD. Das zweite **Run now**, etwa eine Minute später, las dieselbe Datei zurück, glich beide Zusammenfassungen ab und meldete für beide Seiten "No change", dann schrieb es die Datei mit demselben Inhalt neu. Kosten: 0,14 USD.

    Der erste Versuch verwendete `memory_files` statt einer Sandbox, genau wie diese Seite davor warnt: Beide Auslösungen riefen `read_memory` auf und erhielten die obige "no memory"-Ablehnung, und der Agent sagte der Person, die den Bericht liest, korrekt, dass er keinen Basiswert speichern konnte - statt zu behaupten, er habe es getan.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Jede Auslösung sagt "no prior state", nie einen Vergleich.** Der Workspace bleibt nicht erhalten. Prüfen Sie, dass der Scope **This conversation** ist, nicht **Nobody** - der Scope `run` öffnet bei jeder einzelnen Auslösung einen neuen, leeren Workspace.
- **`read_memory` oder `write_memory` taucht überhaupt im Transkript auf.** Memory-Dateien ist noch gebunden. Entfernen Sie es; es kann diese Aufgabe bei einem Zeitplan nicht erfüllen.
- **Eine echte Seitenänderung wird nicht gemeldet.** Nur eine Auslösung, die nach der Änderung läuft und nach einer Auslösung, die den vorherigen Zustand festgehalten hat, erfasst sie. Prüfen Sie in Activity die beiden Auslösungen vor und nach der Änderung, nicht nur die letzte.
- **Jede Auslösung meldet eine Änderung, selbst wenn sich nichts bewegt hat.** Die Zusammenfassung ist zu weit gefasst - ein roher Seitenabruf enthält Star-Zahlen, relative Zeitstempel oder eine wechselnde Nonce, die bei jedem Abruf anders ist. Schränken Sie das, was die Instruktionen behalten, auf die eine Tatsache ein, die zählt.
- **Die Auslösung verhält sich nach dem erneuten Veröffentlichen weiterhin wie die alte Version.** Siehe die Warnung zur Umgebung oben.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie die beiden Seiten-URLs, die Instruktionen, die Agent-Version, `watch-state.txt` nach jeder Auslösung und jeden Run in Activity mit seiner Oberfläche und seinen Kosten auf. Eine Person entscheidet weiterhin, was als eine Änderung zählt, die eine Reaktion wert ist, und beobachtet die erste Auslösung, die nach einer echten Bearbeitung eintrifft, um zu bestätigen, dass der Vergleich sie erfasst - ein Paar aus zwei `Run now` beweist nur die Logik, nie diese Auslösung selbst.
