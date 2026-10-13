---
source_sha: "e98474d14e6a"
title: "Datasety"
description: "Datasety trzymają pytania, na których testujesz agenta: wersjonowane przypadki pisane ręcznie, importowane z CSV lub JSONL albo wzięte z ocenionej odpowiedzi."
---

# Datasety { #datasets }

**Dataset** trzyma pytania, na których testujesz agenta. Bez
niego każde sprawdzenie, czy zmiana poprawiła agenta, polega na tym, że ktoś
ręcznie wpisuje kilka promptów i próbuje pamiętać, jak wyglądała poprzednia
odpowiedź.

Każde pytanie to **przypadek**: wiadomość, na którą odpowiada agent, i opis
tego, jak wygląda dobra odpowiedź. Przypadki pochodzą z trzech miejsc - są
pisane w konsoli, importowane z pliku albo brane z prawdziwej rozmowy, w której
ktoś ocenił odpowiedź łapką w dół. To ostatnie źródło jest zwykle najcenniejsze,
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

Przypadek musi mówić, z czym porównuje się odpowiedź: odpowiedź wzorcowa,
kontrprzykład, oczekiwane wywołanie narzędzia albo sprawdzenie - co najmniej
jedno z czterech. Przypadek z samym wejściem nigdy nie mógłby nie przejść, więc
jest odrzucany: formularz go nie zapisze, API odpowiada 422 ze wskazaniem
`reference_answer`, a import podaje numer wiersza.

Przypadek wzięty z rozmowy zachowuje też odnośnik do runa, rozmowy i
wiadomości, z których pochodzi. Pytanie i odpowiedź są kopiowane do przypadku,
więc przypadek pozostaje kompletny także po tym, jak sam run usunie retencja.

Załączniki nie są częścią przypadku w tej wersji. Przypadek to tekst.

## Każda zmiana to nowa wersja { #versions }

Dodanie, edycja albo usunięcie przypadku oraz import pliku tworzą nową
**wersję** datasetu, numerowaną od 1. Wersja nigdy się nie zmienia po
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

Otwórz **Datasety**, utwórz dataset i wybierz **Dodaj przypadek**. Wpisz wejście
i co najmniej jedno z czterech oczekiwań opisanych wyżej. Rozmowę, oczekiwane wywołania narzędzi i sprawdzenia
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

## Poświadczenia są redagowane { #credentials }

Tekst przypadków jest kopiowany z rozmów i z plików, które ludzie wgrywają, a
potem eksportowany i podawany modelom. Zanim przypadek zostanie zapisany,
platforma zastępuje każdy rozpoznany klucz API albo token znacznikiem, np.
`[redacted:github_token]`. Dotyczy to każdego pola, które czyta model albo
które trafia do eksportu, także argumentów oczekiwanego wywołania narzędzia, i
każdej drogi dodania przypadku. Wpis audytu dla zmiany zapisuje, ile wartości
zredagowano, nigdy same wartości.

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
