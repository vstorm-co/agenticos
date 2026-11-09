---
source_sha: "12c6776e073b"
---

# Każdy ekran w konsoli { #every-screen-in-the-console }

Aktualne screeny z organizacji demonstracyjnej Northwind Labs, wykonane 2 listopada 2026 w AgenticOS 1.35.3. Firmy, wyniki sprzedaży, dostawy i urządzenia są fikcyjne. Przygotowane Visuals są oznaczone; nie sugerują połączenia z CRM, ERP ani maszynami. Kadry zachowują pełne okno aplikacji.

## Gdzie lądujesz { #where-you-land }

### Dashboard { #dashboard }

Twój własny widok, układalny widok organizacji, widok jednej grupy i - dla admina deploymentu - całego wdrożenia, wybierane na górze. Runy, wydatki, kondycja usług i jakość odpowiedzi; każda karta jest bramkowana uprawnieniem, którego wymagają jej własne dane, więc karta, której podstawowego odczytu nie możesz wykonać, to karta, której nie dostajesz do wyboru.

![Dashboard](assets/screens/light/dashboard.webp?v=20261102-industrial#only-light)
![Dashboard](assets/screens/dark/dashboard.webp?v=20261102-industrial#only-dark)

### Chat { #chat }

Przygotowany przegląd sprzedaży z Revenue Pulse renderowanym przez Visuals. Przychód, cele i udział zespołu zmieniają się wraz z filtrami regionu i okresu. Rozmowa i dane są seedowanym przykładem, a nie dowodem wygenerowania dashboardu przez model.

![Chat](assets/screens/light/chat.webp?v=20261102-industrial#only-light)
![Chat](assets/screens/dark/chat.webp?v=20261102-industrial#only-dark)

## Budowanie agenta { #building-an-agent }

### Agents { #agents }

Katalog. Każdy agent niesie wersję, która jest na żywo, informację o tym, kto może do niego sięgnąć, i o tym, czy czeka wersja robocza. Agent jest konfiguracją, a nie kodem - i dlatego tę listę może edytować ten, kto zna odpowiedź.

![Agents](assets/screens/light/agents.webp?v=20261102-industrial#only-light)
![Agents](assets/screens/dark/agents.webp?v=20261102-industrial#only-dark)

### Agent templates { #agent-templates }

Szablony według branży, nad katalogiem. Zainstalowanie jednego tworzy wersję roboczą, którą kończysz i publikujesz; nic nie działa, dopóki tego nie zrobisz.

![Agent templates](assets/screens/light/agent-templates.webp?v=20261102-industrial#only-light)
![Agent templates](assets/screens/dark/agent-templates.webp?v=20261102-industrial#only-dark)

### Skills { #skills }

Know-how spisane raz i dzielone przez każdego związanego z nim agenta - jak obsługuje się zwroty, jaki jest styl firmy. Zedytuj je tutaj, a każdy związany z nim agent jest aktualny przy swoim następnym runie.

![Skills](assets/screens/light/skills.webp?v=20261102-industrial#only-light)
![Skills](assets/screens/dark/skills.webp?v=20261102-industrial#only-dark)

### Skill gallery { #skill-gallery }

Skille według branży. Instalacja kopiuje jeden do Twojej organizacji, gdzie możesz go edytować - kopia, więc źródło nie może zmienić tego, co mówią Twoi agenci.

![Skill gallery](assets/screens/light/skill-gallery.webp?v=20261102-industrial#only-light)
![Skill gallery](assets/screens/dark/skill-gallery.webp?v=20261102-industrial#only-dark)

### Jeden skill { #one-skill }

Otwarty do edycji, ze swoją kategorią. Nazwa, którą posługuje się model, jest ustalana przy tworzeniu i nie może się zmienić; wszystko inne tutaj może.

![Jeden skill](assets/screens/light/skill-detail.webp?v=20261102-industrial#only-light)
![Jeden skill](assets/screens/dark/skill-detail.webp?v=20261102-industrial#only-dark)

### Context { #context }

Stały kontekst, z którego może czerpać każdy agent - słownik pojęć, polityka, ton marki. Wstrzykiwany do promptu albo czytany na żądanie, i aktualny w chwili, w której go zedytujesz.

![Context](assets/screens/light/context.webp?v=20261102-industrial#only-light)
![Context](assets/screens/dark/context.webp?v=20261102-industrial#only-dark)

## Wewnątrz jednego agenta { #inside-one-agent }

Builder, zakładka po zakładce.

### Build { #build }

Instrukcje, model i endpoint. Zachowanie mieszka tutaj, a nie w kodzie, w Markdownie, z którego model czyta strukturę - a nagłówek niesie `published` obok `Draft differs from agent v40`, i o to właśnie chodzi: edytowanie nie wydaje.

![Build](assets/screens/light/agent-builder.webp?v=20261102-industrial#only-light)
![Build](assets/screens/dark/agent-builder.webp?v=20261102-industrial#only-dark)

### Toolbox { #toolbox }

Każda capability jako przełącznik - wyszukiwanie w wiedzy, przeglądarka, Python w sandboksie, wykresy, delegacja - a obok każdego bramka approvalu per narzędzie. Konfiguracja sięga wyłącznie tego, co zarejestrował kod.

![Toolbox](assets/screens/light/agent-toolbox.webp?v=20261102-industrial#only-light)
![Toolbox](assets/screens/dark/agent-toolbox.webp?v=20261102-industrial#only-dark)

### MCP servers { #mcp-servers }

Do których połączeń ten agent może sięgnąć i do których z ich narzędzi. Lista organizacji nadal go ogranicza; agent może zawęzić się wewnątrz niej i nie może sięgnąć poza nią.

![MCP servers](assets/screens/light/agent-mcp.webp?v=20261102-industrial#only-light)
![MCP servers](assets/screens/dark/agent-mcp.webp?v=20261102-industrial#only-dark)

### Limits { #limits }

Jeden limit miesięczny i sufit kroków. Limit jest sprawdzany przed każdym żądaniem do modelu, a limit kroków łapie tę drugą rozbieganą sytuację - pętlę narzędzia, która jest tania na wywołanie i nigdy się nie kończy.

![Limits](assets/screens/light/agent-limits.webp?v=20261102-industrial#only-light)
![Limits](assets/screens/dark/agent-limits.webp?v=20261102-industrial#only-dark)

### Availability { #availability }

Gdzie ten agent odpowiada: dashboard i API zawsze, plus każdy bot czatowy tutaj z nim związany. Agenta da się wywołać przez `@handle` tylko na tych botach, z którymi jest związany.

![Availability](assets/screens/light/agent-availability.webp?v=20261102-industrial#only-light)
![Availability](assets/screens/dark/agent-availability.webp?v=20261102-industrial#only-dark)

### Routines, na agencie { #routines-on-the-agent }

Co robi, gdy nikt nie pisze, na tej samej zakładce - harmonogram, który da się wstrzymać, albo trigger zdarzeniowy.

![Routines, na agencie](assets/screens/light/agent-routines.webp?v=20261102-industrial#only-light)
![Routines, na agencie](assets/screens/dark/agent-routines.webp?v=20261102-industrial#only-dark)

### History { #history }

Każda wersja, jaką ten agent miał. Ta, która była na żywo w marcu, nadal jest czytelna, i to właśnie czyni z rollbacku wybór, a nie projekt archeologiczny.

![History](assets/screens/light/agent-history.webp?v=20261102-industrial#only-light)
![History](assets/screens/dark/agent-history.webp?v=20261102-industrial#only-dark)

### Visual map { #visual-map }

Ten sam agent jako graf: co do niego sięga i po co on sięga. Przerywana ramka to coś, do czego nic nie jest podpięte - budżet bez własnego sufitu czyta się jako luka, a nie jako wartość domyślna.

![Visual map](assets/screens/light/agent-map.webp?v=20261102-industrial#only-light)
![Visual map](assets/screens/dark/agent-map.webp?v=20261102-industrial#only-dark)

## Workflows i tabele { #workflows-and-tables }

### Workflows { #workflows }

Katalog automatyzacji, po jednej karcie na każdą: jej status, kto może do niej dotrzeć, czy ma żywą wersję i kiedy ostatnio ją edytowano, a jej runy, edytor i kopia są jedno kliknięcie dalej.

![Workflows](assets/screens/light/workflows.webp?v=20261102-industrial#only-light)
![Workflows](assets/screens/dark/workflows.webp?v=20261102-industrial#only-dark)

### Edytor workflow { #the-workflow-editor }

Kanwa ma całą szerokość: graf jako karty mówiące, do czego ustawiony jest każdy krok albo do jakiej grupy należy, ustawienia kroku w oknie nad nią i każdy krok do dodania o jedno kliknięcie - albo jeden prawy przycisk - stąd. Pętla pokazuje, ile kroków zawiera jej ciało.

![Workflow editor](assets/screens/light/workflow-editor.webp?v=20261102-industrial#only-light)
![Workflow editor](assets/screens/dark/workflow-editor.webp?v=20261102-industrial#only-dark)

### Ciało pętli { #a-loops-body }

Wewnątrz pętli: bieżąca firma, mapowanie formujące jej rekord i krok zbierający wynik. Lokalny przykład przetwarza nazwy trzech fikcyjnych firm bez zewnętrznych poświadczeń.

![Workflow loop body](assets/screens/light/workflow-loop-body.webp?v=20261102-industrial#only-light)
![Workflow loop body](assets/screens/dark/workflow-loop-body.webp?v=20261102-industrial#only-dark)

### Runy { #runs }

Każdy run jednego workflow, od najnowszego: czy uruchomił draft czy opublikowaną wersję, co go uruchomiło, kiedy, jak długo trwał i ile kosztował. **Start a run** testuje draft z Twoim własnym inputem.

![Workflow runs](assets/screens/light/workflow-runs.webp?v=20261102-industrial#only-light)
![Workflow runs](assets/screens/dark/workflow-runs.webp?v=20261102-industrial#only-dark)

### Run { #a-run }

Jeden run tak, jak przebiegł: graf, który wykonał, z każdym krokiem oznaczonym tym, co zrobił, wyjście, którym odpowiedział, i każdy krok, który wykonał, iteracja po iteracji.

![Workflow run](assets/screens/light/workflow-run.webp?v=20261102-industrial#only-light)
![Workflow run](assets/screens/dark/workflow-run.webp?v=20261102-industrial#only-dark)

### Tabele { #tables }

Fikcyjny pipeline sprzedaży w Kanbanie: jedna szansa na kartę, pogrupowane według etapu. Agenci i workflowy pracują na tych samych typowanych rekordach; tablica jest tu głównym kadrem.

![Tables](assets/screens/light/table-kanban.webp?v=20261102-industrial#only-light)
![Tables](assets/screens/dark/table-kanban.webp?v=20261102-industrial#only-dark)

## Knowledge { #knowledge }

### Knowledge bases { #knowledge-bases }

Kolekcje. Zgrupuj powiązane dokumenty w jedną, a potem wybierz na czacie, które kolekcje agent może przeszukiwać.

![Knowledge bases](assets/screens/light/knowledge-bases.webp?v=20261102-industrial#only-light)
![Knowledge bases](assets/screens/dark/knowledge-bases.webp?v=20261102-industrial#only-dark)

### Jedna kolekcja { #a-collection }

Jej dokumenty, liczby fragmentów i wszystko, czego nie udało się zaingestować, wraz z powodem. To granice fragmentów są tym, do czego dopasowuje się wyszukiwanie, więc dokument wgrany ponownie po zmianie ustawień jest dzielony na nowo.

![Jedna kolekcja](assets/screens/light/knowledge-collection.webp?v=20261102-industrial#only-light)
![Jedna kolekcja](assets/screens/dark/knowledge-collection.webp?v=20261102-industrial#only-dark)

### Parsowanie, per wgranie { #parsing-per-upload }

Wybór, którego nikt inny nie wystawia: **PyMuPDF**, **LiteParse** albo **LlamaParse**, strategia dzielenia na fragmenty, rozmiar fragmentu i zakładka, OCR i jego język. Ustawiane na kolekcji i nadpisywalne przy następnym pliku, który dodasz - bo zeskanowany cennik i runbook w Markdownie nie chcą tego samego parsera, a zły parser jest różnicą między odpowiedzią a odmową.

![Parsowanie, per wgranie](assets/screens/light/kb-parse-options.webp?v=20261102-industrial#only-light)
![Parsowanie, per wgranie](assets/screens/dark/kb-parse-options.webp?v=20261102-industrial#only-dark)

## Testowanie i poprawianie agenta { #testing-and-improving-an-agent }

Te ekrany pochodzą z drugiej organizacji demo, Demo, i jej agenta Refund desk: pytania sklepu Acme o zwroty i dostawy, oceniane checkami i sędzią. Pytania są wymyślone; odpowiedzi, oceny i sesje poprawiania to prawdziwe runy.

### Datasety { #datasets }

Pytania testowe, na których sprawdzane są twoje agenty. Każda zmiana przypadków datasetu tworzy nową wersję, więc dwa runy ewaluacji porównuje się na tych samych pytaniach albo wcale.

![Datasety](assets/screens/light/datasets.webp#only-light)
![Datasety](assets/screens/dark/datasets.webp#only-dark)

### Przypadki datasetu { #a-datasets-cases }

Każde pytanie ze źródłem, liczbą checków i informacją, czy poprawianie użyje go do pisania zmian, czy odłoży je do sprawdzenia wyniku.

![Przypadki datasetu](assets/screens/light/dataset-cases.webp#only-light)
![Przypadki datasetu](assets/screens/dark/dataset-cases.webp#only-dark)

### Ocenianie { #grading }

Co sprawia, że odpowiedź przechodzi: checki, które dostaje każdy przypadek, sędzia, który ją ocenia, jego kryteria i próg. Checki nic nie kosztują; każda ocena sędziego to run na modelu.

![Ocenianie](assets/screens/light/dataset-grading.webp#only-light)
![Ocenianie](assets/screens/dark/dataset-grading.webp#only-dark)

### Ewaluacje datasetu { #a-datasets-evals }

Każdy run na tym datasecie jako linia odsetka zaliczeń dla każdego agenta; kolor punktu mówi, czy run naprawił, czy zepsuł przypadki, a pod spodem jest lista runów.

![Ewaluacje datasetu](assets/screens/light/dataset-evals.webp#only-light)
![Ewaluacje datasetu](assets/screens/dark/dataset-evals.webp#only-dark)

### Jeden run ewaluacji { #one-eval-run }

Najpierw werdykt w jednym zdaniu, potem odsetek zaliczeń przed i po, koszt wobec szacunku i przypadki, które się zmieniły. Odpowiedź, która przy ponownym pytaniu wyszła inaczej, nie liczy się jako zmiana.

![Jeden run ewaluacji](assets/screens/light/eval-run.webp#only-light)
![Jeden run ewaluacji](assets/screens/dark/eval-run.webp#only-dark)

### Ewaluacje agenta { #an-agents-evals }

Ten sam trend od strony agenta: każdy dataset, na którym go sprawdzano, jedna linia na dataset, a obok przycisk uruchomienia ewaluacji.

![Ewaluacje agenta](assets/screens/light/agent-evals.webp#only-light)
![Ewaluacje agenta](assets/screens/dark/agent-evals.webp#only-dark)

### Popraw { #improve }

Początek poprawiania: odpowiedzi ocenione negatywnie, nieudane odpowiedzi testowe, podział pytań testowych na te, które pomagają pisać zmiany, i te odłożone do sprawdzenia, oraz koszt pierwszego kroku. Każdy kolejny krok jest wyceniany, zanim go naciśniesz.

![Popraw](assets/screens/light/improve-start.webp#only-light)
![Popraw](assets/screens/dark/improve-start.webp#only-dark)

### Popraw · Zrozumienie { #improve-understand }

Co poszło nie tak, posortowane na to, co agent może poprawić, i to, czego brakuje w bazie wiedzy: jedna karta na pytanie, z ocenami opisanymi słowami. Sesja zatrzymuje się tu, żebyś mógł to obejrzeć.

![Popraw · Zrozumienie](assets/screens/light/improve-understand.webp#only-light)
![Popraw · Zrozumienie](assets/screens/dark/improve-understand.webp#only-dark)

### Popraw · Zmiany { #improve-changes }

Zmiany napisane przez pomocnika jako diff własnego tekstu agenta, z uzasadnieniem i tym, na czym się opierają. Możesz przeredagować zmianę, zanim zostanie sprawdzona; sprawdzenie mierzy twoje sformułowanie.

![Popraw · Zmiany](assets/screens/light/improve-changes.webp#only-light)
![Popraw · Zmiany](assets/screens/dark/improve-changes.webp#only-dark)

### Popraw · Wynik { #improve-result }

Do czego doszła sesja: każda próba z liczbą pytań naprawionych i zepsutych wśród odłożonych, jej koszt i wybór próby do zachowania. Nic nie trafia na produkcję, dopóki człowiek tego nie zaakceptuje.

![Popraw · Wynik](assets/screens/light/improve-result.webp#only-light)
![Popraw · Wynik](assets/screens/dark/improve-result.webp#only-dark)

### Luki w wiedzy { #knowledge-gaps }

Pytania, dla których agent przeszukał bazy wiedzy i nie znalazł nic trafnego, pogrupowane w tematy. Nic nie trafia do bazy wiedzy samo; dokument pisze i dodaje człowiek.

![Luki w wiedzy](assets/screens/light/knowledge-gaps.webp#only-light)
![Luki w wiedzy](assets/screens/dark/knowledge-gaps.webp#only-dark)


## Co się wydarzyło i co czeka { #what-happened-and-what-is-waiting }

### Runs { #runs }

Każdy run, który wykonała ta organizacja, ze swoim statusem, powierzchnią, modelem, osobą i kosztem. Run jest procesem: startuje, można go zatrzymać i zostawia zapis.

![Runs](assets/screens/light/activity.webp?v=20261102-industrial#only-light)
![Runs](assets/screens/dark/activity.webp?v=20261102-industrial#only-dark)

### Jeden run, otwarty { #one-run-opened }

Tokeny wejściowe i wyjściowe, koszt do czterech miejsc po przecinku, ile to trwało oraz oś czasu każdej tury i każdego wywołania narzędzia. Czat, w którym to się wydarzyło, jest o jedno kliknięcie stąd.

![Jeden run, otwarty](assets/screens/light/run-detail.webp?v=20261102-industrial#only-light)
![Jeden run, otwarty](assets/screens/dark/run-detail.webp?v=20261102-industrial#only-dark)

### Approvals { #approvals }

Wszystko, co czeka na człowieka, razem z tym, co agent zamierza zrobić. Approval jest rozstrzygany dokładnie raz - druga decyzja na rozstrzygniętym jest odrzucana, i to ten szczegół sprawia, że warto mieć tę bramkę.

![Approvals](assets/screens/light/approvals.webp?v=20261102-industrial#only-light)
![Approvals](assets/screens/dark/approvals.webp?v=20261102-industrial#only-dark)

### Spend { #spend }

Ile faktycznie wydano, w podziale na okresy. Budżet jest sprawdzany _przed_ żądaniem do modelu, a nie sumowany po fakcie, więc run, który go przekroczy, zatrzymuje się w środku odpowiedzi i mimo to zapisuje swój koszt.

![Spend](assets/screens/light/spend.webp?v=20261102-industrial#only-light)
![Spend](assets/screens/dark/spend.webp?v=20261102-industrial#only-dark)

### Routines { #routines }

Co agenci robią, gdy nikt nie pisze - według harmonogramu albo kiedy przyjdzie zdarzenie. Te runy są budżetowane, zatwierdzane i audytowane jak każde inne.

![Routines](assets/screens/light/routines.webp?v=20261102-industrial#only-light)
![Routines](assets/screens/dark/routines.webp?v=20261102-industrial#only-dark)

### Nowy trigger zdarzeniowy { #a-new-event-trigger }

Nazwanie zdarzenia, które uruchamia run, nad listą rutyn.

![Nowy trigger zdarzeniowy](assets/screens/light/routine-event-trigger.webp?v=20261102-industrial#only-light)
![Nowy trigger zdarzeniowy](assets/screens/dark/routine-event-trigger.webp?v=20261102-industrial#only-dark)

### Apps { #apps }

Strony opublikowane przez agentów - raporty, małe dashboardy, podsumowania. Każda zachowuje swój link, gdy agent publikuje ją ponownie, a jej wcześniejsze wersje można dalej czytać.

![Apps](assets/screens/light/apps.webp?v=20261102-industrial#only-light)
![Apps](assets/screens/dark/apps.webp?v=20261102-industrial#only-dark)

### Jedna appka { #one-app }

Northline łączy mapę dostawców w Europie, wyjątki dostaw i okna montażowe. Można zasymulować opóźnienie, filtrować dostawy i sprawdzić zależność. To przygotowana lokalna aplikacja planistyczna, bez połączenia z ERP i przewoźnikami.

![Northline](assets/screens/light/app-manufacturing.webp?v=20261102-industrial#only-light)
![Northline](assets/screens/dark/app-manufacturing.webp?v=20261102-industrial#only-dark)

### Motor Atlas { #motor }

Koncepcyjny widok rozstrzelony silnika z wyborem komponentów, regulacją rozsunięcia, fikcyjnym zestawieniem części i przykładową telemetrią. To interaktywne objaśnienie, a nie rysunek CAD, diagnoza lub instrukcja serwisowa.

![Motor Atlas](assets/screens/light/app-motor.webp?v=20261102-industrial#only-light)
![Motor Atlas](assets/screens/dark/app-motor.webp?v=20261102-industrial#only-dark)

### Revenue Pulse { #revenue }

Interaktywny przegląd sprzedaży: przychód względem celu, pipeline, udział zespołu i kolejne szanse. Sumy są liczone z fikcyjnych rekordów; filtry regionu i okresu działają lokalnie.

![Revenue Pulse](assets/screens/light/app-revenue.webp?v=20261102-industrial#only-light)
![Revenue Pulse](assets/screens/dark/app-revenue.webp?v=20261102-industrial#only-dark)

### Visuals { #visuals-in-the-conversation }

Przygotowany Visuals Revenue Pulse w prawdziwym rendererze chatu. Można zapisać go jako App; screen nie przedstawia nowego wykonania przez model ani dostępu do działającego CRM.

![Visuals](assets/screens/light/chat-hero.webp?v=20261102-industrial#only-light)
![Visuals](assets/screens/dark/chat-hero.webp?v=20261102-industrial#only-dark)

## Organizacja { #the-organization }

### Organizations { #organizations }

Przełączaj się między nimi, zarządzaj członkami i twórz nowe. Autorytet wewnątrz organizacji to wiersz członkostwa plus katalog uprawnień - na użytkowniku nie ma kolumny z rolą.

![Organizations](assets/screens/light/organizations.webp?v=20261102-industrial#only-light)
![Organizations](assets/screens/dark/organizations.webp?v=20261102-industrial#only-dark)

### Members { #members }

Ludzie jednej organizacji i ich role, razem z miesięcznym limitem wspólnym dla wszystkich jej agentów i ustawieniem, czy rozmowa może pominąć approvals.

![Members](assets/screens/light/members.webp?v=20261102-industrial#only-light)
![Members](assets/screens/dark/members.webp?v=20261102-industrial#only-dark)

### Roles { #roles }

Co może każda rola, jako macierz zdefiniowana w kodzie. Udostępnienie pojedynczego zasobu może poszerzyć dostęp ponad rolę; nigdy go nie zawęża.

![Roles](assets/screens/light/roles.webp?v=20261102-industrial#only-light)
![Roles](assets/screens/dark/roles.webp?v=20261102-industrial#only-dark)

### Groups { #groups }

Działy i zespoły. Udostępnij grupie agenta, bazę wiedzy, skill albo plik kontekstu, a każdy w niej może z niego korzystać - osoby spoza grupy nie.

![Groups](assets/screens/light/groups.webp?v=20261102-industrial#only-light)
![Groups](assets/screens/dark/groups.webp?v=20261102-industrial#only-dark)

### Vault { #vault }

Każdy klucz, który ta organizacja przechowała, zapieczętowany per tenant. Wymienialny, nigdy więcej odczytywalny; a rotacja jest niewidoczna dla opublikowanego agenta, który odwołuje się do sekretu, a nie do jego wartości.

![Vault](assets/screens/light/vault.webp?v=20261102-industrial#only-light)
![Vault](assets/screens/dark/vault.webp?v=20261102-industrial#only-dark)

### MCP servers { #mcp-servers_1 }

Podłącz dowolny serwer MCP po URL, a jego narzędzia stają się przełącznikami w Builderze. Podłącz go dla organizacji, a może z niego korzystać każdy agent; podłącz go dla siebie, a zostaje w Twoim własnym czacie.

![MCP servers](assets/screens/light/mcp-servers.webp?v=20261102-industrial#only-light)
![MCP servers](assets/screens/dark/mcp-servers.webp?v=20261102-industrial#only-dark)

### Channels { #channels }

Platformy czatowe, na których odpowiada ta organizacja - Slack, Teams, Telegram, Mattermost. Bot obsługuje każdego związanego z nim agenta, a to powiązanie tworzy się na zakładce Availability tego agenta.

![Channels](assets/screens/light/channels.webp?v=20261102-industrial#only-light)
![Channels](assets/screens/dark/channels.webp?v=20261102-industrial#only-dark)

### Sandboxes { #sandboxes }

Miejsce, w którym agenci tej organizacji uruchamiają komendy powłoki i trzymają pliki. Agent nazywa połączenie po id, więc przeniesienie się na inny host to jedna edycja tutaj, a nie ponowna publikacja każdego agenta.

![Sandboxes](assets/screens/light/sandboxes.webp?v=20261102-industrial#only-light)
![Sandboxes](assets/screens/dark/sandboxes.webp?v=20261102-industrial#only-dark)

### Documents { #documents }

Pliki, które agenci trzymają dla Ciebie. Workspace to przestrzeń robocza - jest kasowany razem z rozmową, do której należy, i nie jest miejscem na przechowywanie czegokolwiek trwałego.

![Documents](assets/screens/light/documents.webp?v=20261102-industrial#only-light)
![Documents](assets/screens/dark/documents.webp?v=20261102-industrial#only-dark)

### Twoje ustawienia { #your-settings }

Twój profil i konto, slash commands, pamięć, logowania, które agent przeglądarki trzyma dla Ciebie, powiadomienia, klucze API, klienci MCP i Architect - każde w osobnej zakładce.

![Twoje ustawienia](assets/screens/light/settings.webp?v=20261102-industrial#only-light)
![Twoje ustawienia](assets/screens/dark/settings.webp?v=20261102-industrial#only-dark)

## Administracja wdrożeniem { #deployment-administration }

### Users { #users }

Każdy, kto może zalogować się do tego wdrożenia, oraz flaga administratora aplikacji, która jest niezależna od jakiejkolwiek roli w organizacji.

![Users](assets/screens/light/admin-users.webp?v=20261102-industrial#only-light)
![Users](assets/screens/dark/admin-users.webp?v=20261102-industrial#only-dark)

### All organizations { #all-organizations }

Każdy tenant w tym wdrożeniu, ze swoim właścicielem, członkami i agentami.

![All organizations](assets/screens/light/admin-organizations.webp?v=20261102-industrial#only-light)
![All organizations](assets/screens/dark/admin-organizations.webp?v=20261102-industrial#only-dark)

### System { #system }

Baza danych, Redis, magazyn wektorów, dostęp do modeli i zadania cykliczne - te same sprawdzenia, które wykonuje `agenticos cmd doctor`, na jednej stronie.

![System](assets/screens/light/admin-system.webp?v=20261102-industrial#only-light)
![System](assets/screens/dark/admin-system.webp?v=20261102-industrial#only-dark)

### Deployment { #deployment }

Własna tożsamość i polityka tego wdrożenia: rejestracja, zaproszenia, komunikaty i to, co spotyka odwiedzający po raz pierwszy.

![Deployment](assets/screens/light/admin-deployment.webp?v=20261102-industrial#only-light)
![Deployment](assets/screens/dark/admin-deployment.webp?v=20261102-industrial#only-dark)

## Czego jeszcze tu nie ma { #what-is-not-here-yet }

Logowanie, onboarding przy pierwszym uruchomieniu i przewodnik w produkcie nie mają jeszcze zrzutów.

## Podsumowanie { #recap }

Każdy ekran jest pokazany w obu motywach, z jednej organizacji demonstracyjnej. `docs/assets/screens/capture.mjs` robi je wszystkie od nowa na dowolnym działającym wdrożeniu, więc zmieniony ekran to ponowne uruchomienie, a nie ręcznie robiony obrazek.
