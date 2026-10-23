---
source_sha: "4b8832761f4a"
---

# Każdy ekran w konsoli { #every-screen-in-the-console }

Każdy moduł konsoli, opisany i pokazany na zrzucie. Obrazy idą za motywem, w którym czytasz stronę - przełącz go w nagłówku, a przełączą się razem z nim. Pokazują organizację demonstracyjną Northwind Labs, której firma, dokumenty i liczby są zmyślone; rozmowy i opublikowana appka to prawdziwe runy jej agentów.

## Demo produktu { #product-demo }

Aktualne zmontowane demo pokazuje OSS Launch Planner: zadanie wykorzystujące brief z Notion i informacje z GitHuba, interaktywną aplikację oraz link do udostępnienia. Usunięto czas oczekiwania; raport zawiera dane z chwili wykonania.

<video src="https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953" controls muted playsinline style="width:100%"></video>

## Gdzie lądujesz { #where-you-land }

### Dashboard { #dashboard }

Twój własny widok, układalny widok organizacji, widok jednej grupy i - dla admina deploymentu - całego wdrożenia, wybierane na górze. Runy, wydatki, kondycja usług i jakość odpowiedzi; każda karta jest bramkowana uprawnieniem, którego wymagają jej własne dane, więc karta, której podstawowego odczytu nie możesz wykonać, to karta, której nie dostajesz do wyboru.

![Dashboard](assets/screens/light/dashboard.webp#only-light)
![Dashboard](assets/screens/dark/dashboard.webp#only-dark)

### Chat { #chat }

Arkusz na wejściu, opublikowana strona na wyjściu. Agent przeczytał CSV Pythonem, policzył liczby, opublikował dashboard przychodów jako appkę i napisał, które wartości sprawdził, a które oszacował. Każdy jego krok jest na ekranie i da się go rozwinąć - to, co zrobiło narzędzie, jest w rozmowie, a nie w logu, który czyta ktoś inny.

![Chat](assets/screens/light/chat.webp#only-light)
![Chat](assets/screens/dark/chat.webp#only-dark)

### Rozmowa głosowa { #a-voice-call }

Pole wiadomości zamienione w pasek rozmowy: co się teraz dzieje w rozmowie, jej czas na tle limitu, wykres fali dźwiękowej obu głosów, wyciszenie, „naciśnij, aby mówić” i Zakończ. Nad nim toczy się dalej konwersacja - napisy w wypowiadanej właśnie wiadomości, uruchomienia narzędzi i karta zatwierdzenia z dokładnymi argumentami i tym, co według transkrypcji powiedziałeś.

> **Miejsce na zrzut — Rozmowa głosowa.**

## Budowanie agenta { #building-an-agent }

### Agents { #agents }

Katalog. Każdy agent niesie wersję, która jest na żywo, informację o tym, kto może do niego sięgnąć, i o tym, czy czeka wersja robocza. Agent jest konfiguracją, a nie kodem - i dlatego tę listę może edytować ten, kto zna odpowiedź.

![Agents](assets/screens/light/agents.webp#only-light)
![Agents](assets/screens/dark/agents.webp#only-dark)

### Agent templates { #agent-templates }

Szablony według branży, nad katalogiem. Zainstalowanie jednego tworzy wersję roboczą, którą kończysz i publikujesz; nic nie działa, dopóki tego nie zrobisz.

![Agent templates](assets/screens/light/agent-templates.webp#only-light)
![Agent templates](assets/screens/dark/agent-templates.webp#only-dark)

### Skills { #skills }

Know-how spisane raz i dzielone przez każdego związanego z nim agenta - jak obsługuje się zwroty, jaki jest styl firmy. Zedytuj je tutaj, a każdy związany z nim agent jest aktualny przy swoim następnym runie.

![Skills](assets/screens/light/skills.webp#only-light)
![Skills](assets/screens/dark/skills.webp#only-dark)

### Skill gallery { #skill-gallery }

Skille według branży. Instalacja kopiuje jeden do Twojej organizacji, gdzie możesz go edytować - kopia, więc źródło nie może zmienić tego, co mówią Twoi agenci.

![Skill gallery](assets/screens/light/skill-gallery.webp#only-light)
![Skill gallery](assets/screens/dark/skill-gallery.webp#only-dark)

### Jeden skill { #one-skill }

Otwarty do edycji, ze swoją kategorią. Nazwa, którą posługuje się model, jest ustalana przy tworzeniu i nie może się zmienić; wszystko inne tutaj może.

![Jeden skill](assets/screens/light/skill-detail.webp#only-light)
![Jeden skill](assets/screens/dark/skill-detail.webp#only-dark)

### Context { #context }

Stały kontekst, z którego może czerpać każdy agent - słownik pojęć, polityka, ton marki. Wstrzykiwany do promptu albo czytany na żądanie, i aktualny w chwili, w której go zedytujesz.

![Context](assets/screens/light/context.webp#only-light)
![Context](assets/screens/dark/context.webp#only-dark)

## Wewnątrz jednego agenta { #inside-one-agent }

Builder, zakładka po zakładce.

### Build { #build }

Instrukcje, model i endpoint. Zachowanie mieszka tutaj, a nie w kodzie, w Markdownie, z którego model czyta strukturę - a nagłówek niesie `published` obok `Draft differs from v40`, i o to właśnie chodzi: edytowanie nie wydaje.

![Build](assets/screens/light/agent-builder.webp#only-light)
![Build](assets/screens/dark/agent-builder.webp#only-dark)

### Toolbox { #toolbox }

Każda capability jako przełącznik - wyszukiwanie w wiedzy, przeglądarka, Python w sandboksie, wykresy, delegacja - a obok każdego bramka approvalu per narzędzie. Konfiguracja sięga wyłącznie tego, co zarejestrował kod.

![Toolbox](assets/screens/light/agent-toolbox.webp#only-light)
![Toolbox](assets/screens/dark/agent-toolbox.webp#only-dark)

### MCP servers { #mcp-servers }

Do których połączeń ten agent może sięgnąć i do których z ich narzędzi. Lista organizacji nadal go ogranicza; agent może zawęzić się wewnątrz niej i nie może sięgnąć poza nią.

![MCP servers](assets/screens/light/agent-mcp.webp#only-light)
![MCP servers](assets/screens/dark/agent-mcp.webp#only-dark)

### Limits { #limits }

Jeden limit miesięczny i sufit kroków. Limit jest sprawdzany przed każdym żądaniem do modelu, a limit kroków łapie tę drugą rozbieganą sytuację - pętlę narzędzia, która jest tania na wywołanie i nigdy się nie kończy.

![Limits](assets/screens/light/agent-limits.webp#only-light)
![Limits](assets/screens/dark/agent-limits.webp#only-dark)

### Availability { #availability }

Gdzie ten agent odpowiada: dashboard i API zawsze, plus każdy bot czatowy tutaj z nim związany. Agenta da się wywołać przez `@handle` tylko na tych botach, z którymi jest związany.

![Availability](assets/screens/light/agent-availability.webp#only-light)
![Availability](assets/screens/dark/agent-availability.webp#only-dark)

### Routines, na agencie { #routines-on-the-agent }

Co robi, gdy nikt nie pisze, na tej samej zakładce - harmonogram, który da się wstrzymać, albo trigger zdarzeniowy.

![Routines, na agencie](assets/screens/light/agent-routines.webp#only-light)
![Routines, na agencie](assets/screens/dark/agent-routines.webp#only-dark)

### History { #history }

Każda wersja, jaką ten agent miał. Ta, która była na żywo w marcu, nadal jest czytelna, i to właśnie czyni z rollbacku wybór, a nie projekt archeologiczny.

![History](assets/screens/light/agent-history.webp#only-light)
![History](assets/screens/dark/agent-history.webp#only-dark)

### Visual map { #visual-map }

Ten sam agent jako graf: co do niego sięga i po co on sięga. Przerywana ramka to coś, do czego nic nie jest podpięte - budżet bez własnego sufitu czyta się jako luka, a nie jako wartość domyślna.

![Visual map](assets/screens/light/agent-map.webp#only-light)
![Visual map](assets/screens/dark/agent-map.webp#only-dark)

## Knowledge { #knowledge }

### Knowledge bases { #knowledge-bases }

Kolekcje. Zgrupuj powiązane dokumenty w jedną, a potem wybierz na czacie, które kolekcje agent może przeszukiwać.

![Knowledge bases](assets/screens/light/knowledge-bases.webp#only-light)
![Knowledge bases](assets/screens/dark/knowledge-bases.webp#only-dark)

### Jedna kolekcja { #a-collection }

Jej dokumenty, liczby fragmentów i wszystko, czego nie udało się zaingestować, wraz z powodem. To granice fragmentów są tym, do czego dopasowuje się wyszukiwanie, więc dokument wgrany ponownie po zmianie ustawień jest dzielony na nowo.

![Jedna kolekcja](assets/screens/light/knowledge-collection.webp#only-light)
![Jedna kolekcja](assets/screens/dark/knowledge-collection.webp#only-dark)

### Parsowanie, per wgranie { #parsing-per-upload }

Wybór, którego nikt inny nie wystawia: **PyMuPDF**, **LiteParse** albo **LlamaParse**, strategia dzielenia na fragmenty, rozmiar fragmentu i zakładka, OCR i jego język. Ustawiane na kolekcji i nadpisywalne przy następnym pliku, który dodasz - bo zeskanowany cennik i runbook w Markdownie nie chcą tego samego parsera, a zły parser jest różnicą między odpowiedzią a odmową.

![Parsowanie, per wgranie](assets/screens/light/kb-parse-options.webp#only-light)
![Parsowanie, per wgranie](assets/screens/dark/kb-parse-options.webp#only-dark)

## Co się wydarzyło i co czeka { #what-happened-and-what-is-waiting }

### Runs { #runs }

Każdy run, który wykonała ta organizacja, ze swoim statusem, powierzchnią, modelem, osobą i kosztem. Run jest procesem: startuje, można go zatrzymać i zostawia zapis.

![Runs](assets/screens/light/activity.webp#only-light)
![Runs](assets/screens/dark/activity.webp#only-dark)

### Jeden run, otwarty { #one-run-opened }

Tokeny wejściowe i wyjściowe, koszt do czterech miejsc po przecinku, ile to trwało oraz oś czasu każdej tury i każdego wywołania narzędzia. Czat, w którym to się wydarzyło, jest o jedno kliknięcie stąd.

![Jeden run, otwarty](assets/screens/light/run-detail.webp#only-light)
![Jeden run, otwarty](assets/screens/dark/run-detail.webp#only-dark)

### Approvals { #approvals }

Wszystko, co czeka na człowieka, razem z tym, co agent zamierza zrobić. Approval jest rozstrzygany dokładnie raz - druga decyzja na rozstrzygniętym jest odrzucana, i to ten szczegół sprawia, że warto mieć tę bramkę.

![Approvals](assets/screens/light/approvals.webp#only-light)
![Approvals](assets/screens/dark/approvals.webp#only-dark)

### Spend { #spend }

Ile faktycznie wydano, w podziale na okresy. Budżet jest sprawdzany *przed* żądaniem do modelu, a nie sumowany po fakcie, więc run, który go przekroczy, zatrzymuje się w środku odpowiedzi i mimo to zapisuje swój koszt.

![Spend](assets/screens/light/spend.webp#only-light)
![Spend](assets/screens/dark/spend.webp#only-dark)

### Routines { #routines }

Co agenci robią, gdy nikt nie pisze - według harmonogramu albo kiedy przyjdzie zdarzenie. Te runy są budżetowane, zatwierdzane i audytowane jak każde inne.

![Routines](assets/screens/light/routines.webp#only-light)
![Routines](assets/screens/dark/routines.webp#only-dark)

### Nowy trigger zdarzeniowy { #a-new-event-trigger }

Nazwanie zdarzenia, które uruchamia run, nad listą rutyn.

![Nowy trigger zdarzeniowy](assets/screens/light/routine-event-trigger.webp#only-light)
![Nowy trigger zdarzeniowy](assets/screens/dark/routine-event-trigger.webp#only-dark)

### Apps { #apps }

Strony opublikowane przez agentów - raporty, małe dashboardy, podsumowania. Każda zachowuje swój link, gdy agent publikuje ją ponownie, a jej wcześniejsze wersje można dalej czytać.

![Apps](assets/screens/light/apps.webp#only-light)
![Apps](assets/screens/dark/apps.webp#only-dark)

### Jedna appka { #one-app }

Dashboard przychodów z czatu powyżej, otwarty. Jest prywatny, dopóki ktoś go nie udostępni, a link publiczny to osobna decyzja, którą można cofnąć.

![Jedna appka](assets/screens/light/app-detail.webp#only-light)
![Jedna appka](assets/screens/dark/app-detail.webp#only-dark)

## Organizacja { #the-organization }

### Organizations { #organizations }

Przełączaj się między nimi, zarządzaj członkami i twórz nowe. Autorytet wewnątrz organizacji to wiersz członkostwa plus katalog uprawnień - na użytkowniku nie ma kolumny z rolą.

![Organizations](assets/screens/light/organizations.webp#only-light)
![Organizations](assets/screens/dark/organizations.webp#only-dark)

### Members { #members }

Ludzie jednej organizacji i ich role, razem z miesięcznym limitem wspólnym dla wszystkich jej agentów i ustawieniem, czy rozmowa może pominąć approvals.

![Members](assets/screens/light/members.webp#only-light)
![Members](assets/screens/dark/members.webp#only-dark)

### Roles { #roles }

Co może każda rola, jako macierz zdefiniowana w kodzie. Udostępnienie pojedynczego zasobu może poszerzyć dostęp ponad rolę; nigdy go nie zawęża.

![Roles](assets/screens/light/roles.webp#only-light)
![Roles](assets/screens/dark/roles.webp#only-dark)

### Groups { #groups }

Działy i zespoły. Udostępnij grupie agenta, bazę wiedzy, skill albo plik kontekstu, a każdy w niej może z niego korzystać - osoby spoza grupy nie.

![Groups](assets/screens/light/groups.webp#only-light)
![Groups](assets/screens/dark/groups.webp#only-dark)

### Vault { #vault }

Każdy klucz, który ta organizacja przechowała, zapieczętowany per tenant. Wymienialny, nigdy więcej odczytywalny; a rotacja jest niewidoczna dla opublikowanego agenta, który odwołuje się do sekretu, a nie do jego wartości.

![Vault](assets/screens/light/vault.webp#only-light)
![Vault](assets/screens/dark/vault.webp#only-dark)

### MCP servers { #mcp-servers_1 }

Podłącz dowolny serwer MCP po URL, a jego narzędzia stają się przełącznikami w Builderze. Podłącz go dla organizacji, a może z niego korzystać każdy agent; podłącz go dla siebie, a zostaje w Twoim własnym czacie.

![MCP servers](assets/screens/light/mcp-servers.webp#only-light)
![MCP servers](assets/screens/dark/mcp-servers.webp#only-dark)

### Channels { #channels }

Platformy czatowe, na których odpowiada ta organizacja - Slack, Teams, Telegram, Mattermost. Bot obsługuje każdego związanego z nim agenta, a to powiązanie tworzy się na zakładce Availability tego agenta.

![Channels](assets/screens/light/channels.webp#only-light)
![Channels](assets/screens/dark/channels.webp#only-dark)

### Sandboxes { #sandboxes }

Miejsce, w którym agenci tej organizacji uruchamiają komendy powłoki i trzymają pliki. Agent nazywa połączenie po id, więc przeniesienie się na inny host to jedna edycja tutaj, a nie ponowna publikacja każdego agenta.

![Sandboxes](assets/screens/light/sandboxes.webp#only-light)
![Sandboxes](assets/screens/dark/sandboxes.webp#only-dark)

### Documents { #documents }

Pliki, które agenci trzymają dla Ciebie. Workspace to przestrzeń robocza - jest kasowany razem z rozmową, do której należy, i nie jest miejscem na przechowywanie czegokolwiek trwałego.

![Documents](assets/screens/light/documents.webp#only-light)
![Documents](assets/screens/dark/documents.webp#only-dark)

### Twoje ustawienia { #your-settings }

Twój profil i konto, slash commands, pamięć, logowania, które agent przeglądarki trzyma dla Ciebie, powiadomienia, klucze API, klienci MCP i Architect - każde w osobnej zakładce.

![Twoje ustawienia](assets/screens/light/settings.webp#only-light)
![Twoje ustawienia](assets/screens/dark/settings.webp#only-dark)

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

Baza danych, Redis, magazyn wektorów, dostęp do modeli i zadania cykliczne - te same sprawdzenia, które wykonuje `agenticos cmd doctor`, na jednej stronie.

![System](assets/screens/light/admin-system.webp#only-light)
![System](assets/screens/dark/admin-system.webp#only-dark)

### Deployment { #deployment }

Własna tożsamość i polityka tego wdrożenia: rejestracja, zaproszenia, komunikaty i to, co spotyka odwiedzający po raz pierwszy.

![Deployment](assets/screens/light/admin-deployment.webp#only-light)
![Deployment](assets/screens/dark/admin-deployment.webp#only-dark)

## Czego jeszcze tu nie ma { #what-is-not-here-yet }

Logowanie, onboarding przy pierwszym uruchomieniu i przewodnik w produkcie nie mają jeszcze zrzutów.

## Podsumowanie { #recap }

Każdy ekran jest pokazany w obu motywach, z jednej organizacji demonstracyjnej. `docs/assets/screens/capture.mjs` robi je wszystkie od nowa na dowolnym działającym wdrożeniu, więc zmieniony ekran to ponowne uruchomienie, a nie ręcznie robiony obrazek.
