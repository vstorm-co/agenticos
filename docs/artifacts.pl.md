---
source_sha: "33a88505219c"
---

# Aplikacje { #artifacts }

**Aplikacja** to strona opublikowana przez agenta: raport, mały dashboard,
jednostronicowe podsumowanie, które ktoś otwiera w przeglądarce. Ma link, który
się nie zmienia, gdy agent publikuje ją ponownie, więc „w każdy poniedziałek
opublikuj liczby z tygodnia na tej stronie” to jeden link, który ludzie dodają do
zakładek, a nie nowy co tydzień.

Aplikacja nie jest plikiem. Wykres, wygenerowany PDF i plik w workspace'ie mają już
swoje miejsce w czacie i w [workspace'ie](sandbox.md). Aplikacja to rzecz, która
jest *serwowana*: ma właściciela, widoczność i granty, tak jak agent czy skill, i
można jej nadać publiczny link dla kogoś bez konta.

## Publikowanie aplikacji { #publishing-one }

Włącz agentowi capability **Aplikacje**. Dodaje ona pięć narzędzi:
`publish_artifact`, które model wywołuje, gdy wynik jest czymś, co człowiek
powinien otworzyć, a nie przeczytać raz w czacie; `read_artifact`, które
odczytuje opublikowaną stronę z powrotem; `list_artifacts`, które wymienia
strony, jakie run może otworzyć; oraz `preview_artifact`, które rysuje stronę i
mówi, co jest w niej nie tak.

Strona pochodzi z jednego z trzech miejsc:

- **Z pliku w workspace'ie agenta**, zakończonego na `.html` albo `.md`. To
  zwykły przypadek dla agenta z capability [Sandbox](reference/capabilities.md#files-shell):
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
`publish_artifact`: każdy binding to nazwa i **zapytanie strony** — tabela, pola,
które strona z niej czyta, i opcjonalnie filtry, sortowanie i limit. Strona wywołuje
`agenticos.onData(render)`, a `render(data)` działa z pierwszymi danymi i ponownie
przy każdym odświeżeniu. `agenticos.data` to Promise pierwszych danych.

```js
agenticos.onData((data) => {
  // data.tickets = { status, records, fields, count, truncated, limit }
});
```

Każdy binding przychodzi jako `status` (`ok` albo `unavailable`), `records`
(`{id, <field>: value}`), `fields` (etykieta, typ, opcje i stan każdego pola),
`count`, `truncated` i `limit`. Strona, która nie dostanie odpowiedzi w ciągu
10 sekund, widzi każdy binding jako `unavailable`; listener dodany później pyta
jeszcze raz.

**Każdy, kto otwiera stronę na żywo, czyta te same rekordy**, niezależnie od własnego
dostępu do tabel. Zapytanie jest czytane z dostępem [właściciela](#who-owns-a-page)
strony i dopiero gdy właściciel zgodził się je udostępnić
([zgoda](#consent-the-owner-decides-who-reads-the-data)). Strona jest więc dla danych,
które może zobaczyć każdy, kto może ją otworzyć. Rekordy są czytane, gdy ktoś ogląda
stronę, i nigdy nie są w niej przechowywane.

### Co zamraża binding { #what-a-binding-freezes }

Zapytanie strony nie jest linkiem do zapisanego widoku. Agent podaje `table` albo
[zapisany widok](virtual-tables.md#saved-views) po id lub dokładnej nazwie, a platforma
**kopiuje** filtry i sortowanie widoku do strony przy publikacji. Późniejsza edycja
albo usunięcie widoku niczego na stronie nie zmienia.

| W bindingu | Znaczenie |
|---|---|
| `table` albo `view` | Tabela do czytania albo widok, którego filtry i sortowanie są kopiowane. Nie oba naraz |
| `fields` | Każda nazwa, którą czyta strona, przypisana do kolumny po id albo etykiecie |
| `filters` | `{column, op, value}`, wszystkie muszą być spełnione; dodawane do filtrów widoku |
| `sort` | `{by, direction}`; zastępuje sortowanie widoku |
| `limit` | Najwyżej 1000, co jest też wartością domyślną; zastępuje limit widoku |

`visible_columns` i `group_by` widoku są ignorowane: o kolumnach decyduje `fields`
bindingu. Filtr może wskazywać kolumnę, której strona nie czyta, a właściciel jest
informowany, którą. Zapytanie strony nie ma wyszukiwania pełnotekstowego, więc widoku
z wyszukiwaniem **nie można powiązać**; publikacja jest odrzucana i go nazywa. Tak
samo odrzucany jest widok, którego filtr wskazuje kolumnę, której już nie ma.

Formuły, lookupy, rollupy i etykiety linków są dozwolone. Czytają więcej niż kolumna,
którą nazywa strona, więc zapytanie zapisuje wszystko, do czego sięga: kolumny
wejściowe formuły, link i cel lookupu albo rollupu, każdą powiązaną tabelę oraz
kolumnę, którą każda powiązana tabela etykietuje swoje rekordy. Spec agenta musi
przyznawać odczyt tabeli, a osoba, w imieniu której działa run, musi czytać każdą
tabelę, do której sięga zapytanie, bo nikt nie może powiązać tego, czego nie może
przeczytać.

Wynik publikacji opisuje każde zapytanie słowami — jego tabelę, filtry, kolejność,
limit i każde pole z tym, co czyta (`Status (single_select)`, `Pay band: formula over
Salary, Level`). To tekst, na który zgadza się właściciel, więc agent sprawdza, czy
to jest to, o co mu chodziło. Binding przeniesiony bez zmian mówi `kept`.

Nazwa bindingu składa się z małych liter, cyfr i `_`. Pole można nazwać tak, jak
podpisana jest jego kolumna: słowami z liter dowolnej wielkości, cyfr i `_`,
rozdzielonymi pojedynczą spacją, np. `Status` albo `Created At`. Obie nazwy mają
najwyżej 64 znaki, a `__proto__`, `constructor` i `prototype` są zarezerwowane dla
obu (dla pola także `id`). Strona ma najwyżej 5 bindingów, a binding najwyżej 50 pól.

Wersja 3 [biblioteki stron](#the-library-set) rysuje binding za agenta:
`AO.records("#tickets", data.tickets)` wewnątrz `agenticos.onData` renderuje
rekordy jako tabelę z nagłówkiem z etykiet pól, liczbami i datami wyrównanymi do
prawej, wyborami jako plakietkami i każdą wartością wpisaną jako tekst. Zanim
przyjdą dane, pokazuje wiersz ładowania, a binding `unavailable` albo pusty
i ucięta lista dostają każdy własny komunikat. `AO.onData` w wersji 3 to to samo
wywołanie co `agenticos.onData`. Strona z bindingami, której skrypt nigdy nie prosi
o dane, nadal się publikuje, z
[ostrzeżeniem](#the-page-contract-and-the-publish-warnings).

### Kto co widzi { #who-sees-what }

To, którą wersję oglądający dostaje i czy jej dane są dla niego czytane, zależy od
tego, kim jest.

| Oglądający | Dostaje | Jego dane |
|---|---|---|
| Właściciel strony | Najnowszą wersję | Zawsze |
| Owner, Admin, Builder i Operator, nawet tylko do podglądu | Najnowszą wersję | Zawsze, dla ról czytających każdą tabelę (`tables:view` w zakresie ALL) |
| Każdy inny, kto może edytować stronę | Najnowszą wersję, żeby agent edytora nadal edytował to, co aktualne | Dopóki obowiązuje zgoda właściciela na tę wersję |
| Wszyscy pozostali, którzy mogą ją otworzyć (**odbiorcy**) | Najnowszą wersję, na którą kiedykolwiek wyrażono zgodę, albo która nie czyta danych | Dopóki obowiązuje zgoda właściciela na nią |

Odbiorcy nigdy nie dostają wersji, na której udostępnienie nikt się nie zgodził. Gdy
zgoda na dane już nie obowiązuje — edytor ją wycofał albo zmienił się właściciel —
odbiorcy nadal dostają **całą stronę**, a każdy binding przychodzi jako `unavailable`
z powodem `awaiting_consent`; strona mówi „The data appears once the page's owner
confirms it." Gdy żadna wersja w ogóle nie ma zgody ani nie jest wolna od
danych, odbiorcy widzą „This page isn't available yet" i nic więcej.

Binding jest też `unavailable`, gdy to, co czyta, zmieniło się od opublikowania
strony. Powód widzi tylko ten, kto może edytować stronę; czytelnik widzi, ile źródeł
jest niedostępnych.

| Powód | Co się stało |
|---|---|
| `creator_gone` | Właściciel strony nie jest już aktywnym członkiem |
| `creator_lost_access` | Właściciel nie może już czytać tabeli, do której sięga zapytanie |
| `source_changed` | Znaczenie kolumny się zmieniło (jej typ, formuła, cel linku albo lookupu, agregat, zarchiwizowana albo przywrócona opcja), albo zarchiwizowano kolumnę lub tabelę, albo powiązana tabela etykietuje teraz swoje rekordy inną kolumną. Podawana jest bieżąca etykieta kolumny |
| `awaiting_consent` | Właściciel nie potwierdził udostępnienia danych tej wersji albo zostało wycofane |

Jeden binding, który staje się `unavailable`, nie psuje pozostałych. Strona nigdy nie
jest blokowana przez zmianę tabeli: nic nie powstrzymuje zmiany kolumny, a binding
przestaje serwować, dopóki agent nie opublikuje strony ponownie, co rozwiązuje
zapytanie względem tabeli takiej, jaka jest teraz. Zmiana nazwy kolumny nie zmienia
bindingu; strona czyta ją dalej pod nazwą, którą nadał agent. Dodanie opcji do
pola wyboru albo zmiana etykiety jednej z nich też nie.

### Zgoda: właściciel decyduje, kto czyta dane { #consent-the-owner-decides-who-reads-the-data }

Dane strony są czytane z dostępem jej właściciela, więc to właściciel decyduje, kto
jeszcze je czyta, per wersja. Ta decyzja to **zgoda**: właściciel przegląda słowami
zapytania strony — tabelę, filtry, kolejność, limit i pola każdego zapytania, każdą
powiązaną tabelę, do której sięgają, i to, kto będzie je czytał — i potwierdza.

Przegląd nazywa, kto zobaczy stronę: role, które widzą każdą stronę (Owner, Admin,
Builder i Operator), widoczność strony, osoby, którym jest udostępniona, i grupy,
razem z przyszłymi członkami. Właściciel może
potwierdzić tylko to, co sam przeczytał.

Dane wersji są w jednym z tych stanów:

| Stan | Znaczenie |
|---|---|
| `not_needed` | Wersja nie ma bindingów |
| `pending` | Nikt jej nie potwierdził. Odbiorcy zachowują wersję, którą mieli |
| `consented` | Właściciel ją potwierdził albo wyrażono na nią zgodę automatycznie |
| `declined` | Prośbę o jej potwierdzenie odrzucono |
| `withdrawn` | Zgoda, która już nie obowiązuje: edytor ją cofnął albo jej właściciel nie jest już właścicielem strony |

Nowa wersja dostaje zgodę **automatycznie**, gdy jej zapytania strony — i wszystko,
do czego sięgają — są tymi, na które właściciel już się zgodził. W przeciwnym razie
jest `pending`: dotyczy to także pierwszej wersji z bindingami, chyba że właściciel
ma włączoną [auto-zgodę](#auto-consent).

Potwierdza właściciel, i tylko on jako on sam, w podglądzie. Gdy najnowsza wersja
czeka, pasek pod tytułem strony mówi o tym, z przyciskiem **Confirm data**: otwiera
to, co wersja udostępnia i komu, a potwierdzenie niesie odcisk dokładnie tego, co
pokazano. Jeśli strona została w międzyczasie opublikowana ponownie albo jej zapytania
się zmieniły, potwierdzenie jest odrzucane i właściciel patrzy jeszcze raz.
Potwierdzenie sprawdza też, czy właściciel nadal może czytać każdą tabelę, do której
sięga zapytanie.

Owner albo Admin może potwierdzić za właściciela. Jest to audytowane jako zgoda
wyrażona przez niego za właściciela, a dane nadal stoją na dostępie właściciela.
Nie może tego zrobić nikt z grantem `edit`: grant na edycję strony nie daje władzy
nad tym, czyje dane ona czyta.

**Wycofanie** cofa zgodę. Każdy, kto może edytować stronę, jako on sam, używa
**Stop sharing data** w menu podglądu. Każda dotychczasowa zgoda staje się nieważna,
nie tylko ostatnia, a auto-zgoda się wyłącza. Każdy grant `edit_data` na stronie
spada też do `edit`, więc następna republikacja edytora danych czeka na właściciela
zamiast cofać wycofanie. Odbiorcy zachowują stronę i tracą jej dane, dopóki
właściciel nie potwierdzi ponownie. Wycofanie tylko zawęża, kto czyta, dlatego może
je wykonać każdy edytor.

Gdy właściciel opuszcza organizację, jego zgody wygasają wraz z jego członkostwem.
Właściciel usunięty i zaproszony ponownie zaczyna od zera. Właściciel dezaktywowany
i reaktywowany przywraca swoje zgody: reaktywacja jest aktem dotyczącym całego
konta, w każdej organizacji, do której konto należy.

#### Ponowna publikacja { #republishing }

Gdy edytor inny niż właściciel publikuje wersję, która czyta inne dane, wersja jest
`pending`, a platforma składa **prośbę o wersję** do właściciela — zobacz
[Prośby o udostępnienie](#share-requests). Dopóki właściciel nie zdecyduje, odbiorcy
nadal widzą wcześniejszą wersję. Wynik publikacji mówi „The audience still sees v2
until Alex confirms this version's data in the console." (z imieniem właściciela albo
„the page's owner").

Run bez osoby może ponownie opublikować stronę z bindingami tylko bez zmian — te same
bajty i te same zapytania, co nie wymaga osoby ani zgody. Nie może podmienić kodu,
który otrzymuje rekordy właściciela. Publikacja edytora jest odrzucana, gdy właściciel
strony nie może czytać tabeli, do której sięga zapytanie.

#### Auto-zgoda { #auto-consent }

Właściciel może włączyć dla strony **Share new versions automatically**. Domyślnie
jest wyłączone i tylko właściciel, jako on sam, może to włączyć, nigdy agent. Najpierw
pyta: „Any data change your runs make to this page, including new tables and
columns, reaches everyone who can open it without asking you. This includes API runs." Wpis
audytu zapisuje potwierdzony tekst.

Obejmuje tylko własne republikacje właściciela. Republikacja edytora nadal czeka.
Auto-zgody są zapisywane jako automatyczne, a gdy któraś sięga dalej niż wersja
serwowana przed nią, pasek właściciela ją wymienia: „v4 was shared automatically
and shows more data: +Deals, +Salary". Właściciel albo Owner lub Admin może ją wyłączyć,
a wyłącza ją także wycofanie albo przekazanie strony komuś innemu.

Nigdy nie obejmuje runu, który zaczął się, gdy administrator podszywał się pod
właściciela, choćby publikował bardzo późno: run w tle, krok workflow albo run
wznowiony po zatwierdzeniu niesie to ze sobą, i to samo dotyczy grantu edytora
danych (niżej). Ponowna publikacja zapytań, które właściciel już potwierdził, nadal
jest objęta zgodą.

#### Edytorzy danych { #data-editors }

Okno udostępniania ma poziom grantu ponad `edit`: **Can edit, including data**
(`edit_data`), tylko dla stron. To stała zgoda na republikacje tej osoby, łącznie ze
zmianą zapytania. Tylko właściciel, albo Owner lub Admin, jako oni sami, go nadaje,
po oknie: „Alex can change the data everyone sees on this page, including new tables
and columns, without asking you. This also covers their API runs." Dla grupy okno
mówi „Anyone in Sales, now or later, can change ...". Grant jest
audytowany z potwierdzonym tekstem.

Republikacja osoby z `edit_data` dostaje zgodę automatycznie, zapisaną jako
dokonaną przez jej grant. Nadal musi czytać każdą tabelę, do której sięga zapytanie,
i właściciel też musi. Zakres roli Owner albo Admin nigdy go nie implikuje. Każdy, kto
może edytować stronę, go obniża albo usuwa, a zmiana właściciela obniża każdy grant
`edit_data` do `edit`.

### Kto jest właścicielem strony { #who-owns-a-page }

Właścicielem strony jest osoba, w imieniu której działał pierwszy run publikujący.
Nigdy nie zmienia się sam i jest jedynym właścicielem danych strony: osobą, której
dostęp czyta dane i której zgoda je udostępnia. Jeśli właściciel zostanie usunięty,
strona go nie ma. Nikt nie może przejąć strony.

Właściciel przekazuje ją innemu aktywnemu członkowi organizacji przez **Change owner**
w menu podglądu, a Owner albo Admin może przypisać dowolną stronę, także taką, której
właściciela już nie ma. Każdy robi to jako on sam, nie przez impersonację. Grant
na edycję strony tego nie dopuszcza. Nie ma do tego narzędzia agenta.

Zmiana jest natychmiastowa, bez kroku akceptacji. Dane strony przestają docierać do
odbiorców, dopóki nowy właściciel ich nie potwierdzi, każda dotychczasowa zgoda jest
nieważna na stałe (więc oddanie strony nie przywraca starej), auto-zgoda się
wyłącza, każda oczekująca prośba jest unieważniana, każdy grant `edit_data` spada
do `edit`, a dawny i nowy właściciel dostają powiadomienie, poza tym, kto dokonał
zmiany. Jest audytowana jako `artifact.owner_changed`.

Nadanie stronie bez właściciela widoczności `private` jest uznawane za jej przejęcie
i jest dostępne tylko dla Ownera albo Admina. Przechodzi przez te same reguły.

### Prośby o udostępnienie { #share-requests }

Poszerzenie tego, kto może otworzyć stronę czytającą dane — szersza widoczność albo
nowy grant lub wyższy poziom — to decyzja właściciela albo Ownera lub Admina w jego
imieniu. Zawężanie jest otwarte dla każdego edytora. Strona, która nie czyta danych,
zachowuje zwykłe reguły udostępniania.

Każdy inny, kto może edytować stronę i próbuje ją poszerzyć, nie dostaje odmowy.
Platforma składa prośbę. Są trzy rodzaje:

| Rodzaj | Składa | Prosi o |
|---|---|---|
| `audience` | Edytor, w oknie Share albo przez `share_artifact` swojego agenta | Poszerzenie tego, kto otwiera stronę |
| `access` | Członek organizacji strony, który otwiera jej link bez dostępu | Możliwość otwarcia strony, z opcjonalną notatką |
| `version` | Publikacja innego edytora, którego wersja czyta inne dane | Potwierdzenie tej wersji |

Członek może mieć jedną oczekującą prośbę `audience` i jedną `access` na stronę,
a strona ma jedną oczekującą prośbę `version`; nowsza zastępuje starszą. Prośby
są domyślnie ograniczone do dziesięciu na godzinę na osobę
na organizację
([`RATE_LIMIT_ARTIFACT_SHARE_REQUESTS_PER_HOUR`](configuration.md)). Prośba `version`
wlicza się też do limitu publikującego: po jego przekroczeniu ponowna publikacja nadal
zastępuje oczekującą prośbę, ale właściciel nie dostaje kolejnego powiadomienia.

Decyduje właściciel strony. Gdy nie ma już właściciela, Ownerzy i Admini
mogą odrzucać; żeby zatwierdzić, najpierw przekazują stronę członkowi (**Change
owner**), który potwierdza dane. Prośba staje się nieważna bez decyzji, gdy zapytania
strony się zmienią, zmieni się właściciel albo strona zostanie zarchiwizowana.

Właściciel dostaje powiadomienie w konsoli i e-mailem, zgodnie z ustawieniem w
**Settings → Notifications** („Page requests"). Powiadomienie nazywa stronę
i proszącego, nigdy jej danych.

Odpowiada się na nie w sekcji **Requests** okna Share, a przycisk **Requests** na
pasku podglądu pokazuje, ile czeka. Zatwierdzenie prośby `audience` albo `access`
stosuje widoczność i granty, o które prosiła, każde tylko tam, gdzie nadal poszerza.
**Nigdy nie wyraża zgody na dane**: gdy wersja serwowana odbiorcom nie ma obowiązującej
zgody, zatwierdzenie jest odrzucane z „Confirm the page's data before sharing it",
a właściciel najpierw potwierdza dane, potem zatwierdza. Odrzucenie niczego nie
udostępnia.

Prośby `audience` albo `access` złożonej w ramach członkostwa, które już się skończyło (członka
usunięto i zaproszono ponownie), nie można zatwierdzić; należy ją odrzucić.

Lista próśb (`GET /api/v1/artifacts/{id}/share-requests`) zawsze zawiera wszystkie
oczekujące prośby. Z `include_decided=true` dodaje rozpatrzone i nieważne, które są
przechowywane, od najnowszych i stronami z parametrami `skip` i `limit` (domyślnie 50,
najwyżej 100); `total` liczy wszystkie, a okno Share informuje, gdy pokazuje tylko
najnowsze rozpatrzone.

Proszący nie jest informowany o decyzji: odpowiedzią jest to, że strona się otwiera
albo nie. Strona, która nie czyta danych, przyjmuje zwykłą prośbę `access`, którą
może zatwierdzić każdy jej edytor.

#### Prośba o dostęp { #requesting-access }

Członek organizacji, który otwiera link strony, której nie może otworzyć, widzi „You
don't have access to this page", pole notatki i **Request access**. Nic więcej nie
jest ujawniane: ani tytuł, ani właściciel, ani agent. Niezalogowany odwiedzający albo
ktoś z innej organizacji dostaje zwykłe „nie znaleziono".

#### Przegląd zmienionej wersji { #reviewing-a-changed-version }

Prośba `version` otwiera właścicielowi stronę na oczekującej wersji, z jej prawdziwymi
danymi. Pasek mówi, kto zmienił dane, które pokazuje wersja, z przyciskiem **Review data
change**. Panel porównuje zapytania strony wersji z tym, które odbiorcy widzą teraz,
binding po bindingu i słowami: dodane, usunięte albo zmienione pola, filtry, kolejność,
limit i powiązane tabele, każde oznaczone **Shows more**, **Shows less** albo bez
zmiany, nowe bindingi z pełnym ujawnieniem, a niezmienione zwinięte.

Przełącznik **What others see** pokazuje stronę taką, jaką mają odbiorcy. Panel
nazywa, kto opublikował wersję i kiedy, i linkuje do rozmowy, gdy właściciel może ją
otworzyć. **Approve** potwierdza wersję. **Decline** zostawia odbiorców przy wcześniejszej
wersji i oznacza wersję jako `declined` w jej historii; kolejna republikacja pyta
ponownie. Na liście Requests prośba o wersję oferuje **Review data change**, nie
Approve: potwierdza się ją z przeglądu.

### Udostępnianie strony przez agenta { #sharing-a-page-from-an-agent }

`share_artifact(name, visibility?, people?)` pozwala agentowi poprosić o udostępnienie
strony: `visibility` to `team` albo `org`, `people` to członkowie po pełnym imieniu
i nazwisku albo e-mailu oraz grupy po nazwie, każdy z prośbą o poziom podglądu.
**Nigdy niczego nie udostępnia.** Składa prośbę `audience` dla osoby, w imieniu której
działa run — także gdy to run samego właściciela — i odpowiada „Waiting for Alex to
approve in the page's Share dialog". Zatwierdzeniem jest człowiek w konsoli,
zalogowany jako on sam, nigdy wywołanie narzędzia.

Nazwa, która nie pasuje do nikogo albo do kilku osób, jest zgłaszana z powrotem,
nigdy zgadywana. Nie prosi o nic publicznego: publiczny link ustawia się tylko w
konsoli. Run bez osoby, taki jak odwiedzający widget, nie może prosić.

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

Wiersz pod paskiem pojawia się tylko wtedy, gdy coś wymaga uwagi: wersja czekająca
na potwierdzenie, prośba do przejrzenia albo źródła, których nie da się odczytać.
Strona, do której dostępu odmówiono, mówi „This page's live data is not available to
you.” Czytelnik, którego źródeł nie da się odczytać, widzi, ilu („2 of 3 sources
unavailable to you”). Edytor widzi też dla każdego źródła powód, z linkiem **Open the
table** do związanej tabeli.

Gdy agent opublikuje nową wersję, a ktoś ma otwartą bieżącą, najbliższy odczyt
(odświeżenie, ręczne albo automatyczne) przenosi podgląd na wersję, którą teraz
dostaje: strona ładuje się ponownie, z własnymi danymi. Oglądający, który wybrał
wersję z menu wersji, zostaje przy niej.

Na starszej wersji dane na żywo nie są czytane. Podgląd mówi „Live data only on the
current version.” z przyciskiem **Open current**, a edytorowi pokazuje też
**Restore** dla tej wersji. Przywrócenie rozwiązuje zapytania strony tej wersji
względem tabel takich, jakie są teraz, więc jest nowym zapytaniem, gdy tabela poszła
dalej, i czeka na zgodę jak każda inna republikacja.

### Jak dane docierają do strony { #how-the-data-reaches-the-page }

Gdy konsola otwiera stronę, prosi o podpisany adres, który niesie, kim jest
oglądający. Trasa treści czyta każdy binding **raz, przy ładowaniu**, i wpisuje wynik
do platformowego skryptu strony, więc pierwsze wywołanie `onData` ma już swoje dane
i nie następuje żadna dodatkowa wymiana. [Publiczny link albo embed](#live-data-on-a-public-link)
jest zapisywany tak samo, ale pod ostrzejszymi bramkami. Nic nie jest wstrzykiwane
dla miniatury, karty ani wersji z historii.

Odświeżenie i automatyczne odświeżanie nadal używają trasy danych i `postMessage` z
konsoli, która teraz odpowiada tymi samymi wierszami zapytania strony każdemu, komu
serwowana jest ta wersja. Trasa nigdy nie jest cache'owana, adres jest krótkożyjący, a
treść rekordu nie trafia do logów. Binding, którego nie da się odczytać w czasie albo
który zawodzi w bazie, jest wstrzykiwany jako `unavailable`, a strona nadal się
renderuje.

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
| Odczyty samych powodów (`rows=false`, pasek edytora) | Te same limity, liczone osobno od ładowań danych |
| Prośby o udostępnienie | 10 na godzinę na osobę na organizację (audience, access i version) |

Ucięty binding mówi `truncated: true`, z `limit` ustawionym na `records` albo
`bytes` i `count` równym liczbie podanych rekordów. `bytes` obejmuje też odczyt,
którego zmierzony koszt wyczerpał się, zanim ukształtowane dane wypełniły przypadającą
na binding część strony.

Termin jest sprawdzany przed każdym zapytaniem, bez anulowania żadnego: każde zapytanie
trwa najwyżej krócej z 2 s i czasu pozostałego z 5 s, a po wyczerpaniu 5 s żadne nowe
zapytanie nie startuje, więc strona odpowiada w około 5 s, a czas rzeczywisty może
dojść do około 7 s. Wstrzyknięte ładowania wliczają się do 30 na minutę, tak jak
odświeżenia. Po przekroczeniu limitu zapytań trasa danych odpowiada 429, konsola
ponawia odpowiedź „zajęty” dwa razy, a strona serwowana z danymi dostaje bindingi
`busy`. Gdy Redis nie działa, dolny próg limitu zapytań i limit żądań w toku liczą się
per worker API, a limit na proces nadal ogranicza każdy worker.

### Kto może opublikować stronę z bindingami { #who-may-publish-a-bound-page }

Strona wiąże się z tabelą tylko wtedy, gdy spec publikującego agenta przyznaje
odczyt tej tabeli, a osoba, w imieniu której działa run, czyta każdą tabelę, do której
sięga zapytanie, co jest sprawdzane przy publikacji strony albo przywróceniu wersji.
Późniejsze odebranie któregokolwiek z tych uprawnień nie zatrzymuje stron już
opublikowanych; dostęp właściciela jest sprawdzany od nowa przy każdym załadowaniu.

Stronę z bindingami może **zmienić** tylko run działający w imieniu członka
(ponowna publikacja bez zmian, z tymi samymi bajtami i zapytaniami, nie wymaga
osoby): zalogowanego członka (czat webowy, HTTP API), powiązanego nadawcy z kanału
albo twórcy harmonogramu. Odwiedzający widget, embed albo hostowaną stronę,
niepowiązany nadawca z kanału i dostarczenie triggera zdarzeniowego agenta (GitHub,
e-mail, przekaźnik webhooków) się nie liczą, podobnie jak run workflow przyjęty
przez publiczne wejście albo cokolwiek w łańcuchu takiego runa.

## Akcje { #actions }

Strona może uruchomić [workflow](workflows.md), ale tylko gdy człowiek się zgodzi. Strona
nie działa sama: prosi, konsola pokazuje osobie, co by się stało, a run należy do niej.
Tak strona staje się małą aplikacją - formularzem, który składa wniosek, przyciskiem,
który zatwierdza fakturę - bez żadnej własnej władzy.

### Deklarowanie akcji { #declaring-actions }

Agent deklaruje workflowy, które strona może uruchomić, przy publikacji, argumentem
`actions` w `publish_artifact`: do pięciu wpisów, każdy to workflow (jego id albo
dokładna nazwa) i **label**, czyli słowo, którym strona go nazywa.

```json
{"actions": [{"workflow": "Approve invoice", "label": "Approve"}]}
```

Workflow może być akcją tylko wtedy, gdy spełnione jest wszystko naraz:

- agent publikujący ma go w [capability Workflowy](reference/capabilities.md#workflows),
  więc to, co strona może uruchomić, jest częścią tego, co sprawdził autor agenta;
- jest aktywny (opublikowany, niezarchiwizowany) i startuje od triggera **Manual** albo
  **API**;
- osoba stojąca za runem może go zobaczyć i uruchomić. Odpowiedź dla workflowu, którego
  nie może, brzmi tak, jakby nie był powiązany, więc odmowa nigdy nie wymienia workflowu,
  którego osoba nie widzi.

Label to zwykły tekst do 60 znaków, z usuniętymi znakami sterującymi i niewidocznymi;
pusty zamienia się w nazwę workflowu. Pominięcie `actions` zachowuje akcje obecnej
wersji, a `[]` je usuwa. Wynik publikacji wymienia każdą zadeklarowaną akcję słowami albo
podaje `kept`. Strona Markdown nie może mieć akcji. Run bez nikogo za sobą nie może
dodawać ani zmieniać akcji i może tylko opublikować bez zmian stronę, która już jakieś
ma. Przywrócenie starszej wersji sprawdza jej akcje ponownie względem agenta takiego,
jaki jest teraz, i jest odrzucane, jeśli któraś już nie obowiązuje.

Akcje są zapisane z wersją, więc nowa wersja zastępuje całą listę, a starsza zachowuje
swoją. Odpięcie workflowu od agenta później nie edytuje opublikowanej wersji; stan
samego workflowu i dostęp każdego oglądającego są sprawdzane przy każdym otwarciu strony
i jeszcze raz, gdy startuje run.

### Kto widzi które akcje { #who-sees-which-actions }

Gdy konsola otwiera stronę, wymienia akcje, które **podana wersja** deklaruje i które ten
oglądający może teraz uruchomić: każdą z prawdziwą nazwą workflowu, labelem strony
i polami, o które prosi jego trigger. Akcja, której oglądający uruchomić nie może, jest
pominięta. Pasek oglądającego pokazuje **This page can run: ...** z nazwami workflowów,
każda jest linkiem do runów tego workflowu. Bez akcji nic się nie pokazuje.

Strona nie dostaje akcji, a jej wywołanie `run` jest od razu odrzucane, gdy jest
pokazywana:

- w publicznym linku, embedzie, podglądzie albo miniaturze karty;
- jako starsza wersja z historii albo wersja, która nie jest tą podaną temu
  oglądającemu (grono odbiorców wciąż czeka na zgodę dla nowszej);
- członkowi, który nie może uruchomić żadnego z jej workflowów, albo sesji
  impersonowanej.

Route startu odrzuca to samo, więc strona, która ominęła konsolę, nic by nie zyskała.

### Uruchomienie ze strony { #running-one-from-the-page }

Na stronie `agenticos.run(action, input)` - `AO.run` w [zestawie strony](#the-library-set) -
prosi konsolę o uruchomienie akcji. `action` to id workflowu, label strony albo nazwa
workflowu. Konsola dopasowuje najpierw dokładne id, potem label, potem nazwę, bez
rozróżniania wielkości liter. Poziom, który pasuje do dwóch akcji, nie dopasowuje
niczego i nie przechodzi do następnego. `input` to obiekt z dokładnie tymi wartościami,
które deklaruje trigger workflowu. Wywołanie zwraca Promise zakończonego runa, a `onRun`
(`AO.onRun`) słyszy każdą zmianę po drodze:

```js
AO.run("Approve", { invoice: "INV-204" }).then(
  (run) => show(run.status, run.output_text),
  (error) => show("not run", error.message),
);
```

Konsola niczego nie uruchamia, dopóki osoba się nie zgodzi. Każdy run, ile by ich nie
było wcześniej, otwiera okno potwierdzenia:

- jego tytułem jest **własna nazwa workflowu**, a label strony pojawia się tylko jako
  cytat;
- pokazuje każdą wartość, którą wysyła strona, w całości i jako tekst, ze znakami, które
  niczego nie rysują albo zmieniają kolejność tekstu, wypisanymi wprost (`\u{202E}`);
- **Run** jest wyłączony przez pół sekundy i nigdy nie dostaje fokusu, więc kliknięcie
  już w drodze nie zgadza się na nic; fokus ma Cancel;
- otwarte jest jedno pytanie naraz, wspólnie dla okien runów i linków, a żądanie, które
  przychodzi w tym czasie, jest odrzucane jako `busy`;
- po **trzech odmowach** przy jednym otwarciu strony (przeładowanie ramki zachowuje
  licznik) konsola przestaje pytać i odrzuca kolejne żądania, dopóki strona nie zostanie
  otwarta ponownie.

Żądanie jest odrzucane bez okna, gdy jest za wcześnie (ramka się jeszcze nie załadowała),
wskazuje akcję, której strona nie deklaruje, nie pasuje do pól workflowu albo przychodzi
z czegokolwiek innego niż własna ramka strony, z nonce wydanym przez konsolę dla tego
załadowania. Wiadomość z innej ramki albo nieaktualnej strony jest odrzucana bez
odpowiedzi.

Promise jest odrzucany z `Error`, którego `message` to krótki kod, więc strona sama
formułuje swój komunikat:

| Kod | Kiedy |
|---|---|
| `cancelled` | Osoba odmówiła |
| `busy` | Otwarte było inne pytanie |
| `too_many_cancels` | Trzy odmowy; strona nie jest pytana ponownie, dopóki nie zostanie otwarta na nowo |
| `not_ready` | Strona zapytała, zanim jej ramka się załadowała |
| `unknown_action` | Żadna zadeklarowana akcja, którą oglądający może uruchomić, nie pasuje |
| `invalid_input` | Wartości brakuje, jest nieznana albo ma zły typ; `error.problems` wymienia `{field, kind}` tylko wtedy, gdy problem znalazła konsola, a nie ma go, gdy serwer odpowiedział 422 |
| `rate_limited` | Za dużo runów od tej osoby albo kwota przyjęć wywołującego lub organizacji |
| `not_found`, `unavailable` | Akcji już nie ma, nie da się jej już startować ręcznie albo jest zarchiwizowana, albo strona w ogóle nie może tu uruchamiać akcji (publiczny link, embed, podgląd, historia, oglądający bez żadnej akcji do uruchomienia) |
| `failed` | Runa nie dało się uruchomić albo śledzić |
| `page_changed` | Strona została zastąpiona, gdy pytanie było otwarte |

### Czym jest run { #what-the-run-is }

Run należy do **oglądającego**: startuje z jego uprawnieniami i liczy się do jego
budżetu, jakby uruchomił workflow z konsoli. Jego triggerem jest **App** (`app`), a run
zapisuje stronę i wersję, na którą osoba patrzyła. Strona niczego nie nadaje; run jest
odrzucany, gdy osoba nie mogłaby go uruchomić sama. Run, który czeka na zatwierdzenie
albo aż ktoś na niego spojrzy, zostaje w [historii runów](workflows.md#running-a-workflow)
workflowu, a oglądający pokazuje wiersz z **Open run**.

Strona nigdy nie dostaje całego runa. Czyta projekcję: status, tekst odpowiedzi,
odpowiedź strukturalną z usuniętymi referencjami do plików, pierwszy wiersz błędu
(najwyżej 200 znaków) oraz, gdy run na kogoś czeka, ścieżkę do niego w konsoli. Może go
czytać tylko osoba, która go uruchomiła, i tylko przez stronę, która go uruchomiła.

Konsola czyta run ze wzrastającym opóźnieniem i wysyła każdą zmianę do strony. Run
czekający na kogoś jest czytany przez dziesięć minut, gdy karta jest widoczna. Potem
promise strony kończy się ostatnim stanem, `paused: true` i bez `finished`, a strona
niczego więcej nie słyszy; wiersz w oglądającym jest drogą do runa. Strona przeładowana
albo zamknięta nie dostaje żadnej informacji.

### Limity i audyt { #limits-and-audit }

| Limit | Wartość |
|---|---|
| Akcje na stronę | 5 |
| Label | 60 znaków |
| Runy uruchomione z jednej strony | 10 na minutę na osobę i stronę (`RATE_LIMIT_ARTIFACT_ACTIONS_PER_MINUTE`) |
| Odmowy, po których konsola przestaje pytać | 3 na jedno otwarcie strony (przeładowanie ramki zachowuje licznik) |
| Zaległa praca | własna kwota przyjęć runów workflowów, która też odpowiada `rate_limited` |

Po przekroczeniu limitu osoba widzi komunikat, a strona dostaje `rate_limited`. Każdy
start jest audytowany jako `artifact.action_started` ze stroną, wersją, workflowem i
runem - nigdy z wejściem, które należy do osoby i jest na samym runie. Zobacz
[governance](governance.md#audit) i [stronę o bezpieczeństwie](security.md#a-page-that-starts-workflows).

## Jedna nazwa, jeden link { #one-name-one-link }

Tożsamością aplikacji jest jej **nazwa w obrębie agenta** — `weekly-report`,
`churn-dashboard`. Publikacja pod tą samą nazwą aktualizuje tę samą aplikację, z
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
publikuje ponownie istniejącą aplikację tylko wtedy, gdy osoba, w której imieniu
działa, jest jej właścicielem albo ma na niej `artifacts:edit` — z roli albo z
grantu `edit`, ta sama zasada co przy zarządzaniu nią w konsoli. Run każdego
innego dostaje informację, że nazwa jest zajęta, i publikuje pod inną, więc
kolega, który poprosi tego samego współdzielonego agenta o `weekly-report`, nie
podmieni strony za Twoim linkiem.

Każda publikacja to nowa **wersja**. Nic nie jest nadpisywane, więc lista wersji
na stronie aplikacji jest historią strony. Dwie rzeczy utrzymują tę historię w
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
| `lib/agenticos-3.js` | `window.AO`: Chart.js w stylu konsoli, formatowanie liczb w języku strony, ikony, zakładki, `AO.onData`, `AO.records` oraz `AO.run` i `AO.onRun` dla [akcji](#actions) |
| `lib/agenticos-2.css`, `lib/agenticos-2.js` | Poprzednia wersja biblioteki, zostawiona dla stron opublikowanych z nią |
| `lib/agenticos-1.css` | Pierwsza wersja wyglądu, zostawiona dla stron opublikowanych z nią |
| `lib/three-0.186.0/three.module.js` | three.js 0.186.0 jako moduł ES, z `addons/controls/OrbitControls.js` obok - zmapuj `three` i `three/addons/` mapą importów |
| `lib/mermaid-12.1.0.min.js` | Mermaid 12.1.0, jako `window.mermaid` |
| `lib/leaflet-1.9.4/leaflet.js`, `leaflet.css` | Leaflet 1.9.4, jako `window.L` - rysuje na [kafelkach map](#visuals) deploymentu, jeśli je ma |
| `lib/agenticos-map-2.js` | `window.AOMap.itinerary`: ponumerowane pinezki pokazane po kolei i wbijane jedna po drugiej na życzenie, mapa w proporcji 16:9 do szerokości strony, linia między nimi oraz karty przystanków - na kafelkach map albo, bez nich, jako zarys przystanków. `lib/agenticos-map-1.js`, który wbija pinezki przy ładowaniu i ma jedną wysokość, jest dalej serwowany stronom, które go wskazują |
| `lib/agenticos-map-1.js` | `window.AOMap.itinerary`: ponumerowane pinezki wbijane po kolei, linia między nimi, pauza i powtórka oraz karty przystanków - na kafelkach map albo, bez nich, jako zarys przystanków |

Każda nazwa niesie swoją wersję i jest cache'owana przez rok. Aktualizacja dodaje
nowy plik obok starego, więc strona opublikowana z jedną wersją dalej ją dostaje,
a raz wydanego pliku nikt nie edytuje. Nic nie jest pobierane spoza wdrożenia,
więc wdrożenie bez dostępu do internetu działa tak samo. Pliki są wymienione w
`backend/app/core/catalog/artifact_lib/`.

Pliki odpowiadają `Access-Control-Allow-Origin: *`, bo skrypt modułowy jest pobierany
w trybie CORS, a strona w nieprzezroczystym originie wysyła `Origin: null` - bez tego
three.js by się nie zaimportował.

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
**Page style** capability Aplikacje w Builderze go proponuje. Edytuj skill, żeby
opisać własny branding, a agent będzie się go trzymał.

### Kontrakt strony i ostrzeżenia przy publikacji { #the-page-contract-and-the-publish-warnings }

Agent nie widzi strony, którą publikuje, więc platforma mówi mu, jak strona ma
wyglądać i co wygląda źle w tej, którą wysłał.

Capability Aplikacje daje każdemu agentowi, który ją ma, krótki **kontrakt
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
- `AO.onData`, `AO.records`, `AO.run` albo `AO.onRun` na stronie, która nie ładuje `lib/agenticos-3.js`;
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
czytałaby je dla niej, i wliczają się do jej limitu odczytów danych. W czacie
grupowym da się podejrzeć tylko stronę całej organizacji, te same strony, które
pokazuje tam lista, i jest ona rysowana bez danych. Tak samo rysowana jest strona
podglądana przez run, za który nikt nie odpowiada: uruchomiony przez osobę z zewnątrz
przez webhook, formularz, wiadomość w kanale, e-mail albo zdarzenie repozytorium, bez
względu na to, jako kto się wykonuje. Powierzchnia, na której nikt nie jest zalogowany,
nie podgląda niczego.

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

## Wizualizacje { #visuals }

[Wizual](reference/capabilities.md#visuals) to aplikacja, której jeszcze nie zapisano:
rysunek, który agent pisze w rozmowie przez `draw`, pokazywany pod jego wiadomością w
trakcie pisania. To ten sam rodzaj dokumentu - wizual `html` jest stroną, a `svg` czy
`mermaid` staje się stroną, która go zawiera - i jest rysowany z tą samą izolacją.

**Ramka.** `/api/v1/artifact-content/visual-frame` to jedna stała strona na originie
treści, serwowana z tą samą polityką, którą dostaje strona każdej aplikacji. Nie zawiera
rysunku: konsola wysyła do niej rysunek w trakcie strumieniowania, więc nic nie musi być
zapisane, zanim zostanie pokazane, a izolacja pochodzi z nagłówka odpowiedzi, a nie z
meta tagu `srcdoc`. Podczas strumieniowania ramka przekształca znaczniki na miejscu, bez
skryptów i atrybutów `on*`; po zakończeniu zapisuje cały dokument, żeby jego skrypty
ruszyły, dokładnie tak jak na zapisanej stronie. Ramka zgłasza swój rozmiar, błędy i
sygnał życia; rysunek, który przestaje go wysyłać, jest zamykany, zamiast blokować kartę.

**W czacie.** Rysunek stoi w samej rozmowie, bez karty wokół, od lewej krawędzi
tekstu wiadomości: SVG jest dopasowane po `viewBox` i zmniejszane powyżej 560 pikseli,
strona jest układana w szerokości kolumny i zmniejszana powyżej 900. Cicha linia pod
nim podaje jego nazwę i mówi, czy wciąż jest rysowany; *Pokaż kod*, *Pobierz*
(`.svg`, `.html` albo źródło Mermaid), *Kopiuj jako obraz* dla SVG, *Zapisz w
aplikacjach* i *Pełny ekran* pojawiają się w tej linii, gdy kursor jest nad
rysunkiem, a na ekranie dotykowym zawsze. Podczas streamingu rysunek trzyma
wysokość zadeklarowaną w wywołaniu, na delikatnym tle, więc rozmowa nie przesuwa
się pod czytelnikiem. Pełny ekran pokazuje go w jego rozmiarze; na telefonie podgląd
otwiera pełny ekran po stuknięciu. Powiększenie pojawia się w prawym dolnym rogu
rysunku, gdy jest na nim kursor: SVG jest rysowane większe, strona skalowana, a
ramka przewija się, gdy rysunek z niej wyrośnie. Błąd zgłoszony przez rysunek
przychodzi z *Napraw*, które prosi agenta.

**Dalsze pytania (follow-upy).** Kontrolka w rysunku może oddać wybór osoby do
rozmowy - *Zaplanuj ten przystanek*, *Użyj tych liczb* - wywołując
`agenticos.followUp(text)`. Rysunek tylko prosi. Konsola pokazuje dokładny tekst
pod rysunkiem z *Wyślij*, *Edytuj* i *Odrzuć*, a wiadomością osoby staje się on
dopiero, gdy kliknie *Wyślij* - tego kliknięcia rysunek nie wykona za nią. Prośba,
za którą nie stoi interakcja użytkownika - przy ładowaniu, z timera - jest
odrzucana, podobnie jak dłuższa niż 2000 znaków, a gdy jedna czeka, druga nie może
jej zastąpić. Follow-upy są dostępne tylko w czacie: `agenticos.canFollowUp()` jest
fałszywe w udostępnionym wątku, w widżecie i w aplikacji, gdzie `followUp` nic nie
robi i zwraca `false`, więc zapisany rysunek nadal działa.

**Mapy.** Gdy ustawione jest
[`VISUAL_MAP_TILES`](configuration.md#published-artifacts), rysunek albo aplikacja
mogą rysować na prawdziwych kafelkach map: deployment pobiera każdy kafelek z
tego serwera i serwuje go z własnej ścieżki kafelków, `agenticos.map` mówi
gdzie, a kit map rysuje na nim trasę z atrybucją serwera pod spodem. Bez tego to
samo wywołanie rysuje zarys przystanków - pinezki i linię między nimi, bez ulic -
i tak samo mapa, której kafelki się nie ładują. Agent mówi o tym w odpowiedzi: że
nie podłączono serwera map i że administrator włącza prawdziwe mapy tym
ustawieniem. Obraz mapy w aplikacji czatowej
jest rysowany w stanie końcowym, ze wszystkimi pinezkami.

**Wybór formy.** Skill `visual-design` mówi agentowi, kiedy rysunek w ogóle jest
właściwą odpowiedzią: tekst dla faktu albo rady, tabela Markdown dla dokładnych
wartości, `create_chart` dla liczb do obejrzenia - więc „teraz zrób wykres” zamienia
tabelę w natywny wykres - a rysunek, by wyjaśnić, jak coś działa, zrobić narzędzie
na chwilę albo śledzić miejsca na mapie. Jego szablony to diagram, objaśnienie z
suwakami, samolot 3D z pochyleniem, przechyleniem i odchyleniem, kalkulator i
plan podróży. Pusty czat z agentem, który rysuje, otwiera się z jednym starterem na
każdy z nich. Włączenie Wizualizacji w Builderze podpina też Wykresy (Charts).

**Pobieranie.** Plik otwarty z dysku nie ma wokół siebie ramki, więc pobrany plik
niesie to, co wymuszała ramka. SVG zachowuje rysunek i traci to, co mogłoby się
uruchomić albo sięgnąć na zewnątrz: skrypty, handlery, osadzone dokumenty i każde
odwołanie poza plik. Strona otwiera się z polityką ramki przed wszystkim, co
napisała, i ładuje biblioteki z originu artefaktów tego wdrożenia.

**Zapis jako aplikacja.** *Zapisz w Aplikacjach* bierze tytuł i nazwę, obie wypełnione,
i publikuje wizual jako wersję aplikacji pod agentem, którego tura go narysowała,
w środowisku, w którym ta tura działała, należącą do osoby, która zapisuje, i prywatną, dopóki jej nie udostępni. Serwer odtwarza
wizual z transkryptu - z naniesionymi poprawkami - zamiast brać bajty z przeglądarki,
więc aplikacja jest dokładnie tym, co narysował agent. Zapis pod nazwą, którą osoba już
ma, dodaje wersję tej aplikacji - w ten sposób poprawka zapisanego rysunku aktualizuje
stronę, którą udostępniono. Zapis wymaga `artifacts:edit`.

**Z delegata.** Rysunek zostaje w runie, który go zrobił, więc agent działający
jako delegat innego agenta nie rysuje: `draw` mu to mówi, a on opisuje obraz w
swoim wyniku, żeby agent, dla którego pracuje, narysował go w rozmowie.

## Kto może ją otworzyć { #who-can-open-it }

Nowy artefakt jest **prywatny** dla osoby, w imieniu której działał publikujący
run: dla osoby na czacie albo dla twórcy triggera. Prywatną stronę widzą też
role Owner, Admin, Builder i Operator: ich `artifacts:view` ma zakres `ALL`, więc
otwierają każdą stronę w organizacji, niezależnie od jej widoczności i grantów
(zobacz [zakresy](permissions.md#scope)). Member albo Viewer otwiera tylko to, co
zostało mu udostępnione. Te cztery role są zawsze częścią odbiorców strony i każde
ujawnienie je wymienia.

Jego link - ten, na który wskazują karta w czacie i odpowiedź agenta - otwiera
samą stronę (karta w czacie otwiera ją w nowej karcie), na całe okno, pod
jednym paskiem z tytułem, wersją i przyciskiem **Share**. Sam link nikogo nie
wpuszcza: otwiera się tylko zalogowanemu członkowi, którego wpuszczają już
poniższe zasady. Link wskazuje organizację, w której jest artefakt (`?org=`), więc członek kilku organizacji trafia do
właściwej.

Pod **Share** każdy, kto może nią zarządzać, może ją udostępnić
na trzy sposoby:

| Zasięg | Jak | Kto |
|---|---|---|
| Konkretne osoby | Grant, na poziomie `read`, `edit` albo, dla strony, `edit_data` („Can edit, including data”) | Ci członkowie, w tej organizacji |
| Organizacja | Widoczność ustawiona na całą organizację | Każdy członek, którego rola sięga do udostępnionych artefaktów |
| Każdy, kto ma link | **Create a public link** | Każdy, kto zna adres, bez konta |

Udostępnianie i widoczność korzystają z tego samego panelu i tych samych reguł co
agenci i skille; zobacz [Uprawnienia](permissions.md). Zarządzanie aplikacją —
udostępnianie jej, jej publiczny link i jego ustawienia, przywracanie wersji,
usuwanie — wymaga `artifacts:edit` na tej aplikacji, z roli albo z grantu `edit`.
Otwarcie jej wymaga `artifacts:view`.

Agent nie może poszerzyć grona czytelników strony. Publikuje, a `share_artifact`
tylko składa prośbę; o tym, kto ją widzi, decyduje człowiek. Dlatego capability
domyślnie nie prosi o zatwierdzenie: pierwsza publikacja jest prywatna, a to, co
pokazuje strona z bindingami, jest bramkowane [zgodą](#consent-the-owner-decides-who-reads-the-data)
jej właściciela. Autor, który chce,
żeby człowiek zatwierdzał każdą ponowną publikację już udostępnionej strony albo
strony z bindingami, ustawia `tool_approval` na `publish_artifact` w specu. Stronę
z bindingami może ponownie opublikować tylko run działający w imieniu członka
(zobacz [Dane na żywo](#live-data)).

### Udostępnianie strony na żywo { #sharing-a-live-page }

Otwarcie [strony na żywo](#live-data) pokazuje jej dane każdemu, komu jest
serwowana, czytane z dostępem właściciela, a nie jego własnym, więc poszerzenie
tego, kto może ją otworzyć, jest decyzją właściciela. Właściciel, albo Owner lub
Admin w jego imieniu, poszerza to bezpośrednio w oknie Share, gdy dane są
potwierdzone; próba każdego innego edytora staje się [prośbą](#share-requests).
Zawężanie jest otwarte dla każdego edytora.

### Publiczny link { #the-public-link }

Publiczny link to `/a/<key>` pod własnym adresem konsoli, z losowym kluczem o
długości 192 bitów — według tej samej reguły co klucz hostowanej strony czatu. Nie
mówi nic o tym, kto ją opublikował ani do której organizacji należy.

**Replace the link** wydaje nowy klucz, a stary od razu przestaje cokolwiek
otwierać. **Turn off** usuwa link. Oba działania trafiają do dziennika audytu.
Strona, którą ktoś ma już otwartą, wyświetla dalej to, co ma, ale jej ponowne
załadowanie albo ponowne otwarcie jej adresu treści od razu kończy się odpowiedzią
404: adres wskazuje klucz linku, a trasa sprawdza ten klucz przy każdym ładowaniu.
Własny czas życia adresu, `ARTIFACT_VIEW_TTL_SECONDS` (domyślnie pięć minut), jest
tylko zewnętrzną granicą.

Odwołany członek jest w tej samej sytuacji co wcześniej: traci aplikację przy następnym
żądaniu, a strona, którą miał już otwartą, zostaje najwyżej przez to samo okno.

Pod linkiem **Share** trzyma jego ustawienia. Zostają, gdy link jest wymieniany, a
link wyłączony i włączony ponownie je zachowuje:

| Ustawienie | Co robi |
|---|---|
| **Stops opening after** | Data, po której link niczego nie otwiera, jakby był wyłączony |
| **Shows** | Najnowszą wersję albo jedną zachowaną wersję przypiętą tak, żeby nowa publikacja nie zmieniła tego, co osoby z linkiem już widziały. Przypięta wersja nigdy nie jest usuwana |
| **Password** | Pytanie przed otwarciem strony. Link nie mówi nic — ani tytułu, ani kiedy ją opublikowano — dopóki hasło nie jest poprawne. Przechowywane jako hash, nigdy nie pokazywane ponownie; każda próba liczy się do limitu żądań linku. Zmiana albo usunięcie hasła kończy adresy otwarte pod starym: nie niosą żadnych danych |
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

Osadzenie niesie dane strony na tych samych zasadach co jej link; zobacz
[Dane na żywo w publicznym linku](#live-data-on-a-public-link). Dodanie witryny
poszerza krąg osób czytających te dane, więc czyści zgodę na dane.

### Dane na żywo w publicznym linku { #live-data-on-a-public-link }

[Strona z bindingami](#live-data) pokazuje swoje rekordy w publicznym linku i w embedach
tylko wtedy, gdy zapadły dwie osobne decyzje, a trzecia kontrola obowiązuje przy
każdym ładowaniu. Bez nich publiczna strona renderuje się tak, jak ją opublikowano,
z każdym bindingiem `unavailable`.

1. **Organizacja na to pozwala.** Owner albo Admin włącza w ustawieniach organizacji
   **Public pages with live data**. Domyślnie jest wyłączone, ostrzega przed
   włączeniem i trzeba je zmienić, będąc zalogowanym jako ten sam użytkownik, nigdy
   w czyimś imieniu. To wyłącznik, nie reset: wyłączenie ukrywa dane na każdej
   publicznej stronie i w każdym embedzie przy następnym ładowaniu, a zgodę każdej
   strony zostawia nietkniętą, więc ponowne włączenie przywraca strony, których
   zgoda nadal obowiązuje.
2. **Właściciel strony potwierdza to dla linku.** W ustawieniach linku w **Share**
   **Confirm data** otwiera ekran z tym, co pokazuje zgoda członków — zapytania strony
   obsługiwanej wersji opisane słowami, każda powiązana tabela, do której sięgają —
   oraz z tym, kto może to czytać: każdy z linkiem, bez konta i bez logowania, czy
   chroni go hasło, kiedy wygasa i każda witryna osadzająca. Właściciel, albo w jego
   imieniu Owner lub Admin, potwierdza to, będąc zalogowanym jako ten sam użytkownik;
   grant `edit` nie wystarcza. Potrzebny jest włączony link, włączony wyłącznik
   organizacji i własna [zgoda](#consent-the-owner-decides-who-reads-the-data)
   członków dla tej wersji. Każdy edytor może ją wycofać, będąc zalogowanym jako ten
   sam użytkownik; Owner albo Admin nie może tego zrobić, podszywając się pod niego.
3. **Każda bramka obowiązuje przy każdym ładowaniu.** Zobacz [co dostaje anonimowy
   odwiedzający](#what-an-anonymous-visitor-gets).

Potwierdzenie dotyczy wersji, którą obsługuje link — przypiętej, a jeśli jej nie ma,
tej, którą obsługiwani są odbiorcy strony — i jest związane z dwoma skrótami: odciskiem
jej zapytań strony oraz skrótem tego, do kogo link sięga (witryny osadzające, to, czy
jest hasło, i to, czy link jest włączony). Jest odrzucane z konfliktem, jeśli któryś
z nich zmienił się po narysowaniu ekranu. Zapisuje się je pod członkostwem właściciela
i audytuje po nazwach tabel i kolumn, nigdy po wierszach.

#### Co je unieważnia, a co nie { #what-voids-it-and-what-does-not }

Wszystko, co poszerza krąg odbiorców albo zmienia to, czyje to dane, czyści zgodę, co
trafia do audytu jako `artifact.public_data_voided` z powodem. Ponowne włączenie wymaga
nowego potwierdzenia.

| Unieważnia zgodę | Zostawia ją w spokoju |
|---|---|
| Wyłączenie linku albo archiwizacja strony | Wymiana klucza linku: zmienia adres, nie dane |
| Usunięcie hasła | Zmiana hasła, wygaśnięcia linku albo przypiętej wersji |
| Dodanie witryny osadzającej | Usunięcie witryny osadzającej |
| Przekazanie strony innemu właścicielowi | Wyłączenie wyłącznika organizacji |
| Wycofanie zgody członków na dane | |

Inna przypięta wersja albo ponowna publikacja zmieniająca zapytania strony nie
unieważnia zgody, ale sprawia, że przestaje obowiązywać: odcisk obsługiwanej wersji
już nie pasuje, więc publiczna strona nie pokazuje danych, dopóki ktoś nie potwierdzi
ich ponownie. Wygasły link też niczego nie trzyma.

Właściciel i pozostali edytorzy widzą powód w pasku nad stroną: wyłącznik jest
wyłączony, link nie obsługuje żadnej wersji, zapytania się zmieniły, właściciel odszedł
albo się zmienił, brakuje zgody członków albo link wygasł.

#### Co dostaje anonimowy odwiedzający { #what-an-anonymous-visitor-gets }

Odwiedzający nie dowiaduje się, dlaczego. Zanim cokolwiek zostanie odczytane, każde
ładowanie sprawdza, czy link nadal ma klucz, dla którego wydano adres, czy nie wygasł,
czy stan hasła jest taki, pod jakim adres otwarto, czy wersja jest nadal tą, którą
link obsługuje, czy wyłącznik organizacji jest włączony oraz czy obowiązują zgoda strony
na dane i zgoda członków. Jeśli którakolwiek bramka zawiedzie, strona renderuje się z
każdym bindingiem `unavailable` i bez powodu.

Potem każdy binding jest sprawdzany osobno: właściciel nadal musi być aktywnym członkiem
czytającym tabelę, a tabela nie może się rozjechać z zapytaniem. Binding, który tu
zawiedzie, jest `unavailable`; pozostałe nadal się ładują.

Rekordy są wpisywane do strony przy ładowaniu i obowiązują na jego chwilę. Publiczna
strona i embed nie mają ani Refresh, ani trasy danych, a strona nie może poprosić o
więcej; odwiedzający ładuje ją ponownie, żeby zobaczyć zmianę. Zmieniony albo usunięty
klucz to 404, a nie strona bez danych, natomiast zmienione albo usunięte hasło daje
staremu adresowi stronę bez danych.

#### Cache i limit { #the-cache-and-the-cap }

Anonimowe ładowanie kosztuje odczyty tabel, więc odczyty są współdzielone. Rekordy
bindingu są trzymane przez 30 sekund w pamięci procesu API, pod kluczem złożonym z
wersji, bindingu, odcisku zapytań i członkostwa właściciela — **nigdy w Redisie**,
bo to rekordy. Każda bramka powyżej działa, zanim cache zostanie zapytany, więc
wyłączona organizacja, zmieniony klucz albo wycofana zgoda działają od razu, niezależnie
od tego, co jest trzymane. Nieudany albo niedostępny odczyt nigdy nie jest zachowywany.

Pamięć jest ograniczona: `ARTIFACT_PUBLIC_DATA_CACHE_BYTES` (domyślnie 32 MiB) i 64
odczyty na proces, przy czym najdawniej używane są usuwane pierwsze, a odczyt większy
niż budżet nie jest zachowywany. Osobno każda strona może czytać ze swoich tabel
`RATE_LIMIT_ARTIFACT_PUBLIC_DATA_PER_MINUTE` razy na minutę (60) dla wszystkich
swoich odwiedzających łącznie. Ładowanie, które musi czytać z tabel, liczy się raz,
więc ruchliwą stronę ogranicza limit, a nie jej publiczność. Po jego przekroczeniu, albo
gdy proces obsługuje już tyle ładowań danych, ile może, binding wymagający odczytu
wraca dla tego odwiedzającego jako `unavailable`.

## Jak strona jest izolowana { #how-the-page-is-isolated }

Aplikacja to HTML ze skryptem w środku, napisany przez model, który mógł przeczytać
coś wrogiego. Jest serwowany tak, żeby nic, co robi, nie mogło dosięgnąć konsoli
ani osoby, która ją ogląda:

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
  originie treści, dla skryptów, stylów i fontów. Na deploymencie, który ustawia `VISUAL_MAP_TILES`, dochodzą obrazy z jego własnej ścieżki kafelków, `/api/v1/artifact-content/tiles/{z}/{x}/{y}`. Ta trasa przyjmuje trzy liczby, każdą sprawdzoną względem przybliżenia, przy którym kafelek istnieje, i sama pobiera kafelek, więc strona nigdy nie poznaje adresu ani klucza serwera kafelków i nie może mu wysłać niczego, co sama wybrała. `frame-ancestors` wymienia tylko
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
  między stroną po prompt injection a adresem, pod który wysłałaby swoje liczby. [Follow-up](#visuals) to prośba tego samego rodzaju: konsola pokazuje tekst, a wysyła go człowiek.
  między stroną po prompt injection a adresem, pod który wysłałaby swoje liczby.
- Dane na żywo docierają do strony członka na dwa sposoby, oba rozstrzygane per
  oglądający na serwerze. Przy ładowaniu trasa treści wpisuje rekordy każdego bindingu
  do platformowego skryptu strony, dla członka, którego nazywa podpisany adres;
  odświeżenie przychodzi przez `postMessage` z konsoli, która pobiera je z trasy
  danych z własną sesją oglądającego. Żądanie strony niesie nonce, dzięki któremu
  konsola dopasowuje każdą odpowiedź do właściwego załadowania strony; to
  **korelacja, a nie kontrola dostępu**. Publiczny link albo embed dostają swoje
  dane tylko przy ładowaniu, wpisane przez serwer, i nigdy o nie nie proszą: nie mają
  trasy danych ani odświeżania. Zobacz
  [dane na żywo w publicznym linku](#live-data-on-a-public-link) i
  [stronę o bezpieczeństwie](security.md#a-pages-data-and-its-address).
- Strona może poprosić o uruchomienie [workflowu](#actions) tym samym mostem, przez
  `agenticos.run`, a oferuje to tylko oglądający stronę w konsoli: adres niesie prawo do
  proszenia, a publiczny link, embed, podgląd i miniatura odrzucają wywołanie od razu.
  Prośba jest znów **tylko prośbą**. Konsola przyjmuje ją z własnej ramki, z nonce tego
  załadowania, dopasowuje do akcji, którą serwer wymienił dla tego oglądającego i podanej
  wersji, i pyta osobę w oknie, zanim cokolwiek wystartuje. Run jest wtedy jej, więc
  strona z wstrzykniętym promptem może sprawić, że osoba przeczyta pytanie, ale nigdy nie
  odpowie na nie za nią.
- Jeden podpisany adres ładuje swoją stronę najwyżej kilka razy na minutę, licząc
  per adres, zanim cokolwiek zostanie odczytane. Konsola i strona publiczna
  wydają świeży adres za każdym razem, gdy rysują ramkę, a wydanie go przez
  publiczny link samo jest ograniczone per link.

Lista **Aplikacje** rysuje na każdej karcie bieżącą stronę jako żywą miniaturę,
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
- **Listy.** Lista Aplikacje i widget na dashboardzie ją pomijają. Wybierz na
  liście **Archived included**, żeby ją zobaczyć, oznaczoną jako **Archived**. Widzą
  ją tam tylko ci, którzy mogą ją edytować.
- **Publiczny link i embed.** Oba nie otwierają niczego.
- **Agent.** `publish_artifact` odrzuca nazwę komunikatem wskazującym archiwum,
  więc run nie może założyć pod nią drugiej strony. `read_artifact`,
  `preview_artifact` i `list_artifacts` traktują stronę jak nieistniejącą. Run,
  który nie może edytować strony, słyszy tylko, że nazwa nie jest jego do zmiany.

Archiwizacja wyłącza publiczny link, co trafia do audytu jako
`artifact.public_link_disabled`, i czyści jego [zgodę na dane](#what-voids-it-and-what-does-not).
Przywrócenie nie włącza żadnego z nich ponownie. Adres rozesłany przed archiwizacją
pozostaje martwy, dopóki ktoś nie utworzy nowego w **Share**. Na tę okazję zostają wygaśnięcie linku, przypięta wersja, hasło i
witryny, które mogą go osadzać.

Przez API `POST /api/v1/artifacts/{id}/archive` archiwizuje stronę, a ponowna
archiwizacja niczego nie zmienia. `POST /api/v1/artifacts/{id}/unarchive` ją
przywraca i odpowiada `400` dla strony, która nie jest zarchiwizowana. Oba
wymagają prawa do edycji tej strony, także z grantu. `GET /api/v1/artifacts`
wymienia zarchiwizowane strony, tym, którzy mogą je edytować, tylko z
`include_archived=true`, a `archived_at` na każdej stronie mówi, kiedy ją
zarchiwizowano.

## Obserwowanie strony { #following-a-page }

**Obserwuj** na pasku strony umieszcza powiadomienie w Twojej skrzynce za każdym
razem, gdy strona dostaje nową wersję - agent opublikował ją ponownie z inną
treścią albo ktoś przywrócił starszą wersję. Ponowna publikacja, która niczego
nie zmienia, nikogo nie powiadamia, więc harmonogram, który nie znalazł nic
nowego, pozostaje cichy. Osoba, której run albo przywrócenie utworzyło wersję,
nie dostaje powiadomienia o własnej zmianie.

Obserwowanie nie daje dostępu. Obserwować stronę może każdy, kto może ją
otworzyć, a obserwujący, który straci dostęp, przestaje dostawać powiadomienia
bez rezygnowania z obserwowania. Skrzynka sprawdza dostęp ponownie przy
odczycie, więc powiadomienie o stronie, której nie możesz już otworzyć, znika
razem z tym dostępem. Powiadomienie może też przyjść mailem; każdy kanał
wyłączysz w **Ustawienia → Powiadomienia → App updated**.

## Retencja i usuwanie { #retention-and-deletion }

Aplikacje są osobną [klasą retencji](governance.md#the-classes), liczoną od
**ostatniej publikacji** — raport publikowany ponownie co tydzień żyje, niezależnie
od tego, jak stara jest jego pierwsza wersja. Jak każda klasa, trzyma aplikacje
bezterminowo, dopóki organizacja albo wdrożenie nie ustawi okresu.

Usunięcie aplikacji — ręcznie albo przez retencję — usuwa każdą wersję, jej
przechowywane bajty, jej granty i jej publiczny link. Zarchiwizowana strona
starzeje się i jest usuwana jak każda inna. Usunięcie agenta nie
usuwa jego aplikacji: pozostają czytelne i po prostu nie mają wydawcy. Usunięcie
nazwanego środowiska robi to samo ze stronami z niego opublikowanymi, więc nigdy
nie trafiają na stronę środowiska domyślnego o tej samej nazwie. Usunięcie
organizacji je usuwa. Aplikacje usuniętej osoby zostają i tracą właściciela, tak
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
- **Wszyscy czytają dane z widoku właściciela.** Zapytanie strony jest czytane z
  dostępem właściciela, więc strona jest dla danych, które może zobaczyć każdy, kto
  może ją otworzyć. Zapytanie strony nie ma wyszukiwania pełnotekstowego, filtra
  per oglądający, takiego jak „ja” czy „dziś”, ani ograniczenia na poziomie wiersza
  czy kolumny poza samym zapytaniem.
- **Publiczny link albo embed dostają dane dopiero po dwóch potwierdzeniach.**
  Organizacja musi na to pozwolić, a właściciel strony musi to potwierdzić dla linku;
  do tego czasu strona z bindingami pokazuje tam „unavailable”. To, co pokazuje, jest
  z chwili ładowania, bez odświeżania, nawet do 30 sekund stare i czytane z dostępem
  właściciela dla osób, których właściciel nie zna. Wdrożenie, które tego nie
  akceptuje, zostawia wyłącznik wyłączony. Zobacz
  [dane na żywo w publicznym linku](#live-data-on-a-public-link).
- **Strona działa tylko przez zadeklarowane akcje.** Formularz albo przycisk nie mają
  dokąd wysłać tego, co zbiorą, poza uruchomieniem jednego z najwyżej pięciu workflowów,
  które zadeklarował publikujący, które osoba potwierdza za każdym razem i które działają
  w jej imieniu. Strona sama nie może wywołać API, zapisać rekordu ani wysłać
  wiadomości, a z powrotem dostaje tylko status i odpowiedź runa. Zobacz
  [akcje](#actions).
- **Otwarta strona przeżywa odwołany grant o jeden czas życia podpisanego adresu**,
  domyślnie pięć minut. Wyłączenie publicznego linku albo wymiana jego klucza kończy to
  przy następnym ładowaniu.
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
- **Wizual rysuje się tylko w czacie konsoli i w udostępnionym wątku.** Aplikacja
  czatu dostaje jego obraz, gdy `VISUAL_RENDER_CDP_URL` wskazuje przeglądarkę, a w
  przeciwnym razie tytuł; widget i osadzenie na innej witrynie pokazują jego tytuł.
- **Udostępniony wątek pokazuje dwanaście najnowszych wizuali** i nie więcej niż
  16 MB łącznie. Każdy, kto ma link, może go otwierać dowolnie często, więc jedno
  wyświetlenie jest ograniczone; tura poza którymś z limitów zachowuje tekst i nie
  pokazuje rysunku.

## Podsumowanie { #recap }

- Jedna capability, pięć narzędzi: `publish_artifact`, z pliku w workspace'ie,
  inline albo jako edycje; `read_artifact` do odczytania strony z powrotem;
  `list_artifacts` do jej odnalezienia; `preview_artifact`, żeby zobaczyć ją
  narysowaną, razem z jej błędami; oraz `share_artifact`, żeby poprosić o jej
  udostępnienie.
- Agent, środowisko i nazwa to tożsamość; ponowna publikacja zachowuje link i
  dodaje wersję, a każdą zachowaną wersję można przywrócić.
- Domyślnie prywatny; udostępniany grantami, organizacji albo publicznym linkiem —
  przez człowieka. Publiczny link może wygasnąć, przypiąć wersję, pytać o hasło i
  być osadzony na wymienionych witrynach.
- Strona może związać się z zapytaniem strony — tabelą, filtrami, sortowaniem,
  limitem i polami — i pokazywać dane na żywo, czytane w chwili oglądania z
  dostępem swojego właściciela, dopiero gdy właściciel potwierdzi ich udostępnienie,
  i nigdy nie przechowywane w stronie. Każdy, kto może edytować, może tę zgodę
  wycofać; poszerzenie tego, kto otwiera stronę z bindingami, należy do właściciela
  albo jest prośbą. Publiczny link albo embed pokazują dane tylko wtedy, gdy Owner
  lub Admin pozwolił na to dla organizacji, a właściciel potwierdził to dla linku, a
  wyczyszczenie kręgu odbiorców linku czyści to potwierdzenie.
- Strona może zadeklarować do pięciu workflowów powiązanych przez agenta; jej przyciski
  proszą konsolę o uruchomienie jednego przez `AO.run`, a oglądający potwierdza każdy
  run w oknie, które nazywa prawdziwy workflow i pokazuje każdą wartość. Run należy do
  oglądającego, z triggerem `app`, a strona odczytuje tylko jego status i odpowiedź.
- Właściciel może przekazać stronę innemu członkowi, który musi ponownie potwierdzić
  jej dane.
- Krótki kontrakt strony w instrukcjach każdego agenta z Artifacts i ostrzeżenia w
  wyniku publikacji o tym, co wygląda źle w znacznikach.
- Serwowany z trasy bez ciasteczek, w nieprzezroczystym originie bez sieci poza
  własnym zestawem bibliotek wdrożenia, z linkami, które pytają przed otwarciem, i
  opcjonalnie z własnej domeny.
- Archiwizacja zachowuje stronę i nie serwuje z niej niczego, przy wyłączonym
  publicznym linku, dopóki ktoś, kto może ją edytować, jej nie przywróci.
- Osobna klasa retencji, liczona od ostatniej publikacji.
