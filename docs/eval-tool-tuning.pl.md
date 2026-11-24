---
source_sha: "eacd467a0b5c"
---

# Dostrajanie narzędzi na podstawie ewaluacji { #eval-tool-tuning }

Oceń jedno narzędzie na podstawie już ocenionych przypadków ewaluacyjnych
i przygotuj propozycje dostrojenia na podstawie błędów. Przebieg
dostrajania bierze ocenione wyniki próby ewaluacyjnej - przypadki, które
sprawdziła pętla uczenia się na błędach (#32) - i pyta, jak jedno narzędzie
zachowało się w nich: czy zostało wywołane, czy wybrano właściwe narzędzie,
czy zwróciło błąd, czy odpowiedź mimo to nie trafiła w oczekiwanie.

To skill dostrajania narzędzi na podstawie ewaluacji jako capability.
Procedura mieszka w skillu `eval-tool-tuning`
(`backend/app/core/catalog/skills/eval-tool-tuning/SKILL.md`), który mówi,
kiedy oceniać narzędzie; ta strona mówi, co capability robi z odpowiedzią.

## Jak działa przebieg dostrajania { #how-a-tuning-run-works }

Agent wywołuje `record_eval_tool_tuning` z narzędziem i ocenionymi
przypadkami - każdy przypadek z tym, co jego odpowiedź miała powiedzieć,
czy sędzia uznał, że przeszła, co powiedziała odpowiedź i każdym wywołaniem
narzędzia, które wykonał run tego przypadku. Jedno wywołanie to jeden
przebieg dostrajania: ocenia narzędzie, klasyfikuje każdy błąd, przygotowuje
jedną propozycję na klasę błędów i zapisuje przebieg w manifeście.

Błąd należy do jednej z czterech klas:

| Klasa | Co znaczy |
|---|---|
| `not_called` | Żadne narzędzie nie zadziałało w tym przypadku - narzędzie nigdy nie zostało wywołane |
| `wrong_tool` | Zamiast niego wybrano inne narzędzie |
| `bad_arguments` | Narzędzie zostało wywołane i zwróciło błąd |
| `wrong_answer` | Narzędzie zadziałało poprawnie, ale odpowiedź mimo to nie spełniła oczekiwania |

Każda klasa przygotowuje jeden rodzaj propozycji:

| Błąd | Propozycja | Co zmienia |
|---|---|---|
| `not_called`, `wrong_tool` | `tool_choice` | Które narzędzie jest wybierane - reguła routingu albo preferowanie tego narzędzia nad wybranym |
| `bad_arguments` | `tool_parameters` | Argumenty narzędzia - ich pola wymagane, zakresy i to, co liczy się jako poprawne |
| `wrong_answer` | `prompt_wording` | Co odpowiedź musi powiedzieć - linijka w instrukcjach agenta |

Jedna propozycja na klasę, nie na przypadek: pięć przypadków, które
zawodzą tak samo, to jeden problem dostrojenia, nie pięć. Ocena bez błędów
nie przygotowuje niczego.

## Konfiguracja { #configuration }

| Pole | Domyślnie | Co to jest |
|---|---|---|
| `max_tuning_runs` | `3` | Ile przebiegów dostrajania może zapisać jeden run (1–5) |

Limit powstrzymuje powtarzane ocenianie przed rozrostem pracy: oceń,
pokaż szkice, pozwól zdecydować człowiekowi. Świeży przebieg dostrajania
po zastosowaniu propozycji to nowy przebieg.

## Zapis { #the-record }

Każdy przebieg dostrajania jest zapisywany w manifeście runa i pokazywany
w szufladzie runa:

```markdown
## Dostrajanie narzędzi na podstawie ewaluacji

Narzędzie: search · 1/2 zdanych · najczęstszy błąd: not_called

| Przypadek | Klasyfikacja |
| --- | --- |
| total | passed |
| missing | not_called |

| Propozycja | Rodzaj | Dowody |
| --- | --- | --- |
| Route these requests to search | tool_choice | missing |
```

## Czego nie robi { #what-it-does-not-do }

- **Nie ocenia odpowiedzi.** Werdykt dla każdego przypadku przychodzi już
  oceniony, przez `judge()` pętli uczenia się na błędach
  (`app/services/eval_judging.py`, współdzielony z ewaluacjami przepływów
  pracy). Ocenianie zużywa pary `(passed, shown)`; drugi sędzia odszedłby
  od pierwszego, a bramka ewaluacji przestałaby znaczyć jedną rzecz.
- **Nie uruchamia ewaluacji.** Przepuszczanie przypadków ścieżką runa
  testowego to runner prób pętli (#32). Zanim #32 wyląduje, narzędzie
  bierze ocenione przypadki jako wejście; gdy #32 wyląduje, jego wyniki
  prób zasilą to narzędzie.
- **Nie stosuje propozycji.** Każda propozycja to szkic z jej przypadkami,
  które zawiodły, jako dowodami, do zatwierdzenia przez człowieka.
  Zastosowanie zmiany instrukcji przechodzi przez apply propozycji pętli
  (z bramką ewaluacyjną, audytowane); zmiana skilla przez ścieżkę
  nauczonych skilli (#9). Nie ma tu funkcji apply.
- **Nie trzyma przebiegów dostrajania poza manifestem.** Przebiegi mieszkają
  w JSONB manifestu runa, obok żądań. Nie ma tabeli do migracji ani
  przebiegu dostrajania do odpytania między runami - własne tabele pętli
  trzymają przypadki, gdy tylko #32 wyląduje.

Capability nie potrzebuje żadnego zakresu: jej narzędzie zapisuje we
własnym manifeście runa i nie wywołuje żadnego modelu, niczego nie
deleguje i nie dotyka żadnej usługi.
