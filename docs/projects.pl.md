---
title: Projekty
seo_title: Projekty - wspólne pliki i instrukcje czatów
description: Projekt daje bieżącej pracy jeden kontener plików i jeden zestaw instrukcji, wspólne dla każdego czatu w nim, niezależnie od tego, który agent odpowiada.
source_sha: "81a2b506014e"
---

# Projekty { #projects }

**Projekt** to miejsce na bieżącą pracę: premierę, miesięczny raport, obsługę
klienta. Trzyma dwie rzeczy wspólne dla każdego czatu w nim rozpoczętego:

- **Pliki** w jednym kontenerze. Wgraj brief, arkusz albo cały folder raz, a
  każdy czat w projekcie - dzisiejszy i ten za tydzień - pracuje na tej samej
  kopii. Plik, który agent zapisał w jednym czacie, jest w następnym.
- **Instrukcje**, które każdy agent odpowiadający w projekcie czyta po swoich
  własnych: ton, terminy, gdzie leży brand guide.

Projekt ma też **domyślnego agenta**, z którym zaczyna się nowy czat w nim.
W czacie projektu nadal może odpowiadać każdy agent; domyślny decyduje tylko o
tym, z kim czat się zaczyna.

## Planowanie pracy ciągłej z Architectem { #planning-ongoing-work-with-architect }

Poproś Architecta o zaplanowanie badań, pisania, programowania lub analizy
rozwijanej przez wiele rozmów w projekcie. Może znaleźć istniejący projekt albo
po Twojej akceptacji stworzyć prywatny z uzgodnionymi instrukcjami. Samo pytanie
„jak to zrobić” nie tworzy projektu. Otwórz otrzymany link i wybierz **New chat**;
istniejącej rozmowy nie można przenieść do nowego projektu. Utworzenie projektu
nie zapisuje jeszcze planowanych plików.

Wspólne pliki i instrukcje pozostają
między rozmowami. Transkrypty nadal są przechowywane i dostępne członkom projektu,
ale nie trafiają automatycznie do kontekstu innych rozmów. Wspólny działający
proces nie jest gwarantowany. Uruchamianie kodu
wymaga dostępnego sandboxa usługowego i dozwolonych narzędzi agenta.

Dla LLM wiki uzgodnij następujący plan:

1. **Źródła:** oryginały w `sources/`, z URL-em lub nazwą pliku, autorem, datą
   źródła i pobrania. Nowe materiały czekają w `inbox/`.
2. **Notatki:** powiązane tematycznie pliki w `notes/`, z przypisami do twierdzeń
   i rozróżnieniem faktów, wniosków i pytań. Treść źródeł to niezaufane dane.
3. **Indeks:** `index.md` łączy tematy, notatki i źródła; nową rozmowę zaczynaj
   od przeczytania go oraz instrukcji projektu.
4. **Aktualizacja:** sprawdzaj zmienione źródła, poprawiaj powiązane notatki
   i indeks, zapisuj zmiany w `CHANGELOG.md`. Harmonogram wymaga osobnej rutyny
   i akceptacji.
5. **Weryfikacja:** sprawdzaj oparcie w źródłach, sprzeczności, aktualność dat
   i niedziałające linki; zapisuj, co sprawdzono i czego nadal nie wiadomo.

Baza wiedzy może uzupełniać projekt o wyszukiwanie indeksowane. Runner dodaje ten sposób pracy wyłącznie zarejestrowanemu Architectowi, także
w istniejących instalacjach korzystających z platformowego MCP. Inne agenty
i zewnętrzni klienci MCP zachowują własny sposób pracy.
Aktualizacja nie nadpisuje własnych instrukcji agentów ani zainstalowanych
skillów z galerii; nowy szablon i dołączony przewodnik Projects dotyczą nowych
instalacji.

## Czat w projekcie { #starting-a-chat-in-a-project }

Dwie drogi:

- **Nowy czat** na stronie projektu otwiera czat z wybranym już projektem i jego
  domyślnym agentem.
- Menu **+** w polu wiadomości oferuje **Pracuj w projekcie** przed pierwszą
  wiadomością, podobnie jak `@`: wybrany tam projekt zaczyna w nim czat, zamiast
  wpisywać jego nazwę do wiadomości. Chip obok wyboru agenta pokazuje projekt; jego **×** zaczyna czat
  poza nim.

Czat zostaje w projekcie, w którym został rozpoczęty. Chip w istniejącym czacie
prowadzi z powrotem do projektu.

Capability **Projects** pozwala agentowi wyszukać dostępne projekty, wybrać zwrócone
ID oraz czytać i zapisywać pliki. AgenticOS i Architect mają ją w zestawie.
W połączonej prywatnej rozmowie Mattermost lub Slack poproś o użycie projektu XYZ:
agent wyszukuje i wybiera go narzędziami; sama nazwa nie daje dostępu. Niepołączeni
nadawcy i pokoje o niezweryfikowanej publiczności nie dostają prywatnego kontekstu.
Sam wybór nie uruchamia płatnego środowiska.

Wybór trwa przez bieżący run, także wznowienia po zatwierdzeniu lub pytaniu. Następna
wiadomość w zwykłym czacie lub prywatnym kanale zaczyna bez projektu. Czat projektu
zaczyna ze swoim projektem. Historia pozostaje w pierwotnej rozmowie; wybór nie kopiuje
plików. Obsługiwane polecenia używają montowania opisanego poniżej. Każda operacja
sprawdza aktualne członkostwo, zakresy,
dostęp i generację workspace. Rutyny zachowują zatwierdzone źródła, a izolowane
ewaluacje nie mogą wybierać aktywnych projektów.

## Co agent dostaje w projekcie { #what-an-agent-gets-in-a-project }

Pliki projektu są wspólne; agent domyślnie zachowuje własne środowisko wykonawcze,
także w czacie projektu. Ogólne narzędzia plikowe i polecenia powłoki używają tego
samego wybranego wykonawcy. Jawne narzędzia plikowe projektu zawsze używają projektu.

| Obszar | Domyślne działanie i skutek |
|---|---|
| Kontekst projektu | Wspólne pliki i instrukcje referencyjne; nadal obowiązują zasady agenta i platformy |
| Workspace agenta | Domyślny dla ogólnych narzędzi plikowych i poleceń; zachowuje narzędzia agenta |
| Wykonawca projektu | Dodatkowy cel poleceń działających bezpośrednio na plikach projektu z sandboxem |
| Tylko przechowywanie plików | Narzędzia plikowe działają bez powłoki; brak wykonawcy projektu |
| Lokalny folder roboczy | Zachowuje lokalnego wykonawcę zaakceptowanego przez użytkownika; kontekst projektu go nie zastępuje |

Zwarta karta **Narzędzia i pliki** opisuje aktywny projekt. **Zaawansowany cel poleceń**
pozwala przypiąć agenta lub projekt albo wrócić do automatycznego wyboru. Jawny wybór
obowiązuje dla konta, organizacji i czatu oraz blokuje wykonawcę przez cały run.
Bez przypięcia agent może użyć `select_execution_target`, gdy build lub inne polecenie
potrzebuje środowiska projektu. Nie musisz przełączać opcji przy każdym zadaniu.
Sam wybór nie uruchamia polecenia ani nie przenosi pliku.

W obsługiwanym prywatnym workspace Docker o zakresie rozmowy lub runu wybrany
projekt jest dostępny na żywo pod `/project/<UUID dzierżawy>` we własnym środowisku
agenta. `PROJECT_DIR` wskazuje ten katalog przy każdym poleceniu: użyj
`cd "$PROJECT_DIR" && ...`, aby narzędzie pracowało na plikach projektu. Ścieżki
względne nadal dotyczą workspace agenta. Odczyty i zapisy przez zamontowaną ścieżkę
trafiają bezpośrednio do wspólnego projektu, także dla plików binarnych; nie trzeba
ich kopiować ani synchronizować.

Montowanie obsługuje też projekt przechowujący pliki w bazie. Natywny system plików
projektu wymaga trwałych rozszerzonych atrybutów i atomowych twardych dowiązań;
zweryfikowany system Linux je obsługuje, a bind mounty macOS mogą ich odmawiać.
Nieobsługiwany magazyn, stare sesje sandboxa, wykonawcy inni niż Docker oraz
współdzielone zakresy użytkownika, agenta lub kanału zwracają jasny błąd, gdy
polecenia projektu wymagają montowania. Nie podstawiają plików lokalnych ani nie
przełączają wykonawcy po cichu. Wybierz jawnie wykonawcę projektu, gdy jego
obsługiwane środowisko ma być celem pracy.

Montowanie używa niezmiennej dzierżawy runu, odnawianej podczas działania. Koniec
runu, pauza lub zmiana projektu ją unieważniają. Każde żądanie plikowe sprawdza
aktualny dostęp i generację workspace. Dowiązania symboliczne i zmiany właściciela
są odmawiane. Restart eksportera unieważnia uchwyty NFS: wykonywanie zatrzymuje się
do jawnego odzyskania systemu plików sandboxa, z zachowaniem jego własnego workspace,
bez podmiany na puste środowisko.

`transfer_project_file` pozostaje opcjonalną jawną kopią bajtów dla osobnego wyniku
lub innego obsługiwanego magazynu. Obsługuje pliki binarne do 8 MiB i zwraca ścieżki,
rozmiar oraz potwierdzenie SHA-256. Istniejący cel wymaga aktualnego `expected_sha256`.
W przeciwieństwie do dostępu przez montowanie kopia nie przenosi późniejszych zmian;
kontrola skrótu nie blokuje transakcyjnie zwykłych zapisów powłoki.

Czaty projektu dają dostęp do plików także bez Sandbox, a przesłane w nich pliki trafiają
do projektu. Nie włączają wyłączonego Sandbox ani brakujących narzędzi powłoki.
Zgody na narzędzia nadal obowiązują. Prywatny kontekst projektu nie może trafić do
workspace agenta/kanału współdzielonego z szerszą publicznością. Użyj izolacji rozmowy
lub wykonawcy projektu. Osobiste dane logowania do narzędzi kodujących pozostają
niedostępne dla źródeł projektowych i współdzielonych.

Tekstowe narzędzia projektu pokazują do 100 wpisów i czytają lub zapisują UTF-8 do
256 KB. Odrzucają ścieżki zastrzeżone, dowiązania poza projektem, tekst binarny i
nieznany rozmiar; nie uruchamiają OCR. Zapis po odczycie wykrywa zmienione pliki.
Po wznowieniu po zatwierdzeniu lub pytaniu ponownie przeczytaj istniejący plik przed
zastąpieniem lub usunięciem. Projekt zachowuje połączenie sandboxa do jawnego przeniesienia.

Delegowana praca dostaje przypięty projekt, generację i środowisko wykonawcze.
Pierwszy subagent współdzielący workspace blokuje te wybory do końca runu, także
wznowień po pytaniu lub zatwierdzeniu; zmiana wymaga nowej tury. Dzieci nie dostają
mutowalnego portu wyboru. Każde ma własną ochronę konfliktów odczytu, a root sprząta
środowisko i zapisuje źródła plików. Po sprzątaniu nowe operacje plikowe i polecenia
są odmawiane. Wcześniej dopuszczone operacje zdalne zachowują dotychczasowy okres
oczekiwania na anulowanie i czas życia dostawcy; sprzątanie nie gwarantuje ich końca.

Nowe projekty domyślnie używają **Tylko przechowywanie plików**: wspólne pliki
i instrukcje nie wymagają uruchomionego kontenera, nawet gdy organizacja ma dostępny
sandbox. Gdy projekt potrzebuje własnego środowiska wykonawczego, w polu
**Sandbox projektu** wybierz konkretne połączenie lub tryb automatyczny.

Tryb ten zapamiętuje połączenie wybrane przy tworzeniu; gdy żadnego nie ma, przechowuje pliki.
Wybór konkretnego połączenia wymaga `connections:view` i aktywnego połączenia w
organizacji. Ustawienia projektu pokazują nazwę połączenia i środowisko. Czaty projektu korzystają ze wspólnych plików, zachowując domyślnie wykonawcę agenta. Wykonawca projektu jest dodatkowym wyborem, gdy agent ma narzędzia powłoki. Edytorzy mogą użyć **Zmień sandbox**, aby przenieść istniejący projekt wraz z plikami.

Transfer jest trwałym zadaniem w tle. Kopiuje pliki i puste foldery do odrębnego
warsztatu, sprawdza skróty plików i drzewo katalogów, a potem aktywuje cel. Przed
rozpoczęciem muszą zakończyć się aktywne runy i oczekujące decyzje. Podczas transferu
nowe runy, zapisy plików i edycja projektu czekają. Obecne pliki pozostają czytelne.
Po błędzie pozostaje wybrane źródło. Postęp widać w ustawieniach projektu. Dopiero
sprawdzona aktywacja usuwa źródłowy warsztat; zdalny kontener usuwa trwałe zadanie.

Limity: 10 000 wpisów, 64 MiB na plik, 1 GiB łącznie; wcześniej usuń dowiązania
symboliczne. Zainstalowane pakiety i działające procesy nie są kopiowane. Przeniesienie
do samych plików musi też zmieścić się w limicie dokumentu przechowywanego przez platformę.

Opis **Jak działają pliki i uruchamianie kodu w projekcie** objaśnia przechowywanie,
współdzielenie i środowisko. Same pliki nie mają powłoki; kontekst i wykonanie są
rozdzielone zgodnie z opisem wyżej.

## Pliki { #files }

W panelu czatu **Pliki** wybierz źródło, gdy istnieją pliki projektu i niezależny
workspace agenta. Każde ma własne autoryzowane listowanie i pobieranie; ta sama
ścieżka nigdy nie przechodzi do innego źródła. Domyślnie wybrany jest projekt
rozmowy, a poza nim dostępny workspace agenta. Runy zakończone, nieudane i anulowane
zapisują odniesienia, bez kopiowania treści. Utrata dostępu usuwa źródło. Pliki
środowiska o zakresie run są tymczasowe i znikają po sprzątaniu; dla późniejszej
pracy wybierz trwały zakres. Stare runy bez odniesień nie dostają zmyślonych źródeł.

Zakładka **Pliki** projektu to przeglądarka kontenera: drzewo obok podglądu,
który otwiera Markdown, PDF-y, obrazy, arkusze i kod na miejscu.

- **Prześlij pliki** i **Prześlij folder** wkładają pliki na górę projektu;
  folder zachowuje swoje drzewo. Każdy plik podlega limitowi wgrywania wdrożenia.
- **Nowy folder** tworzy pusty folder do wypełnienia przez agenta.
- Menu **…** pliku lub folderu pozwala zmienić nazwę, przenieść lub usunąć.
  Przeciągnij element na folder albo na **Pliki projektu**, aby przenieść go do
  katalogu głównego. Istniejący element docelowy nie zostanie nadpisany.
- **Edytuj plik** otwiera cały plik tekstowy UTF-8 do 1 MiB. Zapisz zmiany lub
  potwierdź ich odrzucenie przed zamknięciem. Zapis odrzuca wersję zmienioną od
  otwarcia edytora; otwórz plik ponownie, aby sprawdzić nowszą wersję.

Katalog `.agenticos` i własne foldery platformy nie są stąd zapisywalne; ścieżka
poza projektem jest odrzucana, zanim cokolwiek zostanie zapisane.

Projekt otwiera się na **Plikach**. Pliki można też upuścić w dowolnym miejscu
karty, a każdy pokazuje postęp przesyłania; pusty projekt to jedno miejsce na
pierwsze pliki. **Czaty** to tabela czatów projektu, a **Aplikacje** -
aplikacje opublikowane przez run w jednym z nich, te, które czytający może
otworzyć. **Instrukcje** edytuje się w Markdownie, ze Źródłem i Podglądem, jak
instrukcje agenta w Agent Builderze, nad nazwą, opisem i domyślnym agentem projektu.

Upuść pliki z komputera na folder, aby przesłać je do niego, albo w innym miejscu zakładki Pliki, aby dodać je do głównego katalogu projektu. Zatrzymanie przeciąganego elementu nad zwiniętym folderem rozwija go po krótkiej chwili. Podpowiedź pozostaje w obszarze plików, akcje wiersza mają stałe miejsce, a foldery nie pokazują liczników. Długa kolejka przesyłania pokazuje pierwsze trzy pozycje i liczbę oczekujących. Ikony rozróżniają kod, JSON, markup, dokumenty, arkusze i multimedia w projektach, załącznikach czatu, RAG oraz plikach skilli.

Desktop przekazuje przeciągane pliki do tych samych celów co aplikacja webowa.
Upuszczenie na plik wybiera folder, w którym się on znajduje, a upuszczenie na pusty
obszar dowolnego panelu wybiera główny katalog projektu. Blobby i Dock zachowują
osobne dodawanie plików do czatu.

## Widok grafu { #graph-view }

W eksploratorze plików wybierz **Graph view**, aby przeglądać powiązane notatki
Markdown. Widok działa dla współdzielonych plików projektu, workspace sandboxa
i zatwierdzonego folderu Desktop. Każda lokalizacja ma osobny graf; lokalne
notatki nie są wysyłane na serwer.

Graf otwiera się na pełnym ekranie z kolorowymi punktami, cienkimi połączeniami
i etykietami widocznymi po przybliżeniu lub wybraniu notatki. Strzałki kierunku
i stałe etykiety można włączyć. Wyszukiwanie, pliki, szczegóły i zoom są w pływających
panelach. Grupy kolorują notatki domyślnie według folderu, opcjonalnie pierwszego tagu.
Możesz ukrywać grupy, filtrować folder wraz z podfolderami i resetować filtry.

Przeglądarka plików używa wspólnego drzewa folderów i ikon. Węzłami są tylko
zindeksowane notatki Markdown; pozostałe pliki otwierają się we wspólnym podglądzie.
Przeciąganie punktów zmienia tylko widok, bez zapisywania plików lub linków.
Przycisk rozwijania lub Escape przywraca widok osadzony, a strzałka wstecz wraca do plików.

Łącz notatki przez `[[notes/topic|etykieta]]`, linki Markdown w treści, np.
`[Temat](topic.md)`, lub relacje we frontmatter:

```yaml
---
title: Pamięć agenta
aliases: [Memory]
tags: [agents, research]
related: ["[[notes/retrieval]]"]
sources: [sources/report.md]
---
```

`links`, `related` i `sources` przyjmują tekst lub listę tekstów. Zewnętrzne URL-e
pozostają cytowaniami. Wikilinki wskazują dokładną ścieżkę lub unikalną nazwę pliku,
tytuł bądź alias; niejednoznaczne nazwy pozostają nierozwiązane. Linki Markdown są
względne wobec notatki. Przykłady w kodzie i komentarze HTML są pomijane.

Wyszukuj po tytule, ścieżce, aliasach lub tagach. Wybierz węzeł, aby zobaczyć jego
linki, linki przychodzące i nierozwiązane odwołania; **Open note** otwiera notatkę.
Współdzielone pliki projektu zachowują kontrolkę **Edit file** i dotychczasowe
uprawnienia. Przybliżaj przyciskami, przesuwaj graf przez przeciąganie pustego tła;
lista notatek działa również z klawiatury.

Widok odczytuje pliki co 30 sekund, gdy jest otwarty, po powrocie do okna lub
wybraniu **Refresh**. Agenci aktualizują notatki i linki, bez generowania HTML.
Apps odświeżają już bindings do Tables i logów workflows, ale nie mają bindingu
plików workspace; ten graf czyta notatki bezpośrednio. Odświeżenie grafu nie
uruchamia agenta w celu weryfikacji faktów lub aktualizacji źródeł.

Skan obejmuje do 200 plików Markdown, 256 KiB na plik i łącznie 8 MiB, w granicach
listingu źródła. Limit relacji to 256 na notatkę i 2048 na cały graf; osiągnięcie
limitu także oznacza niepełny graf. Aliasy i tagi mają wspólny limit 128 wpisów
na notatkę i 4096 na cały graf. Widok wskazuje pominięte i nieczytelne pliki, niepoprawny YAML oraz
niepełny listing. Brak odwołania może oznaczać pominiętą notatkę, nie tylko zerwany
link. Odświeżanie jest okresowe; równoczesne edycje mogą trafić do różnych skanów.

## Lokalne foldery w aplikacji desktopowej { #local-folders-in-the-desktop-app }

Karta **Pliki** rozdziela **Wspólne pliki projektu** i **Ten komputer**. Folder zatwierdzony przy tworzeniu projektu otwiera się automatycznie na tej instalacji; bez powiązania najpierw widać wspólne pliki. Wybierz Ten komputer, aby podłączyć folder. **Ustawienia folderu** pozwalają go zmienić lub odłączyć; ścieżka i tryb dostępu są widoczne bez powtarzania formularza konfiguracji.

Wspólne pliki projektu to wgrane kopie dostępne dla osób z dostępem do projektu. Aby udostępnić lokalny plik, wybierz to źródło i wgraj kopię. Te miejsca nie synchronizują się: edycja lokalna nie aktualizuje wgranej kopii, a udostępnienie projektu nie daje dostępu do dysku. **Wspólne środowisko projektu** na karcie Instrukcje zmienia wyłącznie miejsce na serwerze; nie podłącza ani nie odłącza osobistego folderu.

Natywne okno potwierdza dostęp, początkowo tylko do odczytu. Powiązanie należy do bieżącego konta i organizacji na tym komputerze. Odłączenie pozostawia uprawnienia innych czatów. Podgląd obejmuje do 500 elementów, pomija generowane foldery, np. `.git` i `node_modules`, i pokazuje błędy odczytu bez cichego przełączania do chmury.

Nowe czaty projektu na desktopie dziedziczą folder i zatwierdzony tryb dostępu.
Instrukcje projektu nadal obowiązują, a narzędzia sandboxa pracują lokalnie zamiast
we wspólnym kontenerze. Ustawienie **Pracuj na** można zmienić dla pojedynczego
czatu; istniejące rozmowy zachowują swoje ustawienia. Skrót folderu przy polu
wiadomości otwiera te opcje. Niedostępny komputer lub cofnięte uprawnienie nie
przełącza wykonania do chmury. Telefony i przeglądarki nadal używają wspólnych
plików; powiązanie nie daje im zdalnego dostępu do komputera. Odpowiedzi agenta
i wyniki narzędzi zapisane w czacie projektu są widoczne dla osób mogących czytać
ten czat, więc uwzględnij jego odbiorców przed omawianiem prywatnych plików.

## Udostępnianie i uprawnienia { #sharing-and-permissions }

Projekt jest prywatny dla swojego twórcy, dopóki go nie udostępni - tym samym
oknem **Udostępnij**, którego używa agent czy skill: osobom,
[działom](departments.md) albo całej organizacji, każdemu na jakimś poziomie.

| Poziom grantu | Uprawnienie     | Na co pozwala                                                |
| ------------- | --------------- | ------------------------------------------------------------ |
| `read`        | `projects:view` | Widzieć projekt, jego pliki i instrukcje                     |
| `use`         | `projects:use`  | Czatować w nim; dodawać, edytować, przenosić i usuwać pliki  |
| `edit`        | `projects:edit` | Zmieniać instrukcje i domyślnego agenta, udostępniać, usuwać |

Role mają te uprawnienia w zwykłych zakresach: Owner i Admin sięgają każdego
projektu, Builder pracuje w udostępnionych mu projektach i je edytuje, Member
edytuje własne i pracuje w udostępnionych, a Viewer czyta to, co mu udostępniono.
Czat, którego autor straci `projects:use`, przestaje sięgać plików projektu przy
kolejnej turze.

**Czaty projektu należą do jego członków.** Kto widzi projekt, czyta każdy czat
w nim, a kto może w nim pracować (`use`), kontynuuje je: jego wiadomości niosą
jego imię i twarz, więc wątek, nad którym pracowało kilka osób, mówi, kto o co
pytał. Zmiana nazwy, archiwizacja i usunięcie czatu zostają przy osobie, która go
zaczęła. Na zakładce **Czaty** każdy wiersz mówi, czyj jest czat, którzy agenci w
nim odpowiadają, kiedy ostatnio coś się w nim działo albo kto teraz w nim pracuje,
i kto go otwierał - ostatnie twarze, a wszystkie imiona po najechaniu;
kto ma go otwartego w tej chwili, jest pierwszy, z zieloną kropką.
Czat poza projektem zaczyna jako prywatny. Jego właściciel może jawnie dodać osoby
lub agentów i przekształcić dotychczasową rozmowę we wspólny pokój bez utraty
historii.

Czatu projektu nie udostępnia się osobno, linkiem ani konkretnej osobie: czyta się
go przez projekt, więc udostępnij projekt.

## Pokoje zespołu { #team-rooms }

Na karcie **Czaty** projektu wybierz **Nowy pokój zespołu (New team room)**, aby
utworzyć pustą wspólną rozmowę. W głównej konsoli czaty projektu pokazują nagłówek
pokoju z odbiorcami projektu i obecnymi osobami, nawet gdy jesteś tam sam.
**Udostępnij (Share)** zarządza dostępem do projektu; uczestnik z prawem tylko do
odczytu może śledzić transkrypcję, ale nie może wysyłać wiadomości.

Wpisz `@` i wybierz osobę lub agenta z listy, aby wspomnieć tę osobę lub tego
agenta. Osoby otrzymują
powiadomienie; każdy wybrany agent otrzymuje własną odpowiedź w kolejce na tę samą
wiadomość napisaną przez człowieka. Podobnie brzmiące nazwy pozostają osobnymi
opcjami. Samo wpisanie nazwy bez wybrania propozycji nie wskazuje odpowiadającego.
Wiadomości i odpowiedzi wskazują nadawcę; **Odpowiedz (Reply)** dodaje cytat do
wiadomości i kontekstu agenta.

Otwórz listę uczestników, aby dodać uprawnionego agenta przed wspomnieniem go.
Udostępnienie projektu nadal określa, które osoby mogą czytać lub pisać; lista
uczestników pokoju nie może przyznać nikomu dostępu do projektu. Agenci domyślnie
odpowiadają tylko na wzmianki. Zarządzający pokojem może włączyć automatyczne
odpowiedzi wybranym agentom; nieoznaczona wiadomość może wtedy trafić do maksymalnie
czterech takich agentów. Wzmianki tylko do osób nie przywołują tych agentów.

Pasek boczny czatu umożliwia też rozmowy poza projektem. Utwórz prywatny pokój albo
pokój widoczny dla organizacji lub dołącz do istniejącego publicznego pokoju przed
wysłaniem wiadomości. Dodanie współpracownika do istniejącego czatu z agentem
przekształca go na miejscu. Potwierdzenie wyjaśnia, że nowy uczestnik może czytać
zapisaną historię. Prywatną pracę już w toku trzeba zakończyć lub anulować przed
taką zmianą.

Żądania odpowiedzi agenta trafiają do jednej trwałej kolejki pokoju. Run czekający
na zatwierdzenie lub odpowiedź zachowuje swoje miejsce do rozstrzygnięcia.
Możesz anulować własne żądanie, gdy czeka w kolejce. Bieżące uprawnienia
zlecającego do projektu i agenta są sprawdzane ponownie przy rozpoczęciu lub
wznowieniu pracy. Kolejne pytanie widzi wcześniejsze wiadomości i ukończone
odpowiedzi na poprzednie żądania, bez pytań wysłanych po nim.

Kolejka pokazuje zapisany stan żądania i odświeża się po ponownym połączeniu.
Jeśli wynik wysłania jest niepewny, ponów oczekującą wiadomość, aby użyć jej
dotychczasowej tożsamości. Przerwane żądanie agenta nie uruchamia się ponownie
automatycznie; sprawdź zapisany run przed nowym żądaniem.

Do wiadomości pokoju możesz bezpośrednio dołączyć do dziesięciu plików, z podpisem
lub bez. Obowiązują dotychczasowe limity typów i rozmiaru uploadu. Te same
załączniki trafiają do każdego wybranego agenta odpowiadającego, a ponowienie
wysłania nie dołącza ich drugi raz. Karta projektu **Pliki (Files)** pozostaje
wspólnym workspace'em dla materiałów referencyjnych używanych dłużej.
Odpowiadają opublikowani agenci zgodni z chmurą; agenci desktopowi i agenci
korzystający z osobistego sandboxa nadal wymagają właściwego dla urządzenia
przepływu czatu.

Użyj kontrolki reakcji przy zapisanej wiadomości człowieka lub agenta, aby dodać
albo usunąć swoją emoji. Liczniki sumują reakcje wszystkich osób, a twoje własne
wybory pozostają oznaczone. Jedna wiadomość może mieć do dwudziestu różnych emoji.

### Wątki boczne { #side-threads }

Wybierz **Odpowiedz w wątku (Reply in thread)** przy zapisanej wiadomości pokoju, aby otworzyć jej
wątek. Panel pokazuje pierwotną wiadomość nad odpowiedziami; liczba odpowiedzi
w pokoju pozwala wrócić do dyskusji. Adres zawiera pokój i wątek, więc link lub
odświeżenie otwiera tę samą dyskusję. Na wąskim ekranie wątek zajmuje dostępną
szerokość. **Odpowiedz (Reply)** nadal dodaje cytat w bieżącej dyskusji.

Wątek ma tych samych odbiorców i te same uprawnienia do pisania co jego pokój.
Otwarcie go nie prosi agenta o odpowiedź. Wybierz agenta przez `@`, aby poprosić o
odpowiedź, albo wspomnij tylko osoby, by z nimi rozmawiać. Odpowiedź należy do tego
wątku, także gdy run jest wznawiany po pytaniu lub zatwierdzeniu. Główny pokój i
jego wątki korzystają z jednej kolejki żądań agentów; oczekujący run zatrzymuje
późniejsze żądania w kolejce.

Bez wybranego zakresu kontekstu agent daje pierwszeństwo pierwotnej wiadomości i odpowiedziom
wątku. Pozostałe miejsce w historii może zawierać wiadomości głównego pokoju
sprzed pierwotnej wiadomości. Odpowiedzi z innych wątków i późniejsze wiadomości
głównego pokoju są wykluczone. Nadal obowiązują instrukcje projektu, wspólne
pliki i wiedza projektu. Cytaty w wątku odnoszą się do jego pierwotnej wiadomości
lub jednej z odpowiedzi.

Plany i oczekujące kroki należą do danego runa. Wznowienie je zachowuje;
osobne żądanie odpowiedzi agenta w wątku zaczyna nowy plan.

Osoba rozpoczynająca wątek i osoby, które na niego odpowiadają, domyślnie go
obserwują. Jawne obserwowanie lub rezygnacja z niego sterują powiadomieniami o
odpowiedziach; bezpośrednia wzmianka `@` nadal cię powiadomi. Przeczytanie głównego
pokoju nie usuwa nieprzeczytanych odpowiedzi wątku. Pokój pokazuje liczbę
nieprzeczytanych odpowiedzi przy podsumowaniu wątku, a jego otwarcie oznacza jako
przeczytane tylko te odpowiedzi, które faktycznie zobaczysz.

Osoba rozpoczynająca wątek lub zarządzający pokojem może go zamknąć albo
zarchiwizować. Odpowiedź ponownie otwiera zamknięty wątek. Zarchiwizowany wątek
jest tylko do odczytu; cofnięcie archiwizacji przywraca jego poprzedni stan:
otwarty lub zamknięty. Te działania zachowują pierwotne wiadomości i odpowiedzi.

Każda dyskusja zachowuje własny szkic i oczekującą ponowną próbę wysłania, gdy
przechodzisz między wątkami w bieżącej sesji. Wróć do pierwotnej dyskusji, aby
ponowić niepewne wysłanie z tą samą tożsamością; wybranie innego wątku nie
przekierowuje oczekującej wiadomości. Zmiana konta lub organizacji usuwa te szkice.

Po odłączeniu czatu od projektu istniejące wątki pozostają widoczne dla osób,
które nadal mają dostęp do tego czatu. Odpowiedzi w wątkach są tylko do odczytu,
chyba że właściciel jawnie przekształci czat w samodzielny pokój. Samo wcześniejsze
członkostwo w projekcie nie daje już dostępu.

### Wybrany kontekst wątku { #selected-thread-context }

Użyj **Wybierz kontekst (Select context)**, aby wskazać pierwszą i ostatnią zapisaną
wiadomość nowego wątku. Przed utworzeniem możesz wykluczyć pojedyncze wiadomości.
Wybór obejmuje od 1 do 500 wiadomości w kolejności transkrypcji; nowy wątek otwiera
się z własnym tytułem i pokazuje wybrany kontekst osobno od odpowiedzi. Utworzenie
wątku nie wywołuje odpowiedzi agenta.

**Przenieś do wątku (Move into thread)** przenosi wybrane wiadomości z głównej osi
czasu i zostawia tytuł z liczbą, który prowadzi do wątku. **Wróć do pokoju (Return to
room)** przywraca tylko przeniesione wiadomości; odpowiedzi zostają w wątku.
Tożsamości, autorzy, załączniki, reakcje i pierwotna kolejność są zachowane. Przeniesiony
wybór możesz edytować bezpośrednio: stary zakres wraca, a nowy jest przenoszony razem.

Wybierz inny pokój źródłowy, aby odwołać się do jego wiadomości bez przenoszenia.
Źródło musi należeć do tej samej organizacji i być czytelne dla każdego obecnego
czytelnika pokoju docelowego. Źródła prywatne i projektowe wymagają też zgodnego
członkostwa agentów. Pokój docelowy z publicznym linkiem udostępniania nie może
importować kontekstu. Dostęp jest sprawdzany ponownie przy odczycie kontekstu i
przed jego użyciem przez agenta.

Czytelnicy muszą zachować dostęp do każdego powiązanego źródła, aby otworzyć pokój
docelowy, jego pliki lub wyniki wyszukiwania. Udostępnienie pokoju docelowego nie
udostępnia źródła. Publiczne linki i forki z zaimportowanym kontekstem są niedostępne.
Gdy kontekst został użyty w żądaniu lub odpowiedzi, jego źródło i znacznik wątku
pozostają powiązane, nawet jeśli odpowiedzi zostaną usunięte; nadal możesz edytować
wybór w obrębie tego źródła. Odpowiedzi pojawiają się po zapisaniu i ponownym
sprawdzeniu dostępu, a nie jako strumień tekstu pochodzącego ze źródła.

Inicjator wątku lub menedżer pokoju może zmienić jego kontekst, gdy oba pokoje są
bezczynne. Najpierw zakończ pracę w kolejce, uruchomioną lub wstrzymaną. Zarchiwizowane
wątki są tylko do odczytu, a wyboru zawierającego inny wątek nie można przenieść.
Dołączony kontekst nie zwiększa liczników odpowiedzi ani nieprzeczytanych. Wykluczenia
nie trafiają do wybranej historii agenta, także do automatycznych cytatów.

## Usuwanie projektu { #deleting-a-project }

Usunięcie projektu usuwa jego kontener i wszystkie pliki. Jego czaty zostają jako
zwykłe czaty, poza jakimkolwiek projektem - poza czatem, którego autor usunął konto:
sięgał do niego już tylko projekt, więc znika razem z nim.

## Gdzie widać projekty { #where-projects-show-up }

- **Projekty** w pasku bocznym pokazują trzy ostatnio używanych, nad linkiem do
  wszystkich. Ikona nowej odpowiedzi oznacza projekt z nieprzeczytaną odpowiedzią w chacie.
- Lista czatów pokazuje każdy czat w projektach, które widzisz - twoje i twoich
  współpracowników - pod nazwą projektu, nad czatami spoza projektów.
- Karta **Projekty** na dashboardzie pokazuje ich rząd, z czatami w każdym.
- `GET /api/v1/projects` i trasy pod nim należą do publicznego API, więc skrypt
  może utworzyć projekt i wypełnić go plikami. Zobacz [API](api.md).


## Pilnuj postępów projektu { #keep-a-project-on-track }

Na stronie projektu wybierz **Pilnuj projektu**. Wskaż opublikowanego agenta, którego możesz edytować, przejrzyj zasoby i połączone konta, nazwij nowego agenta i tabelę zadań, wybierz częstotliwość i jawnie zatwierdź publikację oraz uruchomienie. Powstają prywatna kopia agenta, tabela zadań (prywatna, chyba że wybierzesz widoczność dla organizacji), zapisane widoki wszystkich zadań, tablicy, otwartych zadań i blokad oraz rutyna przypięta do nowej wersji. Oryginalny agent pozostaje bez zmian.

Rutyna działa jako Ty wewnątrz projektu i raportuje w jego rozmowie. Czyta stan zadań, sprawdza postępy w zatwierdzonych źródłach, aktualizuje kolejne kroki i wskazuje blokady oraz terminy. Wysłanie zewnętrznego przypomnienia nadal wymaga zwykłej autoryzacji. Nowe źródła, ponowna zgoda konta lub wymiana przestrzeni projektu wymagają ponownego przeglądu źródeł. Utrata dostępu do projektu zatrzymuje kolejne narzędzia; oczekujące powiadomienia ponownie sprawdzają bieżący dostęp odbiorcy. Identyczna ponowiona konfiguracja wykorzystuje istniejące zasoby. Częstotliwość i źródła zmienisz w Rutynach, a tabelę otworzysz ze strony projektu.

Rozmowę harmonogramową w projekcie, która nie ma właściciela, może zmienić, zarchiwizować lub usunąć osoba z prawem edycji tego projektu. Rozmowami rozpoczętymi przez inną osobę nadal zarządza ich właściciel.


Usunięcie projektu usuwa również jego wpisy pamięci i pochodne udostępnione kopie oraz próbuje wyrejestrować webhooki u dostawców przed kaskadowym usunięciem rutyn. Niedostępność dostawcy jest logowana i nie blokuje usunięcia.


## Powiązane zasoby { #linked-resources }

Karta **Zasoby** grupuje istniejących agentów, workflowy, aplikacje i tabele bez ich kopiowania. Wybierz **Dodaj istniejące zasoby**, zaznacz jeden lub kilka elementów i opcjonalnie oznacz powiązany workflow jako główny. Zasób może należeć do kilku projektów. Listę można przeszukiwać po nazwie lub opisie; katalogi agentów i workflowów mają też filtr projektu. Nazwy projektów są dostępne w wyszukiwaniu palety poleceń.

Powiązania nie nadają dostępu: każdy zasób zachowuje własne uprawnienia, wersje i harmonogramy. Usunięcie powiązania lub projektu pozostawia oryginalny zasób. Usunięcie zasobu usuwa jego powiązania. Oznaczenie głównego workflow nie uruchamia go.

Projekt domyślnie otwiera kartę **Chaty**; link wskazujący konkretną kartę nadal ją otwiera. Plus obok ostatniego projektu w panelu bocznym chatu rozpoczyna w nim nowy chat. Projekty tylko do odczytu nie oferują tej akcji.
