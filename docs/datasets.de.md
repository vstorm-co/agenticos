---
source_sha: "b87eb7e189ca"
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
| Prüfungen | Regeln für die Antwort, jede ein Objekt, dessen `type` die Regel benennt, mit deren Parametern daneben. Ein Fall bewahrt sie auf; das Scoring liest sie und entscheidet, welche Typen es gibt |
| Tags | Labels zum Gruppieren von Ergebnissen, etwa `billing` oder `refusal` |
| Notiz | Warum es den Fall gibt - was schiefging oder was er absichert |
| Quelle | `manual`, `import`, `conversation` oder `synthetic` - von der Plattform gesetzt, nicht eingegeben |

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

Ein Dataset umzubenennen oder seine Beschreibung zu ändern erzeugt keine
Version, weil keines von beiden einen Fall ändert.

## Fälle hinzufügen { #adding-cases }

### In der Konsole { #in-the-console }

Öffnen Sie **Datasets**, legen Sie ein Dataset an und wählen Sie **Fall
hinzufügen**. Das einzige Pflichtfeld ist die Eingabe. Gespräch, erwartete
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

Jede Agent-Antwort im Chat und jeder Agent-Zug in **Aktivität** hat ein
Bedienelement **Zum Dataset hinzufügen**. Wählen Sie ein Dataset, und der Fall
entsteht aus diesem Zug:

- die Frage wird zur Eingabe, die Züge davor werden zum Gespräch vor der
  Eingabe;
- die Antwort wird zum Gegenbeispiel. Hat niemand sie negativ bewertet, wird
  sie stattdessen als Referenzantwort angeboten, und Sie wählen eines von
  beiden;
- der neueste Kommentar zu einem Daumen nach unten wird zur Notiz.

Das Bedienelement sehen Mitglieder, die ein Dataset bearbeiten dürfen. Die
Nachricht muss zu Ihrer Organisation gehören, und Sie müssen sie lesen dürfen:
Entweder Sie haben `runs:view`, womit Sie wie in Aktivität jeden Run der
Organisation lesen, oder Sie können das Gespräch öffnen. Eine Nachricht aus
einer anderen Organisation wird abgelehnt, als gäbe es sie nicht.

### Vom Fallgenerator { #generating-cases }

Hundert gute Fälle von Hand zu schreiben ist der Grund, warum die meisten Teams
keine haben. **Fälle generieren** auf der Seite eines Datasets bittet den
Fallgenerator, sie zu entwerfen, und Sie entscheiden, welche das Dataset behält.
Wählen Sie den Agent, den die Fälle testen, die Quellen und wie viele Fälle Sie
möchten - höchstens 50, gleichmäßig auf die Quellen verteilt:

| Quelle | Was der Generator entwirft | Was er gezeigt bekommt |
|---|---|---|
| Vom Agent | Typische Anfragen und Grenzfälle, mit den Tool-Aufrufen, die eine gute Antwort macht | Die Anweisungen des Agents, seine Skills und seine Tools, unter den Namen, die der Agent ihnen gibt |
| Aus dem Wissen | Fragen, die seine Wissensbasis beantwortet. Jeder Fall verweist auf das Dokument, aus dem sein Abschnitt stammt, behält den Abschnitt als Referenzantwort, erwartet einen Aufruf der Wissenssuche des Agents und trägt eine `judge`-Prüfung, dass die Antwort zum Abschnitt passt | Abschnitte aus höchstens 12 indexierten Dokumenten der Wissensbasen, die der Agent nutzt und die Sie lesen dürfen |
| Aus Gesprächen | Umformulierungen und schwierigere Varianten dessen, was Menschen den Agent gefragt haben, negativ bewertete Antworten zuerst. Jeder Fall verweist auf die Frage, die er abwandelt | Höchstens 60 Fragen, die dem Agent in dieser Organisation gestellt wurden, mit dem Kommentar zu einer negativ bewerteten Antwort |
| Red Team | Anfragen außerhalb des Zwecks, Prompt-Injections, Versuche, personenbezogene Daten herauszulocken, und Versuche, die Richtlinien des Agents zu umgehen. Jeder Fall hat die Tags `red-team` und `red-team:<Kategorie>` und eine `judge`-Prüfung, dass der Agent ablehnt | Die Anweisungen des Agents, seine Skills und seine Tools |

**Zuerst die geschätzten Kosten.** Der Dialog zeigt, wie viele Fälle jede Quelle
liefern soll, woraus jede schöpft und eine Schätzung der Kosten, bevor etwas
ausgegeben wird. Es ist eine Schätzung: Das Budget des Generators wird beim Lauf
geprüft, wie das jedes Agents. Wer den Agent, die Quellen oder die Anzahl
ändert, verwirft die Schätzung.

**Nichts gelangt in das Dataset, bevor Sie es annehmen.** Die Entwürfe warten
unter **Vorgeschlagene Fälle** auf der Seite des Datasets. Nehmen Sie einen
unverändert an, bearbeiten Sie ihn vorher oder verwerfen Sie ihn, einzeln oder
eine Seite auf einmal. Ein Annehmen ist eine neue Version, egal wie viel es
enthielt, und ihre Fälle haben die Quelle `synthetic`. Ein verworfener Entwurf
wird gelöscht und hinterlässt nichts im Dataset. Ein angenommener verschwindet
ebenfalls aus den Entwürfen: Die Version ist sein Nachweis.

**Der Generator ist ein Agent.** Er ist ein Systemagent, der in jeder
Organisation angelegt wird, daher werden seine Runs gegen sein eigenes Budget
und das der Organisation gezählt, und jede Generierung ist ein Run, den Sie in
der [Aktivität](console.md) öffnen können. Er hat keine Tools: Alles, was er
liest, wird mit Ihren eigenen Zugriffsrechten für ihn gesammelt und im Prompt
übergeben, sodass ein Dokument oder ein Gespräch, das ihm Anweisungen geben
will, höchstens den Text eines Entwurfs ändern kann, den Sie prüfen. Ein
Entwurf, der die Regel seiner Quelle nicht einhält - ein Wissensfall ohne einen
Abschnitt, den der Generator bekam, ein Gesprächsfall ohne eine Frage, die er
bekam, ein Red-Team-Fall ohne Kategorie -, wird verworfen, bevor Sie ihn sehen.

**Jede Quelle hat ihre eigene Schranke**, und eine Quelle, die Sie nicht nutzen
dürfen, wird mit Namen abgelehnt statt stillschweigend ausgelassen:

- jede Generierung braucht `datasets:edit` auf dem Dataset, `agents:view` auf
  dem getesteten Agent und `agents:run` auf dem Fallgenerator, weil sie Geld der
  Organisation ausgibt;
- Wissen liest nur die Wissensbasen, die Sie lesen dürfen; der Dialog sagt, wie
  viele der Wissensbasen des Agents ausgelassen wurden;
- Gespräche brauchen `runs:view`, die Berechtigung, mit der die Aktivität jeden
  Run liest;
- eine Organisation, die die KI-Unterstützung ausgeschaltet hat, kann keine
  Generierung starten. Wartende Entwürfe lassen sich weiterhin annehmen oder
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

Ein generierter Fall, der noch auf eine Entscheidung wartet, wird nicht so
aufbewahrt. Wird das Gespräch gelöscht, aus dem er entworfen wurde, oder die
Person gelöscht, die die Frage gestellt hat, wird der Entwurf mit gelöscht:
Niemand hat entschieden, ihn zu behalten. Eine Generierung aus Gesprächen
schickt die gestellten Fragen, geschwärzt, an den Modellanbieter des
Fallgenerators, und eine Generierung aus dem Wissen schickt Abschnitte der
Dokumente - siehe
[was das Deployment verlässt](data-protection.md#what-leaves-the-deployment).
