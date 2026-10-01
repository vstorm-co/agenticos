---
source_sha: "e7ffb37fb1d6"
title: "Personenbezogene Daten aus den Prompts und Antworten eines Agents heraushalten"
description: "Konfigurieren Sie die Guardrails-Capability so, dass sie E-Mail-Adressen, Telefonnummern, Kartennummern und Geheimnisse schwärzt, und vergleichen Sie dann, was das Modell tatsächlich erhielt, mit dem, was der Besucher sah."
---

# Personenbezogene Daten aus den Prompts und Antworten eines Agents heraushalten { #keep-personal-data-out-of-an-agents-prompts-and-answers }

Schalten Sie die [Guardrails-Capability](../reference/capabilities.md#guardrails) bei einem kleinen Test-Agent ein und senden Sie ihm synthetische personenbezogene Daten. Gesucht sind zwei verschiedene Texte: was das Transkript des Runs für das Modell zeigt, und was der Run den Anbieter tatsächlich lesen ließ und bezahlte. Dies ist eine Anleitung zum Ausführen, mit einem festgehaltenen Run als Referenz.

## Was Sie brauchen { #what-you-need }

Eine [laufende Installation](../install.md) mit einem Modellprofil. Weder Sandbox noch Embedding-Modell werden gebraucht. Die Capability fügt keine Tools hinzu, also ist in der Toolbox nichts außer **Guardrails** nötig.

## Die Eingabe vorbereiten { #prepare-the-input }

Diesmal keine Datei: Die Eingabe ist die Chat-Nachricht selbst. Verwenden Sie diese Zeile, die von jeder Art personenbezogener Daten, die die Capability erkennt, ein Beispiel enthält:

```text
My email is jane.doe@example.com, my card number is 4111 1111 1111 1111,
my SSN is 123-45-6789, and my phone number is 415-555-0132.
```

Die Referenzfakten: `redact_pii_*` entfernt E-Mail, IBAN, Kreditkarte (mit Luhn-Prüfung), US-SSN und Telefonnummer. Eine Telefonnummer wird gegen den Nummerierungsplan ihres Landes geprüft: Eine mit `+` geschriebene Nummer wird für jedes Land erkannt, eine nationale wie `415-555-0132` nur für die Länder in **phone_regions**, das standardmäßig `US, GB, DE, PL` enthält.

## Den Agent bauen { #build-the-agent }

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
2. Aktivieren Sie in der **Toolbox** **Guardrails**. Es steuert kein Tool bei: Hier gibt es nichts, was ein Mensch genehmigen müsste, nur eine Prüfung von Text.
3. Schalten Sie in der Konfiguration der Capability **Redact API keys and tokens from the user's prompt**, **Redact emails, phone numbers, IBANs, cards and SSNs from the prompt**, **Redact API keys and tokens from the agent's answer** und **Redact emails, phone numbers, IBANs, cards and SSNs from the answer** ein. Lassen Sie **phone_regions** auf dem Standardwert, der `US` enthält. Setzen Sie **Block the run if the prompt contains any of these terms (comma or newline separated)** auf `wire transfer`.
4. Setzen Sie die Instruktionen unten und klicken Sie dann auf **Publish**.

```text
You are a signup-support assistant.
When the user gives you account details, confirm receipt by repeating them back in a bulleted list.
End every answer with a new line reading exactly: Reference key: sk-live-51ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789
```

Den Agent die Angaben wiederholen zu lassen, gibt der Eingabekante etwas zu zeigen: Was das Modell geschwärzt erreicht, kann nur geschwärzt wiederholt werden. Der feste Referenzschlüssel ist da, damit die Ausgabekante etwas Deterministisches abzufangen hat, denn ein Modell zu zwingen, sich ein eigenes Geheimnis auszudenken, ist nicht zuverlässig.

## Ausführen { #run-it }

Senden Sie die Testnachricht in einer neuen Test-Konversation und danach eine zweite, unabhängige Nachricht:

```text
I need to send a wire transfer today, can you help?
```

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Die Antwort | Wiederholt E-Mail, Kartennummer, SSN und Telefonnummer nicht im Klartext |
| Telefonnummer in der Antwort | Fehlt oder wird als `[redacted:phone]` zitiert |
| Die Zeile `Reference key:` in der Antwort | Lautet `Reference key: [redacted:openai_key]`, nicht der echte Wert |
| Das Transkript des Runs (Activity) für den eigenen Zug des Nutzers | Zeigt die ursprüngliche, ungeschwärzte Nachricht, die Sie eingegeben haben, samt Telefonnummer |
| Die Nachricht zur Überweisung | Der Status des Runs ist `guardrail_blocked`, Kosten `0`, und es gibt keine Antwort |
| Dieselbe Nachricht zur Überweisung ohne gesetztes Schlüsselwort | Läuft normal; blockiert wird das Schlüsselwort, nicht das Thema |

Bei der zweiten Zeile der Tabelle lohnt es sich zu verweilen: Die Telefonnummer ist national, also wird sie nur erkannt, weil `US` in **phone_regions** steht. Entfernen Sie `US`, und sie erreicht das Modell genau so, wie sie eingegeben wurde. Die vierte Zeile ist die andere: Eine Person, die Activity liest, um zu sehen, "was passiert ist", sieht die echte Eingabe des Besuchers, weil die Guardrail umschreibt, was das *Modell* liest, nie den gespeicherten Konversationszug.

!!! example "Festgehalten auf v0.0.504, 25. September 2026, vor dem Schwärzen von Telefonnummern"

    Modell: Claude Sonnet 4.6 über OpenRouter. Erste Antwort: *"some of your details were automatically redacted for your security before they reached me, so I was not able to see your email, card number, or SSN"*, gefolgt von `Phone Number: 415-555-0132` unverändert zitiert und `Reference key: [redacted:openai_key]`. Kosten: 0,003 USD. Dieser Run stammt aus der Zeit vor dem Telefon-Detektor ([#1901](https://github.com/vstorm-co/agenticos/issues/1901)); mit ihm erreicht die Nummer das Modell als `[redacted:phone]`.

    Das Transkript des Runs speicherte den Zug des Nutzers als `My email is jane.doe@example.com, my card number is 4111 1111 1111 1111, my SSN is 123-45-6789, and my phone number is 415-555-0132.`, den vollständigen, ursprünglichen, ungeschwärzten Text, während der gespeicherte Zug des Assistenten bereits `[redacted:openai_key]` enthielt.

    Eine weitere Sache zeigte sich nur auf der Leitung: Die `text_delta`-Frames des WebSockets streamten den echten Referenzschlüssel Zeichen für Zeichen, bevor der `final_result`-Frame die ganze Antwort durch die geschwärzte Version ersetzte. Die Schwärzung läuft über die fertige Antwort, nicht über jeden gestreamten Token. `widget.js` überschreibt genau deshalb seinen angezeigten Text mit `final_result.output`, aber ein Client, der nur Deltas anhängt, würde das Geheimnis für ein, zwei Sekunden vor dem Austausch zeigen.

    Die Nachricht zur Überweisung: `error`, *"This request was blocked by an input guardrail."*, ohne `complete`-Frame danach. Der Run hielt den Status `guardrail_blocked`, `0` Eingabe- und Ausgabe-Tokens und Kosten `0.000000` fest.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Ein Wert, der geschwärzt werden sollte, kommt unverändert durch.** Prüfen Sie ihn gegen die fünf Detektoren: E-Mail, IBAN, Kreditkarte (mit Prüfsumme), US-SSN und Telefonnummer. Eine nationale Telefonnummer braucht ihr Land in **phone_regions**, und eine Nummer, die im Nummerierungsplan ihres Landes nicht gültig ist, bleibt unverändert. Eine Anschrift oder ein Name sind nicht abgedeckt; das ist eine Musterschicht, kein Modell, das versteht, was personenbezogene Daten sind.
- **Ein streamender Client zeigt kurz ein Geheimnis.** Die Schwärzung der Ausgabe läuft über die fertige Antwort, nachdem die `text_delta`-Frames schon hinausgegangen sind. Zeigen Sie den Text aus `final_result` an, wie `widget.js` es tut, statt nur Deltas anzuhängen. Das Puffern der Antwort bei eingeschalteter Ausgabeprüfung wird in [#1900](https://github.com/vstorm-co/agenticos/issues/1900) verfolgt.
- **Die Blockierung hat nicht ausgelöst.** `blocked_keywords_*` sucht einen wörtlichen Teilstring ohne Beachtung der Groß- und Kleinschreibung. Eine Blockierung braucht außerdem den eigenen Schalter der Kante: Eine Schlüsselwortliste an der Ausgabekante bewirkt an der Eingabe nichts.
- **Das Transkript zeigt weiterhin den Rohwert.** An der Eingabekante ist das erwartet: Umgeschrieben wird nur, was das Modell erreicht, nicht der gespeicherte Zug, den ein Mensch später liest. Schwärzen vor dem Speichern ist eine andere Funktion als diese.
- **Ein Run zeigt ein `guardrail_blocked`, das Sie nicht beabsichtigt haben.** Lesen Sie das Feld `error` des Runs. Es nennt die Kante (`input`, `output` oder `tool_result`), aber absichtlich nie den gefundenen Text, also prüfen Sie die Schlüsselwortliste selbst.
- **Die Prüfung von Tool-Ergebnissen wirkt ungenutzt.** Sie zählt erst, wenn ein Agent ein Tool hat, das nicht vertrauenswürdige Inhalte liest: eine abgerufene Seite, eine Datei, eine MCP-Antwort. Dieser Versuch hat keines, also war diese Kante konfiguriert, wurde aber nie genutzt.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie die genaue Nachricht, die Agent-Version, welche Kanten und Schlüsselwörter konfiguriert waren, das Transkript des Runs für beide Züge sowie `status` und Kosten des Runs aus Activity auf. Ein Mensch entscheidet, ob diese fünf Detektoren für einen bestimmten Agent reichen, welche Länder in seine **phone_regions** gehören und ob die Prüfung von Tool-Ergebnissen eingeschaltet sein muss, bevor ein Tool hinzukommt, das die Außenwelt liest.

## Nächste Schritte { #next-steps }

Die [Guardrails-Referenz](../reference/capabilities.md#guardrails) listet die genauen Muster und die drei Kanten in einer Tabelle. Wenn der Agent irgendetwas von außen Abgerufenes liest, etwa eine Webseite, einen MCP-Server oder eine hochgeladene Datei, schalten Sie die Kante für Tool-Ergebnisse ein, bevor diese Capability in Betrieb geht, nicht danach.
