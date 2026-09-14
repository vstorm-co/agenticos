<!-- source_sha: 191696f072e5 -->

<div align="center">

<img src="docs/assets/amigo.svg" alt="Amigo, the AgenticOS pet" width="96">

<h1>AgenticOS</h1>

<p>
  <b>Ein Ort, um die KI-Agents Ihres Unternehmens zu bauen, zu betreiben und zu steuern.</b><br>
  Selbst gehostet und Open Source — auf Ihrem Postgres, in Ihrem Docker, unter
  Ihrer Domain.<br>
  <sub>Das OS im Namen ist eine Behauptung, die wir einlösen: <a href="#das-beste-betriebssystem-für-agents-das-sie-selbst-betreiben-können">sieben Funktionen, sieben Mechanismen</a>.</sub>
</p>

<p>
  <a href="#-schnellstart">Schnellstart</a> &middot;
  <a href="#wie-es-aussieht">Bildschirme</a> &middot;
  <a href="https://vstorm-co.github.io/agenticos/presentation/">Präsentation</a> &middot;
  <a href="docs/index.de.md">Dokumentation</a> &middot;
  <a href="#das-beste-betriebssystem-für-agents-das-sie-selbst-betreiben-können">Warum ein OS</a> &middot;
  <a href="#im-vergleich-mit-den-alternativen">Vergleich</a>
</p>

<p>
  <a href="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml"><img src="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://github.com/vstorm-co/agenticos/releases"><img src="https://img.shields.io/github/v/release/vstorm-co/agenticos?label=release&color=blue" alt="Release"></a>
  <a href="docs/testing.de.md"><img src="https://img.shields.io/badge/platform%20layer-100%25-brightgreen" alt="Coverage"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-Apache--2.0-blue" alt="Licence"></a>
  <a href="https://ai.pydantic.dev"><img src="https://img.shields.io/badge/Powered%20by-Pydantic%20AI-E92063?logo=pydantic&logoColor=white" alt="Pydantic AI"></a>
  <a href="https://github.com/vstorm-co/agenticos/stargazers"><img src="https://img.shields.io/github/stars/vstorm-co/agenticos?style=flat&logo=github&color=e3b341" alt="Stars"></a>
</p>

<p>
  <a href="README.md">English</a> &middot;
  <a href="README.pl.md">Polski</a> &middot;
  <b>Deutsch</b> &middot;
  <a href="README.es.md">Español</a>
</p>

</div>

---

Ein Unternehmen hat am Ende Agents an fünf Stellen und kann vier Fragen nicht
beantworten: **was betreiben wir, was hat es gekostet, was hat es angefasst, und
wer hat es erlaubt.** AgenticOS ist ein Ort, um sie zu bauen, und eine
Buchführung für sie alle.

**Der Harness, als Produkt**: Skills, Context-Dateien — `AGENTS.md` als Seite —
MCP im Maßstab einer Registry, Automatisierungen nach Zeitplan oder Trigger, und
ein Budget, das einen Run *vor* dem Modellaufruf stoppt.

Unten: eine Tabelle in den Chat gelegt, ein Satz, der um Diagramme bittet. Der
Agent schreibt den Code, führt ihn in einer abgeschlossenen Box aus und antwortet.

<div align="center">

<video src="https://github.com/user-attachments/assets/9a8e0f44-781c-4f93-990d-b5b7094cc8fc" controls muted loop playsinline width="100%">
  <img src="docs/assets/screens/chat-live-demo.webp" alt="Chat: Aus einer CSV wird Python in einer Sandbox, dann Diagramme" width="100%">
</video>

</div>

Und dieselbe Konsole auf dem Desktop, mit Gesellschaft: die optionale
[Desktop-App](#auf-dem-desktop-wenn-sie-mögen), ihr Haustier und ein Kürzel, das
einen Screenshot direkt in einen neuen Chat legt.

<div align="center">

<video src="https://github.com/user-attachments/assets/b82867ae-3543-406e-a552-e3a8b61f1d10" controls muted loop playsinline width="100%">
  <img src="docs/assets/desktop_no_more_caramba_pet.png" alt="Amigo, das Desktop-Haustier, mit Sombrero, sagt: No more caramba." width="270">
</video>

</div>

<div align="center">
<sub>
Kein Freund langer Texte? <a href="https://vstorm-co.github.io/agenticos/presentation/"><b>Das Ganze in zwanzig Folien</b></a> — worin das Problem besteht, was ein Spec enthält, wo er antwortet und was er verweigert.
</sub>
</div>

## ⚡ Schnellstart

Ein Kommando, und mehr als Docker braucht es nicht. Es lädt eine Compose-Datei
herunter, holt die veröffentlichten Images, stellt vier Fragen und gibt Ihnen
eine Konsole mit einem funktionierenden Agent darin zurück. Nichts verlässt Ihre
Maschine.

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

<details>
<summary><b>macOS</b></summary>

Docker Desktop oder [OrbStack](https://orbstack.dev). Sonst nichts.

</details>

<details>
<summary><b>Linux</b></summary>

```bash
curl -fsSL https://get.docker.com | sh
sudo apt install docker-compose-plugin
```

</details>

<details>
<summary><b>Windows</b></summary>

Über WSL2. In einer PowerShell als Administrator:

```powershell
wsl --install
```

Danach Docker Desktop mit eingeschalteter WSL2-Integration, und führen Sie den
Installer in der Ubuntu-Shell aus, die es Ihnen gibt.

</details>

### Was es fragt

| | |
|---|---|
| **Welches Modell** | OpenAI, Anthropic, Google, OpenRouter — oder *später entscheiden*, was alles anlegt und Sie einen Schlüssel in der Konsole einfügen lässt |
| **Ihr Schlüssel** | Verdeckt eingegeben, verschlüsselt in Ihrer eigenen Datenbank abgelegt, nie zurückgegeben |
| **Ihr Login und der Name Ihrer Organisation** | Für einen ersten Blick genügen die Vorgaben |
| **Ein Schalter** | Die öffentliche MCP-Registry spiegeln, damit alle 5.802 Tool-Server über den Namen auffindbar sind |

Geben Sie `--check` an, um nur zu erfahren, was fehlt, `--dry-run`, um jedes
Kommando zu sehen, das es ausführen würde, ohne eines auszuführen, oder steuern
Sie es unbeaufsichtigt:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- \
  --yes --provider anthropic --api-key sk-ant-... --org "Acme"
```

### Oder tippen Sie die drei Kommandos selbst

Der Installer ist eine Hülle um diese drei, und es gibt keinen Schritt darin, den
Sie nicht von Hand machen können:

```bash
mkdir agenticos && cd agenticos
curl -fsSLO https://raw.githubusercontent.com/vstorm-co/agenticos/main/docker-compose.yml
docker compose up -d                                          # postgres (pgvector), redis, api, prefect, console
docker compose exec -T -e BOOTSTRAP_API_KEY=sk-... app \
  agenticos cmd bootstrap                                    # an org, an owner, a key, a model, a published agent
open http://localhost:3000                                   # sign in as admin@example.com / admin123
```

Die Images sind `ghcr.io/vstorm-co/agenticos-backend` und `agenticos-frontend`,
von jedem Release für amd64 und arm64 veröffentlicht; `AGENTICOS_VERSION=x.y.z`
in einer `.env` neben der Datei legt eines fest. Es gibt keine `.env`, die Sie
vorher schreiben müssten: jede Compose-Variable hat einen Vorgabewert. Um am Code
etwas zu ändern, nehmen Sie stattdessen `git clone` und `make dev` - ein Klon
baut dieselben Images aus dem Baum.

Wenn etwas nicht hochkommt, beantwortet
`docker compose exec app agenticos cmd doctor` die einzige Frage, auf die es
ankommt — kann dieses Deployment tatsächlich einen Agent ausführen — und
[docs/install.de.md](docs/install.de.md) hat den Rest.

## Was Sie bekommen

- 🧰 **Der Harness, als Konfiguration.** Retrieval über Ihre Dokumente, ein echter
  Browser, Python in einer Sandbox mit Dateien und einer Shell, Diagramme, Bilder,
  Delegation — pro Agent eingeschaltet, nicht in Code verdrahtet.
- 📄 **Context-Dateien.** `AGENTS.md` und `CLAUDE.md` als Seite: stehende
  Instruktionen, einmal geschrieben, an jeden Agent gehängt, der sie braucht.
- 🎓 **Skills.** Ein Verfahren, einmal in einfacher Sprache geschrieben, geladen,
  wenn der Agent es für einschlägig hält. Bearbeiten Sie es; bei der nächsten
  Antwort ist es live, ohne Release.
- 🔌 **MCP, im Maßstab einer Registry.** **5.802 Server** im Katalog, über den
  Namen auffindbar — 99 davon von Hand geprüft, mit verdrahtetem OAuth. Oder jede
  beliebige URL.
- 📚 **Dokumente, richtig gelesen.** Wählen Sie den PDF-Reader pro Collection oder
  für eine einzelne Datei: PyMuPDF eingebaut, LlamaParse dort, wo die Tabellen die
  Bedeutung tragen, selbst gehostetes LiteParse-OCR für Scans. Dazu, wie geteilt
  wird, und die OCR-Sprache.
- ⏰ **Automatisierungen.** Zeitpläne und Event-Trigger — die 07:00-Triage, die
  Montagszusammenfassung. Dieselben Grenzen und derselbe Eintrag wie bei allem,
  worum ein Mensch gebeten hat.
- 📡 **Ein Runner, acht Oberflächen.** Web-Chat, eine gehostete Seite, ein Widget,
  die HTTP-API, ein reiner WebSocket, Slack, Telegram, Mattermost. Einmal
  veröffentlicht.
- 🖥️ **Mehr als einen Browser braucht es nicht; eine Desktop-App, wenn Sie eine
  wollen.** Die Konsole ist eine Web-App. Die [Desktop-App](docs/desktop.de.md) ist
  dieselbe Konsole in einem eigenen Fenster - dazu ein Haustier auf dem Desktop und
  ein Kürzel, das einen Screenshot direkt in einen neuen Chat legt. Eine Ergänzung,
  nie eine Voraussetzung.
- 🛡️ **Gesteuert.** Budgets, die einen Run vor der Modellanfrage stoppen, Approval
  für alles mit Nebenwirkung, eine Audit-Spur, Mandantentrennung im Schema.
- 📊 **Ein Dashboard, das sich jeder selbst legt.** 35 Karten — Runs, Ausgaben,
  Dienstzustand, Antwortqualität, Sandbox-Kapazität — jede daran gebunden, was der
  jeweilige Leser sehen darf. Ein Finanzleiter und ein Entwickler behalten auf
  einem Deployment verschiedene.

**Code definiert, Konfiguration setzt zusammen.** Ein Fachteam setzt Agents im
Browser zusammen und öffnet nie Python; Entwickler erweitern das, was sich
zusammensetzen lässt, und Konfiguration erreicht immer nur das, was Code
registriert hat. Die Obergrenze ist die Registry, keine Konfigurationsdatei — und
es steht unter Apache-2.0, auf Ihrer Hardware.

## Wie es aussieht

### Innerhalb eines Agents

Ein Agent ist ein **Spec**: Instruktionen, ein Modell, die Capabilities, die er
erreichen darf, das an ihn gebundene Wissen, ein Budget, und wo er antwortet.
Nichts geht raus bis **Publish**, und jedes Veröffentlichen ist eine Version.

<img src="docs/assets/screens/dark/builder-build.webp" alt="Einen Agent definieren: Instruktionen, Modell und die Version, die live ist" width="100%">

<table>
<tr>
<td width="50%">

**Toolbox** — Was der Agent tun darf, als Schalter — Ihre Dokumente, ein Browser, Python, Diagramme, Delegation. Jeder davon kann zuerst das Approval eines Menschen verlangen. Das ist der **KI-Harness**, in einem Formular zusammengesetzt.

<img alt="Toolbox" src="docs/assets/screens/dark/builder-toolbox.webp" width="100%">

</td>
<td width="50%">

**Visual map** — Der Agent als Graph: was ihn erreicht, wonach er greift. Ein gestrichelter Kasten ist etwas, das niemand angehängt hat.

<img alt="Visual map" src="docs/assets/screens/dark/builder-visual-map.webp" width="100%">

</td>
</tr>
<tr>
<td width="50%">

**Limits** — Eine monatliche Obergrenze pro Agent, *vor* jedem Modellaufruf geprüft statt hinterher zusammengezählt — dazu ein Schrittlimit, für die Schleife, die billig ist und nie aufhört.

<img alt="Limits" src="docs/assets/screens/dark/builder-limits.webp" width="100%">

</td>
<td width="50%">

**History** — Jede Version, die er hatte, weiterhin lesbar. Zurückrollen ist ein Klick.

<img alt="History" src="docs/assets/screens/dark/builder-history.webp" width="100%">

</td>
</tr>
</table>

<sub>Diese vier gibt es nur in Dunkel — die helle Hälfte ist nicht aufgenommen.</sub>

### Der erste Bildschirm

**Dashboard** — 35 Karten, von dem gelegt, der sie liest: Runs, Ausgaben,
Dienstzustand, Antwortqualität, Sync-Aktualität, Sandbox-Kapazität. Jede daran
gebunden, was diese Person sehen darf, sodass ein Finanzleiter und ein Entwickler
auf demselben Deployment verschiedene Dashboards behalten.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/dashboard.webp">
  <img alt="Das Dashboard: 35 Karten, die sich legen lassen" src="docs/assets/screens/light/dashboard.webp" width="100%">
</picture>

### Vierzig davon betreiben

<table>
<tr>
<td width="50%">

**Agents** — Jeder Agent, den Sie betreiben, mit der Version, die live ist, und wer ihn nutzen darf.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/agents.webp">
  <img alt="Agents" src="docs/assets/screens/light/agents.webp" width="100%">
</picture>

</td>
<td width="50%">

**Templates** — Beginnen Sie mit einem, das für Ihre Branche gebaut ist; Sie bekommen einen Entwurf zum Anpassen und Veröffentlichen.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/agents-templates-dialog.webp">
  <img alt="Templates" src="docs/assets/screens/light/agents-templates-dialog.webp" width="100%">
</picture>

</td>
</tr>
<tr>
<td width="50%">

**Eine Antwort, aufgeklappt** — Jede Antwort verzeichnet: die Frage, was sie angesehen hat, jeder Tool-Aufruf, die Dauer, die Kosten auf den Bruchteil eines Cents genau.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/activity-run-detail.webp">
  <img alt="Eine Antwort, aufgeklappt" src="docs/assets/screens/light/activity-run-detail.webp" width="100%">
</picture>

</td>
<td width="50%">

**Wie Ihre Dokumente gelesen werden** — Drei PDF-Reader — PyMuPDF, LiteParse, LlamaParse — dazu Chunking und OCR. Pro Collection, bei der nächsten Datei übersteuerbar. Eine eingescannte Preisliste und ein Vertrag wollen nicht denselben.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/knowledge-base-upload-parsing-dialog.webp">
  <img alt="Wie Ihre Dokumente gelesen werden" src="docs/assets/screens/light/knowledge-base-upload-parsing-dialog.webp" width="100%">
</picture>

</td>
</tr>
<tr>
<td width="50%">

**Context** — Stehende Fakten — Produktnamen, Richtlinien, der Ton des Hauses — an einem Ort statt in vierzig Prompts.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/context.webp">
  <img alt="Context" src="docs/assets/screens/light/context.webp" width="100%">
</picture>

</td>
<td width="50%">

**Es fragt, bevor es handelt** — Alles, was versendet, einreicht oder erstattet, wartet auf einen Menschen, mit ausgeschriebener beabsichtigter Aktion. Genau einmal entschieden.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/activity-approvals.webp">
  <img alt="Es fragt, bevor es handelt" src="docs/assets/screens/light/activity-approvals.webp" width="100%">
</picture>

</td>
</tr>
<tr>
<td width="50%">

**Was es kostet** — Ausgaben nach Zeitraum und nach Agent. Die Obergrenze wird geprüft, bevor das Modell gefragt wird, also stoppt ein Ausreißer mitten im Satz, statt als Rechnung anzukommen.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/activity-spend.webp">
  <img alt="Was es kostet" src="docs/assets/screens/light/activity-spend.webp" width="100%">
</picture>

</td>
<td width="50%">

**Schlüssel und Zugangsdaten** — Jeder Schlüssel, verschlüsselt und pro Team getrennt. Ersetzbar, nie wieder lesbar — auch nicht für den, der den Server betreibt.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/vault.webp">
  <img alt="Schlüssel und Zugangsdaten" src="docs/assets/screens/light/vault.webp" width="100%">
</picture>

</td>
</tr>
<tr>
<td width="50%">

**Die Tools, für die Sie ohnehin schon zahlen** — 5.802 MCP-Server im Katalog, über den Namen auffindbar, 99 davon von Hand geprüft, mit verdrahtetem OAuth. Oder jeder Server per URL. Kein Connector zu schreiben.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/mcp-servers.webp">
  <img alt="Die Tools, für die Sie ohnehin schon zahlen" src="docs/assets/screens/light/mcp-servers.webp" width="100%">
</picture>

</td>
<td width="50%">

**Wo Menschen ihm begegnen** — Slack, Telegram, Mattermost, ein Widget auf einer Website, Ihre eigene Software über die API. Einmal veröffentlicht; überall dieselben Grenzen.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/channels.webp">
  <img alt="Wo Menschen ihm begegnen" src="docs/assets/screens/light/channels.webp" width="100%">
</picture>

</td>
</tr>
</table>


<sub>Die Screenshots folgen Ihrem GitHub-Theme. <a href="docs/screens.de.md">Alle 35 Bildschirme</a>.</sub>

## Das beste Betriebssystem für Agents, das Sie selbst betreiben können

Das ist eine Behauptung, und der einzige ehrliche Weg, eine aufzustellen, ist,
die Kriterien herauszugeben und Sie zählen zu lassen. Ein Betriebssystem erledigt
sieben Aufgaben. Jede Zeile unten ist ein Mechanismus, den Sie im Quellcode
nachlesen können, kein Versprechen.

| Was ein Betriebssystem tut | Was AgenticOS tut |
|---|---|
| **Führt Prozesse aus und isoliert sie** | Führt Agents aus, stoppt einen an seinem Budget, trennt Mandanten im Schema statt im Service-Code und behält jeden Run mit dem, was er gekostet hat |
| **Erzwingt Ressourcengrenzen** - Quota, cgroups | Monatsbudgets pro Agent, geprüft *vor* jeder Modellanfrage statt hinterher zusammengezählt. Ein Run, der fehlschlägt, verzeichnet trotzdem, was er ausgegeben hat |
| **Kontrolliert Zugriffe** - Nutzer, Permissions, `sudo` | Ein [Permission-Katalog](docs/permissions.de.md) in Code, Rollen daraus zusammengesetzt, Grants pro Ressource, die ausweiten und nie einengen. `approval: required` ist das `sudo`: ein Tool, das auf die Außenwelt wirkt, wartet auf einen Menschen |
| **Erreicht Hardware über Treiber** | Eine Schnittstelle zu [27 Modell-Providern](docs/models.de.md) und zu [jedem MCP-Server per URL](docs/mcp.de.md). Ändern Sie ein Modellprofil, und jeder Agent, der es nutzt, zieht mit, ohne dass einer davon neu veröffentlicht wird |
| **Führt ein Dateisystem** | [Collections, Skills und angehängter Context](docs/file-processing.de.md) in Ihrem eigenen Postgres, mit Embeddings, die einen Schlüssel pro Organisation haben |
| **Gibt vielen Schnittstellen eine Shell** | Ein Runner hinter Web-Chat, der HTTP-API, Slack, Telegram, einem Widget, einer gehosteten Seite und einem Zeitplan. Dasselbe Budget, dasselbe Approval-Gate, dieselbe Audit-Spur |
| **Schreibt ein Audit-Log** - syslog, auditd | Wer was wann ausgeführt hat, was es gekostet hat und wer es freigegeben hat. Geschrieben auch dann, wenn der Run fehlgeschlagen ist |

Wenden Sie dieselben sieben auf alles andere in der Kategorie an. Das ist der
Test, an dem wir gemessen werden möchten, und
[Wann man etwas anderes nimmt](docs/about/comparison.de.md) ist die Stelle, an der
wir ihn gegen die Alternativen laufen lassen - einschließlich der Zeilen, in
denen die ehrliche Antwort hier "noch nicht" lautet.

**Wenden Sie nun dieselben sieben auf alles andere in der Kategorie an** —
einschließlich derer mit dem Tausendfachen unserer Sterne. Keines davon erklärt,
warum es ein Betriebssystem ist, denn die meisten sind ein Workspace mit den
Buchstaben auf der Verpackung. Das ist die ganze Behauptung: nicht, dass wir die
meisten Nutzer hätten, sondern dass wir die Einzigen sind, die die Kriterien
nennen und sie dann in Code erfüllen, den Sie lesen können.

Wo die ehrliche Antwort hier noch "noch nicht" lautet, ist es eine Zeile im
Vergleich unten und eine Zeile auf der [Roadmap](docs/ROADMAP.md).
[Wann man etwas anderes nimmt](docs/about/comparison.de.md) ist die lange Fassung,
einschließlich der Stellen, an denen dieses hier verliert, und
[was etwas zu einem Betriebssystem für Agents macht](docs/about/index.de.md) sind
die Kriterien für sich — nehmen Sie sie und bewerten Sie damit jeden, uns
eingeschlossen.

## Was ein Agent tun kann

Pro Agent eingeschaltet, im Builder. Jede bringt ihre eigenen Einstellungen mit,
ihren eigenen Permission-Scope und — wo sie auf die Außenwelt wirkt — ihr eigenes
Approval-Gate.

| | |
|---|---|
| **Aus Ihren Dokumenten antworten** | Retrieval über Collections in Ihrem eigenen Postgres, dazu [Skills](docs/skills.de.md), die er bei Bedarf lädt, und [Context-Dateien](docs/context.de.md), die über Agents hinweg gebunden sind |
| **Losgehen und nachsehen** | Websuche, eine einzelne Seite richtig abrufen oder einen **echten Browser** durch eine Site steuern, auf der geklickt werden muss |
| **Die Arbeit erledigen** | Python ausführen, eine [Sandbox](docs/sandbox.de.md) mit Dateien und einer Shell halten, Diagramme zeichnen, Bilder erzeugen |
| **Bewältigen, was für eine Antwort zu groß ist** | An Subagents delegieren, eine Aufgabenliste führen, länger nachdenken, ein langes Gespräch kompaktieren |
| **In den Linien bleiben** | Guardrails, die schwärzen oder blockieren, Ausgabe-Obergrenzen pro Tool, und die Uhr |
| **Alles Weitere** | [Jeder MCP-Server per URL](docs/mcp.de.md) - 5.802 im Katalog, 99 davon geprüft, mit verdrahteten OAuth-Flows, und kein Connector zu schreiben |

## Wo es antwortet

Einmal veröffentlichen. Derselbe Runner bedient sie alle, also hängt eine Antwort
nicht davon ab, woher die Frage kam.

| | |
|---|---|
| **Web-Chat** | In der Konsole, mit Anhängen und Slash-Kommandos |
| **Die Desktop-App** | Dieselbe Konsole in einem eigenen Fenster, mit einem Haustier und einem Screenshot-Kürzel - eine [optionale Hülle](docs/desktop.de.md), kein zweites Produkt |
| **Eine gehostete Seite** | `/e/{key}` - schicken Sie jemandem einen Link, kein Konto nötig |
| **Ein einbettbares Widget** | Auf Ihrer eigenen Site, mit Variablen aus der Adresszeile |
| **Die HTTP-API** | [Ein POST, und Sie haben eine Antwort](docs/api.de.md) |
| **Ein reiner WebSocket** | Streamen Sie Tokens in ein Frontend, das Sie selbst gebaut haben |
| **Slack, Telegram, Mattermost** | Wo eine `@mention` als **die Person läuft, die sie geschickt hat**, nicht als der Bot |
| **Zeitpläne und Trigger** | Eine Uhr, ein Webhook oder ein Postfach, das wir abfragen - [Routinen](docs/triggers.de.md) |

## Auf dem Desktop, wenn Sie mögen

Alles oben läuft in einem Browser, und so nutzen es die meisten. Für alle, die es
im Dock haben wollen, gibt es eine [Desktop-App](docs/desktop.de.md): eine dünne
Hülle um dieselbe Konsole - dieselbe Anmeldung, dieselben Permissions, nichts
mitgeliefert - mit zwei Dingen, die ein Browser-Tab nicht kann. Ein Haustier, das
auf dem Desktop lebt, während Sie arbeiten, und ein globales Kürzel (`⌘⇧A`), das
einen Screenshot eines beliebigen Ausschnitts macht und einen neuen Chat damit
als Anhang öffnet.

<div align="center">

<img src="docs/assets/desktop_no_more_caramba_pet.png" alt="Amigo, das Desktop-Haustier, mit Sombrero, sagt: No more caramba." width="270">

<sub>Amigo, eines von fünf Haustieren. Ziehen Sie es, klicken Sie es an, streicheln Sie es; Rechtsklick öffnet sein Menü. <b>No more caramba in your AI.</b></sub>

</div>

## Im Vergleich mit den Alternativen

Als Einziges davon lässt es sich vollständig auf Infrastruktur betreiben, die
Ihnen bereits gehört, mit Agents, die ein Nicht-Entwickler bearbeitet und ein
Buchhalter prüfen kann.

| | **AgenticOS** | Cloudflare&nbsp;OS | Glean | Eine&nbsp;Bibliothek |
|---|:---:|:---:|:---:|:---:|
| Open Source | ✅ Apache-2.0 | ✅ Apache-2.0 | — | ✅ |
| **Läuft auf gewöhnlicher Infrastruktur** (Postgres, Redis, Docker) | ✅ | — | — | ✅ |
| Läuft air-gapped, ohne Anbieterkonto | ✅ | — | — | ✅ |
| Lokale Modelle (Ollama, LiteLLM) | ✅ | ✅ | — | ✅ |
| Agent, von einem Nicht-Entwickler gebaut und bearbeitet | ✅ | ~ | ✅ | — |
| Beim Veröffentlichen versioniert, in Ihr git exportierbar | ✅ | ~ | — | — |
| Budget, das einen Run vor dem Modellaufruf stoppt | ✅ | ~ | ~ | DIY |
| Approval durch einen Menschen bei Tools mit Nebenwirkung | ✅ | ✅ | ~ | DIY |
| Mandantentrennung im Schema | ✅ | ~ | ✅ | DIY |
| Secret-Vault pro Organisation | ✅ | ✅ | ✅ | DIY |
| **Jeder MCP-Server per URL, 5.802 im Katalog** | ✅ | ✅ | ~ | ~ |
| **Slack, Telegram, Widget, gehostete Seite und API aus einem Runner** | ✅ | — | ~ | DIY |
| ACL-bewusste Connectors zu 275+ SaaS-Systemen | — | ~ | ✅ | — |
| Evaluations-Harness | — | — | ✅ | ~ |
| SAML / SCIM | — | ✅ | ✅ | — |

<sub>✅ erstklassig · ~ teilweise oder über Konfiguration · — nicht verfügbar · DIY Sie verdrahten es selbst.
"Eine Bibliothek" meint LangGraph, Pydantic AI oder Ähnliches. Gibt jedes Projekt mit Stand 2026-08 wieder;
Korrekturen gern per PR. Die letzten drei Zeilen sind unsere Aufgabe und stehen auf der
<a href="https://github.com/vstorm-co/agenticos/blob/main/docs/ROADMAP.md">Roadmap</a>.</sub>

## Warum es das gibt

Die meisten Agent-Frameworks geben Ihnen eine Bibliothek. Sie schreiben Python,
Sie deployen es, und jede Änderung am Verhalten eines Agents ist ein Pull
Request, ein Review und ein Release. Das ist die richtige Form für ein
Produktfeature und die falsche Form für die vierzig kleinen Agents, die ein
Unternehmen tatsächlich will — denn wer weiß, was der Agent sagen soll, ist nicht
die Person mit Commit-Zugang.

AgenticOS holt den Agent aus dem Code heraus und legt stattdessen Governance um
ihn herum. [Secrets](docs/secrets.de.md) werden pro Organisation versiegelt: ein
Schlüssel, der aus der Datenbankzeile eines Mandanten kopiert wurde, lässt sich
für einen anderen nicht entschlüsseln, und keine API-Antwort gibt jemals einen
zurück.

## Dokumentation

| | |
|---|---|
| [Installation](docs/install.de.md) · [Ihr erster Agent](docs/first-agent.de.md) | Von nichts zu einem Agent, der antwortet |
| [Konzepte](docs/concepts.de.md) | Spec, Version, Exposure, Trigger, Run — die fünf Substantive |
| [Permissions](docs/permissions.de.md) · [Governance](docs/governance.de.md) | Wer was darf; Budgets, Approvals, Audit |
| [Capabilities](docs/reference/capabilities.de.md) · [MCP](docs/mcp.de.md) | Was ein Agent tun kann, und wie man ein Tool hinzufügt |
| [Modelle](docs/models.de.md) · [Secrets](docs/secrets.de.md) | Provider, Profile, Kosten; der Vault |
| [Wissen](docs/file-processing.de.md) · [Skills](docs/skills.de.md) | Parser, Chunking, OCR; aufgeschriebenes Können |
| [Channels](docs/channels.de.md) · [API](docs/api.de.md) | Slack, Telegram, Widget, WebSocket, HTTP |
| [Desktop-App](docs/desktop.de.md) | Die optionale Hülle: die Konsole in einem Fenster, das Haustier, das Screenshot-Kürzel |
| [Architektur](docs/architecture.de.md) · [Tests](docs/testing.de.md) | Wie es gebaut ist, und wie es verifiziert wird |

Gebaut mit MkDocs: `make docs` liefert sie auf :8001 aus. Der Stack, in einer
Zeile: FastAPI + Pydantic v2, PostgreSQL mit pgvector, Redis, Prefect,
[Pydantic AI](https://ai.pydantic.dev), Next.js 15. Nichts funkt nach Hause — die
einzigen ausgehenden Anfragen sind die, die Ihre Agents stellen.

## Mitwirken

`make check` vor einem Pull Request: jeder CI-Job außer e2e, etwa fünf Minuten.
Neues Verhalten geht mit einem Test raus; ein Bug geht mit einem Regressionstest
raus. Die **Plattformschicht wird bei 100% Coverage gehalten**, und CI schlägt
darunter fehl.

Drei Dinge, über die eine erste Änderung stolpert: ein Tool ist Code und ein
Agent ist keiner (es gibt kein `@agent.tool` — eine Capability registriert sich,
und danach ist sie ein Schalter im Builder von allen); `require(...)`-Gates
kommen nur an Collection-Routen; und wenn es das Tool schon als MCP-Server gibt,
schreiben Sie keines.
[CONTRIBUTING.md](CONTRIBUTING.md) hat den Rest, [`.claude/`](.claude/README.md)
hat dieselben Konventionen für eine Maschine geschrieben, und gute erste Issues
sind [hier gekennzeichnet](https://github.com/vstorm-co/agenticos/labels/good%20first%20issue).

<details>
<summary><b>Der Rest des Vstorm-OSS-Ökosystems</b></summary>

Alles unten läuft auf [Pydantic AI](https://ai.pydantic.dev).

| Projekt | Was es ist | |
|---|---|---|
| **[full-stack-ai-agent-template](https://github.com/vstorm-co/full-stack-ai-agent-template)** | Der Generator, aus dem AgenticOS gebaut wurde — FastAPI + Next.js 15, RAG, Streaming, Auth, 20+ Integrationen | [![Stars](https://img.shields.io/github/stars/vstorm-co/full-stack-ai-agent-template?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/full-stack-ai-agent-template) |
| **[pydantic-deepagents](https://github.com/vstorm-co/pydantic-deepagents)** | Quelloffenes, selbst gehostetes Claude Code — ein Terminal-Assistent und das Framework dahinter | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-deepagents?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-deepagents) |
| **[pydantic-ai-shields](https://github.com/vstorm-co/pydantic-ai-shields)** | Guardrails — Kostenverfolgung, Erkennung von Prompt Injection, PII-Filterung, Schwärzen von Secrets | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-shields?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-shields) |
| **[subagents-pydantic-ai](https://github.com/vstorm-co/subagents-pydantic-ai)** | Verschachtelte Delegation an Subagents, parallele Ausführung, Abbruch von Aufgaben | [![Stars](https://img.shields.io/github/stars/vstorm-co/subagents-pydantic-ai?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/subagents-pydantic-ai) |
| **[pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend)** | Dateiablage und durch Docker isolierte Sandboxes, mit einem Permission-System | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-backend?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-backend) |
| **[pydantic-ai-todo](https://github.com/vstorm-co/pydantic-ai-todo)** | Hierarchische Aufgabenplanung mit PostgreSQL-Speicher und einem Event-System | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-todo?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-todo) |
| **[production-stack-skills](https://github.com/vstorm-co/production-stack-skills)** | Skill-Paket, das einen Coding-Agent zu einem erfahrenen Production Engineer macht | [![Stars](https://img.shields.io/github/stars/vstorm-co/production-stack-skills?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/production-stack-skills) |
| **[content-skills](https://github.com/vstorm-co/content-skills)** | Skill-Paket für ein Content-Studio für Coding-Agents — markenbewusst, mit eingebautem Anti-Slop | [![Stars](https://img.shields.io/github/stars/vstorm-co/content-skills?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/content-skills) |

Alle im Überblick unter **[oss.vstorm.co](https://oss.vstorm.co)**.

Alle im Überblick unter **[oss.vstorm.co](https://oss.vstorm.co)**.

</details>

## Lizenz

Apache License 2.0 - siehe [`LICENSE`](LICENSE) und [`NOTICE`](NOTICE).
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) listet jede Komponente auf, die
die Images ausliefern, samt ihrer Lizenz; die Prüfung dessen, wozu diese Lizenzen
verpflichten, und die noch offenen Befunde stehen in [der Dokumentation](https://vstorm-co.github.io/agenticos/licenses/).

Apache-2.0 statt MIT, weil AgenticOS dafür gedacht ist, in anderen Unternehmen
deployt zu werden: die ausdrückliche Patentlizenz ist der Teil, nach dem deren
Rechtsprüfung fragt, und MIT schweigt dazu.

---

<div align="center">

### Brauchen Sie Hilfe, Agents in Produktion zu bringen?

<p>
Wir sind <a href="https://vstorm.co"><b>Vstorm</b></a> — eine Beratung für angewandtes
Agentic-AI-Engineering mit 30+ Agent-Implementierungen in Produktion.<br>
AgenticOS ist das, worauf wir sie bauen, und wir deployen es in der Infrastruktur
unserer Kunden: Ihre Cloud, Ihr Rechenzentrum oder air-gapped.
</p>

<a href="https://vstorm.co/contact-us/">
  <img src="https://img.shields.io/badge/Talk%20to%20us%20%E2%86%92-0066FF?style=for-the-badge&logoColor=white" alt="Talk to us">
</a>

<br><br>

Built with care by <a href="https://vstorm.co"><b>Vstorm</b></a> ·
<a href="https://oss.vstorm.co">oss.vstorm.co</a>

</div>
