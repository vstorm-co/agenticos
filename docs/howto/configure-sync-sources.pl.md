---
source_sha: "482d37ce9407"
---

# Konfiguracja źródeł synchronizacji { #configure-sync-sources }

Źródła synchronizacji samodzielnie pobierają dokumenty z usług zewnętrznych
(Google Drive, S3/MinIO) do kolekcji wiedzy. Każde źródło przechowuje typ
connectora, kolekcję docelową, ustawienia właściwe dla connectora, tryb
synchronizacji, opcjonalny harmonogram oraz id
[sekretu w vault](../secrets.md), który je uwierzytelnia.

Gdy synchronizacja się uruchamia, connector wypisuje zdalne pliki, pobiera je do
katalogu tymczasowego i przepuszcza przez standardowy potok przetwarzania
(parsowanie, dzielenie na fragmenty, embedowanie, zapis). Wpis `SyncLog`
odnotowuje wynik każdej operacji synchronizacji.

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
# Shows all registered connectors (e.g. gdrive, s3)
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
3. Wybierz typ connectora (Google Drive, S3). Pola formularza są
   generowane ze schematu JSON Schema z `CONFIG_MODEL` connectora.
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
| `failed` | Nieudane przetworzenie |
| `error_message` | Szczegóły błędu (gdy `status` to `error`) |
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

### Zaplanowane synchronizacje nie działają { #scheduled-syncs-are-not-running }

Musi działać system zadań w tle. Sprawdź, czy proces workera jest aktywny:

Bez workera zadziałają wyłącznie ręczne wyzwolenia z CLI lub API.
