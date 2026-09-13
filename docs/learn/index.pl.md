---
source_sha: 80ee04abded5
---

# Nauka { #learn }

Poniższe sekcje to zalecany sposób nauki AgenticOS, po kolei. Czytaj je jak kurs:
każda zakłada te wcześniejsze, a żadna nie zakłada, że czytałeś kod źródłowy.

## Pierwsze kroki { #get-started }

Potrzebujesz działającego stacku i jednego agenta, który ci odpowiada. Około
dwudziestu minut.

<div class="grid cards" markdown>

- :material-download:{ .lg .middle } **[Instalacja](../install.md)**

    Docker Compose albo usługi ręcznie. Pięć minut do stacku, który otworzysz w
    przeglądarce.

- :material-rocket-launch:{ .lg .middle } **[Twój pierwszy agent](../first-agent.md)**

    Klucz providera, agent, opublikowana wersja, run, który coś kosztował.

- :material-lightbulb:{ .lg .middle } **[Pojęcia](../concepts.md)**

    Spec, wersja, ekspozycja, wyzwalacz, run. Pięć rzeczowników. Wszystko inne
    jest z nich zbudowane, więc to jest strona do ponownego przeczytania, gdy coś
    cię zaskoczy.

</div>

!!! tip

    Przeczytaj **Pojęcia**, nawet jeśli ci się spieszy. Większość nieporozumień
    wokół tej platformy bierze się z pomylenia jednego z tych pięciu
    rzeczowników z innym — *speca* z *wersją*, *ekspozycji* z *wyzwalaczem*.

!!! tip "Zgubiłeś się w konsoli?"

    [Konsola](../console.md) to mapa każdego obszaru — do czego każdy służy i
    która strona go wyjaśnia.

## Zbuduj agenta { #build-the-agent }

Teraz zrób go dobrym. Każda strona tutaj to jedna rzecz, którą dajesz agentowi, i
są one niezależne — weź te, których twój agent potrzebuje.

<div class="grid cards" markdown>

- :material-compass-outline:{ .lg .middle } **[Wybór modelu](../choosing-models.md)**

    Którego modelu ma używać ten agent — otwarte wagi czy zamknięte, co napędza
    rachunek i jak później zmienić zdanie.

- :material-brain:{ .lg .middle } **[Modele i providerzy](../models.md)**

    27 providerów, profile modeli, fallbacki i ile naprawdę kosztuje token.

- :material-school:{ .lg .middle } **[Skille](../skills.md)**

    Spisane know-how, które agent wczytuje dopiero wtedy, gdy uzna je za istotne.

- :material-text-box-outline:{ .lg .middle } **[Pliki kontekstowe](../context.md)**

    Stała wiedza spisana raz i przypięta do wielu agentów — słownik, przewodnik
    po tonie, macierz eskalacji.

- :material-file-document-multiple:{ .lg .middle } **[Wiedza](../file-processing.md)**

    Wgrywanie, parsowanie, dzielenie na fragmenty, osadzanie. Kolekcje i
    synchronizacja folderu na Drive albo bucketu do jednej z nich.

- :material-connection:{ .lg .middle } **[Połączenia MCP](../mcp.md)**

    Dowolny serwer MCP po URL-u oraz 59 w selektorze z już podpiętym OAuth.

- :material-console:{ .lg .middle } **[Sandbox](../sandbox.md)**

    Pliki i powłoka, izolowane, z określonym czasem życia.

- :material-clock-outline:{ .lg .middle } **[Wyzwalacze](../triggers.md)**

    Run, który dzieje się według harmonogramu albo na zdarzenie, bez niczyjego
    pisania.

</div>

## Udostępnij go ludziom { #put-it-in-front-of-people }

Agent, do którego nikt nie może dotrzeć, jest draftem. Tak wychodzi z konsoli.

<div class="grid cards" markdown>

- :material-source-branch:{ .lg .middle } **[Środowiska](../environments.md)**

    `staging` i `production` jako nazwy przypięte do wersji, dzięki czemu
    publikacja i wydanie to dwie decyzje.

- :material-forum:{ .lg .middle } **[Powierzchnie](../channels.md)**

    Czat webowy, hostowana strona, osadzalny widget, API HTTP, Slack, Telegram i
    Mattermost — za wszystkimi stoi jeden runner.

- :material-server:{ .lg .middle } **[Sam deployment](../deployment.md)**

    Jego tożsamość, jego polityka rejestracji, jego komunikaty. Rzeczy, które
    dotyczą instalacji, a nie agenta.

- :material-cloud-upload:{ .lg .middle } **[Wdrożenie](../deploy.md)**

    Postawienie platformy na hoście.

- :material-account-group:{ .lg .middle } **[Wdrażanie w organizacji](../rollout.md)**

    Kto co robi, realistyczne pierwsze dziewięćdziesiąt dni, ile to kosztuje i
    jakie pytania zada twój przegląd bezpieczeństwa.

</div>

## Zachowaj kontrolę { #keep-it-under-control }

Część, którą większość frameworków agentowych zostawia tobie. Przeczytaj ją,
zanim dasz agentowi narzędzie, które wydaje pieniądze albo gdzieś zapisuje.

<div class="grid cards" markdown>

- :material-account-key:{ .lg .middle } **[Uprawnienia](../permissions.md)**

    Trzy warstwy: co pozwala rola, co poszerza grant, do czego scope pozwala
    sięgnąć narzędziu.

- :material-shield-check:{ .lg .middle } **[Nadzór](../governance.md)**

    Budżety sprawdzane przed żądaniem, zatwierdzenia rozstrzygane raz, alerty i
    ślad audytowy, który zachowuje wartość, a nie wiersz.

- :material-lock:{ .lg .middle } **[Sekrety i vault](../secrets.md)**

    Jeden mechanizm dla każdego poświadczenia w spoczynku i celowo żadnego
    drugiego.

</div>

## Przewodniki - przepisy { #how-to-recipes }

Krótkie odpowiedzi na konkretne pytania, gdy już się orientujesz.

- [Napisz instrukcje agenta](../howto/customize-agent-prompt.md)
- [Skonfiguruj źródła synchronizacji](../howto/configure-sync-sources.md)
- [Korzystaj z ocen wiadomości](../howto/use-ratings.md)

Szukasz, jak *rozszerzyć* platformę w Pythonie — nowa capability, nowy konektor,
nowy endpoint? To jest w
[Zasobach](../resources/index.md#extending-the-platform).

## Dokąd dalej { #where-to-go-next }

Gdy już wiesz, jak platforma się zachowuje, i chcesz wiedzieć dokładnie, co robi
dane ustawienie, komenda albo pole speca, to są
[Referencje](../configuration.md).
