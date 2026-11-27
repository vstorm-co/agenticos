---
title: "AgenticOS vs Kortix"
seo_title: "AgenticOS vs Kortix CompanyOS: Lizenz und Selbsthosting"
description: "Kortix CompanyOS und AgenticOS im Vergleich: Elastic License 2.0 gegen Apache-2.0, wo Agent-Sessions laufen, Budgets, Freigaben, Anmeldung und Kanäle."
source_sha: "bf622c9110d0"
---

# AgenticOS vs Kortix { #agenticos-vs-kortix }

Kortix CompanyOS und AgenticOS beschreiben sich fast mit denselben Worten: ein Betriebssystem für ein Unternehmen, das mit KI-Agents arbeitet. Der Unterschied zeigt sich an zwei Stellen, die eine Rechts- oder IT-Prüfung zuerst ansieht. Kortix wechselte im Februar 2026 von Apache-2.0 zur Elastic License 2.0, und seine selbst gehostete Variante führt Agent-Sessions weiterhin in Cloud-Sandboxes von Kortix aus. AgenticOS steht unter Apache-2.0 und läuft vollständig auf Ihrer Infrastruktur.

Verantwortlich: das AgenticOS-Team. Quellen geprüft am 26. November 2026. AgenticOS-Basis: v1.95.0. Umfang bei Kortix: Website, Dokumentation, Preisseite und die Historie der Datei `LICENSE` in `kortix-ai/CompanyOS`, kein getesteter Workspace und keine selbst gehostete Bereitstellung.

## Auf einen Blick { #at-a-glance }

| Bereich | Kortix CompanyOS | AgenticOS |
| --- | --- | --- |
| Was es ist | Ein Unternehmen als Git-Repository: Agents, Skills, Gedächtnis und Konnektoren sind Dateien | Eine Konsole, in der ein Fachteam versionierte Agents, Workflows, Apps und Tabellen baut |
| Lizenz | Elastic License 2.0 seit 18. Februar 2026; vor Dezember 2025 Apache-2.0 | Apache-2.0; siehe [Lizenzen der enthaltenen Komponenten](../licenses.md) |
| Wo es läuft | Kortix-Cloud oder selbst gehostet Web, API und Datenbank; Agent-Sessions laufen weiter in Cloud-Sandboxes von Kortix | Ihre Infrastruktur, einschließlich der Sandbox; netzwerkisolierte Setups sind möglich |
| Modelle | Beliebige, mit eigenen Schlüsseln | 28 Provider, auch lokale |
| Ausgabenkontrolle | Ein tägliches, wöchentliches oder monatliches Budget pro Workspace, sperrend oder warnend | Ein monatliches Budget pro Agent und pro Organisation, geprüft vor jeder Modellanfrage |
| Freigaben | Allow, Ask oder Deny pro Werkzeug; entscheidet ein Workspace-Manager oder wer die Session gestartet hat | Freigabe pro Capability, Werkzeug und MCP-Verbindung; der Run wartet auf die Personen Ihrer Wahl |
| Anmeldung und Rollen | SAML-SSO, SCIM, Gruppen und eigene Rollen hinter einem Enterprise-Lizenzschlüssel | OIDC-SSO, LDAP und Kerberos, sechs Rollen und Berechtigungen pro Ressource in jeder Bereitstellung |
| Audit | Gesperrtes Archiv; Lesen braucht Enterprise | Audit-Log mit Manipulationsnachweis, Export als CSV und JSONL |
| Kanäle | Slack, Microsoft Teams, Telegram, Discord, E-Mail; Sprache experimentell | Web-Chat, Widget, gehostete Seite, HTTP-API, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, E-Mail, iMessage, Telefonanrufe |
| Preise | Kostenloser Plan mit 500 Credits; Credits ab 50 USD im Monat; Enterprise-Lizenzschlüssel | Keine Lizenzgebühr; Modellnutzung zu den Preisen Ihres Providers |

## Wo AgenticOS weiter geht { #where-agenticos-goes-further }

### Eine Lizenz, die das Hosten für andere erlaubt { #a-licence-that-lets-you-host-it-for-others }

Die Elastic License 2.0 ist eine Source-available-Lizenz, keine Open-Source-Lizenz. Sie verbietet, die Software Dritten als gehosteten oder verwalteten Dienst bereitzustellen, und die Funktion des Lizenzschlüssels zu verschieben, zu ändern oder zu umgehen. Bei Kortix schaltet der Schlüssel SAML, SCIM, Gruppen, eigene Rollen, das Lesen des Audit-Archivs und Branding frei.

Die Lizenz wechselte in weniger als einem Jahr dreimal: Apache-2.0 im April 2025, eine Kortix Non-Commercial License am 3. Dezember 2025, einen Tag später eine Kortix Public Source License und am 18. Februar 2026 die Elastic License 2.0. AgenticOS steht unter Apache-2.0: Sie dürfen es für jede Abteilung, Tochtergesellschaft oder jeden Kunden betreiben, ändern und unter eigener Marke führen.

### Selbsthosting, bei dem die Arbeit auf Ihren Servern bleibt { #self-hosting-that-keeps-the-work-on-your-servers }

Kortix dokumentiert, dass eine selbst gehostete Installation Web-App, API und Datenbank betreibt, während Agent-Sessions weiter in Cloud-Sandboxes von Kortix laufen, und dass der Server aus dem Internet erreichbar sein muss. Netzwerkisolierter Betrieb und vollständige Datenresidenz sind damit nicht möglich.

In AgenticOS ist die [Sandbox](../sandbox.md) Teil Ihrer Bereitstellung, und eine frische Installation sendet keine Prompts oder Dokumente nach außen. Siehe [was standardmäßig das System verlässt](../data-protection.md#nothing-leaves-by-default).

### Ein Budget pro Agent, nicht pro Workspace { #a-budget-per-agent-not-per-workspace }

Das Budget von Kortix gilt für einen ganzen Workspace. AgenticOS prüft das [monatliche Budget](../governance.md#budgets) jedes Agents und die Obergrenze der Organisation [vor jeder Modellanfrage](../governance.md#enforcement-is-before-the-request), und [delegierte Arbeit](../governance.md#delegation-spends-the-parents-budget) geht vom Budget des übergeordneten Agents ab. Sie wissen, welcher Agent was ausgegeben hat, und ein außer Kontrolle geratener Agent erschöpft nicht das Kontingent aller.

### Die Kontrollen einer Prüfung, ohne Lizenzschlüssel { #the-controls-a-review-asks-for-without-a-licence-key }

[OIDC-Single-Sign-on, LDAP und Kerberos](../directory.md#signing-in-with-a-directory-account), [sechs Rollen und Berechtigungen pro Ressource](../permissions.md#layer-3-visibility-and-grants) und das [Audit-Log mit Manipulationsnachweis](../governance.md#audit) sind in jeder AgenticOS-Bereitstellung enthalten. SAML und SCIM gibt es noch nicht; SAML funktioniert über einen Broker wie Keycloak.

### Viele Organisationen in einer Bereitstellung { #many-organizations-in-one-deployment }

[Organisationen](../concepts.md#organizations) in AgenticOS sind im Schema isolierte Mandanten. Kortix unterstützt mehrere Workspaces pro Konto und beschreibt keine Mandantenisolation auf Ihren eigenen Servern.

## Wann Kortix besser passt { #when-kortix-is-the-better-fit }

- Sie wollen ein Unternehmen vollständig als Dateien in einem Git-Repository beschreiben und mit einem Coding-Agent bearbeiten.
- Sie bevorzugen ein verwaltetes Cloud-Produkt, das in Minuten startet, und die Elastic License 2.0 passt zu Ihrer Nutzung.
- Sie brauchen SAML oder SCIM heute und kaufen den Enterprise-Lizenzschlüssel. AgenticOS hat beides noch nicht.

## Eine Änderung vergleichen, nicht nur eine Antwort { #compare-a-change-not-only-an-answer }

Führen Sie das Fixture des [ersten Dokumenten-Agents](../howto/first-document-agent.md) in beiden Produkten aus. Prüfen Sie dann, wo eine Session tatsächlich läuft, indem Sie die ausgehenden Verbindungen des selbst gehosteten Servers beobachten, während ein Agent arbeitet. Geben Sie einem Agent ein Budget von wenigen Cent und überschreiten Sie es. Halten Sie fest, was jedes Produkt erlaubt, ablehnt und protokolliert, nach der [Vergleichsmethode](comparison.md#a-shared-trial).

## Häufig gestellte Fragen { #frequently-asked-questions }

### Ist Kortix CompanyOS Open Source? { #is-kortix-companyos-open-source }

Nicht unter einer OSI-Lizenz. Sein Repository wechselte am 18. Februar 2026 zur Elastic License 2.0, die verbietet, es anderen als gehosteten Dienst anzubieten und den Lizenzschlüssel zu umgehen. AgenticOS steht unter Apache-2.0.

### Kann Kortix vollständig auf meinen eigenen Servern laufen? { #can-kortix-run-fully-on-my-own-servers }

Laut Dokumentation betreibt eine selbst gehostete Installation Web-App, API und Datenbank, Agent-Sessions laufen aber weiter in Cloud-Sandboxes von Kortix. AgenticOS betreibt jeden Teil, auch die Sandbox, auf Ihrer Infrastruktur.

### Hat Kortix Budgets und Freigaben? { #does-kortix-have-budgets-and-approvals }

Ja: ein Budget pro Workspace, das sperrt oder warnt, und Allow, Ask oder Deny pro Werkzeug. AgenticOS setzt ein Budget pro Agent und pro Organisation, geprüft vor jeder Modellanfrage, und leitet Freigaben an die Personen Ihrer Wahl.

## Verwandte Vergleiche { #related-comparisons }

[AgenticOS vs LobeHub](lobehub.md) · [AgenticOS vs Agno AgentOS](agno.md) · [Lizenzbedingungen im Vergleich](licence-terms.md) · [Alle Vergleiche](comparison.md)

## Quellen { #sources }

- [Kortix](https://kortix.com): Produktbeschreibung und Preisstufen.
- [Kortix-Dokumentation](https://kortix.com/docs/guide): Selbsthosting, Sandboxes, Budgets und Freigaben.
- [Lizenz von `kortix-ai/CompanyOS`](https://github.com/kortix-ai/CompanyOS/blob/main/LICENSE) und ihre Dateihistorie: die zitierten Bedingungen der Elastic License 2.0 und die früheren Lizenzen.
- [Elastic License 2.0](https://www.elastic.co/licensing/elastic-license): der Lizenztext.
