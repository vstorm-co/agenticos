<!-- source_sha: 3bf5cdf03c03 -->

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

AgenticOS ist eine selbst gehostete Arbeitsumgebung, in der KI-Agenten mit Dateien arbeiten, Code ausführen und die Werkzeuge und das Wissen deines Unternehmens nutzen. Erstelle und veröffentliche Agenten im Browser, teile sie mit Kollegen und verwalte Zugriff und Ergebnisse an einem Ort.

<a href="docs/assets/screens/light/agent-builder.png">
  <img src="docs/assets/screens/light/agent-builder.png" alt="Agent Builder mit Anweisungen, Modellauswahl und einer veröffentlichten Version." width="100%">
</a>

## Was du damit machen kannst

| Für dein Team | Was AgenticOS bereitstellt |
|---|---|
| [Dateien und Code](#mit-dateien-und-code-arbeiten) | CSVs analysieren, Diagramme und Dokumente erstellen, an Repositories arbeiten |
| [Wiederverwendbare Agenten](#agenten-für-dein-team-erstellen) | Modelle und Werkzeuge wählen, Versionen veröffentlichen, Agenten mit Kollegen teilen |
| [Unternehmenswissen](#agenten-die-arbeitsweise-deines-teams-vermitteln) | Skills, Kontext und durchsuchbare Dokumente in mehreren Agenten nutzen |
| [Ergebnisse teilen](#ergebnisse-als-interaktive-seiten-veröffentlichen) | Interaktive Seiten mit festen Links und Versionshistorie veröffentlichen |
| [Betrieb und Übersicht](#läufe-kosten-und-freigaben-verfolgen) | Dashboards anpassen, Läufe prüfen, Aufgaben planen und Budgets festlegen |
| [Unternehmenszugriff](#teams-mit-rollen-und-gruppen-organisieren) | Rollen, Abteilungsgruppen und Unternehmensanmeldung kombinieren |

## Schnellstart

Du brauchst Docker Compose und Zugang zu einem Modellanbieter. Unter macOS oder Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

Unter Windows führst du denselben Befehl in WSL2 aus, mit eingeschalteter WSL2-Integration in Docker Desktop.
Der Installer fragt nach Modellanbieter und Schlüssel, deinem Login und dem Namen der Organisation, lädt die
veröffentlichten Images und startet eine Bereitstellung mit einem funktionierenden Agenten.

Öffne **http://localhost:3000** und melde dich mit dem bei der Installation gewählten Login an.

**Dein erster Agent:** Folge der [Anleitung für einen Dokumentassistenten](https://vstorm-co.github.io/agenticos/de/howto/first-document-agent/), lade ein Handbuch hoch, stelle Fragen und prüfe Antworten anhand der zitierten Quellen. Teste anschließend ein aktualisiertes Dokument. Die Dokumentsuche benötigt ein Embedding-Modell. Für andere Aufgaben: [Agent erstellen](https://vstorm-co.github.io/agenticos/de/first-agent/).

<details>
<summary>Installer prüfen oder eine andere Bereitstellung wählen</summary>

Lies den [Installer](scripts/quickstart.sh) vor dem Ausführen. So prüfst du die Voraussetzungen ohne Installation:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- --check
```

Manuelle Einrichtung mit Docker Compose, Versionsauswahl und Fehlerbehebung beschreibt die [Installationsanleitung](https://vstorm-co.github.io/agenticos/de/install/).
Für die Entwicklung am Quellcode siehe [Mitwirken](https://vstorm-co.github.io/agenticos/de/help/).

</details>

## Aufgezeichnetes Integrationsbeispiel

Sieh, wie ein Agent aus einem Notion-Briefing den interaktiven **OSS Launch Planner** erstellt und dafür Vstorms Open-Source-Projekte auf GitHub untersucht: **Briefing → Recherche → gemeinsames Ergebnis**.

<video src="https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512#t=1" controls playsinline width="100%" poster="docs/assets/screens/oss-launch-planner-poster.webp">
  <img src="docs/assets/screens/oss-launch-planner-poster.webp" alt="Vstorm OSS Launch Planner: Zielgruppenauswahl, Projektempfehlung und Quellenlinks" width="100%">
</video>

[Das gekürzte Video ansehen (37 Sekunden)](https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512) · [Screenshot ansehen](docs/assets/screens/oss-launch-planner-poster.webp)

## Erstellen, teilen und betreiben

### Mit Dateien und Code arbeiten

Bitte einen Agenten, eine Tabelle zu analysieren, ein Diagramm oder Dokument zu erstellen oder an einem Repository zu arbeiten. Mit einer konfigurierten Container-Sandbox und aktivierter Befehlsausführung kann er **Dateien lesen und bearbeiten, Shell-Befehle ausführen und Python- oder JavaScript-Code ausführen**. Die mitgelieferte Workbench enthält Werkzeuge für Daten, Diagramme und Dokumente, darunter LibreOffice.

<a href="docs/assets/screens/light/chat.png">
  <img src="docs/assets/screens/light/chat.png" alt="Bestehende Unterhaltung zur Analyse einer Umsatz-CSV mit einem Diagramm nach Region und den Ergebnissen des Agenten." width="100%">
</a>

**Umsatz-CSV → Umsatzdiagramm und Erkenntnisse.** Öffne Werkzeugaufrufe, um die Befehle hinter einer Antwort zu prüfen, und greife über die Dateiansicht auf Eingaben und Ergebnisse zu.

Wenn du [Claude Code](https://code.claude.com/docs/en/overview) oder [Codex](https://developers.openai.com/codex/cli/) nutzt, wird dir die Arbeit mit Dateien und Befehlen vertraut vorkommen. AgenticOS bringt diese Arbeitsweise in eine gemeinsame, selbst gehostete Umgebung mit Unternehmenswissen, wiederverwendbaren Agenten und Zugriffskontrollen für die Organisation. Was ein Agent leisten kann, hängt von seinem Modell, den aktivierten Werkzeugen und seinen Anweisungen ab.

Betreibe Container-Sandboxes auf deiner eigenen Infrastruktur oder konfiguriere ein unterstütztes Remote-Backend. Wähle die Lebensdauer der Arbeitsumgebung und die Ausführungslimits passend zur Aufgabe. [Sandbox-Konfiguration](https://vstorm-co.github.io/agenticos/de/sandbox/).

<details>
<summary>Sandbox-Verbindungen ansehen</summary>

<img src="docs/assets/screens/light/sandboxes.png" alt="Sandbox-Verbindungen mit lokalen Container-Hosts, Zugangsdaten im Tresor und Auswahl der Laufzeitumgebung." width="100%">

</details>

### Agenten für dein Team erstellen

Wähle Modell, Anweisungen und Werkzeuge im Browser. Veröffentliche eine Version für Kollegen; prüfe frühere Versionen und stelle sie bei Bedarf wieder her. Halte spezialisierte Agenten für Recherche, Berichte, Programmierung oder operative Aufgaben in einem Katalog bereit.

<details>
<summary>Agentenkatalog ansehen</summary>

<img src="docs/assets/screens/light/agents.png" alt="Agentenkatalog mit veröffentlichten Agenten, Beschreibungen und Versionsstatus." width="100%">

</details>

Kollegen können einen veröffentlichten Agenten über **Webchat, Slack, Mattermost oder Telegram** nutzen, wenn diese Kanäle eingerichtet sind. Entwickler können ihn über die API aufrufen. [Agent erstellen](https://vstorm-co.github.io/agenticos/de/first-agent/) · [Kanal verbinden](https://vstorm-co.github.io/agenticos/de/channels/).

### Agenten die Arbeitsweise deines Teams vermitteln

- **Skills** enthalten wiederverwendbare Abläufe: Code prüfen, Berichte schreiben oder einen Markt untersuchen. Pflege sie einmal und nutze sie in mehreren Agenten.
- **Kontext** enthält dauerhaftes Wissen wie ein Glossar, Richtlinien oder die Markensprache. Füge ihn dem Prompt hinzu oder lasse den Agenten bei Bedarf darauf zugreifen.
- **Wissensbasen (RAG)** machen hochgeladene Dokumente durchsuchbar. Prüfe Verarbeitungsstatus und Textabschnitte, wähle Parser-Optionen oder konfiguriere Synchronisationsquellen wie Google Drive und S3.

<a href="docs/assets/screens/light/skills.png">
  <img src="docs/assets/screens/light/skills.png" alt="Skills-Bibliothek mit den Filtern Design, Engineering, Finance und Research." width="100%">
</a>

[Skills](https://vstorm-co.github.io/agenticos/de/skills/) · [Kontext](https://vstorm-co.github.io/agenticos/de/context/) · [Dokumentverarbeitung](https://vstorm-co.github.io/agenticos/de/file-processing/) · [Synchronisationsquellen](https://vstorm-co.github.io/agenticos/de/howto/configure-sync-sources/).

<details>
<summary>Geöffnetes Glossar und Wissenssammlung ansehen</summary>

<img src="docs/assets/screens/light/context-detail.png" alt="Glossary in der Vorschau, aktiviert und für den Abruf bei Bedarf konfiguriert." width="100%">

<img src="docs/assets/screens/light/knowledge-collection.png" alt="Die Wissenssammlung vstorm mit einem indexierten Dokument, Parser und Verarbeitungsstatus." width="100%">

</details>

### Ergebnisse als interaktive Seiten veröffentlichen

Agenten können Berichte, interaktive Vergleiche und kleine Dashboards als **Artefakte** veröffentlichen. Wähle, wer sie öffnen darf; Aktualisierungen behalten denselben Link und frühere Versionen bleiben lesbar. Das Beispiel unten ist der OSS Launch Planner, erstellt aus einem Notion-Briefing und einer GitHub-Recherche.

<a href="docs/assets/screens/light/artifact-detail.png">
  <img src="docs/assets/screens/light/artifact-detail.png" alt="OSS Launch Planner als Artefakt mit Zielgruppenauswahl, Projektempfehlungen und Quellenlinks." width="100%">
</a>

[Artefakt teilen](https://vstorm-co.github.io/agenticos/de/artifacts/).

<details>
<summary>Artefaktbibliothek ansehen</summary>

<img src="docs/assets/screens/light/artifacts.png" alt="Artefaktbibliothek mit Seitenvorschauen, Versionen und Sichtbarkeitseinstellungen." width="100%">

</details>

### Läufe, Kosten und Freigaben verfolgen

Passe das **Dashboard** an deine Arbeit an: Ordne Widgets an, ändere ihre Größe, färbe Bereiche ein und speichere Layouts. Verfolge Nutzung, Ergebnisse, erfasste Ausgaben, Freigaben und Sandbox-Kapazität. Berechtigungen bestimmen, welche Daten eine Person sehen darf.

<a href="docs/assets/screens/light/dashboard.png">
  <img src="docs/assets/screens/light/dashboard.png" alt="Angepasstes Dashboard mit Nutzungsübersicht, erfassten Ausgaben, Verlauf der Läufe und Ergebnissen." width="100%">
</a>

In **Activity** kannst du Läufe und Werkzeugaufrufe prüfen, Agentenversionen vergleichen und Datensätze exportieren. Konfiguriere Freigaberichtlinien für unterstützte Werkzeuge und verwende **Routinen**, um Arbeit nach Zeitplan oder Ereignissen zu wiederholen. Manche Kosten hängen von Nutzungs- und Preisdaten der Anbieter ab; externe Dienste können separat abrechnen.

[Laufhistorie, Budgets und Freigaben](https://vstorm-co.github.io/agenticos/de/governance/) · [Routinen](https://vstorm-co.github.io/agenticos/de/triggers/).

<details>
<summary>Activity und Freigabesteuerung ansehen</summary>

<img src="docs/assets/screens/light/activity.png" alt="Activity mit aufgezeichneten Läufen, Status, Modellnutzung und Kosten." width="100%">

Die Freigabeabdeckung hängt vom Werkzeug und Ausführungsmodus ab. Im Webchat erfasst **Ask about everything** auch MCP-Werkzeugaufrufe, die der Runner verarbeitet. [Freigabemodi und Grenzen](https://vstorm-co.github.io/agenticos/de/governance/#how-much-one-conversation-wants-to-be-asked).

</details>

### Teams mit Rollen und Gruppen organisieren

**Rollen bestimmen, was Personen tun dürfen. Gruppen bestimmen, mit wem du teilst.** Nutze Rollen wie Builder, Operator, Member und Viewer und erstelle Abteilungen oder Arbeitsgruppen wie **Operations, Engineering, Finance und Research**. Teile einen Agenten, Skill, eine Sammlung, Kontextdatei oder ein Artefakt mit einer Gruppe in einem Schritt. Gruppenfreigaben ergänzen den Zugriff aus der Rolle und individuellen Freigaben einer Person.

<a href="docs/assets/screens/light/groups.png">
  <img src="docs/assets/screens/light/groups.png" alt="Organisationsgruppen Engineering, Finance, Operations und Research mit Beschreibungen und Mitgliederverwaltung." width="100%">
</a>

Nutze bestehende Unternehmenskonten über **OIDC Single Sign-on, LDAP-Verzeichnisanmeldung oder integrierte Windows-Anmeldung mit Kerberos**, mit entsprechender Konfiguration der Installation. **Directory-Zuordnungen** verbinden externe Verzeichnisgruppen mit einer Organisationsrolle und optional einer AgenticOS-Gruppe; Mitgliedschaften werden bei der Anmeldung abgeglichen.

[Rollen und Ressourcenberechtigungen](https://vstorm-co.github.io/agenticos/de/permissions/) · [Gruppen, LDAP, Kerberos und Verzeichniszuordnungen](https://vstorm-co.github.io/agenticos/de/directory/).

<details>
<summary>Organisationsmitglieder und Rollenmatrix ansehen</summary>

<img src="docs/assets/screens/light/members.png" alt="Organisationsmitglieder mit zugewiesenen Rollen und Mitgliederverwaltung." width="100%">

<img src="docs/assets/screens/light/roles.png" alt="Berechtigungsmatrix zum Vergleich von Owner, Admin, Builder, Operator, Member und Viewer." width="100%">

</details>

## Verbinde die Apps, die dein Team bereits nutzt

<img src="docs/assets/integrations/apps-glass.svg" alt="Sechzehn App-Logos auf dunklen Glaskacheln: Google Drive, Gmail, Outlook, Notion, GitHub, Slack, Telegram, Figma, Linear, Airtable, Dropbox, Mattermost, HubSpot, Stripe, Shopify, Supabase." width="1140">

Verbinde Werkzeuge über **MCP**, neben integrierten Synchronisationsquellen und Chatkanälen. Der Katalog enthält kuratierte Verbindungen und **über 5.700 MCP-Servereinträge** aus einer gespiegelten Registry. Die Einträge sind Metadaten der Herausgeber; jede Verbindung erfordert eigene Einrichtung und Zugriffsprüfung.

[Google Drive™ synchronisieren](https://vstorm-co.github.io/agenticos/de/howto/configure-sync-sources/) · [Gmail-Ereignisse](https://vstorm-co.github.io/agenticos/de/triggers/) · [MCP-Werkzeuge: Notion, GitHub, Linear und mehr](https://vstorm-co.github.io/agenticos/de/mcp/) · [Chatkanäle: Slack, Mattermost, Telegram](https://vstorm-co.github.io/agenticos/de/channels/).

[Outlook-E-Mail und -Kalender](https://vstorm-co.github.io/agenticos/de/mcp/) werden über einen externen MCP-Dienst mit eigenem Konto und Berechtigungen angebunden.

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
