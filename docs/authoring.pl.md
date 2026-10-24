---
source_sha: "e67ba5777c29"
title: "Asystent tworzenia"
description: "Asystent tworzenia czyta, co ludzie ocenili negatywnie i jak kończyły się runy, i sugeruje zmiany w instrukcjach agenta, jego narzędziach, konfiguracji, skillach i plikach kontekstowych. O każdej decyduje człowiek."
---

# Asystent tworzenia { #authoring-assistant }

**Asystent tworzenia** ulepsza agentów na podstawie dowodów. Czyta, co ludzie
ocenili negatywnie i jak kończyły się runy, i sugeruje zmiany w instrukcjach
agenta, w nazwach i opisach jego narzędzi, w jego
[konfiguracji](#configuration) oraz w skillach i plikach kontekstowych, których
używa. Nigdy niczego nie zmienia sam: każda sugestia czeka na człowieka, przyjęta trafia do
[draftu](concepts.md), a nic nie dociera do nikogo, dopóki draft nie zostanie
opublikowany.

Robi trzy rzeczy:

- **Ulepsza** agenta: sugeruje zmiany na podstawie jego negatywnie ocenionych i
  nieudanych runów.
- **Sprawdza** Twoje zmiany: porównuje draft z wersją, na której się opiera -
  najnowszą opublikowaną - na tych samych dowodach i mówi, co zmiany poprawiają,
  czym ryzykują i co usunęły.
- **Ulepsza skill** albo **plik kontekstowy**: sugeruje nową treść na podstawie
  runów, które go czytały.

Asystent jest osobnym [agentem systemowym](datasets.md#judge), widocznym razem z
pozostałymi agentami systemowymi organizacji. Jego instrukcje można edytować jak
instrukcje każdego agenta, a jego runy są zwykłymi runami: objęte budżetem,
wycenione i widoczne w Activity.

## Co czyta { #what-it-reads }

Asystent nie ma narzędzi. To, co czyta, jest dla niego zebrane z runów agenta z
ostatnich 30 dni:

- odpowiedzi ocenione negatywnie, najpierw te z komentarzami;
- runy, które się nie udały, wyczerpały budżet albo zostały zablokowane przez
  guardrail;
- odpowiedzi ocenione pozytywnie, jako kontrast.

Udany run bez oceny nie mówi niczego i nie jest czytany. Nie jest też czytany
test z panelu testowego Buildera ani run delegata.

**Nigdy nie czyta evali.** Runy, które odpowiadały na przypadek
[evala](evals.md), runy sędziego i własne runy asystenta są pomijane, a wyników
ocen nie widzi nigdy. Zmiana sprawdzana evalami nie może być dopasowana do
przypadków, które ją sprawdzają.

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

## Sugestie { #suggestions }

Ulepsz i Sprawdź otwierają **pasek asystenta** na zakładce Build agenta. Każda
sugestia pokazuje zmieniany fragment w jego otoczeniu, powód i dowody, a o
każdej decyduje się osobno:

| Akcja | Co się dzieje |
|---|---|
| **Przyjmij** | Zmiana trafia do draftu. Nic nie jest publikowane. |
| **Edytuj** | Zamiast sugestii przyjmowane jest Twoje sformułowanie. |
| **Odrzuć** | Zapisane; późniejsze zlecenie nie zasugeruje tego ponownie. |
| **Cofnij** | Odwraca decyzję, dopóki pasuje ona do draftu. |

Sugestia jest zakotwiczona w miejscu, w którym był jej fragment, i w tym, co go
otaczało, a nie w samym tekście, więc linia, która występuje dwa razy, jest
zmieniana tam, gdzie miała być. Jeśli draft poszedł dalej - fragment został
usunięty albo opis narzędzia zmieniony ręcznie - sugestia mówi, że **nie pasuje
już do draftu**, i można ją tylko odrzucić. Cofnij odmawia tak samo, gdy
przyjęty tekst został potem zmieniony ręcznie: wyrzuciłoby to tę zmianę.

Nowsze Ulepsz zastępuje oczekujące sugestie; Sprawdź dodaje do nich swoje.
Opublikowanie draftu je zamyka: decyzje stają się ostateczne, a pasek zachowuje
je jako zapis.

Zmiana zaproponowana przez asystenta, której nie da się zapisać, nie znika po
cichu. Pasek wymienia ją pod **proponowane zmiany nie zostały zapisane**, z
powodem: fragmentu, który zmienia, nie ma w instrukcjach albo występuje więcej
niż raz, agent nie ma takiego narzędzia, tego ustawienia asystent nie może
zmieniać. Worker loguje te same powody. Fragment skopiowany z wyprostowanymi
cudzysłowami, bez backticków albo ze złączonymi liniami nadal trafia na tekst
draftu.

### Sprawdź evalami { #check-with-evals }

**Sprawdź evalami** uruchamia [dataset](datasets.md) na bazie draftu - najnowszej
opublikowanej wersji - z naniesionymi wszystkimi oczekującymi sugestiami, obok tej
wersji w tym samym [eval runie](evals.md#a-baseline-in-the-same-run). Strażnik
może trzymać produkcję na starszej wersji; sprawdzenie nigdy nie mierzy względem
niej, więc to, co zmieniła najnowsza wersja, jest po obu stronach i nigdy nie
jest przypisywane sugestii. Gdy draft odszedł od swojej bazy - Twoimi własnymi
zmianami albo wcześniej przyjętymi sugestiami - baseline'em jest sam draft,
uruchomiony na nowo, a nie wzięty z wcześniejszego runu, więc sugestie są jedyną
różnicą; wycena kosztu obejmuje też tę stronę. Strony są nazwane tym, czym są, w
dialogu i na runie: "v2 + 1 sugestia" wobec "v2" albo "Draft + 2 sugestie" wobec
"Draft". Sprawdzenie niczego nie przyjmuje i nie zmienia draftu. Dopóki któraś
oczekująca sugestia nie pasuje już do draftu albo koliduje z inną, sprawdzenia
nie da się uruchomić, dopóki nie zostanie przyjęta lub odrzucona: run mierzy
dokładnie to, co czeka.

Zamiast datasetu sprawdzenie może uruchomić jedną z [suit](evals.md#suites)
agenta: jej dataset, w jej środowisku. Run porównuje obie strony tak jak każde
sprawdzenie, a gdy się zakończy, mówi też, jak oceniłaby go suita: zaliczona,
niezaliczona albo bez rozstrzygnięcia, i dlaczego, według progu, jaki suita
miała w chwili startu sprawdzenia. Widać to na runie i przy sprawdzeniu w pasku,
w tym samym brzmieniu co wyniki suity.

Pasek opisuje każde zakończone sprawdzenie jednym zdaniem z linkiem do jego
runu - "audit-smoke: nie przeszłoby - psuje „Do you ship to Canada?”" albo to,
co zepsuło i naprawiło na datasecie.

Sprawdzenie nie jest runem suity: nie trafia do żadnej historii suity, nikogo
nie powiadamia, a Przyjmij kieruje się werdyktem samego runu. Zmiana skilla albo
pliku kontekstu sprawdzana na suicie agenta, na którym działa, dostaje to samo.

Przypadki wzięte z rozmów, z których wzięły się sugestie, są pomijane, a run
podaje ich liczbę: zmiany nigdy nie mierzy się na danych, do których ją
dopasowano. Dataset złożony wyłącznie z takich przypadków jest odrzucany.

Sprawdzenie liczy się jako test draftu, gdy draft jest dokładnie tym, co
sprawdzało - każda sprawdzona sugestia przyjęta i nic poza tym nie zmienione -
więc dialog publikacji podaje jego werdykt; po kolejnej zmianie mówi, że ten
test jest nieaktualny. Sprawdzenie mierzone względem samego draftu nigdy się nie
liczy: nie mówi nic o drafcie względem opublikowanej wersji, którą by zastąpił.
Sprawdzenie samo z siebie nie wysyła niczego do
[kolejki przeglądu](datasets.md#review) datasetu, bo nic nie zostało przyjęte;
strona jego runu mówi o tym obok **Send failed to review**.

Każda sugestia podaje oczekiwany efekt. Pasek pokazuje go obok eval runów, które
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

Nic poza tym nie jest sugestią: zestawy evali i ich progi, datasety, budgety,
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
wyłączone i mówi dlaczego, dopóki [sprawdzenie evalami](#check-with-evals)
dokładnie tego, co zostawia przyjęcie - draftu z naniesionymi wszystkimi wciąż
czekającymi sugestiami - nie przejdzie na tym modelu bez potwierdzonej regresji.
Odrzucenie innej sugestii albo edycja draftu sprawia, że ostatnie sprawdzenie
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
sprawdzić evalami na agencie, który go używa: obie strony uruchamiają
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
**Sprawdź evalami**, na agencie, który używa pliku, gdzie różni się tylko treść
pliku, a **Zastosuj** mówi, zanim go naciśniesz, dla których agentów i środowisk
zmiana zacznie działać, które suity evali ustawi w kolejce i którzy strażnicy
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
do [Architekta](console.md#the-assistant), który tworzy drafty agentów i pyta,
zanim któryś utworzy; wynikiem jest zwykły draft.

## Koszt i budżet { #cost-and-budget }

Ulepsz i Sprawdź mówią, co przeczytają i ile to będzie kosztować, zanim
cokolwiek zostanie wydane, i ruszają po drugim kliknięciu. Asystent ma własny
miesięczny budżet, pięć dolarów przy utworzeniu, który może zmienić edytor
agenta. Zlecenie, które kosztowałoby więcej, niż zostało asystentowi albo
organizacji, jest odrzucane, zanim cokolwiek zostanie zapisane.

Na dashboardzie linia wydatków podaje osobno, ile asystent kosztował **na
ulepszenia**, niezależnie od kosztu evali.

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
| Sprawdzić evalami | Tego, czego wymaga [eval run](evals.md#access), i uprawnień edycji agenta |

Granty się liczą: członek z grantem edycji na jednym agencie może ulepszać tego
agenta.

## Gdy wsparcie AI jest wyłączone { #when-ai-assistance-is-off }

Gdy przełącznik **wsparcia AI** organizacji jest wyłączony, asystent nie działa:
Ulepsz, Sprawdź i ulepszanie skilla albo pliku kontekstowego są odrzucane przez
serwer, a konsola
pokazuje je jako wyłączone z linkiem do przełącznika. Sugestie, które już
czekają, nadal można przyjmować, odrzucać i cofać, a eval run, który nie
potrzebuje sędziego, nadal działa.
