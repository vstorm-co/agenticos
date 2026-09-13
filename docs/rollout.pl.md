---
source_sha: 5eec786139c5
---

# Wdrożenie u siebie { #rolling-it-out }

Ta strona jest dla tego, kto odpowiada za decyzję, a nie za instalację: co
zmienia się w firmie, która to uruchamia, kto co robi, ile to kosztuje i na
które trzy sposoby zwykle idzie to źle.

Nic tutaj nie wymaga terminala. [Instalacja](install.md) to druga połowa.

## Co to zastępuje { #what-it-replaces }

Nie człowieka. **Backlog.**

Każda firma ma kolejkę małych automatyzacji, które nigdy nie powstają:
odpowiedź na to samo pytanie klienta, cotygodniowe podsumowanie składane ręcznie,
formularz wypełniany z maila, wewnętrzne pytanie rozwiązywane przez oderwanie od
pracy jedynej osoby, która zna odpowiedź.

Każda z nich jest za mała, by uzasadnić projekt, a jest ich czterdzieści. Zostają
niezrobione, bo jedyną drogą do zbudowania którejkolwiek byli dotąd programista,
repozytorium i wydanie — a czas programisty lepiej spożytkować na produkcie.

AgenticOS sprawia, że każda z nich jest dokumentem, który ktoś pisze, a nie
oprogramowaniem, które ktoś wydaje.

## Kto co robi { #who-does-what }

Trzy role, a ten podział liczy się bardziej niż samo narzędzie.

| | Kto to jest | Co należy do niego |
|---|---|---|
| **Budujący** | Osoba, która zna odpowiedź — kierownik wsparcia, manager operacyjny, analityk | Pisze instrukcje agenta, wybiera, co wolno mu robić, wskazuje właściwe dokumenty, testuje go i publikuje |
| **Właściciel** | Ten, kto odpowiada za wydatek i za zachowanie | Ustawia budżety, decyduje, które akcje wymagają zatwierdzenia przez człowieka, czyta ślad audytowy |
| **Inżynier** | Jedna osoba, na część etatu, po pierwszym tygodniu | Przeprowadza instalację, podłącza systemy, dodaje capability, jeśli naprawdę potrzeba czegoś nowego |

Sens tego podziału polega na tym, że budujący nie jest zablokowany na
inżynierze. Jeśli każda zmiana tego, co agent mówi, musi przejść przez osobę z
dostępem do commitowania, kupiłeś wolniejszą wersję tego, co miałeś.

!!! info "Obciążenie inżyniera spada po konfiguracji"

    Podłączenie systemu to [serwer MCP po URL](mcp.md), a nie konektor, który
    ktoś pisze. Zmiana zachowania to edycja i publikacja, a nie wydanie. W
    większości tygodni koszt inżynieryjny wynosi zero.

## Realistyczne pierwsze dziewięćdziesiąt dni { #a-realistic-first-ninety-days }

| | | Jak wygląda „zrobione” |
|---|---|---|
| **Tydzień 1** | Instalacja, podłączenie jednego providera modeli, zaproszenie trzech osób | Jeden agent odpowiada na prawdziwe pytanie z prawdziwego dokumentu |
| **Tygodnie 2–4** | Jeden agent, jeden zespół, jedno powtarzalne zadanie. Budżet ustawiony celowo nisko | Zespół używa go, choć nikt o to nie prosi |
| **Tygodnie 5–8** | Umieść go tam, gdzie praca już się dzieje — [Slack, widget, rutyny uruchamiane mailem](channels.md) | Ktoś spoza zespołu pilotażowego używa go bez szkolenia |
| **Tygodnie 9–12** | Drugi i trzeci agent, zbudowany przez inną osobę | Ktoś spoza inżynierii opublikował agenta od początku do końca |

Kamieniem milowym, który się liczy, jest ten ostatni. **Jeden agent dowodzi
technologii; drugi agent, zbudowany przez kogoś innego, dowodzi modelu pracy.**
Jeśli każdy agent nadal pochodzi od tej samej osoby, masz narzędzie, a nie
platformę.

## Ile to kosztuje { #what-it-costs }

Trzy pozycje, a tylko jedna z nich zaskakuje.

- **Infrastruktura.** Postgres, Redis i host kontenerów. Mała maszyna wirtualna
  uciągnie pilota; to najtańsza pozycja i taka pozostaje.
- **Użycie modeli.** Mierzone per run, per agent i widoczne przed fakturą. To
  pozycja, którą trzeba obserwować, i ta, dla ograniczania której istnieją
  [budżety](governance.md#budgets) — sprawdzane *przed* każdym żądaniem do
  modelu, więc agent po przekroczeniu budżetu zatrzymuje się, zamiast przepłacać.
- **Ludzie.** Inżynier na czas konfiguracji, potem na część etatu. Budujący na
  zespół, w ramach jego dotychczasowej pracy, a nie jako nowe stanowisko.

Nie ma licencji za stanowisko, bo nie ma licencji: jest Apache-2.0, a
uruchamiasz to Ty. To zmienia kształt decyzji — dodanie jedenastego agenta i
setnego użytkownika nie kosztuje nic poza tokenami, których użyją.

!!! tip "Pierwszy budżet ustaw niżej, niż Ci się wydaje"

    Budżet, który zatrzymuje run, uczy dużo lepiej niż faktura. Zacznij od
    liczby, która zostanie osiągnięta, zobacz, na co to idzie, a potem podnieś ją
    świadomie. [Wybór modelu](choosing-models.md) opisuje, co naprawdę napędza
    rachunek.

## O co zapyta Twój przegląd bezpieczeństwa { #what-your-security-review-will-ask }

Pytania padają w przewidywalnej kolejności, a odpowiedzi są powodem, dla którego
wybrano tę architekturę.

| Pytają | Odpowiedź |
|---|---|
| Dokąd trafiają nasze dane? | Do Twojego Postgresa, na Twojej infrastrukturze. Nic nie dzwoni do domu. Jedyne wywołania wychodzące idą do providerów modeli, których skonfigurowałeś — i [nie ma ich wcale](choosing-models.md#closed-models-or-open-weights), jeśli uruchamiasz model sam |
| Kto co widzi? | [Trzy warstwy](permissions.md): administrator wdrożenia, rola w organizacji i granty per zasób. Kontrolka, której ktoś nie może użyć, nie jest renderowana, a nie renderowana i dopiero potem odmawiana |
| Co powstrzymuje agenta przed wyrządzeniem szkody? | Nic, co ma skutki uboczne, nie wykonuje się bez [approvalu](governance.md#approvals), gdy go wymagasz, a approval jest rozstrzygany dokładnie raz |
| Czy możemy udowodnić, co się stało? | Każdy run, każdy approval, każda rotacja sekretu są w [śladzie audytowym](governance.md#audit) — łącznie z runami, które się nie powiodły |
| Gdzie są poświadczenia? | W [jednym vaulcie](secrets.md), zapieczętowane per organizacja. Żadna odpowiedź API, linia logu ani wpis audytowy nigdy nie niesie klucza otwartym tekstem |
| Czy możemy przeczytać kod? | Tak. Zwykle na tym rozmowa się kończy |

## Trzy sposoby, na jakie idzie to źle { #three-ways-this-goes-wrong }

Każdy z nich był widziany; każdego da się uniknąć.

**Jedna osoba buduje każdego agenta.** Platforma staje się kolejką tej osoby i
jesteś tam, gdzie zacząłeś. Naprawa: niech drugi agent będzie czyjś inny i
usiądź przy tej osobie, kiedy go buduje.

**Pierwszy agent jest zbyt ambitny.** Agent, który dotyka czterech systemów i
podejmuje decyzje, zawodzi w sposób, którego nikt nie potrafi zdebugować, a ta
porażka zostaje zapamiętana jako „AI tutaj nie działa”. Naprawa: pierwszy agent
odpowiada na pytania z dokumentów. Jest nudny, działa i zarabia na drugiego.

**Nikt nie ustawił budżetu ani approvalu.** Runem, który kogoś zaskoczy, jest
ten, który nie miał limitu ani bramki, a kosztuje on więcej zaufania niż
pieniędzy. Naprawa: ustaw oba pierwszego dnia, na każdym agencie, zanim ktoś
jeszcze dostanie dostęp.

## Co mierzyć { #what-to-measure }

Powstrzymaj się od liczenia rozmów. Mierz cztery rzeczy, które decydują o tym,
czy było warto:

| | Dlaczego to właściwa liczba |
|---|---|
| **Pytania rozwiązane bez człowieka** | Rzeczywisty rezultat. Wszystko inne jest tylko jego przybliżeniem |
| **Koszt na rozwiązane zadanie** | Spada, kiedy dostrajasz wyszukiwanie i schodzisz o poziom modelu niżej — i jest widoczny per run, a nie per miesiąc |
| **Ile osób opublikowało agenta** | Liczba adopcji, która przewiduje, czy rzecz przetrwa swojego orędownika |
| **Approvale czekające** | Rosnąca kolejka znaczy, że bramka jest na złej akcji albo że agentowi jeszcze się nie ufa. Warto wiedzieć o obu wcześnie |

## Gdzie szukać pomocy { #getting-help }

Możesz prowadzić to całkowicie samodzielnie. Jest na Apache-2.0, dokumentacja
jest całą historią, a nie zajawką, i nic tutaj nie jest zamknięte za umową
wsparcia.

Dwa miejsca, gdzie pytać, kiedy czegoś nie opisano:
[GitHub issues i dyskusje](https://github.com/vstorm-co/agenticos) projektu oraz
[Materiały](resources/index.md) z przewodnikami dla kontrybutorów.

**[Vstorm](https://vstorm.co) buduje AgenticOS, a także go wdraża.** Warto o tym
wiedzieć, jeśli praca, na którą patrzysz, jest jedną z tych:

| | |
|---|---|
| **Doprowadzenie tego na produkcję wewnątrz Twojej infrastruktury** | Twoja chmura, Twoje centrum danych albo środowisko odcięte od sieci, podłączone do systemów, które już prowadzisz |
| **Postawienie modeli lokalnie** | Tak, by inferencja nigdy nie opuszczała budynku — sprzęt, środowisko uruchomieniowe i profile, które na nie wskazują |
| **Dostosowanie platformy do jednego procesu** | Capability, której nikt nie napisał, ścieżka ingestii dla Twojego kształtu dokumentów, kanał, którego używasz Ty i nikt inny |
| **Zbudowanie pierwszych agentów razem z Twoim zespołem** | Z bliska, tak by drugi był ich, a nie nasz |

Nic z tego nie jest licencją — platforma jest tym samym otwartym źródłem tak czy
inaczej, a wdrożenie zrobione przez kogoś innego nadal jest Twoje do czytania,
zmieniania i utrzymywania w ruchu.

[Porozmawiaj z nami →](https://vstorm.co/contact-us/)

## Podsumowanie { #recap }

- Zastępuje **backlog małych automatyzacji**, a nie człowieka.
- Podział, dzięki któremu to działa: **budujący nie jest zablokowany na
  inżynierze.**
- Kamień milowy, który się liczy, to **drugi agent, zbudowany przez kogoś
  innego.**
- **Brak licencji za stanowisko** — jedenasty agent kosztuje tylko tokeny,
  których użyje.
- Ustaw **budżet i approval pierwszego dnia**, na każdym agencie, zanim ktoś
  jeszcze dostanie dostęp.

[Zainstaluj →](install.md) · [Zbuduj pierwszego agenta →](first-agent.md) ·
[Czego odmawia →](about/index.md)
