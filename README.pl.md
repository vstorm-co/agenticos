<!-- source_sha: 832979651f3f -->

<div align="center">

<h1><img src="docs/assets/amigo-walk.svg" alt="Amigo, zwierzak AgenticOS" width="64" valign="middle"> AgenticOS</h1>

<p>
  <strong>Sovereign Agentic AI Layer</strong><br>
  <b>Agenci AI, z których cały zespół może korzystać i których może ulepszać.</b><br>
  Open source. Twórz wspólnych agentów w przeglądarce, na infrastrukturze, którą kontrolujesz.
</p>

<p>
  <a href="#szybki-start">Szybki start</a> &middot;
  <a href="#twórz-udostępniaj-i-nadzoruj">Twórz, udostępniaj i nadzoruj</a> &middot;
  <a href="#czy-agenticos-pasuje-do-twojego-zespołu">Czy to dla nas?</a> &middot;
  <a href="docs/index.pl.md">Dokumentacja</a>
</p>

<p>
  <a href="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml"><img src="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://github.com/vstorm-co/agenticos/releases"><img src="https://img.shields.io/github/v/release/vstorm-co/agenticos?label=release&color=blue" alt="Wydanie"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-Apache--2.0-blue" alt="Apache-2.0"></a>
  <a href="https://ai.pydantic.dev"><img src="https://img.shields.io/badge/Powered%20by-Pydantic%20AI-E92063?logo=pydantic&logoColor=white" alt="Zbudowane na Pydantic AI"></a>
</p>

<p>
  <a href="README.md">English</a> &middot;
  <b>Polski</b> &middot;
  <a href="README.de.md">Deutsch</a> &middot;
  <a href="README.es.md">Español</a>
</p>

</div>

AgenticOS to środowisko na własnej infrastrukturze do tworzenia i uruchamiania wspólnych agentów AI. Określ zadanie agenta, podłącz firmowe dokumenty i narzędzia, a następnie opublikuj go dla zespołu. Inżynierowie rozszerzają jego możliwości; eksperci dziedzinowi utrzymują instrukcje i wiedzę.

<a href="docs/assets/screens/light/agent-builder.webp">
  <img src="docs/assets/screens/light/agent-builder.webp" alt="Builder agenta z instrukcjami, wyborem modelu i opublikowaną wersją." width="100%">
</a>

## Co możesz zrobić

- **Twórz w przeglądarce:** ustaw model, instrukcje, wiedzę i narzędzia agenta, a następnie opublikuj wersję.
- **Pracuj zespołowo:** eksperci utrzymują instrukcje i dokumenty, a współpracownicy otrzymują dostęp do opublikowanego agenta.
- **Udostępniaj wyniki:** publikuj raporty, porównania i dashboardy jako artefakty z kontrolą dostępu.
- **Sprawdzaj i powtarzaj wykonania:** przeglądaj wywołania narzędzi i zapisane koszty w Activity; uruchamiaj agentów według harmonogramu lub zdarzeń.
- **Wybieraj infrastrukturę:** uruchom system u siebie, podłącz modele zewnętrzne lub lokalne i rozszerzaj możliwości w Pythonie.

## Szybki start

Potrzebujesz tylko Dockera z Compose. Na macOS lub Linuksie uruchom:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

Na Windows uruchom tę samą komendę w WSL2 z włączoną integracją WSL2 w Docker Desktop.
Instalator pyta o dostawcę modelu i klucz, login oraz nazwę organizacji, pobiera opublikowane obrazy
i uruchamia wdrożenie z działającym agentem.

Otwórz **http://localhost:3000** i zaloguj się loginem wybranym podczas instalacji.

**Twój pierwszy agent:** przejdź [poradnik asystenta dokumentów](docs/howto/first-document-agent.pl.md), aby wgrać regulamin, zadawać pytania i sprawdzać odpowiedzi w przywołanych źródłach i przetestować zaktualizowany dokument. Wyszukiwanie w dokumentach wymaga modelu embeddingów. Inne zadania opisuje poradnik [Zbuduj agenta](docs/first-agent.pl.md).

<details>
<summary>Sprawdź instalator lub wybierz inny sposób wdrożenia</summary>

Przeczytaj [instalator](scripts/quickstart.sh) przed uruchomieniem. Aby sprawdzić wymagania bez instalowania:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- --check
```

Ręczną konfigurację Docker Compose, wybór wersji i rozwiązywanie problemów opisuje [instrukcja instalacji](docs/install.pl.md).
Pracę nad kodem opisuje [poradnik dla współtwórców](CONTRIBUTING.pl.md).

</details>

## Twórz, udostępniaj i nadzoruj

### Skonfiguruj sposób pracy

Wybierz model, instrukcje i narzędzia w przeglądarce. Opublikuj wersję dla współpracowników; wcześniejsze wersje pozostają dostępne do przeglądania i przywrócenia.

[Bazy wiedzy](docs/file-processing.pl.md) dostarczają dokumenty do wyszukiwania. [Skills](docs/skills.pl.md) przechowują procedury wielokrotnego użytku, a [kontekst](docs/context.pl.md) — wspólne fakty i wytyczne. Aktualizuj te zasoby wraz ze zmianami w pracy.

Podłącz narzędzia takie jak **GitHub, Notion, HubSpot lub Linear** przez [MCP](docs/mcp.pl.md). Katalog łączy wybrane połączenia z **ponad 5700 wpisami serwerów MCP** skopiowanymi z rejestru. Wpisy z rejestru to metadane od wydawców, a nie przetestowane integracje. Każde połączenie wymaga konfiguracji i sprawdzenia dostępu.

### Udostępnij agenta i jego wyniki

Współpracownicy mogą korzystać z opublikowanego agenta w czacie internetowym lub przez skonfigurowane kanały **Slack, Mattermost i Telegram**. Programiści mogą wywoływać go przez API. [Podłącz kanał](docs/channels.pl.md).

Agenci mogą publikować raporty, interaktywne porównania i małe dashboardy jako **artefakty**. Wybierz, kto może je otwierać; aktualizacja tego samego artefaktu zachowuje jego link, a wcześniejsze wersje pozostają dostępne. [Udostępnij artefakt](docs/artifacts.pl.md).

<a href="docs/assets/screens/light/artifacts.webp">
  <img src="docs/assets/screens/light/artifacts.webp" alt="Biblioteka artefaktów z raportami, ustawieniami dostępu i wersjami." width="100%">
</a>

### Sprawdzaj wykonania i powtarzaj przydatne zadania

**Activity** łączy historię wykonań, zatwierdzenia i zarejestrowane wydatki. Przeglądaj wywołania narzędzi, porównuj wersje agentów i eksportuj dane. Część kosztów zależy od danych o zużyciu i cenach dostawcy; usługi zewnętrzne mogą naliczać opłaty osobno. [Ograniczenia rozliczania kosztów](docs/governance.pl.md).

<a href="docs/assets/screens/light/activity.webp">
  <img src="docs/assets/screens/light/activity.webp" alt="Activity z porównaniem wersji i historią wykonań, w tym oczekującym zatwierdzeniem." width="100%">
</a>

Skonfiguruj wymagane zatwierdzenia dla obsługiwanych narzędzi capabilities. W czacie internetowym tryb **Ask about everything** obejmuje również wywołania narzędzi MCP obsługiwane przez runner. Zakres zatwierdzeń zależy od narzędzia i trybu wykonania; samo włączenie połączenia nie wymusza zatwierdzania. [Tryby i ograniczenia zatwierdzeń](docs/governance.pl.md#how-much-one-conversation-wants-to-be-asked).

Gdy zadanie nadaje się do powtarzania, użyj [rutyn](docs/triggers.pl.md), aby uruchamiać agenta według harmonogramu lub zdarzenia. Sprawdź jego narzędzia, limity i politykę zatwierdzeń przed pozostawieniem go bez nadzoru.

## Nagrany przykład integracji

Demo pokazuje, jak brief z Notion po analizie repozytoriów na GitHubie staje się interaktywną stroną ze źródłami. Materiałem są projekty open source Vstorm: istotna sekwencja to **brief → analiza → wspólny wynik**. To demonstracja produktu, a nie badanie efektów wdrożenia u klienta.

<video src="https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512" controls playsinline width="100%" poster="docs/assets/screens/oss-launch-planner-poster.webp">
  <img src="docs/assets/screens/oss-launch-planner-poster.webp" alt="Vstorm OSS Launch Planner: wybór odbiorców, rekomendacja projektu i linki do źródeł" width="100%">
</video>

[Obejrzyj skrócony film (37 sekund)](https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512) · [Zobacz zrzut ekranu](docs/assets/screens/oss-launch-planner-poster.webp)

## Podłącz aplikacje, których Twój zespół już używa

<picture>
  <source media="(prefers-reduced-motion: reduce) and (prefers-color-scheme: dark)" srcset="docs/assets/integrations/connections-dark.png">
  <source media="(prefers-reduced-motion: reduce)" srcset="docs/assets/integrations/connections-light.png">
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/integrations/connections-dark.gif">
  <img src="docs/assets/integrations/connections-light.gif" alt="Ilustracja połączeń AgenticOS z Google Drive, Gmailem, Outlookiem, Notion, GitHubem, Linear, Slackiem, Mattermost i Telegramem." width="960" height="300">
</picture>

[Synchronizacja Google Drive™](docs/howto/configure-sync-sources.pl.md) · [Zdarzenia Gmail](docs/triggers.pl.md) · [Narzędzia MCP: Notion, GitHub, Linear i inne](docs/mcp.pl.md) · [Kanały rozmowy: Slack, Mattermost, Telegram](docs/channels.pl.md).

[Poczta i kalendarz Outlook](docs/mcp.pl.md#outlook-setup) łączą się przez zewnętrzną usługę MCP, która wymaga osobnego konta i uprawnień.

<sub>Google Drive jest znakiem towarowym Google LLC. Nazwy i logotypy wskazują możliwości połączenia, a nie partnerstwa. [Źródła logotypów](docs/assets/integrations/ATTRIBUTION.txt).</sub>

## Czy AgenticOS pasuje do Twojego zespołu?

Wybierz go, gdy zespół ma powtarzalne zadania związane z dokumentami lub narzędziami, ekspertów utrzymujących instrukcje oraz osobę odpowiedzialną za działanie wdrożenia na własnej infrastrukturze.

Sprawdź go na jednym z własnych zadań. [Porównaj podejścia](docs/about/comparison.pl.md) · [Zaplanuj wdrożenie](docs/rollout.pl.md).

## Kontroluj wdrożenie, modele i dostęp

**Sovereign oznacza kontrolę nad wdrożeniem, dostawcami modeli, przepływami danych i dostępem do agentów.** AgenticOS jest oprogramowaniem na licencji Apache-2.0, które możesz sprawdzać, modyfikować i utrzymywać. Wybierz modele hostowane lub lokalne przez Ollama i kompatybilne endpointy, takie jak vLLM. [Konfiguracja modeli](docs/models.pl.md).

Uruchomienie konsoli na własnej infrastrukturze nie sprawia, że każdy model, parser i narzędzie działa lokalnie. Sprawdź skonfigurowane usługi i dane, które otrzymują. Nadaj uprawnienia do zasobów, zapisz poświadczenia w szyfrowanym sejfie i przetestuj politykę zatwierdzeń włączonych narzędzi.

[Bezpieczeństwo i przepływy danych](docs/security.pl.md) · [Uprawnienia](docs/permissions.pl.md) · [Sekrety](docs/secrets.pl.md) · [Kontrola wykonań i kosztów](docs/governance.pl.md).

## Dla programistów i administratorów

Zbudowany z FastAPI, Pydantic AI, PostgreSQL z pgvector, Redis, Prefect i Next.js. Inżynierowie dodają capabilities w typowanym Pythonie; zespoły składają z zarejestrowanych capabilities agentów w konsoli.

[Architektura](docs/architecture.pl.md) · [Capabilities](docs/reference/capabilities.pl.md) · [API](docs/api.pl.md) · [Współtworzenie](CONTRIBUTING.pl.md) · [Plan rozwoju](docs/ROADMAP.md).

[Analogia systemu operacyjnego](docs/about/index.pl.md) wyjaśnia architekturę. Opcjonalna [aplikacja desktopowa](docs/desktop.pl.md) dodaje osobne okno, zwierzaka i skrót do zrzutów ekranu na macOS. [Projekty open source Vstorm](https://github.com/vstorm-co) zawierają biblioteki i narzędzia wokół AgenticOS.

## Licencja

[Apache License 2.0](LICENSE). Zobacz [NOTICE](NOTICE) i [informacje o komponentach zewnętrznych](THIRD_PARTY_NOTICES.md),
aby poznać atrybucje i skład dystrybucji.

## Potrzebujesz pomocy we wdrożeniu agentów na produkcję?

Vstorm wdraża AgenticOS w infrastrukturze klienta, przygotowuje dokumentację, definiuje procesy
i buduje możliwości na zamówienie. Zakres utrzymania i wsparcia ustalamy dla każdej współpracy.

Stworzone z dbałością przez [**Vstorm**](https://vstorm.co) · [Vstorm on GitHub](https://github.com/vstorm-co)
