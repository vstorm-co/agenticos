"""Tests for provider credentials and model resolution.

Three things are worth guarding: that every provider a profile may name can
actually be built, that a credential of the wrong shape is refused while a form
is open rather than at the first run, and that resolution refuses quietly-wrong
configurations instead of producing a client that fails later inside someone's
agent run.
"""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic_ai.models.fallback import FallbackModel

from app.agents.model_resolver import (
    PROVIDERS,
    ProviderSpec,
    ResolvedCredential,
    build_model,
    get_provider,
)
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import (
    ApiKeySecret,
    AwsCredentialsSecret,
    AzureOpenAISecret,
    GcpServiceAccountSecret,
    NoSecret,
    SecretKind,
    seal_secret,
)
from app.core.vault import VaultScope
from app.services.model_catalog import CatalogModel
from app.services.model_profile import (
    MAX_FALLBACK_DEPTH,
    ModelProfileService,
    provider_catalog,
    validate_endpoint_url,
)


def _ctx(org_id=None) -> AuthContext:
    return AuthContext(
        user_id=uuid.uuid4(),
        organization_id=org_id or uuid.uuid4(),
        role=OrgRoleName.OWNER,
    )


def service_account_json(project: str = "demo-project") -> str:
    """A structurally valid service account, with a real key Google can parse.

    Generated rather than pasted: `from_service_account_info` parses the PEM, so
    a placeholder string would make every Vertex test fail for the wrong reason.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return json.dumps(
        {
            "type": "service_account",
            "project_id": project,
            "private_key_id": "abc123",
            "private_key": pem,
            "client_email": "agent@demo-project.iam.gserviceaccount.com",
            "client_id": "1",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


def secret_for(spec: ProviderSpec):
    """A credential of whichever shape this provider declares it wants."""
    if spec.secret_kind is SecretKind.API_KEY:
        return ApiKeySecret(api_key="sk-test-abcd1234")
    if spec.secret_kind is SecretKind.AZURE_OPENAI:
        return AzureOpenAISecret(
            api_key="azure-key-1234",
            azure_endpoint="https://demo.openai.azure.com",
            api_version="2024-10-21",
        )
    if spec.secret_kind is SecretKind.AWS_CREDENTIALS:
        return AwsCredentialsSecret(
            aws_access_key_id="AKIAEXAMPLE1234",
            aws_secret_access_key="aws-secret",
            region_name="us-east-1",
        )
    return GcpServiceAccountSecret(service_account_json=service_account_json())


def _credential(ctx, provider="openai", secret=None, is_active=True, base_url=None):
    value = secret if secret is not None else ApiKeySecret(api_key="sk-test-abcd1234")
    credential = MagicMock()
    credential.id = uuid.uuid4()
    credential.organization_id = ctx.organization_id
    credential.provider = provider
    credential.label = f"{provider} key"
    credential.kind = value.kind.value
    credential.created_by_user_id = None
    credential.created_at = datetime(2026, 7, 1, tzinfo=UTC)
    credential.updated_at = None
    credential.base_url = base_url
    credential.is_active = is_active
    if isinstance(value, NoSecret):
        credential.sealed_secret = None
        credential.hint = ""
        credential.key_version = 1
    else:
        sealed = seal_secret(value, scope=VaultScope.organization(ctx.organization_id))
        credential.sealed_secret = sealed.ciphertext
        credential.hint = sealed.hint
        credential.key_version = sealed.key_version
    return credential


def _profile(ctx, secret=None, model="gpt-4.1", fallbacks=None, provider="openai", base_url=None):
    """A stored model profile, keyed from the vault like every real one.

    `base_url` defaults to None explicitly rather than being left to the mock: a
    `MagicMock` attribute is truthy, so it reaches `httpx.URL()` as a mock and
    raises there instead of meaning "the provider's own API", which is what an
    unset endpoint means.
    """
    profile = MagicMock()
    profile.id = uuid.uuid4()
    profile.organization_id = ctx.organization_id
    profile.label = "Test profile"
    profile.provider = provider
    profile.model = model
    profile.secret_id = secret.id if secret else uuid.uuid4()
    profile.base_url = base_url
    profile.params = {}
    profile.fallback_profile_ids = [str(pid) for pid in (fallbacks or [])]
    return profile


def _db():
    """A session standing in for an empty database.

    Every label lookup this service does before writing therefore finds
    nothing, which is the state each test below is describing. A bare
    `MagicMock` would answer those lookups with a truthy mock and turn every
    creation into a duplicate.
    """
    db = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    return db


class TestProviderCatalog:
    @pytest.mark.parametrize("provider_id", sorted(PROVIDERS))
    def test_every_selectable_provider_actually_builds_a_model(self, provider_id):
        """The invariant a hand-written registry used to give, kept after inference.

        A provider in the catalog but not constructible is a dead option in the
        Builder's dropdown that only fails once somebody has stored a key for
        it. This constructs each one with a credential of the shape it declares
        - which is also what proves the declaration is right.
        """
        spec = PROVIDERS[provider_id]
        # OpenRouter is the one provider that rejects a bare model id, and does
        # so in the constructor rather than at request time.
        model = "openai/gpt-4.1" if provider_id == "openrouter" else "some-model"
        credential = ResolvedCredential(
            provider=provider_id,
            secret=secret_for(spec),
            base_url="https://gateway.example.com" if spec.supports_base_url else None,
        )
        assert build_model(credential, model) is not None

    @pytest.mark.parametrize("provider_id", ["openai", "ollama", "litellm"])
    def test_a_local_endpoint_builds_with_no_credential_at_all(self, provider_id):
        """The point of `keyless`: a model server on your own network has no key."""
        credential = ResolvedCredential(
            provider=provider_id, secret=NoSecret(), base_url="http://localhost:11434/v1"
        )
        assert build_model(credential, "llama3.2") is not None

    def test_the_three_odd_credential_shapes_are_declared_as_such(self):
        """An AWS key pair is not an API key, and the catalog has to say so.

        If these ever collapse back to `api_key`, the credential form asks for
        one string and the resulting credential fails at the first run.
        """
        assert PROVIDERS["azure"].secret_kind is SecretKind.AZURE_OPENAI
        assert PROVIDERS["bedrock"].secret_kind is SecretKind.AWS_CREDENTIALS
        assert PROVIDERS["google_cloud"].secret_kind is SecretKind.GCP_SERVICE_ACCOUNT

    def test_openai_builds_a_chat_model_not_a_responses_one(self):
        """OpenAI-compatible servers implement Chat Completions and not Responses.

        `infer_model("openai:...")` returns a Responses model, which would make
        every vLLM / LM Studio / LiteLLM endpoint fail - the exact case
        `base_url` exists for.
        """
        assert PROVIDERS["openai"].prefix == "openai-chat"

    def test_the_catalog_is_ordered_for_a_stable_picker(self):
        names = [spec.name for spec in provider_catalog()]
        assert names == sorted(names, key=str.lower)

    def test_unknown_provider_fails_loudly(self):
        credential = ResolvedCredential(
            provider="myprovider", secret=ApiKeySecret(api_key="sk-test")
        )
        with pytest.raises(BadRequestError) as exc:
            build_model(credential, "some-model")
        assert exc.value.details is not None
        assert "supported" in exc.value.details

    def test_out_of_scope_provider_names_are_not_offered(self):
        """Three names Pydantic AI knows that a model profile cannot point at.

        `gateway` is a routing prefix rather than a provider, and the other two
        are not chat providers. Listing them would put options in the dropdown
        that cannot produce a working agent.
        """
        assert not {"gateway", "bedrock-mantle", "sentence-transformers"} & set(PROVIDERS)


class TestProfileCreation:
    @pytest.mark.anyio
    async def test_bare_openrouter_model_id_is_rejected(self):
        """Caught at configuration time, not as a ValueError mid-run."""
        with pytest.raises(BadRequestError) as exc:
            await ModelProfileService(_db()).create_profile(
                _ctx(),
                label="OR",
                provider="openrouter",
                model="gpt-4.1",
                secret_id=uuid.uuid4(),
            )
        assert "namespaced" in exc.value.message

    @pytest.mark.anyio
    async def test_a_bare_model_id_names_the_field_and_is_not_posted_back(self):
        """It used to answer `details={"model": model}`.

        Which is the caller's own submission in a response body and in the log
        line the handler writes beside it, and a shape `fieldProblems` reads
        nowhere - so the form showed a sentence and marked nothing (#898).

        The id refused here is deliberately not the one the message offers as
        an example, so the second assertion is about what was submitted rather
        than about a substring of our own copy."""
        with pytest.raises(BadRequestError) as exc:
            await ModelProfileService(_db()).create_profile(
                _ctx(),
                label="OR",
                provider="openrouter",
                model="gpt-5",
                secret_id=uuid.uuid4(),
            )

        assert exc.value.details == {"fields": [{"field": "model", "message": exc.value.message}]}
        assert "gpt-5" not in repr(exc.value.details)

    @pytest.mark.anyio
    async def test_a_provider_with_no_catalog_entry_cannot_become_a_profile(self):
        """A profile the platform cannot construct is a dead option in every picker."""
        with (
            patch(
                "app.services.model_profile.credential_repo.create_profile", new=AsyncMock()
            ) as create,
            pytest.raises(BadRequestError) as refused,
        ):
            await ModelProfileService(_db()).create_profile(
                _ctx(),
                label="x",
                provider="myprovider",
                model="some-model",
                secret_id=uuid.uuid4(),
            )

        assert refused.value.details == {"supported": sorted(PROVIDERS)}
        assert create.await_count == 0

    @pytest.mark.anyio
    async def test_a_taken_label_is_a_conflict_rather_than_a_crash(self):
        """Same unguarded constraint as on credentials, same 500 it produced.

        A model is chosen by its label in the Builder's dropdown, so this is
        the label collision people actually hit - two keys for one provider,
        both named after the provider.
        """
        with (
            patch(
                "app.services.model_profile.credential_repo.get_profile_by_label",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.services.model_profile.credential_repo.create_profile", new=AsyncMock()
            ) as create,
            pytest.raises(AlreadyExistsError) as refused,
        ):
            await ModelProfileService(_db()).create_profile(
                _ctx(),
                label="openai default",
                provider="openai",
                model="gpt-4.1",
                secret_id=uuid.uuid4(),
            )

        assert refused.value.status_code == 409
        assert refused.value.details == {"label": "openai default"}
        assert create.await_count == 0
        assert "openai default" in refused.value.message
        assert "name this one for what makes it different" in refused.value.message

    @pytest.mark.anyio
    async def test_a_profile_is_written_with_its_key_and_audited(self):
        ctx = _ctx()
        secret = _vault_secret(ctx)
        fallback_id = uuid.uuid4()

        with (
            patch(
                "app.services.model_profile.organization_secret_repo.get",
                new=AsyncMock(return_value=secret),
            ),
            patch(
                "app.services.model_profile.credential_repo.create_profile",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ) as create,
            patch("app.services.model_profile.record_audit", new=AsyncMock()) as audit,
        ):
            await ModelProfileService(_db()).create_profile(
                ctx,
                label="Prod",
                provider="openai",
                model="gpt-4.1",
                secret_id=secret.id,
                params={"temperature": 0.2},
                fallback_profile_ids=[fallback_id],
            )

        written = create.call_args.kwargs
        assert written["organization_id"] == ctx.organization_id
        assert written["secret_id"] == secret.id
        assert written["params"] == {"temperature": 0.2}
        # Stored as strings because the column is JSON, not a foreign key.
        assert written["fallback_profile_ids"] == [str(fallback_id)]
        # A profile that is not the default must not disturb the one that is.
        assert audit.call_args.kwargs["action"] == "model_profile.created"
        assert audit.call_args.kwargs["details"] == {
            "label": "Prod",
            "provider": "openai",
            "model": "gpt-4.1",
        }

    @pytest.mark.anyio
    async def test_deleting_a_profile_from_another_organization_is_not_found(self):
        with (
            patch(
                "app.services.model_profile.credential_repo.delete_profile",
                new=AsyncMock(return_value=False),
            ),
            patch("app.services.model_profile.record_audit", new=AsyncMock()) as audit,
            pytest.raises(NotFoundError) as refused,
        ):
            await ModelProfileService(_db()).delete_profile(_ctx(), uuid.uuid4())

        assert audit.await_count == 0
        assert "Model profile not found" in refused.value.message

    @pytest.mark.anyio
    async def test_a_deleted_profile_leaves_a_trail(self):
        ctx = _ctx()
        profile_id = uuid.uuid4()

        with (
            patch(
                "app.services.model_profile.credential_repo.delete_profile",
                new=AsyncMock(return_value=True),
            ) as delete,
            patch("app.services.model_profile.record_audit", new=AsyncMock()) as audit,
        ):
            await ModelProfileService(_db()).delete_profile(ctx, profile_id)

        assert delete.call_args.kwargs["organization_id"] == ctx.organization_id
        assert audit.call_args.kwargs["action"] == "model_profile.deleted"
        assert audit.call_args.kwargs["target_id"] == str(profile_id)


class TestProfileListing:
    @pytest.mark.anyio
    async def test_only_the_callers_own_profiles_are_listed(self):
        ctx = _ctx()
        mine = _profile(ctx)

        with patch(
            "app.services.model_profile.credential_repo.list_profiles",
            new=AsyncMock(return_value=[mine]),
        ) as list_profiles:
            listed = await ModelProfileService(_db()).list_profiles(ctx)

        assert listed == [mine]
        assert list_profiles.call_args.kwargs["organization_id"] == ctx.organization_id


class TestResolution:
    @pytest.mark.anyio
    async def test_named_profile_resolves_with_its_key(self):
        ctx = _ctx()
        secret = _vault_secret(ctx)
        profile = _profile(ctx, secret)

        with (
            patch(
                "app.services.model_profile.credential_repo.get_profile",
                new=AsyncMock(return_value=profile),
            ),
            patch(
                "app.services.model_profile.organization_secret_repo.get",
                new=AsyncMock(return_value=secret),
            ),
        ):
            spec = await ModelProfileService(_db()).resolve(ctx, profile_id=profile.id)

        assert spec.model == "gpt-4.1"
        assert isinstance(spec.credential.secret, ApiKeySecret)
        assert spec.credential.secret.api_key.get_secret_value() == "sk-vault-abcd1234"
        assert spec.build() is not None

    def test_a_resolved_credential_masks_itself_in_a_repr(self):
        """The usual way a key escapes is a dataclass reaching a log line."""
        credential = ResolvedCredential(
            provider="openai", secret=ApiKeySecret(api_key="sk-live-do-not-print")
        )
        assert "sk-live-do-not-print" not in repr(credential)

    @pytest.mark.anyio
    async def test_profile_without_a_key_fails_with_its_label(self):
        ctx = _ctx()
        profile = _profile(ctx)
        profile.secret_id = None

        with (
            patch(
                "app.services.model_profile.credential_repo.get_profile",
                new=AsyncMock(return_value=profile),
            ),
            pytest.raises(BadRequestError) as exc,
        ):
            await ModelProfileService(_db()).resolve(ctx, profile_id=profile.id)
        assert "Test profile" in exc.value.message

    @pytest.mark.anyio
    async def test_a_broken_fallback_degrades_the_chain_not_the_run(self):
        ctx = _ctx()
        secret = _vault_secret(ctx)
        missing_id = uuid.uuid4()
        profile = _profile(ctx, secret, fallbacks=[missing_id])

        with (
            patch(
                "app.services.model_profile.credential_repo.get_profile",
                new=AsyncMock(return_value=profile),
            ),
            patch(
                "app.services.model_profile.organization_secret_repo.get",
                new=AsyncMock(return_value=secret),
            ),
            patch(
                "app.services.model_profile.credential_repo.get_profiles_by_ids",
                new=AsyncMock(return_value={}),
            ),
        ):
            spec = await ModelProfileService(_db()).resolve(ctx, profile_id=profile.id)

        assert spec.fallbacks == []
        assert spec.build() is not None

    @pytest.mark.anyio
    async def test_a_profile_id_from_another_organization_is_not_found(self):
        """The lookup is org-scoped, so a foreign id reads as absent rather than forbidden."""
        profile_id = uuid.uuid4()

        with (
            patch(
                "app.services.model_profile.credential_repo.get_profile",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(NotFoundError) as refused,
        ):
            await ModelProfileService(_db()).resolve(_ctx(), profile_id=profile_id)

        assert refused.value.details == {"profile_id": str(profile_id)}

    @pytest.mark.anyio
    async def test_a_usable_fallback_becomes_a_second_model_to_fail_over_to(self):
        ctx = _ctx()
        secret = _vault_secret(ctx)
        fallback = _profile(ctx, secret, model="gpt-4o-mini")
        profile = _profile(ctx, secret, fallbacks=[fallback.id])

        with (
            patch(
                "app.services.model_profile.credential_repo.get_profile",
                new=AsyncMock(return_value=profile),
            ),
            patch(
                "app.services.model_profile.organization_secret_repo.get",
                new=AsyncMock(return_value=secret),
            ),
            patch(
                "app.services.model_profile.credential_repo.get_profiles_by_ids",
                new=AsyncMock(return_value={fallback.id: fallback}),
            ),
        ):
            spec = await ModelProfileService(_db()).resolve(ctx, profile_id=profile.id)

        assert [model for _, model in spec.fallbacks] == ["gpt-4o-mini"]
        assert isinstance(spec.build(), FallbackModel)

    @pytest.mark.anyio
    async def test_a_fallback_whose_key_is_gone_is_skipped_not_raised(self):
        """A fallback exists to survive an outage; it must not cause one itself."""
        ctx = _ctx()
        secret = _vault_secret(ctx)
        keyless = _profile(ctx)
        keyless.secret_id = None
        profile = _profile(ctx, secret, fallbacks=[keyless.id])

        with (
            patch(
                "app.services.model_profile.credential_repo.get_profile",
                new=AsyncMock(return_value=profile),
            ),
            patch(
                "app.services.model_profile.organization_secret_repo.get",
                new=AsyncMock(return_value=secret),
            ),
            patch(
                "app.services.model_profile.credential_repo.get_profiles_by_ids",
                new=AsyncMock(return_value={keyless.id: keyless}),
            ),
        ):
            spec = await ModelProfileService(_db()).resolve(ctx, profile_id=profile.id)

        assert spec.fallbacks == []
        assert spec.model == "gpt-4.1"

    @pytest.mark.anyio
    async def test_a_chain_longer_than_the_limit_is_cut_before_it_is_read(self):
        """Every hop costs a failed request first, so the tail is truncated, not queried."""
        ctx = _ctx()
        secret = _vault_secret(ctx)
        chain = [_profile(ctx, secret, model=f"gpt-{i}") for i in range(MAX_FALLBACK_DEPTH + 2)]
        profile = _profile(ctx, secret, fallbacks=[link.id for link in chain])

        with (
            patch(
                "app.services.model_profile.credential_repo.get_profile",
                new=AsyncMock(return_value=profile),
            ),
            patch(
                "app.services.model_profile.organization_secret_repo.get",
                new=AsyncMock(return_value=secret),
            ),
            patch(
                "app.services.model_profile.credential_repo.get_profiles_by_ids",
                new=AsyncMock(return_value={link.id: link for link in chain}),
            ) as fetch,
        ):
            spec = await ModelProfileService(_db()).resolve(ctx, profile_id=profile.id)

        assert fetch.call_args.args[1] == [link.id for link in chain[:MAX_FALLBACK_DEPTH]]
        assert [model for _, model in spec.fallbacks] == ["gpt-0", "gpt-1", "gpt-2"]


class TestProviderLookup:
    def test_a_known_provider_returns_its_spec(self):
        assert get_provider("anthropic").name == "Anthropic"


def _vault_secret(ctx, purpose="openai", value=None):
    """A row of the vault, sealed the way the service will try to unseal it."""
    sealed = seal_secret(
        value or ApiKeySecret(api_key="sk-vault-abcd1234"),
        scope=VaultScope.organization(ctx.organization_id),
    )
    secret = MagicMock()
    secret.id = uuid.uuid4()
    secret.organization_id = ctx.organization_id
    secret.purpose = purpose
    secret.kind = SecretKind.API_KEY.value
    secret.sealed_secret = sealed.ciphertext
    secret.hint = sealed.hint
    secret.key_version = sealed.key_version
    return secret


class TestProfilesKeyedFromTheVault:
    """The store people actually manage.

    A model profile used to be keyed only by a provider credential, which is a
    second vault with its own dialog and no rotation. Pointing a profile at a
    vault secret is what makes "add an OpenRouter key" and "run an OpenRouter
    model" the same act - and it is the path with the failure modes: a key that
    was deleted, and a key for a different provider entirely.
    """

    @pytest.mark.anyio
    async def test_a_key_this_organization_does_not_have_is_refused_at_creation(self):
        ctx = _ctx()
        with (
            patch(
                "app.services.model_profile.organization_secret_repo.get",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(BadRequestError) as exc,
        ):
            await ModelProfileService(_db()).create_profile(
                ctx,
                label="GPT",
                provider="openai",
                model="gpt-4.1",
                secret_id=uuid.uuid4(),
            )
        assert "not in this organization's vault" in exc.value.message

    @pytest.mark.anyio
    async def test_a_key_for_another_provider_is_refused_at_creation(self):
        """A Tavily key behind an OpenAI model authenticates against nothing;
        without this the failure arrives days later as a 401 from OpenAI."""
        ctx = _ctx()
        secret = _vault_secret(ctx, purpose="tavily")

        with (
            patch(
                "app.services.model_profile.organization_secret_repo.get",
                new=AsyncMock(return_value=secret),
            ),
            pytest.raises(BadRequestError) as exc,
        ):
            await ModelProfileService(_db()).create_profile(
                ctx,
                label="GPT",
                provider="openai",
                model="gpt-4.1",
                secret_id=secret.id,
            )
        assert "for tavily, not openai" in exc.value.message

    @pytest.mark.anyio
    async def test_the_vault_key_is_what_the_model_runs_on(self):
        ctx = _ctx()
        secret = _vault_secret(ctx)
        profile = _profile(ctx)
        profile.secret_id = secret.id

        with patch(
            "app.services.model_profile.organization_secret_repo.get",
            new=AsyncMock(return_value=secret),
        ):
            resolved = await ModelProfileService(_db())._resolve_credential(
                ctx.organization_id, profile
            )

        assert resolved.secret.api_key.get_secret_value() == "sk-vault-abcd1234"
        # A vault secret carries no endpoint; a base URL would silently point a
        # provider's own client at somebody else's host.
        assert resolved.base_url is None

    @pytest.mark.anyio
    async def test_a_deleted_key_is_named_by_the_model_that_needed_it(self):
        """ "Missing key" with no profile in it is a message that sends somebody
        through every model in the list to find which one broke."""
        ctx = _ctx()
        profile = _profile(ctx)
        profile.secret_id = uuid.uuid4()

        with (
            patch(
                "app.services.model_profile.organization_secret_repo.get",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(BadRequestError) as exc,
        ):
            await ModelProfileService(_db())._resolve_credential(ctx.organization_id, profile)

        assert "Test profile" in exc.value.message

    @pytest.mark.anyio
    async def test_a_matching_key_creates_the_profile_and_is_stored_on_it(self):
        """The success the two refusals above guard. Asserted on the row written
        rather than on "no exception": a profile that dropped its `secret_id`
        would pass every refusal test here and still have no key at run time."""
        ctx = _ctx()
        secret = _vault_secret(ctx, purpose="openai")
        created = _profile(ctx)
        created.secret_id = secret.id

        with (
            patch(
                "app.services.model_profile.organization_secret_repo.get",
                new=AsyncMock(return_value=secret),
            ),
            patch(
                "app.services.model_profile.credential_repo.create_profile",
                new=AsyncMock(return_value=created),
            ) as create,
            patch("app.services.model_profile.record_audit", new=AsyncMock()),
        ):
            profile = await ModelProfileService(_db()).create_profile(
                ctx,
                label="GPT",
                provider="openai",
                model="gpt-4.1",
                secret_id=secret.id,
            )

        assert create.call_args.kwargs["secret_id"] == secret.id
        assert profile.secret_id == secret.id


class TestEndpointValidation:
    """What a stored `base_url` may be.

    Internal addresses are allowed on purpose - Ollama on localhost is the
    whole point of the field, and local models are a first-class provider. The
    scheme and userinfo rules are what remain non-negotiable.
    """

    @pytest.mark.anyio
    @pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://models.example", "not a url"])
    async def test_only_http_and_https_are_endpoints(self, url):
        with pytest.raises(BadRequestError):
            await validate_endpoint_url(url)

    @pytest.mark.anyio
    async def test_an_endpoint_without_a_host_is_refused(self):
        with pytest.raises(BadRequestError):
            await validate_endpoint_url("http://")

    @pytest.mark.anyio
    async def test_credentials_in_the_url_are_refused(self):
        """The key belongs on the profile's secret, not inside a URL that ends
        up in logs and exports."""
        with pytest.raises(BadRequestError):
            await validate_endpoint_url("https://user:pass@models.example/v1")

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:11434/v1",
            "http://10.0.0.5:8000/v1",
            "https://models.example/v1",
        ],
    )
    async def test_local_and_public_endpoints_are_both_accepted(self, url):
        """No DNS resolution, no SSRF probe: localhost has to validate before
        Ollama is even running, and a public URL is just as fine."""
        assert await validate_endpoint_url(url) == url


class TestAnEndpointOfItsOwn:
    """A profile can point somewhere other than the provider's public API.

    Every piece of this existed before and nothing joined them: the provider
    catalog said which providers accept an endpoint, `validate_endpoint_url`
    checked one, and `_build_provider` knew how to pass one to the SDK - while
    `_resolve_credential` returned `base_url=None` unconditionally and the
    validator had no caller outside this file. So a deployment could not reach a
    gateway, a LiteLLM proxy or an Ollama however carefully it stored the URL.
    """

    @pytest.mark.anyio
    async def test_a_stored_endpoint_is_the_one_the_client_is_built_with(self):
        """The point of the whole feature: it reaches the provider client."""
        ctx = _ctx()
        secret = _vault_secret(ctx)
        profile = _profile(ctx, secret=secret, base_url="http://localhost:11434/v1")

        with (
            patch(
                "app.services.model_profile.credential_repo.get_profile",
                new=AsyncMock(return_value=profile),
            ),
            patch(
                "app.services.model_profile.organization_secret_repo.get",
                new=AsyncMock(return_value=secret),
            ),
        ):
            spec = await ModelProfileService(_db()).resolve(ctx, profile_id=profile.id)

        assert spec.credential.base_url == "http://localhost:11434/v1"

    @pytest.mark.anyio
    async def test_an_endpoint_is_refused_for_a_provider_that_has_none(self):
        """Storing one would be storing a value the SDK drops in silence.

        `openrouter` names no endpoint parameter, so a URL saved against it would
        look configured and change nothing about where the request went.
        """
        with pytest.raises(BadRequestError) as exc:
            await ModelProfileService(_db()).create_profile(
                _ctx(),
                label="Through a proxy",
                provider="openrouter",
                model="openai/gpt-4.1",
                secret_id=uuid.uuid4(),
                base_url="https://proxy.example/v1",
            )
        assert "endpoint" in str(exc.value).lower()

    @pytest.mark.anyio
    async def test_a_keyless_provider_without_an_endpoint_is_refused(self):
        """There is no public API for it to fall back on."""
        with pytest.raises(BadRequestError) as exc:
            await ModelProfileService(_db()).create_profile(
                _ctx(),
                label="Local llama",
                provider="ollama",
                model="llama3.3",
                secret_id=None,
            )
        assert "endpoint" in str(exc.value).lower()

    @pytest.mark.anyio
    async def test_a_keyless_provider_with_no_endpoint_names_the_endpoint_field(self):
        """The refusal is about `base_url`, and it named only `provider`.

        Which is a fact rather than a field, so the form had nothing to mark
        (#898). The provider stays beside the field, the way the "no endpoint
        setting" refusal above carries it."""
        with pytest.raises(BadRequestError) as exc:
            await ModelProfileService(_db()).create_profile(
                _ctx(),
                label="Local llama",
                provider="ollama",
                model="llama3.3",
                secret_id=None,
            )

        assert exc.value.details == {
            "provider": "ollama",
            "fields": [{"field": "base_url", "message": exc.value.message}],
        }

    @pytest.mark.anyio
    async def test_a_keyed_provider_without_a_key_is_refused(self):
        """A model that cannot answer is not worth creating."""
        with pytest.raises(BadRequestError) as exc:
            await ModelProfileService(_db()).create_profile(
                _ctx(),
                label="Anthropic, keyless",
                provider="anthropic",
                model="claude-sonnet-5",
                secret_id=None,
            )
        assert "key" in str(exc.value).lower()

    @pytest.mark.anyio
    async def test_a_missing_key_names_the_key_field_rather_than_the_provider(self):
        """Same defect as its neighbour above, about `secret_id` (#898)."""
        with pytest.raises(BadRequestError) as exc:
            await ModelProfileService(_db()).create_profile(
                _ctx(),
                label="Anthropic, keyless",
                provider="anthropic",
                model="claude-sonnet-5",
                secret_id=None,
            )

        assert exc.value.details == {
            "provider": "anthropic",
            "fields": [{"field": "secret_id", "message": exc.value.message}],
        }

    @pytest.mark.anyio
    async def test_a_keyless_profile_resolves_with_no_secret_at_all(self):
        """The case that makes a self-hosted model usable from the product."""
        ctx = _ctx()
        profile = _profile(ctx, provider="ollama", model="llama3.3")
        profile.secret_id = None
        profile.base_url = "http://localhost:11434/v1"

        with patch(
            "app.services.model_profile.credential_repo.get_profile",
            new=AsyncMock(return_value=profile),
        ):
            spec = await ModelProfileService(_db()).resolve(ctx, profile_id=profile.id)

        assert isinstance(spec.credential.secret, NoSecret)
        assert spec.credential.base_url == "http://localhost:11434/v1"
        assert spec.secret_id is None

    @pytest.mark.anyio
    async def test_a_profile_whose_key_was_deleted_still_refuses(self):
        """`keyless` alone must not excuse a missing key.

        It is true of `openai` as well, because OpenAI-compatible servers exist -
        and the secret foreign key is `ON DELETE SET NULL`, so a profile losing its
        key is ordinary. Without an endpoint there is nowhere to send the request,
        and reporting that plainly beats dialling api.openai.com with no
        credential.
        """
        ctx = _ctx()
        profile = _profile(ctx, provider="openai")
        profile.secret_id = None
        profile.base_url = None

        with (
            patch(
                "app.services.model_profile.credential_repo.get_profile",
                new=AsyncMock(return_value=profile),
            ),
            pytest.raises(BadRequestError) as exc,
        ):
            await ModelProfileService(_db()).resolve(ctx, profile_id=profile.id)

        assert "no key configured" in str(exc.value)

    @pytest.mark.anyio
    async def test_a_self_hosted_model_is_written_with_its_endpoint_and_no_key(self):
        """The whole path, end to end: no key, an endpoint, a stored profile.

        This is what "Ollama is a supported provider" has to mean. Before the
        endpoint was wired there was no way to reach this state: `secret_id` was
        required by the schema, and `base_url` was accepted nowhere.
        """
        ctx = _ctx()

        with (
            patch(
                "app.services.model_profile.credential_repo.create_profile",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ) as create,
            patch("app.services.model_profile.record_audit", new=AsyncMock()),
        ):
            await ModelProfileService(_db()).create_profile(
                ctx,
                label="Local llama",
                provider="ollama",
                model="llama3.3",
                secret_id=None,
                base_url="http://localhost:11434/v1",
            )

        written = create.call_args.kwargs
        assert written["secret_id"] is None
        assert written["base_url"] == "http://localhost:11434/v1"


class TestTheWindowAModelAccepts:
    """What `context_length` is for, and why it is stored rather than resolved.

    The `compaction` capability triggers on a fraction of the context window, and
    the only thing it could otherwise resolve one from is the `genai-prices`
    snapshot - which records 1,000,000 for `anthropic:claude-sonnet-4-5` against
    a real 200,000, and answers nothing at all for a profile with fallbacks,
    whose `FallbackModel` has a composite `fallback:...` id. Over-recording is
    the direction that takes a run down: the trigger lands above the real
    ceiling, compaction never fires, and the provider refuses the request (#773).
    """

    @staticmethod
    def _catalog(*models: tuple[str, int | None]) -> AsyncMock:
        return AsyncMock(
            return_value=(
                [CatalogModel(id=mid, name=mid, context_length=n) for mid, n in models],
                "live",
            )
        )

    async def _created(self, catalog: AsyncMock, *, model: str) -> dict:
        with (
            patch("app.services.model_profile.models_for", new=catalog),
            patch(
                "app.services.model_profile.credential_repo.create_profile",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ) as create,
            patch("app.services.model_profile.record_audit", new=AsyncMock()),
        ):
            await ModelProfileService(_db()).create_profile(
                _ctx(),
                label="Local llama",
                provider="ollama",
                model=model,
                secret_id=None,
                base_url="http://localhost:11434/v1",
            )
        return create.call_args.kwargs

    @pytest.mark.anyio
    async def test_the_providers_own_number_is_what_gets_stored(self):
        written = await self._created(
            self._catalog(("llama3.3", 128_000), ("other", 8_000)), model="llama3.3"
        )

        assert written["context_length"] == 128_000

    @pytest.mark.anyio
    async def test_a_model_the_listing_does_not_mention_records_nothing(self):
        """A bespoke deployment, or one that shipped this morning. Null means not
        recorded, and the capability resolves the window itself."""
        written = await self._created(self._catalog(("other", 8_000)), model="llama3.3")

        assert written["context_length"] is None

    @pytest.mark.anyio
    async def test_a_provider_that_publishes_no_length_records_nothing(self):
        """A curated list carries ids and names; most of it carries no window."""
        written = await self._created(self._catalog(("llama3.3", None)), model="llama3.3")

        assert written["context_length"] is None

    @pytest.mark.anyio
    async def test_the_primarys_window_travels_even_when_the_chain_has_fallbacks(self):
        """A `FallbackModel` has no window of its own to resolve, and which model a
        run reaches is not known until one has refused."""
        profile = MagicMock(
            id=uuid.uuid4(),
            label="Prod",
            provider="ollama",
            model="llama3.3",
            params={},
            secret_id=None,
            base_url="http://localhost:11434/v1",
            fallback_profile_ids=[],
            context_length=128_000,
        )
        with patch(
            "app.services.model_profile.credential_repo.get_profile",
            new=AsyncMock(return_value=profile),
        ):
            spec = await ModelProfileService(_db()).resolve_for_organization(
                uuid.uuid4(), profile_id=profile.id
            )

        assert spec.context_length == 128_000
