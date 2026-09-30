---
source_sha: "c43c27daa5da"
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
  Menschen an. Die eigene [Policy](#error-handling) eines Knotens legt fest, wie
  oft er wiederholt wird, wie lange ein Aufruf dauern darf und wohin ein Fehler
  geht.

## Trigger { #triggers }

Ein Workflow startet mit einem Trigger, dem Knoten, mit dem sein Graph beginnt. Das
Veröffentlichen einer Version schaltet ihren Trigger ein; siehe
[Einen Workflow von außerhalb der Konsole starten](../workflows.md#starting-a-workflow-from-outside-the-console).
Jeder Trigger gibt den folgenden Schritten das weiter, womit seine Oberfläche den Run
gestartet hat, beim Annehmen des Runs eingefroren und höchstens
`WORKFLOW_RUN_MAX_INPUT_BYTES`. Ein Test-Run, der mit einer Eingabe anderer Form
gestartet wird, lässt den Trigger mit `TRIGGER_INPUT_INVALID` fehlschlagen. Ein zweiter
Trigger oder ein Trigger, mit dem der Graph nicht beginnt, wird beim Veröffentlichen
abgelehnt.

### core.input { #core-input }

**API request.** Über eine HTTP-Anfrage oder einen WebSocket gestartet. Seine ID bleibt `core.input`, sodass ein Graph, der geschrieben wurde, bevor Manual und API getrennt waren, weiter über die API startet. Er gibt
dem Graphen die Eingabe des Runs als `payload`, was auch immer der Aufrufer gesendet
hat, und nennt die Oberfläche in `triggered_by`.

::: app.workflows.contracts.io.WorkflowInputPayload

Seine **Eingabefelder** machen die Eingabe zu einem Vertrag. Ein Feld hat einen
Namen, einen Typ - Text, Zahl, ganze Zahl, ja oder nein, Datum oder Auswahl - und ob
es Pflicht ist. Ohne Felder nimmt ein Run jedes JSON-Objekt. Mit Feldern fragt
**Start a run** jedes beim Namen ab, ein Run, dessen Eingabe eines fehlt, eines vom
falschen Typ oder ein nicht deklariertes sendet, wird vor dem Start mit
`WORKFLOW_RUN_INPUT_INVALID` abgelehnt, und ein Binding an `payload.<feld>` wird beim
Veröffentlichen auf seinen Typ geprüft.

::: app.workflows.nodes.core_input._handler.InputField

### trigger.manual { #trigger-manual }

**Manual.** Von einer Person gestartet - **Run** im Editor oder **Start a run** auf
seiner Run-Seite. Er gibt dem Graphen dasselbe wie **API request** und nimmt
dieselben Eingabefelder, nach denen der Editor vor dem Start fragt.

### trigger.chat { #trigger-chat }

**Chat message.** Von einer Nachricht im Chat gestartet, in dem dieser Workflow zum
Antworten gewählt ist. Der Text seines `core.output` wird in diese Unterhaltung
zurückgeschrieben.

::: app.workflows.nodes._triggers.ChatTriggerOutput

### trigger.webhook { #trigger-webhook }

**Webhook.** Von einer signierten Zustellung an die eigene Adresse des Workflows
gestartet, die die erste Veröffentlichung des Knotens zusammen mit seinem
Signatur-Secret anlegt.

Vor der Veröffentlichung öffnet **Listen for test event** im Output-Bereich des
Triggers für zwei Minuten eine Test-URL für den Entwurf. Der eine Aufruf an sie,
ein JSON-Objekt, wird als Ausgabe des Triggers angeheftet, sodass jeder Schritt
danach mit einer echten Zustellung getestet werden kann. Die Test-URL prüft keine
Signatur und startet nie einen Run.

::: app.workflows.nodes._triggers.WebhookTriggerOutput

### trigger.schedule { #trigger-schedule }

**Schedule.** Nach der Uhr gestartet, in der Zeitzone des Workflows und höchstens einmal
pro Minute.

::: app.workflows.nodes._triggers.ScheduleTriggerConfig

::: app.workflows.nodes._triggers.ScheduleTriggerOutput

### trigger.table_record { #trigger-table-record }

**New table record.** Von einem Datensatz gestartet, der seiner Tabelle hinzugefügt
wird und beim Hinzufügen jedem Filter entspricht. Das Veröffentlichen braucht
Lesezugriff auf die Tabelle.

::: app.workflows.nodes._triggers.TableRecordTriggerConfig

::: app.workflows.nodes._triggers.TableRecordTriggerOutput

### trigger.workflow_call { #trigger-workflow-call }

**Called by a workflow.** Vom Schritt `workflow.run` eines anderen Workflows
gestartet, mit den Feldern, die er deklariert - denselben wie bei **Manual** - und nie
von Hand oder über die API. Die Eingabe des Aufrufers wird vor dem Start dagegen
geprüft.

### trigger.workflow_failed { #trigger-workflow-failed }

**On failure of a workflow.** Einmal für jeden fehlgeschlagenen echten Lauf eines
Workflows gestartet, dessen Einstellungen diesen als Fehler-Workflow nennen, als das
Mitglied, das ihn gewählt hat. Ein von diesem Auslöser gestarteter Lauf startet selbst
nie einen Fehler-Workflow.

::: app.workflows.nodes._triggers.WorkflowFailedTriggerOutput

## core.output { #core-output }

Womit der Workflow antwortet. Seine gebundenen Felder werden zum `output` des
Runs, den die API zurückgibt und die aufrufende Oberfläche zustellt. Er hat
dieselben Felder wie die Ausgabe von `agent.run`, sodass die Antwort eines Agents
direkt gebunden werden kann. Eine Ausgabe ohne Bindings ist eine leere Antwort.

::: app.workflows.contracts.io.WorkflowOutputPayload

## webhook.respond { #webhook-respond }

**Respond to webhook.** Beantwortet die Zustellung, die den Run gestartet hat, mit
einem Status (200 bis 599), Headern und einem JSON-`body`, der aus einem früheren
Schritt gebunden ist. Eine Zustellung an einen Graphen mit diesem Schritt wartet
auf ihn, statt `202` zu bekommen, höchstens
`WORKFLOW_WEBHOOK_RESPONSE_TIMEOUT_SECONDS` lang. Der erste abgeschlossene
Respond-Schritt ist die Antwort, eine Wiederholung derselben Zustellung bekommt
sie erneut, und der Run läuft danach weiter. Ein Run, der endet, ohne den Schritt
zu erreichen, antwortet `202`, wenn er erfolgreich war, und sonst `500`. Header,
die der eigenen Antwort der API gehören, werden beim Veröffentlichen abgelehnt:
Framing, `Content-Type`, `Set-Cookie` sowie die CORS- und Browser-Policy-Header.

::: app.workflows.nodes.webhook_respond.WebhookRespondConfig

## data.map { #data-map }

Baut aus früheren Ausgaben einen kleinen, typisierten Datensatz. Jedes Mapping
liest einen Wert mit einem JMESPath-Ausdruck und wandelt ihn in `string`,
`number`, `integer`, `boolean`, `json`, `file_ref` oder `table_ref` um. Ein Wert,
der sich nicht umwandeln lässt, schlägt mit `MAPPING_COERCION_FAILED` fehl und
nennt das Feld.

::: app.workflows.nodes.data_map._handler.DataMapConfig

::: app.workflows.nodes.data_map._handler.FieldMapping

## data.filter und data.combine { #data-filter-and-data-combine }

**Filter a list** behält die Elemente einer gebundenen Liste, für die eine
JMESPath-Bedingung über `item` und `index` gilt, und sagt, wie viele es verworfen
hat. **Combine lists** macht aus `first` und `second` eine Liste: `append` hängt die
zweite an, `by_position` vereint die Objekte an derselben Position, und `by_key`
vereint jedes Objekt der ersten mit dem Objekt der zweiten mit demselben `key`. Hat
ein Feld beide, gewinnt die zweite; elementweises Vereinen braucht Objekte und
scheitert sonst mit `COMBINE_NEEDS_OBJECTS`.

::: app.workflows.nodes.data_filter._handler.DataFilterConfig

::: app.workflows.nodes.data_combine._handler.DataCombineConfig

## Transform { #transform }

Die **Transform**-Schritte formen eine Liste von Objekten ohne Code-Schritt um. Jeder
nimmt `items`, eine aus einem früheren Schritt gebundene Liste, und die meisten geben
`items` weiter, sodass sie sich verketten lassen.

| Schritt | Tut |
|---|---|
| `transform.edit_fields` | Setzt Felder aus JMESPath-Ausdrücken über jedes `item`, entfernt Felder oder behält nur die gesetzten |
| `transform.sort` | Sortiert der Reihe nach nach Feldern, auf- oder absteigend |
| `transform.limit` | Behält die ersten oder die letzten Elemente |
| `transform.remove_duplicates` | Behält das erste jeder Gruppe von Elementen, die auf den genannten Feldern oder ganz gleich sind |
| `transform.aggregate` | Sammelt die Werte jedes Felds über alle Elemente in einer Liste je Feld, als `values` |
| `transform.split_out` | Macht aus einer Liste in jedem Element eigene Elemente |
| `transform.summarize` | Zählt, summiert, mittelt, findet das Kleinste oder Größte oder zählt verschiedene Werte, je Gruppe |
| `transform.date_time` | Jetzt oder ein gebundener `value`, um eine Menge verschoben und in einer Zeitzone geschrieben - der des Workflows, sofern der Schritt keine nennt |
| `transform.crypto` | Hasht oder base64-kodiert den gebundenen `text` oder erzeugt eine UUID oder zufälliges Hex |

Ein Feld ist ein Pfad mit Punkten, `customer.email`, und ein Element ohne es ist nie
ein Fehler. Sort stellt es ans Ende, Remove duplicates behandelt „fehlt“ als eigenen
Wert, Aggregate und Summarize lassen es aus, Split out behält das Element unverändert,
und Edit fields setzt `null`, wo sein Ausdruck nichts findet. Crypto ist nicht für
Geheimnisse gedacht: Nichts darin verwendet einen Schlüssel.

Verkettet beantworten sie häufige Fragen ohne Code-Schritt:

- **Die besten Leads, jeder einmal** - **Remove duplicates** nach `email`, **Sort**
  nach `score` absteigend, **Limit** auf 10, dann **Edit fields**, das nur `name` und
  `score` behält, bereit für eine Nachricht.
- **Summen je Region** - **Split out** `lines`, sodass jede Bestellposition ein Element
  ist, dann **Summarize** die `sum` von `amount`, gruppiert nach `region`: ein Element
  je Region mit `sum_amount`.
- **Eine Liste von Adressen** - **Aggregate** `email` gibt `values.email` weiter, alle
  Adressen in einer Liste, für jede Einstellung, die eine Liste nimmt.

Jeder Schritt liest `items` aus dem vorigen. `tests/integration/test_workflow_transform_composed.py`
führt die ersten beiden genau so aus.

::: app.workflows.nodes.transform._handler.EditFieldsConfig

::: app.workflows.nodes.transform._handler.SummarizeConfig

::: app.workflows.nodes.transform._handler.DateTimeConfig

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

## logic.switch { #logic-switch }

**Switch.** Schickt den Lauf in den ersten von vielen Zweigen, dessen Regel gilt.
Jede Regel hat einen Namen, der Port ihres Zweigs ist, und eine JMESPath-Bedingung
über den gebundenen `value`, der Reihe nach geprüft; `otherwise` übernimmt, wenn
keine gilt. Die Zweige laufen in einem `logic.merge` zusammen, der sie annimmt, weil
stets genau einer genommen wird. Eine Regel, die an ihren Daten scheitert, lässt
den Schritt mit `CONDITION_FAILED` scheitern und nennt die Regel.

::: app.workflows.nodes.logic_switch._handler.LogicSwitchConfig

::: app.workflows.nodes.logic_switch._handler.LogicSwitchOutput

## knowledge.search { #knowledge-search }

Durchsucht Wissens-Collections nach einer gebundenen `query` und gibt die
Passagen als typisierte Quellen zurück, die beste zuerst. Ein leeres Ergebnis ist
eine erfolgreiche Suche. Eine Collection, die nicht mehr existiert oder die der
Principal des Runs nicht mehr lesen darf, lässt den Schritt mit
`COLLECTION_NOT_ACCESSIBLE` fehlschlagen. Der Schritt durchsucht nie weniger
Collections, als der Graph nennt.

::: app.workflows.nodes.knowledge_search._handler.KnowledgeSearchConfig

::: app.workflows.contracts.io.SourceRef

## Entscheidungen { #decisions }

Drei Schritte stellen TypeSafes Jev eine typisierte Frage zu einem gebundenen
`text`, mit einem TypeSafe-API-Key aus dem Vault. Jev schreibt keinen Text: Er
beantwortet die Frage mit einer Konfidenz von 0 bis 1, in einer Anfrage, und kann
nur mit einer der Antworten antworten, die der Schritt zulässt. Unter dem
`min_confidence` des Schritts verlässt er ihn stattdessen über seinen Port
`unsure`, sodass ein Workflow dort entscheidet, was ein Mensch oder ein Agent mit
einem zweifelhaften Fall tut.

| Schritt | Fragt | Verlässt über |
|---|---|---|
| `decide.yes_no` | eine Ja-oder-Nein-Frage | `yes`, `no` oder `unsure` |
| `decide.choose` | welche von bis zu 255 Optionen passt | `out` mit der `choice`, oder `unsure` |
| `decide.score` | wo der Text auf einer Skala von 2 bis 10 Stufen liegt | `out` mit dem `score`, oder `unsure` |

Der Key wird beim Veröffentlichen geprüft und bei jedem Run neu gelesen. Ein Key,
der weg oder nicht mehr geteilt ist, lässt den Schritt mit `SECRET_NOT_USABLE`
fehlschlagen, ein Modell, das nicht antwortet, mit `DECISION_FAILED`, das nach der
Policy des Schritts wiederholt wird, und eine Bereitstellung ohne das Extra
`browser` mit `DECISION_MODEL_UNAVAILABLE`. Ein Merge darf die Zweige einer
Entscheidung wieder zusammenführen, wie die eines If-/Else-Schritts.

::: app.workflows.nodes._decide.DecisionConfig

::: app.workflows.nodes.decide_choose._handler.ChooseConfig
    options:
      show_bases: false

::: app.workflows.nodes.decide_score._handler.ScoreConfig
    options:
      show_bases: false

## Kanäle { #channels }

Slack, Mattermost und Telegram haben jeweils eine eigene Gruppe von Schritten, die
als einer der Bots der Organisation auf dieser Plattform handeln, über denselben
Adapter, über den seine Antworten gehen. Eine Nachricht, die ein Workflow sendet,
kommt also von diesem Bot, und ein Schritt kann lesen, was der Bot lesen darf. Eine
Plattform hat nur die Schritte, die ihre Bots ausführen können.

| Schritt | Slack | Mattermost | Telegram | Gibt weiter |
|---|---|---|---|---|
| **Send a message** (`<platform>.message.send`) | ja | ja | ja | wohin sie ging |
| **Read messages** (`<platform>.messages.read`) | ja | ja | - | `messages`, älteste zuerst |
| **List members** (`<platform>.members.list`) | ja | ja | Administratoren | `members`, mit ihren Plattform-IDs |
| **Find channels** (`<platform>.channels.find`) | ja | ja | - | `channels` |

Ein Schritt nimmt nur einen Bot seiner eigenen Plattform, und ein Bot spricht für
die ganze Organisation, darum braucht das Handeln als Bot `channels:manage`: der
Autor des Graphen zum Veröffentlichen, der Principal des Runs bei jedem Run. Ein
gelöschter, abgeschalteter oder zu einer anderen Plattform gehörender Bot lässt den
Schritt mit `CHANNEL_NOT_USABLE` fehlschlagen. Eine Plattform, die einen Aufruf zur
Laufzeit ablehnt, mit `CHANNEL_UNSUPPORTED`, und eine, die nicht antwortet, mit
`CHANNEL_CALL_FAILED`. Senden wird nie von selbst wiederholt.

::: app.workflows.nodes._channels.ChannelBotConfig

::: app.workflows.nodes.channel_read._handler.ChannelReadConfig
    options:
      show_bases: false

::: app.workflows.nodes.channel_read._handler.ChannelReadOutput

::: app.workflows.nodes.channel_members._handler.ChannelMembersOutput

::: app.workflows.nodes.channel_find._handler.ChannelFindOutput

## agent.run { #agent-run }

Fragt einen veröffentlichten Agent in genau der Version, die der Schritt
festlegt, über denselben Runner wie Chat und API, mit Budget, Freigaben,
Guardrails und Run-Historie des Agents. Der Run wird mit der Oberfläche
`workflow` festgehalten. Gebundene `sources` werden als nummerierter Kontext an
den Prompt angehängt. Ein freigabepflichtiger Tool-Aufruf hält den Schritt an,
und die Entscheidung setzt denselben Agent-Run fort.

Ein Agent mit eigenem Antwortformat gibt sein Objekt als `structured` weiter.
`structured_output_schema` verlangt stattdessen eine andere Form: Der Agent läuft
mit diesem Schema, und eine Antwort, die es verletzt, geht zum Korrigieren an das
Modell zurück. Das Objekt wird noch einmal geprüft, bevor irgendetwas danach läuft.
Ein Agent, der nie ein passendes liefert, lässt den Schritt mit `AGENT_RUN_FAILED`
fehlschlagen, und eine Antwort ohne Objekt, wo eines verlangt war, mit
`STRUCTURED_OUTPUT_MISMATCH`.

| Wie der Agent-Run endete | Ergebnis des Schritts |
|---|---|
| Completed | Completed |
| Wartet auf Freigabe | Wartet, setzt dann denselben Run fort |
| Budget überschritten | `AGENT_BUDGET_EXCEEDED` |
| Von einem Guardrail blockiert | `AGENT_GUARDRAIL_BLOCKED` |
| Sonst | `AGENT_RUN_FAILED` |

Gebundene `attachments` sind Bilder aus den Dateien des Runs - ein Download, eine
gerenderte PDF-Seite, ein umgewandeltes Foto -, die dem Agenten als Bilder gezeigt
werden statt als Link, den er nicht öffnen kann. Nur PNG, JPEG, WebP und GIF werden
gezeigt. Jede andere Datei scheitert mit `UNSUPPORTED_ATTACHMENT_TYPE`, also lies den
Text eines Dokuments zuerst mit `text.extract`.

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

Die Zugangsdaten gehen als Bearer-Token, Basic-Authentifizierung, ein Header mit
einem Namen deiner Wahl oder, mit `query`, ein URL-Parameter mit einem Namen deiner
Wahl. **Import cURL** im Editor liest einen aus der Doku einer API eingefügten
Befehl in Methode, URL, Header und JSON-Body ein. Zugangsdaten im Befehl bleiben nie
im Schritt: Der Schritt wird so eingestellt, dass er sie genauso sendet, und das
Vault-Formular öffnet sich mit ihnen ausgefüllt.

Ein `GET` kann mit `pagination` seitenweise durch eine Liste gehen: einer nächsten
URL folgen, die die Antwort nennt, einen Cursor zurücksenden oder einen
Seitenparameter hochzählen. Die `items_path`-Elemente jeder Seite werden der Reihe
nach in `items` gesammelt. Das Blättern endet, wenn es keine nächste Seite gibt,
wenn eine Seite keine Elemente hat, oder bei `max_pages`, wobei `complete` dann
falsch ist. Alle Seiten zusammen lesen nicht mehr als `max_response_bytes`, und eine
nächste Seite auf einem anderen Origin bekommt keine Zugangsdaten.

| Was passiert ist | Ergebnis |
|---|---|
| Die URL ist privat, Loopback, Metadata oder nicht http(s) | `URL_REFUSED`, nichts gesendet |
| Die URL liegt außerhalb der Origins des Credentials | `SECRET_ORIGIN_DENIED`, nichts gesendet |
| Die Verbindung wurde nie geöffnet | `HTTP_UNREACHABLE`, wird wiederholt |
| Gesendet, keine Antwort, `GET` oder Idempotenz-Header | `HTTP_NO_RESPONSE`, wird wiederholt |
| Gesendet, keine Antwort, jeder andere Schreibzugriff | Unsicher: Der Run hält für einen Menschen an |
| Nicht 2xx | `HTTP_ERROR_STATUS` oder die Antwort als Ausgabe mit `on_error_status: complete` |
| Größer als das Limit | `RESPONSE_TOO_LARGE` |
| `items_path` einer Seite findet etwas, das keine Liste ist | `PAGE_ITEMS_NOT_A_LIST` |

::: app.workflows.nodes.http_request._handler.HttpRequestConfig

::: app.workflows.nodes.http_request._handler.HttpAuth

::: app.workflows.nodes.http_request._handler.HttpPagination

::: app.workflows.nodes.http_request._handler.HttpRequestOutput

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

## human.approval { #human-approval }

**Ask for approval** hält den Run an, bis eine Person freigibt oder ablehnt, was
er gleich tun wird, und geht dann über `approved` oder `rejected` weiter. Wer
freigibt, liest den `title` des Schritts und die daran gebundenen `details` im
Tab **Approvals** unter Activity oder über `GET /api/v1/workflow-approvals`.
`approvers` nennt, wer entscheiden darf, und diese Personen werden in der App
benachrichtigt; leer darf jeder mit `approvals:decide`. Nach `timeout_hours`
läuft die Anfrage ab, und der Schritt geht über `rejected` mit
`decision: "expired"` weiter. Einen Run abzubrechen bricht seine Anfragen ab.
Jeder Lauf des Schritts fragt einmal, sodass eine Wiederholung oder eine
Schleifeniteration nie zweimal nach demselben fragt.

::: app.workflows.nodes.human_approval._handler.HumanApprovalConfig

::: app.workflows.nodes.human_approval._handler.HumanApprovalOutput

## flow.wait { #flow-wait }

**Wait.** Hält den Lauf am Schritt für `seconds` nach dem Erreichen oder bis zu einem
gebundenen `until` an und geht dann weiter; höchstens dreißig Tage. Der Schritt wird
auf einer Uhr geparkt, deren Dispatch-Zeile dann fällig wird, sodass das Warten einen
Worker-Neustart übersteht und keinen Worker belegt; andere Zweige laufen derweil
weiter. Ein bereits vergangener Zeitpunkt geht sofort weiter, und die Frist des Laufs
gilt weiterhin.

Mit **Wait for a call to the run's resume link** wartet der Schritt stattdessen, bis
die Adresse aufgerufen wird, die ein **Resume link**-Schritt gab, höchstens `seconds`
(dreißig Tage ohne Angabe). Sende an diese Adresse `POST` mit einem JSON-Objekt oder
ohne Inhalt: Der Schritt gibt den Inhalt als `body` weiter, mit `called` true, und der
Lauf geht weiter. Ruft niemand rechtzeitig auf, geht er mit `called` false weiter. Ein
Aufruf, während nichts wartet - bevor der Schritt erreicht ist, nachdem er
weiterging oder wenn der Lauf endete -, wird mit `WORKFLOW_NOT_WAITING` (409)
abgelehnt, und ein Link, der nicht zum Lauf gehört, antwortet `404`.

::: app.workflows.nodes.flow_wait._handler.FlowWaitConfig

::: app.workflows.nodes.flow_wait._handler.FlowWaitOutput

## flow.resume_link { #flow-resume-link }

**Resume link.** Gibt `url` weiter, die Adresse, die die Wait-Schritte dieses Laufs
fortsetzt, die auf einen Aufruf warten - für eine Nachricht oder eine Anfrage vor dem
Wait, damit wer antwortet den Lauf fortsetzen kann. Jeder Lauf hat seine eigene, aus
seiner Id unter dem Geheimnis des Deployments gebildet und niemandem sonst gezeigt: Wer
sie hat, kann den Lauf fortsetzen, daher wird sie nur dorthin geschickt, woher die
Antwort kommen soll.

::: app.workflows.nodes.flow_resume_link._handler.ResumeLinkOutput

## Fehlerbehandlung { #error-handling }

Jeder Knoten nimmt neben seiner Konfiguration eine optionale `policy` an.

| Feld | Standard | Wirkung |
|---|---|---|
| `timeout_seconds` | keiner | Ein Aufruf, der länger läuft, wird abgebrochen. Ein Schritt ohne externen Schreibzugriff oder mit idempotentem Aufruf schlägt mit `NODE_TIMEOUT` fehl und darf wiederholt werden. Ein Schreibzugriff, der schon angekommen sein kann, wird unsicher und hält für einen Menschen an |
| `retry.max_attempts` | `WORKFLOW_RETRY_CEILING` | Versuche insgesamt, der erste eingeschlossen. Wiederholt wird nur ein Fehler, den der Knoten als `retryable` markiert, und das Veröffentlichen lehnt mehr als einen Versuch für einen Schritt ab, dessen Aufruf nicht sicher wiederholbar ist |
| `retry.backoff`, `base_delay_seconds`, `max_delay_seconds` | `exponential`, `2`, `60` | Die Wartezeit zwischen Versuchen: fest oder verdoppelt bis zur Obergrenze |
| `on_error` | `fail_run` | `route` schickt einen Fehler, den die Wiederholungen nicht erledigt haben, über den `error`-Port des Knotens, statt den Run fehlschlagen zu lassen |

Ein Knoten, dessen Policy Fehler umleitet, hat einen zusätzlichen Ausgangsport
`error`. Er trägt den `WorkflowError`: `code`, `message`, `details` und
`retryable`. Die normale Ausgabe des Knotens gibt es nur auf seinen anderen
Ports, daher lehnt das Veröffentlichen ein Binding ab, das auf dem Fehlerpfad
die Ausgabe oder auf dem Erfolgspfad den Fehler liest. Der Fehlerport muss
irgendwohin führen, und beide Pfade dürfen sich in einem `logic.merge` wieder
treffen.

`error.handle` nimmt diesen Fehler an seinem Port `in` an und verlässt ihn über
den ersten Zweig, dessen `code` und `retryable` beide passen, oder über
`default`, der verbunden sein muss. `error.raise` lässt seinen Zweig mit Code,
Meldung und Details fehlschlagen, die der Autor festlegt.

Manche Fehler werden nie umgeleitet. Entzogener Zugriff, ein aufgebrauchtes
Budget (des Runs oder eines Agenten), ein abgebrochener Run, eine verstrichene
Deadline, die Knotengrenze pro Run und ein Effekt mit unbekanntem Ausgang
beenden den Run, wie auch immer der Graph verdrahtet ist. Ein Revisionskonflikt
oder ein Validierungsfehler kann umgeleitet werden, wird aber nie blind
wiederholt, weil dieselbe Eingabe genauso scheitert.

::: app.workflows.contracts.policy.NodePolicy

::: app.workflows.contracts.policy.RetryPolicy

::: app.workflows.nodes.error_handle._handler.ErrorHandleConfig

::: app.workflows.nodes.error_handle._handler.HandledError

::: app.workflows.nodes.error_raise._handler.ErrorRaiseConfig

## Schleifen { #loops }

`control.foreach` führt seinen Rumpf einmal für jedes Element einer gebundenen
Liste `items` aus, ein Element nach dem anderen und in Reihenfolge. Danach geht
es über seinen Port `done` weiter, mit `results` in Eingabereihenfolge, `errors`
und `count`. Der Rumpf beginnt bei `loop.item`, verbunden vom Port `body` der
Schleife, das `item`, `index` und `count` bereitstellt. Er endet bei
`loop.yield`, dessen gebundenes `value` das Ergebnis der Iteration ist. Keine
Kante führt zur Schleife zurück. Ein Schritt im Rumpf darf an alles binden, was
vor der Schleife lief, und nichts außerhalb des Rumpfs darf in ihn hinein
binden.

Die Liste wird beim Start der Schleife eingefroren, daher sieht eine Iteration
nie eine Quelle, die sich während des Runs geändert hat. Eine Liste, die länger
als `WORKFLOW_FOREACH_MAX_ITEMS` oder größer als
`WORKFLOW_FOREACH_MAX_MANIFEST_BYTES` ist, wird abgelehnt statt gekürzt. Eine
leere Liste ergibt `results: []`, ohne den Rumpf auszuführen. Die Schritte jeder
Iteration laufen in einem eigenen Scope, mit eigenen Versuchen,
Idempotenzschlüsseln und Kosten. Die nächste Iteration wird in der Transaktion
geplant, die die vorige beendet, daher setzt ein Neustart beim richtigen Index
fort und wiederholt nie einen bestätigten Schreibzugriff. Eine Freigabe innerhalb
einer Iteration setzt diese Iteration fort.

Mit `item_error_policy: stop`, dem Standard, schlägt die Schleife bei der
ersten fehlgeschlagenen Iteration fehl, und die Details des Fehlers tragen den
`scope_path` dieser Iteration. Mit `collect` ist das Ergebnis des Elements
`null`, der Fehler kommt zu `errors`, und die Schleife läuft weiter. Schleifen
verschachteln sich höchstens `WORKFLOW_FOREACH_MAX_DEPTH` tief, und jeder
Knotenlauf, den ein Run anlegt, zählt gegen `WORKFLOW_RUN_MAX_NODE_RUNS`. Es
gibt keine `while`-Schleife und kein paralleles Map.

::: app.workflows.nodes.control_foreach._handler.ForeachConfig

::: app.workflows.nodes.control_foreach._handler.ForeachOutput

::: app.workflows.nodes.loop_item._handler.LoopItemOutput

## Virtual Tables { #virtual-tables }

Sieben Knoten lesen und schreiben [Virtual Tables](../virtual-tables.md) über
denselben Service, den die Konsole, die API und die Tabellen-Tools eines Agents
nutzen. Validierung, Revisionskonflikte, Kontingente, Historie, Receipts und Audit
sind auf jeder Oberfläche dieselben.

| Knoten | Tut | Effekt |
|---|---|---|
| `table.record.create` | Fügt einen Datensatz hinzu | write |
| `table.record.upsert` | Legt den Datensatz mit einer External ID an oder ändert ihn | write |
| `table.record.update` | Ändert einige Zellen eines Datensatzes | write |
| `table.record.delete` | Löscht einen Datensatz und behält seine Historie | write |
| `table.record.get` | Findet einen Datensatz per ID oder External ID | read |
| `table.record.query` | Liest eine Seite Datensätze, gefiltert und sortiert | read |
| `table.create` | Legt eine neue Tabelle mit typisiertem Schema an | write |

Jeder Datensatz-Knoten legt seine Tabelle in der Konfiguration fest. Beim
Veröffentlichen wird sie gegen den Autor des Graphen geprüft und bei jedem Run erneut
als Principal des Runs. Werte werden gebunden und per Spalten-ID oder Spalten-Label
angegeben. Ein Datensatz kommt mit seinen Werten zweimal zurück: `values` nach
Spalten-ID für Bindings und `fields` nach Label zum Lesen. Ein Schlüssel, der keine
lebende Spalte nennt, schlägt mit `UNKNOWN_COLUMN` fehl.

Ein Schreibzugriff trägt den Operationsschlüssel des Schritts, daher spielt ein
wiederholter Schritt seinen ersten Schreibzugriff erneut ab. Ein Update, Upsert oder
Delete ohne gebundene Revision schreibt bei der aktuellen Revision des Datensatzes,
unter der Sperre des Datensatzes gelesen, und das erneute Abspielen hält auch dann, wenn
der erste Schreibzugriff diese Revision schon weitergesetzt hat.
Eine verschobene Revision ist `REVISION_CONFLICT`, der nicht wiederholt wird: Dieselbe Revision
würde erneut kollidieren, also leite ihn mit `error.handle` zu einem frischen Lesen um. Ein fehlender
Datensatz ist `found: false` aus `table.record.get`, kein Fehler.
`table.record.query` liest höchstens 100 Datensätze pro Seite und meldet `has_more`.
Es liest nie von sich aus eine ganze große Tabelle.

`table.create` ist ein eigener Knoten und braucht `tables:create`. Seine Ausgabe
trägt die neue Tabelle als Referenz, an die das `table` eines späteren Knotens
gebunden werden kann, und die ID jeder Spalte nach Label. Eine Tabelle, die ein
lebender Workflow liest oder schreibt, oder eine Spalte, die er festlegt, kann nicht
archiviert werden, solange die aktuelle Version dieses Workflows sie nutzt.

Vier weitere Schritte lesen, welche Tabellen die Organisation hat, und ändern
nichts.

| Schritt | Tut | Verlässt über |
|---|---|---|
| `table.list` | listet die Tabellen, die der Principal sieht, nach Namen gesucht | `out`, mit `tables` und `total` |
| `table.describe` | liest Namen und Spalten einer Tabelle | `out`, mit `columns` |
| `table.exists` | ob eine Tabelle genau dieses Namens existiert | `yes`, mit ihrer ID, oder `no` |
| `table.record.exists` | ob ein Datensatz zu den Filtern passt | `yes`, mit der ID des ersten, oder `no` |

`table.exists` vergleicht den ganzen Namen ohne Rücksicht auf Groß- und
Kleinschreibung, sodass ein Workflow seine Tabelle beim ersten Lauf anlegen und
danach wiederverwenden kann. Beide Fragen verlassen den Schritt über genau einen
Port, und ein `logic.merge` kann die Zweige wieder zusammenführen.

::: app.workflows.nodes.table_list._handler.TableListOutput

::: app.workflows.nodes.table_describe._handler.TableDescribeOutput

::: app.workflows.nodes.table_record_exists._handler.TableRecordExistsConfig

::: app.workflows.nodes._tables.TableRecordOutput

::: app.workflows.nodes.table_record_get._handler.TableRecordLookup

::: app.workflows.nodes.table_record_query._handler.TableRecordQueryConfig

::: app.workflows.nodes.table_create._handler.TableCreateConfig

::: app.workflows.nodes.table_create._handler.TableCreatedOutput

## Dateien { #files }

Eine Datei, die ein Schritt erzeugt, wird als Datei seines Runs gespeichert und als
`FileRef` weitergegeben: eine ID, der Typ, als der sich ihre Bytes erwiesen haben, und
eine Größe. Ein Schritt liest eine Datei nur, wenn sein eigener Run sie erzeugt hat
oder der Run mit ihr gestartet wurde - ein im Graphen gebundener `FileRef`, beim
Veröffentlichen gegen einen Run geprüft, den der Autor sehen kann. Jede andere Datei,
die einer anderen Organisation oder eines anderen Runs, ist `FILE_NOT_FOUND`, sodass
eine bekannte ID nichts gewährt. Die Dateien eines Runs stehen auf seiner Seite zum
Herunterladen bereit.

| Knoten | Macht | Effekt |
|---|---|---|
| `http.download` | Holt eine Datei per HTTP, gestreamt, und speichert sie | write |
| `http.upload` | Sendet eine Datei an einen HTTP-Endpunkt, gestreamt aus dem Speicher | write |
| `file.read` | Liest eine Datei als Text, JSON-Wert oder CSV-Zeilen | read |
| `file.write` | Speichert Text, einen JSON-Wert oder Zeilen als Datei | write |
| `text.extract` | Der Text einer TXT-, JSON-, CSV-, Text-PDF- oder DOCX-Datei | read |
| `convert.csv_to_json` | Eine CSV-Datei als JSON-Datei mit Zeilen | write |
| `convert.json_to_csv` | Eine JSON-Liste flacher Objekte als CSV-Datei | write |
| `convert.text_to_file` | Text als TXT-Datei | write |
| `convert.pdf_to_png` | Ausgewählte PDF-Seiten als PNG-Bilder | write |
| `image.transform` | Schneidet ein Bild zu, skaliert, dreht oder konvertiert es | write |

Ein Download folgt denselben SSRF- und Credential-Regeln wie `http.request`, bis zu
fünf Weiterleitungen. Sein Body wird beim Eintreffen gezählt und über `max_bytes`
abgelehnt, und sein Typ wird an den Bytes erkannt, sodass ein Header
`expected_content_types` nicht täuschen kann. `text.extract` macht kein OCR: Eine
gescannte Seite lässt den Schritt mit `TEXT_EXTRACTION_NEEDS_OCR` scheitern und nennt
die Seiten. Ein beschädigtes Dokument ist `DOCUMENT_CORRUPT`, ein Word-Dokument, das sich über die
Archivgrenzen eines Chat-Uploads hinaus entpackt, `DOCUMENT_TOO_LARGE`, ein
passwortgeschütztes PDF `DOCUMENT_ENCRYPTED`.

Ein Bild wird vermessen, bevor es dekodiert wird. Seine Breite mal Höhe, ein
Zuschnittsbereich und eine angeforderte Größe werden jeweils gegen
`CHAT_IMAGE_MAX_PIXELS` geprüft, und das Ergebnis trägt keine Metadaten der Quelle.
Jeder Schritt, der eine Datei speichert, speichert bei jedem Versuch eine neue, also
ist er `at_least_once`.

::: app.workflows.nodes.http_download._handler.HttpDownloadConfig

::: app.workflows.nodes.http_upload._handler.HttpUploadConfig

::: app.workflows.nodes.file_read._handler.FileReadConfig

::: app.workflows.nodes.text_extract._handler.TextExtractOutput

::: app.workflows.nodes.convert_pdf_to_png._handler.ConvertPdfToPngConfig

::: app.workflows.nodes.image_transform._handler.ImageTransformConfig

## Python { #python }

Zwei Knoten führen Python aus, für zwei Arten von Arbeit.

`code.python.simple` führt ein kurzes Skript in der Monty-Sandbox aus, die kein
Dateisystem, kein Netzwerk und nur eine kleine Standardbibliothek hat. Das Skript liest
die gebundenen Werte als `args`, und sein letzter Ausdruck ist das `result` des
Schritts, das ein JSON-Wert sein muss. Es rechnet und tut sonst nichts, also ist es
`pure` und braucht `code:execute`.

Im Editor wird das Skript eines Code-Schritts in einem Code-Editor geschrieben:
Python oder JavaScript, in beiden Themes hervorgehoben, Tab und Shift+Tab zum
Einrücken, Enter behält die Einrückung, Klammern und Anführungszeichen schließen
sich beim Tippen, die Klammer am Cursor wird mit ihrem Gegenstück umrahmt, und die Schlüssel des gebundenen `args` werden angeboten, sobald
`args["` oder, in JavaScript, `args.` getippt wird. Esc und dann Tab verlässt den
Editor. **Test step** führt das Skript allein mit dem aus, was die Schritte davor
weitergegeben haben.

`code.python.sandbox` führt vollständiges Python mit Paketen und den Dateien des Runs
auf der `sandboxd`-Verbindung der Organisation aus und braucht `sandbox:execute`. Das
Skript findet seine Eingabedateien in `inputs`, schreibt Dateien nach `outputs` und
setzt `result`. Es ist ein dauerhafter Job: Der erste Dispatch startet ihn im
Hintergrund, und jeder weitere prüft ihn in derselben Sitzung, sodass ein neu
gestarteter Worker sich wieder verbindet, statt ihn erneut zu starten. Kein Credential
der Plattform gelangt je in die Sandbox, und was das Skript über seine Dateien hinaus
erreicht, ist die eigene Konfiguration der Runtime des Hosts - wähle für nicht
vertrauenswürdige Arbeit eine Runtime ohne Netzwerk.

| Was passiert ist | Ergebnis |
|---|---|
| Das Ergebnis ist kein JSON | `PYTHON_OUTPUT_NOT_JSON` |
| Das Skript hat eine Ausnahme ausgelöst oder ein Limit überschritten | `PYTHON_ERROR` |
| Der Job lief länger als `timeout_seconds` | `PYTHON_SANDBOX_TIMEOUT`, Sitzung gelöscht |
| Keine nutzbare `sandboxd`-Verbindung | `SANDBOX_UNAVAILABLE` |
| Es schrieb mehr als 20 Dateien oder 100 MB oder gab mehr als 10 MB aus | `PYTHON_OUTPUT_TOO_LARGE`, in der Sandbox gemessen, bevor etwas abgeholt wird, und die Session gelöscht |
| Der Host war nicht erreichbar | `SANDBOX_UNREACHABLE`, wiederholt |

::: app.workflows.nodes.code_python_simple._handler.PythonSimpleConfig

::: app.workflows.nodes.code_python_sandbox._handler.PythonSandboxConfig

::: app.workflows.nodes.code_python_sandbox._handler.PythonSandboxOutput

## JavaScript { #javascript }

`code.javascript.sandbox` führt JavaScript auf Node als denselben dauerhaften Job
aus, über dieselbe `sandboxd`-Verbindung, und braucht `sandbox:execute`. Das
Skript ist der Rumpf einer async-Funktion: Es liest die gebundenen Werte als
`args`, seine Eingabedateien in `inputs`, schreibt Dateien nach `outputs`, darf
`await` verwenden, und was es per `return` zurückgibt, ist das `result` des
Schritts - `null`, wenn es nichts zurückgibt. `require` lädt Nodes eigene Module
und was die Runtime installiert hat. Wähle eine Runtime mit Node.

Seine Fehler sind die der Python-Sandbox, für JavaScript benannt: ein geworfener
Fehler ist `JAVASCRIPT_ERROR`, ein Ergebnis, das kein JSON-Wert ist - eine
Funktion, ein `BigInt` - ist `JAVASCRIPT_OUTPUT_NOT_JSON`, und Zeitlimit und
Ausgabegrenzen sind `JAVASCRIPT_SANDBOX_TIMEOUT` und `JAVASCRIPT_OUTPUT_TOO_LARGE`.

::: app.workflows.nodes.code_javascript_sandbox._handler.JavaScriptSandboxConfig

::: app.workflows.nodes.code_javascript_sandbox._handler.JavaScriptSandboxOutput

## workflow.run { #workflow-run }

**Run a workflow.** Führt die veröffentlichte Version eines anderen Workflows aus, die
mit **Called by a workflow** beginnt, mit dem gebundenen `input`, so wie dieser Lauf
handelt. Der Schritt wartet, bis der aufgerufene Lauf endet, und gibt dessen `output`
weiter oder scheitert mit `CALLED_WORKFLOW_FAILED` und dem Fehler des aufgerufenen
Laufs; ist **Wait for it to finish** aus, gibt er den gestarteten Lauf sofort weiter.
Der aufgerufene Lauf ist mit dem Schritt und der Kette dieses Laufs verknüpft. Ein
Aufruf eines Workflows, der weiter oben in der Kette schon läuft, scheitert mit
`WORKFLOW_CALL_LOOP`, einer tiefer als fünf Aufrufe mit `WORKFLOW_CALL_TOO_DEEP`. Ein
Testlauf des Entwurfs ruft den veröffentlichten Workflow wirklich auf.

::: app.workflows.nodes.workflow_run._handler.WorkflowRunConfig

::: app.workflows.nodes.workflow_run._handler.WorkflowRunOutput

## Einen Knoten hinzufügen { #adding-a-node }

Ein Knoten ist ein Paket unter `backend/app/workflows/nodes/`: `__init__.py`
registriert eine `NodeDefinition`, `_handler.py` implementiert sie, und
`README.md` erklärt, warum es sie gibt. `load_builtins` importiert das Paket.
`tests/test_workflow_node_layout.py` erzwingt diesen Aufbau. Ein Handler gibt
`Completed`, `Waiting`, `Failed` oder `Uncertain` zurück und wirft nie. Den Run,
für den er läuft, liest er aus `app.services.workflow_execution.context.current()`.

Ein typisierter Knoten deklariert drei Pydantic-Modelle: seine Konfiguration, im
Editor gesetzt und bei der Veröffentlichung eingefroren; seine Eingabe, deren Felder die
Bindungen füllen; und seine Ausgabe, an die sich spätere Schritte binden.
`extra="forbid"` auf jedem hält einen Tippfehler aus einem veröffentlichten Graphen.
Wählen Sie `retry_guarantee` danach, was eine Wiederholung des Aufrufs täte:
`idempotent`, wenn der Handler eine Wiederholung selbst harmlos macht - ein
Tabellen-Schreibzugriff übergibt `operation_key()` -, `at_least_once`, wenn eine
Wiederholung vertretbar ist, und `none`, wenn nicht. Ein Knoten, der eine Ressource
liest oder schreibt, deklariert `check_resources`, das die Veröffentlichung gegen den
Autor und jeder Run gegen seinen Principal ausführt.

Die Konsole zeichnet einen Knoten aus seiner Definition, mit Icon und Tönung in
`frontend/src/components/workflows/node-visuals.ts`. Testen Sie den Handler direkt auf
seine Ablehnungen, und führen Sie ihn einmal über `tests/integration/workflow_run_support.py`
aus, sodass Konfiguration, Bindungen und Ausgabe in einem echten Run belegt sind.

::: app.workflows.contracts.definition.NodeDefinition
