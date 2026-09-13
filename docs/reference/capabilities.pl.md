---
source_sha: 82fcf03671a3
---

# Katalog capability { #the-capability-catalog }

Wszystko, co agent potrafi *zrobić*, pochodzi z jednego z dwóch miejsc: z
capability zarejestrowanej w kodzie tego deploymentu albo z
[serwera MCP](../mcp.md), który ktoś podłączył. Ta strona jest pierwszą z tych
list.

Capability to jednostka, którą warto włączyć albo wyłączyć — jedna pozycja w
Builderze, jeden wpis w specu. Celowo nie jest to „narzędzie": wyszukiwanie w
bazie wiedzy to jedna decyzja osoby konfigurującej agenta, a to, czy wystawia
dziś jedną funkcję, a za miesiąc trzy, nie jest jej problemem. Capability
obejmują też rzeczy, które nie są narzędziami w ogóle — dlatego `thinking` i
`clock` figurują tutaj bez żadnych narzędzi.

!!! note "API jest źródłem prawdy, ta strona jest tylko migawką"

    `GET /api/v1/agents/capabilities` zwraca rejestr w takim stanie, w jakim jest
    w działającym deploymencie, łącznie ze wszystkim, co dodano po napisaniu tej
    strony. Builder rysuje swój wybór i formularze konfiguracji z tej odpowiedzi.
    Jeśli oba źródła się różnią, rację ma API.

## Co jest dostarczane { #what-ships }

| id | Nazwa | Kategoria | Narzędzia | Zakres | Klucz |
|---|---|---|---|---|---|
| `knowledge` | Wyszukiwanie w bazie wiedzy | wiedza | `search_documents` | `knowledge:read` | — |
| `skills` | Skille | wiedza | `list_skills`, `load_skill`, `read_skill_resource` | `knowledge:read` | — |
| `context` | Kontekst | wiedza | `list_context`, `read_context` | — | — |
| `memory_files` | Pliki pamięci | wiedza | `list_memory`, `read_memory`, `write_memory`, `edit_memory`, `delete_memory` | — | — |
| `memory_mem0` | Pamięć (mem0) | wiedza | `remember`, `recall` | — | wymagany |
| `conversation_search` | Wyszukiwanie w rozmowach | wiedza | `search_conversations`, `read_conversation` | `conversations:read` | — |
| `web_research` | Wyszukiwanie w sieci | badania | `web_search` | `web:read` | dla usług płatnych |
| `web_fetch` | Pobieranie stron | badania | `web_fetch` | `web:fetch` | — |
| `browser_use` | Automatyzacja przeglądarki | badania | `browse_web` | `web:browse` | przez dodatek `browser-use` |
| `code_execution` | Uruchamianie Pythona | analiza | `run_python` | `code:execute` | — |
| `sandbox` | Pliki i powłoka | analiza | `ls`, `read_file`, `glob`, `grep`, `write_file`, `edit_file`, `execute` | `sandbox:execute` | dla Daytony |
| `charts` | Wykresy | analiza | `create_chart` | — | — |
| `image_generation` | Generowanie obrazów | analiza | `generate_image` | — | wymagany |
| `subagents` | Delegowanie | rozumowanie | `task`, `check_task`, `wait_tasks`, `list_active_tasks`, `answer_subagent`, `send_message_to_subagent`, `soft_cancel_task`, `hard_cancel_task`, `create_agent`, `delegate` | `agents:delegate` | — |
| `planning` | Planowanie | rozumowanie | `write_plan`, `read_plan`, `add_task`, `update_task_status`, `update_task_statuses`, `remove_task`, `add_subtask`, `set_dependency`, `get_available_tasks` | — | — |
| `thinking` | Myślenie | rozumowanie | brak, celowo | — | — |
| `system_reminders` | Przypomnienia systemowe | rozumowanie | brak, celowo | — | — |
| `tool_search` | Wyszukiwanie narzędzi | użytkowe | brak, celowo | — | — |
| `clock` | Data i godzina | użytkowe | brak, celowo | — | — |
| `guardrails` | Guardrails | użytkowe | brak, celowo | — | — |
| `compaction` | Zarządzanie kontekstem | użytkowe | brak, celowo | — | — |
| `tool_output_limits` | Limity wyjścia narzędzi | użytkowe | `read_tool_result` | — | — |
| `channel_tools` | Podgląd kanału czatu | kanały | `get_channel_info`, `list_channel_members`, `search_channels`, `read_channel_history` | — | — |

Sześć z nich celowo nie ma narzędzi. `thinking` zmienia sposób, w jaki model
pracuje, a nie to, do czego sięga, `clock` wstawia datę do instrukcji,
`tool_search` wnosi swoją funkcję wyszukiwania dopiero wtedy, gdy opakuje zestaw
narzędzi zawierający narzędzia odroczone — w izolacji nie deklaruje niczego —
`guardrails` bada i przepisuje tekst płynący przez run, `compaction` przepisuje
historię, którą niesie żądanie, a `system_reminders` dokleja tekst sterujący na
końcu żądania. Żadna z tej szóstki nie zostawia niczego, co człowiek mógłby
zatwierdzić, więc żadna nie deklaruje narzędzia. Capability, która naprawdę nie
ma narzędzi, mówi to przez `tools=()`, a nie przez pominięcie argumentu — zobacz
[Dodaj capability](../howto/add-capability.md).

**Ta kolumna mówi, co capability deklaruje, a to nie zawsze jest to, co dostaje
model.** Delegowanie jest jedynym miejscem, w którym jedno różni się od drugiego:
`create_agent` i `delegate` pojawiają się tylko przy `allow_dynamic`, a
`answer_subagent` nie pojawia się nikomu — oba wyjaśnione niżej w sekcji
[Delegowanie](#delegation).

**Jedna z nich w ogóle nie jest w Toolboksie.** `channel_tools` wybiera się
osobno dla każdego powiązanego bota, w sekcji *Where this agent is available*, a
publikacja odrzuca spec, który próbuje ją nieść — zobacz
[Podgląd kanału czatu](#chat-channel-lookup).

## Wyszukiwanie w bazie wiedzy { #knowledge-search }

`search_documents` — *Search the organization's documents for passages relevant to
a question.*

Przeszukuje kolekcje, które wiąże spec agenta, i cytuje to, czego użył. Model
pyta, *czego* szukać, nigdy *gdzie*: kolekcje są rozwiązywane ze speca przed
runem i przekazywane capability, więc agent nie sięgnie do kolekcji, której nikt
do niego nie podłączył.

| Konfiguracja | Domyślnie | Zakres wartości |
|---|---|---|
| `default_top_k` | 5 | 1–50 |

`default_top_k` obowiązuje tylko wtedy, gdy model sam nie poda liczby.

Powiązana bez żadnych kolekcji, ta capability nie wnosi **nic** — nie jest w
ogóle dołączana. Narzędzie wyszukiwania, które zawsze zwraca pustkę, jest gorsze
niż brak narzędzia, bo model próbuje go dalej i wyciąga wnioski z tej ciszy.

## Skille { #skills }

`list_skills`, `load_skill`, `read_skill_resource`

Spisana wiedza praktyczna, którą agent ładuje dopiero wtedy, gdy uzna ją za
istotną, po jednym skillu naraz — alternatywą jest pole instrukcji rosnące tak
długo, aż każdy run płaci za każdą procedurę. Zobacz [Skille](../skills.md), czym
jest skill i jak trafia do organizacji.

Te trzy narzędzia pochodzą z `pydantic-ai-skills`, więc ich nazwy i sformułowania
należą do kogoś innego. Test dryfu porównuje to, co deklaruje rejestr, z
narzędziami, które model faktycznie dostaje — i to on zgłosi dzień, w którym to
się stanie.

## Kontekst { #context }

`list_context`, `read_context`

Stała wiedza organizacji wstawiona do runa, zamiast czekania, aż ktoś o nią
poprosi — słownik pojęć, ton marki, macierz eskalacji. Każdy powiązany plik ma
`mode`: plik `inject` jest wklejany do instrukcji dosłownie, więc model po prostu
go zna; plik `link` zostaje poza promptem i jest osiągalny przez `read_context`,
więc duży albo rzadko potrzebny plik nic nie kosztuje, dopóki model nie uzna go
za istotny. `list_context` pokazuje, co jest dostępne, bez treści. Oba narzędzia
pojawiają się tylko wtedy, gdy powiązany jest plik w trybie `link`; agent,
którego pliki są w całości `inject`, wnosi instrukcje i żadnych narzędzi.

Wstrzykiwana treść jest obudowana jako materiał referencyjny — odgrodzona i
poprzedzona linią mówiącą modelowi, żeby traktował ją jako informację, a nie jako
instrukcje — ponieważ treść pliku pisze człowiek i dociera ona do modelu
dosłownie. To ogrodzenie działa najlepiej, jak umie, przeciwko *przypadkowemu*
wyłamaniu: treść, która sama zawiera zamykający znacznik `</context-file>` lub
`</context-files>`, albo nazwa czy format zawierające `"`, są neutralizowane, tak
by nie mogły przelać tekstu z powrotem do zaufanych instrukcji. To nie jest
granica bezpieczeństwa — posiadacz `context:edit` nadal może wstrzyknąć coś
celowo. Treść jest tekstem: dokument do przeszukiwania należy do kolekcji wiedzy,
nie tutaj.

Powiązana bez niczego użytecznego — bez plików albo wyłącznie z plikami `link`
przy wyłączonym narzędziu odczytu — ta capability nie wnosi **nic** i nie jest
dołączana, tak samo jak `knowledge` powiązane z zerem kolekcji. Plikami zarządza
się pod `/api/v1/context`, a wiąże się je z agentem po id
(`AgentSpec.context_ids`).

## Pliki pamięci { #memory-files }

`list_memory`, `read_memory`, `write_memory`, `edit_memory`, `delete_memory`

Notatki, które agent prowadzi sam dla siebie w poprzek rozmów, zindeksowane
jedną, którą sam utrzymuje. Tam gdzie `context` jest biblioteką, którą pisze
człowiek i wiąże z wieloma agentami, pamięć należy do agenta: pisze do niej
narzędziami w trakcie runa i nikt inny nie pisze tu w ogóle. Nie wiąże się jej po
id — włączenie capability daje agentowi jego notatki.

**`MEMORY.md` jest indeksem i jest pokazywany agentowi przy każdym żądaniu.** To
zwyczajna notatka, którą agent pisze i edytuje tymi samymi narzędziami co każdą
inną, a capability wkleja ją do instrukcji tak samo, jak wklejany jest powiązany
plik kontekstu. Dzięki temu agent spotyka to, co zapisał, zanim cokolwiek
postanowi, i otwiera wymienioną notatkę przez `read_memory`, gdy linijka mówi, że
warto ją przeczytać — zamiast musieć zdecydować się na wywołanie narzędzia
listującego, po które lżejszy model sięga rzadko.

### Czyje to notatki i kto może je usłyszeć { #whose-notes-and-who-may-hear-them }

Notatka należy albo do jednej osoby, albo do jednego czatu grupowego, a **run
dotyka dokładnie jednego magazynu: tego, który należy do rozmowy.** Który to,
wynika po stronie serwera z tego, kto usłyszy odpowiedź, a nigdy z modelu — więc
żadne narzędzie nie przyjmuje zakresu i agent nie ma tu czego pomylić.

- Jeden na jeden — czat webowy, HTTP API, wiadomość prywatna — notatki należą do
  tej osoby i nikt inny ich nie czyta. Ta sama osoba sięga z wszystkich trzech
  miejsc do jednego magazynu: powiązane konto czatu rozwiązuje się na jej konto,
  a nie na powierzchnię, przez którą przyszła.
- Na czacie grupowym notatki należą do czatu i czytają je wszyscy jego
  uczestnicy. Własne notatki mówiącego **nie** są tam osiągalne: tego, co
  zapisano w rozmowie w cztery oczy, nie odczytuje się na głos tam, gdzie widzi
  to cały kanał.
- Na publicznym widgecie albo w embedzie nie ma komu niczego przypisać, więc nie
  ma magazynu, a narzędzia mówią to wprost, zamiast zapisywać gdziekolwiek.

Nie ma magazynu obejmującego całą organizację. Taki istniał i został usunięty:
był drugim mechanizmem dla tego, co robią już [pliki kontekstu](../context.md) —
stałej wiedzy, którą pisze człowiek i wiąże z agentami — a jedno zadanie z dwoma
mechanizmami to sposób, w jaki oba zaczynają się nie zgadzać. Pamięć jest tym,
czego nauczył się *agent*; wszystko, co pisze człowiek, należy do kontekstu.

Jeden przełącznik, **Allow personal memory**, znosi magazyn osobowy w całości ze
względu na zgodność albo prywatność; notatki prowadzone na czatach grupowych
zostają.

### Co jest wstrzykiwane, a co tylko pobierane { #what-is-injected-and-what-is-only-fetched }

Wynik narzędzia to coś, co model waży; instrukcje to coś, czego słucha. Dlatego
indeks trafia do promptu wyłącznie tam, gdzie jego treść nie mogła sterować nikim
poza czytelnikiem: w rozmowie jeden na jeden jest wstrzykiwany, a na czacie
grupowym pozostaje osiągalny przez `read_memory` i nie jest wstrzykiwany nigdy.
Notatki pokoju nie należą do nikogo z osobna, więc zdanie jednego kolegi
docierałoby inaczej jako instrukcja drugiego kolegi w tym samym kanale.

Indeks większy niż mniej więcej 6000 znaków jest pomijany, a nie przycinany.
Połowa indeksu — urwana w środku linii, w środku nazwy pliku — jest gorsza niż
żadna.

### Jak to wymazać { #erasing-it }

Nic w konsoli nie pozwala przeglądać cudzych notatek: operator czytający, co
agent napisał o koledze, jest tą porażką, której ten projekt odmawia, i nie ma na
to ekranu. Jest za to wymazywanie. Człowiek czyści z poziomu własnego profilu
wszystko, co agent o nim pamięta, a administrator z uprawnieniem `members:manage`
może zrobić to za kogoś innego; oba działania usuwają wiersze tutaj **oraz**
odpowiadające im wspomnienia w mem0 dla każdego agenta, który to wiąże.
Wyczyszczenie całej pamięci jednego agenta jest w jego Toolboksie, obok
capability.

## Pamięć (mem0) { #memory-mem0 }

`remember`, `recall`

Pamięć semantyczna trzymana w usłudze [mem0](https://mem0.ai) — w chmurze albo
self-hosted przez `base_url` — a nie w tym deploymencie. `remember` zapisuje
krótkie, samodzielne zdanie; `recall` znajduje te, których dotyczy pytanie, po
znaczeniu, a nie po nazwie. Wymaga klucza API z vaulta organizacji.

To, do których wspomnień sięga run, podlega dokładnie regule powyżej, bo mem0
dostaje cały zakres jako swoje `user_id`: `{org}:{agent}:{owner}`. Jedno konto
mem0 nie jest więc w stanie pomieszać wspomnień dwóch organizacji, dwóch agentów
ani dwóch osób.

Dwie różnice warte poznania przed wyborem. **Nic nie jest przechowywane tutaj**,
więc wymazanie pamięci danej osoby sięga do mem0 przez jego własne API, a nie
przez wiersz, który kasujemy. Oraz: **mem0 rozlicza własne embeddingi poza
kanałem**, więc rejestr wydatków deploymentu ich nie widzi, a limit budżetu ich
nie ogranicza.

Self-hostowany `base_url` musi być https i musi znajdować się na
`MEM0_ALLOWED_HOSTS`. Pusta lista dozwolonych hostów odrzuca self-hostowane mem0
w całości i jest to celowe: klucz podróżuje w nagłówku `Authorization`, więc
twórca, który może wiązać współdzielony klucz, ale nie może go odczytać, nie może
mieć możliwości skierowania go na własny serwer.

## Wyszukiwanie w rozmowach { #conversation-search }

`search_conversations`, `read_conversation`

Znajduje dawną rozmowę po tym, co w niej **powiedziano**, i otwiera ją w całości.
Pamięć potrafi przywołać tylko to, co któraś wcześniejsza tura uznała za warte
zapisania; cała reszta została powiedziana, zapisana i — dopóki tego nie było —
nieosiągalna, więc na „co ustaliliśmy w sprawie cennika na Q3" padała odpowiedź
„nie mam tego w zapisach", w produkcie trzymającym całą tę wymianę.

`search_conversations` zwraca najlepiej pasujące wątki, każdy z tytułem, datą
ostatniej aktywności, liczbą pasujących tur i najmocniejszym fragmentem z
pogrubionymi trafionymi słowami. `read_conversation` otwiera jeden z nich jako
Markdown, podzielony na `USER:` i `AI:` w kolejności zapisu tur, z podaniem, kto
mówił, tam gdzie w pokoju jest kilka osób. Długi wątek przychodzi po jednym oknie
naraz, a odpowiedź mówi, jak poprosić o kolejne.

### Czyje rozmowy { #whose-conversations }

Jednej osoby: tej, której run odpowiada. Trzy drogi wejścia, te same trzy, na
które pozwala konsola — rozmowy, których jest właścicielem, rozmowy jej
udostępnione oraz wątki kanałowe, w których brała udział *i których nadal jest
uczestnikiem*, potwierdzone po stronie platformy czatowej. Log runów triggera
celowo nie jest wśród nich: to zapis runów wykonanych z czyjegoś innego
upoważnienia, a agent szukający w czyimś imieniu nie ma żadnego jej uprawnienia,
którym mógłby to sprawdzić.

**I tylko tam, gdzie ta osoba jest jedynym słuchaczem.** Na czacie grupowym oba
narzędzia odmawiają i mówią dlaczego: korpus jest osobisty, więc odpowiadanie z
niego w kanale odczytywałoby prywatne rozmowy jednej osoby wszystkim w pokoju. To
ta sama linia, którą rysuje indeks pamięci, tylko o warstwę dalej.

### Jak działa dopasowanie { #how-it-matches }

Pełnotekstowe wyszukiwanie PostgreSQL — `tsvector` utrzymywany przez bazę nad
każdą wiadomością, indeks GIN, `websearch_to_tsquery` dla zapytania i
`ts_rank_cd` dla kolejności. Cytowane `"exact phrases"`, `or` oraz wiodący `-`
wykluczający słowo — wszystko to działa. Nie `ILIKE`, które dopasowuje wnętrza
słów i nie umie rankingować; nie embeddingi, bo tym jest już
[wyszukiwanie w bazie wiedzy](#knowledge-search) i odpowiada ono na inne pytanie.

Słowa są dopasowywane w całości i bez rozróżniania wielkości liter, ale **bez
stemmingu**: `meeting` nie znajdzie `meetings`. Konfiguracja jest ustalona w
bazie, a `english` stemowałoby jeden język, kalecząc wszystkie pozostałe —
PostgreSQL nie dostarcza w ogóle słownika polskiego — więc równość między
językami jest kupiona za cenę form wyrazowych. Opis narzędzia to mówi, żeby
model, który nic nie znalazł, spróbował innej formy słowa, zamiast uznać, że nic
nie powiedziano.

Operator, który w ogóle nie chce, by agenci czytali rozmowy, wstrzymuje zakres
`conversations:read`, co wyłącza to w całym deploymencie. Nie ma ustawienia,
które poszerzałoby korpus.

## Wyszukiwanie w sieci { #web-search }

`web_search` — *Search the public web for current information.*

| Konfiguracja | Domyślnie | Wartości |
|---|---|---|
| `method` | `duckduckgo` | `duckduckgo`, `native`, `tavily`, `brave`, `exa` |
| `max_results` | 5 | 1–10, ignorowane przez `native` |

Konsola nazywa każdą metodę zamiast wypisywać przechowywaną wartość i rysuje obok
niej znak firmowy usługi: pole niesie `x-enum-labels`, z którego generowany
formularz czyta etykietę. Bez nich lista wyboru oferowała `duckduckgo` i `exa` w
takiej wielkości liter, w jakiej są zapisane, co czyta się jak klucz
konfiguracyjny do rozpoznania, a nie jak produkt do wybrania.

- **`duckduckgo`** — darmowe, bez konta, wyniki renderowane jako klikalne źródła.
- **`native`** — provider modelu szuka własnym indeksem i zwraca własne cytowania.
  Tylko na modelach, które to obsługują.
- **`tavily`** — wyniki streszczone pod kątem czytania przez model.
- **`brave`** — własny indeks.
- **`exa`** — wyszukiwanie po znaczeniu, a nie po słowie kluczowym.

Trzy płatne metody wymagają klucza API z [sekretów](../secrets.md) organizacji,
wskazanego przez `secret_id` powiązania. Wymóg jest warunkowy, a nie sztywny:
sztywny albo zamykałby darmową wartość domyślną za kontem, albo pozwalałby
opublikować agenta z Tavily bez niczego, czym mógłby się uwierzytelnić, i
poległby przy pierwszym wyszukiwaniu.

Zatwierdzanie i `native` nie łączą się, z powodu, który podaje niżej
[Pobieranie stron](#web-fetch): bramka [zatwierdzeń](../governance.md) opakowuje
*wykonanie narzędzia*, a natywne wyszukiwanie wykonuje provider modelu, więc
powiązanie, które wymaga zatwierdzenia dla `web_search` i ustawia `method` na
`native`, zostaje odrzucone przy publikacji, zamiast dostać bramkę, która nigdy
nie zadziała. Wybierz metodę, którą ten deployment uruchamia sam, albo zrezygnuj
z wymogu zatwierdzania.

Wyszukiwanie znajduje stronę; nie czyta jej. Czytanie to
[Pobieranie stron](#web-fetch) poniżej i jest osobną capability z osobnym
zakresem.

## Pobieranie stron { #web-fetch }

`web_fetch` — *Read the full page at a URL, as Markdown.*

| Konfiguracja | Domyślnie | Wartości |
|---|---|---|
| `method` | `local` | `local`, `native`, `auto` |
| `max_content_chars` | 50000 | 1000–200000, ignorowane przez `native` |
| `allowed_domains` | — | same nazwy hostów, które agent może pobierać; null oznacza dowolne |
| `blocked_domains` | — | same nazwy hostów, których nigdy nie może pobrać |

- **`local`** — stronę pobiera ten deployment. Domyślne, bo to jedyna metoda,
  która zachowuje się identycznie na każdym modelu.
- **`native`** — pobiera ją provider modelu, własnym ruchem wychodzącym i z
  własnymi cytowaniami. Tylko na modelach, które to obsługują; na pozostałych
  Pydantic AI rzuca wyjątek.
- **`auto`** — natywnie tam, gdzie model to ma, `local` wszędzie indziej. Zawsze
  oferowana jest dokładnie jedna z dwóch, więc run nie może wybierać między nimi
  per wywołanie.

Samo pobranie to `web_fetch_tool` z Pydantic AI, oparte na chronionym przed SSRF
`safe_download`, i to jest powód, dla którego nie jest to nasz kod.

URL pochodzi od **modelu** i jest rozwiązywany z wnętrza kontenera, więc
walidowanie go z góry — tak jak robi to `app.core.sanitize.validate_webhook_url`
dla callbacku, który ktoś nam podał — samo w sobie nie wystarcza. `httpx`
rozwiązuje nazwę hosta po raz drugi i podąża za przekierowaniami, nie pytając
ponownie, więc nazwa, która chwilę temu odpowiadała publicznie, może teraz
odpowiadać `169.254.169.254`, a publiczny URL może przekierować na taki adres.

`safe_download` przypina rozwiązany adres do żądania i waliduje ponownie każdy
przeskok, wraz z filtrami domen. Ogranicza też treść w trakcie strumieniowania i
odrzuca te kodowania kompresji, których w ten sposób ograniczyć się nie da.

Adresy prywatne, pętli zwrotnej, link-local i metadanych chmurowych są odrzucane,
a odmowa dociera do modelu jako błąd do ponowienia, a nie jako pusta strona —
odmowa w kształcie wyniku to taka, którą model obchodzi w odpowiedzi, nie mówiąc,
że musiał. Bibliotece można kazać dopuszczać adresy lokalne; nic tutaj tego nie
wystawia.

!!! warning "Filtry domen nie są granicą bezpieczeństwa — jest nią `safe_download`"

    Dopasowują nazwę hosta dokładnie, bez symboli wieloznacznych i bez domyślnych
    subdomen, więc odpowiadają na pytanie *które strony ten agent może czytać*, a
    nie *czy ten agent może sięgnąć do naszej sieci*.

Wpis, który nigdy nie mógłby się dopasować, zostaje odrzucony przy publikacji:
symbol wieloznaczny, schemat, ścieżka, port albo pusta **lista dozwolonych**.
Każdy z nich zostawiłby po cichu listę zablokowanych, która nic nie blokuje, albo
listę dozwolonych, która po cichu blokuje wszystko.

Pusta lista *zablokowanych* nie blokuje niczego, co znaczy dokładnie tyle samo, co
pozostawienie jej nieustawioną, więc jest czytana jako nieustawiona, a nie
odrzucana — zaimportowany spec, który zapisuje „brak zablokowanych hostów" jako
`[]`, mówi coś prawdziwego.

Wpis, który *może* się dopasować, jest zapisywany w jedynej pisowni, o jaką
zapytany byłby DNS: małymi literami, bez końcowej etykiety korzenia, zakodowany
w IDNA. Nazwa ma więcej niż jedną pisownię, a dokładne dopasowanie do jednej z
nich to filtr z dziurą — `https://exämple.com/` dociera do porównania tak, jak
zostało wpisane, więc lista zablokowanych zawierająca tylko
`xn--exmple-cua.com` przepuściłaby to, podczas gdy `getaddrinfo` rozwiązuje obie
identycznie. Każda równoważna pisownia trafia do filtra w momencie budowania;
spec przechowuje jedną.

!!! warning "Zatwierdzanie i `native` nie łączą się"

    Bramka [zatwierdzeń](../governance.md) opakowuje *wykonanie narzędzia*, czyli
    jedyne miejsce, w którym wywołanie da się wstrzymać — więc pobranie, które
    provider modelu wykonuje po swojej stronie, nigdy do niej nie dociera.

Powiązanie, które wymaga zatwierdzenia dla `web_fetch` i ustawia `method` na
`native` — albo na `auto`, gdzie to, która z dwóch metod działa, jest własnością
profilu modelu i zmienia się bez ponownej publikacji — **zostaje odrzucone przy
publikacji**, zamiast dostać bramkę, która po cichu nigdy nie zadziała.

Ustaw `method` na `local` albo zrezygnuj z wymogu zatwierdzania. Oba są
uprawnionymi agentami, a to, którego z nich się chce, nie jest decyzją do podjęcia
za autora.

Wersja opublikowana, zanim ta odmowa zaczęła istnieć, zostaje odrzucona ponownie
w momencie składania, bo nic nie waliduje zamrożonej wersji na nowo. Taki agent
przestaje więc działać, dopóki nie zostanie poprawiony, zamiast pobierać dalej bez
zatwierdzeń.

Strona przychodzi jako Markdown, przycięta na `max_content_chars`; PDF albo obraz
przychodzą jako treść binarna, którą model czyta natywnie. Nic tego nie streszcza
— to, co zrobić ze stroną, należy do instrukcji agenta.

## Automatyzacja przeglądarki { #browser-automation }

`browse_web` — *Delegate an open-ended web task to an autonomous browser agent.*

Jeden cel w języku naturalnym, przekazany agentowi
[browser-use](https://github.com/browser-use/browser-use), który steruje prawdziwym
Chromium — nawiguje, czyta, klika, wyciąga dane — i zwraca wynik tekstowy. Sięgaj
po to, gdy układ strony jest nieznany albo zadanie wymaga oceny, a nie do
skryptowego przepływu, który załatwiłoby zwykłe żądanie.

To największa powierzchnia ataku, jaką otwiera capability: przeglądarka robi to,
co każe jej strona, strona jest niezaufana, więc `browse_web` zamienia treść z
sieci w narzędzie ze skutkami ubocznymi. Z tego powodu jest **`side_effecting` i
da się je bramkować** — postaw je za [zatwierdzeniem](../governance.md), a
wstrzyknięta strona trafi do człowieka, a nie do działania.

| Konfiguracja | Domyślnie | Wartości |
|---|---|---|
| `mode` | `playwright` | `playwright`, `remote` |
| `cdp_url` | null | punkt końcowy Chromium DevTools; wymagany przy `remote` (i tylko tam dozwolony) |
| `allowed_domains` | null | domeny, do których agent może sięgać; wzorce w rodzaju `*.example.com` dozwolone; null oznacza brak ograniczeń |
| `max_steps` | 25 | 1–100; każdy krok to jedno żądanie do modelu |
| `use_vision` | `true` | wysyłaj zrzuty strony do modelu agenta przeglądarkowego |
| `headless` | `true` | uruchamiaj lokalnie startowaną przeglądarkę bez okna (tylko `playwright`) |

**`mode` decyduje, gdzie działa przeglądarka.** `playwright` uruchamia bezgłowe
Chromium obok agenta; `remote` podłącza się przez CDP do przeglądarki, którą
operator uruchamia gdzie indziej. Deployment self-hosted kieruje `remote` na
utwardzoną, odizolowaną usługę przeglądarkową, zamiast dawać procesowi przeglądarki
miejsce w kontenerze aplikacji. `cdp_url` przy `remote` to URL, z którym ten
deployment łączy się po stronie serwera, więc jest sprawdzany pod kątem SSRF —
adres pętli zwrotnej, prywatny, zarezerwowany albo metadanych zostaje odrzucony
**przy publikacji**, w momencie zapisu speca, a nie przy każdym runie (sprawdzenie
rozwiązuje DNS, co nie może blokować pętli zdarzeń, na której składany jest run).

**Wydatki modelu agenta przeglądarkowego są mierzone.** Podagent działa na modelu
runa nadrzędnego — tym, którego poświadczenie zostało rozwiązane z vaulta — a każdy
jego krok to jedno żądanie do modelu, księgowane w budżecie runa przez ten sam
rejestr zużycia otoczkowego, z którego korzysta streszczenie kompaktujące. To nie
jest własny hostowany model browser-use i nie są to wydatki niewidoczne dla
strażnika budżetu.

**`browser-use` jest dodatkiem opcjonalnym.** Ciągnie za sobą ciężkie drzewo
zależności (Chromium przez Playwright) i przypina zależności o wersję niższą niż
reszta platformy, więc nie jest instalowany domyślnie. Operator, który chce tę
capability, instaluje `agenticos[browser-use]` i dostarcza Chromium; powiązany
agent, którego deployment tego nie ma, głośno zawodzi na tym jednym narzędziu,
podając polecenie instalacji.

## Uruchamianie Pythona { #run-python }

`run_python` — *Run a small Python program to compute something.*

Ograniczony sandbox bez sieci i bez systemu plików, dlatego czas i pamięć są
jedynymi limitami wartymi ustawienia.

| Konfiguracja | Domyślnie | Zakres wartości |
|---|---|---|
| `timeout_secs` | 10 | > 0, ≤ 120 |
| `max_memory_mb` | 256 | 16–4096 |

!!! info "Na agenta, nie na deployment"

    Autor podnoszący limit dla jednego agenta przetwarzającego dużo danych nie
    powinien potrzebować operatora ani ponownego wdrożenia — a górne granice są
    ograniczone, a nie otwarte.

## Pliki i powłoka { #files-shell }

`ls`, `read_file`, `glob`, `grep` — *odczyt.*
`write_file`, `edit_file`, `execute` — *zapis i uruchamianie.*

Workspace, który przeżywa między turami. `code_execution` liczy i zapomina; ten
pamięta, a na backendzie opartym na kontenerze ma prawdziwą powłokę. Agent, któremu
przyznano oba, liczy jednym i trzyma pracę w drugim — to normalne połączenie na
backendzie `state`, bo ten nie ma powłoki w ogóle.

| Konfiguracja | Domyślnie | Wartości |
|---|---|---|
| `backend` | `state` | `state`, `service` |
| `connection_id` | null | zarejestrowane połączenie sandboksa; null bierze domyślne połączenie organizacji. Tylko `service` |
| `session_scope` | `conversation` | `run`, `conversation`, `channel`, `user`, `agent` |
| `runtime` | null | alias, na który pozwala usługa tego połączenia; tylko `service` |
| `include_execute` | `true` | wyłączone, usuwa powłokę całkowicie, zamiast ją bramkować |

Nie ma backendu `docker` ani `daytona` do wyboru. *Gdzie* działa sandbox, jest
własnością połączenia, które zarejestrował operator — Sandboxes w aplikacji — więc
wskazanie połączenia jest wskazaniem rodzaju. Wybieranie ich osobno pozwalało
wybrać dwie rzeczy, które się ze sobą nie zgadzają.

**`backend` to infrastruktura; `session_scope` to polityka współdzielenia danych.**
Pomyłka w pierwszym kosztuje funkcję. Pomyłka w drugim pokazuje jednej osobie pliki
drugiej, więc warto przeczytać to dwa razy:

| Zakres | Kto współdzieli workspace |
|---|---|
| `run` | Nikt — świeży przy każdej turze |
| `conversation` | Wszyscy na tym czacie. Na Slacku wątek *jest* czatem, więc wątki nie współdzielą |
| `channel` | Każdy wątek w jednym kanale. Wiadomość prywatna ma własne id czatu, więc ludzie nadal mają swoje |
| `user` | Jedna osoba, na każdej powierzchni, z której sięga po tego agenta |
| `agent` | **Wszyscy, którzy rozmawiają z tym agentem**, w całej organizacji |

`conversation` i `channel` istnieją jako osobne odpowiedzi, bo platforma czatowa
czyni z nich różne rzeczy. `SlackAdapter` wplata `thread_ts` w id czatu, więc
`conversation` na Slacku oznacza jeden workspace na wątek — pięćdziesiąt wątków w
ruchliwym kanale to pięćdziesiąt kontenerów i `429` dla pięćdziesiątej pierwszej
osoby, która odpowie.

Zakres w specu jest **domyślny**. Każdy kanał, na którym agent jest opublikowany,
może go nadpisać na swojej ekspozycji: agent osiągalny w czacie webowym i przez
bota na Slacku to jeden agent w dwóch sytuacjach, a jedna wartość dla obu była
złym kształtem. To zakres `user` przenosi workspace między powierzchniami — ta sama
osoba podejmująca na Slacku rozmowę zaczętą w czacie webowym znajduje tam swoje
pliki.

`agent` jest tym zakresem, który przekracza granicę między ludźmi. Builder ostrzega
przy tym polu, panel plików podpisuje, czyj to workspace, zamiast nazywać go
„plikami tej rozmowy", a ustawienie go jest zapisywane w logu audytu — bo
użytkownik, który widzi plik, którego nie stworzył, powinien móc się dowiedzieć
dlaczego.

**Zmiana backendu albo połączenia zaczyna świeży workspace, a nie podłącza się
ponownie do starego.** Zapisany dokument, wolumen kontenera i sandbox Daytony to
trzy różne rzeczy, a dwie instalacje `sandboxd` to dwie różne rzeczy — więc każda
dostaje własny workspace, a poprzedni zostaje tam, gdzie był, nadal wypisywany i
nadal do odczytu. Przenoszenie żywego agenta nie jest więc sposobem na przeniesienie
jego plików; agent zastaje na nowym hoście pusty workspace. Ponieważ
`connection_id: null` oznacza „domyślne połączenie organizacji", oznaczenie innego
połączenia jako domyślnego daje ten sam efekt bez zmiany jakiegokolwiek speca.

Spec wybiera połączenie i nigdy nie wybiera obrazu, montowania, trybu sieci ani
górnego limitu. Te należą do tego, kto prowadzi deployment: spec jest pisany w
przeglądarce przez każdego, kto ma `edit` na agencie, a taki, który mógłby wskazać
obraz kontenera, mógłby wskazać obraz, którego entrypoint montuje hosta. `runtime`
jest aliasem, a Builder oferuje tylko te aliasy, które zgłasza usługa tego
połączenia — odczytane na żywo, bo zapisana kopia oferowałaby taki, na który usługa
już nie pozwala.

Co kosztuje uruchomienie każdego z backendów:

| Backend | Wymaga | Powłoka | Gdzie leżą pliki |
|---|---|---|---|
| `state` | niczego | nie | ta baza danych, z limitem `SANDBOX_STATE_MAX_BYTES` |
| `service` | zarejestrowanego połączenia | tak | kontener na tym hoście albo chmura Daytony na własnym koncie organizacji |

Operator widzi, co działa: Sandboxes wypisuje otwarte sandboksy tej organizacji na
jej domyślnym hoście wraz z ich runtime'ami, czasem bezczynności i pamięcią, oraz
log aktywności każdego sandboksa. Zobacz
[Konfiguracja](../configuration.md#agent-workspaces).

Publikacja zostaje odrzucona dla workspace'u `service`, gdy organizacja nie
zarejestrowała żadnego połączenia, gdy to, które jest wskazane, zniknęło, albo gdy
to połączenie nie ma poświadczenia — każdy przypadek z nazwy, bo wszystkie trzy to
stany, do których deployment dochodzi *po* opublikowaniu agenta i naprawa należy do
operatora, a nie do autora.

**Pyta tylko `execute`.** Skutki uboczne deklaruje się per narzędzie, a z siedmiu
tylko uruchomienie polecenia je ma: workspace to brudnopis usuwany razem z rozmową,
do której należy, więc zapisanie w nim pliku nie jest tą klasą czynu co wysłanie
maila — a agent, który musi pytać przed każdym `write_file`, nie jest w stanie
wykonać pracy wieloetapowej w ogóle, i tak właśnie autor kończy z bramką wyłączoną
w całości, tracąc tę jedną, która miała znaczenie. `execute` uruchamia dowolne
polecenia na czyimś hoście.

Powiązanie, które chce surowszego zachowania, ustawia je per narzędzie:
`tool_approval: {"write_file": "required"}`. Zobacz
[Nadzór](../governance.md), jak zatwierdzenie trafia do człowieka — i jakie dwie
rzeczy potrafi powiedzieć jedna *sesja czatu* ponad to, co mówi spec: odpuść każde
bramkowane wywołanie w tej rozmowie albo pytaj o każde narzędzie, jakie agent ma,
łącznie z narzędziami MCP, których bramka sterowana specem celowo nie dotyka
(agenticos#925).

**Niektóre ścieżki są odrzucane niezależnie od tego, co mówi polityka
zatwierdzeń.** Poświadczenia (`**/.env`, `**/*.pem`, `**/*.key`, `**/credentials*`,
`**/.ssh/**`, `**/.aws/**`) oraz drzewo systemowe (`/etc/**`, `/usr/**`, `/proc/**`
i ich odpowiedniki) nie mogą być czytane, zapisywane ani edytowane — agent dostaje
czytelną odmowę i może pracować dalej. `grep` jest filtrowany, a nie odrzucany, bo
wzorzec nad `/` w sposób uprawniony obejmuje workspace: trafienia wewnątrz pliku
poza zasięgiem są odrzucane, więc wyszukiwanie nie zwróci z niego żadnej linii.
Nazwy nie są tajemnicą, więc `ls` i `glob` nadal pokazują, co tam jest;
wstrzymywana jest tylko zawartość.

Polecenie, które *wymienia* którąś z tych ścieżek, również zostaje odrzucone, więc
`cat /etc/shadow` nie obchodzi reguły, pytając innym narzędziem. To obrona w głąb,
a nie granica, i ta różnica ma znaczenie: powłoka sięga do pliku na sposoby, których
inspekcja napisów nie zobaczy, więc tym, co naprawdę czyni wykonywanie bezpiecznym,
jest izolacja kontenera i tryb sieci ustawiony przez operatora. Nie ma listy
dozwolonych ciągów poleceń, bo taką pokonuje `sh -c`.

I nic z tego nie zastępuje bramki zatwierdzeń: odmowa tutaj jest płaskim „nie"
kodu, podczas gdy `execute` pytające człowieka jest decyzją, która należy do
operatora.

Pliki, które ktoś dołącza do wiadomości, lądują w `/uploads` — zobacz
[Przetwarzanie plików](../file-processing.md).

**Skille też stają się plikami.** Agent mający i workspace, i skille dostaje każdy
skill jako `/skills/<name>/SKILL.md` z jego zasobami obok, i to właśnie czyni
skrypt skilla w ogóle uruchamialnym: leży na dysku obok powłoki, która potrafi go
uruchomić. Celowo nie ma `run_skill_script` — `execute` ma już za sobą bramkę
zatwierdzeń i górne limity operatora, a druga ścieżka wykonywania byłaby drugim
zestawem reguł do pomylenia.

Te pliki są zapisywalne, a to, co agent zapisze, **nie** staje się skillem. Skill
to instrukcje, za którymi idzie każdy powiązany z nim agent przy każdym runie, więc
zmiana jest zapisywana jako propozycja, a ktoś z `skills:edit` ją przyjmuje albo
odrzuca — zobacz [Skille](../skills.md).

## Wykresy { #charts }

`create_chart` — *Draw a chart of numbers you already have, so the user can see
them.*

Rysuje liczby, które model już ma. Nie pobiera, nie liczy i nie agreguje — do tego
połącz je z `code_execution` albo `knowledge`. Bez konfiguracji.

Liczby przychodzą jako **kolumny** — jedna lista `x_values` na oś, jedna lista
`values` na serię — bo dowolnego argumentu `data` nie da się opisać schematem JSON,
a model, któremu podano tablicę obiektów bez zadeklarowanych właściwości, odesłał
jeden pusty obiekt.

Wykresu, w którym nic nie ma, nie da się już wyrazić, zamiast go jedynie odrzucać.
Oś bez punktów, wykres bez serii albo seria zawierająca mniej liczb, niż oś ma
punktów, wracają jako prośba o ponowienie, wskazująca, czego brakuje.

Ramka narysowana wokół braku danych czyta się jak „nie ma trendu", a nie jak
pomyłka — a do tego jest zapisywana i rysowana ponownie przy każdym odtworzeniu
rozmowy.

## Generowanie obrazów { #image-generation }

`generate_image` — *Generate an image from a written description.*

Rysuje obraz dedykowanym modelem graficznym — osobnym od modelu samego agenta —
więc działa niezależnie od tego, na jakim modelu agent chodzi. `create_chart`
kreśli liczby; to rysuje obrazki.

| Konfiguracja | Domyślnie | Wartości |
|---|---|---|
| `provider` | `openai` | Providerzy, których klasa modelu honoruje narzędzie graficzne *i* przyjmuje klucz API — dziś dwaj |
| `model` | `gpt-image-2` | Modele tego providera, z `app/core/catalog/image_models.json` |
| `quality` | domyślne providera | `low`, `medium`, `high`, `auto` |
| `size` | domyślne providera | `auto`, `1024x1024`, `1024x1536`, `1536x1024`, `512`, `1K`, `2K`, `4K` |
| `background` | domyślne providera | `transparent`, `opaque`, `auto` |
| `output_format` | domyślne providera | `png`, `webp`, `jpeg` |
| `aspect_ratio` | domyślne providera | `16:9`, `1:1`, `9:16`, … |

**To, którzy providerzy potrafią rysować, jest odpowiedzią SDK, a nie listą.**
`Model.supported_native_tools()` to metoda klasowa na każdej klasie modelu, jaką
dostarcza Pydantic AI, więc platforma o to pyta: `OpenAIResponsesModel`,
`GoogleModel` i `GoogleModel` przez Vertex honorują `ImageGenerationTool`, nikt
inny nie, a aktualizacja, która nauczy tego czwartego, nie wymaga tu żadnego kodu.
Modele graficzne Together i Fireworks istnieją naprawdę i poległyby przy pierwszym
wywołaniu z „not supported by this model", i dlatego nie są oferowane.

**Umieć rysować i dać się skonfigurować to dwa różne pytania**, a Vertex AI jest
miejscem, w którym te pytania się rozchodzą. Ta capability pieczętuje jeden klucz
API i buduje nim każdego providera, a Vertex chce konta serwisowego — więc wpis
Vertex byłby pozycją w liście wyboru, do której nikt nie umie dostarczyć
poświadczenia, i odpada razem z tymi, które nie rysują. Zaoferowanie go oznacza
nauczenie capability kształtów poświadczeń specyficznych dla providera, co jest
zmianą w capability, a nie w katalogu.

**To, jakie modele oferuje każdy provider, jest danymi**, w
`app/core/catalog/image_models.json`: id, nazwa i zdanie mówiące, kiedy po ten
model sięgnąć. Żaden endpoint listujący na to pytanie nie odpowiada — `/v1/models`
zwraca modele czatowe — więc model wydany dziś rano to jeden wpis w katalogu, a nie
wydanie. Wpis providera, którego SDK nie potrafi obsłużyć, albo takiego, dla
którego ta capability nie zbuduje poświadczenia, jest pomijany przy odczycie pliku
— to zabezpieczenie przed tym, by nie urósł w nim ktoś, kto nie rysuje albo nie da
się skonfigurować.

Obaj providerzy nazywają model graficzny w innym miejscu i katalog niesie też tę
różnicę. Dla **Google** wybrany model *jest* modelem graficznym. Dla **OpenAI**
narzędzie wywołuje model Responses i rysuje wybranym modelem, więc wpis nazywa tego
wywołującego, a wybór podróżuje jako własne `model` narzędzia. Żadne z tego nie
jest pytaniem zadawanym autorowi.

**Spec opublikowany, zanim ta para istniała, nadal działa.** Kiedyś był to jeden
wyliczeniowy napis niosący prefiks SDK (`openai-responses:gpt-5.4`) i zapisany spec
nadal go trzyma. Czytany przez pryzmat dwóch pól jest to model nieznany, więc
konfiguracja normalizuje stary kształt na wejściu: prefiks nazywa providera, a
nazwa, która jest *wywołującym*, a nie modelem rysującym, rozwiązuje się na
pierwszy model graficzny tego providera. Tylko tam, gdzie nie zapisano `provider` —
powiązanie, które go nazywa, podaje obie połowy.

`model` decyduje też o tym, do którego providera należy klucz API. Klucz jest
wymagany — publikacja agenta, który wiąże to bez klucza, zostaje odrzucona — i
pochodzi z [sekretów](../secrets.md) organizacji, wskazany przez `secret_id`
powiązania. Każde inne ustawienie jest opcjonalne; nieustawione, provider stosuje
własną wartość domyślną, więc samo włączenie capability wystarczy, by generować.

**Wywołuje skutki uboczne.** Narysowanie obrazu wydaje prawdziwe pieniądze z
klucza providera i produkuje treść, którą człowiek może opublikować, więc każde
wywołanie jest kandydatem do [bramki zatwierdzeń](../governance.md) i da się je
bramkować per powiązanie.

**Jego wydatki są mierzone.** Model graficzny działa jako podagent, którego zużycie
księgowane jest w rejestrze runa, więc koszt obrazu liczy się do budżetu tak samo
jak żądanie do modelu. Modele graficzne często nie mają ceny w migawce cennikowej i
wtedy run zapisuje wywołanie po zerze i oznacza swoją sumę jako częściową
(`cost_is_partial`), zamiast ukrywać ten wydatek.

**Gdzie trafia obraz.** Każdy wygenerowany obraz jest przechowywany **per
organizacja** i zwracany przez
[`GET /api/v1/generated/{filename}`](../architecture.md), zawężony do organizacji
wywołującego — szersza granica niż przy pliku wrzuconym na czacie, który należy do
jednego użytkownika, bo nie ma zapisu o tym, kto obraz wyprodukował. Gdy agent ma
też workspace (capability `sandbox`), ten sam obraz jest zapisywany w nim pod
`/output`, żeby późniejszy krok `execute` mógł coś z niego zbudować — złożyć PDF,
slajd, stronę. Agent bez workspace'u nadal generuje i pokazuje obrazy; po prostu
nie ma gdzie niczego z nich zbudować.

## Delegowanie { #delegation }

`task` — *hand a self-contained piece of work to one of this agent's specialists.*
`check_task`, `wait_tasks`, `list_active_tasks` — *following one that is running.*
`send_message_to_subagent`, `soft_cancel_task`, `hard_cancel_task` — *steering or
stopping one.* Tych sześć jest oferowanych tylko wtedy, gdy osiągalne jest
delegowanie w tle — agent wyłącznie `sync` nie dostaje żadnego z nich.
`create_agent`, `delegate` — *a specialist the model writes for itself, when the author allows it.*
`answer_subagent` — *declared, and offered to no model.*

Jeden agent oddający część roboty drugiemu, każdy na własnym modelu, z własną
wiedzą i własnym limitem kroków, adresowany po nazwie. Są dwa kształty delegata, a
różnica decyduje o tym, jak się je recenzuje, wersjonuje i rozlicza — wyjaśnia to
[Koncepcje](../concepts.md#delegate-vs-inline-specialist). To, do których
*opublikowanych* agentów ten może delegować, nie jest w tej konfiguracji: to
`subagents` na najwyższym poziomie speca, gdzie widzą to walidacja publikacji,
eksport do YAML i model uprawnień.

| Konfiguracja | Domyślnie | Zakres wartości |
|---|---|---|
| `inline` | brak | specjaliści zdefiniowani wewnątrz tego agenta |
| `mode` | `sync` | `sync`, `async`, `auto` |
| `allow_questions` | `false` | delegat sync może zapytać człowieka rodzica |
| `allow_dynamic` | `false` | |
| `max_depth` | 1 | 1–3 |
| `max_fanout` | 3 | 1–10 |
| `max_result_chars` | 2000 | 200–20000 |
| `share_with_delegates` | brak | id capability, które ten agent sam wiąże, z wyjątkiem `subagents` |

**Tryb jest decyzją autora, nie modelu.**

Narzędzie `task` z biblioteki przyjmuje argument `mode` domyślnie równy `sync`,
więc „model postanowił poczekać" i „model nic nie powiedział" to to samo wywołanie.
Nie ma sposobu, by uszanować jednocześnie ustawienie i wybór, a ustawienie
przeszło recenzję.

Dlatego argument jest po drodze podmieniany, a `auto` jest sposobem, w jaki autor
świadomie oddaje tę decyzję. `auto` rozstrzyga się *przed* startem delegowania, bo
od odpowiedzi zależy, czy panel zostaje otwarty po tym, jak rodzic już odpowiedział.

Przypięty delegat albo specjalista może nadpisać tryb dla siebie — jeden wolny
researcher to przypadek, który warto puścić w tle. Instrukcje **oznaczają wtedy
tego delegata**, obok jego nazwy: jedno zdanie stwierdzające skonfigurowany tryb
było obietnicą, którą nadpisujący delegat następnie łamał, każąc modelowi czekać na
odpowiedź i podając mu id zadania.

**Agent wyłącznie `sync` nie dostaje żadnego z sześciu narzędzi cyklu życia
zadania.** Każde z `check_task`, `wait_tasks`, `list_active_tasks`,
`send_message_to_subagent` i dwóch anulowań przyjmuje id zadania albo o nim
raportuje, a delegowanie `sync` zwraca odpowiedź i nic więcej — nie ma id do
przekazania. Są więc oferowane tylko wtedy, gdy delegowanie w tle jest osiągalne:
tryb `async` albo `auto`, delegat, który woli jedno z nich, albo pozwolenie na
wymyślanie specjalistów. `sync` jest domyślny, więc jest to konfiguracja
najczęstsza, a sześć wstrzymanych opisów narzędzi to sześć, za które model już nie
płaci w każdej turze. `task` zostaje — agent `sync` nadal deleguje.

**Rozgałęzienie i zagnieżdżenie to pułapy, a nie błędy.**

Powyżej `max_fanout` kolejne delegowanie wraca jako wynik narzędzia, na który model
może zareagować — poczekać albo zrobić robotę sam — bo limit tempa nie powinien
kończyć runa.

`max_depth` liczy poziomy delegowania **wliczając własny poziom skonfigurowanego
agenta**: 1 oznacza, że ten agent deleguje, a jego delegaci już nie; 2 pozwala na
jeden poziom zagnieżdżenia.

Na granicy delegat jest budowany *bez* capability delegowania, a nie z taką, która
może tylko odmówić. Narzędzie, które zawsze odpowiada „brak dostępnych delegatów",
to opis, za który model płaci w każdej turze i tak czy inaczej próbuje.

Celowo nie ma zera. Wyłączenie delegowania to wyłączenie powiązania, a druga
pisownia tego samego przełącznika to taka, która nie zgadza się z pierwszą.

**A każdy agent w drzewie podlega własnemu `max_depth`, nie korzeniowemu.** Delegat
dostaje *niższą* z dwóch wartości: tego, co zostało drzewu, i tego, na co pozwala
jego własny spec — więc korzeń skonfigurowany na trzy poziomy, delegujący do
agenta, którego autor wybrał 1, dostaje jeden: ten delegat deleguje, a jego
delegaci już nie, dokładnie tak, jak czytali to jego właśni recenzenci. Pułap,
który wywołujący mógłby poszerzyć, nie byłby pułapem, a powodem, by przypiąć
delegata do wersji, jest to, że decyzje jego autora obowiązują, gdy woła go ktoś
inny.

**Delegowanie sync może się zatrzymać, żeby o coś zapytać człowieka, i jest
wznawiane w miejscu.** Bramkowane narzędzie w jego wnętrzu parkuje cały run;
zatwierdzenie wznawia tego delegata od miejsca, w którym stanął, zamiast delegować
ponownie, i to właśnie sprawia, że zatwierdzenie dotyczy tego wywołania, które
recenzent naprawdę widział. [Nadzór](../governance.md) ma kształt zapisanego stanu
i powód, dla którego ponowny przebieg odpowiedziałby inaczej.

**Delegowanie w tle nie może się zatrzymać, żeby o coś zapytać człowieka.**

Bramkowane narzędzie w jego wnętrzu zostaje odrzucone, a nie zaparkowane, a odmowa
mówi modelowi, żeby oddelegował tę pracę z `mode="sync"`.

Powodem nie jest polityka, lecz **czas życia**. Kanał zatwierdzeń domyka się na
sesji bazodanowej żądania, a delegowanie w tle przeżywa wywołanie narzędzia, które
je uruchomiło — więc w chwili, gdy chciało zapytać, nie ma już czym zapisać
pytania.

Delegowanie w tle, które mimo wszystko się zawiesza — kształt, który biblioteka
dokumentuje jako niedostarczalny — zostaje zapisane jako `failed` z tym samym
komunikatem. Alternatywą jest zadanie raportujące „wciąż działa" tak długo, jak
żyje proces: z wydatkami przypisanymi do niczego, z nigdy niezwolnionym miejscem w
rozgałęzieniu i z panelem, który powierzchnia otworzyła i nigdy nie zamknęła.

**Delegat sync może zapytać człowieka rodzica, gdy ustawione jest
`allow_questions`.**

Domyślnie wyłączone: specjalista pracuje samodzielnie i mówi, jeśli mu się nie
udało.

Włączone, delegat, którego tryb to sync, dostaje biblioteczne narzędzie
`ask_parent`, a na zadane przez niego pytanie odpowiada własny kanał `ask_user`
runa — człowiek, który już trzyma wywołanie narzędzia rodzica — a nigdy model.

To decyzja autora, bo pytanie nosi nazwę, którą autor opublikował. Specjalista,
którego model *wymyśla*, nie pyta nigdy, cokolwiek by to ustawienie mówiło:
instrukcje napisane przez model chwilę temu nie są tym, co autor stawia przed
człowiekiem.

Tylko sync. Delegowanie w tle oddało id zadania i nie zostało nikogo, kto mógłby
odpowiedzieć, a `auto` może się takim stać.

Sięgnięcie po gotowego delegata wymagało zmiany u źródła.
[subagents-pydantic-ai#76](https://github.com/vstorm-co/subagents-pydantic-ai/pull/76)
honoruje `can_ask_questions` dla agenta podanego przez wywołującego, czyli dla
każdego delegata tutaj — co domyka połowę sync z
[#184](https://github.com/vstorm-co/agenticos/issues/184).

**`answer_subagent` nie jest oferowane żadnemu modelowi.**

Odpowiada ono na pytanie, na którym zaparkował delegat *w tle*, a żaden delegat tu
na takim nie parkuje: pytanie sync idzie do człowieka przez `ask_user` i nigdy
przez to narzędzie, a delegat async nie dostaje `ask_parent` w ogóle. Jedyną możliwą
odpowiedzią tego narzędzia jest więc „to delegowanie nie czeka na odpowiedź".

Pozostaje **zadeklarowane**, bo narzędzia nieobecnego w deklaracji nie da się
zabramkować polityką zatwierdzeń ani przemianować przez powiązanie, a ta połowa
porażki jest cicha.

Jest **odfiltrowywane z zestawu oferowanego**, bo druga połowa to opis w kontekście
każdej tury, opisujący działanie, które nie może się wydarzyć — a opisy narzędzi są
najmocniejszym promptem w tym produkcie.

Narzędzie stanie się osiągalne dopiero wtedy, gdy odpowiedziana zostanie tłowa
połowa [#184](https://github.com/vstorm-co/agenticos/issues/184): tam, gdzie własny
model rodzica odpowiada, choć nic nie zmusza go, by zajrzał, a delegat blokuje się
na miejscu w rozgałęzieniu, które koniec tury anuluje.

**`wait_tasks` przycina i mówi o tym.** Wynik ukończonego zadania jest ucinany na
`max_result_chars` z wyraźnym znacznikiem wskazującym `check_task`, które zawsze
zwraca pełny tekst. To znacznik jest tu połową nośną: ciche ucięcie czyta się jak
krótka odpowiedź, a orkiestrator, któremu podano połowę raportu, deleguje ponownie
pracę, którą już ma.

**Wyłączenie delegowania to wyłączenie powiązania, a nie obniżenie liczby.**
Wyłączone powiązanie nie jest delegowaniem: nic nie jest budowane, więc nic nie
czyta przypięć ani specjalistów, których niesie — a publikacja zostaje wtedy
odrzucona dla agenta, który nadal nazywa delegatów, bo przypięcie, którego nic
nigdy nie zawoła, jest linią konfiguracji czytającą się jak decyzja i nierobiącą
nic.

**Powiązana bez żadnych delegatów, ta capability nie wnosi nic** — nie jest
dołączana, tak samo jak `knowledge` nie jest dołączane bez kolekcji. Dziesięć
narzędzi, które mogą tylko odmówić, to dziesięć narzędzi w kontekście każdej tury.

**O zatwierdzenie proszą tylko te trzy, które działają:**
`send_message_to_subagent`, `soft_cancel_task` i `hard_cancel_task`. Sterowanie
zmienia to, co delegat robi w trakcie runa, a każde z anulowań niszczy pracę, która
została opłacona i niedostarczona. `task` celowo nie wywołuje skutków ubocznych, co
przez chwilę czyta się źle: to, co delegat *robi*, jest bramkowane jego własnym
specem, przez tę samą bramkę zatwierdzeń, której używa ten run — więc bramkowanie
także samego delegowania kazałoby komuś zatwierdzać je, zanim praca, która może
wymagać zatwierdzenia, zostanie w ogóle zaproponowana. Autor, który tego chce, ma
jedno nadpisanie `tool_approval`.

**Delegat nie dostaje w pożyczkę capability rodzica.** Działa na własnym specu plus
na tym, co nazywa `share_with_delegates`, po jednym id naraz — specjalista, który
po cichu zyskałby poświadczenia rodzica, byłby cichą obwodnicą wokół tego, co
rodzicowi przyznano. Publikacja odrzuca współdzielone id, którego rodzic sam nie
wiąże, bo pożyczanie tego, czego się nie ma, jest linią konfiguracji czytającą się
jak decyzja i nierobiącą nic. W praktyce istnieje to dla `sandbox`: współdzielenie
go jest sposobem, w jaki researcher zapisuje `/workspace/notes.md`, a redaktor to
czyta. Delegat, który wiąże `sandbox` *bez* współdzielenia tego rodzica, dostaje
workspace w pamięci, bo tylko run go otwiera.

**`subagents` nie da się współdzielić**, a to jedyne id, którego pytanie „czy
rodzic je ma" nigdy nie mogłoby odrzucić — agent, który cokolwiek współdzieli, ma
je z definicji.

Współdzielone, powiązanie rodzica ląduje na delegacie, który nie wiąże żadnego, a
środowisko uruchomieniowe czyta wtedy specjalistów *rodzica*, jego `allow_dynamic`,
`max_fanout`, `max_depth` i listę współdzielenia tak, jakby wybrał je autor
delegata.

Publikacja to odrzuca, a środowisko uruchomieniowe zrzuca to również z listy
współdzielenia, więc spec zapisany przed tą regułą też nie poszerzy delegata.

To, czy delegat może w ogóle delegować, jest odpowiedzią jego własnego speca, i tak
samo jest z tym, jak głęboko może zejść — ograniczonym tym, co zostało drzewu nad
nim.

Współdzielenie jest też jedyną drogą do [połączenia MCP](../mcp.md) dla specjalisty
wewnętrznego, który nie może związać go w ogóle: połączenie jest konfiguracją w
zakresie organizacji, a sięganie po nie przez specjalistę, którego nikt nie
opublikował, to złe drzwi. Zwiąż je na rodzicu i nazwij tutaj.

**`create_agent` i `delegate` są oferowane tylko przy `allow_dynamic`.**
Narzędzia nieobecnego w deklaracji capability nie da się zabramkować polityką
zatwierdzeń ani przemianować przez powiązanie, a groźna połowa tego jest cicha —
więc deklarowanych jest wszystkie dziesięć, a domyślna konfiguracja oferuje siedem.

To, co kupuje ten przełącznik, to specjalista, którego model pisze sam:
instrukcje i model, i nic poza tym.

Jest budowany przez to samo `build_agent`, przez które przechodzi specjalista
wewnętrzny, na współdzielonym strażniku budżetu runa i jego kanale zatwierdzeń,
więc jego żądania są wyceniane i liczone do limitu, który ktoś ustawił.

To jest cały powód, dla którego wymagało to **fabryki**, a nie flagi. Specjalista,
którego biblioteka zbudowałaby dla siebie, siedziałby poza katalogiem modeli tego
deploymentu, poza jego vaultem i poza strażnikiem budżetu — jako niemierzone
żądanie, być może do providera, dla którego organizacja nie ma klucza. Fabryka jest
tym, co zawraca go z powrotem przez tę platformę.

!!! note "Specjalista, który nie nazywa modelu, zostaje odrzucony"

    Przed `subagents-pydantic-ai` 0.2.18 biblioteka niosła domyślny napis modelu, z
    którego kompilowany był specjalista bez modelu. 0.2.18 usunęła ten fallback, a
    ta platforma odrzuca go jeszcze wcześniej, w `DelegatingToolset._refuse_dynamic`.

Model może nazwać wyłącznie taki model, dla którego organizacja ma profil, a odmowa
podaje listę. Nie może dołączać capability: pozwolenie modelowi na przyznanie
własnemu dziecku capability to ta sama porażka nieprzyznanego zakresu w nowym
kapeluszu. Nie dostaje żadnej wiedzy, żadnych własnych delegatów i nic nie jest
utrwalane między runami — zachowanie specjalisty oznacza opublikowanie agenta, co
jest czynnością człowieka. `MAX_DYNAMIC_SPECIALISTS` ogranicza, ilu jeden run może
zachować.

To, że specjalista nie jest utrwalany, jest projektem i ma wyjście zamiast ślepego
zaułka: człowiek może **awansować** go do agenta w wersji roboczej.

Jego definicja jedzie na otwierającej ramce `SubagentStarted` — w jedynym miejscu,
w którym jest czytelna po tym, jak model ją napisał, a przed końcem tury — więc
panel delegowania na czacie może zaproponować jej zachowanie, póki run jest jeszcze
na ekranie, a Builder proponuje to samo na specjaliście wewnętrznym.

Awans tworzy wersję roboczą należącą do tego, kto awansował, bramkowaną na
`agents:edit`, i na tym się zatrzymuje: nie publikuje, nie przypina nowego agenta
jako delegata i nie usuwa specjalisty, z którego powstał.

Zobacz [Koncepcje](../concepts.md#delegate-vs-inline-specialist), dlaczego reguła
utrwalania jest powodem istnienia tego wyjścia, a nie ograniczeniem, które ono
obchodzi.

Zachowany trwa przez cały run, w którym został wymyślony, łącznie z parkowaniem na
zatwierdzenie: rejestracja żyje w rejestrze, który biblioteka delegowania buduje na
każdego *zbudowanego* agenta, a run, który parkuje, jest przy wznowieniu budowany
ponownie — więc do czasu, aż rejestracje zaczęto nieść w `PausedRunState` i
odtwarzać przy powtórce, ginął na parkowaniu
([#175](https://github.com/vstorm-co/agenticos/issues/175)). Nie przeżywa
*kolejnej tury rozmowy*, która jest świeżym budowaniem bez zaparkowanego stanu —
nazwa utworzona w jednej odpowiedzi jest w następnej nieznana, a opis `create_agent`
mówi modelowi, żeby utworzył ją ponownie, jeśli `task` tak powie.

**Własny niewyspecjalizowany delegat biblioteki delegowania nie jest oferowany w
ogóle**, i nie ma na niego ustawienia.

Przed subagents-pydantic-ai 0.2.18 działałby na modelu, którego ten deployment nie
skonfigurował — skompilowany z własnego domyślnego napisu modelu biblioteki, poza
profilami organizacji, jej vaultem i strażnikiem budżetu runa. Dokładnie tak jak
specjalista tworzony w trakcie runa powyżej, zanim wymagał fabryki.

Chcieć „łapacza wszystkiego" to rzecz uprawniona. Napisz go jako specjalistę
wewnętrznego, gdzie widać, co robi, i gdzie jest wyceniany jak wszystko inne.

Własny delegat biblioteki jest naprawiony od 0.2.18
([#174](https://github.com/vstorm-co/agenticos/issues/174)): bez domyślnego modelu
i bez fabryki odmawia teraz zbudowania delegata, zamiast wybierać model.

To, co model dowiaduje się o tym wszystkim, jest pisane tutaj, a nie przez
bibliotekę: delegaci z nazwy i opisu, tryb, którego ten run naprawdę użyje, i pułap
rozgałęzienia, który inaczej odkryłby, dostając odmowę. Dwie listy tych samych
delegatów w jednym prompcie systemowym to kontekst opłacony dwa razy, a tylko jedna
z nich może powiedzieć, co deployment naprawdę egzekwuje.

Co kosztuje delegowanie i który wiersz runa je zapisuje — zobacz
[Nadzór](../governance.md#delegation-spends-the-parents-budget). Kto może delegować
do czego — zobacz
[Uprawnienia](../permissions.md#delegation-is-not-a-privilege-boundary).

## Planowanie { #planning }

`write_plan` — *lay out or replace the whole checklist.*
`read_plan` — *see the steps and their ids before a granular edit.*
`add_task`, `update_task_status`, `update_task_statuses`, `remove_task` — *change one
step, or a batch, without replacing the plan.*
`add_subtask`, `set_dependency`, `get_available_tasks` — *dependency-aware planning,
offered only under `enable_subtasks`.*

Lista kontrolna, którą model prowadzi dla siebie w trakcie pracy: co zrobione, co w
toku, co zostało. Przy pracy wieloetapowej model radzi sobie lepiej, gdy najpierw
zapisze kroki i trzyma je przed sobą, więc bieżący plan jest przywoływany co turę
jako **przypomnienie w ogonie, bezpieczne dla cache'u** — doklejane za punktem
cache'owania, tak by stabilny prefiks promptu pozostawał bajt w bajt taki sam i by
co turę czytany był ponownie tylko zmienny plan. Plan nigdy nie ląduje w prompcie
systemowym.

Nakłada się to na [Delegowanie](#delegation) tak, jak plan nakłada się na zespół:
planowanie decyduje, *jakie* są kroki, delegowanie decyduje, *kto* je wykonuje. Są
ortogonalne — plan to zestaw narzędzi plus przypomnienie, delegowanie to zestaw
narzędzi plus otoczka runa — więc agent może wiązać oba, jedno albo żadne.

| Konfiguracja | Domyślnie | Wartości |
|---|---|---|
| `enable_subtasks` | `false` | dodaje trzy narzędzia do podzadań i zależności oraz status `blocked` |
| `cache_ttl` | `5m` | `5m`, `1h` — jak długo może się cache'ować prefiks przed przypomnieniem |

**Żadne z dziewięciu narzędzi nie działa na świat.** Każde zmienia listę kontrolną,
którą model prowadzi dla siebie, więc nie ma tu czego zatwierdzać i capability
deklaruje `side_effecting=False`. Trzy narzędzia do podzadań są deklarowane nawet
wtedy, gdy płaska lista kontrolna ich nie oferuje, bo narzędzia nieobecnego w
deklaracji nie da się ani zabramkować polityką zatwierdzeń, ani przemianować przez
powiązanie.

**Plan należy do rozmowy, a nie do jednej jej tury.**

Lista kontrolna jest stanem, a każda granica, jaką ma run, inaczej by ją gubiła.
Run, który parkuje na zatwierdzeniu w środku planu, wznawia się jako świeży run — a
wiadomość na czacie *jest* tutaj runem, więc następna wiadomość startowała z
pustego magazynu.

Agent zapisał trzy kroki, został poproszony o rozpoczęcie pierwszego i odpowiedział,
że żaden plan nie istnieje i że nigdy go nie stworzył (agenticos#1077).

Dlatego magazyn należy do **runnera**, a nie do capability. Jest zasiewany z planu
zapisanego przy rozmowie albo z `paused_state` przy wznowieniu, co jest kopią
nowszą, i zapisywany z powrotem do rozmowy, gdy run się kończy.

Powierzchnia bez rozmowy — gołe wywołanie API — trzyma plan przez czas trwania
swojego runa, bo tylko tyle ma.

**Ukończona lista kontrolna jest historią i nowa tura nie zaczyna od niej.** Wiersz
ją zachowuje — nic nie jest kasowane — ale plan, którego każdy krok jest
`completed` albo `cancelled`, nie jest zasiewany do następnej tury: przypomnienie w
ogonie nazywałoby „twoim bieżącym planem" zadanie, którego nikt nie wykonuje, a
`read_plan` odpowiadałoby nim (agenticos#1221).

Zachowanie wiersza wymaga jeszcze jednej reguły, bo tura zapisuje swój magazyn z
powrotem, gdy się kończy: tura, której magazyn otwarto pusty *nad* ukończonym
planem, nie zapisuje nic. Nic nie zrobiła liście kontrolnej, a pusty zrzut usunąłby
wiersz już przy najbliższej zwykłej wiadomości. Agent, który zaczyna nową pracę,
zrzuca plan i zastępuje go jak zwykle.

Filtr działa przy *zasiewie*, a nie w chwili odhaczenia ostatniego kroku, i na tym
polega cały ten wybór. W obrębie tury, która kończy plan, magazyn nadal go trzyma,
więc agent może streścić to, co właśnie zrobił, i nic nie zaprzecza zapisowi
rozmowy. Czysto zaczyna dopiero następne pytanie — a odhaczona lista kontrolna jest
nadal w wiadomościach powyżej, gdzie czyta się jak to, co zrobiono, a nie jak to, co
jest robione. Krok `blocked` to praca zaległa, więc plan, który go zawiera, jest
zasiewany: coś musi go jeszcze odblokować. Wznowienie zasiewa z `paused_state` i
jest nietknięte, będąc z konstrukcji w środku planu.

Agent, który nie wiąże tej capability, nie płaci nic: żadnych narzędzi, żadnego
przypomnienia i nic zapisanego, bo pusta lista kontrolna wobec kolumny, która jest
nullem, nie jest zmianą do zapisania.

**Nie wydaje własnych tokenów.** Narzędzia to lokalne edycje listy kontrolnej, bez
żadnego żądania do modelu ani do embeddingów, więc w przeciwieństwie do wiedzy czy
delegowania nie ma tu zużycia otoczkowego do mierzenia. Rundy, które model odbywa,
żeby je wywołać, są jego własne, a strażnik budżetu już je liczy.

## Myślenie { #thinking }

Bez narzędzi. Prosi model, by rozumował, zanim odpowie: wolniej i drożej, lepiej
przy pracy wymagającej utrzymania w głowie kilku kroków naraz.

| Konfiguracja | Domyślnie | Wartości |
|---|---|---|
| `effort` | nieustawione | `minimal`, `low`, `medium`, `high`, `xhigh` |

Nieustawione oznacza własny domyślny wysiłek providera. Poziom, którego provider
nie ma, mapuje się na najbliższy, więc spec pozostaje przenośny przy zmianie modelu.

## Przypomnienia systemowe { #system-reminders }

Bez narzędzi. Powtarza wskazówki sterujące w trakcie runa, żeby długa sesja
przestała dryfować od swoich instrukcji — porażką, którą to naprawia, jest zanik
instrukcji, gdy po wielu turach z użyciem narzędzi model stopniowo ignoruje
wskazówki, z którymi zaczynał. Jest to port `SystemReminders` z
[`pydantic-ai-harness`](https://github.com/pydantic/pydantic-ai-harness).

Są trzy rodzaje przypomnień, każdy z własnym rytmem:

| Rodzaj | Koszt | Tekst, który wstrzykuje |
|---|---|---|
| `reminders[]` | żaden | Stała linia, którą piszesz |
| `goal_reanchor` | żaden | Pierwsza prośba użytkownika w tym runie, powtórzona jako kotwica |
| `llm_reminder` | jedno wywołanie modelu na odpalenie | Krótkie ponaglenie, które model pisze z ostatniego zapisu rozmowy |

Każdy rodzaj przyjmuje `interval` (odpalaj co N żądań do modelu), `first_after`
(numer żądania przy pierwszym odpaleniu) i `max_fires` (limit w obrębie rozmowy);
`cache_ttl` na capability ustawia czas życia punktu cache'owania. Ustawiony musi być
przynajmniej jeden rodzaj, inaczej capability nie wnosi nic i jest usuwana z runa —
i to właśnie znaczy pusta konfiguracja.

**Rytm liczy się w poprzek całej rozmowy i jest trwały.** Przypomnienie odpala przy
żądaniu do modelu numer N, a ten licznik jest zapisywany przy rozmowie i zasiewany
z powrotem w następnej turze — więc przypomnienie ustawione na co dziesiąte żądanie
liczy dalej od miejsca, w którym skończyła poprzednia tura, zamiast zerować się, a
wyjście z rozmowy i wczytanie jej ponownie wznawia liczenie (#787). Zapisywane są
tylko liczniki; tekst przypomnienia jest wstrzykiwany per żądanie i nigdy nie trafia
do zapisu rozmowy.

**Wstrzykiwanie jest bezpieczne dla cache'u.** Odpalone przypomnienie jest doklejane
do *ogona* żądania jako efemeryczny prompt użytkownika za punktem cache'owania, po
tym, jak rdzeń utrwalił trwałą historię — więc dociera do modelu, ale nigdy nie
trafia do `message_history`, nie odkładają się przestarzałe przypomnienia, a
cache'owany prefiks (narzędzia, prompt systemowy, właściwa rozmowa) zostaje bajt w
bajt taki sam tura po turze, podczas gdy poza cache'em wypada tylko małe
przypomnienie. Wstrzykiwanie do promptu systemowego psułoby cache'owany prefiks przy
każdym odpaleniu *oraz* kumulowało przestarzałe przypomnienia.

**Przypomnienie LLM jest mierzone i dziedziczy model runa.**

Pisze swój tekst przez agenta, którego buduje samo i którego nie opakowuje żaden
strażnik budżetu — więc jego wydatek jest księgowany w rejestrze runa tak jak
streszczenie, a działa w ramach limitów zużycia runa pomniejszonych o jedno
zarezerwowane żądanie, więc nigdy nie przepchnie runa poza jego własny limit kroków.

Przy dowolnym błędzie, albo gdy zarezerwowany budżet jest już wydany, przypomnienie
cofa się do linii kotwiczącej cel. Nieudane generowanie nigdy nie blokuje runa.

Używa własnego modelu runa — tego, którego poświadczenie rozwiązał vault — a nie
nazwy z konfiguracji, czyli tej samej decyzji, którą wobec swojego streszczacza
podejmuje [Zarządzanie kontekstem](#context-management).

## Data i godzina { #date-and-time }

Bez narzędzi. Wstawia bieżącą datę i godzinę do instrukcji agenta, żeby przestał
ich zgadywać — porażką, którą to naprawia, jest agent pewnie rozumujący o „tym
kwartale" na podstawie daty odcięcia swojego treningu.

| Konfiguracja | Domyślnie | |
|---|---|---|
| `timezone` | `UTC` | dowolna nazwa IANA, np. `Europe/Warsaw` |

## Zarządzanie kontekstem { #context-management }

Bez narzędzi. Przycina historię wiadomości długiego runa przed każdym żądaniem, więc
run, który uderzyłby w limit modelu, pracuje dalej. Strategie pochodzą z
[`pydantic-ai-harness`](https://github.com/pydantic/pydantic-ai-harness).

| Konfiguracja | Domyślnie | |
|---|---|---|
| `strategy` | `summarize` | `summarize`, `tiered`, `clear_tool_results`, `sliding_window` |
| `max_fraction` | `0.9` | 0,05–0,95 okna, przy którym zaczyna się kompaktowanie |
| `keep_messages` | 20 | najnowsze wiadomości, które przeżywają streszczenie albo okno |
| `keep_tool_pairs` | 3 | najnowsze wywołania narzędzi, które zachowują swoje wyniki |
| `summary_prompt` | własny biblioteki | co dostaje model streszczający; musi zawierać `{messages}` |
| `context_window` | nieustawione | nadpisz okno — to, wobec czego to się odpala, *oraz* to, przez co dzieli wskaźnik na czacie |
| `fallback_context_window` | 200000 | okno przyjmowane, gdy okna modelu nie da się ustalić |

`summarize` jest domyślne, bo jako jedyna strategia zachowuje to, co starsze tury
*powiedziały*. Te bez LLM są tańsze, bo wyrzucają informację — przesuwane okno
zrzuca najstarsze wiadomości wprost, wyczyszczenie wyniku narzędzia kasuje
odpowiedź, której agent może jeszcze potrzebować — a agent, który po cichu zapomina
w trakcie runa, co mu powiedziano, jest gorszą porażką niż streszczenie, o które
nikt nie prosił. Odpala przy 0,9 okna z tego samego powodu: kompaktowanie jest
miejscem, w którym run zaczyna tracić szczegóły, więc jest odkładane, dopóki okno
nie jest prawie pełne.

`tiered` jest wyborem oszczędnym i jest jedno powiązanie stąd: najpierw czyści stare
wyniki narzędzi, a za streszczenie płaci dopiero wtedy, gdy to nie wystarczyło.
Streszczanie zamienia tokeny wejściowe w wyjściowe, które są rozliczane z premią i
generowane szeregowo, więc agent, którego runom przewodzą duże wyniki narzędzi,
zwykle wychodzi lepiej na `tiered`.

**Sięga do jednego runa, a nie do jednej rozmowy.** Między turami historia jest
odbudowywana z zapisu rozmowy jako tekst użytkownika i asystenta, więc nie ma tam
wywołań narzędzi ani ich wyników do kompaktowania i żadna zrobiona tu edycja nie
przeżywa granicy tury. Historią wartą kompaktowania jest długa pętla narzędzi
wewnątrz jednego runa, gdzie jedno wylistowanie katalogu albo jedno wyszukanie w
wiedzy to dziesiątki tysięcy tokenów.

**Wyzwalaczem jest ułamek, bo liczba bezwzględna jest właściwa tylko dla jednego
modelu**, a ten sam agent chodzi na dowolnym profilu, na który wskazuje jego spec.
Okno pochodzi z profilu modelu, który zapisał je z własnej listy providera, gdy ktoś
ten model dodawał — zobacz
[Jakie modele oferuje provider](../models.md#the-window-a-model-accepts-is-read-once-and-kept).

Tam, gdzie profil nie zapisał nic, okno jest ustalane z dołączonej migawki cennika,
a dwa przypadki ustalają się źle — oba w kierunku, który psuje run, a nie w tym,
który marnuje streszczenie: spec z fallbackami buduje `FallbackModel`, którego
złożone id nie rozwiązuje się na nic, a `genai-prices` zapisuje 1 000 000 dla
`anthropic:claude-sonnet-4-5` wobec rzeczywistych 200 000, gdzie `max_fraction=0.9`
stawia wyzwalacz na 900 000 i kompaktowanie nie odpala nigdy. `context_window`
nadpisuje wszystko i jest odpowiedzią na oba — provider publikuje maksimum, do
którego model *da się* nakłonić, a deployment ograniczony betą albo poziomem
abonamentu dostaje mniej.

**Wyzwalacz uwzględnia to, co niesie każde żądanie.** Mierzy części wiadomości; a
żądanie niesie też instrukcje i schemat każdego narzędzia. Na prawdziwym agencie
estymator widział 60 tokenów tam, gdzie provider naliczył 3865 — więc narzut jest
mierzony przy każdej odpowiedzi, a okno wyzwalacza jest o niego obniżane, i to
właśnie sprawia, że wskaźnik i wyzwalacz opisują jeden sufit, a nie dwa.

Czeka na odpowiedź, z której może zmierzyć, więc pierwsze żądanie w runie odpala się
na samych wiadomościach. I poddaje się, gdy sam narzut jest już za wyzwalaczem:
żadne streszczenie nie zejdzie poniżej, schematów nie ma w historii, a poprawione
okno kupowałoby streszczenie przy każdym żądaniu na zawsze.

**Gdy się poddaje, mówi o tym.** `context_window` mniejsze niż własny narzut agenta
jest właśnie tym przypadkiem, a niezrobienie z tym niczego wygląda na ekranie tak
samo jak ustawienie, które działa — więc czat pokazuje, ile wynosi narzut i wobec
jakiego okna go zmierzono, czyli parę, której ktoś potrzebuje, by dobrać działającą
liczbę. Raz na run, bo opisuje to konfigurację, a nie zdarzenie, i znika w chwili,
gdy streszczenie naprawdę się wykona.

**Streszczenie mówi, że się dzieje.** To całe żądanie do modelu między dwoma
żądaniami tury, podczas którego nic innego nie płynie — czat zatrzymywał się na ten
czas kompletnie, co czyta się jak zepsuty ekran i kończy przeładowaniem strony,
anulującym turę. Czat pokazuje teraz, co jest streszczane w trakcie. Tylko strategia
streszczająca: pozostałe edytują listę i wracają.

**Streszczenie jest mierzone.** Strategia pisze je przez agenta, którego buduje
sama i którego nie opakowuje żaden strażnik budżetu, więc capability mierzy zużycie
runa w poprzek haka i księguje różnicę w rejestrze runa. Jest to zapisywane, a nie
blokowane: strażnik odmawia przy *następnym* żądaniu, więc kompaktowanie, które
przekracza limit, zatrzymuje run po sobie, a nie w swoim trakcie.

**Wskaźnik obok nie jest częścią tego powiązania.** To, jak pełne było okno,
raportuje każdy agent, niezależnie od tego, czy kompaktuje — zobacz
[jak pełne jest okno kontekstu](../governance.md#how-full-the-context-window-is).
Ostrzeżenie ma największe znaczenie dla agenta, który *nie* będzie kompaktował,
bo to on dochodzi do sufitu i dostaje odmowę.

## Limity wyjścia narzędzi { #tool-output-limits }

Jedno narzędzie, `read_tool_result`. Tam gdzie `compaction` przycina historię
*wewnątrz* okna między żądaniami, to powstrzymuje przerośnięty zwrot narzędzia przed
dostaniem się tam w ogóle. `ToolReturnPart` jest utrwalany, więc grep po dużym
repozytorium albo rozgadana odpowiedź API są wysyłane w całości ponownie przy każdym
późniejszym żądaniu tego runa — `code_execution` przycina już na 8000 znakach
dokładnie z tego powodu, co jest dobrą wartością domyślną i złym sufitem: to, co
miało znaczenie, znika z pola widzenia modelu i nie ma na czym działać. To redukuje
zwrot raz, w chwili jego powstania, i pozwala utrwalić formę zredukowaną. Sama
redukcja to `ToolOutputLimits` z
[`pydantic-ai-harness`](https://github.com/pydantic/pydantic-ai-harness).

| Konfiguracja | Domyślnie | |
|---|---|---|
| `action` | `spill` | `spill`, `truncate`, `summarize` |
| `threshold` | 10000 | rozmiar, od którego zwrot jest redukowany |
| `over_tokens` | `false` | mierz próg w szacowanych tokenach, nie w znakach |
| `max_chars` | 4000 | znaki zachowane przy przycięciu zwrotu albo gdy zrzut cofa się do przycięcia |
| `truncation_strategy` | `head_tail` | `head`, `tail`, `head_tail` — który koniec (lub końce) zachować |
| `strip_ansi` | `false` | usuń kody kolorów terminala przed mierzeniem i redukcją |
| `summary_prompt` | własny biblioteki | co dostaje model streszczający; musi zawierać `{tool_name}` i `{output}` |

`spill` jest domyślne i jako jedyne bezstratne: pełny zwrot jest zapisywany na
backendzie agenta i zastępowany uchwytem, podglądem i szkicem kształtu, a model
czyta jego wycinki na żądanie przez `read_tool_result(handle, offset, limit,
from_end, pattern)` — ten sam wzorzec stronicowania, który `read_file` daje mu nad
workspace'em. `truncate` to tani, stratny zacisk ze znacznikiem mówiącym, co ucięto;
`summarize` zastępuje zwrot streszczeniem LLM i jest tym drogim.

**Zrzut trafia na własny backend agenta.**

Agent, który wiąże `sandbox`, ma już system plików — `state`, kontener Dockera,
Daytonę — który runner otworzył na potrzeby runa i przypisał do organizacji. Zrzut
mieszka tam, pod prefiksem `tool_output/`, więc dzieli czas życia tego workspace'u,
a agent może nawet sięgnąć po niego własnymi `read_file` i `grep`.

Przy domyślnym zakresie sesji `run` tym czasem życia *jest* run, czyli dokładnie to,
o co prosi wymóg „nie może przeżyć runa".

Zrzut jest artefaktem wewnątrz runa i nie przeżywa runa również na workspace'ie o
dłuższym zakresie (`conversation`, `user`, `agent`):

- workspace `state` ma zarezerwowany prefiks usuwany przy zrzucie do bazy, więc
  odkładające się zrzuty nie mogą już pchać go ku limitowi bajtów i odmawiać
  agentowi jego własnych zapisów;
- workspace *kontenerowy* ma zrzuty runa usuwane ze swojego systemu plików w chwili
  zamknięcia workspace'u — dokładnie po tych uchwytach, które run zapisał, a nigdy
  przez zamiatanie prefiksu, żeby dwa równoległe runy współdzielące workspace nie
  mogły zabrać sobie nawzajem zrzutów w locie
  ([#803](https://github.com/vstorm-co/agenticos/issues/803)).

Agent bez backendu dostaje backend w pamięci, zbudowany na potrzeby runa i
porzucony razem z nim, więc zrzut nigdy nie trafia na współdzielony dysk.

Zrzut, którego backend odmawia — workspace `state` już przy swoim limicie bajtów —
cofa się do przycięcia, a nie do cichego porzucenia. Tak samo `summarize`, którego
wywołanie modelu zawiedzie: `summarize` → `spill` → `truncate`.

**Streszczenie jest rozliczane na run.** Jak w `compaction`, wywołanie streszczające
idzie przez `Agent`, którego harness buduje sam, poza strażnikiem budżetu, więc jego
tokeny są księgowane w rejestrze runa tą samą ścieżką zużycia otoczkowego — zobacz
[jak liczony jest koszt runa](../governance.md). `spill` i `truncate` nie wołają
żadnego modelu i nie kosztują nic.

Harness składa redukcje z uporządkowanej listy *pasm* rozmiaru; tutaj autor wybiera
jedno `action` przy jednym `threshold`, bo formularz Buildera nie umie narysować
listy zagnieżdżonej — z tego samego powodu, dla którego `compaction` wybiera
strategię, zamiast komponować poziomy.

## Wyszukiwanie narzędzi { #tool-search }

Bez własnych narzędzi. Pozwala agentowi *znaleźć* narzędzie w dużym zbiorze zamiast
nosić schemat każdego z nich w kontekście przy każdym żądaniu. Ma to największe
znaczenie dla [MCP](../mcp.md): agent może związać dowolną liczbę serwerów, a każde
narzędzie, które serwer wystawia, to schemat, za który model płaci w każdej turze,
niezależnie od tego, czy kiedykolwiek je wywoła.

| Konfiguracja | Domyślnie | Wartości |
|---|---|---|
| `strategy` | `auto` | `auto`, `keywords`, `bm25`, `regex` |
| `max_results` | 10 | 1–50, ignorowane przez wyszukiwanie natywne |

- **`auto`** — natywne wyszukiwanie narzędzi tam, gdzie provider je oferuje
  (Anthropic BM25 albo regex, OpenAI po stronie serwera), lokalny algorytm słów
  kluczowych wszędzie indziej.
- **`keywords`** — zawsze dopasowuj lokalnie, u dowolnego providera.
- **`bm25` / `regex`** — wymuś natywny algorytm Anthropic; run u providera bez
  natywnego wyszukiwania narzędzi kończy się błędem, zamiast po cichu podstawiać
  inny. Model jest rozwiązywany niezależnie od speca, więc jest to koszt czasu
  działania, który autor przyjmuje, nazywając jeden z nich — `auto` nie zawodzi w
  ten sposób nigdy.

**To włączenie tego odracza zestawy narzędzi MCP.** Capability i odraczanie to dwie
połowy jednej decyzji: biblioteczne `ToolSearch` jest bezczynne, gdy nic nie jest
odroczone, a odroczone narzędzie bez wyszukiwania, które by je znalazło, to
narzędzie, którego model nigdy nie wywoła. Związanie `tool_search` jest więc tym, co
oznacza zestawy narzędzi podłączonych serwerów do odroczonego ładowania — własne
narzędzia rejestru zostają widoczne, będąc nieliczne i wybrane per agent. Agent,
który tego nie wiąże, nie płaci nic i widzi wszystkie narzędzia jak wcześniej.

**Odraczanie zmienia to, co widzi model, nigdy tożsamość narzędzia.** Odnalezione
narzędzie MCP przychodzi pod swoją prawdziwą, prefiksowaną nazwą, więc
[bramka zatwierdzeń](#what-a-binding-may-change) nadal paruje się z nim, a zmiana
nazwy z powiązania nadal go dosięga; `ToolSearch` siedzi najbardziej na zewnątrz i
czyta nazwy, które zmiana nazwy już nałożyła.

**Nie wymaga mierzenia.** Dwie lokalne strategie działają w Pythonie i nie wydają
tokenów; wyszukiwanie natywne działa wewnątrz własnego żądania providera, którego
zużycie mierzy już [strażnik budżetu](../governance.md); a rundy odkrywania to
zwykłe żądania do modelu, opakowane przez tego samego strażnika. Jedyny kształt,
który by mu umknął — własna funkcja wyszukująca, która sama woła model albo
embeddingi — celowo nie jest wystawiony.

## Guardrails { #guardrails }

Bez narzędzi. Bada tekst płynący przez run na trzech krawędziach i albo
**redaguje** trafienie, albo **blokuje** run. Sprawdzenia to gotowe detektory z
`pydantic-ai-harness`; agent jest danymi, więc konfiguracja wybiera je i
parametryzuje, zamiast nieść pythonowego strażnika.

| Krawędź | Czyta | Redagowanie | Blokowanie |
|---|---|---|---|
| wejście | prompt użytkownika | `redact_secrets_in`, `redact_pii_in` | `blocked_keywords_in` |
| wyjście | odpowiedź agenta | `redact_secrets_out`, `redact_pii_out` | `blocked_keywords_out` |
| wynik narzędzia | to, co zwróciło narzędzie, zanim przeczyta to model | `redact_secrets_tool`, `redact_pii_tool` | `blocked_keywords_tool` |

| Konfiguracja | Domyślnie | |
|---|---|---|
| `redact_secrets_*` | `false` | wymaż klucze API, tokeny, JWT i bloki PEM |
| `redact_pii_*` | `false` | wymaż e-mail, IBAN (mod-97), kartę (Luhn) i US SSN |
| `blocked_keywords_*` | `""` | terminy rozdzielone przecinkiem albo nową linią; trafienie kończy run |

Każde pole jest domyślnie wyłączone, a capability włączona bez skonfigurowanej
krawędzi nie dołącza niczego — agent, który jej nie używa, nie płaci nic.

**Redagowanie przepisuje; blokada jest wynikiem runa.** Redaktor wymazuje trafienie
i run kończy się normalnie — odpowiedź, która przytoczyła klucz z powrotem, mimo to
wykonała pracę. Blokada na słowie kluczowym zamiast tego kończy run ze statusem
`guardrail_blocked`, własnym wynikiem obok `budget_exceeded`, bo odmowa jest
platformą działającą poprawnie, a operator filtrujący problemy powinien móc ją
znaleźć, a nie czytać ją jak każdą ukończoną odpowiedź. Zobacz
[Nadzór](../governance.md).

**Prześwietlanie wyników narzędzi jest powodem, dla którego ta krawędź znaczy
najwięcej.** Jest jedynym strażnikiem nad niezaufaną treścią wchodzącą do pętli —
pobraną stroną, plikiem, odpowiedzią serwera MCP — gdzie ładunek z prompt injection
inaczej dotarłby do modelu nieprzeczytany.

Dwie rzeczy są celowo poza zakresem. **Argumenty narzędzi** to ustrukturyzowane
mapowanie bez detektora tekstu, więc nie są krawędzią. A werdykt `approve` z
narzędzi harnessu nie jest przeniesiony: [zatwierdzenia](../governance.md) już
parkują run per narzędzie na decyzję człowieka, a druga, sterowana regułami droga do
tego samego mechanizmu to dokładnie to, czego unika się jednymi drzwiami.

## Podgląd kanału czatu { #chat-channel-lookup }

`get_channel_info` — *Describe the channel this conversation is happening in.*
`list_channel_members` — *List the people in this channel.*
`search_channels` — *Find other channels by name or purpose, without reading them.*
`read_channel_history` — *Read the most recent messages in this channel, newest last.*

Jedyna capability, której spec agenta nie może związać. Przyznaje się ją **per
powiązanie**, w Builderze pod *Where this agent is available*, bo organizacja może
związać jednego agenta z dwoma serwerami Mattermost i trzema workspace'ami Slacka —
a „czy może czytać, co powiedziano w tym kanale" ma inną odpowiedź na kanale
wewnętrznym i na klienckim. Pole w specu miałoby jedną odpowiedź dla wszystkich
pięciu, więc walidacja publikacji odrzuca `channel_tools` w specu, a run składa
powiązanie z tego wiersza, który dopuścił wiadomość — dokładnie tak samo, jak dokleja
prompt tego wiersza do instrukcji.

Nadal jest zwyczajną capability z rejestru, i to jest sens robienia tego w ten
sposób, a nie przez wstrzyknięcie zestawu narzędzi: jej narzędzia da się bramkować
przez `tool_approval` i przemianować przez `tool_overrides`, a oba czytają spec.

| Konfiguracja | Domyślnie | Zakres wartości |
|---|---|---|
| `tools` | `[]` | dowolne z czterech id |
| `default_limit` | 20 | 1–200 |

Domyślnie nie jest przyznane nic, a to, na co platforma nie umie odpowiedzieć, nie
jest oferowane: Telegram nie daje botowi żadnego katalogu czatów do przeszukania ani
sposobu na czytanie wiadomości, których mu nie wysłano. `docs/channels.md` ma tabelę
per platforma i uzasadnienie.

Trzy własności obowiązują na każdej platformie:

- **Członkostwo bota jest całą granicą uprawnień.** Każde wywołanie używa własnego
  tokena bota, więc agent widzi dokładnie to, co widzi bot.
- **Model nigdy nie nazywa kanału.** Narzędzia są przypięte po stronie serwera do
  tego kanału, z którego przyszła wiadomość — a w wątku do kanału, który go trzyma.
- **Poza kanałem nie wnosi nic.** Run z dashboardu, z API albo z harmonogramu nie ma
  żadnego katalogu, więc capability nie jest w ogóle dołączana — z tego samego
  powodu, dla którego nie jest dołączane `knowledge` bez kolekcji.

## Co może zmienić powiązanie { #what-a-binding-may-change }

Katalog jest odpowiedzią deploymentu na pytanie „co istnieje". Wpis w
`capabilities[]` speca jest odpowiedzią jednego agenta na pytanie „jak z tego
korzystam" i może zmienić cztery rzeczy:

| Pole | Efekt |
|---|---|
| `config` | Walidowane wobec schematu tej capability **przy publikacji**, a nie w czasie działania |
| `approval` | `default` \| `required` \| `never` dla każdego narzędzia, które wnosi capability |
| `tool_approval` | To samo, per narzędzie, nadpisując `approval` |
| `tool_overrides` | `name` i `description`, które widzi model, per narzędzie |
| `secret_id` | Który sekret organizacji spełnia zadeklarowany wymóg klucza |
| `enabled` | Wyłączenie bez utraty konfiguracji |

Zatwierdzanie jest powodem, dla którego capability w ogóle deklaruje swoje
narzędzia. „Czy ten agent może zapisywać pliki" i „czy może je czytać" to dwie
decyzje, mimo że odpowiada na nie jedna capability, więc włączanie pozostaje per
capability, a zatwierdzanie dzieje się per narzędzie. `default` idzie za własną flagą
`side_effecting` tej capability.

!!! tip "Opis narzędzia jest promptem o największej dźwigni w tym produkcie"

    To jego czyta model, zanim zdecyduje się zawołać, a jego nazwa steruje równie
    mocno: `search_refund_policy` to nie `search_documents`. Agent, który potrzebuje
    innego zachowania od tego samego narzędzia, zwykle potrzebuje przeredagowania
    tych dwóch, a nie napisania drugiej capability.

!!! danger "Kluczem jest stabilne id narzędzia, nigdy nazwa, którą widzi model"

    To właśnie trzyma bramkę zatwierdzeń przypiętą do przemianowanego narzędzia.
    Kluczowanie po nazwie widocznej znaczyłoby, że zmiana nazwy po cichu usuwa
    bramkę, a wywołanie ze skutkami ubocznymi przechodzi wtedy bez nadzoru i nic
    tego nie zgłasza. Id, którego żadna taka capability nie wystawia, zostaje
odrzucone przy publikacji, i tak samo nazwa, której żaden model nie mógłby zawołać.

## Zakresy { #scopes }

Capability może deklarować zakresy (scopes), które organizacja musi mieć przyznane,
sprawdzane w chwili składania agenta:

| Zakres | Deklarowany przez |
|---|---|
| `knowledge:read` | `knowledge`, `skills` |
| `conversations:read` | `conversation_search` |
| `web:read` | `web_research` |
| `web:fetch` | `web_fetch` |
| `web:browse` | `browser_use` |
| `code:execute` | `code_execution` |
| `sandbox:execute` | `sandbox` |
| `agents:delegate` | `subagents` |

!!! note "Wszystkie osiem jest dziś przyznanych domyślnie"

    `DEFAULT_GRANTED_SCOPES` w `app/services/agent_registry.py`. Zarządzanie
    zakresami per organizacja jest pracą z
    [roadmapy](https://github.com/vstorm-co/agenticos/blob/main/docs/ROADMAP.md);
    sprawdzenie jest w międzyczasie żywe i uczciwe, a nie wyłączone i zapomniane.

!!! warning "`agents:delegate` nie jest bramką na to, *do kogo* można delegować"

    Tym jest `agents:run`, sprawdzane na publikującym wobec wiersza każdego
    delegata. Ten zakres odpowiada na pytanie, na które nie odpowie żadne
    uprawnienie: czy ten **deployment** w ogóle pozwala agentom wołać agentów. Usuń
    go z tego zbioru, a delegowanie jest wyłączone wszędzie, jedną zmianą.

Operator, który nie chce zagnieżdżonych runów ani rozliczania rozgałęzień, usuwa go,
a każdy spec, który deleguje, mówi to wtedy przy publikacji, a nie o trzeciej w nocy.
`conversations:read` jest takim samym lewarem dla wyszukiwania w rozmowach: jedna
zmiana powstrzymuje każdego agenta przed czytaniem dawnych rozmów, dla deploymentu,
który uznaje zapis rozmowy za zbyt wrażliwy, by dał się przeszukać, choćby najwęziej
zawężonym korpusem.

## Co narzędzie mówi modelowi { #what-a-tool-tells-the-model }

Definicja narzędzia jest promptem. Model wybiera narzędzie i wypełnia jego
argumenty, mając do dyspozycji wyłącznie dołączony do niego tekst — więc każde
narzędzie tutaj niesie cztery rzeczy, a czwarta jest tą zwykle pomijaną:

1. **Co robi**, w jednym zdaniu. To jest zarazem to, co Builder pokazuje obok pola
   wyboru zatwierdzeń, więc pisze się to raz, a czyta w obu miejscach.
2. **Kiedy go użyć, a kiedy użyć czegoś innego.** `create_chart` mówi, że jest do
   liczb, które już się ma, a `generate_image` do czegoś, co trzeba narysować;
   `glob` mówi, że szuka rekurencyjnie tam, gdzie `ls` tego nie robi.
3. **Co znaczy każdy argument**, wraz z jego wartością domyślną i górną granicą.
4. **Co wraca** — kształt odpowiedzi, jak wygląda niepowodzenie i gdzie wynik jest
   przyciętym wycinkiem, a nie całym zbiorem. Model, który nie wie, że `grep`
   odpowiada w trzech różnych kształtach zależnie od `output_mode`, albo że `glob`
   zatrzymuje się na 100 ścieżkach, rozumuje z wycinka tak, jakby był całością.

Wszystkie cztery docierają do modelu w jednym kształcie, a jest to własny kształt
pydantic-ai: proza wewnątrz `<summary>`, opis zwrotu wewnątrz `<returns>`.

Narzędzie napisane tutaj dostaje to za darmo — framework buduje to z sekcji
`Returns:` w docstringu.

Narzędzie, które przychodzi z biblioteki, jest rejestrowane z jawnym opisem, co
odbiera tamtą drogę. Jego tekst idzie więc przez `ToolText` w
`app/agents/capabilities/_tool_text.py`, które renderuje to, co zrobiłby framework.

Dwie konwencje w jednej liście narzędzi to jeszcze jedna rzecz do pogodzenia przez
model, a `tests/test_tool_text_shape.py` jest tym, co pilnuje, by konwencja była
jedna: przypina `ToolText` do narzędzia, które pydantic-ai buduje samo, i sprawdza,
czy narzędzia każdej capability niosą kształt zwrotu.

Obejmuje to również te narzędzia, których ten deployment nie napisał: `planning` i
narzędzia delegowania dostają tekst z tego repozytorium, `web_fetch` i
`search_tools` są opisywane na nowo tam, gdzie są budowane, a `read_tool_result` i
trzy narzędzia `skills` są opisywane na nowo w miejscu, na własnym zestawie narzędzi
biblioteki. Dwa z nich były warte zachodu poza samą spójnością — biblioteczne zdanie
o `read_tool_result` nie mówiło nic o tym, czym odpowiada uchwyt, czyli o jedynej
rzeczy, której potrzebuje model trzymający uchwyt, a `list_skills` dokumentowało
zwrot pythonowy (słownik), a nie tekst, który dostaje model.

Narzędzie z biblioteki, dla którego to repozytorium nie ma tekstu, zachowuje tekst
biblioteczny, i jest to właściwa wartość domyślna: `run_skill_script` jest wykluczone,
a nie opisane, a jeśli kiedyś się pojawi, pojawi się mówiąc to, co napisał jego autor.

### Pomyłka, wynik i odmowa { #a-mistake-a-result-and-a-refusal }

To, jak narzędzie zgłasza kłopot, decyduje o tym, co model zrobi dalej, a te trzy
rzeczy nie są wymienne.

| Niepowodzenie | Co robi narzędzie | Dlaczego |
|---|---|---|
| Własne argumenty modelu — seria wykresu z błędną liczbą wartości, nieistniejący plik kontekstu, `NameError` w Pythonie, który sam napisał | Prośba o ponowienie | Zawołanie ponownie, inaczej, jest wiarygodną naprawą, a komunikat mówi, jak wygląda poprawne wywołanie |
| Przejściowa awaria tego, co stoi za narzędziem — niedostępny provider wyszukiwania, baza wiedzy przekraczająca czas odpowiedzi | Prośba o ponowienie | Błąd w kształcie wyniku czyta się jak „nic nie znaleziono", a model odpowiada wtedy z pamięci, pewnie, nie mówiąc, że musiał |
| Wynik, który jest po prostu złą wiadomością — polecenie zakończone kodem innym niż zero, wyszukiwanie bez trafień, kanał, którego ten bot nie widzi | Zwracane jako tekst | To jest odpowiedź. Model rozumuje o niej i idzie dalej |
| Odmowa — reguła uprawnień, capability, której ten deployment nie oferuje | Zwracane jako tekst | Prośba o ponowienie zaprasza model do szukania obejścia |

Ponowienia mają budżet: wywołanie narzędzia dostaje jedną próbę poprawienia się, a
ponowienie podniesione *poza* ten budżet kończy cały run, a nie samo wywołanie.
Ostatnia próba zwraca więc swój komunikat, zamiast rzucać wyjątkiem — sterowana,
póki jest na to budżet, i nigdy nie gorsza niż odpowiedź, którą i tak by dała.
Jedynym pomocnikiem, który o tym decyduje, jest
`app/agents/capabilities/_failures.py`; `pydantic-ai-backend` trzyma tę samą regułę
dla narzędzi workspace'u.

## Jak dopisać coś do tej listy { #adding-to-this-list }

Capability są kodem — nic, co wpisze operator, nie powołuje nowej do istnienia, i to
właśnie czyni zbiór rzeczy, które agent może robić, możliwym do zrecenzowania.
Zobacz [Dodaj capability](../howto/add-capability.md) dla nowej albo
[Dodaj narzędzie do capability](../howto/add-capability.md#adding-a-tool-to-an-existing-capability),
gdy capability już istnieje.

Narzędzia, których nikt tutaj nie musi pisać — zobacz [MCP](../mcp.md).
