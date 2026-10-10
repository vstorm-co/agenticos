---
source_sha: "58528fa9516e"
title: "Sich vor einem Anruf über ein Unternehmen informieren"
description: "Recherchieren Sie eine öffentliche Organisation mit Websuche und Web-Abruf und erhalten Sie ein einseitiges Briefing, in dem jede Tatsache ihre Quelle und ihr Datum trägt."
---

# Sich vor einem Anruf über ein Unternehmen informieren { #brief-yourself-on-a-company-before-a-call }

Bauen Sie einen Agent, der eine Organisation recherchiert und vor einem Anruf ein einseitiges Briefing schreibt: was sie tut, aktuelle Nachrichten, die derzeitige Leitung und was sich nicht bestätigen ließ. Als Beispiel dient eine bekannte Open-Source-Stiftung, sodass Sie das Briefing mit Quellen prüfen können, die jeder öffnen kann. Dies ist eine Anleitung zum Ausführen, mit einem festgehaltenen Run als Referenz.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil.
- Websuche: Die Standardmethode ist DuckDuckGo und braucht weder Konto noch Schlüssel.
- Keine Wissenssammlung, keine Sandbox und keine MCP-Verbindung.

## Den Agent bauen { #build-the-agent }

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
2. Aktivieren Sie in der **Toolbox** **Web search** (Methode DuckDuckGo) und **Read web pages**.
3. Legen Sie Budget und Schrittlimit für den Versuch fest. Der festgehaltene Run nutzte 20 Schritte und kostete etwa 0,26 USD.
4. Setzen Sie die Instruktionen unten und klicken Sie dann auf **Publish**.

```text
You write a one-page brief on an organization before a call with them.
Research it with web search and web fetch before writing anything.

Rules:

- Every fact in the brief carries the source URL it came from, next to the
  fact, not collected in a list at the end.
- Next to each fact, name the date: either the date the source page itself
  states (an article date, a filing date) or, when the source carries none,
  the date you fetched it, marked as "(fetched)".
- Never state a person's name, title or any personal detail unless a source
  confirms it. If you cannot confirm who currently holds a role, say so
  instead of guessing, and do not use a plausible-sounding name.
- Do not repeat a home address, personal phone number or other private
  contact detail even if a source shows one. The brief covers the
  organization, not the people in it.
- End with a section called "Could not confirm" naming anything you looked
  for but did not find a source for. An empty section still gets the heading,
  with one line saying nothing was left unconfirmed.
```

## Ausführen { #run-it }

Öffnen Sie einen neuen Chat mit dem Agent und senden Sie:

```text
Brief me on the Python Software Foundation before a call with them.
```

Jede bekannte öffentliche Organisation funktioniert genauso. Eine große Open-Source-Stiftung ist eine gute Voreinstellung, weil ihre Finanzen, ihr Vorstand und ihre Mission veröffentlicht und stabil genug zum Prüfen sind.

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Jede Tatsachenbehauptung | Hat eine Quell-URL direkt daneben |
| Das Datum jeder Behauptung | Nennt das eigene Datum der Quelle oder "(fetched)", wenn die Quelle keines hat |
| Genannte Personen | Nur solche, die eine Quelle bestätigt, belegt mit der eigenen Seite der Organisation statt geraten |
| Eine Rolle, die niemand bestätigen konnte | Sagt das offen, statt eine plausible Person zu nennen |
| Private Kontaktdaten | Fehlen, auch wenn eine Quelle welche zeigte |
| Abschnitt "Could not confirm" | Vorhanden und nennt eine echte Lücke, nicht leer durch Weglassen |
| Dieselbe Frage zu einer Organisation mit fast keiner öffentlichen Präsenz | Sagt das und liefert ein kurzes, ehrlich dünnes Briefing, statt Details zu erfinden, um die Seite zu füllen |

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter. Der Agent führte drei `web_search`-Aufrufe aus, dann `web_fetch` auf den eigenen Seiten der PSF zu Organisation, Vorstand und Jahresbericht 2024, außerdem auf einem Beitrag zum Förderprogramm und einem Aggregator für Form-990-Einreichungen. Ein `web_fetch` (eine Seite mit Einreichungen) schlug fehl und wurde für diese Tatsache nicht mit einer anderen Quelle wiederholt.

    Das Briefing nannte bei jeder Behauptung eine Quelle: Mission, Programme, Finanzen des Geschäftsjahres 2024, die Fördersumme 2024 und die vollständige Vorstandsliste, jeweils datiert nach der Quelle oder mit "(fetched)" markiert. Den Vorstand nannte es nur nach der eigenen Vorstandsseite der PSF. Den Namen der am höchsten vergüteten Person aus einem Suchausschnitt zu einem Form 990 nannte es ausdrücklich nicht, weil die Einreichung selbst nicht direkt erreichbar war. Diese Lücke, die genaue Aufschlüsselung der Einnahmen und die Termine der nächsten PyCon führte es unter "Could not confirm" auf. Kosten: 0,26 USD.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Eine Person wird ohne Quelle daneben genannt.** Verschärfen Sie die Instruktionen so, dass die Quelle an der Stelle der Behauptung verlangt wird, nicht nur irgendwo in der Antwort. Ein Modell, das einen Namen nebenbei bei einer anderen Recherche gelesen hat, kann ihn ungewollt wiederholen.
- **Das Briefing hat keinen Abschnitt "Could not confirm".** Die Instruktionen wurden nicht befolgt, oder es wurde nach nichts gesucht, das plausibel fehlen könnte. Prüfen Sie die Tool-Aufrufe im Transkript, bevor Sie einem Briefing vertrauen, das alles gefunden hat.
- **Ein `web_fetch` schlägt fehl, und die Tatsache verschwindet einfach.** Das Modell ging weiter, statt eine zweite Quelle zu versuchen. Bitten Sie es, zu nennen, was es nicht abrufen konnte. Genau so sah die Form-990-Lücke im festgehaltenen Run aus.
- **Finanz- oder Leitungsangaben wirken aktuell, sind aber ein Jahr alt.** Prüfen Sie das Datum neben jeder Angabe. Eine Seite ohne Veröffentlichungsdatum mit angehängtem Abrufdatum ist nicht dieselbe Behauptung wie eine, die nach der Quelle datiert ist.
- **Dieselbe Organisation hat bei einem erneuten Run einen anderen Vorstand.** Suchergebnisse sind zwischen Runs nicht stabil. Prüfen Sie, von welcher Seite jeder Name stammt, bevor Sie einer Version vertrauen, und ziehen Sie die eigene Seite der Organisation einem Suchausschnitt vor.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie die Frage, das Briefing, die zitierten Quellen, den Run in Activity mit seinen Tool-Aufrufen und die Kosten auf. Ein Mensch liest das Briefing vor dem Anruf weiterhin gegen seine Quellen, entscheidet, ob eine "could not confirm"-Lücke wichtig genug ist, um sie von Hand nachzuschlagen, und wiederholt nie ein unbestätigtes persönliches Detail, auch wenn ein späterer Run es selbstsicher nennt.
