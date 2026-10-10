---
source_sha: "f3a9cc7f1767"
---

# Artefakte { #artifacts }

Ein **Artefakt** ist eine Seite, die ein Agent veröffentlicht hat: ein Bericht,
ein kleines Dashboard, eine einseitige Zusammenfassung, die jemand im Browser
öffnet. Es hat einen Link, der gleich bleibt, wenn der Agent es erneut
veröffentlicht, sodass „veröffentliche jeden Montag die Zahlen der Woche auf
dieser Seite“ ein Link ist, den man sich als Lesezeichen speichert, statt jede
Woche einen neuen.

Ein Artefakt ist keine Datei. Ein Diagramm, ein erzeugtes PDF und eine Datei im
Workspace haben bereits ein Zuhause im Chat und im [Workspace](sandbox.md). Ein
Artefakt ist das, was *ausgeliefert* wird: Es hat einen Besitzer, eine
Sichtbarkeit und Grants wie ein Agent oder ein Skill, und es kann einen
öffentlichen Link für jemanden ohne Konto bekommen.

## Eines veröffentlichen { #publishing-one }

Schalten Sie für den Agent die Capability **Artifacts** ein. Sie fügt zwei Tools
hinzu: `publish_artifact`, das das Modell aufruft, wenn das Ergebnis etwas ist,
das eine Person öffnen sollte, statt es einmal im Chat zu lesen, und
`read_artifact`, das eine veröffentlichte Seite zurückliest.

Die Seite kommt von einer von drei Stellen:

- **Eine Datei im Workspace des Agents**, die auf `.html` oder `.md` endet. Das
  ist der übliche Fall für einen Agent mit der Capability
  [Sandbox](reference/capabilities.md#files-shell): Er schreibt
  `report.html`, führt aus, was auch immer sie baut, und veröffentlicht dann die
  Datei. Die Bytes werden über das eigene Workspace-Backend des Runs gelesen,
  deshalb funktioniert das auf jedem Sandbox-Backend.
- **Die Seite inline übergeben**, für einen Agent ohne Workspace oder eine kurze
  Seite.
- **Änderungen an der Seite**, die unter diesem Namen bereits veröffentlicht ist
  — siehe unten.

Der Chat zeigt eine Karte für die veröffentlichte Seite. Die Karte verlinkt auf
die Version, die *dieser* Run veröffentlicht hat, sodass ein späteres Lesen der
Unterhaltung weiterhin zeigt, was darin veröffentlicht wurde, und nicht, was die
Seite heute zeigt.

### Einen Teil einer Seite ändern { #changing-part-of-a-page }

Ein geändertes Wort sollte nicht noch einmal die ganze Seite kosten. Der Agent
ruft `read_artifact` mit dem Namen der Seite auf, das die aktuelle Version so
liefert, wie sie geschrieben wurde, und dann `publish_artifact` mit demselben
Namen und `edits`: exakte Ersetzungen, der Reihe nach angewendet. Jede muss genau
eine Stelle der Seite treffen; eine, die keine oder mehrere trifft, geht zur
Korrektur an das Modell zurück. Das Ergebnis ist eine neue Version wie jede
andere.

Die Änderungen tragen die Version, auf der sie gemacht wurden. Hat dazwischen ein
anderer Run veröffentlicht, wird nichts geschrieben, und das Modell soll die Seite
neu lesen, sodass eine geänderte Kopie einer älteren Seite nie eine neuere
ersetzt. Das Lesen folgt derselben Regel wie das Öffnen in der Konsole: Die
Person, für die der Run handelt, muss die Seite öffnen dürfen. Eine Seite über
100.000 Zeichen kommt abgeschnitten zurück und sagt das; eine Änderung kann
trotzdem Text hinter dem Schnitt nennen.

## Ein Name, ein Link { #one-name-one-link }

Die Identität eines Artefakts ist sein **Name innerhalb des Agents** —
`weekly-report`, `churn-dashboard`. Wer unter demselben Namen veröffentlicht,
aktualisiert dasselbe Artefakt, von jeder Oberfläche aus: dem Chat, der API,
einem [Trigger](triggers.md) oder einem Workflow. Ein neuer Name ergibt eine neue
Seite. Der Name besteht aus Kleinbuchstaben, Ziffern und Bindestrichen, bis zu
64 Zeichen.

Der Name gilt auch **innerhalb der Umgebung**, aus der der Run geantwortet hat.
Ein Run in einer benannten [Umgebung](environments.md) — `staging`, `dev` —
veröffentlicht eine eigene Seite neben der der Standardumgebung, sodass der
Versuch einer neuen Version eines Agents nie die Seite neu veröffentlichen kann,
die Leser in Produktion als Lesezeichen haben. Die Umgebung wird vom Run selbst
gelesen, nie vom Modell, und die Liste und die Seite nennen sie.

Den Namen teilen sich alle, die den Agent ausführen, die Seite aber nicht. Ein
Run veröffentlicht ein bestehendes Artefakt nur dann erneut, wenn die Person, für
die er handelt, es besitzt oder `artifacts:edit` darauf hat — aus der Rolle oder
aus einem `edit`-Grant, dieselbe Regel wie bei der Verwaltung in der Konsole. Der
Run jeder anderen Person erfährt, dass der Name vergeben ist, und veröffentlicht
unter einem anderen. Eine Kollegin, die denselben geteilten Agent um einen
`weekly-report` bittet, kann die Seite hinter Ihrem Link also nicht ersetzen.

Jede Veröffentlichung ist eine neue **Version**. Nichts wird überschrieben, daher
ist die Versionsliste auf der Seite des Artefakts die Geschichte der Seite. Zwei
Dinge halten diese Geschichte begrenzt:

- Wer genau die Bytes veröffentlicht, die die aktuelle Version enthält, fügt
  keine Version hinzu. Das Ergebnis lautet `unchanged`, und ein Zeitplan, der
  nichts Neues gefunden hat, lässt die Geschichte in Ruhe. Es zählt trotzdem als
  Veröffentlichung, die Uhr der Aufbewahrung beginnt also von vorn.
- Nur die neuesten Versionen werden behalten, `ARTIFACT_MAX_VERSIONS` davon
  (standardmäßig 20). Eine ältere Version wird entfernt, wenn eine neue
  hinzukommt — außer einer, an die der öffentliche Link angeheftet ist. Eine
  Unterhaltung, die auf eine entfernte Version verlinkt, sagt, dass die Version
  nicht mehr aufbewahrt wird, und bietet die neueste an.

**Restore this version** holt eine aufbewahrte Version zurück. Ein Mitglied, das
die Seite bearbeiten darf, öffnet die Version und stellt sie wieder her; das fügt
eine neue Version mit den Bytes der alten hinzu, sodass die Geschichte behält, was
passiert ist, und sich die Wiederherstellung genauso rückgängig machen lässt.
Nichts Neues wird gespeichert. Es wird im Audit-Trail festgehalten.

## Unterstützte Formate { #supported-formats }

| Format | Was gespeichert wird | Was ausgeliefert wird |
|---|---|---|
| HTML (`.html`, `.htm` oder `format: html`) | Das Dokument, wie der Agent es geschrieben hat | Dasselbe Dokument, hinter einem kurzen Plattform-Skript (siehe [Wie die Seite isoliert wird](#how-the-page-is-isolated)) |
| Markdown (`.md`, `.markdown` oder `format: markdown`) | Die Markdown-Quelle | Die Quelle, gerendert zu einer schlichten Seite, Tabellen eingeschlossen. Rohes HTML darin wird maskiert |

Eine Version ist ein in sich geschlossenes Dokument von höchstens
`ARTIFACT_MAX_BYTES` (standardmäßig 5 MiB). Es gibt keine Bündel aus mehreren
Dateien: Betten Sie Ihr eigenes Skript, Ihre Stile und Bilder (als
`data:`-URIs) in die eine Datei ein.

!!! warning "Die Seite hat kein Netzwerk"

    Skripte laufen, ein von einer Bibliothek gezeichnetes Diagramm funktioniert
    also. Aber die Seite kann nichts von irgendwoher laden und nichts irgendwohin
    senden — ein CDN-Skript, eine Webschrift von einer URL und ein API-Aufruf
    schlagen alle fehl. Die einzige Ausnahme ist der Bibliothekssatz unten, den das
    Deployment selbst ausliefert. Das Tool sagt das dem Modell. Es ist Absicht, und
    [Wie die Seite isoliert wird](#how-the-page-is-isolated) sagt, warum.

### Der Bibliothekssatz { #the-library-set }

Das Deployment liefert neben jeder Seite einige Dateien aus, damit das Modell
nicht mehr in jede eine ganze Diagrammbibliothek kopiert. Eine Seite lädt sie über
eine relative Adresse und funktioniert weiter, wenn das Deployment seine Inhalte
später auf einen anderen Origin verlegt:

| Adresse in der Seite | Was es ist |
|---|---|
| `lib/chart-4.5.1.umd.min.js` | Chart.js 4.5.1, als `window.Chart` |
| `lib/d3-7.9.0.min.js` | d3 7.9.0, als `window.d3` |
| `lib/lucide-1.46.0.min.js` | Lucide-1.46.0-Icons, als `window.lucide` - derselbe Satz, den die Konsole verwendet |
| `lib/agenticos-2.css` | Das Aussehen der Konsole für Seiten, hell und dunkel, und die `ao-`-Komponenten, aus denen eine Seite gebaut wird |
| `lib/agenticos-2.js` | `window.AO`: Chart.js im Stil der Konsole, Zahlenformate in der Sprache der Seite, Icons, Tabs |
| `lib/agenticos-1.css` | Die erste Version des Aussehens, behalten für die Seiten, die gegen sie veröffentlicht wurden |

Jeder Name trägt seine Version und wird ein Jahr lang gecacht. Ein Upgrade fügt
eine neue Datei neben der alten hinzu, sodass eine Seite, die gegen eine Version
veröffentlicht wurde, weiter genau diese bekommt. Nichts wird von außerhalb des
Deployments geholt, also funktioniert ein Deployment ohne Internetzugang genauso.
Die Dateien sind in `backend/app/core/catalog/artifact_lib/` aufgeführt.

Der mitgelieferte [Skill](skills.md) **`artifact-pages`** bringt einem Agent bei, sie
zu nutzen: zwei Vorlagen (ein Dashboard und ein Bericht), den Hausstil mit seinen
Komponenten, Icons statt Emoji und wie man
eine Seite mit `read_artifact` ändert. Eine neue Organisation bekommt ihn mit den
anderen mitgelieferten Skills, eine bestehende über `seed-skills`, und der Tab
**Page style** der Capability Artifacts im Builder bietet ihn an. Bearbeiten Sie
den Skill, um Ihre eigene Marke zu beschreiben, und der Agent folgt ihr.

## Wer es öffnen kann { #who-can-open-it }

Ein neues Artefakt ist **privat** für die Person, für die der veröffentlichende
Run gehandelt hat: die Person im Chat oder der Ersteller eines Triggers.

Sein Link - der, auf den die Karte im Chat und die Antwort des Agents zeigen -
öffnet die Seite selbst, fensterfüllend unter einer Leiste mit Titel, Version
und **Share**. Der Link allein lässt niemanden hinein: Er öffnet sich nur für
ein angemeldetes Mitglied, das die Regeln unten bereits hereinlassen. Er nennt
die Organisation, in der das Artefakt liegt (`?org=`), sodass ein Mitglied
mehrerer Organisationen in der richtigen landet.

Unter **Share**
kann jeder, der es verwalten darf, es auf drei Wegen teilen:

| Reichweite | Wie | Wer |
|---|---|---|
| Bestimmte Personen | Ein Grant, mit `read` oder `edit` | Diese Mitglieder, in dieser Organisation |
| Die Organisation | Sichtbarkeit auf die ganze Organisation gesetzt | Jedes Mitglied, dessen Rolle geteilte Artefakte erreicht |
| Jeder mit dem Link | **Create a public link** | Jeder, der die Adresse hat, ohne Konto |

Teilen und Sichtbarkeit verwenden dasselbe Panel und dieselben Regeln wie bei
Agents und Skills; siehe [Berechtigungen](permissions.md). Ein Artefakt zu
verwalten — es zu teilen, seinen öffentlichen Link und dessen Einstellungen, eine
Version wiederherzustellen, es zu löschen — erfordert `artifacts:edit` auf diesem
Artefakt, aus der Rolle oder aus einem `edit`-Grant. Es zu öffnen, erfordert
`artifacts:view`.

Der Agent kann nicht erweitern, wer eine Seite liest. Er veröffentlicht; eine
Person entscheidet, wer sie sieht. Deshalb verlangt die Capability standardmäßig
keine Genehmigung: Eine erste Veröffentlichung ist privat. Ein Autor, der möchte,
dass eine Person jede erneute Veröffentlichung einer bereits geteilten Seite
genehmigt, setzt im Spec `tool_approval` auf `publish_artifact`.

### Der öffentliche Link { #the-public-link }

Ein öffentlicher Link ist `/a/<key>` unter der eigenen Adresse der Konsole, mit
einem zufälligen 192-Bit-Schlüssel — derselben Regel, der auch der Schlüssel der
gehosteten Chat-Seite folgt. Er sagt nichts darüber, wer sie veröffentlicht hat
oder zu welcher Organisation sie gehört.

**Replace the link** stellt einen neuen Schlüssel aus, und der alte öffnet sofort
nichts mehr. **Turn off** entfernt ihn. Beides wird im Audit-Trail festgehalten.
Eine Seite, die jemand bereits geöffnet hat, wird weiter angezeigt, bis ihre
signierte Inhaltsadresse abläuft, höchstens `ARTIFACT_VIEW_TTL_SECONDS`
(standardmäßig fünf Minuten).

Einem entzogenen Mitglied geht es genauso: Es verliert das Artefakt bei seiner
nächsten Anfrage, und eine Seite, die es bereits geöffnet hatte, bleibt
höchstens für dasselbe Zeitfenster.

Unter dem Link hält **Share** seine Einstellungen. Sie bleiben, wenn der Link
ersetzt wird, und ein aus- und wieder eingeschalteter Link behält sie:

| Einstellung | Was sie tut |
|---|---|
| **Stops opening after** | Ein Datum, nach dem der Link nichts mehr öffnet, als wäre er aus |
| **Shows** | Die neueste Version oder eine aufbewahrte Version, angeheftet, damit eine neue Veröffentlichung nicht ändert, was Personen mit dem Link schon gesehen haben. Eine angeheftete Version wird nie entfernt |
| **Password** | Abgefragt, bevor die Seite öffnet. Der Link sagt nichts — weder den Titel noch wann sie veröffentlicht wurde —, bis es stimmt. Als Hash gespeichert, nie wieder angezeigt; jeder Versuch zählt gegen das Rate-Limit des Links |
| **Sites that may embed it** | Siehe unten |

Die Karte sagt auch, wie oft der Link geöffnet wurde und wann zuletzt. Sie zählt
Öffnungen, keine Personen: Über Besucher wird nichts gespeichert. Jede Änderung
der Einstellungen wird auditiert, mit den Namen der geänderten Einstellungen und
nie mit einem Passwort.

### Auf einer anderen Website einbetten { #embedding-it-on-another-site }

Eine öffentliche Seite lässt sich mit einem `<iframe>` auf einer Intranetseite, in
einem Wiki oder auf der Website eines Kunden platzieren. Führen Sie die Websites
unter **Sites that may embed it** auf — nur Schema und Host,
`https://intranet.example.com`, oder `https://*.example.com` für die Subdomains
einer Website — und kopieren Sie den **Embed code**, den Share dann zeigt.

Der Code bettet `/api/v1/artifact-embed/<key>` vom Inhalts-Origin ein: ein kleines
Dokument dieses Deployments, das die Seite seinerseits in derselben Sandbox wie
überall sonst einbettet. Seine Policy lässt nur die aufgeführten Websites es
einbetten, und die Policy der Seite selbst lässt nur dieses Dokument und die
Konsole die Seite einbetten. Ist keine Website aufgeführt, kann es niemand. Eine
Seite hinter einem Passwort kann nicht eingebettet werden — die Einbettung sagt
dann, sie auf ihrer eigenen Seite zu öffnen —, und niemand meldet sich in einem
Frame auf einer fremden Website an.

## Wie die Seite isoliert wird { #how-the-page-is-isolated }

Ein Artefakt ist HTML mit Skript darin, geschrieben von einem Modell, das
möglicherweise etwas Feindseliges gelesen hat. Es wird so ausgeliefert, dass
nichts, was es tut, die Konsole oder die Person erreichen kann, die es ansieht:

- Die Bytes kommen von einer separaten Route,
  `/api/v1/artifact-content/<token>`, die kein Cookie und keine Session liest.
  Das Token ist signiert, nennt eine Version und läuft nach Minuten ab. Es wird
  erst ausgestellt, nachdem ein Grant oder ein öffentlicher Link den Aufrufer
  zugelassen hat.
- Jede Inhaltsantwort trägt `Content-Security-Policy: sandbox
  allow-scripts allow-modals`, ohne `allow-same-origin`. Die Seite läuft in
  einem opaken Origin, kann also weder die Cookies, den Speicher noch die Seite
  der Konsole lesen, und eine Anfrage, die sie stellt, würde nichts vom
  Betrachter mitführen. Das gilt selbst dann, wenn jemand die Inhaltsadresse für
  sich allein öffnet.
- Dieselbe Policy setzt `default-src 'none'` und `connect-src 'none'`. Die einzige
  entfernte Quelle, die sie nennt, ist der eigene Pfad des Bibliothekssatzes auf
  dem Inhalts-Origin, für Skripte, Stile und Schriften. `frame-ancestors` nennt nur
  die Konsole — und für eine Seite mit öffentlichem Link und Einbettungs-Websites
  das Einbettungsdokument und diese Websites. Der Frame in der Konsole trägt
  dieselbe `sandbox`-Liste als zweites Schloss.
- `allow-popups` fehlt. `connect-src` regelt keine Navigation, ein Link, der ein
  neues Fenster öffnet, wäre also ein Weg, das, was die Seite zeigt, an eine
  Adresse ihrer Wahl zu schicken. Stattdessen bekommt jede ausgelieferte Seite
  zuerst ein kurzes Plattform-Skript: Ein Klick auf einen Link zu einer anderen
  Website wird zu einer Nachricht an das Elternfenster des Frames. Die Konsole
  und die öffentliche Seite zeigen die vollständige Adresse und öffnen sie nur
  dann in einem neuen Tab, wenn die Person zustimmt; das Einbettungsdokument tut
  dasselbe in einer Leiste unter der Seite. Die Seite könnte diese Nachricht
  selbst senden, sie ist also eine Bitte und nie eine Erlaubnis — die Person, die
  die Adresse liest, steht zwischen einer per Prompt Injection manipulierten
  Seite und der Adresse, an die sie ihre Zahlen schicken würde.
- Eine signierte Adresse lädt ihre Seite höchstens einige Male pro Minute,
  gezählt pro Adresse, bevor irgendetwas gelesen wird. Die Konsole und die
  öffentliche Seite stellen jedes Mal eine frische Adresse aus, wenn sie den
  Frame zeichnen, und das Ausstellen über einen öffentlichen Link ist selbst pro
  Link begrenzt.

Die Liste **Artifacts** zeichnet die aktuelle Seite jeder Karte als
Live-Vorschau, durch dieselbe Art von Frame, mit Skript und sonst nichts: keine
Dialoge, keine Popups, keine Formulare. Mit Skript, damit ein Dashboard, dessen
Diagramme eine Bibliothek zeichnet, auf seiner Karte keine leere Fläche ist. Die
Vorschau ist inert — keine Zeigerereignisse, nicht in der Tab-Reihenfolge, vor
assistiven Technologien verborgen — und existiert nur, solange ihre Karte in der
Nähe des Sichtbereichs ist, sodass eine lange Liste nur die wenigen ausführt, die
jemand sieht, und eine weggescrollte Seite anhält.

Darüber hinaus kann ein Deployment Inhalte von einer **separaten registrierbaren
Domain** ausliefern, indem es `ARTIFACT_ORIGIN` setzt — zum Beispiel
`https://agenticos-content.example.net`, auf dieselbe API geroutet. Die Seite
liegt dann auf einer ganz anderen Site. Der opake Origin isoliert sie bereits,
das ist also eine Härtung, die ein Security-Review verlangen kann, keine
Voraussetzung. Setzen Sie die Variable für das Backend und für das Frontend, das
diesen Origin zu seinem `frame-src` hinzufügt. Siehe
[Konfiguration](configuration.md#published-artifacts).

## Einer Seite folgen { #following-a-page }

**Folgen** in der Leiste einer Seite legt jedes Mal eine Benachrichtigung in
Ihren Posteingang, wenn die Seite eine neue Version erhält - ein Agent hat sie
mit anderem Inhalt neu veröffentlicht, oder jemand hat eine ältere Version
wiederhergestellt. Eine Neuveröffentlichung, die nichts ändert, benachrichtigt
niemanden, sodass ein Zeitplan, der nichts Neues gefunden hat, still bleibt. Wer
die Version mit seinem Run oder seiner Wiederherstellung erzeugt hat, wird über
die eigene Änderung nicht benachrichtigt.

Folgen gewährt keinen Zugriff. Jeder, der die Seite öffnen kann, kann ihr
folgen, und wer den Zugriff verliert, erhält keine Benachrichtigungen mehr, ohne
entfolgen zu müssen. Der Posteingang prüft den Zugriff beim Lesen erneut, sodass
eine Benachrichtigung über eine Seite, die Sie nicht mehr öffnen dürfen, mit
diesem Zugriff verschwindet. Die Benachrichtigung kann auch per E-Mail kommen;
jeden Kanal schalten Sie unter **Einstellungen → Benachrichtigungen → Artefakt
aktualisiert** ab.

## Aufbewahrung und Löschung { #retention-and-deletion }

Artefakte sind eine eigene [Aufbewahrungsklasse](governance.md#the-classes),
gemessen ab der **letzten Veröffentlichung** — ein Bericht, der jede Woche neu
veröffentlicht wird, lebt, wie alt seine erste Version auch ist. Wie jede Klasse
behält sie Artefakte für immer, bis eine Organisation oder das Deployment eine
Frist setzt.

Ein Artefakt zu löschen — von Hand oder durch die Aufbewahrung — entfernt jede
Version, ihre gespeicherten Bytes, ihre Grants und ihren öffentlichen Link. Den
Agent zu löschen, löscht seine Artefakte nicht: Sie bleiben lesbar und haben
einfach keinen Herausgeber mehr. Eine benannte Umgebung zu löschen, tut dasselbe
mit den Seiten, die aus ihr veröffentlicht wurden, sodass sie nie auf der
gleichnamigen Seite der Standardumgebung landen. Die Organisation zu löschen,
entfernt sie. Die Artefakte einer gelöschten Person bleiben und verlieren ihren
Besitzer, so wie ihre Agents und Skills.

Die Bytes liegen im [Dateispeicher](configuration.md#uploaded-files-at-rest) des
Deployments, unter `artifacts/<organization>/<artifact>/`.

## Einschränkungen { #limitations }

- **Ein in sich geschlossenes Dokument pro Version.** Keine Bündel und kein
  Netzwerk aus der Seite heraus außer dem ausgelieferten Bibliothekssatz.
- **Keine Live-Daten.** Ein Dashboard zeigt die Daten, mit denen es
  veröffentlicht wurde. Es aktualisiert sich, wenn der Agent erneut
  veröffentlicht — ein Zeitplan ist der übliche Weg.
- **Nichts auf der Seite handelt.** Ein Formular oder ein Knopf hat keinen Ort,
  an den es senden könnte, was es sammelt.
- **Eine offene Seite überdauert einen Entzug um eine Lebensdauer der signierten
  Adresse**, standardmäßig fünf Minuten.
- **Ein Link in einer Seite fragt zuerst.** Er öffnet sich in einem neuen Tab,
  nachdem eine Person zugestimmt hat; die Seite selbst kann kein Fenster öffnen
  und die Konsole nicht navigieren.
- **Eine Einbettung braucht den öffentlichen Link und kein Passwort.** Mitglieder
  können sich nicht im Frame einer fremden Website anmelden.
- **Entfernte Versionen sind weg.** Eine Unterhaltung, die auf eine Version
  verlinkt, die älter als das aufbewahrte Fenster ist, kann nur die neueste
  anbieten.

## Zusammenfassung { #recap }

- Eine Capability, zwei Tools: `publish_artifact`, aus einer Workspace-Datei,
  inline oder als Änderungen, und `read_artifact`, um eine Seite zurückzulesen.
- Der Agent, die Umgebung und der Name sind die Identität; erneutes
  Veröffentlichen behält den Link und fügt eine Version hinzu, und jede
  aufbewahrte Version lässt sich wiederherstellen.
- Standardmäßig privat; geteilt mit Grants, der Organisation oder einem
  öffentlichen Link, durch eine Person. Der öffentliche Link kann ablaufen, eine
  Version anheften, nach einem Passwort fragen und auf aufgeführten Websites
  eingebettet werden.
- Ausgeliefert von einer Route ohne Cookies in einem opaken Origin ohne Netzwerk
  außer dem eigenen Bibliothekssatz des Deployments, mit Links, die vor dem
  Öffnen fragen, und optional von einer eigenen Domain.
- Eine eigene Aufbewahrungsklasse, gemessen ab der letzten Veröffentlichung.
