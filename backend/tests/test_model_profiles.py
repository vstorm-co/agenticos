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
from pydantic import ValidationError
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.models.openrouter import OpenRouterModel

from app.agents.model_resolver import (
    PROVIDERS,
    ModelRequestSpec,
    ProviderSpec,
    ResolvedCredential,
    build_model,
    get_provider,
    lacks_key,
)
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    InUseError,
    NotFoundError,
)
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.core.secret_kinds import (
    ApiKeySecret,
    AwsCredentialsSecret,
    AzureOpenAISecret,
    GcpServiceAccountSecret,
    GithubOAuthAppSecret,
    NoSecret,
    OpenAICodexSecret,
    SecretKind,
    seal_secret,
)
from app.core.vault import VaultScope
from app.schemas.model_profile import ModelProfileRead, ModelProfileUpdate
from app.services.model_catalog import CatalogModel
from app.services.model_profile import (
    MAX_FALLBACK_DEPTH,
    ModelProfileService,
    provider_catalog,
    usable_for_agents,
    validate_endpoint_url,
)
from app.services.openai_codex import VaultCodexCredentials


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
    if spec.secret_kind is SecretKind.OPENAI_CODEX:
        return codex_secret()
    return GcpServiceAccountSecret(service_account_json=service_account_json())


def codex_secret() -> OpenAICodexSecret:
    return OpenAICodexSecret(
        access_token="codex-access-1234",
        refresh_token="codex-refresh-1234",
        account_id="account-1234",
    )


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


def _profile(
    ctx, secret=None, model="gpt-4.1", fallbacks=None, provider="openai", base_url=None, api=None
):
    """A stored model profile, keyed from the vault like every real one.

    `base_url` defaults to None explicitly rather than being left to the mock: a
    `MagicMock` attribute is truthy, so it reaches `httpx.URL()` as a mock and
    raises there instead of meaning "the provider's own API", which is what an
    unset endpoint means. `api` likewise, which a mock would fail to validate.
    """
    profile = MagicMock()
    profile.id = uuid.uuid4()
    profile.organization_id = ctx.organization_id
    profile.label = "Test profile"
    profile.provider = provider
    profile.model = model
    profile.secret_id = secret.id if secret else uuid.uuid4()
    profile.base_url = base_url
    profile.api = api
    profile.params = {}
    profile.fallback_profile_ids = [str(pid) for pid in (fallbacks or [])]
    profile.runs_without_key = False
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
            credential_source=VaultCodexCredentials(
                organization_id=uuid.uuid4(), secret_id=uuid.uuid4()
            ),
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

    def test_a_chatgpt_sign_in_builds_the_codex_model_on_its_vault_source(self):
        """The Codex backend, reading and rotating its tokens through the vault."""
        from pydantic_ai.models.openai_codex import OpenAICodexModel

        source = VaultCodexCredentials(organization_id=uuid.uuid4(), secret_id=uuid.uuid4())
        credential = ResolvedCredential(
            provider="openai_codex", secret=codex_secret(), credential_source=source
        )
        model = build_model(credential, "gpt-5.6-luna")

        assert isinstance(model, OpenAICodexModel)
        assert model._provider._credential_source is source

    def test_a_chatgpt_sign_in_with_nowhere_to_store_its_rotation_is_refused(self):
        """Built from the pair alone, its first refresh would retire the stored token.

        The next run would then find the vault holding a refresh token the
        authorization server has already spent, so this refuses instead.
        """
        credential = ResolvedCredential(provider="openai_codex", secret=codex_secret())
        with pytest.raises(BadRequestError, match="rotated tokens"):
            build_model(credential, "gpt-5.6-luna")

    @pytest.mark.parametrize(
        ("provider_id", "api", "wrapper"),
        [
            ("openai", "chat", OpenAIChatModel),
            ("openai", "responses", OpenAIResponsesModel),
            ("azure", "chat", OpenAIChatModel),
            ("azure", "responses", OpenAIResponsesModel),
        ],
    )
    def test_the_profile_api_picks_the_wrapper(self, provider_id, api, wrapper):
        """Neither API is right for every endpoint, so the profile's choice decides.

        OpenAI's newest models answer Chat Completions with a 400, and most
        OpenAI-compatible servers implement nothing else.
        """
        credential = ResolvedCredential(
            provider=provider_id, secret=secret_for(PROVIDERS[provider_id]), api=api
        )
        assert type(build_model(credential, "gpt-6-luna")) is wrapper

    def test_no_api_builds_chat_on_a_provider_that_serves_both(self):
        """`None` is what a provider with one API carries; it never infers Responses.

        `infer_model("openai:...")` would, which would make every vLLM / LM Studio
        endpoint without a stored choice fail.
        """
        credential = ResolvedCredential(
            provider="openai", secret=NoSecret(), base_url="http://vllm:8000/v1"
        )
        assert type(build_model(credential, "llama3.2")) is OpenAIChatModel

    @pytest.mark.security
    def test_a_responses_model_does_not_store_responses_with_the_provider(self):
        """Responses stores every response on OpenAI's side by default; Chat does not.

        Moving a profile to Responses must not start keeping its conversations
        with the provider. It is the model's own setting, so a profile's
        `openai_store` still overrides it.
        """
        credential = ResolvedCredential(
            provider="openai", secret=ApiKeySecret(api_key="sk-test-key"), api="responses"
        )
        assert build_model(credential, "gpt-6-luna").settings == {"openai_store": False}

    def test_a_claude_model_through_openrouter_names_no_cache_ttl(self):
        """Bedrock, one of the hosts OpenRouter routes Claude to, refuses `ttl`.

        Sent, the Architect failed with "cache_control.ephemeral.ttl: Extra inputs
        are not permitted" whenever OpenRouter picked Bedrock. The breakpoint
        itself stays: the prompt is still cached, for the default five minutes.
        """
        credential = ResolvedCredential(
            provider="openrouter", secret=ApiKeySecret(api_key="sk-or-test")
        )
        model = build_model(credential, "anthropic/claude-opus-4.1")

        assert isinstance(model, OpenRouterModel)
        assert model.profile.get("openrouter_supports_cache_control") is True
        assert model._build_cache_control("5m") == {"type": "ephemeral"}

    @pytest.mark.parametrize(
        ("provider_id", "base_url", "expected"),
        [
            ("openai", None, "responses"),
            ("openai", "https://eu.api.openai.com/v1", "chat"),
            ("azure", None, "chat"),
            ("anthropic", None, None),
            ("anthropic", "https://gateway.example.com", None),
        ],
    )
    def test_the_default_api_follows_the_endpoint(self, provider_id, base_url, expected):
        """OpenAI's own endpoint defaults to Responses, a `base_url` to Chat.

        A default only: a regional OpenAI endpoint is a `base_url` that serves
        Responses, which is why the profile stores a choice instead.
        """
        assert PROVIDERS[provider_id].default_api(base_url) == expected

    def test_only_the_openai_apis_offer_a_choice(self):
        offering = {spec.id: spec.apis for spec in PROVIDERS.values() if spec.apis}
        assert offering == {"openai": ("responses", "chat"), "azure": ("responses", "chat")}

    def test_the_catalog_is_ordered_for_a_stable_picker(self):
        names = [spec.name for spec in provider_catalog()]
        assert names == sorted(names, key=str.lower)

    def test_unknown_provider_fails_loudly(self):
        credential = ResolvedCredential(
            provider="myprovider", secret=ApiKeySecret(api_key="sk-test-key")
        )
        with pytest.raises(BadRequestError) as exc:
            build_model(credential, "some-model")
        assert exc.value.details is not None
        assert "supported" in exc.value.details

    @pytest.mark.security
    def test_a_secret_that_is_not_a_provider_credential_is_refused(self):
        """A GitHub OAuth App credential cannot authenticate a model provider.

        Its kind is storable but is not any provider's `secret_kind`, so it can
        only reach the resolver through a mis-wired profile - and coercing its
        client secret into an `api_key` argument would fail far from the cause.
        """
        credential = ResolvedCredential(
            provider="openai",
            secret=GithubOAuthAppSecret(
                client_id="Iv1.0123456789abcdef", client_secret="ghs-live-4242"
            ),
        )
        with pytest.raises(BadRequestError, match="cannot authenticate"):
            build_model(credential, "some-model")

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
                "app.services.model_profile.credential_repo.get_profile",
                new=AsyncMock(return_value=None),
            ) as get,
            patch("app.services.model_profile.credential_repo.delete_profile") as delete,
            patch("app.services.model_profile.record_audit", new=AsyncMock()) as audit,
            pytest.raises(NotFoundError) as refused,
        ):
            ctx = _ctx()
            await ModelProfileService(_db()).delete_profile(ctx, uuid.uuid4())

        assert get.await_args.kwargs == {"organization_id": ctx.organization_id, "for_update": True}
        delete.assert_not_called()
        assert audit.await_count == 0
        assert "Model profile not found" in refused.value.message

    @pytest.mark.anyio
    async def test_a_deleted_profile_leaves_a_trail(self):
        ctx = _ctx()
        profile = _profile(ctx)

        with (
            patch(
                "app.services.model_profile.credential_repo.get_profile",
                new=AsyncMock(return_value=profile),
            ),
            patch(
                "app.services.model_profile.agent_repo.naming_model_profile",
                new=AsyncMock(return_value=[]),
            ) as users,
            patch(
                "app.services.model_profile.credential_repo.delete_profile",
                new=AsyncMock(return_value=True),
            ) as delete,
            patch(
                "app.services.model_profile.organization_repo.stop_proactivity_on",
                new=AsyncMock(),
            ) as stop,
            patch("app.services.model_profile.record_audit", new=AsyncMock()) as audit,
        ):
            await ModelProfileService(_db()).delete_profile(ctx, profile.id)

        assert users.await_args.kwargs == {
            "organization_id": ctx.organization_id,
            "profile_id": profile.id,
        }
        assert delete.call_args.kwargs["organization_id"] == ctx.organization_id
        # Proactivity running on it is switched off with it, not left "on" with no
        # model to run on (Codex on #2324).
        assert stop.await_args.kwargs == {
            "organization_id": ctx.organization_id,
            "model_profile_id": profile.id,
        }
        assert audit.call_args.kwargs["action"] == "model_profile.deleted"
        assert audit.call_args.kwargs["target_id"] == str(profile.id)


def _agent(ctx, name: str, *, status: str = "published") -> MagicMock:
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.organization_id = ctx.organization_id
    agent.name = name
    agent.status = status
    return agent


class TestAModelInUseIsNotDeleted:
    """Deleting the profile agents run on left each of them without a model (#2478)."""

    async def _delete(self, ctx, profile, users, visible):
        with (
            patch(
                "app.services.model_profile.credential_repo.get_profile",
                new=AsyncMock(return_value=profile),
            ),
            patch(
                "app.services.model_profile.agent_repo.naming_model_profile",
                new=AsyncMock(return_value=users),
            ),
            patch(
                "app.services.model_profile.accessible_ids",
                new=AsyncMock(return_value={agent.id for agent in visible}),
            ),
            patch("app.services.model_profile.credential_repo.delete_profile") as delete,
            patch(
                "app.services.model_profile.organization_repo.stop_proactivity_on",
                new=AsyncMock(),
            ) as stop,
            patch("app.services.model_profile.record_audit", new=AsyncMock()) as audit,
            pytest.raises(InUseError) as refused,
        ):
            await ModelProfileService(_db()).delete_profile(ctx, profile.id)
        # Nothing is touched on a refusal: not the row, not proactivity, not the log.
        delete.assert_not_called()
        stop.assert_not_awaited()
        audit.assert_not_awaited()
        return refused.value

    @pytest.mark.anyio
    async def test_the_refusal_names_every_agent_on_it(self):
        ctx = _ctx()
        profile = _profile(ctx)
        users = [_agent(ctx, "Helpdesk"), _agent(ctx, "Researcher")]

        refusal = await self._delete(ctx, profile, users, visible=users)

        assert refusal.status_code == 409
        assert refusal.code == "IN_USE"
        assert "used by 2 agents: Helpdesk, Researcher" in refusal.message
        assert refusal.details == {
            "profile_id": str(profile.id),
            "agents": [{"id": agent.id, "name": agent.name, "archived": False} for agent in users],
            "hidden_agents": 0,
        }

    @pytest.mark.anyio
    async def test_an_agent_the_caller_cannot_see_is_counted_not_named(self):
        ctx = _ctx()
        profile = _profile(ctx)
        seen, private = _agent(ctx, "Helpdesk"), _agent(ctx, "Private payroll")

        refusal = await self._delete(ctx, profile, [seen, private], visible=[seen])

        assert "Private payroll" not in refusal.message
        assert "used by 2 agents: Helpdesk and 1 you cannot see" in refusal.message
        assert refusal.details["agents"] == [{"id": seen.id, "name": "Helpdesk", "archived": False}]
        assert refusal.details["hidden_agents"] == 1

    @pytest.mark.anyio
    async def test_an_archived_agent_is_marked_with_what_to_do_about_it(self):
        """An archived agent cannot publish, so "move them" alone is advice it
        cannot follow where it is (#2478)."""
        ctx = _ctx()
        profile = _profile(ctx)
        live, old = _agent(ctx, "Helpdesk"), _agent(ctx, "Old helpdesk", status="archived")

        refusal = await self._delete(ctx, profile, [live, old], visible=[live, old])

        assert refusal.message.endswith(
            "1 of them is archived: delete those, or restore and move them."
        )
        assert [agent["archived"] for agent in refusal.details["agents"]] == [False, True]

    @pytest.mark.anyio
    async def test_only_hidden_agents_still_refuse_without_naming_any(self):
        ctx = _ctx()
        profile = _profile(ctx)

        refusal = await self._delete(ctx, profile, [_agent(ctx, "Secret")], visible=[])

        assert refusal.message.startswith("Model 'Test profile' is used by 1 agent. Move")
        assert refusal.details["agents"] == []
        assert refusal.details["hidden_agents"] == 1


_STORED = object()


class TestEditingAProfileInPlace:
    """A key or endpoint change keeps the id every agent names (#2478)."""

    async def _update(self, ctx, profile, changes, *, secret=_STORED, visible=True, taken=None):
        if secret is _STORED:
            # The key the profile already has, visible to the caller unless a test
            # says otherwise - an endpoint change looks it up again.
            secret = _vault_secret(ctx, purpose=profile.provider)
            secret.id = profile.secret_id
        with (
            patch(
                "app.services.model_profile.credential_repo.get_profile",
                new=AsyncMock(return_value=profile),
            ),
            patch(
                "app.services.model_profile.credential_repo.get_profile_by_label",
                new=AsyncMock(return_value=taken),
            ),
            patch(
                "app.services.model_profile.organization_secret_repo.get",
                new=AsyncMock(return_value=secret),
            ),
            patch(
                "app.services.model_profile.resolve_access", new=AsyncMock(return_value=visible)
            ) as access,
            patch(
                "app.services.model_profile.credential_repo.update_profile",
                new=AsyncMock(side_effect=lambda _db, **kwargs: kwargs["profile"]),
            ) as update,
            patch("app.services.model_profile.record_audit", new=AsyncMock()) as audit,
        ):
            result = await ModelProfileService(_db()).update_profile(
                ctx, profile.id, ModelProfileUpdate.model_validate(changes)
            )
        return result, update, audit, access

    @pytest.mark.anyio
    async def test_a_new_key_is_written_onto_the_same_profile_and_audited_by_field(self):
        ctx = _ctx()
        profile = _profile(ctx, api="responses")
        secret = _vault_secret(ctx, purpose="openai")

        result, update, audit, access = await self._update(
            ctx, profile, {"secret_id": str(secret.id)}, secret=secret
        )

        assert result is profile
        assert update.await_args.kwargs["update_data"] == {"secret_id": secret.id}
        assert update.await_args.kwargs["organization_id"] == ctx.organization_id
        assert access.await_args.args[2] is secret
        assert audit.await_args.kwargs["action"] == "model_profile.updated"
        assert audit.await_args.kwargs["target_id"] == str(profile.id)
        # The names of what changed, never the values: an endpoint can carry
        # more than a host, and a key id says which secret moved.
        assert audit.await_args.kwargs["details"] == {"fields": ["secret_id"]}

    @pytest.mark.anyio
    async def test_a_profile_from_another_organization_is_not_found(self):
        with (
            patch(
                "app.services.model_profile.credential_repo.get_profile",
                new=AsyncMock(return_value=None),
            ) as get,
            patch("app.services.model_profile.credential_repo.update_profile") as update,
            pytest.raises(NotFoundError),
        ):
            ctx = _ctx()
            await ModelProfileService(_db()).update_profile(
                ctx, uuid.uuid4(), ModelProfileUpdate(label="Mine now")
            )
        assert get.await_args.kwargs == {"organization_id": ctx.organization_id, "for_update": True}
        update.assert_not_called()

    @pytest.mark.anyio
    async def test_a_key_for_another_provider_is_refused(self):
        ctx = _ctx()
        secret = _vault_secret(ctx, purpose="anthropic")
        with pytest.raises(BadRequestError) as refused:
            await self._update(ctx, _profile(ctx), {"secret_id": str(secret.id)}, secret=secret)
        assert "for anthropic, not openai" in refused.value.message

    @pytest.mark.anyio
    @pytest.mark.parametrize("exists", [True, False])
    async def test_a_key_the_caller_cannot_see_reads_like_one_that_does_not_exist(self, exists):
        ctx = _ctx()
        secret = _vault_secret(ctx)
        with pytest.raises(BadRequestError) as refused:
            await self._update(
                ctx,
                _profile(ctx),
                {"secret_id": str(secret.id)},
                secret=secret if exists else None,
                visible=False,
            )
        assert refused.value.message == "That key is not in this organization's vault"

    @pytest.mark.anyio
    async def test_removing_the_key_of_a_model_with_nowhere_else_to_go_is_refused(self):
        ctx = _ctx()
        with pytest.raises(BadRequestError) as refused:
            await self._update(ctx, _profile(ctx), {"secret_id": None})
        assert refused.value.details["fields"][0]["field"] == "base_url"

    @pytest.mark.anyio
    async def test_a_keyed_provider_cannot_lose_its_key(self):
        ctx = _ctx()
        profile = _profile(ctx, provider="anthropic", model="claude-opus-5")
        with pytest.raises(BadRequestError) as refused:
            await self._update(ctx, profile, {"secret_id": None})
        assert refused.value.details["fields"][0]["field"] == "secret_id"

    @pytest.mark.anyio
    async def test_a_self_hosted_model_drops_its_key_and_keeps_its_endpoint(self):
        ctx = _ctx()
        profile = _profile(
            ctx, provider="ollama", model="llama4", base_url="http://ollama:11434/v1"
        )

        _, update, _, access = await self._update(ctx, profile, {"secret_id": None})

        # Saved with no key on purpose, so a later look cannot take it for a
        # profile whose key was deleted.
        assert update.await_args.kwargs["update_data"] == {
            "secret_id": None,
            "runs_without_key": True,
        }
        access.assert_not_awaited()

    @pytest.mark.anyio
    async def test_an_edit_that_leaves_a_deleted_key_alone_keeps_it_missing(self):
        ctx = _ctx()
        # A gateway profile whose key was deleted: `ON DELETE SET NULL` cleared
        # the key and left the endpoint and `runs_without_key` false.
        profile = _profile(ctx, base_url="https://gateway.example/v1", api="chat")
        profile.secret_id = None

        _, update, _, _ = await self._update(ctx, profile, {"label": "Gateway"}, secret=None)

        # A rename says nothing about the key; marking it keyless would offer the
        # profile again and send every run to the gateway with no key.
        assert update.await_args.kwargs["update_data"] == {"label": "Gateway"}

    @pytest.mark.anyio
    async def test_an_endpoint_is_refused_for_a_provider_that_has_none(self):
        ctx = _ctx()
        profile = _profile(ctx, provider="openrouter", model="openai/gpt-5")
        with pytest.raises(BadRequestError) as refused:
            await self._update(ctx, profile, {"base_url": "https://gateway.example/v1"})
        assert refused.value.details["fields"][0]["field"] == "base_url"

    @pytest.mark.anyio
    async def test_an_endpoint_with_credentials_in_it_is_refused_without_echoing_it(self):
        ctx = _ctx()
        with pytest.raises(BadRequestError) as refused:
            await self._update(ctx, _profile(ctx), {"base_url": "https://u:hunter2@gw.example/v1"})
        assert "hunter2" not in str(refused.value.details)
        assert "hunter2" not in refused.value.message

    @pytest.mark.anyio
    async def test_an_api_choice_is_refused_where_there_is_none(self):
        ctx = _ctx()
        profile = _profile(ctx, provider="anthropic", model="claude-opus-5")
        with pytest.raises(BadRequestError) as refused:
            await self._update(ctx, profile, {"api": "chat"})
        assert refused.value.details["fields"][0]["field"] == "api"

    @pytest.mark.anyio
    async def test_a_new_endpoint_rechecks_the_key_and_moves_a_default_api(self):
        ctx = _ctx()
        profile = _profile(ctx, api="responses")

        _, update, audit, access = await self._update(
            ctx, profile, {"base_url": "https://eu.api.openai.com/v1"}
        )

        # Responses was only the provider's own endpoint's default; an endpoint of
        # the caller's gets Chat Completions unless it says otherwise.
        assert update.await_args.kwargs["update_data"] == {
            "base_url": "https://eu.api.openai.com/v1",
            "api": "chat",
        }
        # The endpoint is where the key goes, so the stored key is looked up again.
        access.assert_awaited_once()
        assert audit.await_args.kwargs["details"] == {"fields": ["api", "base_url"]}

    @pytest.mark.anyio
    async def test_a_new_endpoint_for_a_key_the_caller_cannot_see_is_refused(self):
        """The endpoint is where the key is sent. Moving a model keyed by a
        colleague's private key to the caller's own host would hand them that key
        on the next run, so it is the same refusal as choosing the key."""
        ctx = _ctx()
        profile = _profile(ctx)

        with pytest.raises(BadRequestError) as refused:
            await self._update(
                ctx, profile, {"base_url": "https://attacker.example/v1"}, visible=False
            )

        assert refused.value.message == "That key is not in this organization's vault"

    @pytest.mark.anyio
    async def test_a_label_or_api_change_does_not_look_the_key_up_again(self):
        ctx = _ctx()
        profile = _profile(ctx, api="responses")

        _, update, _, access = await self._update(
            ctx, profile, {"label": "Prod", "api": "chat"}, visible=False
        )

        assert update.await_args.kwargs["update_data"] == {"label": "Prod", "api": "chat"}
        access.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_default_api_follows_a_new_endpoint_and_a_chosen_one_stays(self):
        ctx = _ctx()
        defaulted = _profile(ctx, base_url="https://gw.example/v1", api="chat")
        chosen = _profile(ctx, base_url="https://gw.example/v1", api="responses")

        _, moved, _, _ = await self._update(ctx, defaulted, {"base_url": None})
        _, kept, _, _ = await self._update(ctx, chosen, {"base_url": "https://gw2.example/v1"})

        # Chat Completions was only the gateway's default; OpenAI's own endpoint
        # gets Responses, as on creation.
        assert moved.await_args.kwargs["update_data"] == {"base_url": None, "api": "responses"}
        assert kept.await_args.kwargs["update_data"] == {"base_url": "https://gw2.example/v1"}

    @pytest.mark.anyio
    async def test_a_null_api_stores_the_default_for_the_new_endpoint(self):
        ctx = _ctx()
        profile = _profile(ctx, api="responses")

        _, update, _, _ = await self._update(
            ctx, profile, {"base_url": "http://vllm:8000/v1", "api": None}
        )

        assert update.await_args.kwargs["update_data"] == {
            "base_url": "http://vllm:8000/v1",
            "api": "chat",
        }

    @pytest.mark.anyio
    async def test_clearing_the_endpoint_keeps_an_api_that_is_already_the_native_one(self):
        ctx = _ctx()
        profile = _profile(ctx, base_url="https://gw.example/v1", api="responses")

        _, update, _, _ = await self._update(ctx, profile, {"base_url": None})

        assert update.await_args.kwargs["update_data"] == {"base_url": None}

    @pytest.mark.anyio
    async def test_a_taken_label_is_a_conflict(self):
        ctx = _ctx()
        with pytest.raises(AlreadyExistsError) as refused:
            await self._update(ctx, _profile(ctx), {"label": "Prod"}, taken=MagicMock())
        assert refused.value.details == {"label": "Prod"}

    @pytest.mark.anyio
    async def test_a_new_label_and_params_are_written(self):
        ctx = _ctx()
        profile = _profile(ctx)

        _, update, audit, _ = await self._update(
            ctx, profile, {"label": "Prod", "params": {"temperature": 0.2}}
        )

        assert update.await_args.kwargs["update_data"] == {
            "label": "Prod",
            "params": {"temperature": 0.2},
        }
        assert audit.await_args.kwargs["details"] == {"fields": ["label", "params"]}

    @pytest.mark.anyio
    async def test_an_edit_that_changes_nothing_writes_and_records_nothing(self):
        ctx = _ctx()
        profile = _profile(ctx)

        result, update, audit, _ = await self._update(
            ctx,
            profile,
            {"label": profile.label, "secret_id": str(profile.secret_id), "base_url": None},
        )

        assert result is profile
        update.assert_not_awaited()
        audit.assert_not_awaited()


class TestAProfileWithoutAKey:
    """A key deleted from the vault leaves its profiles behind with nothing to send (#2478)."""

    @pytest.mark.parametrize(
        ("provider", "secret_id", "base_url", "on_purpose", "missing"),
        [
            ("openai", None, None, False, True),
            ("anthropic", None, None, False, True),
            ("ollama", None, "http://ollama:11434/v1", True, False),
            ("openai", None, "http://vllm:8000/v1", True, False),
            # A gateway profile that had a key and lost it keeps its endpoint;
            # only the stored intent tells it from one that never needed one.
            ("openai", None, "http://gw.example/v1", False, True),
            ("anthropic", None, "https://gw.example", True, True),
            ("openai", uuid.uuid4(), None, False, False),
            ("not-a-provider", None, "http://x", True, True),
        ],
    )
    def test_the_listing_says_which_have_nothing_to_authenticate_with(
        self, provider, secret_id, base_url, on_purpose, missing
    ):
        read = ModelProfileRead(
            id=uuid.uuid4(),
            label="x",
            provider=provider,
            model="m",
            secret_id=secret_id,
            base_url=base_url,
            runs_without_key=on_purpose,
            created_at=datetime(2026, 10, 27, tzinfo=UTC),
        )
        assert read.missing_key is missing
        assert (
            lacks_key(provider, secret_id=secret_id, base_url=base_url, runs_without_key=on_purpose)
            is missing
        )

    @pytest.mark.parametrize(
        ("model", "secret", "usable"),
        [("gpt-4.1", True, True), ("gpt-4.1", False, False), ("gpt-4o-mini-tts", True, False)],
    )
    def test_an_agent_runs_only_on_a_chat_model_with_a_key(self, model, secret, usable):
        ctx = _ctx()
        profile = _profile(ctx, model=model)
        if not secret:
            profile.secret_id = None
        assert usable_for_agents(profile) is usable


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
    async def test_a_fallback_on_a_speech_model_is_left_out_of_the_chain(self):
        """A provider failure must not hand the conversation to a model that
        cannot hold one (#2487). Publish refuses such a fallback; this covers one
        added to the profile afterwards. A custom endpoint is unknown, so kept."""
        ctx = _ctx()
        secret = _vault_secret(ctx)
        speech = _profile(ctx, secret, model="gpt-4o-mini-tts")
        custom = _profile(ctx, secret, model="whisper-1", base_url="http://vllm:8000/v1")
        profile = _profile(ctx, secret, fallbacks=[speech.id, custom.id])

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
                new=AsyncMock(return_value={speech.id: speech, custom.id: custom}),
            ),
        ):
            spec = await ModelProfileService(_db()).resolve(ctx, profile_id=profile.id)

        assert [model for _, model in spec.fallbacks] == ["whisper-1"]

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


class TestASignInIsItsOwnersAlone:
    """A ChatGPT sign-in is one person's subscription: a model shared with the
    organization must not lend everybody that person's plan."""

    @staticmethod
    def _spec(primary: ResolvedCredential, *fallbacks: ResolvedCredential) -> ModelRequestSpec:
        return ModelRequestSpec(
            profile_id=uuid.uuid4(),
            label="ChatGPT",
            provider="openai_codex",
            model="gpt-5.6",
            params={},
            credential=primary,
            secret_id=None,
            fallbacks=[(fallback, "gpt-5.6") for fallback in fallbacks],
        )

    @staticmethod
    def _sign_in() -> ResolvedCredential:
        return ResolvedCredential(
            provider="openai_codex",
            secret=codex_secret(),
            credential_source=VaultCodexCredentials(
                organization_id=uuid.uuid4(), secret_id=uuid.uuid4()
            ),
        )

    @staticmethod
    def _key() -> ResolvedCredential:
        return ResolvedCredential(provider="openai", secret=ApiKeySecret(api_key="sk-test-123456"))

    async def _resolve(self, spec: ModelRequestSpec, *, sees: bool, ctx: AuthContext | None = None):
        with (
            patch.object(ModelProfileService, "_resolve_in", AsyncMock(return_value=spec)),
            patch.object(VaultCodexCredentials, "visible_to", AsyncMock(return_value=sees)),
        ):
            return await ModelProfileService(_db()).resolve(ctx or _ctx())

    @pytest.mark.anyio
    async def test_its_owner_runs_on_it(self):
        spec = self._spec(self._sign_in())
        assert await self._resolve(spec, sees=True) is spec

    @pytest.mark.anyio
    async def test_anybody_else_is_refused_by_the_model_s_name(self):
        with pytest.raises(AuthorizationError) as exc:
            await self._resolve(self._spec(self._sign_in()), sees=False)
        assert "Model 'ChatGPT'" in exc.value.message

    @pytest.mark.anyio
    async def test_a_caller_with_no_person_behind_it_reaches_nobody_s(self):
        ctx = AuthContext(user_id=None, organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)
        with pytest.raises(AuthorizationError):
            await self._resolve(self._spec(self._sign_in()), sees=True, ctx=ctx)

    @pytest.mark.anyio
    async def test_a_fallback_on_somebody_s_sign_in_is_left_out_of_the_chain(self):
        key = self._key()
        resolved = await self._resolve(self._spec(key, self._sign_in(), key), sees=False)
        assert [credential for credential, _ in resolved.fallbacks] == [key]

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "stand_in",
        [
            {"subject_is_publisher_fallback": True},
            {"api_key_id": uuid.uuid4()},
            {"key_scopes": frozenset({Perm.AGENTS_RUN})},
            {"key_scopes": frozenset()},
        ],
        ids=[
            "visitor-as-publisher",
            "key-holder-as-issuer",
            "persisted-key-ceiling",
            "empty-key-ceiling",
        ],
    )
    @pytest.mark.security
    async def test_a_stand_in_for_somebody_else_reaches_nobody_s(self, stand_in):
        """The publisher behind a public page, or a key's issuer, is the account a
        run is billed to - not the person asking, whose subscription it is not."""
        ctx = AuthContext(
            user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER, **stand_in
        )
        with pytest.raises(AuthorizationError):
            await self._resolve(self._spec(self._sign_in()), sees=True, ctx=ctx)

    @pytest.mark.anyio
    @pytest.mark.security
    async def test_a_restored_key_keeps_api_credentials_but_not_a_private_fallback(self):
        ctx = AuthContext(
            user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            role=OrgRoleName.OWNER,
            key_scopes=frozenset({Perm.AGENTS_RUN}),
        )
        key = self._key()
        resolved = await self._resolve(self._spec(key, self._sign_in(), key), sees=True, ctx=ctx)
        assert [credential for credential, _ in resolved.fallbacks] == [key]

    @pytest.mark.anyio
    async def test_background_work_never_runs_on_one(self):
        """Ingestion describing a document's images is nobody's run, long after the
        upload: a collection editor must not route it through another member's
        subscription."""
        with (
            patch.object(
                ModelProfileService,
                "_resolve_in",
                AsyncMock(return_value=self._spec(self._sign_in())),
            ),
            pytest.raises(BadRequestError, match="background work cannot use"),
        ):
            await ModelProfileService(_db()).resolve_for_organization(uuid.uuid4())

        key = self._key()
        with patch.object(
            ModelProfileService,
            "_resolve_in",
            AsyncMock(return_value=self._spec(key, self._sign_in(), key)),
        ):
            resolved = await ModelProfileService(_db()).resolve_for_organization(uuid.uuid4())
        assert [credential for credential, _ in resolved.fallbacks] == [key]

    @pytest.mark.anyio
    async def test_a_key_is_the_agent_s_whoever_runs_it(self):
        spec = self._spec(self._key(), self._key())
        assert await self._resolve(spec, sees=False) is spec


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
            resolved = await ModelProfileService(_db()).resolve_credential(
                ctx.organization_id, profile
            )

        assert resolved.secret.api_key.get_secret_value() == "sk-vault-abcd1234"
        # A vault secret carries no endpoint; a base URL would silently point a
        # provider's own client at somebody else's host.
        assert resolved.base_url is None

    @pytest.mark.anyio
    async def test_a_chatgpt_sign_in_resolves_with_its_place_in_the_vault(self):
        """The provider is handed where the pair lives, not only the pair.

        A refresh spends the refresh token it presents, so the provider must be
        able to read the current pair and write the next one under this id.
        """
        ctx = _ctx()
        secret = _vault_secret(ctx, purpose="openai_codex", value=codex_secret())
        secret.kind = SecretKind.OPENAI_CODEX.value
        profile = _profile(ctx, secret, provider="openai_codex")

        with patch(
            "app.services.model_profile.organization_secret_repo.get",
            new=AsyncMock(return_value=secret),
        ):
            resolved = await ModelProfileService(_db()).resolve_credential(
                ctx.organization_id, profile
            )

        source = resolved.credential_source
        assert isinstance(source, VaultCodexCredentials)
        assert (source.organization_id, source.secret_id) == (ctx.organization_id, secret.id)

    @pytest.mark.anyio
    async def test_an_api_key_resolves_with_no_source_to_rotate_into(self):
        ctx = _ctx()
        secret = _vault_secret(ctx)
        profile = _profile(ctx, secret)

        with patch(
            "app.services.model_profile.organization_secret_repo.get",
            new=AsyncMock(return_value=secret),
        ):
            resolved = await ModelProfileService(_db()).resolve_credential(
                ctx.organization_id, profile
            )

        assert resolved.credential_source is None

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
            await ModelProfileService(_db()).resolve_credential(ctx.organization_id, profile)

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
    `resolve_credential` returned `base_url=None` unconditionally and the
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
        profile.runs_without_key = True
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


class TestTheApiAProfileUses:
    """Which of OpenAI's two APIs a profile's requests go to, stored on the profile.

    It was decided for every `openai` profile at once - Chat Completions, for
    the OpenAI-compatible servers behind a `base_url` - so a profile on
    OpenAI's newest models, which are served on Responses only, failed at its
    first request with a 400. Deciding by `base_url` instead would be wrong for
    a regional OpenAI endpoint, which has one and serves Responses.
    """

    @staticmethod
    async def _written(ctx, *, provider="openai", **fields):
        """Create a keyed profile and return what reached the repository."""
        secret = _vault_secret(ctx, purpose=provider)
        with (
            patch(
                "app.services.model_profile.organization_secret_repo.get",
                new=AsyncMock(return_value=secret),
            ),
            patch(
                "app.services.model_profile.credential_repo.create_profile",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ) as create,
            patch("app.services.model_profile.record_audit", new=AsyncMock()),
        ):
            await ModelProfileService(_db()).create_profile(
                ctx, label="p", provider=provider, model="m", secret_id=secret.id, **fields
            )
        return create.call_args.kwargs

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("base_url", "stored"),
        [(None, "responses"), ("https://gateway.example.com/v1", "chat")],
    )
    async def test_an_omitted_api_is_stored_as_the_default(self, base_url, stored):
        """Written down, so a later change of default cannot move this profile."""
        written = await self._written(_ctx(), base_url=base_url)
        assert written["api"] == stored

    @pytest.mark.anyio
    async def test_a_chosen_api_wins_over_the_endpoint_default(self):
        """A regional OpenAI endpoint is a `base_url` that serves Responses."""
        written = await self._written(
            _ctx(), base_url="https://eu.api.openai.com/v1", api="responses"
        )
        assert written["api"] == "responses"

    @pytest.mark.anyio
    async def test_a_provider_with_one_api_stores_none(self):
        written = await self._written(_ctx(), provider="anthropic")
        assert written["api"] is None

    @pytest.mark.anyio
    async def test_a_choice_for_a_provider_with_one_api_is_refused_on_its_field(self):
        """Accepted, it would be a setting that changes nothing about the request."""
        with (
            patch(
                "app.services.model_profile.credential_repo.create_profile", new=AsyncMock()
            ) as create,
            pytest.raises(BadRequestError) as exc,
        ):
            await ModelProfileService(_db()).create_profile(
                _ctx(),
                label="p",
                provider="anthropic",
                model="claude-sonnet-5",
                secret_id=uuid.uuid4(),
                api="chat",
            )

        assert exc.value.details == {
            "provider": "anthropic",
            "fields": [{"field": "api", "message": exc.value.message}],
        }
        assert create.await_count == 0

    @pytest.mark.anyio
    async def test_the_stored_api_reaches_the_keyed_credential(self):
        ctx = _ctx()
        secret = _vault_secret(ctx)
        profile = _profile(ctx, secret=secret, api="responses")

        with patch(
            "app.services.model_profile.organization_secret_repo.get",
            new=AsyncMock(return_value=secret),
        ):
            credential = await ModelProfileService(_db()).resolve_credential(
                ctx.organization_id, profile
            )

        assert credential.api == "responses"

    @pytest.mark.anyio
    async def test_the_stored_api_reaches_the_keyless_credential(self):
        """A vLLM without a key, on the API it implements."""
        ctx = _ctx()
        profile = _profile(ctx, base_url="http://vllm:8000/v1", api="chat")
        profile.secret_id = None
        profile.runs_without_key = True

        credential = await ModelProfileService(_db()).resolve_credential(
            ctx.organization_id, profile
        )

        assert credential.api == "chat"

    @pytest.mark.anyio
    async def test_a_stored_value_it_never_wrote_fails_loudly(self):
        """Not built as Chat Completions by default: the column holds a bug."""
        ctx = _ctx()
        profile = _profile(ctx, base_url="http://vllm:8000/v1", api="realtime")
        profile.secret_id = None
        profile.runs_without_key = True

        with pytest.raises(ValidationError):
            await ModelProfileService(_db()).resolve_credential(ctx.organization_id, profile)


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
            api=None,
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
