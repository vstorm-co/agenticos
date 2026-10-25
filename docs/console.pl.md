---
source_sha: "ebbdbea67616"
---

# Konsola { #the-console }

Konsola to aplikacja webowa, przez którą konfiguruje się wszystko inne opisane na
tej stronie. Ta strona jest mapą: do czego służy każdy obszar i która strona
wyjaśnia go porządnie.

Jeśli szukasz jednego ekranu, najszybszą drogą jest **"?"** w nagłówku strony —
odtwarza on przewodnik po tej stronie, a strona, w której nagłówku nie ma "?",
nie ma przewodnika do odtworzenia. Czat nie ma nagłówka: jego wskazówki są w
ustawieniach czatu, pod suwakami obok mikrofonu.

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
| **Usage & cost** | Których agentów się używa, wydatki, [minuty rozmów](#voice-calls), kiedy dzieje się praca, skąd przychodzą runy, miks modeli, opóźnienia, jakość odpowiedzi, kto z tego korzysta |

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

## Dzwonek { #the-bell }

Obok wyszukiwania, w pasku bocznym: bieżący licznik tego, czego jeszcze nie
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
delegata, skilla - oraz `/`; znikają, gdy tylko w nie klikniesz. Nad nim karty
to własne **pierwsze wiadomości** agenta, ustawiane w Builderze pod jego
instrukcjami; agent bez nich proponuje cztery własne wiadomości czatu, w tym jedną
z pytaniem, co potrafi, i jedną z ustawieniem rutyny.

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

## Do czego służy każdy obszar { #what-each-area-is-for }

Sidebar grupuje je. **Build** to Agents, Routines, Apps i Activity;
**Knowledge** to Knowledge bases, Documents, Skills i Context. Dwie grupy są
zwinięte do nagłówka, dopóki ich nie otworzysz, bo ustawia się je raz i odwiedza
rzadko: **Connections** (MCP servers, Channels, Remote agents, Vault, Sandboxes) i
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

## Języki { #languages }

Konsola mówi po angielsku, polsku i niemiecku, w całości poza stronami
prawnymi, które zostają po angielsku. Pierwsza karta przewodnika proponuje te trzy
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

- Dashboard to **trzydzieści osiem widgetów**, które układasz sam, zapisywanych
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
