---
source_sha: "97fb1d6717a2"
---

# Węzły workflow { #workflow-nodes }

Każdy krok, jaki może zawierać workflow: czym się go konfiguruje, co czyta, co
produkuje i co znaczy jego błąd. Paleta w edytorze pokazuje te same węzły z tego
samego rejestru. Dokumentacja pól poniżej jest generowana ze źródła, dlatego
zostaje po angielsku.

Kilka zasad obowiązuje każdy węzeł:

- **Krawędź ustala kolejność, a binding niesie wartość.** Pola wejściowe węzła
  są wiązane z wcześniejszymi wyjściami, z literałem albo z referencją do pliku
  lub tabeli. Zobacz [Konfigurowanie węzła](../workflows.md#configuring-a-node).
- **Ścieżka w głąb wartości o dowolnym kształcie jest sprawdzana, gdy węzeł
  działa.** Ładunek triggera, zmapowany rekord i ustrukturyzowana odpowiedź
  agenta nie mają stałego kształtu, więc binding taki jak `payload.email` jest
  przyjmowany przy publikacji i sprawdzany względem celu, gdy węzeł zostaje
  wysłany. Wartość, która nie pasuje, kończy run błędem `INVALID_BINDING`, a
  handler nigdy jej nie widzi.
- **Zasoby są sprawdzane dwa razy.** Publikacja odrzuca kolekcję, wersję
  agenta, poświadczenie albo odbiorcę, do których autor grafu nie ma dostępu.
  Każdy run sprawdza je ponownie względem własnego principala, bo dostęp może
  zostać odebrany w międzyczasie.
- **Rodzaj efektu i ponowienia** decydują, co silnik może zrobić po błędzie.
  Krok `pure` albo `idempotent` jest ponawiany. Krok, który mógł już zadziałać
  i nie daje żadnej gwarancji, zatrzymuje się dla człowieka. Własna
  [polityka](#error-handling) węzła ustala, jak często jest ponawiany, jak długo
  może trwać wywołanie i dokąd trafia błąd.

## Wyzwalacze { #triggers }

Workflow startuje od jednego wyzwalacza, węzła, od którego zaczyna się jego graf.
Publikacja wersji włącza jej wyzwalacz; zobacz
[Uruchamianie workflow spoza konsoli](../workflows.md#starting-a-workflow-from-outside-the-console).
Każdy wyzwalacz przekazuje kolejnym krokom to, od czego jego powierzchnia uruchomiła
run, zamrożone przy przyjęciu runa i najwyżej `WORKFLOW_RUN_MAX_INPUT_BYTES`. Run
testowy uruchomiony z wejściem innego kształtu kończy wyzwalacz błędem
`TRIGGER_INPUT_INVALID`. Drugi wyzwalacz albo wyzwalacz, od którego graf się nie
zaczyna, jest odrzucany przy publikacji.

### core.input { #core-input }

**API request.** Uruchamiany żądaniem HTTP albo przez WebSocket. Jego id pozostaje `core.input`, więc graf zapisany, zanim Manual i API się rozdzieliły, dalej startuje z API. Przekazuje
grafowi wejście runa jako `payload`, cokolwiek wysłał wywołujący, i nazywa
powierzchnię w `triggered_by`.

::: app.workflows.contracts.io.WorkflowInputPayload

Jego **pola wejścia** robią z wejścia kontrakt. Pole ma nazwę, typ - tekst, liczba,
liczba całkowita, tak lub nie, data albo wybór - i to, czy jest wymagane. Bez pól run
przyjmuje dowolny obiekt JSON. Z polami **Start a run** prosi o każde po nazwie, run,
którego wejściu brakuje pola, który wysyła pole złego typu albo niezadeklarowane,
jest odrzucany przed startem błędem `WORKFLOW_RUN_INPUT_INVALID`, a binding do
`payload.<pole>` jest sprawdzany pod kątem typu przy publikacji.

::: app.workflows.nodes.core_input._handler.InputField

### trigger.manual { #trigger-manual }

**Manual.** Uruchamia go osoba - **Run** w edytorze albo **Start a run** na stronie
runów. Przekazuje grafowi to samo, co **API request**, i przyjmuje te same pola
wejścia, o które edytor prosi przed startem runa.

### trigger.chat { #trigger-chat }

**Chat message.** Uruchamiany wiadomością na czacie, gdy ten workflow wybrano do
odpowiedzi. Tekst jego `core.output` trafia z powrotem do tej rozmowy.

::: app.workflows.nodes._triggers.ChatTriggerOutput

### trigger.webhook { #trigger-webhook }

**Webhook.** Uruchamiany podpisanym dostarczeniem na własny adres workflow, który
pierwsza publikacja węzła tworzy razem z sekretem do podpisu.

::: app.workflows.nodes._triggers.WebhookTriggerOutput

### trigger.schedule { #trigger-schedule }

**Schedule.** Uruchamiany według zegara, w strefie czasowej workflow i najczęściej raz na
minutę.

::: app.workflows.nodes._triggers.ScheduleTriggerConfig

::: app.workflows.nodes._triggers.ScheduleTriggerOutput

### trigger.table_record { #trigger-table-record }

**New table record.** Uruchamiany rekordem dodanym do jego tabeli, który pasuje do
każdego filtra w chwili dodania. Publikacja wymaga dostępu do odczytu tabeli.

::: app.workflows.nodes._triggers.TableRecordTriggerConfig

::: app.workflows.nodes._triggers.TableRecordTriggerOutput

### trigger.workflow_failed { #trigger-workflow-failed }

**On failure of a workflow.** Uruchamiany raz dla każdego nieudanego prawdziwego
przebiegu workflow, którego ustawienia wskazują ten jako workflow błędów, jako
członek, który go wybrał. Przebieg uruchomiony tym wyzwalaczem sam nigdy nie
uruchamia workflow błędów.

::: app.workflows.nodes._triggers.WorkflowFailedTriggerOutput

## core.output { #core-output }

To, czym workflow odpowiada. Jego zbindowane pola stają się `output` runa, który
zwraca API i dostarcza wywołująca powierzchnia. Ma te same pola co wyjście
`agent.run`, więc odpowiedź agenta binduje się wprost. Wyjście bez żadnego
bindingu to pusta odpowiedź.

::: app.workflows.contracts.io.WorkflowOutputPayload

## data.map { #data-map }

Buduje mały, typowany rekord z wcześniejszych wyjść. Każde mapowanie czyta jedną
wartość wyrażeniem JMESPath i zamienia ją na `string`, `number`, `integer`,
`boolean`, `json`, `file_ref` albo `table_ref`. Wartość, której nie da się
zamienić, kończy się błędem `MAPPING_COERCION_FAILED` z nazwą pola.

::: app.workflows.nodes.data_map._handler.DataMapConfig

::: app.workflows.nodes.data_map._handler.FieldMapping

## logic.if i logic.merge { #logic-if-and-logic-merge }

`logic.if` wylicza warunek JMESPath na zbindowanej wartości `value` i prowadzi
dalej portem `true` albo `false`. Każdy węzeł na nieobranej gałęzi zostaje
zapisany jako `skipped`. `logic.merge` łączy obie gałęzie z powrotem. Działa,
gdy dotrze do niego obrana gałąź, i przekazuje dalej jej wyjście jako `value`.
Publikacja sprawdza, czy wejścia merge'a wychodzą z jednego `logic.if` różnymi
portami, żeby zawsze działało dokładnie jedno z nich.

Wyrażenia mogą wybierać, filtrować i porównywać oraz wywoływać stały zestaw
czystych funkcji: `abs`, `avg`, `ceil`, `contains`, `ends_with`, `floor`,
`join`, `keys`, `length`, `max`, `merge`, `min`, `not_null`, `reverse`, `sort`,
`starts_with`, `sum`, `to_array`, `to_number`, `to_string`, `type` i `values`.
Null, `false` oraz pusty napis, lista albo obiekt są fałszem, a wszystko inne
prawdą, także `0`. Wyrażenia, które się nie parsuje albo które wywołuje coś
innego, nie da się opublikować.

::: app.workflows.nodes.logic_if._handler.LogicIfConfig

::: app.workflows.nodes.logic_merge._handler.LogicMergeOutput

## knowledge.search { #knowledge-search }

Przeszukuje kolekcje wiedzy według zbindowanego `query` i zwraca fragmenty jako
typowane źródła, od najlepszego. Pusty wynik to udane wyszukiwanie. Kolekcja,
której już nie ma albo której principal runa nie może już czytać, kończy krok
błędem `COLLECTION_NOT_ACCESSIBLE`. Krok nigdy nie przeszukuje mniej kolekcji,
niż wskazuje graf.

::: app.workflows.nodes.knowledge_search._handler.KnowledgeSearchConfig

::: app.workflows.contracts.io.SourceRef

## Decyzje { #decisions }

Trzy kroki zadają Jev od TypeSafe typowane pytanie o powiązany `text`, z kluczem
API TypeSafe z vaulta. Jev nie pisze tekstu: odpowiada na pytanie z pewnością od 0
do 1, w jednym żądaniu, i może odpowiedzieć tylko jedną z odpowiedzi, na które krok
pozwala. Poniżej `min_confidence` kroku wychodzi on portem `unsure`, więc to
workflow decyduje, co człowiek albo agent zrobi z wątpliwym przypadkiem.

| Krok | Pyta | Wychodzi portem |
|---|---|---|
| `decide.yes_no` | o tak albo nie | `yes`, `no` albo `unsure` |
| `decide.choose` | która z maksymalnie 255 opcji pasuje | `out` z `choice` albo `unsure` |
| `decide.score` | gdzie tekst leży na skali od 2 do 10 poziomów | `out` ze `score` albo `unsure` |

Klucz jest sprawdzany przy publikacji i odczytywany ponownie przy każdym runie.
Klucz, którego już nie ma albo nie jest udostępniony, kończy krok błędem
`SECRET_NOT_USABLE`, model, który nie odpowiada, błędem `DECISION_FAILED`,
ponawianym zgodnie z polityką kroku, a wdrożenie zbudowane bez extra `browser`
błędem `DECISION_MODEL_UNAVAILABLE`. Merge może połączyć gałęzie decyzji tak jak
gałęzie kroku If / else.

::: app.workflows.nodes._decide.DecisionConfig

::: app.workflows.nodes.decide_choose._handler.ChooseConfig
    options:
      show_bases: false

::: app.workflows.nodes.decide_score._handler.ScoreConfig
    options:
      show_bases: false

## Kanały { #channels }

Slack, Mattermost i Telegram mają każdy własną grupę kroków, które działają jako
jeden z botów organizacji na tej platformie, przez ten sam adapter, którym idą jego
odpowiedzi, więc wiadomość wysłana przez workflow przychodzi od tego bota, a krok może
odczytać to, co bot może czytać. Platforma ma tylko te kroki, które jej boty mogą
wykonać.

| Krok | Slack | Mattermost | Telegram | Przekazuje dalej |
|---|---|---|---|---|
| **Send a message** (`<platform>.message.send`) | tak | tak | tak | gdzie ją wysłano |
| **Read messages** (`<platform>.messages.read`) | tak | tak | - | `messages`, od najstarszej |
| **List members** (`<platform>.members.list`) | tak | tak | administratorzy | `members`, z ich id na platformie |
| **Find channels** (`<platform>.channels.find`) | tak | tak | - | `channels` |

Krok przyjmuje tylko bota swojej platformy, a bot mówi w imieniu całej
organizacji, więc działanie jako on wymaga `channels:manage`: od autora grafu przy
publikacji i od podmiotu runa przy każdym runie. Bot usunięty, wyłączony albo z innej
platformy kończy krok błędem `CHANNEL_NOT_USABLE`. Platforma, która odmawia wywołania
w trakcie runa, kończy go błędem `CHANNEL_UNSUPPORTED`, a taka, która nie odpowiada,
błędem `CHANNEL_CALL_FAILED`. Wysyłanie nigdy nie jest powtarzane samo.

::: app.workflows.nodes._channels.ChannelBotConfig

::: app.workflows.nodes.channel_read._handler.ChannelReadConfig
    options:
      show_bases: false

::: app.workflows.nodes.channel_read._handler.ChannelReadOutput

::: app.workflows.nodes.channel_members._handler.ChannelMembersOutput

::: app.workflows.nodes.channel_find._handler.ChannelFindOutput

## agent.run { #agent-run }

Pyta opublikowanego agenta, dokładnie w wersji przypiętej w kroku, przez ten sam
runner co chat i API, z budżetem, zatwierdzeniami, guardrailami i historią runów
agenta. Run jest zapisywany z powierzchnią `workflow`. Zbindowane `sources` są
dopisywane do promptu jako numerowany kontekst. Wywołanie narzędzia wymagające
zatwierdzenia zatrzymuje krok, a decyzja wznawia ten sam run agenta.

Agent z własnym formatem odpowiedzi przekazuje swój obiekt jako `structured`.
`structured_output_schema` prosi w zamian o inny kształt: agent jest uruchamiany
z tym schematem, a odpowiedź, która go łamie, wraca do modelu do poprawki. Obiekt
jest sprawdzany jeszcze raz, zanim cokolwiek dalej się wykona. Agent, który nigdy
nie da pasującego obiektu, kończy krok błędem `AGENT_RUN_FAILED`, a odpowiedź bez
obiektu tam, gdzie o niego proszono, błędem `STRUCTURED_OUTPUT_MISMATCH`.

| Jak zakończył się run agenta | Wynik kroku |
|---|---|
| Completed | Completed |
| Czeka na zatwierdzenie | Czeka, potem wznawia ten sam run |
| Przekroczony budżet | `AGENT_BUDGET_EXCEEDED` |
| Zablokowany przez guardrail | `AGENT_GUARDRAIL_BLOCKED` |
| Inaczej | `AGENT_RUN_FAILED` |

Powiązane `attachments` to obrazy z plików runa - pobrany plik, wyrenderowana strona
PDF, przekształcone zdjęcie - pokazywane agentowi jako obrazy, a nie jako link,
którego nie może otworzyć. Pokazywane są tylko PNG, JPEG, WebP i GIF. Każdy inny plik
kończy się `UNSUPPORTED_ATTACHMENT_TYPE`, więc tekst dokumentu najpierw odczytaj
przez `text.extract`.

Nigdy nie jest ponawiany automatycznie, bo agent mógł wywołać narzędzia z
efektami ubocznymi.

::: app.workflows.nodes.agent_run._handler.AgentRunConfig

::: app.workflows.nodes.agent_run._handler.AgentRunOutput

## http.request { #http-request }

Wywołuje API HTTP. Każde żądanie i każde przekierowanie przechodzi kontrolę SSRF
wdrożenia i jest wysyłane pod adres, który ta kontrola zatwierdziła.
Poświadczenie to [HTTP credential](../secrets.md#kinds) z vaulta i jest wysyłane
tylko do originów, na które pozwala sekret. Odpowiedź jest czytana w granicy
`max_response_bytes` i oddawana bez `Set-Cookie`, nagłówków uwierzytelniania i
samego tokena.

| Co się stało | Wynik |
|---|---|
| URL prywatny, loopback, metadata albo nie http(s) | `URL_REFUSED`, nic nie wysłano |
| URL spoza originów poświadczenia | `SECRET_ORIGIN_DENIED`, nic nie wysłano |
| Połączenie nigdy się nie otworzyło | `HTTP_UNREACHABLE`, ponawiane |
| Wysłane, brak odpowiedzi, `GET` albo nagłówek idempotencji | `HTTP_NO_RESPONSE`, ponawiane |
| Wysłane, brak odpowiedzi, inny zapis | Niepewne: run zatrzymuje się dla człowieka |
| Status inny niż 2xx | `HTTP_ERROR_STATUS` albo odpowiedź jako wyjście przy `on_error_status: complete` |
| Większa niż limit | `RESPONSE_TOO_LARGE` |

::: app.workflows.nodes.http_request._handler.HttpRequestConfig

::: app.workflows.nodes.http_request._handler.HttpAuth

::: app.workflows.nodes.http_request._handler.HttpResponseOutput

## notification.send { #notification-send }

Powiadamia członków organizacji w aplikacji, mailem albo na oba sposoby, przez
centrum powiadomień. Odbiorcy to członkowie wskazani po id. W chwili działania
każdy musi nadal być aktywnym członkiem, który widzi workflow, a pozostali są
pomijani. Jeśli nie zostanie nikt, krok kończy się błędem
`NO_PERMITTED_RECIPIENTS`. Preferencje każdej osoby dla **Workflow
notifications** nadal obowiązują. Krok kończy się, gdy powiadomienie zostanie
zapisane, a mail wychodzi później. Ponowiony krok nie zapisuje drugiego
powiadomienia.

::: app.workflows.nodes.notification_send._handler.NotificationSendConfig

## human.approval { #human-approval }

**Ask for approval** zatrzymuje run, dopóki osoba nie zatwierdzi albo nie odrzuci
tego, co run ma zrobić, a potem idzie dalej przez `approved` albo `rejected`.
Zatwierdzający czyta `title` kroku i powiązane z nim `details` w zakładce
**Approvals** w Activity albo przez `GET /api/v1/workflow-approvals`.
`approvers` wskazuje, kto może zdecydować, i ci ludzie dostają powiadomienie w
aplikacji; gdy lista jest pusta, może każdy z `approvals:decide`. Po
`timeout_hours` prośba wygasa, a krok wychodzi przez `rejected` z
`decision: "expired"`. Anulowanie runa anuluje jego prośby. Każdy przebieg kroku
pyta raz, więc ponowienie ani iteracja pętli nigdy nie pytają dwa razy o to samo.

::: app.workflows.nodes.human_approval._handler.HumanApprovalConfig

::: app.workflows.nodes.human_approval._handler.HumanApprovalOutput

## Obsługa błędów { #error-handling }

Każdy węzeł przyjmuje opcjonalną `policy` obok swojej konfiguracji.

| Pole | Domyślnie | Skutek |
|---|---|---|
| `timeout_seconds` | brak | Wywołanie, które trwa dłużej, zostaje przerwane. Krok bez zewnętrznego zapisu albo z idempotentnym wywołaniem kończy się błędem `NODE_TIMEOUT` i może zostać ponowiony. Zapis, który mógł już dojść, staje się niepewny i zatrzymuje się dla człowieka |
| `retry.max_attempts` | `WORKFLOW_RETRY_CEILING` | Łączna liczba prób, łącznie z pierwszą. Ponawiany jest tylko błąd, który węzeł oznacza jako `retryable`, a publikacja odrzuca więcej niż jedną próbę dla kroku, którego wywołania nie da się bezpiecznie powtórzyć |
| `retry.backoff`, `base_delay_seconds`, `max_delay_seconds` | `exponential`, `2`, `60` | Odstęp między próbami: stały albo podwajany aż do sufitu |
| `on_error` | `fail_run` | `route` wysyła błąd, którego ponowienia nie rozwiązały, portem `error` węzła, zamiast kończyć run błędem |

Węzeł, którego polityka kieruje błędy, ma dodatkowy port wyjściowy `error`.
Niesie on `WorkflowError`: `code`, `message`, `details` i `retryable`. Zwykłe
wyjście węzła istnieje tylko na pozostałych portach, więc publikacja odrzuca
binding, który czyta wyjście na ścieżce błędu albo błąd na ścieżce sukcesu. Port
błędu musi dokądś prowadzić, a obie ścieżki mogą się połączyć w `logic.merge`.

`error.handle` przyjmuje ten błąd na porcie `in` i wychodzi pierwszą gałęzią,
której `code` i `retryable` pasują, albo gałęzią `default`, która musi być
podłączona. `error.raise` kończy swoją gałąź błędem o kodzie, komunikacie i
szczegółach ustalonych przez autora.

Niektórych błędów nigdy się nie kieruje. Odebrany dostęp, wyczerpany budżet
(runa albo agenta), anulowany run, miniony termin, limit węzłów na run i efekt o
nieznanym wyniku kończą run bez względu na to, jak połączono graf. Konflikt
rewizji albo błąd walidacji można skierować, ale nigdy nie jest ponawiany na
ślepo, bo te same dane wejściowe zawiodą tak samo.

::: app.workflows.contracts.policy.NodePolicy

::: app.workflows.contracts.policy.RetryPolicy

::: app.workflows.nodes.error_handle._handler.ErrorHandleConfig

::: app.workflows.nodes.error_handle._handler.HandledError

::: app.workflows.nodes.error_raise._handler.ErrorRaiseConfig

## Pętle { #loops }

`control.foreach` uruchamia swoje ciało raz dla każdego elementu zbindowanej
listy `items`, po jednym elemencie i po kolei. Potem idzie dalej portem `done` z
`results` w kolejności wejścia, `errors` i `count`. Ciało zaczyna się od
`loop.item`, podłączonego z portu `body` pętli, który udostępnia `item`, `index`
i `count`. Kończy się na `loop.yield`, którego zbindowane `value` jest wynikiem
iteracji. Żadna krawędź nie prowadzi z powrotem do pętli. Krok w ciele może
bindować do wszystkiego, co działało przed pętlą, a nic spoza ciała nie może
bindować do jego wnętrza.

Lista zostaje zamrożona, gdy pętla startuje, więc iteracja nigdy nie widzi
źródła, które zmieniło się w trakcie runa. Lista dłuższa niż
`WORKFLOW_FOREACH_MAX_ITEMS` albo większa niż
`WORKFLOW_FOREACH_MAX_MANIFEST_BYTES` jest odrzucana, a nie przycinana. Pusta
lista daje `results: []` bez uruchamiania ciała. Kroki każdej iteracji działają
we własnym zakresie, z własnymi próbami, kluczami idempotencji i kosztami.
Następna iteracja jest planowana w transakcji, która kończy poprzednią, więc
restart wznawia od właściwego indeksu i nigdy nie powtarza potwierdzonego zapisu.
Zatwierdzenie wewnątrz iteracji wznawia tę samą iterację.

Przy `item_error_policy: stop`, domyślnym, pętla kończy się błędem przy
pierwszej nieudanej iteracji, a szczegóły błędu niosą `scope_path` tej
iteracji. Przy `collect` wynik elementu to `null`, błąd trafia do `errors`, a
pętla działa dalej. Pętle zagnieżdżają się najwyżej na
`WORKFLOW_FOREACH_MAX_DEPTH` poziomów, a każdy przebieg węzła, który tworzy run,
liczy się do `WORKFLOW_RUN_MAX_NODE_RUNS`. Nie ma pętli `while` ani
równoległego map.

::: app.workflows.nodes.control_foreach._handler.ForeachConfig

::: app.workflows.nodes.control_foreach._handler.ForeachOutput

::: app.workflows.nodes.loop_item._handler.LoopItemOutput

## Virtual Tables { #virtual-tables }

Siedem węzłów czyta i zapisuje [Virtual Tables](../virtual-tables.md) przez ten sam
serwis, którego używają konsola, API i narzędzia tabel agenta. Walidacja, konflikty
rewizji, limity, historia, paragony i audyt są takie same na każdej powierzchni.

| Węzeł | Co robi | Efekt |
|---|---|---|
| `table.record.create` | Dodaje rekord | write |
| `table.record.upsert` | Tworzy albo aktualizuje rekord z external id | write |
| `table.record.update` | Zmienia część komórek rekordu | write |
| `table.record.delete` | Usuwa rekord, zachowując jego historię | write |
| `table.record.get` | Znajduje jeden rekord po id albo external id | read |
| `table.record.query` | Czyta jedną stronę rekordów, z filtrem i sortowaniem | read |
| `table.create` | Tworzy nową tabelę z typowanym schematem | write |

Każdy węzeł rekordów przypina swoją tabelę w konfiguracji. Przy publikacji jest ona
sprawdzana względem autora grafu, a przy każdym runie ponownie jako principal runa.
Wartości są bindowane i podawane po id albo etykiecie kolumny. Rekord wraca z
wartościami dwa razy: `values` po id kolumny, do bindingów, i `fields` po etykiecie,
do czytania. Klucz, który nie wskazuje żywej kolumny, kończy się błędem
`UNKNOWN_COLUMN`.

Zapis niesie klucz operacji kroku, więc ponowiony krok odtwarza swój pierwszy zapis.
Update, upsert albo delete bez zbindowanej rewizji zapisuje przy bieżącej rewizji
rekordu, odczytanej pod blokadą rekordu, a odtworzenie działa nawet wtedy, gdy pierwszy
zapis już przesunął tę rewizję. Rewizja, która się przesunęła, to `REVISION_CONFLICT`, który nie jest ponawiany: ta sama rewizja
skonfliktowałaby się znowu, więc skieruj go przez `error.handle` do świeżego odczytu.
Brakujący rekord to `found: false` z `table.record.get`, a nie błąd.
`table.record.query` czyta najwyżej 100 rekordów na stronę i podaje `has_more`.
Nigdy sam nie czyta całej dużej tabeli.

`table.create` to osobny węzeł i wymaga `tables:create`. Jego wyjście niesie nową
tabelę jako referencję, do której można zbindować `table` kolejnego węzła, oraz id
każdej kolumny po etykiecie. Tabeli, którą czyta albo zapisuje żywy workflow, ani
kolumny, którą przypina, nie da się zarchiwizować, dopóki używa jej bieżąca wersja
tego workflow.

Cztery kolejne kroki odczytują, jakie tabele ma organizacja, i niczego nie
zmieniają.

| Krok | Robi | Wychodzi przez |
|---|---|---|
| `table.list` | wymienia tabele widoczne dla podmiotu, szukane po nazwie | `out`, z `tables` i `total` |
| `table.describe` | czyta nazwę i kolumny jednej tabeli | `out`, z `columns` |
| `table.exists` | czy istnieje tabela o dokładnie tej nazwie | `yes`, z jej id, albo `no` |
| `table.record.exists` | czy jakikolwiek rekord pasuje do filtrów | `yes`, z id pierwszego, albo `no` |

`table.exists` porównuje całą nazwę bez względu na wielkość liter, więc workflow
może utworzyć swoją tabelę przy pierwszym uruchomieniu, a potem jej używać. Oba
pytania wychodzą dokładnie jednym portem, a `logic.merge` może z powrotem
połączyć gałęzie.

::: app.workflows.nodes.table_list._handler.TableListOutput

::: app.workflows.nodes.table_describe._handler.TableDescribeOutput

::: app.workflows.nodes.table_record_exists._handler.TableRecordExistsConfig

::: app.workflows.nodes._tables.TableRecordOutput

::: app.workflows.nodes.table_record_get._handler.TableRecordLookup

::: app.workflows.nodes.table_record_query._handler.TableRecordQueryConfig

::: app.workflows.nodes.table_create._handler.TableCreateConfig

::: app.workflows.nodes.table_create._handler.TableCreatedOutput

## Pliki { #files }

Plik, który tworzy krok, jest zapisywany jako plik jego runa i przekazywany dalej
jako `FileRef`: id, typ, jakim okazały się jego bajty, i rozmiar. Krok czyta plik
tylko wtedy, gdy utworzył go jego własny run albo run został z nim uruchomiony -
`FileRef` powiązany w grafie, sprawdzany przy publikacji wobec runa, który autor
widzi. Każdy inny plik, innej organizacji albo innego runa, to `FILE_NOT_FOUND`, więc
znajomość id niczego nie daje. Pliki runa są wymienione i do pobrania na jego stronie.

| Węzeł | Robi | Efekt |
|---|---|---|
| `http.download` | Pobiera plik przez HTTP, strumieniowo, i go zapisuje | write |
| `http.upload` | Wysyła plik do endpointu HTTP, strumieniowo z magazynu | write |
| `file.read` | Czyta plik jako tekst, wartość JSON albo wiersze CSV | read |
| `file.write` | Zapisuje tekst, wartość JSON albo wiersze jako plik | write |
| `text.extract` | Tekst pliku TXT, JSON, CSV, tekstowego PDF albo DOCX | read |
| `convert.csv_to_json` | Plik CSV jako plik JSON z wierszami | write |
| `convert.json_to_csv` | Lista płaskich obiektów JSON jako plik CSV | write |
| `convert.text_to_file` | Tekst jako plik TXT | write |
| `convert.pdf_to_png` | Wybrane strony PDF jako obrazy PNG | write |
| `image.transform` | Przycina, skaluje, obraca albo konwertuje obraz | write |

Pobieranie stosuje te same reguły SSRF i poświadczeń co `http.request`, do pięciu
przekierowań. Jego treść jest liczona w trakcie napływu i odrzucana powyżej
`max_bytes`, a typ jest rozpoznawany po bajtach, więc nagłówek nie oszuka
`expected_content_types`. `text.extract` nie robi OCR: zeskanowana strona kończy
krok błędem `TEXT_EXTRACTION_NEEDS_OCR` i wymienia strony. Uszkodzony dokument to
`DOCUMENT_CORRUPT`, dokument Word, który rozpakowuje się ponad limity archiwum
obowiązujące upload na czacie, to `DOCUMENT_TOO_LARGE`, a PDF chroniony hasłem
`DOCUMENT_ENCRYPTED`.

Obraz jest mierzony, zanim zostanie zdekodowany. Jego szerokość razy wysokość, obszar
przycięcia i żądany rozmiar są każdy sprawdzane wobec `CHAT_IMAGE_MAX_PIXELS`, a
wynik nie niesie żadnych metadanych źródła. Każdy krok, który zapisuje plik, zapisuje
nowy przy każdej próbie, więc jest `at_least_once`.

::: app.workflows.nodes.http_download._handler.HttpDownloadConfig

::: app.workflows.nodes.http_upload._handler.HttpUploadConfig

::: app.workflows.nodes.file_read._handler.FileReadConfig

::: app.workflows.nodes.text_extract._handler.TextExtractOutput

::: app.workflows.nodes.convert_pdf_to_png._handler.ConvertPdfToPngConfig

::: app.workflows.nodes.image_transform._handler.ImageTransformConfig

## Python { #python }

Dwa węzły uruchamiają Pythona, do dwóch rodzajów pracy.

`code.python.simple` uruchamia krótki skrypt w sandboxie Monty, który nie ma systemu
plików, sieci i ma małą bibliotekę standardową. Skrypt czyta powiązane wartości jako
`args`, a jego ostatnie wyrażenie jest `result` kroku, które musi być wartością JSON.
Tylko liczy, więc jest `pure` i wymaga `code:execute`.

`code.python.sandbox` uruchamia pełnego Pythona z pakietami i plikami runa na
połączeniu `sandboxd` organizacji i wymaga `sandbox:execute`. Skrypt znajduje pliki
wejściowe w `inputs`, zapisuje pliki do `outputs` i ustawia `result`. To trwałe
zadanie: pierwsze wysłanie uruchamia je w tle, a każde kolejne sprawdza je w tej samej
sesji, więc zrestartowany worker łączy się ponownie, zamiast uruchamiać je od nowa. Do
sandboxa nigdy nie trafia żadne poświadczenie platformy, a to, do czego skrypt sięga
poza swoimi plikami, zależy od konfiguracji runtime'u hosta - do niezaufanej pracy
wybierz runtime bez sieci.

| Co się stało | Wynik |
|---|---|
| Wynik nie jest JSON-em | `PYTHON_OUTPUT_NOT_JSON` |
| Skrypt rzucił wyjątek albo przekroczył limit | `PYTHON_ERROR` |
| Zadanie przekroczyło `timeout_seconds` | `PYTHON_SANDBOX_TIMEOUT`, sesja wyczyszczona |
| Brak używalnego połączenia `sandboxd` | `SANDBOX_UNAVAILABLE` |
| Zapisał więcej niż 20 plików albo 100 MB albo wypisał więcej niż 10 MB | `PYTHON_OUTPUT_TOO_LARGE`, zmierzone w sandboksie, zanim cokolwiek zostanie pobrane, a sesja wyczyszczona |
| Nie udało się połączyć z hostem | `SANDBOX_UNREACHABLE`, ponawiane |

::: app.workflows.nodes.code_python_simple._handler.PythonSimpleConfig

::: app.workflows.nodes.code_python_sandbox._handler.PythonSandboxConfig

::: app.workflows.nodes.code_python_sandbox._handler.PythonSandboxOutput

## JavaScript { #javascript }

`code.javascript.sandbox` uruchamia JavaScript na Node jako to samo trwałe
zadanie, na tym samym połączeniu `sandboxd`, i wymaga `sandbox:execute`. Skrypt
jest ciałem funkcji asynchronicznej: czyta powiązane wartości jako `args`, swoje
pliki wejściowe w `inputs`, zapisuje pliki do `outputs`, może używać `await`, a
to, co zwróci przez `return`, jest `result` kroku - `null`, gdy nie zwraca
niczego. `require` ładuje moduły samego Node i to, co runtime ma zainstalowane.
Wybierz runtime z Node.

Jego błędy są błędami sandboxa Pythona, nazwanymi dla JavaScriptu: rzucony błąd
to `JAVASCRIPT_ERROR`, wynik, który nie jest wartością JSON - funkcja, `BigInt` -
to `JAVASCRIPT_OUTPUT_NOT_JSON`, a limit czasu i limity wyjścia to
`JAVASCRIPT_SANDBOX_TIMEOUT` i `JAVASCRIPT_OUTPUT_TOO_LARGE`.

::: app.workflows.nodes.code_javascript_sandbox._handler.JavaScriptSandboxConfig

::: app.workflows.nodes.code_javascript_sandbox._handler.JavaScriptSandboxOutput

## Dodawanie węzła { #adding-a-node }

Węzeł to paczka w `backend/app/workflows/nodes/`: `__init__.py` rejestruje
`NodeDefinition`, `_handler.py` go implementuje, a `README.md` wyjaśnia, po co
istnieje. `load_builtins` importuje paczkę.
`tests/test_workflow_node_layout.py` pilnuje tego układu. Handler zwraca
`Completed`, `Waiting`, `Failed` albo `Uncertain` i nigdy nie rzuca wyjątku. Run,
dla którego działa, czyta z `app.services.workflow_execution.context.current()`.

Typowany węzeł deklaruje trzy modele Pydantic: konfigurację, ustawianą w edytorze i
zamrażaną przy publikacji; wejście, którego pola wypełniają bindingi; oraz wyjście, do
którego bindują się późniejsze kroki. `extra="forbid"` na każdym z nich trzyma literówkę
z dala od opublikowanego grafu. `retry_guarantee` wybierz według tego, co zrobiłoby
powtórzenie wywołania: `idempotent`, gdy handler sam czyni powtórzenie nieszkodliwym -
zapis do tabeli przekazuje `operation_key()` - `at_least_once`, gdy powtórzenie jest
dopuszczalne, i `none`, gdy nie jest. Węzeł, który czyta albo zapisuje zasób, deklaruje
`check_resources`, które publikacja uruchamia względem autora, a każdy run względem
swojego principala.

Konsola rysuje węzeł z jego definicji, z ikoną i odcieniem w
`frontend/src/components/workflows/node-visuals.ts`. Przetestuj handler bezpośrednio pod
kątem odmów i przeprowadź go raz przez `tests/integration/workflow_run_support.py`, żeby
jego konfiguracja, bindingi i wyjście zostały dowiedzione w prawdziwym runie.

::: app.workflows.contracts.definition.NodeDefinition
