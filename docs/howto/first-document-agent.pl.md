---
source_sha: "37a9ef11651d"
title: "Zbuduj pierwszego agenta z dokumentem"
description: "Daj agentowi mały podręcznik, zadaj pytanie i sprawdź odpowiedź ze źródłem."
---

# Zbuduj pierwszego agenta z dokumentem { #build-your-first-document-agent }

Zbuduj asystenta, który odpowiada na pytania o zasady zgłaszania sprzętu na podstawie jednego dokumentu. Ten syntetyczny przykład daje Ci fakt do sprawdzenia i celową lukę informacyjną. To instrukcja wykonania, z jednym zapisanym runem jako punktem odniesienia.

## Przygotuj źródło { #prepare-the-source }

Użyj [działającej instalacji](../install.md) i skonfigurowanego modelu. Konfigurację poświadczenia dostawcy i modelu opisuje strona [Twój pierwszy agent](../first-agent.md). Koszt zależy od wybranego dostawcy i konfiguracji.

Zapisz ten tekst jako `equipment-handbook.md`:

```text
Equipment requests go to the office manager.
Include the item, reason and delivery location.
```

To wymyślone fakty dotyczące zasad. Nie podano żadnego limitu wydatków.

## Zbuduj i opublikuj { #build-and-publish }

1. W **Knowledge → Collections** otwórz okno tworzenia i rozwiń **Embeddings**. Wybierz zgodnego dostawcę/model embeddingów oraz jego poświadczenie z vault albo lokalny endpoint, a potem utwórz kolekcję i wgraj plik. Sam model czatu nie wystarczy. Poczekaj na przetworzenie i sprawdź status dokumentu.
2. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
3. W **Toolbox** włącz knowledge i przypisz tylko testową kolekcję. Wpisz poniższe instrukcje.
4. Ustaw budżet i limit kroków odpowiedni do próby, a potem **Publish** wersję, którą będziesz testować.

```text
Answer equipment-policy questions from the bound handbook.
Cite the document you used.
If it does not contain the answer, say what is missing.
Do not invent policies or submit equipment requests.
```

## Sprawdź wynik { #check-the-result }

| Pytanie | Kryterium |
| --- | --- |
| Who handles an equipment request? | Podaje office managera, potwierdzonego przez źródło |
| Which details should I include? | Item, reason i delivery location |
| How much can I spend? | Mówi, że w źródle nie ma takiego limitu |

Zadaj pytanie w nowej testowej rozmowie. Sprawdź odpowiedź i pobrany materiał w [Activity](../governance.md). Zachowaj też błędne i niepełne odpowiedzi, nie tylko udane. Jeśli wyszukiwanie nic nie zwraca, sprawdź powiązanie kolekcji, uprawnienia i przetwarzanie, zanim zmienisz prompt.

Zmień właściciela w pliku testowym na facilities team. Na [liście dokumentów kolekcji](../file-processing.md) usuń oryginalny dokument testowy i poczekaj na zakończenie usuwania, zanim wgrasz poprawiony plik. Samo ponowne wgranie tej samej nazwy pliku nie zastępuje starych wektorów. Poczekaj na przetworzenie i powtórz w nowej rozmowie. Sprawdź, czy nieaktualny materiał nie jest nadal pobierany.

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter, wyszukiwanie w wiedzy powiązane z jedną kolekcją. „Who handles an equipment request?” wywołało `search_documents` raz i odpowiedziało „equipment requests go to the office manager,” z trzema szczegółami, cytując `equipment-handbook.md`. „How much can I spend?” wywołało `search_documents` dwa razy i odpowiedziało, że podręcznik „does not contain any information about spending limits or purchase approval thresholds.” Koszt trzech pytań i jednej próby ponownej poniżej: 0,043 USD.

    „Which details should I include?” najpierw zwróciło pytanie doprecyzowujące („could you clarify what you're referring to?”) zamiast wyszukiwania — zadane samodzielnie w nowej rozmowie, to zdanie nie niesie tematu zgłoszenia sprzętu. Druga próba tego samego pytania wywołała `search_documents` i odpowiedziała poprawnie. Sformułuj je z nazwanym tematem, jeśli chcesz, żeby wyszukiwanie uruchomiło się za pierwszym razem.

    Po usunięciu oryginalnego dokumentu, potwierdzeniu, że lista jest pusta, i wgraniu poprawionego pliku, to samo pierwsze pytanie w nowej rozmowie odpowiedziało „equipment requests go to the facilities team” bez żadnej wzmianki o office managerze. Łączny koszt pięciu tur: 0,055 USD.

## Udostępnij kolejny krok { #share-the-next-step }

Po sprawdzeniu wyniku umieść agenta [w Slacku](slack-handbook-assistant.md) albo wybierz [inny punkt wejścia](../channels.md). Hostowana strona jest publiczna dla każdego z linkiem: używaj tam publicznych lub syntetycznych materiałów. Wybór kanału nie ustala reguł dostępu do dokumentów.

Przed pilotażem zespołu przypisz [właściciela utrzymania](../rollout.md). Jeśli krok zawiedzie, podaj wersję, konfigurację i zanonimizowane kroki odtworzenia w [zgłoszeniu pomocy](../help.md).
