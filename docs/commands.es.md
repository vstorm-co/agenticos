---
source_sha: 7e69c0532818
---

# Comandos { #commands }

Este proyecto ofrece comandos a través de dos interfaces: objetivos de **Make**
para los flujos de trabajo habituales y una **CLI del proyecto** para un control
fino.

## Comandos de Make { #make-commands }

Ejecútalos desde el directorio raíz del proyecto.

### Inicio rápido { #quick-start }

| Comando | Descripción |
|---------|-------------|
| `make quickstart` | Arranca Docker, ejecuta las migraciones, crea el usuario administrador. **No** instala dependencias: primero `make install` |
| `make install` | Todo el camino de preparación: `backend/.env` a partir del ejemplo si no hay ninguno, las dependencias del backend con uv, `frontend/node_modules` con bun, y los hooks de pre-commit. Todo ello, porque `make check` necesita todo ello: `db-check` lee el archivo de entorno, y eslint, prettier, tsc, vitest y next solo viven en `node_modules`. Ambos son por checkout, así que esto se debe en cada clonado; un `.env` existente no se sobrescribe nunca |

### Desarrollo { #development }

| Comando | Descripción |
|---------|-------------|
| `make run` | Arranca el servidor de desarrollo con recarga en caliente |
| `make run-prod` | Arranca el servidor de producción (0.0.0.0:8000) |
| `make routes` | Muestra todas las rutas de la API registradas |
| `make test` | La suite del backend más la barrera del 100% sobre la capa de plataforma. Se ejecuta repartida entre procesos worker (`-n auto --maxprocesses 4`); `pytest-cov` combina sus datos, así que la barrera no cambia |
| `make test-cov` | Ejecuta los tests con informe de cobertura (HTML + terminal). Se reparte entre procesos worker igual que `make test` |
| `make format` | Formatea el código automáticamente: ruff en el backend, prettier en el frontend |
| `make lint` | Todas las comprobaciones estáticas: ruff, ruff format, ty, vulture, deptry, eslint, prettier, tsc, los scripts guardianes (backticks, i18n, rutas, comentarios de banner), la comprobación de dependencias de knip y codespell sobre todo el árbol |
| `make lint-backend` / `make lint-frontend` | Una mitad de lo anterior. CI los ejecuta en dos jobs distintos, así que cualquiera puede ejecutarse por su cuenta |
| `make dead-code` | Funciones y métodos sin usar: vulture con menos confianza que la barrera de `lint`, más el informe completo de knip sobre el frontend. Un informe para leer, no una barrera: en una base de código dirigida por registros viene con falsos positivos (un comando de la CLI, un hook de capability), así que lee cada uno antes de borrar. El mismo papel que `dependency-freshness` hace con las dependencias. Su única mitad inequívoca —un paquete en `package.json` que nadie importa— sí es barrera, en `lint-frontend` (`bun run lint:deps`), porque una dependencia que sobrevivió meses sin usarse es lo que lo motivó |
| `make lint-spelling` | codespell sobre cada archivo versionado. El hook de pre-commit lee solo los archivos que toca un commit, así que una falta que entra con su archivo espera ahí para rechazar el commit sin relación de otra persona |
| `make lint-precommit` | yamlfmt, zizmor y lo básico de `pre-commit-hooks` sobre cada archivo versionado. La misma razón que `lint-spelling`: esos hooks son por archivo, así que una subida de `rev:` que trae una regla nueva rompe el árbol sin que nada lo note. `SKIP` descarta los hooks que `lint-backend`/`lint-frontend`/`lint-spelling` ya cubren, así que ni duplica su tiempo ni deja que un corrector reescriba un archivo a mitad de comprobación |
| `make build-frontend` | `next build`. Comprueba los tipos del árbol de rutas y falla ante un server component que no puede renderizarse, cosa que ni tsc ni vitest ven |
| `make desktop-dev` / `make desktop-build` | Abre, o empaqueta, el envoltorio de escritorio: una ventana Tauri alrededor de una consola que nombras por su dirección. Necesita Rust y el webview de la plataforma; `docs/desktop.md` tiene el resto |
| `make desktop-check` | `bun test` sobre la mascota, luego rustfmt, clippy con los avisos denegados y los tests de Rust del envoltorio. No está en `lint` ni en `check`, porque CI todavía no tiene un toolchain de Rust |
| `make audit` | Audita el conjunto de dependencias bloqueadas en busca de vulnerabilidades conocidas. Necesita red —una petición por distribución bloqueada—, así que su última línea dice en cuál de cuatro estados terminó en lugar de dejar ambigua una ejecución en rojo. Ver más abajo |
| `make sandbox-token` | Genera el `SANDBOXD_TOKEN` propio del servicio de sandbox en `backend/.env`, una sola vez. `make dev` lo ejecuta por ti; nunca lo regenera, porque un token nuevo deja huérfano cada workspace que el servicio esté guardando. El formulario de conexión ofrece guardar ese mismo valor en el vault, así que no hay que pegarlo en ninguna parte |
| `make clean` | Borra los archivos de caché (__pycache__, .pytest_cache, etc.) |

### Antes de un pull request { #before-a-pull-request }

!!! success "`make check` es cada job de CI salvo `e2e`"

    La igualdad se mantiene en lugar de afirmarse, y
    `backend/tests/test_ci_parity.py` es lo que la sostiene. Ha divergido cuatro
    veces.

`.github/workflows/ci.yml` llama a esos mismos objetivos de Make en lugar de
repetir sus comandos, así que un job que hace de barrera y al que le crece un paso
que `check` no ejecuta falla el test de paridad, igual que al revés.

```bash
make check   # lint, test, db-check, test-frontend-cov, build-frontend, docs-build, audit
```

Unos cinco minutos, en serie, con la caché caliente. Lo que deja fuera
deliberadamente:

| No está en `check` | Por qué, y qué ejecutar en su lugar |
|---|---|
| `e2e` | Necesita una base de datos migrada, una organización sembrada y un backend en marcha: `make dev && make platform-bootstrap && make test-e2e` |
| La construcción de la imagen, su publicación y el escaneo de Trivy | `.github/workflows/images.yml` los ejecuta en un push a `main` y en una etiqueta `v*`, y publica en GHCR |
| `make test-migrations` | CI recorre la cadena contra una `test_db` desechable. En un portátil, `alembic downgrade base` apunta a lo que diga `backend/.env`, que suele ser la base de datos con tu propio trabajo dentro; `uv run pytest tests/test_migrations.py` hace la misma pregunta contra una base de datos propia, y `make test` ya lo ejecuta |

!!! warning "Un hueco que ningún comando puede cerrar"

    El job `test` de CI tiene un Postgres al lado, así que `tests/integration/` se
    ejecuta allí; en local se salta solo cuando nada responde en el 5432.
    `make check` lo dice al final cuando ocurre: ejecuta antes `make docker-db` si
    el cambio anda cerca de la base de datos.

### Qué significa un `make audit` en rojo { #what-a-red-make-audit-means }

`make audit` exporta lo que resuelve el lockfile —que es lo que instala un
despliegue— y se lo entrega a `pip-audit`, que pregunta al feed de
vulnerabilidades por cada una de las 254 distribuciones bloqueadas, una a una.
`pip-audit` por sí solo no puede decir cuál de dos cosas muy distintas salió mal:
sale con 1 tanto si encontró un aviso como si murió con un `ReadTimeout` al
buscar uno, y `Security Scan` es una comprobación obligatoria, así que una
respuesta lenta de 254 bloquea un merge leyéndose exactamente igual que un
hallazgo real hasta que alguien abre el log
([#855](https://github.com/vstorm-co/agenticos/issues/855)).

`scripts/audit_dependencies.py` se pone entre los dos y **termina cada ejecución
en una línea**:

```
AUDIT: CLEAN — no known advisories against 254 locked dependencies
AUDIT: VULNERABLE — 6 known advisories in 1 of 254 locked dependencies
AUDIT: NETWORK — unreachable (ReadTimeout) after 3 attempts; no audit was performed
AUDIT: FAILED — pip-audit reached no verdict in 3 attempts and did not say why; no audit was performed
```

| Estado | Significa | Qué hacer |
|---|---|---|
| `CLEAN` | Se auditó cada dependencia bloqueada, ninguna tiene un aviso conocido | Nada |
| `VULNERABLE` | Una dependencia bloqueada tiene un aviso conocido. Los ids, las versiones corregidas y los alias CVE se imprimen encima del veredicto | Actualízala |
| `NETWORK` | No hubo auditoría, y la causa fue reconociblemente la red | Vuelve a ejecutarlo |
| `FAILED` | No hubo auditoría, y la causa no se reconoció. La salida propia de pip-audit está en stderr | Lee esa salida |

**Una línea, no un código de salida, porque make no puede llevar uno.** GNU Make
convierte cualquier receta fallida en su propio exit 2, así que `make audit`
devuelve 2 tanto para `VULNERABLE` como para `NETWORK` y no hay forma de objetivo
que cambie eso. Lo que lea el resultado por esta interfaz —el job `Security Scan`
incluido— lee la línea: `make audit | tail -1`, o
`make audit 2>&1 | grep '^AUDIT:'`. Dentro de un job de GitHub esa misma línea se
añade a `$GITHUB_STEP_SUMMARY`, así que la página de resumen de la ejecución dice
en qué estado terminó sin que nadie abra el log.

Invocado directamente, `scripts/audit_dependencies.py` sí lo lleva: `0` para
`CLEAN`, `1` para `VULNERABLE`, `75` (`EX_TEMPFAIL`) para `NETWORK` y `FAILED` por
igual; una auditoría que no ocurrió nunca se informa en verde, porque un conjunto
de dependencias sin auditar al que se llama limpio es el mismo defecto visto del
otro lado.

**Cada ejecución incompleta se reintenta, dijera lo que dijera.**

`AUDIT_ATTEMPTS` (3 por defecto) con una espera de 5s/10s, y `AUDIT_TIMEOUT` (30s
por defecto) como tiempo de espera del socket por petición, subido desde los 15
propios de pip-audit.

Que una frase coincida en la salida decide solo si el veredicto dice `NETWORK` o
`FAILED`, nunca si volver a intentarlo. Los dos errores no son simétricos:
reejecutar un fallo determinista cuesta segundos y la misma respuesta, mientras
que *no* reejecutar uno transitorio es el falso rojo en una comprobación
obligatoria que esto existe para evitar.

Así que un fallo expresado con palabras que la lista no tiene recibe igualmente
sus reintentos. Solo recibe un nombre más vago.

En esa lista hay dos vocabularios, porque dos programas van a la red: `uv`, que
trae `pip-audit` con la caché de herramientas fría, y luego `pip-audit`, que trae
los avisos.

### Base de datos { #database }

| Comando | Descripción |
|---------|-------------|
| `make db-init` | Arranca PostgreSQL + crea la migración inicial + la aplica |
| `make db-migrate` | Crea una migración nueva (pide un mensaje) |
| `make db-upgrade` | Aplica las migraciones pendientes |
| `make db-check` | `alembic check`: falla si un cambio de modelo no tiene migración. No es destructivo (nunca hace downgrade), así que a diferencia de `test-migrations` sí se ejecuta dentro de `make check`; necesita una base de datos al día, y se salta en lugar de fallar cuando nada responde en el 5432. Las tablas `rag_<collection>` por colección del vector store quedan fuera de la comparación, ya que nada las modela ni las migra; `rag_documents`, que es una tabla con modelo, no |
| `make db-downgrade` | Revierte la última migración |
| `make db-current` | Muestra la revisión de migración actual |
| `make db-history` | Muestra el historial completo de migraciones |

### Usuarios { #users }

| Comando | Descripción |
|---------|-------------|
| `make create-admin` | Crea un usuario administrador (interactivo) |
| `make user-create` | Crea un usuario nuevo (interactivo) |
| `make user-list` | Lista todos los usuarios |

### Prefect { #prefect }

Prefect corre como dos contenedores en la pila de desarrollo; arrancan solos con `make dev`:

- **`prefect-server`** — la API de orquestación + la interfaz web en <http://localhost:4200>
- **`prefect-runner`** — registra los deployments programados y sondea si hay trabajo

El runner es `python -m app.worker.prefect_app`; los flows viven en `app/worker/tasks/`.
Abre la interfaz para ver las ejecuciones de los flows, inspeccionar logs y lanzar deployments a mano.
Autoalojado por defecto: fija `PREFECT_API_KEY` (y una `PREFECT_API_URL` de Cloud) para usar Prefect Cloud en su lugar.

### Docker (desarrollo) { #docker-development }

| Comando | Descripción |
|---------|-------------|
| `make docker-up` | Arranca todos los servicios del backend |
| `make docker-down` | Para todos los servicios |
| `make docker-logs` | Sigue los logs del backend |
| `make docker-build` | Construye las imágenes del backend |
| `make docker-shell` | Abre una shell en el contenedor de la app |
| `make docker-frontend` | Arranca la consola (tras el perfil `console` en un clonado) |
| `make docker-frontend-down` | Para el frontend |
| `make docker-frontend-logs` | Sigue los logs del frontend |
| `make docker-frontend-build` | Construye la imagen del frontend |
| `make docker-db` | Arranca solo PostgreSQL |
| `make docker-db-stop` | Para PostgreSQL |
| `make docker-redis` | Arranca solo Redis |
| `make docker-redis-stop` | Para Redis |

### Docker (producción con Traefik) { #docker-production-with-traefik }

| Comando | Descripción |
|---------|-------------|
| `make docker-prod` | Arranca la pila de producción |
| `make docker-prod-down` | Para la pila de producción |
| `make docker-prod-logs` | Sigue los logs de producción |

### Vercel (despliegue del frontend) { #vercel-frontend-deployment }

| Comando | Descripción |
|---------|-------------|
| `make vercel-deploy` | Despliega el frontend en Vercel |

---

## La CLI del proyecto { #project-cli }

Todos los comandos de la CLI del proyecto se invocan así:

```bash
cd backend
uv run agenticos <group> <command> [options]
```

### Comandos de servidor { #server-commands }

```bash
uv run agenticos server run              # Start dev server
uv run agenticos server run --reload     # With hot reload
uv run agenticos server run --port 9000  # Custom port
uv run agenticos server routes           # Show all registered routes
```

`--reload` ejecuta el recargador de uvicorn bajo un supervisor propio
(`backend/cli/reload_supervisor.py`), porque el de uvicorn es un vigilante de
archivos y nada más: cuando el kernel mata al worker —una muerte por falta de
memoria es la vía realista— ni lo recoge ni lo reemplaza, así que el recargador
sigue vigilando mientras ningún puerto escucha. Bajo el supervisor, un worker
matado por una señal se reemplaza en unos cinco segundos, y uno que salió por su
cuenta sigue esperando a la edición que lo arregle, que es para lo que está
`--reload`.

También reemplaza a un worker **atascado**: vivo, pero con un bucle de eventos que
ha dejado de girar, lo cual no tiene código de salida y por eso parece sano para
cualquier otra vía de recuperación.

El worker informa de su bucle a través del hook `callback_notify` de uvicorn una
vez por segundo, y un worker callado durante quince segundos en dos sondeos
consecutivos se mata y se reemplaza. Unos veinticinco segundos desde el deadlock
hasta volver a servir.

Dos sondeos y no uno, porque `docker pause` y un portátil que despierta de suspensión
paran al supervisor tanto como al worker, y el primer sondeo de después lee un latido
rancio que no dice nada.

Eso es **liveness y no readiness**, a propósito: el latido es una llamada de un
temporizador y no una petición, así que una base de datos lenta no puede hacer que
un servidor sano parezca atascado.

| | |
|---|---|
| `EVENT_LOOP_WEDGED_AFTER` | Segundos de silencio antes de reemplazar un worker. Por defecto `15`; `0` o menos apaga la comprobación |

Apágala mientras depuras. Un breakpoint bloquea el bucle de eventos y ninguna
sonda puede distinguir eso de un deadlock, así que un worker parado en uno se
reemplaza bajo tus pies.

La misma variable la lee el propio worker, que vigila su propio bucle de eventos y
mata su propio proceso: eso es lo que cubre las pilas de desarrollo y producción,
donde no hay un supervisor leyendo un latido desde fuera. Un solo número, así que
apagar la comprobación por un breakpoint apaga a los dos jueces.
[Configuración](configuration.md#a-worker-whose-event-loop-has-stopped-turning)
tiene el cuadro completo.

`server run` también selecciona la implementación `websockets-sansio` en ambos
modos. El `auto` de uvicorn elige la antigua, que falla el handshake contra
websockets >=14 con un HTTP 500, y el chat del dashboard es un WebSocket.


### Comandos de base de datos { #database-commands }

```bash
uv run agenticos db init                  # Run all migrations
uv run agenticos db migrate -m "message"  # Create new migration
uv run agenticos db upgrade               # Apply pending migrations
uv run agenticos db upgrade --revision e3f  # Upgrade to specific revision
uv run agenticos db downgrade             # Rollback last migration
uv run agenticos db downgrade --revision base  # Rollback to start
uv run agenticos db current               # Show current revision
uv run agenticos db history               # Show migration history
```

### Comandos de usuario { #user-commands }

```bash
# Create user (interactive prompts for email/password)
uv run agenticos user create

# Create user non-interactively
uv run agenticos user create --email user@example.com --password secret

# Also grant app-admin, which administers the whole deployment
uv run agenticos user create --email admin@example.com --password secret --superuser

# The same thing, as a shortcut
uv run agenticos user create-admin --email admin@example.com --password secret

# List all users
uv run agenticos user list
```

**No hay ningún `--role` ni ningún `set-role`.** La autoridad de un usuario dentro
de una organización es una fila de membresía más el [catálogo de
permisos](reference/permissions.md), concedido desde Users & Roles en la interfaz;
la columna `users.role` se eliminó antes de que se aplastara la cadena de
migraciones. El único privilegio que este grupo puede repartir es el global, y
`--superuser` es ese. Para concederlo o revocarlo después:

```bash
uv run agenticos cmd create-app-admin user@example.com
uv run agenticos cmd create-app-admin user@example.com --revoke
```

### Comandos personalizados { #custom-commands }

Los comandos personalizados se descubren solos desde `app/commands/`. Ejecútalos
así:

```bash
uv run agenticos cmd <command-name> [options]
```

`uv run agenticos cmd --help` lista todo lo que tiene el despliegue en marcha.

### Preparación y diagnóstico { #setup-and-diagnostics }

```bash
# An organization, an owner, a model profile and a published agent. Idempotent.
uv run agenticos cmd bootstrap \
    --email owner@example.com --password secret \
    --org "Acme" --provider anthropic --api-key sk-ant-...

# Without a key the agent is created but cannot run
uv run agenticos cmd bootstrap --org "Acme"

# Can this deployment actually run an agent? Database, vault, a usable model,
# and every registered sandbox connection - probed one by one, credential
# included, because `/healthz` is unauthenticated and answers for a service
# holding the wrong token.
uv run agenticos cmd doctor

# Find published agents that lend a skill their publisher could not reach. The
# publish-time check on skill_ids only guards new publishes; this is the offline
# half, naming versions frozen before it that still hand a private skill to a run.
# It sweeps every version a run can load, not only the current one: each named
# environment's pinned version, each version a non-terminal run (running, or parked
# awaiting approval) still reloads, and each delegate a spec pins - the last only as
# deep as max_depth lets a run reach, so a grandchild past the ceiling is not flagged.
# Report-only - a spec is exported into a client's own git, so unbinding is a person's
# call. Exits non-zero when it finds one, so a cron can gate on it.
uv run agenticos cmd audit-skill-bindings

# Re-wrap every stored secret under the current master key - the staged rotation
# docs/secrets.md describes. Configure the old and new key side by side in
# VAULT_MASTER_KEYS first; --dry-run fully unseals every stored envelope without
# writing, so failures surface before anything moves. Exits non-zero when any row
# could not move, so a script cannot drop the old key on a partial rotation.
uv run agenticos cmd vault-rotate --dry-run
uv run agenticos cmd vault-rotate

# Install the bundled skills (refund-policy, code-review, incident-report)
uv run agenticos cmd seed-skills
uv run agenticos cmd seed-skills --org <org-id> --dry-run

# Sample data for development
uv run agenticos cmd seed --count 10 --clear
```

### Invitar a un equipo, y sacar los enlaces { #inviting-a-team-and-getting-the-links-out }

```bash
# Invitations for several addresses at once, printed as `address  link`.
uv run agenticos cmd invite-members <org-id> ada@example.com grace@example.com

# One role for the batch; `member` unless you say otherwise.
uv run agenticos cmd invite-members <org-id> ada@example.com --role admin

# Whose authority they are created under. Defaults to the organization's first
# owner, and a role gate needs a role to weigh the offered one against.
uv run agenticos cmd invite-members <org-id> ada@example.com --as owner@example.com
```

Esto existe por las dos mitades de una invitación. **En un despliegue sin ningún
`SMTP_*` no se envía nada por correo**, y el token de aceptación se devuelve una
sola vez y no se guarda en ningún sitio al que llegue una segunda lectura, así que
el enlace hay que imprimirlo para poder pasarlo siquiera. El comando dice cuál de
las dos cosas ocurrió, y una dirección rechazada (ya es miembro, ya está invitada)
se informa y se salta en lugar de costarle el resto.

Pasa por el mismo servicio que la interfaz, así que el techo de rol, el límite de
plazas y las comprobaciones de duplicados se aplican exactamente igual que a
alguien que pulsa el botón, incluido que nadie reparte un rol que el suyo propio
no supere estrictamente.

`make platform-bootstrap BOOTSTRAP_API_KEY=sk-...` envuelve `bootstrap` con las
migraciones que necesita. Ejecuta antes `doctor` cuando algo funciona en local y
no en un entorno recién hecho: es más rápido que leer logs.

### Levantar un despliegue { #getting-a-deployment-up }

```bash
# Docker, one downloaded compose file, four questions, and a running agent.
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
# Only report what this machine is missing.
./scripts/quickstart.sh --check
# Print every command it would run, run none of them.
./scripts/quickstart.sh --dry-run
# Unattended.
./scripts/quickstart.sh --yes --provider anthropic --api-key sk-ant-... --org Acme
```

Es un envoltorio alrededor de `docker compose up` sobre las imágenes publicadas
(`make dev` en un clonado), `agenticos cmd bootstrap` y
`agenticos cmd mcp-registry-sync`: nada de lo que hace es inalcanzable a mano, y
Docker es lo único que necesita.

### El espejo del registro MCP { #the-mcp-registry-mirror }

```bash
# Fill or refresh `mcp_registry_servers` from the bundled snapshot.
uv run agenticos cmd mcp-registry-sync

# Or from the live registry, which is how the mirror moves between deploys.
uv run agenticos cmd mcp-registry-sync --fetch

# Keep rows the registry no longer lists, rather than pruning them.
uv run agenticos cmd mcp-registry-sync --no-prune
```

**`make platform-bootstrap` ya lo carga**, desde la instantánea incluida, así que
una preparación desde cero no necesita nada de esto. Se salta cuando la tabla ya
tiene filas: una reejecución de bootstrap no debe gastar segundos reescribiendo
cinco mil filas sin cambios, y refrescar el espejo es trabajo de este comando y no
de bootstrap.

Ejecútalo a mano en un despliegue anterior a la tabla, o para recoger una
instantánea más nueva. La sincronización es idempotente: una segunda ejecución
estampa `synced_at` y no cambia nada más, salvo que el registro sí lo hiciera.

La poda es lo que quita un servidor retirado de la lista. Sin ella el espejo solo
crece y un endpoint muerto queda ofrecible para siempre, así que está activada por
defecto y se guía por `synced_at` y no por un diff de cinco mil ids.

### Bots de canal { #channel-bots }

Mira [Canales](channels.md) para ver qué admite cada plataforma.

Cada comando de aquí actúa para **una organización**, porque un bot de canal
pertenece a una. `--org <id>` la nombra, y un despliegue con exactamente una
organización no necesita la opción. Uno con varias rechaza en lugar de elegir, y
las lista con sus ids: adivinar sería actuar sobre los bots de otra persona.

```bash
# Register a bot
uv run agenticos cmd channel-add-bot \
    --platform telegram --name "Support" --token <token> --mode jwt_linked

# Mattermost is self-hosted, so its bot carries its own server's address.
# --webhook-secret is the token Mattermost shows when the outgoing webhook is
# created; omit it to use the event stream and expose nothing.
uv run agenticos cmd channel-add-bot \
    --platform mattermost --name "Support" --token <token> \
    --api-base-url https://mattermost.acme.internal \
    --webhook-secret <token-from-mattermost>

uv run agenticos cmd channel-list-bots
uv run agenticos cmd channel-list-bots --platform telegram

# Send a test message through it - the cheapest proof the token and the
# address are right. --chat-id is a Telegram chat id or a Mattermost channel id.
uv run agenticos cmd channel-test-message --bot-id <uuid> --chat-id <chat> --text "ping"

# Webhook delivery, or delete the webhook to fall back to polling. Telegram is
# the only platform with an API for this; for Slack and Mattermost the command
# prints the URL to paste into their own settings.
uv run agenticos cmd channel-webhook-register --bot-id <uuid>
uv run agenticos cmd channel-webhook-delete --bot-id <uuid>
```

Registrar un bot desde la CLI es la única vía en un despliegue sin un navegador
apuntándole, que es lo que suele ser un servidor Mattermost detrás de una VPN.

Los modos de acceso son `open`, `whitelist`, `jwt_linked` y `group_only`;
`jwt_linked` solo responde a cuentas de chat vinculadas a un miembro, tanto en un
canal como en un mensaje directo. Una mención se ejecuta como el *remitente*,
nunca como el bot, y una identidad sin vincular se rechaza en lugar de ejecutarse
sin rol; mira
[Canales](channels.md#what-every-channel-shares).

### Comandos de RAG { #rag-commands }

Todos los comandos de RAG son comandos personalizados invocados con `cmd`:

#### Ingesta de documentos { #document-ingestion }

La colección por defecto es `default`. Un nombre cuya tabla vectorial ya declaran
los modelos —`documents`, que con prefijo es la tabla de seguimiento de la
ingesta— se rechaza con un 400 en lugar de aliarse con ella; mira
[Procesamiento de archivos](file-processing.md#vector-storage).

```bash
# Ingest a single file into the default collection
uv run agenticos cmd rag-ingest ./docs/guide.pdf

# Ingest a directory
uv run agenticos cmd rag-ingest ./docs/

# Ingest recursively into a specific collection
uv run agenticos cmd rag-ingest ./docs/ --collection knowledge --recursive

# Ingest with sync mode
uv run agenticos cmd rag-ingest ./docs/ --sync-mode new_only
uv run agenticos cmd rag-ingest ./docs/ --sync-mode update_only

# Skip replacing existing documents
uv run agenticos cmd rag-ingest ./docs/ --no-replace
```

#### Búsqueda { #search }

```bash
# Search the default collection
uv run agenticos cmd rag-search "what is fastapi"

# Search a specific collection
uv run agenticos cmd rag-search "deployment guide" --collection docs

# Get more results
uv run agenticos cmd rag-search "deployment" --top-k 10
```

#### Gestión de colecciones { #collection-management }

```bash
# List all collections with stats
uv run agenticos cmd rag-collections

# Show overall RAG system statistics
uv run agenticos cmd rag-stats

# Drop a collection (with confirmation)
uv run agenticos cmd rag-drop my_collection

# Drop without confirmation
uv run agenticos cmd rag-drop my_collection --yes
```

#### Sincronización con Google Drive { #google-drive-sync }

```bash
# Sync from Google Drive root
uv run agenticos cmd rag-sync-gdrive --collection docs

# Sync from a specific folder
uv run agenticos cmd rag-sync-gdrive --collection docs --folder-id abc123
```

#### Sincronización con S3/MinIO { #s3minio-sync }

```bash
# Sync from S3 bucket root
uv run agenticos cmd rag-sync-s3 --collection docs

# Sync from a specific prefix (folder)
uv run agenticos cmd rag-sync-s3 --collection docs --prefix documents/

# Sync from a specific bucket
uv run agenticos cmd rag-sync-s3 --collection docs --bucket my-bucket
```


#### Gestión de fuentes de sincronización { #sync-source-management }

```bash
# List configured sync sources
uv run agenticos cmd rag-sources

# Add a new sync source. `--org` is required and the collection has to be one
# that organization already holds: a sync *writes into* the collection it names,
# so a source pointing at a name nobody owns fails later in a worker, and one
# pointing at another tenant's is an injection rather than a read.
uv run agenticos cmd rag-source-add \
    --name "My Drive" \
    --type gdrive \
    --org 0c8f2b1e-... \
    --collection docs \
    --config '{"folder_id": "abc123"}' \
    --sync-mode new_only \
    --schedule 60

# Remove a sync source
uv run agenticos cmd rag-source-remove <source-id>
uv run agenticos cmd rag-source-remove <source-id> --yes  # Skip confirmation

# Trigger sync for a specific source
uv run agenticos cmd rag-source-sync <source-id>

# Trigger sync for all active sources
uv run agenticos cmd rag-source-sync --all
```

`rag-source-sync` **espera a las sincronizaciones que arranca**, hasta una hora, y
lo dice mientras lo hace. La sincronización en sí corre en una tarea de segundo
plano, y el proceso del comando termina cuando su corrutina vuelve, así que un
comando que solo disparaba y salía estaba cancelando el trabajo que acababa de
informar como iniciado. Por la API esa tarea pertenece a un worker de vida larga y
nada tiene que esperarla.

## Añadir comandos personalizados { #adding-custom-commands }

Los comandos se descubren solos desde `app/commands/`. Crea un archivo nuevo:

```python
# app/commands/my_command.py
import click
from app.commands import command, success, error

@command("my-command", help="Description of what this does")
@click.option("--name", "-n", required=True, help="Name parameter")
def my_command(name: str):
    """Your command logic here."""
    success(f"Done: {name}")
```

Ejecútalo:

```bash
uv run agenticos cmd my-command --name test
```

Para más detalles, mira `docs/adding_features.md`.
