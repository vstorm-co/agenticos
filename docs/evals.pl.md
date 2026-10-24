---
source_sha: "030a32879fab"
title: "Runy ewaluacji"
description: "Run ewaluacji odpowiada na każdy przypadek datasetu wersją agenta albo jego wersją roboczą, ocenia każdą odpowiedź i porównuje wynik z baseline'em."
---

# Runy ewaluacji { #eval-runs }

**Run ewaluacji** sprawia, że agent odpowiada na każdy przypadek wersji
[datasetu](datasets.md), ocenia każdą odpowiedź tak, jak mówi
[ocenianie](datasets.md#scoring) datasetu, i zachowuje to, co się stało.
Odpowiada na pytanie, które naprawdę ma osoba edytująca agenta: czy ta zmiana
poprawiła agenta, pogorszyła go, czy nic nie zmieniła - i ile to kosztowało.

Run składa się z czterech wyborów: **agent** i to, co z niego się uruchamia
(opublikowana wersja albo wersja robocza w obecnym stanie), **wersja datasetu**,
**środowisko**, którego testowych połączeń używają przypadki, i opcjonalnie
**kilka modeli** obok siebie. W tym samym runie może też działać **baseline** -
wcześniejsza wersja - żeby obie strony trafiły na tego samego providera tego
samego dnia.

## W konsoli { #in-the-console }

Zakładka **Ewaluacje** (Evals) agenta otwiera się wykresem liniowym jego odsetka zaliczeń
run po runie, od najstarszego po lewej, z linią na każdy dataset, każdą z inną
kreską. Punkt jest czerwony, gdy run zepsuł przypadki, zielony, gdy je naprawił,
bursztynowy, gdy zrobił jedno i drugie, a pusty dla wersji roboczej; najechanie na punkt
mówi, co uruchomiono, z czym porównano i kiedy, a kliknięcie otwiera run.

Oś podpisuje każdy punkt tym, co uruchomiono i kiedy - godziną dla dzisiejszego
runu, datą dla wcześniejszych. Powyżej 12 runów pod wykresem pojawia się zakres,
otwarty na ostatnich 12; przeciągnij jego uchwyty albo przesuń je strzałkami,
żeby zobaczyć więcej lub mniej.

Pod wykresem są jego runy, pogrupowane po datasecie, każdy z tym, co testowano
względem czego, z werdyktem - **Psuje: 2** (Breaks 2), **Gorszy ogólnie ·
zepsute: 4** (Worse overall · 4 broke), **Pierwszy wynik** (First result) albo
**W toku** (Pending) - i odsetkiem zaliczeń każdego modelu, a po najechaniu
kursorem - z odsetkiem pierwszych odpowiedzi.

**Uruchom ewaluację** (Run evals) otwiera dialog startu od razu na oczywistej
odpowiedzi: wersja robocza względem bieżącej opublikowanej wersji, gdy się od
niej różni, sama opublikowana wersja, gdy się nie różni, i sama wersja robocza
dla agenta, którego nikt nie opublikował. Dataset, na którym agent był ostatnio
mierzony - albo jedyny, jaki istnieje - jest już wybrany; środowisko, nagrania
i powtórki są pod **Zaawansowane** (Advanced). Koszt jest wyliczany, gdy pola
się ustalą, i mówi, co ocenia odpowiedzi oraz ile zostanie potem w budżecie
agenta i organizacji; run startuje dopiero z przycisku, który podaje tę kwotę.
**Wersja robocza różni się od vN** (Draft differs from vN) na stronie agenta -
vN to najnowsza opublikowana wersja, a gdy strażnicy produkcji trzymają ją na
starszej, drugi znaczek mówi na której, na przykład „produkcja na v1 (czeka na
ewaluacje)” - ma przycisk **Przetestuj wersję roboczą** (Test draft), który
otwiera ten sam dialog. Dialog publikacji mówi, co znalazł ostatni run wersji
roboczej - [sprawdzenie sugestii asystenta](authoring.md#check-with-evals)
liczy się, gdy zostaną przyjęte - albo że nie testowano jej od ostatniej
zmiany, albo że test, który miała, jest nieaktualny, nie wstrzymując publikacji.

Strona runa otwiera się jego werdyktem w kilku zdaniach - przypadki, które
kandydat psuje albo naprawia za każdym razem, gdy jest o nie pytany, jeden z
nich zacytowany z liczbą prób, które to powtórzyły, czy ogólnie jest lepszy,
czy gorszy, gdy potwierdzone zmiany pozwalają to stwierdzić, i odsetek zaliczeń
przed i po - razem z tym, co zrobić dalej: zobaczyć, co zmieniło się między
obiema wersjami (**Historia** (History) otwiera się na tym porównaniu, względem
speca, który run testował, a nie wersji roboczej w jej obecnym stanie), pokazać
przypadki, które się zepsuły, wrócić do zakładki **Budowa** (Build) albo
opublikować wersję roboczą.

**Opublikuj** (Publish) jest główną akcją tylko wtedy, gdy nie potwierdzono
żadnej regresji i żaden przypadek kandydata nie został bez odpowiedzi ani bez
oceny, a run wersji roboczej, która od tego czasu się zmieniła, proponuje
zamiast tego **Testuj ponownie** (Test again). Gdy run odpowiada, strona mówi,
ile pierwszych odpowiedzi już jest, a porównanie czeka na obie strony.
Odpowiedzi, których sędzia nie zdołał ocenić, mówią dlaczego i nie liczą się ani
jako zaliczone, ani jako niezaliczone, a **Oceń ponownie** (Grade again) w
nagłówku ocenia je ponownie bez pytania agenta, dla każdego, kto może uruchamiać
dataset.

Pod werdyktem są obie strony obok siebie, to, jak wypadają w porównaniu, i
przypadki - każdy wiersz z kropką zaliczenia lub niezaliczenia dla każdej
strony, filtrowane po wyniku lub tagu, każdy otwierający się na to, czego
przypadek oczekuje, oraz na odpowiedzi, wywołania i uzasadnienia oceniających
każdej strony. Wybrany tag zawęża do siebie strony, zmiany i przypadki; werdykt
nadal obejmuje wszystkie przypadki.

Gdy są już powtórki, run wysyła do [kolejki przeglądu](datasets.md#review)
datasetu to, za czym może się opowiedzieć - każdą potwierdzoną regresję i każdą
odpowiedź, przy której ocenie jego sędzia zawiódł, po jednej na przypadek i
agenta - i podaje, ile ich jest (`routed_to_review`).
[Sprawdzenie propozycji asystenta](authoring.md#check-with-evals) samo z siebie
nie wysyła nic, bo nic nie zostało przyjęte. Pominięty sędzia nie wysyła nic:
jego odpowiedzi czekają na stronie runu na **Oceń ponownie**.

Gdy wysyłka
zostanie odrzucona, run i tak się kończy, a jego strona mówi dlaczego
(`routing_error`). **Wyślij niezaliczone przypadki do przeglądu**
(Send failed cases to review) wysyła resztę niezaliczonych odpowiedzi jednej
strony, dla każdego, kto może edytować dataset, a przypadek, którego ocenę osoba
uchyliła,
jest oznaczany jako
poprawiony.

W obu przypadkach odpowiedź zajmuje miejsce starszej odpowiedzi tego samego
przypadku i agenta, która jeszcze czeka, a ta opuszcza kolejkę bez decyzji - run
podaje, ile ich było, jako `routed_replacing` - a odpowiedź starsza od
czekającej nie jest wysyłana. Odpowiedź innego agenta na ten przypadek czeka
obok.

Własna zakładka **Ewaluacje** datasetu wymienia każdego mierzonego na nim
agenta, każdego ze swoim trendem i runami, a **Uruchom ewaluację** w jego
nagłówku otwiera dialog startu na tym datasecie i pyta, którego agenta testować.

Karta **Runy ewaluacji** (Eval runs) na dashboardzie wymienia ostatnie runy
organizacji z ich agentem i werdyktem. Przypadki ewaluacji i ocenianie sędziego
nie wchodzą do żadnej innej liczby na dashboardzie, a **Aktywność** (Activity)
je ukrywa, chyba że jej filtr powierzchni prosi o wszystkie powierzchnie albo
tylko o ewaluacje. Lista Aktywności pokazuje, o co zapytano każdy run - jego
pierwszą wiadomość użytkownika albo pytanie przypadku ewaluacji, a dla runa
sędziego to, co ocenił - żeby run dało się znowu znaleźć i zrobić z niego
przypadek. Przypadek ewaluacji otwiera tam swój run ewaluacji na tym przypadku,
a **Zobacz, co widział model** (See what the model saw) przypadku otwiera to, co
dostał jego model.

**Zobacz wszystko** na tej karcie otwiera **Runy ewaluacji** pod `/evals`: każdy
run ewaluacji, który możesz zobaczyć, ze wszystkich agentów, od najnowszego,
stronami. Gdy żadnego nie ma, strona mówi, czym jest ewaluacja i gdzie ją
uruchomić.

## Uruchamianie runa { #starting-a-run }

Uruchomienie to dwa wywołania, żeby nic nie zostało wydane, zanim ktoś zobaczy,
ile to będzie kosztować.

```text
POST /api/v1/agents/{agent_id}/eval-runs/estimate   the estimate, nothing written
POST /api/v1/agents/{agent_id}/eval-runs            the same body; starts the run
```

Body wskazuje dataset (`dataset_id`, `dataset_version`), kandydata
(`candidate: "version"` z opcjonalnym `version` albo `candidate: "draft"`),
`environment_id`, `model_profile_ids` do porównania oraz `paired_baseline`.
Szacunek to średni koszt runa agenta na każdym modelu, liczony z jego ostatnich
zakończonych runów, razy liczba przypadków, plus jedno wywołanie sędziego na
przypadek, gdy dataset ocenia sędzia, a wsparcie AI jest włączone.

Wsparcie AI jest wyłączone w organizacji, dopóki ktoś z `org:settings` je
nie włączy. Gdy jest wyłączone, sędzia nie działa: przypadek rozstrzygają jego
checki i oczekiwane wywołania narzędzi, kryteria sędziego są zapisywane jako
pominięte, a szacunek nie liczy sędziego.

Agent bez historii na danym modelu jest szacowany jako typowy przypadek -
`EVAL_FALLBACK_INPUT_TOKENS` na wejściu, `EVAL_FALLBACK_OUTPUT_TOKENS` na
wyjściu - według ceny samego modelu, albo na `EVAL_FALLBACK_CASE_COST_USD` dla
modelu, którego ceny nic nie zna, a szacunek mówi, że to zgrubne zgadywanie
(`basis: "fallback"`). Sędzia bez historii jest wyceniany tak samo, na modelu,
który wskazuje jego opublikowany spec; szacunek ostrzega, gdy to model, który
jest testowany, a strona runa - gdy nim był. Koszt baseline'u wchodzi do sumy,
chyba że użyty zostanie niedawny pasujący baseline - wtedy jego pierwsze
odpowiedzi nic nie kosztują, a szacunek wskazuje run, z którego pochodzą.

### Budżet, który zostaje { #the-budget-it-leaves }

Ewaluacja wydaje z tych samych miesięcznych budżetów co ruch produkcyjny: z
limitu agenta i z limitu organizacji. Nie ma osobnego budżetu na ewaluacje. Duży dataset
może więc zostawić produkcję bez budżetu do końca miesiąca, dlatego szacunek
pokazuje, ile każdy limit zachowa po wydaniu sumy przez run:
`agent_after_usd` i `org_after_usd`.

Uruchomienie jest odrzucane z `402`, zanim cokolwiek zostanie zapisane, gdy suma
przekracza to, co zostało w którymkolwiek limicie. Powtórki potwierdzające
(niżej) nie wchodzą do tego sprawdzenia, bo dotyczą tylko przypadków, które się
odwróciły; szacunek pokazuje, ile najwyżej mogą dodać - gdy odwróci się każdy
przypadek, powtórzony po każdej stronie, łącznie z wykorzystanym baseline'em -
jako `rerun_ceiling_usd`, który run zachowuje, żeby run, który wydał więcej, niż szacowano, mówił
dlaczego. Każdy przypadek i tak jest sprawdzany względem obu limitów przed
każdym żądaniem do modelu, jak każdy run, a przypadek, który trafi na limit,
zatrzymuje cały run ewaluacji jako `budget_exceeded`.

### Co jest odrzucane { #what-is-refused }

Run, który nikomu niczego by nie powiedział, jest odrzucany, zanim zostanie
oszacowany:

- wersja datasetu bez przypadków;
- ocenianie bez wymaganego oceniającego, który mógłby rozstrzygnąć którykolwiek
  przypadek wersji - bez checku do zastosowania, bez oczekiwanego wywołania
  narzędzia i bez sędziego. Gdy sędzia jest jedynym oceniającym, a wsparcie AI
  jest wyłączone, odmowa to mówi: sędzia potrzebuje wsparcia AI, które jest w
  tej organizacji wyłączone, więc włącz je w ustawieniach organizacji albo dodaj
  check;
- agent, który nigdy nie został opublikowany, a poproszono o wersję - uruchom
  zamiast tego jego wersję roboczą;
- baseline dla pierwszej wersji, przed którą nic nie ma.

Wersja, w której tylko część przypadków nie ma czym ich ocenić, nadal się
uruchamia, a estymata najpierw je liczy (`ungraded_cases`): okno startu, check
sugestii i okno suity mówią „1 przypadek nie ma czym go ocenić. Wynik będzie nierozstrzygnięty.”

### Sprawdzanie sugestii { #checking-suggestions }

[Asystent tworzenia](authoring.md#check-with-evals) uruchamia runy ewaluacji, żeby
sprawdzić to, co sugeruje: wersję roboczą z naniesionymi oczekującymi
sugestiami, obok
opublikowanej wersji. Taki run pomija przypadki wzięte z rozmów, z których
wzięły się sugestie, i podaje ich liczbę, więc próba mniejsza od datasetu sama
wyjaśnia, skąd się wzięła.

## Jako co działa każdy przypadek { #what-each-case-runs-as }

Każdy przypadek to zwykły run agenta z powierzchnią `eval`. Jest sprawdzany
względem budżetów przed każdym żądaniem do modelu, a jego koszt jest
zapisywany. Nie wchodzi do liczb użycia na dashboardzie, które liczą tylko
produkcję i podają obok koszt ruchu ewaluacji (`cost.eval_usd`), a historia
runów go pomija, gdy się o to poprosi (`?exclude_surface=eval`). Odczyt
pojedynczego runa wskazuje run ewaluacji i przypadek, na który odpowiadał
(`eval_case`), czytającemu, który może widzieć dataset. Działa jako osoba, która
uruchomiła ewaluację, z jej obecną rolą, i nie czyta ani nie zapisuje jej osobistej pamięci.

Każdy przypadek działa **w izolacji**, jak opisują [Środowiska](environments.md):
narzędzie z testowym połączeniem w środowisku runa działa na nim, narzędzie, o
którym wiadomo, że tylko czyta, działa na zwykłym połączeniu, a wszystko, co
zapisuje bez testowego połączenia, nie jest wykonywane - wywołanie i jego
argumenty są zachowywane jako zamierzone wywołanie, które ocenianie trajektorii
nadal ocenia.

Na przypadek wzięty z konwersacji można odpowiadać **z nagrania** runa, z
którego pochodzi (`from_recordings`): wywołanie zgodne z nagraniem dostaje
nagrany wynik, a niezgodne jest wstrzymywane i oznaczane jako rozbieżne.
Przypadek bez użytecznego nagrania działa w izolacji bez niego.

### Wersja robocza nigdy nie liczy się jako wersja { #a-draft-is-never-counted-as-a-version }

Wersja robocza przechodzi tą samą ścieżką, z dwiema różnicami. Najpierw jest
sprawdzana względem własnego dostępu osoby uruchamiającej - wszystkiego, co
sprawdziłaby publikacja - bo wersja robocza nigdy nie była walidowana przy
zapisie. A jej runy nie są przypisywane do żadnej wersji: nie pojawiają się w
użyciu wersji, a liczby wersji nigdy nie obejmują odpowiedzi, których udzieliła
wersja robocza.

Wersja robocza jest kopiowana przy starcie runa, więc każdy przypadek odpowiada na tę
samą treść, nawet jeśli ktoś dalej edytuje.

## Działanie i anulowanie { #running-and-cancelling }

Run wykonuje się w tle, jako osobne zadanie workera, więc przetrwa restart API.
Przypadki działają po kilka naraz: najwyżej `EVAL_RUN_CONCURRENCY` na run i
najwyżej `EVAL_ORG_CONCURRENCY` we wszystkich runach ewaluacji organizacji, więc
dataset z 500 przypadkami nie zajmie wszystkich żądań, na które provider
pozwala organizacji.

Anulowanie (`POST /api/v1/eval-runs/{id}/cancel`, przez osobę, która run
uruchomiła, albo każdego, kto może edytować agenta) zatrzymuje to, co się nie
zaczęło: przypadki, które już działają, kończą się i są zachowywane, a żaden
inny się nie zaczyna. Anulowanie zadania runu w **Admin** → **Background jobs**,
zanim przejął je worker, anuluje run tak samo, w ciągu kilku sekund.

Run, którego worker nie może dokończyć - bo na przykład w trakcie stracił bazę -
od razu kończy się jako `failed`, tak jak run agenta: jego działające przypadki
kończą się błędem, pozostałe są pomijane, a strona runu mówi, że zatrzymał się
na błędzie i trzeba go uruchomić ponownie. Run nie jest wznawiany. Tak samo od
razu kończy się jako `failed` run, którego zadaniu skończył się czas albo którego
worker został zamknięty w trakcie.

Worker może też umrzeć bez słowa. Worker działającego runu co
`EVAL_HEARTBEAT_SECONDS` daje znać, że żyje; run, którego worker milczy i którego
przypadki nie ruszyły się przez `EVAL_ABANDONED_AFTER_MINUTES`, kończy się błędem
w sweepie, który worker uruchamia co minutę i który zwalnia też jego miejsca.
Worker, któremu heartbeaty padają tak długo - na maszynie zbyt obciążonej, by
sięgnąć bazy - kończy się tak samo, choć jeszcze pracuje, i run trzeba uruchomić
ponownie.

Run w kolejce nie ma jeszcze workera, który dawałby znać, że żyje. Może czekać na
wolnego workera albo za wstrzymanym rodzajem zadań tak długo, jak jego zadanie
jest w kolejce; sweep kończy go błędem dopiero, gdy nie zostało żadne zadanie,
które by go uruchomiło. Przypadek, który martwy worker zostawił jako działający
w runie już zakończonym, kończy się błędem po tym samym
`EVAL_ABANDONED_AFTER_MINUTES`. Działający przypadek liczy się do
`EVAL_ORG_CONCURRENCY`, dopóki się nie skończy, także po anulowaniu jego runu.

Dopóki run czeka w kolejce albo działa, nie da się usunąć środowiska, które
wskazuje, ani profilu modelu, na którym działa któraś z jego stron: pozostałe
przypadki odpowiadałyby na połączeniach produkcji albo na innym modelu niż
przypadki przed nimi.

## Wyniki { #results }

Każda próba zachowuje odpowiedź, wykonane wywołania - każde oznaczone jako
wykonane, zablokowane, odtworzone albo rozbieżne - werdykt i uzasadnienie
każdego oceniającego, swój koszt, tokeny i latencję. Odpowiedź i wywołania są
kopiowane do wyniku, bo run przypadku nie ma konwersacji, w której trzymałby
transkrypt.

Każde ramię runa jest podsumowane na dwóch osiach i per tag:

| Oś | Mierzy |
|---|---|
| Jakość | Odsetek zaliczonych wśród rozstrzygniętych przypadków, każdy według tego, jak wypadła większość jego prób; obok odsetek pierwszych odpowiedzi; ile zostało nierozstrzygniętych i dlaczego |
| Efektywność | Koszt na zaliczony przypadek, tokeny na przypadek i latencję w p50 i p95 |

Każda próba kończy się na jeden z czterech sposobów (`state` w próbie):

- **zaliczona** albo **niezaliczona** według oceny;
- również **niezaliczona**, gdy run agenta się nie powiódł - narzędzie rzuciło
  wyjątek, przekroczył limit kroków, zapętlił się, zatrzymał go guardrail,
  provider odrzucił żądanie - co od razu oblewa suitę, nawet gdy ponowne próby
  tego przypadku przejdą;
- **niekompletna**, gdy provider zawiódł mimo ponowień (błąd 5xx, 408 albo 429,
  albo brak odpowiedzi), oceniający rzucił wyjątek, run anulowano albo skończył
  się budżet, albo próby wyszły na remis;
- **nieoceniona**, gdy nic nie ocenia odpowiedzi - nie pasuje żaden wymagany
  oceniający albo mógłby tylko sędzia, a wsparcie AI jest wyłączone.

Żaden z dwóch ostatnich stanów nie jest zaliczeniem; podsumowanie liczy je
osobno (`incomplete`, `ungraded`).

Nagłówek runu mówi „Odsetek zaliczeń 67% · 1 z 3 przypadków nierozstrzygnięty” i nazywa wynik
nierozstrzygniętym, dopóki każdy przypadek nie ma werdyktu. Provider, który
odrzuca dane uwierzytelniające, jest nazwany wprost, a strona, której każda
odpowiedź skończyła się tym samym błędem, mówi to zamiast werdyktu. Przypadek,
na którym agent się wysypał, a baseline przeszedł, jest regresją jak każda inna,
pokazaną z jej błędem.

Odpowiedź, której sędzia nie zdołał ocenić albo którą pominął, jest **nieoceniona**: run wymienia te oceny jako
`ungraded_score_ids`, a ponowne ocenienie
(`POST /api/v1/datasets/{id}/scores/rescore`) czyta odpowiedź zachowaną w
próbie, zamiast pytać agenta. Werdykt osoby w
[kolejce przeglądu](datasets.md#review) zastępuje wynik oceniających dla tego
przypadku, a liczby runa idą za nim.

Zakończony run zachowuje werdykt, liczniki i odsetki zaliczeń swojego
pierwszego kandydata jako `outcome`, więc lista odczytuje je bez ponownego
porównywania każdego runa. Jest porównywany ponownie, gdy od tego czasu osoba
rozstrzygnęła którąś z ocen, na których się opiera, albo którąś oceniono
ponownie.

```text
GET /api/v1/agents/{agent_id}/eval-runs      an agent's runs, newest first; ?draft=current
GET /api/v1/datasets/{dataset_id}/eval-runs  a dataset's runs over the agents the reader may see
GET /api/v1/eval-runs/{id}                   one run, with each arm's summary and its outcome
GET /api/v1/eval-runs/{id}/cases             cases, what each expects, and every attempt;
                                             ?outcome=, ?tag=, ?arm_id=, ?case_id=
GET /api/v1/eval-runs/{id}/comparison        a candidate arm against its baseline
GET /api/v1/eval-runs/{id}/arms/{arm}/spec   the spec one side ran; needs agents:edit
```

`?draft=current` zostawia runy, które testowały wersję roboczą w obecnym stanie -
ten sam spec, niezależnie od kolejności, w jakiej zapisano jego klucze, a wśród
nich sprawdzenie sugestii, które potem przyjęto - i to właśnie czyta dialog
publikacji. `?draft=earlier` zostawia runy, które testowały inną wersję roboczą
od opublikowania najnowszej wersji - sprawdzenie dopiero wtedy, gdy przyjęto
którąś z jego sugestii: test, od którego wersja robocza już odeszła. Sprawdzenie
mierzone względem samej wersji roboczej nie liczy się w żadnym z nich.

Kryterium sędziego może dotyczyć wszystkich przypadków albo tylko przypadków z dowolnym wybranym tagiem. W **Grading** wybierz tagi i sprawdź liczbę objętych przypadków; przypadek z kilkoma pasującymi tagami liczy się raz. Niepasujące kryteria są całkowicie pomijane, więc nie mogą oblać przypadku ani pozostawić go nierozstrzygniętym. Notatka Review może stać się kryterium dla wybranego tagu przypadku. Zmiana zakresu zmienia odcisk oceniania; strażnicy przyjmują ją dopiero po uprawnionym przesunięciu przypięcia.

## Porównanie z baseline'em { #comparing-with-a-baseline }

Porównanie dopasowuje obie strony przypadek po przypadku według stałego id
przypadku i podaje każdy jako **regresję** (był zaliczony, teraz nie jest),
**naprawiony** (nie był, teraz jest), bez zmian albo niepełny. Przypadki, na
które odpowiedziała tylko jedna strona, liczą się jako nieporównane. Tak samo
przypadek, którego wejście, historia, odpowiedź wzorcowa, kontrprzykład,
oczekiwane wywołania albo checki zmieniły się między stronami (`changed`):
zaostrzenie checku to zmiana przypadku, nie agenta, a strona runa podaje, ile
przypadków zmieniło się od baseline'u. Zmiana tagów albo notatki się nie liczy.

Baseline jest wybierany **przy starcie runa**, zapisywany w runie jako osobna
strona i nigdy nie jest wybierany ponownie: run otwarty po następnej publikacji
pokazuje to samo porównanie.

**Domyślny baseline jest tani**: ostatni zakończony run tego samego datasetu na
wersji przed kandydatem - dla wersji roboczej na opublikowanej wersji. Liczy się tylko
run tej wersji w opublikowanej postaci: na jej własnym modelu, bez proponowanej
treści skilla ani kontekstu, z odpowiedzią na każdy przypadek, oceniony tym
samym ocenianiem i uruchomiony w tym samym środowisku z tymi samymi
`from_recordings` i `live_reads`. Gdy takiego nie ma, run nie ma baseline'u;
oszacowanie to mówi (`missing_baseline_version`), a dialog startu proponuje
zamiast tego uruchomić tę wersję obok. Obie strony są opisane datą, modelem i
wersją datasetu, bo mogą się różnić w każdej z dwóch ostatnich.

Run może zamiast tego wskazać jako baseline **wcześniejszy run** tego samego
agenta na tym samym datasecie (`baseline_run_id`), taki, który się zakończył -
tak [suita ewaluacji](#suites) sprawdzająca codziennie tę samą wersję widzi dryf.

### Baseline w tym samym runie { #a-baseline-in-the-same-run }

Gdy od wyniku zależy decyzja - bramka promocji, proponowana zmiana sprawdzana
ewaluacją, porównanie modeli - baseline działa **w tym samym runie**
(`paired_baseline`, a zawsze dla `purpose: "gate"`). Providerzy zmieniają się
z dnia na dzień, a regresja zmierzona względem odpowiedzi z zeszłego tygodnia
może być winą providera, nie agenta.

Zakończone ramię baseline'u zastępuje uruchomienie nowego tylko wtedy, gdy
zgadzają się jego wersja, wersja datasetu, model, ocenianie i sędzia, działało
w tym samym środowisku z tymi samymi `from_recordings` i `live_reads`, a
skończyło się w ciągu `EVAL_BASELINE_CACHE_HOURS`. Run mówi, który run
wykorzystał. Wykorzystywane są tylko jego pierwsze odpowiedzi: przypadek, który
się odwraca, jest mu w tym runie zadawany ponownie.

### Odwrócenie jest potwierdzane, zanim się liczy { #a-flip-is-confirmed-before-it-counts }

Przypadek, który się odwrócił, jest powtarzany `EVAL_RERUNS` razy (domyślnie
2), gdy są już pierwsze odpowiedzi. Regresja jest **potwierdzona**, gdy każda
powtórka kandydata znowu nie przechodzi, a przy baseline'ie w tym samym runie
każda powtórka baseline'u znowu przechodzi; w przeciwnym razie jest podawana
jako **niepotwierdzona**. Naprawa jest potwierdzana tak samo.

Każdy baseline jest powtarzany obok kandydata - taki, który odpowiadał tutaj,
albo taki, którego pierwsze odpowiedzi pochodzą z wcześniejszego runa - więc obie
strony potwierdzają odwrócenie tego samego dnia, a jedna szczęśliwa odpowiedź
baseline'u niczego nie potwierdza. Jedynym wyjątkiem jest baseline, który jest
samym kandydatem we wcześniejszym czasie - ten sam spec na tym samym modelu,
uruchomiony tak samo, jak ten, z którym porównuje się suita sprawdzająca
codziennie jedną wersję: jego powtórki byłyby znowu tylko powtórkami kandydata,
więc nie jest powtarzany, a dryf potwierdzają same powtórki kandydata.

Run porównywany z baseline'em potrzebuje co najmniej jednej powtórki; run bez
baseline'u może je pominąć. Run porównany z wcześniejszym runem, któremu nigdy
nie zadał pytań ponownie - zapisany, zanim baseline'y były przechowywane w
runach, albo porównany ręcznie z innym runem - mówi o tym, i żadne z jego
odwróceń nie jest potwierdzone.

Powtórki podnoszą poprzeczkę, a nie ją obniżają: odwrócenie jest potwierdzone
tylko wtedy, gdy utrzyma się przy każdej powtórce, więc więcej powtórek
potwierdza mniej odwróceń. Mały lub tani model, który na ten sam przypadek
odpowiada inaczej przy kolejnych próbach, zostawia swoje odwrócenia
niepotwierdzone, a werdykt brzmi `no_difference`, nawet gdy odsetek zaliczeń się
zmienił - to znaczy, że model jest niestabilny na tych przypadkach, a nie że nic
się nie zmieniło. Pomaga więcej przypadków w datasecie, stabilniejszy model albo
niższa `temperature` w jego [ustawieniach modelu](models.md#model-settings) oraz
przejrzenie niepotwierdzonych przypadków w tabeli.

Strona runu mówi to wprost, gdy nic się nie utrzymało, a co najmniej trzy
przypadki zmieniły się raz albo odsetki zaliczeń dzieli 20 punktów lub więcej.

### Co mówi werdykt { #what-the-verdict-says }

Werdykt opiera się tylko na potwierdzonych odwróceniach. Jedna potwierdzona
regresja sprawia, że kandydat jest `worse` - przypadek, który psuje za każdym
razem, to wystarczający powód, żeby nie publikować - same potwierdzone naprawy
dają `better`, jedne i drugie dają `mixed`, a brak jakiegokolwiek
potwierdzonego odwrócenia to `no_difference`. Każde odwrócenie podaje pytanie
przypadku.

Osobno dokładny test McNemara na potwierdzonych odwróceniach daje `overall`:
`worse` albo `better`, gdy odróżnia obie strony na poziomie
`EVAL_SIGNIFICANCE`, i null, gdy odwróceń jest za mało, jak w większości
małych datasetów.

Odsetek zaliczeń liczy każdy przypadek według większości jego rozstrzygniętych
prób - samej pierwszej odpowiedzi, gdy nie był powtarzany, a werdykt osoby o
tej odpowiedzi przeważa nad jednym i drugim - więc zgadza się z potwierdzonymi
odwróceniami. Własny odsetek pierwszych odpowiedzi jest zachowywany obok jako
`first_pass_rate`.

### Inny sędzia unieważnia porównanie { #a-different-judge-invalidates-the-comparison }

Każda ocena zapisuje [sędziego, który ją wystawił](datasets.md#judge): jego
model, jego wersję, odcisk rubryki i wersję własnego promptu sędziego. Gdy obie
strony były oceniane innymi ustawieniami oceniania albo przez innego sędziego,
model, rubrykę lub prompt, porównanie jest `invalid` i nie daje werdyktu -
odwrócenie mówi wtedy coś o ocenianiu, nie o agencie. Baseline oceniony
wcześniejszym promptem sędziego mówi o tym i nie jest ponownie wykorzystywany
jako baseline z pamięci podręcznej.

Run, którego sędzia zmienił się w trakcie oceniania przypadków, też jest
`invalid`: przypadek, którego próby mają oceny dwóch sędziów, rozstrzyga się
według tego, który ocenił ich więcej.

### Dwie osie, najpierw jakość { #two-axes-quality-first }

Werdykt dotyczy jakości. Efektywność jest podawana obok niego i nigdy do niego
nie wchodzi: koszt na zaliczony przypadek, tokeny i latencja są każde `better`,
`worse` albo `unchanged`, gdzie zmiana w granicach
`EVAL_EFFICIENCY_TOLERANCE` to brak zmiany.

## Porównanie modeli { #comparing-models }

Podanie kilku `model_profile_ids` uruchamia kandydata raz na każdym modelu w
tym samym runie, każdy jako osobne ramię. Każde ramię podaje swój odsetek
zaliczeń, koszt i latencję obok pozostałych. Z baseline'em w tym samym runie
baseline działa na pierwszym podanym modelu, a każde ramię jest z nim
porównywane.

## Suity { #suites }

**Suita** to run ewaluacji, o którego uruchomieniu nikt nie musi pamiętać. Wskazuje
agenta, dataset, środowisko, którego wersję sprawdza, i próg, który musi spełnić
każdy wynik, a potem działa sama. Karta **Suity** stoi pod runami na zakładce
**Ewaluacje** agenta: dataset każdej suity, kiedy się uruchamia, jej próg i jak ostatnio
wypadła. Po otwarciu suita pokazuje każdy wynik, powód, dla którego nie
przeszedł, przypadki, które się zepsuły, i link do runa ewaluacji za nim; strona tego
runa podaje suitę, która go uruchomiła.

### Kiedy suita się uruchamia { #when-a-suite-runs }

Dowolne połączenie:

- **Według harmonogramu** - wyrażenie cron czytane na zegarze strefy czasowej,
  więc `0 6 * * *` w `Europe/Warsaw` to szósta w Warszawie po obu stronach
  zmiany czasu. Sprawdza wersję serwowaną przez swoje środowisko - wersja
  produkcyjna sprawdzana codziennie wyłapuje zmiany modelu u providera i
  zmiany w bazie wiedzy. Uruchomienie pominięte, gdy worker nie działał,
  odbywa się raz.
- **Po publikacji** - każda nowa wersja, z poprzednią wersją uruchomioną obok
  w tym samym runie ewaluacji.
- **Po promocji** - wersja wypromowana na środowisko suity (domyślne, gdy
  suita żadnego nie wskazuje), porównana z wersją, którą zastąpiła.
- **Po zmianie zależności** - edycja skilla albo pliku kontekstowego, z którego
  korzysta sprawdzana wersja, albo dodanie, ponowne przetworzenie lub usunięcie
  dokumentu w bazie wiedzy, którą przeszukuje. Specjaliści zdefiniowani w
  wersji liczą się jako ta wersja. Seria zmian to jeden run, należny
  `EVAL_SUITE_DEPENDENCY_DEBOUNCE_SECONDS` po pierwszej. Profilu modelu nie da
  się zmienić w miejscu - wskazanie agentowi innego to publikacja - a zmianę
  modelu po stronie providera wyłapuje harmonogram.
- **Uruchom teraz** - ręcznie, jako osoba, która to kliknie.

Suita czekająca na sprawdzenie wersji wchłania następny trigger dla tej samej
wersji, więc publikacja, a po niej promocja tej wersji, to jeden run. Suita
prowadzi jeden run ewaluacji naraz; zmiana, która przyjdzie w trakcie, czeka na
następny. Wstrzymana suita nie uruchamia się ani z żadnego triggera, ani
ręcznie.

Suita, która **strzeże środowiska**, uruchamia się też przed promocją na nie -
na wersji, która ma zostać wypromowana, obok tej, którą środowisko serwuje - a
promocja czeka, aż przejdzie; zob.
[Strażnicy promocji z ewaluacji](environments.md#guarding-a-promotion-with-evals).
Jej wyniki noszą oznaczenie *Przed promocją* (`gate`). Suita, która strzeże
środowiska, jest przypięta do wersji datasetu i scoringu, które miała, gdy
została strażnikiem, więc edycja datasetu nie zmienia tego, co sprawdza, dopóki
przypięcie nie zostanie przesunięte. Nie da się jej usunąć, dopóki nie zostanie
tam zdjęta.

### Co musi spełnić wynik { #what-a-result-must-meet }

Bez minimalnego odsetka zaliczeń i wcześniejszego porównywalnego wyniku kompletny pierwszy pomiar ma stan **Ustalono wynik bazowy**, nawet gdy wszystkie przypadki są niezaliczone. To punkt odniesienia dla kolejnych porównań, nie zaliczenie: nie otwiera bramki promocji ani nie przesuwa podążającego środowiska. Ustaw minimum, jeśli suita ma wymagać bezwzględnego poziomu jakości. Aktualizacja zmienia klasyfikację wcześniejszych zaliczeń bez obu kryteriów; operator ocenia środowiska, które już zostały przesunięte.

Wynik **nie przechodzi**, gdy więcej przypadków, niż suita dopuszcza, psuje
się powtarzalnie względem baseline'u - domyślnie żaden, więc jedna
potwierdzona regresja go oblewa - albo gdy odsetek zaliczonych, liczony dla
każdego przypadku według większości prób, spada poniżej minimum suity.
Kierunek z testu McNemara jest pokazywany obok wyniku i nigdy o nim nie
decyduje. Dwa opcjonalne limity sprawdzają wydajność: wzrost kosztu na
zaliczony przypadek i opóźnienia p95 względem baseline'u; puste niczego nie
sprawdzają.

Wynik, którego porównanie jest
[nieważne](#a-different-judge-invalidates-the-comparison) albo w którym choć
jeden przypadek został niekompletny lub nieoceniony, jest **bez rozstrzygnięcia** -
nigdy zaliczony - chyba że coś wprost nie przeszło: potwierdzona regresja albo
minimum, którego odsetek zaliczonych nie osiągnie, nawet gdyby każdy
nierozstrzygnięty przypadek przeszedł. Podaje przypadki, które zostały
nierozstrzygnięte.

Blokada guardraila jest oceniana jak odmowa wraz z zapisaną przyczyną; treść zatrzymana przez guardrail wyjściowy nie jest oceniana. Oczekiwanie na zgodę lub odpowiedź człowieka, anulowanie i niedokończony run pozostawiają przypadek niekompletny. Run zakończony błędem, zatrzymana pętla lub limit kroków liczą się jako awaria. Licznik awarii dotyczy pierwszych odpowiedzi niezależnie od rozstrzygnięcia większości prób: każda taka awaria oblewa suitę, nawet jeśli powtórki przejdą lub dadzą remis.

Strażnik przypina publikację sędziego razem z datasetem i ocenianiem. Ponowna publikacja sędziego nie zmienia runów strażnika ani ich ponownej oceny. Przesunięcie przypięcia wymaga `promotions:override` i zapisuje starą oraz nową wersję sędziego w `agent.environment_guards_changed`. Brak przypiętego sędziego pozostawia ocenę niekompletną; nigdy nie wybiera automatycznie nowej publikacji. Po aktualizacji stare runy bez zapisanego przypięcia sędziego nie otwierają bramki.

Dla suity bez strażnika ponowna publikacja sędziego zmienia ocenianie, więc następne porównanie jest raz bez rozstrzygnięcia, a właściciel dostaje wiadomość. Odsetek zaliczonych poniżej minimum oblewa
wynik niezależnie od porównania: minimum nie potrzebuje baseline'u. Wynik, którego
run ewaluacji anulowano, też jest bez rozstrzygnięcia i mówi o tym; wynik runu, który
skończył się błędem, jest błędem.

Wynik **nie został uruchomiony**, gdy
kosztowałby więcej, niż zostało w budżecie albo niż własny limit suity, gdy
ocenić go mógłby tylko sędzia, a wsparcie AI jest wyłączone, albo gdy nie ma
opublikowanej wersji do sprawdzenia.

Runy z harmonogramu i po zmianie
zależności porównuje się z ostatnim zaliczonym runem suity na tej samej
wersji - ostatnim stanem znanym jako dobry, więc przypadek, który się zepsuł,
pozostaje zepsuty, dopóki ktoś go nie naprawi - i dzięki temu mierzą dryf;
publikacja i promocja uruchamiają baseline w tym samym runie. Po wyniku,
którego nie dało się porównać z tym runem - bo od tamtej pory zmieniło się
ocenianie - następny uruchamia obok siebie poprzednią wersję, ocenianą tak, jak
teraz, więc może znowu przejść i stać się runem, z którym porównuje się kolejne.

Gdy uruchomienie obu przekroczyłoby `max_run_usd` suity, a sam kandydat by go
nie przekroczył, kandydat uruchamia się bez poprzedniej wersji obok siebie:
porównuje się go z ostatnim porównywalnym runem tamtej wersji, jeśli taki
jeszcze jest, a w przeciwnym razie ocenia według własnych liczb. Gdy nie ma z
czym porównać, wynik mówi „Not compared: running the earlier version too would
exceed the suite's cost cap.”, a zaliczony wynik z tą informacją powiadamia
właściciela suity.

[Sprawdzenie sugestii asystenta tworzenia](authoring.md#check-with-evals)
uruchomione na suicie jest oceniane według tego samego progu, ale nie jest
wynikiem suity: nie trafia do jej historii i nikogo nie powiadamia.

### Jako kto działa i kto dostaje wiadomość { #who-it-runs-as-and-who-is-told }

Suita działa jako osoba, która ostatnio ją zapisała - jej **właściciel** - z
uprawnieniami, jakie ta osoba ma w chwili startu runa. Nikt nie patrzy, jak
startuje run z harmonogramu, więc zapisanie suity to zgoda na jej koszt, a
formularz najpierw pokazuje cenę jednego runa i miesiąca harmonogramu. Ktoś
inny, kto zmieni suitę, przejmuje ją. Suita, której właściciel opuści
organizację albo nie może jej już uruchomić, zostaje wstrzymana z podanym
powodem - tak samo jak suita, której środowisko usunięto, także już
wstrzymana, zamiast po cichu sprawdzać inną wersję. Wznowić ją można dopiero
po ponownym wybraniu środowiska.

Właściciel dostaje wiadomość, gdy wynik nie przechodzi, jest bez
rozstrzygnięcia albo się nie uruchamia - raz na serię takich wyników na danej
wersji, z nazwami przypadków, które się zepsuły albo zostały bez oceny - w
centrum powiadomień i mailem, jeśli go
włączył. Slack nie jest jeszcze kanałem powiadomień.

## Ustawienia { #settings }

| Ustawienie | Domyślnie | O czym decyduje |
|---|---|---|
| `EVAL_RUN_CONCURRENCY` | `3` | Ile przypadków jeden run wykonuje naraz |
| `EVAL_ORG_CONCURRENCY` | `6` | Ile przypadków jedna organizacja wykonuje naraz, we wszystkich runach |
| `EVAL_RERUNS` | `2` | Powtórki odwróconego przypadku; run może poprosić o 0 do 5 |
| `EVAL_BASELINE_CACHE_HOURS` | `24` | Jak stary może być pasujący baseline, żeby nadal go użyć |
| `EVAL_SIGNIFICANCE` | `0.05` | Poziom, poniżej którego potwierdzone odwrócenia są werdyktem |
| `EVAL_EFFICIENCY_TOLERANCE` | `0.05` | Względna zmiana kosztu, tokenów lub latencji liczona jako brak zmiany |
| `EVAL_FALLBACK_INPUT_TOKENS` | `2000` | Tokeny wejściowe, według których wyceniany jest przypadek na modelu bez historii |
| `EVAL_FALLBACK_OUTPUT_TOKENS` | `400` | Tokeny wyjściowe, według których wyceniany jest przypadek na modelu bez historii |
| `EVAL_FALLBACK_CASE_COST_USD` | `0.05` | Szacunek na przypadek na modelu bez historii i bez znanej ceny |
| `EVAL_ESTIMATE_SAMPLE` | `50` | Ile ostatnich runów uśrednia szacunek |
| `EVAL_ABANDONED_AFTER_MINUTES` | `10` | Jak długo działający run może stać przy milczącym workerze, zanim sweep zakończy go błędem |
| `EVAL_HEARTBEAT_SECONDS` | `60` | Jak często pracujący run daje znać, że żyje |
| `EVAL_SUITE_DEPENDENCY_DEBOUNCE_SECONDS` | `600` | Jak długo suita czeka po zmianie skilla, pliku kontekstowego albo bazy wiedzy, żeby seria zmian była jednym runem |

## Dostęp { #access }

Uruchomienie runa - albo pytanie, ile by kosztował - wymaga najpierw
`runs:view`: za run się płaci, a kto nie mógłby go odczytać ani anulować, nie
może go uruchomić, jakiekolwiek granty ma. Tam, gdzie konsola zaproponowałaby mu
kontrolkę startu, pokazuje ją wyłączoną i mówi dlaczego. Każdy sposób startu
pyta o to samo: Uruchom ewaluację, suita, Przetestuj wersję roboczą i Sprawdź w ewaluacji asystenta.

Start wymaga następnie `datasets:run` na datasecie i `agents:run` na agencie,
każde rozstrzygane z grantami zasobu. Uruchomienie wersji roboczej wymaga też
`agents:edit` na agencie, bo wersja robocza to praca w toku edytorów. Sędzia, gdy ocenia
dataset, wymaga tego, co mówi [ocenianie](datasets.md#scoring).

Odczyt runa wymaga `runs:view` oraz tego, by czytający widział i agenta, i
dataset - run na datasecie, którego czytający nie może otworzyć, nie jest
wyświetlany, a prośba o niego po id odpowiada `404`, tak jak run innej
organizacji. Runy datasetu wymagają też `datasets:view` na nim i wymieniają
tylko agentów, których czytający może widzieć.

Utworzenie, zmiana, wstrzymanie albo uruchomienie suity wymaga `agents:edit` i
`agents:run` na agencie, `datasets:run` na datasecie i `runs:view`, a do tego
osoby zalogowanej
jako ona sama: suita wydaje jako ta, kto ją zapisze, więc nie może tego zrobić
ani klucz API, ani administrator działający w czyimś imieniu. Odczyt suit
agenta wymaga `runs:view` i dostępu do agenta; pytania przypadków wskazanych w
wyniku widzi tylko ktoś, kto może otworzyć dataset.

## Co run zachowuje { #what-a-run-keeps }

Wynik zawiera odpowiedź agenta i argumenty każdego wykonanego wywołania, więc
może zawierać dane osobowe z przypadku, na który odpowiadał, i z nagrania, z
którego odpowiadano. Jest usuwany razem ze swoim runem, a run razem z agentem
lub datasetem; usunięcie konwersacji, z której wzięto przypadek, nie usuwa
wyników już z niego uzyskanych. [Ochrona danych](data-protection.md) wymienia
go razem z innymi magazynami.

Rozpoznane sekrety w zapisanych odpowiedziach, danych wywołań narzędzi i błędach są zastępowane takimi samymi znacznikami jak w przeglądzie i przypadkach datasetu. Pierwsza ocena korzysta z oryginalnej odpowiedzi w pamięci przed zapisem; ponowna ocena używa zachowanych danych z usuniętymi sekretami. Aktualizacja usuwa również sekrety z istniejących wyników; wycofanie migracji ich nie przywraca.
