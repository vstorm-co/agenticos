---
source_sha: "d73b776f3671"
title: "Notion von einem Agent aus durchsuchen und aktualisieren"
description: "Verbinden Sie Notion als MCP-Server, lassen Sie einen Agent aus einer Seite antworten, die er selbst findet, und verlangen Sie die Prüfung durch einen Menschen, bevor er etwas anhängt."
---

# Notion von einem Agent aus durchsuchen und aktualisieren { #search-and-update-notion-from-an-agent }

Verbinden Sie Notion über [MCP](../mcp.md), damit ein Agent einen Workspace durchsuchen, aus dem Gefundenen antworten und Meeting-Notizen an eine Seite anhängen kann, wobei ein Mensch jedes Mal entscheidet, ob der Schreibvorgang wirklich stattfindet. Diese Seite beschreibt beide Abläufe und die genauen Verbindungsentscheidungen, von denen sie abhängen. Sie lässt sich hier nicht ausführen: Diese Umgebung hat kein Notion-Konto zum Verbinden, daher gibt es unten keinen festgehaltenen Run.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil.
- **`connections:manage`**, um Notion für die ganze Organisation hinzuzufügen, oder nichts über ein normales Mitgliedskonto hinaus, um es nur für sich selbst unter **MCP servers → You** zu verbinden.
- Einen Notion-Workspace, für den Sie eine OAuth-App autorisieren dürfen.

## Notion verbinden { #connect-notion }

Notion steht im Katalog mit **oauth** unter `https://mcp.notion.com/mcp` (siehe [den Katalog](../mcp.md#communication-support-knowledge)). Zwei Entscheidungen zählen, bevor ein Agent es überhaupt berührt:

**Organisation oder persönlich.** Unter **MCP servers → Organization** hinzugefügt (`connections:manage`), antwortet eine Notion-Verbindung für jeden daran gebundenen Agent, auf jeder Oberfläche, unter einem gemeinsamen Namen und einer Identität im eigenen Audit-Log von Notion. Unter **MCP servers → You** hinzugefügt, verbindet dagegen jede Person ihren eigenen Workspace-Zugang, und eine Bindung an *das eigene Konto jeder Person* (`account: personal` im Spec) lässt den Agent als die fragende Person mit Notion sprechen. Das Log von Notion zeigt dann, wer was getan hat, aber eine Kollegin, die ihr eigenes Notion nicht verbunden hat, bekommt die Aufforderung, das zu tun, statt einer Antwort aus dem Workspace von jemand anderem. Siehe [über wessen Konto eine Bindung spricht](../mcp.md#whose-account-a-binding-speaks-through).

**Ein Name und ein Tool-Präfix.** Einen zweiten Notion-Workspace zu verbinden, erzwingt einen zweiten Namen: Das Präfix `notion` ist vergeben, also wird der zweite zu `notion-2`, und das Modell liest das Präfix, das seine Bindung nennt. Siehe [zwei Namen, und sie beantworten verschiedene Fragen](../mcp.md#two-names-and-they-answer-different-questions).

Für ein kleines Team mit einem gemeinsamen Workspace ist das Konto der Organisation der einfachere Start. Wechseln Sie zum eigenen Konto jeder Person, wenn verschiedene Menschen nur erreichen sollen, was ihr eigenes Notion-Login sehen kann.

## Den Agent bauen { #build-the-agent }

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
2. Fügen Sie in der **Toolbox** den Notion-Server unter **MCP servers** hinzu, gebunden an das Konto der Organisation (oder das eigene jeder Person). Lassen Sie seine Tools für einen ersten Durchgang unbeschränkt, oder grenzen Sie `allowed_tools` an der Bindung auf ein reines Such- und Lese-Tool ein, wenn dieser Agent nie schreiben soll.
3. Setzen Sie die Instruktionen unten und klicken Sie dann auf **Publish**.

```text
You answer questions from this organization's Notion workspace.
Search before you answer, and open the page you found before quoting it.
Cite the page's title in your answer, and say plainly if nothing in Notion answers the question.
When asked to add meeting notes to a page, find the exact page first, show the person what you are about to append, and only write it once they confirm.
```

Das Modell erreicht die Tools von Notion unter dem Präfix der Verbindung: `notion_search` und alles andere, was die letzte Prüfung gefunden hat, mit demselben Präfix. Welche Tools es überhaupt gibt, wird beim Prüfen der Verbindung entschieden, nicht von Hand in den Spec geschrieben. Siehe [welche Tools, und wer entscheidet](../mcp.md#which-tools-and-who-decides).

## Ablauf: eine Seite finden und daraus antworten { #workflow-find-a-page-and-answer-from-it }

Stellen Sie in einer neuen Konversation eine Frage, die der Workspace beantworten sollte:

```text
Who owns the Q3 onboarding checklist, and where does it live?
```

Das Modell ruft ein Such-Tool auf, öffnet die Seite, die passend aussieht, und antwortet mit dem Titel der Seite als Quelle. Wenn nichts passt, verlangen die Instruktionen oben, das zu sagen, statt zu raten. Prüfen Sie diese Ablehnung genauso, wie Sie in der eigenen Probe eines Agents mit Wissenssuche eine richtige Antwort prüfen würden.

## Ablauf: Meeting-Notizen anhängen, und ein Mensch entscheidet { #workflow-append-meeting-notes-with-a-person-deciding }

Bei diesem Ablauf lohnt sich Genauigkeit, denn **MCP-Tools haben keine eigene Genehmigung pro Tool**. Der Builder sagt es direkt: *"MCP tools are outside the approval gate entirely: an approval set on a capability does not cover them, so anything these servers can do, this agent can do without asking."* Ein Schreib-Tool, das Sie im Spec benennen können, etwa `execute` oder `send_email`, hat einen Schalter `required`/`never`/`default`. Ein Notion-Schreib-Tool, das beim Verbinden entdeckt wird, bekommt nie einen, weil nichts es im Code deklariert hat. Siehe [was MCP Ihnen nicht gibt](../mcp.md#what-mcp-does-not-get-you).

Die Schranke, die es erreicht, gehört der Konversation selbst. Bevor sie den Agent um einen Schreibvorgang bittet, öffnet die Person, die mit ihm spricht, **Chat controls → Approval mode** und wählt **Ask about everything**. Das ist eine Session-Einstellung, die "reaches further than the spec's gate on purpose, to the tools no capability owns" (siehe [wie oft eine Konversation gefragt werden will](../governance.md#how-much-one-conversation-wants-to-be-asked)). Mit dieser Einstellung:

```text
Append these notes to the Q3 onboarding checklist page: attendees Ana and Marek, decided to move the kickoff to Monday, action item for Marek to update the calendar invite.
```

Das Schreib-Tool parkt jetzt genauso wie `execute` im [CSV-Diagramm-Versuch](csv-chart.md#run-it): Der Chat zeigt **Tool approval required** mit genau der Seite und dem Inhalt, die das Modell senden will, und ein Mensch liest es, bevor er **Approve** wählt. Lassen Sie **Ask about everything** weg, und derselbe Schreibvorgang läuft sofort, ohne etwas zu prüfen. Ein Agent mit einer schreibfähigen Notion-Verbindung wird also nur so gut geprüft, wie es der Modus vorsieht, den die Person im Gespräch in dieser Runde zufällig gewählt hat.

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Eine Frage, die Notion beantwortet | Nennt den Seitentitel als Quelle, und die Antwort stimmt mit dem Inhalt der Seite überein |
| Eine Frage, die nichts im Workspace beantwortet | Sagt das, statt eine plausibel klingende Seite zu erfinden |
| Ein Anhängen mit ausgeschaltetem **Ask about everything** | Läuft sofort; stellen Sie sicher, dass Sie das wollen, bevor es passiert |
| Ein Anhängen mit eingeschaltetem **Ask about everything** | Parkt als **Tool approval required** und zeigt genau Seite und Text |
| Den geparkten Schreibvorgang ablehnen | Die Seite ändert sich nicht, und der Agent kann die Ablehnung weitergeben, statt abzustürzen |
| Jemand ohne persönliche Notion-Verbindung bei einer Bindung an persönliche Konten | Wird aufgefordert, eine zu verbinden, statt aus dem Workspace von jemand anderem eine Antwort zu bekommen |

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Der Agent hat gar keine Notion-Tools.** Die Verbindung wurde nie erfolgreich geprüft. Öffnen Sie **MCP servers**, führen Sie die Prüfung aus und bestätigen Sie, dass eine Tool-Liste erscheint, bevor Sie sie an einen Agent binden.
- **Ein Schreibvorgang läuft, ohne dass jemand ihn prüft.** Prüfen Sie den **Approval mode** der Konversation selbst. `required` an einer Capability erreicht kein MCP-Tool, also braucht eine schreibfähige Verbindung jedes Mal, wenn die Prüfung zählt, die Session-Einstellung **Ask about everything**.
- **Zwei Notion-Verbindungen kollidieren unter einem Namen.** Benennen Sie eine um. Was ein Run tut, wenn er sie nicht unterscheiden kann, beschreibt [Namenskollisionen](../mcp.md#name-collisions).
- **Eine Kollegin bekommt "connect your account" statt einer Antwort.** Bei einer Bindung an persönliche Konten erwartet, bis sie ihr eigenes Notion unter **MCP servers → You** verbindet.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie die Frage und ihre Quelle, den Umfang der Verbindung (Organisation oder persönlich) und den Notion-Workspace, auf den sie zeigt, sowie jeden genehmigten oder abgelehnten Schreibvorgang mit seiner Zielseite auf. Ein Mensch entscheidet weiterhin, wer eine schreibfähige Notion-Verbindung an einen Agent binden darf, und prüft jedes Anhängen, das dieser Modus nicht selbst zur Prüfung geparkt hat.

## Nächste Schritte { #next-steps }

Für dieselbe Prüfungsfrage an einem Projekt-Tracker statt an einem Dokument siehe [Meeting-Aufgaben mit Genehmigung in Tasks umwandeln](meeting-to-tasks.md). Um einzugrenzen, was die Notion-Verbindung einer ganzen Organisation darf, bevor ein Agent sie bindet, siehe [welche Tools, und wer entscheidet](../mcp.md#which-tools-and-who-decides).
