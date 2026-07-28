"""Provider credentials and model profiles — storage, validation, resolution.

The one place that unseals a provider credential. Everything above it deals in
profile ids; everything below deals in ciphertext.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.model_resolver import (
    PROVIDERS,
    ModelRequestSpec,
    ProviderSpec,
    ResolvedCredential,
    get_provider,
)
from app.core.audit import record_audit
from app.core.config import settings
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.core.sanitize import SSRFBlockedError, validate_webhook_url
from app.core.secret_kinds import (
    SecretKind,
    unseal_secret,
)
from app.core.vault import VaultScope
from app.db.models.credential import ModelProfile
from app.repositories import credential_repo, organization_secret_repo

logger = logging.getLogger(__name__)

# A fallback chain longer than this is a configuration mistake, not a strategy:
# every hop costs a failed request before the next is tried.
MAX_FALLBACK_DEPTH = 3

_ALLOWED_ENDPOINT_SCHEMES = frozenset({"http", "https"})


def _validate_model_id(provider: str, model: str) -> None:
    """Reject model ids a provider cannot parse, at configuration time.

    OpenRouter namespaces every model (``openai/gpt-4.1``) and fails on a bare
    id with ``ValueError: not enough values to unpack`` — deep inside a run,
    with nothing pointing at the profile that caused it. Catching it here costs
    one comparison and turns a baffling run-time crash into a form error.
    """
    if provider == "openrouter" and "/" not in model:
        raise BadRequestError(
            message="OpenRouter model ids are namespaced, e.g. 'openai/gpt-4.1'",
            details={"model": model},
        )


async def validate_endpoint_url(url: str) -> str:
    """Check a provider ``base_url`` before the platform will store it.

    Everywhere else — webhooks, MCP servers — an internal address is an SSRF
    attempt and is refused. Here it is frequently the entire point: Ollama on
    ``localhost:11434``, a vLLM server on the deployment's own network, a
    LiteLLM proxy beside the API. Refusing those would remove the feature; not
    checking at all would let any member with ``connections:manage`` turn the
    backend into a probe for the internal network.

    So it is a deployment decision, stated explicitly:
    ``ALLOW_INTERNAL_MODEL_ENDPOINTS`` opens private, loopback and link-local
    addresses to model profiles and nothing else. It defaults to off, so a
    hosted deployment is safe without anyone thinking about it, and a
    self-hosted one turns it on once.

    The scheme and userinfo checks apply either way — ``file://`` is never a
    model endpoint, and credentials in a URL are an ambiguity we do not need.

    Raises:
        BadRequestError: If the URL is malformed, uses another scheme, carries
            credentials, or points inside the network on a deployment that has
            not allowed that.
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_ENDPOINT_SCHEMES:
        raise BadRequestError(
            message="A model endpoint must be an http or https URL",
            details={"base_url": url},
        )
    if not parsed.hostname:
        raise BadRequestError(
            message="A model endpoint must include a host", details={"base_url": url}
        )
    if parsed.username is not None or parsed.password is not None:
        raise BadRequestError(
            message=(
                "A model endpoint must not carry credentials in the URL — store the key "
                "on the credential instead"
            ),
            details={"base_url": url},
        )
    if settings.ALLOW_INTERNAL_MODEL_ENDPOINTS:
        return url
    try:
        # Resolves DNS, so it runs in a thread — same as the MCP URL check.
        return await asyncio.to_thread(validate_webhook_url, url)
    except SSRFBlockedError as exc:
        raise BadRequestError(
            message=(
                "This endpoint is on an internal network. A self-hosted deployment can "
                "allow that with ALLOW_INTERNAL_MODEL_ENDPOINTS=true; a shared one should "
                "not, because any member who can add a key could then reach its network."
            ),
            details={"base_url": url},
        ) from exc


def provider_catalog() -> list[ProviderSpec]:
    """Every provider a key can be stored for, ordered for a stable picker.

    Sorted by display name, case-insensitively: the select that renders this is
    thirty-one rows long, and an order that shifts between deployments is one
    nobody can build muscle memory against.
    """
    return sorted(PROVIDERS.values(), key=lambda spec: spec.name.lower())


class ModelProfileService:
    """Manage an organization's provider credentials and selectable models."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # -- credentials ----------------------------------------------------

    async def list_profiles(self, ctx: AuthContext) -> list[ModelProfile]:
        return await credential_repo.list_profiles(self.db, organization_id=ctx.organization_id)

    async def create_profile(
        self,
        ctx: AuthContext,
        *,
        label: str,
        provider: str,
        model: str,
        secret_id: UUID,
        params: dict | None = None,
        allow_byo: bool = False,
        fallback_profile_ids: list[UUID] | None = None,
    ) -> ModelProfile:
        """Define a selectable model.

        Raises:
            BadRequestError: If the key is not this organization's, or is for a
                different provider than the profile claims — a mismatch that
                would otherwise surface as an authentication error from the
                provider, days later and far from its cause.
            AlreadyExistsError: If the label is taken. Agents reference a model
                by this name, so a duplicate is an agent nobody can point at
                the model they meant.
        """
        get_provider(provider)
        _validate_model_id(provider, model)

        if await credential_repo.get_profile_by_label(
            self.db, label, organization_id=ctx.organization_id
        ):
            raise AlreadyExistsError(
                message=(
                    f"A model named '{label}' already exists. Agents pick a model by this name, "
                    "so it has to be unique — name this one for what makes it different, or "
                    "delete the existing model if you meant to replace it."
                ),
                details={"label": label},
            )

        # The key has to exist and be for the provider the model claims: a
        # Tavily key behind an OpenAI model authenticates against nothing.
        secret = await organization_secret_repo.get(
            self.db, secret_id, organization_id=ctx.organization_id
        )
        if secret is None:
            raise BadRequestError(
                message="That key is not in this organization's vault",
                details={"secret_id": str(secret_id)},
            )
        if secret.purpose != provider:
            raise BadRequestError(
                message=f"That key is for {secret.purpose}, not {provider}",
                details={"secret_purpose": secret.purpose, "provider": provider},
            )

        profile = await credential_repo.create_profile(
            self.db,
            organization_id=ctx.organization_id,
            label=label,
            provider=provider,
            model=model,
            secret_id=secret_id,
            params=params,
            allow_byo=allow_byo,
            fallback_profile_ids=[str(pid) for pid in (fallback_profile_ids or [])],
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="model_profile.created",
            target_type="model_profile",
            target_id=str(profile.id),
            details={"label": label, "provider": provider, "model": model},
        )
        return profile

    async def delete_profile(self, ctx: AuthContext, profile_id: UUID) -> None:
        deleted = await credential_repo.delete_profile(
            self.db, profile_id, organization_id=ctx.organization_id
        )
        if not deleted:
            raise NotFoundError(
                message="Model profile not found", details={"profile_id": str(profile_id)}
            )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="model_profile.deleted",
            target_type="model_profile",
            target_id=str(profile_id),
        )

    # -- resolution -----------------------------------------------------

    async def _resolve_credential(
        self, organization_id: UUID, profile: ModelProfile
    ) -> ResolvedCredential:
        """The key this model runs on, from whichever store holds it.

        A vault secret first: that is the one people manage, and picking
        "OpenRouter" there is what makes OpenRouter's models runnable. A legacy
        `credential` is the fallback, so profiles created before the two stores
        were joined keep working without a migration that rewrites them.
        """
        if profile.secret_id is None:
            raise BadRequestError(
                message=f"Model '{profile.label}' has no key configured — add one in the vault",
                details={"profile_id": str(profile.id)},
            )
        secret = await organization_secret_repo.get(
            self.db, profile.secret_id, organization_id=organization_id
        )
        if secret is None:
            raise BadRequestError(
                message=f"Model '{profile.label}' points at a key this organization no longer has",
                details={"profile_id": str(profile.id)},
            )
        return ResolvedCredential(
            provider=profile.provider,
            secret=unseal_secret(
                secret.sealed_secret,
                kind=SecretKind(secret.kind),
                scope=VaultScope.organization(organization_id),
                key_version=secret.key_version,
            ),
            # A vault secret carries no endpoint: a custom base URL belongs to
            # the deployment's own server, which is what the keyless provider
            # path is for.
            base_url=None,
        )

    async def resolve(
        self,
        ctx: AuthContext,
        *,
        profile_id: UUID | None = None,
    ) -> ModelRequestSpec:
        """Resolve the model a run should use, credentials included."""
        return await self.resolve_for_organization(ctx.organization_id, profile_id=profile_id)

    async def resolve_for_organization(
        self,
        organization_id: UUID,
        *,
        profile_id: UUID | None = None,
    ) -> ModelRequestSpec:
        """The same resolution, for work that has an organization but no caller.

        Which model an organization runs on is a fact about that organization,
        not a permission decision — nothing here consults a role, and the
        request that *was* authorized may have finished hours ago. Background
        ingestion is the case: a document is parsed by a worker long after the
        upload that was allowed, and it still has to reach the same profile and
        unseal the same key. Taking the organization directly says that plainly,
        instead of inventing a caller for the sake of a signature.

        Precedence, most specific first: the profile that was asked for, then
        the organization's default. There is deliberately no environment
        fallback — a deployment serving several tenants must never quietly bill
        one organization's run to a platform-wide key.

        Raises:
            NotFoundError: If neither a named profile nor a default exists.
        """
        profile = None
        if profile_id is not None:
            profile = await credential_repo.get_profile(
                self.db, profile_id, organization_id=organization_id
            )
            if profile is None:
                raise NotFoundError(
                    message="Model profile not found", details={"profile_id": str(profile_id)}
                )
        else:
            # No fallback to "the organization's default". A model an agent did
            # not choose is a model somebody else's change can swap underneath
            # it — the same spec answering on a different model, at a different
            # price, because a flag moved on another page. An agent names its
            # model, and publish validation refuses a spec that does not.
            raise NotFoundError(
                message="This agent has no model selected",
            )

        credential = await self._resolve_credential(organization_id, profile)

        fallbacks: list[tuple[ResolvedCredential, str]] = []
        fallback_ids = [UUID(pid) for pid in profile.fallback_profile_ids[:MAX_FALLBACK_DEPTH]]
        if fallback_ids:
            by_id = await credential_repo.get_profiles_by_ids(
                self.db, fallback_ids, organization_id=organization_id
            )
            for fallback_id in fallback_ids:
                fallback = by_id.get(fallback_id)
                if fallback is None:
                    # A deleted fallback should degrade the chain, not the run.
                    logger.warning(
                        "Model profile %s lists missing fallback %s", profile.id, fallback_id
                    )
                    continue
                try:
                    fallbacks.append(
                        (await self._resolve_credential(organization_id, fallback), fallback.model)
                    )
                except BadRequestError:
                    logger.warning(
                        "Fallback profile %s is not usable; skipping", fallback.id, exc_info=True
                    )

        return ModelRequestSpec(
            profile_id=profile.id,
            label=profile.label,
            provider=profile.provider,
            model=profile.model,
            params=dict(profile.params),
            credential=credential,
            secret_id=profile.secret_id,
            fallbacks=fallbacks,
        )
