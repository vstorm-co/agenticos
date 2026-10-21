---
title: "AgenticOS vs Sauna"
seo_title: "AgenticOS vs Sauna: eine selbst gehostete Alternative"
description: "Sauna ist ein proaktiver KI-Assistent pro Person, in ihrer Cloud. AgenticOS: viele kontrollierte Agents, jedes Modell und Budgets pro Agent auf Ihren Servern."
source_sha: "e589e2dd5acb"
---

# AgenticOS vs Sauna { #agenticos-vs-sauna }

Sauna von HeyDaily Inc. ist ein proaktiver KI-Assistent für jede Person. Er liest das Postfach, den Kalender, die Dokumente und die Tools, die Sie verbinden, merkt sich, was er lernt, und schlägt Arbeit in Ihrem Namen vor oder erledigt sie: in der Web- und iOS-App, in iMessage, in Slack und per E-Mail. AgenticOS gibt einem Unternehmen so viele Agents, wie es braucht, jeden mit eigenen Instruktionen, eigenem Modell, eigenen Werkzeugen, eigenem Wissen, Budget und eigenen Zugriffsregeln, auf einer Infrastruktur, die das Unternehmen kontrolliert.

Wenn Sie einen persönlichen Assistenten möchten, der in zehn Minuten an Ihrem Postfach arbeitet, ist Sauna schnell ausprobiert. Wenn Sie entscheiden möchten, was jeder Agent darf, was er kostet und wo die Daten liegen, gibt Ihnen AgenticOS diese Kontrolle.

Gepflegt vom AgenticOS-Team. Quellen geprüft am 21. Oktober 2026. AgenticOS-Basisversion: v1.10.0. Umfang Sauna: die öffentlichen Seiten zu Preisen, Sicherheit und Datenschutz (die Datenschutzerklärung mit Stand 6. Oktober 2026), kein getestetes Konto und kein verhandelter Vertrag.

## Auf einen Blick { #at-a-glance }

| Bereich | Sauna | AgenticOS |
| --- | --- | --- |
| Was Sie bekommen | Einen proaktiven Assistenten pro Person, mit Gedächtnis und eigenem Cloud-Computer | Beliebig viele Agents, jeder eine versionierte Spezifikation |
| Wo es läuft | Die Cloud von Sauna; US-Infrastruktur für US-Kunden, und Daten können in den USA verarbeitet werden | Ihre Infrastruktur, mit Docker Compose |
| Quellcode | Proprietär | Apache-2.0 |
| Modelle | Das Modell Sauna Lite im Tarif Lite; alle Modelle ab Basic; eigene Modelle ab Pro | 28 Provider, darunter Ollama und LiteLLM auf Ihrer eigenen Hardware |
| Wissen | Abgelegte Dateien, ein Gedächtnis, das er aufbaut, und verbundene Tools | Dokumentsammlungen in Ihrem Postgres, mit Parsing und Chunking nach Ihrer Wahl und fünf Sync-Konnektoren |
| Oberflächen | Web-App, iOS-App, iMessage, Slack, Gmail, Superhuman, E-Mail | Web-Chat, Widget, gehostete Seite, HTTP-API, WebSocket, Slack, Telegram, Mattermost |
| Teilen | Standardmäßig privat; Freigabe für ausgewählte Personen und ein gemeinsames Unternehmensgehirn im Tarif Team | Sechs Rollen, 33 Berechtigungen und Grants pro Ressource, pro Organisation |
| Autonomie | Konfigurierbar, vom Vorschlagen von Aktionen bis zum selbstständigen Handeln | Freigaben pro Capability, pro Werkzeug und pro MCP-Verbindung, entschieden von einer Person mit `approvals:decide` |
| Preise | Free mit 10 Credits pro Tag oder 20 mit verifizierter Karte; Lite 29 $, Basic 99 $, Pro 299 $ und Team 999 $ im Monat, nur monatlich | Keine Lizenzgebühr; Sie bezahlen Modell-Provider und Infrastruktur |
| Compliance-Nachweise | SOC 2 Type II, CASA | Ihre Kontrollen auf Ihrer Infrastruktur; siehe [Sicherheit](../security.md) |

## Wo AgenticOS weiter geht { #where-agenticos-goes-further }

### Agents für das Unternehmen, nicht ein Assistent pro Person { #agents-for-the-company-not-one-assistant-per-person }

Jede Person hat ihre eigene Sauna, und ein gemeinsames Unternehmensgehirn gibt es im Tarif Team. In AgenticOS wird jeder Agent für seine eigene Aufgabe gebaut, etwa ein Agent für HR-Richtlinien, ein Vertriebsassistent oder ein Agent für die Support-Triage. Jeder hat eigene Instruktionen, [Capabilities](../reference/capabilities.md), Wissenssammlungen und ein eigenes Budget, und derselbe Agent bedient alle, mit denen er geteilt ist.

Die Spezifikation eines Agents wird [beim Veröffentlichen versioniert](../concepts.md#version) und [exportiert als YAML](../features.md#exportable-into-your-own-repository) in Ihr Git-Repository. Ein [Projekt](../projects.md) gibt einem Team und seinen Agents gemeinsame Dateien, Instruktionen und Chats.

### Daten bleiben, wo Sie sie ablegen { #data-that-stays-where-you-put-it }

Sauna ist ein US-Dienst: Seine Datenschutzerklärung sagt, dass personenbezogene Daten in den USA und in den Ländern verarbeitet werden können, in denen seine Unterauftragsverarbeiter tätig sind, auf Grundlage der EU-Standardvertragsklauseln. Bei der Anmeldung recherchiert Sauna im öffentlichen Web über Sie und legt das Ergebnis in Ihrem Workspace ab. Website und App laden Werbepixel von Meta, LinkedIn, Google und Reddit, in einigen Regionen standardmäßig ausgeschaltet. Produktanalysedaten werden bis zu sieben Jahre aufbewahrt.

AgenticOS speichert Konversationen, Dokumente und Vektoren in [Ihrem eigenen Postgres](../data-protection.md#where-personal-data-lives), und eine frische Installation [sendet nichts nach außen](../data-protection.md#nothing-leaves-by-default). Sie legen die [Aufbewahrung pro Datenklasse](../governance.md#retention) fest. Mit einem lokalen Modell muss nichts Ihr Netzwerk verlassen.

### Ein Modell Ihrer Wahl und ein Budget pro Agent { #a-model-you-choose-and-a-budget-per-agent }

Der günstigste Tarif von Sauna läuft auf dem eigenen Lite-Modell, und die Modellauswahl öffnet sich ab Basic. Die meisten Modelle laufen ohne Datenaufbewahrung (Zero Data Retention); Claude Fable 5.1 bewahrt Prompts und Ausgaben 30 Tage bei Anthropic auf. AgenticOS erreicht für jeden Agent [28 Provider](../models.md#providers). Jeder Agent hat ein [monatliches Budget](../governance.md#budgets), das [vor jeder Modellanfrage](../governance.md#enforcement-is-before-the-request) geprüft wird, in der Währung Ihres Providers statt in Credits.

### Freigabe durch jemand anderen als den Anfragenden { #approval-by-someone-other-than-the-requester }

Bei Sauna legen Sie fest, wie viel es ohne Sie tun darf. In AgenticOS [hält ein Tool, das der Autor des Agents hinter ein Gate gestellt hat, den Run an](../governance.md#approvals), bis eine Person mit `approvals:decide` entscheidet, und jede Entscheidung landet in einem [Audit-Log mit Manipulationsnachweis](../governance.md#audit). Eine MCP-Verbindung hat ihre eigene [Freigaberichtlinie](../mcp.md#which-calls-wait-for-a-person).

### Wissen, das Sie prüfen können { #knowledge-you-can-inspect }

Sauna behält die Dateien, die Sie ablegen, und greift beim Arbeiten darauf zurück. AgenticOS ergänzt verwaltete Dokumentsammlungen: Sie wählen [Parser](../file-processing.md#parser-selection-rag) und [Chunking](../file-processing.md#chunking-configuration) pro Sammlung. Sie können aus Google Drive, S3, SharePoint oder OneDrive, einer Website oder einem Git-Repository synchronisieren.

## Wann Sauna genügt { #when-sauna-is-enough }

- Sie möchten einen persönlichen Assistenten, der Ihr eigenes Postfach und Ihren Kalender sortiert, ohne etwas zu betreiben.
- Sie möchten über iMessage, eine iOS-App oder Superhuman mit ihm sprechen. AgenticOS hat keine dieser Oberflächen.
- Sein Katalog mit mehr als 3.000 Tools und Ihre eigenen MCP-Server decken Ihre Arbeit ab.
- Die Verarbeitung in den USA und seine Aufbewahrungsbedingungen erfüllen Ihre Anforderungen.

## Gemeinsam nutzen { #use-them-together }

Behalten Sie Sauna für das Postfach einer Person. Nutzen Sie AgenticOS für die Agents, auf die sich ein Team oder seine Kunden verlassen. Ein AgenticOS-Agent kann ein Postfach über einen [Gmail-Trigger](../triggers.md#gmail-1-minute-and-no-secret-anywhere) beobachten, nach Zeitplan als Routine laufen, sich mit dem [Gedächtnis](../reference/capabilities.md#memory-files) merken, was er lernt, und [Apps](../reference/capabilities.md#artifacts) veröffentlichen, unter den oben beschriebenen Budgets und Freigaben.

## Eine Handbuchfrage ausprobieren { #try-one-handbook-question }

Verwenden Sie das [gemeinsame Testdokument](../howto/first-document-agent.md). Stellen Sie in beiden die beantwortbare Frage und die Frage nach einer fehlenden Richtlinie. Geben Sie die Antwort dann einem Kollegen. Bei Sauna braucht er ein eigenes Konto, oder Sie teilen Ihre Sauna mit ihm; bei AgenticOS öffnet er den Agent, den Sie geteilt haben, oder eine [gehostete Seite](../channels.md#a-hosted-page). Halten Sie das Ergebnis mit der [Vergleichsmethode](comparison.md#a-shared-trial) fest.

## Häufig gestellte Fragen { #frequently-asked-questions }

### Ist AgenticOS eine Alternative zu Sauna? { #is-agenticos-an-alternative-to-sauna }

Ja, wenn Sie Agents für ein Team möchten statt eines Assistenten pro Person. AgenticOS betreibt viele Agents, jeden mit eigenen Instruktionen, eigenem Zugriff, Wissen und Budget, auf Ihrer eigenen Infrastruktur. Sauna ist für das Postfach einer Person schneller gestartet und läuft in der eigenen Cloud.

### Wo speichert Sauna Daten? { #where-does-sauna-store-data }

Die Sicherheitsseite sagt, dass Infrastruktur und Datenspeicherung für US-Kunden in den Vereinigten Staaten liegen, und die Datenschutzerklärung, dass Daten in den USA und überall dort verarbeitet werden können, wo die Unterauftragsverarbeiter tätig sind. AgenticOS hält seine Daten in Ihrem eigenen Deployment, wo auch immer Sie es betreiben: Konversationen, Dokumente und Vektoren in Ihrem Postgres, hochgeladene Dateien und Sandbox-Workspaces auf seinen Volumes und kurzlebigen Zustand in Redis.

### Wie unterscheiden sich die Preise? { #how-does-pricing-compare }

Sauna hat einen kostenlosen Tarif mit 10 Credits pro Tag, oder 20 mit verifizierter Karte, und bezahlte Tarife von 29 $ bis 999 $ im Monat, monatlich abgerechnet. AgenticOS hat keine Lizenzgebühr: Sie bezahlen die Modell-Provider direkt, und jeder Agent hat sein eigenes monatliches Budget.

### Kann AgenticOS meine E-Mails lesen wie Sauna? { #can-agenticos-read-my-email-like-sauna }

Ein Agent kann es, wenn Sie ihn verbinden. Ein Gmail-Trigger startet einen Agent bei neuer Post, und ein MCP-Server für Ihr Postfach lässt ihn lesen und Entwürfe schreiben. Jeder schreibende Schritt kann auf eine Freigabe warten.

## Verwandte Vergleiche { #related-comparisons }

[AgenticOS vs Viktor](viktor.md) · [AgenticOS vs ChatGPT](chatgpt.md) · [AgenticOS vs Claude](claude-apps.md) · [Alle Vergleiche](comparison.md)

## Quellen { #sources }

- [Preise von Sauna](https://www.sauna.ai/pricing): Tarife, Credits, Modelle pro Tarif, Oberflächen, Teilen, Autonomie und ausschließlich monatliche Abrechnung.
- [Sicherheit](https://www.sauna.ai/security): SOC 2 Type II, CASA, Verschlüsselung, US-Infrastruktur für US-Kunden, Verbindungen über MCP und API.
- [Datenschutzerklärung](https://www.sauna.ai/privacy): Web-Recherche bei der Anmeldung, Zero Data Retention und ihre Ausnahmen, Werbepixel, internationale Übermittlungen und Aufbewahrungsfristen.
