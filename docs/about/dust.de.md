---
title: "AgenticOS vs Dust"
seo_title: "AgenticOS vs Dust: gehostet oder auf Ihren Servern"
description: "Dust und AgenticOS im Vergleich: ein französisches SaaS für Unternehmens-Agents gegen eine Apache-2.0-Plattform, die Sie hosten. Hosting, Limits, Audit, Preise."
source_sha: "be4cedd13c05"
---

# AgenticOS vs Dust { #agenticos-vs-dust }

Dust bezeichnet sich als Multiplayer-Betriebssystem für Unternehmens-KI: Agents, die auf Unternehmensdaten arbeiten, mit MCP als Client und Server und Agents in Slack, Microsoft Teams, E-Mail und Zendesk. Es ist ein gehosteter Dienst in einer US- oder EU-Region, mit Single-Tenant-Hosting in Enterprise. AgenticOS bietet Agents für denselben Käufer auf Infrastruktur, die Sie selbst betreiben, unter Apache-2.0 und ohne Arbeitsplatzgebühr.

Verantwortlich: das AgenticOS-Team. Quellen geprüft am 26. November 2026. AgenticOS-Basis: v1.95.0. Umfang bei Dust: Website, Preisseite, Administratordokumentation und Presseberichte über die Finanzierung im Mai 2026, kein getesteter Workspace.

## Auf einen Blick { #at-a-glance }

| Bereich | Dust | AgenticOS |
| --- | --- | --- |
| Was es ist | Ein gehosteter Workspace für Unternehmens-Agents auf Unternehmensdaten | Eine Plattform für Unternehmens-Agents, Workflows, Apps und Tabellen, die Sie selbst betreiben |
| Lizenz | Proprietär | Apache-2.0; siehe [Lizenzen der enthaltenen Komponenten](../licenses.md) |
| Wo es läuft | Dust-Cloud, US- oder EU-Region; Single-Tenant in Enterprise; kein Selbsthosting | Ihre Infrastruktur, jede Cloud oder On-Premises |
| Modelle | Mehrere Provider | 28 Provider, auch lokale |
| Ausgabenkontrolle | Kreditlimits pro Person, Gruppe und API-Schlüssel, geprüft vor jeder Nachricht | Ein monatliches Budget pro Agent und pro Organisation, geprüft vor jeder Modellanfrage |
| Audit | Mit Manipulationsnachweis in Enterprise | Audit-Log mit Manipulationsnachweis in jeder Bereitstellung |
| MCP | Client und Server | Client und [Server](../mcp.md#agenticos-as-an-mcp-server) |
| Kanäle | Web, Slack, Microsoft Teams, E-Mail, Zendesk | Web-Chat, Widget, gehostete Seite, HTTP-API, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, E-Mail, iMessage, Telefonanrufe |
| Preise | Pro 24 €, Max 120 € pro Nutzer und Monat bei jährlicher Abrechnung; Enterprise individuell | Keine Lizenz- oder Arbeitsplatzgebühr; Modellnutzung zu den Preisen Ihres Providers |

## Wo AgenticOS weiter geht { #where-agenticos-goes-further }

### Hosting nach Ihrer Wahl { #hosting-you-choose }

Dust läuft nur in seiner eigenen Cloud. AgenticOS läuft [dort, wo Sie es bereitstellen](../deploy.md), auch On-Premises und netzwerkisoliert, mit lokalen Modellen, wenn Ihre Daten nicht hinaus dürfen. Siehe [was standardmäßig das System verlässt](../data-protection.md#nothing-leaves-by-default).

### Limits am Agent, nicht nur an der Person { #limits-on-the-agent-not-only-on-the-person }

Dust begrenzt Kredite pro Person, Gruppe und API-Schlüssel. AgenticOS begrenzt zusätzlich jeden Agent: ein [monatliches Budget](../governance.md#budgets), geprüft [vor jeder Modellanfrage](../governance.md#enforcement-is-before-the-request), sodass ein Agent, der in eine Schleife gerät oder stark genutzt wird, an seiner eigenen Grenze stoppt, ohne jemand anderen zu blockieren.

### Governance im Open-Source-Produkt { #governance-in-the-open-source-product }

Das [Audit-Log mit Manipulationsnachweis](../governance.md#audit), [Freigaben](../governance.md#approvals), die [Verzeichnisanmeldung](../directory.md#signing-in-with-a-directory-account) und [viele Organisationen](../concepts.md#organizations) sind in jeder AgenticOS-Bereitstellung enthalten, nicht einem Enterprise-Vertrag vorbehalten.

### Keine Arbeitsplatzgebühr { #no-seat-fee }

Dust berechnet pro Nutzer. AgenticOS berechnet nichts pro Nutzer; Sie bezahlen Modell-Provider und betreiben die Infrastruktur, selbst oder mit Vstorm.

## Wann Dust besser passt { #when-dust-is-the-better-fit }

- Sie wollen einen verwalteten Dienst, der in Minuten startet, und haben kein Team für den Serverbetrieb.
- Seine Konnektoren und die Zendesk-Integration decken Ihre Systeme ab.
- SAML und SCIM sind Pflicht; AgenticOS hat beides noch nicht.

## Eine Änderung vergleichen, nicht nur eine Antwort { #compare-a-change-not-only-an-answer }

Bauen Sie in beiden Produkten denselben Agent auf denselben Dokumenten. Begrenzen Sie die Ausgaben des Agents auf wenige Cent und prüfen Sie, was an der Grenze passiert. Fragen Sie dann Ihr Sicherheitsteam, welches der beiden alle Prompts und Dokumente in Ihrem Netz halten kann. Halten Sie die Ergebnisse nach der [Vergleichsmethode](comparison.md#a-shared-trial) fest.

## Häufig gestellte Fragen { #frequently-asked-questions }

### Lässt sich Dust selbst hosten? { #can-dust-be-self-hosted }

Laut seinen öffentlichen Seiten nicht: Es läuft in der Dust-Cloud, in einer US- oder EU-Region, mit Single-Tenant-Hosting in Enterprise. AgenticOS ist von Grund auf selbst gehostet.

### Hat Dust Ausgabenlimits? { #does-dust-have-spend-limits }

Ja, Kreditlimits pro Person, Gruppe und API-Schlüssel, geprüft vor jeder Nachricht. AgenticOS ergänzt ein Budget pro Agent und pro Organisation, geprüft vor jeder Modellanfrage.

## Verwandte Vergleiche { #related-comparisons }

[AgenticOS vs Langdock](langdock.md) · [AgenticOS vs deepset](deepset.md) · [Agents in Slack](slack-agents.md) · [Alle Vergleiche](comparison.md)

## Quellen { #sources }

- [Dust](https://dust.tt) und [Preise](https://dust.tt/pricing): Produktbeschreibung, Hosting-Regionen und Pläne.
- [Kreditverwaltung](https://docs.dust.tt/docs/user-documentation/admins/usage-seats-and-credits/credit-management): Kreditlimits pro Person, Gruppe und API-Schlüssel.
- [Dust sammelt 40 Mio. USD in einer Series B](https://tech.eu/2026/05/18/dust-raises-40m-series-b-to-build-the-multiplayer-operating-system-for-enterprise-ai/): die Beschreibung als „Multiplayer-Betriebssystem“.
