<!-- source_sha: 5517463ff18f -->

<div align="center">

<h1><img src="docs/assets/amigo-walk.svg" alt="Amigo, das AgenticOS-Maskottchen" width="64" valign="middle"> AgenticOS</h1>

<p>
  <b>Lass KI in deinem Unternehmen mitarbeiten.</b><br>
  <strong>Sovereign Agentic AI Layer</strong><br>
  Open Source. Gemeinsame Agenten, Unternehmenswissen und Automatisierung — auf Infrastruktur, die du kontrollierst.
</p>

<p>
  <a href="#so-funktioniert-es">Demo ansehen</a> &middot;
  <a href="#schnellstart">Schnellstart</a> &middot;
  <a href="#den-agent-layer-erkunden">Den Agent-Layer erkunden</a> &middot;
  <a href="#warum-ein-betriebssystem">Warum ein OS</a> &middot;
  <a href="docs/index.de.md">Dokumentation</a>
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

Gib einem Agenten ein Briefing, deine Dokumente und deine Werkzeuge. Er recherchiert, schreibt den Bericht und veröffentlicht eine Seite, die dein Team öffnen kann. Anweisungen, Zugriffe und jede Ausführung bleiben an einem Ort, auf Cloud- oder lokalen Modellen.

<h3 align="center">🔌 5.700+ Integrationen über MCP &nbsp;·&nbsp; 🤝 Gemeinsame Agenten und Wissen<br>
📊 Integrierte Observability &nbsp;·&nbsp; 🏠 Selbst gehostet</h3>

## So funktioniert es

**Von einem Notion-Briefing und GitHub-Recherche zu einer interaktiven Entscheidungsseite.**

Der Agent liest das Briefing in Notion, recherchiert die infrage kommenden Repositories auf GitHub und veröffentlicht
ein Artifact, das für jede Zielgruppe ein Projekt empfiehlt, mit Quellen.

<video src="https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512" controls playsinline width="100%" poster="docs/assets/screens/oss-launch-planner-poster.webp">
  <img src="docs/assets/screens/oss-launch-planner-poster.webp" alt="Vstorm OSS Launch Planner: Zielgruppenauswahl, Projektempfehlung und Quellenlinks" width="100%">
</video>

<details>
<summary>Video wird nicht geladen? Animierte Vorschau öffnen</summary>

<a href="https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512">
  <img src="docs/assets/screens/oss-launch-planner-preview.gif" alt="Vstorm OSS Launch Planner: Zielgruppenauswahl, Projektempfehlung und Quellenlinks" width="100%">
</a>

*Animierte Vorschau in doppelter Geschwindigkeit. Klicke, um das 37-sekündige Video mit Ton in normaler Geschwindigkeit anzusehen.*

</details>

[Das gekürzte Video ansehen (37 Sekunden)](https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512) · [Screenshot ansehen](docs/assets/screens/oss-launch-planner-poster.webp)

## Schnellstart

Du brauchst nur Docker mit Compose. Unter macOS oder Linux führst du aus:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

Unter Windows führst du denselben Befehl in WSL2 aus, mit eingeschalteter WSL2-Integration in Docker Desktop.
Der Installer fragt nach Modellanbieter und Schlüssel, deinem Login und dem Namen der Organisation, lädt die
veröffentlichten Images und startet eine Bereitstellung mit einem funktionierenden Agenten.

Öffne **http://localhost:3000** und melde dich mit dem gewählten Login an. Mit den Standardwerten ist das
`admin@example.com` / `admin123`.

### Die erste Aufgabe ausprobieren

Wähle unter **Chat** den Agenten **Getting Started** und füge dieses fiktive Briefing ein. Es braucht keine
Verbindung zu Notion oder GitHub.

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
sollte der fehlende Prüftermin auffallen, bei den Einladungen die fehlende Zuständigkeit. Öffne dann **Activity**:
Die Ausführung ist schon da, mit Modell, Tokens, Dauer und Kosten. Probiere danach
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

## 💬 Agenten dort einsetzen, wo dein Team bereits arbeitet

<p align="center">
  <a href="docs/channels.de.md"><img src="docs/assets/channels/slack.svg" alt="Slack" width="176" height="64"></a>
  <a href="docs/channels.de.md"><img src="docs/assets/channels/mattermost.svg" alt="Mattermost" width="176" height="64"></a>
  <a href="docs/channels.de.md"><img src="docs/assets/channels/telegram.svg" alt="Telegram" width="176" height="64"></a>
</p>

Nutze deinen veröffentlichten Agenten in **Slack, Mattermost oder Telegram**. Kollegen bitten dort um Hilfe, wo sie ohnehin arbeiten, und der Agent antwortet mit seinen Anweisungen, seinem Wissen und seinen Werkzeugen. Eine `@mention` läuft als die Person, die sie geschickt hat, nicht als der Bot.

Derselbe veröffentlichte Agent antwortet auch im Web-Chat, in einem Website-Widget, auf einer gehosteten Seite und in deiner eigenen Anwendung über die API, mit einem Satz Limits und einem Ausführungsverlauf.

[Slack, Mattermost und weitere Kanäle verbinden](docs/channels.de.md).

## Den Agent-Layer erkunden

Alles Folgende läuft in der Konsole im Browser; nichts davon braucht Code.

<table>
<tr>
<td colspan="2" valign="top">

### 🤖 Einen Agenten konfigurieren

Unter **Agents** erstellst du einen Assistenten für eine Aufgabe, wählst sein Modell, schreibst Anweisungen und aktivierst Werkzeuge.
Veröffentliche eine Version, sobald er einsatzbereit ist. Jede frühere Version bleibt lesbar, und ein Rollback ist ein Klick.
[Einen Agenten bauen](docs/first-agent.de.md).

<a href="docs/assets/screens/light/agent-builder.webp">
  <img src="docs/assets/screens/light/agent-builder.webp" alt="Agent-Builder mit Anweisungen, ausgewähltem Modell und aktuell veröffentlichter Version." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 📄 Ergebnisse außerhalb des Chats aufbewahren

**Artifacts** sind Seiten, die ein Agent erstellt: Berichte, interaktive Vergleiche oder kleine Dashboards.
Öffne sie aus der Bibliothek, prüfe Versionen und lege fest, wer Zugriff hat. Wird dasselbe Artifact aktualisiert,
bleibt sein Link erhalten; eine Unterhaltung kann auf eine bestimmte Version verweisen. [Artifacts erstellen und teilen](docs/artifacts.de.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/artifacts.webp">
  <img src="docs/assets/screens/light/artifacts.webp" alt="Artifact-Bibliothek mit gespeicherten Berichten und Versionen." width="100%">
</a>

</td>
</tr>
<tr>
<td colspan="2" valign="top">

### 🔌 5.700+ Integrationen über MCP

Verbinde Agenten mit den Werkzeugen, die dein Unternehmen bereits nutzt: **GitHub, Notion, HubSpot, Linear und n8n**.
**MCP** (Model Context Protocol) ist der Standard, über den Agenten externe Werkzeuge und Datenquellen aufrufen.

Durchsuche den Katalog nach Namen oder füge einen kompatiblen Server per URL hinzu.
Verbinde die benötigten Dienste und wähle, welche Werkzeuge jeder Agent nutzen darf. [Werkzeuge verbinden](docs/mcp.de.md).

<a href="docs/assets/screens/light/mcp-catalog.webp">
  <img src="docs/assets/screens/light/mcp-catalog.webp" alt="MCP-Katalog mit GitHub, Notion, Slack und weiteren Diensten samt Verbindungsstatus." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🧩 Wiederverwendbare Abläufe vermitteln

**Skills** sind schriftliche Abläufe, die ein Agent bei Bedarf lädt: wie ein Angebot geprüft,
ein Bericht abgestimmt oder dein Schreibstil eingehalten wird. Schreibe einen Ablauf einmal und hänge ihn an die Agenten,
die ihn brauchen. Nach einer Änderung gilt er ab der nächsten Antwort, ohne Release. [Mehr über Skills](docs/skills.de.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/skill-detail.webp">
  <img src="docs/assets/screens/light/skill-detail.webp" alt="Der Ablauf artifact-pages mit Anweisungen und Seitenvorlagen." width="100%">
</a>

</td>
</tr>
<tr>
<td colspan="2" valign="top">

### 📚 Dokumente durchsuchbar machen

**Knowledge bases** ordnen Dokumente in Sammlungen, die du Agenten zuweist. Der Agent durchsucht diese
Quellen beim Antworten nach passenden Abschnitten. Das wird oft **RAG** genannt, Retrieval-Augmented Generation.
PDF-Reader, Chunking und OCR wählst du pro Sammlung. [Dokumente hinzufügen und verarbeiten](docs/file-processing.de.md).

<a href="docs/assets/screens/light/knowledge-bases.webp">
  <img src="docs/assets/screens/light/knowledge-bases.webp" alt="Knowledge bases mit persönlichen und organisationsweiten Sammlungen." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🧠 Gemeinsamer Kontext

**Context** enthält feste Informationen wie Produktnamen, ein Glossar oder Kommunikationsrichtlinien.
Nutze ihn für Fakten und Regeln, die für viele Aufgaben gelten; lege fest, ob der Agent sie automatisch erhält
oder bei Bedarf liest. [Mehr über Context](docs/context.de.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/context-detail.webp">
  <img src="docs/assets/screens/light/context-detail.webp" alt="Glossar in der Vorschau, verknüpft zum Lesen bei Bedarf." width="100%">
</a>

</td>
</tr>
<tr>
<td colspan="2" valign="top">

### 📊 Integrierte Observability: Ausführungen und Kosten im Blick

**Activity** bündelt Ausführungsverlauf, Freigaben und Ausgaben. Jede Ausführung speichert Status,
Modell, Tokens, Dauer und Kosten. Filtere nach Agent, Person oder Version, vergleiche Versionen und exportiere die
Daten als CSV. Öffne eine Ausführung, um die Unterhaltung und jeden Werkzeugaufruf zu sehen.
[Activity und Kostenkontrolle](docs/governance.de.md).

<a href="docs/assets/screens/light/activity.webp">
  <img src="docs/assets/screens/light/activity.webp" alt="Activity mit Versionsvergleich und gefiltertem Ausführungsverlauf: Status, Tokens, Dauer und erfasste Kosten." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🛡️ Menschliche Freigabe

Alles, was etwas verschickt, ablegt oder verändert, kann auf einen Menschen warten. Die Freigabeanfrage zeigt
die geplante Operation mit ihren Argumenten, und die Aktion läuft erst, wenn jemand zustimmt.
Der Zugriff auf Agenten und Ressourcen wird über [Rollen und Berechtigungen](docs/permissions.de.md) gesteuert.

</td>
<td width="70%">

<a href="docs/assets/screens/light/approval.webp">
  <img src="docs/assets/screens/light/approval.webp" alt="Eine wartende Werkzeugaktion mit Argumenten und Freigabeschaltflächen." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### ⏱️ Wiederkehrende Arbeit planen

**Routines** starten einen Agenten nach Zeitplan oder auf ein Ereignis hin: das Montagsbriefing, der
wiederkehrende Bericht. Eine Routine-Ausführung hat dieselben Limits und denselben Eintrag wie alles, worum ein Mensch gebeten hat.
[Eine Routine einrichten](docs/triggers.de.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/routines.webp">
  <img src="docs/assets/screens/light/routines.webp" alt="Zeitplan-Editor mit wöchentlicher Wiederholung am Montag um 06:00 UTC und der Nachricht an den Agenten in der Vorschau." width="100%">
</a>

</td>
</tr>
</table>

<details>
<summary>Weitere Ansichten</summary>

<a href="docs/assets/screens/light/skills.webp">
  <img src="docs/assets/screens/light/skills.webp" alt="Skills-Bibliothek mit wiederverwendbaren Abläufen." width="100%">
</a>

<a href="docs/assets/screens/light/context.webp">
  <img src="docs/assets/screens/light/context.webp" alt="Context-Bibliothek mit gemeinsamen Glossardateien." width="100%">
</a>

<a href="docs/assets/screens/light/knowledge-collection.webp">
  <img src="docs/assets/screens/light/knowledge-collection.webp" alt="Die Sammlung vstorm mit erfolgreich verarbeiteter adding_features.md." width="100%">
</a>

<a href="docs/assets/screens/light/artifact-detail.webp">
  <img src="docs/assets/screens/light/artifact-detail.webp" alt="OSS Launch Planner aus der Demo mit Zielgruppenauswahl und Empfehlung." width="100%">
</a>

</details>

## Warum ein Betriebssystem

Der Name ist eine Behauptung, also hier die Kriterien. Ein Betriebssystem erledigt sieben Aufgaben; jede Zeile
ist ein Mechanismus, den du im Quellcode nachlesen kannst.

| Ein Betriebssystem… | AgenticOS |
|---|---|
| **Führt Prozesse aus und isoliert sie** | Führt Agenten aus, isoliert Mandanten im Schema und speichert jede Ausführung mit ihren Kosten |
| **Setzt Ressourcenlimits durch** | Monatliche Budgets pro Agent, geprüft *vor* jeder Modellanfrage |
| **Steuert den Zugriff** | Ein [Berechtigungskatalog](docs/permissions.de.md) im Code, daraus zusammengesetzte Rollen, Freigaben pro Ressource; eine Freigabe ist das `sudo` |
| **Spricht Hardware über Treiber an** | [27 Modellanbieter](docs/models.de.md) und [MCP-Server](docs/mcp.de.md) hinter einer Schnittstelle |
| **Führt ein Dateisystem** | [Sammlungen, Skills und Context](docs/file-processing.de.md) in deinem eigenen Postgres |
| **Gibt vielen Oberflächen eine Shell** | Ein Runner hinter Web-Chat, API, Slack, Telegram, Mattermost, Widget, gehosteter Seite und Zeitplan |
| **Schreibt ein Audit-Log** | Wer was wann ausgeführt hat, was es gekostet hat und wer es freigegeben hat — auch wenn die Ausführung fehlschlug |

Wende dieselben sieben auf alles andere in der Kategorie an, uns eingeschlossen:
[was ein Betriebssystem für Agenten ausmacht](docs/about/index.de.md).

## Warum es das gibt

Die meisten Agent-Frameworks liefern eine Bibliothek. Du schreibst Python, deployst es, und jede Änderung am
Verhalten eines Agenten ist ein Pull Request, ein Review und ein Release. Das ist die richtige Form für ein
Produktfeature und die falsche für die vierzig kleinen Agenten, die ein Unternehmen tatsächlich will — denn wer
weiß, was der Agent sagen soll, ist nicht die Person mit Commit-Rechten.

**Code definiert, Konfiguration setzt zusammen.** Ein Fachteam baut Agenten im Browser zusammen und öffnet nie
Python; Entwickler erweitern, was es zum Zusammensetzen gibt, und die Konfiguration erreicht nur, was der Code
registriert hat. Die Obergrenze ist die Capability-Registry, keine Konfigurationsdatei.

## KI-Arbeit im Team verankern

Für einen wiederkehrenden Bericht kann das Team die Arbeit aufteilen:

1. **Eine Fachperson legt die Methode fest:** Sie pflegt Anweisungen, Skills und das Quellwissen.
2. **Eine Person aus dem Aufbau stellt den Agenten bereit:** Sie konfiguriert Werkzeuge, veröffentlicht eine Version und gibt Kollegen Zugriff.
3. **Kollegen nutzen die Ergebnisse:** Sie starten den Agenten, prüfen das Ergebnis und teilen ein Artifact mit den Personen, die es brauchen.

Der Agent und sein Know-how gehören der Organisation, nicht der Person, die den ersten Prompt geschrieben hat.
[Teamzugriff einrichten](docs/permissions.de.md).

## Betrieb, Modelle und Zugriff selbst kontrollieren

**Souveränität bedeutet Kontrolle über Bereitstellung, Modellanbieter, Datenflüsse und Agentenzugriff.** Du wählst, welche Komponenten lokal laufen und welche externen Dienste Daten erhalten.

**Auf deiner Infrastruktur betreiben.** AgenticOS ist Apache-2.0-Software, die du prüfen, ändern und betreiben kannst.
Wähle gehostete Modellanbieter oder lokale Modelle über Ollama und kompatible Endpunkte wie vLLM.
[Modellkonfiguration](docs/models.de.md).

**Festlegen, was ein Agent darf.** Konfiguriere Ressourcenberechtigungen, speichere Zugangsdaten im verschlüsselten Vault
und setze eine menschliche Freigabe vor Werkzeuge, die nach außen handeln. [Zugriffskontrolle](docs/permissions.de.md) · [Secrets](docs/secrets.de.md).

[Bereitstellen und betreiben](docs/rollout.de.md) · [Ausführungs- und Kostenkontrolle](docs/governance.de.md) · [Sicherheit und Datenflüsse](docs/security.de.md)

## Passt AgenticOS zu deinem Unternehmen?

Wähle AgenticOS, wenn dein Unternehmen gemeinsame Agenten, wiederverwendbares Wissen und Automatisierung will und dabei
Quellcode, Modelle und Bereitstellung selbst kontrollieren möchte. Wenn du nur eine Agent-Bibliothek in einer
bestehenden Anwendung brauchst, beginne mit einem Framework.

Jeder Vergleich zitiert die Seiten des Anbieters, zeigt, wo AgenticOS weiter geht, und nennt, was es noch nicht kann.

- **Assistenz-Apps:** [Claude](docs/about/claude-apps.de.md) · [ChatGPT](docs/about/chatgpt.de.md). Lizenzen für Mitarbeitende oder Agenten, die deiner Organisation gehören, auf jedem Modell.
- **Builder in Cloud-Suiten:** [Copilot Studio](docs/about/copilot-studio.de.md) · [Gemini Enterprise](docs/about/gemini-enterprise.de.md). Cloud und Abrechnung eines Anbieters oder deine Infrastruktur und die Preise deines Modellanbieters.
- **Selbst gehostete Builder:** [Dify](docs/about/dify.de.md) · [n8n](docs/about/n8n.de.md). Lizenzbedingungen und Enterprise-Stufen oder Apache-2.0 mit Governance inklusive.
- **KI-Kollege als Dienst:** [Viktor](docs/about/viktor.de.md). Ein gemeinsamer KI-Mitarbeiter oder viele Agenten mit eigenen Zugriffen und Budgets.
- **Gelieferter Agent-Layer:** [Wonderful](docs/about/wonderful.de.md). Ein System, das ein Anbieter liefert, oder eines, das dir vom ersten Tag an gehört.
- **Coding-Agenten:** [Claude Code](docs/about/claude-code.de.md) · [Codex](docs/about/codex.de.md) · [OpenCode](docs/about/opencode.de.md). Für Entwickler gebaut; AgenticOS ist für alle anderen, und Entwickler erweitern es.

[Alle Vergleiche und die Lücken](docs/about/comparison.de.md).

<details>
<summary>Fragen zum Agent-Layer</summary>

### Ist AgenticOS ein AI Agent Harness?

Ja, mit einer Oberfläche fürs Team. Der Harness ist die Schleife, die ein Modell mit Werkzeugen ausführt: Suche
in deinen Dokumenten, Websuche und ein echter Browser, Python in einer Sandbox mit Dateien und Shell, Diagramme,
Bilder, Delegation an Subagenten, eine Aufgabenliste und das Verdichten langer Unterhaltungen. Jede dieser Fähigkeiten
schaltest du pro Agent im Browser ein, neben Skills, Context, MCP-Servern, Budgets und Freigaben. Entwickler fügen
neue Fähigkeiten in typisiertem Python hinzu. Siehe die [Capability-Referenz](docs/reference/capabilities.de.md).

### Kann ich einen Agenten nach dem Vorbild von Claude Code für Geschäftsaufgaben erstellen?

Ja. Gib einem Agenten eine Sandbox mit Dateien und Shell, Websuche, einen Browser, Delegation und eine Aufgabenliste,
und hänge die nötigen Skills und den Context an. Er plant mehrstufige Arbeit, liest, bevor er handelt, bearbeitet Dateien,
führt Befehle aus, gibt Teile an Spezialisten ab und prüft das Ergebnis. Er antwortet im Web-Chat, in Slack oder über
die API, auf dem Modell deiner Wahl, mit Freigabe vor allem, was nach außen handelt. Siehe den
[Vergleich mit Claude Code](docs/about/claude-code.de.md).

### Lässt es sich vollständig auf eigener Infrastruktur betreiben?

Ja. Modelle laufen über Ollama oder vLLM, Dokumente werden über ein Ollama im eigenen Netz eingebettet, und
PDFs liest der eingebaute PyMuPDF-Reader oder ein selbst gehostetes LiteParse mit OCR. Nichts verlässt die
Bereitstellung, solange keine Einstellung ein Ziel nennt. Siehe [Datenschutz](docs/data-protection.de.md).

</details>

## Auf dem Desktop, wenn du willst

Die Konsole ist eine Web-App, und ein Browser genügt. Die optionale [Desktop-App](docs/desktop.de.md)
ist dieselbe Konsole in einem eigenen Fenster, mit einem Maskottchen auf dem Desktop und einem globalen Kürzel (`⌘⇧A`),
das einen beliebigen Bildschirmbereich direkt in einen neuen Chat aufnimmt.

## Für Entwickler und Betreiber

Gebaut mit FastAPI, Pydantic AI, PostgreSQL mit pgvector, Redis, Prefect und Next.js.
Jeder veröffentlichte Agent ist auch ein Endpunkt, mit demselben Budget, denselben Freigaben und demselben Ausführungsverlauf wie die Konsole:

```bash
curl -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Fasse die offenen Support-Tickets zusammen"}'
```

| Hier anfangen | Inhalt |
|---|---|
| [Architektur](docs/architecture.de.md) | Dienste, Speicherung und Ausführung |
| [Capabilities](docs/reference/capabilities.de.md) | Verfügbare Werkzeuge und Konfiguration |
| [API](docs/api.de.md) | Integration in deine Anwendungen |
| [Modelle](docs/models.de.md) | Modellanbieter und Profile |
| [Sicherheit](docs/security.de.md) | Datenflüsse und Grenzen der Bereitstellung |
| [Tests](docs/testing.de.md) | Testsuiten und Abdeckungsumfang |

`make check` vor einem Pull Request: jeder CI-Job außer e2e. Neues Verhalten kommt mit einem Test; ein Bugfix
mit einem Regressionstest. Der Kern hält 100 % Abdeckung, und CI schlägt darunter fehl.

Drei Dinge, über die eine erste Änderung stolpert: Ein Werkzeug ist Code, ein Agent nicht (es gibt kein
`@agent.tool` — eine Capability registriert sich und ist dann ein Schalter in jedem Builder);
`require(...)`-Gates gehören nur auf Collection-Routen; und wenn das Werkzeug schon als MCP-Server existiert,
schreib keins. [Mitwirken](CONTRIBUTING.de.md) beschreibt den Rest, [`.claude/`](.claude/README.md) enthält
dieselben Konventionen für eine Maschine, die [Roadmap](docs/ROADMAP.md) zeigt geplante Arbeit, und Einstiegsaufgaben
sind [hier markiert](https://github.com/vstorm-co/agenticos/labels/good%20first%20issue).

<details>
<summary><b>Das übrige Vstorm-OSS-Ökosystem</b></summary>

Alles hier läuft auf [Pydantic AI](https://ai.pydantic.dev).

| Projekt | Was es ist | |
|---|---|---|
| **[full-stack-ai-agent-template](https://github.com/vstorm-co/full-stack-ai-agent-template)** | Der Generator, aus dem AgenticOS entstand — FastAPI + Next.js, RAG, Streaming, Auth, 20+ Integrationen | [![Stars](https://img.shields.io/github/stars/vstorm-co/full-stack-ai-agent-template?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/full-stack-ai-agent-template) |
| **[pydantic-deepagents](https://github.com/vstorm-co/pydantic-deepagents)** | Quelloffenes, selbst gehostetes Claude Code — ein Terminal-Assistent und das Framework dahinter | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-deepagents?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-deepagents) |
| **[pydantic-ai-shields](https://github.com/vstorm-co/pydantic-ai-shields)** | Guardrails — Kostenverfolgung, Erkennung von Prompt Injection, PII-Filter, Schwärzen von Secrets | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-shields?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-shields) |
| **[subagents-pydantic-ai](https://github.com/vstorm-co/subagents-pydantic-ai)** | Verschachtelte Delegation an Subagenten, parallele Ausführung, Abbruch von Aufgaben | [![Stars](https://img.shields.io/github/stars/vstorm-co/subagents-pydantic-ai?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/subagents-pydantic-ai) |
| **[pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend)** | Dateispeicher und in Docker isolierte Sandboxes, mit Berechtigungssystem | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-backend?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-backend) |
| **[pydantic-ai-todo](https://github.com/vstorm-co/pydantic-ai-todo)** | Hierarchische Aufgabenplanung mit PostgreSQL-Speicher und Ereignissystem | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-todo?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-todo) |
| **[production-stack-skills](https://github.com/vstorm-co/production-stack-skills)** | Skill-Paket, das einen Coding-Agenten zu einem erfahrenen Produktionsingenieur macht | [![Stars](https://img.shields.io/github/stars/vstorm-co/production-stack-skills?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/production-stack-skills) |
| **[content-skills](https://github.com/vstorm-co/content-skills)** | Skill-Paket für Inhalte mit Coding-Agenten — markenbewusst, mit eingebautem Anti-Slop | [![Stars](https://img.shields.io/github/stars/vstorm-co/content-skills?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/content-skills) |

Alle Projekte findest du auf **[oss.vstorm.co](https://oss.vstorm.co)**.

</details>

## Lizenz

[Apache License 2.0](LICENSE). Siehe [NOTICE](NOTICE) und die [Hinweise zu Drittkomponenten](THIRD_PARTY_NOTICES.md)
für Namensnennungen und enthaltene Komponenten.

## Brauchst du Hilfe beim produktiven Einsatz von Agenten?

Vstorm stellt AgenticOS in der Infrastruktur von Kunden bereit, schreibt die Dokumentation, definiert die Prozesse
und baut eigene Capabilities. Wartung und Support werden pro Auftrag vereinbart.

Mit Sorgfalt gebaut von [**Vstorm**](https://vstorm.co) · [oss.vstorm.co](https://oss.vstorm.co)
