---
source_sha: "2d65da37dcb6"
---

# Der Benchmark der Hintergrund-Jobs { #the-background-job-benchmark }

Bis 1.9.0 lief jeder Hintergrund-Job in AgenticOS auf Prefect, das für jeden Run
einen neuen Python-Prozess startete. Am 18. Oktober 2026 stauten sich rund 1.650
verspätete Runs auf einem Host, der ohnehin CPU durch Steal verlor, und die
Website fiel aus. Bevor wir Prefect ersetzten, haben wir zehn Engines in siebzehn
Konfigurationen durch dieselben Lasten geschickt und gleich gemessen. Diese Seite
beschreibt, was gemessen wurde, was die Wahl entschied und was die Zahlen nicht
zeigen. Der Harness ist `experiments/task-queues` auf dem Branch
`spike/task-queue-benchmark` im Commit `a239dfdd7`; dort liegen auch die
Rohereignisse jedes Laufs.

## Was verglichen wurde { #what-was-compared }

| Variante | Engine | Wie sie Arbeit ausführt |
|---|---|---|
| `prefect-serve` | Prefect 3 `serve`, Limit 5; auch mit Limit 20 und mit Prefects Datenbank auf Postgres getestet | Ein neuer Python-Prozess pro Run: AgenticOS vor 1.9.0 |
| `prefect-tasks` | Prefects Hintergrund-Tasks | Ein langlebiger Task-Worker |
| `celery-prefork`, `celery-threads` | Celery 5.6 und Beat, auf Redis | Ein Pool aus Prozessen oder aus Threads |
| `taskiq` | Taskiq auf Redis Streams, mit eigenem Scheduler | Asynchron, eine Event-Loop pro Prozess |
| `dramatiq` | Dramatiq auf Redis | Prozesse mal Threads |
| `saq` | SAQ auf Redis | Asynchron, eine Event-Loop pro Prozess |
| `procrastinate` | Procrastinate 3.10 auf Postgres | Asynchron, eine Event-Loop |
| `pgqueuer` | PgQueuer 1.6.0 auf Postgres | Asynchron, eine Event-Loop |
| `dbos`, `dbos-poll100` | DBOS 3.3.0 auf Postgres; `-poll100` fragt alle 0,1 s statt jede Sekunde ab | Dauerhafte Workflows |
| `hatchet`, `hatchet-fair` | Hatchet Lite auf Postgres; `-fair` wechselt zwischen Organisationen | Asynchrone Worker-Slots |
| `pgqueue`, `pgqueue-fair` | Eine einfache Warteschlange in Postgres: `SKIP LOCKED`, `LISTEN/NOTIFY`, Leases | Asynchrone Slots; `-fair` holt der Reihe nach aus jeder Organisation |

Jeder Task-Prozess importiert zuerst die echte AgenticOS-Anwendung. Diesen Import
bezahlte Prefect bei jedem Run, ein Benchmark ohne ihn würde also genau die
untersuchten Kosten verstecken. Die Worker bekamen 3 CPUs und 4 GB, den Anteil
des Produktions-Hosts für Hintergrundarbeit. Ein Dienst, den eine Engine
mitbringt, etwa Prefects Server oder Hatchets Engine, bekam eigene Limits, und
seine CPU und sein Speicher zählen zu den Kosten dieser Engine.

## Die Szenarien { #the-scenarios }

- **`workflow`**: 50 Runs aus je 10 aufeinanderfolgenden leichten Schritten,
  gleichzeitig gestartet. Jeder Schritt macht einen Datenbank-Roundtrip und reiht
  den nächsten ein. Gemessen wird der Overhead der Engine pro Sprung.
- **`mix`**: 5 Minuten Modellaufrufe (2 pro Sekunde, jeder wartet 2 bis 10 s) und
  PDF-Parsing (eines alle 2 s, je etwa 1 s CPU), dazu der eigene minütliche Sweep
  der Engine. Gemessen wird, wie wartende Arbeit und CPU-Arbeit sich die Worker
  teilen und wie pünktlich der Zeitplan ist.
- **`tenants`**: Eine Organisation reiht 1.000 Jobs auf einmal ein, eine andere
  schickt 90 s lang einen Job pro Sekunde. Nach 20 s wird jeder Worker beendet
  und 10 s später neu gestartet. Gemessen werden Fairness und die Kosten eines
  Absturzes.
- **`oom`**: Ein Job vergrößert seinen Speicher, bis der Kernel seinen Worker bei
  1 GB beendet, während daneben 210 normale Jobs laufen. Ein toter Worker startet
  nach 3 s neu, der Lauf wird 240 s beobachtet, und jede Engine mit einem
  Wiederholungslimit steht auf 3 Versuchen.

Jeder Task schreibt eine Zeile `started` und eine Zeile `finished`, der
Einreichende eine Zeile `enqueued`, in eine Postgres-Tabelle mit einer Uhr.
Wartezeiten, Lücken zwischen Schritten sowie verlorene und doppelte Jobs ergeben
sich aus diesen Zeilen. Der Driver liest `docker stats` einmal pro Sekunde und den
WAL-Zähler von Postgres vor und nach dem Lauf.

## Overhead pro Schritt { #overhead-per-step }

| Variante | Sprung p50 | Sprung p95 | Schritte pro Sekunde | Spitzenspeicher der Worker |
|---|---|---|---|---|
| `taskiq` | 0,01 s | 0,02 s | 948 | 184 MB |
| `saq` | 0,01 s | 0,05 s | 818 | 564 MB |
| `dramatiq` | 0,02 s | 0,05 s | 1.338 | 583 MB |
| `pgqueue` | 0,03 s | 0,06 s | 506 | 288 MB |
| `pgqueuer` | 0,03 s | 0,08 s | 609 | 584 MB |
| `procrastinate` | 0,05 s | 0,06 s | 829 | 294 MB |
| `celery-prefork` | 0,05 s | 0,13 s | 485 | 1.294 MB |
| `hatchet` | 0,42 s | 0,82 s | 92 | 642 MB |
| `dbos-poll100` | 0,56 s | 1,11 s | 71 | 601 MB |
| `dbos` | 2,51 s | 3,12 s | 19 | 1.488 MB |
| `prefect-tasks` | 2,60 s | 6,82 s | 11 | 861 MB |
| `prefect-serve` | 218 s | 246 s | 0,2 | 1.736 MB |

`prefect-serve` wurde nicht fertig: Nach 20 Minuten hatte es 273 der 500 Schritte
erledigt. Mit einem Limit von 20 Prozessen erledigte es keinen, weil 20 Kopien
der Anwendung nicht in 4 GB passten. Ab `dbos-poll100` abwärts fügt jede Engine
jedem Schritt eines Workflows mindestens eine halbe Sekunde hinzu.

## Wartende Arbeit neben CPU-Arbeit { #waiting-work-beside-cpu-work }

| Variante | Wartezeit eines Modellaufrufs p50 | Wartezeit eines Modellaufrufs p95 | Spätester Start des Sweeps |
|---|---|---|---|
| `taskiq` | 0,00 s | 0,01 s | 0,0 s |
| `pgqueue` | 0,01 s | 0,57 s | 0,0 s |
| `pgqueuer` | 0,01 s | 0,41 s | 0,6 s |
| `celery-threads` | 0,01 s | 0,04 s | 0,0 s |
| `hatchet` | 0,01 s | 0,27 s | 1,0 s |
| `procrastinate` | 0,01 s | 0,61 s | 29,4 s |
| `dbos` | 0,60 s | 1,48 s | 3,7 s |
| `prefect-tasks` | 0,10 s | 2,15 s | Kein Sweep lief |
| `celery-prefork` | 148 s | 279 s | 63,1 s |

Ein Modellaufruf wartet fast die ganze Zeit. Eine Engine, die für jeden Aufruf
einen ganzen Prozess belegt, reiht die nächsten dahinter ein: Unter
`celery-prefork` warteten Aufrufe mehr als zwei Minuten. Postgres selbst
verbrauchte unter `pgqueue`, `pgqueuer` und `dbos` 3 bis 6 % einer CPU. DBOS
schrieb 2,3-mal so viel WAL wie `pgqueue` (4,4 MB gegenüber 1,9 MB), weil jeder
seiner Workflows mehrere Zeilen für Status und Schritte ist.

## Eine Flut und ein Absturz { #a-flood-and-a-crash }

| Variante | Verloren | Doppelt | Wartezeit der kleinen Organisation p95 | Längster Stillstand |
|---|---|---|---|---|
| `pgqueue` | 0 | 0 | 11,1 s | 17,5 s |
| `pgqueuer` | 0 | 0 | 11,0 s | 16,8 s |
| `taskiq` | 0 | 0 | 12,0 s | 17,5 s |
| `procrastinate` | 0 | 0 | 14,0 s | 20,4 s |
| `dbos-poll100` | 0 | 0 | 14,1 s | 18,3 s |
| `hatchet-fair` | 0 | 0 | 18,3 s | 24,0 s |
| `dbos` | 0 | 0 | 64,8 s | 18,8 s |
| `celery-prefork` | 0 | 0 | 50,3 s | 39,5 s |
| `saq` | 0 | 0 | 10,0 s | 551,5 s |
| `pgqueue-fair` | 0 | 137 | 10,1 s | 15,4 s |

Keine Engine in der Tabelle hat einen Job verloren; `prefect-tasks` hatte noch
zwei unerledigte Jobs, als sein Lauf das Zeitlimit erreichte. Die meisten Engines
führten einen Job ein zweites Mal aus: den, den ein beendeter Worker gehalten
hatte. Das muss jede Warteschlange tun, die den Job eines toten Workers
zurückgibt. Der Prototyp `pgqueue-fair` erledigte 137 Jobs doppelt. Sein Abholen
der Reihe nach ist nicht ausgeliefert worden, und die Duplikate sind der Grund.
SAQ ließ die Jobs der beendeten Worker mehr als neun Minuten liegen, bevor es sie
zurückholte.

## Der Job, der seinen Worker beendet { #the-job-that-kills-its-worker }

Dieses Szenario hat die Wahl entschieden. Bei einem früheren Produktionsvorfall,
in einem anderen Projekt auf Celery, startete ein vom OOM-Killer beendeter Job
immer wieder, und sein Fehler wurde nie festgehalten. Die neue Warteschlange
durfte keins von beidem tun.

| Variante | Starts des Jobs in 240 s | Was passierte | Normale Jobs |
|---|---|---|---|
| `pgqueue` | 3 | Nach dem dritten Versuch als `dead` markiert, den Fehler hielt der Sweeper fest | Alle erledigt |
| `dbos` | 3 | `MAX_RECOVERY_ATTEMPTS_EXCEEDED`, festgehalten vom neu gestarteten Prozess | Alle erledigt |
| `procrastinate` | 4 | Startete jede Minute neu; das dokumentierte Rezept für hängende Jobs zählt Versuche, begrenzt aber nichts | Alle erledigt |
| `taskiq` | 5 | Startete alle 60 s neu; der Container starb nie, weil sein Prozessmanager das Kind neu startet, also war von außen nichts zu sehen | Alle erledigt |
| `pgqueuer` | 8 | Jedes Mal neu abgeholt, wenn sein Heartbeat ablief, ohne einen Versuch zu zählen; 7 Worker beendet | Alle erledigt |

DBOS hielt ebenfalls bei 3 an, aber eine zweite Probe fand das andere verbotene
Ergebnis. Als ein Worker mit drei Jobs starb und als neuer Container zurückkam,
wie bei jedem Deploy, waren alle drei 120 s später noch `PENDING` unter der ID
des alten Executors. Der neue Prozess sieht sie nicht. DBOS Conductor erkennt
einen toten Executor, ist für kommerzielles Self-Hosting aber separat lizenziert.
Celery lief nicht durch dieses Szenario. Seine Dokumentation beschreibt beide
Fehler: Eine Nachricht kommt ohne Zustelllimit zurück, oder der Job geht still
verloren.

## Was ausgeliefert wurde { #what-shipped }

1.9.0 ersetzte Prefect durch die einfache Warteschlange in Postgres (`pgqueue`)
und langlebige asyncio-Worker. Sie zählt einen Versuch, wenn ein Job abgeholt
wird, nicht wenn er endet. Jeder Worker führt außerdem einen Rescuer aus: Stirbt einer,
findet der nächste Rescuer - in einem überlebenden Worker oder im neu gestarteten
selbst - seinen abgelaufenen Lease und hält den Tod fest, egal wie der Worker
gestorben ist. Oban, River und Solid
Queue folgen derselben Regel.

Die Ingestion läuft außerdem in Kindprozessen unter
einer Speicherüberwachung, damit ein schweres Dokument seinen Worker nicht
mitreißt. [Hintergrundarbeit aus einem Request
übergeben](architecture.md#dispatching-background-work-from-a-request) zeigt, wie
Code einen Job einreiht, und [Über einen Host
hinaus](scaling.md#more-workers), wie man Worker hinzufügt.

Die Fairness zwischen Organisationen bleibt, wie sie gemessen wurde. Die einfache
Warteschlange gab der kleinen Organisation fast dasselbe p95 wie der Prototyp mit
Abholen der Reihe nach (11,1 s gegenüber 10,1 s), ohne seine Duplikate.

## Was die Zahlen nicht sagen { #what-the-numbers-do-not-say }

- **Eine Maschine.** Alle Läufe fanden auf Docker Desktop auf Apple Silicon statt.
  Auf einem Server sind die absoluten Zahlen andere. CPU-Steal auf einem
  geteilten Host verlangsamt jeden Prozessstart, was den Abstand für einen Prozess
  pro Run nur vergrößert.
- **Ein Lauf pro Zelle.** Die Abstände zwischen den Engines sind groß genug, um sie
  mit einem Lauf zu ordnen. Wo zwei Engines nah beieinander liegen, wie `pgqueue`
  und `pgqueuer` beim Overhead, sagen die Tabellen nicht, dass eine schneller ist.
- **Jede Engine in ihrer üblichen Konfiguration.** Jede Engine hatte dasselbe
  Budget an CPU und Speicher, nicht dieselbe Nebenläufigkeit, weil ein
  Prozess-Pool und eine Event-Loop keine gemeinsame Einheit haben. Eine andere
  Einstellung kann eine Zahl ändern, besonders im OOM-Test.
- **Ein korrigierter Fehler im Harness.** Der erste `tenants`-Lauf von
  Procrastinate verlor einen Job, weil der Harness eine Methode aufrief, die 3.10
  nicht mehr hat. Das war unser Fehler, nicht der von Procrastinate. Der
  wiederholte Lauf in der Tabelle erledigte alle 1.090 Jobs.

## Erneut ausführen { #run-it-again }

```bash
# Aus dem Wurzelverzeichnis des Repositorys, im gemessenen Commit.
git switch --detach a239dfdd7
docker build -f backend/Dockerfile -t agenticos-backend:bench-base .
cd experiments/task-queues
docker build -t tqbench:latest .
./run.sh pgqueue oom          # eine Variante, ein Szenario, in einem frischen Projekt
./matrix.sh                   # jede Zelle; ein paar Stunden
python3 -m bench.report results > results/TABLES.md
```

Die [Lasttests](load-testing.md) beantworten eine andere Frage: wie viel ein
Deployment von AgenticOS bedienen kann, nicht welche Engine seine Jobs ausführen
sollte.
