---
title: "E-Mails mit einem freigegebenen Entwurf beantworten"
description: "Ein Workflow liest neue Mail, entwirft eine Antwort, lässt eine Person sie bearbeiten und freigeben und legt dann einen Entwurf im Thread an oder sendet sie über einen selbst betriebenen MCP-Server für Gmail oder Microsoft 365."
source_sha: "fc39b8c85301"
---

# E-Mails mit einem freigegebenen Entwurf beantworten { #answer-mail-with-an-approved-draft }

Die [Seite zur Posteingangs-Triage](email-triage.md) endet mit einem Text im Chat.
Diese Seite geht einen Schritt weiter: Ein [Workflow](../workflows.md) liest eine
neue Nachricht, entwirft eine Antwort, zeigt sie einer Person, die sie bearbeiten
darf, und schreibt sie dann ins Postfach - als Entwurf im selben Thread oder als
gesendete Antwort. Das Postfach wird über einen MCP-Server erreicht, den Sie selbst
betreiben.

Das ist ein Ablauf zum Nachvollziehen, kein Bericht über eine gemessene
Bereitstellung. Er braucht ein Postfach, eine Google- oder Microsoft-App-Registrierung
und einen Server, die die Maintainer für diese Seite nicht betrieben haben; nichts
hier wurde also an einem echten Postfach ausgeführt. Die Namen von Tools und
Argumenten wurden aus dem Quellcode der Server gelesen, nicht von einem laufenden
Server.

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
- Eine MCP-Connection der **Organisation** zu diesem Server, aus diesem
  Katalogeintrag angelegt von jemandem mit `mcp:manage`. Jede Connection meldet sich
  als ein Konto an und antwortet daher aus einem Postfach. Ein Workflow kann noch
  keine persönliche Connection nutzen; ein so erreichtes Postfach ist ein
  Dienstkonto oder ein gemeinsames Postfach.
- Das verbundene Gmail- oder Outlook-Portal für den Trigger. Der Trigger liest Mail
  nur mit Lesezugriff. Das Schreibrecht liegt an der MCP-Connection, einer eigenen
  Berechtigung: Verbinden Sie sie als das Konto, das die Antworten verfassen soll.

## Gmail { #gmail }

Bauen Sie den Workflow in dieser Reihenfolge.

1. **Gmail**-Trigger ([`trigger.gmail`](../reference/workflow-nodes.md#trigger-gmail)).
   Seine Ausgabe enthält `thread_id`, `rfc_message_id`, `subject`, `sender` und
   `text`.
2. Ein Entwurfsschritt: [`agent.run`](../reference/workflow-nodes.md#agent-run) mit
   der Knowledge-Capability, oder [`knowledge.search`](../reference/workflow-nodes.md#knowledge-search)
   gefolgt von [`ai.prompt`](../reference/workflow-nodes.md#model-steps). Sein Text
   ist die vorgeschlagene Antwort.
3. [`human.approval`](../reference/workflow-nodes.md#human-approval) mit
   eingeschaltetem `editable` und `proposal`, gebunden an den Entwurfsschritt. Die
   freigebende Person liest die Zusammenfassung der Mail in `details`, bearbeitet den
   Text und gibt frei.

4. [`mcp.call`](../reference/workflow-nodes.md#mcp-call) an der Connection
   zu Google Workspace, Tool `draft_gmail_message`, mit diesen Argumenten:

   | Argument | Gebunden an |
   |---|---|
   | `thread_id` | `thread_id` des Triggers |
   | `in_reply_to` | `rfc_message_id` des Triggers |
   | `body` | `final` des Freigabeschritts |

   Lassen Sie `references` weg: Der Server leitet die Kette aus der beantworteten
   Nachricht ab. Lassen Sie auch `to` weg, und der Server antwortet dem Absender
   dieser Nachricht; setzen Sie `reply_all` auf `true`, um allen im Thread zu
   antworten. Ohne `subject` behält der Entwurf den Betreff des Threads.
   `user_google_email` füllt der Server selbst, weil er mit
   `MCP_ENABLE_OAUTH21=true` läuft.

   Setzen Sie **Ask for approval** dieses Schritts auf **Never**. Eine Person hat den
   genauen Text einen Schritt zuvor freigegeben und würde sonst ein zweites Mal
   gefragt.

Um zu **senden**, statt einen Entwurf anzulegen, verwenden Sie `send_gmail_message`
mit denselben Argumenten und einem weiteren: Binden Sie `to` an `sender` des
Triggers, oder setzen Sie `reply_all` auf `true`. Das Tool lehnt einen Aufruf ohne
beides ab (`reply_all` braucht die `thread_id`), und nur das Entwurfs-Tool füllt `to`
selbst. Der Server hat kein Tool, das einen gespeicherten Entwurf sendet; es sind
also zwei getrennte Wege, nicht zwei Schritte.

!!! warning "Ein direktes Senden hat keine Absicherung"

    `send_gmail_message` nimmt keinen Idempotenzschlüssel an, und der Server
    markiert es als Schreibzugriff. Wurde der Aufruf gemacht und kam keine Antwort,
    endet der Schritt als **Uncertain** und der Run wartet auf eine Person: Die Mail
    kann hinausgegangen sein oder nicht. Öffnen Sie den Thread in Gmail und sehen
    Sie nach, bevor Sie den Schritt erneut ausführen. Wollen Sie eine zweite Chance,
    einen Fehler abzufangen, verwenden Sie `draft_gmail_message` und lassen Sie eine
    Person in Gmail auf **Senden** drücken: Eine Wiederholung kann höchstens einen
    zweiten Entwurf hinterlassen.

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
- **Gmail: einen Entwurf anlegen** (empfohlen). Eine Wiederholung hinterlässt
  höchstens einen zweiten Entwurf.
- **Gmail: ein direktes Senden** hat diesen Schutz nicht; siehe die Warnung oben.

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
- Lehnen Sie die Freigabe ab und prüfen Sie, dass nichts geschrieben wird.

## Nächste Schritte von derselben Connection { #next-steps-from-the-same-connection }

- **Google Calendar:** `query_freebusy`, `get_events`, `manage_event`.
- **Google Drive:** `search_drive_files`, `get_drive_file_content`.
- **Google Sheets:** `append_table_rows`, `read_sheet_values`.
- **Microsoft-365-Kalender:** `list-calendar-events`, `create-calendar-event`.

Es gibt noch einen anderen Weg zu Microsoft: Der gehostete Server **Microsoft Work IQ**
beantwortet Fragen über Mail, Besprechungen, Chats und Dateien, blockiert aber
Änderungen, bis ein Tenant-Administrator sie erlaubt. Siehe [Microsoft 365 und
Outlook](../mcp.md#outlook-setup).
