---
title: "E-Mails mit einem freigegebenen Entwurf beantworten"
description: "Ein Workflow liest neue Mail, entwirft eine Antwort, lässt eine Person sie bearbeiten und freigeben und legt dann einen Entwurf im Thread an oder sendet sie über einen selbst betriebenen MCP-Server für Gmail oder Microsoft 365."
source_sha: "bc960ef3277b"
---

# E-Mails mit einem freigegebenen Entwurf beantworten { #answer-mail-with-an-approved-draft }

Die [Seite zur Posteingangs-Triage](email-triage.md) endet mit einem Text im Chat.
Diese Seite geht einen Schritt weiter: Ein [Workflow](../workflows.md) liest eine
neue Nachricht, entwirft eine Antwort, zeigt sie einer Person, die sie bearbeiten
darf, und schreibt sie dann ins Postfach - als Entwurf im selben Thread oder als
gesendete Antwort. Das Postfach wird über einen MCP-Server erreicht, den Sie selbst
betreiben.

Der Gmail-Workflow unten wurde mit einem Testpostfach auf einer Entwicklungs-Bereitstellung
vollständig durchgespielt, mit `workspace-mcp` 2.2.1. Das Rezept für Microsoft 365 nicht:
Die Namen von Tools und Argumenten wurden aus dem Quellcode des Servers gelesen, nicht von
einem laufenden Server.

## Was Sie brauchen { #what-you-need }

- Einen der beiden Server, erreichbar von der Bereitstellung aus, mit einer Adresse
  mit der Endung `/mcp`:
  [`taylorwilsdon/google_workspace_mcp`](https://github.com/taylorwilsdon/google_workspace_mcp)
  für Gmail, mit `--transport streamable-http`, `MCP_ENABLE_OAUTH21=true` und Ihrem
  eigenen Google-OAuth-Client, oder
  [`softeria/ms-365-mcp-server`](https://github.com/softeria/ms-365-mcp-server) für
  Outlook, mit `--http` und einer in Microsoft Entra registrierten App (fügen Sie
  `--org-mode` hinzu, um gemeinsame Postfächer zu erreichen). Der Katalog führt sie
  als **Google Workspace (self-hosted)** und **Microsoft 365 (self-hosted)**.
- Ein Server im eigenen Netzwerk wird abgelehnt, bis ein Betreiber seinen Host in
  `OUTBOUND_PRIVATE_ALLOWLIST` oder `MCP_ALLOWED_HOSTS` einträgt. Siehe
  [MCP-Server](../mcp.md) und [Einstellungen](../configuration.md#project-settings).
- Mit `MCP_ENABLE_OAUTH21=true` weigert sich der Google-Workspace-Server, über
  einfaches `http` zu starten, außer auf `localhost`, und die Bereitstellung lehnt eine
  Loopback-Adresse für einen MCP-Server ab. Betreiben Sie ihn also über HTTPS unter einem
  Hostnamen, den die Bereitstellung erreicht. Um den Workflow auf einem Laptop
  auszuprobieren, starten Sie den Server stattdessen mit `--single-user` und ohne
  `MCP_ENABLE_OAUTH21`: Er meldet sich einmal bei Google an, behält das Token dieses
  Kontos und antwortet der Bereitstellung ohne Anmeldung. Jeder, der den Server
  erreicht, kann dann dieses Postfach nutzen; beschränken Sie ihn daher auf ein Testkonto
  auf einem Rechner, den sonst niemand erreicht.
- Eine MCP-Connection der **Organisation** zu diesem Server, aus diesem
  Katalogeintrag angelegt von jemandem mit `mcp:manage`. Jede Connection meldet sich
  als ein Konto an und antwortet daher aus einem Postfach. Ein Workflow kann noch
  keine persönliche Connection nutzen; ein so erreichtes Postfach ist ein
  Dienstkonto oder ein gemeinsames Postfach.
- Das verbundene Gmail- oder Outlook-Portal für den Trigger. Der Trigger liest Mail
  nur mit Lesezugriff. Das Schreibrecht liegt an der MCP-Connection, einer eigenen
  Berechtigung: Verbinden Sie sie als das Konto, das die Antworten verfassen soll.

## Gmail { #gmail }

Der Workflow folgt einem verbreiteten Muster für Gmail-Autoresponder: entscheiden, ob
eine Mail eine Antwort braucht, eine entwerfen und in den Thread legen. Er ergänzt zwei
Dinge. Eine Person prüft jede Antwort, bevor sie das Postfach erreicht, und wählt dort,
ob sie gesendet oder als Entwurf behalten wird. Bauen Sie ihn in dieser Reihenfolge.

1. **Gmail**-Trigger ([`trigger.gmail`](../reference/workflow-nodes.md#trigger-gmail))
   mit **Label** `INBOX`. Seine Ausgabe enthält `sender`, `subject`, `text`,
   `message_id`, `thread_id` und `rfc_message_id`. Das Postfach wird jede Minute
   geprüft, sofern Sie am Schritt kein längeres Intervall wählen.
2. **Braucht sie eine Antwort?** [`ai.classify`](../reference/workflow-nodes.md#model-steps)
   mit drei Kategorien, `needs_reply`, `fyi` (Newsletter, Belege, Benachrichtigungen,
   Dank) und `spam`, und `text`, gebunden an Absender, Betreff und Text. Setzen Sie
   **Minimum confidence**, zum Beispiel `0.7`: Eine Mail, bei der das Modell sich weniger
   sicher ist, verlässt den Schritt über `unsure`, sodass eine Person entscheidet statt
   des Modells. Die Konfidenz ist die Selbstauskunft des Modells und nicht kalibriert;
   prüfen Sie den Schwellenwert an Ihrer eigenen Mail mit den
   [Evals](../workflows.md#evals-for-a-model-step) des Schritts.
3. **Die zwei Wege zu einer Antwort zusammenführen.** Verbinden Sie `needs_reply` und
   `unsure` mit einem [`logic.merge`](../reference/workflow-nodes.md#logic-if-and-logic-merge).
   `fyi`, `spam` und `other` enden dort oder führen zu dem, was sie festhält.
4. **Die Antwort entwerfen.** [`knowledge.search`](../reference/workflow-nodes.md#knowledge-search)
   in der Collection, die Ihre Antworten enthält, mit `query`, gebunden an Betreff und
   Text, dann [`ai.prompt`](../reference/workflow-nodes.md#model-steps) mit der Mail und
   den `sources` der Suche in seinem Prompt. Anweisungen, die sich bewähren: in der
   Sprache des Absenders antworten, als reiner Text, mit einer Anrede beginnen und mit
   einer Grußformel enden, die Passagen verwenden und nie eine Antwort erfinden, und dort,
   wo die Antwort nicht bekannt ist, einen Platzhalter wie `[YOUR_ANSWER_HERE]` schreiben.
   Die freigebende Person füllt ihn aus. Ein [`agent.run`](../reference/workflow-nodes.md#agent-run)
   mit der Knowledge-Capability leistet dasselbe in einem Schritt.
5. **Sie prüfen lassen.** [`human.approval`](../reference/workflow-nodes.md#human-approval)
   mit eingeschaltetem `editable`, `proposal`, gebunden an die entworfene Antwort, der
   Mail selbst in `details` und zwei **Auswahlmöglichkeiten (choices)**: `send` (**Send now**)
   und `draft` (**Save as draft**). Die freigebende Person bearbeitet den Text und drückt
   die Schaltfläche für das, was damit geschehen soll, oder **Reject**.
6. **In das Postfach schreiben.** Je ein
   [`mcp.call`](../reference/workflow-nodes.md#mcp-call) an der Connection zu Google
   Workspace pro Auswahl:

   | Auswahl | Tool | Argumente |
   |---|---|---|
   | `send` | `send_gmail_message` | `thread_id`, `in_reply_to`, `body` und `to` aus `sender` des Triggers |
   | `draft` | `draft_gmail_message` | `thread_id`, `in_reply_to`, `body` |

   Binden Sie `thread_id` an `thread_id` des Triggers, `in_reply_to` an dessen
   `rfc_message_id` und `body` an das `final` der Ausgabe der Freigabe auf dem Port dieser
   Auswahl. Lassen Sie `references` weg: Der Server leitet die Kette aus der beantworteten
   Nachricht ab. Ohne `subject` behält die Antwort den Betreff des Threads. Das
   Sende-Tool lehnt einen Aufruf ab, bei dem weder `to` noch `reply_all` auf `true`
   gesetzt ist; das Entwurfs-Tool füllt `to` selbst. `user_google_email` füllt ein Server
   selbst, der mit `MCP_ENABLE_OAUTH21=true` läuft; im Einzelnutzer-Modus binden Sie es an
   die Adresse des Postfachs.

   Setzen Sie **Ask for approval** beider Schritte auf **Never**. Eine Person hat den
   genauen Text einen Schritt zuvor freigegeben und würde sonst ein zweites Mal
   gefragt.

Um festzuhalten, was geschehen ist, ergänzen Sie nach einem dieser Schritte einen
Schritt, der einen Datensatz in eine [Tabelle](../virtual-tables.md) schreibt, mit der
Kategorie, der Entscheidung und dem gesendeten Text.

!!! warning "Ein direktes Senden hat keine Absicherung"

    `send_gmail_message` nimmt keinen Idempotenzschlüssel an, und der Server
    markiert es als Schreibzugriff. Wurde der Aufruf gemacht und kam keine Antwort,
    endet der Schritt als **Uncertain** und der Run wartet auf eine Person: Die Mail
    kann hinausgegangen sein oder nicht. Öffnen Sie den Thread in Gmail und sehen
    Sie nach, bevor Sie den Schritt erneut ausführen. **Save as draft** hat dieses
    Problem nicht: Eine Wiederholung kann höchstens einen zweiten Entwurf
    hinterlassen. Der Server hat kein Tool, das einen gespeicherten Entwurf sendet;
    ein Entwurf wird also aus Gmail gesendet.

## Microsoft 365 { #microsoft-365 }

1. **Outlook**-Trigger ([`trigger.outlook`](../reference/workflow-nodes.md#trigger-outlook)).
   Seine Ausgabe enthält `message_id` und, bei einem gemeinsamen Postfach, `mailbox`.
2. Derselbe Entwurfsschritt und dasselbe bearbeitbare `human.approval` wie oben.
3. **Den Text der Antwort bauen.** Ein **Map fields**-Schritt ([`data.map`](../reference/workflow-nodes.md#data-map))
   baut ein Feld, `reply_body`, vom Typ `json` aus dem `final` der Freigabe:

   ```text
   {Message: {body: {contentType: 'text', content: source.final}}}
   ```

   mit `source`, gebunden an den Freigabeschritt; das Ergebnis ist
   `values.reply_body`.

   Der eigene Hinweis des Servers zu `create-reply-draft` lautet,
   den Text als `Message.body.contentType` und `Message.body.content` zu übergeben;
   ein übergebener Text ersetzt den gesamten Text des Entwurfs, der zitierte Verlauf
   ist also nicht enthalten.

   Prüfen Sie die Argumentnamen im Formular des Tools im
   Editor, nachdem Sie das Tool gewählt und seine Tools aktualisiert haben: Der
   Server baut sie aus Microsoft Graph, und sie wurden nicht an einem laufenden
   Server gesehen.

4. [`mcp.call`](../reference/workflow-nodes.md#mcp-call) an der Connection zu
   Microsoft 365, Tool `create-reply-draft`, mit `messageId`, gebunden an `message_id`
   des Triggers, und `body`, gebunden an `values.reply_body` des vorherigen Schritts.
   Graph ordnet den Entwurf selbst dem Thread zu. Für ein vom Trigger gelesenes
   gemeinsames Postfach verwenden Sie stattdessen
   `create-shared-mailbox-reply-draft` und ergänzen `userId`, gebunden an `mailbox`
   des Triggers; der Server muss mit `--org-mode` laufen. Der Server registriert
   seine Pfadparameter in camelCase und verlangt sie.

5. *Optional.* Um den Entwurf zu senden, lesen Sie zuerst seine ID. Der Server
   antwortet mit JSON in seinem `text`, nicht als `structured`-Daten; ein
   [`code.python.simple`](../reference/workflow-nodes.md#python)-Schritt holt sie
   heraus: Binden Sie `args.text` an den `text` des Anlege-Schritts und führen Sie

   ```python
   import json
   json.loads(args['text'])['id']
   ```

   aus. Betreiben Sie den Server nicht mit `--toon`: Seine Ausgabe ist dann kein
   JSON. Rufen Sie dann `send-draft-message` auf, mit `messageId`, gebunden an das
   `result` dieses Schritts (`send-shared-mailbox-draft` für ein gemeinsames
   Postfach, das zusätzlich `userId` nimmt, gebunden an `mailbox` des Triggers).

Setzen Sie **Ask for approval** jedes `mcp.call`-Schritts nach einer bearbeitbaren
Freigabe auf **Never**. Wurde vor dem Schritt nichts freigegeben, behalten Sie den
Standard, **Before a tool that can change something**. Diese Regel fragt vor jedem
Tool, das der Server nicht als nur lesend markiert, also auch vor
`create-reply-draft` und vor `draft_gmail_message` von Gmail.

### Was eine Wiederholung tut { #what-a-repeat-does }

Keiner der Server nimmt einen Idempotenzschlüssel an; lassen Sie **Idempotency key
argument** bei diesen Schritten also leer. Die folgenden Wege machen eine
Wiederholung auch ohne ihn harmlos.

- **Microsoft 365: anlegen, dann über die ID des Entwurfs senden.** Ein zweites
  `send-draft-message` für denselben Entwurf scheitert, weil ein gesendeter Entwurf
  den Entwurfsordner verlassen hat; es sendet keine zweite Mail. Ein wiederholtes
  `create-reply-draft` kann einen überzähligen Entwurf hinterlassen, nie eine zweite
  gesendete Mail. Bricht der Sendeschritt nach dem Aufruf ab, endet er als
  **Uncertain**: Sehen Sie in den gesendeten Elementen nach und führen Sie ihn dann
  erneut aus. Eine erneute Ausführung eines Sendens, das stattgefunden hatte,
  scheitert, statt noch einmal zu senden.
- **Gmail: Save as draft.** Eine Wiederholung hinterlässt höchstens einen zweiten Entwurf.
- **Gmail: Send now** hat diesen Schutz nicht; siehe die Warnung oben.
Ein Fehler vor dem Aufruf - Server nicht erreichbar, Verbindung abgelehnt - wird von
selbst wiederholt. Nach einem Aufruf ohne Schlüssel an einem Tool, das der Server
nicht als nur lesend markiert, wird der Schritt nie von selbst wiederholt. Die Regel
steht in der [Referenz zu `mcp.call`](../reference/workflow-nodes.md#mcp-call).

## Sicherheit { #safety }

Mail ist Eingabe von außen und kann Anweisungen enthalten, die auf das Modell
zielen; die Dokumentation des Google-Workspace-Servers warnt davor. Lassen Sie den
Freigabeschritt zwischen dem Entwurfsschritt und dem Postfach, und geben Sie dem
Entwurfs-Agent kein Tool, das schreiben kann.

Anhänge erreichen den Workflow als Dateien, aber eine so verfasste Antwort trägt
keine.

## Prüfen { #check-it }

- Ein Entwurf oder eine gesendete Antwort erscheint im ursprünglichen Thread im Postfach; eine gesendete erreicht auch den Absender.
- `In-Reply-To` der gesendeten oder entworfenen Nachricht entspricht
  `rfc_message_id` des Triggers.
- Bearbeiten Sie den Text in der Freigabe und prüfen Sie, dass der bearbeitete Text,
  nicht der Vorschlag, im Postfach landet.
- Drücken Sie einmal **Save as draft** und einmal **Send now** und prüfen Sie, dass jede
  nur tat, was ihre Schaltfläche sagt.
- Senden Sie einen Newsletter und prüfen Sie, dass er keine Freigabe startet.
- Lehnen Sie die Freigabe ab und prüfen Sie, dass nichts geschrieben wird.

Mail, die das Postfach von der eigenen Adresse erhält, trägt das Label SENT, und der
Trigger überspringt SENT-Mail; testen Sie also mit Mail von einem anderen Konto.

## Nächste Schritte von derselben Connection { #next-steps-from-the-same-connection }

- **Google Calendar:** `query_freebusy`, `get_events`, `manage_event`.
- **Google Drive:** `search_drive_files`, `get_drive_file_content`.
- **Google Sheets:** `append_table_rows`, `read_sheet_values`.
- **Microsoft-365-Kalender:** `list-calendar-events`, `create-calendar-event`.

Es gibt noch einen anderen Weg zu Microsoft: Der gehostete Server **Microsoft Work IQ**
beantwortet Fragen über Mail, Besprechungen, Chats und Dateien, blockiert aber
Änderungen, bis ein Tenant-Administrator sie erlaubt. Siehe [Microsoft 365 und
Outlook](../mcp.md#outlook-setup).
