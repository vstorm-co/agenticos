---
source_sha: "b7162a5c58d3"
title: "AgenticOS vs Copilot Studio"
seo_title: "AgenticOS vs Copilot Studio: selbst gehostete Alternative"
description: "Microsoft Copilot Studio vs. AgenticOS: keine Copilot Credits, jeder Modell-Provider, Ihre eigene Infrastruktur, Budgets pro Agent und offenes Audit."
---

# AgenticOS vs Copilot Studio { #agenticos-vs-copilot-studio }

Microsoft Copilot Studio erstellt Agents innerhalb von Power Platform. Es bietet Power-Platform-Connectoren, Veröffentlichung in Teams und Microsoft 365 sowie Governance über Purview und Entra, alles in der Cloud von Microsoft und abgerechnet in Copilot Credits. AgenticOS erstellt Agents auf Ihrer eigenen Infrastruktur, mit jedem Modell-Provider, und erhebt keine eigene Gebühr: Sie bezahlen den Provider für das Modell.

Wenn Ihr Unternehmen in Microsoft 365 lebt, ist Copilot Studio ein naheliegender Kandidat. AgenticOS ist der Kandidat, wenn Sie die Plattform besitzen, die Daten dort halten möchten, wo Sie es wählen, und einen Zähler pro Funktion vermeiden wollen.

Verantwortlich: das AgenticOS-Team. Quellen geprüft am 25. September 2026. AgenticOS-Stand: v0.0.504. Copilot-Studio-Umfang: die Preisseite von Microsoft, die Azure-Retail-Preis-API und Microsoft Learn, kein getesteter Tenant.

## Auf einen Blick { #at-a-glance }

| Bereich | Copilot Studio | AgenticOS |
| --- | --- | --- |
| Wo es läuft | Cloud von Microsoft, in Power-Platform-Umgebungen | Ihre Infrastruktur |
| Quellcode | Proprietär | Apache-2.0 |
| Modelle | Standardmäßig GPT-Modelle, Claude-Modelle allgemein verfügbar, Azure-Foundry-Modelle separat abgerechnet | 27 Provider, einschließlich lokaler |
| Abrechnung | 200 $ im Monat für 25.000 Copilot Credits oder 0,01 $ pro Credit bei nutzungsbasierter Abrechnung | Keine Lizenzgebühr; Modellnutzung zu den Tarifen Ihres Providers |
| Wie Nutzung gezählt wird | Credits pro Funktion: eine generative Antwort kostet 2, eine Agent-Aktion 5, Grounding über den Tenant-Graph 10 | Modell-Tokens, bepreist pro Provider |
| Durchsetzung der Ausgaben | Monatliche Limits pro Agent; Agents werden bei 125 % der vorausbezahlten Kapazität deaktiviert | Ein Budget pro Agent und pro Organisation, geprüft vor jeder Modellanfrage |
| Oberflächen | Teams, Microsoft 365, SharePoint, Web, WhatsApp, Sprache sowie Slack oder Telegram über Azure Bot Service | Web-Chat, Widget, gehostete Seite, HTTP-API, WebSocket, Slack, Telegram, Mattermost |
| Identität | Microsoft Entra ID | OIDC-SSO einschließlich Entra, LDAP und Kerberos |
| Governance | Datenrichtlinien von Power Platform, Purview-Audit, Entra Agent ID | Berechtigungskatalog, Grants, Freigaben und ein Audit-Log mit Manipulationsnachweis |

## Wo AgenticOS weiter geht { #where-agenticos-goes-further }

### Eine Rechnung, die sich aus dem Modellpreis vorhersagen lässt { #a-bill-you-can-predict-from-the-model-price }

Copilot Studio misst jede Funktion in Credits, schlägt für Reasoning-Modelle einen Premiumtarif auf und rechnet seinen neueren GitHub-Copilot-Harness ab dem Moment ab, in dem Sie mit dem Erstellen beginnen. AgenticOS erfasst die eigenen Kosten des Modells bei [jedem Run](../governance.md#what-run-history-shows) anhand eines mitgelieferten Preis-Snapshots. Ein Modell, das für den Snapshot zu neu ist, wird als [teilweise bepreist](../models.md#what-a-run-costs) erfasst, und ein selbst gehosteter Provider ohne Key erfasst keine Ausgaben. Das [Budget](../governance.md#budgets) eines Agents wird [vor jeder Modellanfrage](../governance.md#enforcement-is-before-the-request) geprüft, statt den Agent zu deaktivieren, sobald die Kapazität aufgebraucht ist.

### Jede Cloud, oder keine { #any-cloud-or-none }

Copilot Studio läuft in der Cloud von Microsoft. Microsoft weist darauf hin, dass Anthropic-Modelle außerhalb der EU Data Boundary liegen und in der EU, der EFTA und dem Vereinigten Königreich standardmäßig ausgeschaltet sind. AgenticOS läuft dort, wo Sie es bereitstellen. Sie können einen Provider in der Region wählen, die Sie brauchen, oder [das Modell selbst betreiben](../models.md#self-hosted), sodass Prompts Ihr Netzwerk nie verlassen.

### Jeder Modell-Provider gleichrangig { #every-model-provider-first-class }

Der Standard-Harness von Copilot Studio bietet GPT- und Claude-Modelle, mit Azure Foundry für eigene Modelle, separat abgerechnet. AgenticOS behandelt [27 Provider](../models.md#providers) gleich. Sie teilen ein gemeinsames Format für [Modellprofile](../models.md#a-model-profile), dieselben [Fallbacks](../models.md#fallbacks) und dieselbe Kostenerfassung.

### Offen dort, wo es für einen Prüfer zählt { #open-where-it-matters-to-an-auditor }

Die Governance von Copilot Studio ist innerhalb des Microsoft-Stacks stark. AgenticOS lässt Sie die Kontrollen selbst lesen: den [Berechtigungskatalog](../permissions.md), den [Vault](../secrets.md#envelope-encryption), die [Hash-Kette des Audits](../governance.md#audit) und die [Verweigerungstests](../security.md#the-refusals-as-a-set) in der CI. Der Spec [lässt sich als YAML exportieren](../features.md#exportable-into-your-own-repository), sodass ein Wechsel bedeutet, Ihre Agents zu behalten, statt sie neu zu bauen.

### Microsoft-Identität ohne Microsoft-Hosting { #microsoft-identity-without-microsoft-hosting }

AgenticOS meldet Personen mit Entra ID über [OIDC](../configuration.md#single-sign-on-generic-oidc) an, ordnet [Verzeichnisgruppen](../directory.md#the-groups-claim-over-oidc) Rollen zu und liest Dateien aus [SharePoint und OneDrive](../howto/configure-sync-sources.md#sharepoint-and-onedrive-setup). Sie behalten Microsoft als Quelle für Identität und Dokumente und betreiben die Agents selbst.

## Wann Copilot Studio besser passt { #when-copilot-studio-is-the-better-fit }

- Ihre Agents gehören in Teams und Microsoft 365 Copilot, und Ihre Benutzer haben bereits Lizenzen für Microsoft 365 Copilot.
- Sie benötigen Power-Platform-Connectoren, Agent-Flows, Sprache oder WhatsApp. AgenticOS hat keinen Kanal für Teams, Sprache oder WhatsApp.
- Purview, Sentinel und die Datenrichtlinien von Power Platform sind die Art, wie Ihre Organisation alles andere steuert.

## Auf einer Aufgabe ausprobieren { #try-it-on-one-task }

Erstellen Sie den [gemeinsamen Dokumenten-Agent](../howto/first-document-agent.md) in beiden, auf vergleichbaren Modellen. Stellen Sie hundert Fragen und vergleichen Sie die Rechnung: Credits auf der einen Seite, Modellkosten auf der anderen. Wählen Sie ein Modell, das der Preis-Snapshot abdeckt, damit der Wert in AgenticOS vollständig ist. Prüfen Sie dann, was passiert, wenn das Limit erreicht ist. Erfassen Sie das Ergebnis mit der [Vergleichsmethode](comparison.md#a-shared-trial).

## Häufig gestellte Fragen { #frequently-asked-questions }

### Ist AgenticOS eine Alternative zu Microsoft Copilot Studio? { #is-agenticos-an-alternative-to-microsoft-copilot-studio }

Ja, wenn Ihnen die Plattform selbst gehören soll. AgenticOS läuft auf Ihrer Infrastruktur, mit jedem Modell-Provider und ohne Credit-Zähler. Copilot Studio passt besser, wenn Agents in Teams und Microsoft 365 leben.

### Funktioniert AgenticOS mit Microsoft Entra ID und SharePoint? { #does-agenticos-work-with-microsoft-entra-id-and-sharepoint }

Ja. Personen melden sich mit Entra ID über OIDC an, Verzeichnisgruppen werden Rollen zugeordnet, und Sammlungen synchronisieren Dateien aus SharePoint und OneDrive.

### Was kostet Copilot Studio im Vergleich zu AgenticOS? { #how-much-does-copilot-studio-cost-compared-with-agenticos }

Copilot Studio verkauft 25.000 Copilot Credits für 200 $ im Monat oder 0,01 $ pro Credit bei nutzungsbasierter Abrechnung. AgenticOS erhebt keine eigene Gebühr; Sie bezahlen Ihren Modell-Provider für die Tokens, die ein Agent verbraucht.

### Kann AgenticOS Agents in Microsoft Teams veröffentlichen? { #can-agenticos-publish-agents-to-microsoft-teams }

Noch nicht. Es veröffentlicht im Web-Chat, in einem Widget, auf einer gehosteten Seite, über die HTTP-API, einen WebSocket, Slack, Telegram und Mattermost.

## Verwandte Vergleiche { #related-comparisons }

[AgenticOS vs Gemini Enterprise](gemini-enterprise.md) · [AgenticOS vs ChatGPT](chatgpt.md) · [AgenticOS vs n8n](n8n.md) · [Alle Vergleiche](comparison.md)

## Quellen { #sources }

- [Preise für Copilot Studio](https://www.microsoft.com/en-us/microsoft-365-copilot/pricing/copilot-studio): das Credit-Paket und die nutzungsbasierte Abrechnung.
- [Azure-Retail-Preise](https://prices.azure.com/api/retail/prices?$filter=contains(productName,'Copilot%20Studio')): 0,01 $ pro Credit.
- [Abrechnungssätze und Verwaltung](https://learn.microsoft.com/en-us/microsoft-copilot-studio/requirements-messages-management): Credits pro Funktion, Limits pro Agent und die Durchsetzung bei 125 %.
- [Harnesses](https://learn.microsoft.com/en-us/microsoft-copilot-studio/harnesses-overview) und [Abrechnung der Harnesses](https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/billing-credit-overview): Abrechnung ab der Erstellung.
- [Ein Modell auswählen](https://learn.microsoft.com/en-us/microsoft-copilot-studio/authoring-select-agent-model): verfügbare Modelle.
- [Anthropic als Unterauftragsverarbeiter](https://learn.microsoft.com/en-us/microsoft-365/copilot/connect-to-ai-subprocessor): der Ausschluss aus der EU Data Boundary.
- [Veröffentlichungskanäle](https://learn.microsoft.com/en-us/microsoft-copilot-studio/publication-fundamentals-publish-channels): Oberflächen und Authentifizierung.
