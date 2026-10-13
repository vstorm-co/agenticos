---
source_sha: "b87eb7e189ca"
title: "Datasety"
description: "Datasety trzymają pytania, na których testujesz agenta: wersjonowane przypadki pisane ręcznie, importowane z CSV lub JSONL albo wzięte z ocenionej odpowiedzi."
---

# Datasety { #datasets }

**Dataset** trzyma pytania, na których testujesz agenta. Bez
niego każde sprawdzenie, czy zmiana poprawiła agenta, polega na tym, że ktoś
ręcznie wpisuje kilka promptów i próbuje pamiętać, jak wyglądała poprzednia
odpowiedź.

Każde pytanie to **przypadek**: wiadomość, na którą odpowiada agent, i opis
tego, jak wygląda dobra odpowiedź. Przypadki pochodzą z czterech miejsc - są
pisane w konsoli, importowane z pliku, brane z prawdziwej rozmowy, w której
ktoś ocenił odpowiedź łapką w dół, albo przygotowywane przez generator
przypadków i akceptowane przez człowieka. To ostatnie źródło jest zwykle najcenniejsze,
bo to pytanie, które ktoś naprawdę zadał, i odpowiedź, która go naprawdę
zawiodła.

## Co zawiera przypadek { #what-a-case-holds }

| Pole | Co to jest |
|---|---|
| Wejście | Wiadomość, na którą odpowiada agent |
| Rozmowa przed wejściem | Opcjonalne wcześniejsze tury, od najstarszej. Z nimi przypadek jest początkiem rozmowy, a agent odpowiada na jej ostatnią turę |
| Odpowiedź wzorcowa | Co mówi dobra odpowiedź |
| Kontrprzykład | Odpowiedź, o której wiadomo, że jest błędna |
| Oczekiwane wywołania narzędzi | Narzędzia, które agent powinien wywołać, każde z argumentami, które muszą się zgadzać. Argumenty, których przypadek nie wymienia, są pomijane. Przypadek mówi też, jak dopasować wywołania: `any` - w dowolnej kolejności, `in_order` - w podanej kolejności, z innymi wywołaniami pomiędzy, albo `exact` - dokładnie te, w tej kolejności i żadnych innych |
| Sprawdzenia | Reguły dotyczące odpowiedzi, każda jako obiekt, którego `type` nazywa regułę, a obok są jej parametry. Przypadek je przechowuje; ocenianie je czyta i decyduje, jakie typy istnieją |
| Tagi | Etykiety do grupowania wyników, np. `billing` albo `refusal` |
| Notatka | Po co jest ten przypadek - co poszło źle albo czego pilnuje |
| Źródło | `manual`, `import`, `conversation` albo `synthetic` - ustawia je platforma, nie wpisuje się go |

Przypadek wzięty z rozmowy zachowuje też odnośnik do runa, rozmowy i
wiadomości, z których pochodzi. Pytanie i odpowiedź są kopiowane do przypadku,
więc przypadek pozostaje kompletny także po tym, jak sam run usunie retencja.

Załączniki nie są częścią przypadku w tej wersji. Przypadek to tekst.

## Każda zmiana to nowa wersja { #versions }

Dodanie, edycja albo usunięcie przypadku, import pliku oraz akceptacja
wygenerowanych przypadków tworzą nową **wersję** datasetu, numerowaną od 1. Wersja nigdy się nie zmienia po
utworzeniu. Edytowany przypadek jest zapisywany jako nowa rewizja, a wersja
sprzed edycji nadal trzyma poprzednią.

Ma to znaczenie przy porównywaniu wyników. Dwa runy eval na tej samej wersji
widziały te same pytania, więc różnica w wynikach pochodzi od agenta, a nie od
testu. Strona datasetu domyślnie pokazuje najnowszą wersję; starszą wybierasz z
listy wersji. Starsza wersja jest tylko do odczytu.

Zmiana nazwy datasetu albo jego opisu nie tworzy wersji, bo żadna z nich nie
zmienia przypadku.

## Dodawanie przypadków { #adding-cases }

### W konsoli { #in-the-console }

Otwórz **Datasety**, utwórz dataset i wybierz **Dodaj przypadek**. Jedyne
wymagane pole to wejście. Rozmowę, oczekiwane wywołania narzędzi i sprawdzenia
wpisuje się jako listy JSON - ten sam tekst, w jakim trzyma je eksport CSV.

### Z pliku { #import-and-export }

**Import** czyta plik `.csv` albo `.jsonl` i dodaje wszystkie przypadki z niego
jako jedną nową wersję. Import jest typu „wszystko albo nic”: jeśli jeden
wiersz jest błędny, nie zostaje dodany żaden, a odmowa wymienia każdy błędny
wiersz, żebyś mógł poprawić plik i spróbować ponownie. Plik ma najwyżej 10 MB,
a dataset mieści najwyżej 10 000 przypadków.

Oba formaty używają tych samych dziewięciu nazw pól:

| Kolumna | W CSV | W JSONL |
|---|---|---|
| `input` | Tekst. Wymagana | String. Wymagana |
| `history` | Lista JSON w komórce albo pusto | Lista obiektów `{"role", "content"}` |
| `reference_answer`, `counter_example`, `note` | Tekst albo pusto | String albo `null` |
| `expected_tool_calls` | Lista JSON w komórce albo pusto | Lista obiektów `{"tool", "args"}` |
| `order_mode` | `any`, `in_order` albo `exact`; puste oznacza `any` | String |
| `checks` | Lista JSON w komórce albo pusto | Lista obiektów sprawdzeń |
| `tags` | Oddzielone przecinkami | Lista stringów |

Plik CSV musi mieć wiersz nagłówka. Kolumny inne niż te dziewięć są odrzucane,
więc literówka w nazwie kolumny nie gubi po cichu jej danych. Pominięte kolumny
przyjmują pustą wartość. W sprawdzeniu i w argumentach wywołania narzędzia klucze są eksportowane alfabetycznie, po `type` sprawdzenia.

```csv
input,reference_answer,tags
How long is the return window?,30 days from delivery,returns
Can I return a used kettle?,"No, only unused items",returns
```

**Eksport** pobiera wersję widoczną na ekranie jako CSV albo JSONL. Eksport
importuje się z powrotem bez zmian. Żeby tak było także w arkuszu
kalkulacyjnym, komórka CSV zaczynająca się od `=`, `+`, `-`, `@` albo `'` jest
zapisywana z `'` na początku, żeby arkusz nie wykonał jej jako formuły, a import
usuwa ten jeden `'`. Eksport jest zapisywany w [dzienniku audytu](governance.md#audit).

### Z rozmowy albo runa { #add-to-dataset }

Każda odpowiedź agenta w czacie i każda tura agenta w **Aktywności** ma
przycisk **Dodaj do datasetu**. Wybierz dataset, a przypadek powstanie z tej tury:

- pytanie staje się wejściem, a tury przed nim - rozmową przed wejściem;
- odpowiedź staje się kontrprzykładem. Jeśli nikt nie ocenił jej łapką w dół,
  domyślnie jest proponowana jako odpowiedź wzorcowa, a ty wybierasz jedno z
  dwóch;
- najnowszy komentarz zostawiony z łapką w dół staje się notatką.

Przycisk widzą członkowie, którzy mogą edytować jakiś dataset. Wiadomość musi
należeć do twojej organizacji i musisz móc ją przeczytać: albo masz
`runs:view`, które czyta każdy run w organizacji tak jak Aktywność, albo możesz
otworzyć rozmowę. Wiadomość z innej organizacji jest odrzucana tak, jakby nie
istniała.

### Z generatora przypadków { #generating-cases }

Napisanie stu dobrych przypadków ręcznie to powód, dla którego większość
zespołów nie ma żadnych. **Generuj przypadki** na stronie datasetu prosi
generator przypadków o ich przygotowanie, a ty decydujesz, które trafią do
datasetu. Wybierz agenta, którego przypadki testują, źródła i liczbę
przypadków - najwyżej 50, dzielonych po równo między źródła:

| Źródło | Co przygotowuje generator | Co dostaje |
|---|---|---|
| Z agenta | Typowe prośby i przypadki brzegowe, z wywołaniami narzędzi, które wykonuje dobra odpowiedź | Instrukcje agenta, jego skille i narzędzia, pod nazwami, które nadaje im agent |
| Z wiedzy | Pytania, na które odpowiada baza wiedzy. Każdy przypadek wskazuje dokument, z którego pochodzi fragment, trzyma ten fragment jako odpowiedź wzorcową, oczekuje wywołania wyszukiwania w wiedzy agenta i ma sprawdzenie `judge`, że odpowiedź zgadza się z fragmentem | Fragmenty z najwyżej 12 zaindeksowanych dokumentów baz wiedzy, których używa agent i które możesz czytać |
| Z rozmów | Parafrazy i trudniejsze warianty tego, o co ludzie pytali agenta, najpierw odpowiedzi ocenione łapką w dół. Każdy przypadek wskazuje pytanie, które wariantuje | Najwyżej 60 pytań zadanych agentowi w tej organizacji, z komentarzem zostawionym przy odpowiedzi ocenionej łapką w dół |
| Red team | Prośby spoza zakresu, wstrzykiwanie promptów, próby wydobycia danych osobowych i obejścia zasad agenta. Każdy przypadek ma tagi `red-team` i `red-team:<kategoria>` oraz sprawdzenie `judge`, że agent odmawia | Instrukcje agenta, jego skille i narzędzia |

**Najpierw szacowany koszt.** Okno pokazuje, o ile przypadków zostanie
poproszone każde źródło, z ilu materiałów każde korzysta, i szacunek kosztu,
zanim cokolwiek zostanie wydane. To szacunek: budżet generatora jest sprawdzany
w chwili uruchomienia, jak budżet każdego agenta. Zmiana agenta, źródeł albo
liczby unieważnia szacunek.

**Nic nie trafia do datasetu, dopóki tego nie zaakceptujesz.** Propozycje czekają
w sekcji **Proponowane przypadki** na stronie datasetu. Zaakceptuj je bez zmian,
najpierw edytuj albo odrzuć, pojedynczo albo całą stronę naraz. Jedno
Zaakceptuj to jedna nowa wersja, niezależnie od tego, ile niosło, a jej
przypadki mają źródło `synthetic`. Odrzucona propozycja jest usuwana i nie
zostawia niczego w datasecie. Zaakceptowana też znika z propozycji: jej zapisem
jest wersja.

**Generator jest agentem.** To agent systemowy tworzony w każdej organizacji,
więc jego runy są liczone do jego własnego budżetu i budżetu organizacji, a
każde generowanie to jeden run, który możesz otworzyć w
[Aktywności](console.md). Nie ma narzędzi: wszystko, co czyta, jest zbierane dla
niego z twoimi uprawnieniami i przekazywane w prompcie, więc dokument albo
rozmowa, które próbują wydawać mu polecenia, mogą najwyżej zmienić tekst
propozycji, którą przeglądasz. Propozycja, która nie spełnia reguły swojego
źródła - przypadek z wiedzy bez fragmentu, który generator dostał, przypadek z
rozmów bez pytania, które dostał, przypadek red team bez kategorii - jest
odrzucana, zanim ją zobaczysz.

**Każde źródło ma własną bramkę**, a źródło, którego nie możesz użyć, jest
odrzucane z nazwy, a nie pomijane po cichu:

- każde generowanie wymaga `datasets:edit` na datasecie, `agents:view` na
  testowanym agencie i `agents:run` na generatorze przypadków, bo wydaje
  pieniądze organizacji;
- wiedza czyta tylko bazy wiedzy, które możesz czytać; okno mówi, ile baz
  agenta pominięto;
- rozmowy wymagają `runs:view`, uprawnienia, z którym Aktywność czyta każdy run;
- organizacja, która wyłączyła wsparcie AI, nie może rozpocząć generowania.
  Czekające propozycje nadal można zaakceptować albo odrzucić, bo decyzja nie
  woła modelu.

Propozycje widzą tylko członkowie, którzy mogą edytować dataset. Propozycja
wzięta z rozmowy to tekst, którego pozostali czytelnicy datasetu nie widzieli;
po akceptacji jest przypadkiem jak każdy inny.

## Poświadczenia są redagowane { #credentials }

Tekst przypadków jest kopiowany z rozmów i z plików, które ludzie wgrywają, a
potem eksportowany i podawany modelom. Zanim przypadek zostanie zapisany,
platforma zastępuje każdy rozpoznany klucz API albo token znacznikiem, np.
`[redacted:github_token]`. Dotyczy to każdego pola, które czyta model albo
które trafia do eksportu, także argumentów oczekiwanego wywołania narzędzia, i
każdej drogi dodania przypadku. Generowanie redaguje też pytania i fragmenty
przekazywane generatorowi, zanim trafią do modelu. Wpis audytu dla zmiany
zapisuje, ile wartości zredagowano, nigdy same wartości.

## Dostęp { #access }

Dataset jest współdzielonym zasobem z właścicielem, widocznością i
grantami, tak jak [skill](skills.md) albo [plik kontekstowy](context.md). Nowy
dataset jest prywatny dla twórcy, dopóki ktoś nie udostępni go ze strony datasetu.
Katalog ma trzy uprawnienia dla datasetów:

| Uprawnienie | Pozwala członkowi | Poziom grantu, który je daje |
|---|---|---|
| `datasets:view` | Czytać przypadki i wersje datasetu oraz je eksportować | `read` |
| `datasets:edit` | Tworzyć datasety, zmieniać przypadki, importować, usuwać, udostępniać | `edit` |
| `datasets:run` | Uruchamiać evale na datasecie | `use` |

| | Owner | Admin | Builder | Operator | Member | Viewer |
|---|---|---|---|---|---|---|
| `datasets:view` | all | all | all | all | shared | shared |
| `datasets:edit` | all | all | shared | - | own | - |
| `datasets:run` | all | all | all | all | shared | - |

Członek bez dostępu do datasetu dostaje „nie znaleziono” na każdej trasie,
niezależnie od tego, na co pozwala mu rola gdzie indziej - samo istnienie
prywatnego datasetu jest czymś, czego nie może się dowiedzieć. Grant poszerza
dostęp do jednego datasetu i nigdy nie zmienia roli. Jak łączą się zakresy i
granty, opisuje strona [Uprawnienia](permissions.md).

## Dane osobowe { #personal-data }

Przypadek wzięty z rozmowy jest kopią tego, co napisała osoba, i tego, co
odpowiedział agent. Gdy rozmowa zostanie usunięta albo osoba, która ją
napisała, zostanie wymazana, przypadek zostaje, a każde powiązanie z nią jest
czyszczone: run, rozmowa i wiadomość, z których pochodzi, oraz to, kto go dodał,
jeśli była to wymazywana osoba. Zostaje tekst - który może nadal zawierać dane
osobowe wpisane przez kogoś i znika dopiero po usunięciu przypadku. Zobacz
[Ochrona danych](data-protection.md#what-deletion-reaches).

Wygenerowany przypadek, który wciąż czeka na decyzję, nie jest tak
zachowywany. Gdy rozmowa, z której go przygotowano, zostanie usunięta albo
osoba, która zadała pytanie, zostanie wymazana, propozycja jest usuwana razem z
nią: nikt nie zdecydował, że chce ją zachować. Generowanie z rozmów wysyła
zadane pytania, po redakcji, do dostawcy modelu generatora przypadków, a
generowanie z wiedzy wysyła fragmenty dokumentów - zobacz
[co opuszcza wdrożenie](data-protection.md#what-leaves-the-deployment).
