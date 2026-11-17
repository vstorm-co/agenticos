"""Live ingress authenticates once and queues independent durable subscriber work."""

import contextlib
import hashlib
import hmac
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.core.vault import VaultScope, seal
from app.db.models.event_source import (
    EventDelivery,
    EventDispatch,
    EventSource,
    EventSourceCredential,
    EventSubscription,
)
from app.schemas.event_source import EventSourceCreate, SourceAuth, SourceCredentials
from app.services import event_sources as module
from app.services.event_sources import EventSourceService, credential_json

pytestmark = pytest.mark.anyio


@pytest.fixture
def ctx():
    return AuthContext(organization_id=uuid4(), user_id=uuid4(), role=OrgRoleName.MEMBER)


@pytest.fixture
def source(ctx):
    return EventSource(
        id=uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        name="Issues",
        provider="webhook",
        auth=SourceAuth().model_dump(),
        delivery_id_header=None,
        visibility="private",
        is_active=True,
        secret_id=uuid4(),
    )


@pytest.fixture
def db():
    session = AsyncMock()

    @contextlib.asynccontextmanager
    async def nested():
        yield

    session.begin_nested = MagicMock(side_effect=nested)
    return session


@pytest.fixture
def repos(source):
    sealed = seal(
        credential_json(SourceCredentials(secret=SecretStr("shared-secret"))),
        scope=VaultScope.organization(source.organization_id),
    )
    credential = EventSourceCredential(
        id=source.secret_id,
        organization_id=source.organization_id,
        sealed_secret=sealed.ciphertext,
        secret_key_version=sealed.key_version,
    )

    async def save(_db, row):
        if row.id is None:
            row.id = uuid4()
        return row

    with (
        patch.object(module.repo, "get", AsyncMock(return_value=source)),
        patch.object(module.repo, "credential", AsyncMock(return_value=credential)),
        patch.object(module.repo, "save", AsyncMock(side_effect=save)),
        patch.object(module.repo, "admit", AsyncMock(return_value=True)),
        patch.object(module.repo, "subscriptions", AsyncMock(return_value=[])),
        patch.object(module, "record_audit", AsyncMock()),
        patch.object(module, "enqueue", AsyncMock()) as queued,
    ):
        yield queued


def signed(body):
    return {
        "x-signature-256": "sha256=" + hmac.new(b"shared-secret", body, hashlib.sha256).hexdigest()
    }


async def test_receipt_retains_complete_json_and_no_auth_headers(db, source, repos):
    body = b'{"issue":{"body":"' + b"x" * 3000 + b'"},"flag":false}'
    _, receipt, admitted = await EventSourceService(db).receive(
        source.id, body=body, headers=signed(body) | {"authorization": "sensitive"}
    )
    assert admitted
    assert receipt.body["flag"] is False
    assert len(receipt.body["issue"]["body"]) == 3000
    assert receipt.headers == {}
    assert receipt.external_id is None


@pytest.mark.security
async def test_bad_auth_never_persists_or_queues(db, source, repos):
    with pytest.raises(AuthorizationError):
        await EventSourceService(db).receive(source.id, body=b"{}", headers={})
    module.repo.admit.assert_not_called()
    repos.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        b"[]",
        b"null",
        b"broken",
        b'"text"',
        b'{"number":NaN}',
        b'{"number":Infinity}',
        b'{"number":1e10000}',
        b'{"text":"\\u0000"}',
        b'{"text":"\\ud800"}',
    ],
)
async def test_malformed_authenticated_request_has_no_receipt(db, source, repos, body):
    with pytest.raises(BadRequestError):
        await EventSourceService(db).receive(source.id, body=body, headers=signed(body))
    module.repo.admit.assert_not_called()


async def test_duplicate_does_not_queue_any_subscriber(db, source, repos):
    module.repo.admit.return_value = False
    _, _, admitted = await EventSourceService(db).receive(
        source.id, body=b"{}", headers=signed(b"{}") | {"x-delivery-id": "same"}
    )
    assert not admitted
    repos.assert_not_called()


async def test_source_pause_still_authenticates_and_retains_receipt_without_dispatch(
    db, source, repos
):
    source.is_active = False
    _, _, admitted = await EventSourceService(db).receive(
        source.id, body=b"{}", headers=signed(b"{}")
    )
    assert admitted
    repos.assert_not_called()


async def test_each_active_subscriber_gets_its_own_job_in_the_receipt_transaction(
    db, source, repos
):
    subs = [
        EventSubscription(
            id=uuid4(),
            source_id=source.id,
            organization_id=source.organization_id,
            trigger_id=uuid4(),
        )
        for _ in range(3)
    ]
    module.repo.subscriptions.return_value = subs
    with patch.object(
        module.trigger_repo, "get_by_id", AsyncMock(return_value=MagicMock(is_active=True))
    ):
        _, receipt, _ = await EventSourceService(db).receive(
            source.id, body=b"{}", headers=signed(b"{}")
        )
    assert repos.await_count == 3
    assert len({call.args[2].dispatch_id for call in repos.await_args_list}) == 3
    dispatches = [call.args[1] for call in module.repo.save.await_args_list]
    assert {row.delivery_id for row in dispatches} == {receipt.id}
    db.commit.assert_not_called()


async def test_paused_target_gets_no_dispatch_even_if_it_resumes_before_worker(db, source, repos):
    module.repo.subscriptions.return_value = [
        EventSubscription(
            id=uuid4(),
            source_id=source.id,
            organization_id=source.organization_id,
            trigger_id=uuid4(),
        )
    ]
    with patch.object(
        module.trigger_repo, "get_by_id", AsyncMock(return_value=MagicMock(is_active=False))
    ):
        await EventSourceService(db).receive(source.id, body=b"{}", headers=signed(b"{}"))
    repos.assert_not_called()


async def test_static_api_key_is_never_a_deduplication_fingerprint(db, source, repos):
    source.auth = SourceAuth(
        method="api_key", header_name="x-api-key", signature_prefix=""
    ).model_dump()
    headers = {"x-api-key": "shared-secret"}
    _, first, _ = await EventSourceService(db).receive(source.id, body=b"{}", headers=headers)
    _, second, _ = await EventSourceService(db).receive(source.id, body=b"{}", headers=headers)
    assert first.external_id is second.external_id is None
    assert first.id != second.id


@pytest.mark.security
async def test_private_source_is_not_visible_to_another_member(db, ctx, source, repos):
    source.owner_user_id = uuid4()
    with (
        patch("app.services.access.resource_grant_repo.get_level", AsyncMock(return_value=None)),
        pytest.raises(NotFoundError),
    ):
        await EventSourceService(db).get(ctx, source.id)


@pytest.mark.security
async def test_tenant_mismatch_is_refused_even_for_owner(db, ctx, source, repos):
    source.organization_id = uuid4()
    with pytest.raises(NotFoundError):
        await EventSourceService(db).require_use(ctx, source.id)


async def test_source_read_contains_no_credential_or_vault_envelope(db, ctx, source, repos):
    read = await EventSourceService(db).read(ctx, source)
    result = read.model_dump_json()
    assert (
        "shared-secret" not in result
        and "sealed_secret" not in result
        and "secret_id" not in result
    )
    assert read.can_use and read.can_edit


@pytest.mark.security
async def test_credentials_are_sealed_and_only_generated_secret_is_revealed_once(
    db, ctx, source, repos
):
    created = await EventSourceService(db).create(ctx, EventSourceCreate(name="New"))
    assert created.reveal_secret
    stored = module.repo.save.await_args_list[0].args[1]
    assert created.reveal_secret not in stored.sealed_secret
    assert "secret" not in (await EventSourceService(db).read(ctx, source)).model_dump()


async def test_source_with_subscriptions_cannot_be_deleted(db, ctx, source, repos):
    module.repo.subscriptions.return_value = [EventSubscription(id=uuid4())]
    with pytest.raises(BadRequestError, match="Detach"):
        await EventSourceService(db).delete(ctx, source.id)


async def test_dispatch_failure_is_recorded_without_failing_other_jobs(db, source, repos):
    from app.services.agent_trigger import AgentTriggerService

    receipt = EventDelivery(
        id=uuid4(),
        source_id=source.id,
        organization_id=source.organization_id,
        body={"x": 1},
        headers={},
    )
    sub = EventSubscription(
        id=uuid4(), source_id=source.id, organization_id=source.organization_id, trigger_id=uuid4()
    )
    row = EventDispatch(
        id=uuid4(),
        organization_id=source.organization_id,
        delivery_id=receipt.id,
        subscription_id=sub.id,
        status="pending",
    )
    with (
        patch.object(module.repo, "dispatch", AsyncMock(return_value=row)),
        patch.object(module.repo, "delivery", AsyncMock(return_value=receipt)),
        patch.object(module.repo, "subscription", AsyncMock(return_value=sub)),
        patch.object(
            AgentTriggerService,
            "fire_source_delivery",
            AsyncMock(side_effect=AuthorizationError(message="Authority revoked")),
        ),
    ):
        await EventSourceService(db).dispatch(source.organization_id, row.id)
    assert row.status == "failed" and row.error_code == "AUTHORIZATION_ERROR"
    assert isinstance(row.completed_at, datetime)


async def test_worker_restart_does_not_readmit_a_completed_dispatch(db, source, repos):
    row = EventDispatch(id=uuid4(), status="admitted")
    with (
        patch.object(module.repo, "dispatch", AsyncMock(return_value=row)),
        patch.object(module.repo, "delivery", AsyncMock()) as read,
    ):
        await EventSourceService(db).dispatch(source.organization_id, row.id)
    read.assert_not_called()


async def test_deleted_subscription_skips_pending_dispatch(db, source, repos):
    receipt = EventDelivery(
        id=uuid4(), source_id=source.id, organization_id=source.organization_id, body={}, headers={}
    )
    row = EventDispatch(id=uuid4(), delivery_id=receipt.id, subscription_id=None, status="pending")
    with (
        patch.object(module.repo, "dispatch", AsyncMock(return_value=row)),
        patch.object(module.repo, "delivery", AsyncMock(return_value=receipt)),
    ):
        await EventSourceService(db).dispatch(source.organization_id, row.id)
    assert row.status == "skipped" and row.completed_at <= datetime.now(UTC)


@pytest.mark.parametrize("missing", ["source", "credentials"])
async def test_missing_ingress_configuration_refuses_receipt(db, source, repos, missing):
    if missing == "source":
        module.repo.get.return_value = None
    else:
        module.repo.credential.return_value = None
    with pytest.raises(NotFoundError):
        await EventSourceService(db).receive(source.id, body=b"{}", headers=signed(b"{}"))
    module.repo.admit.assert_not_called()


async def test_hubspot_batch_keeps_provider_adaptation_and_stable_event_identity(db, source, repos):
    source.provider = "hubspot"
    source.auth = SourceAuth(method="provider").model_dump()
    body = b'[{"eventId":1,"subscriptionId":2,"occurredAt":3}]'
    with patch.object(module, "verify_source", return_value=True):
        _, receipt, _ = await EventSourceService(db).receive(source.id, body=body, headers={})
    assert receipt.body == {"events": [{"eventId": 1, "subscriptionId": 2, "occurredAt": 3}]}
    assert receipt.external_id.startswith("hubspot:")


@pytest.mark.parametrize(
    "method,header", [("hmac", "x-provider-event"), ("standard_webhooks", "webhook-id")]
)
async def test_configured_and_standard_delivery_ids_remain_event_ids(
    db, source, repos, method, header
):
    source.auth = SourceAuth(method=method).model_dump()
    source.delivery_id_header = header if method == "hmac" else None
    with patch.object(module, "verify_source", return_value=True):
        _, receipt, _ = await EventSourceService(db).receive(
            source.id, body=b"{}", headers={header: "event-123", "x-github-event": "issues"}
        )
    assert receipt.external_id == "event-123"
    assert receipt.headers == {"x-github-event": "issues"}


async def test_long_delivery_identifier_is_refused_without_truncation_collision(db, source, repos):
    with pytest.raises(BadRequestError, match="255"):
        await EventSourceService(db).receive(
            source.id, body=b"{}", headers=signed(b"{}") | {"x-delivery-id": "a" * 256}
        )
    module.repo.admit.assert_not_called()


@pytest.mark.parametrize("target", [None, MagicMock(is_active=False)])
async def test_missing_or_paused_workflow_has_no_queued_dispatch(db, source, repos, target):
    module.repo.subscriptions.return_value = [
        EventSubscription(
            id=uuid4(),
            source_id=source.id,
            organization_id=source.organization_id,
            exposure_id=uuid4(),
        )
    ]
    with patch.object(module.exposure_repo, "get_by_id", AsyncMock(return_value=target)):
        await EventSourceService(db).receive(source.id, body=b"{}", headers=signed(b"{}"))
    repos.assert_not_called()


async def test_a_filtered_routine_marks_its_dispatch_skipped(db, source, repos):
    from app.services.agent_trigger import AgentTriggerService

    receipt = EventDelivery(
        id=uuid4(), source_id=source.id, organization_id=source.organization_id, body={}, headers={}
    )
    sub = EventSubscription(
        id=uuid4(), source_id=source.id, organization_id=source.organization_id, trigger_id=uuid4()
    )
    row = EventDispatch(
        id=uuid4(),
        organization_id=source.organization_id,
        delivery_id=receipt.id,
        subscription_id=sub.id,
        status="pending",
    )
    with (
        patch.object(module.repo, "dispatch", AsyncMock(return_value=row)),
        patch.object(module.repo, "delivery", AsyncMock(return_value=receipt)),
        patch.object(module.repo, "subscription", AsyncMock(return_value=sub)),
        patch.object(AgentTriggerService, "fire_source_delivery", AsyncMock(return_value=None)),
    ):
        await EventSourceService(db).dispatch(source.organization_id, row.id)
    assert row.status == "skipped"
