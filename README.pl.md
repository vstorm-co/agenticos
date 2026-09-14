<!-- source_sha: 191696f072e5 -->

<div align="center">

<img src="docs/assets/amigo.svg" alt="Amigo, the AgenticOS pet" width="96">

<h1>AgenticOS</h1>

<p>
  <b>Jedno miejsce, w którym budujesz, uruchamiasz i nadzorujesz agentów AI swojej firmy.</b><br>
  Hostowany u siebie i otwarty źródłowo — na Twoim Postgresie, w Twoim Dockerze, pod
  Twoją domeną.<br>
  <sub>OS w nazwie to twierdzenie, z którego się wywiązujemy: <a href="#najlepszy-agentowy-os-jaki-możesz-prowadzić-u-siebie">siedem funkcji, siedem mechanizmów</a>.</sub>
</p>

<p>
  <a href="#-szybki-start">Szybki start</a> &middot;
  <a href="#jak-to-wygląda">Ekrany</a> &middot;
  <a href="https://vstorm-co.github.io/agenticos/presentation/">Prezentacja</a> &middot;
  <a href="docs/index.pl.md">Dokumentacja</a> &middot;
  <a href="#najlepszy-agentowy-os-jaki-możesz-prowadzić-u-siebie">Dlaczego OS</a> &middot;
  <a href="#porównanie-z-alternatywami">Porównanie</a>
</p>

<p>
  <a href="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml"><img src="https://github.com/vstorm-co/agenticos/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://github.com/vstorm-co/agenticos/releases"><img src="https://img.shields.io/github/v/release/vstorm-co/agenticos?label=release&color=blue" alt="Release"></a>
  <a href="docs/testing.pl.md"><img src="https://img.shields.io/badge/platform%20layer-100%25-brightgreen" alt="Coverage"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-Apache--2.0-blue" alt="Licence"></a>
  <a href="https://ai.pydantic.dev"><img src="https://img.shields.io/badge/Powered%20by-Pydantic%20AI-E92063?logo=pydantic&logoColor=white" alt="Pydantic AI"></a>
  <a href="https://github.com/vstorm-co/agenticos/stargazers"><img src="https://img.shields.io/github/stars/vstorm-co/agenticos?style=flat&logo=github&color=e3b341" alt="Stars"></a>
</p>

<p>
  <a href="README.md">English</a> &middot;
  <b>Polski</b> &middot;
  <a href="README.de.md">Deutsch</a> &middot;
  <a href="README.es.md">Español</a>
</p>

</div>

---

Firma kończy z agentami w pięciu miejscach i nie umie odpowiedzieć na cztery
pytania: **co uruchamiamy, ile to kosztowało, czego dotknęło i kto się na to
zgodził.** AgenticOS to jedno miejsce, w którym się ich buduje, i jeden komplet
ksiąg dla nich wszystkich.

**Harness jako produkt**: skille, pliki kontekstowe — `AGENTS.md` jako strona —
MCP w skali rejestru, automatyzacje na harmonogramie albo na triggerze, i budżet,
który zatrzymuje run *przed* wywołaniem modelu.

Niżej: arkusz wrzucony na czat i jedno zdanie z prośbą o wykresy. Agent pisze
kod, uruchamia go w zamkniętym pudełku i odpowiada.

<div align="center">

<video src="https://github.com/user-attachments/assets/9a8e0f44-781c-4f93-990d-b5b7094cc8fc" controls muted loop playsinline width="100%">
  <img src="docs/assets/screens/chat-live-demo.webp" alt="Czat: CSV staje się Pythonem w sandboksie, a potem wykresami" width="100%">
</video>

</div>

A do tego ta sama konsola na pulpicie, w towarzystwie: opcjonalna
[aplikacja desktopowa](#na-pulpicie-jeśli-chcesz), jej zwierzak i skrót, który
robi zrzut ekranu prosto do nowego czatu.

<div align="center">

<video src="https://github.com/user-attachments/assets/b82867ae-3543-406e-a552-e3a8b61f1d10" controls muted loop playsinline width="100%">
  <img src="docs/assets/desktop_no_more_caramba_pet.png" alt="Amigo, zwierzak z pulpitu, w sombrero, mówi: No more caramba." width="270">
</video>

</div>

<div align="center">
<sub>
Nie lubisz czytać? <a href="https://vstorm-co.github.io/agenticos/presentation/"><b>Całość na dwudziestu slajdach</b></a> — na czym polega problem, co mieści spec, gdzie odpowiada i czego odmawia.
</sub>
</div>

## ⚡ Szybki start

Jedna komenda, a Docker to wszystko, czego potrzeba. Pobiera jeden plik compose,
ściąga opublikowane obrazy, zadaje cztery pytania i oddaje konsolę z działającym
agentem w środku. Nic nie opuszcza Twojej maszyny.

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

<details>
<summary><b>macOS</b></summary>

Docker Desktop albo [OrbStack](https://orbstack.dev). Nic więcej.

</details>

<details>
<summary><b>Linux</b></summary>

```bash
curl -fsSL https://get.docker.com | sh
sudo apt install docker-compose-plugin
```

</details>

<details>
<summary><b>Windows</b></summary>

Przez WSL2. W PowerShellu uruchomionym jako administrator:

```powershell
wsl --install
```

Potem Docker Desktop z włączoną integracją z WSL2, a instalator uruchom w
powłoce Ubuntu, którą dostaniesz.

</details>

### O co pyta

| | |
|---|---|
| **Który model** | OpenAI, Anthropic, Google, OpenRouter — albo *zdecyduję później*, co tworzy wszystko i pozwala wkleić klucz w konsoli |
| **Twój klucz** | Wpisywany bez echa, przechowywany w zaszyfrowanej postaci w Twojej własnej bazie, nigdy nie drukowany z powrotem |
| **Twój login i nazwa organizacji** | Wartości domyślne w zupełności wystarczą, żeby się rozejrzeć |
| **Jeden przełącznik** | Zlustruj publiczny rejestr MCP, żeby wszystkie 5802 serwery narzędziowe dało się wyszukać po nazwie |

Dodaj `--check`, żeby tylko dowiedzieć się, czego brakuje, `--dry-run`, żeby
zobaczyć każdą komendę, którą by uruchomił, bez uruchomienia ani jednej, albo
prowadź go bez nadzoru:

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash -s -- \
  --yes --provider anthropic --api-key sk-ant-... --org "Acme"
```

### Albo wpisz te trzy komendy samodzielnie

Instalator jest tylko opakowaniem na nie i nie robi kroku, którego nie dałoby
się zrobić ręcznie:

```bash
mkdir agenticos && cd agenticos
curl -fsSLO https://raw.githubusercontent.com/vstorm-co/agenticos/main/docker-compose.yml
docker compose up -d                                          # postgres (pgvector), redis, api, prefect, console
docker compose exec -T -e BOOTSTRAP_API_KEY=sk-... app \
  agenticos cmd bootstrap                                    # an org, an owner, a key, a model, a published agent
open http://localhost:3000                                   # sign in as admin@example.com / admin123
```

Obrazy to `ghcr.io/vstorm-co/agenticos-backend` i `agenticos-frontend`,
publikowane dla amd64 i arm64 przy każdym wydaniu; `AGENTICOS_VERSION=x.y.z` w
pliku `.env` obok tamtego przypina konkretny. Nie ma żadnego `.env`, który
trzeba napisać najpierw: każda zmienna compose'a ma wartość domyślną. Żeby
zmieniać kod, zrób zamiast tego `git clone` i `make dev` - klon buduje te same
obrazy z drzewa.

Jeśli coś się nie podniesie, `docker compose exec app agenticos cmd doctor`
odpowiada na jedyne pytanie, które ma znaczenie — czy to wdrożenie naprawdę
potrafi uruchomić agenta — a resztę ma [docs/install.pl.md](docs/install.pl.md).

## Co dostajesz

- 🧰 **Harness jako konfiguracja.** Wyszukiwanie po Twoich dokumentach, prawdziwa
  przeglądarka, Python w sandboksie z plikami i powłoką, wykresy, obrazy,
  delegowanie — włączane per agent, a nie wpisane w kod.
- 📄 **Pliki kontekstowe.** `AGENTS.md` i `CLAUDE.md` jako strona: stałe
  instrukcje napisane raz, dołączone do każdego agenta, który ich potrzebuje.
- 🎓 **Skille.** Procedura spisana raz, zwykłym językiem, ładowana wtedy, gdy
  agent uzna ją za istotną. Edytujesz ją; działa od następnej odpowiedzi, bez wydania.
- 🔌 **MCP w skali rejestru.** **5802 serwery** w katalogu, do wyszukania po
  nazwie — 99 z nich sprawdzonych ręcznie, z podpiętym OAuth. Albo dowolny URL.
- 📚 **Dokumenty czytane porządnie.** Wybierz czytnik PDF per kolekcja albo dla
  jednego pliku: wbudowany PyMuPDF, LlamaParse tam, gdzie znaczenie niosą tabele,
  hostowany u siebie LiteParse OCR do skanów. Do tego sposób dzielenia i język OCR.
- ⏰ **Automatyzacje.** Harmonogramy i wyzwalacze zdarzeń — triaż o 07:00,
  poniedziałkowe podsumowanie. Te same limity i ten sam zapis co przy tym, o co poprosił człowiek.
- 📡 **Jeden runner, osiem powierzchni.** Czat webowy, hostowana strona, widget,
  HTTP API, surowy WebSocket, Slack, Telegram, Mattermost. Publikowane raz.
- 🖥️ **Wystarczy przeglądarka; aplikacja desktopowa, jeśli chcesz.** Konsola jest
  aplikacją webową. [Aplikacja desktopowa](docs/desktop.pl.md) to ta sama konsola we
  własnym oknie - plus zwierzak na pulpicie i skrót robiący zrzut ekranu prosto
  do nowego czatu. Dodatek, nigdy wymóg.
- 🛡️ **Pod nadzorem.** Budżety zatrzymujące run przed żądaniem do modelu, approval
  na wszystkim, co ma skutki uboczne, ślad audytowy, izolacja tenantów w schemacie.
- 📊 **Dashboard, który każdy układa sobie sam.** 35 kart — runy, wydatki,
  kondycja usług, jakość odpowiedzi, pojemność sandboksów — każda bramkowana tym,
  co dany czytelnik może zobaczyć. Szef finansów i inżynier trzymają na jednym wdrożeniu inne.

**Kod definiuje, konfiguracja komponuje.** Zespół biznesowy składa agentów w
przeglądarce i nigdy nie otwiera Pythona; inżynierowie rozszerzają to, z czego
można składać, a konfiguracja nigdy nie sięgnie dalej niż to, co zarejestrował
kod. Sufitem jest rejestr, a nie plik konfiguracyjny — i jest to Apache-2.0, na
Twoim sprzęcie.

## Jak to wygląda

### W środku jednego agenta

Agent to **spec**: instrukcje, model, capabilities, po które wolno mu sięgnąć,
wiedza z nim związana, budżet i to, gdzie odpowiada. Nic nie rusza w świat przed
**Publish**, a każda publikacja to wersja.

<img src="docs/assets/screens/dark/builder-build.webp" alt="Definiowanie agenta: instrukcje, model i wersja, która działa" width="100%">

<table>
<tr>
<td width="50%">

**Toolbox** — Co agentowi wolno robić, w formie przełączników — Twoje dokumenty, przeglądarka, Python, wykresy, delegowanie. Każdy z nich może najpierw wymagać approvalu od człowieka. To jest **harness AI**, złożony w formularzu.

<img alt="Toolbox" src="docs/assets/screens/dark/builder-toolbox.webp" width="100%">

</td>
<td width="50%">

**Visual map** — Agent jako graf: co do niego sięga i po co on sięga. Pudełko narysowane przerywaną linią to coś, czego nikt nie podłączył.

<img alt="Visual map" src="docs/assets/screens/dark/builder-visual-map.webp" width="100%">

</td>
</tr>
<tr>
<td width="50%">

**Limits** — Miesięczny limit per agent, sprawdzany *przed* każdym wywołaniem modelu, a nie sumowany po fakcie — plus limit kroków, na tę pętlę, która jest tania i nigdy się nie kończy.

<img alt="Limits" src="docs/assets/screens/dark/builder-limits.webp" width="100%">

</td>
<td width="50%">

**History** — Każda wersja, jaką miał, wciąż czytelna. Cofnięcie się do jednej z nich to jedno kliknięcie.

<img alt="History" src="docs/assets/screens/dark/builder-history.webp" width="100%">

</td>
</tr>
</table>

<sub>Te cztery są wyłącznie w wersji ciemnej — jasnej połowy nikt nie zrzucił.</sub>

### Pierwszy ekran

**Dashboard** — 35 kart, ułożonych przez tego, kto akurat patrzy: runy, wydatki,
kondycja usług, jakość odpowiedzi, świeżość synchronizacji, pojemność sandboksów.
Każda bramkowana tym, co dana osoba może zobaczyć, więc szef finansów i inżynier
trzymają na tym samym wdrożeniu inne dashboardy.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/dashboard.webp">
  <img alt="Dashboard: 35 kart do ułożenia" src="docs/assets/screens/light/dashboard.webp" width="100%">
</picture>

### Kiedy prowadzisz ich czterdziestu

<table>
<tr>
<td width="50%">

**Agents** — Każdy agent, którego prowadzisz, z wersją, która działa, i tym, kto może jej używać.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/agents.webp">
  <img alt="Agents" src="docs/assets/screens/light/agents.webp" width="100%">
</picture>

</td>
<td width="50%">

**Templates** — Zacznij od tego, który zbudowano pod Twoją branżę; dostajesz wersję roboczą do poprawienia i opublikowania.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/agents-templates-dialog.webp">
  <img alt="Templates" src="docs/assets/screens/light/agents-templates-dialog.webp" width="100%">
</picture>

</td>
</tr>
<tr>
<td width="50%">

**Jedna odpowiedź, otwarta** — Każda odpowiedź zapisana: pytanie, to, do czego zajrzał agent, każde wywołanie narzędzia, czas trwania, koszt z dokładnością do ułamka centa.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/activity-run-detail.webp">
  <img alt="Jedna odpowiedź, otwarta" src="docs/assets/screens/light/activity-run-detail.webp" width="100%">
</picture>

</td>
<td width="50%">

**Jak czytane są Twoje dokumenty** — Trzy czytniki PDF — PyMuPDF, LiteParse, LlamaParse — plus dzielenie na fragmenty i OCR. Per kolekcja, do nadpisania przy następnym pliku. Zeskanowany cennik i umowa nie chcą tego samego.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/knowledge-base-upload-parsing-dialog.webp">
  <img alt="Jak czytane są Twoje dokumenty" src="docs/assets/screens/light/knowledge-base-upload-parsing-dialog.webp" width="100%">
</picture>

</td>
</tr>
<tr>
<td width="50%">

**Context** — Stałe fakty — nazwy produktów, polityka, firmowy ton — w jednym miejscu zamiast w czterdziestu promptach.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/context.webp">
  <img alt="Context" src="docs/assets/screens/light/context.webp" width="100%">
</picture>

</td>
<td width="50%">

**Pyta, zanim zadziała** — Wszystko, co wysyła, składa albo zwraca pieniądze, czeka na człowieka, z zamierzonym działaniem wypisanym wprost. Rozstrzygane dokładnie raz.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/activity-approvals.webp">
  <img alt="Pyta, zanim zadziała" src="docs/assets/screens/light/activity-approvals.webp" width="100%">
</picture>

</td>
</tr>
<tr>
<td width="50%">

**Ile to kosztuje** — Wydatki w podziale na okresy i na agentów. Limit jest sprawdzany, zanim model zostanie zapytany, więc rozpędzony agent zatrzymuje się w połowie zdania, zamiast przyjść jako faktura.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/activity-spend.webp">
  <img alt="Ile to kosztuje" src="docs/assets/screens/light/activity-spend.webp" width="100%">
</picture>

</td>
<td width="50%">

**Klucze i poświadczenia** — Każdy klucz, zaszyfrowany i oddzielony per zespół. Do wymiany, nigdy więcej do odczytania — również przez tego, kto prowadzi serwer.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/vault.webp">
  <img alt="Klucze i poświadczenia" src="docs/assets/screens/light/vault.webp" width="100%">
</picture>

</td>
</tr>
<tr>
<td width="50%">

**Narzędzia, za które już płacisz** — 5802 serwery MCP w katalogu, do wyszukania po nazwie, 99 z nich sprawdzonych ręcznie, z podpiętym OAuth. Albo dowolny serwer po URL. Żadnego konektora do napisania.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/mcp-servers.webp">
  <img alt="Narzędzia, za które już płacisz" src="docs/assets/screens/light/mcp-servers.webp" width="100%">
</picture>

</td>
<td width="50%">

**Gdzie ludzie się z nim spotykają** — Slack, Telegram, Mattermost, widget na stronie, Twoje własne oprogramowanie po API. Publikowane raz; wszędzie te same limity.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens/dark/channels.webp">
  <img alt="Gdzie ludzie się z nim spotykają" src="docs/assets/screens/light/channels.webp" width="100%">
</picture>

</td>
</tr>
</table>


<sub>Zrzuty ekranu idą za Twoim motywem na GitHubie. <a href="docs/screens.pl.md">Wszystkie 35 ekranów</a>.</sub>

## Najlepszy agentowy OS, jaki możesz prowadzić u siebie

To jest twierdzenie, a jedyny uczciwy sposób, żeby je postawić, to oddać
kryteria i pozwolić Ci policzyć. System operacyjny robi siedem rzeczy. Każdy
wiersz poniżej to mechanizm, który możesz przeczytać w źródłach, a nie obietnica.

| Co robi system operacyjny | Co robi AgenticOS |
|---|---|
| **Uruchamia i izoluje procesy** | Uruchamia agentów, zatrzymuje agenta na jego budżecie, izoluje tenantów w schemacie, a nie w kodzie serwisów, i trzyma każdy run razem z tym, ile kosztował |
| **Egzekwuje limity zasobów** - quota, cgroups | Miesięczne budżety per agent, sprawdzane *przed* każdym żądaniem do modelu, a nie zliczane po fakcie. Run, który zakończył się błędem, i tak zapisuje, ile wydał |
| **Kontroluje dostęp** - użytkownicy, uprawnienia, `sudo` | [Katalog uprawnień](docs/permissions.pl.md) w kodzie, role złożone z niego, granty per zasób, które poszerzają i nigdy nie zawężają. `approval: required` to właśnie `sudo`: narzędzie działające na świat zewnętrzny czeka na człowieka |
| **Sięga do sprzętu przez sterowniki** | Jeden interfejs do [27 providerów modeli](docs/models.pl.md) i do [dowolnego serwera MCP po URL](docs/mcp.pl.md). Zmień profil modelu, a przesuną się wszyscy agenci, którzy go używają, i żaden nie musi być publikowany na nowo |
| **Prowadzi system plików** | [Kolekcje, skille i dołączony kontekst](docs/file-processing.pl.md) w Twoim własnym Postgresie, z embeddingami kluczowanymi per organizacja |
| **Daje wielu interfejsom jedną powłokę** | Jeden runner za czatem webowym, HTTP API, Slackiem, Telegramem, widgetem, hostowaną stroną i harmonogramem. Ten sam budżet, ta sama bramka approvalu, ten sam ślad audytowy |
| **Pisze log audytowy** - syslog, auditd | Kto co uruchomił, kiedy, ile to kosztowało i kto to zatwierdził. Zapisywane nawet wtedy, gdy run zakończył się błędem |

Przyłóż tę samą siódemkę do czegokolwiek innego w tej kategorii. To jest test, na
którym chcielibyśmy być oceniani, a
[Kiedy sięgnąć po coś innego](docs/about/comparison.pl.md) to miejsce, w którym
przeprowadzamy go przeciwko alternatywom - razem z wierszami, gdzie uczciwa
odpowiedź brzmi tu "jeszcze nie".

**A teraz przyłóż tę samą siódemkę do czegokolwiek innego w tej kategorii** —
również do tych, które mają tysiąc razy więcej gwiazdek niż my. Żaden z nich nie
wyjaśnia, dlaczego jest systemem operacyjnym, bo większość z nich to workspace z
literami na pudełku. I na tym polega całe to twierdzenie: nie na tym, że mamy
najwięcej użytkowników, tylko na tym, że jako jedyni podajemy kryteria, a potem
spełniamy je w kodzie, który możesz przeczytać.

Tam, gdzie uczciwa odpowiedź brzmi tu wciąż "jeszcze nie", jest to wiersz w
porównaniu niżej i linia na [roadmapie](docs/ROADMAP.md).
[Kiedy sięgnąć po coś innego](docs/about/comparison.pl.md) to wersja długa, razem z
tym, gdzie ten produkt przegrywa, a
[co sprawia, że coś jest systemem operacyjnym dla agentów](docs/about/index.pl.md),
to same kryteria — weź je i oceń kogokolwiek, nas włącznie.

## Co potrafi agent

Włączane per agent, w Builderze. Każda z tych rzeczy niesie własne ustawienia,
własny scope uprawnień i — tam, gdzie działa na świat zewnętrzny — własną bramkę
approvalu.

| | |
|---|---|
| **Odpowiadać z Twoich dokumentów** | Wyszukiwanie po kolekcjach w Twoim własnym Postgresie, plus [skille](docs/skills.pl.md), które ładuje na żądanie, i [pliki kontekstowe](docs/context.pl.md) wiązane z wieloma agentami |
| **Pójść i się dowiedzieć** | Wyszukiwanie w sieci, porządne pobranie jednej strony albo poprowadzenie **prawdziwej przeglądarki** przez witrynę, która wymaga klikania |
| **Wykonać pracę** | Uruchomić Pythona, prowadzić [sandbox](docs/sandbox.pl.md) z plikami i powłoką, rysować wykresy, generować obrazy |
| **Poradzić sobie z pracą za dużą na jedną odpowiedź** | Zdelegować do subagentów, prowadzić listę zadań, pomyśleć dłużej, skompaktować długą rozmowę |
| **Trzymać się w ryzach** | Guardraile, które redagują albo blokują, limity wyjścia per narzędzie i zegar |
| **Cokolwiek innego** | [Dowolny serwer MCP po URL](docs/mcp.pl.md) - 5802 w katalogu, 99 z nich sprawdzonych, z podpiętymi przepływami OAuth, i żadnego konektora do napisania |

## Gdzie odpowiada

Publikujesz raz. Ten sam runner obsługuje to wszystko, więc odpowiedź nie zależy
od tego, skąd przyszło pytanie.

| | |
|---|---|
| **Czat webowy** | W konsoli, z załącznikami i komendami ze slashem |
| **Aplikacja desktopowa** | Ta sama konsola we własnym oknie, ze zwierzakiem i skrótem do zrzutu ekranu - [opcjonalna powłoka](docs/desktop.pl.md), a nie drugi produkt |
| **Hostowana strona** | `/e/{key}` - wyślij komuś link, konto niepotrzebne |
| **Osadzany widget** | Na Twojej własnej stronie, ze zmiennymi z paska adresu |
| **HTTP API** | [Jeden POST i masz odpowiedź](docs/api.pl.md) |
| **Surowy WebSocket** | Strumieniuj tokeny do frontendu, który zbudowałeś sam |
| **Slack, Telegram, Mattermost** | Gdzie `@mention` działa jako **osoba, która go wysłała**, a nie jako bot |
| **Harmonogramy i triggery** | Zegar, webhook albo skrzynka pocztowa, którą odpytujemy - [routines](docs/triggers.pl.md) |

## Na pulpicie, jeśli chcesz

Wszystko powyżej działa w przeglądarce i tak właśnie korzysta z tego większość
ludzi. Dla tych, którzy chcą mieć to w docku, jest [aplikacja
desktopowa](docs/desktop.pl.md): cienka powłoka wokół tej samej konsoli - to samo
logowanie, te same uprawnienia, nic dołożonego - z dwiema rzeczami, których karta
przeglądarki nie potrafi. Zwierzak, który mieszka na pulpicie, kiedy pracujesz, i
globalny skrót (`⌘⇧A`), który robi zrzut dowolnego fragmentu ekranu i otwiera nowy
czat z tym zrzutem w załączniku.

<div align="center">

<img src="docs/assets/desktop_no_more_caramba_pet.png" alt="Amigo, zwierzak z pulpitu, w sombrero, mówi: No more caramba." width="270">

<sub>Amigo, jeden z pięciu zwierzaków. Przeciągnij go, kliknij, pogłaszcz; prawy przycisk otwiera jego menu. <b>No more caramba in your AI.</b></sub>

</div>

## Porównanie z alternatywami

Jedyny z nich, który da się doprowadzić do końca na infrastrukturze, którą już
masz, z agentami, których edytuje osoba niebędąca inżynierem, a księgowy może
zaudytować.

| | **AgenticOS** | Cloudflare&nbsp;OS | Glean | Biblioteka |
|---|:---:|:---:|:---:|:---:|
| Otwarte źródła | ✅ Apache-2.0 | ✅ Apache-2.0 | — | ✅ |
| **Działa na zwykłej infrastrukturze** (Postgres, Redis, Docker) | ✅ | — | — | ✅ |
| Działa bez dostępu do sieci, bez konta u dostawcy | ✅ | — | — | ✅ |
| Modele lokalne (Ollama, LiteLLM) | ✅ | ✅ | — | ✅ |
| Agent zbudowany i edytowany przez osobę niebędącą inżynierem | ✅ | ~ | ✅ | — |
| Wersjonowany przy publikacji, eksportowalny do Twojego gita | ✅ | ~ | — | — |
| Budżet zatrzymujący run przed wywołaniem modelu | ✅ | ~ | ~ | DIY |
| Approval od człowieka na narzędziach ze skutkami ubocznymi | ✅ | ✅ | ~ | DIY |
| Izolacja wielotenantowa w schemacie | ✅ | ~ | ✅ | DIY |
| Vault na sekrety per organizacja | ✅ | ✅ | ✅ | DIY |
| **Dowolny serwer MCP po URL, 5802 w katalogu** | ✅ | ✅ | ~ | ~ |
| **Slack, Telegram, widget, hostowana strona i API z jednego runnera** | ✅ | — | ~ | DIY |
| Konektory świadome ACL do 275+ systemów SaaS | — | ~ | ✅ | — |
| Harness do ewaluacji | — | — | ✅ | ~ |
| SAML / SCIM | — | ✅ | ✅ | — |

<sub>✅ pierwsza klasa · ~ częściowo albo przez konfigurację · — niedostępne · DIY podpinasz to sam.
"Biblioteka" znaczy LangGraph, Pydantic AI albo podobne. Oddaje stan każdego projektu na 2026-08;
poprawki mile widziane przez PR. Trzy ostatnie wiersze są nasze do naprawienia i są na
<a href="https://github.com/vstorm-co/agenticos/blob/main/docs/ROADMAP.md">roadmapie</a>.</sub>

## Po co to powstało

Większość frameworków agentowych daje Ci bibliotekę. Piszesz Pythona, wdrażasz
go, a każda zmiana w zachowaniu agenta to pull request, przegląd i wydanie. To
właściwy kształt dla funkcji produktu i niewłaściwy dla czterdziestu małych
agentów, których firma naprawdę chce — bo osoba, która wie, co agent ma mówić,
nie jest osobą z dostępem do commitowania.

AgenticOS wyprowadza agenta z kodu i zamiast tego otacza go nadzorem.
[Sekrety](docs/secrets.pl.md) są zapieczętowane per organizacja: klucza skopiowanego
z wiersza bazy jednego tenanta nie da się odszyfrować dla innego, a żadna
odpowiedź API nigdy żadnego nie zwraca.

## Dokumentacja

| | |
|---|---|
| [Instalacja](docs/install.pl.md) · [Twój pierwszy agent](docs/first-agent.pl.md) | Od zera do agenta, który odpowiada |
| [Pojęcia](docs/concepts.pl.md) | Spec, wersja, wystawienie, trigger, run — pięć rzeczowników |
| [Uprawnienia](docs/permissions.pl.md) · [Nadzór](docs/governance.pl.md) | Komu co wolno; budżety, approvale, audyt |
| [Capabilities](docs/reference/capabilities.pl.md) · [MCP](docs/mcp.pl.md) | Co agent potrafi i jak dodać narzędzie |
| [Modele](docs/models.pl.md) · [Sekrety](docs/secrets.pl.md) | Providerzy, profile, koszt; vault |
| [Wiedza](docs/file-processing.pl.md) · [Skille](docs/skills.pl.md) | Parsery, dzielenie na fragmenty, OCR; spisane know-how |
| [Kanały](docs/channels.pl.md) · [API](docs/api.pl.md) | Slack, Telegram, widget, WebSocket, HTTP |
| [Aplikacja desktopowa](docs/desktop.pl.md) | Opcjonalna powłoka: konsola w oknie, zwierzak, skrót do zrzutu ekranu |
| [Architektura](docs/architecture.pl.md) · [Testy](docs/testing.pl.md) | Jak to jest zbudowane i jak to jest weryfikowane |

Zbudowane na MkDocs: `make docs` serwuje dokumentację na :8001. Stack, w jednej
linii: FastAPI + Pydantic v2, PostgreSQL z pgvector, Redis, Prefect,
[Pydantic AI](https://ai.pydantic.dev), Next.js 15. Nic nie dzwoni do domu —
jedyne wychodzące wywołania to te, które robią Twoi agenci.

## Współtworzenie

`make check` przed pull requestem: każde zadanie CI poza e2e, jakieś pięć minut.
Nowe zachowanie jedzie z testem; błąd jedzie z testem regresyjnym. **Warstwa
platformy jest trzymana na 100% pokrycia**, a CI poniżej tego progu nie
przechodzi.

Trzy rzeczy, na których wykłada się pierwsza zmiana: narzędzie jest kodem, a
agent nie (nie ma żadnego `@agent.tool` — capability się rejestruje, a potem jest
przełącznikiem w Builderze każdego); bramki `require(...)` idą wyłącznie na trasy
kolekcji; a jeśli narzędzie już istnieje jako serwer MCP, nie pisz żadnego.
Resztę ma [CONTRIBUTING.md](CONTRIBUTING.md), [`.claude/`](.claude/README.md) ma
te same konwencje spisane dla maszyny, a dobre zadania na start są
[oznaczone tutaj](https://github.com/vstorm-co/agenticos/labels/good%20first%20issue).

<details>
<summary><b>Reszta ekosystemu OSS Vstorm</b></summary>

Wszystko poniżej działa na [Pydantic AI](https://ai.pydantic.dev).

| Projekt | Co to jest | |
|---|---|---|
| **[full-stack-ai-agent-template](https://github.com/vstorm-co/full-stack-ai-agent-template)** | Generator, z którego zbudowano AgenticOS — FastAPI + Next.js 15, RAG, streaming, uwierzytelnianie, 20+ integracji | [![Stars](https://img.shields.io/github/stars/vstorm-co/full-stack-ai-agent-template?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/full-stack-ai-agent-template) |
| **[pydantic-deepagents](https://github.com/vstorm-co/pydantic-deepagents)** | Otwarty, hostowany u siebie Claude Code — asystent w terminalu i framework, który za nim stoi | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-deepagents?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-deepagents) |
| **[pydantic-ai-shields](https://github.com/vstorm-co/pydantic-ai-shields)** | Guardraile — śledzenie kosztów, wykrywanie prompt injection, filtrowanie PII, redagowanie sekretów | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-shields?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-shields) |
| **[subagents-pydantic-ai](https://github.com/vstorm-co/subagents-pydantic-ai)** | Zagnieżdżone delegowanie do subagentów, wykonanie równoległe, anulowanie zadań | [![Stars](https://img.shields.io/github/stars/vstorm-co/subagents-pydantic-ai?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/subagents-pydantic-ai) |
| **[pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend)** | Przechowywanie plików i sandboksy izolowane Dockerem, z systemem uprawnień | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-backend?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-backend) |
| **[pydantic-ai-todo](https://github.com/vstorm-co/pydantic-ai-todo)** | Hierarchiczne planowanie zadań z przechowywaniem w PostgreSQL i systemem zdarzeń | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-todo?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/pydantic-ai-todo) |
| **[production-stack-skills](https://github.com/vstorm-co/production-stack-skills)** | Paczka skilli, która robi z agenta kodującego starszego inżyniera produkcyjnego | [![Stars](https://img.shields.io/github/stars/vstorm-co/production-stack-skills?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/production-stack-skills) |
| **[content-skills](https://github.com/vstorm-co/content-skills)** | Paczka skilli contentowych dla agentów kodujących — świadoma marki, z wbudowanym anty-slopem | [![Stars](https://img.shields.io/github/stars/vstorm-co/content-skills?style=flat&logo=github&color=e3b341)](https://github.com/vstorm-co/content-skills) |

Przejrzyj je wszystkie na **[oss.vstorm.co](https://oss.vstorm.co)**.

Przejrzyj je wszystkie na **[oss.vstorm.co](https://oss.vstorm.co)**.

</details>

## Licencja

Apache License 2.0 - patrz [`LICENSE`](LICENSE) i [`NOTICE`](NOTICE).
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) wymienia każdy komponent,
który niosą obrazy, wraz z jego licencją; przegląd tego, do czego te licencje
zobowiązują, i ustalenia wciąż otwarte są
[w dokumentacji](https://vstorm-co.github.io/agenticos/licenses/).

Apache-2.0, a nie MIT, bo AgenticOS jest pomyślany do wdrażania wewnątrz innych
firm: jawne udzielenie licencji patentowej to ta część, o którą pyta ich przegląd
prawny, a MIT o niej milczy.

---

<div align="center">

### Potrzebujesz pomocy z wdrożeniem agentów na produkcję?

<p>
Jesteśmy <a href="https://vstorm.co"><b>Vstorm</b></a> — firmą inżynieryjną od stosowanego
agentowego AI, z 30+ produkcyjnymi wdrożeniami agentów.<br>
AgenticOS jest tym, na czym je budujemy, i wdrażamy go wewnątrz infrastruktury
klienta: w Twojej chmurze, w Twoim centrum danych albo bez dostępu do sieci.
</p>

<a href="https://vstorm.co/contact-us/">
  <img src="https://img.shields.io/badge/Talk%20to%20us%20%E2%86%92-0066FF?style=for-the-badge&logoColor=white" alt="Talk to us">
</a>

<br><br>

Zbudowane z dbałością przez <a href="https://vstorm.co"><b>Vstorm</b></a> ·
<a href="https://oss.vstorm.co">oss.vstorm.co</a>

</div>
