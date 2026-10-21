---
source_sha: "fa7c64b3a7b7"
title: "Authoring-Assistent"
description: "Der Authoring-Assistent liest, was Leute negativ bewertet haben und wie Runs endeten, und schlägt Änderungen an Anweisungen, Tool-Beschreibungen und Skills vor. Über jede entscheidet ein Mensch."
---

# Authoring-Assistent { #authoring-assistant }

Der **Authoring-Assistent** verbessert Agents anhand von Belegen. Er liest, was
Leute negativ bewertet haben und wie Runs endeten, und schlägt Änderungen an den
Anweisungen eines Agents vor, an den Namen und Beschreibungen seiner Tools und an
den Skills, die er nutzt. Er ändert nie etwas von sich aus: Jeder Vorschlag
wartet auf einen Menschen, ein angenommener landet im [Draft](concepts.md), und
nichts erreicht irgendwen, bevor der Draft veröffentlicht ist.

Er tut drei Dinge:

- Einen Agent **verbessern**: Änderungen aus seinen negativ bewerteten und
  fehlgeschlagenen Runs vorschlagen.
- Ihre eigenen Änderungen **prüfen**: den Draft mit der veröffentlichten Version
  anhand derselben Belege vergleichen und sagen, was die Änderungen verbessern,
  riskieren und entfernt haben.
- **Einen Skill verbessern**: einen neuen Inhalt aus den Runs vorschlagen, die ihn
  geöffnet haben.

Der Assistent ist ein eigener [System-Agent](datasets.md#judge), aufgeführt mit
den übrigen System-Agents der Organisation. Seine Anweisungen lassen sich wie die
jedes Agents bearbeiten, und seine Runs sind gewöhnliche Runs: budgetiert,
bepreist und in Activity aufgeführt.

## Was er liest { #what-it-reads }

Der Assistent hat keine Tools. Was er liest, wird für ihn zusammengestellt, aus
den Runs des Agents der letzten 30 Tage:

- negativ bewertete Antworten, die mit Kommentar zuerst;
- Runs, die fehlgeschlagen sind, an ein Budget stießen oder von einem Guardrail
  blockiert wurden;
- positiv bewertete Antworten, als Kontrast.

Ein unbewerteter, erfolgreicher Run sagt nichts aus und wird nicht gelesen.
Ebenso wenig ein Test aus dem Testpanel des Builders oder der Run eines
Delegierten.

**Er liest nie Evals.** Runs, die einen [Eval](evals.md)-Fall beantwortet haben,
die Runs des Bewerters und die eigenen Runs des Assistenten bleiben außen vor,
und Bewertungen sieht er nie. Eine Änderung, die von Evals geprüft wird, darf
nicht an die Fälle angepasst sein, die sie prüfen.

Gibt es mehr zu lesen, als in eine Anfrage passt, werden die Runs zuerst in
Gruppen gelesen, und die Vorschläge entstehen aus dem, was jede Gruppe zeigte.

### Jedes Zitat wird geprüft { #every-quote-is-checked }

Jeder Vorschlag hat eine Begründung und die Belege dahinter: die Runs, auf die er
sich stützt, und Zitate daraus. Bevor jemand einen Vorschlag sieht, wird jedes
Zitat Wort für Wort mit dem Run abgeglichen, den es nennt. Ein Zitat, das dort
nicht steht, ein Run, der nicht zu den gelesenen gehört, und alles über zwölf
Einträge oder sechshundert Zeichen hinaus wird verworfen, und der Vorschlag sagt,
wie viele es waren. Wer kein `runs:view` hat, sieht, auf welche Runs sich ein
Vorschlag stützt, aber nicht, was darin gesagt wurde.

## Vorschläge { #suggestions }

Verbessern und Prüfen öffnen die **Assistentenleiste** auf dem Build-Tab des
Agents. Jeder Vorschlag zeigt die Passage, die er ändert, in ihrem Umfeld, die
Begründung und die Belege, und über jeden wird einzeln entschieden:

| Aktion | Was passiert |
|---|---|
| **Annehmen** | Die Änderung wird in den Draft geschrieben. Nichts wird veröffentlicht. |
| **Bearbeiten** | Ihre eigene Formulierung wird statt des Vorschlags angenommen. |
| **Verwerfen** | Festgehalten; eine spätere Anfrage schlägt es nicht wieder vor. |
| **Rückgängig** | Kehrt die Entscheidung um, solange sie noch zum Draft passt. |

Ein Vorschlag verankert sich daran, wo seine Passage stand und was sie umgab,
nicht am Text allein, sodass eine Zeile, die zweimal vorkommt, dort geändert
wird, wo es gemeint war. Hat sich der Draft weiterbewegt - die Passage wurde
entfernt oder eine Tool-Beschreibung von Hand geändert -, sagt der Vorschlag, dass
er **nicht mehr zum Draft passt**, und lässt sich nur verwerfen. Rückgängig
verweigert sich ebenso, wenn der angenommene Text danach von Hand bearbeitet
wurde: Es würde diese Änderung verwerfen.

Ein neueres Verbessern ersetzt die wartenden Vorschläge; Prüfen fügt seine
stattdessen hinzu. Das Veröffentlichen des Drafts schließt sie: Ihre
Entscheidungen sind endgültig, und die Leiste behält sie als Protokoll.

### Mit Evals prüfen { #check-with-evals }

**Mit Evals prüfen** führt ein [Dataset](datasets.md) gegen den Draft aus, wie er
mit allen wartenden Vorschlägen wäre, neben der veröffentlichten Version im
selben [Eval Run](evals.md#a-baseline-in-the-same-run). Durch die Prüfung wird
nichts angenommen, und der Draft ändert sich nicht.

Die Fälle aus den Gesprächen, aus denen die Vorschläge abgeleitet wurden, werden
weggelassen, und der Run nennt ihre Zahl: Eine Änderung wird nie an den Daten
gemessen, an die sie angepasst wurde. Ein Dataset, das nur aus solchen Fällen
besteht, wird abgelehnt.

Jeder Vorschlag nennt die Wirkung, die er erwartet. Die Leiste zeigt sie neben
den Eval Runs, die die Vorschläge geprüft haben, sodass Sie die Vorhersage mit
dem vergleichen können, was die Runs ergaben.

## Skills { #skills }

Ein Skill wird aus seiner Werkbank unter Skills verbessert. Der Assistent schlägt
einen vollständigen neuen Inhalt vor, der mit den anderen
[Skill](skills.md)-Änderungen unter Skills wartet, mit Begründung und Belegen.

Das Anwenden einer Skill-Änderung wirkt sofort: Jeder an den Skill gebundene
Agent liest den neuen Inhalt beim nächsten Run. Deshalb lässt sich eine
Skill-Änderung zuerst mit Evals prüfen, an einem Agent, der den Skill nutzt:
Beide Seiten führen die veröffentlichte Version dieses Agents aus, und nur der
Inhalt des Skills unterscheidet sich. Eine Änderung, die für eine ältere Version
des Skills geschrieben wurde, wird abgelehnt, sobald jemand den Skill seitdem
geändert hat.

## Einen neuen Agent beschreiben { #describing-a-new-agent }

Der Dialog zum Anlegen bietet an, den Agent zu beschreiben, statt das Formular
auszufüllen. Die Beschreibung geht an den [Architekten](console.md#the-assistant),
der Agents entwirft und fragt, bevor er einen anlegt; das Ergebnis ist ein
gewöhnlicher Draft.

## Kosten und Budget { #cost-and-budget }

Verbessern und Prüfen sagen, was sie lesen und kosten würden, bevor etwas
ausgegeben wird, und starten mit einem zweiten Klick. Der Assistent hat ein
eigenes Monatsbudget, beim Anlegen fünf Dollar, das ein Bearbeiter des Agents
ändern kann. Eine Anfrage, die mehr kosten würde, als dem Assistenten oder der
Organisation bleibt, wird abgelehnt, bevor etwas gespeichert wird.

Auf dem Dashboard nennt die Ausgabenzeile, was der Assistent **für
Verbesserungen** gekostet hat, getrennt von den Kosten der Evals.

## Zugriff { #access }

| Um | Brauchen Sie |
|---|---|
| Verbessern oder Prüfen an einem Agent zu starten | `runs:view`, Bearbeitungsrechte am Agent und die Nutzung des Assistenten |
| Einen Skill zu verbessern | `runs:view`, Bearbeitungsrechte am Skill und die Nutzung des Assistenten |
| Einen Vorschlag anzunehmen, zu verwerfen oder rückgängig zu machen | Bearbeitungsrechte am Agent |
| Eine Skill-Änderung anzuwenden oder zu verwerfen | `skills:edit` am Skill |
| Mit Evals zu prüfen | Was ein [Eval Run](evals.md#access) braucht, und Bearbeitungsrechte am Agent |

Grants zählen: Ein Mitglied mit einem Bearbeitungs-Grant an einem Agent darf
diesen Agent verbessern.

## Wenn KI-Unterstützung ausgeschaltet ist { #when-ai-assistance-is-off }

Ist der Schalter **KI-Unterstützung** der Organisation aus, läuft der Assistent
nicht: Verbessern, Prüfen und das Verbessern eines Skills lehnt der Server ab,
und die Konsole zeigt sie deaktiviert mit einem Link zum Schalter. Bereits
wartende Vorschläge lassen sich weiterhin annehmen, verwerfen und rückgängig
machen, und ein Eval Run, der keinen Bewerter braucht, läuft weiterhin.
