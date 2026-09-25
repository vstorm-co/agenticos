---
source_sha: "73d658736c90"
title: "AgenticOS vs Dify"
description: "Vergleich zweier selbst gehosteter Agent-Plattformen nach Lizenz, Mandantenfähigkeit, Governance und der Art, wie ein Team einen Agent ändert."
---

# AgenticOS vs Dify { #agenticos-vs-dify }

Beide Produkte lassen sich selbst hosten und beide beherrschen Dokumenten-Retrieval, der Unterschied liegt also woanders. Dify ist eine visuelle Arbeitsfläche für LLM-Apps und Workflows, mit mehreren Workspaces, SSO und Audit-Logs in seiner Enterprise-Edition. AgenticOS steht unter Apache-2.0 und ist bereits im Open-Source-Produkt mandantenfähig; Budgets, Freigaben, Verzeichnisanmeldung und ein Audit-Log mit Manipulationsnachweis sind enthalten.

Verantwortlich: das AgenticOS-Team. Quellen geprüft am 25. September 2026. AgenticOS-Basis: v0.0.504. Umfang bei Dify: das öffentliche Repository in Version 1.17.1, seine Lizenz, Dokumentation und Preisseite, kein getesteter Cloud-Tarif und keine fest versionierte Bereitstellung.

## Auf einen Blick { #at-a-glance }

| Bereich | Dify Community Edition | AgenticOS |
| --- | --- | --- |
| Wie Sie bauen | Eine visuelle Arbeitsfläche aus Workflow-, Chatflow- und Agent-Knoten | Instruktionen, ein Modellprofil, Capabilities, Sammlungen und ein Budget, als Version veröffentlicht |
| Lizenz | Dify Open Source License: Apache 2.0 mit zusätzlichen Bedingungen | Apache-2.0; siehe [Lizenzen der mitgelieferten Komponenten](../licenses.md) |
| Mandantenfähigkeit | Ein Workspace; mehrere Workspaces sind Enterprise | Viele Organisationen in einer Bereitstellung |
| Rollen | Vier eingebaute Rollen; eigene Rollen sind Enterprise | Sechs Rollen, 27 Berechtigungen und Grants pro Ressource für Personen und Gruppen |
| Anmeldung | E-Mail; SSO ist Enterprise | E-Mail, Google, OIDC SSO, LDAP und Kerberos, mit Zuordnung von Verzeichnisgruppen |
| Audit | Enterprise | Manipulationssicheres Audit-Log mit Export als CSV und JSONL |
| Ausgabenkontrolle | Abrechnung beim Provider oder Nachrichten-Credits in der Cloud | Ein monatliches Budget pro Agent und pro Organisation, vor jeder Modellanfrage geprüft |
| Menschliche Freigabe | Ein Human-Input-Knoten in einem Workflow | Freigabe pro Capability und pro Werkzeug; der Run wartet, bis jemand entscheidet |
| Oberflächen | Web-App, Embed, API, MCP-Server; Slack über ein Plugin | Web-Chat, Widget, gehostete Seite, HTTP-API, WebSocket, Slack, Telegram, Mattermost |
| Kubernetes | Helm-Charts aus der Community; offizielle Hochverfügbarkeit ist Enterprise | Docker Compose auf einem Host |

## Wo AgenticOS weiter geht { #where-agenticos-goes-further }

### Mandantenfähig ohne kommerzielle Lizenz { #multi-tenant-without-a-commercial-licence }

Difys Lizenz erlaubt die kommerzielle Nutzung und fügt zwei Bedingungen hinzu. Sie dürfen ohne schriftliche Genehmigung keine mandantenfähige Umgebung betreiben, wobei ein Mandant ein Workspace ist. Sie dürfen das Logo oder die Copyright-Angaben im Frontend weder entfernen noch ändern. Beitragende stimmen außerdem zu, dass der Hersteller die Lizenzbedingungen ändern kann.

AgenticOS steht unter Apache-2.0. [Organisationen](../concepts.md#organizations) sind Mandanten, im Schema isoliert, und eine Bereitstellung kann jede Abteilung, jede Tochtergesellschaft oder jeden Kunden bedienen. Sie können die Konsole ändern und unter Ihrer eigenen Marke führen. Die Einstellungen zur [Identität der Bereitstellung](../deployment.md) umfassen Namen und Hinweise.

### Die Kontrollen, die ein Unternehmen verlangt, im Open-Source-Produkt { #the-controls-an-enterprise-asks-for-in-the-open-source-product }

Die Preisseite von Dify führt SSO nur für Enterprise, und seine Dokumentation ordnet eigene Rollen und mehrere Workspaces Enterprise zu. In AgenticOS sind sie Teil des Apache-2.0-Produkts:

- [OIDC Single Sign-on](../configuration.md#single-sign-on-generic-oidc) mit Entra, Okta, Keycloak und anderen, [LDAP und Kerberos](../directory.md#signing-in-with-a-directory-account) sowie die [Zuordnung von Verzeichnisgruppen](../directory.md#directory-group-mappings) zu Rollen.
- [Sechs Rollen und Grants pro Ressource](../permissions.md#layer-3-visibility-and-grants), die den Zugriff auf einen Agent oder eine Sammlung erweitern.
- Ein [Audit-Log mit Manipulationsnachweis](../governance.md#audit), geschrieben in derselben Transaktion wie die Aktion, die es festhält.
- [Aufbewahrungsfristen](../governance.md#retention) pro Datenklasse und [per Envelope-Verschlüsselung geschützte Secrets](../secrets.md#envelope-encryption), pro Organisation versiegelt.

### Ein Budget, das den nächsten Modellaufruf stoppt { #a-budget-that-stops-the-next-model-call }

Die Dokumentation von Dify beschreibt für die Community Edition keine Ausgabengrenze, die vor Modellaufrufen durchgesetzt wird. Mit Ihren eigenen Schlüsseln läuft die Abrechnung über das Konto des jeweiligen Providers.

AgenticOS prüft das [monatliche Budget](../governance.md#budgets) jedes Agents und die Obergrenze der Organisation [vor jeder Modellanfrage](../governance.md#enforcement-is-before-the-request) und erfasst auch die Kosten eines fehlgeschlagenen Runs. [Delegierte Arbeit](../governance.md#delegation-spends-the-parents-budget) verbraucht das Budget des übergeordneten Agents, sodass ein Sub-Agent es nicht umgehen kann.

### Freigabe am Werkzeug, nicht nur im Ablauf { #approval-on-the-tool-not-only-in-the-flow }

Der Human-Input-Knoten von Dify pausiert einen Workflow und sendet ein Formular, und die Anfrage schließt nach der ersten Antwort. In AgenticOS wird eine [Freigabe](../governance.md#approvals) pro Capability festgelegt und kann pro Werkzeug überschrieben werden. Der Run wartet, die Personen Ihrer Wahl werden [benachrichtigt](../governance.md#alerts), und eine zweite Entscheidung über eine bereits entschiedene Freigabe wird abgelehnt.

### Eine Änderung, die ein Fachteam vornehmen kann { #a-change-a-business-team-can-make }

In Dify ändern Sie einen Prozess, indem Sie die Arbeitsfläche bearbeiten. In AgenticOS bearbeitet ein fachlicher Verantwortlicher die Instruktionen oder schaltet eine Capability ein und veröffentlicht dann. Jede [Version](../concepts.md#version) bleibt lesbar, [Umgebungen](../environments.md#the-workflow-it-is-for) befördern eine getestete Version, und der Spec [wird als YAML exportiert](../features.md#exportable-into-your-own-repository), zur Prüfung in einem Pull Request. Konfiguration erreicht nur, was Entwickler registriert haben, und das macht einen No-Code-Builder sicher.

## Wann Dify besser passt { #when-dify-is-the-better-fit }

- Ihr Team denkt in Flussdiagrammen und möchte eine visuelle Arbeitsfläche aus Knoten, Schleifen und Verzweigungen. AgenticOS hat keine Workflow-Arbeitsfläche.
- Sie brauchen seine Marketplace-Plugins, seine hybride Suche mit Rerank oder seine vielen Observability-Integrationen. AgenticOS hat noch keinen Reranker und kein Trace-Dashboard.
- Ein Workspace genügt, oder die Bedingungen der Enterprise-Edition passen zu Ihnen.

## Eine Änderung vergleichen, nicht nur eine Antwort { #compare-a-change-not-only-an-answer }

Verwenden Sie dasselbe [synthetische Handbuch](../howto/first-document-agent.md), dieselben Fragen und dieselben Referenzprüfungen. Erfassen Sie auf beiden Seiten Version, Modell, Einstellungen der Quellenverarbeitung und Identität. Ändern Sie dann den Verantwortlichen für die Anfrage in der Quelle und wiederholen Sie den Versuch nach der Verarbeitung.

Ergänzen Sie zwei Prüfungen, die die oben genannten Unterschiede zeigen. Legen Sie einen zweiten Mandanten für ein zweites Team an, geben Sie einem Agent ein Budget von wenigen Cent und lassen Sie ihn über die Obergrenze hinaus laufen. Erfassen Sie mit der [Vergleichsmethode](comparison.md#a-shared-trial), was jedes Produkt erlaubt, ablehnt und protokolliert.

## Quellen { #sources }

- [Dify-Repository](https://github.com/langgenius/dify): Editionen, Funktionen und Release 1.17.1.
- [Dify-Lizenz](https://github.com/langgenius/dify/blob/main/LICENSE): die oben zitierten Bedingungen zu Mandantenfähigkeit und Logo.
- [Preise](https://dify.ai/pricing): Cloud-Tarife und die Funktionen, die nur Enterprise bietet.
- [Enterprise](https://dify.ai/enterprise): SSO, SCIM, eigene Rollen, Audit-Logs und Bereitstellungsoptionen.
- [Teammitglieder](https://docs.dify.ai/en/self-host/use-dify/workspace/team-members-management) und [Workspaces](https://docs.dify.ai/en/self-host/use-dify/workspace/readme): Rollen und Installationen mit einem einzigen Workspace.
- [Human-Input-Knoten](https://docs.dify.ai/en/self-host/use-dify/nodes/human-input): Freigabeverhalten in Workflows.
