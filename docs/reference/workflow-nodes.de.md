---
source_sha: "bfbaa450f360"
---

# Workflow-Knoten { #workflow-nodes }

Jeder Schritt, den ein Workflow enthalten kann: womit er konfiguriert wird, was
er liest, was er erzeugt und was ein Fehler bedeutet. Die Palette im Editor zeigt
dieselben Knoten aus derselben Registry. Die Felddokumentation unten wird aus dem
Quellcode erzeugt und bleibt deshalb auf Englisch.

Einige Regeln gelten für jeden Knoten:

- **Eine Kante legt die Reihenfolge fest, ein Binding trägt einen Wert.** Die
  Eingabefelder eines Knotens werden an frühere Ausgaben, an ein Literal oder an
  eine Datei- oder Tabellenreferenz gebunden. Siehe
  [Einen Knoten konfigurieren](../workflows.md#configuring-a-node).
- **Ein Pfad in einen frei geformten Wert wird geprüft, wenn der Knoten läuft.**
  Die Nutzlast eines Triggers, ein gemappter Datensatz und die strukturierte
  Antwort eines Agents haben keine feste Form, daher wird ein Binding wie
  `payload.email` beim Veröffentlichen angenommen und beim Ausführen des Knotens
  gegen sein Ziel geprüft. Ein Wert, der nicht passt, lässt den Run mit
  `INVALID_BINDING` fehlschlagen, und der Handler sieht ihn nie.
- **Ressourcen werden zweimal geprüft.** Das Veröffentlichen lehnt eine
  Collection, eine Agent-Version, ein Credential oder einen Empfänger ab, die
  der Autor des Graphen nicht erreichen kann. Jeder Run prüft sie erneut gegen
  seinen eigenen Principal, weil der Zugriff dazwischen entzogen werden kann.
- **Effektart und Wiederholungen** entscheiden, was die Engine nach einem Fehler
  tun darf. Ein `pure`- oder `idempotent`-Schritt wird wiederholt. Ein Schritt,
  der bereits gewirkt haben kann und keine Garantie gibt, hält für einen
  Menschen an.

## core.input { #core-input }

Wo ein Workflow beginnt. Er gibt dem Graphen die Eingabe des Runs als `payload`,
was auch immer die aufrufende Oberfläche geliefert hat, und nennt diese
Oberfläche in `triggered_by`. Die Eingabe wird beim Annehmen des Runs
eingefroren und umfasst höchstens `WORKFLOW_RUN_MAX_INPUT_BYTES`.

::: app.workflows.contracts.io.WorkflowInputPayload

## core.output { #core-output }

Womit der Workflow antwortet. Seine gebundenen Felder werden zum `output` des
Runs, den die API zurückgibt und die aufrufende Oberfläche zustellt. Er hat
dieselben Felder wie die Ausgabe von `agent.run`, sodass die Antwort eines Agents
direkt gebunden werden kann. Eine Ausgabe ohne Bindings ist eine leere Antwort.

::: app.workflows.contracts.io.WorkflowOutputPayload

## data.map { #data-map }

Baut aus früheren Ausgaben einen kleinen, typisierten Datensatz. Jedes Mapping
liest einen Wert mit einem JMESPath-Ausdruck und wandelt ihn in `string`,
`number`, `integer`, `boolean`, `json`, `file_ref` oder `table_ref` um. Ein Wert,
der sich nicht umwandeln lässt, schlägt mit `MAPPING_COERCION_FAILED` fehl und
nennt das Feld.

::: app.workflows.nodes.data_map._handler.DataMapConfig

::: app.workflows.nodes.data_map._handler.FieldMapping

## logic.if und logic.merge { #logic-if-and-logic-merge }

`logic.if` wertet eine JMESPath-Bedingung über seinem gebundenen `value` aus und
geht über den Port `true` oder `false` weiter. Jeder Knoten auf dem nicht
genommenen Zweig wird als `skipped` festgehalten. `logic.merge` führt die beiden
Zweige wieder zusammen. Er läuft, sobald der genommene Zweig ihn erreicht, und
gibt dessen Ausgabe als `value` weiter. Das Veröffentlichen prüft, dass die
Eingänge eines Merge einen `logic.if` über verschiedene Ports verlassen, sodass
immer genau einer von ihnen läuft.

Ausdrücke können auswählen, filtern und vergleichen und eine feste Menge reiner
Funktionen aufrufen: `abs`, `avg`, `ceil`, `contains`, `ends_with`, `floor`,
`join`, `keys`, `length`, `max`, `merge`, `min`, `not_null`, `reverse`, `sort`,
`starts_with`, `sum`, `to_array`, `to_number`, `to_string`, `type` und `values`.
Null, `false` sowie ein leerer String, eine leere Liste oder ein leeres Objekt
sind falsch, alles andere ist wahr, auch `0`. Ein Ausdruck, der sich nicht parsen
lässt oder etwas anderes aufruft, kann nicht veröffentlicht werden.

::: app.workflows.nodes.logic_if._handler.LogicIfConfig

::: app.workflows.nodes.logic_merge._handler.LogicMergeOutput

## knowledge.search { #knowledge-search }

Durchsucht Wissens-Collections nach einer gebundenen `query` und gibt die
Passagen als typisierte Quellen zurück, die beste zuerst. Ein leeres Ergebnis ist
eine erfolgreiche Suche. Eine Collection, die nicht mehr existiert oder die der
Principal des Runs nicht mehr lesen darf, lässt den Schritt mit
`COLLECTION_NOT_ACCESSIBLE` fehlschlagen. Der Schritt durchsucht nie weniger
Collections, als der Graph nennt.

::: app.workflows.nodes.knowledge_search._handler.KnowledgeSearchConfig

::: app.workflows.contracts.io.SourceRef

## agent.run { #agent-run }

Fragt einen veröffentlichten Agent in genau der Version, die der Schritt
festlegt, über denselben Runner wie Chat und API, mit Budget, Freigaben,
Guardrails und Run-Historie des Agents. Der Run wird mit der Oberfläche
`workflow` festgehalten. Gebundene `sources` werden als nummerierter Kontext an
den Prompt angehängt. Ein freigabepflichtiger Tool-Aufruf hält den Schritt an,
und die Entscheidung setzt denselben Agent-Run fort.

Mit `structured_output_schema` muss die Antwort ein JSON-Objekt sein, das das
Schema erfüllt, bevor irgendetwas danach läuft. Sonst schlägt der Schritt mit
`STRUCTURED_OUTPUT_MISMATCH` fehl.

| Wie der Agent-Run endete | Ergebnis des Schritts |
|---|---|
| Completed | Completed |
| Wartet auf Freigabe | Wartet, setzt dann denselben Run fort |
| Budget überschritten | `AGENT_BUDGET_EXCEEDED` |
| Von einem Guardrail blockiert | `AGENT_GUARDRAIL_BLOCKED` |
| Sonst | `AGENT_RUN_FAILED` |

Er wird nie automatisch wiederholt, weil ein Agent Tools mit Nebenwirkungen
aufgerufen haben kann.

::: app.workflows.nodes.agent_run._handler.AgentRunConfig

::: app.workflows.nodes.agent_run._handler.AgentRunOutput

## http.request { #http-request }

Ruft eine HTTP-API auf. Jede Anfrage und jede Weiterleitung durchläuft die
SSRF-Prüfung des Deployments und wird an die Adresse gesendet, die diese Prüfung
freigegeben hat. Ein Credential ist ein [HTTP credential](../secrets.md#kinds)
aus dem Vault und wird nur an die Origins gesendet, die das Secret erlaubt. Die
Antwort wird innerhalb von `max_response_bytes` gelesen und ohne `Set-Cookie`,
die Authentifizierungs-Header und das Token zurückgegeben.

| Was passiert ist | Ergebnis |
|---|---|
| Die URL ist privat, Loopback, Metadata oder nicht http(s) | `URL_REFUSED`, nichts gesendet |
| Die URL liegt außerhalb der Origins des Credentials | `SECRET_ORIGIN_DENIED`, nichts gesendet |
| Die Verbindung wurde nie geöffnet | `HTTP_UNREACHABLE`, wird wiederholt |
| Gesendet, keine Antwort, `GET` oder Idempotenz-Header | `HTTP_NO_RESPONSE`, wird wiederholt |
| Gesendet, keine Antwort, jeder andere Schreibzugriff | Unsicher: Der Run hält für einen Menschen an |
| Nicht 2xx | `HTTP_ERROR_STATUS` oder die Antwort als Ausgabe mit `on_error_status: complete` |
| Größer als das Limit | `RESPONSE_TOO_LARGE` |

::: app.workflows.nodes.http_request._handler.HttpRequestConfig

::: app.workflows.nodes.http_request._handler.HttpAuth

::: app.workflows.nodes.http_request._handler.HttpResponseOutput

## notification.send { #notification-send }

Benachrichtigt Mitglieder der Organisation in der App, per E-Mail oder beides,
über das Benachrichtigungszentrum. Empfänger sind Mitglieder, die per ID
angegeben werden. Zur Laufzeit muss jeder noch ein aktives Mitglied sein, das
den Workflow sehen kann, alle anderen werden ausgelassen. Bleibt niemand übrig,
schlägt der Schritt mit `NO_PERMITTED_RECIPIENTS` fehl. Die Einstellungen jeder
Person für **Workflow notifications** gelten weiterhin. Der Schritt ist
abgeschlossen, wenn die Benachrichtigung geschrieben ist, die E-Mail wird danach
zugestellt. Ein wiederholter Schritt schreibt keine zweite Benachrichtigung.

::: app.workflows.nodes.notification_send._handler.NotificationSendConfig

## Einen Knoten hinzufügen { #adding-a-node }

Ein Knoten ist ein Paket unter `backend/app/workflows/nodes/`: `__init__.py`
registriert eine `NodeDefinition`, `_handler.py` implementiert sie, und
`README.md` erklärt, warum es sie gibt. `load_builtins` importiert das Paket.
`tests/test_workflow_node_layout.py` erzwingt diesen Aufbau. Ein Handler gibt
`Completed`, `Waiting`, `Failed` oder `Uncertain` zurück und wirft nie. Den Run,
für den er läuft, liest er aus `app.services.workflow_execution.context.current()`.

::: app.workflows.contracts.definition.NodeDefinition
