"""A personal API connection is a person's authority, never an organization's spare key."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.api.routes.v1.secrets import create_secret, list_secret_purposes
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.core.secret_kinds import ApiKeySecret, OpenAICodexSecret, SecretKind, seal_secret
from app.core.vault import VaultScope
from app.db.models.credential import ModelProfile
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.resource_grant import GrantLevel, Visibility
from app.schemas.model_profile import ModelProfileRead, ModelProfileUpdate
from app.schemas.secret import SecretCreate, SecretRead
from app.services.access import SECRET, accessible_ids, resolve_access
from app.services.agent_registry import AgentRegistryService
from app.services.embedding_resolution import EmbeddingKeySource, _api_key_for
from app.services.ingestion_config import IngestionConfig, IngestionConfigService, PdfParserName
from app.services.model_profile import ModelProfileService, choosable_for_others
from app.services.openai_codex import OpenAICodexService
from app.services.organization_secret import OrganizationSecretService
from app.services.provider_keys import key_problem
from app.services.sharing import SharingService
from app.worker.tasks.rag_tasks import _connector_credential

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)


def _db() -> AsyncSession:
    return MagicMock(spec=AsyncSession)


def _secret(
    ctx: AuthContext, *, personal: bool = True, provider: str = "openai"
) -> OrganizationSecret:
    sealed = seal_secret(
        ApiKeySecret(api_key="sk-fake-personal-connection-test"),
        scope=VaultScope.organization(ctx.organization_id),
    )
    return OrganizationSecret(
        id=uuid4(),
        organization_id=ctx.organization_id,
        name=f"Connection {uuid4()}",
        kind=SecretKind.API_KEY.value,
        purpose=provider,
        owner_user_id=ctx.user_id,
        created_by_user_id=ctx.user_id,
        visibility=Visibility.PRIVATE.value,
        usage_scope="personal" if personal else "organization",
        sealed_secret=sealed.ciphertext,
        hint=sealed.hint,
        key_version=sealed.key_version,
        created_at=datetime.now(UTC),
    )


def _profile(ctx: AuthContext, secret: OrganizationSecret, *fallbacks: UUID) -> ModelProfile:
    return ModelProfile(
        id=uuid4(),
        organization_id=ctx.organization_id,
        label=f"Model {uuid4()}",
        provider=secret.purpose,
        model="gpt-4.1" if secret.purpose == "openai" else "claude-sonnet-4-6",
        secret_id=secret.id,
        params={},
        fallback_profile_ids=[str(value) for value in fallbacks],
        runs_without_key=False,
        created_at=datetime.now(UTC),
        personal_owner_user_id=secret.owner_user_id if secret.usage_scope == "personal" else None,
    )


def _not_a_direct_person(ctx: AuthContext, origin: str) -> AuthContext:
    match origin:
        case "other-user":
            return replace(ctx, user_id=uuid4())
        case "anonymous":
            return replace(ctx, user_id=None)
        case "api-key":
            return replace(ctx, api_key_id=uuid4())
        case "persisted-key":
            return replace(ctx, key_scopes=frozenset({Perm.AGENTS_RUN}))
        case "empty-key":
            return replace(ctx, key_scopes=frozenset())
        case "publisher":
            return replace(ctx, subject_is_publisher_fallback=True)
        case "impersonated":
            return replace(ctx, is_impersonated=True)
        case "workflow":
            return replace(ctx, is_workflow=True)
        case "channel":
            return replace(ctx, channel_identity_id=uuid4())
        case "schedule" | "event":
            return replace(ctx, fired_as_creator=origin)
        case "routine":
            return replace(ctx, routine_id=uuid4())
        case "routine-policy":
            return replace(ctx, routine_source_policy_id=uuid4())
        case "routine-activation":
            return replace(ctx, routine_activation_id=uuid4())
        case "cross-tenant":
            return replace(ctx, organization_id=uuid4())
        case _:
            raise AssertionError(origin)


_OTHER_ORIGINS = [
    "other-user",
    "anonymous",
    "api-key",
    "persisted-key",
    "empty-key",
    "publisher",
    "impersonated",
    "workflow",
    "channel",
    "schedule",
    "event",
    "routine",
    "routine-policy",
    "routine-activation",
    "cross-tenant",
]


async def test_personal_connection_is_stored_for_its_signed_in_owner() -> None:
    ctx, db = _ctx(), _db()
    row = _secret(ctx, provider="anthropic")
    with (
        patch(
            "app.services.organization_secret.organization_secret_repo.get_by_name",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.organization_secret.organization_secret_repo.create",
            AsyncMock(return_value=row),
        ) as create,
        patch("app.services.organization_secret.record_audit", AsyncMock()),
        patch("app.services.organization_secret.NotificationService", autospec=True),
    ):
        stored = await OrganizationSecretService(db).create(
            ctx,
            name="My Claude API",
            value=ApiKeySecret(api_key="sk-ant-api-fake-test-key"),
            purpose="anthropic",
            visibility=Visibility.PRIVATE,
            usage_scope="personal",
        )
    assert stored is row
    assert create.call_args.kwargs["owner_user_id"] == ctx.user_id
    assert create.call_args.kwargs["usage_scope"] == "personal"
    assert "sk-ant-api-fake-test-key" not in create.call_args.kwargs["sealed_secret"]
    assert "sk-ant-api-fake-test-key" not in SecretRead.model_validate(row).model_dump_json()


@pytest.mark.parametrize(
    "origin", [value for value in _OTHER_ORIGINS if value not in {"other-user", "cross-tenant"}]
)
async def test_personal_create_refuses_stand_in_authority_before_writing(origin: str) -> None:
    ctx = _not_a_direct_person(_ctx(), origin)
    with (
        patch(
            "app.services.organization_secret.organization_secret_repo.create", AsyncMock()
        ) as create,
        pytest.raises(AuthorizationError),
    ):
        await OrganizationSecretService(_db()).create(
            ctx,
            name="Mine",
            value=ApiKeySecret(api_key="sk-fake-test-key"),
            purpose="openai",
            visibility=Visibility.PRIVATE,
            usage_scope="personal",
        )
    create.assert_not_awaited()


@pytest.mark.parametrize("visibility", [Visibility.ORG, Visibility.TEAM])
async def test_personal_create_requires_private_visibility(visibility: Visibility) -> None:
    with pytest.raises(BadRequestError, match="must be private"):
        await OrganizationSecretService(_db()).create(
            _ctx(),
            name="Mine",
            value=ApiKeySecret(api_key="sk-fake-test-key"),
            purpose="openai",
            visibility=visibility,
            usage_scope="personal",
        )


async def test_consumer_claude_token_is_not_an_api_connection() -> None:
    with pytest.raises(BadRequestError, match="Console API key"):
        await OrganizationSecretService(_db()).create(
            _ctx(),
            name="Mine",
            value=ApiKeySecret(api_key="sk-ant-oat01-fake-setup-token"),
            purpose="anthropic",
            visibility=Visibility.PRIVATE,
            usage_scope="personal",
        )


async def test_personal_codex_request_does_not_consume_or_exchange_an_oauth_state() -> None:
    redis = MagicMock()
    service = OpenAICodexService(_db(), redis)
    with (
        patch("app.services.openai_codex.OpenAICodexOAuthFlow") as flow,
        pytest.raises(BadRequestError, match="not enabled"),
    ):
        await service.create(
            _ctx(),
            callback_url="http://localhost:1455/auth/callback?code=fake&state=fake",
            name="ChatGPT",
            description=None,
            visibility=Visibility.PRIVATE,
            usage_scope="personal",
        )
    flow.assert_not_called()
    assert redis.mock_calls == []


async def test_generic_secret_create_cannot_bypass_the_personal_codex_refusal() -> None:
    with pytest.raises(BadRequestError, match="not enabled"):
        await OrganizationSecretService(_db()).create(
            _ctx(),
            name="ChatGPT",
            purpose="openai_codex",
            visibility=Visibility.PRIVATE,
            usage_scope="personal",
            value=OpenAICodexSecret(
                access_token="fake-access-token",
                refresh_token="fake-refresh-token",
                account_id="fake-account",
            ),
        )


@pytest.mark.parametrize("origin", _OTHER_ORIGINS)
async def test_personal_credential_is_refused_before_unseal_for_every_other_authority(
    origin: str,
) -> None:
    owner = _ctx()
    row = _secret(owner)
    profile = _profile(owner, row)
    caller = _not_a_direct_person(owner, origin)
    with (
        patch(
            "app.services.model_profile.organization_secret_repo.get", AsyncMock(return_value=row)
        ),
        patch("app.services.model_profile.unseal_secret") as unseal,
        pytest.raises(AuthorizationError),
    ):
        await ModelProfileService(_db()).resolve_credential(
            owner.organization_id, profile, ctx=caller
        )
    unseal.assert_not_called()


async def test_direct_credential_reader_without_a_person_cannot_open_a_personal_key() -> None:
    ctx = _ctx()
    row = _secret(ctx)
    with (
        patch(
            "app.services.model_profile.organization_secret_repo.get", AsyncMock(return_value=row)
        ),
        patch("app.services.model_profile.unseal_secret") as unseal,
        pytest.raises(AuthorizationError),
    ):
        await ModelProfileService(_db()).resolve_credential(ctx.organization_id, _profile(ctx, row))
    unseal.assert_not_called()


async def test_a_personal_api_connection_builds_the_ordinary_agent_model_for_its_owner() -> None:
    ctx = _ctx()
    row = _secret(ctx)
    profile = _profile(ctx, row)
    with (
        patch(
            "app.services.model_profile.credential_repo.get_profile",
            AsyncMock(return_value=profile),
        ),
        patch(
            "app.services.model_profile.organization_secret_repo.get", AsyncMock(return_value=row)
        ),
    ):
        resolved = await ModelProfileService(_db()).resolve(ctx, profile_id=profile.id)
    assert resolved.profile_id == profile.id
    assert resolved.credential.personal_owner_user_id == ctx.user_id
    assert resolved.build() is not None
    assert "sk-fake-personal-connection-test" not in repr(resolved.credential)


@pytest.mark.parametrize("workflow", [False, True])
async def test_organization_use_private_keys_keep_their_existing_shared_model_behavior(
    workflow: bool,
) -> None:
    owner = _ctx()
    row = _secret(owner, personal=False)
    profile = _profile(owner, row)
    with (
        patch(
            "app.services.model_profile.credential_repo.get_profile",
            AsyncMock(return_value=profile),
        ),
        patch(
            "app.services.model_profile.organization_secret_repo.get", AsyncMock(return_value=row)
        ),
    ):
        service = ModelProfileService(_db())
        resolved = await service.resolve_for_organization(
            owner.organization_id, profile_id=profile.id
        )
        with_context = await service.resolve(
            replace(owner, is_workflow=workflow), profile_id=profile.id
        )
    assert resolved.credential.personal_owner_user_id is None
    assert with_context.credential.personal_owner_user_id is None
    assert choosable_for_others(profile, {profile.id: profile})


@pytest.mark.parametrize("background", [False, True])
async def test_fallbacks_cannot_spend_another_person_or_a_background_jobs_personal_key(
    background: bool,
) -> None:
    ctx = _ctx()
    shared_secret = _secret(ctx, personal=False)
    mine = _secret(ctx)
    theirs = _secret(replace(ctx, user_id=uuid4()))
    own_profile, other_profile = _profile(ctx, mine), _profile(ctx, theirs)
    primary = _profile(ctx, shared_secret, own_profile.id, other_profile.id)
    secrets = {row.id: row for row in [shared_secret, mine, theirs]}
    with (
        patch(
            "app.services.model_profile.credential_repo.get_profile",
            AsyncMock(return_value=primary),
        ),
        patch(
            "app.services.model_profile.credential_repo.get_profiles_by_ids",
            AsyncMock(return_value={own_profile.id: own_profile, other_profile.id: other_profile}),
        ),
        patch(
            "app.services.model_profile.organization_secret_repo.get",
            AsyncMock(side_effect=lambda db, secret_id, **kwargs: secrets[secret_id]),
        ),
    ):
        service = ModelProfileService(_db())
        resolved = (
            await service.resolve_for_organization(ctx.organization_id, profile_id=primary.id)
            if background
            else await service.resolve(ctx, profile_id=primary.id)
        )
    assert len(resolved.fallbacks) == (0 if background else 1)
    assert all(key.personal_owner_user_id == ctx.user_id for key, _ in resolved.fallbacks)
    assert not choosable_for_others(
        primary, {p.id: p for p in [primary, own_profile, other_profile]}
    )


async def test_background_primary_refuses_a_personal_connection() -> None:
    ctx = _ctx()
    row = _secret(ctx)
    profile = _profile(ctx, row)
    with (
        patch(
            "app.services.model_profile.credential_repo.get_profile",
            AsyncMock(return_value=profile),
        ),
        patch(
            "app.services.model_profile.organization_secret_repo.get", AsyncMock(return_value=row)
        ),
        pytest.raises(BadRequestError, match="Background work cannot use"),
    ):
        await ModelProfileService(_db()).resolve_for_organization(
            ctx.organization_id, profile_id=profile.id
        )


async def test_personal_legacy_codex_profile_is_refused_even_for_its_owner() -> None:
    ctx = _ctx()
    row = _secret(ctx, provider="openai_codex")
    row.kind = SecretKind.OPENAI_CODEX.value
    profile = _profile(ctx, row)
    with (
        patch(
            "app.services.model_profile.organization_secret_repo.get", AsyncMock(return_value=row)
        ),
        patch("app.services.model_profile.unseal_secret") as unseal,
        pytest.raises(BadRequestError, match="not supported"),
    ):
        await ModelProfileService(_db()).resolve_credential(ctx.organization_id, profile, ctx=ctx)
    unseal.assert_not_called()


async def test_picker_lists_only_organization_models_and_the_callers_personal_models() -> None:
    ctx = _ctx()
    own = _profile(ctx, _secret(ctx))
    other = _profile(ctx, _secret(replace(ctx, user_id=uuid4())))
    shared = _profile(ctx, _secret(ctx, personal=False))
    with patch(
        "app.services.model_profile.credential_repo.list_profiles",
        AsyncMock(return_value=[own, other, shared]),
    ):
        service = ModelProfileService(_db())
        assert await service.list_profiles(ctx) == [own, shared]
        assert await service.list_profiles(replace(ctx, api_key_id=uuid4())) == [shared]
        assert await service.list_profiles(replace(ctx, is_workflow=True)) == [shared]
    public = ModelProfileRead.model_validate(own).model_dump()
    assert public["usage_scope"] == "personal"
    assert "connection_owner_user_id" not in public
    assert "sealed_secret" not in public


@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_an_admin_cannot_repoint_or_remove_somebody_elses_personal_model(
    operation: str,
) -> None:
    owner = _ctx()
    profile = _profile(owner, _secret(owner))
    other = replace(owner, user_id=uuid4(), is_app_admin=True)
    with (
        patch(
            "app.services.model_profile.credential_repo.get_profile",
            AsyncMock(return_value=profile),
        ),
        pytest.raises(NotFoundError),
    ):
        service = ModelProfileService(_db())
        if operation == "update":
            await service.update_profile(other, profile.id, ModelProfileUpdate(label="Changed"))
        else:
            await service.delete_profile(other, profile.id)


async def test_role_and_resource_grants_do_not_lend_a_personal_connection() -> None:
    owner, db = _ctx(), _db()
    row = _secret(owner)
    other = replace(owner, user_id=uuid4(), is_app_admin=True)
    assert await resolve_access(db, owner, row, Perm.SECRETS_EDIT, resource_type=SECRET)
    assert not await resolve_access(db, other, row, Perm.SECRETS_VIEW, resource_type=SECRET)
    assert await accessible_ids(db, other, [row], Perm.SECRETS_EDIT, resource_type=SECRET) == set()


async def test_even_the_owner_cannot_share_a_personal_connection() -> None:
    ctx, db = _ctx(), _db()
    row = _secret(ctx)
    sharing = SharingService(db)
    with pytest.raises(BadRequestError, match="cannot be shared"):
        await sharing.set_visibility(ctx, row, resource_type=SECRET, visibility=Visibility.ORG)
    with (
        patch("app.services.sharing.member_repo.get", AsyncMock(return_value=MagicMock())),
        patch("app.services.sharing.resource_grant_repo.upsert", AsyncMock()) as grant,
        pytest.raises(BadRequestError, match="cannot be shared"),
    ):
        await sharing.share(
            ctx, row, resource_type=SECRET, subject_user_id=uuid4(), level=GrantLevel.USE
        )
    grant.assert_not_awaited()
    assert row.visibility == "private"


async def test_catalog_selection_requires_the_real_owner_and_implicit_listing_skips_personal_keys() -> (
    None
):
    owner, db = _ctx(), _db()
    personal, shared = _secret(owner), _secret(owner, personal=False)
    service = OrganizationSecretService(db)
    with patch(
        "app.services.organization_secret.organization_secret_repo.get",
        AsyncMock(return_value=personal),
    ):
        assert (
            await service.listing_key(owner, "openai", secret_id=personal.id)
            == "sk-fake-personal-connection-test"
        )
        with pytest.raises(BadRequestError):
            await service.listing_key(
                replace(owner, user_id=uuid4()), "openai", secret_id=personal.id
            )
    with (
        patch(
            "app.services.organization_secret.organization_secret_repo.list_secrets",
            AsyncMock(return_value=[personal, shared]),
        ),
        patch(
            "app.services.organization_secret.unseal_secret",
            return_value=ApiKeySecret(api_key="sk-shared-fake-key"),
        ) as unseal,
    ):
        assert await service.listing_key(owner, "openai") == "sk-shared-fake-key"
    assert unseal.call_count == 1
    assert unseal.call_args.args[0] == shared.sealed_secret


async def test_capability_bindings_cannot_export_a_personal_key_even_in_the_owners_run() -> None:
    ctx = _ctx()
    row = _secret(ctx)
    with (
        patch(
            "app.services.organization_secret.organization_secret_repo.get_many",
            AsyncMock(return_value={row.id: row}),
        ),
        patch("app.services.organization_secret.unseal_secret") as unseal,
    ):
        assert await OrganizationSecretService(_db()).resolve_for_bindings(ctx, [row.id]) == {}
    unseal.assert_not_called()


async def test_voice_and_transcription_cannot_lend_a_personal_model_connection() -> None:
    ctx = _ctx()
    row = _secret(ctx)
    with patch(
        "app.services.organization_secret.organization_secret_repo.get", AsyncMock(return_value=row)
    ):
        service = OrganizationSecretService(_db())
        assert (
            await service.transcription_key(
                ctx.organization_id, row.id, provider="openai", shared=False
            )
            is None
        )
        assert await service.voice_call_key(ctx.organization_id, row.id) is None
        with pytest.raises(BadRequestError, match="only be selected"):
            await service.get_usable(ctx, row.id, kind=SecretKind.API_KEY)
    with patch(
        "app.services.provider_keys.organization_secret_repo.get", AsyncMock(return_value=row)
    ):
        assert "personal model connection" in (
            await key_problem(
                _db(),
                row.id,
                organization_id=ctx.organization_id,
                provider="openai",
                kind=SecretKind.API_KEY,
                feature="voice calls",
                ctx=ctx,
            )
            or ""
        )


async def test_background_embedding_parsing_and_connectors_never_open_personal_keys() -> None:
    ctx = _ctx()
    row = _secret(ctx)
    kb = KnowledgeBase(
        organization_id=ctx.organization_id,
        embedding_secret_id=row.id,
        collection_name="test-personal",
    )
    config = IngestionConfig(pdf_parser=PdfParserName.LLAMAPARSE, llamaparse_secret_id=row.id)
    with (
        patch(
            "app.services.embedding_resolution.organization_secret_repo.get",
            AsyncMock(return_value=row),
        ),
        patch("app.services.embedding_resolution.unseal_secret") as embedding_unseal,
        patch("app.services.ingestion_config.unseal_secret") as parser_unseal,
        patch("app.worker.tasks.rag_tasks.unseal_secret") as connector_unseal,
    ):
        assert await _api_key_for(_db(), kb) == ("", EmbeddingKeySource.SECRET_UNUSABLE)
        with pytest.raises(BadRequestError, match="cannot spend"):
            await IngestionConfigService(_db())._llamaparse_key(ctx.organization_id, config)
        assert await _connector_credential(_db(), row.id, ctx.organization_id) is None
    embedding_unseal.assert_not_called()
    parser_unseal.assert_not_called()
    connector_unseal.assert_not_called()


def test_legacy_requests_keep_organization_usage_by_default() -> None:
    request = SecretCreate(
        name="Shared API",
        value={"kind": "api_key", "api_key": "sk-fake-test-key"},
        purpose="openai",
    )
    assert request.usage_scope == "organization"


async def test_backend_advertises_only_supported_personal_providers_before_any_key_is_submitted() -> (
    None
):
    catalog = await list_secret_purposes()
    assert {entry.id for entry in catalog.items if entry.personal_supported} == {
        "anthropic",
        "openai",
    }


async def test_secret_route_preserves_the_requested_personal_scope() -> None:
    service = MagicMock(spec=OrganizationSecretService)
    service.create = AsyncMock()
    await create_secret(
        SecretCreate(
            name="Mine",
            value={"kind": "api_key", "api_key": "sk-fake-test-key"},
            purpose="openai",
            visibility="private",
            usage_scope="personal",
        ),
        service,
        _ctx(),
    )
    assert service.create.call_args.kwargs["usage_scope"] == "personal"
    assert service.create.call_args.kwargs["visibility"] is Visibility.PRIVATE


@pytest.mark.parametrize(
    "origin", ["other-user", "api-key", "impersonated", "workflow", "schedule"]
)
async def test_publish_refuses_personal_models_and_fallbacks_the_author_cannot_spend(
    origin: str,
) -> None:
    owner = _ctx()
    key = _secret(owner)
    fallback = _profile(owner, key)
    profile = _profile(owner, key, fallback.id)
    by_id = {row.id: row for row in [profile, fallback]}
    caller = _not_a_direct_person(owner, origin)
    with (
        patch(
            "app.services.agent_registry.credential_repo.get_profiles_by_ids",
            AsyncMock(return_value=by_id),
        ),
        patch(
            "app.services.agent_registry.organization_secret_repo.get_many",
            AsyncMock(return_value={key.id: key}),
        ),
    ):
        problems = await AgentRegistryService(_db())._sign_in_problems(
            caller,
            AgentSpec(
                name="Personal agent", instructions="Help the user", model_profile_id=profile.id
            ),
        )
    assert len(problems.messages) == 2
    assert all(field["field"] == "model_profile_id" for field in problems.fields)


async def test_personal_model_metadata_uses_its_selected_connection_only() -> None:
    ctx = _ctx()
    row = _secret(ctx)
    with (
        patch(
            "app.services.model_profile.organization_secret_repo.get", AsyncMock(return_value=row)
        ),
        patch(
            "app.services.model_profile.models_for", AsyncMock(return_value=([], "unlisted"))
        ) as catalog,
    ):
        assert (
            await ModelProfileService(_db())._listed_model(
                ctx,
                "openai",
                "gpt-4.1",
                None,
                row.id,
                personal=True,
            )
            is None
        )
    assert catalog.call_args.kwargs["api_key"] == "sk-fake-personal-connection-test"


async def test_personal_custom_endpoint_key_is_not_tried_at_the_public_provider_for_metadata() -> (
    None
):
    ctx = _ctx()
    with patch("app.services.model_profile.models_for", AsyncMock()) as catalog:
        assert (
            await ModelProfileService(_db())._listed_model(
                ctx,
                "openai",
                "local-model",
                "https://models.example.test/v1",
                uuid4(),
                personal=True,
            )
            is None
        )
    catalog.assert_not_awaited()
