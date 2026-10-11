---
source_sha: "54d365e1b9c3"
title: "Einen persönlichen Assistenten bauen, der sich an Sie erinnert"
description: "Geben Sie einem Agent ein Gedächtnis für Ihre Vorlieben, prüfen Sie, dass eine spätere Konversation sie anwendet, und bestätigen Sie dann, dass er eine auf Wunsch vergessen kann."
---

# Einen persönlichen Assistenten bauen, der sich an Sie erinnert { #build-a-personal-assistant-that-remembers-you }

Bauen Sie einen Assistenten, der über Konversationen hinweg eigene Notizen über die Person führt, mit der er spricht, ohne etwas zu verbinden und ohne externes Konto. Nennen Sie ein paar synthetische Vorlieben, öffnen Sie eine neue Konversation und prüfen Sie, ob der Assistent sie nutzt, und bitten Sie ihn dann, eine davon zu vergessen. Dies ist eine Anleitung zum Ausführen, mit einem festgehaltenen Run als Referenz.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil.
- Keine Sandbox, kein Embedding-Modell und keine MCP-Verbindung. [Memory files](../reference/capabilities.md#memory-files) funktionieren ohne jede Bindung.

## Die Eingabe vorbereiten { #prepare-the-input }

Das sind erfundene Fakten über eine fiktive Person, klein genug, um sie mit den Antworten des Assistenten abzugleichen:

```text
Timezone: Europe/Warsaw
Meeting-free day: Friday
Summary format: short bullet points, not paragraphs
```

## Den Agent bauen { #build-the-agent }

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
2. Aktivieren Sie in der **Toolbox** **Memory files**, **Date and time** und **Conversation search**. Fügen Sie **Web search** hinzu, wenn das Briefing unten etwas nachschlagen soll; die Prüfungen hier brauchen es nicht.
3. Legen Sie Budget und Schrittlimit für den Versuch fest. Die festgehaltenen Runs nutzten 5–15 Schritte und kosteten jeweils etwa 0,01–0,04 USD.
4. Setzen Sie die Instruktionen unten und klicken Sie dann auf **Publish**.

```text
You are a personal assistant that remembers what this person tells you about themselves.
When the person states a preference or a standing fact (timezone, working hours, meeting-free days, how they like summaries formatted), save it with write_memory under a short name, then read MEMORY.md and add or update a one-line entry for it with edit_memory (or write_memory if MEMORY.md does not exist yet).
When asked for a plan, a summary or a morning brief, apply every preference currently in your notes: check MEMORY.md, read any note it lists that is relevant, and follow it without being asked again.
When asked to forget something, delete the matching note with delete_memory, remove its line from MEMORY.md with edit_memory, and confirm in one sentence what you forgot.
Never save something the person has not actually told you.
```

`write_memory`, `edit_memory` und `delete_memory` haben Seiteneffekte, daher parkt jedes Speichern oder Vergessen standardmäßig als **Tool approval required**, wie jeder andere Schreibvorgang. Genehmigen Sie es, um fortzufahren.

## Ausführen { #run-it }

**Konversation 1**: die Vorlieben nennen.

```text
A few things about me: I'm in the Europe/Warsaw timezone, I keep Fridays meeting-free, and I prefer summaries as short bullet points rather than paragraphs.
```

**Konversation 2**: eine neue Konversation mit demselben Agent, mit der Bitte, das Gelernte zu nutzen.

```text
Give me a plan for tomorrow. I have three things to fit in: a client call, writing a proposal, and a team sync.
```

**Konversation 3**: ihn bitten, eine der drei zu vergessen.

```text
Forget my meeting-free Fridays preference.
```

Ein Zeitplan kann die Instruktionen dieses Agents lesen, aber nicht die Notizen seines Eigentümers. Lesen Sie [was ein Zeitplan nicht lesen kann](#what-a-schedule-cannot-read), bevor Sie ein Morgen-Briefing an einen hängen.

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Antwort in Konversation 1 | Bestätigt alle drei Vorlieben, nachdem drei `write_memory`-Aufrufe und einer, der `MEMORY.md` schreibt, genehmigt wurden |
| `MEMORY.md` nach Konversation 1 | Listet `timezone`, `meeting_free_days` und `summary_format` |
| Der Plan aus Konversation 2 | Nutzt Europe/Warsaw, besteht überwiegend aus Aufzählungspunkten und wendet die Freitagsregel nicht fälschlich auf einen Tag an, der kein Freitag ist |
| Antwort in Konversation 3 | Nennt in einem Satz, was er vergessen hat |
| Settings → Memory (oder `GET /memory/mine`) nach Konversation 3 | `meeting_free_days` ist vollständig verschwunden; die anderen beiden Notizen sind unverändert |
| **Run now** eines Morgen-Briefing-Zeitplans, bevor ihm im Chat etwas gesagt wurde | Sagt, dass nichts hinterlegt ist, statt zu raten; siehe unten |

Öffnen Sie Activity für jeden Run und prüfen Sie die Tool-Aufrufe, nicht nur die Antwort: Ein `write_memory`, das das Modell aufgerufen, aber niemand genehmigt hat, hat nie stattgefunden.

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter. Konversation 1 rief `write_memory` dreimal auf und schrieb nach der Genehmigung `MEMORY.md` als `- timezone [preference] — …`, `- meeting_free_days [preference] — …`, `- summary_format [preference] — …`. Kosten: 0,039 USD.

    Konversation 2 rief `read_memory` für alle drei Notizen und `search_conversations` auf (das korrekterweise nichts fand, weil über morgen noch nichts gesagt worden war) und antwortete dann mit einem Plan in Aufzählungspunkten in Europe/Warsaw-Zeit. Sie wies darauf hin, dass morgen Samstag ist, die Regel für besprechungsfreie Tage also nicht gilt. Kosten: 0,026 USD.

    Konversation 3 rief `delete_memory` für `meeting_free_days` auf, nach der Genehmigung `read_memory` und `edit_memory` auf `MEMORY.md`, um dessen Zeile zu entfernen, und antwortete "Done — I've forgotten your meeting-free Fridays preference and removed it from my index." `GET /memory/mine` listete danach nur noch `timezone` und `summary_format`. Kosten: 0,043 USD.

## Was ein Zeitplan nicht lesen kann { #what-a-schedule-cannot-read }

Eine Auslösung durch einen Zeitplan oder einen Ereignis-Trigger läuft mit der Rolle und den Grants des Erstellers, ist für das Gedächtnis aber niemandes Konversation: `list_memory` bei einem **Run now** eines Morgen-Briefing-Zeitplans antwortete "This conversation has no memory. It has no identified person and is not a group chat, so a note would have to land somewhere other people read". Das ist dieselbe Ablehnung, die ein anonymer Widget-Besucher bekommt, obwohl der Ersteller des Zeitplans ein echtes, bekanntes Mitglied ist.

Braucht ein geplantes Briefing eine Vorliebe, nennen Sie sie im Prompt des Zeitplans selbst, so wie [ein geplanter Bericht](scheduled-report.md) seine Daten in der Nachricht angibt, statt sich auf das Gedächtnis oder eine Datei zu verlassen, die niemand erneut liefert.

## Wer das lesen kann { #who-can-read-this }

Niemand liest Ihre Notizen aufgrund seiner Rolle in der Organisation, weder ein Owner noch ein Admin noch jemand mit Bearbeitungsrecht an diesem Agent. Ihre eigenen erreichen Sie unter **Settings → Memory** (`GET /memory/mine`), wo Sie eine Notiz nicht mehr verwenden, wieder verwenden oder ganz löschen können. "Nicht mehr verwenden" lässt sie für Sie auf der Seite, während sie kein Modell mehr erreicht. Nur ein Administrator der Bereitstellung kann die Notizen einer anderen Person lesen, eine Person nach der anderen, und dieser Zugriff wird mit handelnder Person, betroffener Person und Grund im Audit-Trail festgehalten, nie mit dem Inhalt. Siehe [wessen Notizen, und wer sie hören darf](../reference/capabilities.md#whose-notes-and-who-may-hear-them) und [lesen und löschen](../reference/capabilities.md#reading-it-and-erasing-it).

In einem Gruppenchat ändert sich die Regel: Die Notizen gehören dem Raum, und alle darin lesen sie, und nichts, was dem Assistenten allein gesagt wurde, wird dort wiedergegeben. Dieser Versuch nutzte nur den Web-Chat unter vier Augen, wo der Speicher allein Ihnen gehört.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Ein Speichern oder Vergessen passiert nie.** `write_memory`, `edit_memory` und `delete_memory` haben Seiteneffekte und sind standardmäßig geschützt. Prüfen Sie **Approvals** in Activity auf einen geparkten Aufruf, bevor Sie annehmen, das Modell habe die Anweisung ignoriert.
- **Eine spätere Konversation kennt eine gespeicherte Vorliebe nicht.** Prüfen Sie `MEMORY.md` selbst. Eine gespeicherte, aber nicht indexierte Notiz ist unsichtbar, bis das Modell `list_memory` aufruft, was ein leichteres Modell ungefragt vielleicht nicht tut.
- **Ein geplantes Briefing rät, statt Ihre Notizen zu nutzen.** Erwartet; siehe oben [was ein Zeitplan nicht lesen kann](#what-a-schedule-cannot-read). Schreiben Sie die Tatsache in den Prompt des Zeitplans.
- **Das Löschen einer Notiz entfernt sie nicht überall.** `delete_memory` entfernt die Notiz selbst. Wird die Zeile in `MEMORY.md`, die sie nennt, nicht auch per `edit_memory` umgeschrieben, beschreibt der Index weiter etwas, das es nicht mehr gibt.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie jede Konversation, die Agent-Version, welche `write_memory`/`delete_memory`-Aufrufe genehmigt wurden, und `GET /memory/mine` vor und nach der Bitte ums Vergessen auf. Ein Mensch genehmigt weiterhin jedes Speichern und Löschen, entscheidet, ob **Allow personal memory** für diesen Agent eingeschaltet bleibt, und beurteilt, ob ein Plan tatsächlich widerspiegelt, was gesagt wurde. Der Assistent prüft sich nicht selbst.

## Nächste Schritte { #next-steps }

Um diesen Assistenten über einen Zeitplan statt über den Web-Chat zu erreichen, lesen Sie zuerst [was ein Zeitplan nicht lesen kann](#what-a-schedule-cannot-read) und dann [Einen Wochenbericht planen](scheduled-report.md) für die Mechanik eines Rhythmus und einer Run-Log-Konversation. Damit er durchsuchen kann, was in früheren Konversationen tatsächlich gesagt wurde, statt nur, was er selbst zu speichern beschloss, siehe [Konversationssuche](../reference/capabilities.md#conversation-search).
