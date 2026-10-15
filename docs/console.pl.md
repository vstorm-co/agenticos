---
source_sha: "2943c67ea645"
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

Karty przychodzą pogrupowane w pasy:

| Pas | Odpowiada na |
|---|---|
| *(bez tytułu, na górze)* | Podsumowanie, którego szczegółem jest reszta strony |
| **Deployment** | Tylko dla [admina deploymentu](permissions.md) — sumy platformy, kondycja, najbardziej obciążeni najemcy, oceny |
| **Attention** | Co czeka: [zatwierdzenia](governance.md#approvals), ostatnie błędy, zapas w budżecie, kondycja MCP, nieaktualna wiedza, twoje najnowsze [powiadomienia](#the-bell) |
| **Usage** | Runy, wyniki, powierzchnie, opóźnienia, wydatki, [minuty rozmów](#voice-calls), miks modeli, porównanie wersji |
| **People** | Członkowie, aktywni użytkownicy, oceny, kto co robi |
| **Sandboxes** | [Pojemność, żywe sesje, polityka](sandbox.md) |
| **Workspace** | Twoje: twoje agenty, twoje rozmowy, twoja aktywność, co zostało ci udostępnione |

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

## Chat { #chat }

Miejsce, w którym rozmawiasz z opublikowanym agentem. Selektor wybiera, który
agent odpowiada, a run zachowuje się dokładnie tak, jak zachowałby się w Slacku
albo za API — ten sam budżet, ta sama bramka zatwierdzeń, ten sam ślad audytowy,
bo [każda powierzchnia przechodzi przez jeden runner](channels.md).

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

**Obserwowanie przeglądania.** Agent z
[automatyzacją przeglądarki](reference/capabilities.md#browser-automation-choose)
otwiera panel obok transkryptu, gdy zaczyna przechodzić przez stronę: widok strony na
bieżąco, adres, na którym jest, i każdy krok z prawdopodobieństwem, z jakim silnik go
wybrał. Ta liczba jest powodem, dla którego panel istnieje zamiast spinnera —
przeglądanie, które zadziałało na wyborze 0.31, warto sprawdzić. Panel zostaje po
zakończeniu, bo *zablokowane przez stronę* to odpowiedź o stronie. Zamknij go, a
zostanie zamknięty dla tego przeglądania.

### Dyktowanie { #dictation }

Mikrofon w kompozytorze zamienia mowę na tekst w polu i nigdy go nie wysyła: to,
co powiesz, trafia tam, gdzie był kursor w chwili naciśnięcia mikrofonu, gotowe
do edycji, i nie idzie nigdzie, dopóki nie naciśniesz Wyślij. Sposób
transkrypcji wybiera organizacja, na [karcie Głos (Voice)](#the-voice-card):

- **Wyłączone (Off)** — brak mikrofonu.
- **Przeglądarka (Browser)** — własne rozpoznawanie mowy przeglądarki, więc dźwięk trafia do jej
  producenta (Google, Apple). Firefox go nie ma: jego mikrofon mówi o tym po
  naciśnięciu.
- **Serwer (Server)** — przeglądarka nagrywa, a to wdrożenie wysyła nagranie do providera
  speech-to-text organizacji albo do
  [własnego providera agenta](#an-agents-own-engine), jeśli agent go wskazuje. Działa w każdej przeglądarce, która potrafi nagrywać. Endpoint, jego limity i to, co jest zapisywane, opisuje
  [Dyktowanie w czacie](ml-services.md#dictation-in-chat).

Przy ustawieniu **Serwer** naciśnięcie mikrofonu zastępuje kontrolki paskiem nagrywania:
Anuluj, poziom dźwięku, licznik czasu i Stop. **Enter** zatrzymuje i
transkrybuje, **Escape** anuluje, a nic, co zostanie wpisane albo naciśnięte w
trakcie nagrywania lub transkrypcji, nie jest wysyłane. Nagranie zatrzymuje się
samo na najdłuższym dyktowaniu organizacji i zostaje przetranskrybowane, a
mikrofon odłączony w trakcie kończy je tak samo, zamiast je odrzucić. Gdy
wysyłanie nagrania trwa dłużej niż sekundę, pasek pokazuje, jaka jego część już
poszła; potem pokazuje **Przepisywanie**, dopóki nie przyjdzie tekst.

Wszystko, co dyktowanie ma do powiedzenia, pojawia się w pasku przyczepionym pod
kompozytorem: prośba o uprawnienie, zablokowany albo brakujący mikrofon, ostatnie
30 sekund, pięć sekund bez dźwięku, nagranie krótsze niż sekunda (niewysłane),
nagranie zatrzymane na limicie, liczba wstawionych słów i każda porażka. Liczba
słów znika po kilku sekundach albo przy następnym klawiszu. Nagranie, którego nie
udało się przetranskrybować, jest zachowywane, dopóki nie naciśniesz **Ponów (Retry)**
albo **Odrzuć (Discard)**.

Gdy organizacja
wybrała Server, ale dla wybranego agenta nic się nie rozwiązuje — brak providera
na agencie i w organizacji albo nie wybrano do niego klucza — albo nie wybrano
agenta, mikrofon jest przekreślony i mówi dlaczego; osoba z `org:settings`
dostaje link do karty Głos (Voice), a osoba, która może edytować agenty — link do
karty Głos (Voice) tego agenta.

Poświata pod kompozytorem, gdy mówisz, idzie za ustawieniem **Animacja
dyktowania (Voice glow)** w **Ustawienia → Profil → Wygląd (Settings → Profile →
Appearance)**, obok motywu i ustawienia **Animacje (Motion)**: **Wyrazista
(Vivid)**, **Subtelna (Subtle)** (domyślnie) albo **Wyłączona (Off)**. Jest
zapamiętywana dla każdej przeglądarki. **Animacje** decydują, ile ruchu pokazuje
cała konsola: **Systemowe (System)** (domyślnie) idą za ustawieniem ograniczenia
ruchu w systemie operacyjnym, **Ograniczone (Reduce)** ograniczają ruch bez
niego, a **Pełne (Full)** zachowują ruch niezależnie od systemu operacyjnego. Gdy ruch jest ograniczony, nie ma żadnej poświaty, pasek
pojawia się bez wysuwania, a poziom dźwięku to pięciostopniowy wskaźnik.

### Karta Głos (Voice) { #the-voice-card }

Na stronie **Members** organizacji, dla kogoś z `org:settings`. **Mowa na tekst
(Speech to text)** wybiera silnik — Wyłączone, Przeglądarka albo Serwer (Off,
Browser, Server), każdy z informacją, dokąd idzie dźwięk — a dla Serwera
najdłuższe nagranie, od 10 sekund do 10 minut. **Domyślny provider (Default
provider)**, pod nim, to provider i model z katalogu speech-to-text oraz język
(automatyczne wykrywanie albo jeden ustalony język, co jest dokładniejsze). Jest
pokazywany niezależnie od silnika, bo to także tam
[boty kanałów](channels.md#what-every-channel-shares) ustawione na dziedziczenie
wysyłają swoje wiadomości głosowe; **Brak (None)** go czyści.

**Klucz (Key)**, obok providera, to klucz z vaultu, z którym wysyłane jest
ustawienie domyślne. Lista pokazuje klucze API, których przeznaczeniem jest ten
provider i które widzi cała organizacja — platforma wydaje ten klucz na
dyktowanie każdego członka i na każdego dziedziczącego bota, więc prywatny klucz
członka nie jest oferowany i zostaje odrzucony, jeśli go wysłać. Gdy pasuje
dokładnie jeden klucz, jest wybierany za ciebie, a i tak zapisywany po
identyfikatorze; nic nie wybiera klucza w czasie działania. Provider bez klucza
jest oznaczony **brak klucza dla tego providera**, a wybór linkuje do vaultu, by
go dodać. Gdy zapisano Server, ale nie może działać — model wycofano z katalogu
albo klucz usunięto lub uczyniono prywatnym — karta to mówi i prosi o
**wybranie klucza**, gdy to jego brakuje, bo każdy członek widzi wtedy
przekreślony mikrofon.

Server bez domyślnego providera to ustawienie, a nie usterka: karta zaznacza, że dyktować mogą tylko agenty z własnym providerem. **Rozmowy głosowe (Voice conversations)**, pod nią, zawiera ustawienia rozmów organizacji — zobacz [Rozmowy głosowe](#voice-calls).

Komuś, kto ma także `runs:view`, karta zaczyna się jedną linijką o tym, ile
organizacja przetranskrybowała w ostatnich 30 dniach — „42 min · 118 nagrań (30
bez długości)” — łącznie z dyktowania, wiadomości głosowych z kanałów i API.
**Pokaż podział** rozpisuje to według agenta i według bota kanału. Minuty liczą
tylko nagrania, których długość została podana, więc linijka mówi, ilu jej
brakuje; jest ukryta, dopóki niczego nie przetranskrybowano. Liczby pochodzą z
[`GET /ml/calls/summary`](ml-services.md#what-is-recorded).

### Własny silnik agenta { #an-agents-own-engine }

Zakładka **Build** agenta ma kartę **Głos (Voice)** po ustawieniach modelu, dla agenta,
który ma transkrybować inaczej niż jego organizacja. **Dziedzicz (Inherit)** zachowuje
providera, model i klucz organizacji i pokazuje, które to są; **Wybierz (Choose)**
wybiera parę z katalogu i klucz, z którym jest wysyłana — klucz API dla tego
providera, który widzisz, bo publikacja pożycza go każdemu, kto może uruchomić
agenta.

To nigdy nie jest klucz organizacji: agent z własną parą wskazuje własny
klucz. Język wybiera się osobno: odziedzicz język organizacji albo ustal jeden —
więc polski agent może zachować providera i klucz organizacji. To część speca, zapisywana z wersją
roboczą i działająca, gdy agent zostanie opublikowany, i dotyczy
[dyktowania](#dictation) do tego agenta oraz wiadomości głosowych, które
dziedziczą jego boty kanałów. Resztę opisuje
[kolejność](ml-services.md#which-engine-a-recording-reaches).

Karta mówi, kiedy nadpisanie zmienia mniej, niż się wydaje: gdy silnik
organizacji jest na Off albo Browser, dociera tylko do wiadomości głosowych z
kanałów, a gdy organizacja nie ma providera, to na nim działa dyktowanie do tego
agenta.

### Rozmowy głosowe { #voice-calls }

[Rozmowa głosowa](voice.md) to mówiona rozmowa z opublikowanym agentem: ty
mówisz, on odpowiada na głos, a ty możesz mu przerwać. Konfigurują ją trzy
miejsca w konsoli.

- **Karta Głos (Voice) organizacji**, w sekcji **Rozmowy głosowe (Voice
  conversations)**: **Zezwalaj na rozmowy głosowe (Allow voice conversations)**
  (domyślnie wyłączone), **Oferuj rozmowy w czacie (Offer calls in chat)**,
  **Najdłuższa rozmowa (minuty) (Longest call (minutes))**, od 1 do 50, oraz
  **Miesięczne minuty rozmów (Monthly call minutes)** albo brak miesięcznego
  limitu, by polegać tylko na budżetach. Pierwsze trzy wymagają `org:settings`;
  minuty wymagają `budgets:manage`, a dla wszystkich innych są tylko do odczytu.
  Posiadacz `runs:view` widzi też, ile minut z tego miesiąca zużyły rozmowy.
- **Karta Głos (Voice) agenta**, w sekcji **Rozmowy głosowe (Voice
  conversations)**: **Odbieraj rozmowy głosowe (Take voice calls)**, potem
  provider i model rozmów (dla Azure nazwa wdrożenia i jej model bazowy), klucz,
  głos, język mówiony (albo **Jak osoba dzwoniąca (Follow the caller)**),
  najdłuższa rozmowa i uwagi do głosu. Karta wymienia, czego agent nie może
  używać w rozmowach, mówi, że guardraile nie mogą odfiltrować wypowiedzianych
  słów, zanim zostaną usłyszane, i że rozmowy są zapisywane jako tekst, bez
  przechowywania dźwięku. Działa, gdy agent zostanie opublikowany.
- **Przełącznik Rozmowy głosowe (Voice calls) embeda**, w formularzach widgetu
  i hostowanej strony — zobacz
  [Kanały](channels.md#voice-calls-on-a-widget-or-a-hosted-page).

Zanim zaproponuje rozmowę, konsola pyta, czy ten agent może ją odebrać
(`GET /agents/{id}/voice`), żeby nikt nie udzielał dostępu do mikrofonu tylko
po to, by zostać odrzuconym. Odpowiedź mówi, czego brakuje: rozmowy wyłączone
w organizacji albo w czacie, brak głosu skonfigurowanego u agenta, model, który
nie jest już oferowany, brak klucza albo brak minut w tym miesiącu.

**Przycisk rozmowy** jest w kompozytorze czatu, obok mikrofonu. Gdy rozmowy są
wyłączone w organizacji albo w czacie, w ogóle go nie ma. Gdy ten agent nie może
odebrać rozmowy, przycisk jest przekreślony, a po najechaniu na niego, ustawieniu
na nim fokusu albo kliknięciu wyjaśnia dlaczego - a jeśli możesz skonfigurować
rozmowy, także gdzie to zrobić.

W trakcie rozmowy kompozytor zamienia się w **pasek rozmowy**: co się teraz
dzieje w rozmowie, jej czas na tle limitu rozmowy i minut, które zostały w tym
miesiącu, wykres fali dźwiękowej obu głosów, „naciśnij, aby mówić”, wyciszenie
i **Zakończ (End)**. Z przycisków paska rozmowę kończy tylko Zakończ; rozłącza ją
też otwarcie innej konwersacji albo nowego czatu. Domyślnie mówi się bez użycia
rąk; **naciśnij, aby mówić (push-to-talk)** (przytrzymaj przycisk albo spację)
to wybór zapamiętywany w twojej przeglądarce. Przy ograniczonym ruchu (reduced
motion) zamiast wykresu fali pojawia się schodkowy wskaźnik poziomu.

Rozmowa przechodzi przez stany, które pasek nazywa: łączenie, słuchanie, ty
mówisz, myślenie, agent mówi, przerwano, praca nad narzędziem, oczekiwanie na
twoje zatwierdzenie, zatwierdzenie, którego nie możesz udzielić, czas prawie się
skończył i zakończona — przez ciebie, przez limit, zerwane połączenie albo błąd.

Rozmowa toczy się w konwersacji: napisy pojawiają się słowo po słowie
w wypowiadanej właśnie wiadomości, czytnik ekranu odczytuje każdą linię, gdy
jest już ostateczna, a każda zakończona tura ustępuje miejsca wiadomości
zapisanej w konwersacji, więc rozmowa zostaje potem w twojej historii i możesz
dalej pisać. Gdy agent myśli albo uruchamia narzędzie, konwersacja pokazuje to
tam, gdzie pojawi się jego odpowiedź.

**Zatwierdzenia** są rozstrzygane w rozmowie: karta w konwersacji pokazuje
narzędzie, jego dokładne argumenty i to, co według transkrypcji powiedziałeś,
z 60-sekundowym odliczaniem. Decydują tylko jej przyciski; powiedzenie „tak”
niczego nie zatwierdza. Bez `approvals:decide` karta informuje, że narzędzie
wymaga zatwierdzenia, którego nie możesz udzielić głosem, i proponuje zakończyć
rozmowę i pisać dalej. **Limity** są wypowiadane: minutę przed końcem
najdłuższej rozmowy dostajesz ostrzeżenie, a gdy skończy się czas, budżet albo
minuty miesiąca, agent mówi jedno zdanie i rozmowa się kończy.

Pod paskiem rozmowy **wiersz z komunikatem** wskazuje to, co wymaga twojej
uwagi: prośbę przeglądarki o dostęp do mikrofonu, zatwierdzenie czekające wyżej
(z przyciskiem **Pokaż kartę (Show card)**), ostatnią minutę, limit kończący
rozmowę, ponowne łączenie albo to, jak działa „naciśnij, aby mówić”. Po
zakończeniu rozmowy karta w konwersacji podaje, jak długo trwała i ile tur
zapisano, albo który limit ją zakończył, i ma przycisk **Zadzwoń ponownie (Call
again)**. Gdy rozmowa w ogóle się nie rozpoczęła, pod kompozytorem pojawia się
powód i przycisk **Spróbuj ponownie (Try again)**.

W **Aktywności (Activity)** rozmowa to jeden wiersz z plakietką mikrofonu, a
filtr rodzaju (**Tekst (Text)** albo **Rozmowy głosowe (Voice calls)**) zawęża
listę do rozmów; rozmowa, która połączyła się ponownie, to nadal jeden wiersz,
z czasem i kosztem wszystkich połączeń zsumowanymi. Karta dashboardu **Minuty
rozmów (Voice minutes)**, w pasie Usage dla posiadacza `runs:view`, pokazuje
minuty i liczbę rozmów w okresie, trzech najaktywniejszych agentów i minuty
w tym miesiącu wobec limitu organizacji.

## Do czego służy każdy obszar { #what-each-area-is-for }

| Obszar | Zawiera | Przeczytaj |
|---|---|---|
| **Agents** | Katalog, Builder, wersje, udostępnianie, testowanie, aktywność | [Twój pierwszy agent](first-agent.md) |
| **Chat** | Rozmowa z opublikowanym agentem | [Powierzchnie](channels.md) |
| **Knowledge** | Kolekcje, dokumenty, źródła synchronizacji, ustawienia ingestii | [Przetwarzanie plików](file-processing.md) |
| **Skills** | Spisane procedury, które agent wczytuje na żądanie | [Skille](skills.md) |
| **Context** | Stała wiedza przypięta do wielu agentów | [Pliki kontekstowe](context.md) |
| **Routines** | Harmonogramy i wyzwalacze zdarzeń | [Wyzwalacze](triggers.md) |
| **Runs** | Co się uruchomiło, ile kosztowało, czego dotknęło, czy zakończyło się błędem | [Nadzór](governance.md#audit) |
| **Sandboxes / Workspaces** | Izolowane sesje plików i powłoki, w których pracował agent | [Sandbox](sandbox.md) |
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
- **Slash commands są twoje**, łącznie z wbudowanymi, a te, z których nie
  korzystasz, możesz ukryć.
- Strona pokazująca "nic jeszcze nie ma" może być **nieudanym żądaniem**, a nie
  pustym zasobem.
