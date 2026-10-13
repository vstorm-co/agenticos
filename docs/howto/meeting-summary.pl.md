---
source_sha: "1d2ade73a284"
title: "Streść transkrypcję spotkania w decyzje i zadania"
description: "Wklej krótką syntetyczną transkrypcję i sprawdź, czy agent oddziela decyzje od zadań, podaje właściciela i termin każdego z nich i oznacza jedno zadanie, którego nikt nie wziął."
---

# Streść transkrypcję spotkania w decyzje i zadania { #summarise-a-meeting-transcript-into-decisions-and-action-items }

Zbuduj agenta, który zamienia wklejoną transkrypcję w trzy krótkie listy: decyzje, zadania z właścicielem i terminem oraz otwarte pytania. W przykładowej transkrypcji jest jedno zadanie, które pada w rozmowie, ale nikt faktycznie nie zgadza się go wziąć. Najważniejsze sprawdzenie to to, czy agent uczciwie to zgłosi, zamiast przypisać zadanie osobie wspomnianej obok. To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu.
- Żadnej capability. Ten agent czyta to, co jest w wiadomości, i nic więcej.

## Przygotuj dane wejściowe { #prepare-the-input }

Krótka, syntetyczna transkrypcja, wymyślona na potrzeby tej strony:

```text
Onboarding revamp sync — 12 March, 10:00–10:35
Jenna: Let's get through this quickly. Marcus, where are we with the signup
API changes?
Marcus: Mostly done. I can have the new field validation live by March 20.
Jenna: Good. Priya, the tooltip designs?
Priya: Almost there. I can deliver the final set by March 18, in time for
Marcus to wire them up.
Jenna: Great. Let's also decide on the survey step. Tomas, you said support
tickets show people dropping off there.
Tomas: Right, about a third of drop-offs happen on the survey screen. My
recommendation is to remove it entirely rather than shorten it.
Jenna: Agreed, let's remove the survey step from onboarding. Marcus, can you
fold that into the same API change?
Marcus: Yes, same PR.
Jenna: Decision made — the survey step is gone. Now, should the new tooltip
flow go to everyone at once, or beta first?
Priya: Beta first. We haven't tested it on mobile yet.
Marcus: Agreed, mobile rendering is still rough.
Jenna: Okay, decision: new tooltip flow ships to beta users first, general
release after that's clean.
Tomas: One more thing — the help center article on "how onboarding works"
is now out of date once the survey step is gone. Somebody should update it
before we ship.
Jenna: Good catch. Let's make sure that happens.
Priya: I can't take that on, I'm full up with the tooltip work through the
20th.
Marcus: Not mine either, that's not engineering's article.
Jenna: Okay, let's flag it and figure out who owns docs later this week.
Tomas: Compiling the onboarding-related support tickets into a report —
I'll do that, but I don't have a firm date yet, depends on how much backlog
I need to dig through.
Jenna: That's fine, just get it to us when it's ready.
Jenna: Last open question — do we sunset the old onboarding flow entirely,
or keep it behind a flag as a fallback for a few weeks?
Marcus: I'd lean toward keeping the flag, in case the new flow breaks
something we didn't catch in beta.
Priya: I don't have a strong opinion either way.
Jenna: Let's leave that open and revisit once beta feedback comes in.
Jenna: Okay, I think that's everything. Thanks all.
```

Kryterium: dwie decyzje (usunąć krok z ankietą; najpierw wypuścić przepływ z podpowiedziami do bety), cztery zadania z właścicielem, jedno zadanie, czyli aktualizacja artykułu w centrum pomocy, od którego Priya i Marcus wprost się odżegnują, i jedno otwarte pytanie zostawione na później.

## Zbuduj agenta { #build-the-agent }

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
2. Zostaw Toolbox pusty. Nic tu nie wymaga narzędzia.
3. Ustaw budżet i limit kroków na czas próby.
4. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You turn a pasted meeting transcript into three sections: Decisions,
Action items, and Open questions.

For each action item, name the owner and the due date exactly as stated. If
a task is mentioned but nobody agreed to own it, list it under Action items
as unassigned and say so - never guess an owner, and never assign it to
someone who explicitly declined it in the transcript.

List a topic under Open questions only if the transcript does not record a
decision on it. Do not invent a decision, an owner, or a date the transcript
does not state.
```

## Uruchom { #run-it }

Wklej transkrypcję prosto do nowej rozmowy, po krótkim poleceniu:

```text
Summarise this meeting transcript into decisions, action items and open questions.

[paste the transcript]
```

Załączenie jej jako pliku tekstowego działa tak samo: agent bez workspace'u dostaje tekst załącznika wklejony do promptu, tak jak przy wklejeniu. Zobacz [przetwarzanie plików](../file-processing.md#chat-file-uploads).

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Decyzje | Usunąć krok z ankietą; najpierw wypuścić przepływ z podpowiedziami do bety |
| Zadania Marcusa | Walidacja pól i usunięcie kroku z ankietą, termin 20 marca |
| Zadanie Priyi | Ostateczne projekty podpowiedzi, termin 18 marca |
| Zadanie Tomasa | Zestawienie raportu ze zgłoszeń do wsparcia, bez wymyślonej daty |
| Artykuł w centrum pomocy | Wymieniony jako nieprzypisany, a nie oddany Priyi ani Marcusowi |
| Otwarte pytania | Tylko pytanie o wygaszenie czy fallback, a nie decyzja powtórzona jako pytanie |

Najpierw sprawdź nieprzypisane zadanie. Agent, który po cichu oddaje je osobie, której imię pada najbliżej w transkrypcji, oblał jedyny test, dla którego istnieje ta strona, nawet jeśli każda inna linia jest dobra.

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter. Bez wywołań narzędzi: cała odpowiedź powstała w jednym żądaniu do modelu, za 0,0063 USD. Wymienił obie decyzje, dał Marcusowi dwie pozycje (walidacja pól i usunięcie kroku z ankietą, obie na 20 marca), Priyi projekty podpowiedzi na 18 marca, a Tomasowi raport z opisem „no firm date — to be delivered when ready”. Artykuł w centrum pomocy został wymieniony jako **„Unassigned (Priya and Marcus both declined; owner to be determined later this week)”**, a nie przypisany któremukolwiek z nich. Jedynym otwartym pytaniem była decyzja o wygaszeniu albo fallbacku, oznaczona jako odłożona.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Niewzięte zadanie i tak zostaje przypisane.** To jest błąd, którego trzeba pilnować. Zaostrz dalej instrukcje. Podanie dokładnego słowa „declined” albo „unassigned” czasem pomaga mniej niż dodanie drugiej transkrypcji, w której ten sam wzorzec się powtarza, żeby sprawdzić, czy pierwszy wynik nie był przypadkiem.
- **Pojawia się termin, którego nikt nie podał.** Model uzupełnił lukę, bo zadanie bez daty wygląda na niekompletne. Sprawdź, czy ostatnia linia instrukcji działa, i przetestuj transkrypcję z więcej niż jednym zadaniem bez daty.
- **Otwarte pytanie powtarza coś, co już postanowiono.** Model uznał decyzję podjętą pod presją, pod koniec spotkania, za wciąż otwartą. Wskaż mu dokładną linię, w której zapadła decyzja.
- **Trzy sekcje zlewają się ze sobą.** Przy dłuższej, bardziej chaotycznej transkrypcji poproś o sekcje w stałej kolejności i sprawdź, czy każda zawiera tylko to, co do niej należy.

## Zapisz próbę { #record-the-trial }

Zachowaj transkrypcję, dokładny prompt, wersję agenta, model i odpowiedź. Człowiek nadal sprawdza nieprzypisane zadanie bezpośrednio w transkrypcji. To dokładnie taki mały, łatwy do przeoczenia szczegół, który umyka przy szybkim czytaniu długiego podsumowania.

## Kolejne kroki { #next-steps }

Zamiana każdego zadania w faktycznie śledzony task z powiadomieniem właściciela to osobny krok opisany na stronie [Zamień zadania ze spotkania na taski z zatwierdzeniem](meeting-to-tasks.md). Ta strona kończy się na podsumowaniu, które człowiek czyta i sprawdza.
