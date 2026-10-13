---
source_sha: "760ca1f20862"
---

# Każdy ekran w konsoli { #every-screen-in-the-console }

Poniżej opisano moduły konsoli. Zrzuty poprzedniej wersji interfejsu usunięto; oznaczone miejsca zostaną uzupełnione nowymi ujęciami w jasnym i ciemnym motywie.

## Demo produktu { #product-demo }

Aktualne zmontowane demo pokazuje OSS Launch Planner: zadanie wykorzystujące brief z Notion i informacje z GitHuba, interaktywny artefakt oraz link do udostępnienia. Usunięto czas oczekiwania; raport zawiera dane z chwili wykonania.

<video src="https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953" controls muted playsinline style="width:100%"></video>

## Gdzie lądujesz { #where-you-land }

### Dashboard { #dashboard }

Układalne widgety, najpierw całe wdrożenie, a potem ta organizacja. Runy, wydatki, kondycja usług i jakość odpowiedzi; każda karta jest bramkowana uprawnieniem, którego wymagają jej własne dane, więc karta, której podstawowego odczytu nie możesz wykonać, to karta, której nie dostajesz do wyboru.

> **Miejsce na zrzut — Dashboard.**

### Chat, w trakcie runa { #chat-mid-run }

Agent w trakcie myślenia, a potem komendy powłoki, które faktycznie wykonał w sandboksie, każda do rozwinięcia. Przejrzystość jest tu produktem: to, co zrobiło narzędzie, jest na ekranie, a nie w logu, który może przeczytać ktoś inny.

> **Miejsce na zrzut — Chat, w trakcie runa.**

## Budowanie agenta { #building-an-agent }

### Agents { #agents }

Katalog. Każdy agent niesie wersję, która jest na żywo, informację o tym, kto może do niego sięgnąć, i o tym, czy czeka wersja robocza. Agent jest konfiguracją, a nie kodem - i dlatego tę listę może edytować ten, kto zna odpowiedź.

> **Miejsce na zrzut — Agents.**

### Agent templates { #agent-templates }

Szablony według branży, nad katalogiem. Zainstalowanie jednego tworzy wersję roboczą, którą kończysz i publikujesz; nic nie działa, dopóki tego nie zrobisz.

> **Miejsce na zrzut — Agent templates.**

### Skills { #skills }

Know-how spisane raz i dzielone przez każdego związanego z nim agenta - jak obsługuje się zwroty, jaki jest styl firmy. Zedytuj je tutaj, a każdy związany z nim agent jest aktualny przy swoim następnym runie.

> **Miejsce na zrzut — Skills.**

### Skill gallery { #skill-gallery }

Skille według branży. Instalacja kopiuje jeden do Twojej organizacji, gdzie możesz go edytować - kopia, więc źródło nie może zmienić tego, co mówią Twoi agenci.

> **Miejsce na zrzut — Skill gallery.**

### Jeden skill { #one-skill }

Otwarty do edycji, ze swoją kategorią. Nazwa, którą posługuje się model, jest ustalana przy tworzeniu i nie może się zmienić; wszystko inne tutaj może.

> **Miejsce na zrzut — Jeden skill.**

### Context { #context }

Stały kontekst, z którego może czerpać każdy agent - słownik pojęć, polityka, ton marki. Wstrzykiwany do promptu albo czytany na żądanie, i aktualny w chwili, w której go zedytujesz.

> **Miejsce na zrzut — Context.**

## Wewnątrz jednego agenta { #inside-one-agent }

Builder, zakładka po zakładce. Nowe zrzuty aktualnego interfejsu są w przygotowaniu.

### Build { #build }

Instrukcje, model i endpoint. Zachowanie mieszka tutaj, a nie w kodzie, w Markdownie, z którego model czyta strukturę - a nagłówek niesie `published` obok `Draft differs from v40`, i o to właśnie chodzi: edytowanie nie wydaje.

> **Miejsce na zrzut — Build.**

### Toolbox { #toolbox }

Każda capability jako przełącznik - wyszukiwanie w wiedzy, przeglądarka, Python w sandboksie, wykresy, delegacja - a obok każdego bramka approvalu per narzędzie. Konfiguracja sięga wyłącznie tego, co zarejestrował kod.

> **Miejsce na zrzut — Toolbox.**

### MCP servers { #mcp-servers }

Do których połączeń ten agent może sięgnąć i do których z ich narzędzi. Lista organizacji nadal go ogranicza; agent może zawęzić się wewnątrz niej i nie może sięgnąć poza nią.

> **Miejsce na zrzut — MCP servers.**

### Limits { #limits }

Jeden limit miesięczny i sufit kroków. Limit jest sprawdzany przed każdym żądaniem do modelu, a limit kroków łapie tę drugą rozbieganą sytuację - pętlę narzędzia, która jest tania na wywołanie i nigdy się nie kończy.

> **Miejsce na zrzut — Limits.**

### Availability { #availability }

Gdzie ten agent odpowiada: dashboard i API zawsze, plus każdy bot czatowy tutaj z nim związany. Agenta da się wywołać przez `@handle` tylko na tych botach, z którymi jest związany.

> **Miejsce na zrzut — Availability.**

### Routines, na agencie { #routines-on-the-agent }

Co robi, gdy nikt nie pisze, na tej samej zakładce - harmonogram, który da się wstrzymać, albo trigger zdarzeniowy.

> **Miejsce na zrzut — Routines, na agencie.**

### History { #history }

Każda wersja, jaką ten agent miał. Ta, która była na żywo w marcu, nadal jest czytelna, i to właśnie czyni z rollbacku wybór, a nie projekt archeologiczny.

> **Miejsce na zrzut — History.**

### Visual map { #visual-map }

Ten sam agent jako graf: co do niego sięga i po co on sięga. Przerywana ramka to coś, do czego nic nie jest podpięte - budżet bez własnego sufitu czyta się jako luka, a nie jako wartość domyślna.

> **Miejsce na zrzut — Visual map.**
## Knowledge { #knowledge }

### Knowledge bases { #knowledge-bases }

Kolekcje. Zgrupuj powiązane dokumenty w jedną, a potem wybierz na czacie, które kolekcje agent może przeszukiwać.

> **Miejsce na zrzut — Knowledge bases.**

### Jedna kolekcja { #a-collection }

Jej dokumenty, liczby fragmentów i wszystko, czego nie udało się zaingestować, wraz z powodem. To granice fragmentów są tym, do czego dopasowuje się wyszukiwanie, więc dokument wgrany ponownie po zmianie ustawień jest dzielony na nowo.

> **Miejsce na zrzut — Jedna kolekcja.**

### Parsowanie, per wgranie { #parsing-per-upload }

Wybór, którego nikt inny nie wystawia: **PyMuPDF**, **LiteParse** albo **LlamaParse**, strategia dzielenia na fragmenty, rozmiar fragmentu i zakładka, OCR i jego język. Ustawiane na kolekcji i nadpisywalne przy następnym pliku, który dodasz - bo zeskanowany cennik i runbook w Markdownie nie chcą tego samego parsera, a zły parser jest różnicą między odpowiedzią a odmową.

> **Miejsce na zrzut — Parsowanie, per wgranie.**

## Co się wydarzyło i co czeka { #what-happened-and-what-is-waiting }

### Runs { #runs }

Każdy run, który wykonała ta organizacja, ze swoim statusem, powierzchnią, modelem, osobą i kosztem. Run jest procesem: startuje, można go zatrzymać i zostawia zapis.

> **Miejsce na zrzut — Runs.**

### Jeden run, otwarty { #one-run-opened }

Tokeny wejściowe i wyjściowe, koszt do czterech miejsc po przecinku, ile to trwało oraz oś czasu każdej tury i każdego wywołania narzędzia. Czat, w którym to się wydarzyło, jest o jedno kliknięcie stąd.

> **Miejsce na zrzut — Jeden run, otwarty.**

### Approvals { #approvals }

Wszystko, co czeka na człowieka, razem z tym, co agent zamierza zrobić. Approval jest rozstrzygany dokładnie raz - druga decyzja na rozstrzygniętym jest odrzucana, i to ten szczegół sprawia, że warto mieć tę bramkę.

> **Miejsce na zrzut — Approvals.**

### Spend { #spend }

Ile faktycznie wydano, w podziale na okresy. Budżet jest sprawdzany *przed* żądaniem do modelu, a nie sumowany po fakcie, więc run, który go przekroczy, zatrzymuje się w środku odpowiedzi i mimo to zapisuje swój koszt.

> **Miejsce na zrzut — Spend.**

### Routines { #routines }

Co agenci robią, gdy nikt nie pisze - według harmonogramu albo kiedy przyjdzie zdarzenie. Te runy są budżetowane, zatwierdzane i audytowane jak każde inne.

> **Miejsce na zrzut — Routines.**

### Nowy trigger zdarzeniowy { #a-new-event-trigger }

Nazwanie zdarzenia, które uruchamia run, nad listą rutyn.

> **Miejsce na zrzut — Nowy trigger zdarzeniowy.**

## Organizacja { #the-organization }

### Organizations { #organizations }

Przełączaj się między nimi, zarządzaj członkami i twórz nowe. Autorytet wewnątrz organizacji to wiersz członkostwa plus katalog uprawnień - na użytkowniku nie ma kolumny z rolą.

> **Miejsce na zrzut — Organizations.**

### Vault { #vault }

Każdy klucz, który ta organizacja przechowała, zapieczętowany per tenant. Wymienialny, nigdy więcej odczytywalny; a rotacja jest niewidoczna dla opublikowanego agenta, który odwołuje się do sekretu, a nie do jego wartości.

> **Miejsce na zrzut — Vault.**

### MCP servers { #mcp-servers_1 }

Podłącz dowolny serwer MCP po URL, a jego narzędzia stają się przełącznikami w Builderze. Podłącz go dla organizacji, a może z niego korzystać każdy agent; podłącz go dla siebie, a zostaje w Twoim własnym czacie.

> **Miejsce na zrzut — MCP servers.**

### Channels { #channels }

Platformy czatowe, na których odpowiada ta organizacja - Slack, Telegram, Mattermost. Bot obsługuje każdego związanego z nim agenta, a to powiązanie tworzy się na zakładce Availability tego agenta.

> **Miejsce na zrzut — Channels.**

### Sandboxes { #sandboxes }

Miejsce, w którym agenci tej organizacji uruchamiają komendy powłoki i trzymają pliki. Agent nazywa połączenie po id, więc przeniesienie się na inny host to jedna edycja tutaj, a nie ponowna publikacja każdego agenta.

> **Miejsce na zrzut — Sandboxes.**

### Workspaces { #workspaces }

Pliki, które agenci trzymają dla Ciebie. Workspace to przestrzeń robocza - jest kasowany razem z rozmową, do której należy, i nie jest miejscem na przechowywanie czegokolwiek trwałego.

> **Miejsce na zrzut — Workspaces.**

## Administracja wdrożeniem { #deployment-administration }

### Users { #users }

Każdy, kto może zalogować się do tego wdrożenia, oraz flaga administratora aplikacji, która jest niezależna od jakiejkolwiek roli w organizacji.

> **Miejsce na zrzut — Users.**

### All organizations { #all-organizations }

Każdy tenant w tym wdrożeniu, ze swoim właścicielem, członkami i agentami.

> **Miejsce na zrzut — All organizations.**

### System { #system }

Baza danych, Redis, magazyn wektorów, dostęp do modeli i zadania cykliczne - te same sprawdzenia, które wykonuje `agenticos cmd doctor`, na jednej stronie.

> **Miejsce na zrzut — System.**

### Deployment { #deployment }

Własna tożsamość i polityka tego wdrożenia: rejestracja, zaproszenia, komunikaty i to, co spotyka odwiedzający po raz pierwszy.

> **Miejsce na zrzut — Deployment.**

## Czego jeszcze tu nie ma { #what-is-not-here-yet }

Nowe zrzuty aktualnego interfejsu są w przygotowaniu, w tym Buildera, logowania i onboardingu.

## Podsumowanie { #recap }

Aktualny film znajduje się powyżej. Oznaczone miejsca wskazują ekrany do uchwycenia; dodając je, użyj tych samych kadrów w jasnym i ciemnym motywie.
