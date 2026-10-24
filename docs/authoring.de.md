---
source_sha: "1440cbfd57d8"
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
  fehlgeschlagenen Runs vorschlagen.
- Ihre eigenen Änderungen **prüfen**: den Entwurf mit der Version, auf der er
  beruht - der zuletzt veröffentlichten -, anhand derselben Belege vergleichen und
  sagen, was die Änderungen verbessern, riskieren und entfernt haben.
- **Einen Skill** oder **eine Context-Datei verbessern**: einen neuen Inhalt aus
  den Runs vorschlagen, die sie gelesen haben.

Der Assistent ist ein eigener [System-Agent](datasets.md#judge), aufgeführt mit
den übrigen System-Agents der Organisation. Seine Anweisungen lassen sich wie die
jedes Agents bearbeiten, und seine Runs sind gewöhnliche Runs: budgetiert,
bepreist und in **Aktivität** (Activity) aufgeführt.

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

Endet eine Verbesserungsanfrage bei geöffnetem Builder, zeigt ein Ergebnisdialog die Anzahl geprüfter Antworten, vorgeschlagene und gespeicherte Änderungen sowie abgelehnte Vorschläge mit Gründen. **Ergebnis ansehen** öffnet ihn erneut. Änderungen zeigen Vorher und Nachher nebeneinander mit Begründung und verlinkten Belegen. Ein leeres Ergebnis erklärt, dass nichts anwendbar war, ohne erwartete Wirkung. Wirkungstext mit rohen Run-Kennungen wird durch eine Beschreibung mit der Anzahl verlinkter Quellantworten ersetzt.

Nach einer abgeschlossenen Prüfung können Leser mit `runs:view` Antworten beider Seiten im Dialog vergleichen und die vollständige Prüfung öffnen. Vorher fordert der Dialog zum Prüfen auf. Ohne bewertete Chats oder Trainingsbelege erscheint der Assistent als kompakte Zeile über den Anweisungen.

## Vorschläge { #suggestions }

Verbessern und Prüfen öffnen die **Assistentenleiste** auf dem Tab **Bauen**
(Build) des Agents. Jeder Vorschlag zeigt die Passage, die er ändert, in ihrem Umfeld, die
Begründung und die Belege, und über jeden wird einzeln entschieden:

| Aktion | Was passiert |
|---|---|
| **Annehmen** | Die Änderung wird in den Entwurf geschrieben. Nichts wird veröffentlicht. |
| **Bearbeiten** | Ihre eigene Formulierung wird statt des Vorschlags angenommen. |
| **Verwerfen** | Festgehalten; eine spätere Anfrage schlägt es nicht wieder vor. |
| **Rückgängig** | Kehrt die Entscheidung um, solange sie noch zum Entwurf passt. |

Ein Vorschlag verankert sich daran, wo seine Passage stand und was sie umgab,
nicht am Text allein, sodass eine Zeile, die zweimal vorkommt, dort geändert
wird, wo es gemeint war. Hat sich der Entwurf weiterbewegt - die Passage wurde
entfernt oder eine Tool-Beschreibung von Hand geändert -, sagt der Vorschlag, dass
er **nicht mehr zum Entwurf passt**, und lässt sich nur verwerfen. Rückgängig
verweigert sich ebenso, wenn der angenommene Text danach von Hand bearbeitet
wurde: Es würde diese Änderung verwerfen.

Ein neueres Verbessern ersetzt die wartenden Vorschläge; Prüfen fügt seine
stattdessen hinzu. Das Veröffentlichen des Entwurfs schließt sie: Ihre
Entscheidungen sind endgültig, und die Leiste behält sie als Protokoll.

Eine Änderung, die der Assistent vorschlägt und die sich nicht speichern lässt,
verschwindet nicht stillschweigend. Die Leiste führt sie unter **vorgeschlagene
Änderungen wurden nicht gespeichert** auf, mit dem Grund: Die Stelle, die sie
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

Jeder Fall wird fest dem Training oder der Kontrolle zugeordnet, auch über Dataset-Versionen hinweg. Die Dataset-Einstellungen bestimmen den Kontrollanteil nur für künftige Fälle (standardmäßig 50%). Vorschlagsprüfungen und Verbesserungssitzungen messen ausschließlich Kontrollfälle und benötigen mindestens fünf bewertbare Fragen. Kopien von Trainingsfragen oder Quellbelegen werden anhand normalisierter Eingaben und der Quell-Run-ID ausgeschlossen, auch bei manueller Eingabe oder Generierung. Unter dem Minimum stoppt eine Sitzung mit `no_data` und nennt die fehlende Anzahl. Der Run kennzeichnet beide Teile und ausgeschlossene Kopien. Normale Suites und Beförderungsschranken zählen weiterhin alle Fälle.

Eine Verbesserungssitzung fixiert Dataset-Version und Chat-Belegidentitäten. Spätere Runden können aus den Trainingsergebnissen dieser Version lernen; neue Chats und Fälle ändern die Kontrollstichprobe nicht.

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

Die API koordiniert Verbesserungen im Hintergrund. Senden Sie zunächst Dataset
oder Suite und Rundengrenze an `/agents/{agent_id}/improvements/estimate`, danach
dasselbe Ziel mit `budget_usd` an `/agents/{agent_id}/improvements`. Die gesamte
Schätzung enthält Vorschläge, beide Eval-Seiten, Richter, bestätigende Versuche
und eine Wiederholung eines unentschiedenen Vergleichs je Runde. Ein bezahlter
Schritt startet nur, wenn seine volle Schätzung ins verbleibende Sitzungsbudget
passt. Ein begonnener Schritt darf enden; tatsächliche Kosten bleiben auch nach
einem Abbruch sichtbar.

Die Sammlung oder einzelne Sitzung zeigt gespeicherte Schritte, Aufgaben-IDs,
Urteile und Kosten. Ersteller oder Organisationsadministratoren können
`/{run_id}/cancel` in dieser Sammlung aufrufen. Der Worker prüft vor jedem Schritt
die aktuellen Rechte des Erstellers, Entwurf, letzte Veröffentlichung, Bewertung
und Suite-Pin. Geänderte Eingaben machen die Sitzung veraltet; verlorene Rechte
stoppen sie. Pro Agent darf nur eine Sitzung laufen.

Eine geprüfte Verbesserung endet bei `ready`: Ihr Kandidat wird zum wartenden
Vorschlagspaket. Die Sitzung übernimmt, veröffentlicht oder befördert nichts.
Frühere Kandidaten ersetzen während der Prüfung keine wartenden menschlichen
Vorschläge. Eine Benachrichtigung führt den Ersteller zur fertigen oder gestoppten
Sitzung.

Sitzungen führen höchstens drei Runden aus. Eine Regression oder ein unverändertes Ergebnis startet nur dann einen weiteren Vorschlag, wenn dessen vollständige Schätzung ins Restbudget passt. Zwei unveränderte Runden, zwei unentschiedene Runden, ein bereits getesteter Kandidat oder das Rundenlimit stoppen die Schleife mit gespeichertem Grund. Trainingsantworten vor und nach der Änderung informieren die nächste Runde; Kontrolldaten bleiben verborgen. Rundenkosten sind getrennt. Die beste gemessene Runde bevorzugt Verbesserung, weniger neue Fehler, dann höhere entschiedene Erfolgsquote.

Nach Abschluss macht `/{run_id}/rounds/{number}/select` eine gemessene Runde zum wartenden Kandidaten, nach erneuter Prüfung von Basis und Zugriff. Die optionale Zuordnung von Wirkungen zu Änderungen nutzt `.../attribution/estimate` und `.../attribution`. Der Start verlangt `confirmed: true` und die geprüfte Summe `estimate_usd`; eine höhere neue Schätzung wird abgelehnt. Jede wartende Änderung wird einzeln gegen dieselbe Basis und fixierte Fragen getestet. Die Kosten belasten das Sitzungsbudget. Die Zuordnung akzeptiert oder veröffentlicht nichts und ersetzt nicht das gemeinsame Rundenurteil.

Öffnen Sie **Verbessern** im Agentenkopf oder Dashboard, um eine Sitzung unter `/agents/<agent>/improve/<session>` zu starten. Die Seite lässt sich schließen und bei laufender Hintergrundarbeit erneut öffnen. Wählen Sie Testfragen, prüfen Sie die vollständige Kostenschätzung und bestätigen Sie ein Ausgabenlimit. Ohne Fragen schätzen und bestätigen Sie zuerst das Schreiben eines Testsatzes; die Ausgangswert-Aktion prüft die heutigen Antworten. Erweiterte Hilfsagenten bleiben eingeklappt.

Ein fehlgeschlagener Vorschlags- oder Eval-Schritt lässt sich ausdrücklich mit `/{run_id}/retry` wiederholen; mehrfache Klicks erzeugen kein weiteres Kind. Automatische Job-Wiederholungen wiederholen keinen bezahlten Aufruf. Menschliche Entscheidungen setzen den Sitzungsstatus auf angenommen, veröffentlicht oder verworfen. Die bestätigte Aktion `/{run_id}/finish` übernimmt die geprüften Änderungen und veröffentlicht sie optional in derselben Transaktion. Sie kann eine Suite bei Veröffentlichung mit null erlaubten Regressionen anlegen. Übliche Berechtigungen und Veröffentlichungsprüfungen gelten weiterhin; geschützte Umgebungen warten auf ihre Prüfungen. Nach der Messung bearbeitete Vorschläge müssen erneut geprüft werden.

### Einen neuen Skill vorschlagen { #proposing-a-new-skill }

Der Assistent kann **Ein Skill wäre sinnvoll** vorschlagen, wenn ein wiederverwendbarer Ablauf in mindestens drei verschiedenen Quellantworten vorkommt. Jede Textstelle muss in der Antwort selbst stehen; Kommentare allein belegen keinen wiederholten Ablauf. Die Karte zeigt Name, Beschreibung, vollständigen Inhalt, Begründung und geprüfte Belege. Eine Evaluation bindet einen temporären Skill nur an den Kandidaten: Sie erstellt weder einen Skill-Datensatz noch eine veröffentlichte Version.

**Accept** erstellt den privaten Skill und bindet ihn in derselben Transaktion an den Entwurf des Agenten. Dafür sind `skills:edit` und Bearbeitungszugriff auf den Agenten nötig. Ohne Erstellungsrecht bleibt der Vorschlag lesbar und prüfbar; die deaktivierte Annahme erklärt den Grund. **Dismiss** erstellt nichts. **Undo** entfernt die Bindung und behält den unabhängigen Skill. Erneutes Annehmen verwendet ihn nur bei unverändertem Namen und Inhalt. Skills enthalten Anweisungen und gewähren keine Tools. Zusätzlicher Tool-Zugriff benötigt eigene Richtlinienprüfungen; schreibende Tools erfordern eine Freigabe.

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
