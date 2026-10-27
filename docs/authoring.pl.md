---
source_sha: "edb3762a1f8c"
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
  nieudanych runów. W konsoli każde **Popraw** otwiera [kreator Popraw](#the-improve-wizard);
  jednorazowe żądanie jest nadal dostępne przez API.
- **Sprawdza** Twoje zmiany: porównuje wersję roboczą z wersją, na której się
  opiera - najnowszą opublikowaną - na tych samych dowodach i mówi, co zmiany
  poprawiają, czym ryzykują i co usunęły.
- **Ulepsza skill** albo **plik kontekstowy**: sugeruje nową treść na podstawie
  runów, które go czytały.

Asystent jest osobnym [agentem systemowym](concepts.md#system-agents), widocznym
razem z pozostałymi agentami systemowymi organizacji. Administrator edytuje jego
instrukcje jak instrukcje każdego agenta - zmiana agenta systemowego wymaga
`org:settings` - a jego runy są zwykłymi runami: objęte budżetem, wycenione i
widoczne w **Aktywności** (Activity). Nigdy nie jest agentem, którego dotyczy
Improve albo Verify. Ustawiony na
[przeszukiwanie bazy wiedzy](concepts.md#system-agent-spec) czyta bazy wiedzy
agenta, którego ulepsza.

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

Gdy żądanie asystenta - Sprawdź albo Ulepsz przez API - kończy się przy otwartym Builderze, dialog wyniku pokazuje liczbę przejrzanych odpowiedzi, zaproponowane i zapisane zmiany oraz odrzucone propozycje z powodami. Można otworzyć go ponownie przyciskiem **Zobacz wynik**. Pusty wynik informuje, że niczego nie można zastosować, bez oczekiwanego efektu. Opis efektu zawierający surowe identyfikatory runów jest zastępowany opisem z liczbą podlinkowanych odpowiedzi źródłowych.

Każdy zmieniony tekst - instrukcje, opis narzędzia, plik kontekstowy - jest pokazany jako diff: usunięte i dodane linie z zaznaczonymi zmienionymi słowami, kilka niezmienionych linii wokół każdej zmiany i zwinięta reszta, jednolicie albo obok siebie na szerokim ekranie. Każda zmiana zachowuje uzasadnienie i linki do materiału źródłowego; identyfikatory runów w uzasadnieniu są pokazane jako ponumerowane rozmowy.

Po zakończeniu sprawdzenia osoby z `runs:view` mogą porównać odpowiedzi obu stron w dialogu i otworzyć pełne sprawdzenie. Wcześniej dialog proponuje jego uruchomienie. Agent bez ocenionych rozmów ani materiału treningowego ma nad instrukcjami zwięzły wiersz asystenta.

## Sugestie { #suggestions }

Sugestie z sesji poprawy, ze Sprawdź albo z API czekają na **pasku asystenta** na
zakładce **Budowa** (Build) agenta. Każda
sugestia pokazuje zmieniany fragment w jego otoczeniu, powód i dowody, a o
każdej decyduje się osobno:

| Akcja | Co się dzieje |
|---|---|
| **Przyjmij** | Zmiana trafia do wersji roboczej. Nic nie jest publikowane. |
| **Edytuj** | Zamiast sugestii przyjmowane jest Twoje sformułowanie. Dla instrukcji otwiera się cały tekst: obecna wersja obok proponowanej, którą edytujesz, a diff odświeża się w trakcie pisania. Zapisywany jest tylko sugerowany fragment; tekst poza nim zmienia się w edytorze instrukcji. |
| **Odrzuć** | Zapisane; późniejsze zlecenie nie zasugeruje tego ponownie. |
| **Cofnij** | Odwraca decyzję, dopóki pasuje ona do wersji roboczej. |

Sugestia jest zakotwiczona w miejscu, w którym był jej fragment, i w tym, co go
otaczało, a nie w samym tekście, więc linia, która występuje dwa razy, jest
zmieniana tam, gdzie miała być. Jeśli wersja robocza poszła dalej - fragment
został usunięty albo opis narzędzia zmieniony ręcznie - sugestia mówi, że **nie
pasuje już do wersji roboczej**, i można ją tylko odrzucić. Cofnij odmawia tak samo, gdy
przyjęty tekst został potem zmieniony ręcznie: wyrzuciłoby to tę zmianę.

Pasek ma dwie zakładki, każdą z licznikiem. **Do decyzji** pokazuje w całości
każdą sugestię, która wciąż czeka. **Zdecydowane** zwija każdą przyjętą, zmienioną
albo odrzuconą do jednej linii z rodzajem zmiany - instrukcje, opis narzędzia,
ustawienie, nowy skill - decyzją i celem zmiany; rozwinięcie linii pokazuje zmianę
i Cofnij. Obie zakładki grupują zmiany według rodzaju. Pasek otwiera się na Do
decyzji albo na Zdecydowane, gdy nie zostało już nic do decyzji.

Nowsze Ulepsz zastępuje oczekujące sugestie; Sprawdź dodaje do nich swoje.
Opublikowanie wersji roboczej je zamyka: decyzje stają się ostateczne, a pasek
przestaje pokazywać je i resztę tego, co asystent zgłosił przed publikacją, bo
wszystko to dotyczyło wersji roboczej, która jest teraz wersją. Zostają zapisane
razem z decyzjami. Żądanie, które wciąż trwa w chwili publikacji, pokaże swoje
wyniki, gdy się zakończy.

Zmiana zaproponowana przez asystenta, której nie da się zapisać, nie znika po
cichu. Pasek wymienia ją pod **pomysły, których asystent nie dodał**, z
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

Każdy przypadek ma stałe przypisanie do treningu albo kontroli, zachowane między wersjami datasetu. Ustawienia datasetu wybierają udział kontroli tylko dla przyszłych przypadków (domyślnie 50%). Sprawdzenia sugestii mierzą wyłącznie przypadki kontrolne; sesja poprawy dzieli pytania od nowa dla każdej próby, w tej samej proporcji, i mierzy każdą próbę na jej własnej części kontrolnej. Oba wymagają co najmniej pięciu kontrolnych pytań z możliwością oceny.

Kopie pytań treningowych lub materiału źródłowego są wykluczane według znormalizowanej treści i identyfikatora runu, także po ręcznym wpisaniu lub wygenerowaniu. Poniżej minimum sesja zatrzymuje się z `no_data` albo odrzuca krok, który testowałby za mało pytań, i podaje liczbę brakujących pytań. Widok runu oznacza obie części i wykluczone kopie. Zwykłe suity i bramki promocji nadal liczą wszystkie przypadki.

Sesja poprawy przypina wersję datasetu i identyfikatory rozmów źródłowych. Kolejna próba uczy się na wynikach treningowych własnego podziału, więc pytanie odłożone przez jedną próbę może pomóc napisać następną; nowe rozmowy i przypadki nie zmieniają tego, co sesja mierzy. Próby mierzone na różnych pytaniach porównuje się po tym, co każda zmieniła względem własnej wersji wyjściowej, a nie po odsetku zaliczeń.

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

Sesja poprawiania idzie krok po kroku i między krokami czeka na człowieka; nigdy
nie akceptuje, nie publikuje ani nie promuje zmian. Wyślij dataset lub zestaw do
`/agents/{agent_id}/improvements/estimate`, a potem ten sam cel wraz z
`budget_usd` do `/agents/{agent_id}/improvements`. Budżet ogranicza całą sesję.
Start płaci tylko za odczytanie, co poszło źle: sesja sortuje złe odpowiedzi,
grupuje ich braki w [tematy](knowledge-gaps.md#topics) wiedzy i zatrzymuje się
po **Zrozumieniu** ze stanem `waiting`.

Na postoju wyślij `budget_usd` do `/{run_id}/continue/estimate`, aby poznać cenę
kroku, który by ruszył, a potem tę wycenę z `confirmed: true` do
`/{run_id}/continue`. Po **Zrozumieniu** następny krok pisze zmiany i znów
zatrzymuje się po **Zmianach**. Tam `PUT /{run_id}/selection` z `hunk_ids`
wybiera zmiany do testu, a `PUT /{run_id}/changes/{hunk_id}` z `edited_text`
testuje Twoje sformułowanie zamiast sformułowania pomocnika; oba są bezpłatne.
Następny krok testuje wtedy wybrane zmiany.

Cena, która zmieniła się od wyceny,
jest odrzucana razem z nową, do ponownego potwierdzenia. Krok, który nie mieści
się w tym, co zostało z budżetu, jest odrzucany, a sesja dalej czeka: podnieś
`budget_usd` i wyceń ponownie. Rozpoczęty krok może się dokończyć, a rzeczywiste
koszty pozostają widoczne także po anulowaniu.

Test biegnie sam: obecna i zmieniona wersja agenta odpowiadają na te same
pytania, a nierozstrzygnięte porównanie jest zadawane jeszcze raz w cenie testu.
Kończy się wynikiem: `ready`, gdy próba poprawiła agenta - jej zmiany stają się
wtedy oczekującym pakietem sugestii - a w przeciwnym razie `stopped`, z
werdyktem jako powodem.

Żadna próba nie rusza sama. **Spróbuj ponownie** to ten
sam `/continue` z wyniku, z opcjonalnym polem `note`, które pomocnik czyta obok
materiału; próba pisze nowe zmiany i zatrzymuje się po **Zmianach**, bo
**Zrozumienie** czyta się raz na sesję. Sesja wykonuje najwyżej trzy próby w
ramach budżetu. Dwa wyniki z rzędu bez zmiany albo nierozstrzygnięty wynik i
jego powtórzenie pokazują się na wyniku jako podpowiedź, że kolejna próba raczej
nie pomoże, a nie jako zatrzymanie.

Kto może rozpocząć sesję dla agenta - prawo edycji, `runs:view` i włączone
wsparcie AI - może też wykonać jej następny krok albo spróbować ponownie. Sesja
zapisuje, kto to zrobił, a dalsze kroki idą z aktualnymi uprawnieniami i
poświadczeniem tej osoby, więc sesję rozpoczętą przez Architekta można
poprowadzić dalej w konsoli.

Worker przed każdym przejściem sprawdza wersję
roboczą, ostatnią publikację, ocenianie i przypięcie zestawu: zmiana danych od
razu unieważnia sesję, a utrata uprawnień ją zatrzymuje.

Sesja czekająca na postoju, zatrzymana albo nieudana staje się nieaktualna także od razu, gdy zmieni się pod nią agent albo zestaw pytań; gotowa, której wersja robocza zmienia się, gdy w Budowie zapada decyzja o kandydacie, zamyka się dopiero po tygodniu. Sesja pozostawiona na
postoju albo na wyniku przez siedem dni zamyka się jako nieaktualna, z powodem
`expired`. Agent ma naraz jedną otwartą sesję - w kolejce, w toku, czekającą,
gotową, zatrzymaną albo nieudaną - więc rozpoczęcie kolejnej zwraca `409`,
dopóki otwarta się nie zakończy. Twórca lub administrator organizacji może
wysłać żądanie do `/{run_id}/cancel`.

Osoba, która wykonała ostatni krok, dostaje powiadomienie na każdym postoju i
przy każdym zakończeniu: przeczytana analiza, zmiany gotowe do przejrzenia,
sprawdzony wynik, sesja zatrzymana, nieudana albo nieaktualna, rozstrzygnięta
poza kreatorem oraz zakończone sprawdzenie wiedzy lub atrybucji. Odczyt kolekcji
lub sesji pokazuje zapisaną historię, identyfikatory zadań, werdykty i koszty;
otwarta strona sesji śledzi każdy etap przez zdarzenia zmian na żywo.

Każda próba odkłada do sprawdzenia własne pytania. Pytania testowe są dzielone
od nowa dla każdej próby - ta sama ich część co w ustawieniach datasetu,
losowana z sesji i próby, więc dana próba zawsze losuje te same - a podział
zamraża się, gdy rusza jej test: powtórzenie nierozstrzygniętego porównania,
test wybranych zmian, sprawdzenia pojedynczych zmian i sprawdzenie szkicu wiedzy
mierzą na nim.

Każda próba potrzebuje co najmniej pięciu ocenialnych pytań
odłożonych do sprawdzenia, a krok, który testowałby mniej, jest odrzucany z
informacją, ile pytań dodać. Pomocnik czyta odpowiedzi na pozostałe pytania
próby, nigdy na te odłożone. Ponieważ próby mierzy się na różnych pytaniach,
wynik porównuje je po tym, co każda zmieniła względem własnej wersji wyjściowej
- nowo naprawione minus nowo zepsute, w stosunku do liczby odłożonych pytań - a
odsetek zaliczeń próby zostaje w jej szczegółach. Najlepsza próba ma najlepszy
werdykt, a potem największą taką zmianę.

Po wyniku `/{run_id}/rounds/{number}/select` ustawia zmierzoną próbę jako
oczekującą propozycję, po sprawdzeniu aktualności bazy i dostępu. Opcjonalne
przypisanie skutków do zmian ma akcje `.../attribution/estimate` i
`.../attribution`. Uruchomienie wymaga `confirmed: true` i przejrzanej kwoty
`estimate_usd`; wyższa świeża wycena jest odrzucana. Każdą oczekującą zmianę
sprawdza osobno względem tej samej bazy i pytań próby. Koszt obciąża budżet
sesji. Nie przyjmuje ani nie publikuje zmian i nie zastępuje łącznego werdyktu
próby.

### Kreator Popraw { #the-improve-wizard }

Otwórz **Popraw** w nagłówku agenta albo na pasku asystenta na zakładce Budowa, z plakietki **Wymaga uwagi** na liście agentów, z karty na dashboardzie albo z zakładki **Luki w wiedzy** agenta. Stoi wśród pozostałych akcji nagłówka; gdy wersja, którą agent teraz serwuje, miała w ostatnich 30 dniach odpowiedzi ocenione negatywnie albo nieudane runy, nosi kropkę, a jego nazwa mówi dlaczego. Karta **Poprawki czekające na Ciebie** na dashboardzie wymienia sesje zatrzymane na decyzję.

Każde **Popraw** otwiera otwartą sesję agenta - pracującą, czekającą na Ciebie, na wyniku albo zatrzymaną lub nieudaną - a nową zaczyna, gdy ta sesja zostanie zachowana jako wersja robocza, opublikowana, odrzucona, anulowana albo zamknięta; zostaje wtedy w [historii usprawnień](#improvement-history) agenta. **Zakończ ją i zacznij nową** obok otwartej sesji najpierw ją kończy.

Sesja ma adres `/agents/<agent>/improve/<session>`; stronę można zamknąć i otworzyć ponownie, gdy praca trwa. Każdy ekran prosi o najwyżej jedną decyzję, podaje, kto co na nim zdecydował, a opcje zaawansowane trzyma pod **Pokaż szczegóły**. Każdy ekran zaczyna się od liczb i małych wykresów, a każdy stan oznacza ikoną, nie tylko kolorem; pełne odpowiedzi, cytaty i powody czekają w rozwijanych kartach. Jedna linia nad krokami podaje stan sesji - **Praca trwa**, gdy krok trwa, a na postoju, na co czeka: **Czeka na Ciebie: zobacz, co poszło nie tak** albo **Czeka na Ciebie: przejrzyj zmiany** - i ile wydała ze swojego limitu.

Krok otwiera się, gdy ma pracę do pokazania albo decyzję do podjęcia. Strona podąża za krokiem, na którym jest sesja, a po otwarciu innego kroku **Przejdź do bieżącego kroku** wraca do niego. Na postoju stopka zawiera następny krok z ceną, na przykład **Następny krok: napisz zmiany · ok. $0.04**; nic nie jest wydawane, zanim go naciśniesz. Gdy cena zmieniła się od pokazania, stopka to mówi - **Cena zmieniła się na ok. $0.05. Naciśnij jeszcze raz, aby przejść dalej.** - a gdy krok kosztuje więcej, niż zostało sesji, pozwala od razu podnieść jej limit.

**Start.** Trzy liczby z ostatnich 30 dni, potem własne pytania testowe agenta, już wybrane i wycenione: szacunek obejmuje odczytanie, co poszło źle, razem z przybliżonym czasem, pojawia się bez kliknięcia i niczego nie wydaje, więc **Zacznij poprawianie** to jedyna decyzja. Każdy następny krok jest wyceniany, zanim go naciśniesz, a limit ogranicza całą sesję. Inne pytania testowe, limit wydatków, agent pomocniczy i test dzisiejszych odpowiedzi są pod **Pokaż szczegóły**. Agent bez pytań testowych dostaje **Napisz dla mnie pytania testowe**: ocenione odpowiedzi stają się pytaniami, kolejne powstają dla tematów bez przykładu, a szacunek pojawia się, gdy są gotowe. Gdy zostaje za mało pytań, by zmierzyć zmianę, ekran proponuje napisanie tylu, ilu brakuje sesji. Podpowiedź po pierwszej publikacji otwiera ten ekran, by ustalić punkt odniesienia.

1. **Zrozumienie.** Jedno zdanie i pasek liczą problemy do poprawy w agencie i informacje, których brakuje w bazie wiedzy. Przykłady, których braki trafiły do jednego tematu luk w wiedzy, tworzą jedną kartę, podobnie jak pytanie zadane zarówno jako pytanie testowe, jak i w rozmowie. Karta pokazuje pytanie i rozwija się do odpowiedzi, komentarzy, sposobu oceny odpowiedzi testowej - ocena sędziego dla każdego kryterium i to, czy każda reguła jest spełniona - oraz powodu, dla którego się liczy: oceny, których nie przeszła, jak ktoś ją ocenił i dlaczego klasyfikator ją tam przydzielił. Odpowiedzi ocenione pozytywnie albo takie, w których klasyfikator nie znalazł błędu, trafiają do **Nie wymaga poprawy** automatycznie; na tym kroku nic nie ustawia się ręcznie. Odpowiedź, której temat obejmuje już dokument dodany od tego czasu, jest liczona w grupie **Już w bazie wiedzy** razem z tym dokumentem i dniem jego dodania: nie ma już dla niej czego szkicować. Sesja zawsze się tu zatrzymuje; **Następny krok: napisz zmiany** prosi pomocnika o zmiany.
2. **Zmiany.** Ile zmian zaproponowano i ile włączono, a potem każda zmiana jako diff z sekcją Powinno naprawić oraz zwiniętymi sekcjami Dlaczego i Na podstawie. Na postoju każda zmiana ma **Uwzględnij zmianę N w teście**, z czego co najmniej jedna zostaje zaznaczona, oraz **Zmień sformułowanie**, które testuje Twoje sformułowanie zamiast sformułowania pomocnika: zmiana jest wtedy oznaczona **Przeredagowane przez Ciebie**, a **Wróć do proponowanego sformułowania** to cofa. **Następny krok: przetestuj zaznaczone zmiany** uruchamia test; w jego trakcie listę można czytać, ale nie zmieniać. Szkice wiedzy tworzą osobną kolumnę, w której są szkice, o które ktoś poprosił. Gdy nie znaleziono zmiany, ekran wymienia, czego próbowała każda próba.
3. **Sprawdzenie.** Obecna i zmieniona wersja agenta odpowiadają na te same pytania w jednym teście, każda z paskiem postępu; odpowiedzi z testu sprzed rozpoczęcia sesji od razu wypełniają pasek obecnej wersji. Dalej etapy, każdy oznaczony jako gotowy, w toku albo nierozpoczęty: pytanie, ocenianie i ponowne zadanie pytań, których wynik się zmienił. Test biegnie sam, a wynik otwiera się, gdy się skończy. **Otwórz pełne sprawdzenie** prowadzi do runu ewaluacji.
4. **Wynik.** Najpierw to, do czego doszła sesja, w zdaniach zbudowanych z werdyktów - która próba poprawiła agenta albo że żadna, i która go pogorszyła - z tematami brakującymi w bazie wiedzy i powodem zatrzymania sesji; po decyzji mówi, która próba została opublikowana jako która wersja albo zachowana jako wersja robocza. Pod **Co możesz zrobić** jest jedna główna akcja: **Przejrzyj i zaakceptuj zmiany**, gdy czeka sprawdzony kandydat, **Spróbuj ponownie**, póki zostały próby lub budżet, **Przygotuj dokumenty, których potrzebujesz**, gdy brakuje tylko wiedzy, a poza tym **Zakończ bez zmian**, obok **Rozpocznij nową sesję** i wskazówki, by dodać pytania testowe tam, gdzie agent odpowiada źle. Nieudany krok najpierw proponuje **Ponów ten krok w limicie wydatków**. Gdy zmierzono co najmniej dwie próby, **Którą próbę zachować** wymienia je z zaznaczoną zachowaną; wybór innej wymaga **Zachowaj próbę N**, a próba, która nie była lepsza, najpierw mówi, ile kosztuje jej akceptacja - które pytania zepsuła albo że nie daje zmierzonej poprawy. Zamknięta sesja wymienia je bez wyboru. **Spróbuj ponownie** przyjmuje opcjonalną **Notatkę dla pomocnika** - co zmienić albo zostawić - i pokazuje cenę, zanim ruszy; nowa próba zatrzymuje się na **Zmianach**. Krok zatrzymany, bo osoba, która go wykonała, straciła potrzebny dostęp, proponuje **Kontynuuj ten krok z moim dostępem** każdemu, kto może rozpocząć sesję. Potem liczby: nowo naprawione i nowo zepsute liczą tylko zmiany potwierdzone ponownym zapytaniem, a niepotwierdzone - zmienione raz, ale przy ponownym zadaniu już nie tak samo - stoją pod nimi małym drukiem; liczba brakujących tematów prowadzi do ich listy. Każda próba to jeden zwinięty wiersz - werdykt, co naprawiła i zepsuła względem własnej wersji wyjściowej na odłożonych przez siebie pytaniach, koszt napisania i przetestowania - łączny koszt sesji, z analizą, stoi nad listą - a najlepsza próba jest oznaczona - albo, gdy ktoś wybrał próbę, która nie była lepsza, oznaczona jako wybrana. Każda próba odkłada własne pytania, więc próby porównuje się po zmianie, a nie po odsetku zaliczeń, który widać tylko w szczegółach wiersza. Wiersz rozwija się do pasków pytań obsłużonych dobrze przed i po, kosztu odpowiedzi, gdy się zmienił, i każdego zmienionego pytania z odpowiedziami przed i po; zmiana niepotwierdzona przez powtórzone odpowiedzi czeka pod **Jeszcze niepotwierdzone**, oznaczona tylko jako być może naprawiona albo być może zepsuta. Pasek jest zielony albo czerwony tylko dla zmiany potwierdzonej ponownym zapytaniem; w przeciwnym razie zostaje szary, a różnica jednego pytania albo paski wskazujące przeciwne kierunki są opisane jako mieszczące się w szumie. Pod **Pokaż szczegóły** w wierszu: **Jak to zmierzyliśmy**, jedno zdanie o tym, ile pytań widział pomocnik, a ile odłożono do rozstrzygnięcia wyniku; **Która zmiana pomogła?**, gdy próba wprowadziła co najmniej dwie zmiany, z kosztem przetestowania każdej osobno; i tylko wtedy, gdy sesja ma szkic do przetestowania, **Sprawdź, czy szkic by pomógł** - jakby wyszukiwanie go znalazło albo przez prawdziwe wyszukiwanie. Gdy sprawdzenia były szumem - odpowiedzi dostały obie oceny przy ponownym zadaniu w obrębie próby albo dzisiejsza wersja dostała różne wyniki między próbami na wspólnych dla nich odłożonych pytaniach - a żadna próba nie była lepsza, karta najpierw mówi, że test nie odróżnia lepszej wersji od gorszej, potem podaje, co go uwiarygodni - kryteria oceny tak/nie zamiast skali, regułę dla długości i formatu zamiast sędziego, więcej pytań, do około 30 odłożonych, mocniejszy model sędziego - i wymienia pytania ocenione na oba sposoby z ocenami z każdej próby. Obok lepszej próby tylko odnotowuje szum. Próby, które miały mniej niż pięć wspólnych odłożonych pytań, nie są porównywane pod kątem szumu, a karta to mówi. Dwie próby z rzędu, które niczego nie zmieniły albo których nie dało się wiarygodnie ocenić, dają podpowiedź, że kolejna raczej nie pomoże; sesja nigdy nie zatrzymuje się sama przed limitem prób, a karta wymienia ten limit dopiero, gdy zostanie osiągnięty. Zobacz [gdy porusza się sama ocena](evals.md#a-flip-is-confirmed-before-it-counts) oraz [jak stabilne są odpowiedzi](evals.md#how-steady-the-answers-are).
5. **Akceptacja.** Liczby: co nowa wersja naprawi, zepsuje i ile będzie kosztować odpowiedź, oraz na ilu pytaniach ją przetestowano. Tematy, których według tej sesji brakuje w bazie wiedzy, są wymienione razem z ich pytaniami. Sesja nie pisze szkicu żadnego z nich: każdy ma **Napisz szkic** z najwyższym kosztem jednego szkicu, w trakcie pisania pokazuje **Piszę szkic…**, a gotowy szkic ma **Przejrzyj i dodaj** albo **Nie teraz**, które odkłada go na czas sesji (`PUT /{run_id}/topics/{topic_id}/later`). Każde miejsce, w którym ludzie używają agenta, mówi, czy przełączy się od razu, po zaliczeniu automatycznego sprawdzenia, czy zostanie przy swojej wersji. Potem **Opublikuj wersję N** albo **Zachowaj jako wersję roboczą**. Każda z tych decyzji kończy sesję, a ten krok mówi wtedy, co postanowiono, kto i kiedy, z linkiem do wersji. Gdy nie ma czego akceptować, krok jest pomijany.

Link do kroku, którego już nie ma - `?step=testSet` albo `?step=today` - otwiera krok, który zajął jego miejsce, **Zrozumienie** albo **Sprawdzenie**, bez dodawania wpisu w historii.

Nieudany krok propozycji lub ewaluacji można jawnie ponowić przez `/{run_id}/retry`; powtórne kliknięcia nie tworzą kolejnego zadania. Automatyczne ponowienia zadań nie powtarzają płatnych wywołań. Decyzje człowieka zmieniają stan sesji na zaakceptowaną, opublikowaną lub odrzuconą. Potwierdzona akcja `/{run_id}/finish` akceptuje sprawdzone zmiany, w sformułowaniu podanym przez Ciebie tam, gdzie je podano, i opcjonalnie publikuje je w jednej transakcji.

Sesja zachowana jako wersja robocza jest zakończona: wersję roboczą publikuje się zwykłym **Opublikuj** agenta, a gdy to wersja zmierzona przez sesję, zostaje zapisana w sesji. Zakończenie może utworzyć suite uruchamianą przy publikacji, z zerowym limitem regresji. Nadal obowiązują standardowe uprawnienia i walidacja publikacji, a chronione środowiska czekają na swoje sprawdzenia. Zmiany edytowane po teście trzeba przetestować ponownie.

Szacunek sesji obejmuje klasyfikację złych odpowiedzi z rozmów względem edytowalnych baz wiedzy agenta i grupowanie ich braków w [tematy](knowledge-gaps.md#topics). Nie obejmuje szkiców: szkic powstaje tylko wtedy, gdy poprosi o niego człowiek, i jest rozliczany jako własny run szkicu. Każdy krok przed rozpoczęciem ponownie sprawdza swój pełny koszt. Klasyfikacja i grupowanie korzystają wyłącznie z przypiętych, niewymazanych rozmów; błędy treningowe pozostają materiałem agenta, a tekst kontrolny nie trafia do tych pomocników.

Błąd klasyfikatora jest widoczny, rozmowy źródłowe pozostają dostępne, a sesja i tak zatrzymuje się na **Zrozumieniu**. Sesja wymagająca tylko wiedzy zatrzymuje się i wymienia tematy, których brakuje w bazie wiedzy, żeby napisać szkice tych, których potrzebujesz, bez pustej wersji agenta. Szkic staje się nieaktualny, gdy po jego napisaniu do bazy wiedzy zostanie dodany dokument, a **Napisz szkic od nowa** pisze go ponownie (zobacz [Szkic brakującej treści](knowledge-gaps.md#drafting-the-missing-content)). Sprawdzenie szkicu nadal wymaga własnej wyceny i potwierdzenia; dodanie treści pozostaje osobną decyzją człowieka.

Ręczna ocena i jej cofnięcie przeliczają aktualnie zmierzoną próbę w tej samej transakcji co wynik testu i automatycznego sprawdzenia. Wybrana próba i koszt pozostają bez zmian. Starsze pomiary oraz sprawdzenia pojedynczych sugestii nie zastępują aktualnego wspólnego werdyktu. Przegląd nie uruchamia nowego modelu, publikacji ani przeniesienia środowiska. Jeżeli autor sesji nie może już odczytać porównania, próba staje się nierozstrzygnięta zamiast zachować zielony wynik. Zdarzenia datasetu odświeżają widoki testów, automatycznych sprawdzeń, sesji i środowisk.

Pasek kroków rozróżnia pracę gotową, trwającą, wymagającą decyzji, pominiętą i jeszcze nierozpoczętą. Wybierz krok, aby go obejrzeć; nie uruchamia to płatnej akcji. Ponowne otwarcie sesji pokazuje aktualną pracę, a pasek zachowuje stan każdego kroku. Na telefonie nazwa bieżącego kroku i jego status są widoczne pod znacznikami.

**Zwiększ limit i kontynuuj** pojawia się tam, gdzie wyceniony krok się nie zmieścił. Kolejne wydatki poprzedza pełna nowa wycena i potwierdzenie; źródła, przypięte pytania i limit prób pozostają bez zmian. Ponowienie nieudanego kroku pozostaje w tej samej próbie. Wznowiony test rezerwuje tylko pozostałe pomiary, wraz z niewykorzystanym powtórzeniem nierozstrzygniętego porównania.

**Zakończ bez zmian** na wyniku, a **Odrzuć** na innych krokach, potwierdza odrzucenie wyłącznie oczekujących propozycji tej sesji. Nie zmienia innych zestawów i nie cofa zastosowanych zmian. Wycena nie ogłasza zapisu; potwierdzone decyzje odświeżają otwarte widoki agenta.

#### Historia usprawnień { #improvement-history }

Zakładka **Historia** agenta pokazuje jego sesje usprawniania, od najnowszej: kiedy każda się zaczęła i kto ją uruchomił, jak wypadła wybrana próba, co postanowiono i ile kosztowała.

Zakończona sesja - zachowana jako wersja robocza, opublikowana, odrzucona, anulowana albo zamknięta, bo zmienił się jej punkt wyjścia albo nikt nie poprowadził jej dalej przez siedem dni - otwiera kreator tylko do odczytu: każdy krok i jego szczegóły można otworzyć, a niczego nie da się zmienić ani opłacić. Jej ostatni krok mówi, co postanowiono, kto i kiedy, wymienia zmierzone zmiany z ich rozstrzygnięciem, mówi, co stało się z każdym napisanym dokumentem wiedzy i czy agenta pilnuje automatyczne sprawdzenie.

Sesja czekająca na Ciebie, na wyniku, zatrzymana albo zakończona błędem pozostaje otwarta: **Popraw** i jej wpis w historii prowadzą do niej, żeby wykonać następny krok, podnieść limit i kontynuować, wybrać próbę, ponowić nieudany krok albo ją odrzucić.

API odpowiada `409` na każdą zmianę zakończonej sesji, poza powtórzeniem anulowania albo odrzucenia, które ją zakończyło. `GET /{run_id}/changes` zwraca zmiany zmierzone w wybranej próbie. Odczyt sesji wymaga dostępu do odczytu agenta i `runs:view`; zmiana albo rozpoczęcie sesji wymaga też prawa edycji agenta.

#### Pytanie Architekta { #asking-the-architect }

[Architekt](console.md#the-assistant) czyta sesje agenta, jego testowe runy i
pytania testowe, i wyjaśnia wynik prostymi słowami: co próba naprawiła, a co
zepsuła, czy zmianę potwierdziło ponowne zapytanie i jak zmieniły się pytania
wstrzymane. Odsyła do kreatora, zamiast go opowiadać.

Na każdym postoju mówi, co sesja znalazła, co zrobi następny krok i ile
kosztuje. Sesję uruchamia, wykonuje jej następny krok, ponawia, wybiera próbę,
przyjmuje, publikuje albo kończy tylko na Twoją prośbę; sesję, którą uruchomił,
można kontynuować w kreatorze, i odwrotnie.

Zapytany, co robić, poleca jeden krok i najpierw pyta. Każda zmiana, którą
wprowadza, czeka na Twoją zgodę na karcie, po jednym zdaniu o tym, co i
dlaczego; uruchomienie pokazuje koszt analizy i limit wydatków całej sesji, a
każdy kolejny krok swoją cenę. Woła te same akcje co kreator, jako Ty, więc
obowiązują te same sprawdzenia: zmieniony agent odmawia przyjęcia, chronione
środowisko czeka na swój check, a dziennik audytu zapisuje Ciebie, z
poświadczeniem Architekta obok.

### Propozycja nowego skilla { #proposing-a-new-skill }

Asystent może zaproponować **Warto utworzyć skill**, gdy procedura występuje w co najmniej trzech różnych odpowiedziach stanowiących materiał źródłowy. Każdy cytat musi występować w samej odpowiedzi; komentarze czytelników nie dowodzą powtarzającej się procedury. Karta pokazuje nazwę, opis, pełną treść, uzasadnienie i zweryfikowane cytaty. Ewaluacja przypina tymczasowy skill tylko do kandydata: nie tworzy rekordu skilla ani opublikowanej wersji.

**Accept** tworzy prywatny skill i przypina go do wersji roboczej agenta w jednej transakcji. Wymaga `skills:edit` oraz edycji agenta. Bez uprawnienia tworzenia można czytać i sprawdzać propozycję, ale wyłączone Accept wyjaśnia powód. **Dismiss** niczego nie tworzy. **Undo** usuwa przypięcie i zachowuje niezależny skill; kolejna akceptacja wykorzystuje go ponownie tylko wtedy, gdy nazwa i treść nadal pasują. Skill zawiera instrukcje i nie nadaje dostępu do narzędzi. Dodatkowy dostęp wymaga osobnych propozycji sprawdzanych przez politykę, z zatwierdzaniem narzędzi zapisujących.

Procedura z mniej niż trzech różnych odpowiedzi nie trafia do sugestii. Czeka w zakładce **Do decyzji**, w grupie Nowe skille, z pełną treścią. **Odrzuć** przenosi go do **Zdecydowane**, a Cofnij przywraca. **Create skill** otwiera podgląd: nazwę, opis i treść można edytować, a ostrzeżenie mówi, na ilu odpowiedziach się opiera. **Create skill** w podglądzie tworzy skill w bibliotece i przypina go do wersji roboczej agenta, nigdy do opublikowanej wersji. Wymaga tych samych uprawnień co Accept i nie wywołuje modelu. Drugie kliknięcie zwraca już utworzony skill.

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
