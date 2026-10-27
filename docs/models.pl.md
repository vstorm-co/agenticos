---
source_sha: "03612a4d4028"
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

### Profil, na którym agent nie może działać { #a-profile-an-agent-cannot-run-on }

Profil może wskazywać model, który nie prowadzi rozmowy: model zamiany tekstu na
mowę, taki jak `gpt-4o-mini-tts`, model rozmów głosowych realtime, model
transkrypcji, model obrazów, model wideo
albo model embeddingów. Agent na takim modelu zawodzi już przy pierwszej turze.
Zamiana tekstu na mowę, generowanie obrazów i transkrypcja nie korzystają z
profili: każda z tych funkcji wskazuje własnego providera i model.

Platforma zna te modele z własnych katalogów (list modeli rozmów realtime, zamiany tekstu na mowę,
transkrypcji, obrazów, wideo i embeddingów). `GET /providers/model-profiles`
oznacza każdy profil polami `chat_capable` i `output_modalities`, a
`GET /providers/{provider}/models` oznacza każdą sugestię polem `chat_capable`.
Te dwa pola czytają też listing providera, który podaje, co emituje każdy model
(robią to OpenRouter i router Hugging Face), jeśli proces API już go pobrał. Ten
listing zmienia tylko to, co oferuje picker. Nigdy nie odrzuca publikacji, bo inny
proces API mógł go nie pobrać. Konsola aktualizuje też zapisane profile po
późniejszym nadejściu listingu. Aliasy providerów, takie jak `openai_codex`
i `google_cloud`, korzystają z katalogów odpowiednich dostawców. Wtedy:

- Panel modelu w Builderze, pickery recenzenta i specjalisty, pola modelu
  kolejnych kroków i modelu kroków przeglądarki oraz picker modelu do opisywania
  obrazów w bazie wiedzy nie oferują takiego modelu. Jeśli agent już go wskazuje,
  Builder nadal go pokazuje, oznaczony jako model, który nie jest modelem czatu.
  Członkowi, który zarządza połączeniami, Builder wymienia też pozostałe takie
  modele, oznaczone i bez możliwości wyboru, żeby dało się je usunąć.
- Picker modelu w czacie i formularz dodawania modelu w Builderze nie podpowiadają
  takiego modelu i odrzucają wpisany ręcznie.
- Publikacja odrzuca taki model jako model agenta, recenzenta, specjalisty, model
  kroków przeglądarki albo model kolejnych kroków i podaje jego nazwę. Odrzuca też
  profil, którego fallbacki obejmują taki model. To samo sprawdzenie działa przy
  powrocie do wersji, przy sprawdzaniu szkicu, przy testowym uruchomieniu w
  Builderze i przy włączaniu capability z czatu. Zapisana wersja na takim modelu
  nadal się wczytuje, ale nie można jej przywrócić, dopóki jej profil wskazuje
  model, który nie jest modelem czatu, albo wymienia go jako fallback. Wskaż w tym
  profilu model czatu albo opublikuj nową wersję.
- Run pomija taki fallback w swoim łańcuchu, tak jak usunięty, jeśli dodano go do
  profilu po publikacji.
- Rozmowa, która wskazuje taki model zamiast modelu agenta, z czatu albo przez
  API, jest odrzucana, zanim run się zacznie.
- Model, którego katalogi nie klasyfikują, taki jak model w Ollamie albo model
  wydany dziś rano, jest dozwolony. Nieznany model nie jest odmową. Profil z
  własnym endpointem (`base_url`) nigdy nie jest klasyfikowany, niezależnie od id
  modelu: katalogi opisują własne API providera, a serwer zgodny z OpenAI może
  serwować model czatu pod dowolną nazwą.

Picker modelu proaktywności stosuje tę samą zasadę. Sprawdzenie stałych katalogów
działa też przy konfiguracji proaktywności i przy rozwiązywaniu profilu do zwykłego
żądania tekstowego, w tym przy konfiguracji opisu obrazów i w workerze. Stare
konfiguracje nadal się wczytują; przed użyciem trzeba zastąpić niezgodny model.
Wyłączenie funkcji pozostaje możliwe. Nazwy wdrożeń Azure nie są klasyfikowane
na podstawie identyfikatorów modeli bazowych z katalogu.

### Zmiana klucza lub endpointu profilu { #changing-a-profiles-key-or-endpoint }

Agenci wskazują profil po jego id. Aby przenieść model na inny klucz, inny
endpoint albo drugie API OpenAI, edytuj profil w miejscu:
`PATCH /providers/model-profiles/{id}` zmienia `secret_id`, `base_url`, `api`,
`params` lub `label` i zachowuje id. Każdy agent na tym profilu używa zmiany od
następnego runu. Nikt nie musi niczego ponownie publikować.

W panelu modelu w Builderze zmień klucz, endpoint lub API używanego modelu.
Przycisk zmienia się wtedy na **Zaktualizuj model**, a panel mówi, że każdy agent
na tym modelu przełączy się razem z nim. **Dodaj model** pozostaje przyciskiem dla
innego providera lub modelu oraz dla modelu, któremu nadajesz własną nazwę. Użyj
**Nazwij to inaczej**, aby dać tylko temu agentowi osobny model.

Edycja podlega tym samym regułom co tworzenie i wymaga tego samego uprawnienia
`connections:manage`. Nowy klucz musi być w vaulcie tej organizacji, musi być dla
ciebie widoczny i musi być zapisany dla providera profilu. Nowy endpoint sprawdza
zapisany klucz w ten sam sposób, bo to do endpointu klucz jest wysyłany.
Provider, który wymaga klucza, nie może go stracić. Provider bez klucza
(keyless) bez klucza zachowuje endpoint. Etykieta musi pozostać unikalna.

Jeśli zmienisz endpoint i nie wyślesz `api`, API, które było tylko domyślnym dla starego
endpointu, przechodzi na domyślne dla nowego, a API wybrane przez kogoś zostaje.
Log audytu zapisuje `model_profile.updated` z nazwami zmienionych pól, nie z ich
wartościami. Nie możesz zmienić providera ani id modelu. Inny model to inny
profil.

`connections:manage` jest więc uprawnieniem do przeniesienia każdego agenta na
danym modelu, także agentów, których nie możesz edytować: nowy endpoint dostaje
ich zapytania od następnego runu. Nadaj je osobom, które zarządzają modelami
organizacji.

### Profil bez klucza { #a-profile-without-a-key }

Jeśli usuniesz klucz z vaulta, jego profile zostają z `secret_id` ustawionym na
null, a `GET /providers/model-profiles` oznacza je jako `missing_key: true`.
Profil zapisany bez klucza celowo to co innego: model hostowany samodzielnie
albo gateway, który niczego nie uwierzytelnia, na providerze keyless z
endpointem, na przykład Ollama w twojej sieci albo serwer zgodny z OpenAI.
Zapisuje to jako `runs_without_key` i dalej działa. Profil przed gatewayem, który
miał klucz i go stracił, jest oznaczany `missing_key` jak każdy inny. Wtedy:

- Pickery modelu agenta i czatu go nie oferują. Jeśli agent już go wskazuje,
  Builder pokazuje go z oznaczeniem **brak klucza** i prosi o przypisanie klucza.
- Publikacja go odrzuca i podaje nazwę modelu. Odrzuca też profil, którego
  pierwsze trzy fallbacki obejmują profil bez klucza, bo run by go pominął. Run na nim kończy się błędem
  „no key configured”.
- Aby go naprawić, otwórz agenta na tym modelu, wybierz klucz w sekcji **Model** i
  naciśnij **Zaktualizuj model**. Każdy agent na tym modelu znów działa.

### Usuwanie profilu { #deleting-a-profile }

`DELETE /providers/model-profiles/{id}` odrzuca profil, którego używają agenci.
Odpowiedź to `409 IN_USE`, a `details.agents` wymienia każdego agenta, którego
widzisz, z id i nazwą. `details.hidden_agents` liczy agentów, których nie widzisz.
Profil jest w użyciu, gdy szkic agenta, jego serwowana wersja albo wersja
przypięta przez środowisko wskazuje ten profil gdziekolwiek: jako model agenta,
recenzenta lub specjalisty albo w capability, na przykład model follow-upów lub
model kroków przeglądarki.

Zarchiwizowani agenci się liczą, bo przywrócenie z
archiwum przywraca wersję, którą serwowali. Odmowa oznacza ich jako `archived`:
zarchiwizowany agent nie może publikować, więc usuń go albo przywróć i przenieś.
Stare wersje, których nic nie serwuje, się nie liczą. Pozostałych agentów
najpierw przenieś na inny model. Aby zmienić
tylko klucz, edytuj profil.

### Fallbacki { #fallbacks }

Runner używa tylko pierwszych trzech fallbacków; tylko te są sprawdzane przy publikacji.

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

**Cache'owanie promptu jest domyślnie włączone**, przez neutralne wobec dostawcy
ustawienie `cache` z Pydantic AI. Każde żądanie runu wysyła ponownie instrukcje,
schematy narzędzi i całą historię, więc stały prefiks i rozmowa są oznaczane jako
punkty cache, a każde żądanie czyta poprzednie z cache. Działa wszędzie, gdzie
dostawca przyjmuje jawne cache'owanie - Anthropic, modele Anthropic i Nova w
Bedrock, modele Anthropic i Gemini w OpenRouter, OpenAI od GPT-5.6 - i niczego
nie zmienia u dostawcy, który cache'uje sam, jak Google. Profil wyłącza je
ustawieniem `cache: false` albo cache'uje tylko instrukcje i narzędzia przez
`cache: {"messages": false}`. Flaga konkretnego dostawcy, którą profil już
ustawia, np. `anthropic_cache_messages`, nadal ma dla niego pierwszeństwo.

Nakładu rozumowania **nie** ma tutaj. Jest nim
[capability `thinking`](reference/capabilities.md#thinking), bo „myśl mocniej” to
decyzja o tym, do *czego* agent służy, a nie pokrętło na połączeniu — i dlatego,
że spec, który ustawia to jako ustawienie modelu, przestaje być przenośny przy
zmianie modelu.

### Responses czy Chat Completions { #responses-or-chat-completions }

OpenAI publikuje dwa API dla tych samych modeli, a profil na `openai` lub `azure`
zapisuje, do którego z nich idą jego żądania: `responses` albo `chat`. Każdy inny
provider obsługuje jedno API i nic tu nie zapisuje.

Żadne nie jest właściwe wszędzie. Najnowsze modele OpenAI są serwowane wyłącznie
przez Responses i na Chat Completions odpowiadają błędem 400, a większość serwerów
zgodnych z OpenAI - vLLM, LM Studio, proxy LiteLLM - implementuje tylko Chat
Completions. Dlatego wybór jest polem profilu, w **Agents → add a model → API**,
a formularz startuje od wartości domyślnej:

| Profil | Domyślnie |
|---|---|
| `openai` bez endpointu (własne API OpenAI) | `responses` |
| `openai` z endpointem | `chat` |
| `azure` | `chat`, bo Responses API wymaga nowej `api_version`, a sekret może przypinać starszą |

Wartość domyślna to tylko punkt startowy formularza. Regionalny endpoint OpenAI,
taki jak `https://eu.api.openai.com/v1`, jest endpointem obsługującym Responses,
więc wybierz je tam. Pominięty wybór zapisywany jest jako wartość domyślna, więc
późniejsza zmiana domyślnej nie przestawia istniejącego profilu.

**Profil na Responses nie zostawia rozmów u OpenAI.** Responses API zapisuje
każdą odpowiedź po stronie OpenAI, chyba że się mu tego zabroni, a Chat
Completions domyślnie nie zapisuje niczego, więc model na Responses wysyła
`store: false`. Rozumowanie przechodzi między turami jako zaszyfrowana treść, a nie
przez zapisany identyfikator odpowiedzi, więc nic nie potrzebuje zapisanej kopii.
Profil, który jej chce, ustawia w swoich ustawieniach `openai_store` na `true`.

## Providery { #providers }

Dwadzieścia osiem, czyli wszystko, co Pydantic AI dostarcza i na co profil
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
    `openai` z endpointem domyślnie z niego korzysta - zobacz
    [Responses czy Chat Completions](#responses-or-chat-completions).

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
| ChatGPT (Codex subscription) | `openai_codex` | logowanie do ChatGPT, zapisywane przez zalogowanie się, a nie wpisywane |

Pierwsze trzy są powodem, dla którego sekret w ogóle ma *rodzaj*. Formularz, który
zbierałby dla Azure jeden nieprzejrzysty token, zbierałby coś, co da się wypełnić
poprawnie, a i tak zawiedzie przy pierwszym runie. Zobacz
[rodzaje sekretów](secrets.md#kinds).

!!! note "Dwa id są przepisywane w drodze do SDK"

    Profil `openai` budowany jest jako `openai-chat` albo `openai-responses`, a
    profil `azure` jako `azure` albo `azure-responses`, zależnie od zapisanego API,
    zamiast przyjmować Responses API, które wnioskuje samo `openai`. Zobacz
    [Responses czy Chat Completions](#responses-or-chat-completions).

    `google_cloud` budowany jest jako `google-cloud`. Żadne z nich nie zmienia
    tego, co zapisujesz.

### Uruchamianie na subskrypcji ChatGPT { #running-on-a-chatgpt-subscription }

`openai_codex` uruchamia modele OpenAI na backendzie Codex w ramach subskrypcji
ChatGPT, a nie przez rozliczany za użycie klucz API. Jest przeznaczony do
**użytku osobistego**: logowanie to subskrypcja jednej osoby, a każdy run na
profilu, który go używa, wlicza się do limitów ChatGPT tej osoby.

Nikt nie może wpisać tego poświadczenia. Zamiast tego logujesz się do ChatGPT:

1. W **Vault → add a secret** (albo w **Agents → add a model**, z wybranym
   **ChatGPT (Codex subscription)**) wybierz **Sign in with ChatGPT**. Logowanie
   do ChatGPT otwiera się w nowej karcie.
2. Zatwierdź je. ChatGPT przekieruje wtedy przeglądarkę na
   `http://localhost:1455/...`, który się nie załaduje. Tak ma być: OpenAI
   przypina ten adres dla każdego klienta poza własnym.
3. Skopiuj cały adres z paska adresu i wklej go z powrotem do formularza.

Kod w tym adresie działa raz, tylko dla osoby, która rozpoczęła logowanie,
i tylko przez 15 minut.

Token dostępu wygasa i jest odświeżany w trakcie działania modeli. Każde
odświeżenie zużywa refresh token, więc nowa para jest od razu zapieczętowywana
z powrotem w tym samym sekrecie w vault. Dwa runy odświeżające w tej samej
chwili wciąż mogą się ścigać. Ten, który przegra, zostaje odrzucony, a
rozwiązaniem jest **Reconnect** na sekrecie, który loguje ponownie bez zmiany
jego id.

!!! warning "Czym logowanie do ChatGPT nie jest"

    - **To nie jest `auth.json` z Codex CLI.** Ten plik przechowuje własny grant
      CLI. Refresh tokeny są jednorazowe, więc to z nich, które odświeżyłoby się
      pierwsze, wylogowałoby drugie.
    - **To nie jest poświadczenie organizacji.** Sekret jest domyślnie tworzony jako
      prywatny, a model na nim działa tylko dla kogoś, kto może zobaczyć to
      logowanie w vault i sam pyta. Dla każdego innego - odwiedzającego publiczną
      stronę lub embed, wywołującego z kluczem API - i dla pracy w tle, jak
      opisywanie obrazów z dokumentu, model jest odrzucany, a fallback na nim
      pomijany.
    - **Pokazany wydatek to nie twój rachunek.** Run jest wyceniany według
      stawek API OpenAI dla tego samego modelu, bo to na tym może opierać się
      [budżet](governance.md#budgets). Samą subskrypcję OpenAI rozlicza według
      stałej stawki.
    - **Niektóre ustawienia są ignorowane.** Backend Codex pomija `max_tokens`,
      `temperature` i `top_p`.

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
się na tej stronie. Dodanie dwudziestego dziewiątego to jedna edycja plus to, o co
poprosi wtedy ten test.

Dwa przejścia warto znać, bo są to wyszukania, które mogą nie odpowiedzieć niczym:

- Migawka cen zapisuje czterech providerów inaczej — `xai` to `x-ai`, `bedrock`
  to `aws`, `google_cloud` to `google`, a `openai_codex` wyceniany jest jako
  `openai` — a `_PRICE_PROVIDER_ALIASES` je mostkuje.
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
| `openai_codex` | te same cztery co `openai` |
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
- `vendor/model` agregatora, którego migawka nie zna, jest wyceniany jak własny
  model dostawcy, a wersja z kropką jest sprawdzana także z myślnikami:
  `anthropic/claude-sonnet-5.5` z OpenRouter kosztuje tyle, co `claude-sonnet-5-5`
  z Anthropic.
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

## Modele realtime { #realtime-models }

[Rozmowa głosowa](voice.md) nie używa profilu modelu. Jej model wybiera się z
katalogu, który dostarcza to wdrożenie,
`backend/app/core/catalog/realtime_models.json`, czytanego przez
`backend/app/services/realtime_models.py` i serwowanego Builderowi pod
`GET /api/v1/providers/realtime-models`. Klucz wskazuje sekcja Głos agenta jako
sekret z vaultu, a nie profil. To ten sam kształt, którego używa mowa na tekst:
wybór z katalogu plus jawny klucz.

Każdy wpis nazywa providera, jego modele i dla każdego modelu:

| Pole | O czym decyduje |
|---|---|
| `transport` | `webrtc` (przeglądarka rozmawia z providerem; to wdrożenie trzyma połączenie sideband) albo `relay` (dźwięk przechodzi przez gniazdo tego wdrożenia) |
| `input_sample_rate`, `output_sample_rate` | Częstotliwości PCM, z którymi przeglądarka nagrywa i odtwarza dźwięk przez relay |
| `voices`, `default_voice` | Co oferuje sekcja Głos i co oznacza pusty wybór |
| `supports_thinking` | Czy capability thinking agenta przekłada się na własne ustawienie rozumowania modelu |
| `context_window` | Gdzie ponowne połączenie przechodzi z odtwarzania tur na podsumowanie starszych |
| `pricing` | `kind` (`tokens` albo `per_minute`), `worst_case_usd_per_minute` do sprawdzenia przed rozmową i `usd_per_minute` dla modelu rozliczanego za minutę |

Rodzina `gpt-realtime` od OpenAI działa przez WebRTC i jest jedynym providerem
przetestowanym na żywo. Azure OpenAI, Gemini Live i xAI działają przez relay i
**nie zostały zweryfikowane na żywo**. GPT-Live nie ma w katalogu: nie przyjmuje
historii po rozpoczęciu sesji, więc ponowne połączenie nie mogłoby kontynuować
rozmowy.

**Azure to wdrożenie plus model bazowy.** Nazwę wdrożenia wybiera jego
właściciel i nic ona nie mówi o tym, co wdrożenie uruchamia, więc sekcja Głos
przyjmuje nazwę wdrożenia jako wolny tekst, a model z katalogu, który ono
uruchamia, jako `base_model`. Model bazowy decyduje o głosach i cenie: tokeny
rozmowy przez Azure wyceniane są jak ten model w OpenAI. Endpoint i wersja API
pochodzą z sekretu `azure_openai`.

**Ceny.** Modele wyceniane za tokeny są wyceniane per odpowiedź z tej samej
dołączonej migawki co runy tekstowe. Model rozliczany za minutę (xAI) jest
obciążany za czas połączenia według `usd_per_minute` z katalogu. Model wyceniany
za tokeny, którego migawka nie potrafi wycenić, jest odrzucany przy starcie
rozmowy, zamiast działać z budżetem, którego nie da się egzekwować.

## Podsumowanie { #recap }

- **Profil** to nazwany model plus nazwany klucz, a agenci wskazują na profile, żeby
  zrotowanie jednego albo drugiego dotykało jednego wiersza.
- **28 providerów**, a jedyne, co ta platforma wie o każdym z nich, to kształt
  poświadczenia — konstruowanie to zadanie Pydantic AI.
- Id modelu jest **wolnym tekstem**, bo żadna lista nie jest autorytatywna.
- **Długość kontekstu** czytana jest raz i zapisywana, bo migawka cen myli się co do
  niej w kierunku, który psuje run.
- **Koszt** pochodzi z dołączonej migawki, nieznany model zapisywany jest jako
  niewyceniony, a nie darmowy, a provider bez klucza nie zapisuje wydatku w ogóle.
- **Modele realtime** do rozmów głosowych to wybór z katalogu plus nazwany klucz,
  bez profilu; tylko modele OpenAI są zweryfikowane na żywo.

## Jak go skonfigurować { #setting-one-up }

[Przewodnik po pierwszym agencie](first-agent.md) robi to od początku do końca. W
skrócie: zapisz klucz providera w **Settings → Secrets**, dodaj profil modelu,
który go nazywa, a potem wskaż nim spec agenta.

```bash
make platform-bootstrap BOOTSTRAP_API_KEY=sk-...
```

robi wszystkie trzy rzeczy dla nowego deploymentu.
