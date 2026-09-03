# Deploy

This is what the repository ships for getting the platform onto a host: Docker and
`docker-compose.yml`, an Nginx config, and GitHub Actions.

There are no Kubernetes manifests.

!!! tip "Read [configuration](configuration.md#production-checklist) first"

    The production checklist is the list of settings whose generated defaults are
    fine on a laptop and are not fine on a host somebody else can reach.

## Docker Compose (single host)

For staging or small production:

```bash
# 1. Configure
cp backend/.env.example backend/.env
# Edit backend/.env with production values (see configuration.md)

# 2. Build + start
docker compose up -d --build

# 3. Apply migrations
docker compose exec app uv run alembic upgrade head

# 4. Verify
curl http://localhost:8000/api/v1/health
# Frontend: http://localhost:3000
```

### Reverse proxy

The Nginx config in `nginx/` proxies `/` → frontend, `/api` → backend, `/ws` →
backend WebSocket. Update `server_name` and the TLS certificate paths in
`nginx/conf.d/app.conf`.

!!! info "The security headers come from the backend, not from the proxy"

    A Content-Security-Policy, `X-Frame-Options: DENY`,
    `X-Content-Type-Options: nosniff`, `Referrer-Policy` and `Permissions-Policy`
    are set on every response, so a deployment behind *any* proxy is covered.
    Two edges: a 500 for an unhandled exception is built outside the middleware
    stack and stamps the same headers itself; and the interactive API docs
    (`/docs`, `/redoc`, `/api/v1/openapi.json`) drop the **CSP** only, because
    Swagger and ReDoc load assets a strict policy forbids — their framing and
    MIME protections stay.

    **HSTS is deliberately left to the proxy**, which is where TLS terminates. A
    front proxy setting its own CSP should be at least as strict as this one.

## Platform-specific quickstarts

=== "Fly.io"

    ```bash
    fly launch --name agenticos-backend --region waw
    fly postgres create --name agenticos-db
    fly postgres attach agenticos-db
    # Redis: use Upstash (`fly redis create`) or Fly's Tigris
    fly secrets set $(cat backend/.env | grep -v '^#' | xargs)
    fly deploy
    ```

=== "Railway"

    1. Connect the repo, pick Dockerfile-based deploy.
    2. Add env vars from `backend/.env` to the Railway service.
    3. Provision the PostgreSQL plugin → `DATABASE_URL` auto-injected.
    4. Provision the Redis plugin → `REDIS_URL` auto-injected.
    5. Deploy.

=== "Render"

    1. Create a Web Service → docker, pointed at `backend/Dockerfile`.
    2. Create a Static Site for the frontend (build command
       `bun install && bun run build`, output directory `.next`).
    3. Create PostgreSQL → copy `DATABASE_URL`.
    4. Add env vars; deploy.

=== "Vercel (frontend only)"

    The frontend is a Next.js app and works on Vercel out of the box.

    ```bash
    cd frontend
    vercel
    ```

    Set `BACKEND_URL` and `NEXT_PUBLIC_API_URL` in the Vercel dashboard, pointing
    at your backend host.

!!! warning "Whatever the platform, the database must be pgvector"

    The RAG store issues `CREATE EXTENSION IF NOT EXISTS vector` the first time a
    collection is written to, and stock Postgres answers
    `extension "vector" is not available`. A managed Postgres that cannot enable
    the extension cannot hold knowledge collections. See
    [install](install.md#the-database-must-be-pgvector).

## Environment validation in production

Before promoting to prod, run:

```bash
docker compose exec app uv run python -c "from app.core.config import settings; print('OK')"
```

That catches missing required env vars early. See [Configuration](configuration.md)
for the full list.

## Post-deploy checks

- [ ] `/api/v1/health` returns `{"status": "ok"}`
- [ ] `alembic current` matches the expected revision
- [ ] The frontend renders, and the login flow works end to end
- [ ] A test email sends (trigger the password-reset flow)
- [ ] Logs are flowing to your aggregator, and Logfire is receiving traces
- [ ] The reverse proxy enforces HTTPS

## Rollback

| | How |
|---|---|
| **Schema** | `alembic downgrade -1` rolls back one migration. Test on staging first |
| **Code** | Redeploy the previous image tag |
| **Data** | Restore from your most recent backup, then check `alembic current` matches the data's version |

!!! danger "Pin image tags; never deploy `latest` to production"

    A rollback is only a rollback if there is a specific tag to go back to.

## Recap

- **Compose on one host** is the shipped path. Configure, build, migrate, verify.
- The security headers come from the **backend**, so any proxy is covered — but
  HSTS is the proxy's, because that is where TLS terminates.
- Whatever the platform, the database must be **pgvector**.
- **Pin image tags.** A rollback is only a rollback if there is a tag to go back to.
