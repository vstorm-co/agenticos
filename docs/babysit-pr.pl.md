---
source_sha: "ac197a8b5ef6"
---

# Babysit PR { #babysit-pr }

Obserwuj pull request w CI i botach recenzujących, zgłaszaj tylko to,
co się zmieniło, i kończ, gdy boty są zielone na najnowszym commicie.
To skill babysit-pr jako capability: procedura żyje w skillu
`babysit-pr` (`backend/app/core/catalog/skills/babysit-pr/SKILL.md`),
który mówi, kiedy obserwować; ta strona mówi, co capability robi ze
snapshotem.

## How a watch works { #how-a-watch-works }

Agent obserwuje przy użyciu capability monitor — `start_monitor` na
`gh pr checks --watch` — i przekazuje każdy nowy snapshot do
`babysit_pr_check` z repo, numerem PR, SHA heada i checkami tak, jak
zostały zgłoszone. Narzędzie klasyfikuje snapshot: liczą się tylko
checki bieżącego commita, każdy nieudany check jest nazwany real lub
flake, z powodem, a zgłaszane są tylko checki, które zmieniły się od
ostatniego snapshota. Gdy nic się nie zmieniło, a obserwacja trwa,
raport jest pusty, a agent kończy swoją turę bez wiadomości — nigdy
nie postuje ani nie mówi „ciągle czekam".

Obserwacja kończy się, gdy narzędzie zgłosi zieleń na najnowszym
commicie, gdy obserwacja przekroczy skonfigurowane maksimum bez
zieleni, albo gdy agent zatrzyma ją przez `babysit_pr_stop` —
gotowe, zablokowane lub z pytaniem do użytkownika. Merge albo
zamknięcie kończy obserwację samo. Przed ponowną obserwacją agent
sprawdza `gh api rate_limit` i przekazuje wynik do
`babysit_pr_rate_limit`: dopóki zostały wywołania, obserwuje dalej,
a gdy są prawie zużyte, czeka na reset.

## Configuration { #configuration }

| Pole | Domyślnie | Co to jest |
|---|---|---|
| `poll_interval_seconds` | `300` | Sekundy między sprawdzeniami pull requestu (60–1800) |
| `max_watch_minutes` | `240` | Minuty, przez które obserwacja może trwać, zanim zatrzyma się i zgłosi blokadę (30–1440) |

Zapytania są oddzielone co najmniej 60 sekundami, więc watcher nigdy
nie odpytuje w ciasnej pętli i nie zużywa wspólnego limitu GitHub.
Obserwacja, która przekroczy maksimum bez zieleni, nie została
zatwierdzona — wygasła.

## The watch log { #the-watch-log }

Każdy check, który się zmienił, jest zapisywany w manifeście runa,
wraz z klasyfikacją i decyzją, do której doprowadził. Klasyfikacja
flake to heurystyka oparta na własnym tekście błędu checka, nie
wyrok: agent weryfikuje każde ustalenie u źródła, zanim odrzuci je
z pisemnym powodem, a błąd, którego tekst nie pasuje do żadnego
sygnału infrastruktury, jest prawdziwy, dopóki nie udowodniono
inaczej.

## What it does not do { #what-it-does-not-do }

- **Mergować, komentować ani robić nic innego na PR.** Tylko
  obserwacja i zgłaszanie. Powiadomienie to wiadomość, nie decyzja o
  mergu; agent sam sprawdza merge gate, a merge wymaga wyraźnej
  prośby użytkownika.
- **Uruchamiać `gh` samodzielnie.** Czytanie checków to zadanie
  agenta, w ramach capability monitor. Ta capability klasyfikuje
  snapshoty, które dostaje, więc nie potrzebuje danych GitHub ani
  scope'u sandbox.
- **Obserwować PR, który do niej nie należy.** Jeden watcher na PR
  i tylko wątek właściciela PR go obserwuje. Delegowane dziecko
  nigdy nie obserwuje; rozpoczęcie drugiego PR, gdy jeden jest
  aktywny, jest odrzucane.
- **Trzymać zdarzeń obserwacji poza manifestem.** Zdarzenia żyją w
  JSONB manifestu runa, obok requestów. Nie ma tabeli do migracji
  ani zdarzeń do zapytań między runami.
