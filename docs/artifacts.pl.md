---
source_sha: "abc239ffbca4"
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

Włącz agentowi capability **Artifacts**. Dodaje ona jedno narzędzie,
`publish_artifact`, a model wywołuje je, gdy wynik jest czymś, co człowiek
powinien otworzyć, a nie przeczytać raz w czacie.

Strona pochodzi z jednego z dwóch miejsc:

- **Z pliku w workspace'ie agenta**, zakończonego na `.html` albo `.md`. To
  zwykły przypadek dla agenta z capability [Files & shell](reference/capabilities.md#files-shell):
  zapisuje `report.html`, uruchamia to, co go buduje, a potem publikuje plik.
  Bajty są czytane przez własny backend workspace'u runa, więc działa to na
  każdym backendzie sandboksa.
- **Ze strony przekazanej inline** — dla agenta bez workspace'u albo dla krótkiej
  strony.

Czat pokazuje kartę opublikowanej strony. Karta prowadzi do wersji, którą
opublikował *ten* run, więc późniejsze czytanie rozmowy nadal pokazuje to, co w
niej opublikowano, a nie to, co strona pokazuje dziś.

## Jedna nazwa, jeden link { #one-name-one-link }

Tożsamością artefaktu jest jego **nazwa w obrębie agenta** — `weekly-report`,
`churn-dashboard`. Publikacja pod tą samą nazwą aktualizuje ten sam artefakt, z
dowolnej powierzchni: z czatu, z API, z [triggera](triggers.md) albo z workflow.
Nowa nazwa tworzy nową stronę. Nazwa składa się z małych liter, cyfr i łączników,
maksymalnie 64 znaki.

Każda publikacja to nowa **wersja**. Nic nie jest nadpisywane, więc lista wersji
na stronie artefaktu jest historią strony. Dwie rzeczy utrzymują tę historię w
granicach:

- Publikacja dokładnie tych bajtów, które trzyma bieżąca wersja, nie dodaje
  wersji. Wynik mówi `unchanged`, a harmonogram, który nie znalazł nic nowego,
  zostawia historię w spokoju.
- Zachowywane są tylko najnowsze wersje, `ARTIFACT_MAX_VERSIONS` z nich
  (domyślnie 20). Starsza wersja jest usuwana, gdy pojawia się nowa. Rozmowa,
  która linkuje do usuniętej wersji, mówi, że wersja nie jest już przechowywana,
  i proponuje najnowszą.

## Obsługiwane formaty { #supported-formats }

| Format | Co jest przechowywane | Co jest serwowane |
|---|---|---|
| HTML (`.html`, `.htm` albo `format: html`) | Dokument tak, jak agent go napisał | Ten sam dokument |
| Markdown (`.md`, `.markdown` albo `format: markdown`) | Źródło w Markdownie | Źródło wyrenderowane do prostej strony, razem z tabelami. Surowy HTML w nim jest escapowany |

Jedna wersja to jeden samodzielny dokument o rozmiarze najwyżej
`ARTIFACT_MAX_BYTES` (domyślnie 5 MiB). Nie ma paczek wieloplikowych: wstaw arkusz
stylów, skrypt i obrazy (jako URI `data:`) do tego jednego pliku.

!!! warning "Strona nie ma sieci"

    Skrypty działają, więc wykres rysowany przez wstawioną inline bibliotekę
    zadziała. Ale strona nie może niczego skądkolwiek załadować ani niczego
    nigdzie wysłać — skrypt z CDN, font z adresu URL i wywołanie API kończą się
    błędem. Narzędzie mówi to modelowi. To celowe, a następna sekcja wyjaśnia
    dlaczego.

## Kto może go otworzyć { #who-can-open-it }

Nowy artefakt jest **prywatny** dla osoby, w imieniu której działał publikujący
run: dla osoby na czacie albo dla twórcy triggera. Na jego stronie w **Artifacts**
każdy, kto może nim zarządzać, może go udostępnić na trzy sposoby:

| Zasięg | Jak | Kto |
|---|---|---|
| Konkretne osoby | Grant, na poziomie `read` albo `edit` | Ci członkowie, w tej organizacji |
| Organizacja | Widoczność ustawiona na całą organizację | Każdy członek, którego rola sięga do udostępnionych artefaktów |
| Każdy, kto ma link | **Create a public link** | Każdy, kto zna adres, bez konta |

Udostępnianie i widoczność korzystają z tego samego panelu i tych samych reguł co
agenci i skille; zobacz [Uprawnienia](permissions.md). Zarządzanie artefaktem —
udostępnianie go, jego publiczny link, usuwanie — wymaga `artifacts:edit` na tym
artefakcie, z roli albo z grantu `edit`. Otwarcie go wymaga `artifacts:view`.

Agent nie może poszerzyć grona czytelników strony. Agent publikuje; o tym, kto ją
widzi, decyduje człowiek. Dlatego capability domyślnie nie prosi o zatwierdzenie:
pierwsza publikacja jest prywatna. Autor, który chce, żeby człowiek zatwierdzał
każdą ponowną publikację już udostępnionej strony, ustawia `tool_approval` na
`publish_artifact` w specu.

### Publiczny link { #the-public-link }

Publiczny link to `/a/<key>` pod własnym adresem konsoli, z losowym kluczem o
długości 192 bitów — według tej samej reguły co klucz hostowanej strony czatu.
Zawsze pokazuje najnowszą wersję i nie mówi nic o tym, kto ją opublikował ani do
której organizacji należy.

**Replace the link** wydaje nowy klucz, a stary od razu przestaje cokolwiek
otwierać. **Turn off** usuwa link. Oba działania trafiają do dziennika audytu.
Strona, którą ktoś ma już otwartą, wyświetla się dalej, dopóki nie wygaśnie jej
podpisany adres treści — najwyżej `ARTIFACT_VIEW_TTL_SECONDS` (domyślnie pięć
minut).

Odwołany członek jest w tej samej sytuacji: traci artefakt przy następnym
żądaniu, a strona, którą miał już otwartą, zostaje najwyżej przez to samo okno.

## Jak strona jest izolowana { #how-the-page-is-isolated }

Artefakt to HTML ze skryptem w środku, napisany przez model, który mógł przeczytać
coś wrogiego. Jest serwowany tak, żeby nic, co robi, nie mogło dosięgnąć konsoli
ani osoby, która go ogląda:

- Bajty pochodzą z osobnej trasy, `/api/v1/artifact-content/<token>`, która nie
  czyta żadnego ciasteczka ani sesji. Token jest podpisany, wskazuje jedną wersję
  i wygasa po kilku minutach. Jest wydawany dopiero wtedy, gdy grant albo
  publiczny link dopuściły wywołującego.
- Każda odpowiedź z treścią niesie `Content-Security-Policy: sandbox
  allow-scripts allow-popups allow-popups-to-escape-sandbox allow-modals`, bez
  `allow-same-origin`. Strona działa w nieprzezroczystym originie (opaque
  origin), więc nie może czytać ciasteczek, pamięci ani strony konsoli, a
  żądanie, które wyśle, nie niesie niczego od oglądającego. To obowiązuje nawet
  wtedy, gdy ktoś otworzy adres treści bezpośrednio.
- Ta sama polityka ustawia `default-src 'none'` i `connect-src 'none'` bez
  żadnego zdalnego źródła, a `frame-ancestors` wymienia tylko konsolę. Ramka w
  konsoli niesie tę samą listę `sandbox` jako drugi zamek.

Ponadto wdrożenie może serwować treść z **osobnej domeny rejestrowalnej**,
ustawiając `ARTIFACT_ORIGIN` — na przykład
`https://agenticos-content.example.net`, skierowaną do tego samego API. Strona
jest wtedy w zupełnie innej witrynie. Nieprzezroczysty origin już ją izoluje, więc
to jest utwardzenie, o które może poprosić przegląd bezpieczeństwa, a nie wymóg.
Ustaw zmienną dla backendu i dla frontendu, który dodaje ten origin do swojego
`frame-src`. Zobacz [Konfiguracja](configuration.md#published-artifacts).

## Retencja i usuwanie { #retention-and-deletion }

Artefakty są osobną [klasą retencji](governance.md#the-classes), liczoną od
**ostatniej publikacji** — raport publikowany ponownie co tydzień żyje, niezależnie
od tego, jak stara jest jego pierwsza wersja. Jak każda klasa, trzyma artefakty
bezterminowo, dopóki organizacja albo wdrożenie nie ustawi okresu.

Usunięcie artefaktu — ręcznie albo przez retencję — usuwa każdą wersję, jej
przechowywane bajty, jego granty i jego publiczny link. Usunięcie agenta nie
usuwa jego artefaktów: pozostają czytelne i po prostu nie mają wydawcy. Usunięcie
organizacji je usuwa. Artefakty usuniętej osoby zostają i tracą właściciela, tak
jak jej agenci i skille.

Bajty leżą w [magazynie plików](configuration.md#uploaded-files-at-rest)
wdrożenia, pod `artifacts/<organization>/<artifact>/`.

## Ograniczenia { #limitations }

- **Jeden samodzielny dokument na wersję.** Bez paczek i bez sieci z wnętrza
  strony.
- **Bez danych na żywo.** Dashboard pokazuje dane, z którymi został opublikowany.
  Odświeża się, gdy agent opublikuje go ponownie — zwykle robi to harmonogram.
- **Agent nie może odczytać swoich artefaktów z powrotem.** Raport jest budowany
  na nowo ze swoich danych, a nie edytowany z ostatniej wersji.
- **Otwarta strona przeżywa odwołanie o jeden czas życia podpisanego adresu**,
  domyślnie pięć minut.
- **Usunięte wersje przepadają.** Rozmowa, która linkuje do wersji starszej niż
  przechowywane okno, może zaproponować tylko najnowszą.

## Podsumowanie { #recap }

- Jedna capability, jedno narzędzie: `publish_artifact`, z pliku w workspace'ie
  albo inline.
- Agent i nazwa to tożsamość; ponowna publikacja zachowuje link i dodaje wersję.
- Domyślnie prywatny; udostępniany grantami, organizacji albo publicznym linkiem —
  przez człowieka.
- Serwowany z trasy bez ciasteczek, w nieprzezroczystym originie bez sieci, i
  opcjonalnie z własnej domeny.
- Osobna klasa retencji, liczona od ostatniej publikacji.
