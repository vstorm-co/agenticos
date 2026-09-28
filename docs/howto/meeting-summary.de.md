---
source_sha: "1d2ade73a284"
title: "Ein Meeting-Transkript in Entscheidungen und Aufgaben zusammenfassen"
description: "Fügen Sie ein kurzes synthetisches Transkript ein und prüfen Sie, dass der Agent Entscheidungen von Aufgaben trennt, für jede einen Verantwortlichen und ein Datum nennt und die eine Aufgabe markiert, die niemand übernommen hat."
---

# Ein Meeting-Transkript in Entscheidungen und Aufgaben zusammenfassen { #summarise-a-meeting-transcript-into-decisions-and-action-items }

Bauen Sie einen Agent, der ein eingefügtes Transkript in drei kurze Listen verwandelt: Entscheidungen, Aufgaben mit Verantwortlichem und Fälligkeitsdatum sowie offene Fragen. Im Beispieltranskript gibt es eine Aufgabe, die zur Sprache kommt, die aber niemand tatsächlich übernehmen will. Die wichtigste Prüfung ist, ob der Agent das ehrlich meldet, statt sie der Person zuzuweisen, die in der Nähe erwähnt wird. Dies ist eine Anleitung zum Ausführen, mit einem festgehaltenen Run als Referenz.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil.
- Keine Capability. Dieser Agent liest, was in der Nachricht steht, und sonst nichts.

## Die Eingabe vorbereiten { #prepare-the-input }

Ein kurzes, synthetisches Transkript, für diese Seite erfunden:

```text
Onboarding revamp sync — 12 March, 10:00–10:35
Jenna: Let's get through this quickly. Marcus, where are we with the signup
API changes?
Marcus: Mostly done. I can have the new field validation live by March 20.
Jenna: Good. Priya, the tooltip designs?
Priya: Almost there. I can deliver the final set by March 18, in time for
Marcus to wire them up.
Jenna: Great. Let's also decide on the survey step. Tomas, you said support
tickets show people dropping off there.
Tomas: Right, about a third of drop-offs happen on the survey screen. My
recommendation is to remove it entirely rather than shorten it.
Jenna: Agreed, let's remove the survey step from onboarding. Marcus, can you
fold that into the same API change?
Marcus: Yes, same PR.
Jenna: Decision made — the survey step is gone. Now, should the new tooltip
flow go to everyone at once, or beta first?
Priya: Beta first. We haven't tested it on mobile yet.
Marcus: Agreed, mobile rendering is still rough.
Jenna: Okay, decision: new tooltip flow ships to beta users first, general
release after that's clean.
Tomas: One more thing — the help center article on "how onboarding works"
is now out of date once the survey step is gone. Somebody should update it
before we ship.
Jenna: Good catch. Let's make sure that happens.
Priya: I can't take that on, I'm full up with the tooltip work through the
20th.
Marcus: Not mine either, that's not engineering's article.
Jenna: Okay, let's flag it and figure out who owns docs later this week.
Tomas: Compiling the onboarding-related support tickets into a report —
I'll do that, but I don't have a firm date yet, depends on how much backlog
I need to dig through.
Jenna: That's fine, just get it to us when it's ready.
Jenna: Last open question — do we sunset the old onboarding flow entirely,
or keep it behind a flag as a fallback for a few weeks?
Marcus: I'd lean toward keeping the flag, in case the new flow breaks
something we didn't catch in beta.
Priya: I don't have a strong opinion either way.
Jenna: Let's leave that open and revisit once beta feedback comes in.
Jenna: Okay, I think that's everything. Thanks all.
```

Die Referenz: zwei Entscheidungen (den Umfrageschritt streichen; den Tooltip-Ablauf zuerst in die Beta bringen), vier Aufgaben mit Verantwortlichem, eine Aufgabe, nämlich die Aktualisierung des Hilfecenter-Artikels, die Priya und Marcus beide ausdrücklich ablehnen, und eine offene Frage, die für später bleibt.

## Den Agent bauen { #build-the-agent }

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
2. Lassen Sie die Toolbox leer. Hier braucht nichts ein Tool.
3. Legen Sie Budget und Schrittlimit für den Versuch fest.
4. Setzen Sie die Instruktionen unten und klicken Sie dann auf **Publish**.

```text
You turn a pasted meeting transcript into three sections: Decisions,
Action items, and Open questions.

For each action item, name the owner and the due date exactly as stated. If
a task is mentioned but nobody agreed to own it, list it under Action items
as unassigned and say so - never guess an owner, and never assign it to
someone who explicitly declined it in the transcript.

List a topic under Open questions only if the transcript does not record a
decision on it. Do not invent a decision, an owner, or a date the transcript
does not state.
```

## Ausführen { #run-it }

Fügen Sie das Transkript nach einer kurzen Anweisung direkt in eine neue Konversation ein:

```text
Summarise this meeting transcript into decisions, action items and open questions.

[paste the transcript]
```

Es als Textdatei anzuhängen funktioniert genauso: Ein Agent ohne Workspace bekommt den Text eines Uploads in den Prompt eingefügt, genau wie beim Einfügen. Siehe [Dateiverarbeitung](../file-processing.md#chat-file-uploads).

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Entscheidungen | Den Umfrageschritt streichen; den Tooltip-Ablauf zuerst in die Beta bringen |
| Aufgaben von Marcus | Feldvalidierung und das Entfernen des Umfrageschritts, fällig am 20. März |
| Aufgabe von Priya | Endgültige Tooltip-Designs, fällig am 18. März |
| Aufgabe von Tomas | Zusammenstellung des Berichts über Support-Tickets, ohne erfundenes Datum |
| Der Hilfecenter-Artikel | Als nicht zugewiesen aufgeführt, nicht Priya oder Marcus gegeben |
| Offene Fragen | Nur die Frage Abschaltung oder Fallback, keine als Frage wiederholte Entscheidung |

Prüfen Sie zuerst die nicht zugewiesene Aufgabe. Ein Agent, der sie still der Person gibt, deren Name im Transkript am nächsten steht, hat die eine Prüfung verfehlt, für die es diese Seite gibt, auch wenn jede andere Zeile stimmt.

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter. Keine Tool-Aufrufe: Die ganze Antwort kam aus einer Modellanfrage, für 0,0063 USD. Sie nannte beide Entscheidungen, gab Marcus zwei Positionen (Feldvalidierung und das Entfernen des Umfrageschritts, beide 20. März), Priya die Tooltip-Designs zum 18. März und Tomas den Bericht mit "no firm date — to be delivered when ready". Der Hilfecenter-Artikel stand als **"Unassigned (Priya and Marcus both declined; owner to be determined later this week)"** in der Liste, statt einem der beiden zugewiesen zu werden. Die eine offene Frage war die Entscheidung zwischen Abschaltung und Fallback, als zurückgestellt markiert.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Die nicht übernommene Aufgabe wird trotzdem zugewiesen.** Das ist der Fehler, auf den Sie achten müssen. Verschärfen Sie die Instruktionen weiter. Die genaue Formulierung "declined" oder "unassigned" zu nennen, hilft manchmal weniger als ein zweites Transkript, in dem sich dasselbe Muster wiederholt, um zu sehen, ob das erste Ergebnis Glück war.
- **Ein Fälligkeitsdatum erscheint, das niemand genannt hat.** Das Modell hat eine Lücke gefüllt, weil eine Aufgabe ohne Datum unvollständig wirkt. Prüfen Sie, ob die letzte Zeile der Instruktionen ihre Arbeit tut, und testen Sie mit einem Transkript, das mehr als eine Aufgabe ohne Datum enthält.
- **Eine offene Frage wiederholt etwas, das schon entschieden ist.** Das Modell hat eine unter Druck, spät im Meeting getroffene Entscheidung als noch offen behandelt. Verweisen Sie es auf die genaue Zeile, in der die Entscheidung fiel.
- **Die drei Abschnitte verschwimmen.** Bitten Sie bei einem längeren, unordentlicheren Transkript um die Abschnitte in fester Reihenfolge und prüfen Sie, dass jeder nur enthält, was hineingehört.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie das Transkript, den genauen Prompt, die Agent-Version, das Modell und die Antwort auf. Ein Mensch prüft die nicht zugewiesene Aufgabe weiterhin direkt am Transkript. Genau solche kleinen, leicht übersehenen Details entgehen beim schnellen Lesen einer langen Zusammenfassung.

## Nächste Schritte { #next-steps }

Jede Aufgabe in einen tatsächlich verfolgten Task mit benachrichtigtem Verantwortlichen zu verwandeln, ist ein eigener Schritt, beschrieben unter [Meeting-Aufgaben mit Genehmigung in Tasks umwandeln](meeting-to-tasks.md). Diese Seite endet bei der Zusammenfassung, die ein Mensch liest und prüft.
