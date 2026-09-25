---
source_sha: "2106ff45a345"
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

Schalten Sie für den Agent die Capability **Artifacts** ein. Sie fügt ein Tool
hinzu, `publish_artifact`, und das Modell ruft es auf, wenn das Ergebnis etwas
ist, das eine Person öffnen sollte, statt es einmal im Chat zu lesen.

Die Seite kommt von einer von zwei Stellen:

- **Eine Datei im Workspace des Agents**, die auf `.html` oder `.md` endet. Das
  ist der übliche Fall für einen Agent mit der Capability
  [Dateien & Shell](reference/capabilities.md#files-shell): Er schreibt
  `report.html`, führt aus, was auch immer sie baut, und veröffentlicht dann die
  Datei. Die Bytes werden über das eigene Workspace-Backend des Runs gelesen,
  deshalb funktioniert das auf jedem Sandbox-Backend.
- **Die Seite inline übergeben**, für einen Agent ohne Workspace oder eine kurze
  Seite.

Der Chat zeigt eine Karte für die veröffentlichte Seite. Die Karte verlinkt auf
die Version, die *dieser* Run veröffentlicht hat, sodass ein späteres Lesen der
Unterhaltung weiterhin zeigt, was darin veröffentlicht wurde, und nicht, was die
Seite heute zeigt.

## Ein Name, ein Link { #one-name-one-link }

Die Identität eines Artefakts ist sein **Name innerhalb des Agents** —
`weekly-report`, `churn-dashboard`. Wer unter demselben Namen veröffentlicht,
aktualisiert dasselbe Artefakt, von jeder Oberfläche aus: dem Chat, der API,
einem [Trigger](triggers.md) oder einem Workflow. Ein neuer Name ergibt eine neue
Seite. Der Name besteht aus Kleinbuchstaben, Ziffern und Bindestrichen, bis zu
64 Zeichen.

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
  hinzukommt. Eine Unterhaltung, die auf eine entfernte Version verlinkt, sagt,
  dass die Version nicht mehr aufbewahrt wird, und bietet die neueste an.

## Unterstützte Formate { #supported-formats }

| Format | Was gespeichert wird | Was ausgeliefert wird |
|---|---|---|
| HTML (`.html`, `.htm` oder `format: html`) | Das Dokument, wie der Agent es geschrieben hat | Dasselbe Dokument |
| Markdown (`.md`, `.markdown` oder `format: markdown`) | Die Markdown-Quelle | Die Quelle, gerendert zu einer schlichten Seite, Tabellen eingeschlossen. Rohes HTML darin wird maskiert |

Eine Version ist ein in sich geschlossenes Dokument von höchstens
`ARTIFACT_MAX_BYTES` (standardmäßig 5 MiB). Es gibt keine Bündel aus mehreren
Dateien: Betten Sie das Stylesheet, das Skript und die Bilder (als `data:`-URIs)
in die eine Datei ein.

!!! warning "Die Seite hat kein Netzwerk"

    Skripte laufen, ein von einer eingebetteten Bibliothek gezeichnetes Diagramm
    funktioniert also. Aber die Seite kann nichts von irgendwoher laden und
    nichts irgendwohin senden — ein CDN-Skript, eine Webschrift von einer URL
    und ein API-Aufruf schlagen alle fehl. Das Tool sagt das dem Modell. Es ist
    Absicht, und der nächste Abschnitt sagt, warum.

## Wer es öffnen kann { #who-can-open-it }

Ein neues Artefakt ist **privat** für die Person, für die der veröffentlichende
Run gehandelt hat: die Person im Chat oder der Ersteller eines Triggers. Von
seiner Seite unter **Artifacts** aus kann jeder, der es verwalten darf, es auf
drei Wegen teilen:

| Reichweite | Wie | Wer |
|---|---|---|
| Bestimmte Personen | Ein Grant, mit `read` oder `edit` | Diese Mitglieder, in dieser Organisation |
| Die Organisation | Sichtbarkeit auf die ganze Organisation gesetzt | Jedes Mitglied, dessen Rolle geteilte Artefakte erreicht |
| Jeder mit dem Link | **Create a public link** | Jeder, der die Adresse hat, ohne Konto |

Teilen und Sichtbarkeit verwenden dasselbe Panel und dieselben Regeln wie bei
Agents und Skills; siehe [Berechtigungen](permissions.md). Ein Artefakt zu
verwalten — es zu teilen, seinen öffentlichen Link, es zu löschen — erfordert
`artifacts:edit` auf diesem Artefakt, aus der Rolle oder aus einem `edit`-Grant.
Es zu öffnen, erfordert `artifacts:view`.

Der Agent kann nicht erweitern, wer eine Seite liest. Er veröffentlicht; eine
Person entscheidet, wer sie sieht. Deshalb verlangt die Capability standardmäßig
keine Genehmigung: Eine erste Veröffentlichung ist privat. Ein Autor, der möchte,
dass eine Person jede erneute Veröffentlichung einer bereits geteilten Seite
genehmigt, setzt im Spec `tool_approval` auf `publish_artifact`.

### Der öffentliche Link { #the-public-link }

Ein öffentlicher Link ist `/a/<key>` unter der eigenen Adresse der Konsole, mit
einem zufälligen 192-Bit-Schlüssel — derselben Regel, der auch der Schlüssel der
gehosteten Chat-Seite folgt. Er zeigt immer die neueste Version und sagt nichts
darüber, wer sie veröffentlicht hat oder zu welcher Organisation sie gehört.

**Replace the link** stellt einen neuen Schlüssel aus, und der alte öffnet sofort
nichts mehr. **Turn off** entfernt ihn. Beides wird im Audit-Trail festgehalten.
Eine Seite, die jemand bereits geöffnet hat, wird weiter angezeigt, bis ihre
signierte Inhaltsadresse abläuft, höchstens `ARTIFACT_VIEW_TTL_SECONDS`
(standardmäßig fünf Minuten).

Einem entzogenen Mitglied geht es genauso: Es verliert das Artefakt bei seiner
nächsten Anfrage, und eine Seite, die es bereits geöffnet hatte, bleibt
höchstens für dasselbe Zeitfenster.

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
- Auch `allow-popups` fehlt. `connect-src` regelt keine Navigation, ein Link,
  der ein neues Fenster öffnet, wäre also ein Weg, das, was die Seite zeigt, an
  eine Adresse ihrer Wahl zu schicken. Ein Link in der Seite öffnet sich in
  ihrem eigenen Frame, und das `frame-src` der Konsole lehnt jeden Origin außer
  dem Inhalts-Origin ab.
- Dieselbe Policy setzt `default-src 'none'` und `connect-src 'none'` ohne
  entfernte Quelle, und `frame-ancestors` nennt nur die Konsole. Der Frame in
  der Konsole trägt dieselbe `sandbox`-Liste als zweites Schloss.
- Eine signierte Adresse lädt ihre Seite höchstens einige Male pro Minute,
  gezählt pro Adresse, bevor irgendetwas gelesen wird. Die Konsole und die
  öffentliche Seite stellen jedes Mal eine frische Adresse aus, wenn sie den
  Frame zeichnen, und das Ausstellen über einen öffentlichen Link ist selbst pro
  Link begrenzt.

Darüber hinaus kann ein Deployment Inhalte von einer **separaten registrierbaren
Domain** ausliefern, indem es `ARTIFACT_ORIGIN` setzt — zum Beispiel
`https://agenticos-content.example.net`, auf dieselbe API geroutet. Die Seite
liegt dann auf einer ganz anderen Site. Der opake Origin isoliert sie bereits,
das ist also eine Härtung, die ein Security-Review verlangen kann, keine
Voraussetzung. Setzen Sie die Variable für das Backend und für das Frontend, das
diesen Origin zu seinem `frame-src` hinzufügt. Siehe
[Konfiguration](configuration.md#published-artifacts).

## Aufbewahrung und Löschung { #retention-and-deletion }

Artefakte sind eine eigene [Aufbewahrungsklasse](governance.md#the-classes),
gemessen ab der **letzten Veröffentlichung** — ein Bericht, der jede Woche neu
veröffentlicht wird, lebt, wie alt seine erste Version auch ist. Wie jede Klasse
behält sie Artefakte für immer, bis eine Organisation oder das Deployment eine
Frist setzt.

Ein Artefakt zu löschen — von Hand oder durch die Aufbewahrung — entfernt jede
Version, ihre gespeicherten Bytes, ihre Grants und ihren öffentlichen Link. Den
Agent zu löschen, löscht seine Artefakte nicht: Sie bleiben lesbar und haben
einfach keinen Herausgeber mehr. Die Organisation zu löschen, entfernt sie. Die
Artefakte einer gelöschten Person bleiben und verlieren ihren Besitzer, so wie
ihre Agents und Skills.

Die Bytes liegen im [Dateispeicher](configuration.md#uploaded-files-at-rest) des
Deployments, unter `artifacts/<organization>/<artifact>/`.

## Einschränkungen { #limitations }

- **Ein in sich geschlossenes Dokument pro Version.** Keine Bündel und kein
  Netzwerk aus der Seite heraus.
- **Keine Live-Daten.** Ein Dashboard zeigt die Daten, mit denen es
  veröffentlicht wurde. Es aktualisiert sich, wenn der Agent erneut
  veröffentlicht — ein Zeitplan ist der übliche Weg.
- **Der Agent kann seine Artefakte nicht zurücklesen.** Ein Bericht wird aus
  seinen Daten neu gebaut, nicht aus der letzten Version bearbeitet.
- **Eine offene Seite überdauert einen Entzug um eine Lebensdauer der signierten
  Adresse**, standardmäßig fünf Minuten.
- **Links in einer Seite öffnen kein neues Fenster.** Ein Link auf eine andere
  Site lädt nicht im Frame, nach derselben Regel, die die Seite vom Netzwerk
  fernhält.
- **Entfernte Versionen sind weg.** Eine Unterhaltung, die auf eine Version
  verlinkt, die älter als das aufbewahrte Fenster ist, kann nur die neueste
  anbieten.

## Zusammenfassung { #recap }

- Eine Capability, ein Tool: `publish_artifact`, aus einer Workspace-Datei oder
  inline.
- Der Agent und der Name sind die Identität; erneutes Veröffentlichen behält den
  Link und fügt eine Version hinzu.
- Standardmäßig privat; geteilt mit Grants, der Organisation oder einem
  öffentlichen Link, durch eine Person.
- Ausgeliefert von einer Route ohne Cookies in einem opaken Origin ohne
  Netzwerk, und optional von einer eigenen Domain.
- Eine eigene Aufbewahrungsklasse, gemessen ab der letzten Veröffentlichung.
