---
source_sha: "f0e7bf18f180"
---

# Scenariusz dowodowy { #proof-scenario }

Zmiana nie jest gotowa, dopóki agent nie odtworzy błędu, nie zobaczy, że
przechodzi, i nie pokaże dowodów. Zielone, zmockowane testy nie dowodzą, że
doświadczenie użytkownika działa. Dowód to dowody zaobserwowane w sesji -
wyjście polecenia, odtworzenie, zrzut ekranu - dla każdej zmiany w diffie.

To zasada „Dowód, nie diffy" z `full-send` Theo w tstack, jako capability.
Procedura znajduje się w skillu `proof-scenario`
(`backend/app/core/catalog/skills/proof-scenario/SKILL.md`); ta strona mówi,
co capability robi z dowodami.

## Jak działa scenariusz { #how-a-scenario-works }

Agent zapisuje scenariusz poleceniem `proof_scenario_record`, **zanim cokolwiek
naprawi**: co odtwarza, jak działa - polecenie, odtworzenie albo przepływ
interfejsu -, które pliki diffa obejmuje oraz próbę sprzed poprawki, która
pokazuje błąd. Po poprawce uruchamia **to samo** odtworzenie ponownie i
zapisuje próbę po poprawce wraz z tym, co faktycznie zobaczył.

Scenariusz jest udowodniony tylko wtedy, gdy to samo odtworzenie nie powiodło
się przed poprawką i powiodło się po niej, w obu przypadkach przy
zaobserwowanych dowodach. Jedna połowa sama nic nie dowodzi: błąd bez
ponownego przebiegu, który przechodzi, to zgłoszenie błędu, a sukces bez
wcześniejszej nieudanej próby nigdy nie pokazał, że poprawka cokolwiek
naprawiła. Próba, która się wykonała, ale niczego nie udowodniła - polecenie
zawiodło, zanim dotarło do zachowania, zrzut uchwycił zły ekran - jest
`inconclusive` i nie liczy się jako żadna z połów.

Uruchomienie testów jednostkowych jest zapisywane, gdy agent je przekaże, z
rodzajem dowodu `unit_test`, i nigdy nie liczy się do pokrycia. Przy zmianach
interfejsu dowodem jest zrzut ekranu albo zaobserwowany przepływ interfejsu -
uruchomić aplikację i popatrzeć - a nie test komponentu.

## Werdykt pokrycia { #the-coverage-verdict }

Zanim poprosi o scalenie, agent wywołuje `proof_scenario_verdict` z
zmienionymi plikami, informacją, czy wymagane kontrole są zielone na
bieżącym headzie, ile wciąż oczekuje i ile ustaleń przeglądu jest wciąż
otwartych. Werdykt zgłasza, które zmienione pliki mają zaobserwowany dowód,
a które nie:

| Werdykt | Znaczenie |
|---|---|
| `proven` | Każdy zmieniony plik jest objęty udowodnionym scenariuszem. |
| `partial` | Niektóre pliki są objęte; raport wymienia pozostałe. |
| `unproven` | Żaden plik nie jest objęty. |
| `no_scenarios` | Nie zapisano w ogóle nic. |

To samo wywołanie zgłasza dowodową połowę bramki scalania: dowód, kontrole i
ustalenia. Wszystkie trzy muszą być spełnione, żeby bramka była gotowa -
dowód obejmujący diff, wymagane kontrole zielone bez oczekujących i żadne
otwarte ustalenie przeglądu. Gotowość wciąż niczego nie scala: scalenie
wymaga wyraźnej prośby użytkownika, na bieżącym headzie, bez przeglądu
człowieka, który wciąż żąda zmian, i przy aktualnej, scalalnej gałęzi. Nigdy
nie używaj `--admin` ani żadnego innego obejścia.

Gdy nie da się znaleźć sposobu na udowodnienie zmiany, agent mówi to i pyta
użytkownika, zamiast twierdzić, że ma dowód, którego nie ma. Zmiana
nieudowodniona złożona jako nieudowodniona to uczciwa praca; zmiana
nieudowodniona złożona jako udowodniona to nie jest.

## Gdzie mieszka dowód { #where-the-proof-lives }

Scenariusze znajdują się w manifeście przebiegu, obok żądań i poprawek
recenzenta przebiegu, a szuflada przebiegu pokazuje każdy scenariusz wraz z
jego próbami i informacją, czy jest udowodniony. Nie ma migracji: scenariusze
to JSONB w manifeście, nie tabela. Manifest przebiegu przechowuje co najwyżej
dwadzieścia scenariuszy i sześć prób na scenariusz, a zaobserwowane wyjście
jest przycinane przed zapisaniem.

## Czego celowo nie robi { #what-it-deliberately-does-not-do }

- **Nie scala, nie komentuje, nie działa wobec zmiany.** Tylko dowód i
  raport.
- **Żadnego dowodu z testów jednostkowych.** Zmiana, której jedynym dowodem
  jest zielony zestaw testów, jest zgłaszana jako nieudowodniona.
- **Żadnego wymyślonego dowodu.** Czego agent nie zobaczył, tego nie zapisał.
- **Niczego nie uruchamia.** Capability samo nigdy nie wykonuje polecenia:
  agent uruchamia odtworzenie i przekazuje to, co zaobserwował.
