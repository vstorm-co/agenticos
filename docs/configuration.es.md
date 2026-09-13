---
source_sha: 4b2b3dcb65c8
---

# Configuración { #configuration }

Toda la configuración se gestiona con variables de entorno, cargadas desde
`backend/.env` con [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

Los ajustes se definen en `app/core/config.py` y se leen a través del objeto
global `settings`:

```python
from app.core.config import settings

print(settings.EMBEDDING_MODEL)
print(settings.DEBUG)
```

## Primeros pasos { #getting-started }

`make install` crea `backend/.env` a partir de `backend/.env.example` cuando no
existe ninguno, y no vuelve a tocarlo nunca más — así que en un checkout nuevo no
hay nada que copiar, y en uno existente no hay nada que perder.

Antes de que nada llegue a una red en la que haya alguien más, fija los valores
que el ejemplo trae como marcadores de posición:

```bash
openssl rand -hex 32   # SECRET_KEY — signs every access token
openssl rand -hex 32   # VAULT_MASTER_KEY — unwraps every credential stored at rest
```

!!! danger "`SECRET_KEY` se distribuye con una cadena publicada"

    Un `VAULT_MASTER_KEY` vacío recurre a ella para que un checkout nuevo
    arranque siquiera. Ambas valen en un portátil y son toda la seguridad de un
    despliegue en cualquier otro sitio. Fijar `VAULT_MASTER_KEY` de forma
    explícita es además lo que permite que los secretos guardados sobrevivan a
    una rotación de `SECRET_KEY`.

La configuración rechaza un `VAULT_MASTER_KEY` sin fijar fuera de
`local`/`development`.

## Ajustes del proyecto { #project-settings }

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `PROJECT_NAME` | `agenticos` | Nombre visible del proyecto |
| `API_V1_STR` | `/api/v1` | Prefijo de la versión de la API |
| `DEBUG` | `false` | Activa el modo de depuración (errores detallados, recarga automática) |
| `ENVIRONMENT` | `local` | Uno de: `development`, `local`, `staging`, `production` |
| `TIMEZONE` | `UTC` | Zona horaria IANA (p. ej. `UTC`, `Europe/Warsaw`, `America/New_York`) |
| `MODELS_CACHE_DIR` | `./models_cache` | Directorio para los modelos de ML cacheados |
| `MEDIA_DIR` | `./media` | Directorio para los archivos subidos |
| `MAX_UPLOAD_SIZE_MB` | `50` | Tope de un documento de la base de conocimiento, y el número del que se deriva el techo de la petición completa que se describe abajo. Un documento de este tamaño se trocea y se convierte en embeddings, no se guarda de una pieza |
| `CHAT_MAX_UPLOAD_SIZE_MB` | `10` | Lo que se puede adjuntar en el chat. Tiene su propio ajuste y no el de arriba, porque un adjunto a un agent sin workspace se pega entero en el prompt — así que las dos superficies fallan de forma distinta con el mismo tamaño. Eran 10 MiB fijos que ningún operador podía subir ([#498](https://github.com/vstorm-co/agenticos/issues/498)); el contenedor del frontend lee el mismo `CHAT_MAX_UPLOAD_SIZE_MB` en tiempo de ejecución, así que dale un solo valor a los dos contenedores o el composer rechazará un archivo que el servidor sí aceptaría |
| `EMBED_MAX_UPLOAD_SIZE_MB` | `5` | Lo que un **desconocido** puede subir a una página alojada. Un techo por encima de `CHAT_MAX_UPLOAD_SIZE_MB`, nunca una forma de saltárselo |
| `MEM0_ALLOWED_HOSTS` | `[]` (empty) | Hostnames a los que puede apuntar un servicio de memoria mem0 autoalojado. Un `base_url` viene del spec de un agent, así que sin una lista de permitidos un Builder que puede vincular (pero no leer) una clave mem0 compartida podría apuntarla a su propio servidor y capturar la clave desde la cabecera de la petición. Vacío rechaza mem0 autoalojado y solo permite la nube gestionada; añade un hostname de confianza para habilitar un despliegue autoalojado. Ver [secretos](secrets.md) |
| `FILE_IO_MAX_WORKERS` | `8` | Tamaño del pool de hilos dedicado que ejecuta el trabajo bloqueante con archivos — parsear una subida y leer o escribir sus bytes. Se mantiene fuera del executor por defecto compartido de `asyncio`, que también ejecuta `bcrypt` y el DNS de hosts fijados, para que una ráfaga de subidas no deje el inicio de sesión y las peticiones salientes en cola detrás de ella ([#1108](https://github.com/vstorm-co/agenticos/issues/1108)). Súbelo en una máquina que parsea muchas subidas a la vez. Tiene que ser un entero positivo — un `0` o un valor negativo se rechaza al arrancar |
| `DEFAULT_ORG_MONTHLY_BUDGET_USD` | `100` | El techo de gasto mensual con el que arranca una organización **nueva**, en USD, para que no esté a un agent desbocado de una factura sorpresa. Se aplica solo en la creación; las organizaciones existentes no se tocan y a cualquier organización se le puede quitar el tope después. Tiene que ser positivo; déjalo **vacío** para que las organizaciones empiecen sin tope (la postura anterior, de adhesión voluntaria) |

### El tamaño de una petición, frente al tamaño de un archivo { #the-size-of-a-request-as-opposed-to-the-size-of-a-file }

Todos los límites de arriba se miden sobre bytes que ya han llegado. FastAPI parsea
un cuerpo multipart para resolver el parámetro `UploadFile` *antes* de que el
handler se ejecute, así que cuando uno de esos topes se compara con `len(data)` el
cuerpo ya se ha volcado a un archivo temporal y se ha leído en memoria. Detrás de
una sesión eso no es gran riesgo; en `POST /api/v1/embed/{key}/files`, que puede
alcanzar un desconocido con un enlace, sí lo es.

Por eso una petición que declara un `Content-Length` mayor que
`MAX_UPLOAD_SIZE_MB` más un margen de 5 MiB para el sobre multipart se responde con
**413** antes de leer su cuerpo. No hay ajuste: sigue a `MAX_UPLOAD_SIZE_MB`,
porque un segundo número que hay que mantener a la par del primero es un número que
acaba por debajo de él.

**Es la mitad barata de la respuesta, no la respuesta entera.** El `Content-Length`
lo pone quien llama, y una petición chunked no declara ninguno — esas pasan y
quedan acotadas por los topes por ruta, que miden bytes reales. Un despliegue que
quiera la garantía y no la cortesía fija `client_max_body_size` (nginx) o el
equivalente en lo que termine sus conexiones; los archivos compose ejecutan uvicorn
sin un límite propio.

## Autenticación { #authentication }

### JWT { #jwt }

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `SECRET_KEY` | (insecure default) | Clave de firma de los JWT. **Tiene que** cambiarse en producción. Genérala con: `openssl rand -hex 32` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Vida del access token |
| `REFRESH_TOKEN_EXPIRE_MINUTES` | `10080` | Vida del refresh token (7 días) |
| `ALGORITHM` | `HS256` | Algoritmo de firma de los JWT |

Validación en producción: `SECRET_KEY` tiene que tener al menos 32 caracteres y no
puede usar el valor por defecto con `ENVIRONMENT=production`.

### El vault de secretos { #secret-vault }

Toda credencial que la plataforma guarda en reposo — claves de provider, tokens de
bots de canal, credenciales MCP y secretos de organización — la sella
`app/core/vault.py`, cuyo sobre se deriva de la clave maestra **y del propietario**
(una organización, o el miembro al que pertenece una conexión personal). Un
ciphertext es por tanto inútil fuera del tenant para el que se selló.

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `VAULT_MASTER_KEY` | (empty, falls back to `SECRET_KEY`) | Clave maestra del vault de secretos — abreviatura de la versión 1 de `VAULT_MASTER_KEYS`. Obligatoria fuera de `local`/`development` (salvo que se fije el mapa de abajo), para que un vault de staging no pueda arrancar sellado bajo el `SECRET_KEY` publicado por defecto. Genérala con: `openssl rand -hex 32` |
| `VAULT_MASTER_KEYS` | `{}` | Todas las claves maestras aún en uso, por versión, como JSON — `{"1": "<old>", "2": "<new>"}`. La versión más alta sella los secretos nuevos; las anteriores mantienen legibles las filas existentes hasta que `agenticos cmd vault-rotate` las vuelve a envolver. Cuando se fija, es la verdad entera: `VAULT_MASTER_KEY` tiene que estar entonces vacía. Ver [Secretos](secrets.md#operations) |

### Clave de API { #api-key }

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `API_KEY` | `change-me-in-production` | Clave de API compartida para el acceso programático |
| `API_KEY_HEADER` | `X-API-Key` | Nombre de la cabecera HTTP de la clave de API |

Validación en producción: `API_KEY` no puede usar el valor por defecto con
`ENVIRONMENT=production`.

### OAuth2 (Google) { #oauth2-google }

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `GOOGLE_CLIENT_ID` | (empty) | Client ID de Google OAuth2 — el inicio de sesión **y** el consentimiento del trigger de Gmail |
| `GOOGLE_CLIENT_SECRET` | (empty) | Client secret de Google OAuth2 |
| `GOOGLE_REDIRECT_URI` | `http://localhost:8000/api/v1/oauth/google/callback` | URL de callback de OAuth2 |
| `FRONTEND_URL` | `http://localhost:3000` | URL del frontend para las redirecciones de OAuth2 |

Cómo conseguir el par: [consola de Google Cloud](https://console.cloud.google.com/) →
APIs & Services → Credentials → Create OAuth client ID → **Web application**.

La URI de redirección autorizada es el callback del **backend**, no el del frontend:
`http://localhost:8000/api/v1/oauth/google/callback` por defecto, y lo que diga
`GOOGLE_REDIRECT_URI` en un despliegue. Google intercambia el código con la API, que
después envía el navegador a `FRONTEND_URL`. Registrar en su lugar la URL del
frontend es el error que merece nombrarse: la pantalla de consentimiento funciona, y
el callback da 404.

Al navegador se le envía un código de un solo uso y un minuto de vida, nunca los
tokens de sesión: un token en una URL de redirección llega a la barra de
direcciones, al log de acceso del servidor del frontend y al `Referer` de la
siguiente petición del mismo origen, y el refresh token vale una semana. El
frontend canjea el código por el par de tokens de servidor a servidor en
`POST /api/v1/oauth/exchange`, que lo redime exactamente una vez.


## Base de datos (PostgreSQL) { #database-postgresql }

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `POSTGRES_HOST` | `localhost` | Host de PostgreSQL |
| `POSTGRES_PORT` | `5432` | Puerto de PostgreSQL |
| `POSTGRES_USER` | `postgres` | Usuario de PostgreSQL |
| `POSTGRES_PASSWORD` | (empty) | Contraseña de PostgreSQL |
| `POSTGRES_DB` | `agenticos` | Nombre de la base de datos |
| `POSTGRES_SSLMODE` | (empty) | Cifra la conexión: `require`, `verify-ca` o `verify-full`. Vacío es texto plano. Ver [Conexiones cifradas](#encrypted-connections-tls) |
| `DB_POOL_SIZE` | `5` | Tamaño del pool de conexiones |
| `DB_MAX_OVERFLOW` | `10` | Máximo de conexiones de desbordamiento |
| `DB_POOL_TIMEOUT` | `30` | Tiempo de espera del pool, en segundos |

Propiedades calculadas:
- `DATABASE_URL` -- cadena de conexión asíncrona (`postgresql+asyncpg://...`)
- `DATABASE_URL_SYNC` -- cadena de conexión síncrona, para Alembic

## Redis { #redis }

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `REDIS_HOST` | `localhost` | Host de Redis |
| `REDIS_PORT` | `6379` | Puerto de Redis |
| `REDIS_PASSWORD` | (none) | Contraseña de Redis (opcional) |
| `REDIS_DB` | `0` | Número de base de datos de Redis |
| `REDIS_SSL` | `false` | Cifra la conexión (`rediss://`). Ver [Conexiones cifradas](#encrypted-connections-tls) |

## Conexiones cifradas (TLS) { #encrypted-connections-tls }

Los dos almacenes se conectan en texto plano por defecto. En una sola máquina con
Postgres y Redis en la misma red de Docker eso está bien, y es lo que ejecutan los
archivos compose que se distribuyen. Con un Postgres gestionado, o un Redis en otro
nodo, cifrar la conexión es el control de seguridad en la transmisión que un
auditor pide primero (HIPAA §164.312(e), SOC 2 CC6.7).

Fijar `POSTGRES_SSLMODE` construye la URL que entiende cada driver — `?ssl=<mode>`
para el asyncpg de la aplicación, `?sslmode=<mode>` para el psycopg2 de Alembic — y
`REDIS_SSL` cambia el esquema de Redis a `rediss://`. `require` cifra la conexión;
`verify-ca` y `verify-full` además comprueban el certificado del servidor.

`REDIS_SSL` pide también una cadena de certificados válida y un hostname que
coincida en la propia URL, en vez de dejar ambas cosas a los valores por defecto de
redis-py.

!!! warning "Una CA privada es un archivo que leen los drivers, no el almacén de confianza del sistema"

    Ninguno de los dos drivers consulta el almacén de confianza del contenedor, y
    la imagen se ejecuta como un usuario no root sin un entrypoint que pudiera
    reconstruirlo. asyncpg y libpq leen ambos el archivo de CA que nombra
    `PGSSLROOTCERT`; redis-py confía en el bundle al que apunte OpenSSL, que
    `SSL_CERT_FILE` sobrescribe. Monta la CA una vez y apunta las dos variables a
    ella: `verify-ca` y `verify-full` fallan sin la primera, porque asyncpg busca
    entonces `~/.postgresql/root.crt` y no encuentra nada.

!!! note "Todo servicio que abra una conexión a un almacén necesita el cambio"

    `app`, `migrate` y `prefect-runner` se conectan cada uno a Postgres y a Redis,
    y los archivos compose que se distribuyen fijan `POSTGRES_HOST=db` y
    `REDIS_HOST=redis` en el `environment` de cada uno, lo que gana a un archivo
    de entorno. Así que un almacén gestionado es un archivo de override que llega
    a los tres, no una línea en `.env`.

```yaml
# docker-compose.managed.yml - a managed Postgres and Redis, verified against a
# private CA. Run with `docker compose -f docker-compose.yml -f docker-compose.managed.yml up -d`.
x-managed: &managed
  environment:
    POSTGRES_HOST: db.internal.example.com
    POSTGRES_SSLMODE: verify-full
    PGSSLROOTCERT: /run/tls/managed-ca.crt
    REDIS_HOST: redis.internal.example.com
    REDIS_SSL: "true"
    SSL_CERT_FILE: /run/tls/managed-ca.crt
  volumes:
    - ./ca/managed-ca.crt:/run/tls/managed-ca.crt:ro

services:
  app: *managed
  migrate: *managed
  prefect-runner: *managed
```

Los servicios `db` y `redis` incluidos siguen arrancando, sin usarse; `agenticos cmd
doctor` muestra a qué almacén llegó realmente cada conexión y si iba cifrada
(`postgres: tls=on/off`, `redis: tls=on/off`, a partir de `pg_stat_ssl` y del
esquema de la URL).

## Correo (SMTP) { #email-smtp }

El despliegue envía correo a través de un servidor SMTP, y uno que no tenga ninguno
configurado no falla: se ejecuta, y todos los flujos que dependen del correo se
detienen en silencio, sin que ninguno se anuncie:

- **inicio de sesión sin contraseña y restablecimientos de contraseña** — los
  correos con el enlace mágico y el de restablecimiento son las vías de autoservicio
  para entrar en una cuenta;
- **invitaciones** — a una dirección invitada nunca se le escribe (la consola ahora
  lo dice, en vez de afirmar que envió algo, #1484);
- **notificaciones** — un budget superado, una solicitud de aprobación, un informe
  de uso, el aviso que se envía cuando un administrador actúa como otra cuenta.

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `SMTP_HOST` | `localhost` | Host del servidor SMTP |
| `SMTP_PORT` | `587` | Puerto del servidor SMTP. `587` y `25` negocian STARTTLS; `465` abre TLS desde el principio |
| `SMTP_USER` | (empty) | Usuario con el que se autentica el relay, junto a `SMTP_PASSWORD`. Déjalo vacío para un relay sin autenticación |
| `SMTP_PASSWORD` | (empty) | Contraseña de ese usuario |
| `SMTP_TLS` | `true` | Si se cifra la conexión. El puerto elige el esquema — STARTTLS en `587`, TLS implícito en `465` — salvo que `SMTP_TLS_MODE` diga otra cosa. Ponlo en `false` solo para un relay sin cifrar, como un servidor local en el `25` |
| `SMTP_TLS_MODE` | `auto` | Cómo se abre la conexión cifrada. `auto` deja elegir al puerto; `implicit` abre TLS desde el primer byte y `starttls` negocia la mejora, sea cual sea el puerto. Se ignora con `SMTP_TLS=false` |
| `EMAIL_FROM` | `noreply@agenticos.com` | La dirección `From` de cada mensaje |
| `EMAIL_FROM_NAME` | `agenticos` | El nombre visible que se muestra junto a esa dirección |

!!! note "Cómo se cifra la conexión"

    `SMTP_TLS` es el interruptor; el puerto elige el esquema. El valor por defecto
    que se distribuye — `587` con `SMTP_TLS=true` — negocia STARTTLS, que es lo que
    espera un servidor de envío conforme al estándar. Usa `465` para un servidor
    que quiera TLS implícito, y `SMTP_TLS=false` en el `25` para un relay en texto
    plano.

    Un servidor que habla TLS implícito en un puerto que no sea el `465` — el
    `8465`, pongamos — necesita `SMTP_TLS_MODE=implicit`, porque `auto` le
    ofrecería un saludo en texto plano y todos los envíos fallarían. `starttls` es
    el caso espejo.

## Trabajo en segundo plano (Prefect) { #background-work-prefect }

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `PREFECT_API_URL` | `http://localhost:4200/api` | El servidor autoalojado, o la URL de un workspace de Prefect Cloud |
| `PREFECT_API_KEY` | (none) | Solo para Prefect Cloud |
| `PREFECT_RUNNER_LIMIT` | `5` | Cuántas ejecuciones de flow corren a la vez; el resto espera en cola |
| `PREFECT_RUNNER_SERVER_HOST` | `127.0.0.1` in compose | Interfaz en la que el runner sirve su propio endpoint de salud |
| `PREFECT_RUNNER_SERVER_PORT` | `8080` | Puerto para lo mismo |

`PREFECT_RUNNER_LIMIT` es un techo de memoria, no un mando de rendimiento. Cada
ejecución es un proceso aparte que importa la aplicación entera — unos 120 MB — y el
número que importa no es el estado estable sino el reinicio: el runner arranca,
encuentra todas las ejecuciones programadas mientras estuvo caído y arranca tantas
como permita el límite. Sin tope, tres días de caída fueron 71 procesos y 6 GiB.
Súbelo si la ingesta se acumula detrás de las sincronizaciones en una máquina con
memoria de sobra; bájalo en una máquina pequeña.

Las dos variables `PREFECT_RUNNER_SERVER_*` son de Prefect, y los archivos compose
las fijan para que el contenedor del runner tenga un estado de salud con sentido. El
runner arranca el webserver del runner de Prefect, cuyo `GET /health` responde 503 en
cuanto pierde dos sondeos de la API de Prefect — así, un proceso vivo que ya no
recoge trabajo aparece como `unhealthy` y no como sano. Va atado al loopback porque
ese mismo webserver expone además `POST /shutdown`; la sonda corre dentro del
contenedor y nada de fuera alcanza ninguno de los dos. Mover el puerto obliga a mover
con él la sonda en los archivos compose.

No hay `HEALTHCHECK` en `backend/Dockerfile`. La imagen se arranca como dos procesos
distintos — la API y este runner — y una sonda para uno es una falsa alarma
permanente para el otro, así que cada definición de servicio lleva la suya.

### Caducidad de las aprobaciones { #approval-expiry }

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `APPROVAL_EXPIRY_HOURS` | `72` | Cuánto espera una llamada a herramienta aparcada antes de que el barrido horario la deniegue por tiempo |

Tres días porque tiene que abarcar un fin de semana: la aprobación que llega el
viernes por la tarde es la que nadie decide, y caducarla el sábado sería caducarla
por haberse pedido a mala hora. Acórtalo donde la cola se vigila en horario laboral
y una petición rancia es peor que una lenta; alárgalo donde las aprobaciones son un
ritual semanal. Caducar una llamada además **termina su run** — ver
[Gobernanza](governance.md#a-decision-nobody-makes) para lo que eso zanja y lo que
deja a propósito en paz.

### Recogida de runs estancados { #stale-run-reaping }

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `STALE_RUN_REAPED_AFTER_HOURS` | `6` | Cuánto puede quedarse un run en `running` antes de que el barrido horario decida que su proceso murió y lo termine como `failed`. Cero o menos apaga el barrido |

La fila de un run se confirma antes de llamar a su modelo, así que un worker muerto a
media ejecución la deja en `running` sin nada que la termine. El techo no tiene que
ser exacto — un run vivo que el barrido marque igualmente lo devuelve su propia
escritura terminal — así que ponlo bastante por encima de tu run legítimo más largo y
no más cerca. Ver [Gobernanza](governance.md#a-run-whose-process-died).

## Modelos de IA — se configuran en la aplicación, no aquí { #ai-models-configured-in-the-app-not-here }

Los modelos de chat no son variables de entorno. Cada organización guarda sus propias
claves de provider en el vault (Settings → Models), y el spec de cada agent nombra el
perfil de modelo con el que se ejecuta. `AI_MODEL`, `AI_TEMPERATURE`,
`AI_THINKING_ENABLED`, `AI_THINKING_EFFORT`, `AI_AVAILABLE_MODELS`, `AI_FRAMEWORK` y
`LLM_PROVIDER` se eliminaron junto con el asistente general de la plantilla; fijarlas
ahora no hace nada.

La única credencial de modelo que se queda en el entorno es la de embeddings — ver
RAG más abajo.

## Observabilidad (Logfire) { #observability-logfire }

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `LOGFIRE_TOKEN` | (none) | Token de Pydantic Logfire. Consigue uno en https://logfire.pydantic.dev |
| `LOGFIRE_SERVICE_NAME` | `agenticos` | Nombre del servicio en el dashboard de Logfire |
| `LOGFIRE_ENVIRONMENT` | `development` | Etiqueta de entorno |
| `LOGFIRE_ORGANIZATION` | (none) | Slug de la organización, para construir un enlace **hacia dentro** de una traza guardada. El token es una credencial de *escritura* y no lleva ninguno de los dos slugs |
| `LOGFIRE_PROJECT` | (none) | Slug del proyecto, junto al de la organización. Con cualquiera de los dos sin fijar, el `logfire_trace_id` de un run se sigue registrando y no se ofrece enlace |
| `LOGFIRE_BASE_URL` | `https://logfire-us.pydantic.dev` | A qué despliegue de Logfire pertenecen esos slugs. `logfire-eu` es otro host, y un enlace construido para el equivocado da 404 |

## Búsqueda web { #web-search }

| Variable | Por defecto | Descripción |
|----------|---------|-------------|

## RAG (Retrieval Augmented Generation) { #rag-retrieval-augmented-generation }

### Base de datos vectorial { #vector-database }

pgvector usa la conexión de PostgreSQL que ya existe. No hace falta configuración
adicional — pero la **imagen** tiene que ser `pgvector/pgvector:pg16`, que es lo que
fija cada archivo compose de aquí.

!!! note "\"Vector store: unconfigured\" en un despliegue recién instalado no es un fallo"

    La extensión se crea la primera vez que se escribe en una colección, así que
    antes del primer documento está genuinamente ausente y tanto la página System de
    administración como `agenticos cmd doctor` lo dicen. Se resuelve solo en la
    primera ingesta.

    Lo que sí es un fallo es un `unhealthy` ahí, y dice cuál de los tres: la imagen
    no trae pgvector; el rol que se conecta no puede crearla; o el directorio de
    datos arrastra la fila de la extensión mientras la imagen sobre la que ahora
    corre ha perdido la biblioteca. Los tres hacen fallar una subida después de
    aceptar los bytes, y los tres se leían igual que un primer día sano
    ([#1504](https://github.com/vstorm-co/agenticos/issues/1504)).

### Embeddings { #embeddings }

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | (empty) | La credencial de embeddings de reserva, para las colecciones que no eligieron una clave propia del vault — y aquella a la que recurre una elección degradada. No es "todas las colecciones hacen embeddings con ella": ver [Procesamiento de archivos](file-processing.md#embeddings-the-model-whose-endpoint-answers-and-whose-key-pays) |
| `EMBEDDING_MODEL` | `text-embedding-3-large` | Con qué se construye una colección **nueva**. El ancho queda registrado en la fila y no cambia después, así que cambiar esto no invalida las colecciones existentes: siguen haciendo embeddings con el modelo con el que se crearon |

### Parseo de documentos — se configura por colección, no aquí { #document-parsing-configured-per-collection-not-here }

El parser, el OCR, el tamaño de chunk, el solape de chunks, la estrategia de troceado
y el modelo de descripción de imágenes **no** son variables de entorno. Se guardan en
cada base de conocimiento (`knowledge_bases.ingestion_config`) y se editan en `/rag`,
y cualquiera de ellos puede además sobrescribirse para una sola subida.

La razón es que un único valor para toda la instalación hacía que el mismo formulario
produjera colecciones distintas en dos despliegues, sin que nada en el producto
dijera cuál — y un archivo de contratos escaneados y una carpeta de notas en Markdown
quieren respuestas distintas en el mismo despliegue. `PDF_PARSER`, `CHAT_PDF_PARSER`,
`LLAMAPARSE_TIER`, `LITEPARSE_OCR_LANGUAGE`, `LITEPARSE_TIMEOUT_SECONDS`,
`RAG_ENABLE_OCR`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP` y `RAG_CHUNKING_STRATEGY` se
eliminaron; fijarlas ahora no hace nada.

Lo que se queda aquí es lo que un tenant no debe elegir:

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `LLAMAPARSE_API_KEY` | (empty) | Clave de LlamaParse de reserva, para las colecciones que no eligieron una clave propia del vault |
| `LITEPARSE_OCR_SERVER_URL` | (empty) | Servidor de OCR por HTTP; una dirección en la propia red del despliegue |

Los adjuntos del chat se leen con PyMuPDF y no son configurables: un adjunto no
pertenece a ninguna colección, así que no hay configuración guardada que leer.

### Sincronización con Google Drive { #google-drive-sync }

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `GOOGLE_DRIVE_CREDENTIALS_FILE` | `credentials/google-drive-sa.json` | Ruta a las credenciales de la cuenta de servicio de Google, solo para `rag-sync-gdrive` |

**Esta es la credencial de la CLI, no una reserva para una fuente de sincronización.**
Una fuente de sincronización `gdrive` nombra un secreto `gcp_service_account` en el
vault de su organización y se ejecuta con ese o no se ejecuta: una clave para todo el
despliegue supliendo a una que falta hacía que el `folder_id` de un tenant eligiera
qué se listaba bajo la cuenta de servicio del operador. La credencial de la fuente no
es un ajuste ni un campo de configuración — ver [Secretos y el vault](secrets.md).

El archivo es la clave de una cuenta de servicio: [consola de Cloud](https://console.cloud.google.com/iam-admin/serviceaccounts)
→ crea una cuenta de servicio → Keys → Add key → JSON. Después **comparte la carpeta
de Drive con la propia dirección de correo de la cuenta de servicio**: es un
principal como cualquier otro, y una carpeta que nadie ha compartido con él se lista
como vacía en vez de como rechazada.

### Sincronización con S3/MinIO { #s3minio-sync }

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `S3_RAG_ENDPOINT` | (none) | URL del endpoint de S3/MinIO. Una fuente de sincronización puede sobrescribirla |
| `S3_RAG_ACCESS_KEY` | (empty) | Access key, solo para el comando `rag-sync-s3` de la CLI |
| `S3_RAG_SECRET_KEY` | (empty) | Secret key, igual |
| `S3_RAG_BUCKET` | `agenticos-rag` | Nombre del bucket |
| `S3_RAG_REGION` | `us-east-1` | Región de AWS. La región propia de una credencial gana donde la tenga |

**El par de claves de aquí es el de la CLI, no el de una fuente de sincronización.**
Una fuente `s3` nombra un secreto `aws_credentials` en el vault de su organización,
igual que una `gdrive` nombra una cuenta de servicio. El endpoint y la región siguen
recurriendo a estos ajustes porque ninguno nombra a un principal: dicen dónde está el
almacén, no quién pregunta.

## Workspaces de los agents { #agent-workspaces }

El workspace `state` no necesita nada de aquí. Se guarda en esta base de datos,
funciona en todos los despliegues y es lo que un agent recibe por defecto — así que
los ajustes de abajo son solo para uno respaldado por contenedor.

| Variable | Por defecto | Notas |
|---|---|---|
| `SANDBOX_STATE_MAX_BYTES` | 4 MiB | Por workspace **guardado**. Pasado ese punto una escritura se rechaza con un mensaje que el modelo lee |
| `SANDBOX_INLINE_IMAGE_MAX_BYTES` | 5 MiB | Por encima de esto una imagen adjunta se escribe en el workspace y no se envía además en línea |

**El porcentaje del chat son dos techos distintos, y dice cuál es.** Un workspace
guardado se llena contra `SANDBOX_STATE_MAX_BYTES`, arriba — bytes, y agotarlos
*rechaza una escritura*. Un contenedor informa de la **memoria** residente contra el
techo que su host fijó para ese runtime, que es `1g` salvo que la lista de permitidos
diga otra cosa, y agotar eso es una muerte por OOM y no un rechazo. Por eso la tira
dice `workspace 12% full` para lo primero y `sandbox memory 12% full` para lo
segundo; informar de uno como del otro nombraría un límite que no se aplica.

**Dónde se ejecutan las sandboxes no es un ajuste.** Es una fila por organización
—Sandboxes en la aplicación, `sandbox_connections` en la base de datos— con el token
de servicio en el vault. Dos razones, y ninguna se puede expresar en una variable de
entorno: un despliegue puede tener más de un host, y una dirección por despliegue le
daba la misma a todas las organizaciones; y el token autoriza abrir una sesión, que
ejecuta comandos en el host que sostiene el socket de Docker, así que pertenece al
sitio donde vive cualquier otra credencial en reposo.

Un operador registra una conexión con un nombre, una dirección y una clave del vault.
Un agent nombra una por id, exactamente igual que nombra un perfil de modelo, o no
nombra ninguna y toma la de la organización por defecto — así que mudarse a otro host
es una edición y no volver a publicar todos los agents.

**El token de servicio vale lo que vale el socket de Docker.** El servicio sostiene
ese socket, el socket es una API sin autenticar para root en la máquina, y el token
es lo que abre una sesión sobre él. Nunca en un navegador, nunca en un log, nunca
versionado — por eso la pantalla del operador solo muestra que hay una credencial
adjunta, y por eso `GET /policy` se sirve a través de esta API en vez de que lo pida
el navegador. El dashboard propio del servicio (`SANDBOXD_UI_ENABLED`) está apagado en
todos los archivos compose que se distribuyen por la misma razón: pide a una persona
que pegue este valor en un navegador.

`SANDBOXD_TOKEN` en `backend/.env` es el del *servicio*: lo que el daemon del archivo
compose aceptará.

`make sandbox-token` lo genera, y el formulario de conexión guarda por ti ese mismo
valor en el vault. La API lee este ajuste con un único propósito: ofrecerlo al vault.
Pedirle a alguien que copie un secreto de un archivo que su propio stack ya está
leyendo es fricción sin nada detrás.

**Nunca** se usa para alcanzar un host: resolver una conexión abre la entrada del
vault que esa conexión nombra, y ese sigue siendo el único camino. Así que un
despliegue que lo deje sin fijar pierde un botón y nada más, y pega el token a mano.

El mismo formulario pregunta si ya hay un servicio respondiendo, en vez de obligar al
operador a saber que el servicio de sandbox de `make dev` vive en
`http://sandboxd:8080`. Esa dirección no es configuración, y a propósito — es una
fila, porque un despliegue puede tener varios hosts —, así que la API sondea el
`/healthz` sin autenticar en la dirección que usa el archivo compose de este proyecto
y rellena lo que haya respondido. Preguntar no decide nada: sin servicio el campo
queda vacío, y si ya hay una conexión apuntando ahí se nombra para que nadie registre
dos veces el mismo host.

**La dirección la pide esta API, así que se valida como tal.** Registrar o sondear
una conexión hace que el contenedor de la API emita un `GET` autenticado y devuelva
el cuerpo JSON, lo que es una primitiva de falsificación de peticiones si la
dirección se acepta a ciegas. Así que `base_url` rechaza todo lo que no sea
`http(s)` con un host, y rechaza de plano las direcciones link-local y los hostnames
de metadatos de instancia: `169.254.169.254` y `metadata.google.internal` nunca son
un servicio de sandbox.

Las direcciones privadas siguen permitidas, y tienen que estarlo: `http://sandboxd:8080`
dentro de compose y `http://localhost:8080` para quien ejecuta la API en su propia
máquina son ambas privadas, así que una lista de denegación del rango privado
rechazaría el despliegue que describe esta página. El validador estrecha el agujero
en vez de cerrarlo — un hostname que resuelve a algo interno sigue resolviendo. **El
límite que de verdad aguanta es `connections:manage` más la política de salida del
contenedor de la API**: de quien puede registrar un host se fía uno, y un despliegue
en una red con APIs internas sin autenticar debería decirlo en la red y no aquí.

### Qué entornos puede pedir un agent { #which-environments-an-agent-may-ask-for }

Se distribuye un runtime — `workbench` (1,93 GB): Python 3.12, Node 24, LibreOffice y
las bibliotecas que un agent necesita para leer, escribir, convertir y graficar los
archivos de los que trata una conversación, incluido liteparse con OCR. Está definido
en `backend/app/core/catalog/sandbox_runtimes.json`. Añadir uno es una edición ahí y
`make sandbox-runtimes`, que escribe `SANDBOXD_RUNTIMES` en los tres archivos
compose; esa variable es el único canal por el que el servicio acepta runtimes, y
`PUT /policy` rechaza a propósito la composición de la lista.

`sandbox.md#which-environments-an-agent-may-ask-for` tiene el formato campo por
campo, las tres trampas (la primera entrada es la de por defecto, `network_mode` no
se hereda, una build se paga al arrancar con `prewarm`) y por qué la copia generada
en los archivos compose no puede desviarse del catálogo.

### Los ajustes del propio servicio { #the-services-own-settings }

Cada campo de la configuración del servicio es `SANDBOXD_` más su nombre, así que
esto es un subconjunto y no un vocabulario. Estos son los que fijan los archivos
compose que se distribuyen, o los que deciden si los archivos sobreviven:

| Variable | Valor distribuido | Qué decide |
|---|---|---|
| `SANDBOXD_WORKSPACE_ROOT` | una ruta del host | Dónde vive el directorio de trabajo de cada sesión, montado desde el *host*. **Sin fijar, los archivos existen solo dentro de un contenedor en marcha**: una recogida por inactividad los descarta y la siguiente petición abre un workspace vacío, sin nada en un log. Es además lo que hace posible navegarlos: leer un workspace nunca arranca un contenedor |
| `SANDBOXD_SANDBOX_UID` | `10001` | El usuario sin privilegios con el que corre una sandbox, en vez de root — una fuga de contenedor arranca desde quienquiera que ejecute el contenedor, y todo archivo que escribe un agent pertenece a este uid en el host. **Tiene que ser el uid del propio servicio**: abrir una sesión hace `chown` del workspace a este usuario, cosa que un servicio sin privilegios solo puede hacer para sí mismo. Se aplica a un runtime que el despliegue *construye*, ya que una imagen hecha no tiene tal cuenta y un agent dentro de una no podría instalar nada |
| `SANDBOXD_CONTAINER_TTL` | 86400s | Cuánto se conserva un contenedor persistido ya *parado*. Recupera lo que instaló una sesión —la build, las wheels, `node_modules`— y deja el workspace intacto, porque los archivos son el trabajo. Sin fijar, se conservan para siempre |
| `SANDBOXD_PERSIST_CONTAINERS` | `true` | El contenedor de una sesión cerrada se conserva en vez de eliminarse, así que la siguiente sesión sobre ese workspace arranca sin una build. Cuesta un contenedor parado por workspace; `SANDBOXD_CONTAINER_TTL` lo acota |
| `SANDBOXD_MAX_SESSIONS_PER_TENANT` | `5` | Una organización no puede quedarse con el pool. `SANDBOXD_MAX_SESSIONS` (20) es el pool |
| `SANDBOXD_NETWORK_MODE` | `none` | La red por defecto de una sandbox. `none` es no tener red en absoluto; un runtime puede nombrar `bridge` para sí mismo |
| `SANDBOXD_UI_ENABLED` | `0` | El dashboard propio del servicio. Apagado porque pide a una persona que pegue en un navegador un token equivalente a root |
| `SANDBOXD_IDLE_TIMEOUT` | 1800s | Cuánto vive una sesión inactiva antes de cerrarse y recogerse |
| `SANDBOXD_MEM_LIMIT` | `1g` | El techo de memoria por defecto, y por tanto el número del que el porcentaje `sandbox memory` del chat es una parte |

### Ejecutar el servicio en otra máquina { #running-the-service-on-another-host }

Nada de una conexión da por hecha una dirección local: es una fila con una URL y una
credencial del vault, y el formulario sondea lo que se le dé. Una máquina en otro
sitio necesita tres cosas y nada de código:

1. **El socket de Docker**, porque el servicio arranca contenedores. Eso es root en
   esa máquina, que es por lo que el token de abajo vale lo que vale.
2. **`SANDBOXD_WORKSPACE_ROOT` en disco real, montado en la misma ruta en ambos
   lados.** El servicio crea el directorio y luego pide al *daemon* que lo monte, y
   el daemon resuelve la ruta en el host — así que un volumen con nombre, o una ruta
   que solo existe dentro del contenedor del servicio, se rechaza con `mounts
   denied`.
3. **TLS y un token que no comparta nadie.** Dentro de compose la dirección es
   `http://sandboxd:8080` en una red privada; a través de internet es un servicio que
   ejecutará comandos para quien tenga el token, así que va detrás de HTTPS con un
   valor propio.

Después regístrala en Sandboxes como cualquier otra y apunta un agent a ella por
nombre. El servicio de compose es un despliegue más de la misma imagen.

### Cuándo hay una sesión abierta { #when-a-session-is-open }

La pestaña **Running** lista las sesiones que sostiene el servicio, con refresco cada
diez segundos, y una sesión es un workspace en un host. Tres estados, y solo aparecen
los dos primeros:

- **running** — el contenedor existe y está residente. Lo abre la primera llamada a
  herramienta de un agent en una conversación, no el inicio de la conversación.
- **hibernated** — la fila existe y el contenedor no. Una sesión inactiva más allá de
  `SANDBOXD_EVICT_IDLE_AFTER` se hiberna para liberar una plaza, y su siguiente
  petición la despierta. Esto necesita `WORKSPACE_ROOT`, o despertar una abriría un
  workspace vacío, y el servicio rechaza la combinación en vez de hacer eso.
- **gone** — pasado `SANDBOXD_IDLE_TIMEOUT` la sesión se cierra y se recoge. Con
  `PERSIST_CONTAINERS` el contenedor sobrevive a eso, así que la siguiente sesión
  sobre el mismo workspace arranca sin una build.

Así que una pestaña Running vacía significa que ningún agent ha usado una shell hace
poco, no que no haya nada configurado — y un workspace con archivos dentro y sin
sesión es el estado de reposo normal.

El servicio corre bajo el profile `sandbox` de compose, que está encendido por
defecto en desarrollo local y apagado en el resto hasta que un operador lo active:
montar el socket de Docker en una máquina compartida es un acto deliberado.
`COMPOSE_DEV_PROFILES` en el Makefile es el único sitio donde cambiarlo.
`uv run agenticos cmd doctor` sondea cada conexión registrada: si responde, si acepta
su credencial, y si permite algún runtime. No tener ninguna conexión registrada es un
aviso, no un fallo — el workspace `state` no necesita ninguna.

**Navegar por lo que los agents han guardado.** Workspaces es una pantalla propia, no
parte de Sandboxes, que trata de *hosts*.

Cada fila nombra el agent, la conversación a la que pertenecen los archivos (o
cuántos chats llegan a ellos, para un workspace que no es de una sola conversación),
quién puede verlos, cuánto ocupa y cuándo se usó por última vez.

**Open** lleva a la página propia de ese workspace, con la forma que usa el editor de
skills: el árbol a la izquierda —carpetas recorridas de una en una, con una caja de
búsqueda sobre todo el árbol y no sobre la carpeta en pantalla— y el archivo
renderizado al lado. Así que leer tres archivos son tres clics, y la lista no se
cierra nunca.

La descarga está en la fila y no junto al lector, porque seleccionar un archivo lo
lee y de un archivo grande alguien quiere una copia sin pagar por eso.

Una segunda vista sobre el listado aplana en una sola rejilla todos los archivos que
el lector puede ver: la pregunta de "quién tiene una copia de ese CSV" que la página
por workspace no responde.

**Al hacer clic en un archivo se abre en un visor, y es el mismo visor del panel del
chat.** Una imagen es una imagen, un PDF es la vista PDF propia del navegador,
markdown ofrece *Preview* y *Source* —ambos son el archivo, y un `#` que se convirtió
en silencio en letra grande es como alguien no llega a notar que su agent escribe
markdown dentro de algo que nada lee como markdown— y cualquier otra cosa es su
texto. La descarga está siempre ahí, también para lo que no se puede mostrar en
absoluto. Un solo componente, porque que "abrir este archivo" signifique dos cosas
distintas en dos pantallas es como a la segunda acaba faltándole un caso.

Los bytes vienen de `GET /sandbox-workspaces/{id}/raw?path=…`, o de
`GET /conversations/{id}/workspace/raw?path=…` para el panel junto a un chat.

Dos rutas y no una porque autorizan a llamantes distintos —a la ruta de la
conversación se llega obteniendo la conversación, así que alguien con quien se
*compartió* un chat conserva el acceso— y un solo módulo decide qué se puede mostrar,
para que la respuesta no pueda variar según la superficie.

Casi todo se sirve como adjunto. **Las imágenes ráster y los PDF** se sirven para
mostrarse: la ráster porque no puede ejecutarse, el PDF porque el navegador lo
renderiza en su propio visor, que nunca recibe el DOM de la página.

!!! danger "SVG y HTML se pueden descargar y nunca mostrar"

    Un SVG servido en línea desde este origen es cross-site scripting almacenado
    escrito por lo que el agent decidiera guardar, y "lo escribió el agent" no es un
    límite de confianza.

Todo lo demás se tipa como `application/octet-stream` con
`X-Content-Type-Options: nosniff`, para que un navegador no pueda decidir que ese
cuerpo era HTML después de todo. El nombre del archivo viaja solo como `filename*`,
porque una ruta de workspace puede contener cualquier UTF-8 y la forma simple no
tiene manera de decirlo.

Solo un workspace **guardado** puede servir bytes arbitrarios. Uno respaldado por
contenedor se lee a través del archivo comprimido del workspace, cuyo único lector es
textual, así que un archivo de texto se sirve codificándolo y cualquier otra cosa se
rechaza en vez de estropearse en silencio — el navegador ofrece la descarga junto al
rechazo, para que la respuesta nunca sea un callejón sin salida.

Los archivos se leen solo cuando se abre un workspace, o cuando se activa la vista
plana: un despliegue puede tener uno por conversación caliente, así que leer cada uno
para renderizar la tabla sería una petición por fila de una página a la que nadie le
ha preguntado nada todavía. La vista plana está acotada por la misma razón, y lo dice:
cuántos workspaces leyó, cuántos no pudo, y si hay más. Una lista más corta es, si no,
indistinguible de menos archivos.

**Quién ve qué workspace se decide por lector, en la consulta.** Quien tiene
`connections:manage` ve los de la organización — el listón honesto para un listado que
cruza chats que no son suyos. El resto ve los workspaces de los que forma parte: sus
propios archivos con alcance `user`, los workspaces de sus propias conversaciones y el
workspace compartido de un agent con el que ha hablado. "Ha hablado" y no "podría
abrir", a propósito: el alcance `agent` comparte un workspace entre los usuarios de un
agent y el panel del chat ya muestra esos archivos a cualquiera en una conversación con
él, así que *poder* abrir el agent es una pretensión más amplia que la de este listado.

El alcance `channel` es visible solo para un operador, lo cual es correcto y no un
descuido: está indexado por un chat de Slack o de Telegram, así que a quienes lo
comparten los identifica esa plataforma y no una fila en `users`.

Un workspace obtenido por id aplica los mismos tres predicados y responde **not
found** en vez de prohibido cuando fallan: un id no debe servir para descubrir qué
workspaces existen en la conversación de un colega. Nada de aquí cruza una
organización — un app admin navegando por los archivos de otro tenant sería
precisamente la lectura que esta plataforma rechaza, así que cambia de organización
como cualquiera.

**Un workspace respaldado por contenedor se lee del volumen del host, que hace falta
tener.** El servicio de sandbox sirve esos archivos desde
`SANDBOXD_WORKSPACE_ROOT`, y eso es lo que permite que una conversación del mes pasado
liste sus archivos después de que su sesión fuera recogida: no se arranca ningún
contenedor para responder. Un servicio configurado *sin* uno no guarda nada en disco,
así que sus archivos existen solo mientras una sandbox está en marcha y no se pueden
leer sin arrancar una: el panel Files solo podría decirlo, para un archivo que el
agent acababa demostrablemente de escribir.

Por eso todos los archivos compose fijan uno, sobrescribible con
`SANDBOX_WORKSPACE_ROOT` — una variable de entorno donde compose la interpola, así que
la raíz del proyecto y no `backend/.env`, salvo en los objetivos `dev` y `prod`, que
pasan ese archivo de forma explícita.

Una sola ruta del host, montada en la misma ubicación en ambos lados, porque el
servicio crea el directorio y luego pide al *daemon* que lo monte — y el daemon
resuelve la ruta en el host. Un volumen con nombre, o cualquier ruta que solo exista
dentro del contenedor del servicio, se rechaza con `mounts denied`.

| | Por defecto | |
|---|---|---|
| Desarrollo local | `/tmp/agenticos-sandbox-workspaces` | Docker Desktop la comparte y cualquiera puede escribir en ella, así que un portátil no necesita preparación |
| Los archivos del servidor | `/var/lib/agenticos/sandbox-workspaces` | Tiene que existir y ser escribible por el uid 10001 — `sudo mkdir -p <path> && sudo chown 10001:10001 <path>`, una vez. No `install -d -o 10001`: `install` resuelve el propietario a través de la base de datos de passwd y rechaza un uid que no tiene cuenta. Va en almacenamiento del que alguien haga copia de seguridad |

Un reinicio barre `/tmp`, que es la única razón para no apuntar ahí un despliegue de
verdad.

Eso se informa en vez de lanzarse como error. Todo listado lleva
`unreadable_reason`, y un cliente lo muestra como una explicación y no como un error
— porque ninguna de las dos causas es un fallo: un servicio que no guarda nada en
disco es una configuración con un arreglo de una línea que el mensaje nombra, y un
host caído estará levantado más tarde.

Lanzar un error lo convertía en un 500, que un navegador solo podía renderizar como
"algo ha ido mal", junto a una lista vacía, que se lee como "no hay archivos". Dos
respuestas equivocadas a la vez.

Leer *un archivo* de un host así se rechaza con la misma frase, en vez de informarse
como "no existe tal archivo", lo que diría que el archivo falta cuando no es así.

**Lo que está en marcha también se lee del servicio.**

La pantalla Sandboxes lo mantiene en una pestaña propia, aparte de la tabla de
conexiones, y lista las sandboxes abiertas de esta organización en el host que nombra
— la conexión por defecto hasta que el operador elija otra.

Cada fila lleva el runtime, qué comparte esa sandbox, su tiempo inactivo y su memoria
frente a su propio techo cuando se pide. Se puede ordenar por tiempo inactivo y por
memoria. Junto a ellas está el registro de actividad por sandbox: qué rutas se
leyeron, qué comandos se ejecutaron y cómo fue cada uno.

Ni el contenido de los archivos ni la salida de los comandos los registra el servicio,
que es lo que impide que un rastro de auditoría se convierta en una forma de leer el
trabajo de otro agent.

El dashboard responde a las mismas tres preguntas en su propia sección, para quien
tenga `connections:manage`. La memoria está detrás de un interruptor ahí por la misma
razón que en la pantalla: el servicio muestrea cada sandbox por separado para eso.

**Ahora los tres techos dividen.**

El listado de sesiones está filtrado a la organización de quien llama, pero lleva
`SANDBOXD_MAX_SESSIONS` y `SANDBOXD_MAX_OPEN_SESSIONS` tal cual desde el servicio —
así que esos dos cuentan a todos los tenants del host mientras las filas cuentan uno.
`len(sessions)` divide únicamente contra `SANDBOXD_MAX_SESSIONS_PER_TENANT`.

Así que la respuesta lleva dos numeradores de todo el host para el otro par, tomados
de la lista sin filtrar antes de que el filtro la estreche:

- `host_session_count` — las sandboxes residentes que el servicio marca como
  `state == "running"`, frente a `limit`;
- `host_open_count` — todas las sesiones que existen, residentes o hibernadas, frente
  a `open_limit`.

Ahora la tarjeta de capacidad puede decir por qué se rechazó una sesión mientras esta
organización está lejos de su propio techo: el host mismo está lleno del trabajo de
otro.

Que esos dos abarquen todo el host es una divulgación deliberada y estrecha —dos
enteros agregados que no nombran nada, muy lejos de las filas de sesión que el filtro
retiene— y el listado está protegido por `connections:view`, la autoridad para vigilar
un host más que la de un miembro cualquiera.

Son `None` en una conexión de Daytona, que no impone ningún techo nuestro que dividir.

Ese listado está **filtrado, no reenviado**. Un solo `sandboxd` responde a todas las
organizaciones que registraron una conexión en su dirección, así que pasar su respuesta
tal cual mostraría a un tenant los contenedores de otro. Las sesiones se emparejan por
la etiqueta `tenant` que esta plataforma pone al abrir una, y se nombran desde
`agent_workspaces` y no descodificando el id de la sesión: el id codifica la clave del
alcance, y parsearlo de vuelta convertiría ese formato en un esquema.

**Lo que el servicio permite se lee del servicio.** La lista de runtimes permitidos y
el techo detrás de cada alias (`SANDBOXD_RUNTIMES`, `SANDBOXD_MEM_LIMIT`,
`SANDBOXD_NETWORK_MODE`, `SANDBOXD_MAX_SESSIONS_PER_TENANT` y el resto) son su propia
configuración de arranque, y a propósito no hay endpoint para escribirlos: un navegador
que pudiera reconfigurar el proceso que sostiene el socket de Docker sería dueño del
host. La pantalla Sandboxes y la tarjeta de runtimes del dashboard los *leen* ambas
para que se vea qué está en vigor, y el Builder ofrece a un agent solo los alias que el
servicio va a aceptar de verdad.

Ninguna de las dos vistas le pregunta nada de esto a una conexión de Daytona. No
publica una lista de permitidos propia ni sostiene ninguna de nuestras sesiones que
enumerar: lo que permite es un ajuste de esa cuenta, y lo que corre ahí se ve en su
propio dashboard.

## Canales de mensajería { #messaging-channels }

| Variable | Por defecto | Descripción |
|----------|---------|-------------|

Las credenciales de los bots no se configuran aquí: cada bot se registra en la
aplicación con su token sellado en el vault, y un bot de Slack lleva además el
signing secret de su propia app y su token `xapp-` (`SLACK_BOT_TOKEN`,
`SLACK_SIGNING_SECRET` y `SLACK_APP_TOKEN` se eliminaron: ahora cada bot es su propia
app de Slack). Las URL de webhook de Telegram se construyen a partir de
`PUBLIC_BASE_URL` (`TELEGRAM_WEBHOOK_BASE_URL` se eliminó), los perfiles de modelo
pueden apuntar a endpoints locales como Ollama sin ninguna bandera
(`ALLOW_INTERNAL_MODEL_ENDPOINTS` se eliminó), y los límites de la sandbox de
`run_python` son configuración de la capability por agent
(`CODE_EXECUTION_TIMEOUT_SECS` / `CODE_EXECUTION_MAX_MEMORY_MB` se eliminaron).

## CORS { #cors }

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `CORS_ORIGINS` | `["http://localhost:3000","http://localhost:8080"]` | Orígenes permitidos (array JSON) |
| `CORS_ALLOW_CREDENTIALS` | `true` | Permite credenciales (cookies) |
| `CORS_ALLOW_METHODS` | `["*"]` | Métodos HTTP permitidos |
| `CORS_ALLOW_HEADERS` | `["*"]` | Cabeceras HTTP permitidas |

Validación en producción: `CORS_ORIGINS` no puede contener `"*"` con
`ENVIRONMENT=production`.

## Límites de tasa { #rate-limiting }

Se aplican a las superficies que un desconocido puede alcanzar, y solo a ellas: la API
pública de runs, el script del widget, su configuración, el handshake del socket de
cualquiera de las dos superficies, la configuración y el logo de una página alojada, y
la subida de un visitante. Las rutas propias de la consola están detrás de una sesión
y no se miden — si toda la API debería llevar un techo es una decisión aparte, no
esta.

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `RATE_LIMIT_RUN_PER_MINUTE` | `30` | `POST /api/v1/agents/{id}/run`, por llamante |
| `RATE_LIMIT_AUTH_PER_MINUTE` | `10` | Todas las rutas de `auth.py` — login, registro, refresh y las rutas de petición y verificación del restablecimiento y del enlace mágico. Se cuenta **por IP y, donde el cuerpo lleve una, por dirección enviada**. Ver más abajo |
| `RATE_LIMIT_EMBED_PER_MINUTE` | `20` | Por dirección, y **dos contadores separados de este tamaño**: uno para `widget.js`, otro para la admisión — el `/config` del widget más el handshake del socket de cualquiera de las dos superficies. Ver más abajo |
| `RATE_LIMIT_HOSTED_PAGE_PER_MINUTE` | `240` | La configuración de una página alojada, **por página** — y su logo, en un contador propio. Ver más abajo |
| `RATE_LIMIT_EMBED_UPLOAD_PER_MINUTE` | `5` | Archivos que un visitante puede guardar en una página alojada. Se cuenta **por dirección y por clave de visitante**, y las dos tienen que permitirlo — la clave la acuña el navegador, así que contar solo esa no acota nada |
| `RATE_LIMIT_TRUST_FORWARDED_FOR` | `false` | Si `X-Forwarded-For` nombra a quien llama |

**Lo que recibe un llamante rechazado** es el sobre de error propio de esta API con
`code: "RATE_LIMIT_EXCEEDED"`, el intervalo en
`error.details.retry_after_seconds`, y ese mismo intervalo en la cabecera
`Retry-After`, que es la que un envoltorio de fetch o una CDN respeta de verdad. El
handshake del socket es la excepción, porque un WebSocket no tiene estado con el que
responder: cierra con `4029` (ver [canales](channels.md#the-raw-websocket)).

**Dos contadores, no uno, y la razón es aritmética.**

Cargar una página con un widget cuesta tres peticiones a esta API: el script, la
configuración y el socket. Contadas juntas, `20` compraba unas siete cargas de página
para un navegador frío en vez de veinte admisiones — y un límite equivocado por un
factor de tres es peor que ningún límite, porque se lee como el número que fijaste.

Por eso `widget.js` tiene su propio cubo. Es cacheable, y un rechazo ahí rompe el
widget del todo en vez de retrasar un mensaje.

La configuración y el handshake se quedan juntos, porque juntos *son* una admisión: un
navegador que leyó una configuración y no abrió ningún socket no entró.

Las cuentas viven en el Redis del despliegue, así que valen entre workers — producción
ejecuta cuatro, y una cuenta por proceso dejaría pasar cuatro veces lo que dice. Si no
se puede llegar a Redis el límite no se aplica y se registra un aviso: negarle a un
visitante su respuesta porque una caché tuvo un tropiezo es el peor de los dos fallos.

Lo que un visitante puede *decir* una vez admitido es otro número, fijado por widget en
el Builder (`rate_limit_per_minute`) y contado por visitante. Estos dos son el techo
para entrar.

### `RATE_LIMIT_HOSTED_PAGE_PER_MINUTE`, y por qué no es por dirección { #rate_limit_hosted_page_per_minute-and-why-it-is-not-per-address }

La configuración de una página alojada se pide **del lado del servidor**, por el
frontend, para que la página se pinte con su marca en el primer fotograma. Eso
significa que la dirección de la petición es la del contenedor del frontend y no la
del visitante — así que contarla metía cada carga de página alojada del despliegue en
un solo cubo, y al visitante que lo disparaba se le servía un 404 sin nada que dijera
por qué. `RATE_LIMIT_TRUST_FORWARDED_FOR` no puede ayudar: un `fetch` del lado del
servidor no envía tal cabecera para que nadie confíe en ella.

Por eso este se cuenta por clave pública. Acota una sola página en vez de racionar a un
visitante, y por eso el valor por defecto es amplio — **no es lo que limita el gasto.**
El gasto empieza en el socket que la página abre después, que lo hace el navegador, y
que se cuenta por dirección bajo `RATE_LIMIT_EMBED_PER_MINUTE`. Y adivinar una clave no
es una estrategia contra 192 bits de `secrets.token_urlsafe`.

### `RATE_LIMIT_AUTH_PER_MINUTE`, y por qué la superficie de auth tiene el suyo { #rate_limit_auth_per_minute-and-why-the-auth-surface-has-its-own }

Todas las rutas de `auth.py` llevan este límite, contado **por IP** y —donde el cuerpo
lleve una dirección (login, registro, las peticiones de restablecimiento y de enlace
mágico)— **también por dirección enviada**, ambas contra esta misma asignación. Las dos
frenan ataques distintos: la IP acota una avalancha desde un origen, la dirección acota
una fuerza bruta contra una cuenta.

Es independiente de la asignación de runs, y más baja, porque lo que defiende es el
coste de un **solo intento**. `verify_password` es bcrypt, unos 170 ms sin punto de
suspensión, así que una avalancha sin medir contra `/login` para cualquier dirección
que tenga cuenta satura el bucle de eventos de un worker sin necesidad de credenciales.

Otras dos cosas cierran el resto de esa superficie, y no necesitan configuración:

- bcrypt corre en un hilo, así que nunca bloquea el bucle;
- una dirección **sin** cuenta se verifica contra un hash falso en vez de saltársela,
  así que una dirección conocida y una desconocida tardan lo mismo en rechazarse y los
  tiempos ya no dicen qué direcciones existen.

### `RATE_LIMIT_TRUST_FORWARDED_FOR`, y por qué está apagada { #rate_limit_trust_forwarded_for-and-why-it-is-off }

Los límites por dirección cuentan `request.client.host`. **Detrás de un proxy o de una
CDN esa es la dirección del proxy, no la del visitante** — todos los visitantes
comparten un cubo, así que un sitio concurrido detrás de Cloudflare agota las veinte
admisiones por minuto del widget para todos a la vez. Encender esto lee en su lugar el
salto **más a la derecha** de `X-Forwarded-For`: la dirección que añadió el propio
proxy de confianza.

Está apagada por defecto porque la cabecera la pone quien llama. Confiada sin
condiciones, un límite por dirección se convierte en un límite por cabecera que
cualquiera esquiva variando una cadena.

El salto **más a la derecha** se lee en vez del de más a la izquierda por la misma
razón: `X-Forwarded-For` es una lista que empieza el cliente y a la que añade cada
proxy, así que la cabeza es lo que escribió el cliente y solo la cola es lo que escribió
un proxy que tú controlas.

**La superficie de auth también necesita esto, y el frontend ahora lo hace posible.**
Las peticiones de auth llegan a la API del lado del servidor a través de las rutas
`/api/auth/*` del propio frontend, así que sin ayuda la dirección en ellas es la del
contenedor del frontend y la mitad por IP de `RATE_LIMIT_AUTH_PER_MINUTE` mete todo el
despliegue en un cubo — unos once inicios de sesión y todo el mundo queda fuera durante
un minuto, y un cubo de refresh agotado cierra las sesiones. A diferencia de la petición
de configuración de una página alojada, esas rutas **reenvían el `X-Forwarded-For` de
quien llama** ([#1047](https://github.com/vstorm-co/agenticos/issues/1047)), así que con
este ajuste encendido el límite se indexa por el cliente real. Enciéndelo para el límite
de auth bajo la misma regla que para todo lo demás —un proxy que controlas delante,
añadiendo al cliente como el salto más a la derecha—, que es la decisión de despliegue
que este ajuste es; apagado, el límite sigue siendo seguro pero compartido.

!!! danger "Enciéndela solo cuando un único proxy que controlas sea lo único que puede alcanzar la API"

    Si el puerto del contenedor también está publicado, quien llama puede poner la
    cabecera él mismo y el límite deja de significar nada.

    **El puerto del frontend cuenta aquí como el de la API.** Sus rutas
    `/api/auth/*` reenvían el `X-Forwarded-For` que se les dé, así que quien pueda
    alcanzar el puerto 3000 saltándose el proxy elige contra qué dirección se
    cuentan sus intentos de inicio de sesión igual de bien que quien pueda alcanzar
    el puerto 8000 — y cada intento aceptado contra una dirección que no tiene dueño
    sigue costando un bcrypt. Por eso tanto `docker-compose-prod.yml` como
    `docker-compose-prod.frontend.yml` publican en `127.0.0.1` por defecto, donde el
    proxy inverso del host los alcanza y nada más lo hace. `BIND_HOST=0.0.0.0` los
    vuelve a abrir, para un proxy que de verdad corra en otro sitio — con la red de
    ese proxy como lo que mantiene la promesa.

    Con dos proxies delante, colapsa la cabecera a un solo salto en tu borde: solo el
    último salto es fiable.

## Un worker cuyo bucle de eventos ha dejado de girar { #a-worker-whose-event-loop-has-stopped-turning }

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `EVENT_LOOP_WEDGED_AFTER` | `15` | Segundos que el bucle de eventos puede dejar de girar antes de que el worker se mate y se reemplace. `0` o menos apaga la comprobación |

Un worker que está *vivo pero no responde* —bloqueado en un lock, dando vueltas en una
llamada síncrona, esperando en un socket que nunca responde— no tiene código de salida,
así que todos los caminos de recuperación de todos los stacks lo leían como sano
mientras las peticiones expiraban. El contenedor pasa a `unhealthy`, y un estado no es
un mecanismo.

Por eso el worker juzga su propio bucle de eventos. Un callback de temporizador marca
el bucle una vez por segundo; un hilo lee la marca, y si el bucle no ha girado durante
`EVENT_LOOP_WEDGED_AFTER` en dos comprobaciones seguidas termina el proceso —
`SIGKILL`, o `os._exit(137)` donde el worker es el PID 1, porque el kernel no entrega a
la init de un namespace una señal para la que esa init no tiene handler. De un modo u
otro `docker inspect` informa de `137`, y "atascado", que nada gestionaba, se convierte
en "muerto", que todos los stacks ya gestionan:

| Stack | Qué reemplaza al worker |
|---|---|
| `docker-compose.yml` | el supervisor de recarga, en su siguiente sondeo |
| `docker-compose-dev.yml` | el PID 1 es el servidor, así que el contenedor sale y actúa `restart: unless-stopped` |
| `docker-compose-prod.yml` | el `Multiprocess` de uvicorn, en medio segundo aproximadamente; los otros tres workers siguen sirviendo |

Dos propiedades son la razón del diseño, y las dos merecen conocerse antes de cambiar
el número:

- **Mide la vivacidad, no la disponibilidad.** La marca es un callback de
  temporizador, no una petición, así que una base de datos lenta o un provider de
  modelos que tarda veinte segundos no son un atasco: el bucle está girando, está
  esperando. Una sonda HTTP habría tenido menos piezas móviles y habría metido en un
  bucle de reinicios a un servidor sano por culpa de una dependencia rota.
- **Dos comprobaciones, no una.** `docker pause`, un cgroup congelado y un portátil
  despertando del sueño paran el vigilante tan a fondo como el bucle, así que la
  primera comprobación después de una lee una marca vieja que no dice nada.

El supervisor de recarga del stack local lee la misma variable para el juicio que hace
desde *fuera* del worker, así que un número cubre los dos.

!!! tip "Ponla a `0` mientras depuras"

    Un breakpoint bloquea el bucle de eventos y nada puede distinguir eso de un
    interbloqueo, así que un worker parado en uno se mata bajo tus pies.

No puede ver un proceso que no está corriendo en absoluto —`kill -STOP`, un cgroup
congelado— porque un vigilante dentro de un proceso parado está parado también. Ese
caso es el que ya cubren los supervisores: el latido del supervisor de recarga se
queda viejo y el ping por tubería de producción se queda sin respuesta.

## Docker / producción { #docker-production }

| Variable | Por defecto | Descripción |
|----------|---------|-------------|
| `DOMAIN` | `example.com` | Dominio de producción (para Traefik) |
| `ACME_EMAIL` | `admin@example.com` | Correo de Let's Encrypt para los certificados SSL |
| `REDIS_PASSWORD` | `change-me-in-production` | Contraseña de Redis para producción |

## Lista de comprobación para producción { #production-checklist }

!!! danger "Todas y cada una se distribuyen con un valor por defecto que está mal en producción"

    Un despliegue alcanzable desde cualquier otro sitio tiene las nueve fijadas a
    conciencia.

- [ ] `SECRET_KEY` — una clave hexadecimal única de 64 caracteres: `openssl rand -hex 32`
- [ ] `API_KEY` — una clave única: `openssl rand -hex 32`
- [ ] `VAULT_MASTER_KEY` — una clave única: `openssl rand -hex 32`. La configuración
      rechaza una vacía fuera de `local`/`development`
- [ ] `ENVIRONMENT` — `production`
- [ ] `DEBUG` — `false`
- [ ] `POSTGRES_PASSWORD` — una contraseña fuerte y única
- [ ] `REDIS_PASSWORD` — una contraseña fuerte
- [ ] `CORS_ORIGINS` — solo el dominio o los dominios reales de tu frontend
- [ ] `OPENROUTER_API_KEY` — tu clave de API de producción

El correo a propósito **no** está en esta lista: un despliegue funciona sin él. Pero
las invitaciones, los restablecimientos de contraseña y las notificaciones se quedan
todos sin enviar, en silencio, hasta que `SMTP_HOST` y el resto de
[Correo (SMTP)](#email-smtp) apunten a un servidor de verdad — así que un despliegue
que se lo salte debería saltárselo a sabiendas.
