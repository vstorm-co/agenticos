---
source_sha: 4b2b3dcb65c8
---

# Konfiguracja { #configuration }

Cała konfiguracja jest zarządzana przez zmienne środowiskowe, wczytywane z
`backend/.env` przy użyciu [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

Ustawienia są zdefiniowane w `app/core/config.py` i dostępne przez globalny
obiekt `settings`:

```python
from app.core.config import settings

print(settings.EMBEDDING_MODEL)
print(settings.DEBUG)
```

## Na początek { #getting-started }

`make install` tworzy `backend/.env` z `backend/.env.example`, kiedy tego pliku
nie ma, i nigdy więcej go nie dotyka — więc na świeżym checkoucie nie ma czego
kopiować, a na istniejącym nie ma czego stracić.

Zanim cokolwiek trafi do sieci, w której jest ktoś jeszcze, ustaw wartości, które
przykład dostarcza jako placeholdery:

```bash
openssl rand -hex 32   # SECRET_KEY — signs every access token
openssl rand -hex 32   # VAULT_MASTER_KEY — unwraps every credential stored at rest
```

!!! danger "`SECRET_KEY` jest dostarczany jako publicznie znany ciąg znaków"

    Pusty `VAULT_MASTER_KEY` cofa się do niego, żeby świeży checkout w ogóle
    działał. Oba są w porządku na laptopie i są całym bezpieczeństwem wdrożenia
    gdziekolwiek indziej. Jawne ustawienie `VAULT_MASTER_KEY` jest też tym, co
    pozwala przechowywanym sekretom przetrwać rotację `SECRET_KEY`.

Konfiguracja odrzuca nieustawiony `VAULT_MASTER_KEY` poza `local`/`development`.

## Ustawienia projektu { #project-settings }

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `PROJECT_NAME` | `agenticos` | Nazwa wyświetlana projektu |
| `API_V1_STR` | `/api/v1` | Prefiks wersji API |
| `DEBUG` | `false` | Włącza tryb debugowania (szczegółowe błędy, auto-reload) |
| `ENVIRONMENT` | `local` | Jedno z: `development`, `local`, `staging`, `production` |
| `TIMEZONE` | `UTC` | Strefa czasowa IANA (np. `UTC`, `Europe/Warsaw`, `America/New_York`) |
| `MODELS_CACHE_DIR` | `./models_cache` | Katalog na cache modeli ML |
| `MEDIA_DIR` | `./media` | Katalog na przesłane pliki |
| `MAX_UPLOAD_SIZE_MB` | `50` | Limit dokumentu w knowledge base i liczba, z której wyprowadzany jest opisany niżej sufit całego żądania. Dokument tej wielkości jest dzielony na chunki i embedowany, a nie trzymany w jednym kawałku |
| `CHAT_MAX_UPLOAD_SIZE_MB` | `10` | Co można załączyć w czacie. Ma własne ustawienie zamiast tego powyżej, bo załącznik do agenta bez workspace'u jest wklejany w całości do promptu — więc obie powierzchnie zawodzą inaczej przy tym samym rozmiarze. Kiedyś było to zahardkodowane 10 MiB, którego żaden operator nie mógł podnieść ([#498](https://github.com/vstorm-co/agenticos/issues/498)); kontener frontendu czyta ten sam `CHAT_MAX_UPLOAD_SIZE_MB` w czasie działania, więc daj obu kontenerom jedną wartość albo composer odrzuci plik, który serwer by przyjął |
| `EMBED_MAX_UPLOAD_SIZE_MB` | `5` | Co **obcy** może przesłać na hostowaną stronę. Sufit nałożony na `CHAT_MAX_UPLOAD_SIZE_MB`, nigdy sposób na jego obejście |
| `MEM0_ALLOWED_HOSTS` | `[]` (empty) | Nazwy hostów, na które może wskazywać self-hostowana usługa pamięci mem0. `base_url` pochodzi ze speca agenta, więc bez allowlisty Builder, który może podpiąć (ale nie odczytać) współdzielony klucz mem0, mógłby wycelować go we własny serwer i przechwycić klucz z nagłówka żądania. Pusta wartość odrzuca self-hostowane mem0 i dopuszcza wyłącznie zarządzaną chmurę; dodaj zaufaną nazwę hosta, aby włączyć wdrożenie self-hosted. Zobacz [sekrety](secrets.md) |
| `FILE_IO_MAX_WORKERS` | `8` | Rozmiar dedykowanej puli wątków, która wykonuje blokującą pracę na plikach — parsowanie uploadu oraz odczyt i zapis jego bajtów. Trzymana poza domyślnym współdzielonym executorem `asyncio`, który obsługuje też `bcrypt` i DNS przypiętych hostów, żeby fala uploadów nie zostawiła logowania i wychodzących żądań w kolejce za nimi ([#1108](https://github.com/vstorm-co/agenticos/issues/1108)). Podnieś ją na hoście, który parsuje wiele uploadów naraz. Musi być dodatnią liczbą całkowitą — `0` lub wartość ujemna zostaje odrzucona przy starcie |
| `DEFAULT_ORG_MONTHLY_BUDGET_USD` | `100` | Miesięczny sufit wydatków, z którym startuje **nowa** organizacja, w USD, żeby nie była o jednego rozbieganego agenta od zaskakującego rachunku. Obowiązuje tylko przy tworzeniu; istniejące organizacje pozostają nietknięte i każdej organizacji można później wyczyścić limit. Musi być dodatni; zostaw **pusty**, aby organizacje startowały bez limitu (starsza postawa opt-in) |

### Rozmiar żądania, a nie rozmiar pliku { #the-size-of-a-request-as-opposed-to-the-size-of-a-file }

Każdy limit powyżej jest mierzony na bajtach, które już dotarły. FastAPI parsuje
treść multipart, żeby rozwiązać parametr `UploadFile`, *zanim* uruchomi się
handler, więc zanim któryś z tych sufitów zostanie porównany z `len(data)`, treść
jest już zbuforowana do pliku tymczasowego i wczytana do pamięci. Za sesją nie
jest to duże ryzyko; na `POST /api/v1/embed/{key}/files`, do którego może sięgnąć
obcy trzymający link, już jest.

Dlatego żądanie deklarujące `Content-Length` większy niż `MAX_UPLOAD_SIZE_MB` plus
5 MiB zapasu na kopertę multipart dostaje odpowiedź **413**, zanim jego treść
zostanie odczytana. Nie ma tu ustawienia: wartość idzie za `MAX_UPLOAD_SIZE_MB`,
bo druga liczba, którą trzeba trzymać w zgodzie z pierwszą, to liczba, która
kończy poniżej niej.

**To tańsza połowa odpowiedzi, nie całość.** `Content-Length` ustawia wołający, a
żądanie chunked nie deklaruje go wcale — te są przepuszczane i ograniczane
limitami per trasa, które mierzą prawdziwe bajty. Wdrożenie, które chce gwarancji,
a nie uprzejmości, ustawia `client_max_body_size` (nginx) albo odpowiednik na tym,
co kończy jego połączenia; pliki compose uruchamiają uvicorna bez własnego takiego
limitu.

## Uwierzytelnianie { #authentication }

### JWT { #jwt }

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `SECRET_KEY` | (insecure default) | Klucz podpisujący JWT. **Musi** zostać zmieniony w produkcji. Wygeneruj: `openssl rand -hex 32` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Czas życia access tokena |
| `REFRESH_TOKEN_EXPIRE_MINUTES` | `10080` | Czas życia refresh tokena (7 dni) |
| `ALGORITHM` | `HS256` | Algorytm podpisu JWT |

Walidacja produkcyjna: `SECRET_KEY` musi mieć co najmniej 32 znaki i nie może
używać wartości domyślnej przy `ENVIRONMENT=production`.

### Vault sekretów { #secret-vault }

Każde poświadczenie, które platforma przechowuje w spoczynku — klucze providerów,
tokeny botów kanałów, poświadczenia MCP i sekrety organizacji — jest zapieczętowane
przez `app/core/vault.py`, którego koperta wyprowadzana jest z klucza głównego **i
z właściciela** (organizacji albo członka, do którego należy osobiste połączenie).
Szyfrogram jest więc bezużyteczny poza tenantem, dla którego go zapieczętowano.

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `VAULT_MASTER_KEY` | (empty, falls back to `SECRET_KEY`) | Klucz główny vaultu sekretów — skrót na wersję 1 z `VAULT_MASTER_KEYS`. Wymagany poza `local`/`development` (o ile nie ustawiono mapy poniżej), żeby vault na stagingu nie mógł wstać zapieczętowany pod opublikowaną wartością domyślną `SECRET_KEY`. Wygeneruj: `openssl rand -hex 32` |
| `VAULT_MASTER_KEYS` | `{}` | Każdy klucz główny nadal w użyciu, po wersjach, jako JSON — `{"1": "<old>", "2": "<new>"}`. Najwyższa wersja pieczętuje nowe sekrety; starsze trzymają istniejące wiersze czytelnymi, dopóki `agenticos cmd vault-rotate` nie przepakuje ich na nowo. Kiedy jest ustawiona, jest całą prawdą: `VAULT_MASTER_KEY` musi być wtedy pusty. Zobacz [Sekrety](secrets.md#operations) |

### Klucz API { #api-key }

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `API_KEY` | `change-me-in-production` | Współdzielony klucz API do dostępu programistycznego |
| `API_KEY_HEADER` | `X-API-Key` | Nazwa nagłówka HTTP dla klucza API |

Walidacja produkcyjna: `API_KEY` nie może używać wartości domyślnej przy
`ENVIRONMENT=production`.

### OAuth2 (Google) { #oauth2-google }

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `GOOGLE_CLIENT_ID` | (empty) | Client ID Google OAuth2 — logowanie **oraz** zgoda dla triggera Gmail |
| `GOOGLE_CLIENT_SECRET` | (empty) | Client secret Google OAuth2 |
| `GOOGLE_REDIRECT_URI` | `http://localhost:8000/api/v1/oauth/google/callback` | URL callbacku OAuth2 |
| `FRONTEND_URL` | `http://localhost:3000` | URL frontendu dla przekierowań OAuth2 |

Skąd wziąć tę parę: [konsola Google Cloud](https://console.cloud.google.com/) →
APIs & Services → Credentials → Create OAuth client ID → **Web application**.

Autoryzowany redirect URI to callback **backendu**, a nie frontendu —
`http://localhost:8000/api/v1/oauth/google/callback` domyślnie, a we wdrożeniu to,
co mówi `GOOGLE_REDIRECT_URI`. Google wymienia kod z API, które dopiero potem
odsyła przeglądarkę na `FRONTEND_URL`. Zarejestrowanie zamiast tego URL-a
frontendu to błąd wart nazwania: ekran zgody działa, a callback zwraca 404.

Przeglądarka jest odsyłana z jednorazowym, minutowym kodem, nigdy z samymi
tokenami sesji: token w URL-u przekierowania trafia do paska adresu, do logu
dostępu serwera frontendu i do `Referer` następnego żądania same-origin, a refresh
token jest ważny przez tydzień. Frontend wymienia kod na parę tokenów
serwer–serwer pod `POST /api/v1/oauth/exchange`, które realizuje go dokładnie raz.


## Baza danych (PostgreSQL) { #database-postgresql }

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `POSTGRES_HOST` | `localhost` | Host PostgreSQL |
| `POSTGRES_PORT` | `5432` | Port PostgreSQL |
| `POSTGRES_USER` | `postgres` | Użytkownik PostgreSQL |
| `POSTGRES_PASSWORD` | (empty) | Hasło PostgreSQL |
| `POSTGRES_DB` | `agenticos` | Nazwa bazy danych |
| `POSTGRES_SSLMODE` | (empty) | Szyfruj połączenie: `require`, `verify-ca` albo `verify-full`. Pusta wartość to plaintext. Zobacz [Szyfrowane połączenia](#encrypted-connections-tls) |
| `DB_POOL_SIZE` | `5` | Rozmiar puli połączeń |
| `DB_MAX_OVERFLOW` | `10` | Maksymalna liczba połączeń ponad pulę |
| `DB_POOL_TIMEOUT` | `30` | Timeout puli w sekundach |

Właściwości wyliczane:
- `DATABASE_URL` -- asynchroniczny connection string (`postgresql+asyncpg://...`)
- `DATABASE_URL_SYNC` -- synchroniczny connection string dla Alembica

## Redis { #redis }

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `REDIS_HOST` | `localhost` | Host Redisa |
| `REDIS_PORT` | `6379` | Port Redisa |
| `REDIS_PASSWORD` | (none) | Hasło Redisa (opcjonalne) |
| `REDIS_DB` | `0` | Numer bazy Redisa |
| `REDIS_SSL` | `false` | Szyfruj połączenie (`rediss://`). Zobacz [Szyfrowane połączenia](#encrypted-connections-tls) |

## Szyfrowane połączenia (TLS) { #encrypted-connections-tls }

Oba magazyny łączą się domyślnie plaintextem. Na pojedynczym hoście, gdzie Postgres
i Redis są w tej samej sieci Dockera, jest to w porządku i tak właśnie działają
dostarczane pliki compose. Przy zarządzanym Postgresie albo Redisie na innym węźle
szyfrowanie połączenia jest tą kontrolą bezpieczeństwa transmisji, o którą audytor
pyta najpierw (HIPAA §164.312(e), SOC 2 CC6.7).

Ustawienie `POSTGRES_SSLMODE` buduje URL, który rozumie każdy ze sterowników —
`?ssl=<mode>` dla asyncpg aplikacji, `?sslmode=<mode>` dla psycopg2 Alembica — a
`REDIS_SSL` przełącza schemat Redisa na `rediss://`. `require` szyfruje połączenie;
`verify-ca` i `verify-full` sprawdzają dodatkowo certyfikat serwera.

`REDIS_SSL` wymaga też poprawnego łańcucha certyfikatów i zgodnej nazwy hosta w
samym URL-u, zamiast zostawiać jedno i drugie domyślnym ustawieniom redis-py.

!!! warning "Prywatne CA to plik, który czytają sterowniki, a nie systemowy magazyn zaufania"

    Żaden ze sterowników nie zagląda do magazynu zaufania kontenera, a obraz działa
    jako użytkownik bez uprawnień roota i bez entrypointu, który mógłby go
    przebudować. asyncpg i libpq czytają plik CA wskazany przez `PGSSLROOTCERT`;
    redis-py ufa temu zestawowi, na który wskazuje OpenSSL, a nadpisuje go
    `SSL_CERT_FILE`. Zamontuj CA raz i ustaw obie zmienne na ten plik —
    `verify-ca` i `verify-full` bez pierwszej z nich zawodzą, bo asyncpg szuka
    wtedy `~/.postgresql/root.crt` i niczego nie znajduje.

!!! note "Każda usługa, która otwiera połączenie do magazynu, potrzebuje tej zmiany"

    `app`, `migrate` i `prefect-runner` łączą się z Postgresem i Redisem, a
    dostarczane pliki compose przypinają `POSTGRES_HOST=db` i `REDIS_HOST=redis` w
    `environment` każdej z nich, co wygrywa z plikiem env. Zarządzany magazyn to
    więc plik override sięgający wszystkich trzech, a nie linia w `.env`.

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

Dołączone usługi `db` i `redis` dalej się uruchamiają, nieużywane; `agenticos cmd
doctor` pokazuje, do którego magazynu faktycznie dotarło każde połączenie i czy
było szyfrowane (`postgres: tls=on/off`, `redis: tls=on/off`, z `pg_stat_ssl` i ze
schematu URL).

## E-mail (SMTP) { #email-smtp }

Wdrożenie wysyła pocztę przez serwer SMTP, a takie, które nie ma go
skonfigurowanego, nie zawodzi — działa, a każdy przepływ zależny od poczty po cichu
się zatrzymuje i żaden z nich tego nie oznajmia:

- **logowanie bez hasła i resety haseł** — maile z magic linkiem i z resetem to
  samoobsługowe drogi do konta;
- **zaproszenia** — zapraszany adres nigdy nie dostaje maila (konsola mówi to teraz
  wprost, zamiast twierdzić, że wysłała, #1484);
- **powiadomienia** — przekroczenie budżetu, prośba o zatwierdzenie, raport zużycia,
  informacja wysyłana, gdy administrator działa jako inne konto.

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `SMTP_HOST` | `localhost` | Host serwera SMTP |
| `SMTP_PORT` | `587` | Port serwera SMTP. `587` i `25` negocjują STARTTLS; `465` otwiera TLS od początku |
| `SMTP_USER` | (empty) | Nazwa użytkownika, którą uwierzytelnia się relay, obok `SMTP_PASSWORD`. Zostaw pustą dla relaya bez uwierzytelniania |
| `SMTP_PASSWORD` | (empty) | Hasło do tej nazwy użytkownika |
| `SMTP_TLS` | `true` | Czy szyfrować połączenie. Schemat wybiera port — STARTTLS na `587`, niejawny TLS na `465` — chyba że `SMTP_TLS_MODE` mówi inaczej. Ustaw `false` tylko dla nieszyfrowanego relaya, na przykład lokalnego serwera na `25` |
| `SMTP_TLS_MODE` | `auto` | Jak otwierane jest szyfrowane połączenie. `auto` pozwala wybrać portowi; `implicit` otwiera TLS od pierwszego bajtu, a `starttls` negocjuje podniesienie, niezależnie od portu. Ignorowane, gdy `SMTP_TLS=false` |
| `EMAIL_FROM` | `noreply@agenticos.com` | Adres w polu `From` każdej wiadomości |
| `EMAIL_FROM_NAME` | `agenticos` | Nazwa wyświetlana obok tego adresu |

!!! note "Jak szyfrowane jest połączenie"

    `SMTP_TLS` to przełącznik włącz/wyłącz; schemat wybiera port. Dostarczana
    wartość domyślna — `587` z `SMTP_TLS=true` — negocjuje STARTTLS, czyli to,
    czego oczekuje zgodny ze standardem serwer submission. Użyj `465` dla serwera,
    który chce zamiast tego niejawnego TLS, i `SMTP_TLS=false` na `25` dla relaya
    plaintext.

    Serwer mówiący niejawnym TLS na porcie innym niż `465` — powiedzmy `8465` —
    potrzebuje `SMTP_TLS_MODE=implicit`, bo `auto` zaproponowałoby mu handshake
    plaintext i każda wysyłka by zawiodła. `starttls` to przypadek odwrotny.

## Praca w tle (Prefect) { #background-work-prefect }

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `PREFECT_API_URL` | `http://localhost:4200/api` | Self-hostowany serwer albo URL workspace'u Prefect Cloud |
| `PREFECT_API_KEY` | (none) | Tylko Prefect Cloud |
| `PREFECT_RUNNER_LIMIT` | `5` | Ile flow runów wykonuje się naraz; reszta czeka w kolejce |
| `PREFECT_RUNNER_SERVER_HOST` | `127.0.0.1` w compose | Interfejs, na którym runner serwuje własny endpoint zdrowia |
| `PREFECT_RUNNER_SERVER_PORT` | `8080` | Port do tego samego |

`PREFECT_RUNNER_LIMIT` to sufit pamięci, a nie pokrętło przepustowości. Każdy run
to osobny proces, który importuje całą aplikację — mniej więcej 120 MB — a liczbą,
która ma znaczenie, nie jest stan ustalony, tylko restart: runner wstaje, znajduje
każdy run zaplanowany w czasie, gdy go nie było, i startuje tyle, na ile pozwala
limit. Bez limitu trzy dni przestoju to 71 procesów i 6 GiB. Podnieś go, jeśli
ingestia kolejkuje się za synchronizacjami na maszynie z zapasem pamięci; obniż na
małym hoście.

Dwie zmienne `PREFECT_RUNNER_SERVER_*` należą do Prefecta, a pliki compose
przypinają je, żeby kontener runnera miał status zdrowia, który coś znaczy. Runner
startuje webserver runnera Prefecta, którego `GET /health` odpowiada 503, gdy
przegapi dwa odpytania API Prefecta — więc proces, który żyje, ale nie podejmuje
już pracy, czyta się jako `unhealthy`, a nie jako w porządku. Jest przypięty do
loopbacku, bo ten sam webserver wystawia też `POST /shutdown`; próba działa
wewnątrz kontenera i nic spoza niego nie sięgnie żadnego z nich. Przeniesienie
portu oznacza przeniesienie razem z nim próby w plikach compose.

W `backend/Dockerfile` nie ma `HEALTHCHECK`. Obraz jest uruchamiany jako dwa różne
procesy — API i ten runner — a próba dla jednego jest stałym fałszywym alarmem dla
drugiego, więc każda definicja usługi nosi własną.

### Wygasanie zatwierdzeń { #approval-expiry }

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `APPROVAL_EXPIRY_HOURS` | `72` | Jak długo zaparkowane wywołanie narzędzia czeka, zanim cogodzinne zamiatanie odrzuci je przez timeout |

Trzy dni, bo musi objąć weekend: zatwierdzenie, które przychodzi w piątek po
południu, jest tym, o którym nikt nie decyduje, a wygaszenie go w sobotę byłoby
wygaszeniem za to, że ktoś zapytał o złej porze. Skróć je tam, gdzie kolejka jest
pilnowana w godzinach pracy i nieaktualna prośba jest gorsza niż wolna; wydłuż tam,
gdzie zatwierdzenia są cotygodniowym rytuałem. Wygaśnięcie wywołania **kończy też
jego run** — zobacz [Governance](governance.md#a-decision-nobody-makes), co to
rozstrzyga i co celowo zostawia w spokoju.

### Zbieranie porzuconych runów { #stale-run-reaping }

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `STALE_RUN_REAPED_AFTER_HOURS` | `6` | Jak długo run może stać w stanie `running`, zanim cogodzinne zamiatanie uzna, że jego proces umarł, i zakończy go jako `failed`. Zero lub mniej wyłącza zamiatanie |

Wiersz runa jest commitowany przed wywołaniem jego modelu, więc worker zabity w
trakcie runa zostawia go w stanie `running` bez niczego, co by go dokończyło. Sufit
nie musi być dokładny — żywy run, który zamiatanie mimo to przestawi, zostaje
przestawiony z powrotem przez własny zapis końcowy — więc ustaw go daleko za swoim
najdłuższym uprawnionym runem i nie bliżej. Zobacz
[Governance](governance.md#a-run-whose-process-died).

## Modele AI — konfigurowane w aplikacji, nie tutaj { #ai-models-configured-in-the-app-not-here }

Modele czatu nie są zmiennymi środowiskowymi. Każda organizacja trzyma własne klucze
providerów w vaulcie (Settings → Models), a spec każdego agenta nazywa profil
modelu, na którym ten agent działa. `AI_MODEL`, `AI_TEMPERATURE`,
`AI_THINKING_ENABLED`, `AI_THINKING_EFFORT`, `AI_AVAILABLE_MODELS`,
`AI_FRAMEWORK` i `LLM_PROVIDER` zostały usunięte razem z ogólnym asystentem z
szablonu; ustawienie ich teraz nic nie robi.

Jedynym poświadczeniem modelu, które zostaje w środowisku, jest klucz do
embeddingów — zobacz RAG poniżej.

## Obserwowalność (Logfire) { #observability-logfire }

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `LOGFIRE_TOKEN` | (none) | Token Pydantic Logfire. Zdobądź go na https://logfire.pydantic.dev |
| `LOGFIRE_SERVICE_NAME` | `agenticos` | Nazwa usługi na dashboardzie Logfire |
| `LOGFIRE_ENVIRONMENT` | `development` | Etykieta środowiska |
| `LOGFIRE_ORGANIZATION` | (none) | Slug organizacji, do zbudowania linku **do** zapisanego trace'u. Token jest poświadczeniem do *zapisu* i nie niesie żadnego z tych slugów |
| `LOGFIRE_PROJECT` | (none) | Slug projektu, obok organizacji. Gdy któregokolwiek brakuje, `logfire_trace_id` runa nadal jest zapisywane, a link nie jest oferowany |
| `LOGFIRE_BASE_URL` | `https://logfire-us.pydantic.dev` | Do którego wdrożenia Logfire te slugi należą. `logfire-eu` to inny host, a link zbudowany dla niewłaściwego zwraca 404 |

## Wyszukiwanie w sieci { #web-search }

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|

## RAG (Retrieval Augmented Generation) { #rag-retrieval-augmented-generation }

### Baza wektorowa { #vector-database }

pgvector korzysta z istniejącego połączenia do PostgreSQL. Nie trzeba nic
dodatkowo konfigurować — ale **obraz** musi być `pgvector/pgvector:pg16`, co
przypina tutaj każdy plik compose.

!!! note "\"Vector store: unconfigured\" na świeżym wdrożeniu to nie usterka"

    Rozszerzenie jest tworzone przy pierwszym zapisie do kolekcji, więc przed
    pierwszym dokumentem naprawdę go nie ma i mówią o tym zarówno strona System w
    panelu administracyjnym, jak i `agenticos cmd doctor`. Rozwiązuje się samo przy
    pierwszej ingestii.

    Usterką jest tam `unhealthy`, a komunikat nazywa, która z trzech przyczyn:
    obraz nie dostarcza pgvectora; łącząca się rola nie może go utworzyć; albo
    katalog danych nosi wiersz rozszerzenia, podczas gdy obraz, na którym teraz
    działa, stracił bibliotekę. Wszystkie trzy zawodzą upload już po przyjęciu
    bajtów i wszystkie trzy czytały się kiedyś tak samo jak zdrowy pierwszy dzień
    ([#1504](https://github.com/vstorm-co/agenticos/issues/1504)).

### Embeddingi { #embeddings }

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | (empty) | Zapasowe poświadczenie do embeddingów, dla kolekcji, które nie wybrały własnego klucza z vaultu — i to, do którego cofa się zdegradowany wybór. Nie „każda kolekcja embeduje na nim”: zobacz [Przetwarzanie plików](file-processing.md#embeddings-the-model-whose-endpoint-answers-and-whose-key-pays) |
| `EMBEDDING_MODEL` | `text-embedding-3-large` | Czym budowana jest **nowa** kolekcja. Szerokość jest zapisywana w wierszu i już się potem nie zmienia, więc zmiana tego ustawienia nie unieważnia istniejących kolekcji — one dalej embedują modelem, z którym zostały utworzone |

### Parsowanie dokumentów — konfigurowane per kolekcja, nie tutaj { #document-parsing-configured-per-collection-not-here }

Parser, OCR, rozmiar chunka, zakładka między chunkami, strategia chunkowania i
model opisujący obrazy **nie** są zmiennymi środowiskowymi. Są zapisane na każdej
knowledge base (`knowledge_bases.ingestion_config`) i edytowane na `/rag`, a każde
z nich można dodatkowo nadpisać dla pojedynczego uploadu.

Powodem jest to, że jedna wartość obowiązująca w całej instalacji sprawiała, że ten
sam formularz dawał różne kolekcje na dwóch wdrożeniach i nic w produkcie nie
pokazywało która — a zeskanowane archiwum umów i folder notatek w Markdownie chcą
różnych odpowiedzi na tym samym wdrożeniu. `PDF_PARSER`, `CHAT_PDF_PARSER`,
`LLAMAPARSE_TIER`, `LITEPARSE_OCR_LANGUAGE`, `LITEPARSE_TIMEOUT_SECONDS`,
`RAG_ENABLE_OCR`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP` i
`RAG_CHUNKING_STRATEGY` zostały usunięte; ustawienie ich teraz nic nie robi.

To, co zostaje tutaj, to to, czego tenant nie może wybierać:

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `LLAMAPARSE_API_KEY` | (empty) | Zapasowy klucz LlamaParse dla kolekcji, które nie wybrały własnego klucza z vaultu |
| `LITEPARSE_OCR_SERVER_URL` | (empty) | Serwer OCR po HTTP; adres we własnej sieci wdrożenia |

Załączniki w czacie są czytane PyMuPDF-em i nie są konfigurowalne: załącznik nie
należy do żadnej kolekcji, więc nie ma zapisanej konfiguracji do odczytania.

### Synchronizacja Google Drive { #google-drive-sync }

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `GOOGLE_DRIVE_CREDENTIALS_FILE` | `credentials/google-drive-sa.json` | Ścieżka do poświadczeń konta serwisowego Google, wyłącznie dla `rag-sync-gdrive` |

**To poświadczenie CLI, a nie fallback dla źródła synchronizacji.** Źródło
synchronizacji `gdrive` nazywa sekret `gcp_service_account` w vaulcie swojej
organizacji i działa na nim albo nie działa wcale: klucz obowiązujący w całym
wdrożeniu, zastępujący brakujący, oznaczał, że `folder_id` tenanta wybierał spośród
tego, co widniało pod kontem serwisowym operatora. Poświadczenie źródła nie jest
ustawieniem ani polem konfiguracji — zobacz [Sekrety i vault](secrets.md).

Plik to klucz konta serwisowego: [konsola Cloud](https://console.cloud.google.com/iam-admin/serviceaccounts)
→ create a service account → Keys → Add key → JSON. Następnie **udostępnij folder
na Drive własnemu adresowi e-mail konta serwisowego** — to taki sam principal jak
każdy inny, a folder, którego nikt mu nie udostępnił, listuje się jako pusty, a nie
jako odrzucony.

### Synchronizacja S3/MinIO { #s3minio-sync }

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `S3_RAG_ENDPOINT` | (none) | URL endpointu S3/MinIO. Źródło synchronizacji może go nadpisać |
| `S3_RAG_ACCESS_KEY` | (empty) | Access key, wyłącznie dla polecenia CLI `rag-sync-s3` |
| `S3_RAG_SECRET_KEY` | (empty) | Secret key, tak samo |
| `S3_RAG_BUCKET` | `agenticos-rag` | Nazwa bucketa |
| `S3_RAG_REGION` | `us-east-1` | Region AWS. Własny region poświadczenia wygrywa tam, gdzie je ma |

**Para kluczy tutaj należy do CLI, a nie do źródła synchronizacji.** Źródło
synchronizacji `s3` nazywa sekret `aws_credentials` w vaulcie swojej organizacji,
tak samo jak źródło `gdrive` nazywa konto serwisowe. Endpoint i region nadal cofają
się do tych ustawień, bo żadne z nich nie nazywa principala — mówią, gdzie jest
magazyn, a nie kto pyta.

## Workspace'y agentów { #agent-workspaces }

Workspace `state` nie potrzebuje tutaj niczego. Jest trzymany w tej bazie danych,
działa na każdym wdrożeniu i jest tym, co agent dostaje domyślnie — więc ustawienia
poniżej dotyczą wyłącznie workspace'u opartego na kontenerze.

| Zmienna | Domyślnie | Uwagi |
|---|---|---|
| `SANDBOX_STATE_MAX_BYTES` | 4 MiB | Na **przechowywany** workspace. Po jego przekroczeniu zapis zostaje odrzucony komunikatem, który czyta model |
| `SANDBOX_INLINE_IMAGE_MAX_BYTES` | 5 MiB | Powyżej tej wartości załączony obraz jest zapisywany do workspace'u i nie jest dodatkowo wysyłany inline |

**Procent w czacie to dwa różne sufity i mówi, który.** Przechowywany workspace
zapełnia się względem `SANDBOX_STATE_MAX_BYTES` powyżej — bajty, a ich wyczerpanie
*odrzuca zapis*. Kontener raportuje rezydentną **pamięć** względem sufitu, który
jego host ustawił dla danego runtime'u, czyli `1g`, o ile allowlista nie mówi
inaczej, a wyczerpanie jej to zabicie przez OOM, a nie odmowa. Dlatego pasek mówi
`workspace 12% full` dla pierwszego i `sandbox memory 12% full` dla drugiego;
raportowanie jednego jako drugiego nazywałoby limit, który nie obowiązuje.

**To, gdzie działają sandboksy, nie jest ustawieniem.** To wiersz na organizację —
Sandboxes w aplikacji, `sandbox_connections` w bazie danych — z tokenem usługi w
vaulcie. Dwa powody, i żadnego z nich nie da się wyrazić zmienną środowiskową:
wdrożenie może trzymać więcej niż jeden host, a jeden adres na wdrożenie dawał
każdej organizacji ten sam; oraz token autoryzuje otwarcie sesji, która uruchamia
polecenia na hoście trzymającym socket Dockera, więc należy tam, gdzie mieszka
każde inne poświadczenie w spoczynku.

Operator rejestruje połączenie z nazwą, adresem i kluczem z vaultu. Agent nazywa
jedno po id, dokładnie tak, jak nazywa profil modelu, albo nie nazywa żadnego i
bierze domyślne dla organizacji — więc przeniesienie na inny host to jedna edycja,
a nie republikacja każdego agenta.

**Token usługi jest wart tyle, ile socket Dockera.** Usługa trzyma ten socket,
socket jest nieuwierzytelnionym API dla roota na hoście, a token jest tym, co
otwiera na nim sesję. Nigdy w przeglądarce, nigdy w logu, nigdy zacommitowany —
dlatego ekran operatora pokazuje tylko to, że poświadczenie jest podpięte, i
dlatego `GET /policy` idzie przez to API, a nie jest pobierane przez przeglądarkę.
Własny dashboard usługi (`SANDBOXD_UI_ENABLED`) jest z tego samego powodu wyłączony
w każdym dostarczanym pliku compose: prosi człowieka, żeby wkleił tę wartość do
przeglądarki.

`SANDBOXD_TOKEN` w `backend/.env` to token *samej usługi* — to, co zaakceptuje
demon z pliku compose.

`make sandbox-token` go generuje, a formularz połączenia zapisuje tę samą wartość w
vaulcie za ciebie. API czyta to ustawienie dokładnie w jednym celu: żeby
zaproponować je vaultowi. Proszenie kogoś, żeby skopiował sekret z pliku, który
jego własny stack i tak już czyta, to tarcie bez niczego za nim.

**Nigdy** nie jest używany do sięgnięcia hosta — rozwiązanie połączenia
odpieczętowuje wpis w vaulcie, który to połączenie nazywa, i to pozostaje jedyną
drogą. Wdrożenie, które zostawi go nieustawionym, traci jeden przycisk i nic
więcej, i wkleja token ręcznie.

Ten sam formularz pyta, czy jakaś usługa już odpowiada, zamiast wymagać od
operatora wiedzy, że usługa sandbox z `make dev` mieszka pod
`http://sandboxd:8080`. Ten adres nie jest konfiguracją i to celowo — jest
wierszem, bo wdrożenie może trzymać kilka hostów — więc API sonduje
nieuwierzytelniony `/healthz` pod adresem, którego używa plik compose tego projektu,
i wstępnie wypełnia to, co odpowiedziało. Nic nie jest rozstrzygane samym pytaniem:
brak usługi to puste pole, a połączenie już tam wskazujące jest nazwane, żeby nikt
nie zarejestrował jednego hosta dwa razy.

**Adres jest pobierany przez to API, więc jest jako adres walidowany.**
Zarejestrowanie albo sondowanie połączenia każe kontenerowi API wysłać
uwierzytelniony `GET` i oddaje z powrotem treść JSON, co jest prymitywem do request
forgery, jeśli adres bierze się na wiarę. Dlatego `base_url` odrzuca wszystko, co
nie jest `http(s)` z hostem, i odrzuca wprost adresy link-local oraz nazwy hostów
metadanych instancji — `169.254.169.254` i `metadata.google.internal` nigdy nie są
usługą sandboksa.

Adresy prywatne pozostają dozwolone i muszą: `http://sandboxd:8080` wewnątrz compose
i `http://localhost:8080` dla developera uruchamiającego API na swoim hoście są
prywatne, więc denylista zakresów prywatnych odrzuciłaby wdrożenie, które opisuje ta
strona. Znaczy to, że walidator zwęża dziurę, zamiast ją zamykać — nazwa hosta,
która rozwiązuje się na coś wewnętrznego, nadal się rozwiąże. **Granicą, która
naprawdę trzyma, jest `connections:manage` plus polityka egress na kontenerze
API**: komu wolno zarejestrować host, temu się ufa, że może, a wdrożenie w sieci
trzymającej nieuwierzytelnione wewnętrzne API powinno powiedzieć to na poziomie
sieci, a nie tutaj.

### O jakie środowiska agent może poprosić { #which-environments-an-agent-may-ask-for }

Dostarczany jest jeden runtime — `workbench` (1,93 GB): Python 3.12, Node 24,
LibreOffice i biblioteki, których agent potrzebuje, żeby czytać, zapisywać,
konwertować i wykreślać pliki, o których jest rozmowa, w tym liteparse z OCR. Jest
zdefiniowany w `backend/app/core/catalog/sandbox_runtimes.json`. Dodanie kolejnego
to edycja tam plus `make sandbox-runtimes`, które wpisuje `SANDBOXD_RUNTIMES` do
wszystkich trzech plików compose; ta zmienna jest jedynym kanałem, którym usługa
przyjmuje runtime'y, a `PUT /policy` celowo odrzuca zmianę składu tej listy.

`sandbox.md#which-environments-an-agent-may-ask-for` opisuje format pole po polu,
trzy pułapki (pierwszy wpis jest domyślny, `network_mode` nie jest dziedziczony, za
build płaci się przy starcie przez `prewarm`) i dlaczego wygenerowana kopia w
plikach compose nie może odjechać od katalogu.

### Własne ustawienia usługi { #the-services-own-settings }

Każde pole konfiguracji usługi to `SANDBOXD_` plus jego nazwa, więc to podzbiór, a
nie słownik. Oto te, które ustawiają dostarczane pliki compose albo które decydują
o tym, czy pliki przetrwają:

| Zmienna | W dostarczanej konfiguracji | O czym decyduje |
|---|---|---|
| `SANDBOXD_WORKSPACE_ROOT` | ścieżka na hoście | Gdzie mieszka katalog roboczy każdej sesji, bind-mountowany z *hosta*. **Nieustawione — pliki istnieją wyłącznie wewnątrz działającego kontenera**: zebranie bezczynnej sesji je wyrzuca, a następne żądanie otwiera pusty workspace, bez śladu w logu. To też jest to, co umożliwia przeglądanie: odczyt workspace'u nigdy nie uruchamia kontenera |
| `SANDBOXD_SANDBOX_UID` | `10001` | Nieuprzywilejowany użytkownik, jako który działa sandbox, zamiast roota — ucieczka z kontenera zaczyna się od tego, jako kto kontener działa, a każdy plik zapisany przez agenta należy na hoście do tego uid. **Musi być własnym uid usługi**: otwarcie sesji robi `chown` workspace'u na tego użytkownika, co nieuprzywilejowana usługa może zrobić tylko dla siebie. Dotyczy runtime'u, który wdrożenie *buduje*, bo gotowy obraz nie ma takiego konta, a agent w środku nie mógłby niczego zainstalować |
| `SANDBOXD_CONTAINER_TTL` | 86400s | Jak długo trzymany jest *zatrzymany* utrwalony kontener. Odzyskuje to, co sesja zainstalowała — build, wheele, `node_modules` — i zostawia workspace nietknięty, bo to pliki są pracą. Nieustawione — trzymane na zawsze |
| `SANDBOXD_PERSIST_CONTAINERS` | `true` | Kontener zamkniętej sesji jest zachowywany, a nie usuwany, więc kolejna sesja tego workspace'u startuje bez builda. Kosztuje jeden zatrzymany kontener na workspace; `SANDBOXD_CONTAINER_TTL` to ogranicza |
| `SANDBOXD_MAX_SESSIONS_PER_TENANT` | `5` | Jedna organizacja nie może zabrać całej puli. `SANDBOXD_MAX_SESSIONS` (20) to pula |
| `SANDBOXD_NETWORK_MODE` | `none` | Domyślna sieć dla sandboksa. `none` to brak sieci w ogóle; runtime może nazwać dla siebie `bridge` |
| `SANDBOXD_UI_ENABLED` | `0` | Własny dashboard usługi. Wyłączony, bo prosi człowieka o wklejenie do przeglądarki tokena równoważnego rootowi |
| `SANDBOXD_IDLE_TIMEOUT` | 1800s | Jak długo żyje bezczynna sesja, zanim zostanie zamknięta i zebrana |
| `SANDBOXD_MEM_LIMIT` | `1g` | Domyślny sufit pamięci, a więc liczba, której udziałem jest procent `sandbox memory` w czacie |

### Uruchamianie usługi na innym hoście { #running-the-service-on-another-host }

Nic w połączeniu nie zakłada lokalnego adresu — to wiersz trzymający URL i
poświadczenie z vaultu, a formularz sonduje to, co dostanie. Host gdzie indziej
potrzebuje trzech rzeczy i żadnego kodu:

1. **Socketa Dockera**, bo usługa startuje kontenery. To root na tamtej maszynie,
   dlatego token poniżej jest wart tyle, ile jest.
2. **`SANDBOXD_WORKSPACE_ROOT` na prawdziwym dysku, zamontowany pod tą samą ścieżką
   po obu stronach.** Usługa tworzy katalog, a potem prosi *demona* o bind-mount, a
   demon rozwiązuje ścieżkę na hoście — więc nazwany wolumen albo ścieżka istniejąca
   wyłącznie wewnątrz kontenera usługi zostaje odrzucona z `mounts denied`.
3. **TLS i token, którego nikt nie współdzieli.** Wewnątrz compose adres to
   `http://sandboxd:8080` w prywatnej sieci; przez internet to usługa, która
   uruchomi polecenia dla każdego, kto trzyma token, więc należy ją schować za HTTPS
   z własną wartością.

Potem zarejestruj go w Sandboxes jak każdy inny i wskaż na niego agenta po nazwie.
Usługa z compose to jedno wdrożenie tego samego obrazu.

### Kiedy sesja jest otwarta { #when-a-session-is-open }

Zakładka **Running** listuje sesje, które trzyma usługa, odświeżana co dziesięć
sekund, a sesja to jeden workspace na jednym hoście. Trzy stany, z czego pojawiają
się tylko dwa pierwsze:

- **running** — kontener istnieje i jest rezydentny. Otwierany przez pierwsze
  wywołanie narzędzia przez agenta w rozmowie, a nie wtedy, gdy rozmowa się zaczyna.
- **hibernated** — wiersz istnieje, a kontener nie. Sesja bezczynna dłużej niż
  `SANDBOXD_EVICT_IDLE_AFTER` jest hibernowana, żeby zwolnić slot, a jej następne
  żądanie ją budzi. Wymaga to `WORKSPACE_ROOT`, bo inaczej obudzenie otworzyłoby
  pusty workspace, więc usługa odrzuca tę kombinację, zamiast tak zrobić.
- **gone** — po `SANDBOXD_IDLE_TIMEOUT` sesja jest zamykana i zbierana. Przy
  `PERSIST_CONTAINERS` kontener to przeżywa, więc następna sesja tego samego
  workspace'u startuje bez builda.

Pusta zakładka Running znaczy więc, że żaden agent ostatnio nie używał shella, a nie
że nic nie jest skonfigurowane — a workspace z plikami i bez sesji to normalny stan
spoczynku.

Usługa działa za profilem compose `sandbox`, który jest domyślnie włączony w
lokalnym devie i wyłączony gdzie indziej, dopóki operator się na niego nie
zdecyduje — montowanie socketu Dockera na współdzielonym hoście jest aktem
świadomym. `COMPOSE_DEV_PROFILES` w Makefile to jedyne miejsce, gdzie się to
zmienia. `uv run agenticos cmd doctor` sonduje każde zarejestrowane połączenie: czy
odpowiada, czy przyjmuje swoje poświadczenie i czy w ogóle dopuszcza jakikolwiek
runtime. Brak zarejestrowanego połączenia to ostrzeżenie, a nie błąd — workspace
`state` nie potrzebuje żadnego.

**Przeglądanie tego, co agenci zachowali.** Workspaces to osobny ekran — nie część
Sandboxes, które są o *hostach*.

Każdy wiersz nazywa agenta, rozmowę, do której należą pliki (albo ile czatów do nich
sięga, dla workspace'u, którego nie posiada żadna pojedyncza rozmowa), kto może je
widzieć, jak jest duży i kiedy był ostatnio używany.

**Open** prowadzi na własną stronę tego workspace'u, w kształcie, którego używa
edytor skilli: drzewo po lewej — foldery przechodzone po jednym, z polem
wyszukiwania obejmującym całe drzewo, a nie folder na ekranie — i sam plik
wyrenderowany obok. Czytanie trzech plików to więc trzy kliknięcia, a lista nigdy
się nie zamyka.

Pobieranie jest przy wierszu, a nie obok czytnika, bo wybranie pliku go odczytuje, a
duże archiwum to coś, czego kopii ktoś chce bez płacenia za to.

Drugi widok na liście spłaszcza każdy plik, który czytelnik może zobaczyć, w jedną
siatkę — odpowiedź na pytanie „kto trzyma kopię tego CSV”, którego strona
pojedynczego workspace'u udzielić nie potrafi.

**Kliknięcie pliku otwiera go w podglądzie, i jest to ten sam podgląd co w panelu
czatu.** Obraz jest obrazem, PDF to własny widok PDF przeglądarki, markdown oferuje
*Preview* i *Source* — oba są plikiem, a `#`, które po cichu stało się dużą czcionką,
to sposób, w jaki ktoś nie zauważa, że jego agent pisze markdown do czegoś, co nie
czyta tego jako markdown — a wszystko inne to jego tekst. Pobieranie jest zawsze
dostępne, także dla tego, czego w ogóle nie da się pokazać. Jeden komponent, bo
„otwórz ten plik” znaczące dwie różne rzeczy na dwóch ekranach to sposób, w jaki
drugiemu z nich zaczyna brakować jakiegoś przypadku.

Bajty pochodzą z `GET /sandbox-workspaces/{id}/raw?path=…` albo z
`GET /conversations/{id}/workspace/raw?path=…` dla panelu obok czatu.

Dwie trasy, a nie jedna, bo autoryzują różnych wołających — trasa rozmowy jest
osiągana przez pobranie rozmowy, więc ktoś, komu czat *udostępniono*, zachowuje
dostęp — i jeden moduł decyduje, co można wyświetlić, żeby odpowiedź nie mogła się
różnić w zależności od powierzchni.

Prawie wszystko jest serwowane jako załącznik. **Obrazy rastrowe i PDF-y** są
serwowane do wyświetlenia: raster, bo nie może się wykonać, a PDF, bo przeglądarka
renderuje go we własnym podglądzie, który nigdy nie dostaje DOM strony.

!!! danger "SVG i HTML są do pobrania i nigdy do wyświetlenia"

    SVG serwowany inline z tego origin to trwały cross-site scripting napisany przez
    cokolwiek, co agent postanowił zapisać, a „agent to napisał” nie jest granicą
    zaufania.

Wszystko inne dostaje typ `application/octet-stream` z
`X-Content-Type-Options: nosniff`, więc przeglądarka nie może uznać, że taka treść
jest jednak HTML-em. Nazwa pliku podróżuje wyłącznie jako `filename*`, bo ścieżka w
workspasie może zawierać dowolny UTF-8, a goła forma nie ma jak tego powiedzieć.

Tylko **przechowywany** workspace może serwować dowolne bajty. Ten oparty na
kontenerze jest czytany przez archiwum workspace'u, którego jedyny czytnik jest
tekstowy, więc plik tekstowy jest serwowany przez zakodowanie go, a cokolwiek innego
zostaje odrzucone, zamiast po cichu zniekształcone — przeglądarka oferuje pobranie
obok odmowy, żeby odpowiedź nigdy nie była ślepą uliczką.

Pliki są czytane tylko wtedy, gdy workspace zostaje otwarty albo gdy włączony jest
widok płaski: wdrożenie może trzymać po jednym na każdą ciepłą rozmowę, więc
czytanie każdego, żeby wyrenderować tabelę, byłoby żądaniem na wiersz dla strony, o
nic jeszcze niepytanej. Widok płaski jest z tego samego powodu ograniczony i mówi o
tym — ile workspace'ów odczytał, ilu nie mógł i czy istnieją kolejne. Krótsza lista
jest inaczej nie do odróżnienia od mniejszej liczby plików.

**Kto widzi który workspace, rozstrzyga się per czytelnik, w zapytaniu.** Wołający
trzymający `connections:manage` widzi workspace'y organizacji — uczciwa poprzeczka
dla listy, która przecina czaty nie jego. Wszyscy pozostali widzą workspace'y,
których są częścią: własne pliki o zasięgu `user`, workspace'y własnych rozmów i
współdzielony workspace agenta, z którym rozmawiali. „Rozmawiali”, a nie „mogliby
otworzyć”, celowo: zasięg `agent` dzieli jeden workspace między użytkowników agenta,
a panel czatu i tak pokazuje te pliki każdemu w rozmowie z nim, więc *możliwość*
otwarcia agenta jest szerszym roszczeniem niż to, które ta lista wypowiada.

Zasięg `channel` jest widoczny wyłącznie dla operatora, co jest poprawne, a nie jest
przeoczeniem — jest kluczowany na czacie Slacka albo Telegrama, więc ludzie, którzy
go dzielą, są identyfikowani przez tamtą platformę, a nie przez wiersz w `users`.

Workspace pobrany po id stosuje te same trzy predykaty i odpowiada **not found**, a
nie forbidden, kiedy zawiodą: id nie może dać się użyć do odkrycia, jakie
workspace'y istnieją w rozmowie kolegi. Nic tutaj nie przecina organizacji — admin
aplikacji przeglądający pliki innego tenanta byłby tym jednym odczytem, który ta
platforma odrzuca, więc przełącza organizację jak każdy inny.

**Workspace oparty na kontenerze jest czytany z wolumenu hosta, a ten musi
istnieć.** Usługa sandboksa serwuje te pliki z `SANDBOXD_WORKSPACE_ROOT` i to
właśnie pozwala rozmowie sprzed miesiąca wylistować swoje pliki po tym, jak jej
sesja została zebrana — żaden kontener nie jest do tego uruchamiany. Usługa
skonfigurowana *bez* niego nie trzyma nic na dysku, więc jej pliki istnieją tylko
dopóki sandbox działa i nie da się ich odczytać bez uruchomienia go: panel Files
mógłby wtedy tylko to powiedzieć, o pliku, który agent demonstracyjnie dopiero co
zapisał.

Każdy plik compose więc go ustawia, z możliwością nadpisania przez
`SANDBOX_WORKSPACE_ROOT` — zmienną środowiskową tam, gdzie compose ją interpoluje,
więc w katalogu głównym projektu, a nie w `backend/.env`, poza celami `dev` i
`prod`, które przekazują ten plik jawnie.

Jedna ścieżka na hoście, bind-mountowana w tym samym miejscu po obu stronach, bo
usługa tworzy katalog, a potem prosi *demona* o zamontowanie go — a demon rozwiązuje
ścieżkę na hoście. Nazwany wolumen albo jakakolwiek ścieżka istniejąca wyłącznie
wewnątrz kontenera usługi zostaje odrzucona z `mounts denied`.

| | Domyślnie | |
|---|---|---|
| Lokalny dev | `/tmp/agenticos-sandbox-workspaces` | Docker Desktop go współdzieli i każdy może do niego pisać, więc laptop nie potrzebuje żadnej konfiguracji |
| Pliki na serwerze | `/var/lib/agenticos/sandbox-workspaces` | Musi istnieć i być zapisywalna dla uid 10001 — `sudo mkdir -p <path> && sudo chown 10001:10001 <path>`, raz. Nie `install -d -o 10001`: `install` rozwiązuje właściciela przez bazę passwd i odrzuca uid, którego nie ma żadne konto. Powinna leżeć na pamięci, którą ktoś backupuje |

Reboot zamiata `/tmp` i to jedyny powód, żeby nie kierować tam prawdziwego
wdrożenia.

To jest raportowane, a nie podnoszone jako wyjątek. Każda lista niesie
`unreadable_reason`, a klient pokazuje to jako wyjaśnienie zamiast jako błąd — bo
żadna z przyczyn nie jest usterką: usługa nietrzymająca niczego na dysku to
konfiguracja z jednolinijkową poprawką, którą komunikat nazywa, a host, który jest
wyłączony, później będzie włączony.

Podnoszenie wyjątku robiło z tego 500, które przeglądarka mogła wyrenderować tylko
jako „coś poszło nie tak”, obok pustej listy, która czyta się jako „nie ma żadnych
plików”. Dwie złe odpowiedzi naraz.

Odczyt *jednego pliku* z takiego hosta zostaje odrzucony tym samym zdaniem, zamiast
zgłoszony jako „nie ma takiego pliku”, co mówiłoby, że pliku brakuje, podczas gdy go
nie brakuje.

**To, co działa, też jest czytane z usługi.**

Ekran Sandboxes trzyma to na własnej zakładce, z dala od tabeli połączeń, i listuje
otwarte sandboksy tej organizacji na hoście, który nazywa — domyślne połączenie,
dopóki operator nie wybierze innego.

Każdy wiersz niesie runtime, to, co dzieli ten sandbox, jego czas bezczynności i
jego pamięć względem własnego sufitu, gdy się o nią zapyta. Sortowalne po czasie
bezczynności i po pamięci. Obok jest log aktywności per sandbox: które ścieżki
odczytano, jakie polecenia uruchomiono i jak każde poszło.

Ani treść plików, ani wyjście poleceń nie są przez usługę zapisywane, i to właśnie
powstrzymuje ślad audytowy przed staniem się sposobem na czytanie pracy cudzego
agenta.

Dashboard odpowiada na te same trzy pytania we własnej sekcji, dla wołającego
trzymającego `connections:manage`. Pamięć jest tam za przełącznikiem z tego samego
powodu co na ekranie: usługa próbkuje dla niej każdy sandbox z osobna.

**Wszystkie trzy sufity teraz dzielą.**

Lista sesji jest filtrowana do organizacji wołającego, ale niesie
`SANDBOXD_MAX_SESSIONS` i `SANDBOXD_MAX_OPEN_SESSIONS` przepuszczone z usługi bez
zmian — więc te dwa liczą każdego tenanta na hoście, podczas gdy wiersze liczą
jednego. `len(sessions)` dzieli się wyłącznie przez
`SANDBOXD_MAX_SESSIONS_PER_TENANT`.

Dlatego odpowiedź niesie dla tej drugiej pary dwa liczniki obejmujące cały host,
wzięte z niefiltrowanej listy, zanim filtr ją zawęzi:

- `host_session_count` — rezydentne sandboksy, które usługa oznacza jako
  `state == "running"`, względem `limit`;
- `host_open_count` — każda istniejąca sesja, rezydentna czy zhibernowana, względem
  `open_limit`.

Teraz karta pojemności może powiedzieć, dlaczego sesja została odrzucona, choć tej
organizacji brakuje do własnego sufitu: to sam host jest pełen cudzej pracy.

To, że te dwie liczby obejmują cały host, jest celowym, wąskim ujawnieniem — dwie
zagregowane liczby całkowite, które nikogo nie nazywają, daleko od wierszy sesji,
które filtr zatrzymuje — a lista jest bramkowana na `connections:view`, uprawnieniu
do obserwowania hosta, a nie uprawnieniu któregokolwiek członka.

Na połączeniu Daytona są `None`, bo ono nie egzekwuje żadnych naszych sufitów, które
można by dzielić.

Ta lista jest **filtrowana, a nie przekazywana dalej**. Jeden `sandboxd` odpowiada
każdej organizacji, która zarejestrowała połączenie pod jego adresem, więc
przepuszczenie jego odpowiedzi pokazałoby jednemu tenantowi kontenery drugiego.
Sesje są dopasowywane po etykiecie `tenant`, którą ta platforma ustawia przy ich
otwieraniu, i nazywane z `agent_workspaces`, a nie przez dekodowanie id sesji — id
koduje klucz zasięgu, a parsowanie go z powrotem zrobiłoby z tego formatu schemat.

**To, na co usługa pozwala, jest czytane z usługi.** Allowlista runtime'ów i sufit
za każdym aliasem (`SANDBOXD_RUNTIMES`, `SANDBOXD_MEM_LIMIT`,
`SANDBOXD_NETWORK_MODE`, `SANDBOXD_MAX_SESSIONS_PER_TENANT` i reszta) to jej własna
konfiguracja startowa i celowo nie ma endpointu do ich zapisu: przeglądarka, która
mogłaby przekonfigurować proces trzymający socket Dockera, miałaby na własność host.
Ekran Sandboxes i karta runtime'ów na dashboardzie oba je *czytają*, żeby widać
było, co obowiązuje, a Builder oferuje agentowi wyłącznie te aliasy, które usługa
naprawdę przyjmie.

Żaden z tych widoków nie pyta połączenia Daytona o nic z tego. Nie publikuje ono
własnej allowlisty i nie trzyma żadnych naszych sesji do wyliczenia — to, na co
pozwala, jest ustawieniem na tamtym koncie, a to, co tam działa, widać w jego
własnym dashboardzie.

## Kanały komunikacyjne { #messaging-channels }

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|

Poświadczenia botów nie są konfigurowane tutaj: każdy bot jest rejestrowany w
aplikacji, a jego token zapieczętowany w vaulcie, przy czym bot Slacka niesie
dodatkowo signing secret własnej aplikacji i token `xapp-` (`SLACK_BOT_TOKEN`,
`SLACK_SIGNING_SECRET` i `SLACK_APP_TOKEN` zostały usunięte — każdy bot jest teraz
własną aplikacją Slacka). URL-e webhooków
Telegrama są budowane z `PUBLIC_BASE_URL` (`TELEGRAM_WEBHOOK_BASE_URL` został
usunięty), profile modeli mogą wskazywać na lokalne endpointy takie jak Ollama bez
żadnej flagi (`ALLOW_INTERNAL_MODEL_ENDPOINTS` zostało usunięte), a limity
sandboksa dla `run_python` są konfiguracją capability per agent
(`CODE_EXECUTION_TIMEOUT_SECS` / `CODE_EXECUTION_MAX_MEMORY_MB` zostały usunięte).

## CORS { #cors }

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `CORS_ORIGINS` | `["http://localhost:3000","http://localhost:8080"]` | Dozwolone originy (tablica JSON) |
| `CORS_ALLOW_CREDENTIALS` | `true` | Zezwalaj na credentials (ciasteczka) |
| `CORS_ALLOW_METHODS` | `["*"]` | Dozwolone metody HTTP |
| `CORS_ALLOW_HEADERS` | `["*"]` | Dozwolone nagłówki HTTP |

Walidacja produkcyjna: `CORS_ORIGINS` nie może zawierać `"*"` przy
`ENVIRONMENT=production`.

## Ograniczanie liczby żądań { #rate-limiting }

Stosowane do powierzchni, do których może sięgnąć obcy, i tylko do nich: publicznego
API runów, skryptu widżetu, jego configu, handshake'u socketu którejkolwiek z tych
powierzchni, configu i logo hostowanej strony oraz uploadu odwiedzającego. Własne
trasy konsoli są za sesją i nie są mierzone — czy całe API powinno nosić sufit, to
osobna decyzja, nie ta.

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `RATE_LIMIT_RUN_PER_MINUTE` | `30` | `POST /api/v1/agents/{id}/run`, na wołającego |
| `RATE_LIMIT_AUTH_PER_MINUTE` | `10` | Każda trasa z `auth.py` — logowanie, rejestracja, odświeżenie, trasy prośby i weryfikacji dla resetu i magic linku. Liczone **per IP oraz, gdy treść go niesie, per przesłany adres**. Zobacz niżej |
| `RATE_LIMIT_EMBED_PER_MINUTE` | `20` | Na adres, i **dwa osobne liczniki tej wielkości**: jeden dla `widget.js`, jeden dla wpuszczenia — `/config` widżetu plus handshake socketu którejkolwiek z powierzchni. Zobacz niżej |
| `RATE_LIMIT_HOSTED_PAGE_PER_MINUTE` | `240` | Config hostowanej strony, **na stronę** — oraz jej logo, na osobnym liczniku. Zobacz niżej |
| `RATE_LIMIT_EMBED_UPLOAD_PER_MINUTE` | `5` | Pliki, które odwiedzający może zapisać na hostowanej stronie. Liczone **na adres i na klucz odwiedzającego**, a pozwolić muszą oba — klucz bije przeglądarka, więc liczenie tylko jego niczego nie ogranicza |
| `RATE_LIMIT_TRUST_FORWARDED_FOR` | `false` | Czy `X-Forwarded-For` nazywa wołającego |

**Co dostaje odrzucony wołający** to własna koperta błędu tego API z
`code: "RATE_LIMIT_EXCEEDED"`, interwałem w `error.details.retry_after_seconds` i
tym samym interwałem w nagłówku `Retry-After` — który jest tym, na którym faktycznie
wycofuje się wrapper fetcha albo CDN. Wyjątkiem jest handshake socketu, bo WebSocket
nie ma statusu, którym mógłby odpowiedzieć: zamyka się kodem `4029` (zobacz
[kanały](channels.md#the-raw-websocket)).

**Dwa liczniki, nie jeden, a powód jest arytmetyczny.**

Załadowanie strony z widżetem kosztuje trzy żądania do tego API: skrypt, config i
socket. Liczone razem, `20` kupowało mniej więcej siedem załadowań strony dla zimnej
przeglądarki, a nie dwadzieścia wpuszczeń — a limit mylny o czynnik trzy jest gorszy
niż brak limitu, bo czyta się jako liczba, którą ustawiłeś.

Dlatego `widget.js` ma własny kubełek. Jest cacheowalny, a odmowa tam psuje widżet
całkowicie, zamiast opóźnić jedną wiadomość.

Config i handshake zostają razem, bo razem *są* jednym wpuszczeniem: przeglądarka,
która przeczytała config i nie otworzyła socketu, nie weszła.

Liczniki żyją w Redisie wdrożenia, więc trzymają się w poprzek workerów — produkcja
uruchamia cztery, a licznik trzymany per proces przepuszczałby czterokrotność tego,
co deklaruje. Jeśli Redis jest nieosiągalny, limit nie jest stosowany, a w logu
ląduje ostrzeżenie: odmówienie odwiedzającemu odpowiedzi, bo cache mrugnął, jest
gorszą z tych dwóch porażek.

To, co odwiedzający może *powiedzieć* po wpuszczeniu, to inna liczba, ustawiana per
widżet w Builderze (`rate_limit_per_minute`) i liczona per odwiedzający. Te dwie są
sufitem na samo wejście.

### `RATE_LIMIT_HOSTED_PAGE_PER_MINUTE` i dlaczego nie jest liczony na adres { #rate_limit_hosted_page_per_minute-and-why-it-is-not-per-address }

Config hostowanej strony jest pobierany **po stronie serwera**, przez frontend, żeby
strona pomalowała się w brandingu już na pierwszej klatce. Znaczy to, że adres w
żądaniu należy do kontenera frontendu, a nie do odwiedzającego — więc liczenie go
wrzucało każde załadowanie hostowanej strony w całym wdrożeniu do jednego kubełka, a
odwiedzający, który go przepełnił, dostawał 404 bez niczego, co by mówiło dlaczego.
`RATE_LIMIT_TRUST_FORWARDED_FOR` nic tu nie pomoże: `fetch` po stronie serwera nie
wysyła takiego nagłówka, któremu ktokolwiek mógłby zaufać.

Dlatego ten jest liczony na klucz publiczny. Ogranicza pojedynczą stronę, zamiast
racjonować odwiedzającego, i dlatego wartość domyślna jest szeroka — **to nie to
ogranicza wydatki.** Wydatki zaczynają się przy sockecie, który strona otwiera w
następnej kolejności, który robi przeglądarka i który jest liczony na adres pod
`RATE_LIMIT_EMBED_PER_MINUTE`. A zgadywanie klucza nie jest strategią przeciwko 192
bitom z `secrets.token_urlsafe`.

### `RATE_LIMIT_AUTH_PER_MINUTE` i dlaczego powierzchnia auth ma własny { #rate_limit_auth_per_minute-and-why-the-auth-surface-has-its-own }

Każda trasa w `auth.py` niesie ten limit, liczony **per IP** oraz — gdy treść niesie
adres (logowanie, rejestracja, prośby o reset i o magic link) — **także per
przesłany adres**, oba w ramach tego samego przydziału. Te dwa zatrzymują różne
ataki: IP ogranicza zalew z jednego źródła, adres ogranicza atak siłowy na jedno
konto.

Jest osobny od przydziału dla runów i niższy od niego, bo broni kosztu
**pojedynczej próby**. `verify_password` to bcrypt, ~170 ms bez punktu zawieszenia,
więc niemierzony zalew `/login` dla dowolnego adresu, który ma konto, nasyca pętlę
zdarzeń workera w ogóle bez żadnych poświadczeń.

Resztę tej powierzchni zamykają jeszcze dwie rzeczy i nie potrzebują żadnej
konfiguracji:

- bcrypt działa w wątku, więc nigdy nie blokuje pętli;
- adres **bez** konta jest weryfikowany względem atrapy hasha, a nie pomijany, więc
  adres znany i nieznany zajmują tyle samo czasu do odmowy, a czas nie mówi już,
  które adresy istnieją.

### `RATE_LIMIT_TRUST_FORWARDED_FOR` i dlaczego jest wyłączony { #rate_limit_trust_forwarded_for-and-why-it-is-off }

Limity na adres liczą `request.client.host`. **Za proxy albo CDN-em jest to adres
proxy, a nie odwiedzającego** — każdy odwiedzający dzieli jeden kubełek, więc
ruchliwa strona za Cloudflare wyczerpuje dwadzieścia wpuszczeń widżetu na minutę dla
wszystkich naraz. Włączenie tego każe czytać zamiast tego **skrajnie prawy**
przeskok z `X-Forwarded-For` — adres, który dopisało samo zaufane proxy.

Jest domyślnie wyłączone, bo nagłówek ustawia ten, kto woła. Zaufany bezwarunkowo,
limit na adres staje się limitem na nagłówek, który każdy obchodzi, zmieniając jeden
ciąg znaków.

**Skrajnie prawy** przeskok jest czytany zamiast skrajnie lewego z tego samego
powodu: `X-Forwarded-For` to lista, którą zaczyna klient i do której dopisuje każde
proxy, więc głowa jest tym, co wpisał klient, a tylko ogon tym, co napisało
kontrolowane przez ciebie proxy.

**Powierzchnia auth też tego potrzebuje, a frontend teraz to umożliwia.** Żądania
auth docierają do API po stronie serwera, przez własne trasy frontendu
`/api/auth/*`, więc bez pomocy adres na nich należy do kontenera frontendu, a
połowa `RATE_LIMIT_AUTH_PER_MINUTE` licząca per IP wrzuca całe wdrożenie do jednego
kubełka — jakieś jedenaście logowań i wszyscy są zablokowani na minutę, a wyczerpany
kubełek odświeżania wylogowuje sesje. W odróżnieniu od pobrania configu hostowanej
strony te trasy **przekazują `X-Forwarded-For` wołającego**
([#1047](https://github.com/vstorm-co/agenticos/issues/1047)), więc z tym ustawieniem
włączonym limit kluczuje na prawdziwym kliencie. Włącz je dla limitu auth na tej
samej zasadzie co wszystko inne — jedno kontrolowane przez ciebie proxy z przodu,
dopisujące klienta jako skrajnie prawy przeskok — czyli decyzja wdrożeniowa, którą
to ustawienie jest; zostawione wyłączone, limit pozostaje bezpieczny, ale
współdzielony.

!!! danger "Włącz to tylko wtedy, gdy jedynym, co może sięgnąć API, jest jedno kontrolowane przez ciebie proxy"

    Jeśli port kontenera jest też opublikowany, wołający może sam ustawić nagłówek i
    limit przestaje cokolwiek znaczyć.

    **Port frontendu liczy się tu jako port API.** Jego trasy `/api/auth/*`
    przekazują dalej dowolny `X-Forwarded-For`, który dostały, więc wołający, który
    potrafi sięgnąć portu 3000 z pominięciem proxy, wybiera adres, na który liczone
    są jego próby logowania, dokładnie tak samo jak ten, kto potrafi sięgnąć portu
    8000 — a każda przyjęta próba na adres, którego nikt nie ma, i tak kosztuje
    jeden bcrypt. Dlatego zarówno `docker-compose-prod.yml`, jak i
    `docker-compose-prod.frontend.yml` publikują domyślnie na `127.0.0.1`, gdzie
    sięga do nich reverse proxy hosta i nic więcej. `BIND_HOST=0.0.0.0` otwiera je z
    powrotem, dla proxy, które naprawdę działa gdzie indziej — z siecią tamtego
    proxy jako tym, co trzyma obietnicę.

    Przy dwóch proxy z przodu zwiń nagłówek do jednego przeskoku na swojej krawędzi
    — wiarygodny jest tylko ostatni przeskok.

## Worker, którego pętla zdarzeń przestała się kręcić { #a-worker-whose-event-loop-has-stopped-turning }

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `EVENT_LOOP_WEDGED_AFTER` | `15` | Ile sekund pętla zdarzeń może się nie kręcić, zanim worker zostanie zabity i zastąpiony. `0` lub mniej wyłącza to sprawdzanie |

Worker, który *żyje, ale nie odpowiada* — zakleszczony na blokadzie, kręcący się w
synchronicznym wywołaniu, zablokowany na sockecie, który nigdy nie odpowie — nie ma
kodu wyjścia, więc każda ścieżka odzyskiwania w każdym stacku czytała go jako
zdrowego, podczas gdy żądania wygasały. Kontener robi się `unhealthy`, a status nie
jest mechanizmem.

Dlatego worker ocenia własną pętlę zdarzeń. Callback timera stempluje pętlę raz na
sekundę; wątek czyta stempel, a jeśli pętla nie obróciła się przez
`EVENT_LOOP_WEDGED_AFTER` w dwóch kolejnych sprawdzeniach, kończy proces —
`SIGKILL` albo `os._exit(137)` tam, gdzie worker jest PID 1, bo jądro nie dostarcza
initowi przestrzeni nazw sygnału, dla którego ten init nie ma handlera. Tak czy
inaczej `docker inspect` raportuje `137`, a „zakleszczony”, czego nic nie
obsługiwało, staje się „nieżywy”, co obsługuje już każdy stack:

| Stack | Co zastępuje workera |
|---|---|
| `docker-compose.yml` | supervisor przeładowania, przy następnym odpytaniu |
| `docker-compose-dev.yml` | PID 1 to serwer, więc kontener kończy pracę i działa `restart: unless-stopped` |
| `docker-compose-prod.yml` | `Multiprocess` uvicorna, w jakieś pół sekundy; pozostałe trzy workery serwują dalej |

Dwie właściwości są powodem tego projektu i obie warto znać, zanim zmieni się tę
liczbę:

- **Mierzy żywotność, a nie gotowość.** Stempel jest callbackiem timera, a nie
  żądaniem, więc wolna baza danych albo provider modelu, który potrzebuje
  dwudziestu sekund, nie jest zakleszczeniem — pętla się kręci, ona czeka. Próba
  HTTP miałaby mniej ruchomych części i wpadałaby w pętlę restartów na zdrowym
  serwerze wobec zepsutej zależności.
- **Dwa sprawdzenia, nie jedno.** `docker pause`, zamrożona cgroupa i laptop
  budzący się ze snu zatrzymują watchdoga tak samo dokładnie jak pętlę, więc
  pierwsze sprawdzenie po czymś takim czyta nieaktualny stempel, który nic nie mówi.

Supervisor przeładowania w lokalnym stacku czyta tę samą zmienną dla oceny, którą
robi z *zewnątrz* workera, więc jedna liczba obejmuje oba.

!!! tip "Ustaw `0` na czas debugowania"

    Breakpoint blokuje pętlę zdarzeń i nic nie odróżni tego od zakleszczenia, więc
    worker, który na nim siedzi, jest inaczej zabijany pod tobą.

Nie widzi procesu, który w ogóle nie działa — `kill -STOP`, zamrożona cgroupa — bo
watchdog wewnątrz zatrzymanego procesu też jest zatrzymany. Ten przypadek pokrywają
już supervisory: bicie supervisora przeładowania staje się nieaktualne, a ping po
pipie w produkcji zostaje bez odpowiedzi.

## Docker / produkcja { #docker-production }

| Zmienna | Domyślnie | Opis |
|----------|---------|-------------|
| `DOMAIN` | `example.com` | Domena produkcyjna (dla Traefika) |
| `ACME_EMAIL` | `admin@example.com` | Adres e-mail dla Let's Encrypt do certyfikatów SSL |
| `REDIS_PASSWORD` | `change-me-in-production` | Hasło Redisa dla produkcji |

## Lista kontrolna przed produkcją { #production-checklist }

!!! danger "Każde z nich jest dostarczane z wartością domyślną, która w produkcji jest zła"

    Wdrożenie osiągalne skądkolwiek indziej ma wszystkie dziewięć ustawione
    świadomie.

- [ ] `SECRET_KEY` — unikalny 64-znakowy klucz hex: `openssl rand -hex 32`
- [ ] `API_KEY` — unikalny klucz: `openssl rand -hex 32`
- [ ] `VAULT_MASTER_KEY` — unikalny klucz: `openssl rand -hex 32`. Konfiguracja
      odrzuca pusty poza `local`/`development`
- [ ] `ENVIRONMENT` — `production`
- [ ] `DEBUG` — `false`
- [ ] `POSTGRES_PASSWORD` — silne, unikalne hasło
- [ ] `REDIS_PASSWORD` — silne hasło
- [ ] `CORS_ORIGINS` — wyłącznie twoje faktyczne domeny frontendu
- [ ] `OPENROUTER_API_KEY` — twój produkcyjny klucz API

E-mail celowo **nie** jest na tej liście: wdrożenie działa bez niego. Ale
zaproszenia, resety haseł i powiadomienia po cichu nie są wysyłane, dopóki
`SMTP_HOST` i reszta z [E-mail (SMTP)](#email-smtp) nie wskażą prawdziwego serwera —
więc wdrożenie, które to pomija, powinno pomijać to świadomie.
