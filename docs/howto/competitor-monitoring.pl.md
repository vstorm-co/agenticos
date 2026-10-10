---
source_sha: "eaed0d094904"
title: "Obserwuj strony internetowe pod kątem zmian według harmonogramu"
description: "Pobieraj dwie strony według harmonogramu, porównuj każdą z tym, co zapisano ostatnio, i zgłaszaj tylko to, co się zmieniło."
---

# Obserwuj strony internetowe pod kątem zmian według harmonogramu { #watch-web-pages-for-changes-on-a-schedule }

Zbuduj agenta, który pobiera niewielki zestaw stron, przechowuje krótkie podsumowanie tego, co zobaczył, i przy następnym runie mówi, co się zmieniło - albo że nic się nie zmieniło. Przykład obserwuje dwie strony, których nie kontrolujesz, ale które zmieniają się rzadko: stronę wydań GitHuba pewnego projektu oraz `example.com`. To instrukcja wykonania, z dwoma zapisanymi odpaleniami jako punktem odniesienia.

Dwa odpalenia dowodzą dwóch różnych rzeczy. **Run now** dowodzi, że logika porównania działa. Nie dowodzi, że *prawdziwa* zmiana zostanie kiedykolwiek wychwycona - pokazuje to dopiero odpalenie, które nastąpi już po faktycznej zmianie strony, a tej strony nie da się zapisać na żądanie.

## Czego potrzebujesz { #what-you-need }

- [Działająca instalacja](../install.md) z profilem modelu.
- Żadnej kolekcji wiedzy, żadnego połączenia MCP i żadnego połączenia sandboksa: workspace, którego używa ten przepis, niczego z tego nie potrzebuje. Zobacz niżej.

## Dlaczego nie pliki pamięci { #why-not-memory-files }

Oczywistą capability dla „zapamiętaj, co widziałem ostatnio” są [pliki pamięci](../reference/capabilities.md#memory-files). Tutaj to nie działa, a powód warto poznać, zanim sięgniesz po nie w harmonogramie.

Odpalenie triggera działa z rolą i uprawnieniami swojego twórcy, ale nie jako on w kwestii pamięci: *odbiorca* runa - kto usłyszy odpowiedź - jest celowo pusty na powierzchni `schedule`, więc nienadzorowany run nie może czytać ani zapisywać osobistych notatek twórcy. `write_memory` i `read_memory` odpowiadają tym samym:

```text
This conversation has no memory. It has no identified person and is not a
group chat, so a note would have to land somewhere other people read. Answer
from what you have rather than saving.
```

Ten sam agent, zapytany o to samo w zwykłym czacie, zapisuje notatkę bez przeszkód - magazyn tam istnieje, bo słucha prawdziwy człowiek. W harmonogramie nikt nie słucha.

## Czego użyć zamiast tego { #what-to-use-instead }

Workspace [sandboksa](../sandbox.md) zakresowany na **conversation** przetrwa każde odpalenie jednego triggera, bo trigger otwiera jedną rozmowę na całe swoje życie i dopisuje do niej każde odpalenie - `conversation_id`, na którym opiera się workspace, nie zależy od tego, kto słucha. Backend `state` nie potrzebuje połączenia sandboksa: to mały magazyn we własnej bazie danych tego wdrożenia, bez powłoki i bez kontenera.

## Zbuduj agenta { #build-the-agent }

1. Utwórz agenta w **Agents → New agent** i wybierz swój profil modelu.
2. W **Toolbox** włącz **Read web pages**. Ogranicz `allowed_domains` do `github.com` i `example.com`, żeby nie dało się poprosić agenta o pobranie czegokolwiek innego.
3. Włącz **Sandbox**. Zostaw backend na **Files** (backend `state` - bez powłoki, bez połączenia sandboksa) i zakres na **This conversation** - domyślne ustawienia to dokładnie to, czego potrzebuje ten przepis.
4. Ustaw budżet i limit kroków na czas próby. Każde zapisane odpalenie kosztowało około 0,07-0,14 USD.
5. Wpisz poniższe instrukcje, a potem **Publish**.

```text
You watch two pages for changes, once per run:
- https://github.com/vstorm-co/agenticos/releases
- https://example.com/

Each run:

1. Fetch both pages with web_fetch.
2. For the GitHub page, keep only the latest (topmost) release: its tag and
   title. For example.com, keep its heading and first paragraph. Ignore
   everything else on each page - star counts, timestamps, navigation.
3. Look for a file named watch-state.txt in your workspace.
4. If it does not exist, write it now with today's two summaries, one line
   per page, and report that you recorded a baseline - not a change.
5. If it exists, read it and compare each page's new summary to the line
   stored for it. Report, page by page, either the old and new value or
   "no change". Then overwrite watch-state.txt with the new summaries.
Never say a page changed unless the two lines you compared actually differ.
```

## Utwórz harmonogram { #create-the-schedule }

Otwórz **Routines → New schedule** albo zakładkę **Availability** agenta, wybierz agenta i ustaw dzienną kadencję. Prompt musi tylko nazwać zadanie:

```text
Run today's page check.
```

## Uruchom { #run-it }

Naciśnij **Run now** na harmonogramie dwa razy, w odstępie kilku minut. Pierwsze odpalenie nie znajduje `watch-state.txt` i zapisuje punkt odniesienia. Drugie odczytuje go z powrotem i porównuje.

!!! warning "Opublikowanie poprawki nie przenosi na nią działającego harmonogramu"

    Publikowanie tworzy nową wersję, ale nie przestawia [środowiska](../environments.md),
    z którego czyta harmonogram, chyba że to środowisko śledzi najnowszą wersję - a
    `production` domyślnie tego nie robi. Jeśli edytujesz agenta po utworzeniu
    triggera, przenieś nową wersję na to środowisko (**Promote v2 to…**,
    z Twoim numerem wersji) przed kolejnym **Run now**,
    albo odpalenie nadal uruchomi wersję, którą właśnie zastąpiłeś.

## Sprawdź wynik { #check-the-result }

| Sprawdzenie | Kryterium |
| --- | --- |
| Pierwsze **Run now** | Zgłasza punkt odniesienia, nie zmianę, i żadna strona nie jest opisana jako różna |
| `watch-state.txt` po pierwszym odpaleniu | Istnieje, z jedną linią na stronę |
| Drugie **Run now** | Odczytuje ten sam plik z powrotem i zgłasza „no change” dla obu stron |
| Strona, którą edytowałeś między dwoma odpaleniami | Zgłasza starą i nową wartość tylko dla tej strony |
| Powierzchnia runa w Activity | `schedule` dla obu odpaleń, ten sam trigger, ta sama rozmowa dziennika runów |
| Run z `web_fetch` skierowanym na trzecią domenę | Odrzucony - `allowed_domains` jej nie obejmuje |

!!! example "Zapisano na v0.0.504, 25 września 2026"

    Model: Claude Sonnet 4.6 przez OpenRouter. Pierwsze **Run now** wywołało
    `web_fetch` na obu stronach, potem `read_file` na `watch-state.txt`, co się
    nie powiodło, bo plik jeszcze nie istniał, a potem `write_file`. Zgłosiło
    najnowsze wydanie strony GitHuba jako `v0.0.504` oraz nagłówek i akapit
    example.com, i powiedziało, że to punkt odniesienia. Koszt: 0,13 USD. Drugie
    **Run now**, około minutę później, odczytało ten sam plik z powrotem,
    dopasowało oba podsumowania i zgłosiło „No change” dla obu stron, a potem
    nadpisało plik tą samą treścią. Koszt: 0,14 USD.

    Pierwsza próba użyła `memory_files` zamiast sandboksa, dokładnie tak, jak
    ostrzega ta strona: oba odpalenia wywołały `read_memory` i dostały powyższą
    odmowę „no memory”, a agent poprawnie powiedział osobie czytającej raport,
    że nie może zapisać punktu odniesienia - zamiast twierdzić, że to zrobił.

## Gdy coś pójdzie nie tak { #when-it-goes-wrong }

- **Każde odpalenie mówi „no prior state”, nigdy porównania.** Workspace się nie utrzymuje. Sprawdź, czy zakres to **This conversation**, a nie **Nobody** - zakres `run` otwiera przy każdym odpaleniu świeży, pusty workspace.
- **W transkrypcie w ogóle pojawia się `read_memory` albo `write_memory`.** Pliki pamięci są nadal przypisane. Usuń je; nie mogą wykonać tego zadania w harmonogramie.
- **Prawdziwa zmiana strony nie jest zgłaszana.** Wychwytuje ją dopiero odpalenie, które nastąpi po zmianie i po odpaleniu, które zapisało wcześniejszy stan. Sprawdź w Activity oba odpalenia po obu stronach zmiany, nie tylko ostatnie.
- **Każde odpalenie zgłasza zmianę, nawet gdy nic się nie ruszyło.** Podsumowanie jest zbyt szerokie - surowe pobranie strony obejmuje liczby gwiazdek, względne znaczniki czasu albo zmieniający się nonce, który różni się przy każdym pobraniu. Zawęź w instrukcjach to, co ma znaczenie, do jednego istotnego faktu.
- **Odpalenie nadal zachowuje się jak stara wersja po ponownym opublikowaniu.** Zobacz ostrzeżenie o środowisku powyżej.

## Zapisz próbę { #record-the-trial }

Zachowaj oba adresy URL stron, instrukcje, wersję agenta, `watch-state.txt` po każdym odpaleniu i każdy run w Activity z jego powierzchnią i kosztem. Człowiek nadal decyduje, co liczy się jako zmiana warta działania, i obserwuje pierwsze odpalenie, które nastąpi po prawdziwej edycji, żeby potwierdzić, że porównanie ją wychwytuje - para `Run now` dowodzi tylko logiki, nigdy tego odpalenia.
