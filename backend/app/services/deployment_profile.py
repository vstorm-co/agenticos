"""Whether a running deployment matches an opinionated security profile.

A client's security review does not ask "is this software compliant" - HHS
certifies no software and OCR recognises no private certification. It asks
*can we run this inside our compliant environment, and can you prove it*. The
answer used to be a conversation; this makes it a configuration plus a command
(#1448).

**What a profile is.** A named set of controls, each one a question this code
can put to the running deployment and answer from its settings and its database.
Not a claim, not a certificate: a sheet a security officer can read, with the
setting that satisfies each control named, or the one that does not.

**What it is not.** The HIPAA profile answers the **technical** safeguards,
§164.312, and only those. Administrative (§164.308 - risk analysis, workforce
training, sanction policy, contingency plan, business associate agreements) and
physical (§164.310) safeguards belong to the operator and always will. Anything
here that implied otherwise would be a claim nobody can support.

Three outcomes and the middle one carries weight. `met` and `unmet` are this
code's; `attested` is a control that is genuinely the operator's - volume
encryption, a locked rack - which the sheet names rather than silently passing,
because a profile that quietly skipped what it cannot see would be a sheet that
reads as complete and is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from typing import Final, Literal
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.audit_checkpoint import AppAdminAuditCheckpoint
from app.db.models.credential import ModelProfile
from app.db.models.deployment_settings import DeploymentSettings

#: Six years, which is what §164.316(b)(2) asks of an audit record.
#:
#: The number a deployment's own audit floor is measured against. Per-organization
#: retention (#1420) carries the same figure as its built-in floor; when both have
#: landed one of the two should import the other rather than restating it.
AUDIT_FLOOR_DAYS = 2190

Outcome = Literal["met", "unmet", "attested"]

ProfileName = Literal["hipaa"]

#: Host suffixes a model request may reach without leaving the operator's network.
#:
#: Matched against the **hostname**, and as a suffix or an exact name - never as
#: a substring of the whole URL. `https://ollama.vendor.example/v1` contains
#: "ollama" and leaves the network; so does `https://api.internal.attacker.example`
#: (#1448 review). A private address is recognised separately, because an IP
#: literal has no suffix to match.
_LOCAL_NAMES: Final = frozenset({"localhost", "ollama", "litellm", "vllm"})
_LOCAL_SUFFIXES: Final = (".local", ".internal", ".svc", ".svc.cluster.local")


def _is_local_host(url: str) -> bool:
    """Whether this endpoint is served from the operator's own network.

    Parsed rather than searched. A hostname that *is* one of the known
    single-label service names, that ends in one of the internal suffixes, or
    that is a private, loopback or link-local address stays inside; anything else
    - including a public host with `ollama` somewhere in its name - does not.
    """
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if not host:
        return False
    if host in _LOCAL_NAMES or host.endswith(_LOCAL_SUFFIXES):
        return True
    try:
        address = ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


@dataclass(frozen=True)
class ControlResult:
    """One row of the sheet."""

    key: str
    """A stable identifier, so a client's CI can grep for one."""

    safeguard: str
    """The citation this control answers, for the person reading the sheet."""

    outcome: Outcome
    detail: str
    """What satisfies it, or what does not - naming the setting either way."""

    @property
    def failed(self) -> bool:
        """Whether this row should make the command exit non-zero.

        An attested control does not: it is the operator's to evidence, and a
        command that failed on one would be a command nobody could ever pass.
        """
        return self.outcome == "unmet"


def _met(key: str, safeguard: str, detail: str) -> ControlResult:
    return ControlResult(key=key, safeguard=safeguard, outcome="met", detail=detail)


def _unmet(key: str, safeguard: str, detail: str) -> ControlResult:
    return ControlResult(key=key, safeguard=safeguard, outcome="unmet", detail=detail)


def _attested(key: str, safeguard: str, detail: str) -> ControlResult:
    return ControlResult(key=key, safeguard=safeguard, outcome="attested", detail=detail)


async def evaluate(db: AsyncSession, profile: ProfileName) -> list[ControlResult]:
    """Every control of `profile`, against this deployment, in reading order."""
    row = await db.scalar(select(DeploymentSettings).limit(1))
    return [
        _postgres_in_transit(),
        _redis_in_transit(),
        _browser_in_transit(),
        _credentials_at_rest(),
        _content_at_rest(),
        await _model_requests_stay_here(db),
        await _traces_carry_no_content(db),
        _who_may_sign_in(row),
        _sign_up_is_closed(row),
        _audit_is_kept_six_years(row),
        await _audit_is_tamper_evident(db),
    ]


def _postgres_in_transit() -> ControlResult:
    """§164.312(e)(1). A verified certificate for *this host*, not merely an encrypted socket."""
    mode = settings.POSTGRES_SSLMODE
    if mode == "verify-full":
        return _met("postgres-tls", "§164.312(e)(1)", "POSTGRES_SSLMODE=verify-full")
    if mode == "verify-ca":
        return _unmet(
            "postgres-tls",
            "§164.312(e)(1)",
            "POSTGRES_SSLMODE=verify-ca validates the chain and not the hostname, so a "
            "server holding any certificate from the same CA satisfies it; the profile "
            "asks for verify-full",
        )
    if mode == "require":
        return _unmet(
            "postgres-tls",
            "§164.312(e)(1)",
            "POSTGRES_SSLMODE=require encrypts but verifies no certificate; "
            "the profile asks for verify-full",
        )
    return _unmet(
        "postgres-tls", "§164.312(e)(1)", "POSTGRES_SSLMODE is unset: the link is plaintext"
    )


def _redis_in_transit() -> ControlResult:
    """§164.312(e)(1). Redis carries queued work and cached answers."""
    if settings.REDIS_SSL:
        return _met("redis-tls", "§164.312(e)(1)", "REDIS_SSL=true, with hostname verification")
    return _unmet("redis-tls", "§164.312(e)(1)", "REDIS_SSL is off: the link is plaintext")


#: The shortest master key the profile accepts, in characters.
#:
#: `openssl rand -hex 32` is what the documentation tells an operator to run, and
#: that is 64. HKDF derives a correctly sized wrapping key from anything, but it
#: cannot put entropy into a secret that has none - so a one-character key
#: produces ciphertext an attacker recovers, under a sheet reporting the
#: credentials protected (#1448 review).
MIN_MASTER_KEY_CHARS: Final = 64


def _credentials_at_rest() -> ControlResult:
    """§164.312(a)(2)(iv). Every stored credential is sealed per organization."""
    keys = [settings.VAULT_MASTER_KEY, *settings.VAULT_MASTER_KEYS.values()]
    configured = [key for key in keys if key]
    if not configured:
        return _unmet(
            "vault-key",
            "§164.312(a)(2)(iv)",
            "no VAULT_MASTER_KEY: the vault cannot seal anything",
        )
    weak = sum(1 for key in configured if len(key) < MIN_MASTER_KEY_CHARS)
    if weak:
        return _unmet(
            "vault-key",
            "§164.312(a)(2)(iv)",
            f"{weak} of {len(configured)} master key(s) are shorter than "
            f"{MIN_MASTER_KEY_CHARS} characters. HKDF derives a correctly sized "
            "wrapping key from anything and cannot add entropy to a guessable one; "
            "generate with `openssl rand -hex 32`",
        )
    return _met(
        "vault-key",
        "§164.312(a)(2)(iv)",
        f"{len(configured)} master key(s) of full length, so provider and connector "
        "credentials are sealed per organization",
    )


def _browser_in_transit() -> ControlResult:
    """§164.312(e)(1), for the hop the other rows do not cover.

    Store and model transport were checked and the browser's was not, so every
    other row could pass while a sign-in, a prompt and its answer crossed the
    client boundary in plaintext (#1448 review). What this can see is the
    addresses this deployment publishes to that browser; terminating TLS is the
    operator's proxy, and is attested rather than claimed.
    """
    published = {
        "FRONTEND_URL": settings.FRONTEND_URL,
        "PUBLIC_BASE_URL": settings.PUBLIC_BASE_URL,
    }
    plaintext = sorted(name for name, url in published.items() if not url.startswith("https://"))
    if plaintext:
        return _unmet(
            "browser-tls",
            "§164.312(e)(1)",
            f"{', '.join(plaintext)} is an http:// address, so the browser reaches "
            "this deployment in plaintext",
        )
    return _attested(
        "browser-tls",
        "§164.312(e)(1)",
        "every published address is https, and `Strict-Transport-Security` is sent "
        "in a production build. Terminating TLS, and the certificate it presents, "
        "is the operator's reverse proxy",
    )


def _content_at_rest() -> ControlResult:
    """§164.312(a)(2)(iv), and the operator's.

    The application does not encrypt Postgres data, uploaded files or the sandbox
    workspace root; a volume or a disk does. Named rather than passed, because a
    sheet that quietly skipped what this code cannot see would read as complete
    and would not be.
    """
    return _attested(
        "content-at-rest",
        "§164.312(a)(2)(iv)",
        "volume or disk encryption for Postgres, the media volume and the sandbox "
        "workspace root is the operator's to configure and to evidence",
    )


async def _model_requests_stay_here(db: AsyncSession) -> ControlResult:
    """§164.312(e)(1). A request to a hosted model takes the content with it.

    Every model profile on the deployment, not a default: there is no
    deployment-wide default to check - a profile belongs to an organization, and
    any one of them can carry a run's content. A profile with no `base_url` is
    the provider's public API by definition.

    The profile's answer is local inference, which also sidesteps the business
    associate agreement a hosted vendor would need - and the narrower scope such
    an agreement usually has, where code execution and web fetch are excluded.
    """
    profiles = (await db.execute(select(ModelProfile))).scalars().all()
    if not profiles:
        return _attested(
            "local-model",
            "§164.312(e)(1)",
            "no model profile is configured yet, so nothing says where a run's content would go",
        )
    remote = sorted(
        profile.label for profile in profiles if not _is_local_host(profile.base_url or "")
    )
    if remote:
        shown = ", ".join(remote[:5]) + (", ..." if len(remote) > 5 else "")
        return _unmet(
            "local-model",
            "§164.312(e)(1)",
            f"{len(remote)} model profile(s) reach a third party: {shown}",
        )
    return _met(
        "local-model",
        "§164.312(e)(1)",
        f"all {len(profiles)} model profile(s) are served from this deployment's own network",
    )


async def _traces_carry_no_content(db: AsyncSession) -> ControlResult:
    """§164.312(e)(1). A trace with `content: full` copies the run off the machine.

    The deployment's own token is not the whole question. An agent's
    `observability.token_secret_id` and a named environment's
    `logfire_token_secret_id` each attach an exporter of their own, and the
    content mode still defaults to `full` - so a deployment with no
    `LOGFIRE_TOKEN` could report that nothing leaves while run content was being
    exported per agent (#1448 review). Both are read, and the *published* spec is
    what is read from an agent, because that is what runs.
    """
    if settings.LOGFIRE_TOKEN:
        return _unmet(
            "traces-local",
            "§164.312(e)(1)",
            "LOGFIRE_TOKEN is set: spans reach a hosted project, and an agent's "
            "observability.content defaults to 'full'",
        )

    exporting = await _agents_exporting_traces(db)
    environments = await db.scalar(
        select(func.count())
        .select_from(AgentEnvironment)
        .where(AgentEnvironment.logfire_token_secret_id.is_not(None))
    )
    if exporting or environments:
        return _unmet(
            "traces-local",
            "§164.312(e)(1)",
            f"LOGFIRE_TOKEN is unset, but {len(exporting)} published agent(s) and "
            f"{environments or 0} environment(s) carry a tracing token of their own, "
            "and observability.content defaults to 'full'",
        )
    return _met(
        "traces-local",
        "§164.312(e)(1)",
        "no deployment token, no per-agent token and no per-environment token, so no "
        "span leaves this deployment",
    )


async def _agents_exporting_traces(db: AsyncSession) -> list[str]:
    """Published agents whose own spec attaches a tracing exporter, with full content."""
    rows = await db.execute(
        select(Agent.name, AgentVersion.spec).join(
            AgentVersion, Agent.current_version_id == AgentVersion.id
        )
    )
    named: list[str] = []
    for name, spec in rows.all():
        observability = spec.get("observability") if isinstance(spec, dict) else None
        if not isinstance(observability, dict) or not observability.get("token_secret_id"):
            continue
        if observability.get("content") != "none":
            named.append(name)
    return named


def sso_issuer() -> str:
    """The identity provider this deployment signs people in through, if any.

    The same two settings `app.core.oauth._oidc` requires, and for the reason
    the sheet exists: with an issuer but no client id that function returns
    `None` and the sign-in route answers 404, so a control reading "met" off the
    issuer alone would attest a sign-in nobody can perform. Empty is the honest
    answer for a deployment that configured none, and what makes the control read
    unmet rather than unknown: generic OIDC sign-in exists (#1419), so an unset
    issuer is a choice rather than a missing feature.
    """
    if not settings.OIDC_CLIENT_ID:
        return ""
    return str(settings.OIDC_ISSUER or "")


def _who_may_sign_in(row: DeploymentSettings | None) -> ControlResult:
    """§164.312(d). Person or entity authentication.

    The profile asks for the identity provider the operator already runs, because
    multi-factor authentication is that provider's job and a password this
    deployment stores is one more credential to govern.
    """
    if sso_issuer():
        return _met(
            "sso",
            "§164.312(d)",
            "OIDC_ISSUER is set; multi-factor authentication is the provider's",
        )
    return _unmet(
        "sso",
        "§164.312(d)",
        "no OIDC_ISSUER: people sign in with passwords this deployment stores",
    )


def _sign_up_is_closed(row: DeploymentSettings | None) -> ControlResult:
    """§164.312(a)(1). Access control begins with who gets an account at all."""
    mode = getattr(row, "signup_mode", "open") if row is not None else "open"
    if mode in {"invite_only", "closed"}:
        return _met("signup", "§164.312(a)(1)", f"signup_mode={mode}")
    return _unmet(
        "signup",
        "§164.312(a)(1)",
        "signup_mode=open: anybody reaching the sign-in page can create an account",
    )


def _audit_is_kept_six_years(row: DeploymentSettings | None) -> ControlResult:
    """§164.312(b), with §164.316(b)(2)'s six years as the number."""
    floor = getattr(row, "audit_retention_floor_days", None) if row is not None else None
    effective = floor if floor is not None else AUDIT_FLOOR_DAYS
    if effective >= AUDIT_FLOOR_DAYS:
        return _met(
            "audit-retention",
            "§164.312(b)",
            f"audit entries are kept at least {effective} days, and an organization "
            "may lengthen that and never shorten it",
        )
    return _unmet(
        "audit-retention",
        "§164.312(b)",
        f"the audit floor is {effective} days; §164.316(b)(2) asks for {AUDIT_FLOOR_DAYS}",
    )


async def _audit_is_tamper_evident(db: AsyncSession) -> ControlResult:
    """§164.312(c)(1). Integrity - can somebody tell if the trail was edited.

    Detection rather than prevention, and the sheet says so: a chain and a
    checkpoint catch an edit, a reorder, an insert and a truncation, and anybody
    holding this database's own credentials can remove both.
    """
    checkpoints = await db.scalar(select(func.count()).select_from(AppAdminAuditCheckpoint))
    if checkpoints:
        return _met(
            "audit-chain",
            "§164.312(c)(1)",
            f"{checkpoints} audit chain(s) carry a hash chain and a checkpoint; "
            "verify with `agenticos cmd audit-verify`",
        )
    return _attested(
        "audit-chain",
        "§164.312(c)(1)",
        "the chain is in place but nothing has been recorded yet, so there is nothing to verify",
    )
