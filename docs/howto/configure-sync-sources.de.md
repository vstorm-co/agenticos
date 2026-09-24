---
source_sha: "7dfde94e116e"
---

# Sync-Quellen einrichten { #configure-sync-sources }

Sync-Quellen holen Dokumente aus externen Diensten (Google Drive, S3/MinIO, eine
öffentliche Website) selbsttätig in Knowledge-Collections. Jede Quelle speichert
einen Connector-Typ, eine Ziel-Collection, connector-spezifische Einstellungen,
einen Sync-Modus, einen optionalen Zeitplan und die id des
[Vault-Secrets](../secrets.md), das sie authentifiziert - eine Website braucht
keines.

Läuft ein Sync, listet der Connector die entfernten Dateien auf, lädt sie in ein
temporäres Verzeichnis herunter und schickt sie durch die übliche
Ingestion-Pipeline (parsen, chunken, einbetten, speichern). Ist die Auflistung
vollständig, werden Dokumente entfernt, die die Quelle früher eingebracht hat und
nicht mehr auflistet. Ein Eintrag in `SyncLog` hält das Ergebnis jedes einzelnen
Sync-Vorgangs fest.

### Die Architektur auf einen Blick { #architecture-at-a-glance }

| Baustein | Ort | Rolle |
|-----------|----------|------|
| `BaseSyncConnector` | `app/services/rag/connectors/__init__.py` | Abstrakte Basis aller Connectoren |
| `RemoteFile` | `app/services/rag/connectors/__init__.py` | Pydantic-Modell, das eine entfernte Datei beschreibt |
| `CONNECTOR_REGISTRY` | `app/services/rag/connectors/__init__.py` | Bildet Connector-Typ-Strings auf Klassen ab |
| `SyncSource` (DB-Modell) | `app/db/models/sync_source.py` | Speichert die Konfiguration der Quellen |
| `SyncLog` (DB-Modell) | `app/db/models/sync_log.py` | Verfolgt einzelne Sync-Vorgänge |
| `SyncSourceService` | `app/services/sync_source.py` | Fachlogik für CRUD und Auslösen |
| RAG-CLI-Befehle | `app/commands/rag.py` | CLI-Oberfläche zur Verwaltung der Quellen |
| RAG-API-Routen | `app/api/routes/v1/rag.py` | REST-API zur Verwaltung der Quellen |

## Schnelleinstieg -- CLI { #quick-start-cli }

### Verfügbare Connector-Typen auflisten { #list-available-connector-types }

```bash
# Shows all registered connectors (e.g. gdrive, s3)
uv run agenticos cmd rag-sources
```

### Eine Google-Drive-Quelle anlegen -- Sync alle 2 Stunden { #add-a-google-drive-source-sync-every-2-hours }

```bash
uv run agenticos cmd rag-source-add \
  --name "Legal docs" \
  --type gdrive \
  --org 0c8f2b1e-... \
  --collection legal \
  --config '{"folder_id": "1abc123def", "include_subfolders": true}' \
  --sync-mode new_only \
  --schedule 120
```

### Eine S3-Quelle anlegen -- nur manueller Sync { #add-an-s3-source-manual-sync-only }

```bash
uv run agenticos cmd rag-source-add \
  --name "Marketing" \
  --type s3 \
  --org 0c8f2b1e-... \
  --collection marketing \
  --config '{"bucket": "my-docs", "prefix": "marketing/"}' \
  --sync-mode full \
  --schedule 0
```

### Einen Sync von Hand auslösen { #trigger-sync-manually }

```bash
# Sync a single source by ID
uv run agenticos cmd rag-source-sync <source-id>

# Sync all active sources
uv run agenticos cmd rag-source-sync --all
```

### Eine Quelle entfernen { #remove-a-source }

```bash
uv run agenticos cmd rag-source-remove <source-id>
```

Die `<source-id>` ist eine UUID, die beim Anlegen der Quelle ausgegeben wird und
in der Auflistung von `rag-sources` steht.

## Schnelleinstieg -- Oberfläche { #quick-start-ui }

1. Öffnen Sie **Knowledge Base** und dort den Tab **Sync**.
2. Klicken Sie auf **"+ Add Source"**.
3. Wählen Sie einen Connector-Typ (Google Drive, S3, Website). Die Formularfelder
   werden aus dem JSON Schema des `CONFIG_MODEL` des Connectors erzeugt. Eine
   Website hat keinen Credential-Schritt.
4. Füllen Sie die connector-spezifischen Konfigurationsfelder aus (etwa Folder-ID,
   Bucket-Name).
5. Wählen Sie eine Ziel-Collection, einen Sync-Modus und ein Zeitintervall.
6. Klicken Sie auf **"Create Source"**.
7. Mit **"Sync Now"** lösen Sie einen sofortigen Sync aus, oder Sie warten, bis
   der Zeitplan von selbst greift.

Die Oberfläche ruft dieselbe REST-API auf, die unten dokumentiert ist: Was Sie in
der Oberfläche tun können, können Sie auch mit `curl` oder einem beliebigen
HTTP-Client tun.

## Sync-Modi { #sync-modes }

| Modus | Verhalten |
|------|----------|
| `full` | Alles neu synchronisieren. Alle Dateien werden (erneut) aufgenommen, vorhandene Dokumente ersetzt. |
| `new_only` | Neue Dateien hinzufügen und geänderte aktualisieren. Änderungen werden über einen SHA-256-Hash erkannt — unveränderte Dateien werden übersprungen. |
| `update_only` | Nur Dateien aktualisieren, die bereits in der Collection liegen. Neue Dateien werden übersprungen. Ein SHA-256-Hash überspringt unveränderte Dateien. |

!!! tip "`new_only` für die meisten Abläufe"

    Er fügt neue Dateien hinzu und aktualisiert geänderte, während unveränderte
    übersprungen werden — das ist der schnellste inkrementelle Sync.
    `update_only` frischt vorhandene Dokumente auf, ohne neue hinzuzunehmen;
    `full` ist jedes Mal ein sauberer Neuimport.

### Was ein Sync entfernt { #what-a-sync-removes }

In jedem Modus entfernt ein Sync die Dokumente, die seine Quelle früher
eingebracht hat und nicht mehr auflistet: eine von der Website genommene Seite,
eine aus dem Drive-Ordner gelöschte Datei, ein aus dem Bucket entferntes Objekt.
Das Sync-Protokoll zählt sie unter `removed`.

Er entfernt nichts, solange die Auflistung nicht **vollständig** war. Ein Crawl,
der an seinem Seitenlimit angehalten hat oder eine der Seiten nicht lesen konnte,
hat nicht gesehen, was er nicht auflistet. Dieser Lauf behält jedes Dokument und
sagt das in der Meldung des Sync-Protokolls. Der nächste Sync mit einer
vollständigen Auflistung entfernt, was verschwunden ist. Ein Dokument, das nicht
entfernt werden konnte, zählt als fehlgeschlagene Datei, und der nächste Sync
versucht es erneut.

Pro Quelle läuft immer nur ein Sync. Ein Sync, der gestartet wird, während ein
anderer Sync derselben Quelle noch läuft, startet nicht, und sein Protokoll sagt
das.

Entfernt werden nur die eigenen Dokumente der Quelle. Ein Upload oder ein
Dokument, das eine andere Quelle in dieselbe Collection gebracht hat, wird nie
angerührt. Ein Dokument, das aufgenommen wurde, bevor seine Quelle dies
festhielt (September 2026), bleibt erhalten, bis die Quelle es erneut aufnimmt.

## Zeitplan { #schedule }

Das Feld `schedule_minutes` steuert, wie oft die Quelle selbsttätig
synchronisiert:

| Wert | Bedeutung |
|-------|---------|
| `0` (oder `null`) | Nur manuell -- über CLI oder Oberfläche ausgelöst |
| `30` | Alle 30 Minuten |
| `120` | Alle 2 Stunden |
| `1440` | Einmal am Tag |

!!! warning "Ein Zeitplan braucht den Prefect-Runner"

    `check_scheduled_syncs_flow` ist ein Prefect-Deployment, das alle 60 Sekunden
    aufwacht und auslöst, was fällig ist. Ohne die Container `prefect-server` und
    `prefect-runner`, die `make dev` startet, bewirkt `schedule_minutes` nichts.
    Läuft keiner von beiden, synchronisiert nur ein manueller Auslöser (CLI, API
    oder Oberfläche) überhaupt etwas.

## Google Drive einrichten { #google-drive-setup }

### 1. Ein Dienstkonto anlegen { #1-create-a-service-account }

1. Öffnen Sie die [Google Cloud Console](https://console.cloud.google.com/).
2. Legen Sie ein neues Projekt an (oder wählen Sie ein vorhandenes).
3. Aktivieren Sie die **Google Drive API**.
4. Gehen Sie zu **IAM & Admin > Service Accounts** und legen Sie ein neues
   Dienstkonto an.
5. Erzeugen Sie einen JSON-Schlüssel für das Dienstkonto und laden Sie ihn
   herunter.

### 2. Den Drive-Ordner freigeben { #2-share-your-drive-folder }

1. Öffnen Sie Google Drive und gehen Sie zu dem Ordner, den Sie synchronisieren
   wollen.
2. Klicken Sie auf **Share** und fügen Sie die E-Mail-Adresse des Dienstkontos
   hinzu (sie sieht aus wie `name@project.iam.gserviceaccount.com`).
3. Vergeben Sie mindestens **Viewer**-Zugriff.

### 3. Der Quelle den Schlüssel geben { #3-give-the-source-the-key }

Fügen Sie den Inhalt der JSON-Schlüsseldatei in das Feld **Service Account JSON**
der Quelle ein. Eine `gdrive`-Quelle läuft auf dem Credential, das ihre eigene
Konfiguration trägt, und auf keinem anderen — es gibt keinen deploymentweiten
Rückfall, denn der würde die `folder_id` einer Quelle darüber entscheiden lassen,
was unter dem Dienstkonto des Betreibers aufgelistet wird.

`GOOGLE_DRIVE_CREDENTIALS_FILE` in `.env` gilt allein für den CLI-Befehl
`rag-sync-gdrive`.

### 4. Die Folder-ID herausfinden { #4-get-the-folder-id }

Die Folder-ID ist das letzte Segment der URL des Google-Drive-Ordners:

```
https://drive.google.com/drive/folders/1abc123def456ghi
                                        ^^^^^^^^^^^^^^^
                                        This is the folder ID
```

### 5. Konfigurationsfelder des Google-Drive-Connectors { #5-google-drive-connector-config-fields }

| Feld | Typ | Pflicht | Vorgabe | Beschreibung |
|-------|------|----------|---------|-------------|
| `folder_id` | string | Ja | -- | Die Folder-ID aus der Google-Drive-URL |
| `include_subfolders` | boolean | Nein | `true` | Dateien aus Unterordnern rekursiv einbeziehen |

Das Dienstkonto selbst ist **kein** Konfigurationsfeld. Legen Sie es als
Credential der Art `gcp_service_account` im Vault ab und verweisen Sie die Quelle
mit `secret_id` darauf: So wird es einmal gespeichert und von jeder Quelle
referenziert, die es braucht, statt in jede einzelne eingefügt zu werden
([#937](https://github.com/vstorm-co/agenticos/issues/937)). Es unter `config` zu
senden, wird abgelehnt.

Eine `folder_id` darf nur enthalten, was Google vergibt — Buchstaben, Ziffern,
`-` und `_`. Alles andere wird beim Anlegen der Quelle abgelehnt, denn die id
wird in die Drive-Abfrage interpoliert, und ein einzelnes Anführungszeichen darin
erweitert, was die Abfrage auflistet.

Google Docs, Sheets und Slides werden beim Herunterladen selbsttätig in portable
Formate exportiert (PDF, XLSX, PPTX). Eine Datei, deren Drive-Name
Pfadtrenner enthält, wird als eine Datei innerhalb des Sync-Verzeichnisses
geschrieben, nie unter dem Pfad, den ihr Name buchstabiert.

## S3 / MinIO einrichten { #s3-minio-setup }

### 1. Die Umgebung konfigurieren { #1-configure-the-environment }

Ergänzen Sie Ihre `.env` um die folgenden Variablen:

```bash
S3_RAG_ENDPOINT=https://s3.amazonaws.com   # or your MinIO URL, e.g. http://localhost:9000
S3_RAG_ACCESS_KEY=your-access-key
S3_RAG_SECRET_KEY=your-secret-key
S3_RAG_REGION=us-east-1                    # required for AWS, optional for MinIO
```

Bei MinIO lautet der Endpunkt üblicherweise `http://minio:9000` (Docker) oder
`http://localhost:9000` (lokal).

### 2. Konfigurationsfelder des S3-Connectors { #2-s3-connector-config-fields }

| Feld | Typ | Pflicht | Vorgabe | Beschreibung |
|-------|------|----------|---------|-------------|
| `bucket` | string | Ja | -- | Name des S3-Buckets |
| `prefix` | string | Nein | `""` | Key-Präfix, das den Sync eingrenzt (etwa `documents/legal/`). Für den ganzen Bucket leer lassen. |

## Eine Website einrichten { #website-setup }

Eine `web`-Quelle liest eine öffentliche Website, meist die Dokumentationsseite
eines Produkts. Sie braucht kein Credential und keinen Vault-Eintrag. Geben Sie
ihr eine Start-URL, und sie folgt entweder den Links von dieser Seite aus oder
liest die Seiten, die eine Sitemap auflistet.

```bash
uv run agenticos cmd rag-source-add \
  --name "Product docs" \
  --type web \
  --org 0c8f2b1e-... \
  --collection product-docs \
  --config '{"root_url": "https://docs.example.com/guide/", "max_depth": 3}' \
  --sync-mode new_only \
  --schedule 1440
```

### Konfigurationsfelder des Website-Connectors { #website-connector-config-fields }

| Feld | Typ | Pflicht | Vorgabe | Beschreibung |
|-------|------|----------|---------|-------------|
| `root_url` | string | Ja | -- | Die Seite, von der der Crawl ausgeht. Ihr Host ist der einzige Host, den die Quelle liest. |
| `max_depth` | integer | Nein | `2` | Wie viele Links weit von der Start-URL aus gefolgt wird, `0` bis `10`. `0` liest nur die Startseite. |
| `path_prefix` | string | Nein | der Ordner der Start-URL | Nur Seiten, deren Pfad damit beginnt, werden gelesen. `https://docs.example.com/guide/intro` liest vorgabemäßig `/guide/`; `/` setzen für den ganzen Host. |
| `sitemap_url` | string | Nein | -- | Die Seiten lesen, die diese Sitemap auflistet, statt Links zu folgen. Sie muss auf dem Host der Start-URL liegen und `https://` verwenden, wenn die Start-URL es tut. Einem Sitemap-Index wird bis zu seinen Sitemaps gefolgt. |
| `max_pages` | integer | Nein | `500` | Der Crawl hält an, nachdem er so viele Seiten gelesen hat, `1` bis `5000`. |

### Was einen Crawl begrenzt { #what-bounds-a-crawl }

- **Ein Host und ein Pfad.** Links auf andere Hosts und auf Pfade außerhalb von
  `path_prefix` werden nicht verfolgt. Einer Weiterleitung, die sie verlässt,
  ebenfalls nicht. Eine Start-URL auf `https://` wird nie für `http://`
  verlassen: Einem Link oder einer Weiterleitung auf eine unverschlüsselte Seite
  wird nicht gefolgt.
- **Das Netz des Deployments ist unerreichbar.** Jede Anfrage - robots.txt, die
  Sitemap, jede Seite und jede Weiterleitung - wird gegen dieselbe SSRF-Richtlinie
  geprüft wie Webhooks und MCP-Server. Sie geht an die Adresse, die die Prüfung
  bestanden hat. Eine Start-URL, die auf eine private, Loopback-, Link-Local- oder
  Cloud-Metadata-Adresse auflöst, wird beim Speichern der Quelle abgelehnt.
- **robots.txt wird befolgt**, für Sitemaps und Seiten, einschließlich
  `Crawl-delay` bis zu zehn Sekunden. Der Crawler gibt sich als
  `AgenticOS-Crawler` zu erkennen. Er wartet zwischen Anfragen mindestens eine
  halbe Sekunde, und eine Seite, die `noindex` oder `nofollow` angibt, wird
  respektiert. Eine Seite, die eine Sitemap noch auflistet, nachdem sie `noindex`
  angibt oder verschwunden ist, wird aus der Collection entfernt.
- **Größe und Zeit.** Eine Seite über 5 MB wird nicht gelesen. Der Crawl hält bei
  `max_pages` an. Ein Sync hört nach sechs Stunden auf, die Website zu lesen, und
  ein Sync, der angehalten hat, entfernt nichts.

Jede Seite wird als Markdown-Dokument gespeichert, das ihren Text und die URL
enthält, von der sie stammt, ohne ihren Query-String. Navigation, Kopf- und Fußzeilen und Skripte bleiben
außen vor. Eine Seite wird nur neu eingebettet, wenn sich ihr Text ändert. Ein
neuer Build-Stempel oder ein Tracking-Skript im Markup zählt nicht als Änderung.

### Wer lesen kann, was sie importiert { #who-can-read-what-it-imports }

Eine Website-Quelle hat kein Credential, also reicht sie so weit, wie die Website
jedem im Internet zeigt. Über einen Login kommt sie nie hinaus. Alles, was sie
importiert, ist für jeden durchsuchbar, der die Collection durchsuchen kann, die
sie speist - wie bei jeder anderen Quelle. Siehe
[wer am Ende lesen kann, was eine Quelle aufgenommen hat](../file-processing.md#who-ends-up-able-to-read-what-a-source-ingested).

Importiert werden nur HTML-Seiten. Ein PDF oder eine andere Datei, die von einer
Seite verlinkt ist, wird nicht heruntergeladen.

## API-Referenz { #api-reference }

Alle Endpunkte für Sync-Quellen liegen unter `/api/v1/rag/sync/`. Das Auflisten
verlangt `collections:view`, und alles, was eine Quelle verändert, verlangt
`collections:edit` — in beiden Fällen bezogen auf die Collection, zu der die
Quelle gehört. Eine Adminrolle kommt darin nicht vor. Siehe
[wer eine Collection erreichen darf](../file-processing.md#who-may-reach-a-collection).

### CRUD für Sync-Quellen { #sync-sources-crud }

| Methode | Endpunkt | Beschreibung |
|--------|----------|-------------|
| `GET` | `/api/v1/rag/sync/sources` | Alle eingerichteten Sync-Quellen auflisten |
| `POST` | `/api/v1/rag/sync/sources` | Eine neue Sync-Quelle anlegen |
| `PATCH` | `/api/v1/rag/sync/sources/{id}` | Eine vorhandene Sync-Quelle ändern |
| `DELETE` | `/api/v1/rag/sync/sources/{id}` | Eine Sync-Quelle löschen |
| `POST` | `/api/v1/rag/sync/sources/{id}/trigger` | Einen Sync von Hand auslösen |

### Connectoren und Protokolle { #connectors-logs }

| Methode | Endpunkt | Beschreibung |
|--------|----------|-------------|
| `GET` | `/api/v1/rag/sync/connectors` | Verfügbare Connector-Typen samt Konfigurationsschema auflisten |
| `GET` | `/api/v1/rag/sync/logs` | Die Sync-Historie auflisten (nach `collection_name` filterbar) |

### Beispiel: eine Quelle über die API anlegen { #example-create-a-source-via-api }

```bash
curl -X POST http://localhost:8000/api/v1/rag/sync/sources \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Legal Drive",
    "connector_type": "gdrive",
    "collection_name": "legal",
    "config": {
      "folder_id": "1abc123def",
      "include_subfolders": true
    },
    "sync_mode": "new_only",
    "schedule_minutes": 120
  }'
```

### Beispiel: einen Sync über die API auslösen { #example-trigger-a-sync-via-api }

```bash
curl -X POST http://localhost:8000/api/v1/rag/sync/sources/{source_id}/trigger \
  -H "Authorization: Bearer $TOKEN"
```

### Beispiel: die Sync-Historie ansehen { #example-check-sync-history }

```bash
curl http://localhost:8000/api/v1/rag/sync/logs?limit=10 \
  -H "Authorization: Bearer $TOKEN"
```

### Beispiel: verfügbare Connectoren ermitteln { #example-discover-available-connectors }

```bash
curl http://localhost:8000/api/v1/rag/sync/connectors \
  -H "Authorization: Bearer $TOKEN"
```

Die Antwort enthält das `config_schema` jedes Connectors, aus dem das Frontend
seine dynamischen Formulare erzeugt. Es ist auch nützlich, um Integrationen
programmatisch zu bauen.

## Eine Quelle ändern { #updating-a-source }

Mit `PATCH` ändern Sie eine beliebige Teilmenge der Felder einer vorhandenen
Quelle:

```bash
curl -X PATCH http://localhost:8000/api/v1/rag/sync/sources/{source_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sync_mode": "full",
    "schedule_minutes": 60,
    "is_active": false
  }'
```

Änderbare Felder: `name`, `config`, `sync_mode`, `schedule_minutes`,
`is_active`, `collection_name`.

Setzen Sie `is_active` auf `false`, um eine Quelle anzuhalten, ohne sie zu
löschen.

## Sync-Vorgänge überwachen { #monitoring-sync-operations }

Jeder Sync erzeugt einen `SyncLog`-Eintrag mit den folgenden Feldern:

| Feld | Beschreibung |
|-------|-------------|
| `source` | Connector-Typ oder `"local"` für die Aufnahme über die CLI |
| `collection_name` | Die Ziel-Collection |
| `status` | `running`, `done` oder `error` |
| `mode` | `full`, `new_only` oder `update_only` |
| `total_files` | Anzahl der gefundenen Dateien |
| `ingested` | Erfolgreich aufgenommen (neu) |
| `updated` | Erfolgreich erneut aufgenommen (ersetzt) |
| `skipped` | Übersprungen (bereits vorhanden oder unverändert) |
| `failed` | Aufnahme fehlgeschlagen, einschließlich Seiten oder Dateien, die die Auflistung nicht lesen konnte, und Dokumenten, die nicht entfernt werden konnten |
| `removed` | Entfernt, weil die Quelle sie nicht mehr auflistet (siehe [was ein Sync entfernt](#what-a-sync-removes)) |
| `error_message` | Was schiefging oder warum nichts entfernt wurde. Ein Lauf kann `done` sein und trotzdem eine Meldung tragen, etwa wenn ein Crawl an seinem Seitenlimit angehalten hat |
| `started_at` | Wann der Sync begann |
| `completed_at` | Wann der Sync endete |

Die Protokolle sehen Sie in der Ausgabe der CLI oder über die API:

```bash
curl http://localhost:8000/api/v1/rag/sync/logs?collection_name=legal&limit=5 \
  -H "Authorization: Bearer $TOKEN"
```

## Eigene Connectoren ergänzen { #adding-custom-connectors }

Um einen neuen Connector-Typ zu ergänzen (etwa Notion, Confluence, Dropbox),
siehe [Einen Sync-Connector ergänzen](./add-sync-connector.md).

Die Kurzfassung:

1. Legen Sie in `app/services/rag/connectors/` eine Klasse an, die von
   `BaseSyncConnector` erbt.
2. Implementieren Sie `list_files()`, `_fetch()` und optional
   `validate_config()`.
3. Deklarieren Sie `SECRET_KIND` — welche Art von Vault-Secret sie
   authentifiziert — und ein `CONFIG_MODEL`, ein Pydantic-Modell, das sagt, wie
   die Dokumente zu finden sind. Das Credential ist nie eines seiner Felder.
4. Tragen Sie sie in `CONNECTOR_REGISTRY` in
   `app/services/rag/connectors/__init__.py` ein.

Einmal eingetragen, erscheint der Connector selbsttätig in der CLI, in der API
und in der Oberfläche.

## Fehlersuche { #troubleshooting }

### "No sync sources configured" { #no-sync-sources-configured }

Sie haben noch keine Quellen angelegt. Legen Sie eine mit `rag-source-add` (CLI)
oder `POST /api/v1/rag/sync/sources` (API) an.

### "Unknown connector type" { #unknown-connector-type }

Der angegebene Connector-Typ steht nicht in `CONNECTOR_REGISTRY`. Prüfen Sie die
verfügbaren Typen mit `rag-sources` oder `GET /api/v1/rag/sync/connectors`.
Google Drive (`gdrive`) ist verfügbar.
S3 (`s3`) ist verfügbar.
Website (`web`) ist verfügbar.

### Google Drive: "this source has no credential" { #google-drive-this-source-has-no-credential }

Die `secret_id` der Quelle ist leer, oder das benannte Vault-Secret wurde
gelöscht. Legen Sie das Dienstkonto-JSON im Vault ab und wählen Sie es im
Credential-Schritt der Quelle aus — `GOOGLE_DRIVE_CREDENTIALS_FILE` tritt nicht
an seine Stelle, und nur der CLI-Befehl `rag-sync-gdrive` liest diese
Einstellung.

### "A Google Drive source needs a service account credential" { #a-google-drive-source-needs-a-service-account-credential }

Die `secret_id` benennt ein Credential der falschen Art — etwa ein
AWS-Schlüsselpaar. Eine Drive-Quelle nimmt ein `gcp_service_account`, eine
S3-Quelle ein `aws_credentials`-Paar; der Assistent bietet nur die passenden an,
sodass dies über die API erreichbar ist.

### Google Drive: "folder ID may contain only letters, digits, '-' and '\_'" { #google-drive-folder-id-may-contain-only-letters-digits-and-_ }

Der Wert ist keine Drive-Folder-ID. Nehmen Sie sie aus der Ordner-URL: Sie ist
das letzte Segment, und nichts sonst aus dieser URL gehört in das Feld.

### Google Drive: "Cannot access folder" { #google-drive-cannot-access-folder }

Vergewissern Sie sich, dass Sie den Ordner für die E-Mail-Adresse des
Dienstkontos freigegeben haben. Das Dienstkonto braucht mindestens
Viewer-Zugriff.

### S3: "Cannot access bucket" { #s3-cannot-access-bucket }

Prüfen Sie, ob `S3_RAG_ACCESS_KEY`, `S3_RAG_SECRET_KEY` und `S3_RAG_ENDPOINT` in
der `.env` richtig gesetzt sind. Achten Sie bei MinIO darauf, dass der Endpunkt
den Port enthält (etwa `http://localhost:9000`).

### Website: "resolves to private/internal address" { #website-resolves-to-privateinternal-address }

Die Start-URL oder die Sitemap zeigt in das Netz des Deployments, oder ihr Name
löst dorthin auf. Eine Website-Quelle liest nur öffentliche Adressen. Um eine
interne Website zu indexieren, veröffentlichen Sie ihre Seiten an einem
öffentlichen Ort oder laden Sie die Dateien direkt hoch.

### Website: "The site's robots.txt could not be read, so it was not crawled" { #website-the-sites-robotstxt-could-not-be-read-so-it-was-not-crawled }

`/robots.txt` auf dem Host der Start-URL lief dreimal hintereinander in eine
Zeitüberschreitung oder antwortete mit einem Serverfehler (5xx). Der Crawler rät
nicht, was eine unerreichbare robots.txt erlauben würde, also bricht der Lauf ab.
Eine fehlende robots.txt (404) oder eine verbotene (403) bedeutet keine Regeln,
und der Crawl läuft weiter.

### Website: "The start URL … did not lead to an HTML page" { #website-the-start-url-did-not-lead-to-an-html-page }

Die Start-URL antwortete mit 404, leitete auf einen anderen Host oder aus
`path_prefix` heraus weiter oder lieferte etwas anderes als HTML. Öffnen Sie sie
in einem Browser und nehmen Sie dann die Adresse, bei der sie landet, als
`root_url`.

### Website: "robots.txt does not allow the start URL" { #website-robotstxt-does-not-allow-the-start-url }

Die Website bittet Crawler, diesen Pfad zu meiden. Wählen Sie eine Start-URL, die
die Website erlaubt, oder bitten Sie den Besitzer der Website, `AgenticOS-Crawler`
zuzulassen.

### Website: "… answered HTTP 403" oder "… could not be reached" { #website-answered-http-403-or-could-not-be-reached }

Die Seite verlangt einen Login, oder die Website hat den Crawler abgewiesen. War
die Antwort eine Zeitüberschreitung, 429 oder 5xx, schlug sie nach drei Versuchen
fehl. Jede solche Seite zählt als fehlgeschlagene Datei. In diesem Lauf wird
nichts entfernt, weil die Seiten dahinter nicht gesehen wurden.

### "The source could not be listed completely, so documents it may no longer hold were kept" { #the-source-could-not-be-listed-completely-so-documents-it-may-no-longer-hold-were-kept }

Die Auflistung brach vorzeitig ab: Ein Crawl erreichte `max_pages`, oder einige
Seiten konnten nicht gelesen werden. Was gefunden wurde, ist aufgenommen, und
nichts wurde entfernt. Erhöhen Sie `max_pages` oder grenzen Sie den Crawl mit
`path_prefix` ein, bis ein Lauf ohne diese Meldung endet.

### Geplante Syncs laufen nicht { #scheduled-syncs-are-not-running }

Es muss ein System für Hintergrundaufgaben laufen. Prüfen Sie, ob Ihr
Worker-Prozess aktiv ist:

Ohne Worker funktionieren nur manuelle Auslöser über CLI oder API.
