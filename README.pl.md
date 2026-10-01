<!-- source_sha: 96cce7bd5751 -->

<div align="center">

<img src="docs/assets/amigo-walk.svg" alt="Amigo, zwierzak AgenticOS" width="144">

<h1>AgenticOS</h1>

<p>
  <b>Twórz agentów AI pracujących z dokumentami i narzędziami Twojego zespołu.</b><br>
  Konfiguruj ich w przeglądarce, korzystaj z wyników i śledź działania oraz koszty.
</p>

<p>
  <a href="#zobacz-jak-to-działa">Zobacz demo</a> &middot;
  <a href="#szybki-start">Szybki start</a> &middot;
  <a href="#poznaj-platformę">Poznaj platformę</a> &middot;
  <a href="docs/index.pl.md">Dokumentacja</a>
</p>

<p>
  <a href="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml"><img src="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://github.com/vstorm-co/agenticos/releases"><img src="https://img.shields.io/github/v/release/vstorm-co/agenticos?label=release&color=blue" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-Apache--2.0-blue" alt="Apache-2.0"></a>
  <a href="https://ai.pydantic.dev"><img src="https://img.shields.io/badge/Powered%20by-Pydantic%20AI-E92063?logo=pydantic&logoColor=white" alt="Pydantic AI"></a>
</p>

<p>
  <a href="README.md">English</a> &middot;
  <b>Polski</b> &middot;
  <a href="README.de.md">Deutsch</a> &middot;
  <a href="README.es.md">Español</a>
</p>

</div>

AgenticOS to otwarte oprogramowanie do tworzenia i używania agentów AI, uruchamiane na własnej infrastrukturze.
Agent to asystent AI, któremu powierzasz zadanie, przekazujesz instrukcje i dajesz dostęp do wybranych dokumentów oraz narzędzi.
Może zbadać temat, przeanalizować plik, przygotować raport lub wykonać operację w podłączonej aplikacji.
Wybierasz możliwości i zakres dostępu każdego agenta.

Zespoły konfigurują agentów i wspólne procedury w interfejsie. Programiści rozszerzają platformę
i integrują ją ze swoimi aplikacjami. Administratorzy zarządzają dostępem, wdrożeniem i wykorzystaniem w jednym miejscu.

## Zobacz, jak to działa

**Od briefu w Notion i informacji z GitHuba do interaktywnej strony pomagającej podjąć decyzję.**
W demo agent **Claude Code like** przygotowuje porównanie projektów open source. Użytkownik przełącza
grupy odbiorców na gotowej stronie i tworzy link do udostępnienia. Raport jest **artefaktem**:
wynikiem pracy, który można otworzyć i wykorzystać poza rozmową.

<video src="https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953" controls muted playsinline width="100%" poster="docs/assets/screens/oss-launch-planner-poster.webp">
  <img src="docs/assets/screens/oss-launch-planner-poster.webp" alt="Vstorm OSS Launch Planner: wybór odbiorców, rekomendacja projektu i linki do źródeł" width="100%">
</video>

[Obejrzyj film](https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953) · [Zobacz zrzut ekranu](docs/assets/screens/oss-launch-planner-poster.webp)

*Zmontowane demo z usuniętym czasem oczekiwania. Dane repozytoriów odpowiadają chwili nagrania;
artefakt nie pobiera danych na żywo. Połączenia i możliwości agenta skonfigurowano na potrzeby tego demo.*

## Zacznij od zadania

| Twoje zadanie | Co przekazujesz agentowi | O co możesz poprosić |
|---|---|---|
| Zebranie informacji do decyzji | Brief i dostęp do odpowiednich aplikacji | Porównanie ze źródłami, rekomendacjami i otwartymi pytaniami |
| Analiza arkusza | Plik CSV i pytanie | Obliczenia, wykresy i wynik do pobrania |
| Odpowiedź na podstawie wiedzy firmy | Podręczniki, zasady lub dokumentacja produktów | Odpowiedź z odwołaniami, które można sprawdzić |
| Przygotowanie cyklicznego raportu | Instrukcje, źródła i harmonogram | Nowy raport lub aktualizacja artefaktu po każdym wykonaniu |

To przykłady na początek; włącz potrzebne narzędzia i zweryfikuj wynik swojego zadania.
[Zbuduj pierwszego agenta korzystającego z dokumentów](docs/howto/first-document-agent.pl.md) lub [poznaj więcej zastosowań](docs/use-cases.pl.md).

## Szybki start

Zainstaluj Docker z Compose. Na macOS lub Linuksie uruchom poniższą komendę; na Windows użyj WSL2
z integracją WSL2 w Docker Desktop. Instalator przeprowadzi Cię przez konfigurację dostępu do modelu,
konta i organizacji, a następnie uruchomi środowisko z przykładowym agentem.

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

Otwórz konsolę pod adresem **http://localhost:3000**, zaloguj się skonfigurowanymi danymi i wypróbuj
przykładowego agenta. Następnie dodaj dokument lub podłącz narzędzie do własnego zadania.

<details>
<summary>Sprawdź instalator lub wybierz inny sposób wdrożenia</summary>

Przeczytaj [instalator](scripts/quickstart.sh) przed uruchomieniem. Aby sprawdzić wymagania bez instalowania:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- --check
```

Ręczną konfigurację Docker Compose, wybór wersji i rozwiązywanie problemów opisuje [instrukcja instalacji](docs/install.pl.md).
Pracę nad kodem opisuje [poradnik dla współtwórców](CONTRIBUTING.pl.md).

</details>

Odpowiadasz za utrzymanie wdrożenia. Modele, przetwarzanie dokumentów i podłączone narzędzia mogą korzystać
z usług zewnętrznych, zależnie od konfiguracji. Sprawdź [podział odpowiedzialności](docs/rollout.pl.md) i [przepływy danych](docs/security.pl.md).

## Poznaj platformę

W czacie zlecasz pracę. Pozostałe części środowiska przechowują instrukcje, wiedzę,
połączenia, wyniki i ustawienia kontroli potrzebne do jej powtarzania.

### Skonfiguruj agenta

W **Agents** tworzysz asystenta do zadania, wybierasz model, piszesz instrukcje i włączasz narzędzia.
Gdy jest gotowy do użycia, publikujesz wersję. Możesz przeglądać wcześniejsze wersje i cofnąć zmianę.
[Zbuduj agenta](docs/first-agent.pl.md).

<!-- MEDIA: agent-builder | light + dark; same agent as the demo -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/agent-builder.webp">
  <img src="docs/assets/screens/light/agent-builder.webp" alt="Konfiguracja agenta: instrukcje, wybrany model i opublikowana wersja ze zmianami w szkicu." width="100%">
</picture>

### Naucz go powtarzalnej procedury

**Skills** to zapisane procedury, które agent może wczytać, gdy są potrzebne: jak ocenić ofertę,
sprawdzić zgodność liczb w raporcie lub zastosować styl komunikacji. Zapisz procedurę raz i przypisz ją
agentom, którzy jej potrzebują. [Więcej o skills](docs/skills.pl.md).

<!-- MEDIA: skills | capture light + dark -->
> **Miejsce na zrzut — Skills:** biblioteka i otwarta procedura z czytelnymi krokami.

**Context** przechowuje stałe informacje, np. nazwy produktów, słownik lub zasady komunikacji.
Umieść tu fakty i reguły wspólne dla różnych zadań; wybierz, czy agent otrzymuje je automatycznie,
czy odczytuje na żądanie. [Więcej o kontekście](docs/context.pl.md).

<!-- MEDIA: context | capture light + dark -->
> **Miejsce na zrzut — Context:** otwarty plik kontekstu firmy z treścią i ustawieniami przypisania.

### Udostępnij dokumenty do przeszukiwania

**Knowledge bases** porządkują dokumenty w kolekcje przypisywane agentom. Agent wyszukuje w nich
fragmenty potrzebne do odpowiedzi. Takie podejście jest często nazywane **RAG**, czyli generowaniem
odpowiedzi wspomaganym wyszukiwaniem. [Dodawanie i przetwarzanie dokumentów](docs/file-processing.pl.md).

<!-- MEDIA: knowledge-bases | capture light + dark -->
> **Miejsce na zrzut — Bazy wiedzy:** nazwane kolekcje pokazujące organizację wiedzy zespołu.

Otwórz kolekcję, aby sprawdzić dokumenty i stan ich przetwarzania. Wybierz sposób odczytu
obsługiwanych dokumentów, w tym rozpoznawanie tekstu w skanach (OCR).

<!-- MEDIA: knowledge-collection | capture light + dark -->
> **Miejsce na zrzut — Wnętrze kolekcji:** nazwy dokumentów, stan przetwarzania oraz czytelny podgląd dokumentu lub wynik wyszukiwania.

### Podłącz aplikacje, w których pracujesz

**MCP**, czyli Model Context Protocol, to standard łączenia agentów AI z narzędziami i źródłami danych.
Na stronie **MCP servers** konfigurujesz zgodne połączenia, np. narzędzia Notion i GitHuba użyte w demo.
Dostępne operacje zależą od serwera, danych uwierzytelniających oraz narzędzi włączonych dla agenta.
[Podłącz aplikację](docs/mcp.pl.md).

<!-- MEDIA: mcp-connections | capture light + dark -->
> **Miejsce na zrzut — Połączenia z aplikacjami:** połączone serwery Notion i GitHuba oraz wybrane narzędzia, z ukrytymi danymi uwierzytelniającymi.

### Zachowaj wyniki poza czatem

**Artifacts** to strony tworzone przez agenta: raporty, interaktywne porównania lub niewielkie dashboardy.
Otwierasz je z biblioteki, sprawdzasz wersje i wybierasz, kto ma do nich dostęp. Aktualizacja tego samego
artefaktu zachowuje link do bieżącej strony; rozmowa może odsyłać do konkretnej wersji.

Artefakt pokazuje dane z chwili publikacji. Kolejne wykonanie agenta może je zaktualizować.
[Tworzenie i udostępnianie artefaktów](docs/artifacts.pl.md).

<!-- MEDIA: artifacts | capture light + dark; use the OSS Launch Planner from the video -->
> **Miejsce na zrzut — Artifacts:** biblioteka i otwarty OSS Launch Planner z wyborem odbiorców oraz rekomendacją.

### Sprawdzaj działania i koszty

**Run** to pojedyncze wykonanie agenta. **Activity / Runs** pokazuje jego stan i zapisane zużycie;
otwórz wykonanie, aby przejrzeć rozmowę i wywołania narzędzi. Kontrola budżetu sprawdza zapisane wydatki
przed zapytaniami do modelu; trwające zapytania lub równoległe wykonania mogą przekroczyć limit. [Budżety i historia audytu](docs/governance.pl.md).

<!-- MEDIA: run-detail | capture light + dark; same run as the demo -->
> **Miejsce na zrzut — Szczegóły wykonania:** stan, czas, zapisany koszt i wywołania narzędzi dla zadania z demo.

Dla obsługiwanych operacji narzędzi możesz wymagać zgody człowieka. Prośba o zatwierdzenie pozwala
sprawdzić planowaną operację przed decyzją o jej wykonaniu. Dostęp do agentów i zasobów określają
[role i uprawnienia](docs/permissions.pl.md).

<!-- MEDIA: approval | capture light + dark; real pending operation -->
> **Miejsce na zrzut — Zatwierdzenie:** rzeczywista operacja czekająca na decyzję, z opisem i przyciskami zatwierdzania.

### Zaplanuj powtarzalną pracę

**Routines** uruchamiają agenta według harmonogramu lub w odpowiedzi na skonfigurowane zdarzenie.
Możesz przygotować cotygodniowe podsumowanie lub cykliczny raport. Wykonania korzystają z ustawionego
dostępu i mechanizmów kontroli oraz pozostawiają zapis w historii. [Skonfiguruj rutynę](docs/triggers.pl.md).

<!-- MEDIA: routines | capture light + dark; show an actual scheduled execution -->
> **Miejsce na zrzut — Routines:** harmonogram raportu, ostatnie zakończone wykonanie z harmonogramu i link do wyniku.

## Pracuj razem z zespołem

Korzystaj z konsoli w przeglądarce, udostępnij agenta przez API lub skonfiguruj obsługiwany kanał,
np. Slack, Telegram, Mattermost, stronę agenta albo widget na stronie WWW. [Wybierz kanał](docs/channels.pl.md).
Opcjonalna [aplikacja desktopowa](docs/desktop.pl.md) otwiera konsolę w osobnym oknie, dodając zwierzaka
na pulpicie i skrót do przesyłania zrzutu ekranu do nowego czatu.

Organizacje, uprawnienia do zasobów, sejf z danymi uwierzytelniającymi i dashboardy zużycia pomagają
administratorom zarządzać wdrożeniem. [Zaplanuj wdrożenie](docs/rollout.pl.md).

## Czy AgenticOS pasuje do Twoich potrzeb?

AgenticOS jest przeznaczony dla zespołów, które chcą konfigurować i używać agentów przez przeglądarkę,
korzystając z własnego wdrożenia. Inżynierowie mogą dodawać możliwości i integracje, a osoby odpowiedzialne
za zadania utrzymywać instrukcje, dokumenty i procedury w interfejsie.

Jeśli szukasz usługi zarządzanej, uwzględnij pracę potrzebną do utrzymania własnej platformy. Jeśli potrzebujesz
wyłącznie biblioteki agentowej we własnej aplikacji, rozważ bezpośrednie użycie frameworka. Porównaj opcje
według zadania, sposobu wdrożenia i potrzebnej kontroli w [porównaniu platform](docs/about/comparison.pl.md).

## Dla programistów i administratorów

Platforma korzysta z FastAPI, Pydantic AI, PostgreSQL z pgvector, Redis, Prefect i Next.js.
Konfiguracja agenta wybiera możliwości zarejestrowane w platformie; programiści rozszerzają je w kodzie.

| Zacznij tutaj | Zakres |
|---|---|
| [Architektura](docs/architecture.pl.md) | Usługi, przechowywanie danych i wykonywanie zadań |
| [Możliwości](docs/reference/capabilities.pl.md) | Dostępne narzędzia i konfiguracja |
| [API](docs/api.pl.md) | Integracja z Twoimi aplikacjami |
| [Modele](docs/models.pl.md) | Dostawcy modeli i profile |
| [Bezpieczeństwo](docs/security.pl.md) | Przepływy danych i granice wdrożenia |
| [Testowanie](docs/testing.pl.md) | Zestawy testów i zakres pokrycia |

Zapraszamy do współtworzenia. [Poradnik dla współtwórców](CONTRIBUTING.pl.md) opisuje konfigurację i wymagane kontrole,
a [roadmapa](docs/ROADMAP.md) przedstawia planowane prace.

## Licencja i wsparcie

[Apache License 2.0](LICENSE). Zobacz [NOTICE](NOTICE) i [informacje o komponentach zewnętrznych](THIRD_PARTY_NOTICES.md),
aby poznać atrybucje i skład dystrybucji.

[Vstorm](https://vstorm.co/) rozwija AgenticOS i pomaga we wdrożeniach, integracjach oraz rozwoju na zamówienie.
Zakres wsparcia i utrzymania jest uzgadniany dla każdego projektu.
