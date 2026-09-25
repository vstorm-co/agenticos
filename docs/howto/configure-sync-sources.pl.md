---
source_sha: "3a2e7c635873"
---

# Konfiguracja źródeł synchronizacji { #configure-sync-sources }

Źródła synchronizacji samodzielnie pobierają dokumenty z usług zewnętrznych
(Google Drive, S3/MinIO, publiczna strona internetowa, repozytorium Git) do kolekcji wiedzy. Każde
źródło przechowuje typ connectora, kolekcję docelową, ustawienia właściwe dla
connectora, tryb synchronizacji, opcjonalny harmonogram oraz id
[sekretu w vault](../secrets.md), który je uwierzytelnia - strona internetowa
żadnego nie potrzebuje.

Gdy synchronizacja się uruchamia, connector wypisuje zdalne pliki, pobiera je do
katalogu tymczasowego i przepuszcza przez standardowy potok przetwarzania
(parsowanie, dzielenie na fragmenty, embedowanie, zapis). Gdy lista jest
kompletna, dokumenty, które źródło wprowadziło wcześniej, a których już nie
wypisuje, zostają usunięte. Wpis `SyncLog` odnotowuje wynik każdej operacji
synchronizacji.

### Architektura w skrócie { #architecture-at-a-glance }

| Komponent | Lokalizacja | Rola |
|-----------|----------|------|
| `BaseSyncConnector` | `app/services/rag/connectors/__init__.py` | Abstrakcyjna baza wszystkich connectorów |
| `RemoteFile` | `app/services/rag/connectors/__init__.py` | Model Pydantic opisujący zdalny plik |
| `CONNECTOR_REGISTRY` | `app/services/rag/connectors/__init__.py` | Mapuje nazwy typów connectorów na klasy |
| `SyncSource` (model DB) | `app/db/models/sync_source.py` | Utrwala konfiguracje źródeł |
| `SyncLog` (model DB) | `app/db/models/sync_log.py` | Śledzi poszczególne operacje synchronizacji |
| `SyncSourceService` | `app/services/sync_source.py` | Logika biznesowa CRUD i wyzwalania |
| Komendy CLI dla RAG | `app/commands/rag.py` | Interfejs CLI do zarządzania źródłami |
| Trasy API dla RAG | `app/api/routes/v1/rag.py` | REST API do zarządzania źródłami |

## Szybki start -- CLI { #quick-start-cli }

### Wypisz dostępne typy connectorów { #list-available-connector-types }

```bash
# Shows all registered connectors (e.g. gdrive, s3, git)
uv run agenticos cmd rag-sources
```

### Dodaj źródło Google Drive -- synchronizacja co 2 godziny { #add-a-google-drive-source-sync-every-2-hours }

```bash
uv run agenticos cmd rag-source-add \
  --name "Legal docs" \
  --type gdrive \
  --org 0c8f2b1e-... \
  --collection legal \
  --config '{"folder_id": "1abc123def", "include_subfolders": true}' \
  --sync-mode new_only \
  --schedule 120
```

### Dodaj źródło S3 -- tylko synchronizacja ręczna { #add-an-s3-source-manual-sync-only }

```bash
uv run agenticos cmd rag-source-add \
  --name "Marketing" \
  --type s3 \
  --org 0c8f2b1e-... \
  --collection marketing \
  --config '{"bucket": "my-docs", "prefix": "marketing/"}' \
  --sync-mode full \
  --schedule 0
```

### Dodaj źródło Git -- dokumentacja repozytorium, co noc { #add-a-git-source-a-repositorys-docs-nightly }

```bash
uv run agenticos cmd rag-source-add \
  --name "Handbook" \
  --type git \
  --org 0c8f2b1e-... \
  --collection handbook \
  --config '{"repository_url": "https://github.com/acme/handbook.git", "branch": "main", "path_prefix": "docs"}' \
  --sync-mode new_only \
  --schedule 1440
```

Następnie wybierz jego token dostępu jako poświadczenie źródła w interfejsie albo
wyślij `secret_id` metodą `PATCH` — zobacz
[Konfiguracja repozytorium Git](#git-repository-setup).

### Wyzwól synchronizację ręcznie { #trigger-sync-manually }

```bash
# Sync a single source by ID
uv run agenticos cmd rag-source-sync <source-id>

# Sync all active sources
uv run agenticos cmd rag-source-sync --all
```

### Usuń źródło { #remove-a-source }

```bash
uv run agenticos cmd rag-source-remove <source-id>
```

`<source-id>` to UUID wypisywany przy tworzeniu źródła i pokazywany na
liście `rag-sources`.

## Szybki start -- interfejs { #quick-start-ui }

1. Przejdź do **Knowledge Base** i otwórz zakładkę **Sync**.
2. Kliknij **"+ Add Source"**.
3. Wybierz typ connectora (Google Drive, S3, Website, Git
   repository). Pola formularza są
   generowane ze schematu JSON Schema z `CONFIG_MODEL` connectora. Strona
   internetowa nie ma kroku poświadczenia.
4. Wypełnij pola konfiguracji właściwe dla connectora (na przykład folder ID,
   nazwę bucketa).
5. Wybierz kolekcję docelową, tryb synchronizacji i interwał harmonogramu.
6. Kliknij **"Create Source"**.
7. Przyciskiem **"Sync Now"** wyzwolisz synchronizację natychmiast albo
   poczekasz, aż harmonogram zadziała sam.

Interfejs wywołuje to samo REST API, które opisano poniżej: cokolwiek zrobisz
w interfejsie, zrobisz też przez `curl` lub dowolnego klienta HTTP.

## Tryby synchronizacji { #sync-modes }

| Tryb | Zachowanie |
|------|----------|
| `full` | Synchronizuje wszystko od nowa. Wszystkie pliki są (ponownie) przetwarzane, istniejące dokumenty zastępowane. |
| `new_only` | Dodaje nowe pliki i aktualizuje zmienione. Zmiany wykrywa po skrócie SHA-256 — pliki bez zmian są pomijane. |
| `update_only` | Aktualizuje wyłącznie pliki już obecne w kolekcji. Nowe pliki są pomijane. Skrót SHA-256 pomija pliki bez zmian. |

!!! tip "`new_only` do większości zastosowań"

    Dodaje nowe pliki i aktualizuje zmienione, pomijając te bez zmian — to
    najszybsza synchronizacja przyrostowa. `update_only` odświeża istniejące
    dokumenty, nie dodając nowych; `full` to za każdym razem czysty import
    od nowa.

### Co usuwa synchronizacja { #what-a-sync-removes }

W każdym trybie synchronizacja usuwa dokumenty, które jej źródło wprowadziło
wcześniej, a których już nie wypisuje: stronę zdjętą z witryny, plik skasowany z
folderu na Drive, obiekt usunięty z bucketa. Log synchronizacji liczy je w polu
`removed`.

Nie usuwa niczego, jeśli lista nie była **kompletna**. Crawl, który zatrzymał się
na limicie stron albo nie zdołał odczytać jednej z nich, nie widział tego, czego
nie wypisuje. Taki przebieg zachowuje wszystkie dokumenty i mówi o tym w
komunikacie logu synchronizacji. Następna synchronizacja z kompletną listą usuwa
to, czego już nie ma. Dokument, którego nie udało się usunąć, liczy się jako
nieudany plik, a następna synchronizacja próbuje ponownie.

Jedno źródło ma naraz tylko jedną synchronizację. Synchronizacja uruchomiona, gdy
inna synchronizacja tego samego źródła wciąż trwa, nie startuje, a jej log mówi o
tym.

Usuwane są wyłącznie dokumenty samego źródła. Przesłany plik ani dokument, który
do tej samej kolekcji wprowadziło inne źródło, nigdy nie są ruszane. Gdy dwa
źródła jednej kolekcji wymieniają ten sam dokument, zostaje on, dopóki oba nie
przestaną go wymieniać. Dokument przetworzony, zanim źródło zaczęło to
odnotowywać (wrzesień 2026), zostaje zachowany, dopóki synchronizacja źródła
znowu go nie wymieni.

### Co robi druga synchronizacja { #what-a-second-sync-does }

Każda synchronizacja po pierwszej robi tak mało, jak pozwala na to źródło:

- **Niezmieniony plik kosztuje pobranie, nie embedowanie.** Jego SHA-256 zgadza
  się ze skrótem zapisanego dokumentu, więc jest liczony jako `skipped` i nigdy
  nie jest ponownie parsowany ani embedowany.
- **Niezmienione źródło kosztuje jedno zapytanie.** Connector, który potrafi
  powiedzieć, w jakim stanie jest cała jego zawartość — w przypadku gałęzi Git
  jest to jej commit na czubku (head) — zapisuje tę wartość po każdym przebiegu,
  który zakończył się bez żadnego błędu. Następny przebieg `new_only` albo
  `update_only`, który zastanie tę samą wartość przy tej samej konfiguracji,
  zatrzymuje się, zanim cokolwiek wypisze: jego log nie pokazuje żadnych
  przetworzonych plików, a przebieg niczego nie usuwa. Zmiana konfiguracji, kolekcji albo trybu sprawia, że
  następny przebieg czyta wszystko od nowa, a `full` nigdy nie kończy się
  wcześniej.
- **Plik, który przerwana synchronizacja zostawiła w połowie, zostaje
  naprawiony.** Worker zatrzymany po zapisaniu wektorów pliku, a przed ich
  odnotowaniem, zostawia je bez śledzącego wiersza. Następna synchronizacja tego
  źródła usuwa to, czego nic nie śledzi, i ponownie przetwarza plik; dopóki taki
  plik czeka, nie kończy się wcześniej.

Przebieg z plikiem, którego nie udało się przetworzyć, nie zapisuje stanu, więc
następny przebieg czyta źródło w całości i ponawia próbę.

## Harmonogram { #schedule }

Pole `schedule_minutes` decyduje, jak często źródło synchronizuje się
samoczynnie:

| Wartość | Znaczenie |
|-------|---------|
| `0` (lub `null`) | Tylko ręcznie -- wyzwalane z CLI lub interfejsu |
| `30` | Co 30 minut |
| `120` | Co 2 godziny |
| `1440` | Raz dziennie |

!!! warning "Harmonogram wymaga runnera Prefect"

    `check_scheduled_syncs_flow` to deployment Prefect, który budzi się co 60
    sekund i uruchamia to, czego termin nadszedł. Bez kontenerów
    `prefect-server` i `prefect-runner`, które startuje `make dev`,
    `schedule_minutes` nie robi nic. Gdy nie działa żaden z nich, cokolwiek
    synchronizuje wyłącznie ręczne wyzwolenie (CLI, API lub interfejs).

## Konfiguracja Google Drive { #google-drive-setup }

### 1. Utwórz konto usługi { #1-create-a-service-account }

1. Wejdź do [Google Cloud Console](https://console.cloud.google.com/).
2. Utwórz nowy projekt (albo wybierz istniejący).
3. Włącz **Google Drive API**.
4. Przejdź do **IAM & Admin > Service Accounts** i utwórz nowe konto
   usługi.
5. Utwórz dla niego klucz JSON i pobierz go.

### 2. Udostępnij folder na Drive { #2-share-your-drive-folder }

1. Otwórz Google Drive i przejdź do folderu, który chcesz synchronizować.
2. Kliknij **Share** i dodaj adres e-mail konta usługi (wygląda tak:
   `name@project.iam.gserviceaccount.com`).
3. Przyznaj co najmniej dostęp **Viewer**.

### 3. Przekaż źródłu klucz { #3-give-the-source-the-key }

Wklej zawartość pliku z kluczem JSON w pole **Service Account JSON** źródła.
Źródło `gdrive` działa na poświadczeniu, które niesie jego własna konfiguracja,
i na niczym innym — nie ma zapasowego poświadczenia obowiązującego dla całego
deploymentu, bo pozwoliłoby ono, żeby `folder_id` źródła decydowało o tym, co
zostanie wypisane spod konta usługi operatora.

`GOOGLE_DRIVE_CREDENTIALS_FILE` w `.env` służy wyłącznie komendzie CLI
`rag-sync-gdrive`.

### 4. Odczytaj folder ID { #4-get-the-folder-id }

Folder ID to ostatni segment adresu URL folderu Google Drive:

```
https://drive.google.com/drive/folders/1abc123def456ghi
                                        ^^^^^^^^^^^^^^^
                                        This is the folder ID
```

### 5. Pola konfiguracji connectora Google Drive { #5-google-drive-connector-config-fields }

| Pole | Typ | Wymagane | Domyślnie | Opis |
|-------|------|----------|---------|-------------|
| `folder_id` | string | Tak | -- | Folder ID Google Drive z adresu URL |
| `include_subfolders` | boolean | Nie | `true` | Rekurencyjnie obejmuje pliki z podfolderów |

Samo konto usługi **nie** jest polem konfiguracji. Dodaj je do vault jako
poświadczenie rodzaju `gcp_service_account` i wskaż je źródłu przez `secret_id`:
zostaje zapisane raz i jest przywoływane przez każde źródło, które go potrzebuje,
zamiast być wklejane do każdego z osobna
([#937](https://github.com/vstorm-co/agenticos/issues/937)). Przesłanie go pod
`config` jest odrzucane.

`folder_id` może zawierać wyłącznie to, co wydaje Google — litery, cyfry, `-`
i `_`. Cokolwiek innego jest odrzucane przy tworzeniu źródła, bo id trafia
przez interpolację do zapytania Drive, a pojedynczy apostrof w nim poszerza
to, co zapytanie wypisuje.

Google Docs, Sheets i Slides są przy pobieraniu samoczynnie eksportowane do
formatów przenośnych (PDF, XLSX, PPTX). Plik, którego nazwa na Drive zawiera
separatory ścieżki, zapisywany jest jako jeden plik wewnątrz katalogu
synchronizacji, nigdy pod ścieżką, którą literuje jego nazwa.

## Konfiguracja S3 / MinIO { #s3-minio-setup }

### 1. Skonfiguruj środowisko { #1-configure-the-environment }

Dodaj do swojego pliku `.env` następujące zmienne:

```bash
S3_RAG_ENDPOINT=https://s3.amazonaws.com   # or your MinIO URL, e.g. http://localhost:9000
S3_RAG_ACCESS_KEY=your-access-key
S3_RAG_SECRET_KEY=your-secret-key
S3_RAG_REGION=us-east-1                    # required for AWS, optional for MinIO
```

W MinIO endpoint ma zwykle postać `http://minio:9000` (Docker) albo
`http://localhost:9000` (lokalnie).

### 2. Pola konfiguracji connectora S3 { #2-s3-connector-config-fields }

| Pole | Typ | Wymagane | Domyślnie | Opis |
|-------|------|----------|---------|-------------|
| `bucket` | string | Tak | -- | Nazwa bucketa S3 |
| `prefix` | string | Nie | `""` | Prefiks kluczy zawężający zakres synchronizacji (np. `documents/legal/`). Zostaw pusty, aby objąć cały bucket. |

## Konfiguracja strony internetowej { #website-setup }

Źródło `web` czyta publiczną stronę internetową, zwykle witrynę z dokumentacją
produktu. Nie potrzebuje poświadczenia ani wpisu w vault. Podaj mu początkowy
adres URL, a będzie albo podążać za linkami z tej strony, albo czytać strony
wypisane w sitemapie.

```bash
uv run agenticos cmd rag-source-add \
  --name "Product docs" \
  --type web \
  --org 0c8f2b1e-... \
  --collection product-docs \
  --config '{"root_url": "https://docs.example.com/guide/", "max_depth": 3}' \
  --sync-mode new_only \
  --schedule 1440
```

### Pola konfiguracji connectora strony internetowej { #website-connector-config-fields }

| Pole | Typ | Wymagane | Domyślnie | Opis |
|-------|------|----------|---------|-------------|
| `root_url` | string | Tak | -- | Strona, od której zaczyna się crawl. Jej host jest jedynym hostem, który źródło czyta. |
| `max_depth` | integer | Nie | `2` | Na ile linków od początkowego adresu URL podążać, od `0` do `10`. `0` czyta tylko stronę początkową. |
| `path_prefix` | string | Nie | folder początkowego adresu URL | Czytane są tylko strony, których ścieżka zaczyna się od tej wartości. `https://docs.example.com/guide/intro` domyślnie czyta `/guide/`; ustaw `/`, aby objąć cały host. |
| `sitemap_url` | string | Nie | -- | Czyta strony wypisane w tej sitemapie zamiast podążać za linkami. Musi leżeć na hoście początkowego adresu URL i używać `https://`, gdy używa go początkowy adres URL. Indeks sitemap jest rozwijany do jego sitemap. |
| `max_pages` | integer | Nie | `500` | Crawl zatrzymuje się po odczytaniu tylu stron, od `1` do `5000`. |

### Co ogranicza crawl { #what-bounds-a-crawl }

- **Jeden host i jedna ścieżka.** Linki do innych hostów i do ścieżek spoza
  `path_prefix` nie są śledzone. Przekierowanie, które je opuszcza, także nie.
  Początkowy adres URL na `https://` nigdy nie jest opuszczany na rzecz
  `http://`: link ani przekierowanie do strony bez szyfrowania nie są śledzone.
- **Sieć deploymentu jest poza zasięgiem.** Każde żądanie - robots.txt, sitemapa,
  każda strona i każde przekierowanie - jest sprawdzane według tej samej polityki
  SSRF co webhooki i serwery MCP. Wysyłane jest na adres, który przeszedł
  sprawdzenie. Początkowy adres URL, który rozwiązuje się na adres prywatny,
  loopback, link-local albo metadanych chmury, jest odrzucany przy zapisie źródła.
- **robots.txt jest przestrzegany** dla sitemap i stron, łącznie z `Crawl-delay`
  do dziesięciu sekund. Crawler przedstawia się jako `AgenticOS-Crawler`. Między
  żądaniami czeka co najmniej pół sekundy, a strona oznaczona `noindex` lub
  `nofollow` jest respektowana. Strona, którą sitemapa wciąż wypisuje, choć jest
  oznaczona `noindex` albo już nie istnieje, jest usuwana z kolekcji.
- **Rozmiar i czas.** Strona większa niż 5 MB nie jest czytana. Crawl zatrzymuje
  się na `max_pages`. Synchronizacja przestaje czytać witrynę po sześciu
  godzinach, a synchronizacja, która się zatrzymała, niczego nie usuwa.

Każda strona jest zapisywana jako dokument Markdown zawierający jej tekst i adres
URL, z którego pochodzi, bez query stringa. Nawigacja, nagłówki, stopki i skrypty są pomijane. Strona
jest embedowana ponownie tylko wtedy, gdy zmieni się jej tekst. Nowy znacznik
builda albo skrypt śledzący w znacznikach HTML nie liczy się jako zmiana.

### Kto może czytać to, co importuje { #who-can-read-what-it-imports }

Źródło strony internetowej nie ma poświadczenia, więc jego zasięg to wszystko, co
strona pokazuje każdemu w internecie. Nigdy nie przechodzi przez logowanie.
Wszystko, co importuje, może przeszukiwać każdy, kto może przeszukiwać zasilaną
przez nie kolekcję, tak jak w przypadku każdego innego źródła. Zobacz
[kto ostatecznie może czytać to, co źródło przetworzyło](../file-processing.md#who-ends-up-able-to-read-what-a-source-ingested).

Importowane są wyłącznie strony HTML. PDF ani inny plik podlinkowany ze strony nie
jest pobierany.

## Konfiguracja repozytorium Git { #git-repository-setup }

Źródło `git` czyta dokumentację repozytorium przez HTTPS — z GitHuba, GitLaba
albo dowolnego innego hosta, który serwuje git przez HTTPS. Potrzebuje adresu
URL do klonowania i tokena dostępu, a nie API którejkolwiek z tych platform.

### 1. Wystaw token dla jednego repozytorium { #1-issue-a-token-for-the-one-repository }

**Zasięg tokena to zasięg źródła.** Wszystko, co źródło przetworzy, staje się
możliwe do przeszukania przez każdego, kto może czytać kolekcję, więc token,
który może czytać każde prywatne repozytorium swojego właściciela, to token,
który może je wszystkie opublikować tym odbiorcom. Zobacz
[kto ostatecznie może czytać to, co przetworzyło
źródło](../file-processing.md#who-ends-up-able-to-read-what-a-source-ingested).

- **GitHub:** fine-grained personal access token, *Only select repositories*,
  z tym jednym repozytorium i **Contents: Read-only** jako jedynym uprawnieniem.
- **GitLab:** project access token w tym jednym projekcie, rola **Reporter**,
  wyłącznie zakres **`read_repository`**.

Nadaj mu datę wygaśnięcia. Gdy wygaśnie, następna synchronizacja źródła kończy
się błędem *the repository refused the source's token*, a naprawą jest nowy
token w tym samym sekrecie w vault.

### 2. Dodaj go do vault { #2-add-it-to-the-vault }

Dodaj token do vault jako **Git access token**, razem z **hostem**, do którego
należy: `github.com`, `gitlab.com` albo własny serwer, na przykład
`git.example.com:8443`. Host z literami spoza ASCII wpisuje się w postaci
zakodowanej, na przykład `xn--bcher-kva.example` dla `bücher.example`. Potem
wybierz token w kroku poświadczenia źródła. Jest
wysyłany jako nagłówek HTTP `Authorization`, nigdy w adresie URL i nigdy
w wierszu poleceń, który mógłby odczytać inny proces.

**Host należy do tokena, nie do źródła.** Adres URL repozytorium wybiera ten,
kto edytuje źródło, a token jest wysyłany wyłącznie do hosta, z którym został
dodany. Edycja źródła nie może więc skierować tokena organizacji na inny serwer,
a żadnego innego rodzaju klucza, na przykład klucza API dostawcy modelu, nie da
się w ogóle wybrać dla źródła Git.

### 3. Pola konfiguracji connectora Git { #3-git-connector-config-fields }

| Pole | Typ | Wymagane | Domyślnie | Opis |
|-------|------|----------|---------|-------------|
| `repository_url` | string | Tak | -- | Adres URL klonowania przez HTTPS, np. `https://github.com/acme/handbook.git`. Bez nazwy użytkownika i tokena. |
| `branch` | string | Nie | `main` | Gałąź do odczytu. |
| `path_prefix` | string | Nie | -- | Katalog wewnątrz repozytorium, np. `docs`. Zostaw pusty, aby objąć całe repozytorium. |
| `include` | lista stringów | Nie | `**/*.md`, `**/*.txt` | Które pliki przetwarzać, jako wzorce w stylu `.gitignore` względem `path_prefix`. |

Domyślnie jest to dokumentacja, a nie całe drzewo: kod źródłowy repozytorium nie
jest korpusem, a jego przetworzenie wypełnia bazę wiedzy kodem, którego nikt nie
chciał przeszukiwać. Dodaj wzorzec taki jak `**/*.pdf` dla innego formatu, który
czyta parser kolekcji. Wzorzec nie może zaczynać się od `!`.

Każdy plik jest dokumentem o adresie
`git://<host>/<owner>/<repo>@<branch>/<path>`, z `:<port>` po hoście, gdy port
nie jest 443. Gałąź jest częścią adresu, więc dwa źródła czytające dwie gałęzie
jednego repozytorium do jednej kolekcji mają osobne dokumenty.

### 4. Co przesyła synchronizacja { #4-what-a-sync-transfers }

Pierwszym zapytaniem każdej synchronizacji jest `git ls-remote` dla gałęzi —
około kilobajta. Gdy commit na czubku gałęzi nie przesunął się od ostatniego
czystego przebiegu, synchronizacja na tym się kończy. Gdy się przesunął,
connector wykonuje płytki, częściowy i rzadki (sparse) klon: jeden commit
i wyłącznie pliki pasujące do wzorców `include`. Dokumentacja monorepo kosztuje
więc tyle, co dokumentacja, a nie całe drzewo źródeł.

Zanim klon zapisze cokolwiek na dysk workera, connector mierzy każdy plik, który
by zapisał. Plik większy niż limit dokumentu bazy wiedzy (`MAX_UPLOAD_SIZE_MB`,
domyślnie 50 MB) albo łącznie ponad 512 MB plików zostaje odrzucony i nic nie
jest zapisywane.

Dowiązania symboliczne i submoduły nie są śledzone, a dowiązanie nie jest
przetwarzane jako dokument.

### Reguły sieciowe { #network-rules }

Adres URL musi zaczynać się od `https://`. Jego host jest rozwiązywany raz
i sprawdzany tak jak każdy inny adres wybrany przez tenanta: host, który
rozwiązuje się na adres prywatny, loopback albo link-local, jest odrzucany przy
zapisie źródła i ponownie przy synchronizacji, a git łączy się wyłącznie
z adresami, które ta kontrola zatwierdziła. Przekierowania nie są śledzone.
Deployment za proxy wyjściowym (`HTTPS_PROXY`) nadal z niego korzysta; proxy
rozwiązuje wtedy host samo.

Obraz workera zawiera `git`. Worker zbudowany z innego obrazu potrzebuje `git`
w wersji 2.37 lub nowszej na swoim `PATH`.

## Dokumentacja API { #api-reference }

Wszystkie endpointy źródeł synchronizacji leżą pod `/api/v1/rag/sync/`.
Wypisanie listy wymaga `collections:view`, a wszystko, co zmienia źródło, wymaga
`collections:edit` — w obu przypadkach wobec kolekcji, do której źródło należy;
rola administratora w tym nie występuje. Zobacz
[kto może sięgnąć do kolekcji](../file-processing.md#who-may-reach-a-collection).

### CRUD źródeł synchronizacji { #sync-sources-crud }

| Metoda | Endpoint | Opis |
|--------|----------|-------------|
| `GET` | `/api/v1/rag/sync/sources` | Wypisuje wszystkie skonfigurowane źródła synchronizacji |
| `POST` | `/api/v1/rag/sync/sources` | Tworzy nowe źródło synchronizacji |
| `PATCH` | `/api/v1/rag/sync/sources/{id}` | Zmienia istniejące źródło synchronizacji |
| `DELETE` | `/api/v1/rag/sync/sources/{id}` | Usuwa źródło synchronizacji |
| `POST` | `/api/v1/rag/sync/sources/{id}/trigger` | Ręcznie wyzwala synchronizację |

### Connectory i logi { #connectors-logs }

| Metoda | Endpoint | Opis |
|--------|----------|-------------|
| `GET` | `/api/v1/rag/sync/connectors` | Wypisuje dostępne typy connectorów wraz ze schematami konfiguracji |
| `GET` | `/api/v1/rag/sync/logs` | Wypisuje historię synchronizacji (filtrowaną po `collection_name`) |

### Przykład: utworzenie źródła przez API { #example-create-a-source-via-api }

```bash
curl -X POST http://localhost:8000/api/v1/rag/sync/sources \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Legal Drive",
    "connector_type": "gdrive",
    "collection_name": "legal",
    "config": {
      "folder_id": "1abc123def",
      "include_subfolders": true
    },
    "sync_mode": "new_only",
    "schedule_minutes": 120
  }'
```

### Przykład: wyzwolenie synchronizacji przez API { #example-trigger-a-sync-via-api }

```bash
curl -X POST http://localhost:8000/api/v1/rag/sync/sources/{source_id}/trigger \
  -H "Authorization: Bearer $TOKEN"
```

### Przykład: sprawdzenie historii synchronizacji { #example-check-sync-history }

```bash
curl http://localhost:8000/api/v1/rag/sync/logs?limit=10 \
  -H "Authorization: Bearer $TOKEN"
```

### Przykład: wykrycie dostępnych connectorów { #example-discover-available-connectors }

```bash
curl http://localhost:8000/api/v1/rag/sync/connectors \
  -H "Authorization: Bearer $TOKEN"
```

Odpowiedź zawiera `config_schema` każdego connectora, na podstawie którego
frontend renderuje dynamiczne formularze. Przydaje się też przy programowym
budowaniu integracji.

## Zmiana źródła { #updating-a-source }

Metodą `PATCH` możesz zmienić dowolny podzbiór pól istniejącego źródła:

```bash
curl -X PATCH http://localhost:8000/api/v1/rag/sync/sources/{source_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sync_mode": "full",
    "schedule_minutes": 60,
    "is_active": false
  }'
```

Pola, które można zmienić: `name`, `config`, `sync_mode`, `schedule_minutes`,
`is_active`, `collection_name`.

Ustaw `is_active` na `false`, aby wstrzymać źródło bez usuwania go.

## Monitorowanie operacji synchronizacji { #monitoring-sync-operations }

Każda synchronizacja tworzy wpis `SyncLog` z następującymi polami:

| Pole | Opis |
|-------|-------------|
| `source` | Typ connectora albo `"local"` dla przetwarzania z CLI |
| `collection_name` | Kolekcja docelowa |
| `status` | `running`, `done` albo `error` |
| `mode` | `full`, `new_only` albo `update_only` |
| `total_files` | Liczba znalezionych plików |
| `ingested` | Poprawnie przetworzone (nowe) |
| `updated` | Poprawnie przetworzone ponownie (zastąpione) |
| `skipped` | Pominięte (już obecne lub bez zmian) |
| `failed` | Nieudane przetworzenie, łącznie ze stronami lub plikami, których lista nie zdołała odczytać, oraz dokumentami, których nie udało się usunąć |
| `removed` | Usunięte, bo źródło już ich nie wypisuje (zobacz [co usuwa synchronizacja](#what-a-sync-removes)) |
| `error_message` | Co poszło nie tak albo dlaczego nic nie usunięto. Przebieg może mieć status `done` i mimo to komunikat, na przykład gdy crawl zatrzymał się na limicie stron |
| `started_at` | Kiedy synchronizacja się zaczęła |
| `completed_at` | Kiedy synchronizacja się skończyła |

Logi obejrzysz w wyjściu CLI albo przez API:

```bash
curl http://localhost:8000/api/v1/rag/sync/logs?collection_name=legal&limit=5 \
  -H "Authorization: Bearer $TOKEN"
```

## Dodawanie własnych connectorów { #adding-custom-connectors }

Aby dodać nowy typ connectora (na przykład Notion, Confluence, Dropbox), zobacz
[Dodaj connector synchronizacji](./add-sync-connector.md).

W skrócie:

1. Utwórz klasę dziedziczącą po `BaseSyncConnector` w
   `app/services/rag/connectors/`.
2. Zaimplementuj `list_files()`, `_fetch()` i opcjonalnie `validate_config()`.
3. Zadeklaruj `SECRET_KIND` — rodzaj sekretu w vault, który go uwierzytelnia —
   oraz `CONFIG_MODEL`, model Pydantic mówiący, jak odnaleźć dokumenty.
   Poświadczenie nigdy nie jest jednym z jego pól.
4. Zarejestruj go w `CONNECTOR_REGISTRY` w
   `app/services/rag/connectors/__init__.py`.

Po zarejestrowaniu connector pojawia się samoczynnie w CLI, API i w
interfejsie.

## Rozwiązywanie problemów { #troubleshooting }

### "No sync sources configured" { #no-sync-sources-configured }

Nie utworzono jeszcze żadnego źródła. Utwórz je poleceniem `rag-source-add`
(CLI) albo `POST /api/v1/rag/sync/sources` (API).

### "Unknown connector type" { #unknown-connector-type }

Podany typ connectora nie występuje w `CONNECTOR_REGISTRY`. Sprawdź dostępne
typy poleceniem `rag-sources` albo `GET /api/v1/rag/sync/connectors`.
Google Drive (`gdrive`) jest dostępny.
S3 (`s3`) jest dostępny.
Strona internetowa (`web`) jest dostępna.
Git (`git`) jest dostępny.

### Google Drive: "this source has no credential" { #google-drive-this-source-has-no-credential }

Pole `secret_id` źródła jest puste albo sekret w vault, który wskazywało,
został usunięty. Dodaj JSON konta usługi do vault i wybierz go w kroku
poświadczenia źródła — `GOOGLE_DRIVE_CREDENTIALS_FILE` go nie zastępuje,
a to ustawienie czyta wyłącznie komenda CLI `rag-sync-gdrive`.

### "A Google Drive source needs a service account credential" { #a-google-drive-source-needs-a-service-account-credential }

`secret_id` wskazuje poświadczenie niewłaściwego rodzaju — na przykład parę
kluczy AWS. Źródło Drive przyjmuje `gcp_service_account`, a źródło S3 parę
`aws_credentials`; kreator proponuje wyłącznie pasujące, więc ten przypadek
osiągalny jest przez API.

### Google Drive: "folder ID may contain only letters, digits, '-' and '\_'" { #google-drive-folder-id-may-contain-only-letters-digits-and-_ }

Wartość nie jest identyfikatorem folderu Drive. Weź ją z adresu URL folderu:
to ostatni segment, a nic innego z tego adresu do tego pola nie należy.

### Google Drive: "Cannot access folder" { #google-drive-cannot-access-folder }

Upewnij się, że udostępniono folder adresowi e-mail konta usługi. Konto usługi
potrzebuje co najmniej dostępu Viewer.

### S3: "Cannot access bucket" { #s3-cannot-access-bucket }

Sprawdź, czy `S3_RAG_ACCESS_KEY`, `S3_RAG_SECRET_KEY` i `S3_RAG_ENDPOINT` są
poprawnie ustawione w `.env`. W MinIO upewnij się, że endpoint zawiera port
(na przykład `http://localhost:9000`).

### Website: "resolves to private/internal address" { #website-resolves-to-privateinternal-address }

Początkowy adres URL albo sitemapa wskazuje do wnętrza sieci deploymentu albo
jego nazwa się tam rozwiązuje. Źródło strony internetowej czyta wyłącznie adresy
publiczne. Aby zaindeksować wewnętrzną witrynę, opublikuj jej strony gdzieś
publicznie albo prześlij pliki bezpośrednio.

### Website: "The site's robots.txt could not be read, so it was not crawled" { #website-the-sites-robotstxt-could-not-be-read-so-it-was-not-crawled }

`/robots.txt` na hoście początkowego adresu URL trzy razy z rzędu przekroczył
limit czasu albo odpowiedział błędem serwera (5xx). Crawler nie zgaduje, na co
pozwoliłby nieosiągalny robots.txt, więc przebieg się zatrzymuje. Brakujący
robots.txt (404) albo zabroniony (403) oznacza brak reguł i crawl rusza.

### Website: "The start URL … did not lead to an HTML page" { #website-the-start-url-did-not-lead-to-an-html-page }

Początkowy adres URL odpowiedział 404, przekierował na inny host albo poza
`path_prefix`, albo zwrócił coś innego niż HTML. Otwórz go w przeglądarce, a
potem użyj adresu, pod którym się kończy, jako `root_url`.

### Website: "robots.txt does not allow the start URL" { #website-robotstxt-does-not-allow-the-start-url }

Witryna prosi crawlery, by trzymały się z dala od tej ścieżki. Wybierz początkowy
adres URL, na który witryna pozwala, albo poproś jej właściciela o dopuszczenie
`AgenticOS-Crawler`.

### Website: "… answered HTTP 403" or "… could not be reached" { #website-answered-http-403-or-could-not-be-reached }

Strona wymaga logowania albo witryna odmówiła crawlerowi. Jeśli odpowiedzią był
przekroczony limit czasu, 429 albo 5xx, strona zawiodła po trzech próbach. Każda
taka strona liczy się jako nieudany plik. W tym przebiegu nic nie jest usuwane, bo
strony za nią nie zostały zobaczone.

### "The source could not be listed completely, so documents it may no longer hold were kept" { #the-source-could-not-be-listed-completely-so-documents-it-may-no-longer-hold-were-kept }

Lista urwała się przed końcem: crawl osiągnął `max_pages` albo części stron nie
udało się odczytać. To, co znaleziono, zostało przetworzone, a nic nie usunięto.
Zwiększ `max_pages` albo zawęź crawl przez `path_prefix`, aż przebieg skończy się
bez tego komunikatu.

### Git: "The repository refused the source's token" { #git-the-repository-refused-the-sources-token }

Token wygasł, został unieważniony albo nie może czytać tego repozytorium. Wystaw
nowy zgodnie z opisem w [Konfiguracja repozytorium Git](#git-repository-setup)
i podmień wartość sekretu w vault, którego używa źródło; każde źródło korzystające
z tego sekretu pobierze ją przy następnej synchronizacji.

### Git: "The repository was not found, or the source's token cannot see it" { #git-the-repository-was-not-found-or-the-sources-token-cannot-see-it }

Najpierw sprawdź adres URL klonowania. Prywatne repozytorium odpowiada tokenowi,
który nie może go czytać, *not found* zamiast *forbidden*, więc fine-grained
token wystawiony dla innego repozytorium wygląda właśnie tak.

### Git: "The repository has no branch named …" { #git-the-repository-has-no-branch-named }

Pole `branch` wskazuje gałąź, której repozytorium nie ma. Domyślnie jest to
`main`; w starszym repozytorium gałęzią domyślną może być `master`.

### Git: "… is … MB, and a synced file may be at most … MB" { #git-is-mb-and-a-synced-file-may-be-at-most-mb }

Plik pasujący do wzorców `include` jest większy niż limit dokumentu bazy wiedzy.
Zawęź `include` albo `path_prefix` tak, by ten plik został pominięty. W tej
synchronizacji nic nie zostało zapisane.

### Git: "… over the … MB one sync may check out" { #git-over-the-mb-one-sync-may-check-out }

Wszystkie pliki pasujące do wzorców `include` mają łącznie ponad 512 MB. Zawęź
`include` albo `path_prefix` albo podziel repozytorium na kilka źródeł, każde
z własnym prefiksem.

### Git: "This token was added for …, and the repository is on …" { #git-this-token-was-added-for-and-the-repository-is-on }

Repozytorium źródła jest na innym hoście niż ten, z którym dodano jego token.
Albo adres URL jest błędny, albo źródło potrzebuje tokena dodanego dla tego
hosta. Do hosta repozytorium nic nie zostało wysłane.

### Git: "A Git source needs a Git access token" { #git-a-git-source-needs-a-git-access-token }

Źródło wskazuje sekret innego rodzaju, na przykład API key. Dodaj token jako
**Git access token**, razem z jego hostem, i wybierz właśnie ten.

### "Another sync of this source is still running" { #another-sync-of-this-source-is-still-running }

Przebieg został wyzwolony, gdy trwał inny przebieg tego samego źródła, więc nie
wystartował. Trwający przebieg kończy się normalnie; wyzwól synchronizację
ponownie po nim, jeśli źródło w międzyczasie się zmieniło.

### Git: "… resolves to a private address" { #git-resolves-to-a-private-address }

Host repozytorium rozwiązuje się na adres wewnątrz sieci deploymentu, więc
źródło jest odrzucane. Źródło synchronizacji nie może dotrzeć do
samodzielnie hostowanego serwera Git pod adresem wewnętrznym.

### Git: "git is not installed on this worker" { #git-git-is-not-installed-on-this-worker }

Worker działa z obrazu bez `git`. Dostarczany `backend/Dockerfile` go instaluje;
do własnego obrazu trzeba go dodać.

### Git: synchronizacja zakończyła się bez przetworzonych plików { #git-a-sync-finished-with-no-files-processed }

Commit na czubku gałęzi jest tym samym, który przeczytał ostatni czysty
przebieg, przy tej samej konfiguracji, więc nie było nic do zrobienia. Przełącz
źródło na `full` na jeden przebieg, aby mimo to przeczytać wszystko od nowa.

### Zaplanowane synchronizacje nie działają { #scheduled-syncs-are-not-running }

Musi działać system zadań w tle. Sprawdź, czy proces workera jest aktywny:

Bez workera zadziałają wyłącznie ręczne wyzwolenia z CLI lub API.
