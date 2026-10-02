<!-- source_sha: ae331dd9e708 -->

<div align="center">

<h1><img src="docs/assets/amigo-walk.svg" alt="Amigo, zwierzak AgenticOS" width="64" valign="middle"> AgenticOS</h1>

<p>
  <b>Daj agentom AI pracę w swojej firmie.</b><br>
  Otwarta warstwa agentów AI: wspólni agenci, wiedza firmowa i automatyzacja — na infrastrukturze, którą kontrolujesz.
</p>

<p>
  <a href="#zobacz-jak-to-działa">Obejrzyj demo</a> &middot;
  <a href="#szybki-start">Szybki start</a> &middot;
  <a href="#poznaj-warstwę-agentów">Poznaj warstwę agentów</a> &middot;
  <a href="#dlaczego-system-operacyjny">Dlaczego OS</a> &middot;
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

Daj agentowi brief, swoje dokumenty i narzędzia. Zbiera informacje, pisze raport i publikuje stronę, którą zespół może otworzyć. Instrukcje, uprawnienia i każde wykonanie zostają w jednym miejscu, na modelach chmurowych lub lokalnych.

<h3 align="center">🔌 5700+ integracji przez MCP &nbsp;·&nbsp; 🤝 Wspólni agenci i wiedza<br>
📊 Wbudowane observability &nbsp;·&nbsp; 🏠 Własna infrastruktura</h3>

## Zobacz, jak to działa

**Od briefu w Notion i informacji z GitHuba do interaktywnej strony pomagającej podjąć decyzję.**

Agent czyta brief w Notion, sprawdza kandydujące repozytoria na GitHubie i publikuje artefakt,
który dla każdej grupy odbiorców poleca jeden projekt, ze źródłami.

<video src="https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512" controls playsinline width="100%" poster="docs/assets/screens/oss-launch-planner-poster.webp">
  <img src="docs/assets/screens/oss-launch-planner-poster.webp" alt="Vstorm OSS Launch Planner: wybór odbiorców, rekomendacja projektu i linki do źródeł" width="100%">
</video>

<details>
<summary>Film się nie wyświetla? Otwórz animowany podgląd</summary>

<a href="https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512">
  <img src="docs/assets/screens/oss-launch-planner-preview.gif" alt="Vstorm OSS Launch Planner: wybór odbiorców, rekomendacja projektu i linki do źródeł" width="100%">
</a>

*Animowany podgląd przyspieszony 2×. Kliknij, aby obejrzeć 37-sekundowy film z dźwiękiem w normalnym tempie.*

</details>

[Obejrzyj skrócony film (37 sekund)](https://github.com/user-attachments/assets/1d6bba29-3bfe-4c86-bda3-52ce2b0aa512) · [Zobacz zrzut ekranu](docs/assets/screens/oss-launch-planner-poster.webp)

## Szybki start

Potrzebujesz tylko Dockera z Compose. Na macOS lub Linuksie uruchom:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

Na Windows uruchom tę samą komendę w WSL2 z włączoną integracją WSL2 w Docker Desktop.
Instalator pyta o dostawcę modelu i klucz, login oraz nazwę organizacji, pobiera opublikowane obrazy
i uruchamia wdrożenie z działającym agentem.

Otwórz **http://localhost:3000** i zaloguj się wybranym loginem. Przy wartościach domyślnych
to `admin@example.com` / `admin123`.

### Wypróbuj pierwsze zadanie

W **Chat** wybierz agenta **Getting Started** i wklej ten fikcyjny brief. Nie wymaga on połączenia
z Notion ani GitHubem.

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
brak terminu przeglądu; przy zaproszeniach — brak odpowiedzialnej osoby. Potem otwórz **Activity**: wykonanie
już tam jest, z modelem, tokenami, czasem i kosztem. Następnie użyj własnego briefu lub
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

## 💬 Agenci tam, gdzie już pracuje Twój zespół

<p align="center">
  <a href="docs/channels.pl.md"><img src="docs/assets/channels/slack.svg" alt="Slack" width="176" height="64"></a>
  <a href="docs/channels.pl.md"><img src="docs/assets/channels/mattermost.svg" alt="Mattermost" width="176" height="64"></a>
  <a href="docs/channels.pl.md"><img src="docs/assets/channels/telegram.svg" alt="Telegram" width="176" height="64"></a>
</p>

Udostępnij opublikowanego agenta w **Slacku, Mattermost lub Telegramie**. Zespół prosi o pomoc w narzędziach, których już używa, a agent odpowiada ze swoimi instrukcjami, wiedzą i narzędziami. `@mention` działa jako osoba, która wysłała wiadomość, a nie jako bot.

Ten sam opublikowany agent odpowiada też w czacie, w widgecie na stronie, na stronie agenta i we własnej aplikacji przez API, z jednym zestawem limitów i jedną historią wykonań.

[Podłącz Slack, Mattermost i pozostałe kanały](docs/channels.pl.md).

## Poznaj warstwę agentów

Wszystko poniżej działa w konsoli w przeglądarce; nic z tego nie wymaga kodu.

<table>
<tr>
<td colspan="2" valign="top">

### 📄 Zachowaj wyniki poza czatem

**Artifacts** to strony tworzone przez agenta: raporty, interaktywne porównania lub niewielkie dashboardy.
Otwierasz je z biblioteki, sprawdzasz wersje i wybierasz, kto ma do nich dostęp. Aktualizacja tego samego
artefaktu zachowuje jego link; rozmowa może odsyłać do konkretnej wersji. [Tworzenie i udostępnianie artefaktów](docs/artifacts.pl.md).

<a href="docs/assets/screens/light/artifacts.webp">
  <img src="docs/assets/screens/light/artifacts.webp" alt="Biblioteka artefaktów z zapisanymi raportami i wersjami." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🤖 Skonfiguruj agenta

W **Agents** tworzysz asystenta do zadania, wybierasz model, piszesz instrukcje i włączasz narzędzia.
Gdy jest gotowy do użycia, publikujesz wersję. Każda wcześniejsza wersja pozostaje do wglądu, a powrót do niej to jedno kliknięcie.
[Zbuduj agenta](docs/first-agent.pl.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/agent-builder.webp">
  <img src="docs/assets/screens/light/agent-builder.webp" alt="Edytor agenta z instrukcjami, wybranym modelem i aktualnie opublikowaną wersją." width="100%">
</a>

</td>
</tr>
<tr>
<td colspan="2" valign="top">

### 🔌 5700+ integracji przez MCP

Podłącz agentów do narzędzi, których firma już używa: **GitHub, Notion, HubSpot, Linear i n8n**.
**MCP** (Model Context Protocol) to standard, dzięki któremu agenci korzystają z zewnętrznych narzędzi i źródeł danych.

Przeszukuj katalog po nazwie lub dodaj zgodny serwer przez URL.
Podłącz potrzebne usługi i wybierz narzędzia dostępne dla każdego agenta. [Podłącz swoje narzędzia](docs/mcp.pl.md).

<a href="docs/assets/screens/light/mcp-catalog.webp">
  <img src="docs/assets/screens/light/mcp-catalog.webp" alt="Katalog MCP z GitHubem, Notion, Slackiem i innymi usługami oraz stanem połączeń." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🧩 Naucz go powtarzalnej procedury

**Skills** to zapisane procedury, które agent może wczytać, gdy są potrzebne: jak ocenić ofertę,
sprawdzić zgodność liczb w raporcie lub zastosować styl komunikacji. Zapisz procedurę raz i przypisz ją
agentom, którzy jej potrzebują. Po edycji obowiązuje od następnej odpowiedzi, bez wydania. [Więcej o skills](docs/skills.pl.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/skill-detail.webp">
  <img src="docs/assets/screens/light/skill-detail.webp" alt="Procedura artifact-pages z instrukcjami i szablonami stron." width="100%">
</a>

</td>
</tr>
<tr>
<td colspan="2" valign="top">

### 📚 Udostępnij dokumenty do przeszukiwania

**Knowledge bases** porządkują dokumenty w kolekcje przypisywane agentom. Agent wyszukuje w nich
fragmenty potrzebne do odpowiedzi. Takie podejście jest często nazywane **RAG**, czyli generowaniem
odpowiedzi wspomaganym wyszukiwaniem. Czytnik PDF, podział na fragmenty i OCR wybierasz dla każdej kolekcji.
[Dodawanie i przetwarzanie dokumentów](docs/file-processing.pl.md).

<a href="docs/assets/screens/light/knowledge-bases.webp">
  <img src="docs/assets/screens/light/knowledge-bases.webp" alt="Bazy wiedzy z kolekcjami osobistymi i organizacji." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🧠 Wspólny kontekst

**Context** przechowuje stałe informacje, np. nazwy produktów, słownik lub zasady komunikacji.
Umieść tu fakty i reguły wspólne dla różnych zadań; wybierz, czy agent otrzymuje je automatycznie,
czy odczytuje na żądanie. [Więcej o kontekście](docs/context.pl.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/context-detail.webp">
  <img src="docs/assets/screens/light/context-detail.webp" alt="Słownik w podglądzie, w trybie powiązanym do odczytu na żądanie." width="100%">
</a>

</td>
</tr>
<tr>
<td colspan="2" valign="top">

### 📊 Wbudowane observability: co działało i ile kosztowało

**Activity** łączy historię wykonań, zatwierdzenia i wydatki. Każde wykonanie zapisuje stan, model,
tokeny, czas i koszt. Filtruj po agencie, osobie lub wersji, porównuj wersje i eksportuj dane do CSV.
Otwórz wykonanie, aby zobaczyć rozmowę i każde wywołanie narzędzia.
[Poznaj Activity i kontrolę kosztów](docs/governance.pl.md).

<a href="docs/assets/screens/light/activity.webp">
  <img src="docs/assets/screens/light/activity.webp" alt="Activity z porównaniem wersji agenta i przefiltrowaną historią wykonań: stan, tokeny, czas i zapisany koszt." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### 🛡️ Zatwierdzanie przez człowieka

Wszystko, co wysyła, zapisuje lub zmienia coś na zewnątrz, może czekać na człowieka. Prośba o zatwierdzenie
pokazuje planowaną operację i jej argumenty, a działanie wykonuje się dopiero po zgodzie.
Dostęp do agentów i zasobów określają [role i uprawnienia](docs/permissions.pl.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/approval.webp">
  <img src="docs/assets/screens/light/approval.webp" alt="Oczekujące działanie narzędzia z argumentami i przyciskami zatwierdzenia." width="100%">
</a>

</td>
</tr>
<tr>
<td width="30%" valign="middle">

### ⏱️ Zaplanuj powtarzalną pracę

**Routines** uruchamiają agenta według harmonogramu lub w odpowiedzi na zdarzenie: poniedziałkowe
podsumowanie, cykliczny raport. Wykonanie rutyny ma te same limity i ten sam zapis co wszystko, o co poprosił człowiek.
[Skonfiguruj rutynę](docs/triggers.pl.md).

</td>
<td width="70%">

<a href="docs/assets/screens/light/routines.webp">
  <img src="docs/assets/screens/light/routines.webp" alt="Edytor harmonogramu z cotygodniowym powtarzaniem w poniedziałek o 06:00 UTC i podglądem wiadomości dla agenta." width="100%">
</a>

</td>
</tr>
</table>

<details>
<summary>Więcej widoków</summary>

<a href="docs/assets/screens/light/skills.webp">
  <img src="docs/assets/screens/light/skills.webp" alt="Biblioteka skills z procedurami wielokrotnego użytku." width="100%">
</a>

<a href="docs/assets/screens/light/context.webp">
  <img src="docs/assets/screens/light/context.webp" alt="Biblioteka kontekstu ze wspólnymi plikami słownika." width="100%">
</a>

<a href="docs/assets/screens/light/knowledge-collection.webp">
  <img src="docs/assets/screens/light/knowledge-collection.webp" alt="Kolekcja vstorm z poprawnie przetworzonym plikiem adding_features.md." width="100%">
</a>

<a href="docs/assets/screens/light/artifact-detail.webp">
  <img src="docs/assets/screens/light/artifact-detail.webp" alt="OSS Launch Planner z demo z wyborem odbiorców i rekomendacją." width="100%">
</a>

</details>

## Dlaczego system operacyjny

Nazwa to deklaracja, więc oto kryteria. System operacyjny wykonuje siedem zadań; każdy wiersz to
mechanizm, który przeczytasz w kodzie.

| System operacyjny… | AgenticOS |
|---|---|
| **Uruchamia i izoluje procesy** | Uruchamia agentów, izoluje organizacje w schemacie bazy i zapisuje każde wykonanie z jego kosztem |
| **Egzekwuje limity zasobów** | Miesięczne budżety dla agenta, sprawdzane *przed* każdym zapytaniem do modelu |
| **Kontroluje dostęp** | [Katalog uprawnień](docs/permissions.pl.md) w kodzie, role z niego złożone, uprawnienia do zasobów; zatwierdzenie to `sudo` |
| **Obsługuje sprzęt przez sterowniki** | [27 dostawców modeli](docs/models.pl.md) i [serwery MCP](docs/mcp.pl.md) za jednym interfejsem |
| **Prowadzi system plików** | [Kolekcje, skills i kontekst](docs/file-processing.pl.md) w Twoim własnym Postgresie |
| **Daje wielu interfejsom jedną powłokę** | Jeden runner za czatem, API, Slackiem, Telegramem, Mattermost, widgetem, stroną agenta i harmonogramem |
| **Prowadzi dziennik audytu** | Kto co uruchomił, kiedy, ile to kosztowało i kto to zatwierdził — zapisywane także, gdy wykonanie się nie powiodło |

Zastosuj te same siedem kryteriów do czegokolwiek innego w tej kategorii, także do nas:
[co sprawia, że coś jest systemem operacyjnym dla agentów](docs/about/index.pl.md).

## Dlaczego powstał

Większość frameworków agentowych daje bibliotekę. Piszesz w Pythonie, wdrażasz, a każda zmiana
zachowania agenta to pull request, review i wydanie. To dobry kształt dla funkcji produktu i zły dla
czterdziestu małych agentów, których firma naprawdę potrzebuje — bo osoba, która wie, co agent ma
mówić, nie jest osobą z dostępem do repozytorium.

**Kod definiuje, konfiguracja składa.** Zespół biznesowy składa agentów w przeglądarce i nigdy nie
otwiera Pythona; programiści rozszerzają to, z czego da się składać, a konfiguracja sięga tylko po to,
co zarejestrował kod. Sufitem jest rejestr możliwości, a nie plik konfiguracyjny.

## Zbuduj wspólny sposób pracy z AI

Przy cyklicznym raporcie zespół może podzielić pracę:

1. **Ekspert określa sposób wykonania:** utrzymuje instrukcje, procedury i wiedzę źródłową.
2. **Osoba konfigurująca udostępnia agenta:** podłącza narzędzia, publikuje wersję i nadaje współpracownikom dostęp.
3. **Współpracownicy korzystają z wyników:** uruchamiają agenta, sprawdzają odpowiedź i udostępniają artefakt osobom, które go potrzebują.

Agent i jego know-how należą do organizacji, a nie do osoby, która napisała pierwszy prompt.
[Skonfiguruj dostęp zespołu](docs/permissions.pl.md).

## Kontroluj wdrożenie, modele i dostęp

**Uruchamiaj na własnej infrastrukturze.** Kod AgenticOS na licencji Apache-2.0 możesz przeglądać,
modyfikować i utrzymywać. Wybierz dostawcę modeli w chmurze lub modele lokalne przez Ollama
i zgodne endpointy, np. vLLM. [Konfiguracja modeli](docs/models.pl.md).

**Określ, co wolno agentowi.** Skonfiguruj uprawnienia do zasobów, przechowuj dane uwierzytelniające
w szyfrowanym sejfie i postaw zatwierdzenie człowieka przed narzędziami, które działają na zewnątrz.
[Kontrola dostępu](docs/permissions.pl.md) · [Sekrety](docs/secrets.pl.md).

[Wdrożenie i utrzymanie](docs/rollout.pl.md) · [Kontrola wykonań i kosztów](docs/governance.pl.md) · [Bezpieczeństwo i przepływy danych](docs/security.pl.md)

## Czy AgenticOS pasuje do Twojej firmy?

Wybierz AgenticOS, jeśli firma potrzebuje wspólnych agentów, wiedzy i automatyzacji oraz kontroli
nad kodem, modelami i wdrożeniem. Jeśli potrzebujesz tylko biblioteki agentów w istniejącej aplikacji,
zacznij od frameworka.

Każde porównanie cytuje strony dostawcy, pokazuje, gdzie AgenticOS idzie dalej, i nazywa to, czego jeszcze nie robi.

- **Aplikacje asystentów:** [Claude](docs/about/claude-apps.pl.md) · [ChatGPT](docs/about/chatgpt.pl.md). Licencje dla pracowników albo agenci należący do organizacji, na dowolnym modelu.
- **Kreatory w pakietach chmurowych:** [Copilot Studio](docs/about/copilot-studio.pl.md) · [Gemini Enterprise](docs/about/gemini-enterprise.pl.md). Chmura i licznik dostawcy albo Twoja infrastruktura i ceny Twojego dostawcy modeli.
- **Kreatory do samodzielnego hostowania:** [Dify](docs/about/dify.pl.md) · [n8n](docs/about/n8n.pl.md). Warunki licencji i plany enterprise albo Apache-2.0 z governance w zestawie.
- **Usługa „AI-współpracownik”:** [Viktor](docs/about/viktor.pl.md). Jeden wspólny pracownik AI albo wielu agentów z własnym dostępem i budżetem.
- **Dostarczana warstwa agentów:** [Wonderful](docs/about/wonderful.pl.md). System dostarczany przez dostawcę albo taki, który jest Twój od pierwszego dnia.
- **Agenci do kodowania:** [Claude Code](docs/about/claude-code.pl.md) · [Codex](docs/about/codex.pl.md) · [OpenCode](docs/about/opencode.pl.md). Zbudowani dla programistów; AgenticOS jest dla wszystkich pozostałych, a programiści go rozszerzają.

[Wszystkie porównania i luki](docs/about/comparison.pl.md).

<details>
<summary>Pytania o warstwę agentów</summary>

### Czy AgenticOS to AI agent harness?

Tak, z interfejsem dla zespołu. Harness to pętla, która uruchamia model z narzędziami: wyszukiwanie
w Twoich dokumentach, wyszukiwarka i prawdziwa przeglądarka, Python w sandboksie z plikami i powłoką,
wykresy, obrazy, delegowanie do subagentów, lista zadań i kompaktowanie rozmowy. Każda z tych możliwości
to przełącznik w przeglądarce, obok skills, kontekstu, serwerów MCP, budżetów i zatwierdzeń. Programiści
dodają nowe możliwości w typowanym Pythonie. Zobacz [opis możliwości](docs/reference/capabilities.pl.md).

### Czy mogę stworzyć agenta w stylu Claude Code do zadań biznesowych?

Tak. Daj agentowi sandbox z plikami i powłoką, wyszukiwarkę, przeglądarkę, delegowanie i listę zadań,
a potem przypisz potrzebne skills i kontekst. Planuje wieloetapową pracę, czyta, zanim zacznie działać,
edytuje pliki, uruchamia komendy, przekazuje części specjalistom i sprawdza wynik. Odpowiada w czacie,
w Slacku lub przez API, na wybranym przez Ciebie modelu, z zatwierdzeniem przed wszystkim, co działa
na zewnątrz. Zobacz [porównanie z Claude Code](docs/about/claude-code.pl.md).

### Co mogą współdzielić członkowie zespołu?

Zespoły mogą współdzielić agentów, skills, kontekst, kolekcje wiedzy i artefakty zgodnie z uprawnieniami
do zasobów. Wspólny agent może obsługiwać różne osoby, a udostępniony artefakt daje im wynik dostępny
poza czatem.

</details>

## Na pulpicie, jeśli chcesz

Konsola to aplikacja webowa i wystarczy jej przeglądarka. Opcjonalna [aplikacja desktopowa](docs/desktop.pl.md)
to ta sama konsola we własnym oknie, ze zwierzakiem na pulpicie i globalnym skrótem (`⌘⇧A`), który robi
zrzut dowolnego fragmentu ekranu prosto do nowego czatu.

## Dla programistów i administratorów

AgenticOS korzysta z FastAPI, Pydantic AI, PostgreSQL z pgvector, Redis, Prefect i Next.js.
Każdy opublikowany agent jest też endpointem, z tym samym budżetem, zatwierdzeniami i historią wykonań co konsola:

```bash
curl -X POST "$BASE/api/v1/agents/$AGENT_ID/run" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Podsumuj otwarte zgłoszenia supportu"}'
```

| Zacznij tutaj | Zakres |
|---|---|
| [Architektura](docs/architecture.pl.md) | Usługi, przechowywanie danych i wykonywanie zadań |
| [Możliwości](docs/reference/capabilities.pl.md) | Dostępne narzędzia i konfiguracja |
| [API](docs/api.pl.md) | Integracja z Twoimi aplikacjami |
| [Modele](docs/models.pl.md) | Dostawcy modeli i profile |
| [Bezpieczeństwo](docs/security.pl.md) | Przepływy danych i granice wdrożenia |
| [Testowanie](docs/testing.pl.md) | Zestawy testów i zakres pokrycia |

`make check` przed pull requestem: każde zadanie CI poza e2e. Nowe zachowanie ma test; poprawka błędu
ma test regresyjny. Rdzeń trzyma 100% pokrycia, a CI odrzuca wszystko poniżej.

Trzy rzeczy, o które potyka się pierwsza zmiana: narzędzie to kod, a agent nie (nie ma `@agent.tool` —
możliwość się rejestruje i staje się przełącznikiem w Builderze każdego użytkownika); bramki
`require(...)` stawia się tylko na trasach kolekcji; a jeśli narzędzie istnieje już jako serwer MCP,
nie pisz żadnego. [Poradnik dla współtwórców](CONTRIBUTING.pl.md) opisuje resztę, [`.claude/`](.claude/README.md)
zawiera te same konwencje spisane dla maszyny, [roadmapa](docs/ROADMAP.md) pokazuje planowane prace,
a zadania na początek są [oznaczone tutaj](https://github.com/vstorm-co/agenticos/labels/good%20first%20issue).

<details>
<summary><b>Pozostałe projekty Vstorm OSS</b></summary>

Wszystkie działają na [Pydantic AI](https://ai.pydantic.dev).

| Projekt | Czym jest | |
|---|---|---|
| **[full-stack-ai-agent-template](https://github.com/vstorm-co/full-stack-ai-agent-template)** | Generator, z którego powstał AgenticOS — FastAPI + Next.js, RAG, streaming, uwierzytelnianie, ponad 20 integracji | [![Stars](https://img.shields.io/github/stars/vstorm-co/full-stack-ai-agent-template?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/full-stack-ai-agent-template) |
| **[pydantic-deepagents](https://github.com/vstorm-co/pydantic-deepagents)** | Otwarty, samodzielnie hostowany odpowiednik Claude Code — asystent w terminalu i framework pod nim | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-deepagents?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-deepagents) |
| **[pydantic-ai-shields](https://github.com/vstorm-co/pydantic-ai-shields)** | Guardrails — śledzenie kosztów, wykrywanie prompt injection, filtrowanie PII, maskowanie sekretów | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-shields?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-shields) |
| **[subagents-pydantic-ai](https://github.com/vstorm-co/subagents-pydantic-ai)** | Zagnieżdżone delegowanie do subagentów, równoległe wykonanie, anulowanie zadań | [![Stars](https://img.shields.io/github/stars/vstorm-co/subagents-pydantic-ai?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/subagents-pydantic-ai) |
| **[pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend)** | Przechowywanie plików i sandboksy izolowane w Dockerze, z systemem uprawnień | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-backend?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-backend) |
| **[pydantic-ai-todo](https://github.com/vstorm-co/pydantic-ai-todo)** | Hierarchiczne planowanie zadań z zapisem w PostgreSQL i systemem zdarzeń | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-todo?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-todo) |
| **[production-stack-skills](https://github.com/vstorm-co/production-stack-skills)** | Pakiet skills, który zmienia agenta do kodowania w seniora od produkcji | [![Stars](https://img.shields.io/github/stars/vstorm-co/production-stack-skills?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/production-stack-skills) |
| **[content-skills](https://github.com/vstorm-co/content-skills)** | Pakiet skills do tworzenia treści dla agentów do kodowania — zgodny z marką, z wbudowanym filtrem na slop | [![Stars](https://img.shields.io/github/stars/vstorm-co/content-skills?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/content-skills) |

Wszystkie projekty znajdziesz na **[oss.vstorm.co](https://oss.vstorm.co)**.

</details>

## Licencja

[Apache License 2.0](LICENSE). Zobacz [NOTICE](NOTICE) i [informacje o komponentach zewnętrznych](THIRD_PARTY_NOTICES.md),
aby poznać atrybucje i skład dystrybucji.

## Potrzebujesz pomocy we wdrożeniu agentów na produkcję?

Vstorm wdraża AgenticOS w infrastrukturze klienta, przygotowuje dokumentację, definiuje procesy
i buduje możliwości na zamówienie. Zakres utrzymania i wsparcia ustalamy dla każdej współpracy.

Stworzone z dbałością przez [**Vstorm**](https://vstorm.co) · [oss.vstorm.co](https://oss.vstorm.co)
