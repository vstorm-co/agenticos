---
source_sha: "48a8b9fe7002"
---

# Virtual Tables { #virtual-tables }

Eine **Virtual Table** ist eine typisierte Tabelle mit Datensätzen, die eine
Organisation für ihre Agents, Workflows und Integrationen führt: abzugleichende
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
Dependency-Checker gefragt, ob etwas sie noch verwendet. Workflows, Views und Trigger
gibt es noch nicht, daher ist keiner registriert und nichts blockiert;
`app/services/virtual_tables/dependencies.py` ist der Ort, an dem ein Feature einen
registriert, und eine Ablehnung nennt die Abhängigen in `SCHEMA_DEPENDENCY`.

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

Ein Delete ist ein hartes Löschen. Die Historie des Datensatzes bleibt.

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

## Was gemeinsam committet { #what-commits-together }

Ein Schreibzugriff auf einen Datensatz, seine Historienzeile, seine
Idempotenz-Quittung und bei einem Create eine Outbox-Zeile `table.record.created`
werden in einer Transaktion geschrieben und gemeinsam committet oder zurückgerollt. Ein
Fehler in irgendeinem Schritt hinterlässt keines davon. Änderungen an Tabelle und
Schema werden im [Audit-Log](governance.md) festgehalten; Änderungen an Datensätzen in
der Historie pro Datensatz, die die Werte vor und nach jeder Änderung aufbewahrt.

Drei dieser Speicher halten Daten ohne Aufbewahrungsfrist. Die Historie pro Datensatz und
die Receipts enthalten die Werte, ein Löschen des Datensatzes entfernt also die aktuelle
Zeile und lässt beide zurück. Ein Receipt enthält den ganzen Datensatz, wie ihn der
Schreibzugriff zurückgab, und verschwindet nur mit seinem Konto oder seiner Organisation.
Outbox-Zeilen enthalten ids und werden nach der Zustellung nie bereinigt. Behandeln Sie sie
als personenbezogene Daten, wenn es die Zellen sind; siehe
[Datenschutz](data-protection.md#the-database).

Diese Speicher halten vollständige Schnappschüsse, und eine echte Bearbeitung eines großen
Datensatzes schreibt weiterhin einen in die Historie und, wenn ein Schlüssel gesendet
wird, einen in ein Receipt. Kontingente oder Rate-Limits pro Tenant für dieses Wachstum
und das Speichern nur der Änderungen sind noch nicht implementiert.

Die Outbox-Zeile ist die Übergabe an alles, was auf einen neuen Datensatz reagiert.
Bisher konsumiert sie nichts. Ein Konsument holt sich nicht zugestellte Zeilen in einer
eigenen Session und markiert sie als zugestellt.

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
| `ALREADY_EXISTS` | 409 | Der Tabellenname oder die external id ist vergeben |
| `INVALID_RECORD` | 422 | Ein Wert passt nicht zu seiner Spalte; `details.fields` nennt jeden |
| `ARCHIVED_COLUMN` | 422 | Ein Wert nennt eine archivierte Spalte |
| `INVALID_QUERY` | 422 | Ein Filter oder eine Sortierung, die die Tabelle nicht beantworten kann |
| `INVALID_SCHEMA` | 422 | Eine widersprüchliche Schemaänderung |
| `IDEMPOTENCY_KEY_REUSED` | 422 | Der Schlüssel wurde für eine andere Anfrage verwendet |
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

## Noch nicht gebaut { #not-built-yet }

- **Ein Principal für API-Keys.** Zugriff, Quittungen und Historie nennen einen
  angemeldeten Benutzer. Wie ein API-Key für die externe API auf eine Tabelle wirkt,
  muss noch abgestimmt werden.
- Agent-Tools, Workflow-Knoten und die Konsolenansichten, die diesen Service aufrufen
  werden.
- Konsumenten der Outbox und Dependency-Checker für Workflows, Views und Trigger.
- Kontingente oder Rate-Limits pro Tenant für das Wachstum von Historie und Receipts sowie
  das Speichern nur der Änderungen.
