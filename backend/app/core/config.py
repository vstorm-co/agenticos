"""Application configuration using Pydantic BaseSettings."""
# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals

from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field, field_validator, model_validator, ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict

SmtpTlsMode = Literal["auto", "implicit", "starttls"]
"""How an encrypted SMTP connection is opened: chosen by the port, or forced."""


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

    # Processing bounds for the extra chat attachment formats (FA-013). Each has a
    # concrete default and `gt=0` so a misconfigured `0`/negative is refused at
    # startup rather than producing an unbounded conversion or a zero-page cap.
    #
    # DOC (and other legacy office) conversion runs a managed `soffice` subprocess
    # (`app/core/office_convert.py`); these bound it. The timeout is far below
    # RAG's 600s because an interactive upload cannot wait that long, the
    # concurrency semaphore caps how many LibreOffice processes run at once (the
    # subprocess bypasses the `run_blocking` admission gate), the grace is the
    # TERM->KILL window, and the output cap is checked before the converted file is
    # read back.
    #
    # Three of the four now bound *every* LibreOffice conversion rather than only
    # chat's: the two managers were collapsed into one (#1767), and the semaphore
    # and the kill grace belong to the manager. The `CHAT_` prefix is kept because
    # renaming a setting silently stops an operator's env file applying; only
    # `CHAT_CONVERT_TIMEOUT_SECONDS` and `CHAT_CONVERT_OUTPUT_MAX_BYTES` are still
    # read by the chat caller alone.
    CHAT_CONVERT_TIMEOUT_SECONDS: int = Field(default=60, gt=0)
    CHAT_CONVERT_MAX_CONCURRENCY: int = Field(default=2, gt=0)
    CHAT_CONVERT_KILL_GRACE_SECONDS: float = Field(default=5, gt=0)
    CHAT_CONVERT_OUTPUT_MAX_BYTES: int = Field(default=20 * 1024 * 1024, gt=0)

    # TIFF is converted to PNG at the point it is shown to the model; a multi-page
    # scan can be many pages, so the page count is capped and each image is bounded
    # by pixel count before decode (an explicit per-image check, never a mutation of
    # the process-global `Image.MAX_IMAGE_PIXELS` the shared file pool would race).
    CHAT_TIFF_MAX_INLINE_PAGES: int = Field(default=10, gt=0)
    CHAT_IMAGE_MAX_PIXELS: int = Field(default=40_000_000, gt=0)

    # ZIP-backed office formats (ODF, PPTX) are validated through `safe_unzip`
    # before a third-party parser opens them, so a small upload cannot decompress
    # to an unbounded amount of memory. Member sizes are measured by reading each
    # member, never trusting the forgeable central-directory `file_size`.
    CHAT_ARCHIVE_MEMBER_MAX_BYTES: int = Field(default=50 * 1024 * 1024, gt=0)
    CHAT_ARCHIVE_TOTAL_MAX_BYTES: int = Field(default=100 * 1024 * 1024, gt=0)
    CHAT_ARCHIVE_MAX_MEMBERS: int = Field(default=2000, gt=0)

    # The layered text budget. Stored extracted text is capped so a ZIP/OLE
    # expansion cannot bloat the row; the per-file and per-turn prompt caps bound
    # what the no-workspace paste path puts in front of the model, the aggregate
    # one across every attachment in a single turn.
    CHAT_PARSED_TEXT_MAX_CHARS: int = Field(default=1_000_000, gt=0)
    CHAT_PROMPT_TEXT_MAX_CHARS: int = Field(default=200_000, gt=0)
    CHAT_TURN_TEXT_MAX_CHARS: int = Field(default=500_000, gt=0)
    # How many bytes of inline image one turn may carry, across every attachment.
    # `SANDBOX_INLINE_IMAGE_MAX_BYTES` bounds one image and
    # `CHAT_TIFF_MAX_INLINE_PAGES` one TIFF, which multiply to fifty megabytes
    # from a single file - and nothing bounded several files together, so a turn
    # could hold hundreds of megabytes before the provider request was encoded.
    # The chat takes no per-turn file count, and even a public embed takes three
    # (#1591 review).
    CHAT_TURN_INLINE_MAX_BYTES: int = Field(default=20 * 1024 * 1024, gt=0)

    # A published artifact is one self-contained page, and these bound it. The
    # size is per version: a report with its charts and a library inlined fits
    # in a few megabytes, and a page past this one is an export, which belongs in
    # the workspace. The version count is per artifact - a report republished
    # every hour would otherwise grow storage for ever between retention sweeps.
    ARTIFACT_MAX_BYTES: int = Field(default=5 * 1024 * 1024, gt=0)
    ARTIFACT_MAX_VERSIONS: int = Field(default=20, ge=1)
    # How long a signed content address stays valid. The console and the public
    # page ask for a fresh one every time they draw the frame, so this is only
    # the window in which an address copied out of a frame still opens - and the
    # window in which access revoked a moment ago still reaches a page that was
    # already open.
    ARTIFACT_VIEW_TTL_SECONDS: int = Field(default=300, gt=0, le=3600)
    # Where artifact content is served from. Unset, it is the API's own public
    # address, and isolation rests on the `sandbox` policy every content
    # response carries, which gives the page an opaque origin. Set to a host on
    # a separate registrable domain that routes to this API, it also puts the
    # page on another site, which a security review may ask for.
    ARTIFACT_ORIGIN: str | None = None

    # What a *stranger* may upload to a hosted page, in megabytes. Its own
    # setting and much smaller, because the two callers are not comparable: a
    # member uploading a fifty-megabyte export is somebody the organization
    # employs, and the same allowance on a public link is a way to fill a disk
    # from an address nobody knows. It is a ceiling on top of the allowlist and
    # the chat path's own ceiling, never a way past either.
    EMBED_MAX_UPLOAD_SIZE_MB: int = 5
    # What one call to the standalone ML services may submit - a document to
    # parse, a scan to recognise, a recording to transcribe. Its own number
    # because the work is different in kind from storing a file: the bytes are
    # parsed or sent to an engine inside one request rather than written down,
    # so the ceiling is about what a single synchronous call may occupy. It sits
    # at the transcription client's own 25 MB, which is the smallest engine
    # ceiling behind this surface and so the first one a larger file would meet.
    ML_MAX_UPLOAD_SIZE_MB: int = 25
    # How many documents this worker parses at once for the ML services. The
    # rate limit counts starts and cannot see what is still running, so without
    # this a minute's allowance of OCR calls is that many recognitions in flight,
    # each of them minutes of CPU. Over it, a caller is refused with a
    # `Retry-After` rather than queued: a caller told to come back can, and one
    # parked behind four minutes of other people's scans has already given up.
    ML_MAX_CONCURRENT_PARSES: int = 4
    STORAGE_SOFT_LIMIT_BYTES: int = 5 * 1024 * 1024 * 1024

    # Size of the dedicated thread pool that runs blocking file work - parsing an
    # upload (pymupdf/openpyxl/docx) and reading or writing its bytes. Kept off
    # `asyncio`'s shared default executor, which the same loop also uses for
    # `bcrypt` password hashing and pinned-host DNS: a burst of uploads must not
    # occupy every worker there and leave sign-in and outbound requests queued
    # behind them (#1108). Tunable per deployment; the bound is what contains the
    # blast radius of a parse storm to this pool. `gt=0` so a misconfigured `0`
    # or negative is refused at startup rather than raising `ValueError` from
    # `ThreadPoolExecutor` on the first file operation.
    FILE_IO_MAX_WORKERS: int = Field(default=8, gt=0)

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
    # Encrypt the connection to Postgres. Empty leaves it plaintext, which is fine
    # for both stores on one compose network and is the first thing a reviewer asks
    # about for a managed Postgres or one on another host (HIPAA 164.312(e), SOC 2
    # CC6.7). `require` encrypts; `verify-ca`/`verify-full` also check the server's
    # certificate against the CA file `PGSSLROOTCERT` names - asyncpg and libpq
    # both read that variable, and neither consults the OS trust store (#1418).
    POSTGRES_SSLMODE: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:
        """Build async PostgreSQL connection URL."""
        url = (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )
        # asyncpg's parameter is `ssl`, not libpq's `sslmode`.
        return f"{url}?ssl={self.POSTGRES_SSLMODE}" if self.POSTGRES_SSLMODE else url

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL_SYNC(self) -> str:
        """Build sync PostgreSQL connection URL (for Alembic)."""
        url = (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )
        # psycopg2 speaks libpq, whose parameter is `sslmode`.
        return f"{url}?sslmode={self.POSTGRES_SSLMODE}" if self.POSTGRES_SSLMODE else url

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
    # How long a run may sit `running` before the sweep decides its process
    # died. The row is committed before the model is called (#12), so a worker
    # killed mid-run leaves it `running` with nothing left to finish it - in
    # Activity for ever, and blocking any trigger whose resume it was. Six
    # hours is far past anything this platform executes in one run, and the
    # ceiling does not have to be exact: a live run the sweep flips anyway is
    # flipped back by its own terminal write, which lands later and wins.
    # Zero or below switches the sweep off.
    STALE_RUN_REAPED_AFTER_HOURS: float = 6.0
    ALGORITHM: str = "HS256"
    FRONTEND_URL: str = "http://localhost:3000"
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    # The scheme the desktop shell registers for the sign-in return (#1532).
    #
    # Google's authorization endpoint refuses an embedded user-agent, and the
    # handoff it asks for is the system browser with the result deep-linked back
    # to the app. A setting rather than a query parameter, because the callback
    # builds a redirect out of it: a scheme a caller could choose would be an open
    # redirect into whatever URL handler that machine has registered.
    DESKTOP_DEEP_LINK_SCHEME: str = "agenticos"

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/oauth/google/callback"

    # A generic OpenID Connect provider - Entra ID, Okta, Keycloak, anything that
    # publishes a discovery document. A company deploying this on its own
    # infrastructure runs an identity provider and will not mint local passwords
    # for its staff; without this, its MFA and its offboarding are solved twice
    # (#1419). Configured by discovery alone: the issuer is the only URL, and the
    # authorization, token and JWKS endpoints come from
    # `<issuer>/.well-known/openid-configuration` rather than from three more
    # settings a deployment can get subtly wrong.
    OIDC_ISSUER: str = ""
    OIDC_CLIENT_ID: str = ""
    OIDC_CLIENT_SECRET: str = ""
    OIDC_REDIRECT_URI: str = "http://localhost:8000/api/v1/oauth/oidc/callback"
    # Beyond `openid email profile` a deployment may need its provider's own
    # scope to get the claims back - Entra ID's `User.Read`, a Keycloak client
    # scope. Space-separated, as the OAuth parameter itself is.
    OIDC_SCOPES: str = "openid email profile"
    # A provider's own name for "this address is confirmed", beyond the two
    # recognised already (`email_verified`, and Entra ID's `xms_edov`). Empty
    # unless a deployment's provider names it something else again.
    OIDC_VERIFIED_CLAIM: str = ""
    # The claim carrying the groups a person is in - `groups` for Entra ID,
    # Okta and a Keycloak group-membership mapper. Empty means OIDC sign-ins do
    # not touch memberships at all; set, each sign-in reconciles the person's
    # directory-managed memberships against the organizations' directory group
    # mappings (#1773). A claim that is configured but absent from a token is
    # read as "in no groups", because that is what the providers that omit an
    # empty list mean by it.
    OIDC_GROUPS_CLAIM: str = ""

    # Signing in with a directory account - Active Directory, OpenLDAP, FreeIPA -
    # by binding as it (#1773). Empty `LDAP_URL` switches it off and the sign-in
    # route answers 404, as an unconfigured OIDC issuer does. `ldaps://` is TLS
    # from the first byte; `ldap://` must either upgrade with StartTLS or be
    # allowed in plaintext explicitly, because a bind sends the password.
    LDAP_URL: str = ""
    LDAP_START_TLS: bool = False
    LDAP_ALLOW_PLAINTEXT: bool = False
    # A PEM bundle to verify the directory's certificate against, for a directory
    # signed by a company CA. Empty uses the system trust store.
    LDAP_CA_CERT_FILE: str = ""
    # The service account a sign-in searches with before binding as the person.
    # Both empty searches anonymously, which some directories allow and Active
    # Directory does not.
    LDAP_BIND_DN: str = ""
    LDAP_BIND_PASSWORD: str = ""
    LDAP_USER_BASE_DN: str = ""
    # `{username}` is what the person typed, escaped for a filter. The default
    # finds an account by any of the four names people sign in with.
    LDAP_USER_FILTER: str = (
        "(&(objectClass=person)(|(uid={username})(sAMAccountName={username})"
        "(userPrincipalName={username})(mail={username})))"
    )
    LDAP_EMAIL_ATTRIBUTE: str = "mail"
    LDAP_NAME_ATTRIBUTE: str = "displayName"
    # The account's stable identifier - `entryUUID` on OpenLDAP and FreeIPA,
    # `objectGUID` on Active Directory. The account is keyed on it rather than on
    # the address, for the reason OIDC is keyed on `sub`.
    LDAP_ID_ATTRIBUTE: str = "entryUUID"
    LDAP_GROUP_ATTRIBUTE: str = "memberOf"
    # For a directory without `memberOf`: search here for groups instead, with a
    # filter taking `{dn}` and `{username}`. Active Directory's nested groups are
    # `(member:1.2.840.113556.1.4.1941:={dn})`.
    LDAP_GROUP_BASE_DN: str = ""
    LDAP_GROUP_FILTER: str = "(member={dn})"
    # Whole seconds: `ldap3` packs the read timeout into a `timeval` with
    # `struct.pack('LL', ...)` on Linux and macOS, where a float fails every
    # connection with "required argument is not an integer".
    LDAP_TIMEOUT_SECONDS: int = Field(default=10, gt=0)

    # Integrated Windows sign-in: a browser on a domain-joined machine hands over
    # its Kerberos ticket through SPNEGO and nobody types a password (#1773). It
    # resolves the principal through the directory above, so it needs `LDAP_URL`,
    # and the `kerberos` extra for `gssapi`.
    KERBEROS_ENABLED: bool = False
    # The keytab holding this service's key. Empty uses the default keytab
    # (`KRB5_KTNAME`, else `/etc/krb5.keytab`).
    KERBEROS_KEYTAB: str = ""
    # `HTTP/agenticos.corp.example.com@CORP.EXAMPLE.COM`. Empty accepts a ticket
    # for any principal the keytab holds.
    KERBEROS_SERVICE_PRINCIPAL: str = ""
    # `{principal}` is the full `user@REALM`, `{username}` the part before `@`.
    LDAP_KERBEROS_FILTER: str = "(userPrincipalName={principal})"

    @model_validator(mode="after")
    def validate_directory_sign_in(self) -> "Settings":
        """A directory configuration that would send a password in the clear, or find nobody, is refused.

        Checked at startup rather than at the first sign-in: a typo here would
        otherwise surface as every person in the company being told their
        password is wrong.
        """
        if self.KERBEROS_ENABLED and not self.LDAP_URL:
            raise ValueError(
                "KERBEROS_ENABLED needs LDAP_URL - a ticket names a principal, and the "
                "directory is what turns it into an address and a set of groups"
            )
        if self.LDAP_URL and self.OIDC_GROUPS_CLAIM:
            # Each reports groups in its own identifiers - a DN from LDAP, an
            # object id or a path from OIDC - and the sync reconciles a person's
            # directory memberships against whichever signed them in, so
            # alternating sign-in methods would remove and recreate their access.
            raise ValueError(
                "Set LDAP_URL or OIDC_GROUPS_CLAIM, not both - two sources of directory "
                "groups would undo each other's memberships at every sign-in"
            )
        if not self.LDAP_URL:
            return self
        if not self.LDAP_URL.startswith(("ldap://", "ldaps://")):
            raise ValueError("LDAP_URL must start with ldaps:// or ldap://")
        if self.LDAP_URL.startswith("ldaps://") and self.LDAP_START_TLS:
            raise ValueError(
                "LDAP_START_TLS is for ldap:// - an ldaps:// connection is already TLS"
            )
        if (
            self.LDAP_URL.startswith("ldap://")
            and not self.LDAP_START_TLS
            and not self.LDAP_ALLOW_PLAINTEXT
        ):
            raise ValueError(
                "An ldap:// URL sends every sign-in's password in the clear. Use ldaps://, "
                "set LDAP_START_TLS=true, or set LDAP_ALLOW_PLAINTEXT=true to accept that"
            )
        if not self.LDAP_USER_BASE_DN:
            raise ValueError("LDAP_USER_BASE_DN is required when LDAP_URL is set")
        if "{username}" not in self.LDAP_USER_FILTER:
            raise ValueError("LDAP_USER_FILTER must contain {username}")
        if bool(self.LDAP_BIND_DN) != bool(self.LDAP_BIND_PASSWORD):
            raise ValueError("Set LDAP_BIND_DN and LDAP_BIND_PASSWORD together, or neither")
        if (
            self.LDAP_GROUP_BASE_DN
            and "{dn}" not in self.LDAP_GROUP_FILTER
            and ("{username}" not in self.LDAP_GROUP_FILTER)
        ):
            raise ValueError("LDAP_GROUP_FILTER must contain {dn} or {username}")
        if self.KERBEROS_ENABLED and not (
            "{principal}" in self.LDAP_KERBEROS_FILTER or "{username}" in self.LDAP_KERBEROS_FILTER
        ):
            raise ValueError("LDAP_KERBEROS_FILTER must contain {principal} or {username}")
        return self

    VAULT_MASTER_KEY: str = ""
    # Every master key the vault may unwrap with, by version - the staged form
    # for rotation: `{"1": "<old>", "2": "<new>"}` makes 2 the current version
    # while rows sealed under 1 stay readable until `agenticos cmd vault-rotate`
    # has re-wrapped them. When set it is the whole truth; the single
    # `VAULT_MASTER_KEY` above is shorthand for version 1.
    VAULT_MASTER_KEYS: dict[int, str] = {}

    @model_validator(mode="after")
    def validate_vault_master_keys(self) -> "Settings":
        """A deployment holding real credentials must say which key seals them.

        An unset master key falls back to `SECRET_KEY`, whose default is a
        string published in this repository - acceptable on a laptop, and a
        vault sealed under a public key everywhere else. Staging is a
        first-class deployment here, so the refusal covers it too, not only
        production (#8).
        """
        if self.VAULT_MASTER_KEY and self.VAULT_MASTER_KEYS:
            raise ValueError(
                "Set either VAULT_MASTER_KEY or VAULT_MASTER_KEYS, not both - two sources "
                "for the current master key make it ambiguous which one seals new secrets"
            )
        for version, key in self.VAULT_MASTER_KEYS.items():
            if version < 1:
                raise ValueError("VAULT_MASTER_KEYS versions must be positive integers")
            if not key:
                raise ValueError(f"VAULT_MASTER_KEYS[{version}] must not be empty")
        if self.ENVIRONMENT not in ("local", "development") and not (
            self.VAULT_MASTER_KEY or self.VAULT_MASTER_KEYS
        ):
            raise ValueError(
                "VAULT_MASTER_KEY must be set outside local/development - without it the "
                "vault falls back to SECRET_KEY. Generate one with: openssl rand -hex 32"
            )
        return self

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
    # Encrypt the connection to Redis. redis-py reads TLS off the URL scheme, so
    # this switches `redis://` for `rediss://`, and the URL also demands a valid
    # chain and a matching hostname - stated rather than left to redis-py's
    # defaults, which have flipped between releases. The CA is whatever bundle
    # OpenSSL trusts, so a private one is named with `SSL_CERT_FILE` (#1418).
    REDIS_SSL: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_URL(self) -> str:
        """Build Redis connection URL."""
        scheme = "rediss" if self.REDIS_SSL else "redis"
        verify = "?ssl_cert_reqs=required&ssl_check_hostname=true" if self.REDIS_SSL else ""
        if self.REDIS_PASSWORD:
            return (
                f"{scheme}://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}"
                f"/{self.REDIS_DB}{verify}"
            )
        return f"{scheme}://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}{verify}"

    # What one caller may ask the public run API for, per minute. Keyed on the
    # caller rather than on their address: the endpoint is authenticated, and an
    # office behind one NAT is not one caller.
    RATE_LIMIT_RUN_PER_MINUTE: int = 30
    # How often one caller may ask for a personal-data export, per hour rather
    # than per minute. It is the one route that assembles everything about a
    # person into a single document, which is the shape of a data breach when
    # the caller is not who they claim to be - and nobody legitimately needs it
    # twice in a day. Low enough that a stolen session cannot quietly walk the
    # deployment's people, high enough that a person retrying a failed download
    # is not locked out (#1421).
    RATE_LIMIT_EXPORT_PER_HOUR: int = 5
    # How much conversation text one personal-data export may carry, in
    # characters. The document is assembled and serialized whole, and a message
    # has no length ceiling of its own, so without this the caller decides how
    # much memory a worker spends and five concurrent exports of a thread
    # somebody has been filling take the container with them. Roughly 16 MB of
    # text, which is far more than any real transcript and far less than the
    # 2560 MB the shipped container has (#1421).
    PERSONAL_DATA_EXPORT_MAX_CHARS: int = 16_000_000
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
    # How many ML service calls one caller gets per minute. These are the
    # heaviest synchronous endpoints on the API - an OCR pass is CPU-bound
    # seconds on a thread, a transcription is a call to somebody else's engine -
    # so the ceiling is about what one integration can do to a worker, not about
    # what a stranger can reach: this surface is authenticated.
    RATE_LIMIT_ML_PER_MINUTE: int = 30
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
    # A floor under every scheduled interval, for a machine that is not a server.
    #
    # Four deployments tick every sixty seconds - the trigger heartbeat, the RAG
    # sync check, the portal poll and the notification delivery sweep. On a
    # deployment that is the point of them: a schedule that fires a minute late
    # is a schedule nobody trusts. On a laptop running the whole stack beside an
    # editor it is four fresh Python processes a minute, each importing the
    # application before doing about two tenths of a second of work, and the
    # import is what costs - measured at roughly seven seconds a run, four at a
    # time.
    #
    # `0` changes nothing and is the default, so a deployment keeps the
    # intervals the code declares. Raising it lengthens only the schedules
    # already faster than it, which is why this is a floor rather than a
    # multiplier: at 600 the four minute-ticks become ten minutes and the
    # fifteen-minute, hourly and daily sweeps are untouched. `make dev` sets it;
    # see `docs/configuration.md`.
    WORKER_MIN_INTERVAL_SECONDS: int = Field(default=0, ge=0)

    # Nothing about embeddings or parsing is a setting. The model, the provider
    # and the vault key that pays are recorded on the collection; where a local
    # embedding or OCR server answers is a `local_services` row an organization
    # (or the deployment's administrator) registers in the product; a LlamaParse
    # key is a vault entry the collection's ingestion configuration names. Each
    # of these was an environment variable once, and each was one address or one
    # key for every tenant, visible to none of them.

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
    # Where uploaded files live: chat attachments, avatars, branding images and
    # the original of every knowledge-base document. `local` is the default and
    # writes under `MEDIA_DIR`, which is honest for a single host with an
    # encrypted volume and stops being enough at the second API replica or the
    # first client who wants their own KMS key (#1423).
    #
    # This is a deployment-time choice, not a per-organization one, and it does
    # not migrate what the other backend already holds.
    FILE_STORAGE_BACKEND: Literal["local", "s3"] = "local"
    FILE_STORAGE_S3_BUCKET: str = ""
    # Empty for AWS; the address of the service for MinIO or another
    # S3-compatible store.
    FILE_STORAGE_S3_ENDPOINT: str | None = None
    FILE_STORAGE_S3_REGION: str = "us-east-1"
    # Left empty, boto3's own credential chain answers - an instance profile, an
    # IRSA role, `~/.aws/credentials` - which is what a deployment on AWS should
    # be using rather than a key pair in an environment file.
    FILE_STORAGE_S3_ACCESS_KEY: str = ""
    FILE_STORAGE_S3_SECRET_KEY: str = ""
    # MinIO and most compatible stores address a bucket by path rather than by
    # subdomain, and a virtual-host request to one fails DNS rather than S3.
    FILE_STORAGE_S3_PATH_STYLE: bool = False
    # Every key this deployment writes sits under this prefix, so one bucket can
    # hold more than one deployment without their keys meeting.
    FILE_STORAGE_S3_PREFIX: str = ""
    # Server-side encryption asked of the store on every write. `sse-s3` is the
    # bucket's own key, `sse-kms` the key named below - the one a client brings.
    # `none` exists because MinIO refuses SSE-S3 without a KES server behind it,
    # so a compatible store with no KMS has somewhere to be; `doctor` reports it
    # as unconfigured rather than healthy.
    FILE_STORAGE_S3_ENCRYPTION: Literal["sse-s3", "sse-kms", "none"] = "sse-s3"
    # Required when the mode is `sse-kms`, and refused empty there. An unnamed
    # `aws:kms` is not the bucket's default key: S3 reads it as its own
    # AWS-managed `aws/s3`, so a deployment that asked for a client-held key and
    # named none would encrypt under a key nobody chose and be told nothing.
    FILE_STORAGE_S3_KMS_KEY_ID: str | None = None
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
    # `auto` lets the port choose: 465 opens TLS from the first byte, anything
    # else upgrades with STARTTLS. A server speaking implicit TLS on a port other
    # than 465 (8465, 2465) needs `implicit` spelled out, or the provider offers a
    # plaintext handshake to a TLS socket and every send fails.
    SMTP_TLS_MODE: SmtpTlsMode = "auto"
    LOG_PROVIDER_WRITE_TO_DISK: bool = False

    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:8080",
    ]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: list[str] = ["*"]
    CORS_ALLOW_HEADERS: list[str] = ["*"]

    # Without an allowlist a builder who can bind a shared mem0 key could point
    # `mem0_base_url` at their own server and capture it (docs/secrets.md).
    MEM0_ALLOWED_HOSTS: list[str] = []

    # Hosts a browsing agent may drive a Chromium at. `cdp_url` lives in an agent
    # spec, which anyone holding `edit` on that agent writes - so it is
    # tenant-controlled, and an unbounded one is a request this deployment makes
    # to any address the author names. The SSRF guard is the wrong control for it:
    # it admits only *public* addresses, which refuses the isolated browser
    # service on the deployment's own network that `docs/reference/capabilities.md`
    # tells an operator to run, and accepts a CDP debugger exposed to the
    # internet, which is worse. So the operator names the hosts instead, exactly
    # as `MEM0_ALLOWED_HOSTS` does. Empty refuses browser automation outright.
    BROWSER_CDP_ALLOWED_HOSTS: list[str] = []

    # Where a browsing agent's decision model may run, beyond the vendor's own
    # endpoint. `decision_base_url` is in the agent spec and the vault key is
    # unsealed and handed to that address, so an author who may *bind* a shared
    # TypeSafe key - without being able to read it - could point it at a server
    # of their own and collect it from the request header. This is
    # `MEM0_ALLOWED_HOSTS` again, one field along, and the answer is the same
    # one. Empty allows only the vendor endpoint, which is the default and the
    # configuration nobody has to think about.
    DECISION_MODEL_ALLOWED_HOSTS: list[str] = []

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
        """The RAG settings with nothing of the deployment's in them.

        There is no deployment-level half any more: the embedding model, the
        provider and the key are the collection's, and so are the parser and
        the addresses it reaches. Everything about *how a document is read*
        arrives via :func:`app.services.ingestion_config.rag_settings_for`, which
        builds this same object from the collection's stored configuration; this
        one is what a caller with no collection in hand - the warmup, a `rag-*`
        command - gets, and it embeds nothing.
        """
        return RAGSettings()


# Rebuild Settings to resolve RAGSettings forward reference
from app.services.rag.config import RAGSettings

Settings.model_rebuild()


settings = Settings()
