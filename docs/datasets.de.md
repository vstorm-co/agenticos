---
source_sha: "2bec95c1a323"
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
| Prüfungen | Regeln für die Antwort, jede ein Objekt, dessen `type` die Regel benennt, mit deren Parametern daneben. [Scoring](#checks) listet die Typen auf, und ein Fall mit einem Typ, den es nicht kennt, wird abgelehnt |
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

Öffnen Sie **Datasets**, legen Sie ein Dataset an und wählen Sie **Fall
hinzufügen**. Schreiben Sie die Eingabe und mindestens eine der vier Erwartungen oben. Gespräch, erwartete
Tool-Aufrufe und Prüfungen werden als JSON-Listen geschrieben - derselbe Text,
in dem ein CSV-Export sie enthält.

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

## Scoring { #scoring }

Ein Dataset legt auf seinem Tab **Scoring** fest, wie seine Fälle bewertet
werden. Vier Scorer können auf einen Fall angewendet werden, und jeder wird ein-
oder ausgeschaltet und als erforderlich markiert oder nicht:

| Scorer | Was er vergleicht | Kosten |
|---|---|---|
| Prüfungen | Die Antwort mit den Regeln des Falls und mit Standardregeln, die das Dataset jedem Fall mitgibt | Keine |
| Tool-Aufrufe | Die Tools, die der Agent aufgerufen hat, mit den erwarteten Aufrufen des Falls | Keine |
| Judge | Die Antwort anhand einer Rubrik benannter Kriterien, bewertet vom Eval-Judge | Ein Run des Judge |
| Referenzantwort | Die Antwort mit der Referenzantwort des Falls, bewertet vom Eval-Judge | Derselbe Run des Judge |

Jeder Scorer liefert bestanden oder nicht bestanden, einen Score von 0 bis 1 und
eine Begründung. Ein Fall **besteht**, wenn jeder erforderliche Scorer besteht.
Konnte ein erforderlicher Scorer nicht laufen - der Judge war ausgeschaltet,
sein Budget war aufgebraucht -, ist der Fall **unbewertet**, nicht bestanden:
Ein Ergebnis, das niemand geprüft hat, zählt nicht als bestanden.

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
ist true. Ein Muster wird geprüft, wenn der Fall geschrieben wird, und eine Regel
liest höchstens die ersten 100.000 Zeichen einer Antwort, damit ein einzelnes
Muster das Scoring nicht langsam machen kann.

Eine `judge`-Prüfung ist ein Kriterium nur für einen Fall, bewertet im selben
Judge-Run wie die Rubrik des Datasets. Verwenden Sie sie für das, was eine Regel
nicht ausdrücken kann, etwa „lehnt ab und verrät die Adresse des Kunden nicht“.

### Tool-Aufrufe { #trajectory }

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

### Der Judge { #judge }

Der Judge ist der **Eval judge**, ein Agent, den die Plattform jeder
Organisation hinzufügt (siehe [System-Agents](concepts.md#system-agents)). Er
läuft als die Person, die den Score angefordert hat: Ihr Zugriff auf ihn wird
geprüft, er wird vor dem Modellaufruf gegen sein eigenes Budget und das der
Organisation geprüft, und sein Run erscheint in Activity unter der Oberfläche
`eval`. Seine Anweisungen lassen sich wie die jedes Agents bearbeiten, und ein
Dataset kann ein anderes Modell für ihn festlegen.

Jedes Kriterium wird von 1 bis zum oberen Ende der Skala bewertet und besteht ab
der Bestehensgrenze. Kann der Judge nicht bewerten, werden seine Kriterien als
übersprungen oder als Fehler festgehalten, mit einer Begründung, die die
Ursache nennt: KI-Unterstützung ist ausgeschaltet, der Judge hat keine
veröffentlichte Version, er ist archiviert, die Person darf ihn nicht ausführen,
oder sein Budget ist aufgebraucht. Die regelbasierten Scorer bewerten trotzdem.

Eine Bewertung darf die Antwort zitieren, bis zu 12 Stellen; ein Zitat, das die
Antwort nicht wörtlich enthält, wird in der Begründung als nicht verifiziert
genannt, und die Bewertung bleibt bestehen. Jedes Ergebnis hält den Judge fest,
der es bewertet hat - sein Modellprofil, die Version seiner Spec und einen Hash
der Rubrik -, damit Ergebnisse verschiedener Judges nicht als gleichwertig
verglichen werden.

### Review und Urteile { #review }

Ein Dataset kann Ergebnisse in eine **Review-Warteschlange** schicken: keine,
bis jemand eines schickt, jedes Ergebnis, das nicht bestanden hat, oder jedes
Ergebnis. Der Tab Scores zeigt die Ergebnisse eines Datasets, und die
Dashboard-Karte **Awaiting review** zeigt die Warteschlange über alle Datasets,
die Sie sehen können: wie viele Ergebnisse nicht bestanden haben, nicht bewertet
werden konnten oder bestanden haben, und in welchen Datasets, jedes öffnet sich
auf seinem Tab Scores. Die Karte ist standardmäßig auf dem Dashboard.

Das Urteil einer Person wird neben den Ergebnissen der Scorer gespeichert und
entscheidet über das Ergebnis. Es ändert nie, was der Judge gesagt hat: Die
Bewertungen und Begründungen des Judge bleiben am Score, nachdem er überstimmt
wurde. Ein Urteil kann zurückgezogen werden, und der Score wartet dann wieder
auf ein Review.

### Einen Run bewerten { #scoring-a-run }

Öffnen Sie in **Activity** einen Run und wählen Sie **Score against a case**.
Wählen Sie das Dataset und den Fall, und die Antwort und die Tool-Aufrufe des
Runs werden mit jedem Scorer bewertet, den das Dataset konfiguriert. Ein Run
ohne Transkript hat keine Antwort, die sich bewerten ließe.

| Um | Brauchen Sie |
|---|---|
| Zu ändern, wie ein Dataset bewertet wird | `datasets:edit` darauf |
| Einen Run dagegen zu bewerten | `datasets:run` darauf und `runs:view` |
| Seine Scores zu lesen | `datasets:view` darauf |
| Ein Urteil festzuhalten oder zurückzuziehen | `datasets:edit` darauf |

Eine Begründung, die der Judge geschrieben hat, durchläuft vor dem Speichern
dieselbe Schwärzung von Zugangsdaten wie ein Fall.

## Zugriff { #access }

Ein Dataset ist eine geteilte Ressource mit Besitzer, Sichtbarkeit und Grants,
wie ein [Skill](skills.md) oder eine [Context-Datei](context.md). Ein neues
Dataset ist privat für den Ersteller, bis es auf seiner Seite freigegeben wird.
Der Katalog hat drei Berechtigungen für Datasets:

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

Ein Score wird auf dieselbe Weise aufbewahrt. Wird der Run entfernt, den er
bewertet hat, bleibt der Score ohne die Verbindung zu ihm, und wird die Person
gelöscht, die ihn angefordert oder entschieden hat, wird ihr Name aus ihm
entfernt. Die Begründung eines Judge kann die Antwort zitieren, die er bewertet
hat.
