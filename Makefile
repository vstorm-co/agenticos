.PHONY: install format lint lint-backend lint-frontend check audit build-frontend test run clean help sandbox-token deps-upgrade deps-upgrade-all db-init dev dev-down dev-logs dev-rebuild dev-frontend docker-clean dev-server dev-server-down dev-server-logs dev-server-frontend stage stage-down prod prod-down prod-frontend upgrade upgrade-dry-run upgrade-new-features upgrade-finalize docs docs-build

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

# Which optional compose profiles `make dev` brings up. The sandbox service is
# on by default so an agent can be given a container without anybody reading a
# setup guide first — it is also the one service that mounts the Docker socket,
# so a host that will not have that removes `sandbox` from here.
COMPOSE_DEV_PROFILES ?= --profile sandbox

# The sandbox service refuses to start without a token, deliberately: it can run
# commands on this host, so an empty default would be a shared secret of "".
# Generated into backend/.env once, and left alone afterwards — regenerating it
# would orphan every workspace the service is currently holding.
sandbox-token:
	@if grep -q '^SANDBOXD_TOKEN=.' backend/.env 2>/dev/null; then \
		echo "SANDBOXD_TOKEN already set in backend/.env"; \
	else \
		token=$$(python3 -c "import secrets; print(secrets.token_urlsafe(32))"); \
		printf '\n# Authorises opening a sandbox session, and a session runs commands\n# on this host. Treat it like the Docker socket it sits in front of.\nSANDBOXD_TOKEN=%s\n' "$$token" >> backend/.env; \
		echo "▶ Generated SANDBOXD_TOKEN in backend/.env"; \
	fi

# === Local dev: build → up → migrate ===
# Idempotent — re-run anytime. Migrations are no-ops when already at head;
# admin seeding is a separate target (`make seed`) so re-running `make dev`
# doesn't keep retrying user creation.
dev: sandbox-token
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
	@echo "First time? Run 'make platform-bootstrap BOOTSTRAP_API_KEY=sk-...' —"
	@echo "an organization, an owner, a model and a published agent in one step."
	@echo "('make seed' is the older path: an admin login and nothing else.)"

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
# Both halves of the toolchain, because `check` runs both. eslint, prettier, tsc,
# vitest and next all live in `frontend/node_modules` and nowhere else, so a setup
# that installs only the backend leaves `lint`, `lint-frontend`, `test-frontend`,
# `build-frontend` and therefore `check` failing with `eslint: command not found`
# - and `check` runs the backend half first, so it says so four minutes in.
# `node_modules` is per-checkout and not shared between worktrees, which is why
# this is owed on every clone rather than once a laptop.
#
# `backend/.env` is the third thing a fresh checkout is missing. It is not
# tracked - it holds credentials - and everything that runs on the *host* reads
# it: `db-check`, `db-upgrade`, `run`, and pytest through `app.core.config`.
# Without one `POSTGRES_PASSWORD` defaults to empty and `alembic check` is
# refused with `fe_sendauth: no password supplied`, four minutes into `check`.
# Copied from the example rather than generated, so there is one definition of
# the defaults, and never overwritten: the file that exists holds somebody's
# keys.
#
# It runs last on purpose. It is the step most likely to fail on a given machine -
# no network, a proxy, a lockfile wanting a newer bun - and make stops at the first
# line that fails, so in front of the hooks it would leave somebody with no
# `commit-msg` hook and nothing refusing a commit on `main`, for a reason whose
# error message was about bun.
install:
	@if [ -f backend/.env ]; then \
		echo "backend/.env already exists - leaving it alone"; \
	else \
		cp backend/.env.example backend/.env; \
		echo "▶ Created backend/.env from backend/.env.example"; \
	fi
	uv sync --directory backend --dev
	@if git rev-parse --git-dir > /dev/null 2>&1; then \
		uv run --project backend pre-commit install --hook-type pre-commit --hook-type commit-msg; \
	else \
		echo "⚠️  Not a git repository - skipping pre-commit install"; \
		echo "   Run 'git init && make install' to set up pre-commit hooks"; \
	fi
	cd frontend && bun install --frozen-lockfile
	cd frontend && bun install --frozen-lockfile
	@echo ""
	@echo "✅ Installation complete!"
	@echo ""
	@echo "Next steps:"
	@echo "  • make docker-db        # Start PostgreSQL"
	@echo "  • make db-upgrade       # Apply migrations"
	@echo "  • make run              # Start development server"
	@echo ""
	@echo "Note: backend/.env now holds the development defaults - edit it to"
	@echo "      point at another database or to add a provider key on the host."

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
# Nothing is capped, so the lockfile is what holds versions still. Two targets:
# `deps-upgrade` moves the four frameworks this platform tracks, which is the
# one you want mid-week; `deps-upgrade-all` moves everything, which is what the
# `dependency-freshness` workflow runs on a schedule. Either way the upgrade is
# only done when the suite still passes.
FRAMEWORKS := fastapi pydantic-ai-slim pydantic-ai-skills logfire genai-prices

deps-upgrade:
	uv lock --directory backend $(foreach p,$(FRAMEWORKS),--upgrade-package $(p))
	uv sync --directory backend --dev
	@uv run --directory backend python -c "import fastapi, logfire, genai_prices, pydantic_ai; \
		print(f'fastapi {fastapi.__version__} | logfire {logfire.__version__} | pydantic-ai {pydantic_ai.__version__}')"
	@echo "▶ Now run 'make test' — an upgrade that breaks the suite is not done."

# Everything, not just the four - the same thing the scheduled freshness job
# does, so a red issue from it reproduces here. Expect more fallout.
deps-upgrade-all:
	uv lock --directory backend --upgrade
	uv sync --directory backend --dev
	cd frontend && bun update
	@echo "▶ Now run 'make check'."

# === Code Quality ===
# Every static check: both halves of the repository, plus the one check that
# reads the whole tree at once. CI splits the halves across two jobs (`lint` and
# the first three steps of `test-frontend`) because they need different
# toolchains; here they are one command with callable parts, so a Python-only
# change can run `lint-backend` and skip a minute of eslint.
#
# The frontend half was missing entirely until #143: `make lint` ran ruff, ty and
# the guard scripts, while CI additionally ran eslint, prettier and tsc - so
# `make lint` passed on a branch with a type error in a `.tsx`, and CLAUDE.md's
# "ruff + ty + eslint + tsc" described a command that ran half of that.
lint: lint-backend lint-frontend lint-spelling

# `ruff check .` from `backend/` reads every tracked tree there - app, tests, cli
# and alembic - rather than the three named paths it used to, which left the nine
# migrations and this repo's guard scripts linted by nothing (#229). `../scripts`
# is the repository-root `scripts/` (the guards that gate every PR), which lives
# outside `backend/` and so is a fourth path rather than a second invocation; its
# relaxations are declared in `pyproject.toml` under `../scripts/**`.
lint-backend:
	uv run --directory backend ruff check . ../scripts
	uv run --directory backend ruff format . ../scripts --check
	uv run --directory backend ty check
	uv run --directory backend vulture
	uv run --directory backend deptry app cli alembic
	python3 scripts/check_backticks.py
	python3 scripts/check_routes.py
	python3 scripts/check_comments.py

# Unused functions and methods, reported rather than gated. `make lint` runs
# vulture at a confidence high enough to be a gate (unused variables and
# parameters, near-zero false positives); this lowers it to reach unused
# functions too, which on a registry-driven codebase come with false positives -
# a CLI command, a capability hook, a route handler - that a human reads before
# deleting. The same role dependency-freshness plays for dependencies. See
# [tool.vulture] in backend/pyproject.toml.
#
# The frontend half is knip's *full* report, and stays a report: on a
# design-system codebase it flags the whole UI-primitive barrel and every
# exported type it cannot trace a use for, so `frontend/knip.jsonc` narrows it to
# what is worth reading and the rest is read by eye. Its one unambiguous half -
# a declared dependency nothing imports - is a gate instead, in `lint-frontend`.
dead-code:
	uv run --directory backend vulture --min-confidence 60
	cd frontend && bunx knip --no-progress

# The i18n guard is the fourth step and belongs here rather than beside the Python
# ones: since #395 it *is* TypeScript, reading `frontend/src` through
# `ts.createSourceFile` instead of ten regexes over source text. It runs last because
# it is the slowest of the four and the other three answer faster on a typo.
#
# `lint:deps` is knip narrowed to the one thing it is never wrong about: a
# package declared in `package.json` that nothing imports, and the reverse.
# It gates because the alternative was measured - `date-fns` was declared,
# imported nowhere, and *listed in knip's own ignores*, so the report that
# would have found it had been told not to (#156). The rest of knip's output
# needs a human and stays in `make dead-code`.
lint-frontend:
	cd frontend && bun run lint
	cd frontend && bunx prettier --check "scripts/**/*.ts" "src/**/*.{ts,tsx}" "e2e/**/*.ts"
	cd frontend && bun run type-check
	cd frontend && bun run check:i18n
	cd frontend && bun run lint:deps

# Spelling, over every tracked file rather than the ones a commit happens to
# touch. The hook alone only ever reads changed files, so a misspelling that
# lands with its file sits there until somebody edits that file for an unrelated
# reason - and their commit is then refused by a word they did not write. That is
# #188: one misspelled word reached `main` with #119, and what found it was a
# person running the hook by hand while reconciling `make check` with CI for #143
# - not any gate. (Spelling the word here would fail this very check.)
#
# It runs the hook rather than codespell directly, because a second invocation
# would mean a second version pin and a second copy of the exclude list. The rev
# in `.pre-commit-config.yaml` and the ignore list in `.codespellrc` stay the only
# definitions; this target just points them at the whole tree.
#
# `--project backend`, not `--directory backend` as the targets above use: the
# second changes directory, and pre-commit would then look for its config and its
# git tree inside `backend/`.
lint-spelling:
	uv run --project backend pre-commit run codespell --all-files

# The write side of both halves. `lint-frontend` checks prettier rather than
# applying it, so without the second line here the only way to fix a formatting
# failure would be to let the pre-commit hook rewrite the file for you.
format:
	uv run --directory backend ruff format . ../scripts
	uv run --directory backend ruff check . ../scripts --fix
	cd frontend && bunx prettier --write "src/**/*.{ts,tsx}" "e2e/**/*.ts"

# === Testing ===
# `test` is the gate: it fails if platform-layer coverage drops below 100%.
#
# CI overrides the report because Codecov wants XML and a terminal diff is no use
# in a log nobody reads when it is green. Same run, same gate, either way.
COV_REPORT ?= term-missing

# `-n auto --maxprocesses 4`: run across worker processes. The integration
# suite is I/O-bound on one Postgres and roughly halves; the unit suite is
# import-bound (every worker imports the app once) and gains little past four
# workers, so `auto` is capped there - on a many-core laptop an uncapped `auto`
# is slower than serial, all of it worker startup. pytest-cov combines the
# per-worker data, so the 100% gate holds unchanged. A scoped `pytest <file>`
# stays serial: worker startup is not worth paying for one file.
test:
	uv run --directory backend pytest tests/ -v --cov --cov-report=$(COV_REPORT) -n auto --maxprocesses 4

# Fast loop while writing code — no coverage, no gate.
test-fast:
	uv run --directory backend pytest tests/ -q --no-cov -n auto --maxprocesses 4

# Integration tests only. These talk to a real database; start it with `make docker-db`.
test-integration:
	uv run --directory backend pytest tests/integration -v --no-cov -n auto --maxprocesses 4

test-cov:
	uv run --directory backend pytest tests/ --cov --cov-report=html --cov-report=term-missing -n auto --maxprocesses 4
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

# `next build` type-checks the route tree and fails on a server component that
# cannot render - neither of which tsc or vitest sees, which is why CI builds on
# every pull request and why `check` has to.
build-frontend:
	cd frontend && bun run build

# CI's `security` job. Audits what the lockfile resolves to - which is what a
# deployment installs - rather than whatever this machine happens to have in its
# virtualenv. The export is fully pinned, so `--no-deps --disable-pip` skips a
# resolution round-trip pip-audit would otherwise do in a throwaway virtualenv.
#
# Needs the network: the advisory database is fetched, not vendored - one request
# per locked distribution, 254 of them, none of which pip-audit retries and all of
# which exit 1 the way a real advisory does. `scripts/audit_dependencies.py` is
# what stops a single slow answer reading as a finding on a required check (#855):
# it retries every run that reached no verdict, and says which of the four states
# it ended in.
#
# It says so on its **last line**, not in its exit status, because make has no way
# to carry one: a failed recipe becomes make's own exit 2, so a caller reaching
# this through `make audit` - which the `Security Scan` job does - cannot tell 75
# from 1. So the contract is `AUDIT: CLEAN|VULNERABLE|NETWORK|FAILED - detail`,
# also appended to $GITHUB_STEP_SUMMARY inside a job. `make audit | tail -1` is
# the whole of it; the script's own 0/1/75 is for callers that invoke it directly.
AUDIT_ATTEMPTS ?= 3
AUDIT_TIMEOUT ?= 30

audit:
	cd backend && uv export --frozen --no-emit-project --no-hashes -o requirements-audit.txt
	python3 scripts/audit_dependencies.py backend/requirements-audit.txt \
		--attempts $(AUDIT_ATTEMPTS) --timeout $(AUDIT_TIMEOUT)

# Playwright starts the frontend itself; the backend and its seed are on you.
# Checked rather than assumed: against a backend that is not there the suite
# fails in fifty places at once, none of which say what is actually wrong.
#
# All three addresses are overridable so the suite can run beside another
# checkout holding the defaults: E2E_PORT moves the frontend, E2E_STUB_MODEL_PORT
# the stub model server, E2E_BACKEND the API the health check dials. They are
# passed into the recipe's environment so Playwright and its specs read the same
# values, and printed first because a suite that fails on a busy port should say
# which one it wanted.
E2E_BACKEND ?= http://localhost:8000
E2E_PORT ?= 3000
E2E_STUB_MODEL_PORT ?= 4010

test-e2e:
	@if ! curl -sf $(E2E_BACKEND)/api/v1/health > /dev/null; then \
		echo "No backend at $(E2E_BACKEND)."; \
		echo "  make dev && make platform-bootstrap"; \
		exit 1; \
	fi
	@echo "▶ frontend :$(E2E_PORT)  ·  stub model :$(E2E_STUB_MODEL_PORT)  ·  backend $(E2E_BACKEND)"
	cd frontend && E2E_PORT=$(E2E_PORT) E2E_STUB_MODEL_PORT=$(E2E_STUB_MODEL_PORT) bun run test:e2e

# Every CI job, in the order the workflow declares them, with the exceptions
# named below. This is the one claim in this file that has to be exactly true:
# a command advertised as CI that runs less than CI prints "All checks passed"
# over a branch the build will refuse, and the cost is a review cycle plus
# however long somebody spends believing the local answer.
#
# The workflow calls these targets rather than repeating the commands, and
# `backend/tests/test_ci_parity.py` fails if the two ever drift again. It has
# drifted four times, all four found by #143:
#
#   - `check` ran `test-frontend`, which measures no coverage, where CI runs
#     `test:coverage` and its 100% gate - green locally and red for every run on
#     `feat/sandbox` after 832d647;
#   - `lint` ran neither eslint, prettier nor tsc, all three of which gate CI;
#   - `check` ran neither `next build`, the docs build nor the dependency audit -
#     three whole jobs;
#   - and in the other direction, CI never ran the i18n guard, so a hardcoded
#     string failed `make lint` and passed the build. It was `scripts/check_i18n.py`
#     then and is `frontend/scripts/check-i18n.ts` now, in `lint-frontend`.
#
# Not here, deliberately:
#
#   - `e2e`, which needs a migrated database, a seeded organization and a running
#     backend: `make dev && make platform-bootstrap && make test-e2e`.
#   - the image build and Trivy scan, which CI runs only on a push to `main`.
#   - `test-migrations`. CI cycles the chain against a throwaway database; here
#     `alembic downgrade base` points at whatever `backend/.env` says, which on a
#     laptop is the database with your own work in it.
CHECK_DB_PORT ?= 5432

check: lint test db-check test-frontend-cov build-frontend docs-build audit
	@echo ""
	@echo "All checks passed — every CI job except e2e."
	@if ! python3 -c 'import socket; socket.create_connection(("127.0.0.1", $(CHECK_DB_PORT)), 1).close()' 2>/dev/null; then \
		echo ""; \
		echo "⚠  No database on 127.0.0.1:$(CHECK_DB_PORT), so tests/integration skipped itself"; \
		echo "   — and CI's test job has one, so it did not. 'make docker-db' closes that gap."; \
	fi

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

# Do the models and the migrations still agree? `alembic check` autogenerates
# against the database and fails if anything is left over - the gate that catches
# "somebody edited a model and forgot the migration", the one question
# `test-migrations` (which only proves the chain applies and rolls back) does not
# answer.
#
# Unlike `test-migrations` this belongs in `make check`: it reflects the schema
# and diffs it, it never downgrades, so it cannot empty a laptop's working
# database. It does need one at head - `make dev` keeps it there - and is skipped
# rather than failed when none is reachable, the same bargain `check` strikes for
# the integration suite. CI always has a database, so there it runs for real,
# after `test-migrations` has left it at head.
db-check:
	@if python3 -c 'import socket; socket.create_connection(("127.0.0.1", $(CHECK_DB_PORT)), 1).close()' 2>/dev/null; then \
		uv run --directory backend alembic check; \
	else \
		echo "⚠  No database on 127.0.0.1:$(CHECK_DB_PORT), so 'alembic check' was skipped"; \
		echo "   — and CI's test job has one, so it did not. 'make docker-db' closes that gap."; \
	fi


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
	@echo "  make install       Install Python + frontend deps and the pre-commit hooks"
	@echo ""
	@echo "Development:"
	@echo "  make run           Start dev server (with hot reload)"
	@echo "  make test          Run tests"
	@echo "  make lint          Every static check: ruff, ty, eslint, prettier, tsc, the guards, codespell"
	@echo "  make lint-backend  Just the Python half"
	@echo "  make lint-frontend Just the TypeScript half"
	@echo "  make lint-spelling Just codespell, over every tracked file"
	@echo "  make format        Auto-format code (ruff + prettier)"
	@echo "  make check         Every CI job except e2e - before opening a pull request"
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
