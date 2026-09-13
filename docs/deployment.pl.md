---
source_sha: e5e660ee22ce
---

# Samo wdrożenie { #the-deployment-itself }

Większość tego produktu dotyczy agentów. Ta strona dotyczy tego, w czym one
działają.

**Jedna instalacja, z nazwą, znakiem, regułą mówiącą, kto może do niej dołączyć,
i przełącznikiem, który ją zamyka.** Wszystko to mieści się w jednym wierszu bazy
danych i jest edytowane z `/admin/settings` przez tego, kto ma `is_app_admin` —
bez ponownego wdrożenia, bez zmiennej środowiskowej, bez przebudowy.

!!! info "Dlaczego ta władza, a nie uprawnienie"

    Uprawnienie jest ograniczone do organizacji. Ten wiersz nie należy do żadnej.

    To ta sama władza, która już administruje użytkownikami i tenantami w całej
    instalacji.

## Tożsamość { #identity }

| Pole | Gdzie się pojawia |
|---|---|
| Name | Panel boczny, nagłówek logowania, karta przeglądarki, karta OpenGraph i każdy e-mail, który to wdrożenie wysyła |
| Tagline | Obok nazwy w tytule karty i w udostępnionym linku |
| Description | Opis strony i podglądy linków |
| Logo | Wszędzie tam, gdzie pojawia się nazwa — link marki, nagłówek logowania, strony prawne |
| Favicon | Karta przeglądarki |
| Footer text | Pod formularzem logowania |
| Terms URL, Privacy URL | Każdy link, który w przeciwnym razie prowadzi do wbudowanych stron `/legal/*` |

!!! note "Kolumna null oznacza *wartość wbudowaną*, a nie *pustą*"

    Operator, który czyści pole, prosi o powrót wartości domyślnej, a nie
    o nagłówek logowania bez nazwy. API odpowiada *nadpisaniami*, a każdy renderer
    rozstrzyga null względem własnej wartości wbudowanej.

Operator, który nigdy nie otworzył tej strony, nie ma w ogóle wiersza. Konsola
rozstrzyga null względem `APP_NAME` i `SITE` w `frontend/src/lib/`; backend
rozstrzyga go względem `settings.PROJECT_NAME` dla poczty, którą wysyła sam.

Dwie stałe na jedną nazwę produktu mogą się rozjechać, więc
`backend/tests/test_deployment_settings.py` przypina je do siebie. Czyta
`constants.ts` z frontendu i porównuje go z domyślną wartością klasy
`Settings.PROJECT_NAME` — to ta sama umowa, jaką `TestFrontendToolCatalog`
zawiera z katalogiem narzędzi.

### Dwa obrazy { #the-two-images }

Wgrywane przez `POST /api/v1/admin/settings/{logo,favicon}` i przechowywane tak
jak każdy inny obraz na tej platformie: bajty trafiają do skonfigurowanego
magazynu plików, a klucz do kolumny. **Klucz nigdy nie pochodzi z ciała
żądania** — wywołujący, który mógłby go nazwać, mógłby wskazać publicznemu logo
tego wdrożenia cokolwiek, co trzyma magazyn — a zapisana nazwa pliku powstaje ze
zwalidowanego typu treści, a nie z nazwy samego przesłanego pliku, ponieważ te
pliki są serwowane z tego samego origin, na którym działają strony aplikacji,
a `logo.html` jest tam skryptem.

JPEG, PNG, WebP i GIF, do 2 MB — to jedyna definicja „obrazu, który ta platforma
przyjmuje”.

!!! danger "SVG jest nieobecny celowo"

    To dokument, który może nieść skrypt, a te pliki są serwowane z tego samego
    origin, na którym działają strony aplikacji. ICO nie daje niczego, czego nie
    daje favicon w PNG.

Odpowiedź brandingu niesie **wersję**, a nie URL. Adres jest stały
(`GET /api/v1/branding/{logo,favicon}`), a bajty są serwowane jako `immutable`
przez rok, więc z tego wiersza klient potrzebuje tylko tego, czy obraz istnieje
i kiedy ostatnio się zmienił; zbudowane z tego `?v=` jest jedynym powodem, dla
którego podmiana w ogóle się pojawia. URL byłby dodatkowo czymś, co każdy klient
musiałby przepisywać, bo w każdym prawdziwym wdrożeniu API nie stoi na tym samym
origin co strony.

## Nagłówki bezpieczeństwa { #security-headers }

Każda strona konsoli niesie Content-Security-Policy oraz zwyczajowe nagłówki
utwardzające, zdefiniowane w `frontend/src/lib/csp.ts` i
`frontend/src/lib/security-headers.ts`, jedne i drugie potwierdzone testami.
Polityka to `default-src 'self'` z `connect-src` nazywającym dokładnie ten origin,
`PUBLIC_API_URL` i `PUBLIC_WS_URL`, `img-src` dopuszczającym `data:` dla znaków
marki i awatarów, `frame-src 'self' blob:` dla podglądów dokumentów, `object-src
'none'`, `base-uri 'self'` oraz `frame-ancestors 'none'`.

Polityka jest stemplowana przy każdym żądaniu przez middleware frontendu,
ponieważ oba publiczne adresy URL są czytane ze środowiska serwera w czasie
działania, a nagłówek ustawiony w czasie budowania mógłby nazwać tylko
`localhost`. Pozostałe nagłówki są stałymi i ustawia je konfiguracja Next. Zmień
publiczne adresy URL, a polityka pójdzie za nimi przy następnym żądaniu; nic nie
jest przebudowywane.

Obok niej stoją `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin` oraz `Permissions-Policy`,
która odmawia kamery i geolokalizacji, a mikrofon dopuszcza wyłącznie na tym
origin, na potrzeby zamiany mowy na tekst w czacie.

!!! warning "Reverse proxy nie może dodawać własnych kopii tych nagłówków"

    Nginx, Traefik albo ALB stojący przed aplikacją przepuszcza je bez zmian,
    zamiast ustawiać własne. Dwa nagłówki `Content-Security-Policy` w jednej
    odpowiedzi przeglądarka łączy w ich część wspólną, więc proxy, które dodaje
    drugi — nawet luźniejszy — jedynie zacieśnia politykę do czegoś, co blokuje
    panel, którego nikt nie zamierzał blokować; a przy drugim `X-Frame-Options`
    przeglądarka może wybrać dowolną z wartości. Dołączony `nginx/nginx.conf`
    ustawia tylko `Strict-Transport-Security`, który należy do tego, co terminuje
    TLS; istniejąca konfiguracja proxy, która dodaje pozostałe, powinna je usunąć.

## Kto może się zarejestrować { #who-may-register }

`signup_mode`, stosowany w `app/services/signup_policy.py` — w jednym miejscu,
i bramkuje **obie** ścieżki, które tworzą konto.

| Tryb | Skutek |
|---|---|
| `open` | Każdy może się zarejestrować. Wartość domyślna i to, czym było każde wdrożenie przed tą funkcją. |
| `invite_only` | Tylko adres, który jakaś organizacja faktycznie zaprosiła. |
| `closed` | Nikt się nie rejestruje, żadną drogą — zaproszenie tego nie omija. |

We wszystkich trzech trybach niepusta lista `allowed_email_domains` zawęża to,
kto w ogóle może się zarejestrować. **Zaproszenie ma pierwszeństwo przed tą
listą** — ktoś, kto ma `members:invite`, wskazał ten adres celowo, a lista domen
jest polityką wdrożenia wobec obcych, a nie prawem weta wobec świadomej decyzji.
`closed` nie jest omijane przez nic, bo „zamknięte”, które przepuszcza część
rejestracji, nie jest zamknięte.

**`closed` znaczy zamknięte i nie ma ścieżki, w której administrator tworzy
konto.** Celowo: konto potrzebuje hasła wybranego przez właściciela, więc dodanie
kogoś oznacza otwarcie rejestracji *dla niego* — i od tego jest `invite_only`.
Tryb, który pozwalałby administratorowi wybijać konta, byłby trzecią ścieżką
tworzącą konto, a te dwie, które już istnieją, są całym powodem, dla którego
`signup_policy` jest modułem, a nie sprawdzeniem wewnątrz `register`. Wdrożenie,
które musi wpuścić jeszcze jedną osobę, przełącza się więc na `invite_only`
i ją zaprasza.

Jeszcze trzy rzeczy, które łatwo tu pomylić — i które pomylono:

**Pierwszy użytkownik zawsze zostaje wpuszczony.** Świeża instalacja nie ma kont,
więc jej administrator jeszcze nie istnieje; zamknięte wdrożenie, które odrzuca
także osobę, która miałaby je otworzyć, to wdrożenie, do którego nikt nie wejdzie
i którego nie ma z czego naprawić. `register` i tak podnosi to pierwsze konto do
`is_app_admin`, a polityka opiera się na tym samym fakcie.

**`invite_only` istnieje dlatego, że zamknięcie rejestracji zepsułoby inaczej
zaproszenia.** `InvitationService.accept` wymaga istniejącego, zalogowanego
użytkownika, więc zaproszona osoba musi najpierw się zarejestrować. Polityka pyta
`invitation_repo.first_pending_admitting`, które z konstrukcji sięga przez
wszystkie tenanty — rejestracja dzieje się, zanim wybrana zostanie organizacja.
Bezpieczne trzyma to miejsce, do którego trafia odpowiedź: polityka zamienia ją
w logiczne odrzucenie, więc obcy sondujący formularz rejestracji dowiaduje się,
że ktoś zaprosił ten adres, a nigdy tego, która organizacja to zrobiła.

**To, jak rozpoznawane jest zaproszenie, zależy od tego, czy rejestracja niesie
jego token**, a te dwie odpowiedzi obejmują różne kształty:

| Przychodzi z | Rozpoznawane przez | Jakie kształty wpuszcza |
|---|---|---|
| Tokenem (rozstrzygniętym z przygotowanego zaproszenia, nigdy z ciała rejestracji) | `invitation_admission.admits` | Każde żywe zaproszenie, które wpuszcza ten adres — w tym link, który nie ogranicza **żadnego** adresu, czyli kształt, którego nic innego nie widzi |
| Bez tokena | `invitation_repo.first_pending_admitting` | Zaproszenie e-mailowe na ten adres albo link ograniczony do jego domeny |

Token jest jedynym dowodem dostępnym dla linku do udostępnienia, który nie niesie
ani adresu, ani domeny. Zapytanie o przesłany adres nie rozpozna takiego linku,
więc uhonorowanie go *bez* dowodu posiadania zamieniłoby jeden otwarty link
gdziekolwiek w tym wdrożeniu w otwartą rejestrację dla całego internetu.
Posiadanie tokena jest tym dowodem.

Token, który nie wskazuje niczego żywego, przechodzi do pytania o adres, zamiast
odrzucać: nieaktualny link w zakładkach nie powinien zamieniać rejestracji, która
skądinąd byłaby dozwolona, w błąd dotyczący czegoś, czego ta osoba nie może
naprawić.

**Rejestracja z tokenem nie przyjmuje zaproszenia.** Wpuszcza konto i nic więcej;
dołączenie do organizacji to nadal `InvitationService.accept`, które klient
wywołuje, gdy ma już sesję. Token w nieuwierzytelnionym ciele rejestracji, który
dodatkowo przyznawałby członkostwo, byłby przyznaniem członkostwa na publicznej
trasie.

Konsola nigdy nie przenosi tokena przez obieg logowania. Zaproszony bez konta
otwiera `/invitations/<token>`; `AuthGuard` wymienia token po stronie serwera na
nieprzezroczysty uchwyt, który trzyma w ciasteczku `httpOnly`, nieczytelnym dla
przeglądarki, a potem odsyła go na `/login?returnTo=/invitations/pending?flow=…` —
stronę bez poświadczenia, więc tokena nie ma ani w `returnTo`, ani w historii
przeglądarki, ani w session storage. Jeśli wymiana się nie uda — serwer
nieosiągalny, limit żądań — guard zostaje przy linku z zaproszeniem i proponuje
ponowną próbę, zamiast odejść bez niczego przygotowanego, bo ten link jest
jedynym poświadczeniem, jakie zaproszony ma.

`flow` to losowy identyfikator, który wymiana wybija przy każdym przygotowaniu,
i to od niego nazywane jest ciasteczko. Nie jest poświadczeniem: bez ciasteczka
nie wskazuje niczego. Jest po to, że jedna stała nazwa ciasteczka to jedno
miejsce — dwa linki z zaproszeniem otwarte obok siebie bez zalogowania
nadpisywały się nawzajem, a obie oczekujące karty realizowały potem ten drugi.
Teraz każda karta realizuje dokładnie to ciasteczko, które wskazuje jej własny
`flow`.

„Create an account” niesie tę pozbawioną poświadczenia stronę dalej, a proxy
rejestracji przekazuje przygotowany uchwyt wskazanego `flow` jako nagłówek, więc
wpuszczenie przy rejestracji nadal ma token, którego potrzebuje, a token nigdy
nie znajduje się w URL-u ani w ciele żądania. Po zalogowaniu strona oczekująca
realizuje uchwyt i przyjmuje zaproszenie — ten sam kształt co wymiana kodu OAuth:
nieprzezroczysty, jednorazowy, wygasający zamiennik poświadczenia, żeby samo
poświadczenie nigdy nie jechało w URL-u. Ciasteczko jest czyszczone po wykonanej
realizacji; 401, 429 albo awaria serwera je zostawia, bo uchwyt może być wciąż
niewykorzystany, a ponowna próba go potrzebuje.

**Link z `max_uses` ogranicza konta, a nie tylko dołączenia.**

`used_count` liczy przyjęcia, a przyjęcie wymaga sesji — więc pułap odczytywany
z niego samego nie ograniczał niczego, co robiła rejestracja. Jeden jednorazowy
link wrzucony na kanał wpuszczał tyle kont, ile komukolwiek chciało się utworzyć,
na wdrożeniu, które właśnie zamknęło rejestrację.

Dlatego użycie jest najpierw **rezerwowane** dla rejestrującego się adresu:
`reserved_emails` w wierszu, a „zużyte” znaczy `used_count + reserved_emails`.
Rezerwacja to pojedynczy warunkowy `UPDATE`, bo dwie rejestracje ścigające się
o ostatnie użycie odczytałyby w przeciwnym razie ten sam licznik.

Przyjęcie zaproszenia usuwa adres z listy, zwiększając jednocześnie licznik, co
go zachowuje — ktoś, kto zarejestrował się przez jednorazowy link, nadal może
dołączyć.

Rezerwacja, której nikt nie przyjmie, pozostaje zużyta (`max_uses` mówi, ile osób
link wpuszcza, a konto utworzone przy jego użyciu zostało wpuszczone) i umiera
razem z zaproszeniem.

**Logowanie przez providera także niesie zaproszenie, w postaci jego uchwytu.**
Logowanie przez providera zaczyna się na tym samym origin, pod
`/api/oauth/<provider>/login`, więc przygotowany uchwyt `httpOnly` da się dołączyć
do międzyoriginowego skoku, który przeglądarka potem wykonuje —
`/oauth/google/login?invitation_handle=…`, z którego backend wydobywa token
trzymany przez siebie w sesji przez cały obieg. Tokena nigdy nie ma w tym URL-u.
Bez tego `invite_only` odrzucał przycisk Google dokładnie dla tych linków, które
potrzebują tokena — takich, które nie ograniczają ani adresu, ani domeny —
podczas gdy stojący obok formularz z hasłem przyjmował tę samą osobę.

**Logowanie przez providera też jest rejestracją.** `get_or_create_oauth_user` to
druga ścieżka tworząca konto, a w callbacku od Google nic nie wygląda jak
rejestracja — więc wdrożenie z `closed` i przyciskiem Google stało otworem,
dopóki nie zabramkowano obu. Ktoś, kto *już* ma konto, nie jest bramkowany
ponownie: zamknięcie rejestracji zamyka rejestrację, a odcięcie członka od
wdrożenia, do którego należy, nie jest tym, co mówi to ustawienie.

Formularz rejestracji czyta politykę z publicznego endpointu brandingu i podaje
regułę, **zanim** ktokolwiek cokolwiek wpisze. Formularz, który przyjmuje adres,
a potem zgłasza „ta domena e-mail nie może się zarejestrować”, to formularz,
który kłamie; odwiedzający nie ma jak wiedzieć, że reguła istnieje, i czyta
odrzucenie jako zepsuty produkt. To także powód, dla którego dozwolone domeny są
publikowane: nie są tajemnicą, a wdrożenie stoi na własnym hoście firmy.

## Znalezienie jednego tenanta wśród wszystkich { #finding-one-tenant-among-all-of-them }

`GET /admin/organizations` to jedyna powierzchnia, która odpowiada na pytanie
*jakie tenanty istnieją*, i jest dostępna wyłącznie dla app admina dokładnie
z tego powodu, dla którego jest użyteczna: z konstrukcji sięga przez wszystkie
tenanty. Odpowiada stroną organizacji, z liczbą członków i agentów każdej z nich
oraz z jej najwcześniejszym właścicielem (owner) — czyli tym, kogo o nią zapytać.
Wszystkie pola właściciela są puste naraz w organizacji, której ostatni owner
odszedł; to stan, który może naprawić tylko admin wdrożenia, a więc taki, który
trzeba mu pokazać.

| Parametr | |
|---|---|
| `search` | Nazwa, slug albo adres właściciela. Fraza jest tekstem, a nie wzorcem — `100%` znajduje tenanta o takiej nazwie, a nie wszystkie |
| `sort_by` | `name`, `slug`, `members`, `agents`, `created_at`. Cokolwiek innego to 422 |
| `sort_dir` | `asc` / `desc`, domyślnie od najnowszych |
| `kind` | `personal`, `team` albo `all`. Każde konto dostaje przy rejestracji organizację osobistą, więc na większości wdrożeń to one stanowią większość listy |
| `skip`, `limit` | Jedna strona serwera, do 100 |

**Wszystko to dzieje się w SQL, przed `OFFSET`/`LIMIT`**, a `total` liczy to, do
czego zawężono, a nie całe wdrożenie. To różnica między sortowaniem a jego
pozorem: strona posortowana po tym, jak przyszła, rości sobie porządek całej
kolekcji, którego pięćdziesiąt wierszy nie jest w stanie dowieźć — dlatego lista
tenantów u admina nie miała żadnych kontrolek, dopóki trasa nie odpowiadała na
żadną (#921). Porządek rozstrzyga remisy po id, więc stronicowanie po kolumnie,
w której wiersze dzielą wartość, wypisuje każdy z nich raz.

Kolumna spoza tego zbioru zostaje odrzucona po nazwie, zamiast nie dopasować się
do niczego, z tych dwóch powodów, dla których odrzuca ją `GET /runs`: pusta
strona czyta się jako *to wdrożenie nie ma tenantów*, a `ORDER BY` sklejane
z query stringa jest powierzchnią do wstrzyknięć.

## App admin nie może odciąć się od wdrożenia z poziomu konsoli { #an-app-admin-cannot-lock-the-deployment-out-through-the-console }

!!! warning "Samoodcięcie, któremu to zapobiega"

    Na instalacji z jednym adminem, jaką tworzy `make platform-bootstrap`,
    przypadkowe kliknięcie we własny wiersz kończyło administrację do czasu, aż
    ktoś dotarł do terminala. Odzyskanie dostępu to
    `agenticos cmd create-app-admin <email>` z powłoki — adres e-mail jest
    argumentem wymaganym.

`is_active` jest egzekwowane przy następnym żądaniu, a `is_app_admin` jest tym,
co czytają strony administracyjne, więc app admin działający na **własnym**
wierszu z `/admin/users` mógł się wylogować, stracić `/admin` albo usunąć konto.
`UserService.admin_update` i
`admin_delete` odrzucają samozawieszenie i samousunięcie, a szuflada nie oferuje
Suspend, Demote ani Impersonate na twoim własnym wierszu (Delete zostaje,
widoczny i odrzucany, bo na pytanie „dlaczego nie mogę usunąć siebie” jest
odpowiedź, którą warto pokazać). API odrzuca też działanie jako ty sam — nikt
działający jako nikt nie jest impersonacją.

Przez API nie da się w ogóle zostawić wdrożenia bez app admina: ten jeden
globalny przywilej przyznaje wyłącznie CLI (`agenticos cmd create-app-admin`)
i nie ma żądania, które by go zdejmowało, więc zbiór app adminów kurczy się tylko
przez usunięcie — a usunięcie *ostatniego* z nich jest usunięciem siebie, co
zostaje odrzucone. Usunięcie admina, który naprawdę odchodzi, jest działaniem
innego admina, co dodatkowo trzyma ślad audytowy czytelnym. Odzyskanie dostępu,
gdyby kiedykolwiek było potrzebne, to nadal `create-app-admin` z powłoki na
wdrożeniu.

Ten argument dotyczy *zbioru*, a kod przez pewien czas dotyczył jednego wiersza.

Dwóch adminów usuwających się nawzajem — żaden z nich nie usuwał siebie.
Zablokowali różne wiersze docelowe, nigdy się nie zderzyli i obaj zacommitowali —
zero app adminów, do naprawienia wyłącznie zapisem do bazy danych (#1208).

Dlatego usunięcie admina bierze `SELECT ... FOR UPDATE` na zbiorze app adminów,
uporządkowanym po id, zanim podejmie decyzję. Drugie żądanie czeka, po commicie
pierwszego czyta zbiór ponownie i zostaje odrzucone za opróżnienie go.

Uporządkowanym, bo dwa żądania biorące te same wiersze w różnej kolejności to
zakleszczenie, a nie kolejka. I brane przy każdym usunięciu admina, a nie tylko
wtedy, gdy usuwany jest admin: usunięcie użytkownika jest działaniem
administratora, a nie gorącą ścieżką, a pełny porządek jest wart więcej niż
rywalizacja, którą kosztuje.

## Działanie jako inne konto { #acting-as-another-account }

**Impersonate** na `/admin/users` rozpoczyna działanie jako ta osoba z twojej
własnej przeglądarki. Nic nigdzie nie jest kopiowane: konsola podmienia
ciasteczko dostępu sesji na takie, które wskazuje cel, każda strona renderuje się
tak, jak widziałaby ją tamta osoba, a baner na górze mówi, czyje to konto i kto
naprawdę działa, z jednym przyciskiem, który to kończy.

Impersonacja jest **sesją**, a nie samym poświadczeniem. Token wskazuje wiersz
w `sessions` z ustawionym `impersonator_user_id`, a API odrzuca go w chwili, gdy
ten wiersz zostanie zakończony albo wygaśnie lub gdy stojący za nim administrator
nie jest już aktywnym app adminem — więc kończy się, gdy naciśniesz **End
impersonation**, gdy ta osoba wyloguje się wszędzie albo zmieni hasło, gdy minie
godzina, albo gdy administrator zostanie zawieszony, zdegradowany lub usunięty,
co nastąpi pierwsze. Nie da się jej odświeżyć: oknem jest własne okno tokena
dostępu, a godzina jest sufitem, a nie odnawialną dzierżawą.

!!! note "Otwarta rozmowa na czacie kończy się razem z nią"

    Rozmowa na czacie biegnie po WebSockecie, który uwierzytelnia raz, przy
    handshake'u. Teraz powtarza to sprawdzenie przy każdej wiadomości, więc
    zakończenie impersonacji — albo zawieszenie konta — zamyka także otwarty
    czat, zamiast jedynie odrzucać kolejne żądanie HTTP, podczas gdy gniazdo dalej
    odpowiada.

!!! note "Lista urządzeń tej osoby tego nie pokazuje"

    Impersonacja jest wierszem pod jej id, który trzyma administrator, a nie
    urządzeniem, z którego ta osoba się zalogowała — więc nie ma jej na liście jej
    urządzeń, w liczbie otwartych sesji w szufladzie ani w jej „ostatnio
    widziany”. To, czy w ogóle zostanie o tym powiedziane, rozstrzyga ustawienie
    poniżej, a wiersz na tej liście rozstrzygnąłby to za nią.

**To, czy osoba zostanie poinformowana, jest polityką ustawianą w tym wierszu.**
`notify_impersonated_users` jest domyślnie wyłączone; włączone — osoba dostaje
jednego e-maila w chwili rozpoczęcia impersonacji, z nazwą administratora. Ślad
audytowy zapisuje impersonację tak czy inaczej — i początek, i koniec, wraz
z sesją, do której należą — co opisuje [Nadzór](governance.md#audit).

## Komunikaty i zamykanie wdrożenia { #notices-and-closing-the-deployment }

**Ogłoszenie** to jedno zdanie w jednym z trzech stylów, pokazywane nad każdą
stroną zalogowanym użytkownikom, dopóki go nie zamkną. To jedyne pole w tym
wierszu, którego *nie ma* na publicznym endpoincie: ogłoszenie to operator mówiący
do ludzi korzystających z wdrożenia — okno aktualizacji, do kogo napisać — więc ma
własną trasę, `GET /api/v1/branding/notice`, za sesją.

Zamknięcie jest kluczowane po **samej treści komunikatu**, w magazynie samej
przeglądarki. Flaga sprawiłaby, że następne ogłoszenie byłoby niewidoczne dla
każdego, kto zamknął poprzednie; znacznik czasu z wiersza ustawień odznaczałby
zamknięcie komunikatu za każdym razem, gdy wdrożenie zmieniało nazwę. Zmienił się
tekst, więc kluczem jest tekst. Magazyn, który odmawia odczytu lub zapisu — tryb
prywatny, osadzony webview — oznacza „nic nie zamknięto”, a nie wyjątek: rzucony
w trakcie renderowania położyłby dashboard każdemu zalogowanemu użytkownikowi,
a baner i tak zamyka się na tak długo, jak długo strona jest otwarta.

**Tryb konserwacji trzyma zamknięte API**, a nie tylko konsolę.
`app/core/maintenance.py` to czysto-ASGI middleware ponad trasami, więc strona,
którą ktoś ma już otwartą, przestaje działać — i na tym polega cała różnica między
trybem konserwacji a banerem. Jego lista dozwolonych jest krótka i testowana
pozycja po pozycji:

- `/health*` — sonda gotowości, która zawodzi w trakcie okna, to orkiestrator
  restartujący kontener, w którym pracuje operator.
- `/api/v1/branding` — zamknięta strona musi móc powiedzieć, jak to wdrożenie się
  nazywa i dlaczego jest zamknięte.
- `/api/v1/auth/*` — administrator musi móc się zalogować **w trakcie** otwartego
  okna.
- `/api/v1/admin/*` — a potem dosięgnąć przełącznika.
- Dokumentacja i schemat OpenAPI, które nie serwują żadnych danych.

Wszystko inne to 503 z `Retry-After`. Nie czyta w ogóle sesji — oznaczałoby to
weryfikowanie tokena ponad grafem zależności — więc poszerzenie ścieżki o
`/api/v1/admin/*` nie poszerza władzy: `CurrentAppAdmin` odrzuca tam osobę spoza
adminów dokładnie tak, jak robił to zawsze.

**Zawodzi w stronę otwartą.** Bramka, która nie potrafi odczytać własnego
przełącznika — czkawka Redisa, migracja, która się nie wykonała — przepuszcza ruch,
bo alternatywa zamienia potknięcie infrastruktury w całkowitą niedostępność,
której nikt nie zaplanował.

Werdykt jest cache'owany w tym samym Redisie, który dzieli już każdy worker:
zapisywany **po commicie**, więc przełącznik działa natychmiast, a cache nigdy nie
może ogłaszać stanu, który baza wycofała — publikowany zachłannie, przy żądaniu,
które potem zawiodło, zostawiał wyłączone okno ponownie otwierające wdrożenie na
czas nawet całego TTL. Niesie też TTL wynoszący 30 sekund, więc zapis, który nigdy
nie dotarł do Redisa, sam się leczy, zamiast zostawić wdrożenie otwarte przez
okno, które ktoś zaplanował.

**A strona już otwarta się o tym dowiaduje.** Kontekst brandingu jest rozstrzygany
raz przez główny layout serwera i nie zmienia się przez całe życie strony, więc
okno otwarte później zostawiało każdą otwartą kartę na dashboardzie, którego każde
żądanie zaczęło odpowiadać 503, bez niczego na ekranie, co mówiłoby dlaczego —
a zamknięcie okna zostawiało kartę na ekranie konserwacji, dopóki ktoś nie
przeładował. `GET /api/v1/branding/notice` niesie werdykt konserwacji obok
ogłoszenia i jest odpytywany raz na minutę, czyli jedno żądanie po obie odpowiedzi
zamiast dwóch, które mogą się o jeden wiersz nie zgadzać.

W konsoli administrator widzi pasek, a nie zamkniętą stronę. Jest jedyną osobą,
która może zakończyć okno, a tryb konserwacji, który ukrywa także przełącznik,
jest awarią.

## Ile jedno konto może zająć { #how-much-one-account-may-take-up }

Dwa pułapy, oba w tym samym wierszu i oba **domyślnie null — a null oznacza brak
limitu, a nie „nieskonfigurowane”**. Samodzielnie hostowane wdrożenie dla jednej
firmy nie chce żadnego z nich; wdrożenie otwarte na rejestracje chce obu, bo
w przeciwnym razie jedno konto może wybijać tenanty bez ograniczeń.

| Ustawienie | Liczy | Nie liczy |
|---|---|---|
| Organizacje na konto | Organizacje, które konto **posiada**, wliczając osobistą | Te, do których zaprosił je ktoś inny |
| Agenci na organizację | Agenci należący do organizacji | Zarchiwizowanych agentów |

**Sprawdzane jest każde przejście do stanu liczonego, a nie tylko utworzenie.**
Pułap egzekwowany wyłącznie na nowych wierszach to pułap, który obchodzi się
bokiem: organizacja na swoim limicie agentów archiwizuje jednego, tworzy
zastępcę i przywraca to, co zarchiwizowała, a konto na swoim limicie organizacji
dostaje cudzą przez `transfer_ownership`. Dlatego `unarchive`
i `transfer_ownership` zadają to samo pytanie co `create`.

**A liczenie odbywa się pod blokadą.** Odczyt `count(...) >= limit`, a potem zapis
to dwa polecenia, więc dwa żądania oba przechodzą zliczenie i oba wstawiają wiersz
— pułap przekroczony deterministycznie, przez dwukrotne kliknięcie. Żadne
ograniczenie nie wyrazi „najwyżej N takich wierszy”, więc `app/db/locks.py` bierze
blokadę doradczą w zasięgu transakcji na *podmiocie* pułapu: dwa żądania o jedno
konto ustawiają się w kolejce, żądania o różne konta nigdy się nie spotykają,
a blokadę zwalnia commit albo rollback. Tylko tam, gdzie limit jest ustawiony,
więc wdrożenie bez pułapów nie płaci nic.

Oba wykluczenia są sednem tego projektu, a nie jego szczegółem. Zaproszenie do
dziesięciu organizacji jest cudzą decyzją, a pułap, którego jedna osoba nie
kontroluje, to pułap odcinający ją od tworzenia własnych. A archiwizacja jest
sposobem na wycofanie agenta — pułap, który wycofany agent dalej by zajmował,
sprawiłby, że jedyną drogą powrotu pod niego jest usunięcie, które zabiera ze sobą
historię wersji i przypisanie runów.

Odrzucenie nazywa pułap i liczbę, względem której go zmierzono
(`{"limit": 5, "held": 5}`), więc na „dlaczego nie mogę” odpowiada odpowiedź,
a nie pamięć administratora. Jest podnoszone w serwisie, który tworzy daną rzecz,
a nie na trasie, bo trasa nie jest jedyną drogą do środka.

Zero jest odrzucane przez schemat: konto, które nie może posiadać żadnej
organizacji, to konto, którego nie da się utworzyć, skoro rejestracja daje każdemu
z nich organizację osobistą.

## Ten wiersz { #the-row }

Jeden wiersz na całą instalację, pilnowany przez bazę danych, a nie przez
konwencję, której nikt nie widzi: `singleton` jest unikalny i ograniczony do
wartości prawda, więc druga tożsamość jest `IntegrityError`, a nie wdrożeniem,
które po cichu ma dwie i serwuje tę, którą zapytanie ustawiło pierwszą. Zapis to
pojedynczy `INSERT ... ON CONFLICT DO UPDATE`, bo odczyt-a-potem-wstawienie ściga
się samo ze sobą w chwili, gdy dwóch administratorów zapisuje z dwóch kart.

**Nic nie jest zasiewane.** Brak wiersza oznacza same wartości domyślne, czyli
dokładnie stan wdrożenia, którego nikt nie skonfigurował — i ma to znaczenie,
ponieważ publiczny endpoint brandingu jest nieuwierzytelniony i odpytywany przy
każdym zimnym załadowaniu strony, więc odczyt tworzący wiersz pozwoliłby obcemu
wywołać `INSERT`.

Każdy zapis jest audytowany do `app_admin_audit_logs`, z nazwami **pól**,
a nigdy z ich wartościami: ogłoszenie i lista domen są jednym i drugim tekstem
operatora, a wiersz audytu żyje dłużej niż ciało żądania, z którego pochodzi.

## Odrzucenie z tego wdrożenia zawsze wygląda tak samo { #a-refusal-from-this-deployment-always-looks-the-same }

Warto powiedzieć to tutaj, bo zamykanie wdrożenia to funkcja, która najpewniej
wyprodukuje odrzucenie, jakiego nikt wcześniej nie widział.
`app/api/exception_handlers.py` wkłada **każde** odrzucenie w
`{"error": {"code", "message", "details"}}`:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Agent not found",
    "details": { "agent_id": "…" }
  }
}
```

Obejmuje to wyjątki domenowe, walidację schematu,
a od #917 również `HTTPException`, co pokrywa 405, niedopasowaną ścieżkę oraz te
dwadzieścia dwie trasy, które podnoszą go bezpośrednio. Dwa kształty na łączu
oznaczają, że każdy wywołujący albo obsługuje oba, albo po cichu źle obsługuje
jeden.

Żądanie z niewłaściwą metodą odpowiadało dawniej **500** zamiast 405, na każdej
trasie. Instrumentacja FastAPI w OpenTelemetry wyprowadza nazwę spanu, chodząc po
`app.routes`, a jej gałąź `Match.PARTIAL` — czyli dokładnie „ścieżka pasuje,
a metoda nie” — czyta `.path` bez zabezpieczenia; FastAPI 0.141 wkłada do tej
listy obiekty `_IncludedRouter`, a te go nie mają. `app/core/otel_compat.py`
dostarcza dla tej gałęzi to samo zastępcze zachowanie, którego upstream używa już
w gałęzi zabezpieczonej. Wciąż niepoprawione w upstreamie na 0.65b0,
a `tests/test_otel_route_details.py` zawodzi, gdy zostanie poprawione — i wtedy
moduł znika.

## Podsumowanie { #recap }

- Tożsamość wdrożenia to **jeden wiersz**, edytowany z `/admin/settings`,
  a kolumna null oznacza *wartość wbudowaną*, a nie *pustą*.
- `signup_mode` jest stosowany w **jednym miejscu** i bramkuje obie ścieżki, które
  tworzą konto. Zaproszenie ma pierwszeństwo przed listą domen; `closed` nie
  ustępuje niczemu.
- App admin **nie może odciąć sam siebie** z poziomu konsoli.
- **Impersonacja jest sesją**: uruchamiana z konsoli bez żadnego tokena
  w schowku, nazwana w banerze, kończona przez administratora, przez wylogowanie
  się danej osoby wszędzie albo przez upływ godziny. To, czy ta osoba zostanie
  poinformowana, rozstrzyga `notify_impersonated_users`, domyślnie wyłączone.
- Każde odrzucenie z tego wdrożenia wygląda tak samo, niezależnie od tego, która
  warstwa je wyprodukowała.
