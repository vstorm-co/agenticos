---
source_sha: "417a482ca530"
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
- Ihre eigenen Änderungen **prüfen**: den Draft mit der Version, auf der er
  beruht - der zuletzt veröffentlichten -, anhand derselben Belege vergleichen und
  sagen, was die Änderungen verbessern, riskieren und entfernt haben.
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

**Mit Evals prüfen** führt ein [Dataset](datasets.md) gegen die Basis des Drafts
aus - die zuletzt veröffentlichte Version - mit allen wartenden Vorschlägen
angewendet, neben dieser Version im selben
[Eval Run](evals.md#a-baseline-in-the-same-run). Ein Wächter kann die Produktion
auf einer älteren Version halten; die Prüfung misst nie gegen sie, sodass das,
was die neueste Version geändert hat, auf beiden Seiten steht und nie einem
Vorschlag angelastet wird. Hat sich der Draft von seiner Basis entfernt - durch
eigene Änderungen oder früher angenommene Vorschläge -, ist der Draft selbst die
Baseline, frisch ausgeführt statt aus einem früheren Run übernommen, sodass die
Vorschläge der einzige Unterschied sind; die Schätzung berechnet auch diese Seite
mit ein. Die Seiten heißen, was sie sind, im Dialog und am Run: "v2 + 1
Vorschlag" gegen "v2" oder "Draft + 2 Vorschläge" gegen "Draft". Durch die
Prüfung wird nichts angenommen, und der Draft ändert sich nicht. Solange ein
wartender Vorschlag nicht mehr zum Draft passt oder mit einem anderen
kollidiert, wird die Prüfung abgelehnt, bis er angenommen oder verworfen ist:
Der Run misst genau das, was wartet.

Statt eines Datasets kann die Prüfung eine der [Suites](evals.md#suites) des
Agents ausführen: ihr Dataset, in ihrer Umgebung. Der Run vergleicht die beiden
Seiten wie jede Prüfung und sagt, sobald er abgeschlossen ist, auch, wie die
Suite geurteilt hätte: bestanden, nicht bestanden oder ohne Ergebnis, und warum,
nach dem Schwellenwert, den die Suite beim Start der Prüfung hatte. Das steht am
Run und neben der Prüfung in der Leiste, so formuliert wie die eigenen Ergebnisse
der Suite.

Die Leiste fasst jede abgeschlossene Prüfung in einem Satz zusammen, der auf
ihren Run verlinkt - "audit-smoke würde nicht bestehen: macht „Do you ship to
Canada?“ kaputt" oder was sie auf dem Dataset kaputt gemacht und behoben hat.

Die Prüfung ist keiner der Runs der Suite: Sie steht in keinem Verlauf,
benachrichtigt niemanden, und Annehmen richtet sich nach dem Urteil des Runs
selbst. Eine Skill- oder Kontextänderung, die auf einer Suite des Agents geprüft
wird, auf dem sie läuft, bekommt dasselbe.

Die Fälle aus den Gesprächen, aus denen die Vorschläge abgeleitet wurden, werden
weggelassen, und der Run nennt ihre Zahl: Eine Änderung wird nie an den Daten
gemessen, an die sie angepasst wurde. Ein Dataset, das nur aus solchen Fällen
besteht, wird abgelehnt.

Eine Prüfung zählt als Test des Drafts, sobald der Draft genau das ist, was sie
geprüft hat - jeder geprüfte Vorschlag angenommen und sonst nichts geändert -,
sodass der Veröffentlichungsdialog ihr Urteil meldet; nach einer weiteren
Änderung sagt er, dass dieser Test veraltet ist. Eine Prüfung, die am Draft
selbst gemessen wurde, zählt nie: Sie sagt nichts über den Draft gegenüber der
veröffentlichten Version, die er ersetzen würde. Eine Prüfung schickt von sich aus
nichts in die [Review-Warteschlange](datasets.md#review) eines Datasets, da
nichts angenommen wurde; ihre Run-Seite sagt das neben **Send failed to review**.

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
| Capabilities | Eine hinzufügen oder entfernen oder ihre Einstellungen ändern - nur dort, wo die Einstellungen allein die Qualität betreffen, etwa wie viel Wissen abgerufen oder wann kompaktiert wird; Einstellungen, die eine URL, eine Domain, eine Verbindung, einen Anbieter oder personenbezogene Daten erreichen, ändern sich nie, und Subagents werden nie hinzugefügt oder umkonfiguriert. Eine Schutzmaßnahme - Guardrails - lässt sich nur hinzufügen: nie entfernen oder umkonfigurieren, gleich, wie der Vorschlag sie nennt |
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

### Zugriff erweitern { #widening-access }

Der Assistent kann vorschlagen, dem Agent mehr zugänglich zu machen: eine
Capability, eine Wissensbasis, eine Context-Datei, weitere MCP-Tools. Ein solcher
Vorschlag ist mit **Erweitert den Zugriff** markiert und nennt alles, was er
hinzufügt. Er erweitert nie, was ohne einen Menschen läuft:

- Eine Capability, die er hinzufügt, kommt mit jedem ihrer Tools, das etwas
  ändert, auf Freigabe gesetzt, ganz gleich, worauf der Vorschlag selbst sie
  gesetzt hat.
- Mehr Tools eines MCP-Servers zuzulassen, lässt eine Bindung, die nach nichts
  fragte, für die schreibenden Tools um Freigabe bitten. **Rückgängig** stellt
  die Tools wieder her und lässt sie weiter fragen: Die Freigabe wieder zu
  lockern, ist die Entscheidung eines Menschen. Bei einem Server, den jede
  Person über ihr eigenes Konto erreicht, zählt ein Tool, dessen Beschreibung der
  Assistent nicht sehen kann, als schreibendes.
- Freigaben werden nur strenger: Ein Vorschlag kann eine Capability oder ein
  Tool zuerst fragen lassen, nie aufhören lassen zu fragen.

Einen Vorschlag, der eine Wissensbasis, eine Context-Datei, ein Modellprofil
oder einen MCP-Server bindet oder den Agent mehr MCP-Tools aufrufen lässt, nimmt
nur an, wer diese Änderung auch von Hand vornehmen dürfte: Jeder andere wird
abgelehnt, wie der Builder ihn ablehnen würde.

### Ein Modellwechsel { #a-change-of-model }

Ein Vorschlag, das Modell zu wechseln, sagt, was ein Run mit jedem der beiden
Modelle kosten würde, berechnet aus den letzten Runs des Agents. Beruht die
Berechnung auf weniger als fünf, nennt er sie eine grobe Schätzung und sagt, aus
wie vielen Runs.

Ein Modellwechsel wird erst angenommen, wenn er sich bewährt hat. **Annehmen**
bleibt deaktiviert und sagt warum, bis eine [Prüfung mit Evals](#check-with-evals)
von genau dem, was das Annehmen hinterlässt - dem Draft mit allen noch wartenden
Vorschlägen umgesetzt -, auf diesem Modell gelaufen ist und keine bestätigte
Regression gefunden hat. Einen anderen Vorschlag zu verwerfen oder den Draft zu
bearbeiten, macht die letzte Prüfung veraltet, und eine neue ist nötig. Eine Prüfung, die nichts entschieden hat - eine
unbewertete Antwort oder kein Urteil -, hält ihn ebenfalls zurück: Bewerten Sie
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
