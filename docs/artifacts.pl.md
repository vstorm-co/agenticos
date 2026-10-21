---
source_sha: "3394e53d70df"
---

# Artefakty { #artifacts }

**Artefakt** to strona opublikowana przez agenta: raport, mały dashboard,
jednostronicowe podsumowanie, które ktoś otwiera w przeglądarce. Ma link, który
się nie zmienia, gdy agent publikuje ją ponownie, więc „w każdy poniedziałek
opublikuj liczby z tygodnia na tej stronie” to jeden link, który ludzie dodają do
zakładek, a nie nowy co tydzień.

Artefakt nie jest plikiem. Wykres, wygenerowany PDF i plik w workspace'ie mają już
swoje miejsce w czacie i w [workspace'ie](sandbox.md). Artefakt to rzecz, która
jest *serwowana*: ma właściciela, widoczność i granty, tak jak agent czy skill, i
można mu nadać publiczny link dla kogoś bez konta.

## Publikowanie artefaktu { #publishing-one }

Włącz agentowi capability **Artifacts**. Dodaje ona cztery narzędzia:
`publish_artifact`, które model wywołuje, gdy wynik jest czymś, co człowiek
powinien otworzyć, a nie przeczytać raz w czacie; `read_artifact`, które
odczytuje opublikowaną stronę z powrotem; `list_artifacts`, które wymienia
strony, jakie run może otworzyć; oraz `preview_artifact`, które rysuje stronę i
mówi, co jest w niej nie tak.

Strona pochodzi z jednego z trzech miejsc:

- **Z pliku w workspace'ie agenta**, zakończonego na `.html` albo `.md`. To
  zwykły przypadek dla agenta z capability [Files & shell](reference/capabilities.md#files-shell):
  zapisuje `report.html`, uruchamia to, co go buduje, a potem publikuje plik.
  Bajty są czytane przez własny backend workspace'u runa, więc działa to na
  każdym backendzie sandboksa.
- **Ze strony przekazanej inline** — dla agenta bez workspace'u albo dla krótkiej
  strony.
- **Z edycji strony opublikowanej już** pod tą nazwą — zobacz niżej.

Czat pokazuje kartę opublikowanej strony. Karta prowadzi do wersji, którą
opublikował *ten* run, więc późniejsze czytanie rozmowy nadal pokazuje to, co w
niej opublikowano, a nie to, co strona pokazuje dziś.

### Zmiana części strony { #changing-part-of-a-page }

Zmiana jednego słowa nie powinna kosztować całej strony od nowa. Agent wywołuje
`read_artifact` z nazwą strony, co zwraca bieżącą wersję taką, jaką ją napisano,
a potem `publish_artifact` z tą samą nazwą i `edits`: dokładnymi zamianami,
nakładanymi po kolei. Każda musi pasować dokładnie do jednego miejsca na stronie;
brak dopasowania albo dopasowanie niejednoznaczne wraca do modelu do poprawienia.
Wynikiem jest nowa wersja, jak każda inna.

Edycje niosą wersję, na której je zrobiono. Jeśli w międzyczasie opublikował inny
run, nic nie jest zapisywane, a model dostaje polecenie, żeby przeczytał stronę
jeszcze raz — edytowana kopia starszej strony nigdy nie zastępuje nowszej. Odczyt
podlega tej samej zasadzie co otwarcie strony w konsoli: osoba, w imieniu której
działa run, musi mieć prawo ją otworzyć. Strona dłuższa niż 100 000 znaków wraca
ucięta i to mówi; edycja nadal może wskazać tekst za cięciem.

### Ponowne odnalezienie strony { #finding-a-page-again }

Każda wiadomość to nowy run, a run widzi wcześniejsze tury tylko jako tekst, więc
model nie pamięta nazw, pod którymi publikował. `list_artifacts` wymienia strony
agenta w środowisku runa, od najnowszej, najwyżej 50: każdą z nazwą, tytułem,
bieżącą wersją, formatem, bindingami na żywo, widocznością, informacją, czy
publiczny link jest włączony, datą publikacji, linkiem do konsoli i `may_edit` —
czy publikacja pod tą nazwą z tego runa zaktualizuje stronę, zamiast zostać
odrzucona. Model sprawdza listę, zanim wybierze nową nazwę.

Lista jest czytana jako osoba, dla której działa run, według zasady konsoli: jej
własne strony, strony organizacji i udostępnione jej, albo każda strona dla roli,
która widzi wszystkie strony. W czacie grupowym kanał widzi tylko strony całej
organizacji: nigdy prywatnych ani zespołowych stron mówiącego ani strony
udostępnionej tylko mówiącemu. Powierzchnia, na której nikt nie jest zalogowany,
na przykład publiczny widget, nie wymienia niczego.

## Dane na żywo { #live-data }

Strona może pokazywać rekordy z [Virtual Tables](virtual-tables.md), które są
aktualne, zamiast kopii, z którą ją opublikowano. Agent przekazuje `bindings` do
`publish_artifact`: każdy binding to nazwa, [zapisany widok](virtual-tables.md#saved-views)
i kolumny, które strona z niego czyta. `list_views` daje agentowi id i kolumny
każdego widoku. Strona wywołuje `agenticos.onData(render)`, a `render(data)` działa
z pierwszymi danymi i ponownie przy każdym odświeżeniu. `agenticos.data` to Promise
pierwszych danych.

```js
agenticos.onData((data) => {
  // data.tickets = { status, records, fields, count, truncated, limit, filters_dropped }
});
```

Każdy binding przychodzi jako `status` (`ok` albo `unavailable`), `records`
(`{id, <field>: value}`), `fields` (etykieta, typ, opcje i stan każdego pola),
`count`, `truncated`, `limit` i `filters_dropped`, ustawione na true, gdy filtr
widoku wskazuje kolumnę, której już nie ma — wtedy rekordy obejmują więcej, niż
widok zakładał.

Strona, która nie dostanie odpowiedzi w ciągu 10 sekund, widzi każdy
binding jako `unavailable`; listener dodany później pyta jeszcze raz.

Binding jest `unavailable`, gdy ten oglądający nie może czytać jego widoku albo
widok zniknął. Pole, którego kolumnę usunięto, jest serwowane pod swoją nazwą pola
jako pole `text` o wartości `null` i stanie `missing`; zarchiwizowana kolumna daje
`null` ze stanem `archived`.

Rekordy są czytane **wtedy, gdy ktoś ogląda stronę, z własnym dostępem tego
oglądającego**, i nigdy nie są w niej przechowywane. Dwie osoby, które otworzą tę
samą stronę, mogą zobaczyć różne wiersze. Wynik publikacji wymienia każde pole
jako `Label (type)`, więc agent może sprawdzić, czy związał kolumnę, o którą mu
chodziło; binding przeniesiony bez zmian mówi `kept`.

Prywatny widok obsługuje tylko swojego właściciela. Związanie strony z takim
widokiem nadal ją publikuje, a `warning` w wyniku dostaje wiersz mówiący, że
dopóki widok nie zostanie udostępniony, rekordy widzi tylko ta osoba — agent jej
to przekazuje. Czy zobaczy je kolega, rozstrzyga się tam, gdzie strona jest
udostępniana: zobacz
[Kto widzi rekordy strony na żywo](#who-sees-a-live-pages-records).

Wersja 3 [biblioteki stron](#the-library-set) rysuje binding za agenta:
`AO.records("#tickets", data.tickets)` wewnątrz `agenticos.onData` renderuje
rekordy jako tabelę z nagłówkiem z etykiet pól, liczbami i datami wyrównanymi do
prawej, wyborami jako plakietkami i każdą wartością wpisaną jako tekst. Zanim
przyjdą dane, pokazuje wiersz ładowania, a binding `unavailable` albo pusty,
ucięta lista i pominięty filtr dostają każdy własny komunikat. `AO.onData` w
wersji 3 to to samo wywołanie co `agenticos.onData`. Strona z bindingami, której
skrypt nigdy nie prosi o dane, nadal się publikuje, z
[ostrzeżeniem](#the-page-contract-and-the-publish-warnings).

Nazwa bindingu składa się z małych liter, cyfr i `_`. Pole można nazwać tak, jak
podpisana jest jego kolumna: słowami z liter dowolnej wielkości, cyfr i `_`,
rozdzielonymi pojedynczą spacją, np. `Status` albo `Created At`. Obie nazwy mają
najwyżej 64 znaki, a `__proto__`, `constructor` i `prototype` są zarezerwowane dla
obu (dla pola także `id`). Strona ma najwyżej 5 bindingów, a binding najwyżej 50 pól.

### Co widzi oglądający { #what-the-viewer-sees }

Strona z bindingami pokazuje plakietkę **Live** na swojej karcie, w widgecie
artefaktów na dashboardzie i w podglądzie. W podglądzie jej kropka pulsuje, gdy
dane napływają, i robi się bursztynowa, gdy część źródeł jest dla tego
oglądającego niedostępna. Oglądający, który nie może odczytać żadnego z nich, nie
widzi plakietki; nie ma jej też na starszej wersji.

Podgląd ma przycisk **Refresh**, który czyta dane ponownie i aktualizuje w miejscu
stronę korzystającą z `agenticos.onData`; w podpowiedzi przycisku widać, kiedy dane
odczytano ostatnio. Obok jest menu automatycznego odświeżania: wyłączone, co minutę,
co 5 albo 15 minut albo co godzinę. Każdy oglądający wybiera własne ustawienie, a wybór jest
zapamiętywany per strona w tej przeglądarce.

Automatyczne odświeżanie nic nie robi, gdy karta jest ukryta, i czyta raz, gdy karta
wraca, jeśli jakiś takt został pominięty. Zatrzymuje się, gdy dostęp do danych
zostaje odmówiony (strona nie istnieje już dla tego oglądającego) i gdy żadnego
źródła na stronie nie da się odczytać — dopóki oglądający nie kliknie Refresh i
odczyt się nie powiedzie. Błąd, który nic nie mówi o stronie, na przykład błąd
serwera, nie przerywa odpytywania. Odpowiedź „zajęty” (429) jest ponawiana dwa
razy, co sekundę, zanim oglądający zobaczy komunikat „Busy, try again in a
moment.”

Wiersz pod paskiem pojawia się tylko wtedy, gdy coś wymaga uwagi. Strona, do której
dostępu odmówiono, mówi „This page's live data is not available to you.” Czytelnik,
którego źródeł nie da się odczytać, widzi, ilu („2 of 3 sources unavailable to
you”). Edytor, czyli każdy, kto może edytować stronę, widzi też dla każdego źródła
powód (na przykład jego zapisanego widoku już nie ma, jego tabela jest zarchiwizowana,
agent nie dostał grantu na tabelę albo nie możesz czytać jego zapisanego widoku) z
linkiem **Open the table** do związanego widoku.

Gdy agent opublikuje nową wersję, a ktoś ma otwartą bieżącą, najbliższy odczyt
(odświeżenie, ręczne albo automatyczne) przenosi podgląd na nową wersję: strona
ładuje się ponownie z nowej wersji, z jej własnymi danymi. Oglądający, który wybrał
wersję z menu wersji, zostaje przy niej.

Na starszej wersji dane na żywo nie są czytane. Podgląd mówi „Live data only on the
current version.” z przyciskiem **Open current**, a edytorowi pokazuje też
**Restore** dla tej wersji. Przywrócenie wersji, której źródła danych na żywo są
niedostępne, mówi, które to są.

### Limity { #limits }

Każda odpowiedź jest ograniczona, więc jedna strona nie położy wdrożenia:

| Limit | Wartość |
|---|---|
| Bindingi na stronę | 5 |
| Rekordy na binding | 1000 |
| Dane po ukształtowaniu na stronę | 4 MiB, podzielone sprawiedliwie między bindingi |
| Jedno zapytanie | najwyżej 2 s |
| Jedna strona | termin 5 s |
| Ładowania danych | 30 na minutę na oglądającego, jedno w toku na oglądającego i limit na proces |

Ucięty binding mówi `truncated: true`, z `limit` ustawionym na `records` albo
`bytes` i `count` równym liczbie podanych rekordów. `bytes` obejmuje też odczyt,
którego zmierzony koszt wyczerpał się, zanim ukształtowane dane wypełniły przypadającą
na binding część strony.

Termin jest egzekwowany bez anulowania żadnego zapytania: każde zapytanie trwa
najwyżej krócej z 2 s i czasu pozostałego z 5 s, a po wyczerpaniu 5 s żadne nowe
zapytanie nie startuje, więc strona odpowiada w około 5 s. Po przekroczeniu limitu
zapytań trasa odpowiada 429; konsola ponawia odpowiedź „zajęty” dwa razy. Gdy Redis
nie działa, dolny próg limitu zapytań i limit żądań w toku liczą się per worker API,
a limit na proces nadal ogranicza każdy worker.

### Kto może opublikować stronę z bindingami { #who-may-publish-a-bound-page }

Strona wiąże się z tabelą tylko wtedy, gdy spec publikującego agenta przyznaje
odczyt tej tabeli, co jest sprawdzane przy publikacji strony albo przywróceniu
wersji. Późniejsze odebranie grantu nie zatrzymuje stron już opublikowanych, a każdy
oglądający nadal czyta tylko to, na co pozwala mu jego własny dostęp.

Stronę z bindingami może ponownie opublikować tylko run działający w imieniu
członka: zalogowanego członka (czat webowy, HTTP API), powiązanego nadawcy z kanału
albo twórcy harmonogramu. Odwiedzający widget, embed albo hostowaną stronę,
niepowiązany nadawca z kanału i dostarczenie triggera zdarzeniowego agenta (GitHub,
e-mail, przekaźnik webhooków) się nie liczą, podobnie jak run workflow przyjęty
przez publiczne wejście albo cokolwiek w łańcuchu takiego runa.

## Jedna nazwa, jeden link { #one-name-one-link }

Tożsamością artefaktu jest jego **nazwa w obrębie agenta** — `weekly-report`,
`churn-dashboard`. Publikacja pod tą samą nazwą aktualizuje ten sam artefakt, z
dowolnej powierzchni: z czatu, z API, z [triggera](triggers.md) albo z workflow.
Nowa nazwa tworzy nową stronę. Nazwa składa się z małych liter, cyfr i łączników,
maksymalnie 64 znaki.

Nazwa obowiązuje też **w obrębie środowiska**, z którego odpowiedział run. Run w
nazwanym [środowisku](environments.md) — `staging`, `dev` — publikuje własną
stronę obok strony środowiska domyślnego, więc próba nowej wersji agenta nie może
ponownie opublikować strony, którą czytelnicy produkcji mają w zakładkach.
Środowisko jest odczytywane z samego runa, nigdy od modelu, a lista i strona je
pokazują.

Nazwę dzielą wszyscy, którzy uruchamiają agenta, ale stronę już nie. Run
publikuje ponownie istniejący artefakt tylko wtedy, gdy osoba, w której imieniu
działa, jest jego właścicielem albo ma na nim `artifacts:edit` — z roli albo z
grantu `edit`, ta sama zasada co przy zarządzaniu nim w konsoli. Run każdego
innego dostaje informację, że nazwa jest zajęta, i publikuje pod inną, więc
kolega, który poprosi tego samego współdzielonego agenta o `weekly-report`, nie
podmieni strony za Twoim linkiem.

Każda publikacja to nowa **wersja**. Nic nie jest nadpisywane, więc lista wersji
na stronie artefaktu jest historią strony. Dwie rzeczy utrzymują tę historię w
granicach:

- Publikacja dokładnie tych bajtów, które trzyma bieżąca wersja, nie dodaje
  wersji. Wynik mówi `unchanged`, a harmonogram, który nie znalazł nic nowego,
  zostawia historię w spokoju. To nadal liczy się jako publikacja, więc zegar
  retencji startuje od nowa.
- Zachowywane są tylko najnowsze wersje, `ARTIFACT_MAX_VERSIONS` z nich
  (domyślnie 20). Starsza wersja jest usuwana, gdy pojawia się nowa — poza tą, do
  której przypięty jest publiczny link. Rozmowa, która linkuje do usuniętej
  wersji, mówi, że wersja nie jest już przechowywana, i proponuje najnowszą.

**Restore this version** przywraca zachowaną wersję. Członek, który może edytować
stronę, otwiera wersję i ją przywraca; dodaje to nową wersję z bajtami starej,
więc historia zachowuje to, co się stało, a przywrócenie można cofnąć tak samo.
Nic nowego nie jest zapisywane w magazynie. Trafia to do dziennika audytu. Nowa
wersja mówi, skąd pochodzi: lista wersji pokazuje ją jako `v4 · restored from v2`,
a API podaje jej numer w `restored_from`, które publikacja zostawia puste.

## Obsługiwane formaty { #supported-formats }

| Format | Co jest przechowywane | Co jest serwowane |
|---|---|---|
| HTML (`.html`, `.htm` albo `format: html`) | Dokument tak, jak agent go napisał | Ten sam dokument, poprzedzony krótkim skryptem platformy (zobacz [Jak strona jest izolowana](#how-the-page-is-isolated)) |
| Markdown (`.md`, `.markdown` albo `format: markdown`) | Źródło w Markdownie | Źródło wyrenderowane do prostej strony, razem z tabelami. Surowy HTML w nim jest escapowany |

Jedna wersja to jeden samodzielny dokument o rozmiarze najwyżej
`ARTIFACT_MAX_BYTES` (domyślnie 5 MiB). Nie ma paczek wieloplikowych: wstaw własny
skrypt, style i obrazy (jako URI `data:`) do tego jednego pliku.

!!! warning "Strona nie ma sieci"

    Skrypty działają, więc wykres rysowany przez bibliotekę zadziała. Ale strona
    nie może niczego skądkolwiek załadować ani niczego nigdzie wysłać — skrypt z
    CDN, font z adresu URL i wywołanie API kończą się błędem. Wyjątkami są
    zestaw bibliotek poniżej, który wdrożenie serwuje samo, i
    [dane na żywo](#live-data), które konsola przekazuje stronie z
    zadeklarowanymi bindingami. Narzędzie mówi to modelowi. To celowe, a
    [Jak strona jest izolowana](#how-the-page-is-isolated) wyjaśnia dlaczego.

### Zestaw bibliotek { #the-library-set }

Wdrożenie serwuje kilka plików obok każdej strony, żeby model przestał wklejać do
każdej całą bibliotekę wykresów. Strona ładuje je adresem względnym i działa dalej,
jeśli wdrożenie przeniesie później treść do innego originu:

| Adres na stronie | Co to jest |
|---|---|
| `lib/chart-4.5.1.umd.min.js` | Chart.js 4.5.1, jako `window.Chart` |
| `lib/d3-7.9.0.min.js` | d3 7.9.0, jako `window.d3` |
| `lib/lucide-1.46.0.min.js` | Ikony Lucide 1.46.0, jako `window.lucide` - ten sam zestaw, którego używa konsola |
| `lib/agenticos-3.css` | Biblioteka stron: wygląd konsoli dla stron, jasny i ciemny, oraz komponenty `ao-`, z których buduje się stronę |
| `lib/agenticos-3.js` | `window.AO`: Chart.js w stylu konsoli, formatowanie liczb w języku strony, ikony, zakładki, `AO.onData` i `AO.records` |
| `lib/agenticos-2.css`, `lib/agenticos-2.js` | Poprzednia wersja biblioteki, zostawiona dla stron opublikowanych z nią |
| `lib/agenticos-1.css` | Pierwsza wersja wyglądu, zostawiona dla stron opublikowanych z nią |

Każda nazwa niesie swoją wersję i jest cache'owana przez rok. Aktualizacja dodaje
nowy plik obok starego, więc strona opublikowana z jedną wersją dalej ją dostaje,
a raz wydanego pliku nikt nie edytuje. Nic nie jest pobierane spoza wdrożenia,
więc wdrożenie bez dostępu do internetu działa tak samo. Pliki są wymienione w
`backend/app/core/catalog/artifact_lib/`.

Wersja 3 zachowuje każdą klasę i każde wywołanie wersji 2. Wybacza też znaczniki,
które model pisze niedbale: tytuł, podtytuł i wiersz metadanych wstawione wprost
do nagłówka układają się jeden pod drugim, zamiast rozjeżdżać się po nim, tabela
zbudowana bez `<thead>` i tak dostaje wiersz nagłówka, a komunikat wpisany w
opakowanie tabeli dostaje marginesy. Dodaje wiersze ładowania i notatek, wiersz
podpisu, kropkę „na żywo”, listy, pasek narzędzi z polami oraz ikonę i akcje
nagłówka. Rysowane są też ikony, które skrypt dodaje po załadowaniu strony, tak
jak robią to rekordy strony na żywo.

Dołączony [skill](skills.md) **`artifact-pages`** uczy agenta z nich korzystać:
obowiązkowy szkielet, każda klasa biblioteki, trzy szablony (dashboard, raport i
tabela na żywo rysowana przez `AO.records`), styl domu, ikony zamiast emoji i
sposób zmiany strony przez `read_artifact`. Nowa organizacja dostaje go razem z
innymi dołączonymi skillami, istniejąca przez `seed-skills`, a zakładka
**Page style** capability Artifacts w Builderze go proponuje. Edytuj skill, żeby
opisać własny branding, a agent będzie się go trzymał.

### Kontrakt strony i ostrzeżenia przy publikacji { #the-page-contract-and-the-publish-warnings }

Agent nie widzi strony, którą publikuje, więc platforma mówi mu, jak strona ma
wyglądać i co wygląda źle w tej, którą wysłał.

Capability Artifacts daje każdemu agentowi, który ją ma, krótki **kontrakt
strony** w instrukcjach, niezależnie od tego, czy skill jest związany: szkielet
(doctype, viewport, `lang`, arkusz stylów i skrypt biblioteki w tej kolejności,
`main.ao-page` i nagłówek), zamkniętą listę najczęściej używanych klas biblioteki,
ikony Lucide zamiast emoji i `AO.records` dla związanych danych.

Gdy run agenta oferuje skill `artifact-pages`, a go nie załadował, jego pierwsza
cała strona HTML wraca raz z prośbą, żeby załadować skill i zbudować stronę od
nowa. Dzieje się to raz na run; każda nowa wiadomość to nowy run, więc może się
powtórzyć w późniejszej turze. Edycja nigdy nie wraca.

Opublikowana strona HTML jest potem sprawdzana, a wynik niesie `warning` z jednym
wierszem na każdy znaleziony problem. Strona jest publikowana tak czy inaczej.
Sprawdzane są:

- brak `<!doctype html>` w pierwszym wierszu albo brak meta viewport;
- klasa `ao-`, w znacznikach albo wymieniona w skrypcie, której nie definiuje ani
  wersja biblioteki ładowana przez stronę, ani jej własny `<style>`;
- tabela bez `<thead>` albo bez klasy `ao-table`;
- ikony `data-lucide` bez `lib/lucide-1.46.0.min.js`;
- `AO.onData` albo `AO.records` na stronie, która nie ładuje `lib/agenticos-3.js`;
- strona z bindingami, której skrypt nigdy nie wywołuje `agenticos.onData` ani nie
  czyta `agenticos.data`, więc nie pokazuje żadnych rekordów.

### Jak wygląda strona: podgląd { #seeing-the-page-preview }

`preview_artifact` rysuje bieżącą wersję strony tak, jak zobaczy ją ktoś, kto ją
otworzy, w szerokości 1280 pikseli, i daje modelowi obraz oraz pisemny raport.
Raport podaje dane każdego bindingu (rekordy, ucięcie albo niedostępność i jej
powód), czy strona poprosiła o dane, nieprzechwycone błędy z numerem wiersza,
błędy i ostrzeżenia konsoli, co odrzuciła polityka bezpieczeństwa strony,
odrzucone żądania, okna dialogowe i opisane wyżej ostrzeżenia przy publikacji.
Obraz ma najwyżej 2400 pikseli wysokości; dłuższa strona mówi, jak jest wysoka.
Strona, która po 15 sekundach nadal działa, jest tak zgłaszana, bez obrazu.

Dane są czytane jako osoba, dla której działa run, dokładnie tak, jak konsola
czytałaby je dla niej. W czacie grupowym da się podejrzeć tylko stronę całej
organizacji, te same strony, które pokazuje tam lista, i jest ona rysowana bez
danych. Powierzchnia, na której nikt nie jest zalogowany, nie podgląda niczego.
Nic, o co prosi strona, nie trafia do sieci: API odpowiada na każde żądanie
stroną, [zestawem bibliotek](#the-library-set) albo odmową.

Obraz wymaga przeglądarki uruchomionej przez operatora, wskazanej w
[`ARTIFACT_RENDER_CDP_URL`](configuration.md#published-artifacts), i dodatku
`browser` backendu. To ustawienie należy wyłącznie do operatora: jest oddzielone
od hostów, którymi może sterować agent przeglądający strony, i żaden agent nie może
skierować na nie przeglądarki. Bez któregokolwiek z nich narzędzie nadal zwraca
raport, bez obrazu, i mówi, że wdrożenie nie ma renderera. Dla modelu, który nie
czyta obrazów, wyłącz **Preview screenshot** w ustawieniach capability; raport
nadal wraca. `agenticos cmd doctor` mówi, czy renderer odpowiada.

## Kto może go otworzyć { #who-can-open-it }

Nowy artefakt jest **prywatny** dla osoby, w imieniu której działał publikujący
run: dla osoby na czacie albo dla twórcy triggera. Prywatną stronę widzą też
role Owner, Admin, Builder i Operator.

Jego link - ten, na który wskazują karta w czacie i odpowiedź agenta - otwiera
samą stronę (karta w czacie otwiera ją w nowej karcie), na całe okno, pod
jednym paskiem z tytułem, wersją i przyciskiem **Share**. Sam link nikogo nie
wpuszcza: otwiera się tylko zalogowanemu członkowi, którego wpuszczają już
poniższe zasady. Link wskazuje organizację, w której jest artefakt (`?org=`), więc członek kilku organizacji trafia do
właściwej.

Pod **Share** każdy, kto może nim zarządzać, może go udostępnić
na trzy sposoby:

| Zasięg | Jak | Kto |
|---|---|---|
| Konkretne osoby | Grant, na poziomie `read` albo `edit` | Ci członkowie, w tej organizacji |
| Organizacja | Widoczność ustawiona na całą organizację | Każdy członek, którego rola sięga do udostępnionych artefaktów |
| Każdy, kto ma link | **Create a public link** | Każdy, kto zna adres, bez konta |

Udostępnianie i widoczność korzystają z tego samego panelu i tych samych reguł co
agenci i skille; zobacz [Uprawnienia](permissions.md). Zarządzanie artefaktem —
udostępnianie go, jego publiczny link i jego ustawienia, przywracanie wersji,
usuwanie — wymaga `artifacts:edit` na tym artefakcie, z roli albo z grantu `edit`.
Otwarcie go wymaga `artifacts:view`.

Agent nie może poszerzyć grona czytelników strony. Agent publikuje; o tym, kto ją
widzi, decyduje człowiek. Dlatego capability domyślnie nie prosi o zatwierdzenie:
pierwsza publikacja jest prywatna, a o tym, co pokazuje strona z bindingami,
decyduje w chwili oglądania własny dostęp każdego oglądającego. Autor, który chce,
żeby człowiek zatwierdzał każdą ponowną publikację już udostępnionej strony albo
strony z bindingami, ustawia `tool_approval` na `publish_artifact` w specu. Stronę
z bindingami może ponownie opublikować tylko run działający w imieniu członka
(zobacz [Dane na żywo](#live-data)).

### Kto widzi rekordy strony na żywo { #who-sees-a-live-pages-records }

Udostępnienie [strony na żywo](#live-data) pozwala komuś ją otworzyć, ale rekordy
każdego bindingu są czytane z jego własnym dostępem. Żeby je zobaczyć, potrzebuje
też prawa odczytu tabeli bindingu i widoku udostępnionego albo własnego. Strona
związana z prywatnym widokiem pokazuje więc rekordy tylko właścicielowi widoku;
wynik publikacji mówi to agentowi, żeby przekazał to dalej.

### Publiczny link { #the-public-link }

Publiczny link to `/a/<key>` pod własnym adresem konsoli, z losowym kluczem o
długości 192 bitów — według tej samej reguły co klucz hostowanej strony czatu. Nie
mówi nic o tym, kto ją opublikował ani do której organizacji należy.

**Replace the link** wydaje nowy klucz, a stary od razu przestaje cokolwiek
otwierać. **Turn off** usuwa link. Oba działania trafiają do dziennika audytu.
Strona, którą ktoś ma już otwartą, wyświetla się dalej, dopóki nie wygaśnie jej
podpisany adres treści — najwyżej `ARTIFACT_VIEW_TTL_SECONDS` (domyślnie pięć
minut).

Odwołany członek jest w tej samej sytuacji: traci artefakt przy następnym
żądaniu, a strona, którą miał już otwartą, zostaje najwyżej przez to samo okno.

Pod linkiem **Share** trzyma jego ustawienia. Zostają, gdy link jest wymieniany, a
link wyłączony i włączony ponownie je zachowuje:

| Ustawienie | Co robi |
|---|---|
| **Stops opening after** | Data, po której link niczego nie otwiera, jakby był wyłączony |
| **Shows** | Najnowszą wersję albo jedną zachowaną wersję przypiętą tak, żeby nowa publikacja nie zmieniła tego, co osoby z linkiem już widziały. Przypięta wersja nigdy nie jest usuwana |
| **Password** | Pytanie przed otwarciem strony. Link nie mówi nic — ani tytułu, ani kiedy ją opublikowano — dopóki hasło nie jest poprawne. Przechowywane jako hash, nigdy nie pokazywane ponownie; każda próba liczy się do limitu żądań linku |
| **Sites that may embed it** | Zobacz niżej |

Karta mówi też, ile razy link otwarto i kiedy ostatnio. Liczy otwarcia, nie
osoby: nic o odwiedzającym nie jest zapisywane. Każda zmiana ustawień trafia do
audytu, z nazwami zmienionych ustawień i nigdy z hasłem.

### Osadzanie na innej witrynie { #embedding-it-on-another-site }

Publiczną stronę można umieścić na stronie intranetu, w wiki albo na witrynie
klienta za pomocą `<iframe>`. Wymień witryny w **Sites that may embed it** — tylko
schemat i host, `https://intranet.example.com`, albo `https://*.example.com` dla
subdomen witryny — i skopiuj **Embed code**, który wtedy pokazuje Share.

Kod osadza `/api/v1/artifact-embed/<key>` z originu treści: mały dokument samego
wdrożenia, który z kolei osadza stronę w tym samym sandboksie co wszędzie indziej.
Jego polityka pozwala osadzić go tylko wymienionym witrynom, a polityka samej
strony pozwala osadzić stronę tylko temu dokumentowi i konsoli. Bez żadnej
wymienionej witryny nie może nikt. Strony za hasłem nie da się osadzić — osadzenie
mówi wtedy, żeby otworzyć ją na jej własnej stronie — i nikt nie loguje się w
ramce na cudzej witrynie.

## Jak strona jest izolowana { #how-the-page-is-isolated }

Artefakt to HTML ze skryptem w środku, napisany przez model, który mógł przeczytać
coś wrogiego. Jest serwowany tak, żeby nic, co robi, nie mogło dosięgnąć konsoli
ani osoby, która go ogląda:

- Bajty pochodzą z osobnej trasy, `/api/v1/artifact-content/<token>`, która nie
  czyta żadnego ciasteczka ani sesji. Token jest podpisany, wskazuje jedną wersję
  i wygasa po kilku minutach. Jest wydawany dopiero wtedy, gdy grant albo
  publiczny link dopuściły wywołującego.
- Każda odpowiedź z treścią niesie `Content-Security-Policy: sandbox
  allow-scripts allow-modals`, bez `allow-same-origin`. Strona działa w
  nieprzezroczystym originie (opaque origin), więc nie może czytać ciasteczek,
  pamięci ani strony konsoli, a żądanie, które wyśle, nie niesie niczego od
  oglądającego. To obowiązuje nawet wtedy, gdy ktoś otworzy adres treści
  bezpośrednio.
- Ta sama polityka ustawia `default-src 'none'` i `connect-src 'none'`. Jedynym
  zdalnym źródłem, jakie wymienia, jest własna ścieżka zestawu bibliotek w
  originie treści, dla skryptów, stylów i fontów. `frame-ancestors` wymienia tylko
  konsolę — a dla strony z publicznym linkiem i witrynami do osadzania także
  dokument osadzenia i te witryny. Ramka w konsoli niesie tę samą listę `sandbox`
  jako drugi zamek.
- Nie ma `allow-popups`. `connect-src` nie obejmuje nawigacji, więc link
  otwierający nowe okno byłby sposobem na wysłanie tego, co strona pokazuje, pod
  adres wybrany przez stronę. Zamiast tego każda serwowana strona dostaje najpierw
  krótki skrypt platformy: kliknięcie linku do innej witryny staje się
  wiadomością do rodzica ramki. Konsola i strona publiczna pokazują pełny adres i
  otwierają go w nowej karcie tylko wtedy, gdy człowiek się zgodzi; dokument
  osadzenia robi to samo w pasku pod stroną. Strona mogłaby wysłać tę wiadomość
  sama, więc jest ona prośbą, a nigdy zgodą — to człowiek czytający adres stoi
  między stroną po prompt injection a adresem, pod który wysłałaby swoje liczby.
- Dane na żywo przychodzą przez `postMessage` z konsoli, która pobiera je jako
  oglądający. Trasa treści nigdy nie niesie rekordów. Żądanie strony niesie nonce,
  dzięki któremu konsola dopasowuje każdą odpowiedź do właściwego załadowania
  strony; to **korelacja, a nie kontrola dostępu**. Dostępem jest własna sesja
  oglądającego na trasie danych, więc strona dostaje zawsze tylko to, co
  oglądający może czytać.
- Jeden podpisany adres ładuje swoją stronę najwyżej kilka razy na minutę, licząc
  per adres, zanim cokolwiek zostanie odczytane. Konsola i strona publiczna
  wydają świeży adres za każdym razem, gdy rysują ramkę, a wydanie go przez
  publiczny link samo jest ograniczone per link.

Lista **Artifacts** rysuje na każdej karcie bieżącą stronę jako żywą miniaturę,
przez ten sam rodzaj ramki, ze skryptem i niczym więcej: bez okien dialogowych,
bez popupów, bez formularzy. Ze skryptem, żeby dashboard, którego wykresy rysuje
biblioteka, nie był pustym płótnem na karcie. Miniatura jest bezczynna — bez
zdarzeń wskaźnika, poza kolejnością tabulacji, ukryta przed technologiami
asystującymi — i istnieje tylko wtedy, gdy jej karta jest blisko widoku, więc
długa lista uruchamia tych kilka, które czytelnik widzi, i zatrzymuje stronę,
która zjechała z ekranu.

Ponadto wdrożenie może serwować treść z **osobnej domeny rejestrowalnej**,
ustawiając `ARTIFACT_ORIGIN` — na przykład
`https://agenticos-content.example.net`, skierowaną do tego samego API. Strona
jest wtedy w zupełnie innej witrynie. Nieprzezroczysty origin już ją izoluje, więc
to jest utwardzenie, o które może poprosić przegląd bezpieczeństwa, a nie wymóg.
Ustaw zmienną dla backendu i dla frontendu, który dodaje ścieżkę treści tego
originu do swojego `frame-src`. Zobacz [Konfiguracja](configuration.md#published-artifacts).

## Archiwizacja strony { #archiving-a-page }

Archiwizacja zabiera stronę wszystkim, nie tracąc jej. Ktoś, kto może edytować
stronę, wybiera **Archive** z menu **More actions** nad nią, a dialog mówi, co to
zrobi, zanim cokolwiek się zmieni. Strona, jej wersje, granty i nazwa zostają.
Nic jej nie serwuje, dopóki nie zostanie przywrócona z tej samej strony.
Archiwizacja trafia do audytu jako `artifact.archived`, a przywrócenie jako
`artifact.unarchived`.

Dopóki strona jest zarchiwizowana, każda droga, która by ją pokazała, odpowiada
tak, jakby jej nie było:

- **Konsola.** Jej podgląd i dane na żywo są odrzucane, podobnie jak podpisany
  adres wydany przed archiwizacją. Czytelnik, który otworzy jej link, dowiaduje
  się, że nie jest dostępna. Ktoś, kto może ją edytować, widzi, kiedy ją
  zarchiwizowano, razem z **Restore** i **Delete**.
- **Listy.** Lista Artifacts i widget na dashboardzie ją pomijają. Wybierz na
  liście **Archived included**, żeby ją zobaczyć, oznaczoną jako **Archived**.
- **Publiczny link i embed.** Oba nie otwierają niczego.
- **Agent.** `publish_artifact` odrzuca nazwę komunikatem wskazującym archiwum,
  więc run nie może założyć pod nią drugiej strony. `read_artifact`,
  `preview_artifact` i `list_artifacts` traktują stronę jak nieistniejącą. Run,
  który nie może edytować strony, słyszy tylko, że nazwa nie jest jego do zmiany.

Archiwizacja wyłącza publiczny link, co trafia do audytu jako
`artifact.public_link_disabled`, a przywrócenie nie włącza go ponownie. Adres
rozesłany przed archiwizacją pozostaje martwy, dopóki ktoś nie utworzy nowego w
**Share**. Na tę okazję zostają wygaśnięcie linku, przypięta wersja, hasło i
witryny, które mogą go osadzać.

Przez API `POST /api/v1/artifacts/{id}/archive` archiwizuje stronę, a ponowna
archiwizacja niczego nie zmienia. `POST /api/v1/artifacts/{id}/unarchive` ją
przywraca i odpowiada `400` dla strony, która nie jest zarchiwizowana. Oba
wymagają prawa do edycji tej strony, także z grantu. `GET /api/v1/artifacts`
wymienia zarchiwizowane strony tylko z `include_archived=true`, a `archived_at`
na każdej stronie mówi, kiedy ją zarchiwizowano.

## Retencja i usuwanie { #retention-and-deletion }

Artefakty są osobną [klasą retencji](governance.md#the-classes), liczoną od
**ostatniej publikacji** — raport publikowany ponownie co tydzień żyje, niezależnie
od tego, jak stara jest jego pierwsza wersja. Jak każda klasa, trzyma artefakty
bezterminowo, dopóki organizacja albo wdrożenie nie ustawi okresu.

Usunięcie artefaktu — ręcznie albo przez retencję — usuwa każdą wersję, jej
przechowywane bajty, jego granty i jego publiczny link. Zarchiwizowana strona
starzeje się i jest usuwana jak każda inna. Usunięcie agenta nie
usuwa jego artefaktów: pozostają czytelne i po prostu nie mają wydawcy. Usunięcie
nazwanego środowiska robi to samo ze stronami z niego opublikowanymi, więc nigdy
nie trafiają na stronę środowiska domyślnego o tej samej nazwie. Usunięcie
organizacji je usuwa. Artefakty usuniętej osoby zostają i tracą właściciela, tak
jak jej agenci i skille.

Bajty leżą w [magazynie plików](configuration.md#uploaded-files-at-rest)
wdrożenia, pod `artifacts/<organization>/<artifact>/`.

## Ograniczenia { #limitations }

- **Jeden samodzielny dokument na wersję.** Bez paczek i bez sieci z wnętrza
  strony poza serwowanym zestawem bibliotek i [danymi na żywo](#live-data), które
  przekazuje jej konsola.
- **Dane na żywo są ograniczone.** Pięć bindingów, po 1000 rekordów i około 5 s
  na załadowanie; zobacz [limity](#limits). Dane, które nie są związane, to strona
  taka, jak ją opublikowano, i zmieniają się, gdy agent opublikuje ją ponownie.
- **Nic na stronie nie działa.** Formularz albo przycisk nie mają dokąd wysłać
  tego, co zbiorą.
- **Otwarta strona przeżywa odwołanie o jeden czas życia podpisanego adresu**,
  domyślnie pięć minut.
- **Link wewnątrz strony najpierw pyta.** Otwiera się w nowej karcie, gdy
  człowiek się zgodzi; sama strona nie może otworzyć okna ani nawigować konsolą.
- **Osadzenie wymaga publicznego linku i braku hasła.** Członkowie nie mogą
  zalogować się w ramce na cudzej witrynie.
- **Usunięte wersje przepadają.** Rozmowa, która linkuje do wersji starszej niż
  przechowywane okno, może zaproponować tylko najnowszą.
- **Bez renderera agent nie widzi swojej strony.** Ostrzeżenia przy publikacji
  czytają znaczniki i nie mogą powiedzieć, jak strona wygląda. Z rendererem obraz
  pochodzi z bezgłowego Chromium: fonty i rozmiary mogą się nieco różnić od tych
  w przeglądarce czytelnika.

## Podsumowanie { #recap }

- Jedna capability, cztery narzędzia: `publish_artifact`, z pliku w workspace'ie,
  inline albo jako edycje; `read_artifact` do odczytania strony z powrotem;
  `list_artifacts` do jej odnalezienia; oraz `preview_artifact`, żeby zobaczyć ją
  narysowaną, razem z jej błędami.
- Agent, środowisko i nazwa to tożsamość; ponowna publikacja zachowuje link i
  dodaje wersję, a każdą zachowaną wersję można przywrócić.
- Domyślnie prywatny; udostępniany grantami, organizacji albo publicznym linkiem —
  przez człowieka. Publiczny link może wygasnąć, przypiąć wersję, pytać o hasło i
  być osadzony na wymienionych witrynach.
- Strona może związać się z zapisanymi widokami tabel i pokazywać dane na żywo,
  czytane w chwili oglądania z własnym dostępem oglądającego i nigdy nie
  przechowywane w stronie.
- Krótki kontrakt strony w instrukcjach każdego agenta z Artifacts i ostrzeżenia w
  wyniku publikacji o tym, co wygląda źle w znacznikach.
- Serwowany z trasy bez ciasteczek, w nieprzezroczystym originie bez sieci poza
  własnym zestawem bibliotek wdrożenia, z linkami, które pytają przed otwarciem, i
  opcjonalnie z własnej domeny.
- Archiwizacja zachowuje stronę i nie serwuje z niej niczego, przy wyłączonym
  publicznym linku, dopóki ktoś, kto może ją edytować, jej nie przywróci.
- Osobna klasa retencji, liczona od ostatniej publikacji.
