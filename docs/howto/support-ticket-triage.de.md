---
source_sha: "9121fc5ca757"
title: "Eingehende Support-Anfragen aus Ihrer eigenen App triagieren"
description: "Lösen Sie einen Agent aus Ihrem eigenen Backend mit einem signierten Webhook aus und lassen Sie ihn klassifizieren, eine Antwort entwerfen und Sicherheitsmeldungen markieren."
---

# Eingehende Support-Anfragen aus Ihrer eigenen App triagieren { #triage-incoming-support-requests-from-your-own-app }

Verbinden Sie Ihr eigenes Support-Formular oder Ticketsystem mit einem Agent über einen [Ereignis-Trigger](../triggers.md) mit der Quelle **API**, der generischen `webhook`-Quelle, die bei jeder signierten JSON-Zustellung auslöst. Drei synthetische Tickets, darunter eine Sicherheitsmeldung, prüfen, ob Klassifizierung, Antwortentwurf und Sicherheitsmarkierung funktionieren, bevor Sie ein echtes System darauf richten. Dies ist eine Anleitung zum Ausführen, mit einem festgehaltenen Run als Referenz.

## Was Sie brauchen { #what-you-need }

Eine [laufende Installation](../install.md) mit einem Modellprofil. Keine Sandbox, kein Embedding-Modell und kein externes Konto: Die API-Quelle signiert ihre eigenen Zustellungen, also gibt es keine Anbieterkonsole zu konfigurieren.

## Die Eingabe vorbereiten { #prepare-the-input }

Drei Tickets, so wie Ihr eigenes Backend sie senden würde. Der gesamte JSON-Body erreicht den Prompt des Agents, also funktioniert jede Form, solange Sie die Instruktionen darauf abstimmen:

```json
{"ticket_id":"T-1001","from":"lena@acme-example.com","subject":"Charged twice this month","body":"I was billed 49 USD twice on the 3rd for the same Pro plan invoice. Can you refund the duplicate?"}
{"ticket_id":"T-1002","from":"marek@example.org","subject":"Export button does nothing","body":"Clicking Export CSV on the reports page just spins forever and nothing downloads. Chrome, latest version."}
{"ticket_id":"T-1003","from":"researcher@example.net","subject":"Found an issue with account access","body":"By changing the id in the /api/v1/invoices/{id} URL I was able to view another customer's invoice PDF without being logged in as them. Tested with three different ids, all worked."}
```

Referenz: T-1001 betrifft die Abrechnung, mittlere Priorität. T-1002 ist technisch, mittlere Priorität. T-1003 beschreibt ein IDOR und sollte als Sicherheit, dringend, mit ausdrücklicher Markierung zurückkommen.

## Den Agent bauen { #build-the-agent }

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil. Für diesen Versuch ist keine Capability nötig.
2. Setzen Sie die Instruktionen unten und klicken Sie dann auf **Publish**.

```text
You triage inbound support tickets for a small SaaS product.
Be concise and factual. Never invent facts not in the ticket.
```

3. Öffnen Sie **Routines → New event trigger**, wählen Sie den Agent und die Quelle **API**. Setzen Sie den eigenen Prompt des Triggers. Er wird bei jeder Auslösung vor der Zustellung gesendet:

```text
A support ticket just arrived as JSON below. Classify it by category (billing,
technical, account, security, other) and priority (low, medium, high, urgent).
Draft a reply the support team can send. If the ticket describes a possible
security vulnerability or exposure of somebody else's data, say so explicitly in
a line starting with 'SECURITY:' and set priority to urgent.
```

4. Speichern Sie. Kopieren Sie die **webhook URL** und das **signing secret**, die einmalig angezeigt werden. Die API-Quelle hat eine `manual`-Zustellung, also registriert sich nichts selbst, und Sie wählen das Geheimnis selbst. Was beides bedeutet, beschreibt [Trigger](../triggers.md#the-mechanism-once).

## Ausführen { #run-it }

Signieren Sie die genauen Bytes jedes Tickets mit dem Geheimnis des Triggers und senden Sie sie per POST. Die zwei Fallstricke beschreibt [eine Zustellung selbst signieren](../triggers.md#signing-a-delivery-yourself): Serialisieren Sie den Body nicht neu, und signieren Sie nur die Bytes, die Sie senden.

```bash
SECRET='your-signing-secret'
URL='http://localhost:8110/api/v1/webhooks/triggers/webhook/<trigger_id>'
BODY='{"ticket_id":"T-1001","from":"lena@acme-example.com","subject":"Charged twice this month","body":"I was billed 49 USD twice on the 3rd for the same Pro plan invoice. Can you refund the duplicate?"}'

SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')"

curl -sS -X POST "$URL" \
  -H 'Content-Type: application/json' \
  -H "X-Signature-256: $SIG" \
  --data-raw "$BODY"
```

Wiederholen Sie das für T-1002 und T-1003. Jede angenommene Zustellung antwortet mit `202`, also angenommen, nicht fertig. Die ausgelösten Runs lesen Sie in **Activity** oder in der eigenen Konversation des Triggers unter **Routines**.

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| T-1001 | Kategorie Abrechnung, Priorität mittel, eine Antwort, die die doppelte Belastung bestätigt |
| T-1002 | Kategorie technisch, Priorität mittel, eine Antwort, die nach Details zur Reproduktion fragt |
| T-1003 | Kategorie Sicherheit, Priorität dringend, eine Zeile, die mit `SECURITY:` beginnt und die Offenlegung benennt |
| Die Antwort `202` | Kommt sofort; der Run selbst endet Sekunden später, asynchron |
| Eine unsignierte Zustellung desselben Bodys | `403`, abgelehnt, bevor der Agent überhaupt läuft |
| Eine Zustellung, deren Body Ihr HTTP-Client neu serialisiert hat, statt ihn roh zu senden | `403`, weil die Signatur nicht mehr zu den tatsächlich gesendeten Bytes passt |

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter. Alle drei Zustellungen antworteten mit `202` und waren jeweils in etwa 6 Sekunden fertig, festgehalten mit der Oberfläche `schedule`: Auslösungen von Ereignis-Triggern teilen sich diese Oberfläche mit geplanten.

    T-1001: *"Category: Billing, Priority: Medium"*, eine Antwort, die für die Rückerstattung nach der Rechnungs-ID fragt. T-1002: *"Category: Technical, Priority: Medium"*, eine Antwort, die um die Ausgabe der Browser-Konsole bittet. T-1003: *"Category: Security, Priority: Urgent"*, gefolgt von `SECURITY: Reporter claims unauthenticated/unauthorized access to other customers' invoice PDFs via IDOR (Insecure Direct Object Reference) on /api/v1/invoices/{id}. Multiple accounts confirmed affected.` und einem Antwortentwurf, der die meldende Person bittet, während der Untersuchung nicht weiter zu testen. Gesamtkosten der drei Runs: 0,013 USD.

    Auch beide Ablehnungspfade wurden geprüft: Derselbe Body ohne Header `X-Signature-256` antwortete mit `403`, und ein als String signierter Body, der dann über die eigene `json=`-Kodierung eines Clients gesendet wurde (gleicher Inhalt, andere Bytes), antwortete ebenfalls mit `403 AUTHORIZATION_ERROR: Webhook signature did not verify`. Das bestätigt, dass die Signatur die genauen Bytes auf der Leitung abdeckt, nicht den logischen Inhalt des JSON.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Jede Zustellung kommt als `403` zurück.** Die Signatur deckt die *genauen* gesendeten Bytes ab. `echo` hängt einen abschließenden Zeilenumbruch an, der zum Signierten passen kann oder nicht. Verwenden Sie `printf '%s'` und `curl --data-raw`, und lassen Sie nie zu, dass ein Client ein Dictionary neu kodiert, nachdem Sie den String signiert haben.
- **`202`, aber kein Run erscheint.** Das heißt angenommen, nicht fertig: Ein Prefect-Flow führt ihn im Worker aus. Geben Sie ihm ein paar Sekunden und prüfen Sie Activity, gefiltert auf den Agent.
- **Die Sicherheitsmarkierung hat nicht ausgelöst.** Die Markierung kommt aus den Instruktionen, nicht aus einem eingebauten Klassifikator. Lesen Sie den Prompt des Triggers erneut und schärfen Sie, was als Sicherheitsmeldung zählt, wenn ein synthetischer Fall wie T-1003 übersehen wird.
- **Sie wollen nur den Prompt testen, nicht den Zustellweg.** Nutzen Sie zuerst **Run now** am Trigger. Es löst den Basis-Prompt des Agents ohne Zustellungskontext, ohne Signatur und ohne Webhook aus. Das prüft die Klassifizierung nicht, weil es kein Ticket-JSON zum Klassifizieren gibt, bestätigt aber, dass Agent, Budget und Veröffentlichungsstatus funktionieren.
- **Zapier oder Make statt eines Skripts.** Keines von beiden hat eine eingebaute HMAC-Aktion. Planen Sie eine Stunde für einen Code-Schritt ein, der den Body signiert, nicht fünf Minuten Klicken. Siehe [Trigger](../triggers.md#zapier-and-make-cannot-do-this-without-a-code-step).

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie die drei Ticket-Bodys, den Prompt des Triggers, die Herkunft des Signaturgeheimnisses (nicht seinen Wert), den HTTP-Status jeder Zustellung und den Run, den jede in Activity erzeugt hat, auf. Ein Mensch liest weiterhin jeden Entwurf, bevor er hinausgeht, und entscheidet, ob die Schwelle für die Sicherheitsmarkierung für ein echtes Postfach streng genug ist, bevor ein produktives Ticketsystem auf diesen Webhook zeigt.

## Nächste Schritte { #next-steps }

Dieselbe API-Quelle funktioniert für alles andere, das JSON signieren und per POST senden kann: eine Formulareinsendung, eine geänderte Marktplatz-Anzeige, einen Monitoring-Alarm. Für ein Postfach statt der Tickets Ihrer eigenen App siehe [Ihren Posteingang triagieren und Antworten entwerfen](email-triage.md), das statt einer signierten Zustellung die Gmail-Quelle nutzt.
