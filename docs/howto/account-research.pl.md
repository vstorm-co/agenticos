---
source_sha: "bfce080544ad"
title: "Przygotuj brief o firmie przed rozmową"
description: "Zbadaj publiczną organizację wyszukiwaniem i pobieraniem stron, a potem dostań jednostronicowy brief, w którym każdy fakt ma swoje źródło i datę."
---

# Przygotuj brief o firmie przed rozmową { #brief-yourself-on-a-company-before-a-call }

Zbuduj agenta, który bada organizację i pisze jednostronicowy brief przed rozmową z nią: czym się zajmuje, najnowsze wiadomości, obecne kierownictwo i to, czego nie udało się potwierdzić. Przykładem jest znana fundacja open source, więc brief możesz sprawdzić ze źródłami, które każdy może otworzyć. To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu.
- Wyszukiwanie w sieci: domyślna metoda to DuckDuckGo i nie wymaga konta ani klucza.
- Bez kolekcji wiedzy, sandboksa i połączenia MCP.

## Zbuduj agenta { #build-the-agent }

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
2. W **Toolbox** włącz **Web search** (metoda DuckDuckGo) i **Web fetch**.
3. Ustaw budżet i limit kroków na czas próby. Zapisany run użył 20 kroków i kosztował około 0,26 USD.
4. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You write a one-page brief on an organization before a call with them.
Research it with web search and web fetch before writing anything.

Rules:

- Every fact in the brief carries the source URL it came from, next to the
  fact, not collected in a list at the end.
- Next to each fact, name the date: either the date the source page itself
  states (an article date, a filing date) or, when the source carries none,
  the date you fetched it, marked as "(fetched)".
- Never state a person's name, title or any personal detail unless a source
  confirms it. If you cannot confirm who currently holds a role, say so
  instead of guessing, and do not use a plausible-sounding name.
- Do not repeat a home address, personal phone number or other private
  contact detail even if a source shows one. The brief covers the
  organization, not the people in it.
- End with a section called "Could not confirm" naming anything you looked
  for but did not find a source for. An empty section still gets the heading,
  with one line saying nothing was left unconfirmed.
```

## Uruchom { #run-it }

Otwórz nowy czat z agentem i wyślij:

```text
Brief me on the Python Software Foundation before a call with them.
```

Tak samo działa każda znana publiczna organizacja. Duża fundacja open source to dobry wybór domyślny, bo jej finanse, zarząd i misja są opublikowane i na tyle stabilne, że da się je sprawdzić.

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Każde twierdzenie o faktach | Ma URL źródła tuż obok |
| Data każdego twierdzenia | Podaje własną datę źródła albo „(fetched)”, gdy źródło jej nie ma |
| Wymienione osoby | Tylko te, które potwierdza źródło, z odnośnikiem do strony samej organizacji, a nie zgadywane |
| Rola, której nikt nie potwierdził | Mówi to wprost, zamiast podawać wiarygodnie brzmiące nazwisko |
| Prywatne dane kontaktowe | Nieobecne, nawet jeśli któreś źródło je pokazało |
| Sekcja „Could not confirm” | Jest i wskazuje realną lukę, a nie jest pusta przez pominięcie |
| To samo pytanie o organizację, która prawie nie istnieje w sieci | Mówi o tym i daje krótki, uczciwie skromny brief, zamiast wymyślać szczegóły dla wypełnienia strony |

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter. Agent wykonał trzy wywołania `web_search`, a potem `web_fetch` na stronach PSF: o fundacji, o zarządzie i z raportem rocznym za 2024 rok, a do tego na wpisie o programie grantów i agregatorze formularzy 990. Jedno `web_fetch` (strona z dokumentami) się nie powiodło i agent nie spróbował innego źródła dla tego faktu.

    Brief podawał źródło przy każdym twierdzeniu: misji, programach, finansach za rok obrotowy 2024, sumie grantów za 2024 rok i pełnym składzie zarządu, każde z datą ze źródła albo oznaczeniem „(fetched)”. Zarząd wymienił wyłącznie na podstawie strony PSF z jego składem. Najlepiej wynagradzanej osoby, której nazwisko pojawiło się we fragmencie wyniku wyszukiwania formularza 990, celowo nie wymienił, bo samego dokumentu nie dało się bezpośrednio otworzyć. Tę lukę, a także dokładny podział przychodów i daty najbliższego PyConu, umieścił w sekcji „Could not confirm”. Koszt: 0,26 USD.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Osoba jest wymieniona bez źródła obok.** Zaostrz instrukcje tak, żeby źródło było wymagane w miejscu twierdzenia, a nie gdziekolwiek w odpowiedzi. Model, który przeczytał nazwisko mimochodem przy innym researchu, może je powtórzyć bez zamiaru.
- **Brief nie ma sekcji „Could not confirm”.** Instrukcje nie zostały wykonane albo agent nie szukał niczego, czego mogłoby zabraknąć. Sprawdź wywołania narzędzi w transkrypcji, zanim zaufasz briefowi, który znalazł wszystko.
- **`web_fetch` się nie udaje, a fakt po prostu znika.** Model poszedł dalej, zamiast spróbować drugiego źródła. Poproś go, żeby nazywał to, czego nie udało się pobrać. Dokładnie tak wyglądała luka z formularzem 990 w zapisanym runie.
- **Dane finansowe albo o kierownictwie wyglądają na aktualne, a mają rok.** Sprawdź datę przy każdym z nich. Strona bez daty publikacji z dopisaną datą pobrania to nie to samo twierdzenie co fakt datowany na źródle.
- **Ta sama organizacja ma inny zarząd w kolejnym runie.** Wyniki wyszukiwania nie są stabilne między runami. Sprawdź, z której strony pochodzi każde nazwisko, zanim zaufasz którejkolwiek wersji, i przedkładaj stronę samej organizacji nad fragment wyniku wyszukiwania.

## Zapisz próbę { #record-the-trial }

Zachowaj pytanie, brief, źródła, które cytował, run w Activity z wywołaniami narzędzi i koszt. Człowiek nadal czyta brief ze źródłami przed rozmową, decyduje, czy luka z „could not confirm” jest na tyle ważna, żeby sprawdzić ją ręcznie, i nigdy nie powtarza niepotwierdzonego szczegółu osobistego, nawet jeśli późniejszy run poda go pewnym tonem.
