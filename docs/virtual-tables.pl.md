---
source_sha: "3b91bbe3bade"
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
| `number` | Skończona liczba | `eq` `ne` `lt` `lte` `gt` `gte` `in` `is_null` |
| `integer` | Liczba całkowita, co najwyżej 2^53 - 1 | tak samo jak `number` |
| `boolean` | `true` lub `false` | `eq` `ne` `is_null` |
| `date` | `YYYY-MM-DD` | tak samo jak `number` |
| `datetime` | ISO 8601 ze strefą czasową, zapisywany jako UTC | tak samo jak `number` |
| `single_select` | Id opcji | `eq` `ne` `in` `is_null` |
| `multi_select` | Lista id opcji | `contains` `is_null` |

Tekst jest zapisywany dokładnie tak, jak został wysłany. Spacje na początku i na
końcu, podziały wierszy i wartości złożone z samych spacji to dane użytkownika, więc
nie są przycinane. Obowiązuje tylko limit długości, a znak NUL jest odrzucany, w komórkach i tak samo w nazwach, etykietach, opisach i
external id, bo PostgreSQL nie potrafi go zapisać.

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
kolumną dodaje nową, na początek opcjonalną. Typ kolumny nigdy się nie zmienia.

### Import i eksport { #import-and-export }

**Export** zapisuje to, co pokazuje strona, jako plik CSV: rekordy pasujące do filtrów
i wyszukiwania, w kolejności siatki, w jej widocznych kolumnach. `POST
/tables/{id}/records/export` robi to samo dla wywołującego, z tymi samymi filtrami,
wyszukiwaniem, sortowaniem i listą `columns`. Opcja jest zapisywana jako jej etykieta,
kilka jako `a; b`, a komórka tekstowa, którą arkusz odczytałby jako formułę, zaczyna
się od `'`. Ponad 100 000 pasujących rekordów jest odrzucane z `EXPORT_TOO_LARGE` (413).

**Import** czyta plik CSV rozdzielany przecinkiem lub średnikiem, którego pierwszy
wiersz nazywa kolumny. Każda kolumna pliku jest dopasowana do kolumny tabeli o tej
samej nazwie albo do **External id** i można ją skierować gdzie indziej lub pominąć.
Wartość, której nie da się odczytać w typie kolumny, odrzuca swój wiersz, zanim cokolwiek
zostanie wysłane. Reszta trafia po 200 do `POST /tables/{id}/records/batch`, który
zapisuje każdy rekord osobno i wymienia odrzucone z ich kodami, a konsola wypisuje każdy
nieudany wiersz z numerem linii. Każdy dodany rekord uruchamia wyzwalacze tabeli, jak
każdy inny.

Nowa tabela też może zacząć się od pliku: **Start from a CSV file** w **New table**
zamienia nagłówek na kolumny i daje każdej najwęższy typ, w którym dają się odczytać
wszystkie jej wartości - liczba całkowita, liczba, tak/nie, data albo data i godzina
w ISO - a w przeciwnym razie tekst lub długi tekst, gdy wartość ma podział wiersza albo
przekracza 1000 znaków. Nazwa pochodzi z pliku i obie rzeczy można zmienić przed
utworzeniem, bo typu nie da się później zmienić. Gdy tabela już istnieje, import
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

**Widok** to zachowany filtr, sortowanie i grupowanie nad rekordami jednej tabeli -
to, co zapisują ekrany konsoli table/kanban/list, żeby nikt nie budował tej samej
tablicy przy każdej wizycie. Jest podzasobem tabeli, a nie osobnym zasobem
współdzielonym: widok nie ma własnego właściciela ani grantów swojego rodzaju, a
`shared` oznacza wyłącznie "widoczny dla każdego, kto już ma `tables:view` na
tabeli nadrzędnej" - nigdy nie poszerza dostępu ponad to, na co pozwala sama
tabela.

`GET/POST /tables/{id}/views` oraz `GET/PATCH/DELETE /tables/{id}/views/{view_id}`
listują, tworzą, czytają, aktualizują i usuwają je. Lista jest stronicowana przez
`skip` i `limit` (najwyżej 100): najpierw własne widoki wywołującego, potem
współdzielone, w każdej grupie według nazwy; `total` liczy wszystkie. `config` to `{filters, search, sort,
visible_columns, group_by}` - `RecordQuery` plus dwa pola potrzebne tylko
renderowaniu konsoli: `visible_columns` (`null` oznacza każdą żywą kolumnę) i
`group_by` (żywa kolumna `single_select`, dla kolumn tablicy kanban).

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

## Wyzwalacze { #triggers }

[Workflow](workflows.md#when-a-table-record-is-added), którego węzłem wyzwalacza jest
**New table record**, po publikacji uruchamia się dla każdego rekordu dodanego do jego
tabeli, niezależnie od drogi: w konsoli, przez API, przez narzędzie tabel agenta albo
krok tabeli innego workflow. Upsert, który tworzy rekord, go uruchamia; taki, który
rekord aktualizuje, nie. Publikacja wymaga dostępu do odczytu tabeli i prawa do
uruchamiania workflow, bo działa on jako członek, który go opublikował, nigdy jako autor
rekordu. Dostęp tego członka jest sprawdzany ponownie przy każdym rekordzie.

Wyzwalacz uruchamia wersję, która go włączyła, a następna publikacja przenosi go na
nową wersję. Jego filtry używają operatorów z [Listowania i filtrowania](#listing-and-filtering)
i są oceniane na rekordzie w chwili utworzenia, więc późniejsza edycja ani go nie
uruchamia, ani nie zatrzymuje. Przekazuje runowi cały rekord: `record_id`, `values`
według id kolumn, te same wartości jako `fields` według etykiet oraz `author_id`, żeby
run mógł go zmienić z powrotem przez `table.record.update`. **Triggers** na stronie
tabeli wymienia workflow, które od niej startują, wstrzymuje i wznawia każdy z nich oraz
otwiera jego historię.

Wyzwalacz startuje tylko dla rekordów dodanych, gdy jest włączony. Włączenie -
publikacja albo wznowienie - bierze blokadę schematu tabeli, na którą czeka każdy zapis rekordu, więc żaden
rekord zatwierdzony przed tą chwilą go nie uruchomi, a nic dodanego, gdy był wyłączony,
nie zostanie odtworzone. Heartbeat workera odczytuje zdarzenie outbox każdego nowego
rekordu w ciągu około dziesięciu sekund. Decyduje raz na wyzwalacz i zapisuje decyzję;
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
| `ALREADY_EXISTS` | 409 | Nazwa tabeli, nazwa widoku lub external id jest zajęte |
| `INVALID_RECORD` | 422 | Wartość nie pasuje do kolumny; `details.fields` wskazuje każdą |
| `ARCHIVED_COLUMN` | 422 | Wartość wskazuje zarchiwizowaną kolumnę |
| `INVALID_QUERY` | 422 | Filtr lub sortowanie, na które tabela nie odpowie |
| `INVALID_SCHEMA` | 422 | Niespójna zmiana schematu |
| `IDEMPOTENCY_KEY_REUSED` | 422 | Klucz został użyty dla innego żądania |
| `QUOTA_EXCEEDED` | 402 | Zapis przekroczyłby limit przechowywania; `details` nazywa limit (`tables`, `records`, `record_bytes`) i jego pułap |
| `RATE_LIMIT_EXCEEDED` | 429 | Za dużo zapisów do tabel w ostatniej minucie; zobacz `Retry-After` |
| `VALIDATION_ERROR` | 422 | Samo żądanie jest wadliwe: zły typ, nieznane pole, limit albo NUL, znak nowego wiersza lub osamotniony surogat w id, kluczu lub nazwie. Trasa odrzuca je, zanim uruchomi się serwis |
| `AUTHORIZATION_ERROR` | 403 | Wywołujący nie ma permission, której wymaga trasa kolekcji (`tables:view`, `tables:create`) |
| `CONCURRENT_CHANGE` | 409 | Upsert przegrał wyścig z usunięciem tego samego rekordu. Ponów go |
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

## Jeszcze nie zbudowane { #not-built-yet }

- **Podmiot dla kluczy API.** Dostęp, potwierdzenia i historia wskazują zalogowanego
  użytkownika. Jak klucz API działa na tabeli w zewnętrznym API, ma dopiero zostać
  uzgodnione.
- Tworzenie i usuwanie rekordów z konsoli. Agenci sięgają do tabel przez
  [capability Tables](reference/capabilities.md#tables), a workflow przez
  [węzły tabel](reference/workflow-nodes.md#virtual-tables).
- Wyzwalacz na aktualizację albo usunięcie rekordu. [Wyzwalacze](#triggers) startują
  tylko przy utworzeniu.
- Wznowienie z konsoli runu, który zatrzymał się jako **Wymaga uwagi**. Można go
  anulować i uruchomić nowy run.
