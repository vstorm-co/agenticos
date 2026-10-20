---
source_sha: "0dc46f479226"
---

# Über einen Host hinaus skalieren { #scale-beyond-one-host }

Der ausgelieferte Weg ist [ein Host mit Docker Compose](deploy.md). Diese Seite
beschreibt den Schritt danach: ein verwaltetes Postgres, mehrere API-Hosts,
eigene Worker oder mehrere Deployments nebeneinander. Sie sagt, was jeder Teil
braucht, wenn er umzieht, und was die Plattform noch nicht kann, damit ein Plan
auf dem aufbaut, was läuft.

Zuerst messen. Ein Host in der [empfohlenen Größe](deploy.md#sizing-the-host)
trägt ein Team von einigen Dutzend Leuten, und die meiste Langsamkeit auf einem
kleinen Host ist CPU-Steal oder ein zu kleiner Pool, nicht eine fehlende
Replika. Die [Lasttests](load-testing.md) führen dieselbe Last gegen jedes
Deployment aus.

## Was Zustand hält und was nicht { #what-holds-state-and-what-does-not }

| Teil | Was er hält | Wie er wächst |
|---|---|---|
| API (`app`) | Nichts Eigenes. Sitzungen, Anwesenheit, laufende Chat-Turns und der Live-Update-Feed liegen in Postgres und Redis | Mehr uvicorn-Worker, dann mehr Hosts hinter einem Load Balancer |
| Worker | Nichts. Jobs, Leases und Zeitpläne sind Zeilen in Postgres | Mehr Prozesse, auf beliebigen Hosts, mit den Pools auf sie verteilt |
| Konsole (`frontend`) | Das Branding, das sie fünf Minuten lang cacht | Mehr Instanzen |
| Postgres | Alles Dauerhafte: Organisationen, Agenten, Unterhaltungen, Vektoren, die Job-Warteschlange | Eine größere Instanz oder eine verwaltete |
| Redis (Valkey) | Ein Cache und seine Pub/Sub-Kanäle, nach einem Neustart neu aufgebaut | Eine Instanz, die sich alle Hosts teilen |
| Hochgeladene Dateien | Ein Volume auf dem Host oder ein Bucket | Ein Bucket, sobald mehr als ein Host sie liest oder schreibt |
| Sandbox-Dienst | Die Sandboxes, in denen Agenten Befehle ausführen | Ein eigener Host, siehe [Agent-Arbeitsbereiche](configuration.md#running-the-service-on-another-host) |

## Eine Datenbank pro Deployment { #one-database-per-deployment }

Alle Organisationen eines Deployments teilen sich eine Postgres-Datenbank, und
jede Abfrage ist auf die Organisation eingeschränkt. Auch die Vektoren jeder
Wissensdatenbank liegen darin, über pgvector, ebenso die Job-Warteschlange.
`POSTGRES_DB` nennt die einzige Datenbank, die ein Deployment nutzt: Es gibt
keine eigene Vektordatenbank, keine Lese-Replika und kein Sharding nach
Organisation.

Mehrere Datenbanken bedeuten deshalb mehrere Deployments. Das ist die Antwort
für Daten, die in einer Region bleiben müssen, für eine Geschäftseinheit mit
eigenen Administratoren und für einen Mandanten, dessen Last die anderen nicht
erreichen soll. Jedes Deployment hat eigene Hostnamen, `SECRET_KEY` und
`VAULT_MASTER_KEY`, und zur Laufzeit wird zwischen ihnen nichts geteilt.

Infrastruktur können sie teilen. Zwei Deployments auf einem Postgres-Server
brauchen eigene Datenbanken (`POSTGRES_DB`), auf einem Redis eigene
`REDIS_DB`-Nummern, damit Rate-Limit-Buckets und gecachte Antworten getrennt
bleiben. Auch ein Bucket gehört zu genau einem Deployment. Ein Agent wechselt
als seine Spec zwischen ihnen: auf dem einen als YAML exportieren
(`GET /agents/{id}/spec.yaml`) und auf dem anderen in einen Agenten importieren.

## Ein externes Postgres { #an-external-postgres }

Ein verwaltetes oder selbst betriebenes Postgres funktioniert, wenn es Folgendes
hat:

- **PostgreSQL 16 mit pgvector.** Verwaltete Dienste führen es als Erweiterung
  `vector`. Die Plattform legt sie beim ersten Schreiben in eine Sammlung an,
  also braucht die verbindende Rolle `CREATE` auf der Datenbank, oder ein
  Administrator legt sie vorher an. Dasselbe gilt für `pg_stat_statements`, das
  eine Migration hinzufügt, wo sie darf, und mit einem Hinweis überspringt, wo
  nicht.
- **Eine verschlüsselte Verbindung** zu einer Datenbank auf einem anderen Host.
  Siehe [Verschlüsselte Verbindungen](configuration.md#encrypted-connections-tls):
  Das Override muss `app`, `migrate` und `worker` erreichen, weil die
  Compose-Dateien den Host in jedem davon festlegen.
- **Migrationen laufen einmal.** Der Dienst `migrate` wendet sie an, bevor die
  API startet. Bei mehreren Hosts aus einem Deployment ausführen, nicht aus
  jedem.

Nach einem Failover der verwalteten Datenbank scheitert in jedem Prozess die
erste Anfrage, die auf eine abgerissene Verbindung trifft, und der Pool verwirft
dann alle Verbindungen, die älter sind. Die Engines prüfen eine Verbindung vor
der Nutzung nicht, weil das jede Entnahme aus dem Pool einen Roundtrip kosten
würde.

### Verbindungen zählen { #counting-connections }

Zuerst `max_connections` bemessen, sonst weist Postgres Verbindungen mit „too many
clients“ ab, bevor ein Pool die Last einreihen oder abwerfen kann.

Jeder API-Prozess öffnet zwei Pools mit `DB_POOL_SIZE + DB_MAX_OVERFLOW`,
standardmäßig je 15: einen für Anfragen und einen für Vektorsuchen, die in einer
Anfrage laufen, die bereits eine Verbindung hält. Ein Worker-Prozess öffnet
dieselben zwei, dazu eine kurzlebige Verbindung je laufendem Job. Jedes
Ingest-Kind ist ein eigener Prozess, und der Job darin schreibt seine Vektoren
über eine eigene Engine mit dem Standard-Pool von 15, die beim Ende des Jobs
geschlossen wird. Wissenssuchen eines Agenten verbinden sich einmal pro Suche,
ohne Pool.

```text
max_connections ≥ API-Hosts × UVICORN_WORKERS × 30
                + Worker-Prozesse × 30
                + Ingest-Kinder × 15
                + Reserve für Migrationen und die Sitzung eines Administrators
```

Zwei API-Hosts mit je vier uvicorn-Workern und zwei Worker mit je einem
Ingest-Kind ergeben 330, also ist 400 eine sinnvolle Einstellung. Das sind
Obergrenzen: Ein ruhendes Deployment hält weit weniger. Die
Produktions-Compose-Datei setzt 200 für einen Host.

### PgBouncer { #pgbouncer }

Nur im Session-Modus. Transaction-Pooling bricht zwei Dinge, auf die sich die
Plattform verlässt: die Prepared Statements von asyncpg, die keine Einstellung
hier abschaltet, und den Advisory Lock auf Sitzungsebene, der verhindert, dass
eine Sync-Quelle zweimal gleichzeitig läuft. Der Session-Modus begrenzt die Zahl
der Server-Verbindungen, spart aber sonst wenig, daher ist es meist der bessere
Hebel, die Pools gegen `max_connections` zu bemessen.

## Mehr API-Hosts { #more-api-hosts }

Davor gehört ein Load Balancer, der WebSockets durchlässt: Live-Updates und
Chat der Konsole nutzen `/api/v1/ws/*`. Sticky Sessions sind nicht nötig. Wer
sich mit seinem Socket an einem anderen Host neu verbindet, folgt einem
laufenden Turn über Redis, und auch Anwesenheit und Rate Limits liegen dort.

Jeder Host braucht:

- **Dieselben Secrets.** `SECRET_KEY` signiert Tokens, die jeder Host prüfen
  muss, und `VAULT_MASTER_KEY` entschlüsselt jede gespeicherte Zugangsangabe.
- **Den Bucket.** Mit `FILE_STORAGE_BACKEND=local` liegt eine über einen Host
  hochgeladene Datei nicht auf dem anderen, und der Worker, der sie parst, sitzt
  vielleicht auf keinem von beiden. `s3` verwenden (siehe
  [Hochgeladene Dateien](configuration.md#uploaded-files-at-rest)).
- **Dasselbe Redis**, als eine Instanz oder ein Endpunkt vor einer primären
  Instanz. Der Client ist nicht clusterfähig, Redis Cluster wird also nicht
  unterstützt.
- **`RATE_LIMIT_TRUST_FORWARDED_FOR`**, sobald der Load Balancer der einzige Weg
  zu den Hosts ist, sonst teilen sich alle Besucher den Bucket des Balancers.

Ein Chat-Turn läuft in dem API-Prozess, der ihn angenommen hat, nicht in einem
Worker. Die API-Hosts tragen also die Chat-Last, und `UVICORN_WORKERS` wird
dafür bemessen wie [auf einem Host](deploy.md#sizing-the-host).

Mehrere Konsolen-Instanzen sind kein Problem. Das gecachte Branding gilt je
Instanz: Die Änderung eines Administrators erscheint sofort auf der Instanz,
die sie gespeichert hat, und auf den anderen innerhalb von fünf Minuten.

## Mehr Worker { #more-workers }

So viele Worker-Prozesse betreiben, wie die Arbeit braucht, auf beliebigen
Hosts. Sie holen Jobs mit `SKIP LOCKED`, also laufen nie zwei denselben Job, und
jeder von ihnen kann einen fälligen Zeitplan auslösen. Ein Worker, der stirbt,
gibt seine Jobs innerhalb von `WORKER_LEASE_SECONDS` zurück.

Die Pools trennen, wenn Parsen mit Agenten-Läufen konkurriert.
`WORKER_POOLS=agent,system` auf einer Gruppe von Prozessen und
`WORKER_POOLS=ingest` auf Hosts mit Speicherreserve verhindern, dass ein großer
Upload eine Routine verzögert. Die Health-Probe und `agenticos cmd doctor`
melden einen Pool, den kein lebender Worker bedient. Die Einstellungen unter
[Hintergrundarbeit](configuration.md#background-work) bemessen jeden Prozess.

## Redis { #redis }

Alle API-Hosts und Worker nutzen dasselbe Redis: Es trägt den Live-Update-Feed,
die Anwesenheit, laufende Turns und Rate Limits zwischen ihnen. Es ist ein
Cache, ein Neustart verliert also nichts Dauerhaftes. Live-Updates verbinden
sich neu, und wer einem laufenden Turn folgt, sieht die Antwort im Transkript,
sobald sie eintrifft, statt Frame für Frame.

## Messen, bevor Hosts dazukommen { #measure-before-you-add-hosts }

- **`agenticos cmd doctor`** sagt, welches Postgres und welches Redis jede
  Verbindung erreicht hat, ob sie verschlüsselt war und ob die Worker leben.
- **`pg_stat_statements`** zeigt, welche Statements die Datenbank am meisten
  kosten.
- **Logfire**, mit `LOGFIRE_ENVIRONMENT` je Deployment gesetzt, trennt die Traces
  eines Deployments von denen eines anderen (siehe
  [Observability](configuration.md#observability-logfire)).
- **Die [Lasttests](load-testing.md)**, vor und nach einer Änderung ausgeführt,
  sagen, ob sie geholfen hat.

## Was es noch nicht kann { #what-it-does-not-do-yet }

- Lese-Repliken oder eine eigene Vektordatenbank.
- Sharding von Organisationen über Datenbanken innerhalb eines Deployments.
- PgBouncer im Transaction-Modus oder Redis Cluster.
- Kubernetes-Manifeste. Die Images sind dieselben, die die Compose-Dateien
  ausführen, und jeder Dienst bringt seinen eigenen Health-Check mit, also
  betreibt ein Cluster sie mit der Umgebung, die diese Seite beschreibt.
