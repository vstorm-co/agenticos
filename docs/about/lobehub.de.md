---
title: "AgenticOS vs LobeHub"
seo_title: "AgenticOS vs LobeHub: Agents im Team, selbst gehostet"
description: "LobeHub und AgenticOS im Vergleich: LobeHub Community License gegen Apache-2.0, Team-Kanäle, Budgets, Freigaben, Audit, Rollen und Mandantenfähigkeit."
source_sha: "277af3a6a45c"
---

# AgenticOS vs LobeHub { #agenticos-vs-lobehub }

LobeHub nennt sein Produkt „Super-Agents in Ihrem Team“: Agents, die den Chat-Werkzeugen beitreten, die ein Team schon nutzt, mit einem Workspace, über 90 Providern, MCP, Gedächtnis und einem Skill-Marktplatz. AgenticOS gibt dasselbe Versprechen von Agents in den Kanälen des Teams. Die Unterschiede liegen in der Lizenz, der Governance um jeden Agent und darin, wie viele Organisationen eine Bereitstellung bedienen kann.

Verantwortlich: das AgenticOS-Team. Quellen geprüft am 26. November 2026. AgenticOS-Basis: v1.95.0. Umfang bei LobeHub: Website, Preisseite, Dokumentation und die Datei `LICENSE` in `lobehub/lobehub`, kein getesteter Workspace und keine selbst gehostete Bereitstellung.

## Auf einen Blick { #at-a-glance }

| Bereich | LobeHub | AgenticOS |
| --- | --- | --- |
| Was es ist | Ein KI-Workspace mit Agents, die Team-Chats beitreten | Eine Konsole, in der ein Fachteam versionierte Agents, Workflows, Apps und Tabellen baut |
| Lizenz | LobeHub Community License: Apache 2.0 mit zusätzlichen kommerziellen Bedingungen | Apache-2.0; siehe [Lizenzen der enthaltenen Komponenten](../licenses.md) |
| Wo es läuft | LobeHub-Cloud oder selbst gehostet mit Docker | Ihre Infrastruktur |
| Modelle | Über 90 Provider | 28 Provider, auch lokale |
| Kanäle | Discord, Slack, Telegram, LINE, WeChat, Feishu, DingTalk und weitere; WhatsApp und iMessage angekündigt; kein Microsoft Teams | Web-Chat, Widget, gehostete Seite, HTTP-API, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, E-Mail, iMessage, Telefonanrufe |
| Ausgabenkontrolle | Ein Kreditpool mit Nutzungsverfolgung | Ein monatliches Budget pro Agent und pro Organisation, geprüft vor jeder Modellanfrage |
| Freigaben | Bestätigt von der Person, die den Agent nutzt | Freigabe pro Capability, Werkzeug und MCP-Verbindung, entschieden von den Personen Ihrer Wahl |
| Rollen und Audit | Rollen und Audit im Workspace-Plan Business; SAML in Enterprise | Sechs Rollen, Berechtigungen pro Ressource, OIDC-SSO, LDAP, Kerberos und ein Audit-Log mit Manipulationsnachweis in jeder Bereitstellung |
| AgenticOS als MCP-Server | MCP-Client; eigener MCP-Server angekündigt | MCP-Client und [MCP-Server](../mcp.md#agenticos-as-an-mcp-server) |
| Preise | Persönliche Pläne 20, 100 und 200 USD im Monat; Workspace-Pläne ab 19,90 USD im Monat | Keine Lizenzgebühr; Modellnutzung zu den Preisen Ihres Providers |

## Wo AgenticOS weiter geht { #where-agenticos-goes-further }

### Eine Lizenz ohne kommerzielle Bedingungen { #a-licence-without-commercial-conditions }

Die LobeHub Community License basiert auf Apache 2.0 mit zusätzlichen Bedingungen. LobeHub darf kommerziell als Frontend- und Backend-Dienst genutzt werden, **ohne den Quellcode zu ändern**. Ein abgeleitetes Werk zu entwickeln und zu verbreiten braucht eine kommerzielle Lizenz des Herstellers, und Mitwirkende stimmen zu, dass der Hersteller die Bedingungen verschärfen kann. Geschäftsfunktionen sind nicht Teil des Open-Source-Builds.

AgenticOS steht unter Apache-2.0. Sie dürfen es ändern, unter eigener Marke führen und für andere betreiben. Siehe [Lizenzbedingungen im Vergleich](licence-terms.md).

### Governance auf jedem Agent { #governance-on-every-agent }

Ein AgenticOS-Agent hat einen Besitzer, veröffentlichte [Versionen](../concepts.md#version), ein [Budget](../governance.md#budgets), das vor jeder Modellanfrage geprüft wird, und [Freigaben](../governance.md#approvals), die an jemand anderen als die chattende Person gehen. Eine zweite Entscheidung zu einer entschiedenen Freigabe wird abgelehnt, und jede Aktion landet im [Audit-Log](../governance.md#audit). In LobeHub werden Ausgaben gegen einen Kreditpool verfolgt, und einen Werkzeugaufruf bestätigt sein Nutzer.

### Microsoft Teams, Telefon und E-Mail { #microsoft-teams-phone-and-email }

Ein veröffentlichter AgenticOS-Agent antwortet in [Microsoft Teams](../channels.md#microsoft-teams), per [E-Mail](../channels.md#email), [SMS](../channels.md#sms) und [Telefonanruf](../voice.md#telephone-calls) sowie in denselben Slack-, Telegram- und Discord-Kanälen, die LobeHub abdeckt. LobeHub führt keinen Teams-Kanal.

### Viele Organisationen in einer Bereitstellung { #many-organizations-in-one-deployment }

[Organisationen](../concepts.md#organizations) in AgenticOS sind im Schema isolierte Mandanten, sodass eine Bereitstellung mehrere Unternehmen oder Abteilungen bedient. LobeHub beschreibt keine Mandantenisolation für eine selbst gehostete Installation.

## Wann LobeHub besser passt { #when-lobehub-is-the-better-fit }

- Sie wollen ein ausgefeiltes Chat-Erlebnis auf Verbraucherniveau und einen großen Skill-Marktplatz für ein kleines Team.
- Ihre Teams arbeiten in LINE, WeChat, Feishu oder DingTalk, die AgenticOS nicht abdeckt.
- Sie nutzen es unverändert, oder die kommerzielle Lizenz passt für Sie.

## Eine Änderung vergleichen, nicht nur eine Antwort { #compare-a-change-not-only-an-answer }

Fügen Sie in beiden Produkten einen Agent demselben Slack-Kanal hinzu. Lassen Sie ihn ein Werkzeug ausführen, das eine Freigabe braucht, und entscheiden Sie die Freigabe als jemand anderes als die fragende Person. Geben Sie dem Agent ein Budget von wenigen Cent und überschreiten Sie es. Halten Sie fest, was jedes Produkt erlaubt, ablehnt und protokolliert, nach der [Vergleichsmethode](comparison.md#a-shared-trial).

## Häufig gestellte Fragen { #frequently-asked-questions }

### Ist LobeHub Open Source? { #is-lobehub-open-source }

Sein Code ist öffentlich unter der LobeHub Community License, die Apache 2.0 Bedingungen hinzufügt: Kommerzielle Nutzung ist ohne Codeänderung erlaubt, die Verbreitung eines abgeleiteten Werks braucht eine kommerzielle Lizenz. AgenticOS steht unter reinem Apache-2.0.

### Können AgenticOS-Agents Team-Chats beitreten wie LobeHub-Agents? { #can-agenticos-agents-join-team-chats-like-lobehub-agents }

Ja. Ein veröffentlichter Agent antwortet in Slack, Microsoft Teams, Telegram, Mattermost, Discord und Matrix und kann einem Kanal auch passiv folgen. Anfragen eines verknüpften Nutzers laufen als diese Person.

### Welches kontrolliert Kosten besser? { #which-one-controls-cost-better }

LobeHub verfolgt die Nutzung gegen einen Kreditpool. AgenticOS stoppt die nächste Modellanfrage eines Agents, wenn sein Budget oder die Obergrenze der Organisation erreicht ist, und erfasst auch die Kosten eines fehlgeschlagenen Runs.

## Verwandte Vergleiche { #related-comparisons }

[AgenticOS vs Kortix](kortix.md) · [AgenticOS vs Open WebUI und LibreChat](open-webui-librechat.md) · [Agents in Slack](slack-agents.md) · [Alle Vergleiche](comparison.md)

## Quellen { #sources }

- [LobeHub](https://lobehub.com): Produktbeschreibung, Kanäle und Preise.
- [Lizenz von `lobehub/lobehub`](https://github.com/lobehub/lobehub/blob/main/LICENSE): die zitierten Bedingungen der LobeHub Community License.
- [LobeHub-Repository](https://github.com/lobehub/lobehub): Provider, MCP-Unterstützung und der selbst gehostete Build.
