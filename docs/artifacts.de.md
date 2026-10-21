---
source_sha: "3394e53d70df"
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

Schalten Sie für den Agent die Capability **Artifacts** ein. Sie fügt vier Tools
hinzu: `publish_artifact`, das das Modell aufruft, wenn das Ergebnis etwas ist,
das eine Person öffnen sollte, statt es einmal im Chat zu lesen; `read_artifact`,
das eine veröffentlichte Seite zurückliest; `list_artifacts`, das die Seiten
nennt, die ein Run öffnen darf; und `preview_artifact`, das eine Seite zeichnet
und sagt, was darin schiefgegangen ist.

Die Seite kommt von einer von drei Stellen:

- **Eine Datei im Workspace des Agents**, die auf `.html` oder `.md` endet. Das
  ist der übliche Fall für einen Agent mit der Capability
  [Dateien & Shell](reference/capabilities.md#files-shell): Er schreibt
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

### Eine Seite wiederfinden { #finding-a-page-again }

Jede Nachricht ist ein neuer Run, und ein Run sieht die früheren Runden nur als
Text, deshalb behält das Modell die Namen nicht, unter denen es veröffentlicht
hat. `list_artifacts` führt die Seiten des Agents in der Umgebung des Runs auf,
die neueste zuerst und höchstens 50: jede mit Namen, Titel, aktueller Version,
Format, Live-Bindings, Sichtbarkeit, ob ein öffentlicher Link eingeschaltet ist,
wann sie veröffentlicht wurde, ihrem Link in die Konsole und `may_edit` - ob eine
Veröffentlichung unter diesem Namen aus diesem Run die Seite aktualisiert, statt
abgelehnt zu werden. Das Modell prüft die Liste, bevor es einen neuen Namen wählt.

Die Liste wird als die Person gelesen, für die der Run handelt, nach der Regel
der Konsole: ihre eigenen Seiten, die der Organisation und die mit ihr geteilten,
oder jede Seite für eine Rolle, die jede Seite sieht. In einem Gruppenchat sieht
der Kanal nur Seiten der ganzen Organisation: nie die privaten Seiten oder die
Team-Seiten der sprechenden Person und auch keine Seite, die nur mit ihr geteilt
ist. Eine Oberfläche, an der niemand angemeldet ist, etwa ein öffentliches
Widget, listet nichts auf.

## Live-Daten { #live-data }

Eine Seite kann Datensätze aus [Virtual Tables](virtual-tables.md) zeigen, die
aktuell bleiben, statt der Kopie, mit der sie veröffentlicht wurde. Der Agent
übergibt `publish_artifact` dafür `bindings`: Jedes Binding besteht aus einem
Namen, einer [gespeicherten Ansicht](virtual-tables.md#saved-views) und den
Spalten, die die Seite daraus liest. `list_views` liefert dem Agent die ID und die
Spalten jeder Ansicht. Die Seite ruft `agenticos.onData(render)` auf, und
`render(data)` läuft mit den ersten Daten und erneut bei jeder Aktualisierung.
`agenticos.data` ist ein Promise auf die ersten Daten.

```js
agenticos.onData((data) => {
  // data.tickets = { status, records, fields, count, truncated, limit, filters_dropped }
});
```

Jedes Binding kommt als `status` (`ok` oder `unavailable`), `records`
(`{id, <field>: value}`), `fields` (Label, Typ, Optionen und Zustand jedes Felds),
`count`, `truncated`, `limit` und `filters_dropped` an. `filters_dropped` ist true,
wenn ein Filter der Ansicht eine Spalte nennt, die es nicht mehr gibt; die
Datensätze treffen dann auf mehr zu, als die Ansicht gemeint hat.

Eine Seite, die
innerhalb von 10 Sekunden keine Antwort bekommt, sieht jedes Binding als `unavailable`; ein danach
hinzugefügter Listener fragt noch einmal.

Ein Binding ist `unavailable`, wenn
dieser Betrachter seine Ansicht nicht lesen darf oder die Ansicht nicht mehr
existiert. Ein Feld, dessen Spalte entfernt wurde, wird unter seinem Feldnamen als
`text`-Feld mit dem Wert `null` und dem Zustand `missing` ausgeliefert; eine
archivierte Spalte ergibt `null` mit dem Zustand `archived`.

Die Datensätze werden gelesen, **wenn jemand die Seite ansieht, mit dem eigenen
Zugriff dieses Betrachters**, und nie in der Seite gespeichert. Zwei Personen, die
dieselbe Seite öffnen, können unterschiedliche Zeilen sehen. Das Ergebnis der
Veröffentlichung führt jedes Feld als `Label (type)` auf, sodass der Agent prüfen
kann, ob er die gemeinte Spalte gebunden hat; ein unverändert übernommenes Binding
meldet `kept`.

Eine private Ansicht liefert nur an ihren Besitzer. Wird eine gebunden, wird die
Seite trotzdem veröffentlicht, und die `warning` des Ergebnisses bekommt eine
Zeile, dass nur diese Person ihre Datensätze sieht, bis die Ansicht geteilt ist;
das sagt der Agent ihr. Ob ein Kollege sie sehen wird, entscheidet sich dort, wo
die Seite geteilt wird: siehe
[Wer die Datensätze einer Live-Seite sieht](#who-sees-a-live-pages-records).

Version 3 des [Seiten-Kits](#the-library-set) zeichnet ein Binding für den Agent:
`AO.records("#tickets", data.tickets)` innerhalb von `agenticos.onData` stellt die
Datensätze als Tabelle dar, mit einem Kopf aus den Labels der Felder, Zahlen und
Datumswerten rechtsbündig, Auswahlwerten als Badges und jedem Wert als Text
geschrieben. Bevor die Daten da sind, zeigt es eine Ladezeile, und ein Binding,
das `unavailable` oder leer ist, eine gekürzte Liste und ein verworfener Filter
bekommen je eine eigene Meldung. `AO.onData` in Version 3 ist derselbe Aufruf wie
`agenticos.onData`. Eine gebundene Seite, deren Skript nie nach seinen Daten
fragt, wird trotzdem veröffentlicht, mit einer
[Warnung](#the-page-contract-and-the-publish-warnings).

Der Name eines Bindings besteht aus Kleinbuchstaben, Ziffern und `_`. Ein Feld darf
so heißen, wie seine Spalte beschriftet ist: Wörter aus Buchstaben in beliebiger
Schreibung, Ziffern und `_`, getrennt durch je ein Leerzeichen, etwa `Status` oder
`Created At`. Beide sind höchstens 64 Zeichen lang, und `__proto__`, `constructor`
und `prototype` sind für beide reserviert (für ein Feld außerdem `id`). Eine Seite
hat höchstens 5 Bindings, ein Binding höchstens 50 Felder.

### Was der Betrachter sieht { #what-the-viewer-sees }

Eine Seite mit Bindings trägt ein Badge **Live** auf ihrer Karte, im
Artefakt-Widget des Dashboards und in der Seitenanzeige. In der Seitenanzeige
pulsiert sein Punkt, während die Daten eintreffen, und wird bernsteinfarben, wenn
einige Quellen für diesen Betrachter nicht verfügbar sind. Ein Betrachter, der
keine davon lesen kann, sieht kein Badge, und auf einer älteren Version gibt es
ebenfalls keines.

Die Seitenanzeige hat **Refresh**, das die Daten erneut liest und eine Seite, die
`agenticos.onData` verwendet, an Ort und Stelle aktualisiert; der Tooltip der
Schaltfläche sagt, wann zuletzt gelesen wurde. Daneben liegt ein Menü für die
automatische Aktualisierung: aus, jede Minute, alle 5 oder 15 Minuten oder jede
Stunde.
Jeder Betrachter wählt selbst, und die Wahl wird pro Seite in diesem Browser
gespeichert.

Die automatische Aktualisierung tut nichts, solange der Tab verborgen ist, und
liest einmal, wenn der Tab zurückkommt und ein Takt verpasst wurde. Sie hört auf,
wenn die Daten abgelehnt werden (die Seite ist für diesen Betrachter nicht mehr
da) und wenn keine Quelle der Seite gelesen werden kann, bis der Betrachter auf
Refresh klickt und ein Lesen antwortet. Ein Fehler, der nichts über die Seite
aussagt, etwa ein Serverfehler, lässt sie weiter abfragen. Eine Antwort „busy“
(429) wird zweimal im Abstand von einer Sekunde wiederholt, bevor der Betrachter
„Busy, try again in a moment.“ liest.

Eine Zeile unter der Leiste erscheint nur, wenn etwas Aufmerksamkeit braucht. Eine
abgelehnte Seite sagt „This page's live data is not available to you.“ Ein Leser,
dessen Quellen nicht gelesen werden können, sieht, wie viele („2 of 3 sources
unavailable to you“). Wer die Seite bearbeiten darf, sieht außerdem für jede
Quelle den Grund (zum Beispiel gibt es ihre gespeicherte Ansicht nicht mehr, ihre
Tabelle ist archiviert, die Tabelle ist dem Agent nicht freigegeben, oder Sie
können ihre gespeicherte Ansicht nicht lesen), mit einem Link **Open the table**
zur gebundenen Ansicht.

Veröffentlicht ein Agent eine neue Version, während jemand die aktuelle offen hat,
wechselt die Seitenanzeige beim nächsten Lesen (einer manuellen oder automatischen
Aktualisierung) auf die neue Version: Die Seite wird aus der neuen Version neu
geladen, mit deren eigenen Daten. Wer im Versionsmenü eine Version gewählt hat,
bleibt bei ihr.

Auf einer älteren Version werden keine Live-Daten gelesen. Die Seitenanzeige sagt
„Live data only on the current version.“ mit **Open current** und, für jemanden,
der die Seite bearbeiten darf, **Restore** für diese Version. Wer eine Version
wiederherstellt, deren Live-Quellen nicht verfügbar sind, erfährt, welche.

### Grenzen { #limits }

Jede Antwort ist begrenzt, damit eine einzelne Seite nicht das Deployment
lahmlegen kann:

| Grenze | Wert |
|---|---|
| Bindings pro Seite | 5 |
| Datensätze pro Binding | 1.000 |
| Aufbereitete Daten pro Seite | 4 MiB, gerecht auf die Bindings verteilt |
| Eine Abfrage | höchstens 2 s |
| Eine Seite | Frist von 5 s |
| Datenladevorgänge | 30 pro Minute je Betrachter, einer gleichzeitig je Betrachter und eine Obergrenze pro Prozess |

Ein gekürztes Binding meldet `truncated: true`, mit `limit` auf `records` oder
`bytes` und `count` als Zahl der ausgelieferten Datensätze. `bytes` deckt auch ein
Lesen ab, dessen gemessene Kosten aufgebraucht waren, bevor die aufbereiteten Daten
den Anteil der Seite gefüllt hatten.

Die Frist wird durchgesetzt, ohne eine Abfrage abzubrechen: Jede Abfrage läuft
höchstens so lange wie das Kleinere aus 2 s und der Restzeit der 5 s, und sind die
5 s verbraucht, beginnt keine Abfrage mehr, sodass eine Seite in etwa 5 s
antwortet. Jenseits eines Rate-Limits antwortet die Route mit 429; die Konsole
wiederholt eine Antwort „busy“ zweimal. Ist Redis ausgefallen, zählen die
Untergrenze des Rate-Limits und das Limit gleichzeitiger Ladevorgänge pro
API-Worker, und die Obergrenze pro Prozess begrenzt weiterhin jeden Worker.

### Wer eine gebundene Seite veröffentlichen darf { #who-may-publish-a-bound-page }

Eine Seite bindet sich nur dann an eine Tabelle, wenn der Spec des
veröffentlichenden Agents Lesezugriff auf sie freigibt, geprüft beim
Veröffentlichen der Seite oder beim Wiederherstellen einer Version. Wird die
Freigabe später entzogen, hält das bereits veröffentlichte Seiten nicht an, und
jeder Betrachter liest weiterhin nur, was sein eigener Zugriff erlaubt.

Eine gebundene Seite kann nur ein Run erneut veröffentlichen, der für ein Mitglied
handelt: das angemeldete Mitglied (Web-Chat, HTTP-API), ein verknüpfter Absender
in einem Kanal oder der Ersteller eines Zeitplans. Der Besucher eines Widgets,
eines Embeds oder einer gehosteten Seite, ein nicht verknüpfter Absender in einem
Kanal und die Zustellung eines Ereignis-Triggers eines Agents (GitHub, E-Mail,
Webhook-Relay) zählen nicht, ebenso wenig ein Workflow-Run, den ein öffentlicher
Eingang zugelassen hat, oder irgendein Run in der Kette eines solchen Runs.

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
Nichts Neues wird gespeichert. Es wird im Audit-Trail festgehalten. Die neue
Version sagt, woher sie stammt: Die Versionsliste zeigt sie als
`v4 · restored from v2`, und die API liefert ihre Nummer in `restored_from`, das
bei einer Veröffentlichung leer bleibt.

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
    schlagen alle fehl. Die Ausnahmen sind der Bibliothekssatz unten, den das
    Deployment selbst ausliefert, und die [Live-Daten](#live-data), die die Konsole
    einer Seite mit deklarierten Bindings übergibt. Das Tool sagt das dem Modell.
    Es ist Absicht, und [Wie die Seite isoliert wird](#how-the-page-is-isolated)
    sagt, warum.

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
| `lib/agenticos-3.css` | Das Seiten-Kit: das Aussehen der Konsole für Seiten, hell und dunkel, und die `ao-`-Komponenten, aus denen eine Seite gebaut wird |
| `lib/agenticos-3.js` | `window.AO`: Chart.js im Stil der Konsole, Zahlenformate in der Sprache der Seite, Icons, Tabs, `AO.onData` und `AO.records` |
| `lib/agenticos-2.css`, `lib/agenticos-2.js` | Die vorige Version des Kits, behalten für die Seiten, die gegen sie veröffentlicht wurden |
| `lib/agenticos-1.css` | Die erste Version des Aussehens, behalten für die Seiten, die gegen sie veröffentlicht wurden |

Jeder Name trägt seine Version und wird ein Jahr lang gecacht. Ein Upgrade fügt
eine neue Datei neben der alten hinzu, sodass eine Seite, die gegen eine Version
veröffentlicht wurde, weiter genau diese bekommt, und eine ausgelieferte Datei
wird nie geändert. Nichts wird von außerhalb des Deployments geholt, also
funktioniert ein Deployment ohne Internetzugang genauso. Die Dateien sind in
`backend/app/core/catalog/artifact_lib/` aufgeführt.

Version 3 behält jede Klasse und jeden Aufruf von Version 2. Sie verzeiht außerdem
Markup, das ein Modell nachlässig schreibt: Titel, Untertitel und Metazeile, die
direkt in den Header gesetzt sind, stehen untereinander, statt sich über ihn zu
verteilen, eine Tabelle ohne `<thead>` bekommt trotzdem ihre Kopfzeile, und eine
Meldung, die in den Wrapper einer Tabelle geschrieben ist, bekommt Abstand. Neu
sind Lade- und Hinweiszeilen, eine Beschriftungszeile, ein Live-Punkt, Listen,
eine Werkzeugleiste mit Eingabefeldern sowie Icon und Aktionen im Header. Icons,
die ein Skript nach dem Laden der Seite hinzufügt, wie es die Datensätze einer
Live-Seite tun, werden ebenfalls gezeichnet.

Der mitgelieferte [Skill](skills.md) **`artifact-pages`** bringt einem Agent bei,
sie zu nutzen: das verbindliche Grundgerüst, jede Klasse des Kits, drei Vorlagen
(ein Dashboard, ein Bericht und eine mit `AO.records` gezeichnete Live-Tabelle),
den Hausstil, Icons statt Emoji und wie man eine Seite mit `read_artifact` ändert.
Eine neue Organisation bekommt ihn mit den anderen mitgelieferten Skills, eine
bestehende über `seed-skills`, und der Tab **Page style** der Capability
Artifacts im Builder bietet ihn an. Bearbeiten Sie den Skill, um Ihre eigene
Marke zu beschreiben, und der Agent folgt ihr.

### Der Seitenvertrag und die Warnungen beim Veröffentlichen { #the-page-contract-and-the-publish-warnings }

Der Agent kann die Seite, die er veröffentlicht, nicht sehen, deshalb sagt ihm
die Plattform, wie eine Seite aussehen muss und was an der gesendeten falsch
aussieht.

Die Capability Artifacts gibt jedem Agent, der sie hat, einen kurzen
**Seitenvertrag** in seine Anweisungen, ob der Skill gebunden ist oder nicht: das
Grundgerüst (Doctype, Viewport, `lang`, Stylesheet und Skript des Kits in dieser
Reihenfolge, `main.ao-page` und der Header), eine abgeschlossene Liste der
meistgenutzten Klassen des Kits, Lucide-Icons statt Emoji und `AO.records` für
gebundene Daten.

Bietet der Run des Agents den Skill `artifact-pages` an und hat ihn nicht
geladen, wird seine erste vollständige HTML-Seite einmal zurückgeschickt, mit der
Bitte, den Skill zu laden und die Seite neu zu bauen. Das geschieht einmal pro
Run; jede neue Nachricht ist ein neuer Run, es kann also in einer späteren Runde
wieder geschehen. Eine Änderung wird nie zurückgeschickt.

Eine veröffentlichte HTML-Seite wird danach geprüft, und das Ergebnis trägt eine
`warning` mit einer Zeile für jedes gefundene Problem. Die Seite wird so oder so
veröffentlicht. Die Prüfungen:

- kein `<!doctype html>` in der ersten Zeile oder kein Viewport-Meta-Tag;
- eine `ao-`-Klasse, im Markup oder in einem Skript genannt, die weder die von
  der Seite geladene Version des Kits noch ihr eigenes `<style>` definiert;
- eine Tabelle ohne `<thead>` oder ohne die Klasse `ao-table`;
- `data-lucide`-Icons ohne `lib/lucide-1.46.0.min.js`;
- `AO.onData` oder `AO.records` auf einer Seite, die `lib/agenticos-3.js` nicht
  lädt;
- eine gebundene Seite, deren Skript nie `agenticos.onData` aufruft oder
  `agenticos.data` liest und die deshalb keine Datensätze zeigt.

### Die Seite sehen: Vorschau { #seeing-the-page-preview }

`preview_artifact` zeichnet die aktuelle Version einer Seite so, wie sie jemand
sähe, der sie öffnet, 1280 Pixel breit, und übergibt dem Modell ein Bild und einen
schriftlichen Bericht. Der Bericht nennt die Daten jedes Bindings (Datensätze,
gekürzt oder `unavailable` und warum), ob die Seite nach ihren Daten gefragt hat,
nicht abgefangene Fehler mit ihrer Zeile, Fehler und Warnungen der Konsole, was
die Sicherheitsrichtlinie der Seite abgelehnt hat, abgelehnte Anfragen, Dialoge
und die Warnungen beim Veröffentlichen von oben. Das Bild ist höchstens 2400 Pixel
hoch; eine längere Seite sagt, wie hoch sie ist. Eine Seite, die nach 15 Sekunden
noch läuft, wird als solche gemeldet, ohne Bild.

Die Daten werden als die Person gelesen, für die der Run handelt, genau so, wie
die Konsole sie für sie lesen würde. In einem Gruppenchat lässt sich nur eine
Seite der ganzen Organisation in der Vorschau zeigen, dieselben Seiten, die die
Liste dort zeigt, und sie wird ohne Daten gezeichnet. Eine Oberfläche, an der
niemand angemeldet ist, zeigt keine Vorschau. Nichts, was die Seite anfragt,
erreicht das Netzwerk: Die API beantwortet jede Anfrage mit der Seite, dem
[Bibliothekssatz](#the-library-set) oder einer Ablehnung.

Das Bild braucht einen Browser, den der Betreiber bereitstellt, benannt durch
[`ARTIFACT_RENDER_CDP_URL`](configuration.md#published-artifacts), und das Extra
`browser` des Backends. Diese Einstellung gehört allein dem Betreiber: Sie ist
getrennt von den Hosts, die ein browsender Agent steuern darf, und kein Agent kann
einen Browser auf sie richten. Fehlt eines davon, liefert das Tool trotzdem den
Bericht, ohne das Bild, und sagt, dass das Deployment keinen Renderer hat.
Schalten Sie **Preview screenshot** in den Einstellungen der Capability für ein
Modell aus, das keine Bilder lesen kann; der Bericht kommt weiterhin zurück.
`agenticos cmd doctor` sagt, ob der Renderer antwortet.

## Wer es öffnen kann { #who-can-open-it }

Ein neues Artefakt ist **privat** für die Person, für die der veröffentlichende
Run gehandelt hat: die Person im Chat oder der Ersteller eines Triggers. Eine
private Seite sehen außerdem die Rollen Owner, Admin, Builder und Operator.

Sein Link - der, auf den die Karte im Chat und die Antwort des Agents zeigen -
öffnet die Seite selbst (von der Karte im Chat aus in einem neuen Tab),
fensterfüllend unter einer Leiste mit Titel, Version und **Share**. Der Link allein lässt niemanden hinein: Er öffnet sich nur für
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
keine Genehmigung: Eine erste Veröffentlichung ist privat, und was eine gebundene
Seite zeigt, entscheidet beim Ansehen der eigene Zugriff jedes Betrachters. Ein
Autor, der möchte, dass eine Person jede erneute Veröffentlichung einer bereits
geteilten Seite oder einer gebundenen Seite genehmigt, setzt im Spec
`tool_approval` auf `publish_artifact`. Eine gebundene Seite kann nur ein Run
erneut veröffentlichen, der für ein Mitglied handelt (siehe
[Live-Daten](#live-data)).

### Wer die Datensätze einer Live-Seite sieht { #who-sees-a-live-pages-records }

Wer eine [Live-Seite](#live-data) geteilt bekommt, kann sie öffnen, doch die
Datensätze jedes Bindings werden mit seinem eigenen Zugriff gelesen. Um sie zu
sehen, braucht er außerdem Lesezugriff auf die Tabelle des Bindings und eine
Ansicht, die geteilt ist oder ihm selbst gehört. Eine Seite, die an eine private
Ansicht gebunden ist, zeigt ihre Datensätze deshalb nur dem Besitzer der Ansicht;
das Ergebnis der Veröffentlichung sagt das dem Agent, damit er es weitergibt.

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
- Live-Daten kommen per `postMessage` von der Konsole, die sie als der Betrachter
  abruft. Die Content-Route transportiert nie Datensätze. Die Anfrage der Seite
  trägt eine Nonce, mit der die Konsole jede Antwort dem richtigen Laden der Seite
  zuordnet; das ist **Korrelation, keine Zugriffskontrolle**. Den Zugriff regelt
  die eigene Session des Betrachters auf der Daten-Route, sodass eine Seite immer
  nur bekommt, was der Betrachter lesen darf.
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
die Content-Route dieses Origins zu seinem `frame-src` hinzufügt. Siehe
[Konfiguration](configuration.md#published-artifacts).

## Eine Seite archivieren { #archiving-a-page }

Archivieren nimmt eine Seite allen weg, ohne sie zu verlieren. Wer die Seite
bearbeiten darf, wählt **Archive** im Menü **More actions** über ihr, und ein
Dialog sagt, was das bewirkt, bevor sich etwas ändert. Die Seite, ihre Versionen,
ihre Grants und ihr Name bleiben erhalten. Nichts liefert sie aus, bis sie
wiederhergestellt wird, von derselben Seite aus. Archivieren wird als
`artifact.archived` auditiert, Wiederherstellen als `artifact.unarchived`.

Solange eine Seite archiviert ist, antwortet jeder Weg, der sie zeigen würde, als
gäbe es sie nicht:

- **Die Konsole.** Ihre Ansicht und ihre Live-Daten werden abgelehnt, ebenso eine
  signierte Adresse, die vor dem Archivieren ausgestellt wurde. Ein Leser, der
  ihren Link öffnet, erfährt, dass sie nicht verfügbar ist. Wer sie bearbeiten
  darf, sieht, wann sie archiviert wurde, mit **Restore** und **Delete**.
- **Listen.** Die Liste Artifacts und das Dashboard-Widget lassen sie weg. Wählen
  Sie in der Liste **Archived included**, um sie zu sehen, markiert als
  **Archived**.
- **Der öffentliche Link und die Einbettung.** Beide öffnen nichts.
- **Der Agent.** `publish_artifact` lehnt den Namen mit einer Meldung ab, die das
  Archiv nennt, sodass ein Run keine zweite Seite unter ihm anlegen kann.
  `read_artifact`, `preview_artifact` und `list_artifacts` behandeln die Seite
  als nicht vorhanden. Ein Run, der die Seite nicht bearbeiten darf, erfährt nur,
  dass der Name nicht seiner ist.

Archivieren schaltet den öffentlichen Link aus, auditiert als
`artifact.public_link_disabled`, und Wiederherstellen schaltet ihn nicht wieder
ein. Eine vor dem Archivieren verschickte Adresse bleibt tot, bis jemand unter
**Share** eine neue erstellt. Ablaufdatum, angeheftete Version, Passwort und
Einbettungs-Websites des Links bleiben dafür erhalten.

Über die API archiviert `POST /api/v1/artifacts/{id}/archive` eine Seite, und ein
erneutes Archivieren ändert nichts. `POST /api/v1/artifacts/{id}/unarchive` stellt
sie wieder her und antwortet bei einer nicht archivierten Seite mit `400`. Beide
verlangen das Recht, diese Seite zu bearbeiten, ein Grant eingeschlossen.
`GET /api/v1/artifacts` listet archivierte Seiten nur mit
`include_archived=true`, und `archived_at` an jeder Seite sagt, wann sie
archiviert wurde.

## Aufbewahrung und Löschung { #retention-and-deletion }

Artefakte sind eine eigene [Aufbewahrungsklasse](governance.md#the-classes),
gemessen ab der **letzten Veröffentlichung** — ein Bericht, der jede Woche neu
veröffentlicht wird, lebt, wie alt seine erste Version auch ist. Wie jede Klasse
behält sie Artefakte für immer, bis eine Organisation oder das Deployment eine
Frist setzt.

Ein Artefakt zu löschen — von Hand oder durch die Aufbewahrung — entfernt jede
Version, ihre gespeicherten Bytes, ihre Grants und ihren öffentlichen Link. Eine
archivierte Seite altert und wird gelöscht wie jede andere. Den Agent zu löschen, löscht seine Artefakte nicht: Sie bleiben lesbar und haben
einfach keinen Herausgeber mehr. Eine benannte Umgebung zu löschen, tut dasselbe
mit den Seiten, die aus ihr veröffentlicht wurden, sodass sie nie auf der
gleichnamigen Seite der Standardumgebung landen. Die Organisation zu löschen,
entfernt sie. Die Artefakte einer gelöschten Person bleiben und verlieren ihren
Besitzer, so wie ihre Agents und Skills.

Die Bytes liegen im [Dateispeicher](configuration.md#uploaded-files-at-rest) des
Deployments, unter `artifacts/<organization>/<artifact>/`.

## Einschränkungen { #limitations }

- **Ein in sich geschlossenes Dokument pro Version.** Keine Bündel und kein
  Netzwerk aus der Seite heraus außer dem ausgelieferten Bibliothekssatz und den
  [Live-Daten](#live-data), die die Konsole ihr übergibt.
- **Live-Daten sind begrenzt.** Fünf Bindings, je 1.000 Datensätze und etwa 5 s
  pro Ladevorgang; siehe die [Grenzen](#limits). Nicht gebundene Daten sind die
  Seite, wie sie veröffentlicht wurde, und ändern sich, wenn der Agent erneut
  veröffentlicht.
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
- **Ohne Renderer sieht der Agent seine Seite nicht.** Die Warnungen beim
  Veröffentlichen lesen das Markup und können nicht sagen, wie es aussieht. Mit
  einem Renderer stammt das Bild von einem Headless-Chromium: Schriften und
  Größen können leicht vom Browser eines Lesers abweichen.

## Zusammenfassung { #recap }

- Eine Capability, vier Tools: `publish_artifact`, aus einer Workspace-Datei,
  inline oder als Änderungen; `read_artifact`, um eine Seite zurückzulesen;
  `list_artifacts`, um eine zu finden; und `preview_artifact`, um sie gezeichnet
  zu sehen, mit ihren Fehlern.
- Der Agent, die Umgebung und der Name sind die Identität; erneutes
  Veröffentlichen behält den Link und fügt eine Version hinzu, und jede
  aufbewahrte Version lässt sich wiederherstellen.
- Standardmäßig privat; geteilt mit Grants, der Organisation oder einem
  öffentlichen Link, durch eine Person. Der öffentliche Link kann ablaufen, eine
  Version anheften, nach einem Passwort fragen und auf aufgeführten Websites
  eingebettet werden.
- Eine Seite kann sich an gespeicherte Tabellenansichten binden und Live-Daten
  zeigen, gelesen beim Ansehen mit dem eigenen Zugriff des Betrachters und nie in
  der Seite gespeichert.
- Ein kurzer Seitenvertrag in den Anweisungen jedes Agents mit Artifacts und
  Warnungen im Ergebnis der Veröffentlichung für das, was im Markup falsch
  aussieht.
- Ausgeliefert von einer Route ohne Cookies in einem opaken Origin ohne Netzwerk
  außer dem eigenen Bibliothekssatz des Deployments, mit Links, die vor dem
  Öffnen fragen, und optional von einer eigenen Domain.
- Archivieren behält eine Seite und liefert nichts von ihr aus, den öffentlichen
  Link ausgeschaltet, bis jemand, der sie bearbeiten darf, sie wiederherstellt.
- Eine eigene Aufbewahrungsklasse, gemessen ab der letzten Veröffentlichung.
