---
source_sha: "0dc46f479226"
---

# Escalar más allá de un host { #scale-beyond-one-host }

El camino que se entrega es [un host con Docker Compose](deploy.md). Esta página
es para el paso siguiente: un Postgres gestionado, varios hosts de API, workers
propios o varios despliegues uno al lado de otro. Dice qué necesita cada parte
cuando se mueve y qué no hace todavía la plataforma, para que un plan se
construya sobre lo que funciona.

Primero, medir. Un host del [tamaño recomendado](deploy.md#sizing-the-host)
soporta un equipo de unas decenas de personas, y la mayor parte de la lentitud
en un host pequeño es CPU steal o un pool demasiado pequeño, no una réplica que
falta. La [batería de carga](load-testing.md) ejecuta la misma carga contra
cualquier despliegue.

## Qué guarda estado y qué no { #what-holds-state-and-what-does-not }

| Parte | Qué guarda | Cómo crece |
|---|---|---|
| API (`app`) | Nada propio. Las sesiones, la presencia, los turnos de chat en curso y el feed de actualizaciones en vivo están en Postgres y Redis | Más workers de uvicorn, luego más hosts detrás de un balanceador |
| Worker | Nada. Los jobs, los leases y las programaciones son filas en Postgres | Más procesos, en cualquier host, con los pools repartidos entre ellos |
| Consola (`frontend`) | El branding que guarda en caché cinco minutos | Más instancias |
| Postgres | Todo lo duradero: organizaciones, agentes, conversaciones, vectores, la cola de jobs | Una instancia mayor, o una gestionada |
| Redis (Valkey) | Una caché y sus canales pub/sub, reconstruidos tras un reinicio | Una instancia que comparten todos los hosts |
| Archivos subidos | Un volumen en el host, o un bucket | Un bucket en cuanto más de un host los lee o los escribe |
| Servicio de sandboxes | Los sandboxes en los que los agentes ejecutan comandos | Su propio host, ver [Espacios de trabajo de agentes](configuration.md#running-the-service-on-another-host) |

## Una base de datos por despliegue { #one-database-per-deployment }

Todas las organizaciones de un despliegue comparten una base de datos de
Postgres, y cada consulta está acotada a la organización. Los vectores de cada
base de conocimiento también están en ella, mediante pgvector, igual que la
cola de jobs. `POSTGRES_DB` nombra la única base de datos que usa un
despliegue: no hay una base de datos vectorial aparte, ni réplica de lectura,
ni sharding por organización.

Varias bases de datos significan, por tanto, varios despliegues. Es la
respuesta para datos que deben quedarse en una región, para una unidad de
negocio con sus propios administradores y para un tenant cuya carga no debe
alcanzar a los demás. Cada despliegue tiene sus propios nombres de host,
`SECRET_KEY` y `VAULT_MASTER_KEY`, y en tiempo de ejecución no comparten nada.

Pueden compartir infraestructura. Dos despliegues en un mismo servidor de
Postgres necesitan sus propias bases de datos (`POSTGRES_DB`), y en un mismo
Redis sus propios números de `REDIS_DB`, para que los buckets de límites y las
respuestas en caché no se mezclen. Un bucket también es de un solo despliegue.
Un agente pasa de uno a otro como su spec: se exporta como YAML en uno
(`GET /agents/{id}/spec.yaml`) y se importa en un agente del otro.

## Un Postgres externo { #an-external-postgres }

Un Postgres gestionado o propio funciona cuando tiene esto:

- **PostgreSQL 16 con pgvector.** Los servicios gestionados lo ofrecen como la
  extensión `vector`. La plataforma la crea la primera vez que se escribe en una
  colección, así que el rol que se conecta necesita `CREATE` sobre la base de
  datos, o un administrador la crea antes. Lo mismo vale para
  `pg_stat_statements`, que una migración añade donde puede y omite con un aviso
  donde no.
- **Una conexión cifrada** a una base de datos en otro host. Ver
  [Conexiones cifradas](configuration.md#encrypted-connections-tls): el override
  tiene que llegar a `app`, `migrate` y `worker`, porque los archivos de compose
  fijan el host en cada uno.
- **Las migraciones se ejecutan una vez.** El servicio `migrate` las aplica
  antes de que arranque la API. Con varios hosts, se ejecuta desde un despliegue
  y no desde cada uno.

Tras una conmutación por error del Postgres gestionado, la primera petición de
cada proceso que se encuentra con una conexión caída falla, y el pool descarta
entonces todas las conexiones más antiguas que ella. Los motores no comprueban
una conexión antes de usarla, porque eso costaría un viaje de ida y vuelta en
cada entrega del pool.

### Contar las conexiones { #counting-connections }

Primero, dimensionar `max_connections`, o Postgres rechaza conexiones con "too
many clients" antes de que un pool pueda encolar o descartar la carga.

Cada proceso de la API abre dos pools de `DB_POOL_SIZE + DB_MAX_OVERFLOW`, 15
cada uno por defecto: uno para las peticiones y otro para las búsquedas
vectoriales, que se ejecutan dentro de una petición que ya tiene una conexión.
Un proceso worker abre los mismos dos, más una conexión de corta duración por
cada job que ejecuta. Cada proceso hijo de ingesta es un proceso propio, y el
job que ejecuta escribe sus vectores con un motor propio con el pool por
defecto de 15, que se cierra al terminar el job. Las búsquedas de conocimiento
de un agente se conectan una vez por búsqueda, sin pool.

```text
max_connections ≥ hosts de API × UVICORN_WORKERS × 30
                + procesos worker × 30
                + hijos de ingesta × 15
                + margen para migraciones y la sesión de un administrador
```

Dos hosts de API con cuatro workers de uvicorn cada uno y dos workers con un
hijo de ingesta cada uno suman 330, así que 400 es un valor sensato. Son
límites superiores: un despliegue en reposo mantiene muchas menos. El archivo
de compose de producción fija 200 para un host.

### PgBouncer { #pgbouncer }

Solo en modo sesión. El pooling por transacción rompe dos cosas de las que
depende la plataforma: los prepared statements de asyncpg, que ningún ajuste de
aquí desactiva, y el advisory lock a nivel de sesión que impide que una fuente
de sincronización se ejecute dos veces a la vez. El modo sesión limita cuántas
conexiones de servidor existen, pero ahorra poco más, así que dimensionar los
pools frente a `max_connections` suele ser la mejor palanca.

## Más hosts de API { #more-api-hosts }

Delante va un balanceador que deje pasar WebSockets: las actualizaciones en vivo
y el chat de la consola usan `/api/v1/ws/*`. No hacen falta sesiones fijas.
Quien vuelve a conectar su socket a otro host sigue un turno en curso a través
de Redis, y la presencia y los límites también se guardan allí.

Cada host necesita:

- **Los mismos secretos.** `SECRET_KEY` firma tokens que cualquier host debe
  verificar, y `VAULT_MASTER_KEY` descifra cada credencial guardada.
- **El bucket.** Con `FILE_STORAGE_BACKEND=local`, un archivo subido a través de
  un host no está en el otro, y el worker que lo analiza puede no estar en
  ninguno de los dos. Usa `s3` (ver
  [Archivos subidos](configuration.md#uploaded-files-at-rest)).
- **El mismo Redis**, como una instancia o un endpoint delante de una primaria.
  El cliente no entiende de clústeres, así que Redis Cluster no está soportado.
- **`RATE_LIMIT_TRUST_FORWARDED_FOR`** en cuanto el balanceador sea lo único que
  llega a los hosts, o todos los visitantes compartirán el bucket del
  balanceador.

Un turno de chat se ejecuta en el proceso de la API que lo aceptó, no en un
worker, así que los hosts de API soportan la carga del chat y `UVICORN_WORKERS`
se dimensiona para ella como [en un solo host](deploy.md#sizing-the-host).

Varias instancias de la consola no son un problema. El branding que guardan en
caché es de cada instancia: el cambio de un administrador se ve al momento en la
instancia que lo guardó y en las demás en menos de cinco minutos.

## Más workers { #more-workers }

Ejecuta tantos procesos worker como necesite el trabajo, en cualquier host.
Reclaman jobs con `SKIP LOCKED`, así que nunca dos ejecutan el mismo, y
cualquiera de ellos dispara una programación que toca. Un worker que muere
devuelve sus jobs en menos de `WORKER_LEASE_SECONDS`.

Separa los pools cuando el análisis de documentos compite con las ejecuciones
de agentes. `WORKER_POOLS=agent,system` en un grupo de procesos y
`WORKER_POOLS=ingest` en hosts con memoria de sobra evitan que una subida
grande retrase una rutina. La sonda de salud y `agenticos cmd doctor` avisan de
un pool que ningún worker vivo atiende. Los ajustes de
[Trabajo en segundo plano](configuration.md#background-work) dimensionan cada
proceso.

## Redis { #redis }

Todos los hosts de API y los workers usan el mismo Redis: transporta entre
ellos el feed de actualizaciones en vivo, la presencia, los turnos en curso y
los límites. Es una caché, así que un reinicio no pierde nada duradero. Las
actualizaciones en vivo se reconectan, y quien sigue un turno en curso ve la
respuesta en la transcripción cuando llega, en lugar de fotograma a fotograma.

## Medir antes de añadir hosts { #measure-before-you-add-hosts }

- **`agenticos cmd doctor`** dice a qué Postgres y a qué Redis llegó cada
  conexión, si iba cifrada y si los workers están vivos.
- **`pg_stat_statements`** muestra qué sentencias cuestan más a la base de
  datos.
- **Logfire**, con `LOGFIRE_ENVIRONMENT` fijado por despliegue, separa las trazas
  de un despliegue de las de otro (ver
  [Observabilidad](configuration.md#observability-logfire)).
- **La [batería de carga](load-testing.md)**, ejecutada antes y después de un
  cambio, dice si ayudó.

## Lo que todavía no hace { #what-it-does-not-do-yet }

- Réplicas de lectura, o una base de datos vectorial propia.
- Sharding de organizaciones entre bases de datos dentro de un despliegue.
- PgBouncer en modo transacción, o Redis Cluster.
- Manifiestos de Kubernetes. Las imágenes son las mismas que ejecutan los
  archivos de compose, y cada servicio lleva su propio health check, así que un
  clúster las ejecuta con el entorno que describe esta página.
