"""Application configuration using Pydantic BaseSettings."""
# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals

from pathlib import Path
from typing import Literal

from pydantic import computed_field, field_validator, ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import BaseModel, Field


# Same slug rule as a user connection (app/schemas/mcp_connection.py). The name
# becomes the server's tool prefix in the agent, so an unconstrained name could
# collapse two servers onto one prefix — and the second would then be dropped
# from every chat turn. Reject it at startup instead.
MCP_SERVER_NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,31}$"


class McpServerConfig(BaseModel):
    """One deployment-managed MCP server (see MCP_SERVERS below)."""

    name: str = Field(pattern=MCP_SERVER_NAME_PATTERN)
    url: str
    headers: dict[str, str] = {}
    # None = expose every tool the server offers.
    allowed_tools: list[str] | None = None


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
    # Soft per-org storage cap surfaced on /billing — not enforced yet (5 GB).
    STORAGE_SOFT_LIMIT_BYTES: int = 5 * 1024 * 1024 * 1024

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
    ALGORITHM: str = "HS256"

    # Public URL of the frontend; used to build OAuth redirect targets and
    # Stripe checkout/portal return URLs. Always declared (not gated) because
    # the billing model_validator references it unconditionally.
    FRONTEND_URL: str = "http://localhost:3000"

    # Where this API answers from, as the public internet reaches it. Used to
    # build the one-line embed snippet a customer pastes into their site, which
    # is why it cannot be derived from the request: the dashboard is served from
    # the frontend's host, and a snippet carrying that host would point at a
    # server with no widget on it. Defaults to the frontend URL so a local
    # install works without another variable to set.
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/oauth/google/callback"

    # Master key for the secret vault (app.core.vault) — provider credentials,
    # channel bot tokens, MCP credentials and organization secrets all seal
    # against it. Empty falls back to SECRET_KEY so a fresh checkout runs; set
    # it explicitly in production so secrets survive a SECRET_KEY rotation.
    VAULT_MASTER_KEY: str = ""

    # Whether a model profile may point at a private, loopback or link-local
    # address. Off by default: on a shared deployment any member who can add a
    # provider key could otherwise turn the backend into a probe for its
    # internal network. Turn it on for a self-hosted install, which is what
    # makes Ollama on localhost, a vLLM server or a LiteLLM proxy usable.
    # Scoped to model endpoints — webhooks and MCP servers are unaffected.
    ALLOW_INTERNAL_MODEL_ENDPOINTS: bool = False

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

    # Prefect API — set to http://prefect-server:4200/api for self-hosted,
    # or the Prefect Cloud workspace URL for cloud mode.
    PREFECT_API_URL: str = "http://localhost:4200/api"
    # Only required when PREFECT_CLOUD=true (your workspace API key)
    PREFECT_API_KEY: str | None = None
    OPENROUTER_API_KEY: str = ""
    AI_MODEL: str = "anthropic/claude-opus-4-7"
    AI_TEMPERATURE: float = 0.7
    AI_THINKING_ENABLED: bool = False
    AI_THINKING_EFFORT: str = "medium"  # "low", "medium", "high"
    AI_AVAILABLE_MODELS: list[str] = [
        "anthropic/claude-opus-4-7",
        "anthropic/claude-sonnet-4-6",
        "openai/gpt-5.5",
        "google/gemini-2.5-flash",
        "deepseek/deepseek-r1",
    ]
    AI_FRAMEWORK: str = "pydantic_ai"
    LLM_PROVIDER: str = "openrouter"

    CODE_EXECUTION_TIMEOUT_SECS: float = 10.0
    CODE_EXECUTION_MAX_MEMORY_MB: int = 256

    # Deployment-managed MCP servers, always attached to the agent (on top of
    # the per-user connections configured in Settings → Integrations).
    # Set as a JSON list whose objects carry: name, url, optional headers for
    # authentication, and an optional allowed_tools allowlist.
    MCP_SERVERS: list[McpServerConfig] = []
    # Per-server budget for the pre-flight tools/list ping; unreachable servers
    # are skipped for the turn instead of failing the chat.
    MCP_CONNECT_TIMEOUT_SECS: float = 3.0

    @field_validator("MCP_SERVERS")
    @classmethod
    def validate_mcp_server_names(cls, v: list[McpServerConfig]) -> list[McpServerConfig]:
        """Reject duplicate names: they share a tool prefix, and the agent can
        only attach one server per prefix — the rest would vanish silently."""
        names = [server.name for server in v]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"MCP_SERVERS has duplicate server names: {', '.join(duplicates)}")
        return v

    # Telegram: webhook base URL (e.g. https://api.yourdomain.com) — leave empty to use polling
    TELEGRAM_WEBHOOK_BASE_URL: str = ""
    # Slack: signing secret for verifying webhook requests (from Slack app settings)
    SLACK_SIGNING_SECRET: str = ""
    # Slack: bot token (xoxb-...) — used for sending messages via Web API
    SLACK_BOT_TOKEN: str = ""
    # Slack: app-level token (xapp-...) — used for Socket Mode (dev/polling)
    SLACK_APP_TOKEN: str = ""
    # Vector Database (pgvector) — uses existing PostgreSQL
    EMBEDDING_MODEL: str = "text-embedding-3-large"

    # How documents are parsed and chunked is NOT here. It is a per-collection
    # choice stored on `knowledge_bases.ingestion_config` (see
    # app.services.ingestion_config), because an installation-wide parser or
    # chunk size makes the same form produce different collections on two
    # deployments, with nowhere in the product to see or change it. The removed
    # settings were PDF_PARSER, CHAT_PDF_PARSER, LLAMAPARSE_TIER,
    # LITEPARSE_OCR_LANGUAGE, LITEPARSE_TIMEOUT_SECONDS, RAG_ENABLE_OCR,
    # RAG_CHUNK_SIZE, RAG_CHUNK_OVERLAP and RAG_CHUNKING_STRATEGY.
    RAG_DEFAULT_COLLECTION: str = "documents"
    RAG_TOP_K: int = 10
    RAG_HYBRID_SEARCH: bool = False  # Enable BM25 + vector hybrid search
    # Credentials and network addresses stay deployment-level on purpose: a key
    # is billed to the operator, and letting a tenant name an internal OCR
    # address is the request forgery this platform refuses everywhere else.
    LLAMAPARSE_API_KEY: str = ""
    # Empty url uses the bundled Tesseract; point at e.g. http://easyocr:8000
    # or http://paddleocr:8000 for HTTP OCR.
    LITEPARSE_OCR_SERVER_URL: str = ""
    RAG_ENABLE_IMAGE_DESCRIPTION: bool = True  # set to false to disable LLM image description
    RAG_IMAGE_DESCRIPTION_MODEL: str = ""  # empty = use AI_MODEL
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

        Only what genuinely belongs to the installation: where vectors live, how
        they are searched, and the credentials to reach a parser. Everything
        about *how a document is read* is per collection and arrives via
        :func:`app.services.ingestion_config.rag_settings_for`, which builds this
        same object from the collection's stored configuration.
        """
        return RAGSettings(
            collection_name=self.RAG_DEFAULT_COLLECTION,
            enable_hybrid_search=self.RAG_HYBRID_SEARCH,
            embeddings_config=EmbeddingsConfig(model=self.EMBEDDING_MODEL),
            document_parser=DocumentParser(),
            pdf_parser=PdfParser(
                api_key=self.LLAMAPARSE_API_KEY,
                liteparse_ocr_server_url=self.LITEPARSE_OCR_SERVER_URL or None,
            ),
            enable_image_description=self.RAG_ENABLE_IMAGE_DESCRIPTION,
            image_description_model=self.RAG_IMAGE_DESCRIPTION_MODEL,
        )


# Rebuild Settings to resolve RAGSettings forward reference
from app.services.rag.config import DocumentParser, EmbeddingsConfig, PdfParser, RAGSettings

Settings.model_rebuild()


settings = Settings()
