---
title: "AgenticOS vs OpenAgents"
seo_title: "AgenticOS vs OpenAgents: steuern oder zusammenarbeiten"
description: "OpenAgents und AgenticOS, beide Apache-2.0, im Vergleich: ein Workspace für Menschen und externe Agents gegen eine Plattform, die Agents baut und steuert."
source_sha: "27048ef8f806"
---

# AgenticOS vs OpenAgents { #agenticos-vs-openagents }

OpenAgents bezeichnet sich als „das Kollaborations-Betriebssystem für Menschen und KI-Agents“. Seine Workspaces funktionieren wie ein Team-Chat, in dem Menschen und Agents Threads, einen Browser, Issues und Routinen teilen, und sein Launcher bindet rund 27 Agent-Runtimes wie Claude Code, Codex, Gemini CLI und Cursor an. Beide Produkte stehen unter Apache-2.0, sind selbst gehostet und haben Desktop- und Telefon-Apps. Der Unterschied: OpenAgents koordiniert anderswo gebaute Agents, AgenticOS baut, betreibt und steuert die eigenen Agents des Unternehmens.

Verantwortlich: das AgenticOS-Team. Quellen geprüft am 26. November 2026. AgenticOS-Basis: v1.95.0. Umfang bei OpenAgents: openagents.org und das Repository `openagents-org/openagents`, kein getesteter Workspace. OpenAgents Inc. unter openagents.com ist ein anderes Unternehmen.

## Auf einen Blick { #at-a-glance }

| Bereich | OpenAgents | AgenticOS |
| --- | --- | --- |
| Was es ist | Ein gemeinsamer Workspace für Menschen und Agents aus vielen Runtimes | Eine Plattform, in der ein Fachteam Unternehmens-Agents baut, veröffentlicht und steuert |
| Lizenz | Apache-2.0; Launcher MIT | Apache-2.0; siehe [Lizenzen der enthaltenen Komponenten](../licenses.md) |
| Wo es läuft | Kostenlos gehostet oder selbst gehostet | Ihre Infrastruktur |
| Agents | Bindet rund 27 Coding- und allgemeine Agent-CLIs mit eigenen Schlüsseln an | Baut Agents auf 28 Providern; führt Claude Code und Codex lokal in der [Desktop-App](../desktop.md#coding-agents-on-this-computer) und über den [Coding-Agent](../reference/capabilities.md#coding-agent) aus |
| Zusammenarbeit | Threads mit @agent-Erwähnungen, gemeinsamer Browser, Issues, Routinen | [Projekte](../projects.md) mit gemeinsamen Dateien, Instruktionen und Chats; Routinen und Aufgaben |
| Freigaben | Festlegen, wer die Aktion eines Agents freigibt | Freigabe pro Capability, Werkzeug und MCP-Verbindung, mit einer [Freigabewarteschlange](../governance.md#approvals) |
| Ausgabenkontrolle | Nicht beschrieben | Ein monatliches Budget pro Agent und pro Organisation, geprüft vor jeder Modellanfrage |
| Anmeldung und Audit | Rollen bei Selbsthosting; SSO und Audit nicht beschrieben | OIDC-SSO, LDAP, Kerberos, sechs Rollen und ein Audit-Log mit Manipulationsnachweis |
| Wissen | Nicht beschrieben | [Wissensdatenbanken](../file-processing.md) mit Parsing und synchronisierenden Konnektoren |
| Kanäle | Eigene Web-, Desktop- und Telefon-Apps | Web-Chat, Widget, gehostete Seite, HTTP-API, WebSocket, Slack, Microsoft Teams, Telegram, Mattermost, Discord, Matrix, SMS, E-Mail, iMessage, Telefonanrufe; Desktop- und Telefon-Apps |

## Wo AgenticOS weiter geht { #where-agenticos-goes-further }

### Getrennte Agents, jeder mit Besitzer { #separate-agents-each-with-an-owner }

OpenAgents holt bestehende Agents in einen gemeinsamen Raum. AgenticOS ist der Ort, aus dem diese Agents kommen: Jeder hat Instruktionen, ein Modellprofil, Capabilities, ein [Budget](../governance.md#budgets) und einen Besitzer und wird in [Versionen](../concepts.md#version) veröffentlicht. Statt eines Assistenten, der alles können soll, baut ein Unternehmen mehrere schmale Agents und sieht, welcher was getan hat.

### Governance, die eine Unternehmensprüfung verlangt { #governance-a-company-review-asks-for }

AgenticOS prüft Ausgaben [vor jeder Modellanfrage](../governance.md#enforcement-is-before-the-request), schreibt jede Aktion in ein [Audit-Log mit Manipulationsnachweis](../governance.md#audit), meldet Menschen über [das Firmenverzeichnis](../directory.md#signing-in-with-a-directory-account) an und bedient [viele Organisationen](../concepts.md#organizations) aus einer Bereitstellung. OpenAgents beschreibt weder Budgets noch Audit oder SSO.

### Wissen, Modelle und Kanäle an einem Ort { #knowledge-models-and-channels-in-one-place }

AgenticOS-Agents antworten aus Wissensdatenbanken und erreichen Menschen in Slack, Microsoft Teams, per E-Mail, SMS, Telefon und über ein Website-Widget. OpenAgents-Agents bringen ihre eigenen Schlüssel mit und leben in den OpenAgents-Apps.

## Wann OpenAgents besser passt { #when-openagents-is-the-better-fit }

- Ihre Leute nutzen bereits viele Coding-Agents und wollen einen gemeinsamen Raum mit gemeinsamem Browser dafür.
- Sie wollen Agents koordinieren, nicht bauen und steuern.
- Sie brauchen Runtimes über die hinaus, die AgenticOS lokal unterstützt.

## Besser zusammen { #better-together }

AgenticOS ist ein [MCP-Server](../mcp.md#agenticos-as-an-mcp-server) und spricht [A2A](../channels.md#a2a), sodass ein gesteuerter AgenticOS-Agent aus Werkzeugen in einem anderen Workspace erreichbar ist, während sein Budget, seine Freigaben und sein Audit in AgenticOS bleiben. Prüfen Sie, was Ihr OpenAgents-Setup aufrufen kann, bevor Sie sich darauf verlassen.

## Häufig gestellte Fragen { #frequently-asked-questions }

### Ist OpenAgents eine Alternative zu AgenticOS? { #is-openagents-an-alternative-to-agenticos }

Teilweise. Beide stehen unter Apache-2.0, sind selbst gehostet und haben Desktop- und Telefon-Apps. OpenAgents ist eine Kollaborationsschicht für anderswo gebaute Agents; AgenticOS baut und steuert die Agents, mit Budgets, Freigaben, Audit und Verzeichnisanmeldung.

### Kann AgenticOS Claude Code oder Codex ausführen? { #can-agenticos-run-claude-code-or-codex }

Ja. Die Desktop-App führt Claude Code, Codex und mehrere weitere Runtimes auf Ihrem Rechner in einem freigegebenen Ordner aus, und die Capability Coding-Agent übergibt Softwarearbeit an Claude Code oder Codex in einer Sandbox.

## Verwandte Vergleiche { #related-comparisons }

[AgenticOS vs OpenHuman](openhuman.md) · [AgenticOS vs Claude Code](claude-code.md) · [AgenticOS vs Codex](codex.md) · [Alle Vergleiche](comparison.md)

## Quellen { #sources }

- [OpenAgents](https://openagents.org): Workspaces, Threads, gemeinsamer Browser, Routinen, Freigaben und Apps.
- [`openagents-org/openagents`](https://github.com/openagents-org/openagents): Lizenz, Launcher und unterstützte Runtimes.
