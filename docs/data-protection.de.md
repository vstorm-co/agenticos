---
source_sha: "3a50fc3a822d"
---

# Datenschutz { #data-protection }

Wo personenbezogene Daten in einem Deployment liegen, was es verlässt und unter
welcher Konfiguration, welche Kontrollen im Code existieren und einen Test
hinter sich haben und welche noch offene Issues sind. Geschrieben für den, der
eine Datenschutzprüfung eines Deployments beantwortet — einen
Datenschutzbeauftragten, einen Sicherheitsverantwortlichen, einen Betreiber —
und ehrlich gehalten über den Unterschied zwischen dem, was die Software kann,
und dem, was ein Deployment tatsächlich entschieden hat.

!!! warning "Eine Seite ist keine Compliance"

    Nichts hier ist ein Nachweis, dass ein Deployment die DSGVO einhält. Die
    Codebasis lässt sich innerhalb einer konformen Umgebung betreiben; ob eine
    solche es *ist*, hängt von den konfigurierten Providern ab, von der
    entschiedenen Aufbewahrung, den unterzeichneten Verträgen und dem Betreiber,
    der sie führt. Jede dieser Bedingungen ist unten als etwas benannt, das zu
    beschaffen und zu prüfen ist, nie als etwas Angenommenes.

## Standardmäßig verlässt nichts das System { #nothing-leaves-by-default }

Ein frisches Deployment hält alles in seinem eigenen PostgreSQL und auf seiner
eigenen Platte und sendet nirgendwohin etwas. Jeder Sprung nach außen ist eine
Zeile oder eine Einstellung, die jemand danach hinzufügt: ein Model-Profil, das
einen Provider benennt, eine Collection, die einen Parser wählt, eine
Suchmethode auf einem Spec, ein Logfire-Token, ein mem0-Host, ein MCP-Server,
ein Kanal-Bot. Entfernen Sie die Zeile, und der Sprung ist weg.

Ein Deployment, das **keine dritte Partei in der Kette** will, konfiguriert sich
entsprechend, und die Software macht mit:

| Thema | Die lokale Antwort |
|---|---|
| Das Chat-Model | Ein `ollama`- oder `litellm`-Profil — schlüssellos, auf einen Endpunkt gerichtet, den Sie selbst betreiben. Jeder der 27 Provider mit `base_url` nimmt auch ein Gateway von Ihnen |
| Dokumenten-Parsing | `pymupdf`, der Standard, läuft im Worker. LiteParse-OCR läuft ebenfalls im Worker oder an einem OCR-Server, den Sie als lokalen Dienst registrieren. LlamaParse ist eine Wahl je Collection und braucht einen Vault-Schlüssel; ohne einen wird nichts außer Haus geparst |
| Embeddings | Ein Ollama, das Sie betreiben, unter Knowledge → Integrations als lokaler Dienst registriert und je Collection als Provider `ollama` gewählt. Schlüssellos, und der einzige Provider, den eine app-scoped Collection nutzen darf |
| Traces | Lassen Sie `LOGFIRE_TOKEN` ungesetzt und binden Sie kein `observability`-Token an einen Spec oder ein Environment. Runs halten die Trace-Id weiterhin lokal fest |
| Suche, Browsing, Memory, Tools | Binden Sie kein `search`-Secret, keine Capability `web_fetch`, `browser_use` oder `memory_mem0`, keine MCP-Verbindung |
| E-Mail | Ihr eigenes SMTP-Relay |
| Sprache und Bilder | Profile bei einem Provider, den Sie betreiben, oder gar kein solches Profil |

Embeddings eingeschlossen: Der Katalog nennt OpenRouter und OpenAI, die eine
Collection mit einem Vault-Schlüssel erreicht, und `ollama`, das eine Collection
an einem lokalen Dienst erreicht — einer Zeile, die einen Server benennt, den die
Organisation oder das Deployment betreibt. Eine Collection auf `ollama` schickt
ihre Chunks und Anfragen an keinen anderen Host und zahlt niemandem etwas. Ein
Deployment, das Dokumente auf eigener Hardware halten muss, legt dort jede
Collection an.

## Wer wofür verantwortlich ist { #who-is-responsible-for-what }

| Partei | Rolle | Was das hier bedeutet |
|---|---|---|
| Die Organisation, die es betreibt (eine Stadt, ein Unternehmen) | **Verantwortlicher** | Entscheidet über Zwecke, Aufbewahrung, welche Provider ein Agent erreichen darf, und unterzeichnet die Verträge mit ihnen |
| Vstorm als Autor der Software | **Keines von beiden**, bei einem selbst gehosteten Deployment | Der Code läuft auf Ihrer Infrastruktur, und nichts telefoniert nach Hause. Vstorm sieht Ihre Daten nie |
| Vstorm, wenn es das Deployment für Sie betreibt | **Auftragsverarbeiter** | Ein Auftragsverarbeitungsvertrag ist ein Vertrag zwischen uns, keine Einstellung. Er muss vor dem ersten veröffentlichten Agent existieren |
| Ein Model-, Embedding-, Parsing-, Such- oder Observability-Provider | **Unterauftragsverarbeiter**, per Konfiguration gewählt | Die Plattform hält fest, *welchen* Provider und *welchen* Endpunkt jeder Agent nutzt. Deren Standort, Aufbewahrung und Trainingsbedingungen sind ihre und werden je Deployment geprüft |

Die Plattform trainiert und finetunt nichts. Sie sendet Prompts, Dokumente und
Tool-Ergebnisse an die Provider, die ein Deployment konfiguriert, und speichert,
was zurückkommt. Ob ein Provider API-Verkehr zum Training verwendet, ist eine
Eigenschaft seines Kontos und seiner Bedingungen, und die Checkliste am Ende
verlangt die Erklärung, statt sie anzunehmen.

## Wo personenbezogene Daten liegen { #where-personal-data-lives }

Alles unten liegt im eigenen PostgreSQL des Deployments, auf seiner eigenen
Platte oder in einem Dienst, den das Deployment gewählt hat. Jede Tabelle, die
einer Organisation gehört, trägt eine `organization_id`; eine Kindzeile — eine
Nachricht, ein Anhang, eine Bewertung — ist über die Conversation oder den
Benutzer gescoped, an dem sie hängt, und der Lesezugriff geht über die Prüfung
des Elternteils.

### Die Datenbank { #the-database }

| Speicher | Hält | Personenbezogene Daten darin | Zweck |
|---|---|---|---|
| `users`, `sessions`, `organization_members` | Konten und Anmeldungen | E-Mail, Name, Avatar, gehashtes Passwort oder die Google-Konto-Id, Refresh-Token-Hash, IP-Adresse und User-Agent je Session | Authentifizierung und Autorisierung |
| `conversations`, `messages`, `tool_calls` | Jeder Chat auf jeder Oberfläche | Der Text, den Menschen geschrieben haben, die Antworten und das Reasoning des Models, Tool-Argumente und -Ergebnisse, eine fortlaufende Zusammenfassung langer Threads | Die Kernfunktion des Produkts; die Historie, zu der ein Mensch zurückkehrt |
| `chat_files` | Anhänge an einer Nachricht | Dateiname, Typ, Größe, der extrahierte Text (`parsed_content`) und der Pfad der Bytes auf der Platte | Antworten über eine Datei |
| `context_files` | Dauerhaftes Wissen, das ein Builder für Agents geschrieben hat | Was der Autor dort hineingeschrieben hat — und es erreicht den Prompt wörtlich. Siehe [Kontextdateien](context.md) | Anweisungen und Fakten, die ein Agent immer kennen soll |
| `agent_memory_files` | Notizen, die ein Agent über eine Person oder einen Gruppenchat geschrieben hat | Was der Agent für merkenswert hielt, geschlüsselt auf `person:<user_id>` oder einen Chatraum | Kontinuität zwischen Conversations |
| `rag_documents`, `knowledge_bases` und eine Vektortabelle je Collection | Hochgeladene und synchronisierte Dokumente, ihre Chunks und Embeddings | Der Dokumenttext und seine Vektoren, der ursprüngliche Pfad der Datei in der Quelle | Retrieval |
| `agent_runs`, `tool_approvals`, `run_manifests` | Was jeder Run gekostet und getan hat | Der System-Prompt und die letzte an das Model übergebene Anfrage, Tool-Argumente, die auf Freigabe warten, die entscheidende Person und ihre Notiz | Budgets, Freigaben, Run-Historie |
| `agent_triggers` | Geplante und ereignisgesteuerte Runs | Der Prompt sowie Konfiguration und Filter der Ereignisquelle | Einen Agent ohne Menschen laufen lassen |
| `app_admin_audit_logs` | Wer Zugriff geändert oder Geld ausgegeben hat — die Spur der Organisation und die des Deployment-Administrators teilen sich eine Tabelle | Akteur, Impersonator, IP-Adresse, die Aktion und eine `details`-Map. Die Map benennt meist Felder, aber manche Einträge halten Werte: die E-Mail des impersonierten Kontos, die E-Mail eines vom Administrator gelöschten Kontos, eine Veröffentlichungsnotiz | Rechenschaft. Siehe [Governance](governance.md#audit) |
| `embed_visitors`, `channel_identities`, `channel_sessions` | Fremde auf einer gehosteten Seite und Menschen auf Slack, Telegram oder Mattermost | Ein zufälliger Besucherschlüssel; eine Plattform-Benutzer-Id, ein Benutzername und ein Anzeigename; die Chat-Id | Den richtigen Thread fortsetzen |
| `message_ratings` | Daumen und Kommentare zu Antworten | Der Bewertende und sein Kommentar | Qualitätsprüfung |
| `agent_workspaces`, `sandbox_operations` | Dateien, an denen ein Agent gearbeitet hat, und das Log dessen, was er ausgeführt hat | Beim `state`-Backend die Dateien selbst, als JSON; bei einem Container die Session-Id und jedes Kommando, Ziel und Ergebnis-Resümee | Die Sandbox. Siehe [Die Sandbox](sandbox.md#what-was-done-in-one-and-where-that-record-lives) |
| `organization_secrets`, `model_profiles`, `mcp_connections`, `channel_bots` | Zugangsdaten und wohin sie zeigen | Nur versiegelter Chiffretext, mit einem Hinweis; Provider, Model und `base_url` im Klartext | Provider erreichen. Siehe [Secrets](secrets.md) |

`messages.search_vector` ist ein Volltextindex über denselben Inhalt, und
`conversations.summary_messages` ist eine vom Model geschriebene Verdichtung
davon. Beides sind Kopien des Chats und gehen mit ihm.

### Außerhalb der Datenbank { #outside-the-database }

| Speicher | Hält | Gelöscht, wenn |
|---|---|---|
| `MEDIA_DIR` auf dem API-Host (Volume `media_data`) | Chat-Anhänge unter `<user_id>/`, Avatare, Embed-Logos, generierte Bilder unter `generated_<org>/` und eine temporäre Kopie jedes Dokuments unter `_rag_tmp`, solange es geparst wird | Ein Dokument über das Produkt gelöscht wird. **Nichts im Produkt entfernt die Bytes eines Chat-Anhangs** — weder das Löschen seiner Conversation noch das Löschen seines Besitzers. Siehe [Was das Löschen erreicht](#what-deletion-reaches) |
| `SANDBOXD_WORKSPACE_ROOT` auf dem Sandbox-Host | Die Dateien jedes containergestützten Workspace | Die Conversation gelöscht wird oder `SANDBOXD_WORKSPACE_TTL` sie wegräumt; ungesetzt bleiben sie unbegrenzt. Siehe [Wie lange etwas überlebt](sandbox.md#how-long-anything-survives) |
| Redis | Rate-Limit-Buckets, geschlüsselt auf den Aufrufer — bei einer öffentlichen Oberfläche ist das die **IP-Adresse im Klartext**, im Schlüssel, für die TTL des Fensters; Dedup-Schlüssel für Trigger und Kanäle; OAuth-Austauschzustand; vorgemerkte Einladungen | Beim Ablauf; nichts hier überlebt seine Minuten |
| Prefect | Historie und Logs der Flow-Runs | Parameter sind Ids und Pfade, mit einer Ausnahme: der **`event_context` eines ereignisgesteuerten Runs** — Absender, Betreff und Text einer Gmail-Nachricht, eines GitHub-Issues, eines Webhook-Payloads — reist als Flow-Parameter und bleibt in der Run-Historie. Die Logs des Workers laufen durch denselben Redaktionsfilter wie die der API |
| Logfire, wenn konfiguriert | Traces jedes Runs | Die Aufbewahrung des Providers. Heute trägt ein Trace den vollen Prompt, die Ausgabe und die Tool-Argumente — siehe [Traces](#traces) |
| Ihr SMTP-Relay | Einladungen, Magic Links, Freigabeanfragen, Budget-Warnungen, Nutzungsberichte | Was das Relay aufbewahrt. Eine Freigabe-Mail nennt den Agent, das Tool und einen Link, nicht die Argumente des Tools |
| Backups | Ein `pg_dump` ist die ganze Datenbank; das Media-Volume sind die Dateien | Ihr Backup-Ablauf. Eine Löschung erreicht ein bereits gezogenes Backup nie — siehe [Backups](deploy.md#backups) |

## Was das Deployment verlässt { #what-leaves-the-deployment }

Nichts geht hinaus, solange nicht eine Zeile oder eine Einstellung ein Ziel
benennt. Dies ist die vollständige Liste der Ziele, mit der Konfiguration, die
über jedes entscheidet.

| Ziel | Was gesendet wird | Entschieden durch | Standort und Bedingungen |
|---|---|---|---|
| Das Chat-Model | Die bisherige Conversation, eingefügte oder beschriebene Anhänge, abgerufene Chunks, Tool-Ergebnisse | Ein [Model-Profil](models.md#a-model-profile): `provider`, `model`, `base_url` und ein versiegelter Schlüssel. Siebenundzwanzig Provider; `ollama` und `litellm` sind schlüssellos und werden an einem Endpunkt erreicht, den Sie betreiben, und `openai`, `anthropic`, `google`, `huggingface` und andere akzeptieren eine `base_url`, ein EU-Endpunkt oder ein Gateway ist also ein Feld und keine Abzweigung | Die des Providers. Je Profil prüfen |
| Das Embedding-Model | Jeder Chunk jedes Dokuments einer Collection und jede Retrieval-Anfrage | Je Collection, und nur dort: `embedding_provider` (`openrouter`, `openai` oder `ollama`, aus dem Katalog) und, für die ersten beiden, der Vault-Schlüssel `embedding_secret_id`, der zahlt. Einen deploymentweiten Embedding-Schlüssel gibt es nicht; eine schlüsselpflichtige Collection ohne einen verweigert Indexierung und Suche. `ollama` ist schlüssellos und wird an dem lokalen Dienst erreicht, den die Collection benennt (`embedding_endpoint_id`), einem Host, den Sie betreiben | Die des Providers oder Ihr eigener Host. [Eine dauerhafte Wahl](choosing-models.md#embeddings-are-a-separate-permanent-choice) |
| LlamaCloud | Das ganze Dokument | Eine Collection, deren `pdf_parser` `llamaparse` ist; sie muss einen Vault-Schlüssel benennen (`llamaparse_secret_id`), einen Deployment-Schlüssel gibt es nicht. Der Standard `pymupdf` parst im Worker | Die von LlamaCloud, falls genutzt |
| Ein OCR-Server | Gerenderte Seiten eines Dokuments | Eine Collection, deren `pdf_parser` `liteparse` ist **und** deren `ocr_endpoint_id` einen lokalen Dienst benennt; ohne einen läuft OCR im Worker | Ihr eigener Host — ein lokaler Dienst liegt konstruktionsbedingt im Netz des Deployments |
| Ein Bildbeschreibungs-Model | Bilder in Dokumenten | Das `image_description_model` einer Collection | Die dieses Model-Providers |
| Web-Recherche | Die Suchanfrage, die der Agent formuliert hat | `web_research.method` auf dem Spec: `duckduckgo` (kein Schlüssel), `tavily`, `brave` oder `exa` (je ein `search`-Secret), oder `native`, wobei der Provider des Chat-Models sucht | Die des Suchanbieters oder des Model-Providers |
| Web-Fetch und Browser-Nutzung | Die URL; bei Browser-Nutzung die ganze Aufgabe | Die Capability auf dem Spec; Browser-Nutzung braucht zusätzlich einen CDP-Endpunkt, den Sie benennen | Die abgerufene Seite; der Browser-Host |
| Die Sandbox, ausgehend | **Alles im Workspace, an jeden beliebigen Host** — die Runtime `workbench` hat ein Netz, eine Shell und `curl` | Die Capability `sandbox` und eine Runtime mit `needs_network`; die Kommandofreigabe steuert, was läuft, nicht wohin es sich verbindet | Wohin das Kommando ging. Egress-Kontrolle ist die Firewall des Sandbox-Hosts, keine Einstellung hier |
| Ein MCP-Server | Tool-Argumente und -Ergebnisse | `mcp_connections.url`, je Organisation oder je Person | Die des Serverbetreibers |
| mem0 | Die für eine Person oder einen Chat geschriebenen Memories | Die `base_url` der Capability `memory_mem0`, die in `MEM0_ALLOWED_HOSTS` stehen muss | Die des mem0-Hosts, den Sie zulassen |
| Logfire | Spans für jede Anfrage und jeden Run | `LOGFIRE_TOKEN` deploymentweit; ein `observability`-Token auf einem Spec oder `logfire_token_secret_id` auf einem Environment lenkt diese Runs in ein anderes Projekt. `LOGFIRE_BASE_URL` wählt das US- oder EU-Deployment. Überall ungesetzt wird nichts gesendet | Die von Pydantic, US oder EU |
| Speech-to-Text, Bildgenerierung | Die Sprachnachricht; der Prompt | Ein Profil für `groq`, `mistral` oder `openai`; ein Profil für `google` oder `openai` | Die des Providers |
| Slack, Telegram, Mattermost | Die Antworten des Agents | Eine `channel_bots`-Zeile mit ihrem Token im Vault | Der Messaging-Anbieter hält den Chat ohnehin schon |
| Google-Anmeldung | Nichts ausgehend; Google liefert E-Mail, Name, Bild und Konto-Id zurück | `GOOGLE_CLIENT_ID` | Die von Google |
| Ihr SMTP-Relay | Die oben genannte Post | `SMTP_HOST`, `SMTP_TLS` | Ihre |

Sync-Konnektoren laufen andersherum: Eine Google-Drive- oder S3-Quelle zieht
Dokumente **herein**, authentifiziert durch ein `connector`-Secret, und von da an
sind die Dokumente die Kopie des Deployments und folgen den Regeln oben. Wer
lesen kann, was eine Quelle aufgenommen hat, ist
[eine Entscheidung der Quellzeile](file-processing.md#who-ends-up-able-to-read-what-a-source-ingested).

## Kontrollen, und wo jede nachgewiesen ist { #controls-and-where-each-is-proved }

Jede Zeile benennt den Mechanismus im Code und den Test oder die Seite, die ihn
festnagelt, oder das Issue, das es tun wird. Eine Zeile, deren letzte Spalte ein
Issue ist, ist eine Lücke und steht als solche da.

| Kontrolle | Mechanismus | Nachgewiesen durch |
|---|---|---|
| Mandantentrennung | `organization_id` auf jeder Tabelle, die einer Organisation gehört, bei jeder Anfrage aus `X-Organization-Id` auf eine Mitgliedschaft aufgelöst; Kindzeilen nur über die Prüfung ihres Elternteils erreichbar | `tests/integration/test_conversation_tenant_isolation.py` und Geschwister; [Berechtigungen](permissions.md) |
| Zugriff auf eine Zeile | Drei Schichten: Deployment-Administrator, Rolle in der Organisation, Grant je Ressource über `resolve_access`. Ein Bedienelement, das der Aufrufer nicht nutzen darf, wird nicht gerendert | Ablehnungstests in `tests/api/`; [Berechtigungen](permissions.md#how-the-layers-combine) |
| Den Chat einer anderen Person lesen | Besitzer, eine ausdrückliche Freigabe oder der App-Administrator des Deployments — nie eine Rolle in der Organisation. Conversations haben ihre eigene Prüfung, `ConversationService._may_read`, statt der Grant-Formel | `admin_conversations.py` verlangt `is_app_admin`; `tests/integration/test_conversation_tenant_isolation.py` |
| Zugangsdaten im Ruhezustand | Envelope-Verschlüsselung je Organisation, versionierte Masterschlüssel, Rotation mit Trockenlauf | [Secrets](secrets.md#what-never-happens), vier durch Tests festgenagelte Garantien |
| Inhalte im Ruhezustand | **Von der Anwendung nicht verschlüsselt.** Die Postgres-Daten, `media_data` und das Workspace-Wurzelverzeichnis der Sandbox verlassen sich auf Platten- oder Volume-Verschlüsselung, die Sie bereitstellen | Kontrolle des Betreibers. Ein S3-Backend mit serverseitiger Verschlüsselung für Dateien ist [#1423](https://github.com/vstorm-co/agenticos/issues/1423) |
| Auf dem Transportweg, eingehend | HTTPS an Ihrem Proxy; `Strict-Transport-Security`, wenn `ENVIRONMENT=production`; Session-Cookies `httpOnly`, und `secure` aus dem Schema der Anfrage bei Anmeldung und Refresh. Die Route für den Passwortwechsel setzt `secure` nur in einem Produktions-Build | [Deploy](deploy.md#choose-a-reverse-proxy); `frontend/src/app/api/auth/login/route.ts` |
| Auf dem Transportweg, zu den Speichern | `POSTGRES_SSLMODE` und `REDIS_SSL`; `agenticos cmd doctor` meldet, ob die hergestellte Verbindung verschlüsselt war | [Verschlüsselte Verbindungen](configuration.md#encrypted-connections-tls); `tests/integration/test_store_tls.py` |
| Auf dem Transportweg, zu den Providern | HTTPS zu jedem katalogisierten Endpunkt. Eine eigene `base_url` wird ohne Host oder mit Zugangsdaten darin abgelehnt, aber **`http://` wird akzeptiert**, für ein Ollama oder ein Gateway im Netz des Deployments selbst; ein Klartext-HTTP-Profil, das aus diesem Netz hinauszeigt, sendet Prompts und Schlüssel im Klartext. Punkt 4 der Checkliste listet jedes solche Profil | `refused_field("base_url", ...)` im Model-Profile-Service; das Schema ist Sache des Betreibers |
| Secrets in Antworten, Logs, Audit, Exporten | Kein Endpunkt gibt einen Klartext zurück; `SecretStr` überall; Specs referenzieren Secrets per Id | [Secrets](secrets.md#what-never-happens) |
| Personenbezogene Daten in Logs | `app/core/logging.py` redigiert E-Mail-Adressen, JWTs, API-Schlüssel, Bearer-Token und `password=`-Paare aus jedem Log-Record, in API wie Worker | `tests/test_logging.py`; der Worker installiert es in `prefect_app.py` (#440) |
| Personenbezogene Daten, die das Model erreichen | Die Capability `guardrails` redigiert IBANs, Kartennummern, US-Sozialversicherungsnummern und E-Mail-Adressen aus Prompts, Antworten und Tool-Ergebnissen, sofern konfiguriert | [Capabilities](reference/capabilities.md); ihre Tests unter `tests/` |
| Personenbezogene Daten in einer Fehlerspalte | `rag_documents.error_message` und Verwandte halten Stufe und Klasse fest, nie den Text des Kunden | `app/services/rag/failures.py` (#423) |
| Rechenschaft | Audit-Einträge teilen die handelnde Transaktion und scheitern geschlossen; Impersonation nennt beide Personen; Massenexporte werden festgehalten | [Governance](governance.md#audit) |
| Audit-Export und Manipulationsnachweis | Noch keiner | [#1422](https://github.com/vstorm-co/agenticos/issues/1422) |
| Traces | Heute voller Inhalt, und kein Schalter | [#1413](https://github.com/vstorm-co/agenticos/issues/1413) ergänzt `full`, `redacted`, `none` je Agent |
| Aufbewahrung nach Zeitplan | Nur `sandbox_operations`-Zeilen werden weggeräumt, nach 30 Tagen. Das Wegräumen abgebrochener Runs finalisiert sie; es löscht nichts | [#1420](https://github.com/vstorm-co/agenticos/issues/1420) |
| Löschung einer Person | Die Kontolöschung bereinigt, was sie blockieren würde; die Löschung des Memory ist ein eigener Aufruf und reicht bis mem0 | [Was das Löschen erreicht](#what-deletion-reaches); [#1421](https://github.com/vstorm-co/agenticos/issues/1421) für das, was es zurücklässt |
| Zugang zu den eigenen Daten | Kein Export-Endpunkt; keine Sicht auf das eigene Memory | [#1421](https://github.com/vstorm-co/agenticos/issues/1421), [#1594](https://github.com/vstorm-co/agenticos/issues/1594) |
| Unternehmensidentität | Google-Anmeldung und Passwörter; noch kein OIDC | [#1419](https://github.com/vstorm-co/agenticos/issues/1419) |
| Die Kontrollmatrix, die eine Sicherheitsprüfung liest | Diese Seite und [Einführen](rollout.md#what-your-security-review-will-ask) | [#1412](https://github.com/vstorm-co/agenticos/issues/1412) ergänzt die Zuordnung zu HIPAA und SOC 2 |
| Öffentliche Oberflächen | Der Besucherschlüssel einer gehosteten Seite ist zufällig, nie aus der Person abgeleitet; Einlass und Uploads sind je Adresse ratenbegrenzt, die Adresse liegt für die Dauer des Fensters in einem Redis-Schlüssel und sonst nirgends | [Kanäle](channels.md#a-hosted-page) |
| Rechtliche Hinweise | Die eigenen AGB- und Datenschutz-URLs des Deployments ersetzen die eingebauten Seiten | [Das Deployment](deployment.md#identity) |

### Traces { #traces }

`instrument_pydantic_ai()` läuft mit dem Standard der Bibliothek, ein Span hält
also die Nachricht des Benutzers, die Antwort des Models und jedes Tool-Argument
und -Ergebnis. Mit ungesetztem `LOGFIRE_TOKEN`, ohne `observability`-Token auf
irgendeinem Spec und ohne `logfire_token_secret_id` auf irgendeinem Environment
wird nichts gesendet, und die Trace-Id wird trotzdem lokal festgehalten. Ein
Deployment, das Traces braucht, bevor
[#1413](https://github.com/vstorm-co/agenticos/issues/1413) landet, hat eine
Möglichkeit: ein Logfire-Projekt, dessen Bedingungen und Region es akzeptiert
hat — im Wissen, dass der Inhalt mit den Zeiten mitgeht.

### Was das Löschen erreicht { #what-deletion-reaches }

Löschen ist das, was das Produkt heute tut, wenn jemand darum bittet; geplante
Aufbewahrung ist [#1420](https://github.com/vstorm-co/agenticos/issues/1420).

| Aktion | Entfernt | Lässt zurück |
|---|---|---|
| `DELETE /conversations/{id}` (der Besitzer) | Die Conversation, ihre Nachrichten, Tool-Aufrufe, Bewertungen, Freigaben und `chat_files`-Zeilen, per Kaskade; ein Container-Workspace wird über `purge_for_conversation` gesäubert | **Die Bytes der Anhänge unter `MEDIA_DIR`.** Keine Route löscht eine Chat-Datei; der einzige Codepfad, der eine solche entfernt, verwirft den verwaisten Upload eines Kanal-Bots. Run-Zeilen und Manifeste, die die Conversation benannten, behalten ihre Prompt-Kopie. Verfolgt in [#1421](https://github.com/vstorm-co/agenticos/issues/1421) |
| `DELETE /memory/person/{user_id}` (die Person oder `members:manage`) | Jede `agent_memory_files`-Zeile, die auf die Person geschlüsselt ist, über alle Agents der Organisation hinweg, und dasselbe in jedem gebundenen mem0-Speicher | Notizen, die auf einen Gruppenchat geschlüsselt sind, in dem die Person gesprochen hat |
| `DELETE /users/{id}` | Das Konto, seine Sessions, seine persönliche Organisation und persönlichen Collections samt ihren Vektortabellen und Dateien, durch ausdrücklichen Abbau; Conversations und Chat-Dateien per Kaskade | **Das Memory der Person** — `owner_key` ist ein String und kein Fremdschlüssel, `agent_memory_files`- und mem0-Einträge überleben also, sofern nicht zuvor `DELETE /memory/person` lief. Audit-Einträge, die die Akteurs-Id und bei manchen Aktionen die E-Mail nennen; Nachrichten in geteilten Conversations; die Anhang-Bytes von oben. Die Inventur davon ist das Ergebnis von [#1421](https://github.com/vstorm-co/agenticos/issues/1421) |
| Ein Dokument oder eine Collection löschen | Die Zeilen, die Vektortabelle und die gespeicherte Datei, über einen dauerhaften Flow nach dem Commit | Nichts, sobald der Flow gelaufen ist; die Zählstände in `sync_logs` bleiben |
| Eine Organisation löschen | Alles, was auf sie gescoped ist, mit demselben aufgeschobenen Abbau | Persönliche Collections, die die Id lediglich mitführten |

Keines davon erreicht ein Backup. Eine Wiederherstellung bringt zurück, was
gelöscht wurde, der Backup-Ablauf gehört also zur Aufbewahrungsrichtlinie und
wird mit ihr zusammen niedergeschrieben.

## Was ein Deployment entscheiden und beschaffen muss { #what-a-deployment-has-to-decide-and-obtain }

Die Software kann nichts davon liefern. Jedes ist ein Nachweis, den die Prüfung
verlangen wird, und etwas anderes als die technische Fähigkeit, die ihn möglich
macht.

- **Ein Auftragsverarbeitungsvertrag mit jedem konfigurierten
  Unterauftragsverarbeiter** — jedem Provider, den eine Zeile in
  `model_profiles` oder `organization_secrets` benennt, dem Embedding-Provider,
  LlamaCloud, falls eine Collection es nutzt, dem Suchanbieter, den die `method`
  eines Agents benennt, dem mem0-Host, Logfire, dem SMTP-Relay und Google, falls
  die Anmeldung aktiviert ist.
- **Eine Erklärung zum Datenstandort je Provider**, abgeglichen mit der
  `base_url`, die jedes Profil tatsächlich nutzt. Ein Provider mit EU-Endpunkt
  ist nur dann in der EU, wenn das Profil es sagt.
- **Ein Trainingsausschluss je Provider**: die Kontoeinstellung oder
  Vertragsklausel, unter der API-Daten nicht zum Training verwendet werden. Die
  eigene Position der Plattform ist ein Satz — sie trainiert nichts — und der
  Rest ist deren Sache.
- **Ein Auftragsverarbeitungsvertrag mit Vstorm**, nur wenn Vstorm das
  Deployment betreibt.
- **Ein Aufbewahrungsplan** für Conversations, Dateien, Memory, Dokumente, Runs
  und Audit, und daneben der Backup-Ablauf. Bis
  [#1420](https://github.com/vstorm-co/agenticos/issues/1420) einen erzwingt,
  ist Aufbewahrung manuelles Löschen.
- **Platten- oder Volume-Verschlüsselung** auf dem Datenbank-Host, dem
  Media-Volume und dem Sandbox-Host, da die Anwendung Inhalte nicht selbst
  verschlüsselt — und eine Egress-Regel auf dem Sandbox-Host, wenn Agents
  Kommandos ausführen dürfen.
- **Die Rechtsseiten**, auf die das Deployment verlinkt, und wer eine Auskunfts-
  oder Löschanfrage beantwortet, solange
  [#1421](https://github.com/vstorm-co/agenticos/issues/1421) offen ist.

## Ein Deployment prüfen { #verifying-one-deployment }

Reproduzierbare Prüfungen, vom Host aus, gegen das laufende Deployment. Jede
gibt Fakten aus, die die Prüfung beilegen kann; keine gibt Zugangsdaten oder die
Daten einer Person aus. Führen Sie die Kommandos aus `backend/` aus oder über
`docker compose exec api`.

```bash
# 1. Läuft es, und sind die Verbindungen zu den Speichern verschlüsselt?
#    `postgres` meldet den TLS-Zustand der Verbindung, die der Doctor selbst
#    hergestellt hat.
uv run agenticos cmd doctor

# 2. Jede versiegelte Zugangsinformation öffnet sich noch unter den
#    konfigurierten Masterschlüsseln.
uv run agenticos cmd vault-rotate --dry-run

# 3. Die Einstellungen, die entscheiden, was hinausgeht. Leer ist die leise
#    Antwort.
env | grep -E '^(ENVIRONMENT|LOGFIRE_TOKEN|LOGFIRE_BASE_URL|MEM0_ALLOWED_HOSTS|POSTGRES_SSLMODE|REDIS_SSL|SMTP_TLS|LOG_PROVIDER_WRITE_TO_DISK|RATE_LIMIT_TRUST_FORWARDED_FOR)=' \
  | sed -E 's/(KEY|TOKEN)=.+/\1=<set>/'
```

`LOG_PROVIDER_WRITE_TO_DISK` muss außerhalb der Entwicklung `false` sein: Der
loggende E-Mail-Provider schreibt sonst ganze Mailtexte auf die Platte.

```sql
-- 4. Jeder Provider und Endpunkt, den ein Agent erreichen kann, ohne die
--    Schlüssel.
SELECT o.name AS organization, p.label, p.provider, p.model, p.base_url
FROM model_profiles p JOIN organizations o ON o.id = p.organization_id
ORDER BY 1, 2;

-- Profile, die Klartext-HTTP sprechen. Jedes muss auf das eigene Netz des
-- Deployments zeigen; alles andere sendet Prompts und Schlüssel im Klartext.
SELECT label, provider, base_url FROM model_profiles WHERE base_url LIKE 'http://%';

SELECT o.name AS organization, s.purpose, s.kind, s.name
FROM organization_secrets s JOIN organizations o ON o.id = s.organization_id
ORDER BY 1, 2;

-- Collections: wer sie embeddet, und welche außer Haus parsen.
SELECT name, embedding_provider, embedding_model,
       ingestion_config ->> 'pdf_parser' AS pdf_parser,
       ingestion_config ->> 'llamaparse_secret_id' IS NOT NULL AS llamaparse_key,
       embedding_endpoint_id, ingestion_config ->> 'ocr_endpoint_id' AS ocr_endpoint_id
FROM knowledge_bases ORDER BY 1;

-- Die Server im eigenen Netz, auf die Collections gerichtet werden dürfen.
-- Jede Adresse hier sollte eine sein, die Sie betreiben.
SELECT o.name AS organization, s.kind, s.provider, s.name, s.base_url, s.is_active
FROM local_services s LEFT JOIN organizations o ON o.id = s.organization_id
ORDER BY 1 NULLS FIRST, 2, 4;

SELECT scope, name, url, auth_type FROM mcp_connections WHERE is_enabled ORDER BY 1, 2;
SELECT name, connector_type, collection_name FROM sync_sources WHERE is_active ORDER BY 2, 1;

-- 5. Runs, die in ein eigenes Projekt getract werden: ein Token auf dem
--    veröffentlichten Spec oder auf einem Environment.
SELECT a.slug, v.version, 'spec' AS via
FROM agent_versions v JOIN agents a ON a.id = v.agent_id
WHERE v.spec -> 'observability' ->> 'token_secret_id' IS NOT NULL
UNION ALL
SELECT a.slug, NULL, 'environment ' || e.name
FROM agent_environments e JOIN agents a ON a.id = e.agent_id
WHERE e.logfire_token_secret_id IS NOT NULL;

-- 6. Was eine Aufbewahrung erreichen müsste. Passen Sie das Alter an den
--    entschiedenen Plan an.
SELECT 'conversations' AS store, count(*) FROM conversations WHERE created_at < now() - interval '365 days'
UNION ALL SELECT 'agent_runs', count(*) FROM agent_runs WHERE created_at < now() - interval '365 days'
UNION ALL SELECT 'audit', count(*) FROM app_admin_audit_logs WHERE created_at < now() - interval '365 days'
UNION ALL SELECT 'agent_memory_files', count(*) FROM agent_memory_files
UNION ALL SELECT 'chat_files', count(*) FROM chat_files;
```

```bash
# 7. Anhang-Bytes, deren Zeilen fort sind. Eine chat_files-Zeile verschwindet
#    per Kaskade mit ihrer Nachricht, während die Datei bleibt, die Differenz
#    wächst also mit jeder gelöschten Conversation (siehe „Was das Löschen
#    erreicht"). Generierte Bilder und das Parse-Arbeitsverzeichnis haben
#    absichtlich keine Zeile und sind ausgenommen. Über den Datenbank-Container:
#    Die API kennt ihren Connection String nur als berechnete Einstellung, nicht
#    als Variable, die eine Shell lesen könnte.
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT storage_path FROM chat_files
  UNION SELECT storage_path FROM rag_documents WHERE storage_path IS NOT NULL" \
  | sort > /tmp/referenced.txt
(cd "${MEDIA_DIR:-./media}" && find . -type f -not -path './generated_*' -not -path './_rag_tmp/*' \
  | sed 's|^\./||' | sort) > /tmp/on_disk.txt
comm -23 /tmp/on_disk.txt /tmp/referenced.txt | wc -l      # Dateien, die nichts referenziert
```

Avatare und Embed-Logos liegen ebenfalls auf der Platte und werden aus
`users.avatar_url` und `agent_embeds.logo_path` referenziert; nehmen Sie diese
Spalten in die Abfrage auf, wenn die Zahl oben nicht null ist und Sie die Liste
genau haben wollen.

Legen Sie die Ausgabe von 1 bis 6 der Prüfung zusammen mit den Verträgen aus dem
vorigen Abschnitt bei. Punkt 7 ist eine Zahl, die zu beobachten ist, bis
[#1421](https://github.com/vstorm-co/agenticos/issues/1421) die Bytes mit der
Conversation entfernt.

## Offene Bedingungen für eine erste Einführung { #open-conditions-for-a-first-rollout }

Festgehalten für das Deployment, für das diese Seite geschrieben wurde, und
zutreffend für jedes Deployment, bis jede einzelne geschlossen ist.

**Im Code, verfolgt:**

- Traces tragen vollen Inhalt — [#1413](https://github.com/vstorm-co/agenticos/issues/1413).
- Keine geplante Aufbewahrung — [#1420](https://github.com/vstorm-co/agenticos/issues/1420).
- Anhang-Bytes und das Memory einer Person überleben die Löschung ihres
  Besitzers; kein Export personenbezogener Daten; die Löschinventur —
  [#1421](https://github.com/vstorm-co/agenticos/issues/1421).
- Kein Audit-Export und kein Manipulationsnachweis — [#1422](https://github.com/vstorm-co/agenticos/issues/1422).
- Dateien nur auf lokaler Platte, vom Volume verschlüsselt oder gar nicht — [#1423](https://github.com/vstorm-co/agenticos/issues/1423).
- Keine Selbstbedienungssicht auf das eigene Memory — [#1594](https://github.com/vstorm-co/agenticos/issues/1594).
- Keine OIDC-Anmeldung — [#1419](https://github.com/vstorm-co/agenticos/issues/1419).
- Die Kontrollmatrix für HIPAA und SOC 2 — [#1412](https://github.com/vstorm-co/agenticos/issues/1412).

**Im Deployment, vom Betreiber entschieden:** die Verträge, Standorte,
Trainingsausschlüsse, der Aufbewahrungsplan, der Backup-Ablauf, die
Plattenverschlüsselung, der Sandbox-Egress und die Rechtsseiten aus dem vorigen
Abschnitt.

Eine Prüfung, die jede Zeile oben entweder geschlossen oder schriftlich
akzeptiert vorfindet, hat, was diese Seite ihr geben kann. Der Rest gehört dem
Deployment.
