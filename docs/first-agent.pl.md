---
source_sha: 86db3a8931da
---

# Twój pierwszy agent { #your-first-agent }

Ta strona przechodzi całą drogę raz: klucz providera, model, agent, który
odpowiada, opublikowana wersja i run z kosztem po swojej stronie.

Piętnaście minut i mniej więcej cent tokenów.

Najpierw potrzebujesz działającego stosu — zobacz [Instalację](install.md).

!!! tip "Produkt przeprowadzi cię przez to również sam"

    Przy pierwszym zalogowaniu kogokolwiek na dashboardzie otwiera się
    przewodnik, a jego ukończenie proponuje zbudowanie pierwszego agenta *razem
    z tobą*, obsługując prawdziwe dialogi.

    Ścieżkę ręczną i tak warto przeczytać raz — i tym właśnie jest ta strona.
    Prowadzona jest opisana [na końcu](#the-guided-walkthrough).

## 1. Zapisz klucz providera { #1-store-a-provider-key }

**Settings → Vault → Add credential.**

Wybierz providera, wklej klucz, nadaj mu etykietę. Wartość jest pieczętowana
natychmiast i nie ma endpointu, który by ją zwracał — wraca etykieta i cztery
ostatnie znaki.

!!! info "Dlaczego vault, a nie plik konfiguracyjny"

    Klucz w środowisku należy do wdrożenia. Klucz w vaulcie należy do
    **organizacji**, a to właśnie pozwala jednemu wdrożeniu obsługiwać kilku
    tenantów tak, że żaden nie może wydać budżetu drugiego.

    Szyfrogram jest związany z organizacją, która go zapisała, i nie da się go
    odszyfrować dla innej.

## 2. Dodaj model { #2-add-a-model }

**Agents → dowolny agent → Build → Model.**

Wybierz providera, potem model, a potem to, który zapisany klucz za niego płaci.

Lista modeli pochodzi od providera tam, gdzie ją publikuje, i z dołączonej krótkiej
listy tam, gdzie jej nie publikuje. To sugestia, nigdy ograniczenie — provider
wypuszcza model nazajutrz po rozgrzaniu dowolnego katalogu, więc cokolwiek
wpiszesz, zostanie przyjęte.

To, co właśnie stworzyłeś, to **profil modelu**: nazwany model oparty o nazwany
klucz.

Nazwanie go jest tu sednem. Pozwala zrotować klucz albo przestawić każdego agenta
na nowy model, nie dotykając ani jednego agenta.

## 3. Zbuduj agenta { #3-build-the-agent }

**Agents → New agent.**

!!! tip "Albo zacznij od szablonu"

    **Agents → Agent templates** dostarcza dwadzieścia osiem gotowych agentów
    pogrupowanych według branży, każdego z napisanymi instrukcjami, włączonymi
    capabilities i zainstalowanymi obok skillami, których potrzebuje.

    Taki agent przychodzi jako **draft**, a nie opublikowany, i to celowo: szablon
    nie może wybrać twojego modelu i nigdy nie widział twojej kolekcji wiedzy.
    Reszta tej strony to to, co robisz dalej — tak czy inaczej.

Nazwa staje się uchwytem, po którym adresuje się agenta ze Slacka i z API,
i jest zamrażana przy tworzeniu — `Support Copilot` staje się
`@support-copilot`.

Zakładka **Build** to instrukcje i model, a instrukcje są całością zachowania
agenta:

```markdown
You are Support Copilot.

Answer from the product wiki and cite the document you used.
If the wiki does not cover it, say so rather than guessing.
Never quote a price - route those to sales.
```

Pisz je w Markdownie. Model czyta strukturę, a nagłówki i listy są tym, co czyni
długi prompt możliwym do prześledzenia.

!!! note "Nie ma przycisku Save"

    Draft zapisuje się sam w trakcie pisania. Builder z przyciskiem Save to
    Builder, w którym zakładka zamknęła się na dwudziestu minutach instrukcji.

## 4. Daj mu capabilities { #4-give-it-capabilities }

**Toolbox.**

Każda capability pokazuje dokładnie, co wnosi — każde narzędzie, jego opis
i argumenty, które model musi wypełnić — *zanim* ją włączysz. Przeczytanie
capability to nie to samo co jej przyznanie.

Dwie rzeczy warto tu wiedzieć:

- **Nazwa i opis narzędzia są promptem.** Po `search_refund_policy` model sięga
  przy pytaniach, przy których pomija `search_documents`. Oba da się edytować per
  agent.
- **Wszystko, co ma skutki uboczne, domyślnie prosi o zatwierdzenie.** Run
  parkuje i czeka na człowieka. Ustaw to per capability albo per narzędzie.

## 5. Daj mu coś do czytania { #5-give-it-something-to-read }

**Knowledge → Collections** dla dokumentów. **Skills** dla spisanego know-how.

Różnica ma znaczenie:

| | |
|---|---|
| **Kolekcja** jest *przeszukiwana* | Model wybiera, czego szukać, i nigdy nie może poszerzyć tego, gdzie szuka |
| **Skill** jest *czytany* | Agent ładuje go dopiero wtedy, gdy uzna skilla za istotnego, więc dwadzieścia skilli kosztuje w kontekście prawie nic |

Każda kolekcja podaje, ile trzyma dokumentów, bo podpięcie pustej daje agenta,
który szuka, nic nie znajduje i tak mówi — a to czyta się jak zepsuty agent,
a nie jak pusta kolekcja.

## 6. Ustaw limit i powiedz, kto ma być informowany { #6-set-a-limit-and-say-who-is-told }

**Limits.** Miesięczny cap w dolarach, limit kroków i to, kto się o tym
dowiaduje.

Limit kroków jest tym, o którym ludzie zapominają. Łapie drugi rodzaj rozbiegania
się: pętlę narzędzia, która jest tania w przeliczeniu na wywołanie i nigdy się nie
kończy. Budżet tylko ją rozlicza; limit kroków ją zatrzymuje.

W sekcji **Alerts** zdecyduj, kto jest informowany, gdy ten agent zatrzyma się na
swoim capie albo zaparkuje na zatwierdzeniu. Domyślnie o budżecie dowiadują się
administratorzy i właściciel agenta, a o zatwierdzeniach ten, kto uruchomił runa,
plus administratorzy — więc run uruchomiony przez harmonogram nie parkuje bez
świadka.

[Governance](governance.md) opisuje, jak budżety, zatwierdzenia i alerty łączą
się w całość.

## 7. Opublikuj { #7-publish }

**Publish** najpierw waliduje draft, więc to jest też miejsce, w którym
dowiadujesz się, że spec odwołuje się do kolekcji, którą ktoś usunął.

!!! success "Spec odwołujący się do czegoś, czego brakuje, zostaje odrzucony tutaj, nigdy w czasie runa"

    I to jest cały powód, dla którego walidacja dzieje się przy publikacji: ktoś
    patrzy na formularz i może to poprawić, zamiast dowiadywać się trzy tygodnie
    później w runie uruchomionym przez harmonogram.

Publikacja zamraża **wersję**. Runy zapisują, która wersja się wykonała, więc to,
co agent zrobił w zeszły wtorek, pozostaje odpowiadalne po kilkunastu edycjach.

## 8. Uruchom go { #8-run-it }

**Test**, w nagłówku, otwiera czat z opublikowanym agentem. Zapytaj go o coś.

Potem zajrzyj do **Activity**: run, wersja, która się wykonała, model, do którego
się rozwiązał, tokeny i to, ile kosztował. Jeśli jakieś narzędzie potrzebowało
zatwierdzenia, jest tam w kolejce.

## 9. Umieść go gdzieś { #9-put-it-somewhere }

**Availability** to miejsce, w którym agent przestaje być rzeczą w Builderze:

| | |
|---|---|
| **Exposures** | Kto może go uruchamiać i jak — klucze API, publiczne linki |
| **Channel bots** | Slack i Telegram. `@support-copilot` na kanale działa jako *nadawca*, nigdy jako bot |
| **Embeds** | Widget na twoje własne strony |
| **Environments** | Nazwane wskaźniki na wersje, żeby staging i produkcja mogły się różnić |

## Wyeksportuj go { #export-it }

**Download** daje ci spec w postaci YAML-a.

Nazywa on odwołania — profil modelu, kolekcję, sekret — a nigdy wartości, i to
właśnie sprawia, że można go bezpiecznie zacommitować do własnego repozytorium
i recenzować jak kod.

```yaml
name: Support Copilot
instructions: |
  You are Support Copilot.
  Answer from the product wiki and cite the document you used.
model_profile_id: 8f1c...
capabilities:
  - id: knowledge
    config: { default_top_k: 8 }
collection_ids: [b2a9...]
budget:
  monthly_usd: 50
```

## Podsumowanie { #recap }

Dziewięć kroków, a ich kształt jest kształtem platformy:

1. Zapieczętowałeś **klucz** w vaulcie, per organizacja.
2. Nazwałeś **profil modelu**, żeby klucz i model mogły się zmieniać bez zmiany
   agenta.
3. Napisałeś **instrukcje**.
4. Włączyłeś **capabilities** i zostawiłeś te ze skutkami ubocznymi proszące
   o zatwierdzenie.
5. Podpiąłeś **wiedzę** do przeszukiwania i **skille** do czytania.
6. Ustawiłeś **budżet** i **limit kroków** i powiedziałeś, kto ma być
   informowany.
7. **Opublikowałeś**, co zamroziło wersję i zwalidowało spec.
8. **Uruchomiłeś** go i zobaczyłeś, ile kosztował.
9. Uczyniłeś go **osiągalnym** skądś innego niż Builder.

Wszystko po tym jest po prostu większą ilością kroków 4, 5 i 9.

## Prowadzony przewodnik { #the-guided-walkthrough }

Produkt uczy sam siebie i warto wiedzieć jak — bo przewodnik jest też tym, z
czego nauczy się produktu każdy, komu go przekażesz.

**Pokazuje się raz, a ? go odtwarza.** Ukończenie, pominięcie albo zamknięcie
przewodnika jest zapamiętywane przy koncie, a nie w przeglądarce, więc nie wraca
na kolejnym urządzeniu. **?** w nagłówku dowolnej strony objętej przewodnikiem
odtwarza jej wskazówki, kiedy tylko są potrzebne.

Jest oferowane tylko tam, gdzie jest co odtwarzać. Sekcja bez żadnych przystanków
— strony administracji wdrożenia — nie ma **?** w ogóle, zamiast mieć takie,
które otwiera pusty przewodnik. Wyjście z przewodnika mówi dokładnie to, więc
nikt nie odkrywa **?** przypadkiem ani wcale.

**Ukończenie go proponuje zbudowanie pierwszego agenta wspólnie.** To
interaktywny przepływ, a nie reflektor: wskazuje prawdziwe kontrolki, ty
obsługujesz prawdziwe dialogi, a przewodnik idzie dalej w momencie, w którym
rzecz naprawdę powstaje.

Kiedy trwa, strona jest **zamrożona** — wszystko przygasa poza tą jedną kontrolką,
o którą chodzi w danym kroku, więc nie da się odejść w środku przepływu i zostawić
prowadzonego kroku na niewłaściwej stronie. Zamrożenie samo ustępuje, ilekroć
otwiera się dialog albo picker, więc kontrolka, na którą wskazuje krok, jest
zawsze używalna.

Przewodnik jest adaptacyjny. Idzie ścieżką opisaną wyżej, sprawdza, co
organizacja już ma, i zatrzymuje się tylko tam, gdzie czegoś brakuje — ucząc
workspace bez modelu, jak go dodać, albo mówiąc builderowi, któremu brakuje
uprawnienia do dodania modelu, że go nie ma, zamiast prowadzić go w milczeniu do
publikacji, która odrzuci agenta bez modelu.

**Wiedza, skille i MCP to miejsca, w których robi najwięcej.** Gdy coś już jest,
przepływ po prostu wskazuje, gdzie się to podpina. Gdy nie ma nic, najpierw
przechodzi na własny ekran tej sekcji i *pyta tam* — „no knowledge base yet,
create one?" — żeby pytanie wylądowało tam, gdzie dzieje się odpowiedź.

Odpowiedź „tak" prowadzi tworzenie na miejscu, i nie tylko do przycisku:
przewodnik idzie za tobą do samego dialogu, obramowując po kolei każde pole tym,
co należy w nim wpisać — nazwę skilla, którą wywołuje go model, opis, który
decyduje o tym, kiedy jest czytany, przełącznik na Source, gdzie zapisuje się
know-how — i rusza dalej, kiedy rzecz naprawdę powstanie.

Potem prowadzi cię z powrotem, *wskazując*: na **Agents** w panelu bocznym, na
ołówek edycji przy dokładnie tym agencie, którego właśnie zbudowałeś, na zakładkę
Knowledge, gdzie podpina się nowa baza. Droga powrotna czeka na twoje kliknięcie,
zamiast nawigować za ciebie, więc uczy ścieżki przez aplikację, zamiast ją
odgrywać. Pominięcie wraca do buildera samo.

MCP rozwidla się tak samo, ale zostaje w builderze. Serwer podłącza się
wbudowanym dialogiem od razu na miejscu w Toolboksie, więc „tak" wskazuje na ten
przycisk, a przepływ podejmuje pracę w momencie, w którym połączenie wyląduje —
bez wycieczki na inną stronę i bez powrotu.

**Nie kończy się na Publish.** Gdy Publish wyląduje, przepływ przenosi cię do
czatu, każe wybrać agenta, którego właśnie zbudowałeś, i zamyka się dopiero,
kiedy wyślesz mu pierwszą wiadomość. Pierwszy agent, którego nikt nie uruchomił,
to wycieczka, która zatrzymała się o krok przed sednem.

**Każda inna sekcja ma własny.** Odmowa nie prowadzi nikogo, a oferta wraca na
końcu przewodnika **?** w sekcji Agents. Przewodnik **?** każdej innej sekcji
kończy się tak samo, proponując utworzenie zasobu tej sekcji — skilla, bazy
wiedzy, połączenia MCP, organizacji, rutyny.

Dwa z nich mają celowo inny kształt:

- **Routines** kończy się *za* własnym tworzeniem. Harmonogram, który siedzi
  i czeka na zegar, niczego nie uczy, więc ostatnim przystankiem przewodnika jest
  **Run now** przy świeżo utworzonym wierszu, a pierwsze odpalenie ląduje w logu
  runów na twoich oczach.
- **Chat** proponuje prowadzone przejście przez samą powierzchnię czatu:
  rozpoczęcie rozmowy, przełączenie tego, który agent odpowiada, zmianę modelu
  albo wysiłku myślowego dla pojedynczego czatu. Czat może rozmawiać tylko
  z *opublikowanym* agentem, więc gdy nie ma żadnego, otwiera się propozycją
  zbudowania pierwszego i przekazuje od razu do przepływu agenta. Dalej nie tworzy
  niczego, więc posuwa się naprzód przyciskiem Next.

!!! tip "Odtwórz ? dashboardu raz"

    Jego przystanek o personalizacji tłumaczy cały edytor: dodawanie kart
    z katalogu (tej samej karty więcej niż raz, jeśli chcesz ją mieć per agent),
    przeciąganie ich między sekcjami, zmianę rozmiaru, ukrywanie, zmianę nazw
    i kolorów samych sekcji, nazwane układy oraz reset.

    Każdy układ jest per osoba, więc eksperymentowanie nie rusza niczyjej innej
    strony.

## Dalej { #next }

<div class="grid cards" markdown>

- :material-lightbulb:{ .lg .middle } **[Pojęcia](concepts.md)**

    Spec, wersja, ekspozycja, wyzwalacz, run — pięć rzeczowników, których
    właśnie użyłeś.

- :material-shield-check:{ .lg .middle } **[Governance](governance.md)**

    Budżety, zatwierdzenia, alerty, audyt.

- :material-account-key:{ .lg .middle } **[Uprawnienia](permissions.md)**

    Kto co może i wobec których wierszy.

</div>
