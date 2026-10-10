"""ApiKeyService paths the end-to-end tests do not reach: presets, listing, revocation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.routing import APIRoute

from app.api.public_api import INTERNAL, PUBLIC, is_public_route
from app.core.exceptions import AuthenticationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.api_key import ApiKey
from app.db.models.user import User
from app.schemas.api_key import ApiKeyCreate
from app.services.api_key import ApiKeyService, is_api_key

pytestmark = pytest.mark.anyio

PATH = "app.services.api_key"


def _ctx(role: str = OrgRoleName.MEMBER, user_id: uuid.UUID | None = None) -> AuthContext:
    return AuthContext(user_id=user_id or uuid.uuid4(), organization_id=uuid.uuid4(), role=role)


def _key(ctx: AuthContext, **overrides: Any) -> ApiKey:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "organization_id": ctx.organization_id,
        "user_id": ctx.user_id,
        "name": "script",
        "prefix": "aos_0123abcd",
        "key_hash": "0" * 64,
        "scopes": ["agents:view"],
        "expires_at": None,
        "last_used_at": None,
        "revoked_at": None,
        "created_at": datetime(2026, 10, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return ApiKey(**values)


class TestPresets:
    def test_a_member_s_presets_hold_only_what_a_member_holds(self) -> None:
        catalog = ApiKeyService(MagicMock()).scope_catalog(_ctx(OrgRoleName.MEMBER))

        presets = {preset.id: set(preset.scopes) for preset in catalog.presets}
        assert "runs:view" not in presets["read_only"]
        assert presets["knowledge_ingest"] == {"collections:view", "collections:edit"}
        assert presets["full_access"] == set(catalog.scopes)
        # Keys never manage keys.
        assert "api_keys:create" not in catalog.scopes

    def test_a_preset_left_with_nothing_is_not_offered(self) -> None:
        catalog = ApiKeyService(MagicMock()).scope_catalog(_ctx(OrgRoleName.VIEWER))

        assert "knowledge_ingest" not in {preset.id for preset in catalog.presets}

    def test_a_role_that_holds_nothing_is_offered_nothing(self) -> None:
        catalog = ApiKeyService(MagicMock()).scope_catalog(_ctx("departed"))

        assert catalog.scopes == []
        assert catalog.presets == []


class TestCreating:
    async def test_an_expiry_in_the_past_is_refused_on_its_field(self) -> None:
        with pytest.raises(BadRequestError) as refused:
            await ApiKeyService(MagicMock()).create(
                _ctx(),
                ApiKeyCreate(
                    name="x",
                    scopes=[Perm.AGENTS_VIEW],
                    expires_at=datetime.now(UTC) - timedelta(days=1),
                ),
            )
        assert refused.value.details["fields"][0]["field"] == "expires_at"


class TestListing:
    async def test_a_manager_lists_every_key_and_a_member_their_own(self) -> None:
        listed = AsyncMock(return_value=[])
        with patch(f"{PATH}.api_key_repo.list_for_organization", new=listed):
            await ApiKeyService(MagicMock()).list_keys(_ctx(OrgRoleName.ADMIN))
            member = _ctx(OrgRoleName.MEMBER)
            await ApiKeyService(MagicMock()).list_keys(member)

        assert listed.await_args_list[0].kwargs["user_id"] is None
        assert listed.await_args_list[1].kwargs["user_id"] == member.user_id


class TestRevoking:
    @pytest.mark.security
    async def test_somebody_else_s_key_reads_as_missing_without_manage(self) -> None:
        ctx = _ctx(OrgRoleName.MEMBER)
        other = _key(_ctx(), organization_id=ctx.organization_id)
        with (
            patch(f"{PATH}.api_key_repo.get", new=AsyncMock(return_value=other)),
            pytest.raises(NotFoundError),
        ):
            await ApiKeyService(MagicMock()).revoke(ctx, other.id)

    async def test_an_unknown_key_reads_as_missing(self) -> None:
        with (
            patch(f"{PATH}.api_key_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await ApiKeyService(MagicMock()).revoke(_ctx(), uuid.uuid4())

    async def test_a_manager_revokes_anybody_s_and_a_second_revoke_records_nothing(
        self,
    ) -> None:
        ctx = _ctx(OrgRoleName.ADMIN)
        revoked = _key(_ctx(), organization_id=ctx.organization_id)

        async def update(_db: object, *, key: ApiKey, update_data: dict[str, Any]) -> ApiKey:
            for name, value in update_data.items():
                setattr(key, name, value)
            return key

        audit = AsyncMock()
        issuer = User(id=revoked.user_id, email="ada@example.com", hashed_password="x")
        with (
            patch(f"{PATH}.api_key_repo.get", new=AsyncMock(return_value=revoked)),
            patch(f"{PATH}.api_key_repo.update", new=update),
            patch(f"{PATH}.user_repo.get_by_id", new=AsyncMock(side_effect=[issuer, None])),
            patch(f"{PATH}.record_audit", new=audit),
        ):
            first = await ApiKeyService(MagicMock()).revoke(ctx, revoked.id)
            second = await ApiKeyService(MagicMock()).revoke(ctx, revoked.id)

        assert first.status == "revoked"
        assert first.issuer_email == "ada@example.com"
        assert second.issuer_email == ""
        audit.assert_awaited_once()


class TestAuthenticating:
    async def test_an_unknown_prefix_is_refused(self) -> None:
        with (
            patch(f"{PATH}.api_key_repo.get_by_prefix", new=AsyncMock(return_value=None)),
            pytest.raises(AuthenticationError),
        ):
            await ApiKeyService(MagicMock()).authenticate("aos_00000000secret")

    @pytest.mark.security
    async def test_a_deactivated_issuer_is_refused(self) -> None:
        import hashlib

        raw = "aos_0123abcdsecret"
        ctx = _ctx()
        key = _key(ctx, key_hash=hashlib.sha256(raw.encode()).hexdigest())
        issuer = User(id=ctx.user_id, email="a@example.com", hashed_password="x", is_active=False)
        with (
            patch(f"{PATH}.api_key_repo.get_by_prefix", new=AsyncMock(return_value=key)),
            patch(f"{PATH}.member_repo.get_active", new=AsyncMock(return_value=MagicMock())),
            patch(f"{PATH}.user_repo.get_by_id", new=AsyncMock(return_value=issuer)),
            patch(f"{PATH}.organization_repo.get_by_id", new=AsyncMock(return_value=MagicMock())),
            pytest.raises(AuthenticationError),
        ):
            await ApiKeyService(MagicMock()).authenticate(raw)

    def test_a_key_is_told_apart_from_a_session_token_by_its_prefix(self) -> None:
        assert is_api_key("aos_0123abcdsecret")
        assert not is_api_key("eyJhbGciOiJIUzI1NiJ9.e30.x")


class TestThePublicSurface:
    def test_a_route_is_public_only_through_its_router_and_can_opt_out(self) -> None:
        async def endpoint() -> None:
            return None

        public = APIRoute("/x", endpoint, dependencies=[PUBLIC])
        internal = APIRoute("/y", endpoint, dependencies=[PUBLIC], openapi_extra=INTERNAL)
        console = APIRoute("/z", endpoint)

        assert is_public_route(public)
        assert not is_public_route(internal)
        assert not is_public_route(console)
        assert not is_public_route(None)

    def test_every_public_route_authorizes_through_the_auth_context(self) -> None:
        """A public route reading `CurrentUser` alone would take a key's issuer at
        their full role, past the key's scopes. So every authenticated public route
        must reach `get_auth_context` or `get_path_org_context`, which are where the
        narrowed context is returned."""
        from app.api.deps import get_auth_context, get_current_user, get_path_org_context
        from app.main import app

        def calls(dependant: Any) -> set[Any]:
            found = {dependant.call}
            for child in dependant.dependencies:
                found |= calls(child)
            return found

        def routes(entries: Any) -> Any:
            for entry in entries:
                if hasattr(entry, "effective_route_contexts"):
                    for context in entry.effective_route_contexts():
                        yield context.original_route
                else:
                    yield entry

        public = [route for route in routes(app.routes) if is_public_route(route)]
        assert public
        for route in public:
            reached = calls(route.dependant)
            if get_current_user in reached:
                assert reached & {get_auth_context, get_path_org_context}, route.path
