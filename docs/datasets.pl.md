---
source_sha: "93c168eefee1"
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
| Sprawdzenia | Reguły dotyczące odpowiedzi, każda jako obiekt, którego `type` nazywa regułę, a obok są jej parametry. [Ocenianie](#checks) wymienia typy, a przypadek z typem, którego nie zna, jest odrzucany |
| Tagi | Etykiety do grupowania wyników, np. `billing` albo `refusal` |
| Notatka | Po co jest ten przypadek - co poszło źle albo czego pilnuje |
| Źródło | `manual`, `import`, `conversation` albo `synthetic` - ustawia je platforma, nie wpisuje się go |

Przypadek musi mówić, z czym porównuje się odpowiedź: odpowiedź wzorcowa,
kontrprzykład, oczekiwane wywołanie narzędzia albo sprawdzenie - co najmniej
jedno z czterech. Przypadek z samym wejściem nigdy nie mógłby nie przejść, więc
jest odrzucany: formularz go nie zapisze, API odpowiada 422 ze wskazaniem
`reference_answer`, a import podaje numer wiersza.

Dobry przypadek jest mały: jedno pytanie i ta jedna rzecz, którą poprawna
odpowiedź musi zrobić dobrze. Zwykle wystarczy odpowiedź wzorcowa albo
kontrprzykład. Oczekiwane wywołania narzędzi dodaj, gdy agent ma działać, a nie
tylko odpowiadać, sprawdzenia - gdy regułę da się podać dokładnie, a rozmowę
przed wejściem - tylko gdy pytanie od niej zależy. Notatka jest dla następnego
czytelnika: co poszło źle albo czego przypadek pilnuje. Przy tworzeniu
pierwszego datasetu konsola proponuje przewodnik, który kończy się napisaniem
pierwszego przypadku pole po polu.

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

Zmiana nazwy datasetu albo jego opisu, przyciskiem **Edytuj szczegóły** na jego
stronie, nie tworzy wersji, bo żadna z nich nie zmienia przypadku.

Lista wersji pokazuje sto najnowszych; starszą otwiera się, wpisując jej numer.
Każda wersja trzyma wiersz na przypadek, więc wersje jednej organizacji
trzymają łącznie najwyżej `DATASET_MAX_VERSION_ROWS_PER_ORG` wierszy (domyślnie
5 milionów, zobacz [Konfiguracja](configuration.md#datasets)). Zmiana ponad to
jest odrzucana z podaniem, ile jest zajęte; usunięcie datasetu zwalnia jego
wiersze.

## Dodawanie przypadków { #adding-cases }

### W konsoli { #in-the-console }

Otwórz **Datasety**, utwórz dataset - otwiera się, gdy tylko powstanie - i
wybierz **Dodaj przypadek**. Wpisz wejście i co najmniej jedno z czterech
oczekiwań opisanych wyżej. Rozmowę wpisuje się tura po turze, każde oczekiwane
wywołanie narzędzia jako nazwę narzędzia i jego argumenty jako wiersze nazwy i
wartości, a każde sprawdzenie jako typ wybrany z listy obok tego, co sprawdza.
**Edytuj jako JSON** pokazuje cały przypadek w postaci, w jakiej trzyma go
import.

Przypadek na liście otwiera się w postaci do czytania, z rozmową jako dymkami
czatu; **Edytuj** zamienia go w formularz, który mówi, jaką wersję utworzy zapis
i które oceniacze datasetu oceniłyby przypadek w obecnym brzmieniu. Link do
`?tab=cases&case={case_id}` na stronie datasetu otwiera jeden przypadek.

Zapisanie nowego przypadku, którego pytanie zadaje już inny przypadek - bez
względu na wielkość liter i odstępy - zatrzymuje się, żeby o tym powiedzieć, z
**Otwórz go**, by przeczytać tamten przypadek, i **Dodaj mimo to**, by zachować
oba. Sprawdza to `GET /datasets/{id}/cases?same_input=`.

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

Są dwie drogi i obie tworzą taki sam przypadek:

- **W czacie** oceń odpowiedź, a ocena zdecyduje, jako co zostanie zachowana.
  Po łapce w górę potwierdzenie proponuje **Dodaj do datasetu**: wybierz
  dataset, a odpowiedź zostanie zachowana jako odpowiedź wzorcowa. Po łapce w
  dół okno, które pyta, co poszło źle, proponuje też **Dodaj tę odpowiedź do
  datasetu**: zaznacz to, wybierz dataset i wyślij, a odpowiedź zostanie
  zachowana jako kontrprzykład. Najpierw zapisuje się ocena, a przypadek jest
  dodawany po niej, więc twój komentarz staje się notatką przypadku. To dwa
  osobne zapisy - jeśli dodanie zostanie odrzucone, ocena zostaje, a komunikat
  mówi, która połowa się nie udała. Późniejsze cofnięcie oceny zostawia
  przypadek na miejscu: to kopia, wersjonowana razem z datasetem. Konsola
  pamięta ostatnio użyty dataset, więc kolejne dodanie to jedno kliknięcie.
- **W Aktywności** każda tura agenta ma przycisk **Dodaj do datasetu**. To
  miejsce kuracji, więc dobrą odpowiedź równie łatwo zachować jako wzorcową, jak
  złą jako kontrprzykład.

W obu przypadkach przypadek powstaje z tej tury:

- pytanie staje się wejściem, a tury przed nim - rozmową przed wejściem;
- odpowiedź staje się kontrprzykładem. Jeśli nikt nie ocenił jej łapką w dół,
  domyślnie jest proponowana jako odpowiedź wzorcowa, a ty wybierasz jedno z
  dwóch;
- najnowszy komentarz zostawiony z łapką w dół staje się notatką.

Obie drogi widzą tylko członkowie, którzy mogą edytować jakiś dataset. Wiadomość musi
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

## Ocenianie { #scoring }

Dataset określa, jak oceniane są jego przypadki, w zakładce **Ocenianie**, w
trzech kartach zapisywanych razem: **Kiedy przypadek przechodzi** zawiera
sprawdzenia i oczekiwane wywołania narzędzi, **Sędzia** mówi, który sędzia
ocenia i według czego, a **Przegląd przez człowieka** mówi, co czeka na czyjąś
decyzję. Do jednego przypadku mogą mieć zastosowanie cztery oceniacze, a każdy
z nich włącza się albo wyłącza i oznacza jako **Musi przejść** albo nie:

| Oceniacz | Co porównuje | Koszt |
|---|---|---|
| Sprawdzenia | Odpowiedź z regułami przypadku oraz z domyślnymi regułami, które dataset nadaje każdemu przypadkowi | Nic |
| Oczekiwane wywołania narzędzi | Narzędzia wywołane przez agenta z oczekiwanymi wywołaniami przypadku | Nic |
| Sędzia | Odpowiedź z rubryką nazwanych kryteriów, ocenianą przez sędziego datasetu | Jeden run sędziego |
| Odpowiedź wzorcowa | Odpowiedź z odpowiedzią wzorcową przypadku, ocenianą przez sędziego datasetu | Ten sam run sędziego |

Każdy oceniacz zwraca zaliczenie albo niezaliczenie, wynik od 0 do 1 i
uzasadnienie. Przypadek **zalicza**, gdy zalicza go każdy oceniacz oznaczony
jako Musi przejść, a **nie zalicza**, gdy któryś z nich nie zalicza. Gdy któryś
z nich nie wydał werdyktu - sędzia był wyłączony, jego budżet się wyczerpał,
jego run się nie powiódł albo jego odpowiedzi nie dało się odczytać - przypadek
jest **bez oceny**: ani zaliczony, ani niezaliczony, bo nikt nie sprawdził
odpowiedzi. Wynik mówi dlaczego i po usunięciu przyczyny można go [ocenić
ponownie](#judge).

Każdy oceniacz mówi, ile przypadków zawiera to, co on czyta, a zakładka
ostrzega, gdy ustawienia widoczne na ekranie oceniałyby niektóre przypadki na
podstawie niczego. Datasetowi, którego przypadki mają odpowiedzi wzorcowe, z
którymi nic nie porównuje odpowiedzi, proponowane jest porównanie z odpowiedzią
wzorcową. Karta z niezapisaną zmianą mówi o tym, pasek na dole ekranu zapisuje
albo odrzuca wszystkie zmiany naraz, a strona pyta przed jej opuszczeniem.

Konfiguracja nie jest wersjonowana razem z przypadkami, bo to, jak zespół
ocenia, nie jest tym, o co pyta. Każdy wynik przechowuje kopię konfiguracji, z
którą został obliczony, więc starszy wynik nadal mówi, jak do niego doszło, po
zmianie konfiguracji.

Konfiguracja, która nie mogłaby niczego ocenić, jest odrzucana: wszystkie
oceniacze wyłączone albo sędzia włączony bez żadnego kryterium. Tak samo ocena
przypadku, w którym żaden ze skonfigurowanych oceniaczy nie ma czego sprawdzić -
nic nie jest zapisywane, a sędzia nie jest wywoływany.

### Sprawdzenia { #checks }

| `type` | Parametry | Zalicza, gdy |
|---|---|---|
| `contains`, `not_contains` | `value`, opcjonalnie `path`, `case_sensitive` | Odpowiedź zawiera wartość albo jej nie zawiera |
| `equals` | `value`, opcjonalnie `path`, `case_sensitive` | Odpowiedź po obcięciu białych znaków jest tą wartością |
| `regex` | `value` (najwyżej 500 znaków), opcjonalnie `path`, `case_sensitive` | Wzorzec pasuje w dowolnym miejscu odpowiedzi |
| `json_schema` | `schema`, opcjonalnie `path` | Odpowiedź to JSON zgodny z JSON Schema |
| `max_cost_usd` | `value` | Run kosztował nie więcej niż tyle |
| `max_latency_ms` | `value` | Run trwał nie dłużej niż tyle |
| `judge` | `criterion` | Sędzia evali ocenia kryterium na progu zaliczenia lub wyżej |

`path` sięga do wnętrza odpowiedzi, która jest JSON-em: `items.0.name` to nazwa
pierwszego elementu. Bez niego reguła czyta całą odpowiedź. Reguły tekstowe nie
rozróżniają wielkości liter, chyba że `case_sensitive` ma wartość true.

Wzorzec jest sprawdzany przy zapisie przypadku, a reguła czyta najwyżej pierwsze
100 000 znaków odpowiedzi. Wzorzec, który na jakiejś odpowiedzi działa dłużej
niż dziesiątą część sekundy, zostaje przerwany i zapisany jako błąd, więc jeden
wzorzec nie może zatrzymać oceniania. Z tego samego powodu JSON Schema nie może
używać `pattern` ani `patternProperties` - to samo robi check `regex` z `path`,
z tym samym limitem czasu - a jej `$ref` musi wskazywać wewnątrz schematu.

Sprawdzenie `judge` to kryterium tylko dla jednego przypadku, oceniane w tym
samym runie sędziego co rubryka datasetu. Używaj go do tego, czego reguła nie
wyrazi, np. „odmawia i nie ujawnia adresu klienta”.

### Oczekiwane wywołania narzędzi { #trajectory }

Wywołania agenta są dopasowywane do oczekiwanych wywołań przypadku po nazwie
narzędzia i po każdym argumencie, który przypadek wymienia. Tryb kolejności
przypadku decyduje, co zalicza: przy `any` nastąpiło każde oczekiwane
wywołanie; przy `in_order` nastąpiły w podanej kolejności; przy `exact` są
jedynymi wywołaniami i są w tej kolejności. Uzasadnienie wymienia, czego
brakowało, czego się nie spodziewano albo że kolejność była inna. Zapis, który
zablokował izolowany run, nadal liczy się jako wywołanie wykonane przez agenta.

Wywołanie jest dopasowywane po nazwie narzędzia zapisanej przez run, czyli po
nazwie po ewentualnym nadpisaniu w specu. Przypadek napisany przed zmianą nazwy
narzędzia oczekuje starej nazwy.

### Sędzia { #judge }

Sędzia to agent rodzaju `judge` (zobacz
[Sędziowie](concepts.md#system-agents)). Dataset ocenia za pomocą **Eval
judge**, którego platforma dodaje do każdej organizacji, albo za pomocą
własnego sędziego: **Utwórz sędziego dla tego datasetu** na karcie Sędzia
tworzy sędziego, którego prompt to prompt Eval judge z jego zasadami oceniania,
a po nim nazwa i opis datasetu oraz to, co według ciebie sędzia musi wiedzieć,
żeby oceniać - polityka, cennik - na pierwszym modelu organizacji albo na
wybranym przez ciebie. Prompt można edytować przed utworzeniem (`GET
/datasets/{id}/judge-template`). Utworzenie go wymaga `agents:edit` oraz
`datasets:edit`.

Gdy wsparcie AI jest włączone, utworzenie go od razu włącza też ocenianie:
sędziego, z kryterium startowym do zastąpienia, gdy dataset nie ma żadnego,
oraz porównanie z odpowiedzią wzorcową, gdy któryś przypadek ją ma. Kryteria,
skala i próg zaliczenia zostają na datasecie; prompt, model i budżet sędziego
edytuje się na jego własnej stronie, jedynym miejscu, gdzie ustawia się jego
model; karta Sędzia go pokazuje.

Sędzia działa jako osoba, która poprosiła o ocenę: sprawdzany jest jej dostęp do
niego, przed wywołaniem modelu sprawdzany jest jego własny budżet i budżet
organizacji, a jego run pojawia się w Activity pod powierzchnią `eval`.

Sędzia dostaje notatkę przypadku jako powód, dla którego przypadek istnieje,
jego wcześniejsze tury i pytanie, odpowiedź wzorcową, gdy jest oceniana,
kontrprzykład, każde wywołanie narzędzia wykonane przez agenta - z argumentami i
informacją, czy izolowany run je zablokował - oraz odpowiedź. Przypadek z
kontrprzykładem jest zawsze oceniany także według wymaganego kryterium
**counter-example**: odpowiedź nie może powtarzać znanej złej odpowiedzi.
Sędziowie startują z temperaturą 0, więc ta sama odpowiedź jest oceniana dwa
razy tak samo; model rozumujący, który odrzuca to ustawienie, wymaga
wyczyszczenia go na stronie sędziego.

Sędzia działa tylko tam, gdzie włączone jest [wsparcie AI](governance.md#ai-assistance),
a jest ono wyłączone, dopóki administrator nie włączy go dla organizacji. Do
tego czasu kryteria sędziego i odpowiedzi wzorcowej są zapisywane jako
pominięte, oceniają tylko oceniacze oparte na regułach, a zakładka Ocenianie
mówi o tym i podaje link do przełącznika temu, kto może go zmienić. W tym czasie nie da
się włączyć sędziego ani porównania z odpowiedzią wzorcową; już włączony zostaje
włączony i jest pomijany.

Każde kryterium jest oceniane od 1 do górnej granicy skali i zalicza na progu
zaliczenia lub wyżej. Przy każdym kryterium sędzia cytuje fragment odpowiedzi,
na którym opiera ocenę, i podaje regułę, z której ocena wynika. Ocena, której
uzasadnienie składa się głównie ze słów samego kryterium, bez cytatu, który
odpowiedź zawiera, jest błędem: nic nie pokazuje, że sędzia przeczytał
odpowiedź. Najwyższa ocena bez cytatu z odpowiedzi zostaje, oznaczona jako
niezweryfikowana.

Gdy sędzia nie może ocenić, jego kryteria są zapisywane jako pominięte albo
jako błędy, z uzasadnieniem podającym przyczynę: wsparcie AI jest wyłączone,
sędzia wybrany przez dataset już nie istnieje, nie ma opublikowanej wersji,
jest zarchiwizowany, jego model został usunięty albo nie ma klucza, osoba nie
może go uruchomić, jego budżet się wyczerpał, jego run się nie powiódł albo
jego odpowiedzi nie dało się odczytać - wtedy jej pierwsze 200 znaków zostaje
obok uzasadnienia. Oceniacze oparte na regułach nadal oceniają.

Po usunięciu przyczyny **Oceń ponownie** na wyniku bez oceny - albo na
wszystkich w grupie runu ewaluacji na zakładce Przegląd - ocenia tę samą
odpowiedź od nowa, z konfiguracją, z którą była oceniona za pierwszym razem
(`POST /datasets/{id}/scores/rescore`, do dziesięciu wyników na żądanie). Agent
nie uruchamia się ponownie, a wynik zachowuje swój run ewaluacji i decyzję,
którą ktoś na nim podjął; wynik, na którym każdy oceniacz wydał werdykt,
zostaje bez zmian.

Ocena może cytować odpowiedź, do 12 fragmentów; cytat, którego odpowiedź nie
zawiera słowo w słowo, jest zachowywany obok oceny jako niezweryfikowany,
pokazywany w osobnej linii pod uzasadnieniem, a ocena pozostaje.

Każdy wynik zapisuje sędziego, który go ocenił - agenta sędziego, jego profil
modelu, wersję spec, hash rubryki i wersję zadania, które platforma przekazuje
każdemu sędziemu - więc wyniki od różnych sędziów nie są porównywane jak równe z
równym. Zmiana sędziego albo jego modelu na jego stronie jest dozwolona;
przełączenie sędziego wymaga najpierw potwierdzenia, a karta Sędzia mówi, że
wyniki ocenione wcześniej nie będą porównywalne z ocenianymi później.

### Przegląd { #review }

Wynik czeka w **kolejce przeglądu**, gdy ktoś go tam wyśle albo zrobi to run
ewaluacji. Po ponownym uruchomieniu tego, co się zmieniło, run ewaluacji wysyła
potwierdzone regresje i odpowiedzi, których sędzia nie ocenił - po jednym wyniku
na przypadek i żadnego dla przypadku, który już czeka. Jego strona wysyła inne
wybrane przez ciebie wyniki, wszystkie naraz przez `POST
/datasets/{id}/scores/review`, do 500 identyfikatorów wyników - wszystkie albo
żaden.

Wynik, o który poproszono ręcznie z Activity, podlega ustawieniu **Przegląd
przez człowieka** datasetu: nic, dopóki ktoś czegoś nie wyśle, każdy wynik,
który nie zaliczył, albo każdy wynik. Wynik już rozstrzygnięty pozostaje
rozstrzygnięty.

Zakładka **Przegląd** otwiera się na tym, co czeka na decyzję, a wszystkie
wyniki są o jedno kliknięcie dalej, każdy filtr ze swoją liczbą; widok zawęża
się według rezultatu, agenta, który odpowiedział, i tagu przypadku. Wyniki
każdego runa ewaluacji zbiera pod jednym nagłówkiem z linkiem do runa, skąd
można je wyjąć z kolejki bez decyzji
(`POST /datasets/{id}/scores/review/withdraw`).

Każda karta pokazuje, o co pytał i czego oczekiwał przypadek - pytanie z linkiem
do przypadku, odpowiedź wzorcową, oczekiwane wywołania narzędzi i sprawdzenia -
odpowiedź w postaci, w jakiej została oceniona, który agent i która wersja
odpowiedziały - z ostrzeżeniem, gdy sędzia oceniał na modelu, który odpowiadał,
bo sędzia może faworyzować odpowiedzi podobne do własnych - co ustalił każdy
oceniacz i dlaczego, najpierw niezaliczone, oraz decyzję przeglądu, którą można
cofnąć z komunikatu, który ją potwierdza.

Notatka zostawiona przy decyzji to często reguła, którą sędzia przeoczył, więc
karta proponuje zamienić ją w kryterium sędziego: tylko dla tego przypadku,
jako sprawdzenie `judge` w nowej wersji datasetu, albo dla każdego przypadku, w
rubryce, co włącza sędziego.

Karta pulpitu **Do przeglądu** pokazuje kolejkę ze wszystkich datasetów, które
widzisz: ile wyników nie zaliczyło, było bez oceny albo zaliczyło, i w których
datasetach, a każdy otwiera się w zakładce Przegląd. Karta jest domyślnie na
pulpicie.

Decyzja przeglądu osoby jest zapisywana obok wyników oceniaczy i rozstrzyga o
rezultacie. Nigdy nie zmienia tego, co powiedział sędzia: oceny i uzasadnienia
sędziego zostają w wyniku po tym, jak decyzja je uchyli. Decyzję można wycofać,
a wtedy wynik znowu czeka na przegląd.

### Ocenianie runa { #scoring-a-run }

W **Aktywność** otwórz run, otwórz jego menu **⋯** i wybierz **Oceń względem
przypadku**. Przypadek, który zadaje to samo pytanie co run, jest wybierany za
ciebie; gdy dataset takiego nie ma, okno dialogowe proponuje dodanie odpowiedzi
runa jako przypadku. Odpowiedź i wywołania narzędzi runa są oceniane każdym
oceniaczem, który dataset konfiguruje. Run bez transkryptu nie ma odpowiedzi do
oceny.

| Aby | Potrzebujesz |
|---|---|
| Zmienić sposób oceniania datasetu | `datasets:edit` na nim |
| Utworzyć dla niego sędziego | `datasets:edit` na nim oraz `agents:edit` |
| Ocenić run względem niego | `datasets:run` na nim oraz `runs:view` |
| Czytać jego wyniki | `datasets:view` na nim |
| Wysłać wyniki do przeglądu, zapisać albo wycofać decyzję | `datasets:edit` na nim |

Uzasadnienie napisane przez sędziego przechodzi przed zapisaniem przez tę samą
redakcję poświadczeń co przypadek.

## Dostęp { #access }

Dataset jest współdzielonym zasobem z właścicielem, widocznością i
grantami, tak jak [skill](skills.md) albo [plik kontekstowy](context.md). Nowy
dataset widzi cała organizacja, chyba że twórca od początku ustawi go jako
prywatny; później zmienia się to na stronie datasetu. Katalog ma trzy
uprawnienia dla datasetów:

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

Wynik jest przechowywany tak samo. Zawiera kopię ocenianej odpowiedzi, do 8000
znaków ze zredagowanymi poświadczeniami, żeby recenzent czytał ją obok
przypadku. Ta kopia wraca w eksporcie osoby, do której należał run, i jest
czyszczona, gdy ta osoba zostanie wymazana. Gdy run, który ocenił, zostanie
usunięty, wynik zostaje bez powiązania z nim, a gdy osoba, która o niego
poprosiła albo o nim rozstrzygnęła, zostanie wymazana, jej nazwisko jest z niego
czyszczone. Uzasadnienie sędziego może cytować ocenianą odpowiedź.
