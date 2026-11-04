---
source_sha: "e84c0975e059"
---

# Aplikacja na telefon { #the-phone-app }

Natywne osłony prywatności ukrywają dane konta, zanim iOS i Android wykonają podgląd do przełącznika aplikacji, także przy wyłączonej blokadzie biometrycznej. Powrót nadal podlega ustawieniom biometrii. Powiadomienia i inne linki niezwiązane z logowaniem nie anulują rozpoczętego logowania OAuth w przeglądarce systemowej.

Natywne logowanie OAuth korzysta z PKCE S256. Aplikacja zachowuje prywatny weryfikator, a callback przenosi tylko jego publiczny skrót. Weryfikator jest wysyłany w treści żądania wymiany, nigdy w adresie URL. Wylogowanie usuwa natywne podglądy powiadomień telefonu.

Konsola działa w przeglądarce telefonu i można ją dodać do ekranu głównego jako
aplikację. Aplikacja AgenticOS na iOS i Androida dodaje to, co potrafi tylko
aplikacja: ekran blokady, Dynamic Island, widżety, arkusz Udostępnij, push przy
zamkniętej aplikacji i własną blokadę. Tak jak [aplikacja desktopowa](desktop.md)
jest powłoką wokół konsoli samego wdrożenia, więc logowanie, uprawnienia i
kontrole tenanta są konsoli.

> **Miejsce na zrzut — aplikacja na telefon, live activity i widżety.**

To aplikacja [Tauri](https://tauri.app) w `mobile/`, z natywnymi połówkami - Swift
dla iOS, Kotlin dla Androida - w `mobile/src-tauri/`.

## Dostępność i samodzielna instalacja { #availability-and-self-installation }

!!! info "Buildy mobilne służą do rozwoju, nie do publicznej dystrybucji"

    Budujemy aplikację mobilną w CI, ale obecnie nie publikujemy jej w TestFlight,
    App Store ani Google Play i nie udostępniamy wspieranego wydania mobilnego do
    pobrania. Aby korzystać z natywnej aplikacji już teraz, zbuduj i zainstaluj ją
    samodzielnie, a następnie połącz z wdrożeniem AgenticOS prowadzonym przez Ciebie
    lub Twoją organizację. Nie zapewniamy hostowanego serwera AgenticOS ani kont
    Apple do podpisywania aplikacji.

Workflow **Apps** buduje debugowy APK Androida i niepodpisaną aplikację symulatora
iOS. Są to kontrole deweloperskie, nie wydania sklepowe. Buildu symulatora iOS nie
można zainstalować na fizycznym iPhonie. Uruchomienie na urządzeniu wymaga własnego
podpisywania i profili provisioning dla aplikacji oraz rozszerzeń.

Po sklonowaniu repozytorium zainstaluj Rust i narzędzia platformy: Xcode na macOS
dla iOS albo Android SDK, NDK i JDK dla Androida. Następnie:

```bash
cd mobile
bun install --frozen-lockfile
bun run ios        # rozwój iOS na macOS
# albo
bun run android    # rozwój Androida
```

Przy uruchomieniu wpisz adres swojego wdrożenia. Musi być osiągalny z telefonu;
`localhost` na telefonie oznacza telefon, nie komputer deweloperski. Możesz też
korzystać z [wersji przeglądarkowej dodanej do ekranu głównego](#installing-the-console-instead)
bez budowania natywnej aplikacji.

Publiczna dystrybucja mobilna jest domyślnie wyłączona w workflow wydawniczym.
Późniejsze włączenie wymaga `AGENTICOS_MOBILE_RELEASES_ENABLED=true`; iOS dodatkowo
wymaga `AGENTICOS_TESTFLIGHT_ENABLED=true` i konfiguracji podpisywania opisanej
w [wydaniach aplikacji](desktop.md#installers-and-updates). Zwykłe buildy CI pozostają aktywne.

## Logowanie { #signing-in }

Skanowanie najpierw pokazuje nazwę i e-mail konta docelowego. Potwierdź konto, aby się zalogować; anulowanie pozostawia obecną sesję bez zmian. Podgląd nie zużywa kodu ani nie przedłuża jego minutowej ważności.

**Ustawienia → Aplikacja mobilna** w konsoli pokazuje kod QR; zeskanowanie go
aplikacją pozwala potwierdzić logowanie na Twoje konto. Kod działa raz, przez minutę, a sesja telefonu
jest otwierana dopiero po potwierdzeniu, pod własną nazwą telefonu. Wpisanie adresu
serwera i zalogowanie się też działa. Sesja przetrwa restarty, a aplikacja
blokuje się za Face ID, Touch ID albo odciskiem palca po pięciu minutach
nieobecności.

**Aktywne sesje** w Ustawienia → Profil wymieniają każde zalogowane urządzenie:
„AgenticOS for iOS 0.2.0” dla aplikacji, w innym razie przeglądarkę, oraz które z
nich dostają push. Unieważnienie jednej z nich od razu wylogowuje tę aplikację.

Jeśli pierwsze połączenie albo powrót z logowania nie zakończy ładowania w ciągu
30 sekund, aplikacja wróci do formularza z zapisanym adresem i komunikatem o
połączeniu. Ponów próbę albo wpisz inny adres. Poprawnie załadowana kopia offline
pozostaje otwarta.

## Gotowość połączenia i zapisane serwery { #connection-readiness-and-saved-servers }

Po zalogowaniu panel **Dokończ konfigurację telefonu** sprawdza konto, dostępnego
opublikowanego agenta, blokadę aplikacji i powiadomienia. Dotyczy również
istniejących kont, jeśli konfiguracja jest niepełna. Kontynuuj odkłada opcjonalne
ustawienia; można do nich wrócić w **Ustawienia → Aplikacja mobilna**. Zmieniony
zestaw braków jest pokazywany ponownie. Aparat jest wymagany przy skanowaniu,
mikrofon przy rozpoczęciu rozmowy głosowej; kontrola gotowości ich nie uruchamia.
Odmowa powiadomień iOS udostępnia przycisk ustawień systemowych. Powrót do aplikacji
ponownie sprawdza zgodę.

**Ustawienia → Aplikacja mobilna → Zmień serwer** otwiera zapisane połączenia.
Nadaj serwerowi nazwę, zeskanuj kolejny kod lub wpisz adres. Limit wynosi 20
serwerów. Obecny adres jest migrowany automatycznie. Powrót otwiera dashboard z
zachowaną sesją. Cookies i dane offline nie są kopiowane między originami;
wylogowanie lub zmiana konta nadal usuwa jego pamięć urządzenia. Serwery muszą mieć
różne nazwy hostów: porty nie izolują cookies. Usunięcie wpisu nie usuwa danych
przeglądarki; przed udostępnieniem telefonu najpierw się wyloguj.

Przełączenie usuwa rejestrację push poprzedniego serwera przed otwarciem listy;
jeśli push jest zarejestrowany, potrzebne jest połączenie z tym serwerem. Na
kolejnym włącz push jawnie. Aplikacja nie utrzymuje równocześnie powiadomień w tle
z wielu serwerów. Polityki organizacji dotyczące serwera i blokady mają
pierwszeństwo. Wyłączenie blokady wymaga uwierzytelnienia na urządzeniu.

Przełączenie czyści również stare Live Activities, oczekujące akcje i przypięcia
widżetów. Natywne kliknięcia powiadomień są związane z logowaniem, które
zarejestrowało push; opóźnione powiadomienie nie otworzy rozmowy na innym
serwerze.

Zmiana powiązanego konta usuwa już wyświetlone powiadomienia Androida. Zmiana
serwera usuwa też przypięte agenty z szybkich akcji ikony aplikacji iOS.


## Prywatność powiadomień { #notification-privacy }

Preferencje telefonu dotyczą bieżącego logowania. W **Ustawienia → Powiadomienia**
można ukryć treść, a w ustawieniach czatu wyciszyć rozmowę. Serwer stosuje je przed
wysłaniem APNs lub Web Push, więc działają przy zamkniętej aplikacji. Widoczny,
aktywny czat odnawia 90-sekundowe wyciszenie co 30 sekund. Opuszczenie czatu lub
tło usuwa aktywność; po wymuszonym zamknięciu wygasa ona najpóźniej po 90 sekundach.
Ustawienia dotyczą push, nie skrzynki w aplikacji ani trwających Live Activities.

Test potwierdza przyjęcie przez usługę push, a nie wyświetlenie na konkretnym
telefonie. Sprawdź ekran blokady lub centrum powiadomień. Android korzysta z
UnifiedPush i pokazuje instrukcję instalacji ntfy, gdy brakuje dystrybutora.
iOS rozróżnia brak konfiguracji APNs organizacji i odmowę zgody systemowej.
Nie dodano zależności od Firebase.


## Push { #push }

| Gdzie | Przez | Włączane w |
|---|---|---|
| iPhone | Usługę push Apple, z własnym kluczem APNs organizacji (Admin → Ustawienia) | Ustawienia aplikacji → Powiadomienia |
| Android | ntfy (ntfy.sh albo własny serwer firmy), nie Google | Ustawienia aplikacji → Powiadomienia, z zainstalowaną aplikacją ntfy |
| Przeglądarka albo konsola dodana do ekranu głównego | Web Push, z własnym kluczem wdrożenia | Ustawienia → Powiadomienia |

Powiadomienia każdego zdarzenia - e-mail, push - wybiera się osobno w Ustawienia →
Powiadomienia. Powiadomienie otwiera swoją stronę przez blokadę aplikacji.

Push zarejestrowany przez sesję przestaje być wysyłany po jej odwołaniu lub
wygaśnięciu. Powiązany token działa tylko wtedy, gdy sesja należy do tego samego
użytkownika. Starsze subskrypcje bez zapisanej sesji zachowują dotychczasową
zgodę; usuń je i zarejestruj ponownie, aby przypisać je do bieżącego urządzenia.

Podgląd APNs jest skracany tak, aby cała wiadomość mieściła się w 4 KiB; zbyt
długi adres docelowy otwiera dashboard. Błąd tematu lub środowiska APNs nie usuwa
rejestracji urządzenia, dzięki czemu administrator może poprawić konfigurację.
Jeśli choć jedno urządzenie przyjęło push przed upływem limitu czasu, dostawa jest
uznawana za wysłaną, bez ponawiania na już powiadomionych urządzeniach.


## Poza aplikacją { #outside-the-app }

**Live activities** - ekran blokady i Dynamic Island na iOS, stałe powiadomienie
na Androidzie - pokazują to, co dla ciebie trwa:

- twoje runy w toku, z zegarem;
- akceptację czekającą na ciebie, z przyciskiem Sprawdź akceptację;
- pytanie, na którego odpowiedź czeka agent, otwierające jego rozmowę;
- rozmowę głosową w toku, z zegarem, mówiącą, kiedy agent o coś pyta.

Link aktywności otwiera kolejkę akceptacji. Sam nigdy nie zatwierdza ani nie
odrzuca narzędzia: sprawdź argumenty i wybierz w aplikacji. Starsze linki
zatwierdzenia i odrzucenia również otwierają podgląd bez podejmowania decyzji.

**Widżety.** Widżet podglądu liczy akceptacje czekające na ciebie i twoje runy w
toku, z czasem, kiedy je policzono, oraz część miesięcznego budżetu organizacji,
która została, gdy ma ona limit. Widżet przypiętych agentów otwiera nowy czat z
agentem przypiętym na jego stronie; na Androidzie przypięcie stawia też skrót w
launcherze z twarzą agenta. Liczby pochodzą z konsoli i odświeżają się, ilekroć je
odczyta.

**Skróty.** Menu długiego przytrzymania ikony, Skróty i Siri, przycisk czynności i
Centrum sterowania na iOS oraz kafelek Szybkich ustawień na Androidzie zaczynają
rozmowę głosową, dyktowanie, nowy czat albo akceptacje.

**Udostępnij do AgenticOS.** Arkusz Udostępnij każdej aplikacji oferuje AgenticOS:
tekst, linki, zdjęcia i pliki (do 20 MB każdy) trafiają do nowej wiadomości. Nic
nie jest dołączane, gdy aplikacja jest zablokowana.

## W aplikacji { #in-the-app }

- **Czat jak komunikator.** `+` w polu wiadomości otwiera Aparat, Zdjęcia i Pliki,
  potem wprowadzanie głosowe i polecenia, rozmowę, model i akceptacje. Otwarcie
  czatu proponuje zdjęcie zrobione przed chwilą; do wiadomości trafiają tylko
  zdjęcia, które stukniesz.
- **Gesty.** Przesuń czekającą akceptację w prawo, żeby ją zatwierdzić, albo w
  lewo, żeby odrzucić, i pociągnij stronę w dół, żeby odczytać ją ponownie, z
  wibracją, gdy puszczenie zadziała.
- **Strony ruszają się jak w telefonie.** Otwierana strona wjeżdża od końcowej
  krawędzi, a ta, do której się wraca, od początkowej. Ograniczony ruch to
  wyłącza.

Formularz logowania i czat mieszczą się nad klawiaturą, z uwzględnieniem paska
stanu i wskaźnika gestów. Przyciski zachowują pełne pole dotyku także przy małych
ikonach; kopiowanie i ukrywanie wskazówek jest dostępne bez najeżdżania kursorem.
Natywnego logowania nie zasłania baner cookies przeznaczony dla przeglądarki.

## Bez sieci { #without-a-network }

Aplikacja na telefon, aplikacja desktopowa i konsola dodana do ekranu głównego
trzymają na urządzeniu kopię przez siedem dni: listę rozmów, dwadzieścia ostatnio
otwartych rozmów z ich najnowszymi plikami, kolejkę akceptacji oraz wydatki,
błędy i rozmowy do podjęcia z dashboardu. Kopia jest zapieczętowana kluczem,
którego żaden skrypt nie odczyta, i usuwana przy wylogowaniu albo zmianie
organizacji; zwykła karta przeglądarki nie trzyma niczego.

Bez sieci konsola pokazuje tę kopię pod paskiem mówiącym, kiedy ją zapisano.
Wiadomość napisana offline czeka nad polem wiadomości, przetrwa zamknięcie
aplikacji i wysyła się, gdy połączenie wróci; taka, którą serwer odrzuci, wraca
oznaczona „Nie wysłano” z powodem.

## Zainstaluj konsolę zamiast tego { #installing-the-console-instead }

W przeglądarce, która potrafi ją zainstalować, pasek pod nagłówkiem konsoli to
proponuje: własne okno, push i ikona na ekranie głównym, bez natywnych dodatków
powyżej. Na iPhonie mówi, jak to zrobić - Udostępnij, potem Do ekranu
początkowego. Raz odrzucony nie wraca w tej przeglądarce.

## Zarządzanie urządzeniami { #device-management }

Organizacja może ustawić serwer, z którym łączy się aplikacja, zablokować go,
żeby nie dało się wskazać innego, i wymusić włączenie albo wyłączenie blokady
biometrycznej - klucze `serverUrl`, `serverLocked` i `biometricLock` (`person` |
`on` | `off`) w zarządzanych konfiguracjach Androida i zarządzanej konfiguracji
aplikacji iOS (AppConfig). Polityka, której nie da się odczytać, jest ignorowana,
zamiast kogoś zablokować.

## Gdzie to jest w drzewie { #where-it-sits-in-the-tree }

- `mobile/src-tauri/src/` - pluginy Rust, które wywołuje konsola: live activities
  (`live.rs`), widżety (`widget.rs`), przypięcia, udostępnianie, push i zarządzana
  konfiguracja.
- `mobile/src-tauri/ios/Sources/AgenticOSNative/` - pluginy iOS i typy, które
  rozszerzenie widżetów dzieli z aplikacją.
- `mobile/src-tauri/gen/apple/Widgets/` - widżety, kontrolki i live activity.
- `mobile/src-tauri/gen/android/` - projekt Androida: pluginy, widżety i ich
  układy.
- `frontend/src/components/mobile/` - połowa konsoli: co trwa, liczby widżetu,
  akcje, które oddaje aplikacja.

## Podsumowanie { #recap }

- **Konsola zostaje na serwerze.** Aplikacja ją otwiera i dodaje własne miejsca
  telefonu.
- **Na żywo poza aplikacją**: runy, akceptacje, pytania i rozmowy na ekranie
  blokady; liczby, budżet i przypięte agenty na widżetach.
- **Push bez Google** na Androidzie, z własnym kluczem organizacji na iPhonie.
- **Kopia na urządzeniu**, zapieczętowana, na czas bez sieci.
