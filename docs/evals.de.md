---
source_sha: "2e02221984a4"
title: "Eval-Runs"
description: "Ein Eval-Run beantwortet jeden Fall eines Datasets mit einer Agent-Version oder ihrem Draft, bewertet jede Antwort und vergleicht das Ergebnis mit einer Baseline."
---

# Eval-Runs { #eval-runs }

Ein **Eval-Run** lässt einen Agent jeden Fall einer Version eines
[Datasets](datasets.md) beantworten, bewertet jede Antwort so, wie das
[Scoring](datasets.md#scoring) des Datasets es vorgibt, und hält fest, was
passiert ist. Er beantwortet die Frage, die jemand beim Bearbeiten eines Agents
wirklich hat: Hat diese Änderung den Agent besser gemacht, schlechter oder
keines von beidem - und was hat es gekostet?

Ein Run besteht aus vier Entscheidungen: der **Agent** und was davon läuft
(eine veröffentlichte Version oder der Draft in seinem aktuellen Stand), die
**Dataset-Version**, die **Umgebung**, deren Testverbindungen die Fälle nutzen,
und optional **mehrere Modelle** nebeneinander. Im selben Run kann außerdem
eine **Baseline** laufen - eine frühere Version -, damit beide Seiten am selben
Tag auf denselben Provider treffen.

## In der Konsole { #in-the-console }

Der Tab **Evals** eines Agents öffnet mit einem Liniendiagramm seiner
Bestehensquote Run für Run, der älteste links, eine Linie pro Dataset, jede mit
eigener Strichart. Ein Punkt ist rot, wo der Run Fälle kaputt gemacht hat, grün,
wo er sie behoben hat, bernsteinfarben, wo beides, und hohl für einen Draft; der
Hover sagt, was lief, wogegen und wann, und ein Klick öffnet den Run.

Die Achse benennt jeden Punkt danach, was lief und wann - mit der Uhrzeit für
einen Run von heute, mit dem Datum für frühere. Ab mehr als 12 Runs erscheint
unter dem Diagramm ein Bereich, der mit den letzten 12 öffnet; zieh seine Griffe
oder verschieb sie mit den Pfeiltasten, um mehr oder weniger zu sehen.

Darunter stehen seine Runs, nach Dataset gruppiert, jeder mit dem, was gegen was
getestet wurde, seinem Urteil (Breaks 2, Worse overall · 4 broke, First result,
Pending) und der Bestehensquote jedes Modells, mit der Quote der ersten
Antworten beim Darüberfahren.

**Run evals** öffnet den Startdialog mit der naheliegenden Antwort: der Draft
gegen die Live-Version, wenn sich der Draft von ihr unterscheidet, die
Live-Version allein, wenn nicht, und der Draft allein bei einem Agent, den
niemand veröffentlicht hat. Das Dataset, auf dem der Agent zuletzt gemessen
wurde - oder das einzige, das es gibt -, ist bereits ausgewählt; Umgebung,
Aufzeichnungen und Wiederholungen liegen unter **Advanced**. Die Kosten werden
berechnet, sobald die Felder feststehen, und sagen, was die Antworten bewertet
und was die Budgets des Agents und der Organisation danach behalten; der Run
startet erst über den Button, der den Betrag nennt. **Draft differs from vN**
auf der Seite des Agents trägt einen Button **Test draft**, der denselben
Dialog öffnet, und der Veröffentlichungsdialog sagt, was der letzte Run des
Drafts ergeben hat - oder dass er seit seiner letzten Änderung nicht getestet
wurde -, ohne die Veröffentlichung aufzuhalten.

Die Seite eines Runs öffnet mit seinem Urteil in wenigen Sätzen - die Fälle,
die der Kandidat jedes Mal kaputt macht oder behebt, wenn er sie gestellt
bekommt, einer davon zitiert mit der Zahl der Versuche, die es wiederholt
haben, ob er insgesamt besser oder schlechter ist, wenn die bestätigten
Änderungen das entscheiden können, und die Bestehensquote vorher und nachher -
und mit dem, was als Nächstes zu tun ist: sehen, was sich zwischen den beiden
Versionen geändert hat (History öffnet auf diesem Vergleich, gegen den
getesteten Spec statt den jetzigen Draft), die kaputtgegangenen Fälle zeigen,
zurück zu Build gehen oder den Draft veröffentlichen.

Publish ist nur dann die Hauptaktion, wenn keine Regression bestätigt wurde und
kein Fall des Kandidaten unbeantwortet oder unbewertet blieb, und der Run eines
seitdem geänderten Drafts bietet stattdessen **Test again** an. Solange der Run
antwortet, sagt die Seite, wie viele erste Antworten vorliegen, und der
Vergleich wartet auf beide Seiten. Antworten, die der Judge nicht bewerten
konnte, sagen, warum, und zählen weder als bestanden noch als nicht bestanden,
und **Grade again** im Kopfbereich bewertet sie erneut, ohne den Agent zu
fragen, für jeden, der das Dataset laufen lassen darf.

Unter dem Urteil stehen die Seiten nebeneinander, wie die beiden abschneiden,
und die Fälle - jede Zeile mit einem Punkt für bestanden oder nicht bestanden
pro Seite, gefiltert nach Ergebnis oder Tag, jeder Fall mit dem, was er
erwartet, und den Antworten, Aufrufen und Bewerterbegründungen jeder Seite. Ein
gewählter Tag beschränkt die Seiten, die Änderungen und die Fälle auf ihn; das
Urteil gilt weiter für alle Fälle.

Sobald seine Wiederholungen vorliegen, schickt ein Run in die
[Review-Warteschlange](datasets.md#review) des Datasets, wofür er einstehen
kann - jede bestätigte Regression und jede Antwort, an deren Bewertung sein
Judge gescheitert ist, eine pro Fall - und sagt, wie viele (`routed_to_review`).
Ein übersprungener Judge schickt nichts: Seine Antworten warten auf der Seite
des Runs auf **Grade again**. Wird das Senden abgelehnt, endet der Run trotzdem,
und seine Seite sagt, warum (`routing_error`).
**Send failed to review** schickt die übrigen nicht bestandenen Antworten einer
Seite, für jeden, der das Dataset bearbeiten darf, und ein Fall, dessen
Bewertung eine Person überstimmt hat, wird als korrigiert markiert.

In beiden Fällen nimmt eine Antwort den Platz einer älteren, noch wartenden
Antwort desselben Falls ein, die die Warteschlange unentschieden verlässt - ein
Run nennt deren Zahl als `routed_replacing` - und eine Antwort, die älter ist
als die wartende, wird nicht gesendet.

Der eigene Tab **Evals** eines Datasets listet jeden darauf gemessenen Agent,
jeden mit seinem Verlauf und seinen Runs, und **Run evals** in seinem
Kopfbereich öffnet den Startdialog auf dem Dataset und fragt, welcher Agent
getestet werden soll.

Die Karte **Eval runs** im Dashboard listet die neuesten Runs der Organisation
mit ihrem Agent und ihrem Urteil. Die Fälle eines Evals und die Bewertung durch
den Judge bleiben aus jeder anderen Dashboard-Zahl heraus, und Activity blendet
sie aus, außer ihr Oberflächenfilter verlangt jede Oberfläche oder nur Evals.
Die Liste in Activity zeigt, was jedem Run gestellt wurde - seine erste
Nutzernachricht oder die Frage des Eval-Falls und beim Run des Judges das, was
er bewertet hat -, damit sich ein Run wiederfinden und zu einem Fall machen
lässt. Ein Eval-Fall öffnet dort seinen Eval-Run auf diesem Fall, und **See
what the model saw** eines Falls öffnet, was sein Modell bekommen hat.

## Einen Run starten { #starting-a-run }

Der Start besteht aus zwei Aufrufen, damit nichts ausgegeben wird, bevor jemand
gesehen hat, was es kosten wird.

```text
POST /api/v1/agents/{agent_id}/eval-runs/estimate   the estimate, nothing written
POST /api/v1/agents/{agent_id}/eval-runs            the same body; starts the run
```

Der Body nennt das Dataset (`dataset_id`, `dataset_version`), den Kandidaten
(`candidate: "version"` mit optionaler `version` oder `candidate: "draft"`),
die `environment_id`, die zu vergleichenden `model_profile_ids` und
`paired_baseline`. Die Schätzung ist der durchschnittliche Preis eines Runs des
Agents auf jedem Modell, gemessen an seinen letzten abgeschlossenen Runs, mal
die Zahl der Fälle, plus ein Judge-Aufruf pro Fall, wenn ein Judge das Dataset
bewertet und AI assistance eingeschaltet ist.

AI assistance ist für eine Organisation ausgeschaltet, bis jemand mit
`org:settings` es einschaltet. Solange es aus ist, läuft der Judge nicht: Ein
Fall wird durch seine Checks und erwarteten Tool-Aufrufe entschieden, die
Kriterien des Judges werden als übersprungen erfasst, und die Schätzung
enthält keinen Judge.

Ein Agent ohne Historie auf einem Modell wird als typischer Fall geschätzt -
`EVAL_FALLBACK_INPUT_TOKENS` hinein, `EVAL_FALLBACK_OUTPUT_TOKENS` heraus - zum
eigenen Preis des Modells, oder mit `EVAL_FALLBACK_CASE_COST_USD` bei einem
Modell ohne bekannten Preis, und die Schätzung sagt, dass es eine grobe Annahme
ist (`basis: "fallback"`). Ein Judge ohne Historie wird genauso bepreist, auf
dem Modell, das sein veröffentlichter Spec nennt; die Schätzung warnt, wenn das
das getestete Modell ist, und die Seite eines Runs, wenn es das war. Die Kosten
der Baseline gehören zur Summe, außer eine aktuelle passende Baseline wird
wiederverwendet - dann kosten ihre ersten Antworten nichts, und die Schätzung
nennt den Run, aus dem sie stammen.

### Das verbleibende Budget { #the-budget-it-leaves }

Ein Eval zahlt aus denselben Monatsbudgets wie der Live-Verkehr: dem Limit des
Agents und dem der Organisation. Ein eigenes Eval-Budget gibt es nicht. Ein
großes Dataset kann die Produktion daher für den Rest des Monats ohne Budget
lassen, deshalb zeigt die Schätzung, was jedes Limit behält, nachdem der Run
seine Summe ausgegeben hat: `agent_after_usd` und `org_after_usd`.

Der Start wird mit `402` abgelehnt, bevor etwas geschrieben wird, wenn die Summe
höher ist als das, was einem der beiden Limits bleibt. Bestätigungsläufe (unten)
zählen bei dieser Prüfung nicht, weil sie nur Fälle betreffen, die kippen; die
Schätzung zeigt, wie viel sie höchstens hinzufügen können - jeder Fall kippt
und wird auf jeder Seite wiederholt, eine wiederverwendete Baseline
eingeschlossen - als `rerun_ceiling_usd`, den der Run behält, damit ein Run, der mehr als seine
Schätzung ausgegeben hat, sagt, warum. Jeder Fall wird trotzdem vor jeder
Modellanfrage gegen beide Limits geprüft, wie jeder Run, und ein Fall, der an
ein Limit stößt, stoppt den ganzen Eval-Run als `budget_exceeded`.

### Was abgelehnt wird { #what-is-refused }

Ein Run, der niemandem etwas sagen könnte, wird abgelehnt, bevor er geschätzt
wird:

- eine Dataset-Version ohne Fälle;
- ein Scoring ohne erforderlichen Bewerter, der irgendeinen Fall der Version
  entscheiden könnte - kein anwendbarer Check, kein erwarteter Tool-Aufruf und
  kein Judge. Ist der Judge der einzige Bewerter und AI assistance
  ausgeschaltet, sagt die Ablehnung das: Der Judge braucht AI assistance, das
  für diese Organisation ausgeschaltet ist, also schalte es in den Einstellungen
  der Organisation ein oder füge einen Check hinzu;
- ein Agent, der nie veröffentlicht wurde, für den eine Version verlangt wird -
  starte stattdessen seinen Draft;
- eine Baseline für eine erste Version, vor der es nichts gibt.

### Vorschläge prüfen { #checking-suggestions }

Der [Authoring-Assistent](authoring.md#check-with-evals) startet Eval Runs, um zu
prüfen, was er vorschlägt: den Draft mit den wartenden Vorschlägen, neben der
veröffentlichten Version. Ein solcher Run lässt die Fälle aus den Gesprächen weg,
aus denen die Vorschläge stammen, und nennt ihre Zahl, sodass eine kleinere
Stichprobe als das Dataset sich selbst erklärt.

## Als was jeder Fall läuft { #what-each-case-runs-as }

Jeder Fall ist ein gewöhnlicher Run des Agents mit der Oberfläche `eval`. Er
wird vor jeder Modellanfrage gegen die Budgets geprüft, und seine Kosten
werden erfasst. Er bleibt aus den Nutzungszahlen des Dashboards heraus, die nur
die Produktion zählen und die Kosten des Eval-Verkehrs daneben melden
(`cost.eval_usd`), und die Run-Historie lässt ihn weg, wenn danach gefragt wird
(`?exclude_surface=eval`). Das Lesen des einzelnen Runs nennt den Eval-Run und
den Fall, den er beantwortet hat (`eval_case`), für eine lesende Person, die
das Dataset sehen darf. Er läuft als die Person, die den Eval gestartet hat,
mit ihrer aktuellen Rolle, und liest oder schreibt nicht ihr persönliches
Gedächtnis.

Jeder Fall läuft **isoliert**, wie [Umgebungen](environments.md) beschreibt:
Ein Tool mit einer Testverbindung in der Umgebung des Runs läuft gegen diese,
ein Tool, von dem bekannt ist, dass es nur liest, läuft auf der normalen
Verbindung, und alles, was ohne Testverbindung schreibt, wird nicht ausgeführt
- der Aufruf und seine Argumente werden als beabsichtigter Aufruf behalten, den
das Trajektorie-Scoring trotzdem bewertet.

Ein Fall aus einer Conversation kann **aus der Aufzeichnung** des Runs
beantwortet werden, aus dem er stammt (`from_recordings`): Ein Aufruf, der zur
Aufzeichnung passt, bekommt das aufgezeichnete Ergebnis, einer, der nicht
passt, wird zurückgehalten und als abweichend markiert. Ein Fall ohne
verwendbare Aufzeichnung läuft isoliert ohne sie.

### Ein Draft zählt nie als Version { #a-draft-is-never-counted-as-a-version }

Ein Draft läuft über denselben Weg, mit zwei Unterschieden. Er wird zuerst
gegen den eigenen Zugriff der startenden Person geprüft - alles, was eine
Veröffentlichung prüfen würde -, weil ein Draft beim Speichern nie validiert
wurde. Und seine Runs werden keiner Version zugeordnet: Sie erscheinen nicht in
der Nutzung einer Version, und die Zahlen einer Version enthalten nie Antworten
ihres Drafts.

Der Draft wird beim Start des Runs kopiert, sodass jeder Fall auf denselben
Inhalt antwortet, auch wenn jemand weiter bearbeitet.

## Ausführen und abbrechen { #running-and-cancelling }

Ein Run wird im Hintergrund ausgeführt, als eigener Job im Worker, und
übersteht daher einen Neustart der API. Fälle laufen zu wenigen gleichzeitig:
höchstens `EVAL_RUN_CONCURRENCY` pro Run und höchstens `EVAL_ORG_CONCURRENCY`
über alle Eval-Runs einer Organisation, sodass ein Dataset mit 500 Fällen nicht
jede Anfrage belegen kann, die ein Provider der Organisation erlaubt.

Abbrechen (`POST /api/v1/eval-runs/{id}/cancel`, durch die Person, die ihn
gestartet hat, oder jeden, der den Agent bearbeiten darf) stoppt, was noch nicht
begonnen hat: Bereits laufende Fälle laufen zu Ende und werden behalten, und
kein weiterer Fall startet. Wer den Job eines Runs unter **Admin** →
**Background jobs** abbricht, bevor ein Worker ihn übernommen hat, bricht den
Run ebenso ab, binnen Sekunden.

Ein Run, den sein Worker nicht beenden kann - etwa weil ihm mitten im Run die
Datenbank wegbricht -, endet sofort als `failed`, wie ein Agent-Run: Seine
laufenden Fälle schlagen fehl, die übrigen werden übersprungen, und seine Seite
sagt, dass er an einem Fehler angehalten hat und neu gestartet werden sollte. Er
wird nicht fortgesetzt. Ebenso sofort als `failed` endet ein Run, dessen Job die
Zeit ausgegangen ist oder dessen Worker währenddessen heruntergefahren wurde.

Ein Worker kann auch kommentarlos sterben. Der Worker eines laufenden Runs meldet
alle `EVAL_HEARTBEAT_SECONDS`, dass er lebt; ein Run, dessen Worker schweigt und
dessen Fälle sich `EVAL_ABANDONED_AFTER_MINUTES` lang nicht bewegt haben, wird
von einem Sweep, den der Worker jede Minute ausführt, als fehlgeschlagen beendet,
der auch seine Plätze freigibt. Ein Worker, dessen Heartbeats so lange
fehlschlagen - auf einem Host, der zu ausgelastet ist, um seine Datenbank zu
erreichen -, wird ebenso beendet, obwohl er noch arbeitet, und sein Run muss neu
gestartet werden.

Ein Run in der Warteschlange hat noch keinen Worker, der melden könnte, dass er
lebt. Er darf auf einen freien Worker oder hinter einer pausierten Job-Art warten,
solange sein Job in der Warteschlange steht; der Sweep beendet ihn erst als
fehlgeschlagen, wenn kein Job mehr übrig ist, der ihn ausführen würde. Ein Fall,
den ein toter Worker in einem bereits beendeten Run laufend zurückgelassen hat,
schlägt nach denselben `EVAL_ABANDONED_AFTER_MINUTES` fehl. Ein laufender Fall
zählt auf `EVAL_ORG_CONCURRENCY`, bis er endet, auch nachdem sein Run
abgebrochen wurde.

Solange ein Run wartet oder läuft, lassen sich die Umgebung, die er nennt, und
das Modellprofil, auf dem eine seiner Seiten läuft, nicht entfernen: Seine
übrigen Fälle würden sonst gegen die Verbindungen der Produktion antworten oder
auf einem anderen Modell als die Fälle davor.

## Ergebnisse { #results }

Jeder Versuch behält die Antwort, die gemachten Aufrufe - jeder markiert als
ausgeführt, blockiert, wiedergegeben oder abweichend -, das Urteil und die
Begründung jedes Bewerters, seine Kosten, seine Tokens und seine Latenz.
Antwort und Aufrufe werden in das Ergebnis kopiert, weil ein Run eines Falls
keine Conversation hat, in der er ein Transkript behalten könnte.

Jeder Arm des Runs wird auf zwei Achsen zusammengefasst, und pro Tag:

| Achse | Misst |
|---|---|
| Qualität | Bestehensquote unter den entschiedenen Fällen, jeder so gewertet, wie die meisten seiner Versuche ausgingen; daneben die Quote der ersten Antworten; wie viele nicht entschieden werden konnten |
| Effizienz | Kosten pro bestandenem Fall, Tokens pro Fall und Latenz bei p50 und p95 |

Ein Fall, dessen erforderlicher Bewerter nicht laufen konnte, ist
**unentschieden**, nie bestanden. Einer, bei dem der Judge gescheitert ist oder
den er übersprungen hat, ist **nicht bewertet**: Der Run listet diese
Bewertungen als `ungraded_score_ids`, und sie erneut zu bewerten
(`POST /api/v1/datasets/{id}/scores/rescore`) liest die im Versuch behaltene
Antwort, statt den Agent zu fragen. Das Urteil einer Person in der
[Review-Warteschlange](datasets.md#review) ersetzt für diesen Fall das Ergebnis
der Bewerter, und die Zahlen des Runs folgen ihm.

Ein abgeschlossener Run behält Urteil, Zählungen und Bestehensquoten seines
ersten Kandidaten als `outcome`, sodass eine Liste sie liest, ohne jeden Run
erneut zu vergleichen. Er wird erneut verglichen, wenn eine Person seitdem über
eine der Bewertungen entschieden hat, auf denen er beruht, oder eine davon
erneut bewertet wurde.

```text
GET /api/v1/agents/{agent_id}/eval-runs      an agent's runs, newest first; ?draft=current
GET /api/v1/datasets/{dataset_id}/eval-runs  a dataset's runs over the agents the reader may see
GET /api/v1/eval-runs/{id}                   one run, with each arm's summary and its outcome
GET /api/v1/eval-runs/{id}/cases             cases, what each expects, and every attempt;
                                             ?outcome=, ?tag=, ?arm_id=, ?case_id=
GET /api/v1/eval-runs/{id}/comparison        a candidate arm against its baseline
GET /api/v1/eval-runs/{id}/arms/{arm}/spec   the spec one side ran; needs agents:edit
```

`?draft=current` behält die Runs, die den Draft in seinem jetzigen Stand
getestet haben - denselben Spec, gleich in welcher Reihenfolge seine Schlüssel
gespeichert wurden -, und genau das liest der Veröffentlichungsdialog.

## Mit einer Baseline vergleichen { #comparing-with-a-baseline }

Ein Vergleich ordnet beide Seiten Fall für Fall über die stabile ID des Falls
zu und meldet jeden Fall als **Regression** (bestanden, jetzt nicht mehr),
**behoben** (nicht bestanden, jetzt bestanden), unverändert oder unvollständig.
Fälle, die nur eine Seite beantwortet hat, zählen als nicht verglichen.

**Die Standard-Baseline ist günstig**: der letzte abgeschlossene Run desselben
Datasets auf der Version vor dem Kandidaten - bei einem Draft die
veröffentlichte Version. Beide Seiten sind mit Datum, Modell und
Dataset-Version beschriftet, weil sie sich in jedem davon unterscheiden können.

Ein Run kann stattdessen einen **früheren Run** desselben Agents auf demselben
Dataset als Baseline nennen (`baseline_run_id`). Seine gekippten Fälle werden
dann gegen diesen Run wiederholt und bestätigt - so sieht eine
[Eval-Suite](#suites), die täglich dieselbe Version prüft, die Drift.

### Eine Baseline im selben Run { #a-baseline-in-the-same-run }

Wenn eine Entscheidung vom Ergebnis abhängt - ein Promotion-Gate, eine mit
Evals geprüfte vorgeschlagene Änderung, ein Modellvergleich -, läuft die
Baseline **im selben Run** (`paired_baseline`, und immer bei
`purpose: "gate"`). Provider verändern sich von Tag zu Tag, und eine Regression,
gemessen an den Antworten der letzten Woche, kann am Provider liegen, nicht am
Agent.

Ein abgeschlossener Baseline-Arm ersetzt einen neuen Lauf nur, wenn Version,
Dataset-Version, Modell, Scoring und Judge übereinstimmen, er in derselben
Umgebung mit denselben `from_recordings` und `live_reads` lief und er
innerhalb von `EVAL_BASELINE_CACHE_HOURS` fertig wurde. Der Run nennt den Run, den er
wiederverwendet hat. Nur seine ersten Antworten werden wiederverwendet: Ein Fall,
der kippt, wird ihm in diesem Run erneut gestellt.

### Ein Kippen wird bestätigt, bevor es zählt { #a-flip-is-confirmed-before-it-counts }

Ein gekippter Fall wird `EVAL_RERUNS` Mal (standardmäßig 2) wiederholt, sobald
die ersten Antworten vorliegen. Eine Regression ist **bestätigt**, wenn jede
Wiederholung des Kandidaten wieder nicht besteht und - bei einer Baseline im
selben Run - jede Wiederholung der Baseline wieder besteht; sonst wird sie als
**unbestätigt** gemeldet. Eine Behebung wird genauso bestätigt. Eine Baseline
im selben Run - eine, die hier geantwortet hat, oder eine, deren erste Antworten
wiederverwendet wurden - wird neben dem Kandidaten wiederholt, sodass beide
Seiten ein Kippen am selben Tag bestätigen. Eine Baseline aus einem früheren
Run, mit der verglichen wird, wenn nichts neben dem Kandidaten lief, lässt sich
nicht wiederholen, daher bestätigt ihr gegenüber nur die Seite des Kandidaten.

Wiederholungen heben die Latte, statt sie zu senken: Ein Kippen gilt nur als
bestätigt, wenn es bei jeder Wiederholung hält, daher bestätigen mehr
Wiederholungen weniger Kippen. Ein kleines oder günstiges Modell, das einen Fall
von Versuch zu Versuch anders beantwortet, lässt seine Kippen unbestätigt, und
das Urteil lautet `no_difference`, auch wenn sich die Bestehensquote bewegt
hat - das heißt, das Modell ist bei diesen Fällen unbeständig, nicht dass sich
nichts geändert hat. Helfen mehr Fälle im Dataset, ein beständigeres Modell oder
eine niedrigere `temperature` in seinen [Model
Settings](models.md#model-settings) und das Durchsehen der unbestätigten Fälle
in der Tabelle.

Die Seite des Runs sagt es, wenn nichts hielt, aber drei oder mehr Fälle sich
einmal änderten oder die beiden Bestehensquoten 20 Punkte oder mehr
auseinanderliegen.

### Was das Urteil sagt { #what-the-verdict-says }

Das Urteil beruht nur auf den bestätigten Kippfällen. Eine bestätigte
Regression macht den Kandidaten `worse` - ein Fall, den er jedes Mal kaputt
macht, ist Grund genug, nicht zu veröffentlichen -, nur bestätigte Behebungen
machen ihn `better`, beides macht ihn `mixed`, und gar kein bestätigter
Kippfall ist `no_difference`. Jeder Kippfall nennt die Frage des Falls.

Unabhängig davon ergibt ein exakter McNemar-Test über die bestätigten
Kippfälle `overall`: `worse` oder `better`, wenn er die beiden Seiten bei
`EVAL_SIGNIFICANCE` unterscheidet, und null, wenn es zu wenige Kippfälle gibt,
wie bei den meisten kleinen Datasets.

Die Bestehensquote zählt jeden Fall nach der Mehrheit seiner entschiedenen
Versuche - nur nach seiner ersten Antwort, wenn er nicht wiederholt wurde, und
das Urteil einer Person über diese Antwort geht beidem vor -, sodass sie mit
den bestätigten Kippfällen übereinstimmt. Die eigene Quote der ersten
Antworten wird daneben als `first_pass_rate` behalten.

### Ein anderer Judge macht den Vergleich ungültig { #a-different-judge-invalidates-the-comparison }

Jede Bewertung hält den [Judge fest, der sie vergeben hat](datasets.md#judge):
sein Modell, seine Version, einen Fingerabdruck der Rubrik und die Version des
eigenen Prompts des Judges. Wurden die beiden Seiten mit unterschiedlichen
Scoring-Einstellungen bewertet oder von einem anderen Judge, Modell, einer
anderen Rubrik oder einem anderen Prompt, ist der Vergleich `invalid` und gibt
kein Urteil - ein Kippen sagt dann etwas über die Bewertung, nicht über den
Agent. Eine Baseline, die unter einem früheren Judge-Prompt bewertet wurde, sagt
das und wird nicht als zwischengespeicherte Baseline wiederverwendet.

Ein Run, dessen Judge sich änderte, während seine Fälle bewertet wurden, ist
ebenfalls `invalid`: Ein Fall, dessen Versuche Bewertungen zweier Judges tragen,
entscheidet sich nach dem, der mehr davon bewertet hat.

### Zwei Achsen, Qualität zuerst { #two-axes-quality-first }

Das Urteil betrifft die Qualität. Effizienz wird daneben gemeldet und nie
hineingerechnet: Kosten pro bestandenem Fall, Tokens und Latenz sind jeweils
`better`, `worse` oder `unchanged`, wobei eine Änderung innerhalb von
`EVAL_EFFICIENCY_TOLERANCE` als unverändert gilt.

## Modelle vergleichen { #comparing-models }

Mehrere `model_profile_ids` lassen den Kandidaten im selben Run einmal pro
Modell laufen, jedes als eigener Arm. Jeder Arm meldet seine Bestehensquote,
Kosten und Latenz nebeneinander. Mit einer Baseline im selben Run läuft die
Baseline auf dem zuerst genannten Modell, und jeder Arm wird mit ihr
verglichen.

## Suites { #suites }

Eine **Suite** ist ein Eval-Run, an dessen Start niemand denken muss. Sie nennt
den Agent, das Dataset, die Umgebung, deren Version sie prüft, und eine
Schwelle, die jedes Ergebnis erfüllen muss, und läuft dann selbstständig. Die
Karte **Suites** steht im Evals-Tab eines Agents unter den Runs: das Dataset
jeder Suite, wann sie läuft, ihre Schwelle und wie sie zuletzt abschnitt.
Geöffnet listet eine Suite jedes Ergebnis, warum es nicht bestand, die
gebrochenen Fälle und einen Link zum Eval-Run dahinter; die Seite dieses Runs
nennt die Suite, die ihn gestartet hat.

### Wann eine Suite läuft { #when-a-suite-runs }

Jede Kombination aus:

- **Nach Zeitplan** - ein Cron-Ausdruck, gelesen auf der Uhr einer Zeitzone,
  sodass `0 6 * * *` in `Europe/Berlin` vor und nach der Zeitumstellung sechs
  Uhr in Berlin ist. Sie prüft die Version, die ihre Umgebung ausliefert - die
  täglich geprüfte Produktionsversion bemerkt, wenn sich das Modell beim
  Provider oder eine Wissensbasis darunter ändert. Ein Lauf, der verpasst
  wurde, während der Worker stand, läuft einmal.
- **Bei Veröffentlichung** - jede neue Version, mit der Version davor im selben
  Eval-Run daneben.
- **Bei Promotion** - eine Version, die auf die Umgebung der Suite promotet
  wird (die Standardumgebung, wenn sie keine nennt), gemessen an der Version,
  die sie ersetzt.
- **Wenn sich eine Abhängigkeit ändert** - ein Skill, den die geprüfte Version
  bindet, wird bearbeitet, oder ein Dokument in einer Wissensbasis, die sie
  durchsucht, wird hinzugefügt, neu eingelesen oder gelöscht. Spezialisten, die
  die Version definiert, zählen als die Version. Eine Reihe von Änderungen ist
  ein Lauf, fällig `EVAL_SUITE_DEPENDENCY_DEBOUNCE_SECONDS` nach der ersten. Ein
  Modellprofil lässt sich nicht an Ort und Stelle ändern - einen Agent auf ein
  anderes zu richten ist eine Veröffentlichung -, und ein Provider, der das
  Modell dahinter austauscht, ist das, was der Zeitplan bemerkt.
- **Jetzt ausführen** - von Hand, als die Person, die es drückt.

Eine Suite, die darauf wartet, eine Version zu prüfen, nimmt den nächsten
Trigger für dieselbe Version auf, sodass eine Veröffentlichung und die
Promotion dieser Version danach ein Lauf sind. Eine Suite führt einen Eval-Run
zur Zeit aus; eine Änderung, die währenddessen kommt, wartet auf den nächsten.
Eine pausierte Suite läuft nicht, weder durch einen Trigger noch von Hand.

Eine Suite, die **eine Umgebung bewacht**, läuft auch vor einer Promotion
darauf - auf der Version, die promotet werden soll, neben der, die die Umgebung
ausliefert -, und die Promotion wartet, bis sie besteht; siehe
[Eine Promotion mit Evals bewachen](environments.md#guarding-a-promotion-with-evals).
Ihre Ergebnisse heißen *Vor der Promotion* (`gate`). Eine Suite, die eine
Umgebung bewacht, lässt sich erst löschen, wenn sie dort abgenommen ist.

### Was ein Ergebnis erfüllen muss { #what-a-result-must-meet }

Ein Ergebnis **besteht nicht**, wenn mehr Fälle reproduzierbar gegenüber der
Baseline brechen, als die Suite erlaubt - standardmäßig keiner, also lässt eine
bestätigte Regression es durchfallen -, oder wenn die Bestehensquote, jeder
Fall nach der Mehrheit seiner Versuche, unter das Minimum der Suite fällt. Die
Richtung aus dem McNemar-Test steht neben dem Ergebnis und entscheidet es nie.
Zwei optionale Grenzen prüfen die Effizienz: den Anstieg der Kosten pro
bestandenem Fall und der p95-Latenz gegenüber der Baseline; leer prüfen sie
nichts.

Ein Ergebnis, dessen Vergleich
[ungültig](#a-different-judge-invalidates-the-comparison) ist oder in dem auch
nur ein Fall nicht bewertet werden konnte, ist **ohne Ergebnis** - nie
bestanden -, es sei denn, etwas ist klar durchgefallen, und es nennt die Fälle,
die niemand bewertet hat. Den Judge neu zu veröffentlichen ändert, wie Antworten
bewertet werden, daher ist das nächste Ergebnis jeder Suite, die er bewertet,
einmal ohne Ergebnis, und ihr Eigentümer wird benachrichtigt. Eine
Bestehensquote unter dem Minimum lässt ein Ergebnis unabhängig vom Vergleich
durchfallen: Das Minimum braucht keine Baseline. Ein Ergebnis, dessen Eval-Run
abgebrochen wurde, ist ebenfalls ohne Ergebnis und sagt das; eines, dessen Run
fehlgeschlagen ist, ist ein Fehler.

Ein Ergebnis **ist nicht gelaufen**, wenn es mehr
kosten würde, als ein Budget oder die eigene Grenze der Suite hergibt, wenn nur
der Judge es bewerten könnte und die KI-Unterstützung aus ist, oder wenn es
keine veröffentlichte Version zum Prüfen gibt.

Geplante Läufe und Läufe nach
einer Abhängigkeit werden mit dem letzten bestandenen Lauf der Suite auf
derselben Version verglichen - dem letzten als gut bekannten Stand, sodass ein
gebrochener Fall gebrochen bleibt, bis ihn jemand behebt - und messen so die
Drift; eine Veröffentlichung oder Promotion lässt ihre Baseline im selben Run
laufen. Nach einem Ergebnis, das sich mit diesem Lauf nicht vergleichen ließ,
hat der nächste keine Baseline: Er wird an seinen eigenen Zahlen gemessen und
ist, wenn er besteht, der Lauf, mit dem die folgenden verglichen werden.

Eine [Prüfung der Vorschläge des Authoring-Assistenten](authoring.md#check-with-evals)
auf einer Suite wird am selben Schwellenwert gemessen, ist aber kein Ergebnis der
Suite: Sie steht in keinem ihrer Verläufe und benachrichtigt niemanden.

### Als wer sie läuft, und wer benachrichtigt wird { #who-it-runs-as-and-who-is-told }

Eine Suite läuft als die Person, die sie zuletzt gespeichert hat - ihr
**Eigentümer** -, mit deren Berechtigungen zum Start des Runs. Niemand sieht
einem geplanten Lauf beim Start zu, also stimmt, wer eine Suite speichert,
ihren Kosten zu, und das Formular nennt vorher den Preis eines Laufs und eines
Monats des Zeitplans. Wer die Suite sonst ändert, übernimmt sie. Eine Suite,
deren Eigentümer die Organisation verlässt oder sie nicht mehr ausführen kann,
pausiert mit dem Grund - ebenso eine, deren Umgebung entfernt wird, ob schon
pausiert oder nicht, statt still eine andere Version zu prüfen. Sie lässt sich
erst fortsetzen, wenn jemand wieder eine Umgebung für sie wählt.

Der Eigentümer wird benachrichtigt, wenn ein Ergebnis nicht besteht, ohne
Ergebnis bleibt oder nicht läuft - einmal pro Serie solcher Ergebnisse auf einer
Version, mit den gebrochenen oder unbewerteten Fällen -, im Benachrichtigungscenter und per E-Mail, wenn er sie
eingeschaltet hat. Slack ist noch kein Benachrichtigungskanal.

## Einstellungen { #settings }

| Einstellung | Standard | Was sie entscheidet |
|---|---|---|
| `EVAL_RUN_CONCURRENCY` | `3` | Fälle, die ein Run gleichzeitig ausführt |
| `EVAL_ORG_CONCURRENCY` | `6` | Fälle, die eine Organisation gleichzeitig ausführt, über ihre Runs hinweg |
| `EVAL_RERUNS` | `2` | Wiederholungen eines gekippten Falls; ein Run kann 0 bis 5 verlangen |
| `EVAL_BASELINE_CACHE_HOURS` | `24` | Wie alt eine passende Baseline sein darf, um wiederverwendet zu werden |
| `EVAL_SIGNIFICANCE` | `0.05` | Das Niveau, unter dem bestätigte Kippfälle ein Urteil sind |
| `EVAL_EFFICIENCY_TOLERANCE` | `0.05` | Eine relative Änderung von Kosten, Tokens oder Latenz, die als keine zählt |
| `EVAL_FALLBACK_INPUT_TOKENS` | `2000` | Die Input-Tokens, mit denen ein Fall auf einem Modell ohne Historie bepreist wird |
| `EVAL_FALLBACK_OUTPUT_TOKENS` | `400` | Die Output-Tokens, mit denen ein Fall auf einem Modell ohne Historie bepreist wird |
| `EVAL_FALLBACK_CASE_COST_USD` | `0.05` | Die Schätzung pro Fall auf einem Modell ohne Historie und ohne bekannten Preis |
| `EVAL_ESTIMATE_SAMPLE` | `50` | Wie viele letzte Runs die Schätzung mittelt |
| `EVAL_ABANDONED_AFTER_MINUTES` | `10` | Wie lange ein laufender Run bei schweigendem Worker stillstehen darf, bevor der Sweep ihn beendet |
| `EVAL_HEARTBEAT_SECONDS` | `60` | Wie oft ein arbeitender Run meldet, dass er lebt |
| `EVAL_SUITE_DEPENDENCY_DEBOUNCE_SECONDS` | `600` | Wie lange eine Suite nach einer Änderung an einem Skill oder einer Wissensbasis wartet, damit eine Reihe von Änderungen ein Lauf ist |

## Zugriff { #access }

Einen Run zu starten erfordert `datasets:run` auf dem Dataset und `agents:run`
auf dem Agent, jeweils mit den Grants der Ressource aufgelöst. Den Draft
laufen zu lassen erfordert außerdem `agents:edit` auf dem Agent, weil der Draft
die laufende Arbeit der Bearbeiter ist. Der Judge braucht, wenn er das Dataset
bewertet, was das [Scoring](datasets.md#scoring) sagt.

Einen Run zu lesen erfordert `runs:view` und dass die lesende Person sowohl den
Agent als auch das Dataset sehen kann - ein Run über ein Dataset, das sie nicht
öffnen kann, wird nicht aufgelistet, und eine Anfrage danach per ID antwortet
`404`, wie bei einem Run einer anderen Organisation. Die Runs eines Datasets
erfordern außerdem `datasets:view` darauf und listen nur die Agents, die die
lesende Person sehen darf.

Eine Suite anzulegen, zu ändern, zu pausieren oder auszuführen erfordert
`agents:edit` und `agents:run` auf dem Agent, `datasets:run` auf dem Dataset und
`runs:view`,
und eine Person, die als sie selbst angemeldet ist: Eine Suite gibt als die
Person aus, die sie speichert, also kann das weder ein API-Schlüssel noch ein
Administrator, der für jemanden handelt. Die Suites eines Agents zu lesen
erfordert `runs:view` und den Agent; die Fragen der Fälle, die ein Ergebnis
nennt, sieht nur, wer das Dataset öffnen darf.

## Was ein Run behält { #what-a-run-keeps }

Ein Ergebnis enthält die Antwort des Agents und die Argumente jedes Aufrufs,
den er gemacht hat, und kann daher personenbezogene Daten aus dem beantworteten
Fall und aus der Aufzeichnung enthalten, aus der geantwortet wurde. Es wird mit
seinem Run gelöscht, und ein Run mit seinem Agent oder seinem Dataset; das
Löschen der Conversation, aus der ein Fall stammt, löscht keine bereits daraus
erzeugten Ergebnisse. [Datenschutz](data-protection.md) führt es mit den
anderen Speichern auf.
