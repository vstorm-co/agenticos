---
source_sha: "f3a9cc7f1767"
---

# Artefakty { #artifacts }

**Artefakt** to strona opublikowana przez agenta: raport, mały dashboard,
jednostronicowe podsumowanie, które ktoś otwiera w przeglądarce. Ma link, który
się nie zmienia, gdy agent publikuje ją ponownie, więc „w każdy poniedziałek
opublikuj liczby z tygodnia na tej stronie” to jeden link, który ludzie dodają do
zakładek, a nie nowy co tydzień.

Artefakt nie jest plikiem. Wykres, wygenerowany PDF i plik w workspace'ie mają już
swoje miejsce w czacie i w [workspace'ie](sandbox.md). Artefakt to rzecz, która
jest *serwowana*: ma właściciela, widoczność i granty, tak jak agent czy skill, i
można mu nadać publiczny link dla kogoś bez konta.

## Publikowanie artefaktu { #publishing-one }

Włącz agentowi capability **Artifacts**. Dodaje ona dwa narzędzia:
`publish_artifact`, które model wywołuje, gdy wynik jest czymś, co człowiek
powinien otworzyć, a nie przeczytać raz w czacie, oraz `read_artifact`, które
odczytuje opublikowaną stronę z powrotem.

Strona pochodzi z jednego z trzech miejsc:

- **Z pliku w workspace'ie agenta**, zakończonego na `.html` albo `.md`. To
  zwykły przypadek dla agenta z capability [Sandbox](reference/capabilities.md#files-shell):
  zapisuje `report.html`, uruchamia to, co go buduje, a potem publikuje plik.
  Bajty są czytane przez własny backend workspace'u runa, więc działa to na
  każdym backendzie sandboksa.
- **Ze strony przekazanej inline** — dla agenta bez workspace'u albo dla krótkiej
  strony.
- **Z edycji strony opublikowanej już** pod tą nazwą — zobacz niżej.

Czat pokazuje kartę opublikowanej strony. Karta prowadzi do wersji, którą
opublikował *ten* run, więc późniejsze czytanie rozmowy nadal pokazuje to, co w
niej opublikowano, a nie to, co strona pokazuje dziś.

### Zmiana części strony { #changing-part-of-a-page }

Zmiana jednego słowa nie powinna kosztować całej strony od nowa. Agent wywołuje
`read_artifact` z nazwą strony, co zwraca bieżącą wersję taką, jaką ją napisano,
a potem `publish_artifact` z tą samą nazwą i `edits`: dokładnymi zamianami,
nakładanymi po kolei. Każda musi pasować dokładnie do jednego miejsca na stronie;
brak dopasowania albo dopasowanie niejednoznaczne wraca do modelu do poprawienia.
Wynikiem jest nowa wersja, jak każda inna.

Edycje niosą wersję, na której je zrobiono. Jeśli w międzyczasie opublikował inny
run, nic nie jest zapisywane, a model dostaje polecenie, żeby przeczytał stronę
jeszcze raz — edytowana kopia starszej strony nigdy nie zastępuje nowszej. Odczyt
podlega tej samej zasadzie co otwarcie strony w konsoli: osoba, w imieniu której
działa run, musi mieć prawo ją otworzyć. Strona dłuższa niż 100 000 znaków wraca
ucięta i to mówi; edycja nadal może wskazać tekst za cięciem.

## Jedna nazwa, jeden link { #one-name-one-link }

Tożsamością artefaktu jest jego **nazwa w obrębie agenta** — `weekly-report`,
`churn-dashboard`. Publikacja pod tą samą nazwą aktualizuje ten sam artefakt, z
dowolnej powierzchni: z czatu, z API, z [triggera](triggers.md) albo z workflow.
Nowa nazwa tworzy nową stronę. Nazwa składa się z małych liter, cyfr i łączników,
maksymalnie 64 znaki.

Nazwa obowiązuje też **w obrębie środowiska**, z którego odpowiedział run. Run w
nazwanym [środowisku](environments.md) — `staging`, `dev` — publikuje własną
stronę obok strony środowiska domyślnego, więc próba nowej wersji agenta nie może
ponownie opublikować strony, którą czytelnicy produkcji mają w zakładkach.
Środowisko jest odczytywane z samego runa, nigdy od modelu, a lista i strona je
pokazują.

Nazwę dzielą wszyscy, którzy uruchamiają agenta, ale stronę już nie. Run
publikuje ponownie istniejący artefakt tylko wtedy, gdy osoba, w której imieniu
działa, jest jego właścicielem albo ma na nim `artifacts:edit` — z roli albo z
grantu `edit`, ta sama zasada co przy zarządzaniu nim w konsoli. Run każdego
innego dostaje informację, że nazwa jest zajęta, i publikuje pod inną, więc
kolega, który poprosi tego samego współdzielonego agenta o `weekly-report`, nie
podmieni strony za Twoim linkiem.

Każda publikacja to nowa **wersja**. Nic nie jest nadpisywane, więc lista wersji
na stronie artefaktu jest historią strony. Dwie rzeczy utrzymują tę historię w
granicach:

- Publikacja dokładnie tych bajtów, które trzyma bieżąca wersja, nie dodaje
  wersji. Wynik mówi `unchanged`, a harmonogram, który nie znalazł nic nowego,
  zostawia historię w spokoju. To nadal liczy się jako publikacja, więc zegar
  retencji startuje od nowa.
- Zachowywane są tylko najnowsze wersje, `ARTIFACT_MAX_VERSIONS` z nich
  (domyślnie 20). Starsza wersja jest usuwana, gdy pojawia się nowa — poza tą, do
  której przypięty jest publiczny link. Rozmowa, która linkuje do usuniętej
  wersji, mówi, że wersja nie jest już przechowywana, i proponuje najnowszą.

**Restore this version** przywraca zachowaną wersję. Członek, który może edytować
stronę, otwiera wersję i ją przywraca; dodaje to nową wersję z bajtami starej,
więc historia zachowuje to, co się stało, a przywrócenie można cofnąć tak samo.
Nic nowego nie jest zapisywane w magazynie. Trafia to do dziennika audytu.

## Obsługiwane formaty { #supported-formats }

| Format | Co jest przechowywane | Co jest serwowane |
|---|---|---|
| HTML (`.html`, `.htm` albo `format: html`) | Dokument tak, jak agent go napisał | Ten sam dokument, poprzedzony krótkim skryptem platformy (zobacz [Jak strona jest izolowana](#how-the-page-is-isolated)) |
| Markdown (`.md`, `.markdown` albo `format: markdown`) | Źródło w Markdownie | Źródło wyrenderowane do prostej strony, razem z tabelami. Surowy HTML w nim jest escapowany |

Jedna wersja to jeden samodzielny dokument o rozmiarze najwyżej
`ARTIFACT_MAX_BYTES` (domyślnie 5 MiB). Nie ma paczek wieloplikowych: wstaw własny
skrypt, style i obrazy (jako URI `data:`) do tego jednego pliku.

!!! warning "Strona nie ma sieci"

    Skrypty działają, więc wykres rysowany przez bibliotekę zadziała. Ale strona
    nie może niczego skądkolwiek załadować ani niczego nigdzie wysłać — skrypt z
    CDN, font z adresu URL i wywołanie API kończą się błędem. Jedynym wyjątkiem
    jest zestaw bibliotek poniżej, który wdrożenie serwuje samo. Narzędzie mówi to
    modelowi. To celowe, a [Jak strona jest izolowana](#how-the-page-is-isolated)
    wyjaśnia dlaczego.

### Zestaw bibliotek { #the-library-set }

Wdrożenie serwuje kilka plików obok każdej strony, żeby model przestał wklejać do
każdej całą bibliotekę wykresów. Strona ładuje je adresem względnym i działa dalej,
jeśli wdrożenie przeniesie później treść do innego originu:

| Adres na stronie | Co to jest |
|---|---|
| `lib/chart-4.5.1.umd.min.js` | Chart.js 4.5.1, jako `window.Chart` |
| `lib/d3-7.9.0.min.js` | d3 7.9.0, jako `window.d3` |
| `lib/lucide-1.46.0.min.js` | Ikony Lucide 1.46.0, jako `window.lucide` - ten sam zestaw, którego używa konsola |
| `lib/agenticos-2.css` | Wygląd konsoli dla stron, jasny i ciemny, oraz komponenty `ao-`, z których buduje się stronę |
| `lib/agenticos-2.js` | `window.AO`: Chart.js w stylu konsoli, formatowanie liczb w języku strony, ikony, zakładki |
| `lib/agenticos-1.css` | Pierwsza wersja wyglądu, zostawiona dla stron opublikowanych z nią |

Każda nazwa niesie swoją wersję i jest cache'owana przez rok. Aktualizacja dodaje
nowy plik obok starego, więc strona opublikowana z jedną wersją dalej ją dostaje.
Nic nie jest pobierane spoza wdrożenia, więc wdrożenie bez dostępu do internetu
działa tak samo. Pliki są wymienione w `backend/app/core/catalog/artifact_lib/`.

Dołączony [skill](skills.md) **`artifact-pages`** uczy agenta z nich korzystać: dwa
szablony (dashboard i raport), styl domu z jego komponentami, ikony zamiast
emoji i sposób zmiany strony przez
`read_artifact`. Nowa organizacja dostaje go razem z innymi dołączonymi skillami,
istniejąca przez `seed-skills`, a zakładka **Page style** capability Artifacts w
Builderze go proponuje. Edytuj skill, żeby opisać własny branding, a agent będzie
się go trzymał.

## Kto może go otworzyć { #who-can-open-it }

Nowy artefakt jest **prywatny** dla osoby, w imieniu której działał publikujący
run: dla osoby na czacie albo dla twórcy triggera.

Jego link - ten, na który wskazują karta w czacie i odpowiedź agenta - otwiera
samą stronę, na całe okno, pod jednym paskiem z tytułem, wersją i przyciskiem
**Share**. Sam link nikogo nie wpuszcza: otwiera się tylko zalogowanemu
członkowi, którego wpuszczają już poniższe zasady. Link wskazuje organizację, w
której jest artefakt (`?org=`), więc członek kilku organizacji trafia do
właściwej.

Pod **Share** każdy, kto może nim zarządzać, może go udostępnić
na trzy sposoby:

| Zasięg | Jak | Kto |
|---|---|---|
| Konkretne osoby | Grant, na poziomie `read` albo `edit` | Ci członkowie, w tej organizacji |
| Organizacja | Widoczność ustawiona na całą organizację | Każdy członek, którego rola sięga do udostępnionych artefaktów |
| Każdy, kto ma link | **Create a public link** | Każdy, kto zna adres, bez konta |

Udostępnianie i widoczność korzystają z tego samego panelu i tych samych reguł co
agenci i skille; zobacz [Uprawnienia](permissions.md). Zarządzanie artefaktem —
udostępnianie go, jego publiczny link i jego ustawienia, przywracanie wersji,
usuwanie — wymaga `artifacts:edit` na tym artefakcie, z roli albo z grantu `edit`.
Otwarcie go wymaga `artifacts:view`.

Agent nie może poszerzyć grona czytelników strony. Agent publikuje; o tym, kto ją
widzi, decyduje człowiek. Dlatego capability domyślnie nie prosi o zatwierdzenie:
pierwsza publikacja jest prywatna. Autor, który chce, żeby człowiek zatwierdzał
każdą ponowną publikację już udostępnionej strony, ustawia `tool_approval` na
`publish_artifact` w specu.

### Publiczny link { #the-public-link }

Publiczny link to `/a/<key>` pod własnym adresem konsoli, z losowym kluczem o
długości 192 bitów — według tej samej reguły co klucz hostowanej strony czatu. Nie
mówi nic o tym, kto ją opublikował ani do której organizacji należy.

**Replace the link** wydaje nowy klucz, a stary od razu przestaje cokolwiek
otwierać. **Turn off** usuwa link. Oba działania trafiają do dziennika audytu.
Strona, którą ktoś ma już otwartą, wyświetla się dalej, dopóki nie wygaśnie jej
podpisany adres treści — najwyżej `ARTIFACT_VIEW_TTL_SECONDS` (domyślnie pięć
minut).

Odwołany członek jest w tej samej sytuacji: traci artefakt przy następnym
żądaniu, a strona, którą miał już otwartą, zostaje najwyżej przez to samo okno.

Pod linkiem **Share** trzyma jego ustawienia. Zostają, gdy link jest wymieniany, a
link wyłączony i włączony ponownie je zachowuje:

| Ustawienie | Co robi |
|---|---|
| **Stops opening after** | Data, po której link niczego nie otwiera, jakby był wyłączony |
| **Shows** | Najnowszą wersję albo jedną zachowaną wersję przypiętą tak, żeby nowa publikacja nie zmieniła tego, co osoby z linkiem już widziały. Przypięta wersja nigdy nie jest usuwana |
| **Password** | Pytanie przed otwarciem strony. Link nie mówi nic — ani tytułu, ani kiedy ją opublikowano — dopóki hasło nie jest poprawne. Przechowywane jako hash, nigdy nie pokazywane ponownie; każda próba liczy się do limitu żądań linku |
| **Sites that may embed it** | Zobacz niżej |

Karta mówi też, ile razy link otwarto i kiedy ostatnio. Liczy otwarcia, nie
osoby: nic o odwiedzającym nie jest zapisywane. Każda zmiana ustawień trafia do
audytu, z nazwami zmienionych ustawień i nigdy z hasłem.

### Osadzanie na innej witrynie { #embedding-it-on-another-site }

Publiczną stronę można umieścić na stronie intranetu, w wiki albo na witrynie
klienta za pomocą `<iframe>`. Wymień witryny w **Sites that may embed it** — tylko
schemat i host, `https://intranet.example.com`, albo `https://*.example.com` dla
subdomen witryny — i skopiuj **Embed code**, który wtedy pokazuje Share.

Kod osadza `/api/v1/artifact-embed/<key>` z originu treści: mały dokument samego
wdrożenia, który z kolei osadza stronę w tym samym sandboksie co wszędzie indziej.
Jego polityka pozwala osadzić go tylko wymienionym witrynom, a polityka samej
strony pozwala osadzić stronę tylko temu dokumentowi i konsoli. Bez żadnej
wymienionej witryny nie może nikt. Strony za hasłem nie da się osadzić — osadzenie
mówi wtedy, żeby otworzyć ją na jej własnej stronie — i nikt nie loguje się w
ramce na cudzej witrynie.

## Jak strona jest izolowana { #how-the-page-is-isolated }

Artefakt to HTML ze skryptem w środku, napisany przez model, który mógł przeczytać
coś wrogiego. Jest serwowany tak, żeby nic, co robi, nie mogło dosięgnąć konsoli
ani osoby, która go ogląda:

- Bajty pochodzą z osobnej trasy, `/api/v1/artifact-content/<token>`, która nie
  czyta żadnego ciasteczka ani sesji. Token jest podpisany, wskazuje jedną wersję
  i wygasa po kilku minutach. Jest wydawany dopiero wtedy, gdy grant albo
  publiczny link dopuściły wywołującego.
- Każda odpowiedź z treścią niesie `Content-Security-Policy: sandbox
  allow-scripts allow-modals`, bez `allow-same-origin`. Strona działa w
  nieprzezroczystym originie (opaque origin), więc nie może czytać ciasteczek,
  pamięci ani strony konsoli, a żądanie, które wyśle, nie niesie niczego od
  oglądającego. To obowiązuje nawet wtedy, gdy ktoś otworzy adres treści
  bezpośrednio.
- Ta sama polityka ustawia `default-src 'none'` i `connect-src 'none'`. Jedynym
  zdalnym źródłem, jakie wymienia, jest własna ścieżka zestawu bibliotek w
  originie treści, dla skryptów, stylów i fontów. `frame-ancestors` wymienia tylko
  konsolę — a dla strony z publicznym linkiem i witrynami do osadzania także
  dokument osadzenia i te witryny. Ramka w konsoli niesie tę samą listę `sandbox`
  jako drugi zamek.
- Nie ma `allow-popups`. `connect-src` nie obejmuje nawigacji, więc link
  otwierający nowe okno byłby sposobem na wysłanie tego, co strona pokazuje, pod
  adres wybrany przez stronę. Zamiast tego każda serwowana strona dostaje najpierw
  krótki skrypt platformy: kliknięcie linku do innej witryny staje się
  wiadomością do rodzica ramki. Konsola i strona publiczna pokazują pełny adres i
  otwierają go w nowej karcie tylko wtedy, gdy człowiek się zgodzi; dokument
  osadzenia robi to samo w pasku pod stroną. Strona mogłaby wysłać tę wiadomość
  sama, więc jest ona prośbą, a nigdy zgodą — to człowiek czytający adres stoi
  między stroną po prompt injection a adresem, pod który wysłałaby swoje liczby.
- Jeden podpisany adres ładuje swoją stronę najwyżej kilka razy na minutę, licząc
  per adres, zanim cokolwiek zostanie odczytane. Konsola i strona publiczna
  wydają świeży adres za każdym razem, gdy rysują ramkę, a wydanie go przez
  publiczny link samo jest ograniczone per link.

Lista **Artifacts** rysuje na każdej karcie bieżącą stronę jako żywą miniaturę,
przez ten sam rodzaj ramki, ze skryptem i niczym więcej: bez okien dialogowych,
bez popupów, bez formularzy. Ze skryptem, żeby dashboard, którego wykresy rysuje
biblioteka, nie był pustym płótnem na karcie. Miniatura jest bezczynna — bez
zdarzeń wskaźnika, poza kolejnością tabulacji, ukryta przed technologiami
asystującymi — i istnieje tylko wtedy, gdy jej karta jest blisko widoku, więc
długa lista uruchamia tych kilka, które czytelnik widzi, i zatrzymuje stronę,
która zjechała z ekranu.

Ponadto wdrożenie może serwować treść z **osobnej domeny rejestrowalnej**,
ustawiając `ARTIFACT_ORIGIN` — na przykład
`https://agenticos-content.example.net`, skierowaną do tego samego API. Strona
jest wtedy w zupełnie innej witrynie. Nieprzezroczysty origin już ją izoluje, więc
to jest utwardzenie, o które może poprosić przegląd bezpieczeństwa, a nie wymóg.
Ustaw zmienną dla backendu i dla frontendu, który dodaje ten origin do swojego
`frame-src`. Zobacz [Konfiguracja](configuration.md#published-artifacts).

## Obserwowanie strony { #following-a-page }

**Obserwuj** na pasku strony umieszcza powiadomienie w Twojej skrzynce za każdym
razem, gdy strona dostaje nową wersję - agent opublikował ją ponownie z inną
treścią albo ktoś przywrócił starszą wersję. Ponowna publikacja, która niczego
nie zmienia, nikogo nie powiadamia, więc harmonogram, który nie znalazł nic
nowego, pozostaje cichy. Osoba, której run albo przywrócenie utworzyło wersję,
nie dostaje powiadomienia o własnej zmianie.

Obserwowanie nie daje dostępu. Obserwować stronę może każdy, kto może ją
otworzyć, a obserwujący, który straci dostęp, przestaje dostawać powiadomienia
bez rezygnowania z obserwowania. Skrzynka sprawdza dostęp ponownie przy
odczycie, więc powiadomienie o stronie, której nie możesz już otworzyć, znika
razem z tym dostępem. Powiadomienie może też przyjść mailem; każdy kanał
wyłączysz w **Ustawienia → Powiadomienia → Artefakt zaktualizowany**.

## Retencja i usuwanie { #retention-and-deletion }

Artefakty są osobną [klasą retencji](governance.md#the-classes), liczoną od
**ostatniej publikacji** — raport publikowany ponownie co tydzień żyje, niezależnie
od tego, jak stara jest jego pierwsza wersja. Jak każda klasa, trzyma artefakty
bezterminowo, dopóki organizacja albo wdrożenie nie ustawi okresu.

Usunięcie artefaktu — ręcznie albo przez retencję — usuwa każdą wersję, jej
przechowywane bajty, jego granty i jego publiczny link. Usunięcie agenta nie
usuwa jego artefaktów: pozostają czytelne i po prostu nie mają wydawcy. Usunięcie
nazwanego środowiska robi to samo ze stronami z niego opublikowanymi, więc nigdy
nie trafiają na stronę środowiska domyślnego o tej samej nazwie. Usunięcie
organizacji je usuwa. Artefakty usuniętej osoby zostają i tracą właściciela, tak
jak jej agenci i skille.

Bajty leżą w [magazynie plików](configuration.md#uploaded-files-at-rest)
wdrożenia, pod `artifacts/<organization>/<artifact>/`.

## Ograniczenia { #limitations }

- **Jeden samodzielny dokument na wersję.** Bez paczek i bez sieci z wnętrza
  strony poza serwowanym zestawem bibliotek.
- **Bez danych na żywo.** Dashboard pokazuje dane, z którymi został opublikowany.
  Odświeża się, gdy agent opublikuje go ponownie — zwykle robi to harmonogram.
- **Nic na stronie nie działa.** Formularz albo przycisk nie mają dokąd wysłać
  tego, co zbiorą.
- **Otwarta strona przeżywa odwołanie o jeden czas życia podpisanego adresu**,
  domyślnie pięć minut.
- **Link wewnątrz strony najpierw pyta.** Otwiera się w nowej karcie, gdy
  człowiek się zgodzi; sama strona nie może otworzyć okna ani nawigować konsolą.
- **Osadzenie wymaga publicznego linku i braku hasła.** Członkowie nie mogą
  zalogować się w ramce na cudzej witrynie.
- **Usunięte wersje przepadają.** Rozmowa, która linkuje do wersji starszej niż
  przechowywane okno, może zaproponować tylko najnowszą.

## Podsumowanie { #recap }

- Jedna capability, dwa narzędzia: `publish_artifact`, z pliku w workspace'ie,
  inline albo jako edycje, oraz `read_artifact` do odczytania strony z powrotem.
- Agent, środowisko i nazwa to tożsamość; ponowna publikacja zachowuje link i
  dodaje wersję, a każdą zachowaną wersję można przywrócić.
- Domyślnie prywatny; udostępniany grantami, organizacji albo publicznym linkiem —
  przez człowieka. Publiczny link może wygasnąć, przypiąć wersję, pytać o hasło i
  być osadzony na wymienionych witrynach.
- Serwowany z trasy bez ciasteczek, w nieprzezroczystym originie bez sieci poza
  własnym zestawem bibliotek wdrożenia, z linkami, które pytają przed otwarciem, i
  opcjonalnie z własnej domeny.
- Osobna klasa retencji, liczona od ostatniej publikacji.
