---
source_sha: "efcb7fe03f88"
---

# Glossar { #glossary }

Die Wörter, die die Konsole verwendet, was jedes bedeutet und wie dieselbe Sache
in der API, im Spec und im YAML heißt, das ein Agent exportiert. Konsole, Rundgang,
Architekt und diese Seiten verwenden diese Namen; API und Spec behalten ihre
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
| Erste Nachrichten | Was ein leerer Chat jemandem anbietet, der den Agent öffnet, jede mit einem Klick | `starters` |
| Capability | Etwas, das ein Agent tun darf, im Builder eingeschaltet | `capabilities[]` |
| Skill | Einmal aufgeschriebenes Know-how, das jeder Agent liest, der es braucht | `skill` |
| Kontext | Dauerhaftes Wissen, das ein Agent immer hat, etwa ein Glossar oder eine Richtlinie | `context` |
| Wissensdatenbank | Dokumente, die ein Agent durchsucht und zitiert | `collection` |
| Wissenslücke | Ein Thema aus Fragen, die eine Wissensdatenbank nicht beantworten konnte, nach Bedeutung gruppiert; Verbessern zählt sie als **Fehlendes Wissen in der Wissensdatenbank** | `knowledge_gap_topic` |
| App | Eine Seite, die ein Agent veröffentlicht, etwa ein Bericht oder ein kleines Dashboard | `artifact` |
| Architekt | Der Assistent in der Ecke jeder Seite, der mit dir Agents bauen kann | `platform-assistant` |
| System-Agent | Ein Agent, den die Plattform selbst ausführt, etwa ein Bewerter, der Lücken-Entwerfer oder der Lücken-Klassifizierer; getrennt aufgeführt unter **System-Agents** | `kind` außer `agent` |
| Authoring-Assistent | Schlägt Änderungen an einem Agent, einem Skill oder einer Context-Datei aus negativ bewerteten Antworten vor; über jede entscheidet ein Mensch | `authoring` |
| Vorschlag | Eine vorgeschlagene Änderung am Draft, einzeln angenommen, bearbeitet oder verworfen | `spec_proposal_hunk` |
| Einstellungsänderung | Ein Vorschlag, einen Teil der Konfiguration eines Agents zu ändern, etwa sein Modell oder eine Capability | `spec_field`-Hunk |
| Änderung an einer Context-Datei | Ein neuer Inhalt, den der Assistent für eine Context-Datei vorschlägt, auf der Context-Seite angewendet oder verworfen | `context_proposal` |
| AgenticOS | Der Allzweck-Agent, mit dem eine neue Organisation im Chat beginnt, und das, womit ein neuer Agent startet | `general/agenticos` |

## Wo es läuft { #where-it-runs }

| In der Konsole | Was es ist | In API und Spec |
|---|---|---|
| Chat | Das Gespräch mit einem Agent im Browser | `conversation` |
| Kanal | Slack, Telegram oder Mattermost, wo Menschen einen Agent erreichen | `channel_bot` |
| Routine | Ein Agent, der selbstständig läuft, nach Zeitplan oder Ereignis | `trigger` |
| Eval-Suite | Ein Dataset, an dem ein Agent gemessen wird, nach Zeitplan, bei Veröffentlichung oder Promotion oder nach einer Änderung | `eval_suite` |
| Run | Ein Mal, dass ein Agent geantwortet hat, mit Kosten und Schritten | `agent_run` |
| Environment | Eine benannte Stufe, etwa Produktion, die auf eine Version zeigt | `environment` |
| Wächter | Eine Eval-Suite, die eine Umgebung auf einer Version bestanden sehen will, bevor sie sie übernimmt | `guard_suite_ids` |
| Übergehen | Eine Promotion an nicht bestandenen Wächtern vorbei, mit Begründung | `override_reason` |
| MCP-Server | Ein externer Tool-Server, den Agents aufrufen, einmal verbunden | `mcp_connection` |
| Remote Agent | Der Agent eines anderen Anbieters, über A2A erreichbar, an den Agents delegieren | `external_agent` |
| Agent2Agent (A2A) | Das Protokoll, über das Agents anderer Systeme einem Agent Aufgaben senden | `a2a_enabled` |
| Sandbox | Ein isolierter Rechner, auf dem ein Agent Dateien schreibt und Code ausführt | `sandbox` |
| Dokumente | Die Dateien, die Agents für eine Person aufbewahren, angehängt oder geschrieben, in ihren Sandboxes | `workspace` |

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
| KI-Unterstützung | Der Schalter der Organisation für die Modelle, die Antworten bewerten, Fälle entwerfen, Änderungen vorschlagen und fehlendes Wissen entwerfen, auch in Verbessern; aus, bis jemand sie einschaltet | `ai_assistance_enabled` |

## Wie getestet wird { #how-it-is-tested }

| In der Konsole | Was es ist | In API und Spec |
|---|---|---|
| Dataset | Versionierte Testfälle, an denen die Antworten eines Agents gemessen werden; in Verbessern die **Testfragen** | `dataset` |
| Fall | Eine Frage und das, woran eine gute Antwort gemessen wird; in Verbessern eine Testfrage | `dataset_case` |
| Bewertung | Wie die Antworten eines Datasets bewertet werden: Prüfungen, Referenzantwort und ein Bewerter | `scoring` |
| Kriterium | Eine Sache, die der Bewerter an jeder Antwort benotet, auf einer Skala oder als Ja oder Nein | `criteria[]` |
| Regel | Eine Prüfung, die eine Antwort ohne jedes Modell besteht oder nicht, etwa eine Wendung, ein Muster oder eine Länge; aufgeführt unter **Prüfungen** | `checks[]` |
| Bewerter | Ein Agent, der Antworten für Evals bewertet; nur die Plattform führt ihn aus | `kind: judge` |
| Bewertungsmodell | Das Modell, mit dem neue Bewerter benoten, einmal für die Organisation gewählt | `grading_model_profile_id` |
| Eval | Ein Agent, der jeden Fall eines Datasets beantwortet, bewertet und mit einer früheren Version verglichen | `eval_run` |
| Bestätigte Regression | Ein Fall, der vorher bestand und bei jeder Wiederholung wieder durchfällt; Verbessern sagt **Neu verschlechtert** | `flip: regression`, `confirmed: true` |
| Bestätigte Behebung | Ein Fall, der vorher durchfiel und bei jeder Wiederholung wieder besteht; Verbessern sagt **Neu behoben** | `flip: fixed`, `confirmed: true` |
| Unbestätigt | Ein Fall, der sich einmal geändert hat, bei der Wiederholung aber nicht auf dieselbe Weise, und daher als keins von beidem zählt; Verbessern führt ihn unter **Noch nicht bestätigt** | `confirmed: false` |
| Rauschen | Antworten, die beim erneuten Fragen anders bewertet werden, obwohl sich nichts geändert hat; ein Ergebnis, das es erklären kann, liegt im Rauschen, und **Jede Frage zweimal stellen** misst es | `measurement_noise`, `purpose: stability` |
| Prüfung | Scores, die darauf warten, dass ein Mensch sie bestätigt oder ändert | `review_state` |
| Fallgenerator | Der System-Agent, der Fälle aus einem Agent, seinem Wissen, echten Chats und Red Teaming entwirft | `kind: generator` |
| Vorgeschlagener Fall | Ein entworfener Fall, der unter **Generiert** wartet, bis ein Mensch ihn annimmt oder verwirft | `case_proposal` |
| Red Teaming | Fälle, die prüfen, ob ein Agent ablehnt, was er ablehnen muss | Tag `red-team` |

## Wie verbessert wird { #how-it-is-improved }

| In der Konsole | Was es ist | In API und Spec |
|---|---|---|
| Verbessern | Eine Sitzung, die liest, was bei einem Agent schiefging, Änderungen schreibt und testet und zwischen den Schritten auf einen Menschen wartet; sie veröffentlicht nie von selbst | `improvement` |
| Verstehen | Der erste Schritt: sortiert die Antworten mit Feedback in das, was der Agent beheben kann, und das, was in der Wissensdatenbank fehlt | `stage: analyzing`, `stage: classifying` |
| Änderungen | Der Schritt, in dem der Helfer die Änderungen eines Versuchs schreibt und du wählst, welche getestet werden | `stage: proposing`, `stage: filtering` |
| Prüfung | Der Schritt, in dem die heutige und die geänderte Version dieselben Fragen beantworten und beide bewertet werden; **Vollständige Prüfung öffnen** öffnet seinen Eval-Run | `stage: evaluating`, `stage: judging` |
| Ergebnis | Was die Sitzung ergeben hat: welcher Versuch den Agent verbessert hat oder dass keiner es tat, und was sich als Nächstes tun lässt | `status: ready`, `status: stopped` |
| Annehmen | Der letzte Schritt: **Version N veröffentlichen** oder **Als Entwurf behalten**; beides beendet die Sitzung | `POST /{run_id}/finish` |
| Versuch | Ein Anlauf innerhalb einer Sitzung: Änderungen geschrieben, dann an eigenen Fragen geprüft; höchstens drei pro Sitzung | `improvement_iteration` |
| Agent, der die Änderungen schreibt | Der Agent, der die Bewertungen liest und die Änderungen jedes Versuchs schreibt; der Authoring-Assistent, sofern kein anderer gewählt ist | `improver_agent_id` |
| Zurückgelegt | Testfragen, die ein Versuch zurücklegt, damit der Helfer sie nicht sieht und nur sie sein Ergebnis entscheiden | `improvement_partition: holdout` |
| Helfen, die Änderungen zu schreiben | Testfragen, die der Helfer liest, während er die Änderungen eines Versuchs schreibt; sie entscheiden nie sein Ergebnis | `improvement_partition: train` |
| Erneut versuchen | Startet vom Ergebnis aus einen weiteren Versuch, mit einem optionalen **Hinweis für den Helfer**; er schreibt neue Änderungen und hält bei **Änderungen** an | `/{run_id}/continue` mit `note` |
| Ausgabenlimit | Was eine Sitzung insgesamt ausgeben darf, Analyse und jeder Versuch eingeschlossen; jeder Schritt wird geschätzt, bevor er startet | `budget_usd` |
| Automatische Prüfung | **Diese Fragen bei jeder Änderung automatisch prüfen**: beim Annehmen eine Suite, die die Fragen der Sitzung vor jeder Veröffentlichung stellt und keine bestätigte Regression erlaubt | `automatic_check` |

## Capabilities { #capabilities }

Der Name, den der Builder zeigt, und die ID, die der Spec eines Agents bindet.
Jede ist unter [Capabilities](capabilities.md) beschrieben.

| In der Konsole | Im Spec |
|---|---|
| Apps | `artifacts` |
| Rückfragen | `ask_user` |
| Webbrowser | `browser_use` |
| Infos zum Chat-Kanal | `channel_tools` |
| Diagramme | `charts` |
| Datum und Uhrzeit | `clock` |
| Berechnungen | `code_execution` |
| Coding Agent | `coding_agent` |
| Lange Gespräche | `compaction` |
| Computer-Bedienung | `computer_use` |
| Kontext | `context` |
| Frühere Gespräche | `conversation_search` |
| Nächste Schritte | `follow_ups` |
| Schutzregeln | `guardrails` |
| Bilderzeugung | `image_generation` |
| Wissenssuche | `knowledge` |
| Bilder auslagern | `media` |
| Gedächtnis | `memory_files` |
| Gedächtnis (mem0) | `memory_mem0` |
| Planung | `planning` |
| Weiterarbeiten, während Tools laufen | `background_tools` |
| Sandbox | `sandbox` |
| Skills | `skills` |
| Subagents | `subagents` |
| Erinnerung an Anweisungen | `system_reminders` |
| Sprachausgabe | `text_to_speech` |
| Nachdenken | `thinking` |
| Grenzen für Tool-Ergebnisse | `tool_output_limits` |
| Tool-Suche | `tool_search` |
| Videoerzeugung | `video_generation` |
| Visuals | `visuals` |
| Webseiten lesen | `web_fetch` |
| Websuche | `web_research` |
| Tabellen | `virtual_tables` |
| Workflows | `workflows` |
