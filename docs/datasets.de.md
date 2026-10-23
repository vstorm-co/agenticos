---
source_sha: "2bbee36ec9e5"
title: "Datasets"
description: "Datasets enthalten die Fragen, an denen ein Agent getestet wird: versionierte Fälle, von Hand geschrieben, aus CSV oder JSONL importiert oder aus einer bewerteten Antwort übernommen."
---

# Datasets { #datasets }

Ein **Dataset** enthält die Fragen, an denen ein Agent getestet wird. Ohne eines
besteht jede Prüfung, ob eine Änderung den Agent besser gemacht hat, darin,
dass jemand ein paar Prompts von Hand ausprobiert und sich zu erinnern versucht,
wie die letzte Antwort aussah.

Jede Frage ist ein **Fall**: die Nachricht, die der Agent beantwortet, und wie
eine gute Antwort aussieht. Fälle kommen aus vier Quellen - in der Konsole
geschrieben, aus einer Datei importiert, aus einem echten Gespräch übernommen,
in dem jemand die Antwort negativ bewertet hat, oder vom Fallgenerator entworfen
und von einem Menschen angenommen. Die letzte Quelle
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

Einen Fall hinzufügen, bearbeiten oder entfernen, eine Datei importieren und
generierte Fälle annehmen erzeugt jeweils eine neue **Version** des Datasets,
nummeriert ab 1. Eine
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
indem Sie ihre Nummer eingeben. Eine Version speichert nur,
was sie geändert hat: Ein hinzugefügter oder bearbeiteter Fall ist eine neue
Fallrevision, ein entfernter speichert nichts, daher kostet eine lange
Historie, was sich geändert hat, nicht jeden Fall in jeder Version. Die Datasets
einer Organisation speichern zusammen höchstens
`DATASET_MAX_VERSION_ROWS_PER_ORG` Fallrevisionen (standardmäßig 5 Millionen,
siehe [Konfiguration](configuration.md#datasets)). Ein Hinzufügen oder
Bearbeiten darüber wird abgelehnt und nennt, wie viele gespeichert sind; einen
Fall zu entfernen ist immer erlaubt, und das Löschen eines Datasets gibt seine
Revisionen frei.

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
hinzufügen**, um beide zu behalten. Geprüft wird mit `POST
/datasets/{id}/cases/twins`, mit der Frage im Body, damit sie nicht in
Zugriffsprotokollen landet.

### Aus einer Datei { #import-and-export }

**Importieren** liest eine `.csv`- oder `.jsonl`-Datei und fügt alle Fälle darin
als eine neue Version hinzu. Der Import gilt ganz oder gar nicht: Ist eine Zeile
ungültig, wird keine hinzugefügt, und die Ablehnung nennt jede ungültige Zeile,
damit Sie die Datei korrigieren und es erneut versuchen können. Eine Datei ist
höchstens 10 MB groß, und ein Dataset enthält höchstens 10.000 Fälle. In der
Konsole listet **Importieren** zuerst die Spalten auf und bietet **Vorlage
herunterladen** an, eine CSV-Datei mit jeder Spalte und einem Fall, der sich
unverändert importieren lässt; **Datei wählen** öffnet die Dateiauswahl.

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
  Referenzantwort behalten; die Bestätigung bleibt zehn Sekunden stehen, lange
  genug, um danach zu greifen. Nach einem Daumen nach unten bietet der Dialog,
  der fragt, was schiefging, auch **Diese Antwort zu einem Dataset hinzufügen**
  an: Haken setzen, Dataset wählen und absenden, und die Antwort wird als
  Gegenbeispiel behalten - eine Antwort, die der Agent nicht geben sollte, wie
  der Dialog sagt. Zuerst wird die Bewertung gespeichert, danach der Fall
  angelegt, sodass Ihr Kommentar zur Notiz des Falls wird. Es sind zwei
  getrennte Schreibvorgänge - wird das Hinzufügen abgelehnt, bleibt die
  Bewertung, und die Meldung sagt, welcher Teil fehlschlug. Wird die Bewertung
  später entfernt, bleibt der Fall: Er ist eine Kopie, versioniert mit seinem
  Dataset. Die Konsole merkt sich das zuletzt verwendete Dataset, sodass das
  nächste Hinzufügen ein Klick ist.
- **In Aktivität** hat jede Antwort eines Agents ein Bedienelement **Zum Dataset
  hinzufügen**, einmal, an ihrem letzten Schritt: Eine in Schritten geschriebene
  Antwort - ein Tool-Aufruf, dann der Text - ist ein Fall. Hier werden Antworten
  kuratiert, daher lässt sich eine gute Antwort ebenso leicht als Referenz
  behalten wie eine schlechte als Gegenbeispiel. Gibt es noch kein Dataset zum
  Hinzufügen, legt es eines an, sichtbar für die Organisation; aus **Aus der
  Aktivität hinzufügen** eines Datasets geöffnet, fügt es diesem Dataset hinzu
  und bietet den Weg zurück an.

In beiden Fällen entsteht der Fall aus diesem Zug:

- die Frage wird zur Eingabe, und die Züge davor kommen nur mit, wenn Sie
  **Mit dem Gespräch** wählen. Beide Dialoge im Chat fragen danach - der nach
  dem Daumen nach unten, sobald Sie ihn ankreuzen -, ebenso Activity und
  **Score against a case**; jeder beginnt mit **Nur diese Frage**, damit ein
  Chat, der mit einem anderen Thema begann, draußen bleibt. Im Chat wird eine
  Frage, die die vorige erkennbar fortsetzt, weil sie mit „und“ oder „was ist
  mit“ anfängt, als Fortsetzung gekennzeichnet, und nach einer Frage ohne
  etwas davor wird nicht gefragt. Über die API gilt dasselbe: `with_history`
  auf `POST /datasets/{id}/cases/from-message` ist false, solange es nicht
  gesendet wird;
- die ganze Antwort des Agents auf die Frage - jeder Schritt, den er vor der
  nächsten Frage schrieb - ist die Antwort, und ihr Text wird zum Gegenbeispiel.
  Hat niemand sie negativ bewertet, wird sie stattdessen als Referenzantwort
  angeboten, und Sie wählen eines von beiden; als Referenz behalten, werden die
  Tools, die sie aufrief, zu den erwarteten Tool-Aufrufen des Falls, nach Namen
  (die erfolgreichen, die etwas ändern, kein gescheiterter Aufruf und keiner,
  den ihr Agent als nur lesend deklariert), und eine Antwort ohne Text wird als
  diese allein behalten;
- der neueste Kommentar zu einem Daumen nach unten wird zur Notiz.

Beide Wege sehen nur Mitglieder, die ein Dataset bearbeiten dürfen. Die
Nachricht muss zu Ihrer Organisation gehören, und Sie müssen sie lesen dürfen:
Entweder Sie haben `runs:view`, womit Sie wie in Aktivität jeden Run der
Organisation lesen, oder Sie können das Gespräch öffnen. Eine Nachricht aus
einer anderen Organisation wird abgelehnt, als gäbe es sie nicht, und eine
Antwort, die bereits ein Fall der neuesten Version des Datasets ist, wird
abgelehnt, statt ein zweites Mal hinzugefügt zu werden. **Zu … hinzugefügt**
nennt das Dataset und öffnet es.

### Vom Fallgenerator { #generating-cases }

Hundert gute Fälle von Hand zu schreiben ist der Grund, warum die meisten Teams
keine haben. Der Tab **Generiert** auf der Seite eines Datasets, sichtbar für
Mitglieder, die das Dataset bearbeiten dürfen, bittet den Fallgenerator, sie zu entwerfen, und Sie entscheiden, welche das Dataset behält.
Wählen Sie den Agent, den die Fälle testen - den, aus dessen Anweisungen, Tools
und Chats sie geschrieben werden; gegen ihn läuft nichts -, die Quellen und wie
viele Fälle Sie
möchten - höchstens 50 und mindestens einen je Quelle, gleichmäßig auf die
Quellen verteilt:

| Quelle | Was der Generator entwirft | Was er gezeigt bekommt |
|---|---|---|
| Vom Agent | Typische Anfragen und Grenzfälle, mit den Aufrufen von Tools, die etwas ändern, die eine gute Antwort macht - ein Tool, das nur liest, wird nie erwartet, wie bei einem Fall, der aus einer Antwort hinzugefügt wird | Die Anweisungen des Agents, die seiner Skills, die Sie sehen dürfen, und seine Tools, unter den Namen, die der Agent ihnen gibt |
| Aus dem Wissen | Fragen, die seine Wissensbasis beantwortet. Jeder Fall verweist auf das Dokument, aus dem sein Abschnitt stammt, behält den Abschnitt als Referenzantwort und trägt eine `judge`-Prüfung, dass die Antwort zum Abschnitt passt | Abschnitte aus höchstens 12 indexierten Dokumenten der Wissensbasen, die der Agent nutzt und die Sie lesen dürfen |
| Aus Chats | Umformulierungen und schwierigere Varianten dessen, was Menschen den Agent gefragt haben, negativ bewertete Antworten zuerst. Jeder Fall verweist auf die Frage, die er abwandelt | Höchstens 60 Fragen, die dem Agent in dieser Organisation gestellt wurden, mit dem Kommentar zu einer negativ bewerteten Antwort. Nur Betriebsverkehr: Eval-Runs und isoliert gelaufene Runs haben auf einen Test geantwortet, nicht auf einen Menschen, und bleiben außen vor |
| Red Team | Anfragen außerhalb des Zwecks, Prompt-Injections, Versuche, personenbezogene Daten herauszulocken, und Versuche, die Richtlinien des Agents zu umgehen. Jeder Fall hat die Tags `red-team` und `red-team:<Kategorie>` und eine `judge`-Prüfung, dass der Agent ablehnt | Die Anweisungen des Agents, die seiner Skills, die Sie sehen dürfen, und seine Tools |

**Zuerst die geschätzten Kosten.** Der Dialog zeigt, wie viele Fälle jede Quelle
liefern soll, woraus jede schöpft und eine Schätzung der Kosten auf dem eigenen
Modell des Generators, bevor etwas ausgegeben wird - ein bezahltes Modell unter
einem Cent sagt das, statt $0.00 zu zeigen. Es ist eine Schätzung: Das Budget des Generators wird beim Lauf
geprüft, wie das jedes Agents. Wer den Agent, die Quellen oder die Anzahl
ändert, verwirft die Schätzung.

**Nichts gelangt in das Dataset, bevor Sie es annehmen.** Die Entwürfe warten
unter **Vorgeschlagene Fälle** im Tab Generiert. Nehmen Sie einen
unverändert an, bearbeiten Sie ihn vorher oder verwerfen Sie ihn, einzeln oder
eine Seite auf einmal. Ein Annehmen ist eine neue Version, egal wie viel es
enthielt, und ihre Fälle haben die Quelle `synthetic`. Ein verworfener Entwurf
wird gelöscht und hinterlässt nichts im Dataset. Ein angenommener verschwindet
ebenfalls aus den Entwürfen: Die Version ist sein Nachweis. Ein Entwurf aus Chats
formuliert um, was jemand gefragt hat, deshalb liest und entscheidet ihn nur, wer
Runs ansehen darf; alle anderen, die das Dataset bearbeiten, sehen, wie viele
warten.

**Der Generator ist ein Agent.** Er ist ein Systemagent, der in jeder
Organisation angelegt wird, daher werden seine Runs gegen sein eigenes Budget
und das der Organisation gezählt, und jede Generierung ist ein Run, den Sie in
der [Aktivität](console.md) öffnen können. Er hat keine Tools: Alles, was er
liest, wird mit Ihren eigenen Zugriffsrechten für ihn gesammelt und im Prompt
übergeben, sodass ein Dokument oder ein Gespräch, das ihm Anweisungen geben
will, höchstens den Text eines Entwurfs ändern kann, den Sie prüfen. Ein
Entwurf, der die Regel seiner Quelle nicht einhält - ein Wissensfall ohne einen
Abschnitt, den der Generator bekam, ein Gesprächsfall ohne eine Frage, die er
bekam, ein Red-Team-Fall ohne Kategorie, ein Fall, der nichts erwartet, ein
Fall, dessen Referenzantwort sein Gegenbeispiel wiederholt und damit selbst
durchfallen würde -, wird verworfen, bevor Sie ihn sehen. Ebenso ein Fall in
einer Form, die sich nicht lesen lässt: Der Rest der Antwort wird trotzdem zu
Entwürfen, und nur eine Antwort ohne einen lesbaren Fall schlägt fehl. Eine
abgeschlossene Generierung sagt, wie viele Fälle sie ausgelassen hat, die nicht
lesbaren getrennt von denen, die eine Regel verletzten.

**Jede Quelle hat ihre eigene Schranke**, und eine Quelle, die Sie nicht nutzen
dürfen, wird mit Namen abgelehnt statt stillschweigend ausgelassen:

- jede Generierung braucht `datasets:edit` auf dem Dataset, `agents:view` auf
  dem getesteten Agent und `agents:run` auf dem Fallgenerator, weil sie Geld der
  Organisation ausgibt;
- Wissen liest nur die Wissensbasen, die Sie lesen dürfen; der Dialog sagt, wie
  viele der Wissensbasen des Agents ausgelassen wurden;
- Gespräche brauchen `runs:view`, die Berechtigung, mit der die Aktivität jeden
  Run liest;
- die KI-Unterstützung ist in jeder Organisation ausgeschaltet, bis ein Owner
  oder Admin sie in den Einstellungen der Organisation einschaltet, und solange
  sie aus ist, startet keine Generierung - der Tab sagt das und wer es ändern
  kann. Wartende Entwürfe lassen sich weiterhin annehmen oder
  verwerfen, weil die Entscheidung kein Modell aufruft.

Nur Mitglieder, die das Dataset bearbeiten dürfen, sehen seine Entwürfe. Ein
Entwurf aus einem Gespräch ist Text, den die übrigen Leser des Datasets nicht zu
sehen bekommen haben; angenommen ist er ein Fall wie jeder andere.

## Zugangsdaten werden geschwärzt { #credentials }

Der Text von Fällen wird aus Gesprächen und hochgeladenen Dateien kopiert und
später exportiert und an Modelle übergeben. Bevor ein Fall gespeichert wird,
ersetzt die Plattform jeden erkannten API-Schlüssel und jedes erkannte Token
durch einen Platzhalter wie `[redacted:github_token]`. Das gilt für jedes Feld,
das ein Modell liest oder ein Export enthält, auch für die Argumente eines
erwarteten Tool-Aufrufs, und für jeden Weg, auf dem ein Fall hinzukommt. Eine
Generierung schwärzt außerdem die Fragen und Abschnitte, die sie dem Generator
übergibt, bevor sie an das Modell gehen. Der Audit-Eintrag der Änderung hält
fest, wie viele Werte geschwärzt wurden, nie die Werte selbst.

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
| Bewerter (**Ihre Kriterien** auf der Karte Bewerter) | Die Antwort anhand einer Rubrik benannter Kriterien, bewertet vom Bewerter des Datasets | Ein Run des Bewerters |
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
ersten Modell der Organisation oder einem, das Sie wählen. Der Prompt lässt sich
vor dem Anlegen bearbeiten (`GET /datasets/{id}/judge-template`). Dafür braucht
es `agents:edit` und `datasets:edit`.

Der Bewerter ist so weit sichtbar wie das Dataset, da sein Prompt dessen Namen
und Beschreibung enthält, und bleibt ein Entwurf für jemanden, der ihn
veröffentlichen darf (`agents:publish`), wenn sein Ersteller es nicht darf.

Das Modell wird im selben Panel wie bei einem Agent gewählt: ein Provider, seine
vollständige Modellliste und ein Schlüssel für alle, die ein Modell hinzufügen
dürfen (`connections:manage`), und die gespeicherten Modelle für alle anderen.

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

Der Bewerter erhält die Notiz des Falls als Grund, warum es den Fall gibt, seine
früheren Züge und die Frage, die Referenzantwort, wenn sie bewertet wird, das
Gegenbeispiel, jeden Tool-Aufruf des Agenten - mit seinen Argumenten und ob ein
isolierter Run ihn blockiert hat - und die Antwort.

Ein Fall mit Gegenbeispiel wird immer auch nach dem erforderlichen Kriterium
**counter-example** bewertet: Die Antwort darf die bekannte schlechte Antwort
nicht wiederholen, und der Bewerter soll zitieren, was die Antwort von ihr
unterscheidet. Es wird bewertet, sobald **Ihre Kriterien** oder die
Referenzantwort eingeschaltet ist, und hat daher keinen eigenen Schalter; die
Karte Bewerter zeigt, wie viele Fälle ein Gegenbeispiel haben.

Ein Bestehen des Kriteriums counter-example ist
ein Fehler, wenn es nur zitiert, was beide
sagen, oder nichts aus einer Antwort zitiert, die das Gegenbeispiel kopiert;
jedes andere ohne Zitat bleibt stehen, als nicht belegt markiert. Eine Antwort,
die das Gegenbeispiel behält und ergänzt, was ihm fehlte, besteht mit einem
Zitat der Ergänzung. Eine Antwort, die das Gegenbeispiel ist oder ein Teil
davon, fällt bei dem Kriterium durch, was auch immer der Bewerter sagte.

Bewerter starten mit Temperatur 0, damit dieselbe Antwort zweimal gleich
bewertet wird; ein Modell, das keine Temperatur annimmt, etwa ein
Reasoning-Modell, bewertet ohne sie.

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
Antwort ließ sich nicht lesen - deren erste 2.000 Zeichen bleiben dann neben der
Begründung. Die regelbasierten Scorer bewerten trotzdem.

Ist die Ursache behoben, bewertet **Erneut bewerten** an einem nicht bewerteten
Ergebnis - oder an allen in der Gruppe eines Eval-Runs auf dem Tab Prüfung -
dieselbe Antwort neu, mit der Konfiguration, mit der sie zuerst bewertet wurde
(`POST /datasets/{id}/scores/rescore`, bis zu zehn Scores pro Anfrage). Der
Agent läuft nicht erneut, und der Score behält seinen Eval-Run und jede
Entscheidung, die eine Person darüber getroffen hat; einer, bei dem jeder
Scorer zu einem Urteil kam, bleibt, wie er ist.

Eine Ursache, die noch besteht - KI-Unterstützung aus, Bewerter nicht
veröffentlicht -, wird so abgelehnt, wie sie ist, ebenso der Bewerter eines
Eval-Runs, der seit seinem Fehlschlag neu veröffentlicht wurde, oder ein
Ergebnis eines solchen Runs, das an einen früheren Bewerter-Prompt gebunden ist,
dessen Bewertung sich nicht mit dem Rest des Runs vergleichen ließe; dann wird
nichts bewertet.

Eine für sich bewertete Antwort, aus dem Chat oder aus Activity, hat keinen Run,
mit dem sie sich vergleichen müsste: Sie wird von der jetzt veröffentlichten
Version bewertet, und ihr Pin nennt diese Version. Ein Ergebnis wird gebunden,
ob sein Bewerter bewertet hat oder gescheitert ist, also bleibt ein
gescheitertes an die Version und den Prompt gebunden, mit denen es scheiterte.

Eine Bewertung darf die Antwort zitieren, bis zu 12 Stellen; ein Zitat, das die
Antwort nicht wörtlich enthält, wird neben der Bewertung als nicht verifiziert
aufbewahrt und in einer eigenen Zeile unter der Begründung angezeigt, und die
Bewertung bleibt bestehen.

Was eine Bewertung stützt, macht sie nie ungültig: Ein leeres oder zu langes
Zitat wird verworfen, Zitate über zwölf und eine Regel über 300 Zeichen werden
gekürzt, und nur eine fehlende Kriteriums-ID oder Note macht ein Urteil
unlesbar. Ein mehrfach bewertetes Kriterium ist ein Fehler, nicht die zuletzt
gekommene Note. Der Run des Bewerters in Activity nennt die Felder, die sich
nicht lesen ließen, nie die Antwort selbst, die einen Fall eines Datasets
wiederholen kann, das sein Leser nicht sehen darf.

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
an denen der Bewerter mit einem Fehler scheiterte - nicht die, die er
übersprungen hat und die auf eine erneute Bewertung warten - ein Score pro Fall.
Seine Seite schickt weitere Scores, die Sie auswählen, alle auf einmal über
`POST /datasets/{id}/scores/review` mit bis zu 500 Score-IDs - alle oder keine.

Ein dorthin geschickter Score, von einem Eval-Run oder von Hand, nimmt den Platz
eines noch wartenden Scores seines Falls ein, wenn er höher rangiert oder gleich
rangiert und neuer ist. Ein bewerteter Score - eine Regression oder ein von Hand
geschicktes Fail - rangiert über einem, den nichts bewertet hat, etwa einem
Fehler des Bewerters, sodass ein scheiternder Bewerter die Regression eines
Falls nie verdrängt. Der ersetzte verlässt die Warteschlange unentschieden und
bleibt ein Score; sonst behält der wartende seinen Platz, und der geschickte
wird nicht eingereiht. Ein entschiedener Score wird nie angetastet.

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
**Gegen einen Fall bewerten**. Der Dialog öffnet sich auf einem Dataset mit
einem Fall, der die Frage des Runs selbst stellt, und wählt diesen Fall aus;
haben mehrere Datasets einen, sagt er das und führt sie zuerst auf. Hat das
gewählte Dataset keinen, bietet der Dialog an, die Antwort des Runs als Fall
hinzuzufügen, bis Sie einen Fall wählen, und führt die Fälle, die der Frage des
Runs am nächsten sind, zuerst auf - die, die die meisten ihrer Wörter teilen,
auf der angezeigten Seite.

Die Antwort und die Tool-Aufrufe des Runs werden mit jedem Scorer bewertet, den das Dataset konfiguriert. Ein Run
ohne Transkript hat keine Antwort, die sich bewerten ließe.

Der Dialog nennt den Bewerter, der bewerten wird, und das Modell, auf dem er
bewertet, mit Links, um den Bewerter des Datasets in seinem Tab Bewertung und
das Modell des Bewerters auf seiner Seite zu ändern - beides gilt für jede
danach bewertete Antwort, daher wird keines davon im Dialog geändert.

| Um | Brauchen Sie |
|---|---|
| Zu ändern, wie ein Dataset bewertet wird | `datasets:edit` darauf |
| Einen Bewerter dafür anzulegen | `datasets:edit` darauf und `agents:edit` |
| Einen Run dagegen zu bewerten | `datasets:run` darauf und `runs:view` |
| Seine Scores zu lesen | `datasets:view` darauf |
| Scores zur Prüfung zu schicken, eine Prüfentscheidung festzuhalten oder zurückzuziehen | `datasets:edit` darauf |

Eine Begründung, die der Judge geschrieben hat, durchläuft vor dem Speichern
dieselbe Schwärzung von Zugangsdaten wie ein Fall.

Damit ein Agent jeden Fall einer Version in einem Durchgang beantwortet, jede
Antwort bewertet und das Ergebnis mit einer früheren Version verglichen wird,
starte einen [Eval-Run](evals.md).

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

Die Antwort eines Ergebnisses gehört dem Agent, also braucht ihr Lesen auch
Zugriff auf diesen Agent: Wer das Dataset lesen, den antwortenden Agent aber
nicht sehen darf (`agents:view` darauf, per Rolle oder Grant), liest Ergebnis,
Status und Fall, und die Antwort ist ausgeblendet - mit jeder Begründung, jedem
Zitat und jeder Antwort des Bewerters, die sie wiederholen kann. Das gilt
überall, wo Ergebnisse gelesen werden: im Tab Prüfung, in der Prüfwarteschlange
und im Tab Datasets eines Bewerters. Eine Antwort, deren Run oder Agent nicht
mehr existiert, sieht nur, wer jeden Agent der Organisation sehen darf.

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

Ein generierter Fall, der noch auf eine Entscheidung wartet, wird nicht so
aufbewahrt. Wird das Gespräch gelöscht, aus dem er entworfen wurde, oder die
Person gelöscht, die die Frage gestellt hat, wird der Entwurf mit gelöscht:
Niemand hat entschieden, ihn zu behalten. Der Datenexport einer Person enthält
die Entwürfe aus ihren Fragen und Gesprächen. Eine Generierung aus Gesprächen
schickt die gestellten Fragen, geschwärzt, an den Modellanbieter des
Fallgenerators, und eine Generierung aus dem Wissen schickt Abschnitte der
Dokumente - siehe
[was das Deployment verlässt](data-protection.md#what-leaves-the-deployment).
