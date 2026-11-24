---
source_sha: "1fe0c9faf3be"
---

# Sol-loop { #sol-loop }

Jeden recenzent ocenia pracę, zanim trafi dalej, w rundach, aż przejdzie
albo skończy się budżet. Runda 1 przegląda całą zmianę; późniejsze rundy
sprawdzają tylko zmieniony kod i otwarte ustalenia. Agent naprawia to, co
znalazł recenzent, i woła ponownie o świeżą rundę.

To skill sol-loop jako capability. Procedura znajduje się w skillu
`sol-loop` (`backend/app/core/catalog/skills/sol-loop/SKILL.md`), który mówi,
kiedy prosić o przegląd; ta strona mówi, co capability robi z odpowiedzią.

## Jak działa runda { #how-a-round-works }

Agent woła `run_sol_loop_review` z pracą i kontekstem, którego potrzebuje.
Jedno wołanie to jedna runda: wołanie prosi jedynego skonfigurowanego
recenzenta o werdykt i ustalenia ze stabilnymi id.

Po rundzie agent naprawia to, co znalazł recenzent, i woła ponownie o świeżą
rundę, aż werdykt na bieżącym diffie będzie brzmiał APPROVE. Limit rund
powstrzymuje powtarzane przeglądy przed rozrostem pracy: napraw to, o co
poproszono, nic więcej. Runda, której ustalenia to same nity, zatrzymuje się
wcześniej - odrzucone nity nie potrzebują nowej rundy.

Przegląd recenzenta jest tylko do odczytu. Ocenia pracę taką, jaka jest; nie
edytuje jej, nie robi commita, nie komentuje ani nie uruchamia subagentów czy
recenzentów.

## Konfiguracja { #configuration }

| Pole | Domyślnie | Co to jest |
|---|---|---|
| `reviewer` | — | Jedyny recenzent: nazwa, dostawca i profil modelu |
| `max_rounds` | `3` | Ile rund przeglądu może zażądać jeden run (1–5) |

Recenzent przegląda tylko na **głównym** modelu swojego profilu. Łańcuch
fallback profilu nigdy nie jest tu używany: fallback po cichu podstawiłby
inny model, gdy pierwszy zawiedzie, a przegląd przez zastępcę to nie przegląd,
który skonfigurował operator. Kod nie wymusza, by model był modelem Sol:
operator kieruje profil recenzenta na swój model Sol, a nazwanie wersji w
kodzie zdezaktualizowałoby się, gdy tylko pojawi się nowszy Sol.

## Rejestr { #the-ledger }

Każda runda jest zapisana w manifeście runa i renderowana jako rejestr
ustaleń, który prowadzi skill sol-loop:

```markdown
## Sol-loop review

Rounds: 2

| Round | Scope | Verdict | Stop |
| --- | --- | --- | --- |
| 1 | full | CHANGES | — |
| 2 | changed-only | APPROVE | approved |

| Finding | Severity | File | Outcome |
| --- | --- | --- | --- |
| S1 | blocker | app/x.py | agree-fixed |
```

Ustalenie, na które nikt jeszcze nie odpowiedział, czyta się jako `open`.
Recenzent, do którego nie udało się dotrzeć, czyta się jako `unavailable`,
z powodem - nigdy werdykt, którego nie wydał, i nigdy zatwierdzenie. Koniec
budżetu czyta się jako `budget_exhausted` i też nie jest zatwierdzeniem.
Ustalenie sporne po dwóch odpowiedziach czyta się jako `stuck`: decyduje
użytkownik. Użycie przeglądu czyta się jako `not exposed`: wołanie przeglądu
zwraca tylko przegląd, nigdy jego zużycie tokenów.

## Czego nie robi { #what-it-does-not-do }

- **Nie naprawia tego, co znajduje.** Sol-loop ocenia; agent naprawia, a
  potem prosi o świeżą rundę.
- **Nie przechowuje rund nigdzie poza manifestem.** Rundy żyją w JSONB
  manifestu runa, obok żądań. Nie ma tabeli do migracji ani rundy do
  odpytywania między runami.
- **Nie zastępuje recenzenta.** Recenzent, którego modelu nie udało się
  rozwiązać, jest zgłaszany jako niedostępny, nigdy zastępowany innym modelem.
- **Nie zgaduje użycia.** Rejestr mówi, że użycie nie jest ujawnione, zamiast
  wymyślać liczbę.
- **Nie działa na żywo w rozmowie.** Przegląd trwa minuty, na które rozmowa
  nie może czekać, więc capability działa w tekstowym bliźniaku agenta,
  przekazanym z rozmowy.

Capability potrzebuje scope `agents:delegate`, bo jej recenzent jest wołaniem
modelu, któremu agent przekazuje pracę.
