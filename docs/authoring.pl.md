---
source_sha: "b3157fa045a8"
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
Powiadomienie twórcy prowadzi do gotowej lub zatrzymanej sesji.

Sesja wykonuje najwyżej trzy rundy. Regresja albo brak zmiany uruchamia następną propozycję tylko wtedy, gdy jej pełny kosztorys mieści się w pozostałym budżecie. Dwie rundy bez zmiany, dwie nierozstrzygnięte, wcześniej sprawdzony kandydat albo limit rund zatrzymują pętlę z zapisanym powodem. Odpowiedzi treningowe przed zmianą i po niej zasilają kolejną rundę; materiał kontrolny pozostaje ukryty. Koszty rund są osobne, a wybór najlepszej preferuje poprawę, mniej nowych błędów, następnie wyższą skuteczność po rozstrzygnięciu.

Po zakończeniu `/{run_id}/rounds/{number}/select` ustawia zmierzoną rundę jako oczekującą propozycję, po sprawdzeniu aktualności bazy i dostępu. Opcjonalne przypisanie skutków do zmian ma akcje `.../attribution/estimate` i `.../attribution`. Uruchomienie wymaga `confirmed: true` i przejrzanej kwoty `estimate_usd`; wyższa świeża wycena jest odrzucana. Każdą oczekującą zmianę sprawdza osobno względem tej samej bazy i przypiętych pytań. Koszt obciąża budżet sesji. Nie przyjmuje ani nie publikuje zmian i nie zastępuje łącznego werdyktu rundy.
