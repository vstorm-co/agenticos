---
source_sha: 4b2b3dcb65c8
---

# Konfiguration { #configuration }

Die gesamte Konfiguration läuft über Umgebungsvariablen, die mit
[pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) aus `backend/.env` geladen werden.

Die Settings sind in `app/core/config.py` definiert und werden über das globale
Objekt `settings` gelesen:

```python
from app.core.config import settings

print(settings.EMBEDDING_MODEL)
print(settings.DEBUG)
```

## Erste Schritte { #getting-started }

`make install` legt `backend/.env` aus `backend/.env.example` an, wenn es keine
gibt, und fasst die Datei danach nie wieder an — auf einem frischen Checkout ist
also nichts zu kopieren und auf einem bestehenden nichts zu verlieren.

Bevor irgendetwas ein Netz erreicht, in dem noch jemand anderes ist, setzen Sie
die Werte, die das Beispiel als Platzhalter ausliefert:

```bash
openssl rand -hex 32   # SECRET_KEY — signs every access token
openssl rand -hex 32   # VAULT_MASTER_KEY — unwraps every credential stored at rest
```

!!! danger "`SECRET_KEY` wird als veröffentlichte Zeichenkette ausgeliefert"

    Ein leerer `VAULT_MASTER_KEY` fällt darauf zurück, damit ein frischer
    Checkout überhaupt läuft. Auf einem Laptop ist beides in Ordnung, überall
    sonst ist es die gesamte Sicherheit eines Deployments. `VAULT_MASTER_KEY`
    ausdrücklich zu setzen ist außerdem das, was gespeicherte Secrets eine
    Rotation von `SECRET_KEY` überleben lässt.

Die Konfiguration lehnt einen nicht gesetzten `VAULT_MASTER_KEY` außerhalb von `local`/`development` ab.

## Projekteinstellungen { #project-settings }

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `PROJECT_NAME` | `agenticos` | Anzeigename des Projekts |
| `API_V1_STR` | `/api/v1` | Präfix der API-Version |
| `DEBUG` | `false` | Debug-Modus einschalten (ausführliche Fehler, Auto-Reload) |
| `ENVIRONMENT` | `local` | Eines von: `development`, `local`, `staging`, `production` |
| `TIMEZONE` | `UTC` | IANA-Zeitzone (z. B. `UTC`, `Europe/Warsaw`, `America/New_York`) |
| `MODELS_CACHE_DIR` | `./models_cache` | Verzeichnis für zwischengespeicherte ML-Modelle |
| `MEDIA_DIR` | `./media` | Verzeichnis für hochgeladene Dateien |
| `MAX_UPLOAD_SIZE_MB` | `50` | Obergrenze für Dokumente der Knowledge Base und die Zahl, aus der sich die Obergrenze für die gesamte Anfrage weiter unten ableitet. Ein Dokument dieser Größe wird in Chunks zerlegt und embedded, nicht am Stück gehalten |
| `CHAT_MAX_UPLOAD_SIZE_MB` | `10` | Was im Chat angehängt werden darf. Eine eigene Einstellung statt der obigen, weil ein Anhang an einen Agent ohne Workspace vollständig in den Prompt eingesetzt wird — die beiden Oberflächen scheitern bei derselben Größe also unterschiedlich. War fest verdrahtete 10 MiB, die keine Betreiberin anheben konnte ([#498](https://github.com/vstorm-co/agenticos/issues/498)); der Frontend-Container liest dasselbe `CHAT_MAX_UPLOAD_SIZE_MB` zur Laufzeit, geben Sie also beiden Containern einen Wert, sonst lehnt der Composer eine Datei ab, die der Server annehmen würde |
| `EMBED_MAX_UPLOAD_SIZE_MB` | `5` | Was eine **fremde Person** auf eine Hosted Page hochladen darf. Eine Obergrenze über `CHAT_MAX_UPLOAD_SIZE_MB`, nie ein Weg daran vorbei |
| `MEM0_ALLOWED_HOSTS` | `[]` (empty) | Hostnamen, auf die ein selbst gehosteter mem0-Memory-Dienst zeigen darf. Eine `base_url` kommt aus dem Spec eines Agents, ohne Allowlist könnte also ein Builder, der einen geteilten mem0-Key binden (aber nicht lesen) darf, ihn auf den eigenen Server richten und den Key aus dem Request-Header abgreifen. Leer lehnt selbst gehostetes mem0 ab und lässt nur die verwaltete Cloud zu; fügen Sie einen vertrauenswürdigen Hostnamen hinzu, um ein selbst gehostetes Deployment zu erlauben. Siehe [Secrets](secrets.md) |
| `FILE_IO_MAX_WORKERS` | `8` | Größe des eigenen Thread-Pools, der blockierende Dateiarbeit ausführt — das Parsen eines Uploads und das Lesen oder Schreiben seiner Bytes. Bewusst außerhalb des gemeinsamen Default-Executors von `asyncio`, der auch `bcrypt` und DNS für gepinnte Hosts ausführt, damit eine Welle von Uploads Anmeldung und ausgehende Anfragen nicht dahinter warten lässt ([#1108](https://github.com/vstorm-co/agenticos/issues/1108)). Heben Sie ihn auf einem Host an, der viele Uploads gleichzeitig parst. Muss eine positive ganze Zahl sein — eine `0` oder ein negativer Wert wird beim Start abgelehnt |
| `DEFAULT_ORG_MONTHLY_BUDGET_USD` | `100` | Die monatliche Ausgabenobergrenze, mit der eine **neue** Organisation startet, in USD, damit sie nicht einen entlaufenen Agent von einer überraschenden Rechnung entfernt ist. Gilt nur bei der Erstellung; bestehende Organisationen bleiben unberührt, und jede Organisation lässt sich danach wieder auf kein Cap zurücksetzen. Muss positiv sein; lassen Sie den Wert **leer**, damit Organisationen ohne Cap starten (die ältere Opt-in-Haltung) |

### Die Größe einer Anfrage, im Unterschied zur Größe einer Datei { #the-size-of-a-request-as-opposed-to-the-size-of-a-file }

Jede Grenze oben misst Bytes, die bereits angekommen sind. FastAPI parst einen
Multipart-Body, um den Parameter `UploadFile` aufzulösen, *bevor* der Handler
läuft — wenn eines dieser Caps mit `len(data)` verglichen wird, ist der Body also
längst in eine temporäre Datei geschrieben und in den Speicher gelesen worden.
Hinter einer Session ist das kaum ein Risiko; auf
`POST /api/v1/embed/{key}/files`, das eine fremde Person mit einem Link erreichen
kann, schon.

Eine Anfrage, die eine `Content-Length` größer als `MAX_UPLOAD_SIZE_MB` plus
5 MiB Zuschlag für den Multipart-Umschlag angibt, wird deshalb mit **413**
beantwortet, bevor ihr Body gelesen wird. Es gibt keine Einstellung dafür: Sie
folgt `MAX_UPLOAD_SIZE_MB`, weil eine zweite Zahl, die mit der ersten Schritt
halten muss, eine Zahl ist, die irgendwann darunter liegt.

**Es ist die billige Hälfte der Antwort, nicht die ganze.** `Content-Length`
setzt die aufrufende Seite, und eine Chunked-Anfrage gibt gar keine an — die
werden durchgelassen und durch die Caps je Route begrenzt, die echte Bytes
messen. Ein Deployment, das die Garantie statt der Höflichkeit will, setzt
`client_max_body_size` (nginx) oder das Äquivalent an dem, was seine Verbindungen
terminiert; die Compose-Dateien starten uvicorn ohne eine eigene solche Grenze.

## Authentifizierung { #authentication }

### JWT { #jwt }

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `SECRET_KEY` | (insecure default) | Signierschlüssel für JWT. **Muss** in der Produktion geändert werden. Erzeugen mit: `openssl rand -hex 32` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Lebensdauer des Access Tokens |
| `REFRESH_TOKEN_EXPIRE_MINUTES` | `10080` | Lebensdauer des Refresh Tokens (7 Tage) |
| `ALGORITHM` | `HS256` | Signaturalgorithmus für JWT |

Prüfung für die Produktion: `SECRET_KEY` muss mindestens 32 Zeichen lang sein und
darf bei `ENVIRONMENT=production` nicht der Standardwert sein.

### Secret Vault { #secret-vault }

Jede Zugangsinformation, die die Plattform dauerhaft speichert — Provider-Keys,
Bot-Tokens für Kanäle, MCP-Credentials und Organisations-Secrets —, wird von
`app/core/vault.py` versiegelt, dessen Umschlag aus dem Master Key **und dem
Eigentümer** abgeleitet ist (einer Organisation oder dem Mitglied, dem eine
persönliche Verbindung gehört). Ein Ciphertext ist deshalb außerhalb des Tenants,
für den er versiegelt wurde, nutzlos.

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `VAULT_MASTER_KEY` | (empty, falls back to `SECRET_KEY`) | Master Key für den Secret Vault — Kurzform für Version 1 von `VAULT_MASTER_KEYS`. Außerhalb von `local`/`development` erforderlich (sofern die Map unten nicht gesetzt ist), damit ein Staging-Vault nicht unter dem veröffentlichten Standardwert von `SECRET_KEY` versiegelt starten kann. Erzeugen mit: `openssl rand -hex 32` |
| `VAULT_MASTER_KEYS` | `{}` | Jeder noch genutzte Master Key, nach Version, als JSON — `{"1": "<old>", "2": "<new>"}`. Die höchste Version versiegelt neue Secrets; ältere halten bestehende Zeilen lesbar, bis `agenticos cmd vault-rotate` sie neu einpackt. Ist sie gesetzt, ist sie die ganze Wahrheit: `VAULT_MASTER_KEY` muss dann leer sein. Siehe [Secrets](secrets.md#operations) |

### API Key { #api-key }

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `API_KEY` | `change-me-in-production` | Gemeinsamer API Key für den programmatischen Zugriff |
| `API_KEY_HEADER` | `X-API-Key` | Name des HTTP-Headers für den API Key |

Prüfung für die Produktion: `API_KEY` darf bei `ENVIRONMENT=production` nicht der
Standardwert sein.

### OAuth2 (Google) { #oauth2-google }

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `GOOGLE_CLIENT_ID` | (empty) | Google-OAuth2-Client-ID — Anmeldung **und** die Einwilligung für den Gmail-Trigger |
| `GOOGLE_CLIENT_SECRET` | (empty) | Google-OAuth2-Client-Secret |
| `GOOGLE_REDIRECT_URI` | `http://localhost:8000/api/v1/oauth/google/callback` | Callback-URL für OAuth2 |
| `FRONTEND_URL` | `http://localhost:3000` | Frontend-URL für die OAuth2-Weiterleitungen |

So kommen Sie an das Paar: [Google Cloud console](https://console.cloud.google.com/) →
APIs & Services → Credentials → Create OAuth client ID → **Web application**.

Die autorisierte Redirect-URI ist der Callback des **Backends**, nicht der des
Frontends — standardmäßig `http://localhost:8000/api/v1/oauth/google/callback`
und in einem Deployment das, was `GOOGLE_REDIRECT_URI` sagt. Google tauscht den
Code mit der API, die den Browser anschließend an `FRONTEND_URL` weiterschickt.
Stattdessen die Frontend-URL einzutragen ist der Fehler, den es zu benennen
lohnt: Der Consent-Bildschirm funktioniert, und der Callback antwortet mit 404.

Der Browser wird mit einem einmal einlösbaren Code von einer Minute Gültigkeit
weitergeschickt, nie mit den Session-Tokens selbst: Ein Token in einer
Redirect-URL landet in der Adressleiste, im Access-Log des Frontend-Servers und
im `Referer` der nächsten Anfrage derselben Origin, und das Refresh Token gilt
eine Woche. Das Frontend tauscht den Code Server zu Server unter
`POST /api/v1/oauth/exchange` gegen das Token-Paar, und diese Route löst ihn
genau einmal ein.


## Datenbank (PostgreSQL) { #database-postgresql }

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `POSTGRES_HOST` | `localhost` | PostgreSQL-Host |
| `POSTGRES_PORT` | `5432` | PostgreSQL-Port |
| `POSTGRES_USER` | `postgres` | PostgreSQL-Benutzer |
| `POSTGRES_PASSWORD` | (empty) | PostgreSQL-Passwort |
| `POSTGRES_DB` | `agenticos` | Name der Datenbank |
| `POSTGRES_SSLMODE` | (empty) | Die Verbindung verschlüsseln: `require`, `verify-ca` oder `verify-full`. Leer heißt Klartext. Siehe [Verschlüsselte Verbindungen](#encrypted-connections-tls) |
| `DB_POOL_SIZE` | `5` | Größe des Connection Pools |
| `DB_MAX_OVERFLOW` | `10` | Maximale Overflow-Verbindungen |
| `DB_POOL_TIMEOUT` | `30` | Pool-Timeout in Sekunden |

Berechnete Eigenschaften:
- `DATABASE_URL` -- asynchroner Connection String (`postgresql+asyncpg://...`)
- `DATABASE_URL_SYNC` -- synchroner Connection String für Alembic

## Redis { #redis }

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `REDIS_HOST` | `localhost` | Redis-Host |
| `REDIS_PORT` | `6379` | Redis-Port |
| `REDIS_PASSWORD` | (none) | Redis-Passwort (optional) |
| `REDIS_DB` | `0` | Nummer der Redis-Datenbank |
| `REDIS_SSL` | `false` | Die Verbindung verschlüsseln (`rediss://`). Siehe [Verschlüsselte Verbindungen](#encrypted-connections-tls) |

## Verschlüsselte Verbindungen (TLS) { #encrypted-connections-tls }

Beide Stores verbinden sich standardmäßig im Klartext. Auf einem einzelnen Host
mit Postgres und Redis im selben Docker-Netz ist das in Ordnung, und genau so
laufen die mitgelieferten Compose-Dateien. Bei einem verwalteten Postgres oder
einem Redis auf einem anderen Knoten ist die verschlüsselte Verbindung die
Maßnahme zur Übertragungssicherheit, nach der eine prüfende Person zuerst fragt
(HIPAA §164.312(e), SOC 2 CC6.7).

`POSTGRES_SSLMODE` zu setzen baut die URL, die der jeweilige Treiber versteht —
`?ssl=<mode>` für das asyncpg der Anwendung, `?sslmode=<mode>` für das psycopg2
von Alembic —, und `REDIS_SSL` stellt das Redis-Schema auf `rediss://` um.
`require` verschlüsselt die Verbindung; `verify-ca` und `verify-full` prüfen
zusätzlich das Zertifikat des Servers.

`REDIS_SSL` verlangt außerdem eine gültige Zertifikatskette und einen passenden
Hostnamen an der URL selbst, statt beides den Voreinstellungen von redis-py zu
überlassen.

!!! warning "Eine private CA ist eine Datei, die die Treiber lesen, nicht der Trust Store des Betriebssystems"

    Keiner der beiden Treiber fragt den Trust Store des Containers, und das Image
    läuft als Benutzer ohne Root-Rechte, ohne einen Entrypoint, der ihn neu bauen
    könnte. asyncpg und libpq lesen beide die CA-Datei, die `PGSSLROOTCERT`
    nennt; redis-py vertraut dem Bundle, auf das OpenSSL zeigt, und das
    überschreibt `SSL_CERT_FILE`. Hängen Sie die CA einmal ein und setzen Sie
    beide Variablen darauf — `verify-ca` und `verify-full` scheitern ohne die
    erste, weil asyncpg dann nach `~/.postgresql/root.crt` sucht und nichts findet.

!!! note "Jeder Dienst, der eine Verbindung zu einem Store öffnet, braucht die Änderung"

    `app`, `migrate` und `prefect-runner` verbinden sich jeweils mit Postgres und
    Redis, und die mitgelieferten Compose-Dateien pinnen `POSTGRES_HOST=db` und
    `REDIS_HOST=redis` in der `environment` jedes einzelnen, was eine Env-Datei
    übersteuert. Ein verwalteter Store ist deshalb eine Override-Datei, die alle
    drei erreicht, und keine Zeile in `.env`.

```yaml
# docker-compose.managed.yml - a managed Postgres and Redis, verified against a
# private CA. Run with `docker compose -f docker-compose.yml -f docker-compose.managed.yml up -d`.
x-managed: &managed
  environment:
    POSTGRES_HOST: db.internal.example.com
    POSTGRES_SSLMODE: verify-full
    PGSSLROOTCERT: /run/tls/managed-ca.crt
    REDIS_HOST: redis.internal.example.com
    REDIS_SSL: "true"
    SSL_CERT_FILE: /run/tls/managed-ca.crt
  volumes:
    - ./ca/managed-ca.crt:/run/tls/managed-ca.crt:ro

services:
  app: *managed
  migrate: *managed
  prefect-runner: *managed
```

Die mitgelieferten Dienste `db` und `redis` starten weiter, ungenutzt;
`agenticos cmd doctor` zeigt, welchen Store jede Verbindung tatsächlich erreicht
hat und ob sie verschlüsselt war (`postgres: tls=on/off`, `redis: tls=on/off`,
aus `pg_stat_ssl` und dem URL-Schema).

## E-Mail (SMTP) { #email-smtp }

Das Deployment verschickt Post über einen SMTP-Server, und eines ohne
konfigurierten Server scheitert nicht — es läuft, und jeder Ablauf, der auf Post
angewiesen ist, hört still auf, ohne dass einer davon es ankündigt:

- **Anmeldung ohne Passwort und Passwort-Zurücksetzungen** — die Magic-Link- und
  Reset-Mails sind die Self-Service-Wege in ein Konto;
- **Einladungen** — eine eingeladene Adresse bekommt nie eine Mail (die Konsole
  sagt das inzwischen, statt zu behaupten, sie habe eine verschickt, #1484);
- **Benachrichtigungen** — eine Budget-Überschreitung, eine Freigabeanfrage, ein
  Nutzungsbericht, der Hinweis, der verschickt wird, wenn eine Administratorin im
  Namen eines anderen Kontos handelt.

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `SMTP_HOST` | `localhost` | Host des SMTP-Servers |
| `SMTP_PORT` | `587` | Port des SMTP-Servers. `587` und `25` handeln STARTTLS aus; `465` öffnet TLS von Anfang an |
| `SMTP_USER` | (empty) | Benutzername, mit dem sich das Relay authentifiziert, zusammen mit `SMTP_PASSWORD`. Für ein Relay ohne Authentifizierung leer lassen |
| `SMTP_PASSWORD` | (empty) | Passwort zu diesem Benutzernamen |
| `SMTP_TLS` | `true` | Ob die Verbindung verschlüsselt wird. Der Port wählt das Schema — STARTTLS auf `587`, implizites TLS auf `465` —, sofern `SMTP_TLS_MODE` nichts anderes sagt. Setzen Sie `false` nur für ein unverschlüsseltes Relay, etwa einen lokalen Server auf `25` |
| `SMTP_TLS_MODE` | `auto` | Wie die verschlüsselte Verbindung geöffnet wird. `auto` lässt den Port entscheiden; `implicit` öffnet TLS ab dem ersten Byte und `starttls` handelt das Upgrade aus, unabhängig vom Port. Wird bei `SMTP_TLS=false` ignoriert |
| `EMAIL_FROM` | `noreply@agenticos.com` | Die `From`-Adresse jeder Nachricht |
| `EMAIL_FROM_NAME` | `agenticos` | Der Anzeigename, der neben dieser Adresse steht |

!!! note "Wie die Verbindung verschlüsselt wird"

    `SMTP_TLS` ist der Ein-/Ausschalter; das Schema wählt der Port. Die
    ausgelieferte Voreinstellung — `587` mit `SMTP_TLS=true` — handelt STARTTLS
    aus, und das erwartet ein standardkonformer Submission-Server. Nutzen Sie
    `465` für einen Server, der stattdessen implizites TLS will, und
    `SMTP_TLS=false` auf `25` für ein Relay im Klartext.

    Ein Server, der implizites TLS auf einem anderen Port als `465` spricht — etwa
    `8465` —, braucht `SMTP_TLS_MODE=implicit`, denn `auto` böte ihm einen
    Handshake im Klartext an und jeder Versand würde scheitern. `starttls` ist der
    spiegelbildliche Fall.

## Hintergrundarbeit (Prefect) { #background-work-prefect }

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `PREFECT_API_URL` | `http://localhost:4200/api` | Der selbst gehostete Server oder die URL eines Workspace in Prefect Cloud |
| `PREFECT_API_KEY` | (none) | Nur für Prefect Cloud |
| `PREFECT_RUNNER_LIMIT` | `5` | Wie viele Flow Runs gleichzeitig laufen; der Rest wartet in der Warteschlange |
| `PREFECT_RUNNER_SERVER_HOST` | `127.0.0.1` in compose | Interface, auf dem der Runner seinen eigenen Health-Endpunkt bedient |
| `PREFECT_RUNNER_SERVER_PORT` | `8080` | Port dafür |

`PREFECT_RUNNER_LIMIT` ist eine Speicherobergrenze, kein Regler für den
Durchsatz. Jeder Run ist ein eigener Prozess, der die gesamte Anwendung
importiert — rund 120 MB —, und die Zahl, auf die es ankommt, ist nicht der
Normalbetrieb, sondern der Neustart: Der Runner kommt hoch, findet jeden Run, der
während seiner Abwesenheit geplant wurde, und startet so viele, wie das Limit
zulässt. Ohne Cap waren drei Tage Ausfall 71 Prozesse und 6 GiB. Heben Sie es an,
wenn die Ingestion auf einer Maschine mit freiem Speicher hinter Syncs wartet;
senken Sie es auf einem kleinen Host.

Die beiden `PREFECT_RUNNER_SERVER_*`-Variablen gehören Prefect, und die
Compose-Dateien pinnen sie, damit der Container des Runners einen Health-Status
hat, der etwas bedeutet. Der Runner startet den Runner-Webserver von Prefect,
dessen `GET /health` mit 503 antwortet, sobald er zwei Abfragen der Prefect-API
verpasst hat — ein Prozess, der lebt, aber keine Arbeit mehr annimmt, liest sich
damit als `unhealthy` statt als in Ordnung. Er ist an das Loopback gebunden, weil
derselbe Webserver auch `POST /shutdown` anbietet; die Probe läuft im Container,
und nichts außerhalb erreicht eines von beiden. Den Port zu verschieben heißt,
die Probe in den Compose-Dateien mitzuverschieben.

In `backend/Dockerfile` gibt es kein `HEALTHCHECK`. Das Image wird als zwei
verschiedene Prozesse gestartet — die API und dieser Runner —, und eine Probe für
den einen ist ein Dauerfehlalarm für den anderen, also trägt jede
Service-Definition ihre eigene.

### Ablauf einer Freigabe { #approval-expiry }

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `APPROVAL_EXPIRY_HOURS` | `72` | Wie lange ein geparkter Tool-Aufruf wartet, bevor der stündliche Durchlauf ihn per Timeout ablehnt |

Drei Tage, weil es ein Wochenende überspannen muss: Die Freigabe, die am
Freitagnachmittag eintrifft, ist die, über die niemand entscheidet, und sie am
Samstag ablaufen zu lassen hieße, sie dafür ablaufen zu lassen, dass sie zur
falschen Stunde gestellt wurde. Verkürzen Sie ihn, wo eine Warteschlange während
der Arbeitszeit beobachtet wird und eine veraltete Anfrage schlimmer ist als eine
langsame; verlängern Sie ihn, wo Freigaben ein wöchentliches Ritual sind. Einen
Aufruf ablaufen zu lassen **beendet auch seinen Run** — siehe
[Governance](governance.md#a-decision-nobody-makes) dazu, was das klärt und was
es bewusst unangetastet lässt.

### Abräumen hängen gebliebener Runs { #stale-run-reaping }

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `STALE_RUN_REAPED_AFTER_HOURS` | `6` | Wie lange ein Run auf `running` stehen darf, bevor der stündliche Durchlauf entscheidet, dass sein Prozess gestorben ist, und ihn als `failed` beendet. Null oder darunter schaltet den Durchlauf ab |

Die Zeile eines Runs wird committet, bevor sein Modell aufgerufen wird, ein
mitten im Run getöteter Worker lässt sie also auf `running` zurück, ohne dass
etwas sie noch abschließt. Die Obergrenze muss nicht genau sein — ein lebender
Run, den der Durchlauf trotzdem umstellt, wird durch seinen eigenen abschließenden
Schreibvorgang zurückgestellt —, setzen Sie sie also deutlich über Ihren längsten
legitimen Run und nicht knapper. Siehe
[Governance](governance.md#a-run-whose-process-died).

## KI-Modelle — in der App konfiguriert, nicht hier { #ai-models-configured-in-the-app-not-here }

Chat-Modelle sind keine Umgebungsvariablen. Jede Organisation legt ihre eigenen
Provider-Keys im Vault ab (Settings → Models), und der Spec jedes Agents nennt
das Model Profile, auf dem er läuft. `AI_MODEL`, `AI_TEMPERATURE`,
`AI_THINKING_ENABLED`, `AI_THINKING_EFFORT`, `AI_AVAILABLE_MODELS`,
`AI_FRAMEWORK` und `LLM_PROVIDER` wurden zusammen mit dem allgemeinen Assistenten
der Vorlage entfernt; sie zu setzen bewirkt heute nichts.

Die eine Modell-Zugangsinformation, die in der Umgebung bleibt, ist der Key für
die Embeddings — siehe RAG weiter unten.

## Observability (Logfire) { #observability-logfire }

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `LOGFIRE_TOKEN` | (none) | Token für Pydantic Logfire. Erhältlich unter https://logfire.pydantic.dev |
| `LOGFIRE_SERVICE_NAME` | `agenticos` | Name des Dienstes im Logfire-Dashboard |
| `LOGFIRE_ENVIRONMENT` | `development` | Kennzeichnung der Umgebung |
| `LOGFIRE_ORGANIZATION` | (none) | Slug der Organisation, um einen Link **in** einen gespeicherten Trace zu bauen. Das Token ist eine *schreibende* Zugangsinformation und trägt keinen der beiden Slugs |
| `LOGFIRE_PROJECT` | (none) | Slug des Projekts, neben dem der Organisation. Ist eines von beiden nicht gesetzt, wird die `logfire_trace_id` eines Runs weiterhin aufgezeichnet und kein Link angeboten |
| `LOGFIRE_BASE_URL` | `https://logfire-us.pydantic.dev` | Zu welchem Logfire-Deployment diese Slugs gehören. `logfire-eu` ist ein anderer Host, und ein für den falschen gebauter Link antwortet mit 404 |

## Websuche { #web-search }

| Variable | Standard | Beschreibung |
|----------|---------|-------------|

## RAG (Retrieval Augmented Generation) { #rag-retrieval-augmented-generation }

### Vektordatenbank { #vector-database }

pgvector nutzt die bestehende PostgreSQL-Verbindung. Es ist keine zusätzliche
Konfiguration nötig — aber das **Image** muss `pgvector/pgvector:pg16` sein,
worauf jede Compose-Datei hier pinnt.

!!! note "\"Vector store: unconfigured\" auf einem frischen Deployment ist kein Fehler"

    Die Extension wird angelegt, sobald zum ersten Mal in eine Collection
    geschrieben wird, vor dem ersten Dokument fehlt sie also tatsächlich, und die
    Admin-Seite System wie auch `agenticos cmd doctor` sagen das. Es löst sich mit
    der ersten Ingestion von selbst.

    Ein Fehler ist dort `unhealthy`, und es benennt, welcher von dreien: Das Image
    liefert kein pgvector mit; die verbindende Rolle darf sie nicht anlegen; oder
    das Datenverzeichnis trägt die Zeile der Extension, während dem Image, auf dem
    es jetzt läuft, die Bibliothek fehlt. Alle drei lassen einen Upload scheitern,
    nachdem die Bytes angenommen wurden, und alle drei lasen sich früher wie ein
    gesunder erster Tag
    ([#1504](https://github.com/vstorm-co/agenticos/issues/1504)).

### Embeddings { #embeddings }

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | (empty) | Die Zugangsinformation, auf die Embeddings zurückfallen, für Collections, die keinen eigenen Vault-Key gewählt haben — und die, auf die eine herabgestufte Wahl zurückfällt. Nicht „jede Collection embedded damit“: siehe [Dateiverarbeitung](file-processing.md#embeddings-the-model-whose-endpoint-answers-and-whose-key-pays) |
| `EMBEDDING_MODEL` | `text-embedding-3-large` | Womit eine **neue** Collection gebaut wird. Die Breite wird auf der Zeile festgehalten und ändert sich danach nie, eine Änderung hier entwertet bestehende Collections also nicht — sie embedden weiter mit dem Modell, mit dem sie erstellt wurden |

### Dokument-Parsing — je Collection konfiguriert, nicht hier { #document-parsing-configured-per-collection-not-here }

Parser, OCR, Chunk-Größe, Chunk-Überlappung, Chunking-Strategie und das Modell
für Bildbeschreibungen sind **keine** Umgebungsvariablen. Sie liegen auf jeder
Knowledge Base (`knowledge_bases.ingestion_config`), werden auf `/rag` bearbeitet,
und jedes einzelne davon lässt sich zusätzlich für einen einzelnen Upload
übersteuern.

Der Grund ist, dass ein installationsweiter Wert dasselbe Formular auf zwei
Deployments unterschiedliche Collections erzeugen ließ, ohne dass im Produkt
etwas zeigte, welche — und ein Archiv gescannter Verträge und ein Ordner mit
Markdown-Notizen wollen auf demselben Deployment unterschiedliche Antworten.
`PDF_PARSER`, `CHAT_PDF_PARSER`, `LLAMAPARSE_TIER`, `LITEPARSE_OCR_LANGUAGE`,
`LITEPARSE_TIMEOUT_SECONDS`, `RAG_ENABLE_OCR`, `RAG_CHUNK_SIZE`,
`RAG_CHUNK_OVERLAP` und `RAG_CHUNKING_STRATEGY` wurden entfernt; sie zu setzen
bewirkt heute nichts.

Was hier bleibt, ist das, was ein Tenant nicht wählen darf:

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `LLAMAPARSE_API_KEY` | (empty) | LlamaParse-Key, auf den Collections zurückfallen, die keinen eigenen Vault-Key gewählt haben |
| `LITEPARSE_OCR_SERVER_URL` | (empty) | HTTP-OCR-Server; eine Adresse im eigenen Netz des Deployments |

Chat-Anhänge werden mit PyMuPDF gelesen und sind nicht konfigurierbar: Ein Anhang
gehört zu keiner Collection, es gibt also keine gespeicherte Konfiguration zu
lesen.

### Google-Drive-Sync { #google-drive-sync }

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `GOOGLE_DRIVE_CREDENTIALS_FILE` | `credentials/google-drive-sa.json` | Pfad zu den Zugangsdaten des Google-Service-Accounts, nur für `rag-sync-gdrive` |

**Das ist die Zugangsinformation des CLI, kein Rückfall für eine Sync-Quelle.**
Eine `gdrive`-Sync-Quelle nennt ein `gcp_service_account`-Secret im Vault ihrer
Organisation und läuft damit oder gar nicht: Ein deploymentweiter Key, der für
einen fehlenden einsprang, führte dazu, dass die `folder_id` eines Tenants
auswählte, was unter dem Service-Account der Betreiberin gelistet war. Die
Zugangsinformation der Quelle ist keine Einstellung und kein Konfigurationsfeld —
siehe [Secrets und der Vault](secrets.md).

Die Datei ist der Key eines Service-Accounts: [Cloud console](https://console.cloud.google.com/iam-admin/serviceaccounts)
→ create a service account → Keys → Add key → JSON. Dann **teilen Sie den
Drive-Ordner mit der E-Mail-Adresse des Service-Accounts selbst** — er ist ein
Principal wie jeder andere, und ein Ordner, den niemand mit ihm geteilt hat,
listet sich als leer statt als abgelehnt.

### S3/MinIO-Sync { #s3minio-sync }

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `S3_RAG_ENDPOINT` | (none) | Endpunkt-URL für S3/MinIO. Eine Sync-Quelle darf sie übersteuern |
| `S3_RAG_ACCESS_KEY` | (empty) | Access Key, nur für den CLI-Befehl `rag-sync-s3` |
| `S3_RAG_SECRET_KEY` | (empty) | Secret Key, ebenso |
| `S3_RAG_BUCKET` | `agenticos-rag` | Name des Buckets |
| `S3_RAG_REGION` | `us-east-1` | AWS-Region. Die eigene Region einer Zugangsinformation gewinnt, wo sie eine hat |

**Das Schlüsselpaar hier gehört dem CLI, nicht einer Sync-Quelle.** Eine
`s3`-Sync-Quelle nennt ein `aws_credentials`-Secret im Vault ihrer Organisation,
genauso wie eine `gdrive`-Quelle einen Service-Account nennt. Endpunkt und Region
fallen weiterhin auf diese Einstellungen zurück, weil keines von beiden einen
Principal nennt — sie sagen, wo der Store liegt, nicht, wer fragt.

## Agent-Workspaces { #agent-workspaces }

Der `state`-Workspace braucht hier nichts. Er liegt in dieser Datenbank,
funktioniert auf jedem Deployment und ist das, was ein Agent standardmäßig
bekommt — die Einstellungen unten gelten also nur für einen containergestützten.

| Variable | Standard | Hinweise |
|---|---|---|
| `SANDBOX_STATE_MAX_BYTES` | 4 MiB | Pro **gespeichertem** Workspace. Darüber hinaus wird ein Schreibvorgang mit einer Nachricht abgelehnt, die das Modell liest |
| `SANDBOX_INLINE_IMAGE_MAX_BYTES` | 5 MiB | Darüber wird ein angehängtes Bild in den Workspace geschrieben und nicht zusätzlich inline gesendet |

**Der Prozentsatz im Chat sind zwei verschiedene Obergrenzen, und er sagt,
welche.** Ein gespeicherter Workspace füllt sich gegen
`SANDBOX_STATE_MAX_BYTES` oben — Bytes, und wenn sie ausgehen, *wird ein
Schreibvorgang abgelehnt*. Ein Container meldet residenten **Speicher** gegen die
Obergrenze, die sein Host für diese Runtime gesetzt hat, also `1g`, sofern die
Allowlist nichts anderes sagt, und wenn der ausgeht, ist das ein OOM-Kill und
keine Ablehnung. Deshalb sagt der Streifen `workspace 12% full` für das eine und
`sandbox memory 12% full` für das andere; das eine als das andere zu melden hieße,
eine Grenze zu nennen, die nicht gilt.

**Wo Sandboxes laufen, ist keine Einstellung.** Es ist eine Zeile je Organisation
— Sandboxes in der App, `sandbox_connections` in der Datenbank — mit dem
Service-Token im Vault. Zwei Gründe, und keiner davon lässt sich in einer
Umgebungsvariablen ausdrücken: Ein Deployment kann mehr als einen Host halten, und
eine Adresse je Deployment gab jeder Organisation dieselbe; und das Token
autorisiert das Öffnen einer Session, die Befehle auf dem Host ausführt, der den
Docker-Socket hält, es gehört also dorthin, wo jede andere dauerhaft gespeicherte
Zugangsinformation liegt.

Eine Betreiberin registriert eine Verbindung mit einem Namen, einer Adresse und
einem Key aus dem Vault. Ein Agent nennt eine davon per id, genau wie er ein Model
Profile nennt, oder nennt keine und nimmt die Standardverbindung der Organisation
— der Wechsel auf einen anderen Host ist damit eine Änderung statt einer erneuten
Veröffentlichung jedes Agents.

**Das Service-Token ist so viel wert wie der Docker-Socket.** Der Dienst hält
diesen Socket, der Socket ist eine unauthentifizierte API für root auf dem Host,
und das Token ist das, was darauf eine Session öffnet. Nie in einem Browser, nie
in einem Log, nie committet — deshalb zeigt der Bildschirm für Betreiberinnen nur,
dass eine Zugangsinformation hinterlegt ist, und deshalb wird `GET /policy` über
diese API geleitet, statt vom Browser abgerufen zu werden. Das eigene Dashboard
des Dienstes (`SANDBOXD_UI_ENABLED`) ist aus demselben Grund in jeder
ausgelieferten Compose-Datei aus: Es verlangt von einem Menschen, diesen Wert in
einen Browser einzufügen.

`SANDBOXD_TOKEN` in `backend/.env` ist das *eigene* Token des Dienstes — das, was
der Daemon in der Compose-Datei annimmt.

`make sandbox-token` erzeugt es, und das Verbindungsformular legt denselben Wert
für Sie im Vault ab. Die API liest diese Einstellung für genau einen Zweck: um
ihn dem Vault anzubieten. Jemanden zu bitten, ein Secret aus einer Datei zu
kopieren, die sein eigener Stack ohnehin schon liest, ist Reibung ohne
Gegenwert.

Es wird **nie** benutzt, um einen Host zu erreichen — eine Verbindung aufzulösen
entsiegelt den Vault-Eintrag, den diese Verbindung nennt, und das bleibt der
einzige Weg. Ein Deployment, das es nicht setzt, verliert also eine Schaltfläche
und sonst nichts und fügt das Token stattdessen von Hand ein.

Dasselbe Formular fragt, ob bereits ein Dienst antwortet, statt von einer
Betreiberin zu verlangen zu wissen, dass ein Sandbox-Dienst aus `make dev` unter
`http://sandboxd:8080` liegt. Diese Adresse ist keine Konfiguration, und das mit
Absicht — sie ist eine Zeile, weil ein Deployment mehrere Hosts halten kann —,
also prüft die API das unauthentifizierte `/healthz` unter der Adresse, die die
Compose-Datei dieses Projekts nutzt, und füllt vor, was geantwortet hat. Durch
das Fragen wird nichts entschieden: kein Dienst heißt ein leeres Feld, und eine
Verbindung, die bereits dorthin zeigt, wird benannt, damit niemand einen Host
zweimal registriert.

**Die Adresse wird von dieser API abgerufen, also wird sie als solche
validiert.** Eine Verbindung zu registrieren oder zu prüfen lässt den
API-Container ein authentifiziertes `GET` absetzen und reicht den JSON-Body
zurück, was ein Primitiv für Request Forgery ist, wenn die Adresse auf Treu und
Glauben genommen wird. `base_url` lehnt deshalb alles ab, was nicht `http(s)` mit
einem Host ist, und lehnt Link-Local-Adressen und die Hostnamen der
Instance-Metadata rundheraus ab — `169.254.169.254` und
`metadata.google.internal` sind nie ein Sandbox-Dienst.

Private Adressen bleiben erlaubt, und das müssen sie: `http://sandboxd:8080`
innerhalb von Compose und `http://localhost:8080` für eine Entwicklerin, die die
API auf ihrem eigenen Rechner laufen lässt, sind beide privat, eine Denylist für
private Bereiche würde also das Deployment ablehnen, das diese Seite beschreibt.
Der Validator verengt das Loch also, statt es zu schließen — ein Hostname, der auf
etwas Internes zeigt, tut das weiterhin. **Die Grenze, die tatsächlich hält, ist
`connections:manage` plus Egress-Policy auf dem API-Container**: Wer einen Host
registrieren darf, dem wird einer zugetraut, und ein Deployment in einem Netz mit
unauthentifizierten internen APIs sollte das im Netz sagen und nicht hier.

### Welche Umgebungen ein Agent anfordern darf { #which-environments-an-agent-may-ask-for }

Eine Runtime wird ausgeliefert — `workbench` (1,93 GB): Python 3.12, Node 24,
LibreOffice und die Bibliotheken, die ein Agent braucht, um die Dateien zu lesen,
zu schreiben, zu konvertieren und zu plotten, um die es in einer Unterhaltung
geht, liteparse mit OCR eingeschlossen. Sie ist in
`backend/app/core/catalog/sandbox_runtimes.json` definiert. Eine hinzuzufügen ist
eine Änderung dort plus `make sandbox-runtimes`, was `SANDBOXD_RUNTIMES` in alle
drei Compose-Dateien schreibt; diese Variable ist der einzige Kanal, über den der
Dienst Runtimes annimmt, und `PUT /policy` lehnt die Zusammensetzung der Liste
bewusst ab.

`sandbox.md#which-environments-an-agent-may-ask-for` hat das Format Feld für
Feld, die drei Fallen (der erste Eintrag ist die Voreinstellung, `network_mode`
wird nicht vererbt, ein Build wird beim Start durch `prewarm` bezahlt) und warum
die generierte Kopie in den Compose-Dateien nicht vom Katalog abweichen kann.

### Die Einstellungen des Dienstes selbst { #the-services-own-settings }

Jedes Feld der Konfiguration des Dienstes ist `SANDBOXD_` plus sein Name, das
hier ist also eine Teilmenge und kein Vokabular. Dies sind die, die die
ausgelieferten Compose-Dateien setzen oder die darüber entscheiden, ob Dateien
überleben:

| Variable | Ausgeliefert | Worüber sie entscheidet |
|---|---|---|
| `SANDBOXD_WORKSPACE_ROOT` | a host path | Wo das Arbeitsverzeichnis jeder Session liegt, per Bind-Mount vom *Host*. **Nicht gesetzt existieren Dateien nur innerhalb eines laufenden Containers** — ein Abräumen im Leerlauf verwirft sie, und die nächste Anfrage öffnet einen leeren Workspace, ohne dass etwas in einem Log steht. Es ist auch das, was das Browsen möglich macht: einen Workspace zu lesen startet nie einen Container |
| `SANDBOXD_SANDBOX_UID` | `10001` | Der unprivilegierte Benutzer, als der eine Sandbox läuft, statt als root — ein Ausbruch aus einem Container beginnt bei dem, als der der Container läuft, und jede Datei, die ein Agent schreibt, gehört auf dem Host dieser uid. **Muss die uid des Dienstes selbst sein**: Eine Session zu öffnen `chown`t den Workspace auf diesen Benutzer, und das kann ein unprivilegierter Dienst nur für sich selbst tun. Gilt für eine Runtime, die das Deployment *baut*, denn ein fertiges Image hat kein solches Konto, und ein Agent darin könnte nichts installieren |
| `SANDBOXD_CONTAINER_TTL` | 86400s | Wie lange ein *gestoppter* persistierter Container aufbewahrt wird. Holt zurück, was eine Session installiert hat — den Build, die Wheels, `node_modules` — und lässt den Workspace unangetastet, weil die Dateien die Arbeit sind. Nicht gesetzt werden sie für immer aufbewahrt |
| `SANDBOXD_PERSIST_CONTAINERS` | `true` | Der Container einer geschlossenen Session wird aufbewahrt statt entfernt, damit die nächste Session auf diesem Workspace ohne Build startet. Kostet einen gestoppten Container je Workspace; `SANDBOXD_CONTAINER_TTL` begrenzt das |
| `SANDBOXD_MAX_SESSIONS_PER_TENANT` | `5` | Eine Organisation kann den Pool nicht allein belegen. `SANDBOXD_MAX_SESSIONS` (20) ist der Pool |
| `SANDBOXD_NETWORK_MODE` | `none` | Das Standardnetz einer Sandbox. `none` ist gar kein Netz; eine Runtime darf für sich `bridge` nennen |
| `SANDBOXD_UI_ENABLED` | `0` | Das eigene Dashboard des Dienstes. Aus, weil es von einem Menschen verlangt, ein root-äquivalentes Token in einen Browser einzufügen |
| `SANDBOXD_IDLE_TIMEOUT` | 1800s | Wie lange eine untätige Session lebt, bevor sie geschlossen und abgeräumt wird |
| `SANDBOXD_MEM_LIMIT` | `1g` | Die Standard-Speicherobergrenze und damit die Zahl, von der der Prozentsatz `sandbox memory` im Chat ein Anteil ist |

### Den Dienst auf einem anderen Host betreiben { #running-the-service-on-another-host }

Nichts an einer Verbindung setzt eine lokale Adresse voraus — sie ist eine Zeile
mit einer URL und einer Vault-Zugangsinformation, und das Formular prüft, was
immer es bekommt. Ein Host anderswo braucht drei Dinge und keinen Code:

1. **Den Docker-Socket**, weil der Dienst Container startet. Das ist root auf
   dieser Maschine, weshalb das Token unten so viel wert ist, wie es wert ist.
2. **`SANDBOXD_WORKSPACE_ROOT` auf echter Platte, auf beiden Seiten unter
   demselben Pfad eingehängt.** Der Dienst legt das Verzeichnis an und bittet dann
   den *Daemon*, es per Bind-Mount einzuhängen, und der Daemon löst den Pfad auf
   dem Host auf — ein Named Volume oder ein Pfad, den es nur im Container des
   Dienstes gibt, wird mit `mounts denied` abgelehnt.
3. **TLS und ein Token, das niemand teilt.** Innerhalb von Compose ist die Adresse
   `http://sandboxd:8080` in einem privaten Netz; über das Internet hinweg ist es
   ein Dienst, der für jeden Befehle ausführt, der das Token hält, er gehört also
   hinter HTTPS mit einem eigenen Wert.

Registrieren Sie ihn danach in Sandboxes wie jeden anderen und richten Sie einen
Agent per Namen darauf. Der Compose-Dienst ist ein Deployment desselben Images.

### Wenn eine Session offen ist { #when-a-session-is-open }

Der Tab **Running** listet die Sessions, die der Dienst hält, alle zehn Sekunden
neu abgerufen, und eine Session ist ein Workspace auf einem Host. Drei Zustände,
und nur die ersten beiden treten auf:

- **running** — der Container existiert und ist resident. Wird durch den ersten
  Tool-Aufruf eines Agents in einer Unterhaltung geöffnet, nicht wenn die
  Unterhaltung beginnt.
- **hibernated** — die Zeile existiert und der Container nicht. Eine Session, die
  länger als `SANDBOXD_EVICT_IDLE_AFTER` untätig ist, wird schlafen gelegt, um
  einen Platz freizugeben, und ihre nächste Anfrage weckt sie. Das braucht
  `WORKSPACE_ROOT`, sonst würde das Aufwecken einen leeren Workspace öffnen, und
  der Dienst lehnt die Kombination ab, statt das zu tun.
- **gone** — nach `SANDBOXD_IDLE_TIMEOUT` wird die Session geschlossen und
  abgeräumt. Mit `PERSIST_CONTAINERS` überlebt der Container das, die nächste
  Session auf demselben Workspace startet also ohne Build.

Ein leerer Running-Tab heißt also, dass kein Agent kürzlich eine Shell benutzt
hat, und nicht, dass nichts konfiguriert ist — und ein Workspace mit Dateien
darin und ohne Session ist der normale Ruhezustand.

Der Dienst läuft hinter dem Compose-Profil `sandbox`, das in der lokalen
Entwicklung standardmäßig an ist und überall sonst aus, bis eine Betreiberin es
einschaltet — den Docker-Socket auf einem geteilten Host einzuhängen ist ein
bewusster Akt. `COMPOSE_DEV_PROFILES` im Makefile ist die eine Stelle, an der
sich das ändern lässt. `uv run agenticos cmd doctor` prüft jede registrierte
Verbindung: ob sie antwortet, ob sie ihre Zugangsinformation annimmt und ob sie
überhaupt irgendeine Runtime zulässt. Keine registrierte Verbindung ist eine
Warnung, kein Fehler — der `state`-Workspace braucht keine.

**Browsen, was die Agents behalten haben.** Workspaces ist ein eigener Bildschirm
— nicht Teil von Sandboxes, wo es um *Hosts* geht.

Jede Zeile nennt den Agent, die Unterhaltung, zu der die Dateien gehören (oder
wie viele Chats sie erreichen, bei einem Workspace, den keine einzelne
Unterhaltung besitzt), wer sie sehen kann, wie groß er ist und wann er zuletzt
genutzt wurde.

**Open** führt auf die eigene Seite dieses Workspace, in der Form, die der
Skills-Editor nutzt: der Baum links — Ordner werden einzeln durchlaufen, mit
einem Suchfeld über dem ganzen Baum statt über dem Ordner auf dem Bildschirm —
und die Datei selbst daneben gerendert. Drei Dateien zu lesen sind also drei
Klicks, und die Liste schließt sich nie.

Der Download sitzt auf der Zeile und nicht neben dem Reader, weil eine Datei
auszuwählen sie liest und ein großes Archiv eines ist, von dem jemand eine Kopie
will, ohne dafür zu bezahlen.

Eine zweite Ansicht auf der Liste flacht jede Datei, die die lesende Person sehen
kann, in ein Raster ab — die Frage „wer hält gerade eine Kopie dieser CSV“, die
die Seite je Workspace nicht beantworten kann.

**Ein Klick auf eine Datei öffnet sie in einem Viewer, und es ist derselbe Viewer
wie im Chat-Panel.** Ein Bild ist ein Bild, ein PDF ist die PDF-Ansicht des
Browsers, Markdown bietet *Preview* und *Source* — beides ist die Datei, und ein
`#`, aus dem still große Schrift wurde, ist die Art, wie jemand nicht bemerkt,
dass sein Agent Markdown in etwas schreibt, das nichts als Markdown liest —, und
alles andere ist sein Text. Der Download ist immer da, auch für das, was sich gar
nicht anzeigen lässt. Eine Komponente, denn „diese Datei öffnen“, das auf zwei
Bildschirmen zwei verschiedene Dinge heißt, ist die Art, wie dem zweiten ein Fall
fehlt.

Die Bytes kommen von `GET /sandbox-workspaces/{id}/raw?path=…` oder von
`GET /conversations/{id}/workspace/raw?path=…` für das Panel neben einem Chat.

Zwei Routen statt einer, weil sie unterschiedliche Aufrufende autorisieren — die
Route der Unterhaltung wird erreicht, indem die Unterhaltung geladen wird, sodass
jemand, mit dem ein Chat *geteilt* wurde, den Zugriff behält — und weil ein Modul
entscheidet, was angezeigt werden darf, damit die Antwort nicht je Oberfläche
abweichen kann.

Fast alles wird als Anhang ausgeliefert. **Rasterbilder und PDFs** werden zur
Anzeige ausgeliefert: ein Raster, weil es nichts ausführen kann, ein PDF, weil
der Browser es in seinem eigenen Viewer rendert, der nie das DOM der Seite
bekommt.

!!! danger "SVG und HTML sind herunterladbar und nie anzeigbar"

    Ein SVG, das von dieser Origin inline ausgeliefert wird, ist gespeichertes
    Cross-Site-Scripting, geschrieben von dem, was der Agent zu speichern
    beschlossen hat, und „der Agent hat es geschrieben“ ist keine
    Vertrauensgrenze.

Alles andere wird als `application/octet-stream` mit
`X-Content-Type-Options: nosniff` typisiert, damit ein Browser nicht doch noch
entscheiden kann, ein solcher Body sei HTML. Der Dateiname reist nur als
`filename*`, weil ein Workspace-Pfad beliebiges UTF-8 halten kann und die nackte
Form keine Möglichkeit hat, das zu sagen.

Nur ein **gespeicherter** Workspace kann beliebige Bytes ausliefern. Ein
containergestützter wird über das Archiv des Workspace gelesen, dessen einziger
Leser textuell ist, eine Textdatei wird also durch Kodieren ausgeliefert und
alles andere abgelehnt, statt still verstümmelt zu werden — der Browser bietet
den Download neben der Ablehnung an, damit die Antwort nie eine Sackgasse ist.

Dateien werden nur gelesen, wenn ein Workspace geöffnet wird oder wenn die flache
Ansicht eingeschaltet wird: Ein Deployment kann einen je warmer Unterhaltung
halten, jeden davon zum Rendern der Tabelle zu lesen wäre also eine Anfrage je
Zeile für eine Seite, an die noch niemand eine Frage gestellt hat. Die flache
Ansicht ist aus demselben Grund begrenzt und sagt das — wie viele Workspaces sie
gelesen hat, wie viele nicht, und ob es weitere gibt. Eine kürzere Liste ist sonst
nicht von weniger Dateien zu unterscheiden.

**Wer welchen Workspace sieht, wird je lesender Person in der Abfrage
entschieden.** Eine aufrufende Person mit `connections:manage` sieht die der
Organisation — die ehrliche Latte für eine Liste, die Chats überquert, die ihr
nicht gehören. Alle anderen sehen die Workspaces, an denen sie beteiligt sind:
ihre eigenen `user`-skopierten Dateien, die Workspaces ihrer eigenen
Unterhaltungen und den geteilten Workspace eines Agents, mit dem sie gesprochen
haben. Bewusst „gesprochen haben“ statt „öffnen könnten“: `agent`-Scope teilt
einen Workspace über die Nutzer eines Agents hinweg, und das Chat-Panel zeigt
diese Dateien ohnehin jedem in einer Unterhaltung mit ihm, den Agent öffnen zu
*können* ist also ein weiterer Anspruch, als diese Liste erhebt.

`channel`-Scope ist nur für eine Betreiberin sichtbar, und das ist richtig statt
ein Versehen — er hängt an einem Slack- oder Telegram-Chat, die Menschen, die ihn
teilen, sind also über diese Plattform identifiziert und nicht über eine Zeile in
`users`.

Ein per id geladener Workspace wendet dieselben drei Prädikate an und antwortet
**not found** statt forbidden, wenn sie scheitern: Eine id darf nicht nutzbar
sein, um herauszufinden, welche Workspaces in der Unterhaltung einer Kollegin
existieren. Nichts hier überquert eine Organisation — ein App-Admin, der die
Dateien eines anderen Tenants durchsieht, wäre der eine Lesevorgang, den diese
Plattform ablehnt, also wechselt er die Organisation wie alle anderen.

**Ein containergestützter Workspace wird vom Host-Volume gelesen, und dafür
braucht es eines.** Der Sandbox-Dienst liefert diese Dateien aus
`SANDBOXD_WORKSPACE_ROOT`, und das ist es, was eine Unterhaltung vom letzten Monat
ihre Dateien listen lässt, nachdem ihre Session abgeräumt wurde — es wird kein
Container gestartet, um zu antworten. Ein Dienst, der *ohne* eines konfiguriert
ist, behält nichts auf der Platte, seine Dateien existieren also nur, solange eine
Sandbox läuft, und lassen sich nicht lesen, ohne eine zu starten: Das Files-Panel
könnte dann nur das sagen, für eine Datei, die der Agent nachweislich gerade
geschrieben hatte.

Jede Compose-Datei setzt deshalb eines, übersteuerbar mit
`SANDBOX_WORKSPACE_ROOT` — eine Umgebungsvariable dort, wo Compose sie
interpoliert, also im Projektwurzelverzeichnis statt in `backend/.env`, außer bei
den Targets `dev` und `prod`, die diese Datei ausdrücklich übergeben.

Ein Host-Pfad, auf beiden Seiten an derselben Stelle per Bind-Mount eingehängt,
weil der Dienst das Verzeichnis anlegt und dann den *Daemon* bittet, es
einzuhängen — und der Daemon löst den Pfad auf dem Host auf. Ein Named Volume
oder irgendein Pfad, den es nur im Container des Dienstes gibt, wird mit
`mounts denied` abgelehnt.

| | Standard | |
|---|---|---|
| Lokale Entwicklung | `/tmp/agenticos-sandbox-workspaces` | Docker Desktop teilt es und jeder darf hineinschreiben, ein Laptop braucht also keine Einrichtung |
| Die Server-Dateien | `/var/lib/agenticos/sandbox-workspaces` | Muss existieren und für uid 10001 beschreibbar sein — `sudo mkdir -p <path> && sudo chown 10001:10001 <path>`, einmalig. Nicht `install -d -o 10001`: `install` löst den Eigentümer über die passwd-Datenbank auf und lehnt eine uid ab, der kein Konto gehört. Es gehört auf Speicher, den jemand sichert |

Ein Neustart fegt `/tmp` leer, und das ist der eine Grund, ein echtes Deployment
nicht dorthin zu richten.

Das wird gemeldet und nicht geworfen. Jede Liste trägt `unreadable_reason`, und
ein Client zeigt es als Erklärung statt als Fehler — denn keine der beiden
Ursachen ist ein Defekt: Ein Dienst, der nichts auf der Platte behält, ist eine
Konfiguration mit einer einzeiligen Lösung, die die Nachricht nennt, und ein Host,
der unten ist, ist später wieder oben.

Es zu werfen machte daraus eine 500, die ein Browser nur als „etwas ist
schiefgelaufen“ rendern konnte, neben einer leeren Liste, die sich als „es gibt
keine Dateien“ liest. Zwei falsche Antworten auf einmal.

*Eine Datei* von einem solchen Host zu lesen wird mit demselben Satz abgelehnt,
statt als „keine solche Datei“ gemeldet zu werden, was sagen würde, die Datei
fehle, obwohl sie da ist.

**Was läuft, wird ebenfalls vom Dienst gelesen.**

Der Bildschirm Sandboxes hält das auf einem eigenen Tab, getrennt von der Tabelle
der Verbindungen, und listet die offenen Sandboxes dieser Organisation auf dem
Host, den er nennt — der Standardverbindung, bis die Betreiberin eine andere
wählt.

Jede Zeile trägt die Runtime, was sich diese Sandbox teilt, ihre Leerlaufzeit und
ihren Speicher gegen ihre eigene Obergrenze, wenn danach gefragt wird. Sortierbar
nach Leerlaufzeit und Speicher. Daneben steht das Aktivitätsprotokoll je Sandbox:
welche Pfade gelesen wurden, welche Befehle liefen und wie jeder davon ausging.

Weder Dateiinhalte noch Befehlsausgaben zeichnet der Dienst auf, und genau das
hält einen Audit-Trail davon ab, ein Weg zu werden, die Arbeit eines anderen
Agents zu lesen.

Das Dashboard beantwortet dieselben drei Fragen in einem eigenen Abschnitt, für
eine aufrufende Person mit `connections:manage`. Der Speicher liegt dort aus
demselben Grund hinter einem Schalter wie auf dem Bildschirm: Der Dienst
beprobt jede Sandbox dafür einzeln.

**Alle drei Obergrenzen teilen jetzt sauber.**

Die Session-Liste ist auf die Organisation der aufrufenden Person gefiltert, aber
sie reicht `SANDBOXD_MAX_SESSIONS` und `SANDBOXD_MAX_OPEN_SESSIONS` unverändert
vom Dienst durch — diese beiden zählen also jeden Tenant auf dem Host, während
die Zeilen einen zählen. `len(sessions)` teilt nur gegen
`SANDBOXD_MAX_SESSIONS_PER_TENANT`.

Die Antwort trägt deshalb zwei hostweite Zähler für das andere Paar, genommen aus
der ungefilterten Liste, bevor der Filter sie verengt:

- `host_session_count` — die residenten Sandboxes, die der Dienst als
  `state == "running"` markiert, gegen `limit`;
- `host_open_count` — jede Session, die existiert, resident oder schlafend, gegen
  `open_limit`.

Jetzt kann die Kapazitätskarte sagen, warum eine Session abgelehnt wurde, während
diese Organisation unter ihrer eigenen Obergrenze liegt: Der Host selbst ist voll
mit der Arbeit von jemand anderem.

Dass die beiden hostweit sind, ist eine bewusste, eng gefasste Offenlegung — zwei
aggregierte ganze Zahlen, die nichts benennen, weit entfernt von den
Session-Zeilen, die der Filter zurückhält — und die Liste ist auf
`connections:view` gegattert, die Befugnis, einen Host zu beobachten, und nicht
die irgendeines Mitglieds.

Bei einer Daytona-Verbindung sind sie `None`, denn sie erzwingt keine unserer
Obergrenzen, die sich teilen ließen.

Diese Liste wird **gefiltert, nicht durchgereicht**. Ein `sandboxd` antwortet für
jede Organisation, die an seiner Adresse eine Verbindung registriert hat, seine
Antwort durchzureichen zeigte einem Tenant also die Container eines anderen.
Sessions werden über das `tenant`-Label abgeglichen, das diese Plattform setzt,
wenn sie eine öffnet, und aus `agent_workspaces` benannt statt durch Dekodieren
der Session-id — die id kodiert den Scope-Key, und ihn zurückzuparsen machte aus
diesem Format ein Schema.

**Was der Dienst zulässt, wird vom Dienst gelesen.** Die Allowlist der Runtimes
und die Obergrenze hinter jedem Alias (`SANDBOXD_RUNTIMES`, `SANDBOXD_MEM_LIMIT`,
`SANDBOXD_NETWORK_MODE`, `SANDBOXD_MAX_SESSIONS_PER_TENANT` und der Rest) sind
seine eigene Boot-Konfiguration, und es gibt bewusst keinen Endpunkt, sie zu
schreiben: Ein Browser, der den Prozess umkonfigurieren könnte, der den
Docker-Socket hält, besäße den Host. Der Bildschirm Sandboxes und die
Runtimes-Karte des Dashboards *lesen* sie beide, damit sichtbar ist, was gilt, und
der Builder bietet einem Agent nur die Aliase an, die der Dienst tatsächlich
annimmt.

Keine der beiden Ansichten fragt eine Daytona-Verbindung danach. Sie
veröffentlicht keine eigene Allowlist und hält keine unserer Sessions zum
Aufzählen — was sie erlaubt, ist eine Einstellung auf diesem Konto, und was dort
läuft, ist in ihrem eigenen Dashboard sichtbar.

## Messaging-Kanäle { #messaging-channels }

| Variable | Standard | Beschreibung |
|----------|---------|-------------|

Bot-Zugangsdaten werden nicht hier konfiguriert: Jeder Bot wird in der App
registriert, sein Token im Vault versiegelt, und ein Slack-Bot trägt zusätzlich
das Signing Secret seiner eigenen App und ein `xapp-`-Token
(`SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` und `SLACK_APP_TOKEN` wurden entfernt
— jeder Bot ist jetzt seine eigene Slack-App). Telegram-Webhook-URLs werden aus
`PUBLIC_BASE_URL` gebaut (`TELEGRAM_WEBHOOK_BASE_URL` wurde entfernt), Model
Profiles dürfen ohne jedes Flag auf lokale Endpunkte wie Ollama zeigen
(`ALLOW_INTERNAL_MODEL_ENDPOINTS` wurde entfernt), und die Sandbox-Grenzen von
`run_python` sind Capability-Konfiguration je Agent
(`CODE_EXECUTION_TIMEOUT_SECS` / `CODE_EXECUTION_MAX_MEMORY_MB` wurden entfernt).

## CORS { #cors }

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `CORS_ORIGINS` | `["http://localhost:3000","http://localhost:8080"]` | Erlaubte Origins (JSON-Array) |
| `CORS_ALLOW_CREDENTIALS` | `true` | Credentials (Cookies) erlauben |
| `CORS_ALLOW_METHODS` | `["*"]` | Erlaubte HTTP-Methoden |
| `CORS_ALLOW_HEADERS` | `["*"]` | Erlaubte HTTP-Header |

Prüfung für die Produktion: `CORS_ORIGINS` darf bei `ENVIRONMENT=production` kein
`"*"` enthalten.

## Rate Limiting { #rate-limiting }

Wird auf die Oberflächen angewandt, die eine fremde Person erreichen kann, und
nur auf diese: die öffentliche Run-API, das Skript des Widgets, dessen Config, den
Socket-Handshake beider Oberflächen, Config und Logo einer Hosted Page und den
Upload einer besuchenden Person. Die Routen der Konsole selbst liegen hinter einer
Session und werden nicht gemessen — ob die ganze API eine Obergrenze tragen
sollte, ist eine eigene Entscheidung und nicht diese.

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `RATE_LIMIT_RUN_PER_MINUTE` | `30` | `POST /api/v1/agents/{id}/run`, je aufrufender Seite |
| `RATE_LIMIT_AUTH_PER_MINUTE` | `10` | Jede Route in `auth.py` — Login, Registrierung, Refresh, die Anfrage- und Verifikationsrouten für Reset und Magic Link. Gezählt **je IP und, wo der Body eine trägt, je übermittelter Adresse**. Siehe unten |
| `RATE_LIMIT_EMBED_PER_MINUTE` | `20` | Je Adresse, und **zwei getrennte Zähler dieser Größe**: einer für `widget.js`, einer für die Zulassung — das `/config` des Widgets plus den Socket-Handshake beider Oberflächen. Siehe unten |
| `RATE_LIMIT_HOSTED_PAGE_PER_MINUTE` | `240` | Die Config einer Hosted Page, **je Seite** — und ihr Logo, auf einem eigenen Zähler. Siehe unten |
| `RATE_LIMIT_EMBED_UPLOAD_PER_MINUTE` | `5` | Dateien, die eine besuchende Person auf einer Hosted Page ablegen darf. Gezählt **je Adresse und je Visitor Key**, und beide müssen es zulassen — der Key wird vom Browser erzeugt, nur ihn zu zählen begrenzt also nichts |
| `RATE_LIMIT_TRUST_FORWARDED_FOR` | `false` | Ob `X-Forwarded-For` die aufrufende Seite benennt |

**Was eine abgelehnte aufrufende Seite bekommt**, ist der eigene Fehlerumschlag
dieser API mit `code: "RATE_LIMIT_EXCEEDED"`, dem Intervall in
`error.details.retry_after_seconds` und demselben Intervall im Header
`Retry-After` — auf den ein Fetch-Wrapper oder ein CDN tatsächlich zurücknimmt.
Der Socket-Handshake ist die Ausnahme, weil ein WebSocket keinen Status hat, mit
dem er antworten könnte: Er schließt mit `4029` (siehe
[Kanäle](channels.md#the-raw-websocket)).

**Zwei Zähler, nicht einer, und der Grund ist Arithmetik.**

Eine Seite mit einem Widget darauf zu laden kostet drei Anfragen an diese API: das
Skript, die Config und den Socket. Zusammen gezählt kauften `20` für einen kalten
Browser etwa sieben Seitenaufrufe statt zwanzig Zulassungen — und eine Grenze, die
um den Faktor drei falsch ist, ist schlimmer als keine Grenze, weil sie sich als
die Zahl liest, die Sie gesetzt haben.

`widget.js` hat deshalb einen eigenen Topf. Es ist cachebar, und eine Ablehnung
dort macht das Widget ganz kaputt, statt eine Nachricht zu verzögern.

Die Config und der Handshake bleiben zusammen, weil sie zusammen *eine* Zulassung
sind: Ein Browser, der eine Config gelesen und keinen Socket geöffnet hat, ist
nicht hineingekommen.

Die Zählstände liegen im Redis des Deployments, sie halten also über Worker hinweg
— die Produktion fährt vier, und ein Zählstand je Prozess ließe das Vierfache
dessen durch, was er sagt. Ist Redis nicht erreichbar, wird die Grenze nicht
angewandt und eine Warnung protokolliert: Einer besuchenden Person ihre Antwort zu
verweigern, weil ein Cache gezuckt hat, ist das schlimmere der beiden Versagen.

Was eine besuchende Person, einmal zugelassen, *sagen* darf, ist eine andere Zahl,
je Widget im Builder gesetzt (`rate_limit_per_minute`) und je besuchender Person
gezählt. Diese beiden hier sind die Obergrenze fürs Hineinkommen.

### `RATE_LIMIT_HOSTED_PAGE_PER_MINUTE`, und warum es nicht je Adresse zählt { #rate_limit_hosted_page_per_minute-and-why-it-is-not-per-address }

Die Config einer Hosted Page wird **serverseitig** vom Frontend geholt, damit die
Seite im ersten Frame gebrandet erscheint. Das heißt, die Adresse auf der Anfrage
ist die des Frontend-Containers und nicht die der besuchenden Person — sie zu
zählen legte also jeden Aufruf einer Hosted Page im Deployment in einen einzigen
Topf, und die besuchende Person, die ihn auslöste, bekam eine 404 ohne jeden
Hinweis, warum. `RATE_LIMIT_TRUST_FORWARDED_FOR` hilft nicht: Ein serverseitiges
`fetch` schickt keinen solchen Header, dem jemand vertrauen könnte.

Dieses eine wird deshalb je Public Key gezählt. Es begrenzt eine einzelne Seite,
statt eine besuchende Person zu rationieren, weshalb die Voreinstellung weit ist
— **es ist nicht das, was Ausgaben begrenzt.** Ausgaben beginnen an dem Socket,
den die Seite als Nächstes öffnet, den der Browser aufbaut und der je Adresse
unter `RATE_LIMIT_EMBED_PER_MINUTE` gezählt wird. Und einen Key zu raten ist keine
Strategie gegen 192 Bit `secrets.token_urlsafe`.

### `RATE_LIMIT_AUTH_PER_MINUTE`, und warum die Auth-Oberfläche eine eigene hat { #rate_limit_auth_per_minute-and-why-the-auth-surface-has-its-own }

Jede Route in `auth.py` trägt diese Grenze, gezählt **je IP** und — wo der Body
eine Adresse trägt (Login, Registrierung, die Anfragen für Reset und Magic Link) —
**auch je übermittelter Adresse**, beide gegen dieselbe Zuteilung. Die beiden
halten unterschiedliche Angriffe auf: Die IP begrenzt eine Flut aus einer Quelle,
die Adresse begrenzt einen Brute-Force-Angriff auf ein Konto.

Sie ist von der Run-Zuteilung getrennt und niedriger als diese, weil sie die
Kosten eines **einzelnen Versuchs** abwehrt. `verify_password` ist bcrypt, ~170 ms
ohne Unterbrechungspunkt, eine ungemessene Flut auf `/login` für jede Adresse, die
ein Konto hat, sättigt also den Event Loop eines Workers ganz ohne Zugangsdaten.

Zwei weitere Dinge schließen den Rest dieser Oberfläche und brauchen keine
Konfiguration:

- bcrypt läuft in einem Thread, blockiert den Loop also nie;
- eine Adresse **ohne** Konto wird gegen einen Dummy-Hash geprüft statt
  übersprungen, eine bekannte und eine unbekannte Adresse brauchen für die
  Ablehnung also gleich lang und das Timing sagt nicht mehr, welche Adressen es
  gibt.

### `RATE_LIMIT_TRUST_FORWARDED_FOR`, und warum es aus ist { #rate_limit_trust_forwarded_for-and-why-it-is-off }

Grenzen je Adresse zählen `request.client.host`. **Hinter einem Proxy oder einem
CDN ist das die Adresse des Proxys und nicht die der besuchenden Person** — jede
besuchende Person teilt sich einen Topf, eine belebte Seite hinter Cloudflare
erschöpft die zwanzig Zulassungen des Widgets pro Minute also für alle auf einmal.
Das hier einzuschalten liest stattdessen den **rechtesten** `X-Forwarded-For`-Hop
— die Adresse, die der vertraute Proxy selbst angehängt hat.

Es ist standardmäßig aus, weil den Header setzt, wer auch immer aufruft.
Bedingungslos vertraut, wird aus einer Grenze je Adresse eine Grenze je Header,
die jeder umgeht, indem er eine Zeichenkette variiert.

Der **rechteste** Hop wird aus demselben Grund gelesen und nicht der linkeste:
`X-Forwarded-For` ist eine Liste, die der Client beginnt und an die jeder Proxy
anhängt, der Kopf ist also das, was der Client getippt hat, und nur das Ende ist
das, was ein Proxy geschrieben hat, den Sie kontrollieren.

**Die Auth-Oberfläche braucht das ebenfalls, und das Frontend macht es jetzt
möglich.** Auth-Anfragen erreichen die API serverseitig über die eigenen Routen
`/api/auth/*` des Frontends, ohne Hilfe ist die Adresse darauf also die des
Frontend-Containers, und die Je-IP-Hälfte von `RATE_LIMIT_AUTH_PER_MINUTE` legt
das ganze Deployment in einen Topf — etwa elf Logins sperren dann alle für eine
Minute aus, und ein erschöpfter Refresh-Topf meldet Sessions ab. Anders als beim
Config-Abruf einer Hosted Page **leiten diese Routen das `X-Forwarded-For` der
aufrufenden Seite weiter**
([#1047](https://github.com/vstorm-co/agenticos/issues/1047)), mit dieser
Einstellung an schlüsselt die Grenze also auf den echten Client. Schalten Sie sie
für die Auth-Grenze unter derselben Regel ein wie für alles andere — ein Proxy,
den Sie kontrollieren, davor, der den Client als rechtesten Hop anhängt —, und
genau diese Deployment-Entscheidung ist diese Einstellung; aus gelassen bleibt die
Grenze sicher, aber geteilt.

!!! danger "Schalten Sie es nur ein, wenn ein einziger Proxy, den Sie kontrollieren, das Einzige ist, was die API erreichen kann"

    Ist der Port des Containers ebenfalls veröffentlicht, kann eine aufrufende
    Seite den Header selbst setzen und die Grenze bedeutet nichts mehr.

    **Der Port des Frontends zählt hier als der der API.** Seine Routen
    `/api/auth/*` leiten jedes `X-Forwarded-For` weiter, das sie bekommen haben,
    wer also am Proxy vorbei Port 3000 erreicht, wählt genauso sicher die Adresse,
    gegen die seine Login-Versuche gezählt werden, wie jemand, der Port 8000
    erreicht — und jeder angenommene Versuch gegen eine Adresse, die niemand hält,
    kostet trotzdem ein bcrypt. `docker-compose-prod.yml` und
    `docker-compose-prod.frontend.yml` veröffentlichen deshalb standardmäßig auf
    `127.0.0.1`, wo der Reverse Proxy des Hosts sie erreicht und sonst nichts.
    `BIND_HOST=0.0.0.0` öffnet sie wieder, für einen Proxy, der tatsächlich
    anderswo läuft — mit dem Netz dieses Proxys als dem, was das Versprechen hält.

    Mit zwei Proxys davor falten Sie den Header an Ihrer Kante auf einen Hop
    zusammen — nur der letzte Hop ist vertrauenswürdig.

## Ein Worker, dessen Event Loop sich nicht mehr dreht { #a-worker-whose-event-loop-has-stopped-turning }

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `EVENT_LOOP_WEDGED_AFTER` | `15` | Sekunden, die der Event Loop stillstehen darf, bevor der Worker getötet und ersetzt wird. `0` oder darunter schaltet die Prüfung ab |

Ein Worker, der *lebt, aber nicht antwortet* — verklemmt auf einem Lock, drehend
in einem synchronen Aufruf, blockiert auf einem Socket, der nie antwortet —, hat
keinen Exit-Code, jeder Wiederherstellungspfad in jedem Stack las ihn also als
gesund, während Anfragen in Timeouts liefen. Der Container geht auf `unhealthy`,
und ein Status ist kein Mechanismus.

Also beurteilt der Worker seinen eigenen Event Loop. Ein Timer-Callback stempelt
den Loop einmal pro Sekunde; ein Thread liest den Stempel, und wenn sich der Loop
über zwei aufeinanderfolgende Prüfungen hinweg `EVENT_LOOP_WEDGED_AFTER` lang
nicht gedreht hat, beendet er den Prozess — `SIGKILL`, oder `os._exit(137)`, wo
der Worker PID 1 ist, weil der Kernel dem init eines Namespace kein Signal
zustellt, für das init keinen Handler hat. So oder so meldet `docker inspect`
`137`, und aus „verklemmt“, das nichts behandelt hat, wird „weg“, das jeder Stack
längst behandelt:

| Stack | Was den Worker ersetzt |
|---|---|
| `docker-compose.yml` | der Reload-Supervisor, bei seiner nächsten Abfrage |
| `docker-compose-dev.yml` | PID 1 ist der Server, der Container endet also und `restart: unless-stopped` greift |
| `docker-compose-prod.yml` | `Multiprocess` von uvicorn, innerhalb einer knappen halben Sekunde; die anderen drei Worker bedienen weiter |

Zwei Eigenschaften sind der Grund für das Design, und beide lohnen sich zu wissen,
bevor die Zahl geändert wird:

- **Sie misst Liveness, nicht Readiness.** Der Stempel ist ein Timer-Callback und
  keine Anfrage, eine langsame Datenbank oder ein Model Provider, der zwanzig
  Sekunden braucht, ist also keine Verklemmung — der Loop dreht sich, er wartet.
  Eine HTTP-Probe wären weniger bewegliche Teile gewesen und würde einen gesunden
  Server gegen eine kaputte Abhängigkeit in eine Neustartschleife schicken.
- **Zwei Prüfungen, nicht eine.** `docker pause`, eine eingefrorene cgroup und ein
  Laptop, der aus dem Schlaf erwacht, halten den Watchdog ebenso gründlich an wie
  den Loop, die erste Prüfung danach liest also einen veralteten Stempel, der
  nichts sagt.

Der Reload-Supervisor des lokalen Stacks liest dieselbe Variable für das Urteil,
das er von *außerhalb* des Workers fällt, eine Zahl deckt also beides ab.

!!! tip "Setzen Sie sie beim Debuggen auf `0`"

    Ein Breakpoint blockiert den Event Loop, und nichts kann das von einem
    Deadlock unterscheiden, ein Worker, der auf einem sitzt, wird Ihnen sonst
    unter den Händen getötet.

Sie kann einen Prozess nicht sehen, der überhaupt nicht läuft — `kill -STOP`, eine
eingefrorene cgroup —, weil ein Watchdog in einem angehaltenen Prozess ebenfalls
angehalten ist. Diesen Fall decken die Supervisoren bereits ab: Der Takt des
Reload-Supervisors wird schal und der Pipe-Ping der Produktion bleibt unbeantwortet.

## Docker / Produktion { #docker-production }

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `DOMAIN` | `example.com` | Produktionsdomain (für Traefik) |
| `ACME_EMAIL` | `admin@example.com` | Let's-Encrypt-Adresse für SSL-Zertifikate |
| `REDIS_PASSWORD` | `change-me-in-production` | Redis-Passwort für die Produktion |

## Checkliste für die Produktion { #production-checklist }

!!! danger "Jedes davon wird mit einem Standardwert ausgeliefert, der in der Produktion falsch ist"

    Ein Deployment, das von anderswo erreichbar ist, hat alle neun bewusst gesetzt.

- [ ] `SECRET_KEY` — ein eindeutiger Hex-Key mit 64 Zeichen: `openssl rand -hex 32`
- [ ] `API_KEY` — ein eindeutiger Key: `openssl rand -hex 32`
- [ ] `VAULT_MASTER_KEY` — ein eindeutiger Key: `openssl rand -hex 32`. Die
      Konfiguration lehnt einen leeren außerhalb von `local`/`development` ab
- [ ] `ENVIRONMENT` — `production`
- [ ] `DEBUG` — `false`
- [ ] `POSTGRES_PASSWORD` — ein starkes, eindeutiges Passwort
- [ ] `REDIS_PASSWORD` — ein starkes Passwort
- [ ] `CORS_ORIGINS` — nur Ihre tatsächlichen Frontend-Domains
- [ ] `OPENROUTER_API_KEY` — Ihr Produktions-API-Key

E-Mail steht bewusst **nicht** auf dieser Liste: Ein Deployment läuft auch ohne.
Aber Einladungen, Passwort-Zurücksetzungen und Benachrichtigungen bleiben still
ungesendet, bis `SMTP_HOST` und der Rest von [E-Mail (SMTP)](#email-smtp) auf
einen echten Server zeigen — ein Deployment, das darauf verzichtet, sollte das
also wissentlich tun.
