---
source_sha: bf54d6dd6a38
---

# Funkcje { #features }

AgenticOS daje Ci to, co poniżej.

## Kod definiuje, konfiguracja komponuje { #code-defines-configuration-composes }

To jedno zdanie jest całym projektem tej rzeczy i opisuje dwie połowy, które
celowo nie są tą samą pracą.

**Zespół biznesowy komponuje agentów w przeglądarce.** Instrukcje, model, zestaw
capabilities, budżet — żadnego Pythona, żadnego pull requesta, żadnego wydania.
Spec jest dokumentem, więc wersjonuje się przy publikacji i eksportuje jako YAML
do Twojego własnego repozytorium git.

Przeglądarka to wszystko, czego konsola potrzebuje. [Aplikacja
desktopowa](desktop.md) opakowuje tę samą konsolę dla każdego, kto chce mieć ją w
docku - razem ze zwierzakiem i skrótem do zrzutu ekranu - i jest dodatkiem, a nie
drugim sposobem uruchamiania platformy.

**Inżynierowie rozszerzają to, z czego można komponować.** Capability to
typowany, przetestowany Python w tym repozytorium: narzędzie, które model może
wywołać, guardrail, strategia kompaktowania, konektor. Dodajesz jedną i od tej
chwili jest ona przełącznikiem w Builderze każdego.

Zasada między tymi dwiema połowami jest częścią nośną:

!!! quote "Konfiguracja nigdy nie sięgnie dalej niż to, co zarejestrował kod"

    Właśnie to sprawia, że Builder bez kodu można bezpiecznie oddać komuś, kto
    nie jest inżynierem. Taka osoba nie wymyśli narzędzia, nie poszerzy scope'u
    ani nie sięgnie do systemu, którego nikt nie podłączył — najgorsze, co może
    zrobić, to poskładać rzeczy już zatwierdzone.

Sufitem nie jest więc plik konfiguracyjny. Sufitem jest to, co Twoi inżynierowie
włożą do rejestru, a platforma jest na Apache-2.0, więc mieści się w tym
wszystko, co napiszesz pod własny przypadek użycia.

| Chcesz | Robisz |
|---|---|
| Innej odpowiedzi od agenta | Edytujesz instrukcje i publikujesz. Sekundy, bez inżyniera |
| Narzędzia do produktu SaaS | Wskazujesz [serwer MCP](mcp.md). Zwykle bez ani linijki kodu |
| Narzędzia, którego nikt nie napisał | [Dodajesz capability](howto/add-capability.md) — typowany Python, i pojawia się ona w Builderze |
| Innej ingestii, innego kanału albo konektora | [Rozszerzasz platformę](resources/index.md#extending-the-platform); za każdym razem ten sam wzorzec |
| Całości ukształtowanej pod jeden proces | Robisz forka. To Twoje wdrożenie i Twoje źródła |

!!! tip "O ten podział właśnie chodzi"

    Osoba, która wie, co agent ma mówić, rzadko jest osobą z dostępem do
    commitowania — a osoba, która potrafi napisać narzędzie, nie powinna spędzać
    tygodnia na zmianach w sformułowaniach. To jest ta linia, dzięki której oboje
    mogą pracować, nie czekając na siebie nawzajem.

!!! info "Dlaczego nazywa się to systemem operacyjnym"

    Bo to słowo jest specyfikacją, a nie etykietą: procesy, limity zasobów,
    kontrola dostępu, sterowniki, system plików, jedna powłoka dla wielu
    interfejsów i log audytowy. Każde z nich ma na tej stronie swój mechanizm.
    [Te siedem i jak przetestować nimi dowolny inny produkt →](about/index.md#what-makes-something-an-operating-system-for-agents)

## Zbudowany w UI, wersjonowany przy publikacji { #built-in-a-ui-versioned-on-publish }

Agenta budujesz w przeglądarce. Kiedy go publikujesz, spec zostaje zamrożony jako
wersja i to ta wersja działa — wersja robocza, którą wciąż edytujesz, nie dociera
do nikogo.

Każda opublikowana wersja pozostaje czytelna, więc *jak ten agent wyglądał w
marcu* jest pytaniem, na które istnieje odpowiedź.

## Eksportowalny do Twojego repozytorium { #exportable-into-your-own-repository }

Spec eksportuje się jako YAML. Zacommituj go, przejrzyj w pull requeście,
porównaj dwie wersje, przywróć jedną. To Twój plik, w Twojej historii gita, w
formacie, który do odczytu nie potrzebuje AgenticOS.

Import działa w drugą stronę, więc spec napisany ręcznie jest pełnoprawnym
agentem.

## Co agent naprawdę może zrobić { #what-an-agent-can-actually-do }

Decydujesz, włączając rzeczy pojedynczo, w Builderze. Nic z tego nie jest
wtyczką, którą ktoś instaluje, plikiem Pythona, który ktoś wdraża, ani promptem,
co do którego ktoś ma nadzieję, że model go posłucha — agent nie sięgnie
capability, która jest wyłączona, cokolwiek mówią jego instrukcje.

| Agent może… | Włącz |
|---|---|
| **Odpowiadać z tego, co wie Twoja firma** — Twoje dokumenty, Twoje spisane procedury i to, co dołączono do tej rozmowy | Knowledge search · Skills · Context |
| **Pamiętać i sprawdzać** — prowadzić notatki przez wiele rozmów, przypomnieć sobie fakt po znaczeniu albo znaleźć to, co naprawdę padło w przeszłej rozmowie, i to odczytać | Memory files · Memory (mem0) · Conversation search |
| **Pójść i się dowiedzieć** — przeszukać sieć, przeczytać jedną stronę porządnie albo poprowadzić prawdziwą przeglądarkę przez witrynę wymagającą klikania | Web search · Web fetch · Browser automation |
| **Wykonać pracę, a nie ją opisać** — uruchomić Pythona na pliku, prowadzić workspace z powłoką, narysować wykres, wygenerować obraz | Run Python · Files & shell · Charts · Image generation |
| **Poradzić sobie z pracą za dużą na jedną odpowiedź** — zdelegować do specjalistów, prowadzić listę zadań, pomyśleć dłużej przed odpowiedzią, ciągnąć długą rozmowę bez gubienia jej początku | Delegation · Planning · Thinking · Context management |
| **Trzymać się w ryzach** — zredagować albo zablokować to, co nie może przejść, ograniczyć to, co może zwrócić jedno narzędzie, wiedzieć, jaka jest dzisiaj data | Guardrails · Tool output limits · Date and time |

Każda z nich niesie własne ustawienia, własny scope uprawnień i — tam, gdzie
działa na świat zewnętrzny — własne ustawienie approvalu. Włączenie którejś jest
decyzją, którą ktoś podejmuje wobec *tego* agenta, a nie zmianą w platformie.

[Każda capability, jej narzędzia i jej konfiguracja →](reference/capabilities.md)

## Dowolny model, od 27 providerów { #any-model-from-27-providers }

OpenAI, Anthropic, Google, Groq, Mistral, Bedrock, Vertex, Ollama na Twoim
własnym sprzęcie, proxy LiteLLM przed tym wszystkim.

**Profil modelu** nazywa model, jego parametry i jego fallbacki; agenci wskazują
na profil. Zmień profil, a przesuną się wszyscy agenci, którzy go używają — bez
publikowania na nowo ani jednego speca.

Klucze są per organizacja, zapieczętowane w vaulcie i nigdy nie zwracane przez
żaden endpoint.

[Modele i providerzy →](models.md)

## Dowolny serwer MCP, po URL { #any-mcp-server-by-url }

Podłącz serwer, a jego narzędzia pojawią się w Toolboksie, z przestrzenią nazw,
więc dwa serwery oferujące `search` nie zderzą się ze sobą.

**W wyborze jest 5802 serwerów.** 99 tych popularnych — GitHub, Linear, Notion,
Slack, Stripe, Postgres — przychodzi z gotowo podłączonymi przepływami OAuth, bo
ktoś tutaj podłączył każdy z nich i to sprawdził. Pozostałe 5703 są lustrzaną
kopią publicznego rejestru MCP i da się je wyszukać po nazwie: nikt tutaj ich nie
przejrzał, a lista mówi, którego rodzaju jest dany wiersz.

!!! info

    To dlatego katalog capabilities jest krótki i krótki pozostaje. Integracja z
    produktem SaaS to połączenie MCP, a nie moduł Pythona, który ktoś w tym
    repozytorium musi utrzymywać wobec API tamtego produktu.

[Połączenia MCP →](mcp.md)

## Wiedza, która zostaje na Twoim sprzęcie { #knowledge-that-stays-on-your-hardware }

Wgraj dokumenty albo zsynchronizuj folder Google Drive czy bucket S3. AgenticOS
je parsuje, dzieli na fragmenty, osadza w pgvector i trzyma w *Twoim* Postgresie.

**To, jak je czyta, należy do Ciebie**, per kolekcja i z możliwością nadpisania
per wgranie — co jest nietypowe i co jest miejscem, gdzie naprawdę wygrywa się
jakość wyszukiwania:

| | |
|---|---|
| **Parser PDF** | `pymupdf` — lokalny, szybki i jedyny, który wyciąga osadzone obrazy do opisania · `liteparse` — lokalny i świadomy układu strony, zachowujący tabele jako siatki ASCII, zamiast je spłaszczać · `llamaparse` — usługa chmurowa rozliczana za stronę, zwracająca markdown |
| **Chunking** | `recursive`, `markdown` albo `fixed`, z własnym rozmiarem i zakładką |
| **OCR** | Na żądanie albo automatycznie, z językiem |
| **Obrazy w dokumentach** | Opisywane przez wybrany przez Ciebie profil modelu, z Twoim własnym promptem |

Embeddingi są kluczowane per organizacja. Wektor zapisany dla jednego tenanta nie
może zostać odczytany przez innego, a egzekwuje to schemat bazy, a nie klauzula
`WHERE`, którą ktoś musi pamiętać.

Model embeddingów jest ustalany przy tworzeniu kolekcji, bo dwa modele o tej
samej szerokości piszą do różnych przestrzeni, które wyszukiwanie i tak by
porównywało.

[Przetwarzanie plików →](file-processing.md) · [Skille →](skills.md)

## Jeden agent, każda powierzchnia { #one-agent-every-surface }

Publikujesz raz. Ten sam runner odpowiada na wszystkich tych:

- **Czat webowy** w konsoli
- **Hostowana strona**, do której możesz komuś wysłać link
- **Osadzalny widget** na Twoją własną stronę
- **HTTP API** oraz surowy WebSocket do strumieniowania
- **Slack**, **Telegram** i **Mattermost**, gdzie `@mention` uruchamia się jako
  osoba, która go wysłała — a nie jako bot

[Powierzchnie →](channels.md)

## Budżety, które naprawdę zatrzymują run { #budgets-that-actually-stop-a-run }

Sprawdzane **przed** każdym żądaniem do modelu, a nie sumowane po fakcie.

Run, który się nie powiódł, i tak zapisuje, ile wydał, bo budżet liczący tylko
sukcesy nie jest budżetem. Alerty odpalają się przy progach, które ustawiasz, per
agent.

## Approval dla wszystkiego, co ma skutki uboczne { #approval-for-anything-side-effecting }

Narzędzie, które zmienia świat zewnętrzny, parkuje run i czeka na człowieka.
Ustaw to per capability, nadpisz per narzędzie.

Approval jest rozstrzygany raz. Druga decyzja na rozstrzygniętym approvalu jest
odrzucana — co brzmi oczywiście, dopóki nie zobaczy się wyścigu, który czyni to
koniecznym.

[Nadzór →](governance.md)

## Uprawnienia w kodzie, role złożone z nich { #permissions-in-code-roles-composed-from-them }

Miejsca wywołań sprawdzają uprawnienia, nigdy nazwy ról. Rola to zestaw
uprawnień z katalogu, a **grant** poszerza to, co jedna osoba może zrobić z
jednym wierszem.

Grant nigdy nie zawęża. Viewer z jawnym grantem `edit` na jednym agencie może
edytować tego agenta — i nic więcej.

[Uprawnienia →](permissions.md)

## Sekrety pieczętowane per organizacja { #secrets-sealed-per-organization }

Klucze providerów, tokeny botów, poświadczenia MCP — jeden mechanizm,
`app/core/vault.py`, i celowo żadnego drugiego.

Szyfrogram skopiowany z wiersza bazy jednego tenanta nie może zostać odszyfrowany
dla innego. Żadna odpowiedź, linia logu ani wpis audytowy nigdy nie niesie klucza
otwartym tekstem.

[Sekrety i vault →](secrets.md)

## Wielotenantowość, w schemacie { #multi-tenant-in-the-schema }

Izolacja organizacji to ograniczenia i klucze, a nie konwencja. Ciekawe testy w
tym repozytorium to te, które sprawdzają *odmowę*: odczyt spoza tenanta,
nieprzyznany scope, przekroczenie budżetu, drugą decyzję na rozstrzygniętym
approvalu.

## Triggery, żeby agent działał bez Ciebie { #triggers-so-an-agent-runs-without-you }

Zaplanuj run albo odpal go na zdarzenie. Ten sam spec, ten sam budżet, ten sam
ślad audytowy — po prostu nikt nie pisze.

[Triggery →](triggers.md)

## Hostowany u siebie i cichy { #self-hosted-and-quiet }

Docker Compose, Twój Postgres, Twój Redis, Twój sprzęt.

Nic nie dzwoni do domu. Ceny modeli pochodzą ze snapshotu dołączonego do wydania,
a jedyne żądania wychodzące to te, które robią Twoi agenci.

## Open source { #open-source }

Apache 2.0, audytowalny i możliwy do sforkowania. Format speca jest wersjonowany,
więc dokument wyeksportowany dziś wczyta się także jutro.

[Zainstaluj →](install.md) · [Zbuduj pierwszego agenta →](first-agent.md)
