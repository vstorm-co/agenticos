---
source_sha: "2bdccaa6ec15"
---

# Przetłumacz stronę { #translate-a-page }

Ta strona publikuje się po angielsku, polsku, niemiecku i hiszpańsku z jednego
drzewa `docs/`. Angielski jest językiem źródłowym: strona jest najpierw pisana po
angielsku, a pozostałe trzy są jej tłumaczeniami, które mogą zostać w tyle i mają
obowiązek to powiedzieć, kiedy tak się stanie.

## Gdzie mieszka tłumaczenie { #where-a-translation-lives }

Tłumaczenie leży obok strony, którą tłumaczy, z lokalizacją w nazwie pliku.

```text
docs/install.md      the English source
docs/install.pl.md   Polish
docs/install.de.md   German
docs/install.es.md   Spanish
```

[mkdocs-static-i18n](https://github.com/ultrabug/mkdocs-static-i18n) buduje z tego
drzewa jedną stronę na lokalizację. Angielski zachowuje URL-e, które zawsze
publikował — `/install/` to nadal `/install/` — a każde tłumaczenie jest dodawane
obok pod `/pl/install/`, `/de/install/` i `/es/install/`. Przełącznik języka
w nagłówku przenosi między nimi, nie gubiąc miejsca, w którym jest czytelnik.

Nic poza tym się nie zmienia. Nie ma osobnego pliku nawigacji, drugiego
`docs_dir` ani kopii `mkdocs.yml` na lokalizację: nav w `mkdocs.yml` jest
wspólny, a nagłówki jego sekcji są tłumaczone przez tabelę `nav_translations`
pod każdą lokalizacją w tym pliku. Własny tytuł strony w panelu bocznym pochodzi
z pierwszego nagłówka przetłumaczonego pliku, więc przetłumaczenie nagłówka
tłumaczy wpis w nawigacji.

## Każde tłumaczenie zapisuje, z czego powstało { #every-translation-records-what-it-was-made-from }

Pierwszą rzeczą w przetłumaczonym pliku jest jego front matter, a odcisk palca
w nim jest sednem całego tego układu:

```markdown
---
source_sha: "4f2b9c1ad07e"
---

# Instalacja
```

To pierwsze dwanaście znaków szesnastkowych SHA-256 pliku `install.md` w stanie,
w jakim był w chwili tłumaczenia strony, liczone z tekstu ze znormalizowanymi
znakami końca linii, więc checkout na Windowsie odpowiada tak samo jak CI.
`scripts/docs_i18n.py` je wylicza, a dwie rzeczy je odczytują.

`python3 scripts/check_docs_i18n.py` działa w `make lint` i kładzie build na
stronie bez tłumaczenia, na tłumaczeniu, którego odcisk palca nie pasuje już do
angielskiego źródła, i na tłumaczeniu, którego angielska strona została
przemianowana albo usunięta.

Build strony czyta ten sam odcisk palca i umieszcza ostrzegawczą admonicję,
w języku samego czytelnika, na górze każdej strony, która jest nieprzetłumaczona
albo zostaje w tyle. Bez tego lokalizacja wygląda na skończoną, kiedy nią nie
jest: strona, której nikt nie przetłumaczył, i tak odpowiada pod `/de/...`, po
angielsku, wewnątrz niemieckiej nawigacji, i nic nie odróżnia jej od strony,
którą ktoś naprawdę przetłumaczył.

!!! warning "`--update` jest ostatnim krokiem tłumaczenia, a nie sposobem na uciszenie"

    `python3 scripts/check_docs_i18n.py --update docs/install.pl.md` stempluje
    bieżący angielski odcisk palca na tym pliku. **Wymień pliki, które naprawdę
    przetłumaczyłeś na nowo**, a nic poza nimi nie zostanie tknięte —
    ostemplowanie strony, której nikt nie przetłumaczył na nowo, ukrywa
    nieaktualne tłumaczenie zarówno przed bramką, jak i przed czytelnikiem, czyli
    dokładnie tę jedną awarię, której zapobieganiu ten projekt służy.

    Dlatego przyjmuje ścieżki, zamiast aktualizować wszystko, co znajdzie. Zmień
    dwie angielskie strony, przetłumacz jedną na nowo, a hurtowa aktualizacja
    oznaczyłaby obie jako aktualne: nietknięta strona zachowuje swój stary tekst,
    traci swoją notkę i nikt już o niej nie wspomni.

## Każdy nagłówek przypina swoją angielską kotwicę { #every-heading-pins-its-english-anchor }

Przetłumaczony nagłówek niesie kotwicę angielskiej strony jawnie, w formie
`attr_list`:

```markdown
## Berechtigungen { #permissions }
### Wer welche Rolle vergeben darf { #who-may-hand-out-which-role }
```

Bez tego nagłówek przetłumaczony na niemiecki dostaje niemiecką kotwicę, a każdy
link napisany jako `../permissions.md#who-may-hand-out-which-role` ląduje na
górze niemieckiej strony zamiast przy sekcji. Na tej stronie jest ponad sto
linków między stronami i wiele z nich niesie fragment, więc nie jest to przypadek
brzegowy — a `mkdocs build --strict` waliduje ścieżkę linku, ale **nie** jego
fragment, więc nic innego tego nie zauważa.

Przypinanie oznacza też, że jeden link działa we wszystkich czterech językach bez
przepisywania go per lokalizacja, a permalink, który ktoś udostępnił, dalej
działa, kiedy ten ktoś przełączy język.

`scripts/check_docs_i18n.py` porównuje obie listy kotwic w kolejności
dokumentu, więc nagłówek pominięty, dodany, przestawiony albo zostawiony bez
przypięcia kładzie `make lint` i mówi który. Żeby przeczytać tę listę, musisz
przypiąć, zanim zaczniesz:

```bash
python3 scripts/check_docs_i18n.py --anchors docs/permissions.md
```

Nie wyprowadzaj kotwicy na oko. Nagłówek brzmiący
`Layer 1: users.is_app_admin - the deployment superadmin` odpowiada kotwicy
`layer-1-usersis_app_admin-the-deployment-superadmin`: kropka jest wyrzucana,
a nie zamieniana w separator, a podkreślenia przeżywają.

!!! note "Dwóch kotwic nagłówków nie przypinasz ty"

    Powtórzony nagłówek dostaje dopisane `_1` od rozszerzenia `toc` — `screens.md`
    ma dwa zatytułowane "MCP servers", z których drugi odpowiada kotwicy
    `mcp-servers_1`. Przypnij na obu ten sam tekst, a przyrostek zostanie tak samo
    zastosowany do tłumaczenia. Generowane nagłówki symboli na stronach
    `docs/reference/` pochodzą z docstringów i nie mają w Markdownie żadnego
    nagłówka do przypięcia.

## Co tłumaczyć, a czego nie ruszać { #what-to-translate-and-what-to-leave-alone }

Tłumacz prozę, nagłówki, nagłówki tabel i te komórki tabel, które są prozą,
tytuły admonicji, tekst alternatywny obrazków i tekst linków.

Te rzeczy zostaw dokładnie takimi, jakie są po angielsku:

| Nigdy nietłumaczone | Dlaczego |
|---|---|
| Bloki kodu i wszystko w nich | Czytelnik przepisuje je dosłownie |
| Nazwy komend, flagi, zmienne środowiskowe | `make check`, `--strict`, `DATABASE_URL` |
| Ścieżki API, metody HTTP, kody statusu | `POST /api/v1/agents` |
| Klucze pól i konfiguracji | `spec_version`, `budget.monthly_cap` |
| Nazwy uprawnień | `agents:edit` to łańcuch znaków, który produkt porównuje |
| Ścieżki plików i katalogów | `backend/app/core/vault.py` |
| Nazwy klas błędów i wyjątków | `AuthorizationError` |
| Nazwy produktów | Docker Compose, PostgreSQL, Slack, Prefect |
| Bloki mermaid | Etykieta z nawiasem albo cudzysłowem rozwala graf, a build nie może ci tego powiedzieć — Mermaid renderuje się w przeglądarce |
| Etykieta z konsoli, którą czytelnik ma znaleźć na ekranie | UI jest po angielsku, więc `Admin → Response Ratings` jest punktem orientacyjnym, a nie frazą |
| Ścieżki obrazków | Jeden zrzut ekranu obsługuje wszystkie cztery lokalizacje |

Komentarz wewnątrz bloku kodu jest prozą, którą czytelnik czyta, a nie
przepisuje, więc może zostać przetłumaczony — ale tylko tam, gdzie blok jest
ilustracją. Nigdy nie tłumacz komentarza w bloku, który ktoś ma wkleić, bo
wklejenie obejmie także ten komentarz.

## Własne rzeczowniki produktu zostają angielskie { #the-products-own-nouns-stay-english }

Konsola już tak robi i z tego samego powodu: te słowa nazywają rzeczy, które
czytelnik spotyka też w API, w YAML-u, który spec eksportuje do jego własnego
repozytorium, i na każdej angielskiej stronie tego serwisu. Tłumaczenie ich tutaj
i nigdzie indziej daje jednemu produktowi dwa słowniki, a polski czytelnik, który
wyszuka przetłumaczone słowo, nie znajdzie nic.

**agent · spec · capability · skill · embed · budget · run · prompt · provider ·
token · vault · workspace · sandbox · MCP**

Odmieniaj je, zamiast je zastępować, i tłumacz wszystko dookoła nich.

| Angielski | Polski | Niemiecki | Hiszpański |
|---|---|---|---|
| the agent's spec | spec agenta | der Spec des Agents | el spec del agent |
| publish a version | opublikuj wersję | eine Version veröffentlichen | publica una versión |
| grant a capability | przyznaj capability | eine Capability gewähren | concede una capability |
| the run failed | run zakończył się błędem | der Run ist fehlgeschlagen | el run ha fallado |
| a vault secret | sekret w vault | ein Secret im Vault | un secreto del vault |

Wszystko inne jest zwykłym słownictwem i powinno brzmieć naturalnie: baza wiedzy,
organizacja, członek, rola, uprawnienie, zatwierdzenie, cap budżetu,
powiadomienie, kanał, wdrożenie.

### Zachowany rzeczownik potrzebuje rodzaju i tutaj go dostaje { #a-kept-noun-needs-a-gender-and-it-gets-one-here }

Angielski rzeczownik wrzucony do niemieckiego, polskiego albo hiszpańskiego
zdania musi przyjąć rodzajnik i końcówkę, a zostawiony każdej stronie z osobna
przyjmuje za każdym razem inne. Pierwsze niemieckie podejście wyprodukowało „der
Sandbox" na jednej stronie i „ein Sandbox" na drugiej; czytelnik spotyka oba.
Dlatego wybór jest podejmowany raz, tutaj:

| Rzeczownik | Niemiecki | Polski | Hiszpański |
|---|---|---|---|
| agent | der Agent | ten agent, agenta | el agent |
| spec | der Spec | ten spec, speca | el spec |
| capability | die Capability | ta capability (nieodmienne) | la capability |
| skill | der Skill | ten skill, skilla | el skill |
| embed | das Embed | ten embed, embeda | el embed |
| budget | das Budget | ten budżet | el budget |
| run | der Run | ten run, runa | el run |
| prompt | der Prompt | ten prompt, promptu | el prompt |
| provider | der Provider | ten provider, providera | el provider |
| token | das Token | ten token, tokena | el token |
| vault | der Vault | ten vault, vaulcie | el vault |
| workspace | der Workspace | ten workspace, workspace'u | el workspace |
| sandbox | die Sandbox | ten sandbox, sandboksie | la sandbox |
| MCP server | der MCP-Server | ten serwer MCP | el servidor MCP |

Niemiecki składa je z łącznikiem, kiedy druga połowa jest niemiecka —
Run-Kosten, Vault-Eintrag, Sandbox-Session — i zachowuje wielką literę
angielskiego słowa.

### Osoba bez imienia jest rodzaju męskiego, we wszystkich trzech językach { #a-generic-person-is-masculine-in-all-three-languages }

Angielski mówi "the reader", "an operator", "whoever wrote the agent", nie
wybierając rodzaju, a każdy z tutejszych języków wybrać go musi. Zostawione
każdej stronie z osobna, wychodzi za każdym razem inaczej: pierwsze przejście
niemieckie dało "der Betreiber" na jednej stronie i "die Betreiberin" na
następnej, o tej samej osobie, a czytelnik spotyka oba.

Ogólna forma roli jest więc męska — der Leser, der Betreiber, der Autor, der
Entwickler, der Administrator, der Besitzer, der Kunde; czytelnik, operator,
autor; el lector, el operador, el autor. Dotyczy to osoby, której nikt nie
nazwał. Nazwany przykład zachowuje rodzaj, który ten przykład mu nadaje, i tak
samo zdanie o jednej konkretnej osobie.

## Terminologia, która musi być dokładna { #terminology-that-has-to-be-exact }

Strony o uprawnieniach, governance i bezpieczeństwie opisują odmowy, a odmowa
opisana niedbale jest gorsza niż nieopisana wcale. Zachowaj te rozróżnienia
w każdym języku:

| Angielski | Rozróżnienie, które trzeba zachować |
|---|---|
| permission / grant | Uprawnienie pochodzi z roli; grant jest przypięty do jednego zasobu i je poszerza |
| role / membership | Władza mieszka w wierszu członkostwa, a nie na użytkowniku |
| owner / admin / editor / viewer | Nazwy ról, dopasowywane do katalogu — przy pierwszym użyciu zostaw angielską nazwę w nawiasie |
| budget cap / spend | Limit i to, co zostało na jego poczet wydane |
| approval / refusal | Decyzja, która czeka, i taka, która jest ostateczna |
| organization / deployment | Jeden tenant i cała zainstalowana instancja |
| published / draft | Wersja speca, którą agenci uruchamiają, i taka, której nie uruchamia jeszcze nic |

Kiedy zdanie mówi, co platforma odrzuca, tłumacz tę odmowę dosłownie. Nie
zmiękczaj „zostaje odrzucone" do „może nie zadziałać" i nie zamieniaj
stwierdzenia o tym, co nie może się zdarzyć, w poradę o tym, czego nie powinieneś
robić.

## Cztery pliki, które renderuje GitHub, a nie ten serwis { #the-four-files-github-renders-not-this-site }

`README.md`, `CONTRIBUTING.md`, `SECURITY.md` i `CODE_OF_CONDUCT.md` są tłumaczone
tak samo i zapisywane tak samo, a `scripts/check_docs_i18n.py` pyta też o nie.
Trzy rzeczy się różnią, a wszystkie dlatego, że te pliki renderuje GitHub, a nie
MkDocs.

**Odcisk palca idzie do komentarza, a nie do front mattera.** GitHub renderuje
blok `---` jako tabelę, więc czytelnik spotkałby `source_sha` przed nazwą
projektu. `--update` wpisuje zamiast tego `<!-- source_sha: 4f2b9c1ad07e -->`
w pierwszej linii i stamtąd go odczytuje. Na stronie serwisu wartość jest
w cudzysłowie, bo mniej więcej jeden odcisk palca na 281 składa się z samych
cyfr dziesiętnych, a YAML odczytałby to jako liczbę.

**Nagłówki nie mogą przypiąć kotwicy.** `{ #permissions }` to `attr_list`, czyli
rozszerzenie Python-Markdown; GitHub nie ma odpowiednika i drukuje klamry.
Przetłumaczony nagłówek odpowiada więc własnej kotwicy, wyprowadzonej regułą
GitHuba, a nie rozszerzenia `toc` — blisko, ale nie tej samej, bo GitHub
zachowuje literę, którą serwis składa do ASCII, i zamienia każdą spację
w osobny łącznik. Dlatego **przepisz każdy link, który plik kieruje do samego
siebie**, i sprawdź wynik:

```bash
python3 scripts/check_docs_i18n.py --anchors README.pl.md
```

Bramka porównuje zamiast kotwic kształt sekcji — tyle samo nagłówków,
zagnieżdżonych tak samo — i kładzie się na każdym linku w obrębie strony,
któremu nie odpowiada żaden nagłówek. To ta druga połowa wyłapuje plik
zostawiony w połowie przetłumaczony: nieprzetłumaczone nagłówki zachowują
kształt tych, z których zostały skopiowane, więc sam kształt tego nie widzi, ale
linki nad nimi dalej wskazują nagłówki, które się przesunęły. Nic innego by tego
nie zauważyło, bo GitHub po cichu serwuje martwy fragment jako górę strony.

**Każdy pozostały link wskazuje własny język czytelnika.** Hiszpański README
linkuje do `docs/install.es.md`, a nie do `docs/install.md` — inaczej wybór
języka starcza dokładnie na jedno kliknięcie. Bramka sprawdza każdy z nich
względem linku angielskiej strony na tej samej pozycji, więc link pominięty,
przestawiony albo niezlokalizowany kładzie bramkę. Strona, która nie ma
tłumaczenia, jak `docs/ROADMAP.md`, zostaje angielska, a paska języków się nie
rusza: wskazywanie innych języków jest właśnie tym, do czego służy.

**Każdy plik niesie pasek języków** do swoich trzech tłumaczeń, a tłumaczenia
linkują z powrotem. Przy dodaniu języka zaktualizuj wszystkie cztery.

`CHANGELOG.md` nie jest tłumaczony, z tego samego powodu, z którego nie jest
`release-notes.md`: to historia commitów.

## Dwie rzeczy, których lokalizacja nie dostaje { #two-things-a-locale-does-not-get }

Strony referencyjne pod `docs/reference/` są generowane z pythonowych docstringów
przez mkdocstrings. Przetłumaczenie jednego z tych plików tłumaczy jego prozę
i nagłówki; generowana dokumentacja symboli zostaje angielska, bo jest
odczytywana ze źródeł w czasie budowania. Tak ma być — powiedz to na stronie,
zamiast parafrazować docstringi w drugą kopię, która się rozjedzie.

`release-notes.md` pokazuje `CHANGELOG.md`, podstawiany w czasie budowania.
Przetłumaczona strona release notes tłumaczy własną ramę strony wokół znacznika;
same wpisy changeloga zostają angielskie, bo są historią commitów.

## Wyszukiwanie po polsku { #searching-in-polish }

lunr.js, który napędza wyszukiwarkę serwisu, nie ma polskiego stemmera, więc
wyszukiwanie w `/pl/` dopasowuje całe słowa, a nie ich rdzenie. Niemiecki
i hiszpański stemują normalnie. Nie ma tu nic do skonfigurowania — build mówi to
w swoim logu — ale warto o tym wiedzieć, zanim ktoś zgłosi to jako błąd.

## Przepływ pracy { #the-workflow }

1. Skopiuj angielską stronę do `<page>.<locale>.md`.
2. Przetłumacz ją, zachowując identyczną strukturę nagłówków i przypinając
   angielską kotwicę każdego nagłówka.
3. Sprawdź, czy każdy względny link nadal się rozwiązuje. Link do `../mcp.md`
   z przetłumaczonej strony rozwiązuje się automatycznie do przetłumaczonego
   `mcp.md`; link napisany jako `../mcp.pl.md` jest błędny i kładzie build.
4. `python3 scripts/check_docs_i18n.py --update <page>.<locale>.md` — plik, który
   właśnie przetłumaczyłeś, i żaden inny.
5. `make docs-build` — uruchamia `--strict`, więc martwy link go kładzie.
6. `python3 scripts/check_docs_paragraphs.py` — limit 115 słów na akapit
   obowiązuje w każdym języku, a tłumaczenie, które zlepia dwa angielskie akapity
   w jeden, zwykle się o niego potyka.

Zmiana angielskiej strony to ta sama pętla od drugiej strony: zmień ją, a potem
albo przetłumacz trzy tłumaczenia na nowo w tej samej zmianie, albo zostaw je
i pozwól bramce je zgłosić — czego nie wolno, to ostemplować je przez `--update`.

## Podsumowanie { #recap }

- Tłumaczenie to `<page>.<locale>.md` obok angielskiej strony; angielskie URL-e
  nie ruszają się z miejsca.
- Jego front matter zapisuje odcisk palca angielskiego tekstu, z którego
  powstało, a każdy nagłówek przypina swoją angielską kotwicę.
- `scripts/check_docs_i18n.py` kładzie `make lint` na brakującym, nieaktualnym
  albo osieroconym tłumaczeniu oraz na nagłówkach, które się nie zgadzają,
  a serwis oznacza czytelnikowi stronę nieprzetłumaczoną lub nieaktualną.
- Kod, komendy, klucze, ścieżki i własne rzeczowniki produktu zostają angielskie;
  wszystko dookoła nich jest tłumaczone.
- Sformułowania dotyczące uprawnień i governance są dokładne, a nie przybliżone.
