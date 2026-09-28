---
source_sha: "9d46f3e89ce9"
title: "Dokumente mit Ihrer Terminologie übersetzen"
description: "Binden Sie ein Glossar mit zehn Begriffen an einen Agent und prüfen Sie, dass jeder Begriff angewendet wird, nicht zu übersetzende Begriffe und Zahlen erhalten bleiben und eine Mehrdeutigkeit markiert statt still aufgelöst wird."
---

# Dokumente mit Ihrer Terminologie übersetzen { #translate-documents-with-your-terminology }

Geben Sie einem Agent ein kurzes englisches Dokument und einen Skill mit Ihrem Glossar, und lassen Sie ihn in eine andere Sprache übersetzen, wobei Produktnamen, Funktionsnamen und andere nicht zu übersetzende Begriffe auf Englisch bleiben. Das Beispiel enthält ein wirklich mehrdeutiges Datum, damit Sie prüfen können, ob der Agent es markiert, statt still zu raten. Dies ist eine Anleitung zum Ausführen, mit einem festgehaltenen Run als Referenz.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil.
- Keine Sandbox und kein Embedding-Modell. Dieser Agent braucht nur die [Skills-Capability](../reference/capabilities.md#skills) und einen Chat-Anhang.

## Die Eingabe vorbereiten { #prepare-the-input }

Speichern Sie dies als Skill unter **Skills → New skill**. Nennen Sie ihn `fenwick-glossary` und geben Sie eine Beschreibung wie "Which terms in a Fenwick Ledger document stay in English, and the preferred Polish translation for the rest." an. Fenwick Ledger ist ein synthetisches Buchhaltungsprodukt, das für diesen Test erfunden wurde.

```text
Fenwick Ledger is a synthetic accounting product used only for this test.

## Keep in English, never translate

- Fenwick Ledger (product name)
- Quick Close (feature name)
- workspace
- API key
- sandbox

## Translate using these terms

| English | Polish |
|---|---|
| ledger | księga |
| invoice | faktura |
| reconciliation | uzgadnianie |
| dashboard | pulpit |
| audit trail | ślad audytu |

Numbers, dates and currency amounts are copied exactly as they appear in the
source — do not reformat a date or convert a currency. If a sentence in the
source could be read two ways, translate the more likely reading and add one
line after the translation flagging the ambiguity and both readings.
```

Speichern Sie dann dieses synthetische Dokument als `release-notes.md`. Das Datum `03/04/2026` ist absichtlich mehrdeutig zwischen Lesart Tag zuerst und Monat zuerst. Genau diesen Fall soll das Beispiel prüfen.

```text
Fenwick Ledger 4.2 release notes

This release adds Quick Close, a one-click way to close the monthly ledger
once every invoice is matched. Quick Close runs the reconciliation for the
current period and shows the results on the dashboard.

Every action Quick Close takes is written to the audit trail, so a
controller can see which invoices were matched automatically and which
needed a manual review.

To use Quick Close in a shared workspace, generate an API key from Settings
and add it to your sandbox environment before running your first close.

The reconciliation step handles invoices up to EUR 50,000 automatically;
anything above that amount is queued for manual approval.

Close the March books by 03/04/2026, before the quarterly audit begins.

Fenwick Ledger is a synthetic product created for this test; no real company
or software is described here.
```

## Den Agent bauen { #build-the-agent }

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
2. Aktivieren Sie in der **Toolbox** **Skills** und binden Sie den Skill `fenwick-glossary`.
3. Setzen Sie die Instruktionen unten und klicken Sie dann auf **Publish**.

```text
You translate documents into Polish.
Follow the bound glossary skill: never translate the terms it lists as
English-only, and use its preferred Polish translation for the rest.
Copy every number, date and currency amount exactly as it appears in the
source.
If a sentence could be read two ways, translate the more likely reading and
add one line after the translation flagging the ambiguity and both readings.
```

## Ausführen { #run-it }

Öffnen Sie einen neuen Chat mit dem Agent, hängen Sie `release-notes.md` an und senden Sie:

```text
Translate the attached release notes into Polish.
```

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Fünf Glossarbegriffe übersetzt | ledger→księga, invoice→faktura, reconciliation→uzgadnianie, dashboard→pulpit, audit trail→ślad audytu |
| Fünf nicht zu übersetzende Begriffe erhalten | Fenwick Ledger, Quick Close, workspace, API key, sandbox erscheinen alle auf Englisch |
| Geldbetrag unverändert | `EUR 50,000` erscheint genau so, weder umgerechnet noch umformatiert |
| Datum unverändert | `03/04/2026` erscheint genau so, nicht in ein polnisches Datumsformat umgeschrieben |
| Mehrdeutigkeit markiert | Ein eigener Hinweis nennt beide Lesarten von `03/04/2026` |
| Dieselbe Anfrage ohne angehängte Datei | Der Agent fragt nach dem Dokument, statt nichts zu übersetzen |

Lesen Sie den polnischen Text Begriff für Begriff gegen das Glossar. Verlassen Sie sich nicht auf eine Zusammenfassung, die nur die gefundenen Begriffe auflistet.

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter. Der Agent rief `load_capability` für `fenwick-glossary` auf und übersetzte dann das ganze Dokument in einer Antwort. Alle fünf Glossarbegriffe wurden korrekt übersetzt, und alle fünf nicht zu übersetzenden Begriffe, einschließlich `workspace`, `API key` und `sandbox` in polnischen Sätzen, blieben auf Englisch. `EUR 50,000` und `03/04/2026` wurden unverändert übernommen. Kosten: 0,017 USD.

    Nach der Übersetzung fügte der Agent einen markierten Hinweis hinzu: In der Lesart Tag zuerst ist 03/04/2026 der 3. April 2026 (in der Übersetzung verwendet), in der Lesart Monat zuerst der 4. März 2026. Er empfahl zu bestätigen, welches gemeint war. Ohne angehängte Datei lud er das Glossar und fragte dann nach dem Dokument, statt nichts zu übersetzen.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Ein nicht zu übersetzender Begriff wird trotzdem übersetzt.** Das Modell behandelt ihn vielleicht als gewöhnliches Vokabular statt als Eigennamen. Stellen Sie die Liste an den Anfang des Skill-Inhalts und wiederholen Sie die Anweisung in den eigenen Instruktionen des Agents.
- **Eine Zahl ändert sich.** Bitten Sie den Agent, den Quellsatz neben seiner Übersetzung zu zitieren. Eine Abweichung ist dann sofort sichtbar.
- **Die Mehrdeutigkeit wird still aufgelöst.** Verschärfen Sie die Instruktionen, sodass eine eigene Markierungszeile verlangt wird, statt die Wahl der Standardformulierung des Skills zu überlassen.
- **Der Agent übersetzt ohne angehängte Datei.** Verschärfen Sie die Instruktionen, sodass er ablehnen muss, wenn kein Dokument vorhanden ist.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie das Quelldokument, den Glossar-Inhalt, die Übersetzung, die Agent-Version und den Run in Activity auf. Eine Person, die die Zielsprache liest, prüft weiterhin den Fluss der Übersetzung und bestätigt, welche Lesart einer markierten Mehrdeutigkeit tatsächlich gemeint war. Das Glossar und die Prüfungen oben erkennen Terminologie und erhaltene Werte, nicht, ob der Satz natürlich klingt.

## Nächste Schritte { #next-steps }

Halten Sie ein produktives Glossar in einem Skill pro Sprachpaar statt in einem Skill mit allen Sprachen gemischt, damit eine Übersetzerin nur ihr Paar prüfen und bearbeiten kann. Der [DeepL-Eintrag](../mcp.md#automation-storage-productivity-media) im MCP-Katalog ist eine alternative Übersetzungs-Engine, die Sie statt des Modells direkt anbinden können. Diese Seite nutzt ihn nicht.
