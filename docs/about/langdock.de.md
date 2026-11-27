---
title: "AgenticOS vs Langdock"
seo_title: "AgenticOS vs Langdock: EU-SaaS pro Platz oder eigene Server"
description: "Langdock und AgenticOS im Vergleich: eine deutsche KI-Plattform pro Arbeitsplatz gegen Apache-2.0-Agents auf Ihren Servern. Limits, SSO, Freigaben, Kosten."
source_sha: "b9b5fcbeb158"
---

# AgenticOS vs Langdock { #agenticos-vs-langdock }

Langdock ist eine deutsche KI-Plattform für Unternehmen mit Chat, Agents, Workflows und Apps, gehostet auf Azure in der EU. Unter den europäischen SaaS-Produkten bietet sie die vollständigste Governance: SAML und SCIM in jedem Plan, bis zu fünf eigene Rollen, monatliche Limits pro Agent, die sperren oder auf ein Ersatzmodell umschalten, Freigaben in Workflows, Agent-Evaluierungen und einen MCP-Server. AgenticOS deckt einen Großteil derselben Governance als Open Source auf Ihren eigenen Servern ab, ohne Arbeitsplatzgebühr, und hat noch kein SAML, kein SCIM und keine eigenen Rollen.

Verantwortlich: das AgenticOS-Team. Quellen geprüft am 26. November 2026. AgenticOS-Basis: v1.95.0. Umfang bei Langdock: Preisseite und Administratordokumentation, kein getesteter Workspace.

## Auf einen Blick { #at-a-glance }

| Bereich | Langdock | AgenticOS |
| --- | --- | --- |
| Was es ist | Ein KI-Workspace pro Arbeitsplatz mit Chat, Agents, Workflows und Apps | Eine Plattform für Unternehmens-Agents, Workflows, Apps und Tabellen, die Sie selbst betreiben |
| Lizenz | Proprietär | Apache-2.0; siehe [Lizenzen der enthaltenen Komponenten](../licenses.md) |
| Wo es läuft | SaaS auf Azure in der EU; Single-Tenant und On-Premises bei großen Verträgen | Ihre Infrastruktur, jede Cloud oder On-Premises |
| Modelle | Mehrere Modelle, in der EU gehostet, oder eigene Schlüssel | 28 Provider, auch lokale |
| Ausgabenkontrolle | Monatliche Limits pro Workspace, Person, Gruppe, Agent und Workflow, sperrend oder mit Wechsel auf ein Ersatzmodell | Ein monatliches Budget pro Agent und pro Organisation, geprüft vor jeder Modellanfrage |
| Freigaben | In Workflows, an benannte Empfänger geleitet | Freigabe pro Capability, Werkzeug und MCP-Verbindung, an die Personen Ihrer Wahl geleitet |
| Anmeldung und Rollen | SAML und SCIM in jedem Plan; bis zu fünf eigene Rollen | OIDC-SSO, LDAP und Kerberos; sechs eingebaute Rollen und Berechtigungen pro Ressource; noch kein SAML, SCIM oder eigene Rollen |
| Evaluierungen | Agent-Evaluierungen | [Eval-Runs](../evals.md) und Suites über versionierte Datasets |
| Audit | Audit-API, 90 Tage | Audit-Log mit Manipulationsnachweis und selbst festgelegter Aufbewahrung |
| Kanäle | Web, Slack, Microsoft Teams, Office, Desktop- und Telefon-Apps | Web-Chat, Widget, gehostete Seite, HTTP-API, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, E-Mail, iMessage, Telefonanrufe; Desktop- und Telefon-Apps |
| Preise | Core 23,20 €, Work 31,20 €, Max 99 € pro Nutzer und Monat bei jährlicher Abrechnung; Workflows 449 € pro Workspace und Monat | Keine Lizenz- oder Arbeitsplatzgebühr; Modellnutzung zu den Preisen Ihres Providers |

## Wo AgenticOS weiter geht { #where-agenticos-goes-further }

### Keine Arbeitsplatzgebühr { #no-seat-fee }

Langdock berechnet pro Nutzer. Für 200 Personen ergeben die veröffentlichten Pläne grob 56.000 € bis 238.000 € im Jahr, vor Workflow-Zusätzen. AgenticOS hat keine Lizenz- oder Arbeitsplatzgebühr: Sie bezahlen Modell-Provider zu deren Preisen und betreiben die Infrastruktur, selbst oder mit Vstorm. Vergleichen Sie beide anhand Ihrer eigenen Nutzung, denn Pläne pro Arbeitsplatz enthalten Modellnutzung innerhalb von Grenzen, AgenticOS nicht.

### Ihre Server, ab dem ersten Nutzer { #your-servers-from-the-first-user }

Die dedizierten und On-Premises-Optionen von Langdock gibt es nur bei großen Verträgen. AgenticOS läuft von Anfang an auf [Ihrer Infrastruktur](../deploy.md), bei Bedarf mit lokalen Modellen, lokalen Embeddings und lokalem Parsing. Siehe [was standardmäßig das System verlässt](../data-protection.md#nothing-leaves-by-default).

### Offener Code, den Sie ändern können { #open-code-you-can-change }

AgenticOS steht unter Apache-2.0. Sie können jede Kontrolle lesen, nach der eine Prüfung fragt, die Konsole ändern und unter eigener Marke führen und mehrere Unternehmen aus einer Bereitstellung bedienen, mit [Organisationen](../concepts.md#organizations) als Mandanten.

### Mehr Kanäle { #more-channels }

Derselbe veröffentlichte Agent antwortet auch in Telegram, Mattermost, Discord, Matrix, per [SMS](../channels.md#sms), [E-Mail](../channels.md#email), iMessage und [Telefonanruf](../voice.md#telephone-calls) sowie in einem öffentlichen [Website-Widget](../channels.md#the-website-widget) oder auf einer [gehosteten Seite](../channels.md#a-hosted-page).

## Wann Langdock besser passt { #when-langdock-is-the-better-fit }

- Sie brauchen SAML, SCIM oder eigene Rollen heute. AgenticOS hat nichts davon; SAML funktioniert nur über einen Broker wie Keycloak.
- Sie wollen einen verwalteten EU-Dienst mit ISO-27001- und SOC-2-Type-II-Berichten und keine eigenen Server.
- Ihre Teams wollen einen Chat-Assistenten für jeden Mitarbeiter ebenso sehr wie Unternehmens-Agents.

## Eine Änderung vergleichen, nicht nur eine Antwort { #compare-a-change-not-only-an-answer }

Betreiben Sie denselben Agent in beiden Produkten mit einem Monatslimit von wenigen Cent und prüfen Sie, was am Limit passiert. Leiten Sie einen Werkzeugaufruf an eine zweite Person zur Freigabe. Rechnen Sie dann ein Jahr für Ihre Mitarbeiterzahl: Langdock-Arbeitsplätze gegen Infrastruktur und Modellnutzung bei AgenticOS. Halten Sie die Ergebnisse nach der [Vergleichsmethode](comparison.md#a-shared-trial) fest.

## Häufig gestellte Fragen { #frequently-asked-questions }

### Ist AgenticOS eine europäische Alternative zu Langdock? { #is-agenticos-a-european-alternative-to-langdock }

Es ist eine Open-Source-Alternative, die Sie hosten, wo Sie wollen, auch in der EU oder On-Premises. Vstorm, das es pflegt, ist ein polnisches Unternehmen. Langdock ist ein deutsches SaaS-Produkt.

### Hat Langdock Budgets pro Agent? { #does-langdock-have-budgets-per-agent }

Ja. Langdock setzt monatliche Limits pro Workspace, Person, Gruppe, Agent und Workflow und kann am Limit sperren oder auf ein Ersatzmodell umschalten. AgenticOS setzt ein Budget pro Agent und pro Organisation, geprüft vor jeder Modellanfrage, im Open-Source-Produkt.

### Was fehlt AgenticOS im Vergleich zu Langdock? { #what-does-agenticos-lack-compared-with-langdock }

SAML und SCIM, eigene Rollen und Sicherheitszertifizierungen für einen verwalteten Dienst. Ihre eigene AgenticOS-Bereitstellung zertifizieren Sie selbst; die [Sicherheitsseite](../security.md) ordnet ihre Kontrollen für eine Prüfung zu.

## Verwandte Vergleiche { #related-comparisons }

[AgenticOS vs Dust](dust.md) · [AgenticOS vs deepset](deepset.md) · [AgenticOS vs Mistral](mistral.md) · [Alle Vergleiche](comparison.md)

## Quellen { #sources }

- [Langdock-Preise](https://langdock.com/pricing): Pläne, Preise und Workflow-Zusatz.
- [Agent-Limits](https://docs.langdock.com/en/admin/manage-agents/agent-limits): Limits pro Agent und was am Limit passiert.
- [Langdock-Dokumentation](https://docs.langdock.com): SSO, SCIM, Rollen, Freigaben, Evaluierungen, MCP und Integrationen.
