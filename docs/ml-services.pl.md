---
source_sha: "351a53639a63"
---

# Usługi ML { #the-ml-services }

Cztery usługi tej platformy można wywołać samodzielnie, bez rozpoczynania
rozmowy i bez uruchamiania agenta: analizę dokumentu, OCR, zamianę mowy na tekst
i wykrywanie danych osobowych. To te same implementacje, z których korzystają
agenty, tyle że sięga się do nich wprost — jeden zestaw parserów, jeden zestaw
detektorów, jeden klient transkrypcji.

Istnieją, bo może ich potrzebować inny komponent. Kolejka, która ma odczytać
zeskanowany wniosek, zadanie wsadowe redagujące eksport, usługa chcąca
transkrypcji — żadne z nich nie chce okna czatu i żadne nie powinno udawać, że
nim jest.

## Co jest dostarczone, a co nie { #what-is-delivered-and-what-is-not }

Każda rodzina usług to jeden wiersz. **served** znaczy, że endpoint tego
wdrożenia odpowiada na nią silnikiem wymienionym obok. **dependency** znaczy, że
rodzina jest wymagana i czegoś brakuje, a notatka mówi czego. **prepared** to
przygotowanie architektury: żaden silnik nie jest dostarczany, a szew, którym by
przyszedł, jest nazwany.

`GET /api/v1/ml/services` odpowiada tą samą tabelą, więc integracja może ją
odczytać, zamiast wierzyć stronie dokumentacji.

| Usługa | Wymagania | Endpoint | Stan | Silnik |
|---|---|---|---|---|
| `document_analysis` | FA-069, FA-070 | `POST /api/v1/ml/documents/analyze` | served | LiteParse albo PyMuPDF, lokalnie |
| `ocr` | FA-069, FA-071 | `POST /api/v1/ml/documents/ocr` | served | OCR LiteParse: wbudowany Tesseract albo zarejestrowany serwer OCR |
| `speech_to_text` | FA-069, FA-072 | `POST /api/v1/ml/audio/transcriptions` | served | Własny endpoint transkrypcji organizacji |
| `pii_detection` | FA-069, FA-073 | `POST /api/v1/ml/privacy/pii` | served | Detektory wzorców, których używają guardrails |
| `pii_named_entities` | FA-073, DA-007 | — | dependency | Brak na tym wdrożeniu |
| `image_analysis` | FA-074 | — | prepared | Brak na tym wdrożeniu |

Dwa wiersze mówią „nie" i oba mówią dlaczego. **Nazwane encje** — imię i
nazwisko, adres pocztowy — nie mają kształtu wzorca, więc żadne wyrażenie
regularne ich nie znajdzie: potrzeba modelu rozpoznawania encji dla
każdego języka w zakresie. Endpoint wykrywania poniesie dodatkowe kategorie w
dniu, w którym taki model się pojawi, a do tego czasu ich nie deklaruje.
**Analiza obrazu** jest oznaczona jako zakres przyszły w samych wymaganiach.

## Jak wywołać { #calling-one }

Uwierzytelnianie, nagłówek organizacji i koperta błędu należą do
[API HTTP](api.md). Nie ma osobnego klucza, osobnego hosta ani drugiego wejścia,
i jest to świadome: powierzchnia z własnymi drzwiami frontowymi to powierzchnia
z własnymi pomyłkami.

Wszystkie cztery bramkuje jedno uprawnienie: **`ml:invoke`**. Świadomie nie jest
to `agents:run` — integracja, która parsuje dokumenty, nie powinna przez to móc
wydawać budżetu modelowego organizacji. Trzyma je każda rola poza Viewer.

```bash
curl -X POST "$BASE/api/v1/ml/documents/ocr" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -F "file=@scan.pdf" \
  -F "language=deu"
```

Odpowiedź niesie strony w kolejności, przygotowane chunki oraz rozmiar i skrót
pliku:

```json
{
  "filename": "scan.pdf",
  "filetype": "pdf",
  "byte_size": 184320,
  "content_hash": "9f2c…",
  "pages": [{"page_num": 1, "content": "Antrag auf …"}],
  "chunks": ["Antrag auf …"]
}
```

### Analiza dokumentu { #document-analysis }

`POST /api/v1/ml/documents/analyze` czyta to, co dokument już niesie. Pole
`parser` wybiera między `liteparse`, który zachowuje układ i czyta formaty
biurowe tam, gdzie zainstalowano LibreOffice, a `pymupdf`, który czyta PDF-y i
jest szybszy. `chunk_size`, `chunk_overlap` i `chunking_strategy` kształtują
przygotowane chunki; strategie to `recursive`, `fixed` i `markdown`, a czwarta
pisownia zostaje odrzucona, zamiast po cichu potraktowana jak `recursive`.

`chunk_overlap` musi być **mniejszy** niż `chunk_size`. Równy jest odrzucany i nie
chodzi o porządek: splitter to przyjmuje, a potem przesuwa się o mniej więcej
jeden separator na chunk, zachowując prawie kompletną kopię poprzedniego - więc
legalne wysłanie odpowiada dokumentem zwielokrotnionym wiele razy.

Dokument, z którego nic nie da się odczytać, zostaje odrzucony, a nie zwrócony z
pustą listą stron, a odmowa mówi, żeby wywołać OCR — czego skan parsowany dla
warstwy tekstowej potrzebuje zawsze.

### OCR { #ocr }

`POST /api/v1/ml/documents/ocr` rozpoznaje tekst na każdej stronie, niezależnie
od tego, czy strona niesie warstwę tekstową. Tym różni się od ingestii, która
wykrywa to automatycznie i pomija rozpoznawanie tam, gdzie tekst już jest: kto
poprosił o OCR, poprosił o odczytanie stron jako obrazów.

`language` to kod Tesseracta, czyli trzy litery — `pol`, nie `pl`. Dostarczany
obraz instaluje **`eng` i `pol`** i tylko te dwa endpoint przyjmuje: kod bez
pakietu językowego za sobą wywraca się wewnątrz parsowania, więc odmowa przychodzi
już na granicy. Wdrożenie, które doinstaluje więcej pakietów, poszerza tę listę w
tej samej zmianie.

`ocr_service_id` nazywa serwer OCR zarejestrowany wśród
[usług lokalnych](configuration.md), więc wdrożenie z własnym sidecarem
rozpoznawania wysyła strony tam; pomiń je, a odczyta je silnik wbudowany w
parser. Tak czy inaczej strony zostają w sieci samego wdrożenia.

**`.docx` jest tu odrzucany**, choć parser go czyta. Ingestia kieruje dokumenty
biurowe do czytnika natywnego, zanim sięgnie po parser OCR, więc przyjęcie
takiego pliku wyciągnęłoby istniejące akapity, pominęło zeskanowane strony i nic
by o tej różnicy nie powiedziało. Przekonwertuj go na PDF.

Jedno wywołanie rozpoznaje najwyżej **200 stron** i ma **120 sekund** — oba węższe
niż w ingestii, bo tutaj ktoś czeka, a na ingestię nie czeka nikt.

### Zamiana mowy na tekst { #speech-to-text }

`POST /api/v1/ml/audio/transcriptions` transkrybuje nagranie na własnych
poświadczeniach organizacji. `provider` i `model` nazywają, czego użyć; pominięcie **obu** bierze
pierwszą oferowaną parę wdrożenia, a podanie dostawcy bez modelu bierze pierwszy
model tego dostawcy. Czego nie robi nigdy, to nie wraca do domyślnego dostawcy,
gdy dostawca został nazwany — tak właśnie nagranie przeznaczone dla własnego
silnika trafia do vendora.

Nagranie podlega też własnemu limitowi 25 MB klienta transkrypcji, nawet gdy
`ML_MAX_UPLOAD_SIZE_MB` jest wyższy, więc za duże nagranie zostaje odrzucone jako
za duże, a nie dociera do silnika i wraca jako 503 o poświadczeniach.

Silnikiem jest ten endpoint, który nazywa model profile organizacji dla danego
dostawcy. To jest odpowiedź dla wdrożenia, które nie może wysyłać dźwięku do
dostawcy: skieruj profil na własny serwer mówiący tym samym API, a endpoint tutaj
się nie zmieni. Organizacja bez użytecznych poświadczeń dostaje odmowę, która to
mówi — nic nie jest zakładane jako istniejące, czego operator nie skonfigurował.

Które poświadczenie, gdy organizacja ma kilka dla jednego dostawcy: **najpierw
profil z kluczem**, pierwszy w kolejności etykiet; potem profil bez klucza, tylko
jeśli nazywa własny endpoint; a gdy brak obu, **klucz API zapisany w vaulcie**
z tym dostawcą jako przeznaczeniem, pierwszy według nazwy, wysyłany pod adres z
katalogu. Żądanie bez klucza nie niesie nagłówka `Authorization` i nigdy nie
używa `OPENAI_API_KEY` wdrożenia. Pierwszeństwo klucza sprawia, że bot kanału
dalej transkrybuje w OpenAI, gdy ktoś doda profil `openai` bez klucza dla proxy
czatu, które nie obsługuje `/audio/transcriptions`.

Awaryjne sięgnięcie do vaultu czyta tylko klucze **widoczne dla całej
organizacji**: prywatny klucz członka w vaulcie nie jest brany do nagrania, bo
to, za co by płacił, należy do wszystkich — notatka głosowa na kanale,
dyktowanie w czyimś czacie. Organizacja, która trzyma klucz OpenAI w vaulcie i nie używa żadnego
modelu czatu OpenAI, transkrybuje więc na nim bez profilu modelu, którego nie
potrzebuje.

Profil modelu jest używany tak, jak go skonfigurowano, więc profil wskazujący
na klucz prywatny transkrybuje na nim, tak jak wydaje go run czatu na tym
profilu. Ta sama kolejność obsługuje ten endpoint, dyktowanie i notatki
głosowe z kanałów. Lista agentów używających klucza w vaulcie nie obejmuje tego
użycia, bo żaden agent nie wiąże tego klucza.

Odmowa mówi dlaczego w `details.reason`, tutaj i przy
[dyktowaniu](#dictation-in-chat) tak samo. Własny tekst błędu dostawcy trafia do
logu i nigdy nie jest zwracany, bo klient dostawcy wkłada do swojego komunikatu
URL żądania razem z kluczem.

| `reason` | Status | Co się stało |
|---|---|---|
| `not_configured` | 503 | Brak użytecznych poświadczeń dla dostawcy; przy dyktowaniu także brak skonfigurowanego dyktowania na serwerze |
| `empty` | 400 | Silnik nie usłyszał mowy albo nagranie nie ma bajtów |
| `unsupported_type` | 400 | Tylko dyktowanie: nagranie nie jest WAV z 16-bitowym PCM 16 kHz mono — ani, gdy wdrożenie przyjmuje skompresowany dźwięk, WebM, Ogg czy MP4 — albo, na hostowanej stronie lub w widgecie, nie da się odczytać długości skompresowanego nagrania. `details.accepted` wymienia przyjmowane typy |
| `too_large` | 400 | Ponad 25 MB albo ponad limit dyktowania organizacji w bajtach lub w zmierzonej długości; `details.limit_seconds` podaje limit |
| `provider_error` | 503 | Dostawca odrzucił żądanie albo nie zdołał go obsłużyć |
| `timeout` | 503 | Dostawca nie odpowiedział w ciągu 60 sekund |

#### Dyktowanie w czacie { #dictation-in-chat }

`POST /api/v1/agents/{agent_id}/dictation` to mikrofon w
[polu wiadomości `/chat`](console.md#dictation), gdy organizacja transkrybuje na
serwerze. Przyjmuje jedno nagranie jako `file` i odpowiada `{"text": "..."}`,
które pole wiadomości wstawia do edycji; nic nie zostaje wysłane, dopóki osoba
nie naciśnie Wyślij. Wywołujący nie nazywa dostawcy, modelu ani języka —
[rozwiązują się](#which-engine-a-recording-reaches) z agenta i organizacji — a
osoba może dyktować do każdego agenta, którego może
uruchomić, łącznie z osobą z rolą Viewer, która ma na nim grant `use`. Agent, którego
nie może uruchomić, odpowiada 404, jak wszędzie indziej.

Co odczytuje z organizacji, ustawione na
[karcie Głos (Voice)](console.md#the-voice-card) przez kogoś z `org:settings`:
`chat_dictation` (`off`, `browser` albo `server`; wszystko poza `server` zostaje
odrzucone jako `not_configured`), `speech_to_text_provider` i
`speech_to_text_model` (para z katalogu speech-to-text),
`speech_to_text_language` (kod ISO-639-1 albo null, by silnik sam go rozpoznał)
oraz `dictation_max_seconds` (od 10 do 600, domyślnie 300). Silnik i najdłuższe
dyktowanie zawsze należą do organizacji; agent może zmienić tylko dostawcę, model
i język.

`GET /api/v1/agents/{agent_id}/dictation`, z tym samym dostępem, mówi, czy
mikrofon zadziała, zanim ktokolwiek zacznie nagrywać: `engine`, `max_seconds`,
`provider`, `format`, `ready` i `server_available`. `server_available` wymaga
pary, która rozwiązuje się dla tego agenta, katalogu, który nadal ją oferuje,
oraz poświadczenia dla jej dostawcy w organizacji — sprawdzanego pod kątem
istnienia, nigdy nie otwieranego; `ready` to to samo plus silnik `server` i
agent, który nie jest zarchiwizowany.
Formularz embeda czyta `server_available`, bo
[hostowana strona i widget](channels.md#dictation-on-a-widget-or-a-hosted-page)
nie zależą od silnika `/chat`.

`provider` to ten, do którego trafiłoby nagranie, a `format` to, w czym dla
niego nagrywać: `wav`, chyba że wdrożenie
[przyjmuje skompresowany dźwięk](deployment.md#what-a-dictation-may-be-uploaded-as),
a katalog speech-to-text mówi, że dostawca przyjmuje to, co tworzy
`MediaRecorder` — wtedy `webm`. Rozstrzygane tutaj, więc żaden klient nie trzyma
własnej listy. Agent bez niczego opublikowanego odpowiada według ustawień
organizacji.

**Domyślnie dyktowanie to surowy PCM**: `audio/wav` (albo `audio/x-wav`,
`audio/wave`) z 16-bitowym całkowitoliczbowym PCM 16 kHz mono, który każda
przeglądarka nagrywa przez Web Audio. Plik jest czytany ściśle — jeden fragment
`fmt ` mówiący dokładnie to, jeden fragment `data` z pełnymi próbkami, rozmiary
zgodne z plikiem — a każdy inny WAV, także stereo, 48 kHz, 24-bitowy czy
zmiennoprzecinkowy, jest odrzucany jako `unsupported_type`. Dostawca dostaje
policzone próbki za nagłówkiem zbudowanym przez serwer, nigdy nagłówek
wywołującego ani inny fragment, który plik zawierał, jako `recording.wav`.

Gdy wdrożenie przyjmuje skompresowany dźwięk, przyjmowane są też `audio/webm`,
`audio/ogg` i `audio/mp4`, z dopuszczalnym sufiksem kodeka, a `audio/x-m4a`
i `audio/m4a` są czytane jako `audio/mp4`, a `audio/opus` i `audio/x-ogg` jako
`audio/ogg`. To właśnie tworzy `MediaRecorder` przeglądarek, a dostawca
otrzymuje je jako `recording.webm`, `recording.ogg` albo `recording.m4a`, według
tej samej tabeli, która nazywa notatkę głosową z kanału `voice.<ext>`.

Trasa czyta najwyżej 25 MB treści żądania; limit bajtów organizacji — tyle
bajtów, ile zajmuje PCM przez `dictation_max_seconds` plus trzy sekundy, 32 000
na sekundę, i 4 KB na kontener — jest stosowany do tego, co przeczytano. Treść,
którą limit żądań wdrożenia odrzuca, zanim trasa ruszy, dostaje 413 bez
`reason`, co pole wiadomości odczytuje jako `too_large`.

Potem **długość jest mierzona**, zanim dostawca zostanie wywołany, a nagranie
dłuższe niż `dictation_max_seconds` jest odrzucane jako `too_large`, z trzema
sekundami zapasu, bo pole wiadomości zatrzymuje nagranie przy takcie co sekundę.
Dla PCM długość to policzone próbki, dokładnie. Długość skompresowanego
nagrania jest odczytywana z jego własnego nagłówka — ostatniej strony Ogg,
znaczników czasu bloków WebM, nagłówków filmu albo fragmentów MP4 — który plik
zbudowany ręcznie może zaniżyć. Nagranie, którego długości nie da się odczytać,
jest tu przyjmowane w granicach limitu bajtów;
[hostowana strona i widget](channels.md#what-it-costs-and-what-bounds-it) je
odrzucają.

Każda osoba może dyktować `RATE_LIMIT_DICTATION_PER_MINUTE` razy na minutę,
domyślnie 10, na osobnym liczniku, więc dyktowanie nie zużywa limitu usług ML
integracji. Każde dyktowanie zostawia jeden [zapis wywołania](#what-is-recorded),
pod `speech_to_text`, liczony w sekundach dźwięku — dla PCM w policzonej
długości. Pole wiadomości wysyła długość, którą nagrało, jako pole formularza
`duration` obok `file`, używane tylko dla skompresowanego nagrania, którego
długości nie podaje nic innego.

**Dźwięk nigdy nie jest przechowywany**: zostaje odrzucony, gdy wywołanie się
kończy, a tekst istnieje tylko w odpowiedzi. Anulowanie w przeglądarce nie anuluje nagrania już
wysłanego — dostawca i tak je transkrybuje, obciąża za nie konto organizacji, a
wywołanie zostaje zapisane.

!!! note "W Mistralu przeglądarka zawsze nagrywa WAV, a transkrybowanych języków jest mniej"

    Mistral dokumentuje dla Voxtrala wejście WAV i MP3, a nie WebM ani Opus,
    które nagrywają Chrome i Firefox. Dlatego gdy dostawcą, do którego
    rozwiązuje się nagranie, jest Mistral, pole wiadomości w każdej przeglądarce nagrywa
    WAV 16 kHz, mono, 16 bitów, nawet gdy wdrożenie przyjmuje skompresowany
    dźwięk. Przesyłany PCM jest mniej więcej dwa razy większy niż WebM, który
    zastępuje — 32 000 bajtów na sekundę — a limit długości jest ten sam.

    Lista języków pochodzi z Whispera, którą akceptują OpenAI i Groq. Mistral
    podaje 13 języków dla Voxtrala, więc ustalony język, którego nie przyjmuje,
    wraca jako `provider_error`. W Mistralu zostaw język na automatycznym
    wykrywaniu i wypróbuj nagranie, zanim zaczniesz na nim polegać.

#### Do którego silnika trafia nagranie { #which-engine-a-recording-reaches }

Silnik zamiany mowy na tekst mogą wskazać trzy miejsca:
[karta Głos (Voice)](console.md#the-voice-card) organizacji, nadpisanie
[`speech_to_text`](reference/spec.md#speech-to-text) agenta, ustawiane na jego
własnej [karcie Głos (Voice)](console.md#an-agents-own-engine) i działające po
opublikowaniu, oraz [bot kanału](channels.md#what-every-channel-shares).
Rozwiązują się w dwóch połowach:

| Co | Pochodzi z pierwszego, które to ustawia |
|---|---|
| Dostawca i model, jako para | Bot, potem agent, potem organizacja |
| Język | Agent, potem organizacja, potem silnik sam go rozpoznaje |

Polski agent w organizacji skonfigurowanej dla angielskiego ustawia więc
`language: pl` i zachowuje dostawcę organizacji. Bot nie ma własnego języka;
język agenta albo organizacji dotyczy także jego własnej pary. Gdy nic się nie
rozwiązuje, nic nie jest transkrybowane: dyktowanie odpowiada `not_configured`,
a bot mówi, że nie potrafi słuchać.

Dyktowanie czyta domyślną opublikowaną wersję agenta, tę, którą uruchamia
`/chat`. Bot czyta agenta, którego obsługuje jego powiązanie — nigdy agenta,
o którym ktoś wspomni przez `@slug`, bo nagranie jest transkrybowane, zanim
wzmianki zostaną przekierowane — w wersji, którą przypina środowisko tego
powiązania, tej, której użyje run. Agent w wersji roboczej albo zarchiwizowany
nie ma wersji, którą ktokolwiek uruchamia, i odpowiada sama organizacja.

### Wykrywanie danych osobowych { #personal-data-detection }

`POST /api/v1/ml/privacy/pii` przyjmuje JSON, a nie plik:

```bash
curl -X POST "$BASE/api/v1/ml/privacy/pii" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"text": "write to ada@example.com", "categories": ["email"]}'
```

```json
{
  "counts": [{"category": "email", "count": 1}],
  "total": 1,
  "redacted_text": "write to [redacted:email]"
}
```

Raportowana jest każda zamówiona kategoria, także te, które nic nie dopasowały —
„szukano i nie ma" i „nie szukano" to różne odpowiedzi. Kategorie to `email`,
`iban`, `credit_card`, `us_ssn` i `phone`, a każda jest dopasowywana kształtem,
a potem sprawdzana: Luhn dla karty, ISO 7064 dla IBAN-u, plan numeracji kraju i
grupowanie cyfr dla numeru telefonu, więc ciąg cyfr nie zostaje zgłoszony jako
rachunek ani numer.

Numer telefonu zapisany z `+` jest znajdowany niezależnie od kraju; krajowy,
taki jak `415-555-0132`, jest czytany względem domyślnych krajów guardrails,
`US, GB, DE, PL`. Pole `phone_regions`, które zmienia tę listę, należy do
guardrails agenta, nie do tego endpointu.

Wraca liczność i tekst po redakcji, a nie offsety poszczególnych dopasowań.
Detektory odpowiadają przepisanym tekstem, a odzyskanie pozycji oznaczałoby
skopiowanie ich tablicy wzorców i sum kontrolnych — kopia, która po cichu
przestaje zgadzać się z oryginałem, jest gorsza niż węższy kontrakt.

## Co jest zapisywane { #what-is-recorded }

Każde wywołanie zostawia wiersz: która usługa, która organizacja, kto poprosił,
ile bajtów weszło, ile wyszło, jak długo trwało i jak się skończyło.
`GET /api/v1/ml/calls` odczytuje je z powrotem, od najnowszych, a
`GET /api/v1/ml/calls/{id}` odczytuje jedno.

Odrzucone wywołanie też jest zapisywane, a jego wiersz jest commitowany, zanim
odmowa rozwinie żądanie — wiersz tylko dodany do tej transakcji zostałby wycofany
przez samą odmowę, którą opisuje, a operator pytający, czemu integracja się psuje,
usłyszałby, że tenant nie wykonał żadnych wywołań.

**Żadna treść nie jest przechowywana.** Wynik wraca w odpowiedzi i nie jest
zapisywany, więc dokument tu sparsowany nie staje się dokumentem, który to
wdrożenie trzyma, a tekst wysłany do sprawdzenia pod kątem danych osobowych nie
zostaje w tabeli, o której nikt nie myślał jak o składnicy dokumentów. Wiersz
wywołania innej organizacji jest nie do znalezienia, tak samo jak każdy inny
wiersz na tym API.

Zużycie liczy się w jednostce, w której pracuje usługa — strony przy parsowaniu,
znaki przy skanowaniu, sekundy dźwięku przy transkrypcji — a nie w pieniądzu.
Dostarczone usługi działają albo na maszynach samego operatora, gdzie nie ma ceny
dostawcy, albo na własnym koncie dostawcy organizacji, które rozlicza ją wprost.
Liczba, której nikt nie pogodzi z fakturą, jest gorsza niż uczciwe zliczenie
jednostek. Transkrypcja nie wlicza się też do [budgetu](governance.md#budgets)
agenta.

### Transkrypcje { #transcriptions }

Do zamiany mowy na tekst prowadzą trzy drogi i każda zostawia ten sam wiersz: API
(`surface: api`), [dyktowanie](#dictation-in-chat) (`chat`) i
[wiadomości głosowe bota kanału](channels.md#what-every-channel-shares)
(`channel`). Wiersz dodaje `provider` i `model`, `agent_id`, dla którego było
nagranie - agenta, do którego dyktowano, albo agenta obsługiwanego przez bota -
`channel_bot_id` oraz `audio_ms`, długość nagrania. `requested_by` wiadomości
głosowej to osoba, z którą powiązany jest nadawca, dopóki jest członkiem
organizacji, albo nikt. Zapisywane jest
tylko nagranie przekazane providerowi; bot wyłączony albo bez silnika do
odziedziczenia nikogo nie pytał.

Długość to pierwsze znane z poniższych:

| Źródło | Kto ją podaje |
|---|---|
| Samo nagranie | Tylko dyktowanie: długość odczytana z kontenera, jak wyżej |
| Odpowiedź providera | OpenAI `whisper-1` (`usage.seconds`), Groq (`duration`, o które prosi `response_format=verbose_json`), Mistral (`usage.prompt_audio_seconds`) |
| Metadane platformy | Notatka głosowa albo plik audio z Telegrama, klip ze Slacka |
| Przeglądarka | Tylko dyktowanie: `duration` wysłane przez pole wiadomości, przycięte do najdłuższego dyktowania organizacji, bo to słowo klienta |

`gpt-4o-transcribe` i `gpt-4o-mini-transcribe` od OpenAI podają tokeny, nie
sekundy, a Mattermost nie podaje długości, więc wiadomość głosowa tam na tych
modelach jej nie ma. Udany wiersz liczy wtedy `0` sekund przy pustym `audio_ms` -
niezmierzone, a nie ciche.

`GET /api/v1/ml/calls` zawęża też po `agent_id`, `channel_bot_id`, `surface`,
`since` i `until`, a nie tylko po `ml_service`, zawsze w organizacji
wywołującego: id agenta innej organizacji nie pasuje do niczego. Agent, bot
i droga — jako filtry i jako kolumny — wymagają `runs:view`, jak podsumowanie
niżej. Z samym `ml:invoke` filtr po nich jest odrzucany z 403, a w każdym
wierszu wszystkie trzy wracają jako null.

`GET /api/v1/ml/calls/summary?days=30` sumuje udane transkrypcje w oknie
czasu: `seconds` — własne `units` każdego wiersza, czyli nagranie zaokrąglone
w górę do sekundy, zsumowane, więc podsumowanie zgadza się z listą — oraz
`count`, `count_unknown_length` dla nagrań, których sekundy nie obejmują, oraz to samo według agenta, bota kanału i drogi (`surface`).
Wymaga `runs:view`, jak [`GET /spend`](governance.md#what-the-cost-screen-shows),
a nie `ml:invoke`: podział wymienia agentów i boty, których Member może nie
widzieć. [Karta Głos (Voice)](console.md#the-voice-card) organizacji pokazuje to w
jednej linijce.

## Limity { #limits }

Pojedyncze wywołanie przyjmuje do `ML_MAX_UPLOAD_SIZE_MB` megabajtów, domyślnie
25, i tylko tyle bajtów jest odczytywanych z ciała żądania — za duże wysłanie
zostaje odrzucone, zanim w ogóle zostanie skopiowane do pamięci. Jedno skanowanie
czyta najwyżej 200000 znaków, a skanowanie obejmujące `phone` najwyżej 10 000
cyfr: dopasowanie numerów telefonu kosztuje dziesiątki mikrosekund na cyfrę,
więc dłuższy tekst zostaje odrzucony, a nie przeczytany. Wywołujący może wykonać `RATE_LIMIT_ML_PER_MINUTE`
wywołań na minutę, domyślnie 30, liczonych na wywołującego, a nie na adres.

Limit tempa liczy **starty** i nie widzi tego, co wciąż trwa, co jest złym
kształtem dla pracy mierzonej w minutach. Dlatego worker parsuje naraz najwyżej
`ML_MAX_CONCURRENT_PARSES` dokumentów, domyślnie 4, a wywołanie trafiające na
zajęte wszystkie sloty dostaje odmowę z `Retry-After`, a nie miejsce w kolejce:
kto usłyszy „wróć za chwilę", może wrócić, a kto stoi za czterema skanami, już się
poddał gdzieś, gdzie nikt tutaj tego nie widzi.

Wykonanie jest synchroniczne: odpowiedź jest wynikiem i nie ma kolejki do
odpytywania. To jest uczciwe wobec tego, co tu jest, zamiast aspiracyjne — tryb
kolejkowy dodałby własne stany do wiersza wywołania, i taki miałby kształt.

## Wdrażanie ich osobno { #deploying-them-separately }

Usługi skalują się inaczej niż konsola. Przebieg OCR to sekundy pracy procesora
na wątku; serwowanie dashboardu nie jest ani jednym, ani drugim. Dlatego
`deploy/profiles/ml-services/` uruchamia obraz API drugi raz jako replikę, która
odpowiada tylko na te ścieżki, z własnymi zasobami i własnym skalowaniem, a
ingress przed nią kieruje do niej `/api/v1/ml/`.

To ten sam obraz i ta sama baza, i właśnie to sprawia, że jedna implementacja
obsługuje zarówno agenty, jak i wywołujących wprost. Osobny jest proces, limity i
restart — czyli to, o co prosi „wdrażane, aktualizowane i skalowane niezależnie".

Nakładkę i jej oczekiwania opisuje `deploy/profiles/ml-services/README.md`.
