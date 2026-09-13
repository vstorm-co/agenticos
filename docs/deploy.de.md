---
source_sha: 6f2247bf1919
---

# Auf einem Server deployen { #deploy-to-a-server }

Ein Host, Docker Compose, ein Reverse Proxy davor. Das ist der gesamte
ausgelieferte Weg, und genau er läuft in den Deployments, in denen dieses
Projekt eingesetzt wird.

Es gibt keine Kubernetes-Manifeste und keine Ein-Klick-Schnellstarts für die
Platform-as-a-Service-Anbieter. Das ist keine Bescheidenheit in Bezug auf die
Skalierung. Der Stack besteht aus sechs Containern, zwei davon halten Zustand,
einer kann eigene Container starten, und einer ist ein Postgres, das pgvector
haben muss - was bereits mehr ist, als ein `git push`-Deploy-Ziel abbildet, und
eine Anleitung, die etwas anderes vorgäbe, würde ein Deployment beschreiben, das
niemand betrieben hat.

!!! tip "Lesen Sie zuerst die [Produktions-Checkliste](configuration.md#production-checklist)"

    Neun Einstellungen werden mit Standardwerten ausgeliefert, die auf einem Laptop
    in Ordnung und auf einem Host, den jemand anderes erreichen kann, falsch sind.
    `scripts/server-init.sh` weiter unten erzeugt alle neun, die Checkliste ist also
    das, was Sie danach prüfen, und nicht das, was Sie tippen.

## Was Sie brauchen { #what-you-need }

| | |
|---|---|
| **Einen Host** | 4 vCPU und 8 GB RAM genügen. Siehe [Dimensionierung](#sizing-the-host) |
| **Docker** | Engine 24+ mit dem Compose-Plugin (2.24 oder neuer), und Ihr Benutzer in der Gruppe `docker`. Auf dem Host wird nichts gebaut: die Images werden von GHCR geholt |
| **Zwei Hostnamen** | einen für die Website, einen für die API — siehe [warum zwei](#why-two-hostnames) |
| **Einen Reverse Proxy** | [Traefik](#option-a-traefik) oder [Nginx](#option-b-nginx). Er terminiert TLS |
| **Einen OpenRouter-Key** | jede Collection embeddet darüber. Chat-Modelle werden pro Organisation im Produkt konfiguriert |

Der Host braucht außerdem die Ports 80 und 443 offen, und sonst nichts. Postgres,
Redis und die Prefect-API sind auf keiner Schnittstelle veröffentlicht.

### Warum zwei Hostnamen { #why-two-hostnames }

Der Browser spricht mit beiden. Die meisten Aufrufe laufen über die
serverseitigen Routen des Frontends, aber der Chat-WebSocket verbindet sich
direkt mit der API, also braucht die API einen Namen, den ein Browser auflösen
kann, und ein eigenes Zertifikat.

`app.example.com` und `api.example.com` ist die Form. Es können zwei beliebige
Namen sein; was sie nicht sein dürfen, ist ein Name mit einem Pfadpräfix, denn
die Cookies der API und die der Website sind auf den Host begrenzt.

## Den Host dimensionieren { #sizing-the-host }

Auf einem im Leerlauf befindlichen Deployment gemessen, nicht geschätzt:

| | im Ruhezustand | Obergrenze |
|---|---|---|
| `app` (2 uvicorn workers) | ~1,0 GB | 2,5 GB bei den standardmäßigen 4 Workern |
| `db` | ~1,3 GB mit dem Tuning unten | 2 GB |
| `prefect-runner` | 241 MiB | 1,5 GB |
| `prefect-server` | 245 MiB | 768 MB |
| `frontend` | ~300 MB | 1 GB |
| `redis` | 9 MiB | 512 MB |

Die Zahl, die über den Host entscheidet, ist **`UVICORN_WORKERS`**. Jeder Worker
ist ein eigener Prozess, der die gesamte Anwendung importiert — 460 MiB, per
Spawn statt per Fork erzeugt, es wird also nichts geteilt. Vier davon sind 1,9 GB,
bevor eine Anfrage eintrifft.

Zwei Worker passen zu einem Team von zehn Personen und lassen immer noch einen
bedienen, während
[der Watchdog](configuration.md#a-worker-whose-event-loop-has-stopped-turning)
ein festgefahrenes Geschwister ersetzt. Ein Worker ist die Einstellung, die es zu
vermeiden gilt: eine blockierte Event Loop ist dann das gesamte Deployment, bis
es sich selbst beendet.

!!! note "Die Datenbank ist auf ihr eigenes Limit hin abgestimmt"

    `docker-compose-prod.yml` betreibt Postgres mit `shared_buffers=512MB` gegen ein
    Limit von 2 GB und gibt ihm 512 MB `/dev/shm` — Dockers Standard sind 64 MB, die
    ein paralleler Scan über die Vektoren einer Collection erschöpft, mit der Meldung
    `could not resize shared memory segment`. Verschieben Sie das Limit, verschieben
    Sie das Tuning mit; sie stehen aus diesem Grund nebeneinander.

## Die Namen auf den Host zeigen lassen { #point-the-names-at-the-host }

Zwei A-Records, vor allem anderen. Let's Encrypt weist nach, dass Sie einen Namen
kontrollieren, indem es eine Datei über HTTP von dort abruft, wohin der Name
auflöst; ein Zertifikat wird also erst ausgestellt, wenn das zutrifft und
propagiert ist.

```
app.example.com   A   203.0.113.10
api.example.com   A   203.0.113.10
```

!!! warning "Ein Wildcard erledigt das nicht für Sie"

    Wo `*.example.com` bereits irgendwohin zeigt — meist auf eine Marketing-Website —
    lösen beide Namen dorthin auf. Ein Record für den konkreten Namen schlägt einen
    Wildcard, die Lösung besteht also darin, die beiden oben hinzuzufügen, und nicht
    darin, den Wildcard zu entfernen.

Prüfen Sie von einem Ort, der nicht der Host ist, denn der Host kann eine eigene
Antwort haben:

```bash
dig +short app.example.com api.example.com
```

## Es auf den Host bringen { #get-it-onto-the-host }

```bash
sudo install -d -o "$USER" -g "$USER" /opt/agenticos
git clone https://github.com/vstorm-co/agenticos.git /opt/agenticos
cd /opt/agenticos
bash scripts/server-init.sh
```

`server-init.sh` schreibt `backend/.env`: es erzeugt die fünf Secrets, fragt nach
den beiden Hostnamen, nach einer Adresse für Let's Encrypt und nach dem
OpenRouter-Key und leitet die öffentlichen URLs und den CORS-Origin aus Ihren
Angaben ab. Eine bestehende Datei überschreibt es nicht.

Der Klon ist der Ort, an dem die Compose-Dateien und diese env-Datei liegen; von
dort läuft kein Code. Was läuft, sind die beiden Images, die das Repository
veröffentlicht.

### Die Images { #the-images }

| | |
|---|---|
| `ghcr.io/vstorm-co/agenticos-backend` | Die API, der Prefect-Runner und die Migrationen - ein Image, drei Kommandos |
| `ghcr.io/vstorm-co/agenticos-frontend` | Die Konsole |

Beide werden von `.github/workflows/images.yml` für `linux/amd64` und
`linux/arm64` gebaut. Ein Release (`v0.0.380`) veröffentlicht `0.0.380` und
verschiebt `latest`; jeder Commit auf `main` veröffentlicht `edge` und
`sha-<short>`. Die Compose-Dateien lesen den Tag aus `AGENTICOS_VERSION` in
`backend/.env` und fallen auf `latest` zurück.

Drei Regeln, die der Workflow einhält, jede davon wissenswert, bevor Sie sich auf
einen Tag verlassen:

- **Nur ein Commit auf `main` wird jemals veröffentlicht.** Ein `v*`-Tag, der von
  einem Branch aus gesetzt wird, oder ein dort gestarteter Lauf, wird abgelehnt,
  bevor irgendetwas gebaut wird - `latest` kann also nicht über die Grenze des
  Pull Requests hinausgelangen.
- **Ein Release auf einem Commit, den `main` bereits gebaut hat, wird nicht neu
  gebaut.** Sein `sha-<short>`-Manifest erhält die Version und `latest` als
  zusätzliche Namen, damit die Digests, auf die ein Host gepinnt ist, genau die
  sind, die das Release benennt.
- **Ein Commit ohne Images kann sie bekommen.** Starten Sie den Workflow von Hand
  mit seiner `sha`-Eingabe - `gh workflow run images.yml --ref main -f sha=<commit>` -
  und er veröffentlicht den `sha-<short>`-Tag dieses Commits und nichts, was sich
  bewegt. Das ist der Weg für einen Commit, der älter ist als der Workflow, und
  für einen, dessen Lauf verloren ging.

!!! warning "Pinnen Sie ein Release auf einem Host, der Ihnen wichtig ist"

    `AGENTICOS_VERSION=0.0.380` in `backend/.env`, damit `make prod` an einem
    schlechten Tag das holt, was gestern lief, und nicht das, was heute Morgen
    veröffentlicht wurde. `scripts/deploy.sh` pinnt für Sie - auf den `sha-`-Tag des
    Commits, den es deployt - für genau so lange, wie der Deploy läuft.

Beide Pakete lassen sich anonym holen. Antwortet ein Pull mit `unauthorized`,
wurde das Paket auf privat gestellt oder ein veraltetes `docker login ghcr.io`
steht im Weg; keines von beidem kann ein Host von sich aus beheben.

!!! danger "`backend/.env` hält den Schlüssel, der jede gespeicherte Zugangsinformation entpackt"

    `VAULT_MASTER_KEY` ist das, was die Provider-Keys, Bot-Token und
    MCP-Zugangsdaten einer Organisation lesbar macht. Ihn zu verlieren sperrt Sie
    nicht aus dem Produkt aus; es macht jedes Secret darin unwiederbringlich. Sichern
    Sie die Datei an einem Ort, den eine verlorene Festplatte nicht mitnimmt, und
    rotieren Sie mit [`agenticos cmd vault-rotate`](secrets.md#operations) statt
    durch Editieren.

Zwei optionale Dinge, nach denen es nicht fragt, beide in dieser Datei: `SMTP_*`,
ohne das sich Einladungen und Passwort-Resets nicht versenden lassen, und
`LOGFIRE_TOKEN`, wohin die Traces der Agent-Runs gehen.

## Einen Reverse Proxy wählen { #choose-a-reverse-proxy }

Irgendetwas muss TLS terminieren und die beiden Namen routen. Beide Optionen
unten erreichen dieselben Container; wählen Sie danach, ob Sie bereits einen
betreiben.

### Option A: Traefik { #option-a-traefik }

Der kürzere Weg, und der, den man auf einem Host mit bereits vorhandenem Traefik
wählt: die Container tragen Labels, Traefik entdeckt sie, fordert das Zertifikat
an und erneuert es. Nichts neu zu laden und keine zweite Konfigurationsdatei, die
im Gleichschritt bleiben muss.

Ist Traefik noch nicht vorhanden, liefert das Repository einen mit:
`traefik/traefik.yml` und `docker-compose-traefik.yml`, das ist ein Entrypoint auf
443 mit einem Let's-Encrypt-Resolver und 80, das dorthin umleitet.

```bash
docker network create traefik_webgateway
docker compose --env-file backend/.env -f docker-compose-traefik.yml up -d
```

Wo Traefik **bereits** läuft, lassen Sie diese Dateien in Ruhe und zeigen mit
`TRAEFIK_NETWORK` auf das Netzwerk, das er beobachtet. Die Overlays lesen diesen
Namen, am bestehenden Proxy muss sich also nichts ändern.

Bringen Sie den Stack dann mit `PROXY=traefik` hoch, was die beiden
Overlay-Dateien hinzufügt, die die Labels tragen:

```bash
make prod PROXY=traefik
make prod-frontend PROXY=traefik
```

`server-init.sh` hat `PROXY=traefik` bereits in `backend/.env` geschrieben, und
von dort liest `scripts/deploy.sh` es — spätere Deploys behalten also den Proxy
bei, mit dem dieser Host eingerichtet wurde, und nicht den, den ein Skript
annahm.

!!! info "`exposedByDefault: false` leistet echte Arbeit"

    Es ist die eine Einstellung in `traefik/traefik.yml`, die es sich zu lesen lohnt,
    bevor Sie ihn betreiben. Nur `app` und `frontend` tragen `traefik.enable=true`,
    also sind Postgres, Redis, der Prefect-Server und der Sandbox-Daemon von nichts
    außerhalb des Hosts erreichbar — und das ist eine Eigenschaft davon, *nicht
    gelabelt zu sein*, sie überlebt also, dass jemand einen Dienst hinzufügt, ohne an
    den Proxy zu denken.

### Option B: Nginx { #option-b-nginx }

Für einen Host, auf dem Nginx bereits TLS terminiert, oder auf dem der Proxy gar
nicht in Docker läuft. Der Stack veröffentlicht beide Ports auf `127.0.0.1`, und
Nginx erreicht sie dort:

```bash
make prod
make prod-frontend
```

`nginx/nginx.conf` ist die Vorlage. Zwei Ersetzungen, bevor sie irgendetwas
ausliefert: der `server_name` in jedem Block ist `${DOMAIN:-localhost}`, und
Nginx expandiert das nicht — tragen Sie die beiden Hostnamen von Hand ein.
Zertifikate zu beschaffen und zu erneuern ist Ihre Sache, und ebenso der Header
`Strict-Transport-Security`, den das Backend bewusst dem überlässt, was TLS
terminiert.

!!! warning "`BIND_HOST` ist eine Sicherheitseinstellung, keine Bequemlichkeit"

    Der Loopback-Standard ist das, was das Auth-Rate-Limit überhaupt bedeutsam macht.
    `RATE_LIMIT_TRUST_FORWARDED_FOR` weist die API an, einen Versuch der Adresse
    anzurechnen, die der Proxy weiterreicht — was immer die API also *am* Proxy
    *vorbei* erreichen kann, wählt die Adresse, der seine Versuche angerechnet
    werden. Setzen Sie `BIND_HOST=0.0.0.0` nur für einen Proxy auf einer anderen
    Maschine, und schirmen Sie den Port per Firewall auf ihn ein.

!!! warning "Das Frontend ist ein eigenes Compose-Projekt"

    Compose benennt ein Projekt nach dem Verzeichnis, beide Stacks hießen also
    `agenticos` — und das Hochfahren des Frontends meldete dann die fünf
    Backend-Container als **Waisen**, mit Composes eigenem Vorschlag, das Kommando
    erneut mit `--remove-orphans` auszuführen. Diesem Rat zu folgen stoppt die API,
    die Datenbank, Redis und beide Prefect-Dienste. Die `make`-Targets und
    `scripts/deploy.sh` übergeben `-p agenticos-frontend`, die Warnung ist damit weg.
    Die Compose-Dateien legen auch keine Containernamen fest - jedes Projekt benennt
    seine eigenen, zwei Stacks auf einem Host können einander also nicht die
    Container wegnehmen, und `deploy.sh` wartet auf die Dienste `app` und `frontend`
    statt auf einen Namen. Ein Deployment, das älter ist als beide Korrekturen, wird
    bei seinem nächsten `up` unter den neuen Namen neu erstellt; von Hand muss nichts
    entfernt werden.

    Die beiden Projekte treffen sich weiterhin auf einem Netzwerk mit festem Namen -
    `agenticos_edge` in Produktion, `agenticos_backend` auf dem Dev-Server - weil das
    Frontend ihm als externem Netzwerk beitritt. Ein Host, auf dem **zwei**
    AgenticOS-Stacks laufen, setzt `AGENTICOS_EDGE_NETWORK` und
    `AGENTICOS_DATA_NETWORK` (oder `AGENTICOS_NETWORK`) in der `backend/.env` jedes
    Stacks unterschiedlich; sonst lösen `db`, `redis` und `app` beider Stacks auf
    einer Bridge auf, und eine Anfrage kann die Datenbank des Nachbarn erreichen.

## Starten und den ersten Zugang anlegen { #start-it-and-create-the-first-account }

`make prod` holt die Images, startet den Stack und führt die Migrationen aus -
letztere als `migrate`-Dienst, auf den die API wartet, ein `docker compose up -d`
von Hand auf denselben Dateien tut also dasselbe. Der erste Pull umfasst rund
2 GB; ein späterer sind die Layer, die sich geändert haben.

Legen Sie dann eine Organisation, einen Owner und einen funktionierenden Agent
an:

```bash
docker compose --env-file backend/.env -f docker-compose-prod.yml \
  exec -T app agenticos cmd bootstrap \
  --email you@example.com --password 'a real password' \
  --org 'Your Company' --provider anthropic --api-key sk-ant-...
```

Der Provider-Key an dieser Stelle ist das, worauf der Demo-Agent läuft. Ohne ihn
wird der Agent angelegt und kann nicht antworten; jeder andere Provider wird im
Produkt hinzugefügt, pro Organisation, aus dem Vault.

!!! tip "Prüfen Sie es von außen, nicht vom Host aus"

    ```bash
    curl -fsS https://api.example.com/api/v1/health
    curl -fsSo /dev/null -w '%{http_code}\n' https://app.example.com
    ```

    Ein Stack, der auf dem Host gesund und aus dem Internet unerreichbar ist, ist
    DNS, die Firewall oder das Zertifikat — drei Dinge, die ein Health Check
    innerhalb des Hosts nicht sehen kann.

Dann, einmal, von Hand: melden Sie sich an, laden Sie jemanden ein (was `SMTP_*`
nachweist) und schicken Sie dem Demo-Agent eine Nachricht (was den Provider-Key
und den WebSocket nachweist). Jedes davon übt einen Pfad aus, den hier sonst
nichts prüft.

!!! info "Die Security-Header kommen aus dem Backend, jeder Proxy ist damit abgedeckt"

    Eine Content-Security-Policy, `X-Frame-Options: DENY`,
    `X-Content-Type-Options: nosniff`, `Referrer-Policy` und `Permissions-Policy`
    werden auf jeder Antwort gesetzt — einschließlich der 500 für eine unbehandelte
    Exception, die außerhalb des Middleware-Stacks gebaut wird und sie sich selbst
    aufprägt. Nur die interaktive API-Dokumentation verzichtet auf die CSP, weil
    Swagger Assets lädt, die eine strenge Policy verbietet.

    **HSTS ist bewusst dem Proxy überlassen**, denn dort terminiert TLS. Ein Proxy,
    der eine eigene CSP setzt, sollte mindestens so streng sein wie diese.

### Die Sandbox einschalten { #turning-the-sandbox-on }

Der Dienst, der den Code eines Agents ausführt, liegt hinter einem
Compose-Profil, denn er ist der eine Container, der den Docker-Socket hält, und
den auf einem gemeinsam genutzten Host einzuhängen sollte eine Entscheidung sein
statt eine Voreinstellung. Drei Dinge, einmalig:

```bash
make sandbox-token                       # writes SANDBOXD_TOKEN to backend/.env
sudo mkdir -p /var/lib/agenticos/sandbox-workspaces
sudo chown 10001:10001 /var/lib/agenticos/sandbox-workspaces
```

Ein Deploy bringt sie dann hoch: `scripts/deploy.sh` übergibt `--profile sandbox`,
wenn `SANDBOXD_TOKEN` in `backend/.env` einen Wert hat, der Host selbst sagt also,
ob er eine betreibt. Es exportiert außerdem `DOCKER_GID`, vom Socket gelesen —
jede Compose-Datei hier interpoliert es in das `group_add` der Sandbox, und sein
Standardwert `0` ist auf so gut wie keiner Linux-Distribution der Eigentümer des
Sockets. Sonst wird nichts in `.env` gebraucht: das Backend erreicht den Daemon
über eine Sandbox-*Connection*, die jemand in der Konsole anlegt, und
`http://sandboxd:8080` wird als die eigene dieses Deployments erkannt.

!!! warning "Ein Profil, von dem Compose nichts weiß, ist ein Dienst, den Compose stoppt"

    Ein `up -d` auf demselben Projekt ohne `--profile sandbox` lässt die Sandbox nicht
    in Ruhe — es stoppt sie. Einem Host, der sie von Hand gestartet hatte, wurde sie
    also vom nächsten Deploy weggenommen, wobei die Codeausführung eines Agents aus
    Gründen fehlschlug, die weit weg vom auslösenden Deploy lagen (#1506). Deshalb
    liest das Skript den Token, statt ein Flag entgegenzunehmen.

## Eine Änderung deployen { #deploying-a-change }

### Von Hand { #by-hand }

```bash
remote=$(ssh you@your-host 'mktemp -t agenticos-deploy.XXXXXX')
ssh you@your-host "cat > $remote" < scripts/deploy.sh
ssh you@your-host "trap 'rm -f $remote' EXIT; bash $remote <commit-sha>"
```

`scripts/deploy.sh` holt diesen Commit, wartet auf die Images, die die CI dafür
veröffentlicht hat (`sha-<short>`, meist schon da), holt sie, startet neu und
wartet darauf, dass beide Container sich als gesund melden, bevor es mit einem
Wert ungleich null zurückkehrt oder eben nicht. Es nimmt einen **Commit** statt
eines Branches entgegen, das Deployte ist also das Geprüfte und nicht das, wohin
`main` seither gewandert ist - und was läuft, ist Byte für Byte das, was die CI
gebaut hat, auf einem Host, der die Toolchain nie braucht.

!!! warning "Kopieren Sie es auf den Host und führen Sie es dann aus — leiten Sie es nicht in `bash -s`"

    Unter `bash -s` ist das Skript die Standardeingabe der Shell selbst, und das erste
    Kommando darin, das stdin liest, verbraucht den Rest. `docker compose exec`
    reicht stdin auch mit `-T` an den Container weiter, die Migration hat also alles
    unter sich aufgefressen, bash erreichte EOF, und der Deploy endete mit **0**,
    ohne jemals das Frontend gebaut oder auf irgendeinen Container gewartet zu haben.
    Die Website war unten und der Deploy war grün
    ([#1488](https://github.com/vstorm-co/agenticos/issues/1488)).

    Zwei Verbindungen statt einer sind das, was der Prozedur die Fähigkeit nimmt,
    sich selbst abzuschneiden.

Es ist nicht ausfallfrei. Compose erstellt die Container neu, deren Image sich
geändert hat, die Website ist also für die wenigen Sekunden, die das dauert,
nicht verfügbar.

### Aus GitHub, mit einer Freigabe { #from-github-with-an-approval }

`.github/workflows/deploy.yml` bietet jeden Merge auf `main` zum Deployment an
und wartet darauf, dass jemand ihn freigibt. Dieses Tor ist **eine
Repository-Einstellung, kein Schritt in der Datei** — ohne es deployt der
Workflow jeden Merge unbeaufsichtigt.

Einmal einrichten:

1. **Settings → Environments → New environment**, benannt `production`.
2. **Required reviewers** ankreuzen und hinzufügen, wer freigeben darf. Das ist
   das Tor.
3. Die Variablen der Environment hinzufügen: `SITE_URL`, `API_URL` und `APP_DIR`,
   falls der Checkout nicht unter `/opt/agenticos` liegt.
4. Die Secrets unten hinzufügen.

!!! warning "Brechen Sie einen Deploy ab, den Sie nicht freigeben wollen"

    Jeder Lauf teilt sich die Concurrency-Gruppe `deploy-production`, und ein Lauf,
    der am Freigabe-Tor sitzt, hält sie. Er läuft nicht von selbst ab — GitHub bricht
    einen unbearbeiteten nach 30 Tagen ab — bis also jemand ihn freigibt oder
    abbricht, stauen sich spätere Merges hinter einer Entscheidung, die niemand
    treffen wird, und der Server betreibt weiter das, was zuletzt deployt wurde.

    Ein Deploy, gegen den Sie sich entschieden haben, wird also abgebrochen und nicht
    stehen gelassen. Einer, der auf einem überholten Commit wartete, hat hier drei
    spätere Läufe blockiert, bevor jemand die Warteschlange statt der Läufe bemerkte.

| Secret | Was |
|---|---|
| `DEPLOY_HOST` | Die Adresse des Hosts |
| `DEPLOY_USER` | Das Konto, dem der Checkout gehört |
| `DEPLOY_SSH_KEY` | Ein privater Schlüssel, dessen öffentliche Hälfte in den `authorized_keys` dieses Kontos liegt |
| `DEPLOY_KNOWN_HOSTS` | `ssh-keyscan your-host`, ausgeführt von einem Ort, dem Sie vertrauen |

Erzeugen Sie den Schlüssel dafür und für nichts sonst:

```bash
ssh-keygen -t ed25519 -N '' -C 'github-actions-deploy' -f deploy_key
ssh-copy-id -f -i deploy_key.pub you@your-host
ssh-keyscan your-host                    # → DEPLOY_KNOWN_HOSTS
cat deploy_key                           # → DEPLOY_SSH_KEY, then delete it locally
```

!!! note "Der Host-Key ist ein Secret und kein `ssh-keyscan` zur Deploy-Zeit"

    Zur Deploy-Zeit zu scannen vertraut allem, was unter dieser Adresse antwortet, und
    genau das ist es, was ein Host-Key verhindern soll. Scannen Sie einmal, von einem
    Ort, dem Sie vertrauen, und speichern Sie die Antwort.

Es erscheint dann ein Lauf mit **Review deployments**; ihn freizugeben startet den
Job. `workflow_dispatch` führt denselben Job gegen eine von Ihnen benannte Ref
aus, so wird ein Rollback gemacht, und er durchläuft dieselbe Freigabe.

## Backups { #backups }

Ein Volume zählt, und welches, ist nicht offensichtlich:

| Volume | Enthält | Backup |
|---|---|---|
| `postgres_data` | alles — Agents, Unterhaltungen, versiegelte Zugangsdaten | **ja** |
| `media_data` | hochgeladene Dateien, vor der Ingestion | ja |
| `redis_data` | Rate-Limit-Buckets und Caches | nein, alles wiederherstellbar |
| `prefect_data` | die Historie der Flow-Runs | nein |

```bash
docker compose --env-file backend/.env -f docker-compose-prod.yml exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "agenticos-$(date +%F).dump"
```

Die Bezeichner kommen aus der Umgebung des Containers selbst, statt
ausgeschrieben zu werden, denn beide sind Einstellungen: ein Deployment, das eine
davon geändert hat, bekäme sonst eine leere Datei und einen Fehler, den im
Vorbeigehen niemand liest.

!!! danger "Ein Datenbank-Backup ohne `backend/.env` ist kein Backup"

    Die Zugangsdaten darin sind mit `VAULT_MASTER_KEY` versiegelt. Neben einem anderen
    Schlüssel wiederhergestellt, ist jeder Provider-Key, jeder Bot-Token und jede
    MCP-Zugangsinformation im Dump unlesbar — und das Produkt wird Ihnen das eine
    Ablehnung nach der anderen mitteilen.

## Zurückrollen { #rolling-back }

| | Wie |
|---|---|
| **Code** | Den vorherigen Commit deployen: `workflow_dispatch` mit seinem SHA, oder `scripts/deploy.sh`. Die Images liegen noch in der Registry, das ist also ein Pull und kein Build. Ein Commit ohne `sha-<short>`-Images - älter als `images.yml`, oder sein Lauf ging verloren - wird zuerst mit `gh workflow run images.yml --ref main -f sha=<commit>` veröffentlicht; der Deploy nennt dieses Kommando, wenn er das Warten aufgibt |
| **Schema** | `agenticos db downgrade --revision=-1`, dann den passenden Code deployen |
| **Daten** | Den Dump per `pg_restore` einspielen, dann die Migration prüfen, die der Code erwartet |

Code **über eine Migration hinweg** zurückzurollen **ist eine Entscheidung, kein
Kommando**. Der alte Code trifft auf ein Schema, das er nie gesehen hat; ob das
funktioniert, hängt von der Migration ab. Lesen Sie sie, bevor Sie etwas
annehmen.

## Zusammenfassung { #recap }

- **Ein Host, Compose, ein Proxy davor.** Sieben Container - einer davon führt
  die Migrationen aus und beendet sich - zwei davon zustandsbehaftet, jeder
  einzelne geholt - auf dem Host wird nichts gebaut. Pinnen Sie
  `AGENTICOS_VERSION`.
- **`UVICORN_WORKERS` entscheidet, was der Host kostet.** 460 MiB pro Worker,
  nichts geteilt. Zwei für ein Team, vier für echten Verkehr.
- **DNS vor allem anderen.** Es wird kein Zertifikat ausgestellt, bis die Namen
  auf den Host auflösen.
- **Die Freigabe ist eine Repository-Einstellung**, keine Zeile im Workflow. Ohne
  Required Reviewers auf der Environment `production` deployt sich jeder Merge
  selbst.
- **Sichern Sie `postgres_data` und `backend/.env` zusammen.** Das eine ohne das
  andere ist keine Wiederherstellung.
