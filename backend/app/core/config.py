"""Application configuration using Pydantic BaseSettings."""
# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals

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
    MAX_UPLOAD_SIZE_MB: int = 50  # Max file upload size in MB
    STORAGE_SOFT_LIMIT_BYTES: int = 5 * 1024 * 1024 * 1024

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

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # 30 minutes
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

    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_PERIOD: int = 60  # seconds

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
