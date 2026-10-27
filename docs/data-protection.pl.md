---
source_sha: "cf0f92f2d75a"
---

# Ochrona danych { #data-protection }

Gdzie we wdrożeniu mieszkają dane osobowe, co je opuszcza i przy jakiej
konfiguracji, które kontrole istnieją w kodzie i mają za sobą test, a które są
wciąż otwartymi zgłoszeniami. Napisane dla osoby, która odpowiada na przegląd
ochrony danych jednego wdrożenia — inspektora ochrony danych, oficera
bezpieczeństwa, operatora — i uczciwe co do różnicy między tym, co
oprogramowanie potrafi, a tym, co wdrożenie faktycznie postanowiło.

!!! warning "Strona to nie zgodność"

    Nic tutaj nie jest dowodem, że wdrożenie jest zgodne z RODO. Kod da się
    wdrożyć wewnątrz zgodnego środowiska; czy dane wdrożenie *jest* zgodne,
    zależy od skonfigurowanych providerów, ustalonej retencji, podpisanych umów
    i operatora, który je prowadzi. Każdy taki warunek jest poniżej nazwany jako
    coś do zdobycia i zweryfikowania, nigdy jako coś założonego.

## Domyślnie nic nie wychodzi { #nothing-leaves-by-default }

Świeże wdrożenie trzyma wszystko we własnym PostgreSQL-u i na własnym dysku,
i nigdzie nic nie wysyła. Każdy skok na zewnątrz to wiersz albo ustawienie,
które ktoś dodał później: profil modelu wskazujący providera, kolekcja
wybierająca parser, metoda wyszukiwania w specu, token Logfire, host mem0,
serwer MCP, bot kanału. Usuń wiersz i skok znika.

Wdrożenie, które nie chce **żadnej trzeciej strony w łańcuchu**, konfiguruje się
tak i oprogramowanie współpracuje:

| Zagadnienie | Lokalna odpowiedź |
|---|---|
| Model czatowy | Profil `ollama` albo `litellm` — bezkluczowy, wskazujący endpoint, który hostujesz. Każdy z 28 providerów z `base_url` przyjmie też Twój gateway |
| Parsowanie dokumentów | `pymupdf`, wartość domyślna, działa w workerze. OCR LiteParse też działa w workerze albo na serwerze OCR zarejestrowanym jako usługa lokalna. LlamaParse to wybór per kolekcja, wymagający klucza w vault; bez niego nic nie jest parsowane poza wdrożeniem |
| Embeddingi | Ollama, którą hostujesz, zarejestrowana jako usługa lokalna w Knowledge → Integrations i wybrana per kolekcja jako provider `ollama`. Bezkluczowa i jedyny provider, którego może użyć kolekcja app-scoped |
| Trace'y | Zostaw `LOGFIRE_TOKEN` nieustawiony i nie wiąż żadnego tokenu `observability` ze specem ani ze środowiskiem. Runy dalej zapisują id trace'u lokalnie |
| Wyszukiwanie, przeglądanie, pamięć, narzędzia | Nie wiąż sekretu `search`, żadnej capability `web_fetch`, `browser_use` ani `memory_mem0`, żadnego połączenia MCP. Przeglądarka może zostać, gdy każda strona, którą może otworzyć, jest na `allowed_domains`, a jej kroki idą do modelu, który sam hostujesz |
| Poczta | Twój własny relay SMTP |
| Mowa, obrazy i wideo | Dla zamiany mowy na tekst żaden provider: zostaw dyktowanie na `off` albo `browser` i wyłączone boty kanałów, bo własnego serwera zamiany mowy na tekst nie da się jeszcze wskazać (planowany kolejny krok). Dla syntezy mowy i wideo brak capability `text_to_speech` ani `video_generation`. Dla obrazów profil u providera, którego hostujesz, albo brak takich profili |

Embeddingi w to wliczone: katalog wymienia OpenRouter i OpenAI, do których
kolekcja sięga kluczem z vaultu, oraz `ollama`, do której kolekcja sięga przez
usługę lokalną — wiersz wskazujący serwer prowadzony przez organizację albo
wdrożenie. Kolekcja na `ollama` wysyła swoje chunki i zapytania wyłącznie na ten
host i nikomu nie płaci. Wdrożenie, które musi trzymać dokumenty na własnym
sprzęcie, tam tworzy każdą kolekcję.

## Kto za co odpowiada { #who-is-responsible-for-what }

| Strona | Rola | Co to tutaj znaczy |
|---|---|---|
| Organizacja, która to wdraża (miasto, firma) | **Administrator danych** | Decyduje o celach, retencji, o tym, do których providerów agent może sięgać, i podpisuje z nimi umowy |
| Vstorm jako autor oprogramowania | **Żadna z tych ról**, dla wdrożenia self-hosted | Kod działa na Twojej infrastrukturze i nic nie dzwoni do domu. Vstorm nigdy nie widzi Twoich danych |
| Vstorm, jeśli prowadzi wdrożenie za Ciebie | **Podmiot przetwarzający** | Umowa powierzenia przetwarzania to kontrakt między nami, a nie ustawienie. Musi istnieć przed opublikowaniem pierwszego agenta |
| Provider modelu, embeddingów, parsowania, wyszukiwania albo obserwowalności | **Podprzetwarzający**, wybrany konfiguracją | Platforma zapisuje, *którego* providera i *który* endpoint używa każdy agent. Ich lokalizacja, retencja i warunki treningu są ich, i weryfikuje się je per wdrożenie |

Platforma niczego nie trenuje ani nie dostraja. Wysyła prompty, dokumenty
i wyniki narzędzi do providerów, których wdrożenie skonfigurowało, i zapisuje
to, co wraca. To, czy provider używa ruchu API do treningu, jest własnością
konta i warunków providera, a lista kontrolna na końcu prosi o oświadczenie,
zamiast je zakładać.

## Gdzie mieszkają dane osobowe { #where-personal-data-lives }

Wszystko poniżej jest we własnym PostgreSQL-u wdrożenia, na jego własnym dysku
albo w usłudze, którą wdrożenie wybrało. Każda tabela należąca do organizacji
niesie `organization_id`; wiersz podrzędny — wiadomość, załącznik, ocena — jest
ograniczany przez konwersację albo użytkownika, przy którym wisi, a odczyt idzie
przez sprawdzenie rodzica.

### Baza danych { #the-database }

Łączny limit jest sprawdzany w savepoincie zmiany, pod blokadą organizacji, przed commitem. Przekroczenie cofa rekord i wszystkie zachowane kopie, także dla wiersza importu; pozostałe wiersze są raportowane jako odrzucone. Ponowienie z potwierdzenia, zapis bez zmian, odczyt i usuwanie nadal działają po obniżeniu limitu. Retencja zwalnia usuwane bajty. Bajty danych JSONB PostgreSQL na organizację łącznie dla rekordów, historii, potwierdzeń i outboxa; narzut tabel i indeksów jest osobny.

| Magazyn | Trzyma | Dane osobowe w nim | Cel |
|---|---|---|---|
| `users`, `sessions`, `organization_members` | Konta i logowania | E-mail, imię, awatar, zahaszowane hasło albo id konta Google, hash refresh tokenu, adres IP i user agent na sesję; to, co osoba powiedziała agentom o sobie - język konsoli, strefa czasowa, rola, czym się zajmuje, godziny pracy - oraz pierwsze wiadomości napisane dla jej pustego czatu | Uwierzytelnianie i autoryzacja; to, co każdy agent słyszy o osobie |
| `browser_sign_ins` | Zapisane logowania osoby do stron, dla przeglądarki | Strona, organizacja, kiedy ostatnio użyte, i sama sesja (ciasteczka i `localStorage` strony) zapieczętowana w vaulcie w zakresie tej osoby | Kolejne przeglądanie w jej imieniu zaczyna się już zalogowane. Eksport danych osobowych podaje strony, nigdy sesji |
| `conversations`, `messages`, `tool_calls` | Każdy czat na każdej powierzchni | Tekst, który ludzie napisali, odpowiedzi i rozumowanie modelu, argumenty i wyniki narzędzi, kroczące podsumowanie długich wątków | Podstawowa funkcja produktu; historia, do której człowiek wraca |
| `voice_calls` | Każde połączenie [rozmowy głosowej](voice.md) | Id użytkownika rozmówcy (brak dla odwiedzającego), agent, run, konwersacja i embed, do których należała, provider i model, id rozmowy u providera, id klucza z vaultu, którym była prowadzona, worker, który ją trzyma, jej heartbeat, czasy startu, końca i rozłączenia, jej koszt, sekundy i liczba trafień guardraili. **Bez dźwięku i bez transkrypcji** - słowa rozmowy to zwykłe wiersze w `messages`, każdy oznaczony `turn_id` i, gdy rozmówca wszedł agentowi w słowo, `interrupted` | Rozłączanie rozmowy, której proces umarł, i liczenie miesięcznych minut rozmów organizacji |
| `chat_files` | Załączniki do wiadomości | Nazwa pliku, typ, rozmiar, wyciągnięty tekst (`parsed_content`) i ścieżka bajtów na dysku | Odpowiadanie o pliku |
| `generated_media` | Jeden wiersz na każdy obraz, klip mowy lub wideo wygenerowane przez agenta | Organizacja, konwersacja, w której powstał, jeśli run ją miał, nazwa pliku, ścieżka w magazynie i rozmiar - **nie jego treść**, która jest plikiem pod `MEDIA_DIR` | Liczenie wygenerowanych mediów każdej organizacji względem jej limitu oraz usuwanie ich razem z konwersacją albo po okresie retencji |
| `context_files` | Stała wiedza, którą builder napisał dla agentów | Cokolwiek autor tam umieścił — i trafia to do promptu dosłownie. Zobacz [Pliki kontekstu](context.md) | Instrukcje i fakty, które agent zawsze ma znać |
| `virtual_table_records`, `virtual_table_record_history`, `virtual_table_receipts`, `virtual_table_outbox` | Wiersze [Virtual Table](virtual-tables.md) i ślad każdej zmiany w nich | Cokolwiek organizacja umieściła w komórkach, w tym potencjalnie dane osobowe. Bieżące wartości (records); cały rekord przy create i delete, a przy update tylko komórki, które się zmieniły (history); cały rekord tak, jak zwrócił go zapis z kluczem (receipts); id i external id każdego utworzonego rekordu (outbox, bez wartości). Usunięcie rekordu usuwa tylko bieżący wiersz: history i receipts zachowują wartości, dopóki nie usunie ich codzienny sweep retencji: receipts po 24 godzinach, wysłane wiersze outbox po 3 dniach, a history po 365 dniach, wszystko jako ustawienia wdrożenia. Usunięcie konta usuwa jego receipts i czyści je jako autora w history; usunięcie organizacji usuwa wszystkie cztery | Typowane rekordy dla agentów i workflow, bezpieczne ponawianie zapisu i przekazanie utworzonego rekordu |
| `virtual_table_triggers`, `virtual_table_trigger_revisions`, `table_trigger_admissions` | [Wyzwalacze](virtual-tables.md#triggers) tabeli, każda konfiguracja, jaką miały, i to, co każdy zdecydował o utworzonym rekordzie | Członek, jako który działa wyzwalacz; wartości jego filtrów i klucze mapowania, które mogą zawierać dane osobowe, jeśli builder jakieś wpisał (filtr po adresie e-mail). Decyzja trzyma status, ogólny powód i run, który uruchomiła, nigdy wartości rekordu. Żadna klasa retencji ich nie usuwa: znikają razem z tabelą i wyzwalaczem, a usunięcie konta czyści je jako członka, po czym wyzwalacz niczego nie uruchamia | Uruchamianie workflow, gdy przybędzie rekord |
| `artifacts`, `artifact_versions` i ich pliki | Strony opublikowane przez agentów — raporty, dashboardy | Cokolwiek strona pokazuje, a run zbudował ją z tego, co mógł przeczytać — albo, dla strony powiązanej z danymi tabel, jej zapytania strony (tabela, filtry, sortowanie, limit i kolumny, każde rozwiązane do identyfikatorów), przy czym same rekordy są czytane w chwili oglądania, z dostępem właściciela strony, i nigdy nie są przechowywane w stronie; dla każdej wersji — kto ją opublikował i zgoda właściciela na udostępnienie jej danych (odcisk zapytań, członkostwo właściciela i kiedy) oraz zgoda strony na dane publiczne (kto ją potwierdził, członkostwo właściciela, kiedy); wiersz organizacji trzyma wyłącznik `public_live_data`; właściciel, run, który zapisał każdą wersję, i — gdy jest włączony — klucz publicznego linku, jego ustawienia (hasło jako hash bcrypt) i to, ile razy go otwarto — liczba i czas, nic o odwiedzającym. Zobacz [Aplikacje](artifacts.md) | Udostępnienie wyniku pod stałym linkiem |
| `agent_memory_files` | Notatki, które agent napisał o osobie albo o czacie grupowym | Cokolwiek agent uznał za warte zapamiętania, kluczowane przez `person:<user_id>` albo pokój czatu | Ciągłość między rozmowami |
| `rag_documents`, `knowledge_bases` i jedna tabela wektorowa na kolekcję | Wgrane i zsynchronizowane dokumenty, ich chunki i embeddingi | Tekst dokumentu i jego wektory, oryginalna ścieżka pliku w źródle | Wyszukiwanie |
| `agent_runs`, `tool_approvals`, `run_manifests` | Ile każdy run kosztował i co zrobił | Prompt systemowy i ostatnie żądanie podane modelowi, argumenty narzędzi czekające na zatwierdzenie, osoba decydująca i jej notatka. Obok argumentów `tool_approvals.context` przechowuje nazwy, które oznaczają id zaparkowanego wywołania - nazwę widoku i tabeli, nigdy zawartość rekordu - ustalone jako osoba runa w chwili parkowania wywołania. Zostają z wierszem zatwierdzenia także po zmianie nazwy albo zniknięciu widoku czy tabeli i czyta je każdy, kto może rozstrzygać zatwierdzenia, niezależnie od własnego dostępu do tej tabeli | Budżety, zatwierdzenia, historia runów |
| `workflow_runs`, `node_runs`, `node_attempts`, `workflow_events`, `dispatch_outbox`, `resource_refs` | Każdy run workflowu, próby każdego węzła i strumień zdarzeń runa | Konto, w imieniu którego działa run, a dla runa uruchomionego z [akcji strony](artifacts.md#actions) także strona i numer jej wersji; wynik każdej próby, zawierający to, co węzeł wytworzył z otrzymanych danych; kod i komunikat błędu; referencje do plików i tabel, które powiązał graf. Historia workflow i pliki podlegają `run_retention_days`. Czyszczenie zachowuje źródła aktywnych ponowień, podprocesy potrzebne działającym wywołującym i producentów plików używanych przez zachowane przebiegi. Jawne usunięcie workflow nadal może usunąć jego historię. | Doprowadzenie workflowu do końca mimo restartów i pokazanie jego historii |
| `workflow_approvals` | Prośby, które zgłosiły kroki [`human.approval`](reference/workflow-nodes.md#human-approval) workflow | Tytuł i szczegóły kroku, powiązana z nim propozycja i zatwierdzony tekst końcowy (treść, jawnym tekstem), id wskazanych zatwierdzających, osoba decydująca i jej notatka oraz to, jak bardzo zatwierdzający zmienił propozycję (`edit_ratio`, liczba od 0 do 1, nigdy tekst). Usuwane razem z runem | Pozwalają osobie zatwierdzić, odrzucić albo poprawić to, co workflow ma zrobić |
| `workflow_files` | Pliki zapisane przez kroki runa workflow - pobrane pliki, zapisane pliki, wyrenderowane strony, przekształcone obrazy, wynik skryptu oraz załączniki wiadomości Gmail lub Outlook, która uruchomiła run | Wszystko, co zawiera plik, co może być danymi osobowymi, oraz jego nazwa. Bajty są w `MEDIA_DIR` albo w magazynie obiektów. Historia workflow i pliki podlegają `run_retention_days`. Czyszczenie zachowuje źródła aktywnych ponowień, podprocesy potrzebne działającym wywołującym i producentów plików używanych przez zachowane przebiegi. Jawne usunięcie workflow nadal może usunąć jego historię. | Przekazywanie plików między krokami i pobieranie ich z runa |
| `workflow_exposures`, `workflow_webhook_deliveries` | Webhooki i harmonogramy workflow oraz każde dostarczenie webhooka, które przyjął | Członek, jako który każdy działa, wejście harmonogramu, signing secret webhooka zapieczętowany w sejfie oraz id każdego dostarczenia obok runa, który uruchomiło. Znikają razem z workflow i organizacją, a członek jest czyszczony przy usunięciu konta | Uruchamianie workflow spoza konsoli dokładnie raz na dostarczenie |
| `agent_triggers` | Runy zaplanowane i wyzwalane zdarzeniem | Prompt oraz konfiguracja i filtr źródła zdarzeń | Uruchamianie agenta bez człowieka |
| `app_admin_audit_logs` | Kto zmienił dostęp albo wydał pieniądze — ślad organizacji i ślad administratora wdrożenia dzielą jedną tabelę | Aktor, podszywający się, adres IP, akcja i mapa `details`. Mapa przeważnie nazywa pola, ale niektóre wpisy trzymają wartości: e-mail konta, pod które się podszyto, e-mail konta usuniętego przez administratora, notatka publikacji | Rozliczalność. Zobacz [Nadzór](governance.md#audit) |
| `notifications`, `notification_deliveries` | Każde powiadomienie zaadresowane do kogoś oraz jego dostarczenie mailem. Wiersz powstaje nawet wtedy, gdy odbiorca wyłączył dla tego zdarzenia wszystkie kanały — to on nie pozwala zapisać tego samego wystąpienia dwa razy — i po prostu nigdy nie jest pokazywany ani wysyłany; warunkowy jest tylko wiersz dostawy | Odbiorca, wyrenderowane wcześniej podsumowanie (nigdy surowy komentarz albo wartość sekretu) oraz otypowane zmienne, z których e-mail się odtwarza; wiersz dostawy dodaje swój kanał, status, liczbę prób i oczyszczony powód niepowodzenia — nigdy tekst błędu od providera | Alerty, które ktoś czyta raz, bez asysty. Zobacz [Nadzór](governance.md#alerts) |
| `notification_preferences`, `announcements` | Przełączniki kanału per zdarzenie oraz własne ogłoszenia administratora aplikacji | Id użytkownika na przełącznik; nadawca ogłoszenia, jego treść oraz organizacje i rola, do których było zaadresowane — nigdy rozwiązana lista odbiorców, którą można odtworzyć z `notifications` tylko dopóki ten wiersz nie wypadnie w ramach [zamiatania retencji powiadomień](governance.md#alerts) — po czym wpis audytowy zachowuje tylko liczbę, nigdy odbiorców | Rezygnacja z powiadomień i własny zapis autora |
| `embed_visitors`, `channel_identities`, `channel_sessions` | Obcy na hostowanej stronie oraz ludzie na Slacku, Teams, Telegramie albo Mattermoście | Losowy klucz odwiedzającego; id użytkownika platformy, nazwa użytkownika i nazwa wyświetlana; id czatu | Wznowienie właściwego wątku |
| `message_ratings` | Kciuki i komentarze pod odpowiedziami | Oceniający i jego komentarz | Przegląd jakości |
| `suggestions` | Co [praca z własnej inicjatywy](governance.md#proactive-work) zaproponowała osobie i czy to przyjęła | Osoba, tytuł i linijka opisu wzięte z jej ostatnich próśb, prompt rutyny albo profil, który by ustawiła, i klucz, który nie pozwala zaproponować ponownie czegoś odrzuconego | Propozycje, o których osoba decyduje |
| `watches` | Co osoba kazała [pracy z własnej inicjatywy](governance.md#proactive-work) obserwować na swoich połączeniach | Osoba, które z jej połączeń, czego szukać i co pomijać jej własnymi słowami, jak często i kiedy ostatnio sprawdzono | Obserwacje, które osoba ustawia |
| `ml_service_calls` | Każde wywołanie [usług ML](ml-services.md) i każda transkrypcja: dyktowanie, wiadomość głosowa z kanału, API, dyktowanie odwiedzającego na hostowanej stronie albo w widgecie | Organizacja, kto poprosił, która usługa, liczby bajtów i jednostek, czas trwania i sposób zakończenia; przy transkrypcji także provider i model, identyfikator klucza z vaultu, z którym ją wysłano, skąd przyszła, agent i bot kanału, dla których była, oraz długość nagrania. Wiersz wiadomości głosowej z kanału wskazuje osobę, z którą powiązane jest konto nadawcy, a przy niepowiązanym nadawcy nikogo. Wiersz odwiedzającego nie wskazuje nikogo - ani odwiedzającego, który nie ma konta, ani tego, kto opublikował stronę. Usunięcie osoby, agenta, bota albo klucza czyści powiązanie i zostawia wiersz - **nic z tego, co wysłano, i nic z tego, co wróciło** | Raportowanie zużycia i wgląd operatora w integrację, która się psuje |
| `agent_workspaces`, `sandbox_operations` | Pliki, na których pracował agent, i log tego, co uruchomił | Dla backendu `state` same pliki, jako JSON; dla kontenera id sesji oraz każda komenda, cel i podsumowanie wyniku | Sandbox. Zobacz [Sandbox](sandbox.md#what-was-done-in-one-and-where-that-record-lives) |
| `organization_secrets`, `model_profiles`, `mcp_connections`, `channel_bots` | Poświadczenia i to, gdzie wskazują | Wyłącznie zapieczętowany szyfrogram, z podpowiedzią; provider, model i `base_url` jawnie | Sięganie do providerów. Zobacz [Sekrety](secrets.md) |

`workflow_node_spend` zachowuje bezpośrednie opłaty za decyzje i embeddingi po usunięciu historii: organizację, UUID próby, koszt, znacznik częściowego kosztu i daty. Nie zawiera promptów, wyników, plików ani tożsamości użytkownika. Opłaty agentów pozostają w `agent_runs` i nie są liczone podwójnie. Nigdy niezapisanych kosztów historycznych nie można odtworzyć.

`messages.search_vector` to indeks pełnotekstowy nad tą samą treścią,
a `conversations.summary_messages` to jej kompresja napisana przez model. Oba są
kopiami czatu i idą razem z nim.

### Wygenerowane media { #generated-media }

Obraz, klip mowy albo wideo wygenerowane przez agenta to plik pod
`generated_<org>/` i nazywający go wiersz `generated_media`. Wiersz zapisuje
organizację, konwersację, jeśli run ją miał, oraz rozmiar - więc suma organizacji
jest ograniczona przez `GENERATED_MEDIA_QUOTA_MB` (5120), sprawdzane przed każdym
płatnym wywołaniem generowania. Liczy się każdy plik, także utworzony bez
konwersacji: z podglądu albo przebiegu testowego, z wtrącenia `/btw` w kanale, z
runu API, który nie wskazuje konwersacji, albo plik, którego konwersację usunęła
ścieżka, która go zostawiła.

Plik jest usuwany razem ze swoją konwersacją, razem z kontem, do którego ta
konwersacja należała, przez codzienne zadanie `sweep-generated-media`, gdy jest
starszy niż `GENERATED_MEDIA_RETENTION_DAYS` (90), nawet jeśli konwersacja wciąż
istnieje, oraz po prefiksie razem ze swoją organizacją. 0 wyłącza każde z tych
ograniczeń. Pliku bez konwersacji żaden członek nie może usunąć, żeby zwolnić
miejsce, więc to samo zadanie usuwa go po 7 dniach, bez względu na
`GENERATED_MEDIA_RETENTION_DAYS`, także przy 0. Link do niego - w odpowiedzi w
kanale albo w odpowiedzi API - przestaje wtedy działać.

Usunięcie konwersacji, konta albo organizacji usuwa wiersze we własnej
transakcji i w tej samej transakcji kolejkuje odpięcie bajtów jako zadanie w
tle, więc bajty odchodzą tylko wtedy, gdy odchodzą wiersze, a restart po commicie
nie gubi odpięcia. To zadanie ponawia prefiks, którego magazyn nie usunie w
całości - prefiks organizacji - oraz pojedynczy plik usuniętej konwersacji albo
konta, którego magazyn nie chce usunąć, bo nic innego nie znalazłoby już tych
bajtów. Plik, którego magazyn nie usunie także przy ostatniej próbie zadania,
zostaje bez wiersza pod `generated_<org>/`, dopóki nie odejdzie jego
organizacja, a raport niżej go liczy.

Sweep usuwa najpierw plik, a jego wiersz dopiero wtedy, gdy
pliku już nie ma; plik, którego magazyn nie chce usunąć, zachowuje wiersz, a
następny sweep próbuje ponownie.

Pliki wygenerowane, zanim tabela powstała, nie mają wiersza. Nadal są serwowane,
ale nie wliczają się do limitu, a sweep ich nie widzi: odchodzą razem ze swoją
organizacją albo ręcznie, a raport ochrony danych liczy je wśród plików bez
wiersza.

### Poza bazą danych { #outside-the-database }

| Magazyn | Trzyma | Usuwane, gdy |
|---|---|---|
| `MEDIA_DIR` na hoście API (wolumen `media_data`) | Załączniki czatu pod `<user_id>/`, awatary, logotypy embedów, obrazy, mowę i wideo wygenerowane przez agentów pod `generated_<org>/` oraz tymczasową kopię każdego dokumentu pod `_rag_tmp` na czas parsowania | Dokument zostaje usunięty przez produkt. Bajty załącznika czatu są odpinane po commicie, który usuwa jego konwersację albo jego właściciela. Wygenerowany plik odchodzi razem z konwersacją, w której powstał, po `GENERATED_MEDIA_RETENTION_DAYS` (90) bez względu na los konwersacji - po 7 dniach, gdy nie ma konwersacji - oraz razem ze swoją organizacją; zobacz [Wygenerowane media](#generated-media). Zobacz [Co obejmuje usunięcie](#what-deletion-reaches) |
| `SANDBOXD_WORKSPACE_ROOT` na hoście sandboksa | Pliki każdego workspace'u opartego o kontener | Konwersacja zostaje usunięta albo zamiata je `SANDBOXD_WORKSPACE_TTL`; nieustawiony — trzymane bezterminowo. Zobacz [Jak długo cokolwiek przeżywa](sandbox.md#how-long-anything-survives) |
| Redis | Kubełki rate limitu kluczowane wywołującym — dla powierzchni publicznej to **jawny adres IP**, w kluczu, na czas TTL okna; klucze deduplikacji triggerów i kanałów; stan wymiany OAuth; zaparkowane zaproszenia; podgląd przeglądania na żywo — ostatni zrzut ekranu, kroki oraz to, co osoba trzymająca przeglądarkę kliknęła i wpisała, dopóki przeglądanie tego nie odczyta; kroki do powtórzenia danej osoby — adresy i etykiety tego, co nacisnęły jej zakończone przeglądania, nigdy to, co wpisała | Po wygaśnięciu: podgląd na żywo godzinę po ostatniej klatce przeglądania, kroki do powtórzenia dwa tygodnie po ostatnim wykonaniu zadania, wszystko inne w ciągu minut |
| `background_jobs` w PostgreSQL | Payload każdego zadania w tle, jego ostatni błąd i odpowiedź asynchronicznego runu przez API | Sweep retencji usuwa zakończone zadanie po `BACKGROUND_JOB_RETENTION_DAYS` (14). Payloady to id i ścieżki, z dwoma wyjątkami: **`event_context` odpalenia wyzwolonego zdarzeniem** — nadawca, temat i treść wiadomości Gmail albo Outlook wraz z id wiadomości i wątku, zgłoszenia GitHub, ładunku webhooka — oraz **prompt i odpowiedź asynchronicznego runu przez API** zostają w zadaniu do tego czasu. Logi workera przechodzą przez ten sam filtr redakcji co logi API |
| Logfire, jeśli skonfigurowany | Trace'y każdego runu | Retencja providera. Dziś trace niesie pełny prompt, wyjście i argumenty narzędzi — zobacz [Trace'y](#traces) |
| Twój relay SMTP | Zaproszenia, magic linki, prośby o zatwierdzenie, alerty budżetowe, raporty użycia oraz własny mail [skrzynki powiadomień](governance.md#alerts) - nienadzorowane zakończenie albo błąd runa, zakończenie albo błąd ingestii dokumentu, zdarzenie bezpieczeństwa albo zmiana konfiguracji, własne ogłoszenie administratora - oraz temat i treść kroku [`email.send`](reference/workflow-nodes.md#email-send) workflow, na adresy, które dostał | Cokolwiek relay zachowa. Mail o zatwierdzeniu nazywa agenta, narzędzie i link, a nie argumenty narzędzia |
| Kopie zapasowe | `pg_dump` to cała baza; wolumen mediów to pliki | Twoje wygaśnięcie kopii. Usunięcie nigdy nie sięga kopii już zrobionej — zobacz [Kopie zapasowe](deploy.md#backups) |

## Co opuszcza wdrożenie { #what-leaves-the-deployment }

Nic nie wychodzi, dopóki wiersz albo ustawienie nie wskaże celu. To jest pełna
lista celów, wraz z konfiguracją, która o każdym decyduje.

| Cel | Co jest wysyłane | Decyduje o tym | Lokalizacja i warunki |
|---|---|---|---|
| Model czatowy | Rozmowa jak dotąd, załączniki wklejone albo opisane, pobrane chunki, wyniki narzędzi; raz na noc, dla [pracy z własnej inicjatywy](governance.md#proactive-work), ostatnie prośby osoby, jej profil i to, co zanotował o niej jej agent | [Profil modelu](models.md#a-model-profile): `provider`, `model`, `base_url` i zapieczętowany klucz. Dwudziestu siedmiu providerów; `ollama` i `litellm` są bezkluczowe i sięgane pod endpointem, który hostujesz, a `openai`, `anthropic`, `google`, `huggingface` i inne przyjmują `base_url`, więc endpoint w UE albo gateway to pole, a nie rozwidlenie. Profil `openai` lub `azure` na Responses API wysyła `store: false`, więc provider nie trzyma zapisanej, możliwej do pobrania odpowiedzi, chyba że profil ustawi `openai_store`; retencja OpenAI na potrzeby monitorowania nadużyć nadal obowiązuje, chyba że konto ma zero data retention | Providera. Weryfikuj per profil |
| Model embeddingowy | Każdy chunk każdego dokumentu w kolekcji i każde zapytanie wyszukujące | Per kolekcja i tylko tam: `embedding_provider` (`openrouter`, `openai` albo `ollama`, z katalogu), a dla dwóch pierwszych klucz z vaultu `embedding_secret_id`, który płaci. Nie ma klucza embeddingowego na poziomie wdrożenia; kolekcja z kluczem, ale bez wskazanego, odmawia indeksowania i wyszukiwania. `ollama` jest bezkluczowa i sięgana pod usługą lokalną, którą kolekcja wskazuje (`embedding_endpoint_id`), na hoście, który prowadzisz | Providera albo Twój własny host. [Wybór na stałe](choosing-models.md#embeddings-are-a-separate-permanent-choice) |
| LlamaCloud | Cały dokument | Kolekcja, której `pdf_parser` to `llamaparse`; musi wskazać klucz z vaultu (`llamaparse_secret_id`), nie ma klucza wdrożenia. Domyślny `pymupdf` parsuje w workerze | LlamaCloud, jeśli użyty |
| Serwer OCR | Wyrenderowane strony dokumentu | Kolekcja, której `pdf_parser` to `liteparse` **i** której `ocr_endpoint_id` wskazuje usługę lokalną; bez tego OCR działa w workerze | Twój własny host — usługa lokalna jest z definicji w sieci wdrożenia |
| Model opisujący obrazy | Obrazy wewnątrz dokumentów | `image_description_model` kolekcji | Providera tego modelu |
| Web research | Zapytanie wyszukiwania, które ułożył agent | `web_research.method` w specu: `duckduckgo` (bez klucza), `tavily`, `brave` albo `exa` (każde z sekretem `search`), albo `native`, gdzie szuka provider modelu czatowego | Dostawcy wyszukiwania albo providera modelu |
| Pobieranie stron i przeglądarka | URL; dla przeglądarki to, co wpisuje na otwieranych stronach | Capability w specu; przeglądarka potrzebuje też endpointu CDP na `BROWSER_CDP_ALLOWED_HOSTS`, domyślnie pustej | Pobieranej strony; hosta przeglądarki i stron, które otwiera |
| Proxy przeglądarki agenta albo przeglądarka hostowana | Wszystko, co przeglądarka ładuje i wysyła, tak jak inaczej robiłaby to przeglądarka we wdrożeniu - strony, treść formularzy, ciasteczka, logowania - oraz własny zapis proxy albo usługi | `browser_use.connection` w spec (#2130); domyślnie `built_in` | Proxy albo usługa przeglądarki hostowanej (Browserbase, Steel lub inna), na umowie organizacji z nią |
| Kroki przeglądarki | Każdy krok przeglądania idzie do modelu tego agenta: adres strony, jej tytuł, etykiety widocznych elementów i do 4000 znaków jej widocznego tekstu, plus zrzut ekranu przy włączonym `vision` — co może być zawartością systemu wewnętrznego. To, co zawiera pole, nie jest powtarzane: tabela elementów podaje tylko, że pole jest wypełnione | Capability `browser_use` w specu | Dostawcy modelu agenta, tak jak przy rozmowie |
| Sandbox, ruch wychodzący | **Cokolwiek z workspace'u, do dowolnego hosta** — runtime `workbench` ma sieć, powłokę i `curl` | Capability `sandbox` i runtime z `needs_network`; zatwierdzanie komend bramkuje to, co się uruchamia, a nie to, dokąd się łączy | Dokądkolwiek poszła komenda. Kontrola ruchu wychodzącego to firewall hosta sandboksa, a nie ustawienie tutaj |
| Serwer MCP | Argumenty i wyniki narzędzi, agenta albo kroku [`mcp.call`](reference/workflow-nodes.md#mcp-call) workflow | `mcp_connections.url`, per organizacja albo per osoba | Operatora serwera |
| Google Workspace i Microsoft 365, przez serwer, który prowadzisz | To, o co prosi krok `mcp.call` agenta lub workflow: frazy wyszukiwania, identyfikatory wiadomości i wątków, treść odpowiedzi, szczegóły wydarzeń. Twój własny serwer przekazuje to dalej do API Google lub Microsoft i trzyma też tokeny zalogowanego konta | Połączenie organizacji lub osoby utworzone z wpisu katalogu `google-workspace` albo `ms-365` | Twój serwer, a potem Google lub Microsoft |
| Microsoft Work IQ | To, o co prosi wywołanie narzędzia, i odpowiedź, w hostowanej usłudze Microsoftu; rozliczane w Copilot Credits | Połączenie utworzone z wpisu katalogu `work-iq` | Microsoftu |
| Host we własnej sieci | Wszystko, co krok HTTP workflow, konektor, wywołanie A2A albo połączenie MCP tam wysyła | `OUTBOUND_PRIVATE_ALLOWLIST`, domyślnie pusta; `MCP_ALLOWED_HOSTS` tylko dla MCP | Host, który wpiszesz. Każde konto każdej organizacji może sięgnąć do każdego jego portu |
| mem0 | Wspomnienia zapisane dla osoby albo czatu | `base_url` capability `memory_mem0`, który musi być w `MEM0_ALLOWED_HOSTS` | Hosta mem0, na który pozwalasz |
| Logfire | Spany każdego żądania i runu | `LOGFIRE_TOKEN` na poziomie wdrożenia; token `observability` w specu albo `logfire_token_secret_id` na środowisku przekierowuje te runy do innego projektu. `LOGFIRE_BASE_URL` wybiera wdrożenie w USA albo w UE. Nieustawione wszędzie — nic nie jest wysyłane | Pydantic, USA albo UE |
| Mowa na tekst, generowanie obrazów | Notatka głosowa z kanału, nagranie podyktowane w `/chat` albo nagranie anonimowego odwiedzającego na hostowanej stronie lub w widgecie; prompt | Provider, do którego rozwiązuje się nagranie - własna para bota, nadpisanie agenta albo domyślny provider organizacji, który bot dziedziczy, chyba że ma to wyłączone - wysyłane z kluczem z vaultu wskazanym obok tej pary - kluczem API dla `groq`, `mistral` albo `openai`, widocznym dla organizacji na poziomie organizacji i bota; przy dyktowaniu w `/chat` także silnik organizacji ustawiony na `server`, a dla strony albo widgetu jego własne `dictation: server`. Profil dla `google` albo `openai` przy obrazach. Dźwięk dyktowania nie jest tu przechowywany. Przy `browser` na stronie albo w widgecie przeglądarka odwiedzającego wysyła dźwięk do swojego dostawcy i nic z niego nie przechodzi przez ten deployment | Providera albo, przy obrazach, twój własny host; przy `browser` dostawcy przeglądarki |
| Provider głosu realtime | W trakcie [rozmowy głosowej](voice.md): dźwięk rozmówcy, instrukcje agenta i definicje narzędzi, wyniki narzędzi oraz wcześniejsze tury rozmowy jako tekst, gdy rozmowa się zaczyna albo łączy ponownie | Sekcja Głos agenta: `provider`, `model` (albo wdrożenie Azure) i klucz z vaultu `secret_id`, opublikowana; bez sekcji Głos agent nie odbiera rozmów. Przez WebRTC (OpenAI) dźwięk płynie bezpośrednio między przeglądarką a providerem; przez relay (Azure, Gemini, xAI) przechodzi przez to wdrożenie, nie będąc przechowywanym. Dźwięk nie jest tu zatrzymywany, a sesja zachowuje tylko transkrypcje | Providera |
| Zamiana tekstu na mowę | Tekst do wypowiedzenia i ewentualna wskazówka, jak go wypowiedzieć | `provider` capability `text_to_speech`: `openai`, `elevenlabs` albo `google`, z kluczem bindingu | Providera |
| Generowanie wideo | Prompt i ewentualny obraz początkowy | `provider` capability `video_generation`: `google`, `byteplus`, `xai` albo `alibaba`, z kluczem bindingu. `google` zapisuje interakcję (`store: true`), bo Gemini dostarcza klip pod adresem tylko z zapisanej; pozostałych trzech nikt o to nie prosi | Providera |
| Slack, Teams, Telegram, Mattermost | Odpowiedzi agenta; adres e-mail nowego członka, żeby znaleźć go na [powitanie](channels.md#a-welcome-for-a-new-member) w Slacku, Mattermost albo Teams | Wiersz `channel_bots` z tokenem w vaulcie | Dostawca komunikatora i tak ma już ten czat |
| Logowanie Google | Nic wychodzącego; Google zwraca e-mail, imię, zdjęcie i id konta | `GOOGLE_CLIENT_ID` | Google |
| Twój relay SMTP | Poczta wymieniona wyżej oraz tekst kroku [`email.send`](reference/workflow-nodes.md#email-send) workflow, na adresy wybrane przez jego autora | `SMTP_HOST`, `SMTP_TLS` | Twoja, potem każdego odbiorcy |

Konektory synchronizacji działają w drugą stronę: źródło Google Drive albo S3
zaciąga dokumenty **do środka**, uwierzytelnione sekretem `connector`, a od tej
chwili dokumenty są kopią wdrożenia i podlegają regułom powyżej. To, kto może
przeczytać, co zaciągnęło źródło, jest
[decyzją, którą podejmuje wiersz źródła](file-processing.md#who-ends-up-able-to-read-what-a-source-ingested).

## Dane tabel pokazywane na stronie { #table-data-on-a-page }

Opublikowana [strona](artifacts.md#live-data) może pokazywać rekordy z tabeli,
a te rekordy mogą być danymi osobowymi. To **przepływ wewnątrz wdrożenia, od
właściciela strony do każdego, kto może ją otworzyć** — nie cel poza nim — ale
omija on własną kontrolę dostępu tabeli, więc jest tu wymieniony.

- **Co przepływa.** Tylko kolumny, które nazywa zapytanie strony, i wiersze, które
  wybierają jego filtry, do 1000 na binding. Filtr może używać kolumny, której strona
  nie pokazuje, a właściciel dowiaduje się, której. Formuły, lookupy, rollupy
  i etykiety linków niosą też dane z powiązanych tabel, a zgoda wymienia te tabele.
- **Z czyjego upoważnienia.** Właściciela strony. Każdy oglądający dostaje te same
  rekordy, niezależnie od własnego dostępu do tabeli. Dane opuszczają tabelę dopiero
  wtedy, gdy właściciel to potwierdzi, po przeczytaniu zapytań słowami i tego, kto
  może otworzyć stronę teraz i później (role, które otwierają każdą stronę,
  widoczność, osoby i grupy). Dane są czytane od nowa przy każdym załadowaniu,
  nigdy nie są przechowywane w stronie. Odczyty dla członków nie są cache'owane;
  odczyty dla strony publicznej są, jak opisano niżej.
- **Co się o tym przechowuje.** Dla każdej wersji strony: kto ją opublikował, odcisk jej
  zapytań, czy właściciel wyraził zgodę, kiedy i pod jakim członkostwem. Prośby
  o udostępnienie zachowują proszącego, rodzaj, opcjonalną notatkę, decyzję i to, kto
  ją podjął. Ślad audytu zapisuje zgodę, jej wycofanie, auto-zgodę, granty `edit_data`,
  zmiany właściciela i prośby, razem z tekstem, który człowiek potwierdził.
- **Czego nigdy się nie loguje.** Wartości rekordów, wartości filtrów i adres treści
  strony serwowanej z danymi. Wpisy audytu i powiadomienia nazywają stronę i osoby,
  nigdy wiersz.
- **Co tam nie dociera.** Zgoda usuniętego członka wygasa wraz z jego członkostwem,
  a strona, której właściciel odszedł, nie serwuje danych, dopóki inny właściciel
  ich nie potwierdzi.

### Dla osób bez konta { #table-data-on-a-public-page }

To jedyny przepływ tutaj, który **wychodzi poza krąg osób mających konto**. [Publiczny
link strony i jej embedy](artifacts.md#live-data-on-a-public-link) mogą wpisać te same
rekordy do strony dla każdego, kto otworzy adres, i dla każdej witryny, która ją
osadza, bez logowania. Otwierają go dwie decyzje, a wdrożenie, które tego przepływu
nie chce, zostawia pierwszą wyłączoną.

- **Domyślnie wyłączone, w całej organizacji.** `public_live_data` to wyłącznik, który
  zmienia tylko Owner albo Admin, jako on sam. Gdy jest wyłączony, żadna strona nie
  pokazuje danych w linku ani w embedzie, cokolwiek potwierdził jej właściciel.
- **Potem per strona.** Właściciel strony, albo w jego imieniu Owner lub Admin,
  potwierdza to po ekranie, który nazywa tabele i kolumny i mówi, kto może je czytać —
  każdy z linkiem, jego hasło i wygaśnięcie, każda witryna osadzająca. Zgoda jest
  związana z zapytaniami strony i z tym kręgiem odbiorców. Dodanie witryny, usunięcie
  hasła, wyłączenie linku, archiwizacja strony, nowy właściciel i wycofana zgoda
  członka ją czyszczą.
- **Co jest przechowywane.** Na stronie: odcisk zapytań, którym ją udzielono, kto ją
  potwierdził, członkostwo właściciela i kiedy. Wiersz organizacji trzyma wyłącznik.
  Ślad audytu zapisuje `organization.public_live_data_changed`,
  `artifact.public_data_consented`, `artifact.public_data_withdrawn` i
  `artifact.public_data_voided` z nazwami tabel i kolumn, witrynami osadzającymi,
  informacją, czy hasło jest ustawione, i powodem — nigdy wiersz, wartość ani odwiedzający.
- **Cache.** Rekordy bindingu są trzymane przez 30 sekund w pamięci procesu API, żeby
  ruchliwa strona nie czytała swojej tabeli przy każdym odwiedzającym. **Nigdy nie są
  zapisywane** w Redisie, w bazie danych ani w pliku, pamięć jest ograniczona w bajtach
  (`ARTIFACT_PUBLIC_DATA_CACHE_BYTES`) i znika, gdy proces się zatrzymuje. Każda bramka
  dostępu działa, zanim cache zostanie odczytany, więc wyłączenie wyłącznika albo
  wymiana klucza linku kończy przepływ przy następnym ładowaniu; to, co odwiedzający
  już załadował, zostaje w jego przeglądarce.
- **Czego nigdy się nie loguje.** Wartości rekordów, wartości filtrów, klucz linku i
  adres treści strony załadowanej z danymi są trzymane poza logami, śladami i wpisami
  audytu. Żaden odwiedzający nie jest zapisywany: link liczy otwarcia, nie osoby. Tylko
  klucz limitu żądań trzyma IP odwiedzającego, w Redisie, przez minuty.
- **Nikt nie dowiaduje się, dlaczego.** Odwiedzający, którego ładowanie nie przechodzi
  bramki, widzi stronę bez jej danych i bez powodu, więc strona nie mówi, co trzyma
  tabela ani dlaczego jest ukryta.
- **Co widzi witryna osadzająca stronę.** Witryna osadzająca ramkuje stronę; strona
  działa w nieprzezroczystym originie bez sieci, więc witryna nie może odczytać rekordów
  z ramki, ale czyta je każdy, kto otwiera witrynę.

Rekordy pokazane każdemu z linkiem może skopiować każdy, kto je widzi. Wiąż publiczną
stronę tylko z kolumnami, które mają być publiczne.

Wdrożenie, które musi zachować wiersze tabeli przed niektórymi swoimi członkami,
nie powinno wiązać z nią strony, którą ci członkowie mogą otworzyć; potwierdzenie
wymienia, kim są.

## Kontrole i gdzie każda jest dowiedziona { #controls-and-where-each-is-proved }

Każdy wiersz nazywa mechanizm w kodzie oraz test albo stronę, która go przypina,
albo zgłoszenie, które to zrobi. Wiersz, którego ostatnia kolumna to zgłoszenie,
jest luką — i tak jest nazwany.

| Kontrola | Mechanizm | Dowiedziona przez |
|---|---|---|
| Izolacja tenantów | `organization_id` w każdej tabeli należącej do organizacji, rozwiązywany z `X-Organization-Id` do członkostwa przy każdym żądaniu; wiersze podrzędne osiągalne tylko przez sprawdzenie rodzica | `tests/integration/test_conversation_tenant_isolation.py` i jego rodzeństwo; [Uprawnienia](permissions.md) |
| Dostęp do wiersza | Trzy warstwy: administrator wdrożenia, rola w organizacji, grant per zasób przez `resolve_access`. Kontrolka, której wywołujący nie może użyć, nie jest renderowana | Testy odmów w `tests/api/`; [Uprawnienia](permissions.md#how-the-layers-combine) |
| Czytanie cudzego czatu | Właściciel, jawne udostępnienie albo administrator aplikacji wdrożenia — nigdy rola w organizacji. Czat projektu czyta się wyłącznie przez projekt: każdy, kto może widzieć projekt, łącznie z osobą, która czat zaczęła, i nikt, kto przestał móc. Konwersacje mają własne sprawdzenie, `ConversationService._may_read`, a nie formułę grantów | `admin_conversations.py` wymaga `is_app_admin`; `tests/integration/test_conversation_tenant_isolation.py` |
| Poświadczenia w spoczynku | Szyfrowanie kopertowe per organizacja, wersjonowane klucze główne, rotacja z suchym przebiegiem | [Sekrety](secrets.md#what-never-happens), cztery gwarancje przypięte testami |
| Treść w spoczynku | **Nieszyfrowana przez aplikację.** Dane Postgresa, `media_data` i katalog główny workspace'ów sandboksa polegają na szyfrowaniu dysku albo wolumenu, które zapewniasz. Wyjątkiem są pliki z uploadu i czatu przy `FILE_STORAGE_BACKEND=s3` i `FILE_STORAGE_S3_ENCRYPTION` ustawionym na `sse-s3` (domyślnie) albo `sse-kms` pod kluczem, który trzymasz: każdy zapis prosi wtedy magazyn o ich zaszyfrowanie. Trzeci tryb, `none`, nie wysyła nagłówka szyfrowania i istnieje dla magazynu zgodnego z S3 bez KMS | Kontrola operatora. [Konfiguracja](configuration.md#uploaded-files-at-rest); `agenticos cmd doctor` wypisuje, na którym backendzie stoi działające wdrożenie |
| W tranzycie, przychodzące | HTTPS na Twoim proxy; `Strict-Transport-Security`, gdy `ENVIRONMENT=production`; ciasteczka sesji `httpOnly`, a `secure` ze schematu żądania przy logowaniu i odświeżeniu. Trasa zmiany hasła ustawia `secure` tylko w buildzie produkcyjnym | [Wdrożenie](deploy.md#choose-a-reverse-proxy); `frontend/src/app/api/auth/login/route.ts` |
| W tranzycie, do magazynów | `POSTGRES_SSLMODE` i `REDIS_SSL`; `agenticos cmd doctor` raportuje, czy połączenie, które nawiązał, było szyfrowane | [Połączenia szyfrowane](configuration.md#encrypted-connections-tls); `tests/integration/test_store_tls.py` |
| W tranzycie, do providerów | HTTPS do każdego skatalogowanego endpointu. Własny `base_url` jest odrzucany bez hosta albo z poświadczeniami w środku, ale **`http://` jest przyjmowany**, dla Ollamy albo gatewaya w sieci samego wdrożenia; profil na zwykłym HTTP wskazujący poza tę sieć wysyła prompty i klucz jawnie. Punkt 4 listy kontrolnej wypisuje każdy taki profil | `refused_field("base_url", ...)` w serwisie profili modeli; schemat to kontrola operatora |
| Sekrety w odpowiedziach, logach, audycie, eksportach | Żaden endpoint nie zwraca jawnego tekstu; `SecretStr` wszędzie; spece odwołują się do sekretów po id | [Sekrety](secrets.md#what-never-happens) |
| Dane osobowe w logach | `app/core/logging.py` redaguje adresy e-mail, JWT, klucze API, tokeny bearer, pary `password=` oraz sekretny segment adresu — klucz linku albo token treści artefaktu, token udostępnionej rozmowy, formularza workflow, testu webhooka, linku kanału albo zaproszenia, albo token wznowienia przebiegu workflow — a także wartość parametru zapytania będącego poświadczeniem — `visitor` i `token` socketu widgetu agenta, `code`, `state` i `invitation_handle` logowania oraz `token` linku wysłanego e-mailem — z każdego rekordu logu, tak w API, jak i w workerze, łącznie z logiem dostępu uvicorna i jego liniami WebSocketu. Te same segmenty i wartości są redagowane w spanach Logfire i w argumentach endpointu, które te spany niosą, zanim span zostanie skopiowany albo wypisany. Dołączone konfiguracje Traefika i Nginx pomijają ścieżkę, query string i `Referer` w logu dostępu proxy | `tests/test_logging.py`, `tests/test_logfire_redaction.py`; worker instaluje to w `app/worker/__main__.py`, a każdy proces potomny ingestii w `app/worker/child.py` (#440); [Wdrożenie na serwer](deploy.md#choose-a-reverse-proxy) |
| Dane osobowe docierające do modelu | Capability `guardrails` redaguje numery IBAN, numery kart, amerykańskie numery ubezpieczenia społecznego, numery telefonów i adresy e-mail z promptów, odpowiedzi, wyników i argumentów narzędzi, jeśli jest skonfigurowana | [Capabilities](reference/capabilities.md); jej testy pod `tests/` |
| Dane osobowe w kolumnie błędu | `rag_documents.error_message` i pokrewne zapisują etap i klasę, nigdy tekst klienta | `app/services/rag/failures.py` (#423) |
| Rozliczalność | Wpisy audytu dzielą transakcję działającą i zawodzą zamknięte; podszycie nazywa obie osoby; eksporty masowe są zapisywane | [Nadzór](governance.md#audit) |
| Eksport audytu | `GET /audit/export`, CSV albo JSONL w oknie czasu, bramkowany na `audit:read` i zapisywany w samym śladzie | [Governance](governance.md#audit) (#1422) |
| Dowód nienaruszalności śladu | Każdy wpis wchodzi w łańcuch haszy danej organizacji, a każdy łańcuch ma checkpoint na swoim najwyższym stanie, więc przepisany wpis, urwany koniec i skasowany łańcuch są wykrywalne. `agenticos cmd audit-verify` przechodzi je i kończy się kodem niezerowym przy naruszeniu | [Nadzór](governance.md#audit) (#1622, #1648). Wykrywanie, nie zapobieganie: kto ma poświadczenia samej bazy, ten przekuje łańcuch od nowa albo zdejmie trigger pilnujący checkpointu |
| Trace'y | `observability.content` per agent: `full` zapisuje wszystko, `none` tylko czas, tokeny, koszt i nazwy narzędzi, a tryb ten dziedziczy specjalista tego agenta | [Środowiska](environments.md) (#1413); stan pośredni `redacted` został odrzucony, [#1616](https://github.com/vstorm-co/agenticos/issues/1616) |
| Retencja według harmonogramu | Na organizację i na klasę — rozmowy i ich pliki, runy i manifesty, workspace'y, pamięć agentów, wgrane dokumenty i audyt — w ramach domyślnej wartości, sufitu i podłogi audytu na poziomie wdrożenia. Codzienny sweep usuwa twardo i zapisuje liczniki, nigdy treść. Receipts, wysłane wiersze outbox i history Virtual Tables są zamiatane w tym samym przebiegu, według okresów całego wdrożenia, a nie per organizacja. Backupy i cokolwiek już wysłane do zewnętrznego kolektora są poza tym. `notifications` nie jest jedną z tych klas: zamiast tego jest zamiatane według własnego, stałego harmonogramu — wiersz *przeczytany* po 90 dniach, a każdy wiersz po roku bez względu na to. Same `announcements` są wyłączone, więc to, co zostało wysłane, pozostaje możliwe do sprawdzenia w śladzie audytu, nawet gdy jego dostawy się przedawnią Wygenerowane media też mają osobny okres `GENERATED_MEDIA_RETENTION_DAYS`. | [Retencja](governance.md#retention); `test_retention.py`, `tests/integration/test_retention_sweep.py`; zamiatanie powiadomień to `tests/integration/test_notification_retention.py` (#1598, Decision 8); `test_generated_media.py`, `tests/integration/test_generated_media.py` |
| Usunięcie jednej osoby | Usunięcie konta uzgadnia to, co by je zablokowało, odpina bajty załączników po commicie i czyści to, do czego nie sięga żadna kaskada — notatki, które agenci o niej zapisali, jej tożsamości platformowe, jej workspace'y. Usunięcie pamięci to również osobne wywołanie i sięga mem0 | [Co obejmuje usunięcie](#what-deletion-reaches) — co jest zatrzymywane celowo; `test_personal_data.py` |
| Dostęp do własnych danych | Osoba czyta w Ustawienia → Pamięć wszystko, co każdy agent tutaj o niej zapisał, i może notatkę wyłączyć, przywrócić albo usunąć. Czytanie *cudzego* magazynu należy wyłącznie do administratora wdrożenia — nie do roli w organizacji — i jest audytowane z aktorem, tenantem, podmiotem i powodem, nigdy z treścią. Magazyny zewnętrzne (mem0) są nazwane, a nie listowane | [Jak to czytać i jak wymazać](reference/capabilities.md#reading-it-and-erasing-it); `test_memory_self_service.py`. Wszystko inne, co jest o niej trzymane, wraca z `GET /me/data/export`, ograniczone rozmiarem i audytowane (#1421) |
| Tożsamość korporacyjna | Logowanie Google, hasła, generyczne OIDC przeciwko dostawcy, którego już prowadzisz — konfigurowane samym discovery z `OIDC_ISSUER` — oraz własny katalog przez LDAP albo Kerberos. Adres z katalogu, nazwa wyświetlana i stabilny identyfikator są trzymane na koncie; grupy z katalogu są czytane przy każdym logowaniu i nie są przechowywane — przechowywane są tylko członkostwa, które tworzą z nich mapowania organizacji. Bez SAML i SCIM | [Logowanie katalogowe i grupy](directory.md); `OIDC_ISSUER`, `LDAP_URL` |
| Macierz kontroli, którą czyta przegląd bezpieczeństwa | [Bezpieczeństwo](security.md#controls-matrix) mapuje każdą kontrolę na jej mechanizm i test, który go trzyma, w ramach HIPAA §164.312 i SOC 2 CC6–CC8; ta strona i [Wdrażanie](rollout.md#what-your-security-review-will-ask) to reszta | [Bezpieczeństwo](security.md) (#1412) |
| Powierzchnie publiczne | Klucz odwiedzającego hostowanej strony jest losowy, nigdy wyprowadzony z osoby; wpuszczanie i wgrywanie są rate-limitowane per adres, a adres leży w kluczu Redisa na czas okna i nigdzie indziej | [Kanały](channels.md#a-hosted-page) |
| Noty prawne | Własne adresy Regulaminu i Polityki prywatności wdrożenia zastępują strony wbudowane | [Wdrożenie](deployment.md#identity) |

### Trace'y { #traces }

`instrument_pydantic_ai()` działa z domyślnym ustawieniem biblioteki, więc span
trzyma wiadomość użytkownika, odpowiedź modelu oraz każdy argument i wynik
narzędzia. Z nieustawionym `LOGFIRE_TOKEN`, bez tokenu `observability` w żadnym
specu i bez `logfire_token_secret_id` na żadnym środowisku nic nie jest
wysyłane, a id trace'u i tak jest zapisywane lokalnie. Wdrożenie, które
potrzebuje trace'ów bez treści, ustawia agentowi `observability.content` na
`none`: zapisywane są czas, tokeny, koszt i nazwy narzędzi, a żaden tekst
wiadomości nie wychodzi — i tryb ten dziedziczy specjalista tego agenta, czy to
napisany inline przez autora, czy wymyślony przez model w trakcie runu.

Trzeciego trybu pomiędzy nie ma. Eksport wyczyszczony filtrem PII to gwarancja,
której nikt nie zaudytuje — jeden identyfikator, który filtr przepuści, już
wyszedł, a operator sądzi, że nie — więc wybór jest świadomie między całą treścią
a żadną ([#1616](https://github.com/vstorm-co/agenticos/issues/1616)).

### Co obejmuje usunięcie { #what-deletion-reaches }

Usuwanie to to, co produkt robi dziś, gdy ktoś o to poprosi; retencja według
harmonogramu to [#1420](https://github.com/vstorm-co/agenticos/issues/1420).

| Akcja | Usuwa | Zostawia |
|---|---|---|
| `DELETE /conversations/{id}` (właściciel) | Konwersację, jej wiadomości, wywołania narzędzi, oceny, udostępnienia i wiersze `chat_files`, kaskadą - w tym transkrypcję rozmowy głosowej, bo jej tury są wiadomościami; bajty załączników pod `MEDIA_DIR`, zebrane przed usunięciem i odpięte po commicie; obrazy, mowę i wideo wygenerowane przez jej agentów - wiersze w usunięciu, bajty przez zadanie zakolejkowane razem z nim; obiekty mediów odciążone z tego wątku, po prefiksie; workspace kontenerowy przez `purge_for_conversation` | Wiersze runów i manifesty, które nazywały tę konwersację, zachowują swoją kopię promptu; wiersz `voice_calls` zachowuje swoje czasy i koszt, z wyczyszczonym powiązaniem z konwersacją |
| `DELETE /memory/person/{user_id}` (osoba albo `members:manage`) | Każdy wiersz `agent_memory_files` kluczowany na osobę we wszystkich agentach organizacji, i to samo w każdym związanym magazynie mem0 | Notatki kluczowane na czat grupowy, w którym osoba się odzywała |
| `DELETE /users/{id}` | Konto, jego sesje, jego osobistą organizację i osobiste kolekcje wraz z ich tabelami wektorowymi i plikami, jawnym teardownem; konwersacje poza projektami i pliki czatu kaskadą; ich bajty, odpięte po commicie; obrazy, mowę i wideo wygenerowane przez agentów w tych konwersacjach - wiersze w usunięciu, bajty przez zadanie zakolejkowane razem z nim; oraz to, do czego nie sięga żadna kaskada — notatki, które agenci zapisali o tej osobie (`owner_key` to string, nie klucz obcy), jej tożsamości platformowe i workspace'y przypisane do użytkownika | Wpisy audytowe nazywające id aktora, a przy niektórych akcjach e-mail — zatrzymywane celowo, bo wpis z usuniętym aktorem jest gorszy niż wpis nazywający usunięte konto. Wiadomości w konwersacjach należących do kogoś innego oraz czaty projektów, które ta osoba zaczęła - zostają dla zespołu, bez autora, razem z wygenerowanymi w nich mediami; jej wiadomości są w nich pokazywane jako byłego członka. Media, które osoba wygenerowała bez konwersacji - podglądy i przebiegi testowe, wtrącenia `/btw` w kanałach, runy API, które nie wskazały konwersacji - których żaden wiersz z nią nie łączy; odchodzą po 7 dniach |
| Usunięcie dokumentu albo kolekcji | Wiersze, tabelę wektorową i zapisany plik, przez trwały flow po commicie | Nic, gdy flow już przebiegł; liczniki `sync_logs` zostają |
| Usunięcie organizacji | Wszystko do niej ograniczone, tym samym odroczonym rozmontowaniem - jej wygenerowane media po prefiksie, łącznie z plikami zapisanymi, zanim zaczęto je rejestrować | Kolekcje osobiste, które jedynie niosły to id |

Żadne z tych nie sięga kopii zapasowej. Odtworzenie przywraca to, co usunięto,
więc wygaśnięcie kopii jest częścią polityki retencji i jest spisane razem z nią.

## Co wdrożenie musi rozstrzygnąć i zdobyć { #what-a-deployment-has-to-decide-and-obtain }

Oprogramowanie nie może dostarczyć żadnej z tych rzeczy. Każda jest dowodem,
o który poprosi przegląd, i jest czymś innym niż techniczna możliwość, która ją
umożliwia.

- **Umowa powierzenia z każdym skonfigurowanym podprzetwarzającym** — każdym
  providerem nazwanym przez wiersz `model_profiles` albo `organization_secrets`,
  providerem embeddingów, LlamaCloud, jeśli kolekcja go używa, dostawcą
  wyszukiwania nazwanym przez `method` agenta, hostem mem0, Logfire, relayem
  SMTP i Google, jeśli logowanie jest włączone.
- **Oświadczenie o lokalizacji danych dla każdego providera**, dopasowane do
  `base_url`, którego faktycznie używa każdy profil. Provider z endpointem w UE
  jest w UE tylko wtedy, gdy profil tak mówi.
- **Wyłączenie z treningu dla każdego providera**: ustawienie konta albo zapis
  umowny, na mocy którego dane z API nie są używane do treningu. Własne
  stanowisko platformy to jedno zdanie — niczego nie trenuje — a reszta jest ich.
- **Umowa powierzenia z Vstorm**, tylko jeśli Vstorm prowadzi wdrożenie.
- **Harmonogram retencji** dla konwersacji, plików, pamięci, dokumentów, runów
  i audytu, a obok niego wygaśnięcie kopii zapasowych. Dopóki
  [#1420](https://github.com/vstorm-co/agenticos/issues/1420) nie wymusi
  harmonogramu, retencja jest ręcznym usuwaniem.
- **Szyfrowanie dysku albo wolumenu** na hoście bazy, wolumenie mediów i hoście
  sandboksa, skoro aplikacja sama nie szyfruje treści — oraz reguła ruchu
  wychodzącego na hoście sandboksa, jeśli agenci mogą uruchamiać komendy.
- **Strony prawne**, do których wdrożenie linkuje, i to, kto odpowiada na żądanie
  dostępu albo usunięcia. Mechanizmy są tutaj — `GET /me/data/export` i usunięcie
  konta — ale kto przyjmuje żądanie i w jakim terminie, należy do administratora
  danych.

## Weryfikacja jednego wdrożenia { #verifying-one-deployment }

Powtarzalne sprawdzenia, z hosta, na działającym wdrożeniu. Każde wypisuje
fakty, które przegląd może załączyć; żadne nie wypisuje poświadczenia ani
danych osoby. Uruchamiaj je z `backend/` albo przez `docker compose exec api`.

```bash
# 1. Czy to w ogóle ruszy i czy połączenia do magazynów są szyfrowane?
#    `postgres` raportuje stan TLS połączenia, które sam doctor nawiązał.
uv run agenticos cmd doctor

# 2. Każde zapieczętowane poświadczenie wciąż otwiera się pod skonfigurowanymi
#    kluczami głównymi.
uv run agenticos cmd vault-rotate --dry-run

# 3. Łańcuchy haszy śladu audytowego i ich checkpointy, przeliczone od nowa.
#    Kod wyjścia niezerowy, jeśli którykolwiek łańcuch został naruszony.
uv run agenticos cmd audit-verify

# 4. Wszystko, co to wdrożenie faktycznie skonfigurowało: ustawienia decydujące
#    o tym, co wychodzi na zewnątrz, każdy provider i endpoint, do którego może
#    sięgnąć agent, trzymane poświadczenia według przeznaczenia, kolekcje i to,
#    kto liczy dla nich embeddingi, serwery we własnej sieci, serwery MCP,
#    portale triggerów, źródła synchronizacji i boty kanałów, zdolności, które
#    sięgają pod własny adres, gdzie trafiają trace'y runów i ile treści niesie
#    span, ile w każdym magazynie objąłby okres retencji oraz pliki pod
#    `MEDIA_DIR`, na które nie wskazuje już żaden wiersz.
uv run agenticos cmd data-protection-report --older-than 365
```

Punkt 4 to ten do załączenia. Wypisuje konfigurację i liczby, nigdy treść:
żadnego tekstu wiadomości, żadnego dokumentu, żadnej wartości sekretu ani jej
podpowiedzi, a ustawienie trzymające poświadczenie jest raportowane jako
ustawione albo nieustawione, nie wypisywane. `--older-than` to rozważany okres
retencji, w dniach, a ostatnia kolumna jego tabeli retencji pokazuje, co ten
okres już by usunął.

Jego ostatnia sekcja liczy bajty, których nie nazywa już żaden wiersz. Usunięcie
konwersacji albo konta odpina teraz ich załączniki po commicie, więc ta ścieżka
już do licznika nie dokłada; to, co jeszcze znajduje, pochodzi sprzed tamtych
usunięć albo z odpięcia, którego zamiatanie best-effort nie dokończyło.

Katalog roboczy parsowania jest wyłączony, bo z założenia nie ma wiersza.
Wygenerowane media są liczone, odkąd `generated_media` zapisuje każdy plik, więc
to, co pojawia się pod katalogiem `generated_<org>`, to głównie plik wygenerowany,
zanim ta tabela powstała, który odchodzi tylko razem ze swoją organizacją. Może to
być też plik, którego odpięcie się nie udało po usunięciu jego wiersza, albo plik
wciąż zapisywany, zanim powstał jego wiersz. Wszystko inne, co się tam liczy, to bajty, których produkt już nie znajdzie i nie
umie usunąć. Raportuje katalog i liczbę, a nie
nazwę pliku, bo zapisana ścieżka zachowuje nazwę, pod którą plik został wgrany.

Dwie sekcje czyta się z tego, co się wykonuje, a nie z tabeli. **Cele zdolności**
wymieniają zdolności podpięte do agenta, które sięgają pod własny adres —
`web_research` szuka przez DuckDuckGo bez żadnego poświadczenia, a więc bez
wiersza gdziekolwiek indziej w raporcie — a **Tracing** czyta się z każdej wersji
zdolnej do uruchomienia: domyślnej oraz tej, którą przypina każde nazwane
[środowisko](environments.md), bo run przez to środowisko używa obserwowalności
tamtej wersji, a nie domyślnej.

Czego żadna komenda nie wytworzy, to druga połowa tej strony: umowy, lokalizacje
i wyłączenia z treningu z poprzedniej sekcji. Załącz je obok wyniku.

## Otwarte warunki pierwszego wdrożenia { #open-conditions-for-a-first-rollout }

Spisane dla wdrożenia, pod które powstała ta strona, i prawdziwe dla każdego
wdrożenia, dopóki każdy z nich się nie zamknie.

**W kodzie, i trwałe:**

- Trace'y niosą pełną treść, chyba że agent ustawi `observability.content` na
  `none`. Nie ma stanu pośredniego z filtrem i nie będzie: częściowo wyczyszczony
  eksport to gwarancja, której nikt nie zaudytuje
  ([#1616](https://github.com/vstorm-co/agenticos/issues/1616)).
- **Treść w spoczynku należy do operatora.** Treści wiadomości, dokumenty i ich
  wektory oraz workspace'y sandboksa to zwykłe kolumny i pliki; vault pieczętuje
  poświadczenia, nie treść. Pliki z uploadu mogą trafić do magazynu zgodnego z S3,
  który szyfruje je po swojej stronie, ale baza i wolumen mediów są chronione
  szyfrowaniem dysku albo wolumenu — albo wcale.

**Zamknięte i opisane wyżej, a nie tutaj:** dowód nienaruszalności śladu
audytowego (#1622, #1648), tryb treści trace'u per agent i jego dziedziczenie przez specjalistów (#1413, #1699), trace'owanie w procesie wykonującym
uruchomionego agenta (#1700), macierz
kontroli HIPAA i SOC 2 w [Bezpieczeństwie](security.md#controls-matrix) (#1412),
usunięcie i eksport danych jednej osoby (#1421), backend S3 z szyfrowaniem po
stronie serwera (#1423) oraz generyczne logowanie OIDC (#1419).
Trace'y nie mają stanu pośredniego z filtrem i go nie dostaną
([#1616](https://github.com/vstorm-co/agenticos/issues/1616)); dla wdrożenia,
które nie może eksportować treści, odpowiedzią jest `none`.

**We wdrożeniu, rozstrzygane przez jego operatora:** umowy, lokalizacje,
wyłączenia z treningu, harmonogram retencji, wygaśnięcie kopii zapasowych,
szyfrowanie dysku, ruch wychodzący sandboksa i strony prawne z poprzedniej
sekcji. Każdy z nich to dowód, którego `data-protection-report` celowo nie
wytwarza.

Przegląd, który zastanie każdy wiersz powyżej albo zamknięty, albo zaakceptowany
na piśmie, ma to, co ta strona może mu dać. Reszta należy do wdrożenia.
