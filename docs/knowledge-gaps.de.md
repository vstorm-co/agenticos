---
source_sha: "f929a969ec73"
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
Ein Mensch schreibt den fehlenden Inhalt im Thema - ein Modell kann ihn
entwerfen - und fügt ihn der Wissensdatenbank als Dokument hinzu. Vorher
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
API, eine Vorschau auf der Seite der Wissensdatenbank, eine Suche eines Eval-Runs
und eine aus dem Test eines Entwurfs im Builder werden nicht gespeichert. Von einer Anfrage werden die ersten 1.000 Zeichen
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
jede Antwort mit ihrer Frage, den Kommentaren aller, die sie negativ bewertet
haben, und den Anweisungen und [Kontextdateien](context.md) der Agent-Version,
die sie gegeben hat - denen, die die Person lesen darf, die die Prüfung
angefordert hat -, und entscheidet eines von vier Dingen, mit einem Satz zur
Begründung:

| Urteil | Wann |
|---|---|
| Der Agent wusste es nicht | Die Antwort sagt, in beliebigen Worten und Sprachen, dass der Agent es nicht wusste oder die Information nicht fand. Eine berechtigte Frage, die der Agent abgelehnt hat, weil er nichts dazu hatte, gehört hierher, nicht zu den Ablehnungen |
| Informationen fehlten | Ein Kommentar zu einer negativen Bewertung sagt, dass Informationen fehlten, veraltet oder unvollständig waren |
| Zu Recht abgelehnt | Die Frage verlangte, was die Regeln oder der Zweck des Agents nicht erlauben - seine Anweisungen zu ignorieren, eine Ausnahme zu gewähren oder bei etwas zu helfen, wofür er nicht da ist - und der Agent hat abgelehnt. Keine Lücke, und die Fehltreffer unter den Suchen dieses Runs zählen ebenfalls nicht mehr als Lücken - in dieser Wissensdatenbank und in einer anderen, die eine verfehlte Suche mit abdeckte, denn eine Ablehnung betrifft die Anfrage, nicht eine Wissensdatenbank |
| Keine Lücke | Alles andere: eine richtige Antwort, die Ablehnung von etwas, das die Regeln erlauben, ein Kommentar zu Ton, Länge oder einem Fehler. Eine Antwort, die eine Richtlinie oder Regel falsch angewendet hat, ist keine Lücke: Die Regel war da, und das ist ein Fehler, den man behebt - ebenso eine Antwort, deren Agent in seinen Anweisungen oder Kontextdateien stehen hat, was sie brauchte. Ein Kommentar, dass die Information veraltet war, ist eine Lücke |

Eine Antwort mit einem der ersten beiden Urteile wird zu einer Frage in den
Themen der Wissensbasis und wie eine fehlgeschlagene Suche gruppiert. Im Thema
steht, welcher der beiden Fälle es ist, statt einer Suche.

Eine Antwort wird gelesen, wenn ihr Run aus den letzten 30 Tagen abgeschlossen
ist und entweder die Wissensbasis durchsucht hat oder auf einer an sie
gebundenen Agent-Version lief, bewertet oder nicht: Eine Antwort, in der der
Agent es nicht wusste, bewertet oft niemand. Ein Run, dessen Suche schon ein Fehltreffer war,
wird ebenfalls gelesen, damit eine berechtigte Ablehnung seinen Fehltreffer aus
den Lücken nimmt; sonst zählt er weiterhin einmal, als dieser Fehltreffer. Runs über die HTTP-API behalten keine
Antwort, und Eval-Runs, deren Fragen wiederholt oder erzeugt sind, werden nie
gelesen. Tests eines Entwurfs im Builder, delegierte Runs und Runs, deren
Starter kein Konto mehr hat, ebenso wenig.

Eine Prüfung gehört zu einer Wissensbasis: Was sie findet, ist eine Lücke nur
dieser Basis. Eine Antwort, deren Run zwei Wissensbasen durchsucht hat, wird
erneut gelesen, wenn die andere geprüft wird.

Eine Prüfung liest bis zu 100 Antworten, 20 je Run des Klassifizierers. Jeder
Run wird gegen das Budget des Klassifizierers und der Organisation geprüft,
bevor das Modell aufgerufen wird, und steht in der Aktivität unter der Person,
die gefragt hat: Wählen Sie **Jede Oberfläche, Evals eingeschlossen**, um ihn zu
sehen. Jede gelesene Antwort wird gemerkt, egal mit welchem Urteil, also wird
für keine zweimal bezahlt. Eine als „keine Lücke“ gelesene Antwort wird erst
nach einer neuen negativen Bewertung mit Kommentar erneut gelesen. Eine Prüfung
hält bei einem Run an, der ohne Antwort endet, etwa einem, den ein
aufgebrauchtes Budget verweigert, und behält, was sie gelesen hat.

Für eine Wissensbasis läuft immer nur eine Prüfung, als Hintergrund-Job unter
Admin → Background jobs: Ein Worker, der darunter stehen bleibt, hinterlässt den
Job dort beendet, nie spurlos verloren, und was die Prüfung gelesen hat, bleibt
gelesen.

Eine Verbesserungssitzung - im Hintergrund ausgeführtes
[Verbessern](authoring.md) - liest die schlechten Antworten, die sie gefunden
hat, auf dieselbe Weise, nur diese Antworten und unabhängig von ihrem Alter, und
ordnet jede nach ihren Urteilen ein: fehlendes Wissen, wo einer Wissensbasis
Inhalt fehlte, nichts zu beheben, wo der Agent zu Recht abgelehnt hat, und sonst
ein Fehler des Agents. Die Antworten mit fehlendem Wissen fallen aus dem heraus,
was der Authoring-Assistent liest, und die Sitzung entwirft stattdessen ihre
Themen - nur ein Thema, nach dem mindestens zwei verschiedene Personen gefragt
haben, höchstens drei pro Runde. Die Runs eines Evals werden nie gelesen, also
auch kein zurückgehaltener Fall.

## Themen { #topics }

Fehltreffer werden nach der Bedeutung der Anfrage zu **Themen** gruppiert. Alle
15 Minuten nimmt ein Hintergrundlauf die neuen Fehltreffer jeder Wissensbasis,
bettet sie mit dem eigenen Embedding-Modell dieser Wissensdatenbank ein und legt jeden
in das nächste Thema dieser Wissensbasis oder beginnt ein neues. Ein Lauf bettet
höchstens 500 Fehltreffer pro Wissensbasis ein; der Rest wartet auf den
nächsten. Eine Wissensbasis ohne neue Fehltreffer kostet keinen
Embedding-Aufruf.

Ein Fehltreffer kommt nur dann in das nächste Thema, wenn er ihm mindestens so
ähnlich ist wie `KNOWLEDGE_GAP_TOPIC_SIMILARITY`; sonst beginnt er ein neues.

| Einstellung | Standard | Was sie entscheidet |
|---|---|---|
| `KNOWLEDGE_GAP_TOPIC_SIMILARITY` | `0.55` | Die Kosinus-Ähnlichkeit, die ein Fehltreffer zu einem Thema braucht, um ihm beizutreten. Welchen Wert Fragen zu einer Sache erreichen, hängt vom Embedding-Modell ab: bei OpenAIs `text-embedding-3`-Modellen etwa 0,5 bis 0,7. Erhöhe sie, wenn nicht zusammengehörige Fragen ein Thema teilen, senke sie, wenn eine Sache immer neue beginnt. Der Standard ist auf diese Modelle abgestimmt; ein Embedding-Modell hinter einem OpenAI-kompatiblen Endpunkt, etwa bge oder e5, bewertet selbst nicht zusammengehörige Fragen hoch, also erhöhe ihn dort |

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

Ein Thema zeigt, wie oft und von wie vielen Personen es gestellt wurde, wann
zuletzt, welche Agents es gestellt haben, und bis zu drei seiner Fragen. Wer
über einen Channel gefragt hat, zählt nach seinem Chat-Konto; alle, die anonym
gefragt haben, über ein Widget oder ohne Person hinter dem Run, zählen als eine
Person. Öffne es, um die neuesten Fragen
zu sehen: was die Person gefragt hat, wonach der Agent gesucht hat, wie nah die
nächste Passage war und den Kommentar aller, die die Antwort negativ bewertet
haben. Eine aus einer Antwort gelesene Frage sagt, ob der Agent es nicht wusste
oder ein Leser schrieb, dass Informationen fehlten.

## Was mit einer Lücke zu tun ist { #acting-on-a-gap }

Ein geöffnetes Thema hat einen Editor: einen Titel und den Inhalt in Markdown,
leer oder mit dem Entwurf des Themas gefüllt. **Zum Dataset hinzufügen** und
**Verwerfen** stehen im Menü **…** eines Themas, in seiner Zeile und im Thema
selbst.

| Aktion | Was sie tut |
|---|---|
| **Zu** *Wissensdatenbank* **hinzufügen** | Fügt Titel und Inhalt der Wissensdatenbank des Themas als Markdown-Dokument hinzu, auf demselben Weg wie ein Upload, und markiert das Thema als davon **abgedeckt**. Wird verweigert, solange eine Angabe noch auszufüllen ist oder solange etwas eine Person identifizieren könnte und du es nicht bestätigt hast (siehe [Personenbezogene Daten](#personal-data)) |
| **Speichern** | Behält Titel und Inhalt am Thema, ohne sie irgendwo hinzuzufügen |
| **Zum Dataset hinzufügen** | Wandelt die neuesten Fragen des Themas (bis zu 200) in Fälle eines Datasets um, das du ändern darfst, als eine neue Version. Jeder Fall ist die Frage der Person, mit der Antwort des Agents als Gegenbeispiel. Eine über die HTTP API gestellte Frage hat keine gespeicherte Antwort und wird übersprungen |
| **Verwerfen** | Markiert ein Thema als eines, das keinen Inhalt braucht. Ein verworfenes Thema behält die Fragen, die zu ihm gehören, und kommt deshalb nicht als neues Thema zurück. **Wieder öffnen** macht das rückgängig |

Ein abgedecktes Thema sagt, welches Dokument es abdeckt, behält wie ein
verworfenes die Fragen, die zu ihm gehören, und steht unter **Abgedeckt**. Wird
dieses Dokument gelöscht oder scheitert seine Ingestion, ist das Thema wieder
offen; ein verworfenes Thema wird wieder geöffnet, bevor Inhalt dafür entsteht. **Wieder öffnen** bei
einem abgedeckten Thema lässt das Dokument in der Wissensdatenbank. Das Dokument
hält fest, aus welchem Thema und von wem es hinzugefügt wurde, und jede
Hinzufügung steht im Audit-Log als `knowledge_gap.content_added`.

Du kannst ein Dokument auch selbst hochladen oder es einer Quelle hinzufügen,
aus der die Wissensdatenbank synchronisiert. Nachdem du den Inhalt hinzugefügt
hast, führe ein Eval über das Dataset aus. Die Fälle, die wegen des fehlenden
Wissens fehlgeschlagen sind, sollten jetzt bestehen.

## Den fehlenden Inhalt entwerfen { #drafting-the-missing-content }

**Fehlenden Inhalt entwerfen** in einem geöffneten Thema bittet ein Modell, die
Passage oder den FAQ-Eintrag zu schreiben, der der Wissensbasis fehlt. Das ist
ein Run des **Knowledge gap drafter**, eines
[System-Agents](concepts.md#system-agents), den jede Organisation hat. Er sieht
die 20 neuesten Fragen des Themas: was jede Person gefragt hat, wonach der Agent
gesucht und was er gefunden hat, welche Antwort die Person bekam und jeden
Kommentar zu einer negativen Bewertung. Was Personen identifiziert, wird
vorher entfernt (siehe [Personenbezogene Daten](#personal-data)); aus dem, was
die Suche gefunden hat, dem eigenen Text der Wissensdatenbank, nur
personenbezogene Daten, sodass seine Zahlen bleiben. Er sieht
außerdem die [Kontextdateien](context.md), die die Agents des Themas in ihren
veröffentlichten Versionen lesen, soweit du sie lesen darfst, damit der Entwurf
den Regeln folgt, denen die Agents schon folgen.

Der Entwurf füllt den Editor des Themas, mit einem Link zu seinem Run. Du
kannst ihn kopieren oder als Markdown herunterladen, und in die
Wissensdatenbank kommt er erst, wenn ihn jemand hinzufügt. Der Entwerfer kennt
die Fakten deines Unternehmens nicht: Wo eine Antwort eine Zahl, ein Datum oder
eine Regel braucht, schreibt er `{{what to fill in}}`, und der Editor listet
jede solche Stelle auf, bis sie ersetzt ist.

Wenn eine Kontextdatei oder ein Dokument die Fragen schon beantwortet, sagt der
Drafter das, und das Thema nennt diese Quelle: Verwirf dann das Thema, statt
Inhalt hinzuzufügen. Ein neuer Entwurf ersetzt den alten. Wer den Drafter bearbeiten darf, findet am Entwurf **Anweisungen des
Drafters bearbeiten** und den Drafter selbst unter **System-Agents** auf der
Seite Agents.

Ein Entwurf nennt seine Quellen: die Dokumente der Wissensbasis, auf die er
sich stützt, die Kontextdateien, denen er folgt, und die Fragen des Themas, die
er beantwortet. Jede wird geprüft, bevor der Entwurf gespeichert wird - ein
Dokument muss zur Wissensbasis des Themas gehören, eine Frage zum Thema, eine
Kontextdatei muss eine sein, die du lesen darfst - und eine, die das nicht tut,
wird weggelassen, nie angezeigt und beim Entwurf gezählt. Höchstens 12 Quellen
werden behalten. Eine später gelöschte Quelle wird nicht mehr angezeigt.

Änderst du einen Entwurf im Editor, ist er dein Inhalt: Sein Run und seine
Quellen werden nicht mehr gezeigt, weil das, worauf sich das Modell berief, nicht
mehr für ihn spricht.

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
| Den Inhalt eines Themas zu schreiben, zu speichern oder hinzuzufügen | `runs:view` und `collections:edit` auf der Wissensdatenbank, aus deiner Rolle oder einem Bearbeitungs-Grant darauf |
| Antworten zu prüfen | `runs:view`, `collections:edit` auf der Wissensdatenbank und `agents:run` auf dem Knowledge gap classifier |

Eine Prüfung der Antworten läuft später mit deiner Rolle, also startest du sie
nur persönlich: nicht über einen API-Schlüssel und nicht, während ein
Administrator dich impersoniert.

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
Thema nichts, und der nächste Gruppierungslauf entfernt es samt Entwurf.

Der Entwurf ist der einzige Text, den ein Thema selbst hält, geschrieben von
einem Modell oder einem Menschen. Zugangsdaten darin werden vor dem Speichern
geschwärzt. Das Entwerfen schickt die Fragen, Antworten und Kommentare an den
Modellanbieter des Entwerfers, nachdem entfernt wurde, was Personen
identifiziert: E-Mail-Adressen, Telefon-, Karten- und Bankkontonummern sowie
jede Zahl oder jeder Code mit vier oder mehr Ziffern oder mit drei Ziffern und
einem Buchstaben, etwa eine Bestellnummer. Eine Angabe wie „30 Tage“ oder
„$500“ bleibt. Nichts, was ein Mensch schreibt, wird verändert. Siehe
[Datenschutz](data-protection.md#where-personal-data-lives).

Das Löschen einer Person entfernt die Entwürfe, die ein Modell aus ihren Fragen
geschrieben hat. Inhalt, den ein Mensch geschrieben oder geändert hat, bleibt,
ebenso ein daraus hinzugefügtes Dokument.

Ein Dokument, das aus einem Thema hinzugefügt wird, erreicht alle, denen die
Agents seiner Wissensdatenbank antworten. Deshalb wird der Inhalt vor dem
Hinzufügen auf personenbezogene Daten geprüft und auf jede solche Zahl und
jeden solchen Code, den er aus den Fragen, Antworten oder Kommentaren des
Themas wiederholt, es sei denn, eine Kontextdatei der Agents des Themas nennt
ihn ebenfalls. Was gefunden wird, steht im Thema, und das Hinzufügen wartet,
bis du es bestätigst.

Der Audit-Eintrag hält fest, wie viel markiert wurde und
dass es bestätigt wurde, nicht was. Das Dokument bleibt, wenn das Thema, die
Person, die es hinzugefügt hat, oder eine Person, deren Frage es geprägt hat,
gelöscht wird: Jemand hat geprüft und bestätigt, was es sagt.

Eine aus einer Antwort gelesene Frage wird wie eine Suche aufbewahrt: Sie hält
die Frage der Person und geht mit ihrem Run und ihrer Conversation. Das Prüfen
von Antworten schickt Fragen, Antworten und Kommentare zu negativen Bewertungen
an den Modellanbieter des Klassifizierers. Von jeder gelesenen Antwort bleiben
ihr Urteil, der Run des Klassifizierers und seine Begründung in einem Satz, die
mit der Antwort geht.

## Was Lücken noch nicht erkennen { #limits }

Antworten werden nur gelesen, wenn jemand sie prüft, und nur aus den letzten 30
Tagen. Runs über die HTTP-API behalten keine Antwort, also wird eine dort
gestellte Frage nur dann zur Lücke, wenn ihre Suche ein Fehltreffer war. Eine
ohne Kommentar negativ bewertete Antwort wird auf das gelesen, was der Agent
gesagt hat, nicht auf die Bewertung.

Namen werden weder aus dem entfernt, was der Drafter liest, noch in Inhalten
zum Hinzufügen markiert: Nichts hier erkennt einen Namen. Prüfe einen Entwurf
darauf, bevor du ihn hinzufügst.
