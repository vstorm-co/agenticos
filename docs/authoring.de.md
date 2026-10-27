---
source_sha: "a996016a2d29"
title: "Authoring-Assistent"
description: "Der Authoring-Assistent liest, was Leute negativ bewertet haben und wie Runs endeten, und schlägt Änderungen an Anweisungen, Tools, Konfiguration, Skills und Context-Dateien eines Agents vor. Über jede entscheidet ein Mensch."
---

# Authoring-Assistent { #authoring-assistant }

Der **Authoring-Assistent** verbessert Agents anhand von Belegen. Er liest, was
Leute negativ bewertet haben und wie Runs endeten, und schlägt Änderungen an den
Anweisungen eines Agents vor, an den Namen und Beschreibungen seiner Tools, an
seiner [Konfiguration](#configuration) und an den Skills und Context-Dateien, die
er nutzt. Er ändert nie etwas von sich aus: Jeder Vorschlag
wartet auf einen Menschen, ein angenommener landet im [Entwurf](concepts.md), und
nichts erreicht irgendwen, bevor der Entwurf veröffentlicht ist.

Er tut drei Dinge:

- Einen Agent **verbessern**: Änderungen aus seinen negativ bewerteten und
  fehlgeschlagenen Runs vorschlagen. In der Konsole öffnet jedes **Verbessern** den
  [Verbessern-Assistenten](#the-improve-wizard); eine einmalige Anfrage bleibt über die API möglich.
- Ihre eigenen Änderungen **prüfen**: den Entwurf mit der Version, auf der er
  beruht - der zuletzt veröffentlichten -, anhand derselben Belege vergleichen und
  sagen, was die Änderungen verbessern, riskieren und entfernt haben.
- **Einen Skill** oder **eine Context-Datei verbessern**: einen neuen Inhalt aus
  den Runs vorschlagen, die sie gelesen haben.

Der Assistent ist ein eigener [System-Agent](concepts.md#system-agents),
aufgeführt mit den übrigen System-Agents der Organisation. Ein Administrator
bearbeitet seine Anweisungen wie die jedes Agents - einen System-Agent zu ändern
braucht `org:settings` -, und seine Runs sind gewöhnliche Runs: budgetiert,
bepreist und in **Aktivität** (Activity) aufgeführt. Er ist nie der Agent, um
den es bei einem Improve oder Verify geht. Wenn er die
[Wissensbasis durchsucht](concepts.md#system-agent-spec), liest er die
Wissensbasen des Agents, den er verbessert.

Öffnen Sie **Verbesserungsassistent** beim Verbessern oder Verifizieren und
wählen Sie einen veröffentlichten Assistenten. Eine neue Auswahl löscht die alte
Schätzung; die Zustimmung gilt damit für Preis und Budget des gewählten Agents.
`improver_agent_id` bleibt in der Aufgabe gespeichert, auch für Hintergrundsitzungen.
Der Worker prüft Typ, Veröffentlichung und aktuelle Zugriffsrechte erneut.
Eine gelöschte Auswahl führt zur Ablehnung statt zum Rückfall auf den Standard.

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

**Er lernt nur aus Trainingsfällen.** Neben bewerteten Chats liest der Assistent fehlgeschlagene Trainingsantworten, bestätigte Regressionen, Bewerterbegründungen und Prüfungsnotizen aus zugänglichen [Datasets](datasets.md). Er erhält Trainingsquoten nach Tag und Bewerterkriterium sowie die Anzahl behobener und neuer Fehler. Kontrollfragen, Antworten und Bewertungen gelangen nie in seinen Prompt. Runs des Bewerters und des Assistenten bleiben ausgeschlossen.

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

Endet eine Anfrage an den Assistenten - Prüfen oder Verbessern über die API - bei geöffnetem Builder, zeigt ein Ergebnisdialog die Anzahl geprüfter Antworten, vorgeschlagene und gespeicherte Änderungen sowie abgelehnte Vorschläge mit Gründen. **Ergebnis ansehen** öffnet ihn erneut. Ein leeres Ergebnis erklärt, dass nichts anwendbar war, ohne erwartete Wirkung. Wirkungstext mit rohen Run-Kennungen wird durch eine Beschreibung mit der Anzahl verlinkter Quellantworten ersetzt.

Jeder geänderte Text - Anweisungen, eine Tool-Beschreibung, eine Context-Datei - erscheint als Diff: entfernte und hinzugefügte Zeilen mit markierten geänderten Wörtern, einige unveränderte Zeilen um jede Änderung und der Rest eingeklappt, einheitlich oder auf einem breiten Bildschirm nebeneinander. Jede Änderung behält Begründung und verlinkte Belege; Run-Kennungen in einer Begründung erscheinen als nummerierte Gespräche.

Nach einer abgeschlossenen Prüfung können Leser mit `runs:view` Antworten beider Seiten im Dialog vergleichen und die vollständige Prüfung öffnen. Vorher fordert der Dialog zum Prüfen auf. Ohne bewertete Chats oder Trainingsbelege erscheint der Assistent als kompakte Zeile über den Anweisungen.

## Vorschläge { #suggestions }

Vorschläge aus einer Verbesserungssitzung, aus Prüfen oder aus der API warten in der
**Assistentenleiste** auf dem Tab **Bauen** (Build) des Agents. Jeder Vorschlag zeigt die Passage, die er ändert, in ihrem Umfeld, die
Begründung und die Belege, und über jeden wird einzeln entschieden:

| Aktion | Was passiert |
|---|---|
| **Annehmen** | Die Änderung wird in den Entwurf geschrieben. Nichts wird veröffentlicht. |
| **Bearbeiten** | Ihre eigene Formulierung wird statt des Vorschlags angenommen. Bei Anweisungen öffnet sich der ganze Text: die aktuelle Version neben der vorgeschlagenen, die Sie bearbeiten, mit beim Tippen neu gezeichnetem Diff. Gespeichert wird nur die vorgeschlagene Passage; Text außerhalb ändern Sie im Anweisungseditor. |
| **Verwerfen** | Festgehalten; eine spätere Anfrage schlägt es nicht wieder vor. |
| **Rückgängig** | Kehrt die Entscheidung um, solange sie noch zum Entwurf passt. |

Ein Vorschlag verankert sich daran, wo seine Passage stand und was sie umgab,
nicht am Text allein, sodass eine Zeile, die zweimal vorkommt, dort geändert
wird, wo es gemeint war. Hat sich der Entwurf weiterbewegt - die Passage wurde
entfernt oder eine Tool-Beschreibung von Hand geändert -, sagt der Vorschlag, dass
er **nicht mehr zum Entwurf passt**, und lässt sich nur verwerfen. Rückgängig
verweigert sich ebenso, wenn der angenommene Text danach von Hand bearbeitet
wurde: Es würde diese Änderung verwerfen.

Die Leiste hat zwei Tabs, jeder mit einer Anzahl. **Zu prüfen** zeigt jeden noch
wartenden Vorschlag vollständig. **Entschieden** klappt jeden angenommenen,
bearbeiteten oder verworfenen auf eine Zeile zusammen, die die Art der Änderung -
Anweisungen, eine Tool-Beschreibung, eine Einstellung, ein neuer Skill -, die
Entscheidung und den Zweck nennt; das Öffnen der Zeile zeigt die Änderung und
Rückgängig. Beide Tabs gruppieren Änderungen nach Art. Die Leiste öffnet auf Zu
prüfen oder auf Entschieden, sobald nichts mehr zu prüfen ist.

Ein neueres Verbessern ersetzt die wartenden Vorschläge; Prüfen fügt seine
stattdessen hinzu. Das Veröffentlichen des Entwurfs schließt sie: Ihre
Entscheidungen sind endgültig, und die Leiste zeigt sie und den Rest dessen, was
der Assistent vor der Veröffentlichung gemeldet hat, nicht mehr an, denn all das
betraf einen Entwurf, der jetzt eine Version ist. Sie bleiben mit ihren
Entscheidungen gespeichert. Eine Anfrage, die bei der Veröffentlichung noch läuft,
zeigt ihre Ergebnisse, sobald sie fertig ist.

Eine Änderung, die der Assistent vorschlägt und die sich nicht speichern lässt,
verschwindet nicht stillschweigend. Die Leiste führt sie unter **weitere Ideen,
die der Assistent nicht hinzugefügt hat** auf, mit dem Grund: Die Stelle, die sie
ändert, steht nicht in den Anweisungen oder kommt mehr als einmal vor, der Agent
hat kein solches Tool, die Einstellung darf der Assistent nicht ändern. Der
Worker protokolliert dieselben Gründe. Eine Stelle, die mit begradigten
Anführungszeichen, ohne Backticks oder mit zusammengezogenen Zeilen kopiert
wurde, findet trotzdem den Text des Entwurfs.

### Mit Evals prüfen { #check-with-evals }

**Mit Evals prüfen** führt ein [Dataset](datasets.md) gegen die Basis des
Entwurfs aus - die zuletzt veröffentlichte Version - mit allen wartenden
Vorschlägen angewendet, neben dieser Version im selben
[Eval Run](evals.md#a-baseline-in-the-same-run). Ein Wächter kann die Produktion
auf einer älteren Version halten; die Prüfung misst nie gegen sie, sodass das,
was die neueste Version geändert hat, auf beiden Seiten steht und nie einem
Vorschlag angelastet wird. Hat sich der Entwurf von seiner Basis entfernt - durch
eigene Änderungen oder früher angenommene Vorschläge -, ist der Entwurf selbst die
Baseline, frisch ausgeführt statt aus einem früheren Run übernommen, sodass die
Vorschläge der einzige Unterschied sind; die Schätzung berechnet auch diese Seite
mit ein. Die Seiten heißen, was sie sind, im Dialog und am Run: „v2 + 1
Vorschlag“ gegen „v2“ oder „Entwurf + 2 Vorschläge“ gegen „Entwurf“. Durch die
Prüfung wird nichts angenommen, und der Entwurf ändert sich nicht. Solange ein
wartender Vorschlag nicht mehr zum Entwurf passt oder mit einem anderen
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
ihren Run verlinkt - „audit-smoke würde nicht bestehen: verschlechtert »Do you
ship to Canada?«“ oder was sie auf dem Dataset verschlechtert und behoben hat.

Die Prüfung ist keiner der Runs der Suite: Sie steht in keinem Verlauf,
benachrichtigt niemanden, und Annehmen richtet sich nach dem Urteil des Runs
selbst. Eine Skill- oder Kontextänderung, die auf einer Suite des Agents geprüft
wird, auf dem sie läuft, bekommt dasselbe.

Jeder Fall wird fest dem Training oder der Kontrolle zugeordnet, auch über Dataset-Versionen hinweg. Die Dataset-Einstellungen bestimmen den Kontrollanteil nur für künftige Fälle (standardmäßig 50%). Vorschlagsprüfungen messen ausschließlich Kontrollfälle; eine Verbesserungssitzung teilt die Fragen für jeden ihrer Versuche im selben Anteil neu auf und misst jeden Versuch auf seinem eigenen Kontrollteil. Beide benötigen mindestens fünf bewertbare Kontrollfragen.

Kopien von Trainingsfragen oder Quellbelegen werden anhand normalisierter Eingaben und der Quell-Run-ID ausgeschlossen, auch bei manueller Eingabe oder Generierung. Unter dem Minimum stoppt eine Sitzung mit `no_data` oder lehnt den Schritt ab, der zu wenige testen würde, und nennt die fehlende Anzahl. Der Run kennzeichnet beide Teile und ausgeschlossene Kopien. Normale Suites und Beförderungsschranken zählen weiterhin alle Fälle.

Eine Verbesserungssitzung fixiert Dataset-Version und Chat-Belegidentitäten. Ein späterer Versuch lernt aus den Trainingsergebnissen seiner eigenen Aufteilung, sodass eine Frage, die ein Versuch zurückgelegt hat, beim Schreiben des nächsten helfen kann; neue Chats und Fälle ändern nicht, was die Sitzung misst. Auf verschiedenen Fragen gemessene Versuche werden danach verglichen, was jeder gegenüber seiner eigenen Ausgangsfassung geändert hat, nicht nach ihren Bestehensquoten.

Eine Prüfung zählt als Test des Entwurfs, sobald der Entwurf genau das ist, was
sie geprüft hat - jeder geprüfte Vorschlag angenommen und sonst nichts geändert -,
sodass der Veröffentlichungsdialog ihr Urteil meldet; nach einer weiteren
Änderung sagt er, dass dieser Test veraltet ist. Eine Prüfung, die am Entwurf
selbst gemessen wurde, zählt nie: Sie sagt nichts über den Entwurf gegenüber der
veröffentlichten Version, die er ersetzen würde. Eine Prüfung schickt von sich aus
nichts zur [Prüfung](datasets.md#review) eines Datasets, da nichts angenommen
wurde; ihre Run-Seite sagt das neben **Nicht bestandene Fälle zur Prüfung
senden** (Send failed cases to review).

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
von genau dem, was das Annehmen hinterlässt - dem Entwurf mit allen noch wartenden
Vorschlägen umgesetzt -, auf diesem Modell gelaufen ist und keine bestätigte
Regression gefunden hat. Einen anderen Vorschlag zu verwerfen oder den Entwurf zu
bearbeiten, macht die letzte Prüfung veraltet, und eine neue ist nötig.

Eine Prüfung, die einen Fall unentschieden ließ -
nichts hat ihn bewertet, oder der Provider oder ein Bewerter ist daran
gescheitert - oder zu keinem Urteil kam, hält ihn ebenfalls zurück: Bewerten Sie
die Antworten oder starten Sie die Prüfung erneut. Ebenso eine Prüfung, in der
der Agent abgestürzt ist: Beheben Sie, was gescheitert ist, und starten Sie sie
erneut.

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
Agent liest den neuen Inhalt bei seinem nächsten Run. Deshalb ist die erste
Aktion **Mit Evals prüfen**, an einem Agent, der die Datei nutzt, wobei sich nur
der Inhalt der Datei unterscheidet, und **Anwenden** sagt, bevor Sie es drücken,
für welche Agents und Umgebungen die Änderung wirksam wird, welche Eval-Suites
sie einreiht und welche Wächter sie erst bei der nächsten Promotion prüfen. Das
Anwenden benachrichtigt die Besitzer dieser Agents. Auf eine Datei, die nach dem
Vorschlag bearbeitet wurde, lässt sich die Änderung nicht anwenden: Vergleichen
Sie beide und bearbeiten Sie die Datei von Hand, oder fragen Sie den Assistenten
erneut.

Der Assistent schlägt nie den Inhalt so vor, wie er schon dasteht, und eine neue
Anfrage schreibt die bereits wartende Änderung um. Anwenden und Verwerfen nennen
die Version der Änderung, die Sie gelesen haben, und werden abgelehnt, sobald sie
sich seitdem geändert hat - bei einer Skill-Änderung wie bei einer Datei.

## Einen neuen Agent beschreiben { #describing-a-new-agent }

Der Dialog zum Anlegen bietet an, den Agent zu beschreiben, statt das Formular
auszufüllen. Die Beschreibung geht an den [Architekten](console.md#the-assistant),
der Agents entwirft und fragt, bevor er einen anlegt; das Ergebnis ist ein
gewöhnlicher Entwurf.

## Kosten und Budget { #cost-and-budget }

Verbessern und Prüfen sagen, was sie lesen und kosten würden, bevor etwas
ausgegeben wird, und starten mit einem zweiten Klick. Der Assistent hat ein
eigenes Monatsbudget, beim Anlegen fünf Dollar, das ein Bearbeiter des Agents
ändern kann. Eine Anfrage, die mehr kosten würde, als dem Assistenten oder der
Organisation bleibt, wird abgelehnt, bevor etwas gespeichert wird.

Auf dem Dashboard nennt die Ausgabenzeile, was der Assistent **für
Verbesserungen** gekostet hat, getrennt von den Kosten der Evals.

Die Aufbewahrung der Aktivität erhält die Gesamtkosten gelöschter bezahlter Runs einer Sitzung, ohne Fragen oder Antworten aufzubewahren. Das Entfernen alter Aktivität stellt kein Ausgabenlimit wieder her. Neue Prüfungen und Wiederholungen zählen zu diesem Betrag; auch nach einem Abbruch bleiben entstandene Kosten sichtbar.

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

## Verbesserungssitzungen im Hintergrund { #background-improvement-sessions }

Eine Verbesserungssitzung geht Schritt für Schritt vor und wartet zwischen den
Schritten auf einen Menschen; sie übernimmt, veröffentlicht oder befördert nie
etwas. Senden Sie Dataset oder Suite an
`/agents/{agent_id}/improvements/estimate`, danach dasselbe Ziel mit
`budget_usd` an `/agents/{agent_id}/improvements`. Das Budget begrenzt die ganze
Sitzung. Der Start bezahlt nur das Lesen dessen, was schiefging: Die Sitzung
ordnet die schlechten Antworten ein, gruppiert ihre Lücken zu
Wissens-[Themen](knowledge-gaps.md#topics) und hält nach **Verstehen** mit dem
Status `waiting` an.

An einem Halt senden Sie `budget_usd` an `/{run_id}/continue/estimate`, um den
Preis des Schritts zu erfahren, der starten würde, und dann diese Schätzung mit
`confirmed: true` an `/{run_id}/continue`. Nach **Verstehen** schreibt der
nächste Schritt die Änderungen und hält nach **Änderungen** erneut an. Dort wählt
`PUT /{run_id}/selection` mit `hunk_ids` die zu testenden Änderungen, und
`PUT /{run_id}/changes/{hunk_id}` mit `edited_text` testet Ihre eigene
Formulierung statt der des Helfers; beides ist kostenlos. Der nächste Schritt
testet dann die gewählten Änderungen.

Ein Preis, der sich seit der Schätzung
bewegt hat, wird mit dem neuen abgelehnt, zur erneuten Bestätigung. Ein Schritt,
der nicht in das verbleibende Budget passt, wird abgelehnt, und die Sitzung
wartet weiter: Erhöhen Sie `budget_usd` und schätzen Sie erneut. Ein begonnener
Schritt darf enden; tatsächliche Kosten bleiben auch nach einem Abbruch sichtbar.

Der Test läuft von selbst: Die heutige und die geänderte Fassung des Agents
beantworten dieselben Fragen, und ein unentschiedener Vergleich wird im Preis des
Tests einmal wiederholt. Er endet beim Ergebnis: `ready`, wenn der Versuch den
Agent verbessert hat - seine Änderungen werden dann zum wartenden
Vorschlagspaket -, sonst `stopped`, mit dem Urteil als Grund.

Kein Versuch
startet von selbst. **Erneut versuchen** ist dasselbe `/continue` vom Ergebnis
aus, mit einer optionalen `note`, die der Helfer neben den Belegen liest; der
Versuch schreibt neue Änderungen und hält nach **Änderungen** an, denn
**Verstehen** wird einmal pro Sitzung gelesen. Eine Sitzung macht höchstens drei
Versuche innerhalb ihres Budgets. Zwei Ergebnisse ohne Änderung nacheinander
oder ein unentschiedenes samt Wiederholung erscheinen im Ergebnis als Hinweis,
dass ein weiterer Versuch kaum hilft, nicht als Halt.

Wer eine Sitzung für den Agent starten darf - Bearbeitungsrechte, `runs:view` und
eingeschaltete KI-Unterstützung -, darf auch ihren nächsten Schritt ausführen oder
es erneut versuchen. Die Sitzung hält fest, wer das tat, und die folgenden
Schritte laufen mit den aktuellen Rechten und Zugangsdaten dieser Person; eine
vom Architekten gestartete Sitzung lässt sich daher in der Konsole weiterführen.

Der Worker prüft vor jedem Übergang Entwurf, letzte Veröffentlichung, Bewertung
und Suite-Pin: Geänderte Eingaben machen die Sitzung sofort veraltet, verlorene
Rechte stoppen sie.

Eine an einem Halt wartende, angehaltene oder fehlgeschlagene Sitzung wird außerdem sofort veraltet, sobald sich ihr Agent oder ihr Fragensatz ändert; eine fertige, deren Entwurf sich ändert, während im Tab Bauen über ihren Kandidaten entschieden wird, schließt erst nach ihrer Woche. Eine Sitzung, die sieben Tage an einem Halt oder bei ihrem
Ergebnis liegen bleibt, schließt als veraltet, mit dem Grund `expired`. Ein Agent
hat jeweils eine offene Sitzung - in der Warteschlange, laufend, wartend, fertig,
angehalten oder fehlgeschlagen -, daher beantwortet der Start einer weiteren
`409`, bis die offene endet. Ersteller oder Organisationsadministratoren können
`/{run_id}/cancel` aufrufen.

Wer den letzten Schritt ausgeführt hat, wird an jedem Halt und bei jedem Ende
benachrichtigt: Analyse gelesen, Änderungen zur Prüfung bereit, geprüftes
Ergebnis, angehalten, fehlgeschlagen oder veraltet, außerhalb des Assistenten
entschieden, und eine abgeschlossene Wissens- oder Zuordnungsprüfung. Die
Sammlung oder einzelne Sitzung zeigt gespeicherte Schritte, Aufgaben-IDs, Urteile
und Kosten; eine offene Sitzungsseite folgt jedem Schritt über
Live-Änderungsereignisse.

Jeder Versuch legt eigene Fragen zurück. Die Testfragen werden für jeden Versuch
neu aufgeteilt - derselbe Anteil wie in den Dataset-Einstellungen, gezogen aus
Sitzung und Versuch, sodass ein Versuch immer dieselben zieht -, und die
Aufteilung wird eingefroren, wenn sein Test startet: Die Wiederholung eines
unentschiedenen Vergleichs, ein Test gewählter Änderungen, Einzelprüfungen und
die Prüfung eines Wissensentwurfs messen darauf.

Jeder Versuch braucht mindestens
fünf bewertbare zurückgelegte Fragen, und der Schritt, der weniger testen würde,
wird mit der Zahl der fehlenden Fragen abgelehnt. Der Helfer liest die Antworten
auf die übrigen Fragen eines Versuchs, nie auf die zurückgelegten. Da Versuche
auf verschiedenen Fragen gemessen werden, vergleicht das Ergebnis sie danach,
was jeder gegenüber seiner eigenen Ausgangsfassung geändert hat - neu behoben
minus neu verschlechtert, im Verhältnis zur Zahl der zurückgelegten Fragen -,
und die Bestehensquote eines Versuchs bleibt in seinen Details. Der beste
Versuch hat das beste Urteil, dann die größte solche Änderung.

Nach dem Ergebnis macht `/{run_id}/rounds/{number}/select` einen gemessenen
Versuch zum wartenden Kandidaten, nach erneuter Prüfung von Basis und Zugriff.
Die optionale Zuordnung von Wirkungen zu Änderungen nutzt
`.../attribution/estimate` und `.../attribution`. Der Start verlangt
`confirmed: true` und die geprüfte Summe `estimate_usd`; eine höhere neue
Schätzung wird abgelehnt. Jede wartende Änderung wird einzeln gegen dieselbe
Basis und die Fragen des Versuchs getestet. Die Kosten belasten das
Sitzungsbudget. Die Zuordnung akzeptiert oder veröffentlicht nichts und ersetzt
nicht das gemeinsame Urteil des Versuchs.

### Der Verbessern-Assistent { #the-improve-wizard }

Öffnen Sie **Verbessern** im Agentenkopf oder in der Assistentenleiste auf dem Tab Bauen, über das Abzeichen **Braucht Aufmerksamkeit** in der Agentenliste, über die Dashboard-Karte oder über den Tab **Wissenslücken** des Agents. Es steht zwischen den anderen Aktionen im Kopf; hatte die Version, die der Agent jetzt ausliefert, in den letzten 30 Tagen negativ bewertete Antworten oder fehlgeschlagene Runs, trägt es einen Punkt und sein Name sagt, warum. Die Dashboard-Karte **Verbesserungen, die auf Sie warten** listet die Sitzungen, die für eine Entscheidung angehalten haben.

Jedes **Verbessern** öffnet die offene Sitzung des Agents - laufend, auf Sie wartend, beim Ergebnis oder angehalten oder fehlgeschlagen - und startet eine neue, sobald diese Sitzung als Entwurf behalten, veröffentlicht, verworfen, abgebrochen oder geschlossen wurde; sie bleibt dann im [Verbesserungsverlauf](#improvement-history) des Agents. **Beenden und eine neue starten** neben einer offenen Sitzung beendet sie zuerst.

Eine Sitzung liegt unter `/agents/<agent>/improve/<session>`; die Seite lässt sich schließen und wieder öffnen, während die Arbeit weiterläuft. Jeder Bildschirm verlangt höchstens eine Entscheidung, nennt, wer dort was entschieden hat, und legt erweiterte Optionen unter **Details anzeigen**. Jeder Bildschirm beginnt mit Zahlen und kleinen Diagrammen, jeder Zustand ist mit einem Symbol und nicht nur einer Farbe markiert; vollständige Antworten, Zitate und Gründe warten in aufklappbaren Karten. Eine Zeile über den Schritten nennt den Zustand der Sitzung - **In Bearbeitung**, solange ein Schritt läuft, und an einem Halt, worauf sie wartet: **Wartet auf Sie: sehen Sie sich an, was schiefging** oder **Wartet auf Sie: prüfen Sie die Änderungen** - und was sie von ihrem Limit ausgegeben hat.

Ein Schritt öffnet sich, sobald er Arbeit zu zeigen oder eine Entscheidung zu erfragen hat. Die Seite folgt dem Schritt, auf dem die Sitzung steht; nachdem Sie einen anderen geöffnet haben, führt **Zum aktuellen Schritt** dorthin zurück. An einem Halt trägt die Fußzeile den nächsten Schritt mit seinem Preis, zum Beispiel **Nächster Schritt: Änderungen schreiben · ca. $0.04**; nichts wird ausgegeben, bevor Sie ihn drücken. Hat sich der Preis seit der Anzeige bewegt, sagt die Fußzeile das - **Der Preis hat sich auf ca. $0.05 geändert. Drücken Sie erneut, um fortzufahren.** -, und kostet der Schritt mehr, als der Sitzung bleibt, lässt sich ihr Limit gleich dort erhöhen.

**Start.** Drei Zahlen aus den letzten 30 Tagen, dann die eigenen Testfragen des Agents, bereits gewählt und geschätzt: Die Schätzung deckt das Lesen dessen ab, was schiefging, erscheint samt ungefährer Dauer ohne Klick und gibt nichts aus, daher ist **Verbesserung starten** die einzige Entscheidung. Jeder nächste Schritt wird geschätzt, bevor Sie ihn drücken, und das Limit begrenzt die ganze Sitzung. Andere Testfragen, das Ausgabenlimit, der Hilfsagent und ein Test der heutigen Antworten liegen unter **Details anzeigen**. Ein Agent ohne Testfragen bekommt **Testfragen für mich schreiben**: Bewertete Antworten werden zu Fragen, weitere entstehen für Themen ohne Beispiel, und die Schätzung folgt, sobald sie bereit sind. Bleiben zu wenige Fragen, um eine Änderung zu messen, bietet der Bildschirm an, so viele zu schreiben, wie der Sitzung fehlen. Der Hinweis nach der ersten Veröffentlichung öffnet diesen Bildschirm, um einen Ausgangswert festzulegen.

1. **Verstehen.** Ein Satz und ein Balken zählen die Probleme, die im Agent zu beheben sind, und die Informationen, die in der Wissensdatenbank fehlen. Beispiele, deren Lücken in ein Wissenslücken-Thema fielen, bilden eine Karte, die die Frage zeigt und sich zur Antwort, zu den Kommentaren und zum Grund aufklappen lässt, aus dem der Klassifikator sie dort einordnete. Eine Antwort, deren Thema inzwischen ein Dokument abdeckt, zählt unter **Schon in der Wissensdatenbank**, mit diesem Dokument und dem Tag, an dem es hinzugefügt wurde: Für sie gibt es nichts mehr zu entwerfen. Die Sitzung hält hier immer an; **Nächster Schritt: Änderungen schreiben** bittet den Helfer um Änderungen.
2. **Änderungen.** Wie viele Änderungen vorgeschlagen und wie viele enthalten sind, dann jede Änderung als Diff mit Soll beheben, darunter eingeklappt Warum und Grundlage. Am Halt hat jede Änderung **Änderung N im Test berücksichtigen**, wovon mindestens eine angehakt bleibt, und **Formulierung ändern**, das Ihre Formulierung statt der des Helfers testet: Die Änderung ist dann mit **Von Ihnen umformuliert** markiert, und **Zurück zur vorgeschlagenen Formulierung** macht das rückgängig. **Nächster Schritt: ausgewählte Änderungen testen** startet den Test; solange er läuft, lässt sich die Liste lesen, aber nicht ändern. Wissensentwürfe bilden eine eigene Spalte mit den Entwürfen, die jemand angefordert hat. Wurde keine Änderung gefunden, listet der Bildschirm auf, was jeder Versuch probiert hat.
3. **Prüfung.** Die heutige und die geänderte Fassung des Agents beantworten dieselben Fragen in einem Test, jede mit einem Balken, wie weit sie ist; Antworten aus einem Test vor Beginn der Sitzung füllen den Balken der heutigen Fassung sofort. Dann die Phasen, jede als erledigt, laufend oder nicht begonnen markiert: fragen, bewerten und die Antworten mit geändertem Ergebnis erneut stellen. Der Test läuft von selbst, und das Ergebnis öffnet sich, wenn er fertig ist. **Vollständige Prüfung öffnen** führt zum Eval-Run.
4. **Ergebnis.** Zuerst, was die Sitzung ergeben hat, in Sätzen aus den Urteilen - welcher Versuch den Agent verbessert hat, oder dass keiner es tat und welcher ihn verschlechtert hat - mit den Themen, die in der Wissensdatenbank fehlen, und dem Grund, warum die Sitzung angehalten hat; nach der Entscheidung sagt es, welcher Versuch als welche Version veröffentlicht oder als Entwurf behalten wurde. Unter **Was Sie tun können** steht eine Hauptaktion: **Änderungen prüfen und übernehmen**, wenn ein geprüfter Kandidat wartet, **Erneut versuchen**, solange Versuche oder Budget übrig sind, **Die benötigten Dokumente entwerfen**, wenn nur Wissen fehlt, und sonst **Ohne Änderungen beenden**, neben **Neue Sitzung starten** und dem Hinweis, Testfragen dort zu ergänzen, wo der Agent schlecht antwortet. Ein fehlgeschlagener Schritt bietet zuerst an, ihn innerhalb des Ausgabenlimits zu wiederholen. **Erneut versuchen** nimmt einen optionalen **Hinweis für den Helfer** - was zu ändern oder zu behalten ist - und zeigt seinen Preis, bevor es startet; der neue Versuch hält bei **Änderungen** an. Ein Schritt, der anhielt, weil die Person, die ihn ausführte, den nötigen Zugriff verlor, bietet **Diesen Schritt mit meinem Zugriff fortsetzen** jedem an, der eine Sitzung starten darf. Dann die Zahlen: neu behoben und neu verschlechtert zählen nur durch erneutes Fragen bestätigte Änderungen, die noch nicht bestätigten stehen klein darunter, und die Zahl fehlender Wissensthemen führt zu ihrer Liste. Jeder Versuch ist eine geschlossene Zeile - sein Urteil, was er gegenüber seiner eigenen Ausgangsversion auf den von ihm zurückgelegten Fragen behoben und verschlechtert hat, seine Kosten, der beste Versuch markiert - oder, wenn der gewählte Versuch nicht besser war, als gewählt markiert. Jeder Versuch legt eigene Fragen zurück, daher werden Versuche nach ihrer Änderung verglichen und nicht nach ihren Bestehensquoten, die nur in den Details einer Zeile stehen. Eine Zeile öffnet sich zu den Balken der vorher und nachher gut beantworteten Fragen, den Kosten pro Antwort, wenn sie sich geändert haben, und jeder geänderten Frage mit ihren Antworten vorher und nachher; eine von den wiederholten Antworten nicht bestätigte Änderung wartet unter **Noch nicht bestätigt** und ist nur als möglicherweise behoben oder möglicherweise verschlechtert markiert. Ein Balken ist nur bei einer durch erneutes Fragen bestätigten Änderung grün oder rot; sonst bleibt er grau, und ein Unterschied von einer Frage oder Balken in entgegengesetzte Richtungen gilt als Rauschen. Unter **Details anzeigen** in der Zeile: **Wie wir es gemessen haben**, ein Satz dazu, wie viele Fragen der Helfer sah und wie viele zurückgelegt wurden, um das Ergebnis zu entscheiden; **Welche Änderung hat geholfen?**, wenn der Versuch zwei oder mehr Änderungen gemacht hat, mit dem Preis, jede einzeln zu testen; und nur wenn die Sitzung einen Entwurf zum Testen hat, **Prüfen, ob der Entwurf helfen würde** - als ob die Suche ihn fände oder über die echte Suche. Waren die Prüfungen Rauschen - Antworten wurden innerhalb eines Versuchs beim erneuten Stellen verschieden bewertet, oder die heutige Version erreichte zwischen Versuchen auf ihren gemeinsamen zurückgelegten Fragen unterschiedliche Werte - und war kein Versuch besser, sagt die Karte zuerst, dass der Test eine bessere Version nicht von einer schlechteren unterscheiden kann, nennt, was ihn verlässlich macht - Bewertungskriterien als Ja/Nein statt einer Skala, eine Regel für Länge und Format statt des Bewerters, mehr Fragen bis etwa 30 zurückgelegte, ein stärkeres Bewerter-Modell - und listet die verschieden bewerteten Fragen mit den Bewertungen jedes Versuchs. Neben einem besseren Versuch vermerkt sie das Rauschen nur. Versuche mit weniger als fünf gemeinsamen zurückgelegten Fragen werden nicht auf Rauschen verglichen, und die Karte sagt das. Zwei Versuche hintereinander, die nichts geändert haben oder sich nicht verlässlich bewerten ließen, bringen den Hinweis, dass ein weiterer wahrscheinlich nicht hilft; die Sitzung hält vor ihrem Versuchslimit nie von selbst an, und die Karte nennt dieses Limit erst, wenn es erreicht ist. Siehe [wenn sich die Bewertung selbst bewegt](evals.md#a-flip-is-confirmed-before-it-counts) und [wie beständig die Antworten sind](evals.md#how-steady-the-answers-are).
5. **Annehmen.** Zahlen dazu, was die neue Version behebt, verschlechtert und pro Antwort kostet und mit wie vielen Fragen sie getestet wurde. Die Themen, die laut dieser Sitzung in der Wissensdatenbank fehlen, stehen mit ihren Fragen da. Die Sitzung entwirft keines davon: Jedes bietet **Entwerfen** mit dem, was ein Entwurf höchstens kostet, zeigt **Wird entworfen…**, während der Entwurf geschrieben wird, und bietet danach **Prüfen und hinzufügen** oder **Nicht jetzt**, das ihn für die Sitzung beiseitelegt (`PUT /{run_id}/topics/{topic_id}/later`). Jeder Ort, an dem Leute den Agent nutzen, sagt, ob er sofort wechselt, nach bestandener automatischer Prüfung oder bei seiner Version bleibt. Dann **Version N veröffentlichen** oder **Als Entwurf behalten**. Beides beendet die Sitzung, und dieser Schritt sagt dann, was entschieden wurde, von wem und wann, mit einem Link zur Version. Gibt es nichts zu übernehmen, wird der Schritt übersprungen.

Ein Link auf einen Schritt, den es nicht mehr gibt - `?step=testSet` oder `?step=today` -, öffnet den Schritt, der an seine Stelle trat, **Verstehen** oder **Prüfung**, ohne einen Verlaufseintrag hinzuzufügen.

Ein fehlgeschlagener Vorschlags- oder Eval-Schritt lässt sich ausdrücklich mit `/{run_id}/retry` wiederholen; mehrfache Klicks erzeugen kein weiteres Kind. Automatische Job-Wiederholungen wiederholen keinen bezahlten Aufruf. Menschliche Entscheidungen setzen den Sitzungsstatus auf angenommen, veröffentlicht oder verworfen. Die bestätigte Aktion `/{run_id}/finish` übernimmt die geprüften Änderungen, wo Sie eine eigene Formulierung gaben in dieser, und veröffentlicht sie optional in derselben Transaktion.

Eine als Entwurf behaltene Sitzung ist abgeschlossen: Den Entwurf veröffentlicht das übliche **Veröffentlichen** des Agents, und wenn diese Version die von der Sitzung gemessene ist, wird sie in der Sitzung eingetragen. Der Abschluss kann eine Suite bei Veröffentlichung mit null erlaubten Regressionen anlegen. Übliche Berechtigungen und Veröffentlichungsprüfungen gelten weiter, und geschützte Umgebungen warten auf ihre Prüfungen. Nach ihrem Test bearbeitete Änderungen müssen erneut getestet werden.

Die Sitzungsschätzung umfasst die Einordnung schlechter Chatantworten anhand bearbeitbarer Wissensbasen des Agenten und die Gruppierung ihrer Lücken zu [Themen](knowledge-gaps.md#topics). Entwürfe enthält sie nicht: Ein Entwurf entsteht nur, wenn ein Mensch ihn anfordert, und wird als eigener Run bezahlt. Jeder Schritt prüft vor dem Start erneut seine vollständige Schätzung. Nur festgelegte, nicht gelöschte Quellchats erreichen Klassifizierung oder Gruppierung; Trainingsfehler bleiben Agentenbelege, Kontrolltexte erreichen diese Helfer nie.

Ein Klassifizierungsfehler wird angezeigt, Quellgespräche bleiben verfügbar, und die Sitzung hält trotzdem bei **Verstehen** an. Eine reine Wissenssitzung hält an und listet die Themen auf, die in der Wissensdatenbank fehlen, damit Sie die gewünschten entwerfen, ohne leere Agentenversion. Ein Entwurf veraltet, sobald nach ihm ein Dokument zur Wissensdatenbank hinzugefügt wird, und **Neu entwerfen** schreibt ihn erneut (siehe [Den fehlenden Inhalt entwerfen](knowledge-gaps.md#drafting-the-missing-content)). Eine Entwurfsprüfung erfordert weiterhin eine eigene Schätzung und Bestätigung; das Hinzufügen bleibt eine gesonderte menschliche Entscheidung.

Eine menschliche Bewertung und ihr Widerruf berechnen den aktuell gemessenen Versuch in derselben Transaktion wie Test- und Prüfergebnisse neu. Der ausgewählte Versuch und seine Kosten bleiben bestehen. Frühere Messungen und Einzelprüfungen ersetzen nicht das aktuelle Gesamturteil. Eine Prüfung startet keinen neuen Modellaufruf, keine Veröffentlichung und keinen Umgebungswechsel. Darf der ursprüngliche Anfragende den Vergleich nicht mehr lesen, wird der Versuch unentschieden, statt ein grünes Urteil zu behalten. Live-Dataset-Ereignisse aktualisieren Test-, Prüfungs-, Sitzungs- und Umgebungsansichten.

Die Schrittleiste unterscheidet erledigte, laufende, entscheidungsbedürftige, übersprungene und noch nicht begonnene Arbeit. Wählen Sie einen Schritt zur Ansicht; dies startet keine kostenpflichtige Aktion. Beim erneuten Öffnen erscheint die aktuelle Arbeit, während jeder Schritt seinen Zustand behält. Auf dem Telefon stehen der aktuelle Schritt und sein Status unter den Markierungen.

**Limit erhöhen und fortfahren** erscheint, wo ein geschätzter Schritt nicht ins Budget passte. Vor weiteren Ausgaben stehen eine neue vollständige Schätzung und Bestätigung; Quellen, festgelegte Fragen und Versuchslimit bleiben gleich. Ein fehlgeschlagener Schritt wird im selben Versuch wiederholt. Eine fortgesetzte Prüfung reserviert nur verbleibende Messungen samt noch möglicher Wiederholung.

**Ohne Änderungen beenden** im Ergebnis, in anderen Schritten **Verwerfen**, bestätigt nur ausstehende Vorschläge dieser Sitzung. Andere Vorschläge bleiben bestehen; angewendete Änderungen werden nicht rückgängig gemacht. Schätzungen melden keine Änderung; bestätigte Entscheidungen aktualisieren offene Agentenansichten.

#### Verbesserungsverlauf { #improvement-history }

Der Tab **Historie** des Agents listet seine Verbesserungssitzungen, die neueste zuerst: wann jede begann und wer sie gestartet hat, wie ihr gewählter Versuch abschnitt, was entschieden wurde und was sie gekostet hat.

Eine abgeschlossene Sitzung - als Entwurf behalten, veröffentlicht, verworfen, abgebrochen oder geschlossen, weil sich ihr Ausgangspunkt geändert hat oder sie sieben Tage lang niemand weitergeführt hat - öffnet ihren Assistenten nur zum Lesen: Jeder Schritt und seine Details lassen sich öffnen, nichts lässt sich ändern oder bezahlen. Ihr letzter Schritt sagt, was entschieden wurde, von wem und wann, listet die gemessenen Änderungen mit ihrer Entscheidung, sagt, was aus jedem entworfenen Wissensdokument wurde und ob eine automatische Prüfung den Agent überwacht.

Eine Sitzung, die auf Sie wartet, beim Ergebnis steht, angehalten oder fehlgeschlagen ist, bleibt offen: **Verbessern** und ihr Eintrag im Verlauf führen zu ihr zurück, um ihren nächsten Schritt auszuführen, ihr Limit zu erhöhen und fortzufahren, einen Versuch zu wählen, den fehlgeschlagenen Schritt zu wiederholen oder sie zu verwerfen.

Die API beantwortet jede Änderung an einer abgeschlossenen Sitzung mit `409`, außer der Wiederholung des Abbruchs oder Verwerfens, das sie beendet hat. `GET /{run_id}/changes` liest die Änderungen, die ihr gewählter Versuch gemessen hat. Eine Sitzung zu lesen braucht Lesezugriff auf den Agent und `runs:view`; sie zu ändern oder zu starten braucht zusätzlich Bearbeitungsrechte für den Agent.

#### Den Architekten fragen { #asking-the-architect }

Der [Architekt](console.md#the-assistant) liest die Sitzungen, Testläufe und
Testfragen eines Agenten und erklärt ein Ergebnis in einfachen Worten: was ein
Versuch behoben und was er verschlechtert hat, ob eine Änderung durch erneutes
Fragen bestätigt wurde und wie sich die zurückgehaltenen Fragen verändert haben.
Er verlinkt den Assistenten, statt ihn nachzuerzählen.

An jedem Halt sagt er, was die Sitzung gefunden hat, was der nächste Schritt tut
und was er kostet. Eine Sitzung startet, führt ihren nächsten Schritt aus,
wiederholt, wählt einen Versuch, übernimmt, veröffentlicht oder beendet er nur,
wenn Sie darum bitten; eine Sitzung, die er gestartet hat, lässt sich im
Assistenten fortsetzen, und umgekehrt.

Gefragt, was zu tun ist, empfiehlt er einen Schritt und fragt zuerst. Jede
Änderung wartet auf Ihre Freigabe auf einer Karte, nach einem Satz dazu, was und
warum; Starten zeigt, was die Analyse kostet, und das Ausgabenlimit der ganzen
Sitzung, jeder weitere Schritt seinen eigenen Preis. Er ruft als Sie dieselben
Aktionen wie der Assistent auf, daher gelten dieselben Prüfungen: Ein geänderter
Agent lehnt die Übernahme ab, eine geschützte Umgebung wartet auf ihren Check,
und das Audit-Log verzeichnet Sie, mit der Kennung des Architekten daneben.

### Einen neuen Skill vorschlagen { #proposing-a-new-skill }

Der Assistent kann **Ein Skill wäre sinnvoll** vorschlagen, wenn ein wiederverwendbarer Ablauf in mindestens drei verschiedenen Quellantworten vorkommt. Jede Textstelle muss in der Antwort selbst stehen; Kommentare allein belegen keinen wiederholten Ablauf. Die Karte zeigt Name, Beschreibung, vollständigen Inhalt, Begründung und geprüfte Belege. Eine Evaluation bindet einen temporären Skill nur an den Kandidaten: Sie erstellt weder einen Skill-Datensatz noch eine veröffentlichte Version.

**Accept** erstellt den privaten Skill und bindet ihn in derselben Transaktion an den Entwurf des Agenten. Dafür sind `skills:edit` und Bearbeitungszugriff auf den Agenten nötig. Ohne Erstellungsrecht bleibt der Vorschlag lesbar und prüfbar; die deaktivierte Annahme erklärt den Grund. **Dismiss** erstellt nichts. **Undo** entfernt die Bindung und behält den unabhängigen Skill. Erneutes Annehmen verwendet ihn nur bei unverändertem Namen und Inhalt. Skills enthalten Anweisungen und gewähren keine Tools. Zusätzlicher Tool-Zugriff benötigt eigene Richtlinienprüfungen; schreibende Tools erfordern eine Freigabe.

Ein Ablauf aus weniger als drei verschiedenen Antworten wird nicht als Vorschlag aufgenommen. Er wartet unter **Zu prüfen** in der Gruppe Neue Skills mit vollständigem Text. **Verwerfen** verschiebt ihn nach **Entschieden**, und Rückgängig holt ihn zurück. **Create skill** öffnet eine Vorschau: Name, Beschreibung und Inhalt lassen sich bearbeiten, und ein Hinweis nennt, auf wie vielen Antworten er beruht. **Create skill** in der Vorschau legt den Skill in der Bibliothek an und bindet ihn an den Entwurf des Agenten, nie an eine veröffentlichte Version. Dafür gelten dieselben Berechtigungen wie für Accept, und es gibt keinen Modellaufruf. Ein zweiter Klick liefert den bereits erstellten Skill.

Die Kostenschätzung berücksichtigt den vollständigen vorgeschlagenen Inhalt für jede Kandidatenantwort und bestätigende Wiederholungen zusätzlich zum historischen Antwortpreis.

### Einen Wissensentwurf prüfen { #checking-a-knowledge-draft }

Wähle in einer abgeschlossenen Sitzung einen Entwurf und unabhängige Fragen zu seinem Thema. Schätzung und Bestätigung erfolgen getrennt von der Übernahme der Agentenänderungen. Die Prüfung vergleicht **A**, die ausgewählten Änderungen, mit **B**, denselben Änderungen plus Entwurf. Das eigene Ergebnis sagt **unter der Annahme, dass die Suche diese Passage findet**: Diese Stufe fügt den Text als Kontext ein und prüft die Suche nicht.

Trainingsfälle, Quellgespräche, Quellbeiträge und normalisierte Kopien der Quellfragen sind ausgeschlossen. Mindestens fünf unabhängige, bewertbare Kontrollfragen sind nötig; andernfalls ist der Entwurf **nicht messbar** und keine kostenpflichtige Prüfung startet. Die vollständige Schätzung umfasst beide Varianten und Wiederholungen, zählt zum Sitzungslimit und gilt für den aktuellen Entwurf und die ausgewählten Fragen.

**Unbelegt — Fakten prüfen** bedeutet, dass kein Quelldokument des Entwurfs in der Wissensbasis mehr existiert. Ein bestandener Antworttest beweist keine Fakten. Prüfe die Passage im vorhandenen Themendialog und entscheide selbst über das Hinzufügen. Die Prüfung erzeugt weder Kontextdateien noch Dokumente und veröffentlicht nichts. Abhängige Testsuiten laufen weiterhin, nachdem ein Mensch ein Dokument hinzufügt.

Temporäre Inhalte werden nach Prüfungsende oder einer Entwurfsänderung entfernt. Änderungen machen das alte Ergebnis ungültig. Das Löschen von Daten einer Quellperson entfernt außerdem abgeleitete Testantworten, Bewertungsbegründungen und Modellmanifeste. Ein Sitzungsabbruch beendet auch ihre Wissensprüfungen. Bereits entstandene Kosten bleiben nach Abbruch oder Löschung erhalten.

Der Entwurf speichert Fingerabdrücke aller Eingabefragen, auch der nicht zitierten. Ältere Entwürfe ohne vollständige Herkunft sind nicht messbar; erstelle zuerst einen neuen Entwurf. Fingerabdrücke und Quellrun-Identitäten werden bei der Datenlöschung mit dem Entwurf entfernt.

#### Die tatsächliche Suche prüfen { #checking-real-retrieval }

Wähle **Prüfen, ob die Suche sie findet**, um A mit B über ein reines Such-Overlay zu vergleichen. Der Entwurf wird mit dem ausgewählten Embedding-Modell der Wissensbasis eingebettet und nur während dieses Runs zu den Suchkandidaten hinzugefügt. Mandantengrenzen, Dokumentfreigaben, fachliche Filter, Ranking und endgültige Ergebnislimits gelten weiterhin. Es entstehen weder Vektortabellen noch Dokumente oder Kontextdateien. Temporäre Inhalte werden auch nach Fehlern oder Abbruch entfernt.

Eine neue Korrektur gilt nur als nachgewiesen, wenn der Entwurf jede bestätigende Kandidatenantwort über das endgültige Suchergebnis erreicht hat. Andernfalls ist das Ergebnis nicht schlüssig, auch wenn die Antwort gut bewertet wurde; tatsächliche Antworten und Bewertungen bleiben sichtbar. Ein ignorierter Toolfehler macht einen Suchfehler nicht zum Erfolg. Die Schätzung umfasst zusätzliche Embedding-Suchen und Bestätigungswiederholungen. Nicht verfügbare oder nicht bepreiste Modelle verhindern die Prüfung vor kostenpflichtiger Arbeit. Ein Mensch muss weiterhin Fakten prüfen und das Dokument ausdrücklich hinzufügen.

Manuelle Tests und die Erstellung von Testfragen benachrichtigen die anfordernde Person nach Abschluss, auch bei Fehlern. Erneute Jobzustellungen erzeugen keine doppelten Meldungen. Untergeordnete Tests einer Testsuite oder Verbesserungssitzung verwenden deren übergeordnete Benachrichtigung. Die Einstellungen stehen unter **Einstellungen → Benachrichtigungen**. Offene Test- und Datensatzseiten werden nach dem Speichern des Ergebnisses über den Änderungsstrom aktualisiert.

Der Schritt Verstehen zeigt eine begrenzte Quellenstichprobe, die gespeicherte Ursache, Antwort, Bewertungskommentare und einen Gesprächslink. Unbekannte Ursachen bleiben ausdrücklich unklassifiziert. Der Schritt Testfragen liest die angeheftete Fragenversion der Sitzung und kennzeichnet Trainingsfragen sowie zurückgehaltene Fragen. Heute zeigt die Ausgangsmessung erst nach einem erfolgreich abgeschlossenen Test; teilweise oder fehlgeschlagene Tests gelten nicht als gemessener Ausgangswert. Quellenansichten erfordern `runs:view`, prüfen den aktuellen Zugriff auf Wissensbasen und entfernen Zugangsdaten aus jedem Textfeld.


Der Annahmeschritt nennt die nächste Versionsnummer und wiederholt das gemessene Ergebnis der ausgewählten Runde. Die automatische Prüfung wird nur für Agenten ohne Prüfungssuite angeboten. Eine Veröffentlichung speichert Versionsidentität und Nummer in der Sitzung: Nach erneutem Öffnen führt der Abschluss weiterhin zu dieser Veröffentlichung. Alte Sitzungen ohne diese Verknüpfung zeigen ihren Zustand, ohne eine Version zu erraten. Ein Lesefehler bei Vorschlägen bietet einen erneuten Versuch; ersetzte Vorschläge bleiben nicht endlos im Ladezustand. Geschützte folgende Umgebungen warten auf ihre Prüfungen, fixierte behalten ihre aktuelle Version.
