---
source_sha: "567495b4bc6f"
---

# Workflows { #workflows }

Ein **Workflow** verkettet Schritte zu einer Automatisierung, die Ihre Agents
ausführen: eine [Tabelle](virtual-tables.md) lesen, einen Agent aufrufen, auf das
Ergebnis verzweigen, über eine Liste iterieren. Sie bauen ihn auf einer
Zeichenfläche, verdrahten die Schritte miteinander und veröffentlichen ihn als
unveränderliche Version — dieselbe Form, die ein [Agent](concepts.md) hat: ein
Draft, den Sie bearbeiten, und eine veröffentlichte Version, die läuft.

Diese Seite beschreibt den visuellen Editor: die Liste, die Zeichenfläche und die Schrittauswahl, wie ein Knoten konfiguriert wird, Autosave und Veröffentlichen sowie die
Tastaturwege durch all das. Der Editor liegt unter **Workflows** in der Konsole.
Die **Liste** unter Workflows hat ein **"?"**, das eine Führung durch diese Liste
abspielt; der Editor selbst hat keine Führung.

## Einen Workflow erstellen und duplizieren { #creating-and-duplicating-a-workflow }

**New workflow** hat zwei Tabs: **How does it start?** und **Templates**. Der erste zeigt **Manual**, **API request**, **Chat message**, **Webhook**, **Schedule** und **Table record**; **More ways to start** zeigt weitere Trigger. Vorlagen umfassen **Starter**, **Two-step sequence** und die unten beschriebenen Automatisierungen. **Use** öffnet einen Draft im Editor.

Der Katalog zeigt Karten und Suche in einem gemeinsamen Panel. **Filters** öffnet Status, Tags und Sortierung und zählt aktive Filter. Bei Ladefehlern erscheint **Retry** statt eines leeren Katalogs. Der Import beginnt mit der Dateiauswahl; **Or paste the file's JSON here** öffnet ein beschriftetes Textfeld.

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

### Vorlagen, Export und Import { #templates-exporting-and-importing }

Die sofort ausführbaren Automationen heißen **Öffentliche API → Tabelle** und **Markdown-Notizbuch**. Der Server erstellt eine private Tabelle und einen vollständig konfigurierten Entwurf in einer Transaktion. Konto, API-Schlüssel oder Tabellenauswahl sind nicht nötig. Das erste Beispiel lädt einen Beitrag von [JSONPlaceholder](https://jsonplaceholder.typicode.com/) und speichert Titel und Inhalt; das zweite schreibt eine Markdown-Notiz mit Frontmatter. Weitere Runs verwenden dieselbe Tabelle und aktualisieren denselben Beispieldatensatz. Die Erstellung benötigt Rechte zum Erstellen und Bearbeiten von Tabellen. **Starter** und **Two-step sequence** bleiben kleine lokale Beispiele.

Die Run-Historie füllt den verfügbaren Seitenbereich automatisch, ohne zusätzlichen Vergrößerungsknopf. Der Katalog füllt den verfügbaren Seitenbereich und bietet einen eigenen Vollbildknopf. Seitennavigation erscheint nur bei weiteren Seiten. Der Dateiimport bietet einen beschrifteten Bereich zum Auswählen oder Ablegen einer JSON-Datei.

Die Seitennavigation der Run-Historie steht am unteren Panelrand. Run-Details bieten eine kompakte Zusammenfassung, eine Canvas über den Arbeitsbereich und ein Seitenpanel für Steps, Output und verfügbare Dateien. Ein Klick auf einen Schritt öffnet seine gespeicherten Daten. Dateiimport und eingefügtes JSON haben eigene Tabs; das JSON-Codefeld bietet Formatierung und behält ungültige Eingaben bei einer Fehlermeldung.

**Export workflow** unter **More** in der Kopfzeile des Editors exportiert den Entwurf als
`.workflow.json`-Datei. Die Datei enthält keine IDs dieses Deployments: Jeder
Agent, jede Tabelle, jedes Secret, Mitglied, jeder Bot oder Workflow, den ein
Schritt gewählt hat, wird weggelassen und aufgeführt, angeheftete Testdaten werden
weggelassen und ebenso der Fehler-Workflow. Sie enthält nie den Wert eines Secrets.
**Import** in der Liste macht aus einer solchen Datei einen neuen Entwurf, nimmt
jede ID heraus, die eine von Hand erstellte noch nennt, und führt jeden Schritt und
jedes Feld auf, das vor dem Veröffentlichen neu zu wählen ist. Eine Datei mit
einem Schritt, den dieses Deployment nicht hat, wird abgelehnt, und nichts entsteht.

### Workflows finden, benennen und stilllegen { #finding-naming-and-retiring-a-workflow }

Jede Karte sagt, was den Workflow startet und wie viele Schritte er hat, ob er live
oder ein Entwurf ist und wie und wann sein letzter Lauf ausging - bis zum ersten Lauf
das Datum der Bearbeitung.

Über den Karten findet eine Suche einen Workflow nach Name, Beschreibung oder Tags,
ein Tag-Filter grenzt die Liste auf einen Tag ein, und sortiert wird nach letzter
Bearbeitung, Name oder den neuesten zuerst. Alles bleibt in der Adresse, sodass ein
Neuladen oder ein geteilter Link dieselbe Liste zeigt.

**More → Settings** enthält Name, Beschreibung, Tags und Laufzeiteinstellungen des Workflows; Änderungen werden automatisch gespeichert. Der Schritteditor nutzt das verfügbare Fenster: Input links, Parameters und Settings in der Mitte, Output rechts. Trigger haben zwei Bereiche, da sie keine eingehenden Daten haben. Auf großen Bildschirmen scrollt jeder Bereich separat, auf Telefonen gibt es eine Spalte. Gespeicherte Ausführungen zeigen ihre Parameter schreibgeschützt neben den Daten. Datensatzwerte verwenden die Spaltennamen der Tabelle. Notizen bieten Open note, Größen und Ziehgriffe.

Die App-Auswahl zeigt MCP-Katalogserver bereits vor dem Verbinden; der allgemeine Eintrag Call an MCP tool ist ausgeblendet. Verbinde einen Dienst direkt und wähle anschließend eines seiner erkannten Werkzeuge. Die Werkzeug-Freigabeliste bleibt wirksam. Farbige Schritte und Minimap sind standardmäßig aktiv. KI-Modellschritte zeigen Anweisungen, Temperatur und Reasoning-Aufwand; leere Einstellungen behalten die Anbieterstandards. Jev zeigt Modell, Frage und Konfidenzschwelle. Send an email verwendet den Plattformabsender oder verbindet Gmail beziehungsweise Outlook und wechselt nach Bestätigung zum tatsächlichen MCP-Werkzeug des Postfachs. Dabei werden inkompatible Eingabezuordnungen entfernt; der Wechsel lässt sich rückgängig machen.

Der Architect kann den Knotenkatalog erkunden, private Workflow-Entwürfe erstellen und ändern, sie testen und Run-Ergebnisse prüfen. Er erstellt außerdem typisierte Virtual Tables und sucht oder aktualisiert Datensätze. Die Skills workflow-builder und virtual-tables erklären den passenden Einsatz. Fehlt ein Dienst im MCP-Katalog, kann der Architect dessen dokumentierte API mit einem HTTP-request-Schritt kapseln und einen veröffentlichten aufrufbaren Workflow über die Workflows-Capability als Agentenwerkzeug anbieten. Zugangsdaten bleiben im Tresor. Tests können reale Aktionen ausführen; die Veröffentlichung mit dauerhaften menschlichen Rechten erfordert weiterhin eine menschliche Sitzung.

Unter dem Namen sagt der Editor, wo der Workflow steht: **Draft, not published**
oder **Live · version 3**, mit **Unpublished changes** daneben, sobald der Entwurf
sich von dieser Version so unterscheidet, wie es eine Veröffentlichung übernähme.
Einen Schritt zu verschieben oder Testdaten anzuheften, zählt nicht.

Ein veröffentlichter Workflow, dessen Trigger von selbst läuft - ein Webhook, ein
Zeitplan oder ein neuer Tabellendatensatz -, hat einen Schalter **Active** im Kopf des
Editors, und seine Karte zeigt **Active** oder **Paused**. Ausschalten pausiert den
Trigger sofort; Einschalten setzt ihn als seinen Veröffentlicher fort und braucht daher
die Berechtigung, den Workflow auszuführen. Das Menü **...** einer Karte archiviert
einen Workflow, was seinen Trigger ebenfalls pausiert. Ein archivierter lässt sich
wiederherstellen, weiterhin pausiert, oder mit Versionen, Läufen und Freigaben löschen;
einer mit noch nicht beendeten Läufen wird mit `WORKFLOW_IN_USE` abgelehnt.

## Die Zeichenfläche und das Hinzufügen von Schritten { #the-canvas-and-the-palette }

Der Editor zeigt **Runs**, **Test draft** und **Publish** direkt. **More** enthält **Versions** und den Wechsel zwischen Bearbeiten und Ansicht. **Canvas options** enthält Minimap, Verbindungsstil und Tastenkürzel. Ein Schritt ohne eingehende Verbindung lässt das leere Input-Panel weg und gibt Parametern mehr Platz; **Expected output fields** öffnet das Ausgabeschema. **Review setup before testing** zeigt die unvollständige Einrichtung.

Die **Zeichenfläche** ist der Ort, an dem die Schritte und Verbindungen eines
Workflows erscheinen, und sie hat die ganze Breite des Editors unter dem Kopf. Ein
**Knoten** ist ein Schritt; eine **Kante** ist eine Verbindung, die die Reihenfolge
festlegt: Der Schritt, auf den sie zeigt, läuft nach dem, von dem sie ausgeht.

Jeder Knoten ist eine Karte mit dem Symbol des Schritts, seinem Namen und einer Zeile
darunter: was er tun soll - eine Bedingung, eine URL, die Zahl der zugeordneten
Felder - danach der Agent, das Modell oder die Tabelle, mit denen er arbeitet. Ein
Schritt mit mehr als einem Ausgang nennt seine Ports beim Namen: **true** und
**false**, **Each item** und **Done** und einen roten **Error**-Port an einem
Schritt, der seine Fehler behandelt. Ein Schritt, der das Veröffentlichen blockiert,
trägt eine Einrichtungsmarkierung (rot nach einem Test- oder Veröffentlichungsversuch): Darüberfahren listet die ersten Angaben auf, und
ein Klick darauf öffnet den Schritt.

Ein Trackpad oder ein Mausrad bewegt die Zeichenfläche,
und eine Pinch-Geste - oder Strg bzw. Cmd mit dem Rad - zoomt sie; ihre Steuerung
sitzt in der Ecke.

Schritte wählen Sie in der **Schrittauswahl**. Sie zeigt Abschnitte - **Start**,
**AI**, **Flow**, **Data**, **Apps and the web** - mit den Gruppen darunter. Eine
Gruppe wie **Slack**, **Tables** oder **Jev decisions** öffnet sich zu ihren
Schritten, und eine Gruppe mit einem Schritt ist dieser Schritt. **Search steps**
findet jeden Schritt nach Namen, nach dem, was er tut, oder nach seiner Gruppe. Sie
fügen einen Schritt auf vier Wegen hinzu:

- **+** oben links auf der Zeichenfläche - oder **Add step** in der Mitte einer leeren
  Zeichenfläche - öffnet die Auswahl. Der Schritt kommt hinter den ausgewählten
  Schritt oder ans Ende des sichtbaren Ablaufs und wird verbunden, wenn die Ports
  passen. Ein Startschritt kommt stattdessen vor den aktuellen Start und wird zu ihm.
- **+** neben dem Ausgang eines Schritts öffnet die Auswahl für den Schritt, der nach
  diesem Ausgang kommt.
- **Rechtsklick** auf die Zeichenfläche: dieselbe Auswahl öffnet sich dort, wo Sie
  geklickt haben, und der Schritt landet dort. Darunter **Notiz hinzufügen** (Add a note) und, sobald
  etwas kopiert ist, **Einfügen** (Paste).
- **Ziehen** Sie einen Schritt aus der Auswahl, um ihn dort abzulegen, wo Sie ihn
  fallen lassen, ohne Verbindung.

Die Apps von Google Workspace (**Gmail**, **Google Calendar**, **Google Drive**,
**Google Docs**, **Google Sheets**) und von Microsoft 365 (**Outlook**, **Outlook
Calendar**, **OneDrive**, **Excel**) sind eigene Gruppen unter **Apps and the web**.
Jede enthält den nativen Trigger der App, wo die Zeichenfläche einen annimmt, und einen
Eintrag je Tool jeder MCP-Verbindung der Organisation zum passenden Server - etwa
**Create draft** oder **Send message**. Die Tools einer Verbindung werden nach Namen
auf diese Gruppen verteilt; ein Tool, das keine davon beansprucht, steht in der
eigenen Gruppe des Servers (**Google Workspace**, **Microsoft 365**), wo auch
**Connect** und eine ungetestete Verbindung gezeigt werden. Die Anmelde-Tools
(`start_google_auth`, `login`, `verify-login`) werden nicht angeboten.

Ein Eintrag fügt einen [MCP call](reference/workflow-nodes.md#mcp-call) hinzu, der schon auf
diese Verbindung und dieses Tool gesetzt ist; gespeicherte Workflows und der Vertrag
des Knotens ändern sich nicht. Der Eintrag verbirgt nichts: Er trägt ein **MCP**-Abzeichen
und den Namen der Verbindung, der eigene Name des Tools steht darunter in einer eigenen
Zeile, der Server einmal in der Überschrift der Gruppe; nichts wird abgeschnitten.

**Search steps** findet ihn über beide Namen oder die App. Auf der
Zeichenfläche liest sich der Schritt **Gmail · Create draft** mit einem
**MCP**-Abzeichen, darunter stehen die Verbindung und der eigene Name des Tools; seine
Einstellungen sagen, dass es ein MCP-Tool-Aufruf auf dieser Verbindung ist, und
verlinken sie. Jedes Gmail-Tool, das der Server anbietet, hat einen klaren Namen, etwa **List labels**
oder **Read thread**; ein Tool ohne Namen in der Liste zeigt seinen eigenen Namen. Der native Trigger ist kein MCP-Aufruf und trägt kein Abzeichen.

Ohne passende Verbindung zeigt die eigene Gruppe des Servers eine Zeile **Connect**, um den
Server zu verbinden. Es werden nur Verbindungen der Organisation aufgelistet, und die
Tools einer Verbindung sind die, die ihr letzter Test festgehalten hat; testen Sie sie
erneut, um neue aufzulisten. Wer den Workflow nicht bearbeiten darf, sieht nur die Trigger. Wer ihn bearbeitet, aber keine MCP-Server verwaltet, sieht alle Aktionen und bekommt keine Zeile **Connect**: Nur wer Server verwaltet, verbindet einen. Die Aktionszeilen einer App werden ausgewählt, nicht gezogen: Auf
die Zeichenfläche lassen sich nur die eigenen Zeilen eines Schritts ziehen.

Ein neuer Schritt landet nie auf einem anderen, wird ausgewählt, öffnet seine
Einstellungen, wenn er welche hat, und die Zeichenfläche scrollt zu ihm, wenn er
außerhalb der Ansicht liegt. Im Körper einer Schleife wird jeder neue Schritt in den
Körper verdrahtet, damit er dort bleibt. Die Auswahl zeigt, was an Ihrer Stelle
gültig ist: **Loop item** und **Loop result** nur im Körper einer Schleife und eine
Schleife, solange Schleifen nicht so tief verschachtelt sind, wie das Veröffentlichen
erlaubt.

Ein Rechtsklick auf einen Schritt bietet **Open settings**, **Duplicate**, **Switch
off** und **Delete step**. Sind mehrere Schritte ausgewählt, löscht eine
Leiste unten sie zusammen.

**Switch to view only** in der Kopfzeile zeigt jemandem, der den Workflow bearbeiten darf, was
ein Leser sieht: Auf der Zeichenfläche lässt sich nichts verschieben, verbinden oder
löschen, ein Schritt öffnet sich mit einem Klick schreibgeschützt, und **Test draft** und
**Publish** sind verschwunden. **Switch to editing** schaltet zurück, und der Editor
öffnet immer im Bearbeitungsmodus. Eine Speicherung, die noch läuft, wird in beiden
Fällen abgeschlossen.

!!! note "Der Schrittkatalog wächst mit der Zeit"

    Die Auswahl speist sich aus den registrierten Knoten der Bereitstellung, nicht
    aus einer festen Liste. Eine später registrierte Knotenart erscheint darin, sobald
    sie registriert ist, ohne Änderung an einem Workflow, den Sie schon gebaut haben.

### Notizen, Aufräumen und Tastenkürzel { #notes-tidying-and-shortcuts }

**Notiz hinzufügen** (Add a note) unter der Auswahl, die ein Rechtsklick öffnet, setzt eine Notiz neben die
Schritte: Markdown, per Doppelklick oder Stift geschrieben, durch Ziehen verschoben und
an den Ecken in der Größe geändert; ausgewählt klappt ihre Palettenschaltfläche
Farbfelder zum Einfärben aus - Grau, Gelb, Grün, Blau, Lila oder Rot -, damit sich eine Warnung von einer Aufgabe abhebt. Eine
Notiz wird im Graphen gespeichert, sodass
Versionen, Wiederherstellungen und Kopien des Workflows sie behalten, aber nichts führt
sie aus oder prüft sie. Eine ausgewählte Verbindung bietet ein **+**, das den nächsten
gewählten Schritt in ihre Mitte setzt, auf beiden Seiten verbunden, wo die Ports passen.
**Aufräumen** (Tidy up) in der Werkzeugleiste ordnet die sichtbaren Schritte von links nach rechts
als eine rückgängig machbare Bearbeitung, die Kartenschaltfläche zeigt eine Minikarte,
die Palettenschaltfläche schaltet die Schritte zwischen Farbe und Schlicht um (siehe [Wie ein Schritt gezeichnet wird](#how-a-step-is-drawn)),
und die Tastaturschaltfläche - oder **?** - listet jedes Kürzel; **Tab** öffnet die
Schrittauswahl. Keines davon greift, während Sie in einem Feld schreiben.

### Wie ein Schritt gezeichnet wird { #how-a-step-is-drawn }

Eine Karte sagt, was für ein Schritt es ist, bevor sie sagt, was er tut. Über dem Namen
steht ein kleines Etikett **Familie · Art** - **KI · Classify**, **Daten · Save a
record** -, und das Symbol sitzt auf einer Kachel in der Familie des Schritts, also in
denselben Abschnitten, die die Schrittauswahl verwendet:

| Familie | Ihre Kachel |
|---|---|
| **Start** | In der Schriftfarbe - dunkel im hellen Design, hell im dunklen - und rund, auf einer Karte mit abgerundetem linken Ende |
| **KI** | Volles Violett |
| **Ablauf** (Flow) | Grau |
| **Daten** (Data) | Petrol (Teal) |
| **Apps** | Weiß mit blauem Rand, damit das Zeichen einer Marke unverändert darauf sitzt |
| **Fehler** (Error) | Rot |

Die Familien unterscheiden sich in Helligkeit und Form, nicht nur in der Farbe, sodass
sie auch bei Farbfehlsichtigkeit und auf einer so weit herausgezoomten Canvas, dass
nichts lesbar ist, zu unterscheiden bleiben. Auch die Minikarte zeichnet jeden Schritt
in der Farbe seiner Familie. Rand und Ring einer Karte gehören nie einer Familie: Sie
gehören dem Run (siehe unten), einer Änderung, einer Auswahl oder einem
ausgeschalteten Schritt.

Die Zeile unter dem Namen beginnt mit dem, womit der Schritt arbeitet - Agent, Modell,
Tabelle - und fährt fort mit dem, was er tun soll, wie in **gpt-4.1-mini · 3
categories**.

Ein Schritt, der den Run anhalten kann, trägt oben auf seiner Karte ein Band, formuliert
nach seinen Einstellungen und nie nach einem Run:

| Schritt | Das Band lautet |
|---|---|
| Approval | **Wartet auf eine Person** |
| Wait | **Wartet 2 Tage** (oder Stunden, Minuten, Sekunden), **Wartet bis zu einem Zeitpunkt** oder **Wartet eine festgelegte Zeit**, wenn ein früherer Schritt den Zeitpunkt oder die Dauer liefert, oder **Wartet auf einen Aufruf** - das gewinnt, wenn Dauer und Aufruf gesetzt sind |
| Run a workflow | **Wartet auf den aufgerufenen Workflow**; kein Band, wenn **Wait for it to finish** aus ist |
| MCP call | **Fragt vor Schreibzugriffen** oder **Fragt vor jedem Aufruf**, je nach Freigabe-Einstellung; kein Band, wenn er nie fragt |

Ein Schritt, der eine Person fragt, zeigt das Band in Rosa; ein Timer oder ein Aufruf
in Grau. Der Agent-Schritt hat keines: Seine Freigaben stammen aus der Spec des Agents
selbst, die die Karte nicht sehen kann.

Auf der Canvas eines Runs wird ein Schritt, der auf eine Person wartet, in Rosa mit
einer Sanduhr in seiner Plakette gezeichnet, gleich wie die Schritte sonst gezeichnet
werden.

**Schlicht** zeichnet jede Kachel neutral und die Minikarte grau, so wie die Canvas
aussah, bevor Schritte Familien hatten. Es behält, was nicht von der Farbe abhängt: das
graue Etikett, das abgerundete Ende des Starts und ein neutrales Band. Umgeschaltet wird
es mit der Palettenschaltfläche in der Werkzeugleiste der Canvas oder unter
**Einstellungen → Profil → Darstellung (Settings → Profile → Appearance) →
Workflow-Schritte**; es wird pro Browser gespeichert, wie das Design.

Ziehen Sie die rechte Kante, die untere Kante oder die untere rechte Ecke eines
ausgewählten Schritts, um seine Größe zu ändern. Eine Karte ist 200 bis 560 px breit und
bis zu 400 px hoch und nie niedriger, als ihr Inhalt braucht. Mehr Breite nimmt mehr vom
Namen und von der Zusammenfassung auf; mehr Höhe lässt den Namen auf bis zu drei Zeilen
umbrechen und danach die Zusammenfassung auf zwei, und die Ports bleiben am unteren Rand
der Karte.

Die Größe wird mit dem Entwurf gespeichert, daher bleibt sie bei Rückgängig,
Kopieren, Einfügen, Duplizieren, veröffentlichten Versionen und Export erhalten.
**Größe zurücksetzen** (Reset size) im Kontextmenü des Schritts stellt die Standardgröße wieder her,
und **Aufräumen** (Tidy up) ordnet die Schritte um ihre Größen herum an. Eine veröffentlichte
Version, ein Run und ein Vergleich zeigen die gespeicherte Größe ohne Anfasser.

## Einen Knoten konfigurieren { #configuring-a-node }

Was jeder Knoten tut, womit er konfiguriert wird und was seine Fehler bedeuten, steht
in der [Knotenreferenz](reference/workflow-nodes.md).

Ein Klick wählt einen Schritt aus, ein Doppelklick öffnet ihn über der Zeichenfläche. In einer veröffentlichten Version oder **View only** genügt ein Klick. Der Kopf zeigt den Namen und eine aufklappbare Zusammenfassung der fehlenden Einrichtung. Klappen Sie sie auf, um die Angaben zu prüfen; ein Feldname führt direkt zur Eingabe. Nach einem Test- oder Veröffentlichungsversuch öffnen sich die Validierungsdetails automatisch.

**Connect account** im Schritt oder in der App-Auswahl öffnet die vorhandene Kontoeinrichtung über dem Workflow. Verbinden Sie ein Organisationskonto, schließen Sie die Einrichtung ab und wählen Sie es im Schritt. Die Geheimnisauswahl bietet **Add API key** oder **New secret**, wählt das gespeicherte Geheimnis automatisch aus und speichert im Entwurf nur dessen id. Ein Trigger ohne OAuth-App-Zugangsdaten bietet direkt **Add credentials**; dasselbe Vault-Formular speichert sie für die Organisation.

**Parameters** ist, womit der Schritt arbeitet und was er tun soll, in einer
Liste, die Liste, mit der ein Schritt arbeitet, zuerst: **Items** von Filter vor seiner
**Condition**. **Settings** ist, wie er läuft. Jede Änderung wird sofort im Draft
gespeichert, daher schließt **Done** nur den Dialog, und **Delete step** entfernt den
Schritt. Ein schreibgeschützter Dialog zeigt jede Einstellung deaktiviert mit ihrem
Wert.

Ein Parameter, der Text nimmt, ist ein Feld für eingegebenen Text und Werte aus früheren
Schritten zugleich, etwa `New lead: {{Form.payload.name}} from {{Form.payload.company}}`.
**Data** daneben fügt einen Wert an der Cursorposition ein, ebenso ein aus **Input**
gezogenes Feld. Tippen Sie `{{`, erscheinen dieselben Werte als Liste, und innerhalb des
Payloads eines Triggers oder des Elements einer Schleife die Felder, die der letzte
Testlauf dort gesehen hat; was Sie weiter tippen, grenzt die Liste ein, und `Enter` oder
`Tab` schreibt den Platzhalter.

Ein Platzhalter nennt einen Schritt und einen Pfad in dessen Ausgabe, ist im Feld
farbig hervorgehoben - rot, sobald Sie das Feld verlassen, wenn er nichts nennt, was
dieser Schritt lesen kann -, wird bei der Veröffentlichung wie jeder aus einem Schritt
gelesene Wert geprüft und folgt dem Schritt, wenn er umbenannt wird. Mit den Daten eines Testlaufs erscheint das
Ergebnis als Vorschau darunter. Nichts wird ausgewertet: Läuft der Schritt, wird jeder
Platzhalter zum Text seines Werts, zu JSON für eine Liste oder ein Objekt, und einer ohne
etwas dahinter lässt den Schritt mit `INVALID_BINDING` fehlschlagen und nennt ihn.

Jeder andere Parameter - eine Zahl, eine Auswahl, ein Schalter, eine als JSON eingegebene
Liste - hat sein eigenes Steuerelement, und **Data** daneben übernimmt den Wert
stattdessen aus einem früheren Schritt. **Data** listet nur die hier erreichbaren Werte
mit kompatiblem Typ, nach Schritt gruppiert, jeden mit der Art seines Werts, und sagt
**No compatible upstream outputs**, wenn es keine gibt. Der Parameter zeigt dann, was er
liest - *Run an agent › text* - und **×** kehrt zu einem eingegebenen Wert zurück.

Ein erforderlicher Parameter ohne Wert ist ein Validierungsproblem, am Schritt
markiert statt still mit einem Standardwert gefüllt. Manche Parameter halten
strukturierte Werte: eine Liste von Zeilen, der Sie mit **Add row** Zeilen hinzufügen,
die Sie umordnen und entfernen, oder eine typisierte Auswahl, die das Unterformular
darunter austauscht. Der Dialog steigt in diese hinein, statt Sie auf einen eigenen
Bildschirm zu schicken.

### Bedingungen { #conditions }

**Filter a list**, **If** und **Switch** entscheiden mit einer Bedingung aus Zeilen: ein
Feld des Elements oder des Werts, eine Prüfung - **is equal to**, **is at least**,
**contains**, **is not empty** und die übrigen - und womit verglichen wird. Eine Zahl,
`true` und `false` werden als solche verglichen, alles andere als Text. Bei mehreren
Zeilen sagt **Match all of these** oder **any**, wie sie verknüpft sind, und die Felder,
die der letzte Lauf oder die Testdaten zeigten, werden vorgeschlagen. Die Bedingung wird
als JMESPath-Ausdruck gespeichert, den der Schritt auswertet. **Write it as an
expression** bearbeitet sie als diesen, und einer, den die Zeilen nicht zeigen können,
bleibt ein Ausdruck.

Wird eine **Switch**-Regel, eine Klassifikator-Kategorie, ein Fehlerzweig, ein **Split**-Zweig oder eine
Genehmigungsauswahl umbenannt, nehmen die Verbindungen, Bindungen und das schnelle Log, die
den alten Namen nutzten, den neuen mit, außer wenn Einträge umsortiert, eingefügt oder
gelöscht werden oder sich zwei Namen gleichzeitig ändern.

### Einen Schritt benennen, notieren und abschalten { #naming-noting-and-switching-off-a-step }

Ein Klick auf den Namen des Schritts oben in seinem Dialog gibt ihm einen eigenen Namen,
der auf seiner Karte steht und überall dort, wo ein späterer Schritt wählt, was er liest -
zwei **Send a message**-Schritte werden zu *Tell sales* und *Tell support*. Zwei Schritte
dürfen, ohne Rücksicht auf Groß- und Kleinschreibung, nicht denselben Namen tragen.

Unter **Settings** hält **Note** eine Zeile für den, der den Workflow als Nächstes
bearbeitet, auf der Karte markiert, und der Reiter trägt einen Punkt, sobald dort etwas
geändert ist.

**Run this step** dort auszuschalten, oder **Switch off** in seinem Kontextmenü, lässt
einen Schritt gedimmt auf der Zeichenfläche und überspringt ihn, wenn ein Lauf ihn
erreicht: Er tut nichts und gibt weiter, was bei ihm ankam. Die Veröffentlichung lehnt
einen abgeschalteten Trigger oder einen Schritt, der den Weg entscheidet, ab, und einen
Schritt, der einen abgeschalteten liest, außer das, was bei ihm ankommt - über seine
eine eingehende Verbindung, von einem eingeschalteten Schritt - hat das gelesene Feld,
das er dann weitergibt. Alle drei werden im Graphen gespeichert, sodass Versionen sie
behalten.

### Die Daten eines Schritts, Testdaten und einen Schritt testen { #a-steps-data-pinning-and-testing-one-step }

Beim Bearbeiten legt der Dialog die Parameter eines Schritts zwischen zwei Bereiche.
**Input** zeigt, was ein früherer Schritt weitergegeben hat, zunächst der
nächstgelegene; gibt es mehrere, lässt sich über die Überschrift jeder Schritt wählen,
aus dem dieser lesen darf. **Output** zeigt, was der Schritt selbst weitergegeben hat,
beide aus dem letzten im Editor gestarteten Testlauf oder beim Öffnen aus dem neuesten.
**Table** legt die Daten als Zeilen aus, eine Liste von Datensätzen mit einer Zeile je
Datensatz. **JSON** zeigt sie, wie sie sind, und **Fields** listet jedes Feld nach Pfad
mit einem einfachen Wort dafür, was es hält - text, number, list, ID: die Pfade, die ein
späterer Schritt liest.

Vor jedem Lauf listen beide Bereiche die Felder, die ein Schritt weitergibt, auf dieselbe
Weise, und auch diese lassen sich ziehen; ein Schritt, zu dem nichts führt, sagt **Not
connected yet**. Eine Tabelle zeigt ihre ersten 50 Zeilen, bis **Show more** den Rest
auslegt, und eine auf ihre Spaltenbreite gekürzte Zelle zeigt beim Überfahren den ganzen
Wert.

Eine Spalte oder ein Feld aus **Input** lässt sich auf einen Parameter ziehen, der es
dann aus jenem Schritt liest, als wäre es unter **Data** gewählt - in Text als
Platzhalter. Ein Feld, das nicht passt, wird mit Grund abgelehnt: ein Typ, den der
Parameter nicht nimmt, oder ein Schritt, der nicht immer vor diesem läuft.

Innerhalb eines Werts ohne festgelegte Form, etwa den `values` einer Zuordnung oder dem
`payload` eines Triggers, gilt der Typ, den der Lauf zeigte. **Data** bietet solche Werte
jedem Parameter an, mit **Field inside it** für den Pfad. Halten Sie ein gezogenes Feld
nahe am oberen oder unteren Rand des Formulars, scrollt es, sodass sich auch ein
Parameter außerhalb der Ansicht erreichen lässt.

**Keep as test data** behält die Ausgabe am Schritt, und **Set test data** gibt welche
als JSON-Objekt von höchstens 64.000 Bytes ein. Ein Testlauf gibt Testdaten weiter,
statt den Schritt auszuführen, sodass ein langsamer Modellaufruf oder ein Schreiben in
ein Livesystem einmal erfolgt und wiederverwendet wird. Ein Schritt, der den Weg
entscheidet, behält nie Testdaten, und die Veröffentlichung entfernt sie alle: Eine
veröffentlichte Version führt ihre Schritte immer aus. Ein Stecknadelsymbol markiert die
Karte, und **Remove test data** entfernt sie.

**Test step** führt den Schritt allein aus und ist der Hauptknopf des Bereichs, solange
es noch keine Daten gibt. Der Lauf behält nur den Schritt und die Schritte, die zu ihm
führen, und jeder davon mit bekannter Ausgabe, aus Testdaten oder dem letzten Testlauf,
gibt diese weiter, statt zu laufen. Der Rest läuft, und nichts nach dem Schritt. Ein
Schritt, der schreibt, fragt zuerst, denn der Test schreibt wirklich. Ein Schritt in
einer Schleife lässt sich nicht allein testen, weil er einmal je Element läuft, also
testen Sie die Schleife. Während der Test läuft, stoppt ihn das Quadrat neben **Test step**.
Endet er, ohne den Schritt auszuführen - gestoppt, in einen anderen Zweig
geleitet oder schon davor beendet -, sagt ein Warnzeichen dort, was geschehen ist. Über
die API tut `step` auf `POST /api/v1/workflow-runs` dasselbe.

### Ressourcen-Auswahlfelder { #resource-pickers }

Eine Einstellung, die eine Ressource pinnt, öffnet ein Auswahlfeld statt eines
Freitextfeldes, sodass ein Schritt eine reale Sache benennt, die Ihre Organisation
hat:

| Auswahlfeld | Was es pinnt |
|---|---|
| **Agent** und **Version** | Einen Agent, an seinem Avatar und seiner Beschreibung erkennbar, dann eine seiner veröffentlichten Versionen, mit markierter Live-Version sowie Datum und Release Note jeder Version. Ein Wechsel des Agents löscht die gepinnte Version, weil eine Version zu einem Agent gehört. Die Karte des Schritts zeigt dann den Avatar des Agents und „Name · v3“ |
| **Table** und **Columns** | Eine [Virtual Table](virtual-tables.md), dann die Spalten, die der Schritt liest — begrenzt auf das aktuelle Schema dieser Tabelle |
| **Secret** | Ein [Vault](secrets.md)-Secret, per Referenz. Ein Schritt speichert die id des Secrets, nie seinen Wert |
| **MCP server** und **Tool** | Einer der [MCP-Server](mcp.md) der Organisation, mit dem Zeichen seines Dienstes, dann eines der Tools, die er beim letzten Test gelistet hat. Die Wahl erfordert das Recht, den Workflow zu bearbeiten - per Rolle oder per Freigabe, wie beim Veröffentlichen des Schritts -, nicht `mcp:manage`; nur wer Server verwaltet, kann einen testen oder einen weiteren hinzufügen |

Jedes Auswahlfeld unterscheidet gleichnamige Zeilen durch Kontext und markiert
eine Referenz, deren Ziel verschwunden ist. Die Auswahlfelder **Agent** und
**Secret** bieten zusätzlich einen Link zum Neuanlegen — immer, nicht nur wenn die
Liste leer ist — während das **Table**-Auswahlfeld keinen hat. Eine Tabelle, deren Schema sich seit dem Binden geändert
hat, sagt es und bietet **Rebind to the current schema** an, sodass ein veralteter
Spaltensatz eine sichtbare Aufforderung ist statt eines stillen Bruchs.

### Evals für einen Modellschritt { #evals-for-a-model-step }

Ein Schritt, den ein Modell beantwortet - ein Agent, **Ask a model**, **Classify**,
**Extract data**, **Summarize or translate** oder eine Entscheidung -, hat einen Tab
**Evals**: die Fälle, die er bewältigen soll, und was seine Antwort dann sagen soll.
**Add a case** nimmt die Eingabe, mit der der Schritt zuletzt getestet wurde - die
Eingabe des Laufs und was die Schritte davor übergaben -, also testen Sie den Schritt
zuerst einmal, benennen dann den Fall und sagen, wo in der Antwort zu schauen ist
(`text`, `category`, ein Pfad wie `structured.amount` oder nichts für die ganze
Ausgabe) und ob sie einen Wert **enthalten**, **nicht enthalten** oder ihm **gleichen**
soll, ohne Groß- und Kleinschreibung und Leerzeichen darum.

**Try** startet für jeden Fall einen Testlauf des Schritts, geprüft und abgerechnet
wie jeder andere, und jeder Fall wird als bestanden oder nicht markiert, sobald sein
Lauf endet, mit dem, was die Antwort sagte, oder warum sie keine gab. Ein Fall, dessen
Lauf nicht starten kann - zu viel Arbeit in Bearbeitung, das Monatsbudget aufgebraucht
-, wird mit dem Grund als nicht bestanden markiert. Führen Sie die Fälle nach einer
Änderung von Prompt, Modell oder Anweisungen aus. Ein Schritt hält bis zu 50 Fälle,
und sie auszuführen braucht `workflows:edit`, wie das Testen des Drafts.

### Ein im Schritt konfigurierter Agent { #an-agent-configured-in-the-step }

Ein **Agent**-Schritt legt entweder einen Agent aus dem Katalog fest oder
definiert mit **Hier konfigurieren** einen eigenen: einen Namen, ein Modell,
Anweisungen, Capabilities mit dem Wissen, den Skills und Kontextdateien, die sie
lesen, und MCP-Server - in denselben Editoren wie der Builder. Delegation ist die
eine Capability, die er nicht erhält, denn der Workflow reicht die Arbeit bereits
von Schritt zu Schritt weiter.

Dieser Agent gehört dem Workflow. Er wird mit dem Graphen versioniert und erscheint
nie im Katalog. Sein erster Run legt ihn an, und ein Run nach einer Änderung seiner
Konfiguration veröffentlicht zuerst eine neue Version, geprüft wie jede
Veröffentlichung eines Agents. Seine Runs stehen in Activity mit Budget, Freigaben
und Verlauf wie bei jedem Agent, und seine Seite dort führt zurück zum Workflow.

**Seine Konfiguration in diesen Schritt kopieren** beginnt mit einem Agent aus dem
Katalog, um ihn anzupassen, und **Als Agent speichern** legt den Agent des Schritts
als Entwurf in den Katalog, für andere Workflows und Personen. **Max cost (USD)** begrenzt,
was eine Ausführung des Schritts ausgeben darf, neben den Limits des Agents, des
Workflows und der Organisation.

### Wenn ein Schritt langsam ist oder fehlschlägt { #when-a-step-is-slow-or-fails }

Unter den **Settings** eines Schritts legt **When it is slow or fails** seine Policy
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

### Schnelles Log { #quick-log }

Ein schnelles Log schreibt jedes Mal, wenn ein Schritt in einem Lauf endet, eine Zeile
in das Log des Workflows, sodass Sie sehen, was ein Workflow getan hat, ohne jeden Lauf
zu öffnen. Es ist eine Einstellung des Schritts. Fahren Sie über eine Karte und wählen
Sie **+ Log**: Ein **LOG**-Streifen dockt außen an der rechten Seite der Karte an, die
Ausgangs-Handles des Schritts wandern an seinen äußeren Rand, und jede protokollierte
Ausgabe hat einen Balken. Entfernen Sie das schnelle Log, um den Schritt nicht mehr zu
protokollieren.

Die **Nachricht** ist eine Vorlage von 1 bis 500 Zeichen, standardmäßig
`{{step}} → {{outcome}}`. Sie kann `{{step}}`, den Namen des Schritts, und
`{{outcome}}`, die Ausgabe, über die der Schritt endete, verwenden. Außerdem die
Ausgabefelder des Schritts über ihren Pfad, etwa `{{record.id}}`, sowie
`{{error.code}}` und `{{error.message}}` bei einem Fehler. Ein Verweis, der sich nicht
auflösen lässt, wird leer dargestellt, ebenso ein Listenindex: Pfade führen nur durch
Objekte.

**Outputs** wählt, welche Ergebnisse eine Zeile schreiben. Standardmäßig tut es jede
Ausgabe; haken Sie weniger an, um nur diese zu protokollieren, und entfernen Sie das
schnelle Log, um nichts zu protokollieren. Auf einem **Loop item**- oder
**Loop yield**-Schritt ist ein schnelles Log nicht erlaubt. Setzen Sie es auf den
**For each**-Schritt selbst: Er schreibt über seine Ausgabe `done` eine Zeile, wenn
seine Schleife schließt. Ein Schritt ohne Ausgaben protokolliert seine Fehler.

Fehler werden immer geschrieben. Ein Fehler, den kein `error`-Port weiterleitet, wird
unabhängig von den angehakten Ausgaben protokolliert, denn ein Lauf, der still
fehlschlug, ist genau das, wofür ein Log da ist. Ein Fehler, den ein `error`-Port
weiterleitet, folgt dem **Outputs**-Filter wie jedes andere Ergebnis.

Für einen übersprungenen, ausgeschalteten oder nie gestarteten Schritt wird keine Zeile
geschrieben, ebenso nicht für einen, den eine [Wiederholung ab dem fehlgeschlagenen
Schritt](#running-a-workflow) wiederverwendet statt ausgeführt hat. Ein Log verändert
nie einen Lauf: Eine Nachricht, die sich nicht schreiben lässt, wird verworfen, und der
Lauf geht weiter, wie er es sonst täte. Auch ein Test-Run schreibt Zeilen, als Test
markiert, und eine Zeile von einem Schritt, der angeheftete Testdaten weitergab, ist als
angeheftet markiert.

Zeilen werden mit ihrem Lauf aufbewahrt und mit ihm entfernt, wenn die Aufbewahrung des
Verlaufs den Lauf entfernt (siehe [Workflow-Einstellungen](#workflow-settings)). Sie
lesen sie auf der [Logs-Seite](#the-logs-page) oder, je Schritt, in der Laufansicht.

## Verbindungen und foreach-Scope { #connections-and-foreach-scope }

Sie ziehen eine Kante, indem Sie einen Ausgangs-Port eines Knotens mit einem
Eingangs-Port eines anderen Knotens verbinden. Der Editor lehnt eine Verbindung
zwischen Ports, die unterschiedliche Formen tragen, ab, bevor er sie zeichnet,
sodass eine inkompatible Verbindung nie auf der Zeichenfläche landet, und eine
Verbindung zu ziehen, die schon besteht, bewirkt nichts.

Eine Kante legt fest, in welcher Reihenfolge die Schritte laufen; sie bewegt keine
Daten. Die Werte, die ein Schritt liest, sind seine **Bindings**, beschrieben unter
[Einen Knoten konfigurieren](#configuring-a-node).

Damit Sie nicht jedes Feld von Hand
binden müssen, bindet das Verbinden zweier Ports, die genau dieselbe Form tragen — etwa
die Ausgabe eines Echo mit der Eingabe eines Relay —, auch jeden Input des Ziels an das
gleichnamige Feld der Quelle. Ein Feld, das Sie schon gebunden hatten, bleibt unberührt.

Unterscheiden sich die Formen oder trägt ein Port keine Daten, wird eine Wahl dennoch für
Sie getroffen: Ein Schritt, der mit einer Liste arbeitet, hinter einem Schritt verbunden,
der genau eine weitergibt - **Filter a list** hinter **List records** -, liest diese
Liste. Sonst wird nichts gebunden, und Sie wählen jede Quelle selbst mit **Data**. Undo (`Ctrl`/`Cmd` + `Z`) nimmt die Verbindung samt ihren
Bindings zurück, und das spätere Löschen einer Kante lässt ihre Bindings bestehen —
entfernen oder binden Sie sie in den Einstellungen des Schritts neu.

Um eine Verbindung zu löschen, wählen Sie sie aus: Klicken Sie auf die Linie, dann wird sie dicker gezeichnet, und auf ihr erscheint eine Schaltfläche **Delete connection**. Drücken Sie die Schaltfläche,
`Delete` oder `Backspace`, dann verschwindet die Verbindung, und die beiden Schritte bleiben. Die
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
Element den Körper durchlaufen hat. Die Schrittauswahl und die Binding-Quellen folgen dem Scope,
in dem Sie sind, und ein Schritt im Körper darf alles lesen, was vor der Schleife
lief. Was die Schleife tut, steht in der
[Knoten-Referenz](reference/workflow-nodes.md#loops).

### Parallele Zweige { #parallel-branches }

Jeder Schritt kann einen Ausgangsport an mehrere Schritte schicken, und diese laufen
gleichzeitig. Der Schritt **Split** tut dasselbe mit benannten Zweigen und nimmt
alle; er hat keine Bedingung und kann keine Fehler weiterleiten. Welcher Zweig
zuerst endet, ist nicht festgelegt, nichts darf sich also auf die Reihenfolge
verlassen. Zeichnen Sie die Beine und führen Sie sie dort zusammen, wo ein späterer
Schritt braucht, was sie getan haben.

Ein Schritt mit mehreren eingehenden Verbindungen ist ein Join und braucht keinen
**Merge**. Er läuft, sobald jeder Schritt, der zu ihm führt, abgeschlossen ist,
wenn mindestens eine seiner Verbindungen aktiv ist: Ein Bein, das ein If nicht
genommen hat, hält ihn nicht auf. Er wird übersprungen, wenn keine Verbindung aktiv
ist und wenn ein Schritt, der zu ihm führt, ohne Fehlerpfad fehlgeschlagen ist.
Seine Bindings dürfen nur Schritte lesen, die sicher vorher gelaufen sind; ein Join
darf also jedes Bein einer parallelen Gruppe lesen, aber nicht den Zweig eines If,
der vielleicht nicht lief.

Ein **Merge** hat die Einstellung **Wait for**. **The branch that ran** gibt die
Ausgabe des einen Zweigs weiter, der ihn erreicht hat, und das Veröffentlichen lehnt
ihn ab, wenn zwei seiner Eingänge zusammen laufen können. **All branches** wartet
auf jeden Eingang und gibt jeden unter seinem Namen als `branches` weiter, spätere
Schritte lesen also `branches.<Name>`; jede Verbindung hat einen **Branch name**.

Das Veröffentlichen lehnt es ab, wenn ein Eingang vielleicht nicht läuft - mit
seinem Namen - oder wenn nur einer je laufen kann. Eine zweite Verbindung an einen
Merge wählt die Einstellung, die der Graph braucht, und das Umbenennen eines
Zweignamens zieht die Schritte nach, die ihn lesen, in einem Rückgängig. Die Details
stehen in der [Knotenreferenz](reference/workflow-nodes.md#logic-if-and-logic-merge).

Das Veröffentlichen lehnt außerdem einen Graphen mit zwei **Output**-Schritten oder
zwei **Respond to webhook**-Schritten ab, die in einem Run beide laufen können, und
einen **Error handler**, den zwei Schritte speisen, die im selben Run fehlschlagen
können. Geben Sie jedem Bein einen eigenen.

Ein Zweig, der ohne Fehlerpfad fehlschlägt, lässt den Run fehlschlagen. Die Schritte
neben ihm starten nichts mehr, und was sie in Arbeit hatten, wird geschlossen:
offene Freigaben, Timer und die Agent-Runs, auf die ein Schritt geparkt ist. Ein
Schritt, der danach fertig wird, wird als **Finished after the run stopped**
festgehalten, seine Arbeit bleibt erhalten, und eine [Wiederholung](#running-a-workflow)
verwendet ihn weiter, statt es noch einmal zu tun. Der Status des Runs folgt seinen
aktiven Schritten, ein Zweig, der auf eine Freigabe wartet, ist also auch dann
sichtbar, wenn ein anderer noch läuft.

Das Budget des Runs wird geteilt. Jeder Schritt, der Geld ausgibt, und jeder
Workflow, den er aufruft, schöpft aus dem, was das Limit nach den Ausgaben und nach
dem übrig lässt, was andere laufende Schritte halten, nie mehr als sein eigenes
`max_cost_usd`. Ein Schritt, der den Rest in der Hand seiner Nachbarn findet, wartet
und fragt erneut, jedes Mal etwas später, statt den ganzen Rest zu bekommen. Eine
Reservierung endet, wenn der Schritt, der sie genommen hat, abgeschlossen ist.

Benachbarte
KI-Schritte laufen unter einem Run-Budget nur dann nebeneinander, wenn jeder ein eigenes
`max_cost_usd` hat: Ein Schritt ohne eines hält den ganzen Rest, sodass seine Nachbarn
warten, bis er abgeschlossen ist.

Wie viele Zweige gleichzeitig laufen, bestimmt der Worker, nicht der Run. Es gibt
kein Limit pro Run, die Zweige eines Runs können also jeden Workflow-Slot eines
Workers belegen, `WORKER_WORKFLOW_CONCURRENCY` (standardmäßig fünf, siehe
[Konfiguration](configuration.md)), und der Rest wartet in der Schlange. Ein Run,
auf den jemand wartet, geht vor einem, der sich selbst gestartet hat. Eine breite
Verzweigung in einem Run bremst daher andere Runs auf diesem Worker; machen Sie sie
so breit, wie die Arbeit es verlangt.

## Validierungs-Rückmeldung { #validation-feedback }

Der Editor prüft den Graphen während der Bearbeitung. Vor dem Test tragen unvollständige Schritte eine neutrale Einrichtungsmarkierung; die Zeichenfläche zeigt **Finish setup**. Öffnen Sie die Checkliste, um zu einem Schritt zu springen. Testen oder Veröffentlichen zeigt Fehler an; beim Verlassen eines leeren Pflichtfelds erscheint dessen Meldung inline. Die Veröffentlichung bleibt gesperrt, bis alle Validierungsprobleme behoben sind.

Die Einstellungen eines Schritts bleiben kurz. Was der Schritt braucht und was Sie
bereits gesetzt haben, steht sofort da; optionale Einstellungen mit ihren Standardwerten
warten hinter einer Schaltfläche, die sie zählt - **3 more options** -, und
erscheinen über ihr, bis **Fewer options** sie wieder einklappt; wie der Schritt
läuft, wartet unter **Settings**. Ein erforderlicher Wert, den Sie noch
nicht angegeben haben, wird neben seinem Feld erst markiert, wenn Sie das Feld verlassen
oder ausführen oder veröffentlichen wollen: Die Markierung des Schritts auf der
Zeichenfläche sagt es von Anfang an. Eine Beschreibung, die nur den
Namen des Felds wiederholt, ist ein Hinweis am Namen statt einer Zeile unter dem Feld.

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
bearbeiten, schreibt den aktuellen Graphen, und der Status unter dem Titel, nach seinen Tags, spiegelt
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

Die Konfiguration unbeaufsichtigter Ausführungsrechte erfordert eine Mitgliedssitzung: Veröffentlichung eines Webhook-, Zeitplan-, Tabellen-, Formular-, GitHub-, E-Mail- oder Kanal-Triggers, Aktivierung seiner Exposition, Rotation seines Geheimnisses oder Formularlinks, Zeitplanänderungen und Auswahl eines Fehler-Workflows. Organisations-API-Schlüssel können manuelle Workflows veröffentlichen, erlaubte Ausführungen starten und Automatisierungen pausieren; sie dürfen die Benutzerrechte ihres Ausstellers nicht für spätere Ereignisse hinterlegen. Bestehende Automatisierungen einer Vorabinstallation müssen aus einer vertrauenswürdigen Mitgliedssitzung erneut veröffentlicht werden; historische Datensätze speichern die Herkunft des veröffentlichenden Schlüssels nicht.

MCP-Schritte prüfen bei Veröffentlichung und Ausführung die aktuelle Sichtbarkeit der Verbindung, Gruppen- und Ressourcenrechte sowie `allowed_tools`. Eine leere Liste erlaubt keine Werkzeuge. Nachträglich entzogener Zugriff verhindert die Ausführung vor dem Lesen von Zugangsdaten und vor einem Serveraufruf.

Die DOCX-Extraktion liest Dokument-XML als Datenstrom und stoppt am konfigurierten Zeichenlimit; Entpackung und Verschachtelung sind ebenfalls begrenzt. Das Limit greift ohne Aufbau des vollständigen Dokumentbaums.


Der Verlauf lädt jeweils 50 Metadateneinträge; **More** lädt ältere Versionen.
Die API akzeptiert `before` und `limit` (1–100) und liefert `next_before`, bis
keine älteren Versionen bleiben. Graphen werden erst beim Öffnen einer Version
geladen. Eine fehlgeschlagene Seite lässt sich ohne Verlust geladener Einträge
erneut anfordern.

**Publish** friert den aktuellen Draft als unveränderliche Version ein, die läuft —
eine Version wird nach ihrer Erstellung nie geändert. Der Publish-Dialog nennt die Version, die er erzeugt, und nimmt
eine optionale **Release note** entgegen, die beschreibt, was sich geändert hat; hat
sich der Draft seit der Live-Version nicht geändert, sagt er das zuerst. Hat der
Graph noch Probleme, wird das Veröffentlichen mit **Fix the problems below before
publishing** blockiert, sodass eine Version, die nicht validieren würde, nie
entsteht.

Das Veröffentlichen beendet Ihr Bearbeiten nicht. Der Draft existiert weiter
unabhängig von jeder veröffentlichten Version, sodass Sie ihn sofort weiter
bearbeiten. **Versions** unter **More** in der Kopfzeile des Editors öffnet jede veröffentlichte
Version mit ihrer Release note, die Live-Version mit **Live** markiert. **View** öffnet eine frühere Version schreibgeschützt
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

**Compare with draft** in der Vorschau einer Version zeichnet Version und Entwurf
auf einer Fläche: Jeder Schritt, den der Entwurf hinzugefügt, geändert oder entfernt
hat, ist auf seiner Karte markiert, und die Liste daneben nennt jeden geänderten
Schritt mit dem, was sich in ihm geändert hat - eine Einstellung, eine Eingabe,
Name, Notiz oder Version, ob er ausgeschaltet ist und was er tut, wenn er langsam ist
oder fehlschlägt. Einen Schritt verschieben und angeheftete Testdaten sind keine
Änderungen. **Show this version** kehrt zur Version allein zurück.

## Workflow-Einstellungen { #workflow-settings }

**Settings** gruppiert Zeitsteuerung und Fehlerbehandlung, Verlauf und Aufbewahrung sowie Limits in aufklappbare Bereiche. Bereiche mit geänderten Werten sind zunächst offen. Die Run-Seite beginnt mit dem Verlauf; **Live performance** zeigt Statistiken veröffentlichter Runs. Runs und Logs halten weitere Steuerelemente unter **Filters**. Ein abgelehnter Run-Filter aus einem Link öffnet sein Feld samt Fehlermeldung automatisch.

Für gespeicherte Inline-Ergebnisse gelten gemeinsame Grenzen: `WORKFLOW_RUN_MAX_INLINE_RESULT_BYTES` (64 MiB je Ausführung) und `WORKFLOW_ORG_MAX_INLINE_RESULT_BYTES` (1 GiB über aufbewahrte Ausführungen). Reservierungen zählen kompakte Versuchsergebnisse, einschließlich synthetischer Schleifenausgaben, und mögliche Ausführungs-, Webhook- und Fehlerkopien. Sie messen weder den physischen PostgreSQL-Speicher noch ersetzen sie eine Deployment-weite Speicherpolitik. Kleine abschließende Fehlerdatensätze dürfen das volle Limit überschreiten, damit die Ausführung enden kann. `WORKFLOW_INLINE_RESULT_LIMIT` lässt sich nicht durch Fehlerpfade umgehen; Kosten bleiben erhalten, Auswirkungen werden nicht automatisch wiederholt. Ein Handler kann vor Ablehnung seines Ergebnisses bereits gehandelt haben. Dateireferenzen oder Verlaufslöschung geben Reservierungen frei.

Ein fortgesetzter Agent behält die engere Grenze: sein beim Pausieren gespeichertes Gesamtlimit oder bisherige Kosten plus aktuell verbleibendes Workflow-Budget. Ausgaben paralleler Zweige während einer Freigabe stellen den alten Spielraum nicht wieder her. Jeder Eval-Fall verbraucht ein Ausführungskontingent, auch innerhalb eines Stapels; erschöpfte Fälle werden als abgelehnt gespeichert. Die erste HTTP-Reservierung wird dem ersten Fall angerechnet.

Angeheftete Ausgaben importieren verschachtelte Dateireferenzen nach aktueller Zugriffsprüfung. Aufnahme und Aufbewahrung teilen die Dateisperre: ein bestätigter Import schützt seinen Erzeuger, und die Bereinigung prüft Referenzen nach dem Warten erneut. Editorbeispiele behalten die neuesten Ausführungsdaten trotz verspäteter älterer Antworten; Einfügen erhält Notizen, gemischte Notiz- und Schrittänderungen werden gemeinsam angewendet.

Die Migration `0231_workflow_result_bytes.py` füllt Zähler aus vorhandenem unkomprimiertem JSON-Text, konservativ gegenüber neuen kompakten Reservierungen. API- und Worker-Schreibzugriffe müssen währenddessen gestoppt sein. Bereits übergroße Verläufe bleiben erhalten, blockieren aber weitere große Ergebnisse bis zur Bereinigung oder Anhebung des Limits. Bereits gelöschte Inhalte werden nicht wiederhergestellt.

Reservierungen umfassen auch die ursprüngliche Eingabe, den Entwurfssnapshot im Testmodus und jedes gespeicherte Wait-Fortsetzungspayload. Admission und Resume reservieren vor Schreiben oder Aufwecken; eine Ablehnung liefert `WORKFLOW_INLINE_STORAGE_LIMIT` (429). Resume-Links authentifizieren vor dem Lesen des Bodys. Migration `0232_workflow_input_bytes.py` ergänzt bestehende Payloads in den Zählern, ohne Ergebnisse oder Gebühren zu entfernen. API und Worker während des Backfills anhalten; überschreitet eine Organisation bereits das Limit, muss sie Verlauf bereinigen oder das Limit erhöhen.

Entwürfe, veröffentlichte Versionen und aufbewahrte Importe schützen referenzierte Dateien vor Bereinigung. Ein erzeugender Workflow kann nicht gelöscht werden, solange ein anderer seine Dateien referenziert; Referenzen entfernen oder archivieren. Änderungen, Admission, Importe und Bereinigung teilen die Lebenszyklussperre der Organisation. Löschen prüft Run-Abhängigkeiten vor dem Entfernen der Trigger und versucht GitHub-Hooks über die Kontointegration abzumelden; Anbieterfehler bleiben im Log sichtbar.

Combine by key akzeptiert skalare Schlüssel und lehnt Listen oder Objekte ohne Retry ab. Eval-Fälle werden unter einer Sperre gezählt und positioniert. Das Dashboard berücksichtigt alle sichtbaren Workflows, auch über 500; beendete Runs aktualisieren Dateien unabhängig von den Schritten.

Verschachtelte Importe werden anhand der Datei-ID dedupliziert und vor Datenbankprüfungen durch `WORKFLOW_GRAPH_MAX_BINDINGS` begrenzt.

Ein Quell-Run bleibt erhalten, solange ein Retry aktiv ist oder ein anderer aufbewahrter Run eine seiner Dateien importiert. Das Ende eines Retrys macht weiterhin referenzierte Dateien nicht ungültig.

**Settings** unter **More** in der Kopfzeile des Editors enthalten, womit ein Workflow ausgeführt
wird, nicht was er tut. Sie gehören dem Workflow, nicht einer Version: Eine Änderung
gilt für jeden danach gestarteten Lauf, und das Veröffentlichen behält sie.

- **Timezone** - darin wird der Cron-Ausdruck eines Zeitplans gelesen, auch über die
  Zeitumstellung hinweg, und darin schreibt ein **Date & time**-Schritt, der keine
  eigene Zeitzone nennt. Ein Lauf behält die beim Start gesetzte. Ohne Angabe UTC.
  Das Feld sagt, wie spät es dort gerade ist, und lehnt eine Zeitzone ab, die der
  Browser nicht kennt.
- **Default deadline** - die Frist, die ein Lauf bekommt, wenn das, was ihn startet,
  keine nennt.
- **Error workflow** - ein veröffentlichter Workflow, der mit **On failure of a
  workflow** beginnt und einmal gestartet wird, wenn ein Lauf fehlschlägt. Siehe
  [Wenn ein anderer Workflow fehlschlägt](#when-another-workflow-fails).
- **Keep runs for** und **Keep runs that succeeded** - ein täglicher Durchlauf
  entfernt einen Lauf und die von ihm gespeicherten Dateien so viele Tage nach seinem
  Ende, und einen erfolgreichen Lauf am nächsten Tag, wenn erfolgreiche nicht behalten
  werden. Ohne Angabe bleiben Läufe dauerhaft.

**Limits** begrenzen, was seine Läufe gleichzeitig tun und ausgeben, über den
eigenen Grenzen jedes Schritts - darunter die Kostenobergrenze eines Agentenschritts:

- **Runs under way at once** - ein echter Lauf, der darüber hinaus gestartet wird,
  wird mit `429` abgelehnt, bis einer endet. Der Absender eines Webhooks oder GitHub
  wird um einen erneuten Versuch gebeten, ein Zeitplan wartet auf seinen nächsten
  Takt, und ein Tabellenereignis oder eine Formularantwort darüber hinaus wird
  abgelehnt. Ein Postfach wird eine Minute später erneut gelesen, unabhängig vom Intervall, die Nachricht wartet
  also, bis ein Lauf endet - außer die Läufe, die das Limit belegen, warten auf eine
  Freigabe: Dann wird die Nachricht für diesen Workflow übersprungen, und das Audit-Log
  hält es fest (`workflow.mail_message_skipped`). Testläufe werden weder gezählt noch
  zurückgehalten.
- **Most one run may spend** - das eigene Budget des Laufs, das engere aus ihm und dem
  der Version: Ein Lauf, der es erreicht, hält vor seinem nächsten Schritt an,
  außerhalb des Budgets.
- **Most its runs may spend a month** - über den Kalendermonat in UTC gezählt,
  Testläufe eingeschlossen. Ist es erreicht, startet kein Lauf - `402` -, bis der Monat
  wechselt oder das Budget erhöht wird. Die Seite der Läufe zeigt die Ausgaben des
  Monats im Vergleich dazu.

Über die API ersetzt sie `PUT /api/v1/workflows/{id}/settings`.

Die Aufbewahrungsregel entfernt Inhalte und Dateien der Läufe, bewahrt aber
Beträge und Aufnahmezeitpunkte für die monatliche Budgetabrechnung auf. Das
Löschen der Historie füllt das Monatsbudget des Workflows nicht wieder auf.
Zuvor gelöschte Kosten können nicht rekonstruiert werden.

## Einen Workflow ausführen { #running-a-workflow }

**Test draft** in der Kopfzeile des Editors führt den Draft sofort aus, nie die veröffentlichte Version - `Strg`/`Cmd` +
`Enter` ebenso - und fragt zuerst nach den Feldern, die ein Manual- oder API-Trigger
deklariert. Der Run erscheint dann live auf der Zeichenfläche. Ein Badge an der Ecke
jedes Schritts zeigt, wo er steht - **Pending**, **Starting**, **Running** mit
mitlaufender Zeit, **Waiting**, **Failed**, **Needs attention**,
**Skipped** oder **Not reached** -, und ein erfolgreicher Schritt zeigt, wie
lange er gebraucht hat. Die Verbindung in einen laufenden Schritt bewegt sich, der
genommene Weg wird grün, und ein Zweig, den der Run nicht genommen hat, verblasst. Ein
fehlgeschlagener Schritt zeigt seinen Fehler unter seiner Karte und wackelt einmal.
Eine Verbindung sagt, wie viele Elemente über sie gingen, wenn der Schritt davor eine
Liste weitergab, und eine Leiste unten sagt, wie der Run steht, mit **Open run** für
seine Seite. Solange der Run läuft, stoppt ihn das Quadrat neben **Test draft** ohne
Rückfrage. Die Zeichenfläche behält den Run, wenn er endet; die nächste Bearbeitung
blendet ihn aus und lässt eine Leiste stehen, dass sich der Graph seitdem geändert hat,
weiter mit **Open run**. Ein Schritt, der gewartet hat und weiterging, zählt einen Versuch, nicht zwei. **Test draft** wartet,
solange eine Änderung noch gespeichert wird, und sagt, warum er nicht laufen kann,
solange der Draft Probleme hat.

**Runs** in der Kopfzeile des Editors und das Runs-Icon auf der Karte eines
Workflows öffnen seine Runs, die neuesten zuerst, jeder mit seinem Status, ob er den
Draft oder die veröffentlichte Version ausgeführt hat, was ihn gestartet hat, wann,
wie lange und zu welchen Kosten. **Start a run** startet einen von Hand: **Test the
draft** führt den Draft in seinem jetzigen Stand aus, **Published version** die
Live-Version. Sein **Input (JSON)** ist das, was der **Input**-Schritt des Workflows
als `payload` weitergibt.

Über der Liste fasst **How it ran** die echten Läufe der letzten 7, 30 oder 90 Tage
zusammen: wie viele liefen und wie viele fehlschlugen, der Anteil der beendeten, der
erfolgreich war, die typische Dauer und die, innerhalb derer 95 von 100 fertig wurden,
und was sie je Tag kosteten. Die Kostenkarte nennt auch die Ausgaben dieses Monats,
Testläufe eingeschlossen, im Vergleich zum Monatsbudget des Workflows - rot, sobald es
aufgebraucht ist. **By step** zeigt, woher Zeit, Kosten und Fehler kamen, die teuersten
zuerst. Über die API ist es `GET /api/v1/workflows/{id}/stats?days=30`.

Hat der Workflow in diesem Zeitraum eine Person um Freigabe gebeten, fasst **Freigaben
(Approvals)** zusammen, wie entschieden wurde: **Wie vorgeschlagen freigegeben (Approved
as proposed)**, **Vor der Freigabe bearbeitet (Edited before approval)** mit dem Median
des Textanteils, den die Änderungen betrafen, **Abgelehnt (Rejected)**, wie viele
Anfragen **abgelaufen** sind, und die **Zeit bis zur Entscheidung (Time to decide)**,
die typische und die, innerhalb derer 95 von 100 entschieden waren. Eine Tabelle nennt
dieselben Zahlen für jeden Freigabeschritt.

Das Fenster sind dieselben Tage, gezählt ab dem Zeitpunkt, an dem die Person gefragt
wurde; Testläufe bleiben außen vor. Der Anteil der Freigegebenen und der Anteil der wie
vorgeschlagen Freigegebenen (über die API `acceptance_rate` und `unchanged_rate`; die
Karte zeigt den zweiten) beziehen sich auf die Anfragen, über die entschieden wurde,
also freigegebene oder abgelehnte: Eine Anfrage, die abgelaufen ist oder mit ihrem Run
abgebrochen wurde, wurde nie entschieden; sie wird gezählt, geht aber nicht in die
Quoten ein. Ein Schritt, der sich nicht bearbeiten lässt, zählt als wie vorgeschlagen
freigegeben. Die Zahlen sagen, was geschah, und bewerten es nicht.

Die Zahlen gelten je Schritt und je Tag, nicht je Art von Nachricht. Um Kategorien zu
vergleichen, leiten Sie jede an einen eigenen Freigabeschritt.

Wie stark eine Änderung den Text verändert hat, wird einmal gemessen, wenn die Person
entscheidet, mit demselben Verfahren wie bei
[`text.compare`](reference/workflow-nodes.md#text-compare), zeichenweise: `0`, wenn sie
den Vorschlag in einem bearbeitbaren Schritt unverändert freigegeben hat, bis `1`, wenn
nichts davon übrig ist. Ein Schritt, der sich nicht bearbeiten lässt, eine Ablehnung und
ein Ablauf haben keine solche Zahl. Eine Änderung, die vor der Messung entschieden
wurde, hat sie ebenfalls nicht und bleibt aus dem Median heraus, statt als keine
Änderung zu zählen; wurde im Zeitraum keine Änderung gemessen, steht auf der Karte
**Change not measured** („Änderung nicht gemessen“).

Dieselben Zahlen kommen über die API im Block `approvals` der Statistik. Über alle
Workflows, die Sie sehen, im gewählten Zeitraum liefert `GET
/api/v1/workflow-approvals/stats?from=2026-10-01&to=2026-10-31` die Summen und die fünf
Workflows mit den meisten Anfragen; die Karte **Freigabe-Ergebnisse (Approval
outcomes)** im [Dashboard](console.md#the-dashboard) zeigt sie.

Die Karte **Workflows** im Dashboard rechnet dasselbe über jeden Workflow zusammen,
den Sie sehen, im Zeitraum, auf den das Dashboard eingestellt ist: Runs, Fehler,
Kosten und die fünf aktivsten. Darüber zählt sie die Runs, die gerade auf eine Person
warten - eine Freigabe oder einen Schritt, der Aufmerksamkeit braucht -, egal wann sie
begonnen haben. Über die API ist es
`GET /api/v1/workflows/summary?from=2026-10-01&to=2026-10-31`.

Ein Run öffnet mit seiner Dauer, seinen Kosten (eine Ausgabe unter $0.0001 steht als `<$0.0001`, nicht als null) und der Zahl erledigter Schritte,
dann mit dem Fehler, mit dem er endete, falls es einen gab. Daneben steht der Graph,
den er ausgeführt hat, so gezeichnet, wie der Editor einen Run zeichnet: das Badge
jedes Schritts, seine Versuche und sein Fehler, und die Schritte, die er nie erreicht
hat, blass. Nur eine Seite, die offen war, während der Run lief, bewegt sich; eine
später geöffnete bleibt still. **Open loop body** zeigt die Iterationen einer Schleife auf dieselbe Weise.

Die Antwort des Runs - sein Text, sein strukturiertes Ergebnis, die Passagen, auf
die er sich stützte, und wie viele Dateien er erzeugt hat, mit dem JSON selbst unter
**Raw output** - und jeder Schritt, den er gemacht hat, Iteration für Iteration,
stehen daneben. Ein laufender Run aktualisiert sich alle paar Sekunden, und **Cancel
run** stoppt ihn. Seine **Files** listen, was seine Schritte gespeichert haben - einen Download, eine
gerenderte Seite, die Ausgabe eines Skripts -, jeweils zum Herunterladen.

Ein Run, der auf einen Schritt [**Ask for approval**](reference/workflow-nodes.md#human-approval)
wartet, erscheint im Tab **Freigaben (Approvals)** unter Activity. Ist beim Schritt **Let the
approver edit** gesetzt und ein Vorschlag gebunden, etwa eine vorbereitete Antwort,
ändert die freigebende Person ihn dort in einem Editor, mit **Original
wiederherstellen (Restore original)** und **Änderungen anzeigen (Show changes)**,
und gibt ihre Fassung frei. Der Schritt gibt dann `final`, `original` und `edited`
weiter, sodass ein späterer Schritt sendet, was die Person freigegeben hat. Wer entscheiden darf, vom
Schritt aber nicht genannt wird, sieht den Vorschlag schreibgeschützt, und eine mit
einer geänderten Fassung entschiedene Anfrage trägt unter **Entschieden (Decided)** das Zeichen
**Bearbeitet (Edited)**.

Listet der Schritt **Ways to approve**, zeigt die Warteschlange statt **Approve** eine
Schaltfläche je Weg, mit der Beschriftung, die ihr Autor geschrieben hat; **Reject**
bleibt. Jeder Weg ist ein Ausgangsport des Schritts, der Workflow geht also über den
weiter, den die freigebende Person gedrückt hat, und die entschiedene Zeile nennt ihn.
Eine Bearbeitung geht mit jeder gedrückten Schaltfläche mit.


In der Liste lautet die Version eines Testlaufs **Draft (test)** und die eines echten
**Published**, und ein aus der Konsole oder über die HTTP-API gestarteter Lauf
lautet **Console or API**. **Status**, **Version**, **Started by** und **Started** (die letzte Stunde, der letzte Tag,
die letzte Woche oder 30 Tage) grenzen die Läufe ein, und die Liste
antwortet seitenweise; jeder Filter steht in der Adresse, sodass sich eine
gefilterte Liste verlinken lässt. **Runs** in der Workflow-Liste zeigt die Läufe
aller Workflows zusammen. Auf der Seite eines Laufs zeigt ein Klick auf einen
Schritt dessen **Input** und **Output** aus diesem Lauf. Die Zeilen, die das
[schnelle Log](#quick-log) eines Schritts geschrieben hat, stehen unter dem Schritt.

**Retry from failed step**
startet einen neuen Lauf derselben Version mit derselben Eingabe, in dem jeder
erfolgreiche Schritt weitergibt, was er zuvor weitergegeben hat. So laufen nur der
fehlgeschlagene Schritt und was er nicht erreicht hat, und ein Schreibzugriff
geschieht nie zweimal. Eine Schleife läuft erneut und verwendet die erfolgreichen
Schritte jedes Elements wieder. **Debug in editor** heftet an die Schritte des
Entwurfs, was jeder Schritt außerhalb einer Schleife in diesem Lauf weitergegeben
hat, sodass ein Testlauf dort beginnt, wo jener war. Über die API wiederholt `POST
/api/v1/workflow-runs/{id}/retry`, und `GET /api/v1/workflow-runs` nimmt `status`,
`mode`, `triggered_by`, `created_after` und `created_before`.

**Resolve** erscheint an einem Schritt, der Aufmerksamkeit braucht, solange sein Run
noch läuft. Ein Schritt braucht Aufmerksamkeit, wenn er gewirkt haben kann und
niemand sein Ende sah, oder wenn er aufgehört hat zu warten und nichts ihn mehr
weckt. Der Dialog nennt den Schritt und sagt, welcher Fall es ist. **Run it again**
reiht den Schritt für einen neuen Versuch im selben Run ein und warnt bei einem
Schritt, der etwas geschrieben haben kann, dass es dadurch doppelt geschehen kann.
**Treat it as failed** ist **Take its error route**, wo der Schritt seine Fehler
weiterleitet oder in einer Schleife steht, oder **Fail the run**. Hat der Schritt ein
Ergebnis gemeldet, nachdem er aufgegeben wurde, geht **Use that result** von diesem
aus weiter. Sonst wird nichts im Run angetastet, Nachbarschritte, Freigaben und
Timer laufen also weiter.

Einen Schritt klärt nur, wer den Run gestartet hat, oder ein Editor des Workflows,
und in einem Test-Run darf nur ein Editor einen Schritt klären oder den Run
wiederholen. Über die API dient dazu `POST
/api/v1/workflow-runs/{id}/steps/{node_run_id}/rerun` mit einem `choice`, und die
Entscheidung wird auditiert. Ein abgebrochener oder fehlgeschlagener Run hat keinen
Schritt mehr zu klären: **Retry from failed step** startet einen neuen Run. Ein
Schritt, der nach dem Stopp seines Runs fertig wurde, ist mit **Finished after the
run stopped** markiert, und eine Wiederholung verwendet ihn weiter.

### Die Logs-Seite { #the-logs-page }

**Logs** unter **More** in der Kopfzeile des Editors listet, was die schnellen Logs des
Workflows über seine Läufe hinweg geschrieben haben, die neuesten zuerst: wann, der
Schritt, sein Ergebnis und die Nachricht. Grenzen Sie die Zeilen nach **Step**,
**Outcome** und **Written** (letzte Stunde, letzter Tag, letzte Woche oder 30 Tage) ein,
durchsuchen Sie die Nachricht und schalten Sie **Include test runs** ein - bis dahin
bleiben Test-Runs ausgeblendet. Für die Zeilen eines einzelnen Laufs fügen Sie seine ID
in **Run** ein oder tippen die ersten Zeichen davon (mindestens vier); **Show only this
run** an einer Zeile füllt das Feld aus, und **See in Logs** auf der Seite eines Laufs
öffnet die auf diesen Lauf gefilterten Logs. Eine Zeile öffnet den Lauf, der sie
geschrieben hat. In der Laufansicht stehen die Zeilen jedes Schritts unter ihm, in der
Reihenfolge des Schreibens. Ein Organisations-API-Schlüssel mit `workflows:view` liest
sie ebenfalls, für Läufe öffentlichen Ursprungs: siehe [Das Log eines Workflows
lesen](api.md#reading-a-workflows-log).

### Alerts { #log-alerts }

Ein Alert benachrichtigt Menschen, wenn das Log zu oft etwas Bestimmtes schreibt. Unter
der Liste enthält die Karte **Alerts** die Regeln eines Workflows; **Add alert** öffnet
eine neue. Eine Regel hat einen Namen und zählt die passenden Zeilen:

- **Outcomes**: die Ergebnisse, die zählen, aus denen, die das Log des gewählten Schritts
  schreibt, plus `error`. Eine Zeile, die über mehrere Ports ging, passt zu jedem davon.
- **Step**: ein Schritt oder jeder Schritt, der loggt.
- **Message contains**: optionale Wörter, ohne Beachtung der Groß- und Kleinschreibung.
- **Occurrences** und **Within**: mindestens so viele passende Zeilen (1 bis 1000) innerhalb
  von 5, 15, 30 oder 60 Minuten, 4 Stunden oder einem Tag.

Eine Regel löst höchstens einmal pro Fenster aus: Danach schweigt sie für die Länge ihres
Fensters, zählt dann ab diesem Zeitpunkt neu, und keine Zeile wird für zwei Auslösungen
gezählt. Es zählen nur echte Runs; die Zeilen eines Testlaufs lösen nie einen Alert aus.
Ein Workflow hat bis zu 25 Regeln, und ein Schalter an jeder pausiert sie.

**Who is told** ist der **Eigentümer** des Workflows, womit eine neue Regel beginnt, die
**Admins** der Organisation oder **bestimmte Personen**, die Sie wählen; wer die
Organisation verlassen hat, wird übersprungen. Jede von ihnen erhält eine Benachrichtigung
in der Glocke und eine E-Mail, soweit ihre eigenen
[Benachrichtigungseinstellungen](governance.md#alerts) es erlauben; wer den Workflow nicht
mehr ansehen darf, sieht sie nicht mehr. Die Benachrichtigung nennt, wie viele Zeilen
passten, und ihr Link öffnet die Logs-Seite, gefiltert auf Schritt und Ergebnisse der
Regel. Eine Regel mit einem Ergebnis, das der Schritt der Live-Version nicht hat, wird in
der Liste markiert.

Die Regeln sieht, wer den Workflow ansehen darf; wer ihn bearbeiten darf, per Rolle oder
per Grant darauf, legt sie an, ändert, pausiert und löscht sie. Die Regeln sind nicht Teil
der öffentlichen API.

## Einen Workflow von außerhalb der Konsole starten { #starting-a-workflow-from-outside-the-console }

Ein Workflow kann mehrere unabhängige **Trigger** haben, etwa Manual, Webhook und Schedule. Ein neuer Trigger erhält vorhandene Starts und Verbindungen. Jeder Run wählt einen Start und führt nur dessen erreichbaren Zweig aus; er wartet nicht auf andere Trigger. Ein gemeinsamer Schritt darf nur Daten lesen, die von jedem zu ihm führenden Start verfügbar sind. Unterschiedliche Eingaben sollten vor gemeinsamen Schritten getrennt normalisiert werden.

Die Veröffentlichung aktiviert alle konfigurierten unbeaufsichtigten Eingänge mit den Rechten des veröffentlichenden Mitglieds. Pro Workflow ist höchstens ein Trigger jeder unbeaufsichtigten Art erlaubt. Erneutes Veröffentlichen erhält Adressen und Zugangsdaten bestehender Knoten und entfernt gelöschte Registrierungen. **Trigger** unter **More** zeigt alle veröffentlichten Starts und ihre Optionen. **Active** in der Kopfzeile pausiert oder aktiviert sämtliche Registrierungen. **Test draft** bietet eine Startauswahl; die API akzeptiert `entry_node_id`, reale Anfragen dürfen aber nur Manual/API wählen, niemals einen unbeaufsichtigten Eingang.

Eine Version, die mit **Manual** oder **API request** oder ganz ohne Trigger startet, startet jeder,
der sie ausführen darf, als er selbst: **Start a run** unter Runs, die
[HTTP-API](api.md#running-a-workflow) oder ein WebSocket. Jeder Run wird geprüft,
abgerechnet und auditiert wie ein hier gestarteter. Diese Wege starten keinen anderen
Trigger, und jeder andere Trigger hat einen eigenen. Ein Test-Run des Drafts nimmt
jeden Trigger, und **Start a run** öffnet ihn mit einer Eingabe in der Form dieses
Triggers.

**Manual** ist der Trigger, den eine Person mit **Test draft** startet; **API request** ist der, den ein System aufruft, und **Trigger** zeigt seinen Endpunkt und eine Beispielanfrage. Gib einem von beiden **Eingabefelder**, und ein Run fragt nach dem, was er braucht: **Test draft** und **Start a run** zeigen statt des JSON ein Formular mit einem Feld je
Eingabefeld, so typisiert wie dieses, und ein API-Aufruf, dessen Eingabe nicht passt,
wird mit den falschen Feldern abgelehnt. Siehe
[core.input](reference/workflow-nodes.md#core-input).

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

**Open chat** im Kopf des Editors probiert einen Entwurf, der mit einer
Chat-Nachricht beginnt, ohne ihn zu verlassen. Jede im Panel gesendete Nachricht
startet einen Test-Run des Entwurfs mit dieser Nachricht, der Run öffnet sich auf
der Fläche, und seine Antwort - der Text des Output-Schritts - erscheint unter der
Nachricht. Es sind Test-Runs ohne Unterhaltung, in die sie antworten könnten, also
erreicht nichts aus dem Panel einen echten Chat. **New chat** beginnt neu mit einer
neuen Unterhaltungs-ID.

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
Uhrzeit oder nach einem Cron-Ausdruck, in der Zeitzone des Workflows (UTC, sofern seine **Settings** keine andere nennen)
und höchstens einmal pro Minute, zu seinem Tick und nicht erst beim nächsten Durchlauf danach.
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

Webhook-Inhalte werden beim Streamen begrenzt, auch ohne Content-Length. Testaufrufe
haben die 64-KB-Grenze angehefteter Daten; reguläre Webhook- und GitHub-Aufrufe nutzen
`WORKFLOW_RUN_MAX_INPUT_BYTES`. Antworten mit Status 204, 205 oder 304 enthalten
gemäß HTTP keinen Body, behalten aber erlaubte Header. PDF-Bildkonvertierung lehnt
Dokumente mit mehr als 2.000 Seiten ab, bevor Seitengrößen gelesen werden, auch wenn
nur eine Seite angefordert wurde.

### Wenn ein Tabellen-Datensatz hinzukommt, sich ändert oder gelöscht wird { #when-a-table-record-is-added }

Ein **Table record**-Trigger nennt eine Tabelle, die Datensatz-Ereignisse (`events`),
bei denen er startet - hinzufügen, ändern, löschen -, und filtert den Datensatz, wie
er hinzugefügt oder geändert wurde, oder wie er vor dem Löschen war - aus der Konsole,
der API, durch einen Agent oder den Tabellenschritt eines anderen Workflows. Eine
Änderung startet ihn nur, wenn sich eine gewählte Spalte geändert hat, sofern Spalten
der Tabelle gewählt sind.

Er gibt den Datensatz weiter: `record_id`, `event`, `values` nach Spalten-ID,
dieselben Werte als `fields` nach Beschriftung, eine Auswahl als Label ihrer Option,
`before` und die `changed` Spalten bei einer Änderung oder Löschung und die
`author_id` dessen, der es tat. Das Veröffentlichen braucht Lesezugriff auf die
Tabelle, und nichts vor der Veröffentlichung startet ihn.

Ein so gestarteter Run trägt die Kette der Trigger, die er
durchlief, sodass ein Workflow, der in die Tabelle zurückschreibt, deren Trigger ihn
startete, blockiert wird statt im Kreis zu laufen.

**Triggers** der Tabelle selbst listet die Workflows, die mit ihr starten, pausiert
und setzt sie fort und zeigt, was jeder über jeden Datensatz entschieden hat. Siehe
[Virtual Tables](virtual-tables.md#triggers).

### Über ein Formular { #from-a-form }

Ein Trigger **Form** gibt dem Workflow eine öffentliche Seite: einen Titel, eine
Beschreibung und ein Feld je deklariertem Feld, typisiert wie die Felder von
**Manual**, mit eigenen Worten auf der Schaltfläche und nach dem Senden. Die
Veröffentlichung legt die Seite an, und **Trigger** zeigt ihren Link zum Kopieren
oder Öffnen. Jeder mit dem Link füllt sie ohne Anmeldung aus, und jede Antwort, die
zu den Feldern passt, startet einen Lauf als das Mitglied, das das Formular
veröffentlicht hat. Die Schritte danach lesen die Antworten als `payload`, und die
Seite der Läufe sagt, dass ein Formular ihn gestartet hat.

Der Link ist das einzige Zugangsmerkmal der Seite und übersteht jede
Veröffentlichung desselben Knotens. **New link** ersetzt ihn, und der alte antwortet
dann, als gäbe es kein Formular; das Pausieren des Triggers schließt die Seite.
Antworten, die nicht passen, werden auf der Seite benannt und starten nichts, ein
verstecktes Feld fängt Skripte ab, und jedes Formular nimmt höchstens
`RATE_LIMIT_FORM_SUBMISSIONS_PER_MINUTE` Antworten pro Minute an. Siehe
[trigger.form](reference/workflow-nodes.md#trigger-form).

### Von GitHub { #from-github }

Ein Trigger **GitHub** startet den Workflow, wenn in einem Repository etwas geschieht:
ein Issue, ein Kommentar, ein Pull Request oder sein Review, ein Push, ein Release
oder ein Actions-Lauf - was **Starts on** nennt, und nur die aufgeführten **actions**
wie `opened`, sofern welche genannt sind. Die Veröffentlichung gibt ihm eine eigene
Adresse und ein Signaturgeheimnis. Ist **Set up the webhook for me** an und das
GitHub-Konto der Organisation mit der Berechtigung verbunden, Webhooks zu verwalten,
registriert die Veröffentlichung den Hook im Repository und bei jeder späteren erneut;
sonst zeigt sie das Geheimnis einmal, zum Einfügen mit der Adresse aus **Trigger**
unter **Settings > Webhooks** des Repositorys.

Jede von GitHub signierte Zustellung für dieses Repository, Ereignis und diese Aktion
startet einen Lauf als das Mitglied, das den Workflow veröffentlicht hat, mit
`event`, `action`, `repository`, `sender` und dem ganzen `payload`. Eine erneute
Zustellung antwortet mit ihrem ersten Lauf, und alles andere - einschließlich des
`ping` von GitHub - wird übersprungen. **New secret** ersetzt das Geheimnis und
registriert den Hook dort neu, wo das Konto ihn angelegt hat. Siehe
[trigger.github](reference/workflow-nodes.md#trigger-github).

### Über eine E-Mail { #from-an-email }

Ein Trigger **Gmail** startet den Workflow, wenn im Gmail-Postfach der Organisation -
dem über das Portal **Gmail** verbundenen - eine Nachricht ankommt. Das Panel des
Schritts sagt, ob ein Postfach verbunden ist, und verbindet eines, und die
Veröffentlichung wird abgelehnt, bis es so ist. Das Postfach wird von dem Abruf gelesen, der auch die Gmail-Trigger der Agenten auslöst, jede Minute, und jede neue
Nachricht, die zu allen gesetzten Filtern passt - **Subject contains** und **Sender
contains** ohne Groß- und Kleinschreibung, **Label** genau -, startet einen Lauf als
das Mitglied, das den Workflow veröffentlicht hat.

**Check for new mail every** im Postfachblock des Schritts ändert diesen Takt (1, 5, 15, 30 oder 60 Minuten). Es ist eine Einstellung des Postfachs und gilt für jeden Trigger darauf.

**Sender contains** liest die Adresse des Absenders, nie den Anzeigenamen:
`@acme.com` passt genau auf diese Domain und nicht auf ihre Subdomains, eine
vollständige Adresse passt auf diese Adresse, anderer Text auf einen Teil der
Adresse. Ist es gesetzt, muss die Nachricht außerdem die Prüfung des authentifizierten
Absenders bestehen - DMARC bestanden oder von der Domain des Absenders mit DKIM
signiert -, sodass ein `From`, das jeder eintippen kann, keinen Lauf startet.
Nachrichten mit dem Label `SENT`, `DRAFT`, `SPAM` oder `TRASH` sind keine Eingänge und
starten nichts, es sei denn, **Label** nennt eines davon.

Der Lauf bekommt `sender`, `to`, `subject`, `text`, `snippet`, `labels` und die
`message_id` des Postfachs sowie den Thread, zu dem die Nachricht gehört: `thread_id`,
`rfc_message_id` (der `Message-ID`-Header), `in_reply_to`, `references`,
`received_at` und den `html`-Inhalt. Die drei Header-Felder schreibt der Absender;
mit ihnen lässt sich eine Antwort in den Thread einordnen, sie beweisen aber nichts
darüber, wer die Nachricht gesendet hat. Eine zweimal gelesene Nachricht startet
ihren Lauf einmal, und eine, für die die Organisation noch keinen Platz hatte, wird eine Minute später erneut gelesen. Siehe
[trigger.gmail](reference/workflow-nodes.md#trigger-gmail). Um den `html`-Text als
Text, als Links oder als das zu lesen, was ein CSS-Selektor auswählt, binden Sie ihn an
[`html.parse`](reference/workflow-nodes.md#html-parse).

Ein **Outlook**-Trigger tut dasselbe für das Microsoft-365-Postfach der Organisation,
verbunden über das **Outlook**-Portal. Microsoft Graph wird Ordner für Ordner
gelesen, deshalb nennt der Schritt den **Folder**, den er beobachtet - ohne Angabe
den Posteingang - und, um ein gemeinsames Postfach zu lesen, das das verbundene Konto
öffnen kann, das Feld **Shared mailbox**. Die Filter sind **Subject contains**, **Sender
contains**, **Has attachments**, **Importance** und **Category**. Das erste Lesen
eines Ordners beginnt mit dem Zeitpunkt, zu dem der Workflow veröffentlicht oder zuletzt
eingeschaltet wurde; Post, die schon dort liegt, startet nichts.

Ein gemeinsames Postfach, das der Microsoft-Grant der Organisation öffnen kann, zu
nennen, erfordert die Berechtigung, Verbindungen zu verwalten, wie bei Outlook-Agent-Triggern;
ein Workflow, der schon eines liest, behält es bei späteren Veröffentlichungen, und es zu
ändern erfordert die Berechtigung erneut. Meldet Outlook, dass der Ordner nicht
mehr gelesen werden kann, wird der Workflow ausgeschaltet, und das Audit-Log nennt
den Grund.

Der Lauf bekommt dieselben Felder wie ein Gmail-Lauf, wobei `labels` die
Kategorien der Nachricht enthält und `mailbox` das gemeinsame Postfach, aus dem sie
kam. Siehe [trigger.outlook](reference/workflow-nodes.md#trigger-outlook).

Beide Mail-Trigger nehmen Eingaben von außen an: Jeder kann dem Postfach eine
Nachricht schicken, binden Sie also, was der Lauf damit tut, wie bei einem Webhook.

Die `attachments` einer Nachricht nennen Name, angegebenen Typ und Größe jeder
Datei; ein Postfach liefert höchstens 20 pro Nachricht, und ein `text`- oder
`html`-Inhalt wird bis zu 20.000 Zeichen gelesen. Ein Lauf, den das Postfach
gestartet hat, speichert sie als Dateien des Runs, und jede trägt ihr `file` und
`stored: true`. Von den genannten Anhängen werden nur die ersten 10 berücksichtigt,
zusammen bis 25 MiB, und jeder muss in das Größenlimit für Chat-Uploads, die Liste
erlaubter Dateitypen und das Speicherkontingent der Organisation passen.

Ein ausgelassener Anhang trägt einen `reason`: `too_many` (nach den ersten 10),
`too_large`, `type_not_allowed`, `quota` oder `unreadable` - das Postfach antwortete
darauf mit 400, 401, 403 oder 404, oder sein Grant fehlt, ist ausgeschaltet oder
lässt sich nicht erneuern. Ein Testlauf liest nichts aus dem Postfach, seine Anhänge
sind daher `not_fetched`. Scheitert das Postfach auf eine Weise, die eine
Wiederholung beheben kann, schlägt der Schritt mit `MAIL_ATTACHMENT_UNREACHABLE`
fehl und wird wiederholt.

### Über eine Kanalnachricht { #from-a-channel-message }

Ein Trigger **Channel message** übergibt dem Workflow die Nachrichten eines Slack-,
Mattermost- oder Telegram-Bots. Jede Nachricht, die der Bot mit seinem eigenen
Agenten beantwortet hätte - sie hat die Zugriffsrichtlinie des Bots passiert, ihr
Absender wurde zugelassen, und in einem Kanal hat sie den Bot genannt -, startet
einen Lauf als das Mitglied, das den Workflow veröffentlicht hat, wenn sie zu
**Where** und **Only when the message contains** passt. Eine Nachricht, die einen
Agenten per `@handle` nennt, erreicht weiterhin diesen, und eine, die nicht passt,
beantwortet der Agent des Bots wie bisher.

Der Trigger übergibt `text`, `sender` - mit dem Mitglied, das der Absender verknüpft
hat, falls er es tat - sowie `channel_id` und `thread_id`, die ein Schritt **Send a
message** derselben Plattform annimmt, sodass die Antwort im Thread der Nachricht
landet. Slack- und Mattermost-Trigger übergeben auch bei einer Nachricht auf oberster
Ebene einen Thread, weil die Nachricht selbst ihn eröffnet, sodass eine gebundene
Antwort im Thread steht; ein Telegram-Trigger übergibt ein Thema nur innerhalb eines
Forenthemas.

Ein **Send a message**-Schritt, der nach einem **Channel message**-Trigger hinzugefügt
wird, startet als der Bot des Triggers, mit gebundenen `channel_id` und `thread_id`, wenn
die Plattformen übereinstimmen. Die Nachrichten eines Bots starten höchstens einen
Workflow, und das Zuhören braucht `channels:manage`. Eine Sprachnachricht kommt als Transkript an; andere
Anhänge werden nicht übergeben. Siehe
[trigger.channel_message](reference/workflow-nodes.md#trigger-channel-message).

### Wenn ein anderer Workflow ihn aufruft { #when-another-workflow-calls-it }

Ein Auslöser **Called by a workflow** macht einen Workflow, den andere als Schritt
ausführen: gemeinsame Logik - einen Lead anreichern, ein Ticket anlegen - an einem
Ort. Er deklariert seine Felder wie **Manual**, und der Schritt **Run a workflow**
eines anderen Workflows, der nur so veröffentlichte Workflows anbietet, startet ihn
mit der gebundenen Eingabe, die zuerst gegen diese Felder geprüft wird.

Der Schritt
wartet auf den aufgerufenen Lauf und gibt dessen `output` weiter, oder geht sofort
weiter, wenn **Wait for it to finish** aus ist. Der aufgerufene Lauf ist mit dem
aufrufenden in beide Richtungen verknüpft - seine Seite sagt **Called by** diesen Lauf,
und die Zeile des Schritts auf der Seite des Aufrufers öffnet den Lauf, den er gestartet
hat - und erscheint auf den Laufseiten wie jeder andere. Ein von einem Fehler-Workflow
gestarteter Lauf sagt, welcher fehlgeschlagene Lauf ihn gestartet hat. Ein Aufruf
zurück in einen Workflow, der in der Kette schon läuft, oder tiefer als fünf Aufrufe,
wird abgelehnt.

Aufgerufene Workflows übernehmen das verbleibende Laufbudget des Aufrufers und
die frühere Frist. Ihre Kosten zählen zum Gesamtbetrag des Aufrufers; `own_cost`
enthält nur dessen direkte Gebühren, damit aggregierte Laufdaten nichts doppelt zählen.
Bei begrenztem Budget muss das Warten auf den Abschluss aktiviert bleiben. Abbruch
oder entzogene Berechtigungen des Aufrufers stoppen das Kind vor dem nächsten Schritt;
eine laufende externe Anfrage kann noch enden. Ein erneuter Aufruf verwendet die
erfolgreichen Schritte des ursprünglichen, eingefrorenen Kindes. Ein noch laufendes
Kind muss zuerst enden oder gestoppt werden. Ergebnisdateien werden ausdrücklich in
den Aufrufer importiert; beim Fortsetzen wird der Zugriff erneut geprüft.

Tagesdiagramm und Schrittstatistiken des Aufrufers enthalten ebenfalls die Gebühren aufgerufener Läufe.

Die Wiederherstellung stoppt bei fehlenden Ergebnissen erfolgreicher Schritte
sowie gelöschten Aufrufen oder zyklischer Wiederholungshistorie. Effekte werden
nicht wiederholt, um diese Historie zu ersetzen. Abbruch, ausgeschöpftes Budget
und entzogene Berechtigungen des Kindes bleiben nicht umgehbare Fehler.

### Von einem Agenten { #from-an-agent }

Ein Agent mit der Capability [Workflows](reference/capabilities.md#workflows) startet
die Workflows, die seine Spec nennt, als Werkzeuge, wenn ein Gespräch nach dem fragt,
was einer tut. Er liest die Eingabefelder jedes Workflows, startet einen Lauf damit als
das Mitglied, für das er handelt, und wartet bis zur Grenze des Bindings auf die
Antwort. Der Lauf wird geprüft, abgerechnet und auditiert wie einer aus **Start a run**,
und die Seite der Läufe sagt, dass **An agent** ihn gestartet hat. Einem Agenten lässt
sich nur ein veröffentlichter Workflow geben, der mit **Manual**, **API request** oder
**Called by a workflow** beginnt.

Ein Run, hinter dem kein Mitglied steht (der Besucher eines Widgets, eines Embeds
oder einer gehosteten Seite, ein nicht verknüpfter Absender in einem Kanal, die
Zustellung eines Ereignis-Triggers eines Agenten), startet keinen.

### Aus einer App { #from-an-app }

Eine [veröffentlichte Seite](artifacts.md#actions) kann einen Workflow starten, den ihr
Agent gebunden hat und der aus **Manual** oder **API request** startet. Die Seite fragt nur.
Dem Mitglied, das sie ansieht, wird ein Dialog mit dem eigenen Namen des Workflows und
jedem Eingabewert gezeigt, und der Run startet erst, wenn es bestätigt. Er gehört ihm:
sein Zugriff, sein Budget und seine Run-Seite, geprüft, abgerechnet und auditiert wie ein
Run, der mit **Start a run** gestartet wurde, und derselben Admission-Quote unterworfen.
Ein Run ohne Mitglied dahinter oder aus einer Session, die imitiert wird, startet keinen.

Die Run-Seite nennt einen solchen Run gestartet von **A page**, und **Started by** filtert
danach; über die API ist sein `triggered_by` `app`. Der Run hält auch die Seite und die
Version fest, die das Mitglied ansah, und ein Retry behält sie. Die Seite liest nur den
Status des Runs, seine Antwort und die erste Zeile eines Fehlers zurück.

### Wenn ein anderer Workflow fehlschlägt { #when-another-workflow-fails }

Ein Auslöser **On failure of a workflow** macht einen Fehler-Workflow. In den
**Settings** eines anderen Workflows als dessen Fehler-Workflow gewählt, startet er
einmal für jeden echten Lauf jenes Workflows, der fehlschlägt, mit der `run_id` des
Laufs, seiner `workflow_id` und `workflow_name`, der `step_id` und `step_name` des
fehlgeschlagenen Schritts und dem `error`, mit dem er endete. Er läuft als das
Mitglied, das ihn gewählt hat und ihn weiterhin ausführen können muss. Ein Testlauf
startet nichts, ebenso wenig das Scheitern eines Laufs, der selbst ein Fehler-Workflow
ist, sodass ein scheiternder Fehler-Workflow sich nie erneut startet.
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
| **Braucht Aufmerksamkeit** | Ein Schritt, der gewirkt haben kann, wurde unterbrochen oder hat aufgehört zu warten, und nichts weckt ihn | Prüfen Sie, ob seine Wirkung eingetreten ist, und klären Sie den Schritt dann im Run mit **Resolve**: erneut ausführen, ein spät gemeldetes Ergebnis verwenden, seinen Fehlerpfad nehmen oder den Run fehlschlagen lassen. Den Run abzubrechen und dann **Retry from failed step** zu wählen, beginnt von vorn |
| `PRINCIPAL_REVOKED` | Das Mitglied, als das der Run handelt, hat den Zugriff verloren oder sein Konto wurde deaktiviert | Ein Mitglied, das den Workflow ausführen darf, veröffentlicht ihn erneut, damit sein Trigger als es läuft |
| `WORKFLOW_TRIGGER_MISMATCH` | Der Run wurde über einen Weg angefordert, der nicht sein Live-Trigger ist: von Hand oder per API für einen Workflow, der mit einem Webhook startet, oder im Chat für einen, der nicht mit einer Chatnachricht startet | Starten Sie ihn so, wie sein Trigger es sagt, oder testen Sie den Draft, der jeden Trigger nimmt |
| `INVALID_BINDING` | Ein Wert passte nicht zu dem Feld, an das er gebunden war | Der Fehler des Schritts nennt das Feld; korrigieren Sie die Bindung oder den Wert davor |
| `REVISION_CONFLICT` | Jemand hat einen Datensatz geändert, nachdem der Schritt ihn gelesen hat | Leiten Sie den Fehler des Schritts mit `error.handle` zu einem frischen Lesen um |
| Der Verlauf eines Tabellen-Triggers zeigt **Blockiert** | Der Run hätte sich selbst erneut gestartet, oder seine Kette ging zu tief | Siehe [Trigger](virtual-tables.md#triggers) |
| Ein Webhook antwortet `403` | Die Signatur passt nicht zum Body, oder das Mitglied, als das er läuft, darf den Workflow nicht mehr ausführen | Signieren Sie genau die gesendeten Bytes mit dem aktuellen Secret, oder ein Mitglied, das ihn ausführen darf, veröffentlicht ihn erneut |

## Tastatur und Barrierefreiheit { #keyboard-and-accessibility }

Jeder Teil des Editors hat einen Weg, der keinen Zeiger braucht. Die Schrittauswahl ist eine Liste, durch die Sie mit den Pfeiltasten gehen und mit Enter wählen, jedes reine Icon-Bedienelement trägt
eine gesprochene Bezeichnung, und die Zeichenfläche nimmt den Tastaturfokus, sodass
Sie über ihre Schritte und Verbindungen tabben können. Eine Verbindung lässt sich
über die Tastatur herstellen: Starten Sie eine an einem Knoten und schließen Sie sie
an einem kompatiblen Ziel ab.

Die Tastenkürzel der Zeichenfläche feuern nur, solange der Fokus im Editor ist,
sodass sie nie eine Taste einem Feld anderswo auf der Seite stehlen:

| Tasten | Tut |
|---|---|
| `Tab` | Die Schrittauswahl öffnen |
| `Ctrl`/`Cmd` + `Enter` | Den Draft testweise ausführen, wo auf der Seite der Fokus auch liegt |
| `Ctrl`/`Cmd` + `Z` | Rückgängig |
| `Ctrl`/`Cmd` + `Shift` + `Z` oder `Ctrl`/`Cmd` + `Y` | Wiederherstellen |
| `Ctrl`/`Cmd` + `C` | Auswahl kopieren |
| `Ctrl`/`Cmd` + `X` | Auswahl ausschneiden |
| `Ctrl`/`Cmd` + `V` | Einfügen, versetzt, sodass es das Original nicht verdeckt |
| `Delete` oder `Backspace` | Die Auswahl löschen |
| `Escape` | Eine laufende Verbindung abbrechen |
| `?` | Diese Kürzel anzeigen |

Ein Einfügen bekommt frische ids und mappt die Bindings unter den kopierten
Schritten um, sodass eingefügte Schritte voneinander lesen statt von den Originalen.
Jedes Bearbeitungskürzel ist wirkungslos, solange der Editor schreibgeschützt ist - in
einer veröffentlichten Version oder im Modus **View only**; `Escape` bricht eine übrig
gebliebene Verbindung weiterhin ab, und `?` zeigt weiterhin die Kürzel.

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
  Fläche, eine Verbindung — hält ihn dort. Liegt der Fokus in den Einstellungen eines Schritts oder in der Schrittauswahl, bleiben die Tasten diesen Feldern, klicken Sie also die
  Zeichenfläche an, bevor Sie sie drücken.

Bildanhänge eines Agenten teilen sich ein Limit von 20 MB, geprüft vor jedem
Dateizugriff, auch bei wiederholten Referenzen. MCP-Ergebnisse entfernen
Authentifizierungsheader und Zugangsdaten aus Text und verschachtelten Daten.
Dateinamen werden vor dem Speichern auf höchstens 255 Zeichen normalisiert,
Erweiterungen bleiben erhalten. CSV-Felder können das konfigurierte Dateilimit
bis 50 MB nutzen; Parserablehnungen haben einen definierten Fehlertyp.

Eine Schleife misst neueste Yield-Ergebnisse und unbehandelte Fehler vor dem
Laden in SQL. `WORKFLOW_FOREACH_MAX_OUTPUT_BYTES` beträgt standardmäßig 10 MiB,
einschließlich Sammlungsaufwand; Überschreiten ergibt `FOREACH_OUTPUT_TOO_LARGE`.
Für große Ergebnisse kleinere Werte oder Dateiverweise ausgeben. Eine Kollision
zwischen Zusammenfassungsschlüssel und Gruppenfeld ergibt `SUMMARY_KEY_COLLISION`.

Laufeingaben, Entwurfskonfigurationen und angeheftete Ergebnisse müssen in
PostgreSQL JSONB darstellbar sein. Ein nicht speicherbares Knotenergebnis wird
`INVALID_NODE_OUTPUT`, ohne automatische Wiederholung und mit erhaltenen Kosten.
Eine externe Aktion kann bereits abgeschlossen sein; vor manueller Wiederholung
prüfen.

Inline-Ergebnisse teilen `WORKFLOW_NODE_MAX_OUTPUT_BYTES` (standardmäßig 10 MiB): Versuchsergebnis, Run-Ausgabe und Webhook-Antwort zusammen. Größere Ergebnisse scheitern mit `NODE_OUTPUT_TOO_LARGE`; Kosten bleiben erhalten, automatische Wiederholung entfällt. Split out prüft die expandierte Anzahl (höchstens 10.000) vor dem Kopieren und schätzt wiederholte Felder konservativ in Bytes. Eine Überschreitung ergibt `SPLIT_OUTPUT_TOO_LARGE`. Für größere Daten Dateiverweise verwenden.

Eine flache Vorprüfung der Modellfelder lehnt wiederholte große Werte ab, bevor die Serialisierung das gesamte Ergebnis kopiert.

Workflow-Sockets erhalten Identität und Berechtigungsgrenzen des Organisationsschlüssels bei jedem Frame und Stream-Abruf. Ein Leseschlüssel startet keine Runs; Schlüssel verfolgen keine privaten Runs eines Mitglieds und schreiben nicht in persönliche Chats. Worker behalten die Schlüsselgrenzen; ein Widerruf schließt den Stream beim nächsten Abruf.

Skill- und Kontextgalerien eingebetteter Agenten laden alle Metadatenseiten und bieten bei Fehlern einen neuen Versuch. Neue Eval-Eingaben erfüllen die JSONB- und Bytegrenzen der Run-Zulassung; ältere übergroße Fälle bleiben zum Entfernen lesbar. Fehlgeschlagene PDF- oder Sandbox-Dateibatches entfernen frühere Schreibvorgänge desselben Batches, bestehende Dateien bleiben erhalten. Fehlgeschlagene Skripte behalten ihr Diagnoseprotokoll.

## Zusammenfassung { #recap }

- Ein Workflow ist **ein Draft, den Sie bearbeiten, und eine veröffentlichte,
  unveränderliche Version, die läuft** — starten Sie einen mit einem Trigger oder
  aus einer Vorlage, und **Duplicate** kopiert einen Draft in einen frischen Workflow.
- Die **Schrittauswahl** fügt Schritte hinzu - über **+**, den Ausgang eines Schritts oder einen Rechtsklick; die **Zeichenfläche** verdrahtet sie und lehnt eine Verbindung zwischen inkompatiblen Ports ab.
- Eine Kante legt die **Reihenfolge** fest, Bindings tragen die **Werte**; das Verbinden
  von Ports gleicher Form legt die Bindings für Sie an.
- Ein Parameter ist **ein Wert oder Daten aus einem Schritt** — **Data** liest sie aus
  einer erreichbaren, typkompatiblen vorgelagerten Ausgabe oder fügt sie in Text ein.
- Der Draft **speichert sich selbst**, und eine Bearbeitung von zwei Stellen hebt
  ein Banner mit **Overwrite** oder **Reload**.
- **Publish** wird blockiert, solange ein Problem besteht, und validiert erneut auf
  dem Server; frühere Versionen bleiben schreibgeschützt einsehbar, und **Restore to
  draft** macht eine davon wieder zum Draft.
- Jede Aktion hat einen **Tastaturweg**, und die Bearbeitungskürzel sind auf einer
  schreibgeschützten veröffentlichten Version oder im Modus **View only** wirkungslos.
- Ein Workflow kann mehrere unabhängige **Trigger** haben, etwa Manual, Webhook und Schedule. Ein neuer Trigger erhält vorhandene Starts und Verbindungen. Jeder Run wählt einen Start und führt nur dessen erreichbaren Zweig aus; er wartet nicht auf andere Trigger. Ein gemeinsamer Schritt darf nur Daten lesen, die von jedem zu ihm führenden Start verfügbar sind. Unterschiedliche Eingaben sollten vor gemeinsamen Schritten getrennt normalisiert werden.
- Die **Policy** eines Schritts legt seine Versuche, sein Zeitlimit und fest, ob
  seine Fehler über einen **Error**-Port hinausgehen; der Körper eines **For
  each**-Schritts läuft einmal pro Element von **Loop item** bis **Loop result**.
- **Runs** listet jeden Run, **Start a run** testet den Draft oder führt die
  veröffentlichte Version aus, und ein Run zeigt seinen Graphen Schritt für Schritt,
  wie er abgelaufen ist.
