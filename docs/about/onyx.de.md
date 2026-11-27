---
title: "AgenticOS vs Onyx"
seo_title: "AgenticOS vs Onyx: Firmensuche oder Unternehmens-Agents"
description: "Onyx und AgenticOS im Vergleich: Enterprise-Suche und Chat gegen gesteuerte Unternehmens-Agents, ee-Lizenz, Ausgabenlimits, Freigaben, Kanäle, Preise."
source_sha: "e335c0e76f47"
---

# AgenticOS vs Onyx { #agenticos-vs-onyx }

Onyx ist eine Open-Source-KI-Plattform rund um die Firmensuche: Chat mit beliebigen Modellen über mehr als 40 Konnektoren, mit Agents, MCP und Bots in Slack und Discord. AgenticOS beginnt beim Agent: Jeder hat einen Besitzer, Versionen, ein Budget und Freigaben und antwortet in vielen Kanälen. Wenn Retrieval über viele SaaS-Quellen die ganze Aufgabe ist, ist Onyx stark. Wenn Agents im Namen des Unternehmens handeln, unterscheidet sich die Governance.

Verantwortlich: das AgenticOS-Team. Quellen geprüft am 26. November 2026. AgenticOS-Basis: v1.95.0. Umfang bei Onyx: Repository, Lizenzdateien, Dokumentation und Preisseite, keine getestete Bereitstellung.

## Auf einen Blick { #at-a-glance }

| Bereich | Onyx | AgenticOS |
| --- | --- | --- |
| Was es ist | Chat und Enterprise-Suche über Unternehmensquellen, mit Agents | Versionierte Unternehmens-Agents, Workflows, Apps und Tabellen, im Browser gebaut |
| Lizenz | MIT, mit `ee`-Verzeichnissen unter der Onyx Enterprise License | Apache-2.0; siehe [Lizenzen der enthaltenen Komponenten](../licenses.md) |
| Wo es läuft | Selbst gehostet, auch netzwerkisoliert, oder Onyx-Cloud | Ihre Infrastruktur |
| Wissen | Über 40 Konnektoren, starkes Retrieval | [Wissensdatenbanken](../file-processing.md) mit Parser-Kontrolle und synchronisierenden Konnektoren; noch kein Reranker |
| Ausgabenkontrolle | Ausgabenlimits pro Workspace in Business, pro Nutzer und Gruppe in Enterprise | Ein monatliches Budget pro Agent und pro Organisation, geprüft vor jeder Modellanfrage |
| Freigaben | Vom Nutzer bestätigt, in der Funktion Craft | Freigabe pro Capability, Werkzeug und MCP-Verbindung, entschieden von den Personen Ihrer Wahl |
| Rollen und Anmeldung | Eigene Rollen und SCIM in Enterprise | Sechs Rollen und Berechtigungen pro Ressource; OIDC-SSO, LDAP und Kerberos |
| Mandanten | Eine Organisation pro selbst gehosteter Installation | Viele Organisationen in einer Bereitstellung |
| Kanäle | Web, Slack- und Discord-Bots, Widget, Desktop-App, Chrome-Erweiterung | Web-Chat, Widget, gehostete Seite, HTTP-API, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, E-Mail, iMessage, Telefonanrufe; Desktop- und Telefon-Apps |
| Preise | Community kostenlos; Business 20 USD pro Nutzer im Monat; Enterprise individuell | Keine Lizenzgebühr; Modellnutzung zu den Preisen Ihres Providers |

## Wo AgenticOS weiter geht { #where-agenticos-goes-further }

### Ein Agent ist ein Objekt mit Besitzer { #an-agent-is-an-object-with-an-owner }

In AgenticOS ist ein Agent ein [versionierter Spec](../concepts.md#version): Instruktionen, Modell, Capabilities und Budget, veröffentlicht als Version, die [Umgebungen](../environments.md#what-an-environment-is) weitergeben und die sich als YAML exportieren lässt. Ein fachlicher Besitzer ändert ihn im [Builder](../features.md#exportable-into-your-own-repository), und jede Änderung bleibt später lesbar.

### Governance im Open-Source-Produkt { #governance-in-the-open-source-product }

Der Produktionseinsatz der `ee`-Verzeichnisse von Onyx braucht eine Lizenz für die Zahl der Arbeitsplätze, und Ausgabenlimits pro Nutzer und Gruppe, SCIM und eigene Rollen sind Enterprise-Funktionen. AgenticOS liefert [Budgets](../governance.md#enforcement-is-before-the-request), [Freigaben](../governance.md#approvals), das [Audit-Log mit Manipulationsnachweis](../governance.md#audit) und die [Verzeichnisanmeldung](../directory.md#signing-in-with-a-directory-account) in jeder Bereitstellung, ohne Gebühr pro Arbeitsplatz.

### Freigabe durch jemand anderen als den Nutzer { #approval-by-someone-other-than-the-user }

Ein Werkzeugaufruf in AgenticOS kann auf eine Person Ihrer Wahl warten, [benachrichtigt](../governance.md#alerts) über die Konsole, einen Kanal oder die [Telefon-App](../mobile.md). Onyx beschreibt die Bestätigung durch den Nutzer in seiner Funktion Craft.

### Kanäle über den Chat hinaus { #channels-beyond-chat }

Derselbe veröffentlichte Agent antwortet in [Microsoft Teams](../channels.md#microsoft-teams), per [E-Mail](../channels.md#email), [SMS](../channels.md#sms), [Telefonanruf](../voice.md#telephone-calls) und auf einer [gehosteten Seite](../channels.md#a-hosted-page), und andere Agents erreichen ihn über [A2A](../channels.md#a2a).

## Wann Onyx besser passt { #when-onyx-is-the-better-fit }

- Die Suche über viele SaaS-Quellen ist die Hauptaufgabe, und seine Konnektoren decken Ihre Systeme ab.
- Die Retrieval-Qualität über diese Quellen ist Ihnen wichtiger als die Steuerung dessen, was Agents tun.
- Eine Organisation pro Installation genügt, und Preise pro Arbeitsplatz passen für Sie.

## Eine Änderung vergleichen, nicht nur eine Antwort { #compare-a-change-not-only-an-answer }

Verbinden Sie in beiden Produkten dieselbe Quelle und stellen Sie die Fragen des [ersten Dokumenten-Agents](../howto/first-document-agent.md). Geben Sie dann einem Agent ein Werkzeug, das etwas Harmloses ändert, verlangen Sie die Freigabe einer zweiten Person und begrenzen Sie sein Budget auf wenige Cent. Halten Sie fest, was jedes Produkt erlaubt, ablehnt und protokolliert, nach der [Vergleichsmethode](comparison.md#a-shared-trial).

## Häufig gestellte Fragen { #frequently-asked-questions }

### Ist Onyx Open Source? { #is-onyx-open-source }

Größtenteils MIT. Code in seinen `ee`-Verzeichnissen steht unter der Onyx Enterprise License, die für den Produktionseinsatz eine Arbeitsplatzlizenz verlangt. AgenticOS hat kein Enterprise-Verzeichnis: Sein eigener Code steht unter Apache-2.0, und enthaltene Komponenten behalten ihre eigenen Lizenzen, etwa der AGPL-3.0-Standard-PDF-Parser ([Details](../licenses.md#the-agpl-component)).

### Ersetzt AgenticOS eine Enterprise-Suche? { #does-agenticos-replace-enterprise-search }

Es antwortet aus Wissensdatenbanken mit synchronisierten Konnektoren und Parser-Kontrolle, sein Schwerpunkt sind aber Agents, die handeln. Wenn die Suche über Dutzende SaaS-Werkzeuge der Hauptbedarf ist, vergleichen Sie zuerst die Konnektor-Abdeckung.

### Laufen beide netzwerkisoliert? { #can-both-run-air-gapped }

Ja. Onyx dokumentiert eine netzwerkisolierte Bereitstellung, und AgenticOS läuft mit lokalen Modellen, lokalen Embeddings und lokalem Parsing auf Ihrer eigenen Hardware.

## Verwandte Vergleiche { #related-comparisons }

[AgenticOS vs Open WebUI und LibreChat](open-webui-librechat.md) · [AgenticOS vs DIY-Stack](diy-stack.md) · [AgenticOS vs Dify](dify.md) · [Alle Vergleiche](comparison.md)

## Quellen { #sources }

- [Onyx-Repository](https://github.com/onyx-dot-app/onyx): Funktionen, Konnektoren, Bereitstellungsoptionen und die zitierte Lizenzaufteilung.
- [Onyx-Preise](https://onyx.app/pricing): die Pläne Community, Business und Enterprise.
- [Ausgabenlimits](https://docs.onyx.app/admins/advanced_configs/spending_limits): Limits pro Workspace, Nutzer und Gruppe.
