---
title: Ewaluacja wyszukiwania
description: Zestaw pytań o znanych odpowiedziach do dokumentacji AgenticOS i harness mierzący na nim wyszukiwanie wiedzy według kategorii, top_k i rozszerzania zapytań.
source_sha: "9aba1b51e57e"
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
własnej kolekcji, nazwanej od modelu embeddingów. Kolejny przebieg ponownie
wykorzystuje kolekcję, dopóki zawiera ona każdą stronę, a w przeciwnym razie
buduje ją od nowa. Zwykłe pytanie przeszukuje je wszystkie naraz, tak jak agent
powiązany z kilkoma kolekcjami.

Każda konfiguracja to jedno przejście przez wszystkie 34 pytania. Wyszukiwanie
idzie własną ścieżką narzędzia wiedzy: zapytanie jest rozszerzane według
`query_analysis_mode`, każde zapytanie jest wyszukiwane, a wyniki są łączone i
przycinane do `top_k`. Dla każdej kategorii przebieg raportuje:

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
słów, więc traktuj je jako przybliżony sygnał. `--json` zapisuje pobrane strony i
odpowiedź dla każdego pytania, dla każdego, kto chce je przeczytać.

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
| `--top-k` | `5` | Powtarzalna. Chunki na wyszukiwanie, `default_top_k` capability wiedzy |
| `--mode` | `off` | Powtarzalna. `off`, `multi_query` lub `hyde`, `query_analysis_mode` tej capability |
| `--max-variants` | `3` | Przeredagowania, które może dodać `multi_query` |
| `--locale` | `en`, `pl` | Powtarzalna. Indeksowane języki; musi obejmować język każdego pytania `cross_language` |
| `--embedding-model` | `text-embedding-3-small` | Dowolny model z katalogu embeddingów albo inny z `--embedding-dim` |
| `--embedding-base-url` | `https://api.openai.com/v1` | Dowolny endpoint `/v1/embeddings` zgodny z OpenAI |
| `--embedding-api-key-env` | `OPENAI_API_KEY` | Zmienna, z której czytany jest klucz |
| `--keyless` | wył. | Endpoint nie przyjmuje klucza |
| `--llm-model` | brak | Nazwa modelu Pydantic AI. Jego provider czyta własną zmienną z kluczem |
| `--answers` | wył. | Dodatkowo odpowiada na każde pytanie na podstawie pobranych treści i sprawdza fakty |
| `--reingest` | wył. | Usuwa kolekcje i indeksuje korpus od nowa. Przebieg robi to sam, gdy zmieniła się liczba stron |
| `--json` | brak | Dodatkowo zapisuje wyniki dla poszczególnych pytań do tego pliku |

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

## Koszt { #cost }

Opublikowany korpus to około 0,6 miliona tokenów po angielsku i 1,0 miliona po
polsku, mierzone tokenizerem `cl100k_base`, którego używają modele embeddingów
OpenAI. Przy 200-znakowym nakładaniu się chunków indeksowanie obu języków to
około 1,7 miliona tokenów. Płaci się za nie raz i wykorzystuje ponownie aż do
`--reingest`.

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

## Czego nie rozstrzyga { #what-it-does-not-decide }

Zestaw mierzy; nie zmienia żadnych wartości domyślnych. Capability wiedzy
zachowuje `default_top_k` 5 i `query_analysis_mode` `off`, dopóki zmierzony
przebieg nie uzasadni zmiany. Zestaw nie testuje też uprawnień. Jego kolekcje nie
należą do żadnej organizacji i są przeszukiwane bez zawężenia zakresu, tak jak
robi to `rag-search`. Strony [przetwarzania plików](file-processing.md) i
[capability wiedzy](reference/capabilities.md#query-analysis-and-expansion)
opisują wyszukiwanie z zawężonym zakresem.
