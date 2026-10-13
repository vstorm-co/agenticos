---
source_sha: "70839ec256fb"
title: "Zamień zadania ze spotkania na taski z zatwierdzeniem"
description: "Niech agent zaproponuje jeden task w trackerze na każde prawdziwe zadanie z transkrypcji spotkania, a człowiek zatwierdza każdy, zanim zostanie utworzony."
---

# Zamień zadania ze spotkania na taski z zatwierdzeniem { #turn-meeting-action-items-into-tasks-with-approval }

Daj agentowi zadania z transkrypcji spotkania i [połączenie MCP z Linear albo Jira](../mcp.md#project-management), a potem niech proponuje jeden task na każdą pozycję, zamiast tworzyć cokolwiek bez nadzoru. Osoba czytająca propozycje poprawia je albo odrzuca, zanim choć jeden task trafi do trackera. Tej strony nie da się tu uruchomić od początku do końca: to środowisko nie ma połączenia z Linear ani Jira, więc poniżej nie ma zapisanego runu.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu.
- **`connections:manage`**, żeby dodać Linear albo Jira jako połączenie MCP dla całej organizacji, albo zwykłe konto członka, żeby podłączyć je dla siebie w **MCP servers → You**.
- Transkrypcja spotkania do pracy. [Streszczenie spotkania](meeting-summary.md) opisuje, jak sprawdzić zawarte w niej decyzje i zadania, zanim którekolwiek stanie się taskiem.

## Przygotuj dane wejściowe { #prepare-the-input }

Mała, wymyślona transkrypcja z jednym jasnym zadaniem, jednym zadaniem bez terminu i jedną zgłoszoną wątpliwością, której nikt faktycznie nie bierze. Ta ostatnia to przypadek brzegowy, który warto sprawdzić:

```text
Weekly ops sync - 24 September 2026
Attendees: Priya, Tom, Sana

- Priya will update the onboarding doc with the new pricing tiers by Friday.
- Tom will follow up with the vendor about the delayed shipment.
- Sana raised that the support queue is growing, but nobody was assigned to look into it.
```

Kryterium: dwa prawdziwe zadania (Priya, termin piątek; Tom, bez podanego terminu) i jedno otwarte pytanie bez właściciela, które nie jest zadaniem.

## Podłącz tracker { #connect-the-tracker }

Linear jest w katalogu z uwierzytelnianiem **oauth** pod `https://mcp.linear.app/sse`. Jira i Confluence mają wspólny wpis, też **oauth**, pod `https://mcp.atlassian.com/v1/sse` (zobacz [katalog](../mcp.md#project-management)). Dla trackera, do którego zgłasza cały zespół, podłącz go w **MCP servers → Organization**, żeby każdy przypisany agent tworzył taski jako ta sama tożsamość integracji. Przypisz zamiast tego [własne konto każdej osoby](../mcp.md#whose-account-a-binding-speaks-through) tylko wtedy, gdy Twój tracker oczekuje, że taski będą zgłaszane jako osoba, która o nie poprosiła.

Na połączeniu zawęź `allowed_tools` do narzędzia tworzenia i komentowania, którego potrzebuje ten przepływ, jeśli serwer oferuje też takie, które edytują albo usuwają istniejące issues. Przypisanie może tylko zawężać w ramach tego, na co pozwala już połączenie, nigdy nie przywraca tego, co ono wyklucza.

## Zbuduj agenta { #build-the-agent }

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
2. W **Toolbox** dodaj tracker w **MCP servers**.
3. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You turn meeting notes into tracker tasks.
Propose one task per real action item: a title, the assignee named in the notes, a due date only if one was actually stated, and a one-line description.
Do not invent an assignee, a due date or a priority that the notes do not state.
If something was raised but nobody was assigned to it, say so as an open question rather than proposing a task for it.
Create each proposed task with its own tool call, one at a time, so each can be reviewed on its own.
```

## Uruchom { #run-it }

Zanim poprosisz agenta o utworzenie czegokolwiek, otwórz **Chat controls → Approval mode** i wybierz **Ask about everything**. Ma to tu znaczenie z tego samego powodu co przy [dopisywaniu do Notion](notion-agent.md#workflow-append-meeting-notes-with-a-person-deciding): narzędzie tworzenia w trackerze jest wykrywane z połączenia MCP w trakcie runu, więc żadne zatwierdzanie per narzędzie zadeklarowane w specu do niego nie sięga. Tryb zatwierdzania samej sesji to jedyna bramka, przez którą przechodzi wywołanie tworzenia.

```text
Turn the action items in this transcript into tasks:

Weekly ops sync - 24 September 2026
Attendees: Priya, Tom, Sana

- Priya will update the onboarding doc with the new pricing tiers by Friday.
- Tom will follow up with the vendor about the delayed shipment.
- Sana raised that the support queue is growing, but nobody was assigned to look into it.
```

Każde wywołanie tworzenia parkuje osobno: model, który w jednym kroku proponuje dwa taski, parkuje dwa osobne wiersze zatwierdzeń, a każdy jest rozstrzygany niezależnie. Przeczytaj dokładny tytuł, osobę przypisaną i termin każdego z nich, zanim wybierzesz **Approve** albo odrzucisz. Odrzucone wywołanie wraca do agenta jako odmowa, na którą może zareagować, a nie jako awaria.

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Liczba zaproponowanych tasków | Dwa, po jednym na prawdziwe zadanie |
| Task Priyi | Przypisana Priya, termin piątek |
| Task Toma | Przypisany Tom, bez wymyślonego terminu |
| Pozycja Sany | Niezaproponowana jako task; wymieniona jako otwarte pytanie bez właściciela |
| Odrzucenie jednego proponowanego taska | Tracker go nie dostaje; końcowa odpowiedź agenta mówi, który został pominięty |
| Zatwierdzenie pozostałych | Tracker dostaje dokładnie zatwierdzone taski i nic więcej |
| Ta sama transkrypcja z wyłączonym **Ask about everything** | Każdy proponowany task powstaje od razu, bez niczego do przejrzenia |
| Transkrypcja bez żadnych zadań | Mówi, że nie ma czego zamienić w task, zamiast coś wymyślać |

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Task powstaje, zanim ktokolwiek go przejrzał.** Najpierw sprawdź **Approval mode** rozmowy. `required` na capability nigdy nie sięga do narzędzia MCP, więc przegląd zależy od ustawienia sesji na **Ask about everything**, za każdym razem.
- **Agent wymyśla termin albo osobę przypisaną.** Zaostrz instrukcje, a nie połączenie. To błąd promptu, a transkrypcja powinna już była mu powiedzieć, czego nie wie.
- **Zgłoszona wątpliwość i tak staje się taskiem.** Sprawdź, czy instrukcje odróżniają „przypisane komuś” od „wspomniane”. Otwarte pytanie w przykładzie istnieje właśnie po to, żeby to wychwycić.
- **Dwa różne agenty proponują task dla tego samego zadania.** Źródłem prawdy jest tu sam tracker, a nie historia runów tej platformy. Sprawdź w trackerze, czy nie ma duplikatu, zanim uznasz, że agent się myli.

## Zapisz próbę { #record-the-trial }

Zachowaj transkrypcję, każdy proponowany task, informację, które zatwierdzono, a które odrzucono, i późniejszy stan samego trackera. Dziennik zatwierdzeń w AgenticOS zapisuje, co zaproponowano i kto zdecydował, a nie to, czy tracker później nadal tak wygląda. Człowiek nadal czyta każdą propozycję, poprawia złą osobę przypisaną przed zatwierdzeniem, a nie po nim, i decyduje, kto w ogóle może przypisać agentowi połączenie z trackerem, które pozwala tworzyć taski.

## Kolejne kroki { #next-steps }

Ten sam wzorzec „zatwierdź przed zapisem”, ale dla dokumentu zamiast trackera, opisuje strona [Przeszukuj i aktualizuj Notion z poziomu agenta](notion-agent.md). Jak sprawdzić decyzje i zadania z transkrypcji, zanim którekolwiek zamienisz w task, opisuje [Streść transkrypcję spotkania w decyzje i zadania](meeting-summary.md).
