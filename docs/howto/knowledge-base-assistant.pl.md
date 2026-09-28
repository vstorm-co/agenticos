---
source_sha: "daee0cd1b399"
title: "Odpowiadaj na pytania z biblioteki dokumentów, podając źródła"
description: "Umieść cztery krótkie, syntetyczne dokumenty polityk w jednej kolekcji i sprawdź, czy agent znajduje właściwy, łączy dwa z nich i przyznaje, czego żaden nie pokrywa."
---

# Odpowiadaj na pytania z biblioteki dokumentów, podając źródła { #answer-questions-across-a-document-library-with-citations }

Zbuduj agenta, który odpowiada na podstawie małej biblioteki polityk HR zamiast jednego pliku. Przykład ma cztery krótkie dokumenty w jednej kolekcji: na jedno pytanie odpowiada pojedynczy dokument, jedno wymaga połączenia dwóch z nich, a jednego nic nie pokrywa. Sprawdzenie odpowiedzi opartej na kilku dokumentach oznacza przeczytanie obu fragmentów źródłowych, nie tylko odpowiedzi. To instrukcja wykonania, z jednym zapisanym runem jako punktem odniesienia.

Dla jednego dokumentu bez kolekcji do zarządzania zacznij zamiast tego od [Twojego pierwszego agenta z dokumentem](first-document-agent.md). Ta strona to kolejny krok: kilka dokumentów i odpowiedź, która musi zacytować właściwy.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu.
- Dostawca embeddingów i klucz do niego w vault — zapisany run użył `text-embedding-3-small` z OpenRouter. [Skonfiguruj bazę wiedzy](set-up-knowledge-base.md) opisuje okno tworzenia w pełni.
- Brak sandboksa i żadnej innej capability.

## Przygotuj dane wejściowe { #prepare-the-input }

Cztery krótkie pliki Markdown, zapisane jako osobne załączniki do wgrania. Przykład jest wymyślony, a dwie polityki celowo dzielą tę samą liczbę, żeby jedno pytanie wymagało obu.

`expense-policy.md`:

```text
Employees may claim reimbursement for client meals up to 40 EUR per person.
Travel booked more than 14 days in advance must use economy class for flights
under 6 hours. Mileage for a personal car used on company business is
reimbursed at 0.35 EUR per kilometre. Receipts are required for any claim over
15 EUR. Claims must be submitted within 30 days of the expense.
```

`remote-work-policy.md`:

```text
Employees may work remotely up to 3 days per week without prior approval.
A fully remote arrangement needs sign-off from the department head and HR.
Remote employees must be reachable during core hours, 10:00 to 16:00 in their
local time zone. Equipment for a home office is reimbursed once per employee,
up to 400 EUR, on the same 15 EUR receipt threshold as the expense policy.
```

`onboarding-checklist.md`:

```text
A new employee's manager requests a laptop and accounts in the first week.
IT provisions access within 2 business days of the request. The employee
completes the compliance training module within 30 days of their start date.
The 400 EUR home-office equipment allowance from the remote work policy is
requested through the same IT ticket as the laptop.
```

`travel-booking-guide.md`:

```text
Book flights and hotels through the corporate travel portal. Economy class is
the default for flights under 6 hours, matching the expense policy's advance-
booking rule. Hotel stays are capped at 180 EUR per night in tier-1 cities and
120 EUR elsewhere. A trip that combines client meetings and a conference needs
the sponsoring manager's approval before booking.
```

Fakty referencyjne: posiłek z klientem jest ograniczony do 40 EUR (sama polityka wydatków). Dodatek na home office to 400 EUR i jest zamawiany przez to samo zgłoszenie IT co laptop — jedna liczba z polityki pracy zdalnej, jeden krok z listy kontrolnej onboardingu. Nic tu nie mówi o okresie wypowiedzenia.

## Zbuduj agenta { #build-the-agent }

1. W **Knowledge → New** nadaj nazwę kolekcji, rozwiń **Embeddings** i wybierz dostawcę oraz model obsługiwane przez Twój klucz — zapisany run użył OpenRouter i `text-embedding-3-small`. Ten wybór jest zamrożony, gdy tylko kolekcja powstanie.
2. Utwórz kolekcję, a potem wgraj cztery pliki. Poczekaj, aż każdy osiągnie status `done`, zanim przejdziesz dalej.
3. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
4. W **Toolbox** włącz **Knowledge search** i przypisz właśnie wypełnioną kolekcję. Zostaw `default_top_k` na wartości domyślnej — cztery krótkie dokumenty nie potrzebują więcej.
5. Wpisz poniższe instrukcje, a potem **Publish**.

```text
Answer questions from the bound HR policy collection.
Cite the document you used for each fact.
If the answer draws on more than one document, name each one.
If the collection does not cover the question, say so rather than guessing.
```

!!! info "Dwa ustawienia warte poznania, zanim to skalujesz"

    `self_query_enabled` (domyślnie wyłączone) każe modelowi wywnioskować filtry, takie jak źródło, typ dokumentu czy zakres dat, z pytania w rodzaju „policies updated last quarter” — przydatne, gdy dokumenty niosą takie metadane, i niepotrzebne dla czterech plików bez nich. `parent_context` (domyślnie wyłączone) zwraca tekst wokół trafionego fragmentu zamiast samego fragmentu, co pomaga, gdy odpowiedź leży na jego krawędzi. Oba są tylko odczytywane, nigdy zapisywane, z jawnych filtrów samego modelu, i żadne nie poszerza, do których kolekcji ani tenantów agent ma dostęp. Zobacz [dokumentację capability](../reference/capabilities.md#knowledge-search).

## Uruchom { #run-it }

Zadaj każde pytanie w nowej rozmowie, żeby wcześniejsza odpowiedź nie mogła przeciekać do kolejnej.

```text
How much can I claim for a client meal?
```

```text
I am fully remote. How much is the home-office equipment allowance, and how do I request it?
```

```text
What is the notice period if I want to resign?
```

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Odpowiedź o posiłku z klientem | 40 EUR, z cytatem do `expense-policy.md` |
| Odpowiedź o home office | 400 EUR, z cytatem do `remote-work-policy.md`, a krok zgłoszenia cytowany do `onboarding-checklist.md` |
| Pytanie o wypowiedzenie | Stwierdza, że kolekcja tego nie pokrywa, i nie zmyśla liczby |
| Pobrane fragmenty w Activity | Najlepsze trafienie runa o posiłku to `expense-policy.md`; trafienia runa o home office obejmują oba dokumenty źródłowe |
| Pytanie o rezerwacje podróży z zeszłego tygodnia | Odpowiedź z `travel-booking-guide.md`, nie zmieszana z pozostałymi trzema |

Przeczytaj pobrane fragmenty w Activity, nie tylko odpowiedź. Cytat wskazujący właściwy plik z błędną liczbą albo właściwą liczbę z niewłaściwego pliku — oba wyglądają poprawnie w czacie.

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter, `default_top_k` na 5. Pytanie o posiłek z klientem wywołało `search_documents` raz i odpowiedziało „up to €40 per person,” cytując `expense-policy.md`, za 0,0133 USD. Pytanie o home office pobrało trzy dokumenty i odpowiedziało „up to €400,” cytując `remote-work-policy.md` dla liczby i `onboarding-checklist.md` dla „the same IT ticket used to request your laptop,” za 0,0181 USD. Pytanie o wypowiedzenie pobrało trzy najmniej trafne dokumenty, nic w nich nie znalazło i odpowiedziało „does not appear to contain a document covering resignation notice periods,” za 0,0135 USD.

    Pierwsza próba z tym agentem nie miała żadnej kolekcji przypiętej do speca — błąd w konfiguracji testu, nie produktu — i model odpowiedział z własnej wiedzy z treningu zamiast przyznać, że nic nie ma przypiętego. `search_documents` nigdy nie zostało wywołane. Przypięcie kolekcji i ponowna publikacja to naprawiły; różnica między „narzędzie się nie wywołało” a „narzędzie się wywołało i nic nie znalazło” to pierwsza rzecz do sprawdzenia, gdy odpowiedź brzmi pewnie, ale źródła brakuje.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Agent odpowiada płynnie, bez żadnego cytatu.** Sprawdź w Activity, czy `search_documents` w ogóle zostało wywołane. Capability knowledge bez przypiętej kolekcji po cichu nic nie wnosi, zamiast być narzędziem, które zawsze zawodzi.
- **W odpowiedzi brakuje dokumentu, który powinien zostać użyty.** Sprawdź status dokumentu w kolekcji. Dokument w stanie `processing` albo z błędem jest niewidoczny dla wyszukiwania, choćby człowiek czytał go bez problemu.
- **Pytanie o wypowiedzenie dostaje pewną, ale błędną odpowiedź.** Ostatnia linia instrukcji — „say so rather than guessing” — to ona zamienia ciszę w odmowę. Testuj to celowo, tak jak robi to trzecie pytanie tutaj.
- **Dwa dokumenty, które powinny się połączyć, dają odpowiedź tylko z jednego.** Podnieś `default_top_k` albo sprawdź, czy sformułowanie pytania faworyzuje słownictwo jednego dokumentu nad drugim.
- **Zsynchronizowany folder powinien zasilać tę kolekcję zamiast ręcznego wgrywania.** Zobacz [skonfiguruj źródła synchronizacji](configure-sync-sources.md) — ta sama kolekcja może mieszać wgrania ręczne i zaplanowaną synchronizację.

## Zapisz próbę { #record-the-trial }

Zachowaj cztery pliki, pytania, wersję agenta, profile modelu i embeddingów oraz pobrane fragmenty z Activity dla każdego runa — nie tylko odpowiedzi. Człowiek nadal ocenia, czy cytat faktycznie potwierdza to, co powiedział agent, i czy „nie pokrywa tego” było trafną decyzją, a nie wygodnym skrótem.

## Kolejne kroki { #next-steps }

Gdy wyszukiwanie sprawdza się na kilku dokumentach, postaw agenta przed ludźmi: [Slack](slack-handbook-assistant.md) to ten sam wzorzec z kanałem z przodu. Dla korpusu zbyt dużego, żeby wgrać go ręcznie, zamiast tego [skonfiguruj źródła synchronizacji](configure-sync-sources.md).
