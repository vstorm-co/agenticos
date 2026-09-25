---
source_sha: "f1c199421e4a"
---

# Configura las fuentes de sincronización { #configure-sync-sources }

Las fuentes de sincronización traen documentos de servicios externos (Google
Drive, S3/MinIO, un sitio web público, un repositorio Git, un sitio de SharePoint o
un OneDrive) a las colecciones de conocimiento por su cuenta. Cada fuente guarda un tipo de connector, una colección de destino,
opciones propias del connector, un modo de sincronización, un horario opcional y
el id del [secreto del vault](../secrets.md) que la autentica - un sitio web no
necesita ninguno.

Cuando se ejecuta una sincronización, el connector lista los archivos remotos,
los descarga a un directorio temporal y los pasa por la cadena de ingesta
habitual (parsear, trocear, embeber, almacenar). Cuando el listado está completo,
se eliminan los documentos que la fuente trajo antes y ya no lista. Una entrada
de `SyncLog` deja constancia del resultado de cada operación de sincronización.

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
# Shows all registered connectors (e.g. gdrive, s3, git, sharepoint)
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

### Añadir una fuente de Git -- la documentación de un repositorio, cada noche { #add-a-git-source-a-repositorys-docs-nightly }

```bash
uv run agenticos cmd rag-source-add \
  --name "Handbook" \
  --type git \
  --org 0c8f2b1e-... \
  --collection handbook \
  --config '{"repository_url": "https://github.com/acme/handbook.git", "branch": "main", "path_prefix": "docs"}' \
  --sync-mode new_only \
  --schedule 1440
```

Después elige su token de acceso como credencial de la fuente en la interfaz, o
envía `secret_id` con un `PATCH` — consulta
[Configurar un repositorio Git](#git-repository-setup).

### Añadir una fuente de SharePoint -- una carpeta de una biblioteca, cada 6 horas { #add-a-sharepoint-source-one-library-folder-every-6-hours }

```bash
uv run agenticos cmd rag-source-add \
  --name "HR policies" \
  --type sharepoint \
  --org 0c8f2b1e-... \
  --collection hr \
  --secret-id <vault-secret-id> \
  --config '{"site_url": "https://contoso.sharepoint.com/sites/HR", "folder_path": "Policies"}' \
  --sync-mode new_only \
  --schedule 360
```

`--secret-id` es la app de Microsoft Entra en el vault de la organización —
consulta [Configurar SharePoint y OneDrive](#sharepoint-and-onedrive-setup).

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
3. Elige un tipo de connector (Google Drive, S3, Website, Git
   repository, SharePoint & OneDrive). Los campos del
   formulario se generan a partir del JSON Schema del `CONFIG_MODEL` del
   connector. Un sitio web no tiene paso de credencial.
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

### Qué elimina una sincronización { #what-a-sync-removes }

En todos los modos, una sincronización elimina los documentos que su fuente trajo
antes y ya no lista: una página retirada del sitio, un archivo borrado de la
carpeta de Drive, un objeto quitado del bucket. El registro de sincronización los
cuenta en `removed`.

No elimina nada salvo que el listado estuviera **completo**. Un crawl que se
detuvo en su límite de páginas, o que no pudo leer una de ellas, no ha visto lo
que no lista. Ese run conserva todos los documentos y lo indica en el mensaje del
registro de sincronización. La siguiente sincronización con un listado completo
elimina lo que ya no está. Un documento que no se pudo eliminar cuenta como un
archivo fallido, y la siguiente sincronización lo vuelve a intentar.

Cada fuente ejecuta una sola sincronización a la vez. Una sincronización iniciada
mientras otra de la misma fuente sigue en marcha no arranca, y su registro lo
indica.

Solo se eliminan los documentos de la propia fuente. Una subida, o un documento
que otra fuente trajo a la misma colección, no se toca nunca. Un documento
ingestado antes de que su fuente registrara esto (septiembre de 2026) se
conserva hasta que la fuente vuelva a ingestarlo.

### Qué hace una segunda sincronización { #what-a-second-sync-does }

Una sincronización posterior a la primera hace tan poco como la fuente le
permite:

- **Un archivo sin cambios cuesta una descarga, no un embedding.** Su SHA-256
  coincide con el del documento almacenado, así que se cuenta como `skipped` y
  no se vuelve a parsear ni a embeber.
- **Una fuente sin cambios cuesta una petición.** Un connector capaz de decir en
  qué punto está todo su contenido —el commit de cabeza de una rama de Git, el
  feed de cambios de una biblioteca de SharePoint— lo registra después de cada ejecución que termina sin ningún fallo. La siguiente
  ejecución `new_only` o `update_only` que encuentra el mismo valor, con la misma
  configuración, se detiene antes de listar nada: su registro no muestra ningún
  archivo procesado, y no elimina nada. Cambiar la configuración, la colección o el modo hace que la
  siguiente ejecución lo vuelva a leer todo, y `full` nunca se detiene antes.
- **Un archivo que una sincronización interrumpida dejó a medias se corrige.**
  Un worker detenido después de guardar los vectores de un archivo y antes de
  registrarlos los deja sin ninguna fila que los siga. La siguiente sincronización
  de esa fuente borra lo que nada sigue y vuelve a ingerir el archivo; mientras
  un archivo así espera, no se detiene antes.

Una ejecución con un archivo fallido no registra ningún estado, así que la
siguiente lee la fuente entera y vuelve a intentarlo.

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

## Configurar un sitio web { #website-setup }

Una fuente `web` lee un sitio web público, normalmente el sitio de documentación
de un producto. No necesita credencial ni entrada en el vault. Dale una URL de
inicio y, o bien sigue los enlaces desde esa página, o bien lee las páginas que
lista un sitemap.

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

### Campos de configuración del connector de sitio web { #website-connector-config-fields }

| Campo | Tipo | Obligatorio | Valor por defecto | Descripción |
|-------|------|----------|---------|-------------|
| `root_url` | string | Sí | -- | La página desde la que empieza el crawl. Su host es el único host que lee la fuente. |
| `max_depth` | integer | No | `2` | A cuántos enlaces de distancia de la URL de inicio seguir, de `0` a `10`. `0` lee solo la página de inicio. |
| `path_prefix` | string | No | la carpeta de la URL de inicio | Solo se leen las páginas cuya ruta empieza por esto. `https://docs.example.com/guide/intro` lee `/guide/` por defecto; pon `/` para el host entero. |
| `sitemap_url` | string | No | -- | Lee las páginas que lista este sitemap en lugar de seguir enlaces. Tiene que estar en el host de la URL de inicio y usar `https://` cuando la URL de inicio lo usa. Un índice de sitemaps se sigue hasta sus sitemaps. |
| `max_pages` | integer | No | `500` | El crawl se detiene tras leer este número de páginas, de `1` a `5000`. |

### Qué acota un crawl { #what-bounds-a-crawl }

- **Un host y una ruta.** Los enlaces a otros hosts, y a rutas fuera de
  `path_prefix`, no se siguen. Una redirección que salga de ellos tampoco se
  sigue. Una URL de inicio en `https://` nunca se abandona por `http://`: no se
  sigue un enlace ni una redirección a una página sin cifrar.
- **La red del deployment queda fuera de alcance.** Cada petición - robots.txt,
  el sitemap, cada página y cada redirección - se comprueba contra la misma
  política SSRF que los webhooks y los servidores MCP. Se envía a la dirección que
  pasó la comprobación. Una URL de inicio que resuelve a una dirección privada, de
  loopback, link-local o de metadatos de la nube se rechaza al guardar la fuente.
- **Se respeta robots.txt** para sitemaps y páginas, incluido `Crawl-delay` de
  hasta diez segundos. El crawler se identifica como `AgenticOS-Crawler`. Espera
  al menos medio segundo entre peticiones, y se respeta una página que diga
  `noindex` o `nofollow`. Una página que un sitemap sigue listando después de
  decir `noindex`, o de desaparecer, se elimina de la colección.
- **Tamaño y tiempo.** Una página de más de 5 MB no se lee. El crawl se detiene en
  `max_pages`. Una sincronización deja de leer el sitio al cabo de seis horas, y
  una sincronización que se detuvo no elimina nada.

Cada página se guarda como un documento Markdown que contiene su texto y la URL
de la que procede, sin su query string. La navegación, las cabeceras, los pies de página y los scripts
se dejan fuera. Una página solo se vuelve a embeber cuando cambia su texto. Un
nuevo sello de build o un script de seguimiento en el marcado no cuentan como
cambio.

### Quién puede leer lo que importa { #who-can-read-what-it-imports }

Una fuente de sitio web no tiene credencial, así que su alcance es lo que el
sitio muestra a cualquiera en internet. Nunca pasa de un login. Todo lo que
importa lo puede buscar cualquiera que pueda buscar en la colección que alimenta,
como con cualquier otra fuente. Consulta
[quién acaba pudiendo leer lo que ingirió una fuente](../file-processing.md#who-ends-up-able-to-read-what-a-source-ingested).

Solo se importan páginas HTML. Un PDF u otro archivo enlazado desde una página no
se descarga.

## Configurar un repositorio Git { #git-repository-setup }

Una fuente `git` lee la documentación de un repositorio por HTTPS: GitHub, GitLab
o cualquier otro host que sirva git por HTTPS. Necesita la URL de clonado y un
token de acceso, no la API de ninguna de las dos plataformas.

### 1. Emite un token para ese único repositorio { #1-issue-a-token-for-the-one-repository }

**El alcance del token es el alcance de la fuente.** Todo lo que la fuente
ingiere pasa a poder buscarlo cualquiera que pueda leer la colección, así que un
token capaz de leer todos los repositorios privados que puede leer su dueño es un
token capaz de publicarlos todos para ese público. Consulta [quién acaba pudiendo
leer lo que ingirió una
fuente](../file-processing.md#who-ends-up-able-to-read-what-a-source-ingested).

- **GitHub:** un personal access token de tipo fine-grained, con *Only select
  repositories*, ese único repositorio y **Contents: Read-only** como único
  permiso.
- **GitLab:** un project access token en ese único proyecto, con el rol
  **Reporter** y solo el scope **`read_repository`**.

Ponle una fecha de caducidad. Cuando caduque, la siguiente sincronización de la
fuente falla con *the repository refused the source's token*, y la solución es un
token nuevo en el mismo secreto del vault.

### 2. Añádelo al vault { #2-add-it-to-the-vault }

Añade el token al vault como **Git access token**, con el **host** al que
pertenece: `github.com`, `gitlab.com` o tu propio servidor, como
`git.example.com:8443`. Un host con letras que no son ASCII se escribe en su forma
codificada, por ejemplo `xn--bcher-kva.example` para `bücher.example`. Después
elige el token en el paso de credencial de la fuente. Se
envía en una cabecera HTTP `Authorization`, nunca en la URL ni en una línea de
comandos que otro proceso pueda leer.

**El host es del token, no de la fuente.** Quien edita una fuente elige la URL de
su repositorio, y un token solo se envía al host con el que se añadió. Así que
editar una fuente no puede dirigir el token de la organización a otro servidor, y
ningún otro tipo de clave, como la API key de un provider de modelos, puede
elegirse para una fuente de Git.

### 3. Campos de configuración del connector de Git { #3-git-connector-config-fields }

| Campo | Tipo | Obligatorio | Valor por defecto | Descripción |
|-------|------|----------|---------|-------------|
| `repository_url` | string | Sí | -- | La URL de clonado HTTPS, por ejemplo `https://github.com/acme/handbook.git`. Sin nombre de usuario ni token. |
| `branch` | string | No | `main` | La rama que se lee. |
| `path_prefix` | string | No | -- | Un directorio dentro del repositorio, por ejemplo `docs`. Déjalo vacío para el repositorio entero. |
| `include` | lista de strings | No | `**/*.md`, `**/*.txt` | Qué archivos se ingieren, como patrones al estilo de `.gitignore` relativos a `path_prefix`. |

El valor por defecto es la documentación, no el árbol entero: el código fuente de
un repositorio no es un corpus, e ingerirlo llena la base de conocimiento de
código que nadie ha pedido buscar. Añade un patrón como `**/*.pdf` para otro
formato que lea el parser de la colección. Un patrón no puede empezar por `!`.

Cada archivo es un documento cuya dirección es
`git://<host>/<owner>/<repo>@<branch>/<path>`, con `:<port>` tras el host cuando
el puerto no es 443. La rama forma parte de la dirección, así que dos fuentes que leen dos ramas de un mismo repositorio en una
misma colección mantienen documentos separados.

### 4. Qué transfiere una sincronización { #4-what-a-sync-transfers }

La primera petición de cada sincronización es `git ls-remote` para la rama: más o
menos un kilobyte. Si el commit de cabeza no se ha movido desde la última
ejecución limpia, la sincronización se detiene ahí. Si se ha movido, el connector
hace un clonado superficial, parcial y disperso (shallow, partial, sparse): un
solo commit, y solo los archivos que casan con los patrones de inclusión. Por eso
la documentación de un monorepo cuesta lo que su documentación, no lo que su
árbol de código.

Antes de que el clonado escriba nada en el disco del worker, el connector mide
cada archivo que escribiría. Un archivo que supera el límite de documento de la
base de conocimiento (`MAX_UPLOAD_SIZE_MB`, 50 MB por defecto), o más de 512 MB
de archivos en total, se rechaza, y no se escribe nada.

Los enlaces simbólicos y los submódulos no se siguen, y un enlace no se ingiere
como documento.

### Reglas de red { #network-rules }

La URL tiene que ser `https://`. Su host se resuelve una sola vez y se comprueba
como cualquier otra dirección que elige un inquilino: un host que resuelve a una
dirección privada, de loopback o link-local se rechaza al guardar la fuente y de
nuevo al sincronizar, y git solo se conecta a las direcciones que esa
comprobación aprobó. Las redirecciones no se siguen. Un deployment detrás de un
proxy de salida (`HTTPS_PROXY`) lo sigue usando; en ese caso el proxy resuelve el
host por su cuenta.

La imagen del worker incluye `git`. Un worker construido a partir de otra imagen
necesita `git` 2.37 o posterior en su `PATH`.

## Configurar SharePoint y OneDrive { #sharepoint-and-onedrive-setup }

Una fuente `sharepoint` lee una biblioteca de documentos a través de Microsoft
Graph: la biblioteca de un sitio de SharePoint, o el OneDrive de una persona, que
Microsoft 365 guarda como un sitio propio. Puede leer la biblioteca entera o una
carpeta dentro de ella. Inicia sesión como un registro de aplicación de Microsoft
Entra que un administrador de tu tenant crea una sola vez.

### 1. Registra una app en Microsoft Entra { #1-register-an-app-in-microsoft-entra }

En el [Microsoft Entra admin center](https://entra.microsoft.com), abre
**App registrations → New registration**. Dale un nombre como *AgenticOS
sync*, deja **Accounts in this organizational directory only** y deja vacío el
redirect URI. La fuente inicia sesión como la propia app, no como una persona.

En la **Overview** de la app, anota el **Application (client) ID** y el
**Directory (tenant) ID**. En **Certificates & secrets**, añade un client secret
y copia su **Value**. El valor se muestra una sola vez. El *ID* del secreto no es
lo que necesita la fuente.

### 2. Concédele un sitio, no el tenant { #2-grant-it-one-site-not-the-tenant }

**El alcance de la app es el alcance de la fuente.** Todo lo que la fuente
ingiere pasa a poder buscarlo cualquiera que pueda leer la colección que
alimenta. Consulta [quién acaba pudiendo leer lo que ingirió una
fuente](../file-processing.md#who-ends-up-able-to-read-what-a-source-ingested).

En **API permissions**, añade el permiso de **aplicación** de Microsoft Graph
**`Sites.Selected`** y concede el consentimiento de administrador para él. Por sí
solo, `Sites.Selected` no lee nada. Después, un administrador concede a la app
acceso de lectura al único sitio que lee la fuente:

```http
POST https://graph.microsoft.com/v1.0/sites/{site-id}/permissions
Content-Type: application/json

{
  "roles": ["read"],
  "grantedToIdentities": [
    {"application": {"id": "<client-id>", "displayName": "AgenticOS sync"}}
  ]
}
```

Esa llamada necesita `Sites.FullControl.All`, así que un administrador la hace
desde Graph Explorer o con `Grant-PnPAzureADAppSitePermission` de PnP PowerShell,
y no con la propia app.
`GET https://graph.microsoft.com/v1.0/sites/contoso.sharepoint.com:/sites/HR?$select=id`
devuelve el id del sitio. Un OneDrive se concede de la misma forma, a través de su
sitio: `contoso-my.sharepoint.com:/personal/jane_contoso_com`.

!!! danger "`Files.Read.All` o `Sites.Read.All` hacen legibles todas las bibliotecas del tenant"

    Esos permisos se consienten para todo el tenant. Una fuente que los tiene
    sigue leyendo solo la biblioteca que nombra. Pero quien puede editar la
    fuente puede apuntar su URL de sitio a cualquier sitio u OneDrive de la
    organización, y la siguiente sincronización hace que esa biblioteca pueda
    buscarla cualquiera que pueda leer la colección. Nada en este producto puede
    saber qué permiso se dio a la app, porque un token no lo dice. Usa
    `Sites.Selected` y concede una app por cada público.

### 3. Añádela al vault { #3-add-it-to-the-vault }

Añade la app al vault como **Microsoft Entra app**: el id del tenant (o el
dominio del tenant, como `contoso.onmicrosoft.com`), el client id y el valor del
client secret. Después elígela en el paso de credencial de la fuente. El secreto
solo se envía a `login.microsoftonline.com`, para iniciar sesión.

Un client secret caduca, como mucho a los dos años. Cuando ha caducado, la
siguiente sincronización falla con *Microsoft Entra refused the app
registration's credentials (invalid_client)*. Añade un secreto nuevo a la app y
sustituye el valor en el mismo secreto del vault. Todas las fuentes que lo usan
recogen el valor nuevo en su siguiente sincronización.

### 4. Campos de configuración del connector de SharePoint { #4-sharepoint-connector-config-fields }

| Campo | Tipo | Obligatorio | Valor por defecto | Descripción |
|-------|------|----------|---------|-------------|
| `site_url` | string | Sí | -- | El sitio, por ejemplo `https://contoso.sharepoint.com/sites/HR`, o un OneDrive, por ejemplo `https://contoso-my.sharepoint.com/personal/jane_contoso_com`. Solo el sitio: una URL de biblioteca o de página copiada del navegador se rechaza. |
| `library` | string | No | la biblioteca por defecto del sitio | El nombre de la biblioteca tal como lo muestra SharePoint, por ejemplo `Documents`. Un OneDrive solo tiene su biblioteca por defecto. |
| `folder_path` | string | No | -- | Una carpeta dentro de la biblioteca, por ejemplo `Policies/HR`. Déjalo vacío para la biblioteca entera. |
| `include_subfolders` | boolean | No | `true` | Si se leen las carpetas que hay bajo `folder_path`. |
| `extensions` | lista de strings | No | `.pdf`, `.docx`, `.md`, `.txt` | Qué tipos de archivo se ingieren. Añade `.pptx`, `.xlsx` u otro tipo solo si el parser de la colección lo lee: un archivo que el parser no puede leer cuenta como archivo fallido en cada sincronización. |

Cada archivo es un documento cuya dirección es `sharepoint://<drive-id>/<item-id>`.
La dirección sigue al archivo, no a su ruta, así que un archivo que se renombra o
se mueve dentro de la biblioteca conserva su documento. El documento conserva el
nombre de archivo con el que se ingirió hasta que cambia el contenido del archivo.

Los blocs de notas de OneNote y los archivos de otros tipos no se ingieren.

### 5. Qué transfiere una sincronización { #5-what-a-sync-transfers }

Cada sincronización empieza por el feed de cambios de Microsoft Graph para la
biblioteca. Cuando nada en la biblioteca ha cambiado desde la última ejecución
limpia, la sincronización se detiene ahí: una petición y ningún listado. El feed
cubre la biblioteca entera, porque Graph solo lo ofrece para la raíz de una
biblioteca. Por eso un cambio en otra carpeta de la misma biblioteca hace que la
siguiente sincronización vuelva a listar la carpeta de la fuente.

Cuando algo ha cambiado, la sincronización lista la carpeta y descarga todos los
archivos de los tipos configurados. Un archivo cuyo contenido no ha cambiado se
omite entonces antes de embeberlo, así que solo los archivos nuevos y modificados
cuestan un embedding. Un archivo se descarga desde la dirección que Graph da para
él, sin el token de la app. Un archivo que supera el límite de documento de la
base de conocimiento (`MAX_UPLOAD_SIZE_MB`, 50 MB por defecto) no se descarga y
cuenta como archivo fallido.

Graph frena a un cliente que lee deprisa. Una petición que Graph limita (HTTP
429) o que falla con un 5xx o un error de red se intenta cuatro veces en total, y
la sincronización espera lo que pida el `Retry-After` de Graph, hasta un minuto.
Una carpeta que aun así no se puede listar se nombra en el registro de
sincronización, y esa sincronización no elimina nada, porque no se vieron los
archivos de esa carpeta. Los archivos de las demás carpetas se ingieren igualmente.

Un archivo borrado después del listado y antes de su descarga se elimina como un
archivo que el listado no nombró.

### Red { #network }

El worker necesita HTTPS de salida hacia `login.microsoftonline.com`,
`graph.microsoft.com` y los hosts `*.sharepoint.com` de tu tenant. Nada de lo que
escribe quien edita una fuente se convierte en una dirección a la que se conecte
el worker: la URL del sitio es solo un nombre que Graph busca. Las nubes
nacionales de Microsoft, como US Government y China, usan otros hosts y no están
soportadas.

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
| `failed` | No se pudieron ingestar, incluidas las páginas o archivos que el listado no pudo leer y los documentos que no se pudieron eliminar |
| `removed` | Eliminados porque la fuente ya no los lista (consulta [qué elimina una sincronización](#what-a-sync-removes)) |
| `error_message` | Qué salió mal, o por qué no se eliminó nada. Un run puede estar en `done` y aun así tener un mensaje, por ejemplo cuando un crawl se detuvo en su límite de páginas |
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
Website (`web`) está disponible.
Git (`git`) está disponible.

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

### Sitio web: "resolves to private/internal address" { #website-resolves-to-privateinternal-address }

La URL de inicio, o el sitemap, apunta dentro de la red del deployment, o su
nombre resuelve ahí. Una fuente de sitio web solo lee direcciones públicas. Para
indexar un sitio interno, publica sus páginas en algún lugar público o sube los
archivos directamente.

### Sitio web: "The site's robots.txt could not be read, so it was not crawled" { #website-the-sites-robotstxt-could-not-be-read-so-it-was-not-crawled }

`/robots.txt` en el host de la URL de inicio agotó el tiempo de espera o
respondió con un error del servidor (5xx) tres veces seguidas. El crawler no
adivina qué permitiría un robots.txt inaccesible, así que el run se detiene. Un
robots.txt que falta (404) o que está prohibido (403) significa que no hay
reglas, y el crawl sigue adelante.

### Sitio web: "The start URL … did not lead to an HTML page" { #website-the-start-url-did-not-lead-to-an-html-page }

La URL de inicio respondió 404, redirigió a otro host o fuera de `path_prefix`,
o sirvió algo que no es HTML. Ábrela en un navegador y usa como `root_url` la
dirección en la que acaba.

### Sitio web: "robots.txt does not allow the start URL" { #website-robotstxt-does-not-allow-the-start-url }

El sitio pide a los crawlers que no entren en esa ruta. Elige una URL de inicio
que el sitio permita, o pide al propietario del sitio que permita
`AgenticOS-Crawler`.

### Sitio web: "… answered HTTP 403" o "… could not be reached" { #website-answered-http-403-or-could-not-be-reached }

La página necesita un login, o el sitio rechazó al crawler. Falló tras tres
intentos si la respuesta fue un timeout, un 429 o un 5xx. Cada página así cuenta
como un archivo fallido. En ese run no se elimina nada, porque no se vieron las
páginas que había detrás.

### "The source could not be listed completely, so documents it may no longer hold were kept" { #the-source-could-not-be-listed-completely-so-documents-it-may-no-longer-hold-were-kept }

El listado se quedó corto: un crawl alcanzó `max_pages`, algunas páginas no se
pudieron leer, o una carpeta de SharePoint no se pudo listar. Lo que se encontró
se ingestó, y no se eliminó nada. Para un sitio web, sube `max_pages`, o acota el
crawl con `path_prefix`, hasta que un run termine sin este mensaje. Para
SharePoint, consulta más abajo la entrada de esa carpeta.

### Git: "The repository refused the source's token" { #git-the-repository-refused-the-sources-token }

El token ha caducado, se ha revocado o no puede leer este repositorio. Emite uno
nuevo como se describe en [Configurar un repositorio Git](#git-repository-setup)
y sustituye el valor del secreto del vault que usa la fuente; todas las fuentes
que usan ese secreto lo recogen en su siguiente sincronización.

### Git: "The repository was not found, or the source's token cannot see it" { #git-the-repository-was-not-found-or-the-sources-token-cannot-see-it }

Comprueba primero la URL de clonado. Un repositorio privado responde *not found*
en lugar de *forbidden* a un token que no puede leerlo, así que un token
fine-grained emitido para otro repositorio se ve así.

### Git: "The repository has no branch named …" { #git-the-repository-has-no-branch-named }

El campo `branch` nombra una rama que el repositorio no tiene. Su valor por
defecto es `main`; la rama por defecto de un repositorio más antiguo puede ser
`master`.

### Git: "… is … MB, and a synced file may be at most … MB" { #git-is-mb-and-a-synced-file-may-be-at-most-mb }

Un archivo que casa con los patrones de inclusión supera el límite de documento
de la base de conocimiento. Acota `include` o `path_prefix` para que ese archivo
quede fuera. En esta sincronización no se escribió nada.

### Git: "… over the … MB one sync may check out" { #git-over-the-mb-one-sync-may-check-out }

Todos los archivos que casan con los patrones de inclusión suman más de 512 MB.
Acota `include` o `path_prefix`, o divide el repositorio en varias fuentes, cada
una con su propio prefijo.

### Git: "This token was added for …, and the repository is on …" { #git-this-token-was-added-for-and-the-repository-is-on }

El repositorio de la fuente está en un host distinto de aquel con el que se añadió
su token. O la URL es incorrecta, o la fuente necesita un token añadido para ese
host. No se envió nada al host del repositorio.

### Git: "A Git source needs a Git access token" { #git-a-git-source-needs-a-git-access-token }

La fuente nombra un secreto de otro kind, como una API key. Añade el token como
**Git access token**, con su host, y elige ese.

### "Another sync of this source is still running" { #another-sync-of-this-source-is-still-running }

Se lanzó una ejecución mientras había otra de la misma fuente en curso, así que no
arrancó. La ejecución en curso termina con normalidad; vuelve a lanzarla después
si la fuente ha cambiado entretanto.

### Git: "… resolves to a private address" { #git-resolves-to-a-private-address }

El host del repositorio resuelve dentro de la red del deployment, así que la
fuente se rechaza. Una fuente de sincronización no puede llegar a un servidor Git
autoalojado en una dirección interna.

### Git: "git is not installed on this worker" { #git-git-is-not-installed-on-this-worker }

El worker se ejecuta desde una imagen sin `git`. El `backend/Dockerfile` que se
distribuye lo instala; a una imagen propia hay que añadírselo.

### Git: una sincronización terminó sin ningún archivo procesado { #git-a-sync-finished-with-no-files-processed }

El commit de cabeza de la rama es el mismo que leyó la última ejecución limpia,
con la misma configuración, así que no había nada que hacer. Cambia la fuente a
`full` durante una ejecución para volver a leerlo todo de todos modos.

### SharePoint: "Microsoft Entra refused the app registration's credentials (…)" { #sharepoint-microsoft-entra-refused-the-app-registrations-credentials }

Microsoft Entra no inició la sesión de la app. `invalid_client` suele significar
que el client secret ha caducado o que el vault guarda el ID del secreto en lugar
de su valor. `unauthorized_client` o `invalid_request` suele significar que el id
del tenant o el client id son incorrectos. Comprueba los tres valores con la
**Overview** y **Certificates & secrets** de la app, y sustitúyelos en el secreto
del vault.

### SharePoint: "Microsoft Graph did not accept the app's token for …" { #sharepoint-microsoft-graph-did-not-accept-the-apps-token-for }

La app inició sesión, pero su token no lleva ningún permiso de Microsoft Graph.
Añade el permiso de **aplicación** `Sites.Selected`, no uno delegado, y concede el
consentimiento de administrador, como se describe en el
[paso 2](#2-grant-it-one-site-not-the-tenant).

### SharePoint: "Microsoft Graph denied the app access to … (accessDenied)" { #sharepoint-microsoft-graph-denied-the-app-access-to-accessdenied }

La app tiene `Sites.Selected` pero ninguna concesión sobre este sitio. Concédele
`read` sobre el sitio, como se describe en el
[paso 2](#2-grant-it-one-site-not-the-tenant). Si el mensaje nombra una carpeta
bajo la carpeta de la fuente, esa carpeta tiene permisos propios que excluyen a la
app. El resto de la biblioteca se ingirió y no se eliminó nada.

### SharePoint: "There is no SharePoint site at …, or the app cannot see it" { #sharepoint-there-is-no-sharepoint-site-at-or-the-app-cannot-see-it }

Comprueba primero la URL del sitio: es la dirección del propio sitio, como
`https://contoso.sharepoint.com/sites/HR`, no una biblioteca ni una página dentro
de él. Con `Sites.Selected`, un sitio sobre el que la app no tiene concesión
también puede responder así.

### SharePoint: "The site has no document library named …" { #sharepoint-the-site-has-no-document-library-named }

El mensaje lista las bibliotecas que la app puede ver. Copia uno de esos nombres
en `library`, o deja `library` vacío para la biblioteca por defecto del sitio. La
biblioteca por defecto lleva el nombre en el idioma del sitio, como *Documents* o
*Dokumente*.

### SharePoint: "The library has no folder …" o "… is a file, not a folder" { #sharepoint-the-library-has-no-folder-or-is-a-file-not-a-folder }

`folder_path` no nombra una carpeta de la biblioteca. Es relativo al nivel
superior de la biblioteca, por ejemplo `Policies/HR`, y no repite el nombre de la
biblioteca.

### SharePoint: "The folder … could not be listed: …" { #sharepoint-the-folder-could-not-be-listed }

No se pudo leer una carpeta bajo la carpeta de la fuente. El motivo va detrás de
los dos puntos. Las demás carpetas se ingirieron, y en ese run no se eliminó nada.

### SharePoint: "Microsoft 365 stayed unavailable or kept throttling … after 4 attempts" { #sharepoint-microsoft-365-stayed-unavailable-or-kept-throttling-after-4-attempts }

Graph seguía limitando o fallando tras cuatro intentos. La siguiente
sincronización vuelve a empezar. Si ocurre en cada sincronización, programa la
fuente con menos frecuencia, o divide una biblioteca muy grande en varias fuentes,
cada una con su propio `folder_path`.

### SharePoint: "A SharePoint source needs a Microsoft Entra app credential" { #sharepoint-a-sharepoint-source-needs-a-microsoft-entra-app-credential }

La fuente nombra un secreto de otro kind, como una API key. Añade la app al vault
como **Microsoft Entra app** y elige esa.

### SharePoint: una sincronización terminó sin ningún archivo procesado { #sharepoint-a-sync-finished-with-no-files-processed }

Nada en la biblioteca ha cambiado desde la última ejecución limpia con la misma
configuración, así que no había nada que hacer. Cambia la fuente a `full` durante
una ejecución para volver a leerlo todo de todos modos.

### Las sincronizaciones programadas no se ejecutan { #scheduled-syncs-are-not-running }

Tiene que haber un sistema de tareas en segundo plano en marcha. Comprueba que
tu proceso worker está activo:

Sin un worker, solo funcionan los disparos manuales desde la CLI o la API.
