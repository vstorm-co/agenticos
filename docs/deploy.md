# Deploy to a server

One host, Docker Compose, a reverse proxy in front. That is the whole shipped
path, and it is what runs the deployments this project is used in.

There are no Kubernetes manifests, and no one-click quickstarts for the
platform-as-a-service providers. That is not modesty about scale. The stack is
six containers, two of which hold state, one of which can start containers of
its own, and one of which is a Postgres that must have pgvector - which is
already more than a `git push` deploy target models, and a guide that pretended
otherwise would be describing a deployment nobody has run.

!!! tip "Read the [production checklist](configuration.md#production-checklist) first"

    Nine settings ship with defaults that are fine on a laptop and wrong on a host
    somebody else can reach. `scripts/server-init.sh` below generates all nine, so
    the checklist is what you check afterwards rather than what you type.

## What you need

| | |
|---|---|
| **A host** | 4 vCPU and 8 GB of RAM runs it. See [sizing](#sizing-the-host) |
| **Docker** | Engine 24+ with the Compose plugin, and your user in the `docker` group |
| **Two hostnames** | one for the site, one for the API — see [why two](#why-two-hostnames) |
| **A reverse proxy** | [Traefik](#option-a-traefik) or [Nginx](#option-b-nginx). It terminates TLS |
| **An OpenRouter key** | every collection embeds through it. Chat models are configured per organization, in the product |

The host also needs ports 80 and 443 open, and nothing else. Postgres, Redis and
the Prefect API are published on no interface at all.

### Why two hostnames

The browser talks to both. Most calls go through the frontend's own server-side
routes, but the chat WebSocket connects to the API directly, so the API needs a
name a browser can resolve and a certificate of its own.

`app.example.com` and `api.example.com` is the shape. They can be any two names;
what they must not be is one name with a path prefix, because the API's cookies
and the site's are scoped to the host.

## Sizing the host

Measured on an idle deployment, not estimated:

| | at rest | ceiling |
|---|---|---|
| `app` (2 uvicorn workers) | ~1.0 GB | 2.5 GB at the default 4 workers |
| `db` | ~1.3 GB with the tuning below | 2 GB |
| `prefect-runner` | 241 MiB | 1.5 GB |
| `prefect-server` | 245 MiB | 768 MB |
| `frontend` | ~300 MB | 1 GB |
| `redis` | 9 MiB | 512 MB |

The number that decides the host is **`UVICORN_WORKERS`**. Each worker is a
separate process that imports the whole application — 460 MiB, spawned rather
than forked, so nothing is shared. Four of them are 1.9 GB before a request
arrives.

Two workers suit a team of ten and still leave one serving while
[the watchdog](configuration.md#a-worker-whose-event-loop-has-stopped-turning)
replaces a wedged sibling. One worker is the setting to avoid: a blocked event
loop is then the whole deployment, until it kills itself.

!!! note "The database is tuned against its own limit"

    `docker-compose-prod.yml` runs Postgres with `shared_buffers=512MB` against a
    2 GB limit, and gives it 512 MB of `/dev/shm` — Docker's default is 64 MB,
    which a parallel scan over a collection's vectors exhausts, reporting
    `could not resize shared memory segment`. Move the limit and move the tuning
    with it; they are written next to each other for that reason.

## Point the names at the host

Two A records, before anything else. Let's Encrypt proves you control a name by
fetching a file over HTTP from wherever it resolves, so a certificate is not
issued until this is true and propagated.

```
app.example.com   A   203.0.113.10
api.example.com   A   203.0.113.10
```

!!! warning "A wildcard does not do this for you"

    Where `*.example.com` already points somewhere — a marketing site, usually —
    both names resolve to it. A record for the specific name beats a wildcard, so
    the fix is to add the two above rather than to remove the wildcard.

Check from somewhere that is not the host, because the host may have its own
answer:

```bash
dig +short app.example.com api.example.com
```

## Get it onto the host

```bash
sudo install -d -o "$USER" -g "$USER" /opt/agenticos
git clone https://github.com/vstorm-co/agenticos.git /opt/agenticos
cd /opt/agenticos
bash scripts/server-init.sh
```

`server-init.sh` writes `backend/.env`: it generates the five secrets, asks for
the two hostnames, an address for Let's Encrypt and the OpenRouter key, and
derives the public URLs and the CORS origin from what you gave it. It refuses to
overwrite an existing file.

!!! danger "`backend/.env` holds the key that unwraps every stored credential"

    `VAULT_MASTER_KEY` is what makes an organization's provider keys, bot tokens
    and MCP credentials readable. Losing it does not lock you out of the product;
    it makes every secret in it unrecoverable. Back the file up somewhere a lost
    disk cannot take with it, and rotate with
    [`agenticos cmd vault-rotate`](secrets.md#operations) rather than by editing.

Two optional things it does not ask about, both in that file: `SMTP_*`, without
which invitations and password resets cannot be sent, and `LOGFIRE_TOKEN`, which
is where traces of agent runs go.

## Choose a reverse proxy

Something has to terminate TLS and route the two names. Both options below reach
the same containers; pick on whether you already run one.

### Option A: Traefik

The shorter path, and the one to pick on a host that already has Traefik: the
containers carry labels, Traefik discovers them, asks for the certificate and
renews it. Nothing to reload and no second config file to keep in step.

If Traefik is not there yet, the repository ships one: `traefik/traefik.yml` and
`docker-compose-traefik.yml`, which is an entrypoint on 443 with a Let's Encrypt
resolver and 80 redirecting to it.

```bash
docker network create traefik_webgateway
docker compose --env-file backend/.env -f docker-compose-traefik.yml up -d
```

Where Traefik is **already** running, leave those alone and point
`TRAEFIK_NETWORK` at the network it watches. The overlays read that name, so
nothing about the existing proxy has to change.

Then bring the stack up with `PROXY=traefik`, which adds the two overlay files
that carry the labels:

```bash
make prod PROXY=traefik
make prod-frontend PROXY=traefik
```

`server-init.sh` has already written `PROXY=traefik` into `backend/.env`, which is
where `scripts/deploy.sh` reads it from — so later deploys keep the proxy this
host was set up with rather than the one a script assumed.

!!! info "`exposedByDefault: false` is doing real work"

    It is the one setting in `traefik/traefik.yml` worth reading before you run
    it. Only `app` and `frontend` carry `traefik.enable=true`, so Postgres, Redis,
    the Prefect server and the sandbox daemon are reachable from nothing outside
    the host — and that is a property of *not being labelled*, so it survives
    somebody adding a service without thinking about the proxy.

### Option B: Nginx

For a host where Nginx already terminates TLS, or where the proxy is not in
Docker at all. The stack publishes both ports on `127.0.0.1` and Nginx reaches
them there:

```bash
make prod
make prod-frontend
```

`nginx/nginx.conf` is the template. Two substitutions before it serves anything:
the `server_name` in each block is `${DOMAIN:-localhost}`, and Nginx does not
expand that — put the two hostnames in by hand. Certificates are yours to obtain
and renew, and so is the `Strict-Transport-Security` header, which the backend
deliberately leaves to whatever terminates TLS.

!!! warning "`BIND_HOST` is a security setting, not a convenience"

    The loopback default is what makes the auth rate limit mean anything.
    `RATE_LIMIT_TRUST_FORWARDED_FOR` tells the API to count an attempt against
    the address the proxy forwards, so whatever can reach the API *past* the
    proxy chooses the address its attempts are counted against. Set
    `BIND_HOST=0.0.0.0` only for a proxy on a different machine, and firewall the
    port to it.

!!! warning "The frontend is a compose project of its own"

    Compose names a project after the directory, so both stacks were
    `agenticos` — and bringing the frontend up then reported the five backend
    containers as **orphans**, with compose's own suggestion to run the command
    again with `--remove-orphans`. Taking that advice stops the API, the
    database, Redis and both Prefect services. The `make` targets and
    `scripts/deploy.sh` pass `-p agenticos-frontend`, so the warning is gone; a
    deployment that predates this fix needs its frontend container removed once
    (`docker rm -f agenticos_frontend`) before the renamed project can create it.

## Start it, and create the first account

`make prod` builds the images, starts the stack and runs the migrations. The
first build takes a few minutes; afterwards Docker's layer cache makes it about
a minute.

Then create an organization, an owner and a working agent:

```bash
docker compose --env-file backend/.env -f docker-compose-prod.yml \
  exec -T app agenticos cmd bootstrap \
  --email you@example.com --password 'a real password' \
  --org 'Your Company' --provider anthropic --api-key sk-ant-...
```

The provider key here is what the demo agent runs on. Without it the agent is
created and cannot answer; every other provider is added in the product, per
organization, from the vault.

!!! tip "Check it from outside, not from the host"

    ```bash
    curl -fsS https://api.example.com/api/v1/health
    curl -fsSo /dev/null -w '%{http_code}\n' https://app.example.com
    ```

    A stack that is healthy on the host and unreachable from the internet is DNS,
    the firewall or the certificate — three things a health check inside the host
    cannot see.

Then, once, by hand: sign in, invite somebody (which proves `SMTP_*`), and send
the demo agent a message (which proves the provider key and the WebSocket). Each
exercises a path nothing else here checks.

!!! info "The security headers come from the backend, so any proxy is covered"

    A Content-Security-Policy, `X-Frame-Options: DENY`,
    `X-Content-Type-Options: nosniff`, `Referrer-Policy` and `Permissions-Policy`
    are set on every response — including the 500 for an unhandled exception,
    which is built outside the middleware stack and stamps them itself. The
    interactive API docs drop the CSP only, because Swagger loads assets a strict
    policy forbids.

    **HSTS is deliberately left to the proxy**, which is where TLS terminates. A
    proxy that sets its own CSP should be at least as strict as this one.

## Deploying a change

### By hand

```bash
remote=$(ssh you@your-host 'mktemp -t agenticos-deploy.XXXXXX')
ssh you@your-host "cat > $remote" < scripts/deploy.sh
ssh you@your-host "trap 'rm -f $remote' EXIT; bash $remote <commit-sha>"
```

`scripts/deploy.sh` fetches that commit, rebuilds, migrates, restarts and waits
for both containers to report healthy before it returns non-zero or not. It takes
a **commit** rather than a branch, so what is deployed is what was reviewed, not
whatever `main` has moved to since.

!!! warning "Copy it to the host, then run it — do not pipe it into `bash -s`"

    Under `bash -s` the script is the shell's own standard input, and the first
    command in it that reads stdin consumes the rest. `docker compose exec`
    forwards stdin to the container even with `-T`, so the migration ate
    everything below itself, bash reached EOF, and the deploy exited **0**
    having never built the frontend or waited for any container. The site was
    down and the deploy was green ([#1488](https://github.com/vstorm-co/agenticos/issues/1488)).

    Two connections instead of one is what stops the procedure being able to
    truncate itself.

It is not zero-downtime. Compose recreates the containers it rebuilt, so the site
is unavailable for the few seconds that takes.

### From GitHub, with an approval

`.github/workflows/deploy.yml` offers every merge to `main` for deployment and
waits for somebody to approve it. That gate is **a repository setting, not a step
in the file** — without it, the workflow deploys every merge unattended.

Set it up once:

1. **Settings → Environments → New environment**, named `production`.
2. Tick **Required reviewers** and add whoever may approve. This is the gate.
3. Add the environment's variables: `SITE_URL`, `API_URL`, and `APP_DIR` if the
   checkout is not at `/opt/agenticos`.
4. Add the secrets below.

| Secret | What |
|---|---|
| `DEPLOY_HOST` | The host's address |
| `DEPLOY_USER` | The account the checkout belongs to |
| `DEPLOY_SSH_KEY` | A private key whose public half is in that account's `authorized_keys` |
| `DEPLOY_KNOWN_HOSTS` | `ssh-keyscan your-host`, run from somewhere you trust |

Generate the key for this and nothing else:

```bash
ssh-keygen -t ed25519 -N '' -C 'github-actions-deploy' -f deploy_key
ssh-copy-id -f -i deploy_key.pub you@your-host
ssh-keyscan your-host                    # → DEPLOY_KNOWN_HOSTS
cat deploy_key                           # → DEPLOY_SSH_KEY, then delete it locally
```

!!! note "The host key is a secret rather than a `ssh-keyscan` at deploy time"

    Scanning at deploy time trusts whatever answers on that address, which is the
    thing a host key exists to prevent. Scan once, from somewhere you trust, and
    store the answer.

A run then appears with **Review deployments**; approving it starts the job.
`workflow_dispatch` runs the same job against a ref you name, which is how a
rollback is done, and it passes through the same approval.

## Backups

One volume matters, and it is not obvious which:

| Volume | Holds | Backup |
|---|---|---|
| `postgres_data` | everything — agents, conversations, sealed credentials | **yes** |
| `media_data` | uploaded files, before ingestion | yes |
| `redis_data` | rate-limit buckets and caches | no, all rebuildable |
| `prefect_data` | the flow-run history | no |

```bash
docker compose --env-file backend/.env -f docker-compose-prod.yml exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "agenticos-$(date +%F).dump"
```

The identifiers come from the container's own environment rather than being
written out, because both are settings: a deployment that changed either would
otherwise get an empty file and an error nobody reads on the way past.

!!! danger "A database backup without `backend/.env` is not a backup"

    The credentials in it are sealed with `VAULT_MASTER_KEY`. Restored next to a
    different key, every provider key, bot token and MCP credential in the dump is
    unreadable — and the product will tell you so one refusal at a time.

## Rolling back

| | How |
|---|---|
| **Code** | Deploy the previous commit: `workflow_dispatch` with its sha, or `scripts/deploy.sh` |
| **Schema** | `agenticos db downgrade --revision=-1`, then deploy the code that matches |
| **Data** | `pg_restore` the dump, then check the migration the code expects |

Rolling code back **across a migration is a decision, not a command**. The old
code meets a schema it has never seen; whether that works depends on the
migration. Read it before assuming.

## Recap

- **One host, Compose, a proxy in front.** Six containers, two of them stateful.
- **`UVICORN_WORKERS` decides what the host costs.** 460 MiB per worker, nothing
  shared. Two for a team, four for real traffic.
- **DNS before everything.** No certificate is issued until the names resolve to
  the host.
- **The approval is a repository setting**, not a line in the workflow. Without
  required reviewers on the `production` environment, every merge deploys itself.
- **Back up `postgres_data` and `backend/.env` together.** Either without the
  other is not a restore.
