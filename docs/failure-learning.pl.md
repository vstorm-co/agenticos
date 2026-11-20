---
source_sha: "d80cae6dae16"
---

# Uczenie się na błędach { #failure-learning }

Agent, który powtarza te same błędy, nie uczy się — tylko je powtarza.
Pętla uczenia się na błędach wydobywa z już wykonanych przebiegów
powtarzające się awarie, porządkuje je w rejestrze i sprawdza poprawkę na
tle starego zachowania, zanim cokolwiek zostanie zastosowane.

Faza 1 obejmuje wydobywanie, rejestr, przypadki ewaluacyjne i próby. Faza 2
dodaje propozycje i stosowanie poprawki: propozycja przechowuje jedną zmianę
tekstu reguły wraz z dowodem ewaluacyjnym, a publikujący stosuje ją w jednej
audytowanej akcji. Faza 3 dodaje strony konsoli, codzienne podsumowanie
i liczniki reguł dla agenta.

## Co wydobywa { #what-it-mines }

Wydobywanie to bieżące zapytania SQL na tabelach `agent_runs` i
`message_ratings` — bez ETL i bez zadania w tle. Domyślnie patrzy wstecz o
siedem dni i wykrywa cztery sygnały:

| Sygnał | Co się liczy | Próg |
|---|---|---|
| Nieudane przebiegi | Przebiegi najwyższego poziomu, nietestowe, pogrupowane według agenta, modelu, statusu i klasy błędu | 3 na agenta |
| Awaria podążająca za modelem | Ta sama klasa błędu dla jednego modelu u różnych agentów | 5 u wszystkich agentów |
| Zawieszone przebiegi | Przebieg wciąż `running`, którego heartbeat jest starszy niż 10 minut | 1 |
| Odpowiedzi ocenione negatywnie | Odpowiedzi asystenta ocenione na −1 | 3 |

Klasa błędu nieudanego przebiegu jest wyliczana ze zdania, które przebieg
zapisał: `ModelHTTPError` zachowuje swój kod statusu, wygasła akceptacja
lub pytanie to osobna klasa, limit użycia to osobna klasa, a zatrzymania
przez strażnik pętli i budżet też są klasami. Wszystko inne to `other`.

Warto znać dwa ograniczenia. Przebieg utknięty w wywołaniu modelu nadal
wysyła heartbeat, więc zawieszenie ze świeżym heartbeatem jest
**niewykrywalne** — „zawieszony" znaczy tylko tyle, że heartbeat jest
nieaktualny. A odpowiedź oceniona negatywnie jest przypisywana do
najbliższego przebiegu rozpoczętego wcześniej w tej samej rozmowie;
wiadomość bez wcześniejszego przebiegu nie ma przypisania i jest pomijana.

## Rejestr { #the-ledger }

Wzorzec warty działania staje się wpisem w rejestrze: tytuł, podsumowanie,
dowody i status — `draft`, `open`, `dismissed` albo `resolved`. Wpis jest
otwarty, gdy ma status `draft` lub `open`, a dla jednego wzorca w danym
zakresie może istnieć tylko jeden otwarty wpis. Egzekwuje to częściowy
indeks unikalny, nie konwencja.

Wpisy mają zakres agenta albo modelu. Wpis modelu to zapis dla całej
organizacji i jest widoczny przy wpisach każdego agenta. Wzorzec z otwartym
wpisem jest oznaczany jako `already_tracked` przy wydobywaniu, więc ta sama
awaria nie jest porządkowana dwukrotnie.

Rozwiązanie wpisu należy do stosowania poprawki: zwykła zmiana statusu na
`resolved` jest odrzucana i tylko zastosowanie propozycji przeciwko wpisowi
go rozwiązuje.

## Przypadki ewaluacyjne { #eval-cases }

Przypadek ewaluacyjny to dowód, który poprawka musi przejść: dane wejściowe
i to, co powinna powiedzieć odpowiedź. Agent może mieć co najwyżej 50
przypadków. Przypadek określa oczekiwanie — `equals`, `contains` albo
`not_contains` dla tekstu odpowiedzi lub statusu przebiegu — i może
wskazywać wpis rejestru, z którego pochodzi, źródłowy przebieg pokazujący
awarię oraz profil modelu, pod którym ma być wypróbowany.

## Wypróbowywanie poprawki { #trying-a-fix }

Próba uruchamia każdy przypadek dwukrotnie na próbkę: raz na bieżącej
opublikowanej specyfikacji (strona stara) i raz na tej samej specyfikacji z
podmienionymi instrukcjami (strona nowa). Każdy przebieg otwiera świeżą
rozmowę testową, działa jako przebieg testowy i jest wykluczany z
wydobywania przez filtr `is_test`. Liczba próbek domyślnie wynosi 1,
maksymalnie 5.

Brama jest surowa. Strona przechodzi tylko wtedy, gdy jej przebieg się
ukończył **i** oczekiwanie zostało spełnione — przebieg, który się wysypał,
nie może przejść przez wysypanie się. Przypadek przechodzi tylko wtedy, gdy
strona stara zawodzi, a strona nowa przechodzi, większością próbek, gdy jest
ich więcej niż jedna. Próba przechodzi tylko wtedy, gdy przechodzą wszystkie
przypadki. Gdy strona stara już przechodzi, przypadek jest zgłaszany jako
nieodtwarzalny: „case does not reproduce - the old text already passes".

Werdykty są oceniane w momencie odczytu próby, nigdy nie są przechowywane.
Przebieg, który wciąż trwa, pozostawia swój przypadek jako oczekujący.

Próba może wskazywać roboczą propozycję zamiast nadpisania instrukcji:
uruchamia jej nowy tekst instrukcji albo treść skilla, więc stanowi dowód dla
dokładnie tej propozycji. Zapisuje identyfikator propozycji i sumę SHA-256
sprawdzonej treści; zastosowanie jest odrzucane, jeśli powiązana zaliczona
próba nie dotyczy tej propozycji i tej sumy.

Próba działa synchronicznie w żądaniu i jest ograniczona do dziesięciu runów
agenta (dwie strony na przypadek i próbkę). Każdy run może wysłać wiele żądań
do dostawcy, więc nie jest to limit żądań do dostawcy. Większe żądania są
odrzucane przed rozpoczęciem runów. Wykonywanie w tle pozostaje osobnym,
przyszłym zadaniem.

## Propozycje { #proposals }

Propozycja to jedna zmiana tekstu reguły: tekst, który zastępuje, tekst,
który go zastępuje, dlaczego oraz próba ewaluacyjna, która ją potwierdza.
Wskazuje swój cel — instrukcje agenta albo jeden skill — oraz wpis rejestru,
z którego pochodzi, jeśli taki jest. Propozycja ma status `draft`, dopóki nie
zostanie zastosowana lub odrzucona; zastosowanie jest zatwierdzeniem i nie ma
osobnego kroku zatwierdzania.

Propozycja dotycząca instrukcji jest pisana względem bieżącej opublikowanej
wersji agenta, chyba że treść wskazuje inną. Propozycja dotycząca skilla
jest pisana względem treści skilla w obecnej postaci i zapisuje jej sumę
kontrolną SHA-256 jako bazę. Lista zastosowanych zmian to lista propozycji
odfiltrowana do `status=applied`: każdy wpis zawiera wersję, którą
opublikował, oraz próbę, która go potwierdziła.

Propozycje dotyczące skilli również wymagają zaliczonej próby
ewaluacyjnej. Proponowana treść skilla działa jako nadpisanie w pamięci po
stronie testowej; zapisany skill pozostaje bez zmian.

## Stosowanie propozycji { #applying-a-proposal }

Zastosowanie jest ludzkim działaniem publikującego, w transakcji żądania, i
jest audytowane. Dla celu dotyczącego instrukcji zastosowanie odmawia,
chyba że powiązana próba istnieje i przeszła bramę, oceniona tak, jak stoją
jej przebiegi w tej chwili — próba brakująca, oczekująca albo nieudana nie
może zostać zastosowana. To jest brama, sprawdzana w momencie zastosowania,
a nie przechowywana.

Dwa zabezpieczenia chronią publikację. Optymistyczna współbieżność odmawia
z kodem 409, chyba że bieżąca wersja agenta wciąż jest wersją, względem
której napisano propozycję — ktoś opublikował od tego czasu, więc autor
propozycji pisze ją na nowo względem nowej wersji, zamiast nadpisywać
nowszą publikację. Strażnik wersji roboczej odmawia z kodem 409, jeśli agent
ma nieopublikowane zmiany w wersji roboczej — trwająca praca budowniczego
musi najpierw zostać opublikowana albo odrzucona, ponieważ zastosowanie
nadpisuje wersję roboczą.

Po przejściu zabezpieczeń zastosowanie wczytuje specyfikację roboczą,
ustawia jej instrukcje na nowy tekst propozycji, zapisuje wersję roboczą
i publikuje ją, odnotowując identyfikator propozycji. Opublikowana wersja
to zamrożony nowy tekst, a propozycja zapisuje ją jako uchwyt wycofania.
Powiązany wpis rejestru, jeśli istnieje, jest oznaczany jako rozwiązany, a
wpis audytu zapisuje propozycję, wersję, próbę i wersję bazową.

Zastosowanie skilla wymaga zaliczonej powiązanej próby i zapisuje dokładną
sumę kontrolną nowej treści. Odmawia z kodem 409, jeśli bieżąca treść skilla
nie odpowiada już bazowej sumie propozycji. Przed edycją poprzednia treść jest
zapisywana w propozycji. Jednorazowy endpoint przywracania odtwarza tę kopię
tylko wtedy, gdy skill nadal ma zastosowaną sumę; zapisuje osobę przywracającą
i wpis audytu, a późniejszych zmian nigdy nie nadpisuje.

Cofnięcie zastosowania instrukcji to istniejące wycofanie: opublikuj nową
wersję skopiowaną z wersji bazowej zapisanej przez propozycję. Nie ma do
tego osobnego endpointu pętli. Odrzucenie jest zapisywane w śladzie audytu
wraz z powodem — sam wiersz propozycji nie zawiera notatki o decyzji.

## Konsola { #the-console }

Pętla mieszka w konsoli, na stronie agenta i na jednej stronie dla całej
organizacji. Strona agenta ma kartę Uczenie się na błędach; strona dla
całej organizacji wymienia wzorce wszystkich agentów w jednym miejscu, w
nawigacji pod Monitorowanie. Odczyt wymaga `agents:view`; porządkowanie
wymaga `agents:edit`, stosowanie propozycji instrukcji wymaga
`agents:publish`, a stosowanie propozycji skilla wymaga `skills:edit`
dla tego skilla.

### Wzorce { #patterns }

Panel wzorców wymienia to, co wydobyto z ostatnich siedmiu dni, wraz z
liczbą i z tym, czy wzorzec jest już śledzony. Zastrzeżenia wydobywania
są pokazane obok liczb, nie ukryte: wzorce dla modelu są przybliżone,
zawieszenie ze świeżym pulsem jest niewykrywalne, a odpowiedź oceniona
negatywnie jest przypisywana tylko w przybliżeniu. Śledzenie wzorca z
panelu otwiera formularz rejestru z wypełnionym wzorcem.

### Wpisy rejestru { #ledger-entries }

Rejestr wymienia wpisy z filtrem statusu, a wybranie wpisu pokazuje jego
przypadki ewaluacyjne i propozycje. Zaakceptowanie wersji roboczej ją
otwiera; odrzucenie prosi o powód, a powód zostaje przy wpisie, żeby
zapis przetrwał. Usunięcie wpisu go usuwa — jego przypadki ewaluacyjne
zachowują to, co mówiły, i odnotowują wpis jako usunięty.

### Przypadki ewaluacyjne i próby { #eval-cases-and-tries }

Panel przypadków wymienia każdy przypadek wraz z werdyktem jego
najnowszej próby. Przypadek powstaje z przebiegu, który pokazał awarię:
podaj id przebiegu źródłowego i wczytaj jego ostatnią wiadomość
użytkownika, wraz z wcześniejszymi turami jako historią, potem skróć
wiadomość do wadliwej części i napisz, co powinna mówić odpowiedź.
Próba przebiega po zaznaczonych przypadkach, z liczbą próbek i albo
nowym tekstem roboczej propozycji, albo wpisanym nadpisaniem — nigdy
jednym i drugim. Żądania wymagające więcej niż dziesięciu runów agenta są
odrzucane przed uruchomieniem. Próba, która przeszła bramę,
proponuje swój tekst jako propozycję, wstępnie wypełnioną tą próbą jako
dowodem.

### Przegląd propozycji { #proposal-review }

Wybranie propozycji pokazuje zmianę jako porównanie, dowód ewaluacyjny
wraz z werdyktami bramy dla każdego przypadku oraz akcje zastosowania i
odrzucenia. Propozycja instrukcji stosuje się dopiero, gdy jej próba
przeszła bramę, a kontrolkę zastosowania widzi tylko posiadacz
`agents:publish`. Propozycja skilla również wymaga zaliczonej próby dla
jej dokładnej treści. Przywrócenie odtwarza zapisany poprzedni skill, o ile
nikt go od zastosowania nie zmienił. Zastosowana propozycja zapisuje
opublikowaną wersję i wskazówkę wycofania: wróć do zapisanej wersji bazowej.

### Ile reguł działa { #how-many-rules-are-live }

Góra karty liczy reguły, które pętla wprowadziła do tego agenta:
zastosowane propozycje, otwarte wpisy i rozwiązane wpisy, jako trzy
osobne liczby. Zastosowane propozycje to reguły działające teraz w
instrukcjach. Otwarte wpisy to reguły, nad którymi wciąż się pracuje —
wpis jest otwarty, gdy jest wersją roboczą albo otwarty. Rozwiązany wpis
jest swoją zastosowaną propozycją, więc obie liczby liczy się osobno,
nigdy nie dodaje: dodanie ich policzyłoby jedną regułę dwa razy.

Ta liczba to zachęta, nie werdykt. Reguły się gromadzą — każda
zastosowana propozycja to zdanie, którego agent musi przestrzegać obok
wszystkich pozostałych — więc raz na kwartał przeglądaj działające
reguły: przeczytaj listę zastosowanych zmian i wycofaj te, których agent
już nie potrzebuje, edytując instrukcje, zamiast zostawiać je, żeby
zostały wyuczone na nowo.

## Codzienne podsumowanie { #the-daily-digest }

Raz dziennie zaplanowane zadanie — `failure-ledger-digest` — wydobywa z
ostatnich siedmiu dni wzorce dla każdej organizacji i zapisuje każdy nowy
wzorzec jako roboczy wpis rejestru, a potem wysyła jedno podsumowanie dla
każdej organizacji, która ma coś nowego, na skonfigurowany adres
odbiorcy. Organizacja, która nie ma nic nowego, nie dostaje maila. Wpisy
są robocze, nigdy otwarte: wersja robocza to wzorzec znaleziony przez
wydobywanie, nie taki, który zaakceptował kurator.

Odbiorca to konfiguracja, nie wartość domyślna. Ustaw
`FAILURE_LEARNING_DIGEST_RECIPIENT` na adres, na który mają trafiać
podsumowania; póki jest pusty, zadanie zapisuje w logu brak działania i nie tworzy
roboczych wpisów ani nie wysyła maili. To jeden adres dla całego wdrożenia, więc
widzi podsumowania każdej organizacji: niech to będzie adres operatora,
nie członka. Zobacz [odniesienie do ustawień](configuration.md#email-smtp).

## Uprawnienia { #permissions }

| Trasa | Uprawnienie |
|---|---|
| `GET /v1/failure-learning/patterns` | `runs:view` |
| Odczyty wzorców, rejestru i ewaluacji dla agenta | `agents:view` |
| Zapisy rejestru, przypadków i prób dla agenta | `agents:edit` |
| Proponowanie zmiany, odrzucanie propozycji | `agents:edit` (instrukcje) / `skills:edit` (cel dotyczący skilla) |
| Stosowanie propozycji dotyczącej instrukcji | `agents:publish` |
| Stosowanie propozycji dotyczącej skilla | `skills:edit` dla skilla |

Tylko lista wzorców dla całej organizacji ma bramkę na trasie. Trasy dla
agenta rozstrzygają dostęp do agenta wewnątrz serwisu, a odmowa wygląda
jak brak zasobu — więc przeglądający z jawnym uprawnieniem do jednego
agenta nie jest odrzucany przed sprawdzeniem uprawnienia.

## API { #api }

| Metoda | Ścieżka | Opis |
|---|---|---|
| `GET` | `/v1/failure-learning/patterns` | Wzorce dla całej organizacji |
| `GET` | `/v1/agents/{agent_id}/failure-learning/patterns` | Wzorce jednego agenta |
| `GET` | `/v1/agents/{agent_id}/failure-learning/ledger` | Lista wpisów rejestru |
| `POST` | `/v1/agents/{agent_id}/failure-learning/ledger` | Porządkowanie wzorca |
| `GET` | `/v1/agents/{agent_id}/failure-learning/ledger/{entry_id}` | Jeden wpis |
| `PATCH` | `/v1/agents/{agent_id}/failure-learning/ledger/{entry_id}` | Akceptacja, odrzucenie, przepisanie |
| `DELETE` | `/v1/agents/{agent_id}/failure-learning/ledger/{entry_id}` | Usunięcie wpisu |
| `GET` | `/v1/agents/{agent_id}/failure-learning/eval-cases` | Lista przypadków ewaluacyjnych |
| `POST` | `/v1/agents/{agent_id}/failure-learning/eval-cases` | Dodanie przypadku |
| `DELETE` | `/v1/agents/{agent_id}/failure-learning/eval-cases/{case_id}` | Usunięcie przypadku |
| `POST` | `/v1/agents/{agent_id}/failure-learning/eval-runs` | Rozpoczęcie próby |
| `GET` | `/v1/agents/{agent_id}/failure-learning/eval-runs/{try_id}` | Odczyt próby, ocenionej na bieżąco |
| `POST` | `/v1/agents/{agent_id}/failure-learning/proposals` | Zaproponowanie zmiany |
| `GET` | `/v1/agents/{agent_id}/failure-learning/proposals` | Lista propozycji; `status=applied` to lista zastosowanych zmian |
| `GET` | `/v1/agents/{agent_id}/failure-learning/proposals/{proposal_id}` | Jedna propozycja, z dowodem ewaluacyjnym |
| `POST` | `/v1/agents/{agent_id}/failure-learning/proposals/{proposal_id}/apply` | Zastosowanie propozycji, audytowane |
| `POST` | `/v1/agents/{agent_id}/failure-learning/proposals/{proposal_id}/reject` | Odrzucenie propozycji, z powodem |

Rozpoczęcie próby jest limitowane na powierzchni `agent_eval_run`, a każde
uruchomienie po stronie liczy się do budżetu wywołującego jak każdy przebieg.
Próba wskazująca `proposal_id` uruchamia nowy tekst tej propozycji;
wskazanie zarówno propozycji, jak i nadpisania jest odrzucane.

## Często zadawane pytania { #frequently-asked-questions }

### Dlaczego awaria, którą widzę, nie pojawia się jako wzorzec? { #why-does-a-failure-i-can-see-not-appear-as-a-pattern }

Jest poniżej progu, poza siedmiodniowym oknem, przebiegiem testowym albo
przebiegiem delegowanym. Delegacje są liczone wewnątrz rodzica, a przebiegi
testowe to własne próby pętli — wydobywanie każdego z nich oznaczałoby
uczenie się od samego siebie.

### Dlaczego moja próba trwała tak długo? { #why-did-my-try-take-so-long }

Próby działają synchronicznie: każdy przypadek jest uruchamiany dwa razy
na próbkę, jeden run agenta po drugim, wewnątrz żądania. Próba może rozpocząć
najwyżej dziesięć runów agenta; każdy z nich może wysłać wiele żądań do dostawcy.

### Czy próba może zmienić to, co mówi mój agent? { #can-a-try-change-what-my-agent-says }

Nie. Obie strony działają jako przebiegi testowe na zamrożonej kopii
specyfikacji. Opublikowany agent pozostaje nietknięty do czasu zastosowania
propozycji.

### Co jeśli agent został opublikowany ponownie, odkąd zaproponowałem zmianę? { #what-if-the-agent-was-republished-since-i-proposed }

Zastosowanie odmawia z kodem 409. Napisz propozycję na nowo względem nowej
wersji — względem tego, co agent publikuje teraz — zamiast nadpisywać nowszą
publikację.

### Jak cofnąć zastosowanie? { #how-do-i-undo-an-apply }

Wróć do wersji bazowej zapisanej w propozycji: istniejące wycofanie publikuje
nową wersję skopiowaną z niej, więc oś czasu pokazuje, że wycofanie nastąpiło.
Zastosowanie skilla można raz cofnąć z zapisanej kopii, jeśli skill nadal
ma zastosowaną treść.

### Co się dzieje, gdy zastosuję zmianę skilla? { #what-happens-when-i-apply-a-skill-change }

Każdy agent powiązany ze skillem uruchamia nową treść przy następnym
przebiegu. Propozycja wymaga zaliczonej próby dla dokładnie tej treści i
można ją raz przywrócić, jeśli nikt nie zmienił skilla od zastosowania.

### Gdzie widzę nowe wzorce każdego dnia? { #where-do-i-see-the-new-patterns-each-day }

W skrzynce odbiorczej, jeśli wdrożenie skonfigurowało odbiorcę podsumowania —
jeden mail dla organizacji, która ma coś nowego. Brak odbiorcy lub nowych
wzorców oznacza zapisany w logu brak działania. Wzorce są też na stronie
dla całej organizacji, która wymienia wzorce wszystkich agentów w jednym miejscu.
