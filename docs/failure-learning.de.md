---
source_sha: "d80cae6dae16"
---

# Aus Fehlern lernen { #failure-learning }

Ein Agent, der immer wieder denselben Fehler macht, lernt nicht — er
wiederholt sich. Die Lernschleife aus Fehlern schürft die bereits gelaufenen
Läufe nach sich wiederholenden Fehlern, trägt sie in ein Verzeichnis ein
und prüft eine Korrektur am alten Verhalten, bevor irgendetwas angewendet
wird.

Phase 1 umfasst Schürfen, Verzeichnis, Evaluierungsfälle und Versuche.
Phase 2 fügt Vorschläge und das Anwenden einer Korrektur hinzu: Ein
Vorschlag hält eine Regeltextänderung mit ihrem Evaluierungsbeleg, und ein
Veröffentlichender wendet sie in einer einzigen auditierten Aktion an.
Phase 3 fügt die Konsolenseiten, die tägliche Zusammenfassung und die
Regelzählungen je Agent hinzu.

## Was sie schürft { #what-it-mines }

Schürfen ist Live-SQL über `agent_runs` und `message_ratings` — kein ETL,
kein Hintergrundjob. Standardmäßig blickt sie sieben Tage zurück und
erkennt vier Signale:

| Signal | Was zählt | Schwelle |
|---|---|---|
| Fehlgeschlagene Läufe | Läufe der obersten Ebene, keine Testläufe, gruppiert nach Agent, Modell, Status und Fehlerklasse | 3 pro Agent |
| Ein Fehler, der einem Modell folgt | Dieselbe Fehlerklasse für ein Modell bei mehreren Agenten | 5 über Agenten hinweg |
| Steckengebliebene Läufe | Ein Lauf, der noch `running` ist und dessen Heartbeat älter als 10 Minuten ist | 1 |
| Herabgestufte Antworten | Antworten des Assistenten mit −1 bewertet | 3 |

Die Fehlerklasse eines fehlgeschlagenen Laufs wird aus dem Satz gelesen,
den der Lauf aufgezeichnet hat: `ModelHTTPError` behält seinen Statuscode,
eine abgelaufene Genehmigung oder Frage ist eine eigene Klasse, ein
verbrauchtes Limit ist eine eigene Klasse, und Schleifen- und Budgetstopps
sind ebenfalls Klassen. Alles andere ist `other`.

Zwei Grenzen sind wissenswert. Ein Lauf, der in einem Modellaufruf steckt,
schlägt seinen Heartbeat weiter, also ist ein Hängen mit frischem Heartbeat
**nicht erkennbar** — steckengeblieben heißt nur, dass der Heartbeat
veraltet ist. Und eine herabgestufte Antwort wird dem nächsten Lauf
zugeordnet, der zuvor in derselben Unterhaltung gestartet wurde; eine
Nachricht ohne früheren Lauf hat keine Zuordnung und fällt weg.

## Das Verzeichnis { #the-ledger }

Ein Muster, das Handeln verdient, wird zu einem Eintrag im Verzeichnis: ein
Titel, eine Zusammenfassung, die Belege und ein Status — `draft`, `open`,
`dismissed` oder `resolved`. Ein Eintrag ist offen, solange er `draft` oder
`open` ist, und pro Muster und Bereich darf es nur einen offenen Eintrag
geben. Das setzt ein partieller Unique-Index durch, keine Konvention.

Einträge haben den Bereich eines Agenten oder eines Modells. Ein
Modelleintrag ist ein Datensatz für die ganze Organisation und erscheint
neben den Einträgen jedes Agenten. Ein Muster mit einem offenen Eintrag wird
beim Schürfen als `already_tracked` markiert, damit derselbe Fehler nicht
zweimal kuratiert wird.

Einen Eintrag zu lösen ist Aufgabe des Anwendens: Eine bloße Statusänderung
zu `resolved` wird abgelehnt, und nur das Anwenden eines Vorschlags gegen
den Eintrag löst ihn.

## Evaluierungsfälle { #eval-cases }

Ein Evaluierungsfall ist der Beweis, den eine Korrektur bestehen muss: eine
Eingabe und was ihre Antwort sagen soll. Ein Agent hat höchstens 50 Fälle.
Ein Fall nennt eine Erwartung — `equals`, `contains` oder `not_contains`
für den Antworttext oder den Laufstatus — und kann den Verzeichniseintrag
nennen, aus dem er stammt, einen Quelllauf, der den Fehler gezeigt hat, und
ein Modellprofil, unter dem er versucht werden soll.

## Eine Korrektur versuchen { #trying-a-fix }

Ein Versuch führt jeden Fall zweimal pro Stichprobe aus: einmal mit der
aktuellen veröffentlichten Spezifikation (die alte Seite) und einmal mit
derselben Spezifikation, deren Anweisungen ersetzt wurden (die neue Seite).
Jeder Lauf öffnet eine frische Testunterhaltung, läuft als Testlauf und wird
durch den `is_test`-Filter vom Schürfen ausgeschlossen. Stichproben sind
standardmäßig 1 und höchstens 5.

Das Tor ist streng. Eine Seite besteht nur, wenn ihr Lauf abgeschlossen
wurde **und** die Erwartung erfüllt ist — ein Lauf, der abgestürzt ist,
kann nicht durch Abstürzen bestehen. Ein Fall besteht nur, wenn die alte
Seite fehlschlägt und die neue Seite besteht, bei mehr als einer Stichprobe
mit der Mehrheit. Ein Versuch besteht nur, wenn jeder Fall besteht. Wenn die
alte Seite bereits besteht, wird der Fall als nicht reproduzierbar gemeldet:
„case does not reproduce - the old text already passes".

Urteile werden beim Lesen des Versuchs gefällt, nie gespeichert. Ein Lauf,
der noch läuft, lässt seinen Fall ausstehend.

Ein Versuch kann einen Entwurfsvorschlag statt einer
Anweisungsüberschreibung nennen: Er führt dessen neue Anweisungen oder
Skill-Inhalt aus und belegt damit genau diesen Vorschlag. Versuche speichern
die Vorschlags-ID und den SHA-256-Hash des getesteten Inhalts. Das Anwenden
wird verweigert, wenn der verknüpfte erfolgreiche Versuch nicht zu genau
diesem Vorschlag und Hash gehört.

Ein Versuch läuft synchron innerhalb der Anfrage und ist auf zehn Runs des
Agents begrenzt (zwei Seiten je Fall und Stichprobe). Jeder Run kann mehrere
Provider-Anfragen auslösen; dies ist also keine Grenze für Provider-Anfragen.
Größere Anfragen werden abgelehnt, bevor Runs starten. Hintergrundausführung
bleibt ein separates Folgethema.

## Vorschläge { #proposals }

Ein Vorschlag ist eine Regeltextänderung: der Text, den sie ersetzt, der
Text, der ihn ersetzt, warum, und der Evaluierungsversuch, der sie belegt.
Er nennt sein Ziel — die Anweisungen des Agenten oder einen Skill — und den
Verzeichniseintrag, aus dem er stammt, falls es einen gibt. Ein Vorschlag
ist `draft`, bis er angewendet oder abgelehnt wird; Anwenden ist die
Genehmigung, und es gibt keinen eigenen Genehmigungsschritt.

Ein Anweisungsvorschlag wird gegen die aktuelle veröffentlichte Version des
Agenten geschrieben, es sei denn, der Body nennt eine. Ein Skill-Vorschlag
wird gegen den Inhalt des Skills geschrieben, wie er steht, und hält dessen
SHA-256-Hash als Basis fest. Die Liste der angewendeten Änderungen ist die
Vorschlagsliste, gefiltert auf `status=applied`: Jeder Eintrag trägt die
Version, die er veröffentlicht hat, und den Versuch, der ihn belegt hat.

Auch Skill-Vorschläge brauchen einen erfolgreichen Evaluierungsversuch.
Die vorgeschlagene Skill-Fassung läuft dabei als In-Memory-Überschreibung
auf der Testseite; der gespeicherte Skill bleibt unverändert.

## Einen Vorschlag anwenden { #applying-a-proposal }

Anwenden ist eine menschliche Handlung eines Veröffentlichenden, in der
Transaktion der Anfrage, und sie wird auditiert. Für ein
Anweisungsziel verweigert das Anwenden, es sei denn, der verknüpfte Versuch
existiert und hat das Tor passiert, beurteilt wie seine Läufe in diesem
Moment stehen — ein Versuch, der fehlt, aussteht oder fehlgeschlagen ist,
kann nicht landen. Das ist das Tor, geprüft zum Zeitpunkt des Anwendens
statt gespeichert.

Zwei Wächter schützen die Veröffentlichung. Optimistische Nebenläufigkeit
verweigert mit 409, es sei denn, die aktuelle Version des Agenten ist noch
die Version, gegen die der Vorschlag geschrieben wurde — jemand hat seitdem
neu veröffentlicht, also schreibt der Vorschlagende den Vorschlag neu,
statt eine neuere Veröffentlichung zu überschreiben. Der Entwurfswächter
verweigert mit 409, wenn der Agent unveröffentlichte Entwurfsänderungen hat
— die laufende Arbeit eines Builders muss erst veröffentlicht oder
verworfen werden, weil das Anwenden über den Entwurf speichert.

Wenn die Wächter passiert sind, lädt das Anwenden den Entwurfsspec, setzt
seine Anweisungen auf den neuen Text des Vorschlags, speichert den Entwurf
und veröffentlicht ihn unter Nennung der Vorschlags-ID. Die veröffentlichte
Version ist der eingefrorene neue Text, und der Vorschlag hält sie als
Rollback-Griff fest. Der verknüpfte Verzeichniseintrag, falls es einen gibt,
wird als gelöst markiert, und der Audit-Eintrag hält Vorschlag, Version,
Versuch und Basisversion fest.

Das Anwenden eines Skills benötigt einen erfolgreichen verknüpften Versuch
und speichert den exakten Hash des neuen Inhalts. Es verweigert mit 409, wenn
der aktuelle Skill nicht mehr dem Basishash des Vorschlags entspricht.
Vor der Änderung wird der vorherige Inhalt im Vorschlag gespeichert. Der
einmalige Wiederherstellungs-Endpunkt setzt diese Kopie nur zurück, solange
der Skill noch den angewendeten Hash hat. Er erfasst die wiederherstellende
Person und einen Audit-Eintrag und überschreibt niemals spätere Änderungen.

Das Rückgängigmachen eines Anweisungs-Anwendens ist das bestehende
Rollback: Veröffentliche eine neue Version, die aus der Basisversion
kopiert ist, die der Vorschlag festgehalten hat. Es gibt dafür keinen
eigenen Endpunkt der Schleife. Eine Ablehnung wird mit ihrem Grund in der
Audit-Spur festgehalten — die Vorschlagszeile selbst trägt keine
Entscheidungsnotiz.

## Die Konsole { #the-console }

Die Schleife lebt in der Konsole, auf der Agentenseite und auf einer
organisationsweiten Seite. Die Agentenseite trägt eine Registerkarte Aus
Fehlern lernen; die organisationsweite Seite listet die Muster aller
Agenten an einem Ort, in der Navigation unter Überwachung. Lesen braucht
`agents:view`; Kuratieren braucht `agents:edit`, das Anwenden eines
Anweisungsvorschlags braucht `agents:publish`, und das Anwenden eines
Skill-Vorschlags braucht `skills:edit` auf dem Skill.

### Muster { #patterns }

Das Musterfeld listet, was die letzten sieben Tage geschürft haben, mit
der Anzahl und ob das Muster bereits verfolgt wird. Die Vorbehalte des
Schürfens stehen neben den Zahlen, nicht versteckt: Muster je Modell sind
ungefähr, ein Hängen mit frischem Herzschlag ist nicht erkennbar, und eine
herabgestufte Antwort wird nur ungefähr zugeordnet. Das Verfolgen eines
Musters aus dem Feld öffnet das Verzeichnisformular mit dem Muster
bereits eingetragen.

### Verzeichniseinträge { #ledger-entries }

Das Verzeichnis listet Einträge mit einem Statusfilter, und wer einen
auswählt, sieht seine Evaluierungsfälle und Vorschläge. Das Annehmen
eines Entwurfs öffnet ihn; das Ablehnen fragt nach einem Grund, und der
Grund bleibt am Eintrag, damit der Datensatz überlebt. Das Löschen eines
Eintrags entfernt ihn — seine Evaluierungsfälle behalten, was sie
sagten, und vermerken den Eintrag als verschwunden.

### Evaluierungsfälle und Versuche { #eval-cases-and-tries }

Das Fallfeld listet jeden Fall mit dem Urteil seines neuesten Versuchs.
Ein Fall entsteht aus dem Lauf, der den Fehler gezeigt hat: Gib die
Quelllauf-ID an und lade dessen letzte Nutzernachricht, mit den
vorangehenden Runden als Verlauf, dann kürze die Nachricht auf den
fehlerhaften Teil und schreibe, was die Antwort sagen sollte. Ein
Versuch läuft über die angehakten Fälle, mit einer Stichprobenzahl und
entweder dem neuen Text eines Vorschlags im Entwurf oder einer
getippten Überschreibung — niemals beidem. Anfragen für mehr als zehn Runs
des Agents werden vor der Ausführung abgelehnt. Ein Versuch,
der das Evaluierungstor passiert, bietet seinen Text als Vorschlag an,
vorbefüllt mit dem Versuch als seinem Beleg.

### Vorschlagsprüfung { #proposal-review }

Wer einen Vorschlag auswählt, sieht die Änderung als Diff, den
Evaluierungsbeleg mit seinen Torurteilen je Fall und die Aktionen zum
Anwenden und Ablehnen. Ein Anweisungsvorschlag wird erst angewendet,
wenn sein Versuch das Evaluierungstor passiert hat, und nur ein Inhaber
von `agents:publish` sieht die Anwenden-Schaltfläche. Auch ein
Skill-Vorschlag braucht einen erfolgreichen Versuch für genau seinen Inhalt.
Seine Wiederherstellung setzt den gespeicherten Skill-Inhalt zurück, sofern
niemand den Skill seit dem Anwenden geändert hat. Ein angewendeter Vorschlag
hält die veröffentlichte Version fest, mit dem Rollback-Hinweis: zurück zur
gespeicherten Basisversion.

### Wie viele Regeln leben { #how-many-rules-are-live }

Oben auf der Registerkarte steht, wie viele Regeln die Schleife in
diesen Agenten gebracht hat: angewendete Vorschläge, offene Einträge und
gelöste Einträge, als drei getrennte Zahlen. Angewendete Vorschläge sind
die Regeln, die jetzt in den Anweisungen leben. Offene Einträge sind
die Regeln, an denen noch gearbeitet wird — ein Eintrag ist offen,
solange er Entwurf oder offen ist. Ein gelöster Eintrag ist sein
angewendeter Vorschlag, also werden die beiden getrennt gezählt, niemals
addiert: Sie zu addieren würde eine Regel doppelt zählen.

Diese Zahl ist eine Aufforderung, kein Urteil. Regeln häufen sich an —
jeder angewendete Vorschlag ist ein Satz, den der Agent neben allen
anderen einhalten muss — also prüfe die lebenden Regeln einmal im
Quartal nach: Lies die Liste der angewendeten Änderungen, und nimm die
zurück, die der Agent nicht mehr braucht, indem du die Anweisungen
bearbeitest, statt sie liegen zu lassen, bis sie neu gelernt werden.

## Die tägliche Zusammenfassung { #the-daily-digest }

Einmal am Tag schürft ein geplanter Job — `failure-ledger-digest` — die
letzten sieben Tage für jede Organisation und legt jedes neue Muster als
Entwurfseintrag im Verzeichnis ab, dann mailt er eine Zusammenfassung je
Organisation, die etwas Neues hat, an den konfigurierten Empfänger des
Deployments. Eine Organisation ohne Neues bekommt keine Mail. Die
Einträge sind Entwürfe, niemals offen: Ein Entwurf ist ein Muster, das
das Schürfen gefunden hat, nicht eines, das ein Kurator angenommen hat.

Der Empfänger ist Konfiguration, kein Standardwert. Setze
`FAILURE_LEARNING_DIGEST_RECIPIENT` auf die Adresse, an die die
Zusammenfassungen gehen; solange sie leer ist, protokolliert der Job einen
No-op und legt keine Entwurfseinträge an oder schickt Mail. Es
ist eine Adresse für das ganze Deployment, also sieht sie die
Zusammenfassung jeder Organisation: Mach sie zu einer
Operatoradresse, nicht zu der eines Mitglieds. Siehe
[die Einstellungsreferenz](configuration.md#email-smtp).

## Berechtigungen { #permissions }

| Route | Berechtigung |
|---|---|
| `GET /v1/failure-learning/patterns` | `runs:view` |
| Lesezugriffe auf Muster, Verzeichnis und Evaluierung pro Agent | `agents:view` |
| Schreibzugriffe auf Verzeichnis, Fälle und Versuche pro Agent | `agents:edit` |
| Eine Änderung vorschlagen, einen Vorschlag ablehnen | `agents:edit` (Anweisungen) / `skills:edit` (Skill-Ziel) |
| Einen Anweisungsvorschlag anwenden | `agents:publish` |
| Einen Skill-Vorschlag anwenden | `skills:edit` auf dem Skill |

Nur die organisationsweite Musterliste trägt ein Routen-Gate. Die Routen
pro Agent lösen den Zugriff auf den Agenten innerhalb des Dienstes auf, und
eine Ablehnung liest sich als „nicht gefunden" — ein Betrachter mit einer
expliziten Gewährung für einen Agenten wird also nicht abgewiesen, bevor die
Gewährung geprüft wurde.

## API { #api }

| Methode | Pfad | Beschreibung |
|---|---|---|
| `GET` | `/v1/failure-learning/patterns` | Organisationsweite Muster |
| `GET` | `/v1/agents/{agent_id}/failure-learning/patterns` | Muster eines Agenten |
| `GET` | `/v1/agents/{agent_id}/failure-learning/ledger` | Verzeichniseinträge auflisten |
| `POST` | `/v1/agents/{agent_id}/failure-learning/ledger` | Ein Muster kuratieren |
| `GET` | `/v1/agents/{agent_id}/failure-learning/ledger/{entry_id}` | Ein Eintrag |
| `PATCH` | `/v1/agents/{agent_id}/failure-learning/ledger/{entry_id}` | Annehmen, ablehnen, umschreiben |
| `DELETE` | `/v1/agents/{agent_id}/failure-learning/ledger/{entry_id}` | Einen Eintrag entfernen |
| `GET` | `/v1/agents/{agent_id}/failure-learning/eval-cases` | Evaluierungsfälle auflisten |
| `POST` | `/v1/agents/{agent_id}/failure-learning/eval-cases` | Einen Fall hinzufügen |
| `DELETE` | `/v1/agents/{agent_id}/failure-learning/eval-cases/{case_id}` | Einen Fall entfernen |
| `POST` | `/v1/agents/{agent_id}/failure-learning/eval-runs` | Einen Versuch starten |
| `GET` | `/v1/agents/{agent_id}/failure-learning/eval-runs/{try_id}` | Einen Versuch lesen, beurteilt wie er steht |
| `POST` | `/v1/agents/{agent_id}/failure-learning/proposals` | Eine Änderung vorschlagen |
| `GET` | `/v1/agents/{agent_id}/failure-learning/proposals` | Vorschläge auflisten; `status=applied` ist die Liste der angewendeten Änderungen |
| `GET` | `/v1/agents/{agent_id}/failure-learning/proposals/{proposal_id}` | Ein Vorschlag, mit seinem Evaluierungsbeleg |
| `POST` | `/v1/agents/{agent_id}/failure-learning/proposals/{proposal_id}/apply` | Einen Vorschlag anwenden, auditiert |
| `POST` | `/v1/agents/{agent_id}/failure-learning/proposals/{proposal_id}/reject` | Einen Vorschlag ablehnen, mit einem Grund |

Das Starten eines Versuchs ist auf der `agent_eval_run`-Fläche limitiert,
und jeder Seitenlauf zählt gegen das Budget des Aufrufers wie jeder Lauf.
Ein Versuch, der eine `proposal_id` nennt, führt den neuen Text dieses
Vorschlags aus; einen Vorschlag und eine Überschreibung zugleich zu nennen,
wird abgelehnt.

## Häufig gestellte Fragen { #frequently-asked-questions }

### Warum erscheint ein Fehler, den ich sehen kann, nicht als Muster? { #why-does-a-failure-i-can-see-not-appear-as-a-pattern }

Er liegt unter einer Schwelle, außerhalb des Sieben-Tage-Fensters, ist ein
Testlauf oder ein delegierter Lauf. Delegierungen werden innerhalb ihres
Elternlaufs gezählt, und Testläufe sind die eigenen Versuche der Schleife —
beides zu schürfen hieße, von sich selbst zu lernen.

### Warum hat mein Versuch so lange gedauert? { #why-did-my-try-take-so-long }

Versuche laufen synchron: Jeder Fall wird zweimal pro Stichprobe ausgeführt,
ein Run des Agents nach dem anderen, innerhalb der Anfrage. Ein Versuch kann
höchstens zehn Runs starten; jeder Run kann mehrere Provider-Anfragen auslösen.

### Kann ein Versuch ändern, was mein Agent sagt? { #can-a-try-change-what-my-agent-says }

Nein. Beide Seiten laufen als Testläufe gegen eine eingefrorene Kopie der
Spezifikation. Der veröffentlichte Agent bleibt unberührt, bis ein Vorschlag
angewendet wird.

### Was, wenn der Agent neu veröffentlicht wurde, seit ich vorgeschlagen habe? { #what-if-the-agent-was-republished-since-i-proposed }

Das Anwenden verweigert mit 409. Schreibe den Vorschlag gegen die neue
Version neu — gegen das, was der Agent jetzt veröffentlicht — statt die
neuere Veröffentlichung zu überschreiben.

### Wie mache ich ein Anwenden rückgängig? { #how-do-i-undo-an-apply }

Kehre zur im Vorschlag gespeicherten Basisversion zurück: Das bestehende
Rollback veröffentlicht eine neue, daraus kopierte Version, sodass die
Zeitleiste den Vorgang zeigt. Das Anwenden eines Skills lässt sich einmal
aus seiner Kopie zurücksetzen, solange der Skill noch den angewendeten Inhalt hat.

### Was passiert, wenn ich eine Skill-Änderung anwende? { #what-happens-when-i-apply-a-skill-change }

Jeder Agent, der an den Skill gebunden ist, führt den neuen Inhalt bei
seinem nächsten Lauf aus. Der Vorschlag braucht einen erfolgreichen Versuch
für genau diesen Inhalt und kann einmal wiederhergestellt werden, wenn seit
seiner Anwendung niemand den Skill geändert hat.

### Wo sehe ich die neuen Muster jeden Tag? { #where-do-i-see-the-new-patterns-each-day }

Im Posteingang, wenn das Deployment einen Empfänger für die Zusammenfassung
konfiguriert hat — eine Mail je Organisation mit etwas Neuem. Fehlt der Empfänger
oder gibt es nichts Neues, wird die Untätigkeit protokolliert. Außerdem stehen
die Muster auf der organisationsweiten Seite für alle Agents an einem Ort.
