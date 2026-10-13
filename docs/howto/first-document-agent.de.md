---
source_sha: "37a9ef11651d"
title: "Den ersten Dokumenten-Agent bauen"
description: "Geben Sie einem Agent ein kleines Handbuch, stellen Sie eine Frage und prüfen Sie die Antwort gegen die Quelle."
---

# Den ersten Dokumenten-Agent bauen { #build-your-first-document-agent }

Bauen Sie einen Assistenten, der Fragen zur Geräte-Richtlinie aus einem Dokument beantwortet. Diese synthetische Testdatei gibt Ihnen einen Fakt zum Prüfen und eine absichtliche Informationslücke. Dies ist eine Anleitung zum Durchführen, mit einem festgehaltenen Run als Referenz.

## Die Quelle vorbereiten { #prepare-the-source }

Verwenden Sie eine [laufende Installation](../install.md) und ein konfiguriertes Modell. Folgen Sie [Ihrem ersten Agent](../first-agent.md) für die Zugangsdaten des Anbieters und die Modellkonfiguration. Die Kosten hängen vom gewählten Anbieter und der Konfiguration ab.

Speichern Sie diesen Text als `equipment-handbook.md`:

```text
Equipment requests go to the office manager.
Include the item, reason and delivery location.
```

Dies sind erfundene Richtlinien-Fakten. Es ist kein Ausgabenlimit angegeben.

## Erstellen und veröffentlichen { #build-and-publish }

1. Öffnen Sie unter **Knowledge → Collections** den Erstellen-Dialog und erweitern Sie **Embeddings**. Wählen Sie einen kompatiblen Embedding-Anbieter/Modell sowie dessen Vault-Zugangsdaten oder lokalen Endpunkt, erstellen Sie dann die Sammlung und laden Sie die Datei hoch. Ein Chatmodell allein reicht nicht aus. Warten Sie auf die Verarbeitung und prüfen Sie den Dokumentstatus.
2. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
3. Aktivieren Sie unter **Toolbox** knowledge und binden Sie nur die Testsammlung. Setzen Sie die folgenden Instruktionen.
4. Setzen Sie ein für den Versuch passendes Budget- und Schrittlimit und veröffentlichen Sie mit **Publish** die Version, die Sie testen werden.

```text
Answer equipment-policy questions from the bound handbook.
Cite the document you used.
If it does not contain the answer, say what is missing.
Do not invent policies or submit equipment requests.
```

## Das Ergebnis prüfen { #check-the-result }

| Frage | Referenzprüfung |
| --- | --- |
| Who handles an equipment request? | Nennt den office manager, gestützt durch die Quelle |
| Which details should I include? | Item, reason und delivery location |
| How much can I spend? | Sagt, dass das Limit in der Quelle fehlt |

Fragen Sie in einer neuen Testkonversation. Prüfen Sie die Antwort und das abgerufene Material unter [Activity](../governance.md). Bewahren Sie falsche und unvollständige Antworten ebenso auf wie erfolgreiche. Ist das Retrieval leer, prüfen Sie Bindung, Berechtigungen und Verarbeitung, bevor Sie den Prompt ändern.

Ändern Sie die Zuständigkeit in der Testdatei auf facilities team. Löschen Sie in der [Dokumentliste der Sammlung](../file-processing.md) das ursprüngliche Testdokument und warten Sie, bis das Löschen abgeschlossen ist, bevor Sie die geänderte Datei hochladen. Derselbe Dateiname ersetzt beim Hochladen allein nicht die alten Vektoren. Warten Sie auf die Verarbeitung und wiederholen Sie in einer neuen Konversation. Prüfen Sie, dass keine veraltete Quelle mehr abgerufen wird.

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter, Knowledge-Suche an die eine Sammlung gebunden. „Who handles an equipment request?" rief `search_documents` einmal auf und antwortete „equipment requests go to the office manager," mit den drei Details, unter Zitat von `equipment-handbook.md`. „How much can I spend?" rief `search_documents` zweimal auf und antwortete, dass das Handbuch „does not contain any information about spending limits or purchase approval thresholds" enthalte. Gesamtkosten für die drei Fragen sowie den unten beschriebenen erneuten Versuch: 0,043 USD.

    „Which details should I include?" lieferte zunächst statt einer Suche eine Rückfrage („could you clarify what you're referring to?") — allein in einer neuen Konversation gestellt, trägt die Formulierung das Thema Geräteantrag nicht in sich. Ein zweiter Versuch derselben Frage rief `search_documents` auf und antwortete korrekt. Formulieren Sie die Frage mit genanntem Gegenstand, wenn die Suche beim ersten Versuch laufen soll.

    Nach dem Löschen des ursprünglichen Dokuments, der Bestätigung, dass die Liste leer war, und dem Hochladen der geänderten Datei antwortete dieselbe erste Frage in einer neuen Konversation mit „equipment requests go to the facilities team," ohne Erwähnung des office manager. Gesamtkosten für die fünf Turns: 0,055 USD.

## Den nächsten Schritt teilen { #share-the-next-step }

Stellen Sie den Agent nach der Ergebnisprüfung [in Slack](slack-handbook-assistant.md) bereit oder wählen Sie [einen anderen Zugang](../channels.md). Die Hosted Page ist über den Link öffentlich zugänglich: Verwenden Sie dort öffentliches oder synthetisches Material. Die Wahl des Kanals legt keine Dokumentberechtigungen fest.

Benennen Sie vor einem Team-Pilotprojekt die [Betriebsverantwortung](../rollout.md). Schlägt ein Schritt fehl, geben Sie Version, Konfiguration und eine bereinigte Reproduktion in einer [Hilfeanfrage](../help.md) an.
