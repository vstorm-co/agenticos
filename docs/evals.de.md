---
source_sha: "a76406ae9df0"
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

Der Tab **Evals** eines Agents listet seine Runs, die neuesten zuerst, mit der
Bestehensquote jedes Kandidaten, den Kosten und dem Status. **Run evals** öffnet
den Startdialog: Wähle das Dataset, was läuft, die Umgebung, die Modelle und ob
die vorherige Version daneben läuft, dann **Estimate cost**. Der Run startet erst
über den Button, der den geschätzten Betrag nennt, unter der Zeile, die sagt,
was die Budgets des Agents und der Organisation danach behalten.

Die Seite eines Runs zeigt seinen Fortschritt, solange er antwortet, die
Ergebnisse jedes Arms nebeneinander, den Vergleich mit der Baseline und die
Fälle - gefiltert nach Ergebnis oder Tag, jeder mit den Antworten, Aufrufen und
Bewerterbegründungen jedes Arms. Die Karte **Eval runs** im Dashboard listet die
neuesten Runs der Organisation, und ein in Activity als `eval` markierter Run
verlinkt zurück zum Evals-Tab seines Agents.

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
bewertet.

Ein Agent ohne Historie auf einem Modell wird mit
`EVAL_FALLBACK_CASE_COST_USD` pro Fall geschätzt, und die Schätzung sagt, dass
es eine Annahme ist (`basis: "fallback"`). Die Kosten der Baseline gehören zur
Summe, außer eine aktuelle passende Baseline wird wiederverwendet - dann kostet
sie nichts, und die Schätzung nennt den Run, den sie wiederverwendet.

### Das verbleibende Budget { #the-budget-it-leaves }

Ein Eval zahlt aus denselben Monatsbudgets wie der Live-Verkehr: dem Limit des
Agents und dem der Organisation. Ein eigenes Eval-Budget gibt es nicht. Ein
großes Dataset kann die Produktion daher für den Rest des Monats ohne Budget
lassen, deshalb zeigt die Schätzung, was jedes Limit behält, nachdem der Run
seine Summe ausgegeben hat: `agent_after_usd` und `org_after_usd`.

Der Start wird mit `402` abgelehnt, bevor etwas geschrieben wird, wenn die
Summe höher ist als das, was einem der beiden Limits bleibt. Bestätigungsläufe
(unten) zählen bei dieser Prüfung nicht, weil sie nur Fälle betreffen, die
kippen; die Schätzung zeigt, wie viel sie höchstens hinzufügen können, als
`rerun_ceiling_usd`. Jeder Fall wird trotzdem vor jeder Modellanfrage gegen
beide Limits geprüft, wie jeder Run, und ein Fall, der an ein Limit stößt,
stoppt den ganzen Eval-Run als `budget_exceeded`.

### Was abgelehnt wird { #what-is-refused }

Ein Run, der niemandem etwas sagen könnte, wird abgelehnt, bevor er geschätzt
wird:

- eine Dataset-Version ohne Fälle;
- ein Scoring ohne erforderlichen Bewerter, der irgendeinen Fall der Version
  entscheiden könnte - kein anwendbarer Check, kein erwarteter Tool-Aufruf und
  kein Judge. Ist der Judge der einzige Bewerter und AI assistance
  ausgeschaltet, sagt die Ablehnung das: Der Judge kann nicht laufen, also füge
  einen Check hinzu oder schalte AI assistance ein;
- ein Agent, der nie veröffentlicht wurde, für den eine Version verlangt wird -
  starte stattdessen seinen Draft;
- eine Baseline für eine erste Version, vor der es nichts gibt.

## Als was jeder Fall läuft { #what-each-case-runs-as }

Jeder Fall ist ein gewöhnlicher Run des Agents mit der Oberfläche `eval`. Er
wird vor jeder Modellanfrage gegen die Budgets geprüft, seine Kosten werden
erfasst, und er erscheint in Activity, wo der Oberflächenfilter ihn vom
Produktionsverkehr trennt. Er läuft als die Person, die den Eval gestartet hat,
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

Ein Run wird im Hintergrund ausgeführt, in einem eigenen Worker-Flow, und
übersteht daher einen Neustart der API. Fälle laufen zu wenigen gleichzeitig:
höchstens `EVAL_RUN_CONCURRENCY` pro Run und höchstens `EVAL_ORG_CONCURRENCY`
über alle Eval-Runs einer Organisation, sodass ein Dataset mit 500 Fällen nicht
jede Anfrage belegen kann, die ein Provider der Organisation erlaubt.

Abbrechen (`POST /api/v1/eval-runs/{id}/cancel`, durch die Person, die ihn
gestartet hat, oder jeden, der den Agent bearbeiten darf) stoppt, was noch
nicht begonnen hat: Bereits laufende Fälle laufen zu Ende und werden behalten,
und kein weiterer Fall startet. Ein Run, dessen Worker sich
`EVAL_ABANDONED_AFTER_MINUTES` lang nicht bewegt, wird vom stündlichen Sweep
für hängende Runs als fehlgeschlagen beendet, der auch seine Plätze freigibt.

## Ergebnisse { #results }

Jeder Versuch behält die Antwort, die gemachten Aufrufe - jeder markiert als
ausgeführt, blockiert, wiedergegeben oder abweichend -, das Urteil und die
Begründung jedes Bewerters, seine Kosten, seine Tokens und seine Latenz.
Antwort und Aufrufe werden in das Ergebnis kopiert, weil ein Run eines Falls
keine Conversation hat, in der er ein Transkript behalten könnte.

Jeder Arm des Runs wird auf zwei Achsen zusammengefasst, und pro Tag:

| Achse | Misst |
|---|---|
| Qualität | Bestehensquote unter den entschiedenen Fällen und wie viele nicht entschieden werden konnten |
| Effizienz | Kosten pro bestandenem Fall, Tokens pro Fall und Latenz bei p50 und p95 |

Ein Fall, dessen erforderlicher Bewerter nicht laufen konnte, ist
**unentschieden**, nie bestanden. Das Urteil einer Person in der
[Review-Warteschlange](datasets.md#review) ersetzt für diesen Fall das Ergebnis
der Bewerter, und die Zahlen des Runs folgen ihm.

```text
GET /api/v1/agents/{agent_id}/eval-runs      an agent's runs, newest first
GET /api/v1/eval-runs/{id}                   one run, with each arm's summary
GET /api/v1/eval-runs/{id}/cases             cases and every attempt; ?outcome=, ?tag=, ?arm_id=
GET /api/v1/eval-runs/{id}/comparison        a candidate arm against its baseline
```

## Mit einer Baseline vergleichen { #comparing-with-a-baseline }

Ein Vergleich ordnet beide Seiten Fall für Fall über die stabile ID des Falls
zu und meldet jeden Fall als **Regression** (bestanden, jetzt nicht mehr),
**behoben** (nicht bestanden, jetzt bestanden), unverändert oder unvollständig.
Fälle, die nur eine Seite beantwortet hat, zählen als nicht verglichen.

**Die Standard-Baseline ist günstig**: der letzte abgeschlossene Run desselben
Datasets auf der Version vor dem Kandidaten - bei einem Draft die
veröffentlichte Version. Beide Seiten sind mit Datum, Modell und
Dataset-Version beschriftet, weil sie sich in jedem davon unterscheiden können.

### Eine Baseline im selben Run { #a-baseline-in-the-same-run }

Wenn eine Entscheidung vom Ergebnis abhängt - ein Promotion-Gate, eine mit
Evals geprüfte vorgeschlagene Änderung, ein Modellvergleich -, läuft die
Baseline **im selben Run** (`paired_baseline`, und immer bei
`purpose: "gate"`). Provider verändern sich von Tag zu Tag, und eine Regression,
gemessen an den Antworten der letzten Woche, kann am Provider liegen, nicht am
Agent.

Ein abgeschlossener Baseline-Arm ersetzt einen neuen Lauf nur, wenn Version,
Dataset-Version, Modell, Scoring und Judge übereinstimmen und er innerhalb von
`EVAL_BASELINE_CACHE_HOURS` fertig wurde. Der Run nennt den Run, den er
wiederverwendet hat.

### Ein Kippen wird bestätigt, bevor es zählt { #a-flip-is-confirmed-before-it-counts }

Ein gekippter Fall wird `EVAL_RERUNS` Mal (standardmäßig 2) wiederholt, sobald
die ersten Antworten vorliegen. Eine Regression ist **bestätigt**, wenn jede
Wiederholung des Kandidaten wieder nicht besteht und - bei einer Baseline im
selben Run - jede Wiederholung der Baseline wieder besteht; sonst wird sie als
**unbestätigt** gemeldet. Eine Behebung wird genauso bestätigt. Eine
vergangene Baseline lässt sich nicht wiederholen, daher bestätigt ihr gegenüber
nur die Seite des Kandidaten.

### Zu wenige Kippfälle sind kein Urteil { #too-few-flips-are-not-a-verdict }

Das Urteil beruht nur auf den bestätigten Kippfällen, geprüft mit einem
exakten McNemar-Test. Kann der Test die beiden Seiten bei `EVAL_SIGNIFICANCE`
nicht unterscheiden, lautet das Urteil `inconclusive` - der Unterschied liegt
im Rauschen oder die Stichprobe ist zu klein - statt besser oder schlechter. Es
gibt keine Mindestzahl an Fällen; ein kleines Dataset meldet nur häufiger
`inconclusive`. Ohne jeden bestätigten Kippfall lautet das Urteil
`no_difference`.

### Ein anderer Judge macht den Vergleich ungültig { #a-different-judge-invalidates-the-comparison }

Jede Bewertung hält den [Judge fest, der sie vergeben hat](datasets.md#judge):
sein Modell, seine Version und einen Fingerabdruck der Rubrik. Wurden die
beiden Seiten mit unterschiedlichen Scoring-Einstellungen bewertet oder von
einem anderen Judge, Modell oder einer anderen Rubrik, ist der Vergleich
`invalid` und gibt kein Urteil - ein Kippen sagt dann etwas über die Bewertung,
nicht über den Agent.

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

## Einstellungen { #settings }

| Einstellung | Standard | Was sie entscheidet |
|---|---|---|
| `EVAL_RUN_CONCURRENCY` | `3` | Fälle, die ein Run gleichzeitig ausführt |
| `EVAL_ORG_CONCURRENCY` | `6` | Fälle, die eine Organisation gleichzeitig ausführt, über ihre Runs hinweg |
| `EVAL_RERUNS` | `2` | Wiederholungen eines gekippten Falls; ein Run kann 0 bis 5 verlangen |
| `EVAL_BASELINE_CACHE_HOURS` | `24` | Wie alt eine passende Baseline sein darf, um wiederverwendet zu werden |
| `EVAL_SIGNIFICANCE` | `0.05` | Das Niveau, unter dem bestätigte Kippfälle ein Urteil sind |
| `EVAL_EFFICIENCY_TOLERANCE` | `0.05` | Eine relative Änderung von Kosten, Tokens oder Latenz, die als keine zählt |
| `EVAL_FALLBACK_CASE_COST_USD` | `0.05` | Die Schätzung pro Fall auf einem Modell ohne Historie |
| `EVAL_ESTIMATE_SAMPLE` | `50` | Wie viele letzte Runs die Schätzung mittelt |
| `EVAL_ABANDONED_AFTER_MINUTES` | `30` | Wie lange ein Run stillstehen darf, bevor der Sweep ihn beendet |

## Zugriff { #access }

Einen Run zu starten erfordert `datasets:run` auf dem Dataset und `agents:run`
auf dem Agent, jeweils mit den Grants der Ressource aufgelöst. Den Draft
laufen zu lassen erfordert außerdem `agents:edit` auf dem Agent, weil der Draft
die laufende Arbeit der Bearbeiter ist. Der Judge braucht, wenn er das Dataset
bewertet, was das [Scoring](datasets.md#scoring) sagt.

Einen Run zu lesen erfordert `runs:view` und dass die lesende Person sowohl den
Agent als auch das Dataset sehen kann - ein Run über ein Dataset, das sie nicht
öffnen kann, wird nicht aufgelistet, und eine Anfrage danach per ID antwortet
`404`, wie bei einem Run einer anderen Organisation.

## Was ein Run behält { #what-a-run-keeps }

Ein Ergebnis enthält die Antwort des Agents und die Argumente jedes Aufrufs,
den er gemacht hat, und kann daher personenbezogene Daten aus dem beantworteten
Fall und aus der Aufzeichnung enthalten, aus der geantwortet wurde. Es wird mit
seinem Run gelöscht, und ein Run mit seinem Agent oder seinem Dataset; das
Löschen der Conversation, aus der ein Fall stammt, löscht keine bereits daraus
erzeugten Ergebnisse. [Datenschutz](data-protection.md) führt es mit den
anderen Speichern auf.
