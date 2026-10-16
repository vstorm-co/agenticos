---
source_sha: "c002e273dc7b"
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

Agent bez historii na danym modelu jest szacowany na
`EVAL_FALLBACK_CASE_COST_USD` za przypadek, a szacunek mówi, że to zgadywanie
(`basis: "fallback"`). Koszt baseline'u wchodzi do sumy, chyba że użyty zostanie
niedawny pasujący baseline - wtedy nic nie kosztuje, a szacunek wskazuje run,
który wykorzystuje.

### Budżet, który zostaje { #the-budget-it-leaves }

Eval wydaje z tych samych miesięcznych budżetów co ruch produkcyjny: z limitu
agenta i z limitu organizacji. Nie ma osobnego budżetu na evale. Duży dataset
może więc zostawić produkcję bez budżetu do końca miesiąca, dlatego szacunek
pokazuje, ile każdy limit zachowa po wydaniu sumy przez run:
`agent_after_usd` i `org_after_usd`.

Uruchomienie jest odrzucane z `402`, zanim cokolwiek zostanie zapisane, gdy suma
przekracza to, co zostało w którymkolwiek limicie. Powtórki potwierdzające
(niżej) nie wchodzą do tego sprawdzenia, bo dotyczą tylko przypadków, które się
odwróciły; szacunek pokazuje, ile najwyżej mogą dodać, jako `rerun_ceiling_usd`.
Każdy przypadek i tak jest sprawdzany względem obu limitów przed każdym
żądaniem do modelu, jak każdy run, a przypadek, który trafi na limit, zatrzymuje
cały eval run jako `budget_exceeded`.

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
względem budżetów przed każdym żądaniem do modelu, jego koszt jest zapisywany i
pojawia się w Activity, gdzie filtr powierzchni oddziela go od ruchu
produkcyjnego. Działa jako osoba, która uruchomiła eval, z jej obecną rolą, i
nie czyta ani nie zapisuje jej osobistej pamięci.

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
inny się nie zaczyna. Worker działającego runu co `EVAL_HEARTBEAT_SECONDS` daje
znać, że żyje; run, którego worker milczy i którego przypadki nie ruszyły się
przez `EVAL_ABANDONED_AFTER_MINUTES`, kończy się błędem w cogodzinnym sweepie
zawieszonych runów, który zwalnia też jego miejsca. Run w kolejce nie ma jeszcze
workera - czeka na wolny runner - więc sweep rezygnuje z niego dopiero po
`EVAL_QUEUED_ABANDONED_AFTER_HOURS`.

## Wyniki { #results }

Każda próba zachowuje odpowiedź, wykonane wywołania - każde oznaczone jako
wykonane, zablokowane, odtworzone albo rozbieżne - werdykt i uzasadnienie
każdego oceniającego, swój koszt, tokeny i latencję. Odpowiedź i wywołania są
kopiowane do wyniku, bo run przypadku nie ma konwersacji, w której trzymałby
transkrypt.

Każde ramię runa jest podsumowane na dwóch osiach i per tag:

| Oś | Mierzy |
|---|---|
| Jakość | Odsetek zaliczonych wśród rozstrzygniętych przypadków i ile nie dało się rozstrzygnąć |
| Efektywność | Koszt na zaliczony przypadek, tokeny na przypadek i latencję w p50 i p95 |

Przypadek, którego wymagany oceniający nie mógł zadziałać, jest
**nierozstrzygnięty**, nigdy zaliczony. Werdykt osoby w
[kolejce przeglądu](datasets.md#review) zastępuje wynik oceniających dla tego
przypadku, a liczby runa idą za nim.

```text
GET /api/v1/agents/{agent_id}/eval-runs      an agent's runs, newest first
GET /api/v1/eval-runs/{id}                   one run, with each arm's summary
GET /api/v1/eval-runs/{id}/cases             cases and every attempt; ?outcome=, ?tag=, ?arm_id=
GET /api/v1/eval-runs/{id}/comparison        a candidate arm against its baseline
```

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
wykorzystał.

### Odwrócenie jest potwierdzane, zanim się liczy { #a-flip-is-confirmed-before-it-counts }

Przypadek, który się odwrócił, jest powtarzany `EVAL_RERUNS` razy (domyślnie
2), gdy są już pierwsze odpowiedzi. Regresja jest **potwierdzona**, gdy każda
powtórka kandydata znowu nie przechodzi, a przy baseline'ie w tym samym runie
każda powtórka baseline'u znowu przechodzi; w przeciwnym razie jest podawana
jako **niepotwierdzona**. Naprawa jest potwierdzana tak samo. Baseline'u z
przeszłości nie da się powtórzyć, więc wobec niego potwierdza tylko strona
kandydata.

### Za mało odwróceń to nie werdykt { #too-few-flips-are-not-a-verdict }

Werdykt opiera się tylko na potwierdzonych odwróceniach, testowanych dokładnym
testem McNemara. Gdy test nie odróżnia obu stron na poziomie
`EVAL_SIGNIFICANCE`, werdykt to `inconclusive` - różnica mieści się w szumie
albo próba jest za mała - a nie lepiej czy gorzej. Nie ma minimalnej liczby
przypadków; mały dataset po prostu częściej zgłasza `inconclusive`. Bez żadnego
potwierdzonego odwrócenia werdykt to `no_difference`.

### Inny sędzia unieważnia porównanie { #a-different-judge-invalidates-the-comparison }

Każda ocena zapisuje [sędziego, który ją wystawił](datasets.md#judge): jego
model, jego wersję i odcisk rubryki. Gdy obie strony były oceniane innymi
ustawieniami oceniania albo przez innego sędziego, model lub rubrykę,
porównanie jest `invalid` i nie daje werdyktu - odwrócenie mówi wtedy coś o
ocenianiu, nie o agencie.

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
| `EVAL_FALLBACK_CASE_COST_USD` | `0.05` | Szacunek na przypadek na modelu bez historii |
| `EVAL_ESTIMATE_SAMPLE` | `50` | Ile ostatnich runów uśrednia szacunek |
| `EVAL_ABANDONED_AFTER_MINUTES` | `30` | Jak długo działający run może stać przy milczącym workerze, zanim sweep zakończy go błędem |
| `EVAL_HEARTBEAT_SECONDS` | `60` | Jak często pracujący run daje znać, że żyje |
| `EVAL_QUEUED_ABANDONED_AFTER_HOURS` | `24` | Jak długo run może czekać na workera, zanim sweep zakończy go błędem |

## Dostęp { #access }

Uruchomienie runa wymaga `datasets:run` na datasecie i `agents:run` na agencie,
każde rozstrzygane z grantami zasobu. Uruchomienie draftu wymaga też
`agents:edit` na agencie, bo draft to praca w toku edytorów. Sędzia, gdy ocenia
dataset, wymaga tego, co mówi [ocenianie](datasets.md#scoring).

Odczyt runa wymaga `runs:view` oraz tego, by czytający widział i agenta, i
dataset - run na datasecie, którego czytający nie może otworzyć, nie jest
wyświetlany, a prośba o niego po id odpowiada `404`, tak jak run innej
organizacji.

## Co run zachowuje { #what-a-run-keeps }

Wynik zawiera odpowiedź agenta i argumenty każdego wykonanego wywołania, więc
może zawierać dane osobowe z przypadku, na który odpowiadał, i z nagrania, z
którego odpowiadano. Jest usuwany razem ze swoim runem, a run razem z agentem
lub datasetem; usunięcie konwersacji, z której wzięto przypadek, nie usuwa
wyników już z niego uzyskanych. [Ochrona danych](data-protection.md) wymienia
go razem z innymi magazynami.
