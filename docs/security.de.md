---
source_sha: "2572f06ac36f"
---

# Sicherheit { #security }

Diese Seite ist das, was eine Sicherheitsprüfung im Zuschnitt von HIPAA oder
SOC 2 ausgehändigt bekommt: die Vertrauensgrenzen, welche Daten das Deployment
verlassen und an wen, was wo verschlüsselt ist, und eine Kontrollmatrix, die für
jede Kontrolle den Mechanismus in diesem Code benennt, der sie erfüllt, und den
Test, der sie hält.

Sie beschreibt, was **ist**, nicht was schön wäre. Eine Zeile ohne Mechanismus
sagt das und verlinkt das Issue, das ihn bauen würde. Wie man eine Schwachstelle
meldet und wie die Härtungs-Checkliste für die Produktion aussieht, steht in
[`SECURITY.md`](https://github.com/vstorm-co/agenticos/blob/main/SECURITY.md) im
Wurzelverzeichnis des Repositorys; diese Seite ist alles andere, in einer Kopie.

Zwei benachbarte Seiten beantworten die Fragen, die eine Prüfung als Nächstes
stellt, und werden hier nicht wiederholt: [Datenschutz](data-protection.md) dazu,
wo personenbezogene Daten liegen, was eine Löschung tatsächlich erreicht und
welche Lücken noch offen sind, und [Lizenzen](licenses.md) zu jeder
Drittkomponente, die die Images ausliefern.

## Bedrohungsmodell { #threat-model }

Die Plattform ist selbst gehostet und mandantenfähig. Die Entwurfsannahme ist,
dass die Infrastruktur des Betreibers vertrauenswürdig ist und jede Anfrage in
sie hinein nicht — die Grenzen, auf die es ankommt, sind also jene, die eine
Anfrage auf ihrem Weg zu den Daten überschreitet.

| Grenze | Was sie überschreitet | Auf der anderen Seite vertrauenswürdig? |
|---|---|---|
| Browser → BFF (die Next.js-Route-Handler) | Ein Session-Cookie, der Organisations-Header, Formulareingaben | Nein — aber das BFF prüft das Cookie nicht: es liest das `httpOnly`-`access_token` und reicht es als Bearer-Header weiter (`frontend/src/lib/platform-proxy.ts`). Es ist eine Grenze, die ein Credential weiterreicht; die Prüfung ist Aufgabe der API |
| BFF → API (FastAPI) | Ein an eine DB-Session gebundenes JWT, der Header `X-Organization-Id` | Nein — das Token wird pro Anfrage geprüft, die Session auf Widerruf kontrolliert und die Organisation aus dem Token aufgelöst |
| API → PostgreSQL / Redis | Queries und Cache-Lesezugriffe, über TLS, wenn konfiguriert | Ja — der Speicher gehört dem Betreiber; was er im Ruhezustand schützt, steht unter „Was wo verschlüsselt ist“ |
| API / Worker → Modell-Provider, Kanäle, MCP-Server, Suchanbieter, Logfire | Prompts, Tool-Aufrufe, Anfragen, Antworten, Traces | Nein — das sind Dritte; was sie erreicht, ist eine Entscheidung pro Agent, außer beim deploymentweiten Tracing (unten) |
| Worker → Konnektoren (Google Drive, S3, …) | Aus dem Vault entsiegelte Credentials, abgerufene Dokumente | Nein — ein Konnektor-Credential ist ein Secret im Vault, referenziert über seine id |

Autorität innerhalb eines Mandanten ist nie ein Rollenname auf einer Route: sie
ist eine Mitgliedschaftszeile plus der Berechtigungskatalog
(`app/core/permissions.py`), pro Ressource aufgelöst. Zwei Aufrufer mit derselben
Rolle können unterschiedliche Zeilen erreichen, weil ein Grant auf einer Ressource
erweitert, was eine Rolle erlaubt, ohne das Mitglied zu befördern.

## Was das Deployment verlässt { #what-leaves-the-deployment }

Nichts funkt nach Hause. Jeder ausgehende Aufruf ist einer, den das Deployment
konfiguriert hat, und jeder ist eine Grenze, nach der die Prüfung eines Kunden
fragen wird.

| Wohin | Was | Wann |
|---|---|---|
| Der konfigurierte Modell-Provider | Der Prompt, die Ausgabe des Modells, Tool-Argumente und -Ergebnisse | Jeder Run — außer das Modell läuft auf der eigenen Infrastruktur des Betreibers, dann verlässt nichts das Deployment |
| Der konfigurierte Kanal (Slack, Telegram, Mattermost) | Die generierten Antworten des Agents — Text, Bilder und Anhänge | Immer wenn ein Agent über diesen Kanal exponiert ist; jedes `send_message` postet beim Provider (`app/services/channels/`) |
| Logfire | Traces, die Prompts und Ausgaben tragen, sofern der Agent nichts anderes sagt | Zwei unabhängige Pfade. Ein Observability-Token pro Agent traced diesen Agent, und sein `content`-Modus entscheidet, wie viel der Span trägt - `none` reduziert ihn auf Zeit, Tokens, Kosten und Tool-Namen (#1413). Ein deploymentweites `LOGFIRE_TOKEN` instrumentiert **jeden** Run, in der API wie im Prefect-Worker (`app/core/logfire_setup.py`), mit ihm verlässt also der Inhalt jedes Agenten das Deployment, der nicht `none` verlangt hat; ein Agent, der es verlangt hat, wird auch auf diesem Tracer an eine inhaltsfreie Instrumentierung geheftet (`suppress_content`), der Modus hält also auf beiden Pfaden, und ein Spezialist dieses Agenten erbt ihn - inline geschrieben oder mitten im Run erfunden. Eine Lücke, die er nicht abdeckt: ein fehlgeschlagenes Anheften, das protokolliert und belassen wird. Keiner der beiden Pfade ist standardmäßig an. Ein gefiltertes Dazwischen gibt es bewusst nicht - ein teilweise bereinigter Export ist eine Zusicherung, die niemand prüfen kann ([#1616](https://github.com/vstorm-co/agenticos/issues/1616)) |
| MCP-Server | Tool-Aufrufe und ihre Argumente | Nur für die Tools, an die ein Agent gebunden ist |
| Ein Websuche-Anbieter (Tavily, DuckDuckGo) | Die Suchanfrage | Nur wenn die Such-Capability gewährt ist |
| Ein Embedding-Provider | Dokumenttext, beim Ingest | Nur für eine Wissensbasis, deren Provider entfernt ist |

## Was wo verschlüsselt ist { #what-is-encrypted-where }

Es gibt einen Verschlüsselungsmechanismus auf Anwendungsebene, und er ist
bewusst der einzige: der Vault (`app/core/vault.py`). Jedes **Konnektor- und
API-Credential** im Ruhezustand ist in einem Umschlag pro Eigentümer versiegelt,
dessen Wrapping-Key über HKDF aus der Organisation (oder dem Benutzer) abgeleitet
wird, zu der es gehört — ein Chiffrat, das in die Zeile einer anderen
Organisation kopiert wird, lässt sich also nicht entsiegeln. Der Master-Key ist
rotierbar, ohne die Payloads neu zu verschlüsseln.

Nicht alles, was die Plattform speichert, ist ein Credential im Vault, und das
steht hier klar, weil eine Prüfung es findet:

- **Kurzlebige Bearer-Token** — Organisationseinladungen
  (`OrganizationInvitation.token`), Kanal-Verknüpfungsanfragen
  (`ChannelLinkRequest.token`) und Freigabelinks für Konversationen
  (`ConversationShare.share_token`) — sind zufällige `String(64)`-Spalten, die
  über Gleichheit nachgeschlagen werden, nicht im Vault versiegelt. Wer den Wert
  hat, kann ihn nutzen, sie sind also durch Ablauf und Einmalverwendung
  geschützt, nicht durch Verschlüsselung. Session-Refresh-Token sind die
  Ausnahme, die im Ruhezustand gehasht ist (`sessions.refresh_token_hash`).
- **Hochgeladene Dateien und Chat-Dateien** liegen dort, wohin
  `FILE_STORAGE_BACKEND` sie legt (`app/services/file_storage.py`). Bei `local`,
  der Voreinstellung, ist das im Klartext das Dateisystem des API-Containers,
  geschützt nur durch Volume-Verschlüsselung. Bei `s3` sind es Objekte in einem
  Bucket, den das Deployment benennt, und jeder Schreibvorgang bittet den
  Speicher, sie zu verschlüsseln — SSE-S3 oder SSE-KMS unter einem Schlüssel, den
  der Kunde kontrolliert. `agenticos cmd doctor` gibt aus, in welchem der drei
  Zustände ein laufendes Deployment ist.
- **Nachrichteninhalte, `rag_documents` samt Vektoren und Sandbox-Workspaces**
  werden als Klartextspalten, pgvector-Zeilen und Workspace-Dateien gespeichert.
  Der Vault versiegelt Credentials, keine Inhalte; der Schutz im Ruhezustand ist
  hier auf Datenträgerebene.

Das S3-Backend ist eine Entscheidung zur Deployment-Zeit und migriert nicht, was
das lokale bereits hält; die Einstellungen stehen in der
[Konfiguration](configuration.md#uploaded-files-at-rest), die Begründung in
[Dateiverarbeitung](file-processing.md#storage).

## Kontrollmatrix { #controls-matrix }

Eine Zeile pro Kontrolle, der Mechanismus, der sie erfüllt, und der Test, der sie
hält. Eingeordnet gegen die technischen Schutzmaßnahmen nach HIPAA §164.312 und
SOC 2 CC6–CC8.

### Zugriffskontrolle · HIPAA §164.312(a) · SOC 2 CC6 { #access-control-hipaa-164312a-soc-2-cc6 }

| Kontrolle | Mechanismus | Gehalten von |
|---|---|---|
| Mandantentrennung, auch wenn der Aufrufer die Zeile besitzt | `resolve_access` verweigert eine Ressource mit abweichender `organization_id` vor der Eigentumsprüfung (`app/services/access.py`) | `test_resource_access.py::TestTenantBoundary`, `test_conversation_tenant_isolation.py`, `test_platform_flows.py` |
| Eine Berechtigung auf jeder Collection-Route | Route-Dependency `require(*perms)` auf Listen-, Erstellungs- und Katalogrouten (`app/api/deps.py`), Katalog in `app/core/permissions.py` | `test_platform_routes.py::TestEachRouteDemandsItsOwnPermission` |
| Routen pro Ressource autorisieren im Service, nicht auf der Route | Eine Route, die auf einem Agent, Skill oder einer Collection arbeitet, trägt kein `require()`-Gate — ein Rollen-Gate würde einen Grant-Inhaber abweisen, bevor der Grant greift — und ruft stattdessen `resolve_access` (`app/services/access.py`) | `test_platform_routes.py::TestEveryPlatformRouteIsGuarded` (jede Route ist gegated oder wird im Service entschieden) |
| Ein Grant erweitert den Zugriff, ohne das Mitglied zu befördern | `resolve_access` pro Ressource nimmt `max(Rollen-Scope, Grant)` (`app/services/access.py`) | `test_resource_access.py::TestGrantsWidenAccess`, `::TestPermissionsGrantsCannotWiden` |
| Eine Kanal-Erwähnung läuft als der Absender, nicht als der Bot | Der eigene `AuthContext` eines verknüpften, aktiven Absenders wird verwendet (`app/services/channels/mentions.py`) | `test_channel_mentions.py::TestAnswer::test_the_run_carries_the_senders_own_role` |

### Authentifizierung · HIPAA §164.312(d) · SOC 2 CC6 { #authentication-hipaa-164312d-soc-2-cc6 }

| Kontrolle | Mechanismus | Gehalten von |
|---|---|---|
| JWT (HS256), bcrypt-Passwörter | `app/core/security.py` — `verify_token`, `get_password_hash` | `test_security.py`, `test_auth.py` |
| API-Keys in konstanter Zeit verglichen | `secrets.compare_digest` (`app/api/deps.py`) | `test_auth.py`, HMAC-Prüfungen der Webhooks in den Kanal-Adaptern |
| DB-gestützte Sessions mit Widerruf | Tabelle `sessions` + `SessionService`; Token an einen `sid`-Claim gebunden (`app/services/session.py`, `app/api/routes/v1/sessions.py`) | `test_session_verify.py`, `test_session_revocation.py` |
| Rate-Limiting beim Login | `enforce_auth_limit` (`app/api/deps.py`) | `test_auth_rate_limit.py` |

### Audit-Kontrollen · HIPAA §164.312(b) · SOC 2 CC7 { #audit-controls-hipaa-164312b-soc-2-cc7 }

| Kontrolle | Mechanismus | Gehalten von |
|---|---|---|
| Governance-relevante Mutationen werden in der Transaktion der Anfrage festgehalten | `record_audit` (`app/core/audit.py`) im mutierenden Service — Secret-Rotation, Skill-/Sync-/MCP-Bindung, Mitgliedschaft, Freigabe, Freigaben, Exporte und mehr; geschrieben nach `app_admin_audit_logs`. Es ist keine flächendeckende Abdeckung jedes Schreibvorgangs (das CRUD der Wissensbasis etwa wird nicht auditiert) | `test_skill_binding_audit.py`, `test_sync_source_audit.py` |
| Die Spur ist für einen Auditor lesbar | `GET /audit`, gegated auf `audit:read` (`app/services/audit.py`) | `test_audit_service.py` |
| Export der Spur (CSV/JSONL) | `GET /audit/export` über ein Fenster, auf `audit:read` gegated, hält den eigenen Abruf in der Spur fest; die Run-, Freigabe- und Spend-Exporte tun dasselbe (#1422) | `test_exporting.py` (der Export und sein eigener Audit-Eintrag) |
| Manipulationsnachweis (eine Hash-Kette) | **Noch nicht** — [#1622](https://github.com/vstorm-co/agenticos/issues/1622) | — |

### Integrität · HIPAA §164.312(c) · SOC 2 CC8 (Change Management) { #integrity-hipaa-164312c-soc-2-cc8-change-management }

| Kontrolle | Mechanismus | Gehalten von |
|---|---|---|
| Ein Spec wird beim Veröffentlichen abgewiesen, nie zur Laufzeit | `validate_spec` (`app/services/agent_registry.py`) — unbekannte Capability, nicht gewährter Scope, `secret_id` der falschen Art oder aus einer anderen Organisation, eine persönliche MCP-Verbindung | `test_agent_registry.py`, `test_capability_secrets.py::TestPublishValidation` |
| Ein Budget wird vor der Modellanfrage geprüft, und Kosten werden auch bei einem Fehler festgehalten | `BudgetGuard.wrap_model_request` gated vor dem Aufruf (`app/agents/capabilities/budget/`); die Kosten des Runs werden in einem abschließenden `finally` geschrieben (`app/services/agent_runner.py`) | `test_spend.py::TestBudgetGuard`, `test_agent_runner.py::…::test_a_failed_run_still_records_its_cost` |
| Eine Freigabe wird genau einmal entschieden | `ApprovalService.decide` weist eine nicht mehr ausstehende Zeile ab, die `for_update` gelesen wurde (`app/services/approvals.py`) | `test_approvals_queue.py::TestDecidingTwiceIsRefused` |

### Vertraulichkeit von Credentials · HIPAA §164.312(a)(2)(iv) { #confidentiality-of-credentials-hipaa-164312a2iv }

| Kontrolle | Mechanismus | Gehalten von |
|---|---|---|
| Kein Secret im Klartext in einer API-Antwort oder einem Audit-Eintrag | `SealedStr`/`CredentialStr` maskieren jedes repr; Hinweise sind nur die letzten 4 Zeichen (`app/core/secret_kinds.py`, `app/core/vault.py`) | `test_no_secret_escapes.py` (durchkämmt die gesamte OpenAPI-Oberfläche), `test_capability_secrets.py::TestInjection` |
| Logs sind nicht Teil dieser Zusage | Eine fehlerhafte MCP-OAuth-Token-Antwort erreicht die Logs über einen Pydantic-`ValidationError`, der seine Eingabe wiedergibt — eine bekannte Lücke, [#1626](https://github.com/vstorm-co/agenticos/issues/1626) | `test_mcp_connections.py::test_an_unreadable_token_response_does_not_echo_its_input` (hält fest, dass das Token in `caplog` landet) |
| Ein Credential ist im Ruhezustand an seine Organisation gebunden | HKDF-Umschlag pro Eigentümer (`app/core/vault.py`); der Geltungsbereich sind Konnektor- und API-Credentials — zu den Bearer-Token, die er nicht abdeckt, siehe „Was wo verschlüsselt ist“ | `test_secret_tenant_isolation.py`, `test_vault.py` |

### Übertragungssicherheit · HIPAA §164.312(e) · SOC 2 CC6 { #transmission-security-hipaa-164312e-soc-2-cc6 }

| Kontrolle | Mechanismus | Gehalten von |
|---|---|---|
| TLS zu PostgreSQL und Redis | `POSTGRES_SSLMODE`, `REDIS_SSL` (`app/core/config.py`); `doctor` meldet den Live-Zustand von Postgres aus `pg_stat_ssl` | Postgres, an einer echten Verbindung: `test_store_tls.py`; Redis, beim Bau der URL und in `doctor`: `test_config.py`, `test_doctor_sandbox.py` |
| Framing- und MIME-Header auf jeder Antwort; CSP auf allen außer den API-Referenz-Endpunkten | `SecurityHeadersMiddleware` (`app/core/middleware.py`), dessen `exclude_paths` die CSP fallen lassen — nicht Framing oder MIME — für OpenAPI, Swagger und ReDoc; dazu die eigene CSP des Frontends pro Deployment (`frontend/src/middleware.ts`), deren `script-src` eine Nonce pro Request und `'strict-dynamic'` trägt statt `'unsafe-inline'` | `test_security_headers.py`, inkl. `test_an_excluded_path_keeps_its_framing_but_drops_the_csp`; `csp.test.ts`, `middleware.test.ts` |
| HTTPS und HSTS | Am Reverse Proxy terminiert — die mitgelieferte `nginx/nginx.conf` setzt HSTS; die Anwendung bewusst nicht | Sache des Deployments; siehe die Härtungs-Checkliste |
| Rate-Limits auf öffentlichen Oberflächen | Redis-gestützte Limits auf der Run-API, dem Embed-Widget und den gehosteten Seiten (`app/services/rate_limit.py`); Limits pro Absender auf Kanal-Bots (`app/services/channels/router.py`) | `test_rate_limited_surfaces.py`; das Limit der Kanal-Bots ist implementiert, aber dünn getestet |

### Die Refusals als Menge { #the-refusals-as-a-set }

Die Refusal-Tests oben tragen den `security`-Marker. `make test-security` führt
die ganze Menge aus, und CI veröffentlicht die gesammelte Liste bei jedem
Backend-Lauf als Artefakt `security-tests.txt` (#1417) — die Refusals lassen sich
also zählen und lesen, statt geglaubt zu werden. Ein Test, dessen Name oder Modul
einen Mandanten, eine Berechtigung, ein Budget, eine Freigabe, ein Secret oder
Klartext erwähnt und den Marker nicht trägt, lässt
`tests/test_security_marker.py` fehlschlagen, was die Liste vollständig hält,
während die Suite wächst.

## Fazit { #recap }

- Vertraue der Infrastruktur des Betreibers; vertraue keiner Anfrage in sie
  hinein. Die Grenzen, auf die es ankommt, sind Browser → BFF → API → Speicher
  und API/Worker → Dritte. Das BFF reicht das Session-Cookie weiter; die API ist
  der Ort, an dem eine Anfrage geprüft wird.
- Die einzigen Daten, die das Deployment verlassen, sind die, deren Weggang es
  konfiguriert hat — Modell-Provider, Kanäle, MCP-Server, Such- und
  Embedding-Anbieter und Logfire — das optional ist und, sobald ein
  deploymentweites Token gesetzt ist, jeden Run traced, den der API-Prozess
  bedient, mit dem Inhalt jedes Agenten, der nicht `none` verlangt hat.
- Konnektor- und API-Credentials sind pro Organisation im einen Vault versiegelt;
  kurzlebige Bearer-Token und der übrige Inhalt im Ruhezustand (Nachrichten, RAG,
  Sandboxes) sind es nicht. Hochgeladene Dateien sind das, was sich bewegt hat:
  `FILE_STORAGE_BACKEND=s3` legt sie in einen Objektspeicher, der jeden
  Schreibvorgang verschlüsselt.
- Jede Kontrolle in der Matrix benennt einen Mechanismus und einen Test — und im
  selben Atemzug ihre Lücken: der Manipulationsnachweis verlinkt das Issue, das
  ihn bauen würde.
- Schwachstellen meldest du und die Härtungs-Checkliste führst du aus über
  [`SECURITY.md`](https://github.com/vstorm-co/agenticos/blob/main/SECURITY.md);
  lies [Datenschutz](data-protection.md) und [Lizenzen](licenses.md) neben dieser
  Seite.
