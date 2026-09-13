---
source_sha: bf54d6dd6a38
---

# Funktionen { #features }

AgenticOS gibt Ihnen Folgendes an die Hand.

## Code definiert, Konfiguration setzt zusammen { #code-defines-configuration-composes }

Dieser eine Satz ist der ganze Entwurf, und er beschreibt zwei Hälften, die
absichtlich nicht dieselbe Aufgabe sind.

**Ein Fachteam setzt Agents im Browser zusammen.** Instruktionen, ein Modell,
eine Auswahl an Capabilities, ein Budget — kein Python, kein Pull Request, kein
Release. Der Spec ist ein Dokument, also bekommt er beim Veröffentlichen eine
Version und lässt sich als YAML in Ihr eigenes git-Repository exportieren.

Mehr als einen Browser braucht die Konsole nicht. Die
[Desktop-App](desktop.md) hüllt dieselbe Konsole für alle ein, die sie im Dock
haben wollen - mit einem Haustier und einem Screenshot-Kürzel - und ist eine
Ergänzung, kein zweiter Weg, die Plattform zu betreiben.

**Entwickler erweitern das, was sich zusammensetzen lässt.** Eine Capability ist
typisiertes, getestetes Python in diesem Repository: ein Tool, das das Modell
aufrufen kann, ein Guardrail, eine Kompaktierungsstrategie, ein Connector. Sie
fügen eine hinzu, und von diesem Moment an ist sie ein Schalter im Builder von
allen.

Die Regel zwischen den beiden Hälften ist der tragende Teil:

!!! quote "Konfiguration erreicht immer nur das, was Code registriert hat"

    Genau das macht einen No-Code-Builder sicher genug, um ihn jemandem in die
    Hand zu geben, der kein Entwickler ist. Diese Person kann kein Tool
    erfinden, keinen Scope ausweiten und kein System erreichen, das niemand
    verdrahtet hat — das Schlimmste, was sie tun kann, ist, bereits freigegebene
    Dinge zusammenzustellen.

Die Obergrenze ist also keine Konfigurationsdatei. Sie ist das, was Ihre
Entwickler in die Registry legen, und die Plattform steht unter Apache-2.0 —
also gehört alles dazu, was Sie für Ihren eigenen Anwendungsfall schreiben.

| Sie wollen | Sie tun |
|---|---|
| Eine andere Antwort von einem Agent | Die Instruktionen bearbeiten und veröffentlichen. Sekunden, kein Entwickler |
| Ein Tool für ein SaaS-Produkt | Auf [einen MCP-Server](mcp.md) zeigen. Meist gar kein Code |
| Ein Tool, das noch niemand geschrieben hat | [Eine Capability hinzufügen](howto/add-capability.md) — typisiertes Python, und es erscheint im Builder |
| Eine andere Ingestion, einen anderen Channel oder Connector | [Die Plattform erweitern](resources/index.md#extending-the-platform); jedes Mal dasselbe Muster |
| Das Ganze auf einen Prozess zugeschnitten | Forken Sie es. Es ist Ihr Deployment und Ihr Quellcode |

!!! tip "Die Trennung ist der Punkt"

    Wer weiß, was der Agent sagen soll, ist selten die Person mit Commit-Zugang
    — und wer ein Tool schreiben kann, sollte seine Woche nicht mit
    Formulierungsänderungen verbringen. Diese Linie lässt beide arbeiten, ohne
    auf die andere Seite zu warten.

!!! info "Warum das ein Betriebssystem heißt"

    Weil das Wort eine Spezifikation ist und kein Etikett: Prozesse,
    Ressourcengrenzen, Zugriffskontrolle, Treiber, ein Dateisystem, eine Shell
    für viele Schnittstellen und ein Audit-Log. Zu jedem davon gibt es auf
    dieser Seite einen Mechanismus.
    [Die sieben, und wie man jedes andere Produkt daran misst →](about/index.md#what-makes-something-an-operating-system-for-agents)

## In einer UI gebaut, beim Veröffentlichen versioniert { #built-in-a-ui-versioned-on-publish }

Sie bauen den Agent im Browser. Beim Veröffentlichen wird der Spec als Version
eingefroren, und diese Version ist es, die läuft — ein Entwurf, an dem Sie noch
arbeiten, erreicht niemanden.

Jede veröffentlichte Version bleibt lesbar, also ist *wie sah dieser Agent im
März aus* eine Frage mit einer Antwort.

## Exportierbar in Ihr eigenes Repository { #exportable-into-your-own-repository }

Der Spec exportiert als YAML. Committen Sie ihn, prüfen Sie ihn in einem Pull
Request, vergleichen Sie zwei Versionen, stellen Sie eine wieder her. Es ist Ihre
Datei, in Ihrer git-Historie, in einem Format, das AgenticOS nicht braucht, um
gelesen zu werden.

Der Import geht den umgekehrten Weg, also ist ein von Hand geschriebener Spec ein
vollwertiger Agent.

## Was ein Agent tatsächlich tun kann { #what-an-agent-can-actually-do }

Sie entscheiden das, indem Sie im Builder einzelne Dinge einschalten. Nichts
davon ist ein Plugin, das jemand installiert, eine Python-Datei, die jemand
deployt, oder ein Prompt, dem das Modell hoffentlich folgt — ein Agent kann keine
Capability erreichen, die ausgeschaltet ist, ganz gleich, was seine Instruktionen
sagen.

| Der Agent kann… | Einschalten |
|---|---|
| **Aus dem antworten, was Ihr Unternehmen weiß** — Ihre Dokumente, Ihre schriftlichen Abläufe und was auch immer an diese Unterhaltung angehängt wurde | Knowledge search · Skills · Context |
| **Sich erinnern und nachschlagen** — Notizen über Unterhaltungen hinweg führen, eine Tatsache dem Sinn nach abrufen oder finden, was in einer früheren Unterhaltung tatsächlich gesagt wurde, und es nachlesen | Memory files · Memory (mem0) · Conversation search |
| **Losziehen und es herausfinden** — im Web suchen, eine Seite richtig lesen oder einen echten Browser durch eine Website steuern, die Klicks verlangt | Web search · Web fetch · Browser automation |
| **Die Arbeit erledigen, statt sie zu beschreiben** — Python über eine Datei laufen lassen, einen Workspace mit einer Shell führen, ein Diagramm zeichnen, ein Bild erzeugen | Run Python · Files & shell · Charts · Image generation |
| **Arbeit bewältigen, die für eine Antwort zu groß ist** — an Spezialisten delegieren, eine Aufgabenliste führen, vor der Antwort länger nachdenken, eine lange Unterhaltung führen, ohne ihren Anfang zu verlieren | Delegation · Planning · Thinking · Context management |
| **Innerhalb der Linien bleiben** — schwärzen oder blockieren, was nicht durch darf, begrenzen, was ein Tool zurückgeben darf, wissen, welches Datum heute ist | Guardrails · Tool output limits · Date and time |

Jede bringt ihre eigenen Einstellungen mit, ihren eigenen Permission-Scope und —
wo sie auf die Außenwelt wirkt — ihre eigene Approval-Einstellung. Eine
einzuschalten ist eine Entscheidung über *diesen* Agent, keine Änderung an der
Plattform.

[Jede Capability, ihre Tools und ihre Konfiguration →](reference/capabilities.md)

## Jedes Modell, von 27 Providern { #any-model-from-27-providers }

OpenAI, Anthropic, Google, Groq, Mistral, Bedrock, Vertex, ein Ollama auf Ihrer
eigenen Hardware, ein LiteLLM-Proxy vor allem zusammen.

Ein **Modellprofil** benennt das Modell, seine Parameter und seine Fallbacks;
Agents zeigen auf das Profil. Ändern Sie das Profil, und jeder Agent, der es
nutzt, zieht mit — ohne dass ein einziger Spec neu veröffentlicht wird.

Schlüssel gelten pro Organisation, sind im Vault versiegelt und werden von keinem
Endpunkt je zurückgegeben.

[Modelle und Provider →](models.md)

## Jeder MCP-Server, per URL { #any-mcp-server-by-url }

Verbinden Sie einen Server, und seine Tools erscheinen in der Toolbox — mit
Namensraum, damit zwei Server, die beide `search` anbieten, nicht kollidieren.

**5.802 Server stehen im Picker.** 99 der gängigen — GitHub, Linear, Notion,
Slack, Stripe, Postgres — kommen mit bereits verdrahteten OAuth-Flows, weil hier
jemand jeden davon verbunden und geprüft hat. Die übrigen 5.703 sind aus dem
öffentlichen MCP-Register gespiegelt und nach Namen durchsuchbar: die hat hier
niemand geprüft, und die Liste sagt, welcher Art eine Zeile ist.

!!! info

    Deshalb ist der Capability-Katalog kurz und bleibt es. Eine Integration mit
    einem SaaS-Produkt ist eine MCP-Verbindung, kein Python-Modul, das jemand in
    diesem Repository gegen die API dieses Produkts pflegen muss.

[MCP-Verbindungen →](mcp.md)

## Wissen, das auf Ihrer Hardware bleibt { #knowledge-that-stays-on-your-hardware }

Laden Sie Dokumente hoch oder synchronisieren Sie einen Google-Drive-Ordner oder
einen S3-Bucket. AgenticOS parst sie, zerteilt sie in Chunks, bettet sie in
pgvector ein und behält sie in *Ihrem* Postgres.

**Wie es sie liest, entscheiden Sie** — pro Collection und pro Upload
überschreibbar, was ungewöhnlich ist und der Punkt, an dem Retrieval-Qualität
tatsächlich gewonnen wird:

| | |
|---|---|
| **PDF-Parser** | `pymupdf` — lokal, schnell und der einzige, der eingebettete Bilder für eine Beschreibung extrahiert · `liteparse` — lokal und layoutbewusst, hält Tabellen als ASCII-Raster, statt sie plattzumachen · `llamaparse` — ein Cloud-Dienst, pro Seite abgerechnet, der Markdown zurückgibt |
| **Chunking** | `recursive`, `markdown` oder `fixed`, mit Ihrer eigenen Größe und Überlappung |
| **OCR** | Auf Wunsch oder automatisch, mit einer Sprache |
| **Bilder in Dokumenten** | Beschrieben von einem Modellprofil Ihrer Wahl, mit Ihrem eigenen Prompt |

Embeddings tragen einen Schlüssel pro Organisation. Ein Vektor, der für einen
Mandanten geschrieben wurde, kann von einem anderen nicht gelesen werden, und das
erzwingt das Schema statt einer `WHERE`-Klausel, an die sich jemand erinnern
muss.

Das Embedding-Modell steht fest, sobald eine Collection angelegt ist, denn zwei
Modelle gleicher Breite schreiben in verschiedene Räume, die die Suche weiterhin
vergleichen würde.

[Dateiverarbeitung →](file-processing.md) · [Skills →](skills.md)

## Ein Agent, jede Oberfläche { #one-agent-every-surface }

Einmal veröffentlichen. Derselbe Runner antwortet auf all diesen:

- **Web-Chat** in der Konsole
- **Eine gehostete Seite**, auf die Sie jemandem einen Link schicken können
- **Ein einbettbares Widget** für Ihre eigene Website
- **Die HTTP-API** und ein rohes WebSocket für Streaming
- **Slack**, **Telegram** und **Mattermost**, wo eine `@mention` als die Person
  läuft, die sie geschickt hat — nicht als der Bot

[Oberflächen →](channels.md)

## Budgets, die einen Run wirklich stoppen { #budgets-that-actually-stop-a-run }

Geprüft **vor** jeder Modellanfrage, nicht hinterher zusammengezählt.

Ein Run, der fehlschlägt, verzeichnet trotzdem, was er gekostet hat, denn ein
Budget, das nur Erfolge zählt, ist kein Budget. Alerts feuern bei Schwellen, die
Sie setzen, pro Agent.

## Approval für alles mit Nebenwirkung { #approval-for-anything-side-effecting }

Ein Tool, das die Außenwelt verändert, parkt den Run und wartet auf einen
Menschen. Stellen Sie es pro Capability ein, überschreiben Sie es pro Tool.

Eine Approval wird einmal entschieden. Eine zweite Entscheidung über eine bereits
entschiedene Approval wird abgelehnt — was selbstverständlich klingt, bis man die
Race Condition gesehen hat, die es nötig macht.

[Governance →](governance.md)

## Permissions in Code, Rollen daraus zusammengesetzt { #permissions-in-code-roles-composed-from-them }

Aufrufstellen prüfen Permissions, niemals Rollennamen. Eine Rolle ist eine Menge
von Permissions aus einem Katalog, und ein **Grant** weitet aus, was eine Person
mit einer Zeile tun darf.

Ein Grant engt nie ein. Ein Viewer mit einem ausdrücklichen `edit`-Grant auf einem
Agent kann diesen Agent bearbeiten — und sonst nichts.

[Berechtigungen →](permissions.md)

## Secrets, pro Organisation versiegelt { #secrets-sealed-per-organization }

Provider-Schlüssel, Bot-Token, MCP-Zugangsdaten — ein Mechanismus,
`app/core/vault.py`, und absichtlich kein zweiter.

Ein Chiffrat, das aus der Datenbankzeile eines Mandanten kopiert wurde, lässt
sich für einen anderen nicht entschlüsseln. Keine Antwort, keine Logzeile und
kein Audit-Eintrag trägt je einen Schlüssel im Klartext.

[Secrets und der Vault →](secrets.md)

## Mandantenfähig, im Schema { #multi-tenant-in-the-schema }

Die Isolation zwischen Organisationen besteht aus Constraints und Schlüsseln,
nicht aus Konvention. Die interessanten Tests in diesem Repository sind die, die
eine *Ablehnung* prüfen: ein mandantenübergreifender Lesezugriff, ein nicht
gewährter Scope, eine Budgetüberschreitung, eine zweite Entscheidung über eine
entschiedene Approval.

## Trigger, damit ein Agent ohne Sie läuft { #triggers-so-an-agent-runs-without-you }

Planen Sie einen Run oder lösen Sie einen bei einem Ereignis aus. Derselbe Spec,
dasselbe Budget, dieselbe Audit-Spur — nur tippt niemand.

[Trigger →](triggers.md)

## Selbst gehostet, und still { #self-hosted-and-quiet }

Docker Compose, Ihr Postgres, Ihr Redis, Ihre Hardware.

Nichts telefoniert nach Hause. Modellpreise stammen aus einem Snapshot, der dem
Release beiliegt, und die einzigen ausgehenden Anfragen sind die, die Ihre Agents
stellen.

## Open Source { #open-source }

Apache 2.0, prüfbar und forkbar. Das Spec-Format ist versioniert, also lädt ein
Dokument, das Sie heute exportieren, auch morgen noch.

[Installieren →](install.md) · [Ihren ersten Agent bauen →](first-agent.md)
