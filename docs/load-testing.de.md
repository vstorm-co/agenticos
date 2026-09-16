---
source_sha: "a434e301f063"
---

# Last- und Belastbarkeitstests { #load-and-resilience-testing }

AgenticOS streamt, führt Hintergrundarbeit aus und hält Sockets offen, und nichts
davon sagt etwas darüber, wie viel davon ein Deployment gleichzeitig kann.
Asynchroner Code ist kein Kapazitätsergebnis, und eine grüne Unit-Suite ist kein
Lasttest. Also gibt es eine Suite, die es misst, in `loadtest/`, und diese Seite
sagt, was sie misst, was sie einen Erfolg nennt und wie man sie wiederholt.

Die Zahlen eines Laufs gehören der Maschine, auf der er lief. Nichts hier beweist
das Architekturziel von tausend Nutzern aus NFA-006, und ein einzelner Lauf auf
einem Host beweist das Latenzziel aus NFA-001 nur für diesen Host — beides steht
dort, wo es einen Schwellenwert berührt, statt still behauptet zu werden.

## Die Last { #the-workload }

Der Verkehr eines Deployments besteht überwiegend aus Menschen, die Listen lesen,
einigen, die mit einem Agent sprechen, wenigen, die ein Dokument hochladen, und
einem Rinnsal von Ereignissen, die Routinen auslösen, denen niemand zusieht. Die
Mischung sagt das in Zahlen:

| Last | Anteil | Was eine Anfrage ist |
|---|---|---|
| `api_read` | 45% | Eine authentifizierte Liste — Agents, Runs, Unterhaltungen |
| `chat_stream` | 20% | Eine Chat-Runde über den WebSocket, jede fünfte mittendrin abgebrochen |
| `agent_run` | 15% | `POST /agents/{id}/run` — derselbe Runner ohne Socket |
| `rag_query` | 12% | Retrieval: ein Embedding, eine Vektorsuche |
| `ingest` | 5% | Ein hochgeladenes Dokument, das diese API annimmt und ein Worker indexiert |
| `trigger_fire` | 3% | Eine signierte Webhook-Zustellung, die eine Routine auslöst |

Die Anteile stehen in `loadtest/scenario.py`, jeder ist eine Zeile, und sie sind
der Teil, dem man widersprechen kann. Ein Deployment mit anderem Verkehr ändert
sie und misst neu; was nicht passieren darf, ist eine Zahl, die aus einer Mischung
zitiert wird, die niemand angesehen hat.

### Ankunftsrate, kein Worker-Pool { #arrival-rate-not-a-worker-pool }

Anfragen werden nach einem **Zeitplan** angeboten. Eine geschlossene Schleife aus
N Workern, von denen jeder auf seinen Vorgänger wartet, senkt ihre eigene
Ankunftsrate genau dann, wenn der Server langsamer wird — ein Server, der
umgefallen ist, meldet also bequeme Latenzen und einen Durchsatz, der sich still
halbiert hat. Ein offenes Ankunftsmodell bietet weiter Arbeit in der genannten
Rate an und lässt die Warteschlange wachsen, und genau das wird getestet.

Welche Last eine Anfrage ist, kommt aus einer Folge niedriger Diskrepanz statt aus
einem Würfel, sodass zwei Läufe bei gleicher Rate gleich viele Uploads schicken und
jeder Unterschied zwischen ihnen der Plattform gehört.

### Die Phasen { #the-phases }

| Phase | Sekunden | Angeboten je Sekunde | Wozu |
|---|---|---|---|
| `ramp` | 60 | 4 | Ein kalter Cache ist kein eingeschwungener Zustand |
| `sustain` | 180 | 12 | **Jeder Schwellenwert wird hieran gemessen** |
| `burst` | 45 | 36 | Dreifache Rate, wie ein Fan-out aussieht |
| `recover` | 60 | 12 | Eine Plattform, die sich erholt, und eine, die degradiert bleibt, sehen während des Bursts gleich aus |

## Was als bestanden gilt { #what-counts-as-a-pass }

Diese Schwellenwerte sind **vorgeschlagen, nicht vereinbart**. Die Abnahme von
NFA-004 verlangt vereinbarte; sie hier zu nennen gibt einem Lauf ein Urteil statt
einer Wand aus Zahlen und macht das Gespräch zu einem über eine konkrete Zahl statt
darüber, ob es überhaupt eine geben soll. Nichts hier ist eine Zusage in jemandes
Namen.

| Last | Metrik | Grenze | Warum dort |
|---|---|---|---|
| `api_read` | p95 | 300 ms | Eine Abfrage hinter einer Rechteprüfung; darüber ist es Warteschlange, nicht Arbeit |
| `api_read` | Fehlerrate | 0,1% | Raum für eine erneuerte Verbindung und für sonst nichts |
| `chat_stream` | p95 erstes Token | 1500 ms | Der Anteil der Plattform: Socket, Auth, Spec, Fähigkeiten, Run-Zeile |
| `chat_stream` | Fehlerrate | 1% | Ein abgerissener Socket kostet jemanden seine Antwort |
| `agent_run` | p95 | 5000 ms | Der ganze Run-Pfad gegen den Stub, Ende zu Ende |
| `rag_query` | p95 | 1200 ms | Begrenzt wird pgvector und der Pool davor |
| `ingest` | Fehlerrate | 0% | Ein angenommener und dann verlorener Upload ist der schlimmste Fehler hier |
| `trigger_fire` | Fehlerrate | 0% | Ein 2xx hat die Verantwortung für das Ereignis übernommen |

Jeder wird je Last beurteilt, mit Absicht. Eine Zahl über einen gemischten Lauf
beschreibt nichts: ein Upload und eine Liste sind nicht dieselbe Anfrage.

Eine Last, die keine Probe erzeugt hat, liest sich als **nicht gemessen**, nie als
bestanden. Ein Lauf, der ein Szenario übersprungen und dafür grün gemeldet hat,
ist genau das Versagen, das diese ganze Datei verhindern soll.

## Das Modell ist ein Stub, und absichtlich langsam { #the-model-is-a-stub-and-slow-on-purpose }

`loadtest/stub_model.py` bedient die Chat-Completions-API und einen
Embeddings-Endpunkt, mit einer Verzögerung bis zum ersten Token und einem Takt je
Token, die der Lauf nennt. Ein Lasttest, dessen Modell sofort antwortet, misst eine
Plattform unter einer Last, die es nicht geben kann: jeder echte Anbieter braucht
Hunderte von Millisekunden, und wie viel Gleichzeitigkeit ein Deployment hält,
entscheidet sich daran, wie lange ein Run seine Ressourcen im Warten hält.

Man kann ihm auch sagen, dass er versagen soll — `--error-rate` lehnt diesen Anteil
mit einem 500 ab und `--timeout-rate` hält sie offen — und das ist die
Belastbarkeitshälfte von NFA-004. Was die Plattform tut, wenn ihr Anbieter
ausfällt, ist eine Eigenschaft der Plattform und lässt sich gegen einen Anbieter,
der sich benimmt, nicht messen.

Nichts in einem Standardlauf berührt einen bezahlten Anbieter. Auch die Embeddings
sind die des Stubs, erreicht wie ein schlüsselloser Ollama-Endpunkt, sodass ein
Deployment ganz ohne Anbieterschlüssel messbar bleibt. Eine Messung Ende zu Ende
gegen einen echten Anbieter ist eine bewusste Handlung: das model profile der
Fixture dorthin richten und mit dessen eigener Latenz und dessen Ratenlimits in den
Zahlen rechnen.

## Ausführen { #running-it }

Vier Dinge müssen bereitstehen, und `run.py` verweigert ohne jedes einzelne den
Start, statt ein Deployment zu messen, das die Arbeit nicht tun kann:

1. eine migrierte Datenbank und Redis;
2. das antwortende Stub-Modell, **unter einer Adresse, die die API erreicht** — siehe unten;
3. die Fixture — `make load-seed`, einmal;
4. Prefect, wenn die Last `trigger_fire` etwas bedeuten soll. Ohne ihn wird ein
   Webhook angenommen und seine Weitergabe scheitert, was der Bericht als 500er auf
   dieser Last zeigt, statt es zu verbergen.

### Wo der Stub lauschen muss { #where-the-stub-has-to-listen }

Die *API* ruft den Stub auf, nicht der Treiber, also muss die im model profile
hinterlegte Adresse von dort aus funktionieren, wo die API läuft. Zwei Topologien:

| Die API läuft | Bind | Seed |
|---|---|---|
| Auf diesem Host (`uv run uvicorn …`) | `127.0.0.1` (Vorgabe) | `http://127.0.0.1:4020` (Vorgabe) |
| Im Compose-Stack (`make dev`) | `LOAD_STUB_BIND=0.0.0.0` | `LOAD_STUB_URL=http://host.docker.internal:4020` |

Loopback im `app`-Container ist der Container, nicht der Host, also ist die zweite
Zeile dort nicht optional — und wer es falsch macht, scheitert am Preflight mit
einer Meldung über eine leere Collection statt über eine Adresse, weil auch die
Embeddings den Stub nie erreichen.

```bash
make load-stub-model                       # Terminal eins
make load-seed                             # einmal
make load-test API_PID=$(pgrep -f uvicorn | head -1) \
  DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/agenticos \
  > loadtest/results/$(date +%F)-thismachine.md
```

`API_PID` und `DATABASE_URL` sind optional. Ohne sie misst der Lauf Anfragen und
**benennt im Bericht die Sonden, die er nicht nehmen konnte**, statt Nullen für sie
zu drucken.

Die Fixture-Datei enthält **keine Zugangsdaten**. Der Lauf meldet sich selbst mit
`--email` und `--password` an (den Seed-Vorgaben), sodass kein Bearer-Token auf der
Platte landet und eine gestern erzeugte Fixture heute noch läuft — ein ablaufendes
Token in einer Datei war beides: ein Geheimnis im Ruhezustand und ein Lauf, der
ohne guten Grund verweigerte.

Zwei Einstellungen lohnt es sich für einen Kapazitätslauf anzuheben, und die
Topologiezeile des Berichts sollte sagen, wann das geschah:

- **`RATE_LIMIT_RUN_PER_MINUTE`**. Das Limit gilt je Aufrufer, und der Treiber ist
  eine Identität, die für viele steht — bei den voreingestellten 30 misst das
  Experiment also den Begrenzer statt die Plattform.
- **`UVICORN_WORKERS`**, wenn die Frage dem Host gilt und nicht einem Worker.

`--scale 0.1` kürzt jede Phase und ändert sonst nichts, um den Harness selbst zu
prüfen. Einen Lauf durch Senken seiner *Rate* zu kürzen wäre ein anderes Experiment
unter demselben Namen.

`--connections` begrenzt die eigenen Sockets des Treibers und leitet sich
standardmäßig aus dem Szenario ab — Spitzenrate mal langsamste Anfrage, 3240 bei
den ausgelieferten Phasen. Eine Grenze darunter macht aus einem Lauf mit offener
Ankunft genau im Burst einen geschlossenen, also dann, wenn es zählt: Anfragen
stauen sich im Client, und ein Teil der berichteten Latenz gehört dem Treiber.

## Den Bericht lesen { #reading-the-report }

Vier Abschnitte, in der Reihenfolge, in der die Fragen gestellt werden: was lief,
was während `sustain` geschah, was während `recover`, und ob es bestand. Das
Urteil steht absichtlich zuletzt — ein Urteil oben lädt dazu ein, nur dieses zu
lesen, und die Probenzahlen darunter sagen, ob ein Ausläufer ein Befund oder drei
Anfragen ist.

Der Kopf trägt zwei Zahlen, die vor allem anderen zu prüfen sind. **Angeboten
gegen aufgezeichnet** muss übereinstimmen: jede angebotene Anfrage hinterlässt
eine Probe, erfolgreich oder nicht, auch eine am Ende des Laufs aufgegebene, und
eine Lücke bedeutet, dass die Fehlerraten über einem Nenner kleiner als die Last
berechnet sind — der Bericht sagt das in einem Banner und nennt sich selbst
unbrauchbar. **Verspätete Dispatches** ist das Eingeständnis des Treibers, hinter
seinen eigenen Zeitplan geraten und Teil der Messung geworden zu sein.

Der Durchsatz der anhaltenden Phase steht zweimal da: Abschlüsse, die im Fenster
gelandet sind, und Anfragen, die währenddessen angeboten wurden. Sie gehen
auseinander, wenn das Deployment hinterherhinkt, und nur dann ist die Zahl
interessant.

Perzentile sind **nächster Rang**, nicht interpoliert: ein interpoliertes p99 über
neunzig Proben ist eine Zahl zwischen zwei Messungen, die nichts beobachtet hat.
Und die Latenz wird nur über **erfolgreiche** Anfragen gemessen. Eine in 3 ms
abgelehnte Anfrage ist keine schnelle Anfrage, und sie in die Verteilung zu lassen
ist, wie ein umgefallener Lauf seine besten Perzentile aller Zeiten meldet; die
Fehlschläge werden getrennt gezählt und benannt.

Die CPU ist eine Differenz der kumulierten CPU-Zeit des Prozesses über jedes
Abtastintervall, nicht `ps`' `%CPU` — procps definiert das als CPU-Zeit über die
gesamte Lebensdauer des Prozesses und sagt ausdrücklich, dass es keine Auslastung
ist, sodass Abtasten genau die kurze Sättigung wegmitteln würde, die ein Burst
erzeugen soll. Die Auflösung ist damit die der Uhr von `ps` über das
Abtastintervall, unter Linux eine Sekunde auf zwei.

## Was diese Suite nicht misst { #what-this-suite-does-not-measure }

Gesagt statt dem Zufall überlassen:

- **Den Durchsatz des Workers.** Die Lasten `ingest` und `trigger_fire` messen die
  *Annahme* — die API antwortet 202 und gibt die Arbeit an einen Flow. Wie schnell
  der Worker diese Warteschlange leert, ist eine Messung dort, wo der Worker ist,
  und wird hier nicht behauptet.
- **Irgendetwas über einen echten Anbieter.** Jede Latenz in einem Standardlauf ist
  die der Plattform plus die genannte Verzögerung des Stubs.
- **Die Konsole.** Das Frontend wird nicht bewegt; dies sind API-Pfade.
- **Einen Cluster.** Ein Deployment, eine Datenbank. Das Ziel von NFA-006 ist
  architektonisch, und ein Lauf auf einem Host sagt dazu in keine Richtung etwas.

## Die gemessenen Läufe { #the-measured-runs }

Committet unter `loadtest/results/`, jeder mit Maschine, Topologie und Datum oben,
weil eine Zahl ohne sie kein Ergebnis ist.

Bisher sind zwei Läufe committet, auf derselben Maschine, mit einem Unterschied:

| | `2026-09-16-macbook-default-pool.md` | `2026-09-16-macbook-pool-raised.md` |
|---|---|---|
| Pool | 5 + 10 Overflow (die Vorgabe) | 20 + 30 Overflow |
| Anhaltende 12/s | jeder Schwellenwert erfüllt, kein Fehlschlag | jeder Schwellenwert erfüllt |
| Ganzer Lauf inklusive Burst | **1537 von 4740 scheiterten**, 6559 Pool-Timeouts | 13 scheiterten, kein einziger Pool-Timeout |
| **Nach dem Burst** | **66–100% scheitern weiter** | **keine Fehlschläge, Latenz baut ab** |

Der Befund, und der Grund für zwei Läufe: **die bindende Grenze dieser Last ist der
Verbindungspool, nicht die CPU.** Beide Läufe erreichten etwa 90% *eines* Kerns auf
einer Zehn-Kern-Maschine, weil es einen Worker gab. Die Reihenfolge ist also: erst
der Pool, dann `UVICORN_WORKERS` — und ihr Produkt muss unter `max_connections` der
Datenbank bleiben, da ein Worker bereits 84 der voreingestellten 100 erreichte.

Die Zeile zur Erholung gehört zuerst gelesen. Mit dem voreingestellten Pool wartet
eine Anfrage, die keine Verbindung bekommt, die vollen dreißig Sekunden des
`DB_POOL_TIMEOUT` — der Rückstau überlebt also den Burst, der ihn erzeugt hat, und
das Deployment scheitert weiter bei einer Rate, die es zehn Minuten zuvor bequem
bewältigte. Jede Ergebnisdatei trägt die ganze Begründung.
