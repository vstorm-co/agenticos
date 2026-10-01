<!-- source_sha: 049402217d6b -->

<div align="center">

<h1><img src="docs/assets/amigo-walk.svg" alt="Amigo, zwierzak AgenticOS" width="64" valign="middle"> AgenticOS</h1>

<p>
  <b>Otwarta warstwa agentów AI dla Twojej firmy.</b><br>
  Wspólni agenci, wiedza firmowa i automatyzacja pracy — na infrastrukturze, którą kontrolujesz.
</p>

<p>
  <a href="#zobacz-jak-to-działa">Zobacz demo</a> &middot;
  <a href="#szybki-start">Szybki start</a> &middot;
  <a href="#poznaj-warstwę-agentów">Poznaj warstwę agentów</a> &middot;
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

Twórz agentów AI w przeglądarce, podłącz firmową wiedzę i narzędzia oraz udostępniaj agentów zespołowi. Uruchom warstwę agentów na własnej infrastrukturze i wybierz modele chmurowe lub lokalne.

## Zobacz, jak to działa

**Od briefu w Notion i informacji z GitHuba do interaktywnej strony pomagającej podjąć decyzję.**

<video src="https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953" controls muted playsinline width="100%" poster="docs/assets/screens/oss-launch-planner-poster.webp">
  <img src="docs/assets/screens/oss-launch-planner-poster.webp" alt="Vstorm OSS Launch Planner: wybór odbiorców, rekomendacja projektu i linki do źródeł" width="100%">
</video>

[Obejrzyj film](https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953) · [Zobacz zrzut ekranu](docs/assets/screens/oss-launch-planner-poster.webp)

*Zmontowane demo z usuniętym czasem oczekiwania. Dane repozytoriów odpowiadają chwili nagrania;
artefakt nie pobiera danych na żywo. Połączenia i możliwości agenta skonfigurowano na potrzeby tego demo.*

## Poznaj warstwę agentów

<table>
<tr>
<td width="45%" valign="middle">

### Skonfiguruj agenta

W **Agents** tworzysz asystenta do zadania, wybierasz model, piszesz instrukcje i włączasz narzędzia.
Gdy jest gotowy do użycia, publikujesz wersję. Możesz przeglądać wcześniejsze wersje i cofnąć zmianę.
[Zbuduj agenta](docs/first-agent.pl.md).

</td>
<td width="55%">

<!-- MEDIA: agent-builder | light + dark -->

<a href="docs/assets/screens/light/agent-builder.webp">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/agent-builder.webp">
  <img src="docs/assets/screens/light/agent-builder.webp" alt="Konfiguracja agenta: instrukcje, wybrany model i opublikowana wersja ze zmianami w szkicu." width="100%">
</picture>
</a>

</td>
</tr>
<tr>
<td width="45%" valign="middle">

### Naucz go powtarzalnej procedury

**Skills** to zapisane procedury, które agent może wczytać, gdy są potrzebne: jak ocenić ofertę,
sprawdzić zgodność liczb w raporcie lub zastosować styl komunikacji. Zapisz procedurę raz i przypisz ją
agentom, którzy jej potrzebują. [Więcej o skills](docs/skills.pl.md).

</td>
<td width="55%">

<!-- MEDIA: skills | light + dark -->

<a href="docs/assets/screens/light/skill-detail.webp">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/skill-detail.webp">
  <img src="docs/assets/screens/light/skill-detail.webp" alt="Procedura artifact-pages z instrukcjami i szablonami stron." width="100%">
</picture>
</a>

</td>
</tr>
<tr>
<td width="45%" valign="middle">

### Wspólny kontekst

**Context** przechowuje stałe informacje, np. nazwy produktów, słownik lub zasady komunikacji.
Umieść tu fakty i reguły wspólne dla różnych zadań; wybierz, czy agent otrzymuje je automatycznie,
czy odczytuje na żądanie. [Więcej o kontekście](docs/context.pl.md).

</td>
<td width="55%">

<!-- MEDIA: context | light + dark -->

<a href="docs/assets/screens/light/context-detail.webp">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/context-detail.webp">
  <img src="docs/assets/screens/light/context-detail.webp" alt="Podgląd treści słownika z trybem linked do odczytu na żądanie." width="100%">
</picture>
</a>

</td>
</tr>
<tr>
<td width="45%" valign="middle">

### Udostępnij dokumenty do przeszukiwania

**Knowledge bases** porządkują dokumenty w kolekcje przypisywane agentom. Agent wyszukuje w nich
fragmenty potrzebne do odpowiedzi. Takie podejście jest często nazywane **RAG**, czyli generowaniem
odpowiedzi wspomaganym wyszukiwaniem. [Dodawanie i przetwarzanie dokumentów](docs/file-processing.pl.md).

</td>
<td width="55%">

<!-- MEDIA: knowledge-bases | light + dark -->

<a href="docs/assets/screens/light/knowledge-bases.webp">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/knowledge-bases.webp">
  <img src="docs/assets/screens/light/knowledge-bases.webp" alt="Bazy wiedzy z kolekcjami osobistymi i organizacji." width="100%">
</picture>
</a>

</td>
</tr>
<tr>
<td width="45%" valign="middle">

### Podłącz aplikacje, w których pracujesz

**MCP**, czyli Model Context Protocol, to standard łączenia agentów AI z narzędziami i źródłami danych.
Na stronie **MCP servers** konfigurujesz zgodne połączenia, np. narzędzia Notion i GitHuba użyte w demo.
Dostępne operacje zależą od serwera, danych uwierzytelniających oraz narzędzi włączonych dla agenta.
[Podłącz aplikację](docs/mcp.pl.md).

</td>
<td width="55%">

<!-- MEDIA: mcp-connections | light + dark -->

<a href="docs/assets/screens/light/mcp-connections.webp">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/mcp-connections.webp">
  <img src="docs/assets/screens/light/mcp-connections.webp" alt="Połączone serwery MCP, w tym GitHub i Notion." width="100%">
</picture>
</a>

</td>
</tr>
<tr>
<td width="45%" valign="middle">

### Zachowaj wyniki poza czatem

**Artifacts** to strony tworzone przez agenta: raporty, interaktywne porównania lub niewielkie dashboardy.
Otwierasz je z biblioteki, sprawdzasz wersje i wybierasz, kto ma do nich dostęp. Aktualizacja tego samego
artefaktu zachowuje link do bieżącej strony; rozmowa może odsyłać do konkretnej wersji.

Artefakt pokazuje dane z chwili publikacji. Kolejne wykonanie agenta może je zaktualizować.
[Tworzenie i udostępnianie artefaktów](docs/artifacts.pl.md).

</td>
<td width="55%">

<!-- MEDIA: artifacts | light + dark -->

<a href="docs/assets/screens/light/artifact-detail.webp">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/artifact-detail.webp">
  <img src="docs/assets/screens/light/artifact-detail.webp" alt="OSS Launch Planner z demo z wyborem odbiorców i rekomendacją." width="100%">
</picture>
</a>

</td>
</tr>
<tr>
<td width="45%" valign="middle">

### Zatwierdzanie przez człowieka

Dla obsługiwanych operacji narzędzi możesz wymagać zgody człowieka. Prośba o zatwierdzenie pozwala
sprawdzić planowaną operację przed decyzją o jej wykonaniu. Dostęp do agentów i zasobów określają
[role i uprawnienia](docs/permissions.pl.md).

</td>
<td width="55%">

<!-- MEDIA: approval | light + dark -->

<a href="docs/assets/screens/light/approval.webp">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/approval.webp">
  <img src="docs/assets/screens/light/approval.webp" alt="Oczekująca operacja narzędzia z argumentami i przyciskami zatwierdzania." width="100%">
</picture>
</a>

</td>
</tr>
<tr>
<td width="45%" valign="middle">

### Zaplanuj powtarzalną pracę

**Routines** uruchamiają agenta według harmonogramu lub w odpowiedzi na skonfigurowane zdarzenie.
Możesz przygotować cotygodniowe podsumowanie lub cykliczny raport. Wykonania korzystają z ustawionego
dostępu i mechanizmów kontroli oraz pozostawiają zapis w historii. [Skonfiguruj rutynę](docs/triggers.pl.md).

</td>
<td width="55%">

<!-- MEDIA: routines | capture light + dark; show an actual scheduled execution -->
> **Miejsce na zrzut — Routines:** harmonogram raportu, ostatnie zakończone wykonanie z harmonogramu i link do wyniku.

</td>
</tr>
</table>

<details>
<summary>Więcej widoków i szczegóły wykonania</summary>

<a href="docs/assets/screens/light/skills.webp">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/skills.webp">
  <img src="docs/assets/screens/light/skills.webp" alt="Biblioteka Skills z procedurami do wielokrotnego użycia." width="100%">
</picture>
</a>

<a href="docs/assets/screens/light/context.webp">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/context.webp">
  <img src="docs/assets/screens/light/context.webp" alt="Biblioteka Context ze współdzielonymi słownikami." width="100%">
</picture>
</a>

<!-- MEDIA: knowledge-collection | light + dark; supplementary view -->

<a href="docs/assets/screens/light/knowledge-collection.webp">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/knowledge-collection.webp">
  <img src="docs/assets/screens/light/knowledge-collection.webp" alt="Kolekcja vstorm z poprawnie przetworzonym dokumentem adding_features.md." width="100%">
</picture>
</a>

<a href="docs/assets/screens/light/artifacts.webp">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/artifacts.webp">
  <img src="docs/assets/screens/light/artifacts.webp" alt="Biblioteka artefaktów z zapisanymi raportami i wersjami." width="100%">
</picture>
</a>

### Sprawdzaj działania i koszty

**Run** to pojedyncze wykonanie agenta. **Activity / Runs** pokazuje jego stan i zapisane zużycie;
otwórz wykonanie, aby przejrzeć rozmowę i wywołania narzędzi. Kontrola budżetu sprawdza zapisane wydatki
przed zapytaniami do modelu; trwające zapytania lub równoległe wykonania mogą przekroczyć limit. [Budżety i historia audytu](docs/governance.pl.md).

<!-- MEDIA: run-detail | capture light + dark; same run as the demo -->
> **Miejsce na zrzut — Szczegóły wykonania:** stan, czas, zapisany koszt i wywołania narzędzi dla zadania z demo.

</details>

## Zbuduj wspólny sposób pracy z AI

Przy cyklicznym raporcie zespół może podzielić pracę:

1. **Ekspert określa sposób wykonania:** utrzymuje instrukcje, procedury i wiedzę źródłową.
2. **Osoba konfigurująca udostępnia agenta:** podłącza narzędzia, publikuje wersję i nadaje współpracownikom dostęp.
3. **Współpracownicy korzystają z wyników:** uruchamiają agenta, sprawdzają odpowiedź i udostępniają artefakt z odpowiednimi ustawieniami dostępu.

Agent i zapisane sposoby pracy pozostają zasobem organizacji. Zespół pracuje w przeglądarce;
programiści mogą podłączać systemy wewnętrzne. [Skonfiguruj dostęp zespołu](docs/permissions.pl.md).


Korzystaj z opublikowanych agentów w czacie lub obsługiwanych kanałach, np. Slack, Telegram i Mattermost,
albo przez API, stronę agenta lub widget na stronie. [Poznaj kanały](docs/channels.pl.md).

## Szybki start

Zainstaluj Docker z Compose. Na macOS lub Linuksie uruchom poniższą komendę; na Windows użyj WSL2
z integracją WSL2 w Docker Desktop. Instalator przeprowadzi Cię przez konfigurację dostępu do modelu,
konta i organizacji, a następnie uruchomi środowisko z przykładowym agentem.

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

Otwórz konsolę pod adresem **http://localhost:3000** i zaloguj się skonfigurowanymi danymi.

### Wypróbuj pierwsze zadanie

W **Chat** wybierz agenta **Getting Started** i wklej ten fikcyjny brief. Dostęp do modelu musi być
skonfigurowany; to ćwiczenie nie wymaga połączenia z Notion ani GitHubem.

```text
Odpowiedz po polsku. Zamień ten brief w listę zadań przed premierą. Użyj tylko podanych faktów.
Dla każdego zadania podaj osobę odpowiedzialną, termin i brakujące informacje.
Nie wymyślaj dat ani odpowiedzialności.

Brief:
- Webinar dla klientów odbędzie się 15 października.
- Maya odpowiada za landing page; ma być gotowy do 8 października.
- Leo odpowiada za demo, ale nie ustalono terminu jego przeglądu.
- Zaproszenia trzeba wysłać do 10 października; nie wyznaczono odpowiedzialnej osoby.
```

**Sprawdź wynik:** przy landing page powinny pojawić się Maya i 8 października; przy demo —
brak terminu przeglądu; przy zaproszeniach — brak odpowiedzialnej osoby. Następnie użyj własnego briefu lub
[skonfiguruj agenta z narzędziami i wiedzą firmy](docs/first-agent.pl.md).

<details>
<summary>Sprawdź instalator lub wybierz inny sposób wdrożenia</summary>

Przeczytaj [instalator](scripts/quickstart.sh) przed uruchomieniem. Aby sprawdzić wymagania bez instalowania:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- --check
```

Ręczną konfigurację Docker Compose, wybór wersji i rozwiązywanie problemów opisuje [instrukcja instalacji](docs/install.pl.md).
Pracę nad kodem opisuje [poradnik dla współtwórców](CONTRIBUTING.pl.md).

</details>

## Kontroluj wdrożenie, modele i dostęp

**Uruchamiaj na własnej infrastrukturze.** Kod AgenticOS na licencji Apache-2.0 możesz przeglądać,
modyfikować i utrzymywać. Wybierz dostawcę modeli w chmurze lub modele lokalne przez Ollama
i zgodne endpointy, np. vLLM. Możliwości i wymagania sprzętowe zależą od wybranego modelu.
[Konfiguracja modeli](docs/models.pl.md).

**Określ, co wolno agentowi.** Skonfiguruj uprawnienia do zasobów, przechowuj dane uwierzytelniające
w sejfie i wymagaj zatwierdzenia przez człowieka dla obsługiwanych działań narzędzi.
[Kontrola dostępu](docs/permissions.pl.md) · [Sekrety](docs/secrets.pl.md).

**Sprawdzaj działania i wydatki.** Run to pojedyncze wykonanie agenta. Przeglądaj wywołania narzędzi,
zapisane zużycie oraz rejestr audytowy działań administracyjnych. Budżety sprawdzają zapisane wydatki
przed żądaniami do modelu; żądania trwające lub równoległe mogą przekroczyć limit.
[Kontrola wykonań i kosztów](docs/governance.pl.md).

[Własny hosting](docs/rollout.pl.md) oznacza odpowiedzialność za wdrożenie, aktualizacje i kopie zapasowe. Zewnętrzne modele,
parsery, embeddingi, narzędzia i tracing nadal mogą wysyłać dane poza Twoją infrastrukturę.
Skonfiguruj każdy element zgodnie z wymaganiami dotyczącymi danych.
[Bezpieczeństwo i przepływy danych](docs/security.pl.md).

<details>
<summary>Dokąd trafiają Twoje dane</summary>

| Element | O czym decydujesz |
|---|---|
| Aplikacja i dane | Utrzymujesz aplikację, bazę danych i skonfigurowany magazyn plików; wybierasz miejsce działania i sposób wykonywania kopii zapasowych |
| Modele językowe | Dostawca w chmurze otrzymuje kontekst wysłany do modelu; wybierz lokalny endpoint, jeśli to przetwarzanie ma pozostać w Twojej infrastrukturze |
| Przetwarzanie i wyszukiwanie dokumentów | Sprawdź osobno parsery i dostawców embeddingów: lokalny model czatu nie sprawia, że parser w chmurze lub zdalne embeddingi stają się lokalne |
| Narzędzia i kanały | Włączone integracje wymieniają dane potrzebne do wywołań; podłączone kanały otrzymują wysyłane przez nie odpowiedzi |
| Obserwowalność | Opcjonalny tracing może eksportować dane wykonań; sprawdź ustawienia całego wdrożenia i poszczególnych agentów |

[Sprawdź granice przepływu danych](docs/security.pl.md#what-leaves-the-deployment) ·
[Wybierz przetwarzanie dokumentów](docs/file-processing.pl.md).

</details>

## Czy AgenticOS pasuje do Twojej firmy?

Wybierz AgenticOS, jeśli firma potrzebuje wspólnych agentów, wiedzy i automatyzacji oraz kontroli
nad kodem, modelami i wdrożeniem. Twój zespół utrzymuje instalację; Vstorm może pomóc we wdrożeniu
i wsparciu. Jeśli potrzebujesz tylko biblioteki agentów w istniejącej aplikacji, zacznij od frameworka.
Jeśli szukasz usługi w pełni zarządzanej, uwzględnij odpowiedzialność za utrzymanie w porównaniu.

Porównaj podejście z [Dify](docs/about/dify.pl.md), [Viktor](docs/about/viktor.pl.md)
i [Wonderful](docs/about/wonderful.pl.md) lub skorzystaj z [porównania rozwiązań](docs/about/comparison.pl.md),
aby wybrać według zadania, własności i potrzebnej kontroli.

<details>
<summary>Pytania o warstwę agentów</summary>

### Czy AgenticOS to AI agent harness?

AgenticOS udostępnia AI agent harness z interfejsem dla zespołu: wykonywanie zadań przez model,
narzędzia, skills, kontekst i mechanizmy kontroli konfigurowane w przeglądarce. Programiści dodają
możliwości w kodzie, a zespoły konfigurują je i używają. Sposób wykonywania zadań opisuje
[architektura](docs/architecture.pl.md).

### Czy mogę stworzyć agenta w stylu Claude Code do zadań biznesowych?

Możesz skonfigurować agenta do wieloetapowej pracy z plikami, narzędziami i delegowaniem zadań. Dostępne działania zależą od włączonych możliwości i obsługi przez model.
AgenticOS to niezależny projekt z własnym środowiskiem wykonawczym i wyborem modeli.
Zobacz [porównanie z Claude Code](docs/about/claude-code.pl.md).

### Co mogą współdzielić członkowie zespołu?

Zespoły mogą współdzielić agentów, skills, kontekst, kolekcje wiedzy i artefakty zgodnie z uprawnieniami
do zasobów. Wspólny agent może obsługiwać różne osoby, a udostępniony artefakt daje im wynik dostępny
poza czatem.

</details>

## Dla programistów i administratorów

AgenticOS korzysta z FastAPI, Pydantic AI, PostgreSQL z pgvector, Redis, Prefect i Next.js.
Konfiguracja agenta wybiera możliwości zarejestrowane w środowisku wykonawczym; programiści rozszerzają je w kodzie.

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
