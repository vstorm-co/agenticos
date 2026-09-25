---
source_sha: "d22d5fce4b79"
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

Lista grupuje każdy workflow, który widzisz, według statusu — **Drafts**, które
wciąż budujesz, opublikowane wersje **Published**, które działają, oraz **Archived**
— a **Filter by status** zawęża do jednego. Badge każdego wiersza pokazuje
**Draft**, **Published** lub **Archived**.

**Duplicate** kopiuje bieżący draft workflow do nowego o nazwie *{name} (copy)*.
Duplikat to nowy workflow z własnym draftem, nigdy kopia opublikowanej wersji.

!!! info "Pusta lista może być filtrem, a nie pustą organizacją"

    **No workflows yet** i **Nothing matches** to różne stany: pierwszy to
    organizacja bez żadnego workflow, drugi to filtr statusu, pod który nie
    wpada żaden wiersz. **Clear filter** przywraca pełną listę. Workflow
    udostępniony Tobie pojawia się na tej samej liście, gdy masz `workflows:view`.

## Kanwa i paleta { #the-canvas-and-the-palette }

**Kanwa** to miejsce, gdzie pojawiają się kroki i połączenia workflow. **Węzeł** to
jeden krok; **krawędź** to połączenie niosące wyjście jednego kroku do następnego.
Kanwę można przesuwać i przybliżać, a jej elementy sterujące są w rogu — nie ma
minimapy.

Paleta **Nodes** z boku wymienia typy węzłów, które zarejestrowała Twoja
deployment, pogrupowane według kategorii, każdy z ikoną, nazwą i opisem. **Search
nodes** filtruje listę. Krok dodajesz na dwa sposoby:

- **Przeciągnij** węzeł z palety na kanwę — droga dla wskaźnika.
- **Kliknij** węzeł, aby dodać go blisko środka widoku — droga dla klawiatury i
  dotyku, która nie wymaga przeciągania.

Paleta pokazuje, co jest tu ważne, gdzie właśnie jesteś. Wewnątrz ciała pętli
ukrywa rodzaje węzłów, które nie mogą tam istnieć, więc lista, którą widzisz, jest
zawsze możliwa do dodania w edytowanym scope.

!!! note "Katalog węzłów rośnie z czasem"

    Paletę zasilają zarejestrowane węzły deployment, a nie stała lista. Na początku
    katalog jest mały; więcej rodzajów węzłów — wywołanie agenta, odczyt i zapis
    tabeli, rozgałęzienia i pętle — dochodzi, gdy rejestrują je późniejsze
    milestone'y, i pojawiają się w palecie w tej samej chwili, bez zmiany w
    workflow, który już zbudowałeś.

## Konfigurowanie węzła { #configuring-a-node }

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
  osiągalne tutaj i niosące zgodny typ, każde pokazane jako *{node} · {port}
  ({type})*. Pole bez niczego zgodnego wcześniej mówi **No compatible upstream
  outputs**, zamiast oferować nieprawidłowy wybór.

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

## Połączenia i scope foreach { #connections-and-foreach-scope }

Krawędź rysujesz, łącząc port wyjściowy jednego węzła z portem wejściowym innego
węzła. Edytor odrzuca połączenie między portami, które niosą różne kształty, zanim je
narysuje, więc niezgodne połączenie nigdy nie ląduje na kanwie.

Krok `foreach` wykonuje swoje ciało raz na każdy element listy. Ciało nie jest
osobnym dokumentem — jest częścią tego samego płaskiego grafu, pokazaną osobno.
**Open body** na kroku wchodzi do tego widoku, a okruszki **Workflow scope**
pokazują, gdzie jesteś, od **Workflow** w korzeniu w dół do pętli, którą otworzyłeś.
Każdy okruszek nawiguje z powrotem na zewnątrz. Paleta i źródła binding podążają za
scope, w którym jesteś, więc to, co możesz dodać i skąd możesz czytać, jest zawsze
tym ważnym na danym poziomie.

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
opublikowanej wersji, więc edytujesz go od razu dalej, a każda opublikowana wersja
jest wymieniona w **Version history** wraz ze swoją release note. **View** otwiera
wcześniejszą wersję tylko do odczytu — opublikowana wersja jest tylko do odczytu, a
aby wprowadzić zmiany, edytujesz draft dalej.

## Uruchamianie workflow { #running-a-workflow }

Zakładka **Runs** workflow to miejsce, gdzie pojawią się jego testowe i produkcyjne
runy, krok po kroku z ich inputami, wyjściami i kosztami. Historia runów pojawia się,
gdy zostanie wydany runner workflow; do tego czasu zakładka pokazuje, że nie jest
jeszcze dostępna, a edytor służy do budowania i publikowania.

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

## Podsumowanie { #recap }

- Workflow to **draft, który edytujesz, i opublikowana, niezmienna wersja, która
  działa** — zacznij go pusty lub z szablonu, a **Duplicate** kopiuje draft do
  nowego workflow.
- **Paleta** dodaje kroki przez przeciągnięcie lub kliknięcie; **kanwa** je łączy i
  odrzuca połączenie między niezgodnymi portami.
- Inputy węzła to **literał albo binding** — **Bind** czyta wartość z osiągalnego,
  zgodnego typem wyjścia wcześniejszego kroku.
- Draft **zapisuje się sam**, a edycja z dwóch miejsc podnosi banner z **Overwrite**
  lub **Reload**.
- **Publish** jest zablokowany, dopóki problem istnieje, i waliduje ponownie na
  serwerze; wcześniejsze wersje pozostają widoczne tylko do odczytu.
- Każda akcja ma **drogę klawiaturową**, a skróty edycji są bezczynne na opublikowanej
  wersji tylko do odczytu.
