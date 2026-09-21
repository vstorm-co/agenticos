---
source_sha: "0125f6cd20cf"
---

# Virtual Tables { #virtual-tables }

**Virtual table** to typowana tabela rekordów, którą organizacja trzyma dla swoich
agentów, workflow i integracji: zamówienia do uzgodnienia, pliki do przetworzenia,
leady do obsłużenia.

Tabele to metadane plus JSONB. Nic nie tworzy fizycznej tabeli SQL, więc założenie
tabeli kosztuje jeden wiersz, zmiana nazwy kolumny nie zmienia żadnego rekordu, a
żaden tenant nie może rozrastać katalogu bazy danych. Każdy odczyt i zapis przechodzi
przez jeden serwis, `VirtualTableService`, więc konsola, narzędzia agenta, węzły
workflow i publiczne API mają te same reguły. Ta strona opisuje serwis i jego trasy
HTTP pod `/api/v1/tables`; dokument OpenAPI jest ich kontraktem.

## Jak zbudowana jest tabela { #how-a-table-is-built }

| Element | Czym jest | Tożsamość |
|---|---|---|
| **Table** | Nazwa, właściciel, widoczność i grants, jak w [pliku kontekstowym](context.md) | `id`, stałe |
| **Schema version** | Niezmienna migawka kolumn. Zmiana dodaje wersję N+1 | `version` |
| **Column** | Etykieta, typ, informacja czy może być pusta, opcjonalna wartość domyślna | `id`, stałe |
| **Option** | Jeden wybór kolumny typu select | `id`, stałe |
| **Record** | Wartości komórek kluczowane id kolumny, revision i opcjonalny `external_id` | `id`, stałe |

Wartości są kluczowane **id** kolumny, nigdy jej etykietą. Zmiana nazwy przepisuje więc
jedną wersję schematu i żaden rekord. Rekord pamięta wersję schematu, w której był
ostatnio zapisany.

Rekord przechowuje tylko komórki, które mają wartość. Komórka wysłana jako `null`
zostaje wyczyszczona, a odczyt nic dla niej nie pokazuje.

## Typy kolumn { #column-types }

| Typ | Zapisywany jako | Filtry |
|---|---|---|
| `text` | Tekst do 1000 znaków | `eq` `ne` `contains` `starts_with` `in` `is_null` |
| `long_text` | Tekst do 100 000 znaków | tak samo jak `text` |
| `number` | Skończona liczba | `eq` `ne` `lt` `lte` `gt` `gte` `in` `is_null` |
| `integer` | Liczba całkowita, co najwyżej 2^53 - 1 | tak samo jak `number` |
| `boolean` | `true` lub `false` | `eq` `ne` `is_null` |
| `date` | `YYYY-MM-DD` | tak samo jak `number` |
| `datetime` | ISO 8601 ze strefą czasową, zapisywany jako UTC | tak samo jak `number` |
| `single_select` | Id opcji | `eq` `ne` `in` `is_null` |
| `multi_select` | Lista id opcji | `contains` `is_null` |

Tekst jest zapisywany dokładnie tak, jak został wysłany. Spacje na początku i na
końcu, podziały wierszy i wartości złożone z samych spacji to dane użytkownika, więc
nie są przycinane. Obowiązuje tylko limit długości, a znak NUL jest odrzucany, bo
PostgreSQL nie potrafi go zapisać.

Porównania pasują tylko do komórek, które mają wartość. Puste znajdziesz przez `is_null`.

## Zmiana schematu { #changing-a-schema }

`PUT /tables/{id}/schema` przyjmuje pełną listę kolumn, jakie tabela ma mieć, oraz
`expected_version`, czyli wersję, którą wywołujący ostatnio odczytał. Serwis uzgadnia
ją z bieżącymi kolumnami:

- Kolumna z `id` to ta kolumna. Kolumna bez niego jest nowa.
- **Typ kolumny nigdy się nie zmienia**, bo zapisane pod nim wartości przestałyby
  znaczyć to, co znaczyły. Dodaj zamiast tego nową kolumnę.
- Nic nie jest usuwane. Pominięta kolumna lub opcja zostaje **zarchiwizowana**: jej
  wartości pozostają czytelne i filtrowalne, a zapis do niej jest odrzucany kodem
  `ARCHIVED_COLUMN`.
- Nowa kolumna wymagana potrzebuje wartości domyślnej, bo istniejące rekordy nic w
  niej nie mają. Istniejąca kolumna nie może stać się wymagana, dopóki jakikolwiek
  rekord nie ma w niej wartości.
- Nieaktualne `expected_version` to `SCHEMA_VERSION_CONFLICT`.

Rekordy nie są przepisywane. Rekord zapisany w wersji 1 pozostaje czytelny i
edytowalny w wersji 4; wymagana kolumna, której nigdy nie miał, dostaje wartość
domyślną przy najbliższej edycji rekordu.

Archiwizacja kolumny lub całej tabeli najpierw pyta każdy zarejestrowany checker
zależności, czy coś jeszcze z niej korzysta. Workflow, widoki i triggery jeszcze nie
istnieją, więc żaden checker nie jest zarejestrowany i nic nie blokuje;
`app/services/virtual_tables/dependencies.py` to miejsce, w którym funkcja
rejestruje własny, a odmowa wymienia zależności w `SCHEMA_DEPENDENCY`.

## Rekordy i revisions { #records-and-revisions }

Każdy rekord ma `revision`, która zaczyna się od 1 i rośnie z każdą zmianą.

| Operacja | Trasa | Wymaga `expected_revision` |
|---|---|---|
| Utworzenie | `POST /tables/{id}/records` | Nie |
| Zmiana wskazanych komórek | `PATCH /tables/{id}/records/{record_id}` | Tak |
| Usunięcie | `DELETE /tables/{id}/records/{record_id}?expected_revision=` | Tak |
| Upsert | `PUT /tables/{id}/records/by-external-id/{external_id}` | Tylko gdy rekord istnieje |
| Odczyt, exists | `GET .../records/{record_id}`, `.../by-external-id/{external_id}`, `.../exists` | Nie |

Aktualizacja lub usunięcie ze starą revision jest odrzucane kodem `REVISION_CONFLICT`
(409) i `details.current_revision`; nic nie zostaje nadpisane. Odczytaj rekord ponownie
i spróbuj jeszcze raz. Upsert, który znajdzie istniejący rekord i nie dostanie
`expected_revision`, otrzymuje `REVISION_REQUIRED` (428), znów z revision do wysłania.

Równoległe upserty tego samego external id tworzą jeden rekord. Przegrywający go
znajduje i jest obsługiwany jak aktualizacja: potrzebuje revision albo dowiaduje się,
którą wysłać.

Usunięcie jest twarde. Historia rekordu zostaje.

## Bezpieczne ponawianie { #safe-retries }

Każdy zapis rekordu przyjmuje nagłówek `Idempotency-Key` (co najwyżej 128 znaków).
Ponowienie z tym samym kluczem i tą samą treścią zwraca pierwszą odpowiedź, z
`Idempotent-Replayed: true`, i niczego nie zapisuje, nawet jeśli rekord zmienił się w
międzyczasie. Ten sam klucz z inną treścią jest odrzucany kodem
`IDEMPOTENCY_KEY_REUSED`.

Klucz należy do wywołującego i do rodzaju zapisu, więc dwóch wywołujących może użyć
tego samego ciągu, a jeden wywołujący może go użyć do create i do upsert. Zapisywane
są tylko sukcesy: odrzucony zapis nie zostawia potwierdzenia, więc poprawiasz go i
ponawiasz z tym samym kluczem.

Powtórzona odpowiedź trafia tylko do wywołującego, który nadal może edytować tabelę.
Po cofnięciu dostępu to samo ponowienie to 404.

## Listowanie i filtrowanie { #listing-and-filtering }

`GET /tables/{id}/records` przegląda tabelę stronami; `POST /tables/{id}/records/query`
dodaje typowane filtry, z których wszystkie muszą być spełnione. Oba są ograniczone:
`limit` wynosi od 1 do 100, `skip` co najwyżej 10 000, a zapytanie ma co najwyżej 20
filtrów.

Kolejność jest całkowita. Po żądanym sortowaniu (`created_at`, `updated_at` lub
kolumna, którą można sortować) następuje id rekordu, więc strona nigdy nie powtarza ani
nie pomija rekordu w niezmienionej tabeli. Rekordy bez wartości w sortowanej kolumnie
są na końcu w obu kierunkach. Kolumny `multi_select` nie da się sortować.

Nie ma `total`, bo liczenie przefiltrowanej tabeli nie jest tanie. `has_more` mówi, czy
następuje kolejna strona.

## Co zatwierdza się razem { #what-commits-together }

Zapis rekordu, jego wiersz historii, jego potwierdzenie idempotencji i, dla create,
wiersz outbox `table.record.created` są zapisywane w jednej transakcji i zatwierdzane
lub wycofywane razem. Błąd na dowolnym kroku nie zostawia żadnego z nich. Zmiany
tabeli i schematu trafiają do [audit log](governance.md); zmiany rekordów trafiają do
historii per rekord, która przechowuje wartości sprzed i po każdej zmianie.

Wiersz outbox to przekazanie temu, co reaguje na nowy rekord. Na razie nic go nie
konsumuje. Konsument pobiera niedostarczone wiersze we własnej sesji i oznacza je jako
dostarczone.

## Kto co może { #who-can-do-what }

| Permission | Kto ją ma |
|---|---|
| `tables:view` | Owner, admin, builder i operator widzą wszystkie tabele; member i viewer widzą własne, widoczne dla organizacji i udostępnione |
| `tables:edit` | Owner i admin edytują wszystkie; builder edytuje własne i udostępnione; member edytuje własne |
| `tables:create` | Owner, admin, builder, member |

`tables:view` i `tables:edit` to permissions zasobowe, więc [grant](permissions.md) na
jedną tabelę poszerza rolę tylko dla tej tabeli: viewer z `edit` na jednej tabeli
edytuje tę tabelę i nic więcej. Udostępnianie używa tych samych tras
`/tables/{id}/sharing` co inne zasoby współdzielone. Rekordy dziedziczą dostęp swojej
tabeli.

Tabela innej organizacji i tabela, do której wywołujący nie ma dostępu, to w obu
przypadkach 404. Kontekst bez zalogowanego podmiotu nie dociera do niczego.

## Błędy { #errors }

Każda odmowa odpowiada `{"error": {"code", "message", "details"}}`, a `code` jest tym,
według czego klient się rozgałęzia.

| Kod | Status | Znaczenie |
|---|---|---|
| `REVISION_CONFLICT` | 409 | Rekord zmienił się od odczytu |
| `REVISION_REQUIRED` | 428 | Upsert istniejącego rekordu potrzebuje `expected_revision` |
| `SCHEMA_VERSION_CONFLICT` | 409 | Schemat zmienił się od odczytu |
| `SCHEMA_DEPENDENCY` | 409 | Coś zależy od tego, co zmiana usuwa |
| `TABLE_ARCHIVED` | 409 | Tabela odrzuca zapisy |
| `ALREADY_EXISTS` | 409 | Nazwa tabeli lub external id jest zajęte |
| `INVALID_RECORD` | 422 | Wartość nie pasuje do kolumny; `details.fields` wskazuje każdą |
| `ARCHIVED_COLUMN` | 422 | Wartość wskazuje zarchiwizowaną kolumnę |
| `INVALID_QUERY` | 422 | Filtr lub sortowanie, na które tabela nie odpowie |
| `INVALID_SCHEMA` | 422 | Niespójna zmiana schematu |
| `IDEMPOTENCY_KEY_REUSED` | 422 | Klucz został użyty dla innego żądania |
| `NOT_FOUND` | 404 | Nie ma takiej tabeli ani rekordu albo wywołujący nie ma do nich dostępu |

## Wywoływanie serwisu z Pythona { #calling-the-service-from-python }

```python
service = VirtualTableService(db)
table = await service.create_table(ctx, TableCreate(name="Orders", columns=[
    ColumnInput(label="Customer", type="text"),
]))
customer = str(table.columns[0].id)

written = await service.upsert_record(
    ctx, table.id, "ORD-1042", RecordUpsert(values={customer: "Acme"}),
    operation_key="import-2026-09-21-row-17",
)

# Send the revision back to change it; a stale one raises RevisionConflictError.
await service.upsert_record(
    ctx, table.id, "ORD-1042",
    RecordUpsert(values={customer: "Acme Ltd"}, expected_revision=written.record.revision),
)
```

Organizacja zawsze pochodzi z `ctx`, nigdy z argumentu. Serwis nigdy nie robi commit:
robi go sesja żądania, a worker ma własny zakres sesji.

## Jeszcze nie zbudowane { #not-built-yet }

- **Podmiot dla kluczy API.** Dostęp, potwierdzenia i historia wskazują zalogowanego
  użytkownika. Jak klucz API działa na tabeli w zewnętrznym API, ma dopiero zostać
  uzgodnione.
- Narzędzia agenta, węzły workflow i ekrany konsoli, które będą wywoływać ten serwis.
- Konsumenci outbox oraz checkery zależności dla workflow, widoków i triggerów.
