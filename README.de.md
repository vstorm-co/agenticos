<!-- source_sha: 0340b9ad0e04 -->

<div align="center">

<img src="docs/assets/amigo-walk.svg" alt="Amigo, das AgenticOS-Maskottchen" width="144">

<h1>AgenticOS</h1>

<p>
  <b>Erstelle KI-Agenten, die mit den Dokumenten und Werkzeugen deines Teams arbeiten.</b><br>
  Konfiguriere sie im Browser, nutze ihre Ergebnisse und behalte Aktionen und Kosten im Blick.
</p>

<p>
  <a href="#so-funktioniert-es">Demo ansehen</a> &middot;
  <a href="#schnellstart">Schnellstart</a> &middot;
  <a href="#die-plattform-entdecken">Plattform entdecken</a> &middot;
  <a href="docs/index.de.md">Dokumentation</a>
</p>

<p>
  <a href="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml"><img src="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://github.com/vstorm-co/agenticos/releases"><img src="https://img.shields.io/github/v/release/vstorm-co/agenticos?label=release&color=blue" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-Apache--2.0-blue" alt="Apache-2.0"></a>
  <a href="https://ai.pydantic.dev"><img src="https://img.shields.io/badge/Powered%20by-Pydantic%20AI-E92063?logo=pydantic&logoColor=white" alt="Pydantic AI"></a>
</p>

<p>
  <a href="README.md">English</a> &middot;
  <a href="README.pl.md">Polski</a> &middot;
  <b>Deutsch</b> &middot;
  <a href="README.es.md">Español</a>
</p>

</div>

AgenticOS ist ein selbst gehosteter Open-Source-Arbeitsbereich zum Erstellen und Nutzen von KI-Agenten.
Ein Agent ist ein KI-Assistent, dem du eine Aufgabe, Anweisungen und Zugriff auf ausgewählte Dokumente und Werkzeuge gibst.
Er kann recherchieren, eine Datei analysieren, einen Bericht erstellen oder eine Aktion in einer angebundenen Anwendung ausführen.
Du legst die Fähigkeiten und Zugriffsrechte jedes Agenten fest.

Teams konfigurieren Agenten und wiederverwendbare Abläufe über die Oberfläche. Entwickler erweitern
die Plattform und integrieren sie in ihre Anwendungen. Betreiber verwalten Zugriff, Bereitstellung und Nutzung an einem Ort.

## So funktioniert es

**Von einem Briefing in Notion und GitHub-Recherche zu einer interaktiven Entscheidungsseite.**
In der Demo erstellt der Agent **Claude Code like** einen Vergleich von Open-Source-Projekten.
Anschließend werden auf der fertigen Seite Zielgruppen gewechselt und ein Freigabelink erstellt.
Der Bericht ist ein **Artefakt**: ein Ergebnis, das du außerhalb der Unterhaltung öffnen und nutzen kannst.

<video src="https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953" controls muted playsinline width="100%" poster="docs/assets/screens/oss-launch-planner-poster.webp">
  <img src="docs/assets/screens/oss-launch-planner-poster.webp" alt="Vstorm OSS Launch Planner: Zielgruppenauswahl, Projektempfehlung und Quellenlinks" width="100%">
</video>

[Video ansehen](https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953) · [Screenshot ansehen](docs/assets/screens/oss-launch-planner-poster.webp)

*Bearbeitete Demonstration ohne Wartezeiten. Die Repository-Zahlen entsprechen dem Stand der Aufnahme;
das Artefakt ruft keine Live-Daten ab. Verbindungen und Fähigkeiten wurden für diese Demo eingerichtet.*

## Beginne mit einer Aufgabe

| Deine Aufgabe | Was du dem Agenten gibst | Was du anfordern kannst |
|---|---|---|
| Eine Entscheidung vorbereiten | Ein Briefing und Zugriff auf relevante Anwendungen | Einen Vergleich mit Quellen, Empfehlungen und offenen Fragen |
| Eine Tabelle analysieren | Eine CSV-Datei und eine Frage | Berechnungen, Diagramme und ein Ergebnis zum Herunterladen |
| Fragen zu Firmenwissen beantworten | Handbücher, Richtlinien oder Produktdokumente | Eine Antwort mit überprüfbaren Quellenverweisen |
| Einen wiederkehrenden Bericht erstellen | Anweisungen, Quellen und einen Zeitplan | Einen neuen Bericht oder ein aktualisiertes Artefakt nach jedem Lauf |

Das sind Ausgangspunkte: Aktiviere die erforderlichen Werkzeuge und prüfe das Ergebnis für deine Aufgabe.
[Erstelle deinen ersten Dokumentenagenten](docs/howto/first-document-agent.de.md) oder [entdecke weitere Anwendungsfälle](docs/use-cases.de.md).

## Schnellstart

Installiere zuerst Docker mit Compose. Führe den folgenden Befehl unter macOS oder Linux aus;
unter Windows nutzt du WSL2 mit der WSL2-Integration von Docker Desktop. Der Installer führt dich
durch Modellzugriff, Benutzerkonto und Organisation und richtet die Umgebung mit einem Beispielagenten ein.

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

Öffne die Konsole unter **http://localhost:3000**, melde dich mit deinen konfigurierten Zugangsdaten an
und probiere den Beispielagenten aus. Füge danach ein Dokument hinzu oder verbinde ein Werkzeug für deine eigene Aufgabe.

<details>
<summary>Installer prüfen oder eine andere Bereitstellung wählen</summary>

Lies den [Installer](scripts/quickstart.sh) vor dem Ausführen. So prüfst du die Voraussetzungen ohne Installation:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- --check
```

Manuelle Einrichtung mit Docker Compose, Versionsauswahl und Fehlerbehebung beschreibt die [Installationsanleitung](docs/install.de.md).
Für die Entwicklung am Quellcode siehe [Mitwirken](CONTRIBUTING.de.md).

</details>

Du betreibst die Umgebung. Modelle, Dokumentenverarbeitung und angebundene Werkzeuge können je nach
Konfiguration externe Dienste nutzen. Siehe [Betriebsverantwortung](docs/rollout.de.md) und [Datenflüsse](docs/security.de.md).

## Die Plattform entdecken

Im Chat beauftragst du den Agenten. Der übrige Arbeitsbereich enthält die Anweisungen, das Wissen,
die Verbindungen, Ergebnisse und Kontrollen, mit denen sich diese Arbeit wiederholen lässt.

### Einen Agenten konfigurieren

Unter **Agents** erstellst du einen Assistenten für eine Aufgabe, wählst sein Modell, schreibst Anweisungen
und aktivierst Werkzeuge. Veröffentliche eine Version, wenn sie einsatzbereit ist. Frühere Versionen
lassen sich einsehen und Änderungen zurücknehmen. [Einen Agenten erstellen](docs/first-agent.de.md).

<!-- MEDIA: agent-builder | light + dark; same agent as the demo -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/agent-builder.webp">
  <img src="docs/assets/screens/light/agent-builder.webp" alt="Agent-Konfiguration mit Anweisungen, ausgewähltem Modell und veröffentlichter Version mit Entwurfsänderungen." width="100%">
</picture>

### Wiederverwendbare Abläufe vermitteln

**Skills** sind schriftliche Abläufe, die ein Agent bei Bedarf laden kann: etwa eine Angebotsprüfung,
das Abgleichen eines Berichts oder die Anwendung eures Schreibstils. Schreibe einen Ablauf einmal
und weise ihn den passenden Agenten zu. [Mehr über Skills](docs/skills.de.md).

<!-- MEDIA: skills | light + dark; library and artifact-pages procedure -->

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/skills.webp">
  <img src="docs/assets/screens/light/skills.webp" alt="Skills-Bibliothek mit wiederverwendbaren Abläufen." width="100%">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/skill-detail.webp">
  <img src="docs/assets/screens/light/skill-detail.webp" alt="Der Ablauf artifact-pages mit Anweisungen und Seitenvorlagen." width="100%">
</picture>

**Context** enthält dauerhaft relevante Informationen wie Produktnamen, ein Glossar oder Kommunikationsregeln.
Nutze ihn für Fakten und Regeln, die mehrere Aufgaben betreffen. Wähle, ob der Agent sie automatisch
erhält oder bei Bedarf liest. [Mehr über Kontext](docs/context.de.md).

<!-- MEDIA: context | light + dark; library and glossary content -->

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/context.webp">
  <img src="docs/assets/screens/light/context.webp" alt="Context-Bibliothek mit gemeinsam genutzten Glossardateien." width="100%">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/context-detail.webp">
  <img src="docs/assets/screens/light/context-detail.webp" alt="Glossarvorschau im Modus linked zum Lesen bei Bedarf." width="100%">
</picture>

### Dokumente durchsuchbar machen

**Knowledge bases** organisieren Dokumente in Sammlungen, die du Agenten zuweist. Beim Beantworten von
Fragen sucht der Agent darin nach passenden Textstellen. Dieses Vorgehen heißt häufig **RAG**,
also Retrieval-Augmented Generation. [Dokumente hinzufügen und verarbeiten](docs/file-processing.de.md).

<!-- MEDIA: knowledge-bases | light + dark -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/knowledge-bases.webp">
  <img src="docs/assets/screens/light/knowledge-bases.webp" alt="Wissensdatenbanken mit persönlichen Sammlungen und Organisationssammlungen." width="100%">
</picture>

Öffne eine Sammlung, um Dokumente und ihren Verarbeitungsstatus zu prüfen. Wähle, wie unterstützte Dokumente
gelesen werden, einschließlich Texterkennung für Scans (OCR).

<!-- MEDIA: knowledge-collection | light + dark -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/knowledge-collection.webp">
  <img src="docs/assets/screens/light/knowledge-collection.webp" alt="Die Sammlung vstorm mit dem erfolgreich verarbeiteten Dokument adding_features.md." width="100%">
</picture>

### Anwendungen verbinden

**MCP**, das Model Context Protocol, ist ein Standard zur Verbindung von KI-Agenten mit Werkzeugen und Datenquellen.
Auf der Seite **MCP servers** konfigurierst du kompatible Verbindungen, beispielsweise die Notion- und
GitHub-Werkzeuge aus der Demo. Verfügbare Aktionen hängen vom Server, den Zugangsdaten und den für den
Agenten aktivierten Werkzeugen ab. [Eine Anwendung verbinden](docs/mcp.de.md).

<!-- MEDIA: mcp-connections | capture light + dark -->
> **Screenshot-Platzhalter — Anwendungsverbindungen:** verbundene Notion- und GitHub-Server mit ausgewählten Werkzeugen; Zugangsdaten sind verborgen.

### Ergebnisse außerhalb des Chats aufbewahren

**Artifacts** sind Seiten, die ein Agent erstellt: Berichte, interaktive Vergleiche oder kleine Dashboards.
Öffne sie aus der Bibliothek, prüfe Versionen und lege fest, wer Zugriff erhält. Beim Aktualisieren desselben
Artefakts bleibt der Link zur aktuellen Seite erhalten; eine Unterhaltung kann auf eine bestimmte Version verweisen.

Ein Artefakt zeigt die Daten vom Zeitpunkt seiner Veröffentlichung. Ein neuer Agentenlauf kann es aktualisieren.
[Artefakte erstellen und teilen](docs/artifacts.de.md).

<!-- MEDIA: artifacts | capture light + dark; use the OSS Launch Planner from the video -->
> **Screenshot-Platzhalter — Artifacts:** Bibliothek und geöffneter OSS Launch Planner mit Zielgruppenauswahl und Empfehlung.

### Aktionen und Kosten prüfen

Ein **Run** ist eine Ausführung eines Agenten. **Activity / Runs** zeigt Status und erfassten Verbrauch;
öffne einen Lauf, um Unterhaltung und Werkzeugaufrufe zu prüfen. Budgetprüfungen berücksichtigen erfasste
Ausgaben vor Modellanfragen; laufende Anfragen oder parallele Ausführungen können ein Limit überschreiten.
[Budgets und Audit-Verlauf](docs/governance.de.md).

<!-- MEDIA: run-detail | capture light + dark; same run as the demo -->
> **Screenshot-Platzhalter — Ausführungsdetails:** Status, Dauer, erfasste Kosten und Werkzeugaufrufe der gezeigten Aufgabe.

Für unterstützte Werkzeugaktionen kannst du eine menschliche Freigabe verlangen. Die Anfrage erlaubt einer
Person, die geplante Operation vor ihrer Entscheidung zu prüfen. Der Zugriff auf Agenten und Ressourcen
wird über [Rollen und Berechtigungen](docs/permissions.de.md) gesteuert.

<!-- MEDIA: approval | capture light + dark; real pending operation -->
> **Screenshot-Platzhalter — Freigabe:** eine echte ausstehende Aktion mit Beschreibung und Bedienelementen zur Entscheidung.

### Wiederkehrende Arbeit planen

**Routines** führen einen Agenten nach Zeitplan oder bei einem konfigurierten Ereignis aus.
Nutze sie für wöchentliche Zusammenfassungen oder wiederkehrende Berichte. Dabei gelten die konfigurierten
Zugriffsrechte und Kontrollen; die Ausführung wird protokolliert. [Eine Routine einrichten](docs/triggers.de.md).

<!-- MEDIA: routines | capture light + dark; show an actual scheduled execution -->
> **Screenshot-Platzhalter — Routines:** Zeitplan eines Berichts, letzter abgeschlossener zeitgesteuerter Lauf und Link zum Ergebnis.

## Im Team arbeiten

Nutze die Webkonsole, stelle einen Agenten über die API bereit oder konfiguriere einen unterstützten Kanal
wie Slack, Telegram, Mattermost, eine gehostete Seite oder ein Website-Widget. [Einen Kanal auswählen](docs/channels.de.md).
Die optionale [Desktop-App](docs/desktop.de.md) öffnet die Konsole in einem eigenen Fenster, ergänzt um ein
Desktop-Maskottchen und einen Kurzbefehl zum Senden eines Screenshots in einen neuen Chat.

Organisationen, Ressourcenberechtigungen, der Zugangsdaten-Tresor und Nutzungsdashboards helfen Betreibern,
die Umgebung zu verwalten. [Eine Einführung planen](docs/rollout.de.md).

## Passt AgenticOS zu deinem Team?

AgenticOS richtet sich an Teams, die Agenten im Browser konfigurieren und nutzen sowie ihre eigene
Umgebung betreiben möchten. Entwickler ergänzen Fähigkeiten und Integrationen; Aufgabenverantwortliche
pflegen Anweisungen, Dokumente und Abläufe über die Oberfläche.

Wenn du einen verwalteten Dienst suchst, berücksichtige den Betriebsaufwand einer selbst gehosteten Plattform.
Benötigst du nur eine Agentenbibliothek in einer bestehenden Anwendung, prüfe ein Framework direkt.
Vergleiche Optionen nach Aufgabe, Bereitstellungsmodell und benötigten Kontrollen im [Plattformvergleich](docs/about/comparison.de.md).

## Für Entwickler und Betreiber

Die Plattform basiert auf FastAPI, Pydantic AI, PostgreSQL mit pgvector, Redis, Prefect und Next.js.
Die Agentenkonfiguration wählt registrierte Fähigkeiten aus; Entwickler erweitern diese im Code.

| Einstieg | Inhalt |
|---|---|
| [Architektur](docs/architecture.de.md) | Dienste, Speicherung und Ausführung |
| [Fähigkeiten](docs/reference/capabilities.de.md) | Verfügbare Werkzeuge und Konfiguration |
| [API](docs/api.de.md) | Integration mit deinen Anwendungen |
| [Modelle](docs/models.de.md) | Modellanbieter und Profile |
| [Sicherheit](docs/security.de.md) | Datenflüsse und Systemgrenzen |
| [Tests](docs/testing.de.md) | Testsuiten und Umfang der Abdeckung |

Beiträge sind willkommen. [Mitwirken](CONTRIBUTING.de.md) beschreibt Einrichtung und erforderliche Prüfungen;
die [Roadmap](docs/ROADMAP.md) zeigt geplante Arbeiten.

## Lizenz und Support

[Apache License 2.0](LICENSE). Siehe [NOTICE](NOTICE) und [Hinweise zu Drittanbieterkomponenten](THIRD_PARTY_NOTICES.md)
für Urheberhinweise und enthaltene Komponenten.

[Vstorm](https://vstorm.co/) pflegt AgenticOS und unterstützt bei Bereitstellung, Integrationen und individueller Entwicklung.
Support und Wartung werden für jedes Projekt vereinbart.
