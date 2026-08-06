"""Tests for the general secret store and the shapes a secret can take.

The store exists for one concrete need - a custom capability calling an API the
platform knows nothing about - and it is only defensible because of the
constraint: **a secret is referenced, never handed around.** Most of what is
worth testing here is that constraint holding.
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import (
    STORABLE_KINDS,
    ApiKeySecret,
    AwsCredentialsSecret,
    AzureOpenAISecret,
    GcpServiceAccountSecret,
    NoSecret,
    SecretKind,
    SecretRequirement,
    describe_kinds,
    seal_secret,
    unseal_secret,
)
from app.core.vault import VaultScope
from app.services.organization_secret import OrganizationSecretService
from tests.test_model_profiles import service_account_json


def _ctx(org_id=None) -> AuthContext:
    return AuthContext(
        user_id=uuid.uuid4(),
        organization_id=org_id or uuid.uuid4(),
        role=OrgRoleName.OWNER,
    )


def _db():
    db = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    return db


def _row(ctx, value, *, name="Weather API"):
    sealed = seal_secret(value, scope=VaultScope.organization(ctx.organization_id))
    row = MagicMock()
    row.id = uuid.uuid4()
    row.organization_id = ctx.organization_id
    row.name = name
    row.kind = value.kind.value
    row.sealed_secret = sealed.ciphertext
    row.hint = sealed.hint
    row.key_version = sealed.key_version
    return row


class TestSecretKinds:
    def test_none_is_not_a_shape_anyone_can_store(self):
        """The runtime holds "no credential"; nobody saves it as a secret."""
        assert SecretKind.NONE not in STORABLE_KINDS
        assert set(SecretKind) - {SecretKind.NONE} == STORABLE_KINDS

    def test_every_storable_kind_ships_a_form_schema(self):
        """The frontend generates its forms from these, so a missing one is a dead kind."""
        described = {info.kind for info in describe_kinds()}
        assert described == STORABLE_KINDS
        assert all(info.json_schema.get("properties") for info in describe_kinds())

    def test_a_capability_cannot_require_the_absence_of_a_secret(self):
        with pytest.raises(ValidationError):
            SecretRequirement(kind=SecretKind.NONE, description="nothing")

    def test_a_secret_masks_itself_in_a_repr(self):
        """The way a plaintext usually escapes is a model reaching a log line."""
        value = AwsCredentialsSecret(
            aws_access_key_id="AKIAEXAMPLE",
            aws_secret_access_key="do-not-print-me",
            region_name="eu-central-1",
        )
        assert "do-not-print-me" not in repr(value)
        # And `model_dump()` keeps the SecretStr rather than unwrapping it, so
        # dumping a model into a structured log stays harmless.
        assert "do-not-print-me" not in str(value.model_dump())

    def test_a_secret_serialises_to_its_real_value_for_the_vault(self):
        """The one place the plaintext has to appear is on the way into an envelope."""
        value = ApiKeySecret(api_key="sk-live-1234")
        assert "sk-live-1234" in value.model_dump_json()

    def test_an_unknown_field_is_refused_rather_than_ignored(self):
        with pytest.raises(ValidationError):
            ApiKeySecret(api_key="sk", region_name="eu-west-1")

    @pytest.mark.parametrize(
        ("document", "message"),
        [
            ("not json at all", "downloaded JSON"),
            (json.dumps({"type": "authorized_user"}), "not a service account key"),
            (
                json.dumps({"type": "service_account", "project_id": "p"}),
                "missing: client_email, private_key",
            ),
        ],
    )
    def test_a_service_account_is_validated_while_the_form_is_open(self, document, message):
        """Otherwise the paste fails hours later as an authentication error."""
        with pytest.raises(ValidationError, match=message):
            GcpServiceAccountSecret(service_account_json=document)

    def test_a_service_account_reads_its_project_from_the_document(self):
        """Two places to state the project is one place for them to disagree."""
        value = GcpServiceAccountSecret(service_account_json=service_account_json("acme-prod"))
        assert value.project == "acme-prod"

    def test_a_service_account_is_hinted_by_the_account_it_authenticates_as(self):
        """The client email, not the private key - it is what names the account
        in the Google console, and it is not confidential."""
        value = GcpServiceAccountSecret(service_account_json=service_account_json())
        assert value.hint == ".com"

    def test_the_hint_identifies_a_credential_without_exposing_it(self):
        assert ApiKeySecret(api_key="sk-live-abcd9999").hint == "9999"
        assert (
            AwsCredentialsSecret(
                aws_access_key_id="AKIAEXAMPLE7777",
                aws_secret_access_key="never-shown",
                region_name="us-east-1",
            ).hint
            == "7777"
        )
        assert NoSecret().hint == ""

    def test_the_hint_is_taken_from_the_payload_not_from_the_envelope(self):
        """Sealing a JSON document makes the vault's own hint punctuation."""
        sealed = seal_secret(
            ApiKeySecret(api_key="sk-live-abcd5555"),
            scope=VaultScope.organization(uuid.uuid4()),
        )
        assert sealed.hint == "5555"


class TestSealAndOpen:
    def test_a_structured_secret_survives_the_envelope_whole(self):
        scope = VaultScope.organization(uuid.uuid4())
        value = AzureOpenAISecret(
            api_key="azure-1234",
            azure_endpoint="https://demo.openai.azure.com",
            api_version="2024-10-21",
        )
        sealed = seal_secret(value, scope=scope)

        opened = unseal_secret(sealed.ciphertext, kind=SecretKind.AZURE_OPENAI, scope=scope)

        assert opened == value

    def test_an_envelope_whose_kind_disagrees_with_the_row_is_refused(self):
        """A swapped column would otherwise hand the wrong shape to a caller."""
        scope = VaultScope.organization(uuid.uuid4())
        sealed = seal_secret(ApiKeySecret(api_key="sk-1234"), scope=scope)

        with pytest.raises(BadRequestError) as refused:
            unseal_secret(sealed.ciphertext, kind=SecretKind.AWS_CREDENTIALS, scope=scope)

        assert refused.value.details == {"recorded": "aws_credentials", "sealed": "api_key"}


class TestStoringASecret:
    @pytest.mark.anyio
    async def test_the_value_is_sealed_and_only_a_hint_is_kept(self):
        ctx = _ctx()
        with (
            patch(
                "app.services.organization_secret.organization_secret_repo.create",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ) as create,
            patch("app.services.organization_secret.record_audit", new=AsyncMock()) as audit,
        ):
            await OrganizationSecretService(_db()).create(
                ctx, name="Weather API", value=ApiKeySecret(api_key="wx-live-abcd4242")
            )

        stored = create.call_args.kwargs
        assert stored["hint"] == "4242"
        assert "wx-live-abcd4242" not in stored["sealed_secret"]
        assert stored["kind"] == "api_key"
        # The audit trail records what identifies the secret, never the secret.
        assert audit.call_args.kwargs["details"] == {
            "name": "Weather API",
            "kind": "api_key",
            "hint": "4242",
        }

    @pytest.mark.anyio
    async def test_a_taken_name_is_a_conflict_rather_than_a_crash(self):
        with (
            patch(
                "app.services.organization_secret.organization_secret_repo.get_by_name",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "app.services.organization_secret.organization_secret_repo.create",
                new=AsyncMock(),
            ) as create,
            pytest.raises(AlreadyExistsError) as refused,
        ):
            await OrganizationSecretService(_db()).create(
                _ctx(), name="Weather API", value=ApiKeySecret(api_key="wx")
            )

        assert refused.value.status_code == 409
        assert create.await_count == 0

    @pytest.mark.anyio
    async def test_listing_is_scoped_to_the_caller(self):
        ctx = _ctx()
        with patch(
            "app.services.organization_secret.organization_secret_repo.list_secrets",
            new=AsyncMock(return_value=[]),
        ) as listed:
            await OrganizationSecretService(_db()).list_secrets(ctx)

        assert listed.call_args.kwargs["organization_id"] == ctx.organization_id


class TestRotatingASecret:
    @pytest.mark.anyio
    async def test_a_new_value_replaces_the_envelope_and_the_hint(self):
        ctx = _ctx()
        row = _row(ctx, ApiKeySecret(api_key="wx-old-0000"))

        with (
            patch(
                "app.services.organization_secret.organization_secret_repo.get",
                new=AsyncMock(return_value=row),
            ),
            patch(
                "app.services.organization_secret.organization_secret_repo.update",
                new=AsyncMock(return_value=row),
            ) as update,
            patch("app.services.organization_secret.record_audit", new=AsyncMock()) as audit,
        ):
            await OrganizationSecretService(_db()).update(
                ctx, row.id, value=ApiKeySecret(api_key="wx-new-9999")
            )

        written = update.call_args.kwargs["update_data"]
        assert written["hint"] == "9999"
        assert "wx-new-9999" not in written["sealed_secret"]
        assert audit.call_args.kwargs["action"] == "secret.rotated"

    @pytest.mark.anyio
    async def test_a_rotation_cannot_change_the_shape_of_the_secret(self):
        """Agents were published against a capability requiring one shape.

        Swapping an API key for an AWS key pair under a stable id would break
        every one of them at run time, with nothing pointing back at this edit.
        """
        ctx = _ctx()
        row = _row(ctx, ApiKeySecret(api_key="wx-old-0000"))

        with (
            patch(
                "app.services.organization_secret.organization_secret_repo.get",
                new=AsyncMock(return_value=row),
            ),
            patch(
                "app.services.organization_secret.organization_secret_repo.update",
                new=AsyncMock(),
            ) as update,
            pytest.raises(BadRequestError) as refused,
        ):
            await OrganizationSecretService(_db()).update(
                ctx,
                row.id,
                value=AwsCredentialsSecret(
                    aws_access_key_id="AKIA1",
                    aws_secret_access_key="s",
                    region_name="us-east-1",
                ),
            )

        assert "Create a new secret instead" in refused.value.message
        assert update.await_count == 0

    @pytest.mark.anyio
    async def test_a_rename_checks_the_new_name_is_free(self):
        ctx = _ctx()
        row = _row(ctx, ApiKeySecret(api_key="wx-0000"))

        with (
            patch(
                "app.services.organization_secret.organization_secret_repo.get",
                new=AsyncMock(return_value=row),
            ),
            patch(
                "app.services.organization_secret.organization_secret_repo.get_by_name",
                new=AsyncMock(return_value=MagicMock()),
            ),
            pytest.raises(AlreadyExistsError),
        ):
            await OrganizationSecretService(_db()).update(ctx, row.id, name="Taken")

    @pytest.mark.anyio
    async def test_a_rename_and_a_description_are_written_without_touching_the_value(self):
        ctx = _ctx()
        row = _row(ctx, ApiKeySecret(api_key="wx-0000"))

        with (
            patch(
                "app.services.organization_secret.organization_secret_repo.get",
                new=AsyncMock(return_value=row),
            ),
            patch(
                "app.services.organization_secret.organization_secret_repo.get_by_name",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.organization_secret.organization_secret_repo.update",
                new=AsyncMock(return_value=row),
            ) as update,
            patch("app.services.organization_secret.record_audit", new=AsyncMock()) as audit,
        ):
            await OrganizationSecretService(_db()).update(
                ctx, row.id, name="Weather", description="Used by the forecast skill"
            )

        written = update.call_args.kwargs["update_data"]
        assert written == {"name": "Weather", "description": "Used by the forecast skill"}
        assert audit.call_args.kwargs["action"] == "secret.updated"

    @pytest.mark.anyio
    async def test_an_update_with_nothing_in_it_writes_nothing(self):
        ctx = _ctx()
        row = _row(ctx, ApiKeySecret(api_key="wx-0000"))

        with (
            patch(
                "app.services.organization_secret.organization_secret_repo.get",
                new=AsyncMock(return_value=row),
            ),
            patch(
                "app.services.organization_secret.organization_secret_repo.update",
                new=AsyncMock(),
            ) as update,
            patch("app.services.organization_secret.record_audit", new=AsyncMock()) as audit,
        ):
            assert await OrganizationSecretService(_db()).update(ctx, row.id) is row

        assert update.await_count == 0
        assert audit.await_count == 0

    @pytest.mark.anyio
    async def test_a_secret_from_another_organization_is_not_found(self):
        """The repository scopes the read, so a foreign id reads as absent."""
        secret_id = uuid.uuid4()
        with (
            patch(
                "app.services.organization_secret.organization_secret_repo.get",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(NotFoundError) as refused,
        ):
            await OrganizationSecretService(_db()).update(_ctx(), secret_id, name="x")

        assert refused.value.details == {"secret_id": str(secret_id)}


class TestDeletingASecret:
    @pytest.mark.anyio
    async def test_a_deleted_secret_leaves_a_trail(self):
        ctx = _ctx()
        row = _row(ctx, ApiKeySecret(api_key="wx-0000"))

        with (
            patch(
                "app.services.organization_secret.organization_secret_repo.get",
                new=AsyncMock(return_value=row),
            ),
            patch(
                "app.services.organization_secret.organization_secret_repo.delete",
                new=AsyncMock(return_value=True),
            ) as delete,
            patch("app.services.organization_secret.record_audit", new=AsyncMock()) as audit,
        ):
            await OrganizationSecretService(_db()).delete(ctx, row.id)

        assert delete.call_args.kwargs["organization_id"] == ctx.organization_id
        assert audit.call_args.kwargs["action"] == "secret.deleted"
        # A deleted secret is the one record left of it; the value is not in it.
        assert audit.call_args.kwargs["details"] == {"name": row.name, "kind": row.kind}

    @pytest.mark.anyio
    async def test_deleting_one_that_is_not_ours_is_not_found(self):
        with (
            patch(
                "app.services.organization_secret.organization_secret_repo.get",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.organization_secret.organization_secret_repo.delete",
                new=AsyncMock(),
            ) as delete,
            pytest.raises(NotFoundError),
        ):
            await OrganizationSecretService(_db()).delete(_ctx(), uuid.uuid4())

        assert delete.await_count == 0


class TestResolvingForARun:
    @pytest.mark.anyio
    async def test_a_referenced_secret_opens_for_its_own_organization(self):
        ctx = _ctx()
        row = _row(ctx, ApiKeySecret(api_key="wx-live-abcd4242"))

        with patch(
            "app.services.organization_secret.organization_secret_repo.get_many",
            new=AsyncMock(return_value={row.id: row}),
        ):
            resolved = await OrganizationSecretService(_db()).resolve_for_bindings(ctx, [row.id])

        assert resolved[row.id].api_key.get_secret_value() == "wx-live-abcd4242"

    @pytest.mark.anyio
    async def test_a_secret_sealed_for_another_organization_cannot_be_opened(self):
        """The tenant boundary the envelope exists to draw.

        The repository already filters by organization; this proves the second
        lock still holds if a row ever reached the wrong tenant anyway.
        """
        row = _row(_ctx(), ApiKeySecret(api_key="wx-live-abcd4242"))

        with (
            patch(
                "app.services.organization_secret.organization_secret_repo.get_many",
                new=AsyncMock(return_value={row.id: row}),
            ),
            pytest.raises(BadRequestError, match="Failed to decrypt"),
        ):
            await OrganizationSecretService(_db()).resolve_for_bindings(_ctx(), [row.id])

    @pytest.mark.anyio
    async def test_an_id_that_no_longer_resolves_is_simply_absent(self):
        """Whether that matters is the registry's decision, not this one's.

        Only the registry knows which bindings actually required a secret, so a
        missing id becomes a refusal there rather than here.
        """
        with patch(
            "app.services.organization_secret.organization_secret_repo.get_many",
            new=AsyncMock(return_value={}),
        ):
            assert (
                await OrganizationSecretService(_db()).resolve_for_bindings(_ctx(), [uuid.uuid4()])
                == {}
            )

    @pytest.mark.anyio
    async def test_no_ids_means_no_query(self):
        db = _db()
        with patch(
            "app.services.organization_secret.organization_secret_repo.get_many",
            new=AsyncMock(return_value={}),
        ) as get_many:
            assert await OrganizationSecretService(db).resolve_for_bindings(_ctx(), []) == {}

        assert get_many.call_args.args[1] == []


class TestTheKeyThatAsksAProviderForItsCatalog:
    """`listing_key` is the vault's second reader, and the narrower one.

    It exists because the model form's suggestions come from the provider, and
    asking most providers costs a bearer token. The route used to open the vault
    itself - a route module importing the repository, `unseal_secret` and the
    scope - which is the layering #232 is about. What the plaintext is *for* has
    not changed: it goes to the provider, never to the caller.
    """

    @pytest.mark.anyio
    async def test_the_first_api_key_for_that_provider_is_used(self):
        ctx = _ctx()
        row = _row(ctx, ApiKeySecret(api_key="sk-openai-4242"))

        with patch(
            "app.services.organization_secret.organization_secret_repo.list_secrets",
            new=AsyncMock(return_value=[row]),
        ) as list_secrets:
            key = await OrganizationSecretService(_db()).listing_key(ctx, "openai")

        assert key == "sk-openai-4242"
        assert list_secrets.await_args.kwargs["purposes"] == ["openai"]

    @pytest.mark.anyio
    async def test_it_asks_only_for_this_organizations_keys(self):
        """The scope is the service's answer now, not a handler's argument."""
        ctx = _ctx()

        with patch(
            "app.services.organization_secret.organization_secret_repo.list_secrets",
            new=AsyncMock(return_value=[]),
        ) as list_secrets:
            await OrganizationSecretService(_db()).listing_key(ctx, "openai")

        assert list_secrets.await_args.kwargs["organization_id"] == ctx.organization_id

    @pytest.mark.anyio
    async def test_a_credential_that_is_not_a_bearer_token_is_skipped(self):
        """An AWS pair is a signing credential; no listing endpoint accepts one.

        Skipped rather than mangled into a header - and skipped rather than
        returned, so a stored pair does not hide the API key behind it.
        """
        ctx = _ctx()
        pair = _row(
            ctx,
            AwsCredentialsSecret(
                aws_access_key_id="AKIA4242",
                aws_secret_access_key="s3cret",
                region_name="us-east-1",
            ),
        )
        key = _row(ctx, ApiKeySecret(api_key="sk-openai-4242"))

        with patch(
            "app.services.organization_secret.organization_secret_repo.list_secrets",
            new=AsyncMock(return_value=[pair, key]),
        ):
            found = await OrganizationSecretService(_db()).listing_key(ctx, "bedrock")

        assert found == "sk-openai-4242"

    @pytest.mark.anyio
    async def test_no_stored_key_is_not_an_error(self):
        """Providers that publish a public catalog are asked without one."""
        with patch(
            "app.services.organization_secret.organization_secret_repo.list_secrets",
            new=AsyncMock(return_value=[]),
        ):
            assert await OrganizationSecretService(_db()).listing_key(_ctx(), "openrouter") is None
