---
title: "AgenticOS vs Agents in Slack"
seo_title: "AgenticOS vs Claude Tag und Slackbot: Agents in Slack"
description: "Claude Tag und Slackbot im Vergleich mit AgenticOS: der Agent eines Anbieters in einem Werkzeug oder Unternehmens-Agents in Slack, Teams, E-Mail und Telefon."
source_sha: "8e7bcb5cfd45"
---

# AgenticOS vs Agents in Slack { #agenticos-vs-agents-in-slack }

2026 kam der „KI-Teammate im Kanal“ in den Werkzeugen an, die Menschen schon nutzen. Claude Tag bringt Claude von Anthropic als gemeinsames Teammitglied in Slack-Kanäle, mit Ausgabenlimits pro Organisation und pro Kanal. Slackbot von Salesforce wurde zum persönlichen Agent, der Arbeit an Agentforce und Agents von Drittanbietern weiterleitet. Beide sind mit einem Klick installiert. AgenticOS bringt die eigenen Agents des Unternehmens ebenfalls in Slack, und gleichzeitig in Microsoft Teams, E-Mail, SMS und ans Telefon, mit jedem Modell und auf Ihren Servern.

Verantwortlich: das AgenticOS-Team. Quellen geprüft am 26. November 2026. AgenticOS-Basis: v1.95.0. Umfang: die Ankündigung von Claude Tag durch Anthropic vom 23. Juni 2026 und die Ankündigung von Slackbot durch Salesforce vom 13. Januar 2026, keine getesteten Workspaces.

## Auf einen Blick { #at-a-glance }

| Bereich | Claude Tag | Slackbot | AgenticOS |
| --- | --- | --- | --- |
| Was es ist | Claude als gemeinsames Teammitglied in Slack-Kanälen | Ein persönlicher Agent in Slack und Zugang zu Agentforce und anderen Agents | Unternehmens-Agents mit Besitzern, Versionen und Budgets, in vielen Kanälen |
| Wo es arbeitet | Slack; weitere Plattformen angekündigt | Slack | Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, E-Mail, iMessage, Telefonanrufe, Web-Chat, Widget, gehostete Seite, HTTP-API |
| Modelle | Nur Claude | Wahl von Salesforce | 28 Provider, auch lokale; ein anderes Modell pro Agent |
| Wo es läuft | Cloud von Anthropic | Cloud von Salesforce | Ihre Infrastruktur |
| Ausgabenkontrolle | Token-Ausgabenlimits pro Organisation und pro Kanal | Salesforce-Editionen und Credits | Ein monatliches Budget pro Agent und pro Organisation, geprüft vor jeder Modellanfrage |
| Freigaben | Nicht beschrieben | Läuft mit den Berechtigungen des Nutzers | Freigabe pro Capability, Werkzeug und MCP-Verbindung, als [Schaltflächen im Chat](../channels.md#approvals-and-questions-as-buttons) |
| Audit | In den Admin-Werkzeugen von Claude | In Slack und Salesforce | Ein Audit-Log mit Manipulationsnachweis über alle Kanäle |
| Preise | In den Plänen Claude Team und Enterprise enthalten | Slack Business+ und Enterprise+ | Keine Lizenz- oder Arbeitsplatzgebühr; Modellnutzung zu den Preisen Ihres Providers |

## Wo AgenticOS weiter geht { #where-agenticos-goes-further }

### Ein Agent in jedem Werkzeug, nicht ein Werkzeug pro Agent { #one-agent-in-every-tool-not-one-tool-per-agent }

Der Agent jedes Anbieters lebt in einem Produkt. Ein Unternehmen auf Slack und Teams, mit Kunden per E-Mail und Telefon, endet mit mehreren Assistenten, die Unterschiedliches wissen. Ein veröffentlichter AgenticOS-Agent antwortet in [Slack](../channels.md#slack), [Microsoft Teams](../channels.md#microsoft-teams), per [E-Mail](../channels.md#email), [SMS](../channels.md#sms) und [Telefonanruf](../voice.md#telephone-calls) mit einem Satz Instruktionen, einer Wissensdatenbank, einem Budget und einem Audit-Log.

### Jedes Modell, pro Agent { #any-model-per-agent }

Claude Tag nutzt Claude. AgenticOS kann Claude in einem Agent und einen anderen Provider im nächsten verwenden und ein [Modellprofil](../models.md#a-model-profile) wechseln, ohne die Agents neu zu veröffentlichen, die es nutzen.

### Ein Budget pro Agent { #a-budget-per-agent }

Claude Tag begrenzt Ausgaben pro Organisation und pro Kanal. AgenticOS begrenzt jeden Agent, prüft die Obergrenze [vor jeder Modellanfrage](../governance.md#enforcement-is-before-the-request) und rechnet [delegierte Arbeit](../governance.md#delegation-spends-the-parents-budget) dem delegierenden Agent an.

### Freigaben dort, wo die Anfrage entsteht { #approvals-where-the-request-happens }

Ein Werkzeugaufruf, der eine Entscheidung braucht, erscheint als [Schaltflächen im selben Chat](../channels.md#approvals-and-questions-as-buttons) oder in der Konsole und der Telefon-App, für die Personen Ihrer Wahl. Anfragen eines verknüpften Nutzers [laufen als diese Person](../channels.md#slack).

### Ihre Server { #your-servers }

Gespräche aus Ihren Kanälen bleiben auf Ihrer Infrastruktur. Siehe [was standardmäßig das System verlässt](../data-protection.md#nothing-leaves-by-default).

## Wann ein Slack-Agent besser passt { #when-a-slack-agent-is-the-better-fit }

- Das ganze Unternehmen ist auf Slack und bei einem Modellanbieter, und eine Installation mit einem Klick zählt mehr als Kontrolle.
- Die Leute wollen eher einen persönlichen Assistenten in Slack als Unternehmens-Agents mit Besitzern und Budgets.
- Niemand ist verfügbar, um eine Plattform bereitzustellen und zu betreiben.

## Häufig gestellte Fragen { #frequently-asked-questions }

### Kann AgenticOS Claude in Slack nutzen wie Claude Tag? { #can-agenticos-use-claude-in-slack-like-claude-tag }

Ja. Ein AgenticOS-Agent kann auf Claude laufen und in Slack antworten, während ein anderer Agent in Microsoft Teams ein anderes Modell nutzt. Beide schreiben ins selbe Audit-Log und verbrauchen ihre eigenen Budgets.

### Funktioniert AgenticOS auch in Microsoft Teams? { #does-agenticos-work-in-microsoft-teams-too }

Ja. Derselbe veröffentlichte Agent antwortet gleichzeitig in Teams, Slack und den anderen Kanälen.

### Gibt es Claude Tag außerhalb von Slack? { #is-claude-tag-available-outside-slack }

Zum Start im Juni 2026 funktionierte Claude Tag in Slack, weitere Plattformen waren angekündigt. Prüfen Sie die aktuelle Seite von Anthropic.

## Verwandte Vergleiche { #related-comparisons }

[AgenticOS vs Claude](claude-apps.md) · [AgenticOS vs Viktor](viktor.md) · [AgenticOS vs Copilot Studio](copilot-studio.md) · [Alle Vergleiche](comparison.md)

## Quellen { #sources }

- [Introducing Claude Tag](https://www.anthropic.com/news/introducing-claude-tag): der Slack-Agent und seine Ausgabenlimits.
- [Slackbot-Ankündigung](https://www.salesforce.com/news/press-releases/2026/01/13/slackbot-announcement/): Slackbot als persönlicher Agent und Zugang zu anderen Agents.
