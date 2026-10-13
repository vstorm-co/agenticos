---
source_sha: "2d253005d633"
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

Eine Lücke sagt, was fehlt. Sie fügt einer Collection nie selbst etwas hinzu.
Ein Mensch schreibt oder findet das fehlende Dokument und fügt es hinzu. Vorher
lassen sich die Fragen des Themas in Fälle eines [Datasets](datasets.md)
umwandeln, damit ein Eval zeigt, ob das neue Dokument die Antworten verändert
hat.

## Wie eine Frage zur Lücke wird { #how-a-question-becomes-a-gap }

Jedes Mal, wenn ein Agent während eines Runs seine Wissensbasis durchsucht,
zeichnet die Plattform die Suche auf: die Anfrage, die der Agent geschickt hat,
die durchsuchten Collections, wie viele Passagen zurückkamen und wie ähnlich die
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

Gespeichert werden nur Suchen, die ein Agent während seines Runs macht. Eine
Suche über `/rag/search` der HTTP API oder eine Vorschau auf der Seite der
Collection wird nicht gespeichert.

## Themen { #topics }

Fehltreffer werden nach der Bedeutung der Anfrage zu **Themen** gruppiert. Alle
15 Minuten nimmt ein Hintergrundlauf die neuen Fehltreffer jeder Wissensbasis,
bettet sie mit dem eigenen Embedding-Modell dieser Collection ein und legt jeden
in das nächste Thema dieser Wissensbasis oder beginnt ein neues. Ein Lauf bettet
höchstens 500 Fehltreffer pro Wissensbasis ein; der Rest wartet auf den
nächsten. Eine Wissensbasis ohne neue Fehltreffer kostet keinen
Embedding-Aufruf.

- Eine Suche über zwei Collections wird zu einer Frage in einem Thema jeder der
  beiden.
- Eine Collection, die auf ein anderes Embedding-Modell umgestellt wurde,
  beginnt neue Themen, weil Vektoren zweier Modelle nicht vergleichbar sind.
- Ein Thema behält seine Identität, wenn Fragen hinzukommen, sodass eine
  Entscheidung, die du dazu getroffen hast, weiter gilt.

**Jetzt gruppieren** im Tab der Wissenslücken einer Collection führt den Lauf
für diese Wissensbasis sofort aus, statt auf den Zeitplan zu warten. Bis eine
Frage einem Thema zugeordnet ist, zählt der Tab sie als noch nicht gruppiert.

## Lücken lesen { #reading-gaps }

Lücken erscheinen an drei Stellen:

- im Tab **Wissenslücken** einer Collection: alle Themen dieser Wissensbasis;
- im Tab **Wissenslücken** eines Agents: nur die Fragen dieses Agents, in den
  Wissensbasen, die du lesen darfst;
- im Dashboard-Widget **Wissenslücken**: die am häufigsten gestellten Themen in
  der ganzen Organisation.

Ein Thema zeigt, wie oft es gestellt wurde, wann zuletzt, welche Agents es
gestellt haben, und bis zu drei seiner Fragen. Öffne es, um die neuesten Fragen
zu sehen: was die Person gefragt hat, wonach der Agent gesucht hat, wie nah die
nächste Passage war und den Kommentar aller, die die Antwort negativ bewertet
haben.

## Was mit einer Lücke zu tun ist { #acting-on-a-gap }

| Aktion | Was sie tut |
|---|---|
| Fehlendes Dokument hinzufügen | Lade es in die Collection hoch oder in eine Quelle, aus der die Collection synchronisiert. Nichts wird für dich hinzugefügt |
| **Zum Dataset hinzufügen** | Wandelt die neuesten Fragen des Themas (bis zu 200) in Fälle eines Datasets deiner Wahl um, als eine neue Version. Jeder Fall ist die Frage der Person, mit der Antwort des Agents als Gegenbeispiel. Eine über die HTTP API gestellte Frage hat keine gespeicherte Antwort und wird übersprungen |
| **Verwerfen** | Markiert ein Thema als eines, das keinen Inhalt braucht. Ein verworfenes Thema behält die Fragen, die zu ihm gehören, und kommt deshalb nicht als neues Thema zurück. **Wieder öffnen** macht das rückgängig |

Nachdem du das Dokument hinzugefügt hast, führe ein Eval über das Dataset aus.
Die Fälle, die wegen des fehlenden Wissens fehlgeschlagen sind, sollten jetzt
bestehen.

## Zugriff { #access }

Ein Thema besteht aus den Fragen von Menschen, daher braucht das Lesen von
Lücken `runs:view`, die Berechtigung, die in Activity jeden Run der
Organisation liest. Ein Mitglied ohne sie sieht weder den Tab noch das Widget,
und die API verweigert ihm den Zugriff.

| Um | Brauchst du |
|---|---|
| Die Lücken einer Collection zu lesen | `runs:view` und `collections:view` auf dieser Collection |
| Die Lücken eines Agents zu lesen | `runs:view` und `agents:view` auf dem Agent; Themen von Collections, die du nicht lesen darfst, werden ausgelassen |
| Zu verwerfen, wieder zu öffnen oder neu zu gruppieren | `runs:view` und `collections:edit` auf der Collection |
| Ein Thema zu einem Dataset hinzuzufügen | `runs:view` und `datasets:edit` auf dem Dataset |

Eine Collection, ein Agent, ein Thema oder ein Dataset, auf das du keinen
Zugriff hast, antwortet mit „nicht gefunden“, ebenso eines aus einer anderen
Organisation. Siehe [Berechtigungen](permissions.md).

## Personenbezogene Daten { #personal-data }

Eine gespeicherte Suche ist Inhalt von Nutzern: Der Agent hat sie aus dem
formuliert, was jemand gefragt hat. Sie wird mit dem Run gelöscht, in dem sie
entstanden ist, und mit der Unterhaltung, aus der sie stammt. Das Löschen einer
Person löscht die Suchen, die beim Beantworten ihrer Fragen gemacht wurden,
auch in Runs ohne Unterhaltung. Ihr Export enthält sie.

Ein Thema kopiert keinen Text. Name, Beispiele und Anzahl werden aus den
Suchen gelesen, die es noch enthält. Werden diese Suchen gelöscht, bleibt dem
Thema nichts, und der nächste Gruppierungslauf entfernt es. Siehe
[Datenschutz](data-protection.md#where-personal-data-lives).

## Was Lücken noch nicht erkennen { #limits }

Lücken entstehen nur aus der Suche. Eine Antwort, in der der Agent gesagt hat,
dass er es nicht weiß, oder eine negativ bewertete Antwort mit einem Kommentar
über fehlende Informationen wird nicht von selbst erkannt. Das zu erkennen
braucht ein Modell und wird in
[#2135](https://github.com/vstorm-co/agenticos/issues/2135) verfolgt. Gehört eine
negativ bewertete Antwort zu einem Run, dessen Suche ein Fehltreffer war, wird
ihr Kommentar bei der Frage angezeigt.
