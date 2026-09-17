---
source_sha: "a16194cf5597"
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

## Was über eine Person gehalten wird, und was damit geschieht { #what-is-held-about-one-person-and-what-happens-to-it }

DSGVO Art. 15 fragt, was Sie über jemanden halten, und Art. 17 verlangt, es zu
entfernen. Beides beantwortet diese Tabelle, mit Absicht: ein Inventar, das eine
Tabelle für den Export nennt und beim Löschen vergisst, ist schlechter als keines,
weil es sich vollständig liest.

Die Linie, die es zieht, ist **über** jemanden gegen **erstellt von** jemandem.
Was über eine Person ist, geht mit ihr; was sie für die Organisation erstellt hat
— ein Agent, auf dem das Team arbeitet, eine Wissensdatenbank, ein gespeichertes
Credential — wird weitergereicht, denn das Konto einer Kollegin zu löschen darf
nicht den Agenten löschen, von dem das Team abhängt.

| Tabelle | Beim Löschen | Im Export | Warum |
|---|---|---|---|
| `users` | Gelöscht | Profil, ohne den Passwort-Hash | Das Konto selbst |
| `conversations`, `messages`, `tool_calls` | Kaskade | Von ihnen begonnene Threads, mit jeder Runde darin | Ihre eigenen, und ein Transkript ohne jede zweite Runde beantwortet nichts |
| `chat_files` | Kaskade; die Bytes werden nach dem Commit gelöst | Nicht aufgeführt | Die Zeile kaskadierte, die Datei nicht — also Daten, die nach einer Löschanfrage geblieben sind ([#1421](https://github.com/vstorm-co/agenticos/issues/1421)) |
| `message_ratings` | Kaskade | Ja | Eine geäußerte Meinung |
| `sessions` | Kaskade | Gerät, Adresse und Zeiten — nie das Credential, das ein Hash ist | Wo sie sich angemeldet haben |
| `conversation_favourites`, `dashboard_layouts`, `dashboard_presets`, `user_slash_commands` | Kaskade | Layouts und Kurzbefehle | Persönliche Einstellungen, für niemanden sonst bedeutsam |
| `agent_memory_files` (`owner_key = person:<id>`) | **Ausdrücklich bereinigt**, unter einer Sperre, die ein gleichzeitiger Schreibvorgang ebenfalls nimmt | Ja | Ein String-Schlüssel ohne Fremdschlüssel: nichts kaskadierte, jede Notiz überlebte das Konto — und ein Run, der währenddessen schreibt, hätte sie neu angelegt |
| `agent_workspaces` (`scope = user`) | **Ausdrücklich bereinigt** | Nein | `owner_ref` ist aus demselben Grund ein String wie `owner_key`, also folgt ihm keine Kaskade, und ein zustandsgestützter Workspace hält die Dateien selbst |
| `organization_members` | Kaskade | Welche Organisationen, als was, seit wann | Eine Zeile, die sie direkt benennt und die eine Administratorin ohnehin sieht |
| `channel_identities` | **Ausdrücklich bereinigt** | Ja | `SET NULL` ließ die Zeile mit einer Slack-ID, einem Benutzernamen und einem Anzeigenamen einer Person zurück, die es nicht mehr gibt, verknüpft mit niemandem |
| `agent_runs` | `SET NULL` — behalten | Runs, die sie gestartet haben, und was jeder kostete | Ausgaben sind die Aufzeichnung der Organisation; ein anonymer Run zählt weiter für den Monat |
| `agents`, `knowledge_bases`, `skills`, `contexts`, `agent_triggers`, `agent_environments`, `agent_exposures`, `local_services` | `SET NULL` — behalten | Nein | *Für die Organisation* erstellt. Sie zu entfernen nähme die Arbeit des Teams mit der Person mit |
| `organization_secrets` | `SET NULL`, ein privates Secret steigt zur Organisation auf | Nein | Ein Credential, auf dem die Organisation läuft. Der Aufstieg ist, was ein herrenloses Secret daran hindert, die Löschung zu blockieren |
| `organizations` | Persönliche Org gelöscht; eine geteilte, die sie erstellt haben, geht an einen anderen Owner | Nein | Niemand darf mit einer Organisation ohne Owner zurückbleiben |
| `resource_grants` | Kaskade beim Empfänger; `SET NULL` beim Erteilenden | Nein | Eine Berechtigung *für* sie ist ihre; eine, die sie *erteilt* haben, ist die Aufzeichnung der Organisation darüber, wer was darf |
| `app_admin_audit_logs` | **Behalten**, Akteurs-ID bleibt | **Nein** | Die Aufzeichnung der Organisation über das, was in ihr getan wurde. Ein Eintrag, der ein gelöschtes Konto nennt, ist ehrlich; einer mit entferntem Akteur ist schlimmer als nutzlos, und er gehört nicht der Person zum Mitnehmen |
| `embed_visitors` | Unberührt | Nein | Ein Besucher ist ein Browser-Schlüssel, nie ein Konto — hier steht nichts über eine Person mit Login |

!!! warning "Was die Löschung nicht erreicht — und die Doku sagt es, statt dass ein Deployment es herausfindet"

    **Ein konfigurierter externer Gedächtnisspeicher.** `mem0` hält das, was ein
    Agent sich gemerkt hat, im System eines Dritten, und dieses Deployment kann
    nur um Vergessen bitten, solange es das Credential der Organisation hat.
    `MemoryService.forget_person` tut das für eine Person, die noch Mitglied ist;
    die Notizen eines gelöschten Kontos in einem externen Speicher gehören dem
    Betreiber.

    **Backups.** Eine Löschung entfernt Zeilen aus der laufenden Datenbank. Der
    Backup-Zeitplan eines Deployments behält sie bis zu seiner Rotation, und
    keine Löschung auf Anwendungsebene ändert daran etwas.

    **Die eigene Aufbewahrung eines Modellanbieters.** Was gesendet wurde, um
    eine Runde zu beantworten, unterliegt der Richtlinie des Anbieters, die
    [Modelle](models.md) behandelt und dieses Deployment nicht kontrolliert.

### Selbstbedienung, und was eine Administratorin hinzufügt { #self-service-and-what-an-administrator-adds }

Für die gewöhnlichen Fälle braucht eine Person keine Administratorin.
`GET /me/data/export` ist die ganze obige Tabelle in einem JSON-Dokument,
stündlich limitiert und in der Audit-Spur festgehalten — auch wenn jemand sich
selbst exportiert, denn ein Export hat die Form eines Lecks, wenn der Aufrufer
nicht der ist, für den er sich ausgibt.

Es wird als Ganzes aufgebaut und
serialisiert und ist deshalb begrenzt: `PERSONAL_DATA_EXPORT_MAX_CHARS`
(standardmäßig 16 Millionen Zeichen) ist, wie viel Gesprächstext ein Dokument
tragen darf; ein Konto mit mehr wird mit beiden Zahlen abgewiesen statt mit einem
stillschweigend unvollständigen Dokument beantwortet. Dieses zu erzeugen, ist
Sache der Betreiberin, direkt aus der Datenbank. `DELETE /conversations/{id}` entfernt
einen Thread, seine Runden und die Dateien, die mit ihnen kamen, geprüft gegen
den eigenen Besitz des Aufrufers (FA-015).

Eine Administratorin fügt zwei Dinge hinzu, beide protokolliert:
`GET /admin/users/{id}/export`, das **eine Begründung verlangt** — die gesamte
Gesprächshistorie einer Kollegin zu lesen ist etwa zweimal im Jahr legitim und
jedes Mal ernst — und `DELETE /admin/users/{id}`, wo eine Begründung optional
ist, weil ein Offboarding meist nichts zu erklären hat.

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
| Single Sign-on gegen den eigenen Identitätsanbieter des Deployments | Generisches OIDC per Discovery — Authorization Code mit PKCE, `email_verified` erforderlich, das Konto an `sub` gebunden (`app/core/oauth.py`, `app/api/routes/v1/oauth.py`). Entra ID, Okta, Keycloak; konfiguriert unter [Single Sign-on](configuration.md#single-sign-on-generic-oidc) | `test_oidc_sign_in.py` |
| Die Registrierungsrichtlinie sichert SSO wie das Formular | `check_may_register` innerhalb von `get_or_create_oauth_user` — `invite_only` und die Domain-Erlaubnisliste weisen auch eine Anbieter-Anmeldung ab (`app/services/user.py`) | `test_oidc_sign_in.py::TestTheRoundTrip`, `test_signup_policy.py` |
| Gruppen-zu-Rollen-Zuordnung, SAML, SCIM | **Noch nicht** — Menschen melden sich über den Anbieter an, eine Administratorin ordnet sie ein | — |
| Rate-Limiting beim Login | `enforce_auth_limit` (`app/api/deps.py`) | `test_auth_rate_limit.py` |
| Ein wiedergespielter Refresh-Token beendet seine Kette und wird protokolliert | Die Rotation behält den ersetzten Hash; ein Refresh, der dazu passt, ist der Reuse-Fall aus RFC 6819 §5.2.2.3 und schließt diese Session mit einem Audit-Eintrag (`SessionService.detect_refresh_reuse`) | `test_session_revocation.py::TestReusingASpentRefreshToken` |

### Audit-Kontrollen · HIPAA §164.312(b) · SOC 2 CC7 { #audit-controls-hipaa-164312b-soc-2-cc7 }

| Kontrolle | Mechanismus | Gehalten von |
|---|---|---|
| Governance-relevante Mutationen werden in der Transaktion der Anfrage festgehalten | `record_audit` (`app/core/audit.py`) im mutierenden Service — Secret-Rotation, Skill-/Sync-/MCP-Bindung, Mitgliedschaft, Freigabe, Freigaben, Exporte und mehr; geschrieben nach `app_admin_audit_logs`. Es ist keine flächendeckende Abdeckung jedes Schreibvorgangs (das CRUD der Wissensbasis etwa wird nicht auditiert) | `test_skill_binding_audit.py`, `test_sync_source_audit.py` |
| Die Spur ist für einen Auditor lesbar | `GET /audit`, gegated auf `audit:read` (`app/services/audit.py`) | `test_audit_service.py` |
| Export der Spur (CSV/JSONL) | `GET /audit/export` über ein Fenster, auf `audit:read` gegated, hält den eigenen Abruf in der Spur fest; die Run-, Freigabe- und Spend-Exporte tun dasselbe (#1422) | `test_exporting.py` (der Export und sein eigener Audit-Eintrag) |
| Eine Audit-Frist, die eine Organisation verlängern und nie verkürzen kann | Eine deploymentweite Untergrenze (standardmäßig sechs Jahre, HIPAA §164.316(b)(2)); eine kürzere Frist wird abgelehnt statt angehoben. Der Sweep löscht **keine** Audit-Einträge - die Hash-Kette und ihr Checkpoint stehen darauf, dass Einträge bleiben, eine nachprüfbare Ausmusterung ist [#1622](https://github.com/vstorm-co/agenticos/issues/1622) (`app/core/retention.py`). Siehe [Aufbewahrung](governance.md#retention) | `test_retention.py::TestWhichNumberWins`, `::test_audit_resolves_to_a_period_and_is_still_not_swept` |
| Eine Person kann ihre eigenen Daten auslesen und entfernen | `GET /me/data/export` (stündlich limitiert, auch bei der eigenen Anfrage protokolliert) und `DELETE /conversations/{id}` im Rahmen des eigenen Besitzes; der Export einer Administratorin verlangt eine Begründung (`app/services/personal_data.py`) | `test_personal_data.py` |
| Manipulationsnachweis (eine Hash-Kette) | **Noch nicht** — [#1622](https://github.com/vstorm-co/agenticos/issues/1622) | — |

### Integrität · HIPAA §164.312(c) · SOC 2 CC8 (Change Management) { #integrity-hipaa-164312c-soc-2-cc8-change-management }

| Kontrolle | Mechanismus | Gehalten von |
|---|---|---|
| Ein Spec wird beim Veröffentlichen abgewiesen, nie zur Laufzeit | `validate_spec` (`app/services/agent_registry.py`) — unbekannte Capability, nicht gewährter Scope, `secret_id` der falschen Art oder aus einer anderen Organisation, eine persönliche MCP-Verbindung | `test_agent_registry.py`, `test_capability_secrets.py::TestPublishValidation` |
| Ein Budget wird vor der Modellanfrage geprüft, und Kosten werden auch bei einem Fehler festgehalten | `BudgetGuard.wrap_model_request` gated vor dem Aufruf (`app/agents/capabilities/budget/`); die Kosten des Runs werden in einem abschließenden `finally` geschrieben (`app/services/agent_runner.py`) | `test_spend.py::TestBudgetGuard`, `test_agent_runner.py::…::test_a_failed_run_still_records_its_cost` |
| Eine Freigabe wird genau einmal entschieden | `ApprovalService.decide` weist eine nicht mehr ausstehende Zeile ab, die `for_update` gelesen wurde (`app/services/approvals.py`) | `test_approvals_queue.py::TestDecidingTwiceIsRefused` |
| Statische Analyse erreicht die Änderung, die den Fund einführt | CodeQL (`security-extended`) bei jedem Pull Request für Python, JavaScript/TypeScript, Rust und die Workflows, dazu ein wöchentlicher vollständiger Lauf (`.github/workflows/codeql.yml`). Den Merge verweigert der Merge-Schutz durch Code Scanning im Ruleset von `main`, nicht der Status des Jobs selbst — siehe [Branches](branching.md#what-is-enforced-and-by-what) | `test_codeql_workflow.py` |
| Eine bekannt verwundbare Abhängigkeit lässt den Pull Request scheitern | `make audit` über `backend/uv.lock` und `make audit-frontend` über `frontend/bun.lock`, beide im Job `Security Scan` und in `make check` | `test_ci_parity.py` |
| Was ein Release enthält, ist lesbar ohne es zu bauen | Ein CycloneDX-SBOM pro Image, erzeugt aus dem veröffentlichten Manifest und an das Release angehängt; [das Komponenteninventar](reference/components.md) ist der lesbare Index | `test_images_workflow.py::TestTheReleaseCarriesAnInventory` |

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

## Das HIPAA-Profil, und was es nicht behauptet { #the-hipaa-profile-and-what-it-does-not-claim }

Eine Sicherheitsprüfung fragt nicht „ist diese Software konform“. HHS
zertifiziert keine Software, und OCR erkennt keine private Zertifizierung an. Sie
fragt **können wir das in unserer konformen Umgebung betreiben, und lässt sich
das belegen** - und die Antwort ist eine mitgelieferte Konfiguration plus ein
Befehl, der ein laufendes Deployment dagegen prüft (#1448).

```bash
uv run agenticos cmd doctor --profile hipaa
```

Eine Zeile je Kontrolle, jede mit der Einstellung, die sie erfüllt, oder der, die
es nicht tut, und ein Exit ungleich null bei jedem Fehlschlag, damit es in der CI
einer Kundin laufen kann. Die Konfiguration ist `deploy/profiles/hipaa/`: ein
Compose-Overlay, das ohne die Einstellungen, die es nicht vorbelegen kann, gar
nicht erst startet, und eine kommentierte Env-Datei.

**Diesen Absatz im selben Atemzug mit dem Profil lesen.** Es beantwortet die
**technischen** Sicherungen, §164.312, und nur diese. Administrative Sicherungen
(§164.308 - Risikoanalyse, Schulung, Sanktionsrichtlinie, Notfallplan,
Business-Associate-Verträge) und physische (§164.310) gehören der Betreiberin und
werden es bleiben. Ein Profil, das anderes nahelegt, wäre eine Behauptung, die
niemand stützen kann.

### Das Blatt { #the-sheet }

| Kontrolle | Sicherung | Erfüllt durch |
|---|---|---|
| `postgres-tls` | §164.312(e)(1) | `POSTGRES_SSLMODE=verify-full`. `require` verschlüsselt und prüft kein Zertifikat, das Profil nimmt es deshalb nicht |
| `redis-tls` | §164.312(e)(1) | `REDIS_SSL=true`. Beide Stores müssen Ihre eigenen sein: die mitgelieferten `db` und `redis` haben keinen TLS-Listener, also startet das Overlay ohne `POSTGRES_HOST` und `REDIS_HOST` nicht |
| `browser-tls` | §164.312(e)(1) | `FRONTEND_URL` und `PUBLIC_BASE_URL` über https, terminiert von Ihrem Reverse Proxy. Attestiert, und eine http-Adresse wird hier **abgelehnt**: jede andere Kontrolle kann bestehen, während eine Anmeldung im Klartext über die Client-Grenze geht |
| `vault-key` | §164.312(a)(2)(iv) | Ein Vault-Masterschlüssel von mindestens 64 Zeichen. HKDF leitet aus allem einen richtig dimensionierten Wrapping-Key ab und kann einem ratbaren Geheimnis keine Entropie hinzufügen |
| `content-at-rest` | §164.312(a)(2)(iv) | **Der Betreiberin.** Postgres-Daten, das Medien-Volume und das Sandbox-Workspace-Verzeichnis verschlüsselt ein Volume oder eine Platte, nicht diese Anwendung |
| `local-model` | §164.312(e)(1) | Jedes Modellprofil aus dem eigenen Netz. Geparst wird der **Hostname** - eine private Adresse, `localhost`, ein bloßes `ollama`/`litellm`/`vllm` oder ein `.internal`/`.local`/`.svc`-Name - `https://ollama.vendor.example` ist also nicht lokal, und eines ohne `base_url` ist per Definition die öffentliche API des Anbieters |
| `traces-local` | §164.312(e)(1) | Nicht gesetztes `LOGFIRE_TOKEN` **und** kein veröffentlichter Agent und keine benannte Umgebung mit eigenem Tracing-Token - jedes hängt einen eigenen Exporter an, und `observability.content` ist standardmäßig `full` |
| `sso` | §164.312(d) | `OIDC_ISSUER`. **Noch nicht verfügbar** - generisches OIDC-Sign-in ist [#1419](https://github.com/vstorm-co/agenticos/issues/1419), diese Kontrolle ist heute also auf jedem Deployment unerfüllt, was der Wahrheit über eines entspricht, auf dem man sich mit Passwörtern anmeldet. Mehrfaktor-Authentifizierung ist Sache des Identitätsanbieters, und das Blatt sagt es, statt es zu behaupten |
| `signup` | §164.312(a)(1) | `invite_only` oder `closed` |
| `audit-retention` | §164.312(b) | Eine Audit-Untergrenze von mindestens 2190 Tagen - die sechs Jahre aus §164.316(b)(2) |
| `audit-chain` | §164.312(c)(1) | Die Hash-Kette und ihr Checkpoint. Erkennung, nicht Verhinderung - siehe [Audit-Kontrollen](#audit-controls-hipaa-164312b-soc-2-cc7) |

Drei Ergebnisse, und das mittlere wiegt. `ok` und `!!` sind die Antworten dieses
Codes. `--` ist eine Kontrolle, die wirklich der Betreiberin gehört, **benannt**
statt still bestanden - ein Blatt, das überginge, was es nicht sehen kann, läse
sich als vollständig und wäre es nicht - und sie lässt den Befehl nicht
fehlschlagen, denn eine Kontrolle, die von hier niemand belegen kann, ist eine,
die nie jemand bestehen könnte.

### Wer die Business Associate ist { #who-is-the-business-associate }

Eine Kundin, die das auf eigener Infrastruktur betreibt, bekommt Software.
Niemand hier fasst ihre PHI an, und es braucht keinen Vertrag. Ein Deployment,
das jemand anders für sie betreibt, macht diesen jemand zur Business Associate -
und das ist ein Vertrag, kein Konfigurationsschalter.

### Warum das Profil auf ein lokales Modell setzt { #why-the-profile-defaults-to-a-local-model }

Ein gehostetes Modell nimmt den Inhalt jedes Laufs mit, seine Nutzung bedeutet
also einen Vertrag mit diesem Anbieter - und diese Verträge sind enger, als man
erwartet. Eine HIPAA-fähige Organisation bei einem großen Anbieter schließt
typischerweise Codeausführung und Web-Abrufe aus, also genau die Form der
Capabilities `sandbox`, `code_execution` und `web_fetch`. Wer so einen Vertrag
unterschreibt und dann einen Agenten darauf baut, erfährt es während eines
Vorfalls.

Lokale Inferenz nimmt die Frage weg, und deshalb ist sie die Vorgabe des Profils
und kein Vorschlag.

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
