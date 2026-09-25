---
source_sha: "d22d5fce4b79"
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

**New workflow** öffnet einen Dialog, der Sie mit einer leeren Zeichenfläche oder
einer Vorlage beginnen lässt. **Blank workflow** ist eine leere Zeichenfläche zum
Aufbau von Grund auf. Die Vorlagen sind fertige Ausgangspunkte — **Starter**, ein
einzelner Schritt zum Umbenennen und Verdrahten, und **Two-step sequence**, zwei
bereits verbundene Schritte für einen linearen Ablauf. Wählen Sie eine mit **Use**,
und Sie landen im Editor.

Die Liste gruppiert jeden Workflow, den Sie sehen können, nach Status — **Drafts**,
die Sie noch bauen, die **Published** Versionen, die laufen, und die **Archived** —
und **Filter by status** grenzt auf einen ein. Das Badge jeder Zeile zeigt
**Draft**, **Published** oder **Archived**.

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
Workflows erscheinen. Ein **Knoten** ist ein Schritt; eine **Kante** ist eine
Verbindung, die die Ausgabe eines Schritts in den nächsten trägt. Die Zeichenfläche
lässt sich verschieben und zoomen, und ihre Bedienelemente sitzen in der Ecke —
eine Minimap gibt es nicht.

Die **Nodes**-Palette an der Seite listet die Knotentypen, die Ihr Deployment
registriert hat, gruppiert nach Kategorie, jeder mit Icon, Namen und Beschreibung.
**Search nodes** filtert die Liste. Sie fügen einen Schritt auf zwei Wegen hinzu:

- **Ziehen** Sie einen Knoten aus der Palette auf die Zeichenfläche — der Weg für
  den Zeiger.
- **Klicken** Sie einen Knoten, um ihn nahe der Mitte der Ansicht hinzuzufügen —
  der Weg für Tastatur und Touch, der kein Ziehen braucht.

Die Palette zeigt, was dort gültig ist, wo Sie gerade sind. Innerhalb des Körpers
einer Schleife verbirgt sie Knotenarten, die dort nicht leben können, sodass die
Liste, die Sie sehen, im gerade bearbeiteten Scope immer hinzufügbar ist.

!!! note "Der Knotenkatalog wächst mit der Zeit"

    Die Palette wird von den registrierten Knoten des Deployments gespeist, nicht
    von einer festen Liste. Anfangs ist der Katalog klein; mehr Knotenarten —
    einen Agent aufrufen, eine Tabelle lesen und schreiben, verzweigen und in
    Schleifen laufen — kommen hinzu, sobald spätere Milestones sie registrieren,
    und sie erscheinen in genau dem Moment in der Palette, ohne Änderung an einem
    Workflow, den Sie bereits gebaut haben.

## Einen Knoten konfigurieren { #configuring-a-node }

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
  kompatiblen Typ tragen, jede angezeigt als *{node} · {port} ({type})*. Ein Feld
  ohne etwas Kompatibles davor sagt **No compatible upstream outputs**, statt eine
  ungültige Auswahl anzubieten.

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

## Verbindungen und foreach-Scope { #connections-and-foreach-scope }

Sie ziehen eine Kante, indem Sie einen Ausgangs-Port eines Knotens mit einem
Eingangs-Port eines anderen Knotens verbinden. Der Editor lehnt eine Verbindung
zwischen Ports, die unterschiedliche Formen tragen, ab, bevor er sie zeichnet,
sodass eine inkompatible Verbindung nie auf der Zeichenfläche landet.

Ein `foreach`-Schritt führt seinen Körper einmal pro Element in einer Liste aus.
Der Körper ist kein eigenes Dokument — er ist Teil desselben flachen Graphen, nur
für sich gezeigt. **Open body** am Schritt betritt diese Ansicht, und die
Brotkrumen-Leiste **Workflow scope** zeigt, wo Sie sind, von **Workflow** an der
Wurzel bis zu der Schleife, die Sie geöffnet haben. Jede Krume navigiert wieder
hinaus. Die Palette und die Binding-Quellen folgen dem Scope, in dem Sie sind,
sodass das, was Sie hinzufügen und woraus Sie lesen können, immer die auf dieser
Ebene gültigen sind.

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
bearbeiten, und jede veröffentlichte Version wird unter **Version history** mit
ihrer Release note gelistet. **View** öffnet eine frühere Version schreibgeschützt
— eine veröffentlichte Version ist schreibgeschützt, und um Änderungen zu machen,
bearbeiten Sie den Draft weiter.

## Einen Workflow ausführen { #running-a-workflow }

Der **Runs**-Tab eines Workflows ist der Ort, an dem seine Test- und Produktions-Runs
erscheinen werden, Schritt für Schritt mit ihren Inputs, Ausgaben und Kosten. Die
Run-Historie kommt, sobald der Workflow-Runner ausgeliefert wird; bis dahin zeigt
der Tab, dass sie noch nicht verfügbar ist, und der Editor dient dem Bauen und
Veröffentlichen.

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

## Zusammenfassung { #recap }

- Ein Workflow ist **ein Draft, den Sie bearbeiten, und eine veröffentlichte,
  unveränderliche Version, die läuft** — starten Sie einen leer oder aus einer
  Vorlage, und **Duplicate** kopiert einen Draft in einen frischen Workflow.
- Die **Palette** fügt Schritte per Ziehen oder Klick hinzu; die **Zeichenfläche**
  verdrahtet sie und lehnt eine Verbindung zwischen inkompatiblen Ports ab.
- Die Inputs eines Knotens sind **ein Literal oder ein Binding** — **Bind** liest
  einen Wert aus einer erreichbaren, typkompatiblen vorgelagerten Ausgabe.
- Der Draft **speichert sich selbst**, und eine Bearbeitung von zwei Stellen hebt
  ein Banner mit **Overwrite** oder **Reload**.
- **Publish** wird blockiert, solange ein Problem besteht, und validiert erneut auf
  dem Server; frühere Versionen bleiben schreibgeschützt einsehbar.
- Jede Aktion hat einen **Tastaturweg**, und die Bearbeitungskürzel sind auf einer
  schreibgeschützten veröffentlichten Version wirkungslos.
