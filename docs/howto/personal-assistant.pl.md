---
source_sha: "fc6566006c49"
title: "Zbuduj osobistego asystenta, który Cię pamięta"
description: "Daj agentowi pamięć o Twoich preferencjach, sprawdź, czy późniejsza rozmowa je stosuje, a potem upewnij się, że potrafi jedną zapomnieć na prośbę."
---

# Zbuduj osobistego asystenta, który Cię pamięta { #build-a-personal-assistant-that-remembers-you }

Zbuduj asystenta, który prowadzi własne notatki o osobie, z którą rozmawia, między rozmowami, bez niczego do podłączenia i bez zewnętrznego konta. Podaj kilka syntetycznych preferencji, otwórz nową rozmowę i sprawdź, czy asystent z nich korzysta, a potem poproś, żeby jedną zapomniał. To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu.
- Bez sandboksa, modelu embeddingów i połączenia MCP. [Pamięć](../reference/capabilities.md#memory-files) działa bez niczego przypisanego.

## Przygotuj dane wejściowe { #prepare-the-input }

To wymyślone fakty o fikcyjnej osobie, na tyle krótkie, że sprawdzisz je z odpowiedziami asystenta:

```text
Timezone: Europe/Warsaw
Meeting-free day: Friday
Summary format: short bullet points, not paragraphs
```

## Zbuduj agenta { #build-the-agent }

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
2. W **Toolbox** włącz **Memory**, **Date and time** i **Past conversations**. Dodaj **Web search**, jeśli brief poniżej ma coś wyszukiwać; sprawdzenia tutaj tego nie wymagają.
3. Ustaw budżet i limit kroków na czas próby. Zapisane runy używały 5–15 kroków i kosztowały około 0,01–0,04 USD każdy.
4. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You are a personal assistant that remembers what this person tells you about themselves.
When the person states a preference or a standing fact (timezone, working hours, meeting-free days, how they like summaries formatted), save it with write_memory under a short name, then read MEMORY.md and add or update a one-line entry for it with edit_memory (or write_memory if MEMORY.md does not exist yet).
When asked for a plan, a summary or a morning brief, apply every preference currently in your notes: check MEMORY.md, read any note it lists that is relevant, and follow it without being asked again.
When asked to forget something, delete the matching note with delete_memory, remove its line from MEMORY.md with edit_memory, and confirm in one sentence what you forgot.
Never save something the person has not actually told you.
```

`write_memory`, `edit_memory` i `delete_memory` mają efekty uboczne, więc każde zapisanie albo zapomnienie domyślnie parkuje jako **Tool approval required**, tak jak każdy inny zapis. Zatwierdź, żeby kontynuować.

## Uruchom { #run-it }

**Rozmowa 1**: podaj preferencje.

```text
A few things about me: I'm in the Europe/Warsaw timezone, I keep Fridays meeting-free, and I prefer summaries as short bullet points rather than paragraphs.
```

**Rozmowa 2**: nowa rozmowa z tym samym agentem, z prośbą o użycie tego, czego się dowiedział.

```text
Give me a plan for tomorrow. I have three things to fit in: a client call, writing a proposal, and a team sync.
```

**Rozmowa 3**: poproś, żeby zapomniał jedną z trzech.

```text
Forget my meeting-free Fridays preference.
```

Harmonogram widzi instrukcje tego agenta, ale nie notatki jego właściciela. Zanim podłączysz poranny brief do harmonogramu, przeczytaj [czego harmonogram nie może przeczytać](#what-a-schedule-cannot-read).

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Odpowiedź w rozmowie 1 | Potwierdza wszystkie trzy preferencje po zatwierdzeniu trzech wywołań `write_memory` i jednego, które zapisuje `MEMORY.md` |
| `MEMORY.md` po rozmowie 1 | Wymienia `timezone`, `meeting_free_days` i `summary_format` |
| Plan z rozmowy 2 | Używa Europe/Warsaw, składa się głównie z punktów i nie stosuje błędnie zasady piątkowej do dnia, który nie jest piątkiem |
| Odpowiedź w rozmowie 3 | Jednym zdaniem mówi, co zapomniał |
| Settings → Memory (albo `GET /memory/mine`) po rozmowie 3 | `meeting_free_days` zniknęło całkowicie; dwie pozostałe notatki są niezmienione |
| **Run now** harmonogramu z porannym briefem, zanim cokolwiek mu powiedziano w czacie | Mówi, że nic nie jest zapisane, zamiast zgadywać; zobacz niżej |

Otwórz Activity dla każdego runu i sprawdź wywołania narzędzi, a nie tylko odpowiedź: `write_memory`, które model wywołał, ale którego nikt nie zatwierdził, nigdy się nie wydarzyło.

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter. Rozmowa 1 wywołała `write_memory` trzy razy, a po zatwierdzeniu zapisała `MEMORY.md` jako `- timezone [preference] — …`, `- meeting_free_days [preference] — …`, `- summary_format [preference] — …`. Koszt: 0,039 USD.

    Rozmowa 2 wywołała `read_memory` dla wszystkich trzech notatek oraz `search_conversations` (które poprawnie nic nie znalazło, bo o jutrze jeszcze nic nie mówiono), a potem odpowiedziała planem w punktach w czasie Europe/Warsaw i zauważyła, że jutro jest sobota, więc zasada dni bez spotkań nie ma zastosowania. Koszt: 0,026 USD.

    Rozmowa 3 wywołała `delete_memory` dla `meeting_free_days`, a po zatwierdzeniu `read_memory` i `edit_memory` na `MEMORY.md`, żeby usunąć jego linię, i odpowiedziała „Done — I've forgotten your meeting-free Fridays preference and removed it from my index.” `GET /memory/mine` pokazał potem tylko `timezone` i `summary_format`. Koszt: 0,043 USD.

## Czego harmonogram nie może przeczytać { #what-a-schedule-cannot-read }

Uruchomienie z harmonogramu albo triggera zdarzeń działa z rolą i uprawnieniami twórcy, ale dla pamięci nie jest niczyją rozmową. `list_memory` w **Run now** harmonogramu z porannym briefem odpowiedziało „This conversation has no memory. It has no identified person and is not a group chat, so a note would have to land somewhere other people read”, czyli tą samą odmową, którą dostaje anonimowy gość widgetu, choć twórca harmonogramu jest prawdziwym, znanym członkiem organizacji.

Jeśli zaplanowany brief potrzebuje preferencji, zapisz ją w prompcie samego harmonogramu, tak jak [zaplanowany raport](scheduled-report.md) podaje swoje dane w wiadomości, zamiast polegać na pamięci albo pliku, którego nikt ponownie nie dostarczy.

## Kto może to czytać { #who-can-read-this }

Nikt nie czyta Twoich notatek z racji roli w organizacji: ani Owner, ani Admin, ani ktoś z uprawnieniem do edycji tego agenta. Własne notatki znajdziesz w **Settings → Memory** (`GET /memory/mine`), gdzie możesz przestać używać notatki, znów zacząć jej używać albo całkiem ją usunąć. „Przestań używać” zostawia ją na stronie dla Ciebie, ale nie trafia już do żadnego modelu. Cudze notatki może przeczytać tylko administrator wdrożenia, jedną osobę naraz, a taki odczyt trafia do dziennika audytu z wykonawcą, osobą, której dotyczy, i powodem, ale nigdy z treścią. Zobacz [czyje notatki i kto może je usłyszeć](../reference/capabilities.md#whose-notes-and-who-may-hear-them) oraz [odczyt i usuwanie](../reference/capabilities.md#reading-it-and-erasing-it).

W czacie grupowym zasada się zmienia: notatki należą do pokoju i czytają je wszyscy jego uczestnicy, a nic, co powiedziano asystentowi na osobności, nie jest tam przywoływane. Ta próba używała tylko czatu webowego jeden na jeden, gdzie magazyn należy wyłącznie do Ciebie.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Zapisanie albo zapomnienie nigdy się nie dzieje.** `write_memory`, `edit_memory` i `delete_memory` mają efekty uboczne i domyślnie są za bramką. Sprawdź **Approvals** w Activity, czy nie czeka zaparkowane wywołanie, zanim uznasz, że model zignorował polecenie.
- **Późniejsza rozmowa nie zna zapisanej preferencji.** Sprawdź sam `MEMORY.md`. Notatka zapisana, ale niewpisana do indeksu, jest niewidoczna, dopóki model nie wywoła `list_memory`, czego lżejszy model może nie zrobić sam z siebie.
- **Zaplanowany brief zgaduje, zamiast użyć Twoich notatek.** Tak ma być; zobacz wyżej [czego harmonogram nie może przeczytać](#what-a-schedule-cannot-read). Wpisz fakt do promptu harmonogramu.
- **Usunięcie notatki nie usuwa jej wszędzie.** `delete_memory` usuwa samą notatkę. Jeśli linia w `MEMORY.md`, która ją wymienia, nie zostanie też przepisana przez `edit_memory`, indeks nadal opisuje coś, czego już nie ma.

## Zapisz próbę { #record-the-trial }

Zachowaj każdą rozmowę, wersję agenta, informację, które wywołania `write_memory`/`delete_memory` zatwierdzono, oraz `GET /memory/mine` przed i po prośbie o zapomnienie. Człowiek nadal zatwierdza każde zapisanie i usunięcie, decyduje, czy **Allow personal memory** zostaje włączone dla tego agenta, i ocenia, czy plan naprawdę odzwierciedla to, co powiedziano. Asystent sam siebie nie sprawdza.

## Kolejne kroki { #next-steps }

Żeby korzystać z tego asystenta przez harmonogram zamiast czatu webowego, najpierw przeczytaj [czego harmonogram nie może przeczytać](#what-a-schedule-cannot-read), a potem [Zaplanuj cotygodniowy raport](scheduled-report.md), gdzie opisano mechanikę rytmu i rozmowy z dziennikiem runów. Żeby mógł przeszukiwać to, co faktycznie powiedziano w poprzednich rozmowach, a nie tylko to, co sam zdecydował się zapisać, zobacz [wyszukiwanie w rozmowach](../reference/capabilities.md#conversation-search).
