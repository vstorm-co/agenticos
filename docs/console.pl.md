---
source_sha: "11debd5eabee"
---

Selektor modeli utrzymuje nagłówek, karty dostawcy i wyszukiwarkę na miejscu, a listy modeli i dostawców przewijają się niezależnie. Zmiana karty dashboardu zachowuje krótkie przejście; wejście na dashboard ani przywrócenie historii przeglądarki nie animuje całego panelu. Karuzela avatarów w onboardingu pozostaje dostępna także obok wgranego zdjęcia, z wyjaśnieniem, że wybór koloru dotyczy avatara pokazywanego, gdy zdjęcie jest niedostępne.

**Refresh models** w katalogu dostawcy ponownie pobiera listę, zachowując wyszukiwanie i wybór. Przy zapisanych modelach organizacji odczytuje ponownie zapisane profile. Odświeżenie nie zapisuje modelu ani nie uruchamia agenta. Endpoint, klucz Vault, typ API i region pojawiają się zgodnie z możliwościami dostawcy; osobiste subskrypcje korzystają z ustawień połączonego konta.

Tabela subskrypcji pokazuje dwa pierwsze zgłoszone limity w skróconym podglądzie. **Szczegóły** rozwijają wszystkie okna, daty resetu i czas pomiaru. Akcje konta mieszczą się w jednym wierszu, a odłączenie jest dostępne w menu akcji.

Biblioteka modeli czatu domyślnie chowa wyszukiwanie pod lupą obok kart Models oraz Account lub Key. Escape czyści i zamyka wyszukiwanie przed zamknięciem selektora. Odświeżanie i kompaktowy licznik modeli są w wierszu kart; źródło katalogu jest dostępne przy liczniku, a dane konta pozostają w Account. Zapisany model subskrypcji przywraca konkretną usługę, konto i model zamiast zbiorczego wyboru subskrypcji.

Tytuły stron, kontrolki list i nagłówki tabel mają wspólną, zwartą hierarchię. Tabela osadzona w liście ma jedną zewnętrzną ramkę i zachowuje wysokość wierszy podczas ładowania. Karta agenta otwiera Build również wtedy, gdy Evals wymaga uwagi; znacznik pozostaje widoczny. Historia uruchomień jest w Aktywności, zamiast nad Builderem. Podgląd uruchomienia pokazuje zapisany powód błędu, a pełne surowe zdarzenia pozostają w rozwijanych sekcjach. Czat pokazuje nazwę modelu nad dostawcą lub osobistym kontem. Projekty poprzedzają Build w nawigacji; Wiedza zaczyna zwinięta i otwiera się dla aktywnej strony lub po Twoim wyborze.

# Konsola { #the-console }

Nowe generowane propozycje Inbox zawierają gotową prośbę o konkretne działanie zamiast pytania z identyfikatorem wpisu. Powtarzalna praca zachowuje źródłowe prośby oraz ich lokalne daty, dni tygodnia i strefę czasową, dzięki czemu sugerowany harmonogram może wynikać z dowodów. Wybór propozycji przygotowuje edytowalny szkic i nigdy nie wysyła go automatycznie. Chat na telefonie pokazuje dwa startery; szersze ekrany zachowują cztery.

Operator może sprawdzić plan odświeżenia przez `agenticos cmd refresh-inbox --organization-id UUID`, a następnie dodać `--queue`, aby je zakolejkować. Nadal obowiązują skonfigurowany model i dotychczasowe budżety. Tylko otwarte, generowane propozycje są zastępowane po poprawnym odczycie; błąd lub odmowa pozostawia je bez zmian. Zaakceptowane i odrzucone decyzje, findings, powiązane sprawy oraz approval pozostają nietknięte. Decyzja podjęta podczas generowania anuluje zastąpienie propozycji danej osoby.

Domyślne motywy rozróżniają tło strony, sidebar, karty i panele pływające. Niebieski oznacza linki i fokus klawiatury, a włączone przełączniki są zielone. Nawigacja ma zwykłą grubość tekstu i mocniejszą etykietę aktywnej strony. Podsumowania sekcji Buildera pokazują bieżący model, zmienne, stan głosu i pierwsze wiadomości przed otwarciem edytorów. Logowanie i odzyskiwanie konta korzystają ze wspólnego, krótkiego nagłówka i statycznego panelu marki.

Agregaty użycia i wydatków dashboardu korzystają z tej samej odpowiedzi w pamięci dla tego samego okresu przez maksymalnie 30 minut. Nie są licznikami na żywo: zdarzenia wykonań nie odświeżają agregatów po każdym wykonaniu. Pełne przeładowanie przeglądarki zaczyna od pustego cache i ponownie pyta API. Zapisane presety układu są pobierane wyłącznie w widoku organizacji, gdzie dostępne są kontrolki układu.

Jeśli onboarding bieżącej organizacji nie został ukończony, **Dokończ konfigurację** prowadzi do jej konfiguracji z przewodnikiem. Zamknięcie przypomnienia odkłada je na obowiązujący okres 1, 3 lub 7 dni (domyślnie jeden dzień). Ukończenie i odroczenie są zapisane na serwerze dla twojego członkostwa; ładowanie lub błąd odczytu postępu nie oznacza konfiguracji jako nieukończonej.

**Ustawienia → Profil** zawsze zachowują ręczny link do konfiguracji, również po wyłączeniu przypomnień. Przypomnienie ma wyraźną akcję i krótką animację ilustracji, która respektuje ograniczenie ruchu. Wracasz z własnej inicjatywy: przewodnik nie uruchamia się automatycznie. W tej samej przeglądarce link pamięta ostatni dozwolony krok dla tego konta i organizacji, bez zapisywania wartości formularza.

Konfiguracja z przewodnikiem zapisuje bieżący krok i czas aktualizacji dla twojego członkostwa w organizacji. Tabela członków pokazuje stan nierozpoczęty, w trakcie lub ukończony wraz z czytelną nazwą kroku. Postęp dotyczy danego członkostwa; ukończenie konfiguracji w jednej organizacji nie oznacza ukończenia w pozostałych. Wcześniej zapisane ukończenie pozostaje ważne, ale zawartość profilu nigdy nie stanowi dowodu postępu ani ukończenia.

Krok wyświetlony przed wyborem organizacji lub dołączeniem do niej nie jest zapisywany jako postęp członkostwa. Język konta i wygląd zapisują się osobno. W karcie Asystent organizacji Architect i pozostałe usługi asystenta są przed stroną startową czatu; wspólne ikony i nagłówki kart ułatwiają przeglądanie usług.

Inbox zachowuje tę samą ramę listy, odstępy wierszy, oznaczenia źródeł, typografię tytułów i opisów oraz responsywne położenie akcji w zakładkach Wszystkie, Pilne, Wyniki rutyn, Sugestie i Zakończone. Zakończone zachowują status decyzji i przywracanie odrzuconych wpisów; źródło i czas są widoczne także na telefonie. Formularze zgód mają zgodne zewnętrzne odstępy, zachowując wymagane pola i kontrolę uprawnień.

Pliki i Źródła używają tego samego zwartego panelu bocznego: początkowo 400px, z regulacją od 360 do 420px i ograniczeniem do 38% szerokości zadokowanego czatu. Jeśli jest za mało miejsca na zmianę szerokości zadokowanego panelu, wybierz w jego nagłówku **Maksymalizuj (Maximize)**. Na wąskim desktopie mogą tymczasowo zwinąć listę rozmów; zamknięcie przywraca poprzedni wybór, chyba że zmienisz go ręcznie. Przeglądarka zachowuje szerszy obszar pracy: początkowo 55%, z regulacją od 35% do 65%. Kliknięcie cytatu przewija wyłącznie listę Źródeł, pozostawiając konwersację na miejscu.

Komunikat Plików o obszarze roboczym, który jeszcze nie powstał lub nie jest już przechowywany, różni się od błędu połączenia i nie dowodzi, że pliki nigdy nie istniały. Załączniki rozmowy pozostają dostępne. Dołącz i wyślij plik przez pole wiadomości albo poproś agenta o utworzenie pliku, aby użyć obszaru roboczego; rzeczywiste błędy połączenia i archiwum pozostają jawne. W czacie link do pliku zgodnego z potwierdzonym zapisem narzędzia otwiera podgląd obszaru roboczego. Niezweryfikowane ścieżki pozostają zwykłymi linkami; niedostępne prywatne źródło pliku nie staje się linkiem.

Na początku czatu Inbox pokazuje najwyżej dwa priorytety, bez dat i osobnej ikony czatu. Kliknięcie wiersza wstawia propozycję działania do pola wiadomości do edycji; nie wysyła go. **Otwórz Inbox** prowadzi do pełnej listy. Domyślny układ listy rozmów to **Workspace — projects**; `?sidebar=compact` i `?sidebar=comfortable` pozostają dostępne do porównania.

Publiczny czat i osadzony widget obsługują wiadomości wielowierszowe: Enter wysyła, Shift+Enter dodaje wiersz, a składanie znaku przez IME nie wysyła przedwcześnie. W głównym czacie, publicznym czacie i widgecie czytanie wcześniejszych wiadomości wstrzymuje automatyczne przewijanie. Streaming i zmiana rozmiaru treści zachowują tę pozycję; powrót na dół lub świadome wysłanie nowej wiadomości wznawia podążanie. Ponowne połączenie i wczytanie historii nie przewijają czytelnika na dół.

Wykonania i logi workflow mają wspólną ramę listy: filtry nad przewijanymi wierszami i nawigację poniżej. Szablony workflow używają tego samego przejścia od kategorii do biblioteki co szablony agentów. Test uruchamiany z panelem Run potwierdza start w tym panelu zamiast powtarzać sukces w powiadomieniu; błędy pozostają jawne. Pola tekstowe workflow zachowują kolor tła po najechaniu, a fokus i walidacja pozostają widoczne.

Główne kolekcje tabel wypełniają pozostały obszar roboczy; filtry, nagłówki kolumn i stopka pozostają dostępne podczas przewijania wierszy. Pełne lokalne listy mają strony po 50 rekordów, sortowane przed podziałem. Stopka pozostaje przy **1 / 1**, z wyłączonymi niedostępnymi kierunkami. Listy stronicowane na serwerze zachowują tę paginację; tabele wirtualne, czaty projektu i dokumenty wiedzy zachowują stopniowe doładowywanie i rzeczywistą liczbę wczytanych rekordów zamiast wymyślonej liczby stron. Osadzone raporty i macierze konfiguracji zachowują własny układ.

Kategorie, ikony i tagi datasetów mają neutralny wygląd; błędy zachowują kolor ostrzegawczy. Ustawienia rozdzielają ocenianie od generowania i ulepszania. Zmiana modelu pomocniczego nie przesuwa przycisków Zapisz i Anuluj; są wyłączone bez zmian, a opis modelu zastępczego pozostaje na miejscu.

Udostępnianie korzysta z tych samych zwartych pól, menu i wierszy co reszta konsoli. Błąd pierwszego odczytu pokazuje komunikat i Ponów. Późniejszy błąd usługi lub sieci może zachować wczytane osoby; odmowa autoryzacji lub usunięcie zasobu ukrywa zapisane w cache wiersze dostępu i edycję. Błąd wyszukiwania członków ma własne ponowienie zamiast sugerować, że nikogo nie ma.

Apps ustala dostępne cele przewodnika przed pierwszym krokiem, więc licznik nie obejmuje niewidocznych kontrolek. Ostatni widoczny krok proponuje Zakończ. Pomoc pozostaje w stałym nagłówku przeglądarki aplikacji także po zwinięciu pozostałych opcji.

Galeria agentów pokazuje publikację jako kropkę i tekst. Potrzeba uwagi ma mały bursztynowy wskaźnik z powodem dostępnym po najechaniu, fokusie klawiatury lub dotknięciu. Karty workflow skupiają się na nazwie, opisie, dostępie, publikacji i dotychczasowych akcjach; triggery, węzły, tagi i statystyki wykonań pozostają w edytorze, filtrach lub historii. Wprowadzanie tagów używa jednego pola, zachowując obsługę klawiatury i duplikatów.

Katalogi zasobów mają spokojne odstępy, neutralne metadane i spójne akcje. Projekty, bazy wiedzy, tabele i datasety zachowują dostęp, rozmiar i istotne powiązania bez dat na kartach. W Build Instrukcje mają osobny obszar pisania; Model i opcjonalne Zmienne, Głos oraz Pierwsze wiadomości są w jednym panelu z separatorami. Główny model pozostaje widoczny. Thinking i Answer format są częścią ustawień modelu; brak wymaganej konfiguracji i błędy walidacji pozostają dostępne.

W Build sekcja First messages pokazuje karty z ikoną, tytułem i wiadomością. Otwórz kartę, żeby ją edytować. Zapisanie zmian we wbudowanym przykładzie zachowuje pozostałe przykłady w szkicu. Skills, Context i Knowledge search w Toolbox używają list wyboru. Wcześniej używane modele pozostają na jednej liście Models.

Variables, Voice, First messages, Run reviewers, Alerts i Tracing są początkowo zwinięte; podsumowania pokazują bieżącą konfigurację. Rozwiń sekcję, którą chcesz zmienić. Wymagane ustawienia i błędy walidacji pozostają dostępne. Model jest otwarty, a link do ustawień Voice otwiera odpowiednią zakładkę.

Edytor instrukcji dopasowuje wysokość do okna; do dłuższej edycji można go powiększyć. Przy istniejącym modelu Provider i Model pozostają widoczne, a **Ustawienia połączenia** zawierają endpoint, autoryzację, API i region. Brak wymaganej konfiguracji lub błąd pola rozwija tę sekcję.

Przy tworzeniu projektu najpierw podajesz nazwę, miejsce pracy i odbiorców. **Instrukcje i ustawienia domyślne** zawierają opcjonalny opis, instrukcje oraz początkowego agenta. Błąd takiego pola rozwija sekcję. W tabeli z wieloma kolumnami **Dodaj rekord** pokazuje pierwsze pola, wymagane wartości, treść dokumentu i wartości wpisane wcześniej w siatce. Rozwiń **Dodatkowe pola**, aby uzupełnić pozostałe opcjonalne właściwości.

Organizacje mają wyszukiwanie po nazwie i slugu członkostwa, z liczbą wyników w tym samym pasku. Wyczyszczenie wyszukiwania przywraca pełną listę organizacji użytkownika.

Karta AI Architect ma bezpośredni link do Buildera obok przełącznika, bez dodatkowego rozwijania. Pozostałe usługi AI zachowują rozwijane formularze, jeśli mają ustawienia do edycji.

Widok Me zaczyna się od karty podsumowania okresu, a następnie zwartego Briefingu z tytułami, źródłami i akcjami. Pełne opisy propozycji pozostają w Inbox.

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

Karty agentów pokazują publikację i dostęp bez rozwijania. Karty Skills i Context zachowują podgląd dokumentu, opis, **Used by** z portretami agentów i **Dodaj do agenta**. Kategoria i odbiorcy są obok akcji. Aby usunąć skill lub plik kontekstu, otwórz edytor i menu z trzema kropkami obok **Share**; usunięcie wymaga potwierdzenia i uprawnień edytora.

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

Pole wiadomości pokazuje aktywny tryb zatwierdzania obok wyboru agenta. Kliknij etykietę, aby zmienić zapisany tryb przed wysłaniem. Obowiązują te same uprawnienia i polityka organizacji co w Chat controls. Automatycznie zatwierdzone wywołania zachowują zatwierdzone wpisy audytowe; tylko rzeczywiście oczekujące wywołania pokazują prośby o decyzję.

Na telefonie wyśrodkowane modale zachowują 12 px marginesu z każdej strony. Zwarte nagłówki mieszczą tytuł i akcje w jednym wierszu, gdy jest na to miejsce. Opis pliku Context rozwija się z paska edytora.

Kontekstowe udostępnianie otwiera się przy dolnej krawędzi telefonu i mieści nad klawiaturą. Nagłówek pozostaje widoczny podczas przewijania treści. Mobilna lista rozmów pozwala zmienić tytuł w miejscu, a udostępnianie zastępuje zawartość listy; **Wstecz** ją przywraca. Wyszukiwanie tymczasowo zastępuje listę. Escape anuluje zmianę tytułu, zanim zamknie listę. Zwykłe pola i selecty na telefonie mają co najmniej 44 px wysokości, a tekst w polach ma 16 px. Wyszukiwarka poleceń zachowuje widoczne pole i przycisk zamknięcia podczas przewijania wyników.

Pola wyszukiwania w katalogach pozostają widoczne i dostępne podczas ładowania list; odczyt nie usuwa wpisanego filtra. Pusty podgląd Inboxa na stronie nowego czatu nie pokazuje komunikatu ani linku i zachowuje zarezerwowane miejsce nad polem wiadomości.

Na telefonie główne akcje strony pozostają widoczne, a drugorzędne polecenia rozwija przycisk **Więcej akcji strony**. Filtry Inbox i format tabeli wybiera się selectem. Ustawienia mają poziomy, przewijany pasek zakładek; klienta MCP wybiera się z listy. Plik projektu lub workspace otwiera czytnik na pełnym ekranie, a strzałka wstecz wraca do folderów. Edytor kroku workflow pokazuje jeden wybrany panel: ustawienia, wejście albo wynik. Przełączanie zachowuje edycję; desktop nadal pokazuje panele obok siebie.

Pola Markdown i edytory plików również mają przycisk powiększania, który zachowuje bieżący szkic. Opis i kategorię skilla można rozwinąć nad edytorem. Pole wiadomości na czacie zajmuje mniej miejsca i ogranicza wysokość długiego szkicu do dostępnej wysokości ekranu. Otwarcie nawigacji ustawia focus na panelu, a Tab nadal przechodzi do jego kontrolek. Na telefonie canvas workflow ma pływający przycisk pełnego ekranu, otwiera się z całym przepływem w widoku i startuje z ukrytą minimapą.

Każde jawne kliknięcie **New chat** ponownie ustawia fokus w edytorze, także przy pustym szkicu; nadanie rozmowie identyfikatora podczas pisania nie żąda ponownego fokusu.

Na telefonie edytory skilli i contextu chowają opis, kategorię i zarządzanie plikami podczas pisania. Jeden przycisk przełącza źródło i podgląd. Apps ma pływające przyciski powrotu i opcji; opcje rozwijają tytuł, wersję, motyw i udostępnianie.

Nagłówki korzystają z odstępów otaczającego układu bez ich podwajania. Karty, wiersze panelu bocznego, zakładki i puste stany mają mniejsze odstępy na komputerze, a kontrolki zachowują większe obszary dotykowe.

Przyciski drugorzędne i filtry mają wspólne, wyraźniejsze wypełnienie, kontrastowe etykiety oraz czytelne stany najechania, naciśnięcia i otwarcia. Wybór modelu w chacie korzysta z tego samego stylu przycisku.

Ustawienia osobiste mają poziome, przewijane zakładki na komputerze i telefonie. Objaśnienia otwierają się pod przyciskami informacji; wymagania pól, błędy walidacji i ostrzeżenia przy usuwaniu pozostają widoczne. Konto zawiera zmianę hasła i aktywne sesje.

Tytuły rozmów są pierwszą linią listy czatów, z nazwami agentów i aktywnością poniżej. Wyszukiwanie, filtry i Nowy czat dzielą nagłówek. Filtry nagłówka otwierają się pod przyciskiem, a filtry zwiniętej szyny obok niego. Powitanie w głównym czacie pokazuje aktywnego agenta.

Gdy lista rozmów ma wolne miejsce, rozwija kolejne starsze grupy dat aż do zapełnienia panelu. Grupy projektów również respektują zapisane wybory: ręcznie zwinięta grupa pozostaje zwinięta, dopóki jej nie rozwiniesz, także po zmianie aktywnej rozmowy.

Pola profilu mieszczą się w jednym wierszu, gdy jest miejsce; **Zapisz zmiany** jest dostępne dopiero po edycji. Karta możliwości ma jeden obszar otwierający ustawienia i osobny przełącznik włączenia. W panelu ustawień przykłady są pod ikoną informacji, zamiast powtarzanej ilustracji z galerii.

Okna kategorii szablonów dopasowują się do zawartości; wybranie branży agenta lub umiejętności otwiera większą bibliotekę. Na telefonie wybór wyglądu ma postać zwartych wierszy z miniaturami.

Instrukcje agentów i projektów mają jeden zwarty pasek z tytułem, pomocą, przełączaniem źródła i podglądu oraz rozwijaniem. Rozwinięty Markdown zachowuje wybrany tryb źródła lub podglądu. Zmienne promptu są początkowo zwinięte z podsumowaniem konfiguracji; rozwijanie i zwijanie sekcji zachowuje szkic. Rozwinięte edytory tekstu i plików zachowują równe marginesy na telefonie. Pola tekstowe na telefonie używają większej czcionki bez powiększania pól na komputerze.

Na telefonie fokus w polu wiadomości przełącza czat w zwarty wiersz pisania z załącznikami i wysyłaniem. Wybór agenta oraz głos pozostają dostępne pod **+**. Powitanie i sugestie połączeń chowają się na czas pisania, a menu uzupełniania mieści się w dostępnej wysokości. Przejście z tekstu na Wyślij zachowuje stabilny układ.

Wejście do głównego czatu ustawia fokus w polu wiadomości, gdy tylko można w nim pisać, także jeśli podczas łączenia fokus pozostał na przycisku nawigacji. Kontrolka świadomie użyta podczas łączenia zachowuje fokus.

Na telefonach akcje pod wiadomościami użytkownika i agenta są początkowo ukryte. Przycisk **Więcej** obok nadawcy pokazuje lub ukrywa kopiowanie, odpowiedzi, oceny i pozostałe dostępne akcje. Na komputerze przyciski nadal pojawiają się po najechaniu kursorem.

Importy CSS, obrazy i fonty w podglądzie są rozwiązywane względem arkusza przez ten sam autoryzowany dostęp do plików. Podgląd dopuszcza cztery zagnieżdżone poziomy, 64 zasoby, 8 MiB wejściowych zasobów i 16 MiB rozwiniętego wyniku. Skróty plików zachowują konwersację lub folder z chwili wykonania tury, zapisane z jej osią czasu. Zmiana Work on nie przekierowuje skrótów. Starsze tury bez zapisanego źródła nie otrzymują zgadywanych linków. Otwarcie lokalnego pliku nadal wymaga aktualnej zgody na folder.

Metadane linków do plików zapisują dla lokalnych tur tylko niejawny identyfikator źródła. Powiązanie z folderem pozostaje na komputerze inicjującym, w zakresie konta i organizacji; inni uczestnicy i komputery nie mogą rozwiązać tych linków. Starsze źródła zawierające lokalną ścieżkę są pomijane przy odczycie zapisanych tur.

**Visual map** w builderze agenta dopasowuje całą konfigurację po otwarciu i zmianie rozmiaru obszaru. **Reset view** ponownie dopasowuje mapę po przesunięciu lub przybliżeniu. Duże grupy pokazują sześć elementów i liczbę pozostałych; wybierz grupę, aby otworzyć pełną, przewijaną listę. Minimapa workflow pokazuje cały graf i pozwala przejść do innego miejsca bez zmiany przybliżenia.

Panel testowania w builderze można rozwinąć na cały obszar bez resetowania rozmowy ani niewysłanego tekstu. Porównanie dwóch wersji automatycznie otwiera ten widok; przycisk pełnego ekranu lub Escape przywraca builder. Wybór wersji ma osobny wiersz, dzięki czemu kontrolki testu mieszczą się w wąskim panelu. Na telefonie przełączaj porównywane chaty przyciskami wersji; obie rozmowy nadal działają i zachowują szkice. Wspólny prompt nadal trafia do obu naraz.

Nawigacja zachowuje wspólne układy stron bez wygaszania treści ani animowania statycznych sekcji ustawień przy wejściu. Górny pasek postępu obejmuje też przejścia uruchamiane przyciskami akcji. Podkreślenie zakładek przesuwa się między rzeczywistymi etykietami; ograniczony ruch pozostawia je statyczne. Widżety czekają na zapisany układ, strony zależne od uprawnień na ich odczyt, a listy administracyjne zaczynają od ładowania zamiast twierdzić, że są puste. Filtry grup i autorów Apps rezerwują miejsce podczas ładowania.

Na telefonach wysłane wiadomości zatrzymują się poniżej pływających przycisków czatu, dzięki czemu avatar użytkownika pozostaje widoczny. Początek rozmowy i miejsce rezerwowane na odpowiedź uwzględniają ten sam odstęp pod przyciskami; desktop i osadzone czaty zachowują mniejszy odstęp.

Domyślni agenci kończą jednorazowe zadanie bez przedłużania odpowiedzi pytaniem o opcjonalną automatyzację. Pytania służą decyzjom potrzebnym do bieżącego zadania albo automatyzacji, o którą użytkownik prosi lub którą akceptuje. Opcjonalne karty konfiguracji pozostają propozycjami, które nie blokują zakończenia.

Przycisk źródeł pod odpowiedzią przełącza panel Sources obok rozmowy, na telefonie na pełną szerokość. Ponowne kliknięcie zamyka panel, a wybór innej odpowiedzi zmienia jego źródła. Cytat otwiera panel i wskazuje cytowany fragment. Karty przeglądarki również przełączają swój panel boczny; wybór karty wewnątrz panelu pozostawia go otwartym. Files i Sources dzielą boczny obszar: otwarcie jednego zastępuje drugi. Źródła internetowe używają favicon witryny pobieranej bez nagłówka Referer lub znanego logo usługi; globus pozostaje, gdy ikona jest niedostępna. Źródła z bazy wiedzy zachowują ikony plików i podgląd oryginalnego dokumentu.

Linki internetowe w odpowiedzi korzystają z tych samych favicon niezależnie od połączeń MCP. Ikony nieznanych stron przechodzą przez proxy konsoli i stały serwis ikon DuckDuckGo. Serwis otrzymuje tylko nazwę hosta, bez cookies i adresu IP czytelnika, ścieżki ani parametrów URL. Proxy odrzuca przekierowania, obrazy inne niż rastrowe i ikony ponad 64 KiB; limit czasu wynosi trzy sekundy. Brak lub niedostępność ikony zastępuje globus. Widoki transkrypcji z wyłączonym ładowaniem obrazów nie pobierają też ikon nieznanych stron.

Nieudany run pokazuje błąd oddzielnie od odpowiedzi agenta, poza zwijanymi narzędziami, także po odświeżeniu rozmowy. Filtr treści dostawcy ma osobne wyjaśnienie; surowe odpowiedzi dostawcy i nieznane historyczne komunikaty błędów nie są kopiowane do udostępnianych transkrypcji. Częściowe wyniki pozostają dostępne, a nieudana praca nie jest oznaczana jako ukończona.

Załączniki pozostają wewnątrz pola wiadomości w jednym przewijanym wierszu. Bezpieczne obrazy mają lokalną miniaturę podczas wysyłania; trwające wysyłanie wskazuje animowany wskaźnik bez wymyślonego procentu. Podkreślenia kart i zaznaczenia segmentów płynnie przechodzą między opcjami; przy ograniczeniu animacji zmiana jest natychmiastowa.

Nowy czat pokazuje pod polem wiadomości do czterech promptów bieżącego agenta, w dwóch kolumnach, gdy jest miejsce. Kliknięcie dodaje prompt do edytowalnego szkicu. Pisanie ukrywa propozycje bez przesuwania pola wiadomości; wyczyszczenie szkicu je przywraca. Fokus w pustym polu pozostawia widoczną stałą wskazówkę o komendach `/` i zasobach `@`. Zatwierdzenie znaku za pomocą IME nie wysyła wiadomości.

Oś czasu pokazuje do dwóch pozycji z Inboxa, wliczając link do oczekujących zgód, i prowadzi do pełnego Inboxa. Ładowanie rezerwuje miejsce na podgląd. Skrzynka i kolejki zatwierdzeń od razu korzystają z pamięci podręcznej podczas nawigacji; dane pozostają świeże przez 30 sekund, a nieużywane wpisy są przechowywane przez 30 minut. Błąd odświeżania pozostawia widoczne zapisane elementy wraz z ostrzeżeniem. Zmiana konta lub organizacji nadal czyści pamięć podręczną.

Główny czat ma szerokie pole wiadomości. Biblioteka modeli pokazuje najpierw podłączonych dostawców, z logotypami i nazwami od wielkiej litery, z jedną listą Models i osobną zakładką konta lub klucza. Kliknięcie modelu od razu go wybiera. Brakujące poświadczenia można dodać w formularzach Vaulta z poziomu wyboru modelu, również dla dostawców wymagających kilku pól; nadal obowiązują dotychczasowe uprawnienia i walidacja modeli. Mikrofon i przycisk wysyłania płynnie zmieniają stan podczas pisania.

Wyszukiwanie rozmów obejmuje tytuły i indeksowaną treść wiadomości, także w dostępnych archiwach. Wyniki pokazują fragmenty tekstu, podświetlenia i liczbę pasujących wiadomości. Strzałki i Enter pozwalają otworzyć wynik. Błąd wyszukiwania ma przycisk ponowienia zamiast udawać brak wyników.

## Wygląd i zachowanie konsoli { #console-experience }

Administrator instalacji wybiera dostępność w **menu konta → Administracja → Instalacja → Wygląd i nazwa**. Administrator organizacji ustawia wartości początkowe w jej ustawieniach **AI i usługi**. Każdy członek może je zmienić w **Ustawienia → Profil**, tylko dla bieżącego obszaru roboczego. **Podgląd skrzynki**, **Propozycje wiadomości**, **Powitanie** i **Podpowiedzi funkcji** są niezależne. Element wyłączony dla instalacji pozostaje niedostępny; członek może natomiast zmienić ustawienie domyślne organizacji. Motyw, styl i język nadal dotyczą całego konta.

Ukrycie podglądu skrzynki pozostawia dostęp do pełnej skrzynki i kolejki zgód. Miejsca na powitanie i propozycje zachowują wysokość, więc zmiana widoczności nie przesuwa pola wiadomości. Podpowiedzi funkcji obejmują ogólne opisy funkcji oraz wskazówkę `/` i `@`; niezbędne etykiety pól i dymki pozostają dostępne. Ustawienia zmieniają prezentację, nie uprawnienia do zasobów ani zachowanie agentów.

**Przypomnienia o konfiguracji** mają tę samą hierarchię: dostępność instalacji, ustawienia organizacji i wybór osoby. Możesz zdecydować, czy się pojawiają i czy odroczenie trwa 1, 3 lub 7 dni. Domyślnie to jeden dzień. Serwer oblicza termin powrotu dla tego członkostwa; nie tworzy harmonogramu powiadomień ani udanego zadania. Po wyłączeniu przypomnień ręczny link do konfiguracji pozostaje w Profilu.

Ustawienia instalacji mają też opcjonalny termin **Wygaśnięcia ogłoszenia**. Po tym terminie serwer przestaje zwracać ogłoszenie, a otwarte strony otrzymują zmianę podczas zwykłego odpytywania o komunikaty. **Planowany koniec prac** to wyłącznie informacja: nie otwiera automatycznie aplikacji. Tryb konserwacji kończy administrator. Pola dat pokazują strefę urządzenia i zapisują daty ze strefą w UTC.

Administracja jest dostępna w menu konta. Jej ustawienia używają wspólnych zakładek i zachowują draft podczas przełączania sekcji. Pamięć i Notatki wypełniają pozostały obszar, przewijają własne wiersze i zachowują stopkę **1 / 1**. Zwykły Architect używa tej samej rodziny generowanych portretów co inni agenci; własne przesłane obrazy pozostają zachowane. Widoki skrzynki współdzielą wygląd wierszy, a przeciąganie Kanbana pokazuje rzeczywistą kartę. Późniejsze kroki konfiguracji zachowują spójny układ nagłówka, formularza i ilustracji; kontynuacja niezmienionego profilu nie zgłasza zapisu.

### Koszty w chacie { #chat-cost-visibility }

**Koszty w chacie** mają ściślejszą hierarchię: dostępność w deploymencie → odbiorcy w organizacji → wybór użytkownika. Deployment może ukryć koszty w całym chacie. W ustawieniach **AI i usługi** organizacji wybierz **Wszyscy** (domyślnie), **Osoby z dostępem do wydatków** (`budgets:manage` lub `runs:view`) albo **Nikt w chacie**. W **Ustawienia → Profil** użytkownik może ukryć koszty u siebie, ale nie może obejść nadrzędnego ograniczenia.

Reguła obejmuje ceny odpowiedzi, koszty delegacji, sumy rozmów i procent wykorzystanego budgetu, także w zapisanej historii, streamie po ponownym połączeniu, współdzielonych chatach i kontynuacjach Q&A. Ukryte metadane finansowe nie trafiają do odpowiedzi API chatu; odczyty tokenów i kontekstu pozostają dostępne. Reguła nie zmienia tekstu odpowiedzi agenta ani dowolnych wyników narzędzi. Księgowanie i egzekwowanie budgetów działają bez zmian. Koszty w Activity i dashboardzie zachowują własne uprawnienia.


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

| Widok           | Odpowiada na                                                                                                                                                                                                                                                             |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Ja**          | Twój okres, Briefing i wskazówki Discover; ostatnie rozmowy, projekty, Twoi agenci, najczęściej używani agenci i ostatnie wizualizacje. Domyślny widok osobisty pomija karty decyzji, tematów w tle i udostępnionych zasobów.                                            |
| **Organizacja** | Układalna strona opisana niżej                                                                                                                                                                                                                                           |
| **Grupa**       | Członkowie jednej [grupy](departments.md) - ich runy, wydatki, modele, kiedy pracują i kto korzysta najwięcej. Grupę wybierasz obok przełącznika. Grupa, której członkowie nic nie uruchomili w okresie, mówi to raz, z przejściem do grupy, zamiast strony pustych kart |
| **Wdrożenie**   | Tylko dla [admina deploymentu](permissions.md) — sumy platformy, kondycja, najbardziej obciążeni najemcy, oceny                                                                                                                                                          |

Briefing wyrównuje tytuły i źródła z akcjami. Discover znajduje się bezpośrednio pod nim. Ostatnie wizualizacje mieszczą obrazy w wyśrodkowanych podglądach. Pytanie przestaje oczekiwać na odpowiedź, gdy serwer rozpoczyna przyjętą kontynuację. Kliknięcie zamykanego toastu usuwa go z krótkim wygaszeniem; komunikaty trwających operacji pozostają widoczne.

Karty jakości, w tym **Agenci wymagający uwagi** i **Poprawki czekające na Ciebie**, pozostają w katalogu widoku organizacji pod **Customize**. Decyzje, uprawnienia i linki do ulepszania agentów działają tak samo. Osobisty licznik oczekujących spraw obejmuje zgody na narzędzia użytkownika, pytania czekające na odpowiedź w czacie i otwarte propozycje Inbox.

Widok organizacji pokazuje karty, które odpowiadają danymi, pogrupowane w pasy.
Reszta - integracje, kanały, rutyny, synchronizacja wiedzy, działy, członkowie,
sandboxy - czeka w katalogu, jedno kliknięcie dalej pod **Customize**:

| Pas                      | Odpowiada na                                                                                                                                                                     |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| _(bez tytułu, na górze)_ | Podsumowanie, runy w czasie i to, jak się skończyły                                                                                                                              |
| **Needs attention**      | Co czeka: [zatwierdzenia](governance.md#approvals), ostatnie błędy, zapas w budżecie, twoje najnowsze [powiadomienia](#the-bell)                                                 |
| **Usage & cost**         | Których agentów się używa, wydatki, [minuty rozmów](#voice-calls), kiedy dzieje się praca, skąd przychodzą runy, miks modeli, opóźnienia, jakość odpowiedzi, kto z tego korzysta |

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

Twój własny widok pokazuje też **Odkryj AgenticOS**. Najpierw przedstawia własne
subskrypcje Claude Code, ChatGPT (Codex) i Antigravity, pierwsze zadanie w czacie
oraz użycie AgenticOS z dotychczasowego klienta do kodowania. Kolejne kafelki
obejmują własne połączenia z narzędziami, projekty i pamięć, a dalej sandboxy,
subagentów, aplikacje, rutyny, kanały, przeglądarkę, wiedzę i skills. Każdy prowadzi
do konfiguracji lub miejsca pracy; akcje wymagające uprawnień widzą tylko osoby,
które mogą ich użyć. Zamknij kafelek albo wszystkie; to też zostaje w przeglądarce.

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

Nowe rutyny automatycznie korzystają z dostępnej konfiguracji agenta przy tworzeniu, w zatwierdzonej granicy dostępu i zachowania. Wstępny przegląd dostępu nie jest wymagany; brak opcjonalnego konta MCP nie blokuje niezwiązanej z nim pracy. Późniejsze rozszerzenia źródeł lub narzędzi oraz zmiany instrukcji, skills, kontekstu albo delegatów wymagają przeglądu twórcy przed uruchomieniem. Zmiany samego modelu i bezpieczne ograniczenia pozostają w zatwierdzonej granicy. Nadal obowiązują zgody agenta, obowiązkowe zgody platformy i zgoda na lokalny folder. Okno dostępu pozwala też zachować zatwierdzony snapshot; istniejące ograniczone rutyny zachowują swoją politykę do zmiany przez właściciela.

Gdy **Skip this run** pomija termin z powodu trwającego uruchomienia, historia zapisuje przyczynę bez nowego uruchomienia ani opłat. Jeśli serwer przyznaje Ci prawo do zatrzymania oczekującego uruchomienia, możesz zrobić to bezpośrednio w historii. Zatrzymanie zachowuje naliczone koszty i odblokowuje kolejny termin harmonogramu. Kolejne pominięcia przez ten sam niedokończony przebieg mają jeden wspólny wpis w historii.

Nazwy rutyn zawijają się na telefonach. Brak wyników daje przycisk **Wyczyść wyszukiwanie**, a **Ponów** odświeża zadania i obserwacje po błędzie odczytu. Edycja harmonogramu i wyzwalacza zdarzeniowego przewija się między stałym nagłówkiem i stopką z przyciskami. Zapis blokuje pola oraz zamykanie do zakończenia żądania; odmowa zachowuje wpisane dane.

Routines ma dwie zakładki. **Zadania agentów** uruchamiają wybranego agenta według
harmonogramu lub zdarzenia, z jego narzędziami; runy widać w Activity.
**Moje obserwacje** tylko odczytują osobiste połączenia i przekazują znaleziska do
prywatnego Inbox. Każda zakładka ma własne przyciski tworzenia.
`/routines?tab=watches` otwiera obserwacje. Jedno sprawdzenie wykonuje najwyżej
30 zapytań do modelu, a długie wyniki są przycinane, więc obserwacja dużego
workspace pozostaje tania.

Organizacja → AI i usługi pokazuje osobne karty funkcji z przełącznikami i rozwijanymi ustawieniami. Codzienny briefing i sugestie mają jeden model, budżet i harmonogram; monitoring oraz wiadomość powitalna mają własne karty. Niezapisane zmiany można odrzucić.

Rutyny harmonogramowe, zdarzeniowe i obserwacje korzystają z tej samej ramy modalu: stałego nagłówka i nawigacji oraz przewijanego formularza. Tworzenie obserwacji prowadzi przez konfigurację, wiadomość i częstotliwość; przycisk Wstecz zachowuje wpisane dane. Wybór agenta pokazuje te same avatary co czat. Ustawienia wykonania i dostarczania obserwacji są zebrane w jednym panelu opcji zaawansowanych.

Discover na dashboardzie zaczyna się od własnych kont i codziennych zadań. Najedź na wykres
w _Your period_, aby zobaczyć przedział i wartość; koszty są kwotami. Projekty
pokazują opisy, a wiersze agentów używają tych samych avatarów co chat.

Karty dashboardu korzystają ze spójnych, zwartych wierszy, oznaczeń usług i etykiet statusu. Liczniki i wykresy dostosowują się do szerokości karty, również we własnych układach. Placeholdery odpowiadają rodzajowi ładowanej zawartości; niedostępny briefing pokazuje możliwość ponowienia zamiast informacji o braku propozycji.

Nowy chat wita zależnie od lokalnej pory dnia i pokazuje zwarte pole wiadomości. Pliki są obok agenta, a ustawienia i tarcza uprawnień obok modelu. Zużycie kontekstu pozostaje ikoną do chwili otwarcia szczegółów.

Oś czasu nad polem wiadomości pokazuje najpierw pozycje priorytetowe z Inboxa, a w każdej grupie zaczyna od najnowszych. Przy każdej pozycji widać źródło, bez daty. Kliknięcie wiersza przygotowuje pytanie do edycji w polu wiadomości; Otwórz Inbox prowadzi do pełnej listy. Licznik zgód prowadzi do kolejki decyzji. Ładowanie, błąd i pusta lista mają osobne stany. Dyktowanie i połączenia korzystają z tej samej lekkiej powierzchni co pole wiadomości. Widget Architecta korzysta z tego samego przycisku głównego i kontrolek dyktowania.

Przed pierwszą wiadomością pliki i użycie kontekstu pozostają widoczne, ale nieaktywne. Menu załączników pokazuje dostępne akcje od razu. Ustawienia czatu mają zwarte sekcje połączeń i zapamiętanych zgód; podgląd Inbox pokazuje źródło i priorytet.

Pola, wiersze menu, listy wyboru, zakładki i sekcje ustawień w całej konsoli mają wspólny, zwarty styl. Zwinięcie opcjonalnego formularza zachowuje wpisane dane; wymagane pole z błędem może ponownie otworzyć swoją sekcję. Natywne rozwinięcia mają wspólne odstępy i animację w przeglądarkach obsługujących rozmiar zależny od treści, a w pozostałych otwierają się standardowo. Nadal działają ograniczenie ruchu i większe obszary dotykowe.

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

**Pytania czekające na odpowiedź** pojawiają się w widokach **Wszystkie** i **Pilne**, gdy agent w czacie internetowym czeka na Twoją odpowiedź. Wiersz pokazuje czat, agenta i termin wygaśnięcia. Otwórz go, aby odpowiedzieć w pierwotnym czacie; samo otwarcie nie usuwa wpisu. Pytanie liczy się jako oczekujące, dopóki wykonanie nie zostanie wznowione lub anulowane albo pytanie nie wygaśnie. Wpis w Inbox widzi tylko osoba, do której skierowano pytanie, niezależnie od uprawnień do zatwierdzania.

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

Okno to ten sam czat co w konsoli, a nie strona osadzona w stronie. Otwiera się
na czterech kafelkach, więc pierwsza wiadomość to jedno kliknięcie, i ma własną
historię rozmów. Na telefonie zajmuje cały ekran.

Gdy wskazuje stronę, link otwiera się w konsoli za oknem i podświetla kontrolkę,
o którą chodzi — przycisk tworzący agenta, zakładkę z akceptacjami. Aparat w
nagłówku okna pokazuje mu stronę, na której jesteś: przeglądarka pyta, którą
kartę udostępnić, a jedno zdjęcie trafia jako załącznik do twojej następnej
wiadomości.

Dłuższe zadania planuje jako listę kroków, którą widać na bieżąco,
zapamiętuje notatki o tobie między rozmowami, powie, ile kosztują twoi agenci, i
usuwa tylko draft agenta, który utworzył przez pomyłkę, oraz rutynę, o której
usunięcie poprosisz. Oprócz
akceptacji i pustej organizacji dymek odzywa się, gdy twój run właśnie się nie
udał, i gdy formularz jest otwarty, niedokończony, od minuty.

Przed podłączeniem modelu Architect otwiera ten sam czat z graficzną kartą konfiguracji, krótką listą kroków i przyciskiem ustawień modelu. Możesz napisać wiadomość w widżecie lub wybrać szkic Architecta w czacie: zapisze odpowiedź konfiguracyjną i kartę w historii, bez wywołania modelu i bez runu AI. Odpowiedź używa nazwy wybranego agenta. Przyciski konfiguracji respektują uprawnienia; pozostali członkowie widzą wskazówkę do administratora. Po publikacji zwykła rozmowa jest dostępna bez zamykania widżetu.

Architekt jest agentem jak każdy inny, więc jego nazwę, model, wiedzę i resztę
spec edytuje się w Agent Builderze - może to zrobić ktoś, kto zmienia ustawienia
organizacji, bo uruchamia go każdy w organizacji. Na stronie organizacji jest
karta, która wyłącza go dla wszystkich i prowadzi do Agent Buildera. **Ustawienia →
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

Wspólne pokoje, czaty projektowe i rozmowy udostępnione do edycji odtwarzają widoczne tury czatu zamiast ukrytych checkpointów modelu. Kolejny uczestnik nie dziedziczy prywatnych wyników narzędzi ani rozumowania poprzedniego autora; w razie potrzeby agent ponawia odczyt przez połączenia bieżącej osoby. Fork wspólnej rozmowy także pomija ukryty checkpoint. Prywatne czaty webowe i wiadomości bezpośrednie zachowują ustrukturyzowaną historię modelu.

Prywatny checkpoint jest przypisany do agenta, rzeczywistych celów połączeń z modelami (w tym fallback) oraz kont, adresów i wersji autoryzacji MCP użytych w tej turze. Zmiana agenta, endpointu lub połączenia odtwarza historię z widocznych wiadomości zamiast wysyłać wcześniejsze ukryte wyniki narzędzi innemu odbiorcy.

Starsze checkpointy bez tych danych także korzystają z widocznego zapisu. Oczekujący run nie wznowi się po zmianie celu: przywróć poprzednią konfigurację albo rozpocznij nową turę. Runy zaparkowane przed dodaniem informacji o odbiorcy wymagają ponownego uruchomienia.

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

Czat używa tej samej chronologicznej osi na żywo i w historii. Zwykłe wywołania narzędzi i rozumowanie pozostają pod zwiniętymi kontrolkami pracy. Komunikaty o postępie, odpowiedzi, podsumowania pytań i wyniki wizualne zachowują miejsce po zakończeniu uruchomienia. Rozwinięcie pracy pokazuje wywołania bez automatycznego otwierania argumentów. Pytania i zatwierdzenia zachowują stan oczekiwania do rozstrzygnięcia.

Rozwinięte kroki narzędzi pokazują surowe argumenty i wyniki. Wykresy, wygenerowane multimedia, utworzone pliki i raporty zmian kodu pojawiają się raz w rozmowie, poza szczegółami pracy. Podglądy korzystają z tego samego uwierzytelnionego lub osadzonego dostępu co rozmowa.

Pytania pojawiają się wewnątrz rozmowy, poza dolnym obszarem pola wiadomości. Podczas wysyłania odpowiedzi opcje pozostają widoczne i zablokowane do potwierdzenia przez serwer. Potwierdzone pytanie zamienia się w krótkie podsumowanie; jedno rozwinięcie pokazuje wszystkie pytania i odpowiedzi. Przycisk nad polem wiadomości prowadzi do oczekującego pytania. Czytanie wcześniejszych wiadomości zachowuje pozycję, a nowe pytania nie przejmują fokusu.

Zatwierdzenia w czacie pozostają jedną prostą kartą przy polu wiadomości: operacja, jej ikona i tytuł zadania lub obiektu, a dodatkowe argumenty pod Details. Przyciski Approve i Reject są obok żądania, a na wąskim ekranie pod nim. Zakończona aktywność ma spokojny znacznik ukończenia, oczekujące kroki osobny status, a działające kroki zachowują ikonę operacji zamiast osobnej animowanej kuli przy każdym wywołaniu.

Ponowne otwarcie czatu odtwarza też zatwierdzenia i pytania narzędzi subagenta, których nie ma na osi głównego agenta. W trakcie zatwierdzonego wznowienia przez HTTP wstrzymany subagent jest pokazywany jako pracujący. Zakończony opublikowany subagent zachowuje własny wynik, gdy agent nadrzędny zatrzyma się na kolejnej decyzji.

Napływający tekst pozostaje czytelny podczas ładowania modułu formatowania Markdown. Pole wiadomości ma nieprzezroczyste tło i delikatny stan fokusu, bez animowanej ramki i rozmywania treści pod spodem.

Rozwinięte szczegóły pracy mają ograniczoną wysokość i własne przewijanie zarówno na żywo, jak i w historii. Sąsiadujące segmenty jednego agenta i uruchomienia mają wspólne podsumowanie oraz czas rozpoczęcia, także gdy zawierają komunikaty między narzędziami i wznowienia po zatwierdzeniu. Inny agent lub wiadomość użytkownika pomiędzy segmentami rozpoczyna osobny turn. Zakończone i zagnieżdżone wymiany agentów pozostają dostępne, także raporty agentów programistycznych. Otwórz wymianę, aby przeczytać instrukcje, odpowiedź i zwinięte rozumowanie.

Udane zapisy MCP pokazują karty z linkami do projektów, tabel, zadań, rekordów, agentów, workflow, skilli i Context. Błędy nie tworzą kart sukcesu. Wysłana wiadomość pojawia się blisko góry z miejscem na odpowiedź; ręczne przewijanie zachowuje pozycję. Listy Person i Agent przewijają się w oknie rekordu. Pytania działają także po wznowieniu czatu przez HTTP po zatwierdzeniu operacji.

Powiadomienia o wynikach pojawiają się przy polu wiadomości. Po ponownym otwarciu lub odświeżeniu rozmowy oczekujące zgody na wywołanie narzędzia wracają jako karty ze szczegółami i przyciskami Zatwierdź i Odrzuć dla osób uprawnionych do decyzji. Inbox i dzwonek również pokazują powiadomienia o zgodach. Pojedyncza prośba o zgodę ma formę kompaktowego paska z rozwijanymi szczegółami. W Inboxie rozmowa z agentem pozostaje widoczna, a pozostałe akcje są w menu wiersza. Czat wyróżnia linki do zasobów konsoli, a kod w treści zdania ma osobne neutralne tło.

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

**Osobista pomoc.** Gdy organizacja ją włączy, platforma łączy dostępne rozmowy
z Twoją pamięcią, profilem, widocznymi projektami, prywatnymi lub przypisanymi
zadaniami, aktualnymi rutynami, metadanymi widocznych tabel i wcześniejszymi decyzjami w Inboxie. Rekordy tabel są odczytywane tylko jako zadania o określonym schemacie. Istotne zmiany
zlecają odświeżenie w tle; poranny przegląd pozostaje dodatkowym zabezpieczeniem.
Historia jest indeksowana fragmentami z cytatami wskazującymi źródła. Niezmienione
fragmenty korzystają z zapisanego indeksu, a niezmieniony odczyt nie wywołuje modelu.
Duże historie są kontynuowane w kolejnych zadaniach, zamiast ograniczenia do siedmiu
dni i pierwszych 400 znaków. Obowiązują uprawnienia, rezygnacja i limity wydatków.

Propozycja musi wskazywać źródła i przejść osobną ocenę modelu. Może dotyczyć agenta
na żądanie, pracy cyklicznej, istniejącego zadania lub przydatnej dostępnej funkcji.
Uwierzytelniona odpowiedź na natywne pytanie jest wypowiedzią użytkownika; dowolny
wynik zewnętrznego narzędzia nią nie jest. Brakujące ustalenia harmonogramu pozostają
pytaniami. Propozycje trafiają do **Suggestions**, a ustalenia rutyn do **Routine
results**. Otwarcie propozycji rozpoczyna konkretną rozmowę, bez uruchomienia pracy.
Płatne działania, harmonogramy i publikowanie nadal wymagają odpowiednich zgód.
Usunięta rutyna nie jest traktowana jako wstrzymana, a odrzucony pomysł nie wraca.
Listy zadań i zasobów są ograniczone i w razie potrzeby oznaczane jako niepełne;
brak pozycji na niepełnej liście nie dowodzi, że jej nie ma.

Memory maintenance daje pierwszeństwo wypowiedziom użytkownika przy dopasowaniu
do budżetu kontekstu i uwzględnia uwierzytelnione odpowiedzi na natywne pytania
w kolejności czasowej. Zachowuje zasady trwałości i zakresu pamięci: tymczasowe
zadanie nie staje się stałym stanowiskiem. Link `?agent=<slug>` otwiera danego agenta.

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
  kosztuje.
  Firefox nie ma wbudowanego rozpoznawania mowy. Kompozytor informuje, jeśli mikrofon lub rozpoznawanie są niedostępne.

Przy dyktowaniu u providera główny czat pokazuje wewnątrz kompozytora Anuluj, poziom dźwięku, licznik czasu i Stop.
**Enter**
zatrzymuje i transkrybuje, **Escape** anuluje, a nic, co wpiszesz albo naciśniesz
w trakcie nagrywania lub transkrypcji, nie zostaje wysłane. Nagranie zatrzymuje
się samo na najdłuższym dyktowaniu organizacji i jest transkrybowane, a mikrofon
odłączony w trakcie kończy je tak samo, zamiast je odrzucać. Gdy wysyłanie trwa
dłużej niż sekundę, pigułka pokazuje, ile już poszło; potem mówi
**Przepisywanie**, dopóki nie przyjdzie tekst.

Rozpoznawanie w przeglądarce pokazuje **Słuchanie** i akcję **Zakończ dyktowanie**. Wpisanie lub wysłanie tekstu kończy dyktowanie. Główny przycisk zmienia się w Wyślij, gdy wiadomość jest gotowa.

Komunikaty dyktowania pojawiają się nad kompozytorem: prośba o uprawnienia, zablokowany albo brakujący mikrofon, ostatnie
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
cała konsola: **Systemowe (System)** idą za ustawieniem ograniczenia
ruchu w systemie operacyjnym, **Ograniczone (Reduce)** ograniczają ruch bez
niego, a **Pełne (Full)** (domyślne w nowej przeglądarce) zachowują ruch niezależnie od systemu operacyjnego. Gdy ruch jest ograniczony, nie ma żadnej poświaty, pasek
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

Na górze rozgałęzienia widać **Rozgałęzienie rozmowy** z linkiem do oryginału, a na liście rozmów znak rozgałęzienia przed tytułem podaje nazwę oryginału. Oba widzisz tylko ty: jeśli udostępnisz rozgałęzienie, odbiorca zobaczy zwykłą rozmowę.

Rozgałęzienie może obejmować najwyżej 2000 wiadomości, 10 000 wywołań narzędzi i 20 MiB kopiowanego tekstu oraz danych strukturalnych. Limit wynosi dziesięć żądań na minutę na członka i organizację. Aktualizowana rozmowa może chwilowo odmówić rozgałęzienia; spróbuj ponownie po zakończeniu aktualizacji. Historię przekraczającą limit trzeba skrócić przed skopiowaniem.

Zachowane rozgałęzienia mają osobny limit 100 MiB na członka w organizacji i 1 GiB na całą organizację. Kopia rezerwuje rozmiar treści oraz 4 KiB na rozmowę i 1 KiB na wiadomość lub wywołanie narzędzia. PostgreSQL szereguje przyjmowanie kopii, więc równoległe żądania nie przekraczają limitu. Przydział zwalnia dopiero usunięcie samej kopii; usunięcie źródła lub archiwizacja go nie zwalnia. Rysunku z zapisanymi plikami obrazów nie można obecnie rozgałęzić. Wybierz wcześniejszą odpowiedź; żądanie jest odrzucane przed utworzeniem uszkodzonej kopii.

Tekst i media zapisane poza bazą w kopiowanym podsumowaniu są odtwarzane w rozgałęzieniu, więc usunięcie oryginału nie usuwa tego kontekstu. Odtworzona treść wlicza się do limitu 20 MiB. Odtwarzanie obejmuje najwyżej 100 odwołań i trwa do dziesięciu sekund. Niedostępna treść lub przekroczenie limitu przerywa operację bez tworzenia częściowej kopii.

Rozmowę z zapisaną checklistą można rozgałęzić tylko przy jej najnowszej wiadomości, jeśli jest odpowiedzią agenta. Kopia zachowuje checklistę, w tym identyfikatory zadań i zależności. Wcześniejsze wersje checklisty nie są przechowywane, dlatego wcześniejsze rozgałęzienie jest odrzucane, aby nie kopiować późniejszych zadań do starszej historii.

### Tematy w tle { #background-topics }

Włącz **Tematy w tle** u opublikowanego agenta i poproś np.: „Zbadaj błąd eksportu w nowym temacie, a my kontynuujmy plan wydania” albo „Niech agent finansowy sprawdzi te liczby, gdy omawiamy ofertę”. Agent może użyć swojej przypiętej wersji albo opublikowanego delegata przypiętego w specyfikacji. Zacznij z rozmowy, której jesteś właścicielem; nowy temat należy do tego samego projektu i zawiera brief agenta oraz odnośnik do źródła, bez kopiowania pierwotnego transkryptu.

Otwórz **Pracę w tle** w pasku bocznym, aby zobaczyć zadania aktywne i zakończone. Otwórz osobny temat, aby sprawdzić pracę lub odpowiedzieć na zwykłą prośbę o zgodę albo pytanie. **Zatrzymaj** anuluje dalszą pracę; nie cofa wykonanych zmian plików ani działań w usługach. Na pulpicie jest też widżet pracy w tle. Jedna osoba może mieć do czterech aktywnych zadań; zadanie i odpowiedź z jego wynikiem nie mogą tworzyć kolejnych tematów w tle.

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

| Obszar            | Zawiera                                                                                        | Przeczytaj                                                               |
| ----------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| **Agents**        | Katalog, Builder, wersje, udostępnianie, testowanie, aktywność                                 | [Twój pierwszy agent](first-agent.md)                                    |
| **Chat**          | Rozmowa z opublikowanym agentem                                                                | [Powierzchnie](channels.md)                                              |
| **Knowledge**     | Kolekcje, dokumenty, źródła synchronizacji, ustawienia ingestii                                | [Przetwarzanie plików](file-processing.md)                               |
| **Skills**        | Spisane procedury, które agent wczytuje na żądanie                                             | [Skille](skills.md)                                                      |
| **Context**       | Stała wiedza przypięta do wielu agentów                                                        | [Pliki kontekstowe](context.md)                                          |
| **Tables**        | Typowane rekordy i ich kolumny, oglądane jako tabela, tablica kanban lub lista                 | [Virtual Tables](virtual-tables.md)                                      |
| **Workflows**     | Wieloetapowe automatyzacje, które uruchamiają Twoje agenty, budowane na kanwie                 | [Workflows](workflows.md)                                                |
| **Datasets**      | Wersjonowane przypadki testowe, importowane, eksportowane albo dodawane z ocenionej odpowiedzi | [Datasety](datasets.md)                                                  |
| **Routines**      | Harmonogramy i wyzwalacze zdarzeń                                                              | [Wyzwalacze](triggers.md)                                                |
| **Runs**          | Co się uruchomiło, ile kosztowało, czego dotknęło, czy zakończyło się błędem                   | [Nadzór](governance.md#audit)                                            |
| **Documents**     | Wszystkie pliki, które agenci trzymają dla ciebie: to, co załączyłeś, i to, co napisali        | [Sandbox](sandbox.md#what-the-file-browser-shows-and-what-it-leaves-out) |
| **Sandboxes**     | Gdzie agenci uruchamiają kod: hosty, żywe sesje, polityka                                      | [Sandbox](sandbox.md)                                                    |
| **MCP servers**   | Połączenia z zewnętrznymi narzędziami, osobiste i na całą organizację                          | [MCP](mcp.md)                                                            |
| **Channels**      | Boty Slacka, Teams, Telegrama i Mattermosta, widgety, hostowane strony                         | [Powierzchnie](channels.md)                                              |
| **Remote agents** | Agenci innych dostawców, zarejestrowani po ich agent card A2A, do których delegują agenci      | [Capabilities](reference/capabilities.md#remote-agents)                  |
| **Vault**         | Poświadczenia, zapieczętowane per organizacja                                                  | [Sekrety](secrets.md)                                                    |
| **Organizations** | Członkowie, role, zaproszenia                                                                  | [Uprawnienia](permissions.md)                                            |
| **Settings**      | Providerzy, domyślne ustawienia ingestii, powiadomienia, twój własny profil                    | [Konfiguracja](configuration.md)                                         |
| **Admin**         | Sam deployment: użytkownicy, najemcy, system, zadania w tle, ustawienia deploymentu            | [Deployment](deployment.md)                                              |

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

Szczegóły organizacji mają trzy zakładki: **Members**, **Budget and approvals** oraz **AI & services**. Members pozwala szukać po nazwie i e-mailu, filtrować role i sprawdzić ostatnie zapisane działanie w tym workspace. To działanie z audytu, nie wizyta ani logowanie; działania przez impersonację są pomijane, a brak historii pokazuje kreskę. **Edit workspace** otwiera okno nazwy, avatara i koloru z ochroną niezapisanych zmian. AI & services zawiera osobne karty funkcji bez nadrzędnych grup. Rozwijanie konfiguracji zachowuje szkice. Każda kontrolka zachowuje własne uprawnienia. Stare linki `?tab=profile` otwierają modal workspace, a `?tab=voice` i `?tab=proactivity` odpowiednie ustawienia w AI & services.

Codzienny briefing i sugestie to jedna usługa, konfigurowana w jednym miejscu. Jej karta pokazuje też wydatki i ostatnie wykonania. Utrzymanie pamięci ma własny model i budżet oraz zaczyna jako wyłączone. Najpierw wybierz model, potem włącz usługę. AI Architect pokazuje przełącznik i bezpośredni link do Agent Buildera bez edytora powitania i dodatkowego rozwijania. Pozostałe usługi używają wspólnego nagłówka i układu ikon; rozwijają się tylko wtedy, gdy zawierają ustawienia do edycji.

Po zalogowaniu zaproszenia wysłane na e-mail konta pojawiają się także w konsoli i onboardingu, bez otwierania linku z wiadomości. Odbiorca wybiera organizację i jawnie przyjmuje zaproszenie; Później zostawia dostępny skrót Zaproszenia. Lista zawiera tylko aktualne zaproszenia na bieżący adres konta, bez linków współdzielonych i organizacji, do których użytkownik już należy. Przyjęcie przełącza organizację i otwiera jej powitanie. Serwer nie zwraca tokenu zaproszenia w tej skrzynce.

Skrzynka wymaga potwierdzenia adresu w bieżącej sesji: świeżego logowania przez OAuth ze zweryfikowanym e-mailem lub linku do logowania wysłanego na konkretny adres. Sesje po zalogowaniu hasłem i starsze sesje nie wyświetlają ponaglenia do potwierdzenia skrzynki ani konfiguracji wysyłki e-maili. Zaproszenie można przyjąć przez oryginalny link, także we wdrożeniu bez dostawcy poczty. Potwierdzenie nie przechodzi do innej sesji ani na zmieniony adres. Lista ma stronicowanie przez **Pokaż kolejne zaproszenia**, a dostęp do logo sprawdza konkretne zaproszenie niezależnie od strony listy.

Bursztynowe kropki oznaczają zakładki organizacji i odpowiadające im karty głosu, nocnych sugestii, utrzymania pamięci oraz Architecta, gdy brakuje konfiguracji lub sugestie są wyłączone. Najedź na kropkę lub ustaw na niej fokus, aby przeczytać wyjaśnienie; kliknij lub dotknij, aby je otworzyć. Wskaźniki korzystają z zapisanych ustawień, znikają po uzupełnieniu konfiguracji i respektują uprawnienia do jej zmiany. Wyłączone sugestie są opcją do uruchomienia, a nie błędem. Karta powiadomień iPhone oznacza też brak klucza Apple. Ograniczenie ruchu wyłącza pulsowanie.

Zapisane logowania do stron mają zwarty panel ustawień na pełną szerokość, zamiast rozciągać jeden wpis na całą stronę. Znane usługi pokazują wbudowane logo marki; pozostałe strony korzystają z własnej favicony bez przesyłania odsyłacza, a gdy obraz jest niedostępny — z ikony globu.

## Języki { #languages }

Konsola mówi po angielsku, polsku, niemiecku, turecku, francusku,
niderlandzku i po portugalsku w odmianie brazylijskiej. Pierwsza karta przewodnika proponuje je wszystkie, a menu konta
zmienia język w każdej chwili; wybór jest zapisywany na twoim
koncie, więc konsola otwiera się w nim na każdym urządzeniu, na którym się
logujesz. Możesz też poprosić agenta - "przełącz na angielski" - a strona zmieni
się, gdy odpowie, bez przeładowania. Każdy agent odpowiada w nim, chyba że
jawnie poprosisz o inny język. Słowa produktu - agent, skill, run, budget, MCP i reszta listy z
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

**Chat controls → Tools & files** pokazuje połączenia Claude Code i Codexa, gdy agent korzysta z **Private cloud task with my account**, z osobnymi logotypami i stanem zgody. Każde konto możesz podłączyć lub nim zarządzać bez wychodzenia z czatu; wszystkie konta są w **Settings → Profile**. Zadanie korzysta wyłącznie z włączonego konta osoby, która je rozpoczęła, dla wybranego narzędzia. Domyślne narzędzie jest wyborem początkowym, a nie wyłącznym dostawcą. Podłączenie nie zmienia trybu wykonania agenta; coding na desktopie nadal używa osobnych lokalnych logowań.

## Pierwsze zadanie { #your-first-task }

W nowej organizacji domyślnie wybrany jest dostarczony **AgenticOS**, również przed publikacją, chyba że wybierzesz innego domyślnego agenta. Po pierwszej wiadomości może wyjaśnić konfigurację modelu i pokazać kartę ustawień bez wykonywania draftu ani wywoływania dostawcy AI. Odpowiedź i karta pozostają w historii czatu. Osoby z uprawnieniami konfiguracji otwierają ustawienia modelu agenta; pozostali członkowie widzą wskazówkę dotyczącą administratora i kontakt wsparcia instancji, jeśli został podany. Wybierz model, dodaj klucz, jeśli jest wymagany, i opublikuj agenta, aby uruchomić zwykłe odpowiedzi AI. Zwykłe drafty i zarchiwizowani agenci nadal nie mogą być wykonywani.

Onboarding Studio przedstawia zainstalowanych AgenticOS i Architect. Jeśli dostarczony AgenticOS jest dostępnym draftem konfiguracyjnym, przycisk otwiera rozmowę o konfiguracji; publikacja i zwykłe wykonywanie agenta nadal wymagają dotychczasowych uprawnień. Uprawniona osoba może skonfigurować Architect, gdy brakuje mu modelu. Zwykłe drafty i niedostępni agenci nie stają się wykonywalni przez onboarding.

Zamknięcie propozycji startowej odkłada ją na obowiązujący dla tego członkostwa okres 1, 3 lub 7 dni według czasu serwera. Może wrócić, jeśli konfiguracja pozostaje nieukończona, a przypomnienia są włączone. Po przejściu pytań **Zakończ konfigurację i otwórz aplikację** zapisuje ukończenie dla tego członkostwa. Opcjonalne pola, zaproszenia, model, agent ani run AI nie są wymagane. Ukończenie onboardingu i udane zadanie to osobne stany.

Otwórz **Pierwsze kroki** z dashboardu, propozycji przy pierwszym użyciu lub pomocy
strony. Na desktopie baner startowy czatu jest półprzezroczystą nakładką nad konsolą.
Oba panele nawigacji zachowują pełną wysokość. Administratorowi proponuje konfigurację, a członkowi
przykład; można go zamknąć. Przyjęte zaproszenie otwiera ten sam start w organizacji, do której
właśnie dołączasz. Rejestracja próbuje od razu zalogować konto; gdy sesja się nie
powiedzie, formularz logowania zachowuje cel i już utworzone konto.

Start uwzględnia uprawnienia osoby i jej dotychczasową pracę:

| Osoba                                                | Prowadzony start                                                                                  |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Administrator aplikacji                              | Utworzenie lub wybór firmy, tożsamość i zaproszenia, następnie zasady dołączania przyszłych kont. |
| Administrator organizacji                            | Przygotowanie organizacji i jej limitu wydatków, bez ustawień wdrożenia.                          |
| Nowe konto członka                                   | Powitanie, opcjonalny profil osobisty i kontekst pracy, potem pierwsze zadanie.                   |
| Istniejące konto dołączające do kolejnej organizacji | Powitanie w tej organizacji, użycie zapisanego profilu lub jego świadomy przegląd.                |

Przewodnik AgenticOS objaśnia każdą decyzję przygotowanymi wiadomościami interfejsu.
Nie są odpowiedziami modelu i nie wywołują AI. Profil i kontekst pracy są wspólne dla
organizacji konta. Dane opcjonalne można pominąć. **Zapisz i kontynuuj** prowadzi
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

Adres URL zachowuje krok, pytanie konfiguracji i organizację po odświeżeniu. Nie przechowuje
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

Wybór okresu znajduje się obok zakładek widoku dashboardu. Ostatnie wizualizacje korzystają najpierw z zapisanych miniatur; gdy miniatura jest niedostępna, rysunek jest odtwarzany dla właściciela i renderowany w izolowanej ramce, gdy karta zbliża się do widocznego obszaru. Ten podgląd nie wymaga przeglądarki na serwerze.

Wyszukiwanie otwiera przycisk lupy obok zwijania paska bocznego; skrót klawiaturowy nadal działa. Na komputerze obszar roboczy ma zaokrągloną ramę obok paska bocznego. Galerie umieszczają karty zasobów bezpośrednio na stronie.

Dashboard pokazuje wskazówki Discover pod danymi. Briefing używa wierszy z akcjami obok tekstu, gdy pozwala na to szerokość. Wyjaśnienie pustego widżetu rozwija się z jego podsumowania; błędy i przyciski ponowienia pozostają widoczne.

Edytor agenta wyróżnia Test, Otwórz w czacie i Publikuj. Więcej akcji zawiera udostępnianie, mapę, wznowienie rozmowy i eksport. Aktywność łączy okres, filtry, wybór kolumn i eksport w jednym pasku. Kolumny mogą pokazywać autora, źródło, model i tokeny; koszt, czas trwania i data pozostają w głównej tabeli.

Ustawienia mają poziome, przewijane zakładki na komputerze i telefonie. Zwykłe sekcje rozdzielają linie, a działania nieodwracalne zachowują ramę ostrzeżenia. W czacie kontekst projektu znajduje się nad polem wiadomości, a zużycie w Ustawieniach czatu. Nawigacja zachowuje wspólny układ bez wygaszania treści.

Grupy paska bocznego rozwijają się i zwijają płynnie. Ukryte miejsca nie przyjmują fokusu, a po zwinięciu paska bieżąca strona pozostaje widoczna. Animacje respektują ustawienia Wyglądu; ograniczenie ruchu pozostawia kontrolki nieruchome.

Ustawienia zachowują poziome taby. Klucze API i klienci MCP są razem w **API i MCP**, z oddzielnymi kontrolami dostępu i zachowanymi adresami; domyślnie otwiera się MCP, a adres URL może wskazać każdą z zakładek. Konfiguracja aplikacji mobilnej jest pod **Account**. Profil układa dane osobowe i kontekst agentów obok siebie na szerokim ekranie, z osobnymi kartami wyglądu i połączonych kont. Kontenery list wypełniają dostępną wysokość. Organizacje i grupy otwiera się przez **Manage organizations** w przełączniku workspace, bez powielania ich w sidebarze. Puste strony, listy i tabele korzystają ze wspólnej ilustracji. Directory czeka na uprawnienia i dane, zanim pokaże pojedynczą akcję utworzenia mapowania.

Ustawienia osobiste nie mają osobnej zakładki Assistant. Wskazówki stron znajdują się w **Account**, a stary adres `/settings/assistant` przekierowuje do tej zakładki. **Inbox preferences** zawiera osobisty przełącznik dostarczania nocnych sugestii; historia sugestii i ich przywracanie pozostają w Inbox. Modele organizacji, budżety, utrzymanie pamięci i Voice pozostają w **AI & services**. Etykiety formularzy mają wspólną minimalną wysokość, również przy przycisku pomocy. Standardowe pola tekstowe i selecty mają jednakową wysokość oraz większe obszary dotykowe przy niedokładnym wskaźniku. Kompaktowe filtry tabel zachowują własny rozmiar. Konfiguracja MCP ma jedną własną ramkę zamiast dodatkowego obramowanego kontenera.

Selektor stosuje wybór modelu bez powiadomienia o sukcesie. Przycisk **Powrót do modelu agenta** usuwa model wybrany dla rozmowy. Subskrypcje mają osobny krok po kontekście osobistym w onboardingu: każdy kafelek usługi ma bezpośredni przycisk **Połącz**. **Settings → Subscriptions** pokazuje osobny wiersz dla każdego konta, wyszukiwanie, paginację i okna limitów zgłoszone przez usługę; brak danych jest jawnie oznaczony.

Trzy układy onboardingu można porównać pod adresami `/onboarding?variant=conversation`, `?variant=studio` i `?variant=launchpad`: kolumna rozmowy, studio z boczną ścieżką oraz szeroki launchpad. Korzystają z tych samych formularzy, uprawnień i zapisów. Przełącznik układu zachowuje bieżący krok i szkice w zamontowanych formularzach. Wiadomości przewodnika pojawiają się stopniowo; czytnik ekranu otrzymuje pełny komunikat, a ograniczenie animacji wyświetla tekst statycznie.

Warianty dodają wybór modelu ze zwykłego katalogu dostawców, istniejących kluczy Vault i formularzy podłączeń, a następnie katalog MCP z kontami prywatnymi i wspólnymi. Model jest zapamiętywany dla nowych czatów danej osoby, bez zmiany opublikowanego modelu wspólnego agenta. Podłączenie MCP nie udostępnia narzędzi wszystkim agentom.

Administrator może przejrzeć ustawienia zespołu i wdrożenia albo przejść od razu do zainstalowanych AgenticOS i Architect. Otwarcie agenta nie wysyła zapytania do modelu; niedostępny agent zachowuje wskazówki konfiguracji.

Studio jest domyślne pod `/onboarding`; pozostałe układy pozostają dostępne przez parametry podglądu. Studio ma jedną kolumnę formularza i krótką ścieżkę z boku, bez powtarzanych dekoracyjnych postaci. Wygląd profilu można wybrać w przesuwanej karuzeli rzeczywistych kolorów avatara konta: przeglądanie nie zapisuje wyboru, a wybranie korzysta z dotychczasowego zapisu konta. Animacje respektują ustawienia aplikacji i systemu.

Studio zachowuje położenie nagłówka i dolnych przycisków podczas zmiany kroku. Galeria avatarów ustawia podgląd na środku po przeciągnięciu lub użyciu strzałek; dopiero wybranie podglądu go zapisuje. Ograniczenie ruchu wyłącza sprężyste przejścia galerii i ruch kroków. Przypomnienie o niedokończonej konfiguracji pozostaje wyłącznie w pasku bocznym, bez drugiego banera nad obszarem pracy.

Nowe konta otwierają `/onboarding` po rejestracji hasłem lub pierwszym logowaniu OAuth albo katalogowym, również przy rejestracji z zaproszenia. Język i wygląd poprzedzają konfigurację przestrzeni; tutaj można też sprawdzić i przyjąć zaproszenia. Dołączenie wymaga świadomego wyboru. Język zapisuje się na koncie i trafia do agentów przez `{{language}}` oraz briefing osoby. Jawna prośba o inny język ma pierwszeństwo.

Po subskrypcjach konfiguracja modelu pokazuje najpierw dostawcę, następnie połączenie i model. Subskrypcje osobiste pozostają w poprzednim kroku. Narzędzia zaczynają od sugerowanych usług; **Przeglądaj wszystkie usługi** otwiera pełny katalog MCP.

Gdy agent zadaje pytanie, karta i zwykły edytor pozostają widoczne razem. Edytor zachowuje szkic i załączniki; nowe wiadomości czekają w kolejce, a odpowiedź na pytanie wysyłasz przez kartę. Zatrzymanie odpowiedzi wstrzymuje kolejkę do jej świadomego wznowienia. Zwykłe zakończenie odpowiedzi nadal uruchamia kolejne wiadomości.


## Płaska lista ostatnich chatów { #flat-recent-chat-list }

Nagłówek Chatów oferuje **Ostatnią aktywność (płaską listę)**. Łączy chaty projektowe i zwykłe w jedną listę według ostatniej aktywności, bez nagłówków projektów, nieprzeczytanych i ulubionych. Ulubione zachowują gwiazdki, ale nie są przypinane ponad nowszą aktywnością. Paginacja korzysta z tej kolejności na serwerze, więc stare ulubione nie wypychają ostatnich chatów z pierwszej strony. Dotychczasowe filtry agenta, archiwum i API nadal działają. Wybór jest zapisywany w tej przeglądarce osobno dla każdego zalogowanego użytkownika; **Grupuj chaty według projektu** przywraca domyślny widok grupowany.
