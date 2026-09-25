---
source_sha: "90d62e9ab4aa"
title: "Den ersten Dokumenten-Agent bauen"
description: "Erstellen Sie einen Assistenten für Fragen zu Geräteanträgen. Das synthetische Beispiel enthält einen prüfbaren Fakt und eine absichtliche Informationslücke. Dies ist eine Anleitung, kein Bericht über gemessene Deployment-Ergebnisse."
---

# Den ersten Dokumenten-Agent bauen { #build-your-first-document-agent }

Erstellen Sie einen Assistenten für Fragen zu Geräteanträgen. Das synthetische Beispiel enthält einen prüfbaren Fakt und eine absichtliche Informationslücke. Dies ist eine Anleitung, kein Bericht über gemessene Deployment-Ergebnisse.

## Die Quelle vorbereiten { #prepare-the-source }

Sie benötigen eine [laufende Installation](../install.md) und ein Modell. [Ihr erster Agent](../first-agent.md) beschreibt Zugangsdaten und Modellkonfiguration. Kosten hängen von Anbieter und Einstellungen ab.

Speichern Sie als `equipment-handbook.md`:

```text
Equipment requests go to the office manager.
Include the item, reason and delivery location.
```

Die Regeln sind erfunden. Ein Ausgabenlimit ist nicht angegeben.

## Erstellen und veröffentlichen { #build-and-publish }

1. Öffnen Sie unter **Knowledge → Collections** den Dialog zum Erstellen und erweitern Sie **Embeddings**. Wählen Sie einen kompatiblen Embedding-Anbieter und ein Modell sowie dessen Vault-Schlüssel oder lokalen Endpunkt. Erstellen Sie die Sammlung und laden Sie die Datei hoch. Ein Chatmodell allein reicht nicht. Warten Sie auf die Verarbeitung und prüfen Sie den Dokumentstatus.
2. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie das Modellprofil.
3. Aktivieren Sie unter **Toolbox** knowledge, binden Sie nur die Testsammlung und setzen Sie die folgenden Instruktionen.
4. Setzen Sie passende Budget- und Schrittlimits und veröffentlichen Sie mit **Publish** die Testversion.

```text
Answer equipment-policy questions from the bound handbook.
Cite the document you used.
If it does not contain the answer, say what is missing.
Do not invent policies or submit equipment requests.
```

## Das Ergebnis prüfen { #check-the-result }

| Frage | Prüfkriterium |
| --- | --- |
| Who handles an equipment request? | Office manager, durch die Quelle gestützt |
| Which details should I include? | Item, reason und delivery location |
| How much can I spend? | Hinweis, dass kein Limit in der Quelle steht |

Fragen Sie in einer neuen Testkonversation. Prüfen Sie Antwort und abgerufenes Material unter [Activity](../governance.md). Bewahren Sie auch falsche und unvollständige Antworten auf. Prüfen Sie bei leerem Retrieval Bindung, Berechtigungen und Verarbeitung vor einer Prompt-Änderung.

Ändern Sie die Zuständigkeit in der Testdatei auf facilities team. Löschen Sie das ursprüngliche Testdokument in der [Dokumentliste der Sammlung](../file-processing.md) und warten Sie auf den Abschluss, bevor Sie die geänderte Datei hochladen. Derselbe Dateiname ersetzt beim Hochladen allein keine alten Vektoren. Warten Sie auf die Verarbeitung und wiederholen Sie in einer neuen Konversation. Prüfen Sie, dass keine veraltete Quelle mehr abgerufen wird.

## Den nächsten Schritt teilen { #share-the-next-step }

Wählen Sie nach der Ergebnisprüfung [Slack oder einen anderen Zugang](../channels.md). Die Hosted Page ist per Link öffentlich: verwenden Sie öffentliche oder synthetische Daten. Der Kanal definiert keine Dokumentberechtigungen.

Benennen Sie vor dem Pilot die [Betriebsverantwortung](../rollout.md). Geben Sie bei Problemen Version, Konfiguration und bereinigte Reproduktion in einer [Hilfeanfrage](../help.md) an.
