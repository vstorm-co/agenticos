---
source_sha: "1537be2c7346"
---

# Workflows { #workflows }

**Workflow** łączy kroki w automatyzację, którą wykonują Twoje agenty: odczytać
[tabelę](virtual-tables.md), wywołać agenta, rozgałęzić się na podstawie wyniku,
przejść w pętli po liście. Budujesz go na kanwie, łączysz kroki ze sobą i
publikujesz jako niezmienną wersję — to ten sam kształt, który ma
[agent](concepts.md): draft, który edytujesz, i opublikowana wersja, która
działa.

Ta strona opisuje edytor wizualny: listę, kanwę i wybór kroków, sposób konfiguracji
węzła, autozapis i publikowanie oraz drogi klawiaturowe przez to wszystko. Edytor
znajduje się w sekcji **Workflows** w konsoli. Strona **listy** Workflows ma
**"?"**, które odtwarza przewodnik po tej liście; sam edytor nie ma przewodnika.

## Tworzenie i duplikowanie workflow { #creating-and-duplicating-a-workflow }

**New workflow** otwiera okno, które pozwala zacząć od wyzwalacza lub od szablonu.
**How does it start?** oferuje sześć wyzwalaczy - **Manual**, **API request**, **Chat message**, **Webhook**, **Schedule** i **New table record** - każdy jako poza nim
pusta kanwa, która od niego się zaczyna. Szablony to gotowe punkty wyjścia — **Starter**, pojedynczy krok do zmiany nazwy i podłączenia, oraz
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

### Szablony, eksport i import { #templates-exporting-and-importing }

W sekcji **Automations** dialog oferuje też typowe workflow zbudowane na
prawdziwych krokach: **Lead intake** zapisuje leady z webhooka w tabeli i
odpowiada wywołującemu, **Slack alert on failure** wysyła wiadomość, gdy inny
workflow się nie powiedzie, a **Daily summary** zleca agentowi dzienne
podsumowanie dla zespołu w dni robocze. Każdy otwiera się z tabelą, botem,
agentem albo osobami do wybrania; edytor je oznacza, a workflow da się opublikować,
gdy zostaną wybrane.

Przycisk pobierania w nagłówku edytora eksportuje szkic jako plik
`.workflow.json`. Plik nie zawiera żadnych identyfikatorów tego wdrożenia: każdy
agent, tabela, sekret, członek, bot czy workflow wybrany w kroku zostaje pominięty
i wymieniony, przypięte dane testowe też, podobnie jak workflow błędów. Nigdy nie
zawiera wartości sekretu. **Import** na liście tworzy z takiego pliku nowy szkic,
usuwa identyfikatory, które plik zrobiony ręcznie jeszcze zawiera, i wymienia
każdy krok i pole do ponownego wybrania przed publikacją. Plik z krokiem, którego
to wdrożenie nie ma, zostaje odrzucony i nic nie powstaje.

### Wyszukiwanie, nazywanie i wycofywanie workflow { #finding-naming-and-retiring-a-workflow }

Nad kartami wyszukiwanie znajduje workflow po nazwie, opisie lub tagach, filtr tagów
zawęża listę do jednego tagu, a kolejność to ostatnia edycja, nazwa albo najnowsze
najpierw. Wszystko zostaje w adresie, więc przeładowanie lub udostępniony link
pokazują tę samą listę. W edytorze kliknij nazwę, aby zmienić nazwę workflow - jego
identyfikator, którego używają wywołujący API, zostaje - kliknij opis pod nią albo
**Add a description**, aby go zmienić, a **+ Tag** przypisuje tag.

Opublikowany workflow, którego wyzwalacz działa sam - webhook, harmonogram lub nowy
rekord tabeli - ma przełącznik **Active** w nagłówku edytora, a jego karta mówi
**Active** albo **Paused**. Wyłączenie od razu wstrzymuje wyzwalacz; włączenie wznawia
go jako publikującego, więc wymaga uprawnienia do uruchamiania workflow. Menu **...**
na karcie archiwizuje workflow, co również wstrzymuje wyzwalacz. Zarchiwizowany można
przywrócić, nadal wstrzymany, albo usunąć razem z wersjami, przebiegami i
udostępnieniami; taki, którego przebiegi się nie zakończyły, jest odrzucany z
`WORKFLOW_IN_USE`.

## Kanwa i dodawanie kroków { #the-canvas-and-the-palette }

**Kanwa** to miejsce, w którym pojawiają się kroki i połączenia workflow, i ma całą
szerokość edytora pod nagłówkiem. **Węzeł** to jeden krok; **krawędź** to
połączenie ustalające kolejność: krok, na który wskazuje, działa po tym, z którego
wychodzi.

Każdy węzeł to karta z ikoną kroku, jego nazwą i jedną linią pod nią: co krok ma
robić - warunek, URL, liczba zmapowanych pól - albo grupa, do której należy, na
przykład **Slack** czy **Tables**. Krok z więcej niż jednym wyjściem wymienia porty z
nazwy: **true** i **false**, **Each item** i **Done** oraz czerwony port **Error** w
kroku, który obsługuje swoje błędy. Krok, który blokuje publikację, ma czerwony
znacznik. Gładzik albo kółko myszy przesuwa kanwę, a gest szczypania - albo Ctrl lub
Cmd z kółkiem - ją przybliża; jej przyciski są w rogu.

Kroki wybiera się w **wyborze kroków**. Pokazuje sekcje - **Start**, **AI**,
**Flow**, **Data**, **Apps and the web** - z grupami pod każdą. Grupa taka jak
**Slack**, **Tables** czy **Jev decisions** otwiera się na swoje kroki, a grupa z jednym
krokiem jest tym krokiem. **Search steps** znajduje dowolny krok po nazwie, tym, co
robi, albo po grupie. Krok dodajesz na cztery sposoby:

- **+** w lewym górnym rogu kanwy - albo **Add step** na środku pustej kanwy -
  otwiera wybór. Krok trafia za zaznaczony krok albo na koniec widocznego przepływu i
  łączy się z nim, gdy porty pasują. Krok startowy trafia zamiast tego przed obecny
  start i staje się nim.
- **+** przy wyjściu kroku otwiera wybór kroku, który idzie po tym wyjściu.
- **Prawy przycisk** na kanwie: **Add a step here** pokazuje te same sekcje i grupy, a
  krok trafia tam, gdzie kliknąłeś.
- **Przeciągnij** krok z wyboru, żeby położyć go tam, gdzie go upuścisz, bez połączeń.

Nowy krok nigdy nie ląduje na innym, zostaje zaznaczony, otwiera swoje ustawienia,
gdy jakieś ma, a kanwa przewija się do niego, gdy wypada poza widok. W ciele pętli
każdy nowy krok zostaje wpięty w ciało, więc tam zostaje. Wybór pokazuje to, co jest
poprawne tam, gdzie jesteś: **Loop item** i **Loop result** tylko w ciele pętli, a
pętlę, dopóki pętle nie są zagnieżdżone tak głęboko, jak pozwala publikacja.

Prawy przycisk na kroku daje **Open settings**, **Duplicate** i **Delete step**;
prawy przycisk na kanwie daje też **Paste**, **Undo**, **Redo** i **Fit to view**. Gdy
zaznaczonych jest kilka kroków, pasek na dole usuwa je razem.

!!! note "Katalog kroków rośnie z czasem"

    Wybór zasila lista węzłów zarejestrowanych we wdrożeniu, a nie stała lista.
    Rodzaj węzła zarejestrowany później pojawia się w nim od razu, bez zmiany
    workflow, który już zbudowałeś.

### Notatki, porządkowanie i skróty { #notes-tidying-and-shortcuts }

**Add a note here** w menu kontekstowym kanwy stawia notatkę obok kroków: markdown,
pisany po dwukrotnym kliknięciu lub ołówkiem, przesuwany przeciąganiem i zmieniający
rozmiar od rogów. Notatka jest zapisana w grafie, więc wersje, przywrócenia i kopie
workflow ją zachowują, ale nic jej nie uruchamia ani nie sprawdza. Zaznaczone połączenie
pokazuje **+**, które wstawia następny wybrany krok w jego środek, połączony z obu stron,
gdzie porty pasują. **Tidy up** na pasku narzędzi układa widoczne kroki od lewej do prawej
jako jedną edycję do cofnięcia, przycisk mapy pokazuje minimapę, a przycisk klawiatury -
albo **?** - wypisuje wszystkie skróty; **Tab** otwiera wybór kroku. Żaden nie działa,
gdy piszesz w polu.

## Konfigurowanie węzła { #configuring-a-node }

Co robi każdy węzeł, z czym się go konfiguruje i co znaczą jego błędy, opisuje
[referencja węzłów](reference/workflow-nodes.md).

Kliknij krok, a jego ustawienia otworzą się w oknie nad kanwą: nazwa, co robi i każdy
problem blokujący publikację, nad polami. Każda zmiana zapisuje się w drafcie od razu,
więc **Done** tylko zamyka okno, a **Delete step** usuwa krok. Pola dzielą się na dwie
sekcje. **Configuration** trzyma ustawienia statyczne — stałe wybory, które nie
zmieniają się między runami, w tym zasoby przypięte do kroku. **Inputs** trzyma
wartości, które krok czyta w trakcie działania.

Input wypełnia się na jeden z dwóch sposobów, a **Value** i **From a step** obok jego
etykiety przełączają między nimi:

- **Wartość** — wpisujesz ją wprost w pole, tą samą kontrolką, jakiej wymaga typ pola.
- **From a step** — czytasz wartość z wyjścia innego kroku. Pole zmienia się w wybór
  **Source**, którego opcje to wyjścia wcześniejszych kroków faktycznie osiągalne w
  tym miejscu i o zgodnym typie — całe wyjście kroku albo jedno pole w nim — każde
  pokazane jako *{node} · {port} ({type})* albo *{node} · {port} → {field} ({type})*
  dla pola. Pole, dla którego nic wcześniej nie pasuje, mówi **No compatible upstream
  outputs** zamiast proponować błędny wybór.

Pole tekstowe ma trzeci sposób, **Template**: tekst z wartościami z wcześniejszych
kroków, na przykład `New lead: {{Form.payload.name}} from {{Form.payload.company}}`.
Placeholder wskazuje krok i ścieżkę w jego wyjściu, jest sprawdzany przy publikacji
tak jak binding i podąża za krokiem, gdy ten zmieni nazwę. **Insert a value…** wstawia
go w miejscu kursora, podobnie jak pole przeciągnięte z **Input**. Gdy są dane z
przebiegu testowego, pod polem widać podgląd wyniku. Nic nie jest wykonywane: gdy krok
działa, każdy placeholder staje się tekstem swojej wartości, JSON-em dla listy albo
obiektu, a taki, za którym nic nie stoi, kończy krok błędem `INVALID_BINDING`, który
go wskazuje.

Wymagany input bez wartości to problem walidacji, oznaczony na węźle, a nie
uzupełniony cichą wartością domyślną. Niektóre pola trzymają wartości złożone: listę
wierszy, do której **Add row** dodaje, którą przestawiasz i z której usuwasz, albo
typowany wybór, który podmienia formularz pod nim. Okno wchodzi w nie rekurencyjnie,
zamiast odsyłać do osobnego ekranu.

### Nazywanie kroku, notatka i wyłączanie { #naming-noting-and-switching-off-a-step }

**Step name** nadaje krokowi własną nazwę, pokazywaną na jego karcie i wszędzie, gdzie
późniejszy krok wybiera, co czytać - dwa kroki **Send a message** stają się *Tell sales*
i *Tell support*. Dwa kroki nie mogą mieć tej samej nazwy, bez względu na wielkość
liter. **Note** zachowuje zdanie dla tego, kto edytuje workflow następny, oznaczone na
karcie. **Switched off** albo **Switch off** w menu kontekstowym kroku zostawia krok na
kanwie, przygaszony, i pomija go, gdy przebieg do niego dotrze: nic nie robi i przekazuje
dalej to, co do niego dotarło. Publikacja odrzuca wyłączony wyzwalacz lub krok
decydujący o drodze oraz krok, który czyta wyłączony, chyba że to, co do niego
dociera - jedynym połączeniem wejściowym, z kroku, który jest włączony - ma czytane
pole, które wtedy przekazuje dalej. Wszystkie trzy są zapisane w grafie, więc
wersje je zachowują.

### Dane kroku, przypinanie i test jednego kroku { #a-steps-data-pinning-and-testing-one-step }

Podczas edycji workflow okno umieszcza ustawienia kroku między dwoma panelami. **Input**
pokazuje, co przekazał każdy krok, z którego ten krok czyta, a **Output** – co przekazał
sam krok. Oba pochodzą z ostatniego przebiegu testowego uruchomionego w edytorze albo, po
otwarciu, z najnowszego. **Table** układa dane w wiersze, listę rekordów po jednym wierszu
na rekord. **JSON** pokazuje je takimi, jakie są, a **Fields** wymienia każde pole po ścieżce
z jego typem: ścieżki, które czyta późniejszy krok.

Przed pierwszym przebiegiem oba panele wymieniają pola, które krok deklaruje, po ścieżce
i typie, i je też można przeciągać. Tabela pokazuje pierwsze 50 wierszy, dopóki **Show
more** nie rozłoży reszty, a komórka ucięta do szerokości kolumny pokazuje całą wartość
po najechaniu.

Kolumnę albo pole z **Input** można przeciągnąć na ustawienie, które wtedy czyta
je z tamtego kroku, tak jakby wybrano je w **From a step**. Pole, które nie pasuje,
zostaje odrzucone z podaniem powodu: typ, którego ustawienie nie przyjmuje, albo
krok, który nie zawsze działa przed tym. Wewnątrz wartości o dowolnym kształcie,
takiej jak `values` mapowania czy `payload` wyzwalacza, typem jest ten, który
pokazał przebieg. Lista wyboru też oferuje takie wartości każdemu ustawieniu, a
ścieżkę wpisuje się w **Field inside it**.

**Pin this data** zachowuje wynik na kroku, a **Write data to pin** pozwala
wpisać własny jako obiekt JSON o rozmiarze najwyżej 64 000 bajtów. Przebieg testowy
przekazuje przypięte dane zamiast uruchamiać krok, więc wolne wywołanie modelu albo zapis
do działającego systemu wykonuje się raz i jest używany ponownie. Krok, który decyduje o
drodze, nigdy nie jest przypinany, a publikacja usuwa każde przypięcie: opublikowana wersja
zawsze uruchamia swoje kroki. Ikona pinezki oznacza kartę, a **Unpin** ją usuwa.

**Test step** uruchamia sam krok. Przebieg zachowuje tylko ten krok i kroki, które do
niego prowadzą, a każdy z nich o znanym wyniku, przypiętym albo z ostatniego przebiegu
testowego, przekazuje go zamiast się uruchamiać. Pozostałe działają, a nic po kroku nie
rusza. Krok, który zapisuje, najpierw pyta, bo test naprawdę zapisuje. Kroku w pętli nie da
się przetestować osobno, bo działa raz na element, więc przetestuj pętlę. Przez API to samo
robi `step` w `POST /api/v1/workflow-runs`.

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
port nie niesie danych, nic nie jest wiązane i każde źródło wybierasz sam przez **From a step**. Undo (`Ctrl`/`Cmd` + `Z`) cofa połączenie razem z jego bindingami, a późniejsze usunięcie
krawędzi zostawia jej bindingi na miejscu, więc usuń je lub zwiąż ponownie w ustawieniach kroku.

Aby usunąć połączenie, zaznacz je: kliknij linię, a zostanie narysowana grubiej i pojawi się na niej przycisk **Delete connection**.
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
idzie dalej przez **Done**, gdy każdy element przeszedł przez ciało. Wybór kroków i źródła binding podążają za scope, w którym jesteś, a krok w ciele może czytać wszystko, co
działało przed pętlą. Co robi pętla, opisuje
[referencja węzłów](reference/workflow-nodes.md#loops).

## Informacja zwrotna walidacji { #validation-feedback }

Edytor sprawdza graf w trakcie edycji i pokazuje, co jest nie tak i gdzie. Każdy krok z problemem ma czerwony znacznik na kanwie i licznik w swoich ustawieniach, a pole z problemem pokazuje swój komunikat inline. Status w prawym górnym rogu kanwy mówi **Ready to publish** albo liczy problemy i je wymienia, każdy pod nazwą swojego kroku i pola; wybranie jednego otwiera ustawienia tego kroku.

Ustawienia kroku pozostają krótkie. To, czego krok potrzebuje, i to, co już ustawiłeś,
widać od razu; opcjonalne ustawienia wciąż z wartościami domyślnymi czekają pod **More
options**, a **When it is slow or fails** i notatka otwierają się na żądanie albo gdy są
ustawione. Wymagana wartość, której jeszcze nie podano, nie jest oznaczana przy polu,
dopóki nie opuścisz tego pola albo nie spróbujesz uruchomić lub opublikować: znacznik
kroku na kanwie i licznik powyżej mówią o niej od początku. Opis, który tylko powtarza
nazwę pola, jest podpowiedzią przy nazwie zamiast wiersza pod polem.

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

**Compare with draft** w podglądzie wersji rysuje wersję i szkic na jednym
płótnie: każdy krok, który szkic dodał, zmienił albo usunął, jest oznaczony na swojej
karcie, a lista obok wymienia każdy zmieniony krok z tym, co się w nim zmieniło -
ustawienie, wejście, nazwę, notatkę lub wersję, czy jest wyłączony i co robi, gdy
działa wolno albo zawodzi. Przesunięcie kroku i przypięte dane testowe nie są
zmianami. **Show this version** wraca do samej wersji.

## Ustawienia workflow { #workflow-settings }

**Settings** w nagłówku edytora zawierają to, z czym workflow jest uruchamiany, a nie
to, co robi. Należą do workflow, nie do wersji: zmiana dotyczy każdego przebiegu
rozpoczętego po niej, a publikacja je zachowuje.

- **Timezone** - w niej czytane jest wyrażenie cron harmonogramu, także przy zmianie
  czasu, i w niej pisze krok **Date & time**, który nie wskazuje własnej strefy.
  Przebieg zachowuje tę ustawioną w chwili startu. Bez ustawienia UTC.
- **Default deadline** - termin, który dostaje przebieg, gdy to, co go uruchamia, nie
  podaje żadnego.
- **Error workflow** - opublikowany workflow zaczynający się od **On failure of a
  workflow**, uruchamiany raz, gdy przebieg zawiedzie. Zobacz
  [Gdy inny workflow zawiedzie](#when-another-workflow-fails).
- **Keep runs for** i **Keep runs that succeeded** - codzienne sprzątanie usuwa
  przebieg i zapisane przez niego pliki po tylu dniach od jego końca, a udany przebieg
  następnego dnia, gdy udanych się nie przechowuje. Bez ustawienia przebiegi zostają
  na zawsze.

Przez API zastępuje je `PUT /api/v1/workflows/{id}/settings`.

## Uruchamianie workflow { #running-a-workflow }

**Run** w nagłówku edytora od razu testuje szkic - `Ctrl`/`Cmd` + `Enter` też -
najpierw prosząc o pola, które deklaruje wyzwalacz Manual albo API. Run pokazuje się
potem na kanwie na bieżąco: każdy krok dostaje swój status, próby i błąd, połączenie
mówi, ile elementów nim przeszło, gdy krok przed nim przekazał listę, a pasek na dole
mówi, jak run stoi, z **Open run** do jego strony. Następna edycja go ukrywa i zostawia
pasek z informacją, że graf się od tego czasu zmienił, nadal z **Open run**. Krok,
który poczekał i poszedł dalej, liczy jedną próbę, nie dwie.
**Run** czeka, dopóki zmiana się zapisuje, i mówi, czemu nie może ruszyć, gdy szkic
ma problemy.

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


**Status**, **Version**, **Started by** i **Started** (ostatnia godzina, doba, tydzień
albo 30 dni) zawężają przebiegi, a lista odpowiada po
jednej stronie naraz; każdy filtr trafia do adresu, więc przefiltrowaną listę można
podlinkować. **Runs** na liście workflow pokazuje przebiegi wszystkich workflow
razem. Na stronie przebiegu kliknięcie kroku pokazuje jego **Input** i **Output** z
tego przebiegu.

**Retry from failed step** uruchamia nowy przebieg tej samej wersji
z tym samym wejściem, w którym każdy krok, który się udał, przekazuje to, co
przekazał wcześniej, więc działa tylko nieudany krok i to, do czego nie doszedł, a
zapis nigdy nie powtarza się dwa razy. Pętla działa ponownie i używa kroków
każdego elementu, które się udały. **Debug in editor** przypina do kroków wersji
roboczej to, co każdy krok poza pętlą przekazał w tym przebiegu, więc przebieg
testowy zaczyna od miejsca, w którym tamten był. Przez API ponawia `POST
/api/v1/workflow-runs/{id}/retry`, a `GET /api/v1/workflow-runs` przyjmuje
`status`, `mode`, `triggered_by`, `created_after` i `created_before`.

## Uruchamianie workflow spoza konsoli { #starting-a-workflow-from-outside-the-console }

Workflow startuje od jednego **wyzwalacza**, pierwszego węzła na jego kanwie. Grupa
**Triggers** na górze wyboru kroków ma ich sześć: **Manual**, **API request**, **Chat message**,
**Webhook**, **Schedule** i **New table record**. Dodanie jednego do workflow, który
ma już wyzwalacz, zastępuje stary w tym samym miejscu, a połączenia i powiązania
wychodzące ze starego wychodzą z nowego. **New workflow** zaczyna workflow od
wyzwalacza, który tam wybierzesz.

To publikacja wersji włącza jej wyzwalacz. Webhook, harmonogram i wyzwalacz tabeli
uruchamiają wtedy tę wersję jako członek, który ją opublikował, a następna
publikacja przenosi je na nową wersję. Publikacja, która startuje od innego
wyzwalacza, wyłącza stary. **Trigger** w nagłówku edytora pokazuje żywy wyzwalacz i
jego stan oraz mówi, kiedy szkic startuje inaczej.

Wersję, która startuje od **Manual** albo **API request** albo w ogóle bez wyzwalacza, uruchamia
każdy, kto może ją uruchomić, jako on sam: **Start a run** w Runs,
[HTTP API](api.md#running-a-workflow) albo WebSocket. Każdy run jest sprawdzany,
rozliczany i audytowany tak samo jak uruchomiony tutaj. Te drogi nie uruchamiają
żadnego innego wyzwalacza, a każdy inny wyzwalacz ma własną. Run testowy szkicu
przyjmuje dowolny wyzwalacz, a **Start a run** otwiera go z wejściem w kształcie
tego wyzwalacza.

**Manual** to wyzwalacz, który osoba uruchamia przyciskiem **Run**; **API request** to ten, który wywołuje system, a **Trigger** pokazuje jego endpoint i przykładowe żądanie. Daj któremuś **pola wejścia**, a run poprosi o to, czego potrzebuje: **Run** i **Start a run** pokazują formularz z jednym polem na każde pole zamiast
JSON-a, z typem pola, a wywołanie API, którego wejście nie pasuje, jest odrzucane z
listą błędnych pól. Zobacz [core.input](reference/workflow-nodes.md#core-input).

### Z czatu { #from-the-chat }

Wybór tego, kto odpowiada na czacie, wymienia pod agentami opublikowane workflow,
które startują od **Chat message**. Gdy wybrany jest jeden z nich, każda wiadomość
uruchamia jego run, a wyzwalacz przekazuje kolejnym krokom wiadomość jako `prompt`,
razem z `conversation_id` i `user_id` nadawcy. Wątek pokazuje kartę ze statusem runa
i linkiem do jego kroków, a odpowiedź workflow pojawia się pod nią, gdy run się
skończy.

Odpowiedź jest zapisywana w rozmowie, gdy run się kończy, niezależnie od tego, czy
czat jest jeszcze otwarty, więc ponowne otwarcie rozmowy ją odczytuje. Run pisze do
rozmowy, z której został uruchomiony, i nigdzie indziej: dotarcie do kogokolwiek
innego wymaga kroku HTTP albo powiadomienia w grafie.

**Open chat** w nagłówku edytora pozwala wypróbować szkic zaczynający się od
wiadomości czatu bez wychodzenia z niego. Każda wiadomość wysłana w panelu
uruchamia testowy run szkicu z tą wiadomością, run otwiera się na płótnie, a jego
odpowiedź - tekst kroku Output - pojawia się pod wiadomością. To testowe runy bez
rozmowy, do której mogłyby odpowiedzieć, więc nic z panelu nie trafia do
prawdziwego czatu. **New chat** zaczyna od nowa z nowym id rozmowy.

### Przez WebSocket { #over-a-websocket }

`/api/v1/ws/workflow-runs` uruchamia run i strumieniuje jego zdarzenia albo śledzi
run, który już trwa. Klient, który stracił połączenie, łączy się ponownie z kursorem
ostatniego zdarzenia, które widział, i podejmuje dokładnie tam, gdzie przerwał.
Zdarzenia są zapisywane, zanim zostaną wysłane, więc nic nie ginie i nic nie
uruchamia się dwa razy. Gniazdo ponownie sprawdza sesję i dostęp członka przed każdą
ramką i każdym odczytem strumienia. Ramki opisuje [HTTP API](api.md#following-a-run-over-a-websocket).

### Webhook albo harmonogram { #a-webhook-or-a-schedule }

Wyzwalacz **Webhook** dostaje adres i **signing secret** przy pierwszej publikacji
wersji, która go zawiera. Publikacja pokazuje sekret raz, a kolejne publikacje tego
samego węzła zachowują oba; węzeł webhooka usunięty i dodany ponownie dostaje nowy
adres. Nadawca podpisuje sekretem dokładną treść żądania, HMAC-SHA256 w
`X-Signature-256`, i nazywa każde dostarczenie w `X-Delivery-Id`; własne nagłówki
GitHuba też działają. Wyzwalacz przekazuje JSON dostarczenia jako `body`, razem z
jego `delivery_id`. Ponowienie, które powtarza id, dostaje odpowiedź z pierwszym
runem i niczego nie uruchamia, bo id jest zapisywane razem z runem, który wpuściło,
w jednej transakcji.

Wyzwalacz **Schedule** uruchamia się co jakiś czas, codziennie o ustalonej godzinie
albo według wyrażenia cron, w strefie czasowej workflow (UTC, chyba że jego **Settings** wskazują inną) i
najczęściej raz na minutę. Jego
**Input** to to, od czego zaczyna każdy run, przekazywane jako `input` obok
`fired_at` danego tyknięcia. Tyknięcie, które zastaje poprzedni run wciąż trwający,
jest pomijane, zamiast ustawiać za nim drugi run, a tyknięcie odrzucone przez limit
przyjęć czeka na następne.

Oba działają jako członek, który opublikował wersję, a jego dostęp jest sprawdzany od
nowa przy każdym odpaleniu. Webhook, którego członek nie może już uruchomić
workflow, odrzuca dostarczenia, a taki harmonogram jest wyłączany i odnotowywany w
dzienniku audytu. **Pause** w arkuszu **Trigger** zatrzymuje każdy z nich bez
publikacji, a **New secret** wymienia sekret webhooka; stary od razu przestaje
przechodzić weryfikację.

### Gdy przybędzie rekord tabeli { #when-a-table-record-is-added }

Wyzwalacz **New table record** wskazuje tabelę i filtruje każdy rekord taki, jakim go
dodano - z konsoli, przez API, przez agenta albo krok tabeli innego workflow.
Przekazuje rekord: jego `record_id`, `values` według id kolumn, te same wartości jako
`fields` według etykiet oraz `author_id` tego, kto go dodał. Publikacja wymaga
dostępu do odczytu tabeli, a rekord dodany przed publikacją nigdy go nie uruchamia.
Run uruchomiony w ten sposób niesie łańcuch wyzwalaczy, przez które przeszedł, więc
workflow zapisujący z powrotem do tabeli, której wyzwalacz go uruchomił, jest
blokowany zamiast się zapętlić.

**Triggers** samej tabeli wymienia workflow, które od niej startują, wstrzymuje je i
wznawia oraz pokazuje, co każdy zdecydował o każdym rekordzie. Zobacz
[Virtual Tables](virtual-tables.md#triggers).

### Gdy wywołuje go inny workflow { #when-another-workflow-calls-it }

Wyzwalacz **Called by a workflow** tworzy workflow, który inne uruchamiają jako krok:
wspólna logika - wzbogacenie leada, założenie zgłoszenia - trzymana w jednym miejscu.
Deklaruje pola tak jak **Manual**, a krok **Run a workflow** innego workflow, który
oferuje tylko tak opublikowane workflow, uruchamia go z powiązanym wejściem,
sprawdzonym najpierw względem tych pól.

Krok czeka na wywołany przebieg i przekazuje
jego `output` albo od razu idzie dalej, gdy **Wait for it to finish** jest wyłączone.
Wywołany przebieg jest powiązany z wywołującym w obie strony - jego strona mówi
**Called by** ten przebieg, a wiersz kroku na stronie wywołującego otwiera przebieg,
który krok uruchomił - i widać go na stronach przebiegów jak każdy inny. Przebieg
uruchomiony przez workflow błędów mówi, niepowodzenie którego przebiegu go uruchomiło. Wywołanie z powrotem workflow, który już działa w łańcuchu, albo głębsze
niż pięć wywołań, zostaje odrzucone.

### Gdy inny workflow zawiedzie { #when-another-workflow-fails }

Wyzwalacz **On failure of a workflow** tworzy workflow błędów. Wybrany jako workflow
błędów innego workflow w jego **Settings**, uruchamia się raz dla każdego prawdziwego
przebiegu tamtego workflow, który zakończy się niepowodzeniem, z `run_id` przebiegu,
jego `workflow_id` i `workflow_name`, `step_id` i `step_name` kroku, który zawiódł,
oraz `error`, którym się zakończył. Działa jako członek, który go wybrał i który
nadal musi móc go uruchomić. Przebieg testowy niczego nie uruchamia, podobnie jak
porażka przebiegu, który sam jest workflow błędów, więc zawodzący workflow błędów
nigdy nie uruchamia się ponownie.
## Gdy coś pójdzie nie tak { #when-something-goes-wrong }

**Co obiecuje run.** Wynik kroku i wysłanie kroków po nim zapisują się razem, więc
worker, który zatrzyma się między krokami, niczego nie gubi: inny podejmuje run tam,
gdzie był. Worker, który zatrzyma się w środku kroku, zostawia próbę, której końca
nikt nie widział. Krok bezpieczny do powtórzenia jest ponawiany. Zapis do tabeli
odtwarza swój pierwszy zapis przez potwierdzenie zamiast zapisywać drugi raz, a
powiadomienie idzie raz. Krok, który mógł już zadziałać gdzie indziej i niczego więcej
nie obiecuje - jak uruchomienie agenta - nigdy nie jest powtarzany sam: run zatrzymuje
się jako **Wymaga uwagi**, żeby nikt nie zapłacił za model dwa razy ani nie wysłał
wiadomości dwa razy, zanim ktoś o tym zdecyduje.

Nic innego nie dzieje się dokładnie raz. Wywołanie HTTP, upload albo zapis pliku mogą
zostać wykonane ponownie po takim zatrzymaniu, więc system odbierający, który nie może
zobaczyć żądania dwa razy, potrzebuje własnego klucza idempotencji. Obietnica ponowień
każdego kroku jest w [referencji węzłów](reference/workflow-nodes.md).

| Co widzisz | Dlaczego | Co zrobić |
|---|---|---|
| **Wymaga uwagi** | Przerwano krok, który mógł zadziałać | Sprawdź, czy jego efekt nastąpił, a potem anuluj run i uruchom nowy, jeśli nie. Wznowienie go z konsoli nie jest jeszcze zbudowane |
| `PRINCIPAL_REVOKED` | Członek, jako który działa run, stracił dostęp albo jego konto dezaktywowano | Niech członek, który może uruchamiać workflow, opublikuje go ponownie, żeby jego wyzwalacz działał jako on |
| `WORKFLOW_TRIGGER_MISMATCH` | Run zażądano drogą, którą nie jest żywy wyzwalacz: ręcznie albo przez API dla workflow startującego od webhooka, albo na czacie dla takiego, który nie startuje od wiadomości na czacie | Uruchom go tak, jak mówi jego wyzwalacz, albo przetestuj szkic, który przyjmuje dowolny wyzwalacz |
| `INVALID_BINDING` | Wartość nie pasowała do pola, do którego ją zbindowano | Błąd kroku wskazuje pole; popraw binding albo wartość wcześniej w grafie |
| `REVISION_CONFLICT` | Ktoś zmienił rekord po tym, jak krok go odczytał | Skieruj błąd kroku przez `error.handle` do świeżego odczytu |
| Historia wyzwalacza tabeli mówi **Zablokowany** | Run uruchomiłby sam siebie ponownie albo jego łańcuch sięgnął za głęboko | Zobacz [Wyzwalacze](virtual-tables.md#triggers) |
| Webhook odpowiada `403` | Podpis nie pasuje do treści albo członek, jako który działa, nie może już uruchamiać workflow | Podpisz dokładnie wysłane bajty bieżącym sekretem albo niech członek, który może go uruchamiać, opublikuje go ponownie |

## Klawiatura i dostępność { #keyboard-and-accessibility }

Każda część edytora ma drogę, która nie wymaga wskaźnika. Wybór kroków to lista, po której poruszasz się strzałkami i wybierasz Enterem, a kliknięcie węzła w nim
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
  jej miejscu — w krok, pustą kanwę, połączenie — go tam zatrzymuje. Fokus w ustawieniach kroku lub w wyborze kroków zostawia klawisze tamtym polom, więc kliknij kanwę, zanim
  ich użyjesz.

## Podsumowanie { #recap }

- Workflow to **draft, który edytujesz, i opublikowana, niezmienna wersja, która
  działa** — zacznij go od wyzwalacza lub z szablonu, a **Duplicate** kopiuje draft do
  nowego workflow.
- **Wybór kroków** dodaje kroki - z **+**, z wyjścia kroku albo prawym przyciskiem; **kanwa** je łączy i
  odrzuca połączenie między niezgodnymi portami.
- Krawędź ustala **kolejność**, a bindingi niosą **wartości**; połączenie portów o tym
  samym kształcie tworzy bindingi za Ciebie.
- Inputy węzła to **wartość albo binding** — **From a step** czyta wartość z osiągalnego,
  zgodnego typem wyjścia wcześniejszego kroku.
- Draft **zapisuje się sam**, a edycja z dwóch miejsc podnosi banner z **Overwrite**
  lub **Reload**.
- **Publish** jest zablokowany, dopóki problem istnieje, i waliduje ponownie na
  serwerze; wcześniejsze wersje pozostają widoczne tylko do odczytu, a **Restore to
  draft** robi z jednej z nich z powrotem draft.
- Każda akcja ma **drogę klawiaturową**, a skróty edycji są bezczynne na opublikowanej
  wersji tylko do odczytu.
- Workflow startuje od jednego węzła **wyzwalacza** - **Manual**, **API request**, od
  wiadomości na czacie, podpisanego **webhooka**, **harmonogramu** albo nowego
  rekordu tabeli - a **publikacja** go włącza i działa jako członek, który publikował.
- **Polityka** kroku ustala jego próby, limit czasu i to, czy jego błędy wychodzą
  portem **Error**; ciało kroku **For each** wykonuje się od **Loop item** do **Loop
  result** raz na każdy element.
- **Runs** wymienia każdy run, **Start a run** testuje draft albo uruchamia
  opublikowaną wersję, a run pokazuje swój graf krok po kroku tak, jak przebiegł.
