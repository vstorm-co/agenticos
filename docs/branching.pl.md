---
source_sha: c8b11ff21e6a
---

# Gałęzie i to, co je chroni { #branches-and-what-protects-them }

Jedna długo żyjąca gałąź.

```
feat/… fix/… ──pull request──▶ main
```

`main` to jest to, co klonuje czytelnik tego repozytorium i z czego wycinane są
tagi. Wszystko, co do niego trafia, trafia jako spłaszczony przez squash commit
z krótko żyjącej gałęzi, po tym jak CI przebiegło na pull requeście.

Push do `main` i tag `v*` publikują dodatkowo dwa obrazy kontenerów —
`ghcr.io/vstorm-co/agenticos-backend` i `-frontend`, `edge` oraz `sha-<short>`
z gałęzi, wersję i `latest` z tagu — przez `.github/workflows/images.yml`. Ten
workflow nie ma wyzwalacza na pull request, więc fork nie opublikuje niczego pod
nazwą organizacji, i odrzuca commit, którego nie ma na `main`, więc tag
wypchnięty z gałęzi też nie przesunie `latest`;
[Wdrożenie](deploy.md#the-images) opisuje, co je pobiera.

Nie ma gałęzi `dev`. Przez chwilę była: praca lądowała na niej i docierała do
`main` w release'owych pull requestach. Przy tej skali kupowała gałąź stagingową,
której nikt nie potrzebował, a kosztowała drugie miejsce, w którym każda zmiana
musiała usiąść, więc została usunięta.

## Co jest egzekwowane i przez co { #what-is-enforced-and-by-what }

| Reguła | Egzekwowane przez |
|---|---|
| Żadnego bezpośredniego pusha do `main` | Ruleset — wymagany jest pull request |
| Zielone CI przed mergem | Wymagane status checki: `lint`, `test`, `test-frontend`, `e2e`, `docs`, `Security Scan` |
| Squash przy mergu | Ruleset — jedyna dozwolona metoda merge'owania |
| Rozwiązane wątki dyskusji | Ruleset |
| Nieaktualne akceptacje odrzucane przy nowym pushu | Ruleset |
| Żadnego force pusha, żadnego usuwania | Ruleset |
| Żadnego commita zrobionego stojąc na `main` | `no-commit-to-branch` w `.pre-commit-config.yaml` |
| Pisownia, w każdym śledzonym pliku | codespell — jako hook na plikach, których dotyka commit, i jako `make lint-spelling` w CI-owym jobie `lint` nad całym drzewem |
| Route'y trzymają tylko routery, żadnych komentarzy-banerów, żadnego martwego kodu | `check_routes.py`, `check_comments.py` i `vulture` — hooki w `.pre-commit-config.yaml` (każdy skanuje całe drzewo, `pass_filenames: false`) oraz kroki `make lint-backend` w CI-owym jobie `lint` |
| Żadnej zadeklarowanej zależności, której nic nie importuje | `deptry` — krok `make lint-backend` w CI-owym jobie `lint`, bramkujący na DEP002 i DEP004. Nie jest hookiem pre-commit: czyta cały manifest wobec całego drzewa, więc nie istnieje wersja tego pytania działająca per plik |
| Formatowanie YAML-a, bezpieczeństwo workflowów, podstawy pre-commit, w każdym śledzonym pliku | yamlfmt, zizmor i `pre-commit-hooks` (`end-of-file-fixer`, `trailing-whitespace`, `check-yaml/json/toml`, `detect-private-key` …) — jako hooki na plikach, których dotyka commit, i jako `make lint-precommit` w CI-owym jobie `lint` nad całym drzewem. Tak jak pisownia, są to z natury kontrole per plik, więc bump `rev:`, który przynosi nową regułę, psuje każdy istniejący plik i nic tego nie zauważa, dopóki przez tę regułę nie zostanie odrzucona niepowiązana edycja |

Hook czyta zawsze tylko to, czego dotyka commit, co czyni go kiepską bramką samą
w sobie: literówka, która zmerge'owała się razem ze swoim plikiem, siedzi tam,
dopóki ktoś nie wyedytuje tego pliku z zupełnie innego powodu — i wtedy jego
commit zostaje odrzucony przez słowo, którego sam nie napisał. Dlatego kontrola
pisowni występuje w tabeli dwa razy — hook to szybka informacja zwrotna, a `make
lint-spelling` jest tym, co utrzymuje tę obietnicę prawdziwą dla całego drzewa.

Status checki są dziś wymienione pojedynczo. Powinny zwinąć się w jeden
agregujący job `All Checks Passed`, tak żeby dodanie jobu w CI przestało oznaczać
„pamiętaj, żeby wyedytować ruleset" — lista wymaganych checków, która rozjeżdża
się z workflowem, to sposób, w jaki build zaczyna przechodzić na niczym.

### Wymagany check może zgodnie z prawem zgłosić `skipped` { #a-required-check-may-legitimately-report-skipped }

!!! info "Pominięty wymagany check to zaliczenie, a nie problem"

    GitHub zalicza wymagany status check przy `success`, `skipped` **albo**
    `neutral`. Więc gałąź dotykająca tylko backendu nie dostaje żadnej odpowiedzi
    od frontendu — co oznacza, że „zielono" na takiej gałęzi jest twierdzeniem
    o mniejszej liczbie jobów, niż uruchamia `make check`.

Trzy z tych sześciu nie uruchamiają się na każdym pull requeście. `test`,
`test-frontend` i `e2e` to odpowiednio 8,2, 5,3 i 5,1 rozliczanych minut, a job
`changes` decyduje, na który z nich zestaw zmian dowodliwie nie może mieć wpływu
— `scripts/ci_changed_scope.py`, więc regułę da się przetestować, zamiast być
globem w pliku YAML
([#317](https://github.com/vstorm-co/agenticos/issues/317)).

Dlatego bramką jest `if:` na poziomie jobu, a **nie** filtr `paths:` na
workflowie: odfiltrowany workflow w ogóle nie wystawia swoich checków, więc
ruleset czeka na sześć kontekstów, które nigdy nie nadejdą, a przycisk merge
zostaje szary na zawsze.

Klasyfikator napisano w wersji ostrożnej: **job jest pomijany tylko wtedy, gdy
każda zmieniona ścieżka jest dowodliwie dla niego nieistotna**, więc
nierozpoznana ścieżka uruchamia wszystko.

Permisywny zapis tej samej idei pozwoliłby nowemu katalogowi po cichu zatrzymać
uruchamianie jakiegoś zestawu testów — co nie jest czerwonym buildem, tylko
zielonym z brakującą bramką, a to repozytorium zapłaciło już za to dwa razy
(#143, #165).

Istnieją tylko dwa wyjątki i oba są sprawdzane, a nie zakładane:

- `docs/**`, `mkdocs.yml` i `*.md` na najwyższym poziomie, ponieważ żaden test
  ich nie czyta;
- przeciwna połowa drzewa, dla każdego z dwóch zestawów testów jednostkowych.

`e2e` nie jest wyłączony żadną z tych połówek, a `lint` nie jest bramkowany
nigdy — bo `make lint-spelling` i `make lint-precommit` czytają każdy śledzony
plik.

Drugi wyjątek zatrzymuje się przed jednym katalogiem. `frontend/src/app/api/**`
to BFF, a `backend/tests/api/test_bff_forwarded_paths.py` sprawdza ścieżki
`/api/v1/…`, które ci handlerzy mają wpisane na sztywno, wobec własnej tablicy
route'ów backendu — więc zmiana w proxy uruchamia też zestaw testów backendu.
Pominięcie go tutaj byłoby tą samą awarią „zielono z brakującą bramką" co wyżej,
na jedynym teście napisanym po to, żeby ją złapać.

Dwa szczegóły, których ostrożny kierunek potrzebuje, żeby faktycznie się
trzymał, i oba pierwsza wersja tego rozwiązania miała źle:

- Każdy bramkowany job niesie `!cancelled()` obok sprawdzenia wyjścia. Bez tego
  job `changes`, który **padł** — 502 z API, rate limit — pominąłby wszystkie trzy
  zestawy testów, a ich warunki nigdy nie zostałyby odczytane; a ponieważ
  `changes` sam nie jest wymaganym kontekstem, przycisk merge zrobiłby się
  zielony nad gałęzią, na której nie uruchomił się żaden zestaw.
- Job podaje na wejściu `previous_filename` obok `filename`. Zmiana nazwy
  zgłasza tylko ścieżkę, do której plik dotarł, więc moduł przeniesiony poza
  `backend/` byłby w przeciwnym razie jedną ścieżką frontendową i pomijałby
  zestaw testów backendu dla zmiany, która usunęła moduł backendu.

To, co zestaw zmian pomija, jest wypisane w logu jobu `changes`. Lokalnie nie
jest pomijane nic: `make check` uruchamia cały zestaw.

### Stacked pull request też uruchamia CI { #a-stacked-pull-request-runs-ci-too }

Dwie gałęzie, które edytują ten sam plik, mają być ustawione w stos — druga jest
otwierana wobec pierwszej, a nie wobec `main` — więc wyzwalacz `pull_request`
w `ci.yml` nie niesie **żadnego filtra `branches:`**. Ten filtr dopasowuje do
*bazy*, a dopóki tam był, stacked pull request nie pasował do żadnego wyzwalacza
i nie uruchamiał zupełnie niczego
([#359](https://github.com/vstorm-co/agenticos/issues/359)).

Niebezpieczną połową nie był brak uruchomienia, tylko to, jak się czytał. Pull
request bez żadnych jobów pokazuje **pustą** listę checków, a nie czerwoną:
`gh pr checks` odpowiada „no checks reported", a rollup jest pusty, co wygląda
jak przebieg, który jeszcze się nie zaczął. Cztery pull requesty zmerge'owały się
tak w jeden dzień, każdy zweryfikowany wyłącznie na laptopie. Nic nie zamykało
tej luki, dopóki dziecko nie zostało przekierowane na `main` po zmerge'owaniu
rodzica — czyli dokładnie w momencie, w którym nikt nie czeka na świeży,
siedmiominutowy przebieg.

Kosztuje to niewiele: job `changes` klasyfikuje stacked dziecko po jego własnym
diffie — czyta `pulls/{n}/files`, czyli porównanie wobec własnej bazy tego pull
requesta — a grupa concurrency opisana niżej anuluje nieaktualne przebiegi
dziecka tak samo jak każdego innego.

To, że wyzwalacz nie niesie filtra na bazę, jest asercją, a nie założeniem, w
`backend/tests/test_ci_workflow.py`. I musi nią być: workflow, który się nie
uruchamia, nie produkuje żadnego dowodu, że się nie uruchomił, więc nic w
przebiegu nie może ujawnić tej regresji. Ten sam plik asertuje drugą własność,
której żaden przebieg nie pokaże — że każdy job ogranicza własny czas działania,
niżej.

Dwa ograniczenia warte wyraźnego powiedzenia. **Zielony stacked pull request był
sprawdzony wobec swojego rodzica, a nie wobec `main`** — checki należą do commita
head, więc przekierowanie przenosi stary wynik dalej bez zmian; to jest wpisane
w stackowanie, a nie coś, co wyzwalacz może naprawić, i jest to powód, żeby stosy
były krótkie. Oraz: **CodeQL nie jest tu konfigurowany** — działa z domyślnego
setupu GitHuba, którego wyzwalaczy nie ma w tym repozytorium, więc to, czy czyta
stacked pull request, nie jest naszą decyzją.

### Każdy job ogranicza własny czas działania { #every-job-bounds-its-own-runtime }

`changes` był jedynym jobem w `ci.yml` niosącym `timeout-minutes`, więc pozostałe
siedem dziedziczyło domyślne dla GitHuba **360 minut**
([#364](https://github.com/vstorm-co/agenticos/issues/364)) — zawieszony job
trzymałby więc swój wymagany status check przez sześć godzin i nic w tym
repozytorium nie skończyłoby tego wcześniej. Napisano to jako środek ostrożności
wobec czegoś, czego nikt nie widział. Czternaście przebiegów `e2e` uderzyło w to
ograniczenie w cztery dni do 18 sierpnia
([#879](https://github.com/vstorm-co/agenticos/issues/879)) — a jak wtedy wygląda
job, opisano niżej.

| Job | Ograniczenie | Zaobserwowano |
|---|---|---|
| `changes` | 5 | 7s |
| `lint` | 10 | 22s |
| `Security Scan` | 10 | 14s |
| `docs` | 15 | 4m34s |
| `test-frontend` | 20 | 5m08s |
| `docker` | 20 | 2m30s |
| `test` | 25 | 7m43s |
| `e2e` | 25 | 8m01s |

Zaobserwowane czasy pochodzą z przebiegu 31116003994, pełnej macierzy na `main`.
Każde ograniczenie jest kilka razy większe od swojego jobu, a nie tuż nad nim:
timeout istnieje po to, żeby zakończyć zawieszenie, a taki, który jest dość
ciasny, by przyciąć legalnie zimny cache, to czerwony build z powodu niemającego
związku z diffem.

### Jeden przebieg na gałąź { #one-run-per-branch }

`ci.yml` niesie grupę concurrency kluczowaną na `github.ref`, więc kolejny push
na gałąź anuluje jej poprzedni przebieg. Ma to znaczenie, bo `CLAUDE.md` wymaga
commita i pusha na każdy skończony kawałek: bez anulowania 75 z 369 przebiegów
w pierwszych sześciu dniach sierpnia zostało zastąpionych jeszcze w locie —
około 1800 rozliczanych minut odpowiadania na pytania o commity, na które nikt
już nie czekał.

**Push do `main` jest wyjęty spod tej reguły, a sposób, w jaki jest wyjęty, to
najciekawsza część.**

Przebieg samego merge'a jest tym, co nadaje znaczenie historii i odznace, więc
przebieg na `main` nie może zostać ani anulowany, ani zakolejkowany.

`cancel-in-progress: false` daje tylko pierwsze z tych dwojga. `false` znaczy
*kolejkuj*, a GitHub anuluje każdy wcześniejszy **oczekujący** przebieg w grupie,
kiedy kolejkowany jest nowszy.

Przy jednej grupie dla `main` — merge A działa, B czeka — wejście C anulowałoby B
zupełnie, a commit z B nie dostałby żadnego CI. Przy czternastu wydaniach w sześć
dni i przebiegu na `main` trwającym około 10 minut dwa merge'e w jednym oknie nie
są rzadkim kształtem.

Dlatego grupa niesie przy pushu `github.run_id`, który jest unikalny dla
przebiegu: każdy merge dostaje własną grupę i z niczym nie koliduje. Pull
requesty rozwiązują się wszystkie do tego samego przyrostka i dalej anulują się
nawzajem po `github.ref`.

### Dwie rzeczy zgłaszają `cancelled` i tylko jedna z nich nią jest { #two-things-report-cancelled-and-only-one-of-them-is-that }

Sekcja powyżej opisuje anulowanie, które działa zgodnie z projektem, i to jest
wyjaśnienie, po które każdy sięga. **Tym drugim jest job, któremu skończył się
`timeout-minutes`** — GitHub zapisuje job zakończony na ograniczeniu jako
`cancelled`, a nie jako porażkę — a `cancelled` wymagany check *nie* jest
traktowany jak zaliczenie, w przeciwieństwie do `skipped`, więc merge zostaje
zablokowany nad diffem, z którym wszystko jest w porządku.

Odróżnienie ich zajmuje jedno spojrzenie:

| | Zastąpiony (#317) | Zakończony na ograniczeniu (#879) |
|---|---|---|
| Co jeszcze jest w przebiegu | wszystkie joby w locie anulowane razem | **jeden** job; reszta jest zielona |
| Konkluzja samego przebiegu | `cancelled` | `success`, poza tym jednym jobem |
| Czas trwania anulowanego jobu | tyle, ile zdążył osiągnąć | jego `timeout-minutes`, co do sekundy |
| Nowszy push na gałęzi | tak — to jest przyczyna | nie |
| Ostatnia linia logu | `The operation was canceled.` | ta sama linia, i to jest pułapka |

Czas trwania jest wskazówką.
`gh api repos/vstorm-co/agenticos/actions/runs/<id>/attempts/<n>/jobs` daje
`started_at`, `completed_at` i konkluzje poszczególnych kroków — **i musi to być
forma `attempts/<n>`**, ponieważ ponowne uruchomienie nadpisuje to, co odpowiada
zwykły endpoint `runs/<id>/jobs`, więc job przerobiony ponownym uruchomieniem na
zielono raportuje tam `success`, a pierwotna konkluzja znika.

Tych czternaście miało wspólny jeden krok: `playwright install --with-deps`
wywołujący `apt-get`, który zawiesza się bez ograniczenia, kiedy mirror Azure
runnera jest nieosiągalny. Job e2e nie instaluje już w ogóle pakietów
systemowych, a `backend/tests/test_ci_workflow.py` odrzuca krok, który by to
robił. Ogólna lekcja przeżywa jednak ten konkretny krok: **krok sięgający do
strony trzeciej to krok, który może zawisnąć bez własnego ograniczenia**, a taki,
który zawiśnie, zużywa cały budżet jobu i zgłasza się potem jako czyjeś cudze
anulowanie.

## Squash i dlaczego tytuł pull requesta ma znaczenie { #squash-and-why-the-pull-request-title-matters }

!!! important "Opis pull requesta *jest* wiadomością commita, która przetrwa"

    `main` trzyma jeden commit na pull request, zbudowany z tytułu i treści, a nie
    z commitów samej gałęzi. `CLAUDE.md` opisuje format.

Więc `wip`, `fixup` i „try again" nigdy do niego nie docierają — a opis nie jest
uprzejmością.

## Wyjście awaryjne { #the-escape-hatch }

!!! warning "Nie ma żadnych bypass actors"

    Właściciel, który musi coś zmerge'ować natychmiast, wyłącza ruleset,
    merge'uje i włącza go z powrotem — trzy kliknięcia i wpis w audycie, czyli
    właściwa ilość tarcia dla czegoś, co powinno być rzadkie.

Jest to zamierzone: bypass, który jest zawsze dostępny, to bypass używany co
tydzień i ścieżka wydawnicza, której nikt nie umie opisać.

## Aktualizacje zależności { #dependency-updates }

Backend chodzi co tydzień, z frameworkami agentowymi zgrupowanymi osobno od
reszty — zmieniają się szybko, a ten codebase ma za nimi nadążać. Frontend chodzi
co miesiąc, po siedmiodniowym okresie schłodzenia.

Dependabot proponuje aktualizacje **bezpośrednich** zależności. Wszystko pod nimi
rusza się tylko wtedy, gdy pociągnie je za sobą zależność bezpośrednia, i
dlatego istnieje `.github/workflows/dependency-freshness.yml`: raz w tygodniu
podnosi cały lock — razem z pakietami tranzytywnymi — uruchamia na nim cały zestaw
testów i zakłada issue, jeśli to coś zepsuje. Nic nie jest commitowane; upgrade
jest wyrzucany razem z runnerem. `make deps-upgrade-all` robi lokalnie to samo
i tak właśnie reprodukuje się czerwone issue stamtąd.

Dwie rzeczy w tym nie są oczywiste i obie kosztowały czas, zanim je zrozumiano:

- **Wzorzec grupy musi nieść końcową `*`, żeby dopasować zależność zapisaną
  z extras.** `pydantic-ai-slim[openrouter,…]` nie jest dopasowywany przez
  `pydantic-ai-slim`. Ta cisza kosztowała miesiące: grupa `agent-frameworks` nie
  otworzyła ani jednego pull requesta, a runtime jechał w
  `backend-everything-else` razem ze swoimi majorami. Odwrotnie `fastapi`
  zostaje dokładny, bo jest zadeklarowany bez extras i nie potrzebuje wildcardu;
  kiedyś musiał go unikać, bo `fastapi*` łapało też `fastapi-cache2`, dopóki ta
  zależność nie została usunięta w #155.
- **Dependabot nie potrafi zaktualizować `frontend/bun.lock`.** Jego ekosystem
  npm zna `package-lock.json`, `yarn.lock` i `pnpm-lock.yaml`, ale nie ten od
  buna. Więc bump frontendu przychodzi jako samo `package.json`, a `bun install
  --frozen-lockfile` odrzuca niezgodność, przez co `test-frontend` i `e2e` robią
  się czerwone z powodu niezwiązanego z zależnością. **Wygeneruj go ręcznie** na
  gałęzi pull requesta:

  ```bash
  cd frontend && bun install --lockfile-only && git commit -am "build(deps): sync bun.lock"
  ```

  Zautomatyzowanie tego jest trudniejsze, niż wygląda: workflow na
  `pull_request` dostaje token tylko do odczytu, kiedy wyzwolił go Dependabot,
  cokolwiek mówi jego blok `permissions`, więc nie może wypchnąć wyniku z
  powrotem.

## Recenzje { #reviews }

[Automatyczny recenzent](code-review.md) uruchamia się na każdym pull requeście.
Nigdy nie jest wymaganym checkiem, więc nie może położyć builda — ale jego
ustalenia są wątkami recenzji, a ruleset powyżej wymaga ich rozwiązania.
Odpowiedź nie wystarczy — ktoś musi oznaczyć wątek jako rozwiązany, zanim wróci
przycisk merge. Zobacz [code-review.md](code-review.md).

Jakościowa połowa CodeQL otwiera wątki na tych samych zasadach, jako
`github-code-quality[bot]`. Nie da się jej filtrować po regule ani po ścieżce —
jedynym przełącznikiem jest wyłączenie, dla całego języka, co nie jest wymianą
wartą zrobienia — więc
[code-review.md](code-review.md#codeql-and-the-findings-that-block-a-merge)
wymienia zamiast tego ustalenia już rozstrzygnięte, a rozwiązanie jednego z nich
kosztuje kliknięcie, a nie esej.

## Podsumowanie { #recap }

- **Jedna długo żyjąca gałąź.** Gałąź, pull request, squash przy mergu.
- Push anuluje przebieg w locie, więc kolejny push jest też decyzją o tym, żeby
  przestać interesować się poprzednią odpowiedzią.
- CI uruchamia **mniej jobów niż `make check`** — pominięty wymagany check to
  zaliczenie, a nie problem.
- `main` jest wyjęty spod anulowania, a sposobem, w jaki jest wyjęty, jest grupa
  concurrency niosąca `github.run_id` — unikalny dla przebiegu, więc żaden
  przebieg na `main` nie anuluje innego.
