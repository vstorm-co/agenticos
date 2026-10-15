---
source_sha: "93c168eefee1"
title: "Datasets"
description: "Datasets enthalten die Fragen, an denen ein Agent getestet wird: versionierte Fälle, von Hand geschrieben, aus CSV oder JSONL importiert oder aus einer bewerteten Antwort übernommen."
---

# Datasets { #datasets }

Ein **Dataset** enthält die Fragen, an denen ein Agent getestet wird. Ohne eines
besteht jede Prüfung, ob eine Änderung den Agent besser gemacht hat, darin,
dass jemand ein paar Prompts von Hand ausprobiert und sich zu erinnern versucht,
wie die letzte Antwort aussah.

Jede Frage ist ein **Fall**: die Nachricht, die der Agent beantwortet, und wie
eine gute Antwort aussieht. Fälle kommen aus drei Quellen - in der Konsole
geschrieben, aus einer Datei importiert oder aus einem echten Gespräch
übernommen, in dem jemand die Antwort negativ bewertet hat. Die letzte Quelle
ist meist die wertvollste, weil es eine Frage ist, die ein Mensch wirklich
gestellt hat, und eine Antwort, die ihn wirklich enttäuscht hat.

## Was ein Fall enthält { #what-a-case-holds }

| Feld | Was es ist |
|---|---|
| Eingabe | Die Nachricht, die der Agent beantwortet |
| Gespräch vor der Eingabe | Optionale frühere Züge, älteste zuerst. Mit ihnen ist der Fall ein Gesprächsanfang, und der Agent beantwortet dessen letzten Zug |
| Referenzantwort | Was eine gute Antwort sagt |
| Gegenbeispiel | Eine Antwort, die bekanntermaßen falsch ist |
| Erwartete Tool-Aufrufe | Die Tools, die der Agent aufrufen soll, jeweils mit den Argumenten, die passen müssen. Argumente, die ein Fall nicht nennt, werden ignoriert. Ein Fall legt auch fest, wie die Aufrufe abgeglichen werden: `any` in beliebiger Reihenfolge, `in_order` in der angegebenen Reihenfolge mit anderen Aufrufen dazwischen, oder `exact` - genau diese, in dieser Reihenfolge, und keine anderen |
| Prüfungen | Regeln für die Antwort, jede ein Objekt, dessen `type` die Regel benennt, mit deren Parametern daneben. [Bewertung](#checks) listet die Typen auf, und ein Fall mit einem Typ, den es nicht kennt, wird abgelehnt |
| Tags | Labels zum Gruppieren von Ergebnissen, etwa `billing` oder `refusal` |
| Notiz | Warum es den Fall gibt - was schiefging oder was er absichert |
| Quelle | `manual`, `import`, `conversation` oder `synthetic` - von der Plattform gesetzt, nicht eingegeben |

Ein Fall muss sagen, woran seine Antwort gemessen wird: eine Referenzantwort,
ein Gegenbeispiel, ein erwarteter Tool-Aufruf oder eine Prüfung - mindestens
eines davon. Ein Fall nur mit einer Eingabe könnte nie scheitern, deshalb wird er
abgelehnt: Das Formular speichert ihn nicht, die API antwortet mit 422 und nennt
`reference_answer`, und ein Import nennt die Zeile.

Ein guter Fall ist klein: eine Frage und das eine, was eine richtige Antwort
richtig machen muss. Meist genügt eine Referenzantwort oder ein Gegenbeispiel.
Fügen Sie erwartete Tool-Aufrufe hinzu, wenn der Agent handeln statt nur
antworten soll, Prüfungen, wenn sich eine Regel genau angeben lässt, und das
Gespräch vor der Eingabe nur, wenn die Frage davon abhängt. Die Notiz ist für
die nächste Person, die den Fall liest: was schiefging oder was er absichert.
Beim Anlegen Ihres ersten Datasets bietet die Konsole eine geführte Tour an, die
mit dem ersten Fall endet, Feld für Feld.

Ein Fall aus einem Gespräch behält außerdem einen Verweis auf den Run, das
Gespräch und die Nachricht, aus denen er stammt. Frage und Antwort werden in den
Fall kopiert, sodass der Fall vollständig bleibt, nachdem die Aufbewahrung den
Run selbst entfernt hat.

Anhänge sind in dieser Version kein Teil eines Falls. Ein Fall ist Text.

## Jede Änderung ist eine neue Version { #versions }

Einen Fall hinzufügen, bearbeiten oder entfernen und eine Datei importieren
erzeugt jeweils eine neue **Version** des Datasets, nummeriert ab 1. Eine
Version ändert sich nach ihrem Anlegen nie. Ein bearbeiteter Fall wird als neue
Revision gespeichert, und die Version vor der Bearbeitung enthält weiterhin die
alte.

Das zählt, wenn Sie Ergebnisse vergleichen. Zwei Eval-Runs über dieselbe
Version haben dieselben Fragen gesehen, also kommt ein Unterschied in ihren
Ergebnissen vom Agent und nicht vom Test. Die Dataset-Seite zeigt standardmäßig
die neueste Version; eine ältere wählen Sie in der Versionsliste. Eine ältere
Version ist schreibgeschützt.

Ein Dataset mit **Details bearbeiten** auf seiner Seite umzubenennen oder seine
Beschreibung zu ändern erzeugt keine Version, weil keines von beiden einen Fall
ändert.

Die Versionsliste zeigt die hundert neuesten Versionen; eine ältere öffnen Sie,
indem Sie ihre Nummer eingeben. Jede Version hält eine Zeile pro Fall, daher
halten die Versionen einer Organisation zusammen höchstens
`DATASET_MAX_VERSION_ROWS_PER_ORG` Zeilen (standardmäßig 5 Millionen, siehe
[Konfiguration](configuration.md#datasets)). Eine Änderung darüber wird
abgelehnt und nennt, wie viele belegt sind; das Löschen eines Datasets gibt
seine Zeilen frei.

## Fälle hinzufügen { #adding-cases }

### In der Konsole { #in-the-console }

Öffnen Sie **Datasets**, legen Sie ein Dataset an - es öffnet sich, sobald es
existiert - und wählen Sie **Fall hinzufügen**. Schreiben Sie die Eingabe und
mindestens eine der vier Erwartungen oben. Das Gespräch wird Zug für Zug
geschrieben, jeder erwartete Tool-Aufruf als Tool-Name mit seinen Argumenten als
Zeilen aus Name und Wert und jede Prüfung als Typ, aus der Liste gewählt, neben
dem, was sie prüft. **Als JSON bearbeiten** zeigt den ganzen Fall in der Form,
die ein Import enthält.

Ein Fall in der Liste öffnet sich so, wie er sich liest, mit dem Gespräch als
Chat-Blasen; **Bearbeiten** macht ihn zum Formular, das sagt, welche Version ein
Speichern erzeugt und welche Scorer des Datasets den Fall so, wie er geschrieben
ist, bewerten würden. Ein Link auf `?tab=cases&case={case_id}` auf der Seite des
Datasets öffnet einen einzelnen Fall.

Das Speichern eines neuen Falls, dessen Frage ein Fall bereits stellt - ohne
Rücksicht auf Groß- und Kleinschreibung oder Leerraum -, hält an und sagt das,
mit **Öffnen**, um stattdessen jenen Fall zu lesen, und **Trotzdem
hinzufügen**, um beide zu behalten. Geprüft wird mit `GET
/datasets/{id}/cases?same_input=`.

### Aus einer Datei { #import-and-export }

**Importieren** liest eine `.csv`- oder `.jsonl`-Datei und fügt alle Fälle darin
als eine neue Version hinzu. Der Import gilt ganz oder gar nicht: Ist eine Zeile
ungültig, wird keine hinzugefügt, und die Ablehnung nennt jede ungültige Zeile,
damit Sie die Datei korrigieren und es erneut versuchen können. Eine Datei ist
höchstens 10 MB groß, und ein Dataset enthält höchstens 10.000 Fälle.

Beide Formate verwenden dieselben neun Feldnamen:

| Spalte | In CSV | In JSONL |
|---|---|---|
| `input` | Text. Pflicht | String. Pflicht |
| `history` | Eine JSON-Liste in der Zelle oder leer | Eine Liste von `{"role", "content"}`-Objekten |
| `reference_answer`, `counter_example`, `note` | Text oder leer | String oder `null` |
| `expected_tool_calls` | Eine JSON-Liste in der Zelle oder leer | Eine Liste von `{"tool", "args"}`-Objekten |
| `order_mode` | `any`, `in_order` oder `exact`; leer bedeutet `any` | String |
| `checks` | Eine JSON-Liste in der Zelle oder leer | Eine Liste von Prüfungsobjekten |
| `tags` | Durch Kommas getrennt | Eine Liste von Strings |

Eine CSV-Datei braucht eine Kopfzeile. Andere Spalten als diese neun werden
abgelehnt, damit ein Tippfehler in einem Spaltennamen deren Daten nicht still
verliert. Weggelassene Spalten erhalten ihren leeren Wert. Innerhalb einer Prüfung und in den Argumenten eines Tool-Aufrufs werden die Schlüssel alphabetisch exportiert, nach dem `type` einer Prüfung.

```csv
input,reference_answer,tags
How long is the return window?,30 days from delivery,returns
Can I return a used kettle?,"No, only unused items",returns
```

**Exportieren** lädt die angezeigte Version als CSV oder JSONL herunter. Ein
Export lässt sich unverändert wieder importieren. Damit das auch in einer
Tabellenkalkulation gilt, wird eine CSV-Zelle, die mit `=`, `+`, `-`, `@` oder
`'` beginnt, mit einem vorangestellten `'` geschrieben, damit die Tabelle sie
nicht als Formel ausführt, und ein Import entfernt dieses eine `'` wieder. Der
Export wird im [Audit-Log](governance.md#audit) festgehalten.

### Aus einem Gespräch oder einem Run { #add-to-dataset }

Es gibt zwei Wege, und beide erzeugen denselben Fall:

- **Im Chat** bewerten Sie die Antwort, und die Bewertung entscheidet, als was
  sie behalten wird. Nach einem Daumen nach oben bietet die Bestätigung **Zum
  Dataset hinzufügen** an: Dataset wählen, und die Antwort wird als
  Referenzantwort behalten. Nach einem Daumen nach unten bietet der Dialog, der
  fragt, was schiefging, auch **Diese Antwort zu einem Dataset hinzufügen** an:
  Haken setzen, Dataset wählen und absenden, und die Antwort wird als
  Gegenbeispiel behalten. Zuerst wird die Bewertung gespeichert, danach der Fall
  angelegt, sodass Ihr Kommentar zur Notiz des Falls wird. Es sind zwei
  getrennte Schreibvorgänge - wird das Hinzufügen abgelehnt, bleibt die
  Bewertung, und die Meldung sagt, welcher Teil fehlschlug. Wird die Bewertung
  später entfernt, bleibt der Fall: Er ist eine Kopie, versioniert mit seinem
  Dataset. Die Konsole merkt sich das zuletzt verwendete Dataset, sodass das
  nächste Hinzufügen ein Klick ist.
- **In Aktivität** hat jeder Agent-Zug ein Bedienelement **Zum Dataset
  hinzufügen**. Hier werden Antworten kuratiert, daher lässt sich eine gute
  Antwort ebenso leicht als Referenz behalten wie eine schlechte als
  Gegenbeispiel.

In beiden Fällen entsteht der Fall aus diesem Zug:

- die Frage wird zur Eingabe, die Züge davor werden zum Gespräch vor der
  Eingabe;
- die Antwort wird zum Gegenbeispiel. Hat niemand sie negativ bewertet, wird
  sie stattdessen als Referenzantwort angeboten, und Sie wählen eines von
  beiden;
- der neueste Kommentar zu einem Daumen nach unten wird zur Notiz.

Beide Wege sehen nur Mitglieder, die ein Dataset bearbeiten dürfen. Die
Nachricht muss zu Ihrer Organisation gehören, und Sie müssen sie lesen dürfen:
Entweder Sie haben `runs:view`, womit Sie wie in Aktivität jeden Run der
Organisation lesen, oder Sie können das Gespräch öffnen. Eine Nachricht aus
einer anderen Organisation wird abgelehnt, als gäbe es sie nicht.

## Zugangsdaten werden geschwärzt { #credentials }

Der Text von Fällen wird aus Gesprächen und hochgeladenen Dateien kopiert und
später exportiert und an Modelle übergeben. Bevor ein Fall gespeichert wird,
ersetzt die Plattform jeden erkannten API-Schlüssel und jedes erkannte Token
durch einen Platzhalter wie `[redacted:github_token]`. Das gilt für jedes Feld,
das ein Modell liest oder ein Export enthält, auch für die Argumente eines
erwarteten Tool-Aufrufs, und für jeden Weg, auf dem ein Fall hinzukommt. Der
Audit-Eintrag der Änderung hält fest, wie viele Werte geschwärzt wurden, nie die
Werte selbst.

## Bewertung { #scoring }

Ein Dataset legt auf seinem Tab **Bewertung** fest, wie seine Fälle bewertet
werden, in drei Karten, die zusammen gespeichert werden: **Wann ein Fall
besteht** enthält die Prüfungen und die erwarteten Tool-Aufrufe, **Bewerter**
sagt, welcher Bewerter bewertet und worauf, und **Prüfung durch eine Person**
sagt, was auf die Entscheidung von jemandem wartet. Vier Scorer können auf
einen Fall angewendet werden, und jeder wird ein- oder ausgeschaltet und als
**Muss bestehen** markiert oder nicht:

| Scorer | Was er vergleicht | Kosten |
|---|---|---|
| Prüfungen | Die Antwort mit den Regeln des Falls und mit Standardregeln, die das Dataset jedem Fall mitgibt | Keine |
| Erwartete Tool-Aufrufe | Die Tools, die der Agent aufgerufen hat, mit den erwarteten Aufrufen des Falls | Keine |
| Bewerter | Die Antwort anhand einer Rubrik benannter Kriterien, bewertet vom Bewerter des Datasets | Ein Run des Bewerters |
| Referenzantwort | Die Antwort mit der Referenzantwort des Falls, bewertet vom Bewerter des Datasets | Derselbe Run des Bewerters |

Jeder Scorer liefert bestanden oder nicht bestanden, einen Score von 0 bis 1
und eine Begründung. Ein Fall **besteht**, wenn jeder mit „Muss bestehen“
markierte Scorer besteht, und **besteht nicht**, wenn einer von ihnen nicht
besteht. Kam einer von ihnen zu keinem Urteil - der Bewerter war ausgeschaltet,
sein Budget war aufgebraucht, sein Run schlug fehl oder seine Antwort ließ sich
nicht lesen -, ist der Fall **nicht bewertet**: weder bestanden noch nicht
bestanden, weil niemand die Antwort geprüft hat. Der Score sagt, warum, und
lässt sich [erneut bewerten](#judge), sobald die Ursache behoben ist.

Jeder Scorer sagt, wie viele Fälle enthalten, was er liest, und der Tab warnt,
wenn die angezeigte Konfiguration einige Fälle anhand von nichts bewerten
würde. Einem Dataset, dessen Fälle Referenzantworten haben, mit denen nichts
die Antworten vergleicht, wird der Vergleich mit der Referenzantwort angeboten.
Eine Karte mit einer noch nicht gespeicherten Änderung sagt das, eine Leiste
unten am Bildschirm speichert oder verwirft alle Änderungen auf einmal, und die
Seite fragt nach, bevor man sie verlässt.

Die Konfiguration wird nicht mit den Fällen versioniert, weil die Art, wie ein
Team bewertet, nicht das ist, was es fragt. Jeder Score bewahrt eine Kopie der
Konfiguration auf, mit der er berechnet wurde, sodass ein älterer Score auch
nach einer Änderung der Konfiguration noch sagt, wie er zustande kam.

Eine Konfiguration, die nichts bewerten könnte, wird abgelehnt: alle Scorer
ausgeschaltet oder der Judge eingeschaltet ohne ein Kriterium. Ebenso die
Bewertung eines Falls, an dem keiner der konfigurierten Scorer etwas zu prüfen
hat - nichts wird gespeichert, und der Judge wird nicht aufgerufen.

### Prüfungen { #checks }

| `type` | Parameter | Besteht, wenn |
|---|---|---|
| `contains`, `not_contains` | `value`, optional `path`, `case_sensitive` | Die Antwort den Wert enthält oder nicht enthält |
| `equals` | `value`, optional `path`, `case_sensitive` | Die Antwort ohne umgebende Leerzeichen der Wert ist |
| `regex` | `value` (höchstens 500 Zeichen), optional `path`, `case_sensitive` | Das Muster irgendwo in der Antwort passt |
| `json_schema` | `schema`, optional `path` | Die Antwort JSON ist, das dem JSON Schema entspricht |
| `max_cost_usd` | `value` | Der Run nicht mehr als das gekostet hat |
| `max_latency_ms` | `value` | Der Run nicht länger als das gedauert hat |
| `judge` | `criterion` | Der Eval-Judge das Kriterium mit der Bestehensgrenze oder höher bewertet |

`path` liest in eine Antwort hinein, die JSON ist: `items.0.name` ist der Name
des ersten Elements. Ohne ihn liest eine Regel die ganze Antwort. Textregeln
unterscheiden nicht zwischen Groß- und Kleinschreibung, außer `case_sensitive`
ist true.

Ein Muster wird geprüft, wenn der Fall geschrieben wird, und eine Regel liest
höchstens die ersten 100.000 Zeichen einer Antwort. Ein Muster, das auf einer
Antwort länger als eine Zehntelsekunde braucht, wird abgebrochen und als Fehler
festgehalten, damit ein einzelnes Muster das Scoring nicht aufhalten kann. Aus
demselben Grund darf ein JSON Schema weder `pattern` noch `patternProperties`
verwenden - eine `regex`-Prüfung mit `path` leistet dasselbe unter derselben
Frist -, und sein `$ref` muss innerhalb des Schemas zeigen.

Eine `judge`-Prüfung ist ein Kriterium nur für einen Fall, bewertet im selben
Judge-Run wie die Rubrik des Datasets. Verwenden Sie sie für das, was eine Regel
nicht ausdrücken kann, etwa „lehnt ab und verrät die Adresse des Kunden nicht“.

### Erwartete Tool-Aufrufe { #trajectory }

Die Aufrufe des Agents werden mit den erwarteten Aufrufen des Falls nach
Tool-Name und nach jedem Argument abgeglichen, das der Fall nennt. Der
Reihenfolgemodus des Falls entscheidet, was besteht: Mit `any` hat jeder
erwartete Aufruf stattgefunden; mit `in_order` fanden sie in der aufgeführten
Reihenfolge statt; mit `exact` sind sie die einzigen Aufrufe und in dieser
Reihenfolge. Die Begründung nennt, was fehlte, was nicht erwartet war oder dass
die Reihenfolge abwich. Ein Schreibvorgang, den ein isolierter Run blockiert
hat, zählt weiterhin als Aufruf, den der Agent gemacht hat.

Ein Aufruf wird über den Tool-Namen abgeglichen, den der Run aufgezeichnet hat,
also den Namen nach einer etwaigen Überschreibung im Spec. Ein Fall, der vor der
Umbenennung eines Tools geschrieben wurde, erwartet den alten Namen.

### Der Bewerter { #judge }

Ein Bewerter ist ein Agent der Art `judge` (siehe
[Bewerter](concepts.md#system-agents)). Ein Dataset bewertet mit dem **Eval
judge**, den die Plattform jeder Organisation hinzufügt, oder mit einem eigenen
Bewerter: **Bewerter für dieses Dataset anlegen** auf der Karte Bewerter legt
einen an, dessen Prompt der des Eval judge mit seinen Bewertungsregeln ist,
gefolgt von Namen und Beschreibung des Datasets und dem, was der Bewerter laut
Ihnen zum Bewerten wissen muss - einer Richtlinie, einer Preisliste -, auf dem
ersten Modell der Organisation oder einem, das Sie wählen. Der Prompt lässt
sich vor dem Anlegen bearbeiten (`GET /datasets/{id}/judge-template`). Dafür
braucht es `agents:edit` und `datasets:edit`.

Wo die KI-Unterstützung eingeschaltet ist, schaltet das Anlegen die Bewertung
gleich mit ein: den Bewerter, mit einem Startkriterium zum Ersetzen, wenn das
Dataset keines hat, und den Vergleich mit der Referenzantwort, wenn ein Fall
eine hat. Die Kriterien, die Skala und die Bestehensgrenze bleiben am Dataset;
Prompt, Modell und Budget des Bewerters werden auf seiner eigenen Seite
bearbeitet, dem einzigen Ort, an dem sein Modell festgelegt wird; die Karte
Bewerter zeigt es an.

Ein Bewerter läuft als die Person, die den Score angefordert hat: Ihr Zugriff
auf ihn wird geprüft, er wird vor dem Modellaufruf gegen sein eigenes Budget und
das der Organisation geprüft, und sein Run erscheint in Activity unter der
Oberfläche `eval`.

Der Bewerter erhält die Notiz des Falls als Grund, warum es den Fall gibt,
seine früheren Züge und die Frage, die Referenzantwort, wenn sie bewertet wird,
das Gegenbeispiel, jeden Tool-Aufruf des Agenten - mit seinen Argumenten und ob
ein isolierter Run ihn blockiert hat - und die Antwort. Ein Fall mit
Gegenbeispiel wird immer auch nach dem erforderlichen Kriterium
**counter-example** bewertet: Die Antwort darf die bekannte schlechte Antwort
nicht wiederholen. Bewerter starten mit Temperatur 0, damit dieselbe Antwort
zweimal gleich bewertet wird; bei einem Reasoning-Modell, das die Einstellung
ablehnt, muss sie auf der Seite des Bewerters entfernt werden.

Der Bewerter läuft nur, wo die [KI-Unterstützung](governance.md#ai-assistance)
eingeschaltet ist, und sie ist aus, bis ein Administrator sie für die
Organisation einschaltet. Bis dahin werden die Kriterien des Bewerters und der
Referenzantwort als übersprungen festgehalten, nur die regelbasierten Scorer
bewerten, und der Tab Bewertung sagt das, mit einem Link zum Schalter für den,
der ihn ändern darf. Der Bewerter und der Vergleich mit der Referenzantwort
lassen sich in dieser Zeit nicht einschalten; ein bereits eingeschalteter bleibt
an und wird übersprungen.

Jedes Kriterium wird von 1 bis zum oberen Ende der Skala bewertet und besteht
ab der Bestehensgrenze. Für jedes Kriterium zitiert der Bewerter die Stelle der
Antwort, auf der seine Bewertung beruht, und nennt die Regel, aus der sie
folgt. Eine Bewertung, deren Begründung überwiegend aus den Worten des
Kriteriums besteht, ohne ein Zitat, das die Antwort enthält, ist ein Fehler:
Nichts zeigt, dass der Bewerter die Antwort gelesen hat. Eine Höchstnote ohne
Zitat aus der Antwort bleibt bestehen und wird als nicht belegt markiert.

Kann der Bewerter nicht bewerten, werden seine Kriterien als übersprungen oder
als Fehler festgehalten, mit einer Begründung, die die Ursache nennt:
KI-Unterstützung ist ausgeschaltet, der vom Dataset gewählte Bewerter existiert
nicht mehr, er hat keine veröffentlichte Version, er ist archiviert, sein
Modell ist entfernt oder hat keinen Schlüssel, die Person darf ihn nicht
ausführen, sein Budget ist aufgebraucht, sein Run schlug fehl oder seine
Antwort ließ sich nicht lesen - deren erste 200 Zeichen bleiben dann neben der
Begründung. Die regelbasierten Scorer bewerten trotzdem.

Ist die Ursache behoben, bewertet **Erneut bewerten** an einem nicht bewerteten
Ergebnis - oder an allen in der Gruppe eines Eval-Runs auf dem Tab Prüfung -
dieselbe Antwort neu, mit der Konfiguration, mit der sie zuerst bewertet wurde
(`POST /datasets/{id}/scores/rescore`, bis zu zehn Scores pro Anfrage). Der
Agent läuft nicht erneut, und der Score behält seinen Eval-Run und jede
Entscheidung, die eine Person darüber getroffen hat; einer, bei dem jeder
Scorer zu einem Urteil kam, bleibt, wie er ist.

Eine Bewertung darf die Antwort zitieren, bis zu 12 Stellen; ein Zitat, das die
Antwort nicht wörtlich enthält, wird neben der Bewertung als nicht verifiziert
aufbewahrt und in einer eigenen Zeile unter der Begründung angezeigt, und die
Bewertung bleibt bestehen.

Jedes Ergebnis hält den Bewerter fest, der es bewertet hat - den Bewerter-Agent,
sein Modellprofil, die Version seines Specs, einen Hash der Rubrik und die
Version der Aufgabe, die die Plattform jedem Bewerter übergibt -, damit
Ergebnisse verschiedener Bewerter nicht als gleichwertig verglichen werden. Den
Bewerter oder sein Modell auf seiner Seite zu wechseln ist erlaubt; vor dem
Wechsel des Bewerters fragt die Konsole zuerst nach, und die Karte Bewerter
sagt, dass sich die vorher bewerteten Scores nicht mit den danach bewerteten
vergleichen lassen.

### Prüfung { #review }

Ein Score wartet in der **Warteschlange zur Prüfung**, wenn jemand ihn dorthin
schickt oder ein Eval-Run es tut. Hat er erneut ausgeführt, was gekippt ist,
schickt ein Eval-Run die Regressionen, die er bestätigt hat, und die Antworten,
die der Bewerter nicht bewerten konnte - ein Score pro Fall und keiner für einen
Fall, der bereits wartet. Seine Seite schickt weitere Scores, die Sie
auswählen, alle auf einmal über `POST /datasets/{id}/scores/review` mit bis zu
500 Score-IDs - alle oder keine.

Ein Score, der von Hand aus Activity angefordert wurde, folgt der Einstellung
**Prüfung durch eine Person** des Datasets: nichts, bis jemand einen schickt,
jedes Ergebnis, das nicht bestanden hat, oder jedes Ergebnis. Ein bereits
entschiedener Score bleibt entschieden.

Der Tab **Prüfung** öffnet sich mit dem, was auf eine Entscheidung wartet, jedes
Ergebnis einen Klick entfernt, jeweils mit seiner Anzahl, und lässt sich nach
Ausgang, nach dem Agent, der geantwortet hat, und nach einem Tag des Falls
eingrenzen. Er fasst die Scores jedes Eval-Runs unter einer Überschrift mit einem
Link zum Run zusammen, von der aus sie unentschieden aus der Warteschlange
genommen werden können (`POST /datasets/{id}/scores/review/withdraw`).

Jede Karte zeigt, was der Fall gefragt und erwartet hat - die Frage, mit einem
Link zum Fall, die Referenzantwort, die erwarteten Tool-Aufrufe und die
Prüfungen -, die bewertete Antwort, Agent und Version, die geantwortet haben -
mit einer Warnung, wenn der Bewerter auf dem Modell bewertet hat, das
geantwortet hat, da ein Bewerter Antworten wie seine eigenen bevorzugen kann -,
was jeder Scorer gefunden hat und warum, die nicht bestandenen zuerst, und die
Prüfentscheidung, die sich in der Meldung, die sie bestätigt, rückgängig machen
lässt.

Die Notiz zu einer Entscheidung ist oft die Regel, die der Bewerter übersehen
hat, daher bietet die Karte an, sie zu einem Kriterium des Bewerters zu machen:
nur für diesen Fall, als Prüfung `judge` in einer neuen Version des Datasets,
oder für jeden Fall, in der Rubrik, was den Bewerter einschaltet.

Die Dashboard-Karte **Wartet auf Prüfung** zeigt die Warteschlange über alle
Datasets, die Sie sehen können: wie viele Ergebnisse nicht bestanden haben, nicht
bewertet wurden oder bestanden haben, und in welchen Datasets, jedes öffnet sich
auf seinem Tab Prüfung. Die Karte ist standardmäßig auf dem Dashboard.

Die Prüfentscheidung einer Person wird neben den Ergebnissen der Scorer
gespeichert und entscheidet über das Ergebnis. Sie ändert nie, was der Bewerter
gesagt hat: Die Bewertungen und Begründungen des Bewerters bleiben am Score,
nachdem er überstimmt wurde. Eine Prüfentscheidung kann zurückgezogen werden,
und der Score wartet dann wieder auf eine Prüfung.

### Einen Run bewerten { #scoring-a-run }

Öffnen Sie in **Aktivität** einen Run, öffnen Sie sein Menü **⋯** und wählen Sie
**Gegen einen Fall bewerten**. Der Fall, der die Frage des Runs selbst stellt,
wird für Sie ausgewählt; hat das Dataset keinen, bietet der Dialog an, die
Antwort des Runs als Fall hinzuzufügen. Die Antwort und die Tool-Aufrufe des
Runs werden mit jedem Scorer bewertet, den das Dataset konfiguriert. Ein Run
ohne Transkript hat keine Antwort, die sich bewerten ließe.

| Um | Brauchen Sie |
|---|---|
| Zu ändern, wie ein Dataset bewertet wird | `datasets:edit` darauf |
| Einen Bewerter dafür anzulegen | `datasets:edit` darauf und `agents:edit` |
| Einen Run dagegen zu bewerten | `datasets:run` darauf und `runs:view` |
| Seine Scores zu lesen | `datasets:view` darauf |
| Scores zur Prüfung zu schicken, eine Prüfentscheidung festzuhalten oder zurückzuziehen | `datasets:edit` darauf |

Eine Begründung, die der Judge geschrieben hat, durchläuft vor dem Speichern
dieselbe Schwärzung von Zugangsdaten wie ein Fall.

## Zugriff { #access }

Ein Dataset ist eine geteilte Ressource mit Besitzer, Sichtbarkeit und Grants,
wie ein [Skill](skills.md) oder eine [Context-Datei](context.md). Ein neues
Dataset sieht die ganze Organisation, außer der Ersteller legt es von Anfang
an als privat an; später ändert man das auf seiner Seite. Der Katalog hat drei
Berechtigungen für Datasets:

| Berechtigung | Erlaubt einem Mitglied | Grant-Stufe, die sie gibt |
|---|---|---|
| `datasets:view` | Fälle und Versionen eines Datasets lesen und exportieren | `read` |
| `datasets:edit` | Datasets anlegen, Fälle ändern, importieren, löschen, freigeben | `edit` |
| `datasets:run` | Evals über ein Dataset ausführen | `use` |

| | Owner | Admin | Builder | Operator | Member | Viewer |
|---|---|---|---|---|---|---|
| `datasets:view` | all | all | all | all | shared | shared |
| `datasets:edit` | all | all | shared | - | own | - |
| `datasets:run` | all | all | all | all | shared | - |

Ein Mitglied ohne Zugriff auf ein Dataset erhält auf jeder Route „nicht
gefunden“, gleich was seine Rolle anderswo erlaubt - ob ein privates Dataset
existiert, ist selbst etwas, das es nicht erfahren darf. Ein Grant erweitert den
Zugriff auf ein Dataset und ändert nie eine Rolle. Wie Scopes und Grants
zusammenwirken, steht unter [Berechtigungen](permissions.md).

## Personenbezogene Daten { #personal-data }

Ein Fall aus einem Gespräch ist eine Kopie dessen, was eine Person geschrieben
und der Agent geantwortet hat. Wird das Gespräch gelöscht oder die Person, die
es geschrieben hat, gelöscht, bleibt der Fall, und jede Verbindung zurück zu ihr
wird entfernt: der Run, das Gespräch und die Nachricht, aus denen er stammt, und
wer ihn hinzugefügt hat, falls das die gelöschte Person war. Es bleibt der Text -
der weiterhin personenbezogene Daten enthalten kann, die jemand eingegeben hat,
und erst mit dem Löschen des Falls verschwindet. Siehe
[Datenschutz](data-protection.md#what-deletion-reaches).

Ein Score wird auf dieselbe Weise aufbewahrt. Er enthält eine Kopie der
bewerteten Antwort, bis zu 8.000 Zeichen mit geschwärzten Zugangsdaten, damit
ein Prüfer sie neben dem Fall liest. Diese Kopie ist im Export der Person
enthalten, deren Run es war, und wird entfernt, wenn diese Person gelöscht wird.
Wird der Run entfernt, den er bewertet hat, bleibt der Score ohne die Verbindung
zu ihm, und wird die Person gelöscht, die ihn angefordert oder entschieden hat,
wird ihr Name aus ihm entfernt. Die Begründung eines Bewerters kann die Antwort
zitieren, die er bewertet hat.
