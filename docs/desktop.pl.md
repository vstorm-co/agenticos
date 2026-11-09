---
source_sha: "b0d63e54b2c9"
---

# Aplikacja desktopowa { #the-desktop-app }

Natywne logowanie OAuth korzysta z PKCE S256. Aplikacja zachowuje prywatny weryfikator, a callback przenosi tylko jego publiczny skrót. Weryfikator jest wysyłany w treści żądania wymiany, nigdy w adresie URL. Wylogowanie usuwa natywne podglądy powiadomień telefonu.

Odłączenie, wylogowanie lub zmiana serwera usuwa zgody na foldery, lokalne usługi, cały komputer i ekran. Parowanie pokazuje konto przed zużyciem jednorazowego kodu. Wspólne zgody na foldery procedur przetrwają wygaśnięcie sesji i ponowne sparowanie z tym samym zweryfikowanym kontem i serwerem. Pozostają nieaktywne do ponownej weryfikacji tej tożsamości; jawne odłączenie, wylogowanie lub zmiana serwera albo konta je usuwa.

Opublikowany delegat potrzebujący tego komputera może poprosić o zgodę w tej samej rozmowie, także gdy główny agent działa w chmurze. Zgoda należy do głównego agenta rozpoczynającego uruchomienie. Lokalny delegat kodujący prosi o pełny dostęp; zagnieżdżeni delegaci korzystają z zatwierdzonej przestrzeni urządzenia, bez udostępniania jej innym delegatom chmurowym. Anulowanie lub przekroczenie limitu czasu komendy zatrzymuje też jej procesy potomne.

AgenticOS działa w przeglądarce i tak używa go większość ludzi. Aplikacja
desktopowa jest dla tych, którzy chcą więcej na własnym komputerze: konsola we
własnym oknie, szybkie pytanie z dowolnego miejsca, blobby na pulpicie i - to,
czego przeglądarka nie potrafi - własne agenty pracujące w folderze na tym
komputerze i na jego ekranie. Nic w samej platformie jej nie potrzebuje.

> **Miejsce na zrzut — aplikacja desktopowa, blobby i szybkie pytanie.**

Aplikacja w oknie to ta sama konsola Next.js, którą serwer już serwuje, ładowana
z serwera, więc ma to samo logowanie, te same uprawnienia i te same kontrole
tenanta co karta przeglądarki. To powłoka [Tauri](https://tauri.app) w
`desktop/`.

!!! note "To powłoka, a nie build frontendu"

    `frontend/` to aplikacja Next.js z połową serwerową - route handlery
    przekazujące żądania do backendu, ustawiane przez nie ciasteczka sesji,
    middleware wybierające język i strony renderowane na serwerze. Nic z tego nie
    działa wewnątrz binarki desktopowej, więc powłoka nawet nie próbuje: otwiera
    URL wdrożenia tak, jak zrobiłaby to przeglądarka. Instalujesz wdrożenie;
    aplikacja to sposób, w jaki je otwierasz.

Bez zapisanej preferencji desktop uruchamia się z motywem **Systemowym** i stylem
**Glass**. Wcześniejszy jawny wybór motywu lub stylu ma pierwszeństwo.

W **Chat controls → Computer use** wybierz **Lokalny komputer**, aby udostępnić tej rozmowie narzędzia zrzutów ekranu, myszy i klawiatury, nawet jeśli agent nie ma zdolności Computer use. Wybór jest niezależny od Browser i Work on: nie daje dostępu do folderu ani komend i nie zmienia opublikowanego agenta. Osoba rozpoczynająca pracę musi mieć połączone własne, sparowane urządzenie; nadal obowiązują natywna zgoda na ekran i uprawnienia systemu operacyjnego.

Powrót z ustawień systemowych odświeża gotowość również wtedy, gdy webview pozostaje widoczny. Jeśli Screen Recording jest włączone, ale dostęp nadal jest odrzucany, zamknij i otwórz uruchomioną kopię aplikacji, a następnie odśwież status. Uprawnienia mogą różnić się między zainstalowaną wersją a testową kopią z podpisem ad-hoc.

Lokalne zadania ACP kończą się po 16 384 zdarzeniach wejściowych lub 8 MiB łącznych zserializowanych aktualizacji, wliczając odtworzenie sesji. Błąd jest jawny, a adapter zostaje zamknięty.

Zapisany pin certyfikatu wydawcy wymaga właściwego materiału podpisu: brak MACOS_SELF_SIGNED_P12 zatrzymuje wydanie. Podpis ad-hoc jest dostępny wyłącznie w dystrybucji bez pinu.

## Instalacja aplikacji { #installing-the-app }

Pobierz paczkę dla swojego komputera z [wydania na GitHubie](https://github.com/vstorm-co/agenticos/releases/latest). Instalacja wydania nie wymaga Rusta ani narzędzi programistycznych.

- **macOS:** wybierz Apple silicon lub Intel, otwórz `.dmg` i przeciągnij AgenticOS do **Applications** zgodnie ze strzałką. Uruchom aplikację z Applications i wysuń obraz dysku.
- **macOS bez ostrzeżenia:** `curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/install_macos.sh | bash` pobiera wydanie, sprawdza jego SHA-256 z opublikowaną sumą, kopiuje aplikację do Applications i zdejmuje z tej jednej aplikacji flagę pobrania. `brew install --cask vstorm-co/agenticos/agenticos` robi to samo przez [tap projektu](https://github.com/vstorm-co/homebrew-agenticos). Wydania nie są notaryzowane przez Apple, więc `.dmg` pobrany w przeglądarce nadal wymaga **Otwórz mimo to**. Gdy projekt przypnie certyfikat, którym podpisuje wydania (`scripts/macos_signing_identity.txt`), skrypt odmawia też instalacji aplikacji podpisanej czymkolwiek innym.
- **Windows:** otwórz instalator `setup.exe`. Wybierze język systemu i zainstaluje aplikację dla Twojego użytkownika bez uprawnień administratora. Uruchom AgenticOS z menu Start. Pakiet `.msi` jest również dostępny dla zarządzanych wdrożeń.
- **Linux:** otwórz `.deb` lub `.rpm` w instalatorze oprogramowania swojej dystrybucji. W wersji przenośnej nadaj plikowi `.AppImage` prawo wykonywania we właściwościach i otwórz go.

Pierwsze uruchomienie prowadzi przez połączenie z serwerem lub stworzenie lokalnej instancji. Docker jest potrzebny tylko lokalnej instancji; kreator wykrywa go i proponuje pobranie, jeśli go brakuje. Instalacja nie przyznaje dostępu do ekranu ani mikrofonu.

[Dlaczego macOS pokazuje ostrzeżenie](howto/macos-warning.md).

### Widgety na pulpicie macOS { #desktop-widgets-on-macos }

Na macOS 14 lub nowszym uruchom zainstalowaną aplikację raz, kliknij pulpit prawym przyciskiem, wybierz **Edytuj widżety** i wyszukaj **AgenticOS**. Mały widget otwiera Quick Ask, a średni również Chat, Inbox i Activity. Widgety korzystają z wyglądu systemowego i zawierają tylko skróty, bez danych konta. Kliknięcie widgetu nigdy nie rozpoczyna nagrywania ani połączenia.

CI wydania buduje natywne paczki dla Maca (Apple silicon i Intel), Windowsa i Linuksa. Paczki macOS używają stałego, samopodpisanego certyfikatu. Podpis ad-hoc jest możliwy tylko w dystrybucji bez pinu wydawcy; paczki nie mają notaryzacji Apple. Po skopiowaniu aplikacji do Applications spróbuj ją uruchomić. Jeśli macOS blokuje ją z powodu niezweryfikowanego dewelopera, wybierz **Ustawienia systemowe → Prywatność i ochrona → Otwórz mimo to** i potwierdź. Zarządzane komputery mogą zabraniać tego wyjątku. Zobacz [instrukcję Apple](https://support.apple.com/pl-pl/102445). Pobierane aktualizacje nadal wymagają poprawnego podpisu kluczem aktualizacji wydania.

Po aktualizacji z podpisem ad-hoc macOS może ponownie poprosić o dostęp do mikrofonu, nagrywania ekranu, dostępności lub Pęku kluczy. Jeśli urządzenie utraci sparowanie, połącz je ponownie. Podpis aktualizacji weryfikuje paczkę, ale nie zapewnia stałej tożsamości podpisu Apple.

Gdy workflow wydania ma stały, samopodpisany certyfikat (tworzy go `scripts/create_macos_signing_cert.sh`), macOS zachowuje zgody na nagrywanie ekranu i mikrofon po aktualizacjach, bo są związane z tożsamością podpisu. Utwórz go raz i nigdy nie wymieniaj: nowy certyfikat ponownie pyta wszystkich użytkowników. Samopodpisanie nie usuwa ostrzeżenia Gatekeepera; robi to tylko podpis Developer ID z notaryzacją.

## Uruchamianie { #running-it }

Przed wyborem lokalnej instalacji lub połączeniem z serwerem kreator pierwszego
uruchomienia oferuje opcjonalne uprawnienia Screen Recording, Accessibility i Microphone na macOS.
Każdy przycisk otwiera odpowiednie ustawienia systemowe; konfiguracja niczego nie
przechwytuje ani nie steruje komputerem. Można kontynuować bez żadnego z nich. Powrót z
ustawień odświeża ich status; macOS może wymagać restartu aplikacji. Dostęp do folderów jest nadal żądany przy użyciu. Mikrofon macOS prosi zwykłym okienkiem; pozostałe dwa otwierają Ustawienia systemowe. Pierwsze okno otwiera się na 80% ekranu, wyśrodkowane, a potem pamięta rozmiar i miejsce.

Wymagane są Rust z [rustup](https://rustup.rs) i webview platformy - WebKit na
macOS, WebView2 na Windows, WebKitGTK na Linuksie; listę dla każdej platformy ma
[strona wymagań](https://v2.tauri.app/start/prerequisites/) Tauri. Tauri CLI jest
przypięte w `desktop/package.json`, a `make install` pobiera je razem z resztą.

```bash
make desktop-dev     # opens the shell
make desktop-build   # a .app / .dmg, .msi or .deb/.AppImage for this machine
make desktop-check   # rustfmt, clippy with warnings denied, and the tests
```

Przy pierwszym uruchomieniu aplikacja pyta, gdzie jest AgenticOS:

- **Na tym komputerze.** Aplikacja sprawdza Dockera, uruchamia opublikowane obrazy
  z konsolą i API tylko na loopbacku, tworzy twoją organizację i jej właściciela,
  a potem uruchamia, zatrzymuje i aktualizuje ten stos z paska menu.
- **Na serwerze twojej organizacji.** Wpisz jego adres; sama nazwa hosta
  (`agenticos.acme.com`) jest otwierana przez HTTPS. Logujesz się we własnej
  przeglądarce (zobacz [Logowanie](#signing-in)).

!!! warning "Zwykłe `http://` tylko dla tego komputera"

    `localhost`, `127.0.0.1` i `::1` mogą być osiągane otwartym tekstem; każdy inny
    host jest odrzucany, dopóki nie będzie `https://`. Konsola wysyła hasło i
    dostaje token z powrotem tym połączeniem, a sieć lokalna to dokładnie miejsce,
    gdzie ktoś inny może je przeczytać.

Adres, pod którym nic nie odpowiada, też jest odrzucany: powłoka otwiera
połączenie TCP, zanim skieruje gdziekolwiek webview, bo WebKit rysuje odrzucone
połączenie jako puste białe okno.

Ustawienia są w `server.json` w katalogu konfiguracji aplikacji -
`~/Library/Application Support/co.vstorm.agenticos/` na macOS,
`%APPDATA%\\co.vstorm.agenticos\\` na Windows, `~/.config/co.vstorm.agenticos/` na
Linuksie. Plik, który przestał się parsować, jest odkładany jako
`server.json.invalid`, a zapisywany jest nowy. Serwer zmienia się w
**Ustawieniach…** (`⌘,`), z menu w zasobniku albo uruchamiając z
`--server <address>`.

**Zmień serwer…** znajduje się w rozwijanym menu konta na dole paska bocznego
konsoli. Kliknij nazwę konta lub awatar w zwiniętym pasku, a następnie tę opcję,
aby otworzyć formularz połączenia. Jest dostępna również przy ukrytym blobby.

### Docker i wiele lokalnych instancji { #docker-and-multiple-local-instances }

Tworzenie instancji otwiera osobny krok z pogrupowanymi polami przestrzeni,
właściciela i dostawcy. **Cancel** wraca do listy instancji. Blobby jest ukryty
podczas konfiguracji i wraca razem z konsolą zgodnie z zapisanym ustawieniem.

Wybierz **Set up this computer**, aby przygotować lokalne środowisko. AgenticOS
pobiera Docker Desktop 4.97.0 dla Twojego procesora i sprawdza przypiętą sumę
SHA-256. macOS sprawdza instalator przez Gatekeeper, weryfikuje tożsamość podpisu
Docker Inc i prosi o autoryzację systemową.
Windows uruchamia podpisany instalator; brakujące funkcje WSL są przygotowywane
po autoryzacji systemowej. Jeśli wymagany jest restart Windows, uruchom potem
AgenticOS, aby kontynuować. Ubuntu, Debian i Fedora na x86-64 korzystają z
instalatora pakietów systemu. Zaakceptuj warunki pierwszego uruchomienia Dockera.

W Linuksie konfiguracja dodaje podpisane źródło pakietów Dockera, jeśli go brakuje,
i prosi o uprawnienia administratora do instalacji pakietów i dostępu do KVM.
Uruchom komputer ponownie, jeśli zostaniesz o to poproszony. Samo sprawdzenie stanu
nie instaluje oprogramowania.

Przed instalacją AgenticOS sprawdza dostępność 4 GB wolnego miejsca. Lokalny stos
wymaga też co najmniej 3 GB pamięci widocznej dla jego silnika. To kontrola startu,
a nie gwarancja zasobów dla każdego zadania. Pobieranie obrazów pokazuje postęp i
ma limit 30 minut. **Retry** kontynuuje tę samą instancję z zachowaniem kluczy.
Zwykłe korzystanie z aplikacji nie wymaga Gita, Pythona, uv ani Node.js na hoście.

Nowe instancje mają przypiętą wersję platformy dostarczoną z aplikacją. Aktualizacja
aplikacji desktopowej nie zmienia automatycznie wersji działającej instancji.
**Update** pobiera pasujące obrazy platformy, wstrzymuje zapis i przed aktualizacją
tworzy kopię bazy, plików multimedialnych i kluczy wdrożenia w prywatnym katalogu
`backups/` instancji. Nieudana kopia blokuje aktualizację. Kopie zawierają dane
osobowe i wymagają ochrony. Błąd migracji jest zgłaszany; baza nie jest automatycznie
cofana do wcześniejszego schematu.

Otwarcie AgenticOS automatycznie uruchamia zapisaną, zarządzaną lokalną instancję,
jeśli jest zatrzymana, wraz z zainstalowanym środowiskiem na wspieranych systemach. Serwery zewnętrzne
i niezarządzane środowiska deweloperskie nie są uruchamiane. Aplikacja przekazuje
procesom potomnym katalogi CLI i narzędzi poświadczeń Dockera, także po uruchomieniu
z Findera; nie musisz edytować konfiguracji poświadczeń Dockera ani profilu powłoki.

Publiczne obrazy produktu są pobierane z prywatną, anonimową konfiguracją rejestru,
co pozwala uniknąć monitów narzędzi poświadczeń i pęku kluczy. Twoja istniejąca
konfiguracja Dockera pozostaje bez zmian. Instalacja lokalna odrzuca konteksty
wskazujące na zdalny silnik.

Wybierz **New instance**, nadaj nazwę i podaj organizację oraz konto właściciela.
Aplikacja przydziela wolne porty loopback i tworzy osobny projekt Compose z własną
bazą, wolumenem plików, siecią, katalogiem roboczym i kluczami wdrożenia. Cookies
sesji mają osobną przestrzeń nazw dla każdej instancji, więc przełączenie nie
zastępuje logowania innej instalacji. Obrazy frontendu muszą zawierać tę obsługę;
konfiguracja odrzuca starszy obraz przed utworzeniem właściciela i otwarciem sesji.

Ekran lokalny pokazuje zapisane instancje, adresy i stan uruchomienia. **Start and
connect** uruchamia wybraną instancję; **Finish setup** ponawia przerwaną instalację
z zachowaniem jej plików i kluczy. Start, Stop i Update w menu dotyczą połączonej,
zarządzanej instancji. Połączenie do samodzielnie uruchomionego stosu deweloperskiego
nie przekazuje aplikacji zarządzania nim.

Lokalna instancja uruchamia API, workera, konsolę, bazę danych i Redis, bez
usługi sandboxa, usługi przeglądarki i magazynu obiektów. Agenci dostają
workspace przechowujący same pliki. W **Chat controls → Tools & files** wybierz
**Work on → This computer** dla dostępu do folderów oraz **Browser → Local browser**
dla przeglądania. **Computer use** oddzielnie udostępnia ekran, mysz i klawiaturę.

Metadane znajdują się w `local-instances.json` w katalogu konfiguracji; pliki nowych
instancji w `local-stacks/<id>/` w katalogu danych aplikacji. Istniejące instalacje
`local-stack/` zachowują projekt Compose i dane. Hasła oraz klucze dostawców trafiają
do bootstrapu bez zapisywania w tych plikach ani umieszczania w argumentach Dockera.
Klucze wdrożenia pozostają w prywatnym `.env` instancji, a klucze dostawców zapisuje
sejf serwera. Natywny kreator używa neutralnego oznaczenia fokusu klawiatury i nie
ustawia automatycznie fokusu na przyciskach wyboru.

## Konfiguracja połączenia i gotowość aplikacji { #connection-setup-and-app-readiness }

Menu użytkownika otwiera też bezpośrednio **Gotowość aplikacji**, również z ustawień desktopu. Lista kroków zastępuje pływający licznik konfiguracji i nie zasłania przycisków strony.

Przegląd połączenia jest wycentrowany na natywnym materiale Glass także wtedy,
gdy konsola ma zapisany nieprzezroczysty styl. Wiersze pozostają widoczne podczas
sprawdzania. Połączenie i Kontynuuj od razu pokazują postęp, a dashboard jest
przygotowywany podczas konfiguracji. Animacja wejścia respektuje ograniczenie ruchu.

Połączenie z serwerem otwiera panel gotowości aplikacji także dla istniejącego konta.
Sprawdza on logowanie, połączenie komputera, dostępnego opublikowanego agenta,
model asystenta, skróty i uprawnienia macOS. Dopiero przycisk **Włącz** prosi o
uprawnienie. Można kontynuować bez opcjonalnych elementów i wrócić przez
**Ustawienia → Aplikacja desktopowa** lub natywne menu **Activity & Access**.
Konsola pamięta odłożony przegląd osobno dla konta, organizacji i serwera;
ponowne jawne połączenie proponuje nowy przegląd. Błędy sprawdzania są widoczne
i można ponowić próbę. Powrót z ustawień systemowych odświeża stan uprawnień.

Błędy zrzutów i sterowania ekranem wskazują nagrywanie ekranu lub dostępność;
błędy mikrofonu w Quick Ask prowadzą do tego samego panelu. Po nadaniu uprawnienia
do nagrywania naprawa zrzutu pozwala ponownie uruchomić interaktywny wybór obszaru.
macOS może wymagać restartu aplikacji, zanim nowe uprawnienie zacznie działać.

**Ustawienia → Aplikacja desktopowa → Powiadomienia** kontrolują zakończenia,
błędy, zatwierdzenia, pytania i pozostałe aktualizacje. Podgląd treści jest domyślnie
ukryty; prywatne powiadomienie o zatwierdzeniu otwiera żądanie w aplikacji zamiast
pozwalać na akceptację bez przeczytania. Ustawienia czatu pozwalają wyciszyć rozmowę.
Powiadomienie nie pojawia się, gdy dana rozmowa jest aktywna w konsoli lub Quick Ask.
Dostarczanie nadal zależy od uprawnień systemowych i trybu skupienia macOS.

**Activity & Access** pokazuje trwającą pracę i oczekujące żądania. Otwórz wpis,
aby przejść do konsoli; **Stop** jest dostępne, gdy aplikacja utrzymuje źródłowe
połączenie rozmowy. Inne zadania serwera można otworzyć przyciskiem **Open**.
Menu pozwala też cofnąć pojedyncze zgody na folder lub cały komputer i odzyskać
sterowanie ekranem.

Nagłówek udostępnia **Nowy czat** (`⌘N` lub `Ctrl+N`), przejście do konsoli
i zamknięcie. Nowy czat zeruje wybór rozmowy i kontekst szkicu; edytor pozostaje
pod wątkiem i ma widoczny przycisk wysyłania.

Quick Ask obsługuje `@mention` dla tych samych zasobów co edytor czatu.
Strzałki i Enter lub Tab wybierają zasób, a Escape najpierw zamyka podpowiedzi.
Usunięcie wzmianki usuwa powiązanie zasobu z następnej wiadomości.

## Aplikacja, nie karta { #an-application-not-a-tab }

Na macOS pasek boczny konsoli trzyma przyciski okna i przeciąga okno, okno
pamięta swój rozmiar i miejsce, a zamknięcie go zostawia aplikację w pasku menu.
Pasek menu ma File, Edit, View, Go (`⌘1`-`⌘5`, `⌘[` i `⌘]`) i Window; menu w
zasobniku robi to samo na Windows i Linuksie. Natywne powiadomienia mają Approve i
Reject dla czekającej akceptacji, a Dock lub pasek zadań pokazuje, ile czeka.
**Ustawienia → Aplikacja desktopowa** uruchamia aplikację przy logowaniu, trzyma
ją przy zamkniętym oknie i włącza lub wyłącza licznik.

Nad treścią jest osobny wiersz do przeciągania okna, poza obszarem przewijania,
więc akcje stron i przyciski zamykania paneli pozostają klikalne. Webowy przycisk
Architect jest schowany przy prawej krawędzi konsoli desktopowej i wysuwa się po
najechaniu, zostawiając róg wolny dla akcji kart i natywnego Blobby.

Czat wypełnia obszar treści od samej góry, bez osobnego paska przeciągania i
marginesu strony. Okno można przeciągać za nagłówek listy czatów; jego przyciski
pozostają klikalne.

**Wygląd** w menu konta pozwala wybrać tryb jasny/ciemny oraz Standard, Glass,
Graphite, Midnight i Paper z podglądami. Wiersz menu pokazuje aktualny styl. To te
same ustawienia co **Ustawienia → Profil → Wygląd**; zmiana stylu zachowuje tryb
kolorów, a wybór pozostaje po ponownym uruchomieniu aplikacji.

**Przypięte agenty**: strona agenta oferuje Przypnij do Docka (gdzie indziej do
paska zadań). Przypięty agent jest w menu Docka i w menu zasobnika, jedno
kliknięcie od nowego czatu z nim. Plik upuszczony na ikonę w Docku albo na blobby
zaczyna czat z tym plikiem w załączniku.

## Blobby { #blobby }

Stworek w stylu awatarów agentów, który siedzi na pulpicie, gdy konsola jest
otwarta, zminimalizowana albo zamknięta: jeden z obsady sześciu, twarz jednego z
twoich agentów albo twarz własna. Mówi, kiedy czeka akceptacja, w skrzynce jest
coś nowego albo twoje runy są w toku, i otwiera to po kliknięciu. Przeciągnij go
gdziekolwiek; uszczypnij, przewiń nad nim z wciśniętym `⌘` albo użyj suwaka w
Ustawieniach, żeby zmienić rozmiar. Jego własna zakładka w Ustawieniach wybiera
postać, jak bardzo jest gadatliwy i czy w ogóle pokazuje aktywność.

Jego okno jest przezroczyste, co na macOS wymaga `macOSPrivateApi` w
`tauri.conf.json` - a to wyklucza Mac App Store, dokąd samodzielnie hostowana
konsola i tak się nie wybierała.

## Szybkie pytanie i głos { #quick-ask-and-voice }

**Otwórz AgenticOS** (`⌘⇧O` na macOS, `Ctrl+Shift+O` na pozostałych systemach)
pokazuje konsolę z dowolnej aplikacji. Zmień lub wyczyść skrót w **Ustawienia →
Skróty**. Pasek menu oraz menu zasobnika i Blobby pokazują aktywne skróty otwierania
AgenticOS, szybkiego pytania i zrzutu ekranu do nowego czatu. Oznaczenia odświeżają
się po zmianie skrótu. Menu nie pokazuje skrótu, którego nie udało się zarejestrować.

**Szybkie pytanie** (`⌥Space`, do zmiany) otwiera pływający panel, żeby zapytać
dowolnego agenta z dowolnego miejsca, bez wysuwania konsoli na wierzch. Na macOS
może zabrać to, na co patrzyłeś: tekst zaznaczony w innej aplikacji, schowek albo
pliki zaznaczone w Finderze - każde pokazane przed wysłaniem i tylko wtedy, gdy
pozwoliłeś AgenticOS czytać zaznaczenie.

Przytrzymaj `⌥⇧Space`, żeby dyktować do szybkiego pytania; rozmowa głosowa z
domyślnym agentem ma własny skrót. **Ustawienia → Skróty** zmieniają je
wszystkie: kombinacja potrzebuje co najmniej jednego modyfikatora, taka, którą
trzyma już inna aplikacja, jest odrzucana z zachowaniem starego skrótu, a
**Wyczyść** go wyłącza.

**Zrzut ekranu do nowego czatu** (`⌘⇧A`) pokazuje systemowy celownik; wybrany
obszar trafia do nowego czatu, już w załączniku. Pierwsze naciśnięcie prosi macOS
o Nagrywanie ekranu, które działa po restarcie.

Quick Ask zachowuje pełny zapis rozmowy: twoje pytania, wcześniejsze odpowiedzi,
aktywność narzędzi i wyniki korzystają z widoku wiadomości konsoli. W panelu można
obsłużyć zatwierdzenia, pytania agenta i prośby o połączenie. Tekst oczekujący offline
pozostaje widoczny, a przycisk zatrzymania kończy uruchomienie. Załączniki i cytowane
źródła otwierają się w panelu; przewinięcie w górę wstrzymuje automatyczne przewijanie
aż do powrotu na dół.

Kliknij spinacz, aby wybrać pliki, wklej obraz ze schowka albo upuść pliki na
Quick Ask. Załączniki są widoczne przed wysłaniem i można je usuwać pojedynczo.
Obowiązuje ten sam limit rozmiaru co w czacie. Wysyłanie i rozpoczęcie nowej rozmowy
czekają na zakończenie przesyłania; błąd przesyłania zachowuje szkic wiadomości.
Możesz wysłać plik bez dopisywania tekstu.

Przycisk przypięcia utrzymuje Quick Ask nad innymi aplikacjami po kliknięciu poza
oknem. Odepnij je, aby przywrócić chowanie przy utracie fokusu. Krzyżyk, Escape w
polu wiadomości i skrót Quick Ask nadal mogą schować przypięty panel. Przypięcie
obowiązuje podczas bieżącej sesji aplikacji, także po przeładowaniu strony.

## Praca na tym komputerze { #work-on-this-computer }

Lokalne operacje plikowe korzystają z otwartego uchwytu zatwierdzonego katalogu. Zastąpienie katalogu lub pliku symlinkiem nie przekieruje zapisu poza niego. Sam katalog i jego katalogi nadrzędne są otwierane bez podążania za symlinkami; podgląd i listowanie plików korzystają z tej samej granicy.

Jedyna rzecz, której przeglądarka nie potrafi: czat desktopowy
może pracować w folderze na komputerze, na którym działa aplikacja, zamiast w
chmurze. Narzędzia agenta do plików i powłoki - listowanie, czytanie, zapis,
edycja, uruchamianie - sięgają tego folderu przez aplikację.

**Połącz komputer raz.** W ustawieniach czatu wybierz **Pracuj na → Ten komputer**,
aby połączyć go bezpośrednio. Potwierdź w natywnym oknie, a potem wybierz folder i
tryb dostępu w tym samym panelu. **Ustawienia → Aplikacja desktopowa → Ten komputer
→ Pozwól agentom tu pracować** oferuje tę samą akcję łączenia. Aplikacja dostaje
własną sesję dla tego komputera i przechowuje jej refresh token w systemowym pęku
kluczy. Trzyma jedno wychodzące połączenie WebSocket do device huba serwera
(`/api/v1/ws/device`); nic nie nasłuchuje na komputerze. **Rozłącz** kończy tę sesję.

**Wybierz to dla czatu.** W aplikacji desktopowej ustawienia czatu oferują
**Pracuj na (Work on): Chmura / Ten komputer**. Wybranie tego komputera prosi o
folder w natywnym oknie wyboru i o to, jak daleko agent może w nim sięgać:

Ten komputer zostaje wybrany dopiero po zatwierdzeniu folderu. Lista dostępu
pokazuje zatwierdzony tryb tego folderu; jego zmiana ponownie otwiera natywne okno
wyboru folderu, aby potwierdzić nowe uprawnienia. Anulowanie zachowuje poprzedni
wybór. Folder i tryb pozostają wybrane po zamknięciu ustawień oraz po nadaniu
nowemu czatowi identyfikatora.

| Tryb             | Co agent może                                                             | Jak jest tego pilnowane                                                                                                 |
| ---------------- | ------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Tylko odczyt     | Czytać pliki; nic nie jest zapisywane i żadne polecenie się nie uruchamia | Aplikacja odrzuca zapisy i polecenia                                                                                    |
| Zapis w folderze | Czytać, zapisywać w folderze, uruchamiać polecenia                        | Polecenia działają pod Seatbelt na macOS i bubblewrap na Linuksie, z zapisem tylko w folderze i katalogach tymczasowych |
| Pełny dostęp     | Polecenia działają jako ty, bez piaskownicy                               | Każde polecenie jest najpierw pokazane w natywnym oknie do zatwierdzenia                                                |

Polecenia w folderze mogą czytać wybrany folder i systemowe pliki środowiska
uruchomieniowego, ale nie pozostałe pliki katalogu domowego ani odziedziczone
sekrety aplikacji. Narzędzia potrzebujące tych danych wymagają osobnej zgody na
cały komputer. Bezpośredni odczyt i zapis plików lokalnych mają limit 10 MiB, aby zbyt duży
transfer nie rozłączał urządzenia. Większy zapis jest odrzucany przed kodowaniem
i wysłaniem danych pliku.

Windows oferuje tylko odczyt i pełny dostęp. Linux oferuje zapis w folderze tylko
wtedy, gdy jest zainstalowany `bwrap` z obsługą `--bind-fd`. Aplikacja utrzymuje uchwyt katalogu otwartego bez podążania za dowiązaniami do startu sandboxa, więc zmiana nazwy folderu ani podmiana go na dowiązanie symboliczne nie zmieni zatwierdzonego katalogu. Na Linuksie zmienne środowiskowe zadania są ustawiane wewnątrz sandboxa, a nie w procesie, który go uruchamia; ich wartości są przekazywane przez prywatny deskryptor.

Ścieżka korzenia folderu routine nie może zawierać dowiązań symbolicznych ani junctions. Wybierz rzeczywisty folder w pickerze; dopuszczenie zadania w tle nie rozwiązuje dowiązań w ścieżce korzenia.

**Decyduje komputer, nie serwer.** Wybrane foldery wraz z trybami są trzymane w
ustawieniach aplikacji, a każda operacja podaje folder i tryb, które aplikacja z
nimi porównuje: folder, którego nie wybrałeś, tryb szerszy niż dozwolony albo
ścieżka wychodząca poza folder są odrzucane na komputerze, cokolwiek serwer
poprosił. Wybór jest zapamiętywany dla każdej rozmowy. Nowe czaty dziedziczą ostatni folder
i narzędzia dla konta i organizacji; ustawienia projektu mają pierwszeństwo.
Zgoda na cały komputer udzielona w czacie nigdy nie przechodzi do innej rozmowy;
zgoda udzielona agentowi obowiązuje dla tego agenta (zob. **Cały komputer**).

**Tylko twoje runy.** Czat sięga twojego komputera tylko wtedy, gdy jest twój -
nigdy klucz API, gość widżetu czy czat kogoś innego - a
[trigger](triggers.md) tylko wtedy, gdy działa jako jego twórca, który wskazuje mu
folder swojego komputera w polu **Pracuj na** triggera.

**Gdy komputera nie ma — czat interaktywny.** Run, który poprosił o ten komputer i zastał aplikację
bez połączenia, czeka na nią do dziesięciu minut, a czat o tym mówi. Operacja,
która zastanie aplikację rozłączoną w trakcie runa - zamknięta klapa, zmiana sieci

- czeka do pięciu minut na jej powrót w tej samej sesji, a potem idzie dalej. Gdy
  operacja runa jest w toku, zasobnik mówi, że agent pracuje na tym komputerze.

Serwer sprawdza sesję przed przekazaniem każdej lokalnej operacji. Odwołana lub wygasła sesja odmawia nowej pracy; heartbeat zamyka też bezczynne połączenia. Operacje już w toku są anulowane po zamknięciu połączenia desktopu.

W Builderze **Sandbox → Komputer** zapisuje `backend: local`, bez ścieżki i
natywnej zgody. Każda osoba zatwierdza własne miejsce pracy w czacie desktopowym.
Taki agent nie ma przestrzeni w chmurze, więc **Work on** nie oferuje dla niego
chmury.

Możesz do niego
pisać, zanim cokolwiek udzielisz: odpowiada na to, co nie wymaga plików, i dopiero
gdy prośba potrzebuje twoich plików, pyta, gdzie może pracować - **Cały komputer**
albo folder. Przebieg czeka na twój wybór, a potem czat sam kontynuuje z plikami.
Odpowiedź jest zapamiętywana dla tego agenta na tym komputerze, więc jego kolejne
czaty startują tam bez pytania. W konsoli w przeglądarce, gdzie nie ma komputera do
udostępnienia, agent mówi, że nie ma dostępu do twoich plików. Przy
tworzeniu projektu **Sandbox projektu → Komputer · Twoje pliki** otwiera wybór
prywatnego folderu; inni członkowie zachowują wspólny obszar projektu.

**Cały komputer.** Czat desktopowy oferuje też **Cały komputer**, bez wyboru
folderu. Jedno natywne ostrzeżenie zatwierdza dostęp: dla agenta z obszarem
**Komputer** ostrzeżenie wymienia agenta, a zgoda obowiązuje dla niego w każdej
rozmowie; w pozostałych przypadkach dotyczy tej rozmowy. Narzędzia
plików mogą korzystać ze ścieżek bezwzględnych wszędzie, gdzie sięga twoje konto,
a polecenia działają jako ty, bez osobnych natywnych potwierdzeń. Uprawnienia systemu
i reguły zatwierdzania agenta nadal obowiązują. **Cofnij dostęp do całego komputera**
lub wybór **Chmura** blokuje nowe operacje; działające polecenia nie są przerywane.
Zgoda przetrwa restart aplikacji i dotyczy tego serwera oraz agenta lub rozmowy;
nowy szkic wiąże zgodę rozmowy przy pierwszej operacji. Nowy czat z innym agentem
wymaga własnej zgody. Ten tryb nie
przeszukuje katalogu domowego ani nie zbiera automatycznie załączników.

Lokalna przeglądarka i narzędzia plików są dostępne w czacie desktopowym także bez
funkcji Browser lub Sandbox w agencie. Wybór dodaje funkcję tylko do uruchomienia,
zachowuje ograniczenia domen i reguły zatwierdzania oraz nie zmienia opublikowanego
agenta. Wewnętrzne migawki załączników używają list plików zamiast poleceń powłoki.

## Ekran { #the-screen }

[Computer use](reference/capabilities.md) może sterować ekranem tego komputera. W
czacie pracującym na tym komputerze jego pulpit `auto` - domyślny - to ten ekran;
`local` nie prosi o nic innego.

- **Najpierw pyta.** Pierwszy zrzut w sesji pyta w natywnym oknie, czy agent może
  widzieć ten ekran i nim sterować, na godzinę.
- **Obramowany, gdy działa.** Obrys otacza ekran, gdy agent go trzyma.
- **Do zatrzymania od razu.** `⌘⌥Esc` (gdzie indziej `Ctrl+Alt+Esc`) odbiera
  ekran; następna akcja jest odrzucana, dopóki znowu nie pozwolisz.
- **System też pyta.** macOS potrzebuje AgenticOS w Prywatność i ochrona, zarówno
  w Nagrywaniu ekranu, jak i w Dostępności; odmowa je nazywa.

Każdy pulpit, na którym pracuje run, ten także, jest pokazywany na żywo w czacie i
w podglądzie runa na żywo, gdzie **Przejmij** oddaje go tobie między krokami
agenta, a **Oddaj** zwraca. Podgląd ekranu tego komputera jest tylko dla ciebie,
ktokolwiek inny może oglądać runy.

## Logowanie { #signing-in }

Główne okno desktopowe ma osobny pasek przeciągania i zwarty górny odstęp treści 16px. Na macOS przyciski okna mają zarezerwowany wiersz 32px, dzięki czemu marka w pasku bocznym i nagłówek strony pozostają wyrównane bez dodatkowej przerwy z układu przeglądarkowego.

Konsola, Blobby i Quick Ask współdzielą nazwany, trwały profil WebView; prywatne karty
przeglądarki agenta pozostają odizolowane. Przejście ze starszego profilu może wymagać
jednego logowania. W Glass obszar przeciągania ma tło zgodne z treścią. Panel dashboardu
wygładza nawigację klawiaturą i skokowe ruchy kółka myszy, zachowując natywną obsługę
precyzyjnego przewijania gładzikiem; ograniczenie ruchu wyłącza wygładzanie.

Konsola zachowuje sesję w trwałych cookies HttpOnly, w tym cookie odświeżającym
odnawianym podczas korzystania z sesji. Ponowne otwarcie aplikacji przywraca sesję,
dopóki jest ważna. Chwilowa awaria serwera lub limit żądań zachowuje konto w desktopie;
sprawdzenie sesji ponawia się po odzyskaniu połączenia lub aktywowaniu okna. Odrzucony
lub unieważniony token nadal wymaga logowania. Gdy lokalnie nie ma konta, niedostępność
serwera pokazuje możliwość ponowienia zamiast przekierowania do logowania.

Jedyna nawigacja, której okno konsoli odmawia. Wszystko inne ładuje się w oknie;
kliknięcie **Continue with Google** otwiera się zamiast tego w twojej własnej
przeglądarce, a wynik wraca do aplikacji (#1532).

Co się dzieje, po kolei:

1. Własne `/api/oauth/<provider>/login` konsoli działa **w oknie**, gdzie może
   przeczytać ciasteczko httpOnly z przygotowanym zaproszeniem i je dołączyć.
2. Okno widzi wtedy nawigację do `/api/v1/oauth/<provider>/login` _wdrożenia_,
   przekazuje ją systemowej przeglądarce z dopisanymi `client=desktop` i świeżo
   wybitym `desktop_nonce` i nie idzie za nią.
3. Logujesz się tam, w prawdziwej przeglądarce z własnymi hasłami, własnymi
   rozszerzeniami i jakimkolwiek drugim składnikiem.
4. Callback wdrożenia widzi, że ta próba była desktopowa - zapisane w sesji na
   _początku_ pod `state` OAuth tej próby, nigdy nie odczytywane z powrotu - i
   przekierowuje do `agenticos://auth/callback?code=…` z jednorazowym kodem, który
   wygasa po minucie, oraz otrzymanym nonce.
5. System przekazuje ten link aplikacji. Powłoka wysyła okno konsoli do
   `<your server>/auth/callback?code=…`, które wymienia kod na parę tokenów między
   serwerami; ustawiane są ciasteczka samego okna.

**Deep link może wywołać każdy proces na twoim komputerze**, więc to, co jeden
może tu zrobić, jest wąskie: wysłać konsolę pod jedną ścieżkę, na serwerze, który
_ty_ skonfigurowałeś, z kodem wymienialnym dokładnie raz - i tylko taki, który
niesie nonce wybity przez tę aplikację dla tej próby. Na Windows i Linuksie blokada
jednej instancji przekazuje argumenty drugiego uruchomienia pierwszemu. Wdrożenie
musi zgadzać się co do schematu - `DESKTOP_DEEP_LINK_SCHEME`, `agenticos`, chyba że
ktoś to zmienił - i co do własnego publicznego adresu.

## Czego celowo nie robi { #what-it-deliberately-does-not-do }

- **Brak strażnika nawigacji.** Link wychodzący poza origin serwera otwiera się w
  oknie, bo niektóre przepływy OAuth - podłączanie konta dla terminala - muszą
  wrócić do tego samego webview, żeby ich ciasteczko trafiło na miejsce. Tytuł okna
  nazywa każdy inny host, który pokazuje. Podłączanie serwera MCP do nich nie
  należy: jego zgoda otwiera się w twojej przeglądarce, gdzie są twoje logowania i
  passkeye, bo callback uwierzytelnia sam `state`. Dokończ tam i wróć; serwer
  pojawi się w aplikacji po autoryzacji.

- **Brak stałego dostępu.** Połączenie komputera samo niczego nie daje: run sięga
  tylko zatwierdzonych folderów lub całego komputera po osobnej zgodzie dla rozmowy, a ekranu dopiero po
  twojej zgodzie.

## Gdzie to jest w drzewie { #where-it-sits-in-the-tree }

- `desktop/ui/` - strony pierwszego uruchomienia i obrys ekranu, pliki statyczne.
- `desktop/core/` - części, co do których obie strony muszą się zgadzać, bez
  runtime: ramki urządzenia, endpointy i back-off, testowane osobno.
- `desktop/src-tauri/` - powłoka: okna, menu, blobby, szybkie pytanie, połączenie
  urządzenia (`device.rs`), lokalny wykonawca (`local_work.rs`) i ekran
  (`screen.rs`).
- `backend/app/services/device_hub/` - połowa serwerowa: obecność w Redisie, żeby
  każdy host API i worker sięgał komputera, oraz `DeviceWorkspace`, workspace
  sandboxa wykonywany przez aplikację.

## Coding agents na tym komputerze { #coding-agents-on-this-computer }

**Settings → Desktop app → Coding agents on this computer** pokazuje wersje i
stan logowania. **Set up** przygotowuje prywatny Node.js 24.19.0 oraz przypięte
adaptery z lockfile, sprawdzając integralność pobieranych plików. Nie musisz osobno
instalować narzędzi deweloperskich. **Sign in** uruchamia logowanie OAuth agenta
w przeglądarce; AgenticOS nie odczytuje ani nie kopiuje poświadczeń. **Refresh
status** jawnie sprawdza logowanie. Powrót do aplikacji nie odpytuje ciągle
magazynu poświadczeń; udane logowanie i przygotowanie automatycznie odświeżają stan.

W aplikacji desktopowej wybierz **Ustawienia czatu → Narzędzia i pliki → Agent programistyczny**, a następnie **Claude Code** lub **Codex**, również gdy opublikowana capability jest wyłączona lub nieobecna. Aplikacja przygotowuje lokalne narzędzia plikowe i otwiera natywny wybór folderu, chyba że bieżący folder ma już grant pełnego dostępu. Anulowanie pozostawia poprzednie ustawienia. **Użyj ustawienia agenta** przywraca opublikowaną konfigurację.

Wybór dotyczy tego czatu. Reguły trybu tylko do odczytu i zatwierdzania nadal obowiązują, a natywną zgodę na start można zapamiętać dla agenta i folderu. Przejście do chmury usuwa wybór lokalnego coding agenta dla tej rozmowy. Ustawienia czatu rozwijają się nad polem wiadomości. Ma karty **Model**, **Narzędzia i pliki** (Coding agent, Work on, Browser, Computer use i skille) oraz **Preferencje** (zatwierdzanie i powiadomienia).

Ustaw capability **Coding agent** na **On this computer**, wybierz folder w
**Work on** i przyznaj mu pełny dostęp. Natywna zgoda jest zapamiętywana dla tego
agenta, folderu, wersji adaptera i połączenia. Usunięcie lub ponowne wybranie
folderu usuwa zgodę i zatrzymuje działających w nim agentów; zmiana konta lub
serwera też usuwa zgody. Adapter działa jako Twoje konto systemowe: folder
wyznacza katalog roboczy, a nie sandbox systemu. Dostęp do całego komputera
uruchamia też coding agenta, w katalogu domowym albo folderze wewnątrz niego. Zgody na zadania i uprawnienia systemowe nadal obowiązują.

Zgoda capability obowiązuje raz na zadanie. W jego trakcie `edit` zezwala na żądane operacje, a `read_only` odmawia zmian. Claude w trybie odczytu wyłącza bypass uprawnień i udostępnia tylko narzędzia do czytania. Codex wybiera swój natywny sandbox tylko do odczytu. Lokalny agent używa własnych ustawień modelu; użycie subskrypcji nie jest wyceniane, więc koszt runu stanowi dolną granicę.

Kolejne zadania wznawiają nazwaną sesję (`main`, gdy zadanie nie wskazuje żadnej) dla danej rozmowy, agenta, harnessu, folderu, konta i polityki dostępu; kilka sesji działa naraz, do ośmiu na jednym komputerze, każda w folderze czatu albo folderze wewnątrz niego. `fresh_session` jawnie zaczyna od nowa. Identyfikatory sesji pozostają w ustawieniach desktopu, poza repozytorium, i są usuwane po odłączeniu lub zmianie konta. Niedostępna zapisana sesja kończy zadanie jawnym błędem; w razie potrzeby zacznij od nowa. Odłączenie zatrzymuje proces, ale zapisaną historię harnessu można wznowić.

Korekta wysłana podczas lokalnego zadania przerywa bieżącą turę ACP. Po potwierdzeniu zatrzymania przez adapter ta sama sesja kontynuuje z korektą. Transkrypt zapisuje zastosowaną korektę; wiadomość po zakończeniu pozostaje dostępna dla nadrzędnego agenta.

Po wybraniu agenta kodującego i zatwierdzonego folderu pola **Model kodujący** i **Poziom myślenia** pokazują opcje zgłoszone przez zainstalowanego agenta. Dotyczą tej rozmowy i są stosowane przed nowym lub wznowionym zadaniem. Puste pole zachowuje własne ustawienie agenta. Zmiana agenta usuwa niezgodne nadpisania. Odśwież opcje po zmianie logowania lub konfiguracji; otwarcie kolejnego okna nie sprawdza ponownie konta. Usunięta albo nieobsługiwana opcja jest widoczna i odrzucana, zamiast cichej zamiany. Odczyt opcji nie uruchamia modelu i nie udziela zgody na narzędzia.

## Twoje skills i instrukcje { #your-own-skills-and-instructions }

**Chat controls → Work on → My skills and instructions** wybiera źródła dostępne w rozmowie: `~/.agents/skills`, `~/.claude/skills` i `~/.codex/skills`. W nowym czacie są wyłączone. Pliki są czytane w miejscu, bez kopiowania ani synchronizowania credentials i konfiguracji.

Wśród włączonych źródeł kolizję nazw rozstrzyga kolejność `.agents`, `.claude`, `.codex`. Liczniki uwzględniają bieżący wybór. Desktop deduplikuje linki do tego samego folderu skilla. Globalne instrukcje pochodzą z nowszego włączonego pliku `~/.codex/AGENTS.md`, `~/.claude/AGENTS.md` lub `~/.claude/CLAUDE.md`, także poprzez symlink do Markdowna.

Po globalnych instrukcjach następują `AGENTS.md` i `CLAUDE.md` zatwierdzonego folderu. Przed pracą w podfolderze agent może wywołać `load_local_instructions`, aby odczytać hierarchię od zatwierdzonego katalogu do wskazanego miejsca. Bardziej szczegółowe pliki następują po nadrzędnych. Czytnik nie wychodzi ponad zatwierdzony folder i nie podąża za projektowymi symlinkami. Instrukcje nie rozszerzają uprawnień runu.

Odczytany tekst skilli i instrukcji trafia przez Twój serwer do skonfigurowanego modelu agenta. Przełącznik źródeł steruje tym kontekstem AgenticOS; lokalne coding agents zachowują własną konfigurację i wykrywanie instrukcji.

## Diagnostyka { #diagnostics }

**Help → Export Diagnostics…** zapisuje jeden plik JSON w wybranym miejscu, do załączenia do zgłoszenia błędu. Zawiera wersję, system operacyjny, na co zezwolił macOS, czy Claude Code i Codex są zainstalowane i zalogowane, adres serwera (tylko schemat, host i port) oraz ostatnie awarie. Nie zawiera poświadczeń, tokenów, rozmów ani ścieżek w folderze domowym, a nic nie jest nigdzie wysyłane. Awaria jest zapisywana w `crash.log` w folderze danych aplikacji w chwili, gdy się zdarzy.

Jeśli aplikacja desktopowa 1.38.1 pozostaje w stanie **Linked — reconnecting…**,
a lokalne czaty pokazują **Waiting for your computer**, sprawdź, czy lokalizacje
awarii w wyeksportowanej diagnostyce zawierają `rustls` / `crypto/mod.rs`.
Ten błąd inicjalizacji TLS poprawiono w nowszym wydaniu aplikacji desktopowej.
Zainstaluj je i otwórz aplikację ponownie; aktualizacja samego serwera nie
aktualizuje klienta desktopowego. Ta poprawka nie wymaga resetowania parowania
ani zgód na foldery.

## Lokalna przeglądarka, modele i MCP { #local-browser-models-and-mcp }

Po sparowaniu aplikacji wybierz **Przeglądarka → Lokalna przeglądarka**, aby
nadpisać ustawienie agenta dla tej rozmowy. Ten wybór jest niezależny od **Pracuj na**:
nie wymaga folderu ani funkcji Sandbox i zachowuje sandbox agenta w chmurze. Lokalne
modele i usługi MCP wymagają zatwierdzonego folderu lub dostępu do całego komputera;
run otrzymuje własną funkcję Sandbox. Aplikacja telefonu
nie wywołuje komend desktopowych.

Usługi dodaje się w **Ustawienia → Aplikacja desktopowa → Usługi lokalne**. Każde
uprawnienie potwierdza natywne okno. Model korzysta z endpointu HTTP Ollama lub
OpenAI-compatible (np. `http://127.0.0.1:11434/v1`) i identyfikatora zainstalowanego
modelu. MCP wymaga działającego serwera Streamable HTTP
(np. `http://127.0.0.1:8000/mcp`).

Dopuszczalne są tylko adresy loopback, bez
przekierowań i danych logowania w URL. Adres przechowuje desktop, a API przesyła
nieprzezroczysty identyfikator uprawnienia. Limit żądania i odpowiedzi wynosi 8 MiB,
a czas usługi dwie minuty. Serwer MCP musi przyjmować żądania bez tokena i kończyć
odpowiedzi HTTP; osobne subskrypcje SSE i uruchamianie procesów stdio nie są
obsługiwane. Usunięcie uprawnienia blokuje kolejne wywołania. Profil organizacji pozostaje tożsamością modelu bez otwierania jego danych logowania do chmury.
Lokalny model nie ma awaryjnego przełączenia na chmurę; pozostałe funkcje z osobnymi modelami zachowują
swoje ustawienia.

**Lokalna przeglądarka** po zgodzie na sparowanym komputerze pokazuje natywną
stronę w panelu przeglądarki konsoli. Kliknięcia, przewijanie i wpisywanie odbywają
się lokalnie, bez przesyłania screenshotów. Prywatna sesja nie importuje osobistych
kart ani haseł. Tekst strony nadal trafia do modelu agenta. Ręczna interakcja
przejmuje sterowanie; **Oddaj agentowi** zwraca je agentowi.

Przy szerokim czacie przeglądarka otwiera się obok rozmowy, zarówno lokalnie, jak
i zdalnie. Przeciągnij separator lub użyj jego klawiszy strzałek, aby zmienić
szerokość. **Maksymalizuj** otwiera pełny ekran, a **Wróć obok czatu** przywraca
panel. Wąskie obszary czatu i telefony automatycznie używają pełnego ekranu.

Natywna karta należy do komputera, organizacji, osoby, agenta i rozmowy. Pozostaje
otwarta między runami, a `browser_read` ją wznawia. W danej chwili może jej używać
jeden run. Run odnawia dzierżawę automatycznie; po zatrzymaniu jego backendu
dzierżawa staje się ponownie dostępna po dwóch minutach. **Zamknij kartę** ją usuwa; zamknięcie panelu tylko ją ukrywa.
Rozłączenie sparowanego urządzenia zamyka wszystkie jego karty. Limit to osiem
kart; karty nieaktywne przez dwie godziny mogą zostać usunięte przy otwarciu kolejnej.

Zgoda na natywne przeglądanie obejmuje karty tej rozmowy w bieżącym połączeniu urządzenia. Nowe karty i karty ponownie otwarte przez agenta nie wymagają kolejnego potwierdzenia przy tej samej polityce domen. Samodzielne zamknięcie ostatniej karty cofa zgodę; ukrycie panelu jej nie cofa. Odłączenie urządzenia usuwa zgodę. Inna osoba, agent, rozmowa lub polityka domen wymaga osobnej zgody.

Ustawienia Computer use i przeglądarki używają kafelków środowisk z krótkimi opisami. Nowo włączony Computer use jawnie wybiera Docker / Sandbox. Wybór automatyczny nie jest już oferowany; istniejące konfiguracje pozostają czytelne i niezmienione do czasu wyboru środowiska przez użytkownika. Docker Compose zawiera sandboxd i runtime desktop. Operator może zarejestrować URL i klucz innego hosta w Połączenia → Sandboxy, a następnie wybrać go i runtime desktop w ustawieniach Sandbox agenta.

Aby wybrać zgodność z Chromium, wyłącz **Używaj natywnej przeglądarki lokalnej**
w ustawieniach funkcji przeglądarki. Zadania z vision lub zmianą języka albo strefy
czasowej także używają izolowanego
okna Chromium. Ta ścieżka wymaga Chrome, Chromium, Edge lub Brave i zamyka
profil po runie. Akcje w natywnym DOM korzystają ze skryptów; niektóre strony
odróżniają je od zaufanego wejścia CDP. Strony nie mają uprawnień konsoli ani
plików; mogą tylko zgłosić przejęcie sterowania. Konfiguracja `connection: local`
nadal wymaga wyboru lokalnej przeglądarki.

## Instalatory i aktualizacje { #installers-and-updates }

Workflow Apps buduje też instalatory deweloperskie i testuje instalację bez automatyzacji interfejsu: kopiowanie aplikacji Mac z DMG, cichą instalację i usunięcie na Windowsie, instalację i usunięcie pakietu Debian oraz rozpakowanie przenośnego AppImage. Sprawdza osadzony widget macOS i podpisy, izolację trwałej sesji oraz odrzucenie zmodyfikowanego pliku aktualizacji. Te kontrole używają buildów ad-hoc lub niepodpisanych i nie potwierdzają publicznej notaryzacji ani akceptacji sklepu.

Workflow **Apps** w GitHub Actions sprawdza natywne crate'y na macOS, Windows i
Linuksie, buduje debug APK Androida i aplikację symulatora iOS. Pełne sprawdzenia
natywne wykonuje CI; lokalne `make desktop-check` pozostaje dostępne do zmian
wybranego obszaru. Workflow **App release** dołącza instalatory, podpisane pliki
aktualizacji, APK i cask Homebrew do istniejącego, opublikowanego stabilnego wydania
`v1.MINOR.PATCH`, którego commit należy do `main`. Nie tworzy wydania platformy.
Cask trafia też do tapu Homebrew, gdy skonfigurujesz deploy key lub token.
Menu **Sprawdź aktualizacje…** wymaga buildu z publicznym kluczem aktualizatora i
weryfikuje podpis przed instalacją.

Buildy wydań desktopowych działają równolegle. Każdy wysyła własne podpisane
paczki; jeden końcowy job sprawdza cztery natywne targety i publikuje `latest.json`.
CI aplikacji natywnych zapisuje wyniki kompilacji według systemu, architektury,
kompilatora, targetu i profilu buildu. Wydania tylko odczytują wspólny cache
pobranych zależności. Nieudany build platformy blokuje publikację manifestu aktualizacji.

Publikacja mobile jest obecnie wyłączona. Zmienna repozytorium
`AGENTICOS_MOBILE_RELEASES_ENABLED=true` włącza podpisane wydania Androida;
iOS wymaga dodatkowo flagi TestFlight opisanej poniżej. Zwykłe buildy CI pozostają
aktywne. Do czasu uruchomienia dystrybucji skorzystaj z instrukcji
[samodzielnej instalacji mobile](mobile.md#availability-and-self-installation).

Przed wydaniem skonfiguruj środowisko GitHub `apps-release`:

- Stały podpis macOS: sekrety `MACOS_SELF_SIGNED_P12`, `MACOS_SELF_SIGNED_P12_PASSWORD` i zmienna `MACOS_SELF_SIGNED_IDENTITY`. Opublikuj publiczny fingerprint w `scripts/macos_signing_identity.txt`.
- Homebrew: sekret `HOMEBREW_TAP_DEPLOY_KEY`, deploy key z zapisem wyłącznie do repozytorium tapu. Alternatywą jest `HOMEBREW_TAP_TOKEN`. Tymczasowe pliki klucza są usuwane także przy błędzie.
- Zmienna `AGENTICOS_UPDATER_PUBLIC_KEY`; sekrety `TAURI_SIGNING_PRIVATE_KEY`
  i `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` (stała para kluczy aktualizatora).
- Opcjonalny podpis macOS Developer ID: ustaw zmienną repozytorium `AGENTICOS_MACOS_SIGNING_ENABLED=true` i skonfiguruj poniższe dane Apple. Brak danych zatrzymuje build, bez przejścia na podpis ad-hoc. Gdy flaga nie jest ustawiona lub jest fałszywa, paczki używają skonfigurowanego stałego certyfikatu samopodpisanego albo podpisu ad-hoc przy jego braku. Oba warianty są bez notaryzacji; dane Apple są ignorowane.
- macOS: `APPLE_CERTIFICATE` (P12 w base64), `APPLE_CERTIFICATE_PASSWORD`,
  `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD` (hasło aplikacji)
  i `APPLE_TEAM_ID` do podpisu Developer ID i notaryzacji.
- Opcjonalny Authenticode Windows: `WINDOWS_CERTIFICATE_BASE64` (PFX)
  i `WINDOWS_CERTIFICATE_PASSWORD`. Bez nich instalator nie ma podpisu.
- Android: `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`,
  `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`. Aktualizacje wymagają tego samego keystore.
- TestFlight: zmienna repozytorium `AGENTICOS_TESTFLIGHT_ENABLED=true`; sekrety
  `IOS_CERTIFICATE_BASE64`, `IOS_CERTIFICATE_PASSWORD`, `IOS_PROFILES_BASE64_JSON`
  (tablica JSON profili base64 aplikacji, widgetów i rozszerzenia udostępniania),
  `APP_STORE_CONNECT_KEY_P8`, `APP_STORE_CONNECT_KEY_ID`,
  `APP_STORE_CONNECT_ISSUER_ID`, `APPLE_TEAM_ID`. Najpierw utwórz identyfikatory,
  wspólną App Group i aplikację App Store Connect. Push nadal wymaga istniejących
  danych APNs skonfigurowanych we wdrożeniu.

Dane sklepów pozostają w CI, a zadania usuwają tymczasowe pliki podpisujące.
Wysyłka do TestFlight jest wyłączona do jawnego włączenia. Zatwierdzenie sklepu,
provisioning i dostarczenie na podpisane urządzenia wymagają kont operatora;
nie potwierdzi ich niepodpisany lokalny build.

## Podsumowanie { #recap }

- **Konsola zostaje na serwerze.** Powłoka ją otwiera; nic nie jest dołączane.
- **Natywnie tam, gdzie to ma znaczenie.** Menu, powiadomienia, przypięte agenty,
  blobby, szybkie pytanie i głos z dowolnego miejsca.
- **Twoje agenty mogą pracować na tym komputerze** - w wybranych folderach, w
  wybranych trybach, w piaskownicy systemu i tylko dla twoich własnych runów.
- **I na jego ekranie** - najpierw pytają, są obramowane, gdy działają, i
  zatrzymywane jednym skrótem.

Quick Ask obsługuje do ośmiu niezależnych zakładek w oknie. Każda zachowuje własny szkic, załączniki, wybranego agenta i trwającą odpowiedź. Ostatnie rozmowy otwiera przeszukiwaną listę i przełącza na istniejącą zakładkę, jeśli rozmowa jest już otwarta; zapisane rozmowy wczytują wiadomości i wcześniejszą historię. Nieaktywne zakładki nie przechwytują plików, skrótów dyktowania ani fokusu. Ostatnie rozmowy pokazują avatary agentów w rozwijanej sekcji. Zajmuje ona tylko potrzebne miejsce, bez rezerwowania pustej wysokości okna. Nowy czat jest jedyną akcją otwierającą nową zakładkę. Sidebar w przeglądarce proponuje pobranie desktopu; zamknięcie przypomnienia wycisza je na 14 dni dla tego konta w tej przeglądarce.

Quick Ask ma przycisk mikrofonu do włączania dyktowania kliknięciem, obok istniejącego skrótu przytrzymywanego. Połączenia głosowe korzystają z tych samych kontrolek co chat: konfiguracji wybranego agenta, napisów, zatwierdzeń i pytań. Wypowiedziane tury zapisują się w rozmowie. Wysyłanie tekstu i dyktowanie czekają podczas połączenia. Przejście do innej zakładki lub zmiana agenta kończy połączenie i zwalnia mikrofon.

## Rutyny lokalne { #local-routines }

Odmowa na komputerze zastępczym nie dowodzi cofnięcia zgody na zatwierdzonym komputerze: może on po prostu być offline. Właściciel otrzymuje powiadomienie bez duplikatów, aby połączyć komputer lub przejrzeć dostęp; procedura i dane jej zdarzeń nadal czekają. Odmowa na pierwotnie wybranej aktywnej sesji nadal zatrzymuje procedurę do przeglądu.

Na Linuxie aplikacja sprawdza, czy zainstalowany bubblewrap udostępnia `--bind-fd`, zanim zaoferuje zapis w folderze lub uruchomi komendę w sandboxie. Brak programu, nieobsługiwana albo nieodpowiadająca wersja oznacza odmowę; zaktualizuj bubblewrap, aby włączyć ten tryb.

JSON zgód procedur jest weryfikowany względem aktualnego skrótu SHA-256 w systemowym keychainie. Edycja pliku ani przywrócenie kopii sprzed cofnięcia zgody nie nadaje dostępu. Niedostępny keychain lub niezgodność blokuje procedury. **Aktualizacja:** starsze zgody nie mają skrótu i wymagają ponownego zatwierdzenia: jawnie odłącz komputer, powiąż go ponownie i przejrzyj procedury. Ten sam reset naprawia przerwany zapis zgód; aplikacja nigdy automatycznie nie ufa niezweryfikowanemu plikowi.

Utwórz rutynę z opcją **Uruchamiaj jako ja**, wybierz folder oraz osobno odczyt, zapis i uruchamianie poleceń. Polecenia wymagają zapisu. Zapis najpierw tworzy wstrzymaną rutynę. Za pierwszym razem aplikacja komputerowa pyta raz, w natywnym oknie, czy **wszystkie twoje rutyny** w tej organizacji mogą pracować w tym folderze i jego podfolderach, z tymi operacjami; wybierz folder domowy, aby objąć cały komputer.

Każda kolejna rutyna w tym folderze zapisuje się bez pytania, a zgoda przetrwa aktualizację aplikacji i ponowne zalogowanie. Anulowanie pozostawia tę samą rutynę wstrzymaną; ponowienie kończy konfigurację bez tworzenia kolejnej. Ogólna zgoda na folder w czacie nie upoważnia rutyny.

**Ustawienia → Desktop → Uprawnienia rutyn** pokazuje zgody bieżącego konta i organizacji na tym komputerze. Cofnij zgodę, aby zatrzymać kolejne operacje. Zmiana serwera lub konta usuwa te zgody; zgoda na jedną rutynę, udzielona przez starszą aplikację, kończy się też razem z jej sesją. Zmiana folderu lub zwiększenie uprawnień wymaga nowego potwierdzenia natywnego. Zgoda na folder nie obejmuje przeglądarki, ekranu, lokalnych modeli, lokalnych usług MCP ani całego komputera. Opublikowany agent musi już mieć włączony Sandbox; lokalny cel nie włącza możliwości.

Gdy konkretny zatwierdzony komputer jest offline przed wykonaniem, trwała aktywacja czeka w PostgreSQL. Wiersz rutyny pokazuje liczbę oczekujących aktywacji. Wywołania harmonogramu i ręczne łączą się podczas oczekiwania; odrębne zdarzenia zachowują własny kontekst i identyfikator aktywacji. Istniejący worker sprawdza połączenie co minutę. Sprawdzanie gotowości nie wywołuje modelu i nie zużywa prób błędnych uruchomień. Dopuszczenie do wykonania zatwierdza się z przebiegiem przed pierwszym wywołaniem modelu. Rozpoczęta aktywacja nie jest automatycznie powtarzana po awarii workera; niepewna operacja plikowa lub polecenie nie tworzy nowego przebiegu.

Wstrzymanie, zmiana zadania lub zgody lokalnej, usunięcie rutyny albo osiągnięcie jej końca anuluje stare oczekiwanie zamiast przenosić je do innego folderu. Cofnięta sesja urządzenia wymaga ponownego przeglądu. Trzy martwe lub utracone zadania przed dopuszczeniem zatrzymują rutynę i tworzą incydent właściciela; kontekst nieudanego zdarzenia pozostaje dostępny w eksporcie jego danych. Kontekst po rozpoczęciu lub anulowaniu jest od razu usuwany. Zakończone metadane i nieudany kontekst podlegają retencji historii przebiegów organizacji; aktywne oczekiwanie trwa do dopuszczenia, anulowania lub usunięcia.

Wdrażaj API, workery i aplikację komputerową razem; przed włączeniem kontraktu opróżnij stare workery. Starsze aplikacje nie potwierdzają zgód rutyn; istniejące rutyny lokalne wymagają jawnego przeglądu. Migracja `0272_routine_device_waits.py` dodaje oczekiwanie bez zmiany tożsamości rutyny. Przed cofnięciem migracji wstrzymaj rutyny lokalne i opróżnij ich zadania: cofnięcie usuwa oczekujący kontekst i go nie wykonuje. Stare zaparkowane przebiegi bez migawki celu lokalnego wymagają nowego uruchomienia.

Wybór lokalnego dostępu należy do wybranego agenta, a nie do globalnego ustawienia dziedziczonego przez innych agentów. Cofnięcie dostępu do folderu usuwa także zapamiętane wybory i zgody coding agentów dla jego podfolderów. Starsze aplikacje desktopowe zachowują zgodę na cały komputer tylko w jednej rozmowie; aktualizacja pozwala zapamiętać ją we wszystkich rozmowach agenta.

Korekta `[session:api] Użyj danych z UE` trafia do sesji `api`. Przy jednej aktywnej sesji trafiają do niej także korekty bez adresu; przy wielu pozostają u agenta nadrzędnego, aby nie zmieniać innego zadania. Agent nadrzędny zapisuje korektę raz po wznowieniu pracy.

 Zadania coding w sandboxie w tym samym zestawie narzędzi wykonują się kolejno, aby ich migawki plików się nie nakładały; niezależne sesje lokalne nadal działają równolegle.
