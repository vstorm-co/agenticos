<!-- source_sha: 5a4d6fb78011 -->

<div align="center">

<img src="docs/assets/readme-banner.webp" alt="AgenticOS: Open-Source-KI-Teammates für dein Unternehmen. Agents, als Blobs gezeichnet, arbeiten mit den Capabilities der Toolbox: Wissenssuche, ein Webbrowser, Subagents, eine Sandbox, Diagramme, Apps, Skills und Guardrails." width="100%">

<p>
  <b>Die selbst gehostete Agent-Schicht: KI-Agenten auf deiner eigenen Infrastruktur bauen, betreiben und steuern.</b><br>
  Dein Team und seine Agents in einem Live-Chat, mit Claude Code und Codex zur Hand, einem echten Browser, MCP und einer API, mit Budgets, Freigaben und einem aufgezeichneten Run.<br>
  <sub>Apache-2.0 &middot; gebaut auf Pydantic AI</sub>
</p>

<p>
  <a href="#-agenticos-in-aktion">Ansehen</a> &middot;
  <a href="#-highlights">Highlights</a> &middot;
  <a href="#-was-ist-agenticos">Was ist das?</a> &middot;
  <a href="#-schnellstart">Schnellstart</a> &middot;
  <a href="#-verbinde-die-apps-die-dein-team-bereits-nutzt">Integrationen</a> &middot;
  <a href="#-erstellen-teilen-und-betreiben">Produkttour</a> &middot;
  <a href="#-finde-deinen-weg">Dein Weg</a> &middot;
  <a href="#-was-heute-enthalten-ist">Was enthalten ist</a> &middot;
  <a href="#-häufige-fragen">FAQ</a> &middot;
  <a href="https://vstorm-co.github.io/vstormos-landing/">Website</a> &middot;
  <a href="https://vstorm-co.github.io/agenticos/presentation/">Einführungsfolien</a> &middot;
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

<a href="docs/assets/readme/highlight-hero.webp"><img src="docs/assets/readme/highlight-hero.webp" alt="Dunkler Modus, zwei Personen im Projektchat: Der Chief of Staff schreibt Tom, dass er seine Budgetänderung und Peters Bestätigung in den Launch-Plan übernommen hat, zeigt die neue Aufteilung und listet auf, was das Team noch klären muss." width="100%"></a>

AgenticOS gibt jedem Team KI-Teammates: Agents, die mit Dateien arbeiten, Code ausführen, im Web surfen und die Werkzeuge und das Wissen deines Unternehmens nutzen. Deine Kollegen und deine Agents arbeiten im selben Live-Chat, und jeder Agent kann Code an Claude Code oder Codex übergeben, mit dem ChatGPT- oder Claude-Abo, das du schon bezahlst. Es ist Open Source (Apache-2.0) und selbst gehostet, eine Schicht, die du auf deiner eigenen Infrastruktur betreibst. Baue und veröffentliche Agents im Browser, teile sie mit Kollegen und steuere ihren Zugriff, ihre Kosten und Ergebnisse an einem Ort.

**Neu hier?** Klicke dich durch die [Einführung in 17 Folien](https://vstorm-co.github.io/agenticos/presentation/) (auf Englisch): das Problem, die Idee, das Produkt auf echten Bildschirmen, seine Kontrollen und Grenzen und der Einstieg. Jeden Bildschirm im Detail zeigt die [Produkttour in 47 Folien](https://vstorm-co.github.io/agenticos/presentation/tour/). Die Pfeiltasten blättern in beiden, `O` zeigt alle Folien.

## ⚡ Highlights

### Dein Team und deine Agents in einem Live-Raum

Ein Projekt gibt allen dieselben Dateien, Anweisungen und einen Computer für die Agents. Lade Kollegen ein und arbeitet wie ein Team: Du siehst, wer da ist, verfolgst die Antwort eines Agents live, während sie entsteht, und holst jeden Agent, jedes Werkzeug oder Dokument mit einem `@` dazu.

<a href="docs/assets/readme/highlight-projects.webp"><img src="docs/assets/readme/highlight-projects.webp" alt="Ein Projekt-Chat für den Fall launch: zwei Personen sind im Raum, Jordan Reed bittet den Coder-Agent, die Launch-Seite mit dem Coding Agent zu bauen, und die Schritte von Codex laufen unter der Antwort" width="100%"></a>

### Antworte jedem, und der Agent weiß, wer was gesagt hat

Antworte auf die Nachricht einer Person oder eines Agents, und der Agent übernimmt die Änderung und sagt, von wem sie kam. Jede Nachricht trägt einen Namen, also hat jede Entscheidung eine verantwortliche Person.

<a href="docs/assets/readme/highlight-reply.webp"><img src="docs/assets/readme/highlight-reply.webp" alt="Tom Brooks antwortet auf den Launch-Plan des Chief of Staff mit einer Budgetänderung; der Agent antwortet Tom, übernimmt seine Änderung und Peters Bestätigung, und der Finance Analyst prüft die Zahlen erneut" width="100%"></a>

### Claude Code und Codex in deinem Team

Jeder Agent kann Softwarearbeit an Claude Code oder Codex übergeben. Sie bauen auf dem eigenen Computer des Agents, mit deinem ChatGPT- oder Claude-Abo, und berichten, was sie geändert und geprüft haben und was sie von dir brauchen.

<a href="docs/assets/readme/highlight-coding.webp"><img src="docs/assets/readme/highlight-coding.webp" alt="Die Antwort des Coder-Agents, nachdem Codex die Launch-Seite gebaut hat: verwendete Farben und Überschrift, was weggelassen wurde, bestandene Prüfungen und zwei Entscheidungen für das Team" width="100%"></a>

### Frag, wie es funktioniert, und bekomm eine Zeichnung, die du nutzen kannst

Ein Agent zeichnet, während er schreibt: ein Diagramm aus deinen Dokumenten, einen Rechner mit Schiebereglern, ein Diagramm oder eine 3D-Szene, live unter seiner Nachricht. Ein Klick speichert es als App, die dein Team per Link öffnet.

<a href="docs/assets/readme/highlight-visuals.webp"><img src="docs/assets/readme/highlight-visuals.webp" alt="Ein ROI-Rechner, den der Agent Visuals Lab im Chat gezeichnet hat: Schieberegler für Rechnungen, Minuten pro Rechnung, Stundenkosten und eingesparte Zeit, die gesparten Dollar pro Jahr und ein Balkendiagramm der monatlichen Kosten vorher und nachher" width="100%"></a>

### Schreib einem Agent und geh

Gib eine Recherche in Auftrag, die dauert, und schließ den Tab. Der Agent arbeitet weiter, die Antwort landet in der Unterhaltung, und die Glocke sagt dir, wann er fertig ist.

<a href="docs/assets/readme/highlight-research.webp"><img src="docs/assets/readme/highlight-research.webp" alt="Eine Tabelle des Sales Researcher: was fünf AP-Automatisierungstools ein Unternehmen mit 200 Personen kosten, mit Plan, Preis, Leistungsumfang und Quelllink in jeder Zeile" width="100%"></a>

### Dein Tag auf einem Bildschirm

Die Konsole öffnet mit dem, was deine Agents getan haben, den Entscheidungen, die auf dich warten, und den Unterhaltungen zum Weitermachen - samt einer Tour durch das, was leicht zu übersehen ist.

<a href="docs/assets/readme/highlight-dashboard.webp"><img src="docs/assets/readme/highlight-dashboard.webp" alt="Der Me-Tab des Dashboards: eine Begrüßung, eine Einstiegs-Checkliste, ein Karussell mit isometrischen Illustrationen, Runs, Abschlussquote und Kosten des Zeitraums, wartende Entscheidungen und Unterhaltungen zum Fortsetzen" width="100%"></a>

### Agents, die als Team arbeiten

Ein führender Agent gibt Teile einer Aufgabe an Kollegen weiter und fasst zusammen, was sie gefunden haben - du siehst, wen er gefragt hat und was jeder gesagt hat.

<a href="docs/assets/readme/highlight-subagents.webp"><img src="docs/assets/readme/highlight-subagents.webp" alt="Das Briefing eines Chief-of-Staff-Agenten für eine Preisrunde, geschrieben aus den Antworten von Sales Researcher und Finance Analyst: die Preise von Ramp und Bill.com in Dollar, die Marge, die Finance ohne GuV nicht nennen konnte, und drei Punkte für das Meeting" width="100%"></a>

### Ein echter Browser, direkt im Chat

Sieh zu, wie er sich durch Seiten klickt, übernimm, wenn eine Anmeldung dich braucht, zeig auf eine Stelle, um sie zu kommentieren.

<a href="docs/assets/readme/highlight-browser.webp"><img src="docs/assets/readme/highlight-browser.webp" alt="Der Live-Browser eines Sales Researchers unter seiner Nachricht im Chat, geöffnet auf der Artemis-III-Missionsseite der NASA, darunter die Antwort, die er aus der Seite geschrieben hat" width="100%"></a>

### Bauen, ausstatten und testen in einem Fenster

Schalte Tools über illustrierte Karten ein und gib dem Entwurf im Test-Chat daneben eine echte Aufgabe - hier zeichnet er den Umsatz eines Quartals gegen die Kosten und liest die Marge ab, bevor jemand anderes den Agent sieht.

<a href="docs/assets/readme/highlight-builder-test.webp"><img src="docs/assets/readme/highlight-builder-test.webp" alt="Die Toolbox des Finance Analyst mit isometrischen Capability-Karten und sein Test-Chat, der Umsatz gegen Kosten im dritten Quartal zeichnet" width="100%"></a>

### Apps, nicht nur Antworten

Ein Agent veröffentlicht ein Dashboard oder einen Bericht als Seite mit festem Link und Versionen.

<a href="docs/assets/readme/highlight-app.webp"><img src="docs/assets/readme/highlight-app.webp" alt="Ein ROI-Rechner, den ein Visuals-Lab-Agent im Chat gezeichnet hat, als App mit eigenem Link gespeichert: Regler für Rechnungen, Minuten und Stundensatz, 69.120 $ Ersparnis pro Jahr und die monatlichen Kosten vorher und nachher" width="100%"></a>

### Über 4.700 MCP-Server

Verbinde Notion, GitHub, Jira oder deinen eigenen Server und wähle, welche Werkzeuge jeder Agent nutzen darf.

<a href="docs/assets/readme/highlight-mcp-servers.webp"><img src="docs/assets/readme/highlight-mcp-servers.webp" alt="Die MCP-Server-Galerie mit verbundenen Servern und ihrer Anmeldeart" width="100%"></a>

### In AgenticOS arbeiten, aus Claude Code, Codex oder Cursor

AgenticOS ist ein MCP-Server. Mit einem Befehl hinzufügen und im Browser anmelden: Ihr Coding-Assistent kann Agents auflisten und starten, Runs und ihre Kosten lesen sowie Wissensdatenbanken durchsuchen und befüllen, im Rahmen dessen, was Sie erlaubt haben.

<a href="docs/assets/readme/highlight-mcp-server.webp"><img src="docs/assets/readme/highlight-mcp-server.webp" alt="Die Einstellungen für MCP-Clients: die Server-URL von AgenticOS, Anmeldung über den Browser oder mit einem API-Schlüssel und der Einzeiler, der es zu Claude Code hinzufügt, mit Tabs für Codex, Claude Desktop, Cursor und VS Code" width="100%"></a>

## 📸 AgenticOS in Aktion

<a href="https://github.com/user-attachments/assets/9d2a7923-a52e-4ee6-ab6a-734692824d5a"><img src="docs/assets/screens/agenticos-intro-play.webp" alt="Das agenticos-Logo zwischen den Blob-Figuren der Konsole, mit Abspielknopf: AgenticOS in zwei Minuten" width="100%"></a>

<p align="center"><sub><b>AgenticOS in zwei Minuten.</b> Eine aufgezeichnete Sitzung: Ein Stabschef verteilt Arbeit an andere Agenten, der Architect entwirft einen neuen Agenten zur Freigabe, ein Finanzagent bekommt seine Tools, wird getestet und veröffentlicht ein Dashboard, ein anderer durchsucht GitHub, und einer liest Notion über MCP. Mit synthetischer Stimme vertont. <a href="https://github.com/user-attachments/assets/9d2a7923-a52e-4ee6-ab6a-734692824d5a">Ansehen (2:11)</a></sub></p>


## 💡 Was ist AgenticOS?

**AgenticOS ist eine quelloffene (Apache-2.0), selbst gehostete Schicht, um KI-Agenten im ganzen Unternehmen zu erstellen, zu teilen und zu steuern.** Teams konfigurieren einen Agenten im Browser: Sie schreiben seine Anweisungen, wählen ein Modell und schalten Werkzeuge ein. Sie verbinden ihn mit Unternehmensdokumenten und Apps und veröffentlichen ihn im Webchat, in Slack, Mattermost, Telegram, als Website-Widget oder über eine API. Administratoren steuern, wer einen Agenten nutzen darf, was er ausgeben darf und welche Aktionen die Freigabe einer Person brauchen. Jeder Run wird aufgezeichnet.

Die meisten Agent-Frameworks liefern eine Bibliothek, also wird jede Änderung am Verhalten eines Agenten zu Pull Request, Review und Release. Das passt nicht zu den kleinen Agenten, die ein Unternehmen tatsächlich will, denn wer weiß, was der Agent sagen soll, hat meist keinen Commit-Zugriff. **Code definiert, Konfiguration setzt zusammen:** Entwickler erweitern den Baukasten, und Konfiguration erreicht immer nur das, was Code registriert hat.

Es läuft mit Docker Compose auf deiner eigenen Infrastruktur und arbeitet mit 28 Modellanbietern, darunter dein ChatGPT-Abo und lokale Modelle über Ollama und vLLM. Die Agenten laufen auf [Pydantic AI](https://ai.pydantic.dev) und [pydantic-ai-harness](https://github.com/pydantic/pydantic-ai-harness); die Schicht drumherum nutzt FastAPI, PostgreSQL mit pgvector und Next.js. Gepflegt wird es von [Vstorm](https://vstorm.co).

**Für wen es gedacht ist:**

- Unternehmen, die **eine interne Schicht für KI-Agenten** besitzen wollen statt Assistenten pro Arbeitsplatz in der Cloud eines Anbieters.
- Teams mit **wiederkehrender Arbeit über Dokumenten und Werkzeugen**, etwa Berichten, Support-Antworten, Vertragsprüfungen und Datenanalysen.
- IT- und Sicherheitsteams, die für KI-Agenten **Datensouveränität, Unternehmensanmeldung, Budgets, Freigaben und einen Audit-Trail** brauchen.
- Entwickler, die **typisierte Erweiterungspunkte in Python** wollen und eine Konsole, die ihre nicht technischen Kollegen bedienen können.

<a href="docs/assets/readme/company-architecture-diagram.webp"><img src="docs/assets/readme/company-architecture-diagram.webp" alt="AgenticOS in deinem Unternehmen: links Abteilungen und Systeme; in der Mitte AgenticOS mit Beispielagenten und den Kontrollen, die jede Anfrage durchläuft; innen deine Daten, Sandboxes, der Vault und optionale lokale Modelle; außen gehostete Modelle, SaaS-Werkzeuge und Dokumentquellen, nur wenn du sie wählst." width="100%"></a>

<p align="center"><sub><b>Wie es sich in dein Unternehmen einfügt.</b> Illustrierte Personen; die Agenten sind Beispiele.</sub></p>

**Wie sich AgenticOS in ein Unternehmen einfügt:** Abteilungen wie Finanzen, Betrieb oder Vorstand nutzen gemeinsame Agenten im Webchat, in Slack oder in einem privaten Workspace. Deine Systeme rufen Agenten über die API auf, und Ereignisse oder Zeitpläne starten sie automatisch. Jede Anfrage durchläuft dieselben Kontrollen: Rollen, Budgets, Freigaben, Guardrails und einen aufgezeichneten Run. Deine Daten, Vektoren, Code-Sandboxes, der Vault für Zugangsdaten und optionale lokale Modelle bleiben auf deiner Infrastruktur. Gehostete Modelle, SaaS-Werkzeuge und externe Dokumentquellen werden nur genutzt, wenn du sie konfigurierst.

<img src="docs/assets/readme/figures.webp" alt="29 integrierte Capabilities, pro Agent einschaltbar; 8 Orte, an denen ein Agent antwortet; 28 Modellanbieter, gehostet, in deiner Cloud oder lokal; 5 Quellen für die Dokumentsynchronisation; über 4.700 MCP-Server in der Galerie; 29 Tutorials, jedes mit einer Prüfung, die du ausführen kannst." width="100%">

<p align="center"><sub><b>Auf einen Blick:</b> 29 integrierte Capabilities · 8 Orte, an denen ein Agent antwortet · 28 Modellanbieter · 5 Synchronisationsquellen für Dokumente · über 4.700 MCP-Server · 29 Tutorials.</sub></p>

## ✨ Was du damit machen kannst

| Für dein Team | Was AgenticOS bereitstellt |
|---|---|
| [Dateien und Code](#-mit-dateien-und-code-arbeiten) | CSVs analysieren, Diagramme und Dokumente erstellen, an Repositories arbeiten |
| [Wiederverwendbare Agenten](#-agenten-für-dein-team-erstellen) | Modelle und Werkzeuge wählen, Versionen veröffentlichen, Agenten mit Kollegen teilen |
| [Unternehmenswissen](#-agenten-die-arbeitsweise-deines-teams-vermitteln) | Skills, Kontext und durchsuchbare Dokumente in mehreren Agenten nutzen |
| [Ergebnisse teilen](#-ergebnisse-als-interaktive-seiten-veröffentlichen) | Interaktive Seiten mit festen Links und Versionshistorie veröffentlichen |
| [Betrieb und Übersicht](#-runs-kosten-und-freigaben-verfolgen) | Dashboards anpassen, Runs prüfen, Aufgaben planen und Budgets festlegen |
| [Unternehmenszugriff](#-teams-mit-rollen-und-gruppen-organisieren) | Rollen, Abteilungsgruppen und Unternehmensanmeldung kombinieren |

## 🚀 Schnellstart

Du brauchst Docker Compose und Zugang zu einem Modellanbieter. Unter macOS oder Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

Unter Windows führst du denselben Befehl in WSL2 aus, mit eingeschalteter WSL2-Integration in Docker Desktop. Der Installer fragt nach Modellanbieter und Schlüssel, deinem Login und dem Namen der Organisation, lädt die veröffentlichten Images und startet eine Bereitstellung mit einem funktionierenden Agenten. Ein Host mit 4 vCPU und 8 GB RAM reicht dafür. Öffne dann **http://localhost:3000** und melde dich mit dem bei der Installation gewählten Login an.

**Dein erster Agent:** Folge der [Anleitung für einen Dokumentassistenten](https://vstorm-co.github.io/agenticos/de/howto/first-document-agent/), lade ein Handbuch hoch, stelle Fragen und prüfe die Antworten anhand der zitierten Quellen. Wähle danach eine nächste Aufgabe aus [29 Tutorials](https://vstorm-co.github.io/agenticos/de/use-cases/), jedes mit Beispieleingabe und einer Prüfung, die du ausführen kannst.

<details>
<summary>Installer prüfen oder eine andere Bereitstellung wählen</summary>

Lies den [Installer](scripts/quickstart.sh) vor dem Ausführen. So prüfst du die Voraussetzungen ohne Installation:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- --check
```

Manuelle Einrichtung mit Docker Compose, festgelegte Versionen und Fehlerbehebung beschreibt die [Installationsanleitung](https://vstorm-co.github.io/agenticos/de/install/). Für die Entwicklung am Quellcode siehe [Mitwirken](https://vstorm-co.github.io/agenticos/de/help/).

</details>

## 🔌 Verbinde die Apps, die dein Team bereits nutzt

AgenticOS verbindet Agenten mit den Modellen, Chatwerkzeugen, Geschäftsanwendungen und Dokumentablagen, die ein Unternehmen schon nutzt. So kann ein Agent ein Notion-Briefing lesen, SharePoint-Dokumente durchsuchen oder in Slack antworten, unter denselben Zugriffsregeln und demselben Budget.

<a href="docs/assets/readme/integrations-hub.webp"><img src="docs/assets/readme/integrations-hub.webp" alt="AgenticOS als Drehscheibe: oben die Modelle, mit denen es denkt; links, wo Menschen es erreichen und was es startet; rechts die Werkzeuge, die es über MCP nutzen kann; unten die Dokumente, die es liest." width="100%"></a>

| Verbinden | Wie | Mehr dazu |
|---|---|---|
| **Chatwerkzeuge** | Veröffentliche einen Agenten in Slack, Mattermost oder Telegram, als Website-Widget, gehostete Seite, über die API oder einen WebSocket | [Kanäle](https://vstorm-co.github.io/agenticos/de/channels/) |
| **Geschäftswerkzeuge** | **über 4.700 MCP-Server** in der Galerie (Notion, GitHub, Jira, HubSpot, Stripe…) und eigene Server; wähle, welche Werkzeuge jeder Agent aufrufen darf | [MCP](https://vstorm-co.github.io/agenticos/de/mcp/) |
| **Dokumente** | Synchronisiere Google Drive, S3/MinIO, Git-Repositories, Websites, SharePoint und OneDrive in Wissensbasen | [Synchronisationsquellen](https://vstorm-co.github.io/agenticos/de/howto/configure-sync-sources/) |
| **Ereignisse** | Starte Agenten nach Zeitplan, bei einem neuen GitHub-Issue, einer Gmail-Nachricht oder einem signierten Webhook | [Routinen](https://vstorm-co.github.io/agenticos/de/triggers/) |
| **Modelle** | 28 Anbieter, dein ChatGPT-Abo, dein Cloud-Vertrag (Azure, Bedrock, Vertex) oder lokale Modelle (Ollama, vLLM) | [Modelle](https://vstorm-co.github.io/agenticos/de/models/) |

<sub>Registry-Einträge sind Metadaten der Herausgeber; jede Verbindung erfordert eigene Einrichtung und Zugriffsprüfung. Outlook-E-Mail und -Kalender werden über einen externen MCP-Dienst angebunden. Die Logos kennzeichnen Verbindungsmöglichkeiten und bedeuten keine Partnerschaft.</sub>

## 🧩 Erstellen, teilen und betreiben

### 🤖 Agenten für dein Team erstellen

Wähle Modell, Anweisungen und Werkzeuge eines Agenten im Browser. Veröffentliche eine Version für Kollegen; prüfe frühere Versionen und stelle sie bei Bedarf wieder her. Halte spezialisierte Agenten für Recherche, Berichte, Programmierung oder operative Aufgaben in einem Katalog bereit.

<img src="docs/assets/readme/builder-annotated.webp" alt="Der Agent Builder mit vier nummerierten Bereichen: Name und Status, Tabs, Anweisungen und Modell." width="100%">

Der Agent Builder hat vier Bereiche: **(1)** Name und Veröffentlichungsstatus, wobei ein Entwurf privat bleibt, bis du eine Version veröffentlichst; **(2)** Tabs für Toolbox, MCP-Server, Limits, Verfügbarkeit und Versionshistorie; **(3)** die Anweisungen, in einfacher Sprache geschrieben wie ein Briefing für einen neuen Kollegen; und **(4)** das Modell, pro Agent aus deinen konfigurierten Anbietern gewählt.

Kollegen können einen veröffentlichten Agenten im **Webchat, in Slack, Mattermost oder Telegram** nutzen, wenn diese Kanäle eingerichtet sind, als **Website-Widget** oder **gehostete Seite** oder über die **API** und den **WebSocket**. [Agent erstellen](https://vstorm-co.github.io/agenticos/de/first-agent/) · [Kanal verbinden](https://vstorm-co.github.io/agenticos/de/channels/)

### 📂 Mit Dateien und Code arbeiten

Bitte einen Agenten, eine Tabelle zu analysieren, ein Diagramm zu erstellen, ein Dokument vorzubereiten oder an einem Repository zu arbeiten. Mit einer konfigurierten Container-Sandbox und aktivierter Befehlsausführung kann er **Dateien lesen und bearbeiten, Shell-Befehle ausführen und Python- oder JavaScript-Code ausführen**. Die mitgelieferte Workbench enthält Werkzeuge für Daten, Diagramme und Dokumente, darunter LibreOffice.

Wenn du [Claude Code](https://code.claude.com/docs/en/overview) oder [Codex](https://developers.openai.com/codex/cli/) nutzt, wird dir die Arbeit mit Dateien und Befehlen vertraut vorkommen. AgenticOS bringt diese Arbeitsweise in eine gemeinsame, selbst gehostete Schicht mit Unternehmenswissen, wiederverwendbaren Agenten und Zugriffskontrollen für die Organisation. Was ein Agent leisten kann, hängt von seinem Modell, den aktivierten Werkzeugen und seinen Anweisungen ab. [Sandbox-Konfiguration](https://vstorm-co.github.io/agenticos/de/sandbox/)

### 🧠 Agenten die Arbeitsweise deines Teams vermitteln

- **Skills** enthalten wiederverwendbare Abläufe: Code prüfen, einen Bericht schreiben oder einen Markt untersuchen. Pflege sie einmal und nutze sie in mehreren Agenten.
- **Kontext** enthält dauerhaftes Wissen wie ein Glossar, Richtlinien oder die Markensprache. Füge ihn dem Prompt hinzu oder lass den Agenten bei Bedarf darauf zugreifen.
- **Wissensbasen (RAG)** machen hochgeladene Dokumente durchsuchbar. Wähle Parser-Optionen, prüfe Verarbeitungsstatus und Textabschnitte oder synchronisiere sie aus einer der unten genannten Quellen.

<img src="docs/assets/readme/rag-pipeline.webp" alt="Von der Datei zur zitierten Antwort: Quellen, lesen, aufteilen, einbetten, antworten." width="100%">

**So funktioniert Retrieval-Augmented Generation (RAG) in AgenticOS:** Dokumente werden hochgeladen oder aus Google Drive, S3/MinIO, Git, Websites, SharePoint oder OneDrive synchronisiert. Ein Parser liest sie: PyMuPDF und LiteParse laufen lokal, mit OCR für Scans, LlamaParse ist ein Cloud-Dienst. Danach werden die Dokumente in Abschnitte aufgeteilt, mit einem Modell von OpenAI, OpenRouter oder einem lokalen Ollama-Modell eingebettet und in PostgreSQL mit pgvector gespeichert. Bei einer Frage durchsucht der Agent die Vektoren mit Filtern und antwortet mit Quellenangaben.

[Skills](https://vstorm-co.github.io/agenticos/de/skills/) · [Kontext](https://vstorm-co.github.io/agenticos/de/context/) · [Dokumentverarbeitung](https://vstorm-co.github.io/agenticos/de/file-processing/) · [Synchronisationsquellen](https://vstorm-co.github.io/agenticos/de/howto/configure-sync-sources/)

### 🎨 Ergebnisse als interaktive Seiten veröffentlichen

Agenten können Berichte, interaktive Vergleiche und kleine Dashboards als **Apps** veröffentlichen. Wähle, wer sie öffnen darf; Aktualisierungen behalten denselben Link und frühere Versionen bleiben lesbar. Öffentliche Links können ablaufen, ein Passwort verlangen oder einschränken, welche Websites sie einbetten dürfen. [App teilen](https://vstorm-co.github.io/agenticos/de/artifacts/)

### 📊 Runs, Kosten und Freigaben verfolgen

<img src="docs/assets/readme/dashboard-annotated.webp" alt="Das Dashboard mit sechs nummerierten Abschnitten: Zeitraum, auf einen Blick, Runs im Zeitverlauf, Ergebnisse, offene Entscheidungen und letzte Fehler." width="100%">

Das Dashboard beantwortet für einen gewählten Zeitraum sechs Fragen: wie viele Runs es gab, wie viele abgeschlossen wurden, was sie gekostet haben und wie viele Personen Agenten genutzt haben; wie sich die Runs im Zeitverlauf verändert haben; was fehlgeschlagen ist, auf eine Freigabe gewartet hat oder von einem Budget gestoppt wurde; woher die Runs kamen; und welche Agenten tatsächlich genutzt werden.

Passe das **Dashboard** an deine Arbeit an. In **Activity** prüfst du Runs und Werkzeugaufrufe, vergleichst Agentenversionen und exportierst Datensätze. **Budgets** pro Agent und Organisation werden vor jeder Modellanfrage geprüft. **Freigaberichtlinien** lassen sensible Werkzeuge auf eine Person warten, und **Routinen** wiederholen Arbeit nach Zeitplan oder bei Ereignissen wie einem neuen GitHub-Issue, einer Gmail-Nachricht oder einem signierten Webhook. [Run-Historie, Budgets und Freigaben](https://vstorm-co.github.io/agenticos/de/governance/) · [Routinen](https://vstorm-co.github.io/agenticos/de/triggers/)

### 👥 Teams mit Rollen und Gruppen organisieren

**Rollen bestimmen, was Personen tun dürfen. Gruppen bestimmen, mit wem du teilst.** Nutze Rollen wie Builder, Operator, Member und Viewer und erstelle Abteilungen oder Arbeitsgruppen wie Operations, Engineering, Finance und Research. Teile einen Agenten, einen Skill, eine Sammlung, eine Kontextdatei oder eine App in einem Schritt mit einer Gruppe, oder beschränke es schon beim Anlegen auf ausgewählte Abteilungen. [Abteilungen und Gruppen](https://vstorm-co.github.io/agenticos/de/departments/)

Nutze bestehende Unternehmenskonten über **OIDC Single Sign-on** (Entra ID, Okta, Keycloak und andere), **LDAP-Verzeichnisanmeldung** oder **integrierte Windows-Anmeldung mit Kerberos**. **Directory-Zuordnungen** verbinden Verzeichnisgruppen bei der Anmeldung mit einer Rolle und einer Gruppe. [Rollen und Berechtigungen](https://vstorm-co.github.io/agenticos/de/permissions/) · [Verzeichnisanmeldung](https://vstorm-co.github.io/agenticos/de/directory/)

## 🧭 Finde deinen Weg

Du baust darauf auf? Weiter zu [Für Entwickler und Betreiber](#-für-entwickler-und-betreiber).

<details>
<summary><b>Du entscheidest über die Einführung</b>: welches Problem es löst, was es braucht, wie man anfängt</summary>

<br>

| Die Frage, die deine Teams heute nicht beantworten können | Wie AgenticOS sie beantwortet |
|---|---|
| Wer darf welche Daten nutzen? | Rollen, Abteilungsgruppen und Freigabe pro Ressource, mit Unternehmensanmeldung |
| Was kostet es? | Monatliche Budgets pro Agent und Organisation, vor jeder Modellanfrage geprüft |
| Wer hat diese Aktion freigegeben? | Sensible Werkzeuge warten auf eine Person; jede Entscheidung wird aufgezeichnet |
| Wohin gehen unsere Daten? | Du betreibst AgenticOS und wählst jedes Modell, jeden Parser und jedes Werkzeug, das es erreichen darf |

**Was es braucht:** einen Host (4 vCPU, 8 GB RAM), jemanden, der die Bereitstellung betreibt, und Fachleute, die Anweisungen und Dokumente pflegen. Kosten entstehen durch Modellnutzung, Infrastruktur, externe Dienste und die Zeit der Beteiligten; die Software steht unter Apache-2.0, kommerzielle Nutzung eingeschlossen.

**Wie man anfängt:** Wähle eine wiederkehrende Aufgabe und die Person, die die Antworten beurteilt, richte sie mit dem Modell und den Zugriffsregeln deiner Wahl ein und prüfe sie anhand vorher vereinbarter Kriterien. [Rollout planen](https://vstorm-co.github.io/agenticos/de/rollout/) · [Ansätze vergleichen](https://vstorm-co.github.io/agenticos/de/about/comparison/)

</details>

<details>
<summary><b>Du prüfst die Sicherheit</b>: Datenflüsse, Identität, Kontrollen, was bei deiner IT bleibt</summary>

<br>

<img src="docs/assets/readme/security-layers.webp" alt="Sechs Sicherheitsschichten: Vault, Sandboxes, Apps, Audit-Log, Sitzungen und Datenverkehr, Datenhygiene." width="100%">

Sicherheit ist geschichtet. Zugangsdaten liegen in einem Vault mit Envelope-Verschlüsselung. Code läuft in isolierten Sandboxes. Veröffentlichte Seiten laufen in einer Sandbox. Jede Organisation hat ein hashverkettetes Audit-Log. Sitzungen sind kurzlebig und widerrufbar, und es gelten Rate Limits. Logs werden geschwärzt, und Daten werden nach einem Aufbewahrungsplan gelöscht.

| Ausgehendes Ziel | Genutzt, wenn | Lokale Alternative |
|---|---|---|
| Modellanbieter | Bei jedem Run eines Agenten | Ollama, vLLM oder LM Studio auf deiner Hardware |
| Embedding-Anbieter | Beim Indexieren und Durchsuchen von Dokumenten | Lokale Embedding-Modelle über Ollama |
| LlamaParse | Sammlungen, die diesen Parser nutzen | PyMuPDF oder LiteParse, beide lokal |
| Websuche | Agenten mit aktivierter Websuche | Die Capability abschalten |
| MCP-Server, Chatkanäle | Nur die, die du verbindest | Selbst gehostete Server, Webchat |
| Logfire-Tracing | Nur wenn ein Token konfiguriert ist | Integrierte Run-Historie |

- **Vault:** ein Datenschlüssel pro Secret, verpackt pro Organisation und Schlüsselversion; Master-Schlüssel rotieren; Werte werden nie wieder angezeigt.
- **Sandboxes:** Die API hält keinen Docker-Socket; Container bekommen nur bei Bedarf Netzwerk, mit Limits für CPU, Prozesse und Zeit; gVisor optional.
- **Audit-Log:** hashverkettet pro Organisation, überprüfbar und exportierbar.
- **HIPAA-Profil:** [`deploy/profiles/hipaa/`](deploy/profiles/hipaa/) und `agenticos cmd doctor --profile hipaa` prüfen eine laufende Bereitstellung gegen die technischen Schutzmaßnahmen nach §164.312. Das ist eine Konfigurationsprüfung, keine Zertifizierung. [Was es nicht behauptet](https://vstorm-co.github.io/agenticos/de/security/#the-hipaa-profile-and-what-it-does-not-claim)
- **Bleibt bei deiner IT:** Festplattenverschlüsselung im Ruhezustand, Egress-Firewall, MFA über deinen Identitätsanbieter (keine native MFA, kein SAML oder SCIM) und Backups, die den Vault-Schlüssel einschließen.

[Sicherheit und Datenflüsse](https://vstorm-co.github.io/agenticos/de/security/) · [Datenschutz](https://vstorm-co.github.io/agenticos/de/data-protection/) · [Secrets](https://vstorm-co.github.io/agenticos/de/secrets/) · [SECURITY.de.md](SECURITY.de.md)

</details>

<details>
<summary><b>Du suchst eine erste Aufgabe</b>: 29 Tutorials, jedes mit einer Prüfung, die du ausführen kannst</summary>

<br>

<img src="docs/assets/readme/first-tasks.webp" alt="29 Tutorials, gruppiert nach Dokumenten, Support, Recherche und Analyse, Automatisierung, Inhalte und Produktivität, Engineering und Sicherheit." width="100%">

[Alle Tutorials](https://vstorm-co.github.io/agenticos/de/use-cases/). Für 24 davon gibt es einen Referenz-Run der Maintainer; sie sind Ausgangspunkte, keine Kundenergebnisse.

</details>

## 📦 Was heute enthalten ist

<img src="docs/assets/readme/capabilities.webp" alt="29 integrierte Capabilities in sechs Gruppen: Wissen und Gedächtnis, Web, Dateien, Code und Ausgabe, Arbeitsweise, Sicherheit und Limits, Chatkanäle." width="100%">

<details>
<summary>Alle 31 integrierten Capabilities als Text</summary>

- **Wissen und Gedächtnis:** Wissenssuche mit Quellenangaben, Skills, Kontext, Memory, Memory über mem0, frühere Unterhaltungen.
- **Web:** Websuche (standardmäßig DuckDuckGo; Tavily, Brave oder Exa mit Schlüssel), Webseiten lesen und ein Webbrowser, den der Agent steuert und den du übernehmen kannst.
- **Dateien, Code und Ausgabe:** Berechnungen in Python, eine Sandbox mit Dateien und Shell, ein Coding Agent, der Arbeit an Claude Code oder Codex übergibt, Diagramme, Zeichnungen (Diagramme, Rechner, 3D-Szenen), Bilderzeugung (OpenAI oder Google), Sprache (OpenAI, ElevenLabs oder Google), Videoclips (Google, BytePlus, xAI oder Alibaba), Apps.
- **Arbeitsweise:** Subagents, Planung, Denken, Arbeiten während Werkzeuge laufen, Werkzeugsuche, Datum und Uhrzeit, Erinnerungen an Anweisungen, Rückfragen an den Nutzer.
- **Sicherheit und Limits:** Guardrails, die Secrets und personenbezogene Daten schwärzen, lange Unterhaltungen, Auslagerung von Medien, Limits für Werkzeugausgaben.
- **Chatkanäle:** Suche nach Chatkanälen für Bots in Slack, Telegram und Mattermost.

Dazu jedes Werkzeug eines verbundenen MCP-Servers und Capabilities, die deine Entwickler in typisiertem Python ergänzen. [Capability-Referenz](https://vstorm-co.github.io/agenticos/de/reference/capabilities/)

</details>

<details>
<summary>Wo Agenten antworten und welche Modelle sie nutzen</summary>

<img src="docs/assets/readme/eight-surfaces.webp" alt="Acht Orte, an denen ein Agent antworten kann." width="100%">
<img src="docs/assets/readme/model-providers.webp" alt="28 Modellanbieter: gehostet, über deinen Cloud-Vertrag oder auf deiner Hardware." width="100%">

**Wo Agenten antworten:** Webchat, ein Website-Widget, eine gehostete Seite, die HTTP-API, ein streamender WebSocket, Slack, Mattermost und Telegram.

**Modellanbieter:**
- **Gehostet (22):** OpenAI, Anthropic, Google Gemini, OpenRouter, Mistral, DeepSeek, xAI, Cohere, Groq, Cerebras, Together, Fireworks, Hugging Face, GitHub Models, Alibaba, Moonshot, Z.AI, Nebius, OVHcloud, SambaNova, Heroku und Vercel AI Gateway.
- **Dein Abo:** ChatGPT über Codex, nach einer Anmeldung.
- **Über deinen Cloud-Vertrag:** Azure OpenAI, AWS Bedrock und Google Vertex AI.
- **Selbst gehostet:** Ollama und LiteLLM, dazu vLLM und LM Studio über einen OpenAI-kompatiblen Endpunkt.

</details>

## 🆚 Im Vergleich

| | Wo es läuft | Quellcode | Modelle |
|---|---|---|---|
| **AgenticOS** | **Deine Infrastruktur** | **Apache-2.0** | **28 Anbieter, auch lokale und dein ChatGPT-Abo** |
| OpenAI dots | OpenAIs Cloud | Proprietär | Nur OpenAI |
| Grok Bot | xAIs Cloud | Proprietär | Nur Grok |
| Viktor | Viktors Cloud | Proprietär | OpenAI, Anthropic, Google, Kimi |
| n8n | Selbst gehostet oder n8n Cloud | Sustainable Use License | Viele, auch Ollama |

KI-Teammates kommen in die Cloud jedes Anbieters. AgenticOS ist der, den du selbst betreibst, auf jedem Modell, mit offenem Quellcode. [Alle Vergleiche im Detail](https://vstorm-co.github.io/agenticos/de/about/comparison/).

## 🎯 Passt AgenticOS zu deinem Team?

Wähle es, wenn ein Team wiederkehrende Arbeit mit Dokumenten oder Werkzeugen hat, Fachleute die Anweisungen pflegen können und jemand den Betrieb einer selbst gehosteten Bereitstellung verantwortet. Wisse, wo es heute endet:

<img src="docs/assets/readme/limits.webp" alt="Acht Grenzen mit Alternativen: Berechtigungen der Quellsysteme, Microsoft-365-Trigger, visueller Workflow-Builder, MFA/SAML/SCIM, Werkzeuge für Suchqualität, horizontale Skalierung, Budgets unter Last, Ergebnisse." width="100%">

## 🔐 Betrieb, Modelle und Zugriff selbst kontrollieren

**Sovereign bedeutet Kontrolle über Bereitstellung, Modellanbieter, Datenflüsse und Agentenzugriff.** AgenticOS ist Apache-2.0-Software, die du prüfen, ändern und betreiben kannst.

<img src="docs/assets/readme/sovereignty.webp" alt="Zwei Bereitstellungsoptionen: AgenticOS selbst gehostet mit gehosteten Modellen unter deinem eigenen Vertrag oder vollständig lokal mit offenen Modellen über Ollama oder vLLM." width="100%">

Es gibt zwei übliche Varianten. **Selbst gehostet, mit gehosteten Modellen:** AgenticOS, Dokumente, Vektoren und Logs laufen auf deinen Servern, die Modelle kommen von einem Anbieter unter deinem eigenen Vertrag und mit deinen Schlüsseln. **Vollständig lokal:** dieselbe Schicht mit offenen Modellen über Ollama oder vLLM auf deiner Hardware, dazu lokale Parser und Werkzeuge. Eine selbst gehostete Konsole macht nicht jedes Modell, jeden Parser und jedes Werkzeug lokal, also prüfe jedes Ziel, das du konfigurierst. [Modelle konfigurieren](https://vstorm-co.github.io/agenticos/de/models/) · [Sicherheit und Datenflüsse](https://vstorm-co.github.io/agenticos/de/security/)

## 🛠️ Für Entwickler und Betreiber

AgenticOS ist gebaut mit FastAPI, Pydantic AI, PostgreSQL mit pgvector, Redis und Next.js. Entwickler ergänzen Capabilities, Sync-Konnektoren und Einträge im MCP-Katalog in typisiertem Python; Teams stellen in der Konsole Agenten aus den registrierten Capabilities zusammen.

| Schicht | Was dort läuft |
|---|---|
| Konsole | Next.js |
| API | FastAPI |
| Agent-Laufzeit | [Pydantic AI](https://ai.pydantic.dev) und [pydantic-ai-harness](https://github.com/pydantic/pydantic-ai-harness), ein Runner hinter jeder Oberfläche |
| Hintergrundarbeit | Eine Job-Queue in PostgreSQL, bedient von `python -m app.worker` |
| Daten | PostgreSQL mit pgvector |
| Codeausführung | Container, gestartet von `sandboxd` |

Rufe einen veröffentlichten Agenten als angemeldetes Mitglied mit `POST /api/v1/agents/{id}/run` auf oder streame Tokens über den WebSocket.

[Architektur](https://vstorm-co.github.io/agenticos/de/architecture/) · [API](https://vstorm-co.github.io/agenticos/de/api/) · [Capability hinzufügen](https://vstorm-co.github.io/agenticos/de/howto/add-capability/) · [Capability-Referenz](https://vstorm-co.github.io/agenticos/de/reference/capabilities/) · [Mitwirken](https://vstorm-co.github.io/agenticos/de/help/)

Die [Betriebssystem-Analogie](https://vstorm-co.github.io/agenticos/de/about/) erläutert die Architektur. Die optionale [Desktop-App](https://vstorm-co.github.io/agenticos/de/desktop/) ergänzt ein eigenes Fenster, ein Maskottchen und einen macOS-Kurzbefehl für Screenshots.

## ❓ Häufige Fragen

<details>
<summary><b>Ist AgenticOS für kommerzielle Nutzung kostenlos?</b></summary>

Ja. AgenticOS steht unter der Apache-2.0-Lizenz, die kommerzielle Nutzung, Änderungen und private Bereitstellung erlaubt. Du zahlst für die Infrastruktur, auf der du es betreibst, und für die Modellanbieter und externen Dienste, die du wählst. Name und Logo von AgenticOS fallen nicht unter die Lizenz.

</details>

<details>
<summary><b>Kann AgenticOS nur mit lokalen Modellen laufen?</b></summary>

Ja. Konfiguriere Ollama, LiteLLM oder einen OpenAI-kompatiblen Server wie vLLM oder LM Studio als Modellanbieter, nutze lokale Embedding-Modelle über Ollama und verarbeite Dokumente mit PyMuPDF oder LiteParse. Eine selbst gehostete Konsole allein macht nicht jedes Modell, jeden Parser und jedes Werkzeug lokal: Prüfe jedes Ziel, das du konfigurierst. [Modelle](https://vstorm-co.github.io/agenticos/de/models/) · [Datenflüsse](https://vstorm-co.github.io/agenticos/de/security/)

</details>

<details>
<summary><b>Welche Anmeldeverfahren und Rollen unterstützt es?</b></summary>

E-Mail und Passwort mit Magic Links, Google, generisches OIDC Single Sign-on (Entra ID, Okta, Keycloak, Auth0, Authentik, Google Workspace), LDAP und Kerberos. Sechs integrierte Rollen (Owner, Admin, Builder, Operator, Member, Viewer) lassen sich mit Abteilungsgruppen und Freigaben pro Ressource kombinieren. Multi-Faktor-Authentifizierung kommt von deinem Identitätsanbieter; native MFA, SAML oder SCIM gibt es noch nicht. [Berechtigungen](https://vstorm-co.github.io/agenticos/de/permissions/)

</details>

<details>
<summary><b>Wie hält AgenticOS Agenten unter Kontrolle?</b></summary>

Monatliche Budgets pro Agent und pro Organisation werden vor jeder Modellanfrage geprüft. Sensible Werkzeuge warten auf die Freigabe einer Person. Optionale Guardrails schwärzen Secrets und personenbezogene Daten, und jeder Run wird mit Agentenversion, Werkzeugen, Tokens und Kosten aufgezeichnet. [Governance](https://vstorm-co.github.io/agenticos/de/governance/)

</details>

<details>
<summary><b>Worin unterscheidet es sich von ChatGPT Enterprise, Copilot Studio oder n8n?</b></summary>

AgenticOS läuft auf deiner Infrastruktur mit jedem von 28 Modellanbietern und hat keine eigenen Gebühren pro Arbeitsplatz oder Credits. Es baut Agenten für die Organisation, veröffentlicht in Chats, auf Websites und über APIs, statt Assistenten-Lizenzen für einzelne Mitarbeitende. Anders als n8n beginnt es beim Agenten statt bei einer Workflow-Oberfläche, und viele Teams nutzen beides. Die Leitfäden behandeln auch den selbst gehosteten Builder [Dify](https://vstorm-co.github.io/agenticos/de/about/dify/) und Coding-Agenten wie Claude Code. [Vergleiche](https://vstorm-co.github.io/agenticos/de/about/comparison/)

</details>

<details>
<summary><b>Was braucht es für den Betrieb?</b></summary>

Docker Compose auf einem Host. Eine Maschine mit 4 vCPU und 8 GB RAM reicht, und zwei API-Worker passen für ein Team von zehn Personen. Jemand muss Updates, Backups (einschließlich des Vault-Schlüssels), Zugriffe und die verbundenen externen Dienste verantworten. [Bereitstellung](https://vstorm-co.github.io/agenticos/de/deploy/) · [Rollout](https://vstorm-co.github.io/agenticos/de/rollout/)

</details>

## 💬 Community

- **Fragen und Ideen:** [GitHub Discussions](https://github.com/vstorm-co/agenticos/discussions).
- **Fehler und Wünsche:** [Issues](https://github.com/vstorm-co/agenticos/issues); geplante Arbeit ist in [Milestones](https://github.com/vstorm-co/agenticos/milestones) gruppiert.
- **Mitwirken:** Lies den [Leitfaden zum Mitwirken](CONTRIBUTING.de.md) und den [Verhaltenskodex](CODE_OF_CONDUCT.de.md). Melde Sicherheitslücken vertraulich, wie [SECURITY.de.md](SECURITY.de.md) beschreibt.
- **Releases:** Lies die [Release Notes](https://vstorm-co.github.io/agenticos/de/release-notes/) oder wähle auf GitHub **Watch → Custom → Releases**, um benachrichtigt zu werden.

## 📄 Lizenz

[Apache License 2.0](LICENSE). Siehe [NOTICE](NOTICE) und die [Hinweise zu Drittkomponenten](THIRD_PARTY_NOTICES.md) für Namensnennungen und enthaltene Komponenten.

## 🤝 Brauchst du Hilfe beim produktiven Einsatz von Agenten?

Vstorm stellt AgenticOS in der Infrastruktur von Kunden bereit, schreibt die Dokumentation, definiert die Prozesse und baut eigene Capabilities. Wartung und Support werden pro Auftrag vereinbart.

Mit Sorgfalt gebaut von [**Vstorm**](https://vstorm.co) · [Vstorm on GitHub](https://github.com/vstorm-co)

## 👥 Mitwirkende

Alle, die AgenticOS mit aufgebaut haben:

<a href="https://github.com/vstorm-co/agenticos/graphs/contributors"><img src="https://contrib.rocks/image?repo=vstorm-co/agenticos" alt="Avatare aller, die zu AgenticOS beigetragen haben"></a>
