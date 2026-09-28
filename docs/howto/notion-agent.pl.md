---
source_sha: "d73b776f3671"
title: "Przeszukuj i aktualizuj Notion z poziomu agenta"
description: "Podłącz Notion jako serwer MCP, pozwól agentowi odpowiadać na podstawie strony, którą sam znajdzie, i wymagaj przeglądu przez człowieka, zanim cokolwiek dopisze."
---

# Przeszukuj i aktualizuj Notion z poziomu agenta { #search-and-update-notion-from-an-agent }

Podłącz Notion przez [MCP](../mcp.md), żeby agent mógł przeszukiwać workspace, odpowiadać na podstawie tego, co znajdzie, i dopisywać notatki ze spotkań do strony, a człowiek za każdym razem decydował, czy zapis faktycznie nastąpi. Ta strona opisuje oba przepływy i dokładne wybory przy połączeniu, od których zależą. Nie da się jej tu uruchomić: to środowisko nie ma konta Notion do podłączenia, więc poniżej nie ma zapisanego runu.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu.
- **`connections:manage`**, żeby dodać Notion dla całej organizacji, albo nic poza zwykłym kontem członka, żeby podłączyć go tylko dla siebie w **MCP servers → You**.
- Workspace Notion, w którym możesz autoryzować aplikację OAuth.

## Podłącz Notion { #connect-notion }

Notion jest w katalogu z uwierzytelnianiem **oauth** pod `https://mcp.notion.com/mcp` (zobacz [katalog](../mcp.md#communication-support-knowledge)). Zanim agent w ogóle go dotknie, liczą się dwie decyzje:

**Organizacja czy konto osobiste.** Dodanie go w **MCP servers → Organization** (`connections:manage`) sprawia, że jedno połączenie z Notion odpowiada za każdego przypisanego agenta, na każdej powierzchni, pod jedną wspólną nazwą i tożsamością w dzienniku audytu samego Notion. Dodanie go zamiast tego w **MCP servers → You** oznacza, że każda osoba podłącza własny dostęp do workspace'u, a przypisanie do *własnego konta każdej osoby* (`account: personal` w specu) sprawia, że agent rozmawia z Notion jako osoba, która pyta. Dziennik Notion mówi wtedy, kto co zrobił, ale współpracownik, który nie podłączył własnego Notion, dostaje komunikat, żeby to zrobić, a nie odpowiedź z cudzego workspace'u. Zobacz [przez czyje konto mówi przypisanie](../mcp.md#whose-account-a-binding-speaks-through).

**Nazwa i prefiks narzędzi.** Podłączenie drugiego workspace'u Notion wymusza drugą nazwę: prefiks `notion` jest zajęty, więc drugi staje się `notion-2`, a model czyta ten prefiks, który wskazuje jego przypisanie. Zobacz [dwie nazwy, a każda odpowiada na inne pytanie](../mcp.md#two-names-and-they-answer-different-questions).

Dla małego zespołu korzystającego z jednego wspólnego workspace'u prostszym początkiem jest konto organizacji. Przełącz się na własne konto każdej osoby, gdy różni ludzie mają widzieć tylko to, co widzi ich własny login do Notion.

## Zbuduj agenta { #build-the-agent }

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
2. W **Toolbox** dodaj serwer Notion w **MCP servers**, przypisany do konta organizacji (albo własnego konta każdej osoby). Na początek zostaw jego narzędzia bez ograniczeń albo zawęź `allowed_tools` w przypisaniu do samego narzędzia wyszukiwania i odczytu, jeśli ten agent nigdy nie powinien pisać.
3. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You answer questions from this organization's Notion workspace.
Search before you answer, and open the page you found before quoting it.
Cite the page's title in your answer, and say plainly if nothing in Notion answers the question.
When asked to add meeting notes to a page, find the exact page first, show the person what you are about to append, and only write it once they confirm.
```

Model sięga do narzędzi Notion pod prefiksem połączenia: `notion_search` i wszystko inne, co znalazło ostatnie sprawdzenie, z takim samym prefiksem. To, jakie narzędzia w ogóle istnieją, rozstrzyga się przy sprawdzaniu połączenia, a nie przez ręczne wpisanie do specu. Zobacz [które narzędzia i kto decyduje](../mcp.md#which-tools-and-who-decides).

## Przepływ: znajdź stronę i odpowiedz na jej podstawie { #workflow-find-a-page-and-answer-from-it }

Zadaj w nowej rozmowie pytanie, na które workspace powinien znać odpowiedź:

```text
Who owns the Q3 onboarding checklist, and where does it live?
```

Model wywołuje narzędzie wyszukiwania, otwiera stronę, która wygląda na właściwą, i odpowiada, podając tytuł strony jako źródło. Jeśli nic nie pasuje, powyższe instrukcje każą mu to powiedzieć, zamiast zgadywać. Sprawdź tę odmowę tak samo, jak sprawdzałbyś poprawną odpowiedź w próbie agenta z wyszukiwaniem w wiedzy.

## Przepływ: dopisz notatki ze spotkania, a decyduje człowiek { #workflow-append-meeting-notes-with-a-person-deciding }

Przy tym przepływie warto być precyzyjnym, bo **narzędzia MCP nie mają własnego zatwierdzania per narzędzie**. Builder mówi to wprost: *„MCP tools are outside the approval gate entirely: an approval set on a capability does not cover them, so anything these servers can do, this agent can do without asking.”* Narzędzie zapisu, które można nazwać w specu, jak `execute` albo `send_email`, ma przełącznik `required`/`never`/`default`. Narzędzie zapisu w Notion wykryte przy łączeniu nigdy go nie dostaje, bo nic nie zadeklarowało go w kodzie. Zobacz [czego MCP nie daje](../mcp.md#what-mcp-does-not-get-you).

Bramka, która do niego sięga, należy do samej rozmowy. Zanim poprosi agenta o zapis, osoba, która z nim rozmawia, otwiera **Chat controls → Approval mode** i wybiera **Ask about everything**. To ustawienie sesji, które „reaches further than the spec's gate on purpose, to the tools no capability owns” (zobacz [jak często dana rozmowa chce być pytana](../governance.md#how-much-one-conversation-wants-to-be-asked)). Z takim ustawieniem:

```text
Append these notes to the Q3 onboarding checklist page: attendees Ana and Marek, decided to move the kickoff to Monday, action item for Marek to update the calendar invite.
```

Narzędzie zapisu parkuje teraz tak samo jak `execute` w [próbie z wykresem z CSV](csv-chart.md#run-it): czat pokazuje **Tool approval required** z dokładną stroną i treścią, którą model zamierza wysłać, a człowiek czyta ją przed wybraniem **Approve**. Pomiń **Ask about everything**, a ten sam zapis wykona się od razu, bez niczego do przejrzenia. Agent przypisany do połączenia z Notion, które pozwala pisać, jest więc przeglądany dokładnie tak, jak wybrała w danej turze osoba, która z nim rozmawia.

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Pytanie, na które odpowiada Notion | Podaje tytuł strony jako źródło, a odpowiedź zgadza się z treścią strony |
| Pytanie, na które nic w workspace'ie nie odpowiada | Mówi o tym, zamiast wymyślać wiarygodnie brzmiącą stronę |
| Dopisanie z wyłączonym **Ask about everything** | Wykonuje się od razu; upewnij się, że tego chcesz, zanim do tego dojdzie |
| Dopisanie z włączonym **Ask about everything** | Parkuje jako **Tool approval required** z dokładną stroną i tekstem |
| Odrzucenie zaparkowanego zapisu | Strona się nie zmienia, a agent może przekazać odmowę, zamiast się wywrócić |
| Ktoś bez osobistego połączenia z Notion, przy przypisaniu do konta osobistego | Dostaje prośbę o podłączenie konta, a nie odpowiedź z cudzego workspace'u |

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Agent w ogóle nie ma narzędzi Notion.** Połączenie nigdy nie zostało poprawnie sprawdzone. Otwórz **MCP servers**, uruchom sprawdzenie i upewnij się, że pokazuje listę narzędzi, zanim przypiszesz je do agenta.
- **Zapis wykonuje się bez niczyjego przeglądu.** Sprawdź **Approval mode** samej rozmowy. `required` na capability nie sięga do narzędzia MCP, więc połączenie z prawem zapisu wymaga ustawienia sesji na **Ask about everything** za każdym razem, gdy przegląd ma znaczenie.
- **Dwa połączenia z Notion kolidują pod jedną nazwą.** Zmień nazwę jednego. Co robi run, gdy nie potrafi ich odróżnić, opisują [kolizje nazw](../mcp.md#name-collisions).
- **Współpracownik dostaje „connect your account” zamiast odpowiedzi.** Tak ma być przy przypisaniu do konta osobistego, dopóki nie podłączy własnego Notion w **MCP servers → You**.

## Zapisz próbę { #record-the-trial }

Zachowaj pytanie i jego źródło, zakres połączenia (organizacja czy konto osobiste) i to, na który workspace Notion wskazuje, oraz każdy zatwierdzony albo odrzucony zapis ze stroną, której dotyczył. Człowiek nadal decyduje, kto może przypisać agentowi połączenie z Notion z prawem zapisu, i przegląda każde dopisanie, którego ten tryb sam nie zaparkował do przeglądu.

## Kolejne kroki { #next-steps }

To samo pytanie o przegląd, ale dla trackera projektów zamiast dokumentu, opisuje strona [Zamień zadania ze spotkania na taski z zatwierdzeniem](meeting-to-tasks.md). Jak zawęzić to, co może połączenie z Notion całej organizacji, zanim przypisze je jakikolwiek agent, opisuje [które narzędzia i kto decyduje](../mcp.md#which-tools-and-who-decides).
