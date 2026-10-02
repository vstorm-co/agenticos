<!-- source_sha: afab117df33b -->

<div align="center">

<h1><img src="docs/assets/amigo-walk.svg" alt="Amigo, das AgenticOS-Maskottchen" width="64" valign="middle"> AgenticOS</h1>

<p>
  <strong>Sovereign Agentic AI Layer</strong><br>
  <b>KI-Agenten, die dein ganzes Team nutzen und verbessern kann.</b><br>
  Open Source. Erstelle gemeinsame Agenten im Browser, auf Infrastruktur, die du kontrollierst.
</p>

<p>
  <a href="#schnellstart">Schnellstart</a> &middot;
  <a href="#erstellen-teilen-und-betreiben">Erstellen, teilen und betreiben</a> &middot;
  <a href="#passt-agenticos-zu-deinem-team">Passt es zu uns?</a> &middot;
  <a href="https://vstorm-co.github.io/agenticos/de/">Dokumentation</a>
</p>

<p>
  <a href="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml"><img src="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://github.com/vstorm-co/agenticos/releases"><img src="https://img.shields.io/github/v/release/vstorm-co/agenticos?label=release&color=blue" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-Apache--2.0-blue" alt="Apache-2.0"></a>
  <a href="https://ai.pydantic.dev"><img src="https://img.shields.io/badge/Powered%20by-Pydantic%20AI-E92063?logo=pydantic&logoColor=white" alt="Gebaut mit Pydantic AI"></a>
</p>

<p>
  <a href="README.md">English</a> &middot;
  <a href="README.pl.md">Polski</a> &middot;
  <b>Deutsch</b> &middot;
  <a href="README.es.md">Español</a>
</p>

</div>

AgenticOS ist eine selbst gehostete Arbeitsumgebung zum Erstellen und Betreiben gemeinsamer KI-Agenten. Gib einem Agenten eine Aufgabe, verbinde Unternehmensdokumente und Werkzeuge und veröffentliche ihn für dein Team. Entwickler erweitern seine Fähigkeiten; Fachexperten pflegen seine Anweisungen und sein Wissen.

<a href="docs/assets/screens/light/agent-builder.webp">
  <img src="docs/assets/screens/light/agent-builder.webp" alt="Agent Builder mit Anweisungen, Modellauswahl und einer veröffentlichten Version." width="100%">
</a>

## Was du damit machen kannst

- **Im Browser erstellen:** Modell, Anweisungen, Wissen und Werkzeuge eines Agenten konfigurieren und eine Version veröffentlichen.
- **Im Team arbeiten:** Fachleute pflegen Anweisungen und Dokumente; Kollegen erhalten Zugriff auf den veröffentlichten Agenten.
- **Ergebnisse teilen:** Berichte, Vergleiche und Dashboards als Artefakte mit geregeltem Zugriff veröffentlichen.
- **Ausführungen prüfen und wiederholen:** Werkzeugaufrufe und erfasste Kosten in Activity prüfen; Agenten nach Zeitplan oder durch Ereignisse starten.
- **Infrastruktur selbst wählen:** selbst hosten, gehostete oder lokale Modelle anbinden und Fähigkeiten in Python erweitern.

## Schnellstart

Du brauchst nur Docker mit Compose. Unter macOS oder Linux führst du aus:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

Unter Windows führst du denselben Befehl in WSL2 aus, mit eingeschalteter WSL2-Integration in Docker Desktop.
Der Installer fragt nach Modellanbieter und Schlüssel, deinem Login und dem Namen der Organisation, lädt die
veröffentlichten Images und startet eine Bereitstellung mit einem funktionierenden Agenten.

Öffne **http://localhost:3000** und melde dich mit dem bei der Installation gewählten Login an.

**Dein erster Agent:** Folge der [Anleitung für einen Dokumentassistenten](https://vstorm-co.github.io/agenticos/de/howto/first-document-agent/), um ein Handbuch hochzuladen, Fragen zu stellen, Antworten anhand der zitierten Quellen zu prüfen und ein aktualisiertes Dokument zu testen. Die Dokumentsuche benötigt ein Embedding-Modell. Weitere Aufgaben behandelt [Einen Agenten erstellen](https://vstorm-co.github.io/agenticos/de/first-agent/).

<details>
<summary>Installer prüfen oder eine andere Bereitstellung wählen</summary>

Lies den [Installer](scripts/quickstart.sh) vor dem Ausführen. So prüfst du die Voraussetzungen ohne Installation:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- --check
```

Manuelle Einrichtung mit Docker Compose, Versionsauswahl und Fehlerbehebung beschreibt die [Installationsanleitung](https://vstorm-co.github.io/agenticos/de/install/).
Für die Entwicklung am Quellcode siehe [Mitwirken](https://vstorm-co.github.io/agenticos/de/help/).

</details>

## Erstellen, teilen und betreiben

### Die Arbeitsweise einmal konfigurieren

Wähle Modell, Anweisungen und Werkzeuge im Browser. Veröffentliche eine Version für Kollegen; frühere Versionen bleiben zum Prüfen und Wiederherstellen verfügbar.

[Wissensdatenbanken](https://vstorm-co.github.io/agenticos/de/file-processing/) liefern durchsuchbare Dokumente. [Skills](https://vstorm-co.github.io/agenticos/de/skills/) enthalten wiederverwendbare Abläufe; [Kontext](https://vstorm-co.github.io/agenticos/de/context/) hält gemeinsame Fakten und Richtlinien fest. Aktualisiere diese Ressourcen, wenn sich die Arbeit ändert.

Verbinde Werkzeuge wie **GitHub, Notion, HubSpot oder Linear** über [MCP](https://vstorm-co.github.io/agenticos/de/mcp/). Der Katalog verbindet kuratierte Verbindungen mit **über 5.700 MCP-Servereinträgen** aus einer gespiegelten Registry. Registry-Einträge sind Metadaten der Herausgeber, keine getesteten Integrationen. Jede Verbindung braucht eine eigene Einrichtung und Zugriffsprüfung.

### Agenten und Ergebnisse zugänglich machen

Kollegen können einen veröffentlichten Agenten im Webchat oder über konfigurierte **Slack-, Mattermost- und Telegram-Kanäle** nutzen. Entwickler können ihn über die API aufrufen. [Einen Kanal verbinden](https://vstorm-co.github.io/agenticos/de/channels/).

Agenten können Berichte, interaktive Vergleiche und kleine Dashboards als **Artefakte** veröffentlichen. Lege fest, wer sie öffnen darf; bei Aktualisierungen desselben Artefakts bleibt der Link erhalten, und frühere Versionen bleiben lesbar. [Ein Artefakt teilen](https://vstorm-co.github.io/agenticos/de/artifacts/).

<a href="docs/assets/screens/light/artifacts.webp">
  <img src="docs/assets/screens/light/artifacts.webp" alt="Artefaktbibliothek mit Berichten, Zugriffseinstellungen und Versionen." width="100%">
</a>

### Ausführungen prüfen und nützliche Arbeit wiederholen

**Activity** vereint Ausführungsverlauf, Freigaben und erfasste Ausgaben. Prüfe Werkzeugaufrufe, vergleiche Agentenversionen und exportiere Datensätze. Manche Kosten hängen von Nutzungs- und Preisdaten des Anbieters ab; externe Dienste können separat abrechnen. [Grenzen der Kostenerfassung](https://vstorm-co.github.io/agenticos/de/governance/).

<a href="docs/assets/screens/light/activity.webp">
  <img src="docs/assets/screens/light/activity.webp" alt="Activity mit Versionsvergleichen und Ausführungsverlauf, einschließlich einer ausstehenden Freigabe." width="100%">
</a>

Konfiguriere Freigabeanforderungen für unterstützte Capability-Werkzeuge. Im Webchat erfasst **Ask about everything** auch MCP-Werkzeugaufrufe, die der Runner ausführt. Der Umfang der Freigaben hängt vom Werkzeug und Ausführungsmodus ab; das Aktivieren einer Verbindung allein verlangt keine Freigabe. [Freigabemodi und Grenzen](https://vstorm-co.github.io/agenticos/de/governance/#how-much-one-conversation-wants-to-be-asked).

Wenn sich eine Aufgabe bewährt hat, führe den Agenten mit [Routinen](https://vstorm-co.github.io/agenticos/de/triggers/) nach Zeitplan oder Ereignis aus. Teste Werkzeuge, Limits und Freigaberegeln, bevor du ihn unbeaufsichtigt arbeiten lässt.

## Aufgezeichnetes Integrationsbeispiel

Diese Demo zeigt, wie aus einem Notion-Briefing nach einer GitHub-Recherche eine interaktive Seite mit Quellen wird. Als Beispielmaterial dienen Vstorms eigene Open-Source-Projekte: Der relevante Ablauf ist **Briefing → Recherche → gemeinsames Ergebnis**. Dies ist eine Produktdemonstration, keine Untersuchung eines Kundeneinsatzes.

<video src="https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512" controls playsinline width="100%" poster="docs/assets/screens/oss-launch-planner-poster.webp">
  <img src="docs/assets/screens/oss-launch-planner-poster.webp" alt="Vstorm OSS Launch Planner: Zielgruppenauswahl, Projektempfehlung und Quellenlinks" width="100%">
</video>

[Das gekürzte Video ansehen (37 Sekunden)](https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512) · [Screenshot ansehen](docs/assets/screens/oss-launch-planner-poster.webp)

## Verbinde die Apps, die dein Team bereits nutzt

<img src="docs/assets/integrations/apps-glass.svg" alt="Sechzehn App-Logos auf dunklen Glaskacheln: Google Drive, Gmail, Outlook, Notion, GitHub, Slack, Telegram, Figma, Linear, Airtable, Dropbox, Mattermost, HubSpot, Stripe, Shopify, Supabase." width="1140">

[Google Drive™ synchronisieren](https://vstorm-co.github.io/agenticos/de/howto/configure-sync-sources/) · [Gmail-Ereignisse](https://vstorm-co.github.io/agenticos/de/triggers/) · [MCP-Werkzeuge: Notion, GitHub, Linear und mehr](https://vstorm-co.github.io/agenticos/de/mcp/) · [Chatkanäle: Slack, Mattermost, Telegram](https://vstorm-co.github.io/agenticos/de/channels/).

[Outlook-E-Mail und -Kalender](https://vstorm-co.github.io/agenticos/de/mcp/) werden über einen externen MCP-Dienst mit eigenem Konto und Berechtigungen angebunden.

Einige Verbindungen nutzen externe MCP-Dienste und erfordern eine separate Einrichtung, Konten und Berechtigungen.

## Passt AgenticOS zu deinem Team?

Wähle es, wenn dein Team wiederkehrende Aufgaben mit Dokumenten oder Werkzeugen hat, Fachleute die Anweisungen pflegen und jemand den Betrieb auf eigener Infrastruktur verantwortet.

Prüfe es anhand einer eigenen Aufgabe. [Ansätze vergleichen](https://vstorm-co.github.io/agenticos/de/about/comparison/) · [Rollout planen](https://vstorm-co.github.io/agenticos/de/rollout/).

## Betrieb, Modelle und Zugriff selbst kontrollieren

**Sovereign bedeutet Kontrolle über Bereitstellung, Modellanbieter, Datenflüsse und Agentenzugriff.** AgenticOS ist Apache-2.0-Software, die du prüfen, ändern und betreiben kannst. Wähle gehostete Anbieter oder lokale Modelle über Ollama und kompatible Endpunkte wie vLLM. [Modelle konfigurieren](https://vstorm-co.github.io/agenticos/de/models/).

Eine selbst gehostete Konsole macht nicht jedes Modell, jeden Parser und jedes Werkzeug lokal. Prüfe die konfigurierten Dienste und welche Daten sie erhalten. Weise Ressourcenberechtigungen zu, speichere Zugangsdaten im verschlüsselten Vault und teste die Freigaberegeln für die aktivierten Werkzeuge.

[Sicherheit und Datenflüsse](https://vstorm-co.github.io/agenticos/de/security/) · [Zugriffskontrolle](https://vstorm-co.github.io/agenticos/de/permissions/) · [Secrets](https://vstorm-co.github.io/agenticos/de/secrets/) · [Ausführungs- und Kostenkontrolle](https://vstorm-co.github.io/agenticos/de/governance/).

## Für Entwickler und Betreiber

Gebaut mit FastAPI, Pydantic AI, PostgreSQL mit pgvector, Redis, Prefect und Next.js. Entwickler ergänzen Capabilities in typisiertem Python; Teams stellen in der Konsole Agenten aus den registrierten Capabilities zusammen.

[Architektur](https://vstorm-co.github.io/agenticos/de/architecture/) · [Capabilities](https://vstorm-co.github.io/agenticos/de/reference/capabilities/) · [API](https://vstorm-co.github.io/agenticos/de/api/) · [Mitwirken](https://vstorm-co.github.io/agenticos/de/help/).

Die [Betriebssystem-Analogie](https://vstorm-co.github.io/agenticos/de/about/) erläutert die Architektur. Die optionale [Desktop-App](https://vstorm-co.github.io/agenticos/de/desktop/) ergänzt ein eigenes Fenster, ein Maskottchen und einen macOS-Kurzbefehl für Screenshots. Unter [Vstorms Open-Source-Projekten](https://github.com/vstorm-co) findest du Bibliotheken und Werkzeuge rund um AgenticOS.

## Lizenz

[Apache License 2.0](LICENSE). Siehe [NOTICE](NOTICE) und die [Hinweise zu Drittkomponenten](THIRD_PARTY_NOTICES.md)
für Namensnennungen und enthaltene Komponenten.

## Brauchst du Hilfe beim produktiven Einsatz von Agenten?

Vstorm stellt AgenticOS in der Infrastruktur von Kunden bereit, schreibt die Dokumentation, definiert die Prozesse
und baut eigene Capabilities. Wartung und Support werden pro Auftrag vereinbart.

Mit Sorgfalt gebaut von [**Vstorm**](https://vstorm.co) · [Vstorm on GitHub](https://github.com/vstorm-co)
