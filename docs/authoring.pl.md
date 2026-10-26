---
source_sha: "fdd553b39bfe"
title: "Asystent tworzenia"
description: "Asystent tworzenia czyta, co ludzie ocenili negatywnie i jak kończyły się runy, i sugeruje zmiany w instrukcjach agenta, jego narzędziach, konfiguracji, skillach i plikach kontekstowych. O każdej decyduje człowiek."
---

# Asystent tworzenia { #authoring-assistant }

**Asystent tworzenia** ulepsza agentów na podstawie dowodów. Czyta, co ludzie
ocenili negatywnie i jak kończyły się runy, i sugeruje zmiany w instrukcjach
agenta, w nazwach i opisach jego narzędzi, w jego
[konfiguracji](#configuration) oraz w skillach i plikach kontekstowych, których
używa. Nigdy niczego nie zmienia sam: każda sugestia czeka na człowieka, przyjęta trafia do
[wersji roboczej](concepts.md), a nic nie dociera do nikogo, dopóki wersja
robocza nie zostanie opublikowana.

Robi trzy rzeczy:

- **Ulepsza** agenta: sugeruje zmiany na podstawie jego negatywnie ocenionych i
  nieudanych runów.
- **Sprawdza** Twoje zmiany: porównuje wersję roboczą z wersją, na której się
  opiera - najnowszą opublikowaną - na tych samych dowodach i mówi, co zmiany
  poprawiają, czym ryzykują i co usunęły.
- **Ulepsza skill** albo **plik kontekstowy**: sugeruje nową treść na podstawie
  runów, które go czytały.

Asystent jest osobnym [agentem systemowym](datasets.md#judge), widocznym razem z
pozostałymi agentami systemowymi organizacji. Jego instrukcje można edytować jak
instrukcje każdego agenta, a jego runy są zwykłymi runami: objęte budżetem,
wycenione i widoczne w **Aktywności** (Activity).

Rozwiń **Asystent poprawiania** podczas poprawiania lub weryfikacji, aby
wybrać opublikowanego asystenta. Zmiana usuwa poprzedni szacunek, więc zgoda
dotyczy ceny i budżetu wybranego asystenta. Zadanie zachowuje `improver_agent_id`;
sesja poprawiania w tle przyjmuje ten sam wybór. Worker ponownie sprawdza rodzaj,
publikację i aktualne uprawnienia użytkownika. Usunięty wybór powoduje odmowę,
zamiast powrotu do domyślnego agenta.

## Co czyta { #what-it-reads }

Asystent nie ma narzędzi. To, co czyta, jest dla niego zebrane z runów agenta z
ostatnich 30 dni:

- odpowiedzi ocenione negatywnie, najpierw te z komentarzami;
- runy, które się nie udały, wyczerpały budżet albo zostały zablokowane przez
  guardrail;
- odpowiedzi ocenione pozytywnie, jako kontrast.

Udany run bez oceny nie mówi niczego i nie jest czytany. Nie jest też czytany
test z panelu testowego Buildera ani run delegata.

**Uczy się wyłącznie na przypadkach treningowych.** Oprócz ocenionych rozmów asystent czyta błędne odpowiedzi treningowe, potwierdzone regresje, uzasadnienia sędziego i notatki przeglądu z dostępnych [datasetów](datasets.md). Dostaje skuteczność treningu według tagów i kryteriów sędziego oraz liczby napraw i regresji. Pytania kontrolne, odpowiedzi i oceny nigdy nie trafiają do jego promptu. Runy sędziego i samego asystenta nadal są pomijane.

Gdy do przeczytania jest więcej, niż mieści jedno zapytanie, runy są najpierw
czytane grupami, a sugestie powstają z tego, co pokazała każda grupa.

### Każdy cytat jest sprawdzany { #every-quote-is-checked }

Każda sugestia ma uzasadnienie i dowody: runy, na których się opiera, i cytaty z
nich. Zanim ktokolwiek zobaczy sugestię, każdy cytat jest sprawdzany słowo w
słowo z runem, który wskazuje. Cytat, którego tam nie ma, run spoza tych, które
asystent przeczytał, oraz wszystko ponad dwanaście pozycji albo sześćset znaków
jest odrzucane, a sugestia podaje, ile tego było. Czytelnik bez `runs:view`
widzi, na których runach opiera się sugestia, ale nie to, co w nich powiedziano.

Sprawdzenie dowodzi, że cytat jest w swoim runie, a nie że dotyczy tego, co
popiera: prawdziwy cytat o czymś innym je przechodzi. Dlatego ustalenie Sprawdź
wskazuje linię edycji, której dotyczy, a ta linia musi być częścią edycji. Pasek
pokazuje ją nad cytatami ustalenia, żeby czytelnik ocenił, czy go popierają.
Ustalenie, że edycja ma poparcie, któremu nie został żaden cytat do sprawdzenia,
nie jest pokazywane.

Gdy żądanie poprawy kończy się przy otwartym Builderze, dialog wyniku pokazuje liczbę przejrzanych odpowiedzi, zaproponowane i zapisane zmiany oraz odrzucone propozycje z powodami. Można otworzyć go ponownie przyciskiem **Zobacz wynik**. Zmiany pokazują tekst przed poprawą i po niej obok siebie, z uzasadnieniem i linkami do materiału źródłowego. Pusty wynik informuje, że niczego nie można zastosować, bez oczekiwanego efektu. Opis efektu zawierający surowe identyfikatory runów jest zastępowany opisem z liczbą podlinkowanych odpowiedzi źródłowych.

Po zakończeniu sprawdzenia osoby z `runs:view` mogą porównać odpowiedzi obu stron w dialogu i otworzyć pełne sprawdzenie. Wcześniej dialog proponuje jego uruchomienie. Agent bez ocenionych rozmów ani materiału treningowego ma nad instrukcjami zwięzły wiersz asystenta.

## Sugestie { #suggestions }

Ulepsz i Sprawdź otwierają **pasek asystenta** na zakładce **Budowa** (Build)
agenta. Każda
sugestia pokazuje zmieniany fragment w jego otoczeniu, powód i dowody, a o
każdej decyduje się osobno:

| Akcja | Co się dzieje |
|---|---|
| **Przyjmij** | Zmiana trafia do wersji roboczej. Nic nie jest publikowane. |
| **Edytuj** | Zamiast sugestii przyjmowane jest Twoje sformułowanie. |
| **Odrzuć** | Zapisane; późniejsze zlecenie nie zasugeruje tego ponownie. |
| **Cofnij** | Odwraca decyzję, dopóki pasuje ona do wersji roboczej. |

Sugestia jest zakotwiczona w miejscu, w którym był jej fragment, i w tym, co go
otaczało, a nie w samym tekście, więc linia, która występuje dwa razy, jest
zmieniana tam, gdzie miała być. Jeśli wersja robocza poszła dalej - fragment
został usunięty albo opis narzędzia zmieniony ręcznie - sugestia mówi, że **nie
pasuje już do wersji roboczej**, i można ją tylko odrzucić. Cofnij odmawia tak samo, gdy
przyjęty tekst został potem zmieniony ręcznie: wyrzuciłoby to tę zmianę.

Nowsze Ulepsz zastępuje oczekujące sugestie; Sprawdź dodaje do nich swoje.
Opublikowanie wersji roboczej je zamyka: decyzje stają się ostateczne, a pasek zachowuje
je jako zapis.

Zmiana zaproponowana przez asystenta, której nie da się zapisać, nie znika po
cichu. Pasek wymienia ją pod **proponowane zmiany nie zostały zapisane**, z
powodem: fragmentu, który zmienia, nie ma w instrukcjach albo występuje więcej
niż raz, agent nie ma takiego narzędzia, tego ustawienia asystent nie może
zmieniać. Worker loguje te same powody. Fragment skopiowany z wyprostowanymi
cudzysłowami, bez backticków albo ze złączonymi liniami nadal trafia na tekst
wersji roboczej.

### Sprawdź w ewaluacji { #check-with-evals }

**Sprawdź w ewaluacji** (Check with evals) uruchamia [dataset](datasets.md) na
bazie wersji roboczej - najnowszej opublikowanej wersji - z naniesionymi
wszystkimi oczekującymi sugestiami, obok tej wersji w tym samym
[runie ewaluacji](evals.md#a-baseline-in-the-same-run). Strażnik może trzymać
produkcję na starszej wersji; sprawdzenie nigdy nie mierzy względem niej, więc
to, co zmieniła najnowsza wersja, jest po obu stronach i nigdy nie jest
przypisywane sugestii. Gdy wersja robocza odeszła od swojej bazy - Twoimi
własnymi zmianami albo wcześniej przyjętymi sugestiami - baseline'em jest sama
wersja robocza, uruchomiona na nowo, a nie wzięta z wcześniejszego runu, więc
sugestie są jedyną różnicą; wycena kosztu obejmuje też tę stronę. Strony są
nazwane tym, czym są, w dialogu i na runie: „v2 + 1 sugestia” wobec „v2” albo
„Wersja robocza + 2 sugestie” wobec „Wersja robocza”. Sprawdzenie niczego nie
przyjmuje i nie zmienia wersji roboczej. Dopóki któraś oczekująca sugestia nie
pasuje już do wersji roboczej albo koliduje z inną, sprawdzenia nie da się
uruchomić, dopóki nie zostanie przyjęta lub odrzucona: run mierzy dokładnie to,
co czeka.

Zamiast datasetu sprawdzenie może uruchomić jedną z [suit](evals.md#suites)
agenta: jej dataset, w jej środowisku. Run porównuje obie strony tak jak każde
sprawdzenie, a gdy się zakończy, mówi też, jak oceniłaby go suita: zaliczona,
niezaliczona albo bez rozstrzygnięcia, i dlaczego, według progu, jaki suita
miała w chwili startu sprawdzenia. Widać to na runie i przy sprawdzeniu w pasku,
w tym samym brzmieniu co wyniki suity.

Pasek opisuje każde zakończone sprawdzenie jednym zdaniem z linkiem do jego
runu - „audit-smoke: nie przeszłoby - psuje »Do you ship to Canada?«” albo to,
co zepsuło i naprawiło na datasecie.

Sprawdzenie nie jest runem suity: nie trafia do żadnej historii suity, nikogo
nie powiadamia, a Przyjmij kieruje się werdyktem samego runu. Zmiana skilla albo
pliku kontekstu sprawdzana na suicie agenta, na którym działa, dostaje to samo.

Każdy przypadek ma stałe przypisanie do treningu albo kontroli, zachowane między wersjami datasetu. Ustawienia datasetu wybierają udział kontroli tylko dla przyszłych przypadków (domyślnie 50%). Sprawdzenia sugestii i sesje poprawy mierzą wyłącznie przypadki kontrolne i wymagają co najmniej pięciu pytań z możliwością oceny. Kopie pytań treningowych lub materiału źródłowego są wykluczane według znormalizowanej treści i identyfikatora runu, także po ręcznym wpisaniu lub wygenerowaniu. Poniżej minimum sesja zatrzymuje się z `no_data` i podaje liczbę brakujących pytań. Widok runu oznacza obie części i wykluczone kopie. Zwykłe suity i bramki promocji nadal liczą wszystkie przypadki.

Sesja poprawy przypina wersję datasetu i identyfikatory rozmów źródłowych. Kolejne rundy mogą uczyć się na wynikach treningowych tej wersji, ale nowe rozmowy i przypadki nie zmieniają próby kontrolnej.

Sprawdzenie liczy się jako test wersji roboczej, gdy wersja robocza jest
dokładnie tym, co sprawdzało - każda sprawdzona sugestia przyjęta i nic poza tym
nie zmienione - więc dialog publikacji podaje jego werdykt; po kolejnej zmianie
mówi, że ten test jest nieaktualny. Sprawdzenie mierzone względem samej wersji
roboczej nigdy się nie liczy: nie mówi nic o wersji roboczej względem
opublikowanej wersji, którą by zastąpiła. Sprawdzenie samo z siebie nie wysyła
niczego do [kolejki przeglądu](datasets.md#review) datasetu, bo nic nie zostało
przyjęte; strona jego runu mówi o tym obok **Wyślij niezaliczone przypadki do
przeglądu** (Send failed cases to review).

Każda sugestia podaje oczekiwany efekt. Pasek pokazuje go obok runów ewaluacji, które
sprawdzały sugestie, więc możesz porównać przewidywanie z tym, co wykazały runy.

## Konfiguracja { #configuration }

Poza tekstem asystent może zasugerować zmianę w kilku częściach konfiguracji
agenta. Każda jest sugestią jak każda inna, decydowaną osobno w pasku, i
pokazaną z nazwy: modelu, bazy wiedzy, pliku kontekstowego, capability albo
serwera MCP, do którego się odnosi, nigdy przez identyfikator.

| Część | Co może zrobić sugestia |
|---|---|
| Opis | Ustawić go |
| Model | Zmienić profil modelu |
| Ustawienia modelu | Ustawić temperaturę, top-p, maksymalną liczbę tokenów, timeout albo równoległe wywołania narzędzi |
| Limit kroków | Ustawić `max_steps` |
| Capabilities | Dodać albo usunąć jedną albo zmienić jej ustawienia - tylko tam, gdzie ustawienia dotyczą wyłącznie jakości, na przykład ile wiedzy pobrać albo kiedy kompaktować; ustawienia, które sięgają do URL-a, domeny, połączenia, dostawcy albo danych osobowych, nigdy się nie zmieniają, a Subagents nigdy nie są dodawane ani przekonfigurowywane. Zabezpieczenie - Guardrails - można tylko dodać: nigdy usunąć ani zmienić jego ustawień, niezależnie od tego, jak nazywa je sugestia |
| Zatwierdzanie | Sprawić, że capability albo jedno z jej narzędzi najpierw pyta |
| Specjaliści | Przepisać opis wbudowanego [specjalisty](reference/capabilities.md#delegation) |
| Bazy wiedzy | Podpiąć albo odpiąć jedną |
| Pliki kontekstowe | Podpiąć albo odpiąć jeden |
| Narzędzia MCP | Zmienić, które narzędzia podpiętego serwera agent może wywołać |

Nic poza tym nie jest sugestią: suity ewaluacji i ich progi, datasety, budgety,
obserwowalność i przypięty delegat nigdy nie są zmieniane przez asystenta.
**Edytuj** działa na pojedynczej wartości albo tekście - ustawieniu, limicie
kroków, opisie; wszystko inne przyjmuje się albo odrzuca tak, jak zasugerowano.

### Poszerzanie dostępu { #widening-access }

Asystent może zasugerować, by agent sięgał do większej liczby rzeczy: capability,
bazy wiedzy, pliku kontekstowego, kolejnych narzędzi MCP. Taka sugestia jest
oznaczona **Dodaje dostęp** i wymienia każdą rzecz, którą dodaje. Nigdy nie
poszerza tego, co działa bez udziału człowieka:

- Capability, którą dodaje, przychodzi z każdym swoim narzędziem, które coś
  zmienia, ustawionym na pytanie o zatwierdzenie, niezależnie od tego, na co
  ustawiła je sama sugestia.
- Dopuszczenie większej liczby narzędzi serwera MCP sprawia, że powiązanie, które
  o nic nie pytało, pyta o zatwierdzenie narzędzi zapisujących. **Cofnij**
  przywraca poprzednie narzędzia i zostawia je pytające: ponowne obniżenie
  zatwierdzania to decyzja człowieka. W przypadku serwera, do którego każdy
  sięga przez własne konto, narzędzie, którego opisu asystent nie widzi, liczy
  się jako zapisujące.
- Zatwierdzanie tylko się zaostrza: sugestia może sprawić, że capability albo
  narzędzie najpierw pyta, nigdy że przestaje pytać.

Sugestię, która podpina bazę wiedzy, plik kontekstowy, profil modelu albo serwer
MCP, albo pozwala agentowi wywołać więcej narzędzi MCP, przyjmie tylko ktoś, kto
mógłby wprowadzić tę zmianę ręcznie: przyjęcie jej przez kogokolwiek innego jest
odrzucane, tak jak odrzuciłby je Builder.

### Zmiana modelu { #a-change-of-model }

Sugestia zmiany modelu mówi, ile kosztowałby jeden run na każdym z modeli,
wycenione na podstawie ostatnich runów agenta. Gdy wycena opiera się na mniej
niż pięciu, mówi, że to przybliżone oszacowanie, i z ilu runów.

Zmianę modelu przyjmuje się dopiero, gdy się opłaciła. **Przyjmij** pozostaje
wyłączone i mówi dlaczego, dopóki [sprawdzenie w ewaluacji](#check-with-evals)
dokładnie tego, co zostawia przyjęcie - wersji roboczej z naniesionymi wszystkimi wciąż
czekającymi sugestiami - nie przejdzie na tym modelu bez potwierdzonej regresji.
Odrzucenie innej sugestii albo edycja wersji roboczej sprawia, że ostatnie sprawdzenie
jest nieaktualne i potrzebne jest nowe.
Sprawdzenie, które zostawiło przypadek nierozstrzygnięty - nic go nie oceniło
albo zawiódł na nim provider lub oceniający - albo nie doszło do werdyktu, też ją
wstrzymuje: oceń odpowiedzi albo uruchom sprawdzenie ponownie. Tak samo
sprawdzenie, w którym agent się wysypał: napraw to, co zawiodło, i uruchom je
ponownie.

## Skille { #skills }

Skill ulepsza się z jego workbencha w zakładce Skille. Asystent sugeruje całą
nową treść, która czeka razem z innymi zmianami [skilli](skills.md) w zakładce
Skille, z uzasadnieniem i dowodami.

Zastosowanie zmiany skilla działa od razu: każdy agent powiązany ze skillem
czyta nową treść przy następnym runie. Dlatego zmianę skilla można najpierw
sprawdzić w ewaluacji na agencie, który go używa: obie strony uruchamiają
opublikowaną wersję tego agenta, a różni się tylko treść skilla. Zmiana
napisana dla starszej wersji skilla jest odrzucana, jeśli ktoś w międzyczasie
zmienił skill.

## Pliki kontekstowe { #context-files }

[Plik kontekstowy](context.md) ulepsza się z jego edytora na stronie Context, na
podstawie runów agentów, które go czytają. Asystent sugeruje nową treść, a ta
czeka nad listą na tej stronie, z uzasadnieniem i dowodami, oraz z agentami,
do których plik jest podpięty - o ile możesz ich widzieć. Na każdy plik czeka naraz jedna
zmiana.

Zastosowanie jej działa od razu, jak w przypadku skilla: każdy agent podpięty do
pliku czyta nową treść przy swoim następnym runie. Dlatego pierwszą akcją jest
**Sprawdź w ewaluacji**, na agencie, który używa pliku, gdzie różni się tylko treść
pliku, a **Zastosuj** mówi, zanim go naciśniesz, dla których agentów i środowisk
zmiana zacznie działać, które suity ewaluacji ustawi w kolejce i którzy strażnicy
sprawdzą ją dopiero przy następnej promocji. Zastosowanie powiadamia właścicieli
tych agentów. Zmiany nie da się zastosować do pliku edytowanego po tym, jak ją
zaproponowano: porównaj obie wersje i edytuj plik ręcznie albo poproś asystenta
ponownie.

Asystent nigdy nie proponuje treści w jej obecnym brzmieniu, a nowa prośba
przepisuje zmianę, która już czeka. Zastosuj i Odrzuć wskazują wersję zmiany,
którą przeczytałeś, i odmawiają, jeśli od tamtej pory się zmieniła - przy
zmianie skilla tak samo jak przy pliku.

## Opisanie nowego agenta { #describing-a-new-agent }

Dialog tworzenia pozwala opisać agenta zamiast wypełniać formularz. Opis trafia
do [Architekta](console.md#the-assistant), który tworzy wersje robocze agentów i
pyta, zanim którąś utworzy; wynikiem jest zwykła wersja robocza.

## Koszt i budżet { #cost-and-budget }

Ulepsz i Sprawdź mówią, co przeczytają i ile to będzie kosztować, zanim
cokolwiek zostanie wydane, i ruszają po drugim kliknięciu. Asystent ma własny
miesięczny budżet, pięć dolarów przy utworzeniu, który może zmienić edytor
agenta. Zlecenie, które kosztowałoby więcej, niż zostało asystentowi albo
organizacji, jest odrzucane, zanim cokolwiek zostanie zapisane.

Na dashboardzie linia wydatków podaje osobno, ile asystent kosztował **na
ulepszenia**, niezależnie od kosztu ewaluacji.

Retencja aktywności zachowuje łączny koszt usuniętych płatnych runów sesji, bez przechowywania pytań i odpowiedzi. Usuwanie starych aktywności nie przywraca dostępnego limitu wydatków. Nowe sprawdzenia i ponowienia doliczają się do zachowanej kwoty; anulowanie nadal pozostawia widoczne poniesione koszty.

## Dostęp { #access }

| Żeby | Potrzebujesz |
|---|---|
| Uruchomić Ulepsz albo Sprawdź na agencie | `runs:view`, uprawnień edycji agenta i możliwości użycia asystenta |
| Ulepszyć skill | `runs:view`, uprawnień edycji skilla i możliwości użycia asystenta |
| Ulepszyć plik kontekstowy | `runs:view`, `context:edit` na pliku i możliwości użycia asystenta |
| Przyjąć, odrzucić albo cofnąć sugestię | Uprawnień edycji agenta |
| Przyjąć sugestię, która coś podpina albo do czegoś sięga | Także dostępu, by podpiąć to ręcznie |
| Zastosować albo odrzucić zmianę skilla | `skills:edit` na skillu |
| Zastosować albo odrzucić zmianę pliku kontekstowego | `context:edit` na pliku |
| Sprawdzić w ewaluacji | Tego, czego wymaga [run ewaluacji](evals.md#access), i uprawnień edycji agenta |

Granty się liczą: członek z grantem edycji na jednym agencie może ulepszać tego
agenta.

## Gdy wsparcie AI jest wyłączone { #when-ai-assistance-is-off }

Gdy przełącznik **wsparcia AI** organizacji jest wyłączony, asystent nie działa:
Ulepsz, Sprawdź i ulepszanie skilla albo pliku kontekstowego są odrzucane przez
serwer, a konsola
pokazuje je jako wyłączone z linkiem do przełącznika. Sugestie, które już
czekają, nadal można przyjmować, odrzucać i cofać, a run ewaluacji, który nie
potrzebuje sędziego, nadal działa.

## Sesje poprawiania w tle { #background-improvement-sessions }

API koordynuje poprawianie agenta w tle. Najpierw wyślij dataset lub zestaw i limit
rund do `/agents/{agent_id}/improvements/estimate`, następnie ten sam cel wraz z
`budget_usd` do `/agents/{agent_id}/improvements`. Łączny szacunek obejmuje propozycje,
obie strony ewaluacji, sędziego, powtórki potwierdzające i jedno powtórzenie
nierozstrzygniętego porównania na rundę. Płatny krok rusza tylko wtedy, gdy jego
pełny szacunek mieści się w pozostałym budżecie sesji. Rozpoczęty krok może się
dokończyć, a rzeczywiste koszty pozostają widoczne także po anulowaniu.

Odczyt kolekcji lub sesji pokazuje zapisaną historię, identyfikatory zadań, werdykty
i koszty. Twórca lub administrator organizacji może wysłać żądanie do
`/{run_id}/cancel` w tej kolekcji. Worker przed przejściem sprawdza aktualne
uprawnienia twórcy, wersję roboczą, ostatnią publikację, ocenianie i przypięcie zestawu.
Zmiana danych unieważnia sesję; utrata uprawnień ją zatrzymuje. Dla jednego agenta
może działać tylko jedna sesja.

Sprawdzona poprawa kończy się stanem `ready`, a kandydat staje się oczekującym
pakietem sugestii. Sesja nigdy nie akceptuje, nie publikuje ani nie promuje zmian.
Wcześniejsze kandydaty nie zastępują sugestii oczekujących na decyzję człowieka.
Powiadomienie twórcy prowadzi do gotowej lub zatrzymanej sesji. Otwarta strona sesji śledzi każdy etap przez zdarzenia zmian na żywo, a zakończona propozycja lub sprawdzenie od razu przesuwa sesję dalej.

Sesja wykonuje najwyżej trzy rundy. Regresja albo brak zmiany uruchamia następną propozycję tylko wtedy, gdy jej pełny kosztorys mieści się w pozostałym budżecie. Dwie rundy bez zmiany, nierozstrzygnięte porównanie i jego powtórzenie, wcześniej sprawdzony kandydat albo limit rund zatrzymują pętlę z zapisanym powodem. Odpowiedzi treningowe przed zmianą i po niej zasilają kolejną rundę; materiał kontrolny pozostaje ukryty. Koszty rund są osobne, a wybór najlepszej preferuje poprawę, mniej nowych błędów, następnie wyższą skuteczność po rozstrzygnięciu.

Po zakończeniu `/{run_id}/rounds/{number}/select` ustawia zmierzoną rundę jako oczekującą propozycję, po sprawdzeniu aktualności bazy i dostępu. Opcjonalne przypisanie skutków do zmian ma akcje `.../attribution/estimate` i `.../attribution`. Uruchomienie wymaga `confirmed: true` i przejrzanej kwoty `estimate_usd`; wyższa świeża wycena jest odrzucana. Każdą oczekującą zmianę sprawdza osobno względem tej samej bazy i przypiętych pytań. Koszt obciąża budżet sesji. Nie przyjmuje ani nie publikuje zmian i nie zastępuje łącznego werdyktu rundy.

### Kreator Popraw { #the-improve-wizard }

Otwórz **Popraw** w nagłówku agenta, z plakietki **Wymaga uwagi** na liście agentów, z karty na dashboardzie albo z zakładki **Luki w wiedzy** agenta. To główna akcja nagłówka, gdy agent miał w ostatnich 30 dniach odpowiedzi ocenione negatywnie albo nieudane runy. Sesja ma adres `/agents/<agent>/improve/<session>`; stronę można zamknąć i otworzyć ponownie, gdy praca trwa. Każdy ekran prosi o najwyżej jedną decyzję, a opcje zaawansowane są pod **Pokaż szczegóły**.

1. **Start.** Trzy liczby z ostatnich 30 dni, potem pytania testowe. Pełny szacowany koszt, razem z przybliżonym czasem trwania sesji, pojawia się bez kliknięcia i niczego nie wydaje; przed startem potwierdź limit wydatków. Bez pytań najpierw oszacuj i potwierdź napisanie zestawu testowego. Wybór agenta pomocniczego i test dzisiejszych odpowiedzi są pod **Pokaż szczegóły**.
2. **Zrozumienie.** Jedno zdanie liczy problemy do poprawy w agencie i informacje, których brakuje w bazie wiedzy. Przykłady, których braki trafiły do jednego tematu luk w wiedzy, tworzą jedną kartę. **Przenieś do drugiej kolumny** i **Zignoruj** są zapisywane w sesji przez `PUT /{run_id}/evidence/{evidence_run_id}` z `decision` równym `agent`, `missing_knowledge`, `ignored` albo `null`. Kolejne próby pomijają w zmianach agenta przykłady zignorowane i przeniesione do bazy wiedzy; nic, co już zaproponowano lub zmierzono, się nie zmienia.
3. **Pytania.** Pytania policzone według źródła: odpowiedzi ocenione negatywnie, odpowiedzi ocenione pozytywnie, pytania napisane dla tematów bez przykładu i pytania dodane ręcznie. Przy mniej niż trzech pytaniach krok proponuje **Napisz jeszcze 5** przez generator pytań, który prosi o własny szacunek.
4. **Dzisiaj.** Na ile pytań agent odpowiada dobrze teraz, słabe odpowiedzi ze zdaniem oceniającego i osobno policzone pytania bez oceny.
5. **Zmiany.** Każda zmiana z sekcjami Przed, Po, Dlaczego, Na podstawie i Powinno naprawić oraz przełącznikiem **Uwzględnij w teście**. Szkice wiedzy tworzą osobną kolumnę. Gdy nie znaleziono zmiany, ekran wymienia, czego próbowała każda próba.
6. **Sprawdzenie.** Etapy testu: pytanie poprawionego agenta, ocenianie i ponowne zadanie pytań, których wynik się zmienił.
7. **Wynik.** Jedno zdanie o agencie i jedno o bazie wiedzy, kolorowy werdykt, pytania niewykorzystane do pisania zmian przed i po oraz koszt odpowiedzi. Wcześniejsze próby, sprawdzenia pojedynczych zmian i test szkicu wiedzy są pod **Pokaż szczegóły**.
8. **Akceptacja.** Co nowa wersja naprawi, zepsuje i ile będzie kosztować odpowiedź, oraz na ilu pytaniach ją przetestowano. Każdy dokument wiedzy ma **Przejrzyj i dodaj** albo **Nie teraz**. Jeśli środowisko śledzące nowe wersje ma automatyczne sprawdzenie, ekran mówi, że przełączy się ono po jego zaliczeniu. Potem **Opublikuj wersję N** albo zachowanie zmian w wersji roboczej i ekran **Gotowe** z linkiem do wersji.

Nieudany krok propozycji lub ewaluacji można jawnie ponowić przez `/{run_id}/retry`; powtórne kliknięcia nie tworzą kolejnego zadania. Automatyczne ponowienia zadań nie powtarzają płatnych wywołań. Decyzje człowieka zmieniają stan sesji na zaakceptowaną, opublikowaną lub odrzuconą. Potwierdzona akcja `/{run_id}/finish` akceptuje sprawdzone zmiany i opcjonalnie publikuje je w jednej transakcji. Może utworzyć suite uruchamianą przy publikacji, z zerowym limitem regresji. Nadal obowiązują standardowe uprawnienia i walidacja publikacji; chronione środowiska czekają na sprawdzenia. Propozycje zmienione po pomiarze wymagają ponownego sprawdzenia.

Przełącznikiem **Uwzględnij w teście** na ekranie zmian wybierz część sugestii. Przed wydaniem środków wyceń i potwierdź nowe sprawdzenie; zmiana wyboru albo treści sugestii unieważnia wycenę. Wybrane zmiany są mierzone względem tej samej bazy i przypiętych pytań. Wcześniejsze sprawdzenia pozostają w historii rundy. Wykluczone lub później dodane sugestie pozostają nierozstrzygnięte, a przyjąć można tylko zmierzony wybór. Takie sprawdzenie nie zamawia automatycznie kolejnej propozycji. Wyniki pojedynczych zmian przypisują tylko różnice potwierdzone powtórzeniem odpowiedzi; nieprawidłowe lub niedokończone sprawdzenie nie przypisuje skutków.

Szacunek sesji obejmuje klasyfikację złych odpowiedzi z rozmów względem edytowalnych baz wiedzy agenta, grupowanie braków i rezerwację do trzech proponowanych fragmentów na bazę. Worker zachowuje aktualne zakresy klucza API autora i przed rozpoczęciem ponownie sprawdza pełny koszt kroku. Klasyfikacja, grupowanie i szkice korzystają wyłącznie z przypiętych, niewymazanych rozmów; błędy treningowe pozostają materiałem agenta, a tekst kontrolny nie trafia do tych pomocników.

Błąd klasyfikatora jest widoczny, a rozmowy źródłowe pozostają dostępne. Sesja wymagająca tylko wiedzy kończy się szkicami do przejrzenia, bez pustej wersji agenta. Sprawdzenie szkicu nadal wymaga własnej wyceny i potwierdzenia; dodanie treści pozostaje osobną decyzją człowieka.

Ręczna ocena i jej cofnięcie przeliczają aktualnie zmierzoną rundę w tej samej transakcji co wynik testu i automatycznego sprawdzenia. Wybrana runda i koszt pozostają bez zmian. Starsze pomiary oraz sprawdzenia pojedynczych sugestii nie zastępują aktualnego wspólnego werdyktu. Przegląd nie uruchamia nowego modelu, publikacji ani przeniesienia środowiska. Jeżeli autor sesji nie może już odczytać porównania, runda staje się nierozstrzygnięta zamiast zachować zielony wynik. Zdarzenia datasetu odświeżają widoki testów, automatycznych sprawdzeń, sesji i środowisk.

Pasek kroków rozróżnia pracę gotową, trwającą, wymagającą decyzji, pominiętą i jeszcze nierozpoczętą. Wybierz krok, aby go obejrzeć; nie uruchamia to płatnej akcji. Ponowne otwarcie sesji pokazuje aktualną pracę, a pasek zachowuje stan każdego kroku. Na telefonie nazwa bieżącego kroku i jego status są widoczne pod znacznikami.

Wybierz **Popraw ponownie**, aby rozpocząć następną rundę, lub **Zwiększ limit i kontynuuj**, gdy zabrakło budżetu. Kolejne wydatki poprzedza pełna nowa wycena i potwierdzenie; źródła, przypięte pytania i limit rund pozostają bez zmian. Ponowienie nieudanego kroku pozostaje w tej samej rundzie. Wznowiony test rezerwuje tylko pozostałe pomiary, wraz z niewykorzystanym powtórzeniem nierozstrzygniętego porównania. Płatne wznowienie wymaga pierwotnego autora i tożsamości klucza API, z ponowną kontrolą aktualnych uprawnień. **Odrzuć** potwierdza odrzucenie wyłącznie oczekujących propozycji tej sesji. Nie zmienia innych zestawów i nie cofa zastosowanych zmian. Wycena nie ogłasza zapisu; potwierdzone decyzje odświeżają otwarte widoki agenta.

### Propozycja nowego skilla { #proposing-a-new-skill }

Asystent może zaproponować **Warto utworzyć skill**, gdy procedura występuje w co najmniej trzech różnych odpowiedziach stanowiących materiał źródłowy. Każdy cytat musi występować w samej odpowiedzi; komentarze czytelników nie dowodzą powtarzającej się procedury. Karta pokazuje nazwę, opis, pełną treść, uzasadnienie i zweryfikowane cytaty. Ewaluacja przypina tymczasowy skill tylko do kandydata: nie tworzy rekordu skilla ani opublikowanej wersji.

**Accept** tworzy prywatny skill i przypina go do wersji roboczej agenta w jednej transakcji. Wymaga `skills:edit` oraz edycji agenta. Bez uprawnienia tworzenia można czytać i sprawdzać propozycję, ale wyłączone Accept wyjaśnia powód. **Dismiss** niczego nie tworzy. **Undo** usuwa przypięcie i zachowuje niezależny skill; kolejna akceptacja wykorzystuje go ponownie tylko wtedy, gdy nazwa i treść nadal pasują. Skill zawiera instrukcje i nie nadaje dostępu do narzędzi. Dodatkowy dostęp wymaga osobnych propozycji sprawdzanych przez politykę, z zatwierdzaniem narzędzi zapisujących.

Szacowany koszt uwzględnia pełną proponowaną treść dla każdej odpowiedzi kandydata i jej powtórzeń potwierdzających, oprócz historycznego kosztu odpowiedzi.

### Sprawdzanie szkicu wiedzy { #checking-a-knowledge-draft }

W zakończonej sesji wybierz szkic i niezależne pytania na jego temat. Oszacowanie kosztu i potwierdzenie są oddzielne od akceptacji zmian agenta. Test porównuje **A**, wybrane zmiany agenta, z **B**, tymi samymi zmianami i szkicem. Osobny wynik zawiera zastrzeżenie **zakładając, że wyszukiwanie znajdzie ten fragment**: ten etap przekazuje fragment jako kontekst i nie sprawdza wyszukiwania.

Przypadki treningowe, rozmowy i tury źródłowe oraz znormalizowane kopie pytań źródłowych są wykluczane. Potrzeba co najmniej pięciu niezależnych pytań kontrolnych, które można ocenić; inaczej szkicu **nie można zmierzyć** i płatne sprawdzenie nie ruszy. Pełny szacunek obejmuje oba warianty i powtórzenia, obciąża limit sesji i dotyczy aktualnego szkicu oraz wybranych pytań.

**Bez źródła — sprawdź fakty** oznacza, że szkic nie ma istniejącego dokumentu źródłowego w bazie wiedzy. Poprawne odpowiedzi w teście nie dowodzą prawdziwości faktów. Sprawdź fragment w istniejącym dialogu tematu i samodzielnie zdecyduj o dodaniu. Test nie tworzy pliku kontekstu ani dokumentu bazy wiedzy i niczego nie publikuje. Po dodaniu dokumentu przez osobę nadal uruchamiają się zestawy zależne od bazy wiedzy.

Tymczasowe treści są usuwane po zakończeniu sprawdzenia lub zmianie szkicu. Zmiana szkicu unieważnia stary wynik. Usunięcie danych osoby źródłowej czyści także odpowiedzi testowe, uzasadnienia ocen i manifesty modeli. Anulowanie sesji anuluje jej sprawdzenia wiedzy. Koszt pozostaje zapisany po anulowaniu lub usunięciu danych.

Szkic zapisuje odciski wszystkich pytań wejściowych, także niecytowanych. Starszych szkiców bez pełnego pochodzenia nie można zmierzyć; najpierw przygotuj nowy szkic. Odciski i identyfikatory runów źródłowych są usuwane razem ze szkicem przy usuwaniu danych osoby.

#### Sprawdzenie rzeczywistego wyszukiwania { #checking-real-retrieval }

Wybierz **Sprawdź, czy wyszukiwanie go znajdzie**, aby porównać A z B z nakładką działającą wyłącznie w wyszukiwaniu. Szkic jest przeliczany na embeddingi wybranym modelem bazy wiedzy i dołącza do kandydatów zapytania tylko w danym runie. Nadal obowiązują ograniczenia organizacji, listy dozwolonych dokumentów, filtry, ranking i limity końcowych wyników. Nie powstaje tabela wektorowa, dokument ani plik kontekstu. Tymczasowe treści są usuwane również po błędzie lub anulowaniu.

Nowa naprawa jest potwierdzona tylko wtedy, gdy szkic dotarł do każdej potwierdzającej odpowiedzi kandydata w końcowym wyniku wyszukiwania. Inaczej wynik jest niekonkluzywny, nawet jeśli ocena odpowiedzi jest dobra; rzeczywiste odpowiedzi i oceny pozostają dostępne. Zignorowanie błędu narzędzia przez model nie zamienia błędu wyszukiwania w sukces. Szacunek obejmuje dodatkowe wyszukiwania embeddingów i powtórzenia. Niedostępny lub niewyceniony model powoduje odmowę przed płatną pracą. Osoba nadal musi sprawdzić fakty i jawnie dodać dokument.

Ręczne testy i generowanie pytań testowych powiadamiają osobę, która je uruchomiła, o zakończeniu, także błędem. Ponowne dostarczenie zadania nie powiela powiadomienia. Testy podrzędne zestawu i sesji poprawy korzystają z powiadomienia procesu nadrzędnego. Preferencje tych zdarzeń znajdują się w **Ustawienia → Powiadomienia**. Otwarte strony testów i zbiorów danych odświeżają się przez strumień zmian po zatwierdzeniu wyniku.

Krok Zrozumienie w kreatorze pokazuje ograniczoną próbkę źródeł, zapisaną przyczynę, odpowiedź, komentarze oceniających i odnośnik do rozmowy. Nieznane przyczyny pozostają jawnie niesklasyfikowane. Krok Pytania testowe odczytuje przypiętą wersję pytań sesji i oznacza pytania treningowe oraz odłożone. Dzisiaj pokazuje punkt odniesienia dopiero po pomyślnym zakończeniu testu; pomiar częściowy lub nieudany nie jest przedstawiany jako gotowy wynik bazowy. Podgląd źródeł wymaga `runs:view`, ponownie sprawdza dostęp do baz wiedzy i usuwa dane uwierzytelniające z każdego pola tekstowego.


Ekran akceptacji pokazuje numer następnej wersji i zmierzony wynik wybranej rundy. Oferta automatycznego sprawdzenia pojawia się tylko dla agenta bez zestawu sprawdzeń. Publikacja zapisuje identyfikator i numer wersji w sesji, więc ponowne otwarcie zakończenia prowadzi do tej publikacji także po kolejnej. Stare sesje bez zapisanego powiązania pokazują stan bez zgadywania wersji. Błąd odczytu sugestii pozwala ponowić odczyt; zastąpione sugestie są niedostępne zamiast bez końca się ładować. Chronione środowiska śledzące zmiany czekają na sprawdzenia, a przypięte zachowują obecną wersję.
