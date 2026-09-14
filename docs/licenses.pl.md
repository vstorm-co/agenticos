---
source_sha: "097a2caa4c8d"
---

# Licencje i noty stron trzecich { #licences-and-third-party-notices }

!!! abstract "Co ta strona twierdzi, a czego nie"

    Każdy komponent, który niosą dwa publikowane obrazy, jest wymieniony wraz ze
    swoją licencją i dowodem na nią, a każde zobowiązanie, które te licencje
    nakładają, jest albo spełnione w sposób nazwany na tej stronie, albo zapisane
    jako otwarte ustalenie z issue, które je trzyma. Nie mówi ona „wszystkie
    licencje są zgodne”: w chwili pisania otwarte jest jedno ustalenie i jest
    wypisane poniżej, a nie uśrednione. Dwa kolejne zostały przejrzane
    i rozstrzygnięte — komponent na AGPL, który ma własną sekcję, i obraz Redisa,
    który został wymieniony.

Sam AgenticOS jest na Apache-2.0 (`LICENSE`, `NOTICE`). To, co faktycznie
uruchamia wdrożenie, to ten kod plus mniej więcej pięćset pakietów stron
trzecich, dwa obrazy oparte na Debianie, garść fontów i ikon oraz te usługi
i modele, które wdrożenie podłączy. Ta strona jest przeglądem tego wszystkiego:
co jest w zakresie, jak powstaje inwentarz, o co prosi każda rodzina licencji
i jak jest to zaspokojone oraz co zrobić, gdy zmienia się zależność albo model.

## Co jest w zakresie { #what-is-in-scope }

| Warstwa | Skąd bierze się inwentarz | Dystrybuowane przez ten projekt? |
|---|---|---|
| Dystrybucje Pythona backendu | `backend/uv.lock`, rozwiązany dla Linuksa przez `uv export --no-dev` | Tak, w `agenticos-backend` |
| Pakiety npm frontendu | produkcyjne domknięcie `frontend/package.json`, z `frontend/bun.lock` | Tak, w `agenticos-frontend` |
| Obrazy bazowe i pakiety Debiana, które instaluje obraz backendu | `backend/Dockerfile`, `frontend/Dockerfile` | Tak, jako warstwy obu obrazów |
| Fonty, glify marki, dołączone pliki danych | `frontend/src/app/fonts/`, `NOTICE`, `backend/app/core/catalog/` | Tak |
| Obrazy usług, które wdrożenie uruchamia obok tych dwóch powyżej | pliki compose | Nie: pobiera je operator |
| Wagi modeli | wybierane per wdrożenie w profilu modelu | Nie: nigdy nie są dostarczane |
| Hostowani providerzy i usługi | konfigurowani per wdrożenie poświadczeniem w vaulcie | Nie: to umowa między wdrożeniem a providerem |

Narzędzi deweloperskich i dokumentacyjnych (`uv sync --dev`, grupa zależności
`docs`, `devDependencies`) nie ma ani w obrazach, ani w notach. Narzędzia
budowania, które działają w etapie buildera i których nie ma w warstwie końcowej,
takie jak `uv`, są zapisane w `licenses/components.toml` jako niedystrybuowane.

## Inwentarz { #the-inventory }

Niosą go dwa pliki, a skrypt pilnuje, żeby były uczciwe.

**[`THIRD_PARTY_NOTICES.md`](https://github.com/vstorm-co/agenticos/blob/main/THIRD_PARTY_NOTICES.md)**
jest generowany i commitowany. Dla każdej dystrybucji w którymkolwiek z obrazów
zapisuje nazwę, wersję, wyrażenie licencyjne SPDX, URL źródła oraz dowód, z
którego odczytano licencję: nagłówek `License-Expression`, klasyfikator, treść
samego pliku licencji, indeks pakietów albo override zapisany przez człowieka.
Wypisuje też najpierw otwarte ustalenia, liczbę komponentów na licencję oraz
komponenty zapisane ręcznie.

**`licenses/policy.toml`** trzyma decyzje. Wpis `override` to licencja, którą
człowiek ustalił dla komponentu, którego metadane jej nie podają, wraz z dowodem,
który przeczytał; obowiązuje tylko dopóki metadane milczą. Wpis `notices` to
właściciel praw autorskich pakietu, który nie niesie pliku licencji i nie wymienia
autora. Wpis `review` to decyzja dla komponentu na licencji typu copyleft,
share-alike albo nieotwartej: `accepted`, mówiąca jak zobowiązanie jest spełnione,
albo `open`, wskazująca issue, które je trzyma. **`licenses/components.toml`**
zapisuje to, czego nie wie żaden lockfile: obrazy, pakiety Debiana, fonty, glify,
pliki danych i obrazy usług, każde ze statusem i swoim zobowiązaniem.

`scripts/license_inventory.py` czyta wszystkie trzy. `make licenses` regeneruje
noty; `make licenses-check`, uruchamiany przez job `security` i przez
`make check`, regeneruje je w pamięci i wywala się, gdy:

- zacommitowane noty różnią się od tego, do czego rozwiązują się teraz lockfile'e,
  w którymkolwiek komponencie, wersji, licencji albo źródle (komórka z dowodem nie
  jest porównywana: dwa wheele jednego wydania mogą nieść różne metadane, a ona
  zapisuje, skąd licencję odczytała ta konkretna maszyna);
- metadane komponentu nie wymieniają żadnej licencji i żaden override jej nie
  zapisuje albo override jest zapisany dla komponentu, którego metadane teraz
  jednak licencję wymieniają;
- pakiet nie niesie pliku licencji i albo nie wymienia autora (a żaden wpis
  `notices` nie zapisuje właściciela praw), albo deklaruje licencję, której tekstu
  nie ma pod `frontend/licenses/texts/`;
- komponent jest na licencji ze zbioru do przeglądu i nie ma decyzji;
- decyzję podjęto o innej licencji niż ta, którą komponent niesie teraz, bo
  zmieniła ją aktualizacja;
- decyzja wymienia komponent, którego lockfile'e już nie rozwiązują.

Otwarte ustalenie, które jest śledzone, nie wywala checku. Linia werdyktu je
zlicza: `LICENSES: REVIEWED - 518 components, 1 open finding(s)`.

!!! warning "Nieznane u skanera to pytanie, a nie zgoda"

    Skrypt nigdy nie zgaduje. Samo `BSD` w polu `License` nie jest rozwiązywane do
    liczby klauzul na podstawie założenia; decyduje plik licencji, a jeśli i on
    jest nieczytelny, check wywala się dopóty, dopóki ktoś go nie przeczyta i nie
    zapisze odpowiedzi. Kolumna z dowodem w notach jest tym, co pozwala
    recenzentowi odróżnić licencję zadeklarowaną od wywnioskowanej.

Inwentarz jest tym, co instaluje wdrożenie, a nie tym, co ma maszyna uruchamiająca
skrypt. Markery środowiskowe są ewaluowane dla Linuksa na obu architekturach, pod
które budowane są obrazy, pakiety npm zależne od platformy są zachowywane tylko
wtedy, gdy budują się dla Linuksa z glibc na x64 albo arm64, a pakietowi, którego
maszyna nie ma, metadane są odczytywane z PyPI albo z rejestru npm. Nieudane
odpytanie jest awarią całego przebiegu.

## O co proszą licencje i jak jest to zaspokojone { #what-the-licences-ask-and-how-it-is-answered }

Liczby poniżej pochodzą z not w chwili pisania; aktualną wartością jest sam plik
not.

| Rodzina licencji | Komponentów | Zobowiązanie | Jak jest spełnione |
|---|---|---|---|
| MIT, ISC, BSD-2-Clause, BSD-3-Clause, 0BSD, MIT-0, MIT-CMU, Unlicense | około 400 | Zachować notę o prawach autorskich i tekst licencji przy kopiach | Plik licencji każdego pakietu jedzie w obrazie, obok kodu: każde `*.dist-info/` wheela w obrazie backendu, plik licencji każdego pakietu pod `/app/licenses/node_modules/<name>/` w obrazie frontendu. Noty je indeksują |
| Apache-2.0 | około 90 | Tekst licencji, informacja o zmianach, każdy plik `NOTICE`, który niesie pakiet | Jak wyżej; nic nie jest modyfikowane, więc nie ma zmian, o których trzeba informować |
| PSF-2.0, CNRI-Python, Zlib, CC0-1.0 | kilka | Atrybucja albo nic | Jak wyżej |
| MPL-2.0 (`certifi`, `pathspec`, `tqdm`, część `orjson`) | 4 | Copyleft na poziomie plików: objęte pliki zostają na MPL, a ich źródła są dostępne | Używane bez modyfikacji; tekst licencji jedzie w obrazie; noty linkują źródła |
| LGPL-3.0-or-later (`psycopg2-binary`, `@img/sharp-libvips-linux-*`) | 3 | Tekst licencji, dostępność źródeł i możliwość podmiany biblioteki | Oba to osobno instalowane binaria ładowane dynamicznie, bez modyfikacji, wymienialne przez reinstalację; źródła zalinkowane w notach. Pakiety libvips nie publikują pliku licencji, więc obraz kładzie tekst LGPL obok nich |
| Artistic-1.0-Perl albo GPL-2.0-or-later (`text-unidecode`) | 1 | Podwójna; wzięta na Artistic License: nota i tekst | Plik licencji z wheela jedzie w obrazie |
| CC-BY-4.0 (`caniuse-lite`) | 1 | Atrybucja i link do źródła | Wymieniony wraz ze źródłem w notach |
| AGPL-3.0-only (`pymupdf`) | 1 | Copyleft sieciowy: obraz jest przekazywany na warunkach AGPL-3.0, a zmodyfikowane wdrożenie jest winne swoim użytkownikom zmodyfikowane źródła (art. 13) | Utrzymany świadomie, warunki nazwane: [sekcja poniżej](#the-agpl-component) i plik `COPYING` wheela w obrazie |
| OFL-1.1 (Inter, Bricolage Grotesque, Geist Mono) | 3 rodziny | Tekst licencji i noty o prawach autorskich przy fontach; zakaz sprzedaży samych fontów; zakaz używania zastrzeżonych nazw dla zmodyfikowanych fontów | `frontend/src/app/fonts/OFL.txt` niesie wszystkie trzy noty; fonty są serwowane bez modyfikacji |
| CC0-1.0, CC-BY-4.0, MIT (glify marki) | 3 źródła | Atrybucja dla ikon Font Awesome; znaki pozostają znakami towarowymi swoich właścicieli | `NOTICE` wymienia źródła i stanowisko wobec znaków towarowych |

**Pakietowi, który nie publikuje pliku licencji**, nie da się jej skopiować. Kilka
pakietów npm w domknięciu jest właśnie takich, wśród nich
`@img/sharp-libvips-linux-x64` i jego bliźniak na arm64: biblioteka na LGPL bez
kopii LGPL w tarballu. Takich jest też dziewięć wheeli, wśród nich `tokenizers`
i `liteparse`. Dla każdego pakietu npm `frontend/scripts/collect-licenses.ts`
zapisuje `NOTICE` wymieniające pakiet, jego zadeklarowaną licencję, autora
i repozytorium, oraz kopiuje tekst każdej licencji z jego wyrażenia
z `frontend/licenses/texts/`. Obraz backendu niesie te same teksty pod
`/app/licenses/texts/`, a `METADATA` każdego wheela i tak wymienia jego licencję
i autora. Licencja, której tekstu tam nie ma, wywala build obrazu frontendu,
a `make licenses-check` wywala się wcześniej, na pull requeście, dla obu obrazów.
Pakiet, który nie wymienia też autora, `client-only`, ma właściciela praw
zapisanego w `licenses/policy.toml` pod `notices`, wraz z dowodem, i noty go niosą.

Obrazy bazowe zasługują na własne zdanie. `python:3.12-slim` i `oven/bun:1` to
Debian, czyli setki pakietów na warunkach GPL, LGPL, MIT i BSD. Debian trzyma
licencję każdego pakietu w `/usr/share/doc/<package>/copyright` wewnątrz obrazu
i publikuje odpowiadające źródła dla każdego binarium, które wysyła, i to na tym
opiera się źródłowe zobowiązanie GPL i LGPL dla redystrybuowanego obrazu. Obraz
backendu dokłada LibreOffice (MPL-2.0) i Tesseract (Apache-2.0) jako pakiety
Debiana, używane bez modyfikacji jako osobne procesy. SBOM per wydanie zaplanowany
w [#1415](https://github.com/vstorm-co/agenticos/issues/1415) zapisze dokładny
zbiór pakietów każdego obrazu; zanim to nastąpi, inwentarzem tej warstwy są
Dockerfile'e i digesty obrazów bazowych.

## Komponent na AGPL { #the-agpl-component }

Jeden komponent w obrazie backendu jest na copylefcie sieciowym i jest to jedyna
licencja w tym zbiorze, która prosi o coś wdrożenie, a nie tylko nas.

`pymupdf` jest licencjonowany podwójnie: AGPL-3.0-only albo komercyjna licencja
Artifex. Jest domyślnym parserem PDF-ów i jedynym z trzech, który wyciąga osadzone
obrazy do opisania. AGPL jest jednokierunkowo kompatybilny z Apache-2.0: nasz kod
wolno z nim łączyć, a powstały obraz jest wtedy przekazywany na warunkach
AGPL-3.0.

[#1602](https://github.com/vstorm-co/agenticos/issues/1602) ważył porzucenie go na
rzecz LiteParse (Apache-2.0, i tak już zależność), schowanie go za świadome
włączenie i utrzymanie go z nazwanymi warunkami. **Jest utrzymany, a warunki są
nazwane tutaj.** Co to znaczy w praktyce:

- **Uruchamianie niezmodyfikowanego wydania.** Nic się nie należy. AgenticOS jest
  publiczny i na Apache-2.0, więc źródła, na które wskazywałaby oferta z art. 13,
  są już opublikowane.
- **Modyfikowanie platformy i serwowanie jej przez sieć** — przypadek, na który
  produkt self-hosted wprost zaprasza. Art. 13 AGPL-3.0 zobowiązuje takie
  wdrożenie do zaoferowania swoim użytkownikom zmodyfikowanych źródeł całości.
  To jest zobowiązanie, które trzeba przeczytać przed prywatnym forkiem, i to
  o nie zapyta przegląd bezpieczeństwa.
- **Wdrożenie, które nie może przyjąć tych warunków** ma trzy wyjścia: kupić
  komercyjną licencję Artifex, ustawić parser PDF-ów kolekcji na `liteparse`
  i usunąć zależność w prywatnym buildzie albo trzymać swoje zmiany
  nieopublikowane, ale dostępne dla własnych użytkowników, o co art. 13 tak
  naprawdę prosi.

Nic innego w żadnym z obrazów nie niesie copyleftu sięgającego poza własne pliki.

## Otwarte ustalenia { #open-findings }

Każde ma issue; każde zostanie na tej liście, i na początku not, dopóki issue się
nie zamknie i wpis w policy nie przejdzie na `accepted` albo komponentu nie będzie.

Jedno ustalenie zostało zamknięte przez wymianę komponentu, a nie przez jego
przyjęcie. `redis:7-alpine` rozwiązuje się do Redisa 7.4, a od 7.4.0 Redis jest na
RSALv2 albo SSPL-1.0, a nie BSD-3-Clause — żadna z nich nie jest zatwierdzona
przez OSI. Nic przez to nie zostało złamane: obraz pobiera operator, zamiast być
redystrybuowanym stąd, a RSALv2 pozwala uruchamiać Redisa wewnątrz własnej
aplikacji, czyli robić to, co robi ten stos. Ustalenie było takie, że domyślne
`docker compose up` startowało komponent nieotwarty, nic o tym nie mówiąc.

[#1603](https://github.com/vstorm-co/agenticos/issues/1603) wymieniło go na
`valkey/valkey:8-alpine`, fork Redisa 7.2 spod Linux Foundation na BSD-3-Clause.
Valkey mówi tym samym protokołem, więc nazwa usługi, port, schemat URL-i `redis://`
i każde ustawienie `REDIS_*` pozostają bez zmian.

**Runtime `workbench` sandboksa jest budowany na wdrożeniu** z
`sandbox_runtimes.json`: Python, Node, LibreOffice, `poppler-utils` (GPL) i lista
pakietów PyPI rozwiązywana w czasie budowania. Nie jest nigdy publikowany przez
ten projekt, więc nie ma czego redystrybuować, a narzędzia na GPL działają jako
osobne procesy. Jest zapisany jako `deployment-review`: wdrożenie, które
zbudowany obraz jednak opublikuje, jest winne oferty źródeł do niego.

## Usługi hostowane i warunki providerów { #hosted-services-and-provider-terms }

API providera modeli, Logfire, Tavily, Brave, Exa, LlamaParse, Mem0, Daytona,
Google Drive i S3 nie są oprogramowaniem, które ten projekt dystrybuuje, i nie mają
licencji w powyższym sensie. Każde z nich to umowa o świadczenie usług między
wdrożeniem a providerem, zawierana wtedy, gdy administrator zapisze poświadczenie
tego providera w [vaulcie](secrets.md). Warunki, które mają znaczenie dla
przeglądu, to warunki providera: co dzieje się z promptami i dokumentami, które do
niego trafiają, czy trenuje on na nich, gdzie dane są przetwarzane i jak długo są
trzymane.

To jest pytanie o ochronę danych, a nie o licencje, i odpowiada się na nie per
wdrożenie, a nie tutaj. SDK, które rozmawiają z tymi usługami, są zwykłymi
pakietami w notach: klienci Anthropic, OpenAI, Google, Mistral, Cohere, Groq i xAI
są wszyscy na MIT albo Apache-2.0.

## Wagi modeli { #model-weights }

W żadnym z dwóch obrazów nie ma wag modeli. Wdrożenie wybiera modele w
[profilach modeli](models.md); model zamknięty jest osiągany przez API swojego
providera na warunkach tego providera, a model z otwartymi wagami jest pobierany
przez wdrożenie na licencji, którą przypiął mu wydawca. Te licencje różnią się
między sobą bardziej niż licencje oprogramowania i kilka z nich nie jest
otwartoźródłowych w rozumieniu definicji OSI, nawet gdy wagi da się swobodnie
pobrać.

| Rodzina | Licencja, jak opublikowana wraz z wagami | Co sprawdzić przed wyborem |
|---|---|---|
| Qwen 2.5 i 3 (większość rozmiarów), Mistral 7B i Nemo, GPT-OSS, DeepSeek V3 i R1, Phi-4 | Apache-2.0 albo MIT | Tylko atrybucja. Niektóre większe rozmiary Qwen 2.5 niosą zamiast tego licencję Qwen; przeczytaj kartę modelu |
| Llama 3.x | Llama Community License | Nie jest otwartoźródłowa: polityka dopuszczalnego użycia, atrybucja „Built with Llama” i osobna licencja powyżej progu miesięcznych aktywnych użytkowników |
| Gemma | Gemma Terms of Use | Nie jest otwartoźródłowa: polityka zakazanych zastosowań, która spływa na pochodne |
| Mistral Large i niektóre wydania Codestral | Mistral Research License albo licencja komercyjna | Tylko użycie badawcze i niekomercyjne, chyba że wykupiona licencja |

Tabela jest orientacją, a nie dowodem: licencje modeli zmieniają się między
wydaniami, a dokumentem, który rządzi, jest karta modelu od wydawcy. Strona
[jak wybrać model](choosing-models.md#closed-models-or-open-weights) ma
inżynierską stronę tej samej decyzji.

!!! tip "Zapisz decyzję tam, gdzie model jest konfigurowany"

    Opis profilu modelu to dobre miejsce, żeby nazwać licencję, na której wzięto
    wagi, i datę, kiedy to sprawdzono. Jedzie razem z profilem do każdego
    środowiska i do każdego agenta, który go używa.

## Komponenty specyficzne dla klienta { #client-specific-components }

Własny stos wdrożenia dołoży komponenty, których ten inwentarz nie widzi: model,
który wdrożenie hostuje samo, serwery MCP, które podłącza, zarządzaną bazę danych
albo Redisa w miejsce usług z compose, reverse proxy, dostawcę tożsamości. Każdy
potrzebuje tych samych trzech rzeczy, które mają tabele powyżej — komponent,
licencja, zobowiązanie — zanim przegląd wdrożenia będzie kompletny. Domyślne
elementy ścieżki compose są zapisane w `licenses/components.toml` pod
`deployment-review` i `service image`, i tam właśnie należą też własne wiersze
wdrożenia, w jego forku albo w jego repozytorium wdrożeniowym.

## Jak to zostaje prawdą { #keeping-it-true }

Check działa przy każdym pull requeście w jobie `security` i w `make check`, więc
workflow utrzymaniowy to w większości check odmawiający przepuszczenia.

**Zmienia się zależność.** Dependabot albo `make deps-upgrade` rusza lockfile; job
`security` wywala się z `THIRD_PARTY_NOTICES.md is stale`. Uruchom `make licenses`,
przeczytaj diff, zacommituj. Jeśli diff dokłada komponent bez licencji albo taki ze
zbioru do przeglądu, check nazwie wpis w policy do napisania, a pull request
poniesie decyzję obok aktualizacji, która jej potrzebowała.

**Zmienia się licencja.** Komponent przejrzany na jednej licencji po aktualizacji
rozwiązuje się na inną; check mówi `reviewed as X but resolves to Y - review it
again`. Stara decyzja nie przeżywa sama z siebie.

**Zamyka się ustalenie.** Wpis w policy przechodzi z `open` na `accepted` wraz
z `fulfilled_by` albo komponent znika i check prosi o usunięcie wpisu. Zregeneruj
noty; ustalenie schodzi z góry pliku.

**Zmienia się model albo usługa.** Nic w lockfile'ach się nie rusza, więc nic się
nie wywala. Do aktualizacji są tabela modeli powyżej, opis profilu modelu i własne
wiersze komponentów wdrożenia, a tym, co o to prosi, jest checklista wydania.

**Zmienia się obraz.** Nowy tag bazowy, dołożony pakiet Debiana, nowa usługa
compose: `licenses/components.toml` jest edytowany w tej samej zmianie, a
`scripts/docs_drift.py` przypomina, gdy Dockerfile się ruszył, a ta strona nie.

## Checklista wydania { #release-checklist }

Zanim wydanie zostanie wycięte, i jako dowód do niego dołączony:

- [ ] `make licenses-check` przeszedł na commicie wydania; linia werdyktu jest
  w podsumowaniu joba `security`
- [ ] `THIRD_PARTY_NOTICES.md` na tym commicie jest notami tego wydania; oba obrazy
  niosą swoje pliki licencji (`/app/THIRD_PARTY_NOTICES.md` oraz
  `.venv/**/*.dist-info/` i `/app/licenses/texts/` w obrazie backendu;
  `/app/licenses/` we frontendowym, z `NOTICE`, `OFL.txt` i jednym katalogiem na
  pakiet)
- [ ] Otwarte ustalenia w notach to te, które wymienia ta strona, każde z issue,
  które nadal jest tym właściwym
- [ ] `licenses/components.toml` wymienia tagi obrazów i usługi compose, których
  wydanie faktycznie używa
- [ ] Jeśli do katalogu albo do tabeli modeli powyżej dołożono rodzinę modeli, jej
  licencję odczytano z aktualnej karty modelu
- [ ] Gdy będzie już istniał SBOM per wydanie z #1415: jest dołączony do wydania,
  a jego zbiór komponentów zgadza się z notami dla dwóch obrazów

## Podsumowanie { #recap }

- Obrazy niosą około pięciuset pakietów stron trzecich, niemal wszystkie na MIT,
  Apache-2.0 albo BSD; plik licencji każdego pakietu jedzie razem z nim, a
  `THIRD_PARTY_NOTICES.md` jest generowanym indeksem.
- Decyzje mieszkają w `licenses/policy.toml` i `licenses/components.toml`; check
  wywala się na wszystkim, co nie ma decyzji, i na decyzji podjętej o licencji,
  która od tego czasu się zmieniła.
- Otwarte i śledzone jest jedno ustalenie: runtime sandboksa budowany na
  wdrożeniu. Dwa kolejne zostały rozstrzygnięte, a nie zostawione otwarte — AGPL
  PyMuPDF-a, przejrzany i utrzymany, z własną sekcją, oraz obraz Redisa,
  wymieniony na Valkey.
- Wagi modeli i hostowani providerzy są wybierani per wdrożenie na warunkach
  wydawcy albo providera; ta strona mówi, co sprawdzić, a wdrożenie zapisuje, co
  wybrało.
