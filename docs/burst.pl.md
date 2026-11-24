---
source_sha: "30a1fb9a1506"
---

# Burst { #burst }

Jedno zadanie dzieli się na niezależne podzadania, które działają
równolegle, a ich wyniki łączą się w jeden wynik — seria pracy równoległej
zamiast jednego sekwencyjnego przebiegu. Agent najpierw dzieli zadanie i
pokazuje podział osobie, tak jak `/burst` w OpenMausBot pokazuje części z
wyprzedzeniem, potem jedno wywołanie rozdziela części między workerów
równolegle i zwraca połączenie.

To tryb Burst z OpenMausBot v0.1.153 jako capability: koncept — pokaż
podział, uruchom części równolegle, połącz wyniki — odbudowany na
rozgałęzieniu, którego council (#5) i sol-loop (#6) już używają. Procedura
żyje w skillu `burst-mode`
(`backend/app/core/catalog/skills/burst-mode/SKILL.md`), który mówi, kiedy
dzielić; ta strona mówi, co capability robi z częściami.

## Jak działa burst { #how-a-burst-works }

Agent wywołuje `run_burst` z zadaniem i częściami, każda część to polecenie
dla własnego workera. Jedno wywołanie to jeden burst: wywołanie uruchamia
każdą część równolegle na własnym modelu runa i łączy to, co wróci, w
kolejności części, pod własnym nagłówkiem każdej części.

Po burście agent działa na częściach, które się nie powiodły — ponawia je,
robi je bezpośrednio albo zawęża zadanie — i wywołuje ponownie po świeży
burst. Limit burstów powstrzymuje powtarzane bursty przed poszerzaniem
pracy: napraw to, co się nie powiodło, nic więcej. Nie uruchamiaj całego
bursta od nowa, żeby naprawić jedną część: burstuj tylko części, które się
nie powiodły.

Worker bursta robi tylko swoją część i nic więcej. Nie powtarza pracy innej
części i nie poszerza zadania.

## Konfiguracja { #configuration }

| Pole | Domyślnie | Co to jest |
|---|---|---|
| `max_subtasks` | `3` | Ile podzadań jeden burst wykonuje najwyżej naraz (2–10) |
| `max_bursts` | `3` | Ile burstów może zażądać jeden run najwyżej (1–5) |

Limit podzadań odzwierciedla limit `max_fanout` subagentów — domyślnie 3,
twardy limit 10 — zamiast go podnosić. Workerzy to jednorazowi agenci
ambient na własnym modelu runa, rozliczani z budżetu runa; odmowa z powodu
budżetu zapisuje część jako niepowodzenie zamiast wydawać ponad limit.

## Połączenie { #the-merge }

Każdy burst jest zapisywany w manifeście runa i renderuje się jako
połączony wynik, który skill burst umieszcza w opisie PR:

```markdown
## Burst

Task: Write the guide

Parts: 3 - 3 completed, 0 failed.

| B1 | Part 1 | completed |
| B2 | Part 2 | completed |
| B3 | Part 3 | completed |
```

Część, która się nie powiodła, czyta się jako `failed` z powodem, a
połączenie nazywa ją pod nagłówkiem `FAILED` ze stopką, która liczy — nigdy
jako część, która się zakończyła, i nigdy nie wypada z połączenia. Burst,
który stracił część, nigdy nie czyta się jako ten, który ją ukończył.

## Czego nie robi { #what-it-does-not-do }

- **Nie porzuca części, która się nie powiodła.** Worker, który zgłasza
  wyjątek albo nie zwraca nic użytecznego, zapisuje się jako `failed` z
  powodem. Połączenie tak mówi.
- **Nie wymyśla wyniku.** Połączenie to rzeczywiste wyniki części pod ich
  własnymi nagłówkami. Nic nie jest streszczane aż do zniknięcia.
- **Nie podnosi limitu rozgałęzienia.** Limit podzadań to limit subagentów,
  nie nowy.
- **Nie deleguje ze specyfikacją.** Workerzy bursta to jednorazowi agenci na
  własnym modelu runa, bez własnej specyfikacji. Część, która potrzebuje
  własnych narzędzi, poświadczeń albo stałego agenta, to delegacja przez
  capability subagents, nie część bursta.
- **Nie ocenia pracy.** Części bursta pracują; nie oceniają. Burst, który
  wymaga oceny, to runda council po połączeniu.
- **Nie naprawia tego, co się nie powiodło.** Burst nie naprawia ani nie
  iteruje sam. Agent ponawia, robi część bezpośrednio albo zawęża zadanie,
  potem prosi o świeży burst.
- **Nie trzyma burstów poza manifestem.** Bursty żyją w JSONB manifestu
  runa, obok żądań, i są odczytywane z powrotem przez schemat manifestu. Nie
  ma tabeli do migracji ani bursta do zapytania między runami.
- **Nie działa na żywo w rozmowie.** Burst trwa minuty, na które rozmowa nie
  może czekać, więc capability działa w tekstowym bliźniaku agenta,
  przekazanym z rozmowy.

Capability potrzebuje scope `agents:delegate`, ponieważ jego workerzy to
wywołania modelu, którym agent przekazuje pracę.
