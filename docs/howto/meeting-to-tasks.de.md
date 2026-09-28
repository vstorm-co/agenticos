---
source_sha: "70839ec256fb"
title: "Meeting-Aufgaben mit Genehmigung in Tasks umwandeln"
description: "Lassen Sie einen Agent aus einem Meeting-Transkript einen Tracker-Task pro echter Aufgabe vorschlagen, und verlangen Sie, dass ein Mensch jeden genehmigt, bevor er angelegt wird."
---

# Meeting-Aufgaben mit Genehmigung in Tasks umwandeln { #turn-meeting-action-items-into-tasks-with-approval }

Geben Sie einem Agent die Aufgaben aus einem Meeting-Transkript und eine [MCP-Verbindung zu Linear oder Jira](../mcp.md#project-management), und lassen Sie ihn einen Task pro Punkt vorschlagen, statt unbeaufsichtigt etwas anzulegen. Die Person, die die Vorschläge liest, bearbeitet oder lehnt ab, bevor auch nur ein Task im Tracker landet. Diese Seite lässt sich hier nicht vollständig ausführen: Diese Umgebung hat keine Verbindung zu Linear oder Jira, daher gibt es unten keinen festgehaltenen Run.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil.
- **`connections:manage`**, um Linear oder Jira als organisationsweite MCP-Verbindung hinzuzufügen, oder ein normales Mitgliedskonto, um eine für sich selbst unter **MCP servers → You** zu verbinden.
- Ein Meeting-Transkript als Grundlage. [Ein Meeting zusammenfassen](meeting-summary.md) beschreibt, wie Sie dessen Entscheidungen und Aufgaben prüfen, bevor eine davon zum Task wird.

## Die Eingabe vorbereiten { #prepare-the-input }

Ein kleines, erfundenes Transkript mit einer klaren Aufgabe, einer Aufgabe ohne Fälligkeitsdatum und einem geäußerten Bedenken, das niemand tatsächlich übernimmt. Letzteres ist der Grenzfall, den es zu prüfen lohnt:

```text
Weekly ops sync - 24 September 2026
Attendees: Priya, Tom, Sana

- Priya will update the onboarding doc with the new pricing tiers by Friday.
- Tom will follow up with the vendor about the delayed shipment.
- Sana raised that the support queue is growing, but nobody was assigned to look into it.
```

Referenz: zwei echte Aufgaben (Priya, fällig am Freitag; Tom, ohne genanntes Fälligkeitsdatum) und eine offene Frage ohne Verantwortlichen, die keine Aufgabe ist.

## Den Tracker verbinden { #connect-the-tracker }

Linear steht im Katalog mit **oauth** unter `https://mcp.linear.app/sse`. Jira und Confluence teilen sich einen Eintrag, ebenfalls **oauth**, unter `https://mcp.atlassian.com/v1/sse` (siehe [den Katalog](../mcp.md#project-management)). Für einen Tracker, in den das ganze Team einträgt, verbinden Sie ihn unter **MCP servers → Organization**, damit jeder gebundene Agent Tasks unter derselben Integrationsidentität anlegt. Binden Sie stattdessen [das eigene Konto jeder Person](../mcp.md#whose-account-a-binding-speaks-through) nur, wenn Ihr Tracker erwartet, dass Tasks im Namen der Person angelegt werden, die darum gebeten hat.

Grenzen Sie `allowed_tools` an der Verbindung auf das Tool zum Anlegen und Kommentieren ein, das dieser Ablauf braucht, falls der Server auch solche anbietet, die bestehende Issues bearbeiten oder löschen. Die Bindung kann nur innerhalb dessen eingrenzen, was die Verbindung bereits erlaubt, und nie zurückholen, was sie ausschließt.

## Den Agent bauen { #build-the-agent }

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
2. Fügen Sie in der **Toolbox** den Tracker unter **MCP servers** hinzu.
3. Setzen Sie die Instruktionen unten und klicken Sie dann auf **Publish**.

```text
You turn meeting notes into tracker tasks.
Propose one task per real action item: a title, the assignee named in the notes, a due date only if one was actually stated, and a one-line description.
Do not invent an assignee, a due date or a priority that the notes do not state.
If something was raised but nobody was assigned to it, say so as an open question rather than proposing a task for it.
Create each proposed task with its own tool call, one at a time, so each can be reviewed on its own.
```

## Ausführen { #run-it }

Bevor Sie den Agent bitten, etwas anzulegen, öffnen Sie **Chat controls → Approval mode** und wählen Sie **Ask about everything**. Das ist hier aus demselben Grund wichtig wie beim [Anhängen an Notion](notion-agent.md#workflow-append-meeting-notes-with-a-person-deciding): Das Anlege-Tool des Trackers wird zur Laufzeit aus der MCP-Verbindung ermittelt, sodass keine im Spec erklärte Genehmigung pro Tool es je erreicht. Der Genehmigungsmodus der Session selbst ist die einzige Schranke, die ein Anlege-Aufruf bekommt.

```text
Turn the action items in this transcript into tasks:

Weekly ops sync - 24 September 2026
Attendees: Priya, Tom, Sana

- Priya will update the onboarding doc with the new pricing tiers by Friday.
- Tom will follow up with the vendor about the delayed shipment.
- Sana raised that the support queue is growing, but nobody was assigned to look into it.
```

Jeder Anlege-Aufruf parkt für sich: Ein Modell, das in einem Schritt zwei Tasks vorschlägt, parkt zwei getrennte Genehmigungszeilen, jede unabhängig entschieden. Lesen Sie bei jeder den genauen Titel, die zugewiesene Person und das Fälligkeitsdatum, bevor Sie **Approve** wählen oder ablehnen. Ein abgelehnter Aufruf geht als Ablehnung an den Agent zurück, auf die er reagieren kann, nicht als Absturz.

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Anzahl vorgeschlagener Tasks | Zwei, einer pro echter Aufgabe |
| Priyas Task | Zugewiesen an Priya, fällig am Freitag |
| Toms Task | Zugewiesen an Tom, kein erfundenes Fälligkeitsdatum |
| Sanas Punkt | Nicht als Task vorgeschlagen; als offene Frage ohne Verantwortlichen genannt |
| Einen vorgeschlagenen Task ablehnen | Der Tracker erhält ihn nicht; die letzte Antwort des Agents sagt, welcher übersprungen wurde |
| Den Rest genehmigen | Der Tracker erhält genau die genehmigten Tasks, nicht mehr |
| Dasselbe Transkript mit ausgeschaltetem **Ask about everything** | Jeder vorgeschlagene Task wird sofort angelegt, ohne vorherige Prüfung |
| Ein Transkript ganz ohne Aufgaben | Sagt, dass es nichts in einen Task umzuwandeln gibt, statt einen zu erfinden |

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Ein Task wird angelegt, bevor ihn jemand geprüft hat.** Prüfen Sie zuerst den **Approval mode** der Konversation. `required` an einer Capability erreicht nie ein MCP-Tool, also hängt die Prüfung davon ab, dass die Session jedes Mal auf **Ask about everything** steht.
- **Der Agent erfindet ein Fälligkeitsdatum oder eine zugewiesene Person.** Verschärfen Sie die Instruktionen, nicht die Verbindung. Das ist ein Prompt-Fehler, und das Transkript hätte ihm bereits sagen müssen, was er nicht weiß.
- **Ein geäußertes Bedenken wird trotzdem zum Task.** Prüfen Sie, ob die Instruktionen "jemandem zugewiesen" von "erwähnt" unterscheiden. Die offene Frage im Beispiel gibt es genau, um das zu erkennen.
- **Zwei verschiedene Agents schlagen einen Task für dieselbe Aufgabe vor.** Die Quelle der Wahrheit ist hier der Tracker selbst, nicht der Run-Verlauf dieser Plattform. Prüfen Sie den Tracker auf ein Duplikat, bevor Sie annehmen, dass der Agent falsch liegt.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie das Transkript, jeden vorgeschlagenen Task, welche genehmigt oder abgelehnt wurden, und den späteren Zustand des Trackers selbst auf. Das Genehmigungsprotokoll von AgenticOS hält fest, was vorgeschlagen wurde und wer entschieden hat, nicht, ob der Tracker später noch so aussieht. Ein Mensch liest weiterhin jeden Vorschlag, korrigiert eine falsche zugewiesene Person vor dem Genehmigen statt danach und entscheidet, wer einem Agent überhaupt eine Tracker-Verbindung mit Anlegerechten binden darf.

## Nächste Schritte { #next-steps }

Für dasselbe Muster "vor dem Schreiben genehmigen" an einem Dokument statt einem Tracker siehe [Notion von einem Agent aus durchsuchen und aktualisieren](notion-agent.md). Um die Entscheidungen und Aufgaben eines Transkripts zu prüfen, bevor Sie eine davon in einen Task umwandeln, siehe [Ein Meeting-Transkript in Entscheidungen und Aufgaben zusammenfassen](meeting-summary.md).
