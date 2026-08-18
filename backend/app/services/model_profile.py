"""Provider credentials and model profiles - storage, validation, resolution.

The one place that unseals a provider credential. Everything above it deals in
profile ids; everything below deals in ciphertext.
"""

from __future__ import annotations

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
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
from app.core.secret_kinds import (
    NoSecret,
    SecretKind,
    unseal_secret,
)
from app.core.vault import VaultScope
from app.db.models.credential import ModelProfile
from app.repositories import credential_repo, organization_secret_repo
from app.services.model_catalog import models_for
from app.services.organization_secret import OrganizationSecretService

logger = logging.getLogger(__name__)

# A fallback chain longer than this is a configuration mistake, not a strategy:
# every hop costs a failed request before the next is tried.
MAX_FALLBACK_DEPTH = 3

_ALLOWED_ENDPOINT_SCHEMES = frozenset({"http", "https"})


def _validate_model_id(provider: str, model: str) -> None:
    """Reject model ids a provider cannot parse, at configuration time.

    OpenRouter namespaces every model (`openai/gpt-4.1`) and fails on a bare
    id with `ValueError: not enough values to unpack` - deep inside a run,
    with nothing pointing at the profile that caused it. Catching it here costs
    one comparison and turns a baffling run-time crash into a form error.
    """
    if provider == "openrouter" and "/" not in model:
        raise BadRequestError(
            message="OpenRouter model ids are namespaced, e.g. 'openai/gpt-4.1'",
            details={"model": model},
        )


async def validate_endpoint_url(url: str) -> str:
    """Check a provider `base_url` before the platform will store it.

    Everywhere else - webhooks, MCP servers - an internal address is an SSRF
    attempt and is refused. Here it is frequently the entire point: Ollama on
    `localhost:11434`, a vLLM server on the deployment's own network, a
    LiteLLM proxy beside the API. Local models are a first-class provider, so
    private, loopback and link-local addresses are allowed for model profiles -
    and for model profiles only; the platform's other URL checks are unchanged.

    The scheme and userinfo checks still apply - `file://` is never a model
    endpoint, and credentials in a URL are an ambiguity we do not need. What
    remains of the SSRF posture here is the permission gate: only members who
    may manage connections can store an endpoint at all.

    Every refusal here names the *field*, never the URL it was given. The last
    of the three exists because an endpoint sometimes arrives with a password in
    it, and `details` is both serialized into the response and logged by the
    exception handler - so echoing the value back would write the credential
    this check exists to refuse into the deployment's logs (agenticos#342). The
    scheme check reaches the same URLs (`ftp://user:pass@host`), so all three
    answer the same way.

    Raises:
        BadRequestError: If the URL is malformed, uses another scheme, or
            carries credentials.
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_ENDPOINT_SCHEMES:
        raise refused_field("base_url", "A model endpoint must be an http or https URL")
    if not parsed.hostname:
        raise refused_field("base_url", "A model endpoint must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise refused_field(
            "base_url",
            "A model endpoint must not carry credentials in the URL - store the key "
            "on the credential instead",
        )
    return url


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

    async def list_profiles(self, ctx: AuthContext) -> list[ModelProfile]:
        return await credential_repo.list_profiles(self.db, organization_id=ctx.organization_id)

    async def create_profile(
        self,
        ctx: AuthContext,
        *,
        label: str,
        provider: str,
        model: str,
        secret_id: UUID | None,
        base_url: str | None = None,
        params: dict | None = None,
        allow_byo: bool = False,
        fallback_profile_ids: list[UUID] | None = None,
    ) -> ModelProfile:
        """Define a selectable model.

        `base_url` points the profile somewhere other than the provider's public
        API - a gateway, a LiteLLM proxy, an Ollama on this network. It is only
        accepted for providers whose SDK names an endpoint parameter; offering it
        for the rest would store a value the client silently drops.

        `secret_id` is optional exactly for the keyless providers, which is what
        makes a self-hosted model configurable at all: a model server on the
        deployment's own network usually has nothing to authenticate against. In
        exchange it *must* carry an endpoint, because there is no public API for
        the platform to fall back on.

        Raises:
            BadRequestError: If the key is not this organization's, or is for a
                different provider than the profile claims - a mismatch that
                would otherwise surface as an authentication error from the
                provider, days later and far from its cause. Also on an endpoint
                for a provider that has none, a keyless provider with no
                endpoint, or a keyed provider with no key.
            AlreadyExistsError: If the label is taken. Agents reference a model
                by this name, so a duplicate is an agent nobody can point at
                the model they meant.
        """
        spec = get_provider(provider)
        _validate_model_id(provider, model)

        if base_url is not None:
            if not spec.supports_base_url:
                raise refused_field(
                    "base_url",
                    f"{spec.name} has no endpoint setting - its SDK always talks to the "
                    "provider's own API, so a custom URL here would be ignored",
                    provider=provider,
                )
            base_url = await validate_endpoint_url(base_url)
        elif spec.keyless and secret_id is None:
            raise BadRequestError(
                message=(
                    f"{spec.name} runs without a key, so it needs an endpoint to reach - "
                    "there is no public API to fall back on"
                ),
                details={"provider": provider},
            )

        if secret_id is None and not spec.keyless:
            raise BadRequestError(
                message=f"{spec.name} needs a key. Store one in the vault, then add the model",
                details={"provider": provider},
            )

        if await credential_repo.get_profile_by_label(
            self.db, label, organization_id=ctx.organization_id
        ):
            raise AlreadyExistsError(
                message=(
                    f"A model named '{label}' already exists. Agents pick a model by this name, "
                    "so it has to be unique - name this one for what makes it different, or "
                    "delete the existing model if you meant to replace it."
                ),
                details={"label": label},
            )

        # The key has to exist and be for the provider the model claims: a
        # Tavily key behind an OpenAI model authenticates against nothing.
        if secret_id is not None:
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
            base_url=base_url,
            params=params,
            allow_byo=allow_byo,
            fallback_profile_ids=[str(pid) for pid in (fallback_profile_ids or [])],
            context_length=await self._context_length(ctx, provider, model),
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

    async def _context_length(self, ctx: AuthContext, provider: str, model: str) -> int | None:
        """How many tokens this model accepts, as the provider's own listing says.

        Read once here rather than per run, because the request path must not
        call a provider - and stored, because the alternative source is wrong in
        the direction that breaks a run. The `compaction` capability triggers on
        a fraction of the context window; `genai-prices` records 1,000,000 for
        `anthropic:claude-sonnet-4-5` against a real 200,000, so a trigger at 90%
        lands above the ceiling and compaction never fires before the provider
        refuses the request (#773).

        The picker asked the same question moments ago and the listing is cached
        for an hour, so this is usually free. `models_for` never raises and
        answers its curated list when a provider cannot be reached; a model the
        answer does not mention - a bespoke deployment, one shipped this morning,
        or anything under a curated list that carries no lengths - records
        nothing, and nothing means the capability resolves the window itself.
        """
        api_key = await OrganizationSecretService(self.db).listing_key(ctx, provider)
        models, _ = await models_for(provider, api_key=api_key)
        return next((entry.context_length for entry in models if entry.id == model), None)

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

    async def _resolve_credential(
        self, organization_id: UUID, profile: ModelProfile
    ) -> ResolvedCredential:
        """The key this model runs on, from whichever store holds it.

        A vault secret first: that is the one people manage, and picking
        "OpenRouter" there is what makes OpenRouter's models runnable. A legacy
        `credential` is the fallback, so profiles created before the two stores
        were joined keep working without a migration that rewrites them.

        A keyless provider with an endpoint has no secret to resolve and is not an
        error: an Ollama or a LiteLLM proxy on this network authenticates nothing,
        which is why `NoSecret` is a kind the runtime can hold.

        **Both halves are required.** `keyless` is true of `openai` too, because
        OpenAI-compatible servers exist - so "keyless" alone does not distinguish a
        deliberate self-hosted profile from one whose key was deleted, and the
        foreign key is `ON DELETE SET NULL`, which makes that second case ordinary.
        The endpoint is what tells them apart: without one there is nowhere to send
        the request, and the honest answer is the same refusal as before.
        """
        if profile.secret_id is None:
            spec = get_provider(profile.provider)
            if spec.keyless and profile.base_url:
                return ResolvedCredential(
                    provider=profile.provider,
                    secret=NoSecret(),
                    base_url=profile.base_url,
                )
            raise BadRequestError(
                message=f"Model '{profile.label}' has no key configured - add one in the vault",
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
            # The profile's, not the secret's. A secret says what authenticates;
            # where the request is sent is the profile's business, so the same key
            # can front a staging proxy and a production one as two profiles.
            # This was hardcoded to `None`, which is why no deployment could reach
            # a gateway however carefully it stored the URL.
            base_url=profile.base_url,
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
        not a permission decision - nothing here consults a role, and the
        request that *was* authorized may have finished hours ago. Background
        ingestion is the case: a document is parsed by a worker long after the
        upload that was allowed, and it still has to reach the same profile and
        unseal the same key. Taking the organization directly says that plainly,
        instead of inventing a caller for the sake of a signature.

        Precedence, most specific first: the profile that was asked for, then
        the organization's default. There is deliberately no environment
        fallback - a deployment serving several tenants must never quietly bill
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
            # it - the same spec answering on a different model, at a different
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
            # The primary's window, even when the chain has fallbacks: a
            # `FallbackModel` has no window of its own to resolve, and the model
            # a run actually reaches is not known until one has refused.
            context_length=profile.context_length,
        )
