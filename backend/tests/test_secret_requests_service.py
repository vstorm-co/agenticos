"""Tests for fulfilling and declining a secret request (#13).

The value is the whole test: every assertion below is that a sentinel
value, supplied as if a person pasted it into the card, appears nowhere
after fulfil or decline - not in the stored secret result, not in the
request row, not in the run's error, not in the transcript settlement, not
in the audit details, and not in any repr the endpoint could log. The vault
itself is mocked: sealing is `OrganizationSecretService`'s contract, tested
in `test_secrets.py`, and what is under test here is that this service hands
it the value and keeps nothing.
"""

import json
import uuid
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.core.secret_kinds import AwsCredentialsSecret, seal_secret, unseal_secret
from app.core.vault import VaultScope
from app.db.models.agent_run import ApprovalStatus, RunStatus
from app.schemas.agent import SecretRequestFulfil
from app.services.secret_requests import SecretRequestService

pytestmark = pytest.mark.anyio

SENTINEL = "sk-test-SENTINEL-VALUE-7f3a9c"

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
RUN_ID = uuid.uuid4()
REQUEST_ID = uuid.uuid4()


def _ctx() -> AuthContext:
    return AuthContext(user_id=USER_ID, organization_id=ORG_ID, role=OrgRoleName.OWNER)


def _run(**overrides):
    run = MagicMock()
    run.id = RUN_ID
    run.organization_id = ORG_ID
    run.user_id = USER_ID
    run.agent_id = uuid.uuid4()
    run.status = RunStatus.AWAITING_ANSWER.value
    run.surface = "web"
    run.paused_state = {
        "messages": [],
        "tool_call_ids": {},
        "questions": [],
        "secret_requests": ["call-1"],
    }
    run.input_tokens = 0
    run.output_tokens = 0
    run.cost_usd = 0
    run.cost_is_partial = False
    for key, value in overrides.items():
        setattr(run, key, value)
    return run


def _request(**overrides):
    request = MagicMock()
    request.id = REQUEST_ID
    request.run_id = RUN_ID
    request.organization_id = ORG_ID
    request.tool_call_id = "call-1"
    request.secret_name = "acme_api_key"
    request.kind = "api_key"
    request.what_for = "Acme CRM, to list contacts"
    request.status = "pending"
    request.fulfilled_secret_id = None
    request.fulfilled_hint = None
    request.created_at = None
    request.decided_at = None
    for key, value in overrides.items():
        setattr(request, key, value)
    return request


def _service() -> SecretRequestService:
    return SecretRequestService(MagicMock(), runner=MagicMock())


class TestFulfilBody:
    @pytest.mark.security
    def test_the_value_is_masked_in_the_schema_repr(self):
        data = SecretRequestFulfil(value=SENTINEL)

        assert SENTINEL not in repr(data)
        assert data.value.get_secret_value() == SENTINEL

    @pytest.mark.security
    def test_a_multiline_value_is_refused(self):
        with pytest.raises(ValueError, match="single line"):
            SecretRequestFulfil(value="line-one\nline-two")


@pytest.mark.security
async def test_fulfil_seals_the_value_and_keeps_only_name_and_hint() -> None:
    service = _service()
    run = _run()
    request = _request()
    created = MagicMock()
    created.id = uuid.uuid4()
    created.hint = "9c2f"
    segment = MagicMock()
    service.runner.resume = AsyncMock(return_value=segment)
    kept: dict = {}

    async def keep_paused_state(db, *, run, paused_state):
        kept.update(paused_state)
        return run

    with (
        patch(
            "app.services.secret_requests.agent_run_repo.claim_parked_run",
            AsyncMock(return_value=run),
        ),
        patch(
            "app.services.secret_requests.secret_request_repo.claim",
            AsyncMock(return_value=request),
        ),
        patch("app.services.secret_requests.OrganizationSecretService") as secret_service_cls,
        patch(
            "app.services.secret_requests.secret_request_repo.mark_decided",
            AsyncMock(return_value=request),
        ),
        patch("app.services.secret_requests.record_audit", AsyncMock()) as audit,
        patch(
            "app.services.secret_requests.agent_run_repo.keep_paused_state",
            AsyncMock(side_effect=keep_paused_state),
        ),
    ):
        secret_service_cls.return_value.create = AsyncMock(return_value=created)
        result = await service.fulfil(_ctx(), RUN_ID, REQUEST_ID, value=SecretStr(SENTINEL))

    assert result is segment
    # The vault got the value, and only the vault did.
    secret_service_cls.return_value.create.assert_awaited_once()
    _, kwargs = secret_service_cls.return_value.create.call_args
    assert kwargs["value"].api_key.get_secret_value() == SENTINEL
    assert kwargs["name"] == "acme_api_key"
    # Nothing kept carries it: the stored result, the audit details, the resume.
    assert SENTINEL not in str(kept)
    assert kept["secret_results"] == {
        "call-1": "Secret provided and stored: 'acme_api_key' (hint …9c2f). "
        "Continue the work; the credential is stored under that name. "
        "Never ask the user for its value."
    }
    assert SENTINEL not in str(audit.call_args)
    service.runner.resume.assert_awaited_once()


@pytest.mark.security
async def test_fulfil_round_trips_a_requested_non_api_key_kind() -> None:
    service = _service()
    run = _run()
    request = _request(kind="aws_credentials")
    created = MagicMock()
    created.id = uuid.uuid4()
    created.hint = "MPLE"
    service.runner.resume = AsyncMock(return_value=MagicMock())
    raw = json.dumps(
        {
            "kind": "aws_credentials",
            "aws_access_key_id": "AKIAEXAMPLE",
            "aws_secret_access_key": "sentinel-credential-value",
            "region_name": "us-east-1",
        }
    )

    with _fulfil_patches(service, run=run, request=request) as vault:
        vault.return_value.create = AsyncMock(return_value=created)
        await service.fulfil(_ctx(), RUN_ID, REQUEST_ID, value=SecretStr(raw))

    _, kwargs = vault.return_value.create.call_args
    secret = kwargs["value"]
    assert isinstance(secret, AwsCredentialsSecret)
    assert secret.aws_access_key_id == "AKIAEXAMPLE"
    assert secret.aws_secret_access_key.get_secret_value() == "sentinel-credential-value"
    assert secret.region_name == "us-east-1"
    assert "sentinel-credential-value" not in repr(secret)
    envelope = seal_secret(secret, scope=VaultScope.organization(ORG_ID))
    restored = unseal_secret(
        envelope.ciphertext, kind=secret.kind, scope=VaultScope.organization(ORG_ID)
    )
    assert isinstance(restored, AwsCredentialsSecret)
    assert restored.aws_secret_access_key.get_secret_value() == "sentinel-credential-value"


@pytest.mark.security
async def test_fulfil_while_another_secret_is_outstanding_stays_parked() -> None:
    service = _service()
    run = _run()
    run.paused_state["secret_requests"] = ["call-1", "call-2"]
    request = _request()
    created = MagicMock()
    created.id = uuid.uuid4()
    created.hint = "9c2f"
    service.runner.resume = AsyncMock()

    with (
        patch(
            "app.services.secret_requests.agent_run_repo.claim_parked_run",
            AsyncMock(return_value=run),
        ),
        patch(
            "app.services.secret_requests.secret_request_repo.claim",
            AsyncMock(return_value=request),
        ),
        patch("app.services.secret_requests.OrganizationSecretService") as secret_service_cls,
        patch(
            "app.services.secret_requests.secret_request_repo.mark_decided",
            AsyncMock(return_value=request),
        ),
        patch("app.services.secret_requests.record_audit", AsyncMock()),
        patch(
            "app.services.secret_requests.agent_run_repo.keep_paused_state",
            AsyncMock(return_value=run),
        ),
    ):
        secret_service_cls.return_value.create = AsyncMock(return_value=created)
        result = await service.fulfil(_ctx(), RUN_ID, REQUEST_ID, value=SecretStr(SENTINEL))

    assert result is None
    service.runner.resume.assert_not_awaited()


@pytest.mark.security
async def test_decline_ends_the_run_failed_without_the_value_anywhere() -> None:
    service = _service()
    run = _run()
    request = _request()
    transcript = MagicMock()
    transcript.record = AsyncMock()
    finished: dict = {}

    async def finish_run(db, **kwargs):
        finished.update(kwargs)
        return run

    async def mark_decided(db, *, request, status, decided_by_user_id, **_kwargs):
        request.status = status
        return request

    with (
        patch(
            "app.services.secret_requests.agent_run_repo.claim_parked_run",
            AsyncMock(return_value=run),
        ),
        patch(
            "app.services.secret_requests.secret_request_repo.claim",
            AsyncMock(return_value=request),
        ),
        patch(
            "app.services.secret_requests.TranscriptService",
            return_value=transcript,
        ),
        patch(
            "app.services.secret_requests.agent_run_repo.finish_run",
            AsyncMock(side_effect=finish_run),
        ),
        patch(
            "app.services.secret_requests.secret_request_repo.list_for_run",
            AsyncMock(return_value=[request]),
        ),
        patch(
            "app.services.secret_requests.secret_request_repo.mark_decided",
            AsyncMock(side_effect=mark_decided),
        ),
        patch("app.services.secret_requests.record_audit", AsyncMock()) as audit,
    ):
        read = await service.decline(_ctx(), RUN_ID, REQUEST_ID)

    assert read.status == "declined"
    assert finished["status"] == RunStatus.FAILED.value
    assert finished["error"] == (
        "User declined to provide secret 'acme_api_key' - the run cannot continue without it"
    )
    assert SENTINEL not in str(finished)
    assert SENTINEL not in str(transcript.record.call_args)
    assert transcript.record.call_args.kwargs["settled"] == {
        "call-1": (
            "The user declined to provide this secret. Do not ask for it again; "
            "end with a failed report explaining the run cannot continue without it."
        )
    }
    assert SENTINEL not in str(audit.call_args)
    assert SENTINEL not in repr(read)


from contextlib import contextmanager


@contextmanager
def _fulfil_patches(service, *, run, request, approvals=None):
    """The claim path a fulfil walks, with the vault and resume mocked.

    Yields the entered mocks in patch order, so a test that needs the
    vault mock can set its `create` return before calling fulfil.
    """
    service.runner.resume = AsyncMock(return_value=MagicMock())
    with (
        patch(
            "app.services.secret_requests.agent_run_repo.claim_parked_run",
            AsyncMock(return_value=run),
        ),
        patch(
            "app.services.secret_requests.secret_request_repo.claim",
            AsyncMock(return_value=request),
        ),
        patch(
            "app.services.secret_requests.agent_run_repo.list_approvals_for_run",
            AsyncMock(return_value=approvals or []),
        ),
        patch("app.services.secret_requests.OrganizationSecretService") as vault,
        patch(
            "app.services.secret_requests.secret_request_repo.mark_decided",
            AsyncMock(return_value=request),
        ),
        patch("app.services.secret_requests.record_audit", AsyncMock()),
        patch(
            "app.services.secret_requests.agent_run_repo.keep_paused_state",
            AsyncMock(return_value=run),
        ),
    ):
        yield vault


@pytest.mark.security
async def test_list_for_run_returns_nothing_for_another_person() -> None:
    service = _service()
    run = _run(user_id=uuid.uuid4())
    service.runner.get_run = AsyncMock(return_value=run)

    with patch(
        "app.services.secret_requests.secret_request_repo.list_for_run",
        AsyncMock(),
    ) as listed:
        assert (
            await service.list_for_run(
                _ctx(),
                RUN_ID,
            )
            == []
        )

    listed.assert_not_awaited()


@pytest.mark.security
async def test_list_for_run_returns_the_runs_requests_for_its_person() -> None:
    service = _service()
    run = _run()
    request = _request()
    service.runner.get_run = AsyncMock(return_value=run)

    with patch(
        "app.services.secret_requests.secret_request_repo.list_for_run",
        AsyncMock(return_value=[request]),
    ) as listed:
        reads = await service.list_for_run(_ctx(), RUN_ID)

    listed.assert_awaited_once()
    assert len(reads) == 1
    assert reads[0].secret_name == "acme_api_key"
    assert reads[0].what_for == "Acme CRM, to list contacts"
    assert reads[0].status == "pending"
    assert SENTINEL not in repr(reads[0])


@pytest.mark.security
async def test_fulfil_on_a_run_that_is_not_parked_is_not_found() -> None:
    service = _service()
    with (
        _fulfil_patches(service, run=None, request=_request()),
        pytest.raises(NotFoundError, match="Run not found"),
    ):
        await service.fulfil(_ctx(), RUN_ID, REQUEST_ID, value=SecretStr(SENTINEL))


@pytest.mark.security
async def test_fulfil_refuses_a_request_the_run_is_not_waiting_on() -> None:
    service = _service()
    run = _run()
    run.paused_state["secret_requests"] = ["call-other"]
    with (
        _fulfil_patches(service, run=run, request=_request()),
        pytest.raises(BadRequestError, match="not waiting on that secret request"),
    ):
        await service.fulfil(_ctx(), RUN_ID, REQUEST_ID, value=SecretStr(SENTINEL))


@pytest.mark.security
async def test_fulfil_refuses_while_a_question_is_unanswered() -> None:
    service = _service()
    run = _run()
    run.paused_state["questions"] = ["q-1"]
    run.paused_state["question_results"] = {}
    with (
        _fulfil_patches(service, run=run, request=_request()),
        pytest.raises(BadRequestError, match="before providing its secret"),
    ):
        await service.fulfil(_ctx(), RUN_ID, REQUEST_ID, value=SecretStr(SENTINEL))


@pytest.mark.security
async def test_fulfil_refuses_an_empty_or_oversized_value() -> None:
    service = _service()
    with (
        _fulfil_patches(service, run=_run(), request=_request()),
        pytest.raises(BadRequestError, match="Provide a secret value"),
    ):
        await service.fulfil(_ctx(), RUN_ID, REQUEST_ID, value=SecretStr("   "))
    with (
        _fulfil_patches(service, run=_run(), request=_request()),
        pytest.raises(BadRequestError, match="Provide a secret value"),
    ):
        await service.fulfil(_ctx(), RUN_ID, REQUEST_ID, value=SecretStr("x" * 8193))


@pytest.mark.security
async def test_fulfil_refuses_a_missing_or_wrong_run_request() -> None:
    service = _service()
    with (
        _fulfil_patches(service, run=_run(), request=None),
        pytest.raises(NotFoundError, match="Secret request not found"),
    ):
        await service.fulfil(_ctx(), RUN_ID, REQUEST_ID, value=SecretStr(SENTINEL))
    with (
        _fulfil_patches(service, run=_run(), request=_request(run_id=uuid.uuid4())),
        pytest.raises(NotFoundError, match="Secret request not found"),
    ):
        await service.fulfil(_ctx(), RUN_ID, REQUEST_ID, value=SecretStr(SENTINEL))


@pytest.mark.security
async def test_fulfil_refuses_an_already_decided_request() -> None:
    service = _service()
    with (
        _fulfil_patches(service, run=_run(), request=_request(status="fulfilled")),
        pytest.raises(BadRequestError, match="already decided"),
    ):
        await service.fulfil(_ctx(), RUN_ID, REQUEST_ID, value=SecretStr(SENTINEL))


@pytest.mark.security
async def test_fulfil_refuses_a_request_asked_of_somebody_else() -> None:
    service = _service()
    run = _run(user_id=uuid.uuid4())
    with (
        _fulfil_patches(service, run=run, request=_request()),
        pytest.raises(AuthorizationError, match="Only the person it asked"),
    ):
        await service.fulfil(_ctx(), RUN_ID, REQUEST_ID, value=SecretStr(SENTINEL))


@pytest.mark.security
async def test_fulfil_refuses_a_run_that_is_not_waiting() -> None:
    service = _service()
    run = _run(status=RunStatus.COMPLETED.value)
    with (
        _fulfil_patches(service, run=run, request=_request()),
        pytest.raises(BadRequestError, match="not waiting for a secret"),
    ):
        await service.fulfil(_ctx(), RUN_ID, REQUEST_ID, value=SecretStr(SENTINEL))


@pytest.mark.security
async def test_fulfil_refuses_a_run_parked_without_state() -> None:
    service = _service()
    run = _run(paused_state=None)
    with (
        _fulfil_patches(service, run=run, request=_request()),
        pytest.raises(BadRequestError, match="without the state needed"),
    ):
        await service.fulfil(_ctx(), RUN_ID, REQUEST_ID, value=SecretStr(SENTINEL))


@pytest.mark.security
async def test_fulfil_refuses_while_an_approval_is_still_pending() -> None:
    service = _service()
    run = _run(status=RunStatus.AWAITING_APPROVAL.value)
    pending = MagicMock()
    pending.status = ApprovalStatus.PENDING.value
    with (
        _fulfil_patches(service, run=run, request=_request(), approvals=[pending]),
        pytest.raises(BadRequestError, match="Decide the run's approvals"),
    ):
        await service.fulfil(_ctx(), RUN_ID, REQUEST_ID, value=SecretStr(SENTINEL))


@pytest.mark.security
async def test_fulfil_proceeds_once_the_approvals_are_decided() -> None:
    service = _service()
    run = _run(status=RunStatus.AWAITING_APPROVAL.value)
    decided = MagicMock()
    decided.status = ApprovalStatus.APPROVED.value
    created = MagicMock()
    created.id = uuid.uuid4()
    created.hint = "9c2f"
    with _fulfil_patches(service, run=run, request=_request(), approvals=[decided]) as vault:
        vault.return_value.create = AsyncMock(return_value=created)
        result = await service.fulfil(_ctx(), RUN_ID, REQUEST_ID, value=SecretStr(SENTINEL))

    assert result is service.runner.resume.return_value
    service.runner.resume.assert_awaited_once()


@pytest.mark.security
async def test_fulfil_refuses_a_workflow_run() -> None:
    service = _service()
    run = _run(surface="workflow")
    with (
        _fulfil_patches(service, run=run, request=_request()),
        pytest.raises(BadRequestError, match="through its workflow"),
    ):
        await service.fulfil(_ctx(), RUN_ID, REQUEST_ID, value=SecretStr(SENTINEL))


@pytest.mark.security
async def test_fulfil_refuses_an_api_key_on_a_person_started_run() -> None:
    service = _service()
    keyed = replace(_ctx(), api_key_id=uuid.uuid4(), key_scopes=frozenset(Perm))
    with (
        _fulfil_patches(service, run=_run(), request=_request()),
        pytest.raises(AuthorizationError, match="not with an API key"),
    ):
        await service.fulfil(keyed, RUN_ID, REQUEST_ID, value=SecretStr(SENTINEL))


@pytest.mark.security
async def test_fulfil_refuses_an_api_key_without_the_run_scope() -> None:
    service = _service()
    run = _run(user_id=None)
    keyed = AuthContext(
        user_id=None,
        organization_id=ORG_ID,
        role=OrgRoleName.OWNER,
        api_key_id=uuid.uuid4(),
        key_scopes=frozenset(),
    )
    with (
        _fulfil_patches(service, run=run, request=_request()),
        pytest.raises(AuthorizationError, match="may not run agents"),
    ):
        await service.fulfil(keyed, RUN_ID, REQUEST_ID, value=SecretStr(SENTINEL))


@pytest.mark.security
async def test_decline_on_a_run_that_is_not_parked_is_not_found() -> None:
    service = _service()
    with (
        patch(
            "app.services.secret_requests.agent_run_repo.claim_parked_run",
            AsyncMock(return_value=None),
        ),
        pytest.raises(NotFoundError, match="Run not found"),
    ):
        await service.decline(_ctx(), RUN_ID, REQUEST_ID)


@pytest.mark.security
async def test_decline_refuses_a_run_that_is_not_waiting() -> None:
    service = _service()
    run = _run(status=RunStatus.COMPLETED.value)
    with (
        patch(
            "app.services.secret_requests.agent_run_repo.claim_parked_run",
            AsyncMock(return_value=run),
        ),
        patch(
            "app.services.secret_requests.secret_request_repo.claim",
            AsyncMock(return_value=_request()),
        ),
        pytest.raises(BadRequestError, match="not waiting for a secret"),
    ):
        await service.decline(_ctx(), RUN_ID, REQUEST_ID)


@pytest.mark.security
async def test_decline_refuses_a_workflow_run() -> None:
    service = _service()
    run = _run(surface="workflow")
    with (
        patch(
            "app.services.secret_requests.agent_run_repo.claim_parked_run",
            AsyncMock(return_value=run),
        ),
        patch(
            "app.services.secret_requests.secret_request_repo.claim",
            AsyncMock(return_value=_request()),
        ),
        pytest.raises(BadRequestError, match="through its workflow"),
    ):
        await service.decline(_ctx(), RUN_ID, REQUEST_ID)


@pytest.mark.security
async def test_decline_refuses_while_an_approval_is_still_pending() -> None:
    service = _service()
    run = _run(status=RunStatus.AWAITING_APPROVAL.value)
    pending = MagicMock(status=ApprovalStatus.PENDING.value)
    with (
        patch(
            "app.services.secret_requests.agent_run_repo.claim_parked_run",
            AsyncMock(return_value=run),
        ),
        patch(
            "app.services.secret_requests.secret_request_repo.claim",
            AsyncMock(return_value=_request()),
        ),
        patch(
            "app.services.secret_requests.agent_run_repo.list_approvals_for_run",
            AsyncMock(return_value=[pending]),
        ),
        pytest.raises(BadRequestError, match="Decide the run's approvals"),
    ):
        await service.decline(_ctx(), RUN_ID, REQUEST_ID)


@pytest.mark.security
async def test_decline_refuses_an_api_key_on_a_person_started_run() -> None:
    service = _service()
    keyed = replace(_ctx(), api_key_id=uuid.uuid4(), key_scopes=frozenset(Perm))
    with (
        patch(
            "app.services.secret_requests.agent_run_repo.claim_parked_run",
            AsyncMock(return_value=_run()),
        ),
        patch(
            "app.services.secret_requests.secret_request_repo.claim",
            AsyncMock(return_value=_request()),
        ),
        pytest.raises(AuthorizationError, match="not with an API key"),
    ):
        await service.decline(keyed, RUN_ID, REQUEST_ID)


@pytest.mark.security
async def test_decline_refuses_an_api_key_without_the_run_scope() -> None:
    service = _service()
    run = _run(user_id=None)
    keyed = AuthContext(
        user_id=None,
        organization_id=ORG_ID,
        role=OrgRoleName.OWNER,
        api_key_id=uuid.uuid4(),
        key_scopes=frozenset(),
    )
    with (
        patch(
            "app.services.secret_requests.agent_run_repo.claim_parked_run",
            AsyncMock(return_value=run),
        ),
        patch(
            "app.services.secret_requests.secret_request_repo.claim",
            AsyncMock(return_value=_request()),
        ),
        pytest.raises(AuthorizationError, match="may not run agents"),
    ):
        await service.decline(keyed, RUN_ID, REQUEST_ID)


@pytest.mark.security
async def test_decline_declines_a_pending_sibling_with_the_run() -> None:
    service = _service()
    run = _run()
    request = _request()
    sibling = _request(id=uuid.uuid4(), tool_call_id="call-2", secret_name="other_key")
    transcript = MagicMock()
    transcript.record = AsyncMock()
    decided: list = []

    async def mark_decided(db, *, request, status, decided_by_user_id, **_kwargs):
        request.status = status
        decided.append(request.id)
        return request

    with (
        patch(
            "app.services.secret_requests.agent_run_repo.claim_parked_run",
            AsyncMock(return_value=run),
        ),
        patch(
            "app.services.secret_requests.secret_request_repo.claim",
            AsyncMock(return_value=request),
        ),
        patch(
            "app.services.secret_requests.TranscriptService",
            return_value=transcript,
        ),
        patch(
            "app.services.secret_requests.agent_run_repo.finish_run",
            AsyncMock(return_value=run),
        ),
        patch(
            "app.services.secret_requests.secret_request_repo.list_for_run",
            AsyncMock(return_value=[request, sibling]),
        ),
        patch(
            "app.services.secret_requests.secret_request_repo.mark_decided",
            AsyncMock(side_effect=mark_decided),
        ),
        patch("app.services.secret_requests.record_audit", AsyncMock()),
    ):
        read = await service.decline(_ctx(), RUN_ID, REQUEST_ID)

    assert read.status == "declined"
    assert sibling.status == "declined"
    assert decided == [REQUEST_ID, sibling.id]
    assert transcript.record.call_args.kwargs["settled"] == {
        "call-1": (
            "The user declined to provide this secret. Do not ask for it again; "
            "end with a failed report explaining the run cannot continue without it."
        )
    }
