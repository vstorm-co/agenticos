---
source_sha: 52c1284c9aae
---

# Każdy ekran w konsoli { #every-screen-in-the-console }

Jedna strona, każdy moduł, opisany. Zrzuty ekranu podążają za motywem, w którym
czytasz tę stronę - przełącz go przełącznikiem w nagłówku, a każdy obraz na tej
stronie przełączy się razem z nim.

Zarejestrowane 01.09.2026 z działającego wdrożenia: 35 ekranów, 27 z nich w obu
motywach pod `docs/assets/screens/`, nazwanych identycznie w `light/` i `dark/`.
Osiem ekranów Buildera jest tylko w ciemnym motywie i mówią o tym tam, gdzie się
pojawiają.

## Czat, w dwadzieścia sekund { #the-chat-in-twenty-seconds }

CSV upuszczony do rozmowy, jedno zdanie instrukcji, a agent pisze Pythona,
uruchamia go w sandboksie i odpowiada wykresami, które narysował z tych danych.
Nic tutaj nie było konfigurowane akurat pod ten plik.

<video src="../assets/screens/chat-live-demo.mp4" poster="../assets/screens/chat-live-demo-poster.webp" controls muted loop playsinline style="width:100%"></video>

## Gdzie lądujesz { #where-you-land }

### Dashboard { #dashboard }

Układalne widgety, najpierw całe wdrożenie, a potem ta organizacja. Runy, wydatki, kondycja usług i jakość odpowiedzi; każda karta jest bramkowana uprawnieniem, którego wymagają jej własne dane, więc karta, której podstawowego odczytu nie możesz wykonać, to karta, której nie dostajesz do wyboru.

![Dashboard](assets/screens/light/dashboard.webp#only-light)
![Dashboard](assets/screens/dark/dashboard.webp#only-dark)

### Chat, w trakcie runa { #chat-mid-run }

Agent w trakcie myślenia, a potem komendy powłoki, które faktycznie wykonał w sandboksie, każda do rozwinięcia. Przejrzystość jest tu produktem: to, co zrobiło narzędzie, jest na ekranie, a nie w logu, który może przeczytać ktoś inny.

![Chat, w trakcie runa](assets/screens/light/chat-sandbox-commands.webp#only-light)
![Chat, w trakcie runa](assets/screens/dark/chat-sandbox-commands.webp#only-dark)

## Budowanie agenta { #building-an-agent }

### Agents { #agents }

Katalog. Każdy agent niesie wersję, która jest na żywo, informację o tym, kto może do niego sięgnąć, i o tym, czy czeka wersja robocza. Agent jest konfiguracją, a nie kodem - i dlatego tę listę może edytować ten, kto zna odpowiedź.

![Agents](assets/screens/light/agents.webp#only-light)
![Agents](assets/screens/dark/agents.webp#only-dark)

### Agent templates { #agent-templates }

Szablony według branży, nad katalogiem. Zainstalowanie jednego tworzy wersję roboczą, którą kończysz i publikujesz; nic nie działa, dopóki tego nie zrobisz.

![Agent templates](assets/screens/light/agents-templates-dialog.webp#only-light)
![Agent templates](assets/screens/dark/agents-templates-dialog.webp#only-dark)

### Skills { #skills }

Know-how spisane raz i dzielone przez każdego związanego z nim agenta - jak obsługuje się zwroty, jaki jest styl firmy. Zedytuj je tutaj, a każdy związany z nim agent jest aktualny przy swoim następnym runie.

![Skills](assets/screens/light/skills.webp#only-light)
![Skills](assets/screens/dark/skills.webp#only-dark)

### Skill gallery { #skill-gallery }

Skille według branży. Instalacja kopiuje jeden do Twojej organizacji, gdzie możesz go edytować - kopia, więc źródło nie może zmienić tego, co mówią Twoi agenci.

![Skill gallery](assets/screens/light/skills-gallery-dialog.webp#only-light)
![Skill gallery](assets/screens/dark/skills-gallery-dialog.webp#only-dark)

### Jeden skill { #one-skill }

Otwarty do edycji, ze swoją kategorią. Nazwa, którą posługuje się model, jest ustalana przy tworzeniu i nie może się zmienić; wszystko inne tutaj może.

![Jeden skill](assets/screens/light/skill-detail.webp#only-light)
![Jeden skill](assets/screens/dark/skill-detail.webp#only-dark)

### Context { #context }

Stały kontekst, z którego może czerpać każdy agent - słownik pojęć, polityka, ton marki. Wstrzykiwany do promptu albo czytany na żądanie, i aktualny w chwili, w której go zedytujesz.

![Context](assets/screens/light/context.webp#only-light)
![Context](assets/screens/dark/context.webp#only-dark)

## Wewnątrz jednego agenta { #inside-one-agent }

Builder, zakładka po zakładce. Te osiem jest **tylko w ciemnym motywie** - jasna
połowa nie została zarejestrowana, więc w odróżnieniu od każdego innego ekranu
na tej stronie nie podążają za Twoją paletą.

### Build { #build }

Instrukcje, model i endpoint. Zachowanie mieszka tutaj, a nie w kodzie, w Markdownie, z którego model czyta strukturę - a nagłówek niesie `published` obok `Draft differs from v40`, i o to właśnie chodzi: edytowanie nie wydaje.

![Build](assets/screens/dark/builder-build.webp)

### Toolbox { #toolbox }

Każda capability jako przełącznik - wyszukiwanie w wiedzy, przeglądarka, Python w sandboksie, wykresy, delegacja - a obok każdego bramka approvalu per narzędzie. Konfiguracja sięga wyłącznie tego, co zarejestrował kod.

![Toolbox](assets/screens/dark/builder-toolbox.webp)

### MCP servers { #mcp-servers }

Do których połączeń ten agent może sięgnąć i do których z ich narzędzi. Lista organizacji nadal go ogranicza; agent może zawęzić się wewnątrz niej i nie może sięgnąć poza nią.

![MCP servers](assets/screens/dark/builder-mcp-servers.webp)

### Limits { #limits }

Jeden limit miesięczny i sufit kroków. Limit jest sprawdzany przed każdym żądaniem do modelu, a limit kroków łapie tę drugą rozbieganą sytuację - pętlę narzędzia, która jest tania na wywołanie i nigdy się nie kończy.

![Limits](assets/screens/dark/builder-limits.webp)

### Availability { #availability }

Gdzie ten agent odpowiada: dashboard i API zawsze, plus każdy bot czatowy tutaj z nim związany. Agenta da się wywołać przez `@handle` tylko na tych botach, z którymi jest związany.

![Availability](assets/screens/dark/builder-availability.webp)

### Routines, na agencie { #routines-on-the-agent }

Co robi, gdy nikt nie pisze, na tej samej zakładce - harmonogram, który da się wstrzymać, albo trigger zdarzeniowy.

![Routines, na agencie](assets/screens/dark/builder-routines.webp)

### History { #history }

Każda wersja, jaką ten agent miał. Ta, która była na żywo w marcu, nadal jest czytelna, i to właśnie czyni z rollbacku wybór, a nie projekt archeologiczny.

![History](assets/screens/dark/builder-history.webp)

### Visual map { #visual-map }

Ten sam agent jako graf: co do niego sięga i po co on sięga. Przerywana ramka to coś, do czego nic nie jest podpięte - budżet bez własnego sufitu czyta się jako luka, a nie jako wartość domyślna.

![Visual map](assets/screens/dark/builder-visual-map.webp)
## Knowledge { #knowledge }

### Knowledge bases { #knowledge-bases }

Kolekcje. Zgrupuj powiązane dokumenty w jedną, a potem wybierz na czacie, które kolekcje agent może przeszukiwać.

![Knowledge bases](assets/screens/light/knowledge-bases.webp#only-light)
![Knowledge bases](assets/screens/dark/knowledge-bases.webp#only-dark)

### Jedna kolekcja { #a-collection }

Jej dokumenty, liczby fragmentów i wszystko, czego nie udało się zaingestować, wraz z powodem. To granice fragmentów są tym, do czego dopasowuje się wyszukiwanie, więc dokument wgrany ponownie po zmianie ustawień jest dzielony na nowo.

![Jedna kolekcja](assets/screens/light/knowledge-base-detail.webp#only-light)
![Jedna kolekcja](assets/screens/dark/knowledge-base-detail.webp#only-dark)

### Parsowanie, per wgranie { #parsing-per-upload }

Wybór, którego nikt inny nie wystawia: **PyMuPDF**, **LiteParse** albo **LlamaParse**, strategia dzielenia na fragmenty, rozmiar fragmentu i zakładka, OCR i jego język. Ustawiane na kolekcji i nadpisywalne przy następnym pliku, który dodasz - bo zeskanowany cennik i runbook w Markdownie nie chcą tego samego parsera, a zły parser jest różnicą między odpowiedzią a odmową.

![Parsowanie, per wgranie](assets/screens/light/knowledge-base-upload-parsing-dialog.webp#only-light)
![Parsowanie, per wgranie](assets/screens/dark/knowledge-base-upload-parsing-dialog.webp#only-dark)

## Co się wydarzyło i co czeka { #what-happened-and-what-is-waiting }

### Runs { #runs }

Każdy run, który wykonała ta organizacja, ze swoim statusem, powierzchnią, modelem, osobą i kosztem. Run jest procesem: startuje, można go zatrzymać i zostawia zapis.

![Runs](assets/screens/light/activity-runs.webp#only-light)
![Runs](assets/screens/dark/activity-runs.webp#only-dark)

### Jeden run, otwarty { #one-run-opened }

Tokeny wejściowe i wyjściowe, koszt do czterech miejsc po przecinku, ile to trwało oraz oś czasu każdej tury i każdego wywołania narzędzia. Czat, w którym to się wydarzyło, jest o jedno kliknięcie stąd.

![Jeden run, otwarty](assets/screens/light/activity-run-detail.webp#only-light)
![Jeden run, otwarty](assets/screens/dark/activity-run-detail.webp#only-dark)

### Approvals { #approvals }

Wszystko, co czeka na człowieka, razem z tym, co agent zamierza zrobić. Approval jest rozstrzygany dokładnie raz - druga decyzja na rozstrzygniętym jest odrzucana, i to ten szczegół sprawia, że warto mieć tę bramkę.

![Approvals](assets/screens/light/activity-approvals.webp#only-light)
![Approvals](assets/screens/dark/activity-approvals.webp#only-dark)

### Spend { #spend }

Ile faktycznie wydano, w podziale na okresy. Budżet jest sprawdzany *przed* żądaniem do modelu, a nie sumowany po fakcie, więc run, który go przekroczy, zatrzymuje się w środku odpowiedzi i mimo to zapisuje swój koszt.

![Spend](assets/screens/light/activity-spend.webp#only-light)
![Spend](assets/screens/dark/activity-spend.webp#only-dark)

### Routines { #routines }

Co agenci robią, gdy nikt nie pisze - według harmonogramu albo kiedy przyjdzie zdarzenie. Te runy są budżetowane, zatwierdzane i audytowane jak każde inne.

![Routines](assets/screens/light/routines.webp#only-light)
![Routines](assets/screens/dark/routines.webp#only-dark)

### Nowy trigger zdarzeniowy { #a-new-event-trigger }

Nazwanie zdarzenia, które uruchamia run, nad listą rutyn.

![Nowy trigger zdarzeniowy](assets/screens/light/routines-event-trigger-dialog.webp#only-light)
![Nowy trigger zdarzeniowy](assets/screens/dark/routines-event-trigger-dialog.webp#only-dark)

## Organizacja { #the-organization }

### Organizations { #organizations }

Przełączaj się między nimi, zarządzaj członkami i twórz nowe. Autorytet wewnątrz organizacji to wiersz członkostwa plus katalog uprawnień - na użytkowniku nie ma kolumny z rolą.

![Organizations](assets/screens/light/organizations.webp#only-light)
![Organizations](assets/screens/dark/organizations.webp#only-dark)

### Vault { #vault }

Każdy klucz, który ta organizacja przechowała, zapieczętowany per tenant. Wymienialny, nigdy więcej odczytywalny; a rotacja jest niewidoczna dla opublikowanego agenta, który odwołuje się do sekretu, a nie do jego wartości.

![Vault](assets/screens/light/vault.webp#only-light)
![Vault](assets/screens/dark/vault.webp#only-dark)

### MCP servers { #mcp-servers_1 }

Podłącz dowolny serwer MCP po URL, a jego narzędzia stają się przełącznikami w Builderze. Podłącz go dla organizacji, a może z niego korzystać każdy agent; podłącz go dla siebie, a zostaje w Twoim własnym czacie.

![MCP servers](assets/screens/light/mcp-servers.webp#only-light)
![MCP servers](assets/screens/dark/mcp-servers.webp#only-dark)

### Channels { #channels }

Platformy czatowe, na których odpowiada ta organizacja - Slack, Telegram, Mattermost. Bot obsługuje każdego związanego z nim agenta, a to powiązanie tworzy się na zakładce Availability tego agenta.

![Channels](assets/screens/light/channels.webp#only-light)
![Channels](assets/screens/dark/channels.webp#only-dark)

### Sandboxes { #sandboxes }

Miejsce, w którym agenci tej organizacji uruchamiają komendy powłoki i trzymają pliki. Agent nazywa połączenie po id, więc przeniesienie się na inny host to jedna edycja tutaj, a nie ponowna publikacja każdego agenta.

![Sandboxes](assets/screens/light/sandboxes.webp#only-light)
![Sandboxes](assets/screens/dark/sandboxes.webp#only-dark)

### Workspaces { #workspaces }

Pliki, które agenci trzymają dla Ciebie. Workspace to przestrzeń robocza - jest kasowany razem z rozmową, do której należy, i nie jest miejscem na przechowywanie czegokolwiek trwałego.

![Workspaces](assets/screens/light/workspaces.webp#only-light)
![Workspaces](assets/screens/dark/workspaces.webp#only-dark)

## Administracja wdrożeniem { #deployment-administration }

### Users { #users }

Każdy, kto może zalogować się do tego wdrożenia, oraz flaga administratora aplikacji, która jest niezależna od jakiejkolwiek roli w organizacji.

![Users](assets/screens/light/admin-users.webp#only-light)
![Users](assets/screens/dark/admin-users.webp#only-dark)

### All organizations { #all-organizations }

Każdy tenant w tym wdrożeniu, ze swoim właścicielem, członkami i agentami.

![All organizations](assets/screens/light/admin-organizations.webp#only-light)
![All organizations](assets/screens/dark/admin-organizations.webp#only-dark)

### System { #system }

Baza danych, Redis, magazyn wektorów i dostęp do modeli - te same sprawdzenia, które wykonuje `agenticos cmd doctor`, na jednej stronie.

![System](assets/screens/light/admin-system.webp#only-light)
![System](assets/screens/dark/admin-system.webp#only-dark)

### Deployment { #deployment }

Własna tożsamość i polityka tego wdrożenia: rejestracja, zaproszenia, komunikaty i to, co spotyka odwiedzający po raz pierwszy.

![Deployment](assets/screens/light/admin-deployment.webp#only-light)
![Deployment](assets/screens/dark/admin-deployment.webp#only-dark)

## Czego jeszcze tu nie ma { #what-is-not-here-yet }

- **Jasna połowa Buildera** - tych osiem ujęć istnieje tylko w ciemnym motywie.
- **Logowanie i onboarding**, czyli to, co odwiedzający faktycznie spotyka za
  pierwszym razem.

## Podsumowanie { #recap }

- 27 modułów ma oba motywy w `docs/assets/screens/`, pod tą samą nazwą; osiem
  ekranów Buildera jest tylko w ciemnym.
- Na tej stronie obraz zapisuje się dwa razy, z `#only-light` i `#only-dark`;
  Material pokazuje ten, który pasuje do palety czytelnika.
- W README ta sama para trafia do `<picture>` z
  `media="(prefers-color-scheme: dark)"`, i tak właśnie robi to GitHub.
- Parsowanie to ustawienie, które warto znać, zanim cokolwiek wgrasz: parser i
  rozmiar fragmentu decydują o tym, czy na pytanie o tabelę da się w ogóle
  odpowiedzieć.
