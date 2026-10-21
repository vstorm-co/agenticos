---
source_sha: "0dc46f479226"
---

# Skalowanie poza jeden host { #scale-beyond-one-host }

Dostarczana ścieżka to [jeden host z Docker Compose](deploy.md). Ta strona
opisuje krok dalej: zarządzany Postgres, kilka hostów API, osobne workery albo
kilka wdrożeń obok siebie. Mówi, czego potrzebuje każda część, gdy się
przenosi, i czego platforma jeszcze nie robi, żeby plan opierał się na tym, co
działa.

Najpierw zmierz. Jeden host o [zalecanym rozmiarze](deploy.md#sizing-the-host)
obsługuje zespół liczący kilkadziesiąt osób, a większość spowolnień na małym
hoście to CPU steal albo za mała pula połączeń, a nie brak repliki.
[Zestaw testów obciążeniowych](load-testing.md) uruchamia ten sam scenariusz na
dowolnym wdrożeniu.

## Co trzyma stan, a co nie { #what-holds-state-and-what-does-not }

| Część | Co przechowuje | Jak rośnie |
|---|---|---|
| API (`app`) | Nic własnego. Sesje, obecność, trwające tury czatu i strumień zmian na żywo są w Postgresie i Redisie | Więcej workerów uvicorn, potem więcej hostów za load balancerem |
| Worker | Nic. Zadania, dzierżawy i harmonogramy to wiersze w Postgresie | Więcej procesów, na dowolnych hostach, z pulami podzielonymi między nie |
| Konsola (`frontend`) | Branding, który trzyma w cache przez pięć minut | Więcej instancji |
| Postgres | Wszystko trwałe: organizacje, agenci, rozmowy, wektory, kolejka zadań | Większa instancja albo zarządzana |
| Redis (Valkey) | Cache i jego kanały pub/sub, odbudowywane po restarcie | Jedna instancja wspólna dla wszystkich hostów |
| Przesłane pliki | Wolumen na hoście albo bucket | Bucket, gdy czyta je lub zapisuje więcej niż jeden host |
| Usługa sandboxów | Sandboksy, w których agenci uruchamiają polecenia | Własny host, zobacz [Przestrzenie robocze agentów](configuration.md#running-the-service-on-another-host) |

## Jedna baza na wdrożenie { #one-database-per-deployment }

Wszystkie organizacje we wdrożeniu dzielą jedną bazę Postgresa, a każde
zapytanie jest zawężone do organizacji. Są w niej też wektory każdej bazy
wiedzy, przez pgvector, i kolejka zadań. `POSTGRES_DB` wskazuje jedyną bazę,
której używa wdrożenie: nie ma osobnej bazy wektorowej, repliki do odczytu ani
shardingu po organizacjach.

Kilka baz oznacza więc kilka wdrożeń. To odpowiedź na dane, które muszą zostać
w jednym regionie, na jednostkę biznesową z własnymi administratorami i na
tenanta, którego obciążenie nie powinno dotykać pozostałych. Każde wdrożenie ma
własne nazwy hostów, `SECRET_KEY` i `VAULT_MASTER_KEY`, a w czasie działania nic
między nimi nie jest współdzielone.

Mogą dzielić infrastrukturę. Dwa wdrożenia na jednym serwerze Postgresa
potrzebują osobnych baz (`POSTGRES_DB`), a na jednym Redisie osobnych numerów
`REDIS_DB`, żeby kubełki limitów i odpowiedzi w cache się nie mieszały. Bucket
też jest jeden na wdrożenie. Agent przechodzi między nimi jako specyfikacja:
wyeksportuj ją jako YAML w jednym (`GET /agents/{id}/spec.yaml`) i zaimportuj do
agenta w drugim.

## Zewnętrzny Postgres { #an-external-postgres }

Zarządzany albo własny Postgres działa, gdy ma:

- **PostgreSQL 16 z pgvector.** Usługi zarządzane podają je jako rozszerzenie
  `vector`. Platforma tworzy je przy pierwszym zapisie do kolekcji, więc rola,
  którą się łączy, potrzebuje `CREATE` na bazie, albo administrator tworzy je
  wcześniej. To samo dotyczy `pg_stat_statements`: migracja dodaje je tam, gdzie
  może, a tam, gdzie nie może, pomija z komunikatem.
- **Szyfrowane połączenie** do bazy na innym hoście. Zobacz
  [Szyfrowane połączenia](configuration.md#encrypted-connections-tls): override
  musi dotrzeć do `app`, `migrate` i `worker`, bo pliki compose przypinają host
  w każdej z tych usług.
- **Migracje uruchamiane raz.** Usługa `migrate` stosuje je, zanim wystartuje
  API. Przy kilku hostach uruchom ją z jednego wdrożenia, a nie z każdego.

Po przełączeniu awaryjnym zarządzanej bazy pierwsze żądanie w każdym procesie,
które trafi na zerwane połączenie, kończy się błędem, a pula odrzuca wtedy
wszystkie połączenia starsze od niego. Silniki nie sprawdzają połączenia przed
użyciem, bo każde pobranie z puli kosztowałoby dodatkową wymianę z bazą.

### Liczenie połączeń { #counting-connections }

Najpierw ustaw `max_connections`, bo inaczej Postgres odrzuca połączenia z
komunikatem „too many clients”, zanim pula zdąży ustawić żądania w kolejce albo
odciąć nadmiar.

Każdy proces API otwiera dwie pule po `DB_POOL_SIZE + DB_MAX_OVERFLOW`, domyślnie
po 15: jedną dla żądań i jedną dla wyszukiwań wektorowych, które działają w
żądaniu trzymającym już połączenie. Proces workera otwiera te same dwie oraz
krótkotrwałe połączenie na każde wykonywane zadanie. Każde dziecko ingest to
osobny proces, a wykonywane przez nie zadanie zapisuje wektory przez własny
silnik z domyślną pulą 15, zamykany po zakończeniu zadania. Wyszukiwania w
wiedzy wykonywane przez agenta łączą się raz na wyszukiwanie, bez puli.

```text
max_connections ≥ hosty API × UVICORN_WORKERS × 30
                + procesy workerów × 30
                + dzieci ingest × 15
                + zapas na migracje i sesję administratora
```

Dwa hosty API po cztery workery uvicorn i dwa workery z jednym dzieckiem ingest
każdy dają 330, więc rozsądne ustawienie to 400. To górne granice: bezczynne
wdrożenie trzyma ich znacznie mniej. Produkcyjny plik compose ustawia 200 dla
jednego hosta.

### PgBouncer { #pgbouncer }

Tylko w trybie sesji. Pooling transakcyjny psuje dwie rzeczy, na których opiera
się platforma: prepared statements asyncpg, których żadne ustawienie tu nie
wyłącza, i advisory lock na poziomie sesji, który pilnuje, żeby jedno źródło
synchronizacji nie działało dwa razy naraz. Tryb sesji ogranicza liczbę połączeń
serwera, ale poza tym niewiele oszczędza, więc lepszą dźwignią jest zwykle
dopasowanie pul do `max_connections`.

## Więcej hostów API { #more-api-hosts }

Postaw z przodu load balancer, który przepuszcza WebSockety: aktualizacje na
żywo i czat w konsoli używają `/api/v1/ws/*`. Sticky sessions nie są potrzebne.
Osoba, której socket połączy się ponownie z innym hostem, śledzi trwającą turę
przez Redisa, a obecność i limity też są tam przechowywane.

Każdy host potrzebuje:

- **Tych samych sekretów.** `SECRET_KEY` podpisuje tokeny, które każdy host musi
  zweryfikować, a `VAULT_MASTER_KEY` odszyfrowuje każde zapisane poświadczenie.
- **Bucketu.** Przy `FILE_STORAGE_BACKEND=local` plik przesłany przez jeden host
  nie istnieje na drugim, a worker, który go parsuje, może nie być na żadnym z
  nich. Użyj `s3` (zobacz
  [Przesłane pliki](configuration.md#uploaded-files-at-rest)).
- **Tego samego Redisa**, jako jednej instancji albo jednego endpointu przed
  instancją główną. Klient nie obsługuje klastra, więc Redis Cluster nie jest
  wspierany.
- **`RATE_LIMIT_TRUST_FORWARDED_FOR`**, gdy load balancer jest jedyną drogą do
  hostów, bo inaczej wszyscy odwiedzający dzielą kubełek load balancera.

Tura czatu działa w procesie API, który ją przyjął, a nie w workerze, więc to
hosty API niosą obciążenie czatu, a `UVICORN_WORKERS` dobiera się do niego jak
[na jednym hoście](deploy.md#sizing-the-host).

Kilka instancji konsoli nie stanowi problemu. Branding trzymają w cache osobno:
zmiana administratora pojawia się od razu na instancji, która ją zapisała, a na
pozostałych w ciągu pięciu minut.

## Więcej workerów { #more-workers }

Uruchom tyle procesów workerów, ile potrzeba, na dowolnych hostach. Pobierają
zadania przez `SKIP LOCKED`, więc żadne dwa nie wykonają tego samego zadania, a
każdy z nich może odpalić należny harmonogram. Worker, który padnie, oddaje
swoje zadania w ciągu `WORKER_LEASE_SECONDS`.

Rozdziel pule, gdy parsowanie konkuruje z uruchomieniami agentów.
`WORKER_POOLS=agent,system` na jednych procesach i `WORKER_POOLS=ingest` na
hostach z zapasem pamięci sprawiają, że duży upload nie opóźnia rutyny. Sonda
zdrowia i `agenticos cmd doctor` zgłaszają pulę, której nie obsługuje żaden żywy
worker. Ustawienia z sekcji
[Zadania w tle](configuration.md#background-work) określają rozmiar każdego
procesu.

## Redis { #redis }

Wszystkie hosty API i workery używają tego samego Redisa: przenosi między nimi
strumień zmian na żywo, obecność, trwające tury i limity. To cache, więc restart
nie traci niczego trwałego. Aktualizacje na żywo łączą się ponownie, a osoba
śledząca trwającą turę zobaczy odpowiedź w transkrypcji, gdy się pojawi, a nie
klatka po klatce.

## Zmierz, zanim dodasz hosty { #measure-before-you-add-hosts }

- **`agenticos cmd doctor`** mówi, do którego Postgresa i Redisa dotarło każde
  połączenie, czy było szyfrowane i czy workery żyją.
- **`pg_stat_statements`** pokazuje, które zapytania najwięcej kosztują bazę.
- **Logfire**, z `LOGFIRE_ENVIRONMENT` ustawionym osobno dla każdego wdrożenia,
  oddziela ślady jednego wdrożenia od drugiego (zobacz
  [Obserwowalność](configuration.md#observability-logfire)).
- **[Zestaw testów obciążeniowych](load-testing.md)**, uruchomiony przed zmianą i
  po niej, mówi, czy pomogła.

## Czego jeszcze nie robi { #what-it-does-not-do-yet }

- Replik do odczytu ani własnej bazy wektorowej.
- Shardingu organizacji między bazami w jednym wdrożeniu.
- PgBouncera w trybie transakcyjnym ani Redis Cluster.
- Manifestów Kubernetes. Obrazy są te same, które uruchamiają pliki compose, a
  każda usługa ma własny health check, więc klaster uruchamia je ze środowiskiem
  opisanym na tej stronie.
