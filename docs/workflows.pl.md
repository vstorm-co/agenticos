---
source_sha: "776a2161e7e5"
---

# Workflows { #workflows }

**Workflow** łączy kroki w automatyzację, którą wykonują Twoje agenty: odczytać
[tabelę](virtual-tables.md), wywołać agenta, rozgałęzić się na podstawie wyniku,
przejść w pętli po liście. Budujesz go na kanwie, łączysz kroki ze sobą i
publikujesz jako niezmienną wersję — to ten sam kształt, który ma
[agent](concepts.md): draft, który edytujesz, i opublikowana wersja, która
działa.

Ta strona opisuje edytor wizualny: listę, kanwę i paletę, sposób konfiguracji
węzła, autozapis i publikowanie oraz drogi klawiaturowe przez to wszystko. Edytor
znajduje się w sekcji **Workflows** w konsoli. Strona **listy** Workflows ma
**"?"**, które odtwarza przewodnik po tej liście; sam edytor nie ma przewodnika.

## Tworzenie i duplikowanie workflow { #creating-and-duplicating-a-workflow }

**New workflow** otwiera okno, które pozwala zacząć od pustej kanwy lub od szablonu.
**Blank workflow** to pusta kanwa do budowania od zera. Szablony to gotowe punkty
wyjścia — **Starter**, pojedynczy krok do zmiany nazwy i podłączenia, oraz
**Two-step sequence**, dwa już połączone kroki dla liniowego przebiegu. Wybierz
jeden przyciskiem **Use**, a znajdziesz się w edytorze.

Lista pokazuje każdy workflow, który widzisz, jako kartę: jego status, kto może do
niego dotrzeć, czy ma żywą wersję i kiedy ostatnio go edytowano. **Filter by
status** zawęża ją do **Drafts**, które wciąż budujesz, **Published**, które działają,
albo **Archived**. Z karty otwierasz edytor, runy workflow albo kopię.

**Duplicate** kopiuje bieżący draft workflow do nowego o nazwie *{name} (copy)*.
Duplikat to nowy workflow z własnym draftem, nigdy kopia opublikowanej wersji.

!!! info "Pusta lista może być filtrem, a nie pustą organizacją"

    **No workflows yet** i **Nothing matches** to różne stany: pierwszy to
    organizacja bez żadnego workflow, drugi to filtr statusu, pod który nie
    wpada żaden wiersz. **Clear filter** przywraca pełną listę. Workflow
    udostępniony Tobie pojawia się na tej samej liście, gdy masz `workflows:view`.

## Kanwa i paleta { #the-canvas-and-the-palette }

**Kanwa** to miejsce, gdzie pojawiają się kroki i połączenia workflow, a edytor daje
jej całe okno pod nagłówkiem: paletę po lewej, panel **Properties** po prawej.
**Węzeł** to jeden krok; **krawędź** to połączenie, które ustala kolejność: krok, na
który wskazuje, wykonuje się po tym, z którego wychodzi.

Każdy węzeł to karta z
ikoną kroku, jego nazwą i jedną linią tego, do czego jest ustawiony - warunek, URL,
liczba mapowanych pól - a krok z więcej niż jednym wyjściem wymienia porty z nazwy:
**true** i **false**, **Each item** i **Done** oraz czerwony port **Error** na kroku,
który obsługuje swoje błędy. Kanwę można przesuwać i przybliżać, a jej elementy
sterujące są w rogu - nie ma minimapy.

Paleta **Nodes** wymienia typy węzłów, które zarejestrowała Twoja deployment, w
grupach ułożonych tak, jak czyta się workflow - **Start and finish**, **Agents**,
**Knowledge**, **Data**, **Tables**, **Branching**, **Loops**, **Errors** - każdą grupę
da się zwinąć, a każdy wiersz ma ikonę, nazwę i opis. **Search nodes** filtruje
listę. Krok dodajesz na dwa sposoby:

- **Przeciągnij** węzeł z palety na kanwę — droga dla wskaźnika.
- **Kliknij** węzeł, aby dodać go blisko środka widoku — droga dla klawiatury i
  dotyku, która nie wymaga przeciągania.

Paleta pokazuje, co jest ważne tam, gdzie jesteś. **Loop item** i **Loop result**
pojawiają się tylko wewnątrz ciała pętli, bo poza nim nic nie znaczą, a pętla jest
oferowana, dopóki pętle nie są zagnieżdżone tak głęboko, jak pozwala publikacja.

!!! note "Katalog węzłów rośnie z czasem"

    Paletę zasilają zarejestrowane węzły deployment, a nie stała lista. Na początku
    katalog jest mały; więcej rodzajów węzłów — wywołanie agenta, odczyt i zapis
    tabeli, rozgałęzienia i pętle — dochodzi, gdy rejestrują je późniejsze
    milestone'y, i pojawiają się w palecie w tej samej chwili, bez zmiany w
    workflow, który już zbudowałeś.

## Konfigurowanie węzła { #configuring-a-node }

Co robi każdy węzeł, czym się go konfiguruje i co znaczą jego błędy, opisuje
[referencja węzłów](reference/workflow-nodes.md).

Zaznacz węzeł, a po prawej otworzy się panel **Properties**. Jego pola dzielą się na
dwie sekcje. **Configuration** trzyma statyczne ustawienia — stałe wybory, które nie
zmieniają się z jednego run na następny, w tym zasoby, do których krok jest
przypięty. **Inputs** trzyma wartości, które krok odczytuje, gdy działa.

Input wypełnia się na jeden z dwóch sposobów, a przełącznik **Bind** obok pola
przełącza między nimi:

- **Literał** — wpisujesz wartość wprost w pole, tym samym elementem sterującym,
  którego wymaga typ pola.
- **Binding** — odczytujesz wartość z wyjścia innego kroku. **Bind** zmienia pole w
  wybór **Source**, którego opcjami są wyjścia wcześniejszych kroków rzeczywiście
  osiągalne tutaj i niosące zgodny typ — całe wyjście kroku albo jedno pole w nim —
  każde pokazane jako *{node} · {port} ({type})*, a pole jako
  *{node} · {port} → {field} ({type})*. Pole bez niczego zgodnego wcześniej mówi
  **No compatible upstream outputs**, zamiast oferować nieprawidłowy wybór.

Wymagany input bez wartości to problem walidacji, oznaczony na węźle, a nie
wypełniany cichą wartością domyślną. Niektóre pola trzymają ustrukturyzowane
wartości: listę wierszy, do której dodajesz przez **Add row**, zmieniasz kolejność i
usuwasz, albo typowany wybór, który wymienia pod-formularz pod sobą. Panel schodzi
w nie rekurencyjnie, zamiast wysyłać Cię na osobny ekran.

Zaznacz więcej niż jeden węzeł, a panel zgłasza, ile jest zaznaczonych; zaznacz
krawędź, a pokazuje **From** i **To** połączenia.

### Wybór zasobów { #resource-pickers }

Ustawienie, które przypina zasób, otwiera pole wyboru zamiast pola tekstowego, więc
krok nazywa realną rzecz, którą ma Twoja organizacja:

| Pole wyboru | Co przypina |
|---|---|
| **Agent** i **Version** | Agenta, a potem jedną z jego opublikowanych wersji. Zmiana agenta czyści przypiętą wersję, bo wersja należy do jednego agenta |
| **Table** i **Columns** | [Virtual Table](virtual-tables.md), a potem kolumny, które krok odczytuje — ograniczone do bieżącego schematu tej tabeli |
| **Secret** | Sekret w [vault](secrets.md), przez referencję. Krok zapisuje id sekretu, nigdy jego wartość |

Każde pole wyboru rozróżnia jednakowo nazwane wiersze przez kontekst i oznacza
referencję, której cel zniknął. Pola wyboru **Agent** i **Secret** mają też link do
utworzenia nowego — zawsze, nie tylko gdy lista jest pusta — natomiast pole wyboru
**Table** nie ma żadnego. Tabela, której schemat zmienił się od czasu powiązania, mówi o tym i oferuje
**Rebind to the current schema**, więc nieaktualny zestaw kolumn jest widoczną
zachętą, a nie cichym pęknięciem.

### Gdy krok jest wolny albo zawodzi { #when-a-step-is-slow-or-fails }

Pod polami kroku sekcja **When it is slow or fails** ustala jego politykę. **Handle
errors** daje krokowi port **Error**: błąd, którego ponowienia nie rozwiązały, wychodzi
nim do kroku **Handle error** albo czegokolwiek innego, co podłączysz, zamiast
kończyć run błędem. **Tries** to łączna liczba prób kroku, a **Wait between tries** i
**First wait** ustalają przerwę między próbami. Krok, którego wywołania nie da się
bezpiecznie powtórzyć, na przykład uruchomienie agenta, mówi o tym i nigdy nie jest
ponawiany. **Time limit** przerywa wywołanie po tylu sekundach. Co każde ustawienie
robi w trakcie runa, opisuje [referencja węzłów](reference/workflow-nodes.md#error-handling).

Binding do wartości bez zadeklarowanego kształtu - bieżącego elementu pętli, payloadu
triggera - oferuje pod źródłem pole **Field inside it**, w którym wpisujesz ścieżkę
wewnątrz tej wartości, na przykład `record_id` albo `fields.Email`. Run sprawdza tę
ścieżkę, gdy krok zostaje wysłany do wykonania, bo tylko run wie, co zawiera wartość.

## Połączenia i scope foreach { #connections-and-foreach-scope }

Krawędź rysujesz, łącząc port wyjściowy jednego węzła z portem wejściowym innego
węzła. Edytor odrzuca połączenie między portami, które niosą różne kształty, zanim je
narysuje, więc niezgodne połączenie nigdy nie ląduje na kanwie.

Krawędź ustala kolejność, w jakiej wykonują się kroki; nie przenosi żadnych danych.
Wartości, które krok czyta, to jego **bindingi**, opisane w sekcji
[Konfigurowanie węzła](#configuring-a-node).

Żebyś nie musiał wiązać każdego pola
ręcznie, połączenie dwóch portów, które niosą dokładnie ten sam kształt — na przykład
wyjścia Echo z wejściem Relay — wiąże też każdy input celu z polem o tej samej nazwie
na źródle. Pole, które już związałeś, zostaje nietknięte.

Gdy kształty się różnią albo
port nie niesie danych, nic nie jest wiązane i każde źródło wybierasz sam przez
**Bind**. Undo (`Ctrl`/`Cmd` + `Z`) cofa połączenie razem z jego bindingami, a późniejsze usunięcie
krawędzi zostawia jej bindingi na miejscu, więc usuń je lub zwiąż ponownie w panelu.

Aby usunąć połączenie, zaznacz je: kliknij linię, a zostanie narysowana grubiej, panel
pokaże jego **From** i **To**, a na nim pojawi się przycisk **Delete connection**.
Naciśnij przycisk albo `Backspace`, a połączenie zniknie, podczas gdy oba kroki
zostaną. Połączeń opublikowanej wersji nie można zaznaczyć, więc nie można ich usunąć.

Krok **For each** wykonuje swoje ciało raz na każdy element listy. Ciało nie jest
osobnym dokumentem - jest częścią tego samego płaskiego grafu, pokazaną osobno.
**Edit loop body** na kroku, które podaje, ile kroków zawiera ciało, wchodzi do tego
widoku, a okruszki **Workflow scope** w rogu kanwy pokazują, gdzie jesteś, od
**Workflow** w dół do pętli, którą otworzyłeś. Każdy okruszek nawiguje z powrotem na
zewnątrz.

Ciało zaczyna się od **Loop item**, z którym łączy się port **Each item**
pętli, i kończy na **Loop result**; nic w nim nie łączy się z powrotem z pętlą, która
idzie dalej przez **Done**, gdy każdy element przeszedł przez ciało. Paleta i źródła
binding podążają za scope, w którym jesteś, a krok w ciele może czytać wszystko, co
działało przed pętlą. Co robi pętla, opisuje
[referencja węzłów](reference/workflow-nodes.md#loops).

## Informacja zwrotna walidacji { #validation-feedback }

Edytor sprawdza graf w trakcie edycji i pokazuje, co jest nie tak i gdzie. Zaznaczony
węzeł z problemem nosi badge liczący jego problemy w nagłówku panelu; pole z problemem
pokazuje swój komunikat inline; a zwijana lista u dołu panelu zbiera problemy razem,
tak że każdy odsyła do węzła lub pola, którego dotyczy.

Komunikaty nazywają konkretną usterkę: wymagany input bez wartości, input ustawiany
przez więcej niż jedno źródło, połączenie, którego porty niosą różne kształty, krok,
którego nie da się osiągnąć od startu, pętlę z powrotem do wcześniejszego kroku,
wartość, która czyta krok niewykonany na każdej prowadzącej tutaj ścieżce, albo
połączenie, które przekracza granicę ciała pętli — do środka lub na zewnątrz.

!!! info "Kontrola edytora to podgląd; publikowanie jest autorytetem"

    Walidacja w edytorze to szybkie lustro reguł, które wymusza serwer. Istnieje po
    to, by złapać problem, gdy na niego patrzysz, ale nigdy nie jest ostatnim słowem:
    publikowanie ponownie uruchamia pełną walidację na serwerze, a problem, który
    edytor przeoczył, jest pokazywany tak samo, przy węźle lub polu, do którego
    należy.

## Autozapis i banner konfliktu rewizji { #autosave-and-the-revision-conflict-banner }

Twój draft zapisuje się sam. Krótka przerwa po tym, jak przestajesz edytować,
zapisuje bieżący graf, a status obok nagłówka to odzwierciedla — **Unsaved changes**,
gdy zapis oczekuje, **Saving…**, gdy trwa, **Saved**, gdy się dokona, i **Save failed
— will retry**, gdy się nie dokonał.

Każdy zapis jest zapisywany względem rewizji, którą otworzyłeś, więc draft edytowany
w dwóch miejscach naraz nie może po cichu nadpisać. Gdy to się zdarza, edytor podnosi
banner zatytułowany **This draft changed elsewhere**: *Someone edited this workflow
since you opened it. Overwrite keeps your changes; reload replaces them with the
latest saved draft.* Wybierasz:

- **Overwrite** — zachowaj swoją wersję i zapisz ją nad tą zapisaną gdzie indziej.
- **Reload** — odrzuć niezapisane zmiany i weź ostatnio zapisany draft.

## Publikowanie wersji i historia wersji { #publishing-a-version-and-version-history }

**Publish** zamraża bieżący draft jako niezmienną wersję, która działa — wersja nigdy
nie jest zmieniana po utworzeniu. Okno publikowania przyjmuje opcjonalną **Release
note** opisującą, co się zmieniło. Jeśli graf wciąż ma problemy, publikowanie jest
zablokowane z **Fix the problems below before publishing**, więc wersja, która by nie
przeszła walidacji, nigdy nie powstaje.

Publikowanie nie kończy Twojej edycji. Draft istnieje dalej niezależnie od każdej
opublikowanej wersji, więc edytujesz go od razu dalej. **History** w nagłówku edytora
otwiera każdą opublikowaną wersję wraz z jej release note. **View** otwiera
wcześniejszą wersję tylko do odczytu - opublikowana wersja jest tylko do odczytu, a
aby wprowadzić zmiany, edytujesz draft dalej.

Aby wrócić do opublikowanej wersji, otwórz ją przez **View** i wybierz **Restore to
draft**. Po potwierdzeniu draft przejmuje graf tej wersji, a wszystko, co w drafcie
było nieopublikowane, przepada. Sama wersja się nie zmienia i nic nie zostanie
opublikowane, dopóki znowu nie opublikujesz draftu. Undo zaczyna od nowa od
przywróconego grafu. Jeśli ktoś zmienił draft od chwili, gdy go otworzyłeś,
przywrócenie zostaje odrzucone z tym samym bannerem konfliktu, który zgłasza zapis,
zamiast nadpisać jego zmianę. Przywrócenie wymaga `workflows:edit` na tym workflow,
a zarchiwizowanego workflow nie da się przywrócić. Każde przywrócenie trafia do
[dziennika audytu](governance.md) jako `workflow.version_restored`.

## Uruchamianie workflow { #running-a-workflow }

**Runs** w nagłówku edytora i ikona runów na karcie workflow otwierają jego runy,
od najnowszego, każdy z jego statusem, tym, czy uruchomił draft czy opublikowaną
wersję, co go uruchomiło, kiedy, jak długo trwał i ile kosztował. **Start a run**
uruchamia run ręcznie: **Test the draft** uruchamia draft w obecnym stanie, a
**Published version** uruchamia żywą wersję. Jego **Input (JSON)** to to, co krok
**Input** workflow przekazuje dalej jako `payload`.

Run otwiera się na czasie trwania, koszcie i liczbie wykonanych kroków, a potem na
błędzie, którym się zakończył, jeśli taki był. Obok jest graf, który wykonał, z każdym
krokiem oznaczonym tym, co run z nim zrobił, jego próbami i błędem, oraz wyszarzonymi
krokami, do których nigdy nie dotarł. **Open loop body** pokazuje w ten sam sposób
iteracje pętli.

Wyjście runa i każdy wykonany krok, iteracja po iteracji, są obok.
Trwający run odświeża się co kilka sekund, a **Cancel run** go zatrzymuje. Jego **Files** wymieniają to, co zapisały jego kroki - pobrany plik, wyrenderowaną stronę, wynik skryptu - każde do pobrania.

## Uruchamianie workflow spoza konsoli { #starting-a-workflow-from-outside-the-console }

**Triggers** w nagłówku edytora wymienia każdą drogę do workflow. Niektóre nie
wymagają żadnej konfiguracji. Każdy, kto może uruchomić workflow, może go uruchomić
jako on sam z [HTTP API](api.md#running-a-workflow), przez WebSocket albo na czacie,
i każda z tych dróg uruchamia żywą wersję oraz jest sprawdzana, rozliczana i
audytowana tak samo jak run uruchomiony tutaj. Inne konfiguruje się raz, a potem
odpalają same: podpisany webhook i harmonogram.

### Z czatu { #from-the-chat }

Wybór tego, kto odpowiada na czacie, wymienia opublikowane workflow pod agentami. Gdy
wybrany jest workflow, każda wiadomość uruchamia jego run, z wiadomością jako
`payload.prompt`. Wątek pokazuje kartę ze statusem runa i linkiem do jego kroków, a
odpowiedź workflow pojawia się pod nią, gdy run się skończy.

Odpowiedź jest zapisywana w rozmowie, gdy run się kończy, niezależnie od tego, czy
czat jest jeszcze otwarty, więc ponowne otwarcie rozmowy ją odczytuje. Run pisze do
rozmowy, z której został uruchomiony, i nigdzie indziej: dotarcie do kogokolwiek
innego wymaga kroku HTTP albo powiadomienia w grafie.

### Przez WebSocket { #over-a-websocket }

`/api/v1/ws/workflow-runs` uruchamia run i strumieniuje jego zdarzenia albo śledzi
run, który już trwa. Klient, który stracił połączenie, łączy się ponownie z kursorem
ostatniego zdarzenia, które widział, i podejmuje dokładnie tam, gdzie przerwał.
Zdarzenia są zapisywane, zanim zostaną wysłane, więc nic nie ginie i nic nie
uruchamia się dwa razy. Gniazdo ponownie sprawdza sesję i dostęp członka przed każdą
ramką i każdym odczytem strumienia. Ramki opisuje [HTTP API](api.md#following-a-run-over-a-websocket).

### Webhook albo harmonogram { #a-webhook-or-a-schedule }

**New webhook** i **New schedule** dodają drogę, przy której nikt nie stoi. Każda
jest przypięta do wersji, która była żywa, gdy ją utworzono: ponowna publikacja
niczego nie zmienia, dopóki **Use the live version** jej nie przeniesie. Każda
działa jako członek, który ją skonfigurował albo ostatnio zmienił, a jego dostęp jest
sprawdzany od nowa przy każdym odpaleniu. Webhook, którego członek nie może już
uruchomić workflow, odrzuca dostarczenia, a taki harmonogram jest wyłączany i
odnotowywany w dzienniku audytu.

**Signing secret** webhooka jest pokazywany raz, gdy jest tworzony albo wymieniany.
Nadawca podpisuje nim dokładną treść żądania, HMAC-SHA256 w `X-Signature-256`, i
nazywa każde dostarczenie w `X-Delivery-Id`; własne nagłówki GitHuba też działają.
JSON-owa treść każdego dostarczenia jest wejściem jego runa. Ponowienie, które
powtarza id, dostaje odpowiedź z pierwszym runem i niczego nie uruchamia, bo id jest
zapisywane razem z runem, który wpuściło, w jednej transakcji.

Harmonogram uruchamia się co jakiś czas, codziennie o ustalonej godzinie albo według
wyrażenia cron, wszystko w UTC i najczęściej raz na minutę. Jego **Input** to to, od
czego zaczyna każdy run. Tyknięcie, które zastaje poprzedni run wciąż trwający, jest
pomijane, zamiast ustawiać za nim drugi run, a tyknięcie odrzucone przez limit
przyjęć czeka na następne.

## Klawiatura i dostępność { #keyboard-and-accessibility }

Każda część edytora ma drogę, która nie wymaga wskaźnika. Kliknięcie węzła w palecie
dodaje go bez przeciągania, każdy element sterujący z samą ikoną nosi wypowiadaną
etykietę, a kanwa przyjmuje fokus klawiatury, więc możesz przechodzić tabem po jej
krokach i połączeniach. Połączenie da się wykonać z klawiatury: zacznij je przy
węźle, a potem zakończ przy zgodnym celu.

Skróty kanwy działają tylko wtedy, gdy fokus jest w edytorze, więc nigdy nie kradną
klawisza polu gdzie indziej na stronie:

| Klawisze | Robi |
|---|---|
| `Ctrl`/`Cmd` + `Z` | Cofnij |
| `Ctrl`/`Cmd` + `Shift` + `Z` lub `Ctrl`/`Cmd` + `Y` | Ponów |
| `Ctrl`/`Cmd` + `C` | Kopiuj zaznaczenie |
| `Ctrl`/`Cmd` + `X` | Wytnij zaznaczenie |
| `Ctrl`/`Cmd` + `V` | Wklej, przesunięte, tak by nie zakrywało oryginału |
| `Escape` | Przerwij trwające połączenie |

Wklejenie dostaje świeże id i przemapowuje bindingi wśród skopiowanych kroków, więc
wklejone kroki czytają od siebie nawzajem, a nie od oryginałów. Każdy skrót edycji
jest bezczynny, gdy oglądasz opublikowaną wersję, która jest tylko do odczytu;
`Escape` wciąż przerywa zabłąkane połączenie.

Kopiowanie i wklejanie mają trzy ograniczenia:

- **Krok z bindingami czyta stamtąd, skąd czytał.** Skopiowany krok zachowuje swoje
  bindingi. Ten, który czyta z kroku, którego nie skopiowałeś, wciąż czyta z oryginału,
  ale nic nie łączy wklejonego kroku z tamtym, więc nie przejdzie walidacji, dopóki ich
  nie połączysz. Zaznacz oba kroki, aby skopiować parę, a kopia będzie czytać z własnego
  kroku poprzedzającego.
- **Połączenie podróżuje tylko ze swoimi dwoma krokami.** Zaznaczenie samego połączenia
  i skopiowanie niczego nie robi.
- **Skróty należą do kanwy.** Działają, gdy fokus jest na kanwie, a kliknięcie w dowolnym
  jej miejscu — w krok, pustą kanwę, połączenie — go tam zatrzymuje. Fokus w panelu
  **Properties** lub w palecie zostawia klawisze tamtym polom, więc kliknij kanwę, zanim
  ich użyjesz.

## Podsumowanie { #recap }

- Workflow to **draft, który edytujesz, i opublikowana, niezmienna wersja, która
  działa** — zacznij go pusty lub z szablonu, a **Duplicate** kopiuje draft do
  nowego workflow.
- **Paleta** dodaje kroki przez przeciągnięcie lub kliknięcie; **kanwa** je łączy i
  odrzuca połączenie między niezgodnymi portami.
- Krawędź ustala **kolejność**, a bindingi niosą **wartości**; połączenie portów o tym
  samym kształcie tworzy bindingi za Ciebie.
- Inputy węzła to **literał albo binding** — **Bind** czyta wartość z osiągalnego,
  zgodnego typem wyjścia wcześniejszego kroku.
- Draft **zapisuje się sam**, a edycja z dwóch miejsc podnosi banner z **Overwrite**
  lub **Reload**.
- **Publish** jest zablokowany, dopóki problem istnieje, i waliduje ponownie na
  serwerze; wcześniejsze wersje pozostają widoczne tylko do odczytu, a **Restore to
  draft** robi z jednej z nich z powrotem draft.
- Każda akcja ma **drogę klawiaturową**, a skróty edycji są bezczynne na opublikowanej
  wersji tylko do odczytu.
- **Triggers** uruchamiają workflow z API, przez WebSocket albo na czacie, jako ten,
  kto pyta, oraz z podpisanego **webhooka** albo **harmonogramu** przypiętego do
  jednej wersji i działającego jako członek, który go skonfigurował.
- **Polityka** kroku ustala jego próby, limit czasu i to, czy jego błędy wychodzą
  portem **Error**; ciało kroku **For each** wykonuje się od **Loop item** do **Loop
  result** raz na każdy element.
- **Runs** wymienia każdy run, **Start a run** testuje draft albo uruchamia
  opublikowaną wersję, a run pokazuje swój graf krok po kroku tak, jak przebiegł.
