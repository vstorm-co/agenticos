---
title: "AgenticOS vs deepset"
seo_title: "AgenticOS vs deepset Haystack Enterprise Platform"
description: "Die Haystack Enterprise Platform von deepset im Vergleich mit AgenticOS: souveräne KI-Pipelines mit Behördenreferenzen gegen eine offene Plattform."
source_sha: "d53a219041fc"
---

# AgenticOS vs deepset { #agenticos-vs-deepset }

Die Haystack Enterprise Platform von deepset, früher deepset AI Platform, nennt sich „die Plattform für souveräne KI“. Sie baut, betreibt und steuert Agents und Pipelines auf dem Open-Source-Framework Haystack, in der Cloud, selbst gehostet oder netzwerkisoliert, und seit Oktober 2026 auch auf STACKIT. Sie betreibt AI@EC, die KI-Plattform der Europäischen Kommission. AgenticOS ist die Open-Source-Alternative, bei der die gesamte Anwendung unter Apache-2.0 steht, nicht nur das Framework, und bei der Agents Mitarbeiter in ihren eigenen Kanälen erreichen.

Verantwortlich: das AgenticOS-Team. Quellen geprüft am 26. November 2026. AgenticOS-Basis: v1.95.0. Umfang bei deepset: Produktseite, die Fallstudie der Europäischen Kommission und Partnermeldungen, keine getestete Bereitstellung. Preise sind nicht veröffentlicht.

## Auf einen Blick { #at-a-glance }

| Bereich | deepset Haystack Enterprise Platform | AgenticOS |
| --- | --- | --- |
| Was es ist | Eine Plattform zum Bauen, Betreiben und Steuern von Haystack-Agents und -Pipelines | Eine Plattform für Unternehmens-Agents, Workflows, Apps und Tabellen |
| Lizenz | Proprietäre Plattform; Haystack-Framework Apache-2.0 | Apache-2.0 für die gesamte Anwendung; siehe [Lizenzen der enthaltenen Komponenten](../licenses.md) |
| Wo es läuft | Cloud, selbst gehostet oder netzwerkisoliert; auf STACKIT seit 15. Oktober 2026 | Ihre Infrastruktur, auch netzwerkisoliert |
| Modelle | Beliebige | 28 Provider, auch lokale |
| Bauen | Visueller Pipeline-Builder für Entwickler und KI-Teams | Ein Builder für Fachteams; eine visuelle [Workflow](../workflows.md)-Arbeitsfläche; Capabilities in Python |
| Evaluierungen | Ja | [Eval-Runs](../evals.md) und Suites über versionierte Datasets |
| Governance | Zugriffskontrolle und Observability | Budgets pro Agent, geprüft vor jeder Modellanfrage, Freigaben, Audit mit Manipulationsnachweis, sechs Rollen und Berechtigungen |
| Mandanten | Nicht beschrieben | Viele Organisationen in einer Bereitstellung |
| Kanäle | Auf der Plattform gebaute Anwendungen und APIs | Web-Chat, Widget, gehostete Seite, HTTP-API, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, E-Mail, iMessage, Telefonanrufe; Desktop- und Telefon-Apps |
| Referenzen | Europäische Kommission (AI@EC); Partner Celonis, HPE, NTT DATA, Materna | Früheres Stadium: noch keine vergleichbare Referenz im öffentlichen Sektor |
| Preise | Über den Vertrieb | Keine Lizenzgebühr; Modellnutzung zu den Preisen Ihres Providers |

## Wo AgenticOS weiter geht { #where-agenticos-goes-further }

### Open Source bis ganz oben { #open-source-all-the-way-up }

Haystack ist offen, die darauf gebaute Plattform aber proprietär. AgenticOS veröffentlicht die gesamte Anwendung unter Apache-2.0: Konsole, Governance, Kanäle und Worker. Eine Behörde oder ein Integrator kann jede Kontrolle prüfen und den Code weiter betreiben, wenn die Beziehung zum Anbieter endet.

### Agents in den Kanälen, die Mitarbeiter nutzen { #agents-in-the-channels-employees-use }

deepset liefert Pipelines und Anwendungen. Ein veröffentlichter AgenticOS-Agent antwortet in [Slack](../channels.md#slack), [Microsoft Teams](../channels.md#microsoft-teams), per [E-Mail](../channels.md#email), [SMS](../channels.md#sms), [Telefonanruf](../voice.md#telephone-calls) und in einem [Website-Widget](../channels.md#the-website-widget), mit [Desktop-](../desktop.md) und [Telefon-App](../mobile.md) für Freigaben.

### Budgets und Freigaben auf jedem Agent { #budgets-and-approvals-on-every-agent }

AgenticOS stoppt die nächste Modellanfrage eines Agents an seinem [Budget](../governance.md#enforcement-is-before-the-request), hält einen Werkzeugaufruf an, bis die richtige Person ihn [freigibt](../governance.md#approvals), und schreibt beides ins [Audit-Log](../governance.md#audit).

### Kein Vertriebsprozess zum Start { #no-sales-process-to-start }

Sie können AgenticOS heute aus seinem Repository installieren und einen Pilot auf Ihrer eigenen Hardware fahren. deepset wird über seinen Vertrieb und Partner verkauft.

## Wann deepset besser passt { #when-deepset-is-the-better-fit }

- Sie brauchen einen Anbieter mit Referenzen im öffentlichen Sektor wie der Europäischen Kommission oder eine fertige Präsenz auf STACKIT.
- Ihr Team baut Retrieval-Pipelines in Haystack und will eine verwaltete Plattform darum.
- Sie brauchen heute ein Partnernetz für Verteidigungs- oder netzwerkisolierte Projekte.

## Häufig gestellte Fragen { #frequently-asked-questions }

### Ist AgenticOS eine souveräne KI-Plattform wie deepset? { #is-agenticos-a-sovereign-ai-platform-like-deepset }

Beide laufen auf Ihrer Infrastruktur, auch netzwerkisoliert, mit jedem Modell. In AgenticOS steht die gesamte Anwendung unter Apache-2.0, abgesehen von enthaltenen Komponenten mit eigenen Lizenzen wie dem AGPL-3.0-PDF-Parser; bei deepset ist das Haystack-Framework offen und die Plattform proprietär.

### Kann AgenticOS auf STACKIT oder einer anderen europäischen Cloud laufen? { #can-agenticos-run-on-stackit-or-another-european-cloud }

AgenticOS läuft mit Docker Compose oder seinem [Helm-Chart](../kubernetes.md) auf jeder Infrastruktur, die die Ressourcen aus dem [Bereitstellungsleitfaden](../deploy.md) bietet. Validieren Sie den konkreten Anbieter, bevor Sie sich darauf verlassen; eine STACKIT-Bereitstellung hat das AgenticOS-Team noch nicht dokumentiert.

## Verwandte Vergleiche { #related-comparisons }

[AgenticOS vs Mistral](mistral.md) · [AgenticOS vs Langdock](langdock.md) · [AgenticOS vs Dust](dust.md) · [Alle Vergleiche](comparison.md)

## Quellen { #sources }

- [Haystack Enterprise Platform](https://deepset.ai/products-and-services/deepset-ai-platform): Produktbeschreibung und Bereitstellungsoptionen.
- [Europäische Kommission und deepset](https://deepset.ai/case-studies/european-commission-x-deepset-building-europes-sovereign-ai-platform): die Fallstudie zu AI@EC.
- [Celonis und deepset](https://www.celonis.com/news/press/made-in-germany-celonis-and-deepset-build-sovereign-ai-platform-for-mission-critical-operations): die Partnerschaft für eine souveräne Plattform.
- [deepset-News](https://deepset.ai/news): Verfügbarkeit auf STACKIT ab 15. Oktober 2026 und die Partnerschaften mit HPE, NTT DATA und Materna.
- [Introducing Haystack Enterprise Platform](https://www.deepset.ai/blog/introducing-haystack-enterprise-platform): die Umbenennung von deepset AI Platform.
- [Haystack](https://github.com/deepset-ai/haystack): das Apache-2.0-Framework.
