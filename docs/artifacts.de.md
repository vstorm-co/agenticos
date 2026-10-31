---
source_sha: "10cee0ec4f18"
---

# Apps { #artifacts }

Eine **App** ist eine Seite, die ein Agent veröffentlicht hat: ein Bericht,
ein kleines Dashboard, eine einseitige Zusammenfassung, die jemand im Browser
öffnet. Sie hat einen Link, der gleich bleibt, wenn der Agent sie erneut
veröffentlicht, sodass „veröffentliche jeden Montag die Zahlen der Woche auf
dieser Seite“ ein Link ist, den man sich als Lesezeichen speichert, statt jede
Woche einen neuen.

Eine App ist keine Datei. Ein Diagramm, ein erzeugtes PDF und eine Datei im
Workspace haben bereits ein Zuhause im Chat und im [Workspace](sandbox.md). Eine
App ist das, was *ausgeliefert* wird: Sie hat einen Besitzer, eine
Sichtbarkeit und Grants wie ein Agent oder ein Skill, und sie kann einen
öffentlichen Link für jemanden ohne Konto bekommen.

## App-Darstellung { #app-appearance }

Die angemeldete App-Ansicht und ihr öffentlicher Link haben unabhängige
Schaltflächen für **helle** und **dunkle** Darstellung. Apps starten mit einer
hellen Präferenz, unabhängig vom Konsolen- oder Systemdesign. Ein Wechsel
ändert nur die `prefers-color-scheme`-Präferenz der eingebetteten Seite: Die App
wird weder neu geladen noch werden HTML, CSS oder gespeicherte Versionen
umgeschrieben. Festgelegte Farben bleiben erhalten; Apps mit Unterstützung
beider Modi können auf die Auswahl reagieren.

Den Kontrast bestimmt weiterhin die Seite. In den mitgelieferten Stilen ist
`--ao-muted` eine Hintergrundfarbe; sekundärer Text verwendet `--ao-muted-fg`
oder die Klasse `.ao-muted`. Ein Hintergrundwert als Textfarbe kann in beiden
Modi unlesbar sein.

## Eine veröffentlichen { #publishing-one }

Schalten Sie für den Agent die Capability **Apps** ein. Sie fügt fünf Tools
hinzu: `publish_artifact`, das das Modell aufruft, wenn das Ergebnis etwas ist,
das eine Person öffnen sollte, statt es einmal im Chat zu lesen; `read_artifact`,
das eine veröffentlichte Seite zurückliest; `list_artifacts`, das die Seiten
nennt, die ein Run öffnen darf; `preview_artifact`, das eine Seite zeichnet
und sagt, was darin schiefgegangen ist; und `share_artifact`, das darum bittet,
eine Seite zu teilen.

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
Namen und einer **Seitenabfrage** (Page Query) - einer Tabelle, den Feldern, die
die Seite daraus liest, und optional Filtern, einer Sortierung und einem Limit.
Die Seite ruft `agenticos.onData(render)` auf, und `render(data)` läuft mit den
ersten Daten und erneut bei jeder Aktualisierung. `agenticos.data` ist ein
Promise auf die ersten Daten.

```js
agenticos.onData((data) => {
  // data.tickets = { status, records, fields, count, truncated, limit }
});
```

Jedes Binding kommt als `status` (`ok` oder `unavailable`), `records`
(`{id, <field>: value}`), `fields` (Label, Typ, Optionen und Zustand jedes Felds),
`count`, `truncated` und `limit` an. Eine Seite, die innerhalb von 10 Sekunden
keine Antwort bekommt, sieht jedes Binding als `unavailable`; ein danach
hinzugefügter Listener fragt noch einmal.

**Alle, die eine Live-Seite öffnen, lesen dieselben Datensätze**, gleich welchen
eigenen Zugriff sie auf die Tabellen haben. Die Abfrage wird mit dem Zugriff des
[Besitzers](#who-owns-a-page) der Seite gelesen, und erst dann, wenn der Besitzer
zugestimmt hat, sie zu teilen
([Einwilligung](#consent-the-owner-decides-who-reads-the-data)). Eine Seite ist
also für Daten gedacht, die jeder sehen darf, der sie öffnen kann. Die
Datensätze werden gelesen, wenn jemand die Seite ansieht, und nie in ihr
gespeichert.

### Was ein Binding einfriert { #what-a-binding-freezes }

Eine Seitenabfrage ist kein Link auf eine gespeicherte Ansicht. Der Agent nennt
eine `table` oder eine [gespeicherte Ansicht](virtual-tables.md#saved-views) per
ID oder exaktem Namen, und die Plattform **kopiert** die Filter und die
Sortierung der Ansicht beim Veröffentlichen in die Seite. Wird die Ansicht später
bearbeitet oder gelöscht, ändert das nichts an der Seite.

| Im Binding | Bedeutung |
|---|---|
| `table` oder `view` | Die zu lesende Tabelle oder eine Ansicht, deren Filter und Sortierung kopiert werden. Nicht beides |
| `fields` | Jeder Name, den die Seite liest, einer Spalte per ID oder Label zugeordnet |
| `filters` | `{column, op, value}`, alle müssen zutreffen; zu den Filtern der Ansicht hinzugefügt |
| `sort` | `{by, direction}`; ersetzt die Sortierung der Ansicht |
| `limit` | Höchstens 1.000, zugleich der Standardwert; ersetzt das der Ansicht |

`visible_columns` und `group_by` einer Ansicht werden ignoriert: Die `fields` des
Bindings bestimmen die Spalten. Ein Filter darf eine Spalte nennen, die die Seite
nicht liest, und der Besitzer erfährt, welche. Eine Seitenabfrage hat keine
Freitextsuche, deshalb **lässt sich eine Ansicht mit Suche nicht binden**; das
Veröffentlichen wird abgelehnt und nennt sie. Eine Ansicht, deren Filter eine
nicht mehr vorhandene Spalte nennt, wird genauso abgelehnt.

Formeln, Lookups, Rollups und Link-Labels sind erlaubt. Sie lesen mehr als die
Spalte, die die Seite nennt, daher hält die Abfrage alles fest, was sie erreicht:
die Eingabespalten einer Formel, den Link und das Ziel eines Lookups oder
Rollups, jede verknüpfte Tabelle und die Spalte, nach der jede verknüpfte
Tabelle ihre Datensätze beschriftet. Der Spec des Agents muss Lesezugriff auf die
Tabelle freigeben, und die Person hinter dem Run muss jede Tabelle lesen können,
die die Abfrage erreicht, denn niemand kann binden, was er nicht lesen darf.

Das Ergebnis der Veröffentlichung beschreibt jede Abfrage in Worten - ihre
Tabelle, Filter, Reihenfolge, Limit und jedes Feld mit dem, was es liest
(`Status (single_select)`, `Pay band: formula over Salary, Level`). Es ist der
Text, dem der Besitzer zustimmt, deshalb prüft der Agent, dass er das Gemeinte
wiedergibt. Ein unverändert übernommenes Binding meldet `kept`.

Der Name eines Bindings besteht aus Kleinbuchstaben, Ziffern und `_`. Ein Feld darf
so heißen, wie seine Spalte beschriftet ist: Wörter aus Buchstaben in beliebiger
Schreibung, Ziffern und `_`, getrennt durch je ein Leerzeichen, etwa `Status` oder
`Created At`. Beide sind höchstens 64 Zeichen lang, und `__proto__`, `constructor`
und `prototype` sind für beide reserviert (für ein Feld außerdem `id`). Eine Seite
hat höchstens 5 Bindings, ein Binding höchstens 50 Felder.

Version 3 des [Seiten-Kits](#the-library-set) zeichnet ein Binding für den Agent:
`AO.records("#tickets", data.tickets)` innerhalb von `agenticos.onData` stellt die
Datensätze als Tabelle dar, mit einem Kopf aus den Labels der Felder, Zahlen und
Datumswerten rechtsbündig, Auswahlwerten als Badges und jedem Wert als Text
geschrieben. Bevor die Daten da sind, zeigt es eine Ladezeile, und ein Binding,
das `unavailable` oder leer ist, und eine gekürzte Liste bekommen je eine eigene
Meldung. `AO.onData` in Version 3 ist derselbe Aufruf wie `agenticos.onData`. Eine
gebundene Seite, deren Skript nie nach seinen Daten fragt, wird trotzdem
veröffentlicht, mit einer
[Warnung](#the-page-contract-and-the-publish-warnings).

### Der Workflow-Log als Live-Daten { #a-workflows-log }

Ein Binding kann auch den Log eines [Workflows](workflows.md) lesen - die Zeilen, die die
Quick Logs seiner Schritte geschrieben haben -, um ein Dashboard auf einer Seite zu bauen,
die aktuell bleibt. Gib dem Binding `"kind": "workflow_log"` (ein Binding ohne `kind` liest
eine Tabelle, wie jedes bisher veröffentlichte). Es ist eine zweite Art von Seitenabfrage
und folgt denselben Regeln: Es wird beim Veröffentlichen aufgelöst, eingefroren, mit dem
Zugriff des [Besitzers](#who-owns-a-page) der Seite gelesen und erst nach seiner
[Zustimmung](#consent-the-owner-decides-who-reads-the-data).

| Im Binding | Bedeutung |
|---|---|
| `workflow` | Die ID oder der exakte Name des Workflows. Es muss einer sein, den die Workflows-Capability des Agents bindet, wie bei einer [Aktion](#actions), und die Person hinter dem Run muss ihn sehen können - der Besitzer der Seite ebenso, wenn die Veröffentlichung das Binding ändert |
| `step` | Optional: nur die Zeilen dieses Schritts, per ID, Label oder - bei einem Schritt ohne Label - dem Namen seiner Art, etwa `Send email`, wenn er eindeutig ist. Er muss in der Live-Version oder im Entwurf sein. Ein Schritt ohne Quick Log ist erlaubt, und das Ergebnis der Veröffentlichung vermerkt, dass er keine Zeilen liest |
| `outcomes` | Optional: nur Zeilen mit einem dieser Ausgänge - einem Port oder `error`. Jeder trifft zu, und eine Zeile mit mehreren Ports, gespeichert als `a, b`, zählt für jeden |
| `run` | Optional: eine Run-ID oder ihre ersten 4 oder mehr Zeichen |
| `include_test` | Auch Zeilen von Testläufen. Standardmäßig aus |
| `lines` | Die neuesten N Zeilen liefern, die neueste zuerst. Bis zu 500 in einem Binding; die eigene Route des Logs blättert zu je 100 |
| `per_day` mit `days` und `tz` | Stattdessen die Zahl der Zeilen pro Tag und Ausgang liefern: `days` ist 7, 30 oder 90, heute eingeschlossen, und `tz` ein IANA-Name, dessen Tage gezählt werden (standardmäßig UTC) |

Gib `lines` oder `per_day` an, nicht beides. Es sind die Filter und Limits von
`GET /workflows/{id}/logs` und `GET /workflows/{id}/logs/summary`, vom selben Code
bedient. Der Workflow und der Schritt werden beim Veröffentlichen zu IDs aufgelöst und mit
den Filtern gespeichert: Wird der Workflow oder der Schritt später umbenannt, ändert das
nichts an der Seite. Ein unbekannter Workflow, einer, den der Agent nicht bindet oder die Person nicht sehen kann (gleich
formuliert, damit eine Ablehnung nie bestätigt, dass er existiert), ein unbekannter Schritt,
ein Filter, der nicht stimmt, oder ein Limit über 500 lehnt das Veröffentlichen ab, und die
Meldung sagt, was.

Die Seite erhält es über denselben Aufruf `agenticos.onData`. Mit `lines` kommt ein Binding
als `status`, `records` (jeweils `{id, created_at, step, outcome, status, message, run_id}`),
`count`, `truncated` und `limit`, nach den Datensatz- und Byte-Limits der Seite gekürzt wie
das einer Tabelle. Mit `per_day` kommt es als `status`, `days` (jeder Tag des Fensters,
der älteste zuerst, je `{day, counts: {outcome: n}}`), `total`, `window_days` und `tz`, ohne
Datensatz-Limit.

```js
agenticos.onData((data) => {
  const week = data.errors_per_day;
  if (week.status !== "ok") return;
  AO.chart("#errors", {
    type: "bar",
    data: {
      labels: week.days.map((d) => d.day),
      datasets: [{ label: "Errors", data: week.days.map((d) => d.counts.error ?? 0) }],
    },
  });
});
```

veröffentlicht mit `bindings: {"errors_per_day": {"kind": "workflow_log", "workflow": "Order intake", "outcomes": ["error"], "per_day": true, "days": 30, "tz": "Europe/Warsaw"}}`.

Das Ergebnis der Veröffentlichung und die Zustimmung des Besitzers sagen es in Worten:
welcher Workflow, welche Filter und ob die neuesten N Zeilen oder Zählungen pro Tag über D
Tage geliefert werden.

Jede Änderung an einem Log-Binding - Workflow, Schritt, Ausgänge,
Run, Testzeilen, `lines` oder `per_day`, Limit, Tage oder Zeitzone - ändert die Abfragen der
Seite, braucht also erneut die Zustimmung des Besitzers, und eine
[Prüfung der Datenänderung](#consent-the-owner-decides-who-reads-the-data) markiert sie als
zeigt mehr.

Ein Log hat keine Spalten, kann also nicht abdriften; stattdessen ist das Binding
`unavailable`, wenn der Besitzer den Workflow nicht mehr sehen kann (`creator_lost_access`)
oder der Schritt nicht mehr darin ist (`source_changed`, mit dem Namen `step`). Zwei Grenzen
unterscheiden sich von denen einer Tabelle: Eine Seite, die einen Log liest, **kann keinen
öffentlichen Link haben** - das Veröffentlichen eines Log-Bindings wird abgelehnt, solange
der Link an ist, der Link lässt sich nicht einschalten oder an eine Version anheften, die
einen Log liest, und eine solche Version lässt sich nicht wiederherstellen, solange der Link
an ist. Ein Log-Binding wird auf einer öffentlichen Seite nie ausgeliefert.

Die Rollen, die jede Tabelle lesen, lesen den Log einer Seite nur dann ohne Zustimmung,
wenn sie auch jeden Workflow sehen, was jede eingebaute Rolle erfüllt, die jede Tabelle
liest; eine Rolle, die das nicht erfüllt, wartet wie ein Editor auf die Zustimmung des
Besitzers.

### Wer was sieht { #who-sees-what }

Welche Version ein Betrachter ausgeliefert bekommt und ob seine Daten für ihn
gelesen werden, hängt davon ab, wer er ist.

| Betrachter | Ausgeliefert | Seine Daten |
|---|---|---|
| Der Besitzer der Seite | Die neueste Version | Immer |
| Owner, Admin, Builder und Operator, auch nur lesend | Die neueste Version | Immer, für die Rollen, die jede Tabelle lesen (`tables:view` bei ALL) |
| Jeder andere, der die Seite bearbeiten darf | Die neueste Version, damit der Agent eines Editors weiter am Aktuellen arbeitet | Solange die Einwilligung des Besitzers für diese Version gilt |
| Alle anderen, die sie öffnen können (die **Zielgruppe**) | Die neueste Version, der je zugestimmt wurde oder die keine Daten liest | Solange die Einwilligung des Besitzers dafür gilt |

Die Zielgruppe bekommt nie eine Version ausgeliefert, deren Teilen niemand
zugestimmt hat. Gilt die Einwilligung für die Daten nicht mehr - ein Editor hat sie
zurückgezogen oder der Besitzer hat gewechselt -, bekommt die Zielgruppe weiterhin
diese **ganze Seite**, und jedes Binding kommt als `unavailable` mit dem Grund
`awaiting_consent` an; die Seite sagt „The data appears once the page's owner
confirms it.“ Ist keine Version überhaupt eingewilligt oder datenfrei,
sieht die Zielgruppe „This page isn't available yet“ und sonst nichts.

Ein Binding ist außerdem `unavailable`, wenn sich das, was es liest, seit der
Veröffentlichung der Seite geändert hat. Der Grund wird nur jemandem genannt, der
die Seite bearbeiten darf; ein Leser sieht, wie viele Quellen nicht verfügbar sind.

| Grund | Was passiert ist |
|---|---|
| `creator_gone` | Der Besitzer der Seite ist kein aktives Mitglied mehr |
| `creator_lost_access` | Der Besitzer kann eine Tabelle, die die Abfrage erreicht, nicht mehr lesen oder den Workflow, dessen Log sie liest, nicht mehr sehen |
| `source_changed` | Der Schritt eines Log-Bindings ist nicht mehr im Workflow (`step` wird genannt), oder die Bedeutung einer Spalte hat sich geändert (ihr Typ, eine Formel, ein Link- oder Lookup-Ziel, ein Aggregat, eine archivierte oder wiederhergestellte Option), eine Spalte oder Tabelle wurde archiviert, oder eine verknüpfte Tabelle beschriftet ihre Datensätze jetzt nach einer anderen Spalte. Das aktuelle Label der Spalte wird genannt |
| `awaiting_consent` | Der Besitzer hat das Teilen der Daten dieser Version nicht bestätigt, oder die Einwilligung wurde zurückgezogen |
| `public_link` | Ein Log-Binding wurde auf einer öffentlichen Seite angefordert, die nie eines ausliefert |

Fällt ein Binding aus, arbeiten die anderen weiter. Die Seite wird nie durch eine
Tabellenänderung blockiert: Nichts hindert eine Spalte daran, geändert zu werden,
und das Binding liefert nichts mehr, bis der Agent die Seite erneut
veröffentlicht, wodurch die Abfrage gegen die Tabelle im heutigen Zustand
aufgelöst wird. Eine Spalte umzubenennen ändert ein Binding nicht; die Seite liest
sie weiter unter dem Namen, den der Agent vergeben hat. Eine Option zu einem
Select hinzuzufügen oder eine umzubenennen, ändert es ebenfalls nicht.

### Einwilligung: Der Besitzer entscheidet, wer die Daten liest { #consent-the-owner-decides-who-reads-the-data }

Die Daten einer Seite werden mit dem Zugriff ihres Besitzers gelesen, deshalb
entscheidet der Besitzer pro Version, wer sie sonst noch liest. Diese
Entscheidung ist die **Einwilligung** (Consent): Der Besitzer prüft die
Seitenabfragen in Worten - Tabelle, Filter, Reihenfolge, Limit und Felder jeder
Abfrage, jede verknüpfte Tabelle, die sie erreicht, und wer sie lesen wird - und
bestätigt.

Die Prüfung nennt, wer die Seite sehen wird: die Rollen, die jede Seite sehen
(Owner, Admin, Builder und Operator), die Sichtbarkeit der Seite, die Personen, mit
denen sie geteilt ist, und die Gruppen, einschließlich künftiger Mitglieder. Der Besitzer kann nur bestätigen, was er selbst liest.

Die Daten einer Version befinden sich in einem dieser Zustände:

| Zustand | Bedeutung |
|---|---|
| `not_needed` | Die Version hat keine Bindings |
| `pending` | Niemand hat sie bestätigt. Die Zielgruppe behält die Version, die sie hatte |
| `consented` | Der Besitzer hat sie bestätigt, oder ihr wurde automatisch zugestimmt |
| `declined` | Eine Anfrage, sie zu bestätigen, wurde abgelehnt |
| `withdrawn` | Eine Einwilligung, die nicht mehr gilt: Ein Editor hat sie zurückgenommen, oder ihr Besitzer ist nicht mehr der Besitzer der Seite |

Einer neuen Version wird **automatisch** zugestimmt, wenn ihre Seitenabfragen - und
alles, was sie erreichen - dieselben sind, denen der Besitzer bereits zugestimmt
hat. Andernfalls ist sie `pending`: Das gilt auch für die erste gebundene Version,
sofern der Besitzer nicht die [automatische Einwilligung](#auto-consent)
eingeschaltet hat.

Der Besitzer, und nur er selbst, bestätigt in der Seitenanzeige. Solange die
neueste Version wartet, sagt das die Leiste unter dem Titel der Seite, mit
**Confirm data**: Es öffnet, was die Version teilt und mit wem, und die Bestätigung
trägt einen Fingerabdruck dessen, was genau angezeigt wurde. Wurde die Seite
dazwischen erneut veröffentlicht oder haben sich ihre Abfragen verschoben, wird
die Bestätigung abgelehnt, und der Besitzer schaut erneut hin. Das Bestätigen
prüft außerdem, dass der Besitzer weiterhin jede Tabelle lesen kann, die die
Abfrage erreicht.

Ein Owner oder Admin darf für den Besitzer bestätigen. Das wird als von ihm für
den Besitzer eingewilligt auditiert, und der Zugriff des Besitzers deckt die
Daten weiterhin. Wer einen `edit`-Grant hat, kann das nicht: Ein Grant zum
Bearbeiten der Seite ist keine Befugnis darüber, wessen Daten sie liest.

**Zurückziehen** nimmt die Einwilligung zurück. Jeder, der die Seite bearbeiten
darf, nutzt als er selbst **Stop sharing data** im Menü der Seitenanzeige. Jede
bisher erteilte Einwilligung wird ungültig, nicht nur die letzte, und die
automatische Einwilligung schaltet sich aus. Auch jeder `edit_data`-Grant auf der
Seite fällt auf `edit` zurück, sodass die nächste erneute Veröffentlichung eines
Daten-Editors auf den Besitzer wartet, statt das Zurückziehen rückgängig zu
machen. Die Zielgruppe behält die Seite und verliert ihre Daten, bis der Besitzer
erneut bestätigt. Das Zurückziehen schränkt nur ein, wer liest, deshalb darf es
jeder Editor.

Verlässt der Besitzer die Organisation, verfallen seine Einwilligungen mit seiner
Mitgliedschaft. Ein Besitzer, der entfernt und erneut eingeladen wird, fängt von
vorn an. Ein Besitzer, der deaktiviert und wieder aktiviert wird, belebt seine
Einwilligungen neu: Das Reaktivieren ist ein kontoweiter Vorgang, in jeder
Organisation, zu der das Konto gehört.

#### Erneut veröffentlichen { #republishing }

Veröffentlicht ein anderer Editor als der Besitzer eine Version, die andere Daten
liest, ist die Version `pending`, und die Plattform stellt eine
**Versionsanfrage** für den Besitzer - siehe [Freigabeanfragen](#share-requests).
Bis der Besitzer entscheidet, sieht die Zielgruppe weiterhin die frühere Version.
Das Ergebnis der Veröffentlichung sagt „The audience still sees v2 until Alex
confirms this version's data in the console.“ (mit dem Namen des Besitzers oder
„the page's owner“).

Ein Run ohne Person dahinter kann eine gebundene Seite nur unverändert erneut
veröffentlichen - dieselben Bytes und dieselben Abfragen, wofür es weder eine
Person noch eine Einwilligung braucht. Er kann den Code, der die Datensätze des
Besitzers empfängt, nicht austauschen. Eine Veröffentlichung durch einen Editor
wird abgelehnt, wenn der Besitzer der Seite eine Tabelle, die die Abfrage
erreicht, nicht lesen kann.

#### Automatische Einwilligung { #auto-consent }

Der Besitzer kann für eine Seite **Share new versions automatically**
einschalten. Standardmäßig ist es aus, und nur der Besitzer schaltet es als er
selbst ein, nie ein Agent. Es fragt zuerst: „Any data change your runs make to this
page, including new tables and columns, reaches everyone who can open it
without asking you. This includes API runs.“ Der Audit-Eintrag hält den bestätigten Text
fest.

Es deckt nur die eigenen erneuten Veröffentlichungen des Besitzers ab. Die erneute
Veröffentlichung eines Editors wartet weiterhin. Automatische Einwilligungen
werden als automatisch vermerkt, und erreicht eine mehr als die Version, die vor
ihr ausgeliefert wurde, führt die Leiste des Besitzers sie auf: „v4 was shared
automatically and shows more data: +Deals, +Salary“. Der Besitzer oder ein Owner oder
Admin schaltet es aus, und auch das Zurückziehen oder das Übergeben der Seite an
jemand anderen schaltet es aus.

Es deckt nie einen Run ab, der begann, als ein Administrator den Besitzer
imitierte, so spät er auch veröffentlicht: Ein Hintergrund-Run, ein Workflow-Schritt
oder ein nach einer Genehmigung fortgesetzter Run trägt das mit sich, und dasselbe
gilt für den Grant eines Daten-Editors (unten). Das erneute Veröffentlichen von
Abfragen, die der Besitzer schon bestätigt hat, ist weiterhin eingewilligt.

#### Daten-Editoren { #data-editors }

Der Freigabe-Dialog hat eine Grant-Stufe über `edit`: **Can edit, including data**
(`edit_data`), nur für Seiten. Sie ist eine dauerhafte Einwilligung in die
erneuten Veröffentlichungen dieser Person, eine Änderung der Abfrage
eingeschlossen. Nur der Besitzer oder ein Owner oder Admin erteilt sie, als er
selbst, nach einem Popup: „Alex can change the data everyone sees on this page,
including new tables and columns, without asking you. This also covers their API
runs.“ Bei einer Gruppe sagt das Popup „Anyone in Sales, now or later, can
change ...“. Der Grant wird mit dem bestätigten Text auditiert.

Eine erneute Veröffentlichung durch jemanden mit `edit_data` wird automatisch
eingewilligt und als über seinen Grant erfolgt vermerkt. Er muss weiterhin jede
Tabelle lesen können, die die Abfrage erreicht, und der Besitzer ebenfalls. Der
Rollenscope von Owner oder Admin impliziert ihn nie. Jeder, der die Seite
bearbeiten darf, senkt oder entfernt ihn, und ein Wechsel des Besitzers lässt
jeden `edit_data`-Grant auf `edit` fallen.

### Wem eine Seite gehört { #who-owns-a-page }

Der Besitzer einer Seite ist die Person, für die der erste veröffentlichende Run
gehandelt hat. Er ändert sich nie von selbst und ist der einzige Datenbesitzer der
Seite: die Person, deren Zugriff die Daten liest und deren Einwilligung sie teilt.
Wird der Besitzer gelöscht, hat die Seite keinen. Niemand kann eine Seite für sich
beanspruchen.

Der Besitzer übergibt sie mit **Change owner** im Menü der Seitenanzeige an ein
anderes aktives Mitglied der Organisation, und ein Owner oder Admin darf jede Seite
neu zuweisen, auch eine, deren Besitzer weg ist. Jeder tut das als er selbst, nicht
durch Impersonation. Ein Grant zum Bearbeiten der Seite erlaubt es nicht. Es gibt
dafür kein Agent-Tool.

Der Wechsel erfolgt sofort, ohne Annahmeschritt. Die Daten der Seite erreichen die
Zielgruppe nicht mehr, bis der neue Besitzer sie bestätigt, jede bisherige
Einwilligung wird endgültig ungültig (die Seite zurückzugeben belebt also nie eine
alte), die automatische Einwilligung schaltet sich aus, jede ausstehende Anfrage
wird hinfällig, jeder `edit_data`-Grant fällt auf `edit` zurück, und der alte und
der neue Besitzer werden benachrichtigt, außer wer den Wechsel vorgenommen hat. Er
wird als `artifact.owner_changed` auditiert.

Einer Seite ohne Besitzer die Sichtbarkeit `private` zu geben, gilt als Übernahme
und ist nur einem Owner oder Admin möglich. Es gelten dieselben Regeln.

### Freigabeanfragen { #share-requests }

Zu erweitern, wer eine Seite öffnen kann, die Daten liest - eine weitere
Sichtbarkeit oder ein neuer Grant oder eine höhere Stufe -, ist die Entscheidung
des Besitzers oder die eines Owners oder Admins für ihn. Einschränken steht jedem
Editor offen. Eine Seite, die keine Daten liest, behält die üblichen
Freigaberegeln.

Wer sonst die Seite bearbeiten darf und versucht, sie zu erweitern, bekommt keine
Ablehnung. Die Plattform stellt eine Anfrage. Es gibt drei Arten:

| Art | Gestellt von | Bittet |
|---|---|---|
| `audience` | Einem Editor, im Share-Dialog oder durch das `share_artifact` seines Agents | Zu erweitern, wer die Seite öffnet |
| `access` | Einem Mitglied der Organisation der Seite, das ihren Link ohne Zugriff öffnet | Die Seite öffnen zu dürfen, mit einer optionalen Notiz |
| `version` | Der Veröffentlichung eines anderen Editors, dessen Version andere Daten liest | Diese Version zu bestätigen |

Ein Mitglied kann pro Seite je eine ausstehende `audience`- und eine ausstehende
`access`-Anfrage haben, und eine Seite hat eine ausstehende `version`-Anfrage; eine
neuere ersetzt die ältere. Anfragen sind standardmäßig auf
zehn pro Stunde je Person und Organisation begrenzt
([`RATE_LIMIT_ARTIFACT_SHARE_REQUESTS_PER_HOUR`](configuration.md)). Eine
`version`-Anfrage zählt auch gegen das Kontingent des Veröffentlichenden: Danach
ersetzt eine erneute Veröffentlichung die ausstehende Anfrage weiterhin, der Besitzer
wird aber nicht erneut benachrichtigt.

Der Besitzer der Seite entscheidet. Hat sie
keinen Besitzer mehr, können die Owner und Admins ablehnen; um zu genehmigen,
übergeben sie die Seite zuerst an ein Mitglied (**Change owner**), das die Daten
bestätigt. Eine Anfrage wird ohne Entscheidung hinfällig, wenn sich die Abfragen
der Seite ändern, der Besitzer wechselt oder die Seite archiviert wird.

Der Besitzer wird in der Konsole und per E-Mail benachrichtigt, wie unter
**Settings → Notifications** eingestellt („Page requests“). Die
Benachrichtigung nennt die Seite und den Anfragenden, nie ihre Daten.

Beantwortet werden sie in einem Abschnitt **Requests** des Share-Dialogs, und eine
Schaltfläche **Requests** in der Leiste der Seitenanzeige zeigt, wie viele warten.
Eine `audience`- oder `access`-Anfrage zu genehmigen, wendet die Sichtbarkeit und
die Grants an, um die sie gebeten hat, jeweils nur dort, wo es noch erweitert.
**Es willigt nie in Daten ein**: Hat die Version, die die Zielgruppe ausgeliefert
bekommt, keine Einwilligung, die gilt, wird das Genehmigen mit „Confirm the page's
data before sharing it“ abgelehnt, und der Besitzer bestätigt zuerst die Daten und
genehmigt dann. Ablehnen teilt nichts.

Eine `audience`- oder `access`-Anfrage, die unter einer Mitgliedschaft
gestellt wurde, die inzwischen beendet ist (das Mitglied wurde entfernt und erneut
eingeladen), lässt sich nicht genehmigen; lehnen Sie sie ab.

Die Liste der Anfragen (`GET /api/v1/artifacts/{id}/share-requests`) enthält immer alle
ausstehenden Anfragen. Mit `include_decided=true` fügt sie die entschiedenen und
hinfälligen hinzu, die aufbewahrt werden, neueste zuerst und seitenweise mit `skip`
und `limit` (standardmäßig 50, höchstens 100); `total` zählt alle, und der
Freigabe-Dialog sagt, wenn er nur die neuesten entschiedenen zeigt.

Der Anfragende erfährt die Entscheidung nicht: Dass die Seite sich öffnet oder
nicht, ist die Antwort. Eine Seite, die keine Daten liest, nimmt eine einfache
`access`-Anfrage entgegen, die jeder Editor von ihr genehmigen darf.

#### Zugriff anfragen { #requesting-access }

Ein Mitglied der Organisation, das den Link einer Seite öffnet, die es nicht
öffnen kann, sieht „You don't have access to this page“, ein Notizfeld und
**Request access**. Sonst wird nichts preisgegeben: kein Titel, kein Besitzer, kein
Agent. Ein abgemeldeter Besucher oder jemand aus einer anderen Organisation
bekommt das übliche „nicht gefunden“.

#### Eine geänderte Version prüfen { #reviewing-a-changed-version }

Eine `version`-Anfrage öffnet dem Besitzer die Seite auf der ausstehenden Version,
mit ihren echten Daten. Die Leiste sagt, wer die Daten geändert hat, die die Version zeigt,
mit **Review data change**. Das Panel vergleicht die Seitenabfragen der Version mit
der, die die Zielgruppe jetzt sieht, Binding für Binding und in Worten: Felder,
Filter, Reihenfolge, Limit und verknüpfte Tabellen, hinzugefügt, entfernt oder
geändert, jeweils markiert als **Shows more**, **Shows less** oder ohne Änderung,
neue Bindings mit ihrer vollständigen Offenlegung und unveränderte eingeklappt.

Ein Schalter, **What others see**, zeigt die Seite so, wie die Zielgruppe sie hat.
Das Panel nennt, wer die Version veröffentlicht hat und wann, und verlinkt auf die
Unterhaltung, wenn der Besitzer sie öffnen darf. **Approve** bestätigt die Version.
**Decline** hält die Zielgruppe auf der früheren Version und markiert die Version
in ihrem Verlauf als `declined`; eine spätere erneute Veröffentlichung fragt erneut.
In der Liste Requests bietet eine Versionsanfrage **Review data change**, nicht
Approve: Sie wird aus der Prüfung heraus bestätigt.

### Eine Seite aus einem Agent heraus teilen { #sharing-a-page-from-an-agent }

`share_artifact(name, visibility?, people?)` lässt einen Agent darum bitten, eine
Seite zu teilen: `visibility` ist `team` oder `org`, `people` sind Mitglieder per
vollem Namen oder E-Mail und Gruppen per Namen, jeweils auf Leseebene angefragt. Es
**teilt nie etwas**. Es stellt eine `audience`-Anfrage für die Person, für die der
Run handelt - der eigene Run des Besitzers eingeschlossen - und antwortet „Waiting
for Alex to approve in the page's Share dialog“. Die Genehmigung ist eine Person in
der Konsole, als sie selbst angemeldet, nie ein Tool-Aufruf.

Ein Name, der auf niemanden oder auf mehrere Personen passt, wird zurückgemeldet,
nie geraten. Es bittet um nichts Öffentliches: Der öffentliche Link wird nur in der
Konsole eingerichtet. Ein Run ohne Person dahinter, etwa ein Widget-Besucher, kann
nicht anfragen.

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
Stunde. Jeder Betrachter wählt selbst, und die Wahl wird pro Seite in diesem
Browser gespeichert.

Die automatische Aktualisierung tut nichts, solange der Tab verborgen ist, und
liest einmal, wenn der Tab zurückkommt und ein Takt verpasst wurde. Sie hört auf,
wenn die Daten abgelehnt werden (die Seite ist für diesen Betrachter nicht mehr
da) und wenn keine Quelle der Seite gelesen werden kann, bis der Betrachter auf
Refresh klickt und ein Lesen antwortet. Ein Fehler, der nichts über die Seite
aussagt, etwa ein Serverfehler, lässt sie weiter abfragen. Eine Antwort „busy“
(429) wird zweimal im Abstand von einer Sekunde wiederholt, bevor der Betrachter
„Busy, try again in a moment.“ liest.

Eine Zeile unter der Leiste erscheint nur, wenn etwas Aufmerksamkeit braucht: eine
Version, die auf Bestätigung wartet, eine Anfrage zur Prüfung oder Quellen, die
nicht gelesen werden können. Eine abgelehnte Seite sagt „This page's live data is
not available to you.“ Ein Leser, dessen Quellen nicht gelesen werden können, sieht,
wie viele („2 of 3 sources unavailable to you“). Ein Editor sieht außerdem für jede
Quelle den Grund, mit einem Link **Open the table** zur gebundenen Tabelle.

Veröffentlicht ein Agent eine neue Version, während jemand die aktuelle offen hat,
wechselt die Seitenanzeige beim nächsten Lesen (einer manuellen oder automatischen
Aktualisierung) auf die Version, die dem Betrachter jetzt ausgeliefert wird: Die
Seite wird neu geladen, mit ihren eigenen Daten. Wer im Versionsmenü eine Version
gewählt hat, bleibt bei ihr.

Auf einer älteren Version werden keine Live-Daten gelesen. Die Seitenanzeige sagt
„Live data only on the current version.“ mit **Open current** und, für einen
Editor, **Restore** für diese Version. Eine Wiederherstellung löst die
Seitenabfragen der Version gegen die Tabellen im heutigen Zustand auf, ist also
eine neue Abfrage, wenn eine Tabelle sich weiterentwickelt hat, und wartet wie
jede andere erneute Veröffentlichung auf die Einwilligung.

### Wie die Daten die Seite erreichen { #how-the-data-reaches-the-page }

Öffnet die Konsole eine Seite, fragt sie nach einer signierten Adresse, die trägt,
wer der Betrachter ist. Die Content-Route liest jedes Binding **einmal, beim
Laden**, und schreibt das Ergebnis in das Plattform-Skript der Seite, sodass der
erste `onData`-Aufruf seine Daten bereits hat und kein weiterer Roundtrip folgt.
Ein [öffentlicher Link oder ein Embed](#live-data-on-a-public-link) wird auf
dieselbe Weise beschrieben, unter strengeren Bedingungen. Für eine Vorschau, eine
Karte oder eine Version aus dem Verlauf wird nichts eingefügt.

Refresh und die automatische Aktualisierung nutzen weiterhin die Daten-Route und
ein `postMessage` der Konsole, das jetzt für alle, denen diese Version
ausgeliefert wird, dieselben Zeilen der Seitenabfrage beantwortet. Die Route wird
nie gecacht, die Adresse ist kurzlebig, und der Inhalt eines Datensatzes bleibt
aus den Logs heraus. Ein Binding, das nicht rechtzeitig gelesen werden kann oder
in der Datenbank fehlschlägt, wird als `unavailable` eingefügt, und die Seite wird
trotzdem dargestellt.

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
| Lesevorgänge nur der Gründe (`rows=false`, Leiste des Editors) | Dieselben Grenzen, getrennt von den Datenladevorgängen gezählt |
| Freigabeanfragen | 10 pro Stunde je Person und Organisation (audience, access und version) |

Ein gekürztes Binding meldet `truncated: true`, mit `limit` auf `records` oder
`bytes` und `count` als Zahl der ausgelieferten Datensätze. `bytes` deckt auch ein
Lesen ab, dessen gemessene Kosten aufgebraucht waren, bevor die aufbereiteten Daten
den Anteil der Seite gefüllt hatten.

Die Frist wird vor jeder Abfrage geprüft, ohne eine abzubrechen: Jede Abfrage läuft
höchstens so lange wie das Kleinere aus 2 s und der Restzeit der 5 s, und sind die
5 s verbraucht, beginnt keine Abfrage mehr, sodass eine Seite in etwa 5 s
antwortet und die Wanduhrzeit etwa 7 s erreichen kann.

Eingefügte Ladevorgänge
zählen wie Aktualisierungen gegen die 30 pro Minute. Jenseits eines Rate-Limits
antwortet die Daten-Route mit 429, die Konsole wiederholt eine Antwort „busy“
zweimal, und eine Seite, die mit ihren Daten ausgeliefert wurde, bekommt
Bindings mit `busy`. Ist Redis ausgefallen, zählen die Untergrenze des
Rate-Limits und das Limit gleichzeitiger Ladevorgänge pro API-Worker, und die
Obergrenze pro Prozess begrenzt weiterhin jeden Worker.

### Wer eine gebundene Seite veröffentlichen darf { #who-may-publish-a-bound-page }

Eine Seite bindet sich nur dann an eine Tabelle, wenn der Spec des
veröffentlichenden Agents Lesezugriff auf sie freigibt und die Person hinter dem
Run jede Tabelle liest, die die Abfrage erreicht, geprüft beim Veröffentlichen der
Seite oder beim Wiederherstellen einer Version. Wird eines von beiden später
entzogen, hält das bereits veröffentlichte Seiten nicht an; der Zugriff des
Besitzers wird bei jedem Laden erneut geprüft.

Eine gebundene Seite kann nur ein Run **ändern**, der für ein Mitglied handelt (eine
unveränderte erneute Veröffentlichung, mit denselben Bytes und Abfragen, braucht
keine Person): das angemeldete Mitglied (Web-Chat, HTTP-API), ein verknüpfter
Absender in einem Kanal oder der Ersteller eines Zeitplans. Der Besucher eines
Widgets, eines Embeds oder einer gehosteten Seite, ein nicht verknüpfter Absender
in einem Kanal und die Zustellung eines Ereignis-Triggers eines Agents (GitHub,
E-Mail, Webhook-Relay) zählen nicht, ebenso wenig ein Workflow-Run, den ein
öffentlicher Eingang zugelassen hat, oder irgendein Run in der Kette eines solchen
Runs.
## Aktionen { #actions }

Eine Seite kann einen [Workflow](workflows.md) starten, aber nur, wenn eine Person
zustimmt. Die Seite handelt nicht: Sie fragt, die Konsole zeigt der Person, was
geschehen würde, und der Run gehört ihr. So wird eine Seite zu einer kleinen App - ein
Formular, das eine Anfrage einreicht, ein Knopf, der eine Rechnung freigibt -, ohne dass
die Seite selbst irgendeine Macht hält.

### Aktionen deklarieren { #declaring-actions }

Der Agent deklariert die Workflows, die eine Seite starten darf, beim Veröffentlichen mit
dem Argument `actions` von `publish_artifact`: bis zu fünf Einträge, jeweils ein Workflow
(seine ID oder sein exakter Name) und ein **Label**, das Wort, mit dem die Seite ihn
nennt.

```json
{"actions": [{"workflow": "Approve invoice", "label": "Approve"}]}
```

Ein Workflow kann nur dann eine Aktion sein, wenn alles Folgende zutrifft:

- Der veröffentlichende Agent hat ihn in der [Workflows-Capability](reference/capabilities.md#workflows),
  sodass das, was eine Seite starten darf, Teil dessen ist, was der Autor des Agents
  geprüft hat;
- er ist live (veröffentlicht, nicht archiviert) und startet aus einem **Manual**- oder
  **API**-Trigger;
- die Person hinter dem Run darf ihn ansehen und ausführen. Einen, den sie nicht darf,
  beantwortet die Plattform, als wäre er nicht gebunden, sodass eine Abweisung nie einen
  Workflow nennt, den die Person nicht sehen kann.

Das Label ist reiner Text von höchstens 60 Zeichen, aus dem Steuer- und unsichtbare
Zeichen entfernt wurden; ist es leer, wird es zum Namen des Workflows. Wird `actions`
weggelassen, bleiben die der aktuellen Version erhalten, und `[]` entfernt sie. Das
Ergebnis der Veröffentlichung führt jede deklarierte Aktion in Worten auf oder sagt
`kept`. Eine Markdown-Seite kann keine Aktionen haben. Ein Run ohne Person dahinter kann
sie weder hinzufügen noch ändern und kann nur eine Seite, die bereits welche hat,
unverändert erneut veröffentlichen. Beim Wiederherstellen einer älteren Version werden
ihre Aktionen erneut gegen den Agent in seinem heutigen Zustand geprüft, und sie wird
abgewiesen, wenn eine nicht mehr besteht.

Aktionen werden mit der Version gespeichert, sodass eine neue Version die ganze Liste
ersetzt und eine ältere ihre eigene behält. Einen Workflow später vom Agent zu lösen
ändert keine veröffentlichte Version; der eigene Zustand des Workflows und der Zugriff
jedes Betrachters werden bei jedem Öffnen der Seite und erneut beim Start eines Runs
geprüft.

### Wer welche Aktionen sieht { #who-sees-which-actions }

Wenn die Konsole eine Seite öffnet, listet sie die Aktionen, die die **ausgelieferte
Version** deklariert und die dieser Betrachter jetzt ausführen darf: jede mit dem echten
Namen des Workflows, dem Label der Seite und den Feldern, die sein Trigger verlangt. Eine,
die der Betrachter nicht ausführen darf, bleibt weg. Die Leiste des Betrachters zeigt
**This page can run: ...** und nennt die Workflows, jeweils ein Link auf die Runs dieses
Workflows. Ohne welche wird nichts gezeigt.

Eine Seite bekommt keine Aktionen, und ihr `run`-Aufruf wird sofort abgewiesen, wenn sie
gezeigt wird:

- auf einem öffentlichen Link, in einem Embed, in einer Vorschau oder im Thumbnail einer
  Karte;
- als ältere Version aus dem Verlauf oder als eine Version, die nicht die ist, die diesem
  Betrachter ausgeliefert wird (ein Publikum wartet noch auf die Einwilligung für die
  neuere);
- für ein Mitglied, das keinen ihrer Workflows ausführen darf, oder für eine Session, die
  imitiert wird.

Die Start-Route weist all das ebenso ab, sodass eine Seite, die die Konsole umgeht,
nichts gewänne.

### Eine aus der Seite ausführen { #running-one-from-the-page }

In der Seite bittet `agenticos.run(action, input)` - `AO.run` im
[Seitenkit](#the-library-set) - die Konsole, eine Aktion zu starten. `action` ist eine
Workflow-ID, das Label der Seite oder der Name des Workflows. Die Konsole gleicht erst die
ID exakt ab, dann das Label, dann den Namen, ohne Beachtung der Groß- und Kleinschreibung.
Eine Stufe, die auf zwei Aktionen passt, trifft nichts und fällt nicht auf die nächste
durch. `input` ist ein Objekt mit genau den Werten, die der Trigger des Workflows
deklariert. Der Aufruf gibt ein Promise des abgeschlossenen Runs zurück, und `onRun`
(`AO.onRun`) hört unterwegs jede Änderung:

```js
AO.run("Approve", { invoice: "INV-204" }).then(
  (run) => show(run.status, run.output_text),
  (error) => show("not run", error.message),
);
```

Die Konsole startet nichts, bevor die Person zugestimmt hat. Jeder Run, egal wie viele
davor kamen, öffnet einen Bestätigungsdialog:

- sein Titel ist der **eigene Name des Workflows**, und das Label der Seite erscheint nur
  als Zitat;
- er zeigt jeden Wert, den die Seite sendet, vollständig und als Text, wobei Zeichen, die
  nichts zeichnen oder den Text umordnen, ausgeschrieben werden (`\u{202E}`);
- **Run** ist eine halbe Sekunde deaktiviert und bekommt nie den Fokus, sodass ein Klick,
  der schon unterwegs ist, nicht zustimmt; Cancel hat den Fokus;
- es ist immer nur eine Frage offen, über Run- und Link-Dialoge hinweg, und eine Anfrage,
  die in der Zwischenzeit eintrifft, wird als `busy` abgewiesen;
- nach **drei Ablehnungen** bei einem Öffnen der Seite (ein Neuladen des Frames behält die
  Zählung) hört die Konsole auf zu fragen und weist weitere Anfragen ab, bis die Seite
  erneut geöffnet wird.

Eine Anfrage wird ohne Dialog abgewiesen, wenn sie zu früh kommt (der Frame ist noch nicht
geladen), eine Aktion nennt, die die Seite nicht deklariert, nicht zu den Feldern des
Workflows passt oder von etwas anderem kommt als dem eigenen Frame der Seite unter der
Nonce, die die Konsole für dieses Laden ausgestellt hat. Eine Nachricht von einem anderen
Frame oder von einer veralteten Seite wird ohne Antwort verworfen.

Das Promise wird mit einem `Error` abgelehnt, dessen `message` ein kurzer Code ist, damit
die Seite ihren eigenen Text formuliert:

| Code | Wann |
|---|---|
| `cancelled` | Die Person hat abgelehnt |
| `busy` | Eine andere Frage war offen |
| `too_many_cancels` | Drei Ablehnungen; die Seite wird nicht erneut gefragt, bis sie neu geöffnet wird |
| `not_ready` | Die Seite hat gefragt, bevor ihr Frame geladen war |
| `unknown_action` | Keine deklarierte Aktion passt, die der Betrachter ausführen darf |
| `invalid_input` | Ein Wert fehlt, ist unbekannt oder hat den falschen Typ; `error.problems` listet `{field, kind}` nur, wenn die Konsole das Problem gefunden hat, und fehlt, wenn der Server mit 422 geantwortet hat |
| `rate_limited` | Zu viele Runs von dieser Person, oder die Admission-Quote des Aufrufers oder der Organisation |
| `not_found`, `unavailable` | Die Aktion ist weg, nicht mehr von Hand startbar oder archiviert, oder die Seite kann hier gar keine Aktionen ausführen (ein öffentlicher Link, ein Embed, eine Vorschau, der Verlauf, ein Betrachter ohne ausführbare Aktion) |
| `failed` | Der Run konnte nicht gestartet oder verfolgt werden |
| `page_changed` | Die Seite wurde ersetzt, während die Frage offen war |

### Was der Run ist { #what-the-run-is }

Der Run gehört dem **Betrachter**: Er startet mit dessen Berechtigungen und zählt gegen
dessen Budget, als hätte er den Workflow aus der Konsole ausgeführt. Sein Trigger ist
**App** (`app`), und er hält die Seite und die Version fest, die die Person ansah. Die
Seite verleiht nichts; der Run wird abgewiesen, wenn die Person ihn nicht selbst hätte
starten können. Ein Run, der auf eine Freigabe wartet oder darauf, dass jemand ihn
ansieht, bleibt im [Run-Verlauf](workflows.md#running-a-workflow) des Workflows, und der
Betrachter zeigt eine Zeile mit **Open run**.

Die Seite bekommt nie den ganzen Run. Sie liest eine Projektion: den Status, den
Antworttext, die strukturierte Antwort ohne Dateiverweise, die erste Zeile eines Fehlers
(höchstens 200 Zeichen) und, solange der Run auf jemanden wartet, den Pfad dorthin in der
Konsole. Nur die Person, die den Run gestartet hat, kann ihn lesen, und nur über die
Seite, die ihn gestartet hat.

Die Konsole liest den Run mit wachsender Verzögerung und sendet jede Änderung an die
Seite. Ein Run, der auf jemanden wartet, wird zehn Minuten lang gelesen, in denen der Tab
sichtbar ist. Danach wird das Promise der Seite mit dem letzten Zustand, `paused: true`
und ohne `finished` erfüllt, und die Seite hört nichts mehr; die Zeile im Betrachter ist
der Weg zum Run. Einer Seite, die neu geladen oder geschlossen wird, wird nichts gesagt.

### Grenzen und Audit { #limits-and-audit }

| Grenze | Wert |
|---|---|
| Aktionen pro Seite | 5 |
| Label | 60 Zeichen |
| Aus einer Seite gestartete Runs | 10 pro Minute und Person und Seite (`RATE_LIMIT_ARTIFACT_ACTIONS_PER_MINUTE`) |
| Ablehnungen, bevor die Konsole aufhört zu fragen | 3 pro Öffnen der Seite (ein Neuladen des Frames behält die Zählung) |
| Ausstehende Arbeit | die eigene Admission-Quote der Workflow-Runs, die ebenfalls mit `rate_limited` antwortet |

Jenseits einer Grenze sieht die Person eine Meldung, und die Seite bekommt `rate_limited`.
Jeder Start wird als `artifact.action_started` auditiert, mit der Seite, der Version, dem
Workflow und dem Run - nie die Eingabe, die der Person gehört und am Run selbst steht.
Siehe [Governance](governance.md#audit) und [die Sicherheitsseite](security.md#a-page-that-starts-workflows).

## Ein Name, ein Link { #one-name-one-link }

Die Identität einer App ist ihr **Name innerhalb des Agents** —
`weekly-report`, `churn-dashboard`. Wer unter demselben Namen veröffentlicht,
aktualisiert dieselbe App, von jeder Oberfläche aus: dem Chat, der API,
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
Run veröffentlicht eine bestehende App nur dann erneut, wenn die Person, für
die er handelt, sie besitzt oder `artifacts:edit` darauf hat — aus der Rolle oder
aus einem `edit`-Grant, dieselbe Regel wie bei der Verwaltung in der Konsole. Der
Run jeder anderen Person erfährt, dass der Name vergeben ist, und veröffentlicht
unter einem anderen. Eine Kollegin, die denselben geteilten Agent um einen
`weekly-report` bittet, kann die Seite hinter Ihrem Link also nicht ersetzen.

Jede Veröffentlichung ist eine neue **Version**. Nichts wird überschrieben, daher
ist die Versionsliste auf der Seite der App die Geschichte der Seite. Zwei
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
| `lib/agenticos-3.js` | `window.AO`: Chart.js im Stil der Konsole, Zahlenformate in der Sprache der Seite, Icons, Tabs, `AO.onData`, `AO.records` sowie `AO.run` und `AO.onRun` für [Aktionen](#actions) |
| `lib/agenticos-2.css`, `lib/agenticos-2.js` | Die vorige Version des Kits, behalten für die Seiten, die gegen sie veröffentlicht wurden |
| `lib/agenticos-1.css` | Die erste Version des Aussehens, behalten für die Seiten, die gegen sie veröffentlicht wurden |
| `lib/three-0.186.0/three.module.js` | three.js 0.186.0 als ES-Modul, mit `addons/controls/OrbitControls.js` daneben - `three` und `three/addons/` per Import Map darauf abbilden |
| `lib/mermaid-12.1.0.min.js` | Mermaid 12.1.0, als `window.mermaid` |
| `lib/leaflet-1.9.4/leaflet.js`, `leaflet.css` | Leaflet 1.9.4, als `window.L` - zeichnet auf den [Kartenkacheln](#visuals) des Deployments, wenn es welche hat |
| `lib/agenticos-map-2.js` | `window.AOMap.itinerary`: nummerierte Pins, der Reihe nach gezeigt und auf Wunsch einzeln gesetzt, eine Karte im Verhältnis 16:9 zur Breite der Seite, eine Linie zwischen ihnen und Karten für die Stopps - auf Kartenkacheln, oder ohne sie als Umriss der Stopps. `lib/agenticos-map-1.js`, das die Pins beim Laden setzt und eine feste Höhe hat, wird für die Seiten, die es nennen, weiter ausgeliefert |
| `lib/agenticos-map-1.js` | `window.AOMap.itinerary`: nummerierte Pins, der Reihe nach gesetzt, eine Linie zwischen ihnen, Pause und Wiederholung und Karten für die Stopps - auf Kartenkacheln, oder ohne sie als Umriss der Stopps |

Jeder Name trägt seine Version und wird ein Jahr lang gecacht. Ein Upgrade fügt
eine neue Datei neben der alten hinzu, sodass eine Seite, die gegen eine Version
veröffentlicht wurde, weiter genau diese bekommt, und eine ausgelieferte Datei
wird nie geändert. Nichts wird von außerhalb des Deployments geholt, also
funktioniert ein Deployment ohne Internetzugang genauso. Die Dateien sind in
`backend/app/core/catalog/artifact_lib/` aufgeführt.

Die Dateien antworten mit `Access-Control-Allow-Origin: *`, weil ein Modulskript im
CORS-Modus geladen wird und eine Seite in einem opaken Origin `Origin: null` sendet -
ohne das würde three.js nicht importiert.

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
Apps im Builder bietet ihn an. Bearbeiten Sie den Skill, um Ihre eigene
Marke zu beschreiben, und der Agent folgt ihr.

### Der Seitenvertrag und die Warnungen beim Veröffentlichen { #the-page-contract-and-the-publish-warnings }

Der Agent kann die Seite, die er veröffentlicht, nicht sehen, deshalb sagt ihm
die Plattform, wie eine Seite aussehen muss und was an der gesendeten falsch
aussieht.

Die Capability Apps gibt jedem Agent, der sie hat, einen kurzen
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
- `AO.onData`, `AO.records`, `AO.run` oder `AO.onRun` auf einer Seite, die `lib/agenticos-3.js` nicht
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
die Konsole sie für sie lesen würde, und zählen gegen deren Kontingent für
Datenabrufe. In einem Gruppenchat lässt sich nur eine Seite der ganzen Organisation
in der Vorschau zeigen, dieselben Seiten, die die Liste dort zeigt, und sie wird
ohne Daten gezeichnet. Ebenso eine Seite, die ein Run in der Vorschau zeigt, für den
niemand einsteht: einer, den ein Außenstehender über einen Webhook, ein Formular,
eine Kanalnachricht, eine E-Mail oder ein Repository-Ereignis gestartet hat, gleich
als wer er ausgeführt wird. Eine Oberfläche, an der niemand angemeldet ist, zeigt
keine Vorschau.

Nichts, was die Seite anfragt,
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

## Visuals { #visuals }

Ein [Visual](reference/capabilities.md#visuals) ist eine App, die noch nicht
gespeichert wurde: eine Zeichnung, die ein Agent mit `draw` ins Gespräch schreibt und
die unter seiner Nachricht erscheint, während sie geschrieben wird. Es ist dieselbe Art
Dokument - ein `html`-Visual ist eine Seite, ein `svg`- oder `mermaid`-Visual wird zu
einer Seite, die es enthält - und es wird mit derselben Isolation gezeichnet.

**Der Rahmen.** `/api/v1/artifact-content/visual-frame` ist eine feste Seite auf dem
Content-Origin, ausgeliefert mit genau der Policy, die jede App-Seite bekommt. Sie
enthält keine Zeichnung: Die Konsole gibt die Zeichnung beim Streamen hinein, sodass
nichts gespeichert werden muss, bevor es gezeigt wird, und die Isolation kommt aus dem
Response-Header statt aus einem `srcdoc`-Meta-Tag. Während des Streamens formt der
Rahmen das Markup an Ort und Stelle um, ohne Skripte und `on*`-Attribute; ist es
vollständig, schreibt er das ganze Dokument, damit seine Skripte laufen, genau wie auf
der gespeicherten Seite. Der Rahmen meldet seine Größe, seine Fehler und einen
Herzschlag; eine Zeichnung, die nicht mehr schlägt, wird geschlossen, statt den Tab
festzuhalten.

**Im Chat.** Eine Zeichnung steht im Gespräch selbst, ohne Karte darum, ab dem
linken Rand des Nachrichtentexts: ein SVG wird nach seiner `viewBox` eingepasst und
über 560 Pixeln verkleinert, eine Seite wird in der Breite der Spalte gesetzt und
über 900 verkleinert. Eine ruhige Zeile darunter nennt sie und sagt, ob sie noch
gezeichnet wird; *Code anzeigen*, *Herunterladen* (`.svg`, `.html` oder die
Mermaid-Quelle), *Als Bild kopieren* für ein SVG, *In Apps speichern* und
*Vollbild* erscheinen in dieser Zeile, wenn der Zeiger über der Zeichnung ist, und
auf einem Touchscreen immer. Während sie gestreamt wird, behält die Zeichnung die
Höhe, die ihr Aufruf angegeben hat, auf einem leichten Ton, damit sich das Gespräch
unter dem Leser nicht verschiebt. Vollbild zeigt sie in ihrer eigenen Größe; auf
einem Telefon öffnet ein Tippen die Vorschau im Vollbild. Der Zoom sitzt unten
rechts in der Zeichnung, solange der Zeiger darauf ist: ein SVG wird größer
gezeichnet, eine Seite skaliert, und der Rahmen scrollt, sobald die Zeichnung ihm
entwächst. Ein Fehler, den die Zeichnung meldet, kommt mit *Beheben*, das den
Agent fragt.

**Folgenachrichten.** Ein Bedienelement in einer Zeichnung kann die Wahl der
Person an das Gespräch zurückgeben - *Diesen Stopp planen*, *Diese Zahlen
verwenden* - indem es `agenticos.followUp(text)` aufruft. Die Zeichnung bittet nur.
Die Konsole zeigt den genauen Text unter der Zeichnung mit *Senden*, *Bearbeiten*
und *Verwerfen*, und er wird erst dann zur Nachricht der Person, wenn sie auf
*Senden* klickt - einen Klick, den die Zeichnung nicht für sie machen kann. Eine
Bitte ohne Benutzerinteraktion dahinter - beim Laden, per Timer - wird verworfen,
ebenso eine über 2.000 Zeichen, und solange eine wartet, kann keine zweite sie
ersetzen. Folgenachrichten gibt es nur im Chat: `agenticos.canFollowUp()` ist in
einem geteilten Thread, im Widget und in einer App falsch, wo `followUp` nichts
tut und `false` zurückgibt, sodass eine gespeicherte Zeichnung weiter funktioniert.

**Karten.** Ist [`VISUAL_MAP_TILES`](configuration.md#published-artifacts)
gesetzt, kann eine Zeichnung oder eine App auf echten Kartenkacheln zeichnen: das
Deployment holt jede Kachel von diesem Server und liefert sie über seinen eigenen
Kachelpfad aus, `agenticos.map` sagt wohin, und das Karten-Kit zeichnet darauf eine
Route mit der Quellenangabe des Servers darunter. Ohne die Einstellung zeichnet
derselbe Aufruf einen Umriss der Stopps - Pins und die Linie dazwischen, keine
Straßen - und ebenso eine Karte, deren Kacheln nicht laden. Der Agent sagt das in
seiner Antwort: dass kein Kartenserver angebunden ist und dass ein Administrator
echte Karten mit dieser Einstellung einschaltet. Das Bild einer Karte in
einer Chat-App wird fertig gezeichnet, mit allen Pins an ihrem Platz.

**Die Form wählen.** Der Skill `visual-design` sagt dem Agent, wann eine Zeichnung
überhaupt die richtige Antwort ist: Text für eine Tatsache oder einen Rat, eine
Markdown-Tabelle für genaue Werte, `create_chart` für Zahlen zum Ansehen - sodass
„jetzt als Diagramm“ eine Tabelle in ein natives Diagramm verwandelt - und eine
Zeichnung, um zu erklären, wie sich etwas bewegt, ein Werkzeug für den Moment zu
bauen oder Orten auf einer Karte zu folgen. Seine Vorlagen sind ein Diagramm, eine
Erklärung mit Reglern, ein 3D-Flugzeug mit Nicken, Rollen und Gieren, ein Rechner
und eine Reiseroute. Ein leerer Chat mit einem Agent, der zeichnet, öffnet mit je
einem Starter dafür. Wer Visuals im Builder einschaltet, bindet auch Charts.

**Herunterladen.** Eine von der Festplatte geöffnete Datei hat keinen Rahmen um
sich, also trägt der Download mit, was der Rahmen durchgesetzt hat. Ein SVG behält
die Zeichnung und verliert, was laufen oder nach außen greifen könnte: Skripte,
Handler, eingebettete Dokumente und jeden Verweis außerhalb der Datei. Eine Seite
öffnet sich mit der Richtlinie des Rahmens vor allem, was sie geschrieben hat, und
lädt ihre Bibliotheken vom Artefakt-Origin dieses Deployments.

**Als App speichern.** *In Apps speichern* nimmt einen Titel und einen Namen, beide
vorausgefüllt, und veröffentlicht das Visual als Version einer App unter dem Agent,
dessen Turn es gezeichnet hat, in der Umgebung, in der dieser Turn lief, im Besitz der Person, die speichert, und privat, bis
sie es teilt. Der Server baut das Visual aus dem Transkript neu - Überarbeitungen
angewendet - statt Bytes aus dem Browser zu nehmen, sodass die App genau das ist, was
der Agent gezeichnet hat. Unter einem Namen gespeichert, den die Person schon hat, wird
es eine Version dieser App - so aktualisiert eine Überarbeitung einer gespeicherten
Zeichnung die Seite, unter der sie geteilt wurde. Speichern erfordert `artifacts:edit`.

**Aus einem Delegate.** Eine Zeichnung bleibt in dem Run, der sie gemacht hat, also
zeichnet ein Agent, der als Delegate eines anderen Agents arbeitet, nicht: `draw`
sagt es ihm, und er beschreibt das Bild in seinem Ergebnis, damit der Agent, für den
er arbeitet, es im Gespräch zeichnet.

## Wer sie öffnen kann { #who-can-open-it }

Ein neues Artefakt ist **privat** für die Person, für die der veröffentlichende
Run gehandelt hat: die Person im Chat oder der Ersteller eines Triggers. Eine
private Seite sehen außerdem die Rollen Owner, Admin, Builder und Operator: Ihr
`artifacts:view` gilt im Scope `ALL`, sie öffnen also jede Seite der Organisation,
gleich welche Sichtbarkeit und welche Grants sie hat (siehe
[Scopes](permissions.md#scope)). Ein Member oder Viewer öffnet nur, was mit ihm
geteilt ist. Diese vier Rollen gehören immer zur Zielgruppe einer Seite, und jede
Offenlegung nennt sie.

Sein Link - der, auf den die Karte im Chat und die Antwort des Agents zeigen -
öffnet die Seite selbst (von der Karte im Chat aus in einem neuen Tab),
fensterfüllend unter einer Leiste mit Titel, Version und **Share**. Der Link allein lässt niemanden hinein: Er öffnet sich nur für
ein angemeldetes Mitglied, das die Regeln unten bereits hereinlassen. Er nennt
die Organisation, in der die App liegt (`?org=`), sodass ein Mitglied
mehrerer Organisationen in der richtigen landet.

Unter **Share**
kann jeder, der sie verwalten darf, sie auf drei Wegen teilen:

| Reichweite | Wie | Wer |
|---|---|---|
| Bestimmte Personen | Ein Grant, mit `read`, `edit` oder, für eine Seite, `edit_data` („Can edit, including data“) | Diese Mitglieder, in dieser Organisation |
| Die Organisation | Sichtbarkeit auf die ganze Organisation gesetzt | Jedes Mitglied, dessen Rolle geteilte Artefakte erreicht |
| Jeder mit dem Link | **Create a public link** | Jeder, der die Adresse hat, ohne Konto |

Teilen und Sichtbarkeit verwenden dasselbe Panel und dieselben Regeln wie bei
Agents und Skills; siehe [Berechtigungen](permissions.md). Eine App zu
verwalten — sie zu teilen, ihren öffentlichen Link und dessen Einstellungen, eine
Version wiederherzustellen, sie zu löschen — erfordert `artifacts:edit` auf dieser
App, aus der Rolle oder aus einem `edit`-Grant. Sie zu öffnen, erfordert
`artifacts:view`.

Der Agent kann nicht erweitern, wer eine Seite liest. Er veröffentlicht, und
`share_artifact` stellt nur eine Anfrage; eine Person entscheidet, wer sie sieht.
Deshalb verlangt die Capability standardmäßig keine Genehmigung: Eine erste
Veröffentlichung ist privat, und was eine gebundene Seite zeigt, regelt die
[Einwilligung](#consent-the-owner-decides-who-reads-the-data) ihres Besitzers. Ein
Autor, der möchte, dass eine Person jede erneute Veröffentlichung einer bereits
geteilten Seite oder einer gebundenen Seite genehmigt, setzt im Spec
`tool_approval` auf `publish_artifact`. Eine gebundene Seite kann nur ein Run
erneut veröffentlichen, der für ein Mitglied handelt (siehe
[Live-Daten](#live-data)).

### Eine Live-Seite teilen { #sharing-a-live-page }

Eine [Live-Seite](#live-data) zu öffnen zeigt ihre Daten jedem, dem sie
ausgeliefert wird, gelesen mit dem Zugriff des Besitzers statt mit dem eigenen;
zu erweitern, wer sie öffnen kann, ist deshalb die Entscheidung des Besitzers. Der
Besitzer oder für ihn ein Owner oder Admin erweitert es direkt im Share-Dialog,
sobald die Daten bestätigt sind; der Versuch eines anderen Editors wird zu einer
[Anfrage](#share-requests). Einschränken steht jedem Editor offen.
### Der öffentliche Link { #the-public-link }

Ein öffentlicher Link ist `/a/<key>` unter der eigenen Adresse der Konsole, mit
einem zufälligen 192-Bit-Schlüssel — derselben Regel, der auch der Schlüssel der
gehosteten Chat-Seite folgt. Er sagt nichts darüber, wer sie veröffentlicht hat
oder zu welcher Organisation sie gehört.

**Replace the link** stellt einen neuen Schlüssel aus, und der alte öffnet sofort
nichts mehr. **Turn off** entfernt ihn. Beides wird im Audit-Trail festgehalten.
Eine Seite, die jemand bereits geöffnet hat, zeigt weiter, was sie hat, aber beim
erneuten Laden oder wenn ihre Inhaltsadresse erneut geöffnet wird, antwortet sofort
404: Die Adresse nennt den Schlüssel des Links, und die Route prüft diesen Schlüssel
bei jedem Laden. Die eigene Lebensdauer der Adresse, `ARTIFACT_VIEW_TTL_SECONDS`
(standardmäßig fünf Minuten), ist nur die äußere Grenze.

Einem entzogenen Mitglied geht es wie zuvor genauso: Es verliert die App bei seiner
nächsten Anfrage, und eine Seite, die es bereits geöffnet hatte, bleibt
höchstens für dasselbe Zeitfenster.

Unter dem Link hält **Share** seine Einstellungen. Sie bleiben, wenn der Link
ersetzt wird, und ein aus- und wieder eingeschalteter Link behält sie:

| Einstellung | Was sie tut |
|---|---|
| **Stops opening after** | Ein Datum, nach dem der Link nichts mehr öffnet, als wäre er aus |
| **Shows** | Die neueste Version oder eine aufbewahrte Version, angeheftet, damit eine neue Veröffentlichung nicht ändert, was Personen mit dem Link schon gesehen haben. Eine angeheftete Version wird nie entfernt |
| **Password** | Abgefragt, bevor die Seite öffnet. Der Link sagt nichts — weder den Titel noch wann sie veröffentlicht wurde —, bis es stimmt. Als Hash gespeichert, nie wieder angezeigt; jeder Versuch zählt gegen das Rate-Limit des Links. Wer es ändert oder entfernt, beendet die Adressen, die unter dem alten geöffnet wurden: Sie tragen keine Daten |
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

Ein Embed trägt die Daten einer Seite zu denselben Bedingungen wie ihr Link; siehe
[Live-Daten auf einem öffentlichen Link](#live-data-on-a-public-link). Eine Website
hinzuzufügen erweitert, wer diese Daten liest, und löscht daher die Einwilligung für
die Daten.

### Live-Daten auf einem öffentlichen Link { #live-data-on-a-public-link }

Der Ablauf des öffentlichen Links sperrt auch bereits ausgestellte öffentliche Inhaltstoken, bevor Dokumentbytes geladen werden. Ein kurz vor Ablauf ausgestelltes Token verlängert den Link nicht um seine eigene Laufzeit. Mitgliedstoken unterliegen weiterhin dem Mitgliederzugriff und ihrer Tokenlaufzeit.

Eine [gebundene Seite](#live-data) zeigt ihre Datensätze auf ihrem öffentlichen Link
und in ihren Embeds nur, wenn zwei getrennte Entscheidungen getroffen wurden und eine
dritte Prüfung bei jedem Laden besteht. Ohne sie wird die öffentliche Seite wie
veröffentlicht dargestellt, mit jedem Binding auf `unavailable`.

1. **Die Organisation erlaubt es.** Ein Owner oder Admin schaltet **Public pages with
   live data** in den Einstellungen der Organisation ein. Der Schalter ist standardmäßig
   aus, warnt vor dem Einschalten und muss angemeldet als man selbst geändert werden,
   nie im Namen eines anderen. Er ist ein Kill-Switch, kein Reset: Wird er
   ausgeschaltet, verschwinden die Daten auf jeder öffentlichen Seite und in jedem Embed
   beim nächsten Laden, und die eigene Einwilligung jeder Seite bleibt unberührt; wird
   er wieder eingeschaltet, kommen die Seiten zurück, deren Einwilligung noch gilt.
2. **Der Besitzer der Seite bestätigt sie für den Link.** Unter den Einstellungen des
   Links in **Share** öffnet **Confirm data** einen Bildschirm mit dem, was die
   Einwilligung der Mitglieder zeigt - die Seitenabfragen der ausgelieferten Version in
   Worten, jede verknüpfte Tabelle, die sie erreichen - und mit dem, wer es lesen
   kann: jeder mit dem Link, ohne Konto und ohne Anmeldung, ob ein Passwort ihn schützt,
   wann er abläuft und jede einbettende Website. Der Besitzer oder ein Owner oder Admin
   für ihn bestätigt es angemeldet als man selbst; ein `edit`-Grant genügt nicht. Es
   setzt voraus, dass der Link an ist, der Schalter der Organisation an ist und die
   [Einwilligung](#consent-the-owner-decides-who-reads-the-data) der Mitglieder für diese
   Version vorliegt. Jeder mit Bearbeitungsrecht kann sie zurückziehen, angemeldet als
   man selbst; ein Owner oder Admin kann das nicht, indem er jemanden imitiert.
3. **Jede Bedingung gilt bei jedem Laden.** Siehe
   [was ein anonymer Besucher bekommt](#what-an-anonymous-visitor-gets).

Die Bestätigung gilt für die Version, die der Link ausliefert - die angeheftete, sonst
die, die dem Publikum der Seite ausgeliefert wird - und ist an zwei Digests gebunden:
den Fingerabdruck ihrer Seitenabfragen und einen Digest dessen, wen der Link erreicht
(die einbettenden Websites, ob ein Passwort gesetzt ist, ob der Link an ist). Sie wird
mit einem Konflikt abgelehnt, wenn sich eines von beiden geändert hat, nachdem der
Bildschirm gezeichnet wurde. Sie wird unter der Mitgliedschaft des Besitzers
festgehalten und nach Tabellen- und Spaltennamen auditiert, nie nach Zeilen.

#### Was sie aufhebt und was nicht { #what-voids-it-and-what-does-not }

Alles, was das Publikum erweitert oder ändert, wessen Daten es sind, löscht die
Einwilligung, auditiert als `artifact.public_data_voided` mit dem Grund. Sie wieder
einzuschalten erfordert eine neue Bestätigung.

| Hebt die Einwilligung auf | Lässt sie unberührt |
|---|---|
| Den Link ausschalten oder die Seite archivieren | Den Schlüssel des Links ersetzen: Das ändert die Adresse, nicht die Daten |
| Das Passwort entfernen | Das Passwort, den Ablauf des Links oder die angeheftete Version ändern |
| Eine einbettende Website hinzufügen | Eine einbettende Website entfernen |
| Die Seite an einen anderen Besitzer übergeben | Den Schalter der Organisation ausschalten |
| Die Einwilligung der Mitglieder für die Daten zurückziehen | |

Eine andere angeheftete Version oder eine erneute Veröffentlichung, die die
Seitenabfragen ändert, hebt die Einwilligung nicht auf, aber sie gilt dann nicht mehr:
Der Fingerabdruck der ausgelieferten Version passt nicht mehr, sodass die öffentliche
Seite keine Daten zeigt, bis jemand erneut bestätigt. Auch ein abgelaufener Link hält
nichts.

Der Besitzer und die anderen Bearbeiter sehen den Grund in der Leiste über der Seite:
Der Schalter ist aus, der Link liefert keine Version aus, die Abfragen haben sich
geändert, der Besitzer ist gegangen oder hat gewechselt, die Einwilligung der Mitglieder
fehlt oder der Link ist abgelaufen.

#### Was ein anonymer Besucher bekommt { #what-an-anonymous-visitor-gets }

Ein Besucher erfährt nicht, warum. Bevor irgendetwas gelesen wird, prüft jedes Laden,
dass der Link noch den Schlüssel hat, für den die Adresse ausgestellt wurde, dass er
nicht abgelaufen ist, dass der Passwortzustand der ist, unter dem die Adresse geöffnet
wurde, dass die Version noch die ist, die der Link ausliefert, dass der Schalter der
Organisation an ist und dass die Einwilligung der Seite für die Daten und die
Einwilligung der Mitglieder gelten. Schlägt eine fehl, wird die Seite mit jedem Binding
auf `unavailable` und ohne Grund dargestellt.

Dann wird jedes Binding für sich geprüft: Der Besitzer muss noch ein aktives Mitglied
sein, das die Tabelle liest, und die Tabelle darf nicht von der Abfrage abgewichen sein.
Ein Binding, das dort scheitert, ist `unavailable`; die anderen laden trotzdem.

Die Datensätze werden beim Laden in die Seite geschrieben und gelten zum Zeitpunkt
dieses Ladens. Die öffentliche Seite und das Embed haben kein Refresh und keine
Daten-Route, und die Seite kann nicht um mehr bitten; der Besucher lädt neu, um eine
Änderung zu sehen. Ein rotierter oder entfernter Schlüssel ist ein 404, keine Seite
ohne Daten, und ein geändertes oder entferntes Passwort gibt einer alten Adresse eine
Seite ohne Daten.

#### Der Cache und die Obergrenze { #the-cache-and-the-cap }

Ein anonymes Laden kostet Tabellenlesevorgänge, daher werden Lesevorgänge geteilt. Die
Datensätze eines Bindings werden 30 Sekunden lang im Speicher des API-Prozesses
gehalten, geschlüsselt nach Version, Binding, Fingerabdruck der Abfragen und
Mitgliedschaft des Besitzers - **nie in Redis**, weil es Datensätze sind. Jede
Bedingung oben läuft, bevor der Cache gefragt wird, sodass eine ausgeschaltete
Organisation, ein rotierter Schlüssel oder eine zurückgezogene Einwilligung sofort
wirkt, was auch immer gehalten wird. Ein fehlgeschlagener oder nicht verfügbarer
Lesevorgang wird nie gehalten.

Der Speicher ist begrenzt: `ARTIFACT_PUBLIC_DATA_CACHE_BYTES` (standardmäßig 32 MiB)
und 64 Lesevorgänge pro Prozess, wobei der am längsten nicht genutzte zuerst fällt;
ein Lesevorgang, der größer als das Budget ist, wird nicht gehalten. Davon getrennt
darf jede Seite `RATE_LIMIT_ARTIFACT_PUBLIC_DATA_PER_MINUTE` Mal pro Minute (60) über
alle ihre Besucher aus ihren Tabellen lesen. Ein Laden, das aus den Tabellen lesen
muss, zählt einmal, sodass eine stark besuchte Seite durch die Obergrenze begrenzt
ist und nicht durch ihr Publikum. Darüber hinaus, oder solange der Prozess bereits so
viele Daten-Ladevorgänge bedient, wie er darf, kommt ein Binding, das einen
Lesevorgang braucht, für diesen Besucher als `unavailable` zurück.

## Wie die Seite isoliert wird { #how-the-page-is-isolated }

Eine App ist HTML mit Skript darin, geschrieben von einem Modell, das
möglicherweise etwas Feindseliges gelesen hat. Sie wird so ausgeliefert, dass
nichts, was sie tut, die Konsole oder die Person erreichen kann, die sie ansieht:

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
  dem Inhalts-Origin, für Skripte, Stile und Schriften. Auf einem Deployment, das `VISUAL_MAP_TILES` setzt, kommen Bilder aus seinem eigenen Kachelpfad hinzu, `/api/v1/artifact-content/tiles/{z}/{x}/{y}`. Diese Route nimmt drei Zahlen, jede gegen die Zoomstufe geprüft, auf der es sie geben kann, und holt die Kachel selbst, sodass eine Seite weder Adresse noch Schlüssel des Kachelservers erfährt und ihm nichts schicken kann, was sie selbst gewählt hat. `frame-ancestors` nennt nur
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
  Seite und der Adresse, an die sie ihre Zahlen schicken würde. Eine [Folgenachricht](#visuals) ist dieselbe Art Bitte: die Konsole zeigt den Text, und ein Mensch sendet ihn.
- Live-Daten erreichen die Seite eines Mitglieds auf zwei Wegen, beide pro
  Betrachter auf dem Server entschieden. Beim Laden schreibt die Content-Route die
  Datensätze jedes Bindings in das Plattform-Skript der Seite, für das Mitglied,
  das die signierte Adresse nennt; eine Aktualisierung kommt per `postMessage` von
  der Konsole, die sie mit der eigenen Session des Betrachters von der Daten-Route
  abruft. Die Anfrage der Seite trägt eine Nonce, mit der die Konsole jede Antwort
  dem richtigen Laden der Seite zuordnet; das ist **Korrelation, keine
  Zugriffskontrolle**. Ein öffentlicher Link oder ein Embed bekommt seine Daten nur
  beim Laden, vom Server eingeschrieben, und fragt nie danach: Er hat keine
  Daten-Route und kein Refresh. Siehe
  [Live-Daten auf einem öffentlichen Link](#live-data-on-a-public-link) und
  [die Sicherheitsseite](security.md#a-pages-data-and-its-address).
- Eine Seite kann über dieselbe Brücke mit `agenticos.run` darum bitten, einen
  [Workflow](#actions) zu starten, und nur der Seitenbetrachter der Konsole bietet das an:
  Die Adresse trägt das Recht zu fragen, und ein öffentlicher Link, ein Embed, eine
  Vorschau und ein Thumbnail weisen den Aufruf sofort ab. Die Anfrage ist wieder **nur
  eine Anfrage**. Die Konsole nimmt sie von ihrem eigenen Frame unter der Nonce dieses
  Ladens an, ordnet sie einer Aktion zu, die der Server für diesen Betrachter und die
  ausgelieferte Version aufgeführt hat, und fragt die Person in einem Dialog, bevor
  irgendetwas startet. Der Run gehört dann ihr, sodass eine per Prompt Injection
  manipulierte Seite die Person eine Frage lesen lassen kann, sie aber nie für sie
  beantwortet.
- Eine signierte Adresse lädt ihre Seite höchstens einige Male pro Minute,
  gezählt pro Adresse, bevor irgendetwas gelesen wird. Die Konsole und die
  öffentliche Seite stellen jedes Mal eine frische Adresse aus, wenn sie den
  Frame zeichnen, und das Ausstellen über einen öffentlichen Link ist selbst pro
  Link begrenzt.

Die Liste **Apps** zeichnet die aktuelle Seite jeder Karte als
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
- **Listen.** Die Liste Apps und das Dashboard-Widget lassen sie weg. Wählen
  Sie in der Liste **Archived included**, um sie zu sehen, markiert als
  **Archived**. Dort sehen sie nur diejenigen, die sie bearbeiten dürfen.
- **Der öffentliche Link und die Einbettung.** Beide öffnen nichts.
- **Der Agent.** `publish_artifact` lehnt den Namen mit einer Meldung ab, die das
  Archiv nennt, sodass ein Run keine zweite Seite unter ihm anlegen kann.
  `read_artifact`, `preview_artifact` und `list_artifacts` behandeln die Seite
  als nicht vorhanden. Ein Run, der die Seite nicht bearbeiten darf, erfährt nur,
  dass der Name nicht seiner ist.

Archivieren schaltet den öffentlichen Link aus, auditiert als
`artifact.public_link_disabled`, und löscht seine
[Einwilligung für die Daten](#what-voids-it-and-what-does-not). Wiederherstellen
schaltet keines von beidem wieder ein. Eine vor dem Archivieren verschickte Adresse
bleibt tot, bis jemand unter **Share** eine neue erstellt. Ablaufdatum, angeheftete Version, Passwort und
Einbettungs-Websites des Links bleiben dafür erhalten.

Über die API archiviert `POST /api/v1/artifacts/{id}/archive` eine Seite, und ein
erneutes Archivieren ändert nichts. `POST /api/v1/artifacts/{id}/unarchive` stellt
sie wieder her und antwortet bei einer nicht archivierten Seite mit `400`. Beide
verlangen das Recht, diese Seite zu bearbeiten, ein Grant eingeschlossen.
`GET /api/v1/artifacts` listet archivierte Seiten, für die, die sie bearbeiten
dürfen, nur mit `include_archived=true`, und `archived_at` an jeder Seite sagt,
wann sie archiviert wurde.

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
jeden Kanal schalten Sie unter **Einstellungen → Benachrichtigungen → App
aktualisiert** ab.

## Aufbewahrung und Löschung { #retention-and-deletion }

Apps sind eine eigene [Aufbewahrungsklasse](governance.md#the-classes),
gemessen ab der **letzten Veröffentlichung** — ein Bericht, der jede Woche neu
veröffentlicht wird, lebt, wie alt seine erste Version auch ist. Wie jede Klasse
behält sie Apps für immer, bis eine Organisation oder das Deployment eine
Frist setzt.

Eine App zu löschen — von Hand oder durch die Aufbewahrung — entfernt jede
Version, ihre gespeicherten Bytes, ihre Grants und ihren öffentlichen Link. Eine
archivierte Seite altert und wird gelöscht wie jede andere. Den Agent zu löschen, löscht seine Apps nicht: Sie bleiben lesbar und haben
einfach keinen Herausgeber mehr. Eine benannte Umgebung zu löschen, tut dasselbe
mit den Seiten, die aus ihr veröffentlicht wurden, sodass sie nie auf der
gleichnamigen Seite der Standardumgebung landen. Die Organisation zu löschen,
entfernt sie. Die Apps einer gelöschten Person bleiben und verlieren ihren
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
- **Alle lesen die Sicht des Besitzers auf die Daten.** Eine Seitenabfrage wird mit
  dem Zugriff des Besitzers gelesen, eine Seite ist also für Daten gedacht, die
  jeder sehen darf, der sie öffnen kann. Eine Seitenabfrage hat keine
  Freitextsuche, keinen Filter pro Betrachter wie „ich“ oder „heute“ und keine
  Begrenzung auf Zeilen- oder Spaltenebene über die Abfrage selbst hinaus.
- **Ein öffentlicher Link oder ein Embed bekommt Daten erst nach zwei
  Bestätigungen.** Die Organisation muss es erlauben, und der Besitzer der Seite muss
  es für den Link bestätigen; bis dahin zeigt eine gebundene Seite dort
  „unavailable“. Was sie zeigt, gilt zum Zeitpunkt des Ladens, ohne Refresh, bis zu 30
  Sekunden alt, und wird mit dem Zugriff des Besitzers für Personen gelesen, die der
  Besitzer nicht kennt. Ein Deployment, das das nicht akzeptieren kann, lässt den
  Schalter aus. Siehe [Live-Daten auf einem öffentlichen Link](#live-data-on-a-public-link).
- **Eine Seite handelt nur über ihre deklarierten Aktionen.** Ein Formular oder ein Knopf
  hat keinen Ort, an den es senden könnte, was es sammelt, außer um einen von bis zu
  fünf Workflows zu starten, die ihr Veröffentlichender deklariert hat, die die Person
  jedes Mal bestätigt und die als sie laufen. Sie kann selbst keine API aufrufen, keinen
  Datensatz schreiben und keine Nachricht senden, und sie bekommt nur Status und Antwort
  eines Runs zurück. Siehe [Aktionen](#actions).
- **Eine offene Seite überdauert einen entzogenen Grant um eine Lebensdauer der
  signierten Adresse**, standardmäßig fünf Minuten. Einen öffentlichen Link
  auszuschalten oder seinen Schlüssel zu ersetzen beendet sie beim nächsten Laden.
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
- **Ein Visual wird nur im Web-Chat und in einem geteilten Thread gezeichnet.** Eine
  Chat-App bekommt ein Bild davon, wo `VISUAL_RENDER_CDP_URL` einen Browser nennt,
  sonst seinen Titel; das Widget und eine Einbettung auf einer anderen Website
  zeigen seinen Titel.
- **Ein geteilter Thread zeigt seine zwölf neuesten Visuals**, zusammen höchstens
  16 MB. Wer den Link hat, kann ihn beliebig oft öffnen, also ist ein Aufruf
  begrenzt; ein Turn jenseits einer der Grenzen behält seinen Text und zeigt keine
  Zeichnung.

## Zusammenfassung { #recap }

- Eine Capability, fünf Tools: `publish_artifact`, aus einer Workspace-Datei,
  inline oder als Änderungen; `read_artifact`, um eine Seite zurückzulesen;
  `list_artifacts`, um eine zu finden; `preview_artifact`, um sie gezeichnet zu
  sehen, mit ihren Fehlern; und `share_artifact`, um darum zu bitten, dass eine
  Seite geteilt wird.
- Der Agent, die Umgebung und der Name sind die Identität; erneutes
  Veröffentlichen behält den Link und fügt eine Version hinzu, und jede
  aufbewahrte Version lässt sich wiederherstellen.
- Standardmäßig privat; geteilt mit Grants, der Organisation oder einem
  öffentlichen Link, durch eine Person. Der öffentliche Link kann ablaufen, eine
  Version anheften, nach einem Passwort fragen und auf aufgeführten Websites
  eingebettet werden.
- Eine Seite kann sich an eine Seitenabfrage binden - eine Tabelle, Filter, eine
  Sortierung, ein Limit und Felder - und Live-Daten zeigen, gelesen beim Ansehen
  mit dem Zugriff ihres Besitzers, erst nachdem der Besitzer das Teilen bestätigt
  hat, und nie in der Seite gespeichert. Jeder mit Bearbeitungsrecht kann diese
  Einwilligung zurückziehen; zu erweitern, wer eine gebundene Seite öffnen kann,
  entscheidet der Besitzer, sonst gibt es eine Anfrage. Ein öffentlicher Link oder ein
  Embed zeigt die Daten nur, wenn ein Owner oder Admin es für die Organisation erlaubt
  und der Besitzer es für den Link bestätigt hat, und wer das Publikum des Links
  löscht, löscht diese Bestätigung.
- Eine Seite kann bis zu fünf Workflows deklarieren, die ein Agent gebunden hat; ihre
  Knöpfe bitten die Konsole mit `AO.run`, einen zu starten, und der Betrachter bestätigt
  jeden Run in einem Dialog, der den echten Workflow nennt und jeden Wert zeigt. Der Run
  gehört dem Betrachter, mit dem Trigger `app`, und die Seite liest nur Status und Antwort
  zurück.
- Der Besitzer kann eine Seite an ein anderes Mitglied übergeben, das ihre Daten
  erneut bestätigen muss.
- Ein kurzer Seitenvertrag in den Anweisungen jedes Agents mit Artifacts und
  Warnungen im Ergebnis der Veröffentlichung für das, was im Markup falsch
  aussieht.
- Ausgeliefert von einer Route ohne Cookies in einem opaken Origin ohne Netzwerk
  außer dem eigenen Bibliothekssatz des Deployments, mit Links, die vor dem
  Öffnen fragen, und optional von einer eigenen Domain.
- Archivieren behält eine Seite und liefert nichts von ihr aus, den öffentlichen
  Link ausgeschaltet, bis jemand, der sie bearbeiten darf, sie wiederherstellt.
- Eine eigene Aufbewahrungsklasse, gemessen ab der letzten Veröffentlichung.
