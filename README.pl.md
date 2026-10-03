<!-- source_sha: 3bf5cdf03c03 -->

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
  <a href="https://vstorm-co.github.io/agenticos/pl/">Dokumentacja</a>
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

AgenticOS to środowisko na własnej infrastrukturze, w którym agenci AI pracują z plikami, wykonują kod i korzystają z firmowych narzędzi oraz wiedzy. Twórz i publikuj agentów w przeglądarce, udostępniaj ich współpracownikom oraz zarządzaj dostępem i wynikami w jednym miejscu.

<a href="docs/assets/screens/light/agent-builder.png">
  <img src="docs/assets/screens/light/agent-builder.png" alt="Builder agenta z instrukcjami, wyborem modelu i opublikowaną wersją." width="100%">
</a>

## Co możesz zrobić

| Dla Twojego zespołu | Co zapewnia AgenticOS |
|---|---|
| [Praca z plikami i kodem](#pracuj-z-plikami-i-kodem) | Analizuj CSV, twórz wykresy i dokumenty, pracuj nad repozytoriami |
| [Agenci wielokrotnego użytku](#twórz-agentów-do-wspólnego-użytku) | Wybieraj modele i narzędzia, publikuj wersje, udostępniaj agentów zespołowi |
| [Wiedza firmowa](#naucz-agentów-sposobu-pracy-zespołu) | Wykorzystuj skills, kontekst i przeszukiwalne dokumenty w wielu agentach |
| [Udostępnianie wyników](#publikuj-wyniki-jako-interaktywne-strony) | Publikuj interaktywne strony ze stałymi linkami i historią wersji |
| [Uruchamianie i nadzór](#śledź-wykonania-koszty-i-zatwierdzenia) | Dostosuj dashboardy, sprawdzaj wykonania, planuj zadania i ustalaj budżety |
| [Dostęp w firmie](#organizuj-zespoły-za-pomocą-ról-i-grup) | Łącz role, grupy działów i logowanie firmowe |

## Szybki start

Na początek potrzebujesz Dockera z Compose i dostępu do dostawcy modelu. Na macOS lub Linuksie uruchom:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

Na Windows uruchom tę samą komendę w WSL2 z włączoną integracją WSL2 w Docker Desktop.
Instalator pyta o dostawcę modelu i klucz, login oraz nazwę organizacji, pobiera opublikowane obrazy
i uruchamia wdrożenie z działającym agentem.

Otwórz **http://localhost:3000** i zaloguj się loginem wybranym podczas instalacji.

**Twój pierwszy agent:** przejdź [poradnik asystenta dokumentów](https://vstorm-co.github.io/agenticos/pl/howto/first-document-agent/), aby wgrać regulamin, zadawać pytania i sprawdzać odpowiedzi w przywołanych źródłach. Następnie przetestuj zaktualizowany dokument. Wyszukiwanie w dokumentach wymaga modelu embeddingów. Inne zadania opisuje poradnik [Zbuduj agenta](https://vstorm-co.github.io/agenticos/pl/first-agent/).

<details>
<summary>Sprawdź instalator lub wybierz inny sposób wdrożenia</summary>

Przeczytaj [instalator](scripts/quickstart.sh) przed uruchomieniem. Aby sprawdzić wymagania bez instalowania:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- --check
```

Ręczną konfigurację Docker Compose, wybór wersji i rozwiązywanie problemów opisuje [instrukcja instalacji](https://vstorm-co.github.io/agenticos/pl/install/).
Pracę nad kodem opisuje [poradnik dla współtwórców](https://vstorm-co.github.io/agenticos/pl/help/).

</details>

## Nagrany przykład integracji

Zobacz, jak agent zamienia brief z Notion w interaktywny **OSS Launch Planner**, korzystając z researchu projektów open source Vstorm na GitHubie: **brief → analiza → wspólny wynik**.

<video src="https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512#t=1" controls playsinline width="100%" poster="docs/assets/screens/oss-launch-planner-poster.webp">
  <img src="docs/assets/screens/oss-launch-planner-poster.webp" alt="Vstorm OSS Launch Planner: wybór odbiorców, rekomendacja projektu i linki do źródeł" width="100%">
</video>

[Obejrzyj skrócony film (37 sekund)](https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512) · [Zobacz zrzut ekranu](docs/assets/screens/oss-launch-planner-poster.webp)

## Twórz, udostępniaj i nadzoruj

### Pracuj z plikami i kodem

Poproś agenta o analizę arkusza, wykres, dokument lub pracę nad repozytorium. Po skonfigurowaniu sandboxa opartego na kontenerach i włączeniu wykonywania komend agent może **czytać i edytować pliki, uruchamiać polecenia powłoki oraz wykonywać kod Pythona i JavaScriptu**. Dołączony workbench zawiera narzędzia do danych, wykresów i dokumentów, w tym LibreOffice.

<a href="docs/assets/screens/light/chat.png">
  <img src="docs/assets/screens/light/chat.png" alt="Istniejąca rozmowa analizująca plik CSV ze sprzedażą, z wykresem przychodów według regionu i wnioskami agenta." width="100%">
</a>

**CSV ze sprzedażą → wykres przychodów i wnioski.** Rozwiń wywołania narzędzi, aby sprawdzić komendy stojące za odpowiedzią, a w panelu plików znajdziesz dane wejściowe i wyniki.

Jeśli używasz [Claude Code](https://code.claude.com/docs/en/overview) lub [Codex](https://developers.openai.com/codex/cli/), praca z plikami i komendami będzie znajoma. AgenticOS przenosi taki sposób pracy do wspólnego środowiska na własnej infrastrukturze, z wiedzą firmową, agentami wielokrotnego użytku i kontrolą dostępu w organizacji. Możliwości agenta zależą od modelu, włączonych narzędzi i instrukcji.

Uruchamiaj sandboxy kontenerowe na własnej infrastrukturze lub skonfiguruj obsługiwany backend zdalny. Dobierz czas życia środowiska i limity wykonania do zadania. [Konfiguracja sandboxów](https://vstorm-co.github.io/agenticos/pl/sandbox/).

<details>
<summary>Zobacz połączenia sandboxów</summary>

<img src="docs/assets/screens/light/sandboxes.png" alt="Połączenia sandboxów z lokalnymi hostami kontenerów, poświadczeniami w sejfie i wyborem środowiska wykonawczego." width="100%">

</details>

### Twórz agentów do wspólnego użytku

Wybierz model, instrukcje i narzędzia w przeglądarce. Opublikuj wersję dla współpracowników; przeglądaj wcześniejsze wersje i przywracaj je w razie potrzeby. Trzymaj agentów do researchu, raportowania, programowania i operacji w jednym katalogu.

<details>
<summary>Zobacz katalog agentów</summary>

<img src="docs/assets/screens/light/agents.png" alt="Katalog agentów z opisami, opublikowanymi agentami i statusem wersji." width="100%">

</details>

Współpracownicy mogą korzystać z opublikowanego agenta w **czacie internetowym, Slacku, Mattermost lub Telegramie**, gdy te kanały są skonfigurowane. Programiści mogą wywoływać go przez API. [Zbuduj agenta](https://vstorm-co.github.io/agenticos/pl/first-agent/) · [Podłącz kanał](https://vstorm-co.github.io/agenticos/pl/channels/).

### Naucz agentów sposobu pracy zespołu

- **Skills** przechowują procedury wielokrotnego użytku: jak przeglądać kod, napisać raport lub zbadać rynek. Utrzymuj je w jednym miejscu i wykorzystuj w wielu agentach.
- **Kontekst** przechowuje stałą wiedzę, np. słownik pojęć, politykę firmy lub styl komunikacji marki. Dodaj go do promptu albo pozwól agentowi czytać go na żądanie.
- **Bazy wiedzy (RAG)** umożliwiają przeszukiwanie wgranych dokumentów. Sprawdzaj status przetwarzania i fragmenty, wybieraj parser lub skonfiguruj synchronizację ze źródeł takich jak Google Drive i S3.

<a href="docs/assets/screens/light/skills.png">
  <img src="docs/assets/screens/light/skills.png" alt="Biblioteka skills z filtrami Design, Engineering, Finance i Research." width="100%">
</a>

[Skills](https://vstorm-co.github.io/agenticos/pl/skills/) · [Kontekst](https://vstorm-co.github.io/agenticos/pl/context/) · [Przetwarzanie dokumentów](https://vstorm-co.github.io/agenticos/pl/file-processing/) · [Źródła synchronizacji](https://vstorm-co.github.io/agenticos/pl/howto/configure-sync-sources/).

<details>
<summary>Zobacz otwarty słownik i kolekcję wiedzy</summary>

<img src="docs/assets/screens/light/context-detail.png" alt="Glossary otwarty w podglądzie, włączony i skonfigurowany do odczytu na żądanie." width="100%">

<img src="docs/assets/screens/light/knowledge-collection.png" alt="Kolekcja wiedzy vstorm z zaindeksowanym dokumentem, parserem i statusem przetwarzania." width="100%">

</details>

### Publikuj wyniki jako interaktywne strony

Agenci mogą publikować raporty, interaktywne porównania i małe dashboardy jako **artefakty**. Wybierz, kto może je otwierać; aktualizacje zachowują ten sam link, a wcześniejsze wersje pozostają dostępne. Poniższy przykład to OSS Launch Planner, zbudowany na podstawie briefu z Notion i researchu na GitHubie.

<a href="docs/assets/screens/light/artifact-detail.png">
  <img src="docs/assets/screens/light/artifact-detail.png" alt="Artefakt OSS Launch Planner z wyborem odbiorców, rekomendacjami projektów i linkami do źródeł." width="100%">
</a>

[Udostępnij artefakt](https://vstorm-co.github.io/agenticos/pl/artifacts/).

<details>
<summary>Zobacz bibliotekę artefaktów</summary>

<img src="docs/assets/screens/light/artifacts.png" alt="Biblioteka artefaktów z podglądami stron, wersjami i ustawieniami widoczności." width="100%">

</details>

### Śledź wykonania, koszty i zatwierdzenia

Dostosuj **dashboard** do swojej pracy: układaj i skaluj widżety, nadaj sekcjom kolory i zapisuj układy. Śledź wykorzystanie, wyniki, zarejestrowane wydatki, zatwierdzenia i zasoby sandboxów. Uprawnienia określają, jakie dane widzi dana osoba.

<a href="docs/assets/screens/light/dashboard.png">
  <img src="docs/assets/screens/light/dashboard.png" alt="Dostosowany dashboard z podsumowaniem wykorzystania, zarejestrowanymi kosztami, trendami wykonań i ich wynikami." width="100%">
</a>

**Activity** pozwala sprawdzać wykonania i wywołania narzędzi, porównywać wersje agentów i eksportować dane. Skonfiguruj zasady zatwierdzania dla obsługiwanych narzędzi, a następnie użyj **rutyn**, aby powtarzać pracę według harmonogramu lub zdarzeń. Część kosztów zależy od danych o zużyciu i cenach dostawcy; usługi zewnętrzne mogą naliczać opłaty osobno.

[Historia wykonań, budżety i zatwierdzenia](https://vstorm-co.github.io/agenticos/pl/governance/) · [Rutyny](https://vstorm-co.github.io/agenticos/pl/triggers/).

<details>
<summary>Zobacz Activity i zasady zatwierdzania</summary>

<img src="docs/assets/screens/light/activity.png" alt="Activity z historią wykonań, statusami, wykorzystaniem modeli i kosztami." width="100%">

Zakres zatwierdzeń zależy od narzędzia i trybu wykonania. W czacie internetowym **Ask about everything** obejmuje również wywołania narzędzi MCP obsługiwane przez runner. [Tryby i ograniczenia zatwierdzeń](https://vstorm-co.github.io/agenticos/pl/governance/#how-much-one-conversation-wants-to-be-asked).

</details>

### Organizuj zespoły za pomocą ról i grup

**Role określają, co ludzie mogą robić. Grupy określają, komu udostępniasz zasoby.** Korzystaj z ról takich jak Builder, Operator, Member i Viewer, a następnie utwórz działy lub grupy robocze, np. **Operations, Engineering, Finance i Research**. Udostępnij grupie agenta, skill, kolekcję, plik kontekstu lub artefakt w jednym kroku. Dostęp przyznany grupie uzupełnia uprawnienia wynikające z roli i indywidualnych nadań.

<a href="docs/assets/screens/light/groups.png">
  <img src="docs/assets/screens/light/groups.png" alt="Grupy organizacji Engineering, Finance, Operations i Research z opisami i zarządzaniem członkostwem." width="100%">
</a>

Wykorzystaj istniejące konta firmowe przez **SSO z OIDC, logowanie katalogowe LDAP lub zintegrowane logowanie Windows przez Kerberos**, po odpowiednim skonfigurowaniu wdrożenia. **Mapowania Directory** łączą zewnętrzne grupy katalogowe z rolą w organizacji i opcjonalną grupą AgenticOS; członkostwo jest uzgadniane przy logowaniu.

[Role i uprawnienia do zasobów](https://vstorm-co.github.io/agenticos/pl/permissions/) · [Grupy, LDAP, Kerberos i mapowania katalogowe](https://vstorm-co.github.io/agenticos/pl/directory/).

<details>
<summary>Zobacz członków organizacji i macierz ról</summary>

<img src="docs/assets/screens/light/members.png" alt="Członkowie organizacji z przypisanymi rolami i zarządzaniem członkostwem." width="100%">

<img src="docs/assets/screens/light/roles.png" alt="Macierz uprawnień porównująca role Owner, Admin, Builder, Operator, Member i Viewer." width="100%">

</details>

## Podłącz aplikacje, których Twój zespół już używa

<img src="docs/assets/integrations/apps-glass.svg" alt="Szesnaście logotypów aplikacji na ciemnych szklanych kafelkach: Google Drive, Gmail, Outlook, Notion, GitHub, Slack, Telegram, Figma, Linear, Airtable, Dropbox, Mattermost, HubSpot, Stripe, Shopify, Supabase." width="1140">

Podłączaj narzędzia przez **MCP**, obok wbudowanych źródeł synchronizacji i kanałów rozmowy. Katalog zawiera wybrane połączenia oraz **ponad 5700 wpisów serwerów MCP** skopiowanych z rejestru. Wpisy to metadane od wydawców; każde połączenie wymaga konfiguracji i sprawdzenia dostępu.

[Synchronizacja Google Drive™](https://vstorm-co.github.io/agenticos/pl/howto/configure-sync-sources/) · [Zdarzenia Gmail](https://vstorm-co.github.io/agenticos/pl/triggers/) · [Narzędzia MCP: Notion, GitHub, Linear i inne](https://vstorm-co.github.io/agenticos/pl/mcp/) · [Kanały rozmowy: Slack, Mattermost, Telegram](https://vstorm-co.github.io/agenticos/pl/channels/).

[Poczta i kalendarz Outlook](https://vstorm-co.github.io/agenticos/pl/mcp/) łączą się przez zewnętrzną usługę MCP, która wymaga osobnego konta i uprawnień.

## Czy AgenticOS pasuje do Twojego zespołu?

Wybierz go, gdy zespół ma powtarzalne zadania związane z dokumentami lub narzędziami, ekspertów utrzymujących instrukcje oraz osobę odpowiedzialną za działanie wdrożenia na własnej infrastrukturze.

Sprawdź go na jednym z własnych zadań. [Porównaj podejścia](https://vstorm-co.github.io/agenticos/pl/about/comparison/) · [Zaplanuj wdrożenie](https://vstorm-co.github.io/agenticos/pl/rollout/).

## Kontroluj wdrożenie, modele i dostęp

**Sovereign oznacza kontrolę nad wdrożeniem, dostawcami modeli, przepływami danych i dostępem do agentów.** AgenticOS jest oprogramowaniem na licencji Apache-2.0, które możesz sprawdzać, modyfikować i utrzymywać. Wybierz modele hostowane lub lokalne przez Ollama i kompatybilne endpointy, takie jak vLLM. [Konfiguracja modeli](https://vstorm-co.github.io/agenticos/pl/models/).

Uruchomienie konsoli na własnej infrastrukturze nie sprawia, że każdy model, parser i narzędzie działa lokalnie. Sprawdź skonfigurowane usługi i dane, które otrzymują. Nadaj uprawnienia do zasobów, zapisz poświadczenia w szyfrowanym sejfie i przetestuj politykę zatwierdzeń włączonych narzędzi.

[Bezpieczeństwo i przepływy danych](https://vstorm-co.github.io/agenticos/pl/security/) · [Uprawnienia](https://vstorm-co.github.io/agenticos/pl/permissions/) · [Sekrety](https://vstorm-co.github.io/agenticos/pl/secrets/) · [Kontrola wykonań i kosztów](https://vstorm-co.github.io/agenticos/pl/governance/).

## Dla programistów i administratorów

Zbudowany z FastAPI, Pydantic AI, PostgreSQL z pgvector, Redis, Prefect i Next.js. Inżynierowie dodają capabilities w typowanym Pythonie; zespoły składają z zarejestrowanych capabilities agentów w konsoli.

[Architektura](https://vstorm-co.github.io/agenticos/pl/architecture/) · [Capabilities](https://vstorm-co.github.io/agenticos/pl/reference/capabilities/) · [API](https://vstorm-co.github.io/agenticos/pl/api/) · [Współtworzenie](https://vstorm-co.github.io/agenticos/pl/help/).

[Analogia systemu operacyjnego](https://vstorm-co.github.io/agenticos/pl/about/) wyjaśnia architekturę. Opcjonalna [aplikacja desktopowa](https://vstorm-co.github.io/agenticos/pl/desktop/) dodaje osobne okno, zwierzaka i skrót do zrzutów ekranu na macOS. [Projekty open source Vstorm](https://github.com/vstorm-co) zawierają biblioteki i narzędzia wokół AgenticOS.

## Licencja

[Apache License 2.0](LICENSE). Zobacz [NOTICE](NOTICE) i [informacje o komponentach zewnętrznych](THIRD_PARTY_NOTICES.md),
aby poznać atrybucje i skład dystrybucji.

## Potrzebujesz pomocy we wdrożeniu agentów na produkcję?

Vstorm wdraża AgenticOS w infrastrukturze klienta, przygotowuje dokumentację, definiuje procesy
i buduje możliwości na zamówienie. Zakres utrzymania i wsparcia ustalamy dla każdej współpracy.

Stworzone z dbałością przez [**Vstorm**](https://vstorm.co) · [Vstorm on GitHub](https://github.com/vstorm-co)
