"""Where an organization's sandboxes run: registering one, and reaching it.

The refusals are the point, and they fall into two groups.

*Refused while a form is open.* An unknown kind, a container connection with no
address, a duplicate name. Each of these otherwise surfaces on an agent's first
tool call, where the reader is a user in a conversation and the person who can
fix it is the operator who filled this in.

*Refused at the moment of use.* A connection switched off, one whose vault entry
was deleted, one holding the wrong kind of credential. These are states a
deployment arrives at *after* an agent was published, so each says which rather
than failing as one generic error.

And the standing property behind all of it: the credential leaves this module
only as an argument to a client. Never a response, never a log line, never a
`repr`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret, AwsCredentialsSecret
from app.repositories import agent_workspace_repo, organization_secret_repo, sandbox_connection_repo
from app.schemas.sandbox_connection import (
    SandboxConnectionCreate,
    SandboxConnectionUpdate,
    SandboxProbeRequest,
)
from app.services.sandbox_connection import (
    LOCAL_TOKEN_SECRET_NAME,
    ResolvedConnection,
    SandboxConnectionService,
    to_read,
)

pytestmark = pytest.mark.anyio


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


def _row(**overrides: object) -> MagicMock:
    row = MagicMock(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        kind="docker",
        base_url="http://sandboxd:8080",
        secret_id=uuid.uuid4(),
        default_runtime=None,
        is_default=True,
        is_active=True,
        created_at=datetime(2026, 8, 3, tzinfo=UTC),
        updated_at=None,
    )
    row.name = "Local Docker"
    for name, value in overrides.items():
        setattr(row, name, value)
    return row


def _service(monkeypatch, *, secret: Any = None) -> SandboxConnectionService:
    """A service whose vault answers with one unsealed secret.

    The vault itself is proven in `tests/test_secrets.py`; here the question is
    what this service does with what it gets back.
    """
    service = SandboxConnectionService(MagicMock())
    resolved = {} if secret is None else {secret[0]: secret[1]}
    service.secrets = MagicMock()
    service.secrets.resolve_for_bindings = AsyncMock(return_value=resolved)
    monkeypatch.setattr(sandbox_connection_repo, "clear_default", AsyncMock())
    return service


class TestRegistering:
    async def test_the_first_connection_becomes_the_default(self, monkeypatch):
        """Otherwise the form succeeds and every agent then fails to find a host."""
        service = _service(monkeypatch)
        monkeypatch.setattr(sandbox_connection_repo, "get_by_name", AsyncMock(return_value=None))
        monkeypatch.setattr(
            sandbox_connection_repo, "list_for_organization", AsyncMock(return_value=[])
        )
        created = AsyncMock(return_value=_row())
        monkeypatch.setattr(sandbox_connection_repo, "create", created)

        await service.create(
            _ctx(),
            SandboxConnectionCreate(
                name="Local Docker", kind="docker", base_url="http://sandboxd:8080"
            ),
        )

        assert created.await_args.kwargs["is_default"] is True

    async def test_a_later_connection_does_not_steal_the_default(self, monkeypatch):
        service = _service(monkeypatch)
        monkeypatch.setattr(sandbox_connection_repo, "get_by_name", AsyncMock(return_value=None))
        monkeypatch.setattr(
            sandbox_connection_repo, "list_for_organization", AsyncMock(return_value=[_row()])
        )
        created = AsyncMock(return_value=_row(is_default=False))
        monkeypatch.setattr(sandbox_connection_repo, "create", created)

        await service.create(
            _ctx(), SandboxConnectionCreate(name="Big box", kind="docker", base_url="http://b:8080")
        )

        assert created.await_args.kwargs["is_default"] is False

    async def test_promoting_one_demotes_the_rest(self, monkeypatch):
        service = _service(monkeypatch)
        monkeypatch.setattr(sandbox_connection_repo, "get_by_name", AsyncMock(return_value=None))
        monkeypatch.setattr(
            sandbox_connection_repo, "list_for_organization", AsyncMock(return_value=[_row()])
        )
        row = _row(is_default=True)
        monkeypatch.setattr(sandbox_connection_repo, "create", AsyncMock(return_value=row))
        cleared = AsyncMock()
        monkeypatch.setattr(sandbox_connection_repo, "clear_default", cleared)

        await service.create(
            _ctx(),
            SandboxConnectionCreate(
                name="Big box", kind="docker", base_url="http://b:8080", is_default=True
            ),
        )

        assert cleared.await_args.kwargs["except_id"] == row.id

    async def test_a_duplicate_name_is_refused_by_name(self, monkeypatch):
        """Two hosts called "Docker" is a Builder dropdown nobody can read."""
        service = _service(monkeypatch)
        monkeypatch.setattr(sandbox_connection_repo, "get_by_name", AsyncMock(return_value=_row()))

        with pytest.raises(AlreadyExistsError):
            await service.create(
                _ctx(),
                SandboxConnectionCreate(
                    name="Local Docker", kind="docker", base_url="http://s:8080"
                ),
            )

    async def test_a_container_connection_without_an_address_is_refused(self, monkeypatch):
        """It would resolve, and every session opened on it would fail to connect."""
        service = _service(monkeypatch)
        monkeypatch.setattr(sandbox_connection_repo, "get_by_name", AsyncMock(return_value=None))

        with pytest.raises(BadRequestError) as refused:
            await service.create(_ctx(), SandboxConnectionCreate(name="Big box", kind="docker"))

        assert refused.value.details["field"] == "base_url"

    async def test_daytona_needs_no_address_of_its_own(self, monkeypatch):
        """Their API has one, and asking an operator to type it invites a typo in
        the one field nothing validates."""
        service = _service(monkeypatch)
        monkeypatch.setattr(sandbox_connection_repo, "get_by_name", AsyncMock(return_value=None))
        monkeypatch.setattr(
            sandbox_connection_repo, "list_for_organization", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(
            sandbox_connection_repo,
            "create",
            AsyncMock(return_value=_row(kind="daytona", base_url=None)),
        )

        read = await service.create(_ctx(), SandboxConnectionCreate(name="Daytona", kind="daytona"))

        assert read.kind == "daytona"


class TestEditing:
    async def test_a_connection_from_another_organization_reads_as_missing(self, monkeypatch):
        """Not "forbidden": a probeable id is how a tenant boundary gets mapped."""
        service = _service(monkeypatch)
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=None))

        with pytest.raises(NotFoundError):
            await service.get(_ctx(), uuid.uuid4())

    async def test_renaming_onto_an_existing_name_is_refused(self, monkeypatch):
        service = _service(monkeypatch)
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=_row()))
        monkeypatch.setattr(sandbox_connection_repo, "get_by_name", AsyncMock(return_value=_row()))

        with pytest.raises(AlreadyExistsError):
            await service.update(_ctx(), uuid.uuid4(), SandboxConnectionUpdate(name="Big box"))

    async def test_keeping_the_same_name_is_not_a_duplicate_of_itself(self, monkeypatch):
        service = _service(monkeypatch)
        row = _row()
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        monkeypatch.setattr(
            sandbox_connection_repo, "update_connection", AsyncMock(return_value=row)
        )

        read = await service.update(
            _ctx(), row.id, SandboxConnectionUpdate(name="Local Docker", default_runtime="python")
        )

        assert read.name == "Local Docker"

    async def test_switching_a_container_connection_to_no_address_is_refused(self, monkeypatch):
        """The shape check runs against the row as it *will* be, not as it was."""
        service = _service(monkeypatch)
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=_row()))

        with pytest.raises(BadRequestError):
            await service.update(_ctx(), uuid.uuid4(), SandboxConnectionUpdate(base_url=None))

    async def test_a_row_holding_a_kind_this_build_does_not_know_is_refused(self, monkeypatch):
        """The schema keeps an unknown kind out of the API, so this is only
        reachable from the database - a row written by a build that had a third
        kind, edited by one that does not. Refusing beats saving an edit against
        a kind nothing can open a sandbox on."""
        service = _service(monkeypatch)
        monkeypatch.setattr(
            sandbox_connection_repo, "get", AsyncMock(return_value=_row(kind="kubernetes"))
        )

        with pytest.raises(BadRequestError) as refused:
            await service.update(
                _ctx(), uuid.uuid4(), SandboxConnectionUpdate(default_runtime="python")
            )

        assert refused.value.details["kind"] == "kubernetes"

    async def test_promoting_through_an_edit_demotes_the_rest(self, monkeypatch):
        service = _service(monkeypatch)
        row = _row(is_default=True)
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        monkeypatch.setattr(
            sandbox_connection_repo, "update_connection", AsyncMock(return_value=row)
        )
        cleared = AsyncMock()
        monkeypatch.setattr(sandbox_connection_repo, "clear_default", cleared)

        await service.update(_ctx(), row.id, SandboxConnectionUpdate(is_default=True))

        cleared.assert_awaited_once()

    async def test_deleting_leaves_the_workspaces_alone(self, monkeypatch):
        """Their rows record what an agent did and where; forgetting a host is
        not a statement about that history."""
        service = _service(monkeypatch)
        row = _row()
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        deleted = AsyncMock()
        monkeypatch.setattr(sandbox_connection_repo, "delete", deleted)

        await service.delete(_ctx(), row.id)

        deleted.assert_awaited_once()

    async def test_a_listing_never_carries_a_credential(self, monkeypatch):
        """`secret_id` is a reference the vault resolves under its own check; a
        value here would be a token in a browser."""
        service = _service(monkeypatch)
        monkeypatch.setattr(
            sandbox_connection_repo, "list_for_organization", AsyncMock(return_value=[_row()])
        )

        [read] = await service.list_connections(_ctx())

        assert "token" not in read.model_dump()
        assert "api_key" not in read.model_dump()


class TestResolvingForARun:
    async def test_the_default_is_taken_when_the_spec_names_none(self, monkeypatch):
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get_default", AsyncMock(return_value=row))

        resolved = await service.resolve(_ctx(), None)

        assert resolved.token == "tok"
        assert resolved.kind == "docker"

    async def test_an_organization_with_no_connection_is_told_what_to_do(self, monkeypatch):
        service = _service(monkeypatch)
        monkeypatch.setattr(sandbox_connection_repo, "get_default", AsyncMock(return_value=None))

        with pytest.raises(BadRequestError) as refused:
            await service.resolve(_ctx(), None)

        assert "'state' workspace" in refused.value.message

    async def test_a_connection_deleted_since_publish_says_so(self, monkeypatch):
        """A spec valid when it was published; the fix is in the Builder."""
        service = _service(monkeypatch)
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=None))

        with pytest.raises(BadRequestError) as refused:
            await service.resolve(_ctx(), uuid.uuid4())

        assert "no longer exists" in refused.value.message

    async def test_a_connection_switched_off_is_refused_rather_than_used(self, monkeypatch):
        """Off means an operator has said not to run agents there."""
        row = _row(is_active=False)
        service = _service(monkeypatch)
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))

        with pytest.raises(BadRequestError) as refused:
            await service.resolve(_ctx(), row.id)

        assert "switched off" in refused.value.message

    async def test_a_credential_deleted_from_the_vault_is_named_as_the_cause(self, monkeypatch):
        """`SET NULL` on the vault reference makes this reachable, and the
        connection is still there to be fixed."""
        row = _row(secret_id=None)
        service = _service(monkeypatch)
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))

        with pytest.raises(BadRequestError) as refused:
            await service.resolve(_ctx(), row.id)

        assert "no credential" in refused.value.message

    async def test_a_credential_that_no_longer_resolves_is_refused(self, monkeypatch):
        """The row points at a vault entry that is gone: absent from the result
        rather than raising, so this has to be checked rather than assumed."""
        row = _row()
        service = _service(monkeypatch)
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))

        with pytest.raises(BadRequestError) as refused:
            await service.resolve(_ctx(), row.id)

        assert "not an API key" in refused.value.message

    async def test_the_wrong_kind_of_credential_is_refused_rather_than_sent(self, monkeypatch):
        """A sandbox service authenticates with a token. Handing it AWS keys
        would be a credential sent to the wrong host."""
        row = _row()
        service = _service(
            monkeypatch,
            secret=(
                row.secret_id,
                AwsCredentialsSecret(
                    aws_access_key_id="AKIA0000",
                    aws_secret_access_key="x",
                    region_name="eu-west-1",
                ),
            ),
        )
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))

        with pytest.raises(BadRequestError) as refused:
            await service.resolve(_ctx(), row.id)

        assert "not an API key" in refused.value.message

    def test_a_resolved_connection_keeps_its_token_out_of_its_repr(self):
        """A default `repr` would put the token in every log line touching one."""
        resolved = ResolvedConnection(row=_row(), token="super-secret")

        assert "super-secret" not in repr(resolved)


class TestReadingThePolicy:
    async def test_what_the_service_allows_comes_from_the_service(self, monkeypatch):
        """The runtime allowlist is its boot configuration, so a copy here would
        disagree the first time somebody restarted it with a different limit."""
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        _serve(monkeypatch, _Response(200, {"runtimes": [{"alias": "python"}]}))

        policy = await service.policy(_ctx(), row.id)

        assert policy["runtimes"] == [{"alias": "python"}]
        assert policy["kind"] == "docker"

    async def test_the_token_is_sent_as_a_header_and_not_in_the_url(self, monkeypatch):
        """A token in a query string reaches every access log on the way."""
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        seen = _serve(monkeypatch, _Response(200, {"runtimes": []}))

        await service.policy(_ctx(), row.id)

        assert seen["headers"] == {"X-Sandbox-Token": "tok"}
        assert "tok" not in seen["url"]

    async def test_daytona_publishes_no_policy_of_its_own(self, monkeypatch):
        """What it allows is an account setting on their side, so there is
        nothing to proxy and nothing to invent."""
        row = _row(kind="daytona", base_url=None)
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))

        policy = await service.policy(_ctx(), row.id)

        assert policy == {"runtimes": [], "kind": "daytona"}

    async def test_a_service_that_does_not_answer_is_distinguished_from_an_empty_one(
        self, monkeypatch
    ):
        """ "No runtimes" and "unreachable" are different problems, and only one
        of them is fixed in this form."""
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        _serve(monkeypatch, OSError("connection refused"))

        with pytest.raises(BadRequestError) as refused:
            await service.policy(_ctx(), row.id)

        assert "did not answer" in refused.value.message

    async def test_a_refused_token_is_reported_as_the_credential(self, monkeypatch):
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        _serve(monkeypatch, _Response(401))

        with pytest.raises(BadRequestError) as refused:
            await service.policy(_ctx(), row.id)

        assert "refused this connection's credential" in refused.value.message

    async def test_any_other_status_is_reported_with_its_number(self, monkeypatch):
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        _serve(monkeypatch, _Response(503))

        with pytest.raises(BadRequestError) as refused:
            await service.policy(_ctx(), row.id)

        assert "503" in refused.value.message

    async def test_a_200_that_is_not_json_names_the_port_rather_than_raising(self, monkeypatch):
        """A web server on the wrong port is the commonest way to reach this.

        `response.json()` used to sit outside the guard, so it answered with a
        500 - the one outcome the rest of these messages exist to avoid.
        """
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        _serve(monkeypatch, _NotJson())

        with pytest.raises(BadRequestError) as refused:
            await service.policy(_ctx(), row.id)

        assert "not with JSON" in refused.value.message
        assert "port" in refused.value.message


class TestWhatThisDeploymentCanAlreadySee:
    """The prefill, and the reason it is a probe rather than a setting.

    An operator registering the service their own `make dev` started should not
    have to know that it answers at `http://sandboxd:8080` and that its token is
    already in `backend/.env`. None of that is configuration here - the address is
    a row, because a deployment can hold several hosts - so the only honest way to
    offer it is to ask, and to say plainly when nothing answered.
    """

    async def test_the_compose_address_is_tried_before_a_developers_own(self, monkeypatch):
        """Inside the stack the first answers and the second does not exist."""
        service = _service(monkeypatch)
        monkeypatch.setattr(
            sandbox_connection_repo, "list_for_organization", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(settings, "SANDBOXD_TOKEN", "")
        seen = _serve(monkeypatch, _Response(200, {}))

        local = await service.local_service(_ctx())

        assert local["url"] == "http://sandboxd:8080"
        assert seen["urls"] == ["http://sandboxd:8080/healthz"]

    async def test_a_developer_running_the_api_on_their_host_is_found_too(self, monkeypatch):
        service = _service(monkeypatch)
        monkeypatch.setattr(
            sandbox_connection_repo, "list_for_organization", AsyncMock(return_value=[])
        )
        _serve(monkeypatch, [_Response(503), _Response(200, {})])

        local = await service.local_service(_ctx())

        assert local["url"] == "http://localhost:8080"

    async def test_no_service_is_no_url_rather_than_a_guess(self, monkeypatch):
        """A form that prefilled an address nothing answers on would send an
        operator looking for a network problem that does not exist."""
        service = _service(monkeypatch)
        # Pinned rather than inherited: a developer's own `.env` carries a token,
        # and a test that passed because of one would say nothing about a
        # deployment that has none.
        monkeypatch.setattr(settings, "SANDBOXD_TOKEN", "")
        _serve(monkeypatch, OSError("connection refused"))

        assert await service.local_service(_ctx()) == {
            "url": None,
            "token_available": False,
            "registered_connection_id": None,
        }

    async def test_the_token_this_deployment_holds_is_reported_as_available(self, monkeypatch):
        """Reported, never returned. What reaches the browser is a boolean; the
        value goes to the vault and nowhere else."""
        service = _service(monkeypatch)
        monkeypatch.setattr(
            sandbox_connection_repo, "list_for_organization", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(settings, "SANDBOXD_TOKEN", "sbx-local")
        _serve(monkeypatch, _Response(200, {}))

        local = await service.local_service(_ctx())

        assert local["token_available"] is True
        assert "sbx-local" not in repr(local)

    async def test_a_connection_already_pointing_there_is_named(self, monkeypatch):
        """So the dialog can say "you already registered this" instead of letting
        somebody create a second row for one host and then wonder which is used."""
        service = _service(monkeypatch)
        row = _row(base_url="http://sandboxd:8080/")
        monkeypatch.setattr(
            sandbox_connection_repo, "list_for_organization", AsyncMock(return_value=[row])
        )
        _serve(monkeypatch, _Response(200, {}))

        local = await service.local_service(_ctx())

        assert local["registered_connection_id"] == row.id

    async def test_a_connection_to_somewhere_else_is_not_it(self, monkeypatch):
        service = _service(monkeypatch)
        monkeypatch.setattr(
            sandbox_connection_repo,
            "list_for_organization",
            AsyncMock(return_value=[_row(base_url="http://other:8080")]),
        )
        _serve(monkeypatch, _Response(200, {}))

        assert (await service.local_service(_ctx()))["registered_connection_id"] is None


class TestTheRuntimeCatalog:
    """Read from the library rather than listed here.

    A copy would drift the first time `pydantic-ai-backends` added a runtime, and
    the failure is invisible: a form offering twelve of fifteen looks complete.
    """

    def test_every_runtime_the_library_ships_is_offered(self):
        from pydantic_ai_backends import BUILTIN_RUNTIMES

        catalog = SandboxConnectionService.runtime_catalog()

        assert {entry["alias"] for entry in catalog} == set(BUILTIN_RUNTIMES)

    def test_a_ready_made_image_is_named_and_marked_as_not_building(self):
        catalog = {entry["alias"]: entry for entry in SandboxConnectionService.runtime_catalog()}

        node = catalog["node-minimal"]

        assert node["image"] == "node:20-slim"
        assert node["builds"] is False

    def test_a_built_runtime_says_what_it_starts_from_and_that_it_builds(self):
        """The first session pays for the build, so "coding" and "node-minimal" are
        not the same promise about how long the first message takes."""
        catalog = {entry["alias"]: entry for entry in SandboxConnectionService.runtime_catalog()}

        coding = catalog["coding"]

        assert coding["image"] == "python:3.12-slim"
        assert coding["builds"] is True
        assert "git" in coding["description"]


class TestStoringTheLocalToken:
    async def test_the_token_this_deployment_started_the_service_with_is_stored(self, monkeypatch):
        """The friction this removes: `make sandbox-token` wrote it to
        `backend/.env`, compose handed it to the service, and then a form asked an
        operator to go and find the value their own stack is already using."""
        service = _service(monkeypatch)
        monkeypatch.setattr(settings, "SANDBOXD_TOKEN", "sbx-local-token")
        monkeypatch.setattr(organization_secret_repo, "get_by_name", AsyncMock(return_value=None))
        stored = MagicMock(id=uuid.uuid4(), hint="oken")
        stored.name = LOCAL_TOKEN_SECRET_NAME
        service.secrets.create = AsyncMock(return_value=stored)

        result = await service.store_local_credential(_ctx())

        assert result == {"secret_id": stored.id, "name": LOCAL_TOKEN_SECRET_NAME, "hint": "oken"}
        assert (
            service.secrets.create.await_args.kwargs["value"].api_key.get_secret_value()
            == "sbx-local-token"
        )

    async def test_it_is_stored_as_the_service_credential_it_is(self, monkeypatch):
        """Purpose `sandboxd`, so the connection form's own picker offers it and a
        Daytona key is not offered for a container service."""
        service = _service(monkeypatch)
        monkeypatch.setattr(settings, "SANDBOXD_TOKEN", "sbx")
        monkeypatch.setattr(organization_secret_repo, "get_by_name", AsyncMock(return_value=None))
        service.secrets.create = AsyncMock(return_value=MagicMock(id=uuid.uuid4(), hint="sbx"))

        await service.store_local_credential(_ctx())

        assert service.secrets.create.await_args.kwargs["purpose"] == "sandboxd"

    async def test_a_second_call_rotates_the_entry_rather_than_adding_another(self, monkeypatch):
        """`.env` can have been regenerated since. A reused entry holding the older
        token resolves and then 401s on every session - the same failure this
        exists to prevent, reached from the other side."""
        service = _service(monkeypatch)
        monkeypatch.setattr(settings, "SANDBOXD_TOKEN", "sbx-new")
        existing = MagicMock(id=uuid.uuid4())
        monkeypatch.setattr(
            organization_secret_repo, "get_by_name", AsyncMock(return_value=existing)
        )
        rotated = MagicMock(id=existing.id, hint="-new")
        rotated.name = LOCAL_TOKEN_SECRET_NAME
        service.secrets.update = AsyncMock(return_value=rotated)
        service.secrets.create = AsyncMock()

        result = await service.store_local_credential(_ctx())

        assert result["secret_id"] == existing.id
        service.secrets.create.assert_not_called()
        assert service.secrets.update.await_args.args[1] == existing.id

    async def test_a_deployment_with_no_token_says_so_rather_than_storing_nothing(
        self, monkeypatch
    ):
        """An empty vault entry would be a credential that exists and cannot
        authenticate anything, which is worse than being asked to paste one."""
        service = _service(monkeypatch)
        monkeypatch.setattr(settings, "SANDBOXD_TOKEN", "")

        with pytest.raises(BadRequestError) as refused:
            await service.store_local_credential(_ctx())

        assert "make sandbox-token" in refused.value.message


class TestTestingAnAddressBeforeItIsSaved:
    """What makes `Default runtime` a list rather than a free-text field.

    A typo in free text is stored happily and refused at the first tool call, in
    somebody's conversation. Asking the service which aliases it accepts moves that
    refusal into the form, where the person who can fix it is looking.
    """

    async def test_the_runtimes_come_from_the_service_at_that_address(self, monkeypatch):
        secret_id = uuid.uuid4()
        service = _service(monkeypatch, secret=(secret_id, ApiKeySecret(api_key="tok")))
        seen = _serve(monkeypatch, _Response(200, {"runtimes": [{"alias": "python"}]}))

        policy = await service.probe_policy(
            _ctx(), SandboxProbeRequest(base_url="http://sandboxd:8080/", secret_id=secret_id)
        )

        assert policy["runtimes"] == [{"alias": "python"}]
        assert policy["kind"] == "docker"
        assert seen["url"] == "http://sandboxd:8080/policy"

    async def test_the_token_is_a_header_here_too(self, monkeypatch):
        secret_id = uuid.uuid4()
        service = _service(monkeypatch, secret=(secret_id, ApiKeySecret(api_key="tok")))
        seen = _serve(monkeypatch, _Response(200, {"runtimes": []}))

        await service.probe_policy(
            _ctx(), SandboxProbeRequest(base_url="http://sandboxd:8080", secret_id=secret_id)
        )

        assert seen["headers"] == {"X-Sandbox-Token": "tok"}
        assert "tok" not in seen["url"]

    async def test_a_probe_with_no_credential_says_which_field_is_missing(self, monkeypatch):
        service = _service(monkeypatch)

        with pytest.raises(BadRequestError) as refused:
            await service.probe_policy(_ctx(), SandboxProbeRequest(base_url="http://s:8080"))

        assert refused.value.details["field"] == "secret_id"

    async def test_a_credential_of_the_wrong_shape_cannot_authenticate_a_service(self, monkeypatch):
        secret_id = uuid.uuid4()
        service = _service(
            monkeypatch,
            secret=(
                secret_id,
                AwsCredentialsSecret(
                    aws_access_key_id="AKIA0000",
                    aws_secret_access_key="x",
                    region_name="eu-west-1",
                ),
            ),
        )

        with pytest.raises(BadRequestError) as refused:
            await service.probe_policy(
                _ctx(), SandboxProbeRequest(base_url="http://s:8080", secret_id=secret_id)
            )

        assert "not an API key" in refused.value.message

    async def test_an_address_that_does_not_answer_is_reported_as_the_address(self, monkeypatch):
        secret_id = uuid.uuid4()
        service = _service(monkeypatch, secret=(secret_id, ApiKeySecret(api_key="tok")))
        _serve(monkeypatch, OSError("no route to host"))

        with pytest.raises(BadRequestError) as refused:
            await service.probe_policy(
                _ctx(), SandboxProbeRequest(base_url="http://typo:8080", secret_id=secret_id)
            )

        assert "http://typo:8080 did not answer" in refused.value.message
        assert refused.value.details == {"base_url": "http://typo:8080"}


class TestReadingTheSessions:
    """The filter, which is the whole reason this is not a straight proxy.

    One `sandboxd` serves every organization that registered a connection at its
    address, and `GET /sessions` answers with all of them.
    """

    async def test_another_tenants_sandboxes_are_dropped_before_the_response(self, monkeypatch):
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        monkeypatch.setattr(
            agent_workspace_repo, "list_for_organization", AsyncMock(return_value=[])
        )
        ctx = _ctx()
        _serve(
            monkeypatch,
            _Response(
                200,
                {
                    "sessions": [
                        {"session_id": "mine", "tenant": str(ctx.organization_id)},
                        {"session_id": "theirs", "tenant": str(uuid.uuid4())},
                    ],
                    "limit": 20,
                },
            ),
        )

        listing = await service.sessions(ctx, row.id)

        assert [entry["session_id"] for entry in listing["sessions"]] == ["mine"]
        assert listing["limit"] == 20

    async def test_a_session_with_no_tenant_label_is_not_assumed_to_be_ours(self, monkeypatch):
        """Something else opened it against the same service. Showing it would be
        showing a container this organization has no claim to."""
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        monkeypatch.setattr(
            agent_workspace_repo, "list_for_organization", AsyncMock(return_value=[])
        )
        _serve(monkeypatch, _Response(200, {"sessions": [{"session_id": "stray"}]}))

        assert await service.sessions(_ctx(), row.id) == {"sessions": [], "kind": "docker"}

    async def test_a_session_is_named_by_the_row_rather_than_by_decoding_its_id(self, monkeypatch):
        """Parsing the scope key back out would make its format a schema, and the
        first change to it would mislabel every row."""
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        ctx = _ctx()
        agent_id, conversation_id = uuid.uuid4(), uuid.uuid4()
        workspace = MagicMock(
            session_id="xc-1",
            agent_id=agent_id,
            conversation_id=conversation_id,
            scope="conversation",
        )
        monkeypatch.setattr(
            agent_workspace_repo, "list_for_organization", AsyncMock(return_value=[workspace])
        )
        _serve(
            monkeypatch,
            _Response(
                200, {"sessions": [{"session_id": "xc-1", "tenant": str(ctx.organization_id)}]}
            ),
        )

        [entry] = (await service.sessions(ctx, row.id))["sessions"]

        assert entry["agent_id"] == str(agent_id)
        assert entry["conversation_id"] == str(conversation_id)
        assert entry["scope"] == "conversation"

    async def test_a_run_scoped_sandbox_keeps_its_id_and_nothing_else(self, monkeypatch):
        """It has no row by design, so an unmatched session is normal."""
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        monkeypatch.setattr(
            agent_workspace_repo, "list_for_organization", AsyncMock(return_value=[])
        )
        ctx = _ctx()
        _serve(
            monkeypatch,
            _Response(
                200, {"sessions": [{"session_id": "xr-1", "tenant": str(ctx.organization_id)}]}
            ),
        )

        [entry] = (await service.sessions(ctx, row.id))["sessions"]

        assert "agent_id" not in entry

    async def test_sampling_usage_is_asked_for_explicitly(self, monkeypatch):
        """The service pays a daemon round trip per sandbox for it, so a listing
        page must not do it on load."""
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        monkeypatch.setattr(
            agent_workspace_repo, "list_for_organization", AsyncMock(return_value=[])
        )
        seen = _serve(monkeypatch, _Response(200, {"sessions": []}))

        await service.sessions(_ctx(), row.id, usage=True)

        assert seen["url"].endswith("/sessions?usage=true")

    async def test_daytona_holds_no_sessions_of_ours_to_enumerate(self, monkeypatch):
        row = _row(kind="daytona", base_url=None)
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))

        assert await service.sessions(_ctx(), row.id) == {"sessions": [], "kind": "daytona"}

    async def test_a_service_that_did_not_answer_is_reported(self, monkeypatch):
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        _serve(monkeypatch, OSError("connection refused"))

        with pytest.raises(BadRequestError) as refused:
            await service.sessions(_ctx(), row.id)

        assert "did not answer" in refused.value.message


class TestSamplingOneSandbox:
    """What a usage report can afford: one session, not the listing.

    The service samples each sandbox individually, so asking for all of them to
    find the one a turn used would cost a round trip per sandbox the organization
    has open - on every turn.
    """

    async def test_the_memory_of_one_session_comes_back(self, monkeypatch):
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        ctx = _ctx()
        seen = _serve(
            monkeypatch,
            _Response(
                200,
                {
                    "session_id": "xc-1",
                    "tenant": str(ctx.organization_id),
                    "usage": {"memory_bytes": 512, "memory_limit_bytes": 2048},
                },
            ),
        )

        usage = await service.session_usage(ctx, row.id, "xc-1")

        assert usage == {"memory_bytes": 512, "memory_limit_bytes": 2048}
        assert seen["url"].endswith("/sessions/xc-1?usage=true")

    async def test_another_organizations_sandbox_reads_as_missing(self, monkeypatch):
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        _serve(monkeypatch, _Response(200, {"session_id": "theirs", "tenant": str(uuid.uuid4())}))

        with pytest.raises(NotFoundError):
            await service.session_usage(_ctx(), row.id, "theirs")

    async def test_a_session_that_reported_nothing_is_an_empty_answer(self, monkeypatch):
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        ctx = _ctx()
        _serve(
            monkeypatch, _Response(200, {"session_id": "xc-1", "tenant": str(ctx.organization_id)})
        )

        assert await service.session_usage(ctx, row.id, "xc-1") == {}

    async def test_daytona_reports_no_memory_of_ours(self, monkeypatch):
        row = _row(kind="daytona", base_url=None)
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))

        assert await service.session_usage(_ctx(), row.id, "any") == {}


class TestReadingOneSessionsActivity:
    async def test_another_organizations_session_reads_as_missing(self, monkeypatch):
        """The log names every path read and command run. That is a description of
        somebody's work even with no contents in it."""
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        _serve(monkeypatch, _Response(200, {"session_id": "theirs", "tenant": str(uuid.uuid4())}))

        with pytest.raises(NotFoundError):
            await service.session_events(_ctx(), row.id, "theirs")

    async def test_our_own_session_comes_back_with_its_log(self, monkeypatch):
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        ctx = _ctx()
        seen = _serve(
            monkeypatch,
            [
                _Response(200, {"session_id": "xc-1", "tenant": str(ctx.organization_id)}),
                _Response(200, {"events": [{"seq": 1, "op": "exec"}], "latest_seq": 1}),
            ],
        )

        log = await service.session_events(ctx, row.id, "xc-1", after=0)

        assert log["latest_seq"] == 1
        assert seen["url"].endswith("/sessions/xc-1/events?after=0")

    async def test_polling_asks_only_for_what_it_does_not_have(self, monkeypatch):
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        ctx = _ctx()
        seen = _serve(
            monkeypatch,
            [
                _Response(200, {"session_id": "xc-1", "tenant": str(ctx.organization_id)}),
                _Response(200, {"events": [], "latest_seq": 7}),
            ],
        )

        await service.session_events(ctx, row.id, "xc-1", after=7)

        assert seen["url"].endswith("after=7")

    async def test_a_session_the_service_forgot_is_a_404_rather_than_a_500(self, monkeypatch):
        """Reaped between the listing and the click, which is ordinary."""
        row = _row()
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))
        _serve(monkeypatch, _Response(404))

        with pytest.raises(NotFoundError):
            await service.session_events(_ctx(), row.id, "gone")

    async def test_daytona_has_no_activity_log_of_ours(self, monkeypatch):
        row = _row(kind="daytona", base_url=None)
        service = _service(monkeypatch, secret=(row.secret_id, ApiKeySecret(api_key="tok")))
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=row))

        assert await service.session_events(_ctx(), row.id, "any") == {
            "events": [],
            "latest_seq": 0,
        }


def test_the_read_model_carries_the_reference_and_not_the_secret():
    row = _row()

    read = to_read(row)

    assert read.secret_id == row.secret_id
    assert read.base_url == "http://sandboxd:8080"


class TestAnAddressThePlatformWillFetch:
    """What `base_url` refuses, and what it deliberately still allows.

    This field is the input to a server-side GET that carries the connection's
    token and hands the body back, so an unvalidated string made the API container
    a fetch proxy for its own network. One validator covers all three schemas
    that carry an address - a connection created, one edited, and the probe, which
    is the only one taking an address straight from a request body.
    """

    @pytest.mark.parametrize(
        "address",
        [
            "http://sandboxd:8080",
            "http://localhost:8080",
            "https://sandbox.internal.example.com",
            # RFC1918 stays allowed on purpose: a sandbox service's legitimate
            # address is private, so refusing this range would refuse the
            # deployment this project documents.
            "http://10.1.2.3:8080",
        ],
    )
    def test_a_real_service_address_is_accepted(self, address):
        assert SandboxProbeRequest(base_url=address).base_url == address

    @pytest.mark.parametrize(
        ("address", "because"),
        [
            ("file:///etc/passwd", "http"),
            ("gopher://x/1", "http"),
            ("http://", "host"),
            ("not-a-url", "http"),
            # The one target where a single unauthenticated GET is worth
            # something, blocked by address and by every name that means it.
            ("http://169.254.169.254/latest/meta-data/", "link-local"),
            ("http://metadata.google.internal/computeMetadata/v1/", "metadata"),
            ("http://[fe80::1]:8080", "link-local"),
        ],
    )
    def test_an_address_the_platform_must_not_fetch_is_refused(self, address, because):
        with pytest.raises(ValidationError) as refused:
            SandboxProbeRequest(base_url=address)

        assert because in str(refused.value)

    def test_the_same_rule_applies_to_a_stored_connection(self):
        """Not only to the probe. The probe is the loud one, but `create` and
        `update` store an address that `resolve` then fetches on every run."""
        with pytest.raises(ValidationError):
            SandboxConnectionCreate(
                name="Metadata", kind="docker", base_url="http://169.254.169.254"
            )
        with pytest.raises(ValidationError):
            SandboxConnectionUpdate(base_url="http://169.254.169.254")

    def test_an_unset_address_is_still_allowed(self):
        """A Daytona connection has no address at all, and `update` means
        unchanged rather than empty."""
        assert SandboxConnectionCreate(name="Cloud", kind="daytona").base_url is None
        assert SandboxConnectionUpdate().base_url is None


class _Response:
    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _NotJson(_Response):
    """A 200 whose body is not JSON, which is what a web server answers.

    `httpx` raises `json.JSONDecodeError` here, and that is a `ValueError` - so
    the guard catches the class rather than importing the library's own.
    """

    def __init__(self) -> None:
        super().__init__(200)

    def json(self) -> Any:
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


def _serve(monkeypatch, answer: _Response | Exception | list[_Response]) -> dict[str, Any]:
    """Stand in for the sandbox service, and record how it was called.

    A list answers successive requests in order, which is what the activity log
    needs: it checks the session's tenant before it fetches the log.
    """
    import httpx

    seen: dict[str, Any] = {}
    queue = list(answer) if isinstance(answer, list) else None

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, url: str, headers: dict[str, str] | None = None):
            seen.update(url=url, headers=headers)
            # Every address, not only the last: a probe that tries two in order is
            # only proven correct by which one it tried first.
            seen.setdefault("urls", []).append(url)
            if queue is not None:
                return queue.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _Client())
    return seen
