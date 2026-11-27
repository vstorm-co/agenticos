---
title: "AgenticOS vs OpenHuman"
seo_title: "AgenticOS vs OpenHuman: persönlicher Harness oder Plattform"
description: "OpenHuman und AgenticOS im Vergleich: ein schneller persönlicher GPL-3.0-Harness gegen eine Apache-2.0-Plattform mit Budgets, Rollen und Audit."
source_sha: "bc81d3a12c59"
---

# AgenticOS vs OpenHuman { #agenticos-vs-openhuman }

OpenHuman von Tiny Humans präsentiert sich als der schnellste und günstigste Open-Source-Harness für Agents: eine Desktop-App und Bibliothek in Rust und Tauri mit Gedächtnis, Sprache, Browser- und Desktopsteuerung, dauerhaften Workflow-Graphen mit Freigaben, 14 Kanälen und 26 Providern plus lokalen Modellen. Es veröffentlicht Benchmark-Zahlen als Beleg. AgenticOS ist für eine Organisation statt für eine Person gebaut: viele Agents mit Besitzern, Rollen, Budgets und einem Audit-Log.

Verantwortlich: das AgenticOS-Team. Quellen geprüft am 26. November 2026. AgenticOS-Basis: v1.95.0. Umfang bei OpenHuman: das Repository `tinyhumansai/openhuman`, sein README und das veröffentlichte Benchmark-Repository, keine getestete Installation. OpenHuman bezeichnet sich als frühe Beta.

## Auf einen Blick { #at-a-glance }

| Bereich | OpenHuman | AgenticOS |
| --- | --- | --- |
| Was es ist | Ein persönlicher und Entwickler-Harness, Desktop-App und Rust-Bibliothek | Eine Plattform, in der ein Fachteam Unternehmens-Agents baut, veröffentlicht und steuert |
| Lizenz | GPL-3.0 | Apache-2.0; siehe [Lizenzen der enthaltenen Komponenten](../licenses.md) |
| Wo es läuft | Desktop, Terminal oder Headless-Server | Ihre Infrastruktur; [Desktop-](../desktop.md) und [Telefon-App](../mobile.md) verbinden sich damit |
| Modelle | 26 Provider mit eigenen Schlüsseln plus Ollama, LM Studio und MLX, mit Routing | 28 Provider, auch lokale, mit [Fallbacks](../models.md#fallbacks) |
| Ausgabenkontrolle | Kosten jedes Aufrufs werden erfasst | Ein monatliches Budget pro Agent und pro Organisation, durchgesetzt vor jeder Modellanfrage |
| Freigaben | Vom Nutzer bestätigt, in Workflow-Graphen | Freigabe pro Capability, Werkzeug und MCP-Verbindung, entschieden von den Personen Ihrer Wahl |
| Organisation | Eine Person; Mandanten, Rollen oder SSO nicht beschrieben | Viele Organisationen, sechs Rollen, Berechtigungen pro Ressource, OIDC-SSO, LDAP und Kerberos |
| Audit | Wiederabspielbare Run-Protokolle | Audit-Log mit Manipulationsnachweis, Export als CSV und JSONL |
| Agents bauen | Konfiguration und Code | Ein [Builder](../features.md) im Browser für Fachteams, Versionen und Umgebungen |
| Workflows | Dauerhafte Graphen mit Freigaben | Eine visuelle [Workflow](../workflows.md)-Arbeitsfläche mit typisierten Schritten, Verzweigungen, Schleifen und Freigaben |

## Wo AgenticOS weiter geht { #where-agenticos-goes-further }

### Für eine Organisation gebaut, nicht für eine Person { #built-for-an-organization-not-one-person }

OpenHuman läuft als Harness einer Person. AgenticOS meldet Menschen über [das Firmenverzeichnis](../directory.md#signing-in-with-a-directory-account) an, gibt ihnen [Rollen und Berechtigungen pro Ressource](../permissions.md#layer-3-visibility-and-grants) und isoliert [Organisationen](../concepts.md#organizations) in einer Bereitstellung. Ein Agent gehört dem Unternehmen, nicht dem, der ihn installiert hat.

### Viele schmale Agents statt einem für alles { #many-narrow-agents-instead-of-one-that-does-everything }

In AgenticOS hat jeder Agent einen Zweck, eigene Instruktionen, Capabilities und ein [Budget](../governance.md#budgets) sowie eine veröffentlichte [Version](../concepts.md#version). Sie sehen, welcher Agent lief, was er kostete und was er änderte, und können einen ersetzen, ohne die anderen anzufassen.

### Ein Budget, das stoppt, nicht nur zählt { #a-budget-that-stops-not-only-a-counter }

OpenHuman meldet die Kosten jedes Aufrufs. AgenticOS lehnt die nächste Modellanfrage ab, wenn das Budget eines Agents oder die Obergrenze der Organisation erreicht ist, und [delegierte Arbeit](../governance.md#delegation-spends-the-parents-budget) geht vom Budget des übergeordneten Agents ab.

### Eine Lizenz, auf der man ein Produkt bauen kann { #a-licence-you-can-build-a-product-on }

GPL-3.0 verlangt, dass verbreitete abgeleitete Werke unter derselben Lizenz veröffentlicht werden. Apache-2.0 hat keine solche Bedingung, AgenticOS lässt sich also in ein geschlossenes Produkt einbetten oder als Dienst anbieten.

## Wann OpenHuman besser passt { #when-openhuman-is-the-better-fit }

- Eine Person oder ein Entwickler will den schnellsten lokalen Harness, mit Desktopsteuerung und vielen Integrationen über Composio.
- Reine Effizienz auf einem kleinen Server zählt mehr als Rollen, Budgets und Audit.
- GPL-3.0 passt dazu, wie Sie Ihre Änderungen verbreiten.

## Eine Änderung vergleichen, nicht nur eine Antwort { #compare-a-change-not-only-an-answer }

Benchmarks messen einen Harness an Programmieraufgaben. Für den Einsatz im Unternehmen messen Sie etwas anderes: Fügen Sie eine zweite Person mit einer anderen Rolle hinzu, geben Sie einem Agent ein Budget von wenigen Cent und überschreiten Sie es, und verlangen Sie für einen Werkzeugaufruf die Freigabe durch jemand anderen. Halten Sie fest, was jedes Produkt erlaubt, ablehnt und protokolliert, nach der [Vergleichsmethode](comparison.md#a-shared-trial).

## Häufig gestellte Fragen { #frequently-asked-questions }

### Ist OpenHuman eine Alternative zu AgenticOS? { #is-openhuman-an-alternative-to-agenticos }

Für die Agents einer einzelnen Person kann es das sein. Für ein Unternehmen ergänzt AgenticOS, was OpenHuman nicht beschreibt: Mandanten, Rollen, Verzeichnisanmeldung, ein vor jeder Modellanfrage durchgesetztes Budget, Freigaben durch andere und ein organisationsweites Audit-Log.

### Kann AgenticOS auch lokale Modelle ausführen? { #can-agenticos-run-local-models-too }

Ja. AgenticOS arbeitet mit lokalen Chat-Modellen, lokalen Embeddings und lokalem Parsing, und die Desktop-App kann lokale Modelle und MCP-Server auf Ihrem Rechner nutzen.

## Verwandte Vergleiche { #related-comparisons }

[AgenticOS vs OpenAgents](openagents.md) · [AgenticOS vs OpenClaw](openclaw.md) · [Alle Vergleiche](comparison.md)

## Quellen { #sources }

- [`tinyhumansai/openhuman`](https://github.com/tinyhumansai/openhuman): Funktionen, Kanäle, Provider, Lizenz und Release-Status.
- [OpenHuman-Benchmarks](https://github.com/tinyhumansai/openhuman-benchmarks): der veröffentlichte Harness-Vergleich.
