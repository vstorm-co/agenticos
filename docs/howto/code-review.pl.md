---
source_sha: "7588e57ff61c"
title: "Przejrzyj zmianę w repozytorium"
description: "Niech agent zbuduje w sandboksie małe repozytorium git, przejrzy jeden diff według wbudowanego skilla code-review i znajdzie oba podłożone błędy we właściwych liniach."
---

# Przejrzyj zmianę w repozytorium { #review-a-change-in-a-repository }

Daj agentowi [sandbox](../sandbox.md) i wbudowany skill `code-review`, a potem niech założy małe repozytorium git i przejrzy diff jednego commita. Diff zawiera dwa podłożone błędy, off-by-one i nieobsłużone `None`, w miejscach file:line, które możesz sprawdzić ręcznie. To instrukcja wykonania z jednym zapisanym runem jako punktem odniesienia.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu i zarejestrowanym [połączeniem sandboksa](../sandbox.md), którego domyślnym runtime'em jest `workbench`, bo ma `git`.
- Skill `code-review`, który dostaje każda organizacja. Zobacz [Skills](../skills.md#getting-skills-into-an-organization).
- Nic więcej do dołączenia: repozytorium tworzy sam agent w sandboksie, z dokładnej treści plików z promptu poniżej.

## Przygotuj dane wejściowe { #prepare-the-input }

Tu nie ma pliku do załączenia. „Repozytorium” to dwa małe pliki Pythona, które agent pisze sam na Twoje polecenie, więc dokładnie kontrolujesz zawartość diffu. Wersja 1 to prosty kalkulator koszyka:

```python
# utils.py (version 1)
def compute_total(prices):
    total = 0
    for p in prices:
        total += p
    return total


def find_discount_tier(count):
    tiers = [(10, 0.05), (20, 0.10), (50, 0.15)]
    for threshold, rate in tiers:
        if count >= threshold:
            return rate
    return 0.0
```

```python
# main.py (version 1)
from utils import compute_total, find_discount_tier


def checkout(cart):
    prices = [item["price"] for item in cart]
    total = compute_total(prices)
    rate = find_discount_tier(len(cart))
    return total * (1 - rate)
```

Wersja 2 dodaje rabat członkowski i pomocniczą funkcję `apply_discount` z dwoma podłożonymi błędami. Nowy parametr `member_rate` w `main.py` ma domyślnie `None` i jest używany bez sprawdzenia, a `apply_discount` w `utils.py` obniża cenę każdej pozycji, łącznie z najdroższą, a potem dokłada tę samą pozycję jeszcze raz, licząc ją podwójnie.

```python
# utils.py (version 2, adds apply_discount)
def apply_discount(prices, rate):
    """Discount every item except the single most expensive one."""
    sorted_prices = sorted(prices)
    n = len(sorted_prices)
    discounted = [sorted_prices[i] * (1 - rate) for i in range(n)]
    discounted.append(sorted_prices[-1])
    return discounted
```

```python
# main.py (version 2)
from utils import compute_total, find_discount_tier, apply_discount


def checkout(cart, member_rate=None):
    prices = [item["price"] for item in cart]
    tier_rate = find_discount_tier(len(cart))
    discounted_prices = apply_discount(prices, tier_rate)
    total = compute_total(discounted_prices)
    return total * (1 - member_rate)
```

Kryterium: diff między wersjami ma dokładnie dwa prawdziwe defekty. `return total * (1 - member_rate)` w `main.py` rzuca `TypeError` za każdym razem, gdy `member_rate` zostaje na wartości domyślnej, a `apply_discount` w `utils.py` zwraca o jedną pozycję za dużo, bo pętla obejmuje już ostatni indeks, zanim ta sama pozycja zostanie dołożona ponownie. Ani `compute_total`, ani `find_discount_tier` nie zmieniają się między wersjami, więc poprawny review nic o nich nie mówi.

## Zbuduj agenta { #build-the-agent }

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
2. W **Toolbox** włącz **Files & shell**. Wybierz **Container**, swoje połączenie sandboksa i runtime `workbench`, a zakres zostaw na poziomie rozmowy.
3. Włącz **Skills** i przypisz `code-review`.
4. Ustaw budżet na czas próby. Zapisany run użył około 40 kroków i kosztował około 0,18 USD, głównie przez powtarzane zatwierdzenia poleceń powłoki.
5. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You review a change in a git repository using the bound code-review skill.
Follow that skill: read the whole change before commenting, say what is wrong
and why it matters, and separate what blocks from what does not.
Only report issues that are actually in the diff. Do not report a problem in a
line the diff did not touch.
Cite every finding as file:line and give a concrete fix.
```

## Uruchom { #run-it }

Otwórz nowy czat i wklej obie wersje z powyższego opisu razem z poleceniem, żeby założyć repozytorium i przejrzeć zmianę:

```text
Set up a tiny git repository in your workspace and review one change in it.

1. Create a directory `grocery_calc`, write utils.py and main.py exactly as
   given above (version 1), then git init, configure a throwaway user, and
   commit them as the initial version.
2. Replace both files with version 2 exactly as given above, and commit that
   as a second commit.
3. Run `git diff HEAD~1 HEAD` to get the exact change, then review that diff
   using the bound code-review skill. Report every real defect the diff
   introduces, each as file:line with a concrete fix. Do not report anything
   about a line the diff did not change.
```

Każde wywołanie `execute`, które zrobi agent (`git init`, każdy commit, diff), pokazuje w czacie **Tool approval required**. Przeczytaj polecenie i przy każdym kliknij **Approve**. Run wznawia się tam, gdzie się zatrzymał. Żeby pominąć ten krok dla zaufanego agenta testowego, zmień ustawienie zatwierdzania `execute` w Builderze. Zobacz [zatwierdzenia](../governance.md#approvals).

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Znalezione nieobsłużone `None` | `main.py:9`, `return total * (1 - member_rate)` wywraca się, gdy `member_rate` zostaje na domyślnym `None` |
| Znaleziony off-by-one | `utils.py:20-21`, comprehension obejmuje już każdy indeks łącznie z ostatnim, a potem ta pozycja jest dokładana drugi raz |
| Oba wskazane jako file:line | Nie tylko „w apply_discount jest błąd” |
| Poprawka jest konkretna | Poprawiony fragment kodu, a nie sam opis problemu |
| Niezmieniony kod | Brak uwag o `compute_total` i `find_discount_tier`, których diff nie dotknął |
| Blokujące i nie | Oba błędy są oznaczone jako blokujące, a wszystko stylistyczne ma przedrostek „nit” |

Przeczytaj diff samodzielnie, zanim zaufasz review. `git diff HEAD~1 HEAD` w panelu plików workspace'u pokazuje dokładnie to, co przejrzał agent.

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter. Agent wczytał skill `code-review`, potem przez `read_skill_resource` odczytał jego `checklist.md` i `review-comment.md`, a następnie zapisał oba pliki, dwa razy zrobił commit i uruchomił diff. Były to trzy wywołania `execute`, każde zaparkowane do zatwierdzenia. Po zatwierdzeniu odpowiedział trzema uwagami blokującymi i jednym nitem.

    Wskazał `main.py:9` dla `TypeError` przy brakującym `member_rate` z dwulinijkową poprawką oraz `utils.py:20-21` dla podwójnie liczonej pozycji z poprawioną funkcją `apply_discount`, dokładnie zgodnie z oboma podłożonymi błędami. Oznaczył też diff jako nieprzetestowany, zgodnie z regułą z listy kontrolnej skilla, że zmiana zachowania wymaga testu. O `compute_total` i `find_discount_tier` nie powiedział nic. Koszt: 0,18 USD przy 40 krokach, w większości za trzy rundy zatwierdzeń.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Agent mówi, że nie ma powłoki.** Capability używa **Files** zamiast **Container**. Przełącz na Container i wybierz runtime `workbench`.
- **Run zatrzymuje się po `git init` albo commicie.** Czeka na zatwierdzenie `execute`. Otwórz czat albo zakładkę **Approvals** w **Activity**.
- **Review zgłasza coś w niezmienionym kodzie.** Zaostrz instrukcje: ma przeglądać tylko to, co pokazuje `git diff`, a nie cały plik.
- **Uwaga nie ma file:line.** Poproś agenta, żeby jeszcze raz przeczytał szablony komentarzy z listy kontrolnej, które zawsze podają miejsce.
- **Pierwsza tura jest powolna.** Buduje się obraz `workbench`. Kolejne sesje używają go ponownie. Zobacz [sandbox](../sandbox.md#when-a-build-is-paid-for).

## Zapisz próbę { #record-the-trial }

Zachowaj obie dokładne wersje, diff, review, wersję agenta i każde zatwierdzone polecenie w Activity. Człowiek nadal decyduje, czy poprawki są dobre i czy „brak testu” powinien naprawdę blokować merge. Skill formułuje tę regułę, ale zastosowanie jej do prawdziwego pull requesta to decyzja człowieka, tak samo jak w [lokalnym standardzie review](../code-review.md), którego ten projekt trzyma się we własnych PR-ach.

## Kolejne kroki { #next-steps }

Podłącz tego samego agenta do sandboksa z dostępem do sieci i niech przejrzy diff ze sklonowanego publicznego repozytorium zamiast takiego, które mu podyktujesz. Runtime `workbench` ma `git` i sieć, więc `git clone` działa tak samo, jak tutaj `git diff`.
