# Configuration Reference

All configuration is managed via environment variables, loaded from
`backend/.env` using [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

Settings are defined in `app/core/config.py` and accessed via the global
`settings` object:

```python
from app.core.config import settings

print(settings.AI_MODEL)
print(settings.DEBUG)
```

## Getting Started

```bash
cd backend

# Copy the example file (may already exist if generated with --generate-env)
cp .env.example .env

# Generate a secure secret key
openssl rand -hex 32
# Paste the output as SECRET_KEY in .env
```

## Project Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `PROJECT_NAME` | `agenticos` | Display name for the project |
| `API_V1_STR` | `/api/v1` | API version prefix |
| `DEBUG` | `false` | Enable debug mode (verbose errors, auto-reload) |
| `ENVIRONMENT` | `local` | One of: `development`, `local`, `staging`, `production` |
| `TIMEZONE` | `UTC` | IANA timezone (e.g. `UTC`, `Europe/Warsaw`, `America/New_York`) |
| `MODELS_CACHE_DIR` | `./models_cache` | Directory for cached ML models |
| `MEDIA_DIR` | `./media` | Directory for uploaded files |
| `MAX_UPLOAD_SIZE_MB` | `50` | Maximum file upload size in megabytes |

## Authentication

### JWT

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | (insecure default) | JWT signing key. **Must** be changed in production. Generate with: `openssl rand -hex 32` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_MINUTES` | `10080` | Refresh token lifetime (7 days) |
| `ALGORITHM` | `HS256` | JWT signing algorithm |

Production validation: `SECRET_KEY` must be at least 32 characters and cannot
use the default value in `ENVIRONMENT=production`.

### Secret vault

Every credential the platform stores at rest — provider keys, channel bot
tokens, MCP credentials and organization secrets — is sealed by
`app/core/vault.py`, whose envelope is derived from the master key **and the
owner** (an organization, or the member a personal connection belongs to). A
ciphertext is therefore useless outside the tenant it was sealed for.

| Variable | Default | Description |
|----------|---------|-------------|
| `VAULT_MASTER_KEY` | (empty, falls back to `SECRET_KEY`) | Master key for the secret vault. Set it explicitly in production so stored secrets survive a `SECRET_KEY` rotation. Generate with: `openssl rand -hex 32` |
| `ALLOW_INTERNAL_MODEL_ENDPOINTS` | `false` | Whether a model profile may point at a private, loopback or link-local address. Turn it on for a self-hosted install running Ollama, vLLM or a LiteLLM proxy; leave it off on a shared deployment, where any member who can add a provider key could otherwise reach the internal network. Applies to model endpoints only — webhooks and MCP servers are unaffected. |

### API Key

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | `change-me-in-production` | Shared API key for programmatic access |
| `API_KEY_HEADER` | `X-API-Key` | HTTP header name for API key |

Production validation: `API_KEY` cannot use the default value in
`ENVIRONMENT=production`.

### OAuth2 (Google)

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_CLIENT_ID` | (empty) | Google OAuth2 client ID |
| `GOOGLE_CLIENT_SECRET` | (empty) | Google OAuth2 client secret |
| `GOOGLE_REDIRECT_URI` | `http://localhost:8000/api/v1/oauth/google/callback` | OAuth2 callback URL |
| `FRONTEND_URL` | `http://localhost:3000` | Frontend URL for OAuth2 redirects |


## Database (PostgreSQL)

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_HOST` | `localhost` | PostgreSQL host |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_USER` | `postgres` | PostgreSQL user |
| `POSTGRES_PASSWORD` | (empty) | PostgreSQL password |
| `POSTGRES_DB` | `agenticos` | Database name |
| `DB_POOL_SIZE` | `5` | Connection pool size |
| `DB_MAX_OVERFLOW` | `10` | Max overflow connections |
| `DB_POOL_TIMEOUT` | `30` | Pool timeout in seconds |

Computed properties:
- `DATABASE_URL` -- async connection string (`postgresql+asyncpg://...`)
- `DATABASE_URL_SYNC` -- sync connection string for Alembic

## Redis

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `localhost` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_PASSWORD` | (none) | Redis password (optional) |
| `REDIS_DB` | `0` | Redis database number |

## AI Agent

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | (empty) | OpenRouter API key |
| `AI_MODEL` | `anthropic/claude-opus-4-7` | Default LLM model for chat |
| `AI_TEMPERATURE` | `0.7` | LLM temperature (0.0 = deterministic, 1.0 = creative) |
| `AI_AVAILABLE_MODELS` | (auto-configured) | JSON list of models shown in the UI model selector |
| `AI_FRAMEWORK` | `pydantic_ai` | AI framework (informational) |
| `LLM_PROVIDER` | `openrouter` | LLM provider (informational) |

### Customizing Available Models

Override `AI_AVAILABLE_MODELS` in `.env` to customize the model selector:

```bash
AI_AVAILABLE_MODELS=["gpt-5.5","gpt-5.4","claude-opus-4-7"]
```

## Observability (Logfire)

| Variable | Default | Description |
|----------|---------|-------------|
| `LOGFIRE_TOKEN` | (none) | Pydantic Logfire token. Get one at https://logfire.pydantic.dev |
| `LOGFIRE_SERVICE_NAME` | `agenticos` | Service name in Logfire dashboard |
| `LOGFIRE_ENVIRONMENT` | `development` | Environment tag |

## Web Search

| Variable | Default | Description |
|----------|---------|-------------|

## RAG (Retrieval Augmented Generation)

### Vector Database

pgvector uses the existing PostgreSQL connection. No additional configuration
is needed.

### Embeddings

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model |

### Retrieval

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_DEFAULT_COLLECTION` | `documents` | Default collection for search (used by agent tool) |
| `RAG_TOP_K` | `10` | Default number of results to return |
| `RAG_HYBRID_SEARCH` | `false` | Enable BM25 + vector hybrid search |

### Document Parsing — configured per collection, not here

Parser, OCR, chunk size, chunk overlap, chunking strategy and the
image-description model are **not** environment variables. They are stored on
each knowledge base (`knowledge_bases.ingestion_config`) and edited on `/kb`,
and any one of them can additionally be overridden for a single upload.

The reason is that one installation-wide value made the same form produce
different collections on two deployments, with nothing in the product showing
which — and a scanned contract archive and a folder of Markdown notes want
different answers on the same deployment. `PDF_PARSER`, `CHAT_PDF_PARSER`,
`LLAMAPARSE_TIER`, `LITEPARSE_OCR_LANGUAGE`, `LITEPARSE_TIMEOUT_SECONDS`,
`RAG_ENABLE_OCR`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP` and
`RAG_CHUNKING_STRATEGY` were removed; setting them now does nothing.

What stays here is what a tenant must not choose:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLAMAPARSE_API_KEY` | (empty) | LlamaParse API key — billed to the operator |
| `LITEPARSE_OCR_SERVER_URL` | (empty) | HTTP OCR server; an address on the deployment's own network |

Chat attachments are read with PyMuPDF and are not configurable: an attachment
belongs to no collection, so there is no stored configuration to read.

### Google Drive Sync

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_DRIVE_CREDENTIALS_FILE` | `credentials/google-drive-sa.json` | Path to Google service account credentials |

### S3/MinIO Sync

| Variable | Default | Description |
|----------|---------|-------------|
| `S3_RAG_ENDPOINT` | (none) | S3/MinIO endpoint URL |
| `S3_RAG_ACCESS_KEY` | (empty) | Access key |
| `S3_RAG_SECRET_KEY` | (empty) | Secret key |
| `S3_RAG_BUCKET` | `agenticos-rag` | Bucket name |
| `S3_RAG_REGION` | `us-east-1` | AWS region |

## Messaging Channels

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_WEBHOOK_BASE_URL` | (empty) | Base URL for Telegram webhook (e.g. `https://yourdomain.com`). Required only in webhook mode |
| `SLACK_SIGNING_SECRET` | (empty) | Slack app signing secret for Events API signature verification |
| `SLACK_BOT_TOKEN` | (empty) | Slack bot OAuth token (`xoxb-...`) for sending messages via Web API |
| `SLACK_APP_TOKEN` | (empty) | Slack app-level token (`xapp-...`) for Socket Mode (development only) |

## CORS

| Variable | Default | Description |
|----------|---------|-------------|
| `CORS_ORIGINS` | `["http://localhost:3000","http://localhost:8080"]` | Allowed origins (JSON array) |
| `CORS_ALLOW_CREDENTIALS` | `true` | Allow credentials (cookies) |
| `CORS_ALLOW_METHODS` | `["*"]` | Allowed HTTP methods |
| `CORS_ALLOW_HEADERS` | `["*"]` | Allowed HTTP headers |

Production validation: `CORS_ORIGINS` cannot contain `"*"` in
`ENVIRONMENT=production`.

## Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_REQUESTS` | `100` | Maximum requests per period |
| `RATE_LIMIT_PERIOD` | `60` | Period in seconds |

## Docker / Production

| Variable | Default | Description |
|----------|---------|-------------|
| `DOMAIN` | `example.com` | Production domain (for Traefik) |
| `ACME_EMAIL` | `admin@example.com` | Let's Encrypt email for SSL certs |
| `REDIS_PASSWORD` | `change-me-in-production` | Redis password for production |

## Production Checklist

Before deploying to production, ensure these variables are properly set:
1. `SECRET_KEY` -- Generate a unique 64-character hex key: `openssl rand -hex 32`
2. `API_KEY` -- Generate a unique key: `openssl rand -hex 32`
3. `ENVIRONMENT` -- Set to `production`
4. `DEBUG` -- Set to `false`
5. `POSTGRES_PASSWORD` -- Use a strong, unique password
6. `CORS_ORIGINS` -- List only your actual frontend domain(s)
7. `REDIS_PASSWORD` -- Set a strong password
8. `OPENROUTER_API_KEY` -- Your production API key
