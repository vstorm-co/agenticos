---
source_sha: "1488eff9ea76"
---

# Konsola { #the-console }

Osobisty dashboard odczytuje onboarding i Briefing razem przed pokazaniem pierwszego wiersza. Jedno zarezerwowane miejsce ładowania zapobiega zmianom układu placeholderów; pozostałe widżety ładują się niezależnie. Błędy odczytu zachowują możliwość ponowienia. Rozszerzanie obszaru roboczego jest dostępne na telefonach; przejście na desktop przywraca nawigację i zachowuje niezapisane pola.

Ustawienia kontekstu pokazują zwarte wiersze plików z wyborem sposobu użycia przez agenta. Długie opisy nie rozciągają sąsiednich pozycji, a wyłącznie wstrzykiwany kontekst ma neutralną informację. Dostępność pokazuje logo platformy obok nazwy bota. Udostępnianie aplikacji zaczyna się od adresu i osób z dostępem; wygaśnięcie, przypięcie wersji, osadzanie i hasło są zwinięte w Ustawieniach linku. Aktywne ograniczenia pozostają widoczne jako etykiety, a zwinięcie opcji zachowuje edycję.

Na telefonach rejestracja kanału używa zwartego wyboru platformy. Anulowanie nowego kanału, nowego klucza w sejfie lub rotacji klucza czyści wpisane poświadczenia. Formularze kanałów i sejfu blokują edycję oraz zamykanie podczas zapisu; odmowa zachowuje wartości do poprawienia i ponowienia. Edycja kanału i rotacja klucza utrzymują przyciski w widocznej stopce także na niskim ekranie.

Na telefonach nowy plik kontekstu pokazuje edytor treści przed opcjonalnymi szczegółami. Szczegóły pokazują rzeczywisty dostęp także po zwinięciu; rozwiń je, aby zmienić opis lub dostęp. Błąd opisu automatycznie rozwija tę sekcję, aby można go było poprawić.

Formularze nowego projektu, pliku kontekstu i datasetu pytają przed porzuceniem danych. Zostań zachowuje wersję roboczą, a Odrzuć ją zeruje. Podczas tworzenia pola, Anuluj, Zamknij i Escape są zablokowane do zakończenia zapisu. Odmowa przywraca edycję i zachowuje wartości. Źródło pliku kontekstu jest w tym czasie tylko do odczytu.

Przy wielu upuszczonych plikach kontekstu zamknięcie oferuje tylko Zostań lub Odrzuć; użyj Utwórz, aby przetwarzać je po kolei. Ustawienia datasetu i formularze przypadków także blokują pola i zamykanie podczas zapisu, w tym przełącznik formularz/JSON. Zapis pozostaje dostępny w krótkich oknach telefonu.

Rozpoczęcie logowania MCP zachowuje otwarty formularz do uzyskania adresu zgody. Odmowa zachowuje wpisane dane do poprawienia i ponowienia próby.

Edycja własnych komend slash pyta przed porzuceniem formularza. Zapis blokuje pola i zamykanie do zakończenia żądania; odmowa zachowuje dane. Na telefonach akcje komendy mają osobny wiersz i pola dotykowe. Przełącznik w trakcie zapisu blokuje sprzeczne akcje, a usuwanie wymaga potwierdzenia. Formularze połączeń MCP również blokują pola i zamykanie podczas zapisu.

Konsola to aplikacja webowa, przez którą konfiguruje się wszystko inne opisane na
tej stronie. Ta strona jest mapą: do czego służy każdy obszar i która strona
wyjaśnia go porządnie.

Gdy edytujesz ustawienia projektu, nazwę organizacji, limit wydatków, domyślne ustawienia głosu, okresy retencji danych, skill lub plik context, wyjście wymaga decyzji: zapisać, odrzucić czy zostać. Dotyczy to także przejścia do innego pliku zasobów skill. Odmowa zapisu pozostawia draft otwarty; **Save file** usuwa go dopiero po potwierdzeniu zapisu przez serwer. Tekst dopisany w trakcie zapisywania tego pliku pozostaje niezapisany.

Na telefonie dokumenty bazy wiedzy i członkowie organizacji mają podpisane wiersze z widocznymi akcjami. Usunięcie członka wymaga potwierdzenia, a odmowa zachowuje otwarte okno. Formularze tworzenia KB, parsowania i dostawcy embeddingów blokują pola i pozostają otwarte podczas zapisu; po odmowie znów można je edytować i zamknąć. Nieudane pobranie dokumentu pokazuje błąd i pozwala ponowić próbę.

Zmiana pytania lub zakresu wyszukiwania wiedzy usuwa wcześniejsze wyniki i anuluje oczekujące zapytanie. Spóźniona odpowiedź nie może zastąpić wyników nowszego wyszukiwania.

Publiczny czat pozwala pisać podczas łączenia, ale włącza Send dopiero po otwarciu bieżącego WebSocket. Nowa rozmowa czeka na własne połączenie; przedwczesne kliknięcie nie gubi pierwszego pytania.

Jeśli szukasz jednego ekranu, najszybszą drogą jest **"?"** w nagłówku strony —
odtwarza on przewodnik po tej stronie, a strona, w której nagłówku nie ma "?",
nie ma przewodnika do odtworzenia. Czat nie ma nagłówka: jego wskazówki są w
ustawieniach czatu, pod suwakami obok mikrofonu.

Listy zasobów, w tym Inbox i Routines, wypełniają pozostałą wysokość strony również wtedy, gdy są puste. Szablony Routines pozostają w formularzu tworzenia zamiast osobnego panelu pomysłów.

Czat używa większych portretów agentów bez obwódek. Przełącznik Files pozostaje w polu wiadomości podczas otwierania i zamykania panelu; animacja respektuje ograniczenie ruchu. Ustawienia czatu pokazują najpierw bieżący model. Rozwiń **Zmień model**, aby edytować uzupełnionego dostawcę i model; wybór zaczyna działać po zatwierdzeniu. Karty załączników znajdują się nad polem wiadomości bez dodatkowego panelu z cieniem.

Wprowadzenia do stron i objaśnienia ustawień są dostępne pod ikoną informacji obok nagłówka. Bieżące podsumowania i ostrzeżenia o nieodwracalnych działaniach pozostają widoczne.

W Agentach, Skills, Context i historii uruchomień przycisk **Filtry** rozwija dodatkowe opcje niezależnie od rozmiaru ekranu i pokazuje liczbę aktywnych filtrów.

Karty agentów pokazują status, dostęp i datę edycji bez rozwijania. Karty Skills i Context zachowują podgląd dokumentu, opis, **Used by** z avatarami i **Dodaj do agenta**. Kategoria i odbiorcy są w zwartym wierszu obok akcji. Nie ma rozwijanych Szczegółów. Aby usunąć skill lub plik contextu, otwórz edytor i menu z trzema kropkami obok **Share**; usunięcie nadal wymaga potwierdzenia i jest dostępne tylko dla edytora.

Nazwy, nawigacja i wartości formularzy używają wyraźnego tekstu pierwszego planu;
metadane pozostają drugorzędne. Główne akcje mają kontrastujące neutralne
wypełnienie. Glass zachowuje natywny materiał, ale treść, karty i menu mają bardziej
kryjące powierzchnie do czytania.

Zakładki organizacji, kreatora agentów i projektów mają odpowiednie ikony. Wiersze
budżetu pokazują avatary agentów.

Generowane portrety korzystają z ograniczonego zestawu kształtów Blobatar 2.7 i jaśniejszych odcieni; animują się po najechaniu, a pracujący agenci zachowują animację myślenia. Wgrane zdjęcia pozostają bez zmian. Nowe zdjęcia agentów startowych należą do tej samej rodziny; istniejące zapisane obrazy nie są automatycznie zastępowane.

Ustawienia czatu pokazują Browser i Work on przed Permissions. Powiadomienia rozmowy
i połączenia kont pozostają pod kontrolkami uprawnień.

Ustawienia chatu mają stały nagłówek i przycisk zamknięcia nad przewijaną zawartością. Ikony informacji objaśniają model, Browser, Work on i tryby uprawnień; opis wybranego trybu pozostaje widoczny. W **Knowledge bases → Integrations** integracje i usługi lokalne mają zwarte panele dopasowane do zawartości, z objaśnieniami pod ikonami informacji.

Agenci rozmowy są uporządkowani według ostatniej wiadomości lub uruchomienia głównego agenta, od najnowszego. Zwinięty pasek chatu zachowuje pełny rozmiar avatarów, nakłada maksymalnie trzy i ukrywa starszych uczestników; pełna lista pozostaje dostępna w podpowiedzi.

Gdy **Approve everything** jest niedostępne, ustawienia chatu rozróżniają brak uprawnienia do zatwierdzania i politykę organizacji wyłączającą stałą zgodę. Osoba z uprawnieniem do zatwierdzania otrzymuje odnośnik do **Budżetu i zatwierdzeń**, gdzie może jawnie zmienić tę politykę. Chat nie zmienia polityki organizacji automatycznie.

Na telefonie modale zachowują 12 px marginesu z każdej strony. Zwarte nagłówki mieszczą tytuł i akcje w jednym wierszu, gdy jest na to miejsce. Opis pliku Context rozwija się z paska edytora.

Na telefonie główne akcje strony pozostają widoczne, a drugorzędne polecenia rozwija przycisk **Więcej akcji strony**. Filtry Inbox i format tabeli wybiera się selectem. Ustawienia z wieloma sekcjami mają menu wyboru sekcji; klienta MCP wybiera się z listy. Plik projektu lub workspace otwiera czytnik na pełnym ekranie, a strzałka wstecz wraca do folderów. Edytor kroku workflow pokazuje jeden wybrany panel: ustawienia, wejście albo wynik. Przełączanie zachowuje edycję; desktop nadal pokazuje panele obok siebie.

Pola Markdown i edytory plików również mają przycisk powiększania, który zachowuje bieżący szkic. Opis i kategorię skilla można rozwinąć nad edytorem. Pole wiadomości na czacie zajmuje mniej miejsca i ogranicza wysokość długiego szkicu do dostępnej wysokości ekranu. Otwarcie nawigacji ustawia focus na panelu, a Tab nadal przechodzi do jego kontrolek. Na telefonie canvas workflow ma pływający przycisk pełnego ekranu, otwiera się z całym przepływem w widoku i startuje z ukrytą minimapą.

Każde jawne kliknięcie **New chat** ponownie ustawia fokus w edytorze, także przy pustym szkicu; nadanie rozmowie identyfikatora podczas pisania nie żąda ponownego fokusu.

Na telefonie edytory skilli i contextu chowają opis, kategorię i zarządzanie plikami podczas pisania. Jeden przycisk przełącza źródło i podgląd. Apps ma pływające przyciski powrotu i opcji; opcje rozwijają tytuł, wersję, motyw i udostępnianie.

Nagłówki korzystają z odstępów otaczającego układu bez ich podwajania. Karty, wiersze panelu bocznego, zakładki i puste stany mają mniejsze odstępy na komputerze, a kontrolki zachowują większe obszary dotykowe.

Przyciski drugorzędne i filtry mają wspólne, wyraźniejsze wypełnienie, kontrastowe etykiety oraz czytelne stany najechania, naciśnięcia i otwarcia. Wybór modelu w chacie korzysta z tego samego stylu przycisku.

Ustawienia osobiste zachowują poziome zakładki u góry, w tym opcje desktopowe dostępne w aplikacji. Panele pokazują opisy bezpośrednio, a formularze mają wysokość dopasowaną do zawartości. Konto zawiera zmianę hasła i aktywne sesje; przycisk zmiany hasła jest pod polami.

Pola profilu mieszczą się w jednym wierszu, gdy jest miejsce; **Zapisz zmiany** jest dostępne dopiero po edycji. Karta możliwości ma jeden obszar otwierający ustawienia i osobny przełącznik włączenia. W panelu ustawień przykłady są pod ikoną informacji, zamiast powtarzanej ilustracji z galerii.

Okna kategorii szablonów dopasowują się do zawartości; wybranie branży agenta lub umiejętności otwiera większą bibliotekę. Na telefonie wybór wyglądu ma postać zwartych wierszy z miniaturami.

Instrukcje agentów i projektów mają jeden zwarty pasek z tytułem, pomocą, przełączaniem źródła i podglądu oraz rozwijaniem. Rozwinięty Markdown zachowuje wybrany tryb źródła lub podglądu. Nieużywane zmienne promptu są początkowo zwinięte; istniejące własne zmienne lub niestandardowa strefa czasu pozostawiają panel otwarty. Rozwinięte edytory tekstu i plików zachowują równe marginesy na telefonie. Pola tekstowe na telefonie używają większej czcionki bez powiększania pól na komputerze.

Na telefonie fokus w polu wiadomości przełącza czat w zwarty wiersz pisania z załącznikami i wysyłaniem. Wybór agenta oraz głos pozostają dostępne pod **+**. Powitanie i sugestie połączeń chowają się na czas pisania, a menu uzupełniania mieści się w dostępnej wysokości. Przejście z tekstu na Wyślij zachowuje stabilny układ.

Wejście do głównego czatu ustawia fokus w polu wiadomości, gdy tylko można w nim pisać, także jeśli podczas łączenia fokus pozostał na przycisku nawigacji. Kontrolka świadomie użyta podczas łączenia zachowuje fokus.

Na telefonach akcje pod wiadomościami użytkownika i agenta są początkowo ukryte. Przycisk **Więcej** obok nadawcy pokazuje lub ukrywa kopiowanie, odpowiedzi, oceny i pozostałe dostępne akcje. Na komputerze przyciski nadal pojawiają się po najechaniu kursorem.

Importy CSS, obrazy i fonty w podglądzie są rozwiązywane względem arkusza przez ten sam autoryzowany dostęp do plików. Podgląd dopuszcza cztery zagnieżdżone poziomy, 64 zasoby, 8 MiB wejściowych zasobów i 16 MiB rozwiniętego wyniku. Skróty plików zachowują konwersację lub folder z chwili wykonania tury, zapisane z jej osią czasu. Zmiana Work on nie przekierowuje skrótów. Starsze tury bez zapisanego źródła nie otrzymują zgadywanych linków. Otwarcie lokalnego pliku nadal wymaga aktualnej zgody na folder.

Metadane linków do plików zapisują dla lokalnych tur tylko niejawny identyfikator źródła. Powiązanie z folderem pozostaje na komputerze inicjującym, w zakresie konta i organizacji; inni uczestnicy i komputery nie mogą rozwiązać tych linków. Starsze źródła zawierające lokalną ścieżkę są pomijane przy odczycie zapisanych tur.

**Visual map** w builderze agenta dopasowuje całą konfigurację po otwarciu i zmianie rozmiaru obszaru. **Reset view** ponownie dopasowuje mapę po przesunięciu lub przybliżeniu. Duże grupy pokazują sześć elementów i liczbę pozostałych; wybierz grupę, aby otworzyć pełną, przewijaną listę. Minimapa workflow pokazuje cały graf i pozwala przejść do innego miejsca bez zmiany przybliżenia.

Panel testowania w builderze można rozwinąć na cały obszar bez resetowania rozmowy ani niewysłanego tekstu. Porównanie dwóch wersji automatycznie otwiera ten widok; przycisk pełnego ekranu lub Escape przywraca builder. Wybór wersji ma osobny wiersz, dzięki czemu kontrolki testu mieszczą się w wąskim panelu. Na telefonie przełączaj porównywane chaty przyciskami wersji; obie rozmowy nadal działają i zachowują szkice. Wspólny prompt nadal trafia do obu naraz.

Nawigacja zachowuje wspólne layouty przy przechodzeniu między sekcjami i stosuje krótkie wygaszenie zamiast resetowania ramki. Ograniczony ruch wyłącza animację. Karty dashboardu czekają na zapisany układ, strony zależne od uprawnień czekają na wynik ich odczytu, a lista użytkowników administracji zaczyna od stanu ładowania zamiast chwilowo twierdzić, że jest pusta. Filtry grup i autorów Apps rezerwują miejsce podczas ładowania. Oznaczenia źródeł w Inbox czekają na metadane katalogu; linki do roboczej rozmowy otwierają tę samą trasę chatu co sidebar.

Na telefonach wysłane wiadomości zatrzymują się poniżej pływających przycisków czatu, dzięki czemu avatar użytkownika pozostaje widoczny. Początek rozmowy i miejsce rezerwowane na odpowiedź uwzględniają ten sam odstęp pod przyciskami; desktop i osadzone czaty zachowują mniejszy odstęp.

Domyślni agenci kończą jednorazowe zadanie bez przedłużania odpowiedzi pytaniem o opcjonalną automatyzację. Pytania służą decyzjom potrzebnym do bieżącego zadania albo automatyzacji, o którą użytkownik prosi lub którą akceptuje. Opcjonalne karty konfiguracji pozostają propozycjami, które nie blokują zakończenia.

Kompaktowy przycisk źródeł pod odpowiedzią otwiera Sources obok rozmowy, a na telefonie panel na całą szerokość. Files i Sources dzielą boczny obszar: otwarcie jednego zastępuje drugi. Źródła internetowe używają favicon witryny pobieranej bez nagłówka Referer lub znanego logo usługi; globus pozostaje, gdy ikona jest niedostępna. Źródła z bazy wiedzy zachowują ikony plików i podgląd oryginalnego dokumentu.

Linki internetowe w odpowiedzi korzystają z tych samych favicon niezależnie od połączeń MCP. Ikony nieznanych stron przechodzą przez proxy konsoli i stały serwis ikon DuckDuckGo. Serwis otrzymuje tylko nazwę hosta, bez cookies i adresu IP czytelnika, ścieżki ani parametrów URL. Proxy odrzuca przekierowania, obrazy inne niż rastrowe i ikony ponad 64 KiB; limit czasu wynosi trzy sekundy. Brak lub niedostępność ikony zastępuje globus. Widoki transkrypcji z wyłączonym ładowaniem obrazów nie pobierają też ikon nieznanych stron.

Nieudany run pokazuje błąd oddzielnie od odpowiedzi agenta, poza zwijanymi narzędziami, także po odświeżeniu rozmowy. Filtr treści dostawcy ma osobne wyjaśnienie; surowe odpowiedzi dostawcy i nieznane historyczne komunikaty błędów nie są kopiowane do udostępnianych transkrypcji. Częściowe wyniki pozostają dostępne, a nieudana praca nie jest oznaczana jako ukończona.

## Dashboard { #the-dashboard }

Strona startowa to **układalna siatka widgetów** i jest odpowiedzią na pytanie
"co się dzieje" bez otwierania pięciu stron.

Istnieje pięćdziesiąt siedem kart. Nie zobaczysz wszystkich: **karta jest
bramkowana uprawnieniem, którego wymagają jej dane**, więc widget, którego nie
możesz odczytać, nigdy się nie montuje, a jego zapytania nigdy nie wychodzą —
poza twoimi własnymi powiadomieniami, niżej, które wymagają tylko tego, żebyś
był zalogowany. Pusty pas znika razem ze swoim nagłówkiem, zamiast stać tam
pusty.

Przełącznik na górze mówi, czyj to dashboard, i oferuje tylko widoki, które
możesz otworzyć. Każdy zaczyna od widoku **Ja**:

| Widok | Odpowiada na |
| --- | --- |
| **Ja** | Powitanie, Twój okres i wszystko, co na Ciebie czeka, w dwóch zdaniach - wywołania, odpowiedzi do przeglądu, oblane suity, sugestie asystenta; Twoje runy, ile się skończyło, co na Ciebie czeka (liczone tak samo) i ile to kosztowało; potem wywołania czekające na Ciebie, Twoje rozmowy, agenci wymagający uwagi, poprawki czekające na Ciebie, Twoi agenci, co Ci udostępniono, Twoje [datasety](datasets.md) z tym, z czym porównują odpowiedź ich przypadki, ostatnie runy i suity ewaluacji, sugestie asystenta według agenta, skilla i pliku oraz luki w wiedzy |
| **Ja** | Powitanie i Twój okres w jednym zdaniu; Twoje runy, ile się skończyło, co na Ciebie czeka i ile to kosztowało; potem wywołania czekające na Ciebie, Twoje rozmowy, Twoi agenci i co Ci udostępniono |
| **Organizacja** | Układalna strona opisana niżej |
| **Grupa** | Członkowie jednej [grupy](departments.md) - ich runy, wydatki, modele, kiedy pracują i kto korzysta najwięcej. Grupę wybierasz obok przełącznika. Grupa, której członkowie nic nie uruchomili w okresie, mówi to raz, z przejściem do grupy, zamiast strony pustych kart |
| **Wdrożenie** | Tylko dla [admina deploymentu](permissions.md) — sumy platformy, kondycja, najbardziej obciążeni najemcy, oceny |

Na widoku **Ja** karta **Agenci wymagający uwagi** wymienia agentów, których
widzisz, z odpowiedziami ocenionymi w dół, nieudanymi runami albo oblaną suitą
ewaluacji w tym okresie - same liczby, nigdy treść - z przyciskiem **Ulepsz**
przy tych, które możesz edytować. Galeria agentów oznacza tych samych agentów z
ostatnich trzydziestu dni znaczkiem **Wymaga uwagi**, który po najechaniu mówi
dlaczego. Odpowiedzi i runy liczą się tylko dla wersji, którą agent serwuje
teraz w domyślnym środowisku: opublikowanie poprawki czyści sygnał, dopóki nowa
wersja nie zbierze własnych. Oba wymagają `runs:view`.

Pod nią karta **Poprawki czekające na Ciebie** wymienia sesje [Ulepsz](authoring.md#the-improve-wizard)
zatrzymane na Twój następny krok albo decyzję, każdą otwierając na jej postoju, oraz
[sprawdzenia zmian skilli](skills.md#when-an-agent-got-worse), o których możesz
zdecydować, a które trwają albo czekają na decyzję. Po nich są zmiany skilli
zaproponowane przez agentów, a potem przypięci agenci i forki, które main
[wyprzedził](skills.md#which-version-an-agent-reads). Fork dogania się stamtąd,
a przypiętego agenta przenosi się na stronie jego skilla.

Widok organizacji pokazuje karty, które odpowiadają danymi, pogrupowane w pasy.
Reszta - integracje, kanały, rutyny, synchronizacja wiedzy, działy, członkowie,
sandboxy - czeka w katalogu, jedno kliknięcie dalej pod **Customize**:

| Pas | Odpowiada na |
| --- | --- |
| _(bez tytułu, na górze)_ | Podsumowanie, runy w czasie i to, jak się skończyły |
| **Needs attention** | Co czeka: [zatwierdzenia](governance.md#approvals), ostatnie błędy, zapas w budżecie, twoje najnowsze [powiadomienia](#the-bell) |
| **Usage & cost** | Których agentów się używa, wydatki, [minuty rozmów](#voice-calls), kiedy dzieje się praca, skąd przychodzą runy, miks modeli, opóźnienia, jakość odpowiedzi, kto z tego korzysta |

Karta **Wyniki zatwierdzeń (Approval outcomes)** czeka w katalogu, dla każdego, kto może
oglądać workflow. Pokazuje, jak ludzie rozstrzygali [kroki zatwierdzenia](workflows.md#running-a-workflow),
o które pytały workflow w danym okresie. Pokazuje odsetek zatwierdzonych bez zmian,
poprawki i medianę ich zmiany, czas do decyzji oraz pięć workflow z największą liczbą
próśb. Jest pusta, gdy w okresie ustawionym na dashboardzie nie padła żadna prośba.

Karta **Logi workflow (Workflow logs)** też czeka w katalogu, dla każdego, kto może
oglądać workflow. Pokazuje najnowsze wpisy, które [Quick Logi](workflows.md#the-logs-page)
workflow, które możesz oglądać, zapisały w prawdziwych runach, oraz ile wpisów doszło
w ciągu ostatnich 24 godzin, w tym błędów. Wpis prowadzi do swojego runu, a nazwa
workflow do jego strony Logs. Jest pusta, dopóki nie uruchomi się krok z Quick Logiem,
i nie zważa na okres ustawiony na dashboardzie.

Dashboard otwiera się kartą **Get started**, dopóki nie zrobisz wszystkich jej
kroków: opowiedzieć agentom o sobie, zacząć rozmowę, podłączyć usługę własnym
kontem, ustawić rutynę i zbudować agenta - to ostatnie jest pytaniem do
Architekta, który buduje go razem z tobą. Kto buduje agentów, ma po nich kroki
organizacji: opublikować agenta, dać mu bazę wiedzy, dodać działy, zaprosić kogoś
z zespołu i - jeśli może - wstawić agenta do komunikatora. Każdy krok jest
odhaczany na podstawie tego, co istnieje, gdziekolwiek go zrobiono, a nie z
kliknięcia na karcie; zamknięcie karty ukrywa ją w tej przeglądarce.

Twój własny widok pokazuje też **Odkryj AgenticOS**: po jednym kafelku na to, co
łatwo przeoczyć - własny serwer MCP tego wdrożenia dla Claude Code, Codex albo
Cursora, subagentów, sandboxy, appki, routines, komunikatory, przeglądarkę, bazy
wiedzy i skills - każdy prowadzi tam, gdzie się to włącza, i tylko te, z których
możesz skorzystać. Zamknij kafelek albo wszystkie; to też zostaje w przeglądarce.

Wykresy w czasie same dobierają krok. Odcinek od pierwszego runu w okresie do
teraz jest rysowany w najwyżej 48 punktach, najdrobniejszym krokiem, który się
mieści - minuta, pięć, piętnaście, godzina, trzy albo sześć godzin, dzień,
tydzień - więc runy z jednego popołudnia czyta się w minutach, a kwartał w
tygodniach, zamiast jednego skoku przy prawej krawędzi.

### Zmiana układu { #rearranging-it }

Przeciągnij kartę, zmień jej rozmiar, ukryj którąś. Układ jest **twój** — przypisany
do ciebie i organizacji, w której jesteś, a nie do organizacji — więc zmieniając
go, nie zmieniasz strony nikomu innemu.

Zapisz układ jako nazwany **preset**, żeby mieć więcej niż jeden i przełączać się
między nimi. Zduplikowana nazwa zostaje odrzucona, zamiast po cichu nadpisać
migawkę, którą chciałeś zachować.

!!! info "Bramka działa na końcu, na tym, co dostanie"

    Zapisany układ może zmieniać kolejność i ukrywać, ale nie może odsłaniać.
    Filtrowanie po uprawnieniach dzieje się po rozwiązaniu układu — niezależnie
    od tego, czy układ pochodzi z domyślnego, czy z twojego zapisanego.

## Rutyny i obserwacje { #routines-and-watches }

Nazwy rutyn zawijają się na telefonach. Brak wyników daje przycisk **Wyczyść wyszukiwanie**, a **Ponów** odświeża zadania i obserwacje po błędzie odczytu. Edycja harmonogramu i wyzwalacza zdarzeniowego przewija się między stałym nagłówkiem i stopką z przyciskami. Zapis blokuje pola oraz zamykanie do zakończenia żądania; odmowa zachowuje wpisane dane.

Routines ma dwie zakładki. **Zadania agentów** uruchamiają wybranego agenta według
harmonogramu lub zdarzenia, z jego narzędziami; runy widać w Activity.
**Moje obserwacje** tylko odczytują osobiste połączenia i przekazują znaleziska do
prywatnego Inbox. Każda zakładka ma własne przyciski tworzenia.
`/routines?tab=watches` otwiera obserwacje. Jedno sprawdzenie wykonuje najwyżej
30 zapytań do modelu, a długie wyniki są przycinane, więc obserwacja dużego
workspace pozostaje tania.

Organizacja → Proaktywność oddziela sugestie, monitoring, wspólne limity, harmonogram dostarczania i powitania. Niezapisane zmiany można odrzucić. Usługi działające w tle pokazują stan i zużycie, a ustawienia modelu i budżetu rozwija się przy konkretnej usłudze.

Rutyny harmonogramowe, zdarzeniowe i obserwacje korzystają z tej samej ramy modalu: stałego nagłówka i nawigacji oraz przewijanego formularza. Tworzenie obserwacji prowadzi przez konfigurację, wiadomość i częstotliwość; przycisk Wstecz zachowuje wpisane dane. Wybór agenta pokazuje te same avatary co czat. Ustawienia wykonania i dostarczania obserwacji są zebrane w jednym panelu opcji zaawansowanych.

Discover na dashboardzie zaczyna się od ilustrowanych możliwości. Najedź na wykres
w _Your period_, aby zobaczyć przedział i wartość; koszty są kwotami. Projekty
pokazują opisy, a wiersze agentów używają tych samych avatarów co chat.

Karty dashboardu korzystają ze spójnych, zwartych wierszy, oznaczeń usług i etykiet statusu. Liczniki i wykresy dostosowują się do szerokości karty, również we własnych układach. Placeholdery odpowiadają rodzajowi ładowanej zawartości; niedostępny briefing pokazuje możliwość ponowienia zamiast informacji o braku propozycji.

Pusty chat wita zależnie od lokalnej pory dnia. Najpierw pokazuje pole wiadomości, a pod nim do czterech podpowiedzi. Pierwszeństwo mają opublikowane podpowiedzi agenta; AgenticOS może korzystać z osobistych sugestii, przechowywanych przez pięć minut w cache bieżącej sesji konta. Placeholdery zachowują miejsce do ustalenia źródła. Ekran startowy nie pokazuje podglądu Inbox, pracy w tle ani podpowiedzi skrótów klawiaturowych; otwórz Inbox lub pracę w tle z nawigacji.

Zapisana rozmowa od razu pokazuje placeholdery historii, bez migania powitania; sidebar i historia ładują się niezależnie. Ręcznie wysłana wiadomość łagodnie przesuwa się pod górę; wiadomości z kolejki nie przestawiają widoku. Scrollowanie, dotyk i klawiatura przerywają ruch. Wspólne menu i modale używają niewielkich, łagodnych przejść; preferencja Motion wyłącza ruch.

## Inbox { #the-inbox }

**Inbox**, pod Czatem w pasku bocznym, to to, co platforma przyniosła ci z
własnej inicjatywy: co twoje [obserwacje](governance.md#proactive-work) znalazły
na twoich połączeniach i co zaproponował nocny przegląd. Liczba obok mówi, ile
czeka. Czyta się go jak skrzynkę pocztową: jeden wiersz na rzecz, pilne
pierwsze, skąd i kiedy przyszła, a odpowiedzi w wierszu. Filtruj po źródle albo
otwórz **Załatwione**, żeby zobaczyć, co już przyjąłeś lub odrzuciłeś, i
przywrócić odrzucone. **Co znalazły** na karcie Obserwacje w Rutynach otwiera go
zawężonego do obserwacji. Krótsze wiersze otwierają twój dashboard jako
**Briefing**, a pusty czat z agentem startowym pokazuje pierwszą z nich jako
kartę, z linkiem do reszty.

To, co obserwacja znajdzie, a co nie musi trafić do ciebie od razu, czeka na
twój poranek: o godzinie, którą trzyma proaktywność organizacji, jedno
powiadomienie i jedna wiadomość prywatna od każdego jej bota w Slacku, Teams i
Mattermost, który cię zna, wymieniają to, co nowe. Każde znalezisko trafia tylko
do jednego briefingu.

Przełącznik organizacji znajduje się pod logo u góry paska bocznego i pokazuje
nazwę oraz awatar aktywnej organizacji. Otwórz go, aby zmienić organizację,
zarządzać organizacjami lub utworzyć nową. W zwiniętym pasku bocznym przełącznik
ma postać awatara; menu telefonu udostępnia ten sam element. Ustawienia konta
pozostają w menu konta na dole.

Wyszukiwanie znajduje się nad pozycjami nawigacji, ze skrótem klawiaturowym
widocznym na komputerze. Powiadomienia i menu konta pozostają pod przewijaną listą.
Na urządzeniach dotykowych wspólne przyciski, pola, zakładki i pozycje menu mają
większe obszary dotykowe. Dialogi korzystają z wysokości widocznej nad klawiaturą
ekranową; panele boczne zatrzymują fokus wewnątrz i oddają go do elementu, który je
otworzył. W polu wyszukiwania listy Escape najpierw czyści zapytanie, a kolejne
naciśnięcie zamyka dialog.

## Dzwonek { #the-bell }

U dołu paska bocznego: bieżący licznik tego, czego jeszcze nie
przeczytałeś, a kliknięcie otwiera samą listę. W przeciwieństwie do widgetu
powyżej, otwarcie pobiera stronę, na której właśnie jesteś, a nie pięciokartowy
podgląd — **Load more** cofa cię, stronę po stronie, przez organizację, w
której właśnie jesteś, plus to, co zaadresowano do całego wdrożenia, aż dojdzie
do tego, co wypadło z zasięgu.

Każdy wiersz zaczyna się od tego, czego dotyczy: twarzy agenta z plakietką
mówiącą, jak poszedł jego run, albo ikony rodzaju zdarzenia — zielonej dla
ukończonego runu albo serwera MCP, który znów działa, czerwonej dla porażki
albo wyczerpanego budgetu, bursztynowej dla zatwierdzenia albo ostrzeżenia
o budgecie.

Przełącz organizację, a dzwonek jest jej:
powiadomienie z organizacji, którą zostawiłeś, nie zniknęło — jest za
przełącznikiem. Administrator wdrożenia to jedyny wyjątek — jego dzwonka nie
zawęża organizacja, w której akurat działa, bo audytorium „admins” sięga go bez
członkostwa, po którym można by zawęzić.

Wiersz z celem jest linkiem; ten bez celu — najczęściej własne ogłoszenie
administratora aplikacji — służy tylko do oznaczenia jako przeczytany.
Oznaczenie jednego wiersza jako przeczytanego albo wszystkich naraz od razu
aktualizuje licznik; nic tutaj nie czeka na przeładowanie strony. **Mark all
read** zbiera partiami nawet pięć tysięcy nieprzeczytanych wierszy, a potem pyta
o licznik jeszcze raz — więc przy większej zaległości plakietka dalej pokazuje
to, co wciąż jest nieprzeczytane, a kolejne kliknięcie dokańcza resztę, zamiast
żeby plakietka ogłaszała skrzynkę, którą przerobiła tylko częściowo.

Każde kliknięcie zawsze posuwa sprawę dalej, nawet gdy cała partia to wiersze,
których czytający już nie widzi. Nigdy ich nie oznacza: sprawdzenie dotyczy
_bieżących_ uprawnień, więc ktoś zdegradowany na tydzień i przywrócony zastałby
powiadomienia bezpieczeństwa z tego tygodnia już przeczytane. Zamiast tego
ucięte zamiatanie mówi, gdzie się zatrzymało, a kolejne kliknięcie rusza stamtąd.

I licznik, i zamiatanie mówią, kiedy zatrzymały się na tej granicy, a nie na końcu skrzynki
— `approximate` w `GET /notifications/unread-count` i `remaining` w
`POST /notifications/mark-all-read` — bo inaczej licznik dokładnie na granicy i
prawdziwy licznik dokładnie tej samej wielkości to ta sama liczba.

Przeczytane to nie to samo co usunięte i dostępne jest jedno i drugie.
Najechanie na wiersz odsłania krzyżyk, który wyjmuje go z listy; **Clear**
w nagłówku wyjmuje wszystko, co jest aktualnie na liście — przeczytane
i nieprzeczytane. Wyczyszczenie nieprzeczytanego wiersza oznacza go zarazem
jako przeczytany, bo wiersz, do którego nic na ekranie już nie sięga, nie może
dalej liczyć się do plakietki. Tak jak „Mark all read", jedno czyszczenie ma
granicę — tysiąc wierszy — a dłuższa zaległość wymaga drugiego kliknięcia.

Czego wyczyszczony wiersz _nie_ robi, to nie wraca. Powiadomienie zostaje
zachowane i przestaje być wypisywane, zamiast zostać usunięte, i właśnie to
sprawia, że tak jest: skrzynka rozpoznaje powtórzenie po fakcie, który opisuje,
więc usunięty wiersz to taki, który następne sprawdzenie budżetu albo następna
próba zapisałyby ponownie. Odrzucenie alertu, którym się już zająłeś, jest więc
ostateczne — dla tego wystąpienia; _nowy_, o nowym fakcie, nadal przyjdzie.
Wiersze wychodzą też same z siebie: dziewięćdziesiąt dni po zapisaniu, jeśli
zostały przeczytane, i rok niezależnie od tego.

To, co tu trafia i co można wyłączyć, wyjaśnia [Governance](governance.md#alerts)
— ta strona to tylko dwa miejsca, w których to czytasz: dzwonek dla tego, co
się właśnie wydarzyło, karta na dashboardzie dla kilku najnowszych, przy
następnym otwarciu strony.

## Asystent { #the-assistant }

Na telefonie **Architekt** jest w górnym pasku obok powiadomień, a na komputerze
w prawym dolnym rogu: agent, którego
każda organizacja dostaje bez instalowania czegokolwiek, wspólny dla wszystkich,
którzy mogą uruchamiać agentów (`agents:run`). Jest powiązany z
[serwerem MCP tej platformy](mcp.md#agenticos-as-an-mcp-server). Zapytaj go,
którzy agenci odpowiadają na pytania o zwroty, dlaczego nocny run się nie udał
albo co jest w bazie wiedzy.

Powiedz mu, co agent ma robić, a zbuduje go z tobą, jedno pytanie naraz, każde z
proponowanymi odpowiedziami: dobiera capabilities, bazę wiedzy i model, w jednym
zdaniu mówi dlaczego, tworzy szkic agenta, sprawdza go na twoich własnych pytaniach
jako nieopublikowany draft, poprawia to, co było źle, i publikuje go, gdy to
zatwierdzisz. Tak samo ustawia rutynę.

Zanim cokolwiek się zmieni, pokazuje ci, co zatwierdzasz: szkic agenta jako sam
szkic - gdzie powstanie, jego nazwę, co może robić i jego instrukcje - a
wszystko inne jako dokładne wywołanie. Działa z twoimi uprawnieniami, więc
znajduje i robi to, co ty mógłbyś, i nic więcej. Jego koszty liczą się jak
każdego agenta.

Dymek nad nim mówi o tym, co na ciebie czeka — akceptacje, organizacja bez
żadnego agenta — albo o stronie, na której jesteś, a czasem podsuwa wskazówkę.
Kliknięcie dymka zadaje mu pytanie; × wycisza tę stronę, a dzwonek w jego oknie
wyłącza dymki w ogóle. Dymek bez odpowiedzi znika po kilku sekundach. Pozostawiony
w spokoju na niecałą minutę przycisk chowa się w prawą krawędź ekranu i zostawia
wąski pasek, za który można go wyciągnąć - z kropką, gdy coś czeka - i zostaje
tam między stronami, dopóki go nie otworzysz.

Na telefonie dymka nie ma - zasłaniałby stronę, o której mówi - a przycisk nosi
zamiast niego kropkę. Akceptacje, o których już powiedział, zostają powiedziane do
końca karty przeglądarki, nawet gdy link przeładuje konsolę.

Okno korzysta z czatu konsoli i początkowo ma wybranego głównego asystenta.
Selektor w nagłówku pozwala wybrać opublikowanego agenta, którego możesz
uruchomić. Zmiana agenta zachowuje bieżącą rozmowę; nagłówek i historia rozmów
odpowiadają wybranemu agentowi. Kafelki powitalne Architekta pojawiają się tylko,
gdy wybrany jest główny asystent. Na telefonie okno zajmuje cały ekran.

Każde nowe pytanie zawiera świeży, uporządkowany kontekst bieżącej strony
konsoli, o ile udostępnianie kontekstu strony jest włączone. Okno pokazuje,
która strona zostanie udostępniona, i pozwala wyłączyć udostępnianie.

Pytanie w kolejce lub ponowienie odrzuconego wysłania zachowuje kontekst strony
i agenta wybranego w chwili wysłania. Nowe pytanie lub ponownie wygenerowana
odpowiedź korzysta z bieżącej strony i agenta. Zmiana konta lub organizacji
resetuje rozmowę w oknie, wybór agenta i ustawienie kontekstu strony.

Gdy wskazuje stronę, link otwiera się w konsoli za oknem i podświetla kontrolkę,
o którą chodzi — przycisk tworzący agenta, zakładkę z akceptacjami. Aparat w
nagłówku okna pokazuje mu stronę, na której jesteś: przeglądarka pyta, którą
kartę udostępnić, a jedno zdjęcie trafia jako załącznik do twojej następnej
wiadomości.

Architekt planuje dłuższe zadania jako listę kroków, którą widać na bieżąco,
zapamiętuje notatki o tobie między rozmowami, powie, ile kosztują twoi agenci, i
usuwa tylko draft agenta, który utworzył przez pomyłkę, oraz rutynę, o której
usunięcie poprosisz. Oprócz
akceptacji i pustej organizacji dymek odzywa się, gdy twój run właśnie się nie
udał, i gdy formularz jest otwarty, niedokończony, od minuty.

Przed podłączeniem modelu Architect otwiera ten sam czat z graficzną kartą konfiguracji, krótką listą kroków i przyciskiem ustawień modelu. Możesz napisać wiadomość w widżecie lub wybrać szkic Architecta w czacie: zapisze odpowiedź konfiguracyjną i kartę w historii, bez wywołania modelu i bez runu AI. Odpowiedź używa nazwy wybranego agenta. Przyciski konfiguracji respektują uprawnienia; pozostali członkowie widzą wskazówkę do administratora. Po publikacji zwykła rozmowa jest dostępna bez zamykania widżetu.

Architekt jest agentem jak każdy inny, więc jego nazwę, model, wiedzę i resztę
spec edytuje się w Agent Builderze - może to zrobić ktoś, kto zmienia ustawienia
organizacji, bo uruchamia go każdy w organizacji. Na stronie organizacji jest
karta, która wyłącza go dla wszystkich i ustawia jego powitanie. **Ustawienia →
Asystent** to już tylko twoje własne wskazówki.

## Domyślne agenty platformy { #shipped-agent-defaults }

AgenticOS, Architect i domyślna konfiguracja nowych agentów nie zawierają narzędzi do roboczego planowania. Agenci raportują postęp na czacie, a pracę wymagającą trwałego zapisu obsługują przez zarządzane Tasks w AgenticOS MCP.

Oba agenty startowe i nowe agenty z konsoli mają Watch a command, Background topics, Work while tools run, ograniczone wyszukiwanie wcześniejszych rozmów i wyszukiwanie narzędzi lokalnym BM25 z pięcioma wynikami. Otrzymują specjalistów research, explore i review, dynamicznych specjalistów oraz automatyczny wybór delegowania sync/async. Monitory kończą się wraz z turą i wymagają trwałej powłoki; tematy w tle przeżywają turę. Historia jest wyszukiwana tylko na żądanie, najpierw fragmenty, potem ograniczone okna transkrypcji. Grupy i uruchomienia bez nadzoru nie przeszukują prywatnej historii.

Tylko dostarczany AgenticOS ma Computer use, przeglądarkę i Coding agenta. Sterowanie komputerem i kodowanie domyślnie korzystają z zatwierdzonego desktopa; kodowanie w sandboxie wymaga osobnego skonfigurowanego poświadczenia. Domyślna przeglądarka również korzysta ze sparowanego desktopa; administrator może zamiast tego skonfigurować endpoint przeglądarki wdrożenia. Nowe agenty dziedziczą wspólną konfigurację bez tych trzech narzędzi. AgenticOS odpowiada na pytania o platformę bezpośrednio, korzystając z przewodnika i AgenticOS MCP. Domyślna konfiguracja nie przypina już Architecta; odświeżenie usuwa niezmienione domyślne przypięcie, a własnych delegatów pozostawia.

Każda organizacja otrzymuje **AgenticOS**, agenta do codziennej pracy, oraz
**Architect**, asystenta konfiguracji platformy. Oba mają pamięć. Nowy agent
tworzony w konsoli zaczyna od aktualnego szablonu AgenticOS; autor może potem
zmienić prompt i narzędzia. AgenticOS może poprosić opublikowanego Architecta o
pomoc przez AgenticOS MCP, z zachowaniem uprawnień, budżetów i zatwierdzeń.

Otwarcie konsoli sprawdza również dostarczone ustawienia. Niezmienione instrukcje,
capability, powiązania MCP, skille i propozycje pierwszych wiadomości otrzymują
aktualizacje. Sama zmiana modelu lub budżetu nie blokuje aktualizacji, a wybrane
wartości pozostają zachowane. Własne prompty i konfiguracja narzędzi pozostają
Twoje. Nieopublikowana edycja pozostaje draftem; aktualizacja działającego agenta
nie publikuje jej. Zarchiwizowane agenty pozostają zarchiwizowane. Starsze agenty
są rozpoznawane po pochodzeniu lub historycznych ustawieniach, nie tylko po nazwie.

Czat pokazuje potwierdzone zapisy i korekty pamięci z linkiem do **Your memory**;
odmowy i sporne informacje nie są oznaczane jako udany zapis. Propozycja rutyny
lub obserwacji ma własną kartę konfiguracji i wymaga sprawdzenia przed aktywacją.
Formularze chowają opcje wykonania i dostarczania pod **Opcje zaawansowane**,
zachowując dotychczasowe wartości domyślne.

## Zmiany wprowadzone gdzie indziej { #changes-made-elsewhere }

Otwarta strona nadąża za zmianami wprowadzonymi gdzie indziej: w konsoli
współpracownika, przez skrypt z [kluczem API](api.md), przez Claude Code
połączone z [serwerem MCP platformy](mcp.md#agenticos-as-an-mcp-server) albo przez
Architekta. Każdy udany zapis jest ogłaszany otwartym konsolom organizacji, gdy
tylko zostanie zatwierdzony, także te, które wykonuje tylko konsola — udostępnianie,
rutyny, boty kanałów, udostępnienia grup, ustawienia powiadomień — a lista lub
strona szczegółów bez niezapisanych zmian pobiera dane ponownie na miejscu. Agent
utworzony kluczem pojawia się na stronie Agents bez przeładowania, a agent
udostępniony w jednej karcie pokazuje nowych odbiorców w innej.

Ogłaszane są też runy: gdy startują, zatrzymują się na zatwierdzeniu lub pytaniu
i gdy się kończą. Run uruchomiony przez harmonogram pojawia się na otwartej
stronie Activity i zmienia tam status, choć nie stoi za nim żadne twoje żądanie.

Ogłaszane są też datasety: dodany albo usunięty przypadek, zmiana oceniania,
wynik albo decyzja przeglądu, a także propozycje, które
[generator przypadków](datasets.md#generating-cases) kończy w tle - pojawiają się
w zakładce Generated otwartego datasetu bez przeładowania.

Tak samo ogłaszane są luki w wiedzy: temat odrzucony albo z nowym szkicem w
jednej karcie i pytania, które co 15 minut umieszcza przejście grupujące,
pojawiają się na otwartej karcie Luki w wiedzy bez przeładowania.

Wyjątkiem jest Builder, bo zapisuje draft w trakcie pisania. Gdy edytowany agent
zmieni się gdzie indziej, Builder przestaje zapisywać i pobiera nową wersję. Bez
niezapisanych zmian po prostu ją przyjmuje; z niezapisanymi zmianami mówi, kto i
którędy go zmienił, i czeka na twój wybór: **Przeładuj** (ich wersja) albo
**Zachowaj moje zmiany** (twoja, zapisana zamiast ich).

Słyszysz tylko o tym, co możesz odczytać: zmiana agenta, skilla, bazy wiedzy,
pliku kontekstu, strony, klucza, serwera MCP albo datasetu, których nie widzisz, nigdy nie
trafia do twojej konsoli, a usunięcie trafia tylko do ról, które widzą każdy
wiersz danego rodzaju. Runy trafiają do ról, które czytają historię runów albo
decydują o zatwierdzeniach, luki w wiedzy do ról, które czytają każdy run, boty
kanałów do ról, które nimi zarządzają, a twoje
powiadomienia tylko do ciebie.
Gdy połączenie zostanie zerwane, konsola działa jak dotąd i sama się ponownie łączy.

## Chat { #chat }

Miejsce, w którym rozmawiasz z opublikowanym agentem. Selektor wybiera, który
agent odpowiada, a run zachowuje się dokładnie tak, jak zachowałby się w Slacku
albo za API — ten sam budżet, ta sama bramka zatwierdzeń, ten sam ślad audytowy,
bo [każda powierzchnia przechodzi przez jeden runner](channels.md).

**Lista rozmów** mówi, z kim jest każdy wątek i kiedy ostatnio się zmienił.
Wątek, którego run wciąż pracuje, ma kręcący się wskaźnik i czas trwania; wątek
z odpowiedzią, której nie widziałeś od ostatniego otwarcia, ma kropkę, a otwarcie
go ją gasi - tylko dla ciebie, bo udostępniony wątek każdy czytelnik czyta osobno.

Rozmowy, które ktoś ci udostępnił, są w sekcji **Udostępnione Tobie**, pod
ulubionymi. Zmiana nazwy, udostępnianie, archiwizacja i usuwanie należą do ich
właściciela. W menu możesz dodać rozmowę do ulubionych lub ją stamtąd usunąć, albo wybrać **Usuń z moich czatów**, co kończy twój dostęp i
zostawia rozmowę bez zmian dla pozostałych. Rozmowa udostępniona ci do odczytu
nie ma pola wiadomości. Gdy ktoś udostępni ci rozmowę, dostajesz powiadomienie,
które ją otwiera. Nieprzeczytane i ulubione rozmowy udostępnione trafiają do standardowych sekcji.

W oknie **Udostępnij** przy każdej osobie, której udostępniono rozmowę, jest
wybór **Podgląd** lub **Edytuj**: zmienia, co może zrobić, bez cofania i
ponownego udostępniania. Link do udostępnienia pozostaje tylko do odczytu.

Udostępnienia bezpośrednie mają limity na minutę: 100 prób na organizację, 20 na nadawcę, 20 na odbiorcę i pięć na parę nadawca–odbiorca w tej organizacji. Nowa rozmowa nie zeruje limitu. Odmowa zwraca `429` z czasem ponowienia i nie tworzy ani udostępnienia, ani powiadomienia. Lista udostępnień i faktyczny dostęp odświeżają się co 15 sekund przy aktywnej stronie.

Trzy rzeczy w kompozytorze, które warto znać.

**Twoje własne konta.** Agent powiązany z
[kontem każdej osoby z osobna](mcp.md#whose-account-a-binding-speaks-through) w
danej usłudze rozmawia z nią jako ty. Kontrolki czatu wymieniają, które z usług
agenta potrzebują twojego konta i czy każda jest gotowa, wraz z przyciskiem
połączenia, który otwiera zgodę providera w nowej karcie. Zapytaj przed
połączeniem, a nic się nie pojawi, dopóki agent faktycznie nie potrzebuje usługi:
wtedy odpowiedź zatrzymuje się na karcie z tym przyciskiem, a po podłączeniu konta
ta sama odpowiedź idzie dalej. **Skip** pozwala jej iść dalej bez usługi.

**Załączniki** są parsowane i przekazywane wyłącznie do tej rozmowy; nie trafiają
do [kolekcji wiedzy](file-processing.md). Zobacz
[Przetwarzanie plików](file-processing.md#chat-file-uploads).

**Slash commands** rozwijają się w prompt, zanim wiadomość zostanie wysłana.
Wbudowane przychodzą razem z produktem; własne możesz napisać w
**Settings → Slash commands**, a każdą wbudowaną, z której nie korzystasz,
ukryć. Należą do ciebie, nie do organizacji.

**`@` wskazuje agentowi, czego użyć.** Wpisz `@`, a menu pokaże, czego agent może
użyć, w tej kolejności: jego serwery MCP, agentów, którym przekazuje pracę (przy
włączonej capability delegowania), jego capabilities - **Sandbox**, **Web
research** - jego skille, a potem bazy wiedzy i pliki kontekstu. Wybór zostaje w
twoim tekście jako `@Nazwa`, oznaczony swoim logo, a agent dostaje polecenie, by z
niego skorzystał - z narzędzi serwera, narzędzi capability, wyszukiwania w bazie
wiedzy, skilla - bez wklejania samej treści. Wskazanie agenta przekazuje mu pracę;
nigdy nie zmienia tego, kto odpowiada. Usuń `@Nazwa`, a wybór znika. Wklejony link
pokazuje ikonę swojej strony nad polem i w wysłanej wiadomości. Wzmianka nigdy nie
poszerza tego, do czego agent sięga: serwer sprawdza każdą ponownie jako ty, wobec
tego, co agent już ma. W panelu testowym Buildera menu czyta testowany szkic. Dopóki rozmowa jest pusta, pole pokazuje po kolei
przykłady zbudowane z tego, czego agent może użyć - jego serwera, capability,
delegata, skilla - oraz `/`; znikają, gdy tylko w nie klikniesz. Nad nim karty
to własne **pierwsze wiadomości** agenta, ustawiane w Builderze pod jego
instrukcjami; agent bez nich proponuje cztery własne wiadomości czatu, w tym jedną
z pytaniem, co potrafi, i jedną z ustawieniem rutyny.

Listy rozmów zachowują głównego agenta i pokazują też Claude Code lub Codex, gdy zapisane raporty zadań potwierdzają ich pracę w danym wątku. Sidebar, czaty projektu, dashboard i historia Quick Ask korzystają z tych samych ikon i etykiet. Każdy coding harness pojawia się raz, pozostaje po odświeżeniu i nie zależy od bieżących ustawień czatu. Sam wybór harnessu bez jego uruchomienia nie dopisuje go do historii.

Panel Files grupuje pliki według folderów, rozróżniając identyczne nazwy w różnych katalogach. Podgląd HTML wczytuje lokalne arkusze stylów i ich zagnieżdżone zasoby przez ten sam mechanizm dostępu co stronę. Podgląd i Źródło pozostają oddzielne, a skrypty są wyłączone. Jeśli arkusza nie można odczytać, podgląd wskazuje, który plik zawiódł.

Pliki zmienione w turze mają skróty pod odpowiedzią. Zadania programistyczne korzystają z zapisanego zestawu zmian, w tym edycji przez shell; zadanie bez niego używa raportu harnessu. Panel zadania oferuje **Cofnij to zadanie**, gdy możesz edytować jego pierwotny workspace, a snapshot jest kompletny. Skróty otwierają bieżące pliki workspace, a nie wersjonowaną kopię.

Cofnięcie działa jako trwałe zadanie w izolowanym workspace rozmowy. Snapshoty współdzielonych zakresów pozostają tylko do odczytu. Panel pokazuje postęp; nieznany wynik rezerwuje workspace, dopóki Ponów cofnięcie nie sprawdzi jego plików.

Snapshoty do cofania mają limit 2 MiB na plik i 16 MiB łącznie dla danych przed zmianą i po niej; większe zmiany można przeglądać bez cofania. Weryfikacja ogranicza też odczyty starszych snapshotów. Przyjmowanych jest sześć żądań na osobę i dwadzieścia na organizację na minutę, z lokalnym limitem podczas awarii Redis. W organizacji działa najwyżej jedno zadanie cofania naraz.

Podczas pracy agenta komunikaty o postępie i następujące po nich wywołania narzędzi pojawiają się w kolejności nadejścia w jednej rozwiniętej osi czasu. Zakończenie uruchomienia zwija historię pod jednym „Worked for…” lub „Thought for…”, pozostawiając pod spodem tylko finalną odpowiedź. Rozwinięcie historii przywraca tę samą kolejność wiadomości i grup narzędzi. Rozumowanie ma osobne, opcjonalne rozwinięcie; jego nagłówki nie tworzą etapów procesu. Pytania i zatwierdzenia zachowują stan oczekiwania do rozwiązania, także przy delegacji. Aktywne karty zatwierdzania i wyniki wizualne pozostają poza zakończoną historią.

Kolejne narzędzia między wiadomościami tworzą zwiniętą grupę; rozwiń ją, aby zobaczyć poszczególne wywołania.

Zatwierdzenia w czacie pozostają jedną prostą kartą przy polu wiadomości: operacja, jej ikona i tytuł zadania lub obiektu, a dodatkowe argumenty pod Details. Przyciski Approve i Reject są obok żądania, a na wąskim ekranie pod nim. Zakończona aktywność ma spokojny znacznik ukończenia, oczekujące kroki osobny status, a działające kroki zachowują ikonę operacji zamiast osobnej animowanej kuli przy każdym wywołaniu.

Ponowne otwarcie czatu odtwarza też zatwierdzenia i pytania narzędzi subagenta, których nie ma na osi głównego agenta. W trakcie zatwierdzonego wznowienia przez HTTP wstrzymany subagent jest pokazywany jako pracujący. Zakończony opublikowany subagent zachowuje własny wynik, gdy agent nadrzędny zatrzyma się na kolejnej decyzji.

Napływający tekst pozostaje czytelny podczas ładowania modułu formatowania Markdown. Pole wiadomości ma nieprzezroczyste tło i delikatny stan fokusu, bez animowanej ramki i rozmywania treści pod spodem.

Oś czasu w trakcie pracy jest częścią strony. Rozwinięta historia zakończonej pracy ma ograniczoną wysokość i własne przewijanie. Sąsiadujące segmenty jednego agenta i uruchomienia mają wspólne podsumowanie oraz czas rozpoczęcia, także gdy zawierają komunikaty między narzędziami i wznowienia po zatwierdzeniu. Inny agent lub wiadomość użytkownika pomiędzy segmentami rozpoczyna osobny turn. Zakończone i zagnieżdżone wymiany agentów pozostają dostępne, także raporty agentów programistycznych. Otwórz wymianę, aby przeczytać instrukcje, odpowiedź i zwinięte rozumowanie.

Udane zapisy MCP pokazują karty z linkami do projektów, tabel, zadań, rekordów, agentów, workflow, skilli i Context. Błędy nie tworzą kart sukcesu. Wysłana wiadomość pojawia się blisko góry z miejscem na odpowiedź; ręczne przewijanie zachowuje pozycję. Listy Person i Agent przewijają się w oknie rekordu. Pytania działają także po wznowieniu czatu przez HTTP po zatwierdzeniu operacji.

Powiadomienia o wynikach również są przy polu wiadomości. Powiadomienia o zatwierdzeniu są ukryte, gdy widoczny jest panel decyzji lub agent pracuje, także dla starszych przebiegów. W pozostałych przypadkach prowadzą do kolejki zatwierdzeń. Nie mają przycisków Widziane, Zrobione ani Nie pytaj więcej: operację rozstrzyga wyłącznie zatwierdzenie lub odrzucenie właściwego żądania. Inbox i dzwonek zachowują własne powiadomienia.

**Pod odpowiedzią.** Agent z [Następnymi krokami](reference/capabilities.md#follow-ups)
proponuje pod najnowszą odpowiedzią do trzech następnych kroków jako przyciski, a
kliknięcie wysyła jeden z nich. Linijka mówi, co zanotował o tobie albo co
zapomniał, z **Zarządzaj (Manage)** prowadzącym do
[samych notatek](reference/capabilities.md#memory-files) - poproś, żeby coś
zapomniał, a zapomni. Gdy prośba wymaga capability, której agent nie ma, karta
proponuje ją włączyć albo poprosić o to właściciela agenta
([jak](reference/capabilities.md)).

**Zachowanie prośby, która zadziałała.** Najedź na własną wiadomość: kalendarz
zamienia ją w rutynę - ten sam prompt, domyślnie co tydzień, na agencie, który
odpowiedział - a robot prosi Architekta, żeby zbudował agenta, który to robi.
Najedź na odpowiedź, a zakładka prosi Architekta, żeby zrobił
[skill](skills.md) z tego, jak to zostało zrobione, i każdy agent zrobił to
następnym razem tak samo; dostaje twoją prośbę i odpowiedź, a przycisk widzi ten,
kto może pisać skille.

**Linki, które wskazują.** Link do konsoli, który agent napisze w odpowiedzi -
„tu jest przycisk, który podłącza twój Gmail” - otwiera tę stronę bez
przeładowania konsoli, a `?highlight=` w nim wskazuje kontrolkę, którą nazywa,
tak jak linki Architekta.

**Agent AgenticOS poznaje cię.** Dopóki twoje konto nic nie mówi o twojej roli
ani pracy, powitanie zaczyna krótką rozmowę: czym się zajmujesz, co wypełnia ci
tydzień, w jakich narzędziach pracujesz - po jednym pytaniu, każde z odpowiedziami
do wybrania. To, co powiesz, trafia do twojego profilu, więc od tej pory wie to
każdy agent, a rozmowa kończy się maksymalnie trzema kartami do ustawienia -
rutyną, usługą do podłączenia, własnym agentem - każda na jedno kliknięcie.
Pomiń pytanie albo poproś o coś konkretnego, a zamiast tego zrobi robotę.

**Co zauważyła w nocy.** Tam, gdzie organizacja to włączyła, raz dziennie,
wcześnie rano twojego czasu, platforma przegląda w zadaniu w tle twoje ostatnie
rozmowy: prośba, którą powtarzasz,
staje się propozycją rutyny, to, czego agent dowiedział się o twojej roli -
propozycją profilu, a twój pusty czat z AgenticOS dostaje pierwsze wiadomości
napisane pod twoją pracę. Propozycje czekają jako karty w tym pustym czacie, na
twoim dashboardzie i w dzwonku, a **Ustawienia → Asystent** pokazują wszystkie -
tam przywrócisz odrzuconą albo wyłączysz to dla siebie; przyjmij jedną, a zostanie ustawiona, odrzuć, a ta sama propozycja nie
wróci. Nic się nie uruchamia, gdy nic nowego się nie wydarzyło, a to, ile może to
kosztować, ma [limit na osobę](governance.md#proactive-work). Link do czatu z
`?agent=<slug>` otwiera czat na tym agencie.

**Godziny pracy** w **Settings → Profile** mówią agentom, kiedy pracujesz, więc
rutyna, którą zaproponują, wypada w twoim dniu. Nic na nie nie czeka: to wiedza
dla agenta, nie harmonogram.

Po ponownym otwarciu rozmowy widzisz najnowsze wiadomości. Wybierz **Wczytaj wcześniejsze wiadomości** nad historią, aby przeczytać starsze tury. Trwające odpowiedzi i niezapisane wyniki pozostają widoczne podczas odświeżania zapisanej historii.

Jeśli nie uda się zapisać odpowiedzi asystenta, czat poprosi cię o skopiowanie potrzebnego tekstu przed opuszczeniem rozmowy. Dotyczy to również częściowych odpowiedzi z przerwanych uruchomień. Tekst przesłany na żywo pozostaje widoczny, ale może go zabraknąć po ponownym otwarciu rozmowy.

**Gdy agent pracuje**, to, co wysyłasz, czeka na jego odpowiedź, jak w każdym
czacie: stoi w kolejce nad kompozytorem i wychodzi, gdy run się skończy.
Przeciągnij wiadomość w kolejce albo użyj jej strzałek, żeby zmienić kolejność.
**Send now** wysyła ją zamiast tego do trwającego zadania - agent czyta ją w
następnym kroku i zmienia kurs bez zaczynania od nowa, a w rozmowie pojawia się
tam, gdzie dotarła. Wiadomość z plikami zawsze czeka na odpowiedź. Slack, Telegram
i Mattermost działają po swojemu, jak opisuje [Kanały](channels.md).

**Wychodzenie w trakcie odpowiedzi.** Nie musisz czekać. Zamknij kartę, wyjdź z
aplikacji albo otwórz inną rozmowę, a agent dokończy odpowiedź sam: trafi ona do
rozmowy, a dzwonek - i e-mail, jeśli zostawiasz je włączone dla runów, które się
kończą albo nie udają - powie Ci, że jest, z linkiem do niej. Tura, która po
godzinie bez nikogo przy ekranie wciąż trwa, zostaje zatrzymana i dostajesz o tym
informację ([`CHAT_DETACHED_TURN_MINUTES`](configuration.md#a-chat-turn-left-running)).
Taka, która czeka na zatwierdzenie albo na Twoją odpowiedź na pytanie, powiadamia
Cię przez nie.
Gdy wrócisz, zanim odpowiedź się skończy - do rozmowy, z innej karty, po
odświeżeniu strony - czat podejmie ją tam, gdzie jest, ze wszystkim, co agent już
zrobił, i dalej rysuje ją na bieżąco.

**Na telefonie** czat działa jak komunikator: pole wpisywania zostaje nad
klawiaturą, a rozmowa przy ostatniej wiadomości, gdy klawiatura się otwiera,
Enter zaczyna nową linię, a załącznik i
dyktowanie są pod jednym **+**. Pola nigdy nie są na tyle małe, żeby iOS je
przybliżał.

**Rysunki.** Agent z [Wizualizacjami](reference/capabilities.md#visuals) rysuje pod
swoją wiadomością - diagram, explainer z suwakami, scenę 3D - a ty widzisz, jak powstaje
w trakcie pisania; jego skrypty startują po zakończeniu. Panel pokazuje cały rysunek,
dopasowany do rozmowy, z przyciskami do pełnego ekranu, pokazania kodu, pobrania,
skopiowania SVG jako obrazu, powiększenia i zapisu jako
[aplikacji](artifacts.md#visuals) z linkiem do udostępnienia. Gdy rysunek zgłosi błąd,
agent już o nim wie; **Napraw** prosi go ponownie. Na telefonie stuknięcie otwiera go na
pełnym ekranie. Karta **Ostatnie wizualizacje** na dashboardzie pokazuje najnowsze
rysunki zrobione dla ciebie, a każdy otwiera rozmowę, w której powstał.

**Wersje robocze.** Agent z [Wersjami roboczymi](reference/capabilities.md#drafts)
pokazuje tekst, który wyślesz lub wkleisz gdzie indziej - e-mail, odpowiedź, wpis -
jako kartę w swojej odpowiedzi. Każda część ma własną ikonę kopiowania, która
kopiuje zwykły tekst; kilka wariantów jednej wersji roboczej to zakładki w jednej
karcie. Własne **Kopiuj** wiadomości obejmuje też jej wersje robocze.

**Oglądanie przeglądania.** [Przeglądarka](reference/capabilities.md#browser-automation)
otwiera się automatycznie w pełnym panelu obok przewijanej rozmowy.
Na wąskim ekranie zajmuje cały widok. Po zamknięciu panelu zostaje w rozmowie
mały przycisk do ponownego otwarcia. Karty odwiedzonych stron pokazują ikonę,
domenę i tytuł, także po ponownym otwarciu rozmowy. Każda odpowiedź ma jeden
kafelek na kartę przeglądarki; kliknięcia, ponowne odczyty i powroty aktualizują ten kafelek. Pasek kart w panelu
przełącza strony. Po zakończeniu
zostaje ostatni obraz. **Wznów sesję** prosi agenta o odtworzenie prywatnej sesji,
dostępnej przez maksymalnie godzinę. Zdalne strony zamykają się po każdym runie;
wznowienie wczytuje adresy, cookies i local storage, ale nie niezapisane formularze
ani pamięć JavaScript. Agent odczytuje nowe numery elementów.

**Przejmowanie przeglądania.** Gdy przeglądanie trwa, **Przejmij** w pasku przeglądarki
zatrzymuje agenta po bieżącym kroku i oddaje ci stronę, w tym samym oknie: klikaj, pisz,
przewijaj, wklejaj. **Oddaj** i agent kontynuuje od miejsca, w którym skończyłeś. Gdy
agent nie przejdzie strony sam - logowanie, captcha - przeglądarka mówi _Agent
cię potrzebuje_ i po co. Ktoś, kto może oglądać runy, ale nie edytować agenta, może
patrzeć, ale nie sterować. To samo okno otwiera się na osobnej stronie z linku z kanału.
Zobacz [Przeglądarka](reference/capabilities.md#browser-automation).

**Wskazywanie na stronie.** Przycisk z dymkiem w pasku przeglądarki pozwala kliknąć
miejsce na stronie i dopisać do niego notatkę - _ten przycisk, nie tamten_. **Add to
message** wkłada stronę do Twojej wiadomości jako obrazek z zaznaczonym miejscem, razem
z notatką i adresem strony, do wysłania albo dopisania reszty. Działa też po skończonym
przeglądaniu, na jego ostatnim obrazie.

**Zostajesz zalogowany.** Gdy przeglądanie działa w Twoim imieniu - Twój czat, Twoja
wiadomość prywatna, Twój własny harmonogram - **Oddaj** proponuje _Zapamiętaj moje
logowanie do_ strony, na której jesteś. Zaznacz to po zalogowaniu, a kolejne
przeglądania w Twoim imieniu startują tam zalogowane: ciasteczka i dane strony są
zapieczętowane w vault tylko dla Ciebie, nigdy nie są pokazywane i nie są używane dla
odwiedzającego widget, wspólnego kanału, klucza API ani wyzwalacza zdarzeń.
**Ustawienia → Logowania** pokazują zapamiętane strony, a **Zapomnij** sprawia, że
następne przeglądanie zaczyna się wylogowane. **Zaloguj się do strony** otwiera tam
przeglądarkę na dowolnej stronie tylko dla Ciebie, zanim agent będzie jej potrzebował:
zaloguj się, oddaj ją z zaznaczonym polem, a logowanie zostanie zapamiętane tak samo.
Wymaga przeglądarki wdrożenia do logowania
([`BROWSER_SIGN_IN_CDP_URL`](configuration.md)).

**Zatrzymanie oczekującego uruchomienia.** Przycisk **Stop** pozostaje dostępny, gdy
agent czeka na odpowiedź, zatwierdzenie lub połączenie konta. Działa również po
odświeżeniu strony z oczekującym pytaniem lub zatwierdzeniem. Zatrzymanie zamyka
oczekujące wywołania bez wznawiania modelu i zachowuje zapisany koszt. Możesz zatrzymać
własne uruchomienie; osoby uprawnione do zatwierdzania mogą też zatrzymać uruchomienie
oczekujące na zatwierdzenie. Jeśli tymczasowy błąd uniemożliwi zatrzymanie, karta
pozostaje dostępna do ponownej próby.

### Dyktowanie { #dictation }

Mikrofon stoi obok Wyślij przy każdym agencie, a także w menu `+`. Zamienia mowę
na tekst w polu i nigdy go nie wysyła: to, co powiesz, trafia tam, gdzie był
kursor, gdy nacisnąłeś mikrofon, gotowe do edycji, i nigdzie nie idzie, dopóki
nie naciśniesz Wyślij. Sposób transkrypcji wybiera agent, na zakładce Dyktowanie
[swojej karty Głos (Voice)](#an-agents-voice-card):

- **Transkrybuj u providera** włączone — przeglądarka nagrywa, a ten deployment
  wysyła nagranie do providera agenta albo do domyślnego providera organizacji.
  Działa w każdej przeglądarce, która potrafi nagrywać. Endpoint, jego limity i
  to, co jest zapisywane, opisuje [Dyktowanie w czacie](ml-services.md#dictation-in-chat).
- Wyłączone albo bez klucza, którym można wysłać — własne rozpoznawanie mowy
  przeglądarki, więc dźwięk trafia do jej dostawcy (Google, Apple) i nic nie
  kosztuje. Firefox go nie ma: jego mikrofon mówi o tym po naciśnięciu. Gdy
  przeglądarka słucha, notka nad kompozytorem mówi, że Dyktowanie agenta jest
  wyłączone, a temu, kto może edytować agenta, daje link do jego zakładki
  Dyktowanie.

Z providerem naciśnięcie mikrofonu wyświetla nad kompozytorem, który się nie
zmienia, **pigułkę nagrywania**: Anuluj, poziom, licznik czasu i Stop. **Enter**
zatrzymuje i transkrybuje, **Escape** anuluje, a nic, co wpiszesz albo naciśniesz
w trakcie nagrywania lub transkrypcji, nie zostaje wysłane. Nagranie zatrzymuje
się samo na najdłuższym dyktowaniu organizacji i jest transkrybowane, a mikrofon
odłączony w trakcie kończy je tak samo, zamiast je odrzucać. Gdy wysyłanie trwa
dłużej niż sekundę, pigułka pokazuje, ile już poszło; potem mówi
**Przepisywanie**, dopóki nie przyjdzie tekst. Rozpoznawanie w przeglądarce ma
własną pigułkę, z **Zakończ dyktowanie**.

Wszystko, co dyktowanie ma do powiedzenia, pojawia się w pasku nad kompozytorem,
obok pigułki: prośba o uprawnienia, zablokowany albo brakujący mikrofon, ostatnie
30 sekund, pięć sekund bez dźwięku, nagranie krótsze niż sekunda (nie wysłane),
nagranie zatrzymane na limicie i każda porażka. Ile słów wstawiono, słyszy
czytnik ekranu, ale nie jest to pokazywane, bo słowa są w polu. Nagranie, którego
nie udało się przetranskrybować, jest trzymane, dopóki nie naciśniesz **Ponów**
albo **Odrzuć**.

Poświata wokół pola na hostowanej stronie, gdy mówisz, idzie za ustawieniem **Animacja
dyktowania (Voice glow)** w **Ustawienia → Profil → Wygląd (Settings → Profile →
Appearance)**, obok motywu i ustawienia **Animacje (Motion)**: **Wyrazista
(Vivid)**, **Subtelna (Subtle)** (domyślnie) albo **Wyłączona (Off)**. Jest
zapamiętywana dla każdej przeglądarki. **Animacje** decydują, ile ruchu pokazuje
cała konsola: **Systemowe (System)** (domyślnie) idą za ustawieniem ograniczenia
ruchu w systemie operacyjnym, **Ograniczone (Reduce)** ograniczają ruch bez
niego, a **Pełne (Full)** zachowują ruch niezależnie od systemu operacyjnego. Gdy ruch jest ograniczony, nie ma żadnej poświaty, pasek
pojawia się bez wysuwania, a poziom dźwięku to pięciostopniowy wskaźnik.

**Kroki workflow** w tej samej karcie wybierają, jak kanwa workflow rysuje krok:
**W kolorze (In colour)** (domyślnie) rysuje każdy krok w barwie jego rodziny,
**Prosty (Simple)** zostawia kafelki neutralne, a minimapę szarą. Ustawienie jest
zapamiętywane dla każdej przeglądarki; ten sam przełącznik jest na pasku narzędzi
kanwy. Zobacz [Jak rysowany jest krok](workflows.md#how-a-step-is-drawn).

### Karta Głos (Voice) { #the-voice-card }

Na stronie **Członkowie (Members)** organizacji, dla kogoś z `org:settings`.
Trzyma **domyślny** speech-to-text, który dziedziczą agenty i boty kanałów, oraz
to, jak długo może trwać dyktowanie; to, czy agent dyktuje u providera albo
odbiera rozmowy, włącza się na jego własnej karcie Głos (Voice). **Maksymalna
długość nagrania** to od 10 sekund do 10 minut. **Domyślny provider** to provider
i model z katalogu speech-to-text oraz język (automatyczne rozpoznawanie albo
jeden stały język, co jest dokładniejsze). To także to, do czego
[boty kanałów](channels.md#what-every-channel-shares) ustawione na
dziedziczenie wysyłają swoje wiadomości głosowe; **Brak (None)** go czyści.

**Klucz**, obok providera, to klucz z vaulta, którym wysyłany jest domyślny
provider. Lista obejmuje klucze API, których przeznaczeniem jest ten provider i
które widzi cała organizacja - platforma wydaje ten klucz na dyktowanie każdego
członka i każdego dziedziczącego bota, więc prywatny klucz członka nie jest
oferowany i zostaje odrzucony, jeśli zostanie wysłany. Gdy jest dokładnie jeden
taki klucz, jest wybierany za ciebie i w każdym razie zapisywany po nazwie; nic
nie wybiera klucza w trakcie działania. Provider bez klucza jest oznaczony **brak
klucza dla tego providera**, a selektor prowadzi do vaulta, żeby go dodać. Gdy
domyślny provider nie może działać - model wycofano z katalogu albo klucz
usunięto lub uczyniono prywatnym - karta to mówi i prosi o **wybranie klucza**,
gdy brakuje właśnie jego.

Dla kogoś, kto ma też `runs:view`, karta zaczyna się jedną linią o tym, co
organizacja przetranskrybowała w ostatnich 30 dniach — „42 min · 118 nagrań (30
bez długości)” — w dyktowaniu, wiadomościach głosowych kanałów i API. **Pokaż
podział** rozbija to na agenty i boty kanałów. Minuty liczą tylko nagrania,
których długość została podana, więc linia mówi, ilu nie podano; jest ukryta,
dopóki nic nie przetranskrybowano. Liczby pochodzą z
[`GET /ml/calls/summary`](ml-services.md#what-is-recorded).

### Karta Głos (Voice) agenta { #an-agents-voice-card }

Zakładka **Build** agenta ma kartę **Głos (Voice)** po ustawieniach modelu, z
dwiema zakładkami: **Rozmowy głosowe** i **Dyktowanie**.

**Dyktowanie** trzyma **Transkrybuj u providera**. Włączone, mikrofon w czacie
wysyła nagranie do providera: **Własny tego agenta** (domyślnie) wybiera parę z
katalogu i klucz, którym ją wysłać - klucz API tego providera, który możesz
zobaczyć, bo publikacja pożycza go każdemu, kto może uruchomić agenta - a dopóki
go nie wybierzesz, używany jest domyślny provider organizacji, wskazany z nazwy.
**Organizacji** zostawia providera, model i klucz organizacji. Wyłączone albo bez
klucza, którym można wysłać, transkrybuje przeglądarka, co nic nie kosztuje.

Język wybiera się osobno: dziedziczony z organizacji albo stały - więc polski
agent może zachować providera i klucz organizacji. Karta jest częścią spec,
zapisywana z wersją roboczą i aktywna po publikacji agenta, a dotyczy
[dyktowania](#dictation) do tego agenta i wiadomości głosowych, które dziedziczą
jego boty kanałów. Resztę opisuje
[kolejność](ml-services.md#which-engine-a-recording-reaches).

### Rozmowy głosowe { #voice-calls }

[Rozmowa głosowa](voice.md) to mówiona rozmowa z opublikowanym agentem: mówisz,
on odpowiada na głos, a ty możesz mu przerwać. Rozmowy włącza się w agencie;
organizacja nie ma ustawień rozmów.

- **Karta Głos (Voice) agenta**, na zakładce **Rozmowy głosowe**: provider i
  model rozmowy (dla Azure nazwa deploymentu i jego model bazowy), klucz, głos z
  przyciskiem **odtwarzania**, żeby go usłyszeć, język mówiony (albo **Za
  rozmówcą**), **Najdłuższa rozmowa** (10 minut, gdy nieustawiona, najwyżej 50)
  oraz **Instrukcje dla rozmów**. Karta wymienia, co agent
  [przekazuje swojemu modelowi tekstowemu](voice.md#handing-work-off) w
  rozmowach, mówi, że guardrails nie mogą odfiltrować wypowiedzianych słów, zanim
  zostaną usłyszane, i że rozmowy są zapisywane jako tekst, bez zachowywania
  dźwięku. Zaczyna działać po publikacji agenta.
- **Przełącznik Rozmowy głosowe embeda**, w formularzach widżetu i hostowanej
  strony - zobacz [Kanały](channels.md#voice-calls-on-a-widget-or-a-hosted-page).

Zanim zaproponuje rozmowę, konsola pyta, czy ten agent może ją odebrać
(`GET /agents/{id}/voice`), żeby nikt nie udzielał dostępu do mikrofonu tylko po
to, by zostać odrzuconym. Odpowiedź mówi, czego brakuje: głosu ustawionego w
agencie, modelu, który nadal jest oferowany, albo klucza.

**Przycisk rozmowy** stoi w kompozytorze czatu w miejscu „Wyślij”, dopóki pole
jest puste - po wpisaniu czegoś wraca „Wyślij” - przy każdym
agencie. Gdy ten agent nie może odebrać rozmowy, przycisk jest przekreślony, a
najechanie, fokus albo naciśnięcie mówi dlaczego. Ktoś, kto może edytować
agenta, dostaje **Otwórz w Agent Builderze**, co otwiera jego kartę Głos (Voice)
na zakładce Rozmowy; każdy inny słyszy, żeby poprosił kogoś, kto może.

W trakcie rozmowy nad kompozytorem, który zostaje taki, jaki był, razem z wersją
roboczą i załącznikami, unosi się **pigułka**: co robi rozmowa, jej czas, fala
dźwięku obu głosów, push-to-talk, wyciszenie i **Zakończ rozmowę**. Rozmowę kończy tylko
Zakończ rozmowę; otwarcie innej konwersacji albo nowego czatu ją rozłącza. Domyślnie
mówi się bez trzymania przycisku; **push-to-talk** (przytrzymaj przycisk albo
Spację) to wybór zapamiętywany w przeglądarce. Przy ograniczonym ruchu falę
zastępuje schodkowy miernik poziomu.

Rozmowa przechodzi przez stany, które nazywa pigułka: łączenie, słuchanie, ty
mówisz, myślenie, agent mówi, przerwanie, praca nad narzędziem, czekanie na twoje
zatwierdzenie, zatwierdzenie, którego nie możesz udzielić, prawie koniec czasu i
zakończenie - przez ciebie, przez limit, zerwane połączenie albo awarię.

Rozmowa toczy się w konwersacji: każda tura jest rysowana jako wiadomość, którą
się stanie, rośnie słowo po słowie w miarę mówienia, czytnik ekranu słyszy każdą
linię, gdy jest ostateczna, a zapisana wiadomość zajmuje jej miejsce bez
żadnego przesunięcia, więc rozmowa zostaje potem w historii i możesz dalej
pisać. Gdy agent myśli albo uruchamia narzędzie, konwersacja mówi o tym tam,
gdzie pojawi się jego odpowiedź.

**Zatwierdzenia** zapadają w rozmowie: karta w konwersacji pokazuje narzędzie,
jego dokładne argumenty i to, co usłyszano, że powiedziałeś, z odliczaniem 60
sekund. Decydują tylko jej przyciski; powiedzenie „tak” niczego nie zatwierdza.
Bez `approvals:decide` karta mówi, że narzędzie wymaga zatwierdzenia, którego
nie możesz udzielić głosem, i proponuje zakończyć rozmowę i kontynuować pisemnie.
**Pytania**, które zadaje agent, pojawiają się jako karta pytania czatu, także
czytana na głos: stuknij odpowiedź albo po prostu ją powiedz. Praca, którą agent
[przekazuje swojemu modelowi tekstowemu](voice.md#handing-work-off), pokazuje
każdy krok w trakcie, a kroki zostają potem na turze. **Limity** są mówione:
minutę przed końcem najdłuższej rozmowy dostajesz ostrzeżenie, a gdy skończy się
czas albo budżet, agent mówi jedno zdanie i rozmowa się kończy.

**Pasek nad kompozytorem** wskazuje to, co wymaga twojej uwagi: prośbę o
mikrofon, czekające zatwierdzenie (z **Pokaż kartę**), ostatnią minutę, limit
kończący rozmowę, ponowne łączenie albo to, jak działa push-to-talk. Gdy rozmowa
się kończy, karta w konwersacji mówi, jak długo trwała i ile tur zapisano, albo
jaki limit ją zakończył, z przyciskiem **Zadzwoń ponownie**. Rozmowa, która w
ogóle się nie zaczęła, mówi dlaczego nad kompozytorem, z **Spróbuj ponownie**.

W **Aktywności (Activity)** rozmowa to jeden wiersz z plakietką mikrofonu, a
filtr rodzaju (**Tekst** albo **Rozmowy głosowe**) zawęża do rozmów; rozmowa,
która się ponownie połączyła, to nadal jeden wiersz, z czasem i kosztem
wszystkich połączeń zsumowanymi. Karta pulpitu **Minuty rozmów (Voice minutes)**,
w pasie Użycie dla posiadacza `runs:view`, pokazuje minuty i liczbę rozmów w
okresie oraz trzech najczęstszych agentów.

### Rozgałęzianie rozmowy { #forking }

Aby spróbować innego podejścia albo zająć się pobocznym pytaniem tam, gdzie nie zaśmieci głównego wątku, wybierz **Rozgałęź do nowej rozmowy** pod jedną z odpowiedzi agenta. Dostajesz nową, własną rozmowę w tym samym projekcie, z całą historią aż do tej odpowiedzi włącznie. Następna wiadomość kontynuuje od tego miejsca z tą samą historią; oryginał się nie zmienia.

Rozgałęzić rozmowę może tylko jej właściciel: osoba, której ją udostępniono do podglądu lub edycji, nie ma tej akcji. Rozgałęzienie kopiuje wiadomości i wywołania narzędzi, ale nie pliki załączników, pliki zapisane przez agenta w workspace, obrazy wygenerowane przez agentów, koszt ani rekordy runów. Agent nadal zna tekst załącznika, ale rozgałęzienie nie pokazuje jego karty; obraz wygenerowany przez agenta należy do oryginału i przestaje się wczytywać, gdy oryginał zostanie usunięty. Dopóki run w tej historii wciąż pisze albo czeka na zatwierdzenie lub odpowiedź na pytanie, rozmowy nie da się rozgałęzić.

Na górze rozgałęzienia widać **Rozgałęzienie rozmowy** z linkiem do oryginału. Tę linię widzisz tylko ty: jeśli udostępnisz rozgałęzienie, odbiorca zobaczy zwykłą rozmowę.

Rozgałęzienie może obejmować najwyżej 2000 wiadomości, 10 000 wywołań narzędzi i 20 MiB kopiowanego tekstu oraz danych strukturalnych. Limit wynosi dziesięć żądań na minutę na członka i organizację. Aktualizowana rozmowa może chwilowo odmówić rozgałęzienia; spróbuj ponownie po zakończeniu aktualizacji. Historię przekraczającą limit trzeba skrócić przed skopiowaniem.

Zachowane rozgałęzienia mają osobny limit 100 MiB na członka w organizacji i 1 GiB na całą organizację. Kopia rezerwuje rozmiar treści oraz 4 KiB na rozmowę i 1 KiB na wiadomość lub wywołanie narzędzia. PostgreSQL szereguje przyjmowanie kopii, więc równoległe żądania nie przekraczają limitu. Przydział zwalnia dopiero usunięcie samej kopii; usunięcie źródła lub archiwizacja go nie zwalnia. Rysunku z zapisanymi plikami obrazów nie można obecnie rozgałęzić. Wybierz wcześniejszą odpowiedź; żądanie jest odrzucane przed utworzeniem uszkodzonej kopii.

Tekst i media zapisane poza bazą w kopiowanym podsumowaniu są odtwarzane w rozgałęzieniu, więc usunięcie oryginału nie usuwa tego kontekstu. Odtworzona treść wlicza się do limitu 20 MiB. Odtwarzanie obejmuje najwyżej 100 odwołań i trwa do dziesięciu sekund. Niedostępna treść lub przekroczenie limitu przerywa operację bez tworzenia częściowej kopii.

Rozmowę z zapisaną checklistą można rozgałęzić tylko przy jej najnowszej wiadomości, jeśli jest odpowiedzią agenta. Kopia zachowuje checklistę, w tym identyfikatory zadań i zależności. Wcześniejsze wersje checklisty nie są przechowywane, dlatego wcześniejsze rozgałęzienie jest odrzucane, aby nie kopiować późniejszych zadań do starszej historii.

### Tematy w tle { #background-topics }

Włącz **Tematy w tle** u opublikowanego agenta i poproś np.: „Zbadaj błąd eksportu w nowym temacie, a my kontynuujmy plan wydania” albo „Niech agent finansowy sprawdzi te liczby, gdy omawiamy ofertę”. Agent może użyć swojej przypiętej wersji albo opublikowanego delegata przypiętego w specyfikacji. Zacznij z rozmowy, której jesteś właścicielem; nowy temat należy do tego samego projektu i zawiera brief agenta oraz odnośnik do źródła, bez kopiowania pierwotnego transkryptu.

Pasek **Tematy w tle** nad polem wiadomości pokazuje zadania w kolejce, pracujące i oczekujące. Otwórz osobny temat, aby sprawdzić pracę lub odpowiedzieć na zwykłą prośbę o zgodę albo pytanie. **Zatrzymaj** anuluje dalszą pracę; nie cofa wykonanych zmian plików ani działań w usługach. Te same zadania znajdziesz na pulpicie. Jedna osoba może mieć do czterech aktywnych zadań; zadanie i odpowiedź z jego wynikiem nie mogą tworzyć kolejnych tematów w tle.

Po zakończeniu zadania pierwotny agent budzi się, korzystając z aktualnej historii rozmowy. Czeka na koniec odpowiedzi dla użytkownika i podsumowuje bez narzędzi, aby wynik zadania nie stał się zgodą na kolejne działanie. Zachowuje wybrany model główny i ustawienie myślenia; lokalne wnioskowanie pozostaje lokalne. Lokalna praca kodująca pozostaje na konkretnym sparowanym komputerze i w zatwierdzonym folderze. Dziecko zachowuje zwykłe budżety i zgody. Zamknięcie czatu go nie anuluje. Przerwanie workera jest raportowane, a działania zewnętrzne nie są automatycznie powtarzane. Zadanie czekające na zgodę kontynuuje po jej udzieleniu; utrata członkostwa lub dostępu do projektu zatrzymuje nową pracę i przekazanie wyniku.

To jawna delegacja, oddzielona od pamięci, watchów i rutyn. Istniejące tryby asynchroniczne subagentów i narzędzi nadal należą do jednego uruchomienia; do pracy dłuższej niż odpowiedź źródłowa użyj **Tematów w tle**.

### Odwołanie do innej rozmowy { #conversation-references }

Agent z funkcją **Poprzednie rozmowy** oferuje w menu `@` trzydzieści najnowszych rozmów, do których masz dostęp. Wybierz rozmowę i zadaj konkretne pytanie. Wzmianka wskazuje temat; nie kopiuje transkryptu ani nie zmienia odpowiadającego agenta. Agent czyta odpowiedni fragment przez istniejące narzędzie rozmów, z tymi samymi kontrolami dostępu i odbiorców. Ograniczenia czatów grupowych nadal obowiązują. Przy starszym temacie wklej odnośnik lub identyfikator i poproś agenta o przeczytanie.

## Aktywność { #activity }

**Aktywność** (Activity) wymienia każdy run w organizacji osobie z `runs:view`:
rozmowy, agentów organizacji odpowiadających na przypadki ewaluacji i agentów
platformy przy ich własnej pracy. To, kto może przeczytać run i jego zapis, nie
zależy od rodzaju runa.

Run agenta platformy pokazuje jego nazwę w kolumnie Agent i etykietę obok
powierzchni: **Improve** dla asystenta, **Oceniający** dla sędziego, **Luki w
wiedzy** dla klasyfikatora i autora szkiców oraz **Pytania testowe** dla
generatora przypadków. Agent odpowiadający na przypadek ewaluacji ma etykietę
**Ewaluacja**. Obok etykiety jest link do miejsca, gdzie tę pracę się czyta:
sesji Improve, ewaluacji, tematu luki w wiedzy albo datasetu.

Filtr **Pochodzenie** zawęża listę do **Rozmów**, **Improve i ewaluacji** albo
**Agentów systemowych**. Domyślnie obejmuje każde pochodzenie, więc link ze
szkicu albo z sesji do jej runa trafia na wiersz, który lista pokazuje.

## Do czego służy każdy obszar { #what-each-area-is-for }

**Overview** (Dashboard), **Chat** i **Inbox** są na początku sidebara.
**Build & manage** pokazuje Agents, Workflows, Routines i Apps bez rozwijania;
następne są Projects.

**Knowledge** jest domyślnie rozwinięte i zawiera Knowledge bases, Tables, Skills,
Context i Documents. Ręczny wybór rozwinięcia lub zwinięcia jest zapamiętywany.
**Monitoring** grupuje Activity i Background work i jest domyślnie zwinięte.

**Connections** (MCP servers, Channels, Remote agents, Vault, Sandboxes) i
**Organization** (Organizations, Groups) pozostają zwijane i zapamiętują wybór.
Grupa zawierająca bieżącą stronę zawsze się otwiera, aby ta strona była widoczna.

| Obszar | Zawiera | Przeczytaj |
| --- | --- | --- |
| **Agents** | Katalog, Builder, wersje, udostępnianie, testowanie, aktywność | [Twój pierwszy agent](first-agent.md) |
| **Chat** | Rozmowa z opublikowanym agentem | [Powierzchnie](channels.md) |
| **Knowledge** | Kolekcje, dokumenty, źródła synchronizacji, ustawienia ingestii | [Przetwarzanie plików](file-processing.md) |
| **Skills** | Spisane procedury, które agent wczytuje na żądanie | [Skille](skills.md) |
| **Context** | Stała wiedza przypięta do wielu agentów | [Pliki kontekstowe](context.md) |
| **Tables** | Typowane rekordy i ich kolumny, oglądane jako tabela, tablica kanban lub lista | [Virtual Tables](virtual-tables.md) |
| **Workflows** | Wieloetapowe automatyzacje, które uruchamiają Twoje agenty, budowane na kanwie | [Workflows](workflows.md) |
| **Datasets** | Wersjonowane przypadki testowe, importowane, eksportowane albo dodawane z ocenionej odpowiedzi | [Datasety](datasets.md) |
| **Routines** | Harmonogramy i wyzwalacze zdarzeń | [Wyzwalacze](triggers.md) |
| **Runs** | Co się uruchomiło, ile kosztowało, czego dotknęło, czy zakończyło się błędem | [Nadzór](governance.md#audit) |
| **Documents** | Wszystkie pliki, które agenci trzymają dla ciebie: to, co załączyłeś, i to, co napisali | [Sandbox](sandbox.md#what-the-file-browser-shows-and-what-it-leaves-out) |
| **Sandboxes** | Gdzie agenci uruchamiają kod: hosty, żywe sesje, polityka | [Sandbox](sandbox.md) |
| **MCP servers** | Połączenia z zewnętrznymi narzędziami, osobiste i na całą organizację | [MCP](mcp.md) |
| **Channels** | Boty Slacka, Teams, Telegrama i Mattermosta, widgety, hostowane strony | [Powierzchnie](channels.md) |
| **Remote agents** | Agenci innych dostawców, zarejestrowani po ich agent card A2A, do których delegują agenci | [Capabilities](reference/capabilities.md#remote-agents) |
| **Vault** | Poświadczenia, zapieczętowane per organizacja | [Sekrety](secrets.md) |
| **Organizations** | Członkowie, role, zaproszenia | [Uprawnienia](permissions.md) |
| **Settings** | Providerzy, domyślne ustawienia ingestii, powiadomienia, twój własny profil | [Konfiguracja](configuration.md) |
| **Admin** | Sam deployment: użytkownicy, najemcy, system, zadania w tle, ustawienia deploymentu | [Deployment](deployment.md) |

Katalog **Agents** można filtrować po **category** i **tag** — edytowalnych,
lokalnych dla organizacji etykietach pokazywanych na karcie każdego agenta.
Każdy filtr to menu etykiet z agentów, które widzisz; zaznacz kilka, żeby go
poszerzyć.
Kategorie i tagi agenta utrzymujesz na jego stronie szczegółów, obok kontrolek
avatara, a zmiana działa od razu, bez publikowania nowej wersji.

Zakładka **Historia** agenta zawiera jego opublikowane wersje i nazwane
środowiska, a dla każdego, kto może czytać jego runy, także **Historię usprawnień**:
każdą sesję Popraw, co zmierzyła, co postanowiono i ile kosztowała. Zakończona
sesja otwiera kreator tylko do odczytu, z decyzją w ostatnim kroku; zobacz
[Historię usprawnień](authoring.md#improvement-history).

Szczegóły organizacji mają pięć zakładek: **Członkowie** obejmują osoby i zaproszenia; **Organizacja** — profil i domyślne ustawienia głosu; **Budżet i zgody** — wydatki i zasady dostępu; **Proaktywność** — sugestie, monitoring i dostarczanie wyników; **AI i usługi** — Architecta i usługi systemowe. Każdy formularz zachowuje własne wymagania uprawnień. AI i usługi jest dostępne dla zarządzających budżetem także bez prawa konfiguracji Architecta. Wybrana zakładka jest zapisywana w URL, przełączanie zachowuje wersje robocze, a dawne linki `?tab=voice` otwierają Organizację.

Po zalogowaniu zaproszenia wysłane na e-mail konta pojawiają się także w konsoli i onboardingu, bez otwierania linku z wiadomości. Odbiorca wybiera organizację i jawnie przyjmuje zaproszenie; Później zostawia dostępny skrót Zaproszenia. Lista zawiera tylko aktualne zaproszenia na bieżący adres konta, bez linków współdzielonych i organizacji, do których użytkownik już należy. Przyjęcie przełącza organizację i otwiera jej powitanie. Serwer nie zwraca tokenu zaproszenia w tej skrzynce.

Skrzynka wymaga potwierdzenia adresu w bieżącej sesji: świeżego logowania przez OAuth ze zweryfikowanym e-mailem lub linku do logowania wysłanego na konkretny adres. Sesje po zalogowaniu hasłem i starsze sesje nie wyświetlają ponaglenia do potwierdzenia skrzynki ani konfiguracji wysyłki e-maili. Zaproszenie można przyjąć przez oryginalny link, także we wdrożeniu bez dostawcy poczty. Potwierdzenie nie przechodzi do innej sesji ani na zmieniony adres. Lista ma stronicowanie przez **Pokaż kolejne zaproszenia**, a dostęp do logo sprawdza konkretne zaproszenie niezależnie od strony listy.

Bursztynowe kropki oznaczają zakładki organizacji i odpowiadające im karty głosu, nocnych sugestii, utrzymania pamięci oraz Architecta, gdy brakuje konfiguracji lub sugestie są wyłączone. Najedź na kropkę lub ustaw na niej fokus, aby przeczytać wyjaśnienie; kliknij lub dotknij, aby je otworzyć. Wskaźniki korzystają z zapisanych ustawień, znikają po uzupełnieniu konfiguracji i respektują uprawnienia do jej zmiany. Wyłączone sugestie są opcją do uruchomienia, a nie błędem. Karta powiadomień iPhone oznacza też brak klucza Apple. Ograniczenie ruchu wyłącza pulsowanie.

Zapisane logowania do stron mają zwarty panel ustawień na pełną szerokość, zamiast rozciągać jeden wpis na całą stronę. Znane usługi pokazują wbudowane logo marki; pozostałe strony korzystają z własnej favicony bez przesyłania odsyłacza, a gdy obraz jest niedostępny — z ikony globu.

## Języki { #languages }

Konsola mówi po angielsku, polsku, niemiecku i turecku. Pierwsza karta
przewodnika proponuje te cztery
języki, a menu konta zmienia język w każdej chwili; wybór jest zapisywany na twoim
koncie, więc konsola otwiera się w nim na każdym urządzeniu, na którym się
logujesz. Możesz też poprosić agenta - "przełącz na angielski" - a strona zmieni
się, gdy odpowie, bez przeładowania. Każdy agent odpowiada w nim, chyba że
napiszesz w innym języku. Słowa produktu - agent, skill, run, budget, MCP i reszta listy z
[tłumaczenia](howto/translate.md) - zostają angielskie w każdym języku.

Ta sama karta pyta, czym się zajmujesz, a **Ustawienia → Profil (Settings →
Profile)** trzymają resztę tego, co agenci o tobie wiedzą: twoją rolę, nad czym
pracujesz i twoją strefę czasową. Każdy agent czyta je na początku runu, więc
nigdy nie powtarzasz ich w czacie; „w każdy poniedziałek o 9” to twoja 9. Strefa
czasowa jest brana z przeglądarki przy pierwszym logowaniu, dopóki nie wybierzesz
własnej.

Ustawienia profilu łączą avatar, nazwę i e-mail w jednym formularzu, z kolorami
zastępczymi pod rozwinięciem. Zapis jest pod polami, a Enter wysyła formularz
nazwy lub roli. Podczas zapisu profilu pola danych i kontekstu są zablokowane;
odmowa zachowuje formularz. Dni pracy mają większe pola dotyku, a godziny
początku i końca są osobnymi polami także na telefonie.

**Ustawienia → Powiadomienia** wyszukują nazwy i opisy zdarzeń, po sześć na
stronie. Selektor czatu zmienia dodatkowy kanał bez zmiany pozostałych preferencji.
Połączone miejsca powiadomień w prywatnych czatach są pierwsze; pozostałe platformy
są pod rozwinięciem. Błędy odczytu preferencji, miejsc lub połączonych kont mają
przycisk ponowienia zamiast pozornych wartości domyślnych lub pustej listy kont.

## Następny krok { #the-next-step }

Strona pusta dlatego, że nic jeszcze nie istnieje, proponuje, jak zrobić pierwszą
rzecz - agenta, rutynę, coś udostępnionego działowi. Utworzenie skilla, pliku
kontekstu albo bazy wiedzy kończy się toastem z **Add to an agent** dla każdego,
kto może edytować agentów, więc to, co powstało, trafia do agenta bez wycieczki do
Buildera.

## Kiedy strona wygląda na pustą { #when-a-page-looks-empty }

**Pusty stan i nieudane żądanie wyglądają tak samo.** Każda strona tutaj rozsyła
kilka zapytań i renderuje "nic jeszcze nie ma", gdy jedno z nich się nie powiedzie.

Więc zanim uznasz, że kolekcja jest pusta albo że agent nie ma żadnych runów,
sprawdź zakładkę sieci. To zdecydowanie najczęstszy sposób, w jaki prawdziwy
problem zostaje odczytany jako cisza.

## Podsumowanie { #recap }

- Dashboard to **pięćdziesiąt siedem widgetów**, które układasz sam, zapisywanych
  per osoba i per organizacja — wszystkie poza twoimi własnymi powiadomieniami
  bramkowane uprawnieniem, którego wymagają ich dane.
- Zapisany układ **może ukrywać i zmieniać kolejność, ale nigdy nie odsłania** —
  bramka działa na końcu.
- **Dzwonek** to bieżący licznik nieprzeczytanych, z pełną listą o jedno
  kliknięcie, niezależnie od tego, na której stronie akurat jesteś.
- **Chat, Slack i API to ten sam runner**, więc to, co widzisz w konsoli, jest
  tym, co dostaje klient.
- **Zmiany wprowadzone gdzie indziej docierają same** — przez API, MCP albo
  asystenta — a Builder pyta, zanim zastąpi niezapisane zmiany.
- **Slash commands są twoje**, łącznie z wbudowanymi, a te, z których nie
  korzystasz, możesz ukryć.
- Strona pokazująca "nic jeszcze nie ma" może być **nieudanym żądaniem**, a nie
  pustym zasobem.

Stopka panelu bocznego pokazuje wersję kompilacji konsoli obok wyszukiwania i powiadomień, także w zwiniętym panelu i menu mobilnym. Numer pochodzi z wersji pakietu frontendu zapisanej w kompilacji, więc jego odczyt nie wymaga żądania sieciowego. Podpowiedź określa go jako wersję konsoli; osobno aktualizowany proces API może mieć inną wersję.

Nowsze stabilne wydanie AgenticOS podświetla ten numer i dodaje zieloną kropkę. Kliknięcie pokazuje uruchomioną i dostępną wersję oraz odnośnik do oficjalnego wydania. Sprawdzenie w tle odbywa się przy otwarciu konsoli, co 30 minut podczas pracy oraz po odzyskaniu fokusu lub połączenia, jeśli dane są nieaktualne. Serwer współdzieli wyniki publicznych sprawdzeń przez pięć minut i nie wysyła do GitHuba danych konta, organizacji ani wdrożenia. Awaria sieci pozostawia numer uruchomionej wersji bez stwierdzenia, że jest najnowsza. Powiadomienie nie przeładowuje strony ani nie instaluje aktualizacji automatycznie.

Po zalogowaniu **Co nowego** pokazuje publiczne informacje o zainstalowanej wersji z GitHub Releases, raz dla konta na tym urządzeniu. Okno czeka na zamknięcie onboardingu. Zamknięcie oznacza wersję jako przeczytaną; brak opisu lub błąd pobierania nie przerywa sesji. Funkcje nowszej, niezainstalowanej wersji są dostępne tylko z informacji o aktualizacji. Sekcje **Upgrading** i **Notes for operators**, z migracjami i krokami aktualizacji, widzą tylko administratorzy wdrożenia; wydanie, które nie zawiera nic poza nimi, nie otwiera okna nikomu innemu.

Chat controls zapamiętuje model, tryb zatwierdzania i lokalne narzędzia dla konta i organizacji między chatami. Ustawienia plików projektu mają pierwszeństwo. Zgoda na cały komputer dotyczy jednej rozmowy albo jednego agenta, gdy ten agent pracuje na Twoim komputerze. Pomijanie zatwierdzeń wymaga bieżących uprawnień i zgody organizacji. Agent setting (lub Cloud dla plików) jest nieaktywne, jeśli opublikowany agent nie ma tej funkcji; lokalna opcja nie włącza się sama. Kliknięcie wybranej lokalnej opcji wyłącza ją.

Wyciszanie powiadomień ma ikonę dzwonka; pole wiadomości nie powtarza już plakietki folderu i dostępu. Avatary wielu agentów zachodzą na siebie bez zmiany rozmiaru, a w rozwiniętej liście delikatnie rozsuwają się po najechaniu.

Stopki list pozostają przy dolnej krawędzi panelu, ze spójnymi odstępami i kryjącym tłem. Stronicowane tabele administracyjne przewijają same wiersze, zachowując widoczne nagłówki kolumn i paginację. Puste wyniki i błędy pozostają w tym samym obszarze przewijania.

Lista organizacji w administracji pokazuje wgrane zdjęcie albo inicjały w wybranym kolorze, jeśli zdjęcia nie ustawiono. Dostęp do obrazów w tym widoku mają tylko administratorzy wdrożenia; zwykły endpoint avatarów organizacji nadal wymaga członkostwa.

**Chat controls → Tools & files** pokazuje konto coding, którego agent potrzebuje, gdy jego Coding agent działa jako **Private cloud task with my account**: tylko ten harness, z logotypem i stanem zgody. Możesz je podłączyć lub nim zarządzać bez wychodzenia z chatu; wszystkie konta są w **Settings → Profile**. Podłączenie nie zmienia trybu wykonania agenta: prywatne zadania w chmurze nadal wymagają **Private cloud task with my account**, a coding na desktopie korzysta z osobnego lokalnego logowania.

## Pierwsze zadanie { #your-first-task }

W nowym workspace domyślnie wybrany jest dostarczony **AgenticOS**, również przed publikacją, chyba że wybierzesz innego domyślnego agenta. Po pierwszej wiadomości może wyjaśnić konfigurację modelu i pokazać kartę ustawień bez wykonywania draftu ani wywoływania dostawcy AI. Odpowiedź i karta pozostają w historii czatu. Osoby z uprawnieniami konfiguracji otwierają ustawienia modelu agenta; pozostali członkowie widzą wskazówkę dotyczącą administratora i kontakt wsparcia instancji, jeśli został podany. Wybierz model, dodaj klucz, jeśli jest wymagany, i opublikuj agenta, aby uruchomić zwykłe odpowiedzi AI. Zwykłe drafty i zarchiwizowani agenci nadal nie mogą być wykonywani.

Gdy nie ma dostępnego opublikowanego agenta, onboarding pozwala też otworzyć rozmowę konfiguracyjną z dostępnym draftem dostarczonego AgenticOS. Członek organizacji nie potrzebuje do tego uprawnień do modeli; otrzymuje wskazówki konfiguracyjne, a nie wynik zadania AI. Niedostępne drafty pozostają zablokowane, a dostępny opublikowany agent ma pierwszeństwo.

Zamknięcie banera startowego lub wybranie **Ukryj na 24 godziny** wycisza propozycję na 24
godziny według czasu serwera. Potem może wrócić, jeśli konfiguracja nie została ukończona,
a workspace nadal wymaga pierwszego startu. Po przejściu pytań **Zakończ konfigurację i
otwórz aplikację** zapisuje ukończenie dla tego członkostwa. Opcjonalne pola, zaproszenia,
model, agent ani run AI nie są wymagane. Ukończenie onboardingu i udane zadanie to osobne
stany.

Otwórz **Pierwsze kroki** z dashboardu, propozycji przy pierwszym użyciu lub pomocy
strony. Na desktopie baner startowy czatu jest półprzezroczystą nakładką nad konsolą.
Oba panele nawigacji zachowują pełną wysokość. Administratorowi proponuje konfigurację, a członkowi
przykład; można go zamknąć. Przyjęte zaproszenie otwiera ten sam start w organizacji, do której
właśnie dołączasz. Rejestracja próbuje od razu zalogować konto; gdy sesja się nie
powiedzie, formularz logowania zachowuje cel i już utworzone konto.

Start uwzględnia uprawnienia osoby i jej dotychczasową pracę:

| Osoba | Prowadzony start |
| --- | --- |
| Administrator aplikacji | Utworzenie lub wybór firmy, tożsamość i zaproszenia, następnie zasady dołączania przyszłych kont. |
| Administrator organizacji | Przygotowanie workspace’u i jego limitu wydatków, bez ustawień wdrożenia. |
| Nowe konto członka | Powitanie, opcjonalny profil osobisty i kontekst pracy, potem pierwsze zadanie. |
| Istniejące konto dołączające do kolejnej organizacji | Powitanie w tym workspace, użycie zapisanego profilu lub jego świadomy przegląd. |

Przewodnik AgenticOS objaśnia każdą decyzję przygotowanymi wiadomościami interfejsu.
Nie są odpowiedziami modelu i nie wywołują AI. Profil i kontekst pracy są wspólne dla
workspace’ów konta. Dane opcjonalne można pominąć. **Zapisz i kontynuuj** prowadzi
dalej po udanym zapisie; błąd zapisu pozostawia bieżące pytanie.

Konfiguracja wdrożenia pyta o rejestrację, miejsce startu przyszłych kont i opcjonalny
komunikat z podglądem. Wysyła tylko zmienione pola. **Zachowaj obecne ustawienia**
odrzuca szkic tego pytania bez zapisu. Wybór firmy zachowuje skonfigurowaną rolę
domyślną i nie przenosi istniejących kont. Wygląd aplikacji, głos, dane push iOS oraz
konserwacja są opcjonalnymi kartami otwierającymi odpowiednią sekcję administratora
w nowej karcie. Kreator nie włącza automatycznie konserwacji ani nie dodaje kluczy.

Organizacja dostaje propozycje budżetu i suwak. Istniejący
limit z częścią dziesiętną pozostaje zachowany. Brak limitu jest osobnym wyborem,
a zero ostrzega o możliwej blokadzie runów. To limit rejestrowanego zużycia, nie
abonament ani doładowanie. Zaawansowane zatwierdzenia, asystenci i głos pozostają
zwinięte oraz zachowują swoje uprawnienia i sposób zapisu.

Adres URL zachowuje krok, pytanie konfiguracji i workspace po odświeżeniu. Nie przechowuje
niezapisanych zmian, nie nadaje dostępu i nie oznacza ukończenia. Zmiana organizacji
lub odebranie uprawnień uniemożliwiają wznowienie uprzywilejowanego kroku. Zakończenie
ostatniego etapu zapisuje ukończenie na członkostwie także przy pominięciu pól i AI.

Dawne ukończenie na koncie dotyczy członkostw istniejących do tego czasu. Późniejsze
członkostwo ma osobny start. Własne rozmowy i ukończone przewodniki nadal chronią
przed automatycznym powtarzaniem, a opublikowani agenci ukrywają zwykłe propozycje
startu. Linki po rejestracji i przyjęciu zaproszenia pokazują powitanie osobie bez
własnej aktywności lub ukończenia także w organizacji z gotowymi agentami. Starsze
i nieudane rozmowy liczą się jako aktywność bez udawania udanego runu. Ręczny start
i wznowienie pozostają dostępne. Zwykłe logowanie otwiera chat lub żądany odnośnik.

Nazwa workspace aktualizuje oznaczony podgląd przed utworzeniem. Istniejące organizacje
pokazują wgrane logo albo ustawiony awatar zastępczy. Sąsiednie karty na desktopie
mają równą wysokość. Przejścia i podświetlenia pól respektują ustawienia ruchu. Członkowie wybierają
zapisany przykład w widoku z osobnymi zakładkami odpowiedzi i materiału. Zmiana
przykładu pozostawia podgląd na stronie. Konfiguracja AI otwiera zamykane okno
z obsługą Escape i przywracaniem fokusu. Wybór przykładu nie wywołuje modelu.

Wybierz fikcyjną notatkę, pytanie o politykę albo porównanie ofert. Przejrzyj lub
zmień tekst przed **Uruchom zadanie**. Wykonanie korzysta z modelu agenta i zwykłych
limitów wydatków; może wiązać się z opłatą dostawcy. Te przykłady tekstowe nie
wymagają ekranu, mikrofonu, sandboxu ani zewnętrznego konta.

Podgląd przykładu pozostaje dostępny bez agenta. Nie wywołuje
modelu, nie przetwarza zmian i nie liczy się jako udane wykonanie. Uprawniony
builder może przygotować wspólnego asystenta tekstowego na świadomie wybranym
wspólnym modelu. Jego miesięczny limit to 5 USD w ramach budżetu przestrzeni.
Przygotowanie nie zmienia szkicu istniejącego agenta; do jego zmiany służy
Builder. Osoba bez tych praw widzi kontakt do właściciela.

Wybór przykładu i pominięcie są zapisane na członkostwie, także dla innego
urządzenia. Start prowadzi też do ostatniej zakończonej własnej rozmowy webowej.
Zakończony run dowodzi wykonania, nie oceny przydatności. Wycieczki są opcjonalną
pomocą; ich zamknięcie nie tworzy udanego wykonania. Integracje, pliki, budowanie
agentów, zaproszenia i rutyny są opcjonalnymi kolejnymi krokami.

Osoby zarządzające członkami mogą sprawdzić, czy wraz z wybranym członkiem mogą uruchomić wspólnego opublikowanego agenta. Podgląd zwraca tylko tę informację, bez nazw prywatnych agentów i bez wywołania modelu. Nie potwierdza dostępności dostawcy. Centrum startu blokuje zaproszenia z adresu lokalnego komputera; potrzebny jest adres serwera osiągalny dla odbiorcy.

Zakończone tury chatu pokazują tekst przekazany przed pytaniem agenta obok końcowej odpowiedzi, także po odmowie odpowiedzi na pytanie lub wznowieniu runu. Wyniki narzędzi i rozumowanie pozostają w rozwijanej historii pracy. Dotyczy to zapisanych rozmów i udostępnionych widoków; długość tekstu nie decyduje o jego klasyfikacji.

Historia runów rozróżnia osobę pytającą od publikującego, którego uprawnienia dopuszczają zewnętrzne zapytanie. Niepowiązany nadawca z kanału jest pokazany jako jawnie niezweryfikowane konto chatu, na komputerze i telefonie; anonimowe zapytanie nie otrzymuje wymyślonej tożsamości członka. API zachowuje `user_id` jako kontekst uprawnień i udostępnia `initiated_by_publisher_fallback` oraz `asked_in_chat` do poprawnego przypisania nadawcy. Ten widok nie łączy kont ani nie udostępnia osobistych połączeń publikującego.
