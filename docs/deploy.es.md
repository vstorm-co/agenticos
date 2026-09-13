---
source_sha: 6f2247bf1919
---

# Despliega en un servidor { #deploy-to-a-server }

Un host, Docker Compose, un proxy inverso delante. Ese es todo el camino que se
publica, y es el que hace funcionar los despliegues en los que se usa este
proyecto.

No hay manifiestos de Kubernetes, ni quickstarts de un clic para los proveedores
de plataforma como servicio. No es modestia sobre la escala. El stack son seis
contenedores, dos de los cuales guardan estado, uno de los cuales puede arrancar
contenedores propios, y uno de los cuales es un Postgres que debe ser pgvector -
que ya es más de lo que modela un destino de despliegue a base de `git push`, y
una guía que fingiera lo contrario estaría describiendo un despliegue que nadie
ha ejecutado.

!!! tip "Lee antes la [lista de comprobación para producción](configuration.md#production-checklist)"

    Nueve ajustes se publican con valores por defecto que están bien en un
    portátil y mal en un host al que puede llegar otra persona.
    `scripts/server-init.sh`, más abajo, genera los nueve, así que la lista es lo
    que compruebas después y no lo que escribes.

## Qué necesitas { #what-you-need }

| | |
|---|---|
| **Un host** | 4 vCPU y 8 GB de RAM lo hacen funcionar. Ver [dimensionado](#sizing-the-host) |
| **Docker** | Engine 24+ con el plugin Compose (2.24 o posterior), y tu usuario en el grupo `docker`. En el host no se construye nada: las imágenes se descargan de GHCR |
| **Dos nombres de host** | uno para el sitio, otro para la API — ver [por qué dos](#why-two-hostnames) |
| **Un proxy inverso** | [Traefik](#option-a-traefik) o [Nginx](#option-b-nginx). Termina el TLS |
| **Una clave de OpenRouter** | cada colección hace sus embeddings a través de ella. Los modelos de chat se configuran por organización, en el producto |

El host también necesita los puertos 80 y 443 abiertos, y nada más. Postgres,
Redis y la API de Prefect no se publican en ninguna interfaz.

### Por qué dos nombres de host { #why-two-hostnames }

El navegador habla con los dos. La mayoría de las llamadas pasan por las rutas de
servidor del propio frontend, pero el WebSocket del chat se conecta directamente
a la API, así que la API necesita un nombre que un navegador pueda resolver y un
certificado propio.

`app.example.com` y `api.example.com` es la forma. Pueden ser dos nombres
cualesquiera; lo que no pueden ser es un solo nombre con un prefijo de ruta,
porque las cookies de la API y las del sitio están limitadas al host.

## Dimensionar el host { #sizing-the-host }

Medido sobre un despliegue en reposo, no estimado:

| | en reposo | techo |
|---|---|---|
| `app` (2 workers de uvicorn) | ~1,0 GB | 2,5 GB con los 4 workers por defecto |
| `db` | ~1,3 GB con el ajuste de abajo | 2 GB |
| `prefect-runner` | 241 MiB | 1,5 GB |
| `prefect-server` | 245 MiB | 768 MB |
| `frontend` | ~300 MB | 1 GB |
| `redis` | 9 MiB | 512 MB |

El número que decide el host es **`UVICORN_WORKERS`**. Cada worker es un proceso
aparte que importa la aplicación entera — 460 MiB, creado con spawn y no con
fork, así que no se comparte nada. Cuatro de ellos son 1,9 GB antes de que llegue
una petición.

Dos workers bastan para un equipo de diez y aun así dejan uno atendiendo mientras
[el watchdog](configuration.md#a-worker-whose-event-loop-has-stopped-turning)
reemplaza a un hermano atascado. Un solo worker es el ajuste que hay que evitar:
un bucle de eventos bloqueado es entonces todo el despliegue, hasta que se mata a
sí mismo.

!!! note "La base de datos está ajustada contra su propio límite"

    `docker-compose-prod.yml` ejecuta Postgres con `shared_buffers=512MB` frente
    a un límite de 2 GB, y le da 512 MB de `/dev/shm` — el valor por defecto de
    Docker es 64 MB, que un escaneo en paralelo sobre los vectores de una
    colección agota, informando `could not resize shared memory segment`. Si
    mueves el límite, mueve el ajuste con él; están escritos uno al lado del otro
    por esa razón.

## Apunta los nombres al host { #point-the-names-at-the-host }

Dos registros A, antes que nada. Let's Encrypt comprueba que controlas un nombre
descargando un archivo por HTTP desde donde ese nombre resuelva, así que no se
emite ningún certificado hasta que esto sea cierto y se haya propagado.

```
app.example.com   A   203.0.113.10
api.example.com   A   203.0.113.10
```

!!! warning "Un comodín no hace esto por ti"

    Donde `*.example.com` ya apunta a algún sitio — normalmente una web de
    marketing — los dos nombres resuelven ahí. Un registro para el nombre
    concreto gana al comodín, así que el arreglo es añadir los dos de arriba, no
    quitar el comodín.

Compruébalo desde algún sitio que no sea el host, porque el host puede tener su
propia respuesta:

```bash
dig +short app.example.com api.example.com
```

## Llévalo al host { #get-it-onto-the-host }

```bash
sudo install -d -o "$USER" -g "$USER" /opt/agenticos
git clone https://github.com/vstorm-co/agenticos.git /opt/agenticos
cd /opt/agenticos
bash scripts/server-init.sh
```

`server-init.sh` escribe `backend/.env`: genera los cinco secretos, pide los dos
nombres de host, una dirección para Let's Encrypt y la clave de OpenRouter, y
deriva las URL públicas y el origen CORS de lo que le hayas dado. Se niega a
sobrescribir un archivo existente.

El clon es donde viven los archivos de compose y ese archivo de entorno; de él no
se ejecuta ningún código. Lo que se ejecuta son las dos imágenes que publica el
repositorio.

### Las imágenes { #the-images }

| | |
|---|---|
| `ghcr.io/vstorm-co/agenticos-backend` | La API, el runner de Prefect y las migraciones - una imagen, tres comandos |
| `ghcr.io/vstorm-co/agenticos-frontend` | La consola |

Las dos se construyen para `linux/amd64` y `linux/arm64` en
`.github/workflows/images.yml`. Una release (`v0.0.380`) publica `0.0.380` y
mueve `latest`; cada commit en `main` publica `edge` y `sha-<short>`. Los
archivos de compose leen la etiqueta de `AGENTICOS_VERSION` en `backend/.env` y
por defecto usan `latest`.

Tres reglas que mantiene el workflow, y las tres conviene conocerlas antes de
fiarse de una etiqueta:

- **Solo se publica un commit de `main`.** Una etiqueta `v*` empujada desde una
  rama, o una ejecución lanzada sobre ella, se rechaza antes de construir nada -
  así que `latest` no puede pasar la frontera de la pull request.
- **Una release sobre un commit que `main` ya construyó no se reconstruye.** Su
  manifiesto `sha-<short>` recibe la versión y `latest` como nombres adicionales,
  así que los digests a los que un host se fijó son exactamente los que nombra la
  release.
- **A un commit sin imágenes se le pueden dar.** Ejecuta el workflow a mano con
  su entrada `sha` - `gh workflow run images.yml --ref main -f sha=<commit>` - y
  publica la etiqueta `sha-<short>` de ese commit y nada que se mueva. Ese es el
  camino para un commit más antiguo que el workflow, y para uno cuya ejecución se
  perdió.

!!! warning "Fija una release en un host que te importe"

    `AGENTICOS_VERSION=0.0.380` en `backend/.env`, para que `make prod` en un mal
    día descargue lo que funcionaba ayer y no lo que se publicó esta mañana.
    `scripts/deploy.sh` la fija por ti - a la etiqueta `sha-` del commit que
    despliega - exactamente mientras dura el despliegue.

Los dos paquetes se descargan de forma anónima. Si una descarga responde
`unauthorized`, el paquete se ha hecho privado o hay un `docker login ghcr.io`
caducado en medio; ninguna de las dos cosas la puede arreglar un host por sí
solo.

!!! danger "`backend/.env` guarda la clave que descifra todas las credenciales almacenadas"

    `VAULT_MASTER_KEY` es lo que hace legibles las claves de provider de una
    organización, los tokens de bot y las credenciales MCP. Perderla no te deja
    fuera del producto; hace irrecuperable cada secreto que hay en él. Guarda una
    copia del archivo en algún sitio que un disco perdido no se lleve consigo, y
    rótala con [`agenticos cmd vault-rotate`](secrets.md#operations) en vez de
    editando.

Dos cosas opcionales por las que no pregunta, las dos en ese archivo: `SMTP_*`,
sin el cual no se pueden enviar invitaciones ni restablecimientos de contraseña,
y `LOGFIRE_TOKEN`, que es adonde van las trazas de los runs de los agents.

## Elige un proxy inverso { #choose-a-reverse-proxy }

Algo tiene que terminar el TLS y enrutar los dos nombres. Las dos opciones de
abajo llegan a los mismos contenedores; elige según si ya tienes uno en marcha.

### Opción A: Traefik { #option-a-traefik }

El camino más corto, y el que hay que elegir en un host que ya tiene Traefik: los
contenedores llevan etiquetas, Traefik los descubre, pide el certificado y lo
renueva. Nada que recargar y ningún segundo archivo de configuración que mantener
sincronizado.

Si Traefik aún no está, el repositorio trae uno: `traefik/traefik.yml` y
`docker-compose-traefik.yml`, que es un entrypoint en el 443 con un resolver de
Let's Encrypt y el 80 redirigiendo hacia él.

```bash
docker network create traefik_webgateway
docker compose --env-file backend/.env -f docker-compose-traefik.yml up -d
```

Donde Traefik **ya** está funcionando, deja esos archivos en paz y apunta
`TRAEFIK_NETWORK` a la red que vigila. Los overlays leen ese nombre, así que no
hay que cambiar nada del proxy existente.

Después levanta el stack con `PROXY=traefik`, que añade los dos archivos de
overlay que llevan las etiquetas:

```bash
make prod PROXY=traefik
make prod-frontend PROXY=traefik
```

`server-init.sh` ya ha escrito `PROXY=traefik` en `backend/.env`, que es de donde
lo lee `scripts/deploy.sh` — así que los despliegues posteriores conservan el
proxy con el que se configuró este host y no el que asumiera un script.

!!! info "`exposedByDefault: false` está haciendo trabajo de verdad"

    Es el único ajuste de `traefik/traefik.yml` que merece la pena leer antes de
    ejecutarlo. Solo `app` y `frontend` llevan `traefik.enable=true`, así que
    Postgres, Redis, el servidor de Prefect y el demonio de la sandbox no son
    alcanzables desde nada fuera del host — y eso es una propiedad de *no estar
    etiquetados*, así que sobrevive a que alguien añada un servicio sin pensar en
    el proxy.

### Opción B: Nginx { #option-b-nginx }

Para un host donde Nginx ya termina el TLS, o donde el proxy no está en Docker en
absoluto. El stack publica los dos puertos en `127.0.0.1` y Nginx llega a ellos
ahí:

```bash
make prod
make prod-frontend
```

`nginx/nginx.conf` es la plantilla. Dos sustituciones antes de que sirva nada: el
`server_name` de cada bloque es `${DOMAIN:-localhost}`, y Nginx no lo expande —
pon los dos nombres de host a mano. Los certificados son tuyos de obtener y
renovar, y también lo es la cabecera `Strict-Transport-Security`, que el backend
deja deliberadamente a lo que termine el TLS.

!!! warning "`BIND_HOST` es un ajuste de seguridad, no una comodidad"

    El valor por defecto de loopback es lo que hace que el límite de intentos de
    autenticación signifique algo. `RATE_LIMIT_TRUST_FORWARDED_FOR` le dice a la
    API que cuente un intento contra la dirección que reenvía el proxy, así que
    lo que pueda llegar a la API *saltándose* el proxy elige la dirección contra
    la que se cuentan sus intentos. Pon `BIND_HOST=0.0.0.0` solo para un proxy en
    otra máquina, y limita el puerto por firewall a esa máquina.

!!! warning "El frontend es un proyecto de compose propio"

    Compose nombra un proyecto según el directorio, así que los dos stacks eran
    `agenticos` — y levantar el frontend informaba entonces de los cinco
    contenedores del backend como **orphans**, con la propia sugerencia de
    compose de volver a ejecutar el comando con `--remove-orphans`. Seguir ese
    consejo detiene la API, la base de datos, Redis y los dos servicios de
    Prefect. Los targets de `make` y `scripts/deploy.sh` pasan
    `-p agenticos-frontend`, así que el aviso ha desaparecido. Los archivos de
    compose tampoco fijan nombres de contenedor - cada proyecto nombra los suyos,
    así que dos stacks en un host no pueden apropiarse de los contenedores del
    otro, y `deploy.sh` espera a los servicios `app` y `frontend` y no a un
    nombre. Un despliegue anterior a los dos arreglos se recrea con los nombres
    nuevos en su siguiente `up`; no hay que quitar nada a mano.

    Los dos proyectos se siguen encontrando en una red con un nombre fijo -
    `agenticos_edge` en producción, `agenticos_backend` en el servidor de
    desarrollo - porque el frontend se une a ella como red externa. Un host que
    ejecute **dos** stacks de AgenticOS separa `AGENTICOS_EDGE_NETWORK` y
    `AGENTICOS_DATA_NETWORK` (o `AGENTICOS_NETWORK`) en el `backend/.env` de cada
    stack; si no, los `db`, `redis` y `app` de ambos stacks resuelven en un mismo
    bridge, y una petición puede llegar a la base de datos del vecino.

## Arráncalo y crea la primera cuenta { #start-it-and-create-the-first-account }

`make prod` descarga las imágenes, arranca el stack y ejecuta las migraciones -
lo último como un servicio `migrate` al que espera la API, así que un
`docker compose up -d` a mano sobre los mismos archivos hace lo mismo. La primera
descarga son unos 2 GB; una posterior son las capas que hayan cambiado.

Después crea una organización, un propietario (owner) y un agent que funcione:

```bash
docker compose --env-file backend/.env -f docker-compose-prod.yml \
  exec -T app agenticos cmd bootstrap \
  --email you@example.com --password 'a real password' \
  --org 'Your Company' --provider anthropic --api-key sk-ant-...
```

La clave de provider que va aquí es con lo que funciona el agent de
demostración. Sin ella el agent se crea y no puede responder; cualquier otro
provider se añade en el producto, por organización, desde el vault.

!!! tip "Compruébalo desde fuera, no desde el host"

    ```bash
    curl -fsS https://api.example.com/api/v1/health
    curl -fsSo /dev/null -w '%{http_code}\n' https://app.example.com
    ```

    Un stack que está sano en el host e inalcanzable desde internet es DNS, el
    firewall o el certificado — tres cosas que una comprobación de salud dentro
    del host no puede ver.

Después, una vez, a mano: inicia sesión, invita a alguien (lo que demuestra
`SMTP_*`) y envía un mensaje al agent de demostración (lo que demuestra la clave
de provider y el WebSocket). Cada cosa recorre un camino que aquí no comprueba
nada más.

!!! info "Las cabeceras de seguridad vienen del backend, así que cualquier proxy queda cubierto"

    Una Content-Security-Policy, `X-Frame-Options: DENY`,
    `X-Content-Type-Options: nosniff`, `Referrer-Policy` y `Permissions-Policy`
    se ponen en cada respuesta — incluido el 500 de una excepción no controlada,
    que se construye fuera del stack de middleware y las estampa él mismo. La
    documentación interactiva de la API renuncia solo a la CSP, porque Swagger
    carga recursos que una política estricta prohíbe.

    **HSTS se deja deliberadamente al proxy**, que es donde termina el TLS. Un
    proxy que ponga su propia CSP debería ser al menos tan estricto como esta.

### Encender la sandbox { #turning-the-sandbox-on }

El servicio que ejecuta el código de un agent está detrás de un perfil de
compose, porque es el único contenedor que tiene el socket de Docker y montarlo
en un host compartido debería ser una decisión y no un valor por defecto. Tres
cosas, una vez:

```bash
make sandbox-token                       # writes SANDBOXD_TOKEN to backend/.env
sudo mkdir -p /var/lib/agenticos/sandbox-workspaces
sudo chown 10001:10001 /var/lib/agenticos/sandbox-workspaces
```

Después un despliegue la levanta: `scripts/deploy.sh` pasa `--profile sandbox`
cuando `SANDBOXD_TOKEN` en `backend/.env` tiene valor, así que es el propio host
quien dice si ejecuta una. También exporta `DOCKER_GID` leído del socket — todos
los archivos de compose de aquí lo interpolan en el `group_add` de la sandbox, y
su valor por defecto `0` es el propietario del socket en casi ninguna
distribución de Linux. No hace falta nada más en `.env`: el backend llega al
demonio a través de una *conexión* de sandbox que alguien crea en la consola, y
`http://sandboxd:8080` se reconoce como propio de este despliegue.

!!! warning "Un perfil del que no se avisa a compose es un servicio que compose detiene"

    `up -d` sobre el mismo proyecto sin `--profile sandbox` no deja la sandbox en
    paz — la detiene. Así que a un host que la había arrancado a mano se la
    quitó su siguiente despliegue, con la ejecución de código de un agent
    fallando por motivos que no estaban ni cerca del despliegue que lo causó
    (#1506). Por eso el script lee el token en vez de aceptar un flag.

## Desplegar un cambio { #deploying-a-change }

### A mano { #by-hand }

```bash
remote=$(ssh you@your-host 'mktemp -t agenticos-deploy.XXXXXX')
ssh you@your-host "cat > $remote" < scripts/deploy.sh
ssh you@your-host "trap 'rm -f $remote' EXIT; bash $remote <commit-sha>"
```

`scripts/deploy.sh` trae ese commit, espera a las imágenes que CI publicó para él
(`sha-<short>`, normalmente ya están), las descarga, reinicia y espera a que los
dos contenedores se declaren sanos antes de devolver distinto de cero o no. Toma
un **commit** y no una rama, así que lo que se despliega es lo que se revisó y no
aquello a lo que `main` se haya movido desde entonces - y lo que se ejecuta es
byte a byte lo que construyó CI, en un host que nunca necesita la cadena de
herramientas.

!!! warning "Cópialo al host y ejecútalo allí — no lo canalices a `bash -s`"

    Bajo `bash -s` el script es la propia entrada estándar del shell, y el primer
    comando dentro de él que lee stdin se come el resto. `docker compose exec`
    reenvía stdin al contenedor incluso con `-T`, así que la migración se comió
    todo lo que había debajo, bash llegó a EOF y el despliegue salió con **0**
    sin haber construido nunca el frontend ni haber esperado a ningún contenedor.
    El sitio estaba caído y el despliegue en verde
    ([#1488](https://github.com/vstorm-co/agenticos/issues/1488)).

    Dos conexiones en lugar de una es lo que impide que el procedimiento pueda
    truncarse a sí mismo.

No es un despliegue sin interrupción. Compose recrea los contenedores cuya imagen
ha cambiado, así que el sitio no está disponible durante los pocos segundos que
eso lleva.

### Desde GitHub, con una aprobación { #from-github-with-an-approval }

`.github/workflows/deploy.yml` ofrece cada merge a `main` para desplegarlo y
espera a que alguien lo apruebe. Esa barrera es **un ajuste del repositorio, no
un paso del archivo** — sin ella, el workflow despliega cada merge sin
supervisión.

Configúralo una vez:

1. **Settings → Environments → New environment**, con el nombre `production`.
2. Marca **Required reviewers** y añade a quien pueda aprobar. Esa es la barrera.
3. Añade las variables del entorno: `SITE_URL`, `API_URL` y `APP_DIR` si el
   checkout no está en `/opt/agenticos`.
4. Añade los secretos de abajo.

!!! warning "Cancela un despliegue que no vayas a aprobar"

    Todas las ejecuciones comparten el grupo de concurrencia `deploy-production`,
    y una ejecución parada en la barrera de aprobación lo retiene. No caduca por
    sí sola — GitHub cancela una sin atender después de 30 días — así que hasta
    que alguien la apruebe o la cancele, los merges posteriores hacen cola detrás
    de una decisión que nadie va a tomar, y el servidor sigue ejecutando lo
    último que se desplegó.

    Así que un despliegue que has decidido no hacer se cancela, no se deja. Uno
    dejado esperando sobre un commit ya superado bloqueó aquí tres ejecuciones
    posteriores antes de que nadie se fijara en la cola en vez de en las
    ejecuciones.

| Secreto | Qué |
|---|---|
| `DEPLOY_HOST` | La dirección del host |
| `DEPLOY_USER` | La cuenta a la que pertenece el checkout |
| `DEPLOY_SSH_KEY` | Una clave privada cuya mitad pública está en el `authorized_keys` de esa cuenta |
| `DEPLOY_KNOWN_HOSTS` | `ssh-keyscan your-host`, ejecutado desde algún sitio de confianza |

Genera la clave para esto y para nada más:

```bash
ssh-keygen -t ed25519 -N '' -C 'github-actions-deploy' -f deploy_key
ssh-copy-id -f -i deploy_key.pub you@your-host
ssh-keyscan your-host                    # → DEPLOY_KNOWN_HOSTS
cat deploy_key                           # → DEPLOY_SSH_KEY, then delete it locally
```

!!! note "La clave del host es un secreto en vez de un `ssh-keyscan` en el momento del despliegue"

    Escanear en el momento del despliegue confía en lo que sea que responda en
    esa dirección, que es justo lo que una clave de host existe para evitar.
    Escanea una vez, desde un sitio de confianza, y guarda la respuesta.

Entonces aparece una ejecución con **Review deployments**; aprobarla arranca el
job. `workflow_dispatch` ejecuta el mismo job contra una ref que tú indiques, que
es como se hace una vuelta atrás, y pasa por la misma aprobación.

## Copias de seguridad { #backups }

Un volumen importa, y no es obvio cuál:

| Volumen | Qué guarda | ¿Copia? |
|---|---|---|
| `postgres_data` | todo — agents, conversaciones, credenciales selladas | **sí** |
| `media_data` | archivos subidos, antes de la ingesta | sí |
| `redis_data` | buckets del límite de peticiones y cachés | no, todo reconstruible |
| `prefect_data` | el historial de ejecuciones de los flows | no |

```bash
docker compose --env-file backend/.env -f docker-compose-prod.yml exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "agenticos-$(date +%F).dump"
```

Los identificadores salen del propio entorno del contenedor en vez de estar
escritos, porque los dos son ajustes: un despliegue que hubiera cambiado
cualquiera de ellos obtendría, si no, un archivo vacío y un error que nadie lee
al pasar.

!!! danger "Una copia de la base de datos sin `backend/.env` no es una copia"

    Las credenciales que hay en ella están selladas con `VAULT_MASTER_KEY`.
    Restauradas junto a una clave distinta, cada clave de provider, token de bot
    y credencial MCP del volcado es ilegible — y el producto te lo dirá, negativa
    a negativa.

## Volver atrás { #rolling-back }

| | Cómo |
|---|---|
| **Código** | Despliega el commit anterior: `workflow_dispatch` con su sha, o `scripts/deploy.sh`. Las imágenes siguen en el registro, así que esto es una descarga y no una construcción. Un commit sin imágenes `sha-<short>` - más antiguo que `images.yml`, o con su ejecución perdida - se publica primero con `gh workflow run images.yml --ref main -f sha=<commit>`; el despliegue nombra ese comando cuando se rinde de esperar |
| **Esquema** | `agenticos db downgrade --revision=-1`, y después despliega el código que le corresponde |
| **Datos** | `pg_restore` del volcado, y después comprueba la migración que el código espera |

Volver el código atrás **a través de una migración es una decisión, no un
comando**. El código antiguo se encuentra con un esquema que nunca ha visto; si
eso funciona depende de la migración. Léela antes de dar nada por supuesto.

## Resumen { #recap }

- **Un host, Compose, un proxy delante.** Siete contenedores - uno de ellos
  ejecuta las migraciones y termina - dos de ellos con estado, y todos se
  descargan: en el host no se construye nada. Fija `AGENTICOS_VERSION`.
- **`UVICORN_WORKERS` decide lo que cuesta el host.** 460 MiB por worker, nada
  compartido. Dos para un equipo, cuatro para tráfico de verdad.
- **El DNS antes que todo lo demás.** No se emite ningún certificado hasta que
  los nombres resuelvan al host.
- **La aprobación es un ajuste del repositorio**, no una línea del workflow. Sin
  required reviewers en el entorno `production`, cada merge se despliega solo.
- **Copia `postgres_data` y `backend/.env` juntos.** Cualquiera de los dos sin el
  otro no es una restauración.
