---
title: Projekty
seo_title: Projekty - wspólne pliki i instrukcje czatów
description: Projekt daje bieżącej pracy jeden kontener plików i jeden zestaw instrukcji, wspólne dla każdego czatu w nim, niezależnie od tego, który agent odpowiada.
source_sha: "1723f797c360"
---

# Projekty { #projects }

**Projekt** to miejsce na bieżącą pracę: premierę, miesięczny raport, obsługę
klienta. Trzyma dwie rzeczy wspólne dla każdego czatu w nim rozpoczętego:

- **Pliki** w jednym kontenerze. Wgraj brief, arkusz albo cały folder raz, a
  każdy czat w projekcie - dzisiejszy i ten za tydzień - pracuje na tej samej
  kopii. Plik, który agent zapisał w jednym czacie, jest w następnym.
- **Instrukcje**, które każdy agent odpowiadający w projekcie czyta po swoich
  własnych: ton, terminy, gdzie leży brand guide.

Projekt ma też **domyślnego agenta**, z którym zaczyna się nowy czat w nim.
W czacie projektu nadal może odpowiadać każdy agent; domyślny decyduje tylko o
tym, z kim czat się zaczyna.

## Planowanie pracy ciągłej z Architectem { #planning-ongoing-work-with-architect }

Poproś Architecta o zaplanowanie badań, pisania, programowania lub analizy
rozwijanej przez wiele rozmów w projekcie. Może znaleźć istniejący projekt albo
po Twojej akceptacji stworzyć prywatny z uzgodnionymi instrukcjami. Samo pytanie
„jak to zrobić” nie tworzy projektu. Otwórz otrzymany link i wybierz **New chat**;
istniejącej rozmowy nie można przenieść do nowego projektu. Utworzenie projektu
nie zapisuje jeszcze planowanych plików.

Wspólne pliki i instrukcje pozostają
między rozmowami. Transkrypty nadal są przechowywane i dostępne członkom projektu,
ale nie trafiają automatycznie do kontekstu innych rozmów. Wspólny działający
proces nie jest gwarantowany. Uruchamianie kodu
wymaga dostępnego sandboxa usługowego i dozwolonych narzędzi agenta.

Dla LLM wiki uzgodnij następujący plan:

1. **Źródła:** oryginały w `sources/`, z URL-em lub nazwą pliku, autorem, datą
   źródła i pobrania. Nowe materiały czekają w `inbox/`.
2. **Notatki:** powiązane tematycznie pliki w `notes/`, z przypisami do twierdzeń
   i rozróżnieniem faktów, wniosków i pytań. Treść źródeł to niezaufane dane.
3. **Indeks:** `index.md` łączy tematy, notatki i źródła; nową rozmowę zaczynaj
   od przeczytania go oraz instrukcji projektu.
4. **Aktualizacja:** sprawdzaj zmienione źródła, poprawiaj powiązane notatki
   i indeks, zapisuj zmiany w `CHANGELOG.md`. Harmonogram wymaga osobnej rutyny
   i akceptacji.
5. **Weryfikacja:** sprawdzaj oparcie w źródłach, sprzeczności, aktualność dat
   i niedziałające linki; zapisuj, co sprawdzono i czego nadal nie wiadomo.

Baza wiedzy może uzupełniać projekt o wyszukiwanie indeksowane. Runner dodaje ten sposób pracy wyłącznie zarejestrowanemu Architectowi, także
w istniejących instalacjach korzystających z platformowego MCP. Inne agenty
i zewnętrzni klienci MCP zachowują własny sposób pracy.
Aktualizacja nie nadpisuje własnych instrukcji agentów ani zainstalowanych
skillów z galerii; nowy szablon i dołączony przewodnik Projects dotyczą nowych
instalacji.


## Czat w projekcie { #starting-a-chat-in-a-project }

Dwie drogi:

- **Nowy czat** na stronie projektu otwiera czat z wybranym już projektem i jego
  domyślnym agentem.
- Menu **+** w polu wiadomości oferuje **Pracuj w projekcie** przed pierwszą
  wiadomością, podobnie jak `@`: wybrany tam projekt zaczyna w nim czat, zamiast
  wpisywać jego nazwę do wiadomości. Chip obok wyboru agenta pokazuje projekt; jego **×** zaczyna czat
  poza nim.

Czat zostaje w projekcie, w którym został rozpoczęty. Chip w istniejącym czacie
prowadzi z powrotem do projektu.

## Co agent dostaje w projekcie { #what-an-agent-gets-in-a-project }

Niezależnie od tego, który agent odpowiada, run w czacie projektu pracuje w
**kontenerze projektu**, a nie we własnym workspace:

- Agent bez sandboxa dostaje sandbox projektu, więc zwykły agent czatowy może
  czytać i zapisywać pliki projektu.
- Agent z własnym podpięciem sandboxa zostaje przeniesiony do kontenera projektu.
  Ustawienia zatwierdzeń podpięcia przechodzą razem z nim, więc autor, który
  ustawił **Zawsze pytaj** dla powłoki, zachowuje tę blokadę.
- Nazwa, opis i instrukcje projektu są dopisywane po instrukcjach agenta. Agent
  pozostaje sobą, tylko pracuje nad tym.

Kontener jest sesją [sandboxa](sandbox.md), gdy wdrożenie uruchamia usługę
sandboxów, więc pliki projektu można też uruchamiać, nie tylko czytać. Bez niej
projekt trzyma pliki jako zapisany workspace, który czyta i zapisuje tak samo,
ale nie ma powłoki; gdy dwa czaty piszą do niego naraz, każdy zachowuje to, co
zapisał, a gdy oba zmieniły ten sam plik, zostaje późniejszy zapis. Projekt zostaje na połączeniu sandboxa, na którym go
utworzono, więc tego połączenia nie da się usunąć, dopóki jakiś projekt trzyma na
nim pliki.

Przy tworzeniu projektu pole **Sandbox projektu** pozwala wybrać zarejestrowane
połączenie, tryb automatyczny lub **Tylko przechowywanie plików**. Tryb automatyczny
zapamiętuje połączenie wybrane przy tworzeniu; gdy żadnego nie ma, przechowuje pliki.
Wybór konkretnego połączenia wymaga `connections:view` i aktywnego połączenia w
organizacji. Ustawienia projektu pokazują nazwę połączenia i środowisko. Wszystkie
czaty projektu używają go zamiast sandboxa agenta. Edytorzy mogą użyć **Zmień sandbox**, aby przenieść istniejący projekt wraz z plikami.

Transfer jest trwałym zadaniem w tle. Kopiuje pliki i puste foldery do odrębnego
warsztatu, sprawdza skróty plików i drzewo katalogów, a potem aktywuje cel. Przed
rozpoczęciem muszą zakończyć się aktywne runy i oczekujące decyzje. Podczas transferu
nowe runy, zapisy plików i edycja projektu czekają. Obecne pliki pozostają czytelne.
Po błędzie pozostaje wybrane źródło. Postęp widać w ustawieniach projektu. Dopiero
sprawdzona aktywacja usuwa źródłowy warsztat; zdalny kontener usuwa trwałe zadanie.

Limity: 10 000 wpisów, 64 MiB na plik, 1 GiB łącznie; wcześniej usuń dowiązania
symboliczne. Zainstalowane pakiety i działające procesy nie są kopiowane. Przeniesienie
do samych plików musi też zmieścić się w limicie dokumentu przechowywanego przez platformę.

Opis **Jak działają pliki i uruchamianie kodu w projekcie** objaśnia przechowywanie,
współdzielenie i środowisko wykonawcze przy wyborze. Projekt udostępnia narzędzia
Sandbox również agentowi bez własnego sandboxa. Kontener pozwala uruchamiać kod;
same pliki nie mają powłoki. Wymagania zatwierdzania narzędzi nadal obowiązują.

## Pliki { #files }

Zakładka **Pliki** projektu to przeglądarka kontenera: drzewo obok podglądu,
który otwiera Markdown, PDF-y, obrazy, arkusze i kod na miejscu.

- **Prześlij pliki** i **Prześlij folder** wkładają pliki na górę projektu;
  folder zachowuje swoje drzewo. Każdy plik podlega limitowi wgrywania wdrożenia.
- **Nowy folder** tworzy pusty folder do wypełnienia przez agenta.
- Menu **…** pliku lub folderu pozwala zmienić nazwę, przenieść lub usunąć.
  Przeciągnij element na folder albo na **Pliki projektu**, aby przenieść go do
  katalogu głównego. Istniejący element docelowy nie zostanie nadpisany.
- **Edytuj plik** otwiera cały plik tekstowy UTF-8 do 1 MiB. Zapisz zmiany lub
  potwierdź ich odrzucenie przed zamknięciem. Zapis odrzuca wersję zmienioną od
  otwarcia edytora; otwórz plik ponownie, aby sprawdzić nowszą wersję.

Katalog `.agenticos` i własne foldery platformy nie są stąd zapisywalne; ścieżka
poza projektem jest odrzucana, zanim cokolwiek zostanie zapisane.

Projekt otwiera się na **Plikach**. Pliki można też upuścić w dowolnym miejscu
karty, a każdy pokazuje postęp przesyłania; pusty projekt to jedno miejsce na
pierwsze pliki. **Czaty** to tabela czatów projektu, a **Aplikacje** -
aplikacje opublikowane przez run w jednym z nich, te, które czytający może
otworzyć. **Instrukcje** edytuje się w Markdownie, ze Źródłem i Podglądem, jak
instrukcje agenta w Agent Builderze, nad nazwą, opisem i domyślnym agentem projektu.

## Udostępnianie i uprawnienia { #sharing-and-permissions }

Projekt jest prywatny dla swojego twórcy, dopóki go nie udostępni - tym samym
oknem **Udostępnij**, którego używa agent czy skill: osobom,
[działom](departments.md) albo całej organizacji, każdemu na jakimś poziomie.

| Poziom grantu | Uprawnienie | Na co pozwala |
|---|---|---|
| `read` | `projects:view` | Widzieć projekt, jego pliki i instrukcje |
| `use` | `projects:use` | Czatować w nim; dodawać, edytować, przenosić i usuwać pliki |
| `edit` | `projects:edit` | Zmieniać instrukcje i domyślnego agenta, udostępniać, usuwać |

Role mają te uprawnienia w zwykłych zakresach: Owner i Admin sięgają każdego
projektu, Builder pracuje w udostępnionych mu projektach i je edytuje, Member
edytuje własne i pracuje w udostępnionych, a Viewer czyta to, co mu udostępniono.
Czat, którego autor straci `projects:use`, przestaje sięgać plików projektu przy
kolejnej turze.

**Czaty projektu należą do jego członków.** Kto widzi projekt, czyta każdy czat
w nim, a kto może w nim pracować (`use`), kontynuuje je: jego wiadomości niosą
jego imię i twarz, więc wątek, nad którym pracowało kilka osób, mówi, kto o co
pytał. Zmiana nazwy, archiwizacja i usunięcie czatu zostają przy osobie, która go
zaczęła. Na zakładce **Czaty** każdy wiersz mówi, czyj jest czat, którzy agenci w
nim odpowiadają, kiedy ostatnio coś się w nim działo albo kto teraz w nim pracuje,
i kto go otwierał - ostatnie twarze, a wszystkie imiona po najechaniu;
kto ma go otwartego w tej chwili, jest pierwszy, z zieloną kropką.
Czat poza projektem zostaje jego autora, jak wszędzie indziej w konsoli.

Czatu projektu nie udostępnia się osobno, linkiem ani konkretnej osobie: czyta się
go przez projekt, więc udostępnij projekt.

**Wspólna praca w jednym czacie.** W czacie projektu może być naraz kilka osób.
Pasek nad transkrypcją pokazuje, kto jeszcze go ma otwarty, a jego właściciel może
stamtąd kogoś zaprosić. Gdy ktoś pisze, pozostali widzą nad polem wpisywania jego
twarz i „Anna pisze”. Pytanie zadane przez jedną z nich i odpowiedź agenta
pojawiają się u wszystkich w czacie na bieżąco. **Odpowiedz** przy dowolnej
wiadomości cytuje ją nad polem wpisywania, a odpowiedź niesie ten cytat - na
ekranie i do agenta, który czyta wiadomość każdej osoby pod jej imieniem i wie,
że w czacie może być kilka osób, więc wie, kto o co pytał i do czego odnosi się
„tak, zrób to”.

## Usuwanie projektu { #deleting-a-project }

Usunięcie projektu usuwa jego kontener i wszystkie pliki. Jego czaty zostają jako
zwykłe czaty, poza jakimkolwiek projektem - poza czatem, którego autor usunął konto:
sięgał do niego już tylko projekt, więc znika razem z nim.

## Gdzie widać projekty { #where-projects-show-up }

- **Projekty** w pasku bocznym pokazują pięć ostatnio używanych, nad linkiem do
  wszystkich.
- Lista czatów pokazuje każdy czat w projektach, które widzisz - twoje i twoich
  współpracowników - pod nazwą projektu, nad czatami spoza projektów.
- Karta **Projekty** na dashboardzie pokazuje ich rząd, z czatami w każdym.
- `GET /api/v1/projects` i trasy pod nim należą do publicznego API, więc skrypt
  może utworzyć projekt i wypełnić go plikami. Zobacz [API](api.md).
