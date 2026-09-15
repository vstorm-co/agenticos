---
source_sha: "1ad52431d0bf"
---

# Inwentarz komponentów { #the-component-inventory }

Z czego składa się wdrożenie AgenticOS: części pisane w tym projekcie,
zewnętrzne pakiety, od których zależą, obrazy, w których działają, zasoby, które
dostarczają, oraz modele i usługi podłączane przez operatora później. To czytelna
połowa SBOM-u wydania i odpowiedź na pytanie „co jest w środku”, gdy pada ono
podczas przeglądu bezpieczeństwa, a nie w systemie budowania.

!!! abstract "Co ta strona obejmuje i gdzie się kończy"

    Wszystko do sekcji *Dostarczane zasoby* włącznie jest dostarczane przez ten
    projekt i wyliczone dokładnie — z plików lock i z Dockerfile'i. Wszystko po
    niej — modele, providerzy, serwery MCP, bazy danych, na które wskazuje
    wdrożenie — jest wybierane per wdrożenie, nie jest tu dostarczane i może
    zostać wypisane wyłącznie przez to wdrożenie, które je wybrało. Ostatnia
    sekcja mówi, jak spisać tę drugą połowę; ta strona nie zrobi tego za Ciebie.

Inwentarz odczytywalny maszynowo jest dołączany do każdego wydania jako
`sbom-api.cdx.json` i `sbom-frontend.cdx.json`, w formacie
[CycloneDX](https://cyclonedx.org/) 1.6 JSON. Dowody licencyjne dla każdego
komponentu znajdziesz w
[`THIRD_PARTY_NOTICES.md`](https://github.com/vstorm-co/agenticos/blob/main/THIRD_PARTY_NOTICES.md),
a przegląd tego, do czego te licencje zobowiązują — w [Licencjach i notach
o oprogramowaniu firm trzecich](../licenses.md).

## Wydanie, które opisuje ten inwentarz { #the-release-this-inventory-describes }

Inwentarz bez numeru wersji nie opisuje niczego. Każde wydanie ma własny:
dokumenty SBOM na wydaniu GitHub dla tagu `vX.Y.Z`, wygenerowane z obrazów
opublikowanych pod tym tagiem, oraz tę stronę w postaci, w jakiej była w drzewie
tego tagu. Wdrożenie czytające inwentarz dla wersji, którą uruchamia, powinno
czytać oba z tego samego tagu, a nie z `main`.

| Artefakt | Gdzie jest | Co nazywa jego wersję |
|---|---|---|
| `sbom-api.cdx.json` | zasoby wydania GitHub | tag `v*`, do którego jest dołączony |
| `sbom-frontend.cdx.json` | tam samo | tak samo |
| `ghcr.io/vstorm-co/agenticos-backend` | GHCR | `<version>`, `latest`, `edge`, `sha-<short>` |
| `ghcr.io/vstorm-co/agenticos-frontend` | GHCR | tak samo |
| `THIRD_PARTY_NOTICES.md` | repozytorium, na tym tagu | pliki lock w tym commicie |

## Komponenty pisane w tym projekcie { #components-this-project-writes }

Własne, na licencji Apache-2.0, w tym repozytorium. Nic tutaj nie jest
komponentem firmy trzeciej i nic z tego nie pojawia się w notach.

| Komponent | Gdzie | Czym jest | Dostarczany w |
|---|---|---|---|
| API i platforma | `backend/app` | Aplikacja FastAPI: routes, services, repositories, runner agentów, rejestr capability | `agenticos-backend` |
| Worker w tle | `backend/app/worker` | Runner Prefecta dla ingestii, synchronizacji, sweepów i wyzwalaczy harmonogramu | `agenticos-backend` |
| Migracje | `backend/alembic` | Łańcuch schematu, stosowany przez usługę migracji przed startem API | `agenticos-backend` |
| Wiersz poleceń | `backend/app/commands` | `agenticos cmd …` — bootstrap, doctor, polecenia RAG | `agenticos-backend` |
| Konsola | `frontend/src` | Aplikacja Next.js, którą widzi operator i użytkownik | `agenticos-frontend` |
| Powłoka desktopowa | `desktop/` | Okno Tauri wokół konsoli wdrożenia, budowane per platforma | nie jest obrazem; zobacz [aplikację desktopową](../desktop.md) |
| Strona dokumentacji | `docs/`, `mkdocs.yml` | Ta strona | nie jest dostarczana w żadnym z obrazów |

## Zależności firm trzecich { #third-party-dependencies }

Rozwiązywane z plików lock, a nie z tego, co akurat ma zainstalowana maszyna.
Liczby zmieniają się z każdą zmianą zależności, więc wartością, której warto
ufać, jest ta w pliku not dla wydania, które czytasz.

| Zbiór | Plik lock | Rozwiązywany dla | W notach |
|---|---|---|---|
| Dystrybucje Pythona backendu | `backend/uv.lock` | Linux, obie architektury, `--no-dev` | Tak |
| Pakiety npm frontendu | `frontend/bun.lock` | produkcyjne domknięcie `frontend/package.json` | Tak |
| Narzędzia deweloperskie i dokumentacyjne backendu | `backend/uv.lock`, grupy `dev` i `docs` | maszyna kontrybutora | Nie: nie ma ich w żadnym obrazie |
| `devDependencies` frontendu | `frontend/bun.lock` | maszyna kontrybutora | Nie: nie ma ich w obrazie |
| Crate'y Rusta powłoki desktopowej | `desktop/src-tauri/Cargo.lock` | platforma, dla której budowana jest powłoka | Nie: nie ma ich w żadnym obrazie |

Dwa audyty czytają te pliki lock przy każdym pull requeście. `make audit`
rozwiązuje `backend/uv.lock` i sprawdza go wobec bazy podatności;
`make audit-frontend` uruchamia `bun audit --audit-level=high` na
`frontend/bun.lock`. Oba są w zadaniu `Security Scan` i w `make check`.

## Obrazy uruchomieniowe { #runtime-images }

| Obraz | Baza | Zawiera | Budowany przez |
|---|---|---|---|
| `agenticos-backend` | obraz Pythona oparty na Debianie | API, worker, migracje, CLI, domknięcie zależności backendu, teksty licencji | `backend/Dockerfile` |
| `agenticos-frontend` | obraz Node'a oparty na Debianie | standalone build konsoli, jej produkcyjne domknięcie zależności, fonty, noty per pakiet | `frontend/Dockerfile` |

Oba są budowane dla `amd64` i `arm64`, publikowane do GHCR i skanowane Trivy po
publikacji. Pakiety Debiana instalowane przez każdy obraz są zapisane w
`licenses/components.toml` wraz z ich pozycją licencyjną i pojawiają się
w dokumentach CycloneDX, bo generator czyta opublikowany obraz, a nie drzewo
źródeł.

Usługi, które wdrożenie uruchamia obok tych dwóch — PostgreSQL z pgvector, Redis,
reverse proxy, serwer Prefecta — operator pobiera od ich własnych wydawców. Są
nazwane w plikach compose, nie są tu budowane i nie ma ich w SBOM-ie tego
projektu.

## Dostarczane zasoby { #bundled-assets }

| Zasób | Gdzie | Pochodzenie |
|---|---|---|
| Fonty interfejsu | `frontend/src/app/fonts/` | Inter, Bricolage Grotesque, Geist Mono, wszystkie OFL-1.1 |
| Glify marek i providerów | `frontend/src/components/brand/`, `backend/app/core/catalog/icons/` | Font Awesome, Simple Icons i znaki rysowane ręcznie; źródła nazywa `NOTICE` |
| Katalog serwerów MCP | `backend/app/core/catalog/` | Własne dane tego projektu o serwerach firm trzecich, nie same serwery |
| Domyślne profile modeli | `backend/app/core/catalog/` | Własne dane tego projektu; same modele nigdy nie są dostarczane |

## Modele, providerzy i usługi: połowa należąca do wdrożenia { #models-providers-and-services-the-deployments-half }

Nic z poniższych nie jest częścią wydania i żaden SBOM wygenerowany tutaj nie
może tego wypisać. Każda pozycja jest komponentem działającego systemu i należy
do własnego inwentarza wdrożenia.

- **Providerzy modeli.** Ci z Anthropic, OpenAI, Google, Groq, xAI, Cohere,
  endpointu zgodnego z OpenAI lub lokalnego runtime'u, których wdrożenie
  skonfiguruje, wraz z przypiętymi identyfikatorami modeli. Zobacz
  [modele](../models.md).
- **Wagi modeli.** Lokalny runtime je pobiera; ich licencje przegląda operator,
  a [przegląd licencji](../licenses.md) mówi dlaczego.
- **Serwery MCP.** Procesy firm trzecich lub hostowane endpointy, podłączane per
  organizacja. Katalog nazywa kandydatów; instalacja jest komponentem.
- **Źródła wiedzy i konektory.** Google Drive, S3 i pozostałe, każde jako usługa
  firmy trzeciej osiągana poświadczeniem z vault.
- **Kanały.** Przestrzenie Slacka, Telegrama i Mattermosta, w których wdrożenie
  jest zarejestrowane.
- **Magazyny danych i infrastruktura.** PostgreSQL, Redis, storage obiektowy,
  reverse proxy, host oraz dowolny endpoint obserwowalności odbierający trace'y.

!!! warning "SBOM obrazu to nie inwentarz systemu"

    Dwa dokumenty CycloneDX opisują dwa obrazy. Wdrożenie, które podłącza
    hostowany model, trzy serwery MCP i storage obiektowy, uruchamia komponenty,
    których żaden skan tych obrazów nie zobaczy. Traktowanie SBOM-u wydania jako
    całego inwentarza jest luką, którą ta sekcja ma nazwać.

## Jak inwentarz powstaje i jest utrzymywany { #how-the-inventory-is-produced-and-kept-current }

| Artefakt | Wytwarzany przez | Kiedy |
|---|---|---|
| `sbom-api.cdx.json`, `sbom-frontend.cdx.json` | zadanie `sbom` w `.github/workflows/images.yml`, z opublikowanych manifestów | przy każdej publikacji; dołączany do wydania na tagu `v*` |
| `THIRD_PARTY_NOTICES.md` | `make licenses` | gdy zmienia się plik lock; `make licenses-check` przerywa budowanie, gdy plik jest nieaktualny |
| Ta strona | ręcznie | gdy komponent zostaje dodany, usunięty lub przeniesiony między powyższymi zbiorami |

Lokalnie `make sbom` zapisuje te same dokumenty CycloneDX z drzewa źródeł, a nie
z obrazu. Wymaga zainstalowanego [syfta](https://github.com/anchore/syft),
świadomie nie należy do `make check`, a jego wynik różni się od dokumentów
wydania dokładnie w jednym wartym uwagi punkcie: nie ma warstw obrazu bazowego,
bo nie ma obrazu.

Aby rozszerzyć inwentarz dla wdrożenia, weź SBOM wydania dla uruchamianej wersji,
dodaj komponenty z powyższej sekcji wraz z wersją i dostawcą każdego z nich
i trzymaj to obok własnej konfiguracji wdrożenia. [Przegląd
bezpieczeństwa](../rollout.md) jest miejscem, w którym recenzent klienta o to
poprosi, a [ochrona danych](../data-protection.md) miejscem, w którym spisane są
dane dotykane przez każdy z tych komponentów.
