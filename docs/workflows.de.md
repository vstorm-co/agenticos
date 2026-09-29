---
source_sha: "414894e5a034"
---

# Workflows { #workflows }

Ein **Workflow** verkettet Schritte zu einer Automatisierung, die Ihre Agents
ausführen: eine [Tabelle](virtual-tables.md) lesen, einen Agent aufrufen, auf das
Ergebnis verzweigen, über eine Liste iterieren. Sie bauen ihn auf einer
Zeichenfläche, verdrahten die Schritte miteinander und veröffentlichen ihn als
unveränderliche Version — dieselbe Form, die ein [Agent](concepts.md) hat: ein
Draft, den Sie bearbeiten, und eine veröffentlichte Version, die läuft.

Diese Seite beschreibt den visuellen Editor: die Liste, die Zeichenfläche und die
Palette, wie ein Knoten konfiguriert wird, Autosave und Veröffentlichen sowie die
Tastaturwege durch all das. Der Editor liegt unter **Workflows** in der Konsole.
Die **Liste** unter Workflows hat ein **"?"**, das eine Führung durch diese Liste
abspielt; der Editor selbst hat keine Führung.

## Einen Workflow erstellen und duplizieren { #creating-and-duplicating-a-workflow }

**New workflow** öffnet einen Dialog, der Sie mit einem Trigger oder einer Vorlage
beginnen lässt. **How does it start?** bietet die fünf Trigger an - **Manual or
API**, **Chat message**, **Webhook**, **Schedule** und **New table record** -, jeder
eine sonst leere Zeichenfläche, die mit ihm beginnt. Die Vorlagen sind fertige
Ausgangspunkte — **Starter**, ein
einzelner Schritt zum Umbenennen und Verdrahten, und **Two-step sequence**, zwei
bereits verbundene Schritte für einen linearen Ablauf. Wählen Sie eine mit **Use**,
und Sie landen im Editor.

Die Liste zeigt jeden Workflow, den Sie sehen können, als Karte: seinen Status,
wer ihn erreichen kann, ob eine Version live ist und wann er zuletzt bearbeitet
wurde. **Filter by status** grenzt sie auf **Drafts** ein, die Sie noch bauen, auf die
**Published**, die laufen, oder auf die **Archived**. Von einer Karte aus öffnen Sie
den Editor, die Runs des Workflows oder eine Kopie.

**Duplicate** kopiert den aktuellen Draft eines Workflows in einen frischen namens
*{name} (copy)*. Ein Duplikat ist ein neuer Workflow mit eigenem Draft, nie eine
Kopie einer veröffentlichten Version.

!!! info "Eine leere Liste kann ein Filter sein, keine leere Organisation"

    **No workflows yet** und **Nothing matches** sind unterschiedliche Zustände:
    Das erste ist eine Organisation ohne Workflows, das zweite ein Statusfilter,
    unter den keine Zeile fällt. **Clear filter** bringt die volle Liste zurück.
    Ein mit Ihnen geteilter Workflow erscheint in derselben Liste, sobald Sie
    `workflows:view` haben.

## Die Zeichenfläche und die Palette { #the-canvas-and-the-palette }

Die **Zeichenfläche** ist der Ort, an dem die Schritte und Verbindungen eines
Workflows erscheinen, und der Editor gibt ihr das ganze Fenster unter der
Kopfzeile: die Palette links, das **Properties**-Panel rechts. Ein **Knoten** ist ein
Schritt; eine **Kante** ist eine Verbindung, die die Reihenfolge festlegt: Der
Schritt, auf den sie zeigt, läuft nach dem, von dem sie ausgeht.

Jeder Knoten ist
eine Karte mit dem Icon des Schritts, seinem Namen und einer Zeile dazu, wofür er
eingerichtet ist - eine Bedingung, eine URL, die Zahl gemappter Felder -, und ein
Schritt mit mehr als einem Ausgang nennt seine Ports beim Namen: **true** und
**false**, **Each item** und **Done** und einen roten **Error**-Port bei einem
Schritt, der seine Fehler behandelt. Ein Trackpad oder das Mausrad verschiebt die
Zeichenfläche, und ein Zusammenziehen der Finger - oder Strg bzw. Cmd mit dem Rad -
zoomt sie; ihre Bedienelemente sitzen in der Ecke, eine Minimap gibt es nicht.

Die **Nodes**-Palette listet die Knotentypen, die Ihr Deployment registriert hat,
in Gruppen, die der Lesart eines Workflows folgen - **Start and finish**, **Agents**,
**Knowledge**, **Data**, **Tables**, **Branching**, **Loops**, **Errors** -, jede
Gruppe lässt sich einklappen, jede Zeile hat Icon, Namen und Beschreibung. **Search
nodes** filtert die Liste. Sie fügen einen Schritt auf drei Wegen hinzu:

- **Klicken** Sie einen Knoten in der Palette an oder drücken Sie darauf Enter: Er
  wird nach dem ausgewählten Schritt oder am Ende des sichtbaren Ablaufs
  hinzugefügt und mit ihm verbunden, wenn die Ports passen - ein gerader Ablauf ist
  eine Folge von Klicks. Ein Startschritt wie **Input** kommt stattdessen vor den
  aktuellen Start und wird selbst zum Start.
- **+** neben dem Ausgang eines Schritts öffnet eine Suche der Schritte, die danach
  kommen können, und fügt den gewählten nach diesem Ausgang hinzu.
- **Ziehen** Sie einen Knoten aus der Palette, um ihn genau dort abzulegen, wo Sie
  ihn fallen lassen, ohne Verbindung.

Ein neuer Schritt landet nie auf einem anderen, wird ausgewählt, sodass sich seine
**Properties** öffnen, und die Zeichenfläche scrollt zu ihm, wenn er außerhalb der
Ansicht liegt. Im Körper einer Schleife wird jeder neue Schritt in den Körper
verbunden und bleibt so darin.

Die Palette zeigt, was dort gültig ist, wo Sie gerade sind. **Loop item** und
**Loop result** erscheinen nur im Körper einer Schleife, weil sie außerhalb davon
nichts bedeuten, und eine Schleife wird angeboten, bis Schleifen so tief
verschachtelt sind, wie das Veröffentlichen erlaubt.

!!! note "Der Knotenkatalog wächst mit der Zeit"

    Die Palette wird von den registrierten Knoten des Deployments gespeist, nicht
    von einer festen Liste. Anfangs ist der Katalog klein; mehr Knotenarten —
    einen Agent aufrufen, eine Tabelle lesen und schreiben, verzweigen und in
    Schleifen laufen — kommen hinzu, sobald spätere Milestones sie registrieren,
    und sie erscheinen in genau dem Moment in der Palette, ohne Änderung an einem
    Workflow, den Sie bereits gebaut haben.

## Einen Knoten konfigurieren { #configuring-a-node }

Was jeder Knoten tut, womit er konfiguriert wird und was seine Fehler bedeuten,
steht in der [Knotenreferenz](reference/workflow-nodes.md).

Wählen Sie einen Knoten, und das Panel **Properties** öffnet sich rechts. Seine
Felder fallen in zwei Abschnitte. **Configuration** hält statische Einstellungen —
die festen Entscheidungen, die sich von einem Run zum nächsten nicht ändern,
einschließlich der Ressourcen, an die ein Schritt gepinnt ist. **Inputs** hält die
Werte, die ein Schritt beim Laufen liest.

Ein Input wird auf eine von zwei Arten gefüllt, und der Umschalter **Bind** neben
dem Feld wechselt zwischen ihnen:

- **Ein Literal** — Sie tippen den Wert direkt in das Feld, mit genau dem
  Bedienelement, das der Typ des Feldes verlangt.
- **Ein Binding** — Sie lesen den Wert aus der Ausgabe eines anderen Schritts.
  **Bind** verwandelt das Feld in eine **Source**-Auswahl, deren Optionen die
  vorgelagerten Ausgaben sind, die hier tatsächlich erreichbar sind und einen
  kompatiblen Typ tragen — die ganze Ausgabe eines Schritts oder ein Feld darin —,
  jede angezeigt als *{node} · {port} ({type})*, ein Feld als
  *{node} · {port} → {field} ({type})*. Ein Feld ohne etwas Kompatibles davor sagt
  **No compatible upstream outputs**, statt eine ungültige Auswahl anzubieten.

Ein Pflicht-Input ohne Wert ist ein Validierungsproblem, das am Knoten markiert und
nicht mit einem stillen Standardwert gefüllt wird. Einige Felder halten
strukturierte Werte: eine Liste von Zeilen, zu der Sie mit **Add row** hinzufügen,
die Sie umsortieren und entfernen, oder eine typisierte Auswahl, die das Sub-Formular
darunter austauscht. Das Panel steigt rekursiv in diese hinein, statt Sie auf einen
eigenen Bildschirm zu schicken.

Wählen Sie mehr als einen Knoten, meldet das Panel, wie viele ausgewählt sind;
wählen Sie eine Kante, zeigt es **From** und **To** der Verbindung.

### Ressourcen-Auswahlfelder { #resource-pickers }

Eine Einstellung, die eine Ressource pinnt, öffnet ein Auswahlfeld statt eines
Freitextfeldes, sodass ein Schritt eine reale Sache benennt, die Ihre Organisation
hat:

| Auswahlfeld | Was es pinnt |
|---|---|
| **Agent** und **Version** | Einen Agent, dann eine seiner veröffentlichten Versionen. Ein Wechsel des Agents löscht die gepinnte Version, weil eine Version zu einem Agent gehört |
| **Table** und **Columns** | Eine [Virtual Table](virtual-tables.md), dann die Spalten, die der Schritt liest — begrenzt auf das aktuelle Schema dieser Tabelle |
| **Secret** | Ein [Vault](secrets.md)-Secret, per Referenz. Ein Schritt speichert die id des Secrets, nie seinen Wert |

Jedes Auswahlfeld unterscheidet gleichnamige Zeilen durch Kontext und markiert
eine Referenz, deren Ziel verschwunden ist. Die Auswahlfelder **Agent** und
**Secret** bieten zusätzlich einen Link zum Neuanlegen — immer, nicht nur wenn die
Liste leer ist — während das **Table**-Auswahlfeld keinen hat. Eine Tabelle, deren Schema sich seit dem Binden geändert
hat, sagt es und bietet **Rebind to the current schema** an, sodass ein veralteter
Spaltensatz eine sichtbare Aufforderung ist statt eines stillen Bruchs.

### Wenn ein Schritt langsam ist oder fehlschlägt { #when-a-step-is-slow-or-fails }

Unter den Feldern eines Schritts legt **When it is slow or fails** seine Policy
fest. **Handle errors** gibt dem Schritt einen **Error**-Port: Ein Fehler, den seine
Wiederholungen nicht erledigt haben, verlässt ihn darüber, zu einem **Handle
error**-Schritt oder was immer Sie anschließen, statt den Run fehlschlagen zu lassen.
**Tries** ist, wie oft der Schritt insgesamt versucht wird, und **Wait between tries**
und **First wait** legen die Pause zwischen den Versuchen fest. Ein Schritt, dessen
Aufruf nicht sicher wiederholbar ist, etwa das Ausführen eines Agenten, sagt das und
wird nie wiederholt. **Time limit** bricht einen Aufruf nach so vielen Sekunden ab.
Was jede Einstellung zur Laufzeit tut, steht in der
[Knoten-Referenz](reference/workflow-nodes.md#error-handling).

Ein Binding an einen Wert ohne deklarierte Form - das aktuelle Element einer
Schleife, den Payload eines Triggers - bietet unter der Quelle ein Feld **Field inside
it**, in das Sie den Pfad innerhalb dieses Werts tippen, etwa `record_id` oder
`fields.Email`. Der Run prüft diesen Pfad, wenn der Schritt ausgeführt wird, denn nur
der Run weiß, was der Wert enthält.

## Verbindungen und foreach-Scope { #connections-and-foreach-scope }

Sie ziehen eine Kante, indem Sie einen Ausgangs-Port eines Knotens mit einem
Eingangs-Port eines anderen Knotens verbinden. Der Editor lehnt eine Verbindung
zwischen Ports, die unterschiedliche Formen tragen, ab, bevor er sie zeichnet,
sodass eine inkompatible Verbindung nie auf der Zeichenfläche landet.

Eine Kante legt fest, in welcher Reihenfolge die Schritte laufen; sie bewegt keine
Daten. Die Werte, die ein Schritt liest, sind seine **Bindings**, beschrieben unter
[Einen Knoten konfigurieren](#configuring-a-node).

Damit Sie nicht jedes Feld von Hand
binden müssen, bindet das Verbinden zweier Ports, die genau dieselbe Form tragen — etwa
die Ausgabe eines Echo mit der Eingabe eines Relay —, auch jeden Input des Ziels an das
gleichnamige Feld der Quelle. Ein Feld, das Sie schon gebunden hatten, bleibt unberührt.

Unterscheiden sich die Formen oder trägt ein Port keine Daten, wird nichts gebunden und
Sie wählen jede Quelle selbst mit **Bind**. Undo (`Ctrl`/`Cmd` + `Z`) nimmt die Verbindung samt ihren
Bindings zurück, und das spätere Löschen einer Kante lässt ihre Bindings bestehen —
entfernen oder binden Sie sie im Panel neu.

Um eine Verbindung zu löschen, wählen Sie sie aus: Klicken Sie auf die Linie, dann
wird sie dicker gezeichnet, das Panel zeigt ihr **From** und **To**, und auf ihr
erscheint eine Schaltfläche **Delete connection**. Drücken Sie die Schaltfläche oder
`Backspace`, dann verschwindet die Verbindung, und die beiden Schritte bleiben. Die
Verbindungen einer veröffentlichten Version lassen sich nicht auswählen und daher
nicht löschen.

Ein **For each**-Schritt führt seinen Körper einmal pro Element einer Liste aus.
Der Körper ist kein eigenes Dokument - er ist Teil desselben flachen Graphen, für
sich angezeigt. **Edit loop body** am Schritt, das angibt, wie viele Schritte der
Körper enthält, öffnet diese Ansicht, und die **Workflow scope**-Brotkrumen in der
Ecke der Zeichenfläche zeigen, wo Sie sind, von **Workflow** hinunter zur geöffneten
Schleife. Jede Krume führt wieder hinaus.

Ein Körper beginnt bei **Loop item**, mit
dem der **Each item**-Port der Schleife verbunden ist, und endet bei **Loop result**;
nichts darin führt zurück zur Schleife, die über **Done** weitergeht, sobald jedes
Element den Körper durchlaufen hat. Palette und Binding-Quellen folgen dem Scope,
in dem Sie sind, und ein Schritt im Körper darf alles lesen, was vor der Schleife
lief. Was die Schleife tut, steht in der
[Knoten-Referenz](reference/workflow-nodes.md#loops).

## Validierungs-Rückmeldung { #validation-feedback }

Der Editor prüft den Graphen, während Sie bearbeiten, und zeigt, was falsch ist, wo
es falsch ist. Ein ausgewählter Knoten mit einem Problem trägt ein Badge, das seine
Probleme zählt, im Panel-Kopf; ein Feld mit einem Problem zeigt seine Meldung
inline; und eine ausklappbare Liste am Fuß des Panels sammelt die Probleme, sodass
jedes auf den Knoten oder das Feld verweist, um das es geht.

Die Meldungen benennen den konkreten Fehler: ein Pflicht-Input ohne Wert, ein Input,
den mehr als eine Quelle setzt, eine Verbindung, deren Ports unterschiedliche Formen
tragen, ein Schritt, der vom Start aus nicht erreichbar ist, eine Schleife zurück zu
einem früheren Schritt, ein Wert, der einen Schritt liest, der nicht auf jedem
hierher führenden Pfad gelaufen ist, oder eine Verbindung, die in den Körper einer
Schleife hinein oder aus ihm heraus kreuzt.

!!! info "Die Prüfung des Editors ist eine Vorschau; das Veröffentlichen ist die Autorität"

    Die Validierung im Editor ist ein schneller Spiegel der Regeln, die der Server
    durchsetzt. Sie ist dazu da, ein Problem zu fangen, während Sie es ansehen, ist
    aber nie das letzte Wort: Das Veröffentlichen führt die volle Validierung auf
    dem Server erneut aus, und ein Problem, das der Editor übersehen hat, wird auf
    dieselbe Weise angezeigt, am Knoten oder Feld, zu dem es gehört.

## Autosave und das Revisions-Konflikt-Banner { #autosave-and-the-revision-conflict-banner }

Ihr Draft speichert sich selbst. Eine kurze Pause, nachdem Sie aufhören zu
bearbeiten, schreibt den aktuellen Graphen, und der Status neben dem Kopf spiegelt
ihn — **Unsaved changes**, solange ein Speichern aussteht, **Saving…**, während es
läuft, **Saved**, sobald es landet, und **Save failed — will retry**, wenn es das
nicht tat.

Jedes Speichern wird gegen die Revision geschrieben, die Sie geöffnet haben, sodass
ein an zwei Stellen zugleich bearbeiteter Draft nicht still überschreiben kann.
Passiert das, hebt der Editor ein Banner mit dem Titel **This draft changed
elsewhere**: *Someone edited this workflow since you opened it. Overwrite keeps your
changes; reload replaces them with the latest saved draft.* Sie wählen:

- **Overwrite** — behalten Sie Ihre Version und schreiben Sie sie über die
  anderswo gespeicherte.
- **Reload** — verwerfen Sie Ihre ungespeicherten Änderungen und nehmen Sie den
  zuletzt gespeicherten Draft.

## Eine Version veröffentlichen und die Versionshistorie { #publishing-a-version-and-version-history }

**Publish** friert den aktuellen Draft als unveränderliche Version ein, die läuft —
eine Version wird nach ihrer Erstellung nie geändert. Der Publish-Dialog nimmt eine
optionale **Release note** entgegen, die beschreibt, was sich geändert hat. Hat der
Graph noch Probleme, wird das Veröffentlichen mit **Fix the problems below before
publishing** blockiert, sodass eine Version, die nicht validieren würde, nie
entsteht.

Das Veröffentlichen beendet Ihr Bearbeiten nicht. Der Draft existiert weiter
unabhängig von jeder veröffentlichten Version, sodass Sie ihn sofort weiter
bearbeiten. **History** in der Kopfzeile des Editors öffnet jede veröffentlichte
Version mit ihrer Release note. **View** öffnet eine frühere Version schreibgeschützt
- eine veröffentlichte Version ist schreibgeschützt, und um Änderungen zu machen,
bearbeiten Sie den Draft weiter.

Um zu einer veröffentlichten Version zurückzukehren, öffnen Sie sie mit **View** und
wählen **Restore to draft**. Nach Ihrer Bestätigung übernimmt der Draft den Graphen
dieser Version, und alles, was im Draft unveröffentlicht war, wird verworfen. Die
Version selbst ändert sich nicht, und nichts wird veröffentlicht, bis Sie den Draft
erneut veröffentlichen. Undo beginnt beim wiederhergestellten Graphen von vorn. Hat
jemand den Draft geändert, seit Sie ihn geöffnet haben, wird die Wiederherstellung
mit demselben Konflikt-Banner abgelehnt, das ein Speichern auslöst, statt seine
Änderung zu verwerfen. Wiederherstellen erfordert `workflows:edit` auf dem Workflow,
und ein archivierter Workflow kann nicht wiederhergestellt werden. Jede
Wiederherstellung wird im [Audit-Log](governance.md) als `workflow.version_restored`
festgehalten.

## Einen Workflow ausführen { #running-a-workflow }

**Runs** in der Kopfzeile des Editors und das Runs-Icon auf der Karte eines
Workflows öffnen seine Runs, die neuesten zuerst, jeder mit seinem Status, ob er den
Draft oder die veröffentlichte Version ausgeführt hat, was ihn gestartet hat, wann,
wie lange und zu welchen Kosten. **Start a run** startet einen von Hand: **Test the
draft** führt den Draft in seinem jetzigen Stand aus, **Published version** die
Live-Version. Sein **Input (JSON)** ist das, was der **Input**-Schritt des Workflows
als `payload` weitergibt.

Ein Run öffnet mit seiner Dauer, seinen Kosten und der Zahl erledigter Schritte,
dann mit dem Fehler, mit dem er endete, falls es einen gab. Daneben steht der Graph,
den er ausgeführt hat, jeder Schritt markiert mit dem, was der Run mit ihm getan hat,
seinen Versuchen und seinem Fehler, und die Schritte, die er nie erreicht hat,
blass. **Open loop body** zeigt die Iterationen einer Schleife auf dieselbe Weise.

Die Ausgabe des Runs und jeder Schritt, den er gemacht hat, Iteration für Iteration,
stehen daneben. Ein laufender Run aktualisiert sich alle paar Sekunden, und **Cancel
run** stoppt ihn. Seine **Files** listen, was seine Schritte gespeichert haben - einen Download, eine
gerenderte Seite, die Ausgabe eines Skripts -, jeweils zum Herunterladen.

## Einen Workflow von außerhalb der Konsole starten { #starting-a-workflow-from-outside-the-console }

Ein Workflow startet mit einem **Trigger**, dem ersten Knoten auf seiner
Zeichenfläche. Die Gruppe **Triggers** oben in der Palette enthält fünf: **Manual or
API**, **Chat message**, **Webhook**, **Schedule** und **New table record**. Einen
davon einem Workflow hinzuzufügen, der schon einen Trigger hat, ersetzt den alten an
seiner Stelle, und die Verbindungen und Bindings, die den alten verlassen, verlassen
den neuen. **New workflow** beginnt einen Workflow mit dem Trigger, den Sie dort
wählen.

Erst das Veröffentlichen einer Version schaltet ihren Trigger ein. Ein Webhook, ein
Zeitplan und ein Tabellen-Trigger führen dann diese Version als das Mitglied aus, das
sie veröffentlicht hat, und die nächste Veröffentlichung verschiebt sie auf die neue
Version. Eine Veröffentlichung, die mit einem anderen Trigger startet, schaltet den
alten ab. **Trigger** in der Kopfzeile des Editors zeigt den Live-Trigger und seinen
Zustand und sagt, wann der Draft anders startet.

Eine Version, die mit **Manual or API** oder ganz ohne Trigger startet, startet jeder,
der sie ausführen darf, als er selbst: **Start a run** unter Runs, die
[HTTP-API](api.md#running-a-workflow) oder ein WebSocket. Jeder Run wird geprüft,
abgerechnet und auditiert wie ein hier gestarteter. Diese Wege starten keinen anderen
Trigger, und jeder andere Trigger hat einen eigenen. Ein Test-Run des Drafts nimmt
jeden Trigger, und **Start a run** öffnet ihn mit einer Eingabe in der Form dieses
Triggers.

### Aus dem Chat { #from-the-chat }

Die Auswahl im Chat, wer antwortet, listet unter den Agenten die veröffentlichten
Workflows, die mit **Chat message** starten. Ist einer gewählt, startet jede
Nachricht einen Run davon, und der Trigger gibt den folgenden Schritten die Nachricht
als `prompt` weiter, mit der `conversation_id` und der `user_id` des Absenders. Der
Thread zeigt eine Karte mit dem Status des Runs und einem Link zu seinen Schritten,
und die Antwort des Workflows folgt darunter, sobald der Run endet.

Die Antwort wird in die Unterhaltung geschrieben, wenn der Run endet, ob der Chat noch
offen ist oder nicht, sodass ein erneutes Öffnen der Unterhaltung sie wieder liest.
Ein Run schreibt in die Unterhaltung, aus der er gestartet wurde, und nirgendwo sonst:
Wer jemand anderen erreichen will, braucht einen HTTP- oder Benachrichtigungsschritt
im Graphen.

### Über einen WebSocket { #over-a-websocket }

`/api/v1/ws/workflow-runs` startet einen Run und streamt seine Ereignisse oder folgt
einem, der bereits läuft. Ein Client, der seine Verbindung verloren hat, verbindet
sich mit dem Cursor des letzten Ereignisses, das er gesehen hat, erneut und macht
genau dort weiter, wo er aufgehört hat. Ereignisse werden geschrieben, bevor sie
gesendet werden, sodass nichts verloren geht und nichts zweimal läuft. Der Socket
prüft die Sitzung und den Zugriff des Mitglieds vor jedem Frame und jedem Lesen des
Streams erneut. Die Frames stehen in [Die HTTP-API](api.md#following-a-run-over-a-websocket).

### Ein Webhook oder ein Zeitplan { #a-webhook-or-a-schedule }

Ein **Webhook**-Trigger erhält seine Adresse und sein **Signing Secret**, wenn eine
Version mit ihm zum ersten Mal veröffentlicht wird. Die Veröffentlichung zeigt das
Secret einmal, und spätere Veröffentlichungen desselben Knotens behalten beides; ein
Webhook-Knoten, der gelöscht und neu hinzugefügt wird, erhält eine neue Adresse. Der
Absender signiert mit dem Secret den exakten Request-Body, HMAC-SHA256 in
`X-Signature-256`, und benennt jede Zustellung in `X-Delivery-Id`; GitHubs eigene
Header funktionieren ebenfalls. Der Trigger gibt das JSON der Zustellung als `body`
weiter, mit ihrer `delivery_id`. Ein Retry, der eine ID wiederholt, wird mit dem
ersten Run beantwortet und startet nichts, weil die ID zusammen mit dem Run, den sie
zugelassen hat, in einer Transaktion gespeichert wird.

Ein **Schedule**-Trigger läuft in einem festen Abstand, täglich zu einer festen
Uhrzeit oder nach einem Cron-Ausdruck, alles in UTC und höchstens einmal pro Minute.
Sein **Input** ist das, womit jeder Run beginnt, weitergegeben als `input` neben dem
`fired_at` des Takts. Ein Takt, der den letzten Run noch laufend vorfindet, wird
übersprungen, statt einen zweiten Run dahinter zu stapeln, und ein Takt, den die
Zulassungsquote ablehnt, wartet auf den nächsten.

Beide laufen als das Mitglied, das die Version veröffentlicht hat, und dessen Zugriff
wird bei jedem Auslösen neu geprüft. Ein Webhook, dessen Mitglied den Workflow nicht
mehr ausführen darf, weist seine Zustellungen ab, und ein solcher Zeitplan wird
abgeschaltet und im Audit-Trail vermerkt. **Pause** im Sheet **Trigger** hält beide
ohne Veröffentlichung an, und **New secret** ersetzt das Secret eines Webhooks; das
alte verifiziert sofort nicht mehr.

### Wenn ein Tabellen-Datensatz hinzukommt { #when-a-table-record-is-added }

Ein **New table record**-Trigger nennt eine Tabelle und filtert jeden Datensatz so,
wie er hinzugefügt wurde - in der Konsole, über die API, durch einen Agent oder den
Tabellenschritt eines anderen Workflows. Er gibt den Datensatz weiter: seine
`record_id`, seine `values` nach Spalten-ID, dieselben Werte als `fields` nach
Beschriftung und die `author_id` dessen, der ihn hinzugefügt hat. Das Veröffentlichen
braucht Lesezugriff auf die Tabelle, und ein Datensatz, der vor der Veröffentlichung
hinzukam, startet ihn nie. Ein so gestarteter Run trägt die Kette der Trigger, die er
durchlief, sodass ein Workflow, der in die Tabelle zurückschreibt, deren Trigger ihn
startete, blockiert wird statt im Kreis zu laufen.

**Triggers** der Tabelle selbst listet die Workflows, die mit ihr starten, pausiert
und setzt sie fort und zeigt, was jeder über jeden Datensatz entschieden hat. Siehe
[Virtual Tables](virtual-tables.md#triggers).

## Wenn etwas schiefgeht { #when-something-goes-wrong }

**Was ein Run verspricht.** Das Ergebnis eines Schritts und das Versenden der Schritte
danach werden zusammen gespeichert, sodass ein Worker, der zwischen Schritten stoppt,
nichts verliert: Ein anderer übernimmt den Run, wo er war. Ein Worker, der mitten in
einem Schritt stoppt, hinterlässt einen Versuch, dessen Ende niemand gesehen hat. Ein
Schritt, der sich gefahrlos wiederholen lässt, wird erneut versucht. Ein
Tabellen-Schreibzugriff spielt seinen ersten Schreibzugriff über seine Quittung erneut
ab, statt zweimal zu schreiben, und eine Benachrichtigung geht einmal hinaus. Ein
Schritt, der anderswo schon gewirkt haben kann und nichts weiter verspricht - einen
Agent auszuführen ist so einer -, wird nie von selbst wiederholt: Der Run hält als
**Braucht Aufmerksamkeit** an, damit niemand ein Modell zweimal bezahlt oder eine
Nachricht zweimal sendet, ohne dass jemand entscheidet.

Nichts anderes geschieht genau einmal. Ein HTTP-Aufruf, ein Upload oder ein
Dateischreiben kann nach einem solchen Halt erneut erfolgen, also braucht ein
empfangendes System, das eine Anfrage nicht zweimal sehen darf, einen eigenen
Idempotenzschlüssel. Das Wiederholungsversprechen jedes Schritts steht in der
[Knotenreferenz](reference/workflow-nodes.md).

| Was Sie sehen | Warum | Was tun |
|---|---|---|
| **Braucht Aufmerksamkeit** | Ein Schritt, der gewirkt haben kann, wurde unterbrochen | Prüfen Sie, ob seine Wirkung eingetreten ist, brechen Sie dann den Run ab und starten Sie einen neuen, falls nicht. Ihn in der Konsole fortzusetzen ist noch nicht gebaut |
| `PRINCIPAL_REVOKED` | Das Mitglied, als das der Run handelt, hat den Zugriff verloren oder sein Konto wurde deaktiviert | Ein Mitglied, das den Workflow ausführen darf, veröffentlicht ihn erneut, damit sein Trigger als es läuft |
| `WORKFLOW_TRIGGER_MISMATCH` | Der Run wurde über einen Weg angefordert, der nicht sein Live-Trigger ist: von Hand oder per API für einen Workflow, der mit einem Webhook startet, oder im Chat für einen, der nicht mit einer Chatnachricht startet | Starten Sie ihn so, wie sein Trigger es sagt, oder testen Sie den Draft, der jeden Trigger nimmt |
| `INVALID_BINDING` | Ein Wert passte nicht zu dem Feld, an das er gebunden war | Der Fehler des Schritts nennt das Feld; korrigieren Sie die Bindung oder den Wert davor |
| `REVISION_CONFLICT` | Jemand hat einen Datensatz geändert, nachdem der Schritt ihn gelesen hat | Leiten Sie den Fehler des Schritts mit `error.handle` zu einem frischen Lesen um |
| Der Verlauf eines Tabellen-Triggers zeigt **Blockiert** | Der Run hätte sich selbst erneut gestartet, oder seine Kette ging zu tief | Siehe [Trigger](virtual-tables.md#triggers) |
| Ein Webhook antwortet `403` | Die Signatur passt nicht zum Body, oder das Mitglied, als das er läuft, darf den Workflow nicht mehr ausführen | Signieren Sie genau die gesendeten Bytes mit dem aktuellen Secret, oder ein Mitglied, das ihn ausführen darf, veröffentlicht ihn erneut |

## Tastatur und Barrierefreiheit { #keyboard-and-accessibility }

Jeder Teil des Editors hat einen Weg, der keinen Zeiger braucht. Ein Klick auf einen
Palettenknoten fügt ihn ohne Ziehen hinzu, jedes reine Icon-Bedienelement trägt
eine gesprochene Bezeichnung, und die Zeichenfläche nimmt den Tastaturfokus, sodass
Sie über ihre Schritte und Verbindungen tabben können. Eine Verbindung lässt sich
über die Tastatur herstellen: Starten Sie eine an einem Knoten und schließen Sie sie
an einem kompatiblen Ziel ab.

Die Tastenkürzel der Zeichenfläche feuern nur, solange der Fokus im Editor ist,
sodass sie nie eine Taste einem Feld anderswo auf der Seite stehlen:

| Tasten | Tut |
|---|---|
| `Ctrl`/`Cmd` + `Z` | Rückgängig |
| `Ctrl`/`Cmd` + `Shift` + `Z` oder `Ctrl`/`Cmd` + `Y` | Wiederherstellen |
| `Ctrl`/`Cmd` + `C` | Auswahl kopieren |
| `Ctrl`/`Cmd` + `X` | Auswahl ausschneiden |
| `Ctrl`/`Cmd` + `V` | Einfügen, versetzt, sodass es das Original nicht verdeckt |
| `Escape` | Eine laufende Verbindung abbrechen |

Ein Einfügen bekommt frische ids und mappt die Bindings unter den kopierten
Schritten um, sodass eingefügte Schritte voneinander lesen statt von den Originalen.
Jedes Bearbeitungskürzel ist wirkungslos, während Sie eine veröffentlichte Version
ansehen, die schreibgeschützt ist; `Escape` bricht eine übrig gebliebene Verbindung
weiterhin ab.

Kopieren und Einfügen haben drei Grenzen:

- **Ein gebundener Schritt liest weiter von dort, wo er zuvor las.** Ein kopierter
  Schritt behält seine Bindings. Liest er von einem Schritt, den Sie nicht kopiert
  haben, liest er weiter vom Original, aber nichts verbindet den eingefügten Schritt
  damit, sodass er erst validiert, wenn Sie beide verbinden. Wählen Sie beide Schritte
  aus, um das Paar zu kopieren, dann liest die Kopie von ihrem eigenen vorgelagerten
  Schritt.
- **Eine Verbindung reist nur mit ihren beiden Schritten.** Eine Verbindung allein
  auszuwählen und zu kopieren bewirkt nichts.
- **Die Kürzel gehören zur Zeichenfläche.** Sie wirken, solange der Fokus auf der
  Zeichenfläche liegt, und ein Klick irgendwo darin — auf einen Schritt, die leere
  Fläche, eine Verbindung — hält ihn dort. Liegt der Fokus im Panel **Properties** oder
  in der Palette, bleiben die Tasten diesen Feldern, klicken Sie also die
  Zeichenfläche an, bevor Sie sie drücken.

## Zusammenfassung { #recap }

- Ein Workflow ist **ein Draft, den Sie bearbeiten, und eine veröffentlichte,
  unveränderliche Version, die läuft** — starten Sie einen mit einem Trigger oder
  aus einer Vorlage, und **Duplicate** kopiert einen Draft in einen frischen Workflow.
- Die **Palette** fügt Schritte per Ziehen oder Klick hinzu; die **Zeichenfläche**
  verdrahtet sie und lehnt eine Verbindung zwischen inkompatiblen Ports ab.
- Eine Kante legt die **Reihenfolge** fest, Bindings tragen die **Werte**; das Verbinden
  von Ports gleicher Form legt die Bindings für Sie an.
- Die Inputs eines Knotens sind **ein Literal oder ein Binding** — **Bind** liest
  einen Wert aus einer erreichbaren, typkompatiblen vorgelagerten Ausgabe.
- Der Draft **speichert sich selbst**, und eine Bearbeitung von zwei Stellen hebt
  ein Banner mit **Overwrite** oder **Reload**.
- **Publish** wird blockiert, solange ein Problem besteht, und validiert erneut auf
  dem Server; frühere Versionen bleiben schreibgeschützt einsehbar, und **Restore to
  draft** macht eine davon wieder zum Draft.
- Jede Aktion hat einen **Tastaturweg**, und die Bearbeitungskürzel sind auf einer
  schreibgeschützten veröffentlichten Version wirkungslos.
- Ein Workflow startet mit einem **Trigger**-Knoten - von Hand oder per API, einer
  Chatnachricht, einem signierten **Webhook**, einem **Zeitplan** oder einem neuen
  Tabellen-Datensatz -, und das **Veröffentlichen** schaltet ihn ein, als das
  veröffentlichende Mitglied.
- Die **Policy** eines Schritts legt seine Versuche, sein Zeitlimit und fest, ob
  seine Fehler über einen **Error**-Port hinausgehen; der Körper eines **For
  each**-Schritts läuft einmal pro Element von **Loop item** bis **Loop result**.
- **Runs** listet jeden Run, **Start a run** testet den Draft oder führt die
  veröffentlichte Version aus, und ein Run zeigt seinen Graphen Schritt für Schritt,
  wie er abgelaufen ist.
