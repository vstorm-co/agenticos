---
source_sha: 2a08473da582
---

# Aplikacja desktopowa { #the-desktop-app }

AgenticOS działa w przeglądarce i tak używa go większość ludzi. Aplikacja
desktopowa jest dodatkiem dla tych, którzy chcą mieć go w docku: konsola we
własnym oknie plus zwierzak i skrót do zrzutu ekranu. Nic w samej platformie jej
nie potrzebuje.

<figure markdown>
  ![Amigo, zwierzak z pulpitu, mówi: No more caramba.](assets/desktop_no_more_caramba_pet.png){ width="270" }
  <figcaption>Amigo, jeden z pięciu zwierzaków. No more caramba in your AI.</figcaption>
</figure>

Aplikacja wewnątrz okna to ta sama konsola w Next.js, którą serwer już serwuje,
ładowana z serwera, więc niesie to samo logowanie, te same uprawnienia i te same
sprawdzenia tenanta co zakładka przeglądarki.

Jest to powłoka [Tauri](https://tauri.app) w `desktop/` i trzyma dokładnie jedno
ustawienie: adres serwera. Pierwsze uruchomienie o niego pyta, „Shell → Change
server…" pyta ponownie, a wszystko pomiędzy to konsola.

!!! note "To powłoka, a nie build frontendu"

    `frontend/` to aplikacja Next.js z serwerową połową — kilkadziesiąt route
    handlerów przekazujących żądania do backendu, ciasteczka sesji, które
    ustawiają, middleware wybierające lokalizację i strony renderowane na
    serwerze. Nic z tego nie działa wewnątrz binarki desktopowej, więc powłoka nie
    próbuje: otwiera URL wdrożenia tak, jak zrobiłaby to przeglądarka. Instalujesz
    wdrożenie; aplikacja jest tym, czym je otwierasz.

## Uruchamianie { #running-it }

Wymagania wstępne to Rust z [rustup](https://rustup.rs) i webview danej platformy
— WebKit na macOS, WebView2 na Windowsie, WebKitGTK na Linuksie; listę dla każdej
platformy ma własna
[strona wymagań](https://v2.tauri.app/start/prerequisites/) Tauri. Tauri CLI jest
przypięte w `desktop/package.json`, a `make install` pobiera je razem z całą
resztą.

```bash
make desktop-dev     # opens the shell; type the address of a console
make desktop-build   # a .app / .dmg, .msi or .deb/.AppImage for this machine
make desktop-check   # rustfmt, clippy with warnings denied, and the tests
```

Za pierwszym razem okno pokazuje formularz pytający, gdzie jest serwer,
wypełniony wartością `http://localhost:3000` — czyli stosem z `make dev`. Sam
host (`agenticos.acme.com`) jest otwierany po HTTPS. Wszystko, co nie jest
adresem webowym, zostaje na formularzu odrzucone.

!!! warning "Zwykłe `http://` jest tylko dla tej maszyny"

    `localhost`, `127.0.0.1` i `::1` mogą być osiągane otwartym tekstem; każdy
    inny host zostaje odrzucony, dopóki nie jest `https://`. Konsola wysyła na tym
    połączeniu hasło i odbiera token, a sieć LAN to dokładnie miejsce, w którym
    ktoś inny może to przeczytać.

Adres, na którym nic nie odpowiada, też zostaje odrzucony: powłoka otwiera
połączenie TCP, zanim skieruje gdziekolwiek webview, ponieważ WebKit maluje
odrzucone połączenie jako puste białe okno. Ta sama sonda działa przy każdym
uruchomieniu, więc stos, który leży, odsyła cię z powrotem na formularz wraz
z przyczyną, zamiast stawiać przed pustym oknem.

Odpowiedź jest zapisywana jako `server.json` w katalogu konfiguracyjnym aplikacji
właściwym dla platformy — `~/Library/Application Support/co.vstorm.agenticos/` na
macOS, `%APPDATA%\\co.vstorm.agenticos\\` na Windowsie,
`~/.config/co.vstorm.agenticos/` na Linuksie — i odczytywana ponownie przy każdym
uruchomieniu.

Plik, który przestał się parsować — literówka przy ręcznej edycji — zostaje przy
następnym uruchomieniu odłożony na bok jako `server.json.invalid`, a formularz
połączenia zapisuje świeży.

Zły adres poprawia się na cztery sposoby, którykolwiek jest bliżej:
**Settings…** (`⌘,`, także na ikonie w zasobniku i w menu kontekstowym zwierzaka,
więc jest osiągalne nawet wtedy, gdy okno pokazuje niewłaściwą stronę),
**Shell → Change server…**, edycja tego pliku albo uruchomienie z terminala
z `--server http://localhost:3000`, co też go zapisuje.

## Zwierzak { #the-pet }

Małe stworzonko w pixel-arcie we własnym, przezroczystym oknie zawsze na wierzchu:
siedzi na pulpicie, kiedy konsola jest otwarta, zminimalizowana albo zamknięta,
tak jak robią to zwierzaki Codexa. Przeciągnij go, gdzie chcesz; kliknij, a
pomacha; kliknij dwukrotnie, a podskoczy i wysunie konsolę na wierzch, otwierając
ją ponownie, jeśli okno było zamknięte. Zostawiony sam sobie stoi bezczynnie,
rozgląda się, przechadza kawałek po ekranie i zawraca przy krawędzi, a od czasu
do czasu przysypia.

Najedź na niego, a nad jego głową pojawi się przycisk **+ New chat**; ustawia on
konsolę na świeżej rozmowie, otwierając okno, jeśli było zamknięte. Kliknij
zwierzaka, a coś powie, w dymku, własnym głosem. Pogłaszcz go — kursorem tam
i z powrotem po nim kilka razy — a zamknie oczy i wyskoczy serduszko. Kiedy stoi,
jego oczy podążają za kursorem. Po zmroku przysypia tam, gdzie w innym razie by
się przechadzał. Upuszczony po przeciągnięciu, ląduje z małym podskokiem.

Kliknij zwierzaka prawym przyciskiem, żeby otworzyć jego menu: nowy czat,
konsola, to, którym zwierzakiem jest, i to, czy jest pokazywany. To samo menu
jest na ikonie w zasobniku (na macOS w pasku menu) oraz pod **Pet** w pasku menu,
a wszystkie trzy to jeden zestaw pozycji, więc znacznik zmieniony w jednym jest
zmieniony w pozostałych.

**Show pet** (Cmd/Ctrl+Shift+P) chowa go i przywraca; to samo menu wybiera, który
to zwierzak — Orbit, okrągły, z anteną; Boxy, terminal na nogach; Ghost, który
unosi się w powietrzu; Sprout, nasionko z listkiem; Amigo, w sombrero i z wąsem,
for no more caramba in your AI. To, gdzie go zostawiono, czy jest pokazywany
i którym jest zwierzakiem, zapisuje się obok adresu serwera, więc przy następnym
uruchomieniu zwierzak jest tam, gdzie go postawiłeś. Przy systemowym ustawieniu
ograniczenia ruchu stoi nieruchomo i dalej daje się przeciągać.

Grafika jest komponowana w czasie działania w `desktop/ui/pet-sprites.js`: każdy
zwierzak to jedno ciało i opis tego, gdzie idą jego oczy, stopy i ręka, a każda
animacja to kilka linijek pozycji współdzielonych przez całą piątkę, a nie arkusz
sprite'ów na zwierzaka. To, co każdy z nich mówi, jest w `pet-lines.js`;
zachowanie oraz każda reguła mówiąca, kiedy głaskanie się liczy albo gdzie
patrzą oczy, są w `pet-engine.js`, czystym i przetestowanym. Własne okno jest
tym, co czyni go zwierzakiem, a nie widgetem, i tym, ile to kosztuje:
`macOSPrivateApi` w `tauri.conf.json`, bo przezroczyste okno na macOS tego
wymaga, co wyklucza Mac App Store — a to i tak nie jest miejsce, do którego
wybierała się self-hostowana konsola.

!!! note "Nie wie jeszcze, co robią agenci"

    Zwierzak Codexa nosi dymek mówiący, że run jest w toku albo że czeka
    zatwierdzenie. Nasz jeszcze nie potrafi: konsola jest zdalną stroną bez IPC do
    powłoki, a danie jej takiego kanału oznacza capability z URL-ami `remote` plus
    hook we frontendzie raportujący aktywność. To jest praca na później; zwierzak
    tutaj jest towarzystwem, a nie lampką statusu.

## Zrzut ekranu do nowego czatu { #screenshot-to-a-new-chat }

Naciśnij skrót — domyślnie `⌘⇧A`, gdziekolwiek jesteś — a pojawi się krzyżyk
znany z Cmd+Shift+4. Wybierz obszar, a konsola wyjdzie na wierzch na świeżym
czacie z już załączonym obrazkiem, gotowym pod pytanie. Escape anuluje. Ta sama
akcja jest w menu zwierzaka i na ikonie w zasobniku.

**Settings…** (`⌘,`, pod Shell, na ikonie w zasobniku i w menu kontekstowym
zwierzaka) pozwala przypisać skrót na nowo: kliknij pole, przytrzymaj modyfikatory
i naciśnij klawisz. Kombinacja potrzebuje co najmniej jednego modyfikatora —
globalny skrót na samej literze połykałby pisanie w każdej aplikacji — a taka,
którą trzyma już inna aplikacja, zostaje odrzucona z zachowaniem starego
przypisania. **Clear** wyłącza skrót. Przypisania zapisują się obok adresu
serwera. Przypisanie, którego nie udało się przejąć przy uruchomieniu, bo inna
aplikacja była pierwsza, zostaje nazwane na tej samej stronie, żeby dało się je
zastąpić, zamiast siedzieć tam i wyglądać na przypisane.

!!! note "Dwa modyfikatory same z siebie nie mogą być skrótem"

    Lewy Command plus prawy Command to akord, a nie klawisz: systemowa rejestracja
    skrótów, z której korzysta powłoka, potrzebuje w kombinacji klawisza
    niebędącego modyfikatorem. Wykrywanie akordu złożonego z samych modyfikatorów
    oznacza podsłuch zdarzeń przez API dostępności, który patrzy na każde
    naciśnięcie klawisza, i proszenie każdego użytkownika o zgodę na to. Nie w tej
    wersji.

Pierwsze naciśnięcie pyta macOS, czy AgenticOS może nagrywać ekran. Dopóki nie
może, nic nie da się przechwycić — systemowe narzędzie kończy działanie po cichu,
bez krzyżyka — więc powłoka sprawdza to najpierw, otwiera System Settings →
Privacy & Security → Screen Recording, a zwierzak mówi „Allow screen recording,
then restart me." Zgoda idzie do aplikacji *odpowiedzialnej*: do bundla AgenticOS,
gdy jest już spakowany, ale pod `make desktop-dev` do terminala, z którego
uruchomiono binarkę, albo do hostującego ją IDE — i to właśnie to trzeba
zaznaczyć na tej liście. Zgoda zaczyna działać po restarcie.

Obrazek dociera do kompozytora tak samo jak wybrany plik: powłoka uruchamia na
stronie konsoli skrypt, który podaje PNG do inputa plikowego kompozytora, więc
upload, limit rozmiaru i podgląd należą do samej konsoli. Jest podawany wyłącznie
stronie czatu na originie skonfigurowanego serwera — nigdy innej witrynie, na
którą okno mogło zawędrować — i tylko w ciągu dwóch minut od naciśnięcia; zrzut,
który nigdzie nie trafił, zostaje porzucony. Windows i Linux nie mają jeszcze
podpiętego przechwytywania.

## Czego celowo nie robi { #what-it-deliberately-does-not-do }

- **Żadnego lokalnego wykonywania.** Powłoka nie ma dostępu do maszyny poza
  jednym plikiem JSON. Agent uruchamiający polecenia na laptopie, z którego jest
  otwierany, to inna funkcja z innym modelem uprawnień — trzeci rodzaj połączenia
  sandboksa obok Dockera i Daytony, związany z maszyną jednej osoby, a nie
  z organizacją — i to nie jest ta funkcja.
- **Żadnego trybu offline.** Przy nieosiągalnym serwerze okno pokazuje własną
  stronę błędu webview; „Shell → Reload" ponawia próbę.
- **Żadnej straży nawigacji.** Link, który opuszcza origin serwera, otwiera się
  wewnątrz okna, a nie w przeglądarce systemowej, ponieważ przepływ OAuth —
  logowanie, podłączanie serwera MCP — opuszcza origin i musi wrócić do tego
  samego webview, żeby jego ciasteczko wylądowało. Kiedy okno pokazuje jakąkolwiek
  inną witrynę, jego tytuł nazywa tego hosta — to jedyny element chromu, którego
  strona nie może narysować, bo nie ma paska adresu — a `⌘,` albo „Shell → Change
  server…" to droga powrotna, jeśli strona nie ma linku do domu. Przeniesienie tych
  przepływów do przeglądarki systemowej to
  [#1532](https://github.com/vstorm-co/agenticos/issues/1532).
- **Logowanie zostaje w oknie, a okno mówi, że jest Safari.** Gołe user agent
  WebKita jest tym, co Google odrzuca jako osadzoną przeglądarkę
  (`disallowed_useragent`); okno konsoli niesie tokeny wersji Safari na tym samym
  silniku, więc logowanie Google działa. Przekazanie, które Google woli —
  przeglądarka systemowa i deep link z powrotem — potrzebuje jednorazowej wymiany,
  której backend jeszcze nie ma, i jest to
  [#1532](https://github.com/vstorm-co/agenticos/issues/1532).

## Gdzie siedzi w drzewie { #where-it-sits-in-the-tree }

`desktop/ui/` to formularz połączenia i zwierzak, pliki statyczne bez żadnego
kroku budowania; `bun test` uruchamia tam testy sprite'ów i zachowania zwierzaka.
`desktop/src-tauri/` to strona rustowa: komendy, które wołają obie strony, dwa
okna i menu. `desktop-check` nie jest częścią `make lint` ani `make check`: CI nie
ma jeszcze toolchaina Rusta, a `tests/test_ci_parity.py` odrzuciłby `check`, który
uruchamia krok nieobecny w CI. Uruchom go przed wypchnięciem zmiany pod
`desktop/`.

## Podsumowanie { #recap }

- **Konsola zostaje na serwerze.** Powłoka ją otwiera; nic nie jest dołączane do
  paczki.
- **Jeden plik ustawień.** Adres serwera, o który pyta się raz, i to, gdzie
  zostawiono zwierzaka — jedno i drugie zmienialne z menu.
- **Zrzut ekranu jest o jeden skrót stąd.** `⌘⇧A`, obszar, świeży czat
  z załączonym obrazkiem; skrót przypisuje się na nowo w Settings (`⌘,`).
- **Na razie nic lokalnego.** Lokalne wykonywanie to rodzaj połączenia sandboksa
  do zaprojektowania, a nie flaga na tej powłoce.
