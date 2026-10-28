---
source_sha: "403c6ff7ce7a"
---

# Aplikacja desktopowa { #the-desktop-app }

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

## Uruchamianie { #running-it }

Przed wyborem lokalnej instalacji lub połączeniem z serwerem kreator pierwszego
uruchomienia oferuje opcjonalne uprawnienia Screen Recording i Accessibility na macOS.
Każdy przycisk otwiera odpowiednie ustawienia systemowe; konfiguracja niczego nie
przechwytuje ani nie steruje komputerem. Można kontynuować bez obu uprawnień. Powrót z
ustawień odświeża ich status; macOS może wymagać restartu aplikacji. Dostęp do mikrofonu
i folderów jest nadal żądany przy użyciu tych funkcji.

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

Na macOS **Download Docker Desktop** pobiera oficjalny instalator dla Apple silicon
lub Intela, pokazuje postęp i otwiera obraz dysku. Dokończ instalację w oknie
systemowym, a potem wybierz **Open Docker Desktop** i **Check again**. Aplikacja
wykrywa też CLI Dockera zainstalowane dla użytkownika. Na innych systemach otwiera
stronę pobierania Dockera. Samo sprawdzenie stanu nie uruchamia instalacji.

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

## Praca na tym komputerze { #work-on-this-computer }

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

Windows oferuje tylko odczyt i pełny dostęp. Linux oferuje zapis w folderze tylko
wtedy, gdy jest zainstalowany `bwrap`.

**Decyduje komputer, nie serwer.** Wybrane foldery wraz z trybami są trzymane w
ustawieniach aplikacji, a każda operacja podaje folder i tryb, które aplikacja z
nimi porównuje: folder, którego nie wybrałeś, tryb szerszy niż dozwolony albo
ścieżka wychodząca poza folder są odrzucane na komputerze, cokolwiek serwer
poprosił. Wybór jest zapamiętywany dla każdej rozmowy, a nowy czat zaczyna w
chmurze.

**Tylko twoje runy.** Czat sięga twojego komputera tylko wtedy, gdy jest twój -
nigdy klucz API, gość widżetu czy czat kogoś innego - a
[trigger](triggers.md) tylko wtedy, gdy działa jako jego twórca, który wskazuje mu
folder swojego komputera w polu **Pracuj na** triggera.

**Gdy komputera nie ma.** Run, który poprosił o ten komputer i zastał aplikację
bez połączenia, czeka na nią do dziesięciu minut, a czat o tym mówi. Operacja,
która zastanie aplikację rozłączoną w trakcie runa - zamknięta klapa, zmiana sieci

- czeka do pięciu minut na jej powrót w tej samej sesji, a potem idzie dalej. Gdy
  operacja runa jest w toku, zasobnik mówi, że agent pracuje na tym komputerze.

Serwer sprawdza sesję przed przekazaniem każdej lokalnej operacji. Odwołana lub wygasła sesja odmawia nowej pracy; heartbeat zamyka też bezczynne połączenia. Operacje już w toku są anulowane po zamknięciu połączenia desktopu.

W Builderze **Sandbox → Komputer** zapisuje `backend: local`, bez ścieżki i
natywnej zgody. Każda osoba zatwierdza własne miejsce pracy w czacie desktopowym.
Bez wyboru uruchomienie prosi o niego zamiast otwierać sandbox w chmurze. Przy
tworzeniu projektu **Sandbox projektu → Komputer · Twoje pliki** otwiera wybór
prywatnego folderu; inni członkowie zachowują wspólny obszar projektu.

**Cały komputer.** Czat desktopowy oferuje też **Cały komputer**, bez wyboru
folderu. Jedno natywne ostrzeżenie zatwierdza dostęp dla tej rozmowy: narzędzia
plików mogą korzystać ze ścieżek bezwzględnych wszędzie, gdzie sięga twoje konto,
a polecenia działają jako ty, bez osobnych natywnych potwierdzeń. Uprawnienia systemu
i reguły zatwierdzania agenta nadal obowiązują. **Cofnij dostęp do całego komputera**
lub wybór **Chmura** blokuje nowe operacje; działające polecenia nie są przerywane.
Zgoda przetrwa restart aplikacji i dotyczy tego serwera oraz rozmowy; nowy szkic
wiąże ją przy pierwszej operacji. Nowy czat wymaga własnej zgody. Ten tryb nie
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
  oknie, bo przepływ OAuth - podłączanie serwera MCP - musi wrócić do tego samego
  webview, żeby jego ciasteczko trafiło na miejsce. Tytuł okna nazywa każdy inny
  host, który pokazuje.

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

Aby wybrać zgodność z Chromium, wyłącz **Używaj natywnej przeglądarki lokalnej**
w ustawieniach funkcji przeglądarki. Zadania z vision lub zmianą języka albo strefy
czasowej także używają izolowanego
okna Chromium. Ta ścieżka wymaga Chrome, Chromium, Edge lub Brave i zamyka
profil po runie. Akcje w natywnym DOM korzystają ze skryptów; niektóre strony
odróżniają je od zaufanego wejścia CDP. Strony nie mają uprawnień konsoli ani
plików; mogą tylko zgłosić przejęcie sterowania. Konfiguracja `connection: local`
nadal wymaga wyboru lokalnej przeglądarki.

## Instalatory i aktualizacje { #installers-and-updates }

Workflow **Apps** w GitHub Actions sprawdza natywne crate'y na macOS, Windows i
Linuksie, buduje debug APK Androida i aplikację symulatora iOS. Pełne sprawdzenia
natywne wykonuje CI; lokalne `make desktop-check` pozostaje dostępne do zmian
wybranego obszaru. Workflow **App release** dołącza instalatory, podpisane pliki
aktualizacji, APK i cask Homebrew do istniejącego, opublikowanego stabilnego wydania
`v1.MINOR.PATCH`, którego commit należy do `main`. Nie tworzy wydania platformy.
Cask jest plikiem do pobrania; publikacja tapu Homebrew pozostaje zadaniem operatora.
Menu **Sprawdź aktualizacje…** wymaga buildu z publicznym kluczem aktualizatora i
weryfikuje podpis przed instalacją.

Przed wydaniem skonfiguruj środowisko GitHub `apps-release`:

- Zmienna `AGENTICOS_UPDATER_PUBLIC_KEY`; sekrety `TAURI_SIGNING_PRIVATE_KEY`
  i `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` (stała para kluczy aktualizatora).
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
