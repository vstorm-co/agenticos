---
source_sha: "e2584b648791"
title: "Luki w wiedzy"
description: "Luki w wiedzy pokazują pytania, dla których agent nie znalazł w bazie wiedzy nic trafnego albo odpowiedział, że nie wie, pogrupowane w tematy, żeby było widać, jakiego dokumentu brakuje."
---

# Luki w wiedzy { #knowledge-gaps }

Wiele złych odpowiedzi nie wynika z instrukcji agenta. Baza wiedzy po prostu
nie zawiera odpowiedzi i żadna zmiana promptu tego nie naprawi. **Luki w
wiedzy** pokazują takie pytania: te, dla których agent przeszukał swoją
[bazę wiedzy](file-processing.md) i nie znalazł nic trafnego albo odpowiedział,
że nie wie. Są pogrupowane w tematy, z liczbą zadań każdego pytania i agentami, którzy je zadali.

Luka mówi, czego brakuje. Sama nigdy niczego nie dodaje do bazy wiedzy. Człowiek
pisze brakującą treść w temacie - może ją naszkicować model - i dodaje ją do
bazy wiedzy jako dokument. Wcześniej może zamienić pytania z tematu na przypadki
[datasetu](datasets.md), żeby ewaluacja pokazała, czy nowy dokument zmienił
odpowiedzi.

Edytor wybiera **Pomocników AI** na zakładce luk bazy wiedzy: własny
opublikowany klasyfikator i autor szkiców albo domyślnych agentów organizacji.
Pola to `gap_classifier_agent_id` i `gap_drafter_agent_id`; null przywraca domyślny
wybór, a pominięcie pola zachowuje dotychczasowy. Płatne wywołanie ponownie
sprawdza dostęp i rodzaj; usunięty wybór powoduje jawną odmowę. Bazy całego
wdrożenia korzystają z domyślnych agentów danej organizacji: ustawienie wspólne
nie może odwoływać się do prywatnego pomocnika jednej organizacji.

## Jak pytanie staje się luką { #how-a-question-becomes-a-gap }

Za każdym razem, gdy agent w trakcie runa przeszukuje bazę wiedzy, platforma
zapisuje to wyszukiwanie: zapytanie wysłane przez agenta, przeszukane bazy wiedzy,
liczbę zwróconych fragmentów i to, jak bardzo najbliższy fragment był podobny
do zapytania. Wyszukiwanie jest **chybione**, gdy nic nie zwróciło albo gdy
najbliższy fragment jest mniej podobny do zapytania niż
`KNOWLEDGE_GAP_MIN_SIMILARITY`.

| Ustawienie | Domyślnie | O czym decyduje |
|---|---|---|
| `KNOWLEDGE_GAP_MIN_SIMILARITY` | `0.30` | Podobieństwo kosinusowe, poniżej którego najbliższy fragment liczy się jako „nic trafnego”. To, ile punktów dostaje dobre dopasowanie, zależy od modelu embeddingów, więc przed zmianą sprawdź kilka własnych wyszukiwań |

Podobieństwo to podobieństwo kosinusowe wektora fragmentu do wektora
zapytania. To nie jest wynik rankingu: przy wyszukiwaniu hybrydowym albo
rozszerzaniu zapytania wynik rankingu jest połączoną pozycją i nic nie mówi o
tym, jak blisko był fragment.

Zapisywane jest każde wyszukiwanie, nie tylko chybione. Gdy zmienisz próg,
dotyczy on także wyszukiwań już wykonanych: luki, które czytasz, to zawsze
wyszukiwania poniżej bieżącego ustawienia.

Zapisywane są tylko wyszukiwania, które agent wykonuje w trakcie runa, i tylko
dla pytań zadanych przez ludzi: wyszukiwanie przez `/rag/search` w HTTP API,
podgląd na stronie bazy wiedzy, wyszukiwanie wykonane przez run ewaluacji ani
wyszukiwanie z testu wersji roboczej w Builderze nie są zapisywane. Z zapytania zachowywane jest pierwsze 1000 znaków.

## Odpowiedzi i komentarze { #answers-and-comments }

Wyszukiwanie może znaleźć fragment, a agent i tak nie znać odpowiedzi, a
czytelnik może ocenić odpowiedź łapką w dół, bo czegoś zabrakło. Samo
wyszukiwanie nie widzi żadnego z tych przypadków. **Sprawdź N odpowiedzi** na
zakładce Luki w wiedzy bazy wiedzy prosi model, żeby przeczytał pod tym kątem
jej ostatnie odpowiedzi. Przycisk jest dostępny, gdy
[wsparcie AI](governance.md#ai-assistance) jest włączone, i liczy odpowiedzi
jeszcze nieprzeczytane. Gdy przełącznik jest wyłączony, zakładka mówi, ile
odpowiedzi czeka, z linkiem do przełącznika dla tego, kto może go zmienić.

Model to **Knowledge gap classifier**, [agent systemowy](concepts.md#system-agents),
którego ma każda organizacja. Czyta każdą odpowiedź razem z pytaniem,
komentarzami osób, które oceniły ją łapką w dół, oraz instrukcjami i
[plikami kontekstowymi](context.md) wersji agenta, która jej udzieliła - tymi,
które może czytać osoba, która poprosiła o sprawdzenie - i wybiera jedną z
czterech możliwości, uzasadniając wybór jednym zdaniem:

| Werdykt | Kiedy |
|---|---|
| Agent nie wiedział | Odpowiedź mówi, dowolnymi słowami i w dowolnym języku, że agent nie wie albo nie znalazł informacji. Uzasadnione pytanie, którego agent nie podjął, bo nie miał na ten temat nic, należy tutaj, a nie do odmów |
| Brakowało informacji | Komentarz do oceny łapką w dół mówi, że informacji brakowało, była nieaktualna albo niepełna |
| Słuszna odmowa | Pytanie dotyczyło czegoś, na co nie pozwalają reguły albo przeznaczenie agenta - zignorowania jego instrukcji, przyznania wyjątku albo pomocy w czymś, do czego agent nie służy - i agent odmówił. To nie jest luka, a chybione wyszukiwania tego runa też przestają liczyć się jako luki - w tej bazie wiedzy i w innej, którą chybione wyszukiwanie też objęło, bo odmowa dotyczy prośby, a nie jednej bazy wiedzy |
| Brak luki | Wszystko inne: poprawna odpowiedź, odmowa czegoś, na co reguły pozwalają, komentarz o tonie, długości albo błędzie. Odpowiedź, która źle zastosowała politykę albo regułę, nie jest luką: reguła była, a to błąd do poprawienia - tak samo jak odpowiedź, której agent ma w instrukcjach albo plikach kontekstowych to, czego potrzebowała. Komentarz, że informacja jest nieaktualna, jest luką |

Klasyfikator ustawiony na
[przeszukiwanie bazy wiedzy](concepts.md#system-agent-spec) przeszukuje tę bazę,
zanim zdecyduje, więc odpowiedź, którą już ona zawiera, nie jest nazywana
brakującą.

Odpowiedź z jednym z dwóch pierwszych werdyktów staje się pytaniem w tematach
bazy wiedzy, grupowanym tak jak chybione wyszukiwanie. W temacie mówi, który
to z dwóch przypadków, zamiast podawać wyszukiwanie.

Odpowiedź jest czytana, gdy jej run z ostatnich 30 dni zakończył się i albo
przeszukał bazę wiedzy, albo działał na wersji agenta z nią powiązanej, oceniony
czy nie: odpowiedzi, w której agent nie wiedział, często nikt nie ocenia. Run, którego wyszukiwanie już było
chybione, też jest czytany, żeby słuszna odmowa usunęła jego chybienie z luk; w
przeciwnym razie nadal liczy się raz, jako to chybienie. Runy przez HTTP API nie zachowują
odpowiedzi, a runy ewaluacji, których pytania są odtwarzane albo generowane, nie
są nigdy czytane. Testy wersji roboczej w Builderze, runy delegowane i runy, których
autor nie ma już konta, też nie.

Sprawdzenie dotyczy jednej bazy wiedzy: to, co znajdzie, jest luką tylko tej
bazy. Odpowiedź, której run przeszukał dwie bazy wiedzy, jest czytana ponownie,
gdy sprawdza się tę drugą.

Sprawdzenie czyta do 100 odpowiedzi, po 20 na run klasyfikatora. Każdy run jest
sprawdzany względem budżetu klasyfikatora i organizacji, zanim zostanie
wywołany model, i jest widoczny w Aktywności pod osobą, która poprosiła:
wybierz **Każde źródło, z ewaluacjami**, żeby go zobaczyć. Każda
przeczytana odpowiedź jest zapamiętywana, niezależnie od werdyktu, więc za żadną
nie płaci się dwa razy. Odpowiedź z werdyktem „brak luki” jest czytana ponownie
dopiero po nowej ocenie łapką w dół z komentarzem. Sprawdzenie zatrzymuje się na
runie, który kończy się bez odpowiedzi, na przykład odrzuconym przez
wyczerpany budżet, i zachowuje to, co przeczytało.

Jedna baza wiedzy ma naraz tylko jedno sprawdzenie, uruchamiane jako zadanie w
tle w Admin → Background jobs: gdy worker przestanie działać w jego trakcie,
zadanie kończy się w tym miejscu, zamiast zniknąć bez śladu, a to, co
sprawdzenie przeczytało, pozostaje przeczytane.

Sesja ulepszania - [Ulepsz](authoring.md) uruchomione w tle - czyta w ten sam
sposób złe odpowiedzi, które znalazła, tylko te odpowiedzi i niezależnie od ich
wieku, i przypisuje każdą do grupy według jej werdyktów: brakująca wiedza, gdy w
bazie wiedzy brakowało treści, nic do poprawienia, gdy agent słusznie odmówił,
a w pozostałych przypadkach błąd agenta.

Odpowiedzi z brakującą wiedzą wypadają z tego, co czyta asystent tworzenia, a
ich braki od razu są grupowane w tematy. Sesja nie pisze szkicu żadnego z nich:
wymienia tematy, których brakuje w bazie wiedzy, a człowiek pisze szkice tych,
których potrzebuje, jak [niżej](#drafting-the-missing-content). Nic nie powstaje
jako szkic, dopóki nie poprosi o to człowiek, w sesji ani poza nią. Runy
ewaluacji nie są nigdy czytane, więc żaden przypadek zachowany do sprawdzenia
też nie.

## Tematy { #topics }

Chybione wyszukiwania są grupowane w **tematy** według znaczenia zapytania. Co
15 minut proces w tle bierze nowe chybione wyszukiwania każdej bazy wiedzy,
tworzy ich embeddingi modelem tej bazy wiedzy i umieszcza każde w najbliższym
temacie tej bazy albo zakłada nowy. Jedno przejście tworzy embeddingi dla
najwyżej 500 chybionych wyszukiwań na bazę wiedzy; reszta czeka na następne.
Baza wiedzy bez nowych chybionych wyszukiwań nie kosztuje żadnego wywołania
embeddingów.

Chybienie trafia do najbliższego tematu tylko wtedy, gdy jest do niego co
najmniej tak podobne jak `KNOWLEDGE_GAP_TOPIC_SIMILARITY`; inaczej zakłada nowy.

| Ustawienie | Domyślnie | Co decyduje |
|---|---|---|
| `KNOWLEDGE_GAP_TOPIC_SIMILARITY` | `0.55` | Podobieństwo kosinusowe, jakiego chybienie potrzebuje do tematu, żeby do niego dołączyć. Ile punktów dostają pytania o jedną sprawę, zależy od modelu embeddingów: w modelach `text-embedding-3` OpenAI zwykle od 0.5 do 0.7. Podnieś je, jeśli niepowiązane pytania trafiają do jednego tematu, obniż, jeśli jedna sprawa wciąż zakłada nowe. Wartość domyślna jest dobrana do tych modeli; model embeddingów podany pod endpointem zgodnym z OpenAI, na przykład bge albo e5, daje wysokie wyniki nawet niepowiązanym pytaniom, więc tam ją podnieś |

- Wyszukiwanie w dwóch bazach wiedzy staje się pytaniem w temacie każdej z nich.
- Baza wiedzy przeniesiona na inny model embeddingów zaczyna nowe tematy, bo
  wektorów z dwóch modeli nie da się porównać.
- Temat zachowuje tożsamość, gdy dochodzą do niego pytania, więc decyzja,
  którą o nim podjąłeś, nadal obowiązuje.

**Grupuj teraz** na karcie luk w wiedzy bazy wiedzy od razu uruchamia przejście
dla tej bazy wiedzy, zamiast czekać na harmonogram. Dopóki pytanie nie trafi do
tematu, karta liczy je jako jeszcze niepogrupowane.

## Czytanie luk { #reading-gaps }

Luki są widoczne w trzech miejscach:

- na karcie **Luki w wiedzy** bazy wiedzy: wszystkie jej tematy;
- na karcie **Luki w wiedzy** agenta: tylko pytania tego agenta, w bazach
  wiedzy, które możesz czytać;
- w widżecie **Luki w wiedzy**, dodawanym w **Dostosuj**: najczęściej zadawane
  tematy w całej organizacji i liczba tematów w każdej bazie wiedzy.

Temat należy do swojej bazy wiedzy, więc kto go czyta, wynika z tego, kto
czyta tę bazę wiedzy. Nie ma osobnego filtra według działu: dział widzi luki
baz wiedzy, które mu udostępniono.

Temat pokazuje, ile razy go zadano i przez ile osób, kiedy ostatnio, którzy
agenci go zadali, i do trzech jego pytań. Osoby pytające przez kanał są liczone
według konta czatu; wszyscy, którzy pytali anonimowo, przez widżet albo w runie
bez osoby za nim, liczą się jako jedna. Otwórz go, żeby zobaczyć najnowsze pytania: o co zapytała
osoba, czego szukał agent, jak blisko był najbliższy fragment i komentarz
każdego, kto ocenił odpowiedź łapką w dół. Pytanie odczytane z odpowiedzi mówi,
czy agent nie wiedział, czy czytelnik napisał, że brakowało informacji.

## Co zrobić z luką { #acting-on-a-gap }

Otwarty temat ma edytor: tytuł i treść w Markdownie, pustą albo wypełnioną
szkicem tematu. **Dodaj do datasetu** i **Odrzuć** są w menu **…** tematu, w
jego wierszu i w samym temacie.

| Działanie | Co robi |
|---|---|
| **Dodaj do** *bazy wiedzy* | Dodaje tytuł i treść do bazy wiedzy tematu jako dokument Markdown, tą samą ścieżką co wgranie pliku, i oznacza temat jako **uzupełniony** tym dokumentem. Jest odrzucane, dopóki jakaś informacja czeka na uzupełnienie albo dopóki coś może identyfikować osobę, a nie zostało to potwierdzone (zobacz [Dane osobowe](#personal-data)) |
| **Zapisz** | Zachowuje tytuł i treść przy temacie, nigdzie ich nie dodając |
| **Dodaj do datasetu** | Zamienia najnowsze pytania tematu (do 200) na przypadki wybranego datasetu, który możesz zmieniać, jako jedną nową wersję. Każdy przypadek to pytanie osoby, a odpowiedź agenta jest kontrprzykładem. Pytanie zadane przez HTTP API nie ma zapisanej odpowiedzi i jest pomijane |
| **Odrzuć** | Oznacza temat jako niewymagający treści. Odrzucony temat zatrzymuje należące do niego pytania, więc nie wraca jako nowy temat. **Otwórz ponownie** to odwraca |

Uzupełniony temat mówi, który dokument go uzupełnia, zatrzymuje należące do
niego pytania tak jak odrzucony i jest na liście **Uzupełnione**. Jeśli ten
dokument zostanie usunięty albo jego ingestia się nie powiedzie, temat znów
jest otwarty; odrzucony temat trzeba otworzyć ponownie, zanim powstanie dla
niego treść. **Otwórz ponownie** na
uzupełnionym temacie zostawia dokument w bazie wiedzy. Dokument zapisuje temat,
z którego go dodano, i to, kto go dodał, a każde dodanie trafia do dziennika
audytu jako `knowledge_gap.content_added`.

Dokument można też wgrać samodzielnie albo dodać do źródła, z którego baza
wiedzy się synchronizuje. Po dodaniu treści uruchom ewaluację na datasecie.
Przypadki, które nie przechodziły z powodu brakującej wiedzy, powinny teraz
przejść.

## Szkic brakującej treści { #drafting-the-missing-content }

**Napisz szkic** (Draft) w otwartym temacie prosi model o napisanie
fragmentu albo wpisu FAQ, którego brakuje w bazie wiedzy. Przycisk pokazuje
najwyższy koszt jednego szkicu. To jeden run
**autora szkiców luk** (Knowledge gap drafter),
[agenta systemowego](concepts.md#system-agents), którego ma każda organizacja. Agent widzi 20 najnowszych pytań tematu: o co
zapytała każda osoba, czego agent szukał i co znalazł, jaką odpowiedź dostała
osoba i komentarz zostawiony przy ocenie łapką w dół. To, co identyfikuje
ludzi, jest najpierw usuwane (zobacz [Dane osobowe](#personal-data)); z tego,
co znalazło wyszukiwanie, czyli z własnej treści bazy wiedzy, usuwane są tylko
dane osobowe, więc jej liczby zostają. To, co znalazło, jest zawsze wynikiem
samego wyszukiwania w bazie wiedzy, nigdy tego, co inne narzędzie zwróciło dla
tych samych słów. Agent
widzi też [pliki kontekstowe](context.md), które agenci tematu czytają w swoich
opublikowanych wersjach, te, które możesz czytać, żeby szkic trzymał się reguł,
których agenci już się trzymają. Widzi też, co zwraca wyszukiwanie w bazie
wiedzy dla najwyżej trzech z tych pytań w chwili pisania szkicu, więc widzi
dokument dodany, odkąd je zadano, a autor szkiców ustawiony na
[przeszukiwanie bazy wiedzy](concepts.md#system-agent-spec) przeszukuje też tę
bazę. Tak czy inaczej szkic nie powtarza tego, co już mówi jakiś dokument.

Szkic powstaje w tle, jako ty, z twoim dostępem takim, jaki jest w chwili jego
pisania. Temat mówi **Piszę szkic…** (Drafting…), dopóki szkic nie jest gotowy,
a otwarta strona pokazuje go bez przeładowania; ponowna prośba w tym czasie nic
więcej nie uruchamia. Szkic, którego nie udało się napisać, bo budżet się
wyczerpał albo w międzyczasie wyłączono wsparcie AI, mówi o tym, z przyciskiem
**Spróbuj ponownie** (Try again). Szkic napisany z pytań jednej osoby też to
mówi: sprawdź go, wiedząc, że opiera się na tym, o co pytała jedna osoba.

Szkic wypełnia edytor tematu, z odnośnikiem do swojego runa. Możesz go
skopiować jako Markdown, a do bazy wiedzy trafia dopiero wtedy, gdy ktoś go
doda. Agent nie zna faktów twojej firmy: tam, gdzie odpowiedź wymaga
liczby, daty albo reguły, wpisuje `{{what to fill in}}`, a edytor wymienia każde
takie miejsce, dopóki nie zostanie zastąpione.

Gdy plik kontekstowy albo dokument już odpowiada na te pytania, autor szkiców luk to
mówi, a temat podaje to źródło: zamiast dodawać treść, odrzuć temat.
**Napisz szkic od nowa** (Redraft) zastępuje szkic. Gdy po napisaniu szkicu do
bazy wiedzy zostanie dodany dokument, szkic mówi, że baza wiedzy zmieniła się
po nim: może powtarzać nowy dokument albo mu przeczyć, więc **Napisz szkic od
nowa** pisze go ponownie według tego, co baza wiedzy zawiera teraz. Kto może edytować autora szkiców luk, znajdzie przy szkicu **Edytuj instrukcje
autora szkiców luk**, a samego autora szkiców luk w sekcji **Agenci systemowi** na stronie Agents.

Szkic podaje swoje źródła: dokumenty bazy wiedzy, na których się opiera,
pliki kontekstowe, których się trzyma, i pytania tematu, na które odpowiada.
Każde źródło jest weryfikowane przed zapisaniem szkicu - dokument musi należeć
do bazy wiedzy tematu, pytanie musi być pytaniem tematu, a plik kontekstowy
takim, który możesz czytać - a to, które nie przejdzie, jest pomijane, nigdy
pokazywane, i liczone przy szkicu. Zachowywanych jest najwyżej 12 źródeł.
Źródło usunięte później przestaje być pokazywane.

Zmieniony w edytorze szkic staje się twoją treścią: jego run i źródła przestają
być pokazywane, bo to, na co powołał się model, już za nim nie przemawia.

Szkic to run modelu jak każdy inny. Jest odrzucany, gdy organizacja wyłączyła
[wsparcie AI](governance.md#ai-assistance), a jest ono wyłączone, dopóki nie
włączy je ktoś z `org:settings`; do tego czasu temat to mówi, z odnośnikiem do
przełącznika dla tego, kto może go zmienić. Przed wywołaniem modelu sprawdzany
jest budżet agenta i organizacji, a jego koszt widać w Aktywności. Grupowanie
pytań w tematy nie prosi modelu o pisanie, więc działa niezależnie od
przełącznika.

## Dostęp { #access }

Temat składa się z pytań ludzi, więc czytanie luk wymaga `runs:view`, czyli
uprawnienia, które pozwala czytać w Aktywności każdy run w organizacji. Członek
bez niego nie widzi karty ani widżetu, a API mu odmawia.

| Żeby | Potrzebujesz |
|---|---|
| Czytać luki bazy wiedzy | `runs:view` i `collections:view` na tej bazie wiedzy |
| Czytać luki agenta | `runs:view` i `agents:view` na agencie; tematy baz wiedzy, których nie możesz czytać, są pomijane |
| Odrzucić, otworzyć ponownie albo pogrupować | `runs:view` i `collections:edit` na bazie wiedzy, z twojej roli albo z grantu edycji na niej |
| Dodać temat do datasetu | `runs:view` i `datasets:edit` na datasecie |
| Napisać szkic tematu | `runs:view`, `collections:edit` na bazie wiedzy i `agents:run` na autor szkiców luk |
| Napisać, zapisać albo dodać treść tematu | `runs:view` i `collections:edit` na bazie wiedzy, z twojej roli albo z grantu edycji na niej |
| Sprawdzić odpowiedzi | `runs:view`, `collections:edit` na bazie wiedzy i `agents:run` na Knowledge gap classifier |

Sprawdzenie odpowiedzi działa później na twojej roli, więc uruchamia się je tylko
osobiście: nie przez klucz API i nie wtedy, gdy administrator się pod ciebie
podszywa.

Baza wiedzy, agent, temat albo dataset, do którego nie masz dostępu, odpowiada „nie
znaleziono”; tak samo ten z innej organizacji. Zobacz
[Uprawnienia](permissions.md).

## Dane osobowe { #personal-data }

Zapisane wyszukiwanie to treść użytkownika: agent sformułował je z tego, o co
ktoś zapytał. Jest usuwane razem z runem, w którym powstało, i z rozmową, z
której pochodzi. Usunięcie osoby usuwa wyszukiwania wykonane podczas
odpowiadania jej, także w runach bez rozmowy. Jej eksport je zawiera.

Zapisywane jest każde wyszukiwanie, trafione i chybione, więc zmieniony próg
działa także na wyszukiwania już wykonane. Żadne nie przeżyje swojego runa:
klasa runów w [retencji](governance.md#retention) usuwa je razem z nim.

Temat nie kopiuje pytań. Jego nazwa, przykłady i liczba są czytane z
wyszukiwań, które jeszcze zawiera, więc gdy te wyszukiwania zostaną usunięte,
tematowi nic nie zostaje i następne przejście grupowania usuwa go razem ze
szkicem.

Szkic to jedyny tekst, który temat przechowuje, napisany przez model albo
człowieka. Poświadczenia w nim są redagowane przed zapisaniem. Pisanie szkicu
wysyła pytania, odpowiedzi i komentarze do dostawcy modelu autora szkiców luk, po
usunięciu tego, co identyfikuje ludzi: adresów e-mail, numerów telefonów, kart
i rachunków bankowych oraz każdej liczby albo kodu z co najmniej czterema
cyframi albo z trzema cyframi i literą, jak numer zamówienia. Wartość taka jak
„30 dni” albo „$500” zostaje. Nic, co pisze człowiek, nie jest zmieniane. Zobacz
[Ochrona danych](data-protection.md#where-personal-data-lives).

Usunięcie osoby usuwa szkice, które model napisał na podstawie jej pytań.
Treść napisana albo zmieniona przez człowieka zostaje, tak jak dodany z niej
dokument.

Dokument dodany z tematu trafia do każdego, komu odpowiadają agenci jego bazy
wiedzy, więc przed dodaniem treść jest sprawdzana pod kątem danych osobowych i
każdej takiej liczby albo kodu, które powtarza z pytań, odpowiedzi albo
komentarzy tematu, chyba że podaje je też plik kontekstowy agentów tematu. To,
co zostanie znalezione, jest pokazywane w temacie, a dodanie czeka, aż to
potwierdzisz. Wpis audytu zapisuje, ile oznaczono i że to potwierdzono, ale nie
co. Dokument zostaje, gdy zostanie usunięty temat, osoba, która go dodała, albo
osoba, której pytanie go ukształtowało: ktoś sprawdził i potwierdził jego treść.

Pytanie odczytane z odpowiedzi jest przechowywane tak samo jak wyszukiwanie:
zawiera pytanie osoby i znika razem ze swoim runem i rozmową. Sprawdzanie
odpowiedzi wysyła pytania, odpowiedzi i komentarze do ocen łapką w dół do
dostawcy modelu klasyfikatora.

Z każdej przeczytanej odpowiedzi zapamiętywany
jest werdykt, run klasyfikatora i jego jednozdaniowe uzasadnienie, które znika
razem z odpowiedzią i jest czyszczone, gdy osoba pytająca zostanie usunięta.
Uzasadnienie widzi tylko ktoś, kto może oglądać agenta, który odpowiedział.
Może ono wymienić instrukcje agenta albo jeden z jego plików kontekstowych - z
nazwy, nigdy z treści - także komuś, kto nie może czytać tego pliku. Odpowiedź,
której run już nie istnieje, nie mówi, kto pytał, więc jej uzasadnienie zostaje,
dopóki nie zniknie rozmowa odpowiedzi.

## Czego luki jeszcze nie wykrywają { #limits }

Odpowiedzi są czytane tylko wtedy, gdy ktoś je sprawdzi, i tylko z ostatnich 30
dni. Runy przez HTTP API nie zachowują odpowiedzi, więc zadane tam pytanie staje
się luką tylko wtedy, gdy jego wyszukiwanie było chybione. Odpowiedź oceniona
łapką w dół bez komentarza jest czytana pod kątem tego, co powiedział agent, a
nie samej oceny.

Imiona i nazwiska nie są usuwane z tego, co czyta autor szkiców luk, ani oznaczane w
treści do dodania: nic tutaj nie rozpoznaje imion i nazwisk. Sprawdź pod tym
kątem szkic, zanim go dodasz.
