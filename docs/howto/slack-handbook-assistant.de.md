---
source_sha: "fcf4f76f3d2d"
title: "Eine Handbuchfrage in Slack beantworten"
description: "Setzen Sie den Dokumenten-Agent in einen Slack-Testkanal, stellen Sie dieselben Fragen und prüfen Sie, wem jeder Run gehörte."
---

# Eine Handbuchfrage in Slack beantworten { #answer-a-handbook-question-in-slack }

Setzen Sie den [Dokumenten-Agent](first-document-agent.md) in einen Slack-Testkanal und stellen Sie ihm die Fragen, die Sie in der Konsole bereits geprüft haben. Gesucht ist dieselbe geprüfte Antwort in einem Slack-Thread und ein Run in Activity, der auf der Oberfläche `slack` festgehalten ist. Dies ist eine Anleitung zum Durchführen, kein Bericht über ein gemessenes Deployment.

## Bevor Sie beginnen { #before-you-start }

- **Der Dokumenten-Agent besteht seine drei Prüfungen in der Konsole.** Halten Sie Handbuch, Modell und veröffentlichte Version fest, während Sie Slack hinzufügen. Ändern sich Modell, Dokumente und Kanal gleichzeitig, sagt Ihnen eine abweichende Antwort nicht, welche Änderung sie verursacht hat.
- **Ein Slack-Workspace, in dem Sie Apps installieren dürfen.** Verwenden Sie einen Test-Workspace oder einen Testkanal. Das Handbuch ist synthetisch, daher steht nichts Privates auf dem Spiel, während Sie den Weg kennenlernen.
- **Die Berechtigung `channels:manage`**, um den Bot zu registrieren, und `agents:publish` auf dem Agent, aus Ihrer Rolle oder einem Grant, um ihn zu binden.

Socket Mode ist der unten verwendete Transport. Der Bot baut die Verbindung zu Slack selbst auf, daher muss nichts aus dem Internet erreichbar sein. Das macht ihn zur richtigen Wahl auf einem Laptop. [Kanäle](../channels.md#slack) beschreibt die Alternative über die Events API.

## Die Slack-App erstellen { #create-the-slack-app }

1. Wählen Sie unter **api.slack.com/apps → Create New App → From an app manifest** den Test-Workspace und fügen Sie das Manifest aus dem [Slack-Abschnitt von Kanäle](../channels.md#slack) ein. Ändern Sie `name` und `display_name` in den Namen, den der Bot tragen soll. Prüfen Sie die Scopes vor der Installation: Die [Scope-Tabelle](../channels.md#scopes-and-events) sagt, welcher Aufruf welchen braucht.
2. Fügen Sie unter **Basic Information → App-Level Tokens → Generate** den Scope `connections:write` hinzu und kopieren Sie das `xapp-`-Token.
3. Installieren Sie die App unter **Install App → Install to Workspace → Allow** und kopieren Sie das **Bot User OAuth Token** (`xoxb-`).

!!! warning "Lassen Sie die Token-Rotation ausgeschaltet"

    Bei eingeschalteter Token-Rotation läuft das `xoxb-`-Token ab, und der Bot antwortet nicht mehr. Die Plattform speichert ein statisches Bot-Token und erneuert es nicht.

Halten Sie beide Tokens aus Screenshots, Aufnahmen und Hilfeanfragen heraus.

## Den Bot registrieren und den Agent binden { #register-the-bot-and-bind-the-agent }

1. Wählen Sie unter **Channels → Add channel** Slack. Fügen Sie das Bot-Token in **Bot token** und das `xapp-`-Token in **App-level token** ein. Beide werden im [Vault](../secrets.md) versiegelt und nie wieder angezeigt.
2. Die neue Zeile zeigt *No agent bound - this bot answers nothing*. Das ist bis zum nächsten Schritt erwartet.
3. Öffnen Sie den Dokumenten-Agent im Builder, gehen Sie zu **Availability** und wählen Sie den Bot unter **Where this agent is available**. Der Agent muss eine veröffentlichte Version haben.
4. Lassen Sie die Kanalabfragen ausgeschaltet. Eine Handbuchfrage erfordert nicht, dass der Agent den Verlauf des Kanals oder seine Mitgliederliste liest, und jede Abfrage ist eine [eigene Entscheidung](../reference/capabilities.md#chat-channel-lookup).
5. Erstellen Sie in Slack einen Testkanal und laden Sie den Bot mit `/invite @your-bot` ein.

## Die Fragen stellen { #ask-the-questions }

Stellen Sie jede Frage in Slack und vergleichen Sie die Antwort mit der Quelle.

| Wo und was | Referenzprüfung |
| --- | --- |
| Im Kanal: `@your-bot Who handles an equipment request?` | Nennt den office manager und sagt, dass das Handbuch verwendet wurde |
| Antwort in diesem Thread: `Which details should I include?` | Item, reason und delivery location, beantwortet im selben Thread |
| Eine neue Nachricht im Kanal: `@your-bot How much can I spend?` | Sagt, dass das Handbuch kein Ausgabenlimit nennt |
| Eine Kanalnachricht, die den Bot nicht erwähnt | Keine Antwort |
| Eine Direktnachricht an den Bot, bevor Sie Ihr Konto verknüpfen | Bittet Sie, Ihr Konto zu verbinden, und sendet einen Link |

Ein Thread ist eine Konversation. Die Antwort im Thread behält die erste Antwort im Kontext. Eine neue Nachricht im Kanal beginnt eine neue Konversation ohne Erinnerung an die letzte. Siehe [eine Konversation pro Thread](../channels.md#one-conversation-per-thread).

Die Erwähnung muss eine sein, die Slack aufgelöst hat, ausgewählt aus der Autovervollständigung. Ein als reiner Text getippter Handle ist keine Erwähnung, und der Bot bleibt still.

## Prüfen, wem jeder Run gehörte { #check-who-each-run-belonged-to }

Öffnen Sie **Activity** und suchen Sie die Runs. Jeder hält die Oberfläche `slack`, die antwortende Agent-Version und das Slack-Konto fest, das die Nachricht geschrieben hat. Öffnen Sie einen Run und prüfen Sie, dass er `search_documents` aufgerufen hat und dass die abgerufene Passage diejenige ist, auf die sich die Antwort stützt.

Ein Absender, der kein Slack-Konto mit einem Mitglied verknüpft hat, bekommt in einem Kanal trotzdem eine Antwort. Dieser Run übernimmt die Rolle der Person, die den Agent an den Bot gebunden hat. Jeder, der im Kanal posten kann, kann also über den Agent das Budget der Organisation ausgeben und lesen, was die gebundenen Sammlungen enthalten.

!!! info "Die Mitglieder des Kanals sind das Publikum des Dokuments"

    Der Agent durchsucht die Sammlungen, die sein Spec bindet, egal wer fragt. Die eigenen Berechtigungen eines Slack-Nutzers in AgenticOS schränken das nicht ein. Wählen Sie Kanal und Sammlung gemeinsam, und testen Sie Zugriffsregeln nie mit einem privaten Dokument.

Um Ihr eigenes Konto zu verknüpfen, senden Sie dem Bot eine Direktnachricht. Er antwortet mit einem Link. Öffnen Sie ihn in dem Browser, in dem Sie in der Konsole angemeldet sind, und bestätigen Sie **Connect this account**. Ab dann laufen Ihre Nachrichten als Sie, mit Ihren Berechtigungen und Ihrem Budget. Der Link gilt fünfzehn Minuten und funktioniert einmal. Verknüpfte Konten stehen unter **Settings → Profile → Chat accounts**.

Um unverknüpfte Absender auch in Kanälen abzuweisen, setzen Sie `require_link` in der Zugriffsrichtlinie des Bots. Die Regeln und das Rate-Limit pro Konto stehen unter [Verknüpfung, und wo sie verlangt wird](../channels.md#what-every-channel-shares).

## Wenn er nicht antwortet { #when-it-does-not-answer }

Gehen Sie den Weg in dieser Reihenfolge durch:

1. Die Zeile des Bots unter **Channels** zeigt **Not connected**. Das Badge nennt den Grund, oft ein falsches oder fehlendes `xapp-`-Token.
2. Die Zeile sagt weiterhin, dass kein Agent gebunden ist, oder der Agent hat keine veröffentlichte Version.
3. Ein Scope oder ein Event fehlt. Um einen hinzuzufügen, muss die App neu installiert werden, was ein neues `xoxb-`-Token ausstellt. Fügen Sie das neue Token in die Einstellungen des Bots ein, sonst behält der Bot den Zugriff, den er hatte.
4. Der Bot ist nicht im Kanal, oder die Nachricht war keine aufgelöste Erwähnung.
5. Eine Direktnachricht von einem unverknüpften Konto wird abgewiesen, bis Sie es verknüpfen.

Antwortet der Bot, aber falsch, funktioniert der Slack-Weg. Prüfen Sie das Retrieval in Activity und die Dokumente der Sammlung, bevor Sie in Slack etwas ändern. [Kanäle](../channels.md#slack) führt auf, was bei einem stillen Bot gemeldet wird und was nicht.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie Folgendes zusammen auf, damit eine andere Person den Versuch wiederholen und vergleichen kann:

- die AgenticOS-Version, die Agent-Version, das Modellprofil und die Sammlung mit ihrem Dokumentstatus;
- das eingefügte Slack-Manifest, ohne Tokens, und den Transport;
- jede Frage, die Antwort, wie sie in Slack gepostet wurde, und den passenden Run in Activity;
- jeden Fehler, auch einen stillen Bot, und was ihn behoben hat;
- wer die App installiert, wer den Agent gebunden und wer die Antworten beurteilt hat.

Eine Person tut hier drei Dinge, die keine Einstellung ersetzt: Sie installiert die App, entscheidet, welcher Kanal welche Dokumente erreichen darf, und beurteilt jede Antwort anhand der Quelle. Ein Screenshot der Channels-Seite erklärt die Einrichtung. Nur der Thread mit Frage und Antwort nebeneinander zeigt das Ergebnis.

## Nächste Schritte { #next-steps }

Bevor Sie das synthetische Handbuch durch ein echtes ersetzen, entscheiden Sie, wer dieses Dokument erreichen soll, und wählen Sie den Kanal passend dazu. Benennen Sie, wer das Dokument aktualisiert, wer den Agent ändert und wer Fragen nachgeht, die das Handbuch nicht beantworten kann. [Rollout](../rollout.md) behandelt diese Rollen.
