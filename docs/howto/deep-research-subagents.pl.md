---
source_sha: "c7ac418a906b"
title: "Zbadaj pytanie z subagentami i opublikuj raport"
description: "Podziel pytanie na niezależne pytania cząstkowe, deleguj każde do jednorazowego specjalisty i opublikuj porównanie ze źródłami jako aplikację."
---

# Zbadaj pytanie z subagentami i opublikuj raport { #research-a-question-with-subagents-and-publish-a-report }

Zbuduj agenta, który dzieli pytanie na niezależne części, przekazuje każdą własnemu specjaliście i pisze raport z tego, co wróci. Przykładem jest porównanie trzech licencji open source: stabilny, publiczny temat, w którym każde twierdzenie da się sprawdzić z samym tekstem licencji. To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu.
- Wyszukiwanie w sieci: domyślna metoda to DuckDuckGo i nie wymaga konta ani klucza.
- Bez sandboksa, kolekcji wiedzy i połączenia MCP.

## Przygotuj dane wejściowe { #prepare-the-input }

Pytanie dzieli się na trzy niezależne pytania cząstkowe, po jednym na licencję. Zapytaj:

```text
Compare the MIT licence, the Apache License 2.0 and the GPLv3 on one question:
when you distribute software that includes code under that licence, what are
you obligated to do - include the licence text, state changes you made, or
disclose or release your own source code?
```

Odpowiedź referencyjna, żeby ręcznie sprawdzić raport agenta:

| Licencja | Dołącz tekst licencji | Opisz zmiany | Udostępnij swój kod źródłowy |
| --- | --- | --- | --- |
| MIT | Tak | Nie | Nie |
| Apache-2.0 | Tak, razem z plikiem `NOTICE` | Tak, dla każdego pliku | Nie |
| GPLv3 | Tak | Tak, dla każdego pliku | Tak, dla całego połączonego dzieła, przy dystrybucji |

Obowiązek udostępnienia kodu w GPLv3 uruchamia dystrybucja, a nie modyfikacja: organizacja, która tylko używa zmodyfikowanej kopii wewnętrznie, nie musi niczego nikomu udostępniać.

## Zbuduj agenta { #build-the-agent }

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
2. W **Toolbox** włącz **Delegation**. Włącz `allow_dynamic`, czyli ustawienie, które pozwala modelowi wymyślić jednorazowego specjalistę do pytania cząstkowego, dla którego nikt wcześniej go nie przygotował. Ustaw tryb na **Async**, żeby trzy pytania cząstkowe szły jednocześnie, a nie po kolei, i zostaw limit rozgałęzień na 3.
3. Nadal w Delegation przełącz **Share Web search with delegates** i **Share Web fetch with delegates**. Specjalista wymyślony przez model [celowo](../reference/capabilities.md#delegation) nie dostaje własnych capabilities. Trafia do niego tylko to, co rodzic jawnie udostępni, więc bez tego kroku każdy wymyślony specjalista mógłby delegować, ale nie mógłby szukać.
4. Włącz **Web search** (metoda DuckDuckGo) i **Read web pages** u samego rodzica. Udostępnić delegatowi można tylko to, co ma przypisane rodzic.
5. Włącz **Planning** i **Aplikacje**.
6. Ustaw budżet i limit kroków na czas próby. Zapisany run użył 40 kroków i kosztował około 0,43 USD.
7. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You research a question that splits into independent sub-questions.
Write a plan naming each sub-question as its own step.
For each sub-question, call delegate to create a one-off specialist with
mode="async": give it a narrow instruction (research exactly this one
sub-question, using web search and web fetch, and answer with a short sourced
summary), a clear name, and no capabilities argument.
After firing all the sub-questions, call wait_tasks for all of them before
writing anything.
Every claim in your final report must carry the source URL it came from.
State plainly where the sources disagree or where you could not find an answer.
Publish the finished report with publish_artifact under the name
licence-comparison.
Do not answer from your own training knowledge without a source URL next to it.
```

## Uruchom { #run-it }

Otwórz nowy czat z agentem i wyślij pytanie z sekcji *Przygotuj dane wejściowe*.

Model wywołuje `delegate` trzy razy, raz na licencję. Każde wywołanie to osobna delegacja, a nie jedno wywołanie robiące wszystkie trzy. **Delegate ma efekty uboczne**, więc wszystkie trzy parkują do zatwierdzenia razem, bo jeden krok modelu może zaparkować kilka wywołań naraz. Przeczytaj trzech proponowanych specjalistów, a potem **Approve**. Run wznawia się, uruchamia trzech specjalistów w tle i wywołuje `wait_tasks`, żeby zebrać ich wyniki przed napisaniem raportu.

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Liczba delegacji | Trzy, po jednej na licencję, każda jako osobny wiersz w Activity pod runem rodzica |
| Obowiązek z MIT | Dołączyć tekst licencji i informację o prawach autorskich, nic więcej |
| Obowiązek z Apache-2.0 | Tekst licencji, plik `NOTICE` i informacja o zmianach w każdym pliku |
| Obowiązek z GPLv3 | Tekst licencji, zmiany w każdym pliku i pełny kod źródłowy przy dystrybucji |
| Każde twierdzenie | Ma URL źródła tuż obok, a nie zebrany na jednej liście na końcu |
| Sprzeczność albo luka | Raport mówi o niej wprost albo stwierdza, że jej nie było |
| Aplikacja | **Aplikacje** wymienia `licence-comparison`, prywatną dla Ciebie |
| Pytanie z dwóch części, z których tylko jedna ma prawdziwe źródło (np. o licencję, która nie istnieje) | Raport mówi, że nie potwierdził tej części, zamiast wymyślać odpowiedź |

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter. Agent napisał plan z czterech kroków, a potem w jednej turze trzy razy wywołał `delegate`: `mit-licence-research`, `apache2-licence-research`, `gplv3-licence-research`, wszystkie asynchronicznie. Wszystkie trzy zaparkowały do zatwierdzenia w jednym kroku. Po zatwierdzeniu run wywołał `wait_tasks` i dostał `3/3 finished`. Raport dokładnie zgadzał się z tabelą referencyjną, cytował strony OSI, Apache.org, GNU.org i FAQ FSF i kończył się zdaniem „No source disagreements found” z wymienieniem zgodnych źródeł. Opublikował `licence-comparison` jako aplikację HTML. Łączny koszt: 0,43 USD razem ze wszystkimi trzema delegacjami. Dynamiczny specjalista nie ma osobnego wiersza `agent_runs`, bo nie jest opublikowanym agentem.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Delegacja jest od razu odrzucana, a nie parkowana.** Delegation jest wyłączone albo `allow_dynamic` jest wyłączone, a model i tak spróbował `delegate` albo `create_agent`. Bez żadnego z nich delegacja oferuje tylko `task`.
- **Specjalista zgłasza, że nie ma narzędzia wyszukiwania.** Nie ustawiono `share_with_delegates` albo wskazuje ono capability, której nie ma przypisanej sam rodzic. Publikacja odrzuca ten drugi przypadek, więc zwykle chodzi o pierwszy.
- **Trzy pytania cząstkowe idą po kolei, a nie razem.** Tryb to `sync` albo model sam wybrał `mode="sync"` we własnych wywołaniach `delegate` wbrew instrukcjom.
- **Pojawia się tylko jedna delegacja, obejmująca wszystko.** Model potraktował pytanie z trzech części jako jedno zadanie, zamiast je podzielić. Zaostrz instrukcje tak, żeby mówiły o delegowaniu każdej części osobno, a nie tylko o jej zbadaniu.
- **Run zatrzymuje się komunikatem „reached the fan-out ceiling”.** W jednej turze uruchomiono więcej delegacji niż `max_fanout`. Trzy pytania cząstkowe mieszczą się w domyślnym limicie 3, czwarte by się nie zmieściło.

## Zapisz próbę { #record-the-trial }

Zachowaj pytanie, plan napisany przez agenta, nazwę i wynik każdej delegacji, cytowane źródła, aplikację i jej wersję oraz koszt z Activity. Człowiek nadal czyta aplikację obok faktów referencyjnych, zanim mu zaufa, decyduje, kto może go czytać, i ocenia, czy sekcja „could not confirm” jest uczciwa, czy ukrywa wyszukiwanie, które należało powtórzyć.

## Kolejne kroki { #next-steps }

Gdy to działa na temacie ze znaną odpowiedzią, skieruj agenta na pytanie bez gotowego punktu odniesienia i polegaj na instrukcji „state where sources disagree” zamiast na tabeli, którą już znasz. Żeby raport był aktualny, przejdź do strony [Zaplanuj cotygodniowy raport](scheduled-report.md).
