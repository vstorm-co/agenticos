---
source_sha: "b0c3775cb0c7"
title: "Wissenslücken"
description: "Wissenslücken zeigen die Fragen, zu denen ein Agent in seiner Wissensbasis nichts Passendes gefunden oder ohne Wissen geantwortet hat, nach Thema gruppiert, damit klar ist, welches Dokument fehlt."
---

# Wissenslücken { #knowledge-gaps }

Viele schlechte Antworten liegen nicht an den Anweisungen des Agents. Die
Wissensbasis enthält die Antwort nicht, und keine Änderung am Prompt behebt das.
**Wissenslücken** zeigen genau diese Fragen: die, zu denen ein Agent seine
[Wissensbasis](file-processing.md) durchsucht und nichts Passendes gefunden
oder ohne Wissen geantwortet hat, nach Thema gruppiert, mit der Häufigkeit jeder Frage und den Agents, die
sie gestellt haben.

Eine Lücke sagt, was fehlt. Sie fügt einer Wissensdatenbank nie selbst etwas hinzu.
Ein Mensch schreibt oder findet das fehlende Dokument - ein Modell kann es
entwerfen - und fügt es hinzu. Vorher
lassen sich die Fragen des Themas in Fälle eines [Datasets](datasets.md)
umwandeln, damit ein Eval zeigt, ob das neue Dokument die Antworten verändert
hat.

## Wie eine Frage zur Lücke wird { #how-a-question-becomes-a-gap }

Jedes Mal, wenn ein Agent während eines Runs seine Wissensbasis durchsucht,
zeichnet die Plattform die Suche auf: die Anfrage, die der Agent geschickt hat,
die durchsuchten Wissensdatenbanken, wie viele Passagen zurückkamen und wie ähnlich die
nächste Passage der Anfrage war. Eine Suche ist ein **Fehltreffer**, wenn sie
nichts zurückgegeben hat oder wenn ihre nächste Passage der Anfrage weniger
ähnlich ist als `KNOWLEDGE_GAP_MIN_SIMILARITY`.

| Einstellung | Standard | Was sie entscheidet |
|---|---|---|
| `KNOWLEDGE_GAP_MIN_SIMILARITY` | `0.30` | Die Kosinus-Ähnlichkeit, unter der die nächste Passage als „nichts Passendes“ zählt. Welchen Wert ein guter Treffer erreicht, hängt vom Embedding-Modell ab; prüfe also einige deiner eigenen Suchen, bevor du sie änderst |

Die Ähnlichkeit ist die Kosinus-Ähnlichkeit des Vektors der Passage zum Vektor
der Anfrage. Sie ist nicht der Ranking-Wert: Bei hybrider Suche oder
Anfrageerweiterung ist der Ranking-Wert ein fusionierter Rang und sagt nichts
darüber, wie nah eine Passage war.

Jede Suche wird gespeichert, nicht nur die Fehltreffer. Wenn du den
Schwellenwert änderst, gilt er auch für die bereits gemachten Suchen: Die
Lücken, die du liest, sind immer die Suchen unter der aktuellen Einstellung.

Gespeichert werden nur Suchen, die ein Agent während seines Runs macht, und nur
zu Fragen, die Menschen gestellt haben: Eine Suche über `/rag/search` der HTTP
API, eine Vorschau auf der Seite der Wissensdatenbank und eine Suche eines Eval-Runs
werden nicht gespeichert. Von einer Anfrage werden die ersten 1.000 Zeichen
behalten.

## Antworten und Kommentare { #answers-and-comments }

Eine Suche kann eine Passage finden, und der Agent kennt die Antwort trotzdem
nicht; ein Leser kann eine Antwort negativ bewerten, weil etwas fehlte. Die
Suche allein sieht beides nicht. **N Antworten prüfen** auf dem Tab
Wissenslücken der Wissensbasis lässt ein Modell ihre letzten Antworten darauf
lesen. Die Schaltfläche erscheint, solange die
[KI-Unterstützung](governance.md#ai-assistance) eingeschaltet ist, und zählt
die noch ungelesenen Antworten. Ist der Schalter aus, sagt der Tab, wie viele
Antworten warten, mit einem Link zum Schalter für alle, die ihn ändern dürfen.

Das Modell ist der **Knowledge gap classifier**, ein
[System-Agent](concepts.md#system-agents), den jede Organisation hat. Er liest
jede Antwort mit ihrer Frage und den Kommentaren aller, die sie negativ bewertet
haben, und entscheidet eines von drei Dingen:

| Urteil | Wann |
|---|---|
| Der Agent wusste es nicht | Die Antwort sagt, in beliebigen Worten und Sprachen, dass der Agent es nicht wusste oder die Information nicht fand |
| Informationen fehlten | Ein Kommentar zu einer negativen Bewertung sagt, dass Informationen fehlten, veraltet oder unvollständig waren |
| Keine Lücke | Alles andere: eine richtige Antwort, die Ablehnung einer Frage, für die der Agent nicht da ist, ein Kommentar zu Ton, Länge oder einem Fehler |

Eine Antwort mit einem der ersten beiden Urteile wird zu einer Frage in den
Themen der Wissensbasis und wie eine fehlgeschlagene Suche gruppiert. Im Thema
steht, welcher der beiden Fälle es ist, statt einer Suche.

Eine Antwort wird gelesen, wenn ihr Run aus den letzten 30 Tagen die
Wissensbasis durchsucht und etwas gefunden hat oder mit einem Kommentar negativ
bewertet wurde und auf einer Agent-Version läuft, die an die Wissensbasis
gebunden ist. Ein Run, dessen Suche schon ein Fehltreffer war, zählt einmal, als
dieser Fehltreffer. Runs über die HTTP-API behalten keine Antwort, und Eval-Runs,
deren Fragen wiederholt oder erzeugt sind, werden nie gelesen. Delegierte Runs
ebenso wenig.

Eine Prüfung liest bis zu 100 Antworten, 20 je Run des Klassifizierers. Jeder
Run wird gegen das Budget des Klassifizierers und der Organisation geprüft,
bevor das Modell aufgerufen wird, und steht in der Aktivität unter der Person,
die gefragt hat: Wählen Sie **Jede Oberfläche, Evals eingeschlossen**, um ihn zu
sehen. Jede gelesene Antwort wird gemerkt, egal mit welchem Urteil, also wird
für keine zweimal bezahlt. Eine als „keine Lücke“ gelesene Antwort wird erst
nach einer neuen negativen Bewertung mit Kommentar erneut gelesen. Eine Prüfung
hält bei einem Run an, der ohne Antwort endet, etwa einem, den ein
aufgebrauchtes Budget verweigert, und behält, was sie gelesen hat. Für eine
Wissensbasis läuft immer nur eine Prüfung.

## Themen { #topics }

Fehltreffer werden nach der Bedeutung der Anfrage zu **Themen** gruppiert. Alle
15 Minuten nimmt ein Hintergrundlauf die neuen Fehltreffer jeder Wissensbasis,
bettet sie mit dem eigenen Embedding-Modell dieser Wissensdatenbank ein und legt jeden
in das nächste Thema dieser Wissensbasis oder beginnt ein neues. Ein Lauf bettet
höchstens 500 Fehltreffer pro Wissensbasis ein; der Rest wartet auf den
nächsten. Eine Wissensbasis ohne neue Fehltreffer kostet keinen
Embedding-Aufruf.

- Eine Suche über zwei Wissensdatenbanken wird zu einer Frage in einem Thema jeder der
  beiden.
- Eine Wissensdatenbank, die auf ein anderes Embedding-Modell umgestellt wurde,
  beginnt neue Themen, weil Vektoren zweier Modelle nicht vergleichbar sind.
- Ein Thema behält seine Identität, wenn Fragen hinzukommen, sodass eine
  Entscheidung, die du dazu getroffen hast, weiter gilt.

**Jetzt gruppieren** im Tab der Wissenslücken einer Wissensdatenbank führt den Lauf
für diese Wissensbasis sofort aus, statt auf den Zeitplan zu warten. Bis eine
Frage einem Thema zugeordnet ist, zählt der Tab sie als noch nicht gruppiert.

## Lücken lesen { #reading-gaps }

Lücken erscheinen an drei Stellen:

- im Tab **Wissenslücken** einer Wissensdatenbank: alle ihre Themen;
- im Tab **Wissenslücken** eines Agents: nur die Fragen dieses Agents, in den
  Wissensbasen, die du lesen darfst;
- im Dashboard-Widget **Wissenslücken**, hinzugefügt über **Anpassen**: die am
  häufigsten gestellten Themen in der ganzen Organisation und wie viele Themen
  jede Wissensbasis hat.

Ein Thema gehört zu seiner Wissensdatenbank, also folgt, wer es liest, daraus,
wer diese Wissensdatenbank liest. Einen eigenen Filter nach Abteilung gibt es
nicht: Eine Abteilung sieht die Lücken der Wissensdatenbanken, die mit ihr
geteilt sind.

Ein Thema zeigt, wie oft es gestellt wurde, wann zuletzt, welche Agents es
gestellt haben, und bis zu drei seiner Fragen. Öffne es, um die neuesten Fragen
zu sehen: was die Person gefragt hat, wonach der Agent gesucht hat, wie nah die
nächste Passage war und den Kommentar aller, die die Antwort negativ bewertet
haben. Eine aus einer Antwort gelesene Frage sagt, ob der Agent es nicht wusste
oder ein Leser schrieb, dass Informationen fehlten.

## Was mit einer Lücke zu tun ist { #acting-on-a-gap }

**Zum Dataset hinzufügen** und **Verwerfen** stehen im Menü **…** eines Themas,
in seiner Zeile und im Thema selbst.

| Aktion | Was sie tut |
|---|---|
| Fehlendes Dokument hinzufügen | Lade es in die Wissensdatenbank hoch oder in eine Quelle, aus der die Wissensdatenbank synchronisiert. Nichts wird für dich hinzugefügt |
| **Zum Dataset hinzufügen** | Wandelt die neuesten Fragen des Themas (bis zu 200) in Fälle eines Datasets um, das du ändern darfst, als eine neue Version. Jeder Fall ist die Frage der Person, mit der Antwort des Agents als Gegenbeispiel. Eine über die HTTP API gestellte Frage hat keine gespeicherte Antwort und wird übersprungen |
| **Verwerfen** | Markiert ein Thema als eines, das keinen Inhalt braucht. Ein verworfenes Thema behält die Fragen, die zu ihm gehören, und kommt deshalb nicht als neues Thema zurück. **Wieder öffnen** macht das rückgängig |

Nachdem du das Dokument hinzugefügt hast, führe ein Eval über das Dataset aus.
Die Fälle, die wegen des fehlenden Wissens fehlgeschlagen sind, sollten jetzt
bestehen.

## Den fehlenden Inhalt entwerfen { #drafting-the-missing-content }

**Fehlenden Inhalt entwerfen** in einem geöffneten Thema bittet ein Modell, die
Passage oder den FAQ-Eintrag zu schreiben, der der Wissensbasis fehlt. Das ist
ein Run des **Knowledge gap drafter**, eines
[System-Agents](concepts.md#system-agents), den jede Organisation hat. Er sieht
die 20 neuesten Fragen des Themas: was jede Person gefragt hat, wonach der Agent
gesucht und was er gefunden hat, welche Antwort die Person bekam und jeden
Kommentar zu einer negativen Bewertung.

Der Entwurf bleibt beim Thema, als Entwurf gekennzeichnet, mit einem Link zu
seinem Run. Du kannst ihn kopieren oder als Markdown herunterladen. Er wird nie
der Wissensdatenbank hinzugefügt. Der Entwerfer kennt die Fakten deines Unternehmens nicht: Wo eine
Antwort eine Zahl, ein Datum oder eine Regel braucht, schreibt er einen
Platzhalter in eckigen Klammern, den du ausfüllst. Ein neuer Entwurf ersetzt den
alten. Wer den Drafter bearbeiten darf, findet am Entwurf **Anweisungen des
Drafters bearbeiten** und den Drafter selbst unter **System-Agents** auf der
Seite Agents.

Ein Entwurf nennt seine Quellen: die Dokumente der Wissensbasis, auf die er
sich stützt, und die Fragen des Themas, die er beantwortet. Jede wird geprüft,
bevor der Entwurf gespeichert wird - ein Dokument muss zur Wissensbasis des
Themas gehören, eine Frage zum Thema - und eine, die das nicht tut, wird
weggelassen, nie angezeigt und beim Entwurf gezählt. Höchstens 12 Quellen
werden behalten. Eine später gelöschte Quelle wird nicht mehr angezeigt.

Ein Entwurf ist ein Modell-Run wie jeder andere. Er wird verweigert, solange die
Organisation die [KI-Unterstützung](governance.md#ai-assistance) ausgeschaltet
hat, und das ist sie, bis jemand mit `org:settings` sie einschaltet; bis dahin
sagt das Thema es, mit einem Link zum Schalter für den, der ihn ändern darf. Vor
dem Modellaufruf werden das Budget des Entwerfers und das der
Organisation geprüft, und seine Kosten erscheinen in Activity. Das Gruppieren
von Fragen zu Themen lässt kein Modell etwas schreiben und läuft deshalb
unabhängig vom Schalter.

## Zugriff { #access }

Ein Thema besteht aus den Fragen von Menschen, daher braucht das Lesen von
Lücken `runs:view`, die Berechtigung, die in Activity jeden Run der
Organisation liest. Ein Mitglied ohne sie sieht weder den Tab noch das Widget,
und die API verweigert ihm den Zugriff.

| Um | Brauchst du |
|---|---|
| Die Lücken einer Wissensdatenbank zu lesen | `runs:view` und `collections:view` auf dieser Wissensdatenbank |
| Die Lücken eines Agents zu lesen | `runs:view` und `agents:view` auf dem Agent; Themen von Wissensdatenbanken, die du nicht lesen darfst, werden ausgelassen |
| Zu verwerfen, wieder zu öffnen oder neu zu gruppieren | `runs:view` und `collections:edit` auf der Wissensdatenbank, aus deiner Rolle oder einem Bearbeitungs-Grant darauf |
| Ein Thema zu einem Dataset hinzuzufügen | `runs:view` und `datasets:edit` auf dem Dataset |
| Den fehlenden Inhalt zu entwerfen | `runs:view`, `collections:edit` auf der Wissensdatenbank und `agents:run` auf dem Knowledge gap drafter |
| Antworten zu prüfen | `runs:view`, `collections:edit` auf der Wissensdatenbank und `agents:run` auf dem Knowledge gap classifier |

Eine Wissensdatenbank, ein Agent, ein Thema oder ein Dataset, auf das du keinen
Zugriff hast, antwortet mit „nicht gefunden“, ebenso eines aus einer anderen
Organisation. Siehe [Berechtigungen](permissions.md).

## Personenbezogene Daten { #personal-data }

Eine gespeicherte Suche ist Inhalt von Nutzern: Der Agent hat sie aus dem
formuliert, was jemand gefragt hat. Sie wird mit dem Run gelöscht, in dem sie
entstanden ist, und mit der Unterhaltung, aus der sie stammt. Das Löschen einer
Person löscht die Suchen, die beim Beantworten ihrer Fragen gemacht wurden,
auch in Runs ohne Unterhaltung. Ihr Export enthält sie.

Jede Suche wird gespeichert, ein Treffer wie ein Fehltreffer, damit ein
geänderter Schwellenwert auch für die bereits gemachten Suchen gilt. Keine
überlebt ihren Run: Die Klasse der Runs in der
[Aufbewahrung](governance.md#retention) löscht sie mit ihm.

Ein Thema kopiert keine Fragen. Name, Beispiele und Anzahl werden aus den
Suchen gelesen, die es noch enthält. Werden diese Suchen gelöscht, bleibt dem
Thema nichts, und der nächste Gruppierungslauf entfernt es samt Entwurf. Der
Entwurf ist der einzige Text, den ein Thema selbst hält: Ein Modell schreibt
ihn aus den Fragen, er kann also wiederholen, was jemand geschrieben hat.
Zugangsdaten, die er wiederholt, werden vor dem Speichern geschwärzt. Das
Entwerfen schickt die Fragen, Antworten und Kommentare an den Modellanbieter des
Entwerfers. Siehe [Datenschutz](data-protection.md#where-personal-data-lives).

Eine aus einer Antwort gelesene Frage wird wie eine Suche aufbewahrt: Sie hält
die Frage der Person und geht mit ihrem Run und ihrer Conversation. Das Prüfen
von Antworten schickt Fragen, Antworten und Kommentare zu negativen Bewertungen
an den Modellanbieter des Klassifizierers. Von jeder gelesenen Antwort bleiben
nur ihr Urteil und der Run des Klassifizierers, kein Text.

## Was Lücken noch nicht erkennen { #limits }

Antworten werden nur gelesen, wenn jemand sie prüft, und nur aus den letzten 30
Tagen. Runs über die HTTP-API behalten keine Antwort, also wird eine dort
gestellte Frage nur dann zur Lücke, wenn ihre Suche ein Fehltreffer war. Eine
ohne Kommentar negativ bewertete Antwort wird auf das gelesen, was der Agent
gesagt hat, nicht auf die Bewertung.
