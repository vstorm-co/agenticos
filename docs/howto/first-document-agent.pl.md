---
source_sha: "90d62e9ab4aa"
title: "Zbuduj pierwszego agenta z dokumentem"
description: "Zbuduj asystenta odpowiadającego na pytania o zasady zgłaszania sprzętu. Syntetyczny przykład zawiera fakt do sprawdzenia i celową lukę. To instrukcja wykonania, nie raport z pomiaru wdrożenia."
---

# Zbuduj pierwszego agenta z dokumentem { #build-your-first-document-agent }

Zbuduj asystenta odpowiadającego na pytania o zasady zgłaszania sprzętu. Syntetyczny przykład zawiera fakt do sprawdzenia i celową lukę. To instrukcja wykonania, nie raport z pomiaru wdrożenia.

## Przygotuj źródło { #prepare-the-source }

Potrzebujesz [działającej instalacji](../install.md) i modelu. [Pierwszy agent](../first-agent.md) opisuje klucz dostawcy i konfigurację modelu. Koszt zależy od dostawcy i ustawień.

Zapisz jako `equipment-handbook.md`:

```text
Equipment requests go to the office manager.
Include the item, reason and delivery location.
```

To fikcyjne zasady. Nie określają limitu wydatków.

## Zbuduj i opublikuj { #build-and-publish }

1. W **Knowledge → Collections** otwórz formularz tworzenia i rozwiń **Embeddings**. Wybierz zgodnego dostawcę/model embeddingów oraz jego klucz z sejfu lub lokalny endpoint. Utwórz kolekcję i wgraj plik. Sam model czatu nie wystarczy. Poczekaj na przetworzenie i sprawdź status dokumentu.
2. Utwórz agenta w **Agents → New agent** i wybierz profil modelu.
3. W **Toolbox** włącz knowledge, przypisz tylko testową kolekcję i wpisz instrukcje poniżej.
4. Ustaw budget i limit kroków odpowiednie do próby, następnie **Publish** testowanej wersji.

```text
Answer equipment-policy questions from the bound handbook.
Cite the document you used.
If it does not contain the answer, say what is missing.
Do not invent policies or submit equipment requests.
```

## Sprawdź wynik { #check-the-result }

| Pytanie | Kryterium |
| --- | --- |
| Who handles an equipment request? | Office manager, zgodnie ze źródłem |
| Which details should I include? | Item, reason, delivery location |
| How much can I spend? | Informacja, że limitu nie ma w źródle |

Użyj nowej rozmowy testowej. Sprawdź odpowiedź i pobrany materiał w [Activity](../governance.md). Zachowaj także błędne i niepełne odpowiedzi. Przy pustym wyszukiwaniu sprawdź powiązanie kolekcji, uprawnienia i przetwarzanie, zanim zmienisz prompt.

Zmień właściciela w pliku testowym na facilities team. Na [liście dokumentów kolekcji](../file-processing.md) usuń poprzedni dokument testowy i poczekaj na zakończenie usuwania, zanim wgrasz poprawiony plik. Samo ponowne wgranie tej samej nazwy pliku nie zastępuje starych wektorów. Poczekaj na przetworzenie i powtórz w nowej rozmowie. Sprawdź, czy stare źródło nie jest nadal pobierane.

## Udostępnij kolejny krok { #share-the-next-step }

Po sprawdzeniu wyniku wybierz [Slack lub inny kanał](../channels.md). Hosted page jest publiczna dla posiadacza linku: używaj publicznych lub syntetycznych danych. Kanał nie określa uprawnień do dokumentów.

Przed pilotem przypisz [właściciela utrzymania](../rollout.md). W razie błędu podaj wersję, konfigurację i zanonimizowane kroki w [zgłoszeniu pomocy](../help.md).
