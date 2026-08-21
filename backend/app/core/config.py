"""Application configuration using Pydantic BaseSettings."""
# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals

from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import computed_field, field_validator, ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict


def find_env_file() -> Path | None:
    """Find .env file in current or parent directories."""
    current = Path.cwd()
    for path in [current, current.parent]:
        env_file = path / ".env"
        if env_file.exists():
            return env_file
    return None


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=find_env_file(),
        env_ignore_empty=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "agenticos"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = False
    DB_ECHO: bool = (
        False  # Set DB_ECHO=true to log SQL queries (latency + log-noise drain by default)
    )
    ENVIRONMENT: Literal["development", "local", "staging", "production"] = "local"
    TIMEZONE: str = "UTC"  # IANA timezone (e.g. "UTC", "Europe/Warsaw", "America/New_York")
    MODELS_CACHE_DIR: Path = Path("./models_cache")
    MEDIA_DIR: Path = Path("./media")
    # The knowledge-base document cap: a file that will be parsed, chunked and
    # embedded, and read back through retrieval rather than in one piece.
    MAX_UPLOAD_SIZE_MB: int = 50
    # What may be attached in chat, and deliberately a different number rather
    # than the one above. A knowledge-base document is chunked; an attachment to
    # an agent with no workspace is pasted whole into the prompt
    # (`app/services/attachments.py`), so the two surfaces fail differently at
    # the same size and one ceiling cannot be right for both. This was a
    # hardcoded 10 MiB in `file_storage.py` that no operator could raise, while
    # `/health` published the 50 above and the composer checked against it, so a
    # 20MB attachment passed the client, crossed the wire and was refused by a
    # limit no configuration produced (#498).
    CHAT_MAX_UPLOAD_SIZE_MB: int = 10
    # What a *stranger* may upload to a hosted page, in megabytes. Its own
    # setting and much smaller, because the two callers are not comparable: a
    # member uploading a fifty-megabyte export is somebody the organization
    # employs, and the same allowance on a public link is a way to fill a disk
    # from an address nobody knows. It is a ceiling on top of the allowlist and
    # the chat path's own ceiling, never a way past either.
    EMBED_MAX_UPLOAD_SIZE_MB: int = 5
    STORAGE_SOFT_LIMIT_BYTES: int = 5 * 1024 * 1024 * 1024

    # The monthly spend ceiling a brand-new organization starts with, in USD. A
    # new org one runaway agent away from a surprise bill is the posture this
    # avoids: a budget is only enforced if it exists, so a sensible default is
    # the safer first-run stance. `None` restores the older opt-in behaviour -
    # no ceiling until somebody sets one - and is how a deployment that would
    # rather choose its own turns the default off. Existing orgs are untouched;
    # this applies at creation only. Enforced exactly like a hand-set cap, so it
    # must be positive - `0` is an org whose agents can never answer, which the
    # `ck_organization_budget_positive` constraint already refuses.
    DEFAULT_ORG_MONTHLY_BUDGET_USD: Decimal | None = Decimal("100")

    @field_validator("DEFAULT_ORG_MONTHLY_BUDGET_USD")
    @classmethod
    def validate_default_org_budget(cls, v: Decimal | None) -> Decimal | None:
        """A default cap of zero or below would refuse every org's first run."""
        if v is not None and v <= 0:
            raise ValueError("DEFAULT_ORG_MONTHLY_BUDGET_USD must be positive, or unset for no cap")
        return v

    # Seconds the event loop may stop turning before the worker kills itself so
    # its supervisor replaces it; `0` or below switches the check off, which is
    # what a breakpoint needs. `cli/reload_supervisor.py` reads the same
    # variable from the environment for the judgement it makes from outside the
    # worker - one number, so switching the check off switches off both.
    # `app/core/watchdog.py` has the whole reasoning.
    EVENT_LOOP_WEDGED_AFTER: float = 15.0

    LOGFIRE_TOKEN: str | None = None
    LOGFIRE_SERVICE_NAME: str = "agenticos"
    LOGFIRE_ENVIRONMENT: str = "development"
    # Where a stored trace id can be *read*. `LOGFIRE_TOKEN` is a write
    # credential and carries neither slug, so a deployment that traces
    # successfully still cannot build a URL into what it sent. Both unset is the
    # ordinary case and means no link is offered - the trace id is still
    # recorded, because it is useful to anybody with Logfire access.
    LOGFIRE_ORGANIZATION: str | None = None
    LOGFIRE_PROJECT: str | None = None
    # The Logfire deployment those slugs belong to. `logfire-us` and `logfire-eu`
    # are different hosts, and a link built for the wrong one 404s rather than
    # redirecting.
    LOGFIRE_BASE_URL: str = "https://logfire-us.pydantic.dev"

    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = "agenticos"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:
        """Build async PostgreSQL connection URL."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL_SYNC(self) -> str:
        """Build sync PostgreSQL connection URL (for Alembic)."""
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30

    SECRET_KEY: str = "change-me-in-production-use-openssl-rand-hex-32"

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str, info: ValidationInfo) -> str:
        """Validate SECRET_KEY is secure in production."""
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        env = info.data.get("ENVIRONMENT", "local") if info.data else "local"
        if v == "change-me-in-production-use-openssl-rand-hex-32" and env == "production":
            raise ValueError(
                "SECRET_KEY must be changed in production! "
                "Generate a secure key with: openssl rand -hex 32"
            )
        return v

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    # How long a parked tool call waits before the sweep denies it by timeout.
    # Three days spans a weekend, which is the gap an approval most often falls
    # into: the one that arrives on Friday afternoon is the one nobody decides,
    # and expiring it on Saturday would be expiring it for being asked at the
    # wrong hour. Long enough that a decision is never taken away from someone
    # who was going to make it; short enough that the queue has a ceiling.
    APPROVAL_EXPIRY_HOURS: int = 72
    ALGORITHM: str = "HS256"
    FRONTEND_URL: str = "http://localhost:3000"
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/oauth/google/callback"

    VAULT_MASTER_KEY: str = ""

    API_KEY: str = "change-me-in-production"
    API_KEY_HEADER: str = "X-API-Key"

    @field_validator("API_KEY")
    @classmethod
    def validate_api_key(cls, v: str, info: ValidationInfo) -> str:
        """Validate API_KEY is set in production."""
        env = info.data.get("ENVIRONMENT", "local") if info.data else "local"
        if v == "change-me-in-production" and env == "production":
            raise ValueError(
                "API_KEY must be changed in production! "
                "Generate a secure key with: openssl rand -hex 32"
            )
        return v

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None
    REDIS_DB: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_URL(self) -> str:
        """Build Redis connection URL."""
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # What one caller may ask the public run API for, per minute. Keyed on the
    # caller rather than on their address: the endpoint is authenticated, and an
    # office behind one NAT is not one caller.
    RATE_LIMIT_RUN_PER_MINUTE: int = 30
    # How often one address may ask to be admitted to a widget or a hosted page,
    # per minute. Admission only - what a visitor may say once admitted is the
    # embed's own `rate_limit_per_minute`, counted per visitor.
    RATE_LIMIT_EMBED_PER_MINUTE: int = 20
    # How many files one visitor may upload to one page, per minute. Counted per
    # address first and then per (page, visitor), in the shared Redis, because
    # this is the first thing on this surface that *stores* something: a limit on
    # how fast a stranger may write bytes to the deployment's disk. Address first
    # because the continuity key is minted by the browser, so counting only that
    # bounds nothing - a script varies it per file.
    RATE_LIMIT_EMBED_UPLOAD_PER_MINUTE: int = 5
    # How often one hosted page may be configured, per minute. Per page and not
    # per address, because that config is fetched server-side by the frontend: on
    # that one route every visitor arrives as the same caller, so an address
    # counts nobody. Wide, because it bounds a page rather than rationing
    # visitors - what rations spend is the socket, counted per address.
    RATE_LIMIT_HOSTED_PAGE_PER_MINUTE: int = 240
    # How many auth attempts one caller gets per minute - login, register, token
    # refresh, and the reset/magic-link request and verify routes. Counted per IP
    # and, where the body carries one, per submitted address, both in the shared
    # Redis: the IP bounds the unauthenticated DoS bcrypt makes possible, the
    # address bounds a brute force against one account. Low, because a person
    # signing in does it a handful of times and a script does it thousands.
    RATE_LIMIT_AUTH_PER_MINUTE: int = 10
    # Whether `X-Forwarded-For` names the caller. Off by default because the
    # header is set by whoever is calling, so trusting it unconditionally is a
    # per-IP limit anybody bypasses by varying one string. On costs the mirror
    # image: behind a proxy every visitor arrives as the proxy and shares one
    # bucket. Turn it on when a proxy is the only thing that can reach this
    # deployment - see `docs/configuration.md`.
    RATE_LIMIT_TRUST_FORWARDED_FOR: bool = False

    PREFECT_API_URL: str = "http://localhost:4200/api"
    PREFECT_API_KEY: str | None = None
    # How many flow runs the runner may execute at once. Each one is a separate
    # Python process that imports the whole application, so the ceiling is memory
    # rather than CPU: five of them is about 600 MB. It matters most after
    # downtime, when the runner picks up a backlog of scheduled runs and would
    # otherwise start all of them - see app/worker/prefect_app.py.
    PREFECT_RUNNER_LIMIT: int = 5

    # The embeddings credential. Every collection in the deployment is embedded
    # on this key (via OpenRouter); model *profiles* in the vault cover chat
    # models only. Moving this to per-organization credentials is a feature,
    # not a rename - the vector column width is bound to EMBEDDING_MODEL below.
    OPENROUTER_API_KEY: str = ""
    # Deployment-level on purpose: pgvector columns are created at this model's
    # width, so changing it mid-life invalidates every existing collection.
    # ingestion_config guards both directions of that mistake.
    EMBEDDING_MODEL: str = "text-embedding-3-large"

    # Cloud-parser credential and OCR sidecar. Which parser a collection uses
    # is per-collection configuration; these say only how to reach the tools.
    LLAMAPARSE_API_KEY: str = ""
    LITEPARSE_OCR_SERVER_URL: str = ""

    # Where sandboxes run is deliberately *not* a setting. It is a row per
    # organization in `sandbox_connections`, with its token in the vault: a
    # deployment can hold more than one host, a token that authorises running
    # commands belongs where every other credential lives, and neither of those
    # is expressible in an environment variable. See
    # `app/db/models/sandbox_connection.py`.
    #
    # The token `make sandbox-token` generated, read here for exactly one purpose:
    # offering it to the vault. The service it belongs to was started with it from
    # this same file, so asking an operator to find and paste a value this process
    # can already see is friction with nothing behind it. It is never used to reach
    # a host - `resolve` unseals the vault entry a connection names, and that stays
    # the only path - so a deployment that leaves this unset loses a convenience and
    # nothing else.
    SANDBOXD_TOKEN: str = ""

    # How much of an agent's `state` workspace the platform will store, per
    # workspace. It lives in a JSONB column, so this is a real ceiling on a real
    # row rather than a policy: past it, writes are refused with a message the
    # model reads.
    SANDBOX_STATE_MAX_BYTES: int = 4 * 1024 * 1024
    # Above this, an attached image is written to the workspace and *not* also
    # sent inline. Below it the model gets both: it should see the picture, and
    # it should be able to run something over the file. The ceiling is where
    # paying for the bytes twice stops being worth it.
    SANDBOX_INLINE_IMAGE_MAX_BYTES: int = 5 * 1024 * 1024
    GOOGLE_DRIVE_CREDENTIALS_FILE: str = "credentials/google-drive-sa.json"
    S3_RAG_ENDPOINT: str | None = None
    S3_RAG_ACCESS_KEY: str = ""
    S3_RAG_SECRET_KEY: str = ""
    S3_RAG_BUCKET: str = "agenticos-rag"
    S3_RAG_REGION: str = "us-east-1"

    EMAIL_PROVIDER: str = "smtp"
    EMAIL_FROM: str = "noreply@agenticos.com"
    EMAIL_FROM_NAME: str = "agenticos"
    EMAIL_REPLY_TO: str | None = None
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_TLS: bool = True
    LOG_PROVIDER_WRITE_TO_DISK: bool = False

    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:8080",
    ]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: list[str] = ["*"]
    CORS_ALLOW_HEADERS: list[str] = ["*"]

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_cors_origins(cls, v: list[str], info: ValidationInfo) -> list[str]:
        """Warn if CORS_ORIGINS is too permissive in production."""
        env = info.data.get("ENVIRONMENT", "local") if info.data else "local"
        if "*" in v and env == "production":
            raise ValueError(
                "CORS_ORIGINS cannot contain '*' in production! Specify explicit allowed origins."
            )
        return v

    @computed_field  # type: ignore[prop-decorator]
    @property
    def rag(self) -> "RAGSettings":
        """The deployment-level half of the RAG settings.

        Only what genuinely belongs to the installation: the embedding model
        the vector columns were built for, and the credentials to reach a
        parser. Everything about *how a document is read* is per collection and
        arrives via :func:`app.services.ingestion_config.rag_settings_for`,
        which builds this same object from the collection's stored
        configuration; everything else falls to :class:`RAGSettings` defaults.
        """
        return RAGSettings(
            embeddings_config=EmbeddingsConfig(model=self.EMBEDDING_MODEL),
            document_parser=DocumentParser(),
            pdf_parser=PdfParser(
                api_key=self.LLAMAPARSE_API_KEY,
                liteparse_ocr_server_url=self.LITEPARSE_OCR_SERVER_URL or None,
            ),
        )


# Rebuild Settings to resolve RAGSettings forward reference
from app.services.rag.config import DocumentParser, EmbeddingsConfig, PdfParser, RAGSettings

Settings.model_rebuild()


settings = Settings()
