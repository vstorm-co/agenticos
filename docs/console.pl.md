---
source_sha: "27d973f8560b"
---

# Konsola { #the-console }

Konsola to aplikacja webowa, przez którą konfiguruje się wszystko inne opisane na
tej stronie. Ta strona jest mapą: do czego służy każdy obszar i która strona
wyjaśnia go porządnie.

Jeśli szukasz jednego ekranu, najszybszą drogą jest **"?"** w nagłówku strony —
odtwarza on przewodnik po tej stronie, a strona, w której nagłówku nie ma "?",
nie ma przewodnika do odtworzenia.

## Dashboard { #the-dashboard }

Strona startowa to **układalna siatka widgetów** i jest odpowiedzią na pytanie
"co się dzieje" bez otwierania pięciu stron.

Istnieje trzydzieści osiem kart. Nie zobaczysz wszystkich: **karta jest
bramkowana uprawnieniem, którego wymagają jej dane**, więc widget, którego nie
możesz odczytać, nigdy się nie montuje, a jego zapytania nigdy nie wychodzą —
poza twoimi własnymi powiadomieniami, niżej, które wymagają tylko tego, żebyś
był zalogowany. Pusty pas znika razem ze swoim nagłówkiem, zamiast stać tam
pusty.

Przełącznik na górze mówi, czyj to dashboard, i oferuje tylko widoki, które
możesz otworzyć. Każdy zaczyna od widoku **Ja**:

| Widok | Odpowiada na |
|---|---|
| **Ja** | Powitanie i Twój okres w jednym zdaniu; Twoje runy, ile się skończyło, co na Ciebie czeka i ile to kosztowało; potem wywołania czekające na Ciebie, Twoje rozmowy, Twoi agenci i co Ci udostępniono |
| **Organizacja** | Układalna strona opisana niżej |
| **Grupa** | Członkowie jednej [grupy](departments.md) - ich runy, wydatki, modele, kiedy pracują i kto korzysta najwięcej. Grupę wybierasz obok przełącznika. Grupa, której członkowie nic nie uruchomili w okresie, mówi to raz, z przejściem do grupy, zamiast strony pustych kart |
| **Wdrożenie** | Tylko dla [admina deploymentu](permissions.md) — sumy platformy, kondycja, najbardziej obciążeni najemcy, oceny |

Widok organizacji pokazuje karty, które odpowiadają danymi, pogrupowane w pasy.
Reszta - integracje, kanały, rutyny, synchronizacja wiedzy, działy, członkowie,
sandboxy - czeka w katalogu, jedno kliknięcie dalej pod **Customize**:

| Pas | Odpowiada na |
|---|---|
| *(bez tytułu, na górze)* | Podsumowanie, runy w czasie i to, jak się skończyły |
| **Needs attention** | Co czeka: [zatwierdzenia](governance.md#approvals), ostatnie błędy, zapas w budżecie, twoje najnowsze [powiadomienia](#the-bell) |
| **Usage & cost** | Których agentów się używa, wydatki, kiedy dzieje się praca, skąd przychodzą runy, miks modeli, opóźnienia, jakość odpowiedzi, kto z tego korzysta |

Kto buduje agentów, widzi też nad pasmami kartę **Get started**, dopóki nie
wykona wszystkich jej kroków: utworzyć agenta, opublikować go, dać mu bazę
wiedzy, dodać działy, zaprosić kogoś z zespołu i - jeśli może - wstawić agenta do
komunikatora. Każdy krok jest odhaczany na podstawie tego, co istnieje, gdziekolwiek
go zrobiono; zamknięcie karty ukrywa ją w tej przeglądarce.

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

## Dzwonek { #the-bell }

Obok wyszukiwania, w pasku bocznym: bieżący licznik tego, czego jeszcze nie
przeczytałeś, a kliknięcie otwiera samą listę. W przeciwieństwie do widgetu
powyżej, otwarcie pobiera stronę, na której właśnie jesteś, a nie pięciokartowy
podgląd — **Load more** cofa cię, stronę po stronie, przez organizację, w
której właśnie jesteś, plus to, co zaadresowano do całego wdrożenia, aż dojdzie
do tego, co wypadło z zasięgu.

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
*bieżących* uprawnień, więc ktoś zdegradowany na tydzień i przywrócony zastałby
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

Czego wyczyszczony wiersz *nie* robi, to nie wraca. Powiadomienie zostaje
zachowane i przestaje być wypisywane, zamiast zostać usunięte, i właśnie to
sprawia, że tak jest: skrzynka rozpoznaje powtórzenie po fakcie, który opisuje,
więc usunięty wiersz to taki, który następne sprawdzenie budżetu albo następna
próba zapisałyby ponownie. Odrzucenie alertu, którym się już zająłeś, jest więc
ostateczne — dla tego wystąpienia; *nowy*, o nowym fakcie, nadal przyjdzie.
Wiersze wychodzą też same z siebie: dziewięćdziesiąt dni po zapisaniu, jeśli
zostały przeczytane, i rok niezależnie od tego.

To, co tu trafia i co można wyłączyć, wyjaśnia [Governance](governance.md#alerts)
— ta strona to tylko dwa miejsca, w których to czytasz: dzwonek dla tego, co
się właśnie wydarzyło, karta na dashboardzie dla kilku najnowszych, przy
następnym otwarciu strony.

## Asystent { #the-assistant }

Na każdej stronie, w prawym dolnym rogu, jest **Architekt**: agent, którego
każda organizacja dostaje bez instalowania czegokolwiek, wspólny dla wszystkich,
którzy mogą uruchamiać agentów (`agents:run`). Jest powiązany z
[serwerem MCP tej platformy](mcp.md#agenticos-as-an-mcp-server). Zapytaj go,
którzy agenci odpowiadają na pytania o zwroty, dlaczego nocny run się nie udał
albo co jest w bazie wiedzy.

Poproś o szkic agenta albo zaproszenie
współpracownika, a najpierw pokaże ci, co
zatwierdzasz: szkic agenta jako sam szkic - gdzie powstanie, jego nazwę, co może
robić i jego instrukcje - a wszystko inne jako dokładne wywołanie. Działa
z twoimi uprawnieniami, więc znajduje i robi to, co ty mógłbyś, i nic więcej. Jego
koszty liczą się jak każdego agenta.

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
może cofnąć draft agenta, który utworzył przez pomyłkę — nic poza tym. Oprócz
akceptacji i pustej organizacji dymek odzywa się, gdy twój run właśnie się nie
udał, i gdy formularz jest otwarty, niedokończony, od minuty.

Dopóki organizacja nie ma modelu, nie potrafi odpowiadać. Otwarty wtedy wypisuje
krótką rozmowę o tym, jak go podpiąć: zdobądź klucz API od dostawcy, otwórz
Architekta w Agent Builderze, w sekcji **Model** wybierz dostawcę i wklej klucz, a
potem wybierz model. Przycisk dostaje tylko ktoś, kto może zmieniać ustawienia
organizacji; pozostali dowiadują się, kto może to zrobić.

Architekt jest agentem jak każdy inny, więc jego nazwę, model, wiedzę i resztę
spec edytuje się w Agent Builderze - może to zrobić ktoś, kto zmienia ustawienia
organizacji, bo uruchamia go każdy w organizacji. Na stronie organizacji jest
karta, która wyłącza go dla wszystkich i ustawia jego powitanie. **Ustawienia →
Asystent** to już tylko twoje własne wskazówki.

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

Wyjątkiem jest Builder, bo zapisuje draft w trakcie pisania. Gdy edytowany agent
zmieni się gdzie indziej, Builder przestaje zapisywać i pobiera nową wersję. Bez
niezapisanych zmian po prostu ją przyjmuje; z niezapisanymi zmianami mówi, kto i
którędy go zmienił, i czeka na twój wybór: **Przeładuj** (ich wersja) albo
**Zachowaj moje zmiany** (twoja, zapisana zamiast ich).

Słyszysz tylko o tym, co możesz odczytać: zmiana agenta, skilla, bazy wiedzy,
pliku kontekstu, strony, klucza albo serwera MCP, których nie widzisz, nigdy nie
trafia do twojej konsoli, a usunięcie trafia tylko do ról, które widzą każdy
wiersz danego rodzaju. Runy trafiają do ról, które czytają historię runów albo
decydują o zatwierdzeniach, boty kanałów do ról, które nimi zarządzają, a twoje
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
delegata, skilla - oraz `/`; znikają, gdy tylko w nie klikniesz.

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

**Oglądanie przeglądania.** Gdy agent z
[przeglądarką](reference/capabilities.md#browser-automation) zaczyna na stronie, jego
przeglądarka rysuje się na żywo pod wiadomością agenta: okno z adresem i stroną taką,
jak widzi ją agent, jedną linijką nad stroną o tym, co robi teraz, i kursorem, który
przesuwa się do tego, co klika albo w co pisze. Okno ma stały kształt i rośnie oraz
maleje razem z rozmową; kilka przeglądań naraz stoi obok siebie, po dwa w rzędzie, gdy
jest miejsce. Przycisk maksymalizacji otwiera jedno na pełnym ekranie, a przywrócenie
odkłada je z powrotem pod wiadomość. Pełna lista kroków, każdy z tym, po co był, jest
pod przyciskiem kroków.

**Przejmowanie przeglądania.** Gdy przeglądanie trwa, **Przejmij** w pasku przeglądarki
zatrzymuje agenta po bieżącym kroku i oddaje ci stronę, w tym samym oknie: klikaj, pisz,
przewijaj, wklejaj. **Oddaj** i agent kontynuuje od miejsca, w którym skończyłeś. Gdy
agent nie przejdzie strony sam - logowanie, captcha - przeglądarka mówi *Agent
cię potrzebuje* i po co. Ktoś, kto może oglądać runy, ale nie edytować agenta, może
patrzeć, ale nie sterować. To samo okno otwiera się na osobnej stronie z linku z kanału.
Zobacz [Przeglądarka](reference/capabilities.md#browser-automation).

**Wskazywanie na stronie.** Przycisk z dymkiem w pasku przeglądarki pozwala kliknąć
miejsce na stronie i dopisać do niego notatkę - *ten przycisk, nie tamten*. **Add to
message** wkłada stronę do Twojej wiadomości jako obrazek z zaznaczonym miejscem, razem
z notatką i adresem strony, do wysłania albo dopisania reszty. Działa też po skończonym
przeglądaniu, na jego ostatnim obrazie.

**Zostajesz zalogowany.** Gdy przeglądanie działa w Twoim imieniu - Twój czat, Twoja
wiadomość prywatna, Twój własny harmonogram - **Oddaj** proponuje *Zapamiętaj moje
logowanie do* strony, na której jesteś. Zaznacz to po zalogowaniu, a kolejne
przeglądania w Twoim imieniu startują tam zalogowane: ciasteczka i dane strony są
zapieczętowane w vault tylko dla Ciebie, nigdy nie są pokazywane i nie są używane dla
odwiedzającego widget, wspólnego kanału, klucza API ani wyzwalacza zdarzeń.
**Ustawienia → Logowania** pokazują zapamiętane strony, a **Zapomnij** sprawia, że
następne przeglądanie zaczyna się wylogowane. **Zaloguj się do strony** otwiera tam
przeglądarkę na dowolnej stronie tylko dla Ciebie, zanim agent będzie jej potrzebował:
zaloguj się, oddaj ją z zaznaczonym polem, a logowanie zostanie zapamiętane tak samo.
Wymaga przeglądarki wdrożenia do logowania
([`BROWSER_SIGN_IN_CDP_URL`](configuration.md)).

## Do czego służy każdy obszar { #what-each-area-is-for }

Sidebar grupuje je. **Build** to Agents, Routines, Apps i Activity;
**Knowledge** to Knowledge bases, Documents, Skills i Context. Dwie grupy są
zwinięte do nagłówka, dopóki ich nie otworzysz, bo ustawia się je raz i odwiedza
rzadko: **Connections** (MCP servers, Channels, Vault, Sandboxes) i
**Organization** (Organizations, Groups). Zwinięta grupa otwiera się sama na
każdej stronie, która do niej należy, i zostaje tak, jak ją zostawisz.

| Obszar | Zawiera | Przeczytaj |
|---|---|---|
| **Agents** | Katalog, Builder, wersje, udostępnianie, testowanie, aktywność | [Twój pierwszy agent](first-agent.md) |
| **Chat** | Rozmowa z opublikowanym agentem | [Powierzchnie](channels.md) |
| **Knowledge** | Kolekcje, dokumenty, źródła synchronizacji, ustawienia ingestii | [Przetwarzanie plików](file-processing.md) |
| **Skills** | Spisane procedury, które agent wczytuje na żądanie | [Skille](skills.md) |
| **Context** | Stała wiedza przypięta do wielu agentów | [Pliki kontekstowe](context.md) |
| **Routines** | Harmonogramy i wyzwalacze zdarzeń | [Wyzwalacze](triggers.md) |
| **Runs** | Co się uruchomiło, ile kosztowało, czego dotknęło, czy zakończyło się błędem | [Nadzór](governance.md#audit) |
| **Documents** | Wszystkie pliki, które agenci trzymają dla ciebie: to, co załączyłeś, i to, co napisali | [Sandbox](sandbox.md#what-the-file-browser-shows-and-what-it-leaves-out) |
| **Sandboxes** | Gdzie agenci uruchamiają kod: hosty, żywe sesje, polityka | [Sandbox](sandbox.md) |
| **MCP servers** | Połączenia z zewnętrznymi narzędziami, osobiste i na całą organizację | [MCP](mcp.md) |
| **Channels** | Boty Slacka, Telegrama i Mattermosta, widgety, hostowane strony | [Powierzchnie](channels.md) |
| **Vault** | Poświadczenia, zapieczętowane per organizacja | [Sekrety](secrets.md) |
| **Organizations** | Członkowie, role, zaproszenia | [Uprawnienia](permissions.md) |
| **Settings** | Providerzy, domyślne ustawienia ingestii, powiadomienia, twój własny profil | [Konfiguracja](configuration.md) |
| **Admin** | Sam deployment: użytkownicy, najemcy, system, ustawienia deploymentu | [Deployment](deployment.md) |

Katalog **Agents** można filtrować po **category** i **tag** — edytowalnych,
lokalnych dla organizacji etykietach pokazywanych na karcie każdego agenta.
Każdy filtr to menu etykiet z agentów, które widzisz; zaznacz kilka, żeby go
poszerzyć.
Kategorie i tagi agenta utrzymujesz na jego stronie szczegółów, obok kontrolek
avatara, a zmiana działa od razu, bez publikowania nowej wersji.

## Języki { #languages }

Konsola mówi po angielsku, polsku i niemiecku, w całości poza stronami
prawnymi, które zostają po angielsku. Pierwsza karta przewodnika proponuje te trzy
języki, a menu konta zmienia język w każdej chwili; wybór jest zapamiętywany w
przeglądarce. Słowa produktu - agent, skill, run, budget, MCP i reszta listy z
[tłumaczenia](howto/translate.md) - zostają angielskie w każdym języku.

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

- Dashboard to **trzydzieści sześć widgetów**, które układasz sam, zapisywanych
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
