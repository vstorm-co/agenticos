---
source_sha: 5d457ec305b9
---

# Wybór modelu { #choosing-a-model }

[Modele](models.md) opisują mechanikę — czym jest profil, kiedy odpala się
fallback, jak wyceniany jest run. Ta strona odpowiada na pytanie, które ludzie
zadają jako pierwsze: **jakiego modelu ma używać ten agent?**

Krótka odpowiedź brzmi: to nie jest jedna decyzja. To jedna decyzja *na agenta*,
a zmiana zdania później jest wpisana w projekt — po to właśnie jest
[profil modelu](models.md#a-model-profile).

## Trzy pytania, które o tym decydują { #three-questions-decide-it }

Zadaj je w tej kolejności. Wygrywa pierwsze, które daje twardą odpowiedź.

| | Pytanie | Jeśli odpowiedź brzmi… |
|---|---|---|
| 1 | **Dokąd mogą trafić te dane?** | „Donikąd” — wybierasz spośród modeli, które możesz uruchomić sam. Zatrzymaj się tutaj; nic poniżej tego nie unieważnia |
| 2 | **Jak trudne jest myślenie?** | Rutynowa ekstrakcja i przepisywanie to inny budżet niż wieloetapowe rozumowanie nad nieuporządkowanym korpusem |
| 3 | **Jak często to będzie działać?** | Sto rozmów miesięcznie i sto tysięcy to dwa różne produkty, nawet przy tych samych instrukcjach |

Większość agentów w firmie to pytanie 3 z łatwą odpowiedzią na pytanie 2 —
odpowiedź supportu, streszczenie dokumentu, formularz wypełniony na podstawie
maila. Takie zadania nie potrzebują czołowego modelu, a płacenie za niego to
najczęstszy sposób, w jaki znika budżet agenta.

## Co wybrać, zależnie od tego, co robi agent { #what-to-pick-by-what-the-agent-does }

| Agent… | Sięgnij po | Dlaczego |
|---|---|---|
| Odpowiada na podstawie twoich dokumentów i cytuje je | Model ze **średniej półki** z dużym oknem kontekstu | Trudną część robi retrieval. Zadaniem modelu jest przeczytać to, co dostał, i nie koloryzować |
| Klasyfikuje, wyciąga dane, routuje, przepisuje | **Najtańszy** model, który przechodzi twój własny test | Zadanie ma poprawną odpowiedź, więc jakość jest mierzalna, a dolna granica leży niżej, niż się wydaje |
| Planuje przez wiele kroków i narzędzi | Model **czołowy** | To właśnie na decyzji, *które* narzędzie wywołać jako następne, tanie modele się wykładają — i wykładają się, wpadając w pętlę |
| Pisze coś, co czyta klient | Model **czołowy albo mocny ze średniej półki** | Różnicę widać po tonie i po tym, jak model odmawia, a jedno i drugie widzi osoba, którą najmniej chcesz zirytować |
| Przetwarza dane, które nie mogą opuścić firmy | Model o **otwartych wagach**, hostowany przez ciebie | Zobacz niżej — to jest pytanie 1 i nie jest to kompromis jakościowy, z którym można dyskutować |

!!! tip "Zacznij o półkę wyżej, potem zejdź"

    Zbuduj agenta na mocnym modelu, aż zacznie zachowywać się tak, jak chcesz,
    potem przestaw profil na tańszy i sprawdź, czy ktokolwiek to zauważy.
    Odwrotna kolejność oznacza debugowanie instrukcji i modelu naraz — i obwinisz
    to, co nie zawiniło.

## Modele zamknięte czy otwarte wagi { #closed-models-or-open-weights }

Jedno i drugie jest tu traktowane równorzędnie. Wśród 27 providerów są zamknięte
laboratoria z czołówki, hostingi modeli o otwartych wagach oraz dwie pozycje bez
klucza — [Ollama](models.md) i proxy LiteLLM — dla modeli działających na
sprzęcie, który należy do ciebie.

| | Modele zamknięte (API) | Otwarte wagi (hostowane) | Otwarte wagi (twój sprzęt) |
|---|---|---|---|
| Przykłady z listy wyboru | Anthropic, OpenAI, Google, xAI | Groq, Together, Fireworks, Nebius, DeepSeek | Ollama, proxy LiteLLM |
| Najwyższa dostępna jakość | Tak, na czele stawki | Blisko i coraz bliżej | Ograniczona twoim GPU |
| Dane opuszczają twoją sieć | Tak, do tego dostawcy | Tak, do tego hostingu | **Nie** |
| Kształt kosztu | Za token, bez dolnego progu | Za token, zwykle taniej | Stały — sprzęt już kupiłeś |
| Kto naprawia regresję | Dostawca, w swoim terminie | Hosting | Ty, i tylko wtedy, gdy sam się przeniesiesz |
| Dobry powód, by to wybrać | Praca jest naprawdę trudna | Duży wolumen, zwyczajna praca | Wymogi co do miejsca przechowywania danych albo wolumen, przy którym sprzęt to drobiazg |

Uczciwe podsumowanie: **modele zamknięte wciąż prowadzą w najtrudniejszym
rozumowaniu, a ta różnica nie ma znaczenia dla większości tego, co firma
automatyzuje.** Agent, który czyta dokument z polityką firmy i odpowiada na
pytanie o niego, nie jest zadaniem dla czołowego modelu, a uruchomienie go na
otwartych wagach u siebie bywa lepszą decyzją inżynierską, nie tylko tańszą.

!!! warning "Hostowanie modelu u siebie to realne zobowiązanie"

    Bezczynne GPU i tak kosztuje, ktoś musi łatać runtime, a model hostowany
    u ciebie nie ma dostawcy, do którego można eskalować. Wybierz to, gdy wymaga
    tego miejsce przechowywania danych albo gdy twój wolumen naprawdę przerasta
    sprzęt — a nie po to, by zaoszczędzić na czterdziestu rozmowach dziennie.

## Postawienie gatewaya z przodu { #putting-a-gateway-in-front }

Trzy z tych 27 to nie dostawcy modeli, tylko routery: **OpenRouter**, **Vercel AI
Gateway** i **proxy LiteLLM**, które uruchamiasz sam. Każdy daje jeden klucz
i jeden endpoint przed wieloma modelami.

Warto, gdy chcesz centralnie kontrolować wydatki także w zespołach poza
AgenticOS, albo gdy wciąż się zastanawiasz i chcesz sprawdzić kilka modeli bez
osobnego procesu zakupowego na każdego dostawcę. Kosztuje cię to jeden dodatkowy
przeskok, drugie miejsce, w którym żądanie może się nie powieść, i — przy
routerze hostowanym — drugą firmę widzącą ruch.

## Co naprawdę napędza rachunek { #what-actually-drives-the-bill }

Nie nazwa modelu. **Kontekst.**

O koszcie runa decyduje przede wszystkim to, ile tokenów wchodzi *do środka*,
a wchodzą twoje instrukcje, wyszukane dokumenty, dotychczasowa rozmowa i każdy
wynik narzędzia. Agent z systemowym promptem na 4000 słów i ośmioma wyszukanymi
fragmentami na turę jest drogi na każdym modelu.

Zanim więc zmienisz model, sprawdź trzy rzeczy:

- **`default_top_k` w capability wiedzy.** Osiem fragmentów tam, gdzie
  wystarczyłyby trzy, to najczęstsze ciche przepalanie budżetu.
- **Instrukcje, które się powtarzają.** Są czytane w każdej turze.
- **[Zarządzanie kontekstem](reference/capabilities.md)**, które utrzymuje długą
  rozmowę wewnątrz okna, zamiast wysyłać ją w całości od nowa.

[Budżety](governance.md#budgets) są zabezpieczeniem, a nie planem: budżet
zatrzymuje run przed żądaniem do modelu, więc źle dobrany model objawia się jako
agent, który przestał odpowiadać, a nie jako faktura na koniec miesiąca.

## Zmiana zdania później { #changing-your-mind-later }

Profil modelu wskazuje model; agenci wskazują profil. **Zmień profil, a przesuną
się wszyscy agenci, którzy go używają — i żaden z nich nie musi zostać
opublikowany na nowo.**

Po to właśnie istnieje ta warstwa pośrednia i to dzięki niej rady z tej strony
można bezpiecznie stosować: wybierz teraz coś sensownego, zmierz, czego naprawdę
wymaga twoja praca, i przesiądź się.

Fallbacki mieszkają w tym samym profilu. Ustaw drugiego providera za pierwszym,
a awaria zmieni się w wolniejszą odpowiedź zamiast w incydent — warto to zrobić
przy każdym agencie, do którego może dotrzeć klient.

## Embeddingi to osobny i trwały wybór { #embeddings-are-a-separate-permanent-choice }

Retrieval korzysta z modelu embeddingów, a ten jest **ustalany przy tworzeniu
kolekcji**. Dwa modele o tej samej szerokości zapisują do różnych przestrzeni
wektorowych, a wyszukiwanie dalej porównywałoby je tak, jakby były tą samą — więc
zmiana oznacza policzenie embeddingów całej kolekcji od nowa.

Wybierz go raz, osobno dla każdej kolekcji, i zanim to zrobisz, zajrzyj do
[Przetwarzania plików](file-processing.md).

## Podsumowanie { #recap }

- Wybór jest **na agenta**, a nie na firmę, a profil modelu istnieje po to, żebyś
  mógł go później zmienić bez publikowania czegokolwiek od nowa.
- **To, dokąd mogą trafić dane**, jest ważniejsze niż każda inna przesłanka.
- Większość agentów w firmie **nie** potrzebuje czołowego modelu; zbuduj na
  takim, potem zejdź niżej i sprawdź, czy ktoś to zauważy.
- **Rachunek napędza kontekst**, a nie nazwa modelu — sprawdź `default_top_k`
  i swoje instrukcje, zanim zmienisz providerów.
- **Model embeddingów jest w kolekcji ustalany na stałe.** Ten wybierz uważnie.

[Mechanika: profile, providerzy, fallbacki i koszt →](models.md)
