---
source_sha: "b4f01f7af48e"
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

## Osobiste klucze do modeli { #personal-model-keys }

W Builderze, w sekcji **Dostęp do modelu**, pozostaw domyślne **Użyj klucza organizacji** lub wybierz **Każdy użytkownik podłącza własny klucz**. Tryb osobisty zachowuje model i endpoint administratora. Obsługuje modele czatu z kluczem API, bez modeli zapasowych i zmiany modelu dla pojedynczej rozmowy.

Zalogowany członek otwiera agenta w czacie i podłącza klucz przez prywatny formularz nad polem wiadomości lub w ustawieniach czatu. Klucz nigdy nie trafia do wiadomości, promptów ani instrukcji agenta. Połączenie jest wspólne dla agentów tej organizacji korzystających z tego samego dostawcy i endpointu. Brak klucza blokuje run przed zapytaniem do modelu; błąd uwierzytelnienia nigdy nie przełącza na klucz organizacji. Wymień klucz w ustawieniach czatu lub usuń połączenie w **Vault → Twoje połączenie z modelem**. Zapis klucza nie sprawdza go u dostawcy.

Formularz prywatnego klucza przesyła oczekiwany profil, dostawcę, endpoint i model pokazane użytkownikowi. Jeśli cel zmieni się przed zapisem, serwer odrzuca klucz jako konflikt; formularz odświeża cel i usuwa wpisany klucz przed kolejną próbą.

Tryb osobisty nie obsługuje obecnie kanałów prywatnych ani grupowych, widgetów, stron publicznych, uruchomień przez HTTP API, harmonogramów, triggerów, tematów w tle, głosu, recenzentów ani osobnych modeli funkcji. Przed publikacją wstrzymaj lub usuń aktywne kanały, publiczne udostępnienia i rutyny. Utworzenie lub ponowne włączenie niezgodnego udostępnienia zostaje odrzucone; run sprawdza tę samą zasadę. Strony publiczne i tokeny JWT widgetów nie identyfikują zalogowanego członka instancji.

Delegowanie działa w czacie zalogowanego użytkownika. Subagent w trybie osobistym musi używać dokładnie tego profilu modelu, który wybrano w głównym agencie działającym w trybie osobistym. Agent organizacyjny nie może korzystać z osobistych kluczy przez delegację, a osobisty subagent nie może wybrać innego modelu ani endpointu. Zasady obowiązują przy publikacji, udostępnianiu, promocji wersji i wykonaniu, także w zagnieżdżonych delegacjach i po wznowieniu.

Subagenci organizacyjni zachowują własne klucze. Specjaliści inline dziedziczą tryb rodzica, a dynamiczni w trybie osobistym pozostają przy jego modelu. Zasady osobistego dostępu MCP pozostają bez zmian.

Komunikat o brakującym połączeniu subagenta podaje nazwę agenta i połączenia z modelem. Otwórz ustawienia czatu tego agenta i podłącz klucz; jeśli agent nie jest widoczny, poproś właściciela o dostęp. Runner sprawdza drzewo delegacji przed zapytaniami do modeli i ponownie przy wznowieniu. Klucz innego endpointu, innej osoby ani osoby zatwierdzającej nie zastępuje brakującego połączenia użytkownika.

Klucze są szyfrowane w vaulcie dla właściciela i usuwane wraz z jego członkostwem lub kontem. Zmiana zatwierdzonego endpointu wymaga nowego połączenia. Rotacja klucza jednej osoby nie zmienia kluczy innych ani wspólnego profilu modelu.

Impersonacja innego członka nie daje dostępu do jego osobistych połączeń z modelami: próby odczytu, zmiany lub użycia klucza są odrzucane przed dostępem do vault.

Prywatna historia rozmowy jest przypisana do zatwierdzonych celów modeli, także fallbacków; [historia czatu](console.md#chat) opisuje zmianę połączenia i wznawianie oczekujących runów.

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

### Model, na którym startuje nowy agent { #the-model-a-new-agent-starts-on }

Nie ma domyślnego modelu dla całej organizacji. Spec agenta wskazuje jego model, a
publikacja odrzuca spec, który żadnego nie wskazuje.

Nowy agent, który nie wskazuje modelu, startuje na modelu organizacji, gdy
organizacja ma dokładnie jeden model, na którym agent może działać. To model czatowy
z kluczem albo model self-hosted zapisany do działania bez klucza, który publikacja
przyjmuje w obecnej postaci, razem z fallbackami. Dotyczy to każdego sposobu
tworzenia agenta: **Nowy agent** w konsoli, `POST /agents` bez `model_profile_id`,
szablonu, kopii szkicu bez modelu oraz wypromowanego specjalisty.

Architekt, asystent organizacji, sam wybiera swój model przy publikacji: pierwszy
model czatu, który publikacja przyjmuje, i nigdy model na [logowaniu do
ChatGPT](#running-on-a-chatgpt-subscription). Architekt służy całej organizacji, a
logowanie to subskrypcja jednej osoby: uruchomienia członków, którzy nie widzą go w
vault, są odrzucane, a uruchomienia tych, którzy je widzą, na przykład właścicieli i
administratorów organizacji, zużywają tę subskrypcję. Gdy jest tylko logowanie,
Architekt czeka na inny model.

Logowanie wybrane przez kogoś w szkicu Architekta, albo model z fallbackiem na
logowanie, zostaje w nim, ale jest publikowane dopiero wtedy, gdy opublikuje je w Builderze ktoś, kto może zmieniać
ustawienia organizacji. Architekt opublikowany już wcześniej na logowaniu zachowuje
ten model, dopóki ktoś, kto może zmieniać ustawienia organizacji, nie wybierze
innego w **Budowa > Model** (Build > Model) i go nie opublikuje.

Model jest zapisywany w szkicu, więc agent publikuje się bez otwierania sekcji
**Model**, a jego historia pokazuje, na jakim modelu został opublikowany. Spec,
który wskazuje model, zachowuje go. Szkic liczy się wtedy jako użycie modelu: modelu
nie da się usunąć, dopóki agent nie przejdzie na inny model albo nie zostanie
usunięty; archiwizacja nie wystarczy. Aby zmienić tylko klucz lub endpoint modelu,
edytuj go w miejscu ([Zmiana klucza lub endpointu
profilu](#changing-a-profiles-key-or-endpoint)).

Szkic zostaje bez modelu, gdy organizacja nie ma żadnego modelu albo ma więcej niż
jeden. Profile, na których agent nie może działać, nie są liczone: profil bez
klucza, model text-to-speech i pozostałe modele z sekcji [Profil, na którym agent
nie może działać](#a-profile-an-agent-cannot-run-on), ani profil, który publikacja by
odrzuciła, na przykład taki z fallbackiem na taki model. Model na [logowaniu
ChatGPT](#running-on-a-chatgpt-subscription) nigdy nie jest wybierany za kogoś, bo
to subskrypcja jednej osoby, ale jest liczony jako model.

Nie jest też wybierany model, którego fallbacki zawierają logowanie wśród
pierwszych trzech, czyli tych, których próbuje run: gdy model zawiedzie, run
każdego, kto widzi to logowanie, przeszedłby na tę subskrypcję. Architekt też
nie wybiera takiego modelu. Autor nadal może świadomie wybrać taki
model i go opublikować.

Publikacja odrzuca wtedy szkic komunikatem *No model selected - pick one under
Build > Model before publishing*. Odmowa oznacza też pole (`model_profile_id` w
`details.fields`), a konsola pokazuje obok niej **Przejdź do sekcji Model**, co
otwiera zakładkę **Budowa** na karcie **Model**.

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

Codzienny briefing, sugestie i utrzymanie pamięci udostępniają te parametry oraz
poziom rozumowania w selektorze modelu organizacji. Zmiany wymagają jawnego zapisu
do współdzielonego profilu i dotyczą wszystkich miejsc, które go używają.
Nieustawiona kontrolka nie wysyła nadpisania; dla nieobsługiwanych parametrów
pozostaw wartości dostawcy. Agenci mogą nadpisać poziom rozumowania przez
[capability `thinking`](reference/capabilities.md#thinking), korzystającą z ustawienia
Pydantic AI niezależnego od dostawcy. Role działające w tle nie mają speca agenta
i korzystają bezpośrednio z domyślnego `thinking` w profilu.

### Responses czy Chat Completions { #responses-or-chat-completions }

OpenAI publikuje dwa API dla tych samych modeli, a profil na `openai`, `azure`
lub `stav` zapisuje, do którego z nich idą jego żądania: `responses` albo `chat`. Każdy inny
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
| `stav` | z modelu: `chat`, gdzie jest obsługiwany, w przeciwnym razie `responses` |

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

### Gdzie działają żądania profilu Stav { #where-a-stav-profiles-requests-run }

Profil na `stav` zapisuje region: `eu`, `eea` albo `global`. Stav odpowiada tylko
z endpointów, które liczą w tym regionie, przełącza się awaryjnie tylko w jego
obrębie i odrzuca żądanie, którego nie może tam obsłużyć. `global` nie ustawia
własnego limitu. Region tylko zawęża to, na co pozwala polityka workspace'u w
Stav.

Ustawia się go w **Agents → add a model → Region**. Formularz startuje od `eu`, a
pominięty region zapisywany jest jako `eu`, więc profil opuszcza UE tylko wtedy,
gdy zapisano go z `eea` lub `global`.

Region jest wysyłany przy każdym żądaniu jako nagłówek `X-Stav-Runs-In`, a nie w
treści, więc `extra_body` w ustawieniach profilu nie może go zastąpić.

Własny katalog Stav używa klucza wybranego w formularzu. Użytkownik musi mieć do niego dostęp; aplikacja nie wybiera ukrytego klucza organizacji dla własnego adresu URL. Cache uwierzytelnionych katalogów jest rozdzielony według poświadczeń. `extra_headers` w ustawieniach żądania nie może nadpisać ograniczenia profilu do EU lub EEA.

### Bramka Otari { #otari-gateway }

Wybierz **Otari** przy dodawaniu modelu, zapisz klucz API Otari w vaulcie i wybierz go w profilu. **Endpoint** jest wymagany: dla hostowanego Otari wpisz `https://api.otari.ai/api/v1`. Dla konta Otari w regionie UE ustaw `https://eu.api.otari.ai/api/v1`; dla własnej bramki podaj jej adres API zakończony `/api/v1`, dostępny z API i workerów.

Po wybraniu endpointu i klucza kliknij **Pobierz modele**. Zmiana któregokolwiek z nich wymaga ponownego potwierdzenia; samo wpisywanie adresu nie wysyła klucza.

Podpowiedzi modeli pochodzą z uwierzytelnionego endpointu `/models` tej bramki i używają wybranego klucza. Własny endpoint wymaga `connections:manage` i dostępu do tego klucza. Cache katalogu jest rozdzielony według endpointu i poświadczeń; awaria własnego katalogu nie zastępuje go katalogiem hostowanym. Pole modelu przyjmuje też selektor, np. `anthropic:claude-sonnet-4-6`, lub alias/politykę routingu skonfigurowaną w Otari.

Integracja używa [`pydantic-ai-otari`](https://github.com/mozilla-ai/otari/tree/main/integrations/pydantic-ai-otari): `OtariProvider` przekazuje profil rodziny modelu do modelu Chat Completions z Pydantic AI, tak jak `OtariModel`. Żądania zawsze używają Chat Completions; formularz nie oferuje Responses ani kontroli regionu Stav. Klucz i endpoint pochodzą jawnie z profilu, bez pobierania zastępczych wartości ze zmiennych `OTARI_*` lub `OPENAI_API_KEY`. Budżety i routing bramki Otari są dodatkową warstwą; AgenticOS nadal stosuje własne budżety i zatwierdzenia.

Bezpośrednie selektory `provider:model` korzystają w budżetach AgenticOS z katalogowej ceny modelu dostawcy; aliasy routingu bez prefiksu i nieznane modele pozostają jawnie częściowo wycenione. Są to szacunki według cen dostawcy: opłaty bramki sprawdzaj w widoku użycia Otari.

## Providery { #providers }

Providery czatu obsługiwane przez Pydantic AI oraz Otari przez jego pakiet integracyjny, Stav z routingiem regionalnym i MiniMax przez zgodne API.

Standardowe providery korzystają z wnioskowania modeli i providerów w Pydantic AI. Platforma opisuje kształt poświadczeń i w razie potrzeby integruje pakiety providerów.

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
| TypeSafe (Jev) | `typesafe` | API key | ✓ |
| OpenRouter | `openrouter` | klucz API |  ✓ |
| Otari | `otari` | klucz API | ✓ |
| Alibaba Cloud | `alibaba` | klucz API | ✓ |
| Cerebras | `cerebras` | klucz API | |
| DeepSeek | `deepseek` | klucz API | |
| Fireworks AI | `fireworks` | klucz API | |
| GitHub Models | `github` | klucz API | |
| GitHub Copilot | `github_copilot` | token konta / osobiste logowanie | |
| Groq | `groq` | klucz API | |
| Heroku AI | `heroku` | klucz API | ✓ |
| LLMTR | `llmtr` | klucz API | |
| Mistral | `mistral` | klucz API | |
| MiniMax | `minimax` | klucz API | ✓ |
| Kimi Code (plan) | `kimi_code` | klucz API | ✓ |
| Alibaba Coding Plan | `alibaba_coding_plan` | klucz API | ✓ |
| OpenCode Go | `opencode_go` | klucz API | ✓ |
| Ollama Cloud | `ollama_cloud` | klucz API | ✓ |
| Nous Portal | `nous_portal` | klucz API | ✓ |
| Inception | `inception` | klucz API | ✓ |
| Cline | `cline` | klucz API | ✓ |
| Chutes | `chutes` | klucz API | ✓ |
| Synthetic | `synthetic` | klucz API | ✓ |
| CLIProxyAPI (subscription gateway) | `cliproxyapi` | klucz API | ✓ |
| Moonshot AI | `moonshotai` | klucz API | |
| Nebius AI Studio | `nebius` | klucz API | |
| OVHcloud AI Endpoints | `ovhcloud` | klucz API | |
| SambaNova | `sambanova` | klucz API | ✓ |
| Stav.ai | `stav` | klucz API | ✓ |
| Together AI | `together` | klucz API | |
| Vercel AI Gateway | `vercel` | klucz API | |
| Z.AI | `zai` | klucz API | ✓ |
| xAI (Grok) | `xai` | klucz API | ✓ (`api_host`) |
| Cohere | `cohere` | klucz API | |
| Hugging Face | `huggingface` | klucz API | ✓ |

LLMTR pokazuje tylko modele deklarujące `CHAT_COMPLETIONS`. Model bez zweryfikowanej ceny we wbudowanym zestawie może działać tylko bez aktywnego limitu wydatków w dolarach; zapisany koszt pozostaje niepełny. Przy aktywnym limicie kolejne wywołanie LLMTR jest też odrzucane, jeśli koszt wcześniejszego użycia jest nieznany.

Wybierz **MiniMax**, aby użyć jego API Chat Completions zgodnego z OpenAI. Zapisz klucz API M Plan jako klucz MiniMax w sejfie; zwykły klucz API korzysta z własnego rozliczenia. Pusty Endpoint oznacza `https://api.minimax.io/v1`; własny adres ustaw tylko dla regionu lub bramy właściwych dla klucza. Wpisz dokładny identyfikator modelu z konta, np. `MiniMax-M3.1-Flash`; integracja nie pobiera katalogu planu. Historia MiniMax ma osobną tożsamość dostawcy, więc nie wysyłamy tam zaszyfrowanego rozumowania OpenAI. Znane ceny tokenów służą do szacowania budżetu, a nie rachunku za subskrypcję.

Dla **Z.AI GLM Coding Plan** wybierz **Z.AI** i ustaw **Endpoint** na `https://api.z.ai/api/coding/paas/v4` (globalny) lub `https://open.bigmodel.cn/api/coding/paas/v4` (Chiny), używając klucza właściwego dla planu i regionu. Puste pole Endpoint zachowuje zwykłe API rozliczane według użycia; istniejące profile się nie zmieniają.

**Klucze planów subskrypcyjnych.** Czterech kolejnych dostawców rozlicza plan subskrypcyjny przez klucz planu do endpointu zgodnego z OpenAI. Zapisz klucz planu w skarbcu z odpowiadającym przeznaczeniem; lista modeli pochodzi z katalogu tego klucza, a puste pole Endpoint używa domyślnego adresu planu.

| Provider | Domyślny endpoint | Inny region lub uwaga |
|---|---|---|
| Kimi Code (plan) | `https://api.kimi.ai/coding/v1` | Chiny: `https://api.kimi.com/coding/v1` |
| Alibaba Coding Plan | `https://coding-intl.dashscope.aliyuncs.com/v1` | Chiny: `https://coding.dashscope.aliyuncs.com/v1` |
| OpenCode Go | `https://opencode.ai/inference/go/openai/v1` | Modele nieobsługiwane w tym protokole endpoint odrzuca |
| Ollama Cloud | `https://ollama.com/v1` | Modele chmurowe Twojego konta Ollama |

Klucz planu nie jest zamienny z kluczem zwykłego API rozliczanego według użycia. Niektórzy dostawcy ograniczają klucze planów do narzędzi programistycznych; użycie ich z platformy agentów to Twoja decyzja i może skutkować ograniczeniem lub zawieszeniem planu. Budżety AgenticOS traktują to zużycie jako niewycenione użycie subskrypcji.

**Kolejne konta zgodne z OpenAI.** Nous Portal, Inception, Cline, Chutes i Synthetic przyjmują klucz z konsoli danej usługi. Puste pole Endpoint używa domyślnego adresu poniżej, a lista modeli pochodzi z katalogu klucza. Subskrypcje Nous Portal, Chutes i Synthetic są traktowane jako niewyceniane; kredyty Cline i użycie Inception są wyceniane tylko tam, gdzie AgenticOS zna cenę modelu.

| Provider | Domyślny endpoint |
|---|---|
| Nous Portal | `https://inference-api.nousresearch.com/v1` |
| Inception | `https://api.inceptionlabs.ai/v1` |
| Cline | `https://api.cline.bot/api/v1` |
| Chutes | `https://llm.chutes.ai/v1` |
| Synthetic | `https://api.synthetic.new/openai/v1` |

**Własna brama CLIProxyAPI.** Konta, do których dostawcy nie wydają klucza planu (Antigravity, Grok Build, Devin, Muse Code, logowanie Kimi Code i inne), można używać przez bramę [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) uruchomioną przez Ciebie lub operatora poza stosem. [Konta subskrypcyjne](#subscription-accounts) to ten sam pomysł wbudowany w platformę, z kontami każdej osoby trzymanymi osobno. Zaloguj konta w bramie jej własnymi poleceniami logowania, dodaj klucz klienta w `access.api-keys`, a potem utwórz profil **CLIProxyAPI (subscription gateway)** z jej Endpointem (na przykład `http://cliproxyapi:8317/v1` dla kontenera bramy w sieci wdrożenia) i tym kluczem klienta. Każde konto trzymane przez bramę jest dostępne dla każdego, kto może użyć profilu, więc dla konta osobistego uruchom osobistą bramę. Dodaj host bramy do `OUTBOUND_PRIVATE_ALLOWLIST`; adresy pętli zwrotnej nigdy nie są osiągalne z serwera. Dostawcy mogą ograniczyć lub zawiesić konta używane w ten sposób; to ryzyko ponosi właściciel konta.

Scope obejmuje także identyfikator członkostwa: ponowne dołączenie tworzy nowy scope, więc stare zadanie sprzątania nie usunie nowo połączonych kont. Usunięcie danych logowania trafia do kolejki również przy wyłączonym gatewayu. Wyłączony lub niesprawny gateway pozostawia widoczne nieudane zadanie zamiast potwierdzenia usunięcia; po przywróceniu gatewaya ponów zadanie. Błąd odczytu statusu logowania pokazuje komunikat i przycisk ponowienia.

Przed wczytaniem modeli wybierz klucz z sejfu i potwierdź adres docelowy. Własny katalog korzysta tylko z tego klucza i endpointu; brak listy pozwala wpisać model ręcznie, bez zastępowania jej katalogiem zwykłego API. Szacunki budżetu AgenticOS nie określają pozostałego limitu subskrypcji.

### Konta subskrypcyjne { #subscription-accounts }

W edytorze agenta i selektorze modeli czatu zacznij od **Twoje subskrypcje**, wybierz rozpoznawalnego dostawcę, np. **Claude Code (Pro, Max)** lub **ChatGPT (Codex)**, i kliknij **Połącz**. Logowanie otwiera się w tym miejscu i wraca do selektora; lista modeli pochodzi z połączonych kont wybranego dostawcy, bez zgadywania na podstawie nazw modeli. Niedostępne konta oferują ponowne logowanie. Kontami możesz zarządzać i rozłączać je w **Ustawienia → Subskrypcje**. Klucze API organizacji mają osobną grupę; ręcznie konfigurowane gatewaye i endpointy znajdziesz w **Zaawansowane / własny endpoint**. Dotychczasowe profile `subscription_accounts` i `cliproxyapi` zachowują swoje identyfikatory API.

Katalog czatu pokazuje wszystkie pozycje obsługujące czat, zamiast bez informacji kończyć listę na 100 modelach. Selektor pokazuje liczbę opcji, źródło katalogu lub ograniczoną listę zastępczą i pozwala odświeżyć dane. OpenRouter pokazuje bieżący region katalogu; jego zmiana jest jawna, a nowy zapisany model zachowuje ten region. Zapisane modele zachowują własne ustawienia połączenia.

W onboardingu sekcja **Z których subskrypcji już korzystasz?** pozwala zaznaczyć posiadane subskrypcje i zalogować się przed pierwszym czatem. Jest opcjonalna i dostępna dla członków; konta pozostają prywatne i nie konfigurują wspólnego modelu startowego organizacji.

Przy kilku podłączonych kontach osobistych otwórz zakładkę **Konto** i wybierz konto, tak jak zapisany klucz API. Modele subskrypcyjne korzystają z tej samej przeszukiwalnej listy co dostawcy API; kliknięcie modelu od razu go wybiera. Zatwierdzenie modelu przypisuje go do tego konta przez niejawny identyfikator trasy; nie przełącza automatycznie na inne konto. Profil przypisany do konta wymaga, aby osoba uruchamiająca miała to konto podłączone. Selektor po ponownym otwarciu odtwarza konto i model, a identyfikatorów tras nie pokazuje w nazwach modeli.

**Ustawienia → Subskrypcje** pokazują każde podłączone konto osobno: okna limitów, pozostały procent, paski zużycia i terminy resetu. Zakładka **Konto** w selektorze modeli korzysta z tego samego widoku dla wszystkich kont wybranego dostawcy.

Claude, Codex, Antigravity i oba regiony Kimi Code odczytują metadane limitów bez wywołania modelu. Claude pokazuje okna pięciogodzinne, tygodniowe i rodzin modeli. Antigravity zachowuje osobne grupy modeli, a Kimi — limity tygodniowe i kroczące. Devin pokazuje zgłoszone dane dzienne i tygodniowe. Odczyt limitów Groka i Meta nie jest dostępny przez to połączenie gatewaya.

Dane odświeżają się co minutę w otwartym widoku, a dla Claude’a co pięć minut; można też odświeżyć je ręcznie. Starsze obserwacje są oznaczone jako nieaktualne. Błędy pozostają widoczne; brak danych nigdy nie oznacza pełnego limitu. Kimi Code (kimi.com) i Kimi Code (kimi.ai) to osobne logowania regionalne, a nie plany czatu konsumenckiego.

Wszystkie grupy połączeń są od razu widoczne. Podłączone subskrypcje pokazują plakietkę stanu i dane konta; dodanie kolejnego konta jest akcją drugorzędną. Ponowne otwarcie selektora odtwarza źródło subskrypcji i model z zapisanego profilu subskrypcji.

Modele subskrypcji korzystają z instrukcji i narzędzi AgenticOS w runtime Pydantic AI. Nie uruchamiają Claude Code ani innego harnessu programistycznego. W Capabilities grupa **Delegowanie do agentów** łączy subagentów, **Claude Code i Codex** oraz **Inne zainstalowane agenty**. Coding Agent pozostaje włączony w domyślnym szablonie AgenticOS. Kolejność grup to codzienna praca, wiedza, research, wyniki, delegowanie, automatyzacja i kanały, a zaawansowane ustawienia są zwinięte na końcu. W każdej grupie najpierw są włączone capability, potem zalecane.

Osoby logują się do własnych subskrypcji z konsoli, a modele dostawcy
**Subscription accounts** działają na nich. W **Ustawienia → Subskrypcje** każda osoba łączy konta Claude (Pro, Max), ChatGPT (Codex),
Google Antigravity, Grok, Kimi, Devin lub Meta AI. Logowanie pokazuje kod do
wpisania na stronie dostawcy albo prosi o adres, na którym przeglądarka
skończyła po zatwierdzeniu.

Profil tego dostawcy przyjmuje tylko identyfikator modelu, bez klucza i bez
endpointu. **Add model** pokazuje modele, które serwują Twoje własne konta. Gdy
osoba rozmawia z agentem na takim profilu, uruchomienie korzysta z kont tej
osoby i niczyich innych. Uruchomienie rozpoczęte kluczem API, przez gościa
opublikowanego agenta albo przez pracę w tle nie ma za sobą osoby, więc jest
odrzucane. Z tego samego powodu platforma nigdy nie wybiera takiego modelu dla
nowego agenta.

Usługa `subscription-gateway` jest częścią stosu i uruchamia
[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) (MIT) osobno dla
każdej osoby w każdej organizacji. Proces danej osoby startuje przy pierwszym
użyciu i zatrzymuje się po dziesięciu minutach bezczynności. Każdy proces
nasłuchuje na pętli zwrotnej z własnymi kluczami i katalogiem logowań, a API
wyznacza, do którego trafia żądanie, z organizacji i osoby; przeglądarka nigdy
go nie wskazuje. Gdy członek odchodzi, zadanie w tle usuwa jego logowania;
usunięcie organizacji usuwa logowania wszystkich członków. Zalogowanie się do
tego samego konta w dwóch organizacjach oznacza dwa logowania.

Dostawcy mogą ograniczać używanie subskrypcji poza własnymi aplikacjami i
zawiesić za to konto. Konsola mówi o tym ryzyku, a przyjmuje je właściciel
konta. Cursor i Qwen Code nie mają logowania obsługiwanego przez bramę, więc nie
są oferowane. Budżety AgenticOS zapisują te uruchomienia bez ceny, bo pozostały
limit subskrypcji nie jest mierzony w tokenach. Uruchamianie bramy opisuje
[konfiguracja](configuration.md#subscription-accounts).

### Samodzielnie hostowane { #self-hosted }

| Provider | id | Poświadczenie | Custom URL |
|---|---|---|---|
| System One API | `system-one` | API key, or none | ✓ |
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

### Własny endpoint { #your-own-endpoint }

| Provider | id | Poświadczenie | Custom URL |
|---|---|---|---|
| Custom (OpenAI-compatible) | `openai_compatible` | klucz API | ✓ |
| Custom (Anthropic-compatible) | `anthropic_compatible` | klucz API | ✓ |

Te dwa to *kształt* API, a nie dostawca. Wpisujesz adres serwera, który
prowadzisz, albo bramki, której ufasz, oraz klucz, który ją uwierzytelnia.
Wybierz ten, który pasuje do tego, co odpowiada Twój endpoint:

| Twój endpoint odpowiada | Wybierz | Adres do wpisania |
|---|---|---|
| `POST /chat/completions` — vLLM, LM Studio, proxy LiteLLM, większość bramek | `openai_compatible` | katalog `/v1`, na przykład `https://llm.example/v1` |
| `POST /v1/messages` — własny kształt API Anthropic | `anthropic_compatible` | katalog API, na przykład `https://llm.example` |

Oba potrzebują endpointu i klucza. Nie ma żadnego publicznego API, do którego
można by się wycofać, więc profil bez nich jest odrzucany, a nie kierowany
gdzieś indziej.

Klucz jest przechowywany w sejfie pod nazwą samego providera, więc w sejfie
widać, że uwierzytelnia *ten* endpoint, a nie publiczne API dostawcy. Dlatego
to osobne pozycje, a nie profil `openai` albo `anthropic` z adresem: klucz
zapisany pod nazwą dostawcy mówi o tym dostawcy.

!!! info "Adres Anthropic nie zawiera `/v1`"

    SDK Anthropic wysyła żądanie na `<endpoint>/v1/messages`, więc endpointem
    jest katalog API. Adres, który już kończy się na `/v1`, jest przycięty,
    więc oba zapisy działają — ale to katalog API jest tym, o co pyta
    platforma.

**Load models** czyta listę z tego samego endpointu, tym samym kluczem, więc
lista w polu oferuje to, co Twój serwer faktycznie udostępnia. Identyfikator
modelu pozostaje wolnym tekstem: serwer, który nie publikuje listy, nadal da
się użyć, wpisując identyfikator ręcznie.

### Kiedy poświadczeniem nie jest klucz API { #when-the-credential-is-not-an-api-key }

| Provider | id | Poświadczenie |
|---|---|---|
| Azure OpenAI | `azure` | klucz **+** endpoint **+** przypięta wersja API |
| AWS Bedrock | `bedrock` | access key id, klucz tajny, region, opcjonalny token sesji |
| Google Vertex AI | `google_cloud` | JSON konta serwisowego |
| ChatGPT (Codex subscription) | `openai_codex` | logowanie do ChatGPT, zapisywane przez zalogowanie się, a nie wpisywane |
| ChatGPT (oficjalne użycie planu) | `openai_chatgpt` | grant aplikacji z osobną zgodą na korzystanie z planu, utworzony przez logowanie |
| Konta subskrypcyjne | `subscription_accounts` | własne logowania każdej osoby do subskrypcji, przez dołączoną bramę; bez klucza |

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

Nikt nie może wpisać tego poświadczenia. Zamiast tego logujesz się do ChatGPT,
domyślnie krótkim kodem:

1. W **Vault → add a secret** (albo w **Agents → add a model**, z wybranym
   **ChatGPT (Codex subscription)**, albo w **Settings → Coding accounts**)
   wybierz **Sign in with a code**. Strona urządzeń ChatGPT otwiera się w nowej
   karcie, a formularz pokazuje kod.
2. Wpisz kod na tej stronie i zatwierdź logowanie. Formularz sam zauważy
   zatwierdzenie i dokończy; niczego nie trzeba wklejać.

Kod działa przez 15 minut, tylko dla osoby, która rozpoczęła logowanie. Jeśli
Twoje konto nie obsługuje kodów urządzeń, otwórz **Paste an address instead**:
wybierz **Sign in with ChatGPT**, zatwierdź logowanie i wklej do formularza adres,
na który ChatGPT przekieruje przeglądarkę (`http://localhost:1455/...`, który się
nie załaduje). Ten adres też działa raz, tylko dla osoby, która rozpoczęła
logowanie, i tylko przez 15 minut.

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
    - **Nie każdy może na nim publikować.** Publikacja, rollback do wersji lub
      promocja wersji agenta jest odrzucana dla kogoś, kto nie widzi logowania w
      vault, gdy działa na nim model, do którego docierają runy agenta: model
      agenta, recenzenta, wbudowanego specjalisty albo włączonej capability,
      model [przypiętego delegata](reference/capabilities.md#delegation) i tego,
      do czego ten delegat dociera dalej, lub jeden z pierwszych trzech
      fallbacków któregokolwiek z nich. Mogą to zrobić osoba, do której należy
      logowanie, właściciele (owner) i administratorzy (admin) organizacji oraz
      każdy, komu je udostępniono. Klucz API nie może, niezależnie od tego, co
      widzi jego wystawca, bo run pod kluczem nigdy nie wydaje logowania.
      Wersja opublikowana na nim wcześniej działa dalej.
    - **Nie jest oferowane specjaliście, którego wymyśla model.** Przy
      [`allow_dynamic`](reference/capabilities.md#delegation) model runu może
      wybrać model specjalisty spośród profili organizacji. Profil na logowaniu
      albo taki, którego pierwsze trzy fallbacki do niego docierają, jest na tej
      liście tylko wtedy, gdy spec agenta nazywa dokładnie ten profil jako jeden
      z modeli wymienionych wyżej.
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

Trzydziestu providerów publikuje endpoint listy i jest to jedyne źródło, które wie
o modelu wypuszczonym dziś rano:

`anthropic`, `openai`, `google`, `openrouter`, `groq`, `mistral`, `together`,
`cohere`, `deepseek`, `xai`, `sambanova`, `vercel`, `ovhcloud`, `huggingface`,
`cerebras`, `fireworks`, `nebius`, `moonshotai`, `zai`, `alibaba`,
`kimi_code`, `alibaba_coding_plan`, `opencode_go`, `ollama_cloud`, `cliproxyapi`, `nous_portal`,
`inception`, `cline`, `chutes`, `synthetic`.

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

Selektor subskrypcji pobiera po otwarciu listę dostarczaną z wdrożeniem. Nie pobiera katalogu dla danego konta na żywo. Wpisy GPT-6.2 sprawdzono w Codex app server. Rozmiar kontekstu pozostaje pusty do czasu uzupełnienia katalogu cen.

| Provider | Kuratorowane id |
|---|---|
| `anthropic` | `claude-opus-5`, `claude-sonnet-5`, `claude-fable-5`, `claude-haiku-4-5` |
| `openai` | `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.3-codex` |
| `openai_codex` | GPT-6.2 Sol i Astra, GPT-6.1 Sol i Terra, GPT-6 Sol, Astra i Luna oraz wcześniejsze identyfikatory Codex |
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

Aby użyć regionalnego API OpenRouter, pozostaw dostawcę **OpenRouter** i wpisz `https://eu.openrouter.ai/api/v1` w polu **Endpoint** formularza modelu. Profil zachowuje klucz OpenRouter z sejfu, natywną obsługę modeli i ustawienia pamięci podręcznej. Lista modeli pochodzi z tego endpointu i ma osobną pamięć podręczną; awaria regionalnej listy nie przełącza jej na globalny katalog. W bazach wiedzy ustaw **Endpoint** embeddingów osobno podczas tworzenia kolekcji lub edycji dostawcy embeddingów. Istniejące konfiguracje zachowują globalny endpoint. Routing EU wymaga odpowiedniego planu OpenRouter Business lub Enterprise; [routing regionalny](https://openrouter.ai/docs/guides/get-started/sovereign-ai) i ZDR są osobnymi politykami OpenRouter.

Endpoint regionalny obsługuje mniej modeli embeddingów niż globalny: `eu.openrouter.ai` obsługuje `mistralai/mistral-embed-2312`, `mistralai/codestral-embed-2505` i `google/gemini-embedding-2`, a żadnego z modeli OpenAI. Formularz tworzenia proponuje tylko modele, które endpoint wymienia, a kolekcja, której modelu endpoint nie obsługuje, jest odrzucana zarówno przy tworzeniu, jak i przy przenoszeniu na ten endpoint. Dwóch modeli Mistral nie ma w dołączonym snapshocie cen, więc ich koszt zapisuje się jako wyceniony częściowo.

Przed ustawieniem regionalnych endpointów zaktualizuj wszystkie procesy API i workerów. Starsze wersje ignorują nadpisanie endpointu OpenRouter.

Aby użyć innego endpointu z tym samym dostawcą i modelem, wybierz w Builderze **Dodaj osobny model**. Automatyczna nazwa zawiera endpoint, a istniejący profil pozostaje bez zmian. **Aktualizuj model** edytuje wspólny profil. Pobieranie niestandardowego katalogu ma limit 2 MiB, 2048 modeli i długości pól; proces przechowuje maksymalnie 16 katalogów. Skompresowana lub zbyt duża odpowiedź pozostawia możliwość wpisania identyfikatora modelu bez przechodzenia na globalną listę.

## Modele decyzyjne { #decision-models }

Profile decyzyjne używają natywnego API `decisions` zamiast generowania tekstu. Wybierz dostawcę, model i klucz z sejfu w formularzu modelu. OpenAI, Google i OpenRouter oferują API czatu i decyzji; TypeSafe i własny endpoint System One służą do decyzji. Profil decyzyjny nie może być modelem rozmowy agenta ani przełączać się awaryjnie na model czatowy.

Adaptery pochodzą z Pydantic AI. Obecne sugestie obejmują OpenAI `gpt-6-luna`, Google `gemini-decision-1` oraz TypeSafe `jev-1.14.0` / `jev-latest`. OpenRouter pobiera katalog modeli decyzyjnych osobno od tekstowych. Własny System One wymaga adresu i identyfikatora modelu. Dostępność zależy od dostawcy i konta; sugestia nie gwarantuje dostępu.

Kroki **Decision models** w workflow wybierają profil natywny. Istniejące identyfikatory `decide.*` i konfiguracje z kluczem TypeSafe nadal działają. Odpowiedź poniżej progu pewności kieruje do portu `unsure`. Każde wykonanie ponownie sprawdza uprawnienia i klucz; koszt wchodzi do budżetu workflow i organizacji.

Automatyczne dołączanie do rozmów na kanałach może korzystać z modelu natywnego lub zwykłego LLM ze structured output. Natywna decyzja tak/nie zwraca prawdopodobieństwo dołączenia; ograniczone pole liczbowe zachowuje tę wartość. LLM zwraca ocenę przydatności 0–100, a nie skalibrowane prawdopodobieństwo. Obie wartości porównujemy z suwakiem progu, włącznie z samą granicą. Klasyfikator nie ma narzędzi. Funkcja wymaga włączenia i respektuje ustawione interwały; główny agent może używać organizacyjnych kont MCP, nigdy prywatnych danych uczestnika.

Źródła dostawców: [Pydantic AI](https://pydantic.dev/docs/ai/models/decision/), [OpenAI](https://developers.openai.com/api/docs/guides/decisions), [Google](https://ai.google.dev/gemini-api/docs/decisions-api), [TypeSafe](https://docs.typesafe.ai/models), [OpenRouter](https://github.com/OpenRouterTeam/skills/tree/main/skills/openrouter-decisions).

ElevenLabs Realtime udostępnia `eleven_realtime_v1_mini` oraz `eleven_realtime_v1_max` przez relay PCM 24 kHz, z domyślnym głosem `brian` i semantycznym wykrywaniem tur.

SDK nie raportuje opłat za tokeny. Połączenia z ustawionym budżetem wydatków są odrzucane przed nawiązaniem; połączenia bez takiego budżetu zachowują limit czasu i zapisują koszt audio jako dolną granicę, a nie pełny rachunek. Stawka katalogowa audio wynosi 0,08 USD/minutę (0,16 USD w trybie burst); tokeny kosztują dodatkowo. Wartość kontekstu 16k jest ostrożnym limitem historii przyjętym przez platformę, a nie oknem kontekstu ogłoszonym przez dostawcę. Integrację sprawdzono offline na konstrukcji modeli SDK i kontrolowanych transportach, bez testów na rzeczywistym koncie. [SDK](https://pydantic.dev/docs/ai/api/realtime/elevenlabs/), [ElevenLabs API pricing](https://elevenlabs.io/pricing/api).

## Konta GitHub Copilot { #github-copilot-accounts }

**GitHub Copilot** (`github_copilot`) używa dialektu modeli Copilot z Pydantic AI, odrębnego od GitHub Models (`github`). Wysyła jawnie wybrane poświadczenia vaultu do stałej bramy `https://api.githubcopilot.com`, z tożsamością integracji AgenticOS i bez nagłówków edytora VS Code. Ustawienia żądania nie mogą zastąpić konta ani tożsamości integracji. Własne bramy i bramy Enterprise nie są tu obsługiwane.

Administrator modeli może skonfigurować zatwierdzony profil z tokenem bearer Copilot w vaulcie. Ogólny token API GitHub nie potwierdza dostępu do Copilot. Wybierz osobiste poświadczenia modelu we współdzielonym agencie, aby każdy członek mógł połączyć własne konto w ustawieniach czatu. Administrator wdrożenia musi ustawić `GITHUB_COPILOT_OAUTH_CLIENT_ID` na identyfikator własnej aplikacji OAuth AgenticOS z włączonym device flow. Członek otwiera stronę GitHub, zatwierdza kod widoczny w AgenticOS i sprawdza autoryzację. Kod urządzenia i token nie trafiają do URL. Ponowne połączenie powtarza ten proces; odłączenie usuwa prywatny zapisany token, a zgodę OAuth cofa się osobno w GitHub.

Samo logowanie GitHub nie wystarcza: przed zapisem tokenu AgenticOS sprawdza, czy konto i aplikacja oferują wybrany model przez `/chat/completions`. Katalog zależy od konta, filtruje obsługiwane endpointy i nie korzysta ze wspólnego katalogu zastępczego. Interfejsy Responses, Messages, embeddings i realtime Copilot nie są oferowane. Osobiste połączenia zachowują ograniczenie do zalogowanych czatów WWW, bez przełączania na klucz organizacji lub innego dostawcę.

Device flow przyjmuje niewygasające zgody OAuth App. Wygasające zgody GitHub App lub zgody z refresh tokenem są jawnie odrzucane; ich odnawianie nie jest zaimplementowane i refresh tokeny nie są po cichu pomijane. Brak uprawnień, zasady konta, cofnięcie zgody i limity wymagają ponownego połączenia lub działania na koncie. Nazwa modelu nie ustala opłaty subskrypcji: użycie planu Copilot pozostaje bez wyceny do weryfikacji rozliczania w USD; wartości limitów nie są interpretowane jako dolary. Odbiór na prawdziwym koncie z własną aplikacją i tożsamością AgenticOS pozostaje otwarty. Zobacz [Pydantic AI Copilot](https://pydantic.dev/docs/ai/models/github-copilot/) i [konfigurację OAuth GitHub](https://docs.github.com/en/copilot/how-tos/copilot-sdk/setup/github-oauth).

## Oficjalne użycie planu ChatGPT { #official-chatgpt-plan-usage }

**ChatGPT plan usage (official)** używa grantu dla aplikacji i publicznego Responses API. **ChatGPT (Codex subscription)** pozostaje osobną integracją backendu Codex. Logowania, rodzaje sekretów i tokeny tych ścieżek nie są zamienne.

Funkcja jest domyślnie wyłączona. Operator musi sprawdzić warunki wdrożenia, ustawić `OPENAI_CHATGPT_PLAN_USAGE_ENABLED=true` i zachować jeden UUID w `OPENAI_CHATGPT_HOST_ID` między restartami i replikami. Płatna lub zdalnie hostowana aplikacja wymaga zgody OpenAI. Ustawienia potwierdzają decyzję operatora, ale nie uzyskują zgody. Przy ponownym łączeniu przywróć oryginalny UUID instalacji.

Wybierz oficjalnego dostawcę w skarbcu lub wyborze modelu, zaloguj się i wklej końcowy adres `http://127.0.0.1:1455/auth/callback?...`. Grant jest prywatny. Może go używać tylko właściciel; współdzielone profile, klucze API i zadania w tle nie pożyczają go innej osobie. Odmowa udostępnienia planu zachowuje rejestrację i grant, wyświetla ostrzeżenie i nie pozwala na inferencję. Połącz ponownie, by poprosić o zgodę. Rejestracja klienta przeżywa błąd wymiany tokenów. Callback jest jednorazowy i związany z osobą oraz organizacją; nowe logowanie unieważnia wcześniejsze.

Wybierz model z bieżącego katalogu wybranego konta. Lista nie jest zastępowana globalnym katalogiem kluczy API. Rotacja tokenów używa zapisu warunkowego w skarbcu. Każde wywołanie sprawdza cofnięcie grantu i aktualne członkostwo właściciela. Usuń grant ze skarbca, by rozłączyć lokalnie; dostęp w OpenAI cofniesz w ustawieniach ChatGPT. Metadane rejestracji pozostają na kolejne połączenie.

Pydantic AI wymusza strumieniowanie, `store=false`, lokalną historię i obsługiwany protokół preview. Odtwarzanie zawieszonej odpowiedzi, Batch API i nieobsługiwane narzędzia hostowane są niedostępne. Oficjalny plan nie bierze udziału w automatycznych fallbackach modeli. Koszt w AgenticOS pozostaje nieznany: cena API nie dowodzi opłaty planu. Uprawnienia konta, limity i rozliczenie wymagają testu na uprawnionym koncie. Zobacz [przepływ OpenAI](https://developers.openai.com/siwc/token-sharing-open-source) i [adapter Pydantic AI](https://pydantic.dev/docs/ai/models/openai-chatgpt/).
