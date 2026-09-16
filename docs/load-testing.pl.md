---
source_sha: "a434e301f063"
---

# Testy obciążeniowe i odpornościowe { #load-and-resilience-testing }

AgenticOS streamuje, uruchamia pracę w tle i trzyma otwarte gniazda, a nic z tego
nie mówi, ile tego jedno wdrożenie uniesie naraz. Kod asynchroniczny nie jest
wynikiem pojemnościowym, a zielony zestaw testów jednostkowych nie jest testem
obciążeniowym. Dlatego istnieje zestaw, który to mierzy — w `loadtest/` — a ta
strona mówi, co mierzy, co nazywa zaliczeniem i jak go powtórzyć.

Liczby z przebiegu należą do maszyny, na której powstały. Nic tutaj nie dowodzi
architektonicznego celu tysiąca użytkowników z NFA-006, a pojedynczy przebieg na
jednym hoście dowodzi celu opóźnień z NFA-001 tylko dla tego hosta — obie sprawy
są odnotowane tam, gdzie dotykają progu, zamiast być po cichu zadeklarowane.

## Obciążenie { #the-workload }

Ruch wdrożenia to głównie ludzie czytający listy, część z nich rozmawiająca z
agentem, kilka osób wysyłających dokument i strużka zdarzeń odpalających rutyny,
których nikt nie ogląda. Miks mówi to liczbami:

| Obciążenie | Udział | Czym jest jedno żądanie |
|---|---|---|
| `api_read` | 45% | Uwierzytelniona lista — agenty, runy, rozmowy |
| `chat_stream` | 20% | Tura czatu po WebSocket, co piąta anulowana w połowie |
| `agent_run` | 15% | `POST /agents/{id}/run` — ten sam runner bez gniazda |
| `rag_query` | 12% | Retrieval: jedno osadzenie, jedno wyszukiwanie wektorowe |
| `ingest` | 5% | Wysłany dokument, który to API przyjmuje, a worker indeksuje |
| `trigger_fire` | 3% | Podpisana dostawa webhooka odpalająca rutynę |

Udziały są w `loadtest/scenario.py`, każdy to jedna linia i to jest ta część, z
którą można się nie zgodzić. Wdrożenie o innym profilu ruchu edytuje je i
uruchamia ponownie; nie może się zdarzyć, że ktoś cytuje liczbę z miksu, którego
nikt nie obejrzał.

### Tempo napływu, a nie pula wątków { #arrival-rate-not-a-worker-pool }

Żądania są oferowane **według harmonogramu**. Zamknięta pętla N wątków, z których
każdy czeka na poprzednika, sama zmniejsza tempo napływu dokładnie wtedy, gdy
serwer zwalnia — więc serwer, który się przewrócił, raportuje wygodne opóźnienia
i przepustowość, która po cichu spadła o połowę. Otwarty model napływu dalej
oferuje pracę w zadanym tempie i pozwala kolejce rosnąć, a to jest właśnie
przedmiot badania.

To, którym obciążeniem jest dane żądanie, pochodzi z ciągu o niskiej rozbieżności,
a nie z kostki, więc dwa przebiegi w tym samym tempie wysyłają tyle samo uploadów,
a każda różnica między nimi należy do platformy.

### Fazy { #the-phases }

| Faza | Sekundy | Oferowane na sekundę | Po co |
|---|---|---|---|
| `ramp` | 60 | 4 | Zimny cache to nie stan ustalony |
| `sustain` | 180 | 12 | **Każdy próg jest oceniany względem tej fazy** |
| `burst` | 45 | 36 | Trzykrotność tempa, czyli tyle, ile wygląda rozejście się zadań |
| `recover` | 60 | 12 | Platforma, która się podnosi, i taka, która zostaje zdegradowana, w trakcie burstu wyglądają identycznie |

## Co liczy się jako zaliczenie { #what-counts-as-a-pass }

Te progi są **zaproponowane, nie uzgodnione**. Akceptacja NFA-004 prosi o
uzgodnione; podanie ich tutaj daje przebiegowi werdykt zamiast ściany liczb i
sprawia, że rozmowa dotyczy konkretnej wartości, a nie tego, czy w ogóle ma
jakaś być. Nic tutaj nie jest zobowiązaniem złożonym w czyimś imieniu.

| Obciążenie | Metryka | Limit | Dlaczego tam |
|---|---|---|---|
| `api_read` | p95 | 300 ms | Jedno zapytanie za sprawdzeniem uprawnień; powyżej to kolejkowanie, nie praca |
| `api_read` | odsetek błędów | 0,1% | Miejsce na odnowione połączenie i na nic więcej |
| `chat_stream` | p95 pierwszego tokenu | 1500 ms | Udział platformy: gniazdo, auth, spec, zdolności, wiersz runu |
| `chat_stream` | odsetek błędów | 1% | Zerwane gniazdo kosztuje kogoś jego odpowiedź |
| `agent_run` | p95 | 5000 ms | Cała ścieżka runu wobec stuba, od początku do końca |
| `rag_query` | p95 | 1200 ms | Ogranicza pgvector i pulę przed nim |
| `ingest` | odsetek błędów | 0% | Upload przyjęty i zgubiony to najgorsza awaria z tej listy |
| `trigger_fire` | odsetek błędów | 0% | 2xx oznacza wzięcie odpowiedzialności za zdarzenie |

Każdy jest oceniany osobno dla obciążenia i to jest celowe. Jedna liczba dla
mieszanego przebiegu nie opisuje niczego: upload i lista to nie to samo żądanie.

Obciążenie, które nie dało żadnej próbki, czyta się jako **niezmierzone**, nigdy
jako zaliczone. Przebieg, który pominął scenariusz i zaraportował dla niego
zielone, jest tą porażką, której cały ten plik ma zapobiec.

## Model jest stubem i celowo powolnym { #the-model-is-a-stub-and-slow-on-purpose }

`loadtest/stub_model.py` serwuje API Chat Completions oraz endpoint osadzeń, z
opóźnieniem pierwszego tokenu i tempem na token, które przebieg podaje. Test
obciążeniowy, którego model odpowiada natychmiast, mierzy platformę pod
obciążeniem, które nie może istnieć: każdy prawdziwy dostawca potrzebuje setek
milisekund, a to, ile współbieżności wdrożenie utrzyma, zależy od tego, jak długo
run trzyma swoje zasoby w oczekiwaniu.

Można mu też kazać się psuć — `--error-rate` odrzuca ten udział z 500, a
`--timeout-rate` trzyma je otwarte — i to jest odpornościowa połowa NFA-004. To,
co platforma robi, gdy jej dostawca zawodzi, jest własnością platformy i nie da
się tego zmierzyć wobec dostawcy, który się zachowuje.

Nic w domyślnym przebiegu nie dotyka płatnego dostawcy. Osadzenia też są stuba,
sięgane tak, jak sięga się bezkluczowego endpointu Ollamy, więc wdrożenie bez
żadnego klucza dostawcy nadal da się zmierzyć. Pomiar end-to-end wobec prawdziwego
dostawcy jest świadomym aktem: skieruj na niego model profile fikstury i licz się
z jego własnymi opóźnieniami i limitami w liczbach.

## Uruchamianie { #running-it }

Cztery rzeczy muszą być na miejscu, a `run.py` odmawia startu bez którejkolwiek z
nich, zamiast mierzyć wdrożenie, które nie może wykonać pracy:

1. zmigrowana baza i Redis;
2. odpowiadający model stub, **pod adresem, do którego API sięgnie** — patrz niżej;
3. fikstura — `make load-seed`, raz;
4. Prefect, jeśli obciążenie `trigger_fire` ma cokolwiek znaczyć. Bez niego
   webhook jest przyjmowany, a jego dyspozycja zawodzi, co raport pokazuje jako
   500 na tym obciążeniu, zamiast to ukrywać.

### Gdzie ma słuchać stub { #where-the-stub-has-to-listen }

To *API* woła stub, nie driver, więc adres zasiany w model profile musi działać
stamtąd, gdzie API działa. Dwie topologie:

| API działa | Bind | Seed |
|---|---|---|
| Na tym hoście (`uv run uvicorn …`) | `127.0.0.1` (domyślnie) | `http://127.0.0.1:4020` (domyślnie) |
| W stosie Compose (`make dev`) | `LOAD_STUB_BIND=0.0.0.0` | `LOAD_STUB_URL=http://host.docker.internal:4020` |

Loopback w kontenerze `app` to kontener, a nie host, więc drugi wiersz nie jest
tam opcjonalny — a pomyłka wywraca preflight komunikatem o pustej kolekcji, a nie
o adresie, bo osadzenia też nie dotrą do stuba.

```bash
make load-stub-model                       # terminal pierwszy
make load-seed                             # raz
make load-test API_PID=$(pgrep -f uvicorn | head -1) \
  DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/agenticos \
  > loadtest/results/$(date +%F)-thismachine.md
```

`API_PID` i `DATABASE_URL` są opcjonalne. Bez nich przebieg mierzy żądania i
**nazywa sondy, których nie mógł wykonać** w raporcie, zamiast drukować dla nich
zera.

Plik fikstury nie trzyma **żadnych poświadczeń**. Przebieg sam się loguje przez
`--email` i `--password` (domyślne z seedu), więc żaden token nie ląduje na dysku,
a fikstura zasiana wczoraj nadal działa dziś — wygasający token w pliku był i
sekretem w spoczynku, i przebiegiem odmawiającym bez powodu.

Dwa ustawienia warto podnieść na przebieg pojemnościowy, a linia topologii w
raporcie powinna powiedzieć, kiedy to zrobiono:

- **`RATE_LIMIT_RUN_PER_MINUTE`**. Limit jest na wywołującego, a driver to jedna
  tożsamość zastępująca wielu, więc przy domyślnych 30 eksperyment mierzy
  ogranicznik, a nie platformę.
- **`UVICORN_WORKERS`**, jeśli pytanie dotyczy hosta, a nie jednego workera.

`--scale 0.1` skraca każdą fazę i nie zmienia nic więcej, do sprawdzenia samego
harnessu. Skrócenie przebiegu przez obniżenie *tempa* byłoby innym eksperymentem
pod tą samą nazwą.

`--connections` ogranicza własne gniazda drivera i domyślnie bierze szczytowe
tempo scenariusza razy najwolniejsze żądanie — 3240 dla dostarczonych faz. Limit
poniżej tego zamienia przebieg z otwartym napływem w zamknięty dokładnie w
burście, czyli wtedy, kiedy to ma znaczenie: żądania kolejkują się w kliencie, a
część opóźnień w raporcie należy do samego drivera.

## Czytanie raportu { #reading-the-report }

Cztery sekcje, w kolejności, w jakiej padają pytania: co uruchomiono, co się
działo w `sustain`, co w `recover` i czy przeszło. Werdykt jest ostatni celowo —
werdykt na górze zachęca, żeby przeczytać tylko jego, a liczby próbek pod nim
mówią, czy ogon to wniosek, czy trzy żądania.

Nagłówek niesie dwie liczby, które warto sprawdzić przed wszystkim innym.
**Zaoferowane wobec zapisanych** muszą się zgadzać: każde zaoferowane żądanie
zostawia próbkę, udaną albo nie, łącznie z porzuconym na koniec przebiegu, a
niedobór oznacza, że odsetki błędów liczone są z mianownika mniejszego niż
obciążenie — raport mówi to w banerze i nazywa sam siebie bezużytecznym.
**Spóźnione wysyłki** to przyznanie drivera, że wypadł z własnego harmonogramu i
sam stał się częścią pomiaru.

Przepustowość dla fazy ustalonej pokazana jest dwa razy: ukończenia, które
wylądowały w oknie, i żądania zaoferowane w tym czasie. Rozjeżdżają się, gdy
wdrożenie nie nadąża, a tylko wtedy ta liczba jest ciekawa.

Percentyle są **najbliższej rangi**, nie interpolowane: interpolowany p99 z
dziewięćdziesięciu próbek to liczba pomiędzy dwoma pomiarami, której nic nie
zaobserwowało. A opóźnienie liczy się tylko po **udanych** żądaniach. Żądanie
odrzucone w 3 ms nie jest szybkim żądaniem, a wpuszczenie go do rozkładu jest tym,
jak przebieg, który się przewrócił, raportuje swoje najlepsze percentyle w
historii; porażki są liczone osobno i nazwane.

CPU to różnica skumulowanego czasu procesora procesu w każdym interwale
próbkowania, a nie `%CPU` z `ps` — procps definiuje to jako czas procesora przez
całe życie procesu i wprost mówi, że to nie jest wykorzystanie, więc próbkowanie
tego uśredniłoby krótkie nasycenie, które burst ma wywołać. Rozdzielczość jest
więc rozdzielczością zegara `ps` na interwał próbkowania, czyli na Linuksie jedna
sekunda na dwie.

## Czego ten zestaw nie mierzy { #what-this-suite-does-not-measure }

Powiedziane wprost, a nie zostawione do odkrycia:

- **Przepustowości workera.** Obciążenia `ingest` i `trigger_fire` mierzą
  *przyjęcie* — API odpowiada 202 i oddaje pracę flow. To, jak szybko worker
  opróżnia tę kolejkę, jest pomiarem tam, gdzie jest worker, i nie jest tu
  deklarowane.
- **Niczego o prawdziwym dostawcy.** Każde opóźnienie w domyślnym przebiegu to
  platforma plus podane opóźnienie stuba.
- **Konsoli.** Frontend nie jest ćwiczony; to są ścieżki API.
- **Klastra.** Jedno wdrożenie, jedna baza. Cel NFA-006 jest architektoniczny, a
  przebieg na jednym hoście nie mówi o nim nic w żadną stronę.

## Wykonane przebiegi { #the-measured-runs }

Commitowane w `loadtest/results/`, każdy z maszyną, topologią i datą na górze, bo
liczba bez nich nie jest wynikiem.

Na razie są dwa przebiegi, na tej samej maszynie, różniące się jednym ustawieniem:

| | `2026-09-16-macbook-default-pool.md` | `2026-09-16-macbook-pool-raised.md` |
|---|---|---|
| Pula | 5 + 10 overflow (domyślnie) | 20 + 30 overflow |
| Ustalone 12/s | wszystkie progi spełnione, zero porażek | wszystkie progi spełnione |
| Cały przebieg, z burstem | **1537 z 4740 zawiodło**, 6559 timeoutów puli | 13 zawiodło, ani jednego timeoutu puli |
| **Po burście** | **66–100% wciąż zawodzi** | **zero porażek, opóźnienia opadają** |

Wniosek i powód, dla którego są dwa: **wiążącym ograniczeniem tego obciążenia jest
pula połączeń, a nie procesor.** Oba przebiegi osiągnęły szczyt około 90% *jednego*
rdzenia na dziesięciordzeniowej maszynie, bo worker był jeden. Kolejność
podnoszenia jest więc taka: najpierw pula, potem `UVICORN_WORKERS` — a ich iloczyn
musi zmieścić się pod `max_connections` bazy, skoro jeden worker osiągnął już 84 z
domyślnych 100.

Wiersz o odbudowie trzeba przeczytać pierwszy. Przy domyślnej puli żądanie, które
nie dostanie połączenia, czeka pełne trzydzieści sekund `DB_POOL_TIMEOUT`, więc
zaległość przeżywa burst, który ją stworzył, i wdrożenie nadal zawodzi przy tempie,
które dziesięć minut wcześniej obsługiwało spokojnie. Każdy plik wyniku niesie
całe rozumowanie.
