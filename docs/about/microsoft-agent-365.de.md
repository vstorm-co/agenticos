---
title: "AgenticOS vs Microsoft Agent 365"
seo_title: "AgenticOS vs Microsoft Agent 365: Agents selbst steuern"
description: "Agent 365 ist die Steuerungsebene von Microsoft für Agents in Microsoft 365. Vergleichen Sie AgenticOS: Agents auf Ihren Servern bauen, betreiben und steuern."
source_sha: "b13848977282"
---

# AgenticOS vs Microsoft Agent 365 { #agenticos-vs-microsoft-agent-365 }

Microsoft Agent 365 ist eine Steuerungsebene für die Agents eines Unternehmens - die von Microsoft, die in Copilot Studio gebauten und einige anderer Anbieter - mit Richtlinien, Sicherheit und Lebenszyklusverwaltung in Entra und Purview. AgenticOS ist der Ort, an dem Agents gebaut und gesteuert werden: eine selbst gehostete Schicht mit Builder, Laufzeit, Berechtigungen, Budgets und Audit-Log an einem Ort.

Wenn Ihr Unternehmen auf Microsoft 365 läuft und die vorhandenen Agents erfassen und überwachen möchte, passt Agent 365 in diese Umgebung. Wenn Sie die Agents selbst und die Regeln darüber auf einer Infrastruktur unter Ihrer Kontrolle und mit jedem Modell möchten, erledigt AgenticOS beides an einem Ort.

Gepflegt vom AgenticOS-Team. Quellen geprüft am 14. Oktober 2026. AgenticOS-Basisversion: v0.0.535. Umfang Agent 365: die allgemeine Verfügbarkeit von Microsoft um den 1. Mai 2026 laut Presseberichten, kein getesteter Tenant. Zum Bauen von Agents im Microsoft-Stack siehe [AgenticOS vs Copilot Studio](copilot-studio.md).

## Auf einen Blick { #at-a-glance }

| Bereich | Microsoft Agent 365 | AgenticOS |
| --- | --- | --- |
| Was Sie bekommen | Eine Steuerungsebene über anderswo gebaute Agents | Builder, Laufzeit und Steuerung in einer Schicht |
| Wo es läuft | Die Cloud von Microsoft | Ihre Infrastruktur, mit Docker Compose |
| Quellcode | Proprietär | Apache-2.0 |
| Identität | Microsoft Entra ID | OIDC-Single-Sign-on, LDAP und Kerberos, einschließlich Entra ID |
| Richtlinien und Audit | Purview, Schutz vor Datenverlust, Lebenszyklus | Rollen und Grants pro Ressource, Freigaben, Budgets vor jeder Modellanfrage, ein manipulationssicheres Audit-Log |
| Modelle | Über die Agents, die es steuert | 28 Provider, darunter lokale Modelle |
| Preise | Microsoft-365-Lizenzen | Keine Lizenzgebühr; Sie bezahlen Modell-Provider und Infrastruktur |

## Wo AgenticOS weiter geht { #where-agenticos-goes-further }

### Steuerung dort, wo der Agent läuft { #governance-where-the-agent-runs }

Eine Steuerungsebene beobachtet Agents, die anderswo laufen. AgenticOS [prüft das Budget](../governance.md#enforcement-is-before-the-request) und [die Freigabe](../governance.md#approvals) im selben Prozess, der das Modell und das Werkzeug aufruft, sodass eine Regel in dem Moment durchgesetzt wird, in dem sie zählt, statt hinterher gemeldet zu werden.

### Außerhalb der Cloud eines Anbieters { #outside-one-vendors-cloud }

Agent 365 lebt in der Cloud und den Lizenzen von Microsoft. AgenticOS läuft [dort, wo Sie es betreiben](../deploy.md), meldet über Ihr [Verzeichnis](../directory.md#signing-in-with-a-directory-account) an - Entra ID eingeschlossen - und arbeitet mit [jedem der 28 Modell-Provider](../models.md#providers).

### Offen zum Lesen und Erweitern { #open-to-read-and-extend }

AgenticOS steht unter Apache-2.0. Ein Prüfer kann nachlesen, wie eine Regel durchgesetzt wird, und ein Entwickler kann [eine Capability hinzufügen](../howto/add-capability.md), in typisiertem Python.

## Wann Agent 365 genügt { #when-agent-365-is-enough }

- Ihr Unternehmen standardisiert auf Microsoft 365, und Ihre Agents entstehen in Copilot Studio oder in Microsoft-Produkten.
- Sie brauchen ein Verzeichnis aller Agents über Microsoft-Werkzeuge hinweg mit den Richtlinien von Purview.
- Microsoft Teams ist heute Ihr Hauptkanal; AgenticOS hat noch keinen Teams-Kanal.

## Häufig gestellte Fragen { #frequently-asked-questions }

### Ist AgenticOS eine Alternative zu Microsoft Agent 365? { #is-agenticos-an-alternative-to-microsoft-agent-365 }

Für ein Unternehmen, das seine Agents an einem Ort unter eigener Kontrolle bauen, betreiben und steuern möchte, ja. Agent 365 steuert Agents in der Microsoft-Umgebung; AgenticOS ist die Schicht, die sie baut und betreibt, mit den Regeln am selben Ort.

### Kann sich AgenticOS mit Microsoft Entra ID anmelden? { #can-agenticos-sign-in-with-microsoft-entra-id }

Ja. AgenticOS meldet über OIDC an, und Entra ID ist ein OIDC-Provider; Verzeichnisgruppen werden Rollen zugeordnet.

## Verwandte Vergleiche { #related-comparisons }

[AgenticOS vs Copilot Studio](copilot-studio.md) · [AgenticOS vs OpenAI Frontier](openai-frontier.md) · [AgenticOS vs Gemini Enterprise](gemini-enterprise.md) · [Alle Vergleiche](comparison.md)

## Quellen { #sources }

- [Help Net Security: Copilot Studio security and governance updates](https://www.helpnetsecurity.com/2026/05/14/copilot-studio-security-governance-updates/): Agent 365 als Steuerungsebene, Richtlinien, Sicherheit und Lebenszyklus.
