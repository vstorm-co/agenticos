---
source_sha: "5e91e7483c03"
---

# Rada { #council }

Trzech delegatów ocenia pracę, zanim trafi dalej: po jednym silnym modelu od
każdego z trzech różnych dostawców, przy wysokim wysiłku rozumowania,
równolegle. Każdy delegat ocenia pracę w skali do 10, a nowa ocena po
poprawkach to nowa runda. Pętla działa, aż każdy delegat będzie zadowolony.

To skill rady w postaci capability. Procedura znajduje się w skillu
`council-review` (`backend/app/core/catalog/skills/council-review/SKILL.md`),
który mówi, kiedy prosić o ocenę; ta strona mówi, co capability robi z
odpowiedzią.

## Jak działa runda { #how-a-round-works }

Agent wywołuje `run_council_review`, podając pracę i potrzebny kontekst.
Jedno wywołanie to jedna runda: wywołanie rozsyła pracę do delegatów,
każdego na modelu jego własnego dostawcy, i zwraca ich oceny wraz z uwagami.

Po rundzie agent poprawia to, co znaleźli delegaci, i wywołuje ponownie,
prosząc o nową rundę, aż każdy delegat oceni pracę na co najmniej próg
zgodności. Limit rund powstrzymuje kolejne oceny przed rozrostem pracy:
popraw to, o co poproszono, nic więcej.

Ocena delegata jest tylko do odczytu. Ocenia pracę w jej obecnym stanie; nie
edytuje jej i nie proponuje prac spoza jej zakresu.

## Konfiguracja { #configuration }

| Pole | Domyślnie | Co to jest |
|---|---|---|
| `members` | — | Dokładnie trzech delegatów, każdy z nazwą, innym dostawcą i profilem modelu |
| `agreement_threshold` | `8` | Ocena w skali do 10, którą każdy delegat musi osiągnąć, żeby runda zadowoliła radę |
| `max_rounds` | `3` | Ile rund oceny może poprosić jeden run (1–5) |

Każdy członek ocenia wyłącznie na **podstawowym** modelu swojego profilu.
Łańcuch zapasowy profilu nigdy nie jest tu używany: zapasowy model po cichu
podmieniłby innego dostawcę, gdyby pierwszy nie działał, a rada z dwoma
delegatami u jednego dostawcy nie jest radą.

## Tabela { #the-table }

Każda runda jest zapisywana w manifeście runu i wyświetlana jako tabela,
którą skill rady umieszcza w opisie PR:

```markdown
## Council review

Rounds: 2

| Delegate | Round 1 | Round 2 |
| --- | --- | --- |
| Claude Opus | 7/10 | 9/10 |
| GPT Sol | 8/10 | 10/10 |
| Gemini Pro | 7/10 | 9/10 |
```

Delegat, który nie podał oceny, ma wpis `no score`. Ten, do którego nie
można było dotrzeć, ma wpis `unavailable` wraz z powodem. Żaden z nich nigdy
nie dostaje oceny, której sam nie podał, a niedostępny członek nigdy nie
zostaje zastąpiony.

## Czego to nie robi { #what-it-does-not-do }

- **Nie poprawia tego, co znajduje.** Rada ocenia; agent poprawia, a potem
  prosi o nową rundę.
- **Nie przechowuje ocen nigdzie poza manifestem.** Oceny znajdują się w
  JSONB manifestu runu, obok requestów. Nie ma tabeli do migracji ani oceny
  do wyszukiwania między runami.
- **Nie działa w trakcie rozmowy na żywo.** Ocena trwa minuty, na które
  rozmowa nie może czekać, więc capability działa w tekstowym bliźniaku
  agenta, przekazanym z rozmowy.

Capability wymaga zakresu `agents:delegate`, ponieważ jego delegaci to
wywołania modelu, którym agent przekazuje pracę.
