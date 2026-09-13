---
source_sha: bdfb0e0fa929
---

# Zbuduj bazę wiedzy { #set-up-a-knowledge-base }

Doprowadzenie agenta do tego, żeby odpowiadał z twoich własnych dokumentów, od
początku do końca. Około dwudziestu minut, bez terminala i jedna decyzja po
drodze, której nie da się cofnąć.

[Przetwarzanie plików](../file-processing.md) wyjaśnia pipeline; tutaj jest
przepis.

## 1. Utwórz kolekcję { #1-create-the-collection }

**Knowledge → New**. Nadaj jej nazwę, którą człowiek rozpozna — to ją ktoś
wybiera później z listy — oraz scope, który decyduje o tym, czy należy do ciebie,
czy do organizacji.

!!! danger "Model embeddingowy jest zamrażany przy tworzeniu"

    To jedyny wybór na tej stronie, którego nie da się potem zmienić. Kolumna
    wektorowa powstaje o szerokości tego modelu, a dwa modele o tej samej
    szerokości i tak zapisują w *różnych* przestrzeniach — wyszukiwanie dalej
    porównywałoby więc wektory, które nie znaczą tego samego.

    Zmiana zdania później oznacza utworzenie nowej kolekcji i zaingestowanie
    wszystkiego od nowa. Zostaw wartość domyślną wdrożenia, chyba że masz powód,
    a jeśli go masz, zobacz
    [Wybór modelu](../choosing-models.md#embeddings-are-a-separate-permanent-choice).

## 2. Zdecyduj, jak czytane są dokumenty { #2-decide-how-documents-are-read }

Każda kolekcja niesie własne ustawienia ingestii, a każdy upload może je nadpisać.
Wartości domyślne są rozsądne; te trzy warte są zastanowienia.

**Który parser czyta PDF-a.**

| | Czym jest | Wybierz go, gdy |
|---|---|---|
| `pymupdf` | Lokalny, szybki, darmowy — i jedyny, który wyciąga osadzone obrazy do opisania | Dokumenty oparte przede wszystkim na tekście. Zacznij tutaj |
| `liteparse` | Lokalny, świadomy układu strony, zachowuje tabele jako siatki ASCII, zamiast je spłaszczać | Dokumenty, których sens siedzi w tabelach |
| `llamaparse` | Usługa w chmurze, rozliczana za stronę, zwraca markdown | Zeskanowane albo trudne dokumenty, które tamte dwa kaleczą — i godzisz się na to, że strony opuszczą twoje wdrożenie |

**Czy stosować OCR.** Włączony dla skanów i zdjęć dokumentów, poza tym wyłączony.
Jest wolniejszy i na czystym tekście wymyśla znaki.

**Jak strony są cięte na chunki.** `recursive` dzieli po strukturze i jest
właściwą wartością domyślną; `markdown` podąża za nagłówkami, co jest lepsze, gdy
twoje dokumenty naprawdę je mają; `fixed` to tępe liczenie znaków, na wypadek gdy
tamte dwa produkują bzdury.

!!! tip "Zmieniaj jedną rzecz naraz"

    Te ustawienia na siebie oddziałują. Jeśli wyszukiwanie jest słabe, zmień
    parser *albo* chunkowanie, zaingestuj ponownie jeden dokument i zadaj to samo
    pytanie jeszcze raz.

## 3. Włóż dokumenty { #3-put-documents-in }

Dwa sposoby, i w jednej kolekcji możesz używać obu.

**Wgraj** pliki bezpośrednio — wybrany przez ciebie parser je czyta, dzieli na
chunki, embeduje, a dokument pokazuje się jako `processing`, dopóki to się nie
skończy.

**Zsynchronizuj źródło** — folder na Google Drive albo bucket S3, odczytywany
ponownie według harmonogramu, tak żeby kolekcja podążała za folderem, a nie za
jego kopią. Zobacz
[Konfigurowanie źródeł synchronizacji](configure-sync-sources.md).

!!! warning "Jeśli ingestia zawodzi na świeżej instalacji, sprawdź obraz bazy danych"

    Magazyn wydaje `CREATE EXTENSION IF NOT EXISTS vector` przy pierwszym zapisie
    do kolekcji, a zwykły Postgres odpowiada *extension "vector" is not available*
    — 500 jeszcze zanim jakikolwiek wiersz zostanie zacommitowany. Obrazem musi
    być `pgvector/pgvector:pg16`.

## 4. Daj ją agentowi { #4-give-it-to-an-agent }

W Builderze, na agencie:

1. Włącz capability **Knowledge search**.
2. Podepnij kolekcję — agent przeszukuje kolekcje, które nazwiesz, i nic poza
   nimi.
3. Ustaw `default_top_k`, czyli liczbę chunków, które zwraca wyszukiwanie.

**Zacznij od trzech.** Osiem chunków tam, gdzie wystarczyłyby trzy, to
najczęstsze ciche przepłacanie w tym produkcie: pobrany tekst jest czytany
w turze, w której przychodzi, i w każdej turze, w której jest niesiony dalej,
a zwykle jest największą rzeczą w promptcie.

Potem powiedz to w instrukcjach. Wyszukiwanie stawia tekst przed modelem;
instrukcje decydują, co model z nim robi:

```
Answer from the knowledge collection and cite the document you used.
If the collection does not cover it, say so rather than guessing.
```

To drugie zdanie jest tym, co zamienia pewny siebie wymysł w „nie mam tego" —
i warto przetestować je celowo, pytając o coś, o czym wiesz, że nie ma tego
w dokumentach.

## 5. Przetestuj { #5-test-it }

Opublikuj, otwórz zakładkę **Test** agenta i zadaj trzy pytania:

| Zapytaj | Co sprawdzasz |
|---|---|
| O coś, co wyraźnie jest w dokumentach | Że wyszukiwanie w ogóle działa i że odpowiedź niesie cytowanie |
| O coś, czego wyraźnie w nich *nie ma* | Że agent odmawia, zamiast wymyślać |
| O coś z pogranicza — szczegół w tabeli albo w skanie | Czy parser naprawdę przeczytał tę część |

Trzecie jest tym, które znajduje prawdziwe problemy, i dlatego do wyboru parsera
z kroku 2 warto wracać, zamiast mu ufać.

## Kiedy nie może znaleźć czegoś, co na pewno tam jest { #when-it-cannot-find-something-that-is-definitely-there }

Przejdź w dół tej listy; jest ona z grubsza uporządkowana według tego, jak często
każdy punkt bywa przyczyną.

1. **Czy dokument jest w stanie `processing` albo się nie powiódł?** Błąd
   nieudanego dokumentu jest przy samym dokumencie i mówi, na którym etapie się
   poddał.
2. **Czy kolekcja jest podpięta do *tego* agenta?** Podpięcie jest per agent,
   a opublikowana wersja niesie podpięcia, które miała w chwili publikacji.
3. **Czy parser przeczytał tę część?** Otwórz dokument i spójrz na wyciągnięty
   tekst. Tabela spłaszczona do prozy albo skan bez OCR są dla wyszukiwania
   niewidoczne, choćbyś widział je najwyraźniej.
4. **Czy `default_top_k` nie jest za małe?** Trzy jest właściwe dla skupionego
   korpusu i za małe dla szerokiego.
5. **Czy strona naprawdę jest pusta, czy żądanie się nie powiodło?** Jedno
   i drugie renderuje to samo „nie ma tu nic". Sprawdź zakładkę sieci, zanim
   cokolwiek stwierdzisz.

## Podsumowanie { #recap }

- **Model embeddingowy jest zamrażany przy tworzeniu.** To jedyny nieodwracalny
  wybór w tym miejscu.
- **Najpierw `pymupdf`**, `liteparse` do dokumentów naszpikowanych tabelami,
  `llamaparse`, gdy strony mogą opuścić wdrożenie, a tamte dwa sobie nie radzą.
- **Zacznij `default_top_k` od trzech** i podnoś je tylko wtedy, gdy odpowiedziom
  naprawdę brakuje kontekstu.
- Instrukcje muszą mówić **„say so rather than guessing"** — samo wyszukiwanie
  nie powstrzymuje wymyślania.
- Testuj czymś, czego w dokumentach **nie ma**, i czymś zakopanym w tabeli.

[Pipeline w szczegółach →](../file-processing.md) ·
[Synchronizowanie folderu →](configure-sync-sources.md)
