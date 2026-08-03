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

from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret, AwsCredentialsSecret
from app.repositories import agent_workspace_repo, sandbox_connection_repo
from app.schemas.sandbox_connection import SandboxConnectionCreate, SandboxConnectionUpdate
from app.services.sandbox_connection import (
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


class _Response:
    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


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
            if queue is not None:
                return queue.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _Client())
    return seen
