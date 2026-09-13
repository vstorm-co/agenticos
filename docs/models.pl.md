---
source_sha: d4f249f20433
---

# Modele i providery { #models-and-providers }

!!! tip "Decydujesz, a nie konfigurujesz?"

    Ta strona jest o maszynerii. [Wybór modelu](choosing-models.md) odpowiada na
    pytanie, *którego* modelu agent powinien używać — otwarte wagi czy zamknięte,
    co naprawdę napędza rachunek i dlaczego ten wybór jest odwracalny.

Szablon, z którego wyrosła ta platforma, budował jeden model ze zmiennych
środowiskowych.

To przestaje działać w chwili, gdy kilka organizacji dzieli jeden deployment:
każda potrzebuje własnego klucza, własnej wartości domyślnej i możliwości
zrotowania jednego albo drugiego bez redeployu.

Więc model jest konstruowany **per run**, z bazy danych:

```
model profile → credential → unsealed secret → provider client → Model
```

Nic z tego, którego modelu używa agent, nie mieszka w `.env`.

## Profil modelu { #a-model-profile }

Wiersz w organizacji: etykieta, provider, id modelu, domyślne ustawienia i to,
którym [sekretem w vault](secrets.md) się uwierzytelnić.

Spec agenta wskazuje jeden przez `model_profile_id`, a run go rozwiązuje.

!!! tip "Id modelu jest wolnym tekstem celowo"

    Jest picker, który pomaga, ale pole przyjmuje cokolwiek wpiszesz.

    Provider wypuszcza coś nazajutrz po tym, jak jakakolwiek lista tutaj została
    rozgrzana, a pole, które nie potrafi wyrazić „o ten”, to pole, które ludzie
    obchodzą, edytując speca ręcznie.

### Fallbacki { #fallbacks }

Profil może wymienić profile zapasowe, wypróbowywane po kolei. Awaria jednego
providera nie powinna kłaść agentów organizacji, gdy ma ona drugi klucz albo
skonfigurowanego drugiego providera.

!!! warning "Fallback jest niewidoczny w zapisie runa"

    Wiersz runa zapisywany jest przed pierwszym żądaniem i niesie etykietę,
    providera oraz id sekretu profilu **podstawowego**. Jeśli turę obsłużył
    fallback, run i tak nazywa podstawowy.

    Więc „ile wydaliśmy w OpenAI” i „który klucz kosztuje najwięcej” odpowiadają
    profilem, którego *zapytano* jako pierwszego, a nie tym, który odpowiedział.
    Warto to wiedzieć, zanim oprzesz się na tych liczbach w czasie awarii.

### Ustawienia modelu { #model-settings }

Per profil, nadpisywalne per agent przez `model_settings` w specu:
`temperature`, `top_p`, `max_tokens`, `parallel_tool_calls`, `timeout`. Zobacz
[referencję speca](reference/spec.md#model-settings).

Nakładu rozumowania **nie** ma tutaj. Jest nim
[capability `thinking`](reference/capabilities.md#thinking), bo „myśl mocniej” to
decyzja o tym, do *czego* agent służy, a nie pokrętło na połączeniu — i dlatego,
że spec, który ustawia to jako ustawienie modelu, przestaje być przenośny przy
zmianie modelu.

## Providery { #providers }

Dwadzieścia siedem, czyli wszystko, co Pydantic AI dostarcza i na co profil
czatowy może wskazać.

Nie ma tutaj buildera per provider. Pydantic AI wnioskuje klasę providera i
opakowanie modelu z id, a tym, co ta platforma wciąż musi wiedzieć, jest to,
czego wnioskowanie wiedzieć nie może: **jakiego kształtu poświadczenia chce dany
provider.**

!!! info "Co znaczy Custom URL"

    SDK providera nazywa parametr endpointu, więc możesz skierować profil na
    bramę, proxy LiteLLM albo serwer modelowy we własnej sieci zamiast na
    publiczne API dostawcy.

    To pole na **profilu**, a nie na kluczu. Klucz mówi, co uwierzytelnia,
    endpoint mówi, dokąd idzie żądanie — więc ten sam klucz może stać przed proxy
    stagingowym i produkcyjnym jako dwa profile.

    Ustawisz to w **Agents → add a model → Endpoint**, które pojawia się tylko dla
    providerów oznaczonych poniżej. Zapisanie endpointu dla providera, który go
    nie ma, zostaje odrzucone, a nie przyjęte i porzucone.

### Hostowane { #hosted }

| Provider | id | Poświadczenie | Custom URL |
|---|---|---|---|
| OpenAI | `openai` | klucz API albo brak | ✓ |
| Anthropic | `anthropic` | klucz API | ✓ |
| Google Gemini | `google` | klucz API | ✓ |
| OpenRouter | `openrouter` | klucz API | |
| Alibaba Cloud | `alibaba` | klucz API | ✓ |
| Cerebras | `cerebras` | klucz API | |
| DeepSeek | `deepseek` | klucz API | |
| Fireworks AI | `fireworks` | klucz API | |
| GitHub Models | `github` | klucz API | |
| Groq | `groq` | klucz API | |
| Heroku AI | `heroku` | klucz API | ✓ |
| Mistral | `mistral` | klucz API | |
| Moonshot AI | `moonshotai` | klucz API | |
| Nebius AI Studio | `nebius` | klucz API | |
| OVHcloud AI Endpoints | `ovhcloud` | klucz API | |
| SambaNova | `sambanova` | klucz API | ✓ |
| Together AI | `together` | klucz API | |
| Vercel AI Gateway | `vercel` | klucz API | |
| Z.AI | `zai` | klucz API | |
| xAI (Grok) | `xai` | klucz API | ✓ (`api_host`) |
| Cohere | `cohere` | klucz API | |
| Hugging Face | `huggingface` | klucz API | ✓ |

### Samodzielnie hostowane { #self-hosted }

| Provider | id | Poświadczenie | Custom URL |
|---|---|---|---|
| Ollama | `ollama` | brak | ✓ |
| proxy LiteLLM | `litellm` | brak | ✓ (`api_base`) |

Te dwa są powodem, dla którego „brak poświadczenia” jest zapisanym **rodzajem**, a
nie pustym stringiem. Serwer modelowy we własnej sieci zwykle nie ma się wobec
czego uwierzytelniać, a vault odrzuca pusty sekret — więc resolver przełącza się
po całościowym zbiorze, zamiast traktować brakującą wartość jako przypadek
szczególny.

**Profil bez klucza potrzebuje swojego endpointu i to jedyne, czego potrzebuje.**
Pole klucza staje się opcjonalne, gdy tylko endpoint zostanie wypełniony. Bez
endpointu profil jest odrzucany: nie ma publicznego API, na które można by spaść,
ani nic, czym się uwierzytelnić.

!!! note "To endpoint oznacza profil jako samodzielnie hostowany, a nie `keyless`"

    `keyless` jest prawdziwe także dla `openai`. Serwery zgodne z OpenAI (vLLM, LM
    Studio, proxy LiteLLM) mówią jego API Chat Completions, i dlatego profil
    `openai` budowany jest jako `openai-chat`.

    Więc samo „brak klucza” nie odróżnia świadomie lokalnego modelu od profilu,
    któremu klucz usunięto — a klucz obcy sekretu ma `ON DELETE SET NULL`, co
    czyni ten drugi przypadek czymś zwyczajnym. Run rozwiązuje profil bez klucza
    tylko wtedy, gdy niesie on endpoint; w przeciwnym razie jest odrzucany z tym
    samym komunikatem „no key configured”, który miał zawsze.

### Kiedy poświadczeniem nie jest klucz API { #when-the-credential-is-not-an-api-key }

| Provider | id | Poświadczenie |
|---|---|---|
| Azure OpenAI | `azure` | klucz **+** endpoint **+** przypięta wersja API |
| AWS Bedrock | `bedrock` | access key id, klucz tajny, region, opcjonalny token sesji |
| Google Vertex AI | `google_cloud` | JSON konta serwisowego |

Te trzy są powodem, dla którego sekret w ogóle ma *rodzaj*. Formularz, który
zbierałby dla Azure jeden nieprzejrzysty token, zbierałby coś, co da się wypełnić
poprawnie, a i tak zawiedzie przy pierwszym runie. Zobacz
[rodzaje sekretów](secrets.md#kinds).

!!! note "Dwa id są przepisywane w drodze do SDK"

    Profil `openai` budowany jest jako `openai-chat`, bo samo `openai` wnioskuje
    Responses API, a serwery zgodne z OpenAI — vLLM, LM Studio, proxy LiteLLM —
    go nie implementują.

    `google_cloud` budowany jest jako `google-cloud`. Żadne z nich nie zmienia
    tego, co zapisujesz.

### Celowo nieobecne { #deliberately-absent }

Czterech nazw, które Pydantic AI zna, tutaj nie ma. `sentence-transformers` i
`voyageai` to modele embeddingowe, `bedrock-mantle` nie jest providerem czatowym,
na który profil może wskazać, a `gateway` nie rozwiązuje się do klasy providera —
to prefiks routujący nad pozostałymi.

`tests/test_model_profiles.py` konstruuje każdy wpis w katalogu, więc provider nie
może być wybieralny w Builderze, nie będąc konstruowalnym w czasie działania.

## Która lista odpowiada na które pytanie { #which-list-answers-which-question }

Sześć rzeczy w tym repozytorium wie coś o modelach i providerach i **nie** są to
sześć kopii jednej listy. Każda odpowiada na inne pytanie, a ta, z której
wywiedzione są wszystkie pozostałe, jest pierwsza:

| Pytanie | Odpowiada |
|---|---|
| Na których providerów może wskazać profil i jakiego poświadczenia chce każdy z nich? | `PROVIDERS` w `backend/app/agents/model_resolver.py` — **źródło prawdy**, i tylko dla tej części, której wnioskowanie modelu znać nie może |
| Jak skonstruować klienta? | Własne `infer_provider_class` / `infer_model` z `pydantic_ai`. Nie sprawa tej platformy i celowo nie powtarzane tutaj |
| Jak odczytać żywą listę modeli tego providera? | `backend/app/core/catalog/model_listings.json` |
| Co zaproponować, kiedy providera nie da się zapytać? | `backend/app/core/catalog/curated_models.json` |
| Ile kosztuje ten model i ile kontekstu przyjmuje? | migawka `genai-prices`, przez `model_catalog.priced_model` |
| Które modele rysują obrazy? | `backend/app/core/catalog/image_models.json`, plus własna odpowiedź SDK o to, którzy providerzy w ogóle potrafią rysować |

!!! info "Wszystko poniżej pierwszego wiersza jest z niego wywiedzione"

    Wywiedziona kopia, która się rozjedzie, nie psuje niczego w czasie działania.
    Pokazuje picker dla providera, który nie istnieje, albo pomija tego, który
    istnieje.

    `tests/test_model_catalog.py::TestOneAnswerPerQuestion` jest tym, co zamienia
    to w psujący się build — i wymaga, żeby każdy provider pojawił się **na tej
    stronie**.

Każdy klucz w którymkolwiek z plików katalogu musi nazywać providera, którego ma
`PROVIDERS`. Tak samo każdy wpis w katalogu obrazów. I każdy provider musi pojawić
się na tej stronie. Dodanie dwudziestego ósmego to jedna edycja plus to, o co
poprosi wtedy ten test.

Dwa przejścia warto znać, bo są to wyszukania, które mogą nie odpowiedzieć niczym:

- Migawka cen zapisuje trzech providerów inaczej — `xai` to `x-ai`, `bedrock` to
  `aws`, `google_cloud` to `google` — a `_PRICE_PROVIDER_ALIASES` je mostkuje.
- Katalog obrazów niesie własną parę `provider` i `prefix`, co jest już trzecim
  słownictwem.

## Które modele oferuje provider { #which-models-a-provider-offers }

Pole id modelu wypełniane jest z dwóch źródeł, w tej kolejności — i z żadnego, dla
siedmiu providerów, co odpowiedź mówi wprost.

### Żywe { #live }

Dwudziestu providerów publikuje endpoint listy i jest to jedyne źródło, które wie
o modelu wypuszczonym dziś rano:

`anthropic`, `openai`, `google`, `openrouter`, `groq`, `mistral`, `together`,
`cohere`, `deepseek`, `xai`, `sambanova`, `vercel`, `ovhcloud`, `huggingface`,
`cerebras`, `fireworks`, `nebius`, `moonshotai`, `zai`, `alibaba`.

Kształty odpowiedzi się różnią — tablica siedzi w `data`, w `models` albo w
korzeniu dokumentu; id to `id`, `name` albo `model`; Gemini poprzedza je
`models/` — więc każdy opisany jest danymi, a nie gałęzią kodu. Cache'owane w
procesie przez godzinę; te listy ruszają się w skali tygodni.

**Pięć z nich nie potrzebuje żadnego poświadczenia** — `openrouter`, `sambanova`,
`vercel`, `ovhcloud` i `huggingface` — i to właśnie czyni je wartymi posiadania:
picker wypełnia się, zanim ktokolwiek zapisał klucz dla tego providera. Pozostałych
piętnastu pytanych jest własnym kluczem organizacji, kiedy taki jest.

Sześciu providerów wciąż nie publikuje niczego, co da się tu odczytać: `github`
(jego ścieżka katalogu zniknęła), `heroku`, `azure`, `bedrock`, `google_cloud`
oraz proxy `litellm`, którego lista jest tym, co deployment za nim postawił.
`ollama` odpowiada we własnej sieci deploymentu, a nie pod stałym hostem, więc też
nie jest wymieniony.

!!! warning "Pusta lista modalności znaczy *niepodane*, nigdy „tylko tekst”"

    `openrouter` i router Hugging Face oba niosą
    `architecture.output_modalities`, a wpis listingu może nazwać tę ścieżkę.
    Nikt inny tego nie podaje.

    Klient filtrujący po tym musi traktować brak jako nieznane, bo inaczej ukrywa
    modele, które działają. To metadana, po której klient może zawężać; to *nie*
    jest to, jak capability obrazów wybiera swoje modele — tym jest plik katalogu
    plus własna odpowiedź SDK o to, którzy providerzy w ogóle potrafią rysować —
    zobacz [Generowanie obrazów](reference/capabilities.md#image-generation).

### Kuratorowane { #curated }

Krótka lista per provider, używana wtedy, gdy provider nic nie publikuje, gdy
wywołanie zawiedzie albo gdy nie ma klucza, żeby je wykonać.

Mieszka w `backend/app/core/catalog/curated_models.json` obok innych katalogów
deploymentu, więc dodanie modelu to jeden wpis, a nie edycja Pythona — a same
listingi to `model_listings.json` w tym samym katalogu, co czyni z nowego
providera także dane o endpoincie.

Jest celowo krótka i celowo **nie** wzięta z `genai-prices`, który i tak jest
zależnością i owszem wymienia modele.

To zbiór danych *cenowych*. Niesie `ada` i `babbage` pod OpenAI, `claude-2` pod
Anthropic, 690 wierszy pod OpenRouter i prawie nic nie oznacza jako przestarzałe
— posortowane alfabetycznie, pierwszym, co picker zaproponowałby dla OpenAI,
byłoby `ada`. Krótka aktualna lista bije długą mylącą.

Do czego biblioteka *jest* używana, to ta połowa, która gnije. **Każda długość
kontekstu bierze się z migawki w momencie odczytu**, więc żadne okno nie jest tu
zapisane; dwa, które były, już się zestarzały, a jedno z nich było zapisane
dwukrotnie z dwiema różnymi liczbami.

A kuratorowane id, o którym migawka nigdy nie słyszała, wywraca zestaw testów, i
tak właśnie literówka albo wycofany model jest łapany zamiast wysyłany jako lista
rozwijana, na którą provider odpowiada 404. Model, który migawka zna, ale którego
nie wycenia, po prostu nie ma okna, co jest nullem opisanym poniżej.

| Provider | Kuratorowane id |
|---|---|
| `anthropic` | `claude-opus-5`, `claude-sonnet-5`, `claude-fable-5`, `claude-haiku-4-5` |
| `openai` | `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.3-codex` |
| `google` | `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-pro-preview` |
| `deepseek` | `deepseek-v4-pro`, `deepseek-v4-flash` |
| `xai` | `grok-4.5`, `grok-4.3` |
| `groq` | `openai/gpt-oss-120b`, `llama-3.3-70b-versatile` |
| `openrouter` | pięć popularnych id działających u wielu providerów |

### Ani jedno, ani drugie — i mówi to wprost { #neither-and-it-says-so }

Siedmiu providerów nie publikuje listingu, który ta platforma potrafiłaby
odczytać, i nie ma kuratorowanego wpisu — `github`, `heroku`, `ollama`,
`litellm`, `azure`, `bedrock` i `google_cloud`.

Pole `source` odpowiedzi ma dla nich wartość `unlisted`, **a nie** `curated`.
Pusta krótka lista nie jest krótką listą, a twierdzenie, że jest, zamienia „ta
platforma nie potrafi wyliczyć tego providera” w „ten provider nie ma modeli”
(#923). Picker prosi w zamian o id.

`ollama` i `litellm` to te warte podłączenia — oba publikują `/v1/models` w
kształcie OpenAI pod endpointem, który profil i tak już zapisuje — a to wymaga,
żeby listingowi podać bazowy URL, czym stałe `ListingSpec.url` być nie może.

Żadne ze źródeł nie jest autorytatywne i dlatego pole pozostaje wolnym tekstem.

## Okno, które model przyjmuje, czytane jest raz i zapamiętywane { #the-window-a-model-accepts-is-read-once-and-kept }

Listing zwykle niesie informację o tym, ile tokenów model przyjmuje, a profil
zapisuje ją jako `context_length` w chwili utworzenia.

Ta liczba jest tym, na czym wyzwala się
[zarządzanie kontekstem](reference/capabilities.md#context-management): kompaktowanie
przy ułamku okna to jedyne ustawienie, które pozostaje poprawne, gdy agent
przenosi się na inny model.

!!! danger "Dlaczego jest zapisywana, a nie rozwiązywana per run"

    Ścieżka żądania nie może wołać providera, a jedyne, co mogłaby poza tym
    sprawdzić, to dołączona migawka cen — która jest tu błędna w kierunku
    psującym run.

    Ta migawka zapisuje 1 000 000 dla `anthropic:claude-sonnet-4-5` wobec
    rzeczywistych 200 000, więc wyzwalacz przy 90% ląduje powyżej prawdziwego
    sufitu i kompaktowanie nigdy nie odpala, zanim provider odrzuci żądanie.
    Profil z fallbackami jest gorszy: buduje `FallbackModel`, którego złożone id
    nie rozwiązuje się do niczego w ogóle.

Null znaczy **niezapisane**, a nie zero: profil starszy niż ta kolumna, provider,
który nie publikuje długości, lista kuratorowana albo listing, którego nie dało się
osiągnąć. Capability rozwiązuje wtedy okno samo, dokładnie tak jak wcześniej.

Jeśli wiesz lepiej niż oba, ustaw `context_window` na powiązaniu. Provider
publikuje maksimum, jakie model *da się* zmusić przyjąć, a deployment w becie albo
w bramkowanym progu dostaje mniej.

Łańcuch fallbacków niesie liczbę **podstawowego**. `FallbackModel` nie ma
własnego okna, a to, do którego modelu run dotrze, nie jest wiadome, dopóki jeden
nie odmówi.

## Ile kosztuje run { #what-a-run-costs }

Ceny pochodzą z dołączonej migawki
[`genai-prices`](https://github.com/pydantic/genai-prices). Nic po nie nie dzwoni
do domu, co oznacza dwie rzeczy warte wiedzenia:

- Model zbyt nowy dla migawki jest **niewyceniony**, a run, który go zawiera,
  zapisywany jest jako *częściowo wyceniony*, a nie jako kosztujący zero. Budżet,
  który po cichu traktowałby nieznany model jako darmowy, byłby budżetem z dziurą.
- Aktualizacja cen to podbicie zależności.

!!! warning "Provider bez klucza nie zapisuje żadnego wydatku"

    Wydatek przypisywany jest [sekretowi w vault](secrets.md), do którego run się
    rozwiązał, a provider bez klucza nie ma żadnego, któremu można by go
    przypisać.

Koszt sprawdzany jest *przed* każdym żądaniem do modelu i zapisywany nawet wtedy,
gdy run się nie powiedzie. Zobacz [Budżety](governance.md#budgets).

### Delegacja rozwiązuje własny profil { #a-delegation-resolves-its-own-profile }

Jeden run może angażować kilka modeli.

[Delegat](concepts.md#delegate-vs-inline-specialist) działa na profilu, który
nazywa jego *własny* spec, rozwiązanym wtedy, gdy runner przechodzi drzewo
delegacji. Wbudowany specjalista, który nie nazywa żadnego, działa na profilu
agenta, który go wywołał — i najmniej zaskakująca odpowiedź, i jedyna działająca,
gdy profil rodzica jest jedynym, jaki autor wybrał.

Te żądania mierzone są wobec jednej księgi runa rodzica, ale **wyceniane są per
provider**: strażnik delegata dzieli księgę, limity i bazy miesiąca, a bierze
własnego providera.

Dzielenie profilu rodzica wprost wyceniałoby delegata na Anthropic wobec katalogu
OpenAI — po cichu i zwykle jako niewycenione, co zaniża raportowanie runa i
oznacza flagą doskonale wyceniany run jako sięgający podłogi.

Wiersz runa potomnego, który zapisuje delegacja, nazywa model, który na nią
odpowiedział, więc dashboard kosztów grupuje delegowaną turę pod modelem, który
faktycznie zadziałał, a nie pod modelem rodzica.

## Podsumowanie { #recap }

- **Profil** to nazwany model plus nazwany klucz, a agenci wskazują na profile, żeby
  zrotowanie jednego albo drugiego dotykało jednego wiersza.
- **27 providerów**, a jedyne, co ta platforma wie o każdym z nich, to kształt
  poświadczenia — konstruowanie to zadanie Pydantic AI.
- Id modelu jest **wolnym tekstem**, bo żadna lista nie jest autorytatywna.
- **Długość kontekstu** czytana jest raz i zapisywana, bo migawka cen myli się co do
  niej w kierunku, który psuje run.
- **Koszt** pochodzi z dołączonej migawki, nieznany model zapisywany jest jako
  niewyceniony, a nie darmowy, a provider bez klucza nie zapisuje wydatku w ogóle.

## Jak go skonfigurować { #setting-one-up }

[Przewodnik po pierwszym agencie](first-agent.md) robi to od początku do końca. W
skrócie: zapisz klucz providera w **Settings → Secrets**, dodaj profil modelu,
który go nazywa, a potem wskaż nim spec agenta.

```bash
make platform-bootstrap BOOTSTRAP_API_KEY=sk-...
```

robi wszystkie trzy rzeczy dla nowego deploymentu.
