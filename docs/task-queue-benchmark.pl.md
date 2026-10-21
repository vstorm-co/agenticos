---
source_sha: "63c344022086"
---

# Benchmark zadań w tle { #the-background-job-benchmark }

Do wersji 1.9.0 każde zadanie w tle w AgenticOS działało na Prefekcie, który dla
każdego runu uruchamiał nowy proces Pythona. 18 października 2026 na hoście,
który już tracił CPU przez steal, zebrało się około 1650 spóźnionych runów i
strona przestała działać. Zanim zastąpiliśmy Prefecta, przepuściliśmy dziesięć
silników, w osiemnastu konfiguracjach, przez te same obciążenia, mierzone w ten
sam sposób. Ta strona opisuje, co zmierzyliśmy, co przesądziło o wyborze i czego
liczby nie pokazują. Harness to `experiments/task-queues` na gałęzi
`spike/task-queue-benchmark`; są tam też surowe zdarzenia każdego przebiegu.

## Co porównaliśmy { #what-was-compared }

| Wariant | Silnik | Jak wykonuje pracę |
|---|---|---|
| `prefect-serve` | Prefect 3 `serve`, limit 5; sprawdzony też z limitem 20 i z bazą Prefecta w Postgresie | Nowy proces Pythona na każdy run: AgenticOS przed 1.9.0 |
| `prefect-tasks` | Zadania w tle Prefecta | Długo żyjący worker zadań |
| `celery-prefork`, `celery-threads` | Celery 5.6 i Beat, na Redisie | Pula procesów albo wątków |
| `taskiq` | Taskiq na Redis Streams, z własnym schedulerem | Asynchronicznie, jedna pętla zdarzeń na proces |
| `dramatiq` | Dramatiq na Redisie | Procesy razy wątki |
| `saq` | SAQ na Redisie | Asynchronicznie, jedna pętla zdarzeń na proces |
| `procrastinate` | Procrastinate 3.10 na Postgresie | Asynchronicznie, jedna pętla zdarzeń |
| `pgqueuer` | PgQueuer 1.6.0 na Postgresie | Asynchronicznie, jedna pętla zdarzeń |
| `dbos`, `dbos-poll100` | DBOS 3.3.0 na Postgresie; `-poll100` odpytuje co 0,1 s zamiast co 1 s | Trwałe workflow |
| `hatchet`, `hatchet-fair` | Hatchet Lite na Postgresie; `-fair` rotuje między organizacjami | Asynchroniczne sloty workera |
| `pgqueue`, `pgqueue-fair` | Zwykła kolejka w Postgresie: `SKIP LOCKED`, `LISTEN/NOTIFY`, lease'y | Asynchroniczne sloty; `-fair` pobiera po kolei z każdej organizacji |

Każdy proces zadań najpierw importuje prawdziwą aplikację AgenticOS. Ten import
to koszt, który Prefect płacił przy każdym runie, więc benchmark bez niego
ukryłby właśnie badany koszt. Workery dostały 3 CPU i 4 GB, czyli tyle, ile na
pracę w tle ma host produkcyjny. Usługa, którą przynosi silnik, na przykład
serwer Prefecta albo silnik Hatcheta, dostała własne limity, a jej CPU i pamięć
liczą się do kosztu tego silnika.

## Scenariusze { #the-scenarios }

- **`workflow`**: 50 runów po 10 kolejnych lekkich kroków, uruchomionych naraz.
  Każdy krok robi jedno zapytanie do bazy i kolejkuje następny. Mierzy narzut
  silnika na jeden przeskok.
- **`mix`**: 5 minut wywołań modelu (2 na sekundę, każde czeka od 2 do 10 s) i
  parsowania PDF (jedno co 2 s, ok. 1 s CPU każde), do tego zaplanowany co minutę
  sweep samego silnika. Mierzy, jak praca czekająca i praca na CPU dzielą się
  workerami i jak regularny jest harmonogram.
- **`tenants`**: jedna organizacja kolejkuje naraz 1000 zadań, a druga wysyła
  jedno zadanie na sekundę przez 90 s. Po 20 s wszystkie workery są zabijane i
  startują ponownie 10 s później. Mierzy sprawiedliwość i koszt awarii.
- **`oom`**: jedno zadanie zwiększa pamięć, aż kernel zabije jego workera przy
  1 GB, a obok działa 210 zwykłych zadań. Martwy worker wstaje po 3 s, przebieg
  jest obserwowany przez 240 s, a każdy silnik z limitem ponowień ma ustawione 3
  próby.

Każde zadanie zapisuje wiersz `started` i `finished`, a zlecający wiersz
`enqueued`, do jednej tabeli w Postgresie, według jednego zegara. Czasy
oczekiwania, przerwy między krokami oraz zgubione i zdublowane zadania wynikają
z tych wierszy. Driver co sekundę próbkuje `docker stats` i odczytuje licznik
WAL Postgresa przed przebiegiem i po nim.

## Narzut na krok { #overhead-per-step }

| Wariant | Przeskok p50 | Przeskok p95 | Kroki na sekundę | Szczyt pamięci workerów |
|---|---|---|---|---|
| `taskiq` | 0,01 s | 0,02 s | 948 | 184 MB |
| `saq` | 0,01 s | 0,05 s | 818 | 564 MB |
| `dramatiq` | 0,02 s | 0,05 s | 1338 | 583 MB |
| `pgqueue` | 0,03 s | 0,06 s | 506 | 288 MB |
| `pgqueuer` | 0,03 s | 0,08 s | 609 | 584 MB |
| `procrastinate` | 0,05 s | 0,06 s | 829 | 294 MB |
| `celery-prefork` | 0,05 s | 0,13 s | 485 | 1294 MB |
| `hatchet` | 0,42 s | 0,82 s | 92 | 642 MB |
| `dbos-poll100` | 0,56 s | 1,11 s | 71 | 601 MB |
| `dbos` | 2,51 s | 3,12 s | 19 | 1488 MB |
| `prefect-tasks` | 2,60 s | 6,82 s | 11 | 861 MB |
| `prefect-serve` | 218 s | 246 s | 0,2 | 1736 MB |

`prefect-serve` nie skończył: po 20 minutach miał 273 z 500 kroków. Z limitem
podniesionym do 20 procesów nie skończył żadnego, bo 20 kopii aplikacji nie
zmieściło się w 4 GB. Od `dbos-poll100` w dół każdy silnik dokłada co najmniej
pół sekundy do każdego kroku workflow.

## Praca czekająca obok pracy na CPU { #waiting-work-beside-cpu-work }

| Wariant | Czekanie wywołania modelu p50 | Czekanie wywołania modelu p95 | Najpóźniejszy start sweepu |
|---|---|---|---|
| `taskiq` | 0,00 s | 0,01 s | 0,0 s |
| `pgqueue` | 0,01 s | 0,57 s | 0,0 s |
| `pgqueuer` | 0,01 s | 0,41 s | 0,6 s |
| `celery-threads` | 0,01 s | 0,04 s | 0,0 s |
| `hatchet` | 0,01 s | 0,27 s | 1,0 s |
| `procrastinate` | 0,01 s | 0,61 s | 29,4 s |
| `dbos` | 0,60 s | 1,48 s | 3,7 s |
| `prefect-tasks` | 0,10 s | 2,15 s | Sweep się nie uruchomił |
| `celery-prefork` | 148 s | 279 s | 63,1 s |

Wywołanie modelu prawie cały czas czeka, więc silnik, który na każde wywołanie
zajmuje cały proces, ustawia kolejne w kolejce za nim: przy `celery-prefork`
wywołania czekały ponad dwie minuty. Sam Postgres zużywał 3 do 6% jednego CPU
przy `pgqueue`, `pgqueuer` i `dbos`. DBOS zapisał 2,3 raza więcej WAL niż
`pgqueue` (4,4 MB wobec 1,9 MB), bo każdy jego workflow to kilka wierszy statusu
i kroków.

## Zalew i awaria { #a-flood-and-a-crash }

| Wariant | Zgubione | Zdublowane | Czekanie małej organizacji p95 | Najdłuższy przestój |
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

Żaden silnik z tabeli nie zgubił zadania; `prefect-tasks` miał jeszcze dwa
niedokończone zadania, gdy jego przebieg przekroczył limit czasu. Większość
silników wykonała jedno zadanie drugi raz: to, które trzymał zabity worker. Musi
tak zrobić każda kolejka, która oddaje zadanie martwego workera. Prototyp
`pgqueue-fair` dokończył 137 zadań dwa razy. Jego pobieranie po kolei nie weszło
do produktu i właśnie te duplikaty są powodem. SAQ zostawił zadania zabitych
workerów na ponad dziewięć minut, zanim je odebrał.

## Zadanie, które zabija swojego workera { #the-job-that-kills-its-worker }

Ten scenariusz przesądził o wyborze. W jednej z wcześniejszych awarii
produkcyjnych, w innym projekcie na Celery, zadanie zabite przez OOM killera
startowało raz po raz, a jego błąd nigdy nie został zapisany. Nowa kolejka nie
mogła robić ani jednego, ani drugiego.

| Wariant | Startów zadania w 240 s | Co się stało | Zwykłe zadania |
|---|---|---|---|
| `pgqueue` | 3 | Oznaczone jako `dead` po trzeciej próbie, a błąd zapisał sweeper | Wszystkie skończone |
| `dbos` | 3 | `MAX_RECOVERY_ATTEMPTS_EXCEEDED`, zapisane przez zrestartowany proces | Wszystkie skończone |
| `procrastinate` | 4 | Startowało co minutę; przepis z dokumentacji na zawieszone zadania liczy próby, ale niczego nie ogranicza | Wszystkie skończone |
| `taskiq` | 5 | Startowało co 60 s; kontener nigdy nie umarł, bo menedżer procesów restartuje dziecko, więc z zewnątrz nic nie było widać | Wszystkie skończone |
| `pgqueuer` | 8 | Pobierane ponownie za każdym razem, gdy wygasł jego heartbeat, bez liczenia próby; 7 zabitych workerów | Wszystkie skończone |

DBOS też zatrzymał się na 3, ale druga próba pokazała drugi zakazany wynik. Gdy
worker umarł w trakcie trzech zadań i wrócił jako nowy kontener, tak jak przy
każdym deployu, po 120 s wszystkie trzy wciąż były `PENDING` pod identyfikatorem
starego executora. Nowy proces ich nie widzi. Martwego executora wykrywa DBOS
Conductor, ale przy komercyjnym self-hostingu ma on osobną licencję. Celery nie
przeszło przez ten scenariusz. Jego dokumentacja opisuje obie awarie: wiadomość
wraca bez limitu doręczeń albo zadanie ginie po cichu.

## Co weszło do produktu { #what-shipped }

Wersja 1.9.0 zastąpiła Prefecta zwykłą kolejką w Postgresie (`pgqueue`) i długo
żyjącymi workerami asyncio. Kolejka liczy próbę, gdy zadanie zostaje pobrane, a
nie gdy się kończy. Śmierć zapisuje rescuer spoza workera, a lease wygasa
niezależnie od tego, jak worker umarł. Tę samą zasadę stosują Oban, River i
Solid Queue. Ingestion działa do tego w procesach potomnych pod nadzorem pamięci,
więc jeden ciężki dokument nie kładzie workera. [Przekazywanie pracy w tle z
requestu](architecture.md#dispatching-background-work-from-a-request) pokazuje,
jak kod kolejkuje zadanie, a [Skalowanie poza jeden
host](scaling.md#more-workers), jak dodać workery.

Sprawiedliwość między organizacjami zostaje taka, jak ją zmierzyliśmy. Zwykła
kolejka dała małej organizacji prawie takie samo p95 jak prototyp z pobieraniem
po kolei (11,1 s wobec 10,1 s), bez jego duplikatów.

## Czego liczby nie mówią { #what-the-numbers-do-not-say }

- **Jedna maszyna.** Wszystkie przebiegi szły na Docker Desktop na Apple silicon.
  Na serwerze liczby bezwzględne będą inne. CPU steal na współdzielonym hoście
  spowalnia start każdego procesu, co tylko powiększa różnicę na niekorzyść
  procesu na każdy run.
- **Jeden przebieg na komórkę.** Różnice między silnikami są na tyle duże, że
  jeden przebieg wystarcza, żeby je uszeregować. Tam, gdzie dwa silniki są blisko,
  jak `pgqueue` i `pgqueuer` w narzucie, tabele nie mówią, że któryś jest szybszy.
- **Każdy silnik w swojej zwykłej konfiguracji.** Każdy silnik miał ten sam budżet
  CPU i pamięci, a nie tę samą współbieżność, bo pula procesów i pętla zdarzeń
  nie mają wspólnej jednostki. Inne ustawienie może zmienić liczbę, zwłaszcza w
  teście OOM.
- **Poprawiony błąd harnessu.** Pierwszy przebieg `tenants` na Procrastinate
  zgubił zadanie, bo harness wołał metodę, której 3.10 już nie ma. To był nasz
  błąd, nie Procrastinate. Powtórzony przebieg z tabeli skończył wszystkie 1090
  zadań.

## Jak to powtórzyć { #run-it-again }

```bash
# Z katalogu głównego repozytorium, na gałęzi spike/task-queue-benchmark.
docker build -f backend/Dockerfile -t agenticos-backend:bench-base .
cd experiments/task-queues
docker build -t tqbench:latest .
./run.sh pgqueue oom          # jeden wariant, jeden scenariusz, na świeżym projekcie
./matrix.sh                   # wszystkie komórki; kilka godzin
python3 -m bench.report results > results/TABLES.md
```

[Testy obciążeniowe](load-testing.md) odpowiadają na inne pytanie: ile jedno
wdrożenie AgenticOS może obsłużyć, a nie który silnik powinien wykonywać jego
zadania.
