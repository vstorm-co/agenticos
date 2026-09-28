---
source_sha: "95d57516d759"
title: "Sprawdź umowę według własnej listy kontrolnej"
description: "Przypisz agentowi skill do wstępnego przeglądu, załącz krótką syntetyczną umowę o świadczenie usług i sprawdź, czy znajduje oba podłożone problemy i brakującą klauzulę, nie udzielając porad prawnych."
---

# Sprawdź umowę według własnej listy kontrolnej { #review-a-contract-against-your-checklist }

Zbuduj agenta, który czyta załączoną umowę i tworzy uporządkowany wyciąg oraz listę odstępstw od listy kontrolnej, a nie opinię, czy ją podpisać. Przykładem jest krótka syntetyczna umowa o świadczenie usług z dwoma podłożonymi problemami i jedną klauzulą, której brakuje całkowicie. To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu.
- Capability **skills** z przypisanym skillem z listą kontrolną przeglądu. Ta strona instaluje z galerii `legal/document-review-first-pass`. Jak napisać własny, opisują [skille](../skills.md#getting-skills-into-an-organization). Galeria ma też `legal/contract-clause-library`, do sprawdzania zatwierdzonej klauzuli i stanowiska zapasowego, gdy już masz punkt odniesienia; ten przykład go nie potrzebuje. Gotowy szablon agenta `legal/contract-reviewer` łączy oba.
- Bez sandboksa. Załączony plik tekstowy jest czytany bezpośrednio z promptu; zobacz [przetwarzanie plików](../file-processing.md#chat-file-uploads).

## Przygotuj dane wejściowe { #prepare-the-input }

Krótka umowa o świadczenie usług, wymyślona na potrzeby tej strony, zapisana jako `services-agreement.txt` i załączona w czacie:

```text
MASTER SERVICES AGREEMENT

This Agreement is made between Acme Consulting Ltd ("Provider") and Nimbus
Retail Ltd ("Client"), effective 1 January 2027.

1. Term
The initial term is 12 months from the effective date.

2. Services
Provider will deliver monthly analytics reporting as described in Schedule A.

3. Fees and Payment
Client will pay Provider 5,000 EUR per month, payable within 30 days of
invoice.

4. Confidentiality
Each party will keep the other's confidential information confidential
during the term and for 3 years after termination.

5. Liability
Each party's liability under this Agreement is unlimited.

6. Termination
Either party may terminate this Agreement for uncured material breach on 30
days' written notice.

7. Renewal
This Agreement automatically renews for successive 12-month terms.

8. Assignment
Neither party may assign this Agreement without the other party's prior
written consent.
```

Dwa podłożone problemy: klauzula 5 niczego nie ogranicza (nieograniczona odpowiedzialność), a klauzula 7 odnawia umowę automatycznie bez okna wypowiedzenia, które by to zatrzymało. Jednej klauzuli brakuje całkowicie: nic w umowie nie wskazuje prawa właściwego ani jurysdykcji.

## Zbuduj agenta { #build-the-agent }

1. W **Skills → Skill gallery** zainstaluj z półki legal `Document review first pass`.
2. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
3. W **Toolbox** włącz **Skills** i przypisz właśnie zainstalowany skill.
4. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You produce a structured extract and a list of deviations from the bound
review checklist skill. You do not advise, do not conclude a clause is
acceptable, and do not redraft. Everything you produce is checked by the
person who reviews it before it is relied on.

Use the Document review first pass skill for what to extract and how to flag
deviations. Cite the clause number for every extracted term and every
deviation. Flag anything the checklist expects that the agreement does not
contain.
```

## Uruchom { #run-it }

Załącz `services-agreement.txt` do nowej rozmowy i wyślij:

```text
Review this services agreement against the checklist.
```

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Odpowiedzialność | Oznaczona jako odstępstwo: brak limitu, kl. 5 |
| Odnowienie | Oznaczone jako odstępstwo: brak okna wypowiedzenia, kl. 7 |
| Prawo właściwe i jurysdykcja | Oznaczone jako całkowicie brakujące, a nie wymyślone |
| Każdy wyciągnięty warunek i każde odstępstwo | Podaje numer klauzuli |
| Ton | Podaje fakty i odstępstwa; nie ocenia, czy umowa jest bezpieczna, ryzykowna albo gotowa do podpisu |
| Pytanie, czy podpisać | Odmawia porady i odsyła do prawnika prowadzącego sprawę, który przegląda wynik |

Sam przeczytaj odstępstwa obok klauzul źródłowych. Odstępstwo z błędnym numerem klauzuli albo lista brakujących klauzul, która wymyśla coś, co umowa jednak ma, w czacie wyglądają na staranną pracę.

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter. Wyciąg określił odpowiedzialność z kl. 5 jako „unlimited” z „no exclusion of indirect/consequential loss”, odnowienie z kl. 7 jako pozbawione „no opt-out/break notice mechanism” i wymienił „Governing law & jurisdiction” jako brakujące zarówno w odstępstwach, jak i w osobnej tabeli braków, obok odszkodowań i zmiany kontroli, czyli pozycji z listy kontrolnej, których ten krótki przykład nigdy nie zawierał. Zakończył stwierdzeniem, że wyciąg „requires verification by the fee earner responsible for this matter before being relied upon”. Koszt: 0,0249 USD.

    Pierwsza próba skończyła się błędem, zanim cokolwiek powstało. Model wywołał `load_capability` ze zgadniętym id `document-review-first-pass` (z myślnikami, jak w nazewnictwie galerii), które nie istnieje. Id przypisanego skilla to jego dokładna zapisana nazwa, „Document review first pass”. Model spróbował drugi raz z inną błędną nazwą, a run zakończył się komunikatem „the agent could not finish this turn”, przy koszcie 0,0083 USD za dwa zgadywania. Nowa próba w nowej rozmowie od razu użyła właściwego id. Praktyczne rozwiązanie to jedna ponowna próba. Jeśli model dalej zgaduje źle, podanie w instrukcjach dokładnej zapisanej nazwy skilla całkowicie usuwa zgadywanie.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Run kończy się komunikatem „could not finish this turn”, zanim cokolwiek powstanie.** Zobacz zapisany run powyżej: wywołanie `load_capability` zgadło id skilla, zamiast skopiować je z katalogu. Spróbuj ponownie w nowej rozmowie albo podaj w instrukcjach dokładną nazwę skilla.
- **Agent mówi, czy podpisać.** Zaostrz „you do not advise” i sprawdź to wprost pytaniem uzupełniającym. Narzędzie do listy kontrolnej, które odpowiada „tak, jest w porządku”, gdy tylko ktoś zapyta, wychodzi poza swoje zadanie.
- **Odstępstwo nie ma numeru klauzuli.** Instrukcje wymagają go przy każdej pozycji. Brak odniesienia przy skądinąd poprawnym wniosku i tak warto zgłosić, bo kolejny czytelnik nie sprawdzi go bez numeru.
- **Lista brakujących klauzul wymyśla coś, co umowa ma.** Przeczytaj źródło bezpośrednio. Lista kontrolna oczekuje mniej więcej tuzina standardowych pozycji. Krótkiemu przykładowi zawsze będzie brakować kilku, a model musi poprawnie wskazać te, których naprawdę nie ma, a nie tylko wypisać długą listę.
- **Dwa agenty z tym samym skillem dają różne listy kontrolne.** Skill to jeden wiersz, współdzielony po nazwie. Sprawdź w **Skills**, czy nikt nie ma na nim oczekującej, nieopublikowanej propozycji zmiany. Zobacz [agent może zaproponować zmianę, a wprowadza ją człowiek](../skills.md#an-agent-can-propose-a-change-a-person-makes-it).

## Zapisz próbę { #record-the-trial }

Zachowaj dokładny tekst umowy, odpowiedź, wersję agenta, wersję samego skilla i model. Człowiek nadal sprawdza każde odniesienie ze źródłem i decyduje, co zrobić z każdym odstępstwem. Zadaniem agenta jest je wskazać, a nie zamknąć.

## Kolejne kroki { #next-steps }

Dodaj `legal/contract-clause-library`, gdy będziesz mieć zatwierdzone stanowisko do porównywania klauzul, żeby odstępstwo można było zgłosić razem z właściwym stanowiskiem zapasowym, a nie tylko jako „różni się od standardu”. Przy dłuższej umowie z kilkoma dokumentami do porównania [wyszukiwanie w wiedzy](knowledge-base-assistant.md) odpowiada na inne pytanie niż ta strona: wyszukuje fragment w dużym zbiorze, zamiast przeglądać od początku do końca jeden załączony dokument.
