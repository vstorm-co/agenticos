---
source_sha: "35f32898440e"
---

# Virtual Tables { #virtual-tables }

Eine **Virtual Table** ist eine typisierte Tabelle mit Datensätzen, die eine
Organisation für ihre Agents, [Workflows](workflows.md) und Integrationen führt: abzugleichende
Bestellungen, zu verarbeitende Dateien, nachzufassende Leads.

Tabellen sind Metadaten plus JSONB. Nichts legt eine physische SQL-Tabelle an: Eine
Tabelle zu erstellen kostet eine Zeile, das Umbenennen einer Spalte ändert keinen
Datensatz, und kein Tenant kann den Datenbankkatalog wachsen lassen. Jeder Lese- und
Schreibzugriff läuft über einen einzigen Service, `VirtualTableService`, sodass die
Konsole, Agent-Tools, Workflow-Knoten und die öffentliche API dieselben Regeln teilen.
Diese Seite beschreibt den Service und seine HTTP-Routen unter `/api/v1/tables`; das
OpenAPI-Dokument ist ihr Vertrag.

## Wie eine Tabelle aufgebaut ist { #how-a-table-is-built }

| Teil | Was es ist | Identität |
|---|---|---|
| **Table** | Ein Name, ein Besitzer, eine Sichtbarkeit und Grants, wie bei einer [Context-Datei](context.md) | `id`, stabil |
| **Schema version** | Ein unveränderlicher Schnappschuss der Spalten. Eine Änderung hängt Version N+1 an | `version` |
| **Column** | Eine Bezeichnung, ein Typ, ob sie leer sein darf, ein optionaler Standardwert | `id`, stabil |
| **Option** | Eine Auswahl einer Select-Spalte | `id`, stabil |
| **Record** | Zellwerte, nach Spalten-id geordnet, eine Revision und eine optionale `external_id` | `id`, stabil |

Werte werden über die **id** der Spalte adressiert, nie über ihre Bezeichnung. Ein
Umbenennen schreibt daher eine Schema-Version um und keinen Datensatz. Ein Datensatz
merkt sich die Schema-Version, unter der er zuletzt geschrieben wurde.

Ein Datensatz speichert nur die Zellen, die einen Wert enthalten. Eine Zelle, die als
`null` gesendet wird, wird geleert, und ein Lesezugriff zeigt für sie nichts an. Bei einem
Create füllt der Standardwert einer Spalte nur die Zellen, die Sie weglassen; eine Zelle,
die Sie als `null` senden, bleibt leer.

## Spaltentypen { #column-types }

| Typ | Gespeichert als | Filter |
|---|---|---|
| `text` | Text bis 1.000 Zeichen | `eq` `ne` `contains` `starts_with` `in` `is_null` |
| `long_text` | Text bis 100.000 Zeichen | wie `text` |
| `number` | Eine endliche Zahl | `eq` `ne` `lt` `lte` `gt` `gte` `in` `is_null` |
| `integer` | Eine ganze Zahl, höchstens 2^53 - 1 | wie `number` |
| `boolean` | `true` oder `false` | `eq` `ne` `is_null` |
| `date` | `YYYY-MM-DD` | wie `number` |
| `datetime` | ISO 8601 mit Zeitzone, als UTC gespeichert | wie `number` |
| `single_select` | Die id einer Option | `eq` `ne` `in` `is_null` |
| `multi_select` | Eine Liste von Options-ids | `contains` `is_null` |

Text wird genau so gespeichert, wie er gesendet wurde. Führende und nachgestellte
Leerzeichen, Zeilenumbrüche und Werte, die nur aus Leerzeichen bestehen, sind Daten des
Benutzers und werden deshalb nicht beschnitten. Es gilt nur eine Längenbegrenzung, und
das NUL-Zeichen wird abgelehnt, in Zellen ebenso wie in Namen, Bezeichnungen,
Beschreibungen und external ids, weil PostgreSQL es nicht speichern kann.

Vergleiche treffen nur Zellen, die einen Wert enthalten. Mit `is_null` finden Sie die
leeren.

## Ein Schema ändern { #changing-a-schema }

`PUT /tables/{id}/schema` nimmt die vollständige Liste der Spalten entgegen, die die
Tabelle haben soll, und die `expected_version`, die der Aufrufer zuletzt gelesen hat.
Der Service gleicht sie mit den aktuellen Spalten ab:

- Eine Spalte mit `id` ist diese Spalte. Eine Spalte ohne `id` ist neu.
- Der **Typ einer Spalte ändert sich nie**, weil die darunter gespeicherten Werte sonst
  nicht mehr bedeuten würden, was sie bedeutet haben. Fügen Sie stattdessen eine neue
  Spalte hinzu.
- Nichts wird gelöscht. Eine weggelassene Spalte oder Option wird **archiviert**: Ihre
  Werte bleiben les- und filterbar, und ein Schreibzugriff darauf wird mit
  `ARCHIVED_COLUMN` abgelehnt.
- Archivierte zählen zu den Grenzen. Eine Tabelle hat höchstens 100 Spalten und eine
  Select-Spalte höchstens 100 Optionen, Archivierte eingeschlossen. Eine Änderung, die eine
  davon überschreiten würde, wird mit `INVALID_SCHEMA` abgelehnt und hängt keine Version an;
  eine volle Liste von Optionen lässt sich also nicht ersetzen. Fügen Sie stattdessen eine
  neue Spalte hinzu.
- Eine neue Pflichtspalte braucht einen Standardwert, weil bestehende Datensätze
  nichts für sie enthalten. Eine bestehende Spalte kann nicht zur Pflichtspalte werden,
  solange ein Datensatz keinen Wert für sie hat, und eine Pflichtspalte kann ohne
  Standardwert nicht aus dem Archiv zurückkehren, weil Datensätze, die während der
  Archivierung geschrieben wurden, keinen halten konnten.
- Eine veraltete `expected_version` ergibt `SCHEMA_VERSION_CONFLICT`.
- Eine Übermittlung, die den aktuellen Spalten entspricht, mit denselben ids, derselben
  Reihenfolge, denselben Bezeichnungen und Optionen, ändert nichts: Es wird keine Version
  angehängt, und die aktuelle Tabelle wird zurückgegeben. Eine neue Reihenfolge oder eine
  geänderte Bezeichnung ist eine Änderung.

Datensätze werden nicht umgeschrieben. Ein unter Version 1 geschriebener Datensatz
bleibt unter Version 4 lesbar und bearbeitbar; eine Pflichtspalte, die er nie hatte,
erhält beim nächsten Bearbeiten des Datensatzes ihren Standardwert.

Ein Schreibzugriff auf einen Datensatz und eine Schemaänderung oder Archivierung derselben
Tabelle kommen nacheinander dran: Der Schreibzugriff wartet auf eine laufende und wird
dann an dem gemessen, was sie committet hat, sodass ein Datensatz nie in einer Tabelle
landet, die einen Moment zuvor archiviert wurde.

Beim Archivieren einer Spalte oder der ganzen Tabelle wird zuerst jeder registrierte
Dependency-Checker gefragt, ob etwas, das der Aufrufer sowohl sehen als auch ändern
kann, sie noch verwendet.
Heute sind gespeicherte Ansichten registriert (siehe
[Gespeicherte Ansichten](#saved-views)); Workflows und Trigger werden ihre in
`app/services/virtual_tables/dependencies.py` registrieren. Eine Ablehnung nennt die
Abhängigen in `SCHEMA_DEPENDENCY`. Jeder andere Abhängige wird nie genannt und
blockiert den Aufrufer nie: sein Feature kommt stattdessen selbst mit der Änderung
zurecht.

## Datensätze und Revisions { #records-and-revisions }

Jeder Datensatz hat eine `revision`, die bei 1 beginnt und mit jeder Änderung steigt.

| Operation | Route | Braucht `expected_revision` |
|---|---|---|
| Erstellen | `POST /tables/{id}/records` | Nein |
| Genannte Zellen ändern | `PATCH /tables/{id}/records/{record_id}` | Ja |
| Löschen | `DELETE /tables/{id}/records/{record_id}?expected_revision=` | Ja |
| Upsert | `PUT /tables/{id}/records/by-external-id/{external_id}` | Nur wenn der Datensatz existiert |
| Lesen, exists | `GET .../records/{record_id}`, `.../by-external-id/{external_id}`, `.../exists` | Nein |

Ein Update oder Delete mit einer alten Revision wird mit `REVISION_CONFLICT` (409) und
`details.current_revision` abgelehnt; nichts wird überschrieben. Lesen Sie den Datensatz
erneut und versuchen Sie es noch einmal. Ein Upsert, der einen bestehenden Datensatz findet
und kein `expected_revision` erhält, bekommt `REVISION_REQUIRED` (428), wieder mit der
zu sendenden Revision.

Eine external id hat 1 bis 255 Zeichen und darf `/` enthalten, wie in `2026/ORD-1`. Sie darf weder NUL noch einen Zeilenumbruch enthalten. Der Service
prüft das ebenso wie die Routen. Über HTTP lehnt die Route es zuerst ab, mit
`VALIDATION_ERROR`; ein Aufrufer, der den Service direkt nutzt, erhält `INVALID_RECORD`.

Gleichzeitige Upserts derselben external id erzeugen einen Datensatz. Der Verlierer
findet ihn und wird wie ein Update beantwortet: Er braucht die Revision oder erfährt,
welche er senden muss.

Ein Update, das jede Zelle unverändert ließe, ändert nichts. Die Revision bleibt, es wird
keine Historienzeile und kein Receipt geschrieben, und der aktuelle Datensatz wird
zurückgegeben. Eine veraltete `expected_revision` ist weiterhin ein Konflikt, weil sie
zuerst geprüft wird. Ein Upsert, der den Datensatz findet, folgt derselben Regel.

Ein Delete ist ein hartes Löschen. Die Historie des Datensatzes bleibt, bis ihre Aufbewahrung sie entfernt.

## Sichere Wiederholungen { #safe-retries }

Jeder Schreibzugriff auf Datensätze akzeptiert einen `Idempotency-Key`-Header (höchstens
128 Zeichen). Eine Wiederholung mit demselben Schlüssel und demselben Body liefert die
erste Antwort mit `Idempotent-Replayed: true` und schreibt nichts, selbst wenn sich der
Datensatz inzwischen geändert hat. Derselbe Schlüssel mit einem anderen Body wird mit
`IDEMPOTENCY_KEY_REUSED` abgelehnt.

Der Header kennzeichnet ein wiederholtes Create, Update oder Upsert. Ein wiederholtes
Delete antwortet wie beim ersten Mal mit 204 und wird nicht gekennzeichnet.

Ein Schlüssel gehört dem Aufrufer und der Art des Schreibzugriffs, sodass zwei Aufrufer
dieselbe Zeichenfolge verwenden können und ein Aufrufer sie für ein Create und ein
Upsert nutzen kann. Nur Erfolge werden gespeichert: Ein abgelehnter Schreibzugriff
hinterlässt keine Quittung; Sie korrigieren ihn also und wiederholen ihn mit demselben
Schlüssel.

Eine Wiederholung wird nur einem Aufrufer beantwortet, der die Tabelle noch bearbeiten
darf. Nach dem Entzug des Zugriffs ist dieselbe Wiederholung ein 404.

Ein Receipt hält 24 Stunden. Danach ist der Schlüssel vergessen, und derselbe Schlüssel mit
demselben Body ist ein neuer Schreibzugriff: Er wird erneut ausgeführt, statt die erste
Antwort zurückzugeben. Wiederholen Sie innerhalb des Fensters und behandeln Sie eine
längere Pause als neue Anfrage. Die Lebensdauer wird beim Verwenden des Schlüssels
durchgesetzt und gilt daher auf die Stunde genau; der tägliche Sweep gibt nur den Platz
von Receipts frei, die niemand wiederholt hat.

## Auflisten und Filtern { #listing-and-filtering }

`GET /tables/{id}/records` blättert durch eine Tabelle; `POST /tables/{id}/records/query`
fügt typisierte Filter hinzu, die alle zutreffen müssen. Beide sind begrenzt: `limit`
liegt zwischen 1 und 100, `skip` bei höchstens 10.000, und eine Abfrage hat höchstens 20
Filter.

Die Reihenfolge ist total. Auf die gewünschte Sortierung (`created_at`, `updated_at`
oder eine sortierbare Spalte) folgt die Datensatz-id, sodass eine Seite in einer
unveränderten Tabelle nie einen Datensatz wiederholt oder überspringt. Datensätze ohne
Wert in der sortierten Spalte kommen in beiden Richtungen zuletzt. Eine
`multi_select`-Spalte lässt sich nicht sortieren. `updated_at` wird beim Erstellen eines
Datensatzes gesetzt und rückt mit jeder Bearbeitung vor, sodass Datensätze, die niemand
bearbeitet hat, nach ihrer Erstellungszeit sortieren.

Es gibt kein `total`, weil das Zählen einer gefilterten Tabelle nicht billig ist.
`has_more` sagt, ob eine weitere Seite folgt.

## Gespeicherte Ansichten { #saved-views }

Eine **Ansicht** ist ein gespeicherter Filter, eine Sortierung und eine Gruppierung
über die Datensätze einer Tabelle - was die Tabellen-/Kanban-/Listenansichten der
Konsole speichern, damit niemand bei jedem Besuch dasselbe Board neu aufbaut. Sie
ist eine Unterressource der Tabelle, keine eigene teilbare Ressource: Eine Ansicht
hat keinen eigenen Besitzer und keine eigenen Grants ihrer Art, und `shared`
bedeutet nur "sichtbar für jeden, der bereits `tables:view` auf der übergeordneten
Tabelle hält" - sie erweitert den Zugriff nie über das hinaus, was die Tabelle
selbst erlaubt.

`GET/POST /tables/{id}/views` und `GET/PATCH/DELETE /tables/{id}/views/{view_id}`
listen, erstellen, lesen, aktualisieren und löschen sie. Die Liste ist mit `skip`
und `limit` (höchstens 100) seitenweise: zuerst die eigenen Ansichten des Aufrufers,
dann die geteilten, jeweils nach Name; `total` zählt alle. `config` ist `{filters,
sort, visible_columns, group_by}` - eine `RecordQuery` plus die zwei Felder, die
nur die Darstellung der Konsole braucht: `visible_columns` (`null` bedeutet jede
lebende Spalte) und `group_by` (eine lebende `single_select`-Spalte, für die
Spalten eines Kanban-Boards).

| Feld | Bedeutung |
|---|---|
| `kind` | `table`, `kanban` oder `list` - eine Ansicht wird *für* eine Art gespeichert |
| `visibility` | `private` (nur ihr Besitzer) oder `shared` (jeder, der die Tabelle sehen kann) |
| `can_manage` | Ob dieser Aufrufer sie umbenennen, umkonfigurieren oder teilen darf |
| `can_delete` | Ob dieser Aufrufer sie löschen darf |

Auflisten, Lesen und Löschen lösen sich gegen die Tabelle auf (`tables:view`); eine
Ansicht zu erstellen oder zu ändern braucht `tables:edit` auf der Tabelle, sodass ein
Besitzer, dem das Bearbeitungsrecht entzogen wurde, seine Ansichten noch löschen,
aber nicht mehr umbauen oder teilen kann.

Eine Ansicht zu ändern oder zu löschen ist
enger: nur ihr Besitzer, oder ein Aufrufer, dessen
[Scope](permissions.md) für `tables:edit` `ALL` ist - nicht "jeder, der die Tabelle
bearbeiten darf" - sodass ein geteilter Bearbeiter nicht stillschweigend den
gespeicherten Filter eines anderen Mitglieds umbiegen kann. Die Ablehnung
funktioniert wie bei jedem anderen Schreibzugriff auf eine einzelne Ressource
hier: `NOT_FOUND` (404), nie ein 403, der einem abgelehnten Aufrufer verraten
würde, dass die Ansicht existiert. `can_manage` und `can_delete` sagen, welches von
beidem dieser Aufrufer darf.

Das Archivieren einer Spalte wird mit `SCHEMA_DEPENDENCY` abgelehnt und nennt die
Ansicht, wenn eine Ansicht, die der Aufrufer sowohl sehen als auch ändern kann, sie
noch zum Filtern, Sortieren oder Gruppieren nutzt: eine seiner eigenen oder - für
einen Aufrufer, dessen Scope für `tables:edit` `ALL` ist - eine geteilte. Jede andere
Ansicht blockiert das Archivieren nicht und wird nicht genannt, weil der Aufrufer sie
nicht aus dem Weg räumen könnte; das gilt für jede private Ansicht eines anderen
Mitglieds, die selbst einem Aufrufer mit Scope `ALL` nicht offengelegt wird. Eine
Spalte nur in `visible_columns` anzuzeigen blockiert ebenfalls nicht.

Was eine Ansicht noch von einer Spalte nennt, die nicht mehr lebt, wird beim Lesen
der Ansicht weggelassen: ein Filter darauf entfällt, eine Sortierung danach fällt auf
`created_at` zurück, eine Gruppierung danach wird geleert, und sie verlässt
`visible_columns` - eine Ansicht, die keine ihrer gewählten Spalten mehr zeigt, zeigt
alle lebenden. Die gespeicherte Konfiguration wird nicht umgeschrieben.

## Trigger { #triggers }

Ein [Workflow](workflows.md#when-a-table-record-is-added), dessen Trigger-Knoten **New
table record** ist, läuft nach der Veröffentlichung für jeden Datensatz, der seiner
Tabelle hinzugefügt wird, egal auf welchem Weg: in der Konsole, über die API, durch das
Tabellen-Tool eines Agents oder den Tabellenschritt eines anderen Workflows. Ein Upsert,
der einen Datensatz anlegt, startet ihn; einer, der ihn aktualisiert, nicht. Das
Veröffentlichen braucht Lesezugriff auf die Tabelle und das Recht, den Workflow
auszuführen, denn er läuft als das Mitglied, das ihn veröffentlicht hat, nie als der Autor
des Datensatzes. Dessen Zugriff wird bei jedem Datensatz erneut geprüft.

Der Trigger führt die Version aus, die ihn eingeschaltet hat, und die nächste
Veröffentlichung verschiebt ihn auf die neue Version. Seine Filter nutzen die Operatoren
aus [Auflisten und Filtern](#listing-and-filtering) und werden am Datensatz geprüft, wie
er angelegt wurde, sodass eine spätere Änderung ihn weder startet noch stoppt. Er gibt dem
Run den ganzen Datensatz: `record_id`, `values` nach Spalten-ID, dieselben Werte als
`fields` nach Beschriftung und `author_id`, damit der Run ihn mit `table.record.update`
zurück ändern kann. **Triggers** auf der Seite der Tabelle listet die Workflows, die mit
ihr starten, pausiert und setzt jeden fort und öffnet seinen Verlauf.

Ein Trigger startet nur für Datensätze, die hinzukommen, während er eingeschaltet ist.
Das Einschalten - eine Veröffentlichung oder das Fortsetzen - nimmt die Schema-Sperre der Tabelle, auf die jeder
Schreibzugriff wartet, sodass kein vorher committeter Datensatz ihn je startet und nichts
nachgeholt wird, was hinzukam, während er aus war. Ein Worker-Heartbeat liest das
Outbox-Ereignis jedes neuen Datensatzes innerhalb von etwa zehn Sekunden. Er entscheidet
einmal pro Trigger und hält die Entscheidung fest; ein zweiter Durchlauf oder ein zweiter
Worker findet sie und startet nichts.

**Verlauf** listet jede Entscheidung, die neueste zuerst, ohne die Werte des Datensatzes:

| Angezeigt als | Warum |
|---|---|
| Lauf gestartet | Jeder Filter galt; der Run ist verlinkt |
| Übersprungen | Der Datensatz passte nicht oder kam hinzu, bevor der Trigger eingeschaltet war |
| Blockiert | Er hätte sich erneut gestartet, die Kette ging mehr als fünf Trigger tief oder über 50 Runs, oder die Zulassungsquote lehnte den Run ab |
| Konnte nicht starten | Das Mitglied, als das er läuft, darf die Tabelle nicht mehr lesen oder den Workflow nicht mehr ausführen, oder das Anlegen des Datensatzes war nicht lesbar |

Ein Workflow, der in eine Tabelle schreibt, kann deren Trigger starten, und so weiter
über weitere Tabellen. Jeder Run trägt die Kette, zu der er gehört, und ein Trigger, den
die Kette schon durchlaufen hat, wird blockiert statt erneut gestartet - so laufen zwei
Workflows, die Datensätze in die Tabellen des jeweils anderen schreiben, nicht im Kreis.
Eine Spalte, auf die ein Trigger filtert, kann nicht archiviert werden, bis der Trigger
seines Workflows nicht mehr auf sie filtert und veröffentlicht ist, auch wenn er pausiert
ist, und eine Tabelle, mit der ein veröffentlichter Workflow startet, kann nicht archiviert
werden, bis dieser Workflow anders startet.

## Was gemeinsam committet { #what-commits-together }

Ein Schreibzugriff auf einen Datensatz, seine Historienzeile, seine
Idempotenz-Quittung und bei einem Create eine Outbox-Zeile `table.record.created`
werden in einer Transaktion geschrieben und gemeinsam committet oder zurückgerollt. Ein
Fehler in irgendeinem Schritt hinterlässt keines davon. Änderungen an Tabelle und
Schema werden im [Audit-Log](governance.md) festgehalten; Änderungen an Datensätzen in
der Historie pro Datensatz, die die von jeder Änderung berührten Zellen aufbewahrt.

Zwei dieser Speicher halten Kopien dessen, was geschrieben wurde. Ein Receipt enthält den
ganzen Datensatz, wie ihn der Schreibzugriff zurückgab, und die Historie enthält, was sich
geändert hat. Ein Löschen des Datensatzes entfernt also die aktuelle Zeile und lässt beide
zurück, bis ihre Aufbewahrung sie entfernt. Outbox-Zeilen enthalten ids. Behandeln Sie alle
drei als personenbezogene Daten, wenn es die Zellen sind; siehe
[Datenschutz](data-protection.md#the-database) und
[Limits und Aufbewahrung](#limits-and-retention).

Die Outbox-Zeile ist die Übergabe an alles, was auf einen neuen Datensatz reagiert:
heute die [Trigger](#triggers). Ihr Heartbeat holt sich nicht zugestellte Zeilen in einer
eigenen Session, prüft jede gegen die Trigger der Tabelle und markiert sie in derselben
Transaktion als versendet. Eine nicht zugestellte Zeile wird nur durch ihr eigenes, viel
längeres Aufbewahrungsfenster entfernt (unten) - eine Dead-Letter-Frist für einen Worker,
der so lange ausgefallen ist, keine Behauptung, das Ereignis sei je abgeholt worden.

## Limits und Aufbewahrung { #limits-and-retention }

Ein Tenant kann die gemeinsame Datenbank nur so weit wachsen lassen, wie das Deployment es
zulässt. Jedes Limit ist eine Einstellung des Deployments, gilt **je Organisation**, sodass
die Nutzung eines Tenants nie auf einen anderen angerechnet wird, und wird mit
`QUOTA_EXCEEDED` (402) abgelehnt, wenn ein Schreibzugriff es überschreiten würde.

| Einstellung | Standard | Begrenzt |
|---|---|---|
| `TABLES_MAX_PER_ORGANIZATION` | 200 | Tabellen einer Organisation. Archivierte zählen mit, weil eine Tabelle nie gelöscht wird |
| `TABLES_MAX_RECORDS_PER_TABLE` | 100.000 | Datensätze in einer Tabelle. Ein Update eines Datensatzes in einer vollen Tabelle ist erlaubt |
| `TABLES_MAX_RECORD_BYTES` | 1.000.000 | Die serialisierten Werte eines Datensatzes in Bytes |

Die Ablehnung nennt das Limit und seine Obergrenze in `details` (`{"quota": "records",
"limit": 100000}`), nie den Inhalt, und schreibt einen Eintrag `table.quota_refused` in das
[Audit-Log](governance.md) mit denselben zwei Feldern. Die abgelehnte Anfrage schreibt
nichts. Schreibzugriffe sind außerdem auf `RATE_LIMIT_TABLE_WRITES_PER_MINUTE` (300) je
Mitglied und Organisation begrenzt, in der Konsole ebenso wie über die API; ein Mitglied
darüber erhält ein 429 mit `Retry-After`. Siehe [Konfiguration](configuration.md#rate-limiting).

**Was die Historie aufbewahrt.** Ein Create hält den ganzen Datensatz in `after`, ein Delete
den ganzen Datensatz in `before`; das Datensatzlimit begrenzt beides. Ein Datensatz, der
älter als das Limit ist oder geschrieben wurde, bevor `TABLES_MAX_RECORD_BYTES` gesenkt
wurde, kann immer noch darüber liegen - sein Delete hält `before` dann als
`{"omitted": {"bytes": <seine Größe>, "limit": <das Limit>}}` statt der Werte, und gelingt
trotzdem. Ein Update hält nur die Zellen, die sich geändert haben: `before` enthält ihre
früheren Werte und `after` die neuen, und eine Spalte, die auf einer Seite fehlt, war dort
leer. Das Bearbeiten einer Zelle eines großen Datensatzes kostet daher eine Zelle, wie oft
es auch wiederholt wird.

**Aufbewahrung.** Der tägliche [Aufbewahrungs-Sweep](governance.md#retention) entfernt auch
Tabellendaten, hart und in Batches, für jede Organisation:

| Was | Entfernt, wenn | Einstellung |
|---|---|---|
| Receipts | Älter als 24 Stunden | `TABLES_RECEIPT_TTL_HOURS` |
| Outbox-Zeilen | Vor mehr als 3 Tagen zugestellt | `TABLES_OUTBOX_RETENTION_DAYS` |
| Nicht zugestellte Outbox-Zeilen | Nie zugestellt und 30 Tage alt: Der Trigger-Heartbeat lief so lange nicht, und für diese Datensätze startet kein Trigger mehr | `TABLES_OUTBOX_UNDISPATCHED_RETENTION_DAYS` |
| Historie | Älter als 365 Tage, für einen gelöschten Datensatz ebenso wie für einen lebenden | `TABLES_HISTORY_RETENTION_DAYS` |

Der Sweep schreibt einen Audit-Eintrag je Organisation, der die Klasse (`table_receipts`,
`table_outbox`, `table_history`) und die Anzahl nennt. Es sind Einstellungen des Deployments,
keine je Organisation. Die Datensätze selbst und die Tabellen entfernt er nie.

`RATE_LIMIT_TABLE_WRITES_PER_MINUTE` ist ein Kontingent je *Mitglied*, daher skaliert das
Budget eines Durchlaufs für jede der drei Klassen sowohl damit als auch mit der Anzahl der
aktiven Mitglieder der Organisation, mit Spielraum, damit ein bestehender Rückstand schrumpft
statt nur gehalten zu werden - jedes Mitglied, das gleichzeitig ununterbrochen schreibt, läuft
dem Sweep nie davon, bis zu einer großzügigen Grenze, für wie viele Mitglieder sich der
Durchlauf einer Organisation bemisst. Die Zahlen stehen in der
[Konfiguration](configuration.md#virtual-tables-limits-and-retention). Ein Rückstand darüber
hinaus wird wie bei jeder anderen Klasse über mehrere Durchläufe abgearbeitet.

## Wer was darf { #who-can-do-what }

| Permission | Wer sie hält |
|---|---|
| `tables:view` | Owner, Admin, Builder und Operator sehen alle Tabellen; ein Member oder Viewer sieht die eigenen, die organisationsweit sichtbaren und die geteilten |
| `tables:edit` | Owner und Admin bearbeiten alle; ein Builder bearbeitet die eigenen und geteilten; ein Member die eigenen |
| `tables:create` | Owner, Admin, Builder, Member |

`tables:view` und `tables:edit` sind Ressourcen-Permissions, daher erweitert ein
[Grant](permissions.md) auf eine Tabelle eine Rolle nur für diese Tabelle: Ein Viewer
mit `edit` auf einer Tabelle bearbeitet diese Tabelle und sonst nichts. Das Teilen
nutzt dieselben `/tables/{id}/sharing`-Routen wie die anderen geteilten Ressourcen.
Datensätze erben den Zugriff ihrer Tabelle, und das Schema erzwingt es: Eine Zeile in
Records, History oder Outbox verweist auch über die Organisation auf ihre Tabelle und kann
keine Tabelle eines anderen Tenants nennen.

Die Tabelle einer anderen Organisation und eine, die der Aufrufer nicht erreichen darf,
sind beide ein 404. Ein Kontext ohne angemeldetes Subjekt erreicht nichts.

Ob ein bestimmter Aufrufer eine bestimmte Tabelle bearbeiten darf, steht auch
direkt auf dem Wire: `TableSummary.can_edit` und `TableRead.can_edit` werden
serverseitig aufgelöst (Rollen-Scope oder ein expliziter Grant) und bei jedem
Lesen mitgeschickt, genau wie `Agent.can_run` - sodass eine Katalogzeile oder eine
Detailseite nie raten muss, ob ihre Bearbeitungskontrollen abgelehnt würden. Das
eigene `can_manage` und `can_delete` einer gespeicherten Ansicht sind dieselbe Idee,
eine Ebene tiefer (siehe [Gespeicherte Ansichten](#saved-views)).

## Fehler { #errors }

Jede Ablehnung antwortet mit `{"error": {"code", "message", "details"}}`, und der
`code` ist das, wonach ein Client verzweigt.

| Code | Status | Bedeutung |
|---|---|---|
| `REVISION_CONFLICT` | 409 | Der Datensatz hat sich seit dem Lesen geändert |
| `REVISION_REQUIRED` | 428 | Ein Upsert eines bestehenden Datensatzes braucht `expected_revision` |
| `SCHEMA_VERSION_CONFLICT` | 409 | Das Schema hat sich seit dem Lesen geändert |
| `SCHEMA_DEPENDENCY` | 409 | Etwas hängt von dem ab, was die Änderung entfernt |
| `TABLE_ARCHIVED` | 409 | Die Tabelle lehnt Schreibzugriffe ab |
| `ALREADY_EXISTS` | 409 | Der Tabellenname, ein Ansichtsname oder die external id ist vergeben |
| `INVALID_RECORD` | 422 | Ein Wert passt nicht zu seiner Spalte; `details.fields` nennt jeden |
| `ARCHIVED_COLUMN` | 422 | Ein Wert nennt eine archivierte Spalte |
| `INVALID_QUERY` | 422 | Ein Filter oder eine Sortierung, die die Tabelle nicht beantworten kann |
| `INVALID_SCHEMA` | 422 | Eine widersprüchliche Schemaänderung |
| `IDEMPOTENCY_KEY_REUSED` | 422 | Der Schlüssel wurde für eine andere Anfrage verwendet |
| `QUOTA_EXCEEDED` | 402 | Der Schreibzugriff würde ein Speicherlimit überschreiten; `details` nennt das Limit (`tables`, `records`, `record_bytes`) und seine Obergrenze |
| `RATE_LIMIT_EXCEEDED` | 429 | Zu viele Tabellenschreibzugriffe in der letzten Minute; siehe `Retry-After` |
| `VALIDATION_ERROR` | 422 | Die Anfrage selbst ist fehlerhaft: ein falscher Typ, ein unbekanntes Feld, eine Grenze oder NUL, ein Zeilenumbruch oder ein einzelnes Surrogat in einer id, einem Schlüssel oder Namen. Die Route lehnt sie ab, bevor der Service läuft |
| `AUTHORIZATION_ERROR` | 403 | Dem Aufrufer fehlt die Permission, die eine Collection-Route verlangt (`tables:view`, `tables:create`) |
| `CONCURRENT_CHANGE` | 409 | Ein Upsert hat ein Rennen mit dem Löschen desselben Datensatzes verloren. Wiederholen Sie ihn |
| `NOT_FOUND` | 404 | Keine solche Tabelle oder kein solcher Datensatz, oder nicht erreichbar für den Aufrufer |

## Den Service aus Python aufrufen { #calling-the-service-from-python }

```python
service = VirtualTableService(db)
table = await service.create_table(ctx, TableCreate(name="Orders", columns=[
    ColumnInput(label="Customer", type="text"),
]))
customer = str(table.columns[0].id)

written = await service.upsert_record(
    ctx, table.id, "ORD-1042", RecordUpsert(values={customer: "Acme"}),
    operation_key="import-2026-09-21-row-17",
)

# Send the revision back to change it; a stale one raises RevisionConflictError.
await service.upsert_record(
    ctx, table.id, "ORD-1042",
    RecordUpsert(values={customer: "Acme Ltd"}, expected_revision=written.record.revision),
)
```

Die Organisation kommt immer aus `ctx`, nie aus einem Argument. Der Service committet
nie: Das tut die Session der Anfrage, und ein Worker besitzt seinen eigenen
Session-Scope.

## Einen Spaltentyp hinzufügen { #adding-a-column-type }

Ein Spaltentyp ist ein Eintrag in `COLUMN_TYPES` in
`backend/app/services/virtual_tables/types.py`, mit seinem Namen in `ColumnTypeName` in
`backend/app/schemas/virtual_table.py`. Der Eintrag legt fest, wie die Zelle zum
Vergleichen und Sortieren aus dem Datensatz gelesen wird (ein `SqlKind`), welche
Filteroperatoren sie nimmt, ob sie sortierbar ist, und welchen Validator jeder
Schreibzugriff und jeder Filteroperand durchläuft. Der Validator gibt den Wert so
zurück, wie er gespeichert wird, oder wirft `CellProblem` mit einer Meldung für den, der
ihn geschrieben hat. Jede Oberfläche ruft denselben Service, also nehmen Konsole, API,
Agents und Workflows den neuen Typ sofort an, und ein [Trigger](#triggers) filtert mit
denselben Regeln darauf.

Die Konsole braucht den Typ in `ColumnTypeName` in `frontend/src/types/tables.ts`,
einen Editor in `record-cell-editor.tsx`, eine Auswahl in den Dialogen für Schema und
neue Tabelle und seine Beschriftung in den drei Meldungskatalogen. Tests gehören für den
Validator in `backend/tests/test_virtual_table_types.py` und in einen
Integrationstest, der einen Datensatz des neuen Typs schreibt, filtert und sortiert.

## Noch nicht gebaut { #not-built-yet }

- **Ein Principal für API-Keys.** Zugriff, Quittungen und Historie nennen einen
  angemeldeten Benutzer. Wie ein API-Key für die externe API auf eine Tabelle wirkt,
  muss noch abgestimmt werden.
- Das Erstellen und Löschen von Datensätzen in der Konsole. Agents erreichen Tabellen
  über die [Tables-Capability](reference/capabilities.md#tables), Workflows über die
  [Tabellen-Knoten](reference/workflow-nodes.md#virtual-tables).
- Ein Trigger auf das Ändern oder Löschen eines Datensatzes. [Trigger](#triggers)
  starten nur beim Anlegen.
- Einen Run, der als **Braucht Aufmerksamkeit** angehalten hat, in der Konsole
  fortsetzen. Er lässt sich abbrechen und ein neuer Run starten.
