---
source_sha: "5f8a5a14154b"
title: "AgenticOS vs Viktor"
seo_title: "AgenticOS vs Viktor: selbst gehostete Teammate-Alternative"
description: "Viktor ist ein KI-Teammate pro Slack- oder Teams-Workspace. AgenticOS bietet viele kontrollierte Agents, jedes Modell und Budgets pro Agent auf Ihren Servern."
---

# AgenticOS vs Viktor { #agenticos-vs-viktor }

Viktor verkauft einen KI-Teammate pro Slack- oder Microsoft-Teams-Workspace, betrieben in seiner Cloud und in Credits abgerechnet. AgenticOS gibt Ihnen so viele Agents, wie Sie brauchen, jeder mit eigenen Instruktionen, eigenem Modell, eigenen Werkzeugen, eigenem Wissen, eigenem Budget und eigenen Zugriffsregeln, auf Infrastruktur, die Sie kontrollieren.

Wenn Sie noch heute Nachmittag einen hilfsbereiten Kollegen im Chat haben möchten, ist Viktor schnell ausprobiert. Wenn Sie entscheiden möchten, was jeder Agent darf, was er kostet und wo die Daten liegen, gibt Ihnen AgenticOS diese Kontrolle.

Verantwortlich: das AgenticOS-Team. Quellen geprüft am 21. Oktober 2026. AgenticOS-Basis: v1.9.1. Umfang bei Viktor: die öffentlichen Produkt-, Preis-, Sicherheits- und Enterprise-Seiten sowie das Changelog, kein getestetes Konto und kein verhandelter Vertrag.

## Auf einen Blick { #at-a-glance }

| Bereich | Viktor | AgenticOS |
| --- | --- | --- |
| Was Sie bekommen | Einen gemeinsamen "KI-Mitarbeiter" pro Workspace | Beliebig viele Agents, jeder ein versionierter Spec |
| Wo es läuft | Die Cloud von Viktor, standardmäßig in den USA gehostet | Ihre Infrastruktur, mit Docker Compose |
| Quellcode | Proprietär | Apache-2.0 |
| Modelle | Modelle von OpenAI, Anthropic, Google und xAI zur Auswahl; Ihr eigener OpenRouter-Schlüssel | 28 Provider, darunter Ollama und LiteLLM auf Ihrer eigenen Hardware |
| Wissen | Workspace-Gedächtnis und verbundene Werkzeuge | Dokumentensammlungen in Ihrem Postgres, mit fünf Sync-Konnektoren |
| Oberflächen | Slack, Teams, Discord, ein eigenes E-Mail-Postfach, Web-, Desktop- und Mobil-Apps, API | Web-Chat, Widget, gehostete Seite, HTTP-API, WebSocket, Slack, Telegram, Mattermost |
| Zugriff | Auf Workspace-Ebene; seine Seiten machen unterschiedliche Angaben zu rollenbasiertem Zugriff | Sechs Rollen, 33 Berechtigungen und Grants pro Ressource, pro Organisation |
| Ausgabenkontrolle | Der Credit-Pool mit einer monatlichen Obergrenze für automatisches Aufladen; Limits pro Nutzer im Enterprise-Tarif | Ein monatliches Budget pro Agent und pro Organisation, vor jeder Modellanfrage geprüft |
| Preise | Free mit Credits im Wert von bis zu 100 $; Team für 100 $ im Monat für 40.000 geteilte Credits; Enterprise individuell | Keine Lizenzgebühr; Sie bezahlen Modell-Provider und Infrastruktur |
| Compliance-Nachweise | SOC 2 Type 1; Type II und ISO 27001 in Arbeit | Ihre Kontrollen auf Ihrer Infrastruktur; siehe [Sicherheit](../security.md) |

## Wo AgenticOS weiter geht { #where-agenticos-goes-further }

### Viele Agents, jeder mit einer Aufgabe { #many-agents-each-with-a-job }

Viktor ist ein Teammate, den sich der ganze Workspace teilt. In AgenticOS wird jeder Agent für seine eigene Aufgabe gebaut, etwa ein Agent für HR-Richtlinien, ein Vertriebsassistent oder ein Agent für die Support-Triage. Jeder hat eigene Instruktionen, [Capabilities](../reference/capabilities.md), Wissenssammlungen und ein eigenes Budget.

Der Spec eines Agents wird [bei der Veröffentlichung versioniert](../concepts.md#version) und [als YAML exportiert](../features.md#exportable-into-your-own-repository), in Ihr Git-Repository. Benannte [Umgebungen](../environments.md#what-an-environment-is) erlauben es, eine Version in Staging zu testen, bevor die Produktion damit antwortet.

### Zugriff pro Agent und pro Person entschieden { #access-decided-per-agent-and-per-person }

Die FAQ auf Viktors Startseite, geprüft am 21. Oktober 2026, besagt, dass alle Teammitglieder eines Tarifs eine Viktor-Instanz und einen Kontext teilen und dass ein verbundenes Werkzeug mit dem ganzen Team geteilt oder, in Slack-Workspaces, privat gehalten werden kann. Seine Enterprise-Seite nennt rollenbasierten Zugriff. Fragen Sie, was für Ihren Vertrag gilt.

In AgenticOS ergibt sich der Zugriff aus dem [Berechtigungskatalog](../permissions.md#the-built-in-roles), und [Grants](../permissions.md#layer-3-visibility-and-grants) teilen einen Agent, einen Skill oder eine Sammlung mit einer Person oder einer Gruppe. Eine MCP-Bindung kann [das eigene Konto jeder Person](../mcp.md#whose-account-a-binding-speaks-through) verwenden statt eines gemeinsamen Logins. Ein verknüpfter Slack-Benutzer läuft [als er selbst](../channels.md#slack).

### Ein Budget pro Agent, nicht nur ein Credit-Pool { #a-budget-per-agent-not-only-a-credit-pool }

Viktor rechnet einen Credit-Pool pro Workspace ab und gibt an, dass Credits dem entsprechen, was Modell-Provider berechnen. AgenticOS hat keine Credits. Jeder Agent hat ein [monatliches Budget](../governance.md#budgets), das [vor jeder Modellanfrage](../governance.md#enforcement-is-before-the-request) geprüft wird. Ein fehlgeschlagener Run erfasst seine Ausgaben trotzdem, und eine [Benachrichtigung](../governance.md#alerts) informiert die Personen Ihrer Wahl, wenn ein Agent seine Obergrenze erreicht.

### Ihre Daten bleiben, wo Sie sie ablegen { #your-data-stays-where-you-put-it }

Viktor wird in den USA gehostet. Seine Seiten machen unterschiedliche Angaben zu EU-Datenresidenz und konfigurierbarer Aufbewahrung; lassen Sie sich daher beides schriftlich bestätigen. AgenticOS speichert Konversationen, Dokumente und Vektoren in [Ihrem eigenen Postgres](../data-protection.md#where-personal-data-lives). Sie legen die [Aufbewahrung pro Datenklasse](../governance.md#retention) fest. Mit einem lokalen Modell muss nichts Ihr Netzwerk verlassen.

### Wissen, das Sie prüfen können { #knowledge-you-can-inspect }

Viktor lernt aus Konversationen und verbundenen Werkzeugen. AgenticOS ergänzt verwaltete Dokumentensammlungen: Sie wählen [Parser](../file-processing.md#parser-selection-rag) und [Chunking](../file-processing.md#chunking-configuration) pro Sammlung. Sie können aus Google Drive, S3, SharePoint oder OneDrive, einer Website oder einem Git-Repository synchronisieren. Eine Synchronisierung [entfernt Dokumente](../howto/configure-sync-sources.md#what-a-sync-removes), die die Quelle nicht mehr aufführt.

## Wann Viktor genügt { #when-viktor-is-enough }

- Sie möchten einen Assistenten in Slack oder Teams, ohne Infrastruktur betreiben zu müssen.
- Sein Katalog von mehr als 3.200 OAuth-Integrationen und seine Code-Sandbox decken Ihre Aufgaben ab.
- Credit-Abrechnung und Hosting in den USA erfüllen Ihre Anforderungen.
- Sie brauchen heute Microsoft Teams, Sprache oder ein E-Mail-Postfach. AgenticOS hat noch keinen Konversationskanal für Teams, Sprache oder E-Mail.

## Eine Handbuchfrage ausprobieren { #try-one-handbook-question }

Verwenden Sie das [gemeinsame Dokumentenbeispiel](../howto/first-document-agent.md). Vergleichen Sie Quellenzugriff, die tatsächliche Antwort, eine Frage zu einer fehlenden Regel und eine Aktualisierung der Quelle. Prüfen Sie, welche Identität die Quelle abrufen kann und wie der Zugriff entzogen wird, wenn jemand das Unternehmen verlässt.

Betreiben Sie dann in jedem Produkt einen zweiten Agent für ein anderes Team. Prüfen Sie, ob er die Integrationen und das Gedächtnis des ersten Teams sehen kann. An diesem zweiten Agent unterscheiden sich ein Workspace-Teammate und eine Agent-Plattform am stärksten. Erfassen Sie das Ergebnis mit der [Vergleichsmethode](comparison.md#a-shared-trial).

## Häufig gestellte Fragen { #frequently-asked-questions }

### Ist AgenticOS eine Alternative zu Viktor? { #is-agenticos-an-alternative-to-viktor }

Ja, wenn Sie mehr als einen gemeinsamen Assistenten möchten. AgenticOS betreibt viele Agents, jeder mit eigenen Instruktionen, eigenem Zugriff, eigenem Wissen und eigenem Budget, auf Ihrer eigenen Infrastruktur. Viktor ist in Slack oder Teams schneller startklar und läuft in seiner eigenen Cloud.

### Kann AgenticOS wie Viktor in Slack antworten? { #can-agenticos-answer-in-slack-like-viktor }

Ja. Ein veröffentlichter Agent antwortet in Slack, und ein verknüpfter Benutzer läuft als er selbst. AgenticOS antwortet außerdem in Telegram, Mattermost, einem Website-Widget, auf einer gehosteten Seite und über die HTTP-API. Einen Kanal für Microsoft Teams hat es noch nicht.

### Wie unterscheiden sich die Preise? { #how-does-pricing-compare }

Viktor verkauft Credits pro Workspace: Team kostet 100 $ im Monat für 40.000, die der ganze Workspace teilt. AgenticOS hat keine Lizenzgebühr: Sie bezahlen die Modell-Provider direkt, und jeder Agent hat sein eigenes monatliches Budget.

### Wo werden die Daten gespeichert? { #where-is-the-data-stored }

Viktor gibt an, standardmäßig in den USA gehostet zu sein; EU-Datenresidenz bietet eine Seite in Enterprise-Verträgen an, eine andere führt sie auf der Roadmap. AgenticOS speichert Konversationen, Dokumente und Vektoren in Ihrem eigenen Postgres, wo auch immer Sie es bereitstellen.

## Verwandte Vergleiche { #related-comparisons }

[AgenticOS vs Claude](claude-apps.md) · [AgenticOS vs ChatGPT](chatgpt.md) · [AgenticOS vs Wonderful](wonderful.md) · [Alle Vergleiche](comparison.md)

## Quellen { #sources }

- [Viktor-Produktseite und FAQ](https://viktor.com/): Positionierung, gemeinsame Workspace-Instanz, mit dem Team geteilte oder private Integrationen, Zugriff auf Workspace-Ebene.
- [Preise](https://viktor.com/pricing): Credit-Tarife Free, Team und Enterprise, Ausgabenobergrenzen, keine Gebühr pro Nutzer.
- [Sicherheit](https://viktor.com/security): Hosting standardmäßig in den USA, SOC 2 Type 1, ISO 27001 in Arbeit, SAML SSO.
- [Enterprise](https://www.viktor.com/enterprise): Identität aus Slack oder Teams übernommen, EU-Datenresidenz und Aufbewahrung auf der Roadmap.
- [Changelog](https://www.viktor.com/changelog): OpenRouter-Schlüssel, Modelle zur Auswahl, Discord und E-Mail.
