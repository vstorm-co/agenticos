---
source_sha: "ebde7c56e07b"
title: "Authoring-Assistent"
description: "Der Authoring-Assistent liest, was Leute negativ bewertet haben und wie Runs endeten, und schlägt Änderungen an Anweisungen, Tools, Konfiguration, Skills und Context-Dateien eines Agents vor. Über jede entscheidet ein Mensch."
---

# Authoring-Assistent { #authoring-assistant }

Der **Authoring-Assistent** verbessert Agents anhand von Belegen. Er liest, was
Leute negativ bewertet haben und wie Runs endeten, und schlägt Änderungen an den
Anweisungen eines Agents vor, an den Namen und Beschreibungen seiner Tools, an
seiner [Konfiguration](#configuration) und an den Skills und Context-Dateien, die
er nutzt. Er ändert nie etwas von sich aus: Jeder Vorschlag
wartet auf einen Menschen, ein angenommener landet im [Draft](concepts.md), und
nichts erreicht irgendwen, bevor der Draft veröffentlicht ist.

Er tut drei Dinge:

- Einen Agent **verbessern**: Änderungen aus seinen negativ bewerteten und
  fehlgeschlagenen Runs vorschlagen.
- Ihre eigenen Änderungen **prüfen**: den Draft mit der veröffentlichten Version
  anhand derselben Belege vergleichen und sagen, was die Änderungen verbessern,
  riskieren und entfernt haben.
- **Einen Skill** oder **eine Context-Datei verbessern**: einen neuen Inhalt aus
  den Runs vorschlagen, die sie gelesen haben.

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

Die Prüfung belegt, dass ein Zitat in seinem Run steht, nicht, dass es zu dem
passt, was es stützt: Ein echtes Zitat über etwas anderes besteht sie. Deshalb
nennt ein Befund von Prüfen die Zeile der Änderung, um die es geht, und diese
Zeile muss Teil der Änderung sein. Die Leiste zeigt sie über den Zitaten des
Befunds, damit der Leser beurteilen kann, ob sie sie stützen. Ein Befund, die
Änderung sei belegt, dem kein prüfbares Zitat bleibt, wird nicht gezeigt.

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

Eine Änderung, die der Assistent vorschlägt und die sich nicht speichern lässt,
verschwindet nicht stillschweigend. Die Leiste führt sie unter **vorgeschlagene
Änderungen wurden nicht gespeichert** auf, mit dem Grund: Die Stelle, die sie
ändert, steht nicht in den Anweisungen oder kommt mehr als einmal vor, der Agent
hat kein solches Tool, die Einstellung darf der Assistent nicht ändern. Der
Worker protokolliert dieselben Gründe. Eine Stelle, die mit begradigten
Anführungszeichen, ohne Backticks oder mit zusammengezogenen Zeilen kopiert
wurde, findet trotzdem den Text des Drafts.

### Mit Evals prüfen { #check-with-evals }

**Mit Evals prüfen** führt ein [Dataset](datasets.md) gegen den Draft aus, wie er
mit allen wartenden Vorschlägen wäre, neben der veröffentlichten Version im
selben [Eval Run](evals.md#a-baseline-in-the-same-run). Durch die Prüfung wird
nichts angenommen, und der Draft ändert sich nicht. Solange ein wartender
Vorschlag nicht mehr zum Draft passt oder mit einem anderen kollidiert, wird die
Prüfung abgelehnt, bis er angenommen oder verworfen ist: Der Run misst genau das,
was wartet.

Statt eines Datasets kann die Prüfung eine der [Suites](evals.md#suites) des
Agents ausführen: ihr Dataset, in ihrer Umgebung. Der Run vergleicht den Draft wie
jede Prüfung mit der veröffentlichten Version und sagt, sobald er abgeschlossen
ist, auch, wie die Suite geurteilt hätte: bestanden, nicht bestanden oder ohne
Ergebnis, und warum, nach dem Schwellenwert, den die Suite beim Start der Prüfung
hatte. Das steht am Run und neben der Prüfung in der Leiste, so formuliert wie die
eigenen Ergebnisse der Suite.

Die Prüfung ist keiner der Runs der Suite: Sie steht in keinem Verlauf,
benachrichtigt niemanden, und Annehmen richtet sich nach dem Urteil des Runs
selbst. Eine Skill- oder Kontextänderung, die auf einer Suite des Agents geprüft
wird, auf dem sie läuft, bekommt dasselbe.

Die Fälle aus den Gesprächen, aus denen die Vorschläge abgeleitet wurden, werden
weggelassen, und der Run nennt ihre Zahl: Eine Änderung wird nie an den Daten
gemessen, an die sie angepasst wurde. Ein Dataset, das nur aus solchen Fällen
besteht, wird abgelehnt.

Jeder Vorschlag nennt die Wirkung, die er erwartet. Die Leiste zeigt sie neben
den Eval Runs, die die Vorschläge geprüft haben, sodass Sie die Vorhersage mit
dem vergleichen können, was die Runs ergaben.

## Konfiguration { #configuration }

Neben dem Text kann der Assistent eine Änderung an einigen Teilen der
Konfiguration eines Agents vorschlagen. Jede ist ein Vorschlag wie jeder andere,
einzeln in der Leiste entschieden und mit Namen gezeigt: das Modell, die
Wissensbasis, die Context-Datei, die Capability oder der MCP-Server, auf die sie
sich bezieht, nie eine Kennung.

| Teil | Was ein Vorschlag tun kann |
|---|---|
| Beschreibung | Sie setzen |
| Modell | Das Modellprofil wechseln |
| Modelleinstellungen | Temperatur, Top-p, maximale Tokens, Timeout oder parallele Tool-Aufrufe setzen |
| Schrittlimit | `max_steps` setzen |
| Capabilities | Eine hinzufügen oder entfernen oder ihre Einstellungen ändern - nur dort, wo die Einstellungen allein die Qualität betreffen, etwa wie viel Wissen abgerufen oder wann kompaktiert wird; Einstellungen, die eine URL, eine Domain, eine Verbindung, einen Anbieter oder personenbezogene Daten erreichen, ändern sich nie, und Subagents werden nie hinzugefügt oder umkonfiguriert. Eine Schutzmaßnahme - Guardrails - lässt sich nur hinzufügen: nie entfernen oder umkonfigurieren |
| Freigabe | Eine Capability oder eines ihrer Tools zuerst fragen lassen |
| Spezialisten | Die Beschreibung eines eingebetteten [Spezialisten](reference/capabilities.md#delegation) umschreiben |
| Wissensbasen | Eine binden oder lösen |
| Context-Dateien | Eine binden oder lösen |
| MCP-Tools | Ändern, welche Tools eines gebundenen Servers der Agent aufrufen darf |

Alles andere ist überhaupt kein Vorschlag: Eval-Suites und ihre Schwellen,
Datasets, Budgets, Observability und ein festgelegter Delegat werden vom
Assistenten nie geändert. **Bearbeiten** funktioniert bei einem einzelnen Wert
oder einem Text - einer Einstellung, dem Schrittlimit, einer Beschreibung; alles
andere wird so angenommen oder verworfen, wie es vorgeschlagen wurde.

### Er erweitert nie den Zugriff { #never-widens-access }

Einen Vorschlag, der eine Wissensbasis, eine Context-Datei, ein Modellprofil
oder einen MCP-Server bindet oder den Agent mehr MCP-Tools aufrufen lässt, nimmt
nur an, wer diese Änderung auch von Hand vornehmen dürfte: Jeder andere wird
abgelehnt, wie der Builder ihn ablehnen würde. Freigaben werden nur strenger:
Ein Vorschlag kann eine Capability oder ein Tool zuerst fragen lassen, nie
aufhören lassen zu fragen. Eine Capability, die der Assistent hinzufügt, kommt
mit jedem ihrer Tools, das etwas ändert, auf zuerst fragen gesetzt, und der
Vorschlag nennt diese Tools, so wie er die MCP-Tools nennt, die eine Änderung
erreichbar macht.

### Ein Modellwechsel { #a-change-of-model }

Ein Vorschlag, das Modell zu wechseln, sagt, was ein Run mit jedem der beiden
Modelle kosten würde, berechnet aus den letzten Runs des Agents. Beruht die
Berechnung auf weniger als fünf, nennt er sie eine grobe Schätzung und sagt, aus
wie vielen Runs.

Ein Modellwechsel wird erst angenommen, wenn er sich bewährt hat. **Annehmen**
bleibt deaktiviert und sagt warum, bis eine [Prüfung mit Evals](#check-with-evals)
der wartenden Vorschläge auf diesem Modell gelaufen ist und keine bestätigte
Regression gefunden hat. Eine Prüfung, die einen Fall unentschieden ließ -
nichts hat ihn bewertet, oder der Provider oder ein Bewerter ist daran
gescheitert - oder zu keinem Urteil kam, hält ihn ebenfalls zurück: Bewerten Sie
die Antworten oder starten Sie die Prüfung erneut.

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

## Context-Dateien { #context-files }

Eine [Context-Datei](context.md) wird aus ihrem Editor auf der Context-Seite
verbessert, aus den Runs der Agents, die sie lesen. Was der Assistent
vorschlägt, ist ein neuer Inhalt, und er wartet über der Liste auf dieser Seite,
mit Begründung und Belegen und mit den Agents, an die die Datei gebunden ist - soweit Sie
sie sehen dürfen. Pro Datei wartet jeweils eine Änderung.

Sie anzuwenden wirkt sofort, wie bei einem Skill: Jeder an die Datei gebundene
Agent liest den neuen Inhalt bei seinem nächsten Run. Deshalb lässt sie sich
vorher mit Evals prüfen, an einem Agent, der die Datei nutzt, wobei sich nur der
Inhalt der Datei unterscheidet. Auf eine Datei, die nach dem Vorschlag bearbeitet
wurde, lässt sich die Änderung nicht anwenden: Vergleichen Sie beide und
bearbeiten Sie die Datei von Hand, oder fragen Sie den Assistenten erneut.

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
| Eine Context-Datei zu verbessern | `runs:view`, `context:edit` an der Datei und die Nutzung des Assistenten |
| Einen Vorschlag anzunehmen, der etwas bindet oder erreicht | Zusätzlich den Zugriff, es von Hand zu binden |
| Eine Skill-Änderung anzuwenden oder zu verwerfen | `skills:edit` am Skill |
| Eine Änderung an einer Context-Datei anzuwenden oder zu verwerfen | `context:edit` an der Datei |
| Mit Evals zu prüfen | Was ein [Eval Run](evals.md#access) braucht, und Bearbeitungsrechte am Agent |

Grants zählen: Ein Mitglied mit einem Bearbeitungs-Grant an einem Agent darf
diesen Agent verbessern.

## Wenn KI-Unterstützung ausgeschaltet ist { #when-ai-assistance-is-off }

Ist der Schalter **KI-Unterstützung** der Organisation aus, läuft der Assistent
nicht: Verbessern, Prüfen und das Verbessern eines Skills oder einer
Context-Datei lehnt der Server ab,
und die Konsole zeigt sie deaktiviert mit einem Link zum Schalter. Bereits
wartende Vorschläge lassen sich weiterhin annehmen, verwerfen und rückgängig
machen, und ein Eval Run, der keinen Bewerter braucht, läuft weiterhin.
