---
source_sha: 482d37ce9407
---

# Sync-Quellen einrichten { #configure-sync-sources }

Sync-Quellen holen Dokumente aus externen Diensten (Google Drive, S3/MinIO)
selbsttätig in Knowledge-Collections. Jede Quelle speichert einen Connector-Typ,
eine Ziel-Collection, connector-spezifische Einstellungen, einen Sync-Modus, einen
optionalen Zeitplan und die id des [Vault-Secrets](../secrets.md), das sie
authentifiziert.

Läuft ein Sync, listet der Connector die entfernten Dateien auf, lädt sie in ein
temporäres Verzeichnis herunter und schickt sie durch die übliche
Ingestion-Pipeline (parsen, chunken, einbetten, speichern). Ein Eintrag in
`SyncLog` hält das Ergebnis jedes einzelnen Sync-Vorgangs fest.

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
3. Wählen Sie einen Connector-Typ (Google Drive, S3). Die Formularfelder werden
   aus dem JSON Schema des `CONFIG_MODEL` des Connectors erzeugt.
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
| `failed` | Aufnahme fehlgeschlagen |
| `error_message` | Einzelheiten zum Fehler (wenn `status` gleich `error` ist) |
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

### Geplante Syncs laufen nicht { #scheduled-syncs-are-not-running }

Es muss ein System für Hintergrundaufgaben laufen. Prüfen Sie, ob Ihr
Worker-Prozess aktiv ist:

Ohne Worker funktionieren nur manuelle Auslöser über CLI oder API.
