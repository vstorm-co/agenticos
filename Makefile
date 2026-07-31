.PHONY: install format lint test run clean help deps-upgrade deps-upgrade-all db-init dev dev-down dev-logs dev-rebuild dev-frontend docker-clean dev-server dev-server-down dev-server-logs dev-server-frontend stage stage-down prod prod-down prod-frontend upgrade upgrade-dry-run upgrade-new-features upgrade-finalize docs docs-build

# === Environments ===========================================================
# Three, one compose file each, with a matching frontend file beside it:
#
#   make dev         local, on a laptop    docker-compose.yml
#                                          docker-compose.frontend.yml
#   make dev-server  the dev server        docker-compose-dev.yml
#                                          docker-compose-dev.frontend.yml
#   make prod        production            docker-compose-prod.yml
#                                          docker-compose-prod.frontend.yml
#
# Local bind-mounts the source and reloads. The other two build images, publish
# no database port, and want a reverse proxy in front (nginx/nginx.conf).
# Each has matching -down / -logs / -frontend siblings.

# Wait for postgres to accept connections. Polls pg_isready instead of a
# fixed sleep — handles slow startups and cold-start image pulls.
define _wait_for_db
	@echo "Waiting for PostgreSQL ($(1))..."
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
		if docker compose -f $(1) exec -T db pg_isready -U postgres >/dev/null 2>&1; then \
			echo "  ✅ DB ready"; exit 0; \
		fi; \
		printf '.'; sleep 2; \
	done; \
	echo "  ❌ DB not ready after 30s — check 'make dev-logs'"; exit 1
endef

# === Local dev: build → up → migrate ===
# Idempotent — re-run anytime. Migrations are no-ops when already at head;
# admin seeding is a separate target (`make seed`) so re-running `make dev`
# doesn't keep retrying user creation.
dev:
	@echo "▶ Building backend image…"
	docker compose -f docker-compose.yml build app
	@echo "▶ Starting services…"
	@if ! docker compose -f docker-compose.yml $(COMPOSE_DEV_PROFILES) up -d; then \
		echo ""; \
		echo "⚠ First start failed. Tearing down stale containers and retrying once…"; \
		echo "  (volumes preserved — DB data is safe; use 'make clean' for a full wipe)"; \
		docker compose -f docker-compose.yml down --remove-orphans; \
		docker compose -f docker-compose.yml $(COMPOSE_DEV_PROFILES) up -d; \
	fi
	$(call _wait_for_db,docker-compose.yml)
	@echo "▶ Applying migrations…"
	docker compose -f docker-compose.yml exec -T app agenticos db upgrade
	@echo ""
	@echo "🚀 Dev stack ready:"
	@echo "   API:      http://localhost:8000"
	@echo "   Docs:     http://localhost:8000/docs"
	@echo "   Admin:    http://localhost:8000/admin"
	@echo "   Frontend: http://localhost:3000  (run 'make dev-frontend' or 'cd frontend && bun dev')"
	@echo ""
	@echo "First time? Run 'make seed' to create the default admin user."

# === First-time setup: seed default admin user (one-shot) ===
# Skipped when admin@example.com already exists. Safe to run again — exits
# clean either way. Replace email/password before deploying anywhere real.
seed:
	@echo "▶ Seeding admin user (admin@example.com / admin123)…"
	@if docker compose -f docker-compose.yml exec -T app \
		agenticos user list 2>/dev/null \
		| grep -q "admin@example.com"; then \
		echo "  (admin@example.com already exists — nothing to do)"; \
	else \
		docker compose -f docker-compose.yml exec -T app \
			agenticos user create \
				--email admin@example.com --password admin123 --superuser \
		&& echo "  ✅ Admin created. Login at http://localhost:8000/admin"; \
	fi

# Convenience: bootstrap a fresh checkout end-to-end.
# Fresh install -> a running agent. Idempotent: safe to re-run.
# Pass a key to make the demo agent actually answerable:
#   make platform-bootstrap BOOTSTRAP_API_KEY=sk-...
platform-bootstrap:
	docker compose -f docker-compose.yml exec -T \
		-e BOOTSTRAP_API_KEY=$(BOOTSTRAP_API_KEY) app \
		agenticos cmd bootstrap

bootstrap: dev seed

dev-down:
	docker compose -f docker-compose.yml $(COMPOSE_DEV_PROFILES) down

# Full wipe — containers, networks, AND volumes. Use after a corrupted state
# (e.g. detached networks, port conflicts that left orphans). DESTROYS DB data.
docker-clean:
	@echo "▶ Removing containers, networks, AND volumes for the dev stack…"
	@echo "  ⚠️  This deletes all local DB data and uploaded files."
	docker compose -f docker-compose.yml $(COMPOSE_DEV_PROFILES) down -v --remove-orphans
	@echo "✅ Cleaned. Run 'make dev' to start fresh."

dev-logs:
	docker compose -f docker-compose.yml $(COMPOSE_DEV_PROFILES) logs -f

dev-rebuild:
	docker compose -f docker-compose.yml build --no-cache app
	docker compose -f docker-compose.yml up -d --force-recreate app
dev-frontend:
	docker compose -f docker-compose.frontend.yml up -d
	@echo ""
	@echo "✅ Frontend at http://localhost:3000  (backend must be up — 'make dev')"

# === Dev server: a deployed environment, built images, no bind mounts ===
# Not a laptop. Needs backend/.env with POSTGRES_PASSWORD and REDIS_PASSWORD;
# neither has a default here, because a shared environment reachable with
# `postgres/postgres` is not one you want.
dev-server:
	@test -f backend/.env || (echo "❌ backend/.env missing — cp backend/.env.example backend/.env and fill it in" && exit 1)
	docker compose --env-file backend/.env -f docker-compose-dev.yml up -d --build
	$(call _wait_for_db,docker-compose-dev.yml)
	docker compose --env-file backend/.env -f docker-compose-dev.yml exec -T app agenticos db upgrade
	@echo "✅ Dev-server stack up on :8000 — put a reverse proxy in front of it"

dev-server-frontend:
	@test -f backend/.env || (echo "❌ backend/.env missing" && exit 1)
	docker compose --env-file backend/.env -f docker-compose-dev.frontend.yml up -d --build
	@echo "✅ Dev-server frontend on :3000 (PUBLIC_* vars are baked in at build time)"

dev-server-down:
	docker compose --env-file backend/.env -f docker-compose-dev.yml down
	docker compose --env-file backend/.env -f docker-compose-dev.frontend.yml down 2>/dev/null || true

dev-server-logs:
	docker compose --env-file backend/.env -f docker-compose-dev.yml logs -f

# `make stage` was this file's old name for the dev server. Kept so an existing
# habit or script does not silently do nothing.
stage: dev-server
stage-down: dev-server-down

# === Production: external Nginx, real secrets in backend/.env ===
prod:
	@test -f backend/.env || (echo "❌ backend/.env missing — run 'cp backend/.env.example backend/.env' and fill in real secrets" && exit 1)
	docker compose --env-file backend/.env -f docker-compose-prod.yml up -d --build
	@echo "▶ Waiting for DB then running migrations…"
	@sleep 5
	docker compose --env-file backend/.env -f docker-compose-prod.yml exec -T app agenticos db upgrade
	@echo "✅ Production stack up. Configure your nginx host with nginx/nginx.conf"

prod-frontend:
	@test -f backend/.env || (echo "❌ backend/.env missing" && exit 1)
	docker compose --env-file backend/.env -f docker-compose-prod.frontend.yml up -d --build
	@echo "✅ Production frontend on :3000"

prod-down:
	docker compose --env-file backend/.env -f docker-compose-prod.frontend.yml down 2>/dev/null || true
	docker compose --env-file backend/.env -f docker-compose-prod.yml down

prod-logs:
	docker compose --env-file backend/.env -f docker-compose-prod.yml logs -f

# Legacy alias
quickstart: dev

# === Setup ===
install:
	uv sync --directory backend --dev
	@if git rev-parse --git-dir > /dev/null 2>&1; then \
		uv run --project backend pre-commit install; \
	else \
		echo "⚠️  Not a git repository - skipping pre-commit install"; \
		echo "   Run 'git init && make install' to set up pre-commit hooks"; \
	fi
	@echo ""
	@echo "✅ Installation complete!"
	@echo ""
	@echo "Next steps:"
	@echo "  • make docker-db        # Start PostgreSQL"
	@echo "  • make db-upgrade       # Apply migrations"
	@echo "  • make run              # Start development server"
	@echo ""
	@echo "Note: backend/.env is pre-configured for development"

# === Template upgrade — removed ===
# `.fastapi-fullstack.json` held the generator state these targets merged
# against: template ref, commit and the context hash. It is deleted, so the
# 3-way merge has no base and `uvx fastapi-fullstack upgrade` cannot run.
#
# That is deliberate. This codebase has diverged from the template far past the
# point where a merge helps — the agent runtime, the permission catalog, the
# vault and the capability registry have no counterpart upstream, and a 3-way
# merge against a generator that knows none of them produces conflicts in every
# file worth keeping. Cherry-pick from the template repository by hand instead.
#
# The targets are kept as errors rather than deleted so `make upgrade` explains
# itself instead of answering "No rule to make target".
upgrade upgrade-dry-run upgrade-new-features upgrade-finalize:
	@echo "❌ Template upgrades were removed with .fastapi-fullstack.json."
	@echo "   This project has diverged from the generator; cherry-pick from"
	@echo "   github.com/vstorm-co/full-stack-ai-agent-template by hand."
	@exit 1

# === Dependencies ===
# FastAPI, Pydantic AI, Logfire and genai-prices are uncapped and meant to track
# their newest release. This is the local half of that: bump them, then run the
# suite, because the upgrade is only done when it still passes. The
# `framework-freshness` workflow does the same on a schedule and opens an issue.
FRAMEWORKS := fastapi pydantic-ai-slim pydantic-ai-skills logfire genai-prices

deps-upgrade:
	uv lock --directory backend $(foreach p,$(FRAMEWORKS),--upgrade-package $(p))
	uv sync --directory backend --dev
	@uv run --directory backend python -c "import fastapi, logfire, genai_prices, pydantic_ai; \
		print(f'fastapi {fastapi.__version__} | logfire {logfire.__version__} | pydantic-ai {pydantic_ai.__version__}')"
	@echo "▶ Now run 'make test' — an upgrade that breaks the suite is not done."

# Everything, not just the four. Use before a release; expect more fallout.
deps-upgrade-all:
	uv lock --directory backend --upgrade
	uv sync --directory backend --dev
	cd frontend && bun update
	@echo "▶ Now run 'make check'."

# === Code Quality ===
format:
	uv run --directory backend ruff format app tests cli
	uv run --directory backend ruff check app tests cli --fix

lint:
	uv run --directory backend ruff check app tests cli
	uv run --directory backend ruff format app tests cli --check
	uv run --directory backend ty check
	python3 scripts/check_backticks.py

# === Testing ===
# `test` is the gate: it fails if platform-layer coverage drops below 100%.
test:
	uv run --directory backend pytest tests/ -v --cov --cov-report=term-missing

# Fast loop while writing code — no coverage, no gate.
test-fast:
	uv run --directory backend pytest tests/ -q --no-cov

# Integration tests only. These talk to a real database; start it with `make docker-db`.
test-integration:
	uv run --directory backend pytest tests/integration -v --no-cov

test-cov:
	uv run --directory backend pytest tests/ --cov --cov-report=html --cov-report=term-missing
	@echo "Open backend/htmlcov/index.html"

# Everything, including template-inherited subsystems. Informational: those are
# not held to the platform bar, because mock-heavy tests over code we did not
# design buy a number rather than confidence.
coverage-all:
	uv run --directory backend pytest tests/ -q --cov=app --cov-report=term-missing --cov-fail-under=0

test-frontend:
	cd frontend && bun run test:run

test-frontend-cov:
	cd frontend && bun run test:coverage

# Playwright starts the frontend itself; the backend and its seed are on you.
# Checked rather than assumed: against a backend that is not there the suite
# fails in fifty places at once, none of which say what is actually wrong.
E2E_BACKEND ?= http://localhost:8000

test-e2e:
	@if ! curl -sf $(E2E_BACKEND)/api/v1/health > /dev/null; then \
		echo "No backend at $(E2E_BACKEND)."; \
		echo "  make dev && make platform-bootstrap"; \
		exit 1; \
	fi
	cd frontend && bun run test:e2e

# What CI runs. Run this before opening a pull request.
check: lint test test-frontend
	@echo "All checks passed."

# === Documentation ===

# The docs site, live-reloading on <http://localhost:8001>. Port 8001 because
# 8000 is the API and serving docs there would shadow it. Override with
# `make docs DOCS_PORT=8002` when something else already holds the port -
# mkdocs answers a taken port with a bare OSError traceback.
DOCS_PORT ?= 8001

docs:
	uv run --directory backend --group docs mkdocs serve -f ../mkdocs.yml -a localhost:$(DOCS_PORT)

# Build the site, and fail on anything mkdocs only warns about - a dead internal
# link or a page missing from the nav. Both are things a reader finds and a build
# would otherwise ship.
docs-build:
	uv run --directory backend --group docs mkdocs build -f ../mkdocs.yml --strict

# Migrations against a real database, forwards and back. The only way to know a
# backfill or a check constraint actually works.
test-migrations:
	uv run --directory backend alembic upgrade head
	uv run --directory backend alembic downgrade base
	uv run --directory backend alembic upgrade head
	@echo "Migration chain applies and rolls back cleanly."


# === Database ===
db-init: docker-db
	@echo "Waiting for PostgreSQL to be ready..."
	@sleep 8
	cd backend && uv run agenticos db migrate -m "initial" || true
	cd backend && uv run agenticos db upgrade
	@echo ""
	@echo "✅ Database initialized!"

db-migrate:
	@read -p "Migration message: " msg; \
	uv run --directory backend agenticos db migrate -m "$$msg"

db-upgrade:
	uv run --directory backend agenticos db upgrade

db-downgrade:
	uv run --directory backend agenticos db downgrade

db-current:
	uv run --directory backend agenticos db current

db-history:
	uv run --directory backend agenticos db history

# === Server ===
run:
	uv run --directory backend agenticos server run --reload

run-prod:
	uv run --directory backend agenticos server run --host 0.0.0.0 --port 8000

routes:
	uv run --directory backend agenticos server routes

# === Users ===
create-admin:
	@echo "Creating admin user..."
	uv run --directory backend agenticos user create-admin

user-create:
	uv run --directory backend agenticos user create

user-list:
	uv run --directory backend agenticos user list

# === Docker: Backend (Development) ===
docker-up:
	docker compose build app
	docker compose up -d
	@echo ""
	@echo "✅ Backend services started!"
	@echo "   API: http://localhost:8000"
	@echo "   Docs: http://localhost:8000/docs"
	@echo "   PostgreSQL: localhost:5432"
	@echo "   Redis: localhost:6379"

docker-down:
	docker compose down
	docker compose -f docker-compose.frontend.yml down 2>/dev/null || true

docker-logs:
	docker compose logs -f

docker-build:
	docker compose build

docker-shell:
	docker compose exec app /bin/bash

# === Docker: Frontend (Development) ===
docker-frontend:
	docker compose -f docker-compose.frontend.yml up -d
	@echo ""
	@echo "✅ Frontend started!"
	@echo "   URL: http://localhost:3000"
	@echo ""
	@echo "Note: Backend must be running (make docker-up)"

docker-frontend-down:
	docker compose -f docker-compose.frontend.yml down

docker-frontend-logs:
	docker compose -f docker-compose.frontend.yml logs -f

docker-frontend-build:
	docker compose -f docker-compose.frontend.yml build

# === Docker: Production (with Traefik) ===
docker-prod:
	docker compose -f docker-compose-prod.yml up -d
	@echo ""
	@echo "✅ Production services started with Traefik!"
	@echo ""
	@echo "Endpoints (replace DOMAIN with your domain):"
	@echo "   Frontend: https://$$DOMAIN"
	@echo "   API: https://api.$$DOMAIN"
	@echo "   Traefik: https://traefik.$$DOMAIN"

docker-prod-down:
	docker compose -f docker-compose-prod.yml down

docker-prod-logs:
	docker compose -f docker-compose-prod.yml logs -f

docker-prod-build:
	docker compose -f docker-compose-prod.yml build


# === Docker: Individual Services ===
docker-db:
	docker compose up -d db
	@echo ""
	@echo "✅ PostgreSQL started on port 5432"
	@echo "   Connection: postgresql://postgres:postgres@localhost:5432/agenticos"

docker-db-stop:
	docker compose stop db

docker-redis:
	docker compose up -d redis
	@echo ""
	@echo "✅ Redis started on port 6379"

docker-redis-stop:
	docker compose stop redis

# === Vercel (Frontend Deployment) ===
vercel-deploy:
	cd frontend && npx vercel --prod
	@echo ""
	@echo "✅ Frontend deployed to Vercel!"
	@echo "   Set these in the Vercel dashboard. Every NEXT_PUBLIC_* is a BUILD"
	@echo "   variable: set it at runtime only and the browser bundle keeps"
	@echo "   whatever was baked in, while server rendering carries on working."
	@echo "   BACKEND_URL=https://api.your-domain.com"
	@echo "   NEXT_PUBLIC_API_URL=https://api.your-domain.com"
	@echo "   NEXT_PUBLIC_WS_URL=wss://api.your-domain.com"
	@echo "   NEXT_PUBLIC_SITE_URL=https://app.your-domain.com"
	@echo "   NEXT_PUBLIC_MAX_UPLOAD_SIZE_MB=50"
	@echo "   NEXT_PUBLIC_OAUTH_PROVIDERS=google"
	@echo "   NEXT_PUBLIC_RAG_ENABLED=true"

# === Cleanup ===
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ty_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ .coverage coverage.xml

# === Help ===
help:
	@echo ""
	@echo "agenticos - Available Commands"
	@echo "======================================"
	@echo ""
	@echo "🚀 Bootstrap (first-time setup):"
	@echo "  make bootstrap      'make dev' + 'make seed' — full setup from a fresh clone"
	@echo ""
	@echo "Day-to-day dev:"
	@echo "  make dev            Build + start dev stack + apply migrations (idempotent)"
	@echo "  make seed           One-shot admin seed (admin@example.com / admin123)"
	@echo "  make dev-down       Stop dev stack"
	@echo "  make dev-logs       Tail dev container logs"
	@echo "  make dev-rebuild    Force-rebuild backend image"
	@echo "  make docker-clean   Wipe containers + networks + volumes (DESTROYS data)"
	@echo "  make dev-frontend   Start frontend container (after 'make dev')"
	@echo ""
	@echo "📦 Other environments:"
	@echo "  make stage          Production-like stack on localhost (no bind mounts)"
	@echo "  make prod           Production stack (requires backend/.env + nginx)"
	@echo ""
	@echo "Setup (without Docker):"
	@echo "  make install       Install Python deps + pre-commit hooks"
	@echo ""
	@echo "Development:"
	@echo "  make run           Start dev server (with hot reload)"
	@echo "  make test          Run tests"
	@echo "  make lint          Check code quality"
	@echo "  make format        Auto-format code"
	@echo ""
	@echo "Database:"
	@echo "  make db-init       Initialize database (start + migrate)"
	@echo "  make db-migrate    Create new migration"
	@echo "  make db-upgrade    Apply migrations"
	@echo "  make db-downgrade  Rollback last migration"
	@echo "  make db-current    Show current migration"
	@echo ""
	@echo "Users:"
	@echo "  make create-admin  Create admin user (for SQLAdmin access)"
	@echo "  make user-create   Create new user (interactive)"
	@echo "  make user-list     List all users"
	@echo ""
	@echo "RAG:"
	@echo "  uv run agenticos rag-ingest <path> -c <collection>  Ingest files"
	@echo "  uv run agenticos rag-search <query> -c <collection>  Search"
	@echo "  uv run agenticos rag-collections                     List collections"
	@echo "  uv run agenticos rag-sources                         List sync sources"
	@echo "  uv run agenticos rag-source-add                      Add sync source"
	@echo "  uv run agenticos rag-source-sync <id>                Trigger sync"
	@echo ""
	@echo "Docker (Development):"
	@echo "  make docker-up            Start backend services"
	@echo "  make docker-down          Stop all services"
	@echo "  make docker-logs          View backend logs"
	@echo "  make docker-build         Build backend images"
	@echo "  make docker-frontend      Start frontend (separate)"
	@echo "  make docker-frontend-down Stop frontend"
	@echo "  make docker-db            Start only PostgreSQL"
	@echo "  make docker-redis         Start only Redis"
	@echo ""
	@echo "Docker (Production with Traefik):"
	@echo "  make docker-prod          Start production stack"
	@echo "  make docker-prod-down     Stop production stack"
	@echo "  make docker-prod-logs     View production logs"
	@echo ""
	@echo "Template upgrade:"
	@echo "  make upgrade-dry-run       Preview template updates (no changes)"
	@echo "  make upgrade               Pull latest template changes (3-way merge)"
	@echo "  make upgrade-new-features  Upgrade + opt into newly added features"
	@echo "  make upgrade-finalize      Bump manifest after resolving conflicts"
	@echo ""
	@echo "Other:"
	@echo "  make routes        Show all API routes"
	@echo "  make clean         Clean cache files"
	@echo ""
