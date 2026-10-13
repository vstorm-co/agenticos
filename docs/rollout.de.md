---
source_sha: "6ff659040810"
title: "AgenticOS bereitstellen und betreiben"
description: "Verantwortung zuweisen, Betriebskosten verstehen und Implementierungshilfe vereinbaren."
---

# AgenticOS bereitstellen und betreiben { #deploy-and-operate-agenticos }

AgenticOS ist eine Anwendung, die Ihre Organisation betreibt. Beginnen Sie mit [einer prüfbaren Aufgabe](howto/first-document-agent.md) und bestimmen Sie die Verantwortung für Deployment und Agent-Aufgabe.

## Wer was betreut { #who-maintains-what }

| Bereich | Verantwortung |
| --- | --- |
| Hosting und Updates | Dienste bereitstellen, Kapazität überwachen, Releases prüfen und Updates planen |
| Backup und Wiederherstellung | Datenbanken und benötigte Workspace-Daten sichern, Schlüssel schützen, Wiederherstellung testen |
| Quellen und Verhalten | Dokumente, Instruktionen, Skills und veröffentlichte Versionen aktuell halten |
| Zugriff und Geheimnisse | Identitäten, Berechtigungen, Anbieterzugänge und Rotation verwalten |
| Fehler und Freigaben | Runs prüfen, Vorfälle zuordnen und berechtigte Entscheider benennen |
| Externe Dienste | Modelle, Parser, Embeddings, Werkzeuge, Sandbox, Kanäle und Tracing prüfen |

Details: [Installation](install.md), [Deployment](deployment.md), [Geheimnisse](secrets.md), [Berechtigungen](permissions.md) und [Sicherheit](security.md). Bewahren Sie Wiederherstellungsnachweise und Betriebskontakte beim Deployment auf. Ein veröffentlichter Agent ersetzt diese Arbeit nicht.

## Kosten und Liefermodelle { #costs-and-delivery-options }

Berücksichtigen Sie Modelle, Infrastruktur, externe Dienste, Implementierung und Betriebszeit. Aufgezeichnete Run-Kosten sind nur ein Teil. Prüfen Sie [Projekt- und Komponentenlizenzen](licenses.md).

Sie können AgenticOS selbst betreiben. Vstorm kann separat bei Kundeninfrastruktur, Dokumentation, Prozessgestaltung und individueller Entwicklung helfen. Laufende Wartung erfordert einen vereinbarten Umfang. Installation beinhaltet keinen Standardpreis, Support oder SLA.

Kontaktieren Sie [Vstorm](https://vstorm.co/) oder Kacper mit Aufgabe, Quellentypen, Infrastrukturvorgaben und Betriebsverantwortung. Private Dokumente sind für das erste Gespräch nicht nötig.

<span id="what-your-security-review-will-ask"></span>

## Grenzen prüfen { #boundaries-to-verify }

Self-Hosting bedeutet keinen Offline-Betrieb. Ein lokales Chatmodell verändert einen Datenpfad; Parsing, Embeddings, Werkzeuge, gehostete Sandboxes, Kanäle und Tracing können externe Dienste nutzen. Prüfen Sie den [Datenfluss](security.md).

Freigaben hängen von Capability und Konfiguration ab. Budgets prüfen erfasste Kosten vor Modellaufrufen und garantieren keine überschreitungsfreie Begrenzung. Sammlungsberechtigungen beweisen keine Übernahme aller Quell-ACLs. Testen Sie Identitäten und Aufgabe anhand von [Governance](governance.md) und [Sammlungszugriff](file-processing.md).

## Den Pilot bewerten { #evaluate-the-pilot }

Erfassen Sie bisherigen Ablauf, Abnahmefragen, Quellversion, Modell, Werkzeuge und tatsächliche Ergebnisse. Berücksichtigen Sie Lücken, Fehler, Prüfaufwand und Nutzung. Ändern Sie einen Quellenfakt und wiederholen Sie vor einer Erweiterung.

Nutzen Sie [Vergleiche](about/comparison.md) zur Auswahl und [Hilfe](help.md) bei reproduzierbaren Problemen. Ein Pilot kann Erweiterung, Reparatur oder Abbruch begründen; er verspricht kein Geschäftsergebnis.
