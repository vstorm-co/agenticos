"""What a secret is for, whose it is, and who can see it.

The vault stored a name, a shape and a value - enough to hand a key to a
capability that already knew which one it wanted, and nothing else. Three things
are now true of every secret, and each closes a specific failure:

- it names a **purpose**, so a model picker can offer the providers this
  organization holds keys for, and a capability can ask for a Tavily key rather
  than for "an API key";
- it has an **owner and a visibility**, so somebody's own trial key and the
  team's shared account stop being the same thing;
- per-row access is resolved against **grants**, not against one permission that
  gated the whole vault.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core import secret_purposes
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.core.secret_kinds import ApiKeySecret, AwsCredentialsSecret, SecretKind
from app.db.models.resource_grant import Visibility
from app.services.organization_secret import OrganizationSecretService

MODULE = "app.services.organization_secret"


def _ctx(role: str = OrgRoleName.OWNER, user_id=None) -> AuthContext:
    return AuthContext(user_id=user_id or uuid.uuid4(), organization_id=uuid.uuid4(), role=role)


def _secret(ctx: AuthContext, **overrides):
    secret = MagicMock()
    secret.id = uuid.uuid4()
    secret.organization_id = ctx.organization_id
    secret.owner_user_id = None
    secret.visibility = Visibility.ORG.value
    secret.purpose = "openai"
    secret.kind = SecretKind.API_KEY.value
    for key, value in overrides.items():
        setattr(secret, key, value)
    return secret


class TestTheCatalog:
    def test_every_model_provider_can_be_keyed(self):
        """Generated from the resolver's own table, so a provider added there
        cannot end up with no way to store a key for it."""
        from app.agents.model_resolver import PROVIDERS

        ids = {entry.id for entry in secret_purposes.all_purposes()}
        assert set(PROVIDERS) <= ids

    def test_each_purpose_declares_the_shape_it_takes(self):
        """The form follows from the service. A purpose with the wrong kind
        would ask for an API key and store something Bedrock cannot use."""
        assert secret_purposes.get("bedrock").kind is SecretKind.AWS_CREDENTIALS
        assert secret_purposes.get("openai").kind is SecretKind.API_KEY

    def test_the_search_services_a_capability_consumes_are_all_offered(self):
        """Web search names these three ids; a purpose missing here is a method
        somebody can pick and then cannot key."""
        from app.agents.capabilities.web_research import KEYED_METHODS

        ids = {entry.id for entry in secret_purposes.all_purposes()}
        assert ids >= KEYED_METHODS

    def test_the_tracing_card_can_offer_a_logfire_token(self):
        """The Builder's Tracing card filters the vault on this id; renaming
        or dropping it silently empties that picker."""
        entry = secret_purposes.get("logfire")
        assert entry is not None
        assert entry.kind is SecretKind.API_KEY

    def test_custom_is_last_and_is_not_a_model_provider(self):
        purposes = secret_purposes.all_purposes()
        assert purposes[-1].id == "custom"
        assert secret_purposes.is_model_provider("custom") is False

    def test_an_unknown_purpose_resolves_to_nothing(self):
        assert secret_purposes.get("not-a-service") is None


class TestStoring:
    @pytest.mark.anyio
    async def test_a_purpose_this_deployment_does_not_offer_is_refused(self):
        with pytest.raises(BadRequestError, match="Unknown purpose"):
            OrganizationSecretService._check_purpose("hotdog-stand", SecretKind.API_KEY)

    @pytest.mark.anyio
    async def test_the_wrong_shape_for_the_service_is_refused(self):
        """Storing an AWS pair as an OpenAI key produces a vault entry that
        reads correctly and fails at the first run."""
        with pytest.raises(BadRequestError, match="api_key"):
            OrganizationSecretService._check_purpose("openai", SecretKind.AWS_CREDENTIALS)

    @pytest.mark.anyio
    async def test_a_private_key_records_its_owner(self):
        """The database refuses a private secret with no owner - a row nobody
        can see and nobody can delete. This is where that is made impossible."""
        ctx = _ctx()
        with (
            patch(
                f"{MODULE}.organization_secret_repo.get_by_name", new=AsyncMock(return_value=None)
            ),
            patch(
                f"{MODULE}.organization_secret_repo.create",
                new=AsyncMock(return_value=_secret(ctx)),
            ) as create,
            patch(f"{MODULE}.record_audit", new=AsyncMock()),
        ):
            await OrganizationSecretService(MagicMock()).create(
                ctx,
                name="My own key",
                value=ApiKeySecret(api_key="sk-personal"),
                purpose="openai",
                visibility=Visibility.PRIVATE,
            )

        assert create.call_args.kwargs["owner_user_id"] == ctx.user_id
        assert create.call_args.kwargs["visibility"] == "private"

    @pytest.mark.anyio
    async def test_an_organization_key_belongs_to_nobody_in_particular(self):
        ctx = _ctx()
        with (
            patch(
                f"{MODULE}.organization_secret_repo.get_by_name", new=AsyncMock(return_value=None)
            ),
            patch(
                f"{MODULE}.organization_secret_repo.create",
                new=AsyncMock(return_value=_secret(ctx)),
            ) as create,
            patch(f"{MODULE}.record_audit", new=AsyncMock()),
        ):
            await OrganizationSecretService(MagicMock()).create(
                ctx,
                name="Team key",
                value=AwsCredentialsSecret(
                    aws_access_key_id="AKIA",
                    aws_secret_access_key="s" * 20,
                    region_name="eu-central-1",
                ),
                purpose="bedrock",
                visibility=Visibility.ORG,
            )

        assert create.call_args.kwargs["owner_user_id"] is None


class TestWhoCanReachOne:
    @pytest.mark.anyio
    async def test_a_key_the_caller_may_not_see_reads_as_missing(self):
        """Not "forbidden": a member must not be able to probe which keys exist
        by watching a 403 turn into a 404."""
        ctx = _ctx(OrgRoleName.MEMBER)
        with (
            patch(
                f"{MODULE}.organization_secret_repo.get",
                new=AsyncMock(return_value=_secret(ctx, visibility=Visibility.PRIVATE.value)),
            ),
            patch(f"{MODULE}.resolve_access", new=AsyncMock(return_value=False)),
            pytest.raises(NotFoundError),
        ):
            await OrganizationSecretService(MagicMock())._get(ctx, uuid.uuid4())

    @pytest.mark.anyio
    async def test_editing_asks_for_edit_and_not_merely_view(self):
        """Reading a key's name and being allowed to rotate it are different
        questions, and a viewer holding a read grant must not get the second."""
        ctx = _ctx()
        secret = _secret(ctx)
        with (
            patch(f"{MODULE}.organization_secret_repo.get", new=AsyncMock(return_value=secret)),
            patch(f"{MODULE}.resolve_access", new=AsyncMock(return_value=True)) as resolve,
            patch(f"{MODULE}.organization_secret_repo.delete", new=AsyncMock()),
            patch(f"{MODULE}.record_audit", new=AsyncMock()),
        ):
            await OrganizationSecretService(MagicMock()).delete(ctx, secret.id)

        assert resolve.call_args.args[3] is Perm.SECRETS_EDIT
