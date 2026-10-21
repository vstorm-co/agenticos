---
source_sha: "9f2d6d57c080"
title: "Asystent tworzenia"
description: "Asystent tworzenia czyta, co ludzie ocenili negatywnie i jak kończyły się runy, i sugeruje zmiany w instrukcjach agenta, opisach narzędzi i skillach. O każdej decyduje człowiek."
---

# Asystent tworzenia { #authoring-assistant }

**Asystent tworzenia** ulepsza agentów na podstawie dowodów. Czyta, co ludzie
ocenili negatywnie i jak kończyły się runy, i sugeruje zmiany w instrukcjach
agenta, w nazwach i opisach jego narzędzi oraz w skillach, których używa. Nigdy
niczego nie zmienia sam: każda sugestia czeka na człowieka, przyjęta trafia do
[draftu](concepts.md), a nic nie dociera do nikogo, dopóki draft nie zostanie
opublikowany.

Robi trzy rzeczy:

- **Ulepsza** agenta: sugeruje zmiany na podstawie jego negatywnie ocenionych i
  nieudanych runów.
- **Sprawdza** Twoje zmiany: porównuje draft z opublikowaną wersją na tych samych
  dowodach i mówi, co zmiany poprawiają, czym ryzykują i co usunęły.
- **Ulepsza skill**: sugeruje nową treść na podstawie runów, które go otworzyły.

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
| Przyjąć, odrzucić albo cofnąć sugestię | Uprawnień edycji agenta |
| Zastosować albo odrzucić zmianę skilla | `skills:edit` na skillu |
| Sprawdzić evalami | Tego, czego wymaga [eval run](evals.md#access), i uprawnień edycji agenta |

Granty się liczą: członek z grantem edycji na jednym agencie może ulepszać tego
agenta.

## Gdy wsparcie AI jest wyłączone { #when-ai-assistance-is-off }

Gdy przełącznik **wsparcia AI** organizacji jest wyłączony, asystent nie działa:
Ulepsz, Sprawdź i ulepszanie skilla są odrzucane przez serwer, a konsola
pokazuje je jako wyłączone z linkiem do przełącznika. Sugestie, które już
czekają, nadal można przyjmować, odrzucać i cofać, a eval run, który nie
potrzebuje sędziego, nadal działa.
