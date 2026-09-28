---
source_sha: "d1599ab21791"
title: "Odpowiedz na pytanie z handbooka w Slacku"
description: "Umieść agenta z dokumentem na testowym kanale Slacka, zadaj te same pytania i sprawdź, do kogo należał każdy run."
---

# Odpowiedz na pytanie z handbooka w Slacku { #answer-a-handbook-question-in-slack }

Umieść [agenta z dokumentem](first-document-agent.md) na testowym kanale Slacka i zadaj mu pytania, które już sprawdziłeś w konsoli. Szukasz tej samej, sprawdzonej odpowiedzi w wątku Slacka oraz runa w Activity zapisanego na powierzchni `slack`. To instrukcja wykonania, nie raport z pomiaru wdrożenia.

## Zanim zaczniesz { #before-you-start }

- **Agent z dokumentem przechodzi w konsoli swoje trzy sprawdzenia.** Nie zmieniaj jego handbooka, modelu ani opublikowanej wersji, dopóki dodajesz Slacka. Jeśli naraz zmienią się model, dokumenty i kanał, inna odpowiedź nie powie Ci, która zmiana ją spowodowała.
- **Workspace Slacka, w którym możesz instalować aplikacje.** Użyj testowego workspace'u albo testowego kanału. Handbook jest syntetyczny, więc nic prywatnego nie jest zagrożone, dopóki poznajesz tę ścieżkę.
- **Uprawnienie `channels:manage`** do zarejestrowania bota oraz `agents:publish` na agencie, z Twojej roli albo z grantu, żeby go powiązać.

Poniżej transportem jest Socket Mode. To bot otwiera połączenie do Slacka, więc nic nie musi być osiągalne z internetu. Dlatego to właściwy wybór na laptopie. Alternatywę w postaci Events API opisuje strona [Kanały](../channels.md#slack).

## Utwórz aplikację Slacka { #create-the-slack-app }

1. W **api.slack.com/apps → Create New App → From an app manifest** wybierz testowy workspace i wklej manifest z [sekcji Slack na stronie Kanały](../channels.md#slack). Zmień `name` i `display_name` na nazwę, pod którą ma występować bot. Przed instalacją przejrzyj scope'y: [tabela scope'ów](../channels.md#scopes-and-events) mówi, które wywołanie potrzebuje którego.
2. W **Basic Information → App-Level Tokens → Generate** dodaj scope `connections:write` i skopiuj token `xapp-`.
3. W **Install App → Install to Workspace → Allow** zainstaluj aplikację i skopiuj **Bot User OAuth Token** (`xoxb-`).

!!! warning "Nie włączaj rotacji tokenów"

    Przy włączonej rotacji token `xoxb-` wygasa i bot przestaje odpowiadać. Platforma przechowuje statyczny token bota i go nie odświeża.

Nie pokazuj żadnego z tokenów na zrzutach ekranu, nagraniach ani w zgłoszeniach pomocy.

## Zarejestruj bota i powiąż agenta { #register-the-bot-and-bind-the-agent }

1. W **Channels → Add channel** wybierz Slack. Wklej token bota w **Bot token**, a token `xapp-` w **App-level token**. Oba są zapieczętowane w [vault](../secrets.md) i nigdy więcej nie zostaną pokazane.
2. Nowy wiersz mówi *No agent bound - this bot answers nothing*. Tak ma być aż do następnego kroku.
3. Otwórz agenta z dokumentem w Builderze, przejdź do **Availability** i wybierz bota w **Where this agent is available**. Agent musi mieć opublikowaną wersję.
4. Zostaw wyłączone odczyty kanału. Pytanie z handbooka nie wymaga, żeby agent czytał historię kanału ani listę jego członków, a każdy taki odczyt to [osobna decyzja](../reference/capabilities.md#chat-channel-lookup).
5. W Slacku utwórz testowy kanał i zaproś bota poleceniem `/invite @your-bot`.

## Zadaj pytania { #ask-the-questions }

Zadaj każde pytanie w Slacku i porównaj odpowiedź ze źródłem.

| Gdzie i co | Kryterium |
| --- | --- |
| Na kanale: `@your-bot Who handles an equipment request?` | Wskazuje office managera i mówi, że skorzystał z handbooka |
| Odpowiedź w tym wątku: `@your-bot Which details should I include?` | Item, reason i delivery location, w tym samym wątku |
| Nowa wiadomość na kanale: `@your-bot How much can I spend?` | Mówi, że handbook nie określa limitu |
| Wiadomość na kanale bez wzmianki o bocie | Brak odpowiedzi |
| Wiadomość bezpośrednia do bota, zanim połączysz konto | Prosi o połączenie konta i wysyła link |

Wątek to jedna rozmowa. Odpowiedź w wątku ma pierwszą odpowiedź w kontekście. Na kanale wspominaj bota w każdej odpowiedzi: wiadomość w wątku, która go nie wymienia, nie jest skierowana do niego, nawet w wątku, który sam otworzył. Nowa wiadomość na kanale zaczyna nową rozmowę bez pamięci poprzedniej. Zobacz [jedna rozmowa na wątek](../channels.md#one-conversation-per-thread).

Wzmianka musi być taką, którą Slack rozpoznał, czyli wybraną z autouzupełniania. Uchwyt wpisany jako zwykły tekst nie jest wzmianką i bot milczy.

## Sprawdź, do kogo należał każdy run { #check-who-each-run-belonged-to }

Otwórz **Activity** i znajdź runy. Każdy zapisuje powierzchnię `slack`, wersję agenta, która odpowiedziała, i konto Slacka, które napisało wiadomość. Otwórz run i sprawdź, czy wywołał `search_documents` i czy pobrany fragment to ten, na którym opiera się odpowiedź.

Nadawca, który nie połączył konta Slacka z członkiem organizacji, i tak dostaje odpowiedź na kanale. Taki run przyjmuje rolę osoby, która powiązała agenta z botem. Każdy, kto może pisać na kanale, może więc przez agenta wydawać budżet organizacji i czytać zawartość powiązanych kolekcji.

!!! info "Członkowie kanału są odbiorcami dokumentu"

    Agent przeszukuje kolekcje powiązane w jego specu, niezależnie od tego, kto pyta. Własne uprawnienia użytkownika Slacka w AgenticOS tego nie zawężają. Dobieraj kanał i kolekcję razem i nigdy nie testuj reguł dostępu na prywatnym dokumencie.

Żeby połączyć własne konto, wyślij botowi wiadomość bezpośrednią. Odpowie linkiem. Otwórz go w przeglądarce, w której jesteś zalogowany do konsoli, i potwierdź **Connect this account**. Od tej chwili Twoje wiadomości wykonują się jako Ty, z Twoimi uprawnieniami i Twoim nazwiskiem w dzienniku audytu. Budżety pozostają budżetami agenta i organizacji: połączenie konta nie daje Ci osobnego limitu wydatków. Link jest ważny piętnaście minut i działa raz. Połączone konta są wymienione w **Settings → Profile → Chat accounts**.

Żeby odrzucać niepołączonych nadawców także na kanałach, ustaw `require_link` w polityce dostępu bota. Konsola nie ma do tego kontrolki: wyślij całą politykę na `PATCH /api/v1/channels/bots/{bot_id}` jako `{"access_policy": {"require_link": true}}`, z uprawnieniem `channels:manage`. Żądanie zastępuje zapisaną politykę, więc powtórz każde pole zmienione wcześniej, na przykład `mode` albo `rate_limit_rpm`. Reguły i limit liczby żądań na konto opisuje sekcja [łączenie kont i gdzie jest wymagane](../channels.md#what-every-channel-shares).

## Gdy nie odpowiada { #when-it-does-not-answer }

Przejdź ścieżkę w tej kolejności:

1. Wiersz bota w **Channels** pokazuje **Not connected**. Plakietka podaje przyczynę, często błędny lub brakujący token `xapp-`.
2. Wiersz nadal mówi, że żaden agent nie jest powiązany, albo agent nie ma opublikowanej wersji.
3. Brakuje scope'u albo eventu. Dodanie go oznacza ponowną instalację aplikacji, która wydaje nowy token `xoxb-`. Wklej nowy token w ustawieniach bota, inaczej bot zachowa dotychczasowy dostęp.
4. Bota nie ma na kanale albo wiadomość nie zawierała rozpoznanej wzmianki.
5. Wiadomość bezpośrednia z niepołączonego konta jest odrzucana, dopóki go nie połączysz.

Jeśli bot odpowiada, ale odpowiedź jest błędna, ścieżka Slacka działa. Sprawdź wyszukiwanie w Activity i dokumenty kolekcji, zanim zmienisz cokolwiek w Slacku. Strona [Kanały](../channels.md#slack) wymienia, co jest, a co nie jest zgłaszane przy milczącym bocie.

## Zapisz próbę { #record-the-trial }

Trzymaj to razem, żeby inna osoba mogła powtórzyć próbę i porównać wyniki:

- wersję AgenticOS, wersję agenta, profil modelu i kolekcję ze statusem jej dokumentów;
- wklejony manifest Slacka, bez tokenów, oraz transport;
- każde pytanie, odpowiedź tak, jak pojawiła się w Slacku, i odpowiadający jej run w Activity;
- każdy błąd, w tym milczącego bota, i to, co go naprawiło;
- kto zainstalował aplikację, kto powiązał agenta i kto oceniał odpowiedzi.

Człowiek robi tu trzy rzeczy, których żadne ustawienie nie zastąpi: instaluje aplikację, decyduje, który kanał może sięgać do których dokumentów, i ocenia każdą odpowiedź względem źródła. Zrzut ekranu strony Channels wyjaśnia konfigurację. Wynik pokazuje dopiero wątek z pytaniem i odpowiedzią obok siebie.

## Kolejne kroki { #next-steps }

Zanim zastąpisz syntetyczny handbook prawdziwym, zdecyduj, kto powinien mieć dostęp do tego dokumentu, i dobierz do tego kanał. Wskaż, kto aktualizuje dokument, kto zmienia agenta i kto zajmuje się pytaniami, na które handbook nie odpowiada. Te role opisuje strona [Wdrożenie i utrzymanie](../rollout.md).
