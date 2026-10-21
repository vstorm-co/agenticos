---
source_sha: "80c1b4a989ca"
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
- **Sprawdza** Twoje zmiany: porównuje draft z opublikowaną wersją na tych samych
  dowodach i mówi, co zmiany poprawiają, czym ryzykują i co usunęły.
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

### Sprawdź evalami { #check-with-evals }

**Sprawdź evalami** uruchamia [dataset](datasets.md) na drafcie takim, jaki byłby
po przyjęciu wszystkich oczekujących sugestii, obok opublikowanej wersji w tym
samym [eval runie](evals.md#a-baseline-in-the-same-run). Sprawdzenie niczego nie
przyjmuje i nie zmienia draftu. Dopóki któraś oczekująca sugestia nie pasuje
już do draftu albo koliduje z inną, sprawdzenia nie da się uruchomić, dopóki
nie zostanie przyjęta lub odrzucona: run mierzy dokładnie to, co czeka.

Zamiast datasetu sprawdzenie może uruchomić jedną z [suit](evals.md#suites)
agenta: jej dataset, w jej środowisku. Próg suity nie jest stosowany; run
porównuje draft z opublikowaną wersją tak jak każde sprawdzenie.

Przypadki wzięte z rozmów, z których wzięły się sugestie, są pomijane, a run
podaje ich liczbę: zmiany nigdy nie mierzy się na danych, do których ją
dopasowano. Dataset złożony wyłącznie z takich przypadków jest odrzucany.

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
| Capabilities | Dodać albo usunąć jedną albo zmienić jej ustawienia |
| Zatwierdzanie | Sprawić, że capability albo jedno z jej narzędzi najpierw pyta |
| Specjaliści | Przepisać opis wbudowanego [specjalisty](reference/capabilities.md#delegation) |
| Bazy wiedzy | Podpiąć albo odpiąć jedną |
| Pliki kontekstowe | Podpiąć albo odpiąć jeden |
| Narzędzia MCP | Zmienić, które narzędzia podpiętego serwera agent może wywołać |

Nic poza tym nie jest sugestią: zestawy evali i ich progi, datasety, budgety,
obserwowalność i przypięty delegat nigdy nie są zmieniane przez asystenta.
**Edytuj** działa na pojedynczej wartości albo tekście - ustawieniu, limicie
kroków, opisie; wszystko inne przyjmuje się albo odrzuca tak, jak zasugerowano.

### Nigdy nie poszerza dostępu { #never-widens-access }

Sugestię, która podpina bazę wiedzy, plik kontekstowy, profil modelu albo serwer
MCP, albo pozwala agentowi wywołać więcej narzędzi MCP, przyjmie tylko ktoś, kto
mógłby wprowadzić tę zmianę ręcznie: przyjęcie jej przez kogokolwiek innego jest
odrzucane, tak jak odrzuciłby je Builder. Zatwierdzanie tylko się zaostrza:
sugestia może sprawić, że capability albo narzędzie najpierw pyta, nigdy że
przestaje pytać. Capability dodana przez asystenta przychodzi z każdym swoim
narzędziem, które coś zmienia, ustawionym na pytanie najpierw, a sugestia
wymienia te narzędzia, tak jak wymienia narzędzia MCP, do których zmiana daje
dostęp.

### Zmiana modelu { #a-change-of-model }

Sugestia zmiany modelu mówi, ile kosztowałby jeden run na każdym z modeli,
wycenione na podstawie ostatnich runów agenta. Gdy wycena opiera się na mniej
niż pięciu, mówi, że to przybliżone oszacowanie, i z ilu runów.

Zmianę modelu przyjmuje się dopiero, gdy się opłaciła. **Przyjmij** pozostaje
wyłączone i mówi dlaczego, dopóki [sprawdzenie evalami](#check-with-evals)
czekających sugestii nie przejdzie na tym modelu bez potwierdzonej regresji.
Sprawdzenie, które niczego nie rozstrzygnęło - odpowiedź bez oceny albo brak
werdyktu - też ją wstrzymuje: oceń odpowiedzi albo uruchom sprawdzenie ponownie.

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
którzy czytają plik - o ile możesz ich widzieć. Na każdy plik czeka naraz jedna
zmiana.

Zastosowanie jej działa od razu, jak w przypadku skilla: każdy agent podpięty do
pliku czyta nową treść przy swoim następnym runie. Dlatego można ją najpierw
sprawdzić evalami, na agencie, który używa pliku, gdzie różni się tylko treść
pliku. Zmiany nie da się zastosować do pliku edytowanego po tym, jak ją
zaproponowano: porównaj obie wersje i edytuj plik ręcznie albo poproś asystenta
ponownie.

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
