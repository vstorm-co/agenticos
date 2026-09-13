---
source_sha: df924dfc3bb7
---

<div class="agenticos-hero" markdown>

![AgenticOS](assets/mark.svg){ .agenticos-hero__mark }

<p class="agenticos-hero__name">AgenticOS</p>

<p class="agenticos-hero__tagline">
Ein Ort, um die KI-Agents Ihres Unternehmens zu bauen, zu betreiben und zu steuern. Selbst gehostet, Open Source und Ihres.
Warum es ein Betriebssystem heißt, steht
<a href="#why-it-is-called-an-operating-system">sieben Funktionen weiter unten</a>.
</p>

<p class="agenticos-hero__badges">
<a href="https://github.com/vstorm-co/agenticos/actions"><img src="https://img.shields.io/github/actions/workflow/status/vstorm-co/agenticos/ci.yml?branch=main&label=tests" alt="Tests"></a>
<a href="https://github.com/vstorm-co/agenticos/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="Licence"></a>
<a href="https://github.com/vstorm-co/agenticos"><img src="https://img.shields.io/github/stars/vstorm-co/agenticos?style=flat" alt="Stars"></a>
<img src="https://img.shields.io/badge/python-3.12-blue" alt="Python 3.12">
</p>

<p class="agenticos-hero__links" markdown>
**Dokumentation**: <a href="https://vstorm-co.github.io/agenticos/">vstorm-co.github.io/agenticos</a><br>
**Quellcode**: <a href="https://github.com/vstorm-co/agenticos">github.com/vstorm-co/agenticos</a>
</p>

</div>

---

AgenticOS ist eine selbst gehostete, mandantenfähige Plattform, um die KI-Agents
eines Unternehmens zu bauen, zu steuern und zu betreiben.

Der entscheidende Punkt ist dieser:

!!! quote "Code definiert, Konfiguration setzt zusammen"

    Ein Fachteam setzt Agents im Browser zusammen — Instruktionen, ein Modell,
    eine Auswahl an Capabilities, ein Budget — und das Ergebnis läuft überall
    gleich: Web-Chat, HTTP-API, Slack, Telegram, ein eingebettetes Widget. Die
    Konsole selbst ist eine Web-App; die [Desktop-App](desktop.md) ist dieselbe
    Konsole in einem eigenen Fenster, eine Ergänzung für alle, die sie im Dock
    haben wollen.

    Entwickler erweitern das, was sich zusammensetzen lässt, in typisiertem
    Python. Konfiguration erreicht immer nur das, was Code registriert hat, und
    genau das macht einen No-Code-Builder sicher genug, um ihn jemandem in die
    Hand zu geben, der kein Entwickler ist.

Alles andere auf dieser Website folgt aus diesem einen Satz. Die Obergrenze ist
keine Konfigurationsdatei — sie ist das, was Ihre Entwickler in die Registry
legen, und der Quellcode gehört Ihnen.

## Fangen Sie dort an, wo Sie stehen { #start-where-you-are }

<div class="grid cards" markdown>

- :material-rocket-launch:{ .lg .middle } **Ich will es ausprobieren**

    [Die Installation](install.md) braucht vier Befehle, danach ist
    [Ihr erster Agent](first-agent.md) in etwa zehn Minuten einsatzbereit.

- :material-account-tie:{ .lg .middle } **Ich entscheide, ob wir es einführen**

    [Einführung](rollout.md) — wer was macht, was es kostet und welche Fragen
    Ihre Sicherheitsprüfung stellen wird. Ohne Terminal.

- :material-code-braces:{ .lg .middle } **Ich will es integrieren**

    [Die HTTP-API](api.md), um es aufzurufen, [MCP](mcp.md), um Agents Ihre
    Tools zu geben, und [der Code der Konsole](frontend.md), falls Sie die UI
    ändern.

- :material-cog:{ .lg .middle } **Ich betreibe es bereits, und etwas stimmt nicht**

    [Die Konsole](console.md) zeigt jeden Bildschirm, und das *Fazit* jeder
    Seite ist die Kurzfassung. [Konfiguration](configuration.md) sind alle
    Einstellungen.

</div>

## Warum es ein Betriebssystem heißt { #why-it-is-called-an-operating-system }

Weil das Wort Arbeit leistet. Ein Betriebssystem führt Prozesse aus und isoliert
sie, erzwingt Ressourcengrenzen, kontrolliert Zugriffe, erreicht Hardware über
Treiber, führt ein Dateisystem, gibt vielen Schnittstellen eine Shell und
schreibt ein Audit-Log.

AgenticOS tut jedes davon für Agents: Runs, Budgets, die vor der Modellanfrage
geprüft werden, ein Permission-Katalog mit Approvals als seinem `sudo`, MCP und
Modellprofile als seine Treiber, Collections in Ihrem eigenen Postgres, ein
Runner hinter jeder Oberfläche und eine Audit-Spur, die auch dann geschrieben
wird, wenn ein Run fehlschlägt.

[Die sieben, einzeln, mit dem, was bei jedem anderen Produkt zu prüfen ist →](about/index.md#what-makes-something-an-operating-system-for-agents)

## Warum es das gibt { #why-it-exists }

Die meisten Agent-Frameworks geben Ihnen eine Bibliothek. Sie schreiben Python,
Sie deployen es, und jede Änderung am Verhalten eines Agents ist ein Pull
Request, ein Review und ein Release.

Das ist die richtige Form für ein Produktfeature. Es ist die falsche Form für die
vierzig kleinen Agents, die ein Unternehmen tatsächlich will, denn **wer weiß,
was der Agent sagen soll, ist nicht die Person mit Commit-Zugang.**

Also holt AgenticOS den Agent aus dem Code heraus und legt stattdessen Governance
um ihn herum.

<div class="grid cards" markdown>

- :material-shield-check:{ .lg .middle } **Budgets, die einen Run stoppen**

    Geprüft *vor* jeder Modellanfrage, nicht danach. Ein Run, der fehlschlägt,
    verzeichnet trotzdem, was er gekostet hat, denn ein Budget, das Fehlschläge
    ignoriert, ist kein Budget.

- :material-hand-back-right:{ .lg .middle } **Approval für alles mit Nebenwirkung**

    Ein Tool, das auf die Außenwelt wirkt, parkt den Run und wartet auf einen
    Menschen. Pro Capability gesetzt, pro Tool überschreibbar.

- :material-account-key:{ .lg .middle } **Permissions in Code, Rollen daraus zusammengesetzt**

    Aufrufstellen prüfen Permissions, niemals Rollennamen. Ein Grant weitet aus,
    was eine Person mit einer Zeile tun darf; er engt nie ein.

- :material-database-lock:{ .lg .middle } **Mandantentrennung im Schema**

    Nicht nur in der Service-Schicht. Ein Chiffrat aus einer Organisation lässt
    sich für eine andere nicht entschlüsseln.

</div>

## Voraussetzungen { #requirements }

Docker und Docker Compose. Das ist die ganze Liste — Postgres (mit pgvector),
Redis, die API, der Worker und die Konsole starten gemeinsam.

Sie wollen die Dienste lieber von Hand betreiben? Python 3.12, Node mit
[bun](https://bun.sh), PostgreSQL 16 mit
[pgvector](https://github.com/pgvector/pgvector) und Redis.

## Installation { #installation }

```bash
git clone https://github.com/vstorm-co/agenticos.git
cd agenticos
make dev
```

Das startet Postgres, Redis, die API, den Worker und das Frontend.

Legen Sie dann eine Organisation, einen Owner, ein Modell und einen ersten Agent
an:

```bash
make platform-bootstrap BOOTSTRAP_API_KEY=sk-...
```

Und öffnen Sie die Konsole:

```bash
open http://localhost:3000
```

Melden Sie sich mit `admin@example.com` / `admin123` an.

!!! tip

    Nicht sicher, ob das Deployment wirklich einen Agent ausführen kann? Fragen
    Sie es.

    ```bash
    uv run agenticos cmd doctor
    ```

## Woraus ein Agent besteht { #what-an-agent-is-made-of }

Sechs Entscheidungen, und keine davon ist Code. Wer weiß, was der Agent sagen
soll, trifft alle sechs im Browser; das Veröffentlichen friert die Kombination
als Version ein, und diese Version ist es, die antwortet.

| | Was es entscheidet |
|---|---|
| **Instruktionen** | Was der Agent tut, in klarer Sprache — und was er verweigern soll |
| **Ein Modellprofil** | Welches Modell antwortet, mit welchen Parametern, und worauf es bei einem Ausfall zurückfällt |
| **Capabilities** | Was er überhaupt tun darf: Ihr Wissen durchsuchen, eine Seite lesen, Python ausführen, ein Diagramm zeichnen |
| **Wissen** | Welche Collections er durchsuchen darf, und nichts außerhalb davon |
| **Approval** | Welche dieser Aktionen auf einen Menschen warten, bevor sie die Außenwelt berühren |
| **Ein Budget** | Was er in einem Monat ausgeben darf, geprüft *vor* jeder Anfrage statt danach gezählt |

Ändern Sie eines davon, und es geht nichts live, bis Sie veröffentlichen. Die
Version, die live war, bleibt lesbar, also hat *wie sah dieser Agent im März aus*
eine Antwort.

=== "Was jemand bearbeitet"

    ![Agents — jeder mit der Version, die live ist, und wer ihn erreichen darf](assets/screens/light/agents.webp#only-light)
    ![Agents — jeder mit der Version, die live ist, und wer ihn erreichen darf](assets/screens/dark/agents.webp#only-dark)

=== "Was daraus wird"

    Eine eingefrorene Version und eine Datei, die Sie in Ihr eigenes
    git-Repository exportieren, in einem Pull Request prüfen und wiederherstellen
    können:

    ```yaml
    name: Support Copilot
    instructions: |
      Answer from the product wiki and cite the document you used.
      If the wiki does not cover it, say so rather than guessing.
    model_profile_id: 8f1c...
    capabilities:
      - id: knowledge
        config: { default_top_k: 8 }
      - id: web_research
        approval: required
    collection_ids: [b2a9...]
    budget:
      monthly_usd: 50
    ```

## Probieren Sie es aus { #check-it }

Veröffentlichen Sie ihn, und er läuft auf jeder Oberfläche gleich: im Chat der
Konsole, auf einer gehosteten Seite, in einem eingebetteten Widget, über die
HTTP-API, in Slack, Telegram, Mattermost.

```bash
curl -X POST http://localhost:8000/api/v1/agents/$AGENT_ID/run \
    -H "Authorization: Bearer $TOKEN" \
    -H "X-Organization-Id: $ORG_ID" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "How do I rotate a provider key?"}'
```

Hinter allen steht ein Runner, also hängt eine Antwort nicht davon ab, woher die
Frage kam.

## Was Sie bekommen { #what-you-get }

| | |
|---|---|
| **Agents** | In einer UI gebaut, beim Veröffentlichen versioniert, als YAML in Ihr eigenes git-Repository exportierbar |
| **[Capabilities](reference/capabilities.md)** | Retrieval, Websuche und Abruf, ein echter Browser, Python, eine Sandbox mit Dateien und Shell, Diagramme, Bilder, Delegation, Planung, Guardrails — pro Agent eingeschaltet |
| **[Integrationen](mcp.md)** | Jeder MCP-Server per URL, mit 59 gängigen im Picker — GitHub, Linear, Notion, Slack, Stripe, Postgres |
| **[Modelle](models.md)** | 27 Provider, Schlüssel pro Organisation, Fallbacks und selbst gehostetes Ollama oder ein LiteLLM-Proxy |
| **[Wissen](file-processing.md)** | Retrieval über Ihre Dokumente mit drei PDF-Parsern, Ihrem eigenen Chunking, OCR und Bildbeschreibung — pro Collection, pro Upload überschreibbar. Google-Drive- und S3-Sync |
| **[Skills](skills.md)** | Aufgeschriebenes Know-how, das der Agent nur lädt, wenn er es für relevant hält |
| **[Governance](governance.md)** | Monatsbudgets, menschliche Approval, eine Audit-Spur, Alerts pro Agent |
| **[Oberflächen](channels.md)** | Web-Chat, eine gehostete Seite ohne Login, ein einbettbares Widget, die HTTP-API, ein rohes WebSocket für Ihr eigenes Frontend, Slack, Telegram, Mattermost — ein Runner hinter allen |
| **[Secrets](secrets.md)** | Pro Organisation versiegelt. Keine Antwort, keine Logzeile und kein Audit-Eintrag trägt je einen Schlüssel im Klartext |

[Die vollständige Liste der Funktionen →](features.md)

## Fazit { #recap }

- Ein Agent ist **eine Datei**, kein Modul. Instruktionen, ein Modell,
  Capabilities, ein Budget.
- Er wird **als Version veröffentlicht**, und diese Version ist es, die läuft.
- Er ist **als YAML exportierbar** in Ihr Repository, prüfbar in einem Pull
  Request.
- Er ist **gesteuert**: Budgets, die einen Run stoppen, Approvals, die auf einen
  Menschen warten, Permissions, die an jeder Aufrufstelle geprüft werden.
- Er gehört **Ihnen**: Ihr Postgres, Ihre Hardware, nichts telefoniert nach
  Hause.

## Weiter { #next }

<div class="grid cards" markdown>

- :material-school:{ .lg .middle } **[Lernen](learn/index.md)**

    Der empfohlene Weg hindurch, der Reihe nach: Installation, erster Agent,
    Konzepte, dann die einzelnen Teile.

- :material-star-four-points:{ .lg .middle } **[Funktionen](features.md)**

    Alles, was die Plattform tut, auf einer Seite.

- :material-book-open-variant:{ .lg .middle } **[Referenz](configuration.md)**

    Einstellungen, CLI-Befehle, der Agent-Spec, die Kataloge für Capabilities
    und Permissions.

- :material-account-group:{ .lg .middle } **[Einführung](rollout.md)**

    Für alle, denen die Entscheidung gehört und nicht die Installation: wer was
    macht, was es kostet und was Ihre Sicherheitsprüfung fragen wird.

- :material-information-outline:{ .lg .middle } **[Über AgenticOS](about/index.md)**

    Warum es das gibt, was es absichtlich nicht ist, und die sechs
    Entscheidungen, die es prägen.

</div>

## Stack { #stack }

FastAPI und Pydantic v2 auf PostgreSQL, [Pydantic AI](https://ai.pydantic.dev)
für die Agent-Laufzeit, pgvector für Retrieval, Prefect für Hintergrundarbeit und
Next.js 15 für die Konsole.

Nichts hier telefoniert nach Hause: Modellpreise stammen aus einem beiliegenden
Snapshot, und die einzigen ausgehenden Aufrufe sind die, die Ihre Agents machen.

## Lizenz { #licence }

Apache-2.0. Siehe
[`LICENSE`](https://github.com/vstorm-co/agenticos/blob/main/LICENSE).
