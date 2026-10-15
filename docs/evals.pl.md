---
source_sha: "0aeaa21bc6b9"
title: "Eval runy"
description: "Eval run odpowiada na każdy przypadek datasetu wersją agenta albo jego draftem, ocenia każdą odpowiedź i porównuje wynik z baseline'em."
---

# Eval runy { #eval-runs }

**Eval run** sprawia, że agent odpowiada na każdy przypadek wersji
[datasetu](datasets.md), ocenia każdą odpowiedź tak, jak mówi
[ocenianie](datasets.md#scoring) datasetu, i zachowuje to, co się stało.
Odpowiada na pytanie, które naprawdę ma osoba edytująca agenta: czy ta zmiana
poprawiła agenta, pogorszyła go, czy nic nie zmieniła - i ile to kosztowało.

Run składa się z czterech wyborów: **agent** i to, co z niego się uruchamia
(opublikowana wersja albo draft w obecnym stanie), **wersja datasetu**,
**środowisko**, którego testowych połączeń używają przypadki, i opcjonalnie
**kilka modeli** obok siebie. W tym samym runie może też działać **baseline** -
wcześniejsza wersja - żeby obie strony trafiły na tego samego providera tego
samego dnia.

## W konsoli { #in-the-console }

Zakładka **Evals** agenta otwiera się wykresem liniowym jego odsetka zaliczeń
w czasie, z linią na każdy dataset i każdym punktem opisanym tym, co się
uruchomiło - draft jest rysowany jako pusty punkt. Pod wykresem są jego runy,
pogrupowane po datasecie, każdy z tym, co testowano względem czego, z
werdyktem (Breaks 2, Worse overall · 4 broke, First result, Pending) i
odsetkiem zaliczeń każdego modelu, a po najechaniu kursorem - z odsetkiem
pierwszych odpowiedzi.

**Run evals** otwiera dialog startu od razu na oczywistej odpowiedzi: draft
względem bieżącej opublikowanej wersji, gdy draft się od niej różni, sama
opublikowana wersja, gdy się nie różni, i sam draft dla agenta, którego nikt
nie opublikował. Dataset, na którym agent był ostatnio mierzony - albo jedyny,
jaki istnieje - jest już wybrany; środowisko, nagrania i powtórki są pod
**Advanced**. Koszt jest wyliczany, gdy pola się ustalą, i mówi, co ocenia
odpowiedzi oraz ile zostanie potem w budżecie agenta i organizacji; run
startuje dopiero z przycisku, który podaje tę kwotę. **Draft differs from vN**
na stronie agenta ma przycisk **Test draft**, który otwiera ten sam dialog, a
dialog publikacji mówi, co znalazł ostatni run draftu - albo że draftu nie
testowano od jego ostatniej zmiany - nie wstrzymując publikacji.

Strona runa otwiera się jego werdyktem w kilku zdaniach - przypadki, które
kandydat psuje albo naprawia za każdym razem, gdy jest o nie pytany, jeden z
nich zacytowany z liczbą prób, które to powtórzyły, czy ogólnie jest lepszy,
czy gorszy, gdy potwierdzone zmiany pozwalają to stwierdzić, i odsetek zaliczeń
przed i po - razem z tym, co zrobić dalej: zobaczyć, co zmieniło się między
obiema wersjami (History otwiera się na tym porównaniu, względem speca, który
run testował, a nie draftu w jego obecnym stanie), pokazać przypadki, które się
zepsuły, wrócić do Build albo opublikować draft.

Publish jest główną akcją tylko wtedy, gdy nie potwierdzono żadnej regresji, a
run draftu, który od tego czasu się zmienił, proponuje zamiast tego **Test
again**. Gdy run odpowiada, strona mówi, ile pierwszych odpowiedzi już jest, a
porównanie czeka na obie strony. Odpowiedzi, których sędzia nie zdołał ocenić,
mówią dlaczego i nie liczą się ani jako zaliczone, ani jako niezaliczone, a
**Grade again** w nagłówku ocenia je ponownie bez pytania agenta, dla każdego,
kto może uruchamiać dataset.

Pod werdyktem są obie strony obok siebie, to, jak wypadają w porównaniu, i
przypadki - każdy wiersz z kropką zaliczenia lub niezaliczenia dla każdej
strony, filtrowane po wyniku lub tagu, każdy otwierający się na to, czego
przypadek oczekuje, oraz na odpowiedzi, wywołania i uzasadnienia oceniających
każdej strony. Wybrany tag zawęża do siebie strony, zmiany i przypadki; werdykt
nadal obejmuje wszystkie przypadki.

Gdy są już powtórki, run wysyła do [kolejki przeglądu](datasets.md#review)
datasetu to, za czym może się opowiedzieć - każdą potwierdzoną regresję i każdą
odpowiedź, przy której ocenie jego sędzia zawiódł, po jednej na przypadek - i
podaje, ile ich jest (`routed_to_review`). Pominięty sędzia nie wysyła nic: jego
odpowiedzi czekają na stronie runu na **Grade again**. Gdy wysyłka zostanie
odrzucona, run i tak się kończy, a jego strona mówi dlaczego (`routing_error`). **Send failed to review** wysyła
resztę niezaliczonych odpowiedzi jednej strony, dla każdego, kto może edytować
dataset, a przypadek, którego ocenę osoba uchyliła, jest oznaczany jako
poprawiony.

Własna zakładka **Evals** datasetu wymienia każdego mierzonego na nim agenta,
każdego ze swoim trendem i runami, a **Run evals** w jego nagłówku otwiera
dialog startu na tym datasecie i pyta, którego agenta testować.

Karta **Eval runs** na dashboardzie wymienia ostatnie runy organizacji z ich
agentem i werdyktem. Przypadki evala i ocenianie sędziego nie wchodzą do żadnej
innej liczby na dashboardzie, a Activity je ukrywa, chyba że jej filtr
powierzchni prosi o wszystkie powierzchnie albo tylko o evale. Lista Activity
pokazuje, o co zapytano każdy run - jego pierwszą wiadomość użytkownika albo
pytanie przypadku evala, a dla runa sędziego to, co ocenił - żeby run dało się
znowu znaleźć i zrobić z niego przypadek. Przypadek evala otwiera tam swój eval
run na tym przypadku, a **See what the model saw** przypadku otwiera to, co
dostał jego model.

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
przypadek, gdy dataset ocenia sędzia, a AI assistance jest włączone.

AI assistance jest wyłączone w organizacji, dopóki ktoś z `org:settings` go
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

Eval wydaje z tych samych miesięcznych budżetów co ruch produkcyjny: z limitu
agenta i z limitu organizacji. Nie ma osobnego budżetu na evale. Duży dataset
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
zatrzymuje cały eval run jako `budget_exceeded`.

### Co jest odrzucane { #what-is-refused }

Run, który nikomu niczego by nie powiedział, jest odrzucany, zanim zostanie
oszacowany:

- wersja datasetu bez przypadków;
- ocenianie bez wymaganego oceniającego, który mógłby rozstrzygnąć którykolwiek
  przypadek wersji - bez checku do zastosowania, bez oczekiwanego wywołania
  narzędzia i bez sędziego. Gdy sędzia jest jedynym oceniającym, a AI assistance
  jest wyłączone, odmowa to mówi: sędzia potrzebuje AI assistance, które jest w
  tej organizacji wyłączone, więc włącz je w ustawieniach organizacji albo dodaj
  check;
- agent, który nigdy nie został opublikowany, a poproszono o wersję - uruchom
  zamiast tego jego draft;
- baseline dla pierwszej wersji, przed którą nic nie ma.

## Jako co działa każdy przypadek { #what-each-case-runs-as }

Każdy przypadek to zwykły run agenta z powierzchnią `eval`. Jest sprawdzany
względem budżetów przed każdym żądaniem do modelu, a jego koszt jest
zapisywany. Nie wchodzi do liczb użycia na dashboardzie, które liczą tylko
produkcję i podają koszt ruchu evali obok (`cost.eval_usd`), a historia runów
go pomija, gdy się o to poprosi (`?exclude_surface=eval`). Odczyt pojedynczego
runa wskazuje eval run i przypadek, na który odpowiadał (`eval_case`),
czytającemu, który może widzieć dataset. Działa jako osoba, która uruchomiła
eval, z jej obecną rolą, i nie czyta ani nie zapisuje jej osobistej pamięci.

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

### Draft nigdy nie liczy się jako wersja { #a-draft-is-never-counted-as-a-version }

Draft przechodzi tą samą ścieżką, z dwiema różnicami. Najpierw jest sprawdzany
względem własnego dostępu osoby uruchamiającej - wszystkiego, co sprawdziłaby
publikacja - bo draft nigdy nie był walidowany przy zapisie. A jego runy nie są
przypisywane do żadnej wersji: nie pojawiają się w użyciu wersji, a liczby
wersji nigdy nie obejmują odpowiedzi, których udzielił jej draft.

Draft jest kopiowany przy starcie runa, więc każdy przypadek odpowiada na tę
samą treść, nawet jeśli ktoś dalej edytuje.

## Działanie i anulowanie { #running-and-cancelling }

Run wykonuje się w tle, we własnym flow workera, więc przetrwa restart API.
Przypadki działają po kilka naraz: najwyżej `EVAL_RUN_CONCURRENCY` na run i
najwyżej `EVAL_ORG_CONCURRENCY` we wszystkich eval runach organizacji, więc
dataset z 500 przypadkami nie zajmie wszystkich żądań, na które provider
pozwala organizacji.

Anulowanie (`POST /api/v1/eval-runs/{id}/cancel`, przez osobę, która run
uruchomiła, albo każdego, kto może edytować agenta) zatrzymuje to, co się nie
zaczęło: przypadki, które już działają, kończą się i są zachowywane, a żaden
inny się nie zaczyna. Run, którego worker przestaje robić postępy na
`EVAL_ABANDONED_AFTER_MINUTES`, kończy się błędem w cogodzinnym sweepie
zawieszonych runów, który zwalnia też jego miejsca.

## Wyniki { #results }

Każda próba zachowuje odpowiedź, wykonane wywołania - każde oznaczone jako
wykonane, zablokowane, odtworzone albo rozbieżne - werdykt i uzasadnienie
każdego oceniającego, swój koszt, tokeny i latencję. Odpowiedź i wywołania są
kopiowane do wyniku, bo run przypadku nie ma konwersacji, w której trzymałby
transkrypt.

Każde ramię runa jest podsumowane na dwóch osiach i per tag:

| Oś | Mierzy |
|---|---|
| Jakość | Odsetek zaliczonych wśród rozstrzygniętych przypadków, każdy według tego, jak wypadła większość jego prób; obok odsetek pierwszych odpowiedzi; ile nie dało się rozstrzygnąć |
| Efektywność | Koszt na zaliczony przypadek, tokeny na przypadek i latencję w p50 i p95 |

Przypadek, którego wymagany oceniający nie mógł zadziałać, jest
**nierozstrzygnięty**, nigdy zaliczony. Taki, którego sędzia nie zdołał ocenić
albo który pominął, jest **nieoceniony**: run wymienia te oceny jako
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

`?draft=current` zostawia runy, które testowały draft w obecnym stanie - ten
sam spec, niezależnie od kolejności, w jakiej zapisano jego klucze - i to
właśnie czyta dialog publikacji.

## Porównanie z baseline'em { #comparing-with-a-baseline }

Porównanie dopasowuje obie strony przypadek po przypadku według stałego id
przypadku i podaje każdy jako **regresję** (był zaliczony, teraz nie jest),
**naprawiony** (nie był, teraz jest), bez zmian albo niepełny. Przypadki, na
które odpowiedziała tylko jedna strona, liczą się jako nieporównane.

**Domyślny baseline jest tani**: ostatni zakończony run tego samego datasetu na
wersji przed kandydatem - dla draftu na opublikowanej wersji. Obie strony są
opisane datą, modelem i wersją datasetu, bo mogą się różnić w każdej z nich.

### Baseline w tym samym runie { #a-baseline-in-the-same-run }

Gdy od wyniku zależy decyzja - bramka promocji, proponowana zmiana sprawdzana
evalami, porównanie modeli - baseline działa **w tym samym runie**
(`paired_baseline`, a zawsze dla `purpose: "gate"`). Providerzy zmieniają się
z dnia na dzień, a regresja zmierzona względem odpowiedzi z zeszłego tygodnia
może być winą providera, nie agenta.

Zakończone ramię baseline'u zastępuje uruchomienie nowego tylko wtedy, gdy
zgadzają się jego wersja, wersja datasetu, model, ocenianie i sędzia, a
skończyło się w ciągu `EVAL_BASELINE_CACHE_HOURS`. Run mówi, który run
wykorzystał. Wykorzystywane są tylko jego pierwsze odpowiedzi: przypadek, który
się odwraca, jest mu w tym runie zadawany ponownie.

### Odwrócenie jest potwierdzane, zanim się liczy { #a-flip-is-confirmed-before-it-counts }

Przypadek, który się odwrócił, jest powtarzany `EVAL_RERUNS` razy (domyślnie
2), gdy są już pierwsze odpowiedzi. Regresja jest **potwierdzona**, gdy każda
powtórka kandydata znowu nie przechodzi, a przy baseline'ie w tym samym runie
każda powtórka baseline'u znowu przechodzi; w przeciwnym razie jest podawana
jako **niepotwierdzona**. Naprawa jest potwierdzana tak samo. Baseline w tym
samym runie - taki, który odpowiadał tutaj, albo taki, którego pierwsze
odpowiedzi wykorzystano - jest powtarzany obok kandydata, więc obie strony
potwierdzają odwrócenie tego samego dnia. Baseline'u z wcześniejszego runa,
porównywanego, gdy nic nie działało obok kandydata, nie da się powtórzyć, więc
wobec niego potwierdza tylko strona kandydata.

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
| `EVAL_ABANDONED_AFTER_MINUTES` | `30` | Jak długo run może stać, zanim sweep zakończy go błędem |

## Dostęp { #access }

Uruchomienie runa wymaga `datasets:run` na datasecie i `agents:run` na agencie,
każde rozstrzygane z grantami zasobu. Uruchomienie draftu wymaga też
`agents:edit` na agencie, bo draft to praca w toku edytorów. Sędzia, gdy ocenia
dataset, wymaga tego, co mówi [ocenianie](datasets.md#scoring).

Odczyt runa wymaga `runs:view` oraz tego, by czytający widział i agenta, i
dataset - run na datasecie, którego czytający nie może otworzyć, nie jest
wyświetlany, a prośba o niego po id odpowiada `404`, tak jak run innej
organizacji. Runy datasetu wymagają też `datasets:view` na nim i wymieniają
tylko agentów, których czytający może widzieć.

## Co run zachowuje { #what-a-run-keeps }

Wynik zawiera odpowiedź agenta i argumenty każdego wykonanego wywołania, więc
może zawierać dane osobowe z przypadku, na który odpowiadał, i z nagrania, z
którego odpowiadano. Jest usuwany razem ze swoim runem, a run razem z agentem
lub datasetem; usunięcie konwersacji, z której wzięto przypadek, nie usuwa
wyników już z niego uzyskanych. [Ochrona danych](data-protection.md) wymienia
go razem z innymi magazynami.
