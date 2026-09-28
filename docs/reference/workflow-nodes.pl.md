---
source_sha: "bfbaa450f360"
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
  i nie daje żadnej gwarancji, zatrzymuje się dla człowieka.

## core.input { #core-input }

Miejsce, w którym workflow się zaczyna. Przekazuje grafowi wejście runa jako
`payload`, cokolwiek dostarczyła wywołująca powierzchnia, i nazywa tę
powierzchnię w `triggered_by`. Wejście jest zamrażane przy przyjęciu runa i ma
najwyżej `WORKFLOW_RUN_MAX_INPUT_BYTES`.

::: app.workflows.contracts.io.WorkflowInputPayload

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

## agent.run { #agent-run }

Pyta opublikowanego agenta, dokładnie w wersji przypiętej w kroku, przez ten sam
runner co chat i API, z budżetem, zatwierdzeniami, guardrailami i historią runów
agenta. Run jest zapisywany z powierzchnią `workflow`. Zbindowane `sources` są
dopisywane do promptu jako numerowany kontekst. Wywołanie narzędzia wymagające
zatwierdzenia zatrzymuje krok, a decyzja wznawia ten sam run agenta.

Z `structured_output_schema` odpowiedź musi być obiektem JSON spełniającym
schemat, zanim cokolwiek dalej się wykona. W przeciwnym razie krok kończy się
błędem `STRUCTURED_OUTPUT_MISMATCH`.

| Jak zakończył się run agenta | Wynik kroku |
|---|---|
| Completed | Completed |
| Czeka na zatwierdzenie | Czeka, potem wznawia ten sam run |
| Przekroczony budżet | `AGENT_BUDGET_EXCEEDED` |
| Zablokowany przez guardrail | `AGENT_GUARDRAIL_BLOCKED` |
| Inaczej | `AGENT_RUN_FAILED` |

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

## Dodawanie węzła { #adding-a-node }

Węzeł to paczka w `backend/app/workflows/nodes/`: `__init__.py` rejestruje
`NodeDefinition`, `_handler.py` go implementuje, a `README.md` wyjaśnia, po co
istnieje. `load_builtins` importuje paczkę.
`tests/test_workflow_node_layout.py` pilnuje tego układu. Handler zwraca
`Completed`, `Waiting`, `Failed` albo `Uncertain` i nigdy nie rzuca wyjątku. Run,
dla którego działa, czyta z `app.services.workflow_execution.context.current()`.

::: app.workflows.contracts.definition.NodeDefinition
