---
source_sha: "9d46f3e89ce9"
title: "Tłumacz dokumenty z własną terminologią"
description: "Przypisz agentowi glosariusz z dziesięcioma terminami i sprawdź, czy każdy termin zostaje zastosowany, terminy bez tłumaczenia i liczby zostają nietknięte, a niejednoznaczność jest oznaczona, a nie po cichu rozstrzygnięta."
---

# Tłumacz dokumenty z własną terminologią { #translate-documents-with-your-terminology }

Daj agentowi krótki angielski dokument i skill z Twoim glosariuszem, a potem niech przetłumaczy go na inny język, zostawiając po angielsku nazwy produktów, nazwy funkcji i inne terminy, których się nie tłumaczy. Przykład zawiera naprawdę niejednoznaczną datę, więc możesz sprawdzić, czy agent ją oznaczy, zamiast po cichu zgadywać. To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu.
- Bez sandboksa i modelu embeddingów. Ten agent potrzebuje tylko [capability skills](../reference/capabilities.md#skills) i załącznika w czacie.

## Przygotuj dane wejściowe { #prepare-the-input }

Zapisz to jako skill w **Skills → New skill**. Nazwij go `fenwick-glossary` i dodaj opis w rodzaju „Which terms in a Fenwick Ledger document stay in English, and the preferred Polish translation for the rest.” Fenwick Ledger to syntetyczny produkt księgowy wymyślony na potrzeby tego testu.

```text
Fenwick Ledger is a synthetic accounting product used only for this test.

## Keep in English, never translate

- Fenwick Ledger (product name)
- Quick Close (feature name)
- workspace
- API key
- sandbox

## Translate using these terms

| English | Polish |
|---|---|
| ledger | księga |
| invoice | faktura |
| reconciliation | uzgadnianie |
| dashboard | pulpit |
| audit trail | ślad audytu |

Numbers, dates and currency amounts are copied exactly as they appear in the
source — do not reformat a date or convert a currency. If a sentence in the
source could be read two ways, translate the more likely reading and add one
line after the translation flagging the ambiguity and both readings.
```

Potem zapisz ten syntetyczny dokument jako `release-notes.md`. Data `03/04/2026` jest celowo niejednoznaczna: można ją czytać jako dzień/miesiąc albo miesiąc/dzień. To właśnie ten przypadek ma sprawdzić przykład.

```text
Fenwick Ledger 4.2 release notes

This release adds Quick Close, a one-click way to close the monthly ledger
once every invoice is matched. Quick Close runs the reconciliation for the
current period and shows the results on the dashboard.

Every action Quick Close takes is written to the audit trail, so a
controller can see which invoices were matched automatically and which
needed a manual review.

To use Quick Close in a shared workspace, generate an API key from Settings
and add it to your sandbox environment before running your first close.

The reconciliation step handles invoices up to EUR 50,000 automatically;
anything above that amount is queued for manual approval.

Close the March books by 03/04/2026, before the quarterly audit begins.

Fenwick Ledger is a synthetic product created for this test; no real company
or software is described here.
```

## Zbuduj agenta { #build-the-agent }

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
2. W **Toolbox** włącz **Skills** i przypisz skill `fenwick-glossary`.
3. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You translate documents into Polish.
Follow the bound glossary skill: never translate the terms it lists as
English-only, and use its preferred Polish translation for the rest.
Copy every number, date and currency amount exactly as it appears in the
source.
If a sentence could be read two ways, translate the more likely reading and
add one line after the translation flagging the ambiguity and both readings.
```

## Uruchom { #run-it }

Otwórz nowy czat z agentem, załącz `release-notes.md` i wyślij:

```text
Translate the attached release notes into Polish.
```

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Pięć przetłumaczonych terminów z glosariusza | ledger→księga, invoice→faktura, reconciliation→uzgadnianie, dashboard→pulpit, audit trail→ślad audytu |
| Pięć terminów bez tłumaczenia zachowanych | Fenwick Ledger, Quick Close, workspace, API key, sandbox pojawiają się po angielsku |
| Kwota bez zmian | `EUR 50,000` pojawia się dokładnie tak, bez przeliczenia i przeformatowania |
| Data bez zmian | `03/04/2026` pojawia się dokładnie tak, bez zmiany na polski format daty |
| Oznaczona niejednoznaczność | Osobna uwaga podaje oba odczytania `03/04/2026` |
| To samo polecenie bez załączonego pliku | Agent prosi o dokument, zamiast tłumaczyć nic |

Czytaj polski tekst z glosariuszem, termin po terminie. Nie ufaj podsumowaniu, które tylko wymienia znalezione terminy.

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter. Agent wywołał `load_capability` dla `fenwick-glossary`, a potem przetłumaczył cały dokument w jednej odpowiedzi. Wszystkie pięć terminów z glosariusza zostało przetłumaczonych poprawnie, a wszystkie pięć terminów bez tłumaczenia, w tym `workspace`, `API key` i `sandbox` w polskich zdaniach, zostało po angielsku. `EUR 50,000` i `03/04/2026` zostały skopiowane bez zmian. Koszt: 0,017 USD.

    Po tłumaczeniu agent dodał oznaczoną uwagę: przy odczycie dzień/miesiąc 03/04/2026 to 3 kwietnia 2026 (użyte w tłumaczeniu), a przy odczycie miesiąc/dzień to 4 marca 2026. Zalecił potwierdzenie, o którą datę chodziło. Bez załączonego pliku wczytał glosariusz, a potem poprosił o dokument, zamiast tłumaczyć nic.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Termin, którego nie tłumaczy się, i tak zostaje przetłumaczony.** Model może traktować go jak zwykłe słownictwo, a nie nazwę własną. Umieść listę na początku treści skilla i powtórz polecenie we własnych instrukcjach agenta.
- **Zmienia się liczba.** Poproś agenta, żeby cytował zdanie źródłowe obok tłumaczenia. Rozbieżność od razu będzie widoczna.
- **Niejednoznaczność zostaje po cichu rozstrzygnięta.** Zaostrz instrukcje tak, żeby wymagały osobnej linii z oznaczeniem, zamiast zostawiać wybór domyślnemu sformułowaniu skilla.
- **Agent tłumaczy bez załączonego pliku.** Zaostrz instrukcje tak, żeby wymagały odmowy, gdy nie ma dokumentu.

## Zapisz próbę { #record-the-trial }

Zachowaj dokument źródłowy, treść glosariusza, tłumaczenie, wersję agenta i run w Activity. Osoba znająca język docelowy nadal sprawdza płynność tłumaczenia i potwierdza, o które odczytanie oznaczonej niejednoznaczności faktycznie chodziło. Glosariusz i powyższe sprawdzenia wychwytują terminologię i zachowane wartości, a nie to, czy zdanie brzmi naturalnie.

## Kolejne kroki { #next-steps }

Produkcyjny glosariusz trzymaj w jednym skillu na parę języków, a nie w jednym skillu z wymieszanymi wszystkimi językami, żeby tłumacz mógł przejrzeć i edytować tylko swoją parę. [Wpis DeepL](../mcp.md#automation-storage-productivity-media) w katalogu MCP to alternatywny silnik tłumaczeń, który można podłączyć zamiast używać bezpośrednio modelu. Ta strona z niego nie korzysta.
