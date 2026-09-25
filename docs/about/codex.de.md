---
source_sha: "74107fac73b3"
title: "AgenticOS vs OpenAI Codex"
seo_title: "AgenticOS vs OpenAI Codex: Firmen-Agents oder Coding-Agent"
description: "OpenAI Codex ist ein Coding-Agent für Entwickler, AgenticOS eine selbst gehostete Open-Source-Plattform für kontrollierte Firmen-Agents. Beide im Vergleich."
---

# AgenticOS vs OpenAI Codex { #agenticos-vs-openai-codex }

OpenAI Codex ist ein Agent für Softwareentwicklung. Er umfasst eine Open-Source-CLI, eine IDE-Erweiterung, die ChatGPT-Desktop-App, Cloud-Aufgaben und Reviews von GitHub-Pull-Requests. Er ist für Entwickler gedacht, die Code ändern. AgenticOS ist für die Agents gedacht, die eine ganze Organisation nutzt: von Fachabteilungen im Browser konfiguriert, auf dem Server kontrolliert und auf Chat-, Web- und API-Oberflächen veröffentlicht.

Beide haben einiges gemeinsam: eine Apache-2.0-Lizenz für die offenen Teile, MCP, Ausführung in einer Sandbox und eine Freigabe vor riskanten Aktionen. Sie wenden das auf unterschiedliche Benutzer an.

Verantwortlich: das AgenticOS-Team. Quellen geprüft am 25. September 2026. AgenticOS-Stand: v0.0.504. Codex-Umfang: die Codex-Dokumentation von OpenAI auf learn.chatgpt.com, die Preisseite und das Repository `openai/codex`, kein getesteter Enterprise-Rollout.

## Auf einen Blick { #at-a-glance }

| Bereich | OpenAI Codex | AgenticOS |
| --- | --- | --- |
| Für wen | Softwareentwickler | Fachabteilungen, die Agents konfigurieren, und die Entwickler, die sie erweitern |
| Woran es arbeitet | Ein Code-Repository und eine Shell | Unternehmensdokumente, Werkzeuge und Systeme |
| Wo es läuft | Entwicklerrechner; Cloud-Aufgaben in von OpenAI verwalteten Containern | Ihre Infrastruktur, als gemeinsamer Dienst |
| Quellcode | CLI Apache-2.0; Cloud, Review und ChatGPT-App proprietär | Apache-2.0 |
| Modelle | OpenAI mit ChatGPT-Anmeldung; die CLI akzeptiert auch Ollama, LM Studio, Bedrock und eigene Provider | 27 Provider, festgelegt pro Modellprofil |
| Endbenutzer | Der Entwickler | Mitarbeiter, Kunden und Systeme, auf acht Oberflächen |
| Freigaben | Sandbox-Modi und Freigaberichtlinien am Arbeitsplatz des Entwicklers | Eine Person mit `approvals:decide`, aus einer gemeinsamen Warteschlange |
| Ausgabenkontrolle | Tariflimits pro Fünf-Stunden-Fenster und Credits, die mit ChatGPT Work geteilt werden | Ein monatliches Budget pro Agent und pro Organisation |
| Preise | In ChatGPT-Tarifen enthalten; OpenAI schätzt 100–200 $ pro Entwickler und Monat bei Credits | Keine Lizenzgebühr; Modellnutzung und Infrastruktur |

## Wo AgenticOS weiter geht { #where-agenticos-goes-further }

### Agents für Menschen außerhalb der Entwicklung { #agents-for-people-outside-engineering }

Die Cloud-Funktionen von Codex erfordern einen ChatGPT-Tarif, und seine Benutzer sind Entwickler. Für Unternehmens-Agents verweist OpenAI stattdessen auf die Workspace-Agents von ChatGPT; siehe [AgenticOS vs ChatGPT](chatgpt.md). AgenticOS gibt einer Fachabteilung den ganzen Weg: Instruktionen, [Capabilities](../reference/capabilities.md), Wissen, ein Budget, eine [veröffentlichte Version](../concepts.md#version) und [acht Oberflächen](../channels.md).

### Regeln, die für alle zugleich gelten { #rules-that-hold-for-everyone-at-once }

Codex setzt Sandbox- und Freigaberichtlinien auf dem Rechner jedes einzelnen Entwicklers durch, mit einer verwalteten `requirements.toml` für ganze Geräteflotten. AgenticOS setzt sie einmal durch, auf dem Server. [Berechtigungen](../permissions.md), [Budgets](../governance.md#enforcement-is-before-the-request), [Freigaben](../governance.md#approvals) und das [Audit-Log](../governance.md#audit) gelten für jeden Run, gleich welche Oberfläche ihn gestartet hat.

### Jedes Modell mit jeder Funktion { #any-model-with-every-feature }

Die Codex-CLI kann andere Provider nutzen, aber ihre Cloud-Aufgaben, das Code-Review und Slack erfordern eine ChatGPT-Anmeldung und Modelle von OpenAI. In AgenticOS erreicht jeder Provider dieselbe Plattform: [27 Provider](../models.md#providers), [Fallbacks](../models.md#fallbacks) und erfasste Kosten für jeden Run jedes Agents.

### Codeausführung als kontrollierte Capability { #code-execution-as-a-governed-capability }

Codex führt Befehle in einer Betriebssystem-Sandbox auf dem Rechner des Entwicklers oder in einem Cloud-Container aus. AgenticOS gibt Agents [Run Python](../reference/capabilities.md#run-python), einen Monty-Interpreter ohne Netzwerk oder Dateisystem, und einen Workspace [Files & shell](../reference/capabilities.md#files-shell) in [Geschwister-Containern](../sandbox.md#isolation-plainly). Beide werden pro Agent eingeschaltet, mit Limits und einer Freigabeeinstellung.

## Wann Codex das richtige Werkzeug ist { #when-codex-is-the-right-tool }

- Die Arbeit ist Software: parallele Cloud-Aufgaben, Reviews von Pull-Requests und CLI-Arbeit in einem Repository.
- Sie möchten eine Open-Source-Coding-CLI mit vom Betriebssystem durchgesetzter Sandbox und standardmäßig abgeschaltetem Netzwerk.
- Ihre Entwickler haben bereits ChatGPT-Plätze.

## Beides zusammen nutzen { #use-them-together }

Ein Entwickler kann mit Codex eine neue [Capability](../howto/add-capability.md) schreiben, testen und reviewen: typisiertes Python mit Tests, in einem Repository, dessen Regeln für Beitragende schriftlich festgehalten sind. Nach dem Merge steht sie jedem Agent-Ersteller in der Organisation zur Verfügung. Der Spec eines Agents [lässt sich als YAML exportieren](../features.md#exportable-into-your-own-repository), sodass Codex auch die Änderung an einem Agent in einem Pull-Request reviewen kann.

## Auf einer Aufgabe ausprobieren { #try-it-on-one-task }

Stellen Sie beiden die Frage aus dem [gemeinsamen Handbuch](../howto/first-document-agent.md). Geben Sie die Antwort dann an einen Kollegen, der nicht programmiert, und prüfen Sie, was jeder braucht, bevor er seine eigene Frage stellen kann. Erfassen Sie das Ergebnis mit der [Vergleichsmethode](comparison.md#a-shared-trial).

## Häufig gestellte Fragen { #frequently-asked-questions }

### Ist AgenticOS eine Alternative zu OpenAI Codex? { #is-agenticos-an-alternative-to-openai-codex }

Nein, die beiden lösen unterschiedliche Probleme. Codex ist ein Coding-Agent für Entwickler. AgenticOS ist eine Plattform für kontrollierte Agents, die Fachabteilungen bauen und alle nutzen.

### Ist OpenAI Codex Open Source? { #is-openai-codex-open-source }

Die Codex-CLI steht unter Apache-2.0. Codex Cloud, das Code-Review und die ChatGPT-App sind proprietäre Dienste. AgenticOS steht als Ganzes unter Apache-2.0.

### Kann Codex helfen, AgenticOS zu erweitern? { #can-codex-help-extend-agenticos }

Ja. Ein Entwickler kann mit Codex eine neue Capability in typisiertem Python schreiben und reviewen. Nach dem Merge ist sie ein Schalter in jedem Agent-Builder.

### Können AgenticOS-Agents Code ausführen? { #can-agenticos-agents-run-code }

Ja. Run Python führt Code ohne Netzwerk oder Dateisystem aus, und Files & shell gibt einem Agent einen Workspace in isolierten Containern. Beide werden pro Agent eingeschaltet.

## Verwandte Vergleiche { #related-comparisons }

[AgenticOS vs Claude Code](claude-code.md) · [AgenticOS vs OpenCode](opencode.md) · [AgenticOS vs ChatGPT](chatgpt.md) · [Alle Vergleiche](comparison.md)

## Quellen { #sources }

- [Codex-Repository](https://github.com/openai/codex): die Apache-2.0-CLI.
- [Codex-Preise](https://learn.chatgpt.com/docs/pricing): Tarife, Nutzungsfenster, Credits und Funktionen nach Tarif.
- [Freigaben und Sicherheit](https://learn.chatgpt.com/docs/agent-approvals-security): Sandbox-Modi und Freigaberichtlinien.
- [Erweiterte Konfiguration](https://learn.chatgpt.com/docs/config-file/config-advanced): eigene und lokale Modell-Provider.
- [Verwaltete Enterprise-Konfiguration](https://learn.chatgpt.com/codex/enterprise/managed-configuration): `requirements.toml`.
- [ChatGPT-Preisliste](https://help.openai.com/en/articles/11481834-chatgpt-rate-card-business-enterpriseedu-credit-based-pricing): die Schätzung pro Entwickler.
