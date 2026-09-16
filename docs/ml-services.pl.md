---
source_sha: "b542fd3f7700"
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
nazwisko, adres pocztowy, numer telefonu — nie mają kształtu wzorca, więc żadne
wyrażenie regularne ich nie znajdzie: potrzeba modelu rozpoznawania encji dla
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
`iban`, `credit_card` i `us_ssn`, a każda jest dopasowywana kształtem, a potem
sprawdzana: Luhn dla karty, ISO 7064 dla IBAN-u, więc ciąg cyfr nie zostaje
zgłoszony jako rachunek.

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
znaki przy skanowaniu — a nie w pieniądzu. Dostarczone usługi działają albo na
maszynach samego operatora, gdzie nie ma ceny dostawcy, albo na własnym koncie
dostawcy organizacji, które rozlicza ją wprost. Liczba, której nikt nie pogodzi z
fakturą, jest gorsza niż uczciwe zliczenie jednostek.

## Limity { #limits }

Pojedyncze wywołanie przyjmuje do `ML_MAX_UPLOAD_SIZE_MB` megabajtów, domyślnie
25, i tylko tyle bajtów jest odczytywanych z ciała żądania — za duże wysłanie
zostaje odrzucone, zanim w ogóle zostanie skopiowane do pamięci. Jedno skanowanie
czyta najwyżej 200000 znaków. Wywołujący może wykonać `RATE_LIMIT_ML_PER_MINUTE`
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
