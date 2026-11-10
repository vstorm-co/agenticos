---
title: Ewaluacja wyszukiwania
description: Zestaw pytań o znanych odpowiedziach do dokumentacji AgenticOS i harness mierzący na nim wyszukiwanie wiedzy według kategorii, top_k i rozszerzania zapytań.
source_sha: "d37f8d29a8ce"
---

# Ewaluacja wyszukiwania { #retrieval-evaluation }

Agent wiedzy jest tak dobry, jak to, co jego wyszukiwanie podaje modelowi. Zmiana
chunkowania, `top_k` albo rozszerzania zapytania to przesuwa, a odpowiedź, która
dobrze się czyta, nic nie mówi o tym, czy pobrano właściwą stronę. Dlatego
istnieje zestaw pytań o znanych odpowiedziach do tej dokumentacji i harness,
który mierzy na nim wyszukiwanie — w `evals/retrieval/`. Ta strona mówi, co on
mierzy, jak go uruchomić i ile kosztuje przebieg.

Zaczęło się od jednego pytania ([#2482](https://github.com/vstorm-co/agenticos/issues/2482)).
Zapytany *„Does AgenticOS support SAML single sign-on?”* agent działający na
dokumentacji pobrał tylko stronę porównania z Dify i odpowiedział, że
dokumentacja tego nie mówi. [Logowanie przez katalog](directory.md) mówi wprost,
że SAML nie ma, i jak zamiast tego dotrzeć do AgenticOS przez Keycloak.

## Zestaw pytań { #the-question-set }

`evals/retrieval/docs_questions.yaml` zawiera 34 pytania w trzech kategoriach:

| Kategoria | Co sprawdza | Przykład |
|---|---|---|
| `factual` | Podane ustawienie, wartość domyślną lub nazwę | „If I never set a vault master key, what does the platform encrypt credentials with?” |
| `negative` | Pytanie „czy obsługujecie X”, na które dokumentacja odpowiada wprost „nie” | „Does AgenticOS support SAML single sign-on?” |
| `cross_language` | Pytanie po polsku, na które odpowiedź jest tylko na stronach angielskich, albo pytanie po angielsku z odpowiedzią tylko na stronach polskich | „Czy da się logować do AgenticOS przez SAML?” |

Każde pytanie wskazuje oczekiwane strony i, na potrzeby sprawdzenia odpowiedzi,
fakty, które zawiera poprawna odpowiedź. Wpis wygląda tak:

```yaml
- id: saml-single-sign-on
  category: negative
  language: en
  question: Does AgenticOS support SAML single sign-on?
  expected_pages: [directory.md]
  expected_facts:
    - ["no", "not", "nie"]
    - [Keycloak*]
  evidence: "directory.md: **No SAML.** A SAML-only identity provider can reach AgenticOS through Keycloak"
```

Strona jest nazwana bez języka: `directory.md` to także `directory.pl.md`, więc
chunk z dowolnego tłumaczenia liczy się jako jej znalezienie. Pytanie
`cross_language` dodaje `search_locales`, jedyny język, który jego wyszukiwanie
może czytać, i nigdy nie jest to język, w którym zadano pytanie. Plik jest
wersjonowany, a zmiana znaczenia pola podnosi `version`. Loader odrzuca oczekiwaną
stronę, która nie istnieje albo nie jest opublikowana, więc zmiana nazwy strony
wywala testy jednostkowe, zamiast stać się chybieniem w przebiegu, za który ktoś
zapłacił.

## Co mierzy przebieg { #what-a-run-measures }

Korpusem jest opublikowana strona: każda strona Markdown w `docs/` poza tym, co
`mkdocs.yml` pomija (`plans/`, `design/`, `audits/`, roadmapa), oraz poza tą
stroną, która cytuje pytania i ich odpowiedzi. Każdy język jest indeksowany do
własnej kolekcji, nazwanej od modelu embeddingów i skrótu ustawień embeddingów
i ingestii, więc przebieg, który zmienia rozmiar chunka lub model, indeksuje od
zera. Kolejny przebieg ponownie wykorzystuje kolekcję, dopóki zawiera ona każdą
stronę w jej obecnej postaci, i buduje ją od nowa, gdy jakąś stronę dodano,
usunięto, przemianowano lub zmieniono. Zwykłe pytanie przeszukuje je wszystkie
naraz, tak jak agent powiązany z kilkoma kolekcjami.

Każda konfiguracja to jedno przejście przez wszystkie 34 pytania. Wyszukiwanie
idzie własną ścieżką narzędzia wiedzy: zapytanie jest rozszerzane według
`query_analysis_mode`, każde zapytanie jest wyszukiwane, a wyniki są łączone i
przycinane do `top_k`. Rozszerzone zapytania pytania są generowane raz na tryb
i ponownie używane dla każdego `top_k`, więc dwie wartości `top_k` są porównywane
na tych samych przeformułowaniach. Dla każdej kategorii przebieg raportuje:

| Liczba | Znaczenie |
|---|---|
| hit@k | Odsetek pytań z co najmniej jednym chunkiem z oczekiwanej strony wśród `top_k` zwróconych |
| recall@k | Odsetek oczekiwanych stron danego pytania, do których dotarto, uśredniony |
| MRR | Średnia z 1/pozycja pierwszego chunka z oczekiwanej strony, 0, gdy żaden nie został zwrócony |
| Poprawne odpowiedzi | Z `--answers`: ile odpowiedzi zawiera każdy oczekiwany fakt |

Po każdej tabeli przebieg wypisuje pytania, które chybił, i strony, które dostał
zamiast nich — i tam jest użyteczna informacja.

Sprawdzenie odpowiedzi jest celowo proste. Fakt pasuje jako całe słowo, wielkość
liter nie ma znaczenia, a alternatywa kończąca się na `*` pasuje jako prefiks
(`Keycloak*` pasuje do „Keycloaka”). Znaczniki cytowań, takie jak `[5]`, są
pomijane, więc numer fragmentu nigdy nie liczy się jako liczba w odpowiedzi. Samo
„nie” nie wystarcza: każde pytanie negatywne wymaga też alternatywy, którą podaje
dokumentacja, więc „dokumentacja tego nie mówi” nigdy nie przechodzi. Sprawdzenie
nadal nie odróżni poprawnej odpowiedzi od pogubionej, która używa tych samych
słów, więc traktuj je jako przybliżony sygnał.

Symbol wieloznaczny wymaga niepustego rdzenia: samo `*` jest odrzucane przed
indeksowaniem, ponieważ pasowałoby do każdej odpowiedzi.

`--json` zapisuje pobrane strony i odpowiedź dla każdego pytania, dla każdego,
kto chce je przeczytać, oraz zapytania, których szukał dla niego tryb
`multi_query` lub `hyde`. Plik zapisuje też, co złożyło się na przebieg: kiedy się zaczął,
SHA-256 zestawu pytań, model embeddingów i jego wymiar, ustawienia chunków i
parsery oraz skrót, który niosą nazwy kolekcji.

## Uruchamianie { #running-it }

Przebieg potrzebuje zmigrowanej bazy z pgvector (`make dev` ją daje), endpointu
embeddingów, a dla `multi_query`, `hyde` i `--answers` — modelu. Używaj bazy
deweloperskiej, nie bazy wdrożenia. Harness usuwa i odbudowuje własne kolekcje i
odmawia startu, gdy baza wiedzy już używa jednej z ich nazw.

!!! warning "Każde wywołanie jest prawdziwym, płatnym wywołaniem"
    Harness tworzy embeddingi korpusu i każdego zapytania przez podany endpoint
    i wywołuje wskazany model. Nic nie jest cache'owane ani podrabiane. Przed
    pierwszym przebiegiem przeczytaj [Koszt](#cost).

```bash
export OPENAI_API_KEY=sk-...
make eval-retrieval EVAL_ARGS="--top-k 5 --top-k 10 --mode off --mode multi_query --mode hyde \
    --llm-model openai:gpt-4.1-mini --answers --json /tmp/retrieval.json"
```

Opcje:

| Opcja | Domyślnie | |
|---|---|---|
| `--collection-prefix` | `retrieval_eval` | Zacznij od małej litery; dalej małe litery, cyfry lub podkreślenia. Wygenerowane nazwy muszą mieścić się w limicie nazw kolekcji magazynu |
| `--top-k` | `5` | Powtarzalna, 1–50. Chunki na wyszukiwanie, `default_top_k` capability wiedzy |
| `--mode` | `off` | Powtarzalna. `off`, `multi_query` lub `hyde`, `query_analysis_mode` tej capability |
| `--chunk-size` | `2500` | Znaki na chunk, tak jak ustawiają je ustawienia ingestii kolekcji |
| `--chunk-overlap` | `200` | Znaki, które chunk powtarza z poprzedniego. Musi być mniejsze niż `--chunk-size` |
| `--chunking-strategy` | `recursive` | `recursive`, `markdown` lub `fixed` |
| `--max-variants` | `3` | Przeredagowania, które może dodać `multi_query`, 1–5 |
| `--locale` | `en`, `pl` | Powtarzalna. Indeksowane języki; musi obejmować język każdego pytania `cross_language` |
| `--embedding-model` | `text-embedding-3-small` | Dowolny model z katalogu embeddingów albo inny z `--embedding-dim` |
| `--embedding-dim` | z katalogu modeli | Wymagany dodatni wymiar dla modelu spoza katalogu |
| `--embedding-base-url` | `https://api.openai.com/v1` | Dowolny endpoint `/v1/embeddings` zgodny z OpenAI |
| `--embedding-api-key-env` | `OPENAI_API_KEY` | Zmienna, z której czytany jest klucz |
| `--keyless` | wył. | Endpoint nie przyjmuje klucza |
| `--llm-model` | brak | Nazwa modelu Pydantic AI. Jego provider czyta własną zmienną z kluczem. `openai:` używa Responses API OpenAI; inne endpointy opisano niżej |
| `--answers` | wył. | Dodatkowo odpowiada na każde pytanie na podstawie pobranych treści i sprawdza fakty |
| `--reingest` | wył. | Usuwa kolekcje i indeksuje korpus od nowa. Przebieg robi to sam, gdy zmieniła się jakaś strona lub ustawienie chunków; podaj ją po zmianie w kodzie parsera |
| `--json` | brak | Dodatkowo zapisuje wyniki dla poszczególnych pytań do tego pliku |

Opcje chunków są sprawdzane tak jak ustawienia ingestii bazy wiedzy, a każde inne
ustawienie ingestii ma domyślną wartość tego formularza. Korpus to Markdown,
który parsuje wbudowany czytnik niezależnie od ustawionego parsera PDF, więc nie
ma opcji parsera. Harness nie czyta tych ustawień ze zmiennych środowiskowych.

Zestaw pytań, który loader odrzuca, zatrzymuje przebieg, zanim cokolwiek
zostanie zindeksowane, jednym komunikatem, który podaje każde pytanie i jego
problem.

Raport trafia na standardowe wyjście, a postęp na standardowe wyjście błędów, więc
`> results.md` zachowuje sam raport. Harness zatrzymuje się przed pomiarem, jeśli
którejś strony nie da się zindeksować, a przerwany przebieg usuwa to, co
zindeksował, bo korpus z lukami mierzy luki.

### Bez płatnego klucza { #without-a-paid-key }

Do embeddingów wystarczy serwer zgodny z OpenAI na własnej maszynie. Z
[Ollama](https://ollama.com), po `ollama pull bge-m3`:

```bash
make eval-retrieval EVAL_ARGS="--embedding-base-url http://localhost:11434/v1 \
    --embedding-model bge-m3 --keyless"
```

`bge-m3` jest wielojęzyczny, co ma znaczenie dla pytań `cross_language`. Liczby
opisują ten model, a nie ten, którego używają kolekcje wdrożenia, więc porównuj
tylko przebiegi z tym samym modelem embeddingów.

Lokalny model dla `multi_query`, `hyde` i `--answers` potrzebuje prefiksu
`openai-chat:`, bo `openai:` wywołuje Responses API, którego większość serwerów
zgodnych z OpenAI nie ma. `OPENAI_BASE_URL` kieruje providera na serwer. Ustaw
ją tylko dla jednego polecenia, jak niżej: wyeksportowana wysłałaby każde
późniejsze wywołanie `openai:`, razem z jego kluczem, do lokalnego serwera. Bez
`OPENAI_API_KEY` provider wysyła zastępczy klucz. Po `ollama pull qwen3:8b`:

```bash
OPENAI_BASE_URL=http://localhost:11434/v1 make eval-retrieval EVAL_ARGS="\
    --embedding-base-url http://localhost:11434/v1 --embedding-model bge-m3 --keyless \
    --mode multi_query --llm-model openai-chat:qwen3:8b"
```

To samo dotyczy każdego endpointu, który oferuje tylko chat completions.

## Koszt { #cost }

Opublikowany korpus to około 0,6 miliona tokenów po angielsku i 1,0 miliona po
polsku, mierzone tokenizerem `cl100k_base`, którego używają modele embeddingów
OpenAI. Przy 200-znakowym nakładaniu się chunków indeksowanie obu języków to
około 1,7 miliona tokenów. Płaci się za nie raz, a za dany język ponownie, gdy
zmieni się jedna z jego stron, lub przy `--reingest`.

| Część | Tokeny na przebieg | Po cenie katalogowej |
|---|---|---|
| Indeksowanie, `text-embedding-3-small` | ~1,7M, raz | ~$0.03 |
| Indeksowanie, `text-embedding-3-large` | ~1,7M, raz | ~$0.22 |
| Embeddingi pytań | poniżej 10k na konfigurację | poniżej $0.01 |
| `multi_query` lub `hyde`, `gpt-4.1-mini` | ~34 wywołania, ~10k tokenów na konfigurację | poniżej $0.01 |
| `--answers` przy `top_k` 5, `gpt-4.1-mini` | ~34 wywołania, ~150k tokenów wejściowych i ~5k wyjściowych | ~$0.07 |
| `--answers` przy `top_k` 10, `gpt-4.1-mini` | ~300k tokenów wejściowych i ~5k wyjściowych | ~$0.13 |

Ceny to ceny katalogowe za milion tokenów w chwili pisania:
`text-embedding-3-small` $0.02, `text-embedding-3-large` $0.13, `gpt-4.1-mini`
$0.40 za wejście i $1.60 za wyjście. Sprawdź aktualne ceny swojego providera.
Przy tych cenach pełna macierz dwóch wartości `top_k`, trzech trybów i odpowiedzi
kosztuje poniżej dolara. Na końcu przebieg wypisuje wykonane wywołania modelu i
ich tokeny.

## Zmierzone porównanie { #measured-comparison }

10 listopada 2026 r. rzeczywisty przebieg użył istniejącego połączenia GPT-6 Luna
przez OpenRouter: `openai/gpt-6-luna` do rozwijania zapytań i odpowiedzi oraz
`openai/text-embedding-3-small` z 1536 wymiarami do embeddingów. Korpus w rewizji
`e8e782562` zawierał 128 stron angielskich (1452 chunki) i 128 polskich (1553
chunki). Chunkowanie: `recursive`, rozmiar 2500, nakładanie 200. Wszystkie 34
pytania uruchomiono w każdej konfiguracji; rozwinięte zapytania wykorzystano
ponownie dla obu głębokości wyszukiwania.

| `top_k` | Tryb | hit@k | recall@k | MRR | Kontrole faktów w odpowiedzi |
|---|---|---|---|---|---|
| 5 | `off` | 73.5% | 70.6% | 0.571 | 23/34 |
| 5 | `multi_query` | 76.5% | 73.5% | 0.581 | 25/34 |
| 5 | `hyde` | 88.2% | 83.8% | 0.698 | 25/34 |
| 10 | `off` | 85.3% | 83.8% | 0.588 | 28/34 |
| 10 | `multi_query` | 79.4% | 77.9% | 0.621 | 24/34 |
| 10 | `hyde` | 94.1% | 92.6% | 0.705 | 27/34 |

Oba pytania o SAML, po angielsku i polsku, znalazły stronę o logowaniu
katalogowym i uzyskały odpowiedź, że SAML nie jest obsługiwany bezpośrednio,
a pośrednikiem jest Keycloak, we wszystkich sześciu konfiguracjach. `10/hyde`
dotarł do oczekiwanej strony dla wszystkich dziesięciu pytań międzyjęzykowych.
`10/off` zaliczył najwięcej kontroli odpowiedzi, poprawiając pięć odpowiedzi
względem `5/off`, bez nowych niezaliczonych kontroli ani wywołania rozwijania.

Dla agenta dokumentacji na tym korpusie zacznij od `default_top_k: 10` i
`query_analysis_mode: off`. Wybierz `hyde` jawnie, gdy dotarcie do większej liczby
oczekiwanych stron, zwłaszcza między językami, jest ważniejsze niż dodatkowe
wywołanie modelu i wyszukiwania. Zachowaj wartości domyślne platformy:
`default_top_k: 5` i `query_analysis_mode: off`. Jeden mały korpus i jeden model
nie uzasadniają zwiększania kontekstu ani dodawania rozwijania dla każdego
wdrożenia.

[Pełny przebieg](https://github.com/vstorm-co/agenticos/blob/main/evals/retrieval/results/2026-11-10-openrouter-gpt6-luna.json)
zawiera wyniki kategorii, każdą znalezioną stronę, rozwinięte zapytanie i odpowiedź,
hashe korpusu, wersje pakietów i zużycie tokenów. Wykonał 272 żądania modelu,
zużywając 872 567 tokenów wejściowych i 41 553 wyjściowych, poza embeddingami.
To pomiary pojedynczego przebiegu, nie gwarancja jakości ani powtarzane porównanie
statystyczne. Sześć odpowiedzi `10/off` nadal pomijało wymagane fakty, w tym rolę
zatwierdzającą, domyślny rozmiar chunka i pośrednika stdio. Nadal obowiązują
opisane wyżej ograniczenia kontroli odpowiedzi.

Aby powtórzyć ustawienia modelu i wyszukiwania z własnym autoryzowanym kluczem:

```bash
OPENAI_BASE_URL=https://openrouter.ai/api/v1 make eval-retrieval EVAL_ARGS="\
    --embedding-base-url https://openrouter.ai/api/v1 \
    --embedding-model openai/text-embedding-3-small --embedding-dim 1536 \
    --llm-model openai-chat:openai/gpt-6-luna \
    --top-k 5 --top-k 10 --mode off --mode multi_query --mode hyde \
    --answers --json /tmp/retrieval.json"
```

## Czego nie rozstrzyga { #what-it-does-not-decide }

Narzędzie nigdy nie zmienia ustawień agenta. Powyższe zalecenie dotyczy zmierzonego
korpusu dokumentacji; oceń własny korpus przed zmianą agenta. Zestaw nie testuje
też uprawnień. Jego kolekcje nie
należą do żadnej organizacji i są przeszukiwane bez zawężenia zakresu, tak jak
robi to `rag-search`. Strony [przetwarzania plików](file-processing.md) i
[capability wiedzy](reference/capabilities.md#query-analysis-and-expansion)
opisują wyszukiwanie z zawężonym zakresem.
