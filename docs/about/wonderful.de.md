---
source_sha: "08e94982c326"
title: "AgenticOS vs Wonderful"
description: "Vergleich einer geschlossenen, von Teams des Anbieters gelieferten Plattform mit einer offenen Plattform, die Ihnen gehört, und separat vereinbarter Implementierungshilfe."
---

# AgenticOS vs Wonderful { #agenticos-vs-wonderful }

Wonderful verkauft eine geschlossene Enterprise-KI-Plattform zusammen mit Forward-Deployed-Teams, die die Agents in Ihrer Organisation bauen und die Verantwortung schrittweise übergeben. AgenticOS ist eine offene Plattform, die Ihrer Organisation vom ersten Tag an gehört. Ihr Quellcode steht unter Apache-2.0, sie läuft auf Ihrer Infrastruktur, und Implementierungshilfe von Vstorm wird separat vereinbart.

Die Frage ist weniger, welche Software besser ist, als vielmehr, was Ihnen am Ende des Projekts gehören soll: ein Vertrag mit einem Plattformanbieter oder die Plattform selbst.

Verantwortlich: das AgenticOS-Team bei Vstorm. Quellen geprüft am 25. September 2026. AgenticOS-Basis: v0.0.504. Umfang bei Wonderful: die öffentlichen Seiten zu AI OS, Deployment, Agents, Gateway und Sicherheit sowie die Finanzierungsankündigung, kein verhandelter Vertrag und kein getestetes Konto.

## Auf einen Blick { #at-a-glance }

| Bereich | Wonderful | AgenticOS |
| --- | --- | --- |
| Was Sie kaufen | Eine Plattform mit Deployment-Teams und Strategen | Software, die Sie betreiben; Implementierungshilfe separat vereinbart |
| Quellcode | Proprietär; Export von Agents und Konfiguration über UI oder API | Apache-2.0; die gesamte Plattform ist lesbar und forkbar |
| Wo es läuft | Mandantenfähiges SaaS, Single-Tenant, Ihre Cloud oder vom Netz getrennt On-Premises | Ihre Infrastruktur, mit Docker Compose |
| Preise | Nicht veröffentlicht; über den Vertrieb | Keine Lizenzgebühr; Modelle, Infrastruktur und etwaige vereinbarte Leistungen |
| Kanäle | Sprache, Chat, E-Mail, WhatsApp und SMS | Web-Chat, Widget, gehostete Seite, HTTP-API, WebSocket, Slack, Telegram, Mattermost |
| Modelle | Von der Plattform pro Aufgabe geroutet | Ihre Wahl aus 27 Providern, pro Modellprofil festgelegt |
| Governance | AI Gateway mit Budgetobergrenzen pro Team und Audit-Logs | Budgets pro Agent und pro Organisation, Freigaben und ein Audit-Log mit Manipulationsnachweis |
| Compliance-Angaben | SOC 2 Type II, ISO 27001:2022, PCI DSS, DSGVO | Ihre Kontrollen auf Ihrer Infrastruktur; siehe [Sicherheit](../security.md) |

## Wo AgenticOS weiter geht { #where-agenticos-goes-further }

### Ihnen gehört die Plattform, nicht eine Lizenz dafür { #you-own-the-platform-not-a-licence-to-it }

Wonderful beschreibt Exporte von Agents, Skills, Werkzeugen und Governance-Konfiguration sowie eine Headless-API. Das ist eine echte Zusage. Die Laufzeitumgebung bleibt geschlossen, sodass ein exportierter Agent weiterhin einen Ort braucht, an dem er läuft.

Bei AgenticOS ist die Laufzeitumgebung der Teil, der Ihnen gehört. Der Quellcode steht unter Apache-2.0, Specs [werden als YAML exportiert](../features.md#exportable-into-your-own-repository), in Ihr Repository, und die Daten liegen in [Ihrem Postgres](../data-protection.md#where-personal-data-lives). Wenn Sie sich von Vstorm trennen, läuft die Bereitstellung weiter, und ein anderes Team kann sie betreiben.

### Ein Kostenmodell, das Sie vor der Unterschrift sehen { #a-cost-model-you-can-see-before-you-sign }

Wonderful veröffentlicht keine Preise. AgenticOS hat keine Lizenzgebühr und keine Gebühr pro Nutzer. Sie bezahlen Ihre Modell-Provider zu deren Tarifen, die [Kostenansicht](../governance.md#what-the-cost-screen-shows) zeigt, was jeder Agent ausgegeben hat, und [Budgets](../governance.md#budgets) stoppen einen Agent vor der nächsten Modellanfrage, sobald er seine Obergrenze erreicht. Der Implementierungsumfang mit Vstorm wird pro Projekt vereinbart.

### Ihr Team behält das Know-how { #your-team-keeps-the-know-how }

Das Liefermodell von Wonderful geht schrittweise von einer von Wonderful geführten Arbeit zur Verantwortung beim Kunden über. AgenticOS ist so gebaut, dass Ihre eigenen Leute von Anfang an Agents ändern können. Ein fachlicher Verantwortlicher bearbeitet die Instruktionen und veröffentlicht eine [Version](../concepts.md#version). Ein Entwickler fügt eine [Capability](../howto/add-capability.md) in typisiertem Python hinzu, und sie steht danach allen zur Verfügung.

### Kontrollen, die Sie prüfen können { #controls-you-can-inspect }

Die Zertifizierungen von Wonderful decken seinen eigenen Dienst ab. Bei AgenticOS prüfen Sie die Kontrollen selbst: den [Berechtigungskatalog](../permissions.md), den [Vault](../secrets.md#envelope-encryption), das [Audit-Log](../governance.md#audit) und seine Hash-Kette sowie die [Ablehnungstests](../security.md#the-refusals-as-a-set), die in der CI laufen. Das [HIPAA-Profil](../security.md#the-hipaa-profile-and-what-it-does-not-claim) und das Kommando `data-protection-report` liefern Nachweise für eine Bereitstellung. Ihre Zertifizierung deckt Ihre Bereitstellung ab.

## Wann Wonderful besser passt { #when-wonderful-is-the-better-fit }

- Sie möchten, dass ein Anbieter die Lieferung vollständig verantwortet, über viele Märkte und Sprachen hinweg.
- Kundenseitige Agents für Sprache, WhatsApp oder SMS sind der Hauptanwendungsfall. AgenticOS hat keinen dieser Kanäle.
- Sie brauchen die eigenen Zertifizierungen eines Anbieters, etwa SOC 2 Type II und PCI DSS, statt Ihrer eigenen Kontrollen.

## Fragen für die Liefervereinbarung { #questions-for-the-delivery-agreement }

Stellen Sie beiden Anbietern dieselben Fragen.

| Bereich | Vor dem Pilotprojekt klären |
| --- | --- |
| Infrastruktur | Wo läuft jede Komponente, und wer aktualisiert und stellt sie wieder her? |
| Daten und Zugriff | Welche Dienste erhalten Daten, und wer pflegt Identitäten und Zugangsdaten? |
| Prozess | Wer definiert die Aufgabe, behandelt Ausnahmen und nimmt die Ergebnisse ab? |
| Support | Wer bearbeitet Vorfälle, mit welcher vereinbarten Abdeckung? |
| Ausstieg | Welchen Code, welche Konfiguration und welche Daten kann der Kunde behalten, und läuft es ohne den Anbieter weiter? |

Mit AgenticOS kann Vstorm die Installation auf der Infrastruktur des Kunden, Dokumentation, Prozessgestaltung und individuelle Entwicklung besprechen. Support, Wartung, Integrationen und Reaktionszusagen werden für das Projekt vereinbart; sie kommen nicht automatisch mit dem Repository.

Definieren Sie eine überprüfbare Aufgabe anhand des [Dokumentenbeispiels](../howto/first-document-agent.md) und des [Betriebsleitfadens](../rollout.md). Für Implementierungshilfe wenden Sie sich an [Vstorm](https://vstorm.co/) oder an Kacper. Vergleichen Sie den vereinbarten Lieferumfang zusammen mit den [Softwarekriterien](comparison.md).

## Quellen { #sources }

- [Wonderful AI OS](https://www.wonderful.ai/ai-os): Komponenten, Modellwahl, Bereitstellungsoptionen und Compliance-Angaben.
- [Deployment](https://www.wonderful.ai/deployment): die vier Bereitstellungsmodelle und die Forward-Deployed-Teams.
- [Agents](https://www.wonderful.ai/agents): Kanäle, Workspaces, Versionierung und Berechtigungen.
- [AI Gateway](https://www.wonderful.ai/ai-gateway): Budgetobergrenzen, Modellzugriff nach Rolle und Audit-Logs.
- [Open by default](https://www.wonderful.ai/blog-articles/open-by-default-competitive-by-design): Exporte und die Headless-API.
- [Ankündigung der Series C](https://www.wonderful.ai/blog-articles/wonderful-raises-550m-series-c): Märkte, Unternehmensgröße und Bereitstellung On-Premises.
