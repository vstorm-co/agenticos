---
source_sha: "cab676070fd6"
title: "Wissenslücken"
description: "Wissenslücken zeigen die Fragen, zu denen ein Agent in seiner Wissensbasis nichts Passendes gefunden hat, nach Thema gruppiert, damit klar ist, welches Dokument fehlt."
---

# Wissenslücken { #knowledge-gaps }

Viele schlechte Antworten liegen nicht an den Anweisungen des Agents. Die
Wissensbasis enthält die Antwort nicht, und keine Änderung am Prompt behebt das.
**Wissenslücken** zeigen genau diese Fragen: die, zu denen ein Agent seine
[Wissensbasis](file-processing.md) durchsucht und nichts Passendes gefunden
hat, nach Thema gruppiert, mit der Häufigkeit jeder Frage und den Agents, die
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
haben.

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
| Den fehlenden Inhalt zu entwerfen | `runs:view`, `collections:view` auf der Wissensdatenbank und `agents:run` auf dem Knowledge gap drafter |

Eine Wissensdatenbank, ein Agent, ein Thema oder ein Dataset, auf das du keinen
Zugriff hast, antwortet mit „nicht gefunden“, ebenso eines aus einer anderen
Organisation. Siehe [Berechtigungen](permissions.md).

## Personenbezogene Daten { #personal-data }

Eine gespeicherte Suche ist Inhalt von Nutzern: Der Agent hat sie aus dem
formuliert, was jemand gefragt hat. Sie wird mit dem Run gelöscht, in dem sie
entstanden ist, und mit der Unterhaltung, aus der sie stammt. Das Löschen einer
Person löscht die Suchen, die beim Beantworten ihrer Fragen gemacht wurden,
auch in Runs ohne Unterhaltung. Ihr Export enthält sie.

Ein Thema kopiert keine Fragen. Name, Beispiele und Anzahl werden aus den
Suchen gelesen, die es noch enthält. Werden diese Suchen gelöscht, bleibt dem
Thema nichts, und der nächste Gruppierungslauf entfernt es samt Entwurf. Der
Entwurf ist der einzige Text, den ein Thema selbst hält: Ein Modell schreibt
ihn aus den Fragen, er kann also wiederholen, was jemand geschrieben hat.
Zugangsdaten, die er wiederholt, werden vor dem Speichern geschwärzt. Das
Entwerfen schickt die Fragen, Antworten und Kommentare an den Modellanbieter des
Entwerfers. Siehe [Datenschutz](data-protection.md#where-personal-data-lives).

## Was Lücken noch nicht erkennen { #limits }

Lücken entstehen nur aus der Suche. Eine Antwort, in der der Agent gesagt hat,
dass er es nicht weiß, oder eine negativ bewertete Antwort mit einem Kommentar
über fehlende Informationen wird nicht von selbst erkannt. Das zu erkennen
braucht ein Modell und wird in
[#2135](https://github.com/vstorm-co/agenticos/issues/2135) verfolgt. Gehört eine
negativ bewertete Antwort zu einem Run, dessen Suche ein Fehltreffer war, wird
ihr Kommentar bei der Frage angezeigt.
