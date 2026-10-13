---
source_sha: "bc3d361ee1d5"
title: "Zamień jeden artykuł na posty w głosie marki"
description: "Załącz krótki syntetyczny artykuł i niech agent napisze po jednym poście na kanał, każdy możliwy do prześledzenia do źródła i w limicie swojego kanału."
---

# Zamień jeden artykuł na posty w głosie marki { #turn-one-article-into-social-posts-in-your-brand-voice }

Daj agentowi jeden artykuł i skill z zasadami głosu marki oraz limitami dla kanałów, a potem niech napisze jeden post na LinkedIn, jeden na X i jedną zajawkę do newslettera. Przykład jest na tyle krótki, że każde twierdzenie w postach sprawdzisz z artykułem ręcznie. To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia. Nie mierzy, jak dobrze głos pasuje do Twojego.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu.
- Bez sandboksa, modelu embeddingów i połączenia MCP. Ten agent potrzebuje tylko [capability skills](../reference/capabilities.md#skills) i załącznika w czacie.

## Przygotuj dane wejściowe { #prepare-the-input }

Zapisz to jako skill w **Skills → New skill**. Nazwij go `brand-voice`, dodaj opis w rodzaju „Tone, banned phrases and per-channel limits for turning an article into social posts” i wklej tę treść:

```text
Plain, confident, specific. Say what happened and what it means for the
reader. Use second person when addressing the reader, and "we" when
describing what the company did. State only facts, numbers and outcomes that
appear in the source article — never round a figure or add an outcome the
article does not give.

## Banned phrases

Never use any of: "game-changer", "revolutionize", "cutting-edge", "seamless",
"unlock your potential", "at the end of the day", "in today's fast-paced
world".

## Channel limits

| Channel | Limit | Shape |
|---|---|---|
| LinkedIn | 80-150 words | Open with the concrete result, two or three short paragraphs, at most one hashtag |
| X | 280 characters or fewer, counting spaces | One idea, no thread, no hashtag needed |
| Newsletter blurb | 40-60 words | One sentence hook, one sentence of detail, end with the placeholder [link] |

Write one post per channel from the attached article. Every claim in a post
must trace to a sentence in the article. If the article does not state a
number or outcome, the post does not state one either.
```

Potem zapisz ten syntetyczny artykuł, około 400 słów, jako `article.md`. Liczby są wymyślone na potrzeby testu: fikcyjna firma, fikcyjny pilotaż, nic tu nie jest prawdziwe.

```text
Northwind Robotics cuts warehouse pick times in six-week pilot

Northwind Robotics, a fictional logistics-robotics company, ran a six-week pilot
of its updated picking robot, the Pallox-3, across three regional warehouses.
The pilot measured the time from an order arriving to an item leaving the pick
station.

Average pick time fell from 12 seconds to 9 seconds per item, a 25 percent
reduction, measured across 40,000 picks during the pilot. The Pallox-3's
battery lasts 8 hours per charge, up from 5 hours on the previous model,
which let two of the three sites run a full shift without a midday swap.

No worker injuries were recorded at any of the three pilot sites during the
six weeks, according to the internal safety log Northwind shared with pilot
staff. The robot's new obstacle sensor, added after last year's design
review, stops the unit within 4 centimeters of an unexpected object, compared
with 15 centimeters on the previous sensor.

Warehouse staff at the pilot sites were surveyed at the end of the six weeks.
68 percent said the robot's new charging dock was easier to use than the old
one; 12 percent reported no opinion; the remainder did not respond to that
question.

Based on the pilot results, Northwind plans to roll the Pallox-3 update out
to 40 additional warehouses during the fourth quarter. The rollout will
happen in four batches of ten sites, starting with the two regions that ran
the pilot. Each batch is expected to take one week to install and configure,
based on the installation time recorded during the pilot.

The Pallox-3 hardware itself did not change during the pilot; the
improvement came from a software update to the picking algorithm, which
Northwind's engineering team had been testing internally for four months
before the pilot began. The update is delivered over the air to existing
Pallox-3 units, so warehouses do not need to replace hardware to get the
faster pick times.

Northwind has not yet published pricing for warehouses outside the original
three pilot sites, and a company spokesperson said in the pilot debrief that
a decision on pricing for the Q4 rollout is still under review. The company
also declined to say whether the update would be offered to older Pallox-2
units.

This is a synthetic case study; Northwind Robotics, the Pallox-3 and every
figure above are invented for this test.
```

Fakty referencyjne do późniejszego sprawdzenia: o 25% szybciej (z 12 s do 9 s), 40 000 pobrań, bateria na 8 godzin, czujnik zatrzymujący robota w odległości 4 cm, 68% pracowników uznało nową stację ładowania za łatwiejszą w obsłudze, aktualizacja wyłącznie oprogramowania, brak urazów i wdrożenie w IV kwartale w 40 lokalizacjach w czterech partiach. Artykuł mówi też, czego jeszcze *nie* wiadomo: ceny wdrożenia i tego, czy starsze roboty Pallox-2 dostaną aktualizację.

## Zbuduj agenta { #build-the-agent }

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
2. W **Toolbox** włącz **Skills** i przypisz właśnie utworzony skill `brand-voice`.
3. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You repurpose one article into social posts.
Follow the bound brand-voice skill for tone, banned phrases and channel limits.
Write exactly one post per channel: LinkedIn, X and the newsletter blurb.
Every claim must trace to a sentence in the attached article. Do not invent a
fact, a number or an outcome the article does not state.
Label each post with its channel name.
```

## Uruchom { #run-it }

Otwórz nowy czat z agentem, załącz `article.md` i wyślij:

```text
Turn the attached article into one post per channel: LinkedIn, X and the
newsletter blurb.
```

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Długość posta na X | Najwyżej 280 znaków, ze spacjami |
| Długość posta na LinkedIn | 80–150 słów |
| Długość zajawki do newslettera | 40–60 słów |
| Zakazane frazy | Żadna z siedmiu fraz ze skilla nie pojawia się w żadnym poście |
| Każda liczba i każdy wynik | Da się je odnaleźć w zdaniu z `article.md`: 25%, z 12 s do 9 s, 40 000 pobrań, 4 cm, brak urazów, wdrożenie w IV kwartale w 40 lokalizacjach |
| To samo polecenie bez załączonego pliku | Agent prosi o artykuł, zamiast go wymyślić |

Policz znaki w poście na X ręcznie albo krótkim skryptem. Nie ufaj temu, co model sam mówi o długości.

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter. Agent wywołał `load_capability` dla `brand-voice`, a potem od razu odpowiedział wszystkimi trzema postami. Post na X miał 185 znaków. Post na LinkedIn miał 113 słów, a zajawka do newslettera 50 słów, oba w limitach. W żadnym poście nie pojawiła się zakazana fraza. Każda liczba we wszystkich trzech postach (25%, z 12 s do 9 s, 40 000 pobrań, 4 cm dla czujnika i wdrożenie w IV kwartale w 40 lokalizacjach w czterech partiach) zgadzała się z artykułem. Koszt: 0,016 USD.

    Bez załączonego pliku agent i tak wczytał skill, a potem napisał „I don't see any article attached to your message” i poprosił o artykuł, zamiast pisać posty z niczego.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Post przekracza limit.** Skill podaje limit jako regułę, a nie sugestię. Zaostrz instrukcje tak, żeby agent musiał policzyć przed odpowiedzią, albo skróć przykładowe długości w samym skillu.
- **Przemyka zakazana fraza.** Sprawdź, czy przypisana jest dokładnie ta treść skilla i czy nie przesłoniła jej starsza wersja. Skills trzyma jedną wersję na skill, a stara rozmowa mogła wczytać wcześniejszą odpowiedź przed edycją.
- **Agent wymyśla statystykę.** Poproś go o zacytowanie zdania, z którego pochodzi liczba. Liczba, której nie potrafi zacytować, jest wymyślona.
- **Agent pisze posty bez załączonego artykułu.** Jeśli nie odmawia, zaostrz instrukcje tak, żeby wymagały odmowy, gdy nie ma pliku.

## Zapisz próbę { #record-the-trial }

Zachowaj artykuł, treść skilla, trzy posty, wersję agenta i run w Activity. Zachowaj też run, w którym przekroczono limit, bo pokazuje, czy winne było sformułowanie skilla, czy arytmetyka modelu.

Człowiek nadal decyduje, czy głos naprawdę brzmi jak marka i czy post nadaje się do publikacji. Liczenie znaków i sprawdzanie zakazanych fraz jest mechaniczne, ocena głosu już nie.

## Kolejne kroki { #next-steps }

Dodaj głos drugiej marki jako osobny skill i przypisuj ten, którego potrzebuje dana rozmowa, zamiast rozbudowywać jeden skill o wariant dla każdego klienta. Jak skill jest ograniczany i udostępniany, opisuje strona [Skills](../skills.md).
