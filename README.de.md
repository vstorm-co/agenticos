<!-- source_sha: a49d7398a1bf -->

<div align="center">

<h1><img src="docs/assets/amigo-walk.svg" alt="Amigo, das AgenticOS-Maskottchen" width="64" valign="middle"> AgenticOS</h1>

<p>
  <b>Lass KI in deinem Unternehmen mitarbeiten.</b><br>
  Der Open-Source-Agent-Layer für gemeinsame Agenten, Unternehmenswissen und Automatisierung — auf Infrastruktur, die du kontrollierst.
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

Gib einem Agenten das Briefing, das Wissen und die Werkzeuge. Lass ihn recherchieren, Berichte vorbereiten und Ergebnisse erstellen, die dein Team nutzen kann. Anweisungen, Zugriffsrechte und Ausführungsverlauf bleiben an einem Ort; du wählst Cloud- oder lokale Modelle.

<h3 align="center">🔌 5.700+ Integrationen über MCP &nbsp;·&nbsp; 🤝 Gemeinsame Agenten und Wissen<br>
📊 Integrierte Observability &nbsp;·&nbsp; 🏠 Selbst gehostet</h3>

## So funktioniert es

**Von einem Briefing in Notion und GitHub-Recherche zu einer interaktiven Entscheidungsseite.**

<video src="https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512" controls playsinline width="100%" poster="docs/assets/screens/oss-launch-planner-poster.webp">
  <img src="docs/assets/screens/oss-launch-planner-poster.webp" alt="Vstorm OSS Launch Planner: Zielgruppenauswahl, Projektempfehlung und Quellenlinks" width="100%">
</video>

<details>
<summary>Video wird nicht geladen? Animierte Vorschau öffnen</summary>

<a href="https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512">
  <img src="docs/assets/screens/oss-launch-planner-preview.gif" alt="Vstorm OSS Launch Planner: Zielgruppenauswahl, Projektempfehlung und Quellenlinks" width="100%">
</a>

*Animierte Vorschau mit 2× Geschwindigkeit. Klicke für das 37-sekündige Video mit Ton in normalem Tempo.*

</details>

[Gekürztes Video ansehen (37 Sekunden)](https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512) · [Screenshot ansehen](docs/assets/screens/oss-launch-planner-poster.webp)

*Bearbeitete Demonstration ohne Wartezeiten. Die Repository-Zahlen entsprechen dem Stand der Aufnahme;
das Artefakt ruft keine Live-Daten ab. Verbindungen und Fähigkeiten wurden für diese Demo eingerichtet.*

## 💬 Agenten dort einsetzen, wo dein Team bereits arbeitet

<p align="center">
  <a href="docs/channels.de.md"><img src="docs/assets/channels/slack.svg" alt="Slack" width="176" height="64"></a>
  <a href="docs/channels.de.md"><img src="docs/assets/channels/mattermost.svg" alt="Mattermost" width="176" height="64"></a>
  <a href="docs/channels.de.md"><img src="docs/assets/channels/telegram.svg" alt="Telegram" width="176" height="64"></a>
</p>

Nutze deinen veröffentlichten Agenten in **Slack, Mattermost oder Telegram**. Kollegen können in ihren vertrauten Werkzeugen um Hilfe bitten; der Agent nutzt seine konfigurierten Anweisungen, sein Wissen und seine Werkzeuge.

**Ein Agent, mehrere Zugangswege:** Team-Messenger, AgenticOS-Webchat, Website-Widget, gehostete Seite oder deine eigene Anwendung über die API. Richte den Kanal ein, verwalte die veröffentlichte Agentenversion zentral und prüfe seine Ausführungen in Activity.

[Slack, Mattermost und weitere Kanäle verbinden](docs/channels.de.md).

## Den Agent-Layer erkunden

<table>
<tr>
<td colspan="2" valign="top">

### 📄 Ergebnisse außerhalb des Chats aufbewahren

**Artifacts** sind Seiten, die ein Agent erstellt: Berichte, interaktive Vergleiche oder kleine Dashboards.
Öffne sie aus der Bibliothek, prüfe Versionen und lege fest, wer Zugriff erhält. Beim Aktualisieren desselben
Artefakts bleibt der Link zur aktuellen Seite erhalten; eine Unterhaltung kann auf eine bestimmte Version verweisen.

Ein Artefakt zeigt die Daten vom Zeitpunkt seiner Veröffentlichung. Ein neuer Agentenlauf kann es aktualisieren.
[Artefakte erstellen und teilen](docs/artifacts.de.md).

<!-- MEDIA: artifacts | light -->

<a href="docs/assets/screens/light/artifacts.webp">
  <img src="docs/assets/screens/window-chrome.svg" alt="" width="100%"><br>
  <img src="docs/assets/screens/light/artifacts.webp" alt="Artefaktbibliothek mit gespeicherten Berichten und Versionen." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🤖 Einen Agenten konfigurieren

Unter **Agents** erstellst du einen Assistenten für eine Aufgabe, wählst sein Modell, schreibst Anweisungen
und aktivierst Werkzeuge. Veröffentliche eine Version, wenn sie einsatzbereit ist. Frühere Versionen
lassen sich einsehen und Änderungen zurücknehmen. [Einen Agenten erstellen](docs/first-agent.de.md).

</td>
<td width="70%">

<!-- MEDIA: agent-builder | light -->

<a href="docs/assets/screens/light/agent-builder.webp">
  <img src="docs/assets/screens/window-chrome.svg" alt="" width="100%"><br>
  <img src="docs/assets/screens/light/agent-builder.webp" alt="Agent-Konfiguration mit Anweisungen, ausgewähltem Modell und aktueller veröffentlichter Version." width="100%">
</a>

</td>
</tr>
<tr>
<td colspan="2" valign="top">

### 🔌 5.700+ Integrationen über MCP

Verbinde Agenten mit den Werkzeugen, die dein Unternehmen bereits nutzt: **GitHub, Notion, HubSpot, Linear und n8n**.
**MCP** (Model Context Protocol) ist der Standard, über den Agenten externe Werkzeuge und Datenquellen aufrufen.

Durchsuche **über 5.700 MCP-Servereinträge** im Katalog oder füge einen kompatiblen Server per URL hinzu.
Verbinde die benötigten Dienste und wähle die Werkzeuge für jeden Agenten. Einrichtung, Zugangsdaten
und verfügbare Aktionen hängen vom Server ab. [Werkzeuge verbinden](docs/mcp.de.md).

<!-- MEDIA: mcp-catalog | light -->

<a href="docs/assets/screens/light/mcp-catalog.webp">
  <img src="docs/assets/screens/window-chrome.svg" alt="" width="100%"><br>
  <img src="docs/assets/screens/light/mcp-catalog.webp" alt="MCP-Katalog mit GitHub, Notion, Slack und weiteren Diensten sowie dem Verbindungsstatus." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🧩 Wiederverwendbare Abläufe vermitteln

**Skills** sind schriftliche Abläufe, die ein Agent bei Bedarf laden kann: etwa eine Angebotsprüfung,
das Abgleichen eines Berichts oder die Anwendung eures Schreibstils. Schreibe einen Ablauf einmal
und weise ihn den passenden Agenten zu. [Mehr über Skills](docs/skills.de.md).

</td>
<td width="70%">

<!-- MEDIA: skills | light -->

<a href="docs/assets/screens/light/skill-detail.webp">
  <img src="docs/assets/screens/window-chrome.svg" alt="" width="100%"><br>
  <img src="docs/assets/screens/light/skill-detail.webp" alt="Der Ablauf artifact-pages mit Anweisungen und Seitenvorlagen." width="100%">
</a>

</td>
</tr>
<tr>
<td colspan="2" valign="top">

### 📚 Dokumente durchsuchbar machen

**Knowledge bases** organisieren Dokumente in Sammlungen, die du Agenten zuweist. Beim Beantworten von
Fragen sucht der Agent darin nach passenden Textstellen. Dieses Vorgehen heißt häufig **RAG**,
also Retrieval-Augmented Generation. [Dokumente hinzufügen und verarbeiten](docs/file-processing.de.md).

<!-- MEDIA: knowledge-bases | light -->

<a href="docs/assets/screens/light/knowledge-bases.webp">
  <img src="docs/assets/screens/window-chrome.svg" alt="" width="100%"><br>
  <img src="docs/assets/screens/light/knowledge-bases.webp" alt="Wissensdatenbanken mit persönlichen Sammlungen und Organisationssammlungen." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🧠 Gemeinsamer Kontext

**Context** enthält dauerhaft relevante Informationen wie Produktnamen, ein Glossar oder Kommunikationsregeln.
Nutze ihn für Fakten und Regeln, die mehrere Aufgaben betreffen. Wähle, ob der Agent sie automatisch
erhält oder bei Bedarf liest. [Mehr über Kontext](docs/context.de.md).

</td>
<td width="70%">

<!-- MEDIA: context | light -->

<a href="docs/assets/screens/light/context-detail.webp">
  <img src="docs/assets/screens/window-chrome.svg" alt="" width="100%"><br>
  <img src="docs/assets/screens/light/context-detail.webp" alt="Glossarvorschau im Modus linked zum Lesen bei Bedarf." width="100%">
</a>

</td>
</tr>
<tr>
<td colspan="2" valign="top">

### 📊 Integrierte Observability: Ausführungen und Kosten im Blick

**Activity** bündelt Ausführungsverlauf, Freigaben und Ausgaben. Ein **Run** ist eine Ausführung eines Agenten:
Du siehst Status, Modell, Token, Dauer und erfasste Kosten. Filtere nach Agent, Person oder Version,
vergleiche Versionsergebnisse und exportiere die Daten als CSV.

Finde langsame oder fehlgeschlagene Ausführungen und öffne sie, um Unterhaltung und Werkzeugaufrufe zu prüfen.
[Activity und Kostenkontrolle erkunden](docs/governance.de.md).

<!-- MEDIA: activity | light; filtered run history and version comparison -->

<a href="docs/assets/screens/light/activity.webp">
  <img src="docs/assets/screens/window-chrome.svg" alt="" width="100%"><br>
  <img src="docs/assets/screens/light/activity.webp" alt="Activity mit Versionsvergleich und gefiltertem Ausführungsverlauf: Status, Token, Dauer und erfasste Kosten." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🛡️ Menschliche Freigabe

Für unterstützte Werkzeugaktionen kannst du eine menschliche Freigabe verlangen. Die Anfrage erlaubt einer
Person, die geplante Operation vor ihrer Entscheidung zu prüfen. Der Zugriff auf Agenten und Ressourcen
wird über [Rollen und Berechtigungen](docs/permissions.de.md) gesteuert.

</td>
<td width="70%">

<!-- MEDIA: approval | light -->

<a href="docs/assets/screens/light/approval.webp">
  <img src="docs/assets/screens/window-chrome.svg" alt="" width="100%"><br>
  <img src="docs/assets/screens/light/approval.webp" alt="Ausstehender Werkzeugaufruf mit Argumenten und Freigabesteuerung." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### ⏱️ Wiederkehrende Arbeit planen

**Routines** führen einen Agenten nach Zeitplan oder bei einem konfigurierten Ereignis aus.
Nutze sie für wöchentliche Zusammenfassungen oder wiederkehrende Berichte. Dabei gelten die konfigurierten
Zugriffsrechte und Kontrollen; die Ausführung wird protokolliert. [Eine Routine einrichten](docs/triggers.de.md).

</td>
<td width="70%">

<!-- MEDIA: routines | light; existing weekly schedule configuration -->

<a href="docs/assets/screens/light/routines.webp">
  <img src="docs/assets/screens/window-chrome.svg" alt="" width="100%"><br>
  <img src="docs/assets/screens/light/routines.webp" alt="Zeitplan-Editor mit wöchentlicher Wiederholung am Montag um 06:00 UTC und Vorschau der Agentennachricht." width="100%">
</a>

</td>
</tr>
</table>

<details>
<summary>Weitere Ansichten und Ausführungsdetails</summary>

<a href="docs/assets/screens/light/skills.webp">
  <img src="docs/assets/screens/window-chrome.svg" alt="" width="100%"><br>
  <img src="docs/assets/screens/light/skills.webp" alt="Skills-Bibliothek mit wiederverwendbaren Abläufen." width="100%">
</a>

<a href="docs/assets/screens/light/context.webp">
  <img src="docs/assets/screens/window-chrome.svg" alt="" width="100%"><br>
  <img src="docs/assets/screens/light/context.webp" alt="Context-Bibliothek mit gemeinsam genutzten Glossardateien." width="100%">
</a>

<!-- MEDIA: knowledge-collection | light; supplementary view -->

<a href="docs/assets/screens/light/knowledge-collection.webp">
  <img src="docs/assets/screens/window-chrome.svg" alt="" width="100%"><br>
  <img src="docs/assets/screens/light/knowledge-collection.webp" alt="Die Sammlung vstorm mit dem erfolgreich verarbeiteten Dokument adding_features.md." width="100%">
</a>

<a href="docs/assets/screens/light/artifact-detail.webp">
  <img src="docs/assets/screens/window-chrome.svg" alt="" width="100%"><br>
  <img src="docs/assets/screens/light/artifact-detail.webp" alt="OSS Launch Planner aus der Demo mit Zielgruppenauswahl und Empfehlung." width="100%">
</a>

### Aktionen und Kosten prüfen

Ein **Run** ist eine Ausführung eines Agenten. **Activity / Runs** zeigt Status und erfassten Verbrauch;
öffne einen Lauf, um Unterhaltung und Werkzeugaufrufe zu prüfen. Budgetprüfungen berücksichtigen erfasste
Ausgaben vor Modellanfragen; laufende Anfragen oder parallele Ausführungen können ein Limit überschreiten.
[Budgets und Audit-Verlauf](docs/governance.de.md).

<!-- MEDIA: run-detail | capture light with expanded sidebar; same run as the demo -->
> **Screenshot-Platzhalter — Ausführungsdetails:** Status, Dauer, erfasste Kosten und Werkzeugaufrufe der gezeigten Aufgabe.

</details>

## KI-Arbeit im Team verankern

Bei einem regelmäßigen Bericht kann das Team die Arbeit aufteilen:

1. **Eine Fachperson legt das Vorgehen fest:** Sie pflegt Anweisungen, Skills und Wissensquellen.
2. **Eine zuständige Person stellt den Agenten bereit:** Sie konfiguriert Werkzeuge, veröffentlicht eine Version und erteilt Kollegen Zugriff.
3. **Kollegen nutzen die Ergebnisse:** Sie führen den Agenten aus, prüfen seine Antwort und teilen ein Artefakt mit passenden Zugriffseinstellungen.

Agent und wiederverwendbares Wissen bleiben bei der Organisation. Das Team arbeitet im Browser;
Entwickler können interne Systeme anbinden. [Teamzugriff einrichten](docs/permissions.de.md).

## Schnellstart

Installiere zuerst Docker mit Compose. Führe den folgenden Befehl unter macOS oder Linux aus;
unter Windows nutzt du WSL2 mit der WSL2-Integration von Docker Desktop. Der Installer führt dich
durch Modellzugriff, Benutzerkonto und Organisation und richtet die Umgebung mit einem Beispielagenten ein.

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

Öffne die Konsole unter **http://localhost:3000** und melde dich mit deinen konfigurierten Zugangsdaten an.

### Die erste Aufgabe ausprobieren

Wähle unter **Chat** den Agenten **Getting Started** und füge dieses fiktive Briefing ein. Der Modellzugriff muss
eingerichtet sein; für diese Übung brauchst du keine Verbindung zu Notion oder GitHub.

```text
Antworte auf Deutsch. Erstelle aus diesem Briefing eine Checkliste für den Start. Nutze nur die genannten Fakten.
Nenne für jede Aufgabe die verantwortliche Person, die Frist und fehlende Informationen.
Erfinde keine Termine oder Zuständigkeiten.

Briefing:
- Das Kundenwebinar findet am 15. Oktober statt.
- Maya betreut die Landingpage; sie muss bis zum 8. Oktober fertig sein.
- Leo betreut die Demo, aber der Termin für ihre Prüfung steht noch nicht fest.
- Die Einladungen müssen bis zum 10. Oktober verschickt werden; niemand ist dafür eingeteilt.
```

**Prüfe das Ergebnis:** Bei der Landingpage sollten Maya und der 8. Oktober stehen; bei der Demo
sollte der fehlende Prüftermin auffallen, bei den Einladungen die fehlende Zuständigkeit. Probiere danach
dein eigenes Briefing aus oder
[konfiguriere einen Agenten mit Werkzeugen und Unternehmenswissen](docs/first-agent.de.md).

<details>
<summary>Installer prüfen oder eine andere Bereitstellung wählen</summary>

Lies den [Installer](scripts/quickstart.sh) vor dem Ausführen. So prüfst du die Voraussetzungen ohne Installation:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- --check
```

Manuelle Einrichtung mit Docker Compose, Versionsauswahl und Fehlerbehebung beschreibt die [Installationsanleitung](docs/install.de.md).
Für die Entwicklung am Quellcode siehe [Mitwirken](CONTRIBUTING.de.md).

</details>

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

<details>
<summary>Wohin deine Daten gelangen</summary>

| Komponente | Was du entscheidest |
|---|---|
| Anwendung und Speicherung | Du betreibst Anwendung, Datenbank und konfigurierten Dateispeicher; wähle den Betriebsort und die Sicherung |
| Sprachmodelle | Ein gehosteter Anbieter erhält den zur Inferenz gesendeten Kontext; wähle einen lokalen Endpunkt, wenn diese Verarbeitung in deiner Infrastruktur bleiben muss |
| Dokumentverarbeitung und Suche | Prüfe Parser und Embedding-Anbieter getrennt: Ein lokales Chatmodell macht einen Cloud-Parser oder externe Embeddings nicht lokal |
| Werkzeuge und Kanäle | Aktivierte Integrationen tauschen die für ihre Aufrufe nötigen Daten aus; verbundene Kanäle erhalten die darüber gesendeten Antworten |
| Beobachtbarkeit | Optionales Tracing kann Ausführungsdaten exportieren; prüfe sowohl die Einstellungen der Bereitstellung als auch die einzelnen Agenten |

[Datengrenzen prüfen](docs/security.de.md#what-leaves-the-deployment) ·
[Dokumentverarbeitung wählen](docs/file-processing.de.md).

</details>

## Passt AgenticOS zu deinem Unternehmen?

Wähle AgenticOS, wenn dein Unternehmen gemeinsame Agenten, Wissen und Automatisierung mit Kontrolle über
Quellcode, Modelle und Betrieb benötigt. Dein Team betreibt die Installation; Vstorm kann bei Umsetzung
und Support helfen. Wenn du nur eine Agentenbibliothek in einer bestehenden Anwendung benötigst, beginne
mit einem Framework. Bei einem vollständig verwalteten Dienst gehört die Betriebsverantwortung in den Vergleich.

Vergleiche den Ansatz mit [Dify](docs/about/dify.de.md), [Viktor](docs/about/viktor.de.md) und
[Wonderful](docs/about/wonderful.de.md), oder nutze den [Vergleichsleitfaden](docs/about/comparison.de.md)
für die Auswahl nach Aufgabe, Eigentum und erforderlichen Kontrollen.

<details>
<summary>Fragen zum Agent-Layer</summary>

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

</details>

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

## Brauchst du Hilfe beim produktiven Einsatz von Agenten?

Vstorm kann AgenticOS in der Infrastruktur des Kunden bereitstellen, Dokumentation erstellen, Prozesse definieren und individuelle Komponenten entwickeln. Wartung und Support werden für das jeweilige Projekt vereinbart.

Mit Sorgfalt entwickelt von [**Vstorm**](https://vstorm.co) · [oss.vstorm.co](https://oss.vstorm.co)
