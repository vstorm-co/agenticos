---
source_sha: "921578018ea4"
title: "Odpowiadaj nowym pracownikom za pomocą plików kontekstu i skilli"
description: "Przypisz jednemu agentowi krótki plik kontekstu ze stałymi faktami i skill z procedurą, a potem sprawdź, które z nich odpowiada na jaki rodzaj pytania."
---

# Odpowiadaj nowym pracownikom za pomocą plików kontekstu i skilli { #answer-new-hire-questions-with-context-files-and-skills }

Zbuduj helpdesk dla nowych pracowników, który zawsze zna kilka małych, stałych faktów i sięga po spisaną procedurę tylko wtedy, gdy pytanie naprawdę jej wymaga. Stoją za tym dwie capabilities: [pliki kontekstu](../context.md) i [skille](../skills.md). Ta strona istnieje, bo wybór niewłaściwej z nich to zwykły powód, dla którego agent ignoruje to, co mu powiedziano, albo nigdy nie otwiera tego, czego potrzebował. To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia.

## Co do czego pasuje { #which-one-fits }

| | Zawiera | Model to widzi |
| --- | --- | --- |
| **Plik kontekstu** | Stałe fakty, małe i niezmienne: termin wypłaty, kanał IT | Zawsze (`inject`) albo na żądanie (`link`) |
| **Skill** | Procedurę dla jednego rodzaju zadania: jak poprosić o dostęp | Tylko gdy model uzna, że to właśnie to zadanie |
| **Kolekcja wiedzy** | Zbiór zbyt duży, żeby przeczytać go w całości: cały podręcznik, każdy PDF z polityką | Tylko fragmenty zwrócone przez wyszukiwanie |

Poniższy przewodnik onboardingowy jest krótki i zawsze istotny, więc jest plikiem kontekstu. „Jak dostać dostęp do systemu” to procedura z krokami i wyjątkiem, więc jest skillem. Jeśli Twoje materiały onboardingowe to pięćdziesięciostronicowy podręcznik, przypisz go jako [kolekcję wiedzy](set-up-knowledge-base.md), a wzorzec z tej strony zostaw tylko dla krótkich, stałych faktów. To samo rozróżnienie od strony skilli opisuje [skille czy wiedza?](../skills.md#skills-or-knowledge).

## Czego potrzebujesz { #what-you-need }

[Działająca instalacja](../install.md) z profilem modelu. Bez sandboksa i bez modelu embeddingów: oba pliki są tu na tyle małe, że da się je wstrzyknąć albo wczytać w całości.

## Przygotuj dane wejściowe { #prepare-the-input }

Plik kontekstu ze stałymi faktami:

```markdown
# Acme Robotics — new-hire quick facts

- Payroll runs on the last business day of the month.
- The standard laptop is a MacBook Pro; loaner laptops are requested from IT, not HR.
- The internal help channel for IT questions is #it-help.
- Health insurance enrollment is open during your first 30 days; after that, only
  during the November open-enrollment window.
```

Skill z procedurą, o którą nowi pracownicy pytają najczęściej:

```markdown
# Requesting access

Most access requests go through the #it-help channel, not a person directly.

1. Post in #it-help naming the system and the reason you need it.
2. IT grants standard tools (chat, email, laptop) within one business day.
3. Anything touching customer data (the CRM, production databases) needs your
   manager's written approval first - tag them in the same thread.
4. Access to the payroll system is never granted through chat; email
   payroll@acme-example.com instead.
```

Acme Robotics jest wymyślona. Fakty referencyjne: wypłata w ostatni dzień roboczy, domyślnie MacBook Pro, a dostęp do CRM najpierw wymaga zgody przełożonego.

## Zbuduj agenta { #build-the-agent }

1. W **Context → New** utwórz plik o nazwie `onboarding-guide`, wklej powyższe fakty, ustaw **Mode** na `inject` i dodaj opis, który człowiek później rozpozna.
2. W **Skills → New** utwórz `request-access` z powyższą procedurą i opisem napisanym dla modelu: *"When somebody asks how to get access to a tool, a repository, a system, or is not sure who grants it."* Podłączony skill jest wybierany wyłącznie na podstawie nazwy i tej jednej linii.
3. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
4. W **Toolbox** włącz **Context** i przypisz `onboarding-guide`. Włącz **Skills** i przypisz `request-access`.
5. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You are Acme Robotics' new-hire helpdesk assistant.
Answer from the standing facts you were given, and use a bound skill's
procedure when a question is about how to do something.
If you are not sure, say so rather than guessing.
```

## Uruchom { #run-it }

Najpierw zapytaj o stały fakt, potem o procedurę:

```text
When does payroll run, and what laptop will I get?
```

```text
How do I get access to the CRM?
```

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Pytanie o wypłatę i laptopa | Odpowiedź od razu, bez wywołania narzędzia, bo plik kontekstu jest już w prompcie |
| Pytanie o dostęp do CRM | Wywołuje `load_capability` dla `request-access` przed odpowiedzią |
| Odpowiedź o CRM | Jako pierwszy krok podaje pisemną zgodę przełożonego, a nie tylko „post in #it-help” |
| Pytanie, którego plik kontekstu nie obejmuje (np. „what's the dress code?”) | Mówi, że nie wie, zamiast wymyślać zasadę |
| Późniejsza edycja pliku kontekstu | Kolejny run uwzględnia zmianę, bez ponownej publikacji agenta |

Najważniejsze są pierwsze dwa wiersze: jedna odpowiedź pochodzi z tekstu, który jest w każdym prompcie, druga z wywołania narzędzia, na które zdecydował się model. Jeśli któraś wydarzy się odwrotnie, użyto niewłaściwej capability.

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter. Pytanie o wypłatę i laptopa zużyło 914 tokenów wejściowych **bez wywołania narzędzia** i dostało odpowiedź: *"Payroll runs on the last business day of the month... The standard laptop is a MacBook Pro"*. Koszt: 0,004 USD.

    Pytanie o CRM wywołało `load_capability` z `{"id": "request-access"}`, dostało pełną treść skilla i odpowiedź: *"Since the CRM touches customer data, there's a specific process... Get your manager's written approval first... Post in #it-help. Tag your manager in the same thread"*. Koszt: 0,009 USD.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **W odpowiedzi brakuje stałego faktu.** Sprawdź **Mode** pliku kontekstu. Plik w trybie `link` w ogóle nie trafia do promptu, dopóki model nie zdecyduje się go przeczytać. Dla faktów, których nie wolno pominąć, użyj `inject`.
- **Skill nigdy się nie wczytuje.** Model wybiera go wyłącznie po nazwie i opisie. Opis, który brzmi jak tytuł („Access requests”), mówi mu mniej niż opis napisany jako *kiedy po to sięgnąć*.
- **Agent recytuje skill przy każdym pytaniu.** Opis skilla jest zbyt szeroki albo instrukcje nie odróżniają „stałego faktu” od „procedury” na tyle wyraźnie, żeby model wiedział, czym jest dane pytanie.
- **Edytowany plik kontekstu nie zmienia odpowiedzi.** Upewnij się, że edytujesz plik organizacji, a nie kopię. Pliki kontekstu są przypisywane po id i nie ma osobnej wersji dla każdego agenta.
- **Zamiast odpowiedzi pojawia się propozycja zmiany skilla.** Agent może próbować *ulepszyć* skill w trakcie rozmowy. To propozycja, którą zatwierdza albo odrzuca osoba z `skills:edit`, a nie coś, co run wprowadza sam. Zobacz [skille](../skills.md#an-agent-can-propose-a-change-a-person-makes-it).

## Zapisz próbę { #record-the-trial }

Zachowaj treść i id obu plików, wersję agenta, oba pytania i odpowiedzi oraz informację, czy każda z nich użyła wywołania narzędzia. Człowiek nadal pisze i edytuje stałe fakty i procedurę. Ten wzorzec decyduje tylko o tym, gdzie mieszka każdy tekst, a nie o tym, kto ma rację co do terminu wypłaty.

## Kolejne kroki { #next-steps }

Tego samego agenta można przypisać do bota Slacka dla kanału zespołu zamiast konsoli. Zobacz [Odpowiedz na pytanie z handbooka w Slacku](slack-handbook-assistant.md), gdzie opisano przypisanie, łączenie kont i sprawdzanie, do kogo należy który run. Jeśli materiały onboardingowe urosną ponad stronę czy dwie, przenieś je do [kolekcji wiedzy](set-up-knowledge-base.md), zamiast rozciągać wstrzykiwany plik kontekstu.
