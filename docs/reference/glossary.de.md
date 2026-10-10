---
source_sha: "ee9dcf4d5cd6"
---

# Glossar { #glossary }

Die Wörter, die die Konsole verwendet, was jedes bedeutet und wie dieselbe Sache
in der API, im Spec und im YAML heißt, das ein Agent exportiert. Konsole, Rundgang,
AI Architect und diese Seiten verwenden diese Namen; API und Spec behalten ihre
eigenen, damit ein Skript, das dagegen geschrieben ist, bei einer Umbenennung
nicht bricht.

## Was du baust { #what-you-build }

| In der Konsole | Was es ist | In API und Spec |
|---|---|---|
| Agent | Ein Assistent mit eigenen Instruktionen, Modell, Wissen und Tools | `agent` |
| Entwurf | Die unveröffentlichten Änderungen eines Agents; außerhalb des Builders sieht sie niemand | `draft_spec` |
| Veröffentlichen | Den Entwurf als nummerierte Version einfrieren, die jede Oberfläche ausführt | `POST /agents/{id}/publish` |
| Version | Ein veröffentlichter Stand eines Agents, aufbewahrt und vergleichbar | `agent_version` |
| Test | Der Chat neben dem Builder, der als Entwurf oder als beliebige Version antwortet | `is_test` an seinen Runs |
| Instruktionen | Was der Agent vor jedem Gespräch gesagt bekommt | `instructions` |
| Variablen | `{{name}}` in den Instruktionen, beim Start eines Runs ausgefüllt | `variables` |
| Capability | Etwas, das ein Agent tun darf, im Builder eingeschaltet | `capabilities[]` |
| Skill | Einmal aufgeschriebenes Know-how, das jeder Agent liest, der es braucht | `skill` |
| Kontext | Dauerhaftes Wissen, das ein Agent immer hat, etwa ein Glossar oder eine Richtlinie | `context` |
| Wissensdatenbank | Dokumente, die ein Agent durchsucht und zitiert | `collection` |
| App | Eine Seite, die ein Agent veröffentlicht, etwa ein Bericht oder ein kleines Dashboard | `artifact` |
| AI Architect | Der Assistent in der Ecke jeder Seite, der mit dir Agents bauen kann | `platform-assistant` |

## Wo es läuft { #where-it-runs }

| In der Konsole | Was es ist | In API und Spec |
|---|---|---|
| Chat | Das Gespräch mit einem Agent im Browser | `conversation` |
| Kanal | Slack, Telegram oder Mattermost, wo Menschen einen Agent erreichen | `channel_bot` |
| Routine | Ein Agent, der selbstständig läuft, nach Zeitplan oder Ereignis | `trigger` |
| Run | Ein Mal, dass ein Agent geantwortet hat, mit Kosten und Schritten | `agent_run` |
| Environment | Eine benannte Stufe, etwa Produktion, die auf eine Version zeigt | `environment` |
| MCP-Server | Ein externer Tool-Server, den Agents aufrufen, einmal verbunden | `mcp_connection` |
| Sandbox | Ein isolierter Rechner, auf dem ein Agent Dateien schreibt und Code ausführt | `sandbox` |
| Agentendateien | Die Dateien, die Agents in ihren Sandboxes aufbewahren | `workspace` |

## Wer entscheidet { #who-decides }

| In der Konsole | Was es ist | In API und Spec |
|---|---|---|
| Organisation | Die Firma oder das Team, dem alles gehört | `organization` |
| Gruppe | Eine Abteilung oder ein Team, mit dem Agents, Skills und Wissen geteilt werden | `group` |
| Leitung | Ein Gruppenmitglied, das bestimmt, wer noch dazugehört | `is_lead` |
| Freigabe | Ein Tool-Aufruf, der darauf wartet, dass ein Mensch ihn erlaubt | `approval` |
| Budget | Ein Ausgabenlimit, das Runs stoppt, sobald es erreicht ist | `budget` |
| Schutzregeln | Prüfungen, die schwärzen oder blockieren, was durch einen Run fließt | `guardrails` |
| Vault | Wo Schlüssel und Tokens liegen, versiegelt und nie wieder angezeigt | `secret` |

## Capabilities { #capabilities }

Der Name, den der Builder zeigt, und die ID, die der Spec eines Agents bindet.
Jede ist unter [Capabilities](capabilities.md) beschrieben.

| In der Konsole | Im Spec |
|---|---|
| Apps | `artifacts` |
| Rückfragen | `ask_user` |
| Webbrowser (Schritt für Schritt) | `browser_choice` |
| Webbrowser | `browser_use` |
| Infos zum Chat-Kanal | `channel_tools` |
| Diagramme | `charts` |
| Datum und Uhrzeit | `clock` |
| Berechnungen | `code_execution` |
| Lange Gespräche | `compaction` |
| Kontext | `context` |
| Frühere Gespräche | `conversation_search` |
| Schutzregeln | `guardrails` |
| Bilderzeugung | `image_generation` |
| Wissenssuche | `knowledge` |
| Bilder auslagern | `media` |
| Gedächtnis | `memory_files` |
| Gedächtnis (mem0) | `memory_mem0` |
| Planung | `planning` |
| Sandbox | `sandbox` |
| Skills | `skills` |
| Delegation | `subagents` |
| Erinnerung an Anweisungen | `system_reminders` |
| Nachdenken | `thinking` |
| Grenzen für Tool-Ergebnisse | `tool_output_limits` |
| Tool-Suche | `tool_search` |
| Webseiten lesen | `web_fetch` |
| Websuche | `web_research` |
