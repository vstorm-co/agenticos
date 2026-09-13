---
source_sha: 82fcf03671a3
---

# Der Capability-Katalog { #the-capability-catalog }

Alles, was ein Agent *tun* kann, stammt aus einer von zwei Quellen: aus einer
Capability, die im Code dieses Deployments registriert ist, oder aus einem
[MCP-Server](../mcp.md), den jemand verbunden hat. Diese Seite ist die erste Liste.

Eine Capability ist die Einheit, die sich zu- oder abschalten lässt — eine Zeile im
Builder, ein Eintrag im Spec. Sie ist bewusst nicht „ein Tool“: Die Wissenssuche ist
eine einzige Entscheidung für die Person, die einen Agent konfiguriert, und ob sie
heute eine Funktion bereitstellt und nächsten Monat drei, ist nicht deren Problem.
Capabilities decken außerdem Dinge ab, die gar keine Tools sind — deshalb stehen
`thinking` und `clock` hier ohne aufgeführte Tools.

!!! note "Die API ist maßgeblich, diese Seite ist eine Momentaufnahme"

    `GET /api/v1/agents/capabilities` liefert die Registry so aus, wie sie im
    laufenden Deployment vorliegt, einschließlich allem, was seit dem Schreiben
    dieser Seite hinzugekommen ist. Der Builder zeichnet seine Auswahl und seine
    Konfigurationsformulare aus dieser Antwort. Widersprechen sich die beiden, hat
    die API recht.

## Was ausgeliefert wird { #what-ships }

| id | Name | Kategorie | Tools | Scope | Schlüssel |
|---|---|---|---|---|---|
| `knowledge` | Wissenssuche | knowledge | `search_documents` | `knowledge:read` | — |
| `skills` | Skills | knowledge | `list_skills`, `load_skill`, `read_skill_resource` | `knowledge:read` | — |
| `context` | Kontext | knowledge | `list_context`, `read_context` | — | — |
| `memory_files` | Gedächtnisdateien | knowledge | `list_memory`, `read_memory`, `write_memory`, `edit_memory`, `delete_memory` | — | — |
| `memory_mem0` | Gedächtnis (mem0) | knowledge | `remember`, `recall` | — | erforderlich |
| `conversation_search` | Unterhaltungssuche | knowledge | `search_conversations`, `read_conversation` | `conversations:read` | — |
| `web_research` | Websuche | research | `web_search` | `web:read` | für kostenpflichtige Dienste |
| `web_fetch` | Webabruf | research | `web_fetch` | `web:fetch` | — |
| `browser_use` | Browser-Automatisierung | research | `browse_web` | `web:browse` | über das Extra `browser-use` |
| `code_execution` | Python ausführen | analysis | `run_python` | `code:execute` | — |
| `sandbox` | Dateien & Shell | analysis | `ls`, `read_file`, `glob`, `grep`, `write_file`, `edit_file`, `execute` | `sandbox:execute` | für Daytona |
| `charts` | Diagramme | analysis | `create_chart` | — | — |
| `image_generation` | Bilderzeugung | analysis | `generate_image` | — | erforderlich |
| `subagents` | Delegation | reasoning | `task`, `check_task`, `wait_tasks`, `list_active_tasks`, `answer_subagent`, `send_message_to_subagent`, `soft_cancel_task`, `hard_cancel_task`, `create_agent`, `delegate` | `agents:delegate` | — |
| `planning` | Planung | reasoning | `write_plan`, `read_plan`, `add_task`, `update_task_status`, `update_task_statuses`, `remove_task`, `add_subtask`, `set_dependency`, `get_available_tasks` | — | — |
| `thinking` | Nachdenken | reasoning | keine, mit Absicht | — | — |
| `system_reminders` | Systemerinnerungen | reasoning | keine, mit Absicht | — | — |
| `tool_search` | Tool-Suche | utility | keine, mit Absicht | — | — |
| `clock` | Datum und Uhrzeit | utility | keine, mit Absicht | — | — |
| `guardrails` | Guardrails | utility | keine, mit Absicht | — | — |
| `compaction` | Kontextverwaltung | utility | keine, mit Absicht | — | — |
| `tool_output_limits` | Grenzen für Tool-Ausgaben | utility | `read_tool_result` | — | — |
| `channel_tools` | Chat-Kanal-Abfrage | channels | `get_channel_info`, `list_channel_members`, `search_channels`, `read_channel_history` | — | — |

Sechs davon haben absichtlich keine Tools. `thinking` verändert, wie das Modell
arbeitet, statt was es erreichen kann, `clock` schreibt das Datum in die
Instruktionen, `tool_search` steuert seine Suchfunktion erst bei, sobald es ein
Toolset umschließt, das zurückgestellte Tools enthält — für sich allein deklariert
es nichts —, `guardrails` prüft und überschreibt den Text, der durch einen Run
fließt, `compaction` schreibt die Historie um, die eine Anfrage mitführt, und
`system_reminders` hängt steuernden Text an das Ende der Anfrage. Keine der sechs
lässt etwas übrig, das eine Person genehmigen müsste, also deklariert auch keine
ein Tool. Eine Capability, die wirklich keine Tools hat, sagt das mit `tools=()`,
statt das Argument wegzulassen; siehe
[Eine Capability hinzufügen](../howto/add-capability.md).

**Diese Spalte zeigt, was eine Capability deklariert, und das ist nicht immer das,
was einem Modell angeboten wird.** Die Delegation ist die einzige Stelle, an der
beides auseinandergeht: `create_agent` und `delegate` erscheinen nur unter
`allow_dynamic`, und `answer_subagent` erscheint überhaupt niemandem — beides wird
unten unter [Delegation](#delegation) erklärt.

**Eine davon steht gar nicht in der Toolbox.** `channel_tools` wird pro gebundenem
Bot unter *Where this agent is available* gewählt, und die Veröffentlichung lehnt
einen Spec ab, der diese Capability zu führen versucht — siehe
[Chat-Kanal-Abfrage](#chat-channel-lookup).

## Wissenssuche { #knowledge-search }

`search_documents` — *Durchsucht die Dokumente der Organisation nach Passagen, die
für eine Frage relevant sind.*

Durchsucht die Collections, die der Spec des Agents bindet, und belegt, was es
verwendet hat. Das Modell bestimmt, *was* gesucht wird, niemals *wo*: Die
Collections werden vor dem Run aus dem Spec aufgelöst und der Capability übergeben,
sodass ein Agent keine Collection erreichen kann, die ihm niemand zugeordnet hat.

| Konfiguration | Standard | Bereich |
|---|---|---|
| `default_top_k` | 5 | 1–50 |

`default_top_k` greift nur, wenn das Modell nicht selbst eine Anzahl verlangt.

Ohne gebundene Collections steuert diese Capability **nichts** bei — sie wird gar
nicht erst angehängt. Ein Suchtool, das immer leer zurückkommt, ist schlimmer als
gar kein Suchtool, denn das Modell versucht es weiter und schließt aus dem
Schweigen.

## Skills { #skills }

`list_skills`, `load_skill`, `read_skill_resource`

Aufgeschriebenes Know-how, das der Agent nur lädt, wenn er es für relevant hält,
und zwar einen Skill nach dem anderen — die Alternative wäre ein Instruktionsfeld,
das so lange wächst, bis jeder Run für jede Prozedur bezahlt. Siehe
[Skills](../skills.md) dafür, was ein Skill ist und wie einer in eine Organisation
gelangt.

Diese drei Tools stammen aus `pydantic-ai-skills`, ihre Namen und Formulierungen
liegen also in fremder Hand. Ein Drift-Test vergleicht, was die Registry
deklariert, mit den Tools, die dem Modell tatsächlich angeboten werden — das ist
es, was den Tag meldet, an dem das passiert.

## Kontext { #context }

`list_context`, `read_context`

Der ständige Kontext einer Organisation, der in den Run gelegt wird, statt erfragt
werden zu müssen — ein Glossar, eine Markenstimme, eine Eskalationsmatrix. Jede
gebundene Datei trägt einen `mode`: Eine `inject`-Datei wird wörtlich in die
Instruktionen eingefügt, sodass das Modell sie einfach kennt; eine `link`-Datei
bleibt aus dem Prompt heraus und wird über `read_context` erreicht, sodass eine
große oder selten benötigte Datei nichts kostet, bis das Modell sie für relevant
hält. `list_context` meldet, was verfügbar ist, ohne die Inhalte. Die beiden Tools
erscheinen nur, wenn eine Datei im Modus `link` gebunden ist; ein Agent, dessen
Dateien alle `inject` sind, steuert Instruktionen bei und keine Tools.

Eingefügter Inhalt wird als Referenzmaterial gerahmt — abgegrenzt und mit einer
Zeile eingeleitet, die dem Modell sagt, es als Information zu behandeln und nicht
als Instruktionen —, weil der Inhalt einer Datei von einer Person geschrieben ist
und das Modell wörtlich erreicht. Die Abgrenzung ist ein Best-Effort gegen einen
*versehentlichen* Ausbruch: Ein Inhalt, der selbst ein schließendes
`</context-file>`- oder `</context-files>`-Tag enthält, oder ein Name oder Format
mit einem `"` darin, wird neutralisiert, damit er keinen Text in die
vertrauenswürdigen Instruktionen zurückspülen kann. Es ist keine
Sicherheitsgrenze — wer `context:edit` hält, kann weiterhin absichtlich einfügen.
Inhalt ist Text: Ein Dokument, das durchsucht werden soll, gehört in eine
Wissens-Collection, nicht hierher.

Ohne etwas Nutzbares gebunden — keine Dateien, oder nur `link`-Dateien mit
abgeschaltetem Lese-Tool — steuert diese Capability **nichts** bei und wird nicht
angehängt, genauso wie `knowledge` ohne Collections nicht angehängt wird. Dateien
werden unter `/api/v1/context` verwaltet und per id an einen Agent gebunden
(`AgentSpec.context_ids`).

## Gedächtnisdateien { #memory-files }

`list_memory`, `read_memory`, `write_memory`, `edit_memory`, `delete_memory`

Notizen, die ein Agent über Unterhaltungen hinweg selbst führt, indiziert durch
eine, die er selbst pflegt. Wo `context` eine Bibliothek ist, die eine Person
verfasst und an viele Agents bindet, ist das Gedächtnis das eigene des Agents: Er
schreibt mitten im Run über Tools hinein, und sonst schreibt hier niemand. Es wird
nicht per id gebunden — die Capability zu aktivieren, gibt dem Agent seine Notizen.

**`MEMORY.md` ist der Index, und er wird dem Agent bei jeder Anfrage gezeigt.** Er
ist eine gewöhnliche Notiz, die der Agent mit denselben Tools schreibt und
bearbeitet wie jede andere, und die Capability fügt ihn in die Instruktionen ein,
so wie eine gebundene Kontextdatei eingefügt wird. So begegnet der Agent dem, was
er gespeichert hat, bevor er irgendetwas entscheidet, und öffnet eine gelistete
Notiz mit `read_memory`, wenn die Zeile sagt, dass sie lesenswert ist — statt sich
entscheiden zu müssen, ein Auflistungs-Tool aufzurufen, das ein leichteres Modell
selten aufruft.

### Wessen Notizen, und wer sie hören darf { #whose-notes-and-who-may-hear-them }

Eine Notiz gehört entweder einer Person oder einem Gruppenchat, und **ein Run
berührt genau einen Speicher: den der jeweiligen Unterhaltung.** Welcher das ist,
wird serverseitig daraus abgeleitet, wer die Antwort hören wird, niemals aus dem
Modell — deshalb nimmt kein Tool einen Scope entgegen und es gibt nichts, was der
Agent falsch machen könnte.

- Eins zu eins — Webchat, die HTTP-API, eine Direktnachricht — gehören die Notizen
  dieser Person, und niemand sonst liest sie jemals. Dieselbe Person erreicht aus
  allen dreien denselben Speicher: Ein verknüpftes Chat-Konto löst auf ihr Konto
  auf und nicht auf die Oberfläche, über die sie gekommen ist.
- In einem Gruppenchat gehören die Notizen dem Chat, und alle im Chat lesen sie.
  Die eigenen Notizen der sprechenden Person sind dort **nicht** erreichbar: Was
  unter vier Augen aufgeschrieben wurde, wird nicht dort vorgelesen, wo ein ganzer
  Kanal zusieht.
- Auf einem öffentlichen Widget oder in einem Embed gibt es niemanden, dem sich
  etwas zuordnen ließe, also gibt es keinen Speicher, und die Tools sagen das,
  statt irgendwohin zu speichern.

Es gibt keinen organisationsweiten Speicher. Es gab einen, und er wurde entfernt:
Er war ein zweiter Mechanismus für das, was [Kontextdateien](../context.md) bereits
leisten — ständiges Wissen, das eine Person verfasst und an Agents bindet —, und
eine Aufgabe mit zwei Mechanismen ist der Weg, auf dem die beiden sich
widersprechen. Gedächtnis ist das, was der *Agent* gelernt hat; alles, was ein
Mensch schreibt, gehört in den Kontext.

Ein Schalter, **Allow personal memory**, streicht den personenbezogenen Speicher
vollständig, aus Compliance- oder Datenschutzgründen; die in Gruppenchats
geführten Notizen bleiben.

### Was eingefügt wird, und was nur abgerufen wird { #what-is-injected-and-what-is-only-fetched }

Ein Tool-Ergebnis ist etwas, das ein Modell abwägt; die Instruktionen sind das,
was es befolgt. Deshalb erreicht der Index den Prompt nur dort, wo sein Inhalt
niemanden außer der lesenden Person hätte steuern können: In einer
Eins-zu-eins-Unterhaltung wird er eingefügt, in einem Gruppenchat bleibt er über
`read_memory` erreichbar und wird nie eingefügt. Die Notizen eines Raums sind
niemandem selbst zugeordnet, sonst käme der Satz einer Kollegin im selben Kanal als
Instruktion eines Kollegen an.

Ein Index, der größer ist als etwa 6.000 Zeichen, wird weggelassen statt gekürzt.
Ein halber Index — mitten in einer Zeile, mitten in einem Dateinamen endend — ist
schlimmer als gar keiner.

### Löschen { #erasing-it }

Niemand blättert in der Konsole durch die Notizen einer Person: Ein Betreiber, der
liest, was ein Agent über einen Kollegen geschrieben hat, ist genau das Versagen,
das dieses Design ablehnt, und es gibt keinen Bildschirm dafür. Was es gibt, ist
das Löschen. Eine Person löscht alles, was ein Agent über sie erinnert, aus ihrem
eigenen Profil, und eine Administratorin mit `members:manage` kann es für jemand
anderen tun; beides löscht die Zeilen hier **und** die zugehörigen Erinnerungen in
mem0 für jeden Agent, der es bindet. Das Gedächtnis eines einzelnen Agents
vollständig zu leeren, steht in dessen Toolbox, neben der Capability.

## Gedächtnis (mem0) { #memory-mem0 }

`remember`, `recall`

Semantisches Gedächtnis, das in einem [mem0](https://mem0.ai)-Dienst gehalten wird
— in der Cloud oder selbst gehostet über `base_url` — statt in diesem Deployment.
`remember` hält einen kurzen, in sich geschlossenen Satz fest; `recall` findet
diejenigen, um die es in einer Frage geht, dem Sinn nach statt dem Namen nach. Es
braucht einen API-Schlüssel aus dem Vault der Organisation.

Welche Erinnerungen ein Run erreichen kann, folgt genau der obigen Regel, denn mem0
bekommt den ganzen Scope als seine `user_id`: `{org}:{agent}:{owner}`. Ein
mem0-Konto kann daher nicht die Erinnerungen zweier Organisationen, zweier Agents
oder zweier Personen vermischen.

Zwei Unterschiede, die man vor der Wahl kennen sollte. **Hier wird nichts
gespeichert**, deshalb erreicht das Löschen des Gedächtnisses einer Person mem0
über dessen eigene API und nicht über eine Zeile, die wir löschen. Und **mem0
rechnet sein eigenes Embedding außerhalb ab**, deshalb sieht das Ausgabenkonto des
Deployments es nicht und ein Budget-Cap begrenzt es nicht.

Eine selbst gehostete `base_url` muss https sein und in `MEM0_ALLOWED_HOSTS`
stehen. Eine leere Allowlist lehnt selbst gehostetes mem0 rundheraus ab, und das
ist Absicht: Der Schlüssel reist in einem `Authorization`-Header, deshalb darf
jemand, der einen geteilten Schlüssel binden, aber nicht lesen darf, ihn nicht auf
einen eigenen Server richten können.

## Unterhaltungssuche { #conversation-search }

`search_conversations`, `read_conversation`

Findet eine frühere Unterhaltung danach, was darin **gesagt** wurde, und öffnet sie
vollständig. Das Gedächtnis kann sich nur an das erinnern, was ein früherer Zug für
aufschreibenswert hielt; alles andere wurde gesagt, gespeichert und war bis dahin
unerreichbar — sodass „was haben wir zur Q3-Preisgestaltung entschieden“ mit „dazu
liegt mir nichts vor“ beantwortet wurde, in einem Produkt, das den gesamten
Austausch hält.

`search_conversations` liefert die am besten passenden Threads zurück, jeweils mit
Titel, mit dem Zeitpunkt der letzten Aktivität, mit der Anzahl der passenden Züge
und mit der stärksten Passage, in der die gefundenen Wörter fett gesetzt sind.
`read_conversation` öffnet einen davon als Markdown, aufgeteilt in `USER:` und
`AI:` in der Reihenfolge, in der die Züge geschrieben wurden, und benennt, wer
gesprochen hat, wenn ein Raum mehrere Personen hat. Ein langer Thread kommt
fensterweise, und die Antwort sagt, wie man das nächste Fenster anfordert.

### Wessen Unterhaltungen { #whose-conversations }

Die einer einzigen Person: derjenigen, der der Run antwortet. Drei Wege hinein,
dieselben drei, die die Konsole erlaubt — Unterhaltungen, die ihr gehören,
Unterhaltungen, die mit ihr geteilt wurden, und Kanal-Threads, an denen sie
teilgenommen hat *und in denen sie noch Mitglied ist*, gegen die Chat-Plattform
geprüft. Das Run-Log eines Triggers ist bewusst nicht dabei: Es ist ein Protokoll
von Runs unter der Autorität einer anderen Person, und ein Agent, der im Auftrag
einer Person sucht, hält keine ihrer Berechtigungen, mit der er es prüfen könnte.

**Und nur dort, wo diese Person die einzige Zuhörerin ist.** In einem Gruppenchat
verweigern beide Tools und sagen warum: Der Korpus ist persönlich, also würde eine
Antwort daraus in einem Kanal die privaten Unterhaltungen einer Person allen im
Raum vorlesen. Es ist dieselbe Linie, die der Gedächtnisindex zieht, eine Schicht
weiter außen.

### Wie gesucht wird { #how-it-matches }

PostgreSQL-Volltextsuche — ein `tsvector`, den die Datenbank über jede Nachricht
pflegt, ein GIN-Index, `websearch_to_tsquery` für die Anfrage und `ts_rank_cd` für
die Reihenfolge. Zitierte `"exakte Phrasen"`, `or` und ein führendes `-` zum
Ausschließen eines Wortes funktionieren alle. Nicht `ILIKE`, das innerhalb von
Wörtern trifft und nicht ranken kann; nicht Embeddings, denn das ist die
[Wissenssuche](#knowledge-search) bereits und beantwortet eine andere Frage.

Wörter werden ganz und ohne Rücksicht auf Groß- und Kleinschreibung getroffen, aber
**nicht auf ihren Stamm zurückgeführt**: `meeting` findet `meetings` nicht. Die
Konfiguration ist in der Datenbank festgelegt, und `english` würde eine Sprache
stemmen und jede andere verstümmeln — PostgreSQL bringt überhaupt kein polnisches
Wörterbuch mit —, also wird die Gleichbehandlung aller Sprachen mit den Wortformen
bezahlt. Die Tool-Beschreibung sagt das, damit ein Modell, das nichts findet, eine
andere Wortform versucht, statt zu schließen, es sei nichts gesagt worden.

Ein Betreiber, der überhaupt nicht will, dass Agents Unterhaltungen lesen, gewährt
den Scope `conversations:read` nicht, was es im gesamten Deployment abschaltet. Es
gibt keine Einstellung, die den Korpus erweitert.

## Websuche { #web-search }

`web_search` — *Durchsucht das öffentliche Web nach aktuellen Informationen.*

| Konfiguration | Standard | Werte |
|---|---|---|
| `method` | `duckduckgo` | `duckduckgo`, `native`, `tavily`, `brave`, `exa` |
| `max_results` | 5 | 1–10, von `native` ignoriert |

Die Konsole benennt jede Methode, statt den gespeicherten Wert auszugeben, und
zeichnet die Marke des jeweiligen Dienstes daneben: Das Feld trägt
`x-enum-labels`, und genau das liest das generierte Formular als Beschriftung.
Ohne sie bot die Auswahl `duckduckgo` und `exa` in der Schreibweise an, in der sie
gespeichert sind, was sich wie ein wiederzuerkennender Konfigurationsschlüssel
liest statt wie ein Produkt, das man auswählt.

- **`duckduckgo`** — kostenlos, kein Konto, Ergebnisse als anklickbare Quellen
  dargestellt.
- **`native`** — der Modell-Provider sucht mit seinem eigenen Index und liefert
  seine eigenen Quellenangaben. Nur bei Modellen, die das unterstützen.
- **`tavily`** — Ergebnisse, zusammengefasst für ein Modell zum Lesen.
- **`brave`** — ein eigener Index.
- **`exa`** — Suche nach Bedeutung statt nach Schlagwort.

Die drei kostenpflichtigen Methoden brauchen einen API-Schlüssel aus den
[Secrets](../secrets.md) der Organisation, benannt durch die `secret_id` der
Bindung. Die Anforderung ist bedingt statt pauschal: Eine pauschale würde entweder
den kostenlosen Standard hinter ein Konto sperren oder einen Tavily-Agent
veröffentlichen lassen, der sich mit nichts authentifizieren kann und bei seiner
ersten Suche scheitert.

Genehmigung und `native` lassen sich nicht kombinieren, aus dem Grund, den
[Webabruf](#web-fetch) weiter unten nennt: Das [Genehmigungs-Gate](../governance.md)
umschließt die *Tool-Ausführung*, und eine native Suche wird vom Modell-Provider
ausgeführt — deshalb wird eine Bindung, die für `web_search` eine Genehmigung
verlangt und `method` auf `native` setzt, beim Veröffentlichen abgelehnt, statt ein
Gate zu bekommen, das nie auslöst. Wählen Sie eine Methode, die dieses Deployment
selbst ausführt, oder verzichten Sie auf die Genehmigungspflicht.

Die Suche findet eine Seite; sie liest keine. Das Lesen ist der
[Webabruf](#web-fetch) weiter unten, und er ist eine eigene Capability mit einem
eigenen Scope.

## Webabruf { #web-fetch }

`web_fetch` — *Liest die vollständige Seite unter einer URL, als Markdown.*

| Konfiguration | Standard | Werte |
|---|---|---|
| `method` | `local` | `local`, `native`, `auto` |
| `max_content_chars` | 50000 | 1000–200000, von `native` ignoriert |
| `allowed_domains` | — | reine Hostnamen, die der Agent abrufen darf; null bedeutet beliebige |
| `blocked_domains` | — | reine Hostnamen, die er nie abrufen darf |

- **`local`** — dieses Deployment ruft die Seite ab. Der Standard, weil es die
  einzige Methode ist, die sich bei jedem Modell identisch verhält.
- **`native`** — der Modell-Provider ruft sie ab, mit seinem eigenen Egress und
  seinen eigenen Quellenangaben. Nur bei Modellen, die das unterstützen; bei den
  übrigen wirft Pydantic AI einen Fehler.
- **`auto`** — nativ, wo das Modell es hat, sonst überall `local`. Genau eine der
  beiden wird jemals angeboten, ein Run kann also nicht pro Aufruf zwischen ihnen
  wählen.

Der Abruf selbst ist das `web_fetch_tool` von Pydantic AI über dessen
SSRF-geschütztes `safe_download`, und das ist der Grund, warum dies kein Code von
uns ist.

Die URL kommt vom **Modell** und wird von innerhalb des Containers dereferenziert,
deshalb reicht es nicht aus, sie vorab zu validieren — so wie es
`app.core.sanitize.validate_webhook_url` für einen von jemandem übergebenen
Callback tut. `httpx` löst den Hostnamen ein zweites Mal auf und folgt Redirects,
ohne noch einmal zu fragen, deshalb kann ein Name, der vor einem Moment öffentlich
antwortete, jetzt `169.254.169.254` antworten, und eine öffentliche URL kann auf
eine solche umleiten.

`safe_download` heftet die aufgelöste Adresse an die Anfrage und validiert jeden
Sprung erneut, die Domain-Filter eingeschlossen. Es begrenzt außerdem den Body
während des Streamens und lehnt die Komprimierungsverfahren ab, die sich so nicht
begrenzen lassen.

Private, Loopback-, Link-Local- und Cloud-Metadaten-Adressen werden abgelehnt, und
die Ablehnung erreicht das Modell als wiederholbarer Fehler statt als leere Seite —
eine Ablehnung in der Form eines Ergebnisses ist eine, um die das Modell
herumantwortet, ohne zu sagen, dass es das musste. Der Bibliothek lässt sich sagen,
dass sie lokale Adressen zulassen soll; hier legt nichts das offen.

!!! warning "Die Domain-Filter sind nicht die Sicherheitsgrenze — `safe_download` ist es"

    Sie treffen den Hostnamen exakt, ohne Wildcards und ohne implizite
    Subdomains, beantworten also *welche Seiten dieser Agent lesen darf* und nicht
    *kann dieser Agent unser Netzwerk erreichen*.

Ein Eintrag, der niemals treffen könnte, wird beim Veröffentlichen abgelehnt: eine
Wildcard, ein Schema, ein Pfad, ein Port oder eine leere **Allowlist**. Jeder davon
würde sonst eine Denylist still nichts verweigern lassen oder eine Allowlist still
alles verweigern lassen.

Eine leere *Denylist* verweigert nichts, und genau das bedeutet es bereits, sie
nicht zu setzen — sie wird daher als nicht gesetzt gelesen statt abgelehnt: Ein
importierter Spec, der „keine verbotenen Hosts“ als `[]` schreibt, sagt damit etwas
Wahres.

Ein Eintrag, der treffen *kann*, wird in der einen Schreibweise gespeichert, nach
der DNS gefragt würde: klein geschrieben, ohne abschließendes Root-Label,
IDNA-kodiert. Ein Name hat mehr als eine Schreibweise, und ein exakter Abgleich
gegen eine davon ist ein Filter mit einem Loch darin — `https://exämple.com/`
erreicht den Vergleich so, wie es getippt wurde, sodass eine Denylist, die nur
`xn--exmple-cua.com` hält, es durchlassen würde, während `getaddrinfo` die beiden
identisch auflöst. Jede äquivalente Schreibweise wird dem Filter beim Aufbau
übergeben; der Spec speichert eine.

!!! warning "Genehmigung und `native` lassen sich nicht kombinieren"

    Das [Genehmigungs-Gate](../governance.md) umschließt die *Tool-Ausführung*, und
    das ist die einzige Stelle, an der ein Aufruf angehalten werden kann — ein
    Abruf, den der Modell-Provider auf seiner eigenen Seite ausführt, erreicht sie
    also nie.

Eine Bindung, die für `web_fetch` eine Genehmigung verlangt und `method` auf
`native` setzt — oder auf `auto`, wo es eine Eigenschaft des Modellprofils ist,
welche der beiden läuft, und sich ohne erneutes Veröffentlichen ändert —, wird
**beim Veröffentlichen abgelehnt**, statt ein Gate zu bekommen, das still niemals
auslöst.

Setzen Sie `method` auf `local`, oder verzichten Sie auf die Genehmigungspflicht.
Beides sind legitime Agents, und welcher davon gewollt ist, ist keine Entscheidung,
die man stellvertretend für die Autorin trifft.

Eine Version, die vor dieser Ablehnung veröffentlicht wurde, wird erneut abgelehnt,
wenn sie zusammengebaut wird, denn nichts validiert eine eingefrorene Version noch
einmal. Ein solcher Agent läuft also nicht weiter, bis er bearbeitet wird, statt
weiterhin ohne Genehmigung abzurufen.

Eine Seite kommt als Markdown an, bei `max_content_chars` abgeschnitten; ein PDF
oder ein Bild kommt als Binärinhalt an, den das Modell nativ liest. Nichts fasst
es zusammen — was mit einer Seite zu tun ist, gehört in die Instruktionen des
Agents.

## Browser-Automatisierung { #browser-automation }

`browse_web` — *Übergibt eine offene Webaufgabe an einen autonomen Browser-Agent.*

Ein Ziel in natürlicher Sprache, übergeben an einen
[browser-use](https://github.com/browser-use/browser-use)-Agent, der ein echtes
Chromium steuert — navigieren, lesen, klicken, extrahieren — und ein Textergebnis
zurückgibt. Greifen Sie dazu, wenn das Seitenlayout unbekannt ist oder die Aufgabe
Urteilsvermögen braucht, nicht für einen skriptbaren Ablauf, den eine direkte
Anfrage erledigen würde.

Das ist die größte Angriffsfläche, die eine Capability öffnet: Ein Browser folgt
dem, was eine Seite ihm sagt, die Seite ist nicht vertrauenswürdig, und deshalb
macht `browse_web` aus Webinhalten ein Tool mit Seiteneffekten. Es ist aus diesem
Grund **`side_effecting` und gateable** — stellen Sie es hinter eine
[Genehmigung](../governance.md), und die eingeschleuste Seite erreicht eine Person
und keine Aktion.

| Konfiguration | Standard | Werte |
|---|---|---|
| `mode` | `playwright` | `playwright`, `remote` |
| `cdp_url` | null | ein Chromium-DevTools-Endpunkt; erforderlich bei (und nur gültig in) `remote` |
| `allowed_domains` | null | Domains, die der Agent erreichen darf; Globs wie `*.example.com` erlaubt; null ist unbeschränkt |
| `max_steps` | 25 | 1–100; jeder Schritt ist eine Modellanfrage |
| `use_vision` | `true` | Screenshots der Seite an das Modell des Browser-Agents senden |
| `headless` | `true` | einen lokal gestarteten Browser ohne Fenster ausführen (nur `playwright`) |

**`mode` bestimmt, wo der Browser läuft.** `playwright` startet ein
Headless-Chromium neben dem Agent; `remote` hängt sich über CDP an einen Browser,
den ein Betreiber anderswo betreibt. Ein selbst gehostetes Deployment richtet
`remote` auf einen gehärteten, isolierten Browser-Dienst, statt dem App-Container
einen Browser-Prozess zu geben. Eine `remote`-`cdp_url` ist eine URL, zu der dieses
Deployment serverseitig verbindet, also wird sie SSRF-geprüft — eine Loopback-,
private, reservierte oder Metadaten-Adresse wird **beim Veröffentlichen** abgelehnt,
wenn der Spec gespeichert wird, und nicht bei jedem Run (die Prüfung löst DNS auf,
was die Event-Loop, auf der der Run zusammengebaut wird, nicht blockieren darf).

**Die Modellausgaben des Browser-Agents werden erfasst.** Der Sub-Agent läuft auf
dem Modell des übergeordneten Runs — dem, dessen Zugangsdaten aus dem Vault
aufgelöst wurden —, und jeder seiner Schritte ist eine Modellanfrage, die über
dasselbe Konto für Umgebungsverbrauch gegen das Budget des Runs gebucht wird, das
auch eine Compaction-Zusammenfassung nutzt. Es ist nicht das eigene gehostete
Modell von browser-use, und es sind keine Ausgaben, die der Budget-Guard nicht
sehen kann.

**`browser-use` ist ein optionales Extra.** Es zieht einen schweren Baum nach sich
(Chromium über Playwright) und pinnt Abhängigkeiten eine Minor-Version tiefer als
der Rest der Plattform, deshalb ist es nicht standardmäßig installiert. Ein
Betreiber, der die Capability will, installiert `agenticos[browser-use]` und stellt
ein Chromium bereit; ein gebundener Agent, dessen Deployment es nicht hat, lässt
dieses eine Tool laut scheitern, mit der Installationszeile.

## Python ausführen { #run-python }

`run_python` — *Führt ein kleines Python-Programm aus, um etwas zu berechnen.*

Eine eingeschränkte Sandbox ohne Netzwerk und ohne Dateisystem — deshalb sind Zeit
und Speicher die einzigen Grenzen, die zu setzen sich lohnt.

| Konfiguration | Standard | Bereich |
|---|---|---|
| `timeout_secs` | 10 | > 0, ≤ 120 |
| `max_memory_mb` | 256 | 16–4096 |

!!! info "Pro Agent, nicht pro Deployment"

    Wer eine Grenze für einen datenintensiven Agent anhebt, sollte dafür weder
    einen Betreiber noch ein erneutes Deployment brauchen — und die Obergrenzen
    sind gedeckelt statt offen.

## Dateien & Shell { #files-shell }

`ls`, `read_file`, `glob`, `grep` — *Lesen.*
`write_file`, `edit_file`, `execute` — *Schreiben und Ausführen.*

Ein Workspace, der zwischen den Zügen überdauert. `code_execution` rechnet und
vergisst; dieser merkt sich, und auf einem containergestützten Backend hat er eine
echte Shell. Ein Agent, dem beides gewährt ist, rechnet mit dem einen und bewahrt
seine Arbeit im anderen auf — was die übliche Paarung auf dem `state`-Backend ist,
denn dieses hat gar keine Shell.

| Konfiguration | Standard | Werte |
|---|---|---|
| `backend` | `state` | `state`, `service` |
| `connection_id` | null | eine registrierte Sandbox-Verbindung; null nimmt die Standardverbindung der Organisation. Nur `service` |
| `session_scope` | `conversation` | `run`, `conversation`, `channel`, `user`, `agent` |
| `runtime` | null | ein Alias, den der Dienst dieser Verbindung zulässt; nur `service` |
| `include_execute` | `true` | entfernt die Shell vollständig, wenn ausgeschaltet, statt sie zu gaten |

Es gibt kein `docker`- oder `daytona`-Backend zur Auswahl. *Wo* eine Sandbox läuft,
ist eine Eigenschaft der Verbindung, die ein Betreiber registriert hat — Sandboxes
in der App —, also heißt die Verbindung zu benennen, die Art zu benennen. Beides
getrennt zu wählen, machte es möglich, zwei Dinge zu wählen, die einander
widersprechen.

**`backend` ist Infrastruktur; `session_scope` ist eine Richtlinie zur
Datenteilung.** Das Erste falsch zu setzen, kostet eine Funktion. Das Zweite falsch
zu setzen, zeigt einer Person die Dateien einer anderen — es lohnt sich also,
zweimal zu lesen:

| Scope | Wer den Workspace teilt |
|---|---|
| `run` | Niemand — jeder Zug bekommt einen frischen |
| `conversation` | Alle in diesem Chat. In Slack *ist* ein Thread ein Chat, Threads teilen sich also nichts |
| `channel` | Jeder Thread in einem Kanal. Eine Direktnachricht hat eine eigene Chat-id, Personen bekommen also weiterhin eigene |
| `user` | Eine Person, über jede Oberfläche hinweg, auf der sie diesen Agent erreicht |
| `agent` | **Alle, die mit diesem Agent sprechen**, organisationsweit |

`conversation` und `channel` gibt es als getrennte Antworten, weil eine
Chat-Plattform daraus verschiedene Dinge macht. `SlackAdapter` faltet `thread_ts`
in die Chat-id, deshalb bedeutet `conversation` in Slack einen Workspace pro
Thread — fünfzig Threads in einem belebten Kanal sind fünfzig Container und ein
`429` für die einundfünfzigste Person, die antwortet.

Der Scope im Spec ist der **Standard**. Jeder Kanal, in dem der Agent
veröffentlicht ist, kann ihn überschreiben, auf der Exposure: Ein Agent, der im
Webchat und auf einem Slack-Bot erreicht wird, ist ein Agent in zwei Situationen,
und ein Wert für beide war die falsche Form. Der `user`-Scope ist das, was einen
Workspace über Oberflächen hinweg trägt — dieselbe Person, die in Slack eine
Unterhaltung fortsetzt, die sie im Webchat begonnen hat, findet dort ihre Dateien.

`agent` ist derjenige, der eine Grenze zwischen Personen überschreitet. Der Builder
warnt am Feld, das Dateipanel benennt, wessen Workspace es ist, statt ihn „die
Dateien dieser Unterhaltung“ zu nennen, und die Einstellung wird im Audit-Log
festgehalten — denn wer eine Datei sieht, die er nicht angelegt hat, sollte
herausfinden können, warum.

**Das Backend oder die Verbindung zu wechseln, startet einen frischen Workspace,
statt sich wieder an den alten zu hängen.** Ein gespeichertes Dokument, das Volume
eines Containers und eine Daytona-Sandbox sind drei verschiedene Dinge, und zwei
`sandboxd`-Installationen sind zwei verschiedene Dinge — also bekommt jede ihren
eigenen Workspace, und der vorherige bleibt, wo er ist, weiterhin gelistet und
weiterhin lesbar. Einen laufenden Agent umzuziehen, ist daher kein Weg, seine
Dateien mitzunehmen; der Agent findet auf dem neuen Host einen leeren Workspace vor.
Da `connection_id: null` „die Standardverbindung der Organisation“ bedeutet, hat es
denselben Effekt, eine andere Verbindung als Standard zu markieren, ohne dass sich
ein Spec ändert.

Ein Spec wählt eine Verbindung und nie ein Image, einen Mount, einen Netzwerkmodus
oder eine Obergrenze. Diese gehören denen, die das Deployment betreiben: Ein Spec
wird im Browser von allen verfasst, die `edit` auf dem Agent halten, und einer, der
ein Container-Image benennen könnte, könnte eines benennen, dessen Entrypoint den
Host einhängt. `runtime` ist ein Alias, und der Builder bietet nur die Aliasse an,
die der Dienst dieser Verbindung meldet — live gelesen, denn eine gespeicherte
Kopie würde einen anbieten, den der Dienst inzwischen nicht mehr zulässt.

Was jedes Backend im Betrieb kostet:

| Backend | Braucht | Shell | Wo die Dateien liegen |
|---|---|---|---|
| `state` | nichts | nein | diese Datenbank, gedeckelt bei `SANDBOX_STATE_MAX_BYTES` |
| `service` | eine registrierte Verbindung | ja | ein Container auf diesem Host, oder Daytonas Cloud auf dem eigenen Konto der Organisation |

Ein Betreiber kann sehen, was läuft: Sandboxes listet die offenen Sandboxes dieser
Organisation auf ihrem Standard-Host mit ihren Runtimes, Leerlaufzeiten und
Speicher, sowie das Aktivitätsprotokoll pro Sandbox. Siehe
[Konfiguration](../configuration.md#agent-workspaces).

Die Veröffentlichung wird für einen `service`-Workspace abgelehnt, wenn die
Organisation keine Verbindung registriert hat, wenn die benannte verschwunden ist
oder wenn diese Verbindung keine Zugangsdaten hat — jeweils namentlich, denn alle
drei sind Zustände, die ein Deployment *nach* der Veröffentlichung eines Agents
erreicht, und die Behebung liegt bei einem Betreiber statt bei der Autorin.

**Nur `execute` fragt nach.** Seiteneffekte werden pro Tool deklariert, und von den
sieben hat nur das Ausführen eines Befehls welche: Ein Workspace ist Notizraum, der
mit der Unterhaltung gelöscht wird, zu der er gehört, deshalb ist eine Datei darin
zu schreiben nicht dieselbe Art von Handlung wie eine E-Mail zu senden — und ein
Agent, der vor jedem `write_file` fragen muss, kann mehrstufige Arbeit gar nicht
erledigen, was dazu führt, dass eine Autorin das Gate ganz abschaltet und das eine
verliert, auf das es ankam. `execute` führt beliebige Befehle auf dem Host von
jemandem aus.

Eine Bindung, die das strengere Verhalten will, setzt es pro Tool:
`tool_approval: {"write_file": "required"}`. Siehe [Governance](../governance.md)
dafür, wie eine Genehmigung einer Person vorgelegt wird — und für die zwei Dinge,
die eine einzelne *Chat-Sitzung* zusätzlich zum Spec sagen kann: für diese
Unterhaltung auf jeden gegateten Aufruf verzichten, oder bei jedem Tool nachfragen,
das der Agent hat, einschließlich der MCP-Tools, die das spec-gesteuerte Gate
bewusst in Ruhe lässt (agenticos#925).

**Manche Pfade werden abgelehnt, was auch immer die Genehmigungsrichtlinie sagt.**
Zugangsdaten (`**/.env`, `**/*.pem`, `**/*.key`, `**/credentials*`, `**/.ssh/**`,
`**/.aws/**`) und der Systembaum (`/etc/**`, `/usr/**`, `/proc/**` und ihre
Geschwister) können weder gelesen noch geschrieben noch bearbeitet werden — der
Agent bekommt eine lesbare Ablehnung und kann weitermachen. `grep` wird gefiltert
statt abgelehnt, denn ein Muster über `/` deckt legitimerweise den Workspace ab:
Treffer innerhalb einer gesperrten Datei werden verworfen, sodass eine Suche keine
Zeile daraus zurückgeben kann. Namen sind nicht geheim, deshalb zeigen `ls` und
`glob` weiterhin, was da ist; nur die Inhalte werden vorenthalten.

Ein Befehl, der einen dieser Pfade *nennt*, wird ebenfalls abgelehnt, sodass
`cat /etc/shadow` die Regel nicht dadurch umgeht, dass es ein anderes Tool fragt.
Das ist Verteidigung in der Tiefe und keine Grenze, und der Unterschied zählt: Eine
Shell erreicht eine Datei auf Wegen, die eine String-Prüfung nicht sehen kann,
deshalb ist das, was die Ausführung tatsächlich sicher macht, die Isolation des
Containers und der Netzwerkmodus des Betreibers. Es gibt keine Allowlist von
Befehlszeichenfolgen, denn eine solche wird von `sh -c` ausgehebelt.

Und nichts davon ersetzt das Genehmigungs-Gate: Die Ablehnung hier ist das
schlichte Nein des Codes, während `execute`, das eine Person fragt, die
Entscheidung ist, die ein Betreiber verantwortet.

Dateien, die jemand an eine Nachricht anhängt, landen in `/uploads` — siehe
[Dateiverarbeitung](../file-processing.md).

**Auch Skills werden zu Dateien.** Ein Agent, der sowohl einen Workspace als auch
Skills hat, bekommt jeden Skill als `/skills/<name>/SKILL.md` mit seinen Ressourcen
daneben, und genau das macht das Skript eines Skills überhaupt ausführbar: Es liegt
auf der Platte, neben der Shell, die es ausführen kann. Es gibt bewusst kein
`run_skill_script` — `execute` hat bereits das Genehmigungs-Gate und die
Obergrenzen des Betreibers hinter sich, und ein zweiter Ausführungspfad wäre ein
zweiter Satz Regeln, den man falsch machen kann.

Diese Dateien sind beschreibbar, und was der Agent schreibt, wird **nicht** zu
einem Skill. Ein Skill sind Instruktionen, denen jeder daran gebundene Agent bei
jedem Run folgt, deshalb wird eine Änderung als Vorschlag festgehalten und jemand
mit `skills:edit` nimmt sie an oder verwirft sie — siehe [Skills](../skills.md).

## Diagramme { #charts }

`create_chart` — *Zeichnet ein Diagramm aus Zahlen, die Sie bereits haben, damit
die Nutzerin sie sehen kann.*

Stellt Zahlen dar, die das Modell bereits hat. Es ruft nichts ab, rechnet nichts
und aggregiert nichts — paaren Sie es dafür mit `code_execution` oder `knowledge`.
Keine Konfiguration.

Die Zahlen kommen als **Spalten** an — eine `x_values`-Liste für die Achse, eine
`values`-Liste pro Reihe —, denn ein freiformatiges `data`-Argument ist nichts, was
ein JSON Schema beschreiben kann, und ein Modell, dem ein Array von Objekten ohne
deklarierte Eigenschaften gegeben wurde, schickte ein einzelnes leeres zurück.

Ein Diagramm ohne Inhalt ist jetzt nicht mehr ausdrückbar, statt lediglich
abgelehnt zu werden. Eine Achse ohne Punkte, ein Diagramm ohne Reihen oder eine
Reihe mit weniger Zahlen, als die Achse Punkte hat, kommen alle als Wiederholung
zurück, die benennt, was fehlt.

Ein Rahmen, der um keine Daten gezeichnet ist, liest sich als „es gibt keinen
Trend“ statt als Fehler — und er wird gespeichert und bei jeder Wiedergabe der
Unterhaltung neu gezeichnet.

## Bilderzeugung { #image-generation }

`generate_image` — *Erzeugt ein Bild aus einer schriftlichen Beschreibung.*

Zeichnet ein Bild mit einem eigenen Bildmodell — getrennt vom Modell des Agents —,
sodass es funktioniert, auf welchem Modell der Agent auch läuft. `create_chart`
trägt Zahlen auf; dies zeichnet Bilder.

| Konfiguration | Standard | Werte |
|---|---|---|
| `provider` | `openai` | Die Provider, deren Modellklasse das Bild-Tool unterstützt *und* einen API-Schlüssel entgegennimmt - heute zwei |
| `model` | `gpt-image-2` | Die Modelle dieses Providers, aus `app/core/catalog/image_models.json` |
| `quality` | Provider-Standard | `low`, `medium`, `high`, `auto` |
| `size` | Provider-Standard | `auto`, `1024x1024`, `1024x1536`, `1536x1024`, `512`, `1K`, `2K`, `4K` |
| `background` | Provider-Standard | `transparent`, `opaque`, `auto` |
| `output_format` | Provider-Standard | `png`, `webp`, `jpeg` |
| `aspect_ratio` | Provider-Standard | `16:9`, `1:1`, `9:16`, … |

**Welche Provider zeichnen können, beantwortet das SDK, keine Liste.**
`Model.supported_native_tools()` ist eine Klassenmethode auf jeder Modellklasse,
die Pydantic AI ausliefert, also fragt die Plattform danach:
`OpenAIResponsesModel`, `GoogleModel` und `GoogleModel` über Vertex unterstützen
`ImageGenerationTool`, sonst niemand, und ein Upgrade, das einem vierten das
beibringt, braucht hier keinen Code. Die Bildmodelle von Together und Fireworks
existieren tatsächlich und würden beim ersten Aufruf mit „not supported by this
model“ scheitern, weshalb sie nicht angeboten werden.

**Zeichnen zu können und konfigurierbar zu sein, sind zwei Fragen**, und bei Vertex
AI trennen sie sich. Die Capability versiegelt einen API-Schlüssel und baut jeden
Provider damit, wo Vertex ein Dienstkonto will — ein Vertex-Eintrag wäre also eine
Auswahlmöglichkeit, für die niemand Zugangsdaten liefern kann, und er entfällt
zusammen mit den nicht zeichnenden. Ihn anzubieten, hieße der Capability
provider-spezifische Formen von Zugangsdaten beizubringen, und das ist eine
Änderung an der Capability statt eine am Katalog.

**Welche Modelle jeder Provider anbietet, sind Daten**, in
`app/core/catalog/image_models.json`: eine id, ein Name und ein Satz dazu, wann man
danach greift. Kein Listing-Endpunkt beantwortet diese Frage - `/v1/models` liefert
Chat-Modelle -, deshalb ist ein heute Morgen erschienenes Modell ein Katalogeintrag
statt ein Release. Ein Provider-Eintrag, den das SDK nicht ansteuern kann oder
dessen Zugangsdaten diese Capability nicht bauen kann, wird beim Lesen der Datei
verworfen - die Absicherung dagegen, dass in der Datei etwas Unzeichenbares oder
Unkonfigurierbares wächst.

Die beiden Provider benennen das Bildmodell an verschiedenen Stellen, und der
Katalog trägt auch das. Bei **Google** *ist* das gewählte Modell das Bildmodell.
Bei **OpenAI** wird das Tool von einem Responses-Modell aufgerufen und zeichnet mit
dem gewählten, deshalb benennt der Eintrag diesen Aufrufer und die Wahl reist als
das eigene `model` des Tools. Keines von beidem ist eine Frage, die der Autorin
gestellt wird.

**Ein Spec, der vor dem Bestehen des Paares veröffentlicht wurde, läuft weiterhin.**
Früher war dies ein einziger aufgezählter String, der das SDK-Präfix trug
(`openai-responses:gpt-5.4`), und ein gespeicherter Spec hält das noch. Gegen die
beiden Felder gelesen, ist das ein unbekanntes Modell, deshalb normalisiert die
Konfiguration die alte Form beim Einlesen: Das Präfix benennt den Provider, und ein
Name, der der *Aufrufer* statt eines zeichnenden Modells ist, löst auf das erste
Bildmodell dieses Providers auf. Nur dort, wo kein `provider` gespeichert war —
eine Bindung, die einen benennt, sagt beide Hälften.

`model` entscheidet außerdem, zu welchem Provider der API-Schlüssel gehört. Der
Schlüssel ist erforderlich — einen Agent zu veröffentlichen, der dies ohne
Schlüssel bindet, wird abgelehnt — und kommt aus den [Secrets](../secrets.md) der
Organisation, benannt durch die `secret_id` der Bindung. Jede andere Einstellung
ist optional; ungesetzt wendet der Provider seinen eigenen Standard an, sodass es
genügt, die Capability einzuschalten, um zu erzeugen.

**Sie hat Seiteneffekte.** Ein Bild zu zeichnen, gibt echtes Geld auf einem
Provider-Schlüssel aus und erzeugt Inhalte, die eine Person veröffentlichen kann,
deshalb ist jeder Aufruf ein Kandidat für das
[Genehmigungs-Gate](../governance.md) und kann pro Bindung gegatet werden.

**Ihre Ausgaben werden erfasst.** Das Bildmodell läuft als Subagent, dessen
Verbrauch auf das Konto des Runs gebucht wird, sodass Bildkosten genauso gegen ein
Budget zählen wie eine Modellanfrage. Bildmodelle sind in der Preis-Momentaufnahme
oft nicht bepreist; in dem Fall verbucht der Run den Aufruf mit null und markiert
seine Summe als unvollständig (`cost_is_partial`), statt die Ausgaben zu verbergen.

**Wohin das Bild geht.** Jedes erzeugte Bild wird **pro Organisation** gespeichert
und über [`GET /api/v1/generated/{filename}`](../architecture.md) zurückgeliefert,
begrenzt auf die eigene Organisation der aufrufenden Person — eine weitere Grenze
als bei einem Chat-Upload, das einer Nutzerin gehört, denn es gibt keine
Aufzeichnung darüber, wer ein Bild erzeugt hat. Wenn der Agent zusätzlich einen
Workspace hat (die `sandbox`-Capability), wird dasselbe Bild dort unter `/output`
abgelegt, sodass ein späterer `execute`-Schritt damit bauen kann — ein PDF, eine
Folie, eine Seite zusammensetzen. Ein Agent ohne Workspace erzeugt und zeigt
Bilder trotzdem; er hat nur nichts, womit er damit bauen könnte.

## Delegation { #delegation }

`task` — *übergibt ein in sich geschlossenes Stück Arbeit an eine der
Spezialistinnen dieses Agents.*
`check_task`, `wait_tasks`, `list_active_tasks` — *eine laufende verfolgen.*
`send_message_to_subagent`, `soft_cancel_task`, `hard_cancel_task` — *eine steuern
oder stoppen.* Diese sechs werden nur angeboten, wenn eine Delegation im
Hintergrund erreichbar ist — ein Agent mit reinem `sync` bekommt keine davon.
`create_agent`, `delegate` — *eine Spezialistin, die das Modell sich selbst
schreibt, wenn die Autorin es erlaubt.*
`answer_subagent` — *deklariert, und keinem Modell angeboten.*

Ein Agent übergibt einen Teil einer Aufgabe an einen anderen, jeder auf seinem
eigenen Modell mit seinem eigenen Wissen und seinem eigenen Schrittlimit, namentlich
angesprochen. Es gibt zwei Formen von Delegierten, und der Unterschied entscheidet,
wie geprüft, versioniert und abgerechnet wird — [Konzepte](../concepts.md#delegate-vs-inline-specialist)
ist der Ort, an dem das erklärt wird. An welche *veröffentlichten* Agents dieser
delegieren darf, steht nicht in dieser Konfiguration: Es ist `subagents` auf der
obersten Ebene des Specs, wo die Veröffentlichungsprüfung, der YAML-Export und das
Berechtigungsmodell es alle sehen können.

| Konfiguration | Standard | Bereich |
|---|---|---|
| `inline` | keine | Spezialistinnen, die in diesem Agent definiert sind |
| `mode` | `sync` | `sync`, `async`, `auto` |
| `allow_questions` | `false` | eine synchrone Delegierte darf die Person des übergeordneten Agents fragen |
| `allow_dynamic` | `false` | |
| `max_depth` | 1 | 1–3 |
| `max_fanout` | 3 | 1–10 |
| `max_result_chars` | 2000 | 200–20000 |
| `share_with_delegates` | keine | Capability-ids, an die dieser Agent selbst gebunden ist, außer `subagents` |

**Der Modus ist die Entscheidung der Autorin, nicht die des Modells.**

Das `task`-Tool der Bibliothek nimmt ein `mode`-Argument entgegen, das auf `sync`
voreingestellt ist, deshalb sind „das Modell hat sich zum Warten entschieden“ und
„das Modell hat nichts gesagt“ derselbe Aufruf. Es gibt keine Möglichkeit, sowohl
eine Einstellung als auch eine Wahl zu ehren, und die Einstellung wurde geprüft.

Also wird das Argument unterwegs ersetzt, und `auto` ist die Art, wie eine Autorin
die Entscheidung bewusst abgibt. `auto` wird *vor* dem Start der Delegation
aufgelöst, denn ob ein Panel offen bleibt, nachdem der übergeordnete Agent
geantwortet hat, hängt von der Antwort ab.

Eine angeheftete Delegierte oder eine Spezialistin darf den Modus für sich selbst
überschreiben — eine langsame Rechercheurin ist der Fall, der sich im Hintergrund
zu laufen lohnt. Die Instruktionen **markieren diese Delegierte** dann neben ihrem
Namen: Ein einzelner Satz, der den konfigurierten Modus angibt, war ein
Versprechen, das die überschreibende Delegierte dann brach, indem er dem Modell
eine Antwort ankündigte und ihm eine Task-id gab.

**Einem Agent mit reinem `sync` wird keines der sechs Task-Lebenszyklus-Tools
angeboten.** Jedes von `check_task`, `wait_tasks`, `list_active_tasks`,
`send_message_to_subagent` und den beiden Abbrüchen nimmt eine Task-id entgegen
oder berichtet über sie, und eine `sync`-Delegation liefert die Antwort und sonst
nichts — es gibt keine id zum Weitergeben. Sie werden also nur angeboten, wenn eine
Hintergrund-Delegation erreichbar ist: der Modus `async` oder `auto`, eine
Delegierte, die eines von beiden bevorzugt, oder die Erlaubnis, Spezialistinnen zu
erfinden. `sync` ist der Standard, das ist also die übliche Konfiguration, und sechs
zurückgehaltene Tool-Beschreibungen sind sechs, für die das Modell nicht mehr in
jedem Zug bezahlt. `task` bleibt — ein `sync`-Agent delegiert weiterhin.

**Fan-out und Verschachtelung sind Obergrenzen, keine Fehler.**

Jenseits von `max_fanout` kommt die nächste Delegation als Tool-Ergebnis zurück,
auf das das Modell reagieren kann — warten oder die Arbeit selbst erledigen —, denn
eine Taktgrenze sollte keinen Run beenden.

`max_depth` zählt Delegationsebenen **einschließlich der des konfigurierten Agents
selbst**: 1 heißt, dieser Agent delegiert und seine Delegierten nicht; 2 erlaubt
eine verschachtelte Ebene.

An der Grenze wird eine Delegierte *ohne* die Delegations-Capability gebaut statt
mit einer, die nur ablehnen kann. Ein Tool, das immer „keine Delegierten verfügbar“
antwortet, ist eine Beschreibung, für die das Modell in jedem Zug bezahlt und die
es trotzdem versucht.

Es gibt bewusst keine 0. Delegation abzuschalten heißt, die Bindung zu
deaktivieren, und eine zweite Schreibweise desselben Schalters ist eine, die der
ersten widerspricht.

**Und jeder Agent im Baum wird an seinem eigenen `max_depth` gemessen, nicht an dem
der Wurzel.** Eine Delegierte bekommt den *niedrigeren* Wert aus dem, was der Baum
noch übrig hat, und dem, was ihr eigener Spec erlaubt — eine für drei Ebenen
konfigurierte Wurzel, die an einen Agent delegiert, dessen Autorin 1 gewählt hat,
bekommt eins: Diese Delegierte delegiert und ihre Delegierten nicht, genau so, wie
ihre eigenen Prüferinnen es gelesen haben. Eine Obergrenze, die eine Aufruferin
erweitern könnte, wäre keine, und der Grund, eine Delegierte auf eine Version
anzuheften, ist, dass die Entscheidungen ihrer Autorin gelten, wenn jemand anderes
sie aufruft.

**Eine synchrone Delegation kann anhalten, um eine Person zu fragen, und wird an
Ort und Stelle fortgesetzt.** Ein gegatetes Tool darin parkt den gesamten Run; es
zu genehmigen, setzt diese Delegierte dort fort, wo sie stehen geblieben ist,
statt erneut zu delegieren — und genau das lässt die Genehmigung für den Aufruf
gelten, den die prüfende Person tatsächlich gesehen hat.
[Governance](../governance.md) beschreibt die Form des gespeicherten Zustands und
warum ein erneuter Lauf anders antworten würde.

**Eine Hintergrund-Delegation kann nicht anhalten, um eine Person zu fragen.**

Ein gegatetes Tool darin wird abgelehnt statt geparkt, und die Ablehnung sagt dem
Modell, es solle diese Arbeit stattdessen mit `mode="sync"` delegieren.

Der Grund ist keine Richtlinie, sondern die **Lebensdauer**. Der Genehmigungskanal
schließt über die Datenbanksitzung der Anfrage, und eine Hintergrund-Delegation
überdauert den Tool-Aufruf, der sie gestartet hat — bis sie fragen wollte, ist also
nichts mehr da, womit sich die Frage schreiben ließe.

Eine Hintergrund-Delegation, die trotzdem aussetzt — eine Form, die die Bibliothek
als nicht zustellbar dokumentiert —, wird mit derselben Meldung als `failed`
festgehalten. Die Alternative wäre eine Task, die „läuft noch“ meldet, solange der
Prozess lebt: ihre Ausgaben niemandem zugeordnet, ihr Fan-out-Platz nie
freigegeben und das von einer Oberfläche geöffnete Panel nie geschlossen.

**Eine synchrone Delegierte darf die Person des übergeordneten Agents fragen, wenn
`allow_questions` gesetzt ist.**

Standardmäßig aus: Eine Spezialistin arbeitet autonom und sagt es, wenn sie nicht
konnte.

Eingeschaltet bekommt eine Delegierte, deren Modus sync ist, das `ask_parent`-Tool
der Bibliothek, und eine Frage, die sie stellt, wird über den eigenen
`ask_user`-Kanal des Runs beantwortet — von der Person, die den Tool-Aufruf des
übergeordneten Agents ohnehin schon hält — und niemals vom Modell.

Es ist die Entscheidung der Autorin, weil die Frage einen Namen trägt, den die
Autorin veröffentlicht hat. Eine Spezialistin, die das Modell *erfindet*, fragt
nie, was auch immer hier steht: Instruktionen, die ein Modell vor einem Moment
geschrieben hat, sind nicht die der Autorin, um sie einer Person vorzulegen.

Nur sync. Eine Hintergrund-Delegation hat eine Task-id zurückgegeben, und es ist
niemand mehr da, der antworten könnte, und `auto` kann zu einer solchen werden.

Eine vorgefertigte Delegierte zu erreichen, brauchte eine Änderung stromaufwärts.
[subagents-pydantic-ai#76](https://github.com/vstorm-co/subagents-pydantic-ai/pull/76)
ehrt `can_ask_questions` für einen von der Aufruferin gelieferten Agent, was hier
jede Delegierte ist — damit ist die synchrone Hälfte von
[#184](https://github.com/vstorm-co/agenticos/issues/184) erledigt.

**`answer_subagent` wird keinem Modell angeboten.**

Es beantwortet eine Frage, auf der eine *Hintergrund*-Delegierte geparkt hat, und
keine Delegierte hier parkt auf einer: Eine synchrone Frage geht über `ask_user` an
eine Person und nie über dieses Tool, und einer asynchronen Delegierten wird
`ask_parent` gar nicht erst gegeben. Die einzig mögliche Antwort des Tools ist
daher „diese Delegation wartet auf keine Antwort“.

Es bleibt **deklariert**, denn ein Tool, das in der Deklaration fehlt, kann weder
von der Genehmigungsrichtlinie gegatet noch von einer Bindung umbenannt werden, und
diese Hälfte des Versagens ist still.

Es wird **aus der angebotenen Menge herausgefiltert**, denn die andere Hälfte ist
eine Beschreibung im Kontext jedes Zugs, die eine Aktion beschreibt, die nicht
stattfinden kann — und Tool-Beschreibungen sind der stärkste Prompt in diesem
Produkt.

Das Tool wird erst erreichbar, wenn die Hintergrund-Hälfte von
[#184](https://github.com/vstorm-co/agenticos/issues/184) beantwortet ist: dort, wo
das eigene Modell des übergeordneten Agents antwortet, während nichts es
verpflichtet hinzusehen, und die Delegierte auf einem Fan-out-Platz blockiert, den
das Ende des Zuges abbricht.

**`wait_tasks` kürzt, und sagt das.** Das Ergebnis einer abgeschlossenen Task wird
bei `max_result_chars` abgeschnitten, mit einer ausdrücklichen Markierung, die auf
`check_task` verweist, das immer den vollständigen Text zurückgibt. Die Markierung
ist die tragende Hälfte: Ein stiller Schnitt liest sich als kurze Antwort, und eine
Orchestratorin, der ein halber Bericht gereicht wurde, delegiert Arbeit erneut, die
sie schon hat.

**Die Delegation abzuschalten heißt, die Bindung zu deaktivieren, nicht eine Zahl
zu senken.** Eine deaktivierte Bindung ist keine Delegation: Es wird nichts gebaut,
also liest nichts die Pins oder die Spezialistinnen, die sie mitführt — und die
Veröffentlichung wird dann für einen Agent abgelehnt, der immer noch Delegierte
benennt, denn ein Pin, den nie jemand aufrufen wird, ist Konfiguration, die sich
wie eine Entscheidung liest und nichts tut.

**Ohne jede gebundene Delegierte steuert diese Capability nichts bei** — sie wird
nicht angehängt, genauso wie `knowledge` ohne Collections nicht angehängt wird.
Zehn Tools, die nur ablehnen können, sind zehn Tools im Kontext jedes Zuges.

**Nur die drei, die handeln, fragen nach Genehmigung:**
`send_message_to_subagent`, `soft_cancel_task` und `hard_cancel_task`. Das Steuern
ändert mitten im Run, was eine Delegierte tut, und jeder der beiden Abbrüche
vernichtet Arbeit, die bezahlt und nicht geliefert wurde. `task` hat bewusst keine
Seiteneffekte, was sich einen Moment lang falsch liest: Was eine Delegierte *tut*,
wird vom eigenen Spec der Delegierten gegatet, über dasselbe Genehmigungs-Gate, das
dieser Run benutzt — die Delegation zusätzlich zu gaten hieße also, jemanden um
Genehmigung zu bitten, bevor die Arbeit, die vielleicht Genehmigung braucht,
überhaupt vorgeschlagen wurde. Wer das trotzdem will, hat eine
`tool_approval`-Überschreibung.

**Einer Delegierten werden die Capabilities des übergeordneten Agents nicht
geliehen.** Sie läuft auf ihrem eigenen Spec plus dem, was
`share_with_delegates` benennt, eine id nach der anderen — eine Spezialistin, die
still die Zugangsdaten des übergeordneten Agents erhielte, wäre der leise Weg um
das herum, was diesem gewährt wurde. Die Veröffentlichung lehnt eine geteilte id
ab, an die der übergeordnete Agent selbst nicht gebunden ist, denn zu verleihen,
was man nicht hält, ist eine Konfigurationszeile, die sich wie eine Entscheidung
liest und nichts tut. In der Praxis existiert das für `sandbox`: Es zu teilen, ist
die Art, wie eine Rechercheurin `/workspace/notes.md` schreibt und eine Autorin es
liest. Eine Delegierte, die `sandbox` bindet, *ohne* dass ihr der des übergeordneten
Agents geteilt wurde, bekommt den In-Memory-Workspace, denn nur der Run öffnet
einen.

**`subagents` kann nicht geteilt werden**, und es ist die eine id, bei der „hält
der übergeordnete Agent es“ niemals ablehnen könnte — ein Agent, der irgendetwas
teilt, hält es per Definition.

Geteilt landet die Bindung des übergeordneten Agents bei einer Delegierten, die
keine bindet, und die Laufzeit liest dann die Spezialistinnen, `allow_dynamic`,
`max_fanout`, `max_depth` und die Teilungsliste des *übergeordneten* Agents, als
hätte die Autorin der Delegierten sie gewählt.

Die Veröffentlichung lehnt das ab, und die Laufzeit streicht es außerdem aus der
Teilungsliste, sodass auch ein vor dieser Regel gespeicherter Spec eine Delegierte
nicht erweitern kann.

Ob eine Delegierte überhaupt delegieren darf, beantwortet ihr eigener Spec, und wie
tief sie gehen darf, ebenfalls — begrenzt durch das, was der Baum über ihr übrig
hat.

Das Teilen ist außerdem der einzige Weg zu einer
[MCP-Verbindung](../mcp.md) für eine Inline-Spezialistin, die selbst gar keine
binden kann: Eine Verbindung ist organisationsweite Konfiguration, und sie über
eine Spezialistin zu erreichen, die niemand veröffentlicht hat, ist die falsche
Tür. Binden Sie sie am übergeordneten Agent und benennen Sie sie hier.

**`create_agent` und `delegate` werden nur unter `allow_dynamic` angeboten.** Ein
Tool, das in der Deklaration einer Capability fehlt, kann weder von der
Genehmigungsrichtlinie gegatet noch von einer Bindung umbenannt werden, und die
gefährliche Hälfte davon ist still — deshalb sind alle zehn deklariert, und eine
Standardkonfiguration bietet sieben an.

Was der Schalter einbringt, ist eine Spezialistin, die das Modell selbst schreibt:
Instruktionen und ein Modell, und sonst nichts.

Sie wird über dasselbe `build_agent` gebaut, über das eine Inline-Spezialistin
kommt, auf dem gemeinsamen Budget-Guard des Runs und dessen Genehmigungskanal,
sodass ihre Anfragen bepreist und gegen das von jemandem gesetzte Cap gezählt
werden.

Das ist der ganze Grund, warum es dafür eine **Factory** brauchte statt eines
Schalters. Eine Spezialistin, die die Bibliothek für sich selbst gebaut hätte, säße
außerhalb des Modellkatalogs dieses Deployments, seines Vaults und seines
Budget-Guards — eine nicht erfasste Anfrage, womöglich an einen Provider, für den
die Organisation keinen Schlüssel hält. Die Factory ist das, was sie stattdessen
durch diese Plattform zurückleitet.

!!! note "Eine Spezialistin, die kein Modell benennt, wird abgelehnt"

    Vor `subagents-pydantic-ai` 0.2.18 führte die Bibliothek einen
    Standard-Modellstring mit, aus dem eine modelllose Spezialistin kompiliert
    wurde. 0.2.18 hat diesen Rückfall entfernt, und diese Plattform lehnt es noch
    früher ab, in `DelegatingToolset._refuse_dynamic`.

Das Modell darf nur ein Modell benennen, für das die Organisation ein Profil hat,
und die Ablehnung nennt die Liste. Es darf keine Capabilities anhängen: Einem
Modell zu erlauben, seinem eigenen Kind eine Capability zu gewähren, ist das
Versagen des nicht gewährten Scopes mit einem neuen Hut. Sie bekommt kein Wissen,
keine eigenen Delegierten, und nichts wird über Runs hinweg gespeichert — eine
Spezialistin zu behalten heißt, einen Agent zu veröffentlichen, und das ist die
Handlung einer Person. `MAX_DYNAMIC_SPECIALISTS` begrenzt, wie viele ein Run
behalten darf.

Dass eine Spezialistin nicht gespeichert wird, ist Absicht, und es hat einen
Ausgang statt einer Sackgasse: Eine Person kann eine solche zu einem Entwurfs-Agent
**befördern**.

Ihre Definition reist auf dem eröffnenden `SubagentStarted`-Frame mit — der einen
Stelle, an der sie lesbar ist, nachdem das Modell sie geschrieben hat und bevor der
Zug endet —, sodass das Delegationspanel im Chat anbieten kann, sie zu behalten,
während der Run noch auf dem Bildschirm ist, und der Builder bietet dasselbe bei
einer Inline-Spezialistin an.

Die Beförderung erzeugt einen Entwurf, der demjenigen gehört, der befördert hat,
gegatet auf `agents:edit`, und hört dort auf: Sie veröffentlicht nicht, heftet den
neuen Agent nicht als Delegierten an und entfernt auch nicht die Spezialistin, aus
der er hervorging.

Siehe [Konzepte](../concepts.md#delegate-vs-inline-specialist) dafür, warum die
Speicherregel der Grund für den Ausgang ist statt eine Einschränkung, die er
umgeht.

Eine behaltene hält den gesamten Run, in dem sie erfunden wurde, eine
Genehmigungsparkung eingeschlossen: Die Registrierung lebt in einer Registry, die
die Delegationsbibliothek pro *gebautem* Agent aufbaut, und ein Run, der parkt,
wird bei der Fortsetzung erneut gebaut — sie ging also über die Parkung hinweg
verloren, bis die Registrierungen in `PausedRunState` mitgeführt und beim erneuten
Abspielen neu registriert wurden
([#175](https://github.com/vstorm-co/agenticos/issues/175)). Sie überdauert nicht
in den *nächsten Zug der Unterhaltung*, der ein frischer Aufbau ohne pausierten
Zustand ist — ein in einer Antwort erzeugter Name ist in der nächsten unbekannt,
und die Beschreibung von `create_agent` sagt dem Modell, es solle ihn erneut
erzeugen, wenn `task` das nahelegt.

**Die eigene unspezialisierte Delegierte der Delegationsbibliothek wird gar nicht
angeboten**, und es gibt keine Einstellung dafür.

Vor subagents-pydantic-ai 0.2.18 wäre sie auf einem Modell gelaufen, das dieses
Deployment nicht konfiguriert hat — kompiliert aus dem bibliothekseigenen
Standard-Modellstring, außerhalb der Profile der Organisation, ihres Vaults und des
Budget-Guards des Runs. Genau wie die Laufzeit-Spezialistin oben, bevor es dafür
eine Factory gab.

Ein Auffangbecken ist ein legitimer Wunsch. Schreiben Sie es als
Inline-Spezialistin, wo Sie lesen können, was sie tut, und sie wie alles andere
bepreist wird.

Die Delegierte der Bibliothek ist seit 0.2.18 behoben
([#174](https://github.com/vstorm-co/agenticos/issues/174)): Ohne Standardmodell
und ohne Factory weigert sie sich nun, die Delegierte zu bauen, statt ein Modell
auszuwählen.

Was dem Modell über all das gesagt wird, wird hier geschrieben statt von der
Bibliothek: die Delegierten mit Namen und Beschreibung, der Modus, den dieser Run
tatsächlich verwenden wird, und die Fan-out-Obergrenze, die es sonst dadurch
entdecken würde, dass es abgelehnt wird. Zwei Listen derselben Delegierten in einem
System-Prompt sind doppelt bezahlter Kontext, und nur eine davon kann sagen, was
das Deployment durchsetzt.

Was eine Delegation kostet und welche Run-Zeile sie festhält, steht unter
[Governance](../governance.md#delegation-spends-the-parents-budget). Wer an wen
delegieren darf, steht unter
[Berechtigungen](../permissions.md#delegation-is-not-a-privilege-boundary).

## Planung { #planning }

`write_plan` — *legt die ganze Checkliste an oder ersetzt sie.*
`read_plan` — *zeigt die Schritte und ihre ids vor einer feinkörnigen Änderung.*
`add_task`, `update_task_status`, `update_task_statuses`, `remove_task` — *ändern
einen Schritt oder eine Gruppe, ohne den Plan zu ersetzen.*
`add_subtask`, `set_dependency`, `get_available_tasks` — *abhängigkeitsbewusste
Planung, nur unter `enable_subtasks` angeboten.*

Eine Checkliste, die das Modell während der Arbeit für sich selbst führt: was
erledigt ist, was in Arbeit ist, was übrig ist. Bei mehrstufiger Arbeit ist ein
Modell besser, wenn es die Schritte zuerst aufschreibt und sie sich vor Augen hält,
deshalb wird der aktuelle Plan in jedem Zug als **cache-sichere Erinnerung am Ende**
zurückgespielt — nach einem Cache-Breakpoint angehängt, sodass das stabile
Prompt-Präfix bytegleich bleibt und nur der veränderliche Plan in jedem Zug neu
gelesen wird. Der Plan landet nie im System-Prompt.

Sie überschneidet sich mit der [Delegation](#delegation) so, wie sich ein Plan mit
einem Team überschneidet: Die Planung entscheidet, *was* die Schritte sind, die
Delegation entscheidet, *wer* sie macht. Sie sind orthogonal — ein Plan ist ein
Toolset plus eine Erinnerung, Delegation ist ein Toolset plus eine Run-Hülle —,
deshalb darf ein Agent beides binden, eines oder keines.

| Konfiguration | Standard | Werte |
|---|---|---|
| `enable_subtasks` | `false` | fügt die drei Subtask-/Abhängigkeits-Tools und den Status `blocked` hinzu |
| `cache_ttl` | `5m` | `5m`, `1h` — wie lange das Präfix vor der Erinnerung cachen darf |

**Keines der neun Tools wirkt auf die Welt.** Jedes verändert eine Checkliste, die
das Modell für sich selbst führt, deshalb gibt es hier nichts, was eine Person
genehmigen müsste, und die Capability deklariert `side_effecting=False`. Die drei
Subtask-Tools sind auch dann deklariert, wenn eine flache Checkliste sie nicht
anbietet, denn ein Tool, das in der Deklaration fehlt, kann weder von der
Genehmigungsrichtlinie gegatet noch von einer Bindung umbenannt werden.

**Der Plan gehört der Unterhaltung, nicht einem einzelnen Zug davon.**

Die Checkliste ist Zustand, und jede Grenze, die ein Run hat, würde sie sonst
verlieren. Ein Run, der mitten im Plan auf einer Genehmigung parkt, wird als
frischer Run fortgesetzt — und eine Chat-Nachricht *ist* hier ein Run, deshalb
begann die nächste Nachricht mit einem leeren Speicher.

Ein Agent schrieb drei Schritte, wurde gebeten, mit dem ersten zu beginnen, und
antwortete, es gebe keinen Plan und er habe nie einen erstellt (agenticos#1077).

Der Speicher gehört also dem **Runner**, nicht der Capability. Er wird aus dem
gespeicherten Plan der Unterhaltung befüllt, oder bei einer Fortsetzung aus
`paused_state`, was die neuere Kopie ist, und beim Anhalten des Runs in die
Unterhaltung zurückgeschrieben.

Eine Oberfläche ohne Unterhaltung — ein reiner API-Aufruf — hält einen Plan für die
Dauer ihres Runs, und das ist alles, was sie hat.

**Eine fertige Checkliste ist Geschichte, und ein neuer Zug beginnt nicht mit ihr.**
Die Zeile behält sie — nichts wird gelöscht —, aber ein Plan, dessen Schritte alle
`completed` oder `cancelled` sind, wird nicht in den nächsten Zug übernommen: Die
Erinnerung am Ende würde eine Aufgabe, die niemand erledigt, „Ihren aktuellen Plan“
nennen, und `read_plan` würde damit antworten (agenticos#1221).

Die Zeile zu behalten, braucht eine weitere Regel, denn ein Zug schreibt seinen
Speicher am Ende zurück: Der Zug, dessen Speicher *über* einem fertigen Plan leer
geöffnet wurde, schreibt nichts. Er hat nichts an der Checkliste getan, und ein
leerer Dump würde die Zeile schon bei der nächsten gewöhnlichen Nachricht löschen.
Ein Agent, der neue Arbeit beginnt, legt wie üblich einen Plan an und ersetzt ihn.

Der Filter sitzt beim *Befüllen*, nicht beim Abhaken des letzten Schritts, und
darin besteht die ganze Entscheidung. Innerhalb des Zuges, der
einen Plan abschließt, hält der Speicher ihn noch, sodass der Agent zusammenfassen
kann, was er gerade getan hat, und nichts dem Transkript widerspricht. Erst die
nächste Frage beginnt sauber — und die abgehakte Checkliste steht weiterhin in den
Nachrichten darüber, wo sie sich als das liest, was getan wurde, statt als das, was
gerade getan wird. Ein `blocked`-Schritt ist ausstehende Arbeit, deshalb wird ein
Plan, der einen hält, übernommen: Irgendetwas muss ihn noch entsperren. Eine
Fortsetzung wird aus `paused_state` befüllt und bleibt unangetastet, da sie
konstruktionsbedingt mitten im Plan steht.

Ein Agent, der die Capability nicht bindet, zahlt nichts: keine Tools, keine
Erinnerung und nichts Gespeichertes, denn eine leere Checkliste gegen eine Spalte,
die null ist, ist keine Änderung, die geschrieben werden müsste.

**Sie gibt keine eigenen Tokens aus.** Die Tools sind lokale Änderungen an einer
Checkliste, hinter denen keine Modell- oder Embedding-Anfrage steht, deshalb gibt
es anders als bei Wissen oder Delegation keinen Umgebungsverbrauch zu erfassen. Die
Runden, die das Modell macht, um sie aufzurufen, sind seine eigenen, und die zählt
der Budget-Guard bereits.

## Nachdenken { #thinking }

Keine Tools. Bittet das Modell, vor der Antwort nachzudenken: langsamer und teurer,
besser bei Arbeit, die mehrere Schritte gleichzeitig im Kopf braucht.

| Konfiguration | Standard | Werte |
|---|---|---|
| `effort` | ungesetzt | `minimal`, `low`, `medium`, `high`, `xhigh` |

Ungesetzt bedeutet den eigenen Standardaufwand des Providers. Eine Stufe, die ein
Provider nicht hat, wird auf die nächstliegende abgebildet, sodass ein Spec über
einen Modellwechsel hinweg portabel bleibt.

## Systemerinnerungen { #system-reminders }

Keine Tools. Wiederholt steuernde Hinweise mitten im Run, damit eine lange Sitzung
nicht von ihren Instruktionen abdriftet — das Versagen, das dies behebt, ist das
Verblassen der Instruktionen, bei dem ein Modell nach vielen Tool-Zügen die
Hinweise, mit denen es begonnen hat, zunehmend ignoriert. Es ist eine Portierung
von `SystemReminders` aus
[`pydantic-ai-harness`](https://github.com/pydantic/pydantic-ai-harness).

Es gibt drei Arten von Erinnerungen, jede mit ihrem eigenen Takt:

| Art | Kosten | Text, den sie einfügt |
|---|---|---|
| `reminders[]` | keine | Eine feste Zeile, die Sie schreiben |
| `goal_reanchor` | keine | Die erste Nutzeranfrage des Runs, als Anker wiederholt |
| `llm_reminder` | ein Modellaufruf pro Auslösung | Ein kurzer Hinweis, den ein Modell aus dem jüngsten Transkript schreibt |

Jede Art nimmt `interval` (bei jeder N-ten Modellanfrage auslösen), `first_after`
(die Nummer der Anfrage, bei der zum ersten Mal ausgelöst wird) und `max_fires`
(die Obergrenze über die Unterhaltung hinweg) entgegen; `cache_ttl` auf der
Capability legt die Lebensdauer des Cache-Breakpoints fest. Mindestens eine Art
muss gesetzt sein, sonst steuert die Capability nichts bei und wird aus dem Run
gestrichen — und genau das bedeutet eine leere Konfiguration.

**Der Takt zählt über die gesamte Unterhaltung, und er ist dauerhaft.** Eine
Erinnerung löst bei Modellanfrage Nummer N aus, und dieser Zähler wird auf der
Unterhaltung gespeichert und im nächsten Zug zurückgeladen — eine Erinnerung, die
alle zehn Anfragen auslösen soll, zählt also dort weiter, wo der letzte Zug
aufgehört hat, statt auf null zurückzuspringen, und eine Unterhaltung zu verlassen
und neu zu laden, setzt sie fort (#787). Gespeichert werden nur die Zähler; der
Erinnerungstext wird pro Anfrage eingefügt und gelangt nie ins Transkript.

**Das Einfügen ist cache-sicher.** Eine ausgelöste Erinnerung wird an das *Ende*
der Anfrage als flüchtiger Nutzer-Prompt hinter einem Cache-Breakpoint angehängt,
nachdem der Kern die dauerhafte Historie gespeichert hat — sie erreicht also das
Modell, gelangt aber nie in `message_history`, es häufen sich keine veralteten
Erinnerungen an, und das gecachte Präfix (Tools, System, die echte Unterhaltung)
bleibt Zug um Zug bytegleich, während nur die kleine Erinnerung außerhalb des
Caches liegt. In den System-Prompt einzufügen, würde stattdessen bei jeder
Auslösung das gecachte Präfix sprengen *und* veraltete Erinnerungen ansammeln.

**Eine LLM-Erinnerung wird erfasst und erbt das Modell des Runs.**

Sie schreibt ihren Text über einen Agent, den sie selbst baut und den kein
Budget-Guard umschließt — ihre Ausgaben werden daher auf das Konto des Runs gebucht,
so wie bei einer Zusammenfassung, und sie läuft unter den Verbrauchsgrenzen des
Runs abzüglich einer reservierten Anfrage, sodass sie den Run nie über sein eigenes
Schrittlimit hinausschieben kann.

Sie verwendet das eigene Modell des Runs — dasjenige, dessen Zugangsdaten der Vault
aufgelöst hat — statt eines Namens aus der Konfiguration, dieselbe Entscheidung,
die die [Kontextverwaltung](#context-management) für ihren Zusammenfasser trifft.

Bei jedem Fehler, oder wenn das reservierte Budget bereits verbraucht ist, fällt
sie auf die Zielanker-Zeile zurück. Eine fehlgeschlagene Erzeugung blockiert den
Run nie.

## Datum und Uhrzeit { #date-and-time }

Keine Tools. Legt das aktuelle Datum und die aktuelle Uhrzeit in die Instruktionen
des Agents, damit er aufhört, eines anzunehmen — das Versagen, das dies behebt, ist
ein Agent, der selbstbewusst über „dieses Quartal“ von seinem Trainingsstand aus
nachdenkt.

| Konfiguration | Standard | |
|---|---|---|
| `timezone` | `UTC` | ein beliebiger IANA-Name, z. B. `Europe/Warsaw` |

## Kontextverwaltung { #context-management }

Keine Tools. Stutzt die Nachrichtenhistorie eines langen Runs vor jeder Anfrage,
sodass ein Run, der sonst an die Grenze des Modells gestoßen wäre, weiterarbeitet.
Die Strategien stammen aus
[`pydantic-ai-harness`](https://github.com/pydantic/pydantic-ai-harness).

| Konfiguration | Standard | |
|---|---|---|
| `strategy` | `summarize` | `summarize`, `tiered`, `clear_tool_results`, `sliding_window` |
| `max_fraction` | `0.9` | 0,05–0,95 des Fensters, ab dem die Compaction beginnt |
| `keep_messages` | 20 | jüngste Nachrichten, die eine Zusammenfassung oder ein Fenster überleben |
| `keep_tool_pairs` | 3 | jüngste Tool-Aufrufe, die ihre Ergebnisse behalten |
| `summary_prompt` | der bibliothekseigene | was dem zusammenfassenden Modell gesagt wird; muss `{messages}` enthalten |
| `context_window` | ungesetzt | überschreibt das Fenster — das, wogegen dies auslöst, *und* das, wodurch die Anzeige im Chat teilt |
| `fallback_context_window` | 200000 | Fenster, das anzunehmen ist, wenn das des Modells nicht aufgelöst werden kann |

`summarize` ist der Standard, weil es die einzige Strategie ist, die bewahrt, was
die älteren Züge *gesagt* haben. Die Strategien ohne LLM sind billiger, weil sie
Information wegwerfen — ein gleitendes Fenster verwirft die ältesten Nachrichten
rundheraus, ein geleertes Tool-Ergebnis löscht eine Antwort, die der Agent noch
brauchen könnte —, und ein Agent, der mitten im Run still vergisst, was ihm gesagt
wurde, ist ein schlimmeres Versagen als eine Zusammenfassung, um die niemand gebeten
hat. Sie löst aus demselben Grund bei 0,9 des Fensters aus: Bei der Compaction
beginnt ein Run, Details zu verlieren, deshalb wird sie aufgeschoben, bis das
Fenster nahezu voll ist.

`tiered` ist die sparsame Wahl und eine Bindung entfernt: Es leert zuerst alte
Tool-Ergebnisse und bezahlt eine Zusammenfassung nur, wenn das nicht gereicht hat.
Zusammenfassen macht aus Eingabe-Tokens Ausgabe-Tokens, die mit einem Aufschlag
abgerechnet und seriell erzeugt werden, deshalb ist ein Agent, dessen Runs von
großen Tool-Ergebnissen dominiert werden, meist mit `tiered` besser bedient.

**Sie reicht über einen Run, nicht über eine Unterhaltung.** Zwischen den Zügen
wird die Historie aus dem Transkript als Nutzer- und Assistententext neu aufgebaut,
deshalb sind Tool-Aufrufe und ihre Ergebnisse nicht mehr da, um komprimiert zu
werden, und keine hier vorgenommene Änderung überdauert eine Zuggrenze. Die
Historie, deren Compaction sich lohnt, ist die lange Tool-Schleife innerhalb eines
einzelnen Runs, wo eine Verzeichnisauflistung oder eine Wissenssuche
Zehntausende Tokens groß ist.

**Der Auslöser ist ein Bruchteil, weil eine absolute Zahl nur für ein Modell
stimmt**, und derselbe Agent läuft auf dem Profil, auf das sein Spec gerade zeigt.
Das Fenster kommt aus dem Modellprofil, das es aus dem eigenen Listing des Providers
übernommen hat, als jemand das Modell hinzugefügt hat — siehe
[Welche Modelle ein Provider anbietet](../models.md#the-window-a-model-accepts-is-read-once-and-kept).

Wo das Profil nichts festgehalten hat, wird das Fenster stattdessen aus der
mitgelieferten Preis-Momentaufnahme aufgelöst, und zwei Fälle lösen falsch auf —
beide in die Richtung, die einen Run kaputt macht, statt in die, die eine
Zusammenfassung verschwendet: Ein Spec mit Fallbacks baut ein `FallbackModel`,
dessen zusammengesetzte id auf nichts auflöst, und `genai-prices` hält für
`anthropic:claude-sonnet-4-5` 1.000.000 fest gegenüber echten 200.000, wo
`max_fraction=0.9` den Auslöser auf 900.000 legt und die Compaction nie auslöst.
`context_window` überschreibt alles und ist die Antwort auf beides — ein Provider
veröffentlicht das Maximum, das ein Modell annehmen *kann*, und ein Deployment mit
Beta- oder Tier-Beschränkung bekommt weniger.

**Der Auslöser berücksichtigt, was jede Anfrage mitführt.** Er misst die
Nachrichtenteile; eine Anfrage trägt außerdem die Instruktionen und jedes
Tool-Schema. Bei einem echten Agent sah der Schätzer 60 Tokens, wo der
Provider 3.865 abrechnete — der Overhead wird deshalb an jeder Antwort gemessen
und das Fenster des Auslösers um ihn nach unten verschoben, und genau das lässt
die Anzeige
und den Auslöser eine Obergrenze beschreiben statt zwei.

Er wartet auf eine Antwort, an der er messen kann, deshalb löst die erste Anfrage
eines Runs allein anhand der Nachrichten aus. Und er gibt auf, wenn der Overhead
allein bereits jenseits des Auslösers liegt: Keine Zusammenfassung kommt darunter,
die Schemata stehen nicht in der Historie, und ein korrigiertes Fenster würde für
immer bei jeder Anfrage eine Zusammenfassung einbringen.

**Wenn sie aufgibt, sagt sie das.** Ein `context_window`, das kleiner ist als der
Overhead des Agents selbst, ist dieser Fall, und nichts dagegen zu tun, ist auf dem
Bildschirm nicht von einer funktionierenden Einstellung zu unterscheiden — deshalb
zeigt der Chat, wie hoch der Overhead ist und gegen welches Fenster er gemessen
wurde, und das ist das Paar, das jemand braucht, um eine funktionierende Zahl zu
wählen. Einmal pro Run, weil es eine Konfiguration beschreibt statt eines
Ereignisses, und es wird in dem Moment verdrängt, in dem tatsächlich eine
Zusammenfassung läuft.

**Eine Zusammenfassung sagt, dass sie stattfindet.** Sie ist eine ganze
Modellanfrage zwischen zwei eigenen des Zuges, bei der sonst nichts streamt — der
Chat blieb früher für ihre Dauer stehen, was sich wie ein kaputter Bildschirm liest
und dazu führt, dass die Seite neu geladen und der Zug abgebrochen wird. Der Chat
zeigt jetzt, was gerade zusammengefasst wird, während es geschieht. Nur die
zusammenfassende Strategie: Die anderen bearbeiten eine Liste und kehren zurück.

**Eine Zusammenfassung wird erfasst.** Die Strategie schreibt sie über einen Agent,
den sie selbst baut und den kein Budget-Guard umschließt, deshalb misst die
Capability den Verbrauch des Runs über den Hook hinweg und bucht die Differenz auf
das Konto des Runs. Sie wird festgehalten statt verhindert: Der Guard lehnt bei der
*nächsten* Anfrage ab, deshalb stoppt eine Compaction, die ein Cap überschreitet,
den Run danach und nicht während ihrer selbst.

**Die Anzeige daneben gehört nicht zu dieser Bindung.** Wie voll das Fenster war,
meldet jeder Agent, ob er komprimiert oder nicht — siehe
[wie voll das Kontextfenster ist](../governance.md#how-full-the-context-window-is).
Die Warnung zählt am meisten für den Agent, der *nicht* komprimieren wird, denn das
ist der, der an die Decke stößt und abgelehnt wird.

## Grenzen für Tool-Ausgaben { #tool-output-limits }

Ein Tool, `read_tool_result`. Wo `compaction` die Historie *innerhalb* des Fensters
zwischen zwei Anfragen stutzt, verhindert dies, dass eine übergroße Tool-Rückgabe
überhaupt dorthin gelangt. Ein `ToolReturnPart` bleibt bestehen, deshalb wird ein
grep über ein großes Repository oder eine geschwätzige API-Antwort bei jeder
späteren Anfrage des Runs vollständig erneut gesendet — `code_execution` schneidet
genau aus diesem Grund bereits bei 8.000 Zeichen ab, was der richtige Standard und
die falsche Obergrenze ist: Der Teil, auf den es ankam, ist aus dem Blick des
Modells verschwunden, und es bleibt nichts, worauf es reagieren könnte. Dies
verkleinert eine Rückgabe einmal, wenn sie entsteht, und lässt die verkleinerte Form
bestehen. Die Verkleinerung selbst ist `ToolOutputLimits` aus
[`pydantic-ai-harness`](https://github.com/pydantic/pydantic-ai-harness).

| Konfiguration | Standard | |
|---|---|---|
| `action` | `spill` | `spill`, `truncate`, `summarize` |
| `threshold` | 10000 | Größe, ab der eine Rückgabe verkleinert wird |
| `over_tokens` | `false` | die Schwelle in geschätzten Tokens messen, nicht in Zeichen |
| `max_chars` | 4000 | Zeichen, die beim Abschneiden einer Rückgabe erhalten bleiben, oder wenn ein Spill darauf zurückfällt |
| `truncation_strategy` | `head_tail` | `head`, `tail`, `head_tail` — welches Ende bzw. welche Enden behalten werden |
| `strip_ansi` | `false` | Terminal-Farbcodes vor dem Messen und Verkleinern entfernen |
| `summary_prompt` | der bibliothekseigene | was dem zusammenfassenden Modell gesagt wird; muss `{tool_name}` und `{output}` enthalten |

`spill` ist der Standard und der einzige verlustfreie: Die vollständige Rückgabe
wird in das Backend des Agents geschrieben und durch ein Handle, eine Vorschau und
eine Strukturskizze ersetzt, und das Modell liest bei Bedarf Ausschnitte davon über
`read_tool_result(handle, offset, limit, from_end, pattern)` — dasselbe Muster zum
Durchblättern, das ihm `read_file` über den Workspace gibt. `truncate` ist die
billige, verlustbehaftete Klammer mit einer Markierung, die sagt, was abgeschnitten
wurde; `summarize` ersetzt die Rückgabe durch eine LLM-Zusammenfassung und ist die
teure Variante.

**Ein Spill geht in das eigene Backend des Agents.**

Ein Agent, der `sandbox` bindet, hat bereits ein Dateisystem — `state`, einen
Docker-Container, Daytona —, das der Runner für den Run geöffnet und der
Organisation zugeordnet hat. Der Spill lebt dort, unter einem `tool_output/`-Präfix,
teilt also die Lebensdauer dieses Workspace, und der Agent kann ihn sogar über sein
eigenes `read_file` und `grep` erreichen.

Beim standardmäßigen Sitzungs-Scope `run` *ist* diese Lebensdauer der Run, und
genau das verlangt die Anforderung „darf den Run nicht überdauern“.

Ein Spill ist ein Artefakt innerhalb eines Runs und überdauert den Run auch auf
einem länger gefassten Workspace (`conversation`, `user`, `agent`) nie:

- bei einem `state`-Workspace wird das reservierte Präfix beim Schreiben entfernt,
  sodass angesammelte Spills ihn nicht mehr in Richtung seiner Byte-Obergrenze
  drücken und die eigenen Schreibvorgänge des Agents ablehnen lassen können;
- bei einem *Container*-Workspace werden die Spills des Runs beim Schließen des
  Workspace von dessen Dateisystem gelöscht — anhand genau der Handles, die der Run
  festgehalten hat, nie durch ein Abräumen des Präfixes, sodass zwei gleichzeitige
  Runs, die sich einen Workspace teilen, einander die Spills nicht mitten im Flug
  wegnehmen können ([#803](https://github.com/vstorm-co/agenticos/issues/803)).

Ein Agent ohne Backend bekommt ein In-Memory-Backend, das für den Run gebaut und
mit ihm verworfen wird, sodass der Spill nie auf eine geteilte Platte geschrieben
wird.

Ein Spill, den das Backend ablehnt — ein `state`-Workspace, der bereits an seiner
Byte-Obergrenze ist —, fällt auf ein Abschneiden zurück statt still verworfen zu
werden. Ebenso ein `summarize`, dessen Modellaufruf scheitert:
`summarize` → `spill` → `truncate`.

**Eine Zusammenfassung wird dem Run berechnet.** Wie bei `compaction` läuft der
zusammenfassende Aufruf über einen `Agent`, den der Harness selbst baut, außerhalb
des Budget-Guards, deshalb werden seine Tokens über denselben Pfad für
Umgebungsverbrauch auf das Konto des Runs gebucht — siehe
[wie die Kosten eines Runs gezählt werden](../governance.md). `spill` und
`truncate` rufen kein Modell auf und kosten nichts.

Der Harness setzt Verkleinerungen aus einer geordneten Liste von Größen-*Bändern*
zusammen; hier wählt eine Autorin eine `action` bei einer `threshold`, denn das
Builder-Formular kann keine verschachtelte Liste zeichnen — aus demselben Grund
wählt `compaction` eine Strategie, statt Stufen zusammenzusetzen.

## Tool-Suche { #tool-search }

Keine eigenen Tools. Lässt den Agent ein Tool aus einer großen Menge *finden*,
statt bei jeder Anfrage das Schema jedes Tools in seinem Kontext mitzuführen. Das
zählt am meisten für [MCP](../mcp.md): Ein Agent darf beliebig viele Server binden,
und jedes Tool, das ein Server bereitstellt, ist ein Schema, für das das Modell in
jedem Zug bezahlt, ob es es jemals aufruft oder nicht.

| Konfiguration | Standard | Werte |
|---|---|---|
| `strategy` | `auto` | `auto`, `keywords`, `bm25`, `regex` |
| `max_results` | 10 | 1–50, von der nativen Suche ignoriert |

- **`auto`** — native Tool-Suche, wo der Provider sie anbietet (Anthropic BM25 oder
  regex, OpenAI serverseitig), sonst überall der lokale Schlagwortalgorithmus.
- **`keywords`** — immer lokal abgleichen, bei jedem Provider.
- **`bm25` / `regex`** — einen Anthropic-nativen Algorithmus erzwingen; ein Run auf
  einem Provider ohne native Tool-Suche wirft einen Fehler, statt still einen
  anderen einzusetzen. Das Modell wird getrennt vom Spec aufgelöst, das ist also
  eine Laufzeitkosten, die die Autorin akzeptiert, indem sie einen benennt — `auto`
  scheitert nie auf diese Weise.

**Sie einzuschalten, ist das, was die MCP-Toolsets zurückstellt.** Die Capability
und die Zurückstellung sind zwei Hälften einer Entscheidung: Das `ToolSearch` der
Bibliothek ist ohne Zurückgestelltes wirkungslos, und ein zurückgestelltes Tool
ohne eine Suche, die es findet, ist ein Tool, das das Modell nie aufrufen kann.
`tool_search` zu binden ist also das, was die Toolsets der verbundenen Server zum
zurückgestellten Laden markiert — die Tools der Registry selbst bleiben sichtbar,
da sie wenige und pro Agent gewählt sind. Ein Agent, der es nicht bindet, zahlt
nichts und sieht jedes Tool wie zuvor.

**Die Zurückstellung ändert, was das Modell sieht, nie die Identität eines Tools.**
Ein gefundenes MCP-Tool kommt unter seinem echten, präfigierten Namen an, sodass
das [Genehmigungs-Gate](#what-a-binding-may-change) weiterhin darauf passt und die
Umbenennung einer Bindung es weiterhin erreicht; `ToolSearch` sitzt ganz außen und
liest die Namen, die eine Umbenennung bereits angewandt hat.

**Sie braucht keine Erfassung.** Die beiden lokalen Strategien laufen in Python und
geben keine Tokens aus; die native Suche läuft innerhalb der Anfrage des Providers
selbst, deren Verbrauch der [Budget-Guard](../governance.md) bereits erfasst; und
die Runden zur Entdeckung sind gewöhnliche Modellanfragen, die derselbe Guard
umschließt. Die eine Form, die ihm entgehen würde — eine eigene Suchfunktion, die
selbst ein Modell oder ein Embedding aufruft —, ist bewusst nicht freigegeben.

## Guardrails { #guardrails }

Keine Tools. Prüft den Text, der durch einen Run fließt, an drei Kanten und
**schwärzt** entweder einen Treffer oder **blockiert** den Run. Die Prüfungen sind
fertige Detektoren aus `pydantic-ai-harness`; ein Agent ist Daten, deshalb wählt und
parametrisiert die Konfiguration sie, statt eine Python-Prüfung mitzuführen.

| Kante | Liest | Schwärzen | Blockieren |
|---|---|---|---|
| Eingabe | den Prompt der Nutzerin | `redact_secrets_in`, `redact_pii_in` | `blocked_keywords_in` |
| Ausgabe | die Antwort des Agents | `redact_secrets_out`, `redact_pii_out` | `blocked_keywords_out` |
| Tool-Ergebnis | was ein Tool zurückgab, bevor das Modell es liest | `redact_secrets_tool`, `redact_pii_tool` | `blocked_keywords_tool` |

| Konfiguration | Standard | |
|---|---|---|
| `redact_secrets_*` | `false` | API-Schlüssel, Tokens, JWTs und PEM-Blöcke entfernen |
| `redact_pii_*` | `false` | E-Mail, IBAN (mod-97), Karte (Luhn) und US-SSN entfernen |
| `blocked_keywords_*` | `""` | durch Komma oder Zeilenumbruch getrennte Begriffe; ein Treffer beendet den Run |

Jedes Feld ist standardmäßig aus, und eine Capability, die ohne konfigurierte Kante
aktiviert wird, hängt nichts an — ein Agent, der sie nicht nutzt, zahlt nichts.

**Das Schwärzen schreibt um; eine Blockade ist ein Run-Ergebnis.** Ein Schwärzer
entfernt den Treffer, und der Run läuft zu Ende — eine Antwort, die einen Schlüssel
zurückzitiert hat, hat die Arbeit trotzdem getan. Eine Schlagwort-Blockade beendet
den Run stattdessen mit dem Status `guardrail_blocked`, einem eigenen Ergebnis
neben `budget_exceeded`, denn eine Ablehnung ist die Plattform bei der Arbeit, und
eine Betreiberin, die nach Problemen filtert, sollte sie finden können, statt dass
sie sich wie jede abgeschlossene Antwort liest. Siehe
[Governance](../governance.md).

**Die Prüfung von Tool-Ergebnissen ist der Grund, warum diese Kante am meisten
zählt.** Sie ist die einzige Absicherung gegen nicht vertrauenswürdige Inhalte, die
in die Schleife gelangen — eine abgerufene Seite, eine Datei, die Antwort eines
MCP-Servers —, wo eine Prompt-Injection-Nutzlast das Modell sonst ungelesen
erreichen würde.

Zwei Dinge stehen bewusst außerhalb des Umfangs. **Tool-Argumente** sind eine
strukturierte Abbildung ohne Textdetektor, deshalb sind sie keine Kante. Und das
`approve`-Urteil des Harness für ein Tool ist nicht portiert:
[Genehmigungen](../governance.md) parken einen Run bereits pro Tool für eine
menschliche Entscheidung, und ein zweiter, regelgetriebener Pfad zu demselben
Mechanismus ist das, was eine einzige Tür vermeidet.

## Chat-Kanal-Abfrage { #chat-channel-lookup }

`get_channel_info` — *Beschreibt den Kanal, in dem diese Unterhaltung stattfindet.*
`list_channel_members` — *Listet die Personen in diesem Kanal auf.*
`search_channels` — *Findet andere Kanäle nach Namen oder Zweck, ohne sie zu lesen.*
`read_channel_history` — *Liest die jüngsten Nachrichten in diesem Kanal, die neuesten zuletzt.*

Die eine Capability, die der Spec eines Agents nicht binden darf. Sie wird **pro
Bindung** gewährt, im Builder unter *Where this agent is available*, denn eine
Organisation kann einen Agent an zwei Mattermost-Server und drei Slack-Workspaces
binden — und „darf er lesen, was in diesem Kanal gesagt wurde“ hat beim internen
eine andere Antwort als beim Kundenkanal. Ein Feld im Spec hätte eine Antwort für
alle fünf, deshalb lehnt die Veröffentlichungsprüfung `channel_tools` in einem Spec
ab, und der Run baut die Bindung aus der Zeile zusammen, die die Nachricht
zugelassen hat — genau so, wie er den Prompt dieser Zeile an die Instruktionen
anhängt.

Sie ist trotzdem eine gewöhnliche Registry-Capability, und das ist der Sinn dieses
Vorgehens statt des Einschleusens eines Toolsets: Ihre Tools können durch
`tool_approval` gegatet und durch `tool_overrides` umbenannt werden, und beides
liest den Spec.

| Konfiguration | Standard | Bereich |
|---|---|---|
| `tools` | `[]` | beliebige der vier ids |
| `default_limit` | 20 | 1–200 |

Standardmäßig wird nichts gewährt, und was eine Plattform nicht beantworten kann,
wird nicht angeboten: Telegram gibt einem Bot kein Verzeichnis von Chats zum Suchen
und keine Möglichkeit, Nachrichten zu lesen, die ihm nicht gesendet wurden.
`docs/channels.md` hat die Tabelle pro Plattform und die Begründung.

Drei Eigenschaften gelten auf jeder Plattform:

- **Die Mitgliedschaft des Bots ist die gesamte Berechtigungsgrenze.** Jeder Aufruf
  verwendet das Token des Bots, der Agent sieht also genau das, was der Bot sieht.
- **Das Modell benennt nie einen Kanal.** Die Tools sind serverseitig an den Kanal
  gebunden, in dem die Nachricht eingegangen ist — in einem Thread an den Kanal, der
  ihn enthält.
- **Außerhalb eines Kanals steuert sie nichts bei.** Ein Run vom Dashboard, aus der
  API oder aus einem Zeitplan hat kein Verzeichnis, deshalb wird die Capability gar
  nicht erst angehängt — aus demselben Grund, aus dem `knowledge` ohne Collections
  nicht angehängt wird.

## Was eine Bindung ändern darf { #what-a-binding-may-change }

Der Katalog ist die Antwort des Deployments auf „was existiert“. Ein
`capabilities[]`-Eintrag in einem Spec ist die Antwort eines Agents auf „wie
benutze ich es“, und er darf vier Dinge ändern:

| Feld | Wirkung |
|---|---|
| `config` | Gegen das Schema dieser Capability validiert, **beim Veröffentlichen**, nicht zur Laufzeit |
| `approval` | `default` \| `required` \| `never` für jedes Tool, das die Capability beisteuert |
| `tool_approval` | Dasselbe, pro Tool, überschreibt `approval` |
| `tool_overrides` | Der `name` und die `description`, die das Modell sieht, pro Tool |
| `secret_id` | Welches Secret der Organisation eine deklarierte Schlüsselanforderung erfüllt |
| `enabled` | Aus, ohne die Konfiguration zu verlieren |

Die Genehmigung ist der Grund, warum eine Capability ihre Tools überhaupt
deklariert. „Darf dieser Agent Dateien schreiben“ und „darf er sie lesen“ sind zwei
Entscheidungen, obwohl eine Capability beide beantwortet — deshalb bleibt das
Aktivieren pro Capability, während das Genehmigen pro Tool geschieht. `default`
folgt dem eigenen `side_effecting`-Flag der Capability.

!!! tip "Die Beschreibung eines Tools ist der Prompt mit der größten Hebelwirkung im Produkt"

    Sie ist das, was das Modell liest, bevor es sich zum Aufruf entscheidet, und
    sein Name steuert genauso stark: `search_refund_policy` ist nicht
    `search_documents`. Ein Agent, der von demselben Tool ein anderes Verhalten
    braucht, braucht meist eine andere Formulierung dieser beiden und keine zweite
    geschriebene Capability.

!!! danger "Am stabilen id des Tools verschlüsselt, nie am Namen, den das Modell sieht"

    Das ist es, was ein Genehmigungs-Gate an einem umbenannten Tool hängen lässt.
    Es am sichtbaren Namen zu verschlüsseln, hieße, dass eine Umbenennung das Gate
    still entfernt und ein Aufruf mit Seiteneffekten dann unbeaufsichtigt läuft,
    ohne dass etwas es meldet. Eine id, die keine solche Capability bereitstellt,
wird beim Veröffentlichen abgelehnt, und ebenso ein Name, den kein Modell aufrufen könnte.

## Scopes { #scopes }

Eine Capability darf Scopes deklarieren, die die Organisation gewährt haben muss;
geprüft wird, wenn der Agent zusammengebaut wird:

| Scope | Deklariert von |
|---|---|
| `knowledge:read` | `knowledge`, `skills` |
| `conversations:read` | `conversation_search` |
| `web:read` | `web_research` |
| `web:fetch` | `web_fetch` |
| `web:browse` | `browser_use` |
| `code:execute` | `code_execution` |
| `sandbox:execute` | `sandbox` |
| `agents:delegate` | `subagents` |

!!! note "Alle acht werden heute standardmäßig gewährt"

    `DEFAULT_GRANTED_SCOPES` in `app/services/agent_registry.py`. Die Verwaltung
    von Scopes pro Organisation ist [Roadmap](https://github.com/vstorm-co/agenticos/blob/main/docs/ROADMAP.md)-Arbeit;
    die Prüfung ist in der Zwischenzeit aktiv und ehrlich statt abgeschaltet und
    vergessen.

!!! warning "`agents:delegate` ist nicht das Tor dafür, an *wen* delegiert werden darf"

    Das ist `agents:run`, geprüft an der veröffentlichenden Person gegen die Zeile
    jeder Delegierten. Dieser Scope beantwortet eine Frage, die keine Berechtigung
    beantworten kann: ob dieses **Deployment** Agents überhaupt erlaubt, Agents
    aufzurufen. Nehmen Sie ihn aus dieser Menge heraus, und die Delegation ist mit
    einer Änderung überall aus.

Eine Betreiberin, die keine verschachtelten Runs oder Fan-out-Abrechnung will,
entfernt ihn, und jeder Spec, der delegiert, sagt das dann beim Veröffentlichen
statt um drei Uhr nachts. `conversations:read` ist derselbe Hebel für die
Unterhaltungssuche: Eine Änderung hält jeden Agent davon ab, vergangene
Unterhaltungen zu lesen, für ein Deployment, das ein Transkript für zu sensibel
hält, um durchsuchbar zu sein, wie eng der Korpus auch gefasst ist.

## Was ein Tool dem Modell sagt { #what-a-tool-tells-the-model }

Eine Tool-Definition ist ein Prompt. Das Modell wählt ein Tool aus und füllt seine
Argumente aus, und zwar aus nichts als dem Text, der daran hängt — deshalb trägt
jedes Tool hier vier Dinge, und das vierte ist das, was üblicherweise weggelassen
wird:

1. **Was es tut**, in einem Satz. Das ist auch das, was der Builder neben dem
   Genehmigungs-Häkchen zeigt, es wird also einmal geschrieben und von beiden
   gelesen.
2. **Wann man es benutzt und wann etwas anderes.** `create_chart` sagt, dass es für
   Zahlen ist, die man bereits hat, und `generate_image` für etwas, das gezeichnet
   werden soll; `glob` sagt, dass es rekursiv sucht, wo `ls` das nicht tut.
3. **Was jedes Argument bedeutet**, einschließlich seines Standards und seiner
   Obergrenze.
4. **Was zurückkommt** — die Form der Antwort, wie ein Fehlschlag aussieht und wo
   das Ergebnis ein abgeschnittener Ausschnitt statt der ganzen Menge ist. Ein
   Modell, das nicht weiß, dass `grep` je nach `output_mode` in drei verschiedenen
   Formen antwortet oder dass `glob` bei 100 Pfaden aufhört, schließt aus einem
   Ausschnitt, als wäre er alles.

Alle vier erreichen das Modell in einer Form, und es ist die von pydantic-ai
selbst: die Prosa in `<summary>`, die Beschreibung der Rückgabe in `<returns>`.

Ein hier geschriebenes Tool bekommt das umsonst — das Framework baut es aus dem
`Returns:`-Abschnitt des Docstrings.

Ein Tool, das aus einer Bibliothek kommt, wird mit einer ausdrücklichen
Beschreibung registriert, was diesen Weg abschneidet. Sein Text läuft deshalb durch
`ToolText` in `app/agents/capabilities/_tool_text.py`, das rendert, was das
Framework gerendert hätte.

Zwei Konventionen in einer Tool-Liste sind eine Sache mehr, die das Modell
zusammenbringen muss, und `tests/test_tool_text_shape.py` ist das, was dafür sorgt,
dass es eine bleibt: Es pinnt `ToolText` gegen ein Tool, das pydantic-ai selbst
baut, und prüft, dass die Tools jeder Capability eine Rückgabeform mitführen.

Das deckt auch die Tools ab, die dieses Deployment nicht geschrieben hat:
`planning` und die Delegations-Tools bekommen den Text dieses Repositories,
`web_fetch` und `search_tools` werden dort neu beschrieben, wo sie gebaut werden,
und `read_tool_result` sowie die drei `skills`-Tools werden direkt auf dem Toolset
der Bibliothek neu beschrieben. Zwei davon waren den Aufwand über die Konsistenz
hinaus wert — der Satz der Bibliothek für `read_tool_result` sagte nichts darüber,
womit ein Handle antwortet, und das ist das Einzige, was ein Modell mit einem
Handle braucht, und `list_skills` dokumentierte die Python-Rückgabe (ein
Dictionary) statt des Textes, den das Modell bekommt.

Ein Tool aus einer Bibliothek, für das dieses Repository keinen Text hat, behält
den der Bibliothek, und das ist der richtige Standard: `run_skill_script` wird
ausgeschlossen statt beschrieben, und falls es je ankommt, kommt es mit dem an, was
seine Autorin geschrieben hat.

### Ein Fehler, ein Ergebnis und eine Ablehnung { #a-mistake-a-result-and-a-refusal }

Wie ein Tool über Probleme berichtet, entscheidet, was das Modell als Nächstes tut,
und die drei sind nicht austauschbar.

| Der Fehlschlag | Was das Tool tut | Warum |
|---|---|---|
| Die eigenen Argumente des Modells — eine Diagrammreihe mit der falschen Anzahl Werte, eine Kontextdatei, die es nicht gibt, ein `NameError` in selbst geschriebenem Python | Wiederholungsaufforderung | Ein anderer Aufruf ist eine plausible Behebung, und die Meldung sagt, wie ein korrekter Aufruf aussieht |
| Ein vorübergehender Fehlschlag dessen, was hinter dem Tool steht — ein Suchanbieter ist ausgefallen, eine Wissensdatenbank läuft in einen Timeout | Wiederholungsaufforderung | Ein Fehler in der Form eines Ergebnisses liest sich als „nichts gefunden“, und das Modell antwortet dann selbstbewusst aus dem Gedächtnis, ohne zu sagen, dass es das musste |
| Ein Ergebnis, das schlicht eine schlechte Nachricht ist — ein Befehl mit Exit-Code ungleich null, eine Suche ohne Treffer, ein Kanal, den dieser Bot nicht sehen kann | Als Text zurückgegeben | Es ist die Antwort. Das Modell denkt darüber nach und macht weiter |
| Eine Ablehnung — eine Berechtigungsregel, eine Capability, die das Deployment nicht anbietet | Als Text zurückgegeben | Eine Wiederholungsaufforderung lädt das Modell ein, nach einem Weg daran vorbei zu suchen |

Wiederholungen sind budgetiert: Ein Tool-Aufruf bekommt einen Versuch, sich selbst
zu korrigieren, und eine *jenseits* dieses Budgets ausgelöste Wiederholung beendet
den ganzen Run statt des Aufrufs. Der letzte Versuch gibt daher seine Meldung
zurück, statt zu werfen — gesteuert, solange Budget dafür da ist, und nie
schlechter als die Antwort, die er ohnehin gegeben hätte. Der eine Helfer, der das
entscheidet, ist `app/agents/capabilities/_failures.py`; `pydantic-ai-backend` hält
dieselbe Regel für die Workspace-Tools.

## Diese Liste erweitern { #adding-to-this-list }

Capabilities sind Code — nichts, was eine Betreiberin tippt, bringt eine neue
hervor, und genau das macht die Menge dessen, was ein Agent tun kann, prüfbar.
Siehe [Eine Capability hinzufügen](../howto/add-capability.md) für eine neue, oder
[Einer Capability ein Tool hinzufügen](../howto/add-capability.md#adding-a-tool-to-an-existing-capability),
wenn die Capability bereits existiert.

Für Tools, die hier niemand schreiben muss, siehe [MCP](../mcp.md).
