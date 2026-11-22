"""The starter opens and retries their own run without `runs:view`, and nobody else's.

A member holds no `runs:view`, and the link in an expired-approval notice opens
`/runs?run=<id>`. These pin the narrow way in - the stored starter, a signed-in
session, an active membership - and that it never turns into reading any other run.
"""

import uuid
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.audit import set_impersonator
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.main import app
from app.services.agent_runner import AgentRunnerService
from app.services.approval_authority import may_open_own_run

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_ORG = uuid.uuid4()
_MEMBER = uuid.uuid4()
_COLLEAGUE = uuid.uuid4()
_MODULE = "app.services.agent_runner"


def _ctx(role: str, user_id: uuid.UUID | None = _MEMBER, **overrides) -> AuthContext:
    return AuthContext(user_id=user_id, organization_id=_ORG, role=role, **overrides)


def _run(
    user_id: uuid.UUID | None = _MEMBER,
    surface: str = RunSurface.WEB.value,
    *,
    publisher_fallback: bool = False,
) -> AgentRun:
    return AgentRun(
        id=uuid.uuid4(),
        organization_id=_ORG,
        user_id=user_id,
        surface=surface,
        initiated_by_publisher_fallback=publisher_fallback,
    )


def _finished(user_id: uuid.UUID = _MEMBER) -> AgentRun:
    run = _run(user_id)
    run.status = RunStatus.CANCELLED.value
    run.conversation_id = uuid.uuid4()
    run.agent_id = uuid.uuid4()
    run.cost_usd = 0
    run.cost_is_partial = False
    run.is_test = False
    run.tool_args_repaired = 0
    run.modality = "text"
    run.fallback_used = False
    run.input_tokens = run.output_tokens = 0
    run.cache_read_tokens = run.cache_write_tokens = 0
    return run


class TestMayOpenOwnRun:
    @pytest.mark.parametrize("role", ["member", "builder", "operator", "owner"])
    def test_the_starter_opens_their_own_run(self, role):
        assert may_open_own_run(_ctx(role), _run()) is True

    def test_a_starter_demoted_to_viewer_does_not(self):
        """They need the run to decide its approvals, and a viewer cannot decide them."""
        assert may_open_own_run(_ctx("viewer"), _run()) is False

    def test_a_member_does_not_open_a_colleagues_run(self):
        assert may_open_own_run(_ctx("member"), _run(_COLLEAGUE)) is False

    def test_a_member_never_holds_runs_view_through_it(self):
        assert _ctx("member").has(Perm.RUNS_VIEW) is False

    def test_somebody_with_no_membership_does_not(self):
        assert may_open_own_run(_ctx(""), _run()) is False

    def test_an_api_key_does_not(self):
        ctx = _ctx("member", api_key_id=uuid.uuid4(), key_scopes=frozenset({Perm.RUNS_VIEW}))
        assert may_open_own_run(ctx, _run()) is False

    def test_a_publisher_fallback_identity_does_not(self):
        assert may_open_own_run(_ctx("member", subject_is_publisher_fallback=True), _run()) is False
        assert may_open_own_run(_ctx("builder"), _run(publisher_fallback=True)) is False

    def test_a_routine_does_not(self):
        assert may_open_own_run(_ctx("member", routine_id=uuid.uuid4()), _run()) is False

    def test_a_fired_trigger_does_not(self):
        assert may_open_own_run(_ctx("member", fired_as_creator="event"), _run()) is False

    def test_an_impersonated_session_does_not(self):
        set_impersonator(uuid.uuid4())
        try:
            assert may_open_own_run(_ctx("member"), _run()) is False
        finally:
            set_impersonator(None)

    @pytest.mark.parametrize("surface", [RunSurface.API.value, RunSurface.SCHEDULE.value])
    def test_a_run_on_an_unattended_surface_does_not(self, surface):
        assert may_open_own_run(_ctx("member"), _run(surface=surface)) is False

    def test_a_subject_less_context_does_not(self):
        assert may_open_own_run(_ctx("member", None), _run(None)) is False


@contextmanager
def _stored(run: AgentRun | None):
    with patch(f"{_MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=run)):
        yield AgentRunnerService(MagicMock())


class TestReadRun:
    async def test_a_member_reads_their_own_run(self):
        run = _run()
        with _stored(run) as service:
            assert await service.read_run(_ctx("member"), run.id) is run

    async def test_a_member_does_not_read_a_colleagues_run(self):
        run = _run(_COLLEAGUE)
        with _stored(run) as service, pytest.raises(AuthorizationError, match="Insufficient"):
            await service.read_run(_ctx("member"), run.id)

    async def test_a_member_cannot_tell_a_missing_run_from_a_colleagues(self):
        with _stored(None) as service, pytest.raises(AuthorizationError, match="Insufficient"):
            await service.read_run(_ctx("member"), uuid.uuid4())

    async def test_a_key_does_not_read_its_issuers_run(self):
        run = _run()
        ctx = _ctx("member", api_key_id=uuid.uuid4(), key_scopes=frozenset({Perm.AGENTS_VIEW}))
        with _stored(run) as service, pytest.raises(AuthorizationError):
            await service.read_run(ctx, run.id)

    @pytest.mark.parametrize("role", ["owner", "admin", "operator"])
    async def test_whoever_holds_runs_view_still_reads_any_run(self, role):
        run = _run(_COLLEAGUE)
        with _stored(run) as service:
            assert await service.read_run(_ctx(role), run.id) is run


@contextmanager
def _retryable(run: AgentRun | None, service: AgentRunnerService):
    """What a retry reads and runs, patched at the repository boundary."""
    new_run = SimpleNamespace(
        id=uuid.uuid4(),
        conversation_id=run.conversation_id if run else None,
        status=RunStatus.COMPLETED.value,
        cost_usd=0,
        cost_is_partial=False,
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
    prompt = SimpleNamespace(id=uuid.uuid4(), role="user", content="send it", files=[])
    conversations = MagicMock(
        find_conversation=AsyncMock(return_value=MagicMock()),
        model_text=AsyncMock(return_value="send it"),
        model_history=AsyncMock(return_value=[]),
    )
    with (
        patch(f"{_MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=run)),
        patch("app.repositories.room_submission.for_run", new=AsyncMock(return_value=None)),
        patch.object(service, "get_run_transcript", new=AsyncMock(return_value=(run, [prompt], 1))),
        patch(f"{_MODULE}.ConversationService", return_value=conversations),
        patch(f"{_MODULE}.load_turn_attachments", new=AsyncMock(return_value=[])),
        patch(f"{_MODULE}.record_audit", new=AsyncMock()),
        patch.object(service, "parked_calls", new=AsyncMock(return_value=[])),
        patch.object(service, "execute", new=AsyncMock(return_value=("Done.", new_run))) as execute,
    ):
        yield execute


class TestRetryRun:
    async def _retry(self, ctx: AuthContext, run: AgentRun | None):
        service = AgentRunnerService(MagicMock())
        with _retryable(run, service) as execute:
            result = await service.retry_run(ctx, run.id if run else uuid.uuid4())
        return result, execute

    async def test_a_member_retries_their_own_run(self):
        run = _finished()

        result, execute = await self._retry(_ctx("member"), run)

        assert result.output == "Done."
        assert execute.await_args.kwargs["retry_of_run_id"] == run.id

    async def test_a_member_does_not_retry_a_colleagues_run(self):
        with pytest.raises(AuthorizationError, match="Insufficient permissions"):
            await self._retry(_ctx("member"), _finished(_COLLEAGUE))

    async def test_a_member_cannot_tell_a_missing_run_from_a_colleagues(self):
        with pytest.raises(AuthorizationError, match="Insufficient permissions"):
            await self._retry(_ctx("member"), None)

    async def test_an_operator_still_cannot_retry_a_colleagues_run(self):
        """`runs:view` opens a run to read, and the starter rule on retrying is unchanged."""
        with pytest.raises(AuthorizationError, match="who started this run"):
            await self._retry(_ctx("operator"), _finished(_COLLEAGUE))

    async def test_a_publishers_fallback_run_is_not_a_members_to_retry(self):
        run = _finished()
        run.initiated_by_publisher_fallback = True

        with pytest.raises(AuthorizationError, match="Insufficient permissions"):
            await self._retry(_ctx("member"), run)


class TestTheRunRoutes:
    """`GET /runs/{id}` and `POST /runs/{id}/retry` carry no gate, so the service is the gate."""

    @asynccontextmanager
    async def _client(self, ctx: AuthContext, runner: AgentRunnerService):
        app.dependency_overrides[deps.get_auth_context] = lambda: ctx
        app.dependency_overrides[deps.get_agent_runner_service] = lambda: runner
        app.dependency_overrides[deps.get_skill_service] = lambda: MagicMock(
            used_in_run=AsyncMock(return_value=[])
        )
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                yield client
        finally:
            app.dependency_overrides.clear()

    async def _open(self, ctx: AuthContext, run: AgentRun):
        runner = AgentRunnerService(MagicMock())
        with (
            patch(f"{_MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=run)),
            patch.object(runner, "down_rated_run_ids", new=AsyncMock(return_value=set())),
            patch.object(
                runner,
                "neighbor_run_ids",
                new=AsyncMock(return_value=(uuid.uuid4(), uuid.uuid4())),
            ) as neighbours,
            patch.object(
                runner, "trace_url", new=AsyncMock(return_value="https://trace.example/1")
            ) as trace,
        ):
            async with self._client(ctx, runner) as client:
                response = await client.get(f"/api/v1/runs/{run.id}")
        return response, neighbours, trace

    async def test_a_member_opens_their_own_run_without_the_trace_or_the_neighbours(self):
        run = _finished()

        response, neighbours, trace = await self._open(_ctx("member"), run)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["id"] == str(run.id)
        assert body["logfire_url"] is None
        assert body["prev_run_id"] is None and body["next_run_id"] is None
        neighbours.assert_not_awaited()
        trace.assert_not_awaited()

    async def test_an_operator_opening_a_run_still_gets_the_trace_and_the_neighbours(self):
        response, neighbours, trace = await self._open(_ctx("operator"), _finished(_COLLEAGUE))

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["logfire_url"] == "https://trace.example/1"
        assert body["prev_run_id"] is not None and body["next_run_id"] is not None

    async def test_a_member_cannot_open_a_colleagues_run(self):
        response, *_ = await self._open(_ctx("member"), _finished(_COLLEAGUE))

        assert response.status_code == 403

    async def test_a_member_retries_their_own_run_over_http(self):
        run = _finished()
        runner = AgentRunnerService(MagicMock())

        with _retryable(run, runner):
            async with self._client(_ctx("member"), runner) as client:
                response = await client.post(f"/api/v1/runs/{run.id}/retry")

        assert response.status_code == 200, response.text
        assert response.json()["output"] == "Done."

    async def test_a_member_cannot_retry_a_colleagues_run_over_http(self):
        run = _finished(_COLLEAGUE)
        runner = AgentRunnerService(MagicMock())

        with _retryable(run, runner) as execute:
            async with self._client(_ctx("member"), runner) as client:
                response = await client.post(f"/api/v1/runs/{run.id}/retry")

        assert response.status_code == 403
        execute.assert_not_awaited()


@contextmanager
def _turns(run: AgentRun | None, *, file=None):
    """A run's turns and one attachment, patched at the repository boundary."""
    with (
        patch(f"{_MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=run)),
        patch(f"{_MODULE}.conversation_repo.get_messages_by_run", new=AsyncMock(return_value=[])),
        patch(f"{_MODULE}.conversation_repo.count_messages_by_run", new=AsyncMock(return_value=0)),
        patch(
            f"{_MODULE}.conversation_repo.get_messages_by_conversation",
            new=AsyncMock(return_value=[]),
        ),
        patch(f"{_MODULE}.conversation_repo.count_messages", new=AsyncMock(return_value=0)),
        patch(f"{_MODULE}.chat_file_repo.get_in_conversation", new=AsyncMock(return_value=file)),
    ):
        yield AgentRunnerService(MagicMock())


class TestTheStartersTranscript:
    @pytest.mark.parametrize("whole_conversation", [False, True])
    async def test_a_member_reads_the_transcript_of_their_own_run(self, whole_conversation):
        run = _finished()
        with _turns(run) as service:
            read, items, total = await service.get_run_transcript(
                _ctx("member"), run.id, whole_conversation=whole_conversation
            )
        assert (read, items, total) == (run, [], 0)

    async def test_a_member_cannot_read_a_colleagues_transcript(self):
        run = _finished(_COLLEAGUE)
        with _turns(run) as service, pytest.raises(AuthorizationError, match="Insufficient"):
            await service.get_run_transcript(_ctx("member"), run.id)

    async def test_an_api_key_cannot_read_its_issuers_own_run(self):
        run = _finished()
        ctx = _ctx("member", api_key_id=uuid.uuid4(), key_scopes=frozenset({Perm.AGENTS_VIEW}))
        with _turns(run) as service, pytest.raises(AuthorizationError):
            await service.get_run_transcript(ctx, run.id)

    async def test_a_starter_demoted_to_viewer_cannot_read_it(self):
        run = _finished()
        with _turns(run) as service, pytest.raises(AuthorizationError):
            await service.get_run_transcript(_ctx("viewer"), run.id)

    async def test_a_publisher_fallback_run_is_not_the_publishers_to_read(self):
        run = _finished()
        run.initiated_by_publisher_fallback = True
        with _turns(run) as service, pytest.raises(AuthorizationError):
            await service.get_run_transcript(_ctx("member"), run.id)

    async def test_a_member_reads_an_attachment_of_their_own_run_only(self):
        mine, theirs = _finished(), _finished(_COLLEAGUE)
        file = MagicMock()
        with _turns(mine, file=file) as service:
            assert await service.get_run_attachment(_ctx("member"), mine.id, uuid.uuid4()) is file
        with _turns(theirs, file=file) as service, pytest.raises(AuthorizationError):
            await service.get_run_attachment(_ctx("member"), theirs.id, uuid.uuid4())

    async def test_the_manifest_stays_with_runs_view(self):
        """What the run handed its model is the agent's, not a part of the starter's conversation."""
        run = _finished()
        with _turns(run) as service, pytest.raises(AuthorizationError):
            await service.get_run_manifest(_ctx("member"), run.id)


class TestTheTranscriptRoute:
    """`GET /runs/{id}/transcript` builds the caller from the membership held *now*."""

    @asynccontextmanager
    async def _http(self, membership_role: str | None, run: AgentRun):
        from contextlib import ExitStack

        from app.db.models.organization import Organization, OrganizationMember
        from app.db.models.user import User
        from app.db.session import get_db_session

        org = Organization(id=run.organization_id, name="Acme", slug="acme")
        user = User(id=_MEMBER, email="starter@example.test", is_app_admin=False)
        membership = (
            None
            if membership_role is None
            else OrganizationMember(organization_id=org.id, user_id=user.id, role=membership_role)
        )
        db = MagicMock()
        runner = AgentRunnerService(db)
        app.dependency_overrides[deps.get_current_user] = lambda: user
        app.dependency_overrides[deps.get_active_organization] = lambda: org
        app.dependency_overrides[get_db_session] = lambda: db
        app.dependency_overrides[deps.get_agent_runner_service] = lambda: runner
        try:
            with ExitStack() as stack, _turns(run):
                for target, value in {
                    "app.api.deps._member_repo.get": AsyncMock(return_value=membership),
                    "app.api.deps.bind_table_access": AsyncMock(),
                }.items():
                    stack.enter_context(patch(target, new=value))
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    yield client
        finally:
            app.dependency_overrides.clear()

    async def test_a_member_reads_their_own_transcript_over_http(self):
        run = _finished()
        async with self._http("member", run) as client:
            response = await client.get(f"/api/v1/runs/{run.id}/transcript?scope=conversation")

        assert response.status_code == 200, response.text
        assert response.json()["run_id"] == str(run.id)

    async def test_a_member_cannot_read_a_colleagues_transcript_over_http(self):
        run = _finished(_COLLEAGUE)
        async with self._http("member", run) as client:
            response = await client.get(f"/api/v1/runs/{run.id}/transcript")

        assert response.status_code == 403

    async def test_a_starter_demoted_to_viewer_is_refused_over_http(self):
        run = _finished()
        async with self._http("viewer", run) as client:
            response = await client.get(f"/api/v1/runs/{run.id}/transcript")

        assert response.status_code == 403

    async def test_a_starter_removed_from_the_organization_is_refused_over_http(self):
        run = _finished()
        async with self._http(None, run) as client:
            response = await client.get(f"/api/v1/runs/{run.id}/transcript")

        assert response.status_code == 404
