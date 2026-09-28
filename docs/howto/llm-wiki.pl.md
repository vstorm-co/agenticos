---
source_sha: "2db3d6fc670a"
title: "Zbuduj LLM wiki, które prowadzi agent"
description: "Daj agentowi workspace, który przetrwa między rozmowami, i plik schematu, a potem pozwól mu zamieniać surowe notatki w małe, powiązane wiki w Markdownie."
---

# Zbuduj LLM wiki, które prowadzi agent { #build-an-llm-wiki-the-agent-maintains }

Andrej Karpathy opisał ten wzorzec w kwietniu 2026: surowe źródła trzymaj nietknięte w jednym miejscu, niech agent kompiluje je w małe, powiązane wiki w Markdownie w innym, i zapisz schemat, żeby każda późniejsza sesja mogła się z nim porównać, zamiast znowu zgadywać układ. Ta strona buduje to na workspace'ie, który przeżywa pojedynczą rozmowę, z dwoma syntetycznymi źródłami dodanymi w odstępie jednej sesji.

To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia. Dwie rozmowy z dodawaniem źródeł poniżej zostały wykonane w całości; do pytania i kroku lint w tym runie nie doszło i są tak oznaczone.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu i zarejestrowanym [połączeniem sandboksa](../sandbox.md) z runtime'em `workbench`.
- Żadnej innej capability. Wiki żyje w całości w workspace'ie agenta.

## Przygotuj dane wejściowe { #prepare-the-input }

Dwie krótkie notatki, które wyglądają na niepowiązane, ale mają wspólny fakt, więc wiki ma powód, żeby je ze sobą połączyć.

Źródło pierwsze, wklejone w pierwszej rozmowie:

```text
Meeting notes, 3 March. The team adopts a weekly on-call rotation starting
Monday. Alice is on-call first, then Bob, then Carol, rotating every Monday
at 9am. Escalation rule: if the on-call person does not respond within 15
minutes, page the backup, who is always the previous week's on-call person.
```

Źródło drugie, wklejone w drugiej, osobnej rozmowie:

```text
Incident report, 11 March. A database outage occurred on Tuesday. Alice was
on-call and responded within 5 minutes; the backup escalation was not
needed. Root cause: a migration script left a lock unreleased. Fix: the
migration now acquires the lock with a timeout.
```

Fakt referencyjny, który strona wiki musi przenieść przez obie notatki: Alice miała dyżur podczas awarii z powodu grafiku ustalonego 3 marca, a zasada zastępstwa z tego samego grafiku nie zadziałała.

## Zbuduj agenta { #build-the-agent }

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
2. W **Toolbox** włącz **Files & shell**. Wybierz **Container**, swoje połączenie sandboksa i runtime `workbench`.
3. Ustaw **session scope na `user`**, a nie domyślne `conversation`. Workspace o zakresie rozmowy w kolejnym czacie zaczyna od zera, a to dokładnie ten błąd „wiki wszystko zapomina”, który sprawdza ta strona. Workspace o zakresie agenta współdzieli każdy w organizacji, kto rozmawia z tym agentem, co jest złym modelem współdzielenia dla wiki jednej osoby. `user` trzyma jeden workspace dla danej osoby we wszystkich rozmowach i powierzchniach, przez które dociera do agenta, i dla nikogo innego. Co współdzieli każdy zakres, opisuje [Files & shell](../reference/capabilities.md#files-shell).
4. Ustaw budżet i limit kroków na czas próby.
5. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You maintain a small personal LLM wiki in your workspace: raw sources
compiled into a cross-linked Markdown wiki, following this schema.

Layout:
raw/<slug>.md - one file per ingested source, saved verbatim, append-only.
Never edit a raw file once written.
wiki/index.md - one line per wiki page, each a Markdown link to it.
wiki/<topic>.md - one page per topic, written in your own words from the raw
sources. Link related pages with a relative Markdown link.
schema.md - this layout, written once on your first turn if it does not
exist, so any later session can check itself against it.

When asked to ingest a source: read schema.md first, writing it if it is
missing; list wiki/ so you know what exists; save the source verbatim to
raw/<slug>.md; update an existing wiki page if the source is about it, or
create a new one only for a genuinely new topic; cross-link pages that refer
to each other; update wiki/index.md; report which files you touched.

When asked a question, read the relevant wiki page(s) - not the raw sources,
unless a page is missing something the question needs - and answer citing
the page you used by name.

When asked to lint the wiki: list every file, read wiki/index.md and every
page it links to, then report broken links, orphan pages nothing links to,
and any two pages that state different facts about the same thing. Do not
fix anything unless asked; only report.
```

Schemat jest tu w instrukcjach, bo jest krótki. Schemat, który rozrośnie się ponad akapit czy dwa, lepiej pasuje do [pliku kontekstu](../context.md) w trybie `link`, czytanego raz i współdzielonego przez każdego agenta, który prowadzi wiki w ten sposób, zamiast wklejania go do instrukcji każdego z nich.

## Uruchom { #run-it }

W pierwszej, nowej rozmowie:

```text
Ingest this source: [paste source one]
```

Zacznij **drugą, nową rozmowę** z tym samym agentem, a nie odpowiedź w pierwszej, i poproś o dodanie drugiego źródła, a potem zadaj pytanie:

```text
Ingest this source: [paste source two]
```

```text
Who was on-call during the outage, and what is the backup escalation rule?
```

W trzeciej turze albo trzeciej rozmowie poproś o sprawdzenie, wokół którego zbudowany jest ten wzorzec:

```text
Lint the wiki.
```

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| `schema.md` po pierwszej rozmowie | Istnieje i odpowiada układowi z instrukcji |
| Workspace na początku drugiej rozmowy | Ma już `schema.md`, `raw/` i `wiki/` z pierwszej; nic nie jest tworzone od nowa |
| Strony wiki po obu źródłach | Wspominają Alice, kolejność dyżurów i awarię; oba tematy linkują do siebie nawzajem, zamiast leżeć jako dwie niepowiązane strony |
| Odpowiedź na pytanie | Wymienia Alice, cytuje strony wiki i stwierdza, że zasada zastępstwa nie zadziałała |
| Raport lint | Zgodnie z prawdą wymienia każdy zepsuty link i osieroconą stronę, łącznie z „nic nie znaleziono”, zamiast ogólnego „wygląda dobrze” |
| Trzecia rozmowa z pytaniem, bez dodawania niczego nowego | Czyta istniejące wiki i nadal odpowiada, bo workspace należy do osoby, a nie do rozmowy |

Przeczytaj faktyczne pliki w panelu plików rozmowy, a nie tylko odpowiedź. Model, który opisuje aktualizację linku, i model, który go naprawdę zapisał, prozą wyglądają tak samo.

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter, runtime `workbench`, `session_scope: user`. Pierwsza rozmowa nie znalazła `schema.md` ani `wiki/`, zapisała oba według układu z instrukcji, zapisała notatkę o dyżurach do `raw/meeting-notes-2024-03-03.md` i utworzyła `wiki/on-call-rotation.md` oraz `wiki/index.md`. Nie było wywołania `execute`, więc nie trzeba było niczego zatwierdzać. Koszt: 0,1022 USD.

    Druga, osobna rozmowa z tym samym agentem zaczęła od przeczytania `schema.md` i wylistowania `wiki/` i zastała oba na miejscu, więc workspace przetrwał. Zapisała raport z incydentu do `raw/incident-report-11-march.md`, utworzyła `wiki/database-incidents.md` z Alice, 5-minutowym czasem reakcji i przyczyną źródłową, a potem przez `edit_file` dodała w `wiki/on-call-rotation.md` sekcję „Incidents” z linkiem do nowej strony i zaktualizowała `wiki/index.md`, żeby wymieniał obie strony. To prawdziwe powiązanie w obie strony, a nie dwie strony obok siebie. Koszt: 0,1250 USD.

    Awaria infrastruktury niezwiązana z agentem ani z sandboksem przerwała próbę w tym miejscu. Pytania („Who was on-call during the outage...”) i kroku lint nie uruchomiono, więc odpowiadające im wiersze w tabeli powyżej są oczekiwanym kryterium, a nie zaobserwowanym wynikiem. Potwierdzone jest to, co ta strona ma sprawdzić: workspace przetrwał zupełnie osobną rozmowę, a dwa tematy połączyły się ze sobą, zamiast powielać treść.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Druga rozmowa zaczyna od pustego workspace'u.** Zakres to `conversation` albo `agent` wiąże się z innym domyślnym połączeniem niż w pierwszym runie, albo połączenie lub backend zmieniły się między rozmowami. Każda z tych sytuacji uruchamia świeży workspace, zamiast podłączyć stary.
- **Dwie strony powtarzają się, zamiast się łączyć.** Model nie przeczytał `wiki/index.md` przed pisaniem. Zaostrz instrukcje tak, żeby za każdym razem wymagały najpierw wylistowania wiki.
- **Raport lint zawsze mówi, że wszystko jest w porządku.** Poproś o lint wiki, o którym wiesz, że ma problem (najpierw zmień nazwę linkowanego pliku), żeby sprawdzić, czy raport czyta pliki, a nie zakłada.
- **`schema.md` jest przepisywany w każdej rozmowie.** Instrukcje każą zapisać go tylko wtedy, gdy go brakuje. Jeśli model i tak go przepisuje, każ mu wprost czytać przed jakimkolwiek zapisem.
- **Współpracownik widzi notatki, które uważałeś za prywatne.** Sprawdź session scope. `agent` współdzieli jeden workspace ze wszystkimi, którzy rozmawiają z tym agentem, i dlatego Builder ostrzega przy tym polu.

## Zapisz próbę { #record-the-trial }

Zachowaj oba surowe źródła, dokładne prompty, wersję agenta i listę plików workspace'u po każdej rozmowie, a nie tylko odpowiedzi. Człowiek nadal ocenia, czy powiązanie jest naprawdę przydatne, czy tylko istnieje, i czy raport lint wychwycił coś prawdziwego.

## Wiki czy wyszukiwanie w wiedzy? { #wiki-or-knowledge-search }

Odpowiadają na różne potrzeby. [Wyszukiwanie w wiedzy](../reference/capabilities.md#knowledge-search) wyciąga fragmenty z dokumentów, których nikt nie przepisuje, takich jak podpisana umowa czy PDF z polityką, i cytuje źródłowy fragment. Ten wzorzec jest dla materiału, który na początku jest chaotyczny i mały, a warto poświęcić czas agenta na jego *kompilację*: notatek, transkrypcji, niedokończonych opracowań, które zyskują na zamianie w kilka utrzymywanych stron zamiast rosnącej sterty plików źródłowych. Gdy samo skompilowane wiki staje się zbyt duże, żeby je wstrzyknąć albo przeczytać w całości, naturalnym kolejnym krokiem jest przeszukiwanie go jak każdej innej kolekcji, a nie plik w workspace'ie.

## Kolejne kroki { #next-steps }

Spróbuj celowo dodać źródło sprzeczne z wcześniejszym i sprawdź, czy krok lint wymieni obie strony, zamiast po cichu wybrać jedną. Dla wiki, które ma czytać i rozwijać kilka osób, porównaj zakres sesji `agent` z daniem każdemu współautorowi własnego agenta przypisanego do wspólnego [pliku kontekstu](../context.md).
