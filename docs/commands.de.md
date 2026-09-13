---
source_sha: 7e69c0532818
---

# Befehle { #commands }

Dieses Projekt stellt Befehle über zwei Schnittstellen bereit: **Make**-Targets für
gängige Abläufe und ein **Projekt-CLI** für die feinkörnige Steuerung.

## Make-Befehle { #make-commands }

Führen Sie diese aus dem Wurzelverzeichnis des Projekts aus.

### Schnellstart { #quick-start }

| Befehl | Beschreibung |
|---------|-------------|
| `make quickstart` | Docker starten, Migrationen ausführen, Admin-Nutzer anlegen. Installiert **keine** Abhängigkeiten — zuerst `make install` |
| `make install` | Der gesamte Einrichtungsweg: `backend/.env` aus dem Beispiel, falls keine existiert, Backend-Abhängigkeiten mit uv, `frontend/node_modules` mit bun, und die Pre-commit-Hooks. All das, weil `make check` all das braucht — `db-check` liest die env-Datei, und eslint, prettier, tsc, vitest und next leben nur in `node_modules`. Beide gelten pro Checkout, das ist also bei jedem Klon fällig; eine bestehende `.env` wird nie überschrieben |

### Entwicklung { #development }

| Befehl | Beschreibung |
|---------|-------------|
| `make run` | Entwicklungsserver mit Hot Reload starten |
| `make run-prod` | Produktionsserver starten (0.0.0.0:8000) |
| `make routes` | Alle registrierten API-Routen anzeigen |
| `make test` | Backend-Suite plus das 100%-Gate auf der Plattformschicht. Läuft über mehrere Worker-Prozesse (`-n auto --maxprocesses 4`); `pytest-cov` führt deren Daten zusammen, das Gate bleibt also unverändert |
| `make test-cov` | Tests mit Coverage-Bericht ausführen (HTML + Terminal). Läuft über mehrere Worker-Prozesse wie `make test` |
| `make format` | Code automatisch formatieren — ruff im Backend, prettier im Frontend |
| `make lint` | Jede statische Prüfung: ruff, ruff format, ty, vulture, deptry, eslint, prettier, tsc, die Guard-Skripte (Backtick, i18n, Routen, Banner-Kommentare), knips Abhängigkeitsprüfung und codespell über den gesamten Baum |
| `make lint-backend` / `make lint-frontend` | Eine Hälfte des Obigen. CI führt sie in zwei verschiedenen Jobs aus, jede lässt sich also einzeln ausführen |
| `make dead-code` | Ungenutzte Funktionen und Methoden — vulture mit einer niedrigeren Konfidenz als das `lint`-Gate, dazu knips vollständiger Bericht zum Frontend. Ein Bericht zum Lesen, kein Gate: in einer registry-getriebenen Codebasis kommt er mit False Positives (ein CLI-Befehl, ein Capability-Hook), lesen Sie also jeden, bevor Sie löschen. Dieselbe Rolle, die `dependency-freshness` für Abhängigkeiten spielt. Seine eine eindeutige Hälfte — ein Paket in `package.json`, das nichts importiert — sperrt stattdessen in `lint-frontend` (`bun run lint:deps`), denn eine Abhängigkeit, die monatelang ungenutzt überlebt hat, ist der Anlass dafür |
| `make lint-spelling` | codespell über jede versionierte Datei. Der Pre-commit-Hook liest nur die Dateien, die ein Commit berührt, ein Rechtschreibfehler, der mit seiner Datei landet, wartet dort also darauf, den unzusammenhängenden Commit von jemand anderem abzulehnen |
| `make lint-precommit` | yamlfmt, zizmor und die Grundlagen aus `pre-commit-hooks` über jede versionierte Datei. Derselbe Grund wie bei `lint-spelling` — diese Hooks arbeiten pro Datei, ein `rev:`-Sprung, der eine neue Regel mitbringt, macht den Baum also kaputt, ohne dass etwas es bemerkt. `SKIP` lässt die Hooks weg, die `lint-backend`/`lint-frontend`/`lint-spelling` bereits absichern, es verdoppelt ihre Zeit also weder noch lässt es einen Fixer eine Datei mitten in der Prüfung umschreiben |
| `make build-frontend` | `next build`. Typprüft den Routenbaum und schlägt bei einer Server-Komponente fehl, die nicht rendern kann — was weder tsc noch vitest sieht |
| `make desktop-dev` / `make desktop-build` | Die Desktop-Hülle öffnen oder paketieren - ein Tauri-Fenster um eine Konsole, die Sie über ihre Adresse benennen. Braucht Rust und die Webview der Plattform; `docs/desktop.md` hat den Rest |
| `make desktop-check` | `bun test` über das Pet, dann rustfmt, clippy mit Warnungen als Fehler und die Rust-Tests der Hülle. Nicht in `lint` oder `check`, denn CI hat noch keine Rust-Toolchain |
| `make audit` | Den gesperrten Abhängigkeitssatz auf bekannte Schwachstellen prüfen. Braucht das Netzwerk — ein Request pro gesperrter Distribution — seine letzte Zeile sagt deshalb, in welchem von vier Zuständen er geendet hat, statt einen roten Lauf mehrdeutig zu lassen. Siehe unten |
| `make sandbox-token` | Den eigenen `SANDBOXD_TOKEN` des Sandbox-Services einmalig in `backend/.env` erzeugen. `make dev` führt es für Sie aus; es erzeugt nie neu, denn ein neuer Token verwaist jeden Workspace, den der Service hält. Das Connection-Formular bietet an, denselben Wert im Vault abzulegen, er muss also nirgendwohin eingefügt werden |
| `make clean` | Cache-Dateien entfernen (__pycache__, .pytest_cache usw.) |

### Vor einem Pull Request { #before-a-pull-request }

!!! success "`make check` ist jeder CI-Job außer `e2e`"

    Die Gleichheit wird gepflegt statt behauptet, und
    `backend/tests/test_ci_parity.py` ist das, was sie wahr hält. Sie ist viermal
    auseinandergelaufen.

`.github/workflows/ci.yml` ruft dieselben Make-Targets auf, statt ihre Befehle zu
wiederholen, ein sperrender Job, der um einen Schritt wächst, den `check` nicht
ausführt, lässt den Paritätstest also fehlschlagen — und umgekehrt ebenso.

```bash
make check   # lint, test, db-check, test-frontend-cov, build-frontend, docs-build, audit
```

Etwa fünf Minuten, seriell, auf einem warmen Cache. Was er absichtlich auslässt:

| Nicht in `check` | Warum, und was stattdessen auszuführen ist |
|---|---|
| `e2e` | Braucht eine migrierte Datenbank, eine bereitgestellte Organisation und ein laufendes Backend: `make dev && make platform-bootstrap && make test-e2e` |
| Der Image-Build, das Veröffentlichen und der Trivy-Scan | `.github/workflows/images.yml` führt die bei einem Push auf `main` und bei einem `v*`-Tag aus und veröffentlicht nach GHCR |
| `make test-migrations` | CI durchläuft die Kette gegen eine Wegwerf-`test_db`. Auf einem Laptop zeigt `alembic downgrade base` auf das, was `backend/.env` sagt, was üblicherweise die Datenbank mit Ihrer eigenen Arbeit darin ist — `uv run pytest tests/test_migrations.py` stellt dieselbe Frage gegen eine eigene Datenbank, und `make test` führt es bereits aus |

!!! warning "Eine Lücke, die kein Befehl schließen kann"

    Der `test`-Job von CI hat ein Postgres daneben, `tests/integration/` läuft dort
    also; lokal überspringt sich die Suite selbst, wenn auf 5432 nichts antwortet.
    `make check` sagt das am Ende, wenn es passiert — führen Sie zuerst
    `make docker-db` aus, wenn die Änderung irgendwo in der Nähe der Datenbank ist.

### Was ein rotes `make audit` bedeutet { #what-a-red-make-audit-means }

`make audit` exportiert das, worauf die Lockfile auflöst — was ein Deployment
installiert — und übergibt es an `pip-audit`, das den Schwachstellen-Feed der Reihe
nach zu jeder der 254 gesperrten Distributionen befragt. `pip-audit` allein kann
nicht sagen, welche von zwei sehr verschiedenen Sachen schiefgegangen ist: es endet
mit 1, ob es eine Meldung gefunden hat oder beim Abruf an einem `ReadTimeout`
gestorben ist, und `Security Scan` ist eine erforderliche Prüfung, eine langsame
Antwort von 254 blockiert also einen Merge, während sie sich genau wie ein echter
Fund liest, bis jemand das Log öffnet
([#855](https://github.com/vstorm-co/agenticos/issues/855)).

`scripts/audit_dependencies.py` steht zwischen beiden und **beendet jeden Lauf auf
einer Zeile**:

```
AUDIT: CLEAN — no known advisories against 254 locked dependencies
AUDIT: VULNERABLE — 6 known advisories in 1 of 254 locked dependencies
AUDIT: NETWORK — unreachable (ReadTimeout) after 3 attempts; no audit was performed
AUDIT: FAILED — pip-audit reached no verdict in 3 attempts and did not say why; no audit was performed
```

| Zustand | Bedeutet | Was zu tun ist |
|---|---|---|
| `CLEAN` | Jede gesperrte Abhängigkeit wurde geprüft, keine hat eine bekannte Meldung | Nichts |
| `VULNERABLE` | Eine gesperrte Abhängigkeit hat eine bekannte Meldung. Ids, behobene Versionen und CVE-Aliase werden über dem Urteil ausgegeben | Aktualisieren Sie sie |
| `NETWORK` | Es fand keine Prüfung statt, und die Ursache war erkennbar das Netzwerk | Erneut ausführen |
| `FAILED` | Es fand keine Prüfung statt, und die Ursache wurde nicht erkannt. Die Ausgabe von pip-audit steht auf stderr | Lesen Sie diese Ausgabe |

**Eine Zeile, kein Exit-Code, denn make kann keinen tragen.** GNU Make verwandelt
jedes fehlgeschlagene Rezept in seinen eigenen Exit 2, `make audit` gibt also für
`VULNERABLE` und für `NETWORK` gleichermaßen 2 zurück, und es gibt keine
Target-Form, die das ändert. Alles, was das Ergebnis über diese Schnittstelle liest
— den `Security Scan`-Job eingeschlossen — liest die Zeile: `make audit | tail -1`
oder `make audit 2>&1 | grep '^AUDIT:'`. Innerhalb eines GitHub-Jobs wird dieselbe
Zeile an `$GITHUB_STEP_SUMMARY` angehängt, die Übersichtsseite des Laufs sagt also,
in welchem Zustand er war, ohne dass jemand das Log öffnet.

Direkt aufgerufen trägt `scripts/audit_dependencies.py` ihn sehr wohl: `0` für
`CLEAN`, `1` für `VULNERABLE`, `75` (`EX_TEMPFAIL`) für `NETWORK` und `FAILED`
gleichermaßen — eine Prüfung, die nicht stattgefunden hat, wird nie grün gemeldet,
denn ein ungeprüfter Abhängigkeitssatz, der sauber genannt wird, ist derselbe Defekt
mit dem Gesicht zur anderen Seite.

**Jeder unvollständige Lauf wird wiederholt, was auch immer er gesagt hat.**

`AUDIT_ATTEMPTS` (Voreinstellung 3) mit einem Backoff von 5 s/10 s, und
`AUDIT_TIMEOUT` (Voreinstellung 30 s) als Socket-Timeout pro Request, angehoben von
den 15 von pip-audit.

Ob eine Formulierung in der Ausgabe passt, entscheidet nur darüber, ob das Urteil
`NETWORK` oder `FAILED` lautet — nie darüber, ob es einen weiteren Versuch gibt. Die
beiden Fehler sind nicht symmetrisch: ein deterministisches Scheitern erneut
auszuführen kostet Sekunden und dieselbe Antwort, während ein vorübergehendes
*nicht* erneut auszuführen das falsche Rot auf einer erforderlichen Prüfung ist, das
zu verhindern es dies gibt.

Ein Fehlschlag, der in Worten formuliert ist, die die Liste nicht führt, bekommt
seine Wiederholungen also trotzdem. Er bekommt nur einen vageren Namen.

Zwei Vokabulare stehen in dieser Liste, denn zwei Programme greifen zum Netzwerk:
`uv`, das `pip-audit` selbst bei kaltem Tool-Cache holt, und dann `pip-audit`, das
die Meldungen holt.

### Datenbank { #database }

| Befehl | Beschreibung |
|---------|-------------|
| `make db-init` | PostgreSQL starten + erste Migration anlegen + anwenden |
| `make db-migrate` | Neue Migration anlegen (fragt nach einer Meldung) |
| `make db-upgrade` | Ausstehende Migrationen anwenden |
| `make db-check` | `alembic check` — schlägt fehl, wenn eine Modelländerung keine Migration hat. Nicht destruktiv (es stuft nie zurück), es läuft also anders als `test-migrations` innerhalb von `make check`; braucht eine Datenbank auf head und überspringt sich, statt fehlzuschlagen, wenn auf 5432 nichts antwortet. Die `rag_<collection>`-Tabellen des Vektorspeichers, eine pro Collection, sind vom Vergleich ausgenommen, da nichts sie modelliert oder migriert — `rag_documents`, das eine Modelltabelle ist, ist es nicht |
| `make db-downgrade` | Letzte Migration zurückrollen |
| `make db-current` | Aktuelle Migrationsrevision anzeigen |
| `make db-history` | Vollständige Migrationshistorie anzeigen |

### Nutzer { #users }

| Befehl | Beschreibung |
|---------|-------------|
| `make create-admin` | Admin-Nutzer anlegen (interaktiv) |
| `make user-create` | Neuen Nutzer anlegen (interaktiv) |
| `make user-list` | Alle Nutzer auflisten |

### Prefect { #prefect }

Prefect läuft im Dev-Stack als zwei Container — sie starten automatisch mit `make dev`:

- **`prefect-server`** — Orchestrierungs-API + Web-UI unter <http://localhost:4200>
- **`prefect-runner`** — registriert die geplanten Deployments und fragt nach Arbeit

Der Runner ist `python -m app.worker.prefect_app`; Flows liegen in `app/worker/tasks/`.
Öffnen Sie die UI, um Flow-Läufe zu beobachten, Logs zu prüfen und Deployments von
Hand auszulösen.
Standardmäßig selbst gehostet — setzen Sie `PREFECT_API_KEY` (und eine Cloud-`PREFECT_API_URL`), um stattdessen Prefect Cloud zu nutzen.

### Docker (Entwicklung) { #docker-development }

| Befehl | Beschreibung |
|---------|-------------|
| `make docker-up` | Alle Backend-Services starten |
| `make docker-down` | Alle Services stoppen |
| `make docker-logs` | Backend-Logs verfolgen |
| `make docker-build` | Backend-Images bauen |
| `make docker-shell` | Shell im App-Container öffnen |
| `make docker-frontend` | Die Konsole starten (in einem Klon hinter dem Profil `console`) |
| `make docker-frontend-down` | Frontend stoppen |
| `make docker-frontend-logs` | Frontend-Logs verfolgen |
| `make docker-frontend-build` | Frontend-Image bauen |
| `make docker-db` | Nur PostgreSQL starten |
| `make docker-db-stop` | PostgreSQL stoppen |
| `make docker-redis` | Nur Redis starten |
| `make docker-redis-stop` | Redis stoppen |

### Docker (Produktion mit Traefik) { #docker-production-with-traefik }

| Befehl | Beschreibung |
|---------|-------------|
| `make docker-prod` | Produktions-Stack starten |
| `make docker-prod-down` | Produktions-Stack stoppen |
| `make docker-prod-logs` | Produktions-Logs verfolgen |

### Vercel (Frontend-Deployment) { #vercel-frontend-deployment }

| Befehl | Beschreibung |
|---------|-------------|
| `make vercel-deploy` | Frontend nach Vercel deployen |

---

## Projekt-CLI { #project-cli }

Alle Befehle des Projekt-CLI werden so aufgerufen:

```bash
cd backend
uv run agenticos <group> <command> [options]
```

### Server-Befehle { #server-commands }

```bash
uv run agenticos server run              # Start dev server
uv run agenticos server run --reload     # With hot reload
uv run agenticos server run --port 9000  # Custom port
uv run agenticos server routes           # Show all registered routes
```

`--reload` führt den Reloader von uvicorn unter einem eigenen Supervisor aus
(`backend/cli/reload_supervisor.py`), denn der von uvicorn ist ein Datei-Watcher und
nichts weiter: wenn der Kernel den Worker tötet — ein Out-of-Memory-Kill ist der
realistische Weg — räumt er ihn weder ab noch ersetzt er ihn, der Reloader beobachtet
also weiter, während kein Port lauscht. Unter dem Supervisor wird ein von einem Signal
getöteter Worker innerhalb von etwa fünf Sekunden ersetzt, und einer, der von selbst
beendet wurde, wartet weiterhin auf die Bearbeitung, die ihn repariert, wofür
`--reload` da ist.

Er ersetzt außerdem einen Worker, der **verklemmt** ist — am Leben, aber mit einer
Event Loop, die sich nicht mehr dreht, was keinen Exit-Code hat und deshalb für
jeden anderen Wiederherstellungsweg gesund aussieht.

Der Worker meldet seine Loop einmal pro Sekunde über den `callback_notify`-Hook von
uvicorn, und ein Worker, der über zwei aufeinanderfolgende Abfragen hinweg fünfzehn
Sekunden lang schweigt, wird getötet und ersetzt. Etwa fünfundzwanzig Sekunden vom
Deadlock bis zum erneuten Ausliefern.

Zwei Abfragen statt einer, denn `docker pause` und ein aus dem Schlaf erwachender
Laptop stoppen den Supervisor ebenso wie den Worker, und die erste Abfrage danach
liest einen veralteten Herzschlag, der nichts aussagt.

Das ist **Liveness und nicht Readiness**, mit Absicht: der Herzschlag ist ein
Timer-Callback und kein Request, eine langsame Datenbank kann einen gesunden Server
also nicht verklemmt aussehen lassen.

| | |
|---|---|
| `EVENT_LOOP_WEDGED_AFTER` | Sekunden des Schweigens, bevor ein Worker ersetzt wird. Voreinstellung `15`; `0` oder darunter schaltet die Prüfung ab |

Schalten Sie sie beim Debuggen ab. Ein Breakpoint blockiert die Event Loop und keine
Probe kann das von einem Deadlock unterscheiden, ein Worker, der auf einem sitzt,
wird Ihnen also unter den Händen ersetzt.

Dieselbe Variable wird vom Worker selbst gelesen, der seine eigene Event Loop
beobachtet und seinen eigenen Prozess tötet — das deckt den Dev- und den
Produktions-Stack ab, wo es keinen Supervisor gibt, der einen Herzschlag von außen
liest. Eine Zahl, die Prüfung für einen Breakpoint abzuschalten schaltet also beide
Richter ab.
[Konfiguration](configuration.md#a-worker-whose-event-loop-has-stopped-turning)
hat das ganze Bild.

`server run` wählt außerdem in beiden Modi die Implementierung
`websockets-sansio`. Das `auto` von uvicorn wählt die alte, die den Handshake gegen
websockets >=14 mit einem HTTP 500 scheitern lässt — und der Dashboard-Chat ist ein
WebSocket.


### Datenbank-Befehle { #database-commands }

```bash
uv run agenticos db init                  # Run all migrations
uv run agenticos db migrate -m "message"  # Create new migration
uv run agenticos db upgrade               # Apply pending migrations
uv run agenticos db upgrade --revision e3f  # Upgrade to specific revision
uv run agenticos db downgrade             # Rollback last migration
uv run agenticos db downgrade --revision base  # Rollback to start
uv run agenticos db current               # Show current revision
uv run agenticos db history               # Show migration history
```

### Nutzer-Befehle { #user-commands }

```bash
# Create user (interactive prompts for email/password)
uv run agenticos user create

# Create user non-interactively
uv run agenticos user create --email user@example.com --password secret

# Also grant app-admin, which administers the whole deployment
uv run agenticos user create --email admin@example.com --password secret --superuser

# The same thing, as a shortcut
uv run agenticos user create-admin --email admin@example.com --password secret

# List all users
uv run agenticos user list
```

**Es gibt kein `--role` und kein `set-role`.** Die Autorität eines Nutzers innerhalb
einer Organisation ist eine Mitgliedschaftszeile plus der
[Berechtigungskatalog](reference/permissions.md), vergeben unter Users & Roles in der
UI — die Spalte `users.role` wurde entfernt, bevor die Migrationskette gestaucht
wurde. Das einzige Privileg, das diese Gruppe vergeben kann, ist das globale, und
`--superuser` ist es. Um es später zu vergeben oder zu entziehen:

```bash
uv run agenticos cmd create-app-admin user@example.com
uv run agenticos cmd create-app-admin user@example.com --revoke
```

### Eigene Befehle { #custom-commands }

Eigene Befehle werden automatisch aus `app/commands/` erkannt. Führen Sie sie so aus:

```bash
uv run agenticos cmd <command-name> [options]
```

`uv run agenticos cmd --help` listet alles auf, was das laufende Deployment hat.

### Einrichtung und Diagnose { #setup-and-diagnostics }

```bash
# An organization, an owner, a model profile and a published agent. Idempotent.
uv run agenticos cmd bootstrap \
    --email owner@example.com --password secret \
    --org "Acme" --provider anthropic --api-key sk-ant-...

# Without a key the agent is created but cannot run
uv run agenticos cmd bootstrap --org "Acme"

# Can this deployment actually run an agent? Database, vault, a usable model,
# and every registered sandbox connection - probed one by one, credential
# included, because `/healthz` is unauthenticated and answers for a service
# holding the wrong token.
uv run agenticos cmd doctor

# Find published agents that lend a skill their publisher could not reach. The
# publish-time check on skill_ids only guards new publishes; this is the offline
# half, naming versions frozen before it that still hand a private skill to a run.
# It sweeps every version a run can load, not only the current one: each named
# environment's pinned version, each version a non-terminal run (running, or parked
# awaiting approval) still reloads, and each delegate a spec pins - the last only as
# deep as max_depth lets a run reach, so a grandchild past the ceiling is not flagged.
# Report-only - a spec is exported into a client's own git, so unbinding is a person's
# call. Exits non-zero when it finds one, so a cron can gate on it.
uv run agenticos cmd audit-skill-bindings

# Re-wrap every stored secret under the current master key - the staged rotation
# docs/secrets.md describes. Configure the old and new key side by side in
# VAULT_MASTER_KEYS first; --dry-run fully unseals every stored envelope without
# writing, so failures surface before anything moves. Exits non-zero when any row
# could not move, so a script cannot drop the old key on a partial rotation.
uv run agenticos cmd vault-rotate --dry-run
uv run agenticos cmd vault-rotate

# Install the bundled skills (refund-policy, code-review, incident-report)
uv run agenticos cmd seed-skills
uv run agenticos cmd seed-skills --org <org-id> --dry-run

# Sample data for development
uv run agenticos cmd seed --count 10 --clear
```

### Ein Team einladen und die Links herausbekommen { #inviting-a-team-and-getting-the-links-out }

```bash
# Invitations for several addresses at once, printed as `address  link`.
uv run agenticos cmd invite-members <org-id> ada@example.com grace@example.com

# One role for the batch; `member` unless you say otherwise.
uv run agenticos cmd invite-members <org-id> ada@example.com --role admin

# Whose authority they are created under. Defaults to the organization's first
# owner, and a role gate needs a role to weigh the offered one against.
uv run agenticos cmd invite-members <org-id> ada@example.com --as owner@example.com
```

Das gibt es wegen der beiden Hälften einer Einladung. **Auf einem Deployment ohne
`SMTP_*` wird nichts per E-Mail versandt**, und der Annahme-Token wird einmal
zurückgegeben und nirgends gespeichert, wo ein zweiter Lesevorgang ihn erreicht — der
Link muss also ausgegeben werden, um überhaupt weitergegeben werden zu können. Der
Befehl sagt, welches von beidem geschehen ist, und eine abgelehnte Adresse (bereits
Mitglied, bereits eingeladen) wird gemeldet und übersprungen, statt den Rest zu
kosten.

Er geht durch denselben Service wie die UI, die Rollenobergrenze, die Sitzplatzgrenze
und die Duplikatsprüfungen gelten also genau so wie für jemanden, der die
Schaltfläche drückt — einschließlich dessen, dass niemand eine Rolle vergibt, die
seine eigene nicht strikt überragt.

`make platform-bootstrap BOOTSTRAP_API_KEY=sk-...` umhüllt `bootstrap` mit den
Migrationen, die es braucht. Führen Sie zuerst `doctor` aus, wenn etwas lokal
funktioniert und auf einer frischen Umgebung nicht — das ist schneller als Logs zu
lesen.

### Ein Deployment zum Laufen bringen { #getting-a-deployment-up }

```bash
# Docker, one downloaded compose file, four questions, and a running agent.
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
# Only report what this machine is missing.
./scripts/quickstart.sh --check
# Print every command it would run, run none of them.
./scripts/quickstart.sh --dry-run
# Unattended.
./scripts/quickstart.sh --yes --provider anthropic --api-key sk-ant-... --org Acme
```

Es ist eine Hülle um `docker compose up` auf den veröffentlichten Images (`make dev`
in einem Klon), `agenticos cmd bootstrap` und `agenticos cmd mcp-registry-sync` —
nichts, was es tut, ist von Hand nicht verfügbar, und Docker ist das Einzige, was es
braucht.

### Der MCP-Registry-Spiegel { #the-mcp-registry-mirror }

```bash
# Fill or refresh `mcp_registry_servers` from the bundled snapshot.
uv run agenticos cmd mcp-registry-sync

# Or from the live registry, which is how the mirror moves between deploys.
uv run agenticos cmd mcp-registry-sync --fetch

# Keep rows the registry no longer lists, rather than pruning them.
uv run agenticos cmd mcp-registry-sync --no-prune
```

**`make platform-bootstrap` lädt ihn bereits**, aus dem mitgelieferten Snapshot, eine
erstmalige Einrichtung braucht davon also nichts. Es wird übersprungen, wenn die
Tabelle bereits Zeilen hält: ein erneuter Lauf von bootstrap darf keine Sekunden
damit verbringen, fünftausend unveränderte Zeilen neu zu schreiben, und den Spiegel
aufzufrischen ist die Aufgabe dieses Befehls und nicht die von bootstrap.

Führen Sie ihn von Hand auf einem Deployment aus, das älter als die Tabelle ist, oder
um einen neueren Snapshot aufzunehmen. Der Sync ist idempotent: ein zweiter Lauf
stempelt `synced_at` und ändert sonst nichts, es sei denn, die Registry hat es getan.

Das Pruning ist das, was einen ausgelisteten Server entfernt. Ohne es wächst der
Spiegel nur und ein toter Endpunkt bleibt für immer anbietbar, es ist also
standardmäßig an und hängt an `synced_at` statt an einem Diff über fünftausend Ids.

### Channel-Bots { #channel-bots }

Was jede Plattform unterstützt, steht unter [Channels](channels.md).

Jeder Befehl hier handelt für **eine Organisation**, denn ein Channel-Bot gehört zu
einer. `--org <id>` benennt sie, und ein Deployment mit genau einer Organisation
braucht kein Flag. Ein Deployment mit mehreren lehnt ab, statt zu wählen, und listet
sie mit ihren Ids auf — zu raten hieße, auf die Bots von jemand anderem zu wirken.

```bash
# Register a bot
uv run agenticos cmd channel-add-bot \
    --platform telegram --name "Support" --token <token> --mode jwt_linked

# Mattermost is self-hosted, so its bot carries its own server's address.
# --webhook-secret is the token Mattermost shows when the outgoing webhook is
# created; omit it to use the event stream and expose nothing.
uv run agenticos cmd channel-add-bot \
    --platform mattermost --name "Support" --token <token> \
    --api-base-url https://mattermost.acme.internal \
    --webhook-secret <token-from-mattermost>

uv run agenticos cmd channel-list-bots
uv run agenticos cmd channel-list-bots --platform telegram

# Send a test message through it - the cheapest proof the token and the
# address are right. --chat-id is a Telegram chat id or a Mattermost channel id.
uv run agenticos cmd channel-test-message --bot-id <uuid> --chat-id <chat> --text "ping"

# Webhook delivery, or delete the webhook to fall back to polling. Telegram is
# the only platform with an API for this; for Slack and Mattermost the command
# prints the URL to paste into their own settings.
uv run agenticos cmd channel-webhook-register --bot-id <uuid>
uv run agenticos cmd channel-webhook-delete --bot-id <uuid>
```

Einen Bot aus dem CLI zu registrieren ist der einzige Weg auf einem Deployment, auf
das kein Browser zeigt, was ein Mattermost-Server hinter einem VPN üblicherweise ist.

Die Zugriffsmodi sind `open`, `whitelist`, `jwt_linked` und `group_only`;
`jwt_linked` antwortet nur Chat-Konten, die mit einem Mitglied verknüpft sind, in
einem Kanal ebenso wie in einer Direktnachricht. Eine Erwähnung läuft als der
*Absender*, nie als der Bot, und eine nicht verknüpfte Identität wird abgelehnt,
statt ohne Rolle zu laufen — siehe
[Channels](channels.md#what-every-channel-shares).

### RAG-Befehle { #rag-commands }

Alle RAG-Befehle sind eigene Befehle, aufgerufen über `cmd`:

#### Dokumente ingestieren { #document-ingestion }

Die voreingestellte Collection ist `default`. Ein Name, dessen Vektortabelle die
Modelle bereits deklarieren — `documents`, was mit Präfix die Tracking-Tabelle der
Ingestion ist — wird mit einem 400 abgelehnt, statt darauf umgeleitet zu werden;
siehe [Dateiverarbeitung](file-processing.md#vector-storage).

```bash
# Ingest a single file into the default collection
uv run agenticos cmd rag-ingest ./docs/guide.pdf

# Ingest a directory
uv run agenticos cmd rag-ingest ./docs/

# Ingest recursively into a specific collection
uv run agenticos cmd rag-ingest ./docs/ --collection knowledge --recursive

# Ingest with sync mode
uv run agenticos cmd rag-ingest ./docs/ --sync-mode new_only
uv run agenticos cmd rag-ingest ./docs/ --sync-mode update_only

# Skip replacing existing documents
uv run agenticos cmd rag-ingest ./docs/ --no-replace
```

#### Suche { #search }

```bash
# Search the default collection
uv run agenticos cmd rag-search "what is fastapi"

# Search a specific collection
uv run agenticos cmd rag-search "deployment guide" --collection docs

# Get more results
uv run agenticos cmd rag-search "deployment" --top-k 10
```

#### Collections verwalten { #collection-management }

```bash
# List all collections with stats
uv run agenticos cmd rag-collections

# Show overall RAG system statistics
uv run agenticos cmd rag-stats

# Drop a collection (with confirmation)
uv run agenticos cmd rag-drop my_collection

# Drop without confirmation
uv run agenticos cmd rag-drop my_collection --yes
```

#### Google-Drive-Sync { #google-drive-sync }

```bash
# Sync from Google Drive root
uv run agenticos cmd rag-sync-gdrive --collection docs

# Sync from a specific folder
uv run agenticos cmd rag-sync-gdrive --collection docs --folder-id abc123
```

#### S3/MinIO-Sync { #s3minio-sync }

```bash
# Sync from S3 bucket root
uv run agenticos cmd rag-sync-s3 --collection docs

# Sync from a specific prefix (folder)
uv run agenticos cmd rag-sync-s3 --collection docs --prefix documents/

# Sync from a specific bucket
uv run agenticos cmd rag-sync-s3 --collection docs --bucket my-bucket
```


#### Sync-Quellen verwalten { #sync-source-management }

```bash
# List configured sync sources
uv run agenticos cmd rag-sources

# Add a new sync source. `--org` is required and the collection has to be one
# that organization already holds: a sync *writes into* the collection it names,
# so a source pointing at a name nobody owns fails later in a worker, and one
# pointing at another tenant's is an injection rather than a read.
uv run agenticos cmd rag-source-add \
    --name "My Drive" \
    --type gdrive \
    --org 0c8f2b1e-... \
    --collection docs \
    --config '{"folder_id": "abc123"}' \
    --sync-mode new_only \
    --schedule 60

# Remove a sync source
uv run agenticos cmd rag-source-remove <source-id>
uv run agenticos cmd rag-source-remove <source-id> --yes  # Skip confirmation

# Trigger sync for a specific source
uv run agenticos cmd rag-source-sync <source-id>

# Trigger sync for all active sources
uv run agenticos cmd rag-source-sync --all
```

`rag-source-sync` **wartet auf die Syncs, die es startet**, bis zu einer Stunde, und
sagt das, während es das tut. Der Sync selbst läuft in einem Hintergrund-Task, und
der Prozess des Befehls endet, wenn seine Koroutine zurückkehrt — ein Befehl, der nur
ausgelöst und sich beendet hat, brach also die Arbeit ab, deren Start er gerade
gemeldet hatte. Über die API gehört dieser Task zu einem langlebigen Worker, und
nichts muss auf ihn warten.

## Eigene Befehle hinzufügen { #adding-custom-commands }

Befehle werden automatisch aus `app/commands/` erkannt. Legen Sie eine neue Datei an:

```python
# app/commands/my_command.py
import click
from app.commands import command, success, error

@command("my-command", help="Description of what this does")
@click.option("--name", "-n", required=True, help="Name parameter")
def my_command(name: str):
    """Your command logic here."""
    success(f"Done: {name}")
```

Führen Sie ihn aus:

```bash
uv run agenticos cmd my-command --name test
```

Weitere Einzelheiten finden Sie in `docs/adding_features.md`.
