"""The group and directory-mapping routes under `/orgs/{org_id}` (#1773).

The services decide who may do what and are tested over a real database in
`tests/integration/test_directory_groups.py`. Here the routes are driven through
the app with the service replaced: each hands the path's organization, the
caller and the body to the service, and serializes what comes back - including
the directory `source` a client branches on.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AuthorizationError
from app.main import app

pytestmark = pytest.mark.anyio

ORG = uuid4()
CALLER = SimpleNamespace(id=uuid4(), is_active=True, is_app_admin=False)
NOW = datetime(2026, 9, 25, tzinfo=UTC)
V1 = settings.API_V1_STR


def _group(name: str = "Finance") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(), organization_id=ORG, name=name, description=None, created_at=NOW
    )


def _member_row(source: str = "directory") -> tuple[SimpleNamespace, str, str | None]:
    return (
        SimpleNamespace(user_id=uuid4(), source=source, created_at=NOW),
        "jane@corp.example",
        "Jane",
    )


@pytest.fixture
def signed_in() -> None:
    app.dependency_overrides[deps.get_current_user] = lambda: CALLER


@pytest.fixture
def groups(signed_in: None) -> MagicMock:
    service = MagicMock()
    app.dependency_overrides[deps.get_group_service] = lambda: service
    return service


@pytest.fixture
def mappings(signed_in: None) -> MagicMock:
    service = MagicMock()
    app.dependency_overrides[deps.get_directory_mapping_service] = lambda: service
    return service


class TestGroupRoutes:
    async def test_listing_reports_each_group_with_its_member_count(
        self, client: AsyncClient, groups: MagicMock
    ) -> None:
        finance = _group()
        groups.list_groups = AsyncMock(return_value=[(finance, 3)])

        resp = await client.get(f"{V1}/orgs/{ORG}/groups")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "Finance"
        assert body["items"][0]["member_count"] == 3
        assert groups.list_groups.await_args.args == (ORG, CALLER.id)

    async def test_creating_answers_201_with_an_empty_group(
        self, client: AsyncClient, groups: MagicMock
    ) -> None:
        groups.create = AsyncMock(return_value=_group("Ops"))

        resp = await client.post(f"{V1}/orgs/{ORG}/groups", json={"name": "Ops"})

        assert resp.status_code == 201
        assert resp.json()["member_count"] == 0
        assert groups.create.await_args.args[2].name == "Ops"

    async def test_an_empty_name_never_reaches_the_service(
        self, client: AsyncClient, groups: MagicMock
    ) -> None:
        groups.create = AsyncMock()

        resp = await client.post(f"{V1}/orgs/{ORG}/groups", json={"name": "   "})

        assert resp.status_code == 422
        groups.create.assert_not_awaited()

    async def test_updating_returns_the_group_with_its_count(
        self, client: AsyncClient, groups: MagicMock
    ) -> None:
        group = _group("Renamed")
        groups.update = AsyncMock(return_value=(group, 5))

        resp = await client.patch(f"{V1}/orgs/{ORG}/groups/{group.id}", json={"name": "Renamed"})

        assert resp.status_code == 200
        assert (resp.json()["name"], resp.json()["member_count"]) == ("Renamed", 5)

    async def test_deleting_answers_204(self, client: AsyncClient, groups: MagicMock) -> None:
        groups.delete = AsyncMock()
        group_id = uuid4()

        resp = await client.delete(f"{V1}/orgs/{ORG}/groups/{group_id}")

        assert resp.status_code == 204
        assert groups.delete.await_args.args == (ORG, group_id, CALLER.id)

    async def test_members_carry_who_put_them_there(
        self, client: AsyncClient, groups: MagicMock
    ) -> None:
        groups.list_members = AsyncMock(
            return_value=[_member_row("directory"), _member_row("manual")]
        )

        resp = await client.get(f"{V1}/orgs/{ORG}/groups/{uuid4()}/members")

        assert [item["source"] for item in resp.json()["items"]] == ["directory", "manual"]
        assert resp.json()["total"] == 2

    async def test_adding_and_removing_a_member(
        self, client: AsyncClient, groups: MagicMock
    ) -> None:
        row = _member_row("manual")
        groups.add_member = AsyncMock(return_value=row)
        groups.remove_member = AsyncMock()
        group_id, user_id = uuid4(), uuid4()

        added = await client.post(
            f"{V1}/orgs/{ORG}/groups/{group_id}/members", json={"user_id": str(user_id)}
        )
        removed = await client.delete(f"{V1}/orgs/{ORG}/groups/{group_id}/members/{user_id}")

        assert added.status_code == 201
        assert added.json()["email"] == "jane@corp.example"
        assert groups.add_member.await_args.args == (ORG, group_id, user_id, CALLER.id)
        assert removed.status_code == 204
        assert groups.remove_member.await_args.args == (ORG, group_id, user_id, CALLER.id)

    @pytest.mark.security
    async def test_a_refusal_from_the_service_is_a_403(
        self, client: AsyncClient, groups: MagicMock
    ) -> None:
        groups.create = AsyncMock(side_effect=AuthorizationError(message="no"))

        resp = await client.post(f"{V1}/orgs/{ORG}/groups", json={"name": "Ops"})

        assert resp.status_code == 403


class TestDirectoryMappingRoutes:
    async def test_listing_names_the_group_each_mapping_places_people_in(
        self, client: AsyncClient, mappings: MagicMock
    ) -> None:
        mapping = SimpleNamespace(
            id=uuid4(),
            organization_id=ORG,
            external_group="cn=finance,dc=corp",
            role="builder",
            group_id=uuid4(),
            created_at=NOW,
        )
        mappings.list_mappings = AsyncMock(return_value=[(mapping, "Finance")])

        resp = await client.get(f"{V1}/orgs/{ORG}/directory-mappings")

        item = resp.json()["items"][0]
        assert (item["external_group"], item["role"], item["group_name"]) == (
            "cn=finance,dc=corp",
            "builder",
            "Finance",
        )

    async def test_creating_folds_the_group_name_and_answers_201(
        self, client: AsyncClient, mappings: MagicMock
    ) -> None:
        async def create(org_id, requester_id, data):
            return (
                SimpleNamespace(
                    id=uuid4(),
                    organization_id=org_id,
                    external_group=data.external_group,
                    role=data.role,
                    group_id=None,
                    created_at=NOW,
                ),
                None,
            )

        mappings.create = AsyncMock(side_effect=create)

        resp = await client.post(
            f"{V1}/orgs/{ORG}/directory-mappings",
            json={"external_group": "CN=Finance,DC=Corp", "role": "member"},
        )

        assert resp.status_code == 201
        assert resp.json()["external_group"] == "cn=finance,dc=corp"

    @pytest.mark.security
    async def test_owner_is_never_a_mapped_role(
        self, client: AsyncClient, mappings: MagicMock
    ) -> None:
        mappings.create = AsyncMock()

        resp = await client.post(
            f"{V1}/orgs/{ORG}/directory-mappings",
            json={"external_group": "cn=everyone", "role": "owner"},
        )

        assert resp.status_code == 422
        mappings.create.assert_not_awaited()

    async def test_deleting_answers_204(self, client: AsyncClient, mappings: MagicMock) -> None:
        mappings.delete = AsyncMock()
        mapping_id = uuid4()

        resp = await client.delete(f"{V1}/orgs/{ORG}/directory-mappings/{mapping_id}")

        assert resp.status_code == 204
        assert mappings.delete.await_args.args == (ORG, mapping_id, CALLER.id)
