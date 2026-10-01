<!-- source_sha: 571c0eb5fe9a -->

<div align="center">

<img src="docs/assets/amigo-walk.svg" alt="Amigo, das AgenticOS-Maskottchen" width="144">

<h1>AgenticOS</h1>

<p>
  <b>Der Open-Source-Agent-Layer für dein Unternehmen.</b><br>
  Gemeinsame KI-Agenten, Unternehmenswissen und Automatisierung — auf Infrastruktur, die du kontrollierst.
</p>

<p>
  <a href="#so-funktioniert-es">Demo ansehen</a> &middot;
  <a href="#schnellstart">Schnellstart</a> &middot;
  <a href="#den-agent-layer-erkunden">Den Agent-Layer erkunden</a> &middot;
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

AgenticOS ist ein selbst gehosteter Open-Source-Agent-Layer für Teams. Erstelle KI-Agenten im Browser,
verbinde sie mit Unternehmensdokumenten und Werkzeugen und teile sie mit den Personen, die sie benötigen.
Agenten können recherchieren, Dateien analysieren, Berichte erstellen und mehrstufige Aufgaben erledigen.
Deine Organisation kontrolliert ihren Zugriff, die Modellwahl und den Betrieb.

Wenn Agenten zum Arbeitsalltag gehören, muss das Team wissen, welche es nutzen kann, worauf sie zugreifen
und was ihre Arbeit kostet. AgenticOS bündelt Agenten, wiederverwendbare Anweisungen, Wissen,
Automatisierung und Ausführungsverläufe an einem Ort.

**Apache-2.0 · Selbst gehostet · Cloud- oder lokale Modelle · Gemeinsame Agenten und Wissen**

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

## KI-Arbeit im Team verankern

Der Vertrieb kann einen Rechercheagenten pflegen, der Betrieb einen wöchentlichen Bericht planen und
Fachexperten das Wissen aktualisieren, das diese Agenten nutzen. Das Team arbeitet im Browser;
Entwickler erweitern Werkzeuge und verbinden interne Systeme. Die Organisation behält die Agenten
und das wiederverwendbare Know-how.

| Was dein Team braucht | Wie AgenticOS hilft |
|---|---|
| Einheitliche Arbeitsweisen | **Skills** speichern wiederverwendbare Abläufe; **Context** enthält gemeinsame Fakten, Begriffe und Richtlinien |
| Antworten aus Unternehmensdokumenten | **Wissensdatenbanken** enthalten durchsuchbare Sammlungen; Retrieval-Augmented Generation (**RAG**) findet relevante Textstellen |
| Aktionen in vorhandenen Anwendungen | **MCP** (Model Context Protocol) verbindet Agenten mit kompatiblen Werkzeugen und Datenquellen wie Notion und GitHub |
| Nutzbare Ergebnisse für Kollegen | **Artifacts** sind gespeicherte Seiten wie Berichte und interaktive Dashboards, mit Versionen und Zugriffseinstellungen |
| Wiederkehrende Arbeit | **Routines** starten Agenten nach Zeitplan oder konfiguriertem Ereignis und protokollieren die Ausführung |
| Passender Zugriff pro Person | Organisationen, Rollen und Ressourcenfreigaben regeln, wer gemeinsame Agenten und Wissen nutzen und verwalten darf |

Nutze veröffentlichte Agenten im Webchat oder in unterstützten Kanälen wie Slack, Telegram und Mattermost,
oder binde sie über die API, eine gehostete Seite oder ein Website-Widget ein. [Kanäle erkunden](docs/channels.de.md).

## Betrieb, Modelle und Zugriff selbst kontrollieren

**Auf eigener Infrastruktur betreiben.** AgenticOS ist Apache-2.0-Software, die du prüfen, ändern und
betreiben kannst. Wähle Cloudanbieter oder lokale Modelle über Ollama und kompatible Endpunkte wie vLLM.
Fähigkeiten und Hardwareanforderungen hängen vom gewählten Modell ab. [Modelle konfigurieren](docs/models.de.md).

**Festlegen, was ein Agent tun darf.** Konfiguriere Ressourcenrechte, speichere Zugangsdaten im Vault
und verlange für unterstützte Werkzeugaktionen eine menschliche Freigabe.
[Zugriffskontrollen](docs/permissions.de.md) · [Geheimnisse](docs/secrets.de.md).

**Arbeit und Ausgaben nachvollziehen.** Ein Run ist eine Ausführung eines Agenten. Prüfe Werkzeugaufrufe
und erfassten Verbrauch sowie Audit-Einträge für Verwaltungsaktionen. Budgets prüfen erfasste Ausgaben
vor Modellanfragen; laufende oder parallele Anfragen können eine Grenze überschreiten.
[Ausführungen und Kosten kontrollieren](docs/governance.de.md).

Beim [Self-Hosting](docs/rollout.de.md) übernimmt dein Team Betrieb, Updates und Backups. Externe Modelle, Parser, Embeddings,
Werkzeuge und Tracing können weiterhin Daten aus deiner Infrastruktur übertragen. Konfiguriere jede
Komponente nach deinen Datenanforderungen. [Sicherheit und Datenflüsse](docs/security.de.md).

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

## Den Agent-Layer erkunden

### Einen Agenten konfigurieren

Unter **Agents** erstellst du einen Assistenten für eine Aufgabe, wählst sein Modell, schreibst Anweisungen
und aktivierst Werkzeuge. Veröffentliche eine Version, wenn sie einsatzbereit ist. Frühere Versionen
lassen sich einsehen und Änderungen zurücknehmen. [Einen Agenten erstellen](docs/first-agent.de.md).

<!-- MEDIA: agent-builder | light + dark; same agent as the demo -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/agent-builder.webp">
  <img src="docs/assets/screens/light/agent-builder.webp" alt="Agent-Konfiguration mit Anweisungen, ausgewähltem Modell und veröffentlichter Version mit Entwurfsänderungen." width="100%">
</picture>

<details>
<summary>Produktrundgang öffnen: Konfiguration, gemeinsames Wissen, Integrationen und Automatisierung</summary>

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

</details>

## Passt AgenticOS zu deinem Unternehmen?

Wähle AgenticOS, wenn dein Unternehmen gemeinsame Agenten, Wissen und Automatisierung mit Kontrolle über
Quellcode, Modelle und Betrieb benötigt. Dein Team betreibt die Installation; Vstorm kann bei Umsetzung
und Support helfen. Wenn du nur eine Agentenbibliothek in einer bestehenden Anwendung benötigst, beginne
mit einem Framework. Bei einem vollständig verwalteten Dienst gehört die Betriebsverantwortung in den Vergleich.

Vergleiche den Ansatz mit [Dify](docs/about/dify.de.md), [Viktor](docs/about/viktor.de.md) und
[Wonderful](docs/about/wonderful.de.md), oder nutze den [Vergleichsleitfaden](docs/about/comparison.de.md)
für die Auswahl nach Aufgabe, Eigentum und erforderlichen Kontrollen.

## Fragen zum Agent-Layer

### Ist AgenticOS ein AI Agent Harness?

AgenticOS verbindet einen AI Agent Harness mit einer Teamoberfläche: Modellausführung, Werkzeuge,
Skills, Kontext und Kontrollen werden im Browser konfiguriert. Entwickler ergänzen Fähigkeiten im Code;
Teams konfigurieren und nutzen sie. Die [Architektur](docs/architecture.de.md) beschreibt die Ausführung.

### Kann ich einen Agenten nach dem Vorbild von Claude Code für Geschäftsaufgaben erstellen?

Du kannst einen Agenten für mehrstufige Arbeit mit Dateien, Werkzeugen und delegierten Aufgaben
konfigurieren. Verfügbare Aktionen hängen von aktivierten Fähigkeiten und der Unterstützung
durch das Modell ab. AgenticOS ist ein unabhängiges Projekt mit eigener Laufzeit und Modellwahl.
Siehe den [Vergleich mit Claude Code](docs/about/claude-code.de.md).

### Was können Kollegen gemeinsam nutzen?

Teams können Agenten, Skills, Kontext, Wissenssammlungen und Artifacts gemäß den Ressourcenrechten teilen.
Ein gemeinsamer Agent kann verschiedene Personen unterstützen; ein geteiltes Artifact macht ein Ergebnis
außerhalb des Chats zugänglich.

## Für Entwickler und Betreiber

AgenticOS basiert auf FastAPI, Pydantic AI, PostgreSQL mit pgvector, Redis, Prefect und Next.js.
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
