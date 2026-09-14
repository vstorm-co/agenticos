---
source_sha: "482d37ce9407"
---

# Configura las fuentes de sincronización { #configure-sync-sources }

Las fuentes de sincronización traen documentos de servicios externos (Google
Drive, S3/MinIO) a las colecciones de conocimiento por su cuenta. Cada fuente
guarda un tipo de connector, una colección de destino, opciones propias del
connector, un modo de sincronización, un horario opcional y el id del
[secreto del vault](../secrets.md) que la autentica.

Cuando se ejecuta una sincronización, el connector lista los archivos remotos,
los descarga a un directorio temporal y los pasa por la cadena de ingesta
habitual (parsear, trocear, embeber, almacenar). Una entrada de `SyncLog` deja
constancia del resultado de cada operación de sincronización.

### La arquitectura de un vistazo { #architecture-at-a-glance }

| Componente | Ubicación | Función |
|-----------|----------|------|
| `BaseSyncConnector` | `app/services/rag/connectors/__init__.py` | Base abstracta de todos los connectores |
| `RemoteFile` | `app/services/rag/connectors/__init__.py` | Modelo de Pydantic que describe un archivo remoto |
| `CONNECTOR_REGISTRY` | `app/services/rag/connectors/__init__.py` | Asocia las cadenas de tipo de connector con sus clases |
| `SyncSource` (modelo de BD) | `app/db/models/sync_source.py` | Persiste la configuración de las fuentes |
| `SyncLog` (modelo de BD) | `app/db/models/sync_log.py` | Registra cada operación de sincronización |
| `SyncSourceService` | `app/services/sync_source.py` | Lógica de negocio del CRUD y del disparo manual |
| Comandos CLI de RAG | `app/commands/rag.py` | Interfaz de línea de comandos para gestionar fuentes |
| Rutas de la API de RAG | `app/api/routes/v1/rag.py` | API REST para gestionar fuentes |

## Inicio rápido -- CLI { #quick-start-cli }

### Listar los tipos de connector disponibles { #list-available-connector-types }

```bash
# Shows all registered connectors (e.g. gdrive, s3)
uv run agenticos cmd rag-sources
```

### Añadir una fuente de Google Drive -- sincronización cada 2 horas { #add-a-google-drive-source-sync-every-2-hours }

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

### Añadir una fuente de S3 -- solo sincronización manual { #add-an-s3-source-manual-sync-only }

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

### Lanzar una sincronización a mano { #trigger-sync-manually }

```bash
# Sync a single source by ID
uv run agenticos cmd rag-source-sync <source-id>

# Sync all active sources
uv run agenticos cmd rag-source-sync --all
```

### Eliminar una fuente { #remove-a-source }

```bash
uv run agenticos cmd rag-source-remove <source-id>
```

El `<source-id>` es un UUID que se imprime al crear la fuente y que aparece en
el listado de `rag-sources`.

## Inicio rápido -- interfaz { #quick-start-ui }

1. Ve a **Knowledge Base** y abre la pestaña **Sync**.
2. Pulsa **"+ Add Source"**.
3. Elige un tipo de connector (Google Drive, S3). Los campos del formulario se
   generan a partir del JSON Schema del `CONFIG_MODEL` del connector.
4. Rellena los campos de configuración propios del connector (por ejemplo, el
   ID de la carpeta o el nombre del bucket).
5. Elige una colección de destino, un modo de sincronización y un intervalo de
   ejecución.
6. Pulsa **"Create Source"**.
7. Usa el botón **"Sync Now"** para lanzar una sincronización inmediata, o
   espera a que el horario la dispare por sí solo.

La interfaz llama a la misma API REST que se documenta más abajo, así que todo
lo que puedes hacer desde ella lo puedes hacer también con `curl` o con
cualquier cliente HTTP.

## Modos de sincronización { #sync-modes }

| Modo | Comportamiento |
|------|----------|
| `full` | Sincroniza todo de nuevo. Todos los archivos se (re)ingestan y los documentos existentes se reemplazan. |
| `new_only` | Añade los archivos nuevos y actualiza los que han cambiado. Usa un hash SHA-256 para detectar cambios: los archivos sin cambios se omiten. |
| `update_only` | Solo actualiza archivos que ya están en la colección. Los archivos nuevos se omiten. Usa un hash SHA-256 para omitir los archivos sin cambios. |

!!! tip "`new_only` para casi todos los flujos"

    Añade los archivos nuevos y actualiza los modificados mientras omite los que
    no han cambiado, que es la sincronización incremental más rápida.
    `update_only` refresca los documentos existentes sin añadir ninguno nuevo;
    `full` es una reimportación limpia cada vez.

## Horario { #schedule }

El campo `schedule_minutes` controla con qué frecuencia se sincroniza la fuente
por sí sola:

| Valor | Significado |
|-------|---------|
| `0` (o `null`) | Solo manual -- se lanza desde la CLI o la interfaz |
| `30` | Cada 30 minutos |
| `120` | Cada 2 horas |
| `1440` | Una vez al día |

!!! warning "Un horario necesita el runner de Prefect"

    `check_scheduled_syncs_flow` es un deployment de Prefect que despierta cada
    60 segundos y lanza lo que toque, así que `schedule_minutes` no hace nada sin
    los contenedores `prefect-server` y `prefect-runner` que arranca `make dev`.
    Si no hay ninguno de los dos en marcha, solo un disparo manual (CLI, API o la
    interfaz) sincroniza algo.

## Configurar Google Drive { #google-drive-setup }

### 1. Crea una cuenta de servicio { #1-create-a-service-account }

1. Entra en la [Google Cloud Console](https://console.cloud.google.com/).
2. Crea un proyecto nuevo (o selecciona uno existente).
3. Activa la **Google Drive API**.
4. Ve a **IAM & Admin > Service Accounts** y crea una cuenta de servicio nueva.
5. Crea una clave JSON para la cuenta de servicio y descárgala.

### 2. Comparte tu carpeta de Drive { #2-share-your-drive-folder }

1. Abre Google Drive y ve a la carpeta que quieres sincronizar.
2. Pulsa **Share** y añade la dirección de correo de la cuenta de servicio
   (tiene la forma `name@project.iam.gserviceaccount.com`).
3. Concédele al menos acceso **Viewer**.

### 3. Dale la clave a la fuente { #3-give-the-source-the-key }

Pega el contenido del archivo de clave JSON en el campo **Service Account JSON**
de la fuente. Una fuente `gdrive` funciona con la credencial que lleva su propia
configuración y con nada más: no hay un valor de respaldo para todo el
despliegue, porque uno así dejaría que el `folder_id` de una fuente decidiera qué
se lista bajo la cuenta de servicio del operador.

`GOOGLE_DRIVE_CREDENTIALS_FILE` en `.env` sirve únicamente para el comando de
CLI `rag-sync-gdrive`.

### 4. Averigua el ID de la carpeta { #4-get-the-folder-id }

El ID de la carpeta es el último segmento de la URL de la carpeta de Google
Drive:

```
https://drive.google.com/drive/folders/1abc123def456ghi
                                        ^^^^^^^^^^^^^^^
                                        This is the folder ID
```

### 5. Campos de configuración del connector de Google Drive { #5-google-drive-connector-config-fields }

| Campo | Tipo | Obligatorio | Valor por defecto | Descripción |
|-------|------|----------|---------|-------------|
| `folder_id` | string | Sí | -- | El ID de la carpeta de Google Drive, tomado de la URL |
| `include_subfolders` | boolean | No | `true` | Incluir de forma recursiva los archivos de las subcarpetas |

La cuenta de servicio en sí **no** es un campo de configuración. Guárdala en el
vault como credencial de tipo `gcp_service_account` y apunta la fuente hacia ella
con `secret_id`: así se almacena una sola vez y la referencia cada fuente que la
necesite, en lugar de pegarla en cada una
([#937](https://github.com/vstorm-co/agenticos/issues/937)). Enviarla bajo
`config` se rechaza.

Un `folder_id` solo puede contener lo que Google emite: letras, dígitos, `-` y
`_`. Cualquier otra cosa se rechaza al crear la fuente, porque el id se
interpola en la consulta de Drive y una comilla simple dentro de él amplía lo
que esa consulta lista.

Los archivos de Google Docs, Sheets y Slides se exportan por sí solos a formatos
portables (PDF, XLSX, PPTX) durante la descarga. Un archivo cuyo nombre en Drive
contiene separadores de ruta se escribe como un único archivo dentro del
directorio de sincronización, nunca en la ruta que deletrea su nombre.

## Configurar S3 / MinIO { #s3-minio-setup }

### 1. Configura el entorno { #1-configure-the-environment }

Añade estas variables a tu `.env`:

```bash
S3_RAG_ENDPOINT=https://s3.amazonaws.com   # or your MinIO URL, e.g. http://localhost:9000
S3_RAG_ACCESS_KEY=your-access-key
S3_RAG_SECRET_KEY=your-secret-key
S3_RAG_REGION=us-east-1                    # required for AWS, optional for MinIO
```

En MinIO, el endpoint suele ser `http://minio:9000` (Docker) o
`http://localhost:9000` (local).

### 2. Campos de configuración del connector de S3 { #2-s3-connector-config-fields }

| Campo | Tipo | Obligatorio | Valor por defecto | Descripción |
|-------|------|----------|---------|-------------|
| `bucket` | string | Sí | -- | Nombre del bucket de S3 |
| `prefix` | string | No | `""` | Prefijo de clave que acota el alcance de la sincronización (por ejemplo, `documents/legal/`). Déjalo vacío para el bucket entero. |

## Referencia de la API { #api-reference }

Todos los endpoints de las fuentes de sincronización viven bajo
`/api/v1/rag/sync/`. Listar exige `collections:view` y todo lo que modifica una
fuente exige `collections:edit`, en ambos casos sobre la colección a la que
pertenece la fuente: no interviene ningún rol de administrador. Consulta
[quién puede llegar a una colección](../file-processing.md#who-may-reach-a-collection).

### CRUD de fuentes de sincronización { #sync-sources-crud }

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET` | `/api/v1/rag/sync/sources` | Lista todas las fuentes de sincronización configuradas |
| `POST` | `/api/v1/rag/sync/sources` | Crea una fuente de sincronización nueva |
| `PATCH` | `/api/v1/rag/sync/sources/{id}` | Modifica una fuente de sincronización existente |
| `DELETE` | `/api/v1/rag/sync/sources/{id}` | Borra una fuente de sincronización |
| `POST` | `/api/v1/rag/sync/sources/{id}/trigger` | Lanza una sincronización a mano |

### Connectores y registros { #connectors-logs }

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET` | `/api/v1/rag/sync/connectors` | Lista los tipos de connector disponibles con sus esquemas de configuración |
| `GET` | `/api/v1/rag/sync/logs` | Lista el historial de sincronizaciones (se puede filtrar por `collection_name`) |

### Ejemplo: crear una fuente con la API { #example-create-a-source-via-api }

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

### Ejemplo: lanzar una sincronización con la API { #example-trigger-a-sync-via-api }

```bash
curl -X POST http://localhost:8000/api/v1/rag/sync/sources/{source_id}/trigger \
  -H "Authorization: Bearer $TOKEN"
```

### Ejemplo: consultar el historial de sincronizaciones { #example-check-sync-history }

```bash
curl http://localhost:8000/api/v1/rag/sync/logs?limit=10 \
  -H "Authorization: Bearer $TOKEN"
```

### Ejemplo: descubrir los connectores disponibles { #example-discover-available-connectors }

```bash
curl http://localhost:8000/api/v1/rag/sync/connectors \
  -H "Authorization: Bearer $TOKEN"
```

La respuesta incluye el `config_schema` de cada connector, que el frontend usa
para renderizar formularios dinámicos. También resulta útil para construir
integraciones de forma programática.

## Modificar una fuente { #updating-a-source }

Puedes actualizar cualquier subconjunto de campos de una fuente existente con
`PATCH`:

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

Campos modificables: `name`, `config`, `sync_mode`, `schedule_minutes`,
`is_active`, `collection_name`.

Pon `is_active` en `false` para pausar una fuente sin borrarla.

## Supervisar las sincronizaciones { #monitoring-sync-operations }

Cada sincronización crea una entrada de `SyncLog` con estos campos:

| Campo | Descripción |
|-------|-------------|
| `source` | El tipo de connector, o `"local"` para la ingesta desde la CLI |
| `collection_name` | La colección de destino |
| `status` | `running`, `done` o `error` |
| `mode` | `full`, `new_only` o `update_only` |
| `total_files` | Número de archivos encontrados |
| `ingested` | Ingestados correctamente (nuevos) |
| `updated` | Reingestados correctamente (reemplazados) |
| `skipped` | Omitidos (ya presentes o sin cambios) |
| `failed` | No se pudieron ingestar |
| `error_message` | Detalle del error (si `status` es `error`) |
| `started_at` | Cuándo empezó la sincronización |
| `completed_at` | Cuándo terminó la sincronización |

Consulta los registros desde la salida de la CLI o desde la API:

```bash
curl http://localhost:8000/api/v1/rag/sync/logs?collection_name=legal&limit=5 \
  -H "Authorization: Bearer $TOKEN"
```

## Añadir connectores propios { #adding-custom-connectors }

Para añadir un tipo de connector nuevo (por ejemplo, Notion, Confluence o
Dropbox), consulta
[Añade un connector de sincronización](./add-sync-connector.md).

La versión corta:

1. Crea una clase que herede de `BaseSyncConnector` en
   `app/services/rag/connectors/`.
2. Implementa `list_files()`, `_fetch()` y, opcionalmente,
   `validate_config()`.
3. Declara `SECRET_KIND` —qué tipo de secreto del vault lo autentica— y un
   `CONFIG_MODEL`, un modelo de Pydantic que dice cómo encontrar los documentos.
   La credencial nunca es uno de sus campos.
4. Regístralo en `CONNECTOR_REGISTRY`, en
   `app/services/rag/connectors/__init__.py`.

Una vez registrado, el connector aparece por sí solo en la CLI, en la API y en
la interfaz.

## Resolución de problemas { #troubleshooting }

### "No sync sources configured" { #no-sync-sources-configured }

Todavía no has creado ninguna fuente. Crea una con `rag-source-add` (CLI) o con
`POST /api/v1/rag/sync/sources` (API).

### "Unknown connector type" { #unknown-connector-type }

El tipo de connector que has indicado no está en `CONNECTOR_REGISTRY`. Consulta
los tipos disponibles con `rag-sources` o con
`GET /api/v1/rag/sync/connectors`.
Google Drive (`gdrive`) está disponible.
S3 (`s3`) está disponible.

### Google Drive: "this source has no credential" { #google-drive-this-source-has-no-credential }

El `secret_id` de la fuente está vacío, o el secreto del vault que nombraba ha
sido borrado. Guarda el JSON de la cuenta de servicio en el vault y elígelo en el
paso de credencial de la fuente: `GOOGLE_DRIVE_CREDENTIALS_FILE` no lo sustituye,
y solo el comando de CLI `rag-sync-gdrive` lee ese ajuste.

### "A Google Drive source needs a service account credential" { #a-google-drive-source-needs-a-service-account-credential }

El `secret_id` nombra una credencial del tipo equivocado: un par de claves de
AWS, por ejemplo. Una fuente de Drive toma un `gcp_service_account` y una fuente
de S3 un par `aws_credentials`; el asistente solo ofrece las que corresponden,
así que a esto se llega a través de la API.

### Google Drive: "folder ID may contain only letters, digits, '-' and '\_'" { #google-drive-folder-id-may-contain-only-letters-digits-and-_ }

El valor no es un id de carpeta de Drive. Tómalo de la URL de la carpeta: es el
último segmento, y nada más de esa URL pertenece al campo.

### Google Drive: "Cannot access folder" { #google-drive-cannot-access-folder }

Asegúrate de haber compartido la carpeta con el correo de la cuenta de servicio.
La cuenta de servicio necesita al menos acceso Viewer.

### S3: "Cannot access bucket" { #s3-cannot-access-bucket }

Comprueba que `S3_RAG_ACCESS_KEY`, `S3_RAG_SECRET_KEY` y `S3_RAG_ENDPOINT` están
bien puestos en el `.env`. En MinIO, asegúrate de que el endpoint incluye el
puerto (por ejemplo, `http://localhost:9000`).

### Las sincronizaciones programadas no se ejecutan { #scheduled-syncs-are-not-running }

Tiene que haber un sistema de tareas en segundo plano en marcha. Comprueba que
tu proceso worker está activo:

Sin un worker, solo funcionan los disparos manuales desde la CLI o la API.
