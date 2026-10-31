---
source_sha: "07d0e3bf20fc"
---

# Virtual Tables { #virtual-tables }

**Virtual table** to typowana tabela rekordów, którą organizacja trzyma dla swoich
agentów, [workflow](workflows.md) i integracji: zamówienia do uzgodnienia, pliki do przetworzenia,
leady do obsłużenia.

Tabele to metadane plus JSONB. Nic nie tworzy fizycznej tabeli SQL, więc założenie
tabeli kosztuje jeden wiersz, zmiana nazwy kolumny nie zmienia żadnego rekordu, a
żaden tenant nie może rozrastać katalogu bazy danych. Każdy odczyt i zapis przechodzi
przez jeden serwis, `VirtualTableService`, więc konsola, narzędzia agenta, węzły
workflow i publiczne API mają te same reguły. Ta strona opisuje serwis i jego trasy
HTTP pod `/api/v1/tables`; dokument OpenAPI jest ich kontraktem.


Obszar tabeli domyślnie wypełnia dostępne miejsce, bez przycisku rozszerzania. Panel rekordu ma osobny przycisk **Full screen**, który powiększa wszystkie pola bez utraty edycji; **Exit full screen** przywraca panel boczny. Wiersze leżą bezpośrednio pod paskiem, bez drugiej ramki i pustego panelu z marginesami. Katalog wypełnia dostępną wysokość strony, ma własny przycisk pełnego ekranu i pokazuje paginację dopiero przy wielu stronach.

Każda tabela pokazuje zablokowane pola `created_at`, `updated_at`, `created_by` i `updated_by` z rekordu. To te same właściwości, które są nad Markdownem, a nie edytowalne kopie w komórkach. Przed pierwszą aktualizacją `updated_at` pokazuje datę utworzenia. Pola pozostają widoczne po ukryciu kolumn użytkownika. Ich nazwy są zarezerwowane przy dodawaniu i zmianie nazw kolumn; istniejące starsze nazwy pozostają czytelne.

Typowaną **Wartość domyślną** ustawisz w ustawieniach lub przy dodawaniu kolumny. Nowe rekordy używają jej tylko po pominięciu pola; jawna wartość lub null ma pierwszeństwo. Domyślne opcje select mogą przy wysyłaniu schematu wskazywać ID albo etykiety; serwer zapisuje ID. Kolor opcji wybierzesz na liście opcji; **Automatyczny** zachowuje dotychczasową paletę. Zmiana koloru zachowuje identyfikatory i rewizję znaczenia kolumny.

Szybkie dodawanie jest bezpośrednio za załadowanymi wierszami, w ich obszarze przewijania. Eksport CSV w konsoli zawiera cztery właściwości rekordu. Eksport API zachowuje dotychczasowy format, chyba że podasz `include_metadata: true`. Przy tworzeniu tabeli z eksportowanego CSV pola systemowe są pomijane; importowane rekordy dostają nowe metadane systemowe.

## Klienci zewnętrzni { #external-clients }

Źródło zapisu jest rejestrowane oddzielnie od osoby udzielającej uprawnień. Nowe zapisy przechowują `created_source` i `updated_source`: rodzaj, identyfikator i nazwę osoby, agenta, klucza API, workflow lub systemu. Konsola pokazuje avatar osoby, portret agenta albo ikonę API/workflow obok nazwy w kolumnach systemowych i właściwościach dokumentu. Utworzenie ustawia oba źródła; późniejsze zapisy zachowują twórcę. Starsze rekordy zachowują zapisaną osobę bez zgadywania historycznego źródła. Tych pól nie można ustawić przez dane rekordu ani Markdown.

Klucze API organizacji działają na `/api/v1/tables`. Wyślij
`Authorization: Bearer aos_…`; organizacja pochodzi z klucza. Odczyt wymaga
`tables:view`, zapis rekordów i schematu `tables:edit`, a utworzenie tabeli
`tables:create`. Obowiązują zarówno bieżący dostęp wystawcy, jak i zakres klucza.
Historia i potwierdzenia wskazują wystawcę; klucz nie rozszerza jego dostępu.
Niedostępna tabela zwraca `404`, brak uprawnienia kolekcji `403`, stara rewizja `409`,
a nieprawidłowe zapytanie lub rekord `422`. Ponowiony zapis z tym samym
`Idempotency-Key` i treścią zwraca pierwotny wynik bez kolejnego zdarzenia utworzenia.

`POST /api/v1/tables/{id}/records/query` przyjmuje `columns` (do 100 identyfikatorów
aktywnych kolumn) obok filtrów, sortowania, skip i limit. Odpowiedź zawiera tylko
wybrane komórki i etykiety powiązań. `null` zachowuje cały rekord; `[]` zwraca tylko
metadane. Kolumny obliczane są wyliczane przed projekcją, więc ich zależności nie
muszą być wybrane. Te same rekordy od razu widać w konsoli; asynchroniczne uruchomienie
wyzwalacza tabeli nie opóźnia odpowiedzi CRUD.

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
zostaje wyczyszczona, a odczyt nic dla niej nie pokazuje. Przy create wartość domyślna
kolumny wypełnia tylko komórki, które pominiesz; komórka wysłana jako `null` zostaje
pusta.

## Typy kolumn { #column-types }

| Typ | Zapisywany jako | Filtry |
|---|---|---|
| `text` | Tekst do 1000 znaków | `eq` `ne` `contains` `starts_with` `in` `is_null` |
| `long_text` | Tekst do 100 000 znaków | tak samo jak `text` |
| `rich_text` | Źródło Markdown do 100 000 znaków | tak samo jak `text` |
| `email` | Adres z jednym `@` i kropką w domenie, do 254 znaków | tak samo jak `text` |
| `url` | Adres `http` lub `https` z hostem, do 2048 znaków | tak samo jak `text` |
| `phone` | Cyfry, spacje i `+ ( ) - . /`, co najmniej pięć cyfr | tak samo jak `text` |
| `number` | Skończona liczba | `eq` `ne` `lt` `lte` `gt` `gte` `in` `is_null` |
| `integer` | Liczba całkowita, co najwyżej 2^53 - 1 | tak samo jak `number` |
| `rating` | Liczba całkowita od 1 do 5 | tak samo jak `number` |
| `boolean` | `true` lub `false` | `eq` `ne` `is_null` |
| `date` | `YYYY-MM-DD` | tak samo jak `number` |
| `datetime` | ISO 8601 ze strefą czasową, zapisywany jako UTC | tak samo jak `number` |
| `single_select` | Id opcji | `eq` `ne` `in` `is_null` |
| `multi_select` | Lista id opcji | `contains` `is_null` |
| `link` | Lista do 100 id rekordów tabeli, z którą łączy | `contains` (id rekordu) `is_null` |
| `lookup`, `rollup` | Nic: wyliczane przy odczycie rekordu | brak |
| `formula` | Nic: wyliczana z pozostałych kolumn rekordu przy odczycie | brak |

Tekst jest zapisywany dokładnie tak, jak został wysłany. Spacje na początku i na
końcu, podziały wierszy i wartości złożone z samych spacji to dane użytkownika, więc
nie są przycinane. Obowiązuje tylko limit długości, a znak NUL jest odrzucany, w komórkach i tak samo w nazwach, etykietach, opisach i
external id, bo PostgreSQL nie potrafi go zapisać.

Porównania pasują tylko do komórek, które mają wartość. Puste znajdziesz przez `is_null`.
`contains` i `starts_with` przyjmują fragment wartości, więc `@example.com` znajdzie
w kolumnie `email` adresy w tej domenie.

Narzędzia tabel agenta i kroki tabel w workflow nazywają wybór etykietą opcji,
bez rozróżniania wielkości liter: po etykiecie zapisują i filtrują, a wybory rekordu
odczytują jako etykiety, także opcji zarchiwizowanej. Wartość, która nie wskazuje
żadnej aktywnej opcji, jest odrzucana wraz z listą opcji kolumny.

### Tekst formatowany i Markdown { #rich-text }

Wybierz **Rich text (Markdown)** dla notatek z nagłówkami, listami, zadaniami, tabelami, linkami i kodem. Kliknięcie komórki otwiera rekord. **Write** oferuje pole dokumentu i pasek pogrubienia, kursywy, linków, obrazów i filmów. **Preview** używa renderera czatu dla linków i obrazów; bezpośrednie linki HTTP(S) do MP4, WebM lub Ogg stają się filmami z kontrolkami, bez autoodtwarzania. Surowy HTML nie jest wykonywany. **Expand editor** otwiera większy obszar pracy. Zapisane dokumenty zaczynają od podglądu; **Write** przełącza do edycji.

Kanban pokazuje kartę pod kursorem i docelową kolumnę, animuje przejście i od razu przenosi kartę na czas zapisu. Odmowa zapisu przywraca poprzednią kolumnę i zachowuje obsługę konfliktu. Menu Move to pozostaje dostępne z klawiatury.

Właściwości dokumentu są nad edytorem Markdown. **Utworzono**, **Ostatnia zmiana** i **Autor** pochodzą z rekordu i nie można ich zmienić przez Markdown. Data ostatniej zmiany uwzględnia zapis całego rekordu, także innych komórek; przed pierwszą zmianą pokazuje datę utworzenia.

Właściwości dokumentu przechowuj w typowanych kolumnach tabeli. Edytor Markdown nie dodaje ani nie edytuje już właściwości YAML. Nowe szablony notatnika zawierają tylko Markdown. Dotychczasowe nagłówki importowanych dokumentów są zachowywane podczas edycji treści, aby nie utracić danych historycznych. Automatyczne daty i tożsamości autorów nadal pochodzą z rekordu.

Domyślny szablon dokumentu wybierzesz przy tworzeniu kolumny rich text lub w **Columns**. Dostępne są pusty dokument, notatka, spotkanie i opis projektu; treść można dostosować. Szablon korzysta z istniejącego `default` kolumny: konsola, API i workflow stosują go przy tworzeniu, jeśli pominięto komórkę. Jawnie podana wartość, także pusty tekst, ma pierwszeństwo. Zmiana szablonu wpływa wyłącznie na nowe rekordy. **Użyj szablonu kolumny** zastępuje treść istniejącego dokumentu po potwierdzeniu i zachowuje właściwości. Zapytania tekstowe i konwersje działają jak wcześniej.

## Powiązania, odczyty i podsumowania { #links-lookups-and-rollups }

Kolumna `link` przechowuje rekordy innej tabeli albo tej samej, wskazanej przez
`link_table_id`. Zapis sprawdza, czy każdy rekord istnieje w tej tabeli i czy
zapisujący ją widzi, więc powiązanie nie pozwala sprawdzić, jakie id ma
prywatna tabela. Rekord zwraca swoje powiązania nazwane, w `links`, pierwszą
wartością tekstową każdego powiązanego rekordu, a w drugiej kolejności jego
zewnętrznym id. Powiązany rekord usunięty w międzyczasie po prostu znika.

`lookup` czyta jedną kolumnę powiązanych rekordów przez kolumnę powiązania tej
samej tabeli (`link_column_id`, `target_column_id`): wartości, a wybór po
etykiecie. `rollup` coś z nich wylicza: `count` powiązań albo `sum`, `avg`, `min`
lub `max` kolumny liczb - `min` i `max` także dat. Obie są wyliczane przy
odczycie rekordu i nigdy nie są zapisywane, filtrowane ani sortowane.

To, co pokazuje odczyt, nie sięga dalej niż czytelnik: powiązana tabela, której
czytelnik nie widzi, zostawia powiązania bez nazw, a każdy odczyt i każde
podsumowanie przez nie puste. Powiązanie zachowuje swoją tabelę na zawsze.
Odczyt czyta kolumnę z wartościami, nie inne powiązanie ani odczyt, a
archiwizacja kolumny powiązania jest odrzucana, dopóki czyta przez nią odczyt
lub podsumowanie. Eksport zapisuje powiązanie nazwami jego rekordów, a odczyt
tym, co przeczytał.

## Formuły { #formulas }

Kolumna `formula` wylicza wartość z pozostałych kolumn rekordu:
`{Price} * {Quantity}`, `IF({Total} > 100, "large", "small")`,
`ROUND({Total} / {Count}, 2)`, `DAYS({Due}, TODAY())`. Kolumnę wskazuje się jej
etykietą w nawiasach klamrowych, a zmiana nazwy przepisuje każdą formułę, która ją
wskazuje. Formuła liczy przez `+ - * / %`, porównuje przez `= <> < <= > >=`, łączy
warunki przez `and`, `or` i `not` oraz wywołuje `IF`, `ROUND`, `ABS`, `MIN`, `MAX`,
`CONCAT`, `LEN`, `UPPER`, `LOWER`, `DAYS` i `TODAY`. Wybór czyta się jego etykietą.

Może czytać każdą żywą kolumnę z wartościami, także wynik odczytu lub
podsumowania, ale nie powiązanie ani inną formułę, a kolumny czytanej przez
formułę nie można zarchiwizować. Zapis schematu sprawdza formułę i mówi, co jest
w niej nie tak. Wartość, której nie da się wyliczyć - dzielenie przez zero, tekst
w sumie, pusta komórka - zostawia komórkę tego rekordu pustą. Formuła jest
wyliczana przy odczycie rekordu, jak odczyt z powiązania, i nigdy nie jest
zapisywana, filtrowana ani sortowana.

## Zmiana schematu { #changing-a-schema }

`PUT /tables/{id}/schema` przyjmuje pełną listę kolumn, jakie tabela ma mieć, oraz
`expected_version`, czyli wersję, którą wywołujący ostatnio odczytał. Serwis uzgadnia
ją z bieżącymi kolumnami:

- Kolumna z `id` to ta kolumna. Kolumna bez niego jest nowa.
- **Typ kolumny zmienia się tylko na taki, jako który dają się odczytać jej
  wartości**, a zmiana przepisuje wartość w każdym rekordzie. Każda wartość staje się
  tekstem; tekst staje się liczbą, tak/nie, datą albo pojedynczym wyborem, gdy to
  mówi - wybór dostaje opcję na każdą inną wartość; liczba całkowita staje się liczbą
  i z powrotem, gdy jest całkowita; data staje się datą z czasem; jeden wybór staje się
  kilkoma i z powrotem, gdy jest jeden. Każda inna zmiana jest odrzucana, podobnie jak
  taka, której któraś wartość nie przetrwa - z liczbą i przykładem, a nic nie zostaje
  zapisane. Coś, co używa kolumny, odrzuca zmianę tak jak archiwizację. Rewizja rekordu
  idzie dalej, więc edycja według starej wartości jest konfliktem.
- Tekst staje się kolumną `email`, `url`, `phone` lub `rating`, gdy każda wartość
  się nią czyta, a liczba staje się oceną, gdy jest liczbą całkowitą od 1 do 5. Każda
  z nich wraca do tekstu, a ocena także do liczby.
- Nic nie jest usuwane. Pominięta kolumna lub opcja zostaje **zarchiwizowana**: jej
  wartości pozostają czytelne i filtrowalne, a zapis do niej jest odrzucany kodem
  `ARCHIVED_COLUMN`.
- Zarchiwizowane liczą się do limitów. Tabela ma co najwyżej 100 kolumn, a kolumna typu
  select co najwyżej 100 opcji, wliczając zarchiwizowane. Zmiana, która przekroczyłaby
  któryś, jest odrzucana kodem `INVALID_SCHEMA` i nie dodaje wersji, więc nie można
  zastąpić pełnej listy opcji; dodaj zamiast tego nową kolumnę.
- Nowa kolumna wymagana potrzebuje wartości domyślnej, bo istniejące rekordy nic w
  niej nie mają. Istniejąca kolumna nie może stać się wymagana, dopóki jakikolwiek
  rekord nie ma w niej wartości, a wymagana kolumna nie może wrócić z archiwum bez
  wartości domyślnej, bo rekordy zapisane w czasie archiwizacji nie mogły jej mieć.
- Nieaktualne `expected_version` to `SCHEMA_VERSION_CONFLICT`.
- Zgłoszenie identyczne z bieżącymi kolumnami, z tymi samymi id, kolejnością, etykietami i
  opcjami, nie zmienia niczego: nie powstaje wersja, a zwracana jest bieżąca tabela.
  Zmiana kolejności lub etykiety jest zmianą.

Rekordy nie są przepisywane. Rekord zapisany w wersji 1 pozostaje czytelny i
edytowalny w wersji 4; wymagana kolumna, której nigdy nie miał, dostaje wartość
domyślną przy najbliższej edycji rekordu.

Każda kolumna ma tylko do odczytu **`revision`**, równe `0` dla nowej kolumny i dla
każdej kolumny, która istniała, zanim je dodano. Zlicza zmiany tego, co wartości
kolumny *oznaczają*, żeby opublikowana [strona](artifacts.md#live-data) mogła
rozpoznać, że kolumna, względem której ją opublikowano, nie jest już tą samą. Rośnie o jeden przy:

- konwersji typu;
- zmianie formuły, porównywanej po tym, jak przez nią przepisano zmianę nazwy, więc
  zmiana nazwy kolumny, którą czyta formuła, się nie liczy, ale przejęcie etykiety przez
  inną kolumnę tak;
- innym celu linku, lookupu albo rollupu, albo innym agregacie;
- archiwizacji albo przywróceniu kolumny, albo archiwizacji albo przywróceniu jednej z jej opcji wyboru.

Nowa etykieta, wartość domyślna czy wymaganie, zmiana etykiety opcji wyboru i nowa
opcja zostawiają je bez zmian. Filtr trzyma id opcji, więc żadna z tych zmian nie
zmienia tego, co filtr dopasowuje. Kolumnę `TableRead` można odesłać w zmianie schematu
tak, jak przyszła: pole jest przyjmowane i ignorowane, a ustawia je dopiero sama zmiana.

Zapis rekordu oraz zmiana schematu lub archiwizacja tej samej tabeli czekają na siebie:
zapis czeka na trwającą zmianę i jest potem oceniany według tego, co ona zatwierdziła,
więc rekord nigdy nie trafia do tabeli zarchiwizowanej chwilę wcześniej.

Archiwizacja kolumny lub całej tabeli najpierw pyta każdy zarejestrowany checker
zależności, czy coś, co wywołujący może zarówno zobaczyć, jak i zmienić, jeszcze z
niej korzysta. Zapisane widoki (zobacz [Zapisane widoki](#saved-views)) i workflow,
które czytają lub zapisują tabelę, rejestrują swoje w
`app/services/virtual_tables/dependencies.py`, podobnie wyzwalacze tabeli, które
blokują każdego, kto archiwizuje: wyzwalacz filtrujący po kolumnie, której już nie ma,
wróciłby zepsuty.

Odmowa wymienia każdą zależność w `SCHEMA_DEPENDENCY` z jej `kind`,
`id` i `name`, a `name` jest null dla wyzwalacza w workflow, którego wywołujący nie
może otworzyć. Konsola pokazuje je w dialogu, który pytał, workflow jako link do
niego. Każda inna zależność nigdy nie jest wymieniana i nigdy nie blokuje
wywołującego: jej funkcja sama radzi sobie ze zmianą.

## Archiwizacja i przywracanie tabeli { #archiving-a-table }

Tabela nigdy nie jest usuwana; jest archiwizowana. Zarchiwizowana tabela zachowuje
rekordy, kolumny, widoki i historię, a każdy odczyt nadal działa. Każdy zapis jest
odrzucany kodem `TABLE_ARCHIVED`, niezależnie od tego, kto pyta: żaden rekord nie
powstaje, nie zmienia się ani nie znika, a jej nazwa i kolumny też się nie zmieniają.
Jej nazwa jest wolna dla nowej tabeli, a ona sama nadal wlicza się do
[limitu tabel](#limits-and-retention) organizacji.

W konsoli członek, który może edytować tabelę, znajdzie **Archive table** w menu
**More actions** na jej stronie. Dialog mówi, co robi archiwizacja, zanim cokolwiek
się zmieni. Opublikowany workflow, który nadal czyta lub zapisuje tabelę i który
wywołujący może edytować, odrzuca archiwizację kodem `SCHEMA_DEPENDENCY`, a dialog
pokazuje go jako link. Zapisane widoki i wyzwalacze blokują tylko archiwizację kolumny.

Strona zarchiwizowanej tabeli mówi, kiedy ją zarchiwizowano. Dla członka, który może
edytować tabelę, komunikat zawiera **Restore**, które przywraca ją pod jej nazwą;
każdy inny czyta jej rekordy i dowiaduje się, kto może ją przywrócić. Katalog pokazuje
aktywne tabele, dopóki nad nim nie wybierze się **Archived included**, a karta
zarchiwizowanej tabeli mówi, że jest zarchiwizowana.

| Akcja | Trasa | Kod odmowy |
|---|---|---|
| Archiwizacja | `POST /tables/{id}/archive` | `SCHEMA_DEPENDENCY` (409), gdy coś używa tabeli. Ponowna archiwizacja nie jest błędem |
| Przywrócenie | `POST /tables/{id}/unarchive` | `BAD_REQUEST` (400), gdy tabela nie jest zarchiwizowana; `ALREADY_EXISTS` (409), gdy w międzyczasie aktywna tabela zajęła jej nazwę |

Obie wymagają prawa do edycji tej tabeli, z roli lub z grantu na nią, a każdy inny
dostaje 404. `can_edit` jest false dla zarchiwizowanej tabeli, więc to
`TableRead.can_restore` mówi, czy ten wywołujący może ją przywrócić. Każda trafia do
audytu, jako `table.archived` i `table.unarchived`, i liczy się do limitu
częstotliwości zapisów tabel. Nazwę zajętą w międzyczasie zmienia się
najpierw w aktywnej tabeli, bo zarchiwizowanej nie można przemianować.

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

External id ma od 1 do 255 znaków i może zawierać `/`, jak w `2026/ORD-1`. Nie może zawierać NUL ani znaku nowego wiersza. Serwis sprawdza to
tak samo jak trasy. Przez HTTP trasa odrzuca to pierwsza, kodem `VALIDATION_ERROR`;
wywołujący, który używa serwisu bezpośrednio, dostaje `INVALID_RECORD`.

Równoległe upserty tego samego external id tworzą jeden rekord. Przegrywający go
znajduje i jest obsługiwany jak aktualizacja: potrzebuje revision albo dowiaduje się,
którą wysłać.

Aktualizacja, która zostawiłaby każdą komórkę bez zmian, nie zmienia niczego. Revision
zostaje, nie powstaje wiersz historii ani receipt, a zwracany jest bieżący rekord.
Nieaktualne `expected_revision` to nadal konflikt, bo jest sprawdzane najpierw. Upsert,
który znajdzie rekord, podlega tej samej regule.

Usunięcie jest twarde. Historia rekordu zostaje, dopóki nie usunie jej retencja.

## Edycja rekordów w konsoli { #editing-in-the-console }

Katalog oraz widoki Table, Kanban i List mają wspólny panel z wyszukiwaniem i zapisanymi widokami. **Add record** używa dwóch kolumn na większym ekranie i jednej na telefonie; długi tekst i powiązania zachowują pełną szerokość. Panel rekordu korzysta ze wspólnej obsługi klawiatury i fokusu konsoli. **Columns** zwija istniejące opcje wyboru pod ich liczbą. Błąd pobierania rekordów daje **Retry**.

Karty katalogu mówią, ile rekordów i aktywnych kolumn ma każda tabela, kto ma do niej
dostęp i kiedy ostatnio się zmieniła. Na stronie tabeli każdy nagłówek pokazuje typ
kolumny ikoną, liczby są wyrównane do prawej, a daty zapisane tak, jak zapisuje je
twój język. Panel rekordu ma w tytule pierwszą kolumnę rekordu i mówi, kiedy go dodano
i kiedy ostatnio zmieniono.

Członek, który może edytować tabelę, dodaje, zmienia i usuwa rekordy z jej strony.
**Add record** prosi o wartość dla każdej aktywnej kolumny, w typie tej kolumny.
Kolumna wymagana i bez wartości domyślnej jest oznaczona `*` i trzeba ją wypełnić,
zanim rekord zostanie zapisany; każda inna pusta kolumna przyjmuje wartość domyślną.
Kliknięcie komórki edytuje ją w miejscu: Enter lub kliknięcie obok zapisuje, Escape
zostawia ją bez zmian, a pole tak/nie, które nie może być puste, przełącza się jednym
kliknięciem. Strzałki przenoszą między komórkami, a przycisk rozwinięcia na końcu
wiersza otwiera cały rekord.

Linia pod siatką dodaje rekordy podczas pisania: to, co wpiszesz, trafia do pierwszej
kolumny tekstowej, a Enter tworzy rekord i zostawia linię gotową na następny. Tabela z
inną wymaganą kolumną otwiera zamiast tego **Add record** z wpisaną wartością, więc
nic nie zostaje zapisane, dopóki nie ma wszystkich wymaganych wartości.

Każda edycja to jeden `PATCH` względem rewizji widocznej na ekranie, więc edycja, która
przegrywa z nowszą zmianą, zostaje odrzucona, a nie zapisana na niej. Rekord otwiera się
wtedy z odrzuconą wartością zachowaną obok **Reload and reapply**. Zaznaczenie wierszy
udostępnia **Delete** dla wszystkich naraz, każdy względem własnej rewizji: rekord,
który ktoś w międzyczasie zmienił, zostaje, a konsola mówi, ile takich było. Panel
rekordu usuwa pojedynczy rekord w ten sam sposób.

Usunięcie czeka kilka sekund z
**Undo** w komunikacie, zanim zostanie wysłane; rekordy od razu znikają ze wszystkich
widoków, a Undo przywraca je nietknięte. Członek, który może tylko oglądać
tabelę, widzi tę samą siatkę tylko do odczytu, a kliknięcie wiersza otwiera rekord.

Członkowi, który może edytować tabelę, nagłówek kolumny otwiera menu. **Sort ascending**
i **Sort descending** sortują siatkę według niej, a **Hide in this view** zdejmuje ją z
ekranu, dopóki przycisk ukrytych kolumn nie pokaże jej z powrotem; **Save view**
zapisuje jedno i drugie. **Rename** i **Archive column** zmieniają tabelę dla wszystkich,
każda jako ta sama nowa wersja schematu, którą zapisałby dialog Columns, a archiwizacja
czegoś, co jest jeszcze używane, zostaje odrzucona, a workflow, widoki i wyzwalacze
pojawiają się w dialogu. **+** za ostatnią
kolumną dodaje nową, na początek opcjonalną. Typ kolumny zmienia się w **Columns**, na
typy, na które dają się przekonwertować jej wartości.

W **Columns** przełącznik **Required** sprawia, że kolumna wymaga wartości, a
zarchiwizowana kolumna trafia do **Archived columns**, skąd **Restore** przywraca ją
razem z jej wartościami.

### Import i eksport { #import-and-export }

Eksport odczytuje najwyżej 4 MiB rozwiniętego JSON rekordów na stronę (albo jeden
rekord), maksymalnie 500 rekordów naraz. Organizacja może przesyłać jeden eksport
jednocześnie i rozpoczynać dziesięć na minutę. Kolejne żądania zwracają `429` z
`Retry-After`; ponów je po tym czasie. Bez Redis limit rozpoczęć zachowuje minimum
w każdym procesie; baza nadal wymusza jeden eksport na organizację naraz.
Jeden kursor serwera utrzymuje spójny snapshot rekordów eksportu, pobierając z
wyprzedzeniem najwyżej cztery rekordy. Zamyka się po zakończeniu lub anulowaniu;
kolejne strony nie skanują ponownie wcześniejszych rekordów.

**Export**, w menu **…** obok **Share**, zapisuje to, co pokazuje strona, jako plik CSV: rekordy pasujące do filtrów
i wyszukiwania, w kolejności siatki, w jej widocznych kolumnach. `POST
/tables/{id}/records/export` robi to samo dla wywołującego, z tymi samymi filtrami,
wyszukiwaniem, sortowaniem i listą `columns`. Opcja jest zapisywana jako jej etykieta,
kilka jako `a; b`, a komórka tekstowa, którą arkusz odczytałby jako formułę, zaczyna
się od `'`. Ponad 100 000 pasujących rekordów jest odrzucane z `EXPORT_TOO_LARGE` (413).

**Import**, w tym samym menu, czyta plik CSV rozdzielany przecinkiem lub średnikiem, którego pierwszy
wiersz nazywa kolumny. Każda kolumna pliku jest dopasowana do kolumny tabeli o tej
samej nazwie albo do **External id** i można ją skierować gdzie indziej lub pominąć.
Wartość, której nie da się odczytać w typie kolumny, odrzuca swój wiersz, zanim cokolwiek
zostanie wysłane. Reszta trafia po 200 do `POST /tables/{id}/records/batch`, który
zapisuje każdy rekord osobno i wymienia odrzucone z ich kodami, a konsola wypisuje każdy
nieudany wiersz z numerem linii. Każdy dodany rekord uruchamia wyzwalacze tabeli, jak
każdy inny.

Gdy zmapowane jest **External id**, **Update records already here** importuje plik
ponownie, żeby zaktualizować tabelę: wiersz, którego zewnętrzne id tabela już ma, zmienia
wskazane komórki tego rekordu zamiast zostać odrzucony jako zajęty (`update_existing` w
partii), a import podaje, ile dodał i ile zaktualizował.

**New table** zaczyna się od kolumny **Name**. Najpierw podaj nazwę tabeli i jej kolumny; opis oraz widoczność są pod **More options**, z domyślną widocznością prywatną. Zamiast tego może zacząć się od pliku:
**Start from a CSV file** zamienia nagłówek na kolumny i daje każdej najwęższy typ, w którym dają się odczytać
wszystkie jej wartości - liczba całkowita, liczba, tak/nie, data, data i godzina
w ISO, adres e-mail albo link - a w przeciwnym razie tekst lub długi tekst, gdy wartość ma podział wiersza albo
przekracza 1000 znaków. Nazwa pochodzi z pliku i obie rzeczy można zmienić przed
utworzeniem, co kosztuje mniej niż późniejsza zmiana typu. Gdy tabela już istnieje, import
otwiera się z każdą kolumną już przypisaną, a po nim otwiera się tabela.

## Bezpieczne ponawianie { #safe-retries }

Każdy zapis rekordu przyjmuje nagłówek `Idempotency-Key` (co najwyżej 128 znaków).
Ponowienie z tym samym kluczem i tą samą treścią zwraca pierwszą odpowiedź, z
`Idempotent-Replayed: true`, i niczego nie zapisuje, nawet jeśli rekord zmienił się w
międzyczasie. Ten sam klucz z inną treścią jest odrzucany kodem
`IDEMPOTENCY_KEY_REUSED`.

Nagłówek oznacza powtórzone create, update lub upsert. Powtórzone usunięcie odpowiada 204
jak za pierwszym razem i nie jest oznaczane.

Klucz należy do wywołującego i do rodzaju zapisu, więc dwóch wywołujących może użyć
tego samego ciągu, a jeden wywołujący może go użyć do create i do upsert. Zapisywane
są tylko sukcesy: odrzucony zapis nie zostawia potwierdzenia, więc poprawiasz go i
ponawiasz z tym samym kluczem.

Powtórzona odpowiedź trafia tylko do wywołującego, który nadal może edytować tabelę.
Po cofnięciu dostępu to samo ponowienie to 404.

Receipt trwa 24 godziny. Potem klucz jest zapominany, a ten sam klucz z tą samą treścią to
nowy zapis: wykonuje się ponownie, zamiast zwrócić pierwszą odpowiedź. Ponawiaj w tym
oknie, a dłuższą przerwę traktuj jak nowe żądanie. Czas życia jest egzekwowany w chwili użycia
klucza, więc obowiązuje co do godziny; codzienny sweep tylko odzyskuje miejsce po receipts,
których nikt nie ponowił.

## Listowanie i filtrowanie { #listing-and-filtering }

`GET /tables/{id}/records` przegląda tabelę stronami; `POST /tables/{id}/records/query`
dodaje typowane filtry, z których wszystkie muszą być spełnione. Oba są ograniczone:
`limit` wynosi od 1 do 100, `skip` co najwyżej 10 000, a zapytanie ma co najwyżej 20
filtrów.

`search` to tekst, który rekord musi zawierać, bez względu na wielkość liter, w dowolnej
aktywnej kolumnie tekstowej lub długiego tekstu albo w etykiecie opcji wyboru, którą
przechowuje. Łączy się z filtrami, a puste wyszukiwanie niczego nie szuka. Zapisany
widok przechowuje je obok swoich filtrów. W konsoli wysyła je pole wyszukiwania, a
**Filter** zapisuje warunki: kolumnę, operator obsługiwany przez jej typ i wartość.
Każdy kompletny warunek od razu zawęża rekordy, a **Save view** zapisuje warunki,
wyszukiwanie i sortowanie w widoku na ekranie.

Kolejność jest całkowita. Po żądanym sortowaniu (`created_at`, `updated_at` lub
kolumna, którą można sortować) następuje id rekordu, więc strona nigdy nie powtarza ani
nie pomija rekordu w niezmienionej tabeli. Rekordy bez wartości w sortowanej kolumnie
są na końcu w obu kierunkach. Kolumny `multi_select` nie da się sortować. `updated_at` jest ustawiane przy utworzeniu
rekordu i przesuwa się z każdą edycją, więc rekordy, których nikt nie edytował,
sortują się według czasu utworzenia.

Listowanie nie ma `total`, bo liczenie przefiltrowanej tabeli nie jest tanie: `has_more`
mówi, czy następuje kolejna strona. `POST /tables/{id}/records/count` odpowiada na to
pytanie osobno, dla filtrów i wyszukiwania zapytania, i liczy najwyżej do 100 000;
`capped` mówi, że pasuje więcej. Konsola pokazuje tę liczbę obok zakładek widoków, a jej
siatka wczytuje po sto rekordów podczas przewijania i rysuje tylko widoczne wiersze. Za
10 000 rekordów, które zapytanie może pominąć, prosi o filtr lub wyszukiwanie.

## Zapisane widoki { #saved-views }

**Sortuj** obok **Filtruj** wybiera kolumnę oraz kierunek rosnący lub malejący dla tabeli, listy albo kart w każdej kolumnie Kanbana. Dostępne są też ukryte kolumny obsługujące sortowanie i daty systemowe. Przycisk pokazuje aktywną kolumnę i kierunek. Serwer sortuje przed stronicowaniem, także rekordy jeszcze niewczytane. **Zapisz widok** zachowuje kolejność razem z filtrami i wyglądem; **+** zapisuje nowy widok. **Domyślna kolejność: najstarsze najpierw** przywraca sortowanie według daty utworzenia.

**Ustawienia widoku** pozwalają zmieniać kolejność i widoczność kolumn, także systemowych. Przeciągnij kolumnę lub użyj strzałek; ukrycie pola systemowego zachowuje jego automatyczną wartość. **Zawijaj tekst** pokazuje pełny tekst i podziały wierszy; wyłączenie przywraca kompaktowe wiersze. Wybierz datę automatyczną, ISO, dzień–miesiąc–rok, miesiąc–dzień–rok lub pełną oraz godzinę automatyczną, 24-godzinną, 12-godzinną albo ukrytą. Sama data zachowuje dzień, a znaczniki czasu używają strefy odbiorcy. **Zapisz widok** zachowuje ustawienia wybranego widoku; **+** tworzy nowy. Formatowanie nie zmienia wartości ani filtrów.

Tablica kanban bez zapisanego grupowania automatycznie korzysta z jedynej aktywnej kolumny jednokrotnego wyboru. Przy kilku kolumnach wybierz, która tworzy tory. Zapis widoku zachowuje grupowanie. Wiersze listy nazywają pola pomocnicze i pokazują **Unnamed record**, gdy tytuł jest pusty. **Triggers** proponuje **Open workflows**, gdy żaden workflow nie startuje jeszcze z tej tabeli.

**Widok** to zachowany filtr, sortowanie i grupowanie nad rekordami jednej tabeli -
to, co zapisują ekrany konsoli table/kanban/list, żeby nikt nie budował tej samej
tablicy przy każdej wizycie. Jest podzasobem tabeli, a nie osobnym zasobem
współdzielonym: widok nie ma własnego właściciela ani grantów swojego rodzaju, a
`shared` oznacza wyłącznie "widoczny dla każdego, kto już ma `tables:view` na
tabeli nadrzędnej" - nigdy nie poszerza dostępu ponad to, na co pozwala sama
tabela.

W konsoli ekran bez wybranego widoku nazywa się **All records**, a **+** obok zapisuje
to, co pokazuje ekran, jako nowy widok. Tablica kanban automatycznie wybiera jedyną aktywną kolumnę jednokrotnego wyboru;
przy kilku pyta, która tworzy tory. Zapis widoku zachowuje grupowanie. Karta pokazuje pod tytułem do czterech kolumn ekranu, pomijając puste. Tabela bez kolumny jednokrotnego wyboru proponuje zamiast tego **Add a
column**.

Właściciel widoku przełącza go między **Private** a **Shared** przyciskiem obok
**Rename**. Ktoś, kto zarządza widokiem innego członka, na przykład administrator, nie
dostaje tego przełącznika: o udostępnieniu czyichś filtrów decyduje ich autor.

`GET/POST /tables/{id}/views` oraz `GET/PATCH/DELETE /tables/{id}/views/{view_id}`
listują, tworzą, czytają, aktualizują i usuwają je. Lista jest stronicowana przez
`skip` i `limit` (najwyżej 100): najpierw własne widoki wywołującego, potem
współdzielone, w każdej grupie według nazwy; `total` liczy wszystkie. `config` to `{filters, search, sort,
visible_columns, group_by, display}` - `RecordQuery` oraz pola potrzebne tylko
renderowaniu konsoli: `visible_columns` (`null` oznacza każdą żywą kolumnę) i
`group_by` (żywa kolumna `single_select`, dla kolumn tablicy kanban).

Obiekt `display` przechowuje `column_order`, `hidden_system_columns`, `wrap_text`, `date_format` i `time_format`. Starsze widoki zachowują kompaktowy wygląd i formatowanie języka. Jawne `visible_columns: []` ukrywa wszystkie kolumny niestandardowe.

| Pole | Znaczenie |
|---|---|
| `kind` | `table`, `kanban` lub `list` - widok jest zapisany *dla* jednego rodzaju |
| `visibility` | `private` (tylko właściciel) lub `shared` (każdy, kto widzi tabelę) |
| `can_manage` | Czy ten wywołujący może zmienić nazwę, przekonfigurować lub udostępnić widok |
| `can_delete` | Czy ten wywołujący może usunąć widok |

Listowanie, odczyt i usunięcie rozwiązują się względem tabeli (`tables:view`);
utworzenie lub zmiana widoku wymaga `tables:edit` na tabeli, więc właściciel,
któremu odebrano prawo edycji, nadal może usunąć swoje widoki, ale nie może już
ich przekształcić ani udostępnić.

Zmiana lub usunięcie widoku jest węższe:
tylko jego właściciel albo wywołujący, którego [scope](permissions.md) dla
`tables:edit` to `ALL` - nie "każdy, kto może edytować tabelę" - więc
współdzielony edytor nie może po cichu przestawić zapisanego filtra innego
członka. Odmowa działa tak samo jak przy każdym innym zapisie na jednym zasobie
tutaj: `NOT_FOUND` (404), nigdy 403, który ujawniłby istnienie widoku wywołującemu,
któremu go odmówiono. `can_manage` i `can_delete` mówią, co z tych dwóch ten
wywołujący może zrobić.

Zarchiwizowanie kolumny jest odrzucane z `SCHEMA_DEPENDENCY`, wskazując widok, gdy
widok, który wywołujący może zarówno zobaczyć, jak i zmienić, nadal używa jej do
filtrowania, sortowania lub grupowania: jeden z jego własnych albo - dla
wywołującego, którego scope dla `tables:edit` to `ALL` - współdzielony. Żaden inny
widok nie blokuje archiwizacji i nie jest wymieniany, bo wywołujący nie mógłby go
usunąć z drogi; dotyczy to każdego prywatnego widoku innego członka, którego nie
ujawnia się nawet wywołującemu ze scope `ALL`. Samo pokazywanie kolumny w
`visible_columns` też nie blokuje.

To, co widok nadal wskazuje z kolumny, która nie jest już żywa, jest pomijane przy
jego odczycie: filtr na niej znika, sortowanie po niej wraca do `created_at`,
grupowanie po niej jest czyszczone, a ona sama wypada z `visible_columns` - widok,
który nie pokazuje już żadnej z wybranych kolumn, pokazuje wszystkie żywe. Zapisana
konfiguracja nie jest przepisywana.

### Strony i widoki { #views-for-pages }

Opublikowany [artefakt](artifacts.md#live-data) nie czyta przez widok. Jego bindingi
to **zapytania strony**: tabela, filtry, sortowanie, limit i pola, które strona
czyta, a które platforma zapisuje w wersji strony przy publikacji. Binding może
wystartować od zapisanego widoku — agent znajduje go przez `list_views`, które dla
tabel, które może czytać, zwraca id każdego widoku, jego kolumny i to, czy jest
współdzielony — ale filtry i sortowanie widoku są wtedy **kopiowane** do strony.
Późniejsza edycja, udostępnienie, zmiana nazwy czy usunięcie widoku niczego na
stronie nie zmienia, a `visible_columns` i `group_by` widoku są ignorowane: o kolumnach
decyduje `fields` bindingu.

Widoku z wyszukiwaniem pełnotekstowym nie można powiązać, bo wyszukiwanie dopasowuje
każdą żywą kolumnę tekstową i poszerzałoby się wraz z dodawaniem kolumn; publikacja
jest odrzucana i nazywa widok. Tak samo widok, którego filtr wskazuje kolumnę, której już nie ma.

O tym, kto może czytać rekordy strony, nie decyduje widok. Są czytane z dostępem
właściciela strony, gdy właściciel wyraził zgodę, a dostęp do tabeli jest wszystko
albo nic: `read` daje każdy wiersz i każdą żywą kolumnę. Zapytanie strony to sposób,
w jaki wiersze tabeli docierają do osób, które nie mogłyby jej otworzyć, i właściciel
jest o to najpierw pytany. Zobacz
[Artefakty](artifacts.md#consent-the-owner-decides-who-reads-the-data).

Zapytanie strony zapisuje `revision` każdej kolumny, do której sięga: jej pola,
kolumny filtra i sortowania, wejścia formuły, link i cel lookupu albo rollupu oraz
kolumnę, którą każda powiązana tabela etykietuje swoje rekordy. Binding staje się
`unavailable` (`source_changed`), gdy któraś z nich poszła dalej albo została
zarchiwizowana, albo gdy zarchiwizowano tabelę, do której sięga, a pozostałe bindingi
nadal działają. Nic nie blokuje z tego powodu zmiany tabeli: strona nie jest
zależnością, która blokuje archiwizację. `share_view` już nie istnieje; dla strony
nie ma prywatnego widoku do udostępnienia.

## Wyzwalacze { #triggers }

Kolumny Kanbana wczytują po 25 kart. **Wczytaj więcej** zachowuje dotychczasowe karty; po błędzie strony dostępne jest ponowienie. Zmianę grupowania można zapisać w aktywnym widoku. Odczyt prywatnego widoku po zmianie typów kolumn przez innego członka usuwa niezgodne filtry, sortowanie i grupowanie ze zwracanej konfiguracji, bez nadpisywania zapisanego widoku właściciela. Zapytanie strony tracące filtr wymaga ponownej zgody.

Zdarzenia tabel używają zegara ściennego przy wstawianiu po blokadzie mutacji, zgodnego z aktywacją triggera. Transakcja rozpoczęta przed aktywacją może nadal utworzyć późniejsze, kwalifikujące się zdarzenie. Migracja `0229_table_event_wall_clock.py` zmienia przyszłe znaczniki czasu; nie odtwarza wcześniej pominiętych zdarzeń, co mogłoby powielić efekty.


[Workflow](workflows.md#when-a-table-record-is-added), którego węzłem wyzwalacza jest
**Table record**, po publikacji uruchamia się dla tego, co dzieje się z rekordami jego
tabeli - dodania, zmiany lub usunięcia, zależnie od `events`; domyślnie tylko dodania -
niezależnie od drogi: w konsoli, przez API, przez narzędzie tabel agenta albo krok tabeli
innego workflow. Upsert, który tworzy rekord, to dodanie, a taki, który go aktualizuje,
to zmiana. Publikacja wymaga dostępu do odczytu tabeli i prawa do uruchamiania workflow,
bo działa on jako członek, który go opublikował, nigdy jako autor rekordu. Dostęp tego
członka jest sprawdzany ponownie przy każdym zdarzeniu.

Wyzwalacz uruchamia wersję, która go włączyła, a następna publikacja przenosi go na
nową wersję. Jego filtry używają operatorów z [Listowania i
filtrowania](#listing-and-filtering) i są oceniane na rekordzie takim, jaki został
dodany lub zmieniony, albo jaki był przed usunięciem. Zmiana uruchamia go tylko wtedy,
gdy zmieniła się jedna z kolumn wybranych dla tabeli, o ile kolumny są wybrane.

Przekazuje runowi rekord: `record_id`, `event`, `values` według id kolumn, te same
wartości jako `fields` według etykiet i `author_id`, a przy zmianie lub usunięciu
także `before` oraz kolumny `changed` według etykiet. **Triggers** na stronie tabeli
wymienia workflow, które od niej startują, wstrzymuje i wznawia każdy z nich oraz
otwiera jego historię.

Wyzwalacz startuje tylko dla rekordów dodanych, gdy jest włączony. Włączenie -
publikacja albo wznowienie - bierze blokadę schematu tabeli, na którą czeka każdy zapis rekordu, więc żaden
rekord zatwierdzony przed tą chwilą go nie uruchomi, a nic dodanego, gdy był wyłączony,
nie zostanie odtworzone. Job `workflow-table-triggers`, uruchamiany co dziesięć sekund, odczytuje zdarzenie
outbox każdego nowego rekordu, więc wyzwalacz startuje w ciągu około dziesięciu sekund. Decyduje raz na wyzwalacz i zapisuje decyzję;
drugi przebieg albo drugi worker znajduje tę decyzję i niczego nie uruchamia.

**Historia** wymienia każdą decyzję, od najnowszej, bez wartości rekordu:

| Widoczne jako | Dlaczego |
|---|---|
| Rozpoczął uruchomienie | Każdy filtr był spełniony; run jest podlinkowany |
| Pominięty | Rekord nie pasował albo dodano go, zanim wyzwalacz włączono |
| Zablokowany | Uruchomiłby sam siebie ponownie, łańcuch przekroczył pięć wyzwalaczy w głąb albo 50 runów, albo run odrzucił limit przyjęć |
| Nie udało się uruchomić | Członek, jako który działa, nie może już czytać tabeli ani uruchamiać workflow, albo nie udało się odczytać utworzenia rekordu |

Workflow, który zapisuje do tabeli, może uruchomić jej wyzwalacze, i tak dalej przez
kolejne tabele. Każdy run niesie łańcuch, do którego należy, a wyzwalacz, przez który
łańcuch już przeszedł, jest blokowany zamiast uruchamiany ponownie - to powstrzymuje
dwa workflow dodające rekordy do swoich tabel przed zapętleniem. Kolumny, którą
wyzwalacz filtruje, nie da się zarchiwizować, dopóki wyzwalacz jego workflow nie
przestanie po niej filtrować i nie zostanie opublikowany, nawet gdy jest wstrzymany, a
tabeli, od której startuje opublikowany workflow, nie da się zarchiwizować, dopóki ten
workflow nie zacznie startować inaczej.

## Co zatwierdza się razem { #what-commits-together }

Zapis rekordu, jego wiersz historii, jego potwierdzenie idempotencji i, dla create,
wiersz outbox `table.record.created` są zapisywane w jednej transakcji i zatwierdzane
lub wycofywane razem. Błąd na dowolnym kroku nie zostawia żadnego z nich. Zmiany
tabeli i schematu trafiają do [audit log](governance.md); zmiany rekordów trafiają do
historii per rekord, która przechowuje komórki dotknięte każdą zmianą.

Dwa z tych magazynów trzymają kopie tego, co zapisano. Receipt trzyma cały rekord tak, jak
zwrócił go zapis, a history trzyma to, co się zmieniło, więc usunięcie rekordu usuwa
bieżący wiersz i zostawia oba, dopóki nie usunie ich retencja. Wiersze outbox trzymają id.
Traktuj wszystkie trzy jako dane osobowe, jeśli takie są komórki; zobacz
[ochronę danych](data-protection.md#the-database) oraz
[limity i retencję](#limits-and-retention).

Wiersz outbox to przekazanie temu, co reaguje na nowy rekord: dziś są to
[wyzwalacze](#triggers). Ich heartbeat pobiera niedostarczone wiersze we własnej sesji,
ocenia każdy względem wyzwalaczy tabeli i oznacza go jako wysłany w tej samej transakcji.
Niewysłany wiersz jest usuwany tylko przez własne, znacznie dłuższe okno retencji (poniżej)
- to dead-letter cutoff dla workera, który tak długo nie działał, a nie deklaracja, że
zdarzenie zostało kiedykolwiek odebrane.

## Limity i retencja { #limits-and-retention }

Tenant może rozrosnąć wspólną bazę tylko tak, jak pozwala wdrożenie. Każdy limit to
ustawienie wdrożenia, obowiązuje **per organizacja**, więc użycie jednego tenanta nigdy nie
liczy się na konto innego, i jest odrzucany kodem `QUOTA_EXCEEDED` (402), gdy zapis by go
przekroczył.

| Ustawienie | Domyślnie | Ogranicza |
|---|---|---|
| `TABLES_MAX_PER_ORGANIZATION` | 200 | Tabele organizacji. Zarchiwizowane się liczą, bo tabela nigdy nie jest usuwana |
| `TABLES_MAX_RECORDS_PER_TABLE` | 100 000 | Rekordy w jednej tabeli. Aktualizacja rekordu w pełnej tabeli jest dozwolona |
| `TABLES_MAX_RECORD_BYTES` | 1 000 000 | Zserializowane wartości jednego rekordu, w bajtach |
| `TABLES_MAX_STORAGE_BYTES_PER_ORGANIZATION` | 1,073,741,824 | Bajty danych JSONB PostgreSQL na organizację łącznie dla rekordów, historii, potwierdzeń i outboxa; narzut tabel i indeksów jest osobny |

Łączny limit jest sprawdzany w savepoincie zmiany, pod blokadą organizacji, przed commitem. Przekroczenie cofa rekord i wszystkie zachowane kopie, także dla wiersza importu; pozostałe wiersze są raportowane jako odrzucone. Ponowienie z potwierdzenia, zapis bez zmian, odczyt i usuwanie nadal działają po obniżeniu limitu. Retencja zwalnia usuwane bajty.

Odmowa nazywa limit i jego pułap w `details` (`{"quota": "records", "limit": 100000}`),
nigdy treść, i zapisuje wpis `table.quota_refused` w [audit log](governance.md) z tymi
samymi dwoma polami. Odrzucone żądanie niczego nie zapisuje. Zapisy są też ograniczone do
`RATE_LIMIT_TABLE_WRITES_PER_MINUTE` (300) na członka i organizację, w konsoli tak samo jak
przez API; członek ponad limit dostaje 429 z `Retry-After`. Zobacz
[konfigurację](configuration.md#rate-limiting).

**Co trzyma history.** Create trzyma cały rekord w `after`, a delete trzyma cały rekord w
`before`; limit rekordu ogranicza oba. Rekord sprzed limitu, albo zapisany zanim
`TABLES_MAX_RECORD_BYTES` obniżono, wciąż może go przekraczać - jego delete trzyma wtedy
`before` jako `{"omitted": {"bytes": <jego rozmiar>, "limit": <limit>}}` zamiast wartości,
i mimo to się udaje. Update trzyma tylko komórki, które się zmieniły: `before` zawiera ich
wcześniejsze wartości, a `after` nowe, a kolumna nieobecna po jednej stronie była tam
pusta. Edycja jednej komórki dużego rekordu kosztuje więc jedną komórkę, choćby powtarzana
bez końca.

**Retencja.** Codzienny [sweep retencji](governance.md#retention) usuwa też dane tabel,
twardo i partiami, dla każdej organizacji:

| Co | Usuwane, gdy | Ustawienie |
|---|---|---|
| Receipts | Starsze niż 24 godziny | `TABLES_RECEIPT_TTL_HOURS` |
| Wiersze outbox | Wysłane ponad 3 dni temu | `TABLES_OUTBOX_RETENTION_DAYS` |
| Niewysłane wiersze outbox | Nigdy niewysłane i mające 30 dni: heartbeat wyzwalaczy nie działał tak długo i dla tych rekordów żaden wyzwalacz nie wystartuje | `TABLES_OUTBOX_UNDISPATCHED_RETENTION_DAYS` |
| History | Starsza niż 365 dni, dla usuniętego rekordu tak samo jak dla żywego | `TABLES_HISTORY_RETENTION_DAYS` |

Sweep zapisuje jeden wpis audytu na organizację, nazywający klasę (`table_receipts`,
`table_outbox`, `table_history`) i liczbę. To ustawienia wdrożenia, a nie per organizacja.
Samych rekordów i tabel sweep nigdy nie usuwa.

`RATE_LIMIT_TABLE_WRITES_PER_MINUTE` to przydział *per member*, więc budżet jednego przebiegu
dla każdej z trzech klas skaluje się zarówno z nim, jak i z liczbą aktywnych członków
organizacji, z zapasem, żeby istniejąca zaległość się kurczyła, a nie tylko utrzymywała na
stałym poziomie - każdy member piszący bez przerwy naraz nigdy nie wyprzedza sweepa, aż do
hojnego limitu na to, dla ilu członków budżet jednego przebiegu organizacji się skaluje.
Liczby są w [konfiguracji](configuration.md#virtual-tables-limits-and-retention). Zaległość
ponad to jest usuwana w kilku kolejnych przebiegach, tak jak w każdej innej klasie.

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
tabeli, a schemat to wymusza: wiersz records, history lub outbox odwołuje się do swojej
tabeli także przez organizację, więc nie może wskazać tabeli innego tenanta.

Tabela innej organizacji i tabela, do której wywołujący nie ma dostępu, to w obu
przypadkach 404. Kontekst bez zalogowanego podmiotu nie dociera do niczego.

Czy konkretny wywołujący może edytować konkretną tabelę, jest też bezpośrednio na
przewodzie: `TableSummary.can_edit` i `TableRead.can_edit` są rozwiązywane po
stronie serwera (scope roli lub jawny grant) i wysyłane przy każdym odczycie, tak
samo jak `Agent.can_run` - więc wiersz katalogu albo strona szczegółów nigdy nie
musi zgadywać, czy jej kontrolki edycji zostałyby odrzucone. Własne `can_manage` i
`can_delete` zapisanego widoku to ta sama idea, o jeden poziom niżej (zobacz
[Zapisane widoki](#saved-views)).

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
| `BAD_REQUEST` | 400 | Przywrócenie wskazało tabelę, która nie jest zarchiwizowana |
| `ALREADY_EXISTS` | 409 | Nazwa tabeli, nazwa widoku lub external id jest zajęte |
| `INVALID_RECORD` | 422 | Wartość nie pasuje do kolumny; `details.fields` wskazuje każdą |
| `ARCHIVED_COLUMN` | 422 | Wartość wskazuje zarchiwizowaną kolumnę |
| `INVALID_QUERY` | 422 | Filtr lub sortowanie, na które tabela nie odpowie |
| `INVALID_SCHEMA` | 422 | Niespójna zmiana schematu |
| `IDEMPOTENCY_KEY_REUSED` | 422 | Klucz został użyty dla innego żądania |
| `QUOTA_EXCEEDED` | 402 | Zapis przekroczyłby limit przechowywania; `details` nazywa limit (`tables`, `records`, `record_bytes`, `storage_bytes`) i jego pułap |
| `RATE_LIMIT_EXCEEDED` | 429 | Za dużo zapisów do tabel w ostatniej minucie; zobacz `Retry-After` |
| `VALIDATION_ERROR` | 422 | Samo żądanie jest wadliwe: zły typ, nieznane pole, limit albo NUL, znak nowego wiersza lub osamotniony surogat w id, kluczu lub nazwie. Trasa odrzuca je, zanim uruchomi się serwis |
| `AUTHORIZATION_ERROR` | 403 | Wywołujący nie ma permission, której wymaga trasa kolekcji (`tables:view`, `tables:create`) |
| `CONCURRENT_CHANGE` | 409 | Upsert przegrał wyścig z usunięciem tego samego rekordu. Ponów go |
| `NOT_FOUND` | 404 | Nie ma takiej tabeli ani rekordu albo wywołujący nie ma do nich dostępu |

## Wywoływanie serwisu z Pythona { #calling-the-service-from-python }

```python
service = VirtualTableService(db)
table = await service.create_table(
    ctx,
    TableCreate(
        name="Orders",
        columns=[
            ColumnInput(label="Customer", type="text"),
        ],
    ),
)
customer = str(table.columns[0].id)

written = await service.upsert_record(
    ctx,
    table.id,
    "ORD-1042",
    RecordUpsert(values={customer: "Acme"}),
    operation_key="import-2026-09-21-row-17",
)

# Send the revision back to change it; a stale one raises RevisionConflictError.
await service.upsert_record(
    ctx,
    table.id,
    "ORD-1042",
    RecordUpsert(values={customer: "Acme Ltd"}, expected_revision=written.record.revision),
)
```

Organizacja zawsze pochodzi z `ctx`, nigdy z argumentu. Serwis nigdy nie robi commit:
robi go sesja żądania, a worker ma własny zakres sesji.

## Dodawanie typu kolumny { #adding-a-column-type }

Typ kolumny to jeden wpis w `COLUMN_TYPES` w
`backend/app/services/virtual_tables/types.py`, z nazwą w `ColumnTypeName` w
`backend/app/schemas/virtual_table.py`. Wpis mówi, jak komórka jest odczytywana z
rekordu do porównań i sortowania (`SqlKind`), które operatory filtrów przyjmuje, czy
się sortuje, i jaki walidator przechodzi każdy zapis i każdy operand filtra. Walidator
zwraca wartość tak, jak zostanie zapisana, albo rzuca `CellProblem` z komunikatem dla
tego, kto ją zapisał. Każda powierzchnia woła ten sam serwis, więc konsola, API,
agenci i workflow przyjmują nowy typ od razu, a [wyzwalacz](#triggers) filtruje po nim
według tych samych reguł.

Konsola potrzebuje typu w `ColumnTypeName` w `frontend/src/types/tables.ts`, edytora w
`record-cell-editor.tsx`, wyboru w dialogach schematu i tworzenia tabeli oraz etykiety
w trzech katalogach komunikatów. Testy należą do
`backend/tests/test_virtual_table_types.py` dla walidatora oraz do testu
integracyjnego, który zapisuje, filtruje i sortuje rekord nowego typu.
